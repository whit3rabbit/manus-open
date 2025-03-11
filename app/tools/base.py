import os
from dataclasses import dataclass, fields, replace
from typing import Any

# Default working directory inside the container
wd = '/home/ubuntu'

# Check if running inside a container by verifying if the default working directory exists
IS_INSIDE_CONTAINER = os.path.exists(wd)

# Determine the default working directory:
# - If inside a container, use the container's working directory 'wd'.
# - Otherwise, calculate the project root directory by going up three levels from the current file's location.
DEFAULT_WORKING_DIR = wd if IS_INSIDE_CONTAINER else os.path.normpath(os.path.join(os.path.dirname(__file__), '../../../'))

# Determine the default user:
# - If inside a container, use 'ubuntu'.
# - Otherwise, get the username from the environment variable 'USER'.
DEFAULT_USER = 'ubuntu' if IS_INSIDE_CONTAINER else os.environ.get('USER')

@dataclass
class ToolResult:
    """Base class for tool results."""
    pass

class CLIResult(ToolResult):
    '''A ToolResult that can be rendered as a CLI output.'''
    pass

class ToolFailure(ToolResult):
    '''A ToolResult that represents a failure.'''
    pass

class ToolError(Exception):
    '''Raised when a tool encounters an error.'''
    def __init__(self, message):
        """Initialize ToolError with an error message."""
        self.message = message
        super().__init__(message)