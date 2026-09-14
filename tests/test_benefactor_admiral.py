"""Regression coverage using the Benefactor Admiral pack's original readmes.

Set VMM_TEST_BENEFACTOR_SOURCE to the complete pack directory to exercise its
real DFF/TXD/FXT files too. All installation/editing happens in a temporary game.
The readme samples are embedded below; no external test data is required.
The default suite uses small placeholder model assets.
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
from core.parser import DualTrackParser, normalize_ide_line


# Original configuration samples from the user-provided Benefactor Admiral pack.
READMES = {
    "admiral": """vehicles.ide
445, 	admiral, 	admiral, 	car, 		ADMIRAL, 	ADMIRAL, 	null,	richfamily, 	10,	0,	0,		-1, 0.71, 0.71,		0

handling.cfg
name       mass     turnmass  drag   centreofmass  boy traction                 transmission            brakes       steer  suspension       suslines        antidive   seat col  cost      mflags      hflags      lights
; A          B         C   	D      F   G    H    I   J    K    L    	M N     O    P    Q R   S     T    U V    	a    b     c     d    e     f    g   		aa   ab   ac		af 	ag 			ah ai aj
ADMIRAL     1600.0    2100.0   2.0    0.0 0.0 -0.05 75  0.65 0.75 0.55  	4 175.0 20.0 10.5  R D 	15.0  0.3  0 30.0  	0.7  0.18  0.0   0.14 -0.21 0.5  0.55		0.2  0.56 45000     0            0        0  1    0

carcols.dat
car4
admiral, 96,20,0,0, 114,102,0,0, 68,102,0,0, 123,102,0,0, 0,102,0,0, 1,65,0,0, 53,20,0,0, 99,24,0,0

carmods.dat
admiral, exh_b_s, exh_b_m, exh_b_t, exh_b_ts, nto_b_l, nto_b_s, nto_b_tw

gtasa_vehicleAudioSettings.cfg
admiral                                      0             84     83     0         0.65         1.0          7         1.18921      1           0          8          0           45                 2.0
""",
    "admrl28": """vehicles.ide
ID, 	admrl28, 	admrl28, 	car, 		ADMRL28, 	ADMRL28, 	null,	richfamily, 	7,	0,	0,		-1, 0.71, 0.71,		0

handling.cfg
name       mass     turnmass  drag   centreofmass  boy traction                 transmission            brakes       steer  suspension       suslines        antidive   seat col  cost      mflags      hflags      lights
; A          B         C   	D      F   G    H    I   J    K    L    	M N     O    P    Q R   S     T    U V    	a    b     c     d    e     f    g   		aa   ab   ac		af 	ag 			ah ai aj
ADMRL28     1600.0    2100.0   2.0    0.0 0.0 -0.05 75  0.65 0.75 0.55  	5 205.0 23.0 3.5  R P 	15.0  0.3  0 30.0  	0.7  0.18  0.0   0.14 -0.21 0.5  0.55		0.2  0.56 55000     0            0        0  1    0

carcols.dat
car4
admrl28, 123,102,0,0, 3,102,0,0, 46,102,0,0, 7,20,0,0, 83,65,0,0, 1,20,0,0, 37,107,0,0, 6,102,0,0

carmods.dat
admrl28, exh_b_s, exh_b_m, exh_b_t, exh_b_ts, nto_b_l, nto_b_s, nto_b_tw

gtasa_vehicleAudioSettings.cfg
admrl28                                      0             87     86     0         0.65         1.0          7         1.18921      1           0          8          0           45                 0.0
""",
}
BUFFALO = "402, buffalo, buffalo, car, BUFFALO, BUFFALO, null, richfamily, 5, 0, 0, -1, 0.74, 0.74, 0"


class BenefactorAdmiralRegression(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="benefactor_test_")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        env = patch.dict(os.environ, {"VMM_DIAGNOSTICS_ROOT": str(root / "diagnostics")})
        env.start()
        self.addCleanup(env.stop)
        self.source = root / "source"
        actual_source = os.environ.get("VMM_TEST_BENEFACTOR_SOURCE")
        if actual_source:
            shutil.copytree(actual_source, self.source)
        else:
            for model in ("admiral", "admrl28"):
                folder = self.source / model
                folder.mkdir(parents=True)
                (folder / "readme.txt").write_text(READMES[model], encoding="utf-8")
                (folder / f"{model}.dff").write_bytes(b"test dff")
                (folder / f"{model}.txd").write_bytes(b"test txd")

        self.parser = DualTrackParser()
        self.rows = {}
        for model in ("admiral", "admrl28"):
            parsed = self.parser.parse_text_content(READMES[model])
            self.rows[model] = parsed["vehicles_ide"][0]
        # The author's addon row deliberately leaves its ID as 'ID'.
        self.rows["admrl28"] = "12000," + self.rows["admrl28"].split(",", 1)[1]
        self.game = root / "game"
        data = self.game / "data"
        data.mkdir(parents=True)
        (self.game / "gta_sa.exe").write_bytes(b"test game")
        (data / "vehicles.ide").write_text("cars\n" + self.rows["admiral"] + "\n" + BUFFALO + "\nend\n", encoding="utf-8")
        (data / "carcols.dat").write_text("col\n0,0,0\nend\ncar\nadmiral, 34,34\nbuffalo, 91,32\nend\n", encoding="utf-8")
        self.baseline = {p.name: p.read_bytes() for p in data.iterdir()}
        backup = BackupManager(str(root / "backups"), str(self.game))
        self.shadow = self.game / "modloader" / "Modded Cars"
        self.shadow.mkdir(parents=True)
        self.merger = ConfigMerger(str(self.shadow), str(self.game), backup)
        self.installer = ModInstaller(str(self.game), "Modded Cars", backup)
        self.ide_path = self.shadow / "vehicles.ide"

    def write_blocks(self, duplicate=False):
        first = BUFFALO + "\n" + self.rows["admiral"] + "\n"
        if duplicate:
            first += self.rows["admrl28"] + "\n"
        self.ide_path.write_text("# preserved header\ncars\n" + first + "end\n\ncars\n" + self.rows["admrl28"] + "\nend\n", encoding="utf-8")

    def model_rows(self, model):
        block = 0
        in_cars = False
        rows = []
        for line in self.ide_path.read_text(encoding="utf-8-sig").splitlines():
            clean = normalize_ide_line(line.strip())
            if clean.lower() == "cars":
                block += 1
                in_cars = True
            elif clean.lower() == "end":
                in_cars = False
            elif in_cars:
                parts = [p.strip() for p in clean.split(",")]
                if len(parts) > 1 and parts[1].lower() == model:
                    rows.append((block, parts))
        return rows

    def test_edit_later_block_stays_unique_and_repeat_save_is_identical(self):
        self.write_blocks()
        updated = self.rows["admrl28"].replace("0.71", "0.73")
        for _ in range(2):
            result = self.merger.save_vehicle_config("admrl28", "vehicles_ide", updated)
            self.assertTrue(result["success"], result)
            rows = self.model_rows("admrl28")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], 2)
            self.assertEqual(rows[0][1][12:14], ["0.73", "0.73"])
            content = self.ide_path.read_bytes()
            if _:
                self.assertEqual(content, previous)
            previous = content
        self.assertIn(BUFFALO, self.ide_path.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(self.model_rows("admiral")), 1)

    def test_save_repairs_old_duplicates_only_for_the_edited_model(self):
        self.write_blocks(duplicate=True)
        with self.ide_path.open("a", encoding="utf-8") as f:
            f.write("cars\n" + BUFFALO + "\nend\n")
        result = self.merger.save_vehicle_config("admrl28", "vehicles_ide", self.rows["admrl28"])
        self.assertTrue(result["success"], result)
        self.assertEqual(len(self.model_rows("admrl28")), 1)
        self.assertEqual(len(self.model_rows("buffalo")), 2)

    def test_batch_inserts_new_model_without_copying_later_existing_model(self):
        self.write_blocks()
        new_row = self.rows["admrl28"].replace("12000", "12001").replace("admrl28", "newcar")
        result = self.merger._merge_vehicles_ide([
            {"model": "admrl28", "line": self.rows["admrl28"]},
            {"model": "newcar", "line": new_row},
        ])
        self.assertTrue(result["success"], result)
        self.assertEqual([b for b, _ in self.model_rows("newcar")], [1])
        self.assertEqual([b for b, _ in self.model_rows("admrl28")], [2])

    def test_save_creates_missing_cars_block(self):
        self.ide_path.write_text("# no cars yet\nobjs\nend\n", encoding="utf-8")
        result = self.merger.save_vehicle_config("admrl28", "vehicles_ide", self.rows["admrl28"])
        self.assertTrue(result["success"], result)
        self.assertEqual(len(self.model_rows("admrl28")), 1)
        self.assertIn("objs\nend\n", self.ide_path.read_text(encoding="utf-8-sig"))

    def test_pack_install_and_edit_preserve_all_eight_four_color_schemes(self):
        inspection = self.installer.inspect_source(str(self.source))
        self.assertTrue(inspection["success"], inspection)
        self.assertEqual({v["model"] for v in inspection["target_vehicles"]}, {"admiral", "admrl28"})
        result = self.installer.execute_install({
            "inspect_dir": str(self.source), "target_category": "Modded Cars", "folder_name": "Benefactor",
            "vehicles": [
                {"source_model": model, "target_model": model, "addon_id": 12000,
                 "category": "Addon Cars" if model == "admrl28" else "Modded Cars",
                 "merge_fla": False, "generate_fxt": False}
                for model in ("admiral", "admrl28")
            ],
        })
        self.assertTrue(result["success"], result)
        for model in ("admiral", "admrl28"):
            expected = self.parser.parse_text_content(READMES[model])["carcols_dat"][0]
            cfg = self.merger.get_vehicle_active_configs(model)["carcols"]
            self.assertEqual(cfg["source"], "shadow")
            self.assertTrue(cfg["decomposed"]["is_car4"])
            self.assertEqual(cfg["decomposed"]["count"], 8)
            self.assertEqual(cfg["decomposed"]["color_sets"], self.parser.decompose_carcols(expected)["color_sets"])
            # Edit the last color and verify both the change and every other color.
            edited = cfg["raw"].rsplit(",", 1)[0] + ", 7"
            for _ in range(2):
                saved = self.merger.save_vehicle_config(model, "carcols", edited)
                self.assertTrue(saved["success"], saved)
            active = self.merger.get_vehicle_active_configs(model)["carcols"]["decomposed"]
            self.assertTrue(active["is_car4"])
            self.assertEqual(active["color_sets"], self.parser.decompose_carcols(edited)["color_sets"])
            section = None
            occurrences = []
            for line in (self.shadow / "carcols.dat").read_text(encoding="utf-8-sig").splitlines():
                if line.strip() in ("car", "car4", "end"):
                    section = line.strip()
                elif line.split(",")[0].strip() == model:
                    occurrences.append(section)
            self.assertEqual(occurrences, ["car4"])
            for ext in ("dff", "txd"):
                source_file = next(self.source.rglob(f"{model}.{ext}"))
                written = list((self.game / "modloader").rglob(f"{model}.{ext}"))
                self.assertEqual(len(written), 1)
                self.assertEqual(written[0].read_bytes(), source_file.read_bytes())
        self.assertEqual(len(self.model_rows("admrl28")), 1)
        self.assertEqual(self.model_rows("admrl28")[0][1][0], "12000")
        # Reproduce a historical multi-block file using the installed addon
        # row, then edit it through the same save API used by the inspector.
        lines = self.ide_path.read_text(encoding="utf-8-sig").splitlines()
        addon_line = next(line for line in lines if "admrl28" in line.lower())
        rest = [line for line in lines if line != addon_line]
        self.ide_path.write_text("\n".join(rest) + "\ncars\n" + addon_line + "\nend\n", encoding="utf-8")
        edited_ide = addon_line.replace("0.71", "0.73")
        for _ in range(2):
            saved = self.merger.save_vehicle_config("admrl28", "vehicles_ide", edited_ide)
            self.assertTrue(saved["success"], saved)
        self.assertEqual([b for b, _ in self.model_rows("admrl28")], [2])
        self.assertEqual(self.model_rows("admrl28")[0][1][12:14], ["0.73", "0.73"])
        active_ide = self.merger.get_vehicle_active_configs("admrl28")["vehicles_ide"]
        self.assertEqual(active_ide["source"], "shadow")
        self.assertIn("0.73", active_ide["raw"])
        for filename, original in self.baseline.items():
            self.assertEqual((self.game / "data" / filename).read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
