"""
Unit tests for Data Copies browsing, reading, saving, and API endpoints.
"""

import os
import shutil
import tempfile
import unittest
from core.baseline import BaselineManager
from core.backup_manager import BackupManager


class TestDataCopies(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.game_path = os.path.join(self.test_dir, "game")
        os.makedirs(self.game_path, exist_ok=True)

        # Create dummy gta_sa.exe
        with open(os.path.join(self.game_path, "gta_sa.exe"), "wb") as f:
            f.write(b"EXE")

        # Create vanilla data/
        self.data_dir = os.path.join(self.game_path, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        with open(os.path.join(self.data_dir, "vehicles.ide"), "w", encoding="utf-8") as f:
            f.write("# Vanilla vehicles.ide\ncars\n400, landstal, landstal, car, LANDSTAL\nend\n")
        with open(os.path.join(self.data_dir, "handling.cfg"), "w", encoding="utf-8") as f:
            f.write("; Vanilla handling\nLANDSTAL 1700.0 4000.0 2.2 0.0 0.0 -0.1 70 0.75\n")

        # Create modloader folders
        self.modloader_dir = os.path.join(self.game_path, "modloader")
        self.modded_dir = os.path.join(self.modloader_dir, "Modded Cars")
        self.addon_dir = os.path.join(self.modloader_dir, "Addon Cars")
        os.makedirs(self.modded_dir, exist_ok=True)
        os.makedirs(self.addon_dir, exist_ok=True)

        # Populate a shadow copy in Modded Cars
        with open(os.path.join(self.modded_dir, "vehicles.ide"), "w", encoding="utf-8") as f:
            f.write("# Shadow vehicles.ide\ncars\n400, landstal, landstal, car, LANDSTAL\n411, infernus, infernus, car, INFERNUS\nend\n")

        # Create backup manager and baseline manager
        self.backup_mgr = BackupManager(game_dir=self.game_path)
        self.mgr = BaselineManager(game_path=self.game_path, data_folder="Modded Cars", backup_manager=self.backup_mgr)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_data_copies_list(self):
        res = self.mgr.get_data_copies_list()
        self.assertTrue(res["valid"])
        self.assertEqual(res["default_folder"], "Modded Cars")

        folders = {f["id"]: f for f in res["folders"]}
        self.assertIn("Modded Cars", folders)
        self.assertIn("Addon Cars", folders)
        self.assertIn("vanilla", folders)

        # Vanilla folder checks
        vanilla = folders["vanilla"]
        self.assertTrue(vanilla["is_vanilla"])
        v_files = {f["name"]: f for f in vanilla["files"]}
        self.assertIn("vehicles.ide", v_files)
        self.assertTrue(v_files["vehicles.ide"]["exists"])
        self.assertGreater(v_files["vehicles.ide"]["size"], 0)

        # Shadow folder checks
        shadow = folders["Modded Cars"]
        self.assertFalse(shadow["is_vanilla"])
        s_files = {f["name"]: f for f in shadow["files"]}
        self.assertTrue(s_files["vehicles.ide"]["exists"])
        self.assertFalse(s_files["carcols.dat"]["exists"])

    def test_read_data_file_vanilla(self):
        res = self.mgr.read_data_file("vanilla", "vehicles.ide")
        self.assertTrue(res["success"])
        self.assertTrue(res["is_vanilla"])
        self.assertTrue(res["is_readonly"])
        self.assertIn("Vanilla vehicles.ide", res["content"])
        self.assertEqual(res["lines"], 4)

    def test_read_data_file_shadow(self):
        res = self.mgr.read_data_file("Modded Cars", "vehicles.ide")
        self.assertTrue(res["success"])
        self.assertFalse(res["is_vanilla"])
        self.assertFalse(res["is_readonly"])
        self.assertIn("Shadow vehicles.ide", res["content"])
        self.assertIn("infernus", res["content"])
        self.assertEqual(res["lines"], 5)

    def test_read_nonexistent_file(self):
        res = self.mgr.read_data_file("Modded Cars", "nonexistent.dat")
        self.assertFalse(res["success"])
        self.assertIn("File does not exist", res["error"])

    def test_save_data_file_strictly_blocks_vanilla(self):
        res = self.mgr.save_data_file("vanilla", "vehicles.ide", "Attempt to overwrite vanilla!")
        self.assertFalse(res["success"])
        self.assertIn("Vanilla data files are strictly protected", res["error"])

        # Verify vanilla file content is completely intact
        with open(os.path.join(self.data_dir, "vehicles.ide"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Vanilla vehicles.ide", content)

    def test_save_data_file_creates_backup_and_writes_atomically(self):
        new_content = "# Updated shadow copy\ncars\n400, landstal, landstal, car, LANDSTAL\nend\n"
        res = self.mgr.save_data_file("Modded Cars", "vehicles.ide", new_content)
        self.assertTrue(res["success"])
        self.assertTrue(res["backup_created"])
        self.assertTrue(os.path.exists(res["backup_created"]))

        # Verify file was written
        target_path = os.path.join(self.modded_dir, "vehicles.ide")
        with open(target_path, "rb") as f:
            data = f.read()
        self.assertNotIn(b"\xef\xbb\xbf", data)  # NO UTF-8 BOM
        self.assertIn(b"\r\n", data)  # Standard CRLF line endings
        self.assertIn(b"Updated shadow copy", data)

    def test_save_disallowed_file_extension(self):
        res = self.mgr.save_data_file("Modded Cars", "evil.exe", "malicious payload")
        self.assertFalse(res["success"])
        self.assertIn("Invalid or disallowed file type", res["error"])

    def test_save_new_config_file_in_addon_folder(self):
        content = "; Addon car handling\nADDONCAR 1500.0 3000.0 2.0 0.0 0.0 0.0 70 0.8\n"
        res = self.mgr.save_data_file("Addon Cars", "handling.cfg", content)
        self.assertTrue(res["success"])
        addon_handling = os.path.join(self.addon_dir, "handling.cfg")
        self.assertTrue(os.path.exists(addon_handling))
        with open(addon_handling, "r", encoding="utf-8") as f:
            self.assertIn("Addon car handling", f.read())


if __name__ == "__main__":
    unittest.main()
