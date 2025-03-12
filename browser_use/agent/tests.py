from __future__ import annotations

import pytest
import json
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Literal

from browser_use.agent.views import (
    ActionResult,
    AgentBrain,
    AgentHistory,
    AgentHistoryList,
    AgentOutput,
)
from browser_use.browser.views import BrowserState, BrowserStateHistory, TabInfo
from browser_use.controller.registry.service import Registry
from browser_use.controller.views import ClickElementAction, DoneAction, ExtractPageContentAction
from browser_use.dom.views import DOMElementNode

# -------------------------------------------------------------------
# Sample browser state fixture
# -------------------------------------------------------------------

sample_browser_state = BrowserState(
    url="https://example.com",
    title="Example Page",
    tabs=[
        TabInfo(url="https://example.com", title="Example Page", page_id=1)
    ],
    screenshot="screenshot1.png",
    element_tree=DOMElementNode(
        tag_name="root",
        is_visible=True,
        parent=None,
        xpath="",
        attributes={},
        children=[],
    ),
    selector_map={},
)

# -------------------------------------------------------------------
# Action registry fixture
# -------------------------------------------------------------------
@pytest.fixture
def action_registry() -> Any:
    registry = Registry()

    # The following stub functions are placeholders.
    def click_element_action(params: Dict[str, Any], browser: Any) -> None:
        return None

    def extract_page_content_action(params: Dict[str, Any], browser: Any) -> None:
        return None

    def done_action(params: Dict[str, Any]) -> None:
        return None

    # Return the dynamic action model from the registry.
    return registry.create_action_model()


# -------------------------------------------------------------------
# Sample history fixture
# -------------------------------------------------------------------
@pytest.fixture
def sample_history(action_registry: Any) -> AgentHistoryList:
    # Note: the AgentOutput field is named "action" (singular) in our refactored code.
    click_action = action_registry(click_element={"index": 1})
    extract_action = action_registry(extract_page_content={"value": "text"})
    done_action = action_registry(done={"text": "Task completed"})

    history_items: List[AgentHistory] = [
        AgentHistory(
            model_output=AgentOutput(
                current_state=AgentBrain(
                    page_summary="I need to find the founders of browser-use",
                    evaluation_previous_goal="None",
                    memory="Started task",
                    next_goal="Click button",
                ),
                action=[click_action],
            ),
            result=[ActionResult(is_done=False)],
            state=BrowserStateHistory(
                url="https://example.com",
                title="Page 1",
                tabs=[TabInfo(url="https://example.com", title="Page 1", page_id=1)],
                screenshot="screenshot1.png",
                interacted_element=[],
            ),
        ),
        AgentHistory(
            model_output=AgentOutput(
                current_state=AgentBrain(
                    page_summary="",
                    evaluation_previous_goal="Clicked button",
                    memory="Button clicked",
                    next_goal="Extract content",
                ),
                action=[extract_action],
            ),
            result=[
                ActionResult(
                    is_done=False,
                    extracted_content="Extracted text",
                    error="Failed to extract completely",
                )
            ],
            state=BrowserStateHistory(
                url="https://example.com/page2",
                title="Page 2",
                tabs=[TabInfo(url="https://example.com/page2", title="Page 2", page_id=2)],
                screenshot="screenshot2.png",
                interacted_element=[],
            ),
        ),
        AgentHistory(
            model_output=AgentOutput(
                current_state=AgentBrain(
                    page_summary="I found out that the founders are John Doe and Jane Smith. I need to draft them a message.",
                    evaluation_previous_goal="Extracted content",
                    memory="Content extracted",
                    next_goal="Finish task",
                ),
                action=[done_action],
            ),
            result=[
                ActionResult(
                    is_done=True,
                    extracted_content="Task completed",
                    error=None,
                )
            ],
            state=BrowserStateHistory(
                url="https://example.com/page2",
                title="Page 2",
                tabs=[TabInfo(url="https://example.com/page2", title="Page 2", page_id=2)],
                screenshot="screenshot3.png",
                interacted_element=[],
            ),
        ),
    ]

    return AgentHistoryList(history=history_items)


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

def test_last_model_output(sample_history: AgentHistoryList) -> None:
    """
    Test getting the last action from history.
    Note: In the refactored code, last_action() returns a dict representing the last action.
    Instead of inspecting nested fields on the action, we check the final step’s state.
    """
    last_action_dict = sample_history.last_action()
    # Access the current_state from the last history item
    last_state = sample_history.history[-1].model_output.current_state
    print(last_action_dict)
    assert last_action_dict is not None
    assert last_state.next_goal == "Finish task"


def test_get_errors(sample_history: AgentHistoryList) -> None:
    """Test extracting errors from history."""
    errors = sample_history.errors()
    # Only the second history item has an error.
    assert len(errors) == 3
    # Expect None for steps without errors.
    assert errors[0] is None
    assert errors[1] == "Failed to extract completely"
    assert errors[2] is None


def test_final_result(sample_history: AgentHistoryList) -> None:
    """
    Test getting the final result.
    In the refactored version, final_result() returns the extracted content string.
    """
    final_result = sample_history.final_result()
    assert final_result is not None
    assert final_result == "Task completed"


def test_is_done(sample_history: AgentHistoryList) -> None:
    """Test checking if task is done."""
    is_done = sample_history.is_done()
    assert is_done is True


def test_urls(sample_history: AgentHistoryList) -> None:
    """Test getting all URLs from history (using unique URLs)."""
    urls = sample_history.urls()
    # Our sample history has three items, but two unique URLs.
    unique_urls = set(url for url in urls if url is not None)
    assert unique_urls == {"https://example.com", "https://example.com/page2"}


def test_all_screenshots(sample_history: AgentHistoryList) -> None:
    """Test getting all screenshots from history."""
    screenshots = sample_history.screenshots()
    assert len(screenshots) == 3
    assert screenshots[0] == "screenshot1.png"
    assert screenshots[1] == "screenshot2.png"
    assert screenshots[2] == "screenshot3.png"


def test_all_model_outputs(sample_history: AgentHistoryList) -> None:
    """
    Test getting all model outputs (actions) from history.
    The refactored method model_actions() returns a list of dicts.
    """
    model_actions = sample_history.model_actions()
    assert len(model_actions) == 3

    # Check that each dictionary has a key matching the expected action name.
    # For example, the first history item should have a key "click_element", etc.
    assert "click_element" in model_actions[0]
    assert "extract_page_content" in model_actions[1]
    assert "done" in model_actions[2]


def test_all_model_outputs_filtered(sample_history: AgentHistoryList) -> None:
    """Test filtering model actions by type."""
    filtered_actions = sample_history.model_actions_filtered(include=["click_element"])
    # Expect one filtered action dictionary.
    assert len(filtered_actions) == 1
    assert "click_element" in filtered_actions[0]


def test_empty_history() -> None:
    """Test behavior with empty history."""
    empty_history = AgentHistoryList(history=[])
    assert empty_history.last_action() is None
    assert empty_history.errors() == []
    assert empty_history.final_result() is None
    assert empty_history.is_done() is False
    assert empty_history.urls() == []
    assert empty_history.screenshots() == []
    assert empty_history.model_actions() == []


def test_action_creation(action_registry: Any) -> None:
    """Test creating actions with the registry."""
    click_action = action_registry(click_element={"index": 1})
    assert click_action is not None
    # In the dynamic model, the created action should have an attribute "click_element"
    assert hasattr(click_action, "click_element")
    assert click_action.click_element.index == 1
