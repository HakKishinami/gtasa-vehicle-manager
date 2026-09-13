import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, os.environ.get("TEST_PROJECT", str(ROOT if (ROOT / "core").is_dir() else ROOT.parent)))
# Installs write an operation log and source manifests; keep them out of the
# working copy for the whole test run.
os.environ.setdefault("VMM_DIAGNOSTICS_ROOT", str(Path(tempfile.gettempdir()) / "vmm-test-diagnostics"))
from core.fla_manager import FLAManager
from core.installer import ModInstaller
from core.merger import ConfigMerger
from core.parser import DualTrackParser
from core.cleaner import ModCleaner
from core.backup_manager import BackupManager
from core.atomic_io import write_text_atomic
from core.seven_zip import extract_with_7zip, EXTRACT_TIMEOUT_SECONDS
from core import fxt_installer
from core.fxt_installer import update_fxt_entry
from core.parser import detect_text_encoding, has_private_use, read_text_file_safe
from core.mod_renamer import rename_mod_folder, validate_mod_folder_name
from core.scanner import ModScanner
from core.tuning_manager import TuningManager
from core.id_manager import IdManager
from core.vanilla_data import VANILLA_AUDIO_SETTINGS


def audio(model, bank=99):
    return FLAManager.format_audio_line(model, f"{model} 0 {bank} 98 0 0.85 1.0 5 0.943874 2 0 3 0 0 0")


def ide(model, mid):
    return f"{mid}, {model}, {model}, car, RANCHER, {model.upper()}, null, normal, 10, 0, 0, -1, 0.7, 0.7, -1"


def handling(ident):
    return (f"{ident}     1500.0    5348.3   2.8    0.0 \t0.2  -0.1  \t85  0.60 0.80 0.50 \t5 140.0 15.0 15.0 \tR P "
            f"\t4.8   0.6  0 30.0  \t1.4  0.1   0.0   0.35 -0.15 0.55 0.0\t\t0.2  0.75 31000 \t20\t\t0\t\t1  3\t0")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="regression_", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        self.path = self.game / "data" / "gtasa_vehicleAudioSettings.cfg"
        self.backup_dir = Path(self.temp.name) / "backups"
        self.backup_manager = BackupManager(backup_dir=str(self.backup_dir), game_dir=str(self.game))
        self.manager = FLAManager(str(self.game), backup_manager=self.backup_manager)

    def backups(self):
        # Ensure game directory is NEVER polluted with .bak_* files
        self.assertEqual(len(list(self.path.parent.glob(self.path.name + ".bak_*"))), 0)
        return sorted(self.backup_dir.glob("**/" + self.path.name))


class AudioRegression(Fixture):
    def test_two_separator_lines_and_missing_final_newline(self):
        original = b"; header\r\n;\r\n;\r\n;the end"
        self.path.write_bytes(original)
        self.assertTrue(self.manager.update_audio_setting("ranchxlt", audio("ranchxlt")))
        expected = b"; header\r\n" + audio("ranchxlt").encode() + b"\r\n;\r\n;\r\n;the end"
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.backups()[0].read_bytes(), original)

    def test_repair_screenshot_glued_and_trailing_rows(self):
        original = ("; header\n;\n;\n;the end" + audio("ranchxlt", 80) + "\n"
                    + audio("rancher") + "\n" + audio("ranchxlt") + "\n"
                    + audio("agitator") + "\n; keep this note\n")
        self.path.write_text(original, encoding="utf-8")
        self.assertTrue(self.manager.update_audio_setting("ranchxlt", audio("ranchxlt")))
        result = self.path.read_text(encoding="utf-8")
        self.assertNotIn(";the endranchxlt", result)
        self.assertEqual(result.count(audio("ranchxlt")), 1)
        for model in ("ranchxlt", "rancher", "agitator"):
            self.assertLess(result.index(audio(model)), result.index(";\n;\n;the end"))
        self.assertIn("; keep this note", result)

    def test_batch_has_one_backup_and_repeat_is_byte_identical(self):
        self.path.write_bytes(b"; header\n;\n;\n;the end\n")
        rows = [(name, audio(name)) for name in ("ranchxlt", "rancher", "agitator")]
        self.assertTrue(self.manager.update_audio_settings(rows))
        self.assertEqual(len(self.backups()), 1)
        result = self.path.read_bytes()
        self.assertTrue(self.manager.update_audio_settings(rows))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.path.read_bytes(), result)

    def test_equal_tokens_preserve_alignment_bom_and_comment_encoding(self):
        original = b"\xef\xbb\xbf; comment \xff\r\n" + audio("rancher").replace(" ", "\t  ").encode() + b"\r\n;\r\n;\r\n;the end"
        self.path.write_bytes(original)
        self.assertTrue(self.manager.update_audio_setting("rancher", audio("rancher")))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.backups(), [])

    def test_update_existing_row_and_deduplicate(self):
        self.path.write_text(audio("rancher", 70) + "\n" + audio("rancher", 80) + "\n;\n;\n;the end", encoding="utf-8")
        self.assertTrue(self.manager.update_audio_setting("rancher", audio("rancher")))
        result = self.path.read_text(encoding="utf-8")
        self.assertEqual(result.count("rancher"), 1)
        self.assertTrue(result.startswith(audio("rancher")))

    def test_markerless_no_newline_does_not_glue_rows(self):
        self.path.write_bytes(audio("rancher").encode())
        self.assertTrue(self.manager.update_audio_setting("ranchxlt", audio("ranchxlt")))
        self.assertEqual(self.path.read_text().splitlines(), [audio("rancher"), audio("ranchxlt")])

    def test_missing_file_created_with_trailer_and_no_empty_backup(self):
        self.assertTrue(self.manager.update_audio_setting("rancher", audio("rancher")))
        self.assertIn(audio("rancher") + "\n;\n;\n;the end", self.path.read_text())
        self.assertEqual(self.backups(), [])

    def test_invalid_model_or_multiline_does_not_write(self):
        self.assertFalse(self.manager.update_audio_setting("rancher", audio("ranchxlt")))
        self.assertFalse(self.manager.update_audio_setting("rancher", audio("rancher") + "\n" + audio("other")))
        self.assertFalse(self.path.exists())

    def test_empty_batch_is_noop(self):
        self.assertTrue(self.manager.update_audio_settings([]))
        self.assertFalse(self.path.exists())

    def test_removing_absent_row_has_no_backup(self):
        original = b"; header\n;\n;\n;the end"
        self.path.write_bytes(original)
        self.assertTrue(self.manager.remove_audio_setting("absent"))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.backups(), [])

    def test_batch_remove_repairs_glued_and_tail_rows(self):
        self.path.write_text("; header\n;\n;\n;the end" + audio("ranchxlt") + "\n" + audio("agitator") + "\n", encoding="utf-8")
        self.assertTrue(self.manager.remove_audio_settings(["ranchxlt", "agitator"]))
        result = self.path.read_text()
        self.assertNotIn("ranchxlt", result)
        self.assertNotIn("agitator", result)
        self.assertEqual(len(self.backups()), 1)

    def test_atomic_replace_failure_preserves_original(self):
        original = b"; header\n;\n;\n;the end"
        self.path.write_bytes(original)
        with patch("core.fla_manager.os.replace", side_effect=OSError("test write failure")):
            self.assertFalse(self.manager.update_audio_setting("rancher", audio("rancher")))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.path.parent.glob(".vehicle_audio_*.tmp")))

    def test_audio_line_alignment_matches_standard_header(self):
        line = FLAManager.format_audio_line("copcarru", "copcarru 0 87 86 0 0.7 1.0 7 1.05946 2 0 13 3 38 0.0")
        self.assertEqual(line.index("0 "), 44)
        tokens = line.split()
        self.assertEqual(tokens[0], "copcarru")
        self.assertEqual(tokens[1], "0")
        self.assertEqual(tokens[2], "87")
        self.assertEqual(tokens[14], "0.0")
        line2 = FLAManager.format_audio_line("fbiprem", "0 87 86 0 0.7 1.0 7 1.05946 2 0 13 3 38 0.0")
        self.assertEqual(line2.index("0 "), 44)
        self.assertEqual(line2.split()[0], "fbiprem")



class InstallRegression(Fixture):
    def setUp(self):
        super().setUp()
        self.native = "# original\ncars\n" + ide("rancher", 489) + "\nend\n"
        (self.game / "data" / "vehicles.ide").write_text(self.native, encoding="utf-8")
        self.path.write_text("; audio header\n;\n;\n;the end", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        self.source = Path(self.temp.name) / "source"
        self.source.mkdir()
        for name in ("rancher", "ranchxlt", "agitator"):
            (self.source / (name + ".dff")).write_bytes(b"test model asset")
        (self.source / "vehicles.ide").write_text("cars\n" + ide("ranchxlt", 12093) + "\n" + ide("agitator", 12094) + "\nend\n", encoding="utf-8")
        (self.source / "readme.txt").write_text("\n".join(audio(n) for n in ("rancher", "ranchxlt", "agitator")), encoding="utf-8")
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup_manager)

    def payload(self):
        return {"inspect_dir": str(self.source), "target_category": "Addon Cars",
                "folder_name": "Pack", "vehicles": [
                    {"source_model": "rancher", "target_model": "rancher", "category": "Modded Cars", "generate_fxt": False},
                    {"source_model": "ranchxlt", "target_model": "ranchxlt", "category": "Addon Cars", "addon_id": 12093, "generate_fxt": False},
                    {"source_model": "agitator", "target_model": "agitator", "category": "Addon Cars", "addon_id": 12094, "generate_fxt": False}]}

    def test_mixed_install_only_one_active_ide_in_shared_directory(self):
        result = self.installer.execute_install(self.payload())
        self.assertTrue(result["success"], result)
        active = list((self.game / "modloader").rglob("vehicles.ide"))
        self.assertEqual(active, [self.shadow / "vehicles.ide"])
        text = active[0].read_text()
        self.assertIn(ide("ranchxlt", 12093), text)
        self.assertIn(ide("agitator", 12094), text)
        self.assertIn(ide("rancher", 489), text)
        self.assertEqual((self.game / "data" / "vehicles.ide").read_text(), self.native)
        self.assertEqual(self.installer.data_folder, "Modded Cars")
        self.assertTrue((self.game / "modloader" / "Addon Cars" / "Pack" / "ranchxlt.dff").is_file())
        self.assertEqual(len(self.backups()), 1)
        self.assertTrue(self.installer.execute_install(self.payload())["success"])
        self.assertEqual(len(self.backups()), 1)

    def test_source_ide_is_available_in_preflight_and_installed_inspection(self):
        inspection = self.installer.inspect_source(str(self.source))
        self.assertTrue(inspection["parsed_config"]["vehicles_ide"])
        self.assertTrue(self.installer.execute_install(self.payload())["success"])
        sources = list((self.game / "modloader").rglob("vehicles.ide.source"))
        self.assertEqual(len(sources), 1)
        detail = DualTrackParser().inspect_mod_directory(str(sources[0].parent))
        self.assertIn("ranchxlt", [r["model_name"] for r in detail["parsed"]["ide"]])

    def test_fla_applies_only_selected_enabled_vehicles_and_renames(self):
        params = self.payload()
        params["vehicles"][0]["target_model"] = "landstal"
        params["vehicles"][1]["merge_fla"] = False
        params["vehicles"][2]["skip"] = True
        result = self.installer.execute_install(params)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.manager.get_all_audio_settings(), {"landstal": audio("landstal")})

    def test_custom_shared_directory_survives_consecutive_category_changes(self):
        self.installer.set_data_folder("Shared Config")
        params = self.payload()
        self.assertTrue(self.installer.execute_install(params)["success"])
        params["target_category"] = "Other Assets"
        self.assertTrue(self.installer.execute_install(params)["success"])
        active = list((self.game / "modloader").rglob("vehicles.ide"))
        self.assertEqual(active, [self.game / "modloader" / "Shared Config" / "vehicles.ide"])
        self.assertEqual(self.installer.data_folder, "Shared Config")

    def test_audio_failure_is_not_reported_as_install_success(self):
        with patch.object(FLAManager, "update_audio_settings", return_value=False):
            result = self.installer.execute_install(self.payload())
        self.assertFalse(result["success"])
        self.assertTrue(result["errors"])

    def test_uninstall_batch_creates_one_audio_backup(self):
        self.assertTrue(self.installer.execute_install(self.payload())["success"])
        before = len(self.backups())
        cleaner = ModCleaner(str(self.game), "Modded Cars", backup_manager=self.backup_manager)
        result = cleaner.delete_mod(str(self.game / "modloader" / "Addon Cars" / "Pack"), "ranchxlt,agitator")
        self.assertTrue(result["success"], result)
        self.assertEqual(len(self.backups()), before + 1)
        self.assertEqual(self.manager.get_all_audio_settings(), {"rancher": audio("rancher")})

    def test_vanilla_tuning_parts_not_added_to_veh_mods_ide(self):
        # Create a mock vanilla veh_mods.ide in game/data/maps/veh_mods
        vm_dir = self.game / "data" / "maps" / "veh_mods"
        vm_dir.mkdir(parents=True, exist_ok=True)
        vanilla_vm = "objs\n1005, bnt_b_sc_l, vehicle, 70, 0\n1008, nto_b_l, vehicle, 70, 0\nend\n"
        (vm_dir / "veh_mods.ide").write_text(vanilla_vm, encoding="utf-8")

        # Mod source that only references vanilla tuning parts in carmods
        mod_src = Path(self.temp.name) / "premier_pack"
        mod_src.mkdir()
        (mod_src / "premier.dff").write_bytes(b"test dff")
        (mod_src / "carmods.dat").write_text("premier, bnt_b_sc_l, nto_b_l\ntaxi, bnt_b_sc_l, nto_b_l\n", encoding="utf-8")

        insp = self.installer.inspect_source(str(mod_src))
        self.assertEqual(insp["tuning_parts_analysis"], [])

        params = {
            "inspect_dir": str(mod_src),
            "target_category": "Modded Cars",
            "folder_name": "PremierMod",
            "vehicles": [
                {"source_model": "premier", "target_model": "premier", "category": "Modded Cars"}
            ]
        }
        res = self.installer.execute_install(params)
        self.assertTrue(res["success"], res)

        # Ensure shadow veh_mods.ide does NOT have duplicate bnt_b_sc_l or nto_b_l
        shadow_vm_path = self.shadow / "veh_mods.ide"
        if shadow_vm_path.exists():
            text = shadow_vm_path.read_text(encoding="utf-8")
            self.assertNotIn("bnt_b_sc_l, premier", text)
            self.assertNotIn("nto_b_l, premier", text)
            self.assertEqual(text.count("bnt_b_sc_l"), 1)

    def test_custom_tuning_parts_are_added_to_veh_mods_ide(self):
        (self.game / "data" / "carmods.dat").write_text("mods\nend\nlink\nend\n", encoding="utf-8")
        (self.game / "data" / "shopping.dat").write_text("section prices\nsection CarMods\nend\nend\n", encoding="utf-8")
        vm_dir = self.game / "data" / "maps" / "veh_mods"
        vm_dir.mkdir(parents=True, exist_ok=True)
        vanilla_vm = "objs\n1005, bnt_b_sc_l, vehicle, 70, 0\nend\n"
        (vm_dir / "veh_mods.ide").write_text(vanilla_vm, encoding="utf-8")

        mod_src = Path(self.temp.name) / "custom_pack"
        mod_src.mkdir()
        (mod_src / "custom_car.dff").write_bytes(b"test dff")
        (mod_src / "spl_custom_1.dff").write_bytes(b"test spoiler")
        (mod_src / "carmods.dat").write_text("custom_car, bnt_b_sc_l, spl_custom_1\n", encoding="utf-8")

        insp = self.installer.inspect_source(str(mod_src))
        # spl_custom_1 is new, so it SHOULD be analyzed
        self.assertEqual(len(insp["tuning_parts_analysis"]), 1)
        self.assertEqual(insp["tuning_parts_analysis"][0]["part_name"], "spl_custom_1")

        params = {
            "inspect_dir": str(mod_src),
            "target_category": "Modded Cars",
            "folder_name": "CustomMod",
            "vehicles": [
                {"source_model": "custom_car", "target_model": "custom_car", "category": "Modded Cars"}
            ]
        }
        res = self.installer.execute_install(params)
        self.assertTrue(res["success"], res)

        shadow_vm_path = self.shadow / "veh_mods.ide"
        self.assertTrue(shadow_vm_path.exists())
        text = shadow_vm_path.read_text(encoding="utf-8")
        # spl_custom_1 MUST be present
        self.assertIn("spl_custom_1", text)
        # bnt_b_sc_l must not be duplicated
        self.assertEqual(text.count("bnt_b_sc_l"), 1)

    def test_alternative_install_modes_are_detected(self):
        src = Path(self.temp.name) / "alt_pack"
        (src / "Added").mkdir(parents=True)
        (src / "Replace").mkdir(parents=True)
        (src / "Added" / "newcar.dff").write_bytes(b"identical model bytes")
        (src / "Added" / "newcar.txt").write_text(
            "vehicles.ide\n12090, newcar, newcar, car, NEWCAR, NEWCAR, null, normal, 7, 0, 0, -1, 0.7, 0.7, 0\n",
            encoding="utf-8")
        (src / "Replace" / "rancher.dff").write_bytes(b"identical model bytes")
        (src / "Replace" / "rancher.txt").write_text(
            "vehicles.ide\n489, rancher, rancher, car, RANCHER, RANCHR, null, normal, 7, 0, 0, -1, 0.7, 0.7, 0\n",
            encoding="utf-8")

        insp = self.installer.inspect_source(str(src))
        self.assertTrue(insp["success"], insp)
        by_model = {v["model"]: v for v in insp["target_vehicles"]}
        self.assertEqual(set(by_model), {"newcar", "rancher"})
        self.assertNotIn("alternative_of", by_model["newcar"])
        self.assertEqual(by_model["rancher"]["alternative_of"], "newcar")

    def test_skipped_alternative_assets_and_docs_are_not_deployed(self):
        src = Path(self.temp.name) / "alt_pack2"
        (src / "Added").mkdir(parents=True)
        (src / "Replace").mkdir(parents=True)
        (src / "Added" / "newcar.dff").write_bytes(b"newcar model bytes")
        (src / "Added" / "newcar.txt").write_text(
            "vehicles.ide\n12090, newcar, newcar, car, NEWCAR, NEWCAR, null, normal, 7, 0, 0, -1, 0.7, 0.7, 0\n",
            encoding="utf-8")
        (src / "Replace" / "rancher.dff").write_bytes(b"rancher model bytes")
        (src / "Replace" / "rancher.txt").write_text(
            "vehicles.ide\n489, rancher, rancher, car, RANCHER, RANCHR, null, normal, 7, 0, 0, -1, 0.7, 0.7, 0\n",
            encoding="utf-8")

        params = {
            "inspect_dir": str(src),
            "target_category": "Addon Cars",
            "folder_name": "AltPack",
            "vehicles": [
                {"source_model": "newcar", "target_model": "newcar", "category": "Addon Cars",
                 "addon_id": 12090, "generate_fxt": False, "merge_fla": False},
                {"source_model": "rancher", "target_model": "rancher", "category": "Modded Cars",
                 "skip": True, "generate_fxt": False},
            ],
        }
        res = self.installer.execute_install(params)
        self.assertTrue(res["success"], res)

        addon_dir = self.game / "modloader" / "Addon Cars" / "AltPack"
        self.assertTrue((addon_dir / "newcar.dff").is_file())
        self.assertEqual((addon_dir / "newcar.dff").read_bytes(), b"newcar model bytes")
        # The vehicle-specific doc follows its own vehicle, not the first dir.
        self.assertTrue((addon_dir / "newcar.txt.used_source").is_file())
        # Skipped vehicle assets/docs must not be deployed or renamed.
        self.assertFalse((addon_dir / "rancher.dff").exists())
        self.assertFalse((addon_dir / "rancher.txt").exists())
        self.assertFalse((self.game / "modloader" / "Modded Cars" / "AltPack").exists())

    def test_repeated_install_does_not_duplicate_mirror_links(self):
        src = Path(self.temp.name) / "mirror_pack"
        src.mkdir()
        (src / "newcar.dff").write_bytes(b"newcar model")
        (src / "spl_l_lr_x.dff").write_bytes(b"left spoiler")
        (src / "spl_r_lr_x.dff").write_bytes(b"right spoiler")
        (src / "carmods.dat").write_text("newcar, spl_l_lr_x, spl_r_lr_x\n", encoding="utf-8")
        params = {
            "inspect_dir": str(src),
            "target_category": "Addon Cars",
            "folder_name": "MirrorPack",
            "vehicles": [{"source_model": "newcar", "target_model": "newcar",
                          "category": "Addon Cars", "addon_id": 12091,
                          "generate_fxt": False, "merge_fla": False}],
        }
        self.assertTrue(self.installer.execute_install(params)["success"])
        self.assertTrue(self.installer.execute_install(params)["success"])
        text = (self.shadow / "carmods.dat").read_text(encoding="utf-8")
        link_lines = [l.strip().lower() for l in text.splitlines()
                      if l.strip().lower() == "spl_l_lr_x, spl_r_lr_x"]
        self.assertEqual(len(link_lines), 1)

    def test_addon_handling_keeps_author_id_when_it_differs_from_model(self):
        src = Path(self.temp.name) / "blistr_pack"
        src.mkdir()
        (src / "blister.dff").write_bytes(b"blister model")
        (src / "blister.txt").write_text(
            "vehicles.ide\n12092, blister, blister, car, BLISTR, BLISTR, null, normal, 7, 0, 0, -1, 0.7, 0.7, 0\n\n"
            "handling.cfg\n" + handling("BLISTR") + "\n", encoding="utf-8")
        params = {
            "inspect_dir": str(src),
            "target_category": "Addon Cars",
            "folder_name": "BlistrPack",
            "vehicles": [{"source_model": "blister", "target_model": "blister",
                          "category": "Addon Cars", "addon_id": 12092,
                          "generate_fxt": False, "merge_fla": False}],
        }
        res = self.installer.execute_install(params)
        self.assertTrue(res["success"], res)
        handling_text = (self.shadow / "handling.cfg").read_text(encoding="utf-8")
        self.assertIn("BLISTR", handling_text)
        self.assertNotIn("BLISTER", handling_text)
        ide_text = (self.shadow / "vehicles.ide").read_text(encoding="utf-8")
        self.assertIn("12092, blister", ide_text)
        self.assertFalse(any("未写入" in w for w in res.get("warnings", [])))

    def test_replace_handling_is_renamed_to_target_handling_id(self):
        src = Path(self.temp.name) / "h_pack"
        src.mkdir()
        (src / "ranchxlt.dff").write_bytes(b"custom rancher")
        (src / "readme.txt").write_text("handling.cfg\n" + handling("RANCHXLT") + "\n", encoding="utf-8")
        params = {
            "inspect_dir": str(src),
            "target_category": "Modded Cars",
            "folder_name": "HPack",
            "vehicles": [{"source_model": "ranchxlt", "target_model": "rancher",
                          "category": "Modded Cars", "merge_fla": False}],
        }
        res = self.installer.execute_install(params)
        self.assertTrue(res["success"], res)
        handling_text = (self.shadow / "handling.cfg").read_text(encoding="utf-8")
        self.assertIn("RANCHER", handling_text)
        self.assertNotIn("RANCHXLT", handling_text)


class BackupManagerRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bm_test_", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.temp_path = Path(self.temp.name)
        self.game_dir = self.temp_path / "game"
        self.game_dir.mkdir()
        (self.game_dir / "data").mkdir()
        (self.game_dir / "modloader" / "Modded Cars").mkdir(parents=True)
        self.backup_dir = self.temp_path / "backups"
        self.bm = BackupManager(backup_dir=str(self.backup_dir), game_dir=str(self.game_dir), max_snapshots=3)

    def test_snapshot_groups_multiple_files_and_writes_manifest(self):
        file1 = self.game_dir / "data" / "handling.cfg"
        file2 = self.game_dir / "modloader" / "Modded Cars" / "carcols.dat"
        file1.write_text("HANDLING_V1", encoding="utf-8")
        file2.write_text("CARCOLS_V1", encoding="utf-8")

        with self.bm.snapshot(action_name="install_test", description="testing install"):
            self.bm.backup_file(str(file1))
            self.bm.backup_file(str(file2))

        snapshots = self.bm.list_snapshots()
        self.assertEqual(len(snapshots), 1)
        snap = snapshots[0]
        self.assertEqual(snap["action"], "install_test")
        self.assertEqual(len(snap["files"]), 2)

        # Ensure no backups created inside game directory
        self.assertEqual(len(list(self.game_dir.rglob("*.bak_*"))), 0)

    def test_duplicate_backup_preserves_initial_content(self):
        file1 = self.game_dir / "data" / "handling.cfg"
        file1.write_text("INITIAL_STATE", encoding="utf-8")

        with self.bm.snapshot(action_name="double_edit"):
            # First backup captures INITIAL_STATE
            self.bm.backup_file(str(file1))
            file1.write_text("MODIFIED_ONCE", encoding="utf-8")
            # Second backup in same snapshot must not overwrite with MODIFIED_ONCE
            self.bm.backup_file(str(file1))

        snap_dir = Path(self.bm.list_snapshots()[0]["dir_path"])
        backed_up_file = snap_dir / "data" / "handling.cfg"
        self.assertEqual(backed_up_file.read_text(encoding="utf-8"), "INITIAL_STATE")

    def test_rotation_limit_removes_oldest_snapshots(self):
        file1 = self.game_dir / "data" / "test.cfg"
        file1.write_text("test", encoding="utf-8")

        # Create 5 snapshots (max_snapshots is set to 3)
        for i in range(5):
            with self.bm.snapshot(action_name=f"snap_{i}"):
                self.bm.backup_file(str(file1))
                time.sleep(0.01)

        snapshots = self.bm.list_snapshots()
        self.assertEqual(len(snapshots), 3)
        actions = [s["action"] for s in snapshots]
        self.assertIn("snap_4", actions)
        self.assertIn("snap_3", actions)
        self.assertIn("snap_2", actions)
        self.assertNotIn("snap_0", actions)

    def test_restore_snapshot_reverts_game_files(self):
        file1 = self.game_dir / "data" / "handling.cfg"
        file1.write_text("SAFE_ORIGINAL", encoding="utf-8")

        with self.bm.snapshot(action_name="before_corruption"):
            self.bm.backup_file(str(file1))

        # Corrupt file
        file1.write_text("CORRUPTED_MOD_DATA", encoding="utf-8")

        # Restore
        snap_id = self.bm.list_snapshots()[0]["id"]
        res = self.bm.restore_snapshot(snap_id)
        self.assertTrue(res["success"], res)
        self.assertEqual(file1.read_text(encoding="utf-8"), "SAFE_ORIGINAL")

    def test_clean_legacy_game_backups_clears_game_dir(self):
        # Create legacy .bak_* files in data and modloader
        legacy1 = self.game_dir / "data" / "gtasa_vehicleAudioSettings.cfg.bak_20260908_120000"
        legacy2 = self.game_dir / "modloader" / "Modded Cars" / "carcols.dat.bak_20260908_120000"
        legacy1.write_text("OLD_BAK_1", encoding="utf-8")
        legacy2.write_text("OLD_BAK_2", encoding="utf-8")

        self.assertEqual(len(list(self.game_dir.rglob("*.bak_*"))), 2)

        res = self.bm.clean_legacy_game_backups(str(self.game_dir), archive_to_backup=True)
        self.assertTrue(res["success"])
        self.assertEqual(res["cleaned_count"], 2)

        # Game directory must be completely clean now
        self.assertEqual(len(list(self.game_dir.rglob("*.bak_*"))), 0)
        # Archived folder must exist in backup_dir
        archive_dir = Path(res["archive_dir"])
        self.assertTrue(archive_dir.exists())
        self.assertEqual(len(list(archive_dir.rglob("*.bak_*"))), 2)


class FileExclusionRegression(Fixture):
    INFERNUS_IDE_LINE = ("411, infernus, infernus, car, INFERNUS, INFERNU, null, executive, "
                         "5, 0, 0, -1, 0.7, 0.7, 0")

    def setUp(self):
        super().setUp()
        (self.game / "data" / "handling.cfg").write_text("; vanilla handling\n", encoding="utf-8")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n" + self.INFERNUS_IDE_LINE + "\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        (self.shadow / "handling.cfg").write_text("; shadow handling\n", encoding="utf-8")
        (self.shadow / "vehicles.ide").write_text(
            "cars\n" + self.INFERNUS_IDE_LINE + "\nend\n", encoding="utf-8")
        self.source = Path(self.temp.name) / "source_exclude"
        self.source.mkdir()
        (self.source / "infernus.dff").write_bytes(b"test dff")
        (self.source / "infernus.txd").write_bytes(b"test txd")
        (self.source / "readme.txt").write_text(
            "INFERNUS 1500.0 3000.0 2.2 0.0 0.1 -0.15 70 0.85 0.8 0.5 5 240.0 30.0 10.0 R P 11.0 0.45 0 35.0 1.4 0.15 0.0 0.28 -0.15 0.5 0.3 0.36 0.60 35000 40002004 1 0 0 1",
            encoding="utf-8"
        )
        autoid_dir = self.source / "AutoID Files"
        autoid_dir.mkdir()
        (autoid_dir / "blister.txt").write_text(
            "600, blister, blister, car, BLISTAC, BLISTAC, null, normal, 10, 0, 0, -1, 0.7, 0.7, -1",
            encoding="utf-8"
        )
        (autoid_dir / "^cBlister.auid").write_bytes(b"auid binary text data")
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup_manager)

    def test_reparse_inspection_excludes_deselected_files(self):
        inspection = self.installer.inspect_source(str(self.source))
        self.assertTrue(inspection["success"])
        session_id = inspection["inspection_id"]

        # Initial parse should see both handling and vehicles.ide
        self.assertTrue(inspection["parsed_config"]["handling_cfg"])
        self.assertTrue(inspection["parsed_config"]["vehicles_ide"])

        # Deselect AutoID Files/blister.txt
        res = self.installer.reparse_inspection(session_id, excluded_files=["AutoID Files/blister.txt"])
        self.assertTrue(res["success"])
        # handling from readme.txt is kept
        self.assertTrue(res["parsed_config"]["handling_cfg"])
        # vehicles_ide from excluded blister.txt is removed
        self.assertFalse(res["parsed_config"]["vehicles_ide"])

        # Deselect both readme.txt and AutoID Files/blister.txt
        res2 = self.installer.reparse_inspection(session_id, excluded_files=["readme.txt", "AutoID Files/blister.txt"])
        self.assertTrue(res2["success"])
        self.assertFalse(res2["parsed_config"]["handling_cfg"])
        self.assertFalse(res2["parsed_config"]["vehicles_ide"])

    def test_preview_source_text_reads_files_properly(self):
        inspection = self.installer.inspect_source(str(self.source))
        self.assertTrue(inspection["success"])
        session_id = inspection["inspection_id"]
        res = self.installer.preview_source_text(session_id, "readme.txt")
        self.assertTrue(res["success"], res)
        self.assertIn("INFERNUS", res["content"])

        res2 = self.installer.preview_source_text(session_id, "AutoID Files/blister.txt")
        self.assertTrue(res2["success"], res2)
        self.assertIn("blister", res2["content"])

    def test_execute_install_skips_excluded_files(self):
        payload = {
            "inspect_dir": str(self.source),
            "target_category": "Modded Cars",
            "folder_name": "InfernusMod",
            "target_model": "infernus",
            "copy_files": True,
            "excluded_files": ["AutoID Files/blister.txt", "^cBlister.auid"]
        }
        res = self.installer.execute_install(payload)
        self.assertTrue(res["success"], res)

        dest_dir = self.game / "modloader" / "Modded Cars" / "InfernusMod"
        self.assertTrue((dest_dir / "infernus.dff").is_file())
        self.assertTrue((dest_dir / "infernus.txd").is_file())
        self.assertTrue((dest_dir / "readme.txt.used_source").is_file())

        # Excluded files must NOT be copied anywhere in modloader
        self.assertFalse((dest_dir / "blister.txt").exists())
        self.assertFalse((dest_dir / "AutoID Files" / "blister.txt").exists())
        self.assertFalse((dest_dir / "^cBlister.auid").exists())
        self.assertFalse((dest_dir / "AutoID Files" / "^cBlister.auid").exists())
        all_copied = [str(p.name) for p in (self.game / "modloader").rglob("*")]
        self.assertNotIn("blister.txt", all_copied)
        self.assertNotIn("^cBlister.auid", all_copied)

    def test_execute_install_skips_excluded_tuning_part(self):
        (self.source / "rf_b_sc.dff").write_bytes(b"test tuning part")
        payload = {
            "inspect_dir": str(self.source),
            "target_category": "Modded Cars",
            "folder_name": "InfernusMod2",
            "target_model": "infernus",
            "copy_files": True,
            "excluded_files": ["rf_b_sc.dff"]
        }
        res = self.installer.execute_install(payload)
        self.assertTrue(res["success"], res)
        dest_dir = self.game / "modloader" / "Modded Cars" / "InfernusMod2"
        self.assertFalse((dest_dir / "rf_b_sc.dff").exists())

    def test_execute_install_uses_user_parsed_config_fallback(self):
        payload = {
            "inspect_dir": str(self.source),
            "target_category": "Modded Cars",
            "folder_name": "InfernusFallback",
            "target_model": "infernus",
            "copy_files": True,
            "merge_handling": True,
            "parsed_config": {
                "handling_cfg": [
                    "INFERNUS 2222.0 4500.0 2.2 0.0 0.1 -0.15 75 0.85 0.8 0.5 5 240.0 35.0 10.0 R P 11.0 0.52 0 35.0 1.4 0.15 0.0 0.28 -0.1 0.5 0.3 0.25 0.60 35000 40002004 1 0 0"
                ]
            }
        }
        res = self.installer.execute_install(payload)
        self.assertTrue(res["success"], res)
        # Check that the handling line with mass 2222.0 was merged
        handling_file = self.game / "modloader" / "Modded Cars" / "handling.cfg"
        self.assertTrue(handling_file.is_file())
        content = handling_file.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("2222.0", content)



class DataComplianceAndCleanerRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="data_regression_", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "modloader" / "Modded Cars").mkdir(parents=True)
        self.backup_dir = Path(self.temp.name) / "backups"
        self.backup_manager = BackupManager(backup_dir=str(self.backup_dir), game_dir=str(self.game))
        shadow_dir = self.game / "modloader" / "Modded Cars"
        self.merger = ConfigMerger(str(shadow_dir), str(self.game), backup_manager=self.backup_manager)
        self.cleaner = ModCleaner(str(self.game), backup_manager=self.backup_manager)

        # Populate vanilla data
        (self.game / "data" / "vehicles.ide").write_text(
            "# vehicles.ide\n"
            "cars\n"
            "411, infernus, infernus, car, INFERNUS, INFERN, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0\n"
            "end\n",
            encoding="utf-8"
        )
        (self.game / "data" / "handling.cfg").write_text(
            "; handling.cfg\n"
            "INFERNUS 1500.0 4000.0 2.2 0.0 0.0 -0.2 70 0.8 0.8 0.5 5 240.0 30.0 10.0 R P 11.0 0.5 0 35.0 1.2 0.15 0.0 0.28 -0.1 0.5 0.3 0.25 0.6 35000 40002004 1 0 0\n"
            ";the end\n",
            encoding="utf-8"
        )
        (self.game / "data" / "carcols.dat").write_text(
            "col\n"
            "0,0,0\n"
            "end\n"
            "car\n"
            "infernus, 1,1, 2,2\n"
            "end\n"
            "car4\n"
            "camper, 1,2,3,4\n"
            "end\n",
            encoding="utf-8"
        )
        (self.game / "data" / "carmods.dat").write_text(
            "link\n"
            "part_a, part_b\n"
            "end\n"
            "mods\n"
            "infernus, exh_a\n"
            "end\n"
            "wheel\n"
            "0, 1, 2\n"
            "end\n",
            encoding="utf-8"
        )

    def test_merge_carcols_places_in_correct_sections_and_never_after_end(self):
        # Merge 2-color addon car (fbiprem) and 4-color car (testquad)
        actions = [
            {"model": "fbiprem", "line": "fbiprem, 0,0, 1,1"},
            {"model": "testquad", "line": "car4 testquad, 1,2,3,4, 5,6,7,8"}
        ]
        res = self.merger._merge_carcols(actions)
        self.assertTrue(res["success"], res)

        shadow_c = self.game / "modloader" / "Modded Cars" / "carcols.dat"
        self.assertTrue(shadow_c.is_file())
        content = shadow_c.read_text(encoding="utf-8")

        # Verify nothing is placed after the final end of car4
        end_idx = content.rfind("end")
        after_end = content[end_idx + 3:].strip()
        self.assertEqual(after_end, "", "No vehicle entries allowed after final end in carcols.dat!")

        # Verify 2-color car is in 'car' section
        car_idx = content.find("car\n")
        car_end = content.find("end", car_idx)
        fbiprem_idx = content.find("fbiprem")
        self.assertTrue(car_idx < fbiprem_idx < car_end, "fbiprem must be inside car section before its end")

        # Verify 4-color car is in 'car4' section
        car4_idx = content.find("car4\n")
        car4_end = content.find("end", car4_idx)
        quad_idx = content.find("testquad")
        self.assertTrue(car4_idx < quad_idx < car4_end, "testquad must be inside car4 section before its end")

    def test_delete_mod_purges_addon_entries_from_all_files(self):
        # Set up shadow files with addon entries for 'fbiprem'
        shadow_dir = self.game / "modloader" / "Modded Cars"
        (shadow_dir / "vehicles.ide").write_text(
            "cars\n411, infernus, infernus, car, INFERNUS, INFERN, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0\n12000, fbiprem, fbiprem, car, FBIPREM, FBIPREM, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0\nend\n"
        )
        (shadow_dir / "handling.cfg").write_text(
            "INFERNUS 1500.0 ...\nFBIPREM 1800.0 ...\n;the end\n"
        )
        (shadow_dir / "carcols.dat").write_text(
            "col\n0,0,0\nend\ncar\ninfernus, 1,1\nfbiprem, 0,0\nend\ncar4\ncamper, 1,2,3,4\nend\n"
        )
        (shadow_dir / "carmods.dat").write_text(
            "link\nend\nmods\ninfernus, exh_a\nfbiprem, exh_a\nend\nwheel\nend\n"
        )
        # Create dummy mod folder with fbiprem.dff
        mod_folder = shadow_dir / "FbiPremMod"
        mod_folder.mkdir()
        (mod_folder / "fbiprem.dff").write_bytes(b"dff content")

        res = self.cleaner.delete_mod(str(mod_folder), target_model="fbiprem")
        self.assertTrue(res["success"], res)

        # Mod folder deleted
        self.assertFalse(mod_folder.exists())

        # Check that fbiprem was removed from all shadow files
        self.assertNotIn("fbiprem", (shadow_dir / "vehicles.ide").read_text())
        self.assertNotIn("FBIPREM", (shadow_dir / "handling.cfg").read_text())
        self.assertNotIn("fbiprem", (shadow_dir / "carcols.dat").read_text())
        self.assertNotIn("fbiprem", (shadow_dir / "carmods.dat").read_text())

        # Infernus must still be preserved in all shadow files
        self.assertIn("infernus", (shadow_dir / "vehicles.ide").read_text())
        self.assertIn("INFERNUS", (shadow_dir / "handling.cfg").read_text())
        self.assertIn("infernus", (shadow_dir / "carcols.dat").read_text())
        self.assertIn("infernus", (shadow_dir / "carmods.dat").read_text())

    def test_clean_orphaned_vehicle_entries_purges_only_orphans(self):
        shadow_dir = self.game / "modloader" / "Modded Cars"
        (shadow_dir / "vehicles.ide").write_text(
            "cars\n411, infernus, infernus, car, INFERNUS, INFERN, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0\n12000, orphan1, orphan1, car, ORPHAN, ORPHAN, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0\nend\n"
        )
        (shadow_dir / "handling.cfg").write_text(
            "INFERNUS 1500.0 ...\nORPHAN1 1800.0 ...\n;the end\n"
        )
        (shadow_dir / "carcols.dat").write_text(
            "col\n0,0,0\nend\ncar\ninfernus, 1,1\norphan1, 0,0\nend\ncar4\ncamper, 1,2,3,4\nend\norphan1, 0,0\n"
        )
        (shadow_dir / "carmods.dat").write_text(
            "link\npart_a, part_b\nend\nmods\ninfernus, exh_a\norphan1, exh_a\nend\nwheel\n0, 1, 2\nend\n"
        )

        res = self.cleaner.clean_orphaned_vehicle_entries()
        self.assertTrue(res["success"], res)
        self.assertIn("orphan1", res["purged"]["vehicles_ide"])
        self.assertIn("orphan1", res["purged"]["handling_cfg"])
        self.assertIn("orphan1", res["purged"]["carcols_dat"])
        self.assertIn("orphan1", res["purged"]["carmods_dat"])

        # Check file contents
        carmods_text = (shadow_dir / "carmods.dat").read_text()
        self.assertIn("link\npart_a, part_b\nend", carmods_text)
        self.assertIn("wheel\n0, 1, 2\nend", carmods_text)
        self.assertIn("infernus, exh_a", carmods_text)
        self.assertNotIn("orphan1", carmods_text)

        carcols_text = (shadow_dir / "carcols.dat").read_text()
        self.assertNotIn("orphan1", carcols_text)
        self.assertTrue(carcols_text.strip().endswith("end"))

    def test_vanilla_handling_baseline_retrieval(self):
        # 1. When no shadow handling exists, active handling falls back to vanilla, and vanilla_handling baseline is also present
        cfg = self.merger.get_vehicle_active_configs("infernus")
        self.assertIsNotNone(cfg["vanilla_handling"])
        self.assertEqual(cfg["vanilla_handling"]["decomposed"]["max_speed_kmh"], 240.0)
        self.assertEqual(cfg["vanilla_handling"]["decomposed"]["mass_kg"], 1500.0)
        self.assertEqual(cfg["vanilla_handling"]["decomposed"]["drive_type"], "R")

        # 2. When a modded shadow handling entry exists, active handling is shadow, but vanilla_handling baseline stays intact
        shadow_dir = self.game / "modloader" / "Modded Cars"
        (shadow_dir / "handling.cfg").write_text(
            "INFERNUS 1350.0 3800.0 2.0 0.0 0.0 -0.2 70 0.85 0.85 0.5 6 265.0 35.0 12.0 4 P 12.0 0.55 0 38.0 1.2 0.15 0.0 0.28 -0.1 0.5 0.3 0.25 0.6 35000 40002004 1 0 0\n",
            encoding="utf-8"
        )
        cfg_modded = self.merger.get_vehicle_active_configs("infernus")
        self.assertEqual(cfg_modded["handling"]["source"], "shadow")
        self.assertEqual(cfg_modded["handling"]["decomposed"]["max_speed_kmh"], 265.0)
        self.assertEqual(cfg_modded["handling"]["decomposed"]["drive_type"], "4")
        self.assertEqual(cfg_modded["handling"]["decomposed"]["gears"], 6)

        # Baseline vanilla_handling remains the true vanilla
        self.assertIsNotNone(cfg_modded["vanilla_handling"])
        self.assertEqual(cfg_modded["vanilla_handling"]["decomposed"]["max_speed_kmh"], 240.0)
        self.assertEqual(cfg_modded["vanilla_handling"]["decomposed"]["drive_type"], "R")
        self.assertEqual(cfg_modded["vanilla_handling"]["decomposed"]["gears"], 5)


class AudioSettingsRegression(Fixture):
    def setUp(self):
        super().setUp()
        self.fla = FLAManager(str(self.game), backup_manager=self.backup_manager)
        self.audio_file = self.game / "data" / "gtasa_vehicleAudioSettings.cfg"
        self.audio_file.write_text(
            "; fastman92 audio\n"
            "supergt 0 103 102 1 0.9 1.0 4 1.0 2 0 8 0 2 0.0\n"
            "infernus 0 38 37 1 0.9 1.0 8 1.12246 2 0 6 0 2 0.0\n"
            "customaddon 0 87 86 0 0.8 1.0 7 1.0 2 0 1 0 10 0.0\n"
            ";the end\n",
            encoding="utf-8"
        )

    def test_vanilla_audio_settings_integrity(self):
        from core.vanilla_data import VANILLA_AUDIO_SETTINGS
        self.assertEqual(len(VANILLA_AUDIO_SETTINGS), 212)
        self.assertIn("zr350", VANILLA_AUDIO_SETTINGS)
        self.assertIn("supergt", VANILLA_AUDIO_SETTINGS)
        self.assertIn("buffalo", VANILLA_AUDIO_SETTINGS)
        self.assertIn("infernus", VANILLA_AUDIO_SETTINGS)
        # Check supergt bank numbers are 103 and 102
        parts = VANILLA_AUDIO_SETTINGS["supergt"].split()
        self.assertEqual(parts[2], "103")
        self.assertEqual(parts[3], "102")

    def test_sound_presets_authenticity(self):
        from core.fla_manager import SOUND_PRESETS
        self.assertEqual(len(SOUND_PRESETS), 7)  # default + 6 donor cars
        ids = [p["id"] for p in SOUND_PRESETS]
        self.assertEqual(ids, ["default", "infernus", "cheetah", "sultan", "elegy", "sabre", "rancher"])
        # Check authentic bank numbers
        by_id = {p["id"]: p for p in SOUND_PRESETS}
        self.assertEqual((by_id["infernus"]["bank_a"], by_id["infernus"]["bank_b"]), (38, 37))
        self.assertEqual((by_id["cheetah"]["bank_a"], by_id["cheetah"]["bank_b"]), (103, 102))
        self.assertEqual((by_id["sultan"]["bank_a"], by_id["sultan"]["bank_b"]), (87, 86))
        self.assertEqual((by_id["elegy"]["bank_a"], by_id["elegy"]["bank_b"]), (8, 7))
        self.assertEqual((by_id["sabre"]["bank_a"], by_id["sabre"]["bank_b"]), (46, 45))
        self.assertEqual((by_id["rancher"]["bank_a"], by_id["rancher"]["bank_b"]), (99, 98))

    def test_remove_audio_setting_reverts_vanilla_car(self):
        # Change supergt to custom values
        custom_line = "supergt 0 87 86 0 1.0 1.0 7 1.0 2 0 1 0 10 0.0"
        self.fla.update_audio_setting("supergt", custom_line)
        detail = self.fla.get_model_fla_detail("supergt")
        self.assertTrue(detail["audio"]["is_modified"])

        # Revert supergt audio
        ok = self.fla.remove_audio_setting("supergt")
        self.assertTrue(ok)
        detail_after = self.fla.get_model_fla_detail("supergt")
        # Must still exist in file!
        self.assertTrue(detail_after["audio"]["exists"])
        self.assertFalse(detail_after["audio"]["is_modified"])
        # And must match official vanilla line
        from core.vanilla_data import VANILLA_AUDIO_SETTINGS
        self.assertEqual(detail_after["audio"]["raw_line"].split(), VANILLA_AUDIO_SETTINGS["supergt"].split())

    def test_remove_audio_setting_deletes_addon_car(self):
        # customaddon is not in VANILLA_AUDIO_SETTINGS
        detail = self.fla.get_model_fla_detail("customaddon")
        self.assertTrue(detail["audio"]["exists"])
        self.assertFalse(detail["audio"]["is_vanilla"])

        ok = self.fla.remove_audio_setting("customaddon")
        self.assertTrue(ok)
        detail_after = self.fla.get_model_fla_detail("customaddon")
        self.assertFalse(detail_after["audio"]["exists"])

    def test_audio_dual_track_recognition(self):
        from core.parser import DualTrackParser
        parser = DualTrackParser()

        # 1. With section header
        txt_header = "[Audio Settings]\nbuffsux 0 38 37 1 0.9 1.0 2 1.05946 2 0 7 0 2 0.0\n"
        res1 = parser.parse_text_content(txt_header)
        self.assertEqual(len(res1["vehicle_audio"]), 1)

        # 2. Without any section header (pure syntax fingerprinting)
        txt_no_header = (
            "Readme info:\n"
            "This is my new vehicle.\n"
            "landstal 0 99 98 0 0.78 1.0 7 1.0 2 0 8 0 0 0.0\n"
            "Thanks for downloading!\n"
        )
        res2 = parser.parse_text_content(txt_no_header)
        self.assertEqual(len(res2["vehicle_audio"]), 1)
        self.assertIn("landstal", res2["vehicle_audio"][0])

        # 3. Commented lines without headers
        txt_commented = "; landstal 0 99 98 0 0.78 1.0 7 1.0 2 0 8 0 0 0.0\n"
        res3 = parser.parse_text_content(txt_commented)
        self.assertEqual(len(res3["vehicle_audio"]), 1)



class BrowseDialogRegression(unittest.TestCase):
    @patch("tkinter.filedialog.askdirectory")
    @patch("tkinter.Tk")
    def test_browse_folder_localization_and_title(self, mock_tk, mock_askdir):
        from server import browse_folder_native
        mock_askdir.return_value = "D:\\Games\\GTA SA"

        # 1. Custom title passed explicitly (e.g. Mod Folder in EN)
        res = browse_folder_native(initial_dir="C:\\", title="Select Vehicle Mod Folder", lang="en")
        mock_askdir.assert_called_with(initialdir="C:\\", title="Select Vehicle Mod Folder")
        self.assertEqual(res, "D:\\Games\\GTA SA")

        # 2. Custom title passed explicitly
        res2 = browse_folder_native(initial_dir="C:\\", title="Custom Folder Picker", lang="en")
        mock_askdir.assert_called_with(initialdir="C:\\", title="Custom Folder Picker")

        # 3. Default fallback in EN
        browse_folder_native(initial_dir="C:\\", title="", lang="en")
        mock_askdir.assert_called_with(initialdir="C:\\", title="Select Folder")

        # 4. Default fallback for unsupported language falls back to English
        browse_folder_native(initial_dir="C:\\", title="", lang="unknown")
        mock_askdir.assert_called_with(initialdir="C:\\", title="Select Folder")

    @patch("tkinter.filedialog.askopenfilename")
    @patch("tkinter.Tk")
    def test_browse_file_localization_and_filetypes(self, mock_tk, mock_askopen):
        from server import browse_file_native
        mock_askopen.return_value = "D:\\Downloads\\mod.zip"

        # 1. EN mode
        res_en = browse_file_native(initial_dir="C:\\", title="Select Vehicle Mod Archive or Files", lang="en")
        args_en, kwargs_en = mock_askopen.call_args
        self.assertEqual(kwargs_en["title"], "Select Vehicle Mod Archive or Files")
        self.assertTrue(any("Mod Archives" in ft[0] for ft in kwargs_en["filetypes"]))
        self.assertTrue(any("All Files" in ft[0] for ft in kwargs_en["filetypes"]))
        self.assertEqual(res_en, "D:\\Downloads\\mod.zip")

        # 2. Fallback mode for other language
        res_other = browse_file_native(initial_dir="C:\\", title="Custom File Picker", lang="unknown")
        args_other, kwargs_other = mock_askopen.call_args
        self.assertEqual(kwargs_other["title"], "Custom File Picker")
        self.assertTrue(any("Mod Archives" in ft[0] for ft in kwargs_other["filetypes"]))
        self.assertTrue(any("All Files" in ft[0] for ft in kwargs_other["filetypes"]))

    @patch("server.browse_folder_native")
    def test_api_browse_folder_handler(self, mock_browse):
        import io
        import json
        from server import ModManagerHandler

        mock_browse.return_value = "D:\\Modded Cars\\car1"
        handler = ModManagerHandler.__new__(ModManagerHandler)
        payload = json.dumps({"initial": "", "title": "Select Vehicle Mod Folder", "lang": "en"}).encode("utf-8")
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.path = "/api/browse-folder"

        sent_data = []
        handler._send_json = lambda d: sent_data.append(d)
        handler.do_POST()

        mock_browse.assert_called_with("", title="Select Vehicle Mod Folder", lang="en")
        self.assertEqual(sent_data[0], {"success": True, "path": "D:\\Modded Cars\\car1"})

    @patch("server.browse_file_native")
    def test_api_browse_file_handler(self, mock_browse):
        import io
        import json
        from server import ModManagerHandler

        mock_browse.return_value = "D:\\Downloads\\car.zip"
        handler = ModManagerHandler.__new__(ModManagerHandler)
        payload = json.dumps({"initial": "", "title": "Select Vehicle Mod Archive or Files", "lang": "en"}).encode("utf-8")
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.path = "/api/browse-file"

        sent_data = []
        handler._send_json = lambda d: sent_data.append(d)
        handler.do_POST()

        mock_browse.assert_called_with("", title="Select Vehicle Mod Archive or Files", lang="en")
        self.assertEqual(sent_data[0], {"success": True, "path": "D:\\Downloads\\car.zip"})


class FxtAuthorHandlingRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fxt_reg_", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "modloader" / "Modded Cars").mkdir(parents=True)
        (self.game / "modloader" / "Addon Cars").mkdir(parents=True)
        (self.game / "data" / "vehicles.ide").write_text("cars\nend\n", encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; handling\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("car\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nend\n", encoding="utf-8")
        (self.game / "modloader" / "Modded Cars" / "vehicles.ide").write_text("cars\nend\n", encoding="utf-8")
        (self.game / "modloader" / "Modded Cars" / "handling.cfg").write_text("; handling\n", encoding="utf-8")
        (self.game / "modloader" / "Modded Cars" / "carcols.dat").write_text("car\nend\n", encoding="utf-8")
        (self.game / "modloader" / "Modded Cars" / "carmods.dat").write_text("mods\nend\n", encoding="utf-8")
        self.backup_mgr = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup_mgr)

    def test_author_fxt_file_reading_and_no_duplicate_generation(self):
        # Create a mod folder mimicking "Ubermacht Sentinel 2.7 Coupe 1984"
        mod_dir = Path(self.temp.name) / "Ubermacht Sentinel 2.7 Coupe 1984"
        mod_dir.mkdir()
        (mod_dir / "sent84c.dff").write_bytes(b"dummy dff")
        (mod_dir / "sent84c.txd").write_bytes(b"dummy txd")
        (mod_dir / "readme.txt").write_text("Author: TestAuthor\n12001, sent84c, sent84c, car, SENT84C, SENT84C, null, normal, 10, 0, 0, -1, 0.7, 0.7, -1\n", encoding="utf-8")

        # Author provided sent84c.fxt with UTF-8 BOM
        fxt_content = "\ufeffSENT84C Sentinel 2.7 Coupe\n"
        (mod_dir / "sent84c.fxt").write_text(fxt_content, encoding="utf-8-sig")

        # 1. Inspect source
        res = self.installer.inspect_source(str(mod_dir))
        self.assertTrue(res["success"])
        self.assertTrue(res["has_author_fxt"])
        self.assertIn("sent84c.fxt", res["fxt_files"])

        # Verify fxt proposal uses author's name, NOT the folder name!
        fxt_prop = res["fxt_proposal"]
        self.assertEqual(fxt_prop["key"], "SENT84C")
        self.assertEqual(fxt_prop["name"], "Sentinel 2.7 Coupe")
        self.assertNotEqual(fxt_prop["name"], "Ubermacht Sentinel 2.7 Coupe 1984")
        self.assertTrue(fxt_prop["has_author_fxt"])

        # Target vehicle proposal
        tv = res["target_vehicles"][0]
        self.assertEqual(tv["fxt_proposal"]["key"], "SENT84C")
        self.assertEqual(tv["fxt_proposal"]["name"], "Sentinel 2.7 Coupe")

        # 2. Apply install
        install_params = {
            "source_path": str(mod_dir),
            "inspect_dir": res["inspect_dir"],
            "folder_name": "Ubermacht Sentinel 2.7 Coupe 1984",
            "target_category": "Addon Cars",
            "vehicles": [{
                "source_model": "sent84c",
                "target_model": "sent84c",
                "fxt_key": "SENT84C",
                "fxt_name": "Sentinel 2.7 Coupe",
                "copy_files": True,
                "generate_fxt": True,
                "addon_id": 12001
            }]
        }
        ins_res = self.installer.execute_install(install_params)
        self.assertTrue(ins_res["success"])

        # 3. Check installed directory:
        installed_dest = self.game / "modloader" / "Addon Cars" / "Ubermacht Sentinel 2.7 Coupe 1984"
        self.assertTrue(installed_dest.is_dir())

        # Author's sent84c.fxt MUST be present
        self.assertTrue((installed_dest / "sent84c.fxt").exists())

        # Must NOT generate a second duplicate file with folder name!
        self.assertFalse((installed_dest / "Ubermacht Sentinel 2.7 Coupe 1984.fxt").exists())

        # Check that there is exactly ONE .fxt file
        fxts = list(installed_dest.glob("*.fxt"))
        self.assertEqual(len(fxts), 1)
        self.assertEqual(fxts[0].name, "sent84c.fxt")
        self.assertIn("SENT84C Sentinel 2.7 Coupe", fxts[0].read_text(encoding="utf-8"))

    def test_fallback_fxt_generation_uses_clean_model_name(self):
        # Mod WITHOUT an author fxt
        mod_dir = Path(self.temp.name) / "1992 Maibatsu Super GT"
        mod_dir.mkdir()
        (mod_dir / "supergt.dff").write_bytes(b"dummy dff")
        (mod_dir / "supergt.txd").write_bytes(b"dummy txd")

        res = self.installer.inspect_source(str(mod_dir))
        self.assertTrue(res["success"])
        self.assertFalse(res["has_author_fxt"])
        self.assertEqual(len(res["fxt_files"]), 0)

        install_params = {
            "source_path": str(mod_dir),
            "inspect_dir": res["inspect_dir"],
            "folder_name": "1992 Maibatsu Super GT",
            "target_category": "Modded Cars",
            "vehicles": [{
                "source_model": "supergt",
                "target_model": "supergt",
                "fxt_key": "SUPERGT",
                "fxt_name": "Super GT",
                "copy_files": True,
                "generate_fxt": True
            }]
        }
        ins_res = self.installer.execute_install(install_params)
        self.assertTrue(ins_res["success"])

        installed_dest = self.game / "modloader" / "Modded Cars" / "1992 Maibatsu Super GT"
        self.assertTrue(installed_dest.is_dir())
        
        # Clean <model>.fxt should be generated, NOT <folder_name>.fxt!
        self.assertTrue((installed_dest / "supergt.fxt").exists())
        self.assertFalse((installed_dest / "1992 Maibatsu Super GT.fxt").exists())
        self.assertIn("SUPERGT Super GT", (installed_dest / "supergt.fxt").read_text(encoding="utf-8"))


class DataParsingAndMergingRegression(Fixture):
    def test_read_text_file_safe_encodings(self):
        from core.parser import read_text_file_safe

        # 1. UTF-8 with BOM
        bom_file = Path(self.temp.name) / "bom.txt"
        bom_file.write_bytes(b"\xef\xbb\xbfLANDSTAL 1700.0 4000.0")
        txt = read_text_file_safe(str(bom_file))
        self.assertFalse(txt.startswith("\ufeff"))
        self.assertTrue(txt.startswith("LANDSTAL"))

        # 2. GB18030 Chinese
        gb_file = Path(self.temp.name) / "gbk.txt"
        gb_file.write_bytes("车辆安装说明：桑塔纳".encode("gb18030"))
        txt_gb = read_text_file_safe(str(gb_file))
        self.assertIn("桑塔纳", txt_gb)

        # 3. CP1251 Cyrillic
        cp_file = Path(self.temp.name) / "cp1251.txt"
        cp_file.write_bytes("Модификация автомобиля".encode("cp1251"))
        txt_cp = read_text_file_safe(str(cp_file))
        self.assertIn("Модификация", txt_cp)

        # 4. UTF-16 LE with BOM
        u16_file = Path(self.temp.name) / "u16.txt"
        u16_file.write_bytes("SUPERGT 1400.0".encode("utf-16"))
        txt_u16 = read_text_file_safe(str(u16_file))
        self.assertIn("SUPERGT", txt_u16)

    def test_handling_prefix_bike_aircraft_boat(self):
        parser = DualTrackParser()
        bike_spaced = "! BF400 1200.0 2500.0 2.0 0.0 0.0 -0.2 70 0.8 0.8 0.5 5 180.0 25.0 10.0 R P 8.0 0.5 0 30.0 1.0 0.1 0.0 0.25 -0.1 0.5 0.3 0.25 0.10 35000 40002004 1 0"
        bike_joined = "!BF400 1200.0 2500.0 2.0 0.0 0.0 -0.2 70 0.8 0.8 0.5 5 180.0 25.0 10.0 R P 8.0 0.5 0 30.0 1.0 0.1 0.0 0.25 -0.1 0.5 0.3 0.25 0.10 35000 40002004 1 0"
        plane_line = "$ HYDRA 8000.0 15000.0 3.0 0.0 0.0 0.0 75 0.65 0.9 0.5 1 400.0 40.0 15.0 4 P 15.0 0.5 0 45.0 1.0 0.15 0.0 0.2 -0.15 0.5 0.3 0.25 0.10 1000000 2004 0 0"
        boat_line = "% PREDATOR 2000.0 4000.0 2.0 0.0 0.0 -0.1 80 0.9 0.8 0.5 1 200.0 30.0 10.0 4 D 10.0 0.5 0 35.0 1.0 0.1 0.0 0.2 -0.1 0.5 0.3 0.25 0.10 50000 40000000 0 0"

        d_spaced = parser.decompose_handling(bike_spaced)
        self.assertEqual(d_spaced["identifier"], "BF400")
        self.assertEqual(d_spaced["prefix"], "!")
        self.assertTrue(d_spaced["prefix_spaced"])

        d_joined = parser.decompose_handling(bike_joined)
        self.assertEqual(d_joined["identifier"], "BF400")
        self.assertEqual(d_joined["prefix"], "!")
        self.assertFalse(d_joined["prefix_spaced"])

        d_plane = parser.decompose_handling(plane_line)
        self.assertEqual(d_plane["identifier"], "HYDRA")
        self.assertEqual(d_plane["prefix"], "$")

        d_boat = parser.decompose_handling(boat_line)
        self.assertEqual(d_boat["identifier"], "PREDATOR")
        self.assertEqual(d_boat["prefix"], "%")

        # Test _merge_handling replaces bike in place without duplication
        merger = ConfigMerger(str(self.game / "modloader" / "Modded Cars"), str(self.game), backup_manager=self.backup_manager)
        h_file = self.game / "data" / "handling.cfg"
        h_file.write_text("; handling\n! BF400 999.0\nLANDSTAL 1700.0\n", encoding="utf-8")

        res = merger._merge_handling([{
            "identifier": "BF400",
            "line": "! BF400 1200.0 2500.0"
        }])
        self.assertTrue(res["success"])
        shadow_h = (self.game / "modloader" / "Modded Cars" / "handling.cfg").read_text(encoding="utf-8")
        self.assertEqual(shadow_h.count("BF400"), 1)
        self.assertIn("! BF400 1200.0 2500.0", shadow_h)
        self.assertNotIn("999.0", shadow_h)

    def test_carcols_car4_support(self):
        parser = DualTrackParser()
        content = "carcols.dat\ncar4\nsent87x, 0,0,107,0, 1,1,107,0, 3,3,107,0\nend\n"
        parsed = parser.parse_text_content(content)
        self.assertTrue(parsed["carcols_dat"])
        c_line = parsed["carcols_dat"][0]
        self.assertTrue(c_line.startswith("car4 "))

        d = parser.decompose_carcols(c_line)
        self.assertTrue(d["is_car4"])
        self.assertEqual(d["model_name"], "sent87x")
        self.assertEqual(d["count"], 3)
        self.assertEqual(len(d["color_pairs"]), 3)
        self.assertEqual(d["color_pairs"][0]["c1"], 0)
        self.assertEqual(d["color_pairs"][0]["c2"], 0)
        self.assertEqual(d["color_pairs"][0]["c3"], 107)
        self.assertEqual(d["color_pairs"][0]["c4"], 0)

        # Test merging car4 into carcols.dat without existing car4 section
        merger = ConfigMerger(str(self.game / "modloader" / "Modded Cars"), str(self.game), backup_manager=self.backup_manager)
        c_file = self.game / "data" / "carcols.dat"
        c_file.write_text("col\nend\ncar\nlandstal, 0,0\nend\n", encoding="utf-8")

        res = merger._merge_carcols([{
            "model": "sent87x",
            "line": "sent87x, 0,0,107,0, 1,1,107,0",
            "is_car4": True
        }])
        self.assertTrue(res["success"])
        shadow_c = (self.game / "modloader" / "Modded Cars" / "carcols.dat").read_text(encoding="utf-8")
        self.assertIn("car4", shadow_c)
        self.assertIn("sent87x, 0,0,107,0, 1,1,107,0", shadow_c)

    def test_vehicles_ide_comments_and_expanded_types(self):
        parser = DualTrackParser()
        ide_with_comment = "400, landstal, landstal, car, LANDSTAL, LANDSTAL, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0 # inline comment"
        self.assertTrue(parser._is_ide_line(ide_with_comment))
        d = parser.decompose_ide(ide_with_comment)
        self.assertEqual(d["id"], 400)
        self.assertEqual(d["model_name"], "landstal")
        self.assertNotIn("#", str(d["flags"]))

        # Expanded types: mtruck, dodo, train, wayfarer
        for vtype in ("mtruck", "dodo", "train", "wayfarer"):
            line = f"444, test_{vtype}, test_{vtype}, {vtype}, TEST, TEST, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0"
            self.assertTrue(parser._is_ide_line(line), f"Failed for {vtype}")
            d_type = parser.decompose_ide(line)
            self.assertEqual(d_type["vehicle_type"], vtype)

        # Tolerates short IDE lines (>= 8 columns)
        short_line = "555, shorty, shorty, car, SHORT, SHORT, null, normal"
        self.assertTrue(parser._is_ide_line(short_line))
        d_short = parser.decompose_ide(short_line)
        self.assertEqual(d_short["id"], 555)
        self.assertEqual(d_short["wheel_scale"], 0.7)


class SevenZipDetectionRegression(unittest.TestCase):
    def setUp(self):
        from core.seven_zip import reset_cache
        reset_cache()
        self.addCleanup(reset_cache)
        self.temp = tempfile.TemporaryDirectory(prefix="sevenzip_", dir=ROOT)
        self.addCleanup(self.temp.cleanup)

    def _fake_7z(self):
        fake = Path(self.temp.name) / "7z.exe"
        fake.write_bytes(b"fake-7z")
        return fake

    def test_env_var_points_to_exe(self):
        from core.seven_zip import find_7zip
        fake = self._fake_7z()
        with patch.dict(os.environ, {"SEVEN_ZIP": str(fake)}, clear=False):
            self.assertEqual(find_7zip(force_refresh=True), str(fake))

    def test_env_var_points_to_folder(self):
        from core.seven_zip import find_7zip
        fake = self._fake_7z()
        with patch.dict(os.environ, {"SEVEN_ZIP": str(fake.parent)}, clear=False):
            self.assertEqual(find_7zip(force_refresh=True), str(fake))

    def test_zip_extracts_without_7zip(self):
        from core.installer import ModInstaller
        src = Path(self.temp.name) / "mod.zip"
        inner = Path(self.temp.name) / "payload"
        inner.mkdir()
        (inner / "readme.txt").write_text("hello", encoding="utf-8")
        import zipfile
        with zipfile.ZipFile(src, "w") as zf:
            zf.write(inner / "readme.txt", "readme.txt")
        installer = ModInstaller(str(Path(self.temp.name) / "game"), "Modded Cars")
        with patch("core.installer.find_7zip", return_value=None):
            out = installer.extract_archive(str(src))
        self.assertTrue((Path(out) / "readme.txt").is_file())

    def test_rar_without_7zip_raises_typed_error(self):
        from core.installer import ModInstaller
        from core.seven_zip import SevenZipNotFoundError
        rar = Path(self.temp.name) / "mod.rar"
        rar.write_bytes(b"Rar!\x1a")
        installer = ModInstaller(str(Path(self.temp.name) / "game"), "Modded Cars")
        with patch("core.installer.find_7zip", return_value=None):
            with self.assertRaises(SevenZipNotFoundError) as ctx:
                installer.extract_archive(str(rar))
        self.assertEqual(ctx.exception.error_code, "seven_zip_missing")
        self.assertIn("7-zip.org", ctx.exception.download_url)

    def test_inspect_rar_without_7zip_returns_error_code(self):
        from core.installer import ModInstaller
        rar = Path(self.temp.name) / "mod.rar"
        rar.write_bytes(b"Rar!\x1a")
        installer = ModInstaller(str(Path(self.temp.name) / "game"), "Modded Cars")
        with patch("core.installer.find_7zip", return_value=None):
            res = installer.inspect_source(str(rar))
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "seven_zip_missing")
        self.assertIn("7-zip.org", res["download_url"])

    def test_status_payload_includes_seven_zip(self):
        from core.seven_zip import get_7zip_status
        with patch("core.seven_zip.find_7zip", return_value=None):
            status = get_7zip_status(force_refresh=True)
        self.assertFalse(status["found"])
        self.assertEqual(status["path"], "")
        self.assertIn(".rar", status["required_for"])
        self.assertIn(".7z", status["required_for"])


class DesktopEntryRegression(unittest.TestCase):
    def test_server_exposes_single_main(self):
        import server
        self.assertTrue(callable(server.main))
        self.assertTrue(callable(server.start_desktop_app))
        self.assertTrue(callable(server.start_server))

    def test_desktop_wrappers_import_server_main(self):
        import app_desktop
        import server as srv
        self.assertIs(app_desktop.main, srv.main)


class LanguageSettingsRegression(unittest.TestCase):
    def test_core_i18n_normalization_and_support(self):
        from core.i18n import (
            normalize_language, is_supported, language_catalog, pick_localized
        )
        self.assertEqual(normalize_language("en"), "en")
        self.assertEqual(normalize_language("EN"), "en")
        self.assertEqual(normalize_language("en-US"), "en")
        self.assertEqual(normalize_language("en_US"), "en")
        self.assertEqual(normalize_language("fr", default="en"), "en")
        self.assertEqual(normalize_language(None, default="en"), "en")
        self.assertEqual(normalize_language("", default="en"), "en")

        self.assertTrue(is_supported("en"))
        self.assertTrue(is_supported("en-US"))
        self.assertFalse(is_supported("unknown"))
        self.assertFalse(is_supported(""))
        self.assertFalse(is_supported(None))

        cat = language_catalog()
        self.assertGreaterEqual(len(cat), 1)
        ids = [c["id"] for c in cat]
        self.assertIn("en", ids)

        item = {"label_en": "Test", "label": "Default"}
        self.assertEqual(pick_localized(item, field="label", lang="en"), "Test")
        self.assertEqual(pick_localized({"en": "English", "es": "Spanish"}, lang="en"), "English")

    def test_api_languages_handler(self):
        import server
        from server import ModManagerHandler

        handler = ModManagerHandler.__new__(ModManagerHandler)
        handler.path = "/api/languages"
        handler.headers = {}
        sent_data = []
        handler._send_json = lambda d: sent_data.append(d)
        handler.do_GET()

        self.assertTrue(sent_data[0]["success"])
        self.assertIn("language", sent_data[0])
        self.assertIn("default_language", sent_data[0])
        self.assertIsInstance(sent_data[0]["languages"], list)

    @patch("server.save_config")
    def test_api_config_language_session_and_default(self, mock_save):
        import io
        import json
        import server
        from server import ModManagerHandler

        orig_lang = server.LANGUAGE
        orig_def = server.DEFAULT_LANGUAGE
        try:
            with patch.dict("core.i18n.LANGUAGES", {"es": {"id": "es", "name": "Spanish"}}, clear=False):
                # 1. Session-only language switch
                handler = ModManagerHandler.__new__(ModManagerHandler)
                handler.path = "/api/config/language"
                payload = json.dumps({"language": "es", "set_default": False}).encode("utf-8")
                handler.headers = {"Content-Length": str(len(payload))}
                handler.rfile = io.BytesIO(payload)
                sent_data = []
                handler._send_json = lambda d: sent_data.append(d)
                handler.do_POST()

                self.assertTrue(sent_data[0]["success"])
                self.assertEqual(sent_data[0]["language"], "es")
                self.assertEqual(server.LANGUAGE, "es")
                mock_save.assert_not_called()

                # 2. Set default language switch
                mock_save.reset_mock()
                handler2 = ModManagerHandler.__new__(ModManagerHandler)
                handler2.path = "/api/config/language"
                payload2 = json.dumps({"language": "es", "set_default": True}).encode("utf-8")
                handler2.headers = {"Content-Length": str(len(payload2))}
                handler2.rfile = io.BytesIO(payload2)
                sent_data2 = []
                handler2._send_json = lambda d: sent_data2.append(d)
                handler2.do_POST()

                self.assertTrue(sent_data2[0]["success"])
                self.assertEqual(sent_data2[0]["language"], "es")
                self.assertEqual(sent_data2[0]["default_language"], "es")
                self.assertEqual(server.LANGUAGE, "es")
                self.assertEqual(server.DEFAULT_LANGUAGE, "es")
                mock_save.assert_called_with(language="es", default_language="es")
        finally:
            server.LANGUAGE = orig_lang
            server.DEFAULT_LANGUAGE = orig_def


class ModFolderRenameRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rename_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        self.modloader = self.game / "modloader"
        self.mod_dir = self.modloader / "Modded Cars" / "BF Club"
        self.mod_dir.mkdir(parents=True)
        (self.mod_dir / "bfclub.dff").write_bytes(b"dff")
        (self.mod_dir / "readme.txt").write_text("hello", encoding="utf-8")

    def test_validate_mod_folder_name_rules(self):
        self.assertIsNone(validate_mod_folder_name("BF Club"))
        self.assertIsNone(validate_mod_folder_name("宝马 M3"))
        self.assertIsNotNone(validate_mod_folder_name(""))
        self.assertIsNotNone(validate_mod_folder_name("   "))
        self.assertIsNotNone(validate_mod_folder_name("bad/name"))
        self.assertIsNotNone(validate_mod_folder_name("bad\\name"))
        self.assertIsNotNone(validate_mod_folder_name("bad:name"))
        self.assertIsNotNone(validate_mod_folder_name("bad?name"))
        self.assertIsNotNone(validate_mod_folder_name("trail."))
        self.assertIsNotNone(validate_mod_folder_name("."))
        self.assertIsNotNone(validate_mod_folder_name(".."))
        self.assertIsNotNone(validate_mod_folder_name("con"))
        self.assertIsNotNone(validate_mod_folder_name("COM1"))
        self.assertIsNotNone(validate_mod_folder_name("lpt9"))
        self.assertIsNotNone(validate_mod_folder_name("x" * 101))

    def test_rename_moves_folder_and_reports_paths(self):
        res = rename_mod_folder(str(self.mod_dir), "BF Club Turbo", str(self.modloader))
        self.assertTrue(res["success"])
        self.assertFalse(res["unchanged"])
        self.assertEqual(res["new_name"], "BF Club Turbo")
        new_path = Path(res["new_path"])
        self.assertTrue(new_path.is_dir())
        self.assertFalse(self.mod_dir.exists())
        self.assertEqual((new_path / "bfclub.dff").read_bytes(), b"dff")
        self.assertEqual((new_path / "readme.txt").read_text(encoding="utf-8"), "hello")
        self.assertEqual(res["rel_path"], os.path.join("Modded Cars", "BF Club Turbo"))

    def test_rename_same_name_is_successful_noop(self):
        res = rename_mod_folder(str(self.mod_dir), "BF Club", str(self.modloader))
        self.assertTrue(res["success"])
        self.assertTrue(res["unchanged"])
        self.assertTrue(self.mod_dir.is_dir())

    def test_rename_rejects_illegal_names(self):
        for bad in ["", "   ", "bad/name", "bad\\name", "bad:name", "con", "COM1", "trail.", "x" * 101]:
            res = rename_mod_folder(str(self.mod_dir), bad, str(self.modloader))
            self.assertFalse(res["success"], msg=f"name {bad!r} must be rejected")
            self.assertTrue(self.mod_dir.is_dir(), msg=f"folder must survive {bad!r}")

    def test_rename_rejects_existing_target_and_outside_paths(self):
        (self.modloader / "Modded Cars" / "Taken").mkdir()
        res = rename_mod_folder(str(self.mod_dir), "Taken", str(self.modloader))
        self.assertFalse(res["success"])
        self.assertTrue(self.mod_dir.is_dir())

        outside = Path(self.temp.name) / "elsewhere"
        outside.mkdir()
        res_outside = rename_mod_folder(str(outside), "Renamed", str(self.modloader))
        self.assertFalse(res_outside["success"])
        self.assertTrue(outside.is_dir())

        res_root = rename_mod_folder(str(self.modloader), "RenamedRoot", str(self.modloader))
        self.assertFalse(res_root["success"])
        self.assertTrue(self.modloader.is_dir())

    @unittest.skipUnless(os.name == "nt", "Windows-only case rename semantics")
    def test_case_only_rename_on_windows(self):
        res = rename_mod_folder(str(self.mod_dir), "bf club", str(self.modloader))
        self.assertTrue(res["success"])
        entries = os.listdir(self.modloader / "Modded Cars")
        self.assertIn("bf club", entries)
        self.assertNotIn("BF Club", entries)

    def test_api_rename_endpoint(self):
        import io
        import json
        import server

        handler = server.ModManagerHandler.__new__(server.ModManagerHandler)
        payload = json.dumps({"path": str(self.mod_dir), "new_name": "BF Club API"}).encode("utf-8")
        handler.path = "/api/mods/rename"
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        sent = []
        handler._send_json = lambda data, status=200: sent.append((data, status))

        with patch.object(server, "GAME_PATH", str(self.game)):
            handler.do_POST()

        self.assertTrue(sent[0][0]["success"])
        self.assertEqual(sent[0][0]["new_name"], "BF Club API")
        self.assertTrue(Path(sent[0][0]["new_path"]).is_dir())

    def test_api_rename_endpoint_missing_path(self):
        import io
        import json
        import server

        handler = server.ModManagerHandler.__new__(server.ModManagerHandler)
        payload = json.dumps({"new_name": "Whatever"}).encode("utf-8")
        handler.path = "/api/mods/rename"
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        sent = []
        handler._send_json = lambda data, status=200: sent.append((data, status))

        with patch.object(server, "GAME_PATH", str(self.game)):
            handler.do_POST()

        self.assertFalse(sent[0][0]["success"])
        self.assertEqual(sent[0][1], 400)


class FlaDetectionRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fla_test_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        self.manager = FLAManager(str(self.game))

    def test_open_limit_adjuster_is_not_detected_as_fla(self):
        ola = self.game / "modloader" / "Open Limit Adjuster"
        ola.mkdir(parents=True)
        (ola / "III.VC.SA.LimitAdjuster.asi").write_bytes(b"x")
        (ola / "III.VC.SA.LimitAdjuster.ini").write_text("; ola\n", encoding="utf-8")
        info = self.manager.find_fla_installation()
        self.assertFalse(info["installed"])
        self.assertFalse(info["has_asi"])
        self.assertFalse(info["has_ini"])

    def test_fastman92_asi_and_ini_are_detected(self):
        (self.game / "$fastman92limitAdjuster.asi").write_bytes(b"x")
        (self.game / "fastman92limitAdjuster_GTASA.ini").write_text("; fla\n", encoding="utf-8")
        info = self.manager.find_fla_installation()
        self.assertTrue(info["installed"])
        self.assertTrue(info["has_asi"])
        self.assertTrue(info["has_ini"])
        self.assertFalse(info["ini_orphaned"])
        self.assertFalse(info["is_pending_launch"])

    def test_fastman92_asi_in_modloader_is_detected(self):
        folder = self.game / "modloader" / "FLA"
        folder.mkdir(parents=True)
        (folder / "fastman92limitAdjuster.asi").write_bytes(b"x")
        info = self.manager.find_fla_installation()
        self.assertTrue(info["installed"])
        self.assertTrue(info["has_asi"])
        self.assertTrue(info["is_pending_launch"])

    def test_asi_without_ini_is_pending_launch(self):
        (self.game / "$fastman92limitAdjuster.asi").write_bytes(b"x")
        info = self.manager.find_fla_installation()
        self.assertTrue(info["installed"])
        self.assertTrue(info["is_pending_launch"])
        self.assertFalse(info["ini_orphaned"])

    def test_orphan_ini_alone_is_not_installed_and_loaders_stay_off(self):
        (self.game / "fastman92limitAdjuster_GTASA.ini").write_text(
            "[SOME]\nEnable vehicle audio loader = 1\nEnable model special feature loader = 1\n",
            encoding="utf-8")
        info = self.manager.find_fla_installation()
        self.assertFalse(info["installed"])
        self.assertFalse(info["has_asi"])
        self.assertTrue(info["has_ini"])
        self.assertTrue(info["ini_orphaned"])

        status = self.manager.get_fla_status()
        self.assertFalse(status["installed"])
        self.assertTrue(status["ini_orphaned"])
        self.assertFalse(status["audio_loader_enabled"])
        self.assertFalse(status["special_loader_enabled"])


class InspectorConfigResolutionRegression(unittest.TestCase):
    VANILLA_HANDLING = ("SUPERGT      1400.0    2800.0   2.0    0.0 -0.2 -0.24 70 0.75 0.86 0.48 \t5 230.0 26.0 5.0  "
                        "R P \t8.0   0.52 0 30.0  \t1.0  0.20  0.0   0.25 -0.10 0.5  0.3\t\t0.40 0.54 105000 \t40002004\t208000\t\t0  0\t1")
    MOD_HANDLING = ("SUPERGT \t1706.0    2800.0      1.8    0.0 0.0  0.0  70  0.70 0.80 0.54      5 200.0 26.0 15.0  4 P   "
                    "7.0   0.60 0 40.0      1.0  0.12  0.0  0.25 -0.06 0.60 0.5            0.25 0.60 50000     80222004   00000000                  3  0  1")
    SHADOW_HANDLING = ("SUPERGT \t9999.0    2800.0      1.8    0.0 0.0  0.0  70  0.70 0.80 0.54      5 210.0 26.0 15.0  4 P  "
                       "7.0   0.60 0 40.0      1.0  0.12  0.0  0.25 -0.06 0.60 0.5            0.25 0.60 50000     80222004   00000000                  3  0  1")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="inspect_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n506, supergt, supergt, car, SUPERGT, SUPERGT, null, normal, 5, 0, 0, -1, 0.78, 0.78, 0\nend\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text(
            "; header\n" + self.VANILLA_HANDLING + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text(
            "col\nend\ncar\nsupergt, 1, 1\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text(
            "mods\nsupergt, bnt_b_sc_l\nend\nlink\nend\n", encoding="utf-8")
        (self.game / "data" / "shopping.dat").write_text(
            "section prices\nsection CarMods\n"
            "nto_b_l BMBLN respect 0 sexy 0 777\n"
            "nto_b_s BMBSM respect 0 sexy 0 200\n"
            "end\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        self.mod_dir = self.shadow / "OniK" / "1992 Maibatsu Super GT"
        self.mod_dir.mkdir(parents=True)
        (self.mod_dir / "supergt.dff").write_bytes(b"dff")
        (self.mod_dir / "supergt_dat.txt").write_text(
            "handling.cfg\n----------------\n" + self.MOD_HANDLING + "\n\n"
            "vehicles.ide\n----------------\n"
            "506, supergt, supergt, car, SUPERGT, SUPERGT, null, executive, 5, 0, 0, -1, 0.78, 0.78, 0\n\n"
            "carcols.dat\n----------------\nsupergt, 42,42, 6,42, 14,42\n\n"
            "carmods.dat\n----------------\nsupergt, nto_b_l, nto_b_s, nto_b_tw, spl_custom_x\n\n"
            "veh_mods.ide\n----------------\nobjs\n12345, spl_custom_x, custom, 100, 2097152\nend\n",
            encoding="utf-8")

    def _detail(self):
        import server
        orig_merger = server.merger
        orig_shadow = server.shadow_dir
        backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        server.shadow_dir = str(self.shadow)
        server.merger = ConfigMerger(str(self.shadow), str(self.game), backup_manager=backup)
        try:
            handler = server.ModManagerHandler.__new__(server.ModManagerHandler)
            handler.path = "/api/mod-detail?" + urllib.parse.urlencode({"full_path": str(self.mod_dir)})
            handler.headers = {}
            sent = []
            handler._send_json = lambda data, status=200: sent.append((data, status))
            handler.do_GET()
        finally:
            server.merger = orig_merger
            server.shadow_dir = orig_shadow
        self.assertTrue(sent, "mod-detail handler produced no response")
        return sent[0][0]

    def test_unmerged_txt_preset_is_used_for_inspection(self):
        detail = self._detail()
        self.assertTrue(detail.get("success"), detail)
        active = detail["active_configs"]
        self.assertEqual(active["handling"]["source"], "mod")
        self.assertIn("1706.0", active["handling"]["raw"])
        self.assertEqual(active["handling"]["decomposed"]["mass_kg"], 1706.0)
        self.assertEqual(active["carcols"]["source"], "mod")
        self.assertIn("42", active["carcols"]["raw"])
        self.assertEqual(active["carmods"]["source"], "mod")
        self.assertIn("nto_b_l", active["carmods"]["raw"])
        self.assertEqual(active["vehicles_ide"]["source"], "mod")

        # Parts are enriched with the real shopping price and author .ide IDs.
        parts = {p["part_name"]: p for p in active["carmods"]["decomposed"]["parts"]}
        self.assertEqual(parts["nto_b_l"]["shopping_price"], 777)
        self.assertTrue(parts["nto_b_l"]["shopping_registered"])
        self.assertEqual(parts["spl_custom_x"]["model_id"], 12345)
        self.assertEqual(parts["spl_custom_x"]["ide_source"], "mod")

    def test_shadow_override_still_wins_over_txt_preset(self):
        (self.shadow / "handling.cfg").write_text("; header\n" + self.SHADOW_HANDLING + "\n", encoding="utf-8")
        detail = self._detail()
        self.assertTrue(detail.get("success"), detail)
        active = detail["active_configs"]
        self.assertEqual(active["handling"]["source"], "shadow")
        self.assertIn("9999.0", active["handling"]["raw"])

    def test_baseline_identical_shadow_carmods_falls_back_to_txt_preset(self):
        # A full shadow copy is created during merges; its untouched line for
        # this vehicle is identical to vanilla and must not hide the mod's own
        # carmods preset (regression: tuning card showed only 1 part).
        (self.shadow / "carmods.dat").write_text(
            "mods\nsupergt, bnt_b_sc_l\nend\nlink\nend\n", encoding="utf-8")
        detail = self._detail()
        self.assertTrue(detail.get("success"), detail)
        active = detail["active_configs"]
        self.assertEqual(active["carmods"]["source"], "mod")
        self.assertIn("nto_b_l", active["carmods"]["raw"])
        self.assertIn("nto_b_tw", active["carmods"]["raw"])


class ActiveConfigSourceRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="src_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n506, supergt, supergt, car, SUPERGT, SUPERGT, null, normal, 5, 0, 0, -1, 0.78, 0.78, 0\nend\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("SUPERGT") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("col\nend\ncar\nsupergt, 1, 1\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nsupergt, nto_b_s\nend\nlink\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        # Full baseline copies in the shadow (as _ensure_shadow_file creates).
        for name in ("vehicles.ide", "handling.cfg", "carcols.dat", "carmods.dat"):
            shutil.copy2(self.game / "data" / name, self.shadow / name)
        self.merger = ConfigMerger(str(self.shadow), str(self.game))

    def test_identical_shadow_copy_reports_vanilla_source(self):
        cfg = self.merger.get_vehicle_active_configs("supergt")
        for key in ("vehicles_ide", "handling", "carcols", "carmods"):
            self.assertIsNotNone(cfg[key], key)
            self.assertEqual(cfg[key]["source"], "vanilla", key)

    def test_customized_shadow_line_reports_shadow_source(self):
        (self.shadow / "carmods.dat").write_text(
            "mods\nsupergt, nto_b_l, nto_b_s, nto_b_tw\nend\nlink\nend\n", encoding="utf-8")
        cfg = self.merger.get_vehicle_active_configs("supergt")
        self.assertEqual(cfg["carmods"]["source"], "shadow")
        self.assertIn("nto_b_l", cfg["carmods"]["raw"])


class CardDensitySettingsRegression(unittest.TestCase):
    def test_normalize_card_density(self):
        import server
        self.assertEqual(server.normalize_card_density("compact"), "compact")
        self.assertEqual(server.normalize_card_density("COMFORTABLE"), "comfortable")
        self.assertEqual(server.normalize_card_density("nonsense"), "comfortable")
        self.assertEqual(server.normalize_card_density(None), "comfortable")

    def test_card_density_roundtrip_and_api(self):
        import io
        import json
        import server

        temp = tempfile.TemporaryDirectory(prefix="density_")
        self.addCleanup(temp.cleanup)
        config = Path(temp.name) / "config.json"
        orig_path = server.CONFIG_PATH
        orig_density = server.CARD_DENSITY
        server.CONFIG_PATH = str(config)
        try:
            server.save_config(card_density="compact")
            self.assertEqual(server.load_saved_config()["card_density"], "compact")

            server.save_config(card_density="bogus")
            self.assertEqual(server.load_saved_config()["card_density"], "comfortable")

            handler = server.ModManagerHandler.__new__(server.ModManagerHandler)
            payload = json.dumps({"density": "compact"}).encode("utf-8")
            handler.path = "/api/config/card-density"
            handler.headers = {"Content-Length": str(len(payload))}
            handler.rfile = io.BytesIO(payload)
            sent = []
            handler._send_json = lambda data, status=200: sent.append((data, status))
            handler.do_POST()
            self.assertTrue(sent[0][0]["success"])
            self.assertEqual(server.CARD_DENSITY, "compact")
            self.assertEqual(server.load_saved_config()["card_density"], "compact")
        finally:
            server.CONFIG_PATH = orig_path
            server.CARD_DENSITY = orig_density


class ShoppingPriceRegression(unittest.TestCase):
    def test_shadow_price_overrides_vanilla(self):
        temp = tempfile.TemporaryDirectory(prefix="shop_")
        self.addCleanup(temp.cleanup)
        game = Path(temp.name) / "game"
        (game / "data").mkdir(parents=True)
        shadow = game / "modloader" / "Modded Cars"
        shadow.mkdir(parents=True)
        (game / "data" / "shopping.dat").write_text(
            "section prices\nsection CarMods\n"
            "nto_b_l BMBLN respect 0 sexy 0 500\n"
            "nto_b_s BMBSM respect 0 sexy 0 200\n"
            "end\nend\n", encoding="utf-8")
        (shadow / "shopping.dat").write_text(
            "section prices\nsection CarMods\n"
            "nto_b_s BMBSM respect 0 sexy 0 999\n"
            "end\nend\n", encoding="utf-8")

        prices = TuningManager(str(shadow), str(game)).get_shopping_prices()
        self.assertEqual(prices.get("nto_b_s"), 999)
        self.assertEqual(prices.get("nto_b_l"), 500)


class ScannerAudioBadgeRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scanaudio_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "modloader" / "Modded Cars").mkdir(parents=True)
        (self.game / "data" / "gtasa_vehicleAudioSettings.cfg").write_text(
            VANILLA_AUDIO_SETTINGS["landstal"] + "\n", encoding="utf-8")
        self.scanner = ModScanner(str(self.game / "modloader" / "Modded Cars"), str(self.game))

    def _make_mod(self, name, readme=None):
        mod = self.game / "modloader" / "Modded Cars" / name
        mod.mkdir()
        (mod / "landstal.dff").write_bytes(b"dff")
        if readme:
            (mod / "readme.txt").write_text(readme, encoding="utf-8")
        return mod

    def test_vanilla_audio_baseline_row_is_not_custom_audio(self):
        self._make_mod("PlainLandstal")
        mods = self.scanner.scan_installed_mods()
        self.assertEqual(len(mods), 1)
        self.assertFalse(mods[0]["fla_has_audio"])

    def test_txt_audio_preset_marks_custom_audio(self):
        self._make_mod(
            "AudioLandstal",
            "vehicle audio settings\nlandstal 0 95 94 0 0.7 1.0 1 0.890899 4 0 1 0 11 0.0\n")
        mods = self.scanner.scan_installed_mods()
        self.assertEqual(len(mods), 1)
        self.assertTrue(mods[0]["fla_has_audio"])


class IdPoolLogicRegression(unittest.TestCase):
    def _make_game(self):
        temp = tempfile.TemporaryDirectory(prefix="idpool_")
        self.addCleanup(temp.cleanup)
        game = Path(temp.name) / "game"
        (game / "data").mkdir(parents=True)
        (game / "modloader" / "Modded Cars").mkdir(parents=True)
        (game / "data" / "vehicles.ide").write_text("cars\nend\n", encoding="utf-8")
        return game

    @staticmethod
    def _ide(model, mid, name=None):
        n = name or model
        return f"{mid}, {model}, {model}, car, {n.upper()}, {n.upper()}, null, normal, 5, 0, 0, -1, 0.7, 0.7, 0\n"

    def _manager(self, game, limit=None):
        mgr = IdManager(str(game))
        if limit is not None:
            mgr.fla_status = {"apply_id_limit_patch": True, "count_of_killable_model_ids": limit}
        return mgr

    def test_addon_allocation_prefers_safe_window_below_killable_limit(self):
        game = self._make_game()
        shadow = game / "modloader" / "Modded Cars"
        (shadow / "vehicles.ide").write_text(
            "cars\n" + self._ide("car_a", 12093) + self._ide("car_b", 12700) + "end\n",
            encoding="utf-8")
        mgr = self._manager(game, limit=12600)
        self.assertEqual(mgr.allocate_free_addon_ids(1), [12094])

    def test_allocation_uses_over_cap_ids_only_as_last_resort(self):
        game = self._make_game()
        shadow = game / "modloader" / "Modded Cars"
        lines = ["cars"]
        for i in range(12093, 12601):
            lines.append(self._ide(f"car_{i}", i))
        lines.append("end")
        (shadow / "vehicles.ide").write_text("\n".join(lines) + "\n", encoding="utf-8")
        mgr = self._manager(game, limit=12600)
        self.assertEqual(mgr.allocate_free_addon_ids(1), [12601])
        stats = mgr.get_stats()
        self.assertEqual(stats["killable_limit"], 12600)
        self.assertTrue(stats["next_recommended_addon_over_limit"])
        self.assertEqual(stats["total_free_safe"],
                         sum(g["count"] for g in mgr.cached_gaps if not g.get("over_killable_limit")))

    def test_free_gaps_split_at_zone_edges_and_killable_cap(self):
        game = self._make_game()
        shadow = game / "modloader" / "Modded Cars"
        (shadow / "vehicles.ide").write_text(
            "cars\n" + self._ide("x1", 11000) + self._ide("x2", 11700) + self._ide("x3", 12700) + "end\n",
            encoding="utf-8")
        mgr = self._manager(game, limit=12600)
        mgr.scan_all_ides(force_refresh=True)
        gaps = mgr.cached_gaps
        seg_general = next((g for g in gaps if g["start"] == 11001), None)
        seg_tuning = next((g for g in gaps if g["start"] == 11682), None)
        seg_over = next((g for g in gaps if g["start"] == 12600), None)
        self.assertIsNotNone(seg_general)
        self.assertEqual(seg_general["end"], 11681)
        self.assertEqual(seg_general["category"], "general")
        self.assertIsNotNone(seg_tuning)
        self.assertEqual(seg_tuning["end"], 11699)
        self.assertEqual(seg_tuning["category"], "tuning")
        self.assertIsNotNone(seg_over)
        self.assertTrue(seg_over["over_killable_limit"])
        self.assertFalse(seg_over["recommended"])

    def test_prose_txt_without_config_header_does_not_occupy_ids(self):
        game = self._make_game()
        mod = game / "modloader" / "Addon Cars" / "TestMod"
        mod.mkdir(parents=True)
        (mod / "readme.txt").write_text(
            "Thanks for downloading!\n"
            "Example line: 12999, newcar, newcar, car, NEWCAR, NEWCAR, null, normal, 5, 0, 0, -1, 0.7, 0.7, 0\n",
            encoding="utf-8")
        records = self._manager(game).scan_all_ides(force_refresh=True)
        self.assertNotIn(12999, records)

    def test_txt_with_config_header_is_accepted(self):
        game = self._make_game()
        mod = game / "modloader" / "Addon Cars" / "TestMod"
        mod.mkdir(parents=True)
        (mod / "add.txt").write_text(
            "vehicles.ide\n" + self._ide("newcar", 12999) + "\nhandling.cfg\n",
            encoding="utf-8")
        records = self._manager(game).scan_all_ides(force_refresh=True)
        self.assertIn(12999, records)

    def test_headerless_txt_with_real_asset_is_accepted(self):
        # Author snippets without a header are common; a matching DFF proves
        # the declaration is real (regression: header-only gate dropped 23
        # installed addon IDs).
        game = self._make_game()
        mod = game / "modloader" / "Addon Cars" / "TestMod"
        mod.mkdir(parents=True)
        (mod / "trinity.txt").write_text(self._ide("trinity", 12156), encoding="utf-8")
        (mod / "trinity.dff").write_bytes(b"dff")
        records = self._manager(game).scan_all_ides(force_refresh=True)
        self.assertIn(12156, records)

    def test_ide_declaration_wins_over_same_model_txt(self):
        game = self._make_game()
        mod = game / "modloader" / "Addon Cars" / "TestMod"
        mod.mkdir(parents=True)
        (mod / "extra.ide").write_text("cars\n" + self._ide("newcar", 12500) + "end\n", encoding="utf-8")
        (mod / "readme.txt").write_text(
            "vehicles.ide\n" + self._ide("newcar", 12999), encoding="utf-8")
        records = self._manager(game).scan_all_ides(force_refresh=True)
        self.assertIn(12500, records)
        self.assertNotIn(12999, records)

    def test_installer_leaves_no_phantom_txt_id(self):
        game = self._make_game()
        for name, text in {
            "handling.cfg": "; h\n",
            "carcols.dat": "col\nend\ncar\nend\n",
            "carmods.dat": "mods\nend\nlink\nend\n",
            "shopping.dat": "section prices\nsection CarMods\nend\nend\n",
        }.items():
            (game / "data" / name).write_text(text, encoding="utf-8")
        src = Path(game).parent / "src"
        src.mkdir()
        (src / "newcar.dff").write_bytes(b"dff")
        (src / "readme.txt").write_text(
            "vehicles.ide\n" + self._ide("newcar", 12999), encoding="utf-8")
        backup = BackupManager(backup_dir=str(Path(game).parent / "backups"), game_dir=str(game))
        installer = ModInstaller(str(game), "Modded Cars", backup_manager=backup)
        res = installer.execute_install({
            "inspect_dir": str(src), "target_category": "Addon Cars", "folder_name": "NewCar",
            "vehicles": [{"source_model": "newcar", "target_model": "newcar",
                          "category": "Addon Cars", "addon_id": 12500,
                          "generate_fxt": False, "merge_fla": False}],
        })
        self.assertTrue(res["success"], res)
        records = self._manager(game).scan_all_ides(force_refresh=True)
        self.assertIn(12500, records)
        self.assertNotIn(12999, records)


class ReplaceToAddonConversionRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="convert_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n436, previon, previon, car, PREVION, PREVION, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0\nend\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("PREVION") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("col\nend\ncar\nprevion, 1, 1\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nprevion, nto_b_s\nend\nlink\nend\n", encoding="utf-8")
        (self.game / "data" / "shopping.dat").write_text("section prices\nsection CarMods\nend\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.source = Path(self.temp.name) / "src"
        self.source.mkdir()
        (self.source / "previon.dff").write_bytes(b"dff")
        (self.source / "previon.txd").write_bytes(b"txd")
        custom_handling = handling("PREVION").replace("1500.0", "9999.0", 1)
        (self.source / "readme.txt").write_text(
            "vehicles.ide\n436, previon, previon, car, PREVION, PREVION, null, normal, 10, 0, 0, -1, 0.7, 0.7, 0\n\n"
            "handling.cfg\n" + custom_handling + "\n\n"
            "carcols.dat\nprevion, 42, 42\n\n"
            "carmods.dat\nprevion, nto_b_l, nto_b_s\n",
            encoding="utf-8")
        self.backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup)

    def payload(self, **over):
        veh = {
            "source_model": "previon", "target_model": "previonadd", "target_txd": "previontxd",
            "category": "Addon Cars", "addon_id": 12345,
            "fxt_key": "PREVADD", "fxt_name": "Previon Add",
            "generate_fxt": True, "merge_fla": False,
        }
        veh.update(over)
        return {"inspect_dir": str(self.source), "target_category": "Addon Cars",
                "folder_name": "PrevionAdd", "vehicles": [veh]}

    def test_replace_mod_converted_to_addon_isolates_everything(self):
        res = self.installer.execute_install(self.payload())
        self.assertTrue(res["success"], res)

        addon_dir = self.game / "modloader" / "Addon Cars" / "PrevionAdd"
        self.assertTrue((addon_dir / "previonadd.dff").is_file())
        self.assertTrue((addon_dir / "previontxd.txd").is_file())
        self.assertFalse((addon_dir / "previon.dff").exists())

        ide_text = (self.shadow / "vehicles.ide").read_text(encoding="utf-8-sig")
        line = next(l for l in ide_text.splitlines() if "previonadd" in l.lower())
        dec = DualTrackParser().decompose_ide(line)
        self.assertEqual(dec["id"], 12345)
        self.assertEqual(dec["model_name"], "previonadd")
        self.assertEqual(dec["txd_name"], "previontxd")
        self.assertEqual(dec["handling_id"], "PREVIONADD")
        self.assertEqual(dec["game_name"], "PREVADD")

        hand = (self.shadow / "handling.cfg").read_text(encoding="utf-8-sig")
        new_line = next(l for l in hand.splitlines() if l.strip().upper().startswith("PREVIONADD"))
        self.assertIn("9999.0", new_line)
        old_line = next(l for l in hand.splitlines() if l.strip().upper().startswith("PREVION "))
        self.assertIn("1500.0", old_line)
        self.assertNotIn("PREVIONADD", (self.game / "data" / "handling.cfg").read_text(encoding="utf-8-sig"))

        carcols = (self.shadow / "carcols.dat").read_text(encoding="utf-8-sig")
        self.assertIn("previonadd", carcols)
        carmods = (self.shadow / "carmods.dat").read_text(encoding="utf-8-sig")
        self.assertIn("previonadd", carmods)

        fxt = (addon_dir / "previonadd.fxt").read_text(encoding="utf-8-sig")
        self.assertIn("PREVADD Previon Add", fxt)

    def test_conversion_rejects_existing_model_name(self):
        self.shadow.mkdir(parents=True, exist_ok=True)
        (self.shadow / "vehicles.ide").write_text(
            "cars\n12100, taken1, taken1, car, TAKEN1, TAKEN1, null, normal, 5, 0, 0, -1, 0.7, 0.7, 0\nend\n",
            encoding="utf-8")
        res = self.installer.execute_install(self.payload(target_model="taken1", target_txd="taken1"))
        self.assertFalse(res["success"])
        self.assertIn("occupied", res.get("error", "").lower())

    def test_conversion_rejects_invalid_model_name(self):
        res = self.installer.execute_install(self.payload(target_model="previon!"))
        self.assertFalse(res["success"])
        self.assertIn("invalid", res.get("error", "").lower())

    def test_conversion_uses_explicit_handling_and_gxt_key(self):
        res = self.installer.execute_install(self.payload(target_handling="PREVADD2", fxt_key="PREVAD2"))
        self.assertTrue(res["success"], res)
        ide_text = (self.shadow / "vehicles.ide").read_text(encoding="utf-8-sig")
        line = next(l for l in ide_text.splitlines() if "previonadd" in l.lower())
        dec = DualTrackParser().decompose_ide(line)
        self.assertEqual(dec["handling_id"], "PREVADD2")
        self.assertEqual(dec["game_name"], "PREVAD2")
        hand = (self.shadow / "handling.cfg").read_text(encoding="utf-8-sig")
        new_line = next(l for l in hand.splitlines() if l.strip().upper().startswith("PREVADD2"))
        self.assertIn("9999.0", new_line)
        self.assertFalse(any(l.strip().upper().startswith("PREVIONADD") for l in hand.splitlines()))

    def test_conversion_rejects_bad_handling_id(self):
        res = self.installer.execute_install(self.payload(target_handling="bad handling!"))
        self.assertFalse(res["success"])
        self.assertIn("Handling", res.get("error", ""))

    def test_conversion_rejects_overlong_gxt_key(self):
        res = self.installer.execute_install(self.payload(fxt_key="EIGHTKEY"))
        self.assertFalse(res["success"])
        self.assertIn("GXT", res.get("error", ""))

    def test_derived_handling_id_is_truncated_to_14(self):
        long_name = "previonaddlongmodel"
        res = self.installer.execute_install(self.payload(target_model=long_name, target_txd=long_name))
        self.assertTrue(res["success"], res)
        ide_text = (self.shadow / "vehicles.ide").read_text(encoding="utf-8-sig")
        line = next(l for l in ide_text.splitlines() if long_name in l.lower())
        dec = DualTrackParser().decompose_ide(line)
        self.assertEqual(dec["handling_id"], long_name.upper()[:14])
        self.assertEqual(len(dec["handling_id"]), 14)


class AddonToReplaceConversionRegression(unittest.TestCase):
    """Reverse conversion: an addon package (recurs) installed as a
    replacement of a vanilla vehicle (alpha)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="addon2replace_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n"
            "602, alpha, alpha, car, ALPHA, ALPHA, null, executive, 7, 0, 0, -1, 0.75, 0.75, 0\n"
            "468, sanchez, sanchez, bike, SANCHEZ, SANCHEZ, null, ignore, 10, 0, 0, -1, 0.7, 0.7, 0\n"
            "end\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("ALPHA") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("col\nend\ncar\nalpha, 1, 1\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nalpha, nto_b_s\nend\nlink\nend\n", encoding="utf-8")
        (self.game / "data" / "shopping.dat").write_text("section prices\nsection CarMods\nend\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.source = Path(self.temp.name) / "src"
        self.source.mkdir()
        (self.source / "recurs.dff").write_bytes(b"dff")
        (self.source / "recurs.txd").write_bytes(b"txd")
        custom_handling = handling("RECURS").replace("1500.0", "9999.0", 1)
        # Mirrors the real-world addon package layout: placeholder ID column,
        # the author's own model name in every section.
        (self.source / "readme.txt").write_text(
            "vehicles.ide\n"
            "ID, \trecurs,     recurs,     car,        RECURS,     RECURS,     null, normal,  10, \t0,\t1f10,   -1, 0.67, 0.67, \t0\n\n"
            "handling.cfg\n" + custom_handling + "\n\n"
            "carcols.dat\nrecurs, 42, 42\n\n"
            "carmods.dat\nrecurs, nto_b_l, nto_b_s\n",
            encoding="utf-8")
        self.backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup)

    def payload(self, **over):
        veh = {
            "source_model": "recurs", "target_model": "alpha", "source_type": "car",
            "category": "Modded Cars",
            "fxt_key": "RECURS", "fxt_name": "Recursion",
            "generate_fxt": True, "merge_fla": False,
        }
        folder = over.pop("folder_name", "RecursionGT")
        veh.update(over)
        return {"inspect_dir": str(self.source), "target_category": "Modded Cars",
                "folder_name": folder, "vehicles": [veh]}

    def test_addon_package_installed_as_replacement_rekeys_everything(self):
        res = self.installer.execute_install(self.payload())
        self.assertTrue(res["success"], res)

        dest = self.game / "modloader" / "Modded Cars" / "RecursionGT"
        self.assertTrue((dest / "alpha.dff").is_file())
        self.assertTrue((dest / "alpha.txd").is_file())
        self.assertFalse((dest / "recurs.dff").exists())
        self.assertFalse((dest / "recurs.txd").exists())

        # Handling: the author's RECURS physics re-keyed onto ALPHA's slot.
        hand = (self.shadow / "handling.cfg").read_text(encoding="utf-8-sig")
        alpha_line = next(l for l in hand.splitlines() if l.strip().upper().startswith("ALPHA"))
        self.assertIn("9999.0", alpha_line)
        self.assertNotIn("RECURS", hand.upper())
        self.assertNotIn("9999.0", (self.game / "data" / "handling.cfg").read_text(encoding="utf-8-sig"))

        # Carcols + carmods follow the target model name, not the author's.
        carcols = (self.shadow / "carcols.dat").read_text(encoding="utf-8-sig")
        self.assertIn("alpha, 42, 42", carcols)
        self.assertNotIn("recurs", carcols.lower())
        carmods = (self.shadow / "carmods.dat").read_text(encoding="utf-8-sig")
        self.assertIn("alpha,", carmods.lower())
        self.assertIn("nto_b_l", carmods.lower())
        self.assertNotIn("recurs", carmods.lower())

        # Replacement installs never ADD a vehicles.ide line: alpha's IDE line
        # keeps the target identity (ID/model/txd/handling) with the mod's
        # behavioral columns merged in (class normal, wheel scale 0.67), and
        # the GXT game-name column re-pointed by the payload's fxt_key.
        ide = (self.shadow / "vehicles.ide").read_text(encoding="utf-8-sig")
        alpha_lines = [l for l in ide.splitlines() if l.strip().lower().startswith("602,")]
        self.assertEqual(len(alpha_lines), 1)
        tokens = [t.strip() for t in alpha_lines[0].split(",")]
        self.assertEqual(tokens[:6], ["602", "alpha", "alpha", "car", "ALPHA", "RECURS"])
        self.assertEqual(tokens[6:], ["null", "normal", "10", "0", "1f10", "-1", "0.67", "0.67", "0"])
        for line in ide.splitlines():
            tk = [t.strip() for t in line.split(",")]
            if len(tk) >= 3 and tk[1]:
                self.assertNotEqual(tk[1].lower(), "recurs")

    def test_addon_to_replace_rejects_cross_class_target(self):
        res = self.installer.execute_install(self.payload(target_model="pcj600"))
        self.assertFalse(res["success"])
        self.assertIn("class", res.get("error", "").lower())
        # Nothing was deployed for the rejected install.
        self.assertFalse((self.game / "modloader" / "Modded Cars" / "RecursionGT" / "pcj600.dff").exists())

    def test_addon_to_replace_with_target_gxt_key_keeps_vanilla_identity(self):
        # Default conversion naming: the target's vanilla GXT key paired with
        # the package's display name ("ALPHA Recursion"). The merged shadow
        # IDE line keeps the target's identity columns and adopts the mod's
        # behavioral columns; the vanilla data/ file is never touched.
        res = self.installer.execute_install(self.payload(fxt_key="ALPHA", fxt_name="Recursion"))
        self.assertTrue(res["success"], res)
        shadow_ide = self.shadow / "vehicles.ide"
        self.assertTrue(shadow_ide.exists())
        alpha_lines = [l for l in shadow_ide.read_text(encoding="utf-8-sig").splitlines()
                       if l.strip().lower().startswith("602,")]
        self.assertEqual(len(alpha_lines), 1)
        tokens = [t.strip() for t in alpha_lines[0].split(",")]
        self.assertEqual(tokens[:6], ["602", "alpha", "alpha", "car", "ALPHA", "ALPHA"])
        self.assertEqual(tokens[6:], ["null", "normal", "10", "0", "1f10", "-1", "0.67", "0.67", "0"])
        for line in shadow_ide.read_text(encoding="utf-8-sig").splitlines():
            tk = [t.strip() for t in line.split(",")]
            if len(tk) >= 3 and tk[1]:
                self.assertNotEqual(tk[1].lower(), "recurs")
        game_ide = (self.game / "data" / "vehicles.ide").read_text(encoding="utf-8-sig")
        self.assertIn("ALPHA, ALPHA", game_ide)
        self.assertNotIn("RECURS", game_ide.upper())
        dest = self.game / "modloader" / "Modded Cars" / "RecursionGT"
        fxt_files = list(dest.glob("*.fxt"))
        self.assertTrue(fxt_files)
        text = "".join(f.read_text(encoding="utf-8-sig") for f in fxt_files)
        entry_keys = [line.split()[0].upper() for line in text.splitlines() if line.split()]
        self.assertIn("ALPHA", entry_keys)
        self.assertNotIn("RECURS", entry_keys)
        self.assertIn("ALPHA Recursion", text)

    def test_addon_to_replace_same_class_family_allows_bike(self):
        # A bike package (source_type bike) onto a vanilla bike is legitimate.
        (self.source / "recurs.dff").unlink()
        (self.source / "scooter.dff").write_bytes(b"dff")
        (self.source / "scooter.txd").write_bytes(b"txd")
        readme = (self.source / "readme.txt").read_text(encoding="utf-8")
        readme = readme.replace("recurs", "scooter").replace("RECURS", "SCOOTER")
        (self.source / "readme.txt").write_text(readme, encoding="utf-8")
        res = self.installer.execute_install(self.payload(
            source_model="scooter", target_model="sanchez", source_type="bike",
            folder_name="ScooterGT"))
        self.assertTrue(res["success"], res)
        dest = self.game / "modloader" / "Modded Cars" / "ScooterGT"
        self.assertTrue((dest / "sanchez.dff").is_file())
        hand = (self.shadow / "handling.cfg").read_text(encoding="utf-8-sig")
        sanchez_line = next(l for l in hand.splitlines() if l.strip().upper().startswith("SANCHEZ"))
        self.assertIn("9999.0", sanchez_line)


class ReplacementPackageIdeRegression(unittest.TestCase):
    """A same-name replacement package that ships its own vehicles.ide line.

    The target keeps its identity columns (ID/model/txd/type/handling/game
    name) but adopts the package's behavioral columns - the reported case was a
    package whose class and wheel scale silently never reached the shadow copy.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="replace_ide_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n"
            "602, alpha, alpha, car, ALPHA, ALPHA, null, executive, 10, 0, 0, -1, 0.7, 0.7, 0\n"
            "end\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("ALPHA") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("col\nend\ncar\nalpha, 1, 1\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nalpha, nto_b_s\nend\nlink\nend\n", encoding="utf-8")
        (self.game / "data" / "shopping.dat").write_text("section prices\nsection CarMods\nend\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.source = Path(self.temp.name) / "src"
        self.source.mkdir()
        (self.source / "alpha.dff").write_bytes(b"dff")
        (self.source / "alpha.txd").write_bytes(b"txd")
        self.backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup)

    def author_config(self, ide_line):
        (self.source / "alpha_dat.txt").write_text(
            "vehicles.ide\n" + ide_line + "\n\ncarcols.dat\nalpha, 42, 42\n", encoding="utf-8")

    def payload(self):
        return {"inspect_dir": str(self.source), "target_category": "Modded Cars",
                "folder_name": "1992 Bravado Alpha",
                "vehicles": [{"source_model": "alpha", "target_model": "alpha", "source_type": "car",
                              "category": "Modded Cars", "generate_fxt": False, "merge_fla": False}]}

    def shadow_alpha_tokens(self):
        ide = (self.shadow / "vehicles.ide").read_text(encoding="utf-8-sig")
        lines = [l for l in ide.splitlines() if l.strip().lower().startswith("602,")]
        self.assertEqual(len(lines), 1)
        return [t.strip() for t in lines[0].split(",")]

    def test_same_name_replacement_adopts_the_package_behavioral_columns(self):
        self.author_config("602, alpha, alpha, car, ALPHA, ALPHA, null, normal, 10, 0, 0, -1, 0.78, 0.78, 0")
        res = self.installer.execute_install(self.payload())
        self.assertTrue(res["success"], res)

        tokens = self.shadow_alpha_tokens()
        self.assertEqual(tokens[:6], ["602", "alpha", "alpha", "car", "ALPHA", "ALPHA"])
        self.assertEqual(tokens[6:], ["null", "normal", "10", "0", "0", "-1", "0.78", "0.78", "0"])
        self.assertIn("vehicles.ide", res["applied_configs"])
        # Identity matched, so nothing to warn about.
        self.assertEqual(res["ide_notes"], [])
        # The vanilla data/ file is never touched.
        self.assertIn("executive", (self.game / "data" / "vehicles.ide").read_text(encoding="utf-8-sig"))

    def test_a_foreign_id_and_handling_reference_are_reported(self):
        self.author_config("13000, alpha, alpha, car, ZR350, ALPHA, null, normal, 10, 0, 0, -1, 0.78, 0.78, 0")
        res = self.installer.execute_install(self.payload())
        self.assertTrue(res["success"], res)

        tokens = self.shadow_alpha_tokens()
        self.assertEqual(tokens[:6], ["602", "alpha", "alpha", "car", "ALPHA", "ALPHA"])
        self.assertEqual(tokens[6:], ["null", "normal", "10", "0", "0", "-1", "0.78", "0.78", "0"])
        self.assertEqual(len(res["ide_notes"]), 2)
        self.assertIn("keeps ID 602", res["ide_notes"][0])
        self.assertIn("13000", res["ide_notes"][0])
        self.assertIn("keeps handling 'ALPHA'", res["ide_notes"][1])
        self.assertIn("ZR350", res["ide_notes"][1])
        # The notes are part of the install record as well.
        for note in res["ide_notes"]:
            self.assertIn(note, res["warnings"])

    def test_a_package_that_declares_its_own_model_and_handling_is_not_reported(self):
        # Author placeholders ("ID") and the package's own model name stand for
        # "my own slot/handling line": the installer re-keys both, so warning
        # about them would be noise.
        self.author_config("ID, alpha, alpha, car, ALPHA, ALPHA, null, normal, 10, 0, 0, -1, 0.78, 0.78, 0")
        res = self.installer.execute_install(self.payload())
        self.assertTrue(res["success"], res)
        self.assertEqual(res["ide_notes"], [])

    def test_a_package_without_an_ide_line_leaves_the_line_alone(self):
        (self.source / "alpha_dat.txt").write_text("carcols.dat\nalpha, 42, 42\n", encoding="utf-8")
        res = self.installer.execute_install(self.payload())
        self.assertTrue(res["success"], res)
        # Nothing in this package addresses vehicles.ide, so no shadow copy is
        # created for it and the vanilla line stays as it is.
        self.assertNotIn("vehicles.ide", res["applied_configs"])
        self.assertFalse((self.shadow / "vehicles.ide").exists())
        self.assertEqual(res["ide_notes"], [])
        self.assertIn("executive", (self.game / "data" / "vehicles.ide").read_text(encoding="utf-8-sig"))


class VanillaIdeTypoRegression(unittest.TestCase):
    WAYFARER_LINE = ("586,\twayfarer\twayfarer,\tbike,\t\tWAYFARER,\tWAYFARE,\twayfarer,motorbike,"
                     "\t6,\t0,\t0,\t\t23, 0.654, 0.654,\t-1")

    def test_vanilla_wayfarer_missing_comma_line_is_parsed(self):
        parser = DualTrackParser()
        self.assertTrue(parser._is_ide_line(self.WAYFARER_LINE))
        dec = parser.decompose_ide(self.WAYFARER_LINE)
        self.assertIsNotNone(dec)
        self.assertEqual(dec["id"], 586)
        self.assertEqual(dec["model_name"], "wayfarer")
        self.assertEqual(dec["txd_name"], "wayfarer")
        self.assertEqual(dec["handling_id"], "WAYFARER")
        self.assertEqual(dec["game_name"], "WAYFARE")

    def test_wayfarer_ide_line_is_read_and_updated_in_shadow(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        game = Path(temp.name) / "game"
        (game / "data").mkdir(parents=True)
        (game / "modloader" / "Modded Cars").mkdir(parents=True)
        (game / "data" / "vehicles.ide").write_text(
            "cars\n" + self.WAYFARER_LINE + "\nend\n", encoding="utf-8")
        merger = ConfigMerger(str(game / "modloader" / "Modded Cars"), str(game))
        active = merger.get_vehicle_active_configs("wayfarer")
        self.assertIsNotNone(active["vehicles_ide"])
        self.assertEqual(active["vehicles_ide"]["decomposed"]["handling_id"], "WAYFARER")
        res = merger.save_vehicle_config(
            "wayfarer", "vehicles_ide",
            "586, wayfarer, wayfarer, bike, WAYFARER, WAYFARE, wayfarer, motorbike, 6, 0, 0, 23, 0.654, 0.654, -1")
        self.assertTrue(res.get("success"), res)
        shadow = (game / "modloader" / "Modded Cars" / "vehicles.ide").read_text(encoding="utf-8-sig")
        wayfarer_lines = [l for l in shadow.splitlines() if l.strip().startswith("586,")]
        self.assertEqual(len(wayfarer_lines), 1)
        self.assertIn("wayfarer, wayfarer, bike", wayfarer_lines[0].lower())


class ShoppingRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        self.shadow = self.game / "modloader" / "Modded Cars"
        (self.game / "data").mkdir(parents=True)
        self.shadow.mkdir(parents=True)

        self.sample_shopping = (
            "section prices\n"
            "\tsection CarMods\n"
            "\t\texh_a_s\t\tEXH_A_S\trespect 0 \tsexy 0\t\t350\n"
            "\t\tfbmp_a_s\tFBMP_A1\trespect 0 \tsexy 0\t\t1200\n"
            "\tend\n"
            "\tsection carmod1 # TransFender\n"
            "\ttype CarMods\n"
            "\t\titem exh_a_l\n"
            "\tend\n"
            "\tsection carmod2 # Loco Low Co\n"
            "\ttype CarMods\n"
            "\t\titem exh_lr_sv1\n"
            "\tend\n"
            "\tsection carmod3 # Street Racers\n"
            "\ttype CarMods\n"
            "\t\titem exh_a_s\n"
            "\t\titem fbmp_a_s\n"
            "\tend\n"
            "end\n"
        )
        (self.game / "data" / "shopping.dat").write_text(self.sample_shopping, encoding="utf-8")
        (self.shadow / "shopping.dat").write_text(self.sample_shopping, encoding="utf-8")
        self.merger = ConfigMerger(str(self.shadow), str(self.game))
        self.parser = DualTrackParser()

    def test_parse_shopping_zr350_format(self):
        sample = (
            "-----------------------------------##| SHOPPING.DAT |##----------------------------------\n"
            "\tsection CarMods\n"
            "\t\texh_a_zr\t\tZR2AE\t\trespect 0 \tsexy 0\t850\n"
            "\t\texh_c_zr\t\tZR2CE\t\trespect 0 \tsexy 0\t950\n"
            "\t\twg_l_c_zr\t\tZR2CSI\t\trespect 0 \tsexy 0\t750\t\t\t# END OF ZR350\n"
            "\n"
            "\tsection carmod3\n"
            "\t\titem exh_a_zr\n"
            "\t\titem exh_c_zr\n"
            "\t\titem wg_l_c_zr\t\t\t# END OF ZR350\n"
            "======================================}> CREDITS <{======================================\n"
        )
        parsed = self.parser.parse_text_content(sample)
        self.assertIn("shopping_dat", parsed)
        self.assertGreaterEqual(len(parsed["shopping_dat"]), 5)

        decomp = self.parser.decompose_shopping(parsed["shopping_dat"])
        self.assertEqual(len(decomp["carmods"]), 3)
        self.assertEqual(decomp["carmods"][0]["part_name"], "exh_a_zr")
        self.assertEqual(decomp["carmods"][0]["nametag"], "ZR2AE")
        self.assertEqual(decomp["carmods"][0]["price"], 850)
        self.assertEqual(decomp["carmods"][1]["price"], 950)

        self.assertIn("carmod3", decomp["workshops"])
        self.assertEqual(decomp["workshops"]["carmod3"], ["exh_a_zr", "exh_c_zr", "wg_l_c_zr"])

    def test_parse_shopping_tahoma_format(self):
        sample = (
            "add this to shopping.dat \"section CarMods\" at the top of the file\n"
            "\t\texh_lr_tah1\t\tTAHEX1\t\trespect 0 \tsexy 0\t\t2500\t#LOWRIDERS MOD TAHOMA\n"
            "\t\tfbb_lr_tah1\t\tTAHMC1\t\trespect 0 \tsexy 0\t\t500\n"
            "\t\trbmp_lr_tah1\t\tTAHRB1\t   \trespect 0 \tsexy 0\t\t2250\t# END OF TAHOMA\n"
            "\n"
            "add this to shopping.dat \"section carmod2\" at the bottom of the file\n"
            "\t\titem exh_lr_tah1\t\t#LOWRIDERS MOD TAHOMA\n"
            "\t\titem fbb_lr_tah1\n"
            "\t\titem rbmp_lr_tah1\t\t# END OF TAHOMA\n"
        )
        parsed = self.parser.parse_text_content(sample)
        decomp = self.parser.decompose_shopping(parsed["shopping_dat"])
        self.assertEqual(len(decomp["carmods"]), 3)
        self.assertEqual(decomp["carmods"][0]["part_name"], "exh_lr_tah1")
        self.assertEqual(decomp["carmods"][0]["nametag"], "TAHEX1")
        self.assertEqual(decomp["carmods"][0]["price"], 2500)
        self.assertEqual(decomp["carmods"][1]["price"], 500)

        self.assertIn("carmod2", decomp["workshops"])
        self.assertEqual(decomp["workshops"]["carmod2"], ["exh_lr_tah1", "fbb_lr_tah1", "rbmp_lr_tah1"])

    def test_merge_shopping_multi_section_and_indentation(self):
        actions = [
            {
                "type": "append_carmods_entry",
                "part": "exh_a_zr",
                "line": "\t\texh_a_zr        \tZR2AE   \trespect 0 \tsexy 0\t\t850\t# FOR ZR350",
                "price": 850
            },
            {
                "type": "append_workshop_item",
                "workshop": "carmod3",
                "part": "exh_a_zr",
                "line": "\t\titem exh_a_zr"
            },
            {
                "type": "append_carmods_entry",
                "part": "exh_lr_tah1",
                "line": "\t\texh_lr_tah1     \tTAHEX1  \trespect 0 \tsexy 0\t\t2500\t# FOR TAHOMA",
                "price": 2500
            },
            {
                "type": "append_workshop_item",
                "workshop": "carmod2",
                "part": "exh_lr_tah1",
                "line": "\t\titem exh_lr_tah1"
            },
        ]

        res = self.merger._merge_shopping(actions)
        self.assertTrue(res.get("success"), res)

        content = (self.shadow / "shopping.dat").read_text(encoding="utf-8")
        lines = content.splitlines()

        # Verify section CarMods has exh_a_zr and exh_lr_tah1 with \t\t
        zr_cm = [l for l in lines if "exh_a_zr" in l and "item" not in l]
        self.assertEqual(len(zr_cm), 1)
        self.assertTrue(zr_cm[0].startswith("\t\t"))
        self.assertIn("850", zr_cm[0])

        tah_cm = [l for l in lines if "exh_lr_tah1" in l and "item" not in l]
        self.assertEqual(len(tah_cm), 1)
        self.assertTrue(tah_cm[0].startswith("\t\t"))
        self.assertIn("2500", tah_cm[0])

        # Verify section carmod3 has item exh_a_zr with \t\titem
        zr_w = [l for l in lines if "item exh_a_zr" in l]
        self.assertEqual(len(zr_w), 1)
        self.assertTrue(zr_w[0].startswith("\t\titem exh_a_zr"))

        # Verify section carmod2 has item exh_lr_tah1 with \t\titem
        tah_w = [l for l in lines if "item exh_lr_tah1" in l]
        self.assertEqual(len(tah_w), 1)
        self.assertTrue(tah_w[0].startswith("\t\titem exh_lr_tah1"))

        # Test idempotency: repeated merge must not duplicate
        res2 = self.merger._merge_shopping(actions)
        self.assertTrue(res2.get("success"))
        content2 = (self.shadow / "shopping.dat").read_text(encoding="utf-8")
        self.assertEqual(content, content2)

    def test_delete_tuning_part_cleans_both_carmods_and_workshop(self):
        # Set up a carmod line with parts
        (self.shadow / "carmods.dat").write_text("mods\nzr350, exh_a_zr, exh_c_zr\nend\nlink\nend\n", encoding="utf-8")
        (self.shadow / "veh_mods.ide").write_text("objs\n11747, exh_a_zr, zr350, 100, 2097152\nend\n", encoding="utf-8")
        actions = [
            {"type": "append_carmods_entry", "part": "exh_a_zr", "line": "\t\texh_a_zr\tZR2AE\trespect 0 \tsexy 0\t850", "price": 850},
            {"type": "append_workshop_item", "workshop": "carmod3", "part": "exh_a_zr", "line": "\t\titem exh_a_zr"}
        ]
        self.merger._merge_shopping(actions)
        content_before = (self.shadow / "shopping.dat").read_text(encoding="utf-8")
        self.assertIn("exh_a_zr", content_before)
        self.assertIn("item exh_a_zr", content_before)

        # Delete part
        del_res = self.merger.delete_tuning_part("zr350", "exh_a_zr")
        self.assertTrue(del_res.get("success"), del_res)

        content_after = (self.shadow / "shopping.dat").read_text(encoding="utf-8")
        self.assertNotIn("exh_a_zr", content_after)
        self.assertNotIn("item exh_a_zr", content_after)

    def test_infer_workshop_section(self):
        tuning_mgr = self.merger.tuning_mgr
        # Target vanilla vehicle lookup
        self.assertEqual(tuning_mgr.infer_workshop_section("zr350", ["exh_a_zr"]), "carmod3")
        self.assertEqual(tuning_mgr.infer_workshop_section("tahoma", ["exh_lr_tah1"]), "carmod2")
        self.assertEqual(tuning_mgr.infer_workshop_section("buffalo", ["exh_bf1"]), "carmod1")

        # Addon vehicle heuristic
        self.assertEqual(tuning_mgr.infer_workshop_section("custom_low", ["exh_lr_c1", "fbb_lr_c1"]), "carmod2")
        self.assertEqual(tuning_mgr.infer_workshop_section("custom_street", ["exh_a_cs", "spl_c_cs_b"]), "carmod3")
        self.assertEqual(tuning_mgr.infer_workshop_section("custom_sedan", ["spl_cs1"]), "carmod1")

    def test_plan_merge_uses_author_shopping_prices(self):
        readme_text = (
            "-----------------------------------##| CARMODS.DAT |##-----------------------------------\n"
            "zr350, exh_a_zr, exh_c_zr, spl_a_zr_b\n"
            "-----------------------------------##| SHOPPING.DAT |##----------------------------------\n"
            "\tsection CarMods\n"
            "\t\texh_a_zr\t\tZR2AE\t\trespect 0 \tsexy 0\t850\n"
            "\t\texh_c_zr\t\tZR2CE\t\trespect 0 \tsexy 0\t950\n"
            "\t\tspl_a_zr_b\t \tZR2AS\t\trespect 0 \tsexy 0\t650\n"
            "\tsection carmod3\n"
            "\t\titem exh_a_zr\n"
            "\t\titem exh_c_zr\n"
            "\t\titem spl_a_zr_b\n"
        )
        parsed_raw = self.parser.parse_text_content(readme_text)
        parsed_mod = {
            "success": True,
            "target_model": "zr350",
            "files": {"tuning_dffs": []},
            "parsed": {
                "carmods": [self.parser.decompose_carmods(l) for l in parsed_raw["carmods_dat"]],
                "shopping": self.parser.decompose_shopping(parsed_raw["shopping_dat"]),
                "handling": [],
                "ide": [],
                "carcols": [],
                "veh_mods_ide": [],
                "fxt": [],
                "fxt_text": [],
                "audio_lines": [],
                "special_features": []
            }
        }
        plan = self.merger.plan_merge(parsed_mod)
        self.assertTrue(plan["success"])
        shop_actions = plan["changes"]["shopping_dat"]["actions"]

        # Check price entries
        carmod_actions = [a for a in shop_actions if a["type"] == "append_carmods_entry"]
        self.assertEqual(len(carmod_actions), 3)
        self.assertEqual(carmod_actions[0]["price"], 850)
        self.assertIn("ZR2AE", carmod_actions[0]["line"])
        self.assertTrue(carmod_actions[0]["line"].startswith("\t\t"))
        self.assertEqual(carmod_actions[1]["price"], 950)
        self.assertIn("ZR2CE", carmod_actions[1]["line"])

        # Check workshop actions
        workshop_actions = [a for a in shop_actions if a["type"] == "append_workshop_item"]
        self.assertEqual(len(workshop_actions), 3)
        self.assertEqual(workshop_actions[0]["workshop"], "carmod3")
        self.assertEqual(workshop_actions[0]["part"], "exh_a_zr")
        self.assertEqual(workshop_actions[0]["line"], "\t\titem exh_a_zr")

        # Now apply the merge
        res = self.merger.apply_merge(parsed_mod)
        self.assertTrue(res["success"])

        # Read back shadow shopping.dat
        content = (self.shadow / "shopping.dat").read_text(encoding="utf-8")
        lines = content.splitlines()

        # Verify lines are in section CarMods and aligned with \t\t
        cm_line = [l for l in lines if "exh_a_zr" in l and "item" not in l][0]
        self.assertTrue(cm_line.startswith("\t\t"))
        self.assertIn("850", cm_line)
        self.assertIn("ZR2AE", cm_line)

        # Verify item is in section carmod3
        w_line = [l for l in lines if "item exh_a_zr" in l][0]
        self.assertTrue(w_line.startswith("\t\titem exh_a_zr"))


class AudioCleanupRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.game = Path(self.temp.name)
        self.data = self.game / "data"
        self.modloader = self.game / "modloader"
        self.data.mkdir(parents=True)
        self.modloader.mkdir(parents=True)
        self.cleaner = ModCleaner(str(self.game))
        self.fla = FLAManager(str(self.game))

    def tearDown(self):
        self.temp.cleanup()

    def test_clean_misplaced_vanilla_cars_from_added_vehicles(self):
        # Construct audio cfg with added vehicles section containing buffalo and premier
        cfg_text = (
            "# gtasa_vehicleAudioSettings.cfg\n;\n"
            "; ----- standard vehicles ---------------------------------\n;\n"
            "landstal 0 99 98 0 0.78 1.0 7 1.0 2 0 8 0 0 0.0\n"
            "; ----------------------------------- added vehicles -----------------------------------\n;\n"
            "buffalo 0 38 37 1 0.9 1.0 2 1.05946 2 0 7 0 2 0.0\n"
            "premier 0 87 86 0 0.78 1.0 8 1.0 2 0 8 0 45 0.0\n"
            "myaddon 0 100 101 0 0.8 1.0 5 1.0 2 0 6 0 0 0.0\n;\n"
            ";the end\n"
        )
        audio_file = self.data / "gtasa_vehicleAudioSettings.cfg"
        audio_file.write_text(cfg_text, encoding="utf-8")

        # Active dffs only has myaddon, so myaddon is NOT orphan, but buffalo & premier are misplaced vanilla
        purged = self.fla.clean_misplaced_or_orphan_audio({"myaddon"})
        self.assertTrue(any("buffalo" in p for p in purged))
        self.assertTrue(any("premier" in p for p in purged))

        content = audio_file.read_text(encoding="utf-8")
        # Added vehicles section must ONLY contain myaddon, NOT buffalo or premier
        added_part = content.split("added vehicles")[1]
        self.assertNotIn("buffalo", added_part)
        self.assertNotIn("premier", added_part)
        self.assertIn("myaddon", added_part)

        # Standard vehicles section must contain buffalo, premier, and landstal
        std_part = content.split("added vehicles")[0]
        self.assertIn("buffalo", std_part)
        self.assertIn("premier", std_part)
        self.assertIn("landstal", std_part)

    def test_orphan_addon_audio_and_features_purged(self):
        # Create audio cfg and special features with an orphan addon vehicle
        cfg_text = (
            "# gtasa_vehicleAudioSettings.cfg\n;\n"
            "; ----- standard vehicles ---------------------------------\n;\n"
            "landstal 0 99 98 0 0.78 1.0 7 1.0 2 0 8 0 0 0.0\n"
            "; ----------------------------------- added vehicles -----------------------------------\n;\n"
            "orphan_car 0 100 101 0 0.8 1.0 5 1.0 2 0 6 0 0 0.0\n;\n"
            ";the end\n"
        )
        (self.data / "gtasa_vehicleAudioSettings.cfg").write_text(cfg_text, encoding="utf-8")
        (self.data / "model_special_features.dat").write_text("orphan_car 1\n", encoding="utf-8")

        # Run orphan cleanup (active_dffs is empty)
        res = self.cleaner.clean_orphaned_vehicle_entries()
        self.assertTrue(res["success"])
        self.assertIn("orphan_car", res["purged"]["audio_settings"])
        self.assertIn("orphan_car", res["purged"]["special_features"])

        # Check audio file
        audio_content = (self.data / "gtasa_vehicleAudioSettings.cfg").read_text(encoding="utf-8")
        self.assertNotIn("orphan_car", audio_content)

        # Check special features file
        feat_content = (self.data / "model_special_features.dat").read_text(encoding="utf-8")
        self.assertNotIn("orphan_car", feat_content)

    def test_delete_mod_cleans_audio_properly(self):
        # Create a mod folder inside modloader
        mod_dir = self.modloader / "Modded Cars" / "premier_mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "premier.dff").write_text("dummy dff")

        # In audio cfg, premier has custom line
        cfg_text = (
            "# gtasa_vehicleAudioSettings.cfg\n;\n"
            "; ----- standard vehicles ---------------------------------\n;\n"
            "premier 0 103 102 1 0.9 1.0 4 1.0 2 0 8 0 2 0.0\n;\n"
            ";the end\n"
        )
        (self.data / "gtasa_vehicleAudioSettings.cfg").write_text(cfg_text, encoding="utf-8")

        res = self.cleaner.delete_mod(str(mod_dir), target_model="premier")
        self.assertTrue(res["success"])

        # Premier audio must be reverted to authentic vanilla line
        from core.vanilla_data import VANILLA_AUDIO_SETTINGS
        detail = self.fla.get_model_fla_detail("premier")
        self.assertFalse(detail["audio"]["is_modified"])
        self.assertEqual(detail["audio"]["raw_line"].split(), VANILLA_AUDIO_SETTINGS["premier"].split())


class ConfigMergeRevertAndOrphanCleanupRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.game = Path(self.temp.name)
        self.vanilla_dir = self.game / "data"
        self.shadow_dir = self.game / "modloader" / "Modded Cars"
        self.vanilla_dir.mkdir(parents=True)
        self.shadow_dir.mkdir(parents=True)
        self.cleaner = ModCleaner(str(self.game), data_folder="Modded Cars")
        self.merger = ConfigMerger(str(self.shadow_dir), str(self.game))

    def tearDown(self):
        self.temp.cleanup()

    def test_handling_merge_preserves_special_physics(self):
        shadow_handling = (
            "BF400 500.0 200.0 4.5 0.0 0.05 -0.09 103 1.4 0.9 0.48 5 190.0 50.0 5.0 R P 15.0 0.50 0 35.0 0.85 0.15 0.0 0.15 -0.20 0.5 0.0 0.0 0.15 10000 1000000 0 1 1 4\n"
            "! BF400 0.35 0.10 0.35 0.10 40.0 30.0 0.92 0.65 0.6 0.1 40.0 -40.0 -0.013 0.6 0.5\n"
        )
        (self.shadow_dir / "handling.cfg").write_text(shadow_handling, encoding="utf-8")

        mod_info = {
            "success": True,
            "target_model": "bf400",
            "target_models": ["bf400"],
            "files": {},
            "parsed": {
                "handling": [{
                    "model_name": "BF400",
                    "identifier": "BF400",
                    "raw": "BF400 600.0 250.0 4.5 0.0 0.05 -0.09 103 1.4 0.9 0.48 5 190.0 50.0 5.0 R P 15.0 0.50 0 35.0 0.85 0.15 0.0 0.15 -0.20 0.5 0.0 0.0 0.15 10000 1000000 0 1 1 4"
                }],
                "carmods": [],
                "carcols": [],
                "ide": []
            }
        }
        res = self.merger.apply_merge(mod_info)
        self.assertTrue(res["success"], res)

        content = (self.shadow_dir / "handling.cfg").read_text(encoding="utf-8")
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        self.assertTrue(any(l.startswith("BF400") and "600.0" in l for l in lines))
        self.assertTrue(any(l.startswith("! BF400") or l.startswith("!BF400") for l in lines))
        self.assertEqual(len(lines), 2)

    def test_handling_merge_sub_physics_separately(self):
        shadow_handling = (
            "BF400 500.0 200.0 4.5 0.0 0.05 -0.09 103 1.4 0.9 0.48 5 190.0 50.0 5.0 R P 15.0 0.50 0 35.0 0.85 0.15 0.0 0.15 -0.20 0.5 0.0 0.0 0.15 10000 1000000 0 1 1 4\n"
            "! BF400 0.35 0.10 0.35 0.10 40.0 30.0 0.92 0.65 0.6 0.1 40.0 -40.0 -0.013 0.6 0.5\n"
        )
        (self.shadow_dir / "handling.cfg").write_text(shadow_handling, encoding="utf-8")

        mod_info = {
            "success": True,
            "target_model": "bf400",
            "target_models": ["bf400"],
            "files": {},
            "parsed": {
                "handling": [{
                    "model_name": "BF400",
                    "identifier": "BF400",
                    "prefix": "!",
                    "raw": "! BF400 0.50 0.20 0.45 0.15 45.0 35.0 0.95 0.70 0.8 0.1 42.0 -40.0 -0.015 0.7 0.6"
                }],
                "carmods": [],
                "carcols": [],
                "ide": []
            }
        }
        res = self.merger.apply_merge(mod_info)
        self.assertTrue(res["success"], res)

        content = (self.shadow_dir / "handling.cfg").read_text(encoding="utf-8")
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        self.assertTrue(any(l.startswith("BF400") and "500.0" in l for l in lines))
        self.assertTrue(any(l.startswith("! BF400") and "0.50" in l for l in lines))
        self.assertEqual(len(lines), 2)

    def test_handling_revert_restores_both_main_and_sub_physics(self):
        vanilla_handling = (
            "BF400 500.0 200.0 4.5 0.0 0.05 -0.09 103 1.4 0.9 0.48 5 190.0 50.0 5.0 R P 15.0 0.50 0 35.0 0.85 0.15 0.0 0.15 -0.20 0.5 0.0 0.0 0.15 10000 1000000 0 1 1 4\n"
            "! BF400 0.35 0.10 0.35 0.10 40.0 30.0 0.92 0.65 0.6 0.1 40.0 -40.0 -0.013 0.6 0.5\n"
        )
        (self.vanilla_dir / "handling.cfg").write_text(vanilla_handling, encoding="utf-8")

        shadow_handling = (
            "BF400 999.0 999.0 4.5 0.0 0.05 -0.09 103 1.4 0.9 0.48 5 190.0 50.0 5.0 R P 15.0 0.50 0 35.0 0.85 0.15 0.0 0.15 -0.20 0.5 0.0 0.0 0.15 10000 1000000 0 1 1 4\n"
            "! BF400 0.99 0.99 0.99 0.99 40.0 30.0 0.92 0.65 0.6 0.1 40.0 -40.0 -0.013 0.6 0.5\n"
        )
        (self.shadow_dir / "handling.cfg").write_text(shadow_handling, encoding="utf-8")

        self.cleaner._revert_handling("bf400")

        content = (self.shadow_dir / "handling.cfg").read_text(encoding="utf-8")
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        self.assertTrue(any(l.startswith("BF400") and "500.0" in l for l in lines))
        self.assertTrue(any(l.startswith("! BF400") and "0.35" in l for l in lines))
        self.assertEqual(len(lines), 2)

    def test_shopping_and_carmods_revert_on_delete_mod(self):
        mod_dir = self.game / "modloader" / "Modded Cars" / "tahoma_mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "tahoma.dff").write_bytes(b"dff")
        (mod_dir / "wg_l_b_lr_t.dff").write_bytes(b"dff")

        vanilla_shopping = (
            "section prices\n"
            "bnd_b_s CARBL1 respect 4 sexy 10 200\n"
            "end\n"
            "section carmod2\n"
            "\t\titem bnd_b_s\n"
            "end\n"
        )
        (self.vanilla_dir / "shopping.dat").write_text(vanilla_shopping, encoding="utf-8")

        vanilla_carmods = (
            "link\n"
            "end\n"
            "mods\n"
            "tahoma, bnd_b_s\n"
            "end\n"
        )
        (self.vanilla_dir / "carmods.dat").write_text(vanilla_carmods, encoding="utf-8")

        shadow_shopping = (
            "section prices\n"
            "bnd_b_s CARBL1 respect 4 sexy 10 200\n"
            "wg_l_b_lr_t CARBL1 respect 4 sexy 10 250\n"
            "end\n"
            "section carmod2\n"
            "\t\titem bnd_b_s\n"
            "\t\titem wg_l_b_lr_t\n"
            "end\n"
        )
        (self.shadow_dir / "shopping.dat").write_text(shadow_shopping, encoding="utf-8")

        shadow_carmods = (
            "link\n"
            "wg_l_b_lr_t, wg_r_b_lr_t\n"
            "end\n"
            "mods\n"
            "tahoma, bnd_b_s, wg_l_b_lr_t\n"
            "end\n"
        )
        (self.shadow_dir / "carmods.dat").write_text(shadow_carmods, encoding="utf-8")

        shadow_vm = (
            "objs\n"
            "1005, bnd_b_s, vehicle, 70, 0\n"
            "1194, wg_l_b_lr_t, tahoma, 70, 2097152\n"
            "end\n"
        )
        (self.shadow_dir / "veh_mods.ide").write_text(shadow_vm, encoding="utf-8")

        res = self.cleaner.delete_mod(str(mod_dir), target_model="tahoma")
        self.assertTrue(res["success"])

        # Check shopping.dat
        shop_text = (self.shadow_dir / "shopping.dat").read_text(encoding="utf-8")
        self.assertNotIn("wg_l_b_lr_t", shop_text)
        self.assertIn("bnd_b_s", shop_text)

        # Check carmods.dat
        cm_text = (self.shadow_dir / "carmods.dat").read_text(encoding="utf-8")
        self.assertNotIn("wg_l_b_lr_t", cm_text)
        self.assertNotIn("wg_r_b_lr_t", cm_text)
        self.assertIn("bnd_b_s", cm_text)

        # Check veh_mods.ide
        vm_text = (self.shadow_dir / "veh_mods.ide").read_text(encoding="utf-8")
        self.assertNotIn("1194", vm_text)
        self.assertNotIn("wg_l_b_lr_t", vm_text)
        self.assertIn("1005", vm_text)

    def test_clean_orphaned_entries_all_files(self):
        (self.vanilla_dir / "handling.cfg").write_text(
            "INFERNUS 1500.0 3500.0 2.2 0.0 0.3 -0.15 75 0.65 0.9 0.5 5 200.0 28.0 5.0 R P 8.0 0.5 0 35.0 1.0 0.20 0.0 0.28 -0.10 0.5 0.3 0.25 0.60 35000 40002804 4000001 1 1 1\n"
            "! BF400 0.35 0.10 0.35 0.10 40.0 30.0 0.92 0.65 0.6 0.1 40.0 -40.0 -0.013 0.6 0.5\n",
            encoding="utf-8"
        )
        (self.vanilla_dir / "carmods.dat").write_text(
            "link\nend\nmods\nelegy, rf_a_l\nend\n", encoding="utf-8"
        )
        (self.vanilla_dir / "shopping.dat").write_text(
            "section CarMods\nrf_a_l CARBL1 respect 4 sexy 10 250\nend\nsection carmod3\nitem rf_a_l\nend\n",
            encoding="utf-8"
        )

        (self.shadow_dir / "handling.cfg").write_text(
            "INFERNUS 1500.0 3500.0 2.2 0.0 0.3 -0.15 75 0.65 0.9 0.5 5 200.0 28.0 5.0 R P 8.0 0.5 0 35.0 1.0 0.20 0.0 0.28 -0.10 0.5 0.3 0.25 0.60 35000 40002804 4000001 1 1 1\n"
            "! BF400 0.35 0.10 0.35 0.10 40.0 30.0 0.92 0.65 0.6 0.1 40.0 -40.0 -0.013 0.6 0.5\n"
            "^ 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.5 0.0 -0.5 -0.3 0.3 0.41 0.8 0.3 0.45 0.06 0.43 0.20 0.43 0\n"
            "MYORPHAN 1500.0 3500.0 2.2 0.0 0.3 -0.15 75 0.65 0.9 0.5 5 200.0 28.0 5.0 R P 8.0 0.5 0 35.0 1.0 0.20 0.0 0.28 -0.10 0.5 0.3 0.25 0.60 35000 40002804 4000001 1 1 1\n"
            "! ORPHANBIKE 0.35 0.10 0.35 0.10 40.0 30.0 0.92 0.65 0.6 0.1 40.0 -40.0 -0.013 0.6 0.5\n",
            encoding="utf-8"
        )
        (self.shadow_dir / "carmods.dat").write_text(
            "link\norphan_l, orphan_r\nend\nmods\nelegy, rf_a_l\norphan_car, part1, part2\nend\n",
            encoding="utf-8"
        )
        (self.shadow_dir / "veh_mods.ide").write_text(
            "objs\n1000, rf_a_l, generic, 100, 0\n1195, orphan_part, tahoma, 100, 0\nend\n",
            encoding="utf-8"
        )
        (self.shadow_dir / "shopping.dat").write_text(
            "section CarMods\nrf_a_l CARBL1 respect 4 sexy 10 250\norphan_part CARBL1 respect 4 sexy 10 500\nend\nsection carmod3\nitem rf_a_l\nitem orphan_part\nend\n",
            encoding="utf-8"
        )
        (self.vanilla_dir / "model_special_features.dat").write_text(
            "uranus 1\norphan_car 1\n", encoding="utf-8"
        )

        res = self.cleaner.clean_orphaned_vehicle_entries()
        self.assertTrue(res["success"])
        purged = res["purged"]

        self.assertIn("myorphan", purged["handling_cfg"])
        self.assertIn("orphanbike", purged["handling_cfg"])
        h_text = (self.shadow_dir / "handling.cfg").read_text(encoding="utf-8")
        self.assertIn("INFERNUS", h_text)
        self.assertIn("! BF400", h_text)
        self.assertIn("^ 0", h_text)
        self.assertNotIn("MYORPHAN", h_text)
        self.assertNotIn("ORPHANBIKE", h_text)

        self.assertIn("orphan_car", purged["carmods_dat"])
        cm_text = (self.shadow_dir / "carmods.dat").read_text(encoding="utf-8")
        self.assertIn("elegy", cm_text)
        self.assertNotIn("orphan_car", cm_text)
        self.assertNotIn("orphan_l", cm_text)

        self.assertIn("orphan_part", purged["veh_mods_ide"])
        vm_text = (self.shadow_dir / "veh_mods.ide").read_text(encoding="utf-8")
        self.assertIn("1000", vm_text)
        self.assertNotIn("1195", vm_text)

        self.assertIn("orphan_part", purged["shopping_dat"])
        shop_text = (self.shadow_dir / "shopping.dat").read_text(encoding="utf-8")
        self.assertIn("rf_a_l", shop_text)
        self.assertNotIn("orphan_part", shop_text)

        feat_text = (self.vanilla_dir / "model_special_features.dat").read_text(encoding="utf-8")
        self.assertIn("uranus", feat_text)
        self.assertNotIn("orphan_car", feat_text)
        self.assertIn("orphan_car", purged["special_features"])
        self.assertNotIn("uranus", purged["special_features"])

    def test_handling_boat_and_plane_merge_revert(self):
        vanilla_handling = (
            "PREDATOR 2200.0 29333.3 1.0 0.0 0.0 0.0 14 2.30 15.0 0.58 5 190.0 1.7 5.0 R P 0.05 0.01 0 24.0 1.0 3.0 0.0 0.10 0.1 0.0 0.0 0.2 0.33 40000 8000000 0 0 1 0\n"
            "% PREDATOR 0.79 0.5 0.6 7.0 0.60 -1.9 4.0 0.8 0.998 0.998 0.85 0.98 0.97 4.0\n"
            "SEAPLANE 5000.0 27083.3 12.0 0.0 0.0 0.0 9 0.83 45.0 0.5 1 200.0 1.7 5.0 4 P 0.01 0.05 0 24.0 1.5 0.75 0.0 0.10 0.0 2.0 0.0 1.0 0.05 10000 4000400 0 0 1 0\n"
            "$ SEAPLANE 0.5 0.40 -0.00006 0.002 0.10 0.002 -0.002 0.0002 0.0020 0.020 0.15 1.0 1.0 0.2 1.0 0.998 0.998 0.995 20.0 50.0 20.0\n"
        )
        (self.vanilla_dir / "handling.cfg").write_text(vanilla_handling, encoding="utf-8")
        (self.shadow_dir / "handling.cfg").write_text(vanilla_handling, encoding="utf-8")

        # 1. Merge updated boat handling
        mod_boat = {
            "success": True,
            "target_model": "predator",
            "target_models": ["predator"],
            "files": {},
            "parsed": {
                "handling": [{
                    "model_name": "PREDATOR",
                    "identifier": "PREDATOR",
                    "prefix": "%",
                    "raw": "% PREDATOR 0.99 0.9 0.9 9.0 0.90 -1.9 5.0 0.9 0.999 0.999 0.95 0.99 0.99 5.0"
                }],
                "carmods": [], "carcols": [], "ide": []
            }
        }
        res = self.merger.apply_merge(mod_boat)
        self.assertTrue(res["success"])

        # Verify % PREDATOR updated, main line untouched
        h_lines = (self.shadow_dir / "handling.cfg").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(l.startswith("PREDATOR") and "2200.0" in l for l in h_lines))
        self.assertTrue(any(l.startswith("% PREDATOR") and "0.99" in l for l in h_lines))

        # 2. Merge updated plane flying handling
        mod_plane = {
            "success": True,
            "target_model": "seaplane",
            "target_models": ["seaplane"],
            "files": {},
            "parsed": {
                "handling": [{
                    "model_name": "SEAPLANE",
                    "identifier": "SEAPLANE",
                    "prefix": "$",
                    "raw": "$ SEAPLANE 0.8 0.60 -0.00006 0.002 0.10 0.002 -0.002 0.0002 0.0020 0.020 0.15 1.0 1.0 0.2 1.0 0.998 0.998 0.995 20.0 50.0 20.0"
                }],
                "carmods": [], "carcols": [], "ide": []
            }
        }
        res2 = self.merger.apply_merge(mod_plane)
        self.assertTrue(res2["success"])

        h_lines = (self.shadow_dir / "handling.cfg").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(l.startswith("SEAPLANE") and "5000.0" in l for l in h_lines))
        self.assertTrue(any(l.startswith("$ SEAPLANE") and "0.8" in l for l in h_lines))

        # 3. Revert boat: restores vanilla % line
        self.cleaner._revert_handling("predator")
        h_lines = (self.shadow_dir / "handling.cfg").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(l.startswith("% PREDATOR") and "0.79" in l for l in h_lines))

        # 4. Revert plane: restores vanilla $ line
        self.cleaner._revert_handling("seaplane")
        h_lines = (self.shadow_dir / "handling.cfg").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(l.startswith("$ SEAPLANE") and "0.5" in l for l in h_lines))


class MergeRollbackRegression(unittest.TestCase):
    """A failed merge must never leave the game half-configured."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.game = Path(self.temp.name)
        self.vanilla_dir = self.game / "data"
        self.shadow_dir = self.game / "modloader" / "Modded Cars"
        self.vanilla_dir.mkdir(parents=True)
        self.shadow_dir.mkdir(parents=True)
        # Keep snapshots inside the temp dir so rotation never touches real backups.
        self.backup_manager = BackupManager(
            backup_dir=str(self.game / "_backups"), game_dir=str(self.game)
        )
        self.merger = ConfigMerger(
            str(self.shadow_dir), str(self.game), backup_manager=self.backup_manager
        )

    def tearDown(self):
        self.temp.cleanup()

    def _seed_shadow_files(self):
        (self.shadow_dir / "handling.cfg").write_text(
            "BF400 500.0 200.0 4.5 0.0 0.05 -0.09 103 1.4 0.9 0.48 5 190.0 50.0 5.0 R P 15.0 0.50 0 35.0 0.85 0.15 0.0 0.15 -0.20 0.5 0.0 0.0 0.15 10000 1000000 0 1 1 4\n",
            encoding="utf-8",
        )
        (self.shadow_dir / "carmods.dat").write_text(
            "mods\nbf400, exh_a_s\nend\n",
            encoding="utf-8",
        )
        (self.shadow_dir / "shopping.dat").write_text(
            "section prices\n\tCarMods\n\tend\nend\n",
            encoding="utf-8",
        )

    def _snapshot_shadow(self):
        return {
            p.name: p.read_text(encoding="utf-8")
            for p in self.shadow_dir.iterdir()
            if p.is_file()
        }

    def _mod_info(self):
        return {
            "success": True,
            "target_model": "bf400",
            "target_models": ["bf400"],
            "files": {},
            "parsed": {
                "handling": [{
                    "model_name": "BF400",
                    "identifier": "BF400",
                    "prefix": "!",
                    "raw": "! BF400 0.50 0.20 0.45 0.15 45.0 35.0 0.95 0.70 0.8 0.1 42.0 -40.0 -0.015 0.7 0.6"
                }],
                "carmods": [{
                    "model": "bf400",
                    "part_names": ["exh_a_zr", "wg_l_lr_tah1", "wg_r_lr_tah1"]
                }],
                "carcols": [],
                "ide": []
            }
        }

    def test_failed_merge_rolls_back_already_written_files(self):
        self._seed_shadow_files()
        before = self._snapshot_shadow()

        # Fail on the 4th step: carmods.dat / shopping.dat were already written.
        with patch.object(ConfigMerger, "_merge_handling",
                          return_value={"success": False, "error": "磁盘写入失败"}):
            res = self.merger.apply_merge(self._mod_info())

        self.assertFalse(res["success"])
        self.assertTrue(res["rolled_back"])
        self.assertEqual(res["applied_files"], [])

        after = self._snapshot_shadow()
        for name, content in before.items():
            self.assertEqual(
                after.get(name), content,
                f"{name} 未被回滚到合并前的内容"
            )

    def test_successful_merge_leaves_files_applied(self):
        self._seed_shadow_files()
        before = self._snapshot_shadow()

        res = self.merger.apply_merge(self._mod_info())

        self.assertTrue(res["success"], res)
        self.assertNotIn("rolled_back", res)
        self.assertTrue(res["applied_files"])

        after = self._snapshot_shadow()
        self.assertNotEqual(after.get("carmods.dat"), before.get("carmods.dat"))

    def test_rollback_reports_error_when_snapshot_is_unusable(self):
        self._seed_shadow_files()

        with patch.object(ConfigMerger, "_merge_handling",
                          return_value={"success": False, "error": "磁盘写入失败"}), \
             patch.object(BackupManager, "restore_snapshot",
                          return_value={"success": False, "errors": ["快照文件丢失"]}):
            res = self.merger.apply_merge(self._mod_info())

        self.assertFalse(res["success"])
        self.assertTrue(res["rolled_back"])
        self.assertTrue(any("Rollback failed" in e for e in res["errors"]), res["errors"])


class IdCacheCoherencyRegression(unittest.TestCase):
    """A cached IDE scan must never outlive a write that changes ID occupancy."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="idcache_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        (self.game / "data" / "vehicles.ide").write_text("cars\nend\n", encoding="utf-8")

    @staticmethod
    def _ide(model, mid):
        return f"{mid}, {model}, {model}, car, {model.upper()}, {model.upper()}, null, normal, 5, 0, 0, -1, 0.7, 0.7, 0\n"

    def _write_shadow_ide(self, *entries):
        (self.shadow / "vehicles.ide").write_text(
            "cars\n" + "".join(entries) + "end\n", encoding="utf-8")

    def test_sibling_manager_rescans_once_any_manager_invalidates(self):
        self._write_shadow_ide()
        reader = IdManager(str(self.game))
        self.assertTrue(reader.check_id_status(12094)["is_free"])

        # A new addon ID appears on disk without the reader knowing.
        self._write_shadow_ide(self._ide("newcar", 12094))
        self.assertTrue(reader.check_id_status(12094)["is_free"])  # still cached

        IdManager.invalidate_shared_cache(str(self.game))
        self.assertFalse(reader.check_id_status(12094)["is_free"])

    def test_forced_refresh_is_visible_to_sibling_instances(self):
        self._write_shadow_ide()
        writer = IdManager(str(self.game))
        reader = IdManager(str(self.game))
        writer.scan_all_ides()
        reader.scan_all_ides()
        self.assertTrue(reader.check_id_status(12094)["is_free"])

        self._write_shadow_ide(self._ide("newcar", 12094))
        writer.scan_all_ides(force_refresh=True)
        self.assertFalse(reader.check_id_status(12094)["is_free"])

    def test_merge_invalidates_cached_id_scan(self):
        self._write_shadow_ide()
        self.merger = ConfigMerger(str(self.shadow), str(self.game))
        reader = IdManager(str(self.game))
        self.assertTrue(reader.check_id_status(12094)["is_free"])

        mod_info = {
            "success": True,
            "target_model": "newcar",
            "target_models": ["newcar"],
            "files": {},
            "parsed": {
                "handling": [], "carmods": [], "carcols": [],
                "ide": [{
                    "model_name": "newcar",
                    "id": 12094,
                    "raw": self._ide("newcar", 12094).strip(),
                }],
            },
        }
        res = self.merger.apply_merge(mod_info)
        self.assertTrue(res["success"], res)
        self.assertFalse(reader.check_id_status(12094)["is_free"])

    def test_mirror_link_cache_reloads_after_carmods_changes(self):
        (self.shadow / "carmods.dat").write_text(
            "mods\nend\nlink\nend\n", encoding="utf-8")
        tuning = TuningManager(str(self.shadow), str(self.game))

        # Neither the wg_r_ nor bntr_ shortcut applies to this part name.
        self.assertFalse(tuning.is_mirror_counterpart("spl_r_lr_tah1"))

        (self.shadow / "carmods.dat").write_text(
            "mods\nend\nlink\nspl_l_lr_tah1, spl_r_lr_tah1\nend\n", encoding="utf-8")
        self.assertTrue(tuning.is_mirror_counterpart("spl_r_lr_tah1"))


class AtomicWriteRegression(unittest.TestCase):
    """A failed config write must leave the previous file intact, not truncated."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atomic_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        self.backup_manager = BackupManager(
            backup_dir=str(self.game / "_backups"), game_dir=str(self.game))
        self.merger = ConfigMerger(
            str(self.shadow), str(self.game), backup_manager=self.backup_manager)

    def _temp_files(self):
        return [p.name for p in self.shadow.iterdir() if p.name.endswith(".tmp")]

    def test_write_text_atomic_preserves_original_on_failure(self):
        target = self.shadow / "handling.cfg"
        target.write_text("original\n", encoding="utf-8")

        with patch("core.atomic_io.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                write_text_atomic(str(target), "replacement\n")

        self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
        self.assertEqual(self._temp_files(), [])

    def test_write_text_atomic_creates_new_file(self):
        target = self.shadow / "veh_mods.ide"
        write_text_atomic(str(target), "objs\nend\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "objs\nend\n")
        self.assertEqual(self._temp_files(), [])

    def test_failed_merge_write_preserves_original_config(self):
        original = "mods\nbf400, exh_a_s\nend\nlink\nwg_l_lr_tah1, wg_r_lr_tah1\nend\n"
        (self.shadow / "carmods.dat").write_text(original, encoding="utf-8")

        mod_info = {
            "success": True,
            "target_model": "bf400",
            "target_models": ["bf400"],
            "files": {},
            "parsed": {
                "handling": [], "carcols": [], "ide": [],
                "carmods": [{"model": "bf400", "part_names": ["exh_a_zr"]}],
            },
        }
        with patch("core.atomic_io.os.replace", side_effect=OSError("locked")):
            res = self.merger.apply_merge(mod_info)

        self.assertFalse(res["success"])
        self.assertTrue(any("Exception" in e for e in res["errors"]), res["errors"])
        self.assertEqual(
            (self.shadow / "carmods.dat").read_text(encoding="utf-8"), original)
        self.assertEqual(self._temp_files(), [])


class LocalApiGuardRegression(unittest.TestCase):
    """The local API must only answer this machine's own UI."""

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.httpd, cls.port = server._bind_http_backend(0)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def _raw(self, request_line, headers=()):
        """Send a raw request so paths and headers reach the server verbatim."""
        chunks = []
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            payload = "\r\n".join([request_line, "Connection: close", *headers, "", ""])
            sock.sendall(payload.encode("latin-1"))
            try:
                while True:
                    data = sock.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
            except socket.timeout:
                pass
        return b"".join(chunks)

    @staticmethod
    def _status(response):
        return int(response.split(b"\r\n", 1)[0].decode("latin-1").split(" ")[1])

    def test_authority_helper_accepts_only_loopback(self):
        s = self.server
        for value in ("127.0.0.1", "127.0.0.1:28848", "localhost:28848",
                      "http://127.0.0.1:28848", "http://localhost:28848/",
                      "[::1]:28848", "http://[::1]:28848"):
            self.assertTrue(s._is_loopback_authority(value), value)

        for value in ("", "null", "evil.example", "evil.example:80",
                      "http://evil.example", "https://evil.example:443/x",
                      "127.0.0.1.evil.example", "0.0.0.0:28848", "localhost.evil.example"):
            self.assertFalse(s._is_loopback_authority(value), value)

    def test_foreign_origin_is_refused(self):
        res = self._raw(
            "POST /api/does-not-exist HTTP/1.1",
            [f"Host: 127.0.0.1:{self.port}", "Origin: https://evil.example",
             "Content-Length: 0"],
        )
        self.assertEqual(self._status(res), 403)
        self.assertIn("Access denied", res.decode("utf-8", "replace"))

    def test_foreign_host_is_refused(self):
        res = self._raw(
            "GET /api/status HTTP/1.1",
            ["Host: evil.example", f"Origin: http://127.0.0.1:{self.port}"],
        )
        self.assertEqual(self._status(res), 403)

    def test_null_origin_is_refused(self):
        res = self._raw(
            "POST /api/does-not-exist HTTP/1.1",
            [f"Host: 127.0.0.1:{self.port}", "Origin: null", "Content-Length: 0"],
        )
        self.assertEqual(self._status(res), 403)

    def test_loopback_origin_reaches_the_endpoint(self):
        res = self._raw(
            "POST /api/does-not-exist HTTP/1.1",
            [f"Host: 127.0.0.1:{self.port}",
             f"Origin: http://127.0.0.1:{self.port}", "Content-Length: 0"],
        )
        # 404 proves the guard let it through; the endpoint itself is unknown.
        self.assertEqual(self._status(res), 404)

    def test_local_ui_still_gets_api_and_static_files(self):
        local = [f"Host: 127.0.0.1:{self.port}",
                 f"Origin: http://localhost:{self.port}"]
        self.assertEqual(self._status(self._raw("GET /api/status HTTP/1.1", local)), 200)
        self.assertEqual(self._status(self._raw("GET / HTTP/1.1", local)), 200)

        js = self._raw("GET /app.js HTTP/1.1", local)
        self.assertEqual(self._status(js), 200)
        self.assertIn(b"vanillaVehicles", js)

    def test_responses_never_grant_cross_origin_access(self):
        for headers in ([f"Host: 127.0.0.1:{self.port}"],
                        [f"Host: 127.0.0.1:{self.port}",
                         f"Origin: http://127.0.0.1:{self.port}"]):
            res = self._raw("GET /api/status HTTP/1.1", headers)
            self.assertNotIn(b"Access-Control-Allow", res, res[:120])

    def test_options_does_not_authorise_a_cross_site_preflight(self):
        res = self._raw(
            "OPTIONS /api/status HTTP/1.1",
            [f"Host: 127.0.0.1:{self.port}", "Origin: https://evil.example",
             "Access-Control-Request-Method: POST"],
        )
        self.assertEqual(self._status(res), 403)
        self.assertNotIn(b"Access-Control-Allow", res)

    def test_options_from_the_local_ui_is_allowed(self):
        res = self._raw(
            "OPTIONS /api/status HTTP/1.1",
            [f"Host: 127.0.0.1:{self.port}",
             f"Origin: http://127.0.0.1:{self.port}"],
        )
        self.assertEqual(self._status(res), 200)
        self.assertNotIn(b"Access-Control-Allow", res)

    def test_path_traversal_cannot_read_outside_the_web_root(self):
        for target in ("/../config.json", "/..%2fconfig.json", "/%2e%2e/config.json"):
            res = self._raw(f"GET {target} HTTP/1.1", [f"Host: 127.0.0.1:{self.port}"])
            self.assertEqual(self._status(res), 404, target)
            self.assertNotIn(b"game_path", res, target)

    def test_stalled_clients_are_bounded_by_a_socket_timeout(self):
        handler = self.server.ModManagerHandler
        self.assertEqual(handler.timeout, self.server.REQUEST_SOCKET_TIMEOUT_SECONDS)
        self.assertGreater(handler.timeout, 0)

    def test_handler_crash_returns_json_instead_of_dropping_the_connection(self):
        # limit=abc makes int() raise inside the GET handler.
        with patch("traceback.print_exc"):
            res = self._raw("GET /api/ids/search?limit=abc HTTP/1.1",
                            [f"Host: 127.0.0.1:{self.port}"])
        self.assertEqual(self._status(res), 500)

        body = res.split(b"\r\n\r\n", 1)[1]
        self.assertTrue(body, "a crashed handler must still send a body")
        payload = json.loads(body.decode("utf-8"))
        self.assertFalse(payload["success"])
        self.assertIn("ValueError", payload["error"])
        self.assertIn("int", payload["error"])

    def test_handler_crash_body_is_valid_json_with_utf8_header(self):
        with patch("traceback.print_exc"):
            res = self._raw("GET /api/ids/search?limit=abc HTTP/1.1",
                            [f"Host: 127.0.0.1:{self.port}"])
        self.assertIn(b"application/json; charset=utf-8", res)

    def test_successful_requests_are_unaffected_by_the_guard(self):
        local = [f"Host: 127.0.0.1:{self.port}"]
        self.assertEqual(self._status(self._raw("GET /api/status HTTP/1.1", local)), 200)
        self.assertEqual(self._status(self._raw("GET /api/languages HTTP/1.1", local)), 200)

    def test_guard_passes_through_normal_error_statuses(self):
        res = self._raw("POST /api/does-not-exist HTTP/1.1",
                        [f"Host: 127.0.0.1:{self.port}", "Content-Length: 0"])
        # A handler's own 404 is not an internal error.
        self.assertEqual(self._status(res), 404)

    def test_second_response_is_not_attempted_after_output_started(self):
        handler = self.server.ModManagerHandler.__new__(self.server.ModManagerHandler)
        handler._response_started = True
        handler.close_connection = False
        handler.wfile = io.BytesIO()
        handler._send_error = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not append a second response"))

        with patch("traceback.print_exc"):
            handler._on_unhandled_error(RuntimeError("boom"))

        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.wfile.getvalue(), b"")


class SevenZipTimeoutRegression(unittest.TestCase):
    """A hung 7z.exe must not block the single-threaded server forever."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sevenzip_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)

    def test_extraction_passes_a_timeout_to_subprocess(self):
        with patch("core.seven_zip.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0)
            extract_with_7zip("7z.exe", "pack.rar", "out")
        self.assertEqual(run.call_args.kwargs.get("timeout"), EXTRACT_TIMEOUT_SECONDS)
        self.assertGreater(EXTRACT_TIMEOUT_SECONDS, 0)

    def test_timeout_becomes_a_clear_runtime_error(self):
        expired = subprocess.TimeoutExpired(cmd="7z.exe x", timeout=EXTRACT_TIMEOUT_SECONDS)
        with patch("core.seven_zip.subprocess.run", side_effect=expired):
            with self.assertRaises(RuntimeError) as ctx:
                extract_with_7zip("7z.exe", os.path.join("C:", "mods", "big pack.rar"), "out")
        message = str(ctx.exception)
        self.assertIn("timed out", message.lower())
        self.assertIn("big pack.rar", message)

    def test_inspect_reports_a_stuck_extraction_as_a_normal_failure(self):
        archive = Path(self.temp.name) / "pack.rar"
        archive.write_bytes(b"not really a rar")
        installer = ModInstaller(str(self.game), "Modded Cars")
        expired = subprocess.TimeoutExpired(cmd="7z.exe x", timeout=EXTRACT_TIMEOUT_SECONDS)

        with patch("core.installer.find_7zip", return_value="7z.exe"), \
             patch("core.seven_zip.subprocess.run", side_effect=expired):
            res = installer.inspect_source(str(archive))

        self.assertFalse(res["success"])
        self.assertIn("timed out", res["error"].lower())
        self.assertIn("pack.rar", res["error"])


class FxtEntryEditRegression(unittest.TestCase):
    """Renaming one in-game car name must not damage the rest of the file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fxtedit_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name)
        self.mod = self.game / "modloader" / "Modded Cars" / "Modder" / "SomeMod"
        self.mod.mkdir(parents=True)
        self.backups = BackupManager(
            backup_dir=str(self.game / "_backups"), game_dir=str(self.game))

    def _edit(self, key="CHEETAH", name="My Cheetah", **kw):
        return update_fxt_entry(str(self.mod), key, name,
                                backup_manager=self.backups, **kw)

    def test_gbk_file_keeps_unrelated_entries_byte_identical(self):
        path = self.mod / "names.fxt"
        original = "CHEETAH 猎豹\nBANSHEE 女妖\n".encode("gb18030")
        path.write_bytes(original)

        res = self._edit()
        self.assertTrue(res["success"], res)

        after = path.read_bytes()
        decoded = after.decode("gb18030")
        self.assertIn("CHEETAH My Cheetah", decoded)
        self.assertIn("BANSHEE 女妖", decoded)
        # The untouched line must survive byte for byte.
        self.assertEqual(original.split(b"\n")[1], after.split(b"\n")[1])

    def test_line_endings_and_trailing_newline_are_preserved(self):
        crlf = self.mod / "crlf.fxt"
        crlf.write_bytes(b"CHEETAH Old\r\nBANSHEE Keep\r\n")
        no_eol = self.mod / "noeol.fxt"
        no_eol.write_bytes(b"CHEETAH Old")

        self.assertTrue(self._edit()["success"])

        self.assertEqual(crlf.read_bytes(), b"CHEETAH My Cheetah\r\nBANSHEE Keep\r\n")
        self.assertEqual(no_eol.read_bytes(), b"CHEETAH My Cheetah")

    def test_utf8_file_accepts_a_cjk_name(self):
        path = self.mod / "a.fxt"
        path.write_text("CHEETAH Old\nBANSHEE Keep\n", encoding="utf-8", newline="")
        res = self._edit(name="猎豹改名")
        self.assertTrue(res["success"], res)
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "CHEETAH 猎豹改名\nBANSHEE Keep\n")

    def test_scratch_file_is_created_when_the_key_is_absent(self):
        res = self._edit(key="NEWCAR", name="Brand New", model_hint="newcar")
        self.assertTrue(res["success"], res)
        self.assertTrue(res["created"])
        created = self.mod / "newcar.fxt"
        self.assertTrue(created.is_file())
        self.assertEqual(created.read_text(encoding="utf-8"), "NEWCAR Brand New\n")

    def test_big5_file_keeps_unrelated_entries_byte_identical(self):
        # Big5 used to be read as GB18030, which turned the whole file into
        # mojibake before it was written back.
        path = self.mod / "names.fxt"
        original = "CHEETAH 獵豹\nBANSHEE 女妖\n".encode("big5")
        path.write_bytes(original)

        res = self._edit()
        self.assertTrue(res["success"], res)

        after = path.read_bytes()
        decoded = after.decode("big5")
        self.assertIn("CHEETAH My Cheetah", decoded)
        self.assertIn("BANSHEE 女妖", decoded)
        self.assertEqual(original.split(b"\n")[1], after.split(b"\n")[1])

    def test_a_failing_write_rolls_back_every_file(self):
        files = []
        for i in (1, 2, 3):
            p = self.mod / f"p{i}.fxt"
            p.write_text(f"CHEETAH Name {i}\n", encoding="utf-8")
            files.append(p)
        before = {p: p.read_bytes() for p in files}

        calls = {"n": 0}
        real_write = fxt_installer.write_bytes_atomic

        def flaky(path, data):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("simulated disk failure")
            return real_write(path, data)

        with patch.object(fxt_installer, "write_bytes_atomic", side_effect=flaky):
            res = self._edit()

        self.assertFalse(res["success"])
        self.assertTrue(res["rolled_back"])
        for path in files:
            self.assertEqual(path.read_bytes(), before[path],
                             f"{path.name} was not restored")

    def test_a_file_whose_bytes_cannot_be_reproduced_is_refused(self):
        path = self.mod / "weird.fxt"
        raw = "CHEETAH Old\nBANSHEE Машина\n".encode("cp1251")
        path.write_bytes(raw)

        with patch.object(fxt_installer, "detect_text_encoding", return_value="ascii"):
            res = self._edit()

        self.assertFalse(res["success"])
        self.assertIn("Cannot safely read", res["error"])
        self.assertEqual(path.read_bytes(), raw)

    def test_validation_rejects_bad_keys_and_names(self):
        (self.mod / "v.fxt").write_text("CHEETAH Old\n", encoding="utf-8")
        cases = [
            (("bad key!", "Ok"), "Invalid FXT key"),
            (("CHEETAH", ""), "Display name cannot be empty"),
            (("CHEETAH", "12345"), "valid text"),
            (("CHEETAH", "Car 12 34 56 78"), "too many numbers"),
        ]
        for (key, name), expected in cases:
            res = self._edit(key=key, name=name)
            self.assertFalse(res["success"], f"{key}/{name} should be rejected")
            self.assertIn(expected, res["error"])

    def test_missing_directory_is_reported(self):
        res = update_fxt_entry(str(self.game / "nope"), "CHEETAH", "Name")
        self.assertFalse(res["success"])
        self.assertIn("Invalid mod directory", res["error"])


class TextEncodingDetectionRegression(unittest.TestCase):
    """detect_text_encoding backs read_text_file_safe, so its contract matters."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="encdetect_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_detects_common_encodings(self):
        cases = {
            "utf-8": "CHEETAH 猎豹\n".encode("utf-8"),
            "utf-8-sig": b"\xef\xbb\xbf" + "CHEETAH 猎豹\n".encode("utf-8"),
            "gb18030": "CHEETAH 猎豹\n".encode("gb18030"),
            "utf-16": "CHEETAH Cheetah\n".encode("utf-16"),
        }
        for expected, data in cases.items():
            self.assertEqual(detect_text_encoding(data), expected,
                             f"wrong codec for {expected}")

    def test_empty_input_reports_a_codec(self):
        self.assertEqual(detect_text_encoding(b""), "utf-8")

    def test_traditional_chinese_is_detected_as_big5(self):
        # gb18030 decodes Big5 bytes into Private Use Area code points, which is
        # exactly how the detector tells a wrong guess from a right one.
        text = "作者：夜行者\n售價 850\n"
        p = self.root / "big5"
        p.write_bytes(text.encode("big5"))
        self.assertEqual(detect_text_encoding(p.read_bytes()), "big5")
        self.assertEqual(read_text_file_safe(str(p)), text)

    def test_gb18030_guess_is_rejected_when_it_yields_private_use(self):
        raw = "作者：夜行者".encode("big5")
        self.assertTrue(has_private_use(raw.decode("gb18030")),
                        "the gb18030 guess must contain PUA for this rule to work")
        self.assertFalse(has_private_use(raw.decode("big5")))

    def test_simplified_chinese_still_resolves_to_gb18030(self):
        text = "作者：夜行者\n售价 850\n"
        p = self.root / "gbk"
        p.write_bytes(text.encode("gb18030"))
        self.assertEqual(detect_text_encoding(p.read_bytes()), "gb18030")
        self.assertEqual(read_text_file_safe(str(p)), text)

    def test_private_use_helper(self):
        self.assertTrue(has_private_use("\ue706"))
        self.assertTrue(has_private_use("正常\ue706文本"))
        self.assertTrue(has_private_use("\U000F0001"))
        self.assertFalse(has_private_use(""))
        self.assertFalse(has_private_use("正常文本"))
        self.assertFalse(has_private_use("Café Müller"))

    def test_read_text_file_safe_still_matches_the_original_semantics(self):
        # BOM handling and legacy fallbacks are the parts most easily broken.
        p = self.root / "bomutf8"
        p.write_bytes(b"\xef\xbb\xbf" + "CHEETAH 猎豹\n".encode("utf-8"))
        self.assertEqual(read_text_file_safe(str(p)), "CHEETAH 猎豹\n")

        p2 = self.root / "gbk"
        p2.write_bytes("CHEETAH 猎豹\n".encode("gb18030"))
        self.assertEqual(read_text_file_safe(str(p2)), "CHEETAH 猎豹\n")

    def test_every_sample_round_trips_through_its_detected_codec(self):
        """
        The invariant the FXT editor relies on: whatever codec detection picks,
        the decoded text must reproduce the original bytes. Legacy 8-bit text
        can be misattributed (gb18030 wins over cp1251 when both decode), but
        that is only cosmetic - untouched content still survives.
        """
        samples = {
            "ascii": b"CHEETAH Cheetah\n",
            "utf8": "CHEETAH 猎豹\n".encode("utf-8"),
            "bom": b"\xef\xbb\xbf" + "CHEETAH 猎豹\n".encode("utf-8"),
            "gbk": "CHEETAH 猎豹\n".encode("gb18030"),
            "cp1251": "CHEETAH Машина\n".encode("cp1251"),
            "cp1252": "CHEETAH Café\n".encode("cp1252"),
            "utf16": "CHEETAH Cheetah\n".encode("utf-16"),
        }
        for name, data in samples.items():
            codec = detect_text_encoding(data)
            self.assertIsNotNone(codec, name)
            p = self.root / name
            p.write_bytes(data)
            text = read_text_file_safe(str(p))
            encoded = text.encode("utf-16") if codec == "utf-16" else text.encode(codec)
            self.assertEqual(encoded, data, f"{name} did not round-trip via {codec}")


    def test_mirror_parts_excluded_from_carmods_vehicle_lines(self):
        """
        Mirror counterparts (e.g. wg_r_*, bntr_*) must NEVER appear on the
        vehicle line in carmods.dat because they are not sold in shopping.dat
        and will crash the game when entering a tuning garage.
        """
        merger = ConfigMerger(str(self.root / "shadow"), str(self.root / "game"))
        mod_info = {
            "success": True,
            "target_model": "stratum",
            "files": {
                "dff_files": ["stratum.dff"],
                "tuning_dffs": [
                    {"name": "wg_l_a_st.dff", "path": "/dummy/wg_l_a_st.dff"},
                    {"name": "wg_r_a_st.dff", "path": "/dummy/wg_r_a_st.dff"},
                    {"name": "fbmp_a_st.dff", "path": "/dummy/fbmp_a_st.dff"},
                ]
            },
            "parsed": {
                "handling": [], "ide": [], "carcols": [], "carmods": [],
                "veh_mods_ide": [], "shopping": {}, "fxt": [], "fxt_text": [],
                "audio_lines": [], "special_features": []
            }
        }
        plan = merger.plan_merge(mod_info)
        actions = plan["changes"]["carmods_dat"]["actions"]
        car_actions = [a for a in actions if a["type"] == "replace_or_insert_car_mods"]
        self.assertEqual(len(car_actions), 1)
        line = car_actions[0]["line"]
        self.assertIn("wg_l_a_st", line)
        self.assertIn("fbmp_a_st", line)
        self.assertNotIn("wg_r_a_st", line)


    def test_generic_carmods_parts_strictly_preserved(self):
        """
        Vehicles with nitro, hydraulics, or stereo in baseline carmods must have
        those exact generic upgrades strictly preserved when fallback carmods are generated,
        without adding upgrades the vehicle never had.
        """
        game_dir = self.root / "game_carmods_test"
        (game_dir / "data").mkdir(parents=True, exist_ok=True)
        (game_dir / "data" / "carmods.dat").write_text(
            "mods\n"
            "stratum, exh_a_st, nto_b_l, nto_b_s, nto_b_tw\n"
            "supergt, nto_b_s\n"
            "lowrider, exh_lr, hydralics, stereo\n"
            "copcar, none\n"
            "end\n",
            encoding="utf-8"
        )
        merger = ConfigMerger(str(self.root / "shadow_generic"), str(game_dir))

        # 1. Stratum: had nitro (all 3), no hydraulics, no stereo
        gen_st = merger.get_original_generic_carmods_parts("stratum")
        self.assertEqual(gen_st["nitro"], ["nto_b_l", "nto_b_s", "nto_b_tw"])
        self.assertEqual(gen_st["hydraulics"], [])
        self.assertEqual(gen_st["stereo"], [])

        merged_st = merger.merge_generic_carmods_parts("stratum", ["exh_a_st", "fbmp_a_st"])
        self.assertIn("nto_b_l", merged_st)
        self.assertIn("nto_b_s", merged_st)
        self.assertIn("nto_b_tw", merged_st)
        self.assertNotIn("hydralics", merged_st)
        self.assertNotIn("stereo", merged_st)

        # If current parts already had nitro, does not duplicate or overwrite
        merged_st_existing = merger.merge_generic_carmods_parts("stratum", ["exh_a_st", "nto_b_s"])
        self.assertEqual(merged_st_existing, ["exh_a_st", "nto_b_s"])

        # 2. SuperGT: had only nto_b_s
        gen_sgt = merger.get_original_generic_carmods_parts("supergt")
        self.assertEqual(gen_sgt["nitro"], ["nto_b_s"])
        self.assertEqual(gen_sgt["hydraulics"], [])
        merged_sgt = merger.merge_generic_carmods_parts("supergt", ["exh_sgt"])
        self.assertEqual(merged_sgt, ["exh_sgt", "nto_b_s"])

        # 3. Lowrider: had hydraulics and stereo, but no nitro
        gen_low = merger.get_original_generic_carmods_parts("lowrider")
        self.assertEqual(gen_low["nitro"], [])
        self.assertEqual(gen_low["hydraulics"], ["hydralics"])
        self.assertEqual(gen_low["stereo"], ["stereo"])
        merged_low = merger.merge_generic_carmods_parts("lowrider", ["exh_custom"])
        self.assertIn("hydralics", merged_low)
        self.assertIn("stereo", merged_low)
        self.assertNotIn("nto_b_l", merged_low)

        # 4. Copcar: had no tuning upgrades
        gen_cop = merger.get_original_generic_carmods_parts("copcar")
        self.assertEqual(gen_cop["nitro"], [])
        self.assertEqual(gen_cop["hydraulics"], [])
        self.assertEqual(gen_cop["stereo"], [])
        merged_cop = merger.merge_generic_carmods_parts("copcar", ["lightbar"])
        self.assertEqual(merged_cop, ["lightbar"])

    def test_multivehicle_addon_tuning_id_allocation_no_collision(self):
        """
        Verify that in a multi-vehicle mod pack with shared and vehicle-exclusive tuning parts,
        IDs allocated in veh_mods.ide are strictly unique with zero collisions.
        """
        temp_dir = tempfile.mkdtemp()
        try:
            shadow = os.path.join(temp_dir, "modloader", "Modded Cars")
            os.makedirs(shadow, exist_ok=True)
            os.makedirs(os.path.join(temp_dir, "data"), exist_ok=True)
            with open(os.path.join(shadow, "veh_mods.ide"), "w") as f:
                f.write("objs\nend\n")
            with open(os.path.join(shadow, "carmods.dat"), "w") as f:
                f.write("mods\nend\nlink\nend\n")

            merger = ConfigMerger(shadow_dir=shadow, game_path=temp_dir)
            parsed_mod = {
                "success": True,
                "target_model": "car_a",
                "target_models": ["car_a", "car_b"],
                "files": {"tuning_dffs": [], "tuning_txds": []},
                "parsed": {
                    "handling": [],
                    "ide": [],
                    "carcols": [],
                    "carmods": [
                        {"model_name": "car_a", "part_names": ["exh_shared", "spl_a_exclusive"]},
                        {"model_name": "car_b", "part_names": ["exh_shared", "spl_b_exclusive"]},
                    ],
                    "veh_mods_ide": [
                        {"part_name": "exh_shared", "txd_name": "car_a", "draw_dist": 100.0, "flags": 2097152},
                        {"part_name": "spl_a_exclusive", "txd_name": "car_a", "draw_dist": 100.0, "flags": 2101248},
                        {"part_name": "spl_b_exclusive", "txd_name": "car_b", "draw_dist": 100.0, "flags": 2101248},
                    ],
                    "shopping": {},
                    "fxt": [],
                    "fxt_text": [],
                    "audio_lines": [],
                    "special_features": []
                }
            }
            plan = merger.plan_merge(parsed_mod)
            vm_actions = plan["changes"]["veh_mods_ide"]["actions"]
            self.assertEqual(len(vm_actions), 3)

            allocated_ids = [a["id"] for a in vm_actions]
            allocated_parts = [a["part"] for a in vm_actions]

            # All 3 parts must have distinct IDs
            self.assertEqual(len(set(allocated_ids)), 3, f"Duplicate IDs detected: {allocated_ids}")
            self.assertEqual(set(allocated_parts), {"exh_shared", "spl_a_exclusive", "spl_b_exclusive"})

            # Verify apply_merge writes all 3 unique entries
            res = merger.apply_merge(parsed_mod)
            self.assertTrue(res["success"])
            with open(os.path.join(shadow, "veh_mods.ide")) as f:
                vm_content = f.read()
            self.assertIn("exh_shared", vm_content)
            self.assertIn("spl_a_exclusive", vm_content)
            self.assertIn("spl_b_exclusive", vm_content)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_multivehicle_revert_preserves_shared_tuning_parts(self):
        """
        Verify that uninstalling one vehicle of a shared-tuning pack preserves
        tuning parts still referenced by other active vehicles in carmods.dat.
        """
        from core.cleaner import ModCleaner
        temp_dir = tempfile.mkdtemp()
        try:
            shadow = os.path.join(temp_dir, "modloader", "Modded Cars")
            vanilla = os.path.join(temp_dir, "data")
            os.makedirs(shadow, exist_ok=True)
            os.makedirs(vanilla, exist_ok=True)

            # Pre-populate shadow files with two vehicles sharing exh_shared
            with open(os.path.join(shadow, "carmods.dat"), "w") as f:
                f.write("mods\ncar_a, exh_shared, spl_a\ncar_b, exh_shared, spl_b\nend\n")
            with open(os.path.join(shadow, "veh_mods.ide"), "w") as f:
                f.write("objs\n11747, exh_shared, car_a, 100, 2097152\n11748, spl_a, car_a, 100, 2101248\n11749, spl_b, car_b, 100, 2101248\nend\n")
            with open(os.path.join(shadow, "shopping.dat"), "w") as f:
                f.write("section prices\nsection CarMods\nexh_shared E_SH respect 0 sexy 0 500\nspl_a S_A respect 0 sexy 0 500\nspl_b S_B respect 0 sexy 0 500\nend\nend\n")

            cleaner = ModCleaner(game_path=temp_dir)
            # Revert car_a
            cleaner._revert_veh_mods("car_a", {"exh_shared", "spl_a"})
            cleaner._revert_shopping("car_a", {"exh_shared", "spl_a"})

            with open(os.path.join(shadow, "veh_mods.ide")) as f:
                vm_after = f.read()
            # spl_a must be gone, but exh_shared must be preserved because car_b still uses it
            self.assertNotIn("spl_a", vm_after)
            self.assertIn("exh_shared", vm_after)
            self.assertIn("spl_b", vm_after)

            with open(os.path.join(shadow, "shopping.dat")) as f:
                shop_after = f.read()
            self.assertNotIn("spl_a", shop_after)
            self.assertIn("exh_shared", shop_after)
            self.assertIn("spl_b", shop_after)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class DeclaredTxdRegression(unittest.TestCase):
    """A new model may declare another vehicle's TXD in its vehicles.ide line
    (e.g. "ID, sentxs, sentinel, car, ..."): the installer must keep the
    author's column and deploy the texture under the name the written line
    references instead of defaulting it to the model name."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="declared_txd_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 10, 0, 0, -1, 0.73, 0.73, 0\nend\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("SENTINEL") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("car\nsentinel, 51, 0\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nsentinel, nto_b_l\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.source = Path(self.temp.name) / "sentinel84"
        self.source.mkdir()
        (self.source / "sentinel.dff").write_bytes(b"sentinel dff")
        (self.source / "sentinel.txd").write_bytes(b"sentinel txd")
        (self.source / "sentxs.dff").write_bytes(b"sentxs dff")
        (self.source / "sentxs.fxt").write_text("SENTXS Sentinel XS\n", encoding="utf-8")
        (self.source / "readme.txt").write_text(
            "vehicles.ide\n"
            "405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 10, 0, 0, -1, 0.73, 0.73, 0\n"
            "ID, sentxs, sentinel, car, SENTXS, SENTXS, null, executive, 8, 0, 0, -1, 0.73, 0.73, 0\n",
            encoding="utf-8")
        self.backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup)

    def payload(self, skip_replace=False, **addon_overrides):
        addon = {
            "source_model": "sentxs", "target_model": "sentxs", "category": "Addon Cars",
            "addon_id": 12093, "declared_txd": "sentinel", "target_txd": "",
            "generate_fxt": True, "fxt_key": "SENTXS", "fxt_name": "Sentinel XS",
        }
        addon.update(addon_overrides)
        return {
            "inspect_dir": str(self.source), "target_category": "Addon Cars", "folder_name": "Sentinel84",
            "vehicles": [
                {"source_model": "sentinel", "target_model": "sentinel", "category": "Modded Cars",
                 "skip": skip_replace},
                addon,
            ],
        }

    def installed_line(self, model):
        text = (self.shadow / "vehicles.ide").read_text(encoding="utf-8-sig")
        return next(line for line in text.splitlines() if model in line.lower())

    def test_inspection_reports_the_declared_texture(self):
        inspection = self.installer.inspect_source(str(self.source))
        self.assertTrue(inspection["success"], inspection)
        by_model = {v["model"]: v for v in inspection["target_vehicles"]}
        self.assertEqual(by_model["sentxs"]["declared_txd"], "sentinel")
        self.assertEqual(by_model["sentxs"]["txd_files"], [])
        self.assertEqual(by_model["sentinel"]["txd_files"], ["sentinel.txd"])

    def test_addon_keeps_the_authors_texture_column(self):
        res = self.installer.execute_install(self.payload())
        self.assertTrue(res["success"], res)
        dec = DualTrackParser().decompose_ide(self.installed_line("sentxs"))
        self.assertEqual(dec["id"], 12093)
        self.assertEqual(dec["model_name"], "sentxs")
        self.assertEqual(dec["txd_name"], "sentinel")
        self.assertTrue((self.shadow / "Sentinel84" / "sentinel.txd").is_file())

    def test_shared_texture_is_deployed_when_its_owner_is_skipped(self):
        res = self.installer.execute_install(self.payload(skip_replace=True))
        self.assertTrue(res["success"], res)
        self.assertEqual(DualTrackParser().decompose_ide(self.installed_line("sentxs"))["txd_name"], "sentinel")
        addon_dir = self.game / "modloader" / "Addon Cars" / "Sentinel84"
        self.assertTrue((addon_dir / "sentinel.txd").is_file())
        self.assertFalse((addon_dir / "sentinel.dff").exists())

    def test_explicit_texture_name_overrides_the_declared_one(self):
        res = self.installer.execute_install(self.payload(target_txd="custm_txd"))
        self.assertTrue(res["success"], res)
        self.assertEqual(DualTrackParser().decompose_ide(self.installed_line("sentxs"))["txd_name"], "custm_txd")

    def test_payload_without_texture_information_keeps_line_and_file_in_sync(self):
        res = self.installer.execute_install({
            "inspect_dir": str(self.source), "target_category": "Addon Cars", "folder_name": "SentinelXS",
            "target_model": "sentxs", "source_model": "sentxs", "source_type": "car",
            "generate_fxt": True, "merge_fla": False,
        })
        self.assertTrue(res["success"], res)
        self.assertEqual(DualTrackParser().decompose_ide(self.installed_line("sentxs"))["txd_name"], "sentinel")
        self.assertTrue((self.game / "modloader" / "Addon Cars" / "SentinelXS" / "sentinel.txd").is_file())

    def test_package_without_declaration_keeps_the_model_name(self):
        plain = Path(self.temp.name) / "plain"
        plain.mkdir()
        (plain / "plaincar.dff").write_bytes(b"dff")
        (plain / "plaincar.txd").write_bytes(b"txd")
        (plain / "readme.txt").write_text(
            "vehicles.ide\nID, plaincar, plaincar, car, PLAINCAR, PLAINCAR, null, normal, 5, 0, 0, -1, 0.7, 0.7, 0\n",
            encoding="utf-8")
        res = self.installer.execute_install({
            "inspect_dir": str(plain), "target_category": "Addon Cars", "folder_name": "Plain",
            "vehicles": [{"source_model": "plaincar", "target_model": "plaincar", "category": "Addon Cars",
                          "addon_id": 12094, "target_txd": "", "declared_txd": "plaincar"}],
        })
        self.assertTrue(res["success"], res)
        self.assertEqual(DualTrackParser().decompose_ide(self.installed_line("plaincar"))["txd_name"], "plaincar")
        self.assertTrue((self.game / "modloader" / "Addon Cars" / "Plain" / "plaincar.txd").is_file())


class PartFileNamingRegression(unittest.TestCase):
    """A tuning part whose file name follows no known prefix (and is not in a
    "tuning" folder) must keep its own name: renaming it onto the vehicle model
    used to overwrite the car's own DFF/TXD, or silently drop the part."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="part_names_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n"
            "405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 10, 0, 0, -1, 0.73, 0.73, 0\n"
            "602, blade, blade, car, BLADE, BLADE, null, executive, 8, 0, 0, -1, 0.7, 0.7, 0\n"
            "end\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("SENTINEL") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("car\nsentinel, 51, 0\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nsentinel, nto_b_l\nend\n", encoding="utf-8")
        (self.game / "data" / "shopping.dat").write_text(
            "section prices\nsection CarMods\nnto_b_l NTO respect 0 sexy 0 500\nend\nend\n", encoding="utf-8")
        vm_dir = self.game / "data" / "maps" / "veh_mods"
        vm_dir.mkdir(parents=True, exist_ok=True)
        (vm_dir / "veh_mods.ide").write_text("objs\n1005, bnt_b_sc_l, vehicle, 70, 0\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup)

    def pack(self, name, part=None, referenced=False, extra_vehicle=False):
        source = Path(self.temp.name) / name
        source.mkdir()
        (source / "sentinel.dff").write_bytes(b"CAR MODEL BINARY")
        (source / "sentinel.txd").write_bytes(b"CAR TEXTURE BINARY")
        if extra_vehicle:
            (source / "blade.dff").write_bytes(b"SECOND CAR MODEL")
            (source / "blade.txd").write_bytes(b"SECOND CAR TEXTURE")
        readme = ("vehicles.ide\n"
                  "405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 10, 0, 0, -1, 0.73, 0.73, 0\n")
        if extra_vehicle:
            readme += "602, blade, blade, car, BLADE, BLADE, null, executive, 8, 0, 0, -1, 0.7, 0.7, 0\n"
        if part:
            (source / (part + ".dff")).write_bytes(b"PART DFF BINARY")
            (source / (part + ".txd")).write_bytes(b"PART TXD BINARY")
            if referenced:
                readme += ("\nveh_mods.ide\n"
                           f"11000, {part}, sentinel, 100, 2097152\n"
                           "\ncarmods.dat\n"
                           f"sentinel, {part}\n"
                           "\nshopping.dat\n"
                           "section CarMods\n"
                           f"{part} ADAM respect 0 sexy 0 777\nend\n")
        (source / "readme.txt").write_text(readme, encoding="utf-8")
        return source

    def deploy(self, source, vehicles=None, **extra):
        params = {"inspect_dir": str(source), "target_category": "Modded Cars", "folder_name": "Pack",
                  "merge_fla": False, "generate_fxt": False}
        if vehicles is None:
            params.update({"target_model": "sentinel", "source_model": "sentinel", "source_type": "car"})
        else:
            params["vehicles"] = vehicles
        params.update(extra)
        return self.installer.execute_install(params)

    def deployed(self, name):
        return (self.shadow / "Pack" / name).read_bytes()

    def test_inspection_does_not_offer_a_referenced_part_as_a_vehicle(self):
        source = self.pack("classified", part="airdam", referenced=True)
        inspection = self.installer.inspect_source(str(source))
        self.assertTrue(inspection["success"], inspection)
        models = [v["model"] for v in inspection["target_vehicles"]]
        self.assertIn("sentinel", models)
        self.assertNotIn("airdam", models)
        tuning_names = [f["name"] for f in inspection["asset_files"]["tuning"]]
        self.assertIn("airdam.dff", tuning_names)

    def test_configured_part_keeps_its_name_and_never_replaces_the_car(self):
        source = self.pack("configured", part="airdam", referenced=True)
        res = self.deploy(source)
        self.assertTrue(res["success"], res)
        self.assertEqual(self.deployed("sentinel.dff"), b"CAR MODEL BINARY")
        self.assertEqual(self.deployed("sentinel.txd"), b"CAR TEXTURE BINARY")
        self.assertEqual(self.deployed("airdam.dff"), b"PART DFF BINARY")
        self.assertEqual(self.deployed("airdam.txd"), b"PART TXD BINARY")
        self.assertIn("airdam", (self.shadow / "carmods.dat").read_text(encoding="utf-8-sig"))

    def test_unlisted_extra_file_keeps_its_name_instead_of_overwriting_the_car(self):
        source = self.pack("extra", part="airdam", referenced=False)
        res = self.deploy(source)
        self.assertTrue(res["success"], res)
        self.assertEqual(self.deployed("sentinel.dff"), b"CAR MODEL BINARY")
        self.assertEqual(self.deployed("sentinel.txd"), b"CAR TEXTURE BINARY")
        self.assertEqual(self.deployed("airdam.dff"), b"PART DFF BINARY")
        self.assertEqual(self.deployed("airdam.txd"), b"PART TXD BINARY")

    def test_part_survives_when_the_other_vehicle_is_skipped(self):
        source = self.pack("skipped", part="airdam", referenced=True, extra_vehicle=True)
        res = self.deploy(source, vehicles=[
            {"source_model": "sentinel", "target_model": "sentinel", "category": "Modded Cars", "target_txd": ""},
            {"source_model": "blade", "target_model": "blade", "category": "Modded Cars", "skip": True},
        ])
        self.assertTrue(res["success"], res)
        self.assertEqual(self.deployed("sentinel.dff"), b"CAR MODEL BINARY")
        self.assertEqual(self.deployed("sentinel.txd"), b"CAR TEXTURE BINARY")
        self.assertEqual(self.deployed("airdam.dff"), b"PART DFF BINARY")

    def test_pack_without_its_own_model_still_installs_under_the_target_name(self):
        source = Path(self.temp.name) / "renamed"
        source.mkdir()
        (source / "recurve.dff").write_bytes(b"ONLY MODEL BINARY")
        (source / "recurve.txd").write_bytes(b"ONLY TEXTURE BINARY")
        res = self.deploy(source)
        self.assertTrue(res["success"], res)
        self.assertEqual(self.deployed("sentinel.dff"), b"ONLY MODEL BINARY")
        self.assertEqual(self.deployed("sentinel.txd"), b"ONLY TEXTURE BINARY")


class ShortIdeLineMergeRegression(unittest.TestCase):
    """A package whose vehicles.ide line stops early must not shorten the
    target's line: columns it does not declare keep their vanilla values
    instead of falling back to engine defaults."""

    VANILLA_LINE = "405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 10, 0, 0, -1, 0.73, 0.73, 0"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="short_ide_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(f"cars\n{self.VANILLA_LINE}\nend\n", encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("SENTINEL") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("car\nsentinel, 51, 0\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nsentinel, nto_b_l\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.source = Path(self.temp.name) / "shortpack"
        self.source.mkdir()
        (self.source / "sentinel.dff").write_bytes(b"dff")
        (self.source / "sentinel.txd").write_bytes(b"txd")
        (self.source / "readme.txt").write_text(
            "vehicles.ide\n405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 3\n", encoding="utf-8")
        self.backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup)

    def test_undeclared_trailing_columns_keep_their_vanilla_values(self):
        res = self.installer.execute_install({
            "inspect_dir": str(self.source), "target_category": "Modded Cars", "folder_name": "ShortPack",
            "vehicles": [{"source_model": "sentinel", "target_model": "sentinel", "category": "Modded Cars",
                          "target_txd": "", "merge_handling": False, "merge_carcols": False,
                          "merge_carmods": False, "merge_fla": False, "generate_fxt": False}],
        })
        self.assertTrue(res["success"], res)
        ide = (self.shadow / "vehicles.ide").read_text(encoding="utf-8-sig")
        line = next(l for l in ide.splitlines() if l.strip().startswith("405,"))
        tokens = [t.strip() for t in line.split(",")]
        vanilla = [t.strip() for t in self.VANILLA_LINE.split(",")]
        self.assertEqual(tokens[:6], vanilla[:6])
        self.assertEqual(tokens[8], "3")
        self.assertEqual(tokens[9:], vanilla[9:])


class ShoppingPriceOverrideNoteRegression(unittest.TestCase):
    """An author who re-prices an already registered part must not have the
    declaration vanish silently: the existing entry stays (rewriting lines in
    the shared shopping.dat is out of scope) and the install reports it."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="price_note_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n477, zr350, zr350, car, ZR350, ZR350, null, richfamily, 8, 0, 0, -1, 0.76, 0.76, 1\nend\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("ZR350") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("car\nzr350, 51, 0\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text("mods\nzr350, exh_a_zr\nend\n", encoding="utf-8")
        # Vanilla price entry the package tries to re-price.
        (self.game / "data" / "shopping.dat").write_text(
            "section prices\nsection CarMods\nexh_a_zr ZR2AE respect 0 sexy 0 850\nend\nend\n", encoding="utf-8")
        vm_dir = self.game / "data" / "maps" / "veh_mods"
        vm_dir.mkdir(parents=True, exist_ok=True)
        (vm_dir / "veh_mods.ide").write_text("objs\n1000, exh_a_zr, zr350, 100, 2097152\nend\n", encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.source = Path(self.temp.name) / "pack"
        self.source.mkdir()
        (self.source / "zr350.dff").write_bytes(b"dff")
        (self.source / "zr350.txd").write_bytes(b"txd")
        (self.source / "exh_a_zr.dff").write_bytes(b"part dff")
        (self.source / "newpart1.dff").write_bytes(b"new part dff")
        self.backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup)

    def install(self, shopping_body):
        (self.source / "readme.txt").write_text(
            "vehicles.ide\n"
            "477, zr350, zr350, car, ZR350, ZR350, null, richfamily, 8, 0, 0, -1, 0.76, 0.76, 1\n"
            "\ncarmods.dat\nzr350, exh_a_zr, newpart1\n"
            "\nveh_mods.ide\nID, newpart1, zr350, 100, 2097152\n"
            "\nshopping.dat\nsection CarMods\n" + shopping_body + "end\n",
            encoding="utf-8")
        return self.installer.execute_install({
            "inspect_dir": str(self.source), "target_category": "Modded Cars", "folder_name": "ZR350HD",
            "vehicles": [{"source_model": "zr350", "target_model": "zr350", "category": "Modded Cars",
                          "target_txd": "", "merge_fla": False, "generate_fxt": False}],
        })

    def test_repricing_an_existing_part_keeps_the_entry_and_reports_it(self):
        res = self.install("exh_a_zr ZR2AE respect 5 sexy 3 1200\n"
                           "newpart1 NEWPART respect 0 sexy 0 777\n")
        self.assertTrue(res["success"], res)
        shopping = (self.shadow / "shopping.dat").read_text(encoding="utf-8-sig")
        self.assertIn("exh_a_zr ZR2AE respect 0 sexy 0 850", shopping)
        self.assertNotIn("1200", shopping)
        self.assertIn("newpart1", shopping)
        self.assertIn("777", shopping)
        notes = res.get("ide_notes") or []
        self.assertTrue(any("shopping.dat" in n and "EXH_A_ZR" in n and "$1200" in n for n in notes), notes)

    def test_new_parts_are_registered_without_a_note(self):
        res = self.install("newpart1 NEWPART respect 0 sexy 0 777\n")
        self.assertTrue(res["success"], res)
        shopping = (self.shadow / "shopping.dat").read_text(encoding="utf-8-sig")
        self.assertIn("777", shopping)
        self.assertEqual(res.get("ide_notes") or [], [])


class CarmodsDeclarationRegression(unittest.TestCase):
    """A part list the package declares is deployed verbatim - the vehicle's
    generic upgrades (nitro/hydraulics/stereo) are no longer re-added behind
    the author's back. Only a fallback list the tool has to generate itself
    (a package that ships part files but no carmods.dat) keeps the car's
    baseline generics."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="carmods_decl_")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"x")
        (self.game / "data" / "vehicles.ide").write_text(
            "cars\n405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 10, 0, 0, -1, 0.73, 0.73, 0\nend\n",
            encoding="utf-8")
        (self.game / "data" / "handling.cfg").write_text("; h\n" + handling("SENTINEL") + "\n", encoding="utf-8")
        (self.game / "data" / "carcols.dat").write_text("car\nsentinel, 51, 0\nend\n", encoding="utf-8")
        (self.game / "data" / "carmods.dat").write_text(
            "mods\nsentinel, exh_b_l, exh_b_m, nto_b_l, nto_b_s, nto_b_tw\nend\n", encoding="utf-8")
        (self.game / "data" / "shopping.dat").write_text(
            "section prices\nsection CarMods\nnto_b_l BMBLN respect 0 sexy 0 500\n"
            "nto_b_s BMBSM respect 0 sexy 0 200\nnto_b_tw BMBTN respect 0 sexy 0 1000\nend\nend\n",
            encoding="utf-8")
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.source = Path(self.temp.name) / "pack"
        self.source.mkdir()
        (self.source / "sentinel.dff").write_bytes(b"dff")
        (self.source / "sentinel.txd").write_bytes(b"txd")
        self.backup = BackupManager(backup_dir=str(Path(self.temp.name) / "backups"), game_dir=str(self.game))
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup_manager=self.backup)

    def install(self, readme):
        (self.source / "readme.txt").write_text(readme, encoding="utf-8")
        return self.installer.execute_install({
            "inspect_dir": str(self.source), "target_category": "Modded Cars", "folder_name": "Pack",
            "vehicles": [{"source_model": "sentinel", "target_model": "sentinel", "category": "Modded Cars",
                          "target_txd": "", "merge_fla": False, "generate_fxt": False}],
        })

    def installed_line(self):
        text = (self.shadow / "carmods.dat").read_text(encoding="utf-8-sig")
        return next(l for l in text.splitlines() if l.strip().lower().startswith("sentinel"))

    def test_declared_list_is_deployed_verbatim(self):
        (self.source / "fbmp_hd_a.dff").write_bytes(b"part")
        res = self.install(
            "vehicles.ide\n405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 10, 0, 0, -1, 0.73, 0.73, 0\n"
            "\ncarmods.dat\nsentinel, fbmp_hd_a\n")
        self.assertTrue(res["success"], res)
        line = self.installed_line()
        self.assertIn("fbmp_hd_a", line)
        self.assertNotIn("nto_", line)

    def test_generated_fallback_keeps_baseline_generics(self):
        (self.source / "spl_hd_a.dff").write_bytes(b"part")
        res = self.install(
            "vehicles.ide\n405, sentinel, sentinel, car, SENTINEL, SENTINL, null, executive, 10, 0, 0, -1, 0.73, 0.73, 0\n")
        self.assertTrue(res["success"], res)
        line = self.installed_line()
        self.assertIn("spl_hd_a", line)
        self.assertIn("nto_b_l", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)



