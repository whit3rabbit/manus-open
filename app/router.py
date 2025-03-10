import time
from typing import Callable
from fastapi import Request, Response
from fastapi.routing import APIRoute
from logger import logger

class TimedRoute(APIRoute):
    
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()
        
        async def custom_route_handler(request):
            pass
            
        return custom_route_handler

__all__ = ['TimedRoute']