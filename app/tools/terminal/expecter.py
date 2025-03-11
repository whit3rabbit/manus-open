import asyncio
from typing import AsyncGenerator, Callable
from pexpect.exceptions import EOF, TIMEOUT
from pexpect.expect import Expecter

class MyExpecter(Expecter):
    """
    Custom implementation of pexpect's Expecter class.
    This class extends the functionality to support asynchronous operation
    and customized expect loops.
    """
    
    async def my_expect_loop(self, PS1_REG, get_user_input):
        """
        Custom expect loop that can handle terminal interactions asynchronously.
        
        Args:
            PS1_REG: Regular expression pattern for the prompt
            get_user_input: Coroutine function to get user input
            
        Returns:
            AsyncGenerator yielding terminal outputs
        """
        # Initialize buffer
        self.buffer = self.spawn.buffer
        
        # Start with initial read
        try:
            incoming = await self.spawn.read_nonblocking(size=1000, timeout=0)
            self.buffer += incoming
        except (TIMEOUT, EOF):
            pass
        
        # Main expect loop
        while True:
            try:
                # Try to match the pattern
                index = self.new_data(PS1_REG)
                
                if index >= 0:
                    # Found a match - yield the data and wait for user input
                    yield self.buffer
                    
                    # Get user input - this is a coroutine that waits for user input
                    user_input = await get_user_input()
                    
                    # Send the user input to the process
                    if user_input is not None:
                        self.spawn.send_line(user_input)
                    
                    # Clear the buffer after processing
                    self.buffer = b""
                else:
                    # No match yet - read more data
                    try:
                        # Use a short timeout to avoid blocking
                        incoming = await self.spawn.read_nonblocking(size=1000, timeout=0.1)
                        self.buffer += incoming
                        
                        # Yield partial data for interactive feedback
                        yield self.buffer
                    except TIMEOUT:
                        # No data available - yield current buffer and continue
                        yield self.buffer
                    except EOF:
                        # End of file - process terminated
                        yield self.buffer
                        break
            
            except Exception as e:
                # Handle any unexpected errors
                yield f"Error in expect loop: {str(e)}".encode()
                break