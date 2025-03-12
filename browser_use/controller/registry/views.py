from typing import Callable, Dict, Type
from pydantic import BaseModel, ConfigDict

class RegisteredAction(BaseModel):
    """Model for a registered action"""
    name: str
    description: str
    function: Callable
    param_model: Type[BaseModel]
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def prompt_description(self) -> str:
        """Get a description of the action for the prompt"""
        skip_keys = ['title']
        description_text = f'{self.description}: \n'
        description_text += '{' + str(self.name) + ': '
        description_text += str(
            {
                param_name: {field_key: field_value for field_key, field_value in param_details.items() 
                            if field_key not in skip_keys}
                for param_name, param_details in self.param_model.schema()['properties'].items()
            }
        )
        description_text += '}'
        return description_text


class ActionModel(BaseModel):
    """Base model for dynamically created action models"""
    # This class will have all the registered actions dynamically added
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def get_index(self) -> int | None:
        """Get the index of the action"""
        # Looks for an 'index' value in any of the action parameters
        # Example data shape: {'clicked_element': {'index': 5}}
        parameters = self.model_dump(exclude_unset=True).values()
        if not parameters:
            return None
        
        for param in parameters:
            if param is not None and 'index' in param:
                return param['index']
        return None
    
    def set_index(self, index: int):
        """Overwrite the index of the action"""
        # Get the action name and params
        action_data = self.model_dump(exclude_unset=True)
        action_name = next(iter(action_data.keys()))
        action_params = getattr(self, action_name)
        
        # Update the index directly on the model
        if hasattr(action_params, 'index'):
            action_params.index = index


class ActionRegistry(BaseModel):
    """Model representing the action registry"""
    actions: Dict[str, RegisteredAction] = {}
    
    def get_prompt_description(self) -> str:
        """Get a description of all actions for the prompt"""
        return '\n'.join([action.prompt_description() for action in self.actions.values()])