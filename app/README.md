# Sandbox Runtime API

This repository implements a multi-functional runtime API that provides endpoints for file operations, browser automation, terminal interactions, and text editor functionalities.
 It is designed to run with Python 3.11 inside a Docker container at `/opt/.manus/.sandbox-runtime/app`.

## Table of Contents

- [Features](#features)
- [Repository Structure](#repository-structure)
- [API Endpoints](#api-endpoints)
- [Running the Server](#running-the-server)
- [Usage](#usage)

## Features

- **File Operations**: Upload single or multipart files to S3, download files, and batch download attachments.
- **Browser Automation**: Execute browser actions (navigate, click, input, screenshot, etc.) using Playwright.
- **Terminal Interaction**: Manage terminal sessions via WebSockets, execute commands, view history, and control running processes.
- **Text Editor Operations**: View, create, modify, and search file contents.

## Repository Structure

Below is a tree view of the repository with a short description for each component:

```
app/
├── helpers/                  # Utility modules for shell commands and file operations
│   ├── tool_helpers.py       # Async shell command execution and output truncation utilities
│   ├── local_storage.py      # Removed S3 upload and now stores files locally
│   ├── utils.py              # File uploads, directory management, and multipart upload logic
│   └── __init__.py
├── logger.py                 # Logging configuration for the application
├── models.py                 # Data models (using Pydantic) for API requests/responses
├── README.md                 # Project documentation (this file)
├── router.py                 # Custom FastAPI route with request timing/logging
├── server.py                 # Main FastAPI application with API endpoint definitions
├── terminal_socket_server.py # WebSocket server for terminal connections and interactions
├── tools/                    # Collection of tools for browser, terminal, and text editing operations
│   ├── base.py              # Base classes and common utility functions for tools
│   ├── browser/             # Browser automation tools powered by Playwright
│   │   ├── browser_actions.py   # Handlers for browser actions (navigation, click, input, etc.)
│   │   ├── browser_helpers.py   # JavaScript snippets and helper functions for browser tasks
│   │   ├── browser_manager.py   # Manages the browser lifecycle and action execution
│   │   └── __init__.py
│   ├── terminal/            # Terminal management and communication tools
│   │   ├── expecter.py         # Asynchronous expect loop for terminal I/O handling
│   │   ├── terminal_helpers.py # Processing terminal output and ANSI escape sequences
│   │   ├── terminal_manager.py # Creates, manages, and interacts with terminal sessions
│   │   └── __init__.py
│   ├── text_editor.py       # File editor operations: view, create, write, and search file content
│   └── __init__.py
├── types/                    # API schema definitions using Pydantic
│   ├── browser_types.py     # Models for browser-specific actions and results
│   ├── messages.py          # Models for terminal and text editor messages and responses
│   └── __init__.py
└── __init__.py
```

## API Endpoints

The API is built with FastAPI and provides the following endpoints:

### File Endpoints

| HTTP Method | Endpoint                         | Description                                                                       |
|-------------|----------------------------------|-----------------------------------------------------------------------------------|
| POST        | `/file/upload`                   | Upload a file to S3. Returns multipart info if the file exceeds the size threshold. |
| POST        | `/file/multipart_upload`         | Upload file parts using presigned URLs for multipart uploads.                     |
| GET         | `/file`                          | Download a file from a given path.                                                |
| POST        | `/request-download-attachments`  | Batch download files from specified URLs and optionally save to a subfolder.       |

### Browser Endpoints

| HTTP Method | Endpoint            | Description                                                |
|-------------|---------------------|------------------------------------------------------------|
| GET         | `/browser/status`   | Get the current status of the browser manager.           |
| POST        | `/browser/action`   | Execute a browser action (e.g., navigation, interactions). |

### Terminal Endpoints

| HTTP Method | Endpoint                                | Description                                                                                              |
|-------------|-----------------------------------------|----------------------------------------------------------------------------------------------------------|
| WebSocket   | `/terminal`                             | Establish a terminal connection for interactive sessions (via WebSocket).                                |
| POST        | `/terminal/{terminal_id}/reset`         | Reset a specific terminal identified by `terminal_id`.                                                  |
| POST        | `/terminal/reset-all`                   | Reset all active terminals.                                                                              |
| GET         | `/terminal/{terminal_id}/view`          | View terminal history. Query parameter `full` toggles between full history and the last output only.     |
| POST        | `/terminal/{terminal_id}/kill`          | Kill the current process running in the terminal.                                                      |
| POST        | `/terminal/{terminal_id}/write`         | Write input to a terminal process (optionally sending an "enter" key).                                   |

### Other Endpoints

| HTTP Method | Endpoint          | Description                                                                     |
|-------------|-------------------|---------------------------------------------------------------------------------|
| POST        | `/text_editor`    | Execute a text editor action (e.g., open or update a file).                     |
| POST        | `/init-sandbox`   | Initialize the sandbox environment by writing provided secrets to `.secrets`.    |
| GET         | `/healthz`        | Health check endpoint to verify overall service status.                        |
| GET         | `/file`                         | Download a file from the given path.                                             |
| POST        | `/zip-file`                     | Zip a directory and save the archive to local storage.                          |

---

## WebSocket Information

| WebSocket Endpoint | Description                                                                                           | Key Features                                                                                                                                                                                                                                                                                  |
|--------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `/terminal`        | Terminal WebSocket endpoint for real-time interactive terminal sessions.                            | - **Connection Management:** Accepts new connections and maintains a continuous message loop.<br>- **Message Handling:** Validates incoming JSON messages using Pydantic and dispatches tasks based on the message type.<br>- **Task Management:** Creates asynchronous tasks for each action and cleans up on disconnect.<br>- **Command Support:** Supports terminal commands like reset, view history, kill process, and command execution (with different modes). |

## Running the Server

The entry point for the application is `start_server.py`, which is located in the repository's root folder. This script sets up the environment and starts the API server using Uvicorn.

### Command-Line Arguments

- `--port`: Port to run the server on (default: **8330**)
- `--host`: Host interface to bind to (default: **0.0.0.0**)
- `--log-level`: Logging level (choices: debug, info, warning, error, critical; default: **info**)
- `--chrome-path`: Optional path to the Chrome browser instance

### Example Usage

Run the server from the root folder:

```bash
python start_server.py --port 8330 --host 0.0.0.0 --log-level info --chrome-path /usr/bin/chrome
```

The server will then be accessible on the specified host and port.

## Usage

### Running in Docker

This application runs on Python 3.11 inside a Docker container at `/opt/.manus/.sandbox-runtime/app`. To build and run the container:

1. **Build the Docker image:**

   ```bash
   docker build -t sandbox-runtime .
   ```

2. **Run the Docker container:**

   ```bash
   docker run -p 8330:8330 sandbox-runtime
   ```

The API will then be accessible at `http://localhost:8330`.

### Local Development

Start the server with Uvicorn directly:

```bash
uvicorn app.server:app --host 0.0.0.0 --port 8330 --log-level info
```

## Development

- **Python Version**: 3.11  
- **Dependencies**: See requirements.txt
- **Local Run**: Start the server as shown above.
