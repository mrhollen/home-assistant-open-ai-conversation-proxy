import json
import copy
import uuid
import time

def format_sse(event_type: str, data_dict: dict) -> str:
    """Formats data into an SSE message string."""
    json_data = json.dumps(data_dict)
    return f"event: {event_type}\ndata: {json_data}\n\n"

def get_structured_usage(raw_usage_data: dict = None) -> dict:
    """Creates the structured usage block."""
    if not raw_usage_data: raw_usage_data = {}
    return {
        "input_tokens": raw_usage_data.get("prompt_tokens", raw_usage_data.get("input_tokens", 0)),
        "input_tokens_details": { "cached_tokens": None }, # Mimic structure
        "output_tokens": raw_usage_data.get("completion_tokens", raw_usage_data.get("output_tokens", 0)),
        "output_tokens_details": { "reasoning_tokens": None }, # Mimic structure
        "total_tokens": raw_usage_data.get("total_tokens", 0)
    }

def build_base_response_structure(incoming_data: dict, response_id: str, created_at: int, config: dict) -> dict:
    """
    Builds the common static structure of a response, used for multiple
    events in the fake stream. Ensures optional fields are present even if null.
    """
    max_tokens = incoming_data.get('max_output_tokens',
                                   incoming_data.get('max_tokens', config.get('default_max_tokens')))
    original_tools = incoming_data.get('tools')

    base_response = {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "error": None,
        "incomplete_details": None,
        "model": incoming_data.get('model', config.get('default_model')),
        "output": [],
        "reasoning": {"effort": None, "summary": None},
        # "service_tier": "default", # Set dynamically per event
        "text": {"format": {"type": "text"}},
        "truncation": "disabled",
        "instructions": incoming_data.get('instructions'), # Keep even if None
        "max_output_tokens": max_tokens,
        "parallel_tool_calls": incoming_data.get('parallel_tool_calls', True),
        "previous_response_id": incoming_data.get('previous_response_id'), # Keep even if None
        "store": incoming_data.get('store', False),
        "temperature": incoming_data.get('temperature', config.get('default_temperature')),
        "tool_choice": incoming_data.get('tool_choice', 'auto'),
        "tools": original_tools, # Use original tools format here
        "top_p": incoming_data.get('top_p', config.get('default_top_p')),
        "user": incoming_data.get('user'), # Keep even if None
        "metadata": incoming_data.get('metadata', {}) # Ensure metadata exists
    }

    if "metadata" not in base_response:
         base_response["metadata"] = {} # Should be redundant due to get default
    return base_response

def create_sse_event_created(base_response: dict) -> dict:
    """Creates the data payload for the 'response.created' SSE event."""
    created_data = copy.deepcopy(base_response)
    created_data["status"] = "in_progress"
    created_data["usage"] = None
    created_data["service_tier"] = "auto"
    return {"type": "response.created", "response": created_data}

def create_sse_event_item_added_tool(tool_details: dict, output_index: int) -> dict:
    """Creates the data payload for 'response.output_item.added' (tool call)."""
    return {
        "type": "response.output_item.added", "output_index": output_index,
        "item": {
            "id": tool_details["item_id"], "type": "function_call",
            "status": "in_progress", "arguments": "",
            "call_id": tool_details["call_id"], "name": tool_details["name"]
        }
    }

def create_sse_event_item_added_text(item_id: str, role: str, output_index: int) -> dict:
    """Creates the data payload for 'response.output_item.added' (text message)."""
    return {
        "type": "response.output_item.added", "output_index": output_index,
        "item": {
            "id": item_id, "type": "message", "status": "in_progress",
            "content": [], "role": role
        }
    }

def create_sse_event_func_args_delta(tool_details: dict, output_index: int) -> dict:
     """Creates the data payload for 'response.function_call_arguments.delta'."""
     return {
         "type": "response.function_call_arguments.delta",
         "item_id": tool_details["item_id"], "output_index": output_index,
         "delta": tool_details["arguments"]
     }

def create_sse_event_func_args_done(tool_details: dict, output_index: int) -> dict:
    """Creates the data payload for 'response.function_call_arguments.done'."""
    return {
        "type": "response.function_call_arguments.done",
        "item_id": tool_details["item_id"], "output_index": output_index,
        "arguments": tool_details["arguments"]
    }

def create_sse_event_content_part_added(item_id: str, output_index: int, content_index: int) -> dict:
    """Creates the data payload for 'response.content_part.added'."""
    return {
        "type": "response.content_part.added", "item_id": item_id,
        "output_index": output_index, "content_index": content_index,
        "part": {"type": "output_text", "annotations": [], "text": ""}
    }

def create_sse_event_text_delta(item_id: str, text_delta: str, output_index: int, content_index: int) -> dict:
    """Creates the data payload for 'response.output_text.delta'."""
    return {
        "type": "response.output_text.delta", "item_id": item_id,
        "output_index": output_index, "content_index": content_index,
        "delta": text_delta
    }

def create_sse_event_text_done(item_id: str, full_text: str, output_index: int, content_index: int) -> dict:
    """Creates the data payload for 'response.output_text.done'."""
    return {
        "type": "response.output_text.done", "item_id": item_id,
        "output_index": output_index, "content_index": content_index,
        "text": full_text
    }

def create_sse_event_content_part_done(item_id: str, final_part: dict, output_index: int, content_index: int) -> dict:
    """Creates the data payload for 'response.content_part.done'."""
    return {
        "type": "response.content_part.done", "item_id": item_id,
        "output_index": output_index, "content_index": content_index,
        "part": final_part
    }

def create_sse_event_item_done(final_item: dict, output_index: int) -> dict:
    """Creates the data payload for 'response.output_item.done'."""
    return {
        "type": "response.output_item.done", "output_index": output_index,
        "item": final_item
    }

def create_sse_event_completed(base_response: dict, usage_data: dict, final_output_items: list) -> dict:
    """Creates the data payload for the final 'response.completed' SSE event."""
    completed_data = copy.deepcopy(base_response)
    completed_data["status"] = "completed"
    completed_data["usage"] = get_structured_usage(usage_data)
    completed_data["output"] = final_output_items
    completed_data["service_tier"] = "default"
    return {"type": "response.completed", "response": completed_data}