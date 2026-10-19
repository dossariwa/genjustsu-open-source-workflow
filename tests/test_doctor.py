import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import doctor


class DoctorTests(unittest.TestCase):
    def run_doctor(self, values=None, argv=(), authenticated=True, masks=True, discovery_error=None, credits=12000, model_verified=True, schema_verified=True, hd_supported=False):
        values = values or {}
        def setting(name, default=''):
            return values.get(name, default)
        status = {
            'provider': 'openart', 'cli_version': 'test-version',
            'authenticated': authenticated, 'plan': 'verified-plan', 'credits': credits,
            'model': 'byte-plus-seedance-2-5-draft', 'model_verified': model_verified,
            'schema_verified': schema_verified, 'mode': 'reference-video', 'resolution': '480p',
            'capabilities': {'video_hd_supported': hd_supported},
        }
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('doctor.setting', side_effect=setting))
            stack.enter_context(patch('doctor.shutil.which', return_value='/bin/rubberband'))
            stack.enter_context(patch('doctor.subprocess.run', return_value=Mock(returncode=0)))
            stack.enter_context(patch('openart_bridge.readiness', return_value=status, side_effect=discovery_error))
            stack.enter_context(patch('raw_masks.configuration_status', return_value={'ready': masks, 'detail': 'raw mask configuration'}))
            stack.enter_context(patch('doctor.importlib.import_module'))
            stack.enter_context(contextlib.redirect_stdout(output))
            code = doctor.main(list(argv))
        return code, output.getvalue()

    def credentials(self):
        return {key: 'PRIVATE-CREDENTIAL-MUST-NOT-APPEAR' for key in ('HF_ACCESS_TOKEN', 'OPENAI_API_KEY', 'ELEVENLABS_API_KEY')}

    def test_missing_credentials_are_ui_ready_but_generation_blocked(self):
        code, output = self.run_doctor(authenticated=False, masks=False)
        self.assertEqual(code, 0)
        self.assertIn('GENERATION BLOCKED', output)
        self.assertIn('NOT SIGNED IN', output)
        strict, _ = self.run_doctor(argv=['--require-keys'], authenticated=False, masks=False)
        self.assertEqual(strict, 2)

    def test_openart_ready_without_legacy_keys_and_secrets_never_printed(self):
        code, output = self.run_doctor(self.credentials(), argv=['--require-keys'])
        self.assertEqual(code, 0)
        self.assertIn('CONFIGURATION CHECKS PASSED', output)
        self.assertNotIn('PRIVATE-CREDENTIAL', output)
        self.assertIn('credits 12000', output)
        self.assertIn('live generation and download remain untested', output)
        self.assertIn('no replacement generation is substituted', output)

    def test_provider_exception_text_is_never_exposed(self):
        code, output = self.run_doctor(argv=['--require-keys'], discovery_error=RuntimeError('sk-PRIVATE-LEAK'))
        self.assertEqual(code, 2)
        self.assertIn('RuntimeError', output)
        self.assertNotIn('sk-PRIVATE-LEAK', output)

    def test_sts_requires_voice_id(self):
        values = self.credentials()
        values['AUDIO_DISGUISE_MODE'] = 'elevenlabs_sts'
        code, output = self.run_doctor(values, argv=['--require-keys'])
        self.assertEqual(code, 2)
        self.assertIn('ELEVENLABS_VOICE_ID', output)

    def test_connector_login_does_not_substitute_for_cli_login(self):
        code, output = self.run_doctor(self.credentials(), argv=['--require-keys'], authenticated=False)
        self.assertEqual(code, 2)
        self.assertIn('connector authentication is separate', output)
        self.assertIn('GENERATION BLOCKED: OpenArt CLI authentication', output)

    def test_catalog_or_schema_failure_blocks_without_inference(self):
        for key in ('model_verified', 'schema_verified'):
            with self.subTest(key=key):
                code, output = self.run_doctor(self.credentials(), argv=['--require-keys'], **{key: False})
                self.assertEqual(code, 2)
                self.assertIn('UNVERIFIED', output)
                self.assertNotIn('CONFIGURATION CHECKS PASSED', output)

    def test_zero_balance_blocks_but_no_account_purchase_is_attempted(self):
        code, output = self.run_doctor(self.credentials(), argv=['--require-keys'], credits=0)
        self.assertEqual(code, 2)
        self.assertIn('GENERATION BLOCKED: OpenArt credits', output)

    def test_hd_contract_does_not_authorize_hd_spending(self):
        code, output = self.run_doctor(self.credentials(), argv=['--require-keys'], hd_supported=True)
        self.assertEqual(code, 0)
        self.assertIn('separate explicit approval and draft lineage required', output)


if __name__ == '__main__':
    unittest.main()
