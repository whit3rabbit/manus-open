# Source Generated with Decompyle++
# File: tests.py (Python 3.11)

import pytest
from browser_use.agent.views import ActionResult, AgentBrain, AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserState, BrowserStateHistory, TabInfo
from browser_use.controller.registry.service import Registry
from browser_use.controller.views import ClickElementAction, DoneAction, ExtractPageContentAction
from browser_use.dom.views import DOMElementNode

# Sample browser state fixture
sample_browser_state = BrowserState(
    url='https://example.com',
    title='Example Page',
    tabs=[TabInfo(url='https://example.com', title='Example Page', page_id=1)],
    screenshot='screenshot1.png',
    element_tree=DOMElementNode(
        tag_name='root',
        is_visible=True,
        parent=None,
        xpath='',
        attributes={},
        children=[]
    ),
    selector_map={}
)

# Action registry fixture
@pytest.fixture
def action_registry():
    registry = Registry()
    # These functions were stubs in the original
    def click_element_action(params, browser):
        return None
        
    def extract_page_content_action(params, browser):
        return None
        
    def done_action(params):
        return None
        
    return registry.create_action_model()

# Sample history fixture
@pytest.fixture
def sample_history(action_registry):
    click_action = action_registry(click_element={'index': 1})
    extract_action = action_registry(extract_page_content={'value': 'text'})
    done_action = action_registry(done={'text': 'Task completed'})
    
    history_items = [
        AgentHistory(
            model_output=AgentOutput(
                current_state=AgentBrain(
                    page_summary='I need to find the founders of browser-use',
                    evaluation_previous_goal='None',
                    memory='Started task',
                    next_goal='Click button'
                ),
                actions=[click_action]
            ),
            result=[ActionResult(is_done=False)],
            state=BrowserStateHistory(
                url='https://example.com',
                title='Page 1',
                tabs=[TabInfo(url='https://example.com', title='Page 1', page_id=1)],
                screenshot='screenshot1.png',
                interacted_element=[]
            )
        ),
        AgentHistory(
            model_output=AgentOutput(
                current_state=AgentBrain(
                    evaluation_previous_goal='Clicked button',
                    memory='Button clicked',
                    next_goal='Extract content',
                    page_summary=''
                ),
                actions=[extract_action]
            ),
            result=[
                ActionResult(
                    is_done=False,
                    extracted_content='Extracted text',
                    error='Failed to extract completely'
                )
            ],
            state=BrowserStateHistory(
                url='https://example.com/page2',
                title='Page 2',
                tabs=[TabInfo(url='https://example.com/page2', title='Page 2', page_id=2)],
                screenshot='screenshot2.png',
                interacted_element=[]
            )
        ),
        AgentHistory(
            model_output=AgentOutput(
                current_state=AgentBrain(
                    page_summary='I found out that the founders are John Doe and Jane Smith. I need to draft them a message.',
                    evaluation_previous_goal='Extracted content',
                    memory='Content extracted',
                    next_goal='Finish task'
                ),
                actions=[done_action]
            ),
            result=[
                ActionResult(
                    is_done=True,
                    extracted_content='Task completed',
                    error=None
                )
            ],
            state=BrowserStateHistory(
                url='https://example.com/page2',
                title='Page 2',
                tabs=[TabInfo(url='https://example.com/page2', title='Page 2', page_id=2)],
                screenshot='screenshot3.png',
                interacted_element=[]
            )
        )
    ]
    
    return AgentHistoryList(history=history_items)


def test_last_model_output(sample_history):
    """Test getting the last action from history"""
    last_action = sample_history.last_action()
    print(last_action)
    assert last_action is not None
    assert last_action.current_state.next_goal == 'Finish task'


def test_get_errors(sample_history):
    """Test extracting errors from history"""
    errors = sample_history.errors()
    assert len(errors) == 1
    assert errors[0] == 'Failed to extract completely'


def test_final_result(sample_history):
    """Test getting the final result"""
    final_result = sample_history.final_result()
    assert final_result is not None
    assert final_result.is_done is True
    assert final_result.extracted_content == 'Task completed'
    assert final_result.error is None


def test_is_done(sample_history):
    """Test checking if task is done"""
    is_done = sample_history.is_done()
    assert is_done is True


def test_urls(sample_history):
    """Test getting all URLs from history"""
    urls = sample_history.urls()
    assert len(urls) == 2
    assert urls[0] == 'https://example.com'
    assert urls[1] == 'https://example.com/page2'


def test_all_screenshots(sample_history):
    """Test getting all screenshots from history"""
    screenshots = sample_history.screenshots()
    assert len(screenshots) == 3
    assert screenshots[0] == 'screenshot1.png'
    assert screenshots[1] == 'screenshot2.png'
    assert screenshots[2] == 'screenshot3.png'


def test_all_model_outputs(sample_history):
    """Test getting all model actions from history"""
    model_actions = sample_history.model_actions()
    assert len(model_actions) == 3
    
    # Check the types of each action
    assert hasattr(model_actions[0], 'click_element')
    assert hasattr(model_actions[1], 'extract_page_content')
    assert hasattr(model_actions[2], 'done')


def test_all_model_outputs_filtered(sample_history):
    """Test filtering model actions by type"""
    filtered_actions = sample_history.model_actions_filtered(include=['click_element'])
    assert len(filtered_actions) == 1
    assert hasattr(filtered_actions[0], 'click_element')


def test_empty_history():
    """Test behavior with empty history"""
    empty_history = AgentHistoryList(history=[])
    assert empty_history.last_action() is None
    assert empty_history.errors() == []
    assert empty_history.final_result() is None
    assert empty_history.is_done() is False
    assert empty_history.urls() == []
    assert empty_history.screenshots() == []
    assert empty_history.model_actions() == []


def test_action_creation(action_registry):
    """Test creating actions with the registry"""
    click_action = action_registry(click_element={'index': 1})
    assert click_action is not None
    assert hasattr(click_action, 'click_element')
    assert click_action.click_element.index == 1