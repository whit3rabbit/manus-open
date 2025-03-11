import asyncio
import json
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.logger import logger
from app.tools.terminal import terminal_manager
from app.types.messages import TerminalInputMessage, TerminalOutputMessage, TerminalStatus

class TerminalSocketServer:
    """
    WebSocket server for handling terminal connections.
    This class manages bidirectional communication with terminals through WebSockets.
    """
    
    async def handle_connection(self, ws: WebSocket):
        """
        Handle a new WebSocket connection for terminal interaction.
        
        Args:
            ws: The WebSocket connection
        """
        await ws.accept()
        logger.info("New terminal WebSocket connection established")
        
        try:
            while True:
                # Wait for messages from the client
                msg_text = await ws.receive_text()
                
                try:
                    # Parse the message
                    msg_data = json.loads(msg_text)
                    await self.handle_msg(msg_data, ws)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON received: {msg_text}")
                    await self.send_resp(ws, {
                        "type": "error",
                        "terminal": "",
                        "action_id": "",
                        "result": "Invalid JSON message",
                        "output": [],
                        "terminal_status": "idle"
                    })
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    await self.send_resp(ws, {
                        "type": "error",
                        "terminal": "",
                        "action_id": "",
                        "result": f"Error: {str(e)}",
                        "output": [],
                        "terminal_status": "idle"
                    })
        except WebSocketDisconnect:
            logger.info("Terminal WebSocket connection closed")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
    
    async def send_resp(self, ws: WebSocket, resp: Dict[str, Any]):
        """
        Send a response to the client over the WebSocket connection.
        
        Args:
            ws: The WebSocket connection
            resp: The response data to send
        """
        try:
            await ws.send_text(json.dumps(resp))
        except Exception as e:
            logger.error(f"Error sending response: {e}")
    
    async def handle_msg(self, msg: Dict[str, Any], ws: WebSocket):
        """
        Handle an incoming message from the client.
        
        Args:
            msg: The message data
            ws: The WebSocket connection
        """
        try:
            # Validate and parse the message using the Pydantic model
            terminal_msg = TerminalInputMessage(**msg)
            await self.do_handle_msg(terminal_msg, ws)
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            await self.send_resp(ws, {
                "type": "error",
                "terminal": msg.get("terminal", ""),
                "action_id": msg.get("action_id", ""),
                "result": f"Invalid message format: {str(e)}",
                "output": [],
                "terminal_status": "idle"
            })
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self.send_resp(ws, {
                "type": "error",
                "terminal": msg.get("terminal", ""),
                "action_id": msg.get("action_id", ""),
                "result": f"Error: {str(e)}",
                "output": [],
                "terminal_status": "idle"
            })
    
    async def do_handle_msg(self, msg: TerminalInputMessage, ws: WebSocket):
        """
        Process a validated terminal input message.
        
        Args:
            msg: The validated terminal input message
            ws: The WebSocket connection
        """
        terminal_id = msg.terminal
        action_id = msg.action_id
        
        # Handle different message types
        if msg.type == "reset":
            # Reset the terminal
            terminal = await terminal_manager.create_or_get_terminal(terminal_id)
            await terminal.reset()
            response = TerminalOutputMessage(
                type="action_finish",
                terminal=terminal_id,
                action_id=action_id,
                result="Terminal reset",
                output=terminal.get_history(True, False),
                terminal_status="idle",
                sub_command_index=0
            )
            await self.send_resp(ws, response.dict())
            
        elif msg.type == "reset_all":
            # Reset all terminals
            for term_id in list(terminal_manager.terminals.keys()):
                terminal = terminal_manager.terminals[term_id]
                await terminal.reset()
            
            response = TerminalOutputMessage(
                type="action_finish",
                terminal=terminal_id,
                action_id=action_id,
                result="All terminals reset",
                output=[],
                terminal_status="idle",
                sub_command_index=0
            )
            await self.send_resp(ws, response.dict())
            
        elif msg.type == "view" or msg.type == "view_last":
            # View terminal content
            terminal = await terminal_manager.create_or_get_terminal(terminal_id)
            is_full = msg.type == "view"
            
            terminal_status: TerminalStatus = "idle" if not terminal.is_running else "running"
            response = TerminalOutputMessage(
                type="history",
                terminal=terminal_id,
                action_id=action_id,
                result="",
                output=terminal.get_history(True, is_full),
                terminal_status=terminal_status,
                sub_command_index=0
            )
            await self.send_resp(ws, response.dict())
            
        elif msg.type == "kill_process":
            # Kill the current process in the terminal
            terminal = await terminal_manager.create_or_get_terminal(terminal_id)
            await terminal.kill_process()
            
            response = TerminalOutputMessage(
                type="action_finish",
                terminal=terminal_id,
                action_id=action_id,
                result="Process killed",
                output=terminal.get_history(True, False),
                terminal_status="idle",
                sub_command_index=0
            )
            await self.send_resp(ws, response.dict())
            
        elif msg.type == "command":
            # Execute a command in the terminal
            if not msg.command:
                response = TerminalOutputMessage(
                    type="error",
                    terminal=terminal_id,
                    action_id=action_id,
                    result="Command cannot be empty",
                    output=[],
                    terminal_status="idle",
                    sub_command_index=0
                )
                await self.send_resp(ws, response.dict())
                return
            
            terminal = await terminal_manager.create_or_get_terminal(terminal_id)
            
            # Set working directory if provided
            if msg.exec_dir:
                if not await terminal.set_working_directory(msg.exec_dir):
                    response = TerminalOutputMessage(
                        type="error",
                        terminal=terminal_id,
                        action_id=action_id,
                        result=f"Failed to change directory to {msg.exec_dir}",
                        output=[],
                        terminal_status="idle",
                        sub_command_index=0
                    )
                    await self.send_resp(ws, response.dict())
                    return
            
            # Handle different command modes
            if msg.mode == "send_key":
                await terminal.send_key(msg)
                terminal_status: TerminalStatus = "idle" if not terminal.is_running else "running"
                response = TerminalOutputMessage(
                    type="action_finish",
                    terminal=terminal_id,
                    action_id=action_id,
                    result=f"Key sent: {msg.command}",
                    output=terminal.get_history(True, False),
                    terminal_status=terminal_status,
                    sub_command_index=0
                )
                await self.send_resp(ws, response.dict())
                
            elif msg.mode == "send_line":
                await terminal.send_line(msg)
                terminal_status: TerminalStatus = "idle" if not terminal.is_running else "running"
                response = TerminalOutputMessage(
                    type="action_finish",
                    terminal=terminal_id,
                    action_id=action_id,
                    result=f"Line sent: {msg.command}",
                    output=terminal.get_history(True, False),
                    terminal_status=terminal_status,
                    sub_command_index=0
                )
                await self.send_resp(ws, response.dict())
                
            elif msg.mode == "send_control":
                await terminal.send_control(msg)
                terminal_status: TerminalStatus = "idle" if not terminal.is_running else "running"
                response = TerminalOutputMessage(
                    type="action_finish",
                    terminal=terminal_id,
                    action_id=action_id,
                    result=f"Control character sent: {msg.command}",
                    output=terminal.get_history(True, False),
                    terminal_status=terminal_status,
                    sub_command_index=0
                )
                await self.send_resp(ws, response.dict())
                
            else:  # Default to "run" mode
                # Execute the command
                result = await terminal.execute_command(msg)
                
                # Send the final response
                if result:
                    response = TerminalOutputMessage(
                        type="finish",
                        terminal=terminal_id,
                        action_id=action_id,
                        result=result,
                        output=terminal.get_history(True, False),
                        terminal_status="idle",
                        sub_command_index=0
                    )
                    await self.send_resp(ws, response.dict())
                else:
                    # If no result, the command might still be running
                    # Send an update with the current status
                    response = TerminalOutputMessage(
                        type="update",
                        terminal=terminal_id,
                        action_id=action_id,
                        result="",
                        output=terminal.get_history(True, False),
                        terminal_status="running",
                        sub_command_index=0
                    )
                    await self.send_resp(ws, response.dict())
        else:
            # Unknown message type
            response = TerminalOutputMessage(
                type="error",
                terminal=terminal_id,
                action_id=action_id,
                result=f"Unknown message type: {msg.type}",
                output=[],
                terminal_status="idle",
                sub_command_index=0
            )
            await self.send_resp(ws, response.dict())