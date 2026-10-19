import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import config


class ConfigTests(unittest.TestCase):
    def test_alias_is_exported_and_access_token_takes_precedence(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, 'ROOT', Path(folder)), patch.dict(os.environ, {'HF_TOKEN': 'alias', 'HF_ACCESS_TOKEN': 'preferred'}, clear=True):
            self.assertEqual(config.credential('HF_ACCESS_TOKEN'), 'preferred')
            self.assertEqual(os.environ['HF_TOKEN'], 'preferred')

    def test_hf_token_alias_without_new_name(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, 'ROOT', Path(folder)), patch.dict(os.environ, {'HF_TOKEN': 'alias'}, clear=True):
            self.assertEqual(config.credential('HF_ACCESS_TOKEN'), 'alias')

    def test_project_file_never_overwrites_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, 'ROOT', Path(folder)), patch.dict(os.environ, {'OPENAI_API_KEY': 'environment'}, clear=True):
            (Path(folder) / '.env').write_text('OPENAI_API_KEY=file\nELEVENLABS_API_KEY=local\n')
            self.assertEqual(config.credential('OPENAI_API_KEY'), 'environment')
            self.assertEqual(config.credential('ELEVENLABS_API_KEY'), 'local')

    def test_new_defaults_do_not_depend_on_legacy_keys(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, 'ROOT', Path(folder)), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.setting('OPENART_CLI_BIN'), 'openart')
            self.assertEqual(config.setting('OPENART_DRAFT_MODEL'), 'byte-plus-seedance-2-5-draft')
            self.assertEqual(config.setting('OPENART_DRAFT_RESOLUTION'), '480p')
            self.assertEqual(config.setting('FINAL_AUDIO_SOURCE'), 'original')
            self.assertEqual(config.setting('AUDIO_DISGUISE_MODE'), 'pitch_shift')
            with self.assertRaisesRegex(ValueError, 'HF_ACCESS_TOKEN'):
                config.credential('HF_ACCESS_TOKEN')
