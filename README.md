# GTASA Vehicle Mod Manager

A vehicle mod manager and installer for **Grand Theft Auto: San Andreas (PC)**.

---

## Key Features

### 🛡️ Strict Vanilla Data Protection (Shadow Baseline)
* **Never touches your clean data/ folder**: All configurations (`handling.cfg`, `carcols.dat`, `carmods.dat`, `shopping.dat`, `veh_mods.ide`, `vehicles.ide`) are deployed as shadow overrides inside modloader folder.
* **One-Click Clean Revert**: Safely uninstalls any vehicle and instantly restores configurations back to original vanilla baselines without leaving corrupted game files.
* **Automatic Snapshots & Rollback**: Creates timestamped backups prior to configuration merges with atomic file write protections.

### 🧠 Dual-Track Readme & Mod Package Parser
* **Multi-Format Archive Extraction**: Automatically unpacks and inspects ZIP, RAR, and 7Z archives (with built-in 7-Zip detection).
* **Section-Anchor Matching (Track 1)**: Recognizes standard configuration headers (`handling.cfg`, `carcols.dat`, `vehicles.ide`, `carmods.dat`, `shopping.dat`, `audio`, etc.).
* **Heuristic Syntax Fingerprinting (Track 2)**: Identifies IDE lines and physics parameters even in badly formatted author Readmes without clear section headers.

### 🚗 Replacement & Addon Vehicle Support
* **Standard Replacement**: Easily preview and install vehicles to replace existing vanilla cars.
* **Addon Vehicle Conversion**: Converts standard replacement car mods into standalone Addon vehicles without replacing original cars.

### 🔧 Full Tuning Kit Management
* Automatically identifies vehicle tuning components (spoilers, hoods, exhausts, nitro, hydraulics, wheels, etc.).
* Registers tuning parts synchronously across `carmods.dat`, `veh_mods.ide`, and `shopping.dat`.

### 🔊 Fastman92 Limit Adjuster (FLA 92) Integration
* **Custom Sounds**: Edit and preview vehicle engine and horn sound profiles in `gtasa_vehicleAudioSettings.cfg`.
* **Model Special Features**: Toggles and configures pop-up headlights, siren lights and various features in `model_special_features.dat`.

### 🆔 Conflict-Free Model ID Pool Inspector
* Scans all `.ide` definitions in `data/` and across `modloader/` (including map mods, weapon mods and vehicle mods).
* Visualizes occupied ID ranges and discovers safe gaps for new addon cars and tuning parts.

---

## Requirements

* **Game**: Grand Theft Auto: San Andreas v1.0 (PC)
  * [CLEO](https://cleo.li/) installed
  * [ModLoader](https://gtaforums.com/topic/669520-mod-loader/) installed
  * (Optional) [Fastman92 Limit Adjuster](https://fastman92.com/) for custom audio and special features
* **Python** (if running from source): Python 3.9 or higher
* **7-Zip**: Installed on your machine for extracting .rar and .7z mod archives.

---

## Quick Start

### 1. Running from Source

1. Clone or download this repository:
   ```bash
   git clone https://github.com/<your-username>/gtasa-vehicle-manager.git
   cd gtasa-vehicle-manager
   ```
2. Launch the application:
   * Double-click `run.bat` (or `start.bat`), or
   * Run in terminal:
     ```bash
     python server.py
     ```
3. To open directly in your default browser:
   ```bash
   python server.py --browser
   ```

### 2. First-Time Setup
* On first launch, the manager will prompt you to select your **GTA San Andreas root directory** (the folder containing `gta_sa.exe`).
* The manager verifies the presence of `modloader/` and prepares clean shadow baselines automatically.

---

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

* Rockstar Games for Grand Theft Auto: San Andreas.
* The GTA SA modding community, including the creators of **ModLoader**, **CLEO**, and **Fastman92 Limit Adjuster**.
