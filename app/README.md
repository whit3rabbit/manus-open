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

| Endpoint                              | HTTP Method | Description                                                                                                                          |
| ------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `/file/upload_to_s3`                  | POST        | Upload a file to S3. Files larger than 10MB return multipart upload details.                                                       |
| `/file/multipart_upload_to_s3`        | POST        | Upload file parts to S3 using presigned URLs for multipart upload.                                                                   |
| `/file`                               | GET         | Download a file given its path.                                                                                                      |
| `/request-download-attachments`       | POST        | Batch download files from specified URLs to a target folder.                                                                         |
| `/browser/status`                     | GET         | Check the status of the browser automation service and view open tabs.                                                               |
| `/browser/action`                     | POST        | Execute a browser action (navigate, click, input, screenshot, etc.) based on provided parameters.                                     |
| `/text_editor`                        | POST        | Execute text editor actions (view, create, write, string replacement, find content, or find file).                                      |
| `/init-sandbox`                       | POST        | Initialize the sandbox environment by writing provided secrets to the user's `.secrets` directory.                                     |
| `/healthz`                            | GET         | Health check endpoint to verify API readiness.                                                                                       |
| `/zip-and-upload`                     | POST        | Zip a project directory (excluding certain directories like node_modules) and upload the archive to S3.                                |
| `/terminal`                           | WebSocket   | Connect to an interactive terminal session via WebSocket.                                                                            |
| `/terminal/{terminal_id}/reset`       | POST        | Reset a specific terminal session.                                                                                                   |
| `/terminal/reset-all`                 | POST        | Reset all active terminal sessions.                                                                                                  |
| `/terminal/{terminal_id}/view`        | GET         | Retrieve the command history and output from a terminal session.                                                                     |
| `/terminal/{terminal_id}/kill`        | POST        | Terminate the current process running in a terminal session.                                                                         |
| `/terminal/{terminal_id}/write`       | POST        | Write input to a terminal session (optionally simulating an Enter key press).                                                          |

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
