from typing import Any, List
import bashlex
import bashlex.errors
from app.logger import logger

__all__ = [
    'process_terminal_output',
    'split_bash_commands'
]

def split_bash_commands(commands):
    """
    能够将类似 'ls -l \n echo hello' 这样的命令拆分成两个单独的命令 
    (Can split commands like 'ls -l \n echo hello' into two separate commands)
    但是类似 'echo a && echo b' 这样的命令不会被拆分 
    (But commands like 'echo a && echo b' won't be split)
    Copy from OpenHands:
    https://github.com/All-Hands-AI/OpenHands/blob/main/openhands/runtime/utils/bash.py
    """
    if not commands.strip():
        return ['']
    
    try:
        parsed = bashlex.parse(commands)
        result = []
        start = 0
        
        # Process each command in the parsed result
        for node in parsed:
            if hasattr(node, 'pos') and hasattr(node, 'end'):
                cmd = commands[node.pos:node.end].strip()
                result.append(cmd)
        
        # If no commands were parsed but the input wasn't empty, return the original
        if not result and commands.strip():
            # Check for line breaks
            if '\n' in commands:
                # Split by line breaks
                return [cmd.strip() for cmd in commands.split('\n') if cmd.strip()]
            else:
                # Return the original command
                return [commands.strip()]
        
        return result
    except (bashlex.errors.ParsingError, Exception) as e:
        logger.warning(f"Error parsing bash commands: {e}")
        
        # Fallback: split by newlines
        if '\n' in commands:
            return [cmd.strip() for cmd in commands.split('\n') if cmd.strip()]
        
        # Return as a single command if parsing failed
        return [commands.strip()] if commands.strip() else ['']

def process_terminal_output(text):
    '''
    处理终端输出，保留 ANSI 转义序列并正确处理行覆盖
    (Process terminal output, preserve ANSI escape sequences and correctly handle line overwriting)
    处理规则：(Processing rules:)
    1. 保留所有 ANSI 转义序列（\x1b[...m 颜色，\x1b[...G 光标移动等）
       (Preserve all ANSI escape sequences (\x1b[...m colors, \x1b[...G cursor movement, etc.))
    2. 处理 \r 的行内覆盖效果
       (Handle line overwriting effect of \r)
    3. 处理光标控制序列的行内覆盖效果
       (Handle line overwriting effect of cursor control sequences)
    '''
    if not text:
        return ""
    
    lines = text.split('\n')
    result = []
    
    for line in lines:
        # Handle carriage returns (line overwriting)
        if '\r' in line:
            # Split the line by carriage returns and only keep the latest version
            parts = line.split('\r')
            processed_line = parts[-1]
            
            # If any ANSI color sequences were used in earlier parts, preserve them
            for i in range(len(parts) - 1):
                ansi_colors = extract_ansi_colors(parts[i])
                if ansi_colors and not have_matching_ansi_reset(parts[-1]):
                    processed_line = ansi_colors + processed_line
            
            result.append(processed_line)
        else:
            # Handle cursor movement escape sequences for line editing
            # This is a simplified version - full implementation would need state tracking
            processed_line = process_cursor_movements(line)
            result.append(processed_line)
    
    return '\n'.join(result)

def extract_ansi_colors(text):
    """
    Extract ANSI color sequences from a text.
    
    Args:
        text: The text to extract colors from
        
    Returns:
        str: Concatenated color sequences found in the text
    """
    import re
    
    # Find all ANSI color sequences
    color_pattern = r'\x1b\[\d+(;\d+)*m'
    colors = re.findall(color_pattern, text)
    
    # Return concatenated colors
    return ''.join(colors)

def have_matching_ansi_reset(text):
    """
    Check if the text has a matching ANSI reset sequence.
    
    Args:
        text: The text to check
        
    Returns:
        bool: True if there's a reset sequence, False otherwise
    """
    return '\x1b[0m' in text or '\x1b[m' in text

def process_cursor_movements(line):
    """
    Process cursor movement escape sequences.
    
    Args:
        line: Line to process
        
    Returns:
        str: Processed line with cursor movements applied
    """
    import re
    
    # This is a simplified implementation
    # Handles only the most common cursor movement: \x1b[nG (move to column n)
    
    # Find all cursor column positioning commands
    cursor_pattern = r'\x1b\[(\d+)G'
    matches = list(re.finditer(cursor_pattern, line))
    
    if not matches:
        return line
    
    # Process the line from right to left, applying cursor movements
    result = list(line)
    for match in reversed(matches):
        col = int(match.group(1)) - 1  # Convert to 0-based indexing
        cmd_start = match.start()
        cmd_end = match.end()
        
        # Remove the command
        for i in range(cmd_start, cmd_end):
            result[i] = ''
        
        # If there's anything to the right of this position, 
        # we'd need to move cursor and overwrite - simplified implementation
        # just removes the command for now
    
    return ''.join(result)