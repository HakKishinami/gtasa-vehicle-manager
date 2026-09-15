import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.backup_manager import BackupManager
from core.fxt_installer import deploy_fxt, entry
from core.installer import ModInstaller


class FxtRoutingRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.dest = [self.root / 'Modded Cars' / 'Cheetah GT',
                     self.root / 'Addon Cars' / 'CHEET86',
                     self.root / 'Addon Cars' / 'CHEETSP']
        for path in self.dest:
            path.mkdir(parents=True)
        self.vehicles = [dict(source_model=m, target_model=m, fxt_key=m.upper(),
                              fxt_name=n, generate_fxt=True)
                         for m, n in [('cheetah', 'Cheetah GT'), ('cheet86', "Cheetah '86"),
                                      ('cheetsp', 'Cheetah Spider')]]
        self.backup = BackupManager(str(self.root / 'backups'), str(self.root))

    def author(self, filename, content):
        path = self.source / filename
        path.write_text(content, encoding='utf-8')
        return str(path)

    def deploy(self, files, destinations=None, source_keys=None):
        return deploy_fxt(files, self.vehicles,
                          destinations or [str(d) for d in self.dest],
                          source_keys or {}, self.backup)

    def mappings(self):
        found = {}
        for directory in self.dest:
            for path in directory.rglob('*.fxt'):
                for line in path.read_text(encoding='utf-8-sig').splitlines():
                    parsed = entry(line)
                    if parsed:
                        found.setdefault(parsed[0], []).append((path, parsed[1]))
        return found

    def test_generated_file_uses_crlf(self):
        """A file this function creates follows the long-standing convention."""
        self.deploy([])
        created = self.dest[0] / 'cheetah.fxt'
        self.assertTrue(created.exists())
        self.assertEqual(created.read_bytes(), b'CHEETAH Cheetah GT\r\n')

    def test_replacement_without_author_fxt_and_empty_name_creates_no_fxt(self):
        vehicles = [dict(source_model='glenshit', target_model='glenshit', fxt_key='GLENSHI',
                         fxt_name='', generate_fxt=False, is_addon=False)]
        changed, _ = deploy_fxt([], vehicles, [str(self.dest[0])], {}, self.backup)
        self.assertEqual(changed, [])
        fxts = list(self.dest[0].glob('*.fxt'))
        self.assertEqual(fxts, [])

    def test_cheetah_pack_routes_individual_author_files_without_duplicates(self):
        files = [self.author('cheetah.fxt', 'CHEETAH Cheetah GT'),
                 self.author('cheet86.fxt', 'CHEET86 Cheetah'),
                 self.author('cheetsp.fxt', 'CHEETSP Cheetah Spider')]
        self.deploy(files)
        rows = self.mappings()
        for index, vehicle in enumerate(self.vehicles):
            key = vehicle['fxt_key']
            self.assertEqual(rows[key], [(self.dest[index] / (vehicle['source_model'] + '.fxt'), vehicle['fxt_name'])])

    def test_shared_author_file_is_split_and_skipped_vehicle_is_omitted(self):
        source = self.author('names.fxt', '# Author names\nCHEETAH GT\nCHEET86 Classic\nCHEETSP Spider\nEXTRA Other UI text\n')
        self.vehicles[2]['skip'] = True
        self.deploy([source], [str(self.dest[0]), str(self.dest[1]), None])
        rows = self.mappings()
        self.assertNotIn('CHEETSP', rows)
        self.assertEqual(len(rows['EXTRA']), 1)
        self.assertEqual(rows['CHEET86'][0][0].parent, self.dest[1])
        self.assertIn('# Author names', (self.dest[1] / 'names.fxt').read_text())

    def test_ignored_skipped_vehicle_key_is_not_rehomed(self):
        # A shared author file that also carries the skipped car's key must not
        # leak that entry into an active destination through the unowned fallback.
        source = self.author('names.fxt', 'CHEETAH GT\nCHEETSP Spider\n')
        deploy_fxt([source], self.vehicles,
                   [str(self.dest[0]), None, None], {}, self.backup,
                   ignored_keys={'CHEETSP'})
        rows = self.mappings()
        self.assertIn('CHEETAH', rows)
        self.assertNotIn('CHEETSP', rows)

    def test_updates_key_in_second_author_file_in_shared_directory(self):
        first = self.author('a.fxt', 'CHEETAH GT\n')
        second = self.author('b.fxt', 'CHEET86 Old name\nCHEETSP Spider\n')
        self.deploy([first, second], [str(self.dest[0])] * 3)
        rows = self.mappings()
        self.assertEqual(rows['CHEET86'], [(self.dest[0] / 'b.fxt', "Cheetah '86")])
        self.assertNotIn('CHEET86', (self.dest[0] / 'a.fxt').read_text())

    def test_existing_duplicates_removed_with_backup_and_unrelated_entries_preserved(self):
        (self.dest[0] / 'wrong.fxt').write_text('CHEET86 Old\nKEEP Other name\n', encoding='utf-8')
        (self.dest[0] / 'duplicate.fxt').write_text('# redundant\nCHEET86 Old\n', encoding='utf-8')
        (self.dest[1] / 'cheet86.fxt').write_text('CHEET86 Old\n', encoding='utf-8')
        self.deploy([self.author('cheet86.fxt', 'CHEET86 Author name\n')])
        rows = self.mappings()
        self.assertEqual(len(rows['CHEET86']), 1)
        self.assertEqual(len(rows['KEEP']), 1)
        self.assertFalse((self.dest[0] / 'duplicate.fxt').exists())
        self.assertTrue(list((self.root / 'backups').rglob('duplicate.fxt')))

    def test_reinstall_is_idempotent(self):
        source = self.author('names.fxt', 'CHEET86 Old\nCHEETSP Old\nEXTRA Other UI text\n')
        self.deploy([source])
        before = {p: p.read_bytes() for d in self.dest for p in d.glob('*.fxt')}
        changed, _ = self.deploy([source])
        self.assertEqual(changed, [])
        self.assertEqual({p: p.read_bytes() for d in self.dest for p in d.glob('*.fxt')}, before)

    def test_case_insensitive_existing_filename_keeps_unrelated_entries(self):
        (self.dest[1] / 'CHEET86.FXT').write_text('CHEET86 Old\nKEEP Unrelated\n', encoding='utf-8')
        self.deploy([self.author('cheet86.fxt', 'CHEET86 Original\n')])
        self.assertEqual(len(self.mappings()['CHEET86']), 1)
        self.assertEqual(len(self.mappings()['KEEP']), 1)

    def test_previous_custom_key_is_removed_when_reinstalling_with_a_new_key(self):
        (self.dest[1] / 'cheet86.fxt').write_text('OLDKEY Old name\nKEEP Unrelated\n', encoding='utf-8')
        self.vehicles[1]['fxt_key'] = 'NEWKEY'
        deploy_fxt([self.author('cheet86.fxt', 'CHEET86 Original\n')], self.vehicles,
                   [str(d) for d in self.dest], {}, self.backup, {'cheet86':'OLDKEY'})
        self.assertNotIn('OLDKEY', self.mappings())
        self.assertEqual(len(self.mappings()['NEWKEY']), 1)
        self.assertEqual(len(self.mappings()['KEEP']), 1)

    def test_ide_key_and_custom_key_rename_replace_old_mapping(self):
        self.vehicles[1]['fxt_key'] = 'MYNAME'
        source = self.author('author.fxt', 'ORIGKEY Author Cheetah\n')
        _, keys = self.deploy([source], source_keys={'cheet86':'ORIGKEY'})
        rows = self.mappings()
        self.assertNotIn('ORIGKEY', rows)
        self.assertEqual(rows['MYNAME'], [(self.dest[1] / 'author.fxt', "Cheetah '86")])
        self.assertEqual(keys['cheet86'], 'MYNAME')

    def test_disabled_generation_preserves_author_name_and_does_not_synthesize(self):
        for vehicle in self.vehicles:
            vehicle['generate_fxt'] = False
        self.deploy([self.author('names.fxt', 'CHEET86 Author name\n')])
        self.assertEqual(set(self.mappings()), {'CHEET86'})
        self.assertEqual(self.mappings()['CHEET86'][0][1], 'Author name')

    def test_disabled_generation_with_no_author_leaves_existing_names_untouched(self):
        path = self.dest[1] / 'cheet86.fxt'
        original = b'CHEET86 User existing name\r\n'
        path.write_bytes(original)
        for vehicle in self.vehicles:
            vehicle['generate_fxt'] = False
        changed, _ = self.deploy([])
        self.assertEqual(changed, [])
        self.assertEqual(path.read_bytes(), original)

    def test_localized_names_bom_lowercase_keys_and_duplicate_source_entries(self):
        self.vehicles[1]['fxt_name'] = '猎豹，经典版'
        a = self.author('a.fxt', '\ufeffcheet86 猎豹 原名\n')
        b = self.author('b.fxt', 'CHEET86 Conflicting original\n')
        self.deploy([a, b])
        self.assertEqual(len(self.mappings()['CHEET86']), 1)
        self.assertEqual(self.mappings()['CHEET86'][0][1], '猎豹，经典版')

    def test_same_key_with_conflicting_user_names_fails_before_fxt_writes(self):
        self.vehicles[1]['fxt_key'] = self.vehicles[2]['fxt_key'] = 'SHARED'
        with self.assertRaisesRegex(ValueError, 'Multiple vehicles share FXT key'):
            self.deploy([])
        self.assertEqual(self.mappings(), {})

    def test_failure_during_atomic_write_preserves_existing_file(self):
        path = self.dest[1] / 'cheet86.fxt'
        path.write_text('CHEET86 Existing\n', encoding='utf-8')
        with patch('core.fxt_installer.os.replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                self.deploy([])
        self.assertEqual(path.read_text(), 'CHEET86 Existing\n')

    def test_shared_author_file_named_after_one_vehicle_gives_other_vehicle_its_own_fxt_file(self):
        source = self.author('phoenix.fxt', 'PHOENIX Phoenix\nPHXSHIT Phoenix (Beater)\n')
        vehicles = [
            dict(source_model='phoenix', target_model='phoenix', fxt_key='PHOENIX', fxt_name='Phoenix', category='Modded Cars', generate_fxt=True),
            dict(source_model='phxshit', target_model='phxshit', fxt_key='PHXSHIT', fxt_name='Phoenix (Beater)', category='Addon Cars', addon_id=13000, generate_fxt=True)
        ]
        deploy_fxt([source], vehicles, [str(self.dest[0]), str(self.dest[1])], {}, self.backup)
        self.assertTrue((self.dest[0] / 'phoenix.fxt').exists())
        self.assertEqual((self.dest[0] / 'phoenix.fxt').read_text(encoding='utf-8').strip(), 'PHOENIX Phoenix')
        self.assertTrue((self.dest[1] / 'phxshit.fxt').exists())
        self.assertEqual((self.dest[1] / 'phxshit.fxt').read_text(encoding='utf-8').strip(), 'PHXSHIT Phoenix (Beater)')
        self.assertFalse((self.dest[1] / 'phoenix.fxt').exists())

    def test_reinstall_cleans_up_obsolete_author_named_fxt_in_addon_dir(self):
        (self.dest[0] / 'phoenix.fxt').write_text('PHOENIX Phoenix\n', encoding='utf-8')
        (self.dest[1] / 'phoenix.fxt').write_text('PHXSHIT Old (Beater)\n', encoding='utf-8')
        source = self.author('phoenix.fxt', 'PHOENIX Phoenix\nPHXSHIT Phoenix (Beater)\n')
        vehicles = [
            dict(source_model='phoenix', target_model='phoenix', fxt_key='PHOENIX', fxt_name='Phoenix', category='Modded Cars', generate_fxt=True),
            dict(source_model='phxshit', target_model='phxshit', fxt_key='PHXSHIT', fxt_name='Phoenix (Beater)', category='Addon Cars', addon_id=13000, generate_fxt=True)
        ]
        deploy_fxt([source], vehicles, [str(self.dest[0]), str(self.dest[1])], {}, self.backup)
        self.assertFalse((self.dest[1] / 'phoenix.fxt').exists())
        self.assertTrue((self.dest[1] / 'phxshit.fxt').exists())
        self.assertEqual((self.dest[1] / 'phxshit.fxt').read_text(encoding='utf-8').strip(), 'PHXSHIT Phoenix (Beater)')


class FxtInstallIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'game'
        data = self.game / 'data'
        data.mkdir(parents=True)
        (data / 'vehicles.ide').write_text('cars\n415, cheetah, cheetah, car, CHEETAH, CHEETAH, null, normal, 10, 0, 0, -1, 0.7, 0.7, -1\nend\n')
        for name, content in [('handling.cfg','; empty\n'), ('carcols.dat','car\nend\n'), ('carmods.dat','mods\nend\n')]:
            (data / name).write_text(content)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.backup = BackupManager(str(self.root / 'backups'), str(self.game))
        self.installer = ModInstaller(str(self.game), backup_manager=self.backup)

    def test_install_split_pack_and_sync_custom_keys_in_addon_and_replacement_ide(self):
        models = ['cheetah','cheet86','cheetsp']
        for model in models:
            (self.source / (model + '.dff')).write_bytes(b'dff')
            (self.source / (model + '.fxt')).write_text(model.upper() + ' Author name\n')
        ide = [f'{13000+i}, {model}, {model}, car, {model.upper()}, {model.upper()}, null, normal, 10, 0, 0, -1, 0.7, 0.7, -1' for i,model in enumerate(models[1:])]
        (self.source / 'readme.txt').write_text('vehicles.ide\n' + '\n'.join(ide))
        vehicles = [dict(source_model=m, target_model=m, category='Modded Cars' if i == 0 else 'Addon Cars',
                         folder_name=m, fxt_key='MYGT' if i == 0 else ('MY86' if i == 1 else m.upper()),
                         fxt_name='Custom ' + m, addon_id=13000+i-1 if i else None,
                         merge_fla=False) for i,m in enumerate(models)]
        result = self.installer.execute_install(dict(inspect_dir=str(self.source), folder_name='Pack', vehicles=vehicles))
        self.assertTrue(result['success'], result)
        for vehicle in vehicles:
            dest = self.game / 'modloader' / vehicle['category'] / vehicle['folder_name']
            self.assertEqual(len(list(dest.glob('*.fxt'))), 1)
            self.assertIn(vehicle['fxt_key'] + ' ' + vehicle['fxt_name'], next(dest.glob('*.fxt')).read_text())
        shadow = (self.game / 'modloader' / 'Modded Cars' / 'vehicles.ide').read_text()
        self.assertIn('CHEETAH, MYGT,', shadow)
        self.assertIn('CHEET86, MY86,', shadow)
        self.assertIn('CHEETAH, CHEETAH,', (self.game / 'data' / 'vehicles.ide').read_text())

    def test_install_pack_with_replacement_and_addon_routes_fxt_without_filename_collision(self):
        (self.source / 'phoenix.dff').write_bytes(b'dff')
        (self.source / 'phxshit.dff').write_bytes(b'dff')
        (self.source / 'phoenix.fxt').write_text('PHOENIX Phoenix\nPHXSHIT Phoenix (Beater)\n')
        ide = '13500, phxshit, phxshit, car, PHXSHIT, PHXSHIT, null, normal, 10, 0, 0, -1, 0.7, 0.7, -1'
        (self.source / 'readme.txt').write_text('vehicles.ide\n' + ide)
        vehicles = [
            dict(source_model='phoenix', target_model='phoenix', category='Modded Cars',
                 folder_name='imponte-phoenix', fxt_key='PHOENIX', fxt_name='Phoenix',
                 merge_fla=False),
            dict(source_model='phxshit', target_model='phxshit', category='Addon Cars',
                 folder_name='phoenix beater', fxt_key='PHXSHIT', fxt_name='Phoenix (Beater)',
                 addon_id=13500, merge_fla=False)
        ]
        result = self.installer.execute_install(dict(inspect_dir=str(self.source), folder_name='Pack', vehicles=vehicles))
        self.assertTrue(result['success'], result)
        rep_dest = self.game / 'modloader' / 'Modded Cars' / 'imponte-phoenix'
        addon_dest = self.game / 'modloader' / 'Addon Cars' / 'phoenix beater'
        self.assertTrue((rep_dest / 'phoenix.fxt').exists())
        self.assertIn('PHOENIX Phoenix', (rep_dest / 'phoenix.fxt').read_text())
        self.assertTrue((addon_dest / 'phxshit.fxt').exists())
        self.assertIn('PHXSHIT Phoenix (Beater)', (addon_dest / 'phxshit.fxt').read_text())
        self.assertFalse((addon_dest / 'phoenix.fxt').exists())

    def test_excluded_author_file_is_not_copied_when_generation_disabled(self):
        (self.source / 'cheetah.dff').write_bytes(b'dff')
        (self.source / 'names.fxt').write_text('CHEETAH Author\n')
        result = self.installer.execute_install(dict(inspect_dir=str(self.source), folder_name='Pack',
            target_model='cheetah', generate_fxt=False, excluded_files=['names.fxt'], merge_fla=False))
        self.assertTrue(result['success'], result)
        self.assertEqual(list((self.game / 'modloader').rglob('*.fxt')), [])

    def test_fxt_write_failure_is_reported_as_install_failure(self):
        (self.source / 'cheetah.dff').write_bytes(b'dff')
        with patch('core.installer.deploy_fxt', side_effect=OSError('locked')):
            result = self.installer.execute_install(dict(inspect_dir=str(self.source), folder_name='Pack',
                target_model='cheetah', fxt_key='CHEETAH', fxt_name='My Cheetah', merge_fla=False))
        self.assertFalse(result['success'])
        self.assertIn('FXT', result['error'])


class FxtFileLayoutRegression(unittest.TestCase):
    """
    Rewriting a deployed .fxt must change only the entry it names.

    Real author files are overwhelmingly a single unterminated line, or CRLF
    text with no trailing newline; the previous text-mode write silently added
    a terminator and converted LF to CRLF on Windows.
    """

    LAYOUTS = {
        'unterminated': b'CHEETAH Old Name',
        'crlf_unterminated': b'CHEETAH Old Name\r\nOTHER Keeper',
        'lf_unterminated': b'CHEETAH Old Name\nOTHER Keeper',
        'lf_terminated': b'CHEETAH Old Name\nOTHER Keeper\n',
        'crlf_terminated': b'CHEETAH Old Name\r\nOTHER Keeper\r\n',
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _deploy(self, name, raw, filename='names.fxt'):
        """Deploy into a destination containing exactly one file."""
        dest = self.root / name / 'Modded Cars' / 'Mod'
        dest.mkdir(parents=True)
        target = dest / filename
        target.write_bytes(raw)
        backup = BackupManager(str(self.root / name / 'backups'), str(self.root))
        vehicles = [dict(source_model='cheetah', target_model='cheetah',
                         fxt_key='CHEETAH', fxt_name='Cheetah GT', generate_fxt=True)]
        changed, _ = deploy_fxt([], vehicles, [str(dest)], {}, backup)
        return target, changed

    def test_rewrite_preserves_the_file_layout(self):
        for name, raw in self.LAYOUTS.items():
            with self.subTest(layout=name):
                target, changed = self._deploy(name, raw)
                self.assertEqual(changed, [str(target)])

                after = target.read_bytes()
                self.assertIn(b'CHEETAH Cheetah GT', after)
                self.assertNotIn(b'Old Name', after)
                # Any unrelated entry the layout carried must survive verbatim.
                if b'OTHER Keeper' in raw:
                    self.assertIn(b'OTHER Keeper', after)

                self.assertEqual(after.endswith(b'\n'), raw.endswith(b'\n'),
                                 f'{name}: trailing-newline choice changed')
                self.assertEqual(after.count(b'\r\n'), raw.count(b'\r\n'),
                                 f'{name}: CRLF count changed')
                self.assertEqual(after.count(b'\n'), raw.count(b'\n'),
                                 f'{name}: total newline count changed')

    def test_untouched_file_is_left_completely_alone(self):
        raw = b'CHEETAH Cheetah GT'
        target, changed = self._deploy('nochange', raw, filename='cheetah.fxt')
        self.assertEqual(changed, [])
        self.assertEqual(target.read_bytes(), raw)

    def test_new_file_uses_crlf_and_is_terminated(self):
        dest = self.root / 'fresh' / 'Modded Cars' / 'Mod'
        dest.mkdir(parents=True)
        backup = BackupManager(str(self.root / 'fresh' / 'backups'), str(self.root))
        vehicles = [dict(source_model='cheetah', target_model='cheetah',
                         fxt_key='CHEETAH', fxt_name='Cheetah GT', generate_fxt=True)]
        deploy_fxt([], vehicles, [str(dest)], {}, backup)

        created = dest / 'cheetah.fxt'
        self.assertTrue(created.exists())
        self.assertEqual(created.read_bytes(), b'CHEETAH Cheetah GT\r\n')
