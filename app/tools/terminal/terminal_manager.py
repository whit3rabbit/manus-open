import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from signal import SIGTERM
from typing import Any, AsyncGenerator, Dict, List, Optional, cast

import pexpect
from pexpect.expect import searcher_re

from app.helpers.utils import truncate_text_from_back
from app.logger import logger
from app.tools.base import DEFAULT_USER, DEFAULT_WORKING_DIR, IS_INSIDE_CONTAINER
from app.tools.terminal.expecter import MyExpecter
from app.tools.terminal.terminal_helpers import process_terminal_output, split_bash_commands
from app.types.messages import (
    TerminalInputMessage,
    TerminalOutputMessage,
    TerminalOutputMessageType,
    TerminalStatus
)

# Constants for terminal configuration
PS1 = '[CMD_BEGIN]\\n\\u@\\h:\\w\\n[CMD_END]'
PS1_REG = '\\[CMD_BEGIN\\]\\s*(.*?)\\s*([a-z0-9_-]*)@([a-zA-Z0-9.-]*):(.+)\\s*\\[CMD_END\\]'
COLUMNS = 80
GREEN = '\x1b[32m'
RESET = '\x1b[0m'

class TerminalManager:
    """
    Manages multiple terminal instances.
    """
    
    def __init__(self):
        self.terminals: Dict[str, Terminal] = {}

    async def create_or_get_terminal(self, name: str) -> 'Terminal':
        """
        Create a new terminal or return an existing one.
        
        Args:
            name: The terminal identifier
            
        Returns:
            Terminal: The terminal instance
        """
        if name not in self.terminals:
            terminal = Terminal(name, DEFAULT_WORKING_DIR)
            self.terminals[name] = terminal
            await terminal.init(DEFAULT_WORKING_DIR)
            return terminal
        return self.terminals[name]

    def remove_terminal(self, name: str) -> None:
        """
        Remove a terminal.
        
        Args:
            name: The terminal identifier
        """
        if name in self.terminals:
            terminal = self.terminals[name]
            if terminal.is_alive():
                terminal.shell.terminate()
            del self.terminals[name]

@dataclass
class TerminalHistoryItem:
    """
    Represents a command execution history item in a terminal.
    """
    command: str
    text: str
    pre_prompt: str
    after_prompt: str
    finished: bool
    timestamp: datetime

class Terminal:
    """
    Represents a terminal process with command execution capabilities.
    """
    
    def __init__(self, name: str, default_wd: str):
        """
        Initialize a new Terminal instance.
        
        Args:
            name: The terminal identifier
            default_wd: The default working directory
        """
        self.name = name
        self.default_wd = default_wd
        self.shell = None
        self.history: List[TerminalHistoryItem] = []
        self.is_running = False
        self.user_input_buffer = ''
        self.prompt_string = ''

    async def init(self, wd: str) -> None:
        """
        Initialize the terminal with a working directory.
        
        Args:
            wd: The working directory to start in
        """
        if self.shell and self.shell.isalive():
            return
            
        # Create a bash shell with environment setup
        env = os.environ.copy()
        env['PS1'] = PS1
        env['TERM'] = 'xterm-256color'
        env['COLUMNS'] = str(COLUMNS)
        env['PATH'] = env.get('PATH', '') + ':/usr/local/bin:/usr/bin:/bin'
        
        # Create the pexpect spawn process
        self.shell = pexpect.spawn(
            '/bin/bash',
            ['--norc', '--noprofile'],
            env=env,
            encoding='utf-8',
            echo=False,
            timeout=None
        )
        
        # Set the window size
        self.shell.setwinsize(24, COLUMNS)
        
        # Change to the specified working directory
        if wd and wd != self.default_wd:
            self.shell.sendline(f'cd {wd}')
            await asyncio.sleep(0.1)
        
        # Initialize the prompt
        self.shell.sendline('echo "Terminal initialized"')
        await asyncio.sleep(0.1)
        
        # Update the prompt string
        self.update_prompt_str()
        
        logger.info(f"Terminal {self.name} initialized in directory {wd}")

    async def reset(self) -> None:
        """
        Reset the terminal by terminating and restarting it.
        """
        if self.shell and self.shell.isalive():
            self.shell.terminate()
            
        # Clear history
        self.history = []
        self.is_running = False
        self.user_input_buffer = ''
        self.prompt_string = ''
        
        # Reinitialize
        await self.init(self.default_wd)
        logger.info(f"Terminal {self.name} reset")

    async def set_working_directory(self, directory: str) -> bool:
        """
        Change the terminal's working directory.
        
        Args:
            directory: The directory to change to
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.shell or not self.shell.isalive():
            await self.init(self.default_wd)
            
        try:
            # Send cd command
            self.shell.sendline(f'cd "{directory}"')
            
            # Wait for prompt
            await asyncio.sleep(0.2)
            
            # Check if the directory exists by executing pwd
            self.shell.sendline('pwd')
            await asyncio.sleep(0.2)
            
            # Update prompt
            self.update_prompt_str()
            
            return True
        except Exception as e:
            logger.error(f"Error changing directory: {e}")
            return False

    def get_history(self, append_prompt_line: bool, full_history: bool) -> List[str]:
        """
        Get the command execution history.
        
        Args:
            append_prompt_line: Whether to append the prompt line at the end
            full_history: Whether to return the full history or just the latest
            
        Returns:
            List[str]: The history lines
        """
        max_text_length = 5000
        max_total_length = 10000
        
        if not self.history:
            if full_history:
                return [f"Terminal {self.name} has no history yet", self.get_prompt_string()]
            else:
                return [self.get_prompt_string()]
        
        if not full_history:
            # Return only the last item
            last_item = self.history[-1]
            truncated_text = truncate_text_from_back(last_item.text, max_text_length)
            result = f"{last_item.pre_prompt} {last_item.command}\n{truncated_text}"
            
            if last_item.finished and append_prompt_line:
                result += f"\n{last_item.after_prompt}"
                
            return [result]
        
        # Return full history
        result = []
        total_length = 0
        
        # Start from the latest history and work backwards
        for item in reversed(self.history):
            # Format the history item
            truncated_text = truncate_text_from_back(item.text, max_text_length)
            formatted_item = f"{item.pre_prompt} {item.command}\n{truncated_text}"
            
            if item.finished:
                formatted_item += f"\n{item.after_prompt}"
                
            item_length = len(formatted_item)
            
            # Check if adding this item would exceed the maximum length
            if total_length + item_length > max_total_length:
                result.append("... earlier history truncated ...")
                break
                
            result.append(formatted_item)
            total_length += item_length
        
        # Reverse to get chronological order
        result.reverse()
        
        # Add current prompt if needed
        if append_prompt_line and (not self.history or self.history[-1].finished):
            result.append(self.get_prompt_string())
            
        return result

    async def execute_command(self, cmd_msg: TerminalInputMessage) -> str:
        """
        Execute a command in the terminal.
        
        Args:
            cmd_msg: The command message
            
        Returns:
            str: Result message
        """
        if not self.shell or not self.shell.isalive():
            await self.init(self.default_wd)
            
        if self.is_running:
            return "A command is already running in this terminal"
            
        command = cmd_msg.command.strip()
        if not command:
            return "Empty command"
            
        # Split the command into separate commands if needed
        commands = split_bash_commands(command)
        result = ""
        
        for i, cmd in enumerate(commands):
            if cmd.strip():
                self.is_running = True
                result = await self._do_execute_command(cmd)
                self.is_running = False
                
        return result

    async def kill_process(self) -> None:
        """
        Kill the current process running in the terminal.
        """
        if not self.shell or not self.shell.isalive():
            return
            
        try:
            # Send SIGTERM signal
            self.shell.kill(SIGTERM)
            await asyncio.sleep(0.2)
            
            # If still alive, force termination
            if self.shell.isalive():
                self.shell.terminate(force=True)
                
            # Reinitialize the shell
            await self.init(self.default_wd)
            
            self.is_running = False
            logger.info(f"Process killed in terminal {self.name}")
        except Exception as e:
            logger.error(f"Error killing process: {e}")

    async def send_control(self, cmd_msg: TerminalInputMessage) -> None:
        """
        Send a control character to the terminal.
        
        Args:
            cmd_msg: The command message containing the control character
        """
        if not self.shell or not self.shell.isalive():
            await self.init(self.default_wd)
            
        control_char = cmd_msg.command.strip().lower()
        
        if control_char == 'c':
            self.shell.sendcontrol('c')
        elif control_char == 'd':
            self.shell.sendcontrol('d')
        elif control_char == 'z':
            self.shell.sendcontrol('z')
        else:
            logger.warning(f"Unsupported control character: {control_char}")
            
        await asyncio.sleep(0.2)
        self.update_prompt_str()

    async def write_to_process(self, text: str, enter: bool = True) -> None:
        """
        Write text to the terminal process.
        
        Args:
            text: The text to write
            enter: Whether to send an enter key after the text
        """
        if not self.shell or not self.shell.isalive():
            await self.init(self.default_wd)
            
        if enter:
            self.shell.sendline(text)
        else:
            self.shell.write(text)
            
        await asyncio.sleep(0.1)
        self.update_prompt_str()

    async def send_key(self, cmd_msg: TerminalInputMessage) -> None:
        """
        Send a specific key to the terminal.
        
        Args:
            cmd_msg: The command message containing the key to send
        """
        if not self.shell or not self.shell.isalive():
            await self.init(self.default_wd)
            
        key = cmd_msg.command.strip()
        
        if key == 'up':
            self.shell.send('\033[A')
        elif key == 'down':
            self.shell.send('\033[B')
        elif key == 'right':
            self.shell.send('\033[C')
        elif key == 'left':
            self.shell.send('\033[D')
        elif key == 'enter':
            self.shell.send('\r')
        elif key == 'esc':
            self.shell.send('\033')
        elif key == 'tab':
            self.shell.send('\t')
        elif key == 'backspace':
            self.shell.send('\b')
        elif key == 'delete':
            self.shell.send('\033[3~')
        else:
            logger.warning(f"Unsupported key: {key}")
            
        await asyncio.sleep(0.1)
        self.update_prompt_str()

    async def send_line(self, cmd_msg: TerminalInputMessage) -> None:
        """
        Send a line of text to the terminal.
        
        Args:
            cmd_msg: The command message containing the line to send
        """
        if not self.shell or not self.shell.isalive():
            await self.init(self.default_wd)
            
        text = cmd_msg.command
        self.shell.sendline(text)
        
        await asyncio.sleep(0.1)
        self.update_prompt_str()

    def add_history(self, history: TerminalHistoryItem) -> None:
        """
        Add a command output to the history.
        
        Args:
            history: The history item to add
        """
        self.history.append(history)
        if len(self.history) > 100:
            self.history.pop(0)

    def get_prompt_string(self) -> str:
        """
        Get the current prompt string.
        
        Returns:
            str: The formatted prompt string
        """
        if not self.prompt_string:
            self.update_prompt_str()
        return self.prompt_string

    def update_prompt_str(self) -> None:
        """
        Update the prompt string from the shell.
        """
        self.prompt_string = self._do_get_prompt_from_shell()

    def _do_get_prompt_from_shell(self) -> str:
        """
        Extract the prompt string from the shell output.
        
        Returns:
            str: The formatted prompt string
        """
        after_text = cast(str, self.shell.after or '')
        
        if not after_text:
            logger.warning('Failed to get ps1, using default. This should not happen')
            return f"{GREEN}${RESET}"
            
        match = re.match(PS1_REG, after_text)
        if not match:
            logger.warning(f'Failed to parse PS1: {after_text}')
            return f"{GREEN}${RESET}"
            
        # Format the prompt using the regex match groups
        username = match.group(2) or DEFAULT_USER
        hostname = match.group(3) or 'localhost'
        path = match.group(4) or '~'
        
        return f"{GREEN}{username}@{hostname}:{path}${RESET} "

    async def _do_execute_command(self, command: str) -> str:
        """
        Execute a command and capture its output.
        
        Args:
            command: The command to execute
            
        Returns:
            str: Result message
        """
        if not self.shell or not self.shell.isalive():
            await self.init(self.default_wd)
            
        # Update prompt before executing
        self.update_prompt_str()
        pre_prompt = self.get_prompt_string()
        
        # Create a new history item
        history_item = TerminalHistoryItem(
            command=command,
            text="",
            pre_prompt=pre_prompt,
            after_prompt="",
            finished=False,
            timestamp=datetime.now()
        )
        
        self.add_history(history_item)
        
        try:
            # Send the command
            self.shell.sendline(command)
            
            # Wait for output and prompt
            output = ""
            timeout = 60  # 60 seconds timeout
            start_time = datetime.now()
            
            while (datetime.now() - start_time).total_seconds() < timeout:
                try:
                    # Try to match the prompt pattern
                    index = self.shell.expect([searcher_re(PS1_REG), pexpect.TIMEOUT, pexpect.EOF], timeout=1)
                    
                    if index == 0:
                        # Got prompt, command finished
                        output += self.shell.before or ''
                        self.update_prompt_str()
                        
                        # Update history item
                        history_item.text = process_terminal_output(output)
                        history_item.after_prompt = self.get_prompt_string()
                        history_item.finished = True
                        
                        self.is_running = False
                        return "Command completed"
                    elif index == 1:
                        # Timeout, command still running
                        output += self.shell.before or ''
                        history_item.text = process_terminal_output(output)
                        continue
                    elif index == 2:
                        # EOF, shell died
                        output += self.shell.before or ''
                        logger.error("Shell process ended unexpectedly")
                        
                        # Reinitialize shell
                        await self.init(self.default_wd)
                        
                        history_item.text = process_terminal_output(output)
                        history_item.after_prompt = self.get_prompt_string()
                        history_item.finished = True
                        
                        self.is_running = False
                        return "Shell process ended unexpectedly"
                        
                except Exception as e:
                    logger.error(f"Error waiting for command output: {e}")
                    history_item.text = process_terminal_output(output)
                    history_item.after_prompt = self.get_prompt_string()
                    history_item.finished = True
                    
                    self.is_running = False
                    return f"Error: {str(e)}"
            
            # Timeout reached
            history_item.text = process_terminal_output(output)
            history_item.after_prompt = self.get_prompt_string()
            history_item.finished = True
            
            self.is_running = False
            return "Command timed out"
            
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            
            # Update history item with error
            history_item.text += f"\nError: {str(e)}"
            history_item.after_prompt = self.get_prompt_string()
            history_item.finished = True
            
            self.is_running = False
            return f"Error: {str(e)}"

    def is_alive(self) -> bool:
        """
        Check if the terminal process is still alive.
        
        Returns:
            bool: True if alive, False otherwise
        """
        return self.shell is not None and self.shell.isalive()

# Initialize a global terminal manager
terminal_manager = TerminalManager()