import asyncio
import math
import mimetypes
import os
import shutil
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Dict, List
import httpx
from fastapi import Body, FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from app.helpers.utils import upload_to_presigned_url, upload_file_parts
from app.logger import logger
from app.models import MultipartUploadRequest, MultipartUploadResponse
from app.router import TimedRoute
from app.terminal_socket_server import TerminalSocketServer
from app.tools.base import ToolError
from app.tools.browser.browser_manager import BrowserDeadError, BrowserManager, PageDeadError
from app.tools.terminal import terminal_manager
from app.tools.text_editor import text_editor
from app.types.messages import BrowserActionRequest, BrowserActionResponse, TerminalApiResponse, TerminalWriteApiRequest, TextEditorAction, TextEditorActionResult

app = FastAPI()
app.router.route_class = TimedRoute
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FileUploadRequest(BaseModel):
    file_path: str
    presigned_url: str

MULTIPART_THRESHOLD = 10485760  # 10MB

@app.post("/upload_file")
async def upload_file(request: FileUploadRequest):
    """Upload a file to a presigned URL."""
    try:
        file_path = request.file_path
        presigned_url = request.presigned_url
        
        if not os.path.exists(file_path):
            return {"status": "error", "message": f"File not found: {file_path}"}
        
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        with open(file_path, 'rb') as f:
            content = f.read()
            
        content_type = "application/octet-stream"
        await upload_to_presigned_url(content, presigned_url, content_type, file_name)
        
        return {
            "status": "success", 
            "message": f"Successfully uploaded {file_name} ({file_size} bytes)"
        }
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/multipart_upload")
async def multipart_upload(request: MultipartUploadRequest):
    """Upload a large file in multiple parts."""
    try:
        file_path = request.file_path
        presigned_urls = request.presigned_urls
        part_size = request.part_size
        
        if not os.path.exists(file_path):
            return MultipartUploadResponse(
                status="error",
                message=f"File not found: {file_path}",
                file_name=os.path.basename(file_path),
                parts_results=[],
                successful_parts=0,
                failed_parts=0
            )
        
        file_name = os.path.basename(file_path)
        MAX_CONCURRENT = 5
        
        results = await upload_file_parts(file_path, presigned_urls, part_size, MAX_CONCURRENT)
        
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        return MultipartUploadResponse(
            status="success" if failed == 0 else "partial",
            message=f"Upload completed: {successful} parts succeeded, {failed} parts failed",
            file_name=file_name,
            parts_results=results,
            successful_parts=successful,
            failed_parts=failed
        )
    except Exception as e:
        logger.error(f"Error in multipart upload: {e}")
        return MultipartUploadResponse(
            status="error",
            message=str(e),
            file_name=os.path.basename(file_path),
            parts_results=[],
            successful_parts=0,
            failed_parts=len(request.presigned_urls)
        )

@app.get("/get_file/{path:path}")
async def get_file(path: str):
    """Return a file for download."""
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    return FileResponse(path)

class DownloadItem(BaseModel):
    url: str
    filename: str

class DownloadRequest(BaseModel):
    files: List[DownloadItem]
    folder: str | None = None

class DownloadResult(BaseModel):
    filename: str
    success: bool
    error: str | None = None

@app.post("/batch_download")
async def batch_download(request: DownloadRequest):
    """Download multiple files to a specified folder."""
    results = []
    folder = request.folder or os.getcwd()
    
    # Ensure the folder exists
    os.makedirs(folder, exist_ok=True)
    
    for item in request.files:
        result = DownloadResult(filename=item.filename, success=False)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(item.url, timeout=30.0)
                if response.status_code == 200:
                    file_path = os.path.join(folder, item.filename)
                    content = response.content
                    with open(file_path, 'wb') as f:
                        f.write(content)
                    result.success = True
                else:
                    result.error = f"HTTP error: {response.status_code}"
        except httpx.TimeoutException:
            result.error = "Download timed out"
        except Exception as e:
            result.error = str(e)
        results.append(result)
    
    return {
        "results": results,
        "success_count": sum(1 for r in results if r.success),
        "error_count": sum(1 for r in results if not r.success)
    }

# Initialize browser manager
browser_manager = BrowserManager()

@app.get("/browser/status")
async def browser_status():
    """Get the status of the browser."""
    try:
        status = await browser_manager.health_check()
        return {"status": "running" if status else "stopped"}
    except Exception as e:
        logger.error(f"Error checking browser status: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/browser/action")
async def browser_action(request: BrowserActionRequest):
    """Execute a browser action."""
    try:
        result = await browser_manager.execute_action(request)
        return BrowserActionResponse(status="success", result=result)
    except BrowserDeadError as e:
        logger.error(f"Browser dead error: {e}")
        return BrowserActionResponse(status="error", error="Browser is not running or has crashed")
    except PageDeadError as e:
        logger.error(f"Page dead error: {e}")
        return BrowserActionResponse(status="error", error="The current browser page is no longer available")
    except Exception as e:
        logger.error(f"Error executing browser action: {e}")
        return BrowserActionResponse(status="error", error=str(e))

@app.post("/text_editor")
async def text_editor_endpoint(action: TextEditorAction):
    """Execute a text editor action."""
    try:
        result = await text_editor.run_action(action)
        return TextEditorActionResult(status="success", **result.dict())
    except Exception as e:
        logger.error(f"Error in text editor: {e}")
        return TextEditorActionResult(status="error", error=str(e), result="")

# Initialize the terminal socket server
terminal_socket_server = TerminalSocketServer()

@app.websocket("/terminal")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket endpoint for terminal connections."""
    await terminal_socket_server.handle_connection(ws)

@app.post("/terminal/{terminal_id}/reset")
async def reset_terminal(terminal_id: str):
    """Reset a specific terminal."""
    try:
        terminal = await terminal_manager.create_or_get_terminal(terminal_id)
        await terminal.reset()
        return TerminalApiResponse(
            status="success",
            output=terminal.get_history(True, False),
            result="Terminal reset successfully",
            terminal_id=terminal_id
        )
    except Exception as e:
        logger.error(f"Error resetting terminal {terminal_id}: {e}")
        return TerminalApiResponse(
            status="error", 
            output=[], 
            result=f"Error: {str(e)}", 
            terminal_id=terminal_id
        )

@app.post("/terminal/reset_all")
async def reset_all_terminals():
    """Reset all terminals."""
    try:
        for terminal_id in list(terminal_manager.terminals.keys()):
            terminal = terminal_manager.terminals[terminal_id]
            await terminal.reset()
        
        return {"status": "success", "message": "All terminals reset successfully"}
    except Exception as e:
        logger.error(f"Error resetting all terminals: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/terminal/{terminal_id}")
async def view_terminal(terminal_id: str, full: bool = False):
    """View the content of a specific terminal."""
    try:
        terminal = await terminal_manager.create_or_get_terminal(terminal_id)
        history = terminal.get_history(True, full)
        
        return TerminalApiResponse(
            status="success",
            output=history,
            result="",
            terminal_id=terminal_id
        )
    except Exception as e:
        logger.error(f"Error viewing terminal {terminal_id}: {e}")
        return TerminalApiResponse(
            status="error", 
            output=[], 
            result=f"Error: {str(e)}", 
            terminal_id=terminal_id
        )

@app.post("/terminal/{terminal_id}/kill")
async def kill_terminal_process(terminal_id: str):
    """Kill the current process in a specific terminal."""
    try:
        terminal = await terminal_manager.create_or_get_terminal(terminal_id)
        await terminal.kill_process()
        
        return TerminalApiResponse(
            status="success",
            output=terminal.get_history(True, False),
            result="Process killed",
            terminal_id=terminal_id
        )
    except Exception as e:
        logger.error(f"Error killing process in terminal {terminal_id}: {e}")
        return TerminalApiResponse(
            status="error", 
            output=[], 
            result=f"Error: {str(e)}", 
            terminal_id=terminal_id
        )

@app.post("/terminal/{terminal_id}/write")
async def write_terminal_process(terminal_id: str, request: TerminalWriteApiRequest):
    """Write text to a terminal process."""
    try:
        terminal = await terminal_manager.create_or_get_terminal(terminal_id)
        await terminal.write_to_process(request.text, request.enter if request.enter is not None else True)
        
        return TerminalApiResponse(
            status="success",
            output=terminal.get_history(True, False),
            result="Text written to terminal",
            terminal_id=terminal_id
        )
    except Exception as e:
        logger.error(f"Error writing to terminal {terminal_id}: {e}")
        return TerminalApiResponse(
            status="error", 
            output=[], 
            result=f"Error: {str(e)}", 
            terminal_id=terminal_id
        )

class InitSandboxRequest(BaseModel):
    secrets: Dict[str, str]

@app.post("/init_sandbox")
async def init_sandbox(request: InitSandboxRequest):
    """Initialize the sandbox environment with secrets."""
    try:
        secrets_dir = Path.home() / '.secrets'
        secrets_dir.mkdir(exist_ok=True)
        
        for key, value in request.secrets.items():
            secret_file = secrets_dir / key
            with open(secret_file, 'w') as f:
                f.write(value)
            
            # Set permissions to be readable only by the owner
            os.chmod(secret_file, 0o600)
        
        return {"status": "success", "message": f"Initialized {len(request.secrets)} secrets"}
    except Exception as e:
        logger.error(f"Error initializing sandbox: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/healthz")
async def healthz():
    """Health check endpoint."""
    return {"status": "ok"}

class ProjectType(str, Enum):
    FRONTEND = 'frontend'
    BACKEND = 'backend'
    NEXTJS = 'nextjs'

class ZipAndUploadRequest(BaseModel):
    directory: str
    upload_url: str
    project_type: ProjectType

class ZipAndUploadResponse(BaseModel):
    status: str
    message: str
    error: str | None = None

@app.post("/zip_and_upload")
async def zip_and_upload(request: ZipAndUploadRequest):
    """Zip a project directory and upload it to a presigned URL."""
    try:
        # Create a temporary directory for the zip file
        with tempfile.TemporaryDirectory() as temp_dir:
            output_zip = os.path.join(temp_dir, "project.zip")
            
            # Create the zip archive
            success, msg = create_zip_archive(request.directory, output_zip)
            if not success:
                return ZipAndUploadResponse(status="error", message=msg)
            
            # Upload the zip to the presigned URL
            with open(output_zip, 'rb') as f:
                content = f.read()
            
            content_type = "application/zip"
            await upload_to_presigned_url(content, request.upload_url, content_type, "project.zip")
            
            return ZipAndUploadResponse(
                status="success",
                message=f"Successfully zipped and uploaded {request.directory}"
            )
    except Exception as e:
        logger.error(f"Error in zip_and_upload: {e}")
        return ZipAndUploadResponse(status="error", message="Failed to zip and upload", error=str(e))

def create_zip_archive(source_dir, output_zip):
    '''
    Create a zip archive of a directory, excluding node_modules and .next

    Args:
        source_dir: Path to the directory to zip
        output_zip: Path for the output zip file

    Returns:
        tuple[bool, str]: (success, error_message)
    '''
    source_path = Path(source_dir).resolve()
    if not source_path.is_dir():
        return (False, f"Directory '{source_dir}' does not exist")
    
    if not output_zip.endswith('.zip'):
        output_zip += '.zip'
        
    exclude_patterns = [
        'node_modules',
        '.next',
        '.open-next',
        '.turbo',
        '.wrangler',
        '.git'
    ]
    
    try:
        shutil.make_archive(output_zip[:-4], 'zip', source_path, 
                           ignore=shutil.ignore_patterns(*exclude_patterns))
        return (True, f"Successfully created zip archive at '{output_zip}'")
    except Exception as e:
        error_message = f"Error creating zip archive: {e}"
        logger.error(error_message)
        return (False, error_message)