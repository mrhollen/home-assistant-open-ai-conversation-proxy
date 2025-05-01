import json
import os

CONFIG = {}

def load_config(config_path='config.json'):
    """Loads configuration from a JSON file and environment variables."""
    global CONFIG
    try:
        with open(config_path, 'r') as f:
            CONFIG = json.load(f)
        print(f"Configuration loaded from {config_path}")
    except FileNotFoundError:
        print(f"Warning: {config_path} not found. Using defaults and environment variables.")
        CONFIG = { # Provide some basic defaults if file is missing
            "default_model": "gpt-3.5-turbo",
            "default_max_tokens": 150,
            "default_temperature": 0.7,
            "default_top_p": 1.0,
            "proxy_port": 5002,
            "sse_delay": 0.02,
            "downstream_timeout": 90
        }
    except json.JSONDecodeError:
        raise ValueError(f"Error decoding JSON from {config_path}")

    # Allow environment variable override for the crucial URL
    env_url = os.environ.get('LOCAL_CHAT_COMPLETIONS_URL')
    if env_url:
        CONFIG['local_chat_completions_url'] = env_url
        print(f"Overriding local_chat_completions_url with environment variable: {env_url}")
    elif not CONFIG.get('local_chat_completions_url'):
         raise ValueError("LOCAL_CHAT_COMPLETIONS_URL environment variable or "
                          "'local_chat_completions_url' in config.json must be set.")

    # Ensure required keys have defaults if missing after load (apart from URL)
    CONFIG.setdefault("default_model", "gpt-3.5-turbo")
    CONFIG.setdefault("default_max_tokens", 150)
    CONFIG.setdefault("default_temperature", 0.7)
    CONFIG.setdefault("default_top_p", 1.0)
    CONFIG.setdefault("proxy_port", 5002)
    CONFIG.setdefault("sse_delay", 0.02)
    CONFIG.setdefault("downstream_timeout", 90)

    return CONFIG

# Load config when module is imported
load_config()

# --- Public accessors ---
def get_config():
    """Returns the loaded configuration dictionary."""
    return CONFIG

def get(key, default=None):
    """Gets a specific config value by key."""
    return CONFIG.get(key, default)