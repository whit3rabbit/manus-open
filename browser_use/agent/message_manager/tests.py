import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.prompts import SystemPrompt
from browser_use.agent.views import ActionResult, AgentStepInfo
from browser_use.browser.views import BrowserState, TabInfo
from browser_use.dom.views import DOMElementNode, DOMTextNode

@pytest.fixture(params=[
    ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0),
    ChatAnthropic(model_name="claude-2", temperature=0),
    None  # Also test with no LLM for robustness
])
def message_manager(request):
    """Create a message manager with different LLM backends"""
    llm = request.param
    task = "Test task"
    action_descriptions = "Test actions"
    
    return MessageManager(
        llm=llm,
        task=task,
        action_descriptions=action_descriptions,
        system_prompt_class=SystemPrompt,
        max_input_tokens=1000,
        estimated_characters_per_token=3,
        image_tokens=800,
        include_attributes=True,
        max_error_length=500,
        max_actions_per_step=5,
        message_context=None,
        sensitive_data=None
    )

def test_initial_messages(message_manager):
    """Test that message manager initializes with system and task messages"""
    messages = message_manager.get_messages()
    
    # There should be several initial messages
    assert len(messages) >= 3
    
    # First message should be the system prompt
    assert isinstance(messages[0], SystemMessage)
    
    # There should be at least one human message containing the task description.
    human_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
    assert any("Test task" in msg.content for msg in human_messages)
    
    # There should be at least one AI message (e.g. example output or tool call).
    ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]
    assert len(ai_messages) > 0

def test_add_state_message(message_manager):
    """Test adding browser state message"""
    browser_state = BrowserState(
        url="https://test.com",
        title="Test Page",
        element_tree=DOMElementNode(
            tag_name="div",
            attributes={},
            children=[],
            is_visible=True,
            parent=None,
            xpath="//div"
        ),
        selector_map={},
        tabs=[TabInfo(page_id=1, url="https://test.com", title="Test Page")]
    )
    
    initial_message_count = len(message_manager.get_messages())
    
    message_manager.add_state_message(
        browser_state, 
        None,  # No result provided
        AgentStepInfo(step=1),
        use_vision=False
    )
    
    messages = message_manager.get_messages()
    
    # Expect one additional message to be added.
    assert len(messages) == initial_message_count + 1
    
    # The newly added message should be a HumanMessage containing state information.
    assert isinstance(messages[-1], HumanMessage)
    assert "Current browser state" in messages[-1].content
    assert "https://test.com" in messages[-1].content
    assert "Test Page" in messages[-1].content

def test_add_state_with_memory_result(message_manager):
    """Test adding state with a result that should be included in memory"""
    browser_state = BrowserState(
        url="https://test.com",
        title="Test Page",
        element_tree=DOMElementNode(
            tag_name="div",
            attributes={},
            children=[],
            is_visible=True,
            parent=None,
            xpath="//div"
        ),
        selector_map={},
        tabs=[TabInfo(page_id=1, url="https://test.com", title="Test Page")]
    )
    
    action_result = [ActionResult(
        extracted_content="Important content",
        include_in_memory=True
    )]
    
    message_manager.add_state_message(
        browser_state, 
        action_result,
        AgentStepInfo(step=1),
        use_vision=False
    )
    
    messages = message_manager.get_messages()
    
    # The resulting state message should include the important content.
    assert "Important content" in messages[-1].content
    # And when memory inclusion is enabled, it should mark the content (e.g. with "Extracted:" or similar).
    assert "Extracted:" in messages[-1].content

def test_add_state_with_non_memory_result(message_manager):
    """Test adding state with a result that should not be included in memory"""
    browser_state = BrowserState(
        url="https://test.com",
        title="Test Page",
        element_tree=DOMElementNode(
            tag_name="div",
            attributes={},
            children=[],
            is_visible=True,
            parent=None,
            xpath="//div"
        ),
        selector_map={},
        tabs=[TabInfo(page_id=1, url="https://test.com", title="Test Page")]
    )
    
    action_result = [ActionResult(
        extracted_content="Temporary content",
        include_in_memory=False
    )]
    
    message_manager.add_state_message(
        browser_state, 
        action_result,
        AgentStepInfo(step=1),
        use_vision=False
    )
    
    messages = message_manager.get_messages()
    
    # The message should still include the temporary content.
    assert "Temporary content" in messages[-1].content
    # And its presentation should indicate that it was not retained in memory.
    assert "Extracted:" in messages[-1].content

def test_token_overflow_handling_with_real_flow(message_manager):
    """Test handling of token overflow in a realistic message flow"""
    # Force a low token limit to trigger overflow handling.
    message_manager.max_input_tokens = 500
    
    for i in range(20):
        browser_state = BrowserState(
            url=f"https://test.com/page{i}",
            title=f"Test Page {i}",
            element_tree=DOMElementNode(
                tag_name="div",
                attributes={},
                children=[],
                is_visible=True,
                parent=None,
                xpath="//div"
            ),
            selector_map={},
            tabs=[TabInfo(page_id=1, url=f"https://test.com/page{i}", title=f"Test Page {i}")]
        )
        
        action_result = None
        if i % 2 == 0:
            action_result = [ActionResult(
                extracted_content=f"Important content from step {i}" * 5,
                include_in_memory=(i % 4 == 0)
            )]
        
        message_manager.add_state_message(
            browser_state, 
            action_result,
            AgentStepInfo(step=i+1),
            use_vision=False
        )
        
    messages = message_manager.get_messages()
    
    total_tokens = message_manager.history.total_tokens
    # Either the token count is within limit, or if trimmed, the number of messages is low.
    assert total_tokens <= message_manager.max_input_tokens or len(messages) <= 5
    
    # The system prompt (first message) should be preserved.
    assert isinstance(messages[0], SystemMessage)
    
    # The most recent message should include the title of the last page.
    assert f"Test Page {19}" in messages[-1].content

def test_add_new_task(message_manager):
    """Test adding a new task to the message manager"""
    initial_message_count = len(message_manager.get_messages())
    
    new_task = "New test task"
    message_manager.add_new_task(new_task)
    
    messages = message_manager.get_messages()
    assert len(messages) == initial_message_count + 1
    # The new task should be contained in the last human message.
    assert isinstance(messages[-1], HumanMessage)
    assert new_task in messages[-1].content

def test_add_plan(message_manager):
    """Test adding a plan to the message manager"""
    initial_message_count = len(message_manager.get_messages())
    
    plan = "1. Step one\n2. Step two\n3. Step three"
    message_manager.add_plan(plan)
    
    messages = message_manager.get_messages()
    assert len(messages) == initial_message_count + 1
    # The plan should be contained within an AI message.
    assert isinstance(messages[-1], AIMessage)
    assert plan in messages[-1].content

def test_add_model_output(message_manager):
    """Test adding model output as an AI message"""
    from browser_use.agent.views import AgentBrain, AgentOutput
    
    initial_message_count = len(message_manager.get_messages())
    
    model_output = AgentOutput(
        actions=[],
        current_state=AgentBrain(
            page_summary="Test page summary",
            evaluation_previous_goal="Success",
            memory="Test memory",
            next_goal="Test next goal"
        )
    )
    
    message_manager.add_model_output(model_output)
    
    messages = message_manager.get_messages()
    # Expect two additional messages: one for the AI output and one for the associated tool message.
    assert len(messages) == initial_message_count + 2
    assert isinstance(messages[-2], AIMessage)
    assert hasattr(messages[-2], "tool_calls")

def test_filter_sensitive_data(message_manager):
    """Test filtering sensitive data from messages"""
    # Create a message manager with sensitive data settings.
    manager = MessageManager(
        llm=None,
        task="Test task",
        action_descriptions="Test actions",
        system_prompt_class=SystemPrompt,
        max_input_tokens=1000,
        sensitive_data={"PASSWORD": "secret123", "API_KEY": "api-12345"}
    )
    
    # A message that contains placeholder markers for sensitive data.
    content = "Please use <secret>PASSWORD</secret> to login and <secret>API_KEY</secret> for API access"
    message = HumanMessage(content=content)
    
    filtered_message = manager._filter_sensitive_data(message)
    
    # After filtering, the placeholders should be replaced with the actual sensitive values.
    assert "secret123" in filtered_message.content
    assert "api-12345" in filtered_message.content
    assert "<secret>" not in filtered_message.content
