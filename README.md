# Manus Sandbox

A containerized sandbox environment that enables AI agents to interact with terminal environments and web browsers programmatically.

The code is reconstructed from bytecode with Claude 3.7's help:

* https://gist.github.com/jlia0/db0a9695b3ca7609c9b1a08dcbf872c9
* https://github.com/whit3rabbit/manus-open/issues/1

## Overview

Manus Sandbox (this repo) is a container-based environment that provides a secure, isolated space for AI agents (particularly LLMs like Claude) to interact with terminal environments and web browsers. It acts as a bridge between the AI system and computing resources, allowing the AI to execute real-world tasks like:

- Running terminal commands
- Automating browser actions
- Managing files and directories
- Editing text files

This sandbox creates a controlled environment where AI systems can safely perform actions without having direct access to the host system.

## Architecture

```
┌───────────────────────────┐                ┌─────────────────┐      ┌────────────────────────────────────────────┐
│                           │                │                 │      │              Sandbox Container             │
│    AI Agent (e.g. Claude) │                │  API Proxy      │      │                                            │
│                           │                │                 │      │ ┌──────────┐  ┌─────────┐  ┌────────────┐  │
│         MANUS             │  API Requests  │  - Auth check   │      │ │          │  │         │  │            │  │
│                           │◄──────────────►│  - Rate limiting├─────►│ │ Terminal │  │ Browser │  │ File/Text  │  │
│                           │  & Responses   │  - Routing      │      │ │ Service  │  │ Service │  │ Operations │  │
│                           │                │                 │      │ │          │  │         │  │            │  │
│                           │                │                 │      │ └────┬─────┘  └────┬────┘  └─────┬──────┘  │
└───────────────────────────┘                └─────────────────┘      │      │             │             │         │
                                             x-sandbox-token          │      │             │             │         │
                                             authentication           │      v             v             v         │
                                                                      │ ┌──────────────────────────────────────┐   │
                                                                      │ │               FastAPI                │   │
                                                                      │ │      (app/server.py + router.py)     │   │
                                                                      │ └──────────────────────────────────────┘   │
                                                                      │                                            │
                                                                      └────────────────────────────────────────────┘
```

## Key Components

1. **AI Agent**: The LLM (e.g., Claude) that sends API requests to the sandbox to perform tasks.

2. **API Proxy**: An intermediary service (`https://api.manus.im/apiproxy.v1.ApiProxyService/CallApi`) that:
   - Authenticates requests using the `x-sandbox-token` header
   - Routes requests to the appropriate sandbox instance
   - Handles rate limiting and access control

3. **Sandbox Container**: A Docker container that isolates the execution environment and provides:
   - FastAPI server (`app/server.py`) - The main entry point for HTTP requests
   - WebSocket server (`app/terminal_socket_server.py`) - For real-time terminal interaction
   - File and text editing capabilities (`app/tools/text_editor.py`)

4. **browser_use Library**: A modified version of the browser-use library that:
   - Provides browser automation via Playwright
   - Has been specifically adapted to work with Claude API (via `browser_use/agent/service.py`)
   - Handles browser actions, DOM interactions, and browser session management

## browser_use Integration

The browser_use library is a key component of Manus Sandbox that enables browser automation. It provides a clean API for the AI to interact with web browsers programmatically.

It is MIT licensced although the liscence was missing from the original source code.

### Key Classes and Components:

#### Agent Class (browser_use/agent/service.py)

The `Agent` class is the main entry point for browser automation. It handles:

- Initializing browser sessions
- Processing LLM outputs into actions
- Managing state history
- Handling errors and retries

```python
class Agent:
    def __init__(
        self,
        task: str,
        llm: BaseChatModel,
        browser: Browser | None = None,
        # Many other parameters...
    ):
        # Initialize all components
        
    async def run(self, max_steps: int = 100) -> AgentHistoryList:
        # Main execution loop
        # Process LLM outputs and execute actions
```

#### Browser Context (browser_use/browser/context.py)

The `BrowserContext` class manages the browser state and provides methods for interacting with web pages:

```python
class BrowserContext:
    async def navigate_to(self, url: str):
        """Navigate to a URL"""
        
    async def click_element(self, index: int):
        """Click an element using its index"""
        
    async def input_text_to_element(self, index: int, text: str, delay: float = 0):
        """Input text into an element"""
```

#### System Prompts (browser_use/agent/prompts.py)

The `SystemPrompt` class defines the instructions given to the LLM about how to interact with the browser:

```python
class SystemPrompt:
    def important_rules(self) -> str:
        """
        Returns the important rules for the agent.
        """
        rules = """
1. RESPONSE FORMAT: You must ALWAYS respond with valid JSON in this exact format:
   {
     "current_state": {
        "page_summary": "Quick detailed summary of new information from the current page which is not yet in the task history memory. Be specific with details which are important for the task. This is not on the meta level, but should be facts. If all the information is already in the task history memory, leave this empty.",
        "evaluation_previous_goal": "Success|Failed|Unknown - Analyze the current elements and the image to check if the previous goals/actions are successful like intended by the task. Ignore the action result. The website is the ground truth. Also mention if something unexpected happened like new suggestions in an input field. Shortly state why/why not",
       "memory": "Description of what has been done and what you need to remember. Be very specific. Count here ALWAYS how many times you have done something and how many remain. E.g. 0 out of 10 websites analyzed. Continue with abc and xyz",
       "next_goal": "What needs to be done with the next actions"
     },
     "action": [
       {
         "one_action_name": {
           // action-specific parameter
         }
       },
       // ... more actions in sequence
     ]
   }
        """
        # More rules follow...
        return rules
```

The prompt instructs the LLM on:

- How to format its responses (JSON structure)
- Rules for interacting with browser elements
- Navigation and error handling
- Task completion criteria
- Element interaction guidelines

#### Controller Registry (browser_use/controller/registry/service.py)

The `Registry` class provides a way to register and execute actions:

```python
class Registry:
    def action(
        self,
        description: str,
        param_model: Optional[Type[BaseModel]] = None,
    ):
        """Decorator for registering actions"""
        
    async def execute_action(
        self,
        action_name: str,
        params: dict,
        browser: Optional[BrowserContext] = None,
        # Other parameters
    ) -> Any:
        """Execute a registered action"""
```

## How AI-Sandbox Communication Works

The communication between an AI agent (like Claude) and the sandbox follows this flow:

1. **AI Agent Formulates a Request**:
   - The AI decides on an action to perform (e.g., run a terminal command, navigate a browser)
   - It constructs an appropriate API request following the sandbox API specification

2. **Request Transmission**:
   - The AI sends an HTTP request to either:
     - Directly to the sandbox container (if exposed)
     - Through an API proxy service (`https://api.manus.im/apiproxy.v1.ApiProxyService/CallApi`)

3. **Authentication**:
   - The request includes an API token (`x-sandbox-token` header)
   - The token is verified against the value stored in `$HOME/.secrets/sandbox_api_token`

4. **Request Processing**:
   - The sandbox FastAPI server receives and processes the request
   - It routes the request to the appropriate service (terminal, browser, file operations)
   - The requested action is performed within the isolated container environment

5. **Response Return**:
   - Results of the action are formatted as JSON or binary data (for file downloads)
   - The response is sent back to the AI agent

6. **Real-time Communication** (for terminal):
   - Terminal sessions use WebSockets for bidirectional, real-time communication
   - The AI can receive terminal output as it's generated and send new commands

### Example Flow: AI Running a Shell Command

```
┌─────────────┐                 ┌───────────────┐              ┌──────────────────┐
│             │ 1. HTTP Request │               │ 2. Route to  │                  │
│  AI Agent   │────────────────►│ Sandbox API   │─────────────►│ Terminal Service │
│             │                 │ (FastAPI)     │              │                  │
│             │◄────────────────│               │◄─────────────│                  │
└─────────────┘ 4. JSON Response└───────────────┘ 3. Execute   └──────────────────┘
                                                    Command
```

## API Client Usage

The sandbox includes a Python API client (`data_api.py`) that communicates with the proxy service:

```python
from data_api import ApiClient

# Initialize the client
api_client = ApiClient()

# Call a terminal command
response = api_client.call_api(
    "terminal_execute",
    body={
        "command": "ls -la",
        "terminal_id": "main"
    }
)

print(response)
```

## LLM Response Format for Browser Automation

When interacting with browser_use, the LLM (like Claude) must format its responses as JSON according to the schema defined in the system prompt:

```json
{
  "current_state": {
    "page_summary": "Found search page with 10 results for 'electric cars'",
    "evaluation_previous_goal": "Success - successfully navigated to search page and performed search as intended",
    "memory": "Completed search for 'electric cars'. Need to extract information from first 3 results (0 of 3 done)",
    "next_goal": "Extract detailed information from first search result"
  },
  "action": [
    {
      "click_element": {
        "index": 12
      }
    }
  ]
}
```

This response structure allows the Agent to:

1. Track the LLM's understanding of the current page
2. Evaluate the success of previous actions
3. Maintain memory across interactions
4. Execute the next action(s)

## Available Browser Actions

The browser_use library provides a wide range of actions for web automation:

### Navigation Actions

- `go_to_url`: Navigate to a specific URL
- `search_google`: Perform a Google search
- `go_back`: Navigate back in browser history
- `open_tab`: Open a new browser tab
- `switch_tab`: Switch between browser tabs

### Element Interaction

- `click_element`: Click on a page element by its index
- `input_text`: Type text into a form field
- `scroll_down`/`scroll_up`: Scroll the page
- `scroll_to_text`: Scroll to find specific text
- `select_dropdown_option`: Select from dropdown menus

### Content Extraction

- `extract_content`: Extract and process page content
- `get_dropdown_options`: Get all options from a dropdown

### Task Completion

- `done`: Mark the task as complete and return results

## Integration with LLM Systems

To integrate an LLM with this sandbox:

1. **API Client Implementation**: Create an API client in the LLM's execution environment

2. **Task Planning**: The LLM should break down user requests into specific API calls

3. **Sequential Operations**: Complex tasks often require multiple API calls in sequence

4. **Error Handling**: The LLM should interpret error responses and adjust its approach

5. **State Management**: For multi-step operations, the LLM needs to track the state of the environment

## Example Workflow: LLM Using the Sandbox

1. User asks the LLM to "Create a Python script that fetches weather data and save it"

2. LLM plans the steps:
   - Create a new Python file
   - Write the code to fetch weather data
   - Save the file
   - Run the script to test it
   - Show the results to the user

3. LLM executes each step by making API calls to the sandbox:
   - `POST /text_editor` with `command: "create"` to create a new file
   - `POST /text_editor` with `command: "write"` to write the code
   - `POST /terminal/{id}/write` to run the script
   - `GET /terminal/{id}` to get the output
   - Return the results to the user

## Security Considerations

1. **Multi-layered Authentication**:

   - API token authentication using the `x-sandbox-token` header (NOT IMPLEMENTED IN THIS CODE)
   - Token verification happens at the proxy layer before requests reach the FastAPI application  (NOT IMPLEMENTED IN THIS CODE)
   - Tokens are stored securely in `$HOME/.secrets/sandbox_api_token`

2. **Proxy Service Protection**:
   - The proxy service provides an additional layer of security
   - Acts as a gatekeeper for all requests to the sandbox
   - Can implement rate limiting, request validation, and access control

3. **Isolation**:
   - The Docker container provides isolation from the host system
   - Prevents the AI from affecting the host machine directly

4. **Resource Limitations**:

   - The sandbox can be configured with resource constraints (CPU, memory) at the Docker level
   - Prevents resource exhaustion attacks

5. **Action Restrictions**:

   - The API can be configured to restrict certain dangerous operations
   - Browser automation is contained within the sandbox environment

## Deployment with Docker

The sandbox is designed to run in a Docker container. The provided Dockerfile was not in the original code but gives an idea of what the container could look like:

1. A Python 3.11 environment
2. Chromium browser for web automation
3. All necessary dependencies
4. API token initialization

To build and run the container:

```bash
# Build the container
docker build -t manus-sandbox .

# Run the container
docker run -p 8330:8330 manus-sandbox
```

## Acknowledgements

This project is reconstructed from bytecode with Claude 3.7's help, and it demonstrates the advanced capabilities of container-based AI sandboxes. The browser_use component is a modified version of the open-source [browser-use](https://github.com/browser-use/browser-use) library.
