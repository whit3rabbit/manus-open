import re
from pathlib import Path
from typing import get_args
from pydantic import BaseModel
from app.helpers.tool_helpers import MAX_RESPONSE_LEN, TRUNCATED_MESSAGE, maybe_truncate, run_shell
from app.types.messages import FileInfo, TextEditorAction
from app.types.messages import TextEditorCommand as Command
from base import DEFAULT_WORKING_DIR, ToolError

class ToolResult(BaseModel):
    output: str
    file_info: FileInfo | None = None

SNIPPET_LINES: int = 4

class TextEditor:
    '''
    An filesystem editor tool that allows the agent to view, create, and edit files.
    The tool parameters are defined by Anthropic and are not editable.
    '''
    
    def __init__(self):
        super().__init__()

    async def run_action(self, action):
        pass

    def validate_path(self, command, path):
        '''
        Check that the path/command combination is valid.
        '''
        if path.is_absolute() and DEFAULT_WORKING_DIR:
            path = Path(DEFAULT_WORKING_DIR) / path
            
        if not path.exists() and command != 'create' and command != 'write':
            raise ToolError(f'The path {path} does not exist. Please provide a valid path.')
            
        if path.exists():
            if command == 'create':
                if path.is_file() or path.stat().st_size > 0:
                    raise ToolError(f'Non-empty file already exists at: {path}. Cannot overwrite no-empty files using command `create`.')
            if command in ('view_dir', 'find_file'):
                if not path.is_dir():
                    raise ToolError(f'The path {path} is not a directory.')
            if command in ('move', 'delete'):
                pass
            elif path.is_dir():
                raise ToolError(f'The path {path} is a directory. Directory operations are not supported for this command.')
        
        return path

    async def view_dir(self, path):
        '''List contents of a directory'''
        pass

    async def view(self, path, view_range, sudo):
        '''Implement the view command'''
        pass

    async def str_replace(self, path, old_str, new_str, sudo):
        '''Implement the str_replace command, which replaces old_str with new_str in the file content'''
        pass

    async def find_content(self, path, regex, sudo):
        '''Implement the find_content command, which searches for content matching regex in file'''
        pass

    async def find_file(self, path, glob_pattern):
        '''Implement the find_file command, which finds files matching glob pattern'''
        pass

    async def read_file(self, path, sudo):
        '''Read the content of a file from a given path; raise a ToolError if an error occurs.'''
        pass

    async def write_file(self, path, content, sudo, append, trailing_newline, leading_newline):
        """Write the content of a file to a given path; raise a ToolError if an error occurs.
        Creates parent directories if they don't exist.

        Args:
            path: The path to write to
            content: The content to write
            sudo: Whether to use sudo privileges
            append: If True, append content to file instead of overwriting
        """
        pass

    def _make_output(self, file_content, file_descriptor, init_line, expand_tabs):
        '''Generate output for the CLI based on the content of a file.'''
        if expand_tabs:
            file_content = file_content.expandtabs()
        
        header = f"Here's the result of running `cat -n` on {file_descriptor}:\n"
        line_width = 8
        max_content_length = MAX_RESPONSE_LEN - len(header) - len(TRUNCATED_MESSAGE)
        lines = file_content.split('\n')
        line_num_chars = line_width * len(lines)
        max_content_length -= line_num_chars
        
        # The rest of the implementation is missing due to decompyle being incomplete

text_editor = TextEditor()