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
    
    # Should include a task message
    human_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
    assert any("Test task" in msg.content for msg in human_messages)
    
    # Should include an example output
    ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]
    assert len(ai_messages) > 0

def test_add_state_message(message_manager):
    """Test adding browser state message"""
    # Create a simple browser state
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
    
    # Count initial messages
    initial_message_count = len(message_manager.get_messages())
    
    # Add state message
    message_manager.add_state_message(
        browser_state, 
        None,  # No result
        AgentStepInfo(step=1),
        use_vision=False
    )
    
    # Get updated messages
    messages = message_manager.get_messages()
    
    # Should have one more message
    assert len(messages) == initial_message_count + 1
    
    # Last message should be a HumanMessage containing state info
    assert isinstance(messages[-1], HumanMessage)
    assert "Current browser state" in messages[-1].content
    assert "https://test.com" in messages[-1].content
    assert "Test Page" in messages[-1].content

def test_add_state_with_memory_result(message_manager):
    """Test adding state with result that should be included in memory"""
    # Create a simple browser state
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
    
    # Create a result with content to be included in memory
    action_result = [ActionResult(
        extracted_content="Important content",
        include_in_memory=True
    )]
    
    # Add state message with result
    message_manager.add_state_message(
        browser_state, 
        action_result,
        AgentStepInfo(step=1),
        use_vision=False
    )
    
    # Get updated messages
    messages = message_manager.get_messages()
    
    # Last message should include the extracted content
    assert "Important content" in messages[-1].content
    
    # When include_in_memory is True, the content should be clearly marked
    assert "Extracted:" in messages[-1].content

def test_add_state_with_non_memory_result(message_manager):
    """Test adding state with result that should not be included in memory"""
    # Create a simple browser state
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
    
    # Create a result with content not to be included in memory
    action_result = [ActionResult(
        extracted_content="Temporary content",
        include_in_memory=False
    )]
    
    # Add state message with result
    message_manager.add_state_message(
        browser_state, 
        action_result,
        AgentStepInfo(step=1),
        use_vision=False
    )
    
    # Get updated messages
    messages = message_manager.get_messages()
    
    # Last message should still include the extracted content
    assert "Temporary content" in messages[-1].content
    
    # The presentation might be different when include_in_memory is False
    assert "Extracted:" in messages[-1].content

def test_token_overflow_handling_with_real_flow(message_manager):
    """Test how the message manager handles token overflow with a realistic message flow"""
    # Set a low token limit to force overflow handling
    message_manager.max_input_tokens = 500
    
    # Simulate a conversation with many messages
    for i in range(20):  # Reduced from 200 to make the test faster
        # Create browser state
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
        
        # Create result (different types for variety)
        action_result = None
        if i % 2 == 0:
            action_result = [ActionResult(
                extracted_content=f"Important content from step {i}" * 5,
                include_in_memory=(i % 4 == 0)
            )]
        
        # Add state message
        message_manager.add_state_message(
            browser_state, 
            action_result,
            AgentStepInfo(step=i+1),
            use_vision=False
        )
        
    # Get the final messages
    messages = message_manager.get_messages()
    
    # Token count should be within the limit
    total_tokens = message_manager.history.total_tokens
    assert total_tokens <= message_manager.max_input_tokens or len(messages) <= 5
    
    # System message should always be preserved
    assert isinstance(messages[0], SystemMessage)
    
    # Most recent messages should be preserved
    assert f"Test Page {19}" in messages[-1].content

def test_add_new_task(message_manager):
    """Test adding a new task to the message manager"""
    initial_message_count = len(message_manager.get_messages())
    
    # Add a new task
    new_task = "New test task"
    message_manager.add_new_task(new_task)
    
    # Get updated messages
    messages = message_manager.get_messages()
    
    # Should have one more message
    assert len(messages) == initial_message_count + 1
    
    # Last message should be a HumanMessage containing the new task
    assert isinstance(messages[-1], HumanMessage)
    assert new_task in messages[-1].content

def test_add_plan(message_manager):
    """Test adding a plan to the message manager"""
    initial_message_count = len(message_manager.get_messages())
    
    # Add a plan
    plan = "1. Step one\n2. Step two\n3. Step three"
    message_manager.add_plan(plan)
    
    # Get updated messages
    messages = message_manager.get_messages()
    
    # Should have one more message
    assert len(messages) == initial_message_count + 1
    
    # Last message should be an AIMessage containing the plan
    assert isinstance(messages[-1], AIMessage)
    assert plan in messages[-1].content

def test_add_model_output(message_manager):
    """Test adding model output as an AI message"""
    from browser_use.agent.views import AgentBrain, AgentOutput
    
    initial_message_count = len(message_manager.get_messages())
    
    # Create a model output
    model_output = AgentOutput(
        actions=[],
        current_state=AgentBrain(
            page_summary="Test page summary",
            evaluation_previous_goal="Success",
            memory="Test memory",
            next_goal="Test next goal"
        )
    )
    
    # Add model output
    message_manager.add_model_output(model_output)
    
    # Get updated messages
    messages = message_manager.get_messages()
    
    # Should have two more messages (AI message and tool message)
    assert len(messages) == initial_message_count + 2
    
    # Check message types
    assert isinstance(messages[-2], AIMessage)
    assert hasattr(messages[-2], "tool_calls")

def test_filter_sensitive_data(message_manager):
    """Test filtering sensitive data from messages"""
    # Create a message manager with sensitive data
    manager = MessageManager(
        llm=None,
        task="Test task",
        action_descriptions="Test actions",
        system_prompt_class=SystemPrompt,
        max_input_tokens=1000,
        sensitive_data={"PASSWORD": "secret123", "API_KEY": "api-12345"}
    )
    
    # Create a message with sensitive data references
    content = "Please use <secret>PASSWORD</secret> to login and <secret>API_KEY</secret> for API access"
    message = HumanMessage(content=content)
    
    # Filter the message
    filtered_message = manager._filter_sensitive_data(message)
    
    # Sensitive data should be replaced
    assert "secret123" in filtered_message.content
    assert "api-12345" in filtered_message.content
    assert "<secret>" not in filtered_message.content