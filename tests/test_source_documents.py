import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import test_regressions as fixtures
from core import diagnostics
from core.parser import DualTrackParser
from core.scanner import ModScanner
from core.source_documents import (
    archive_used_sources, list_source_documents, read_source_document,
    LEGACY_MANIFEST_NAME, MAX_PREVIEW_BYTES,
)


class ArchiveOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(diagnostics, "app_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lossless_mixed_encoding_and_existing_archive(self):
        path = self.root / "readme.txt"
        original = "作者致谢\r\ncarcols.dat\r\nalpha, 42, 42\r\n".encode("utf-16")
        path.write_bytes(original)
        old_archive = self.root / "readme.txt.used_source"
        old_archive.write_bytes(b"previous version")
        result = archive_used_sources([str(path)])
        self.assertTrue(result["success"], result)
        self.assertEqual(old_archive.read_bytes(), b"previous version")
        archived = self.root / "readme.txt.2.used_source"
        self.assertEqual(archived.read_bytes(), original)
        self.assertFalse(path.exists())
        preview = read_source_document(self.root, archived.name)
        self.assertTrue(preview["success"])
        self.assertIn("作者致谢", preview["content"])
        self.assertTrue(all(d["archived"] for d in list_source_documents(self.root)))

    def test_rename_failure_restores_entire_batch(self):
        first, second = self.root / "first.txt", self.root / "second.txt"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        original_rename = Path.rename
        def rename(path, target):
            if path == second:
                raise PermissionError("locked")
            return original_rename(path, target)
        with patch.object(Path, "rename", rename):
            result = archive_used_sources([first, second])
        self.assertFalse(result["success"])
        self.assertEqual(first.read_bytes(), b"first")
        self.assertEqual(second.read_bytes(), b"second")
        self.assertEqual(list(self.root.glob("*.used_source")), [])
        self.assertFalse(diagnostics.manifest_path_for(self.root).exists())

    def test_manifest_lives_beside_the_application_not_in_the_mod_folder(self):
        path = self.root / "readme.txt"
        path.write_bytes(b"credits")
        result = archive_used_sources([str(path)])
        self.assertTrue(result["success"], result)
        records = json.loads(diagnostics.manifest_path_for(self.root).read_text(encoding="utf-8"))
        self.assertEqual(records[0]["mod_dir"], str(self.root))
        self.assertEqual([p.name for p in self.root.iterdir() if p.is_file()], ["readme.txt.used_source"])

    def test_legacy_manifest_inside_the_mod_folder_is_migrated_then_removed(self):
        legacy = self.root / LEGACY_MANIFEST_NAME
        legacy.write_text(json.dumps([{"original": "old.txt", "archive": "old.txt.used_source",
                                       "status": "processed", "context": {}}]), encoding="utf-8")
        (self.root / "readme.txt").write_bytes(b"credits")
        result = archive_used_sources([str(self.root / "readme.txt")])
        self.assertTrue(result["success"], result)
        self.assertFalse(legacy.exists())
        records = json.loads(diagnostics.manifest_path_for(self.root).read_text(encoding="utf-8"))
        self.assertEqual([record["original"] for record in records], ["old.txt", "readme.txt"])

    def test_manifest_failure_restores_files(self):
        source = self.root / "readme.txt"
        source.write_bytes(b"credits")
        with patch("core.source_documents.write_text_atomic", side_effect=PermissionError("locked")):
            result = archive_used_sources([source])
        self.assertFalse(result["success"])
        self.assertEqual(source.read_bytes(), b"credits")
        self.assertFalse((self.root / "readme.txt.used_source").exists())

    def test_viewer_rejects_traversal_and_unlisted_files(self):
        (self.root / "private.json").write_text("secret")
        self.assertFalse(read_source_document(self.root, "private.json")["success"])
        self.assertFalse(read_source_document(self.root, "../outside.txt")["success"])

    def test_long_document_is_bounded_and_explicitly_marked(self):
        source = self.root / "large.txt.used_source"
        source.write_bytes(b"x" * (MAX_PREVIEW_BYTES + 10))
        result = read_source_document(self.root, source.name)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["content"]), MAX_PREVIEW_BYTES)


class InstallSourceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AddonToReplaceConversionRegression()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.dest = self.fixture.shadow / "RecursionGT"
        patcher = patch.object(diagnostics, "app_root", return_value=self.fixture.game)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_success_preserves_author_bytes_and_deployed_badges(self):
        f = self.fixture
        original = (f.source / "readme.txt").read_bytes()
        credits = b"Special Thanks\r\nCredits: <script>alert(1)</script>\r\n"
        (f.source / "credits.txt").write_bytes(credits)
        result = f.installer.execute_install(f.payload())
        self.assertTrue(result["success"], result)
        self.assertEqual((self.dest / "readme.txt.used_source").read_bytes(), original)
        self.assertEqual((self.dest / "credits.txt.used_source").read_bytes(), credits)
        self.assertEqual((f.source / "readme.txt").read_bytes(), original)
        self.assertFalse((self.dest / "readme.txt").exists())
        self.assertIn("readme.txt.used_source", result["copied_files"])
        parsed = DualTrackParser().inspect_mod_directory(str(self.dest))
        self.assertEqual(parsed["target_models"], ["alpha"])
        self.assertEqual(parsed["parsed"]["handling"], [])
        self.assertEqual(parsed["parsed"]["carcols"], [])
        mod = ModScanner(str(f.shadow), str(f.game)).scan_installed_mods()[0]
        self.assertTrue(mod["has_handling"])
        self.assertTrue(mod["has_carcols"])
        self.assertTrue(mod["has_carmods"])
        self.assertNotIn("recurs", mod["target_models"])

    def test_deselected_options_are_archived_without_being_applied(self):
        f = self.fixture
        result = f.installer.execute_install(f.payload(merge_handling=False, merge_carcols=False, merge_carmods=False))
        self.assertTrue(result["success"], result)
        self.assertTrue((self.dest / "readme.txt.used_source").exists())
        active = f.installer.merger.get_vehicle_active_configs("alpha")
        self.assertNotIn("9999.0", active["handling"]["raw"])
        self.assertNotIn("42", active["carcols"]["raw"])
        records = json.loads(diagnostics.manifest_path_for(self.dest).read_text(encoding="utf-8"))
        self.assertFalse(records[0]["context"]["vehicles"][0]["merge_handling"])
        self.assertEqual(records[0]["status"], "processed")
        self.assertFalse((self.dest / LEGACY_MANIFEST_NAME).exists())

    def test_failed_merge_keeps_original_txt(self):
        f = self.fixture
        with patch.object(f.installer.merger, "apply_merge", return_value={"success": False, "errors": ["locked"]}):
            result = f.installer.execute_install(f.payload())
        self.assertFalse(result["success"])
        self.assertTrue((self.dest / "readme.txt").exists())
        self.assertFalse((self.dest / "readme.txt.used_source").exists())

    def test_failed_final_ide_write_does_not_archive(self):
        f = self.fixture
        with patch.object(f.installer.merger, "save_vehicle_config", return_value={"success": False, "error": "locked"}):
            result = f.installer.execute_install(f.payload(fxt_key="ALPHA"))
        self.assertFalse(result["success"])
        self.assertTrue((self.dest / "readme.txt").exists())

    def test_unrelated_existing_txt_and_excluded_sources_are_untouched(self):
        f = self.fixture
        self.dest.mkdir(parents=True)
        unrelated = self.dest / "user-notes.txt"
        unrelated.write_bytes(b"My notes")
        (f.source / "excluded.txt").write_bytes(b"Author alternate settings")
        payload = f.payload()
        payload["excluded_files"] = ["excluded.txt"]
        result = f.installer.execute_install(payload)
        self.assertTrue(result["success"], result)
        self.assertEqual(unrelated.read_bytes(), b"My notes")
        self.assertFalse((self.dest / "excluded.txt.used_source").exists())
        self.assertFalse((self.dest / "excluded.txt").exists())

    def test_reinstall_keeps_previous_archive(self):
        f = self.fixture
        first = f.installer.execute_install(f.payload())
        self.assertTrue(first["success"], first)
        old = (self.dest / "readme.txt.used_source").read_bytes()
        with (f.source / "readme.txt").open("a", encoding="utf-8") as stream:
            stream.write("\nUpdated author notes\n")
        second = f.installer.execute_install(f.payload())
        self.assertTrue(second["success"], second)
        self.assertEqual((self.dest / "readme.txt.used_source").read_bytes(), old)
        self.assertIn(b"Updated author notes", (self.dest / "readme.txt.2.used_source").read_bytes())

    def test_document_endpoint_returns_archive_and_rejects_outside_root(self):
        import server
        f = self.fixture
        self.assertTrue(f.installer.execute_install(f.payload())["success"])
        def request(root, document):
            handler = object.__new__(server.ModManagerHandler)
            handler.path = "/api/mod-document?" + urlencode({"full_path": str(root), "document": document})
            handler._reject_non_local_request = lambda: False
            captured = []
            handler._send_json = lambda data, status=200: captured.append((data, status))
            with patch.object(server, "GAME_PATH", str(f.game)):
                handler._handle_get()
            return captured[0]
        data, status = request(self.dest, "readme.txt.used_source")
        self.assertEqual(status, 200)
        self.assertIn("RECURS", data["content"])
        self.assertEqual(request(f.source, "readme.txt")[1], 404)
        self.assertEqual(request(self.dest, "../../../data/handling.cfg")[1], 404)

    def test_archived_presets_never_reenter_apply_merge(self):
        f = self.fixture
        self.assertTrue(f.installer.execute_install(f.payload())["success"])
        active_file = f.shadow / "handling.cfg"
        active_file.write_text(active_file.read_text().replace("9999.0", "8888.0"))
        info = DualTrackParser().inspect_mod_directory(str(self.dest))
        result = f.installer.merger.apply_merge(info)
        self.assertTrue(result["success"], result)
        self.assertIn("8888.0", active_file.read_text())
        self.assertNotIn("9999.0", active_file.read_text())
