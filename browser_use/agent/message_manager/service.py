from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Type
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from browser_use.agent.message_manager.views import MessageHistory, MessageMetadata
from browser_use.agent.prompts import AgentMessagePrompt, SystemPrompt
from browser_use.agent.views import ActionResult, AgentOutput, AgentStepInfo, MessageManagerState
from browser_use.browser.views import BrowserState
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MessageManagerSettings(BaseModel):
    max_input_tokens: int = 128000
    estimated_characters_per_token: int = 3
    image_tokens: int = 800
    include_attributes: List[str] = []
    message_context: Optional[str] = None
    sensitive_data: Optional[Dict[str, str]] = None
    available_file_paths: Optional[List[str]] = None


class MessageManager:
    def __init__(
        self,
        llm: Optional[BaseChatModel] = None,
        task: str = "",
        action_descriptions: Optional[List[str]] = None,
        system_prompt_class: Optional[Type[SystemPrompt]] = None,
        max_input_tokens: int = 128000,
        estimated_characters_per_token: int = 3,
        image_tokens: int = 800,
        include_attributes: Optional[List[str]] = None,
        max_error_length: int = 100,
        max_actions_per_step: int = 5,
        message_context: Optional[str] = None,
        sensitive_data: Optional[Dict[str, str]] = None,
        system_message: Optional[SystemMessage] = None,
        settings: Optional[MessageManagerSettings] = None,
        state: Optional[MessageManagerState] = None,
    ):
        # Support both old and new initialization patterns
        if settings is not None:
            # New style initialization
            self.task = task
            self.settings = settings
            self.state = state or MessageManagerState()
            self.system_prompt = system_message
            # Only initialize messages if state is empty
            if len(self.state.history.messages) == 0:
                self._init_messages()
        else:
            # Old style initialization
            self.llm = llm
            self.system_prompt_class = system_prompt_class
            self.max_input_tokens = max_input_tokens
            self.history = MessageHistory()
            self.task = task
            self.action_descriptions = action_descriptions or []
            self.estimated_characters_per_token = estimated_characters_per_token
            self.IMG_TOKENS = image_tokens
            self.include_attributes = include_attributes or []
            self.max_error_length = max_error_length
            self.message_context = message_context
            self.sensitive_data = sensitive_data
            self.tool_id = 1

            # Initialize with system prompt
            system_message = self.system_prompt_class(
                self.action_descriptions,
                max_actions_per_step=max_actions_per_step
            ).get_system_message()
            self._add_message_with_tokens(system_message)
            self.system_prompt = system_message

            # Add context message if provided
            if self.message_context:
                context_message = HumanMessage(content='Context for the task' + self.message_context)
                self._add_message_with_tokens(context_message)

            # Add task instructions
            task_message = self.task_instructions(task)
            self._add_message_with_tokens(task_message)

            # Add sensitive data information if provided
            if self.sensitive_data:
                info = f"Here are placeholders for sensitve data: {list(self.sensitive_data.keys())}"
                info += "To use them, write <secret>the placeholder name</secret>"
                info_message = HumanMessage(content=info)
                self._add_message_with_tokens(info_message)

            # Add example output placeholder
            placeholder_message = HumanMessage(content="Example output:")
            self._add_message_with_tokens(placeholder_message)

            # Add example tool call
            tool_calls = [
                {
                    'name': 'AgentOutput',
                    'args': {
                        'current_state': {
                            'page_summary': 'On the page are company a,b,c wtih their revenue 1,2,3.',
                            'evaluation_previous_goal': 'Success - I opend the first page',
                            'memory': 'Starting with the new task. I have completed 1/10 steps',
                            'next_goal': 'Click on company a'
                        },
                        'action': [
                            {
                                'click_element': {
                                    'index': 0
                                }
                            }
                        ]
                    },
                    'id': str(self.tool_id),
                    'type': 'tool_call'
                }
            ]
            example_ai_message = AIMessage(content='', tool_calls=tool_calls)
            self._add_message_with_tokens(example_ai_message)

            example_tool_message = ToolMessage(content='Browser started', tool_call_id=str(self.tool_id))
            self._add_message_with_tokens(example_tool_message)
            self.tool_id += 1

            memory_message = HumanMessage(content='[Your task history memory starts here]')
            self._add_message_with_tokens(memory_message)

    def _init_messages(self) -> None:
        """Initialize the message history with system message, context, task, and other initial messages"""
        self._add_message_with_tokens(self.system_prompt)

        if self.settings.message_context:
            context_message = HumanMessage(content='Context for the task' + self.settings.message_context)
            self._add_message_with_tokens(context_message)

        task_message = HumanMessage(
            content=f'Your ultimate task is: """{self.task}""". If you achieved your ultimate task, stop everything and use the done action in the next step to complete the task. If not, continue as usual.'
        )
        self._add_message_with_tokens(task_message)

        if self.settings.sensitive_data:
            info = f'Here are placeholders for sensitve data: {list(self.settings.sensitive_data.keys())}'
            info += 'To use them, write <secret>the placeholder name</secret>'
            info_message = HumanMessage(content=info)
            self._add_message_with_tokens(info_message)

        placeholder_message = HumanMessage(content='Example output:')
        self._add_message_with_tokens(placeholder_message)

        tool_calls = [
            {
                'name': 'AgentOutput',
                'args': {
                    'current_state': {
                        'evaluation_previous_goal': 'Success - I opend the first page',
                        'memory': 'Starting with the new task. I have completed 1/10 steps',
                        'next_goal': 'Click on company a',
                    },
                    'action': [{'click_element': {'index': 0}}],
                },
                'id': str(self.state.tool_id),
                'type': 'tool_call',
            }
        ]
        example_tool_call = AIMessage(content='', tool_calls=tool_calls)
        self._add_message_with_tokens(example_tool_call)
        self.add_tool_message(content='Browser started')

        placeholder_message = HumanMessage(content='[Your task history memory starts here]')
        self._add_message_with_tokens(placeholder_message)

        if self.settings.available_file_paths:
            filepaths_msg = HumanMessage(content=f'Here are file paths you can use: {self.settings.available_file_paths}')
            self._add_message_with_tokens(filepaths_msg)

    def task_instructions(self, task: str) -> HumanMessage:
        """Format task instructions as a human message."""
        content = f'''Your ultimate task is: """{task}""". If you achieved your ultimate task, stop everything and use the done action in the next step to complete the task. If not, continue as usual.'''
        return HumanMessage(content=content)

    def add_new_task(self, new_task: str) -> None:
        """Add a new task to the conversation."""
        content = f'''Your new ultimate task is: """{new_task}""". Take the previous context into account and finish your new ultimate task. '''
        msg = HumanMessage(content=content)
        self._add_message_with_tokens(msg)
        if hasattr(self, 'settings'):
            self.task = new_task

    def add_plan(self, plan: Optional[str], position: Optional[int] = None) -> None:
        """Add a plan as an AI message at the specified position."""
        if plan:
            msg = AIMessage(content=plan)
            self._add_message_with_tokens(msg, position)

    def add_state_message(
        self,
        state: BrowserState,
        result: Optional[List[ActionResult]] = None,
        step_info: Optional[AgentStepInfo] = None,
        use_vision: bool = True
    ) -> None:
        """Add browser state as human message"""
        if hasattr(self, 'settings'):
            if result:
                for r in result:
                    if r.include_in_memory:
                        if r.extracted_content:
                            msg = HumanMessage(content='Action result: ' + str(r.extracted_content))
                            self._add_message_with_tokens(msg)
                        if r.error:
                            if r.error.endswith('\n'):
                                r.error = r.error[:-1]
                            last_line = r.error.split('\n')[-1]
                            msg = HumanMessage(content='Action error: ' + last_line)
                            self._add_message_with_tokens(msg)
                        result = None
            state_message = AgentMessagePrompt(
                state,
                result,
                include_attributes=self.settings.include_attributes,
                step_info=step_info,
            ).get_user_message(use_vision)
            self._add_message_with_tokens(state_message)
        else:
            if result:
                for r in result:
                    if r.include_in_memory:
                        if r.extracted_content:
                            msg = HumanMessage(content='Action result: ' + str(r.extracted_content))
                            self._add_message_with_tokens(msg)
                        if r.error:
                            error = r.error[:self.max_error_length] if len(r.error) > self.max_error_length else r.error
                            if error.endswith('\n'):
                                error = error[:-1]
                            last_line = error.split('\n')[-1]
                            msg = HumanMessage(content='Action error: ' + last_line)
                            self._add_message_with_tokens(msg)
                        result = None
            state_message = AgentMessagePrompt(
                state,
                result,
                include_attributes=self.include_attributes,
                step_info=step_info,
            ).get_user_message(use_vision)
            self._add_message_with_tokens(state_message)

    def _remove_last_state_message(self) -> None:
        """Remove last state message from history"""
        if hasattr(self, 'state'):
            self.state.history.remove_last_state_message()
        else:
            if len(self.history.messages) > 2 and isinstance(self.history.messages[-1].message, HumanMessage):
                self.history.remove_message()

    def add_model_output(self, model_output: AgentOutput) -> None:
        """Add model output as AI message"""
        if hasattr(self, 'state'):
            tool_calls = [
                {
                    'name': 'AgentOutput',
                    'args': model_output.model_dump(mode='json', exclude_unset=True),
                    'id': str(self.state.tool_id),
                    'type': 'tool_call',
                }
            ]
            msg = AIMessage(content='', tool_calls=tool_calls)
            self._add_message_with_tokens(msg)
            self.add_tool_message(content='')
        else:
            tool_calls = [
                {
                    'name': 'AgentOutput',
                    'args': model_output.model_dump(mode='json', exclude_unset=True),
                    'id': str(self.tool_id),
                    'type': 'tool_call'
                }
            ]
            msg = AIMessage(content='', tool_calls=tool_calls)
            self._add_message_with_tokens(msg)
            tool_msg = ToolMessage(content='', tool_call_id=str(self.tool_id))
            self._add_message_with_tokens(tool_msg)
            self.tool_id += 1

    def add_tool_message(self, content: str) -> None:
        """Add tool message to history"""
        if hasattr(self, 'state'):
            msg = ToolMessage(content=content, tool_call_id=str(self.state.tool_id))
            self.state.tool_id += 1
            self._add_message_with_tokens(msg)
        else:
            msg = ToolMessage(content=content, tool_call_id=str(self.tool_id))
            self.tool_id += 1
            self._add_message_with_tokens(msg)

    def get_messages(self) -> List[BaseMessage]:
        """Get current message list, potentially trimmed to max tokens"""
        if hasattr(self, 'state'):
            messages = [m.message for m in self.state.history.messages]
            total_input_tokens = 0
            logger.debug(f'Messages in history: {len(self.state.history.messages)}:')
            for m in self.state.history.messages:
                total_input_tokens += m.metadata.tokens
                logger.debug(f'{m.message.__class__.__name__} - Token count: {m.metadata.tokens}')
            logger.debug(f'Total input tokens: {total_input_tokens}')
            return messages
        else:
            messages = [m.message for m in self.history.messages]
            total_tokens = 0
            logger.debug(f'Messages in history: {len(self.history.messages)}:')
            for m in self.history.messages:
                total_tokens += m.metadata.input_tokens
                logger.debug(f'{m.message.__class__.__name__} - Token count: {m.metadata.input_tokens}')
            logger.debug(f'Total input tokens: {total_tokens}')
            return messages

    def _add_message_with_tokens(self, message: BaseMessage, position: Optional[int] = None) -> None:
        """Add message with token count metadata
        position: None for last, -1 for second last, etc.
        """
        if hasattr(self, 'settings'):
            if self.settings.sensitive_data:
                message = self._filter_sensitive_data(message)
            token_count = self._count_tokens(message)
            metadata = MessageMetadata(tokens=token_count)
            self.state.history.add_message(message, metadata, position)
        else:
            if self.sensitive_data:
                message = self._filter_sensitive_data(message)
            token_count = self._count_tokens(message)
            metadata = MessageMetadata(input_tokens=token_count)
            self.history.add_message(message, metadata, position)

    def _filter_sensitive_data(self, message: BaseMessage) -> BaseMessage:
        """Filter out sensitive data from the message"""
        if hasattr(self, 'settings'):
            def replace_sensitive(value: str) -> str:
                if not self.settings.sensitive_data:
                    return value
                for key, val in self.settings.sensitive_data.items():
                    if not val:
                        continue
                    value = value.replace(val, f'<secret>{key}</secret>')
                return value

            if isinstance(message.content, str):
                message.content = replace_sensitive(message.content)
            elif isinstance(message.content, list):
                for i, item in enumerate(message.content):
                    if isinstance(item, dict) and 'text' in item:
                        item['text'] = replace_sensitive(item['text'])
                        message.content[i] = item
        else:
            def replace_sensitive(value: str) -> str:
                if not self.sensitive_data:
                    return value
                for key, val in self.sensitive_data.items():
                    if not val:
                        continue
                    value = value.replace(val, f'<secret>{key}</secret>')
                return value

            if isinstance(message.content, str):
                message.content = replace_sensitive(message.content)
            elif isinstance(message.content, list):
                for i, item in enumerate(message.content):
                    if isinstance(item, dict) and 'text' in item:
                        item['text'] = replace_sensitive(item['text'])
                        message.content[i] = item
        return message

    def _count_tokens(self, message: BaseMessage) -> int:
        """Count tokens in a message using the model's tokenizer"""
        tokens = 0
        if hasattr(self, 'settings'):
            if isinstance(message.content, list):
                for item in message.content:
                    if 'image_url' in item:
                        tokens += self.settings.image_tokens
                    elif isinstance(item, dict) and 'text' in item:
                        tokens += self._count_text_tokens(item['text'])
            else:
                msg = message.content
                if hasattr(message, 'tool_calls'):
                    msg += str(message.tool_calls)
                tokens += self._count_text_tokens(msg)
        else:
            if isinstance(message.content, list):
                for item in message.content:
                    if 'image_url' in item:
                        tokens += self.IMG_TOKENS
                    elif isinstance(item, dict) and 'text' in item:
                        tokens += self._count_text_tokens(item['text'])
            else:
                msg = message.content
                if hasattr(message, 'tool_calls'):
                    msg += str(message.tool_calls)
                tokens += self._count_text_tokens(msg)
        return tokens

    def _count_text_tokens(self, text: str) -> int:
        """Count tokens in a text string"""
        if hasattr(self, 'settings'):
            tokens = len(text) // self.settings.estimated_characters_per_token
        else:
            tokens = len(text) // self.estimated_characters_per_token
        return tokens

    def cut_messages(self):
        """Get current message list, potentially trimmed to max tokens"""
        if hasattr(self, 'state'):
            diff = self.state.history.current_tokens - self.settings.max_input_tokens
            if diff <= 0:
                return None

            msg = self.state.history.messages[-1]

            if isinstance(msg.message.content, list):
                text = ""
                for item in list(msg.message.content):
                    if 'image_url' in item:
                        msg.message.content.remove(item)
                        diff -= self.settings.image_tokens
                        msg.metadata.tokens -= self.settings.image_tokens
                        self.state.history.current_tokens -= self.settings.image_tokens
                        logger.debug(
                            f"Removed image with {self.settings.image_tokens} tokens - total tokens now: {self.state.history.current_tokens}/{self.settings.max_input_tokens}"
                        )
                    elif 'text' in item and isinstance(item, dict):
                        text += item['text']
                msg.message.content = text
                self.state.history.messages[-1] = msg

            if diff <= 0:
                return None

            proportion_to_remove = diff / msg.metadata.tokens
            if proportion_to_remove > 0.99:
                raise ValueError(
                    f"Max token limit reached - history is too long - reduce the system prompt or task. proportion_to_remove: {proportion_to_remove}"
                )
            logger.debug(
                f"Removing {proportion_to_remove * 100:.2f}% of the last message  {proportion_to_remove * msg.metadata.tokens:.2f} / {msg.metadata.tokens:.2f} tokens)"
            )

            content = msg.message.content
            characters_to_remove = int(len(content) * proportion_to_remove)
            content = content[:-characters_to_remove]

            self.state.history.remove_last_state_message()

            msg = HumanMessage(content=content)
            self._add_message_with_tokens(msg)

            last_msg = self.state.history.messages[-1]
            logger.debug(
                f"Added message with {last_msg.metadata.tokens} tokens - total tokens now: {self.state.history.current_tokens}/{self.settings.max_input_tokens} - total messages: {len(self.state.history.messages)}"
            )
        else:
            diff = self.history.total_tokens - self.max_input_tokens
            if diff <= 0:
                return None

            msg = self.history.messages[-1]

            if isinstance(msg.message.content, list):
                text = ""
                for item in list(msg.message.content):
                    if 'image_url' in item:
                        msg.message.content.remove(item)
                        diff -= self.IMG_TOKENS
                        msg.metadata.input_tokens -= self.IMG_TOKENS
                        self.history.total_tokens -= self.IMG_TOKENS
                        logger.debug(
                            f"Removed image with {self.IMG_TOKENS} tokens - total tokens now: {self.history.total_tokens}/{self.max_input_tokens}"
                        )
                    elif 'text' in item and isinstance(item, dict):
                        text += item['text']
                msg.message.content = text
                self.history.messages[-1] = msg

            if diff <= 0:
                return None

            proportion_to_remove = diff / msg.metadata.input_tokens
            if proportion_to_remove > 0.99:
                raise ValueError(
                    f"Max token limit reached - history is too long - reduce the system prompt or task. proportion_to_remove: {proportion_to_remove}"
                )
            logger.debug(
                f"Removing {proportion_to_remove * 100:.2f}% of the last message ({proportion_to_remove * msg.metadata.input_tokens:.2f} / {msg.metadata.input_tokens:.2f} tokens)"
            )

            content = msg.message.content
            characters_to_remove = int(len(content) * proportion_to_remove)
            content = content[:-characters_to_remove]

            self._remove_last_state_message()

            msg = HumanMessage(content=content)
            self._add_message_with_tokens(msg)

            last_msg = self.history.messages[-1]
            logger.debug(
                f"Added message with {last_msg.metadata.input_tokens} tokens - total tokens now: {self.history.total_tokens}/{self.max_input_tokens} - total messages: {len(self.history.messages)}"
            )

    def extract_json_from_model_output(self, content: str) -> dict:
        """Extract JSON from model output, handling both plain JSON and code-block-wrapped JSON."""
        if "```" in content:
            content = content.split("```")[1]
            if "\n" in content:
                content = content.split("\n", 1)[1]
        return json.loads(content)

    def convert_messages_for_non_function_calling_models(self, input_messages: List[BaseMessage]) -> List[BaseMessage]:
        """Convert messages for non-function-calling models"""
        converted_messages = []
        for msg in input_messages:
            if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                tool_call = msg.tool_calls[0]
                content = json.dumps(tool_call.get('args', {}), indent=2)
                converted_messages.append(AIMessage(content=content))
            else:
                converted_messages.append(msg)
        return converted_messages

    def merge_successive_messages(self, messages: List[BaseMessage], class_to_merge: Type[BaseMessage]) -> List[BaseMessage]:
        """Some models like deepseek-reasoner dont allow multiple human messages in a row. This function merges them into one."""
        merged_messages = []
        buffer = ""
        buffer_items = 0

        for i, msg in enumerate(messages):
            if isinstance(msg, class_to_merge):
                if buffer_items > 0 and i < len(messages) - 1 and isinstance(messages[i+1], class_to_merge):
                    buffer += "\n\n" + msg.content
                    buffer_items += 1
                elif buffer_items > 0:
                    buffer += "\n\n" + msg.content
                    merged_messages.append(class_to_merge(content=buffer))
                    buffer = ""
                    buffer_items = 0
                else:
                    if i < len(messages) - 1 and isinstance(messages[i+1], class_to_merge):
                        buffer = msg.content
                        buffer_items = 1
                    else:
                        merged_messages.append(msg)
            else:
                if buffer_items > 0:
                    merged_messages.append(class_to_merge(content=buffer))
                    buffer = ""
                    buffer_items = 0
                merged_messages.append(msg)

        if buffer_items > 0:
            merged_messages.append(class_to_merge(content=buffer))
        return merged_messages
