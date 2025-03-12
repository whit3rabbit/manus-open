import time
from typing import Callable
from fastapi import Request, Response
from fastapi.routing import APIRoute
from app.logger import logger

class TimedRoute(APIRoute):
    """
    A custom route class that logs request processing time.
    Extends FastAPI's APIRoute to add timing information for each request.
    """
    
    def get_route_handler(self) -> Callable:
        """
        Override the get_route_handler method to add timing functionality.
        
        Returns:
            Callable: The modified route handler with timing capabilities
        """
        original_route_handler = super().get_route_handler()
        
        async def custom_route_handler(request: Request) -> Response:
            """
            Custom route handler that measures and logs request processing time.
            
            Args:
                request: The incoming HTTP request
                
            Returns:
                Response: The HTTP response
            """
            # Get the route path for logging
            path = request.url.path
            
            # Log the request
            logger.info(f"[>>] {request.method} {path}")
            
            # Record the start time
            start_time = time.time()
            
            # Process the request with the original handler
            response = await original_route_handler(request)
            
            # Calculate the processing time (in milliseconds)
            process_time = time.time() - start_time
            
            # Log the completion with time in milliseconds
            logger.info(f"[<<] Finished handling {request.method} {path} in {process_time * 1000}ms")
            
            return response
            
        return custom_route_handler

# Export the TimedRoute class
__all__ = ['TimedRoute']