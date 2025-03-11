'''Utility to run shell commands asynchronously with a timeout.'''
import asyncio
from app.logger import logger

TRUNCATED_MESSAGE: str = '<response clipped><NOTE>To save on context only part of this file has been shown to you. You should retry this tool after you have searched inside the file with `grep -n` in order to find the line numbers of what you are looking for.</NOTE>'
MAX_RESPONSE_LEN: int = 16000

def maybe_truncate(content, truncate_after):
    '''Truncate content and append a notice if content exceeds the specified length.'''
    return content if truncate_after is None or len(content) <= truncate_after else content[:truncate_after] + TRUNCATED_MESSAGE

async def run_shell(cmd, timeout=30, truncate_after=None, input=None):
    '''
    Run a shell command asynchronously with a timeout.
    
    Args:
        cmd: The shell command to run
        timeout: Maximum execution time in seconds (default: 30)
        truncate_after: Maximum length of output before truncation (default: None)
        input: Optional input to send to the command's stdin
        
    Returns:
        Tuple[int, str, str]: (return_code, stdout, stderr)
    '''
    logger.debug(f"Running shell command: {cmd}")
    
    try:
        # Create process
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if input else None
        )
        
        # Set up timeout
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=input.encode() if input else None),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Kill the process if it takes too long
            logger.warning(f"Command timed out after {timeout} seconds: {cmd}")
            try:
                process.terminate()
                await asyncio.sleep(0.1)
                if process.returncode is None:
                    process.kill()
            except Exception as e:
                logger.error(f"Error killing process: {e}")
            return (124, "", f"Command timed out after {timeout} seconds")
        
        # Get the return code
        return_code = process.returncode or 0
        
        # Decode output
        stdout = stdout_bytes.decode('utf-8', errors='replace')
        stderr = stderr_bytes.decode('utf-8', errors='replace')
        
        # Truncate if necessary
        if truncate_after is not None:
            stdout = maybe_truncate(stdout, truncate_after)
            stderr = maybe_truncate(stderr, truncate_after)
        
        logger.debug(f"Command completed with return code {return_code}")
        return (return_code, stdout, stderr)
        
    except Exception as e:
        logger.error(f"Error running shell command: {e}")
        return (1, "", f"Error running command: {str(e)}")