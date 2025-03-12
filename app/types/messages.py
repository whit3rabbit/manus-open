from typing import Literal
from pydantic import BaseModel
from app.types.browser_types import BrowserAction, BrowserActionResult

TextEditorCommand = Literal['view', 'create', 'write', 'str_replace', 'find_content', 'find_file']

class CommonApiResult(BaseModel):
    status: Literal['success', 'error']
    error: str | None = None

class TextEditorAction(BaseModel):
    command: TextEditorCommand
    path: str
    sudo: bool | None = None
    file_text: str | None = None
    view_range: list[int] | None = None
    old_str: str | None = None
    new_str: str | None = None
    insert_line: int | None = None
    glob: str | None = None
    regex: str | None = None
    append: bool | None = None
    trailing_newline: bool | None = None
    leading_newline: bool | None = None

class FileInfo(BaseModel):
    path: str
    content: str
    old_content: str | None = None

class TextEditorActionResult(CommonApiResult):
    result: str
    file_info: FileInfo | None = None

class BrowserActionRequest(BaseModel):
    action: BrowserAction
    screenshot_presigned_url: str | None = None
    clean_screenshot_presigned_url: str | None = None

class BrowserActionResponse(CommonApiResult):
    result: BrowserActionResult | None = None

class TerminalWriteApiRequest(BaseModel):
    text: str
    enter: bool | None = None

class TerminalApiResponse(CommonApiResult):
    output: list[str]
    result: str
    terminal_id: str

TerminalInputMessageType = Literal['command', 'view', 'view_last', 'kill_process', 'reset', 'reset_all']
TerminalOutputMessageType = Literal['update', 'finish', 'partial_finish', 'error', 'history', 'action_finish']
TerminalCommandMode = Literal['run', 'send_line', 'send_key', 'send_control']
TerminalStatus = Literal['idle', 'running']

class TerminalInputMessage(BaseModel):
    type: TerminalInputMessageType
    terminal: str
    action_id: str
    command: str | None = None
    mode: TerminalCommandMode | None = None
    exec_dir: str | None = None

    def create_response(self, type: TerminalOutputMessageType, result: str, output: list[str], terminal_status: TerminalStatus, sub_command_index: int):
        return TerminalOutputMessage(
            type=type,
            terminal=self.terminal,
            action_id=self.action_id,
            sub_command_index=sub_command_index,
            result=result,
            output=output,
            terminal_status=terminal_status
        )

class TerminalOutputMessage(BaseModel):
    type: TerminalOutputMessageType
    terminal: str
    action_id: str
    sub_command_index: int = 0 
    result: str | None = None
    output: list[str]
    terminal_status: Literal['idle', 'running', 'unknown']
