from http.server import HTTPServer
import sys

# Import necessary components
try:
    import config_loader as config # Loads config on import
    from proxy_handler import ProxyHandler
    import requests # Check dependency early
except ImportError as e:
     print(f"Error: Missing required module. {e}")
     print("Please install dependencies: pip install requests")
     sys.exit(1)
except ValueError as e:
     print(f"Error: Configuration failed. {e}")
     sys.exit(1)


def run_server(server_class=HTTPServer, handler_class=ProxyHandler):
    """Starts the HTTP proxy server."""
    cfg = config.get_config()
    port = cfg['proxy_port']
    downstream_url = cfg['local_chat_completions_url']

    try:
        server_address = ('', port)
        httpd = server_class(server_address, handler_class)
    except OSError as e:
        print(f"Error: Could not bind to port {port}. Is it already in use? ({e})")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to initialize server. {e}")
        sys.exit(1)


    print(f"--- Starting Python OpenAI /responses Proxy Server ---")
    print(f"Listening on port {port}")
    print(f"Accepting POST requests at /api/v1/responses")
    print(f"Forwarding to Chat Completions API: {downstream_url}")
    print(f"Using downstream request timeout: {cfg['downstream_timeout']}s")
    print(f"Transforming responses to fake SSE stream matching OpenAI format.")
    print(f"Using fake SSE inter-message delay: {cfg['sse_delay']}s")
    print(f"NOTE: Reformatting tools array to standard OpenAI structure for forwarding.")
    print(f"NOTE: Streaming is ALWAYS DISABLED when forwarding requests to backend.")
    print("--------------------------------------------------------------------------")
    print("Press Ctrl+C to stop the server.")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received, shutting down server...")
    finally:
        httpd.server_close()
        print("Server stopped.")

if __name__ == '__main__':
    run_server()