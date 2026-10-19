"""Official OpenArt Streamable HTTP MCP transport for this headless workflow.

The CLI owns OAuth sign-in and refresh. No credentials are copied into project
configuration, logs or job state. Request failures are never retried, especially
the credit-spending generation call. Setup uses only read-only discovery.
"""
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
from urllib.parse import urljoin, urlsplit

import requests

from config import setting

ENDPOINT = 'https://mcp.openart.ai/mcp'
PROTOCOL = '2025-03-26'
_AUTH_LOCK = threading.Lock()
_CLI_ENVIRONMENT_KEYS = frozenset({
    'PATH', 'HOME', 'USERPROFILE', 'SYSTEMROOT', 'SystemRoot',
    'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ',
    'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME',
    'APPDATA', 'LOCALAPPDATA',
    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
    'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
})
_TOOLS = frozenset({
    'openart_account_get', 'openart_model_list', 'openart_model_form_get',
    'openart_model_cost', 'openart_project_list', 'openart_upload_sign',
    'openart_upload_list', 'openart_upload_metadata_get',
    'openart_generate_video', 'openart_creation_get',
})


class TransportError(RuntimeError):
    """A diagnostic safe to show without exposing provider bodies or tokens."""


def _cli_environment():
    """Give the CLI only runtime paths, locale and network configuration."""
    return {key: value for key, value in os.environ.items() if key in _CLI_ENVIRONMENT_KEYS}


def _public_https(url):
    """Reject local/private URL destinations, including each redirect target."""
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        if parts.port not in (None, 443):
            raise ValueError()
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError()
    except (ValueError, OSError, TypeError):
        raise TransportError('OpenArt returned an unsafe or unreachable media destination.') from None
    return url


class OpenArtTransport:
    def __init__(self, cli_bin=None, session=None, credential_path=None):
        configured = cli_bin or setting('OPENART_CLI_BIN', 'openart')
        self.cli_bin = shutil.which(configured)
        if not self.cli_bin and configured == 'openart':
            local = Path.home() / '.local/bin/openart'
            self.cli_bin = str(local) if local.is_file() else None
        self.credential_path = Path(credential_path or Path.home() / '.openart/cli-credentials.json')
        self.session = session or requests.Session()
        self._access_token = None
        self._expiry = None
        self._session_id = None
        self._initialized = False
        self._tools = None
        self._sequence = 0
        self.cli_version = None

    def _authorize(self):
        if self._access_token and self._expiry and self._expiry > datetime.now(timezone.utc) + timedelta(seconds=60):
            return
        if not self.cli_bin:
            raise TransportError('Install the official OpenArt CLI and run openart login.')
        with _AUTH_LOCK:
            # Let the CLI refresh its own OAuth credential. Do not pass other
            # provider credentials or an account-selecting OPENART_TOKEN.
            environment = _cli_environment()
            try:
                result = subprocess.run(
                    [self.cli_bin, '--json', '--no-input', 'account'],
                    env=environment, capture_output=True, text=True, timeout=45,
                )
                if result.returncode:
                    raise ValueError()
                if self.cli_version is None:
                    version = subprocess.run([self.cli_bin, 'version'], env=environment, capture_output=True, text=True, timeout=10)
                    import re
                    match = re.search(r'\b\d+\.\d+\.\d+\b', version.stdout)
                    self.cli_version = match.group(0) if version.returncode == 0 and match else 'unknown'
                data = json.loads(self.credential_path.read_text())
                if data.get('type') != 'oauth' or data.get('origin') != 'https://openart.ai':
                    raise ValueError()
                token = data.get('accessToken')
                expiry = datetime.fromisoformat(data['expiry'].replace('Z', '+00:00'))
                if not isinstance(token, str) or not token or expiry <= datetime.now(timezone.utc):
                    raise ValueError()
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                raise TransportError('OpenArt CLI authentication is unavailable or expired. Run openart login, then retry the read-only doctor.') from None
            self._access_token, self._expiry = token, expiry

    @staticmethod
    def _decode(response, request_id):
        try:
            if 'text/event-stream' in response.headers.get('Content-Type', ''):
                messages = []
                for event in response.text.replace('\r\n', '\n').split('\n\n'):
                    payload = '\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
                    if payload:
                        messages.append(json.loads(payload))
                value = next(message for message in messages if message.get('id') == request_id)
            else:
                value = response.json()
            if value.get('id') != request_id or value.get('error') or not isinstance(value.get('result'), dict):
                raise ValueError()
            return value['result']
        except (ValueError, TypeError, KeyError, StopIteration, AttributeError):
            raise TransportError('OpenArt returned an invalid MCP response. No request was retried.') from None

    def _rpc(self, method, params):
        self._authorize()
        self._sequence += 1
        headers = {'Authorization': 'Bearer ' + self._access_token,
                   'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': PROTOCOL}
        if self._session_id:
            headers['Mcp-Session-Id'] = self._session_id
        try:
            response = self.session.post(
                ENDPOINT, headers=headers,
                json={'jsonrpc': '2.0', 'id': self._sequence, 'method': method, 'params': params},
                timeout=(15, 180), allow_redirects=False,
            )
        except requests.RequestException:
            raise TransportError('OpenArt MCP connection failed. The request was not retried.') from None
        if response.status_code != 200:
            raise TransportError(f'OpenArt MCP returned HTTP {response.status_code}. The request was not retried.')
        if response.headers.get('Mcp-Session-Id'):
            self._session_id = response.headers['Mcp-Session-Id']
        return self._decode(response, self._sequence)

    def _initialize(self):
        if self._initialized:
            return
        result = self._rpc('initialize', {
            'protocolVersion': PROTOCOL, 'capabilities': {},
            'clientInfo': {'name': 'genjustsu-workflow', 'version': '1.0.0'},
        })
        if result.get('protocolVersion') != PROTOCOL or not result.get('capabilities', {}).get('tools'):
            raise TransportError('OpenArt does not advertise the required MCP protocol and tools.')
        # MCP initialized notification has no response body or JSON-RPC id.
        headers = {'Authorization': 'Bearer ' + self._access_token,
                   'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': PROTOCOL}
        if self._session_id:
            headers['Mcp-Session-Id'] = self._session_id
        try:
            response = self.session.post(ENDPOINT, headers=headers,
                json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                timeout=(15, 30), allow_redirects=False)
            if response.status_code not in (200, 202, 204):
                raise ValueError()
        except (requests.RequestException, ValueError):
            raise TransportError('OpenArt MCP initialization could not be completed.') from None
        self._initialized = True

    def call(self, tool, arguments):
        if tool not in _TOOLS or not isinstance(arguments, dict):
            raise TransportError('This OpenArt operation is not supported by the workflow.')
        self._initialize()
        if self._tools is None:
            self._tools = set()
            cursor = None
            while True:
                page = self._rpc('tools/list', {'cursor': cursor} if cursor else {})
                self._tools.update(item['name'] for item in page.get('tools', []) if isinstance(item.get('name'), str))
                next_cursor = page.get('nextCursor')
                if not next_cursor:
                    break
                if next_cursor == cursor:
                    raise TransportError('OpenArt tool discovery did not complete.')
                cursor = next_cursor
        if tool not in self._tools:
            raise TransportError('The official OpenArt server does not expose the required operation.')
        result = self._rpc('tools/call', {'name': tool, 'arguments': arguments})
        if result.get('isError'):
            raise TransportError('OpenArt rejected the operation. Raw provider output was not saved.')
        value = result.get('structuredContent')
        if value is None:
            try:
                value = json.loads(next(item['text'] for item in result.get('content', []) if item.get('type') == 'text'))
            except (ValueError, KeyError, StopIteration):
                raise TransportError('OpenArt returned no structured operation result.') from None
        if not isinstance(value, dict):
            raise TransportError('OpenArt returned an invalid operation result.')
        return value

    def upload(self, path, media_type, label, project_id=None):
        """Headless app upload, invoked only for an authorized reviewed job."""
        path = Path(path)
        content_type = mimetypes.guess_type(path.name)[0]
        if not path.is_file() or not content_type or path.stat().st_size <= 0:
            raise TransportError('The reference file is missing, empty or unsupported.')
        args = {'mediaType': media_type, 'filename': path.name, 'size': path.stat().st_size,
                'contentType': content_type, 'label': label, 'purpose': 'create-video'}
        if project_id:
            args['projectId'] = project_id
        signed = self.call('openart_upload_sign', args)
        try:
            destination = _public_https(signed['signURL'])
            with path.open('rb') as stream:
                # No OAuth header is sent to a media host. Never follow PUT redirects.
                response = self.session.put(destination, data=stream,
                    headers={'Content-Type': signed['contentType'], 'Content-Length': str(path.stat().st_size)},
                    timeout=(15, 180), allow_redirects=False)
            if response.status_code not in (200, 201, 204):
                raise ValueError()
            result = self.call('openart_upload_metadata_get', {
                'mediaUrl': signed['accessURL'], 'mediaType': media_type,
                'uploadId': signed['uploadId'], 'label': label,
            })
            reference = result['visualReference']
            if reference['id'] != signed['uploadId'] or reference['type'] != media_type:
                raise ValueError()
            return reference
        except (requests.RequestException, OSError, KeyError, ValueError, TypeError):
            raise TransportError('OpenArt reference transfer or acceptance failed; generation was not submitted.') from None

    def resolve_reference(self, upload_id, project_id):
        cursor = None
        seen = set()
        while True:
            args = {'projectId': project_id, 'includeMetadata': True}
            if cursor:
                args['cursor'] = cursor
            page = self.call('openart_upload_list', args)
            matches = [item for item in page.get('items', []) if item.get('id') == upload_id]
            if len(matches) == 1:
                reference = matches[0].get('visualReference', {})
                if reference.get('id') == upload_id:
                    return reference
                break
            cursor = page.get('nextCursor')
            if not page.get('hasMore') or not cursor or cursor in seen:
                break
            seen.add(cursor)
        raise TransportError('The exact saved OpenArt upload is unavailable in its original project.')

    def download(self, url, target):
        target = Path(target)
        response = None
        try:
            for _ in range(4):
                _public_https(url)
                response = self.session.get(url, stream=True, timeout=(15, 180), allow_redirects=False)
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    response.close()
                    if not location:
                        raise ValueError()
                    url = urljoin(url, location)
                    continue
                break
            if response is None or response.status_code != 200:
                raise ValueError()
            with target.open('wb') as stream:
                os.chmod(target, 0o600)
                total = 0
                for chunk in response.iter_content(1024 * 1024):
                    total += len(chunk)
                    if total > 2 * 1024**3:
                        raise ValueError()
                    stream.write(chunk)
        except (requests.RequestException, OSError, ValueError, TransportError):
            target.unlink(missing_ok=True)
            raise TransportError('The OpenArt video download failed; resume the saved operation without resubmitting.') from None
        finally:
            if response is not None:
                response.close()
