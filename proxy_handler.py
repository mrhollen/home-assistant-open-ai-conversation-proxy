from http.server import BaseHTTPRequestHandler
import json
import requests
import uuid
import time
import traceback

# Import components
import config_loader as config
import request_transformer
import response_transformer
from response_transformer import ResponseProcessingError # Import custom exception

class ProxyHandler(BaseHTTPRequestHandler):
    """
    Handles incoming HTTP requests, proxies them to a local chat completions API,
    and transforms responses into a fake SSE stream matching OpenAI format.
    """
    # Flag to track if headers have been sent (especially for SSE)
    _headers_sent = False

    def do_POST(self):
        """Handles POST requests to the '/api/v1/responses' endpoint."""
        self._headers_sent = False # Reset flag for each request
        cfg = config.get_config()
        downstream_url = cfg['local_chat_completions_url']
        timeout = cfg['downstream_timeout']
        response = None # To store downstream response obj
        incoming_data = {} # To store parsed incoming request

        if self.path == '/api/v1/responses':
            try:
                # 1. Read and Validate Incoming Request
                incoming_data = request_transformer.read_request_body(self)
                print(f"Received Incoming Request: {json.dumps(incoming_data, indent=2)}")
                request_transformer.validate_request_data(incoming_data) # Raises ValueError on failure

                # 2. Transform Request for Downstream API
                downstream_payload = request_transformer.build_downstream_payload(incoming_data)
                print(f"Forwarding request to: {downstream_url}")
                print(f"Payload being sent: {json.dumps(downstream_payload, indent=2)}")

                # 3. Forward Request to Downstream API
                response = requests.post(
                    downstream_url, json=downstream_payload,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    timeout=timeout
                )
                print(f"Received status code {response.status_code} from {downstream_url}")
                response.raise_for_status() # Raises HTTPError for bad status codes (4xx or 5xx)

                # 4. Parse Downstream Response
                backend_response_json = response.json() # Raises JSONDecodeError on failure
                print(f"Received Chat Completion Response: {json.dumps(backend_response_json, indent=2)}")
                parsed_backend_data = response_transformer.parse_downstream_response(backend_response_json) # Raises ResponseProcessingError

                # 5. Generate and Send Fake SSE Stream
                # This function now handles sending headers and all SSE events.
                response_transformer.generate_sse_stream(self, incoming_data, parsed_backend_data)

            except Exception as e:
                # --- Centralized Error Handling ---
                print(f"Error during request processing: {e}")
                traceback.print_exc()

                # If headers haven't been sent, we can send a proper JSON error response.
                # Otherwise (SSE started), we can't change the status code or content type.
                if not self._headers_sent:
                    status_code = 500
                    error_type = "internal_server_error"
                    error_message = f"An internal server error occurred: {str(e)}"

                    # Refine error details based on exception type
                    if isinstance(e, ValueError): # Covers JSON errors from read_request_body, validation errors
                         status_code=400; error_type="invalid_request_error"; error_message=str(e)
                    elif isinstance(e, requests.exceptions.ConnectionError):
                         status_code=503; error_type="connection_error"; error_message=f"Failed to connect to downstream API at {downstream_url}: {e}"
                    elif isinstance(e, requests.exceptions.Timeout):
                         status_code=504; error_type="timeout_error"; error_message=f"Downstream API at {downstream_url} timed out after {timeout}s: {e}"
                    elif isinstance(e, requests.exceptions.HTTPError):
                         # Error response from the downstream service
                         status_code = response.status_code if response else 502 # 502 Bad Gateway if response obj missing
                         error_type = "downstream_api_error"
                         try:
                              # Try to relay error details from downstream if JSON
                              err_details = response.json()
                              error_message = f"Downstream API error (HTTP {status_code}): {err_details}"
                         except (json.JSONDecodeError, AttributeError):
                              # Fallback if downstream error isn't JSON or response is None
                              error_message = f"Downstream API error (HTTP {status_code}): {response.text if response else str(e)}"
                    elif isinstance(e, requests.exceptions.RequestException):
                         # Other requests-related errors
                         status_code=502; error_type="downstream_request_error"; error_message=f"Error during request to downstream API: {e}"
                    elif isinstance(e, json.JSONDecodeError): # Should primarily catch errors parsing downstream response
                        status_code=502; error_type="invalid_downstream_response"; error_message=f"Invalid JSON received from downstream: {getattr(response, 'text', 'N/A')[:200]}..."
                    elif isinstance(e, ResponseProcessingError): # Custom error for bad structure downstream
                        status_code=502; error_type="invalid_downstream_structure"; error_message=str(e)
                    # Keep generic 500 for unexpected errors

                    # Attempt to build and send the structured error response
                    self._send_error_response(status_code, error_type, error_message, incoming_data)
                else:
                    # Headers already sent (SSE started). Cannot send a normal error response.
                    print("Error occurred after SSE stream started. Client connection may be closed or stream corrupted.")
                    # Attempt to close the connection gracefully if possible.
                    # self.finish() # This might interfere with BaseHTTPRequestHandler internals

        else:
            print(f"Error: Received request for unknown path: {self.path}")
            self._send_error_response(404, "not_found", f"Endpoint {self.path} not found.", {})


    def _send_error_response(self, status_code: int, error_type: str, error_message: str, incoming_data: dict):
        """Sends a structured JSON error response if headers haven't been sent."""
        if self._headers_sent:
            print("Attempted to send error response after headers were already sent. Ignoring.")
            return

        try:
            cfg = config.get_config()
            safe_incoming = incoming_data if isinstance(incoming_data, dict) else {}
            error_payload = {
                "id": f"resp_{uuid.uuid4().hex}",
                "object": "response",
                "created_at": int(time.time()),
                "status": "error",
                "error": {"type": error_type, "message": error_message},
                "model": safe_incoming.get('model', cfg.get('default_model')),
                # Include other relevant fields from base structure if desired, keeping them minimal
            }
            self.send_response(status_code)
            self.send_header('Content-type', 'application/json')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self._headers_sent = True
            self.wfile.write(json.dumps(error_payload).encode('utf-8'))
            self.wfile.flush()
        except Exception as send_err:
            # Log if sending the error response itself fails
            print(f"FATAL: Could not send error response (Status: {status_code}). Error: {send_err}")
            # Ensure headers_sent reflects reality if end_headers() failed
            # (Difficult to know for sure, but assume failure means not sent)
            self._headers_sent = False

    # Suppress default http.server log messages for cleaner output
    def log_message(self, format, *args):
        """Overrides default logging to keep stdout cleaner."""
        # Optionally log to a file here if needed
        # import sys
        # print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args), file=sys.stderr)
        return