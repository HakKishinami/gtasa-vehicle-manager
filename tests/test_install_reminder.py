import tempfile
import unittest
import io
import json
from pathlib import Path
from unittest.mock import patch
from core.install_reminder import check_existing_models


class InstallReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'unchanged')
        return path.parent

    def check(self, **params):
        return check_existing_models(str(self.root), params)['matches']

    def test_first_install_does_not_create_modloader(self):
        self.assertEqual(self.check(target_model='cheetah'), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_renamed_folder_and_case_insensitive_model(self):
        folder = self.write('modloader/Modded Cars/My renamed car/CHEETAH.DFF')
        self.assertEqual(self.check(target_model='Cheetah'),
                         [{'path': str(folder), 'models': ['cheetah']}])

    def test_multi_car_groups_matches_and_ignores_skipped_source_models(self):
        folder = self.write('modloader/Addon Cars/Pack/cheetah86.dff')
        self.write('modloader/Addon Cars/Pack/spider.dff')
        self.write('modloader/Addon Cars/Pack/skipme.dff')
        self.write('modloader/Addon Cars/Pack/source.dff')
        matches = self.check(vehicles=[
            {'target_model': 'cheetah86', 'source_model': 'source'},
            {'target_model': 'spider'}, {'target_model': 'skipme', 'skip': True}])
        self.assertEqual(matches, [{'path': str(folder), 'models': ['cheetah86', 'spider']}])

    def test_only_deployed_dff_matches(self):
        self.write('data/cheetah.dff')
        self.write('modloader/cheetah/cheetah.txd')
        self.write('modloader/cheetah/cheetah.fxt')
        self.assertEqual(self.check(target_model='cheetah'), [])

    def test_check_never_changes_files(self):
        self.write('modloader/Old/cheetah.dff')
        self.write('modloader/Old/names.fxt')
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.check(target_model='cheetah')
        after = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_scan_errors_are_not_reported_as_no_matches(self):
        self.write('modloader/Old/cheetah.dff')
        with patch('core.install_reminder.os.walk', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.check(target_model='cheetah')

    def test_no_target_and_all_skipped(self):
        self.write('modloader/Old/cheetah.dff')
        self.assertEqual(self.check(), [])
        self.assertEqual(self.check(vehicles=[{'target_model': 'cheetah', 'skip': True}]), [])

    def test_http_check_returns_matches_without_calling_installer(self):
        import server
        folder = self.write('modloader/Renamed/cheetah.dff')
        handler = object.__new__(server.ModManagerHandler)
        handler.path = '/api/installer/check-existing'
        body = json.dumps({'target_model': 'cheetah'}).encode()
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        with patch.object(server, 'GAME_PATH', str(self.root)), \
             patch.object(server, 'installer') as installer, \
             patch.object(handler, '_send_json') as reply:
            handler.do_POST()
        installer.execute_install.assert_not_called()
        self.assertEqual(reply.call_args.args[0]['matches'],
                         [{'path': str(folder), 'models': ['cheetah']}])
