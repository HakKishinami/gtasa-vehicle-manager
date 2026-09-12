import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from core import diagnostics


class DiagnosticsLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(diagnostics, "app_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_records_success_and_failure_newest_first(self):
        self.assertTrue(diagnostics.record_operation("install", {"success": True}, {"folder_name": "ZR150"}))
        self.assertTrue(diagnostics.record_operation("install", {"success": False, "errors": ["locked"]}))
        operations = diagnostics.read_operations()
        self.assertEqual([entry["success"] for entry in operations], [False, True])
        self.assertEqual(operations[0]["errors"], ["locked"])
        self.assertEqual(operations[1]["context"]["folder_name"], "ZR150")
        self.assertEqual(operations[0]["operation"], "install")
        self.assertRegex(operations[0]["timestamp"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_log_keeps_only_the_newest_operations(self):
        for index in range(diagnostics.MAX_OPERATIONS + 5):
            diagnostics.record_operation("install", {"success": True, "error": str(index)})
        operations = diagnostics.read_operations(limit=diagnostics.MAX_OPERATIONS + 10)
        self.assertEqual(len(operations), diagnostics.MAX_OPERATIONS)
        self.assertEqual(operations[0]["error"], str(diagnostics.MAX_OPERATIONS + 4))

    def test_malformed_lines_are_skipped(self):
        path = diagnostics.operations_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"operation": "install", "success": true}\nnot json\n\n', encoding="utf-8")
        self.assertEqual(len(diagnostics.read_operations()), 1)

    def test_list_fields_are_bounded(self):
        errors = [f"error {index}" for index in range(diagnostics.MAX_LIST_FIELDS + 20)]
        diagnostics.record_operation("install", {"success": False, "errors": errors})
        self.assertEqual(len(diagnostics.read_operations()[0]["errors"]), diagnostics.MAX_LIST_FIELDS)

    def test_an_unwritable_log_is_reported_not_raised(self):
        with patch.object(diagnostics, "operations_path", side_effect=OSError("locked")):
            self.assertFalse(diagnostics.record_operation("install", {"success": True}))
        self.assertEqual(diagnostics.read_operations(), [])


class DiagnosticsExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(diagnostics, "app_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bundle_carries_log_manifests_and_settings(self):
        diagnostics.record_operation("apply_merge", {"success": True}, {"mod_dir": "Mod"})
        manifest = diagnostics.manifest_path_for(self.root / "modloader" / "Modded Cars" / "ZR150")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("[]", encoding="utf-8")
        config = self.root / "config.json"
        config.write_text('{"game_path": "E:/Game"}', encoding="utf-8")

        result = diagnostics.export_bundle(config)
        self.assertTrue(result["success"], result)
        self.assertGreater(result["entries"], 2)
        with zipfile.ZipFile(result["path"]) as archive:
            names = archive.namelist()
            self.assertIn("README.txt", names)
            self.assertIn("system.json", names)
            self.assertIn("logs/operations.jsonl", names)
            self.assertIn("config.json", names)
            self.assertIn(f"manifests/{manifest.name}", names)
            self.assertIn("attach this zip", archive.read("README.txt").decode("utf-8").lower())
            self.assertEqual(json.loads(archive.read("logs/operations.jsonl").decode("utf-8"))["operation"],
                             "apply_merge")

    def test_bundle_without_previous_operations_still_exports(self):
        result = diagnostics.export_bundle()
        self.assertTrue(result["success"], result)
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertIn("system.json", archive.namelist())

    def test_system_info_reports_the_python_and_platform(self):
        info = diagnostics.system_info()
        self.assertIn("python", info)
        self.assertIn("platform", info)
        self.assertFalse(info["frozen"])
        self.assertEqual(info["app_root"], str(self.root))


class DiagnosticsEndpointTests(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(diagnostics, "app_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _handler(self, path, body=None):
        handler = object.__new__(self.server.ModManagerHandler)
        handler.path = path
        handler._reject_non_local_request = lambda: False
        captured = []
        handler._send_json = lambda data, status=200: captured.append((data, status))
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            handler.headers = {"Content-Length": str(len(payload))}
            handler.rfile = io.BytesIO(payload)
        return handler, captured

    def test_get_reports_the_folder_and_the_recent_operations(self):
        diagnostics.record_operation("install", {"success": True}, {"folder_name": "ZR150"})
        handler, captured = self._handler("/api/diagnostics?limit=10")
        handler._handle_get()
        data, status = captured[0]
        self.assertEqual(status, 200)
        self.assertEqual(Path(data["dir"]), self.root / "diagnostics")
        self.assertTrue(Path(data["dir"]).is_dir())
        self.assertEqual(data["operations"][0]["context"]["folder_name"], "ZR150")

    def test_export_endpoint_writes_one_attach_and_reports_it(self):
        with patch.object(self.server, "CONFIG_PATH", str(self.root / "config.json")):
            handler, captured = self._handler("/api/diagnostics/export", {})
            handler.do_POST()
        data, status = captured[0]
        self.assertEqual(status, 200)
        self.assertTrue(Path(data["path"]).is_file())
        self.assertGreater(data["size"], 0)

    def test_install_endpoint_records_the_failure_a_user_would_report(self):
        body = {"inspect_dir": "E:/Mod", "folder_name": "ZR150", "target_category": "Modded Cars",
                "excluded_files": ["alt.txt"],
                "vehicles": [{"source_model": "zr150", "target_model": "zr350", "merge_handling": True}]}
        with patch.object(self.server, "installer") as installer:
            installer.execute_install.return_value = {"success": False, "errors": ["locked"]}
            handler, captured = self._handler("/api/installer/install", body)
            handler.do_POST()
        self.assertEqual(captured[0][1], 400)
        entry = diagnostics.read_operations()[0]
        self.assertEqual(entry["operation"], "install")
        self.assertFalse(entry["success"])
        self.assertEqual(entry["errors"], ["locked"])
        self.assertEqual(entry["context"]["folder_name"], "ZR150")
        self.assertEqual(entry["context"]["vehicles"][0]["source_model"], "zr150")
        self.assertEqual(entry["context"]["excluded_files"], ["alt.txt"])

    def test_install_endpoint_records_a_successful_install(self):
        body = {"inspect_dir": "E:/Mod", "folder_name": "ZR150"}
        with patch.object(self.server, "installer") as installer, patch.object(self.server, "id_mgr"):
            installer.execute_install.return_value = {"success": True, "applied_configs": ["handling.cfg"]}
            handler, captured = self._handler("/api/installer/install", body)
            handler.do_POST()
        self.assertEqual(captured[0][1], 200)
        entry = diagnostics.read_operations()[0]
        self.assertTrue(entry["success"])
        self.assertEqual(entry["context"]["folder_name"], "ZR150")

    def test_a_crashing_install_is_recorded_before_it_propagates(self):
        with patch.object(self.server, "installer") as installer:
            installer.execute_install.side_effect = RuntimeError("boom")
            handler, captured = self._handler("/api/installer/install", {"inspect_dir": "E:/Mod"})
            handler.do_POST()
        data, status = captured[0]
        self.assertEqual(status, 500)
        self.assertIn("boom", data["error"])
        self.assertIn("RuntimeError: boom", diagnostics.read_operations()[0]["error"])

    def test_apply_merge_endpoint_records_the_result(self):
        target = self.root / "Modded Cars" / "ZR150"
        target.mkdir(parents=True)
        info = {"success": True, "mod_dir": str(target), "target_model": "zr350", "source_txt_files": []}
        with patch.object(self.server, "parser") as parser, patch.object(self.server, "merger") as merger:
            parser.inspect_mod_directory.return_value = info
            merger.apply_merge.return_value = {"success": True, "applied_files": ["handling.cfg"]}
            handler, captured = self._handler("/api/apply-merge", {"path": str(target)})
            handler.do_POST()
        self.assertEqual(captured[0][1], 200)
        entry = diagnostics.read_operations()[0]
        self.assertEqual(entry["operation"], "apply_merge")
        self.assertTrue(entry["success"])
        self.assertEqual(entry["context"]["target_model"], "zr350")
