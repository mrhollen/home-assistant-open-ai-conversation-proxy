# ⚠️ This repository is now unmaintained

# Home Assistant OpenAI Conversation Proxy for Local LLMs

* [Overview](#overview)
* [Features](#features)
* [Data Flow Diagram](#data-flow-diagram)
* [Prerequisites](#prerequisites)
* [Setup & Running](#setup--running)
    * [Running with Docker Compose (Recommended)](#running-with-docker-compose-recommended)
    * [Running with Dockerfile (Manual Docker Commands)](#running-with-dockerfile-manual-docker-commands)
    * [Running Manually (Without Docker)](#running-manually-without-docker)
* [Home Assistant Configuration](#home-assistant-configuration)
* [Troubleshooting](#troubleshooting)
* [License](#license)

## Overview

This Python project aims to create a proxy server to bridge the gap between Home Assistant's OpenAI Conversation integration and local Large Language Models (LLMs) that expose an OpenAI-compatible API endpoint (like a Llama.cpp server).

The primary goal is to enable tool usage (function calling) with local LLMs via Home Assistant, even if the local LLM server doesn't fully support the standard OpenAI streaming protocol (Server-Sent Events - SSE) required by the Home Assistant integration when tools are involved. This is not needed if you are using Ollama. OpenAI Conversation natively supports Ollama.

## Features

* **Receives Requests:** Listens for requests from Home Assistant on an endpoint mimicking the OpenAI `/responses` API structure.
* **Forwards Requests:** Reformats the request (including tool definitions) and forwards it to your local LLM's `/v1/chat/completions` endpoint. At the moment the proxy disables streaming for all requests. See Fakes SSE below for the reason why.
* **Handles Responses:** Receives the complete response (text or tool call) from the local LLM.
* **Fakes SSE Stream:** Sends the response back to Home Assistant using a sequence of Server-Sent Events (SSE) that mimics the real OpenAI API stream, allowing Home Assistant's parser to correctly handle both text responses and tool calls. (This is required by Llama.cpp, but may not be needed for long. There is a [PR open](https://github.com/ggml-org/llama.cpp/pull/12379) to allow streaming by llama.cpp during function use.)
* **Dockerized:** Includes `Dockerfile` and `docker-compose.yml` for easy deployment as a background service.

## Data Flow Diagram

This diagram shows how requests flow from Home Assistant, through the proxy, to your local LLM, and back:

```text
+--------------------------+
|   Home Assistant User    |
+--------------------------+
            |
            v (Input/Tools)
+--------------------------+
| HA OpenAI Integration    |
+--------------------------+
            |
            | 1. POST to Proxy URL
            |    (e.g., http://proxy:5000/api/v1)
            |
            v
+--------------------------+
|      Proxy Server        |
|  (Receives @ /responses) |
|  (Formats Tools,         |
|   stream=false)          |
+--------------------------+
            |
            | 2. POST to LLM URL
            |    (e.g., http://llm:8000/v1/chat/completions)
            |
            v
+--------------------------+
|    Local LLM Server      |
|   (Processes Request)    |
+--------------------------+
            |
            | 3. Full JSON Response
            |    (Text or Tool Call)
            |
            v
+--------------------------+
|      Proxy Server        |
|  (Receives Full JSON)    |
|  (Generates Fake SSE)    |
+--------------------------+
            |
            | 4. Fake SSE Stream Response
            |    (Back to Home Assistant)
            |
            v
+--------------------------+
| HA OpenAI Integration    |
|   (Parses SSE)           |
+--------------------------+
            |
            v (Display Text / Execute Tool)
+--------------------------+
|   Home Assistant Action  |
+--------------------------+
```

## Prerequisites

* **Python:** Python 3.9 or higher recommended.
* **Pip:** Python package installer.
* **Local LLM Server:** A running instance of an LLM server (e.g., Llama.cpp) configured with:
    * An OpenAI-compatible API endpoint (specifically `/v1/chat/completions`).
    * Tool/function calling support enabled for the loaded model.
    * Network accessibility from the machine running this proxy.
* **(Optional) Docker & Docker Compose:** Required if using the Docker setup.

## Setup & Running

You can run this proxy either using Docker (recommended for background service) or manually with Python.

### Running with Docker Compose (Recommended)

1.  **Get the Files:** Clone this repository or download the following files into a single directory:
    * `proxy.py` (The Python script itself)
    * `Dockerfile`
    * `docker-compose.yml`
    * `requirements.txt`
2.  **Configure:** The proxy needs to know the URL of your local LLM server. This is configured via an environment variable:
    * **`local_chat_completions_url`**: (Required) The full URL to your LLM's chat completions endpoint.
        * *Default (Docker Desktop - Mac/Win):* `http://host.docker.internal/v1/chat/completions` (adjust port if needed).
        * *Linux Host:* You might need to replace `host.docker.internal` with your host's IP address on the Docker network (e.g., `http://172.17.0.1/v1/chat/completions`). Check with `ip addr show docker0` or similar.
    * **`proxy_port`**: (Required) The port the proxy listens on. This must match the port mapping in `docker-compose.yml` or your `docker run` command.

    You can set these by:
    * Creating a `config.json` file in the same directory as `docker-compose.yml` (recommended):
        ```json
        {
            "local_chat_completions_url": "http://localhost/v1/chat/completions",
            "default_model": "gpt-3.5-turbo",
            "default_max_tokens": 1024,
            "default_temperature": 0.7,
            "default_top_p": 1.0,
            "proxy_port": 5000,
            "sse_delay": 0.02,
            "downstream_timeout": 90
        }
        ```
3.  **Run:**
    * Open a terminal in the directory containing the files.
    * Build and run the container in detached mode:
        ```bash
        docker-compose up -d --build
        ```
4.  **Check Logs (Optional):**
    ```bash
    docker-compose logs -f
    ```
    (Press `Ctrl+C` to stop viewing logs).
5.  **Stopping:**
    ```bash
    docker-compose down
    ```

### Running with Dockerfile (Manual Docker Commands)

If you prefer not to use Docker Compose, you can build and run the container directly.

1.  **Get the Files:** Ensure you have all the necessary Python files (`server.py`, `proxy_handler.py`, etc.), `config.json`, `requirements.txt`, and `Dockerfile` in a single directory.
2.  **Configure `config.json`:** Edit `config.json` in the directory. Pay attention to:
    * `local_chat_completions_url`: Set the correct URL for your downstream LLM API.
    * `proxy_port`: Set the port the proxy should listen on *inside* the container (e.g., `5000`). This port number will be used in the `docker run` command.
3.  **Build the Image:**
    * Open a terminal in the directory containing the `Dockerfile`.
    * Run the build command. Replace `my-ha-proxy-image` with a tag name you prefer:
        ```bash
        docker build -t my-ha-proxy-image .
        ```
4.  **Run the Container:**
    * Execute the `docker run` command. You need to:
        * Publish the port specified by `proxy_port` in your `config.json` (e.g., map host port `5000` to container port `5000`).
        * Mount your `config.json` file as a volume into the container at `/app/config.json`.
        * Run in detached mode (`-d`) so it runs in the background.
        * Use `--rm` to automatically remove the container when it stops (optional but good for testing).
        * Specify the image name you built.

        ```bash
        # Make sure config.json is in your current directory (.)
        # Replace 5000:5000 if you use a different host:container port mapping
        # Ensure the container port (second 5000) matches config.json's proxy_port
        docker run -d --rm \
          -p 5000:5000 \
          -v "$(pwd)/config.json:/app/config.json:ro" \
          --name ha-openai-proxy-manual \
          my-ha-proxy-image
        ```
        *(Note: `$(pwd)` works on Linux/macOS to get the current directory for the volume mount. On Windows PowerShell, use `${PWD}`. On Windows CMD, you might need to use the full path explicitly like `-v C:\path\to\your\config.json:/app/config.json:ro`)*
5.  **Check Logs:**
    ```bash
    docker logs -f ha-openai-proxy-manual
    ```
    (Press `Ctrl+C` to stop viewing logs).
6.  **Stopping:**
    ```bash
    docker stop ha-openai-proxy-manual
    ```
    *(The container will be removed automatically if you used `--rm`)*. If you didn't use `--rm`, you might also need `docker rm ha-openai-proxy-manual`.

### Running Manually (Without Docker)

1.  **Get the Files:** Download `proxy.py` and `requirements.txt` to a directory on the machine where you want to run the proxy.
2.  **Open a Terminal:** Navigate to the directory where you saved the files.
3.  **Create Virtual Environment (Recommended):**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # Linux/macOS
    # OR
    .\.venv\Scripts\activate  # Windows
    ```
4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
5.  **Set config.json:** You need to set `local_chat_completions_url` and `proxy_port` a long with other configuration variables in the `config.json` file the same as above:
    * Create a `config.json` file in the project root:
        ```json
        {
            "local_chat_completions_url": "http://localhost/v1/chat/completions",
            "default_model": "gpt-3.5-turbo",
            "default_max_tokens": 1024,
            "default_temperature": 0.7,
            "default_top_p": 1.0,
            "proxy_port": 5000,
            "sse_delay": 0.02,
            "downstream_timeout": 90
        }
        ```
6.  **Run the Script:**
    ```bash
    python server.py
    ```
    The proxy will start listening on the specified port (default 5000). Press `Ctrl+C` to stop it.

## Home Assistant Configuration

1.  **Go to Settings > Devices & Services > Add Integration.**
2.  **Search for and select "OpenAI Conversation".**
3.  **API Key:** Enter anything (e.g., "dummy_key") - it won't be used as the request goes to your local proxy.
4.  **API Proxy URL:** <span style="color:red;">THIS IS IMPORTANT!!!</span>
    * You must override the plugin's OpenAI URL by using an environment variable called `OPENAI_BASE_URL`. It must end with `/api/v1` inorder to send the proper data to the proxy. If you do not do this the proxy will never be sent data and you will not see anthing in the proxy logs.
    * Example: `OPENAI_BASE_URL=http://localhost:5000/api/v1`
5.  **Configure Model, Prompt, etc.:** Set up the rest of the OpenAI Conversation integration options as desired (model name should ideally match what your local LLM expects, though the proxy uses the `default_model` if not specified).

**(You might need to add more specific details here based on exactly how you configured HA to use the proxy)**

## Troubleshooting

* **`intent-failed` in Home Assistant:**
    * Check the proxy logs (either `docker-compose logs -f` or the terminal output if running manually) for errors connecting to the `local_chat_completions_url` or processing the response.
    * Check the logs of your local LLM server (e.g., Llama.cpp) for errors during request processing.
* **Connection Refused (Proxy to LLM):** Ensure the `local_chat_completions_url` is correct and accessible from the proxy (either the container or the manual host). Check host IP vs. `host.docker.internal` if using Docker. Ensure the LLM server is running and accessible on the network.
* **Connection Refused (HA to Proxy):** Ensure the IP address and port used in the Home Assistant configuration are correct for the proxy. Check firewalls on the machine running the proxy.
* **Port Conflicts:** Make sure port `5000` (or your `proxy_port`) is not already in use on the machine running the proxy.

## License

Apache 2.0

