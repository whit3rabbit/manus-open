import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from signal import SIGTERM
from typing import Any, AsyncGenerator, cast

import pexpect
from pexpect.expect import searcher_re

from app.helpers.utils import truncate_text_from_back
from app.logger import logger
from app.types.messages import (
    TerminalInputMessage,
    TerminalOutputMessage,
    TerminalOutputMessageType,
    TerminalStatus
)
from app.tools.base import DEFAULT_USER, DEFAULT_WORKING_DIR, IS_INSIDE_CONTAINER
from app.tools.terminal.expecter import MyExpecter
from app.tools.terminal.terminal_helpers import process_terminal_output, split_bash_commands

# Constants for terminal configuration
PS1 = '[CMD_BEGIN]\\n\\u@\\h:\\w\\n[CMD_END]'
PS1_REG = '\\[CMD_BEGIN\\]\\s*(.*?)\\s*([a-z0-9_-]*)@([a-zA-Z0-9.-]*):(.+)\\s*\\[CMD_END\\]'
COLUMNS = 80
GREEN = '\x1b[32m'
RESET = '\x1b[0m'


class TerminalManager:
    def __init__(self):
        self.terminals = {}

    async def create_or_get_terminal(self, name: str) -> 'Terminal':
        """Create a new terminal or return existing one"""
        if name not in self.terminals:
            terminal = Terminal(name, DEFAULT_WORKING_DIR)
            await terminal.init()
            self.terminals[name] = terminal
        return self.terminals[name]

    def remove_terminal(self, name: str):
        """Remove a terminal"""
        if name in self.terminals:
            terminal = self.terminals[name]
            if terminal.is_alive():
                terminal.shell.terminate()
            del self.terminals[name]


@dataclass
class TerminalHistoryItem:
    pre_prompt: str
    after_prompt: str
    command: str
    timestamp: float
    finished: bool
    text: str


class Terminal:
    name: str
    shell: 'pexpect.spawn[Any]'
    history: list[TerminalHistoryItem]
    is_running = False
    user_input_buffer = ''
    prompt_string = ''

    def __init__(self, name: str, default_wd: str):
        self.name = name
        self.default_wd = default_wd

    async def init(self, wd: str = None):
        self.history = []
        self.is_running = False
        self.user_input_buffer = ''
        
        command = f'sudo su {DEFAULT_USER}'
        if not IS_INSIDE_CONTAINER:
            command = '/bin/bash --norc --noprofile'
            
        logger.info(f'Initializing terminal {self.name} with command: {command}')
        
        self.shell = pexpect.spawn(
            command,
            encoding='utf-8',
            codec_errors='replace',
            echo=False,
            cwd=wd or self.default_wd,
            dimensions=(24, COLUMNS),
            maxread=4096
        )
        
        if IS_INSIDE_CONTAINER:
            await self.shell.expect(['\\$|\\#'], async_=True)
        else:
            await self.shell.expect(['.*'], async_=True)
            
        setup_commands = [
            f'export PS1="{PS1}"; export PS2=""',
            'export TERM=xterm-256color'
        ]
        
        for cmd in setup_commands:
            self.shell.sendline(cmd)
            await self.shell.expect(PS1_REG, async_=True)
            
        logger.info(f'Terminal {self.name} initialized')
        return self

    async def reset(self):
        if self.shell and not self.shell.terminated:
            self.shell.sendcontrol('c')
            self.shell.terminate()
            
        await asyncio.sleep(0.1)
        await self.init()

    def get_history(self, append_prompt_line: bool, full_history: bool) -> list[str]:
        max_text_length = 5000
        max_total_length = 10000
        
        if not self.history:
            if full_history:
                return [self.get_prompt_string()]
            else:
                return []
                
        if not full_history:
            last_item = self.history[-1]
            truncated_text = truncate_text_from_back(last_item.text, max_text_length)
            result = f"{last_item.pre_prompt} {last_item.command}\n{truncated_text}"
            
            if last_item.finished and append_prompt_line:
                result += f"\n{last_item.after_prompt}"
                
            return [result]
            
        result = []
        total_length = 0
        
        for i, item in enumerate(self.history):
            cmd_str = f"{item.pre_prompt} {item.command}"
            truncated_text = truncate_text_from_back(item.text, max_text_length)
            line = f"{cmd_str}\n{truncated_text}"
            
            if i == len(self.history) - 1 and item.finished and append_prompt_line:
                line += f"\n{item.after_prompt}"
                
            if total_length + len(line) > max_total_length:
                break
                
            result.append(line)
            total_length += len(line)
            
        return result

    async def execute_command(self, cmd_msg: TerminalInputMessage) -> AsyncGenerator[TerminalOutputMessage, None]:
        """Execute a command in the terminal"""
        if cmd_msg.mode != "run":
            raise AssertionError("mode mismatch")
            
        if self.is_running:
            yield cmd_msg.create_response(
                "error", 
                "Previous command not finished in this terminal, abort the previous one use another terminal.",
                [],
                "idle"
            )
            return
            
        self.is_running = True
        cmd = cmd_msg.command
        
        if not cmd:
            raise AssertionError("command must be defined")
            
        if cmd_msg.exec_dir:
            cmd = f'cd {cmd_msg.exec_dir} && {cmd}'
            
        logger.info(f'Executing command in terminal {self.name}: {cmd}')
        
        commands = split_bash_commands(cmd)
        output = ""
        
        history_item = TerminalHistoryItem(
            pre_prompt=self.get_prompt_string(),
            after_prompt="",
            command=cmd,
            timestamp=datetime.now().timestamp(),
            finished=False,
            text=""
        )
        
        self.add_history(history_item)
        
        for i, command in enumerate(commands):
            results = []
            last_output = ""
            
            async for is_done, cmd_output in self._do_execute_command(command):
                if history_item not in self.history:
                    return
                    
                logger.info(f"Command is_done: {is_done}, output: {cmd_output}")
                results.append(cmd_output)
                processed_output = process_terminal_output("".join(results))
                
                if not is_done and processed_output == last_output:
                    continue
                    
                last_output = processed_output
                processed_output = output + processed_output
                update_type = "update"
                
                if is_done:
                    is_last = i == len(commands) - 1
                    update_type = "finish" if is_last else "partial_finish"
                    
                status = "idle" if update_type == "finish" else "running"
                
                history_item.text = processed_output
                
                if update_type == "finish":
                    self.update_prompt_str()
                    history_item.finished = True
                    history_item.after_prompt = self.get_prompt_string()
                    
                history_lines = self.get_history(True, False)
                
                yield cmd_msg.create_response(
                    update_type,
                    None,
                    history_lines,
                    status,
                    i
                )
                
                if is_done:
                    output = processed_output
                    results = []
        
        self.is_running = False
        self.shell.sendline()
        await self.shell.expect(PS1_REG, async_=True)
        logger.info(f"Execute finish: {cmd}")

    async def kill_process(self):
        _wd = self._wd
        
        self.shell.kill(SIGTERM)
        await asyncio.sleep(0.1)
        
        saved_history = self.history
        await self.init(_wd)
        self.history = saved_history
        
        for item in self.history:
            item.finished = True

    async def send_control(self, cmd_msg: TerminalInputMessage):
        if cmd_msg.mode != "send_control":
            raise AssertionError("mode mismatch")
            
        if not self.is_running:
            return cmd_msg.create_response(
                "error",
                "Terminal not running. Must use send_control on running terminal",
                [],
                "idle"
            )
            
        cmd = cmd_msg.command
        if not cmd:
            raise AssertionError("command must be defined")
            
        if len(cmd) != 1:
            return cmd_msg.create_response(
                "error",
                "Control command must be a single character",
                [],
                "running"
            )
            
        self.user_input_buffer = f"^{cmd.upper()}"
        self.shell.sendcontrol(cmd)
        
        return cmd_msg.create_response(
            "action_finish",
            f"control '{cmd}' sent to the terminal",
            self.get_history(True, False),
            "running"
        )

    async def write_to_process(self, text: str, enter: bool):
        if enter:
            self.user_input_buffer = text + "\n"
            self.shell.sendline(text)
        else:
            self.user_input_buffer = text
            self.shell.send(text)

    async def send_key(self, cmd_msg: TerminalInputMessage):
        if cmd_msg.mode != "send_key":
            raise AssertionError("mode mismatch")
            
        if not self.is_running:
            return cmd_msg.create_response(
                "error",
                "Terminal not running. Must use send_key on running terminal",
                [],
                "idle"
            )
            
        key = cmd_msg.command
        if not key:
            raise AssertionError("command must be defined")
            
        self.user_input_buffer = key
        self.shell.send(key)
        
        return cmd_msg.create_response(
            "action_finish",
            f"key '{key}' sent to the terminal",
            self.get_history(True, False),
            "running"
        )

    async def send_line(self, cmd_msg: TerminalInputMessage):
        if cmd_msg.mode != "send_line":
            raise AssertionError("mode mismatch")
            
        if not self.is_running:
            return cmd_msg.create_response(
                "error",
                "Terminal not running. Must use send_line on running terminal",
                [],
                "idle"
            )
            
        line = cmd_msg.command
        if not line:
            raise AssertionError("command must be defined")
            
        self.user_input_buffer = line + "\n"
        self.shell.sendline(line)
        
        return cmd_msg.create_response(
            "action_finish",
            f"string '{line}\\n' sent to the terminal",
            self.get_history(True, False),
            "running"
        )

    def add_history(self, history: TerminalHistoryItem):
        """Add a command output to the history"""
        self.history.append(history)
        if len(self.history) > 100:
            self.history.pop(0)

    def get_prompt_string(self) -> str:
        if not self.prompt_string:
            self.update_prompt_str()
        return self.prompt_string

    def update_prompt_str(self):
        self.prompt_string = self._do_get_prompt_from_shell()

    def _do_get_prompt_from_shell(self) -> str:
        """
        构造一个 ps1 字符串
        类似: ubuntu@host:/home $
        """
        after = cast(str, self.shell.after)
        
        if not after:
            logger.warning("Failed to get ps1, using default. this should not happen")
            return f"{GREEN}${RESET}"
            
        match = re.match(PS1_REG, after)
        if not match:
            raise AssertionError(f"Failed to parse bash prompt: {after}. This should not happen.")
            
        status, username, hostname, path = match.groups()
        path = path.rstrip()
        self._wd = os.path.expanduser(path)
        
        prompt = f"{status}{username}@sandbox:{path} "
        if username == "root":
            prompt += "#"
        else:
            prompt += "$"
            
        return f"{GREEN}{prompt}{RESET}"

    async def _do_execute_command(self, command: str) -> AsyncGenerator[tuple[bool, str], None]:
        shell = self.shell
        shell.sendline(command)
        
        expecter = MyExpecter(shell, searcher_re(shell.compile_pattern_list(PS1_REG)))
        
        def get_user_input():
            buffer = self.user_input_buffer
            self.user_input_buffer = ""
            return buffer
            
        async for is_done, output in expecter.my_expect_loop(PS1_REG, get_user_input):
            logger.debug("\n".join([
                f"[Terminal Updated - {self.name}]",
                f"Finished: {is_done}",
                f"Data:{json.dumps(output)}"
            ]))
            
            yield is_done, output
            
            if is_done:
                break

    async def _do_execute_command_old(self, command: str) -> AsyncGenerator[tuple[bool, str], None]:
        """@deprecated"""
        self.shell.sendline(command)
        
        while True:
            if self.user_input_buffer:
                logger.info(f"[user_input_buffer]\n{json.dumps(self.user_input_buffer)}")
                yield False, self.user_input_buffer
                self.user_input_buffer = ""
                
            try:
                res = self.shell.read_nonblocking(size=4096, timeout=0.01)
                
                if res:
                    match = re.search(PS1_REG, res)
                    
                    if self.user_input_buffer:
                        res = self.user_input_buffer + res
                        self.user_input_buffer = ""
                        
                    logger.info(f"[res]\n{json.dumps(res)}")
                    
                    if match:
                        if res[match.end():]:
                            raise AssertionError(f"content after ps1 mark, this should not happen, res:{json.dumps(res)}")
                            
                        yield True, res[:match.start()]
                        return
                        
                    yield False, res
            except pexpect.TIMEOUT:
                pass
            except pexpect.EOF:
                yield (True, "")
                return
                
            await asyncio.sleep(0.2)

    def is_alive(self) -> bool:
        """Check if the terminal process is still alive"""
        return self.shell.isalive()


# Initialize a global terminal manager
terminal_manager = TerminalManager()