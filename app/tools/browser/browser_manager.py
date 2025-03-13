import asyncio
import os
import random
import urllib
import urllib.parse as urlparse
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
from browser_use.browser.context import BrowserContext, ScreenshotError, PageDeadError
from browser_use.controller.service import Controller


class BrowserDeadError(Exception):
    """Exception raised when the browser is not available or has crashed."""
    pass


class BrowserManager:
    """
    browser agent 基于 browser-use 和 playwright, 用于执行所有浏览器相关操作
    (browser agent based on browser-use and playwright, used to execute all browser-related operations)
    """
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
        if self.status in ("initializing", "ready"):
            return

        self.status = "initializing"
        logger.info("Initializing browser...")

        try:
            browser_config = BrowserConfig(
                headless=self.headless,
                chrome_executable_path=self.chrome_instance_path,
                args=[
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials"
                ]
            )
            browser_context_config = BrowserContextConfig(
                viewport_width=1280,
                viewport_height=800,
                default_timeout_ms=30000,
                default_navigation_timeout_ms=45000,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
            )
            self.browser = await Browser.create(browser_config)
            self.browser_context = await BrowserContext.create(self.browser, browser_context_config)
            self.controller = Controller.create(self.browser_context)

            # Navigate to a blank page to prepare the context
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
            await self.browser_context.recreate_page()
            await self.browser_context.goto("about:blank")
            logger.info("Browser page recreated successfully")
        except Exception as e:
            logger.error(f"Failed to recreate page: {e}")
            raise PageDeadError(f"Failed to recreate page: {e}")

    async def execute_action(self, cmd: BrowserActionRequest) -> BrowserActionResult:
        """
        Execute a browser action.
        This version waits for the browser to be ready, checks page availability,
        calls the controller’s act method, updates state, takes screenshots, uploads them,
        and then returns a BrowserActionResult with extended fields.
        """
        # Ensure browser is ready
        if self.status == "started":
            logger.info("Browser not initialized, starting initialization")
            await self.initialize()
        elif self.status != "ready":
            logger.info("Browser not ready, waiting for initialization")
            while self.status != "ready":
                await asyncio.sleep(0.2)

        # Check page availability
        logger.info("Check page availability")
        await self.browser_context.ensure_page_alive()

        # Determine action type
        action = cmd.action
        action_type = None
        for field in action.__fields__:
            if getattr(action, field) is not None:
                action_type = field
                break
        if not action_type:
            raise ValueError("No action specified in the request")

        logger.info("Page available, executing the action")
        try:
            # Execute the action using the controller's act method
            result = await self.controller.act(action, self.browser_context)
            logger.info(f"Action execution finish, result {repr(result)}")

            # Update state
            logger.info("Updating state...")
            session = await self.browser_context.get_session()
            await self.browser_context.update_state()
            cached_state = session.cached_state

            elements = ""
            if hasattr(cached_state, "clickable_elements"):
                elements = "\n".join(f"{el.index}[:]{el.description}" 
                                     for el in cached_state.clickable_elements.values())

            screenshot_save_path = self.get_screenshot_save_path(cached_state.url)
            logger.info("Taking screenshots")
            try:
                clean_screenshot = await self.browser_context.take_screenshot(
                    full_page=False, save_path=screenshot_save_path
                )
            except ScreenshotError as e:
                logger.error(f"Error taking clean screenshot: {e}")
                clean_screenshot = b""
            try:
                marked_screenshot = await self.browser_context.take_screenshot(full_page=True)
            except ScreenshotError as e:
                logger.error(f"Error taking marked screenshot: {e}")
                marked_screenshot = b""

            logger.info(f"Screenshot saved to {screenshot_save_path}, uploading screenshots")
            await self.upload_screenshots(cmd, clean_screenshot, marked_screenshot)

            # Construct and return the BrowserActionResult with extended fields.
            return BrowserActionResult(
                url=cached_state.url,
                title=cached_state.title,
                result=(result.extracted_content if hasattr(result, "extracted_content") and result.extracted_content
                        else "success"),
                error=(result.error if hasattr(result, "error") else ""),
                markdown=(result.article_markdown if hasattr(result, "should_show_markdown") and result.should_show_markdown and hasattr(result, "article_markdown")
                          else ""),
                elements=elements,
                screenshot_uploaded=bool(cmd.screenshot_presigned_url),
                clean_screenshot_uploaded=bool(cmd.clean_screenshot_presigned_url),
                clean_screenshot_path=screenshot_save_path,
                pixels_above=getattr(cached_state, "pixels_above", 0),
                pixels_below=getattr(cached_state, "pixels_below", 0)
            )
        except TargetClosedError:
            logger.error("Browser page closed unexpectedly")
            raise PageDeadError("Browser page closed unexpectedly")
        except PageDeadError as e:
            logger.error(f"Page dead error: {e}")
            await self.recreate_page()
            raise
        except Exception as e:
            logger.error(f"Error executing browser action: {e}")
            raise

    async def restart_browser(self):
        """
        Restart the browser by closing and reinitializing it.
        This version also attempts to restart Chrome via a shell command.
        """
        logger.info("Restarting browser")
        if self.browser:
            try:
                await self.browser.close()
                self.browser = None
                if self.browser_context:
                    await self.browser_context.close()
                self.browser_context = None
                self.controller = None
                self.status = "started"
            except Exception as e:
                logger.error(f"Error closing browser: {e}")

        # Attempt to restart Chrome via supervisorctl
        logger.info("Try restart chrome")
        try:
            output = await run_shell("sudo supervisorctl restart chrome")
            logger.info(output)
            logger.info("Chrome restarted")
        except Exception as e:
            logger.error(f"Error restarting chrome: {e}")

        # Reinitialize the browser
        await self.initialize()
        logger.info("Browser restarted")

    async def health_check(self) -> bool:
        """
        Check if the browser is healthy.
        """
        if self.status != "ready":
            return False

        try:
            if not self.browser or not self.browser_context or not self.controller:
                return False

            await self.browser_context.evaluate_javascript("1 + 1")
            return True
        except Exception as e:
            logger.error(f"Browser health check failed: {e}")
            return False

    def get_screenshot_save_path(self, page_url: str) -> str:
        """
        Generate a path for saving a screenshot.
        """
        screenshots_dir = f"{DEFAULT_WORKING_DIR}/screenshots"
        os.makedirs(screenshots_dir, exist_ok=True)

        parsed_url = urlparse.urlparse(page_url)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        random_id = random.randint(1000, 9999)

        if parsed_url.scheme in ('http', 'https') and parsed_url.hostname:
            hostname = parsed_url.hostname.replace('.com', '').replace('www.', '').replace('.', '_')
        else:
            hostname = page_url.split('/').pop().replace('.', '_')

        return f"{screenshots_dir}/{hostname}_{timestamp}_{random_id}.webp"

    async def upload_screenshots(self, cmd: BrowserActionRequest, clean_screenshot: bytes, marked_screenshot: bytes):
        """
        Save screenshots to local storage instead of uploading to S3.
        """
        from app.helpers.local_storage import upload_to_local_storage
        
        screenshots_dir = f"{DEFAULT_WORKING_DIR}/screenshots"
        os.makedirs(screenshots_dir, exist_ok=True)
        
        marked_path = None
        clean_path = None
        
        if cmd.screenshot_presigned_url:
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                marked_filename = f"marked_{timestamp}.webp"
                
                result = await upload_to_local_storage(
                    marked_screenshot,
                    marked_filename,
                    "image/webp"
                )
                
                if result['success']:
                    marked_path = result['path']
                    logger.info(f"Screenshot saved successfully to {marked_path}")
                else:
                    logger.error("Failed to save marked screenshot")
            except Exception as e:
                logger.error(f"Error saving marked screenshot: {e}")
        else:
            logger.info("No screenshot requested, skipped saving")

        if cmd.clean_screenshot_presigned_url:
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                clean_filename = f"clean_{timestamp}.webp"
                
                result = await upload_to_local_storage(
                    clean_screenshot,
                    clean_filename,
                    "image/webp"
                )
                
                if result['success']:
                    clean_path = result['path']
                    logger.info(f"Clean screenshot saved successfully to {clean_path}")
                else:
                    logger.error("Failed to save clean screenshot")
            except Exception as e:
                logger.error(f"Error saving clean screenshot: {e}")
        else:
            logger.info("No clean screenshot requested, skipped saving")
        
        return marked_path, clean_path