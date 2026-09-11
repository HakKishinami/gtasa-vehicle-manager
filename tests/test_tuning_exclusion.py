"""
Tests for tuning parts parsing heuristics and fallback exclusion feature.
"""

import os
import shutil
import tempfile
import unittest

from core.parser import DualTrackParser
from core.installer import ModInstaller
from core.vanilla_data import VANILLA_VEHICLES, MODEL_TO_ID


SAMPLE_ZR350_README = """
-----------------------------------##| VEH_MODS.IDE |##----------------------------------
ID, exh_a_zr, zr350, 100, 2097152
ID, exh_c_zr, zr350, 100, 2097152
ID, fbmp_a_zr, zr350, 100, 2097152
ID, fbmp_c_zr, zr350, 100, 2097152
ID, rbmp_a_zr, zr350, 100, 2097152
ID, rbmp_c_zr, zr350, 100, 2097152
ID, rf_a_zr, zr350, 100, 2097152
ID, rf_c_zr, zr350, 100, 2097152
ID, spl_a_zr_b, zr350, 100, 2097152
ID, spl_c_zr_b, zr350, 100, 2097152
ID, wg_l_a_zr, zr350, 100, 2097152
ID, wg_l_c_zr, zr350, 100, 2097152

-----------------------------------##| CARMODS.DAT |##-----------------------------------
zr350, exh_a_zr, exh_c_zr, fbmp_a_zr, fbmp_c_zr, rbmp_a_zr, rbmp_c_zr, rf_a_zr, rf_c_zr, spl_a_zr_b, spl_c_zr_b, wg_l_a_zr, wg_l_c_zr

-----------------------------------##| HANDLING.CFG |##----------------------------------
ZR350        1400.0 2998.3 2.0 0.0 0.1 -0.15 70 0.75 0.82 0.52 5 200.0 22.0 10.0 R P 8.0 0.52 0 30.0 1.2 0.15 0.0 0.28 -0.12 0.5 0.3 0.24 0.10 35000 00222004 01400002 0 1 0

-----------------------------------##| CARCOLS.DAT |##-----------------------------------
zr350, 0,0, 1,1, 3,3, 6,6
"""


class TuningParserAndExclusionTests(unittest.TestCase):
    def setUp(self):
        self.parser = DualTrackParser()

    def test_section_header_matches_pipe_decorations(self):
        header1 = "-----------------------------------##| VEH_MODS.IDE |##----------------------------------"
        header2 = "-----------------------------------##| CARMODS.DAT |##-----------------------------------"
        parsed = self.parser.parse_text_content(header1 + "\n11735, exh_a_zr, zr350, 100, 2097152\n" + header2 + "\nzr350, exh_a_zr\n")
        self.assertEqual(len(parsed["veh_mods_ide"]), 1)
        self.assertEqual(len(parsed["carmods_dat"]), 1)

    def test_carmods_line_heuristic_rejects_numeric_parts_and_placeholder_ids(self):
        veh_mod_line = "ID, exh_a_zr, zr350, 100, 2097152"
        self.assertFalse(self.parser._is_carmods_line(veh_mod_line))
        self.assertTrue(self.parser._is_veh_mod_line(veh_mod_line))

    def test_decompose_veh_mod_supports_placeholder_id(self):
        res = self.parser.decompose_veh_mod("ID, exh_a_zr, zr350, 100, 2097152")
        self.assertIsNotNone(res)
        self.assertIsNone(res["id"])
        self.assertEqual(res["part_name"], "exh_a_zr")
        self.assertEqual(res["txd_name"], "zr350")
        self.assertEqual(res["draw_dist"], 100.0)
        self.assertEqual(res["flags"], 2097152)

    def test_parse_zr350_readme_cleanly_separates_carmods_and_veh_mods(self):
        parsed = self.parser.parse_text_content(SAMPLE_ZR350_README)
        self.assertEqual(len(parsed["carmods_dat"]), 1)
        self.assertEqual(len(parsed["veh_mods_ide"]), 12)
        self.assertTrue(parsed["carmods_dat"][0].strip().startswith("zr350,"))

    def test_installer_inspect_source_tuning_analysis(self):
        temp_dir = tempfile.mkdtemp()
        try:
            game_dir = os.path.join(temp_dir, "game")
            os.makedirs(os.path.join(game_dir, "data", "maps", "veh_mods"), exist_ok=True)
            with open(os.path.join(game_dir, "data", "carmods.dat"), "w") as f:
                f.write("mods\nzr350, nto_b_l\nend\n")
            with open(os.path.join(game_dir, "data", "maps", "veh_mods", "veh_mods.ide"), "w") as f:
                f.write("objs\n1000, nto_b_l, vehicle, 70, 0\nend\n")
            with open(os.path.join(game_dir, "data", "shopping.dat"), "w") as f:
                f.write("section prices\nsection CarMods\nend\nend\nsection carmod1\ntype CarMods\nend\n")

            mod_dir = os.path.join(temp_dir, "zr350_mod")
            os.makedirs(mod_dir, exist_ok=True)
            with open(os.path.join(mod_dir, "readme.txt"), "w") as f:
                f.write(SAMPLE_ZR350_README)

            installer = ModInstaller(game_dir)
            insp = installer.inspect_source(mod_dir)
            self.assertTrue(insp["success"])

            analysis = insp["tuning_parts_analysis"]
            self.assertEqual(len(analysis), 12)

            part_names = [p["part_name"] for p in analysis]
            self.assertIn("exh_a_zr", part_names)
            self.assertIn("fbmp_a_zr", part_names)
            self.assertIn("wg_l_a_zr", part_names)
            self.assertNotIn("100", part_names)
            self.assertNotIn("2097152", part_names)
            self.assertNotIn("zr350", part_names)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_installer_excludes_tuning_parts(self):
        temp_dir = tempfile.mkdtemp()
        try:
            game_dir = os.path.join(temp_dir, "game")
            os.makedirs(os.path.join(game_dir, "data", "maps", "veh_mods"), exist_ok=True)
            with open(os.path.join(game_dir, "data", "carmods.dat"), "w") as f:
                f.write("mods\nzr350, nto_b_l\nend\n")
            with open(os.path.join(game_dir, "data", "maps", "veh_mods", "veh_mods.ide"), "w") as f:
                f.write("objs\n1000, nto_b_l, vehicle, 70, 0\nend\n")
            with open(os.path.join(game_dir, "data", "shopping.dat"), "w") as f:
                f.write("section prices\nsection CarMods\nend\nend\nsection carmod1\ntype CarMods\nend\n")

            mod_dir = os.path.join(temp_dir, "zr350_mod")
            os.makedirs(mod_dir, exist_ok=True)
            with open(os.path.join(mod_dir, "readme.txt"), "w") as f:
                f.write(SAMPLE_ZR350_README)
            with open(os.path.join(mod_dir, "exh_a_zr.dff"), "wb") as f:
                f.write(b"dff1")
            with open(os.path.join(mod_dir, "exh_c_zr.dff"), "wb") as f:
                f.write(b"dff2")
            with open(os.path.join(mod_dir, "zr350.dff"), "wb") as f:
                f.write(b"cardff")

            installer = ModInstaller(game_dir)
            insp = installer.inspect_source(mod_dir)

            res = installer.execute_install({
                "inspect_dir": mod_dir,
                "folder_name": "zr350_test",
                "target_category": "Modded Cars",
                "target_model": "zr350",
                "excluded_tuning_parts": ["exh_c_zr"],
                "parsed_config": insp["parsed_config"],
                "merge_carmods": True,
                "copy_files": True,
            })
            self.assertTrue(res["success"])

            installed_folder = res["installed_path"]
            self.assertTrue(os.path.exists(os.path.join(installed_folder, "exh_a_zr.dff")))
            self.assertFalse(os.path.exists(os.path.join(installed_folder, "exh_c_zr.dff")))

            shadow_carmods = os.path.join(game_dir, "modloader", "Modded Cars", "carmods.dat")
            self.assertTrue(os.path.exists(shadow_carmods))
            with open(shadow_carmods, "r") as f:
                cm_content = f.read()
            self.assertIn("exh_a_zr", cm_content)
            self.assertNotIn("exh_c_zr", cm_content)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
