from __future__ import annotations
import asyncio
import base64
import io
import json
import logging
import os
import platform
import re
import textwrap
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar
from dotenv import load_dotenv
from google.api_core.exceptions import ResourceExhausted
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from lmnr import observe
from openai import RateLimitError
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ValidationError
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.prompts import AgentMessagePrompt, PlannerPrompt, SystemPrompt
from browser_use.agent.views import ActionResult, AgentError, AgentHistory, AgentHistoryList, AgentOutput, AgentStepInfo
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext
from browser_use.browser.views import BrowserState, BrowserStateHistory
from browser_use.controller.registry.views import ActionModel
from browser_use.controller.service import Controller
from browser_use.dom.history_tree_processor.service import DOMHistoryElement, HistoryTreeProcessor
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import AgentEndTelemetryEvent, AgentRunTelemetryEvent, AgentStepTelemetryEvent
from browser_use.utils import time_execution_async

load_dotenv()
logger = logging.getLogger(__name__)
T = TypeVar('T', bound=BaseModel)

class Agent:
	def __init__(
		self,
		task: str,
		llm: BaseChatModel,
		browser: Browser | None = None,
		browser_context: BrowserContext | None = None,
		controller: Controller = Controller(),
		use_vision: bool = True,
		use_vision_for_planner: bool = False,
		save_conversation_path: Optional[str] = None,
		save_conversation_path_encoding: Optional[str] = 'utf-8',
		max_failures: int = 3,
		retry_delay: int = 10,
		system_prompt_class: Type[SystemPrompt] = SystemPrompt,
		max_input_tokens: int = 128000,
		validate_output: bool = False,
		message_context: Optional[str] = None,
		generate_gif: bool | str = False,
		sensitive_data: Optional[Dict[str, str]] = None,
		include_attributes: list[str] = [
			'title', 'type', 'name', 'role', 'tabindex', 'aria-label', 
			'placeholder', 'value', 'alt', 'aria-expanded'
		],
		max_error_length: int = 400,
		max_actions_per_step: int = 10,
		tool_call_in_content: bool = True,
		initial_actions: Optional[List[Dict[str, Dict[str, Any]]]] = None,
		register_new_step_callback: Callable[['BrowserState', 'AgentOutput', int], None] | None = None,
		register_done_callback: Callable[['AgentHistoryList'], None] | None = None,
		tool_calling_method: Optional[str] = 'auto',
		page_extraction_llm: Optional[BaseChatModel] = None,
		planner_llm: Optional[BaseChatModel] = None,
		planner_interval: int = 1
	):
		self.agent_id = str(uuid.uuid4())
		self.sensitive_data = sensitive_data
		
		if not page_extraction_llm:
			self.page_extraction_llm = llm
		else:
			self.page_extraction_llm = page_extraction_llm
			
		self.task = task
		self.use_vision = use_vision
		self.use_vision_for_planner = use_vision_for_planner
		self.llm = llm
		self.save_conversation_path = save_conversation_path
		self.save_conversation_path_encoding = save_conversation_path_encoding
		self._last_result = None
		self.include_attributes = include_attributes
		self.max_error_length = max_error_length
		self.generate_gif = generate_gif
		self.planner_llm = planner_llm
		self.planning_interval = planner_interval
		self.last_plan = None
		self.controller = controller
		self.max_actions_per_step = max_actions_per_step
		self.injected_browser = browser is not None
		self.injected_browser_context = browser_context is not None
		self.message_context = message_context
		
		# Setup browser and browser context
		if browser is not None:
			self.browser = browser
		elif browser_context:
			self.browser = None
		else:
			self.browser = Browser()
			
		if browser_context:
			self.browser_context = browser_context
		elif self.browser:
			self.browser_context = BrowserContext(browser=self.browser, config=self.browser.config.new_context_config)
		else:
			self.browser = Browser()
			self.browser_context = BrowserContext(browser=self.browser)
		
		self.system_prompt_class = system_prompt_class
		self.telemetry = ProductTelemetry()
		
		# Setup actions and models
		self._setup_action_models()
		self._set_version_and_source()
		self.max_input_tokens = max_input_tokens
		self._set_model_names()
		
		self.tool_calling_method = self.set_tool_calling_method(tool_calling_method)
		
		# Initialize message manager
		self.message_manager = MessageManager(
			llm=self.llm,
			task=self.task,
			action_descriptions=self.controller.registry.get_prompt_description(),
			system_prompt_class=self.system_prompt_class,
			max_input_tokens=self.max_input_tokens,
			include_attributes=self.include_attributes,
			max_error_length=self.max_error_length,
			max_actions_per_step=self.max_actions_per_step,
			message_context=self.message_context,
			sensitive_data=self.sensitive_data
		)
		
		self.register_new_step_callback = register_new_step_callback
		self.register_done_callback = register_done_callback
		self.history = AgentHistoryList(history=[])
		self.n_steps = 1
		self.consecutive_failures = 0
		self.max_failures = max_failures
		self.retry_delay = retry_delay
		self.validate_output = validate_output
		
		if initial_actions:
			self.initial_actions = self._convert_initial_actions(initial_actions)
		else:
			self.initial_actions = None
			
		if save_conversation_path:
			logger.info(f'Saving conversation to {save_conversation_path}')
			
		self._paused = False
		self._stopped = False
		self.action_descriptions = self.controller.registry.get_prompt_description()

	def _set_version_and_source(self):
		try:
			import pkg_resources
			version = pkg_resources.get_distribution('browser-use').version
			source = 'pip'
		except Exception:
			try:
				import subprocess
				version = subprocess.check_output(['git', 'describe', '--tags']).decode('utf-8').strip()
				source = 'git'
			except Exception:
				version = 'unknown'
				source = 'unknown'
				
		logger.debug(f'Version: {version}, Source: {source}')
		self.version = version
		self.source = source
		
	def _set_model_names(self):
		self.chat_model_library = self.llm.__class__.__name__
		
		if hasattr(self.llm, 'model_name'):
			self.model_name = self.llm.model_name
		elif hasattr(self.llm, 'model'):
			self.model_name = self.llm.model
		else:
			self.model_name = 'Unknown'
			
		if self.planner_llm:
			if hasattr(self.planner_llm, 'model_name'):
				self.planner_model_name = self.planner_llm.model_name
			elif hasattr(self.planner_llm, 'model'):
				self.planner_model_name = self.planner_llm.model
			else:
				self.planner_model_name = 'Unknown'
		else:
			self.planner_model_name = None
			
	def _setup_action_models(self):
		"""Setup dynamic action models from controller's registry"""
		self.ActionModel = self.controller.registry.create_action_model()
		self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		
	def set_tool_calling_method(self, tool_calling_method):
		if tool_calling_method == 'auto':
			if self.chat_model_library == 'ChatGoogleGenerativeAI':
				return None
			elif self.chat_model_library == 'ChatOpenAI':
				return 'function_calling'
			elif self.chat_model_library == 'AzureChatOpenAI':
				return 'function_calling'
			else:
				return None
		else:
			return tool_calling_method
			
	def add_new_task(self, new_task):
		self.message_manager.add_new_task(new_task)
		
	def _check_if_stopped_or_paused(self):
		if self._stopped or self._paused:
			logger.debug('Agent paused after getting state')
			raise InterruptedError
		return False
		
	@observe(name='agent.step', ignore_output=True, ignore_input=True)
	@time_execution_async('--step')
	async def step(self, step_info: Optional[AgentStepInfo] = None):
		"""Execute one step of the task"""
		logger.info(f'📍 Step {self.n_steps}')
		
		state = None
		model_output = None
		result = []
		
		try:
			# Get browser state
			state = await self.browser_context.get_state()
			self._check_if_stopped_or_paused()
			
			# Add state to message history
			self.message_manager.add_state_message(state, self._last_result, step_info, self.use_vision)
			
			# Run planner at specified intervals if configured
			if self.planner_llm and self.n_steps % self.planning_interval == 0:
				plan = await self._run_planner()
				self.message_manager.add_plan(plan, position=-1)
				
			# Get all messages for model
			messages = self.message_manager.get_messages()
			self._check_if_stopped_or_paused()
			
			# Get next action from LLM
			model_output = await self.get_next_action(messages)
			
			# Callback if registered
			if self.register_new_step_callback:
				self.register_new_step_callback(state, model_output, self.n_steps)
				
			# Save conversation if path specified
			self._save_conversation(messages, model_output)
			
			# Remove state from history to avoid token bloat
			self.message_manager._remove_last_state_message()
			self._check_if_stopped_or_paused()
			
			# Add model output to message history
			self.message_manager.add_model_output(model_output)
			
		except Exception as e:
			# If message processing failed, remove state message
			self.message_manager._remove_last_state_message()
			raise e
			
		# Execute actions
		result = await self.controller.multi_act(
			model_output.action, 
			self.browser_context,
			self.page_extraction_llm,
			self.sensitive_data,
			check_break_if_paused=lambda: self._check_if_stopped_or_paused()
		)
		
		self._last_result = result
		
		# Check if task is done
		if len(result) > 0 and result[-1].is_done:
			logger.info(f'📄 Result: {result[-1].extracted_content}')
			
		# Reset failure counter on success
		self.consecutive_failures = 0
		
	async def _handle_step_error(self, error: Exception) -> list[ActionResult]:
		"""Handle all types of errors that can occur during a step"""
		include_trace = logger.isEnabledFor(logging.DEBUG)
		error_msg = AgentError.format_error(error, include_trace=include_trace)
		prefix = f'❌ Result failed {self.consecutive_failures + 1}/{self.max_failures} times:\n '
		
		if isinstance(error, (ValidationError, ValueError)):
			logger.error(f'{prefix}{error_msg}')
			
			if 'Max token limit reached' in error_msg:
				# Cut tokens from history
				self.message_manager.max_input_tokens = self.max_input_tokens - 500
				logger.info(f'Cutting tokens from history - new max input tokens: {self.message_manager.max_input_tokens}')
				self.message_manager.cut_messages()
			elif 'Could not parse response' in error_msg:
				# Add hint for proper response format
				error_msg += '\n\nReturn a valid JSON object with the required fields.'
				
			self.consecutive_failures += 1
			
		elif isinstance(error, RateLimitError) or isinstance(error, ResourceExhausted):
			logger.warning(f'{prefix}{error_msg}')
			await asyncio.sleep(self.retry_delay)
			self.consecutive_failures += 1
			
		else:
			logger.error(f'{prefix}{error_msg}')
			self.consecutive_failures += 1
			
		return [ActionResult(error=error_msg, include_in_memory=True)]
		
	def _make_history_item(self, model_output: AgentOutput | None, state: BrowserState, result: list[ActionResult]):
		"""Create and store history item"""
		interacted_elements = None
		num_results = len(result)
		
		if model_output:
			interacted_elements = AgentHistory.get_interacted_element(model_output, state.selector_map)
		else:
			interacted_elements = [None]
			
		browser_state_history = BrowserStateHistory(
			url=state.url, 
			title=state.title, 
			tabs=state.tabs, 
			interacted_element=interacted_elements, 
			screenshot=''
		)
		
		history_item = AgentHistory(
			model_output=model_output, 
			result=result, 
			state=browser_state_history
		)
		
		self.history.history.append(history_item)
		
	THINK_TAGS_REGEX = re.compile('<think>.*?</think>', re.DOTALL)
	
	def _remove_think_tags(self, text: str) -> str:
		"""Remove think tags from text"""
		return re.sub(self.THINK_TAGS_REGEX, '', text)
		
	def _convert_input_messages(self, input_messages: list[BaseMessage], model_name: Optional[str]) -> list[BaseMessage]:
		"""Convert input messages to a format that is compatible with the planner model"""
		if model_name is None:
			return input_messages
			
		if model_name == 'deepseek-reasoner' or model_name.startswith('deepseek-r1'):
			converted_messages = self.message_manager.convert_messages_for_non_function_calling_models(input_messages)
			merged_messages = self.message_manager.merge_successive_messages(converted_messages, HumanMessage)
			merged_messages = self.message_manager.merge_successive_messages(merged_messages, AIMessage)
			return merged_messages
			
		return input_messages
		
	@time_execution_async('--get_next_action')
	async def get_next_action(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get next action from LLM based on current state"""
		# Convert input messages to the appropriate format
		input_messages = self._convert_input_messages(input_messages, self.model_name)
		
		# Handle raw text completion models
		if self.model_name == 'deepseek-reasoner' or self.model_name.startswith('deepseek-r1'):
			model_response = self.llm.invoke(input_messages)
			model_response.content = self._remove_think_tags(model_response.content)
			
			try:
				extracted_json = self.message_manager.extract_json_from_model_output(model_response.content)
				parsed_output = self.AgentOutput(**extracted_json)
			except (ValueError, ValidationError) as e:
				logger.warning(f'Failed to parse model output: {model_response} {str(e)}')
				raise ValueError('Could not parse response.')
				
		# Handle structured output with function calling
		elif self.tool_calling_method is not None:
			structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True)
			response = await structured_llm.ainvoke(input_messages)
			parsed_output = response['parsed']
			
		else:
			structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True, method=self.tool_calling_method)
			response = await structured_llm.ainvoke(input_messages)
			parsed_output = response['parsed']
			
		if parsed_output is None:
			raise ValueError('Could not parse response.')
			
		# Limit the number of actions
		parsed_output.action = parsed_output.action[:self.max_actions_per_step]
		
		self._log_response(parsed_output)
		self.n_steps += 1
		
		return parsed_output
		
	def _log_response(self, response: AgentOutput) -> None:
		"""Log the model's response"""
		if 'Success' in response.current_state.evaluation_previous_goal:
			emoji = '👍'
		elif 'Failed' in response.current_state.evaluation_previous_goal:
			emoji = '⚠'
		else:
			emoji = '🤷'
			
		logger.debug(f'🤖 {emoji} Page summary: {response.current_state.page_summary}')
		logger.info(f'{emoji} Eval: {response.current_state.evaluation_previous_goal}')
		logger.info(f'🧠 Memory: {response.current_state.memory}')
		logger.info(f'🎯 Next goal: {response.current_state.next_goal}')
		
		for i, action in enumerate(response.action):
			logger.info(f'🛠️  Action {i + 1}/{len(response.action)}: {action.model_dump_json(exclude_unset=True)}')
		
	def _save_conversation(self, input_messages: list[BaseMessage], response: Any) -> None:
		"""Save conversation history to file if path is specified"""
		if not self.save_conversation_path:
			return None
			
		os.makedirs(os.path.dirname(self.save_conversation_path), exist_ok=True)
		
		with open(self.save_conversation_path + f'_{self.n_steps}.txt', 'w', encoding=self.save_conversation_path_encoding) as file:
			self._write_messages_to_file(file, input_messages)
			self._write_response_to_file(file, response)
			
	def _write_messages_to_file(self, file, messages: list[BaseMessage]) -> None:
		"""Write messages to conversation file"""
		for message in messages:
			file.write(f' {message.__class__.__name__} \n')
			
			if isinstance(message.content, list):
				for content_item in message.content:
					if isinstance(content_item, dict) and content_item.get('type') == 'text':
						file.write(content_item['text'].strip() + '\n')
			elif isinstance(message.content, str):
				try:
					parsed_content = json.loads(message.content)
					file.write(json.dumps(parsed_content, indent=2) + '\n')
				except json.JSONDecodeError:
					file.write(message.content.strip() + '\n')
					
			file.write('\n')
			
	def _write_response_to_file(self, file, response: Any) -> None:
		"""Write model response to conversation file"""
		file.write(' RESPONSE\n')
		file.write(json.dumps(json.loads(response.model_dump_json(exclude_unset=True)), indent=2))
		
	def _log_agent_run(self) -> None:
		"""Log the agent run"""
		logger.info(f'🚀 Starting task: {self.task}')
		logger.debug(f'Version: {self.version}, Source: {self.source}')
		
		self.telemetry.capture(
			AgentRunTelemetryEvent(
				agent_id=self.agent_id,
				use_vision=self.use_vision,
				task=self.task,
				model_name=self.model_name,
				chat_model_library=self.chat_model_library,
				version=self.version,
				source=self.source
			)
		)
		
	@observe(name='agent.run', ignore_output=True)
	@time_execution_async('--run')
	async def run(self, max_steps: int = 100) -> AgentHistoryList:
		"""Execute the task with maximum number of steps"""
		try:
			self._log_agent_run()
			
			# Execute initial actions if provided
			if self.initial_actions:
				result = await self.controller.multi_act(
					self.initial_actions,
					self.browser_context,
					False,
					self.page_extraction_llm,
					check_break_if_paused=lambda: self._check_if_stopped_or_paused()
				)
				self._last_result = result
				
			# Main execution loop
			for step in range(max_steps):
				# Check for too many failures
				if self._too_many_failures():
					break
					
				# Check control flags
				if not await self._handle_control_flags():
					break
					
				# Execute step
				await self.step()
				
				# Check if task is completed
				if self.history.is_done():
					# Validate output if enabled
					if self.validate_output and step < max_steps - 1:
						if not await self._validate_output():
							continue
							
					logger.info('✅ Task completed successfully')
					
					# Call done callback if registered
					if self.register_done_callback:
						self.register_done_callback(self.history)
						
					break
			else:
				logger.info('❌ Failed to complete task in maximum steps')
				
			return self.history
			
		except Exception:
			# Ensure proper cleanup on exception
			actions = [action.model_dump(exclude_unset=True) for action in model_output.action] if model_output else []
			
			self.telemetry.capture(
				AgentStepTelemetryEvent(
					agent_id=self.agent_id,
					step=self.n_steps,
					actions=actions,
					consecutive_failures=self.consecutive_failures,
					step_error=[r.error for r in result if r.error] if result else ['No result']
				)
			)
			
			if state:
				self._make_history_item(model_output, state, result)
				
			raise
			
		finally:
			# Capture telemetry
			actions = [action.model_dump(exclude_unset=True) for action in model_output.action] if model_output else []
			
			self.telemetry.capture(
				AgentEndTelemetryEvent(
					agent_id=self.agent_id,
					step=self.n_steps,
					actions=actions,
					consecutive_failures=self.consecutive_failures,
					step_error=[r.error for r in result if r.error] if result else ['No result']
				)
			)
			
			if state:
				self._make_history_item(model_output, state, result)
				
			# Close resources
			if not self.injected_browser_context:
				await self.browser_context.close()
				
			if not self.injected_browser and self.browser:
				await self.browser.close()
				
			# Generate GIF if enabled
			if self.generate_gif:
				output_path = 'agent_history.gif'
				if isinstance(self.generate_gif, str):
					output_path = self.generate_gif
					
				self.create_history_gif(output_path=output_path)
				
	def _too_many_failures(self) -> bool:
		"""Check if we should stop due to too many failures"""
		if self.consecutive_failures >= self.max_failures:
			logger.error(f'❌ Stopping due to {self.max_failures} consecutive failures')
			return True
		return False
		
	async def _handle_control_flags(self) -> bool:
		"""Handle pause and stop flags. Returns True if execution should continue."""
		if self._stopped:
			logger.debug('Agent stopped')
			return False
			
		while self._paused:
			await asyncio.sleep(0.2)  # Small delay to prevent CPU spinning
			if self._stopped:  # Allow stopping while paused
				return False
				
		return True
		
	async def _validate_output(self) -> bool:
		"""Validate the output of the last action is what the user wanted"""
		system_msg = (
			'You are a validator of an agent who interacts with a browser. '
			'Validate if the output of last action is what the user wanted and if the task is completed. '
			'If the task is unclear defined, you can let it pass. But if something is missing or the image does not show what was requested dont let it pass. '
			'Try to understand the page and help the model with suggestions like scroll, do x, ... to get the solution right. '
			f'Task to validate: {self.task}. Return a JSON object with 2 keys: is_valid and reason. '
			'is_valid is a boolean that indicates if the output is correct. '
			'reason is a string that explains why it is valid or not. '
			'example: {"is_valid": false, "reason": "The user wanted to search for "cat photos", but the agent searched for "dog photos" instead."}'
		)
		
		if not self.browser_context.session:
			return True
			
		state = await self.browser_context.get_state()
		prompt = AgentMessagePrompt(
			state=state,
			result=self._last_result,
			include_attributes=self.include_attributes,
			max_error_length=self.max_error_length
		)
		
		messages = [SystemMessage(content=system_msg), prompt.get_user_message(self.use_vision)]
		
		class ValidationResult(BaseModel):
			is_valid: bool
			reason: str
			
		validator = self.llm.with_structured_output(ValidationResult, include_raw=True)
		response = await validator.ainvoke(messages)
		parsed_result = response['parsed']
		
		is_valid = parsed_result.is_valid
		if not is_valid:
			logger.info(f'❌ Validator decision: {parsed_result.reason}')
			message = f'The output is not yet correct. {parsed_result.reason}.'
			self._last_result = [ActionResult(extracted_content=message, include_in_memory=True)]
		else:
			logger.info(f'✅ Validator decision: {parsed_result.reason}')
			
		return is_valid
		
	async def rerun_history(
		self,
		history: AgentHistoryList,
		max_retries: int = 3,
		skip_failures: bool = True,
		delay_between_actions: float = 2.0
	) -> list[ActionResult]:
		"""
		Rerun a saved history of actions with error handling and retry logic.

		Args:
			history: The history to replay
			max_retries: Maximum number of retries per action
			skip_failures: Whether to skip failed actions or stop execution
			delay_between_actions: Delay between actions in seconds

		Returns:
			List of action results
		"""
		if self.initial_actions:
			result = await self.controller.multi_act(
				self.initial_actions,
				self.browser_context,
				False,
				self.page_extraction_llm,
				check_break_if_paused=lambda: self._check_if_stopped_or_paused()
			)
			self._last_result = result
			
		results = []
		
		for i, history_item in enumerate(history.history):
			goal = history_item.model_output.current_state.next_goal if history_item.model_output else ''
			logger.info(f'Replaying step {i + 1}/{len(history.history)}: goal: {goal}')
			
			if not history_item.model_output or not history_item.model_output.action or history_item.model_output.action == [None]:
				logger.warning(f'Step {i + 1}: No action to replay, skipping')
				results.append(ActionResult(error='No action to replay'))
				continue
				
			retry_count = 0
			while retry_count < max_retries:
				try:
					result = await self._execute_history_step(history_item, delay_between_actions)
					results.extend(result)
					break
				except Exception as e:
					retry_count += 1
					if retry_count == max_retries:
						error_msg = f'Step {i + 1} failed after {max_retries} attempts: {str(e)}'
						logger.error(error_msg)
						if not skip_failures:
							results.append(ActionResult(error=error_msg))
							raise RuntimeError(error_msg)
					else:
						logger.warning(f'Step {i + 1} failed (attempt {retry_count}/{max_retries}), retrying...')
						await asyncio.sleep(delay_between_actions)
												
		return results
								
	async def _execute_history_step(self, history_item: AgentHistory, delay: float) -> list[ActionResult]:
		"""Execute a single step from history with element validation"""
		# Get current browser state
		state = await self.browser_context.get_state()
		
		if not state or not history_item.model_output:
			raise ValueError('Invalid state or model output')
			
		updated_actions = []
		
		# Update action indices based on current DOM structure
		for i, action in enumerate(history_item.model_output.action):
			updated_action = await self._update_action_indices(
				history_item.state.interacted_element[i],
				action,
				state
			)
			updated_actions.append(updated_action)
			
			if updated_action is None:
				raise ValueError(f'Could not find matching element {i} in current page')
				
		# Execute updated actions
		result = await self.controller.multi_act(
			updated_actions,
			self.browser_context,
			self.page_extraction_llm,
			check_break_if_paused=lambda: self._check_if_stopped_or_paused()
		)
		
		await asyncio.sleep(delay)
		return result
		
	async def _update_action_indices(
		self,
		historical_element: Optional[DOMHistoryElement],
		action: ActionModel, 
		current_state: BrowserState
	) -> Optional[ActionModel]:
		"""
		Update action indices based on current page state.
		Returns updated action or None if element cannot be found.
		"""
		if not historical_element or not current_state.element_tree:
			return action
			
		current_element = HistoryTreeProcessor.find_history_element_in_tree(
			historical_element, 
			current_state.element_tree
		)
		
		if not current_element or current_element.highlight_index is None:
			return None
			
		old_index = action.get_index()
		if old_index != current_element.highlight_index:
			action.set_index(current_element.highlight_index)
			logger.info(f'Element moved in DOM, updated index from {old_index} to {current_element.highlight_index}')
			
		return action
		
	async def load_and_rerun(self, history_file: Optional[str | Path] = None, **kwargs) -> list[ActionResult]:
		"""
		Load history from file and rerun it.

		Args:
			history_file: Path to the history file
			**kwargs: Additional arguments passed to rerun_history
		"""
		if not history_file:
			history_file = 'AgentHistory.json'
			
		history = AgentHistoryList.load_from_file(history_file, self.AgentOutput)
		return await self.rerun_history(history, **kwargs)
		
	def save_history(self, file_path: Optional[str | Path] = None) -> None:
		"""Save the history to a file"""
		if not file_path:
			file_path = 'AgentHistory.json'
			
		self.history.save_to_file(file_path)
		
	def create_history_gif(
		self,
		output_path: str = 'agent_history.gif',
		duration: int = 3000,
		show_goals: bool = True,
		show_task: bool = True,
		show_logo: bool = False,
		font_size: int = 40,
		title_font_size: int = 56,
		goal_font_size: int = 44,
		margin: int = 40,
		line_spacing: float = 1.5
	) -> None:
		"""Create a GIF from the agent's history with overlaid task and goal text."""
		if not self.history.history:
			logger.warning('No history to create GIF from')
			return None
			
		frames = []
		
		if not self.history.history or not self.history.history[0].state.screenshot:
			logger.warning('No history or first screenshot to create GIF from')
			return None
			
		# Try to find available fonts
		font_names = ['Helvetica', 'Arial', 'DejaVuSans', 'Verdana']
		font_found = False
		
		for font_name in font_names:
			try:
				if platform.system() == 'Windows':
					font_name = os.path.join(os.getenv('WIN_FONT_DIR', 'C:\\Windows\\Fonts'), font_name + '.ttf')
					
				regular_font = ImageFont.truetype(font_name, font_size)
				title_font = ImageFont.truetype(font_name, title_font_size)
				goal_font = ImageFont.truetype(font_name, goal_font_size)
				font_found = True
				break
			except OSError:
				continue
				
		if not font_found:
			try:
				regular_font = ImageFont.load_default()
				title_font = ImageFont.load_default()
				goal_font = ImageFont.load_default()
			except OSError:
				raise OSError('No preferred fonts found')
				
		# Try to load logo if enabled
		logo_image = None
		if show_logo:
			try:
				logo_path = os.path.join(os.path.dirname(__file__), 'assets/browser-use-logo.png')
				if os.path.exists(logo_path):
					logo_image = Image.open(logo_path)
					logo_image.thumbnail((150, 150))
			except Exception as e:
				logger.warning(f'Could not load logo: {e}')
				
		# Create task frame if enabled
		if show_task and self.task:
			task_frame = self._create_task_frame(
				self.task,
				self.history.history[0].state.screenshot,
				title_font,
				regular_font,
				logo_image,
				line_spacing
			)
			frames.append(task_frame)
			
		# Create frames for each step
		for i, history_item in enumerate(self.history.history[1:], 1):
			if not history_item.state.screenshot:
				continue
				
			# Decode screenshot
			image_data = base64.b64decode(history_item.state.screenshot)
			
			# Open image
			img = Image.open(io.BytesIO(image_data))
			
			# Add text overlay if goals are enabled
			if show_goals and history_item.model_output:
				img = self._add_overlay_to_image(
					image=img,
					step_number=i,
					goal_text=history_item.model_output.current_state.next_goal,
					regular_font=regular_font,
					title_font=title_font,
					margin=margin,
					logo=logo_image
				)
				
			frames.append(img)
			
		# Save as GIF
		if frames:
			frames[0].save(
				output_path,
				save_all=True,
				append_images=frames[1:],
				duration=duration,
				loop=0,
				optimize=False
			)
			logger.info(f'Created GIF at {output_path}')
		else:
			logger.warning('No images found in history to create GIF')
			
	def _create_task_frame(
		self,
		task: str,
		first_screenshot: str,
		title_font,
		regular_font,
		logo=None,
		line_spacing=1.5
	) -> Image.Image:
		"""Create initial frame showing the task."""
		# Decode screenshot
		screenshot_data = base64.b64decode(first_screenshot)
		screenshot_image = Image.open(io.BytesIO(screenshot_data))
		
		# Create black background
		background_image = Image.new('RGB', screenshot_image.size, (0, 0, 0))
		draw = ImageDraw.Draw(background_image)
		
		# Position variables
		center_y = background_image.height // 2
		margin_x = 140
		text_width = background_image.width - 2 * margin_x
		
		# Create larger font for task title
		task_title_font = ImageFont.truetype(regular_font.path, regular_font.size + 16)
		
		# Wrap text to fit width
		wrapped_text = self._wrap_text(task, task_title_font, text_width)
		line_height = task_title_font.size * line_spacing
		lines = wrapped_text.split('\n')
		total_text_height = line_height * len(lines)
		text_start_y = (center_y - total_text_height / 2) + 50
		
		# Draw each line of the task
		for line in lines:
			# Calculate text width for centering
			text_bbox = draw.textbbox((0, 0), line, font=task_title_font)
			text_start_x = (background_image.width - (text_bbox[2] - text_bbox[0])) // 2
			
			# Draw text
			draw.text(
				(text_start_x, text_start_y),
				line,
				font=task_title_font,
				fill=(255, 255, 255)
			)
			
			text_start_y += line_height
			
		# Add logo if available
		if logo:
			logo_margin = 20
			logo_x = background_image.width - logo.width - logo_margin
			background_image.paste(
				logo,
				(logo_x, logo_margin),
				logo if 'A' in logo.getbands() else None
			)
			
		return background_image
		
	def _add_overlay_to_image(
		self,
		image,
		step_number,
		goal_text,
		regular_font,
		title_font,
		margin,
		logo=None,
		display_step=True,
		text_color=(255, 255, 255, 255),
		text_box_color=(0, 0, 0, 255)
	) -> Image.Image:
		"""Add step number and goal overlay to an image."""
		# Convert to RGBA for transparency
		image = image.convert('RGBA')
		overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
		draw = ImageDraw.Draw(overlay)
		
		# Add step number if enabled
		if display_step:
			step_text = str(step_number)
			step_bbox = draw.textbbox((0, 0), step_text, font=title_font)
			step_width = step_bbox[2] - step_bbox[0]
			step_height = step_bbox[3] - step_bbox[1]
			
			# Position for step number
			step_x = margin + 10
			step_y = image.height - margin - step_height - 10
			padding = 20
			
			# Background for step number
			step_background_bbox = (
				step_x - padding,
				step_y - padding,
				step_x + step_width + padding,
				step_y + step_height + padding
			)
			
			draw.rounded_rectangle(step_background_bbox, radius=15, fill=text_box_color)
			draw.text((step_x, step_y), step_text, font=title_font, fill=text_color)
			
		# Add goal text
		text_width = image.width - 4 * margin
		wrapped_text = self._wrap_text(goal_text, title_font, text_width)
		
		# Get text dimensions
		text_bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=title_font)
		text_w = text_bbox[2] - text_bbox[0]
		text_h = text_bbox[3] - text_bbox[1]
		
		# Position for goal text
		text_x = (image.width - text_w) // 2
		text_y = step_y - text_h - padding * 4  # Use variables from step number section
		text_padding = 25
		
		# Background for goal text
		text_background_bbox = (
			text_x - text_padding,
			text_y - text_padding,
			text_x + text_w + text_padding,
			text_y + text_h + text_padding
		)
		
		draw.rounded_rectangle(text_background_bbox, radius=15, fill=text_box_color)
		draw.multiline_text(
			(text_x, text_y),
			wrapped_text,
			font=title_font,
			fill=text_color,
			align='center'
		)
		
		# Add logo if available
		if logo:
			logo_overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
			logo_margin = 20
			logo_x = image.width - logo.width - logo_margin
			logo_overlay.paste(
				logo,
				(logo_x, logo_margin),
				logo if logo.mode == 'RGBA' else None
			)
			overlay = Image.alpha_composite(logo_overlay, overlay)
			
		# Composite the overlay with the original image
		composite_image = Image.alpha_composite(image, overlay)
		return composite_image.convert('RGB')
		
	def _wrap_text(self, text: str, font, max_width: int) -> str:
		"""
		Wrap text to fit within a given width.

		Args:
			text: Text to wrap
			font: Font to use for text
			max_width: Maximum width in pixels

		Returns:
			Wrapped text with newlines
		"""
		words = text.split()
		lines = []
		current_line = []
		
		for word in words:
			current_line.append(word)
			line_text = ' '.join(current_line)
			line_bbox = font.getbbox(line_text)
			
			if line_bbox[2] > max_width:
				if len(current_line) == 1:
					# Single word is too long, just add it anyway
					lines.append(current_line.pop())
				else:
					# Remove last word and add the rest to wrapped lines
					current_line.pop()
					lines.append(' '.join(current_line))
					current_line = [word]
					
		if current_line:
			lines.append(' '.join(current_line))
			
		return '\n'.join(lines)
		
	def _create_frame(
		self,
		screenshot: str,
		text: str,
		step_number: int,
		width: int = 1200,
		height: int = 800
	) -> Image.Image:
		"""Create a frame for the GIF with improved styling"""
		# Create base image
		base_image = Image.new('RGB', (width, height), 'white')
		
		# Load screenshot
		screenshot_image = Image.open(BytesIO(base64.b64decode(screenshot)))
		screenshot_image.thumbnail((width - 40, height - 160))
		
		# Center screenshot
		screenshot_x = (width - screenshot_image.width) // 2
		screenshot_y = 120
		base_image.paste(screenshot_image, (screenshot_x, screenshot_y))
		
		# Try to load logo
		logo_size = 100
		logo_path = os.path.join(os.path.dirname(__file__), 'assets/browser-use-logo.png')
		
		if os.path.exists(logo_path):
			logo_image = Image.open(logo_path)
			logo_image.thumbnail((logo_size, logo_size))
			base_image.paste(
				logo_image,
				(width - logo_size - 20, 20),
				logo_image if 'A' in logo_image.getbands() else None
			)
			
		# Setup for drawing text
		draw = ImageDraw.Draw(base_image)
		
		try:
			title_font = ImageFont.truetype('Arial.ttf', 36)
			regular_font = ImageFont.truetype('Arial.ttf', 24)
			step_number_font = ImageFont.truetype('Arial.ttf', 48)
		except:
			# Fallback to default fonts
			title_font = ImageFont.load_default()
			regular_font = ImageFont.load_default()
			step_number_font = ImageFont.load_default()
			
		# Text positioning
		margin_x = 80
		text_width = width - 2 * margin_x
		padding = 20
		
		# Wrap text
		wrapped_text = textwrap.wrap(text, width=60)
		
		# Calculate text height
		total_text_height = sum(
			draw.textsize(line, font=regular_font)[1]
			for line in wrapped_text
		)
		
		text_area_height = total_text_height + 2 * padding
		
		# Create text area background
		text_area_bbox = [
			margin_x - padding,
			40,
			(width - margin_x) + padding,
			40 + text_area_height
		]
		
		draw.rounded_rectangle(text_area_bbox, radius=15, fill='#f0f0f0')
		
		# Add small logo to text area
		small_logo_size = 30
		if os.path.exists(logo_path):
			small_logo_image = Image.open(logo_path)
			small_logo_image.thumbnail((small_logo_size, small_logo_size))
			base_image.paste(
				small_logo_image,
				((margin_x - padding) + 10, 45),
				small_logo_image if 'A' in small_logo_image.getbands() else None
			)
			
		# Draw text
		text_y = 50
		for line in wrapped_text:
			draw.text(
				(margin_x + small_logo_size + 20, text_y),
				line,
				font=regular_font,
				fill='black'
			)
			text_y += draw.textsize(line, font=regular_font)[1] + 5
			
		# Add step number
		step_number_text = str(step_number)
		step_number_bbox = draw.textsize(step_number_text, font=step_number_font)
		step_number_padding = 20
		step_number_width = step_number_bbox[0] + 2 * step_number_padding
		step_number_height = step_number_bbox[1] + 2 * step_number_padding
		
		# Step number background
		step_number_background_bbox = [
			20,
			height - step_number_height - 20,
			20 + step_number_width,
			height - 20
		]
		
		draw.rounded_rectangle(step_number_background_bbox, radius=15, fill='#007AFF')
		
		# Calculate center position for step number
		step_number_x = step_number_background_bbox[0] + (step_number_width - step_number_bbox[0]) // 2
		step_number_y = step_number_background_bbox[1] + (step_number_height - step_number_bbox[1]) // 2
		
		# Draw step number
		draw.text(
			(step_number_x, step_number_y),
			step_number_text,
			font=step_number_font,
			fill='white'
		)
		
		return base_image
		
	def pause(self):
		"""Pause the agent before the next step"""
		logger.info('🔄 pausing Agent ')
		self._paused = True
		
	def resume(self):
		"""Resume the agent"""
		logger.info('▶️ Agent resuming')
		self._paused = False
		
	def stop(self):
		"""Stop the agent"""
		logger.info('⏹️ Agent stopping')
		self._stopped = True
		
	def _convert_initial_actions(self, actions: List[Dict[str, Dict[str, Any]]]) -> List[ActionModel]:
		"""Convert dictionary-based actions to ActionModel instances"""
		converted_actions = []
		action_model_instance = self.ActionModel  # Renamed for clarity
		for action_dict in actions:
			# Each action_dict should have a single key-value pair
			action_name = next(iter(action_dict))
			params = action_dict[action_name]

			# Get the parameter model for this action from registry
			action_info = self.controller.registry.registry.actions[action_name]
			param_model = action_info.param_model

			# Create validated parameters using the appropriate param model
			validated_params = param_model(**params)

			# Create ActionModel instance with the validated parameters
			action_model_instance = self.ActionModel(**{action_name: validated_params}) # Use the renamed variable
			converted_actions.append(action_model_instance)

		return converted_actions

	async def _run_planner(self) -> Optional[str]:
		"""Run the planner to analyze state and suggest next steps"""
		# Skip planning if no planner_llm is set
		if not self.planner_llm:
			return None

		# Create planner message history using full message history
		planner_messages = [
			PlannerPrompt(self.controller.registry.get_prompt_description()).get_system_message(),
			*self.message_manager.get_messages()[1:],  # Use full message history except the first
		]

		if not self.use_vision_for_planner and self.use_vision:
			last_state_message: HumanMessage = planner_messages[-1]
			# remove image from last state message
			new_message_content = ''
			if isinstance(last_state_message.content, list):
				for message_part in last_state_message.content:
					if message_part['type'] == 'text':  # type: ignore
						new_message_content += message_part['text']  # type: ignore
					elif message_part['type'] == 'image_url':  # type: ignore
						continue  # type: ignore
			else:
				new_message_content = last_state_message.content

			planner_messages[-1] = HumanMessage(content=new_message_content)

		planner_messages = self._convert_input_messages(planner_messages, self.planner_model_name)

		# Get planner output
		response = await self.planner_llm.ainvoke(planner_messages)
		plan = str(response.content)
		# if deepseek-reasoner, remove think tags
		if self.planner_model_name and ('deepseek-r1' in self.planner_model_name or 'deepseek-reasoner' in self.planner_model_name):
			plan = self._remove_think_tags(plan)
		try:
			plan_json = json.loads(plan)
			logger.info(f'Planning Analysis:\n{json.dumps(plan_json, indent=4)}')
		except json.JSONDecodeError:
			logger.info(f'Planning Analysis:\n{plan}')
		except Exception as error:
			logger.debug(f'Error parsing planning analysis: {error}')
			logger.info(f'Plan: {plan}')

		return plan

	@property
	def message_manager(self) -> MessageManager:
		return self._message_manager