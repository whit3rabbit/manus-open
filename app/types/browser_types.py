from pydantic import BaseModel
from browser_use.agent.views import ActionModel
from browser_use.controller.views import ClickElementAction, GoToUrlAction, InputTextAction, OpenTabAction, ScrollAction, SearchGoogleAction, SendKeysAction, SwitchTabAction
from browser_use.controller.views import ExtractPageContentAction as BaseExtractPageContentAction

class NoParamAction(BaseModel):
    pass

class ScrollToTextAction(BaseModel):
    text: str

class GetDropdownOptionsAction(BaseModel):
    index: int

class SelectDropdownOptionAction(BaseModel):
    index: int
    text: str

class ViewAction(BaseModel):
    delay: float

class DoneAction(BaseModel):
    result: str

class SaveImageAction(BaseModel):
    url: str
    file_path: str

class SaveScreenshotAction(BaseModel):
    file_path: str

class ExtractPageContentAction(BaseExtractPageContentAction):
    save_to_file_path: str | None = None

class BrowserNavigateAction(BaseModel):
    url: str

class BrowserViewAction(BaseModel):
    reload: bool | None = None

class BrowserScreenshotAction(BaseModel):
    file: str
    reload: bool | None = None

class BrowserRestartAction(BaseModel):
    url: str

class BrowserClickAction(BaseModel):
    index: int | None = None
    coordinate_x: float | None = None
    coordinate_y: float | None = None

class BrowserMoveMouseAction(BaseModel):
    coordinate_x: float
    coordinate_y: float

class BrowserInputAction(BaseModel):
    index: int | None = None
    coordinate_x: float | None = None
    coordinate_y: float | None = None
    text: str
    press_enter: bool | None = None

class BrowserPressKeyAction(BaseModel):
    key: str

class BrowserScrollUpAction(BaseModel):
    to_top: bool | None = None

class BrowserScrollDownAction(BaseModel):
    to_bottom: bool | None = None

class BrowserSelectOptionAction(BaseModel):
    index: int
    option: int

class BrowserConsoleExecAction(BaseModel):
    javascript: str

class BrowserConsoleViewAction(BaseModel):
    max_lines: int | None = None

class BrowserAction(ActionModel):
    view: ViewAction | None = None
    save_image: SaveImageAction | None = None
    save_screenshot: SaveScreenshotAction | None = None
    extract_content: ExtractPageContentAction | None = None
    search_google: SearchGoogleAction | None = None
    go_to_url: GoToUrlAction | None = None
    click_element: ClickElementAction | None = None
    input_text: InputTextAction | None = None
    switch_tab: SwitchTabAction | None = None
    open_tab: OpenTabAction | None = None
    scroll_down: ScrollAction | None = None
    scroll_up: ScrollAction | None = None
    send_keys: SendKeysAction | None = None
    go_back: NoParamAction | None = None
    scroll_to_text: ScrollToTextAction | None = None
    get_dropdown_options: GetDropdownOptionsAction | None = None
    select_dropdown_option: SelectDropdownOptionAction | None = None
    browser_navigate: BrowserNavigateAction | None = None
    browser_view: BrowserViewAction | None = None
    browser_screenshot: BrowserScreenshotAction | None = None
    browser_restart: BrowserRestartAction | None = None
    browser_click: BrowserClickAction | None = None
    browser_move_mouse: BrowserMoveMouseAction | None = None
    browser_input: BrowserInputAction | None = None
    browser_press_key: BrowserPressKeyAction | None = None
    browser_scroll_up: BrowserScrollUpAction | None = None
    browser_scroll_down: BrowserScrollDownAction | None = None
    browser_select_option: BrowserSelectOptionAction | None = None
    browser_console_exec: BrowserConsoleExecAction | None = None
    browser_console_view: BrowserConsoleViewAction | None = None

class BrowserActionResult(BaseModel):
    url: str
    title: str
    result: str
    error: str | None = None
    screenshot_uploaded: bool
    clean_screenshot_uploaded: bool
    clean_screenshot_path: str
    elements: str
    markdown: str
    pixels_above: int
    pixels_below: int