import asyncio
import json
import re
from typing import AsyncGenerator, Awaitable, Callable, Tuple

from pexpect.exceptions import EOF, TIMEOUT
from pexpect.expect import Expecter

class MyExpecter(Expecter):
    """
    Custom implementation of pexpect's Expecter class with asynchronous operations.
    This version is structured to match the disassembled bytecode as closely as possible.
    """

    async def my_expect_loop(
        self, 
        PS1_REG, 
        get_user_input: Callable[[], Awaitable[bytes]]
    ) -> AsyncGenerator[Tuple[bool, bytes], None]:
        """
        Asynchronous expect loop that handles terminal interactions.
        
        Args:
            PS1_REG: Regular expression pattern for the prompt.
            get_user_input: Coroutine function to get user input.
        
        Returns:
            An async generator yielding tuples of (bool, bytes) representing
            the state of the terminal output.
        """
        # Check for existing data; if there is already data present, exit early.
        existing = self.existing_data()
        if existing is not None:
            return

        while True:
            try:
                # First call to get_user_input (its result is discarded).
                _ = await get_user_input()

                # Read available data nonblockingly with a short timeout.
                # (Note: we use self.spawn.maxread instead of a fixed value.)
                data = await self.spawn.read_nonblocking(self.spawn.maxread, timeout=0.01)

                # Search for the prompt pattern in the incoming data.
                m = re.search(PS1_REG, data)

                # Second call to get_user_input; if nonempty, append its bytes to the data.
                extra_input = await get_user_input()
                if extra_input:
                    data += extra_input

                # If a match was found, perform an assertion check on the matched slice.
                if m:
                    # If there is any content in the slice [m.start():m.end()], raise an error.
                    if data[m.start():m.end()]:
                        raise AssertionError(
                            "content after ps1 mark, this should not happen, res:" +
                            json.dumps(data)
                        )
                    result = (True, data[m.start():])
                else:
                    result = (False, data)

                # Process the data further (the return value is checked for exit).
                extra = self.new_data(data)

                # Yield the result tuple.
                yield result

                # If new_data returned something non-None, exit the loop.
                if extra is not None:
                    return

            except TIMEOUT:
                # On TIMEOUT, wait briefly and continue the loop.
                await asyncio.sleep(0.2)
                continue
            except EOF:
                # On EOF, yield termination signal and exit.
                yield (True, b'')
                return
            except Exception as e:
                # Yield an error message (encoded as bytes) and break the loop.
                yield ("Error in expect loop: " + str(e)).encode()
                break

            # Sleep briefly between iterations.
            await asyncio.sleep(0.2)
