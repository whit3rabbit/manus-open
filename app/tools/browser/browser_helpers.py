import os
import pathlib
import base64
from dataclasses import dataclass

from app.logger import logger
from browser_use import ActionResult

__all__ = [
    'HelperJs',
    'screenshot_to_data_url',
    'check_file_path'
]

# Directory where JavaScript helper files are stored
JS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '../../../app_data/js'))

@dataclass
class HelperJs:
    """Container for JavaScript helper code snippets used for browser automation."""
    
    # Extract page content helper
    EXTRACT_CONTENT = """
    function extractPageContent() {
        // Get title and metadata
        const title = document.title;
        const metaDescription = document.querySelector('meta[name="description"]')?.content || '';
        
        // Get main content
        let mainContent = '';
        const mainElement = document.querySelector('main') || document.body;
        mainContent = mainElement.innerText;
        
        // Get all links
        const links = [];
        document.querySelectorAll('a[href]').forEach(link => {
            links.push({
                text: link.innerText.trim(),
                href: link.href
            });
        });
        
        return {
            title,
            metaDescription,
            mainContent,
            links,
            url: window.location.href
        };
    }
    
    return JSON.stringify(extractPageContent());
    """
    
    # Find clickable elements helper
    FIND_CLICKABLE = """
    function findClickableElements() {
        const clickableElements = [];
        
        // Common clickable elements
        const selectors = [
            'a', 'button', 'input[type="button"]', 'input[type="submit"]',
            '.btn', '[role="button"]', '[onclick]', 'select', 'summary',
            'details', '[tabindex]:not([tabindex="-1"])'
        ];
        
        const elements = document.querySelectorAll(selectors.join(', '));
        
        elements.forEach((el, index) => {
            // Check if element is visible
            const rect = el.getBoundingClientRect();
            const isVisible = !!(rect.width && rect.height &&
                window.getComputedStyle(el).getPropertyValue('display') !== 'none' &&
                window.getComputedStyle(el).getPropertyValue('visibility') !== 'hidden');
                
            if (isVisible) {
                clickableElements.push({
                    index,
                    tagName: el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: el.className || '',
                    text: el.innerText?.trim() || el.textContent?.trim() || '',
                    name: el.name || '',
                    href: el.href || '',
                    type: el.type || '',
                    value: el.value || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    rect: {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height
                    }
                });
            }
        });
        
        return clickableElements;
    }
    
    return JSON.stringify(findClickableElements());
    """
    
    # Find input elements helper
    FIND_INPUTS = """
    function findInputElements() {
        const inputElements = [];
        
        // Input selectors
        const selectors = [
            'input:not([type="button"]):not([type="submit"]):not([type="reset"]):not([type="hidden"])',
            'textarea',
            '[contenteditable="true"]',
            '[role="textbox"]'
        ];
        
        const elements = document.querySelectorAll(selectors.join(', '));
        
        elements.forEach((el, index) => {
            // Check if element is visible
            const rect = el.getBoundingClientRect();
            const isVisible = !!(rect.width && rect.height &&
                window.getComputedStyle(el).getPropertyValue('display') !== 'none' &&
                window.getComputedStyle(el).getPropertyValue('visibility') !== 'hidden');
                
            if (isVisible) {
                inputElements.push({
                    index,
                    tagName: el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: el.className || '',
                    name: el.name || '',
                    type: el.type || '',
                    placeholder: el.placeholder || '',
                    value: el.value || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    rect: {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height
                    }
                });
            }
        });
        
        return inputElements;
    }
    
    return JSON.stringify(findInputElements());
    """
    
    # Console log helper
    CONSOLE_LOGS = """
    function getConsoleLogs(maxLines) {
        if (!window.__consoleLogs) {
            return "Console logging not initialized. Refresh the page to enable logging.";
        }
        
        const logs = window.__consoleLogs;
        if (maxLines && logs.length > maxLines) {
            return logs.slice(logs.length - maxLines).join("\\n");
        }
        
        return logs.join("\\n");
    }
    
    return getConsoleLogs(%d);
    """
    
    # Initialize console logging
    INIT_CONSOLE_LOGGING = """
    (function initializeConsoleLogging() {
        if (window.__consoleLogs) {
            return "Console logging already initialized.";
        }
        
        window.__consoleLogs = [];
        
        // Store original console methods
        const originalConsole = {
            log: console.log,
            info: console.info,
            warn: console.warn,
            error: console.error,
            debug: console.debug
        };
        
        // Override console methods to capture logs
        console.log = function() {
            window.__consoleLogs.push(["LOG", ...arguments].map(arg =>
                typeof arg === 'object' ? JSON.stringify(arg) : String(arg)).join(" "));
            return originalConsole.log.apply(console, arguments);
        };
        
        console.info = function() {
            window.__consoleLogs.push(["INFO", ...arguments].map(arg =>
                typeof arg === 'object' ? JSON.stringify(arg) : String(arg)).join(" "));
            return originalConsole.info.apply(console, arguments);
        };
        
        console.warn = function() {
            window.__consoleLogs.push(["WARN", ...arguments].map(arg =>
                typeof arg === 'object' ? JSON.stringify(arg) : String(arg)).join(" "));
            return originalConsole.warn.apply(console, arguments);
        };
        
        console.error = function() {
            window.__consoleLogs.push(["ERROR", ...arguments].map(arg =>
                typeof arg === 'object' ? JSON.stringify(arg) : String(arg)).join(" "));
            return originalConsole.error.apply(console, arguments);
        };
        
        console.debug = function() {
            window.__consoleLogs.push(["DEBUG", ...arguments].map(arg =>
                typeof arg === 'object' ? JSON.stringify(arg) : String(arg)).join(" "));
            return originalConsole.debug.apply(console, arguments);
        };
        
        return "Console logging initialized.";
    })();
    """

# Read additional JavaScript helpers from files in JS_DIR
try:
    select_option = pathlib.Path(JS_DIR, "selectOption.js").read_text()
except Exception as e:
    logger.error(f"Error reading selectOption.js: {e}")
    select_option = ""

try:
    get_viewport = pathlib.Path(JS_DIR, "getViewport.js").read_text()
except Exception as e:
    logger.error(f"Error reading getViewport.js: {e}")
    get_viewport = ""

def screenshot_to_data_url(screenshot):
    '''将 base64 编码的截图转换为 data URL 格式 (Convert base64 encoded screenshot to data URL format)'''
    if isinstance(screenshot, bytes):
        screenshot = base64.b64encode(screenshot).decode('utf-8')
    return f'data:image/png;base64,{screenshot}'

def check_file_path(file_path):
    '''
    检查文件路径并创建必要的目录 (Check file path and create necessary directories)
    
    Args:
        file_path: 文件路径，必须是绝对路径 (file path, must be an absolute path)
        
    Returns:
        如果有错误返回 ActionResult，否则返回 None (Return ActionResult if there is an error, otherwise return None)
        
    错误情况: (Error cases:)
        - file_path 为空 (file_path is empty)
        - file_path 不是绝对路径 (file_path is not an absolute path)
        - file_path 指向的文件已存在 (file pointed to by file_path already exists)
        - 无法创建目录 (unable to create directory)
    '''
    if not file_path:
        return ActionResult(error='file_path is required', include_in_memory=True)
        
    if not file_path.startswith('/'):
        return ActionResult(error=f'File path must be absolute: {file_path}', include_in_memory=True)
        
    if pathlib.Path(file_path).exists():
        return ActionResult(error=f'File already exists: {file_path}', include_in_memory=True)
        
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        return None
    except Exception as e:
        logger.error(f"Error creating directory for file {file_path}: {e}")
        return ActionResult(error=f'Failed to create directory for {file_path}: {str(e)}', include_in_memory=True)
