import re
from pathlib import Path
from typing import List, Optional, Union, get_args
from pydantic import BaseModel

from app.helpers.tool_helpers import MAX_RESPONSE_LEN, TRUNCATED_MESSAGE, maybe_truncate, run_shell
from app.types.messages import FileInfo, TextEditorAction
from app.types.messages import TextEditorCommand as Command
from app.tools.base import DEFAULT_WORKING_DIR, ToolError

class ToolResult(BaseModel):
    output: str
    file_info: FileInfo | None = None

SNIPPET_LINES: int = 4

class TextEditor:
    '''
    A filesystem editor tool that allows the agent to view, create, and edit files.
    The tool parameters are defined by Anthropic and are not editable.
    '''
    
    def __init__(self):
        super().__init__()

    async def run_action(self, action: TextEditorAction) -> ToolResult:
        '''
        Run the specified editor action.
        
        Args:
            action: The editor action to run
            
        Returns:
            ToolResult: The result of the action
        '''
        command = action.command
        path = Path(action.path)
        sudo = action.sudo or False
        
        try:
            # Validate the path
            path = self.validate_path(command, path)
            
            # Execute the appropriate command
            if command == 'view_dir':
                return await self.view_dir(path)
            elif command == 'view':
                return await self.view(path, action.view_range, sudo)
            elif command == 'create':
                return await self.write_file(path, action.file_text or '', sudo, False, False, False)
            elif command == 'write':
                return await self.write_file(
                    path, 
                    action.file_text or '', 
                    sudo, 
                    action.append or False,
                    action.trailing_newline or False,
                    action.leading_newline or False
                )
            elif command == 'str_replace':
                return await self.str_replace(path, action.old_str or '', action.new_str or '', sudo)
            elif command == 'find_content':
                return await self.find_content(path, action.regex or '', sudo)
            elif command == 'find_file':
                return await self.find_file(path, action.glob or '*')
            else:
                raise ToolError(f"Unrecognized command {command}. The allowed commands for the TextEditor tool are: {', '.join(get_args(Command))}")
                
        except ToolError as e:
            return ToolResult(output=f"Error: {e.message}")
        except Exception as e:
            return ToolResult(output=f"Unexpected error: {str(e)}")

    def validate_path(self, command: Command, path: Path) -> Path:
        '''
        Check that the path/command combination is valid.
        
        Args:
            command: The command being performed
            path: The path to validate
            
        Returns:
            Path: The validated path
            
        Raises:
            ToolError: If the path is invalid for the given command
        '''
        if path.is_absolute() and DEFAULT_WORKING_DIR:
            path = Path(DEFAULT_WORKING_DIR) / path.relative_to('/')
            
        if not path.exists() and command != 'create' and command != 'write':
            raise ToolError(f'The path {path} does not exist. Please provide a valid path.')
            
        if path.exists():
            if command == 'create':
                if path.is_file() or path.stat().st_size > 0:
                    raise ToolError(f'Non-empty file already exists at: {path}. Cannot overwrite non-empty files using command `create`.')
            if command in ('view_dir', 'find_file'):
                if not path.is_dir():
                    raise ToolError(f'The path {path} is not a directory.')
            if command in ('move', 'delete'):
                pass
            elif path.is_dir():
                raise ToolError(f'The path {path} is a directory. Directory operations are not supported for this command.')
        
        return path

    async def view_dir(self, path: Path) -> ToolResult:
        '''
        List contents of a directory.
        
        Args:
            path: Directory path to list
            
        Returns:
            ToolResult: The directory listing
        '''
        cmd = f'ls -la "{path}"'
        return_code, stdout, stderr = await run_shell(cmd)
        
        if return_code != 0:
            raise ToolError(f"Failed to list directory {path}: {stderr}")
            
        return ToolResult(output=f"Directory contents of {path}:\n\n{stdout}")

    async def view(self, path: Path, view_range: Optional[List[int]], sudo: bool) -> ToolResult:
        '''
        View the content of a file.
        
        Args:
            path: File path to view
            view_range: Optional line range to view [start, end]
            sudo: Whether to use sudo privileges
            
        Returns:
            ToolResult: The file content
        '''
        # Read the file content
        file_content = await self.read_file(path, sudo)
        
        # Apply view range if specified
        if view_range and len(view_range) == 2:
            start, end = view_range
            lines = file_content.split('\n')
            
            # Adjust for 1-based indexing and ensure valid range
            start = max(1, min(start, len(lines))) - 1
            end = max(start + 1, min(end, len(lines)))
            
            file_content = '\n'.join(lines[start:end])
        
        # Format the output
        output = self._make_output(file_content, str(path), 1, True)
        
        # Create file info
        file_info = FileInfo(path=str(path), content=file_content)
        
        return ToolResult(output=output, file_info=file_info)

    async def str_replace(self, path: Path, old_str: str, new_str: str, sudo: bool) -> ToolResult:
        '''
        Replace occurrences of old_str with new_str in the file.
        
        Args:
            path: File path to modify
            old_str: String to replace
            new_str: Replacement string
            sudo: Whether to use sudo privileges
            
        Returns:
            ToolResult: The result of the operation
        '''
        if not old_str:
            raise ToolError("old_str cannot be empty")
            
        # Read the file content
        old_content = await self.read_file(path, sudo)
        
        # Perform the replacement
        if old_str not in old_content:
            return ToolResult(
                output=f"Warning: The string '{old_str}' was not found in {path}.",
                file_info=FileInfo(path=str(path), content=old_content)
            )
            
        new_content = old_content.replace(old_str, new_str)
        
        # Write the modified content back to the file
        await self.write_file(path, new_content, sudo, False, False, False)
        
        # Count replacements
        replacements = old_content.count(old_str)
        
        return ToolResult(
            output=f"Successfully replaced {replacements} occurrence(s) of '{old_str}' with '{new_str}' in {path}.",
            file_info=FileInfo(path=str(path), content=new_content, old_content=old_content)
        )

    async def find_content(self, path: Path, regex: str, sudo: bool) -> ToolResult:
        '''
        Find content matching regex in the file.
        
        Args:
            path: File path to search
            regex: Regular expression pattern to search for
            sudo: Whether to use sudo privileges
            
        Returns:
            ToolResult: The search results
        '''
        if not regex:
            raise ToolError("regex pattern cannot be empty")
            
        # Construct the grep command
        grep_cmd = f"{'sudo ' if sudo else ''}grep -n '{regex}' '{path}'"
        return_code, stdout, stderr = await run_shell(grep_cmd)
        
        # Read the file content for the file_info
        file_content = await self.read_file(path, sudo)
        
        if return_code != 0 and not stderr:
            # No matches found (grep returns 1 when no matches)
            return ToolResult(
                output=f"No matches found for pattern '{regex}' in {path}.",
                file_info=FileInfo(path=str(path), content=file_content)
            )
        elif return_code != 0:
            # Error occurred
            raise ToolError(f"Error searching file: {stderr}")
            
        # Format the output
        results = [f"Line {match.split(':', 1)[0]}: {match.split(':', 1)[1]}" for match in stdout.strip().split('\n') if match]
        output = f"Found {len(results)} matches for pattern '{regex}' in {path}:\n\n" + '\n'.join(results)
        
        return ToolResult(
            output=output,
            file_info=FileInfo(path=str(path), content=file_content)
        )

    async def find_file(self, path: Path, glob_pattern: str) -> ToolResult:
        '''
        Find files matching glob pattern in directory.
        
        Args:
            path: Directory path to search
            glob_pattern: Glob pattern to match files
            
        Returns:
            ToolResult: The search results
        '''
        if not glob_pattern:
            glob_pattern = "*"
            
        # Construct the find command
        find_cmd = f"find '{path}' -type f -name '{glob_pattern}' | sort"
        return_code, stdout, stderr = await run_shell(find_cmd)
        
        if return_code != 0:
            raise ToolError(f"Error finding files: {stderr}")
            
        # Format the output
        files = stdout.strip().split('\n')
        if not files or (len(files) == 1 and not files[0]):
            return ToolResult(output=f"No files matching pattern '{glob_pattern}' found in {path}.")
            
        output = f"Found {len(files)} files matching pattern '{glob_pattern}' in {path}:\n\n" + '\n'.join(files)
        
        return ToolResult(output=output)

    async def read_file(self, path: Path, sudo: bool) -> str:
        '''
        Read the content of a file from a given path.
        
        Args:
            path: File path to read
            sudo: Whether to use sudo privileges
            
        Returns:
            str: The file content
            
        Raises:
            ToolError: If an error occurs while reading the file
        '''
        if not path.exists():
            raise ToolError(f"File does not exist: {path}")
            
        if path.is_dir():
            raise ToolError(f"Cannot read directory as file: {path}")
            
        # Construct the cat command
        cat_cmd = f"{'sudo ' if sudo else ''}cat '{path}'"
        return_code, stdout, stderr = await run_shell(cat_cmd)
        
        if return_code != 0:
            raise ToolError(f"Failed to read file {path}: {stderr}")
            
        return stdout

    async def write_file(self, path: Path, content: str, sudo: bool, append: bool, 
                        trailing_newline: bool, leading_newline: bool) -> ToolResult:
        """
        Write content to a file.
        
        Args:
            path: File path to write to
            content: Content to write
            sudo: Whether to use sudo privileges
            append: If True, append content to file instead of overwriting
            trailing_newline: If True, add a newline at the end of content
            leading_newline: If True, add a newline at the beginning of content
            
        Returns:
            ToolResult: The result of the operation
            
        Raises:
            ToolError: If an error occurs while writing the file
        """
        # Create parent directories if they don't exist
        if not path.parent.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ToolError(f"Failed to create directory {path.parent}: {str(e)}")
                
        # Prepare the content
        if leading_newline and not content.startswith('\n'):
            content = '\n' + content
            
        if trailing_newline and not content.endswith('\n'):
            content = content + '\n'
            
        # Determine if we need to append or create new
        old_content = ""
        if path.exists() and path.is_file() and append:
            old_content = await self.read_file(path, sudo)
            content = old_content + content
            
        # Write to a temporary file first
        temp_path = path.with_name(f".tmp_{path.name}")
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        # Move the temporary file to the destination
        if sudo:
            # Use sudo to move the file
            mv_cmd = f"sudo mv '{temp_path}' '{path}'"
            return_code, stdout, stderr = await run_shell(mv_cmd)
            
            if return_code != 0:
                raise ToolError(f"Failed to write file {path}: {stderr}")
        else:
            # Move without sudo
            try:
                temp_path.replace(path)
            except Exception as e:
                raise ToolError(f"Failed to write file {path}: {str(e)}")
                
        action = "Created" if not append or not path.exists() else "Updated"
        
        return ToolResult(
            output=f"{action} file {path} successfully.",
            file_info=FileInfo(path=str(path), content=content, old_content=old_content if append else None)
        )

    def _make_output(self, file_content: str, file_descriptor: str, init_line: int = 1, expand_tabs: bool = True) -> str:
        '''
        Format file content for output with line numbers.
        
        Args:
            file_content: The content to format
            file_descriptor: Description of the file (usually path)
            init_line: Initial line number
            expand_tabs: Whether to expand tabs to spaces
            
        Returns:
            str: Formatted output with line numbers
        '''
        if expand_tabs:
            file_content = file_content.expandtabs(4)
        
        header = f"Here's the result of running `cat -n` on {file_descriptor}:\n"
        line_width = 8  # Width for line numbers
        max_content_length = MAX_RESPONSE_LEN - len(header) - len(TRUNCATED_MESSAGE)
        lines = file_content.split('\n')
        line_num_chars = line_width * len(lines)
        max_content_length -= line_num_chars
        
        if len(file_content) > max_content_length:
            # Truncate the content
            content_parts = []
            current_length = 0
            
            for i, line in enumerate(lines):
                if current_length + len(line) + 1 > max_content_length:
                    break
                
                content_parts.append(line)
                current_length += len(line) + 1  # +1 for newline
                
            file_content = '\n'.join(content_parts)
            file_content = maybe_truncate(file_content, max_content_length)
        
        # Add line numbers
        numbered_lines = []
        for i, line in enumerate(file_content.split('\n')):
            line_num = i + init_line
            numbered_lines.append(f"{line_num:>{line_width-1}}  {line}")
            
        return header + '\n'.join(numbered_lines)

text_editor = TextEditor()