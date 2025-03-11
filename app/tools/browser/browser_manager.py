import asyncio
import os
import random
import urllib
import urllib.parse as urllib
from datetime import datetime
from typing import Literal

from playwright._impl._errors import TargetClosedError
from app.helpers.tool_helpers import run_shell
from app.helpers.utils import upload_to_presigned_url
from app.logger import logger
from app.tools.base import DEFAULT_WORKING_DIR
from app.types.browser_types import BrowserActionResult
from app.types.messages import BrowserActionRequest
from browser_use.browser.browser import Browser, BrowserConfig, BrowserContextConfig
from browser_use.browser.context import BrowserContext, ScreenshotError
from browser_use.browser.context import PageDeadError
from browser_use.controller.service import Controller

class BrowserDeadError(Exception):
    """Exception raised when the browser is not available or has crashed."""
    pass

class BrowserManager:
    '''
    browser agent 基于 browser-use 和 playwright, 用于执行所有浏览器相关操作
    (browser agent based on browser-use and playwright, used to execute all browser-related operations)
    '''
    browser: Browser
    browser_context: BrowserContext
    controller: Controller
    include_attributes: list[str]
    status: Literal['started', 'initializing', 'ready'] = 'started'
    
    def __init__(self, *, chrome_instance_path=None, headless=True):
        """
        Initialize the browser manager.
        
        Args:
            chrome_instance_path: Path to Chrome browser instance
            headless: Whether to run the browser in headless mode
        """
        # Set Chrome instance path from environment if not provided
        if not chrome_instance_path:
            chrome_instance_path = os.getenv('CHROME_INSTANCE_PATH', None)
            
        self.chrome_instance_path = chrome_instance_path
        self.headless = headless
        self.browser = None
        self.browser_context = None
        self.controller = None
        self.include_attributes = ["id", "tagName", "href", "src", "alt", "ariaLabel", "placeholder", "name"]
        self.status = "started"  # started, initializing, ready
        
        logger.info(f"Browser manager initialized with Chrome path: {chrome_instance_path}")
    
    async def initialize(self):
        """
        Initialize the browser and create a new page.
        """
        if self.status == "initializing" or self.status == "ready":
            return
            
        self.status = "initializing"
        logger.info("Initializing browser...")
        
        try:
            # Set up browser configuration
            browser_config = BrowserConfig(
                headless=self.headless,
                chrome_executable_path=self.chrome_instance_path,
                args=[
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials"
                ]
            )
            
            # Create browser context configuration
            browser_context_config = BrowserContextConfig(
                viewport_width=1280,
                viewport_height=800,
                default_timeout_ms=30000,
                default_navigation_timeout_ms=45000,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
            )
            
            # Initialize browser and context
            self.browser = await Browser.create(browser_config)
            self.browser_context = await BrowserContext.create(self.browser, browser_context_config)
            
            # Initialize controller
            self.controller = Controller.create(self.browser_context)
            
            # Navigate to blank page to ensure context is ready
            await self.browser_context.goto("about:blank")
            
            self.status = "ready"
            logger.info("Browser initialized successfully")
            
        except Exception as e:
            self.status = "started"
            logger.error(f"Failed to initialize browser: {e}")
            raise BrowserDeadError(f"Failed to initialize browser: {e}")
    
    async def recreate_page(self):
        """
        Close the current page and create a new one.
        """
        if self.status != "ready":
            await self.initialize()
            
        logger.info("Recreating browser page")
        
        try:
            # Close current page and create a new one
            await self.browser_context.recreate_page()
            
            # Navigate to blank page to ensure page is ready
            await self.browser_context.goto("about:blank")
            
            logger.info("Browser page recreated successfully")
            
        except Exception as e:
            logger.error(f"Failed to recreate page: {e}")
            raise PageDeadError(f"Failed to recreate page: {e}")
    
    async def execute_action(self, cmd: BrowserActionRequest) -> BrowserActionResult:
        """
        Execute a browser action.
        
        Args:
            cmd: The browser action request
            
        Returns:
            BrowserActionResult: The result of the action
        """
        if self.status != "ready":
            await self.initialize()
            
        action = cmd.action
        action_type = None
        
        # Determine action type
        for field in action.__fields__:
            if getattr(action, field) is not None:
                action_type = field
                break
                
        if not action_type:
            raise ValueError("No action specified in the request")
            
        logger.info(f"Executing browser action: {action_type}")
        
        try:
            # Execute the action using the controller
            result = await self.controller.execute_action(action)
            
            # Handle screenshot uploads if URLs are provided
            if action_type == "browser_screenshot" and (cmd.screenshot_presigned_url or cmd.clean_screenshot_presigned_url):
                try:
                    # Take screenshots
                    screenshot_result = await self.browser_context.take_screenshot(full_page=True)
                    clean_screenshot = screenshot_result.screenshot
                    marked_screenshot = screenshot_result.screenshot  # In real implementation, this would be a marked version
                    
                    # Upload screenshots
                    await self.upload_screenshots(cmd, clean_screenshot, marked_screenshot)
                except ScreenshotError as e:
                    logger.error(f"Error taking screenshot: {e}")
                    
            # Convert result to BrowserActionResult
            return BrowserActionResult(
                url=result.url,
                title=result.title,
                result=result.result,
                pixels_below=result.pixels_below if hasattr(result, 'pixels_below') else 0
            )
            
        except TargetClosedError:
            logger.error("Browser page closed unexpectedly")
            raise PageDeadError("Browser page closed unexpectedly")
        except PageDeadError as e:
            logger.error(f"Page dead error: {e}")
            
            # Try to recreate the page
            await self.recreate_page()
            raise
        except Exception as e:
            logger.error(f"Error executing browser action: {e}")
            raise
    
    async def restart_browser(self):
        """
        Restart the browser by closing and reinitializing it.
        """
        logger.info("Restarting browser")
        
        # Close browser if it exists
        if self.browser:
            try:
                await self.browser.close()
                self.browser = None
                self.browser_context = None
                self.controller = None
                self.status = "started"
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
        
        # Reinitialize
        await self.initialize()
        logger.info("Browser restarted")
    
    async def health_check(self) -> bool:
        """
        Check if the browser is healthy.
        
        Returns:
            bool: True if healthy, False otherwise
        """
        if self.status != "ready":
            return False
            
        try:
            # Check if browser components are initialized
            if not self.browser or not self.browser_context or not self.controller:
                return False
                
            # Try to execute a simple action to check if browser is responsive
            await self.browser_context.evaluate_javascript("1 + 1")
            return True
        except Exception as e:
            logger.error(f"Browser health check failed: {e}")
            return False
    
    def get_screenshot_save_path(self, page_url: str) -> str:
        """
        Generate a path for saving a screenshot.
        
        Args:
            page_url: The URL of the page being screenshotted
            
        Returns:
            str: The file path for the screenshot
        """
        screenshots_dir = f"{DEFAULT_WORKING_DIR}/screenshots"
        
        # Ensure the screenshots directory exists
        os.makedirs(screenshots_dir, exist_ok=True)
        
        # Parse URL to get hostname
        parsed_url = urllib.parse.urlparse(page_url)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        random_id = random.randint(1000, 9999)
        
        if parsed_url.scheme in ('http', 'https') and parsed_url.hostname:
            hostname = parsed_url.hostname.replace('.com', '').replace('www.', '').replace('.', '_')
        else:
            hostname = page_url.split('/').pop().replace('.', '_')
            
        return f"{screenshots_dir}/{hostname}_{timestamp}_{random_id}.webp"
    
    async def upload_screenshots(self, cmd: BrowserActionRequest, clean_screenshot: bytes, marked_screenshot: bytes):
        """
        Upload screenshots to the provided presigned URLs.
        
        Args:
            cmd: The browser action request containing presigned URLs
            clean_screenshot: The clean screenshot data
            marked_screenshot: The marked screenshot data
        """
        # Upload the clean screenshot if a URL is provided
        if cmd.clean_screenshot_presigned_url:
            try:
                await upload_to_presigned_url(
                    clean_screenshot,
                    cmd.clean_screenshot_presigned_url,
                    "image/webp",
                    "clean_screenshot.webp"
                )
                logger.info("Clean screenshot uploaded successfully")
            except Exception as e:
                logger.error(f"Error uploading clean screenshot: {e}")
        
        # Upload the marked screenshot if a URL is provided
        if cmd.screenshot_presigned_url:
            try:
                await upload_to_presigned_url(
                    marked_screenshot,
                    cmd.screenshot_presigned_url,
                    "image/webp",
                    "marked_screenshot.webp"
                )
                logger.info("Marked screenshot uploaded successfully")
            except Exception as e:
                logger.error(f"Error uploading marked screenshot: {e}")