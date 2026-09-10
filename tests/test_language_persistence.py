import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class LanguagePersistenceRegression(unittest.TestCase):
    def post_language(self, **body):
        handler = server.ModManagerHandler.__new__(server.ModManagerHandler)
        handler.path = '/api/config/language'
        payload = json.dumps(body).encode('utf-8')
        handler.headers = {'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        result = []
        handler._send_json = result.append
        handler.do_POST()
        self.assertTrue(result[0]['success'])
        return result[0]

    def test_session_switch_leaves_file_unchanged_and_restart_uses_default(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            with patch.object(server, 'CONFIG_PATH', str(config)), \
                    patch.dict('core.i18n.LANGUAGES', {'es': {'id': 'es', 'name': 'Spanish'}}, clear=False):
                self.post_language(language='en', set_default=True)
                saved = config.read_bytes()
                response = self.post_language(language='es', set_default=False)
                self.assertEqual(response['language'], 'es')
                self.assertEqual(response['default_language'], 'en')
                self.assertEqual(config.read_bytes(), saved)
                loaded = server.load_saved_config()
                self.assertEqual(loaded['language'], 'en')
                self.assertEqual(loaded['default_language'], 'en')
                # Saving an unrelated preference must not persist a transient language.
                server.save_config(dismiss_fla_warning=True)
                self.assertEqual(server.load_saved_config()['language'], 'en')

    def test_legacy_session_field_does_not_override_saved_default(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            config.write_text(json.dumps({'language':'unknown_lang','default_language':'en'}), encoding='utf-8')
            with patch.object(server, 'CONFIG_PATH', str(config)):
                self.assertEqual(server.load_saved_config()['language'], 'en')
