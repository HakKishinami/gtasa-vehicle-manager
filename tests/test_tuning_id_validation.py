"""Installer tuning ID regressions; all game and mod files are temporary."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.backup_manager import BackupManager
from core.installer import ModInstaller


class TuningIdValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.source = self.root / "source"
        self.source.mkdir()
        self.write(self.game / "data/maps/veh_mods/veh_mods.ide",
                   "objs\n1000, nto_b_l, vehicle, 70, 0\nend\n")
        self.write(self.game / "data/carmods.dat", "mods\neuros, nto_b_l\nend\n")
        self.write(self.game / "data/shopping.dat",
                   "section prices\nsection CarMods\nend\nend\nsection carmod1\ntype CarMods\nend\n")
        self.write(self.source / "readme.txt", """veh_mods.ide
ID, rf_a_eu, euros, 100, 2097152
ID, rf_c_eu, euros, 100, 2097152
carmods.dat
euros, rf_a_eu, rf_c_eu
""")
        for name in ("euros", "rf_a_eu", "rf_c_eu"):
            (self.source / f"{name}.dff").write_bytes(b"test asset")
        backup = BackupManager(backup_dir=str(self.root / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), backup_manager=backup)
        self.inspect = self.installer.inspect_source(str(self.source))
        self.assertTrue(self.inspect["success"])
        self.params = {
            "inspect_dir": str(self.source), "folder_name": "Euros Test",
            "target_category": "Modded Cars", "target_model": "euros",
            "parsed_config": self.inspect["parsed_config"], "copy_files": True,
            "merge_carmods": True, "generate_fxt": False, "merge_fla": False,
            "tuning_id_assignments": {"rf_a_eu": 11688, "rf_c_eu": 11689},
        }

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def snapshot(self):
        return {str(p.relative_to(self.game)): p.read_bytes() for p in self.game.rglob("*") if p.is_file()}

    def assert_rejected_without_writes(self, params, expected):
        before = self.snapshot()
        result = self.installer.execute_install(params)
        self.assertFalse(result["success"], result)
        self.assertIn(expected, result["error"])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.game / "modloader/Modded Cars/Euros Test").exists())

    def test_duplicate_batch_is_rejected_before_copy_or_merge(self):
        self.params["tuning_id_assignments"]["rf_c_eu"] = 11688
        self.assert_rejected_without_writes(self.params, "11688 is assigned to both rf_a_eu and rf_c_eu")

    def test_invalid_id_formats_are_never_truncated_or_omitted(self):
        for value in ("", "11688.5", 11688.5, 11688.0, "1e4", True, None, -1, 999, 65536):
            with self.subTest(value=value):
                self.params["tuning_id_assignments"]["rf_a_eu"] = value
                self.assert_rejected_without_writes(self.params, "integer between 1000 and 65535")

    def test_unique_ids_install_both_models_and_keep_their_assignments(self):
        result = self.installer.execute_install(self.params)
        self.assertTrue(result["success"], result)
        installed = Path(result["installed_path"])
        self.assertTrue((installed / "rf_a_eu.dff").exists())
        self.assertTrue((installed / "rf_c_eu.dff").exists())
        text = (self.game / "modloader/Modded Cars/veh_mods.ide").read_text(encoding="utf-8-sig")
        self.assertIn("11688, rf_a_eu,", text)
        self.assertIn("11689, rf_c_eu,", text)

    def test_unchecked_duplicate_is_not_copied_or_registered(self):
        self.params["tuning_id_assignments"]["rf_c_eu"] = 11688
        self.params["excluded_tuning_parts"] = ["RF_C_EU"]
        result = self.installer.execute_install(self.params)
        self.assertTrue(result["success"], result)
        self.assertFalse((Path(result["installed_path"]) / "rf_c_eu.dff").exists())
        text = (self.game / "modloader/Modded Cars/veh_mods.ide").read_text(encoding="utf-8-sig")
        self.assertIn("11688, rf_a_eu,", text)
        self.assertNotIn("rf_c_eu", text)

    def test_fresh_scan_catches_an_id_occupied_since_inspection(self):
        self.installer.id_mgr.scan_all_ides()
        self.write(self.game / "modloader/Map Mod/objects.ide",
                   "objs\n11688, map_object, generic, 100, 0\nend\n")
        self.assert_rejected_without_writes(self.params, "already used by map_object")

    def test_unavailable_scan_fails_closed_without_copying(self):
        with patch.object(self.installer.id_mgr, "scan_all_ides", side_effect=OSError("unavailable")):
            self.assert_rejected_without_writes(self.params, "Unable to verify tuning IDs")

    def test_cross_vehicle_duplicate_is_rejected(self):
        self.params.pop("tuning_id_assignments")
        self.params["vehicles"] = [
            {"target_model": "euros", "tuning_id_assignments": {"rf_a_eu": 11688}},
            {"target_model": "elegy", "tuning_id_assignments": {"rf_c_eu": 11688}},
        ]
        self.assert_rejected_without_writes(self.params, "assigned to both")

    def test_skipped_vehicle_and_shared_parts_do_not_create_false_duplicates(self):
        vehicles = [
            {"target_model": "euros", "tuning_id_assignments": {"rf_a_eu": "11688"}},
            {"target_model": "elegy", "tuning_id_assignments": {"RF_A_EU": 11688}},
            {"target_model": "sentinel", "skip": True, "tuning_id_assignments": {"other_part": 11688}},
        ]
        self.params["vehicles"] = vehicles
        self.params["tuning_id_assignments"] = {"rf_a_eu": 11688, "rf_c_eu": 11689}
        # The execute path must pass only active vehicles into validation.
        original = self.installer._validate_requested_tuning_ids
        checked = []
        def validate(params, active):
            checked.extend(active)
            result = original(params, active)
            self.assertTrue(result["success"], result)
            self.assertEqual(result["assignments"], {"rf_a_eu": 11688, "rf_c_eu": 11689})
            return {"success": False, "error": "stop after validation"}
        with patch.object(self.installer, "_validate_requested_tuning_ids", side_effect=validate):
            self.assert_rejected_without_writes(self.params, "stop after validation")
        self.assertEqual(len(checked), 2)

    def test_tuning_id_cannot_reuse_a_requested_addon_vehicle_id(self):
        self.params["addon_id_assignments"] = {"newcar": 11688}
        self.assert_rejected_without_writes(self.params, "also assigned to addon vehicle newcar")

    def test_registered_part_keeps_existing_id_and_does_not_take_a_custom_id(self):
        result = self.installer._validate_requested_tuning_ids(
            {"tuning_id_assignments": {"nto_b_l": 11688, "rf_a_eu": "11688"}}, [])
        self.assertTrue(result["success"], result)
        self.assertEqual(result["assignments"], {"rf_a_eu": 11688})

    def test_same_model_at_existing_id_can_be_reinstalled(self):
        self.write(self.game / "modloader/Previous Mod/parts.ide",
                   "objs\n11688, rf_a_eu, euros, 100, 2097152\nend\n")
        result = self.installer._validate_requested_tuning_ids(self.params, [])
        self.assertTrue(result["success"], result)

    def test_merger_rejects_duplicate_instead_of_silently_skipping_second_part(self):
        path = self.game / "modloader/Modded Cars/veh_mods.ide"
        self.write(path, "objs\n1000, nto_b_l, vehicle, 70, 0\nend\n")
        before = path.read_bytes()
        actions = [
            {"part": part, "id": 11688, "line": f"11688, {part}, euros, 100, 2097152"}
            for part in ("rf_a_eu", "rf_c_eu")
        ]
        result = self.installer.merger._merge_veh_mods(actions)
        self.assertFalse(result["success"], result)
        self.assertIn("assigned to both", result["error"])
        self.assertEqual(path.read_bytes(), before)

    def test_merger_rejects_id_already_owned_by_another_model(self):
        path = self.game / "modloader/Modded Cars/veh_mods.ide"
        self.write(path, "objs\n11688, other_part, euros, 100, 2097152\nend\n")
        before = path.read_bytes()
        result = self.installer.merger._merge_veh_mods([
            {"part": "rf_a_eu", "id": 11688, "line": "11688, rf_a_eu, euros, 100, 2097152"}
        ])
        self.assertFalse(result["success"], result)
        self.assertEqual(path.read_bytes(), before)

    def test_duplicate_merge_rolls_back_carmods_and_shopping_changes(self):
        shadow = self.game / "modloader/Modded Cars"
        for relative in ("carmods.dat", "shopping.dat"):
            self.write(shadow / relative, (self.game / "data" / relative).read_text(encoding="utf-8"))
        self.write(shadow / "veh_mods.ide", "objs\n1000, nto_b_l, vehicle, 70, 0\nend\n")
        before = self.snapshot()
        result = self.installer.merger.apply_merge({
            "target_model": "euros", "files": {},
            "parsed": {
                "carmods": [{"model": "euros", "part_names": ["rf_a_eu", "rf_c_eu"]}],
                "handling": [], "carcols": [], "ide": [],
            },
            "custom_tuning_ids": {"rf_a_eu": 11688, "rf_c_eu": 11688},
        })
        self.assertFalse(result["success"], result)
        self.assertTrue(any("assigned to both" in error for error in result["errors"]), result)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
