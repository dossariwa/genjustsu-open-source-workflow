"""Offline contract checks: no real credentials, network, upload or spending."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from openart_transport import ENDPOINT, OpenArtTransport, TransportError, _public_https


class OpenArtTransportTests(unittest.TestCase):
    def setUp(self):
        # Mock assertion failures must never capture inherited credentials.
        self.enterContext(patch.dict(os.environ, {'PATH': '/test-bin'}, clear=True))

    def transport(self, session=None, credential_path=None):
        with patch('openart_transport.shutil.which', return_value='/mock/bin/openart'):
            result = OpenArtTransport(cli_bin='/mock/bin/openart', session=session or Mock(), credential_path=credential_path)
        return result

    def response(self, status=200, result=None, request_id=1, headers=None):
        result = {} if result is None else result
        response = Mock(status_code=status, headers=headers or {'Content-Type': 'application/json'})
        response.json.return_value = {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        response.text = 'PRIVATE-PROVIDER-BODY'
        return response

    def dns(self, host, port, **kwargs):
        address = '127.0.0.1' if host in ('localhost', '127.0.0.1') else '8.8.8.8'
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]

    def test_cli_owns_oauth_refresh_and_inherited_token_cannot_select_account(self):
        secret = 'PRIVATE-OAUTH-ACCESS-TOKEN'
        with tempfile.TemporaryDirectory() as directory:
            credentials = Path(directory) / 'credentials.json'
            credentials.write_text(json.dumps({
                'type': 'oauth', 'origin': 'https://openart.ai', 'accessToken': secret,
                'expiry': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            }))
            transport = self.transport(credential_path=credentials)
            output = io.StringIO()
            with patch.dict(os.environ, {'OPENART_TOKEN': 'UNRELATED-ACCOUNT-TOKEN', 'HF_ACCESS_TOKEN': 'SYNTHETIC-HF-SECRET', 'OPENAI_API_KEY': 'SYNTHETIC-OPENAI-SECRET', 'HOME': '/mock-home', 'HTTPS_PROXY': 'http://proxy.example:8080'}), patch('openart_transport.subprocess.run', return_value=Mock(returncode=0, stdout=secret)) as command, contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                transport._authorize()
                transport._authorize()
            self.assertEqual(command.call_count, 2)
            account_call = command.call_args_list[0]
            self.assertEqual(account_call.args[0], ['/mock/bin/openart', '--json', '--no-input', 'account'])
            expected_environment = {'PATH': '/test-bin', 'HOME': '/mock-home', 'HTTPS_PROXY': 'http://proxy.example:8080'}
            self.assertEqual(account_call.kwargs['env'], expected_environment)
            self.assertEqual(command.call_args_list[1].kwargs['env'], expected_environment)
            self.assertTrue(account_call.kwargs['capture_output'])
            self.assertEqual(transport._access_token, secret)
            self.assertNotIn(secret, output.getvalue())

    def test_wrong_origin_expired_and_non_oauth_credentials_fail_without_leaking(self):
        base = {'type': 'oauth', 'origin': 'https://openart.ai', 'accessToken': 'PRIVATE-TOKEN',
                'expiry': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        invalid = [dict(base, origin='https://untrusted.example'), dict(base, type='pat'),
                   dict(base, expiry='2000-01-01T00:00:00Z'), dict(base, expiry='PRIVATE-TOKEN')]
        with tempfile.TemporaryDirectory() as directory, patch('openart_transport.subprocess.run', return_value=Mock(returncode=0, stdout='openart 0.1.1')):
            credentials = Path(directory) / 'credentials.json'
            for entry in invalid:
                with self.subTest(entry=entry['origin'] + entry['type'] + entry['expiry']):
                    credentials.write_text(json.dumps(entry))
                    transport = self.transport(credential_path=credentials)
                    with self.assertRaises(TransportError) as caught:
                        transport._authorize()
                    self.assertNotIn('PRIVATE-TOKEN', str(caught.exception))
                    self.assertIsNone(transport._access_token)

    def test_generation_http_401_is_never_retried_or_reauthorized(self):
        session = Mock()
        session.post.return_value = self.response(status=401)
        transport = self.transport(session)
        transport._access_token = 'TEST-ACCESS-TOKEN'
        with patch.object(transport, '_authorize') as authorize:
            with self.assertRaisesRegex(TransportError, 'HTTP 401') as caught:
                transport._rpc('tools/call', {'name': 'openart_generate_video', 'arguments': {}})
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(authorize.call_count, 1)
        self.assertNotIn('PRIVATE-PROVIDER-BODY', str(caught.exception))
        self.assertNotIn('TEST-ACCESS-TOKEN', str(caught.exception))
        self.assertEqual(session.post.call_args.args, (ENDPOINT,))
        self.assertFalse(session.post.call_args.kwargs['allow_redirects'])

    def test_generation_timeout_is_never_retried(self):
        session = Mock()
        session.post.side_effect = requests.Timeout('PRIVATE-SIGNED-URL?token=SECRET')
        transport = self.transport(session)
        transport._access_token = 'TEST-ACCESS-TOKEN'
        with patch.object(transport, '_authorize'):
            with self.assertRaises(TransportError) as caught:
                transport._rpc('tools/call', {'name': 'openart_generate_video', 'arguments': {}})
        self.assertEqual(session.post.call_count, 1)
        self.assertIn('not retried', str(caught.exception))
        self.assertNotIn('SECRET', str(caught.exception))

    def test_json_and_sse_responses_bind_to_requested_id(self):
        response = self.response(result={'account': 'ok'}, request_id=17)
        self.assertEqual(OpenArtTransport._decode(response, 17), {'account': 'ok'})
        response.headers = {'Content-Type': 'text/event-stream; charset=utf-8'}
        response.text = 'event: message\r\ndata: {"id": 16, "result": {"wrong": true}}\r\n\r\nevent: message\r\ndata: {"id":17,\r\ndata: "result":{"account":"ok"}}\r\n\r\n'
        self.assertEqual(OpenArtTransport._decode(response, 17), {'account': 'ok'})

    def test_mismatched_rpc_id_and_provider_errors_are_safe_failures(self):
        responses = [self.response(request_id=2)]
        error = self.response()
        error.json.return_value = {'id': 1, 'error': {'message': 'PRIVATE-SECRET'}}
        responses.append(error)
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(TransportError) as caught:
                    OpenArtTransport._decode(response, 1)
                self.assertNotIn('PRIVATE-SECRET', str(caught.exception))

    def test_tool_allowlist_rejects_unknown_operations_before_network(self):
        transport = self.transport()
        with patch.object(transport, '_initialize') as initialize:
            for tool, arguments in [('openart_purchase_credits', {}), ('openart_account_get', []), ('shell', {})]:
                with self.subTest(tool=tool):
                    with self.assertRaises(TransportError):
                        transport.call(tool, arguments)
            initialize.assert_not_called()
        transport.session.post.assert_not_called()

    def test_operation_must_also_be_advertised_by_server(self):
        transport = self.transport()
        transport._tools = {'openart_account_get'}
        with patch.object(transport, '_initialize'), patch.object(transport, '_rpc') as rpc:
            with self.assertRaisesRegex(TransportError, 'does not expose'):
                transport.call('openart_generate_video', {})
            rpc.assert_not_called()

    def test_mcp_result_accepts_structured_or_json_text_but_hides_remote_error(self):
        transport = self.transport()
        transport._tools = {'openart_account_get'}
        with patch.object(transport, '_initialize'), patch.object(transport, '_rpc') as rpc:
            rpc.return_value = {'structuredContent': {'credits': 4000}}
            self.assertEqual(transport.call('openart_account_get', {}), {'credits': 4000})
            rpc.return_value = {'content': [{'type': 'text', 'text': '{"credits":4000}'}]}
            self.assertEqual(transport.call('openart_account_get', {}), {'credits': 4000})
            rpc.return_value = {'isError': True, 'content': [{'type': 'text', 'text': 'PRIVATE-SECRET'}]}
            with self.assertRaises(TransportError) as caught:
                transport.call('openart_account_get', {})
            self.assertNotIn('PRIVATE-SECRET', str(caught.exception))

    def test_upload_is_project_bound_and_does_not_send_oauth_to_media_host(self):
        session = Mock()
        session.put.return_value = self.response(status=204)
        transport = self.transport(session)
        signed = {'signURL': 'https://media.example/upload?signature=PRIVATE',
                  'accessURL': 'https://media.example/accepted', 'uploadId': 'upload-123', 'contentType': 'video/mp4'}
        reference = {'id': 'upload-123', 'type': 'video', 'url': signed['accessURL'], 'label': 'Video1'}
        with tempfile.TemporaryDirectory() as directory, patch('openart_transport.socket.getaddrinfo', side_effect=self.dns), patch.object(transport, 'call', side_effect=[signed, {'visualReference': reference}]) as call:
            source = Path(directory) / 'source.mp4'
            source.write_bytes(b'synthetic-test-media')
            result = transport.upload(source, 'video', 'Video1', project_id='project-original')
        self.assertEqual(result, reference)
        self.assertEqual(call.call_args_list[0].args[0], 'openart_upload_sign')
        self.assertEqual(call.call_args_list[0].args[1]['projectId'], 'project-original')
        self.assertEqual(call.call_args_list[1].args[1]['uploadId'], 'upload-123')
        self.assertNotIn('Authorization', session.put.call_args.kwargs['headers'])
        self.assertFalse(session.put.call_args.kwargs['allow_redirects'])

    def test_resume_resolves_only_exact_saved_upload_in_original_project(self):
        transport = self.transport()
        reference = {'id': 'upload-123', 'type': 'video', 'url': 'https://media.example/accepted', 'label': 'Video1'}
        pages = [
            {'items': [{'id': 'different-id', 'filename': 'same-name.mp4', 'visualReference': reference}], 'hasMore': True, 'nextCursor': 'page-two'},
            {'items': [{'id': 'upload-123', 'visualReference': reference}], 'hasMore': False},
        ]
        with patch.object(transport, 'call', side_effect=pages) as call:
            self.assertEqual(transport.resolve_reference('upload-123', 'project-original'), reference)
        self.assertEqual(call.call_count, 2)
        for invocation in call.call_args_list:
            self.assertEqual(invocation.args[0], 'openart_upload_list')
            self.assertEqual(invocation.args[1]['projectId'], 'project-original')
        self.assertEqual(call.call_args_list[1].args[1]['cursor'], 'page-two')

    def test_ambiguous_upload_or_repeated_cursor_fails_without_substitution(self):
        transport = self.transport()
        duplicate = {'items': [{'id': 'same'}, {'id': 'same'}], 'hasMore': False}
        repeated = {'items': [], 'hasMore': True, 'nextCursor': 'again'}
        for pages in ([duplicate], [repeated, repeated]):
            with self.subTest(pages=len(pages)), patch.object(transport, 'call', side_effect=pages) as call:
                with self.assertRaisesRegex(TransportError, 'exact saved'):
                    transport.resolve_reference('same', 'original')
                self.assertEqual(call.call_count, len(pages))

    def test_private_destination_and_credentials_in_url_are_rejected(self):
        with patch('openart_transport.socket.getaddrinfo', side_effect=self.dns):
            for url in ('http://media.example/file', 'https://localhost/file', 'https://127.0.0.1/file', 'https://user:password@media.example/file', 'https://media.example:8443/file'):
                with self.subTest(url=url):
                    with self.assertRaises(TransportError):
                        _public_https(url)

    def test_download_revalidates_redirect_before_contacting_localhost(self):
        session = Mock()
        redirect = self.response(status=302, headers={'Location': 'https://localhost/secret'})
        session.get.return_value = redirect
        transport = self.transport(session)
        with tempfile.TemporaryDirectory() as directory, patch('openart_transport.socket.getaddrinfo', side_effect=self.dns):
            target = Path(directory) / 'result.mp4'
            target.write_bytes(b'old-partial')
            with self.assertRaises(TransportError):
                transport.download('https://media.example/result', target)
            self.assertFalse(target.exists())
        session.get.assert_called_once()
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
        redirect.close.assert_called()

    def test_download_saves_private_file_and_never_sends_oauth_header(self):
        session = Mock()
        response = self.response()
        response.iter_content.return_value = [b'video-', b'data']
        session.get.return_value = response
        transport = self.transport(session)
        with tempfile.TemporaryDirectory() as directory, patch('openart_transport.socket.getaddrinfo', side_effect=self.dns):
            target = Path(directory) / 'result.mp4'
            transport.download('https://media.example/result', target)
            self.assertEqual(target.read_bytes(), b'video-data')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('headers', session.get.call_args.kwargs)
        response.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
