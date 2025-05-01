import json
import uuid
import time
import copy
import sse_utils
import config_loader as config

class ResponseProcessingError(Exception):
    """Custom exception for errors during response processing."""
    pass

def parse_downstream_response(response_json: dict) -> dict:
    """
    Parses the downstream chat completions response and extracts key information.
    Returns a dictionary containing:
        - message (dict): The assistant's message object.
        - is_tool_call (bool): Whether the response indicates a tool call.
        - backend_model (str): The model used by the backend.
        - backend_usage (dict | None): Usage statistics from the backend.
    Raises ResponseProcessingError if the response structure is invalid.
    """
    if not response_json.get('choices') or len(response_json['choices']) == 0:
        raise ResponseProcessingError("Invalid response structure from downstream server (no choices)")

    first_choice = response_json['choices'][0]
    message = first_choice.get('message', {})
    if not message:
         raise ResponseProcessingError("Invalid response structure from downstream server (no message in choice)")

    finish_reason = first_choice.get('finish_reason')
    is_tool_call = (finish_reason == 'tool_calls' and
                    'tool_calls' in message and
                    isinstance(message['tool_calls'], list) and
                    len(message['tool_calls']) > 0)

    # Validate tool call structure if present
    if is_tool_call:
        valid_calls_found = False
        for tc in message['tool_calls']:
            if isinstance(tc, dict) and tc.get('type') == 'function' and 'function' in tc \
               and isinstance(tc['function'], dict) and 'name' in tc['function'] \
               and 'arguments' in tc['function']:
                 valid_calls_found = True
                 # Ensure arguments are strings if possible
                 if isinstance(tc['function']['arguments'], dict):
                     try:
                         tc['function']['arguments'] = json.dumps(tc['function']['arguments'])
                     except TypeError:
                          print(f"Warning: Could not JSON serialize tool arguments: {tc['function']['arguments']}")
                          tc['function']['arguments'] = str(tc['function']['arguments']) # Fallback
                 elif not isinstance(tc['function']['arguments'], str):
                      tc['function']['arguments'] = str(tc['function']['arguments']) # Fallback
                 # Ensure ID exists
                 if 'id' not in tc or not tc['id']:
                    tc['id'] = f"call_{uuid.uuid4().hex}"

            else:
                print(f"Warning: Invalid tool call structure found and ignored: {tc}")
        if not valid_calls_found:
             raise ResponseProcessingError("Response indicated tool_calls but contained no valid function calls.")


    # Validate text content if not a tool call
    elif not is_tool_call and message.get('content') is None:
         # Allow empty string content, but not missing 'content' key entirely
         message['content'] = "" # Default to empty string if finish reason isn't tool_call
         print("Warning: Non-tool-call response message missing 'content', defaulting to empty string.")
         # raise ResponseProcessingError("Invalid response: Non-tool-call message missing 'content'.")


    backend_model = response_json.get('model', 'unknown_backend_model') # Use a default if missing
    backend_usage = response_json.get('usage') # Can be None

    return {
        "message": message,
        "is_tool_call": is_tool_call,
        "backend_model": backend_model,
        "backend_usage": backend_usage,
    }


def send_sse_event(handler, event_name: str, data: dict, delay: float):
    """Formats, encodes, sends an SSE event, and sleeps."""
    sse_msg = sse_utils.format_sse(event_name, data)
    print(f"Sending Fake SSE Chunk ({event_name}): {sse_msg.strip()}")
    try:
        handler.wfile.write(sse_msg.encode('utf-8'))
        handler.wfile.flush()
        time.sleep(delay)
    except BrokenPipeError:
        print("Client disconnected during SSE stream.")
        raise # Re-raise to stop further processing
    except Exception as e:
        print(f"Error writing SSE chunk ({event_name}): {e}")
        raise # Re-raise to stop further processing


def generate_sse_stream(handler, incoming_data: dict, parsed_backend_data: dict):
    """Generates and sends the fake SSE stream based on the backend response."""
    cfg = config.get_config()
    sse_delay = cfg['sse_delay']
    message = parsed_backend_data['message']
    is_tool_call = parsed_backend_data['is_tool_call']
    backend_model = parsed_backend_data['backend_model']
    backend_usage = parsed_backend_data['backend_usage']

    # --- Prepare Common Data ---
    response_id = f"resp_{uuid.uuid4().hex}"
    created_at = int(time.time())

    base_resp_struct = sse_utils.build_base_response_structure(
        incoming_data, response_id, created_at, cfg
    )
    base_resp_struct["model"] = backend_model # Use model reported by backend

    # --- Send Headers ---
    # Headers must be sent *before* any body content (SSE events)
    handler.send_response(200)
    handler.send_header('Content-type', 'text/event-stream')
    handler.send_header('Cache-Control', 'no-cache')
    handler.end_headers()
    handler._headers_sent = True # Mark headers as sent in the handler

    final_output_items = [] # Store the final structure for the 'completed' event output

    try:
        # --- Send Initial Event ---
        created_event_data = sse_utils.create_sse_event_created(base_resp_struct)
        send_sse_event(handler, "response.created", created_event_data, sse_delay)

        # --- Send Intermediate Events (Specific to Type) ---
        if is_tool_call:
            print("Processing Tool Call SSE events.")
            processed_tool_calls = []
            for index, tool_call in enumerate(message.get('tool_calls', [])):
                 # Basic validation already done in parse_downstream_response
                 function_info = tool_call.get('function', {})
                 call_id = tool_call.get('id') # Should exist now
                 func_name = function_info.get('name')
                 func_args_str = function_info.get('arguments', "") # Should be string now

                 if func_name is None: continue # Skip if name somehow missing

                 output_item_id = f"fc_{uuid.uuid4().hex}" # Unique ID for this output item
                 final_output_item = { # Structure for final 'completed' event
                     "id": output_item_id, "type": "function_call",
                     "status": "completed", "arguments": func_args_str,
                     "call_id": call_id, "name": func_name
                 }
                 final_output_items.append(final_output_item)

                 tool_details = {
                     "item_id": output_item_id, "call_id": call_id,
                     "name": func_name, "arguments": func_args_str
                 }
                 processed_tool_calls.append(tool_details)

                 # --- Send Tool Call Intermediate Events (per tool) ---
                 # 2. 'response.output_item.added'
                 item_added_data = sse_utils.create_sse_event_item_added_tool(tool_details, index)
                 send_sse_event(handler, "response.output_item.added", item_added_data, sse_delay)

                 # 3. 'response.function_call_arguments.delta' (send all args as one delta)
                 delta_data = sse_utils.create_sse_event_func_args_delta(tool_details, index)
                 send_sse_event(handler, "response.function_call_arguments.delta", delta_data, sse_delay)

                 # 4. 'response.function_call_arguments.done'
                 args_done_data = sse_utils.create_sse_event_func_args_done(tool_details, index)
                 send_sse_event(handler, "response.function_call_arguments.done", args_done_data, sse_delay)

                 # 5. 'response.output_item.done'
                 item_done_data = sse_utils.create_sse_event_item_done(final_output_item, index)
                 send_sse_event(handler, "response.output_item.done", item_done_data, sse_delay)

        else: # --- Text Message Events ---
            print("Processing Text Message SSE events.")
            assistant_content = message.get('content', '') # Already defaulted if needed
            assistant_role = message.get('role', 'assistant')
            output_item_id = f"msg_{uuid.uuid4().hex}"
            output_index = 0 # Only one text message output item
            content_index = 0 # Only one content part (output_text)

            # Final output item structure
            final_content_part = {
                 "type": "output_text", "annotations": [], "text": assistant_content
            }
            final_output_item = {
                "id": output_item_id, "type": "message", "status": "completed",
                "content": [final_content_part],
                "role": assistant_role
            }
            final_output_items.append(final_output_item)

            # --- Send Text Intermediate Events ---
            # 2. 'response.output_item.added'
            item_added_data = sse_utils.create_sse_event_item_added_text(output_item_id, assistant_role, output_index)
            send_sse_event(handler, "response.output_item.added", item_added_data, sse_delay)

            # 3. 'response.content_part.added'
            content_added_data = sse_utils.create_sse_event_content_part_added(output_item_id, output_index, content_index)
            send_sse_event(handler, "response.content_part.added", content_added_data, sse_delay)

            # 4. 'response.output_text.delta' (send full content as one delta)
            delta_data = sse_utils.create_sse_event_text_delta(output_item_id, assistant_content, output_index, content_index)
            send_sse_event(handler, "response.output_text.delta", delta_data, sse_delay)

            # 5. 'response.output_text.done'
            text_done_data = sse_utils.create_sse_event_text_done(output_item_id, assistant_content, output_index, content_index)
            send_sse_event(handler, "response.output_text.done", text_done_data, sse_delay)

            # 6. 'response.content_part.done'
            content_done_data = sse_utils.create_sse_event_content_part_done(output_item_id, final_content_part, output_index, content_index)
            send_sse_event(handler, "response.content_part.done", content_done_data, sse_delay)

            # 7. 'response.output_item.done'
            item_done_data = sse_utils.create_sse_event_item_done(final_output_item, output_index)
            send_sse_event(handler, "response.output_item.done", item_done_data, sse_delay)


        # --- Send Final Event ---
        completed_event_data = sse_utils.create_sse_event_completed(
            base_resp_struct, backend_usage, final_output_items
        )
        # Send final event without delay
        sse_msg_final = sse_utils.format_sse("response.completed", completed_event_data)
        print(f"Sending Fake SSE Chunk (response.completed): {sse_msg_final.strip()}")
        handler.wfile.write(sse_msg_final.encode('utf-8'))
        handler.wfile.flush()

        print("Enhanced Fake SSE stream finished.")

    except BrokenPipeError:
        # Already logged in send_sse_event, just stop processing
        return
    except Exception as e:
        # Catch any other exceptions during SSE generation
        print(f"FATAL: Error during SSE stream generation after headers sent: {e}")
        # Cannot send a standard error response here. The stream might be corrupted.
        # Best effort is to just stop. Client will likely timeout or see a broken stream.
        import traceback
        traceback.print_exc()