"""
Playwright browser on steroids.
"""

import asyncio
import base64
import gc
import io
import json
import logging
import os
import pathlib
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, TypedDict, cast
from urllib.parse import urlparse

from PIL import Image
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext as PlaywrightBrowserContext
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, ElementHandle, FrameLocator
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from browser_use.browser.views import (
    BrowserError, 
    BrowserState, 
    ClickableElementData, 
    ElementInfo, 
    ExtractedPageContentInfo, 
    ScreenshotError, 
    TabInfo, 
    URLNotAllowedError
)
from browser_use.dom.views import DOMElementNode
from browser_use.dom.service import DomService
from browser_use.utils import time_execution_sync, time_execution_async

if TYPE_CHECKING:
    from browser_use.browser.browser import Browser
    from browser_use.dom.views import SelectorMap

# Constants
JS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '../../app_data/js'))
URL_BLANK = 'about:blank'

# Configure PIL logging
logging.getLogger('PIL').setLevel(logging.CRITICAL + 1)
logger = logging.getLogger(__name__)


class BrowserContextWindowSize(TypedDict):
    """
    Size configuration for browser window
    """
    width: int
    height: int


class PageDeadError(Exception):
    """
    Exception raised when a page is no longer accessible
    """
    pass


@dataclass
class BrowserContextConfig:
    """
    Configuration for the BrowserContext.

    Default values:
        cookies_file: None
            Path to cookies file for persistence

            disable_security: True
                    Disable browser security features

        minimum_wait_page_load_time: 0.5
            Minimum time to wait before getting page state for LLM input

            wait_for_network_idle_page_load_time: 1.0
                    Time to wait for network requests to finish before getting page state.
                    Lower values may result in incomplete page loads.

        maximum_wait_page_load_time: 5.0
            Maximum time to wait for page load before proceeding anyway

        wait_between_actions: 1.0
            Time to wait between multiple per step actions

        browser_window_size: {
                'width': 1280,
                'height': 1100,
            }
            Default browser window size

        no_viewport: False
            Disable viewport

        save_recording_path: None
            Path to save video recordings

        save_downloads_path: None
            Path to save downloads to

        trace_path: None
            Path to save trace files. It will auto name the file with the TRACE_PATH/{context_id}.zip

        locale: None
            Specify user locale, for example en-GB, de-DE, etc. Locale will affect navigator.language value, Accept-Language request header value as well as number and date formatting rules. If not provided, defaults to the system default locale.

        user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
            custom user agent to use.

        highlight_elements: True
            Highlight elements in the DOM on the screen

        viewport_expansion: 500
            Viewport expansion in pixels. This amount will increase the number of elements which are included in the state what the LLM will see. If set to -1, all elements will be included (this leads to high token usage). If set to 0, only the elements which are visible in the viewport will be included.

        allowed_domains: None
            List of allowed domains that can be accessed. If None, all domains are allowed.
            Example: ['example.com', 'api.example.com']

        include_dynamic_attributes: bool = True
            Include dynamic attributes in the CSS selector. If you want to reuse the css_selectors, it might be better to set this to False.
    """

    cookies_file: str | None = None
    minimum_wait_page_load_time: float = 0.25
    wait_for_network_idle_page_load_time: float = 0.5
    maximum_wait_page_load_time: float = 5
    wait_between_actions: float = 0.5

    disable_security: bool = True

    browser_window_size: BrowserContextWindowSize = field(default_factory=lambda: {'width': 1280, 'height': 1100})
    no_viewport: Optional[bool] = None

    save_recording_path: str | None = None
    save_downloads_path: str | None = None
    trace_path: str | None = None
    locale: str | None = None
    user_agent: str = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
    )

    highlight_elements: bool = True
    viewport_expansion: int = 500
    allowed_domains: list[str] | None = None
    include_dynamic_attributes: bool = True

    _force_keep_context_alive: bool = False


@dataclass
class BrowserSession:
    """
    Browser session containing the context and cached state
    """
    context: PlaywrightBrowserContext
    cached_state: BrowserState | None


@dataclass
class BrowserContextState:
    """
    State of the browser context
    """
    target_id: str | None = None  # CDP target ID


class BrowserContext:
    """
    Enhanced browser context that wraps Playwright's browser context
    with additional functionality for browser automation.
    """
    
    def __init__(
        self,
        browser: 'Browser',
        config: BrowserContextConfig = BrowserContextConfig(),
        state: Optional[BrowserContextState] = None,
    ):
        """
        Initialize a new browser context
        
        Args:
            browser: Browser instance that this context belongs to
            config: Configuration for the browser context
            state: Optional state for the browser context
        """
        self.context_id = str(uuid.uuid4())
        logger.debug(f'Initializing new browser context with id: {self.context_id}')

        self.config = config
        self.browser = browser
        self.state = state or BrowserContextState()
        
        # Initialize these as None - they'll be set up when needed
        self.session: BrowserSession | None = None
        self._page_event_handler = None
        self.current_state: BrowserState | None = None

    async def __aenter__(self):
        """Async context manager entry"""
        await self._initialize_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    @time_execution_async('--close')
    async def close(self):
        """Close the browser instance"""
        logger.debug('Closing browser context')

        try:
            if self.session is None:
                return

            # Then remove CDP protocol listeners
            if self._page_event_handler and self.session.context:
                try:
                    # This actually sends a CDP command to unsubscribe
                    self.session.context.remove_listener('page', self._page_event_handler)
                except Exception as e:
                    logger.debug(f'Failed to remove CDP listener: {e}')
                self._page_event_handler = None

            await self.save_cookies()

            if self.config.trace_path:
                try:
                    await self.session.context.tracing.stop(path=os.path.join(self.config.trace_path, f'{self.context_id}.zip'))
                except Exception as e:
                    logger.debug(f'Failed to stop tracing: {e}')

            # This is crucial - it closes the CDP connection
            if not self.config._force_keep_context_alive:
                try:
                    await self.session.context.close()
                except Exception as e:
                    logger.debug(f'Failed to close context: {e}')

        finally:
            # Dereference everything
            self.session = None
            self._page_event_handler = None

    def __del__(self):
        """Cleanup when object is destroyed"""
        if not self.config._force_keep_context_alive and self.session is not None:
            logger.debug('BrowserContext was not properly closed before destruction')
            try:
                # Use sync Playwright method for force cleanup
                if hasattr(self.session.context, '_impl_obj'):
                    asyncio.run(self.session.context._impl_obj.close())

                self.session = None
                gc.collect()
            except Exception as e:
                logger.warning(f'Failed to force close browser context: {e}')

    @time_execution_async('--initialize_session')
    async def _initialize_session(self):
        """Initialize the browser session"""
        logger.debug('Initializing browser context')

        playwright_browser = await self.browser.get_playwright_browser()
        context = await self._create_context(playwright_browser)
        self._page_event_handler = None

        # Get or create a page to use
        pages = context.pages

        self.session = BrowserSession(
            context=context,
            cached_state=None,
        )

        active_page = None
        if hasattr(self.browser, 'config') and getattr(self.browser.config, 'cdp_url', None):
            # If we have a saved target ID, try to find and activate it
            if self.state.target_id:
                targets = await self._get_cdp_targets()
                for target in targets:
                    if target['targetId'] == self.state.target_id:
                        # Find matching page by URL
                        for page in pages:
                            if page.url == target['url']:
                                active_page = page
                                break
                        break

        # If no target ID or couldn't find it, use existing page or create new
        if not active_page:
            if pages:
                active_page = pages[0]
                logger.debug('Using existing page')
            else:
                active_page = await context.new_page()
                logger.debug('Created new page')

            # Get target ID for the active page
            if hasattr(self.browser, 'config') and getattr(self.browser.config, 'cdp_url', None):
                targets = await self._get_cdp_targets()
                for target in targets:
                    if target['url'] == active_page.url:
                        self.state.target_id = target['targetId']
                        break

        # Bring page to front
        await active_page.bring_to_front()
        await active_page.wait_for_load_state('load')

        return self.session

    def _add_new_page_listener(self, context: PlaywrightBrowserContext):
        """Add listener for new page events"""
        async def on_page(page: Page):
            if hasattr(self.browser, 'config') and getattr(self.browser.config, 'cdp_url', None):
                await page.reload()  # Reload the page to avoid timeout errors
            await page.wait_for_load_state()
            logger.debug(f'New page opened: {page.url}')
            if self.session is not None:
                self.state.target_id = None

        self._page_event_handler = on_page
        context.on('page', on_page)

    async def get_session(self) -> BrowserSession:
        """Lazy initialization of the browser and related components"""
        if self.session is None:
            return await self._initialize_session()
        return self.session

    async def get_current_page(self) -> Page:
        """Get the current page"""
        session = await self.get_session()
        return await self._get_current_page(session)

    async def _create_context(self, browser: PlaywrightBrowser):
        """Creates a new browser context with anti-detection measures and loads cookies if available."""
        if hasattr(self.browser, 'config'):
            if getattr(self.browser.config, 'cdp_url', None) and len(browser.contexts) > 0:
                context = browser.contexts[0]
            elif getattr(self.browser.config, 'chrome_instance_path', None) and len(browser.contexts) > 0:
                # Connect to existing Chrome instance instead of creating new one
                context = browser.contexts[0]
            else:
                # Original code for creating new context
                context = await browser.new_context(
                    viewport=self.config.browser_window_size,
                    no_viewport=False,
                    user_agent=self.config.user_agent,
                    java_script_enabled=True,
                    bypass_csp=self.config.disable_security,
                    ignore_https_errors=self.config.disable_security,
                    record_video_dir=self.config.save_recording_path,
                    record_video_size=self.config.browser_window_size,
                    locale=self.config.locale,
                )
        else:
            # Fallback if browser doesn't have the config attribute
            context = await browser.new_context(
                viewport=self.config.browser_window_size,
                no_viewport=False,
                user_agent=self.config.user_agent,
                java_script_enabled=True,
                bypass_csp=self.config.disable_security,
                ignore_https_errors=self.config.disable_security,
                record_video_dir=self.config.save_recording_path,
                record_video_size=self.config.browser_window_size,
                locale=self.config.locale,
            )

        if self.config.trace_path:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)

        # Load cookies if they exist
        if self.config.cookies_file and os.path.exists(self.config.cookies_file):
            with open(self.config.cookies_file, 'r') as f:
                cookies = json.load(f)
                logger.info(f'Loaded {len(cookies)} cookies from {self.config.cookies_file}')
                await context.add_cookies(cookies)

        # Expose anti-detection scripts
        await context.add_init_script(
            """
            // Webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US']
            });

            // Plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Chrome runtime
            window.chrome = { runtime: {} };

            // Permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            (function () {
                const originalAttachShadow = Element.prototype.attachShadow;
                Element.prototype.attachShadow = function attachShadow(options) {
                    return originalAttachShadow.call(this, { ...options, mode: "open" });
                };
            })();
            """
        )

        return context

    async def _wait_for_stable_network(self):
        """Wait for network to become stable"""
        page = await self.get_current_page()

        pending_requests = set()
        last_activity = asyncio.get_event_loop().time()

        # Define relevant resource types and content types
        RELEVANT_RESOURCE_TYPES = {
            'document',
            'stylesheet',
            'image',
            'font',
            'script',
            'iframe',
        }

        RELEVANT_CONTENT_TYPES = {
            'text/html',
            'text/css',
            'application/javascript',
            'image/',
            'font/',
            'application/json',
        }

        # Additional patterns to filter out
        IGNORED_URL_PATTERNS = {
            # Analytics and tracking
            'analytics',
            'tracking',
            'telemetry',
            'beacon',
            'metrics',
            # Ad-related
            'doubleclick',
            'adsystem',
            'adserver',
            'advertising',
            # Social media widgets
            'facebook.com/plugins',
            'platform.twitter',
            'linkedin.com/embed',
            # Live chat and support
            'livechat',
            'zendesk',
            'intercom',
            'crisp.chat',
            'hotjar',
            # Push notifications
            'push-notifications',
            'onesignal',
            'pushwoosh',
            # Background sync/heartbeat
            'heartbeat',
            'ping',
            'alive',
            # WebRTC and streaming
            'webrtc',
            'rtmp://',
            'wss://',
            # Common CDNs for dynamic content
            'cloudfront.net',
            'fastly.net',
        }

        async def on_request(request):
            # Filter by resource type
            if request.resource_type not in RELEVANT_RESOURCE_TYPES:
                return

            # Filter out streaming, websocket, and other real-time requests
            if request.resource_type in {
                'websocket',
                'media',
                'eventsource',
                'manifest',
                'other',
            }:
                return

            # Filter out by URL patterns
            url = request.url.lower()
            if any(pattern in url for pattern in IGNORED_URL_PATTERNS):
                return

            # Filter out data URLs and blob URLs
            if url.startswith(('data:', 'blob:')):
                return

            # Filter out requests with certain headers
            headers = request.headers
            if headers.get('purpose') == 'prefetch' or headers.get('sec-fetch-dest') in [
                'video',
                'audio',
            ]:
                return

            nonlocal last_activity
            pending_requests.add(request)
            last_activity = asyncio.get_event_loop().time()
            # logger.debug(f'Request started: {request.url} ({request.resource_type})')

        async def on_response(response):
            request = response.request
            if request not in pending_requests:
                return

            # Filter by content type if available
            content_type = response.headers.get('content-type', '').lower()

            # Skip if content type indicates streaming or real-time data
            if any(
                t in content_type
                for t in [
                    'streaming',
                    'video',
                    'audio',
                    'webm',
                    'mp4',
                    'event-stream',
                    'websocket',
                    'protobuf',
                ]
            ):
                pending_requests.remove(request)
                return

            # Only process relevant content types
            if not any(ct in content_type for ct in RELEVANT_CONTENT_TYPES):
                pending_requests.remove(request)
                return

            # Skip if response is too large (likely not essential for page load)
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > 5 * 1024 * 1024:  # 5MB
                pending_requests.remove(request)
                return

            nonlocal last_activity
            pending_requests.remove(request)
            last_activity = asyncio.get_event_loop().time()
            # logger.debug(f'Request resolved: {request.url} ({content_type})')

        # Attach event listeners
        page.on('request', on_request)
        page.on('response', on_response)

        try:
            # Wait for idle time
            start_time = asyncio.get_event_loop().time()
            while True:
                await asyncio.sleep(0.1)
                now = asyncio.get_event_loop().time()
                if len(pending_requests) == 0 and (now - last_activity) >= self.config.wait_for_network_idle_page_load_time:
                    break
                if now - start_time > self.config.maximum_wait_page_load_time:
                    logger.debug(
                        f'Network timeout after {self.config.maximum_wait_page_load_time}s with {len(pending_requests)} '
                        f'pending requests: {[r.url for r in pending_requests]}'
                    )
                    break

        finally:
            # Clean up event listeners
            page.remove_listener('request', on_request)
            page.remove_listener('response', on_response)

        logger.debug(f'Network stabilized for {self.config.wait_for_network_idle_page_load_time} seconds')

    async def _wait_for_page_and_frames_load(self, timeout_overwrite: float | None = None):
        """
        Ensures page is fully loaded before continuing.
        Waits for either network to be idle or minimum WAIT_TIME, whichever is longer.
        Also checks if the loaded URL is allowed.
        """
        # Start timing
        start_time = time.time()

        # Wait for page load
        try:
            await self._wait_for_stable_network()

            # Check if the loaded URL is allowed
            page = await self.get_current_page()
            await self._check_and_handle_navigation(page)
        except URLNotAllowedError as e:
            raise e
        except Exception:
            logger.warning('Page load failed, continuing...')
            pass

        # Calculate remaining time to meet minimum WAIT_TIME
        elapsed = time.time() - start_time
        remaining = max((timeout_overwrite or self.config.minimum_wait_page_load_time) - elapsed, 0)

        logger.debug(f'--Page loaded in {elapsed:.2f} seconds, waiting for additional {remaining:.2f} seconds')

        # Sleep remaining time if needed
        if remaining > 0:
            await asyncio.sleep(remaining)

    def _is_url_allowed(self, url: str) -> bool:
        """Check if a URL is allowed based on the whitelist configuration."""
        if not self.config.allowed_domains:
            return True

        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()

            # Remove port number if present
            if ':' in domain:
                domain = domain.split(':')[0]

            # Check if domain matches any allowed domain pattern
            return any(
                domain == allowed_domain.lower() or domain.endswith('.' + allowed_domain.lower())
                for allowed_domain in self.config.allowed_domains
            )
        except Exception as e:
            logger.error(f'Error checking URL allowlist: {str(e)}')
            return False

    async def _check_and_handle_navigation(self, page: Page) -> None:
        """Check if current page URL is allowed and handle if not."""
        if not self._is_url_allowed(page.url):
            logger.warning(f'Navigation to non-allowed URL detected: {page.url}')
            try:
                await self.go_back()
            except Exception as e:
                logger.error(f'Failed to go back after detecting non-allowed URL: {str(e)}')
            raise URLNotAllowedError(f'Navigation to non-allowed URL: {page.url}')

    async def navigate_to(self, url: str):
        """Navigate to a URL"""
        if not self._is_url_allowed(url):
            raise BrowserError(f'Navigation to non-allowed URL: {url}')

        page = await self.get_current_page()
        await page.goto(url)
        await page.wait_for_load_state()

    async def refresh_page(self):
        """Refresh the current page"""
        page = await self.get_current_page()
        await page.reload()
        await page.wait_for_load_state()

    async def go_back(self):
        """Navigate back in history"""
        page = await self.get_current_page()
        try:
            # 10 ms timeout
            await page.go_back(timeout=10, wait_until='domcontentloaded')
            # await self._wait_for_page_and_frames_load(timeout_overwrite=1.0)
        except Exception as e:
            # Continue even if its not fully loaded, because we wait later for the page to load
            logger.debug(f'During go_back: {e}')

    async def go_forward(self):
        """Navigate forward in history"""
        page = await self.get_current_page()
        try:
            await page.go_forward(timeout=10, wait_until='domcontentloaded')
        except Exception as e:
            # Continue even if its not fully loaded, because we wait later for the page to load
            logger.debug(f'During go_forward: {e}')

    async def close_current_tab(self):
        """Close the current tab"""
        session = await self.get_session()
        page = await self._get_current_page(session)
        await page.close()

        # Switch to the first available tab if any exist
        if session.context.pages:
            await self.switch_to_tab(0)

        # otherwise the browser will be closed

    async def get_page_html(self) -> str:
        """Get the current page HTML content"""
        page = await self.get_current_page()
        return await page.content()

    async def execute_javascript(self, script: str):
        """Execute JavaScript code on the page"""
        page = await self.get_current_page()
        return await page.evaluate(script)

    @time_execution_sync('--get_state')
    async def get_state(self) -> BrowserState:
        """Get the current state of the browser"""
        await self._wait_for_page_and_frames_load()
        session = await self.get_session()
        session.cached_state = await self._update_state()

        # Save cookies if a file is specified
        if self.config.cookies_file:
            asyncio.create_task(self.save_cookies())

        return session.cached_state

    async def _update_state(self, focus_element: int = -1) -> BrowserState:
        """Update and return state."""
        session = await self.get_session()

        # Check if current page is still valid, if not switch to another available page
        try:
            page = await self.get_current_page()
            # Test if page is still accessible
            await page.evaluate('1')
        except Exception as e:
            logger.debug(f'Current page is no longer accessible: {str(e)}')
            # Get all available pages
            pages = session.context.pages
            if pages:
                self.state.target_id = None
                page = await self._get_current_page(session)
                logger.debug(f'Switched to page: {await page.title()}')
            else:
                raise BrowserError('Browser closed: no valid pages available')

        try:
            await self.remove_highlights()
            dom_service = DomService(page)
            content = await dom_service.get_clickable_elements(
                focus_element=focus_element,
                viewport_expansion=self.config.viewport_expansion,
                highlight_elements=self.config.highlight_elements,
            )

            screenshot_b64 = await self.take_screenshot()
            pixels_above, pixels_below = await self.get_scroll_info(page)

            self.current_state = BrowserState(
                element_tree=content.element_tree,
                selector_map=content.selector_map,
                url=page.url,
                title=await page.title(),
                tabs=await self.get_tabs_info(),
                screenshot=screenshot_b64,
                pixels_above=pixels_above,
                pixels_below=pixels_below,
            )

            return self.current_state
        except Exception as e:
            logger.error(f'Failed to update state: {str(e)}')
            # Return last known good state if available
            if hasattr(self, 'current_state'):
                return self.current_state
            raise

    # Browser Actions
    @time_execution_async('--take_screenshot')
    async def take_screenshot(self, full_page: bool = False) -> str:
        """
        Returns a base64 encoded screenshot of the current page.
        """
        page = await self.get_current_page()

        await page.bring_to_front()
        await page.wait_for_load_state()

        screenshot = await page.screenshot(
            full_page=full_page,
            animations='disabled',
        )

        screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')

        return screenshot_b64

    @time_execution_async('--remove_highlights')
    async def remove_highlights(self):
        """
        Removes all highlight overlays and labels created by the highlightElement function.
        Handles cases where the page might be closed or inaccessible.
        """
        try:
            page = await self.get_current_page()
            await page.evaluate(
                """
                try {
                    // Remove the highlight container and all its contents
                    const container = document.getElementById('playwright-highlight-container');
                    if (container) {
                        container.remove();
                    }

                    // Remove highlight attributes from elements
                    const highlightedElements = document.querySelectorAll('[browser-user-highlight-id^="playwright-highlight-"]');
                    highlightedElements.forEach(el => {
                        el.removeAttribute('browser-user-highlight-id');
                    });
                } catch (e) {
                    console.error('Failed to remove highlights:', e);
                }
                """
            )
        except Exception as e:
            logger.debug(f'Failed to remove highlights (this is usually ok): {str(e)}')
            # Don't raise the error since this is not critical functionality
            pass

    # Selector Generation Methods
    @classmethod
    def _convert_simple_xpath_to_css_selector(cls, xpath: str) -> str:
        """Converts simple XPath expressions to CSS selectors."""
        if not xpath:
            return ''

        # Remove leading slash if present
        xpath = xpath.lstrip('/')

        # Split into parts
        parts = xpath.split('/')
        css_parts = []

        for part in parts:
            if not part:
                continue

            # Handle index notation [n]
            if '[' in part:
                base_part = part[: part.find('[')]
                index_part = part[part.find('[') :]

                # Handle multiple indices
                indices = [i.strip('[]') for i in index_part.split(']')[:-1]]

                for idx in indices:
                    try:
                        # Handle numeric indices
                        if idx.isdigit():
                            index = int(idx) - 1
                            base_part += f':nth-of-type({index + 1})'
                        # Handle last() function
                        elif idx == 'last()':
                            base_part += ':last-of-type'
                        # Handle position() functions
                        elif 'position()' in idx:
                            if '>1' in idx:
                                base_part += ':nth-of-type(n+2)'
                    except ValueError:
                        continue

                css_parts.append(base_part)
            else:
                css_parts.append(part)

        base_selector = ' > '.join(css_parts)
        return base_selector

    @classmethod
    @time_execution_sync('--enhanced_css_selector_for_element')
    def _enhanced_css_selector_for_element(cls, element: DOMElementNode, include_dynamic_attributes: bool = True) -> str:
        """
        Creates a CSS selector for a DOM element, handling various edge cases and special characters.

        Args:
            element: The DOM element to create a selector for
            include_dynamic_attributes: Whether to include dynamic attributes in the selector

        Returns:
            A valid CSS selector string
        """
        try:
            # Get base selector from XPath
            css_selector = cls._convert_simple_xpath_to_css_selector(element.xpath)

            # Handle class attributes
            if 'class' in element.attributes and element.attributes['class'] and include_dynamic_attributes:
                # Define a regex pattern for valid class names in CSS
                valid_class_name_pattern = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_-]*')

                # Iterate through the class attribute values
                classes = element.attributes['class'].split()
                for class_name in classes:
                    # Skip empty class names
                    if not class_name.strip():
                        continue

                    # Check if the class name is valid
                    if valid_class_name_pattern.match(class_name):
                        # Append the valid class name to the CSS selector
                        css_selector += f'.{class_name}'
                    else:
                        # Skip invalid class names
                        continue

            # Expanded set of safe attributes that are stable and useful for selection
            SAFE_ATTRIBUTES = {
                # Data attributes (if they're stable in your application)
                'id',
                # Standard HTML attributes
                'name',
                'type',
                'placeholder',
                # Accessibility attributes
                'aria-label',
                'aria-labelledby',
                'aria-describedby',
                'role',
                # Common form attributes
                'for',
                'autocomplete',
                'required',
                'readonly',
                # Media attributes
                'alt',
                'title',
                'src',
                # Custom stable attributes (add any application-specific ones)
                'href',
                'target',
            }

            if include_dynamic_attributes:
                dynamic_attributes = {
                    'data-id',
                    'data-qa',
                    'data-cy',
                    'data-testid',
                }
                SAFE_ATTRIBUTES.update(dynamic_attributes)

            # Handle other attributes
            for attribute, value in element.attributes.items():
                if attribute == 'class':
                    continue

                # Skip invalid attribute names
                if not attribute.strip():
                    continue

                if attribute not in SAFE_ATTRIBUTES:
                    continue

                # Escape special characters in attribute names
                safe_attribute = attribute.replace(':', r'\:')

                # Handle different value cases
                if value == '':
                    css_selector += f'[{safe_attribute}]'
                elif any(char in value for char in '"\'<>`\n\r\t'):
                    # Use contains for values with special characters
                    # Regex-substitute *any* whitespace with a single space, then strip.
                    collapsed_value = re.sub(r'\s+', ' ', value).strip()
                    # Escape embedded double-quotes.
                    safe_value = collapsed_value.replace('"', '\\"')
                    css_selector += f'[{safe_attribute}*="{safe_value}"]'
                else:
                    css_selector += f'[{safe_attribute}="{value}"]'

            return css_selector

        except Exception:
            # Fallback to a more basic selector if something goes wrong
            tag_name = element.tag_name or '*'
            return f"{tag_name}[highlight_index='{element.highlight_index}']"

    @time_execution_async('--get_locate_element')
    async def get_locate_element(self, element: DOMElementNode) -> Optional[ElementHandle]:
        """
        Locate an element in the DOM using the enhanced CSS selector
        
        Args:
            element: The DOM element to locate
            
        Returns:
            The element handle if found, None otherwise
        """
        current_frame = await self.get_current_page()

        # Start with the target element and collect all parents
        parents: list[DOMElementNode] = []
        current = element
        while current.parent is not None:
            parent = current.parent
            parents.append(parent)
            current = parent

        # Reverse the parents list to process from top to bottom
        parents.reverse()

        # Process all iframe parents in sequence
        iframes = [item for item in parents if item.tag_name == 'iframe']
        for parent in iframes:
            css_selector = self._enhanced_css_selector_for_element(
                parent,
                include_dynamic_attributes=self.config.include_dynamic_attributes,
            )
            current_frame = current_frame.frame_locator(css_selector)

        css_selector = self._enhanced_css_selector_for_element(
            element, include_dynamic_attributes=self.config.include_dynamic_attributes
        )

        try:
            if isinstance(current_frame, FrameLocator):
                element_handle = await current_frame.locator(css_selector).element_handle()
                return element_handle
            else:
                # Try to scroll into view if hidden
                element_handle = await current_frame.query_selector(css_selector)
                if element_handle:
                    await element_handle.scroll_into_view_if_needed()
                    return element_handle
                return None
        except Exception as e:
            logger.error(f'Failed to locate element: {str(e)}')
            return None

    @time_execution_async('--input_text_element_node')
    async def _input_text_element_node(self, element_node: DOMElementNode, text: str):
        """
        Input text into an element with proper error handling and state management.
        Handles different types of input fields and ensures proper element state before input.
        
        Args:
            element_node: The DOM element to input text into
            text: The text to input
        """
        try:
            element_handle = await self.get_locate_element(element_node)

            if element_handle is None:
                raise BrowserError(f'Element: {repr(element_node)} not found')

            # Ensure element is ready for input
            try:
                await element_handle.wait_for_element_state('stable', timeout=1000)
                await element_handle.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass

            # Get element properties to determine input method
            is_contenteditable = await element_handle.get_property('isContentEditable')

            # Different handling for contenteditable vs input fields
            if await is_contenteditable.json_value():
                await element_handle.evaluate('el => el.textContent = ""')
                await element_handle.type(text, delay=5)
            else:
                await element_handle.fill(text)

        except Exception as e:
            logger.debug(f'Failed to input text into element: {repr(element_node)}. Error: {str(e)}')
            raise BrowserError(f'Failed to input text into index {element_node.highlight_index}')

    async def input_text_to_element(self, index: int, text: str, delay: float = 0):
        """
        Input text into an element using its index
        
        Args:
            index: The index of the element to input text into
            text: The text to input
            delay: Optional delay before inputting text (in seconds)
        """
        selector_map = await self.get_selector_map()
        if index not in selector_map:
            raise BrowserError(f'No element found with index {index}')
            
        element_node = selector_map[index]
        
        if delay > 0:
            await asyncio.sleep(delay)
            
        await self._input_text_element_node(element_node, text)

    @time_execution_async('--click_element_node')
    async def _click_element_node(self, element_node: DOMElementNode) -> Optional[str]:
        """
        Optimized method to click an element
        
        Args:
            element_node: The DOM element to click
            
        Returns:
            Optional download path if a download was triggered
        """
        page = await self.get_current_page()

        try:
            element_handle = await self.get_locate_element(element_node)

            if element_handle is None:
                raise Exception(f'Element: {repr(element_node)} not found')

            async def perform_click(click_func):
                """Performs the actual click, handling both download
                and navigation scenarios."""
                if self.config.save_downloads_path:
                    try:
                        # Try short-timeout expect_download to detect a file download has been been triggered
                        async with page.expect_download(timeout=5000) as download_info:
                            await click_func()
                        download = await download_info.value
                        # Determine file path
                        suggested_filename = download.suggested_filename
                        unique_filename = await self._get_unique_filename(self.config.save_downloads_path, suggested_filename)
                        download_path = os.path.join(self.config.save_downloads_path, unique_filename)
                        await download.save_as(download_path)
                        logger.debug(f'Download triggered. Saved file to: {download_path}')
                        return download_path
                    except PlaywrightTimeoutError:
                        # If no download is triggered, treat as normal click
                        logger.debug('No download triggered within timeout. Checking navigation...')
                        await page.wait_for_load_state()
                        await self._check_and_handle_navigation(page)
                else:
                    # Standard click logic if no download is expected
                    await click_func()
                    await page.wait_for_load_state()
                    await self._check_and_handle_navigation(page)

            try:
                return await perform_click(lambda: element_handle.click(timeout=1500))
            except URLNotAllowedError as e:
                raise e
            except Exception:
                try:
                    return await perform_click(lambda: page.evaluate('(el) => el.click()', element_handle))
                except URLNotAllowedError as e:
                    raise e
                except Exception as e:
                    raise Exception(f'Failed to click element: {str(e)}')

        except URLNotAllowedError as e:
            raise e
        except Exception as e:
            raise Exception(f'Failed to click element: {repr(element_node)}. Error: {str(e)}')

    async def click_element(self, index: int):
        """
        Click an element using its index
        
        Args:
            index: The index of the element to click
        """
        selector_map = await self.get_selector_map()
        if index not in selector_map:
            raise BrowserError(f'No element found with index {index}')
            
        element_node = selector_map[index]
        return await self._click_element_node(element_node)

    async def get_element(self, index: int) -> ElementHandle:
        """
        Get an element handle by its index
        
        Args:
            index: The index of the element to get
            
        Returns:
            The element handle
        """
        selector_map = await self.get_selector_map()
        if index not in selector_map:
            raise BrowserError(f'No element found with index {index}')
            
        element_node = selector_map[index]
        element_handle = await self.get_locate_element(element_node)
        
        if element_handle is None:
            raise BrowserError(f'Element with index {index} not found in DOM')
            
        return element_handle

    @time_execution_async('--get_tabs_info')
    async def get_tabs_info(self) -> list[TabInfo]:
        """
        Get information about all tabs
        
        Returns:
            List of tab info objects
        """
        session = await self.get_session()

        tabs_info = []
        for page_id, page in enumerate(session.context.pages):
            tab_info = TabInfo(page_id=page_id, url=page.url, title=await page.title())
            tabs_info.append(tab_info)

        return tabs_info

    @time_execution_async('--switch_to_tab')
    async def switch_to_tab(self, page_id: int) -> None:
        """
        Switch to a specific tab by its page_id
        
        Args:
            page_id: The ID of the page to switch to
        """
        session = await self.get_session()
        pages = session.context.pages

        if page_id >= len(pages):
            raise BrowserError(f'No tab found with page_id: {page_id}')

        page = pages[page_id]

        # Check if the tab's URL is allowed before switching
        if not self._is_url_allowed(page.url):
            raise BrowserError(f'Cannot switch to tab with non-allowed URL: {page.url}')

        # Update target ID if using CDP
        if hasattr(self.browser, 'config') and getattr(self.browser.config, 'cdp_url', None):
            targets = await self._get_cdp_targets()
            for target in targets:
                if target['url'] == page.url:
                    self.state.target_id = target['targetId']
                    break

        await page.bring_to_front()
        await page.wait_for_load_state()

    @time_execution_async('--create_new_tab')
    async def create_new_tab(self, url: str | None = None) -> None:
        """
        Create a new tab and optionally navigate to a URL
        
        Args:
            url: Optional URL to navigate to
        """
        if url and not self._is_url_allowed(url):
            raise BrowserError(f'Cannot create new tab with non-allowed URL: {url}')

        session = await self.get_session()
        new_page = await session.context.new_page()
        await new_page.wait_for_load_state()

        if url:
            await new_page.goto(url)
            await self._wait_for_page_and_frames_load(timeout_overwrite=1)

        # Get target ID for new page if using CDP
        if hasattr(self.browser, 'config') and getattr(self.browser.config, 'cdp_url', None):
            targets = await self._get_cdp_targets()
            for target in targets:
                if target['url'] == new_page.url:
                    self.state.target_id = target['targetId']
                    break

    # Helper methods
    async def _get_current_page(self, session: BrowserSession) -> Page:
        """
        Get the current page
        
        Args:
            session: The browser session
            
        Returns:
            The current page
        """
        pages = session.context.pages

        # Try to find page by target ID if using CDP
        if hasattr(self.browser, 'config') and getattr(self.browser.config, 'cdp_url', None) and self.state.target_id:
            targets = await self._get_cdp_targets()
            for target in targets:
                if target['targetId'] == self.state.target_id:
                    for page in pages:
                        if page.url == target['url']:
                            return page

        # Fallback to last page
        return pages[-1] if pages else await session.context.new_page()

    async def get_selector_map(self) -> 'SelectorMap':
        """
        Get the selector map from the cached state
        
        Returns:
            The selector map
        """
        session = await self.get_session()
        if session.cached_state is None:
            return {}
        return session.cached_state.selector_map

    async def get_element_by_index(self, index: int) -> ElementHandle | None:
        """
        Get an element handle by its index
        
        Args:
            index: The index of the element to get
            
        Returns:
            The element handle, or None if not found
        """
        selector_map = await self.get_selector_map()
        if index not in selector_map:
            return None
            
        element_handle = await self.get_locate_element(selector_map[index])
        return element_handle

    async def get_dom_element_by_index(self, index: int) -> DOMElementNode:
        """
        Get a DOM element by its index
        
        Args:
            index: The index of the element to get
            
        Returns:
            The DOM element
        """
        selector_map = await self.get_selector_map()
        if index not in selector_map:
            raise BrowserError(f'No element found with index {index}')
            
        return selector_map[index]

    async def save_cookies(self):
        """Save current cookies to file"""
        if self.session and self.session.context and self.config.cookies_file:
            try:
                cookies = await self.session.context.cookies()
                logger.debug(f'Saving {len(cookies)} cookies to {self.config.cookies_file}')

                # Check if the path is a directory and create it if necessary
                dirname = os.path.dirname(self.config.cookies_file)
                if dirname:
                    os.makedirs(dirname, exist_ok=True)

                with open(self.config.cookies_file, 'w') as f:
                    json.dump(cookies, f)
            except Exception as e:
                logger.warning(f'Failed to save cookies: {str(e)}')

    async def is_file_uploader(self, element_node: DOMElementNode, max_depth: int = 3, current_depth: int = 0) -> bool:
        """
        Check if element or its children are file uploaders
        
        Args:
            element_node: The element to check
            max_depth: Maximum depth to check children
            current_depth: Current depth of recursion
            
        Returns:
            True if the element is a file uploader, False otherwise
        """
        if current_depth > max_depth:
            return False

        # Check current element
        is_uploader = False

        if not isinstance(element_node, DOMElementNode):
            return False

        # Check for file input attributes
        if element_node.tag_name == 'input':
            is_uploader = element_node.attributes.get('type') == 'file' or element_node.attributes.get('accept') is not None

        if is_uploader:
            return True

        # Recursively check children
        if element_node.children and current_depth < max_depth:
            for child in element_node.children:
                if isinstance(child, DOMElementNode):
                    if await self.is_file_uploader(child, max_depth, current_depth + 1):
                        return True

        return False

    async def get_scroll_info(self, page: Page) -> tuple[int, int]:
        """
        Get scroll position information for the current page
        
        Args:
            page: The page to get scroll info for
            
        Returns:
            Tuple of (pixels_above, pixels_below)
        """
        scroll_y = await page.evaluate('window.scrollY')
        viewport_height = await page.evaluate('window.innerHeight')
        total_height = await page.evaluate('document.documentElement.scrollHeight')
        pixels_above = scroll_y
        pixels_below = total_height - (scroll_y + viewport_height)
        return pixels_above, pixels_below

    async def reset_context(self):
        """
        Reset the browser session
        Call this when you don't want to kill the context but just kill the state
        """
        # close all tabs and clear cached state
        session = await self.get_session()

        pages = session.context.pages
        for page in pages:
            await page.close()

        session.cached_state = None
        self.state.target_id = None

    async def _get_unique_filename(self, directory, filename):
        """
        Generate a unique filename by appending (1), (2), etc., if a file already exists
        
        Args:
            directory: The directory to check
            filename: The original filename
            
        Returns:
            A unique filename
        """
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filename = filename
        while os.path.exists(os.path.join(directory, new_filename)):
            new_filename = f'{base} ({counter}){ext}'
            counter += 1
        return new_filename

    async def _get_cdp_targets(self) -> list[dict]:
        """
        Get all CDP targets directly using CDP protocol
        
        Returns:
            List of CDP targets
        """
        if not hasattr(self.browser, 'config') or not getattr(self.browser.config, 'cdp_url', None) or not self.session:
            return []

        try:
            pages = self.session.context.pages
            if not pages:
                return []

            cdp_session = await pages[0].context.new_cdp_session(pages[0])
            result = await cdp_session.send('Target.getTargets')
            await cdp_session.detach()
            return result.get('targetInfos', [])
        except Exception as e:
            logger.debug(f'Failed to get CDP targets: {e}')
            return []

    def _get_initial_state(self, page: Page) -> BrowserState:
        """
        Get the initial state of the browser
        
        Args:
            page: The current page
            
        Returns:
            The initial browser state
        """
        return BrowserState(
            element_tree=self._createRootNode(), 
            selector_map={}, 
            clickable_elements={}, 
            article_markdown='', 
            url=page.url if page else '', 
            title='', 
            tabs=[]
        )

    def _createRootNode(self) -> DOMElementNode:
        """
        Create the root DOM node
        
        Returns:
            The root DOM node
        """
        return DOMElementNode(
            False, 
            None, 
            '', 
            '', 
            {}, 
            []
        )