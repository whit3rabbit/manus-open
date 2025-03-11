from typing import Literal, Optional, List
from pydantic import BaseModel
from browser_types import BrowserAction, BrowserActionResult

TextEditorCommand = Literal['view', 'create', 'write', 'str_replace', 'find_content', 'find_file']

class CommonApiResult(BaseModel):
    status: Literal['success', 'error']
    error: Optional[str] = None

class TextEditorAction(BaseModel):
    command: TextEditorCommand
    path: str
    sudo: Optional[bool] = None
    file_text: Optional[str] = None
    view_range: Optional[List[int]] = None
    old_str: Optional[str] = None
    new_str: Optional[str] = None
    insert_line: Optional[int] = None
    glob: Optional[str] = None
    regex: Optional[str] = None
    append: Optional[bool] = None
    trailing_newline: Optional[bool] = None
    leading_newline: Optional[bool] = None

class FileInfo(BaseModel):
    path: str
    content: str
    old_content: Optional[str] = None

class TextEditorActionResult(CommonApiResult):
    result: str
    file_info: Optional[FileInfo] = None

class BrowserActionRequest(BaseModel):
    action: BrowserAction
    screenshot_presigned_url: Optional[str] = None
    clean_screenshot_presigned_url: Optional[str] = None

class BrowserActionResponse(CommonApiResult):
    result: Optional[BrowserActionResult] = None

class TerminalWriteApiRequest(BaseModel):
    text: str
    enter: Optional[bool] = None

class TerminalApiResponse(CommonApiResult):
    output: List[str]
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
    command: Optional[str] = None
    mode: Optional[TerminalCommandMode] = None
    exec_dir: Optional[str] = None

    def create_response(self, type: TerminalOutputMessageType, result: str, output: List[str], terminal_status: TerminalStatus, sub_command_index: int):
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
    result: str  # Added to match create_response method
    output: List[str]  # Added to match create_response method
    terminal_status: TerminalStatus = 'idle'
    sub_command_index: Optional[int] = None