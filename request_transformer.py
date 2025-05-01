import json
import copy
import config_loader as config

def read_request_body(handler) -> dict:
    """Reads and parses the JSON request body from the HTTP handler."""
    content_length = int(handler.headers.get('Content-Length', 0))
    if content_length == 0:
        raise ValueError("Request body is empty")
    body = handler.rfile.read(content_length)
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in request body: {e}")

def validate_request_data(data: dict):
    """Validates the essential parts of the incoming request data."""
    if not data.get('input'):
        raise ValueError("Missing 'input' in request body")
    # Basic type check for input
    if not isinstance(data['input'], (str, list, dict)): # Allow richer inputs conceptually
         print(f"Warning: 'input' type is {type(data['input'])}, expected str primarily. Attempting to cast.")
         data['input'] = str(data['input']) # Ensure it's at least a string for basic case


def format_tools_for_openai(tools_list) -> list | None:
    """Reformats the tool list to the standard OpenAI structure."""
    if not isinstance(tools_list, list): return None
    formatted_tools = []
    for tool in tools_list:
        if isinstance(tool, dict) and tool.get('type') == 'function':
            # Case 1: Already in OpenAI format (nested function dict)
            if 'function' in tool and isinstance(tool['function'], dict):
                formatted_tools.append(copy.deepcopy(tool))
            # Case 2: Flattened structure (name, parameters, description at top level)
            elif 'name' in tool and 'parameters' in tool:
                 formatted_tool = {
                     "type": "function",
                     "function": {
                         "name": tool.get('name'),
                         "description": tool.get('description'),
                         "parameters": tool.get('parameters')
                     }
                 }
                 # Clean up None values within the function dict
                 formatted_tool['function'] = {k: v for k, v in formatted_tool['function'].items() if v is not None}
                 formatted_tools.append(formatted_tool)
            else:
                 print(f"Warning: Skipping tool with unexpected 'function' structure: {tool}")
        else:
            print(f"Warning: Skipping non-function tool or invalid tool format: {tool}")
    return formatted_tools if formatted_tools else None


def build_downstream_payload(incoming_data: dict) -> dict:
    """Builds the JSON payload for the downstream chat completions API."""
    cfg = config.get_config()
    input_content = incoming_data.get('input', '') # Already validated
    # Ensure input_content is a string for the message
    if not isinstance(input_content, str):
        input_content = str(input_content)

    model = incoming_data.get('model', cfg['default_model'])
    messages = [{"role": "user", "content": input_content}] # Simple user message
    original_tools = incoming_data.get('tools')
    formatted_tools = format_tools_for_openai(original_tools)

    chat_payload = {
        "model": model,
        "messages": messages,
        "max_tokens": incoming_data.get('max_output_tokens',
                                        incoming_data.get('max_tokens', cfg['default_max_tokens'])),
        "temperature": incoming_data.get('temperature', cfg['default_temperature']),
        "top_p": incoming_data.get('top_p', cfg['default_top_p']),
        "n": incoming_data.get('n'), # Pass through if present
        "stream": False, # CRITICAL: Always request non-streaming from backend
        "tools": formatted_tools,
        "tool_choice": incoming_data.get('tool_choice', 'auto'),
        # "stop": incoming_data.get('stop'), # Add stop sequences if needed
        # Add other potential OpenAI params if necessary (e.g., presence_penalty)
    }

    # Remove keys with None values before sending
    chat_payload_final = {k: v for k, v in chat_payload.items() if v is not None}

    # Handle 'stop' sequences specifically if they exist
    if 'stop' in incoming_data and incoming_data['stop'] is not None:
        chat_payload_final['stop'] = incoming_data['stop']

    return chat_payload_final