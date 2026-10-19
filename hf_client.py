"""Authenticated Gradio client helpers. This module loads no model weights."""
import inspect
from pathlib import Path
from gradio_client import Client
from config import credential


def client(space):
    """Support both current token and older hf_token client releases."""
    parameters = inspect.signature(Client).parameters
    key = 'token' if 'token' in parameters else 'hf_token'
    token = credential('HF_ACCESS_TOKEN')
    try:
        return Client(space, **{key: token}, verbose=False)
    except Exception:
        raise RuntimeError('Cannot connect to the configured Hugging Face Space; check authentication and availability.') from None


def endpoint_schema(connection, api_name):
    try:
        schema = connection.view_api(return_format='dict', print_info=False)
    except Exception:
        raise RuntimeError('Cannot read the Hugging Face Space API schema; no inference was submitted.') from None
    endpoint = schema.get('named_endpoints', {}).get(api_name)
    if not endpoint:
        raise ValueError(f'Hugging Face Space does not expose {api_name}. Check its current API schema.')
    return endpoint


def local_file(value):
    """Only accept files downloaded by gradio_client, never arbitrary URLs."""
    if isinstance(value, dict):
        return local_file(value.get('path') or value.get('video'))
    if isinstance(value, (str, Path)) and Path(value).is_file():
        return Path(value)
    raise ValueError('Hugging Face did not return a downloaded local file.')
