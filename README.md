# Manus Sandbox

Claude generated files based on (bytecode):

https://gist.github.com/jlia0/db0a9695b3ca7609c9b1a08dcbf872c9

## Description

This repository implements a proxy server that allows users to interact with both terminal environments and web browsers programmatically. It offers a REST API for managing file operations, text editing, and browser actions, as well as WebSocket support for real-time terminal interaction. This setup is ideal for automation scenarios where you need to execute shell commands, interact with web pages, or manage files remotely.

## Features

- **Terminal Access via WebSocket**:
    - Establish persistent WebSocket connections for interactive terminal sessions.
    - Supports various terminal commands and operations like reset, kill process, and viewing history.
- **Browser Automation via REST API**:
    - Control browser actions such as navigation, clicking elements, inputting text, taking screenshots, and more through a REST API.
    - Provides browser status checks and restart capabilities.
- **File Management API**:
    - Upload files to presigned URLs, including support for multipart uploads for large files.
    - Download files and batch download multiple files to specified folders.
    - Zip and upload entire project directories.
- **Text Editor API**:
    - Perform text editor operations like viewing file content, creating new files, writing to files, string replacement, and content searching.
- **Sandbox Environment Initialization**:
    - Initialize a sandbox environment by setting up secrets securely.
- **Health Check Endpoint**:
    - Provides a `/healthz` endpoint for monitoring server availability.
- **Customizable Logging**:
    - Configurable logging level to suit different operational needs (debug, info, warning, error, critical).

## Architecture Overview

The project is structured into two main directories that handle different aspects of the functionality: `app` and `browser_use`.

### `app` Directory

The `app` directory contains the core server-side logic and API definitions. It's built using FastAPI and is responsible for:

- **API Routing (`app/router.py`):** Defines custom API route handling, including request timing and logging.
- **Server Logic (`app/server.py`):** Implements the FastAPI application, defines API endpoints, and orchestrates interactions with terminal and browser components.
- **WebSocket Server (`app/terminal_socket_server.py`):** Manages WebSocket connections for terminal sessions, handling message parsing and response sending.
- **Tools (`app/tools/`):** Contains modules for different tools:
    - `base.py`: Base classes and utilities for tools.
    - `browser/`:  Manages browser interactions, actions, and browser management.
    - `terminal/`: Manages terminal sessions, command execution, and terminal history.
    - `text_editor.py`: Implements text editor functionalities.
- **Helpers (`app/helpers/`):** Utility modules for common tasks:
    - `tool_helpers.py`: Utilities for running shell commands.
    - `utils.py`: General utility functions like file upload, text truncation, etc.
- **Models (`app/models.py`):** Defines Pydantic models for request and response data structures.
- **Logger (`app/logger.py`):** Configures logging for the application.
- **Types (`app/types/`):** Defines type hints and Pydantic models for browser and message types.

### `browser_use` Directory

Browser use is based on: https://github.com/browser-use/browser-use

However, it has been modified to use Claude API (browser_use/agent/service.py)

The `browser_use` directory houses the browser automation library, which is designed to be reusable and independent of the main `app` server. It provides:

- **Agent (`browser_use/agent/`):** Implements the agent logic for browser automation, message management, and prompts.
- **Browser (`browser_use/browser/`):** Manages browser instances, contexts, and pages using Playwright.
- **Controller (`browser_use/controller/`):** Defines actions and action registry for browser automation.
- **DOM (`browser_use/dom/`):** Handles Document Object Model (DOM) processing and element interaction.
- **Telemetry (`browser_use/telemetry/`):** Implements telemetry collection for usage metrics.
- **Utils (`browser_use/utils.py`):** Utility functions for the `browser_use` library.
- **Logging Configuration (`browser_use/logging_config.py`):** Configures logging specifically for the `browser_use` library.

**Relationship between `app` and `browser_use`**: The `app` directory leverages the `browser_use` library for browser automation functionalities. `app/server.py` and `app/terminal_socket_server.py` act as the entry points, using the tools and libraries from both `app` and `browser_use` to provide the API and WebSocket interfaces. `browser_use` is designed as a modular library that `app` integrates with, keeping the browser automation logic separate and reusable.

### `app_data` Directory

Currently, `app_data` contains a single subdirectory:

- **`js/`**: This directory specifically stores JavaScript files.

Inside the `js/` directory, you can find the following files based on the provided documentation:

- **`getViewport.js`**:

    - **Content**: Contains JavaScript code that, when executed in a browser, returns the current viewport dimensions (width and height) of the browser window.
    - **Usage**: This script is likely used by the browser automation tools to determine the visible area of a webpage, which can be important for actions like scrolling, element visibility checks, and responsive design considerations.

- **`runExtensionAction.js`**:

    - **Content**: Contains JavaScript code designed to interact with browser extensions. It likely provides a mechanism to send messages to browser extensions and handle responses.
    - **Usage**: This script suggests that the browser automation is capable of interacting with browser extensions programmatically. This could be used for tasks like:
        - Triggering actions within browser extensions.
        - Retrieving data from browser extensions.
        - Controlling extension behavior as part of an automation workflow.

- **`selectOption.js`**:

    - **Content**: Contains JavaScript code that helps in selecting an option from a dropdown (`<select>`) element on a webpage.
    - **Usage**: This script is used to programmatically interact with dropdown menus in web forms. It takes parameters (likely a CSS selector and option index) to locate and select a specific option within a dropdown, simulating user interaction with form elements.

### How `app_data/js` is Used in the Application

The JavaScript files in `app_data/js` are not directly executed as part of the backend server code (Python). Instead, they are designed to be:

1. **Read by the Python Backend**: The Python code in the `app` and `browser_use` directories (likely within `browser_use/browser/context.py` and `browser_use/dom/service.py`) reads the content of these `.js` files.
2. **Injected into the Browser Context**: The content of these JavaScript files is then injected into the browser context managed by Playwright. This is typically done using Playwright's `page.evaluate()` or `context.add_init_script()` methods.
3. **Executed in the Browser**: Once injected, the JavaScript code runs within the security context of the webpage loaded in the browser. This allows the server to:
    - Execute complex browser-side logic that is difficult or inefficient to perform from the server-side Python code.
    - Interact directly with the DOM, browser APIs, and potentially browser extensions.
    - Retrieve structured data from the webpage (like viewport dimensions or dropdown options).

**Example Usage Scenario (Hypothetical):**

When the server needs to get the viewport dimensions of a webpage during a browser automation task, it might:

1. Read the content of `app_data/js/getViewport.js`.
2. Use Playwright to execute this JavaScript code within the current browser page using `page.evaluate(getViewport_js_content)`.
3. Receive the JSON response from the JavaScript execution, containing the viewport width and height.

## API Structure

The API is structured to provide clear separation of concerns, with endpoints categorized by functionality.

### Authentication and API Client

I didn't actually see the header being used for the calls. However, in real world implementation an API token is used so that only
 valid API calls are allowed. The API key is set in: $HOME/.secrets/sandbox_api_token

data_api.py is used as a api client. The original proxy service is located at: https://api.manus.im/apiproxy.v1.ApiProxyService/CallApi but you can set it to localhost.

In order to work with API you need to create a key (assuming there is actually authentication):

```bash
curl -X GET http://localhost:8330/healthz -H "x-sandbox-token: dummy_api_key"
```

But I don't see the token being used anywhere in code so it's possible that it's only being used on the proxy, but that's just a guess.

### Terminal API Endpoints

- **`GET /terminal/{terminal_id}`**: Retrieves the content of a specific terminal session.
- **`POST /terminal/{terminal_id}/reset`**: Resets a specific terminal session, clearing its history and restarting the shell.
- **`POST /terminal/reset_all`**: Resets all active terminal sessions.
- **`POST /terminal/{terminal_id}/kill`**: Kills the current process running in a specific terminal session.
- **`POST /terminal/{terminal_id}/write`**: Writes text input to a specific terminal session.
- **`WebSocket /terminal`**: Establishes a WebSocket connection for real-time, bidirectional communication with a terminal session.

### Browser API Endpoints

- **`GET /browser/status`**: Checks the status of the browser automation service, indicating if it's running or stopped.
- **`POST /browser/action`**: Executes a browser action. Accepts a JSON payload defining the action to be performed, such as navigation, clicking, inputting text, etc.

### File API Endpoints

- **`POST /upload_file`**: Uploads a single file to a pre-signed URL. Requires `file_path` and `presigned_url` in the request body.
- **`POST /multipart_upload`**: Handles multipart uploads for large files, using pre-signed URLs for each part. Requires `file_path`, `presigned_urls` (list of pre-signed URLs for each part), and `part_size` in the request body.
- **`GET /get_file/{path:path}`**: Serves a file for download from the server's filesystem. The file path is specified in the URL path.
- **`POST /batch_download`**: Downloads multiple files from URLs to a specified folder on the server. Accepts a JSON payload with a list of files to download and an optional folder path.
- **`POST /zip_and_upload`**: Zips a specified directory and uploads the archive to a pre-signed URL. Requires `directory`, `upload_url`, and `project_type` in the request body.

### Text Editor API Endpoints

- **`POST /text_editor`**: Executes text editor actions. Accepts a JSON payload defining the text editor command (`view`, `create`, `write`, `str_replace`, `find_content`, `find_file`) and associated parameters like `path`, `file_text`, `old_str`, `new_str`, etc.

### Sandbox Initialization API Endpoints

- **`POST /init_sandbox`**: Initializes the sandbox environment with secrets. Accepts a JSON payload containing secrets as key-value pairs.

### Health Check API Endpoints

- **`GET /healthz`**: Provides a health check endpoint to verify if the server is running.

## Usage

### Starting the Server

To start the server, navigate to the repository directory and run:

```bash
python start_server.py
```

You can customize the server startup using command-line arguments:

- `--port <port>`:  Specify the port number for the server (default: 8330).
- `--host <host>`: Specify the host address to bind to (default: `0.0.0.0` for all interfaces).
- `--log-level <level>`: Set the logging level (`debug`, `info`, `warning`, `error`, `critical`; default: `info`).
- `--chrome-path <path>`: Provide a custom path to the Chrome browser executable.

**Example with custom port and log level:**

```bash
python start_server.py --port 8080 --log-level debug
```

### Interacting with the API

Once the server is running, you can interact with the API endpoints using tools like `curl`, `httpie`, or any HTTP client. For WebSocket interactions, you can use tools like `wscat` or implement a WebSocket client in your preferred programming language.

Refer to the "API Structure" section for details on each endpoint and the required request formats.

## Environment Variables

- **`CHROME_INSTANCE_PATH`**: (Optional) Specifies the path to a Chrome browser instance. If set, the server will use this instance for browser automation. If not set, the server will attempt to manage its own browser instance.
- **`RUNTIME_API_HOST`**: (Optional) Specifies the host URL for the internal API aggregation platform (used by `data_api.py`). Defaults to `https://api.manus.im`.
- **`BROWSER_USE_LOGGING_LEVEL`**: (Optional) Specifies the logging level for the `browser_use` library. Defaults to `info`.
