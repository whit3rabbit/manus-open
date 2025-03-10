import asyncio
from typing import Any
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from logger import logger
from tools.terminal import terminal_manager
from types.messages import TerminalInputMessage, TerminalOutputMessage, TerminalStatus

class TerminalSocketServer:
    
    async def handle_connection(self, ws):
        pass
    
    async def send_resp(self, ws, resp):
        pass
    
    async def handle_msg(self, msg, ws):
        pass
    
    async def do_handle_msg(self, msg, ws):
        pass