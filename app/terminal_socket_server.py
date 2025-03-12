import asyncio
import json  # Not directly used but kept for bytecode consistency
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
        
        # Dictionary to track running tasks by action_id
        tasks = {}
        
        # Helper function to cleanup tasks when connection closes
        def stop_all_tasks():
            for task in tasks.values():
                task.cancel()
        
        # Helper function to receive and process messages
        async def get_socket_message():
            try:
                # Get JSON message directly
                msg_data = await ws.receive_json()
                
                try:
                    # Validate message using model_validate
                    msg = TerminalInputMessage.model_validate(msg_data)
                    logger.info(f"Got message: {msg_data}")
                    
                    # Create task to handle the message
                    task = asyncio.create_task(self.handle_msg(msg, ws))
                    tasks[msg.action_id] = task
                    
                    # Add callback to remove task when done
                    task.add_done_callback(lambda task: tasks.pop(msg.action_id))
                except ValidationError as e:
                    logger.error(f"Invalid message: {msg_data}, {e}")
                    await self.send_resp(ws, TerminalOutputMessage(
                        action_id="",
                        type="error",
                        result=f"Invalid message: {e}",
                        output=[],
                        terminal_status="unknown",
                        terminal=""
                    ))
            except Exception as e:
                logger.error(f"Error handling message: {e}")
        
        try:
            # Process messages continuously
            while True:
                await get_socket_message()
        except WebSocketDisconnect:
            logger.info("Websocket disconnected")
        except Exception as e:
            logger.error(e)
            logger.error(f"Error: {e}")
            logger.info("Closing websocket")
            await ws.close()
            
        # Clean up any remaining tasks
        stop_all_tasks()
    
    async def send_resp(self, ws: WebSocket, resp: TerminalOutputMessage):
        """
        Send a response to the client over the WebSocket connection.
        
        Args:
            ws: The WebSocket connection
            resp: The response data to send
        """
        logger.info(f"Sending resp {resp}")
        try:
            # Use model_dump() method instead of manual JSON serialization
            await ws.send_json(resp.model_dump())
        except RuntimeError as e:
            logger.error(f"Error sending resp: {e}")
    
    async def handle_msg(self, msg: TerminalInputMessage, ws: WebSocket):
        """
        Handle an incoming message from the client.
        
        Args:
            msg: The validated terminal input message
            ws: The WebSocket connection
        """
        logger.info(f"Handle terminal socket msg#{msg.action_id} {msg}")
        
        # Direct call to _do_handle_msg without additional validation
        await self._do_handle_msg(msg, ws)
        
        logger.info(f"Finished handling msg#{msg.action_id}")
    
    async def _do_handle_msg(self, msg: TerminalInputMessage, ws: WebSocket):
        """
        Process a validated terminal input message.
        
        Args:
            msg: The validated terminal input message
            ws: The WebSocket connection
        """
        terminal_id = msg.terminal
        action_id = msg.action_id
        
        # Get or create terminal instance
        terminal = await terminal_manager.create_or_get_terminal(terminal_id)
        
        # Handle different message types
        if msg.type == "reset":
            # Reset the terminal
            await terminal.reset()
            response = msg.create_response(
                type="action_finish",
                result="terminal reset success",
                output=[],
                terminal_status="idle"
            )
            await self.send_resp(ws, response)
            
        elif msg.type == "reset_all":
            # Reset all terminals
            for term in terminal_manager.terminals.values():
                await term.reset()
            
            response = msg.create_response(
                type="action_finish",
                result="all terminals reset success",
                output=[],
                terminal_status="idle"
            )
            await self.send_resp(ws, response)
            
        elif msg.type == "view":
            # View full terminal history
            terminal_status: TerminalStatus = "running" if terminal.is_running else "idle"
            
            logger.info(f"Sending history: {terminal.get_history(True, True)}")
            
            response = msg.create_response(
                type="history",
                result=None,
                output=terminal.get_history(True, True),  # True for include_prompt, True for is_full
                terminal_status=terminal_status
            )
            await self.send_resp(ws, response)
            
        elif msg.type == "view_last":
            # View only the most recent terminal output
            terminal_status: TerminalStatus = "running" if terminal.is_running else "idle"
            
            logger.info(f"Sending last history: {terminal.get_history(True, False)}")
            
            response = msg.create_response(
                type="history",
                result=None,
                output=terminal.get_history(True, False),  # True for include_prompt, False for not is_full
                terminal_status=terminal_status
            )
            await self.send_resp(ws, response)
            
        elif msg.type == "kill_process":
            # Kill the current process in the terminal
            await terminal.kill_process()
            
            response = msg.create_response(
                type="action_finish",
                result="process killed",
                output=terminal.get_history(True, False),
                terminal_status="idle"
            )
            await self.send_resp(ws, response)
            
        elif msg.type == "command":
            # Execute a command in the terminal
            if not msg.command:
                response = msg.create_response(
                    type="error",
                    result="must provide command",
                    output=[],
                    terminal_status="idle"
                )
                await self.send_resp(ws, response)
                return
            
            # Set working directory if provided
            if msg.exec_dir:
                if not await terminal.set_working_directory(msg.exec_dir):
                    response = msg.create_response(
                        type="error",
                        result=f"Failed to change directory to {msg.exec_dir}",
                        output=[],
                        terminal_status="idle"
                    )
                    await self.send_resp(ws, response)
                    return
            
            # Default to "run" mode if not specified
            if not msg.mode:
                msg.mode = "run"
                
            # Handle different command modes
            if msg.mode == "send_key":
                await terminal.send_key(msg)
                terminal_status: TerminalStatus = "idle" if not terminal.is_running else "running"
                response = msg.create_response(
                    type="action_finish",
                    result=f"Key sent: {msg.command}",
                    output=terminal.get_history(True, False),
                    terminal_status=terminal_status
                )
                await self.send_resp(ws, response)
                
            elif msg.mode == "send_line":
                await terminal.send_line(msg)
                terminal_status: TerminalStatus = "idle" if not terminal.is_running else "running"
                response = msg.create_response(
                    type="action_finish",
                    result=f"Line sent: {msg.command}",
                    output=terminal.get_history(True, False),
                    terminal_status=terminal_status
                )
                await self.send_resp(ws, response)
                
            elif msg.mode == "send_control":
                await terminal.send_control(msg)
                terminal_status: TerminalStatus = "idle" if not terminal.is_running else "running"
                response = msg.create_response(
                    type="action_finish",
                    result=f"Control character sent: {msg.command}",
                    output=terminal.get_history(True, False),
                    terminal_status=terminal_status
                )
                await self.send_resp(ws, response)
                
            elif msg.mode == "run":
                # Execute the command and yield responses
                async for result in terminal.execute_command(msg):
                    await self.send_resp(ws, result)
            else:
                # Invalid mode
                response = msg.create_response(
                    type="error",
                    result=f"Invalid mode: {msg.mode}",
                    output=[],
                    terminal_status="idle"
                )
                await self.send_resp(ws, response)
        else:
            # Unknown message type
            logger.error(f"Invalid message type: {msg.type}")
            response = msg.create_response(
                type="error",
                result=f"Invalid message type: {msg.type}",
                output=[],
                terminal_status="idle"
            )
            await self.send_resp(ws, response)