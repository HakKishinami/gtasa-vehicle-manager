/**
 * GTASA Vehicle Mod Manager — i18n
 *
 * Add a language (e.g. Spanish):
 *   1. Push { id, name, htmlLang, title } into I18N_LANGUAGES.
 *   2. Add es: { "brand.title": "...", ... } to I18N_DICTIONARY.
 *      Missing keys fall back to English, then Chinese — partial packs are fine.
 *   3. Register the same id in core/i18n.py LANGUAGES.
 *
 * Call sites:
 *   t("key")
 *   t("key", "fallback {0}", arg)
 *   t("key", { en: "English {0}" }, arg)
 *   I18N.pick({ zh: "...", en: "..." })
 *   I18N.pick(apiObject, "label")  // label_es / label_en / label_zh / label
 */

window.I18N_LANGUAGES = [
  { id: "en", name: "English", htmlLang: "en", title: "GTASA Vehicle Manager" }
];

window.I18N_DICTIONARY = {
  en: {
    "assets.title": "Mod Files",
    "assets.other": "Other Files",
    "assets.configs": "Configuration",
    "assets.close": "Close",
    "assets.search": "Search filenames or paths",
    "assets.file": "Filename",
    "assets.location": "Path in Package",
    "assets.model": "Vehicle",
    "assets.size": "Size",
    "assets.replacement": "Replaces",
    "assets.addon": "Addon",
    "assets.paintjob": "Paintjob",
    "assets.paintjobNum": "Paintjob {0}",
    "assets.empty": "No matching files",
    "assets.loading": "Reading...",
    "assets.truncated": "Large file: showing the first 512 KB",
    "assets.binary": "This is not a plain text file",
    "assets.unavailable": "Unable to read the file. Retry or inspect the package again.",
    "assets.copy": "Copy Text",
    "assets.retry": "Retry",
    "assets.copied": "Text copied",
    "assets.copyFailed": "Clipboard is unavailable",
    "assets.selectAll": "Select All",
    "assets.deselectAll": "Deselect All",
    "assets.excluded": "Excluded",
    "assets.apply": "Apply & Save",
    "assets.excludedSummary": "{0} files excluded",
    "assets.badgeExcluded": "{0} files excluded",
    "assets.configEditHint": "✏️ Editable configuration lines (Fallback)",
    "assets.emptyConfig": "0 lines (empty)",
    "assets.configEditorPlaceholder": "Edit configuration lines here...",
    "assets.categoryTabsLabel": "File type",
    "assets.linesCountOne": "{0} line",
    "assets.linesCountMany": "{0} lines",
    "assets.modifiedSuffix": " (modified)",
    "brand.title": "Vehicle Mod Manager",
    "brand.version": "Beta",
    "footer.buildStampTitle": "Frontend build version",
    "header.detecting": "Detecting...",
    "header.notConfigured": "No Path Set",
    "header.changeDir": "📁 Change Directory",
    "header.changeDirTitle": "Change GTA:SA Root Directory",
    "header.idPool": "🆔 ID Pool Analyzer",
    "header.idPoolTitle": "Inspect Free Model IDs & Allocation",
    "header.logs": "🩺 Log",
    "header.logsTitle": "Operation log & diagnostics package",
    "header.setDefaultLang": "Set Default",
    "header.setDefaultLangTitle": "Set current language as default on startup",
    "header.setDefaultLangSuccess": "Default startup language set to [{0}]!",
    "header.langSelectorTitle": "Interface language",
    "header.flaReadyPending": "FLA92: Ready (ASI installed, pending launch)",
    "header.flaActive": "FLA92: Active ({0} Specials / {1} Audio)",
    "header.flaMissing": "FLA92: Not Installed",
    "common.requestFailed": "Request failed: ",
    "common.unknownError": "Unknown error",
    "common.saving": "💾 Saving...",
    "common.selectExisting": "📋 Select Existing",
    "common.unknown": "Unknown",
    "common.lines": "lines",
    "common.identical": "Identical",
    "common.notGenerated": "Not Generated",
    "common.noDff": "No DFF",
    "common.lastVehicle": "Last Vehicle ✓",
    "base.statusAligned": "Aligned to Baseline",
    "base.confirmRevert": "Revert shadow file {0} to clean vanilla baseline?\nAn automatic backup will be created before resetting.",
    "inspect.targetCardTitleAddon": "🎯 Target Addon Vehicle (vehicles.ide)",
    "inspect.targetCardTitleReplace": "🎯 Target Replaced Vehicle (vehicles.ide)",
    "inspect.noVehicleSelected": "No vehicle selected",
    "nav.mods": "Installed Vehicles",
    "nav.installer": "Install Vehicle Mod",
    "nav.inspector": "Vehicle Inspector",
    "nav.baseline": "Baseline & Health",
    "nav.readmeLab": "Readme Lab",
    "fla.bannerTitle": "Fastman92 Limit Adjuster (FLA) not detected",
    "fla.bannerDesc": "FLA main file <code>fastman92limitAdjuster.asi</code> was not found; the .ini config only takes effect alongside the main file. The game is running with vanilla limits: standard replacement vehicles work normally; install the full FLA if you need extra tuning parts or custom audio.",
    "fla.statusDismiss": "Dismiss",
    "fla.statusIgnore": "Don't Show Again",
    "fla.statusIgnoreTitle": "Remember this choice and stop showing this notice at startup",
    "sevenzip.bannerTitle": "7-Zip not found",
    "sevenzip.bannerDesc": "ZIP archives still install without 7-Zip. RAR / 7Z require a local 7-Zip install. After installing, click Recheck. Site: <code>https://www.7-zip.org/</code>",
    "sevenzip.btnDownload": "Open 7-Zip website",
    "sevenzip.btnRecheck": "Recheck",
    "sevenzip.btnDismiss": "Dismiss",
    "sevenzip.foundToast": "7-Zip found: {0}",
    "sevenzip.stillMissing": "7-Zip is still not installed. Install it and try again.",
    "sevenzip.missingToast": "7-Zip not found. ZIP still works; install 7-Zip for RAR / 7Z (https://www.7-zip.org/).",
    "sevenzip.openFailed": "Could not open the 7-Zip website",
    "vanilla.bannerTitle": "Vanilla vehicle list could not be loaded",
    "vanilla.bannerDesc": "The vanilla vehicle list is unavailable, so duplicate-name checking is disabled. To avoid creating a new vehicle whose name collides with a vanilla model, addon-mode installs are blocked; replacement installs are unaffected. Click Reload to try again.",
    "vanilla.btnRetry": "Reload",
    "vanilla.reloadOk": "Vanilla vehicle list reloaded",
    "vanilla.reloadFailed": "The vanilla vehicle list still could not be loaded; restart the app and try again",
    "mods.partitionReplace": "Replacement Mods",
    "mods.partitionAddon": "Addon Mods",
    "mods.multiPackBadge": "📦 Multi-Vehicle ({count} Vehicles)",
    "mods.navTotalVehicles": "{vehicles} Vehicles / {folders} Folders",
    "mods.badgeVehiclesAndFolders": "{vehicles} Vehicles ({folders} Folders)",
    "mods.badgeVehicleCount": "{0} vehicles",
    "mods.badgeFolderCount": "({0} folders)",
    "mods.clickOpenFolder": "Click to open this folder",
    "mods.replaceVehiclePrefix": "Replaces ",
    "mods.folderPrefixReplace": "📁 Replacement Folder:",
    "mods.folderPrefixAddon": "📁 Addon Folder:",
    "mods.btnOpenFolder": "Open",
    "mods.btnChangeFolder": "Change Folder",
    "mods.openFolderTitle": "Open this directory in Windows File Explorer",
    "mods.editFolderTitle": "Change mod directory for this partition",
    "mods.modalTitleReplace": "📁 Change Replacement Mods Directory",
    "mods.modalTitleAddon": "📁 Change Addon Mods Directory",
    "mods.modalDesc": "Select or specify the subfolder under modloader\\. The system will automatically rescan vehicle mods upon switching.",
    "mods.modalFolderSelectLabel": "Existing ModLoader Folders:",
    "mods.modalFullTargetPreview": "Target Full Path:",
    "mods.btnToggleCustomFolder": "➕ Custom",
    "mods.btnBrowseFolder": "📁 Browse",
    "mods.customPartitionFolderPlaceholder": "Enter a custom folder name, e.g. MyCars",
    "mods.browsePartitionFolderBtnTitle": "Browse and pick a folder in the system dialog",
    "mods.browsePartitionFolderTitle": "Select ModLoader Vehicle Folder",
    "mods.searchPlaceholder": "Search mod, author, model, or tuning parts...",
    "mods.filterAll": "All",
    "mods.filterHandling": "Handling",
    "mods.filterTuning": "Tuning",
    "mods.filterRisk": "⚠️ Crash Risk",
    "mods.filterSpecial": "FLA Special Features",
    "mods.btnInstallNew": "➕ Install Mod",
    "mods.refreshBtn": "🔄 Refresh",
    "mods.densityToggleTitle": "Card density",
    "mods.densityComfortableTitle": "Comfortable view (larger cards, full info)",
    "mods.densityCompactTitle": "Compact view (smaller cards, path hidden)",
    "mods.loading": "Scanning ModLoader vehicle mods...",
    "mods.emptyTitle": "No matching vehicle mods found",
    "mods.cardAuthor": "Author",
    "mods.cardUnknownAuthor": "Unknown Author",
    "mods.cardOriginal": "Replaces",
    "mods.cardAddon": "Addon Vehicle",
    "mods.cardTuningParts": "parts",
    "mods.cardAudioBadge": "Audio",
    "mods.cardHandlingBadge": "Handling",
    "mods.cardCarcolsBadge": "Colors",
    "mods.cardMoreVehicles": "+{count}",
    "mods.cardLessVehicles": "Less",
    "mods.cardDeleteBtn": "Delete",
    "mods.cardRenameBtn": "Rename",
    "mods.cardRenameTitle": "Rename this mod folder",
    "mods.renameModalTitle": "Rename Mod Folder",
    "mods.renameCurrentLabel": "Current path:",
    "mods.renameInputLabel": "New folder name:",
    "mods.renamePlaceholder": "e.g. BF Club",
    "mods.renameHint": "Only the mod folder itself is renamed. Merged configuration data is untouched and the list refreshes automatically.",
    "mods.renameBtnCancel": "Cancel",
    "mods.renameBtnSave": "💾 Save Name",
    "mods.renameEmptyError": "Folder name cannot be empty",
    "inspect.titleDefault": "Select a mod to inspect",
    "inspect.btnDryRun": "⚡ Dry-Run Test",
    "inspect.btnApplyMerge": "💾 Apply & Merge",
    "inspect.btnRenameMod": "✏️ Rename Folder",
    "inspect.btnRenameModTitle": "Rename this mod folder (merged configs are untouched)",
    "inspect.btnDeleteMod": "🗑️ Delete Mod",
    "inspect.btnDeleteModTitle": "Permanently delete mod folder and revert configurations",
    "inspect.targetCardTitle": "🎯 Target Vehicle",
    "inspect.metaModelCode": "Internal Model",
    "inspect.metaVanillaName": "Vehicle Name",
    "inspect.metaShop": "Tuning Shop",
    "inspect.metaDffSize": "DFF Size",
    "inspect.targetIdBadgeDefault": "ID: --",
    "inspect.targetIdBadgePrefix": "Vanilla ID: ",
    "inspect.targetIdBadgePrefixAddon": "Addon ID: ",
    "inspect.targetUnrecognized": "Unrecognized",
    "inspect.targetNoneShop": "None",
    "inspect.rawToggle": "Raw configuration",
    "inspect.rawToggleFla": "Configuration record",
    "inspect.handlingCardTitle": "🏎️ Handling Parameters",
    "inspect.handlingEmpty": "No custom handling provided. Using vanilla physics.",
    "inspect.handlingVanillaBadge": "Vanilla Physics",
    "inspect.handlingCustomBadge": "Custom Handling",
    "inspect.handlingMaxSpeed": "Top Speed",
    "inspect.handlingMass": "Vehicle Mass",
    "inspect.handlingGears": "Gears",
    "inspect.handlingGearsVal": "{0}-Speed",
    "inspect.handlingAccel": "Acceleration Factor",
    "inspect.handlingBrakeBias": "Brake Bias",
    "inspect.handlingSteering": "Steering Lock Angle",
    "inspect.handlingDriveRwd": "RWD",
    "inspect.handlingDriveFwd": "FWD",
    "inspect.handlingDriveAwd": "AWD",
    "inspect.carcolsCardTitle": "🎨 Colors (Carcols)",
    "inspect.colorCountBadgeDefault": "0 Schemes",
    "inspect.colorCountBadge": "{0} Color Schemes",
    "inspect.colorPairTooltip": "Scheme #{0}: Colors {1}, {2}",
    "inspect.colorQuadTooltip": "4-Color Scheme #{0}: Colors {1}, {2}, {3}, {4}",
    "inspect.carcolsEmpty": "No custom colors provided. Using vanilla palette.",
    "inspect.tuningCardTitle": "🛠️ Tuning Parts & Shop Configuration",
    "inspect.tuningCountBadgeDefault": "0 Parts",
    "inspect.tuningCountBadge": "{0} Parts",
    "inspect.tuningEmpty": "No tuning parts detected for this vehicle.",
    "inspect.tuningDangerTooltip": "Unpriced in shopping.dat — entering a garage may crash; the installer can backfill this",
    "inspect.tuningDangerShort": "Unpriced",
    "inspect.tuningSafe": "In shop (${0})",
    "inspect.clickToEditId": "Click to edit part ID",
    "inspect.unassignedId": "Unassigned",
    "inspect.deletePartTitle": "Completely delete this part from carmods and veh_mods.ide",
    "inspect.modalEditIdTitle": "🆔 Edit Tuning Part Model ID",
    "inspect.modalEditIdPartLabel": "Target Part Name:",
    "inspect.modalEditIdInputLabel": "New Model ID (veh_mods.ide):",
    "inspect.modalEditIdChecking": "Checking ID availability...",
    "inspect.modalEditIdFree": "✔️ ID available; no conflicts found",
    "inspect.modalEditIdConflict": "❌ ID is occupied: ",
    "inspect.modalEditIdBtnSave": "💾 Save ID",
    "inspect.modalEditIdBtnCancel": "Cancel",
    "inspect.deletePartConfirm": "Are you sure you want to completely delete part [{0}] from this vehicle?\n\nThis will remove it from carmods.dat, veh_mods.ide, and unlink mirror parts.",
    "toast.tuningIdUpdated": "Successfully updated part [{0}] ID to {1}!",
    "toast.tuningIdUpdateFailed": "Failed to update part ID: ",
    "toast.tuningPartDeleted": "Successfully deleted tuning part [{0}]!",
    "toast.tuningPartDeleteFailed": "Failed to delete part: ",
    "inspect.flaSpecialTitle": "✨ Special Features (FLA92 & Native)",
    "inspect.flaSpecialNotConfigured": "Not Configured",
    "inspect.flaSpecialConfigured": "Active: {0}",
    "inspect.flaSpecialNative": "Native: {0}",
    "inspect.flaReadingFile": "Reading configuration...",
    "inspect.flaActualLine": "File record:",
    "inspect.flaQuickPresets": "Presets",
    "inspect.presetZr350Title": "ZR-350: pop-up headlights",
    "inspect.presetSandkingTitle": "Sandking: high clearance",
    "inspect.presetCopcarTitle": "Copcar LA: lights and siren",
    "inspect.presetTaxiTitle": "Taxi: roof lamp",
    "inspect.presetHydraTitle": "Hydra: VTOL thrust",
    "inspect.presetFbiTitle": "FBI Rancher: strobe lights",
    "inspect.flaCustomTargetLabel": "Target model",
    "inspect.flaCustomTargetPlaceholder": "zr350 / sandking / copcarla…",
    "inspect.flaCustomTargetHint": "Syncs to <code>data/model_special_features.dat</code> to assign special features.",
    "inspect.btnSaveSpecial": "Save",
    "inspect.btnRemoveSpecial": "Revert",
    "inspect.specialActive": "Active Special Feature: ",
    "inspect.specialNativeActive": "Built-in Special Feature: ",
    "inspect.specialNativeDesc": "Built into the game; no extra entry in model_special_features.dat is needed.",
    "inspect.specialNotActive": "No custom special features; using this model’s built-in behavior.",
    "inspect.specialNoRecord": "(No record in data/model_special_features.dat for this model)",
    "inspect.modalEditIdHint": "IdManager checks this ID live against vehicles, weapons, and map models to prevent conflicts.",
    "inspect.modalEditIdPlaceholder": "e.g. 11735",
    "header.gamePathTitle": "Current game root directory",
    "inspect.flaAudioTitle": "🔊 Audio (FLA92)",
    "inspect.flaAudioVanilla": "Vanilla Audio",
    "inspect.flaAudioCustom": "Custom Audio",
    "inspect.flaAudioQuickPreset": "Audio preset",
    "inspect.flaAudioRawLabel": "Parameter line",
    "inspect.btnResetAudio": "Reset",
    "inspect.audioFieldGuide": "Field guide",
    "inspect.audioPlaceholder": "VehicleName AudioType BankA BankB BassSetting BassFactor Pitch HornType HornPitch DoorSound Upgrade Radio RadioType NameType Gain",
    "inspect.flaAudioHint": "Saves to <code>data/gtasa_vehicleAudioSettings.cfg</code> with automatic snapshot in manager <code>backups/</code>.",
    "inspect.btnSaveAudio": "Save",
    "inspect.btnRemoveAudio": "Revert",
    "inspect.audioActive": "Custom audio configured",
    "inspect.audioActivePreset": "Custom audio ({0})",
    "inspect.audioNotActive": "Using default vehicle audio",
    "inspect.audioNoRecord": "(Not listed in data/gtasa_vehicleAudioSettings.cfg)",
    "inspect.audioPresetPlaceholder": "-- Select a vehicle audio preset --",
    "audio.p1": "1. Model",
    "audio.p2": "2. Audio Type",
    "audio.p3": "3. Bank A",
    "audio.p4": "4. Bank B",
    "audio.p5": "5. Bass Config",
    "audio.p6": "6. Bass Factor",
    "audio.p7": "7. Pitch",
    "audio.p8": "8. Horn Type",
    "audio.p9": "9. Horn Pitch",
    "audio.p10": "10. Door Sound",
    "audio.p11": "11. Upgrade",
    "audio.p12": "12. Radio",
    "audio.p13": "13. Radio Type",
    "audio.p14": "14. Name Type",
    "audio.p15": "15. Gain",
    "inspect.btnEdit": "✏️ Edit",
    "inspect.btnCancelEdit": "✕ Cancel",
    "inspect.btnEditFxt": "🔤 Name",
    "inspect.btnEditFxtTitle": "Edit in-game display name (writes to mod .fxt file)",
    "inspect.fxtEditLabel": "In-game display name (written to the mod .fxt file, auto-loaded by ModLoader):",
    "inspect.btnSaveFxt": "💾 Save Name",
    "inspect.fxtEditKeyHint": "GXT key: ",
    "inspect.fxtEditNoKey": "No FXT entry for this vehicle yet; saving will create one.",
    "inspect.fxtEditEmpty": "Name cannot be empty.",
    "toast.saveFxtSuccess": "Vehicle display name saved!",
    "toast.saveFxtFailed": "Failed to save name: ",
    "inspect.btnSaveConfig": "💾 Save Changes",
    "inspect.guideClickToJump": "Click to jump and select this parameter field",
    "inspect.ideguide1": "1.ID",
    "inspect.ideguide2": "2.Model",
    "inspect.ideguide3": "3.TXD",
    "inspect.ideguide4": "4.Type",
    "inspect.ideguide5": "5.HandlingID",
    "inspect.ideguide6": "6.GameName",
    "inspect.ideguide7": "7.Anim",
    "inspect.ideguide8": "8.Class",
    "inspect.ideguide9": "9.Freq",
    "inspect.ideguide10": "10.Flags",
    "inspect.ideguide11": "11.Comp",
    "inspect.ideguide12": "12.WheelID",
    "inspect.ideguide13": "13.FrontScale",
    "inspect.ideguide14": "14.RearScale",
    "inspect.hguide1": "1.Identifier",
    "inspect.hguide2": "2.Mass(kg)",
    "inspect.hguide3": "3.TurnMass",
    "inspect.hguide4": "4.DragMult",
    "inspect.hguide5": "5.CenterOfMass",
    "inspect.hguide6": "6.Submerged%",
    "inspect.hguide7": "7.Traction",
    "inspect.hguide8": "8.Gears",
    "inspect.hguide9": "9.MaxSpeed",
    "inspect.hguide10": "10.Accel",
    "inspect.hguide11": "11.Drive[FR4]",
    "inspect.hguide12": "12.Engine[PDE]",
    "inspect.hguide13": "13.Brake",
    "inspect.hguide14": "14.SteerAngle",
    "inspect.guideCarOnly": "This guide describes car parameters; this vehicle uses a different physics layout",
    "inspect.secondaryPhysicsTag": "separate physics",
    "inspect.secondaryPhysicsHint": "This vehicle uses the game's own physics layout for motorcycles, boats, aircraft and trailers, so its fields are not the car parameter set. The line is shown as it is; the editor below still saves it straight into handling.cfg.",
    "inspect.diffModified": "Modified",
    "inspect.diffMatchesVanilla": "= Matches Vanilla",
    "inspect.diffMatchesVanillaTooltip": "This parameter is identical to the vanilla game data/ physics",
    "inspect.diffVanillaVal": "Vanilla",
    "inspect.handlingDiffToggle": "Compare with Vanilla Handling",
    "inspect.diffCountBadge": "{0} parameters modified",
    "inspect.diffAllMatchBadge": "Identical to Vanilla",
    "inspect.diffColParam": "Parameter",
    "inspect.diffColVanilla": "Vanilla Baseline",
    "inspect.diffColMod": "Current Values",
    "inspect.diffColDelta": "Difference",
    "inspect.diffGroupDrivetrain": "Power & Drivetrain",
    "inspect.diffGroupControl": "Control & Brakes",
    "inspect.diffGroupSuspension": "Suspension & Mass",
    "inspect.diffGroupMisc": "Other",
    "inspect.diffNeutralTooltip": "Modified (no absolute better/worse for this parameter)",
    "inspect.colorScheme2": "2-color",
    "inspect.colorScheme4": "4-color",
    "inspect.diffLiveEditTitle": "⚡ Live Physics Delta Preview",
    "inspect.paramMass": "Vehicle Mass",
    "inspect.paramTurnMass": "Turn Mass",
    "inspect.paramDragMult": "Drag Multiplier",
    "inspect.paramCenterOfMass": "Center of Mass Offset [X, Y, Z]",
    "inspect.paramSubmerged": "Submerged %",
    "inspect.paramTractionMult": "Traction Multiplier",
    "inspect.paramTractionLoss": "Traction Loss",
    "inspect.paramTractionBias": "Traction Bias",
    "inspect.paramGears": "Transmission Gears",
    "inspect.paramMaxSpeed": "Max Speed",
    "inspect.paramAccel": "Acceleration Factor",
    "inspect.paramInertia": "Engine Inertia",
    "inspect.paramDriveType": "Drive Type",
    "inspect.paramEngineType": "Engine Type",
    "inspect.paramBrakeDecel": "Brake Deceleration",
    "inspect.paramBrakeBias": "Brake Bias",
    "inspect.paramSteering": "Steering Lock Angle",
    "inspect.paramSuspensionForce": "Suspension Force",
    "inspect.paramSuspensionDamping": "Suspension Damping",
    "inspect.paramSuspensionLower": "Suspension Lower Limit",
    "inspect.paramMonetary": "Monetary Value",
    "inspect.carcolsPlaceholder": "Model, color1,color2, color3,color4... e.g.: previon, 14,33, 13,33, 92,33",
    "inspect.carmodsPlaceholder": "Model, part1, part2, part3... e.g.: previon, exh_b_l, exh_b_m, fbmp_a_l",
    "inspect.ideEditLabel": "Edit vehicles.ide definition line:",
    "inspect.handlingEditLabel": "Edit handling.cfg parameters line:",
    "inspect.carcolsEditLabel": "Edit carcols.dat palette line:",
    "inspect.carmodsEditLabel": "Edit carmods.dat parts mount line:",
    "inspect.ideRawLineLabel": "vehicles.ide Entry (resolved):",
    "inspect.handlingRawLineLabel": "handling.cfg Physics Parameters (resolved):",
    "inspect.carcolsRawLineLabel": "carcols.dat Entry (resolved):",
    "inspect.carmodsRawLineLabel": "carmods.dat Entry (resolved):",
    "inspect.ideEditorHint": "Directly saved to ModLoader shadow copy of <code>vehicles.ide</code> with automatic snapshot backup in <code>backups/</code>.",
    "inspect.handlingEditorHint": "Directly saved to ModLoader shadow copy of <code>handling.cfg</code> with automatic snapshot backup in <code>backups/</code>.",
    "inspect.carcolsEditorHint": "Directly saved to ModLoader shadow copy of <code>carcols.dat</code> with automatic snapshot backup in <code>backups/</code>.",
    "inspect.carmodsEditorHint": "Directly saved to ModLoader shadow copy of <code>carmods.dat</code> with auto mirror link pairing.",
    "inspect.sourceShadow": "Modified Configuration Copy",
    "inspect.sourceVanilla": "Vanilla Baseline",
    "inspect.sourceMod": "Mod Preset",
    "toast.configSaved": "{0} configuration saved successfully!",
    "toast.configSaveFailed": "Failed to save {0}: ",
    "inspect.readmePreviewTitle": "📜 Original Documents",
    "inspect.readmeEmpty": "No text content available",
    "sources.fileLabel": "Source file",
    "sources.contentLabel": "Source document content",
    "sources.hint": "Original author text is available here for reference. Archived files are excluded from automatic configuration merging.",
    "sources.archived": "Archived · read only",
    "sources.active": "Original file · read only",
    "sources.empty": "No source documents found for this mod.",
    "sources.selectMod": "Select a mod to view its original documents.",
    "sources.loading": "Loading source document…",
    "sources.failed": "This document could not be read. Select it again to retry.",
    "sources.truncated": "Preview shows the first 512 KB. The complete original file is preserved in the mod folder.",
    "sources.encoding": "Encoding: {0}",
    "diag.headerTitle": "Operation Log",
    "diag.headerDesc": "Every install and merge this manager performed, including the ones that failed",
    "diag.intro": "Hit \"Create diagnostics package\" and the manager writes one zip next to the application, inside diagnostics\\exports. It already contains this operation log, the archived-source manifests and your settings, so that single file is everything needed to work out what happened. Absolute game paths are included; skim the contents before posting them publicly.",
    "diag.btnExport": "📦 Create diagnostics package",
    "diag.btnOpenFolder": "📂 Open diagnostics folder",
    "diag.btnRefresh": "🔄 Refresh",
    "diag.btnClose": "Close",
    "diag.recentTitle": "🧾 Recent operations",
    "diag.empty": "No operations recorded yet. Install or merge something, then refresh this list.",
    "diag.exporting": "Writing the diagnostics package…",
    "diag.exported": "Package ready: {0}",
    "diag.exportedToast": "Diagnostics package created",
    "diag.loadFailed": "Could not read the operation log",
    "diag.statusOk": "OK",
    "diag.statusFailed": "Failed",
    "diag.operationInstall": "Install",
    "diag.operationMerge": "Apply merge",
    "diag.operationOther": "Operation",
    "diag.noTarget": "(no target recorded)",
    "foreign.cardTitle": "🧯 Competing Config Copies",
    "foreign.badgeChecking": "Checking...",
    "foreign.badgeCount": "{0} disabled",
    "foreign.badgeNone": "None",
    "foreign.cardHint": "ModLoader loads only one copy of each of these config files, so a second copy makes this manager's edits unreliable. Copies the manager did not create are renamed with .vmm-disabled; nothing is deleted.",
    "foreign.none": "No competing copies found: every config file under modloader belongs to this manager.",
    "foreign.stateDisabledNow": "just disabled",
    "foreign.stateDisabled": "disabled earlier",
    "foreign.btnOpenFolder": "📂 Open folder",
    "foreign.openFailed": "Could not open that folder",
    "foreign.chkDontRemind": "Don't show this again",
    "foreign.btnGotIt": "Got it",
    "foreign.modalTitle": "Other copies of the vehicle config files were disabled",
    "foreign.modalDesc": "ModLoader picks one winner per file, so these copies competed with the data this manager deploys",
    "foreign.modalIntro": "Each file was only renamed with .vmm-disabled so ModLoader stops loading it. Merge anything you still need into the manager's own copies, then delete the disabled files.",
    "foreign.loadFailed": "Could not check for competing config copies",
    "inspect.noReadmeFound": "(No Readme or txt documentation found)",
    "base.title": "🛡️ ModLoader Baseline Health & Shadow Copies",
    "base.btnSyncAll": "📥 Sync Missing Copies",
    "base.folderLabel": "📁 Shadow Data Folder:",
    "base.btnToggleCustom": "➕ Custom",
    "base.btnApplyFolder": "Apply Folder",
    "base.currentAbsPath": "Active Path:",
    "base.zeroDestruction": "<strong>Zero-Risk Guarantee:</strong> Vanilla <code>data/</code> is strictly read-only; all operations modify shadow copies only.",
    "base.inputCustomFolderPlaceholder": "Enter folder name...",
    "base.thFile": "Config File",
    "base.thVanilla": "Vanilla data/ Status",
    "base.thShadow": "ModLoader Shadow Copy",
    "base.thLineCount": "Line Comparison",
    "base.thHealth": "Health Status",
    "base.thAction": "Actions",
    "base.statusOk": "OK",
    "base.statusMissing": "Missing",
    "base.statusModified": "Modified",
    "base.statusUnknown": "Unknown",
    "base.actionSync": "Sync Copy",
    "base.actionSynced": "Aligned",
    "base.nativeMissing": "Vanilla Missing",
    "lab.title": "📝 Readme Parser & Testbench",
    "lab.btnTestParse": "🔍 Parse Text",
    "lab.dropText": "Drop Readme files here (.txt / .readme / .log)",
    "lab.browseLink": "browse files",
    "lab.textPlaceholder": "Drop files here or paste text manually...",
    "lab.resultTitle": "Extracted Configurations:",
    "lab.emptyHint": "Drop a readme or click 'Parse Text' to preview extracted configurations",
    "lab.fxtTitle": "🔤 FXT / GXT Names",
    "lab.handlingTitle": "🏎️ handling.cfg (Physics & Handling)",
    "lab.ideTitle": "🏷️ vehicles.ide (Vehicle Definitions)",
    "lab.carcolsTitle": "🎨 carcols.dat (Color Palettes)",
    "lab.carmodsTitle": "🛠️ carmods.dat (Tuning Mods)",
    "lab.audioTitle": "🔊 vehicleAudioSettings (Audio)",
    "lab.specialTitle": "✨ model_special_features (Special Features)",
    "lab.linesCount": "{0} lines",
    "lab.noDataFound": "No GTA:SA configuration lines recognized.",
    "lab.extractedSummary": "Extracted <strong>{0}</strong> valid configuration entries.",
    "install.headerTitle": "📦 Install Vehicle Mod",
    "install.headerBadge": "ZIP / RAR / 7Z archive or mod folder",
    "install.step1Drop": "Drag & drop mod archive or folder here",
    "install.btnBrowseArchive": "📦 Browse Archive...",
    "install.btnBrowseFolder": "📂 Browse Folder...",
    "install.browseArchiveDialogTitle": "Select Vehicle Mod Archive or Files",
    "install.browseFolderDialogTitle": "Select Vehicle Mod Folder",
    "install.orManual": "or enter path:",
    "install.manualPlaceholder": "e.g. D:\\Downloads\\MyMod.zip",
    "install.btnAnalyze": "Scan Mod",
    "install.loadingSpinner": "Scanning mod archive and analyzing assets...",
    "install.step2Title": "Review the options, then install.",
    "install.cardTargetModel": "Target vehicle",
    "install.vehicleSearchPlaceholder": "Search vehicles...",
    "install.vehicleTypeFilterTitle": "Filter by vehicle class",
    "install.typeAll": "All classes",
    "install.vehiclePickerEmpty": "No vehicles match the current search or class filter.",
    "install.targetModelDesc": "Vehicle to replace:",
    "install.modelRenameHint": "Replacement target changed. Models and textures will be renamed to match.",
    "install.modeReplace": "🔁 Replace",
    "install.modeAddon": "➕ Add New",
    "install.newModelLabel": "New model name (DFF file name)",
    "install.newModelPlaceholder": "e.g. previon2",
    "install.newTxdLabel": "Texture name (TXD file name)",
    "install.newTxdPlaceholder": "Defaults to the model name",
    "install.newNameHint": "DFF/TXD files are renamed automatically and registered as a new ID with handling/carcols/carmods/FLA data; the original car is left untouched.",
    "install.newNameEmpty": "Please enter a new model name",
    "install.newNameCharset": "Model/texture names allow 2-20 lowercase letters, digits or underscores",
    "install.newNameTaken": "That name is already used by a vanilla or in-package vehicle",
    "install.newNameDuplicate": "Multiple vehicles in this install share the same model name",
    "install.newNameListUnavailable": "The vanilla vehicle list has not loaded, so duplicate names cannot be checked; use Reload in the banner above",
    "install.optionAddonTag": " [Addon]",
    "install.optionAddonTypedTag": " [{0} · Addon]",
    "install.addonReplaceHint": "📦 Addon package installed as a replacement: DFF/TXD are renamed to {1}; the package's handling, colors, tuning parts, FLA audio and IDE behavior data (wheel scale, class etc.) replace {0}'s vanilla data, while the target keeps its own ID and model identity. The GXT key below defaults to the target's vanilla key and the in-game name keeps the package's — edit either to customize.",
    "install.addonReplaceConfirm": "Install this addon package as a replacement?\n\nIts model files will be renamed to the selected vanilla vehicle, and its handling, colors, tuning parts and FLA audio will replace that vehicle's vanilla data.\n\nContinue?",
    "install.classMismatchError": "⚠️ Class mismatch: this package is a {0}, but {1} is a {2}. Physics and animation schemas differ between classes — pick a vanilla {0} target instead.",
    "install.newNameInvalidToast": "Fix the new model/texture name first (2-20 lowercase letters, digits or underscores, unique)",
    "install.newHandlingLabel": "Internal handling ID (handling.cfg first column / vehicles.ide Handling column)",
    "install.newHandlingPlaceholder": "Derived from the model name, e.g. PREVION2",
    "install.newHandlingCharset": "Handling ID allows 2-14 letters, digits or underscores",
    "install.newGxtKeyCharset": "GXT key allows 2-7 uppercase letters, digits or underscores",
    "install.cardPathTitle": "Install path",
    "install.categoryLabel": "ModLoader folder",
    "install.authorLabel": "Author subfolder (optional)",
    "install.authorPlaceholder": "Leave blank to install at the folder root",
    "install.authorHint": "Optional author grouping, e.g. Modded Cars/Mad Driver/infernus.",
    "install.subfolderLabel": "Mod folder",
    "install.subfolderPlaceholder": "e.g. Infernus_2024",
    "install.livePathPreview": "Install path",
    "install.pathVehicleListToggle": "Per-vehicle paths",
    "install.cardFxtTitle": "In-game name",
    "install.fxtKeyLabel": "GXT key",
    "install.fxtNameLabel": "In-game name",
    "install.fxtHint": "ModLoader loads the matching .fxt file as the in-game name.",
    "install.cardComponentsTitle": "Pack contents",
    "install.cardVariantTitle": "Versions",
    "install.variantHint": "Same-named files exist in more than one version. Pick one per group. Tuning parts should match the vehicle version.",
    "install.variantStandard": "Standard",
    "install.variantQuickPick": "All",
    "install.variantQuickIvf": "Select all IVF",
    "install.variantQuickNoIvf": "Select all noIVF",
    "install.variantGroupCount": "{0} version groups",
    "install.variantWarnings": "Same-name multi-version files detected, auto-selected one (details):",
    "install.variantKindVehicle": "🚗 Vehicle",
    "install.variantKindTuning": "🛠️ Tuning",
    "install.perCarFolderLabel": "This vehicle folder",
    "install.perCarFolderPlaceholder": "Empty = shared mod folder",
    "install.perCarFolderOwn": "separate",
    "install.perCarFolderShared": "shared",
    "install.perCarFolderPlaceholderDyn": "Empty = shared: {0}",
    "install.separateFoldersBtn": "Separate folders",
    "install.separateFoldersTitle": "Give every car with a blank folder its own folder named after the car",
    "install.separateFoldersDone": "Assigned separate folders to {0} vehicle(s)",
    "install.phaseReplace": "① Replace",
    "install.phaseAddon": "② Addon",
    "install.groupReplace": "Replace vehicles",
    "install.groupAddon": "Addon vehicles",
    "install.nextPhaseBtn": "Next: addon vehicles ➡️",
    "install.backPhaseBtn": "⬅️ Back to replace",
    "install.addonNameConflict": "These models collide with vanilla names and will install as replace (rename for true addon):",
    "install.addonIdTitle": "🆔 Addon vehicle ID assignment:",
    "install.addonIdLabel": "Addon vehicle ID",
    "install.addonIdAutoBtn": "Pick a free ID",
    "install.addonIdFree": "🟢 ID {0} is free",
    "install.addonIdTaken": "🔴 ID {0} occupied ({1})",
    "install.addonIdSelf": "🟢 ID {0} already belongs to this vehicle",
    "install.addonIdInvalid": "⚠️ Enter an ID between 612–65535",
    "install.addonIdConflict": "Addon vehicle {0}: ID {1} unusable: {2}",
    "install.addonIdOverKillable": "⛔ ID {0} exceeds the FLA killable limit {1}; kills may not register or the game may crash. Lower it or raise the ini",
    "install.addonIdOverKillableConfirm": "These addon vehicle IDs exceed the FLA killable limit {0}; destroyed vehicles may not register kills or crash the game (raise Count of killable model IDs in the ini and retry):\n{1}\nInstall anyway?",
    "install.cardChecklistTitle": "Will write",
    "install.checklistNone": "Nothing selected",
    "install.chkDeploy": "Models & textures",
    "install.chkHandling": "handling.cfg",
    "install.chkCarcols": "carcols.dat",
    "install.chkCarmods": "carmods.dat",
    "install.chkShopping": "shopping.dat crash guard",
    "install.chkFxt": "In-game name (.fxt)",
    "install.chkFla": "FLA features & audio",
    "install.cardTuningTitle": "Tuning part IDs",
    "install.btnViewIdPool": "Free ID pool",
    "install.btnAutoResetIds": "Auto-assign",
    "install.tuningConflict": "⚠️ <strong>ID Conflict Detected!</strong> Original IDs conflict with installed mods. Reassigned to free IDs automatically.",
    "install.thPartModel": "Part Model",
    "install.thPartCategory": "Category",
    "install.thAssignedId": "Assigned ID (Editable)",
    "install.thConflictCheck": "Status & Safety",
    "install.tuningTip": "💡 Addon tuning parts are automatically registered in ModLoader's <code>veh_mods.ide</code>.",
    "install.tuningSafeText": "All tuning parts verified conflict-free",
    "install.btnCancel": "Cancel",
    "install.btnConfirm": "Install",
    "install.btnConfirmMulti": "Install {0} vehicles",
    "install.btnPrevCar": "Previous",
    "install.btnNextCar": "Next",
    "install.wizardPackBadge": "🚗 Multi-Vehicle Mod Pack",
    "install.wizardNotice": "Multiple vehicles detected in this pack. Review and customize each vehicle step-by-step:",
    "install.wizardProgress": "Vehicle {0} of {1}",
    "install.currentlyConfiguring": "Configuring:",
    "install.skipCurrentCar": "Skip this vehicle",
    "install.skipShort": "Skip",
    "install.alternativeHint": "This package ships the same car in multiple install modes: [{0}] and [{1}] are the same vehicle. [{0}] is skipped by default; uncheck \"Skip this vehicle\" to install it instead.",
    "install.assetModels": "models",
    "install.assetTextures": "textures",
    "install.assetTuning": "parts",
    "install.assetReadme": "docs",
    "inspect.switcherLabel": "🚘 Inspect Vehicle:",
    "inspect.switchCarSuccess": "Switched to live configs for [{0}]",
    "install.installingBtn": "🚀 Installing mod...",
    "install.step3Title": "🎉 Vehicle Mod Installed!",
    "install.btnOpenFolder": "📁 Open Folder",
    "install.btnGoToMods": "🚗 View Mod",
    "install.btnInstallAnother": "📦 Install Another",
    "install.primaryCar": "🚗 Main Vehicle Assets:",
    "install.tuningParts": "🛠️ Tuning Parts:",
    "install.readmeDocs": "📄 Readme / Docs:",
    "install.extractedConfigs": "⚙️ Extracted Configs:",
    "install.included": "✅ Included",
    "install.none": "❌ None",
    "install.notDetected": "Not detected",
    "install.filesCount": "{0} files",
    "install.partsCount": "{0} parts",
    "install.deployedTo": "Successfully deployed to:",
    "install.resultMultiPack": "🚗 Multi-vehicle pack ({0} vehicles):",
    "install.deployedFilesList": "📦 Deployed Files ({0}):",
    "install.updatedConfigsList": "📝 Updated Configurations ({0}):",
    "install.mergeWarnings": "Warnings:",
    "install.statusConflict": "⚠️ Conflict: ID In Use",
    "install.statusSuggested": "🟡 Mod Default (Free)",
    "install.statusRegistered": "Keep ID",
    "install.statusFree": "🟢 Free & Safe",
    "install.statusInvalid": "❌ Invalid ID",
    "install.statusExcluded": "Skipped",
    "install.chkPartTooltip": "Include this tuning part in installation",
    "install.partsCountRatio": "{0} / {1} parts",
    "install.tuningAllExcluded": "All tuning parts excluded from installation",
    "install.tuningSomeExcluded": "{0} part(s) excluded from installation",
    "install.autoAssigning": "⚡ Assigning IDs...",
    "install.reassignSuccess": "Assigned safe free IDs for {0} tuning parts!",
    "modal.dryRunTitle": "⚡ Dry-Run Merge Preview",
    "modal.btnCancel": "Cancel",
    "confirm.appTitle": "GTASA Vehicle MOD Manager",
    "confirm.btnContinue": "Continue",
    "common.cancel": "Cancel",
    "common.saveAndApply": "Confirm & Apply",
    "modal.btnApply": "Apply to Shadow Baseline",
    "dryrun.loading": "Simulating merge operations...",
    "dryrun.summary": "<strong>Dry-run Complete:</strong> Detected <strong>{0}</strong> changes. Vanilla <code>data/</code> remains 100% untouched.",
    "dryrun.actionsCount": "{0} changes",
    "path.modalTitle": "📁 Select GTA: San Andreas Root Directory",
    "path.changePathTitle": "📁 Change GTA: San Andreas Root Directory",
    "path.modalDesc": "Please select the game directory containing <code>gta_sa.exe</code> and <code>data/</code>:",
    "path.changePathDesc": "Please select the game directory containing <code>gta_sa.exe</code> and <code>data/</code>:",
    "path.firstRunTitle": "👋 Welcome to GTASA Vehicle Manager!",
    "path.firstRunDesc": "Please select your GTA San Andreas root directory (containing <code>gta_sa.exe</code> and <code>data/</code>):",
    "path.inputPlaceholder": "Click 'Browse...' or enter game path manually",
    "path.btnBrowse": "📂 Browse...",
    "path.browseGameFolderTitle": "Select GTA: San Andreas Game Root Directory",
    "path.subfolderDesc": "ModLoader folder for shadow data copies (default: Modded Cars):",
    "path.subfolderPlaceholder": "e.g. Modded Cars or Addon Cars",
    "path.rememberTitle": "Save this directory for next time",
    "path.rememberDesc": "When checked, saves to config.json. If unchecked, only used for current session and prompts on next startup.",
    "path.btnSave": "Confirm & Launch",
    "path.saveCurrentBtn": "Apply Path",
    "path.validating": "Validating path...",
    "path.configuredSuccess": "Game directory set: {0} {1}",
    "path.rememberedNotice": "(Saved as default)",
    "path.notRememberedNotice": "(Will prompt on next launch)",
    "idpool.headerTitle": "GTA:SA Model ID Analyzer & Free Gaps",
    "idpool.headerDesc": "Scans vanilla data and all ModLoader .ide files to identify free gaps and prevent crash conflicts.",
    "idpool.kpiOccupied": "Occupied IDs",
    "idpool.kpiBreakdown": "Vanilla: {0} | Addons: {1}",
    "idpool.kpiFree": "Free IDs (1000 - 20000)",
    "idpool.kpiFreeSub": "Free across all vanilla and mod files",
    "idpool.kpiNextTuning": "⭐ Recommended Tuning Start",
    "idpool.kpiMaxVehMod": "Highest Veh Mod ID: {0}",
    "idpool.kpiFla": "Fastman92 (FLA) ID Limits",
    "idpool.flaEnabled": "🟢 ID Limit Patch Active",
    "idpool.flaKillableSub": "Model limit: {0}",
    "idpool.flaDisabled": "⚪ FLA Not Detected",
    "idpool.flaVanillaSub": "Vanilla game limits active",
    "idpool.gapsTitle": "🎯 Free ID Blocks",
    "idpool.gapsHint": "Click any block to probe its starting ID below",
    "idpool.gapCardTooltip": "Click to probe ID {0}",
    "idpool.freeCountBadge": "{0} Free",
    "idpool.probeTitle": "🔎 Live ID Conflict Probe",
    "idpool.probePlaceholder": "Enter model ID (e.g. 411, 11748, 12055)",
    "idpool.probeBtn": "Probe ID",
    "idpool.probeInvalid": "⚠️ Please enter a valid positive integer ID!",
    "idpool.probing": "Probing ID...",
    "idpool.probeFreeTitle": "🟢 ID {0} is FREE and available!",
    "idpool.probeFreeDesc": "Not used in vanilla data or any installed mod. Safe for tuning parts or new vehicles.",
    "idpool.probeOccupiedTitle": "🔴 ID {0} is OCCUPIED!",
    "idpool.modelNameLabel": "Model:",
    "idpool.originFileLabel": "Source File:",
    "idpool.sectionLabel": "Section:",
    "idpool.searchTitle": "📋 Occupied IDs Directory",
    "idpool.searchPlaceholder": "Filter by name, type, or ID...",
    "idpool.filterAll": "All Models",
    "idpool.filterAddon": "Mod Addons",
    "idpool.filterOverride": "Mod Replaced",
    "idpool.filterVanilla": "Vanilla Built-in",
    "idpool.filterTuning": "Tuning Parts",
    "idpool.filterCars": "All Vehicles",
    "idpool.filterCar": "Cars",
    "idpool.filterBike": "Bikes",
    "idpool.filterPlane": "Aircraft",
    "idpool.filterBoat": "Boats",
    "idpool.filterTrailer": "Trailers",
    "idpool.thId": "ID",
    "idpool.thModel": "Model Name",
    "idpool.thSection": "Section",
    "idpool.thNature": "Type",
    "idpool.thFile": "Source IDE File",
    "idpool.btnClose": "Close",
    "idpool.searching": "Searching IDs...",
    "idpool.noResults": "No matching model records found.",
    "idpool.searchFailed": "Search failed: {0}",
    "idpool.inGap": "(Inside free block <strong>{0} - {1}</strong> with {2} contiguous free IDs)",
    "idpool.recommendedBadge": "⭐ Recommended Tuning Start",
    "idpool.tagAddon": "Mod Addon",
    "idpool.tagOverride": "Mod Replaced",
    "idpool.tagVanilla": "Vanilla Built-in",
    "veh.car": "🚗 Car",
    "veh.bike": "🏍️ Bike",
    "veh.bmx": "🚲 Bicycle",
    "veh.quad": "🏎️ Quad",
    "veh.heli": "🚁 Helicopter",
    "veh.plane": "✈️ Airplane",
    "veh.boat": "🛥️ Boat",
    "veh.trailer": "🚛 Trailer",
    "veh.train": "🚆 Train",
    "veh.tuning": "🔧 Tuning",
    "veh.object": "Object",
    "veh.modAddon": "Mod Addon",
    "veh.modOverride": "Mod Replaced",
    "veh.vanilla": "Vanilla",
    "toast.networkError": "Network error: ",
    "toast.deleteSuccess": "Mod deleted successfully!",
    "toast.deleteFailed": "Failed to delete mod: ",
    "toast.deleteError": "Exception occurred while deleting: ",
    "toast.confirmDeleteMod": "Are you sure you want to delete this mod?\nThis will clean up related configuration entries.",
    "toast.selectModFirst": "Please select a vehicle from the list first",
    "toast.saveSpecialSuccess": "Special feature saved successfully!",
    "toast.saveSpecialFailed": "Failed to save special feature: ",
    "toast.removeSpecialSuccess": "Special feature removed successfully!",
    "toast.confirmRemoveSpecial": "Are you sure you want to revert to vanilla special features?",
    "toast.saveAudioSuccess": "Audio parameters saved with .bak backup!",
    "toast.saveAudioFailed": "Failed to save audio settings: ",
    "toast.removeAudioSuccess": "Custom audio removed, reverted to vanilla!",
    "toast.confirmRemoveAudio": "Are you sure you want to remove custom audio from data file?",
    "toast.audioTooFewParams": "⚠️ Audio parameters has fewer than 8 columns, which may cause game crash. Save anyway?",
    "toast.audioEmptyError": "Audio line cannot be empty! Click 'Revert to Vanilla' if you wish to reset.",
    "toast.applyMergeSuccess": "Merged successfully! Updated files: ",
    "toast.applyMergeFailed": "Failed to apply merge",
    "toast.confirmMerge": "Are you sure you want to apply and merge configs to ModLoader shadow copies?\nTarget vehicle: ",
    "toast.pathSuccess": "Game directory saved successfully!",
    "toast.pathInvalid": "Invalid path. Ensure gta_sa.exe and data/ exist.",
    "toast.syncBaselineSuccess": "Successfully synchronized all missing shadow copies!",
    "toast.fileLoadedParsing": "Loaded {0}, parsing automatically...",
    "toast.dragDetected": "Detected dragged file {0}. Please use Select Archive/Folder button to locate.",
    "toast.inputSubfolderName": "Please enter a dedicated mod folder name",
    "toast.installSuccess": "Vehicle mod installed successfully!",
    "toast.installFailed": "Installation failed: ",
    "toast.precheckFailed": "Mod pre-check failed",
    "toast.fetchDetailFailed": "Failed to load mod details",
    "lab.orText": "or",
    "status.detecting": "Detecting...",
    "status.detectingFla": "FLA 92: Detecting...",
    "install.zeroFiles": "0 files",
    "install.zeroParts": "0 parts",
    "idpool.headerTitle": "GTA:SA Model ID Pool & Free Range Inspector",
    "idpool.headerDesc": "Scans vanilla <code>data/</code> and all <code>modloader/</code> configs to pinpoint conflict-free ID blocks",
    "idpool.kpiOccupied": "Total Occupied IDs",
    "idpool.breakdownInitial": "Vanilla: -- | Mod Addon: --",
    "idpool.kpiBreakdown": "Vanilla: {0} | Addons: {1}",
    "idpool.kpiFree": "Common Free IDs (1000-20000)",
    "idpool.kpiFreeSub": "Completely free of vanilla or mod conflicts",
    "idpool.kpiFreeSafeSub": "Safe (<{0}): {1} · Total: {2}",
    "idpool.gapOverKillable": "⚠️ Over killable cap",
    "idpool.gapOverKillableTitle": "This free block exceeds the FLA killable model-ID ceiling; destroyed vehicles may misbehave",
    "idpool.kpiNextTuning": "⭐ Recommended Tuning Start ID",
    "idpool.maxModInitial": "Highest Part ID: --",
    "idpool.kpiMaxVehMod": "Highest Part ID: {0}",
    "idpool.kpiNextAddon": "🚗 Addon Vehicle Start ID",
    "idpool.maxAddonInitial": "Highest Addon Car ID: --",
    "idpool.kpiMaxAddonVeh": "Highest Addon Car ID: {0}",
    "idpool.kpiConflict": "Model ID Conflict Check",
    "idpool.conflictInitial": "Scanning all mods",
    "idpool.conflictNone": "🟢 0 Conflicts (Clean)",
    "idpool.conflictFound": "⚠️ {0} Conflicts Detected!",
    "idpool.conflictNoneSub": "All mod IDs operate without collision",
    "idpool.conflictFoundSub": "Click to view conflicting mod details",
    "idpool.gapFilterAll": "All Ranges",
    "idpool.gapFilterTuning": "🔧 Tuning Prime",
    "idpool.gapFilterAddon": "🚗 Addon Car Prime",
    "idpool.gapFilterLarge": "📦 Large Blocks (≥100 Free)",
    "idpool.btnCopyId": "📋 Copy ID",
    "idpool.idCopied": "Copied ID {0} to clipboard!",
    "idpool.kpiFla": "Fastman92 (FLA) ID Patch",
    "idpool.flaEnabled": "🟢 ID limit patch active",
    "idpool.flaSubInitial": "Killable Limit: --",
    "idpool.flaKillableSub": "Killable models limit: {0}",
    "idpool.flaDisabled": "⚪ FLA not detected",
    "idpool.flaVanillaSub": "Using vanilla limit",
    "idpool.gapsTitle": "🎯 Prominent Free ID Gaps",
    "idpool.gapsHint": "Click any gap card to probe its starting ID below",
    "idpool.gapCardTooltip": "Click to probe starting ID {0}",
    "idpool.freeCountBadge": "{0} free",
    "idpool.gapCat_tuning": "🔧 Tuning",
    "idpool.gapCat_addon": "🚗 Addon",
    "idpool.gapCat_reserve": "📦 Reserve",
    "idpool.gapCat_fla": "⚡ FLA",
    "idpool.gapCat_general": "Free",
    "idpool.gapStartHint": "Start {0} · click to probe →",
    "idpool.probeTitle": "🔎 Live ID Conflict Prober",
    "idpool.probePlaceholder": "Enter model ID (e.g. 411, 11748, 12501)",
    "idpool.probeBtn": "🔍 Probe ID",
    "idpool.probeInvalid": "⚠️ Please enter a valid non-negative integer ID!",
    "idpool.probing": "Probing ID status...",
    "idpool.probeFreeTitle": "🟢 ID {0} is Completely Free!",
    "idpool.probeFreeDesc": "This ID is unoccupied in vanilla data and all mod configs. Safe for addon vehicles or tuning parts.",
    "idpool.probeOccupiedTitle": "🔴 ID {0} is Occupied!",
    "idpool.modelNameLabel": "Model:",
    "idpool.originFileLabel": "File:",
    "idpool.sectionLabel": "Section:",
    "idpool.searchTitle": "📋 Occupied ID Search & Verification Table",
    "idpool.searchPlaceholder": "Search model name, vehicle type or ID...",
    "idpool.filterAll": "All Occupied Models",
    "idpool.filterAddon": "Mod Addon Only",
    "idpool.filterOverride": "Mod Replaced Only",
    "idpool.filterVanilla": "Vanilla Only",
    "idpool.filterTuning": "Tuning Parts Only",
    "idpool.filterCars": "All Vehicles",
    "idpool.filterCar": "Cars Only",
    "idpool.filterBike": "Bikes Only",
    "idpool.filterPlane": "Aircraft Only",
    "idpool.filterBoat": "Boats Only",
    "idpool.filterTrailer": "Trailers Only",
    "idpool.thId": "ID",
    "idpool.thModel": "Model Name",
    "idpool.thSection": "Section",
    "idpool.thNature": "Nature",
    "idpool.thFile": "Source File",
    "idpool.btnClose": "Close"
  }
};

(function initI18n(global) {
  const DEFAULT_LANG = "en";
  const FALLBACK_LANG = "en";

  const catalog = {};
  (global.I18N_LANGUAGES || []).forEach(meta => {
    if (meta && meta.id) catalog[meta.id] = meta;
  });
  const dictionaries = global.I18N_DICTIONARY || {};
  const extraListeners = [];
  let initialized = false;
  let saveQueue = Promise.resolve();

  function isLangMap(obj) {
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
    return Object.keys(catalog).some(id => Object.prototype.hasOwnProperty.call(obj, id));
  }

  function interpolate(str, args) {
    if (str == null) return "";
    const text = String(str);
    if (!args || !args.length) return text;
    if (args.length === 1 && args[0] && typeof args[0] === "object" && !Array.isArray(args[0]) && !isLangMap(args[0])) {
      return text.replace(/\{(\w+)\}/g, (m, k) => (args[0][k] != null ? String(args[0][k]) : m));
    }
    return text.replace(/\{(\d+)\}/g, (m, i) => (args[i] != null ? String(args[i]) : m));
  }

  function lookup(key, lang) {
    const order = [lang, FALLBACK_LANG, DEFAULT_LANG];
    const seen = {};
    for (let i = 0; i < order.length; i++) {
      const id = order[i];
      if (!id || seen[id]) continue;
      seen[id] = true;
      const dict = dictionaries[id];
      if (dict && dict[key] != null && dict[key] !== "") return dict[key];
    }
    return undefined;
  }

  function resolve(lang, defaultId) {
    if (!lang) return defaultId || DEFAULT_LANG;
    const raw = String(lang).trim().toLowerCase().replace(/_/g, "-");
    if (catalog[raw]) return raw;
    const base = raw.split("-")[0];
    if (catalog[base]) return base;
    return defaultId || DEFAULT_LANG;
  }

  function pick(source, field) {
    if (source == null) return "";
    if (typeof source === "string") return source;
    const lang = I18N.current;
    if (field) {
      const named = [
        source[field + "_" + lang],
        source[lang],
        source[field],
        source[field + "_" + FALLBACK_LANG],
        source[FALLBACK_LANG],
        source[field + "_" + DEFAULT_LANG],
        source[DEFAULT_LANG]
      ];
      for (let i = 0; i < named.length; i++) {
        if (named[i]) return String(named[i]);
      }
      return "";
    }
    if (source[lang]) return String(source[lang]);
    if (source[FALLBACK_LANG]) return String(source[FALLBACK_LANG]);
    if (source[DEFAULT_LANG]) return String(source[DEFAULT_LANG]);
    return "";
  }

  function t(key, fallback, ...args) {
    let vars = args;
    let inline = null;
    if (fallback && typeof fallback === "object" && !Array.isArray(fallback)) {
      if (isLangMap(fallback)) {
        inline = fallback;
      } else {
        vars = [fallback, ...args];
        fallback = "";
      }
    }
    let text = lookup(key, I18N.current);
    if (text == null && inline) text = pick(inline);
    if (text == null) text = (typeof fallback === "string" ? fallback : "") || key;
    return interpolate(text, vars);
  }

  function applyDom(root) {
    const scope = root || document;
    const applyText = (el, attr, set) => {
      try {
        const k = el.getAttribute(attr);
        if (k) set(t(k, ""));
      } catch (e) {}
    };
    scope.querySelectorAll("[data-i18n]").forEach(el => {
      applyText(el, "data-i18n", v => { if (v) el.textContent = v; });
    });
    scope.querySelectorAll("[data-i18n-html]").forEach(el => {
      applyText(el, "data-i18n-html", v => { if (v) el.innerHTML = v; });
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
      applyText(el, "data-i18n-placeholder", v => { if (v) el.placeholder = v; });
    });
    scope.querySelectorAll("[data-i18n-title]").forEach(el => {
      applyText(el, "data-i18n-title", v => { if (v) el.title = v; });
    });
    scope.querySelectorAll("[data-i18n-aria-label]").forEach(el => {
      applyText(el, "data-i18n-aria-label", v => { if (v) el.setAttribute("aria-label", v); });
    });
  }

  function fillSelect(selectEl) {
    if (!selectEl) return;
    const current = I18N.current;
    selectEl.innerHTML = "";
    I18N.list().forEach(meta => {
      const opt = document.createElement("option");
      opt.value = meta.id;
      opt.textContent = meta.name;
      selectEl.appendChild(opt);
    });
    selectEl.value = current;
  }

  function register(meta, dict) {
    if (!meta || !meta.id) return;
    catalog[meta.id] = {
      id: meta.id,
      name: meta.name || meta.id,
      htmlLang: meta.htmlLang || meta.id,
      title: meta.title || document.title
    };
    if (dict) dictionaries[meta.id] = Object.assign({}, dictionaries[meta.id] || {}, dict);
    fillSelect(document.getElementById("selectAppLanguage"));
  }

  const I18N = {
    DEFAULT: DEFAULT_LANG,
    FALLBACK: FALLBACK_LANG,
    get current() { return global.currentLang; },
    list() { return Object.keys(catalog).map(id => catalog[id]); },
    meta(id) { return catalog[resolve(id)] || catalog[DEFAULT_LANG]; },
    resolve,
    register,
    t,
    pick,
    apply: applyDom,
    fillSelect,
    onChange(fn) { if (typeof fn === "function" && !extraListeners.includes(fn)) extraListeners.push(fn); },
    initialize(status) {
      if (initialized) return;
      initialized = true;
      // The backend owns session/startup language. Browser storage can belong
      // to a different run (the desktop app uses a dynamically allocated port).
      I18N.applyLanguage(status.language || status.default_language || DEFAULT_LANG);
    },
    applyLanguage(lang) {
      const resolved = resolve(lang, I18N.current || DEFAULT_LANG);
      global.currentLang = resolved;
      const meta = catalog[resolved] || {};
      document.documentElement.lang = meta.htmlLang || resolved;
      if (meta.title) document.title = meta.title;

      const sel = document.getElementById("selectAppLanguage");
      if (sel) {
        if (!sel.options.length) fillSelect(sel);
        else if (sel.value !== resolved) sel.value = resolved;
      }

      applyDom(document);

      const listeners = new Set(extraListeners);
      if (typeof global.onLanguageChanged === "function") listeners.add(global.onLanguageChanged);
      listeners.forEach(fn => {
        try { fn(resolved); } catch (e) { console.error(e); }
      });
    },
    setLanguage(lang, persistAsDefault) {
      // A user choice made while /api/status is pending wins over that response.
      initialized = true;
      const resolved = resolve(lang, I18N.current || DEFAULT_LANG);
      if (resolved !== I18N.current) I18N.applyLanguage(resolved);
      const meta = catalog[resolved] || {};
      const payload = persistAsDefault
        ? { language: resolved, set_default: true, default_language: resolved }
        : { language: resolved, set_default: false };
      // Preserve choice order even when the user switches quickly.
      saveQueue = saveQueue.then(async () => {
        try {
          const res = await fetch("/api/config/language", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          });
          if (persistAsDefault) {
            const data = await res.json();
            if (data.success && typeof showToast === "function") {
              showToast(t("header.setDefaultLangSuccess", "Default startup language set to [{0}]!", meta.name || resolved));
            }
          }
        } catch (e) {
          if (persistAsDefault) console.error("Failed to persist language setting", e);
        }
      });
      return saveQueue;
    }
  };

  global.I18N = I18N;
  global.t = t;
  global.setLanguage = function (lang, persistAsDefault) {
    return I18N.setLanguage(lang, persistAsDefault);
  };

  global.currentLang = DEFAULT_LANG;

  document.addEventListener("DOMContentLoaded", () => {
    const sel = document.getElementById("selectAppLanguage");
    fillSelect(sel);
    if (sel) {
      sel.addEventListener("change", (e) => {
        I18N.setLanguage(e.target.value, false);
      });
    }
    const btnDef = document.getElementById("btnSetDefaultLang");
    if (btnDef) {
      btnDef.addEventListener("click", () => {
        I18N.setLanguage(I18N.current, true);
      });
    }
    const langIcon = document.querySelector(".lang-selector-wrap span[title]");
    if (langIcon) langIcon.title = t("header.langSelectorTitle", "Language");
    // Render the initial shell without saving or firing application callbacks.
    // loadSystemStatus initializes the language once the backend responds.
    applyDom(document);
  });
})(window);
