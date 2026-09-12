import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import diagnostics
from core import foreign_configs


class ForeignConfigScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"")

    def write(self, relative, content=b"data"):
        path = self.game / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_scan_finds_nested_copies_and_skips_the_shadow_folder(self):
        nested = self.write("modloader/Proper Fixes/Vehicles Config Fix/handling.cfg", b"fix")
        virtual = self.write("modloader/Some Mod/data/vehicles.ide", b"ide")
        ours = self.write("modloader/Modded Cars/handling.cfg", b"ours")
        self.write("modloader/Some Mod/readme.txt", b"text")
        found = {(Path(entry["path"]), entry["state"])
                 for entry in foreign_configs.scan(str(self.game), str(self.shadow))}
        self.assertEqual(found, {(nested, "active"), (virtual, "active")})
        self.assertNotIn(ours, {path for path, _ in found})

    def test_all_watched_names_are_covered(self):
        for name in foreign_configs.WATCHED_FILES:
            self.write(f"modloader/Proper Fixes/{name}", b"x")
        result = foreign_configs.scan_and_disable(str(self.game), str(self.shadow))
        self.assertEqual(sorted(entry["name"] for entry in result["disabled"]),
                         sorted(foreign_configs.WATCHED_FILES))

    def test_scan_skips_hidden_folders(self):
        self.write("modloader/.data/handling.cfg", b"modloader internals")
        found = foreign_configs.scan(str(self.game), str(self.shadow))
        self.assertEqual(found, [])

    def test_scan_skips_symlinks(self):
        target = self.write("modloader/Real Mod/handling.cfg", b"real")
        link = self.game / "modloader" / "Linked Mod" / "handling.cfg"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        found = [entry["path"] for entry in foreign_configs.scan(str(self.game), str(self.shadow))]
        self.assertEqual(found, [str(target)])

    def test_disabling_keeps_the_bytes_and_is_not_repeated(self):
        path = self.write("modloader/Proper Fixes/Vehicles Config Fix/carcols.dat", b"colours")
        first = foreign_configs.scan_and_disable(str(self.game), str(self.shadow))
        self.assertEqual([entry["name"] for entry in first["disabled"]], ["carcols.dat"])
        disabled_path = Path(first["disabled"][0]["disabled_path"])
        self.assertEqual(disabled_path.read_bytes(), b"colours")
        self.assertEqual(disabled_path.name, "carcols.dat.vmm-disabled")
        self.assertFalse(path.exists())

        second = foreign_configs.scan_and_disable(str(self.game), str(self.shadow))
        self.assertEqual(second["disabled"], [])
        self.assertEqual([entry["name"] for entry in second["already_disabled"]],
                         ["carcols.dat.vmm-disabled"])

    def test_an_existing_archive_gets_a_numbered_sibling(self):
        path = self.write("modloader/Mod/veh_mods.ide", b"new")
        (path.parent / "veh_mods.ide.vmm-disabled").write_bytes(b"old")
        result = foreign_configs.scan_and_disable(str(self.game), str(self.shadow))
        self.assertEqual(Path(result["disabled"][0]["disabled_path"]).name, "veh_mods.ide.2.vmm-disabled")
        self.assertEqual((path.parent / "veh_mods.ide.vmm-disabled").read_bytes(), b"old")

    def test_an_unavailable_file_is_reported_instead_of_raising(self):
        result = foreign_configs.disable([{"path": str(self.shadow / "nope.cfg")}])
        self.assertEqual(result["disabled"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("nope.cfg", result["errors"][0]["path"])


class ForeignConfigEndpointTests(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        self.foreign = self.game / "modloader" / "Proper Fixes" / "Vehicles Config Fix"
        self.foreign.mkdir(parents=True)
        self.file = self.foreign / "handling.cfg"
        self.file.write_bytes(b"fix")
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

    def _scan(self):
        with patch.object(self.server, "GAME_PATH", str(self.game)), \
             patch.object(self.server, "shadow_dir", str(self.shadow)), \
             patch.object(self.server, "FOREIGN_CONFIGS_STATE",
                          {"checked": False, "disabled": [], "already_disabled": [], "errors": []}):
            handler, captured = self._handler("/api/foreign-configs/scan", {})
            handler.do_POST()
        return captured[0]

    def test_the_scan_endpoint_disables_competing_copies(self):
        data, status = self._scan()
        self.assertEqual(status, 200)
        self.assertEqual([entry["name"] for entry in data["disabled"]], ["handling.cfg"])
        self.assertFalse(self.file.exists())
        self.assertTrue(Path(data["disabled"][0]["disabled_path"]).is_file())

    def test_the_guard_is_written_to_the_operation_log(self):
        self._scan()
        entry = diagnostics.read_operations()[0]
        self.assertEqual(entry["operation"], "disable_foreign_configs")
        self.assertTrue(entry["success"])
        self.assertEqual(entry["context"]["disabled"], [str(self.file)])

    def test_the_status_endpoint_returns_the_cached_result(self):
        data, _ = self._scan()
        with patch.object(self.server, "FOREIGN_CONFIGS_STATE", data):
            handler, captured = self._handler("/api/foreign-configs")
            handler._handle_get()
        cached, status = captured[0]
        self.assertEqual(status, 200)
        self.assertTrue(cached["checked"])
        self.assertEqual([entry["name"] for entry in cached["disabled"]], ["handling.cfg"])
