"""Inline source samples; no fixture files or game installation are required.

VMM_TEST_ALPHA_SOURCE optionally points to the installed 1992 Bravado Alpha
folder. Its archived readme is restored only in a temporary copy for testing
the original installation input; the user's installed game is never changed.
"""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.backup_manager import BackupManager
from core.installer import ModInstaller
from core.merger import ConfigMerger
from core.parser import DualTrackParser


ALPHA = "alpha, 42,42,0,0, 36,42,0,0, 14,42,0,0, 4,42,0,0, 53,42,0,0, 41,42,0,0, 30,42,0,0, 8,42,0,0, "
ELEGY = "elegy, 36,1, 35,1, 17,1, 11,1, 116,1, 113,1, 101,1, 92,1"
CAMPER = "camper, 1,31,1,0, 1,31,1,0, 1,20,3,0, 1,5,0,0, 0,6,3,0, 3,6,3,0, 16,0,8,0, 17,0,120,0"
ALPHA_IDE = "602, alpha, alpha, car, ALPHA, ALPHA, null, normal, 10, 0, 0, -1, 0.78, 0.78, 0"


class CarcolsInferenceRegression(unittest.TestCase):
    def setUp(self):
        self.parser = DualTrackParser()

    def parse(self, text):
        return [self.parser.decompose_carcols(row)
                for row in self.parser.parse_text_content(text)["carcols_dat"]]

    def test_alpha_without_car4_is_eight_four_color_schemes(self):
        for text in (ALPHA, "carcols.dat\n----------------\n" + ALPHA,
                     "carcols.dat: " + ALPHA, "; " + ALPHA):
            with self.subTest(text=text):
                rows = self.parse(text)
                self.assertEqual(len(rows), 1)
                cfg = rows[0]
                self.assertEqual(cfg["model_name"], "alpha")
                self.assertTrue(cfg["is_car4"])
                self.assertEqual(cfg["count"], 8)
                self.assertEqual([s["c1"] for s in cfg["color_sets"]], [42, 36, 14, 4, 53, 41, 30, 8])
                self.assertTrue(all([s["c2"], s["c3"], s["c4"]] == [42, 0, 0] for s in cfg["color_sets"]))

    def test_elegy_pairs_remain_two_color(self):
        cfg = self.parse(ELEGY)[0]
        self.assertFalse(cfg["is_car4"])
        self.assertEqual(cfg["count"], 8)

    def test_camper_groups_are_inferred_without_a_section(self):
        cfg = self.parse(CAMPER)[0]
        self.assertTrue(cfg["is_car4"])
        self.assertEqual(cfg["count"], 8)

    def test_explicit_car_overrides_four_number_grouping(self):
        for text in ("carcols.dat\ncar\n" + ALPHA + "\nend", "car\n" + ALPHA + "\nend", "car " + ALPHA):
            with self.subTest(text=text):
                cfg = self.parse(text)[0]
                self.assertFalse(cfg["is_car4"])
                self.assertEqual(cfg["count"], 16)

    def test_explicit_car4_overrides_pair_grouping(self):
        for text in ("carcols.dat\ncar4\n" + ELEGY + "\nend", "car4\n" + ELEGY + "\nend", "car4 " + ELEGY):
            with self.subTest(text=text):
                cfg = self.parse(text)[0]
                self.assertTrue(cfg["is_car4"])
                self.assertEqual(cfg["count"], 4)

    def test_complete_dat_file_keeps_each_explicit_section(self):
        rows = self.parse("col\n0,0,0\nend\ncar\n" + ALPHA + "\nend\ncar4\n" + CAMPER + "\nend")
        self.assertEqual([(c["model_name"], c["is_car4"]) for c in rows], [("alpha", False), ("camper", True)])

    def test_uniform_spaces_mixed_groups_and_single_group_are_ambiguous(self):
        for row in ("alpha, 1,2,3,4", "alpha, 1,2,3,4,5,6,7,8",
                    "alpha, 1, 2, 3, 4, 5, 6, 7, 8",
                    "alpha, 1,2,3,4, 5,6, 7,8", "alpha, 1,2,3,4, 5,6,7, 8"):
            with self.subTest(row=row):
                self.assertFalse(self.parse(row)[0]["is_car4"])

    def test_tabs_trailing_comma_and_comments_preserve_grouping(self):
        for suffix in ("", " # colors", " ; colors", " // colors"):
            with self.subTest(suffix=suffix):
                cfg = self.parse("alpha,\t1,2,3,4,\t5,6,7,8, " + suffix)[0]
                self.assertTrue(cfg["is_car4"])
                self.assertEqual(cfg["count"], 2)

    def test_mode_does_not_leak_across_headers_or_document_boundaries(self):
        for boundary in ("carcols.dat", "handling.cfg", "--- FILE: other.txt ---", "--- Readme: other.txt ---", "end"):
            for mode, row, expected in (("car", ALPHA, True), ("car4", ELEGY, False)):
                with self.subTest(boundary=boundary, mode=mode):
                    cfg = self.parse(f"carcols.dat\n{mode}\n{boundary}\n{row}")[0]
                    self.assertEqual(cfg["is_car4"], expected)

    def test_inferred_mode_survives_whitespace_normalization(self):
        normalized = self.parser.parse_text_content(ALPHA)["carcols_dat"][0]
        normalized = ", ".join(p.strip() for p in normalized.split(","))
        cfg = self.parser.decompose_carcols(normalized)
        self.assertTrue(cfg["is_car4"])
        self.assertEqual(cfg["count"], 8)


class AlphaInstallationInferenceRegression(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="alpha_inference_")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        env = patch.dict(os.environ, {"VMM_DIAGNOSTICS_ROOT": str(root / "diagnostics")})
        env.start()
        self.addCleanup(env.stop)
        self.source = root / "1992 Bravado Alpha"
        actual = os.environ.get("VMM_TEST_ALPHA_SOURCE")
        if actual:
            shutil.copytree(actual, self.source)
            archived = self.source / "alpha_dat.txt.used_source"
            if archived.exists():
                shutil.copyfile(archived, self.source / "alpha_dat.txt")
        else:
            self.source.mkdir()
            (self.source / "alpha_dat.txt").write_text("carcols.dat\n----------------\n" + ALPHA, encoding="utf-8")
            (self.source / "alpha.dff").write_bytes(b"test dff")
            (self.source / "alpha.txd").write_bytes(b"test txd")
        self.game = root / "game"
        data = self.game / "data"
        data.mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"test game")
        (data / "vehicles.ide").write_text("cars\n" + ALPHA_IDE + "\nend\n", encoding="utf-8")
        (data / "carcols.dat").write_text("car\nalpha, 58,1, 69,1\n" + ELEGY + "\nend\ncar4\n" + CAMPER + "\nend\n", encoding="utf-8")
        self.original = (data / "carcols.dat").read_bytes()
        backup = BackupManager(str(root / "backups"), str(self.game))
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup)
        self.merger = ConfigMerger(str(self.shadow), str(self.game), backup)

    def test_source_inspection_and_installation_move_alpha_to_car4(self):
        inspection = self.installer.inspect_source(str(self.source))
        self.assertTrue(inspection["success"], inspection)
        row = inspection["parsed_config"]["carcols_dat"][0]
        self.assertTrue(row.startswith("car4 alpha,"), row)
        vehicle = next(v for v in inspection["target_vehicles"] if v["model"] == "alpha")
        self.assertTrue(vehicle["has_carcols"])
        # Both installation paths must retain the mode: source reinspection
        # and the wizard's already-parsed configuration payload.
        for use_payload in (False, True):
            with self.subTest(use_payload=use_payload):
                params = {"inspect_dir": str(self.source), "target_category": "Modded Cars",
                          "folder_name": "Alpha", "vehicles": [{"source_model": "alpha", "target_model": "alpha",
                          "merge_fla": False, "generate_fxt": False}]}
                if use_payload:
                    params["parsed_config"] = inspection["parsed_config"]
                result = self.installer.execute_install(params)
                self.assertTrue(result["success"], result)
                cfg = self.merger.get_vehicle_active_configs("alpha")["carcols"]
                self.assertEqual(cfg["source"], "shadow")
                self.assertTrue(cfg["decomposed"]["is_car4"])
                self.assertEqual(cfg["decomposed"]["count"], 8)
                expected = self.merger.parser.decompose_carcols("car4 " + ALPHA)
                self.assertEqual(cfg["decomposed"]["color_sets"], expected["color_sets"])
                result = self.merger.save_vehicle_config("alpha", "carcols", cfg["raw"])
                self.assertTrue(result["success"], result)
                section = None
                occurrences = []
                for line in (self.shadow / "carcols.dat").read_text(encoding="utf-8-sig").splitlines():
                    if line.strip() in ("car", "car4", "end"):
                        section = line.strip()
                    elif line.split(",")[0].strip() == "alpha":
                        occurrences.append(section)
                self.assertEqual(occurrences, ["car4"])
        for ext in ("dff", "txd"):
            written = self.shadow / "Alpha" / f"alpha.{ext}"
            self.assertEqual(written.read_bytes(), (self.source / f"alpha.{ext}").read_bytes())
        self.assertEqual((self.game / "data" / "carcols.dat").read_bytes(), self.original)

    def test_existing_car_section_is_not_silently_reinterpreted(self):
        path = self.shadow / "carcols.dat"
        path.write_text("car\n" + ALPHA + "\nend\n", encoding="utf-8")
        before = path.read_bytes()
        cfg = self.merger.get_vehicle_active_configs("alpha")["carcols"]
        self.assertFalse(cfg["decomposed"]["is_car4"])
        self.assertEqual(cfg["decomposed"]["count"], 16)
        self.assertEqual(path.read_bytes(), before)
        saved = self.merger.save_vehicle_config("alpha", "carcols", cfg["raw"])
        self.assertTrue(saved["success"], saved)
        self.assertFalse(self.merger.get_vehicle_active_configs("alpha")["carcols"]["decomposed"]["is_car4"])
        self.assertNotIn("car4", path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
