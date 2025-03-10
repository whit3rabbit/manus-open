from dataclasses import dataclass, field
from typing import Any, Optional
from playwright.async_api import ElementHandle
from pydantic import BaseModel
from browser_use.dom.history_tree_processor.service import DOMHistoryElement
from browser_use.dom.views import DOMState


class TabInfo(BaseModel):
    """Represents information about a browser tab"""
    page_id: int
    url: str
    title: str


@dataclass
class ClickableElementData:
    element_handle: ElementHandle
    element_info: "ElementInfo"
    x_center: float
    y_center: float


@dataclass
class BrowserState(DOMState):
    url: str
    title: str
    tabs: list[TabInfo]
    screenshot: Optional[str] = None
    pixels_above: int = 0
    pixels_below: int = 0
    browser_errors: list[str] = field(default_factory=list)


@dataclass
class ElementInfo:
    element_id: str
    tag_name: str
    attributes: dict[str, str]
    text_content: str
    inner_text: str
    visible_text: str
    bounding_box: dict[str, float]
    is_visible: bool
    computed_style: dict[str, str]


@dataclass
class ExtractedPageContentInfo:
    elements: list[ElementInfo]
    page_text: str
    html_content: str


@dataclass
class BrowserStateHistory:
    url: str
    title: str
    tabs: list[TabInfo]
    interacted_element: list[DOMHistoryElement | None] | list[None]
    screenshot: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        data = {}
        data['tabs'] = [tab.model_dump() for tab in self.tabs]
        data['screenshot'] = self.screenshot
        data['interacted_element'] = [el.to_dict() if el else None for el in self.interacted_element]
        data['url'] = self.url
        data['title'] = self.title
        return data


class BrowserError(Exception):
    """Base class for all browser errors"""
    pass


class URLNotAllowedError(BrowserError):
    """Error raised when a URL is not allowed"""
    pass


class ScreenshotError(BrowserError):
    """Error raised when a screenshot fails"""
    pass