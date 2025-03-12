import os
from dataclasses import dataclass, fields, replace
from typing import Any

# Default working directory inside the container
wd = '/home/ubuntu'
# Check if running inside a container by verifying if the default working directory exists
IS_INSIDE_CONTAINER = os.path.exists(wd)
# Determine the default working directory based on environment
DEFAULT_WORKING_DIR = wd if IS_INSIDE_CONTAINER else os.path.normpath(os.path.join(__file__, '../../../'))
# Determine the default user based on environment
DEFAULT_USER = 'ubuntu' if IS_INSIDE_CONTAINER else os.environ.get('USER')

@dataclass(kw_only=True, frozen=True)
class ToolResult:
    """Represents the result of a tool execution."""
    output: str | None = None
    error: str | None = None
    base64_image: str | None = None
    system: str | None = None
    
    def __bool__(self):
        return any(getattr(self, field.name) for field in fields(self))
    
    def __add__(self, other: 'ToolResult'):
        def combine_fields(field: str | None, other_field: str | None, concatenate=True):
            if field and other_field:
                if concatenate:
                    return field + other_field
                raise ValueError('Cannot combine tool results')
            return field or other_field
        
        return ToolResult(
            output=combine_fields(self.output, other.output),
            error=combine_fields(self.error, other.error),
            base64_image=combine_fields(self.base64_image, other.base64_image, False),
            system=combine_fields(self.system, other.system)
        )
    
    def replace(self, **kwargs):
        """Returns a new ToolResult with the given fields replaced."""
        return replace(self, **kwargs)

class CLIResult(ToolResult):
    """A ToolResult that can be rendered as a CLI output."""
    pass

class ToolFailure(ToolResult):
    """A ToolResult that represents a failure."""
    pass

class ToolError(Exception):
    """Raised when a tool encounters an error."""
    def __init__(self, message: str):
        self.message = message
        # Note: The bytecode doesn't show a call to super().__init__,
        # but it's good practice to include it