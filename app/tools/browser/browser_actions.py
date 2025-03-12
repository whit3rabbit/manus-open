import asyncio
import os
import time
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, TimeoutError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from app.helpers.tool_helpers import run_shell
from app.logger import logger
from app.tools.base import DEFAULT_WORKING_DIR
from app.types.browser_types import (
    BrowserClickAction, BrowserConsoleExecAction, BrowserConsoleViewAction, BrowserInputAction,
    BrowserMoveMouseAction, BrowserNavigateAction, BrowserPressKeyAction, BrowserRestartAction,
    BrowserScreenshotAction, BrowserScrollDownAction, BrowserScrollUpAction, BrowserSelectOptionAction,
    BrowserViewAction
)
from browser_use import ActionResult
from browser_use.browser.context import BrowserContext
from browser_helpers import HelperJs
from browser_manager import BrowserManager

__all__ = [
    'register_browser_actions'
]

TOTAL_TIMEOUT_MS = 45000
CONN_TIMEOUT_MS = 10000
default_headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9'
}

def register_browser_actions(manager):
    # Define browser action handlers with lambda initial declarations
    action_browser_navigate = lambda params, browser: None  # 浏览器导航操作 - Browser navigation operation
    action_browser_click = lambda params, browser: None  # 浏览器点击操作 - Browser click operation
    action_browser_input = lambda params, browser: None  # 浏览器输入操作 - Browser input operation
    action_browser_view = lambda params, browser: None  # 浏览器查看操作 - Browser view operation
    action_browser_screenshot = lambda params, browser: None  # 浏览器截图操作 - Browser screenshot operation
    action_browser_scroll_down = lambda params, browser: None  # 浏览器向下滚动 - Browser scroll down
    action_browser_scroll_up = lambda params, browser: None  # 浏览器向上滚动 - Browser scroll up
    action_browser_press_key = lambda params, browser: None  # 浏览器按键操作 - Browser key press
    action_browser_select_option = lambda params, browser: None  # 浏览器选择选项 - Browser select option
    action_browser_console_exec = lambda params, browser: None  # 浏览器控制台执行 - Browser console execution
    action_browser_console_view = lambda params, browser: None  # 浏览器控制台查看 - Browser console view
    action_browser_restart = lambda params, browser: None  # 浏览器重启操作 - Browser restart
    action_browser_move_mouse = lambda params, browser: None  # 浏览器移动鼠标 - Browser mouse movement
    
    async def handle_navigation_timeout(page):
        """Handle navigation timeout by getting partial page details."""
        try:
            # Try to get current page details
            current_url = page.url
            title = await page.title()
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=current_url,
                title=title,
                result="Navigation timed out, but page partially loaded",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Error handling navigation timeout: {e}")
            return ActionResult(
                error="Navigation timed out and failed to get partial page details",
                include_in_memory=True
            )
    
    async def handle_timeout(page):
        """Handle general timeout errors."""
        try:
            # Try to get current page details
            current_url = page.url
            title = await page.title()
            
            return ActionResult(
                url=current_url,
                title=title,
                result="Operation timed out",
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Error handling timeout: {e}")
            return ActionResult(
                error="Operation timed out and failed to get page details",
                include_in_memory=True
            )
    
    browser_context = None

    async def get_browser_context(key):
        """Get or create browser context with specified key."""
        nonlocal browser_context
        if browser_context is None:
            browser_context = BrowserContext(manager, key)
            await browser_context.initialize()
        return browser_context
    
    async def get_page_details(browser, page, original_url, now):
        """Get page details including URL, title, and navigation status."""
        try:
            current_url = page.url
            title = await page.title()
            
            return {
                "url": current_url,
                "title": title,
                "navigation": current_url != original_url,
                "timestamp": now,
                "elapsed": time.time() - now
            }
        except Exception as e:
            logger.error(f"Error getting page details: {e}")
            return {
                "url": original_url,
                "title": "Unknown",
                "navigation": False,
                "timestamp": now,
                "elapsed": time.time() - now,
                "error": str(e)
            }
    
    # Redefine handlers with actual implementations
    
    async def action_browser_navigate_impl(params, browser):
        """Navigate browser to a URL."""
        page = browser.page
        url = params.url
        
        try:
            # Start navigation with a timeout
            async with asyncio.timeout(TOTAL_TIMEOUT_MS / 1000):
                logger.info(f"Navigating to URL: {url}")
                
                # Perform the navigation
                response = await page.goto(url, timeout=TOTAL_TIMEOUT_MS, wait_until="networkidle")
                
                # Wait for page to stabilize
                await asyncio.sleep(1)
                
                current_url = page.url
                title = await page.title()
                
                # Get the page height for scrolling calculations
                height = await page.evaluate("document.documentElement.scrollHeight")
                
                return ActionResult(
                    url=current_url,
                    title=title,
                    result=f"Navigated to {url}",
                    pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                    include_in_memory=True
                )
        except TimeoutError:
            return await handle_navigation_timeout(page)
        except Exception as e:
            logger.error(f"Navigation error: {e}")
            return ActionResult(error=f"Failed to navigate to {url}: {str(e)}", include_in_memory=True)
    
    async def action_browser_click_impl(params, browser):
        """Handle click actions on browser elements."""
        page = browser.page
        
        try:
            # Get page details before the action
            current_url = page.url
            title = await page.title()
            
            # If index is provided, click on element by index
            if params.index is not None:
                # Evaluate JavaScript to find clickable elements
                elements = await page.evaluate(HelperJs.FIND_CLICKABLE)
                
                if params.index >= len(elements):
                    return ActionResult(
                        error=f"Index {params.index} is out of range. Only {len(elements)} clickable elements found.",
                        include_in_memory=True
                    )
                
                # Get the element to click
                element = elements[params.index]
                
                # Calculate the center of the element
                x = element["rect"]["x"] + element["rect"]["width"] / 2
                y = element["rect"]["y"] + element["rect"]["height"] / 2
                
                # Scroll to the element
                await page.evaluate(f"window.scrollTo(0, {max(0, y - 100)})")
                
                # Click on the element
                await page.mouse.click(x, y)
            
            # If coordinates are provided, click at the specific location
            elif params.coordinate_x is not None and params.coordinate_y is not None:
                x = params.coordinate_x
                y = params.coordinate_y
                
                # Scroll to the coordinates
                await page.evaluate(f"window.scrollTo(0, {max(0, y - 100)})")
                
                # Click at the specified coordinates
                await page.mouse.click(x, y)
            
            else:
                return ActionResult(
                    error="Either index or coordinates must be provided for click action.",
                    include_in_memory=True
                )
            
            # Wait for any resulting navigation or page updates
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except:
                # Ignore timeout, page might not have navigated
                pass
            
            # Get updated page details
            new_url = page.url
            new_title = await page.title()
            
            # Determine if navigation occurred
            nav_result = "navigated to a new page" if new_url != current_url else "clicked successfully"
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=new_url,
                title=new_title,
                result=f"Click action {nav_result}",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Click error: {e}")
            return ActionResult(error=f"Failed to perform click action: {str(e)}", include_in_memory=True)
    
    async def action_browser_input_impl(params, browser):
        """Handle input operations in browser."""
        page = browser.page
        
        try:
            # Get page details
            current_url = page.url
            title = await page.title()
            
            # If index is provided, type in element by index
            if params.index is not None:
                # Evaluate JavaScript to find input elements
                elements = await page.evaluate(HelperJs.FIND_INPUTS)
                
                if params.index >= len(elements):
                    return ActionResult(
                        error=f"Index {params.index} is out of range. Only {len(elements)} input elements found.",
                        include_in_memory=True
                    )
                
                # Get the element to input text into
                element = elements[params.index]
                
                # Calculate the center of the element
                x = element["rect"]["x"] + element["rect"]["width"] / 2
                y = element["rect"]["y"] + element["rect"]["height"] / 2
                
                # Scroll to the element
                await page.evaluate(f"window.scrollTo(0, {max(0, y - 100)})")
                
                # Click on the element to focus it
                await page.mouse.click(x, y)
                
                # Clear any existing text (select all and delete)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Delete")
                
                # Type the text
                await page.keyboard.type(params.text)
                
                # Press Enter if requested
                if params.press_enter:
                    await page.keyboard.press("Enter")
                    
                    # Wait for any resulting navigation
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        # Ignore timeout, page might not have navigated
                        pass
            
            # If coordinates are provided, click at that location and input text
            elif params.coordinate_x is not None and params.coordinate_y is not None:
                x = params.coordinate_x
                y = params.coordinate_y
                
                # Scroll to the coordinates
                await page.evaluate(f"window.scrollTo(0, {max(0, y - 100)})")
                
                # Click at the specified coordinates to focus
                await page.mouse.click(x, y)
                
                # Clear any existing text (select all and delete)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Delete")
                
                # Type the text
                await page.keyboard.type(params.text)
                
                # Press Enter if requested
                if params.press_enter:
                    await page.keyboard.press("Enter")
                    
                    # Wait for any resulting navigation
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        # Ignore timeout, page might not have navigated
                        pass
            
            else:
                return ActionResult(
                    error="Either index or coordinates must be provided for input action.",
                    include_in_memory=True
                )
            
            # Get updated page details
            new_url = page.url
            new_title = await page.title()
            
            # Determine if navigation occurred
            nav_result = "and navigated to a new page" if new_url != current_url else ""
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=new_url,
                title=new_title,
                result=f"Text input successful {nav_result}",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Input error: {e}")
            return ActionResult(error=f"Failed to perform input action: {str(e)}", include_in_memory=True)
    
    async def action_browser_view_impl(params, browser):
        """View page content action."""
        page = browser.page
        
        try:
            # Reload the page if requested
            if params and params.reload:
                await page.reload(timeout=TOTAL_TIMEOUT_MS, wait_until="networkidle")
                await asyncio.sleep(1)
            
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Extract page content using JavaScript
            content = await page.evaluate(HelperJs.EXTRACT_CONTENT)
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=current_url,
                title=title,
                result=content,
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"View error: {e}")
            return ActionResult(error=f"Failed to view page content: {str(e)}", include_in_memory=True)
    
    async def action_browser_screenshot_impl(params, browser):
        """Take a screenshot of the current page."""
        page = browser.page
        
        try:
            # Reload the page if requested
            if params and params.reload:
                await page.reload(timeout=TOTAL_TIMEOUT_MS, wait_until="networkidle")
                await asyncio.sleep(1)
            
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Define the file path for the screenshot
            file_path = params.file
            if not os.path.isabs(file_path):
                file_path = os.path.join(DEFAULT_WORKING_DIR, file_path)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Take the screenshot
            await page.screenshot(path=file_path, full_page=True)
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=current_url,
                title=title,
                result=f"Screenshot saved to {file_path}",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return ActionResult(error=f"Failed to take screenshot: {str(e)}", include_in_memory=True)
    
    async def action_browser_scroll_down_impl(params, browser):
        """Scroll the page down."""
        page = browser.page
        
        try:
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Get current scroll position and page height
            current_scroll = await page.evaluate("window.scrollY")
            window_height = await page.evaluate("window.innerHeight")
            page_height = await page.evaluate("document.documentElement.scrollHeight")
            
            # Calculate new scroll position
            if params and params.to_bottom:
                # Scroll to the bottom of the page
                new_scroll = page_height
            else:
                # Scroll down by one viewport height
                new_scroll = min(current_scroll + window_height, page_height - window_height)
            
            # Perform the scroll
            await page.evaluate(f"window.scrollTo(0, {new_scroll})")
            
            # Wait a moment for any lazy-loaded content
            await asyncio.sleep(0.5)
            
            # Recalculate page height (may have changed due to lazy loading)
            updated_page_height = await page.evaluate("document.documentElement.scrollHeight")
            updated_scroll = await page.evaluate("window.scrollY")
            
            # Calculate remaining pixels below viewport
            pixels_below = max(0, updated_page_height - (updated_scroll + window_height))
            
            scroll_result = "bottom of page" if params and params.to_bottom else f"position {updated_scroll}px"
            
            return ActionResult(
                url=current_url,
                title=title,
                result=f"Scrolled to {scroll_result}",
                pixels_below=pixels_below,
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Scroll down error: {e}")
            return ActionResult(error=f"Failed to scroll down: {str(e)}", include_in_memory=True)
    
    async def action_browser_scroll_up_impl(params, browser):
        """Scroll the page up."""
        page = browser.page
        
        try:
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Get current scroll position and page height
            current_scroll = await page.evaluate("window.scrollY")
            window_height = await page.evaluate("window.innerHeight")
            page_height = await page.evaluate("document.documentElement.scrollHeight")
            
            # Calculate new scroll position
            if params and params.to_top:
                # Scroll to the top of the page
                new_scroll = 0
            else:
                # Scroll up by one viewport height
                new_scroll = max(current_scroll - window_height, 0)
            
            # Perform the scroll
            await page.evaluate(f"window.scrollTo(0, {new_scroll})")
            
            # Wait a moment for any animations to complete
            await asyncio.sleep(0.5)
            
            # Get updated scroll position
            updated_scroll = await page.evaluate("window.scrollY")
            
            # Calculate remaining pixels below viewport
            pixels_below = max(0, page_height - (updated_scroll + window_height))
            
            scroll_result = "top of page" if params and params.to_top else f"position {updated_scroll}px"
            
            return ActionResult(
                url=current_url,
                title=title,
                result=f"Scrolled to {scroll_result}",
                pixels_below=pixels_below,
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Scroll up error: {e}")
            return ActionResult(error=f"Failed to scroll up: {str(e)}", include_in_memory=True)
    
    async def action_browser_press_key_impl(params, browser):
        """Press a key in the browser."""
        page = browser.page
        
        try:
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Press the specified key
            await page.keyboard.press(params.key)
            
            # Wait for any resulting navigation or page updates
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except:
                # Ignore timeout, page might not have navigated
                pass
            
            # Get updated page details
            new_url = page.url
            new_title = await page.title()
            
            # Determine if navigation occurred
            nav_result = "and navigated to a new page" if new_url != current_url else ""
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=new_url,
                title=new_title,
                result=f"Pressed key '{params.key}' {nav_result}",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Key press error: {e}")
            return ActionResult(error=f"Failed to press key '{params.key}': {str(e)}", include_in_memory=True)
    
    async def action_browser_select_option_impl(params, browser):
        """Select an option from a dropdown menu."""
        page = browser.page
        
        try:
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Find all select elements
            select_elements = await page.query_selector_all('select')
            
            if params.index >= len(select_elements):
                return ActionResult(
                    error=f"Index {params.index} is out of range. Only {len(select_elements)} select elements found.",
                    include_in_memory=True
                )
            
            # Get the select element
            select_element = select_elements[params.index]
            
            # Scroll to the element
            await select_element.scroll_into_view_if_needed()
            
            # Get all options in the select element
            options = await select_element.query_selector_all('option')
            
            if params.option >= len(options):
                return ActionResult(
                    error=f"Option index {params.option} is out of range. Only {len(options)} options found.",
                    include_in_memory=True
                )
            
            # Get the option value
            option_element = options[params.option]
            option_value = await option_element.get_attribute('value')
            option_text = await option_element.inner_text()
            
            # Select the option
            await select_element.select_option(value=option_value)
            
            # Wait for any resulting events or page updates
            await asyncio.sleep(0.5)
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=current_url,
                title=title,
                result=f"Selected option '{option_text}' from select element at index {params.index}",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Select option error: {e}")
            return ActionResult(error=f"Failed to select option: {str(e)}", include_in_memory=True)
    
    async def action_browser_console_exec_impl(params, browser):
        """Execute JavaScript code in the browser console."""
        page = browser.page
        
        try:
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Initialize console logging if needed
            await page.evaluate(HelperJs.INIT_CONSOLE_LOGGING)
            
            # Execute the JavaScript code
            result = await page.evaluate(params.javascript)
            
            # Convert result to string if it's not already
            if result is None:
                result_str = "undefined"
            elif isinstance(result, (dict, list)):
                result_str = str(result)
            else:
                result_str = str(result)
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=current_url,
                title=title,
                result=f"JavaScript executed successfully. Result: {result_str}",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Console exec error: {e}")
            return ActionResult(error=f"Failed to execute JavaScript: {str(e)}", include_in_memory=True)
    
    async def action_browser_console_view_impl(params, browser):
        """View the console logs in the browser."""
        page = browser.page
        
        try:
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Initialize console logging if needed
            init_result = await page.evaluate(HelperJs.INIT_CONSOLE_LOGGING)
            
            # Get console logs
            max_lines = params.max_lines if params and params.max_lines is not None else 100
            logs = await page.evaluate(HelperJs.CONSOLE_LOGS % max_lines)
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=current_url,
                title=title,
                result=f"Console logs:\n\n{logs}",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Console view error: {e}")
            return ActionResult(error=f"Failed to view console logs: {str(e)}", include_in_memory=True)
    
    async def action_browser_restart_impl(params, browser):
        """Restart the browser instance."""
        try:
            # Close the current browser context and page
            await browser_context.close()
            
            # Recreate the browser context
            await browser_context.create()
            
            # Create a new page and navigate to the initial URL
            page = browser_context.page
            url = params.url
            
            # Setup default headers
            await page.set_extra_http_headers(default_headers)
            
            # Navigate to the specified URL
            response = await page.goto(url, timeout=TOTAL_TIMEOUT_MS, wait_until="networkidle")
            
            # Wait for page to stabilize
            await asyncio.sleep(1)
            
            current_url = page.url
            title = await page.title()
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=current_url,
                title=title,
                result=f"Browser restarted and navigated to {url}",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Browser restart error: {e}")
            return ActionResult(error=f"Failed to restart browser: {str(e)}", include_in_memory=True)
    
    async def action_browser_move_mouse_impl(params, browser):
        """Move the mouse to specified coordinates."""
        page = browser.page
        
        try:
            # Get current page details
            current_url = page.url
            title = await page.title()
            
            # Extract coordinates
            x = params.coordinate_x
            y = params.coordinate_y
            
            # Scroll to ensure the target area is visible
            await page.evaluate(f"window.scrollTo(0, {max(0, y - 100)})")
            
            # Move the mouse to the specified coordinates
            await page.mouse.move(x, y)
            
            # Get the page height for scrolling calculations
            height = await page.evaluate("document.documentElement.scrollHeight")
            
            return ActionResult(
                url=current_url,
                title=title,
                result=f"Moved mouse to coordinates ({x}, {y})",
                pixels_below=max(0, height - await page.evaluate("window.innerHeight")),
                include_in_memory=True
            )
        except Exception as e:
            logger.error(f"Mouse movement error: {e}")
            return ActionResult(error=f"Failed to move mouse: {str(e)}", include_in_memory=True)
    
    # Assign the implementation functions to the lambda placeholders
    action_browser_navigate = action_browser_navigate_impl
    action_browser_click = action_browser_click_impl
    action_browser_input = action_browser_input_impl
    action_browser_view = action_browser_view_impl
    action_browser_screenshot = action_browser_screenshot_impl
    action_browser_scroll_down = action_browser_scroll_down_impl
    action_browser_scroll_up = action_browser_scroll_up_impl
    action_browser_press_key = action_browser_press_key_impl
    action_browser_select_option = action_browser_select_option_impl
    action_browser_console_exec = action_browser_console_exec_impl
    action_browser_console_view = action_browser_console_view_impl
    action_browser_restart = action_browser_restart_impl
    action_browser_move_mouse = action_browser_move_mouse_impl
    
    # Create browser context
    browser_context = BrowserContext(manager)
    
    # Register action handlers with the manager
    manager.register_action_handler("browser_navigate", action_browser_navigate)
    manager.register_action_handler("browser_click", action_browser_click)
    manager.register_action_handler("browser_input", action_browser_input)
    manager.register_action_handler("browser_view", action_browser_view)
    manager.register_action_handler("browser_screenshot", action_browser_screenshot)
    manager.register_action_handler("browser_scroll_down", action_browser_scroll_down)
    manager.register_action_handler("browser_scroll_up", action_browser_scroll_up)
    manager.register_action_handler("browser_press_key", action_browser_press_key)
    manager.register_action_handler("browser_select_option", action_browser_select_option)
    manager.register_action_handler("browser_console_exec", action_browser_console_exec)
    manager.register_action_handler("browser_console_view", action_browser_console_view)
    manager.register_action_handler("browser_restart", action_browser_restart)
    manager.register_action_handler("browser_move_mouse", action_browser_move_mouse)
    
    return browser_context