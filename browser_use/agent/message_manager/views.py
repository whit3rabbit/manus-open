from __future__ import annotations
from typing import TYPE_CHECKING, Any, Optional
from langchain_core.load import dumpd, load
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

if TYPE_CHECKING:
    from browser_use.agent.views import AgentOutput


class MessageMetadata(BaseModel):
    """Metadata for a message including token counts"""
    tokens: int = 0
    input_tokens: int = 0  # For backward compatibility

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ManagedMessage(BaseModel):
    """A message with its metadata"""
    message: BaseMessage
    metadata: MessageMetadata = Field(default_factory=MessageMetadata)
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    @model_serializer(mode='wrap')
    def to_json(self, original_dump):
        """
        Return the JSON representation of the model.
        Uses langchain's `dumpd` to serialize the message field.
        """
        data = original_dump(self)
        data['message'] = dumpd(self.message)
        return data
    
    @model_validator(mode='before')
    @classmethod
    def validate(
        cls,
        value: Any,
        *,
        strict: bool | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
    ) -> Any:
        """
        Custom validator that uses langchain's `load` function
        to parse the message if it is provided as a JSON string.
        """
        if isinstance(value, dict) and 'message' in value:
            value['message'] = load(value['message'])
        return value


class MessageHistory(BaseModel):
    """Container for message history with metadata"""
    messages: list[ManagedMessage] = Field(default_factory=list)
    current_tokens: int = 0
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def add_message(self, message: BaseMessage, metadata: MessageMetadata, position: Optional[int] = None) -> None:
        """
        Add a message with its metadata to history.

        Args:
            message: The message to add.
            metadata: Metadata including token counts.
            position: Optional index at which to insert the message (None to append).
        """
        if position is None:
            self.messages.append(ManagedMessage(message=message, metadata=metadata))
        else:
            self.messages.insert(position, ManagedMessage(message=message, metadata=metadata))
        
        token_count = metadata.tokens or metadata.input_tokens
        self.current_tokens += token_count
    
    def add_model_output(self, output: 'AgentOutput') -> None:
        """
        Add model output as an AI message with an associated tool call.
        """
        tool_calls = [
            {
                'name': 'AgentOutput',
                'args': output.model_dump(mode='json', exclude_unset=True),
                'id': '1',
                'type': 'tool_call',
            }
        ]
        
        msg = AIMessage(
            content='',
            tool_calls=tool_calls,
        )
        
        # Estimate tokens for tool call message
        self.add_message(msg, MessageMetadata(tokens=100))
        
        # Add an empty tool response (estimated token count)
        tool_message = ToolMessage(content='', tool_call_id='1')
        self.add_message(tool_message, MessageMetadata(tokens=10))
    
    def get_messages(self) -> list[BaseMessage]:
        """Return a list of all messages (without metadata)."""
        return [m.message for m in self.messages]
    
    def get_total_tokens(self) -> int:
        """Return the total token count for the message history."""
        return self.current_tokens
    
    def remove_message(self, index: int = -1) -> None:
        """
        Remove a message at the specified index (default: last message)
        and update the total token count.
        """
        if 0 <= abs(index) < len(self.messages):
            msg = self.messages.pop(index)
            token_count = msg.metadata.tokens or msg.metadata.input_tokens
            self.current_tokens -= token_count
    
    def remove_oldest_message(self) -> None:
        """
        Remove the oldest non-system message from history.
        """
        for i, msg in enumerate(self.messages):
            if not isinstance(msg.message, SystemMessage):
                token_count = msg.metadata.tokens or msg.metadata.input_tokens
                self.current_tokens -= token_count
                self.messages.pop(i)
                break
    
    def remove_last_state_message(self) -> None:
        """
        Remove the last state (Human) message from history if there are more than 2 messages.
        """
        if len(self.messages) > 2 and isinstance(self.messages[-1].message, HumanMessage):
            token_count = self.messages[-1].metadata.tokens or self.messages[-1].metadata.input_tokens
            self.current_tokens -= token_count
            self.messages.pop()
    
    @property
    def total_tokens(self) -> int:
        """Backward compatibility: total tokens in history."""
        return self.current_tokens


class MessageManagerState(BaseModel):
    """Holds the state for MessageManager"""
    history: MessageHistory = Field(default_factory=MessageHistory)
    tool_id: int = 1
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
