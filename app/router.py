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
            # Record the start time
            start_time = time.time()
            
            # Get the route path for logging
            route_path = request.url.path
            method = request.method
            
            try:
                # Process the request with the original handler
                response = await original_route_handler(request)
                
                # Calculate and log the processing time
                process_time = time.time() - start_time
                logger.info(f"{method} {route_path} completed in {process_time:.4f}s")
                
                # Add the processing time to response headers
                response.headers["X-Process-Time"] = f"{process_time:.4f}"
                
                return response
            except Exception as e:
                # Log errors with timing information
                process_time = time.time() - start_time
                logger.error(f"{method} {route_path} failed after {process_time:.4f}s: {str(e)}")
                raise
            
        return custom_route_handler

__all__ = ['TimedRoute']