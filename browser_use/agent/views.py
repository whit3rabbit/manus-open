from __future__ import annotations

import json
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Type

from langchain_core.language_models.chat_models import BaseChatModel
from openai import RateLimitError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.browser.views import BrowserStateHistory
from browser_use.controller.registry.views import ActionModel
from browser_use.dom.history_tree_processor.service import (
    DOMElementNode,
    DOMHistoryElement,
    HistoryTreeProcessor,
)
from browser_use.dom.views import SelectorMap

ToolCallingMethod = Literal['function_calling', 'json_mode', 'raw', 'auto']


class AgentSettings(BaseModel):
    """Options for the agent"""

    use_vision: bool = True
    use_vision_for_planner: bool = False
    save_conversation_path: Optional[str] = None
    save_conversation_path_encoding: Optional[str] = 'utf-8'
    max_failures: int = 3
    retry_delay: int = 10
    max_input_tokens: int = 128000
    validate_output: bool = False
    message_context: Optional[str] = None
    generate_gif: bool | str = False
    available_file_paths: Optional[List[str]] = None
    override_system_message: Optional[str] = None
    extend_system_message: Optional[str] = None
    include_attributes: List[str] = [
        'title',
        'type',
        'name',
        'role',
        'tabindex',
        'aria-label',
        'placeholder',
        'value',
        'alt',
        'aria-expanded',
    ]
    max_error_length: int = 100
    max_actions_per_step: int = 10

    tool_calling_method: Optional[ToolCallingMethod] = 'auto'
    page_extraction_llm: Optional[BaseChatModel] = None
    planner_llm: Optional[BaseChatModel] = None
    planner_interval: int = 1  # Run planner every N steps


class AgentState(BaseModel):
    """Holds all state information for an Agent"""

    agent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    n_steps: int = 1
    consecutive_failures: int = 0
    last_result: Optional[List[ActionResult]] = None
    history: AgentHistoryList = Field(default_factory=lambda: AgentHistoryList(history=[]))
    last_plan: Optional[str] = None
    paused: bool = False
    stopped: bool = False

    message_manager_state: MessageManagerState = Field(default_factory=MessageManagerState)

    model_config = ConfigDict(arbitrary_types_allowed=True)


@dataclass
class AgentStepInfo:
    """Information about the current step in the agent's execution"""
    step_number: int
    max_steps: int

    def is_last_step(self) -> bool:
        """Check if this is the last step"""
        return self.step_number >= self.max_steps - 1


class ActionResult(BaseModel):
    """Result of executing an action"""

    is_done: Optional[bool] = False
    success: Optional[bool] = None
    extracted_content: Optional[str] = None
    error: Optional[str] = None
    include_in_memory: bool = False
    should_show_markdown: bool = False


class StepMetadata(BaseModel):
    """Metadata for a single step including timing and token information"""

    step_start_time: float
    step_end_time: float
    input_tokens: int
    step_number: int

    @property
    def duration_seconds(self) -> float:
        """Calculate step duration in seconds"""
        return self.step_end_time - self.step_start_time


class AgentBrain(BaseModel):
    """Current state of the agent"""

    page_summary: str
    evaluation_previous_goal: str
    memory: str
    next_goal: str


class AgentOutput(BaseModel):
    """Output model for agent

    @dev note: this model is extended with custom actions in AgentService. You can also use some fields
    that are not in this model as provided by the linter, as long as they are registered in the DynamicActions model.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    current_state: AgentBrain
    action: List[ActionModel] = Field(
        ...,
        description='List of actions to execute',
        json_schema_extra={'min_items': 1},
    )

    @staticmethod
    def type_with_custom_actions(custom_actions: Type[ActionModel]) -> Type[AgentOutput]:
        """Extend actions with custom actions"""
        model_ = create_model(
            'AgentOutput',
            __base__=AgentOutput,
            action=(
                List[custom_actions],
                Field(..., description='List of actions to execute', json_schema_extra={'min_items': 1}),
            ),
            __module__=AgentOutput.__module__,
        )
        model_.__doc__ = 'AgentOutput model with custom actions'
        return model_


class AgentHistory(BaseModel):
    """History item for agent actions"""

    model_output: Optional[AgentOutput]
    result: List[ActionResult]
    state: BrowserStateHistory
    metadata: Optional[StepMetadata] = None

    model_config = ConfigDict(arbitrary_types_allowed=True, protected_namespaces=())

    @staticmethod
    def get_interacted_element(model_output: AgentOutput, selector_map: SelectorMap) -> List[Optional[DOMHistoryElement]]:
        """Extract interacted elements from model output and selector map"""
        elements = []
        for action in model_output.action:
            index = action.get_index()
            if index is not None and index in selector_map:
                el: DOMElementNode = selector_map[index]
                elements.append(HistoryTreeProcessor.convert_dom_element_to_history_element(el))
            else:
                elements.append(None)
        return elements

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """Custom serialization handling circular references"""
        model_output_dump = None
        if self.model_output:
            action_dump = [action.model_dump(exclude_none=True) for action in self.model_output.action]
            model_output_dump = {
                'current_state': self.model_output.current_state.model_dump(),
                'action': action_dump,
            }
        return {
            'model_output': model_output_dump,
            'result': [r.model_dump(exclude_none=True) for r in self.result],
            'state': self.state.to_dict(),
            'metadata': self.metadata.model_dump() if self.metadata else None,
        }


class AgentHistoryList(BaseModel):
    """List of agent history items"""

    history: List[AgentHistory]

    def total_duration_seconds(self) -> float:
        total = 0.0
        for h in self.history:
            if h.metadata:
                total += h.metadata.duration_seconds
        return total

    def total_input_tokens(self) -> int:
        total = 0
        for h in self.history:
            if h.metadata:
                total += h.metadata.input_tokens
        return total

    def input_token_usage(self) -> List[int]:
        return [h.metadata.input_tokens for h in self.history if h.metadata]

    def __str__(self) -> str:
        return f'AgentHistoryList(all_results={self.action_results()}, all_model_outputs={self.model_actions()})'

    def __repr__(self) -> str:
        return self.__str__()

    def save_to_file(self, filepath: str | Path) -> None:
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            data = self.model_dump()
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            raise e

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        return {
            'history': [h.model_dump(**kwargs) for h in self.history],
        }

    @classmethod
    def load_from_file(cls, filepath: str | Path, output_model: Type[AgentOutput]) -> AgentHistoryList:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for h in data['history']:
            if h['model_output']:
                if isinstance(h['model_output'], dict):
                    h['model_output'] = output_model.model_validate(h['model_output'])
                else:
                    h['model_output'] = None
            if 'interacted_element' not in h['state']:
                h['state']['interacted_element'] = None
        history = cls.model_validate(data)
        return history

    def last_action(self) -> Optional[dict]:
        if self.history and self.history[-1].model_output:
            return self.history[-1].model_output.action[-1].model_dump(exclude_none=True)
        return None

    def errors(self) -> List[Optional[str]]:
        errors = []
        for h in self.history:
            step_errors = [r.error for r in h.result if r.error]
            errors.append(step_errors[0] if step_errors else None)
        return errors

    def final_result(self) -> Optional[str]:
        if self.history and self.history[-1].result and self.history[-1].result[-1].extracted_content:
            return self.history[-1].result[-1].extracted_content
        return None

    def is_done(self) -> bool:
        if self.history and len(self.history[-1].result) > 0:
            last_result = self.history[-1].result[-1]
            return last_result.is_done is True
        return False

    def is_successful(self) -> Optional[bool]:
        if self.history and len(self.history[-1].result) > 0:
            last_result = self.history[-1].result[-1]
            if last_result.is_done is True:
                return last_result.success
        return None

    def has_errors(self) -> bool:
        return any(error is not None for error in self.errors())

    def urls(self) -> List[Optional[str]]:
        return [h.state.url if h.state.url is not None else None for h in self.history]

    def screenshots(self) -> List[Optional[str]]:
        return [h.state.screenshot if h.state.screenshot is not None else None for h in self.history]

    def action_names(self) -> List[str]:
        action_names = []
        for action in self.model_actions():
            actions = list(action.keys())
            if actions:
                action_names.append(actions[0])
        return action_names

    def model_thoughts(self) -> List[AgentBrain]:
        return [h.model_output.current_state for h in self.history if h.model_output]

    def model_outputs(self) -> List[AgentOutput]:
        return [h.model_output for h in self.history if h.model_output]

    def model_actions(self) -> List[dict]:
        outputs = []
        for h in self.history:
            if h.model_output:
                for action, interacted_element in zip(h.model_output.action, h.state.interacted_element):
                    output = action.model_dump(exclude_none=True)
                    output['interacted_element'] = interacted_element
                    outputs.append(output)
        return outputs

    def action_results(self) -> List[ActionResult]:
        results = []
        for h in self.history:
            results.extend([r for r in h.result if r])
        return results

    def extracted_content(self) -> List[str]:
        content = []
        for h in self.history:
            content.extend([r.extracted_content for r in h.result if r.extracted_content])
        return content

    def model_actions_filtered(self, include: Optional[List[str]] = None) -> List[dict]:
        if include is None:
            include = []
        outputs = self.model_actions()
        result = []
        for o in outputs:
            # Check if the first key matches one of the include list items
            if o and list(o.keys())[0] in include:
                result.append(o)
        return result

    def number_of_steps(self) -> int:
        return len(self.history)


class AgentError:
    """Container for agent error handling"""

    VALIDATION_ERROR = 'Invalid model output format. Please follow the correct schema.'
    RATE_LIMIT_ERROR = 'Rate limit reached. Waiting before retry.'
    NO_VALID_ACTION = 'No valid action found'

    @staticmethod
    def format_error(error: Exception, include_trace: bool = False) -> str:
        """Format error message based on error type and optionally include trace"""
        if isinstance(error, ValidationError):
            return f'{AgentError.VALIDATION_ERROR}\nDetails: {str(error)}'
        if isinstance(error, RateLimitError):
            return AgentError.RATE_LIMIT_ERROR
        if include_trace:
            return f'{str(error)}\nStacktrace:\n{traceback.format_exc()}'
        return str(error)
