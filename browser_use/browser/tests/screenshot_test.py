import base64
import pytest
from browser_use.browser.browser import Browser, BrowserConfig

@pytest.fixture
def browser():
    """Create a browser instance for testing"""
    browser_config = BrowserConfig(headless=True)
    browser_instance = Browser(config=browser_config)
    yield browser_instance
    # Cleanup after tests
    # This would normally include code to close the browser

def test_take_full_page_screenshot(browser):
    """Test taking a full page screenshot"""
    browser.go_to_url('https://example.com')
    screenshot_data = browser.take_screenshot(full_page=True)
    
    # Verify the screenshot data is valid base64
    assert screenshot_data is not None
    try:
        base64.b64decode(screenshot_data)
        assert True
    except Exception:
        assert False, "Screenshot data is not valid base64"

if __name__ == '__main__':
    test_take_full_page_screenshot(Browser(config=BrowserConfig(headless=False)))