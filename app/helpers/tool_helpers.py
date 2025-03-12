'''Utility to run shell commands asynchronously with a timeout.'''
import asyncio
from typing import Optional, Tuple
from app.logger import logger

TRUNCATED_MESSAGE: str = (
    '<response clipped><NOTE>To save on context only part of this file has been shown to you. '
    'You should retry this tool after you have searched inside the file with `grep -n` in order to '
    'find the line numbers of what you are looking for.</NOTE>'
)
MAX_RESPONSE_LEN: int = 16000

def maybe_truncate(content: str, truncate_after: Optional[int]) -> str:
    '''Truncate content and append a notice if content exceeds the specified length.'''
    if truncate_after is None or len(content) <= truncate_after:
        return content
    return content[:truncate_after] + TRUNCATED_MESSAGE

async def run_shell(cmd: str, timeout: float = 30, truncate_after: Optional[int] = None, input: Optional[str] = None) -> Tuple[int, str, str]:
    '''
    Run a shell command asynchronously with a timeout.
    
    Args:
        cmd: The shell command to run.
        timeout: Maximum execution time in seconds (default: 30).
        truncate_after: Maximum length of output before truncation (default: None).
        input: Optional input to send to the command's stdin.
        
    Returns:
        Tuple[int, str, str]: (return_code, stdout, stderr)
        
    Raises:
        asyncio.TimeoutError: If the command exceeds the specified timeout.
    '''
    logger.info(f"Running command: {cmd}")
    
    try:
        # Create the subprocess, sending input only if provided
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if input is not None else None
        )
        
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=input.encode() if input else None),
                timeout=timeout
            )
        except asyncio.TimeoutError as e:
            logger.warning(f"Command timed out after {timeout} seconds: {cmd}")
            try:
                process.kill()
            except Exception as kill_exc:
                logger.error(f"Error killing process: {kill_exc}")
            raise asyncio.TimeoutError(f"Command '{cmd}' timed out after {timeout} seconds") from e
        
        return_code = process.returncode or 0
        stdout = stdout_bytes.decode('utf-8', errors='replace')
        stderr = stderr_bytes.decode('utf-8', errors='replace')
        
        # Truncate the output if a truncation limit is provided
        if truncate_after is not None:
            stdout = maybe_truncate(stdout, truncate_after)
            stderr = maybe_truncate(stderr, truncate_after)
        
        logger.info(f"Command completed with return code {return_code}")
        return return_code, stdout, stderr
        
    except Exception as e:
        logger.error(f"Error running shell command: {e}")
        return 1, "", f"Error running command: {e}"
