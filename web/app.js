/**
 * GTASA Vehicle Mod Manager - Web Frontend Logic
 */

let allMods = [];
let activeMod = null;
let appStatus = null;
let activeModPartition = "replace";
let inspectRequestSeq = 0;

function isSamePath(p1, p2) {
  if (!p1 || !p2) return false;
  const n1 = String(p1).replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  const n2 = String(p2).replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  return n1 === n2;
}

function loc(map) {
  if (window.I18N && typeof window.I18N.pick === "function") return window.I18N.pick(map);
  return (map && (map[window.currentLang] || map.en || map.zh)) || "";
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupFiltersAndSearch();
  setupDensityToggle();
  setupModals();
  setupDataFolderControls();
  setupPartitionFolderControls();
  setupFlaControls();
  setupLanguageControls();
  loadSystemStatus();
  loadMods();
  setupLab();
  setupInstaller();
  setupIdPool();
  setupDiagnostics();
  setupForeignConfigs();
  runForeignConfigGuard();
  setupCardEditors();
  setupFxtNameEditor();
  setupTuningPartControls();
  setupRenameModControls();
  setupDataCopiesModule();
});

// ---------------- Language & Internationalization ----------------

// Called from i18n.js setLanguage after static [data-i18n] nodes are updated.
window.onLanguageChanged = function(lang) {
  if (window.InstallAssets && typeof window.InstallAssets.refreshLanguage === "function") {
    window.InstallAssets.refreshLanguage();
  }
  if (appStatus) {
    renderHeaderStatus(appStatus);
    if (appStatus.baseline) renderBaselineTable(appStatus.baseline);
    if (appStatus.sound_presets && typeof populateSoundPresets === "function") {
      populateSoundPresets(appStatus.sound_presets);
    }
  }
  if (typeof updatePartitionFolderBar === "function") updatePartitionFolderBar();
  if (typeof updateModCountBadges === "function") updateModCountBadges();
  if (typeof applyFilter === "function") applyFilter();
  else if (allMods) renderModGrid(allMods);
  if (activeMod) {
    inspectMod(activeMod);
  } else if (typeof resetInspectorView === "function") {
    resetInspectorView();
  }
  if (typeof currentFlaDetail !== "undefined" && currentFlaDetail && typeof renderFlaDetail === "function") {
    renderFlaDetail(currentFlaDetail);
  } else if (typeof resetFlaDisplay === "function") {
    resetFlaDisplay();
  }
  const installStep2 = document.getElementById("installStep2");
  if (installStep2 && installStep2.style.display !== "none") {
    refreshInstallerLanguage();
  }
  const idModal = document.getElementById("idPoolModal");
  if (idModal && idModal.classList.contains("active")) {
    loadIdStats();
    const searchInput = document.getElementById("inputIdSearch");
    const filterSelect = document.getElementById("selectIdFilterType");
    doSearchIds(searchInput ? searchInput.value : "", filterSelect ? filterSelect.value : "all");
  }
};

function setupLanguageControls() {
  const select = document.getElementById("selectAppLanguage");
  if (select) select.value = window.currentLang || "en";
}


// ---------------- Navigation Tabs ----------------

function setupTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(btn => {
    btn.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) targetPanel.classList.add("active");

      if (targetId === "inspectorTab") {
        if (!activeMod) {
          resetInspectorView();
        } else if (Array.isArray(allMods) && allMods.length > 0) {
          const stillExists = allMods.some(m => isSamePath(m.full_path, activeMod.full_path));
          if (!stillExists) {
            discardInspectorContext(false);
          }
        }
      } else if (targetId === "dataCopiesTab") {
        loadDataCopiesView();
      }
    });
  });
}

function switchTab(tabId) {
  const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  if (btn) btn.click();
}

// ---------------- Toast Notifications ----------------

function showToast(message, type = "info") {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = `toast show ${type}`;
  setTimeout(() => {
    toast.className = "toast";
  }, 3500);
}

// ---------------- System Status & Baseline ----------------

let _hasPromptedPathOnStartup = false;

async function loadSystemStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.success) {
      appStatus = data;

      if (window.I18N) window.I18N.initialize(data);

      renderHeaderStatus(data);
      renderBaselineTable(data.baseline);
      updateDataFolderUI(data);
      populateSoundPresets(data.sound_presets);
      populateSpecialFeatureTargets(data.special_targets);
      checkFlaStatusBanner(data);
      checkSevenZipBanner(data);
      checkStartupPathPrompt(data);
      applyCardDensity(data.card_density);
    }
  } catch (err) {
    console.error("Failed to load system status:", err);
  }
}

function checkStartupPathPrompt(data) {
  if (_hasPromptedPathOnStartup) return;
  if (data && data.should_prompt_path) {
    _hasPromptedPathOnStartup = true;
    // Auto-display modal for directory selection on startup
    openPathModal(true);
  }
}

function checkFlaStatusBanner(data) {
  const banner = document.getElementById("flaWarningBanner");
  if (!banner) return;

  const fla = (data && data.fla) || {};
  const isInstalled = Boolean(fla.installed);
  const isDismissed = Boolean(data && data.dismiss_fla_warning) || Boolean(window._flaSessionDismissed);

  if (!isInstalled && !isDismissed) {
    banner.style.display = "flex";
  } else {
    banner.style.display = "none";
  }
}

function checkSevenZipBanner(data) {
  const banner = document.getElementById("sevenZipWarningBanner");
  if (!banner) return;
  const info = (data && data.seven_zip) || {};
  const found = Boolean(info.found);
  if (found) {
    window._sevenZipSessionDismissed = false;
    banner.style.display = "none";
    return;
  }
  if (window._sevenZipSessionDismissed) {
    banner.style.display = "none";
    return;
  }
  banner.style.display = "flex";
}

async function openSevenZipDownload() {
  const url = (appStatus && appStatus.seven_zip && appStatus.seven_zip.download_url) || "https://www.7-zip.org/";
  try {
    await fetch("/api/open-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    });
  } catch (err) {
    showToast(window.t("sevenzip.openFailed", "Could not open the 7-Zip website"), "error");
  }
}

async function recheckSevenZip() {
  try {
    const res = await fetch("/api/seven-zip");
    const data = await res.json();
    if (appStatus) appStatus.seven_zip = data;
    checkSevenZipBanner({ seven_zip: data });
    if (data && data.found) {
      showToast(window.t("sevenzip.foundToast", "7-Zip found: {0}").replace("{0}", data.path || ""), "success");
    } else {
      showToast(window.t("sevenzip.stillMissing", "7-Zip is still not installed. Install it and try again."), "warning");
    }
  } catch (err) {
    showToast(window.t("sevenzip.stillMissing", "7-Zip is still not installed. Install it and try again."), "error");
  }
}

function openPathModal(isStartup = false) {
  const pathModal = document.getElementById("pathModal");
  const inputGamePath = document.getElementById("inputCustomGamePath");
  const modalFolderInput = document.getElementById("inputModalDataFolder");
  const chkRemember = document.getElementById("chkRememberDefaultPath");
  const title = document.getElementById("pathModalTitle");
  const desc = document.getElementById("pathModalDesc");
  const saveBtn = document.getElementById("saveGamePathBtn");
  const cancelBtn = document.getElementById("cancelPathModal");
  const pathAlert = document.getElementById("pathValidationAlert");

  if (!pathModal) return;
  if (isStartup) {
    if (title) title.textContent = window.t("path.firstRunTitle", "👋 Welcome to GTASA Vehicle Manager!");
    if (desc) desc.innerHTML = window.t("path.firstRunDesc", "Please select your GTA San Andreas root directory (containing <code>gta_sa.exe</code> and <code>data/</code>):");
    if (saveBtn) saveBtn.textContent = window.t("path.btnSave", "Confirm & Launch");
    if (cancelBtn) cancelBtn.style.display = (appStatus && appStatus.is_valid_game_path) ? "inline-block" : "none";
  } else {
    if (title) title.textContent = window.t("path.changePathTitle", "📁 Change GTA: San Andreas Root Directory");
    if (desc) desc.innerHTML = window.t("path.changePathDesc", "Please select the game directory containing <code>gta_sa.exe</code> and <code>data/</code>:");
    if (saveBtn) saveBtn.textContent = window.t("path.saveCurrentBtn", "Apply Path");
    if (cancelBtn) cancelBtn.style.display = "inline-block";
  }

  if (inputGamePath) {
    if (isStartup) {
      // User requested: selection input field starts completely empty
      inputGamePath.value = "";
    } else if (appStatus && appStatus.game_path) {
      inputGamePath.value = appStatus.game_path;
    } else {
      inputGamePath.value = "";
    }
  }

  if (modalFolderInput) {
    modalFolderInput.value = (appStatus && appStatus.data_folder) ? appStatus.data_folder : "Modded Cars";
  }

  if (chkRemember) {
    chkRemember.checked = Boolean(appStatus && appStatus.remember_default_path);
  }

  if (pathAlert) {
    pathAlert.style.display = "none";
    pathAlert.textContent = "";
  }

  pathModal.classList.add("active");
}

function updateDataFolderUI(data) {
  const select = document.getElementById("selectModloaderFolder");
  const pathDisplay = document.getElementById("currentShadowDirDisplay");
  const badge = document.getElementById("displayActiveFolderBadge");
  const modalFolderInput = document.getElementById("inputModalDataFolder");

  if (pathDisplay) pathDisplay.textContent = data.shadow_dir || "--";
  if (badge) badge.textContent = `modloader\\${data.data_folder || 'Modded Cars'}\\`;
  if (modalFolderInput) modalFolderInput.value = data.data_folder || "Modded Cars";

  if (select && data.modloader_folders) {
    select.innerHTML = "";
    data.modloader_folders.forEach(f => {
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      if (f === data.data_folder) opt.selected = true;
      select.appendChild(opt);
    });
  }
}

function setupDataFolderControls() {
  const toggleBtn = document.getElementById("btnToggleCustomFolder");
  const select = document.getElementById("selectModloaderFolder");
  const input = document.getElementById("inputCustomFolder");
  const applyBtn = document.getElementById("btnApplyDataFolder");

  if (toggleBtn && select && input) {
    toggleBtn.addEventListener("click", () => {
      const isInputHidden = (input.style.display === "none");
      if (isInputHidden) {
        input.style.display = "inline-block";
        select.style.display = "none";
        input.value = select.value || "";
        input.focus();
        toggleBtn.textContent = t("common.selectExisting");
      } else {
        input.style.display = "none";
        select.style.display = "inline-block";
        toggleBtn.textContent = t("mods.btnToggleCustomFolder");
      }
    });
  }

  if (applyBtn) {
    applyBtn.addEventListener("click", async () => {
      let targetFolder = "";
      if (input && input.style.display !== "none") {
        targetFolder = input.value.trim();
      } else if (select) {
        targetFolder = select.value.trim();
      }

      if (!targetFolder) {
        showToast(loc({ en: "Target folder name cannot be empty" }), "warning");
        return;
      }

      applyBtn.disabled = true;
      applyBtn.textContent = loc({ en: "Switching..." });

      try {
        const res = await fetch("/api/set-data-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ folder: targetFolder })
        });
        const data = await res.json();
        if (data.success) {
          showToast(loc({ en: `Switched shadow data folder to: modloader\\${data.data_folder}` }), "success");
          if (input) input.style.display = "none";
          if (select) select.style.display = "inline-block";
          if (toggleBtn) toggleBtn.textContent = t("mods.btnToggleCustomFolder");
          discardInspectorContext();
          await loadSystemStatus();
          await loadMods();
          // A different game or shadow folder changes which config copies count
          // as this manager's own.
          foreignConfigsNotified = false;
          await runForeignConfigGuard();
        } else {
          showToast((loc({ en: "Switch failed: " })) + data.error, "error");
        }
      } catch (err) {
        showToast((t("common.requestFailed")) + err.message, "error");
      } finally {
        applyBtn.disabled = false;
        applyBtn.textContent = loc({ en: "Apply Folder" });
      }
    });
  }
}

// ---------------- Partition Folder Directory Controls ----------------

function updatePartitionFolderBar() {
  const labelEl = document.getElementById("partitionFolderLabel");
  const pathEl = document.getElementById("partitionFolderPathText");
  if (!labelEl || !pathEl) return;

  const isAddon = (activeModPartition === "addon");

  // Label prefix
  labelEl.textContent = isAddon
    ? window.t("mods.folderPrefixAddon", "📁 Addon Folder:")
    : window.t("mods.folderPrefixReplace", "📁 Replacement Folder:");

  // Subfolder name
  const folderName = isAddon
    ? (appStatus && appStatus.addon_folder ? appStatus.addon_folder : "Addon Cars")
    : (appStatus && appStatus.data_folder ? appStatus.data_folder : "Modded Cars");

  // Full path
  let fullPath = "";
  if (isAddon) {
    fullPath = (appStatus && appStatus.addon_folder_full)
      ? appStatus.addon_folder_full
      : (appStatus && appStatus.game_path ? (appStatus.game_path + "\\modloader\\" + folderName) : ("modloader\\" + folderName));
  } else {
    fullPath = (appStatus && appStatus.replace_folder_full)
      ? appStatus.replace_folder_full
      : (appStatus && appStatus.game_path ? (appStatus.game_path + "\\modloader\\" + folderName) : ("modloader\\" + folderName));
  }

  pathEl.textContent = `modloader\\${folderName}`;
  pathEl.title = `${fullPath}\n(${window.t("mods.clickOpenFolder", "Click to open this folder")})`;
}

async function openCurrentPartitionFolder() {
  const isAddon = (activeModPartition === "addon");
  const folderName = isAddon
    ? (appStatus && appStatus.addon_folder ? appStatus.addon_folder : "Addon Cars")
    : (appStatus && appStatus.data_folder ? appStatus.data_folder : "Modded Cars");

  let targetPath = isAddon ? (appStatus && appStatus.addon_folder_full) : (appStatus && appStatus.replace_folder_full);
  if (!targetPath && appStatus && appStatus.game_path) {
    targetPath = `${appStatus.game_path}\\modloader\\${folderName}`;
  }

  if (!targetPath) {
    showToast(loc({ en: "No valid mod directory path detected" }), "warning");
    return;
  }

  try {
    const res = await fetch("/api/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: targetPath })
    });
    const data = await res.json();
    if (data.success) {
      showToast(loc({ en: `Opened in File Explorer: modloader\\${folderName}` }), "success");
    } else {
      showToast((loc({ en: "Failed to open folder: " })) + (data.error || ""), "error");
    }
  } catch (err) {
    showToast((loc({ en: "Request failed: " })) + err.message, "error");
  }
}

async function openPartitionFolderModal() {
  const modal = document.getElementById("partitionFolderModal");
  if (!modal) return;
  const isAddon = (activeModPartition === "addon");

  const titleEl = document.getElementById("partitionModalTitle");
  if (titleEl) {
    titleEl.textContent = isAddon
      ? window.t("mods.modalTitleAddon", "📁 Change Addon Mods Directory")
      : window.t("mods.modalTitleReplace", "📁 Change Replacement Mods Directory");
  }

  const select = document.getElementById("selectPartitionFolder");
  const input = document.getElementById("inputCustomPartitionFolder");
  const toggleBtn = document.getElementById("btnToggleCustomPartitionFolder");
  const previewPathEl = document.getElementById("partitionModalTargetFullPath");

  // Reset custom toggle
  if (input) {
    input.style.display = "none";
    input.value = "";
  }
  if (select) select.style.display = "inline-block";
  if (toggleBtn) toggleBtn.textContent = window.t("mods.btnToggleCustomFolder", "➕ Custom");

  const currentFolder = isAddon
    ? (appStatus && appStatus.addon_folder ? appStatus.addon_folder : "Addon Cars")
    : (appStatus && appStatus.data_folder ? appStatus.data_folder : "Modded Cars");

  function updatePreview() {
    let chosen = "";
    if (input && input.style.display !== "none") {
      chosen = input.value.trim();
    } else if (select) {
      chosen = select.value.trim();
    }
    const base = (appStatus && appStatus.game_path) ? `${appStatus.game_path}\\modloader\\` : "modloader\\";
    if (previewPathEl) {
      previewPathEl.textContent = chosen ? `${base}${chosen}` : `${base}--`;
    }
  }

  // Fetch modloader folders list
  try {
    const res = await fetch("/api/modloader-folders");
    const data = await res.json();
    if (data.success && select) {
      select.innerHTML = "";
      const folders = data.folders || [];
      if (!folders.includes(currentFolder)) {
        folders.unshift(currentFolder);
      }
      folders.forEach(f => {
        const opt = document.createElement("option");
        opt.value = f;
        opt.textContent = f;
        if (f === currentFolder) opt.selected = true;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.error("Failed to load modloader folders:", err);
  }

  updatePreview();

  if (select) {
    select.onchange = updatePreview;
  }
  if (input) {
    input.oninput = updatePreview;
  }

  modal.classList.add("active");
}

function setupPartitionFolderControls() {
  const openBtn = document.getElementById("btnOpenCurrentFolder");
  const changeBtn = document.getElementById("btnChangeCurrentFolder");
  const pathBadge = document.getElementById("partitionFolderPathText");

  if (openBtn) openBtn.addEventListener("click", openCurrentPartitionFolder);
  if (pathBadge) pathBadge.addEventListener("click", openCurrentPartitionFolder);
  if (changeBtn) changeBtn.addEventListener("click", openPartitionFolderModal);

  const modal = document.getElementById("partitionFolderModal");
  const closeBtn = document.getElementById("closePartitionFolderModal");
  const cancelBtn = document.getElementById("cancelPartitionFolderModal");
  const saveBtn = document.getElementById("savePartitionFolderModal");
  const toggleBtn = document.getElementById("btnToggleCustomPartitionFolder");
  const browseBtn = document.getElementById("btnBrowsePartitionFolder");
  const select = document.getElementById("selectPartitionFolder");
  const input = document.getElementById("inputCustomPartitionFolder");
  const previewPathEl = document.getElementById("partitionModalTargetFullPath");

  if (closeBtn) closeBtn.addEventListener("click", () => modal && modal.classList.remove("active"));
  if (cancelBtn) cancelBtn.addEventListener("click", () => modal && modal.classList.remove("active"));

  if (toggleBtn && select && input) {
    toggleBtn.addEventListener("click", () => {
      const isInputHidden = (input.style.display === "none");
      if (isInputHidden) {
        input.style.display = "inline-block";
        select.style.display = "none";
        input.value = select.value || "";
        input.focus();
        toggleBtn.textContent = t("common.selectExisting");
      } else {
        input.style.display = "none";
        select.style.display = "inline-block";
        toggleBtn.textContent = window.t("mods.btnToggleCustomFolder", "➕ Custom");
      }
      const base = (appStatus && appStatus.game_path) ? `${appStatus.game_path}\\modloader\\` : "modloader\\";
      const chosen = (input.style.display !== "none") ? input.value.trim() : select.value.trim();
      if (previewPathEl) previewPathEl.textContent = chosen ? `${base}${chosen}` : `${base}--`;
    });
  }

  if (browseBtn) {
    browseBtn.addEventListener("click", async () => {
      const initial = (appStatus && appStatus.game_path) ? `${appStatus.game_path}\\modloader` : "";
      try {
        const title = (window.t ? window.t("mods.browsePartitionFolderTitle", "Select ModLoader Vehicle Folder") : "Select ModLoader Vehicle Folder");
        const res = await fetch("/api/browse-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            initial,
            title,
            lang: window.currentLang || "en"
          })
        });
        const data = await res.json();
        if (data.success && data.path) {
          const picked = data.path;
          let folderName = picked;
          const modloaderDir = (appStatus && appStatus.game_path) ? `${appStatus.game_path}\\modloader`.toLowerCase() : "";
          if (modloaderDir && picked.toLowerCase().startsWith(modloaderDir)) {
            const rel = picked.substring(modloaderDir.length).replace(/^[\\\/]+/, "");
            folderName = rel.split(/[\\\/]/)[0] || picked;
          } else {
            folderName = picked.split(/[\\\/]/).filter(Boolean).pop() || picked;
          }

          if (input && select) {
            input.style.display = "inline-block";
            select.style.display = "none";
            input.value = folderName;
            if (toggleBtn) {
              toggleBtn.textContent = t("common.selectExisting");
            }
          }
          const base = (appStatus && appStatus.game_path) ? `${appStatus.game_path}\\modloader\\` : "modloader\\";
          if (previewPathEl) previewPathEl.textContent = folderName ? `${base}${folderName}` : `${base}--`;
        }
      } catch (err) {
        console.error("Browse folder failed:", err);
      }
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      let folderName = "";
      if (input && input.style.display !== "none") {
        folderName = input.value.trim();
      } else if (select) {
        folderName = select.value.trim();
      }

      if (!folderName) {
        showToast(loc({ en: "Folder name cannot be empty" }), "warning");
        return;
      }

      const partitionType = activeModPartition; // "replace" or "addon"
      saveBtn.disabled = true;
      saveBtn.textContent = loc({ en: "Saving..." });

      try {
        const res = await fetch("/api/set-mod-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: partitionType,
            folder: folderName
          })
        });
        const data = await res.json();
        if (data.success) {
          if (appStatus) {
            appStatus.data_folder = data.data_folder;
            appStatus.addon_folder = data.addon_folder;
            appStatus.replace_folder_full = data.replace_folder_full;
            appStatus.addon_folder_full = data.addon_folder_full;
            if (data.modloader_folders) appStatus.modloader_folders = data.modloader_folders;
          }

          if (modal) modal.classList.remove("active");

          updatePartitionFolderBar();
          discardInspectorContext();

          // Refresh mods list and counts
          if (data.mods) {
            allMods = data.mods;
            if (typeof updateModCountBadges === "function") updateModCountBadges(data);
            applyFilter();
          } else {
            await loadMods();
          }

          const typeName = (partitionType === "addon")
            ? (loc({ en: "Addon Mods" }))
            : (loc({ en: "Replacement Mods" }));
          showToast(loc({ en: `Switched [${typeName}] directory to: modloader\\${folderName}` }), "success");

          // Sync baseline status in background
          loadSystemStatus();
        } else {
          showToast((loc({ en: "Failed to switch folder: " })) + (data.error || ""), "error");
        }
      } catch (err) {
        showToast((loc({ en: "Request failed: " })) + err.message, "error");
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = window.t("common.saveAndApply", "Confirm & Apply");
      }
    });
  }
}

function renderHeaderStatus(data) {
  if (!data) return;
  const gamePathText = document.getElementById("gamePathText");
  const flaStatusText = document.getElementById("flaStatusText");

  gamePathText.textContent = data.game_path || t("header.notConfigured");
  const fla = data.fla || {};
  if (fla.installed) {
    if (fla.is_pending_launch) {
      flaStatusText.textContent = t("header.flaReadyPending");
    } else {
      flaStatusText.textContent = t("header.flaActive", "FLA92: Active ({0} Specials / {1} Audio)", fla.special_count, fla.audio_count);
    }
  } else {
    flaStatusText.textContent = t("header.flaMissing");
  }

  updatePartitionFolderBar();
}

function renderBaselineTable(baseline) {
  const tbody = document.getElementById("baselineTableBody");
  tbody.innerHTML = "";

  if (!baseline || !baseline.files) return;

  for (const [fname, f] of Object.entries(baseline.files)) {
    const tr = document.createElement("tr");

    const statusBadge = f.shadow_exists
      ? (f.modified ? `<span class="badge badge-warning">${t("base.statusModified")}</span>` : `<span class="badge badge-success">${t("base.statusAligned")}</span>`)
      : `<span class="badge badge-warning">${t("base.statusMissing")}</span>`;

    const lineWord = t("common.lines");
    const diff = f.shadow_lines - f.vanilla_lines;
    const diffText = (f.shadow_lines === f.vanilla_lines)
      ? t("common.identical")
      : (diff > 0 ? `+${diff} ${lineWord}` : `${diff} ${lineWord}`);

    tr.innerHTML = `
      <td><strong>${fname}</strong></td>
      <td>${f.vanilla_exists ? `${f.vanilla_lines} ${lineWord} (${(f.vanilla_size/1024).toFixed(1)} KB)` : `<span class="badge">${t("base.nativeMissing")}</span>`}</td>
      <td>${f.shadow_exists ? `${f.shadow_lines} ${lineWord} (${(f.shadow_size/1024).toFixed(1)} KB)` : `<span class="badge badge-warning">${t("common.notGenerated")}</span>`}</td>
      <td>${diffText}</td>
      <td>${statusBadge}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="revertBaselineFile('${fname}')">${loc({ en: "Revert" })}</button>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

async function revertBaselineFile(filename) {
  if (!confirm(t("base.confirmRevert", "Revert shadow file {0} to vanilla baseline?", filename))) return;
  try {
    const res = await fetch("/api/revert-baseline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message);
      loadSystemStatus();
    } else {
      showToast((loc({ en: "Revert failed: " })) + data.error, "error");
    }
  } catch (err) {
    showToast(loc({ en: "Request failed" }), "error");
  }
}

document.getElementById("btnSyncAllBaseline").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/sync-baseline", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(loc({ en: `Synchronized ${data.copied.length} missing baseline shadow copies` }));
      loadSystemStatus();
    }
  } catch (err) {
    showToast(loc({ en: "Sync failed" }), "error");
  }
});

// ---------------- Data Copies & Config Studio ----------------

let dataCopiesFolders = [];
let dataCopiesCurrentFolder = "";
let dataCopiesCurrentFile = "";
let dataCopiesCurrentContent = "";
let dataCopiesIsDirty = false;
let dataCopiesIsReadOnly = false;
let dataCopiesFindMatches = [];
let dataCopiesFindIndex = -1;

function setupDataCopiesModule() {
  const folderSelect = document.getElementById("dataCopyFolderSelect");
  const saveBtn = document.getElementById("btnSaveDataCopy");
  const reloadBtn = document.getElementById("btnReloadDataCopy");
  const toggleFindBtn = document.getElementById("btnToggleDataCopyFind");
  const findInput = document.getElementById("dataCopyFindInput");
  const findCloseBtn = document.getElementById("btnDataCopyFindClose");
  const findNextBtn = document.getElementById("btnDataCopyFindNext");
  const findPrevBtn = document.getElementById("btnDataCopyFindPrev");
  const textarea = document.getElementById("dataCopyTextarea");
  const lineNumbers = document.getElementById("dataCopyLineNumbers");

  if (folderSelect) {
    folderSelect.addEventListener("change", async () => {
      const nextFolder = folderSelect.value;
      if (dataCopiesIsDirty) {
        const discard = confirm(t("datacopy.confirmUnsaved", "You have unsaved changes in {0}. Do you want to discard them?", dataCopiesCurrentFile || "file"));
        if (!discard) {
          folderSelect.value = dataCopiesCurrentFolder;
          return;
        }
      }
      dataCopiesCurrentFolder = nextFolder;
      renderDataCopyFilePills(nextFolder);
      const folderObj = dataCopiesFolders.find(f => f.id === nextFolder);
      const files = (folderObj && folderObj.files) || [];
      const firstFile = files.find(f => f.exists) || files[0];
      if (firstFile) {
        await loadDataCopyFile(nextFolder, firstFile.name);
      } else {
        clearDataCopyEditor();
      }
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", () => saveCurrentDataCopyFile());
  }

  if (reloadBtn) {
    reloadBtn.addEventListener("click", () => {
      if (!dataCopiesCurrentFolder || !dataCopiesCurrentFile) return;
      if (dataCopiesIsDirty) {
        const discard = confirm(t("datacopy.confirmUnsaved", "You have unsaved changes in {0}. Do you want to discard them?", dataCopiesCurrentFile));
        if (!discard) return;
      }
      loadDataCopyFile(dataCopiesCurrentFolder, dataCopiesCurrentFile);
    });
  }

  if (toggleFindBtn) {
    toggleFindBtn.addEventListener("click", () => {
      const widget = document.getElementById("dataCopyFindWidget");
      if (widget && widget.style.display !== "none") {
        closeDataCopyFindWidget();
      } else {
        openDataCopyFindWidget();
      }
    });
  }

  if (findCloseBtn) {
    findCloseBtn.addEventListener("click", () => closeDataCopyFindWidget());
  }

  if (findNextBtn) {
    findNextBtn.addEventListener("click", () => {
      stepDataCopyFind(1);
      if (findInput) findInput.focus();
    });
  }

  if (findPrevBtn) {
    findPrevBtn.addEventListener("click", () => {
      stepDataCopyFind(-1);
      if (findInput) findInput.focus();
    });
  }

  if (findInput) {
    findInput.addEventListener("input", () => performDataCopyFind());
    findInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        stepDataCopyFind(e.shiftKey ? -1 : 1);
      } else if (e.key === "Escape") {
        e.preventDefault();
        closeDataCopyFindWidget();
      }
    });
  }

  if (textarea) {
    textarea.addEventListener("input", () => {
      if (dataCopiesIsReadOnly) return;
      dataCopiesIsDirty = (textarea.value !== dataCopiesCurrentContent);
      updateDataCopyStatusBadge();
      updateDataCopyLineNumbers();
      updateDataCopyFooterStats();
      if (document.getElementById("dataCopyFindWidget")?.style.display !== "none") {
        performDataCopyFind();
      }
    });

    textarea.addEventListener("scroll", () => {
      if (lineNumbers) lineNumbers.scrollTop = textarea.scrollTop;
      renderDataCopyHighlights();
    });

    textarea.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveCurrentDataCopyFile();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        openDataCopyFindWidget();
      } else if (e.key === "Tab") {
        e.preventDefault();
        if (dataCopiesIsReadOnly) return;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        textarea.value = textarea.value.substring(0, start) + "    " + textarea.value.substring(end);
        textarea.selectionStart = textarea.selectionEnd = start + 4;
        textarea.dispatchEvent(new Event("input"));
      }
    });
  }

  // Global shortcut: when in dataCopiesTab, Ctrl+F opens find
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
      const tab = document.getElementById("dataCopiesTab");
      if (tab && tab.classList.contains("active")) {
        e.preventDefault();
        openDataCopyFindWidget();
      }
    }
  });
}

async function loadDataCopiesView(targetFolder = null, targetFile = null) {
  try {
    const res = await fetch("/api/data-copies/list");
    const data = await res.json();
    if (!res.ok || !data.valid) {
      showToast(data.error || t("datacopy.noFiles", "No data configuration files found in this folder"), "error");
      return;
    }
    dataCopiesFolders = data.folders || [];
    const folderSelect = document.getElementById("dataCopyFolderSelect");
    if (!folderSelect) return;

    folderSelect.innerHTML = "";
    dataCopiesFolders.forEach(f => {
      const opt = document.createElement("option");
      opt.value = f.id;
      opt.textContent = f.is_vanilla ? t("datacopy.vanilla", "Vanilla data/ (Read-Only)") : `modloader \\ ${f.name}`;
      folderSelect.appendChild(opt);
    });

    const activeFolderId = targetFolder || dataCopiesCurrentFolder || data.default_folder || (dataCopiesFolders[0] && dataCopiesFolders[0].id) || "Modded Cars";
    dataCopiesCurrentFolder = activeFolderId;
    folderSelect.value = activeFolderId;

    renderDataCopyFilePills(activeFolderId);

    const folderObj = dataCopiesFolders.find(f => f.id === activeFolderId);
    const files = (folderObj && folderObj.files) || [];
    const activeFileName = targetFile || dataCopiesCurrentFile || (files.find(f => f.exists) || files[0] || {}).name || "vehicles.ide";

    if (activeFileName) {
      await loadDataCopyFile(activeFolderId, activeFileName);
    } else {
      clearDataCopyEditor();
    }
  } catch (err) {
    showToast(t("datacopy.noFiles", "No data configuration files found in this folder"), "error");
  }
}

function renderDataCopyFilePills(folderId) {
  const container = document.getElementById("dataCopyFilePills");
  if (!container) return;
  container.innerHTML = "";

  const folderObj = dataCopiesFolders.find(f => f.id === folderId);
  const files = (folderObj && folderObj.files) || [];

  files.forEach(f => {
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = `data-copy-pill${f.name === dataCopiesCurrentFile ? " active" : ""}${!f.exists ? " is-missing" : ""}`;
    pill.textContent = f.name;
    if (!f.exists) {
      pill.title = t("common.notGenerated", "Not created yet");
    }
    pill.addEventListener("click", async () => {
      if (f.name === dataCopiesCurrentFile) return;
      if (dataCopiesIsDirty) {
        const discard = confirm(t("datacopy.confirmUnsaved", "You have unsaved changes in {0}. Do you want to discard them?", dataCopiesCurrentFile));
        if (!discard) return;
      }
      await loadDataCopyFile(dataCopiesCurrentFolder, f.name);
    });
    container.appendChild(pill);
  });
}

async function loadDataCopyFile(folderId, fileName) {
  dataCopiesCurrentFolder = folderId;
  dataCopiesCurrentFile = fileName;

  // Highlight active pill
  document.querySelectorAll(".data-copy-pill").forEach(p => {
    p.classList.toggle("active", p.textContent.trim() === fileName);
  });

  const textarea = document.getElementById("dataCopyTextarea");
  const saveBtn = document.getElementById("btnSaveDataCopy");
  const pathDisplay = document.getElementById("dataCopyPathDisplay");

  try {
    const res = await fetch(`/api/data-copies/read?folder=${encodeURIComponent(folderId)}&file=${encodeURIComponent(fileName)}`);
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast(data.error || t("datacopy.noFiles", "Unable to read file"), "error");
      return;
    }

    dataCopiesCurrentContent = data.content || "";
    dataCopiesIsDirty = false;
    dataCopiesIsReadOnly = Boolean(data.is_readonly);

    if (textarea) {
      textarea.value = dataCopiesCurrentContent;
      textarea.readOnly = dataCopiesIsReadOnly;
      textarea.scrollTop = 0;
    }

    if (saveBtn) {
      saveBtn.disabled = dataCopiesIsReadOnly;
    }

    if (pathDisplay) {
      pathDisplay.textContent = data.rel_path || data.path || fileName;
    }

    const encodingDisplay = document.getElementById("dataCopyEncodingDisplay");
    if (encodingDisplay) {
      encodingDisplay.textContent = `${(data.encoding || "UTF-8").toUpperCase()} / CRLF`;
    }

    updateDataCopyStatusBadge();
    updateDataCopyLineNumbers();
    updateDataCopyFooterStats();
    closeDataCopyFindWidget();
  } catch (err) {
    showToast(t("datacopy.noFiles", "Unable to read file"), "error");
  }
}

function clearDataCopyEditor() {
  const textarea = document.getElementById("dataCopyTextarea");
  const pathDisplay = document.getElementById("dataCopyPathDisplay");
  dataCopiesCurrentContent = "";
  dataCopiesIsDirty = false;
  if (textarea) textarea.value = "";
  if (pathDisplay) pathDisplay.textContent = "--";
  updateDataCopyStatusBadge();
  updateDataCopyLineNumbers();
  updateDataCopyFooterStats();
}

function updateDataCopyStatusBadge() {
  const badge = document.getElementById("dataCopyStatusBadge");
  if (!badge) return;
  if (dataCopiesIsReadOnly) {
    badge.className = "badge";
    badge.style.background = "#1f293d";
    badge.style.color = "var(--accent-cyan)";
    badge.textContent = t("datacopy.readOnlyBadge", "🔒 Read-Only");
  } else if (dataCopiesIsDirty) {
    badge.className = "badge";
    badge.style.background = "rgba(245, 158, 11, 0.2)";
    badge.style.color = "var(--accent-amber, #f59e0b)";
    badge.textContent = t("datacopy.unsavedBadge", "● Unsaved");
  } else {
    badge.className = "badge badge-success";
    badge.style.background = "";
    badge.style.color = "";
    badge.textContent = t("datacopy.savedBadge", "✓ Saved");
  }
}

function updateDataCopyLineNumbers() {
  const lineNumbers = document.getElementById("dataCopyLineNumbers");
  const textarea = document.getElementById("dataCopyTextarea");
  if (!lineNumbers || !textarea) return;

  const count = (textarea.value.match(/\n/g) || []).length + 1;
  const arr = new Array(count);
  for (let i = 0; i < count; i++) {
    arr[i] = String(i + 1);
  }
  lineNumbers.textContent = arr.join("\n");
}

function updateDataCopyFooterStats() {
  const linesEl = document.getElementById("dataCopyLinesDisplay");
  const charsEl = document.getElementById("dataCopyCharsDisplay");
  const textarea = document.getElementById("dataCopyTextarea");
  if (!textarea) return;

  const text = textarea.value;
  const lineCount = (text.match(/\n/g) || []).length + (text.length > 0 ? 1 : 0);
  if (linesEl) linesEl.textContent = t("datacopy.linesCount", "{0} lines").replace("{0}", lineCount);
  if (charsEl) charsEl.textContent = t("datacopy.charsCount", "{0} chars").replace("{0}", text.length);
}

async function saveCurrentDataCopyFile() {
  if (dataCopiesIsReadOnly) return;
  if (!dataCopiesCurrentFolder || !dataCopiesCurrentFile) return;

  const textarea = document.getElementById("dataCopyTextarea");
  if (!textarea) return;
  const content = textarea.value;

  const saveBtn = document.getElementById("btnSaveDataCopy");
  if (saveBtn) saveBtn.disabled = true;

  try {
    const res = await fetch("/api/data-copies/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        folder: dataCopiesCurrentFolder,
        file: dataCopiesCurrentFile,
        content: content
      })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast(data.error || t("datacopy.saveSuccess", "Failed to save file"), "error");
      return;
    }

    dataCopiesCurrentContent = content;
    dataCopiesIsDirty = false;
    updateDataCopyStatusBadge();
    showToast(t("datacopy.saveSuccess", "Saved {0} successfully (Backup created).", dataCopiesCurrentFile), "success");
  } catch (err) {
    showToast(t("datacopy.saveSuccess", "Failed to save file"), "error");
  } finally {
    if (saveBtn) saveBtn.disabled = dataCopiesIsReadOnly;
  }
}

// In-Editor Ctrl+F Find Widget
function openDataCopyFindWidget() {
  const widget = document.getElementById("dataCopyFindWidget");
  const findInput = document.getElementById("dataCopyFindInput");
  const textarea = document.getElementById("dataCopyTextarea");
  if (!widget || !findInput) return;

  widget.style.display = "flex";
  if (textarea && textarea.selectionStart !== textarea.selectionEnd) {
    const selected = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd).trim();
    if (selected && !selected.includes("\n") && selected.length < 50) {
      findInput.value = selected;
    }
  }
  findInput.focus();
  findInput.select();
  performDataCopyFind();
}

let dataCopyMeasureEl = null;
let dataCopyCharWidthCache = null;

function getDataCopyMeasureEl() {
  if (!dataCopyMeasureEl && typeof document !== "undefined") {
    dataCopyMeasureEl = document.createElement("span");
    dataCopyMeasureEl.style.position = "absolute";
    dataCopyMeasureEl.style.visibility = "hidden";
    dataCopyMeasureEl.style.pointerEvents = "none";
    dataCopyMeasureEl.style.whiteSpace = "pre";
    dataCopyMeasureEl.style.fontFamily = "'Consolas', 'Fira Code', monospace";
    dataCopyMeasureEl.style.fontSize = "12px";
    dataCopyMeasureEl.style.lineHeight = "20px";
    dataCopyMeasureEl.style.tabSize = "4";
    document.body.appendChild(dataCopyMeasureEl);
  }
  return dataCopyMeasureEl;
}

function getDataCopyCharWidth() {
  if (dataCopyCharWidthCache === null) {
    if (typeof document === "undefined") return 7.2;
    const el = getDataCopyMeasureEl();
    if (!el) return 7.2;
    el.textContent = "MMMMMMMMMM";
    const w = el.getBoundingClientRect().width;
    dataCopyCharWidthCache = (w > 0 ? w / 10 : 7.2);
  }
  return dataCopyCharWidthCache;
}

function measureDataCopyTextWidth(text) {
  if (!text) return 0;
  if (!text.includes("\t")) {
    return text.length * getDataCopyCharWidth();
  }
  if (typeof document === "undefined") return text.length * 7.2;
  const el = getDataCopyMeasureEl();
  if (!el) return text.length * 7.2;
  el.textContent = text;
  return el.getBoundingClientRect().width;
}

function renderDataCopyHighlights() {
  const overlay = document.getElementById("dataCopyHighlightOverlay");
  const textarea = document.getElementById("dataCopyTextarea");
  if (!overlay || !textarea) return;

  if (!dataCopiesFindMatches || !dataCopiesFindMatches.length || dataCopiesFindIndex < 0) {
    overlay.innerHTML = "";
    return;
  }

  const text = textarea.value;
  const scrollTop = textarea.scrollTop;
  const scrollLeft = textarea.scrollLeft;
  const clientHeight = textarea.clientHeight;
  const clientWidth = textarea.clientWidth;
  const lineHeight = 20;
  const paddingTop = 12;
  const paddingLeft = 14;

  let html = "";

  // 1. Active line highlight strip
  const activeMatch = dataCopiesFindMatches[dataCopiesFindIndex];
  if (activeMatch) {
    const activeLineStart = text.lastIndexOf("\n", activeMatch.start - 1) + 1;
    const activeLineIndex = (text.substring(0, activeLineStart).match(/\n/g) || []).length;
    const activeLineTop = paddingTop + (activeLineIndex * lineHeight) - scrollTop;
    if (activeLineTop >= -lineHeight && activeLineTop <= clientHeight) {
      html += `<div class="data-copy-active-line-strip" style="top:${activeLineTop}px; height:${lineHeight}px;"></div>`;
    }
  }

  // 2. Word highlight bounding boxes
  let rendered = 0;
  for (let i = 0; i < dataCopiesFindMatches.length && rendered < 150; i++) {
    const m = dataCopiesFindMatches[i];
    const isActive = (i === dataCopiesFindIndex);

    const mLineStart = text.lastIndexOf("\n", m.start - 1) + 1;
    const mLineIndex = (text.substring(0, mLineStart).match(/\n/g) || []).length;
    const mLineTop = paddingTop + (mLineIndex * lineHeight) - scrollTop;

    // Check vertical visibility
    if (mLineTop < -lineHeight || mLineTop > clientHeight) {
      continue;
    }

    const prefix = text.substring(mLineStart, m.start);
    const word = text.substring(m.start, m.end);
    const charX = measureDataCopyTextWidth(prefix);
    const charWidth = measureDataCopyTextWidth(word);
    const boxLeft = paddingLeft + charX - scrollLeft;

    // Check horizontal visibility
    if (boxLeft + charWidth < 0 || boxLeft > clientWidth) {
      continue;
    }

    const cls = isActive ? "data-copy-word-highlight is-active" : "data-copy-word-highlight is-secondary";
    html += `<div class="${cls}" style="top:${mLineTop}px; left:${boxLeft}px; width:${Math.max(4, charWidth)}px; height:${lineHeight}px;"></div>`;
    rendered++;
  }

  overlay.innerHTML = html;
}

function closeDataCopyFindWidget() {
  const widget = document.getElementById("dataCopyFindWidget");
  if (widget) widget.style.display = "none";
  dataCopiesFindMatches = [];
  dataCopiesFindIndex = -1;
  const overlay = document.getElementById("dataCopyHighlightOverlay");
  if (overlay) overlay.innerHTML = "";
  const textarea = document.getElementById("dataCopyTextarea");
  if (textarea) textarea.focus();
}

function performDataCopyFind() {
  const findInput = document.getElementById("dataCopyFindInput");
  const countEl = document.getElementById("dataCopyFindCount");
  const textarea = document.getElementById("dataCopyTextarea");
  if (!findInput || !textarea) return;

  const query = findInput.value;
  if (!query) {
    dataCopiesFindMatches = [];
    dataCopiesFindIndex = -1;
    if (countEl) countEl.textContent = t("datacopy.noMatches", "No matches");
    renderDataCopyHighlights();
    return;
  }

  const text = textarea.value.toLowerCase();
  const q = query.toLowerCase();
  const matches = [];
  let pos = 0;
  while ((pos = text.indexOf(q, pos)) !== -1) {
    matches.push({ start: pos, end: pos + q.length });
    pos += q.length;
  }

  dataCopiesFindMatches = matches;
  if (!matches.length) {
    dataCopiesFindIndex = -1;
    if (countEl) countEl.textContent = t("datacopy.noMatches", "No matches");
    renderDataCopyHighlights();
    return;
  }

  const cursor = textarea.selectionStart;
  let idx = matches.findIndex(m => m.start >= cursor);
  if (idx === -1) idx = 0;
  dataCopiesFindIndex = idx;
  jumpToDataCopyMatch(idx);
}

function stepDataCopyFind(direction) {
  if (!dataCopiesFindMatches.length) return;
  const total = dataCopiesFindMatches.length;
  let nextIdx = (dataCopiesFindIndex + direction + total) % total;
  dataCopiesFindIndex = nextIdx;
  jumpToDataCopyMatch(nextIdx);
}

function jumpToDataCopyMatch(index) {
  const textarea = document.getElementById("dataCopyTextarea");
  const countEl = document.getElementById("dataCopyFindCount");
  if (!textarea || index < 0 || index >= dataCopiesFindMatches.length) return;

  const match = dataCopiesFindMatches[index];
  textarea.setSelectionRange(match.start, match.end);

  const text = textarea.value;
  const lineStart = text.lastIndexOf("\n", match.start - 1) + 1;
  const linesBefore = (text.substring(0, lineStart).match(/\n/g) || []).length;
  const lineHeight = 20;

  // Vertical scroll: keep match visible with comfortable headroom
  const targetScrollTop = Math.max(0, (linesBefore * lineHeight) - 120);
  textarea.scrollTop = targetScrollTop;

  // Horizontal scroll: if match is horizontally outside view, bring it in
  const prefix = text.substring(lineStart, match.start);
  const word = text.substring(match.start, match.end);
  const charX = measureDataCopyTextWidth(prefix);
  const charWidth = measureDataCopyTextWidth(word);
  const paddingLeft = 14;

  const currentLeft = textarea.scrollLeft;
  const viewportWidth = textarea.clientWidth;
  const matchLeft = paddingLeft + charX;
  const matchRight = matchLeft + charWidth;

  if (matchLeft < currentLeft + 30 || matchRight > currentLeft + viewportWidth - 30) {
    textarea.scrollLeft = Math.max(0, matchLeft - 60);
  }

  if (countEl) {
    countEl.textContent = t("datacopy.matchCount", "{0} of {1}", index + 1, dataCopiesFindMatches.length);
  }

  renderDataCopyHighlights();
}

// ---------------- Mod Library ----------------

let currentModStats = {
  total_folders: 0,
  total_vehicles: 0,
  replace_folders: 0,
  replace_vehicles: 0,
  addon_folders: 0,
  addon_vehicles: 0
};

function updateModCountBadges(stats) {
  if (stats) {
    if (stats.total_folders !== undefined) currentModStats.total_folders = stats.total_folders;
    else if (stats.total !== undefined) currentModStats.total_folders = stats.total;
    if (stats.total_vehicles !== undefined) currentModStats.total_vehicles = stats.total_vehicles;
    if (stats.replace_folders !== undefined) currentModStats.replace_folders = stats.replace_folders;
    if (stats.replace_vehicles !== undefined) currentModStats.replace_vehicles = stats.replace_vehicles;
    else if (stats.replace_count !== undefined) currentModStats.replace_vehicles = stats.replace_count;
    if (stats.addon_folders !== undefined) currentModStats.addon_folders = stats.addon_folders;
    if (stats.addon_vehicles !== undefined) currentModStats.addon_vehicles = stats.addon_vehicles;
    else if (stats.addon_count !== undefined) currentModStats.addon_vehicles = stats.addon_count;
  } else if (Array.isArray(allMods)) {
    const repMods = allMods.filter(m => m.mod_type !== "addon" && !m.is_addon);
    const addMods = allMods.filter(m => m.mod_type === "addon" || m.is_addon);
    currentModStats.replace_folders = repMods.length;
    currentModStats.addon_folders = addMods.length;
    currentModStats.replace_vehicles = repMods.reduce((sum, m) => sum + (m.target_vehicles ? m.target_vehicles.length : (m.target_models ? m.target_models.length : 1)), 0);
    currentModStats.addon_vehicles = addMods.reduce((sum, m) => sum + (m.target_vehicles ? m.target_vehicles.length : (m.target_models ? m.target_models.length : 1)), 0);
    currentModStats.total_folders = allMods.length;
    currentModStats.total_vehicles = currentModStats.replace_vehicles + currentModStats.addon_vehicles;
  }

  const navBadge = document.getElementById("modCountBadge");
  const replaceBadge = document.getElementById("replaceCountBadge");
  const addonBadge = document.getElementById("addonCountBadge");

  const totV = currentModStats.total_vehicles || (currentModStats.replace_vehicles + currentModStats.addon_vehicles);
  const totF = currentModStats.total_folders || 0;
  const repV = currentModStats.replace_vehicles || 0;
  const repF = currentModStats.replace_folders || 0;
  const addV = currentModStats.addon_vehicles || 0;
  const addF = currentModStats.addon_folders || 0;

  const vehicleFolderBadge = (vehicles, folders) => {
    const vLabel = window.t("mods.badgeVehicleCount", "{0} vehicles").replace("{0}", vehicles);
    const fLabel = window.t("mods.badgeFolderCount", "({0} folders)").replace("{0}", folders);
    return `<span>${vLabel}</span> <span class="badge-sub-folder">${fLabel}</span>`;
  };

  if (navBadge) {
    navBadge.textContent = "";
  }
  if (replaceBadge) {
    replaceBadge.innerHTML = vehicleFolderBadge(repV, repF);
  }
  if (addonBadge) {
    addonBadge.innerHTML = vehicleFolderBadge(addV, addF);
  }
}

async function loadMods() {
  const grid = document.getElementById("modGrid");
  if (!allMods || allMods.length === 0) {
    grid.innerHTML = `<div class="loading-spinner">${window.t("mods.loading", "Scanning ModLoader vehicle mods...")}</div>`;
  }

  try {
    const res = await fetch("/api/mods");
    const data = await res.json();
    if (data.success) {
      allMods = data.mods;
      updateModCountBadges(data);
      applyFilter();

      if (activeMod && Array.isArray(data.mods)) {
        const stillExists = data.mods.some(m => isSamePath(m.full_path, activeMod.full_path));
        if (!stillExists) {
          discardInspectorContext(false);
        }
      }
    }
  } catch (err) {
    grid.innerHTML = `<div class="empty-hint">${loc({ en: "Failed to load mods: " })}${err.message}</div>`;
  }
}

document.getElementById("refreshModsBtn").addEventListener("click", loadMods);

// Compact vehicle-type tile for mod cards. Icons are intentionally small and
// monochrome; each type gets a subtle tint so the card keeps its text-first
// hierarchy instead of turning into an icon wall.
const VEHICLE_TYPE_ICONS = {
  car: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 15.5v-1.6c0-.9.6-1.7 1.5-1.9l2-.5 1.9-3.3A2.3 2.3 0 0 1 10.8 7h2.4a2.3 2.3 0 0 1 1.9 1.2l1.9 3.3 2 .5c.9.2 1.5 1 1.5 1.9v1.6"/><path d="M3.5 15.5h17"/><circle cx="7.2" cy="16.1" r="1.7"/><circle cx="16.8" cy="16.1" r="1.7"/></svg>`,
  bike: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="16.2" r="2.5"/><circle cx="18" cy="16.2" r="2.5"/><path d="M8.6 16.2h4.2l2.6-6.6h2.3"/><path d="M12.8 9.6h3.6"/><path d="M9.6 16.2l3.2-6.6"/></svg>`,
  quad: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5.6 15.2h12.8l-.8-3.3a2 2 0 0 0-1.9-1.5h-4.2a2 2 0 0 0-1.9 1.5l-.8 3.3z"/><circle cx="7.2" cy="16.6" r="1.7"/><circle cx="16.8" cy="16.6" r="1.7"/><path d="M13.6 10.4V8.2h2.6"/></svg>`,
  boat: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.7 14.6h16.6l-2.4 3.9a2 2 0 0 1-1.7.9H7.8a2 2 0 0 1-1.7-.9l-2.4-3.9z"/><path d="M12 3.6v11"/><path d="M12 4.9l5.1 5.1H12"/></svg>`,
  heli: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="10.4" cy="14.4" rx="4.6" ry="3.3"/><path d="M15 14.4h3.4l2.1-2.6"/><path d="M4.6 6.6h14.8"/><path d="M12 6.6v4.5"/></svg>`,
  plane: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3c.6 0 1 .5 1 1.1v5l7 4.1v1.9l-7-2.1v4.4l2.6 1.9v1.4L12 19.4l-3.6 1.3v-1.4l2.6-1.9v-4.4l-7 2.1v-1.9L11 9.1v-5c0-.6.4-1.1 1-1.1z"/></svg>`,
  trailer: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 9.5h10v6.5H7z"/><circle cx="9.6" cy="17.4" r="1.5"/><circle cx="14.4" cy="17.4" r="1.5"/><path d="M7 14H4.6l-1.6 2.1"/></svg>`,
  train: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="4.8" width="12" height="10.4" rx="2.4"/><path d="M6 12.6h12"/><path d="M9.2 15.2v1.2M14.8 15.2v1.2"/><circle cx="9.2" cy="17.9" r="1.6"/><circle cx="14.8" cy="17.9" r="1.6"/></svg>`,
};

const VEHICLE_TYPE_META = {
  car: { icon: VEHICLE_TYPE_ICONS.car, cls: "type-car", label: { en: "Car" } },
  mtruck: { icon: VEHICLE_TYPE_ICONS.car, cls: "type-car", label: { en: "Truck" } },
  bike: { icon: VEHICLE_TYPE_ICONS.bike, cls: "type-bike", label: { en: "Motorcycle" } },
  bmx: { icon: VEHICLE_TYPE_ICONS.bike, cls: "type-bike", label: { en: "Bicycle" } },
  wayfarer: { icon: VEHICLE_TYPE_ICONS.bike, cls: "type-bike", label: { en: "Motorcycle" } },
  quad: { icon: VEHICLE_TYPE_ICONS.quad, cls: "type-quad", label: { en: "Quad" } },
  boat: { icon: VEHICLE_TYPE_ICONS.boat, cls: "type-boat", label: { en: "Boat" } },
  heli: { icon: VEHICLE_TYPE_ICONS.heli, cls: "type-heli", label: { en: "Helicopter" } },
  plane: { icon: VEHICLE_TYPE_ICONS.plane, cls: "type-plane", label: { en: "Plane" } },
  dodo: { icon: VEHICLE_TYPE_ICONS.plane, cls: "type-plane", label: { en: "Plane" } },
  trailer: { icon: VEHICLE_TYPE_ICONS.trailer, cls: "type-trailer", label: { en: "Trailer" } },
  train: { icon: VEHICLE_TYPE_ICONS.train, cls: "type-train", label: { en: "Train" } },
};

function vehicleTypeMeta(type) {
  return VEHICLE_TYPE_META[(type || "").toLowerCase()] || VEHICLE_TYPE_META.car;
}

function renderModGrid(mods) {
  const grid = document.getElementById("modGrid");
  grid.innerHTML = "";
  if (mods.length === 0) {
    grid.innerHTML = `<div class="empty-hint">${window.t("mods.emptyTitle", "No matching vehicle mods found")}</div>`;
    return;
  }

  mods.forEach(mod => {
    const card = document.createElement("div");
    card.className = "mod-card";
    card.addEventListener("click", () => inspectMod(mod));

    const author = mod.author || (loc({ en: "Unknown Author" }));

    const metaBits = [];
    if (mod.has_handling) metaBits.push(`<span class="feat-meta" title="${window.t("mods.filterHandling", "Handling")}">${window.t("mods.cardHandlingBadge", "Handling")}</span>`);
    if (mod.has_carcols) metaBits.push(`<span class="feat-meta" title="${window.t("mods.cardCarcolsBadge", "Colors")}">${window.t("mods.cardCarcolsBadge", "Colors")}</span>`);
    if (mod.fla_has_audio) metaBits.push(`<span class="feat-meta" title="${window.t("mods.cardAudioBadge", "Audio")}">${window.t("mods.cardAudioBadge", "Audio")}</span>`);
    if (mod.total_tuning_parts > 0) {
      metaBits.push(`<span class="feat-meta feat-parts">${mod.total_tuning_parts} ${window.t("mods.cardTuningParts", "parts")}</span>`);
    }

    const alertBits = [];
    if (mod.has_shopping_risk) {
      alertBits.push(`<span class="badge badge-warning" title="${loc({ en: "Unpriced parts in shopping.dat" })}">${loc({ en: "Shop Risk" })}</span>`);
    }
    if (mod.fla_special) {
      const icon = mod.fla_special.icon || "★";
      const specialLabel = mod.fla_special.target || (window.I18N && typeof window.I18N.pick === "function"
        ? (window.I18N.pick(mod.fla_special, "label") || mod.fla_special.label)
        : (mod.fla_special.label || mod.fla_special.target));
      const titleAttr = mod.fla_special.is_native
        ? (loc({ en: `GTA:SA Native Feature (${mod.fla_special.target})` }))
        : (loc({ en: `FLA Special Feature` }));
      alertBits.push(`<span class="badge badge-special" title="${titleAttr}">${icon} ${specialLabel}</span>`);
    }

    const isAddonMod = Boolean(mod.is_addon || mod.mod_type === "addon");
    const vList = (mod.target_vehicles && mod.target_vehicles.length > 0)
      ? mod.target_vehicles
      : (mod.target_models && mod.target_models.length > 0
          ? mod.target_models.map(m => ({ model: m, name: m.toUpperCase(), id: mod.addon_id, is_addon: isAddonMod }))
          : []);

    const isMulti = Boolean(vList && vList.length > 1);
    const vehicleCount = vList.length || (mod.target_models ? mod.target_models.length : 1);

    let targetRowHtml = "";
    let subVehiclesHtml = "";

    if (isMulti) {
      const packLabel = window.t("mods.multiPackBadge", "📦 Multi-Vehicle ({count} Vehicles)").replace("{count}", vehicleCount);
      targetRowHtml = `<div class="mod-card-target-row"><span class="badge-multi-pack">${packLabel}</span></div>`;

      const extraCount = vList.length > 2 ? vList.length - 2 : 0;
      const moreLabel = extraCount
        ? window.t("mods.cardMoreVehicles", "+{count}").replace("{count}", extraCount)
        : "";
      subVehiclesHtml = `
        <div class="mod-card-sub-vehicles">
          ${vList.map(v => {
            const isAddonVeh = Boolean(v.is_addon !== undefined ? v.is_addon : isAddonMod);
            const vName = v.name || (v.model ? v.model.toUpperCase() : "");
            const vIdBadge = v.id ? `<span class="sub-chip-id">${v.id}</span>` : "";
            const chipClass = isAddonVeh ? "sub-chip-addon" : "sub-chip-replace";
            return `<span class="vehicle-sub-chip ${chipClass}" title="${v.model || ''} (${v.dff_name || ''})">${vName} ${vIdBadge}</span>`;
          }).join("")}
          ${extraCount ? `<button type="button" class="sub-chip-more" data-extra="${extraCount}">${moreLabel}</button>` : ""}
        </div>
      `;
    } else {
      const targetName = (vList.length === 1 && vList[0].name)
        ? vList[0].name
        : (mod.vanilla_name || (mod.target_model ? mod.target_model.toUpperCase() : (t("common.unknown"))));
      const singleId = (vList.length === 1 && vList[0].id) ? vList[0].id : mod.addon_id;
      if (isAddonMod) {
        const kindLabel = window.t("mods.cardAddon", "Addon Vehicle");
        const idPill = singleId ? `<span class="sub-chip-id">ID: ${singleId}</span>` : "";
        const modelSub = (vList.length === 1 && vList[0].model) ? `<span class="target-model-code">${vList[0].model.toUpperCase()}</span>` : "";
        targetRowHtml = `<div class="mod-card-target-row"><span class="target-kind-tag kind-addon">➕ ${kindLabel}</span><span class="target-name" title="${targetName}">${targetName}</span>${modelSub}${idPill}</div>`;
      } else {
        const replacesLabel = window.t("mods.cardOriginal", "Replaces");
        targetRowHtml = `<div class="mod-card-target-row"><span class="target-kind-tag kind-replace">🔁 ${replacesLabel}</span><span class="target-name" title="${targetName}">${targetName}</span></div>`;
      }
    }

    const authorText = `${window.t("mods.cardAuthor", "Author")}: ${author}`;
    const deleteTitle = loc({ en: "Delete this mod folder and revert configs" });
    const footerHtml = (metaBits.length || alertBits.length)
      ? `<div class="feature-badges">
        ${metaBits.length ? `<div class="feat-meta-row">${metaBits.join("")}</div>` : "<div></div>"}
        ${alertBits.length ? `<div class="feat-alert-row">${alertBits.join("")}</div>` : ""}
      </div>`
      : "";

    const targetModelsArg = (mod.target_models && mod.target_models.length > 0) ? mod.target_models.join(',') : (mod.target_model || '');
    const deleteIcon = `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M6.5 1h3a.5.5 0 0 1 .5.5V2h3.5a.5.5 0 0 1 0 1H13v10.5A1.5 1.5 0 0 1 11.5 15h-7A1.5 1.5 0 0 1 3 13.5V3H1.5a.5.5 0 0 1 0-1H5v-.5a.5.5 0 0 1 .5-.5zM4 3v10.5a.5.5 0 0 0 .5.5h7a.5.5 0 0 0 .5-.5V3H4zm2.5 2.5a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0v-6a.5.5 0 0 1 .5-.5zm3 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0v-6a.5.5 0 0 1 .5-.5z"/></svg>`;
    const renameTitle = window.t("mods.cardRenameTitle", "Rename this mod folder");
    const renameIcon = `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61zm.176 4.823L9.75 4.81l-6.286 6.287a.253.253 0 0 0-.064.108l-.558 1.953 1.953-.558a.253.253 0 0 0 .108-.064zm1.238-3.763a.25.25 0 0 0-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 0 0 0-.354z"/></svg>`;
    const typeMeta = vehicleTypeMeta((vList[0] && vList[0].type) || mod.vanilla_type || "car");
    const typeLabel = loc(typeMeta.label);

    card.innerHTML = `
      <div class="mod-card-header">
        <div class="mod-card-type ${typeMeta.cls}" title="${typeLabel}" aria-label="${typeLabel}">${typeMeta.icon}</div>
        <div class="mod-card-heading">
          <div class="mod-card-title-row">
            <span class="mod-card-title" title="${mod.name}">${mod.name}</span>
            <div class="mod-card-actions">
              <button type="button" class="card-rename-btn" title="${renameTitle}" aria-label="${window.t("mods.cardRenameBtn", "Rename")}">${renameIcon}</button>
              <button type="button" class="card-delete-btn" title="${deleteTitle}" aria-label="${window.t("mods.cardDeleteBtn", "Delete")}">${deleteIcon}</button>
            </div>
          </div>
          ${targetRowHtml}
        </div>
      </div>
      <div class="mod-card-author">${authorText}</div>
      <div class="mod-card-path" title="${mod.rel_path}">${mod.rel_path}</div>
      ${subVehiclesHtml}
      ${footerHtml}
    `;

    const authorHint = card.querySelector(".mod-card-author");
    if (authorHint) authorHint.title = `${authorText}\n${mod.rel_path || ""}`;

    const delBtn = card.querySelector(".card-delete-btn");
    if (delBtn) {
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        requestDeleteMod(encodeURIComponent(mod.full_path), encodeURIComponent(mod.name), targetModelsArg);
      });
    }
    const renBtn = card.querySelector(".card-rename-btn");
    if (renBtn) {
      renBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openRenameModModal(mod);
      });
    }
    const moreBtn = card.querySelector(".sub-chip-more");
    if (moreBtn) {
      moreBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const extra = moreBtn.dataset.extra || "";
        const expanded = card.classList.toggle("is-expanded");
        moreBtn.textContent = expanded
          ? window.t("mods.cardLessVehicles", "Less")
          : window.t("mods.cardMoreVehicles", "+{count}").replace("{count}", extra);
      });
    }

    grid.appendChild(card);
  });
}

async function requestDeleteMod(encodedPath, encodedName, targetModel) {
  const fullPath = decodeURIComponent(encodedPath);
  const modName = decodeURIComponent(encodedName);
  const confirmMsg = loc({ en: `⚠️ Are you sure you want to permanently delete mod [${modName}]?\n\nFile Path: ${fullPath}\n\nThis action will:\n1. Permanently delete the mod folder and all 3D models/textures\n2. Automatically restore handling/carcols/carmods/FLA to original baseline\n3. Clean up empty author subfolders if applicable\n\nThis action cannot be undone. Confirm delete?` });

  if (!confirm(confirmMsg)) return;

  try {
    const res = await fetch("/api/mods/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: fullPath,
        model: targetModel,
        revert_config: true
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(loc({ en: `Mod [${modName}] deleted and configs reverted!` }));
      allMods = allMods.filter(m => !isSamePath(m.full_path, fullPath));
      updateModCountBadges();
      applyFilter();

      const isInspectingDeleted = (
        (activeMod && isSamePath(activeMod.full_path, fullPath)) ||
        (currentInspectorSummary && isSamePath(currentInspectorSummary.full_path, fullPath)) ||
        (currentInspectorDetail && (isSamePath(currentInspectorDetail.mod_dir, fullPath) || isSamePath(currentInspectorDetail.mod_dir_full, fullPath)))
      );
      if (isInspectingDeleted) {
        discardInspectorContext();
      }
      loadMods();
      loadSystemStatus();
    } else {
      showToast((loc({ en: "Failed to delete mod: " })) + (data.error || (t("common.unknownError"))), "error");
    }
  } catch (err) {
    showToast((loc({ en: "Delete request exception: " })) + err.message, "error");
  }
}

let currentFilter = "all";

// ---------------- Mod Folder Rename ----------------

let renamingMod = null;

function openRenameModModal(mod) {
  if (!mod || !mod.full_path) return;
  renamingMod = mod;

  const modal = document.getElementById("renameModModal");
  const input = document.getElementById("inputRenameModName");
  const pathHint = document.getElementById("renameModCurrentPath");
  const errorDiv = document.getElementById("renameModError");
  const saveBtn = document.getElementById("saveRenameModBtn");

  const folderName = mod.full_path.split(/[\\/]/).filter(Boolean).pop() || mod.name || "";
  if (input) input.value = folderName;
  if (pathHint) pathHint.textContent = mod.full_path;
  if (errorDiv) errorDiv.textContent = "";
  if (saveBtn) {
    saveBtn.disabled = false;
    if (saveBtn.dataset.origText) saveBtn.textContent = saveBtn.dataset.origText;
  }

  if (modal) modal.classList.add("active");
  if (input) {
    setTimeout(() => {
      input.focus();
      input.select();
    }, 100);
  }
}

function setupRenameModControls() {
  const modal = document.getElementById("renameModModal");
  const closeBtn = document.getElementById("closeRenameModModal");
  const cancelBtn = document.getElementById("cancelRenameModBtn");
  const saveBtn = document.getElementById("saveRenameModBtn");
  const input = document.getElementById("inputRenameModName");

  const hideModal = () => {
    if (modal) modal.classList.remove("active");
    renamingMod = null;
  };

  if (closeBtn) closeBtn.addEventListener("click", hideModal);
  if (cancelBtn) cancelBtn.addEventListener("click", hideModal);
  if (saveBtn) saveBtn.addEventListener("click", submitModRename);

  if (input) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submitModRename();
      } else if (e.key === "Escape") {
        hideModal();
      }
    });
  }
}

async function submitModRename() {
  if (!renamingMod) return;

  const input = document.getElementById("inputRenameModName");
  const errorDiv = document.getElementById("renameModError");
  const saveBtn = document.getElementById("saveRenameModBtn");
  if (saveBtn && saveBtn.disabled) return;
  const newName = (input ? input.value : "").trim();

  if (!newName) {
    if (errorDiv) errorDiv.textContent = window.t("mods.renameEmptyError", "Folder name cannot be empty");
    return;
  }

  const oldPath = renamingMod.full_path;
  const wasActive = Boolean(activeMod && isSamePath(activeMod.full_path, oldPath));

  if (saveBtn) {
    saveBtn.dataset.origText = saveBtn.dataset.origText || saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = t("common.saving");
  }
  if (errorDiv) errorDiv.textContent = "";

  try {
    const res = await fetch("/api/mods/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: oldPath, new_name: newName })
    });
    const data = await res.json();

    if (!data.success) {
      if (errorDiv) errorDiv.textContent = data.error || t("common.unknownError");
      return;
    }

    const modal = document.getElementById("renameModModal");
    if (modal) modal.classList.remove("active");
    renamingMod = null;

    showToast(loc({ en: `Mod folder renamed to [${data.new_name}]` }), "success");

    if (wasActive && activeMod) {
      const updated = {
        ...activeMod,
        name: data.new_name,
        full_path: data.new_path,
        rel_path: data.rel_path || activeMod.rel_path
      };
      activeMod = updated;
      if (currentInspectorSummary) {
        currentInspectorSummary = {
          ...currentInspectorSummary,
          name: data.new_name,
          full_path: data.new_path,
          rel_path: data.rel_path || currentInspectorSummary.rel_path
        };
      }
      if (currentInspectorDetail) {
        currentInspectorDetail.mod_dir = data.new_path;
        if (currentInspectorDetail.mod_dir_full) currentInspectorDetail.mod_dir_full = data.new_path;
      }
      const nameEl = document.getElementById("inspectModName");
      if (nameEl) nameEl.textContent = data.new_name;
      const inspectorTab = document.getElementById("inspectorTab");
      if (inspectorTab && inspectorTab.classList.contains("active")) {
        inspectMod(activeMod);
      }
    }

    loadMods();
    loadSystemStatus();
  } catch (err) {
    if (errorDiv) errorDiv.textContent = (loc({ en: "Rename request failed: " })) + err.message;
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      if (saveBtn.dataset.origText) saveBtn.textContent = saveBtn.dataset.origText;
    }
  }
}

function applyFilter() {
  const searchInput = document.getElementById("modSearchInput");
  const q = searchInput ? searchInput.value.toLowerCase().trim() : "";
  const filtered = allMods.filter(m => {
    // 1. Partition filter (replace vs addon)
    const isAddon = Boolean(m.mod_type === "addon" || m.is_addon);
    if (activeModPartition === "addon" && !isAddon) return false;
    if (activeModPartition === "replace" && isAddon) return false;

    // 2. Text match (including sub-vehicles inside packs)
    const matchVehicles = Boolean(m.target_vehicles && m.target_vehicles.some(v =>
      (v.name && v.name.toLowerCase().includes(q)) ||
      (v.model && v.model.toLowerCase().includes(q)) ||
      (v.id && String(v.id).includes(q))
    ));

    const matchText = !q || m.name.toLowerCase().includes(q) ||
      (m.author && m.author.toLowerCase().includes(q)) ||
      (m.target_model && m.target_model.toLowerCase().includes(q)) ||
      (m.vanilla_name && m.vanilla_name.toLowerCase().includes(q)) ||
      (m.addon_id && String(m.addon_id).includes(q)) ||
      matchVehicles;

    if (!matchText) return false;

    // 3. Chip filter
    if (currentFilter === "has_handling") return m.has_handling;
    if (currentFilter === "has_tuning") return m.total_tuning_parts > 0;
    if (currentFilter === "has_risk") return m.has_shopping_risk;
    if (currentFilter === "has_special") return !!m.fla_special;
    return true;
  });

  renderModGrid(filtered);
}

function setupFiltersAndSearch() {
  const searchInput = document.getElementById("modSearchInput");
  const chips = document.querySelectorAll(".filter-chips .chip");
  const btnReplace = document.getElementById("partitionReplaceBtn");
  const btnAddon = document.getElementById("partitionAddonBtn");

  if (btnReplace) {
    btnReplace.addEventListener("click", () => {
      activeModPartition = "replace";
      btnReplace.classList.add("active");
      if (btnAddon) btnAddon.classList.remove("active");
      updatePartitionFolderBar();
      applyFilter();
    });
  }

  if (btnAddon) {
    btnAddon.addEventListener("click", () => {
      activeModPartition = "addon";
      btnAddon.classList.add("active");
      if (btnReplace) btnReplace.classList.remove("active");
      updatePartitionFolderBar();
      applyFilter();
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", applyFilter);
  }

  chips.forEach(chip => {
    chip.addEventListener("click", () => {
      chips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      currentFilter = chip.getAttribute("data-filter");
      applyFilter();
    });
  });
}

// ---------------- Card Density (comfortable / compact) ----------------

const CARD_DENSITIES = ["comfortable", "compact"];
let currentCardDensity = "comfortable";

function applyCardDensity(density, persist = false) {
  const next = CARD_DENSITIES.includes(density) ? density : "comfortable";
  currentCardDensity = next;
  const grid = document.getElementById("modGrid");
  if (grid) grid.classList.toggle("density-compact", next === "compact");
  document.querySelectorAll("#densityToggle .density-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-density") === next);
  });
  if (persist) {
    fetch("/api/config/card-density", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ density: next })
    }).catch(() => {});
  }
}

function setupDensityToggle() {
  const toggle = document.getElementById("densityToggle");
  if (!toggle) return;
  toggle.querySelectorAll(".density-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      applyCardDensity(btn.getAttribute("data-density"), true);
    });
  });
}

// ---------------- Mod Inspector ----------------

function resetInspectorView() {
  if (window.SourceDocuments) window.SourceDocuments.render(null);
  const nameEl = document.getElementById("inspectModName");
  if (nameEl) nameEl.textContent = window.t("inspect.titleDefault", "Select a mod to inspect");
  const authorEl = document.getElementById("inspectAuthor");
  if (authorEl) authorEl.textContent = "--";

  ["btnDryRun", "btnApplyMerge", "btnDeleteCurrentMod", "btnRenameCurrentMod"].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.disabled = true;
    if (id === "btnDeleteCurrentMod" || id === "btnRenameCurrentMod") el.onclick = null;
  });

  if (typeof resetAllCardEditors === "function") resetAllCardEditors();

  const switcherBar = document.getElementById("inspectorMultiVehicleBar");
  if (switcherBar) switcherBar.style.display = "none";

  const idBadge = document.getElementById("targetIdBadge");
  if (idBadge) idBadge.textContent = window.t("inspect.targetIdBadgeDefault", "ID: --");
  const vName = document.getElementById("targetVanillaName");
  if (vName) vName.textContent = "--";
  const typeIconEl = document.getElementById("targetVehicleTypeIcon");
  if (typeIconEl) {
    typeIconEl.style.display = "none";
    typeIconEl.innerHTML = "";
  }
  const vModel = document.getElementById("targetModelCode");
  if (vModel) vModel.textContent = "--";
  const vDff = document.getElementById("targetDffSize");
  if (vDff) vDff.textContent = "--";
  const shopWrap = document.getElementById("identityShopWrap");
  if (shopWrap) shopWrap.hidden = true;

  ["vehiclesIdeRawPreview", "handlingRawPreview", "carcolsRawPreview", "carmodsRawPreview"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "--";
  });
  ["vehiclesIdeSourceBadge", "handlingSourceBadge", "carcolsSourceBadge", "carmodsSourceBadge"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "--";
  });

  const hDiv = document.getElementById("handlingDetails");
  if (hDiv) hDiv.innerHTML = `<p class="empty-hint" data-i18n="inspect.handlingEmpty">${window.t("inspect.handlingEmpty", "No custom handling provided. Using vanilla physics.")}</p>`;
  const hBadge = document.getElementById("handlingDriveBadge");
  if (hBadge) hBadge.textContent = "--";

  const cDiv = document.getElementById("carcolsPalettes");
  if (cDiv) cDiv.innerHTML = `<p class="empty-hint" data-i18n="inspect.carcolsEmpty">${window.t("inspect.carcolsEmpty", "No custom colors provided. Using vanilla palette.")}</p>`;
  const cBadge = document.getElementById("colorCountBadge");
  if (cBadge) cBadge.textContent = window.t("inspect.colorCountBadgeDefault", "0 Schemes");
  const cTypeBadge = document.getElementById("colorTypeBadge");
  if (cTypeBadge) {
    cTypeBadge.style.display = "none";
    cTypeBadge.textContent = "";
  }

  const tDiv = document.getElementById("tuningDetails");
  if (tDiv) tDiv.innerHTML = `<p class="empty-hint" data-i18n="inspect.tuningEmpty">${window.t("inspect.tuningEmpty", "No tuning parts detected for this vehicle.")}</p>`;
  const tBadge = document.getElementById("tuningCountBadge");
  if (tBadge) tBadge.textContent = window.t("inspect.tuningCountBadgeDefault", "0 Parts");

  const readme = document.getElementById("rawReadmeContent");
  if (readme) readme.textContent = window.t("inspect.readmeEmpty", "No text content available");

  document.querySelectorAll("#inspectorTab details.raw-disclosure[open]").forEach(d => { d.open = false; });

  if (typeof resetFlaDisplay === "function") resetFlaDisplay();
}

function discardInspectorContext(redirect = true) {
  inspectRequestSeq += 1;
  flaRequestSeq += 1;
  activeMod = null;
  currentInspectorDetail = null;
  currentInspectorSummary = null;
  currentInspectedModel = "";
  currentFlaDetail = null;
  activeFxtKey = "";
  activeFxtName = "";
  carcolsPaletteCache = null;
  resetInspectorView();

  if (redirect) {
    const inspectorPanel = document.getElementById("inspectorTab");
    if (inspectorPanel && inspectorPanel.classList.contains("active")) {
      switchTab("modsTab");
    }
  }
}

async function inspectMod(modSummary) {
  const mySeq = ++inspectRequestSeq;
  switchTab("inspectorTab");
  activeMod = modSummary;

  document.getElementById("inspectModName").textContent = modSummary.name;
  document.getElementById("inspectAuthor").textContent = `${window.t("mods.cardAuthor", "Author")}: ${modSummary.author}`;
  document.getElementById("btnDryRun").disabled = false;
  document.getElementById("btnApplyMerge").disabled = false;

  const btnDelete = document.getElementById("btnDeleteCurrentMod");
  if (btnDelete) {
    btnDelete.disabled = false;
    btnDelete.onclick = () => {
      const current = activeMod;
      if (!current || !current.full_path) return;
      const modelsArg = (current.target_models && current.target_models.length > 0) ? current.target_models.join(',') : (current.target_model || "");
      requestDeleteMod(encodeURIComponent(current.full_path), encodeURIComponent(current.name), modelsArg);
    };
  }

  const btnRename = document.getElementById("btnRenameCurrentMod");
  if (btnRename) {
    btnRename.disabled = false;
    btnRename.onclick = () => {
      if (activeMod) openRenameModModal(activeMod);
    };
  }

  // Fetch full details
  try {
    const res = await fetch(`/api/mod-detail?full_path=${encodeURIComponent(modSummary.full_path)}`);
    const detail = await res.json();
    if (mySeq !== inspectRequestSeq) return;
    if (detail.success) {
      renderInspectorData(detail, modSummary);
    }
  } catch (err) {
    if (mySeq !== inspectRequestSeq) return;
    showToast(window.t("toast.fetchDetailFailed", "Failed to load mod details"), "error");
  }
}

let carcolsPaletteCache = null;

async function ensureCarcolsPalette() {
  if (carcolsPaletteCache) return carcolsPaletteCache;
  try {
    const res = await fetch("/api/colors");
    const data = await res.json();
    if (data.success && data.palette) {
      carcolsPaletteCache = data.palette;
      return carcolsPaletteCache;
    }
  } catch (e) {}
  return null;
}

function setupCardEditors() {
  ensureCarcolsPalette();

  const bindEditor = (type, toggleId, cancelId, saveId, inputId) => {
    const btnToggle = document.getElementById(toggleId);
    const btnCancel = document.getElementById(cancelId);
    const btnSave = document.getElementById(saveId);
    const input = document.getElementById(inputId);

    if (btnToggle) {
      btnToggle.addEventListener("click", () => toggleCardEdit(type));
    }
    if (btnCancel) {
      btnCancel.addEventListener("click", () => toggleCardEdit(type, false));
    }
    if (btnSave) {
      btnSave.addEventListener("click", () => saveCardConfig(type));
    }
    if (type === "carcols" && input) {
      input.addEventListener("input", (e) => renderLiveCarcolsSwatches(e.target.value));
    }
  };

  bindEditor("vehiclesIde", "btnToggleEditVehiclesIde", "btnCancelEditVehiclesIde", "btnSaveVehiclesIde", "inputVehiclesIdeRaw");
  bindEditor("handling", "btnToggleEditHandling", "btnCancelEditHandling", "btnSaveHandling", "inputHandlingRaw");
  bindEditor("carcols", "btnToggleEditCarcols", "btnCancelEditCarcols", "btnSaveCarcols", "inputCarcolsRaw");
  bindEditor("carmods", "btnToggleEditCarmods", "btnCancelEditCarmods", "btnSaveCarmods", "inputCarmodsRaw");

  setupParamGuideInteractive();
}

function setupParamGuideInteractive() {
  // 1. vehicles.ide Guide
  const ideInput = document.getElementById("inputVehiclesIdeRaw");
  const ideGrid = document.getElementById("vehiclesIdeGuideGrid");
  if (ideInput && ideGrid) {
    const ideSpans = Array.from(ideGrid.querySelectorAll("span"));

    const updateIdeGuide = () => {
      const pos = ideInput.selectionStart ?? 0;
      const text = ideInput.value || "";
      const textBefore = text.slice(0, pos);
      const commaCount = (textBefore.match(/,/g) || []).length;
      ideSpans.forEach((span, i) => {
        const isActive = (i === commaCount);
        span.classList.toggle("active-item", isActive);
        span.classList.toggle("highlight", isActive);
      });
    };

    ["input", "click", "keyup", "keydown", "select", "focus"].forEach(evt => {
      ideInput.addEventListener(evt, updateIdeGuide);
    });

    ideSpans.forEach((span, targetIdx) => {
      span.title = window.t("inspect.guideClickToJump", "Click to jump and select this parameter field");
      span.addEventListener("click", () => {
        const val = ideInput.value || "";
        const tokens = val.split(",");
        if (targetIdx < tokens.length) {
          let startPos = 0;
          for (let i = 0; i < targetIdx; i++) {
            startPos += tokens[i].length + 1; // +1 for comma
          }
          while (startPos < val.length && val[startPos] === " ") startPos++;
          let endPos = startPos;
          while (endPos < val.length && val[endPos] !== ",") endPos++;
          ideInput.focus();
          ideInput.setSelectionRange(startPos, endPos);
          updateIdeGuide();
        }
      });
    });
  }

  // 2. handling.cfg Guide
  const handlingInput = document.getElementById("inputHandlingRaw");
  const handlingGrid = document.getElementById("handlingGuideGrid");
  if (handlingInput && handlingGrid) {
    const handlingSpans = Array.from(handlingGrid.querySelectorAll("span"));

    // A chip names a *group* of whitespace-separated tokens (centre of mass is
    // X Y Z, traction is mult/loss/bias, brake is decel/bias/ABS, ...), so token
    // N is not chip N - and the engine-inertia field between acceleration and
    // the Drive/Engine pair belongs to no chip at all. The Drive/Engine pair is
    // located by pattern and every later chip is anchored on it, exactly like
    // the backend decomposes the same line (core/parser.py decompose_handling).
    // Bike/boat/plane lines (!/%/$ prefix) have no such pair: they simply get no
    // highlight instead of a wrongly aligned one.
    const HANDLING_GUIDE_FIELDS = [
      { start: 0, size: 1 },      // 1 Identifier
      { start: 1, size: 1 },      // 2 Mass
      { start: 2, size: 1 },      // 3 TurnMass
      { start: 3, size: 1 },      // 4 DragMult
      { start: 4, size: 3 },      // 5 CenterOfMass [X, Y, Z]
      { start: 7, size: 1 },      // 6 Submerged %
      { start: 8, size: 3 },      // 7 Traction [mult, loss, bias]
      { drive: -4, size: 1 },     // 8 Gears
      { drive: -3, size: 1 },     // 9 MaxSpeed
      { drive: -2, size: 1 },     // 10 Acceleration
      { drive: 0, size: 1 },      // 11 Drive [F/R/4]
      { drive: 1, size: 1 },      // 12 Engine [P/D/E]
      { drive: 2, size: 3 },      // 13 Brake [decel, bias, ABS]
      { drive: 5, size: 1 },      // 14 SteerAngle
    ];

    const handlingTokens = () => Array.from((handlingInput.value || "").matchAll(/\S+/g));

    // The fourteen chips describe the car parameter set only; a bike/boat/
    // aircraft/trailer line has a different layout, so the guide steps aside
    // instead of pointing at fields it does not know.
    const handlingLineIsSecondary = text => {
      const trimmed = (text || "").trim();
      return Boolean(trimmed) && '!$%^'.includes(trimmed[0]);
    };

    const handlingDriveIndex = tokens => {
      for (let i = 10; i < Math.min(25, tokens.length - 1); i++) {
        if (/^[FR4]$/i.test(tokens[i][0]) && /^[PDE]$/i.test(tokens[i + 1][0])) return i;
      }
      for (let i = 10; i < Math.min(25, tokens.length - 1); i++) {
        if (/^[FR4]$/i.test(tokens[i][0]) && /^[A-Z]$/i.test(tokens[i + 1][0])) return i;
      }
      return -1;
    };

    const handlingFieldRange = (field, driveIdx) => {
      const start = field.drive === undefined ? field.start : driveIdx + field.drive;
      return start < 0 ? null : { start, end: start + field.size - 1 };
    };

    const handlingChipForToken = (tokenIndex, tokens) => {
      const driveIdx = handlingDriveIndex(tokens);
      if (driveIdx < 0) return -1;
      for (let chip = 0; chip < HANDLING_GUIDE_FIELDS.length; chip++) {
        const range = handlingFieldRange(HANDLING_GUIDE_FIELDS[chip], driveIdx);
        if (range && tokenIndex >= range.start && tokenIndex <= range.end) return chip;
      }
      return -1;
    };

    // The caret belongs to the token it sits in; inside the whitespace between
    // two tokens it belongs to the one that just ended. Selecting a field starts
    // at the token's first character, so both directions agree on the same chip.
    const handlingTokenAt = (text, pos) => {
      const tokens = Array.from(text.matchAll(/\S+/g));
      for (let i = 0; i < tokens.length; i++) {
        const start = tokens[i].index;
        if (pos >= start && pos <= start + tokens[i][0].length) return { index: i, tokens };
      }
      let previous = -1;
      for (let i = 0; i < tokens.length; i++) {
        if (tokens[i].index + tokens[i][0].length <= pos) previous = i; else break;
      }
      return { index: previous, tokens };
    };

    const updateHandlingGuide = () => {
      const text = handlingInput.value || "";
      const secondary = handlingLineIsSecondary(text);
      const pos = handlingInput.selectionStart ?? 0;
      const { index, tokens } = handlingTokenAt(text, pos);
      const chip = secondary ? -1 : handlingChipForToken(index, tokens);
      handlingSpans.forEach((span, i) => {
        span.classList.toggle("chip-disabled", secondary);
        span.title = secondary
          ? window.t("inspect.guideCarOnly", "This guide describes car parameters; this vehicle uses a different physics layout")
          : window.t("inspect.guideClickToJump", "Click to jump and select this parameter field");
        const isActive = (i === chip);
        span.classList.toggle("active-item", isActive);
        span.classList.toggle("highlight", isActive);
      });
    };

    ["input", "click", "keyup", "keydown", "select", "focus"].forEach(evt => {
      handlingInput.addEventListener(evt, updateHandlingGuide);
    });

    handlingInput.addEventListener("input", () => {
      if (currentVanillaHandling && !currentIsAddonVehicle) {
        const parsed = parseHandlingLine(handlingInput.value);
        renderLiveHandlingDiff(parsed, currentVanillaHandling);
      }
    });

    handlingSpans.forEach((span, chipIndex) => {
      span.title = window.t("inspect.guideClickToJump", "Click to jump and select this parameter field");
      span.addEventListener("click", () => {
        if (handlingLineIsSecondary(handlingInput.value)) return;
        const tokens = handlingTokens();
        const driveIdx = handlingDriveIndex(tokens);
        if (driveIdx < 0) return;
        const range = handlingFieldRange(HANDLING_GUIDE_FIELDS[chipIndex], driveIdx);
        if (!range || range.start >= tokens.length) return;
        // Select the group's first token only: replacing a three-token vector
        // with a single typed number would shift every following field.
        const target = tokens[range.start];
        handlingInput.focus();
        handlingInput.setSelectionRange(target.index, target.index + target[0].length);
        updateHandlingGuide();
      });
    });
  }
}

function toggleCardEdit(type, forceState) {
  const map = {
    vehiclesIde: {
      btn: document.getElementById("btnToggleEditVehiclesIde"),
      preview: document.getElementById("vehiclesIdePreviewContainer"),
      edit: document.getElementById("vehiclesIdeEditContainer"),
      input: document.getElementById("inputVehiclesIdeRaw")
    },
    handling: {
      btn: document.getElementById("btnToggleEditHandling"),
      preview: document.getElementById("handlingPreviewContainer"),
      edit: document.getElementById("handlingEditContainer"),
      input: document.getElementById("inputHandlingRaw")
    },
    carcols: {
      btn: document.getElementById("btnToggleEditCarcols"),
      preview: document.getElementById("carcolsPreviewContainer"),
      edit: document.getElementById("carcolsEditContainer"),
      input: document.getElementById("inputCarcolsRaw")
    },
    carmods: {
      btn: document.getElementById("btnToggleEditCarmods"),
      preview: document.getElementById("carmodsPreviewContainer"),
      edit: document.getElementById("carmodsEditContainer"),
      input: document.getElementById("inputCarmodsRaw")
    }
  };

  const c = map[type];
  if (!c || !c.preview || !c.edit) return;

  const shouldOpen = (forceState !== undefined) ? forceState : (c.edit.style.display === "none" || !c.edit.style.display);

  if (shouldOpen) {
    c.preview.style.display = "none";
    c.edit.style.display = "block";
    if (c.btn) {
      c.btn.style.display = "none";
    }
    if (type === "vehiclesIde") {
      const fxtBtn = document.getElementById("btnToggleEditFxtName");
      if (fxtBtn) fxtBtn.style.display = "none";
    }
    if (c.input) {
      c.input.focus();
      if (type === "carcols") {
        renderLiveCarcolsSwatches(c.input.value);
      }
      if (type === "vehiclesIde") {
        c.input.dispatchEvent(new Event("focus"));
      }
      if (type === "handling") {
        c.input.dispatchEvent(new Event("focus"));
        if (currentVanillaHandling && !currentIsAddonVehicle) {
          const parsed = parseHandlingLine(c.input.value);
          renderLiveHandlingDiff(parsed, currentVanillaHandling);
        }
      }
    }
  } else {
    c.preview.style.display = "block";
    c.edit.style.display = "none";
    if (c.btn) {
      c.btn.style.display = "";
      c.btn.textContent = window.t("inspect.btnEdit", "✏️ Edit");
      c.btn.classList.remove("active");
    }
    if (type === "vehiclesIde") {
      const fxtBtn = document.getElementById("btnToggleEditFxtName");
      if (fxtBtn) fxtBtn.style.display = "";
    }
    if (type === "handling") {
      const liveDiff = document.getElementById("handlingEditLiveDiff");
      if (liveDiff) {
        liveDiff.style.display = "none";
        liveDiff.innerHTML = "";
      }
    }
  }
}

function resetAllCardEditors() {
  ["vehiclesIde", "handling", "carcols", "carmods"].forEach(t => toggleCardEdit(t, false));
  toggleFlaEdit("special", false);
  toggleFlaEdit("audio", false);
  const fxtBox = document.getElementById("fxtEditContainer");
  if (fxtBox) fxtBox.style.display = "none";
  const fxtBtn = document.getElementById("btnToggleEditFxtName");
  if (fxtBtn) fxtBtn.classList.remove("active");
}

// Right-column FLA cards follow the same collapsed-preview / edit pattern as
// the left-hand config cards.
function toggleFlaEdit(type, forceState) {
  const map = {
    special: {
      btn: document.getElementById("btnToggleEditSpecial"),
      preview: document.getElementById("specialPreviewContainer"),
      edit: document.getElementById("specialEditContainer"),
      input: document.getElementById("specialFeatureCustomInput")
    },
    audio: {
      btn: document.getElementById("btnToggleEditAudio"),
      preview: document.getElementById("audioPreviewContainer"),
      edit: document.getElementById("audioEditContainer"),
      input: document.getElementById("audioRawInput")
    }
  };
  const c = map[type];
  if (!c || !c.preview || !c.edit) return;

  const shouldOpen = (forceState !== undefined) ? forceState : (c.edit.style.display === "none" || !c.edit.style.display);
  if (shouldOpen) {
    c.preview.style.display = "none";
    c.edit.style.display = "block";
    if (c.btn) {
      c.btn.style.display = "none";
      c.btn.classList.add("active");
    }
    if (c.input) c.input.focus();
  } else {
    c.preview.style.display = "block";
    c.edit.style.display = "none";
    if (c.btn) {
      c.btn.style.display = "";
      c.btn.classList.remove("active");
    }
  }
}

function setupFxtNameEditor() {
  const btnToggle = document.getElementById("btnToggleEditFxtName");
  const box = document.getElementById("fxtEditContainer");
  const input = document.getElementById("inputFxtName");
  const btnSave = document.getElementById("btnSaveFxtName");
  const hint = document.getElementById("fxtEditKeyHint");
  if (!btnToggle || !box || !input || !btnSave) return;

  btnToggle.addEventListener("click", () => {
    const opening = (box.style.display === "none" || !box.style.display);
    box.style.display = opening ? "block" : "none";
    btnToggle.classList.toggle("active", opening);
    if (opening) {
      input.value = activeFxtName || "";
      input.focus();
    }
    if (hint) {
      const k = activeFxtKey || ((activeMod && activeMod.target_model) || "").toUpperCase();
      hint.textContent = k
        ? `${window.t("inspect.fxtEditKeyHint", "GXT key: ")} ${k}`
        : window.t("inspect.fxtEditNoKey", "No FXT entry for this vehicle yet; saving will create one.");
    }
  });

  btnSave.addEventListener("click", async () => {
    const detail = currentInspectorDetail;
    const modDir = (detail && (detail.mod_dir || detail.mod_dir_full)) || (currentInspectorSummary && currentInspectorSummary.full_path) || "";
    const model = ((activeMod && activeMod.target_model) || (detail && detail.target_model) || "").toLowerCase();
    const key = (activeFxtKey || model.toUpperCase() || "").toUpperCase();
    const name = (input.value || "").trim();
    if (!modDir) {
      showToast(window.t("toast.selectModFirst", "Please select a vehicle from the list first"), "error");
      return;
    }
    if (!key) {
      showToast(window.t("inspect.fxtEditNoKey", "No FXT entry for this vehicle yet; saving will create one."), "error");
      return;
    }
    if (!name) {
      showToast(window.t("inspect.fxtEditEmpty", "Name cannot be empty."), "error");
      return;
    }
    btnSave.disabled = true;
    try {
      const res = await fetch("/api/vehicle/update-fxt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mod_dir: modDir, key, name, model })
      });
      const data = await res.json();
      if (data.success) {
        showToast(window.t("toast.saveFxtSuccess", "Vehicle display name saved!"), "success");
        // Patch local state so the preview updates without refetch
        if (detail && detail.parsed) {
          detail.parsed.fxt = detail.parsed.fxt || [];
          const hit = detail.parsed.fxt.find(f => f && f.key && f.key.toUpperCase() === key);
          if (hit) { hit.name = name; hit.raw = `${key} ${name}`; }
          else detail.parsed.fxt.push({ key, name, raw: `${key} ${name}` });
        }
        if (detail && detail.target_vehicles) {
          const tv = detail.target_vehicles.find(t => t && t.model && t.model.toLowerCase() === model);
          if (tv) tv.name = name;
        }
        activeFxtKey = key;
        activeFxtName = name;
        box.style.display = "none";
        btnToggle.classList.remove("active");
        renderInspectorVehicleView(model);
      } else {
        showToast((window.t("toast.saveFxtFailed", "Failed to save name: ") || "Failed to save name: ") + (data.error || ""), "error");
      }
    } catch (err) {
      showToast(window.t("toast.networkError", "Network error: ") + err.message, "error");
    } finally {
      btnSave.disabled = false;
    }
  });
}

function renderConfigBadge(badgeId, source) {
  const badge = document.getElementById(badgeId);
  if (!badge) return;
  badge.className = "badge badge-sm";
  if (source === "shadow") {
    badge.classList.add("badge-success");
    badge.textContent = window.t("inspect.sourceShadow", "Modified Configuration Copy");
  } else if (source === "vanilla") {
    badge.classList.add("badge-secondary");
    badge.textContent = window.t("inspect.sourceVanilla", "Vanilla Baseline");
  } else if (source === "mod") {
    badge.classList.add("badge-info");
    badge.textContent = window.t("inspect.sourceMod", "Mod Preset");
  } else {
    badge.textContent = "--";
  }
}

function renderLiveCarcolsSwatches(rawText) {
  const container = document.getElementById("carcolsEditSwatchesPreview");
  if (!container) return;

  if (!rawText || !rawText.trim()) {
    container.innerHTML = "";
    return;
  }

  let line = rawText.trim();
  const isCar4 = /^car4\b/i.test(line);
  const stride = isCar4 ? 4 : 2;
  if (isCar4) {
    line = line.substring(4).trim();
  }

  const parts = line.split(",").map(p => p.trim()).filter(Boolean);
  if (parts.length < 2) {
    container.innerHTML = "";
    return;
  }

  const colorIds = [];
  for (let i = 1; i < parts.length; i++) {
    const num = parseInt(parts[i], 10);
    if (!isNaN(num)) {
      colorIds.push(num);
    }
  }

  if (colorIds.length < stride) {
    container.innerHTML = "";
    return;
  }

  let html = '<div class="swatch-grid" style="margin-top:4px;">';
  let pairCount = 0;
  for (let i = 0; i + stride <= colorIds.length; i += stride) {
    const c1 = colorIds[i];
    const c2 = colorIds[i + 1];
    pairCount++;
    const hex1 = (carcolsPaletteCache && carcolsPaletteCache[c1]) || "#888888";
    const hex2 = (carcolsPaletteCache && carcolsPaletteCache[c2]) || "#888888";
    if (isCar4) {
      const c3 = colorIds[i + 2];
      const c4 = colorIds[i + 3];
      const hex3 = (carcolsPaletteCache && carcolsPaletteCache[c3]) || "#888888";
      const hex4 = (carcolsPaletteCache && carcolsPaletteCache[c4]) || "#888888";
      const tooltip = window.t("inspect.colorQuadTooltip", "4-Color Scheme #{0}: Colors {1}, {2}, {3}, {4}")
        .replace("{0}", pairCount).replace("{1}", c1).replace("{2}", c2).replace("{3}", c3).replace("{4}", c4);
      html += `
        <div class="color-pair-badge" title="${tooltip}">
          <div class="swatch-split swatch-quad">
            <div class="quad" style="background-color: ${hex1}"></div>
            <div class="quad" style="background-color: ${hex2}"></div>
            <div class="quad" style="background-color: ${hex3}"></div>
            <div class="quad" style="background-color: ${hex4}"></div>
          </div>
          <span class="swatch-ids">${c1}, ${c2}, ${c3}, ${c4}</span>
        </div>
      `;
      continue;
    }
    const tooltip = window.t("inspect.colorPairTooltip", "Scheme #{0}: Colors {1}, {2}")
      .replace("{0}", pairCount).replace("{1}", c1).replace("{2}", c2);

    html += `
      <div class="color-pair-badge" title="${tooltip}">
        <div class="swatch-split">
          <div class="half" style="background-color: ${hex1}"></div>
          <div class="half" style="background-color: ${hex2}"></div>
        </div>
        <span class="swatch-ids">${c1}, ${c2}</span>
      </div>
    `;
  }
  html += '</div>';
  container.innerHTML = html;
}

let currentVanillaHandling = null;
let currentIsAddonVehicle = false;

function parseHandlingLine(rawLine) {
  if (!rawLine) return null;
  const clean = rawLine.split(';')[0].split('//')[0].trim();
  // Bikes (!), boats (%), aircraft ($) and trailers (^) use their own shorter
  // physics layout: the car fields below do not describe them, so no car-field
  // preview is produced (core/parser.py splits the same way and reports
  // is_secondary for those lines). Testing the prefix also closes the boundary
  // where a long prefixed line used to slip through the length gate below.
  if (clean && '!$%^'.includes(clean[0])) return null;
  const parts = clean.split(/\s+/).filter(Boolean);
  if (parts.length < 20) return null;
  let driveIdx = -1;
  for (let i = 10; i < Math.min(25, parts.length - 1); i++) {
    const p1 = parts[i].toUpperCase();
    const p2 = parts[i + 1].toUpperCase();
    if (['F', 'R', '4'].includes(p1) && ['P', 'D', 'E'].includes(p2)) {
      driveIdx = i;
      break;
    }
  }
  if (driveIdx === -1) {
    for (let i = 10; i < Math.min(25, parts.length - 1); i++) {
      const p1 = parts[i].toUpperCase();
      const p2 = parts[i + 1].toUpperCase();
      if (['F', 'R', '4'].includes(p1) && /^[A-Z]$/.test(p2)) {
        driveIdx = i;
        break;
      }
    }
  }
  if (driveIdx === -1) return null;
  try {
    const res = {
      valid: true,
      raw: rawLine,
      identifier: parts[0].toUpperCase(),
      mass_kg: parseFloat(parts[1]),
      turn_mass: parseFloat(parts[2]),
      drag_mult: parseFloat(parts[3]),
      center_of_mass: [parseFloat(parts[4]), parseFloat(parts[5]), parseFloat(parts[6])],
      submerged_percent: parseInt(parts[7], 10),
      traction_mult: parseFloat(parts[8]),
      traction_loss: parseFloat(parts[9]),
      traction_bias: parseFloat(parts[10]),
      gears: parseInt(parts[driveIdx - 4], 10),
      max_speed_kmh: parseFloat(parts[driveIdx - 3]),
      acceleration: parseFloat(parts[driveIdx - 2]),
      engine_inertia: parseFloat(parts[driveIdx - 1]),
      drive_type: parts[driveIdx].toUpperCase(),
      engine_type: parts[driveIdx + 1].toUpperCase(),
      brake_decel: parseFloat(parts[driveIdx + 2]),
      brake_bias: parseFloat(parts[driveIdx + 3]),
      steering_lock_deg: parseFloat(parts[driveIdx + 5]),
    };
    if (parts.length > driveIdx + 6) res.suspension_force = parseFloat(parts[driveIdx + 6]);
    if (parts.length > driveIdx + 7) res.suspension_damping = parseFloat(parts[driveIdx + 7]);
    if (parts.length > driveIdx + 10) res.suspension_lower_limit = parseFloat(parts[driveIdx + 10]);
    if (parts.length > driveIdx + 15) res.monetary_value = parseInt(parts[driveIdx + 15], 10);
    return res;
  } catch (e) {
    return null;
  }
}

function renderLiveHandlingDiff(modH, vanillaH) {
  const container = document.getElementById("handlingEditLiveDiff");
  if (!container) return;
  if (!modH || !modH.valid || !vanillaH || !vanillaH.valid) {
    container.style.display = "none";
    container.innerHTML = "";
    return;
  }
  container.style.display = "flex";

  const diffItems = [];

  // 1. Max Speed
  const speedDiff = modH.max_speed_kmh - vanillaH.max_speed_kmh;
  diffItems.push(`
    <div class="live-diff-item">
      <span>${window.t("inspect.paramMaxSpeed", "Max Speed")}:</span>
      <span class="live-diff-val">${modH.max_speed_kmh} km/h</span>
      ${Math.abs(speedDiff) > 0.01 ? `<span class="diff-tag ${speedDiff > 0 ? 'diff-tag-up' : 'diff-tag-down'}">${speedDiff > 0 ? '+' : ''}${speedDiff.toFixed(1)}</span>` : `<span class="diff-same-badge">=</span>`}
    </div>
  `);

  // 2. Mass
  const massDiff = modH.mass_kg - vanillaH.mass_kg;
  diffItems.push(`
    <div class="live-diff-item">
      <span>${window.t("inspect.paramMass", "Vehicle Mass")}:</span>
      <span class="live-diff-val">${modH.mass_kg} kg</span>
      ${Math.abs(massDiff) > 0.01 ? `<span class="diff-tag ${massDiff > 0 ? 'diff-tag-down' : 'diff-tag-up'}">${massDiff > 0 ? '+' : ''}${Math.round(massDiff)}</span>` : `<span class="diff-same-badge">=</span>`}
    </div>
  `);

  // 3. Gears
  const gearsDiff = modH.gears - vanillaH.gears;
  diffItems.push(`
    <div class="live-diff-item">
      <span>${window.t("inspect.paramGears", "Transmission Gears")}:</span>
      <span class="live-diff-val">${modH.gears}</span>
      ${gearsDiff !== 0 ? `<span class="diff-tag ${gearsDiff > 0 ? 'diff-tag-up' : 'diff-tag-down'}">${gearsDiff > 0 ? '+' : ''}${gearsDiff}</span>` : `<span class="diff-same-badge">=</span>`}
    </div>
  `);

  // 4. Accel
  const accelDiff = modH.acceleration - vanillaH.acceleration;
  diffItems.push(`
    <div class="live-diff-item">
      <span>${window.t("inspect.paramAccel", "Acceleration Factor")}:</span>
      <span class="live-diff-val">${modH.acceleration}</span>
      ${Math.abs(accelDiff) > 0.01 ? `<span class="diff-tag ${accelDiff > 0 ? 'diff-tag-up' : 'diff-tag-down'}">${accelDiff > 0 ? '+' : ''}${accelDiff.toFixed(1)}</span>` : `<span class="diff-same-badge">=</span>`}
    </div>
  `);

  // 5. Drive Type
  const dDiff = modH.drive_type !== vanillaH.drive_type;
  diffItems.push(`
    <div class="live-diff-item">
      <span>${window.t("inspect.paramDriveType", "Drive Type")}:</span>
      <span class="live-diff-val">${modH.drive_type}</span>
      ${dDiff ? `<span class="diff-tag diff-tag-modified">${vanillaH.drive_type} ➔ ${modH.drive_type}</span>` : `<span class="diff-same-badge">=</span>`}
    </div>
  `);

  container.innerHTML = `
    <span style="font-weight:600; color:var(--text-bright);">${window.t("inspect.diffLiveEditTitle", "⚡ Live Physics Delta Preview")}:</span>
    ${diffItems.join("")}
  `;
}

function renderHandlingPreview(h, vanillaH = currentVanillaHandling, isAddon = currentIsAddonVehicle) {
  const hDiv = document.getElementById("handlingDetails");
  const hBadge = document.getElementById("handlingDriveBadge");
  const driveMap = {
    "F": loc({ en: "FWD" }),
    "R": loc({ en: "RWD" }),
    "4": loc({ en: "AWD" })
  };
  const engineMap = {
    "P": loc({ en: "Petrol" }),
    "D": loc({ en: "Diesel" }),
    "E": loc({ en: "Electric" })
  };

  if (h && h.is_secondary) {
    // Motorcycles, boats, aircraft and trailers carry the game's own physics
    // layout. The car stats below would render as "undefined", so the card
    // states what the line is instead of pretending to decompose it; editing
    // and saving still write the raw line straight into handling.cfg.
    const kind = { "!": "bike", "%": "boat", "$": "plane", "^": "trailer" }[h.prefix] || "";
    if (hBadge) {
      const label = kind ? window.t("veh." + kind, kind) : window.t("veh.car", "Car");
      hBadge.innerHTML = `${label} · ${window.t("inspect.secondaryPhysicsTag", "separate physics")}`;
    }
    if (hDiv) {
      hDiv.innerHTML = `
        <p class="field-hint" data-i18n="inspect.secondaryPhysicsHint">${window.t("inspect.secondaryPhysicsHint", "This vehicle uses the game's own physics layout for motorcycles, boats, aircraft and trailers, so its fields are not the car parameter set. The line is shown as it is; the editor below still saves it straight into handling.cfg.")}</p>
      `;
    }
    return;
  }

  if (h && h.valid) {
    const dText = driveMap[h.drive_type] || (window.I18N ? window.I18N.pick(h, "drive_type_label") : "") || h.drive_type_label || h.drive_type;
    const eText = engineMap[h.engine_type] || (window.I18N ? window.I18N.pick(h, "engine_type_label") : "") || h.engine_type_label || h.engine_type;

    const hasVanilla = Boolean(!isAddon && vanillaH && vanillaH.valid);

    // Header drive badge with comparison
    let badgeHtml = `${dText} / ${eText}`;
    if (hasVanilla) {
      const dDiff = (h.drive_type !== vanillaH.drive_type);
      const eDiff = (h.engine_type !== vanillaH.engine_type);
      if (dDiff || eDiff) {
        const vd = driveMap[vanillaH.drive_type] || vanillaH.drive_type;
        const ve = engineMap[vanillaH.engine_type] || vanillaH.engine_type;
        badgeHtml += ` <span class="badge-diff-note">(${window.t("inspect.diffVanillaVal", "Vanilla")}: ${vd}/${ve})</span>`;
      }
    }
    hBadge.innerHTML = badgeHtml;

    // Scheme 1: Helper for Delta Badges inside stat pills
    // mode: "up" (higher is better), "weight" (lighter is better), "neutral"
    const renderDelta = (cur, van, unit = "", decimals = 1, mode = "neutral") => {
      if (!hasVanilla || van === null || van === undefined || isNaN(cur) || isNaN(van)) {
        return "";
      }
      const diff = cur - van;
      if (Math.abs(diff) < 0.0001) {
        return `<div class="stat-diff diff-same" title="${window.t("inspect.diffMatchesVanillaTooltip", "This parameter is identical to the vanilla game data/ physics")}">${window.t("inspect.diffMatchesVanilla", "= Matches Vanilla")}</div>`;
      }
      const diffStr = (diff > 0 ? "+" : "") + (decimals === 0 ? Math.round(diff) : diff.toFixed(decimals));
      const vanStr = (decimals === 0 ? Math.round(van) : (Number.isInteger(van) ? van : van.toFixed(decimals)));
      let cls = "diff-neutral";
      let arrow = "Δ";
      if (mode === "up") {
        cls = diff > 0 ? "diff-up" : "diff-down";
        arrow = diff > 0 ? "▲" : "▼";
      } else if (mode === "weight") {
        cls = diff > 0 ? "diff-down" : "diff-up";
        arrow = diff > 0 ? "▲" : "▼";
      }
      const titleAttr = mode === "neutral"
        ? window.t("inspect.diffNeutralTooltip", "Modified (no absolute better/worse for this parameter)")
        : `${window.t("inspect.diffVanillaVal", "Vanilla")}: ${vanStr}${unit ? ' ' + unit : ''}`;
      return `
        <div class="stat-diff ${cls}" title="${titleAttr}">
          <span class="diff-arrow">${arrow}</span> ${diffStr}${unit ? ' <small>' + unit + '</small>' : ''}
          <span class="diff-vanilla">(${window.t("inspect.diffVanillaVal", "Vanilla")}: ${vanStr})</span>
        </div>
      `;
    };

    // Scheme 2: Full Side-by-Side Comparison Table
    let diffDisclosureHtml = "";
    if (hasVanilla) {
      // semantic: "up" (higher is better), "weight" (lighter is better),
      // undefined = neutral (changed, but no absolute better/worse direction)
      const paramDefs = [
        { group: "drivetrain", key: "max_speed_kmh", semantic: "up", labelKey: "inspect.paramMaxSpeed", labelDef: "Max Speed", unit: "km/h", decimals: 1, type: "number" },
        { group: "drivetrain", key: "acceleration", semantic: "up", labelKey: "inspect.paramAccel", labelDef: "Acceleration", unit: "", decimals: 1, type: "number" },
        { group: "drivetrain", key: "gears", labelKey: "inspect.paramGears", labelDef: "Gears", unit: "", decimals: 0, type: "number" },
        { group: "drivetrain", key: "drive_type", labelKey: "inspect.paramDriveType", labelDef: "Drive Type", type: "enum", map: driveMap },
        { group: "drivetrain", key: "engine_type", labelKey: "inspect.paramEngineType", labelDef: "Engine Type", type: "enum", map: engineMap },
        { group: "drivetrain", key: "engine_inertia", labelKey: "inspect.paramInertia", labelDef: "Engine Inertia", unit: "", decimals: 1, type: "number" },
        { group: "control", key: "brake_decel", labelKey: "inspect.paramBrakeDecel", labelDef: "Brake Decel", unit: "", decimals: 2, type: "number" },
        { group: "control", key: "brake_bias", labelKey: "inspect.paramBrakeBias", labelDef: "Brake Bias", unit: "", decimals: 2, type: "number" },
        { group: "control", key: "steering_lock_deg", labelKey: "inspect.paramSteering", labelDef: "Steering Lock", unit: "°", decimals: 1, type: "number" },
        { group: "control", key: "traction_mult", labelKey: "inspect.paramTractionMult", labelDef: "Traction Mult", unit: "", decimals: 2, type: "number" },
        { group: "control", key: "traction_loss", labelKey: "inspect.paramTractionLoss", labelDef: "Traction Loss", unit: "", decimals: 2, type: "number" },
        { group: "control", key: "traction_bias", labelKey: "inspect.paramTractionBias", labelDef: "Traction Bias", unit: "", decimals: 2, type: "number" },
        { group: "control", key: "turn_mass", labelKey: "inspect.paramTurnMass", labelDef: "Turn Mass", unit: "", decimals: 1, type: "number" },
        { group: "control", key: "drag_mult", labelKey: "inspect.paramDragMult", labelDef: "Drag Mult", unit: "", decimals: 2, type: "number" },
        { group: "control", key: "center_of_mass", labelKey: "inspect.paramCenterOfMass", labelDef: "Center of Mass [X,Y,Z]", type: "vector" },
        { group: "suspension", key: "mass_kg", semantic: "weight", labelKey: "inspect.paramMass", labelDef: "Mass", unit: "kg", decimals: 0, type: "number" },
        { group: "suspension", key: "suspension_force", labelKey: "inspect.paramSuspensionForce", labelDef: "Suspension Force", unit: "", decimals: 2, type: "number" },
        { group: "suspension", key: "suspension_damping", labelKey: "inspect.paramSuspensionDamping", labelDef: "Suspension Damping", unit: "", decimals: 3, type: "number" },
        { group: "suspension", key: "suspension_lower_limit", labelKey: "inspect.paramSuspensionLower", labelDef: "Suspension Lower Limit", unit: "", decimals: 2, type: "number" },
        { group: "suspension", key: "submerged_percent", labelKey: "inspect.paramSubmerged", labelDef: "Submerged %", unit: "%", decimals: 0, type: "number" },
        { group: "misc", key: "monetary_value", semantic: "up", labelKey: "inspect.paramMonetary", labelDef: "Monetary Value", unit: "$", decimals: 0, type: "number", prefixUnit: true },
      ];

      const diffGroupDefs = [
        { key: "drivetrain", labelKey: "inspect.diffGroupDrivetrain", labelDef: "Power & Drivetrain" },
        { key: "control", labelKey: "inspect.diffGroupControl", labelDef: "Control & Braking" },
        { key: "suspension", labelKey: "inspect.diffGroupSuspension", labelDef: "Suspension & Mass" },
        { key: "misc", labelKey: "inspect.diffGroupMisc", labelDef: "Other Parameters" },
      ];

      let modifiedCount = 0;

      const buildDiffRow = (p) => {
        const curVal = h[p.key];
        const vanVal = vanillaH[p.key];
        if (curVal === undefined && vanVal === undefined) return "";

        const pName = window.t(p.labelKey, p.labelDef);
        let isModified = false;
        let vDisplay = "";
        let mDisplay = "";
        let deltaHtml = "";

        if (p.type === "number") {
          const cNum = (curVal !== undefined && !isNaN(curVal)) ? curVal : null;
          const vNum = (vanVal !== undefined && !isNaN(vanVal)) ? vanVal : null;
          if (cNum !== null && vNum !== null) {
            const diff = cNum - vNum;
            isModified = Math.abs(diff) > 0.0001;
            const u = p.unit ? ` ${p.unit}` : "";
            const vText = (p.prefixUnit ? p.unit : "") + (p.decimals === 0 ? Math.round(vNum) : vNum.toFixed(p.decimals)) + (!p.prefixUnit ? u : "");
            const mText = (p.prefixUnit ? p.unit : "") + (p.decimals === 0 ? Math.round(cNum) : cNum.toFixed(p.decimals)) + (!p.prefixUnit ? u : "");
            vDisplay = vText;
            mDisplay = isModified ? `<strong>${mText}</strong>` : mText;
            if (isModified) {
              const diffStr = (diff > 0 ? "+" : "") + (p.decimals === 0 ? Math.round(diff) : diff.toFixed(p.decimals)) + u;
              let tagCls = 'diff-tag-neutral';
              let tagTitle = window.t("inspect.diffNeutralTooltip", "Modified (no absolute better/worse for this parameter)");
              if (p.semantic === "up") {
                tagCls = diff > 0 ? 'diff-tag-up' : 'diff-tag-down';
                tagTitle = "";
              } else if (p.semantic === "weight") {
                tagCls = diff > 0 ? 'diff-tag-down' : 'diff-tag-up';
                tagTitle = "";
              }
              deltaHtml = `<span class="diff-tag ${tagCls}"${tagTitle ? ` title="${tagTitle}"` : ""}>${diffStr}</span>`;
            } else {
              deltaHtml = `<span class="diff-same-badge">${window.t("inspect.diffMatchesVanilla", "= Matches Vanilla")}</span>`;
            }
          } else {
            vDisplay = vNum !== null ? String(vNum) : "--";
            mDisplay = cNum !== null ? String(cNum) : "--";
            deltaHtml = "--";
          }
        } else if (p.type === "enum") {
          const vRaw = vanVal || "";
          const mRaw = curVal || "";
          const vText = p.map ? (p.map[vRaw] || vRaw) : vRaw;
          const mText = p.map ? (p.map[mRaw] || mRaw) : mRaw;
          isModified = (vRaw !== mRaw);
          vDisplay = vText;
          mDisplay = isModified ? `<strong>${mText}</strong>` : mText;
          if (isModified) {
            deltaHtml = `<span class="diff-tag diff-tag-modified">${vText} ➔ ${mText}</span>`;
          } else {
            deltaHtml = `<span class="diff-same-badge">${window.t("inspect.diffMatchesVanilla", "= Matches Vanilla")}</span>`;
          }
        } else if (p.type === "vector") {
          const vArr = Array.isArray(vanVal) ? vanVal : [];
          const mArr = Array.isArray(curVal) ? curVal : [];
          vDisplay = `[${vArr.join(", ")}]`;
          mDisplay = `[${mArr.join(", ")}]`;
          isModified = (vDisplay !== mDisplay);
          if (isModified) {
            mDisplay = `<strong>${mDisplay}</strong>`;
            deltaHtml = `<span class="diff-tag diff-tag-modified">${window.t("inspect.diffModified", "Modified")}</span>`;
          } else {
            deltaHtml = `<span class="diff-same-badge">${window.t("inspect.diffMatchesVanilla", "= Matches Vanilla")}</span>`;
          }
        }

        if (isModified) modifiedCount++;

        return `
          <tr class="${isModified ? 'diff-row-modified' : 'diff-row-match'}">
            <td>${pName}</td>
            <td>${vDisplay}</td>
            <td>${mDisplay}</td>
            <td>${deltaHtml}</td>
          </tr>
        `;
      };

      let rowsHtml = "";
      diffGroupDefs.forEach(group => {
        const groupRows = paramDefs
          .filter(p => p.group === group.key)
          .map(buildDiffRow)
          .filter(Boolean)
          .join("");
        if (!groupRows) return;
        rowsHtml += `<tr class="diff-group-row"><td colspan="4">${window.t(group.labelKey, group.labelDef)}</td></tr>${groupRows}`;
      });

      diffDisclosureHtml = `
        <details class="handling-diff-disclosure" id="handlingDiffDisclosure">
          <summary>
            <div class="diff-summary-left">
              <span class="diff-summary-icon">⚖️</span>
              <span class="diff-summary-title">${window.t("inspect.handlingDiffToggle", "Compare with Vanilla Handling")}</span>
            </div>
            <span class="badge badge-sm ${modifiedCount > 0 ? 'badge-diff-alert' : 'badge-diff-match'}">
              ${modifiedCount > 0
                ? window.t("inspect.diffCountBadge", "{0} parameters modified").replace("{0}", modifiedCount)
                : window.t("inspect.diffAllMatchBadge", "Identical to Vanilla")}
            </span>
          </summary>
          <div class="handling-diff-table-container">
            <table class="handling-diff-table">
              <thead>
                <tr>
                  <th>${window.t("inspect.diffColParam", "Parameter")}</th>
                  <th>${window.t("inspect.diffColVanilla", "Vanilla Baseline")}</th>
                  <th>${window.t("inspect.diffColMod", "Current Values")}</th>
                  <th>${window.t("inspect.diffColDelta", "Difference")}</th>
                </tr>
              </thead>
              <tbody>
                ${rowsHtml}
              </tbody>
            </table>
          </div>
        </details>
      `;
    }

    hDiv.innerHTML = `
      <div class="handling-stat-grid">
        <div class="stat-pill">
          <div class="val">${h.max_speed_kmh} <small>km/h</small></div>
          <div class="lbl">${window.t("inspect.handlingMaxSpeed", "Top Speed")}</div>
          ${renderDelta(h.max_speed_kmh, vanillaH ? vanillaH.max_speed_kmh : null, "km/h", 1, "up")}
        </div>
        <div class="stat-pill">
          <div class="val">${h.mass_kg} <small>kg</small></div>
          <div class="lbl">${window.t("inspect.handlingMass", "Vehicle Mass")}</div>
          ${renderDelta(h.mass_kg, vanillaH ? vanillaH.mass_kg : null, "kg", 0, "weight")}
        </div>
        <div class="stat-pill">
          <div class="val">${window.t("inspect.handlingGearsVal", "{0}-Speed").replace("{0}", h.gears)}</div>
          <div class="lbl">${window.t("inspect.handlingGears", "Gears")}</div>
          ${renderDelta(h.gears, vanillaH ? vanillaH.gears : null, "", 0)}
        </div>
        <div class="stat-pill">
          <div class="val">${h.acceleration}</div>
          <div class="lbl">${window.t("inspect.handlingAccel", "Acceleration Factor")}</div>
          ${renderDelta(h.acceleration, vanillaH ? vanillaH.acceleration : null, "", 1, "up")}
        </div>
        <div class="stat-pill">
          <div class="val">${h.brake_bias}</div>
          <div class="lbl">${window.t("inspect.handlingBrakeBias", "Brake Bias")}</div>
          ${renderDelta(h.brake_bias, vanillaH ? vanillaH.brake_bias : null, "", 2)}
        </div>
        <div class="stat-pill">
          <div class="val">${h.steering_lock_deg}°</div>
          <div class="lbl">${window.t("inspect.handlingSteering", "Steering Lock Angle")}</div>
          ${renderDelta(h.steering_lock_deg, vanillaH ? vanillaH.steering_lock_deg : null, "°", 1)}
        </div>
      </div>
      ${diffDisclosureHtml}
    `;
  } else {
    hBadge.textContent = window.t("inspect.handlingVanillaBadge", "Vanilla Physics");
    hDiv.innerHTML = `<p class="empty-hint" data-i18n="inspect.handlingEmpty">${window.t("inspect.handlingEmpty", "No custom handling provided. Using vanilla physics.")}</p>`;
  }
}

function renderCarcolsPreview(c) {
  const cDiv = document.getElementById("carcolsPalettes");
  const cBadge = document.getElementById("colorCountBadge");
  const typeBadge = document.getElementById("colorTypeBadge");
  const scheme2 = window.t("inspect.colorScheme2", "2-color");
  const scheme4 = window.t("inspect.colorScheme4", "4-color");

  const allPairs = (c && c.color_pairs) ? c.color_pairs.filter(Boolean) : [];
  // Merge byte-identical schemes (same color codes in the same order).
  const seen = new Set();
  const pairs = [];
  allPairs.forEach(pair => {
    const key = [pair.c1, pair.c2, pair.c3, pair.c4]
      .filter(x => x !== undefined && x !== null)
      .join("|");
    if (seen.has(key)) return;
    seen.add(key);
    pairs.push(pair);
  });

  if (pairs.length > 0) {
    const quadCount = pairs.filter(pair => pair.c3 !== undefined && pair.c4 !== undefined).length;
    const dualCount = pairs.length - quadCount;
    cBadge.textContent = window.t("inspect.colorCountBadge", "{0} Color Schemes").replace("{0}", pairs.length);
    if (typeBadge) {
      const bits = [];
      if (dualCount) bits.push(`${dualCount}×${scheme2}`);
      if (quadCount) bits.push(`${quadCount}×${scheme4}`);
      typeBadge.textContent = bits.join(" · ");
      typeBadge.style.display = bits.length ? "" : "none";
    }

    let swatchesHtml = '<div class="swatch-grid">';
    pairs.forEach((pair, idx) => {
      const isCar4 = pair.c3 !== undefined && pair.c4 !== undefined;
      const kindTag = `<em class="swatch-kind">${isCar4 ? scheme4 : scheme2}</em>`;
      if (isCar4) {
        const tooltip = window.t("inspect.colorQuadTooltip", "4-Color Scheme #{0}: Colors {1}, {2}, {3}, {4}")
          .replace("{0}", idx + 1).replace("{1}", pair.c1).replace("{2}", pair.c2).replace("{3}", pair.c3).replace("{4}", pair.c4);
        swatchesHtml += `
          <div class="color-pair-badge" title="${tooltip}">
            <div class="swatch-split swatch-quad">
              <div class="quad" style="background-color: ${pair.hex1}"></div>
              <div class="quad" style="background-color: ${pair.hex2}"></div>
              <div class="quad" style="background-color: ${pair.hex3}"></div>
              <div class="quad" style="background-color: ${pair.hex4}"></div>
            </div>
            <span class="swatch-ids">${pair.c1}, ${pair.c2}, ${pair.c3}, ${pair.c4} ${kindTag}</span>
          </div>
        `;
      } else {
        const tooltip = window.t("inspect.colorPairTooltip", "Scheme #{0}: Colors {1}, {2}")
          .replace("{0}", idx + 1).replace("{1}", pair.c1).replace("{2}", pair.c2);
        swatchesHtml += `
          <div class="color-pair-badge" title="${tooltip}">
            <div class="swatch-split">
              <div class="half" style="background-color: ${pair.hex1}"></div>
              <div class="half" style="background-color: ${pair.hex2}"></div>
            </div>
            <span class="swatch-ids">${pair.c1}, ${pair.c2} ${kindTag}</span>
          </div>
        `;
      }
    });
    swatchesHtml += '</div>';
    cDiv.innerHTML = swatchesHtml;
  } else {
    cBadge.textContent = window.t("inspect.colorCountBadgeDefault", "0 Schemes");
    if (typeBadge) {
      typeBadge.style.display = "none";
      typeBadge.textContent = "";
    }
    cDiv.innerHTML = `<p class="empty-hint" data-i18n="inspect.carcolsEmpty">${window.t("inspect.carcolsEmpty", "No custom colors provided. Using vanilla palette.")}</p>`;
  }
}

function renderCarmodsPreview(cmods, summary) {
  const tDiv = document.getElementById("tuningDetails");
  const tBadge = document.getElementById("tuningCountBadge");
  const parts = (cmods && cmods.parts) ? cmods.parts : [];
  const tuningDffs = (summary && summary.files && summary.files.tuning_dffs) ? summary.files.tuning_dffs : [];

  tBadge.textContent = window.t("inspect.tuningCountBadge", "{0} Parts").replace("{0}", parts.length + tuningDffs.length);

  if (parts.length > 0 || tuningDffs.length > 0) {
    let rowsHtml = '<div class="tuning-item-list">';
    const missingParts = (summary && summary.missing_shopping_parts) || [];
    parts.forEach(p => {
      const isMissing = missingParts.includes(p.part_name);
      const price = (p.shopping_price !== null && p.shopping_price !== undefined)
        ? p.shopping_price
        : (p.default_price || 100);
      const statusLabel = isMissing
        ? `<span class="tuning-status danger" title="${window.t("inspect.tuningDangerTooltip", "Unpriced in shopping.dat — entering a garage may crash; the installer can backfill this")}">${window.t("inspect.tuningDangerShort", "Unpriced")}</span>`
        : `<span class="tuning-status safe" title="${window.t("inspect.tuningSafe", "In shop (${0})").replace("{0}", price)}">$${price}</span>`;

      const catZh = p.name_cn || "";
      const catEn = p.name_en || (p.name_cn ? (p.name_cn.match(/\(([^)]+)\)/)?.[1] || p.name_cn) : (p.category || "Tuning"));
      const catDisplay = loc({ zh: catZh, en: catEn });

      // Model ID Pill Badge
      const hasId = p.model_id !== null && p.model_id !== undefined;
      const idArg = hasId ? p.model_id : 'null';
      const idPill = hasId
        ? `<span class="tuning-id-pill" onclick="openEditTuningIdModal('${p.part_name}', ${idArg})" title="${window.t("inspect.clickToEditId", "Click to edit part ID")}">ID ${p.model_id}</span>`
        : `<span class="tuning-id-pill unassigned" onclick="openEditTuningIdModal('${p.part_name}', null)" title="${window.t("inspect.clickToEditId", "Click to edit part ID")}">${window.t("inspect.unassignedId", "Unassigned")}</span>`;

      const deleteBtn = `<button type="button" class="btn-delete-part" onclick="confirmDeleteTuningPart('${p.part_name}')" title="${window.t("inspect.deletePartTitle", "Completely delete this part from carmods and veh_mods.ide")}"><svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M6.5 1h3a.5.5 0 0 1 .5.5V2h3.5a.5.5 0 0 1 0 1H13v10.5A1.5 1.5 0 0 1 11.5 15h-7A1.5 1.5 0 0 1 3 13.5V3H1.5a.5.5 0 0 1 0-1H5v-.5a.5.5 0 0 1 .5-.5zM4 3v10.5a.5.5 0 0 0 .5.5h7a.5.5 0 0 0 .5-.5V3H4zm2.5 2.5a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0v-6a.5.5 0 0 1 .5-.5zm3 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0v-6a.5.5 0 0 1 .5-.5z"/></svg></button>`;

      rowsHtml += `
        <div class="tuning-row${isMissing ? " is-risk" : ""}">
          <div class="tuning-part-info">
            <span class="tuning-part-name">${p.part_name}</span>
            <span class="tuning-part-cat">${catDisplay}</span>
          </div>
          <div class="tuning-part-actions">
            ${idPill}
            ${statusLabel}
            ${deleteBtn}
          </div>
        </div>
      `;
    });
    rowsHtml += '</div>';
    tDiv.innerHTML = rowsHtml;
  } else {
    tDiv.innerHTML = `<p class="empty-hint" data-i18n="inspect.tuningEmpty">${window.t("inspect.tuningEmpty", "No tuning parts detected for this vehicle.")}</p>`;
  }
}

function updateCardAfterSave(cardType, result) {
  if (cardType === "vehiclesIde") {
    const rawPreview = document.getElementById("vehiclesIdeRawPreview");
    if (rawPreview) rawPreview.textContent = result.raw || "--";
    renderConfigBadge("vehiclesIdeSourceBadge", "shadow");
    if (result.decomposed && result.decomposed.id) {
      const badgeEl = document.getElementById("targetIdBadge");
      if (badgeEl) {
        const cur = (badgeEl.textContent || "");
        const isAddon = cur.indexOf("Addon") !== -1 || (currentInspectorDetail && currentInspectorDetail.is_addon);
        const prefix = isAddon
          ? window.t("inspect.targetIdBadgePrefixAddon", "Addon ID: ")
          : window.t("inspect.targetIdBadgePrefix", "Vanilla ID: ");
        badgeEl.textContent = `${prefix}${result.decomposed.id}`;
      }
    }
  } else if (cardType === "handling") {
    const rawPreview = document.getElementById("handlingRawPreview");
    if (rawPreview) rawPreview.textContent = result.raw || "--";
    renderConfigBadge("handlingSourceBadge", "shadow");
    renderHandlingPreview(result.decomposed, currentVanillaHandling, currentIsAddonVehicle);
  } else if (cardType === "carcols") {
    const rawPreview = document.getElementById("carcolsRawPreview");
    if (rawPreview) rawPreview.textContent = result.raw || "--";
    renderConfigBadge("carcolsSourceBadge", "shadow");
    renderCarcolsPreview(result.decomposed);
  } else if (cardType === "carmods") {
    const rawPreview = document.getElementById("carmodsRawPreview");
    if (rawPreview) rawPreview.textContent = result.raw || "--";
    renderConfigBadge("carmodsSourceBadge", "shadow");
    renderCarmodsPreview(result.decomposed, activeMod);
  }
}

async function saveCardConfig(cardType) {
  const model = activeMod ? (activeMod.target_model || "") : "";
  if (!model) {
    showToast(window.t("inspect.targetUnrecognized", "Unrecognized"), "warning");
    return;
  }

  const typeConfigMap = {
    vehiclesIde: {
      type: "vehicles_ide",
      inputId: "inputVehiclesIdeRaw",
      btnId: "btnSaveVehiclesIde",
      label: "vehicles.ide"
    },
    handling: {
      type: "handling",
      inputId: "inputHandlingRaw",
      btnId: "btnSaveHandling",
      label: "handling.cfg"
    },
    carcols: {
      type: "carcols",
      inputId: "inputCarcolsRaw",
      btnId: "btnSaveCarcols",
      label: "carcols.dat"
    },
    carmods: {
      type: "carmods",
      inputId: "inputCarmodsRaw",
      btnId: "btnSaveCarmods",
      label: "carmods.dat"
    }
  };

  const cfg = typeConfigMap[cardType];
  if (!cfg) return;

  const inputElem = document.getElementById(cfg.inputId);
  const saveBtn = document.getElementById(cfg.btnId);
  if (!inputElem) return;

  const rawLine = inputElem.value.trim();
  if (!rawLine) {
    showToast(loc({ en: "Configuration line cannot be empty" }), "warning");
    return;
  }

  const origText = saveBtn ? saveBtn.textContent : "";
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = t("common.saving");
  }

  try {
    const res = await fetch("/api/vehicle/update-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model,
        config_type: cfg.type,
        raw_line: rawLine
      })
    });
    const result = await res.json();
    if (result.success) {
      showToast(window.t("toast.configSaved", "{0} configuration saved successfully!").replace("{0}", cfg.label), "success");
      updateCardAfterSave(cardType, result);
      toggleCardEdit(cardType, false);

      if (activeMod) {
        if (!activeMod.active_configs) activeMod.active_configs = {};
        activeMod.active_configs[cfg.type] = {
          raw: result.raw,
          source: "shadow",
          decomposed: result.decomposed
        };
      }
    } else {
      const errMsg = result.error || "Unknown error";
      showToast((window.t("toast.configSaveFailed", "Failed to save {0}: ").replace("{0}", cfg.label)) + errMsg, "error");
    }
  } catch (err) {
    showToast(window.t("toast.networkError", "Network error: ") + err.message, "error");
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = origText;
    }
  }
}

// ---------------- Tuning Part ID Quick Editor & Deletion ----------------

let currentEditingPartName = "";
let tuningIdCheckTimer = null;

function setupTuningPartControls() {
  const modal = document.getElementById("tuningIdModal");
  const closeBtn = document.getElementById("closeTuningIdModal");
  const cancelBtn = document.getElementById("cancelTuningIdBtn");
  const saveBtn = document.getElementById("saveTuningIdBtn");
  const inputId = document.getElementById("inputTuningNewId");

  const hideModal = () => {
    if (modal) modal.classList.remove("active");
  };

  if (closeBtn) closeBtn.addEventListener("click", hideModal);
  if (cancelBtn) cancelBtn.addEventListener("click", hideModal);
  if (saveBtn) saveBtn.addEventListener("click", saveTuningId);

  if (inputId) {
    inputId.addEventListener("input", (e) => {
      clearTimeout(tuningIdCheckTimer);
      const val = e.target.value.trim();
      const statusDiv = document.getElementById("tuningIdCheckStatus");
      if (!val) {
        if (statusDiv) statusDiv.innerHTML = "";
        return;
      }
      const num = parseInt(val, 10);
      if (isNaN(num) || num < 400 || num > 65535) {
        if (statusDiv) {
          statusDiv.innerHTML = `<span style="color:#f85149;">${loc({ en: "⚠️ ID must be within 400 - 65535" })}</span>`;
        }
        return;
      }

      if (statusDiv) {
        statusDiv.innerHTML = `<span style="color:var(--text-muted);">${window.t("inspect.modalEditIdChecking", "Checking ID availability...")}</span>`;
      }

      tuningIdCheckTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/ids/check?id=${num}`);
          const data = await res.json();
          if (data.success && data.result) {
            const r = data.result;
            if (r.is_free) {
              statusDiv.innerHTML = `<span style="color:var(--accent-emerald); font-weight:600;">${window.t("inspect.modalEditIdFree", "✔️ ID available; no conflicts found")}</span>`;
            } else {
              const occName = (r.name || "").toLowerCase();
              if (occName === currentEditingPartName.toLowerCase()) {
                statusDiv.innerHTML = `<span style="color:var(--accent-cyan);">${loc({ en: "ℹ️ Already assigned to this part" })}</span>`;
              } else {
                statusDiv.innerHTML = `<span style="color:#f85149; font-weight:600;">${window.t("inspect.modalEditIdConflict", "❌ ID is occupied: ")}<strong>${r.name}</strong> (${r.file || r.source})</span>`;
              }
            }
          }
        } catch (err) {
          if (statusDiv) statusDiv.innerHTML = "";
        }
      }, 250);
    });

    inputId.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        saveTuningId();
      }
    });
  }
}

function openEditTuningIdModal(partName, currentId) {
  currentEditingPartName = partName;
  const modal = document.getElementById("tuningIdModal");
  const nameSpan = document.getElementById("editTuningPartName");
  const inputId = document.getElementById("inputTuningNewId");
  const statusDiv = document.getElementById("tuningIdCheckStatus");

  if (nameSpan) nameSpan.textContent = partName;
  if (inputId) {
    inputId.value = (currentId !== null && currentId !== undefined) ? currentId : "";
  }
  if (statusDiv) statusDiv.innerHTML = "";

  if (modal) modal.classList.add("active");
  if (inputId) {
    setTimeout(() => {
      inputId.focus();
      inputId.select();
    }, 100);
  }
}

async function saveTuningId() {
  const model = activeMod ? (activeMod.target_model || "") : "";
  if (!model) {
    showToast(window.t("inspect.targetUnrecognized", "Unrecognized"), "warning");
    return;
  }
  if (!currentEditingPartName) return;

  const inputId = document.getElementById("inputTuningNewId");
  const newId = parseInt(inputId ? inputId.value.trim() : "", 10);
  if (isNaN(newId) || newId < 400 || newId > 65535) {
    showToast(loc({ en: "Please enter a valid Model ID (400 - 65535)" }), "warning");
    return;
  }

  const saveBtn = document.getElementById("saveTuningIdBtn");
  const origText = saveBtn ? saveBtn.textContent : "";
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = t("common.saving");
  }

  try {
    const res = await fetch("/api/vehicle/update-tuning-id", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model,
        part_name: currentEditingPartName,
        new_id: newId
      })
    });
    const result = await res.json();
    if (result.success) {
      showToast(window.t("toast.tuningIdUpdated", "Successfully updated part [{0}] ID to {1}!").replace("{0}", currentEditingPartName).replace("{1}", newId), "success");
      const modal = document.getElementById("tuningIdModal");
      if (modal) modal.classList.remove("active");

      // Update activeConfigs and UI in place
      if (activeMod && result.active_configs) {
        activeMod.active_configs = result.active_configs;
        const cmods = result.active_configs.carmods;
        const cDecomp = cmods ? cmods.decomposed : null;
        renderCarmodsPreview(cDecomp, activeMod);
        const rawPreview = document.getElementById("carmodsRawPreview");
        if (rawPreview && cmods) rawPreview.textContent = cmods.raw || "--";
        renderConfigBadge("carmodsSourceBadge", "shadow");
      }
    } else {
      const errMsg = result.error || "Unknown error";
      showToast(window.t("toast.tuningIdUpdateFailed", "Failed to update part ID: ") + errMsg, "error");
    }
  } catch (err) {
    showToast(window.t("toast.networkError", "Network error: ") + err.message, "error");
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = origText;
    }
  }
}

async function confirmDeleteTuningPart(partName) {
  const model = activeMod ? (activeMod.target_model || "") : "";
  if (!model) {
    showToast(window.t("inspect.targetUnrecognized", "Unrecognized"), "warning");
    return;
  }

  const confirmMsg = window.t("inspect.deletePartConfirm", "Are you sure you want to completely delete part [{0}] from this vehicle?\n\nThis will remove it from carmods.dat, veh_mods.ide, and unlink mirror parts.").replace("{0}", partName);

  if (!(await showAppConfirm(confirmMsg))) return;

  try {
    const res = await fetch("/api/vehicle/delete-tuning-part", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model,
        part_name: partName
      })
    });
    const result = await res.json();
    if (result.success) {
      showToast(window.t("toast.tuningPartDeleted", "Successfully deleted tuning part [{0}]!").replace("{0}", partName), "success");

      // Update activeConfigs and UI in place
      if (activeMod && result.active_configs) {
        activeMod.active_configs = result.active_configs;
        const cmods = result.active_configs.carmods;
        const cDecomp = cmods ? cmods.decomposed : null;
        renderCarmodsPreview(cDecomp, activeMod);
        const rawPreview = document.getElementById("carmodsRawPreview");
        if (rawPreview && cmods) rawPreview.textContent = cmods.raw || "--";
        const inputCarmods = document.getElementById("inputCarmodsRaw");
        if (inputCarmods && cmods) inputCarmods.value = cmods.raw || "";
        renderConfigBadge("carmodsSourceBadge", "shadow");
      }
    } else {
      const errMsg = result.error || "Unknown error";
      showToast(window.t("toast.tuningPartDeleteFailed", "Failed to delete part: ") + errMsg, "error");
    }
  } catch (err) {
    showToast(window.t("toast.networkError", "Network error: ") + err.message, "error");
  }
}

window.openEditTuningIdModal = openEditTuningIdModal;
window.confirmDeleteTuningPart = confirmDeleteTuningPart;

let currentInspectorDetail = null;
let currentInspectorSummary = null;

function renderInspectorData(detail, summary) {
  currentInspectorDetail = detail;
  currentInspectorSummary = summary;

  // Reset all editor toggles to preview state on mod switch
  resetAllCardEditors();

  const initialModel = detail.target_model || (detail.target_models && detail.target_models[0]) || "";
  renderInspectorVehicleView(initialModel);

  if (window.SourceDocuments) window.SourceDocuments.render(detail);
  else document.getElementById("rawReadmeContent").textContent = detail.raw_text_summary || window.t("inspect.noReadmeFound", "(No Readme or txt documentation found)");
}

function renderInspectorVehicleView(model) {
  if (!currentInspectorDetail) return;
  const detail = currentInspectorDetail;
  const summary = currentInspectorSummary;
  const modelClean = (model || "").trim().toLowerCase();
  if (activeMod) {
    activeMod.target_model = modelClean;
  }

  // Multi-vehicle switcher pill tabs
  const switcherBar = document.getElementById("inspectorMultiVehicleBar");
  const switcherTabs = document.getElementById("inspectorVehicleTabs");
  const models = (detail.target_models && detail.target_models.length > 0) ? detail.target_models : (detail.target_model ? [detail.target_model] : []);

  if (switcherBar && switcherTabs) {
    if (models.length > 1) {
      switcherBar.style.display = "flex";
      switcherTabs.innerHTML = "";
      models.forEach(m => {
        const mLower = m.toLowerCase();
        const vMatch = vanillaVehicles.find(v => v.model.toLowerCase() === mLower);
        const tvMatchPill = (detail.target_vehicles || []).find(tv => tv && tv.model && tv.model.toLowerCase() === mLower);
        const vName = (tvMatchPill && tvMatchPill.name) || (vMatch ? vMatch.name : m.toUpperCase());
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `switcher-tab-btn ${mLower === modelClean ? 'active' : ''}`;
        btn.innerHTML = `<span>🚗 ${vName}</span> <small style="opacity:0.75;">(${m.toUpperCase()})</small>`;
        btn.addEventListener("click", () => {
          renderInspectorVehicleView(mLower);
          showToast(window.t("inspect.switchCarSuccess", "Switched to live configs for [{0}]").replace("{0}", m.toUpperCase()), "info");
        });
        switcherTabs.appendChild(btn);
      });
    } else {
      switcherBar.style.display = "none";
    }
  }

  // Active configurations for this model
  let activeConfigs = {};
  if (detail.all_active_configs && detail.all_active_configs[modelClean]) {
    activeConfigs = detail.all_active_configs[modelClean];
  } else if (detail.active_configs && (!detail.target_model || detail.target_model.toLowerCase() === modelClean)) {
    activeConfigs = detail.active_configs;
  }

  // 1. Target vehicle card & vehicles.ide
  const vMatch = vanillaVehicles.find(v => v.model.toLowerCase() === modelClean);
  const tvMatch = (detail.target_vehicles || []).find(tv => tv && tv.model && tv.model.toLowerCase() === modelClean);
  const v = vMatch || tvMatch || detail.target_vanilla;

  const typeMeta = vehicleTypeMeta((tvMatch && tvMatch.type) || (v && v.type) || "car");
  const typeIconEl = document.getElementById("targetVehicleTypeIcon");
  if (typeIconEl) {
    typeIconEl.className = `mod-card-type inspector-type-tile ${typeMeta.cls}`;
    typeIconEl.innerHTML = typeMeta.icon;
    const typeLabel = loc(typeMeta.label);
    typeIconEl.title = typeLabel;
    typeIconEl.setAttribute("aria-label", typeLabel);
    typeIconEl.style.display = "";
  }

  const ideCfg = activeConfigs.vehicles_ide;
  const ideDecomp = ideCfg ? ideCfg.decomposed : null;
  const targetId = (ideDecomp && ideDecomp.id) || (tvMatch && tvMatch.id) || (v ? v.id : "--");

  const isAddonVehicle = Boolean(
    (summary && (summary.is_addon || summary.mod_type === "addon")) ||
    (detail && detail.is_addon) ||
    (v && v.is_addon)
  );
  const idPrefix = isAddonVehicle
    ? window.t("inspect.targetIdBadgePrefixAddon", "Addon ID: ")
    : window.t("inspect.targetIdBadgePrefix", "Vanilla ID: ");

  document.getElementById("targetIdBadge").textContent = (targetId && targetId !== "--") ? `${idPrefix}${targetId}` : (t("common.unknown"));

  const cardTitleEl = document.querySelector("#cardVehiclesIde .card-header h3");
  if (cardTitleEl) {
    if (isAddonVehicle) {
      cardTitleEl.textContent = loc({ en: "🎯 Target Addon Vehicle (vehicles.ide)" });
    } else {
      cardTitleEl.textContent = loc({ en: "🎯 Target Replaced Vehicle (vehicles.ide)" });
    }
  }

  document.getElementById("targetModelCode").textContent = modelClean ? modelClean.toUpperCase() : window.t("inspect.targetUnrecognized", "Unrecognized");

  let displayName = v ? v.name : (modelClean ? modelClean.toUpperCase() : "--");
  activeFxtKey = "";
  activeFxtName = "";
  if (detail.parsed && detail.parsed.fxt && detail.parsed.fxt.length > 0) {
    // Match this vehicle's own entry: model code or its IDE game name.
    // The old fxt[0] fallback leaked other cars' names into multi-car packs.
    const ideGame = (ideCfg && ideCfg.decomposed && ideCfg.decomposed.game_name)
      ? String(ideCfg.decomposed.game_name).toLowerCase() : "";
    const fxtKeys = [modelClean];
    if (ideGame && !fxtKeys.includes(ideGame)) fxtKeys.push(ideGame);
    const fxtMatched = detail.parsed.fxt.find(f => f && f.key && fxtKeys.includes(f.key.toLowerCase()));
    const useEntry = fxtMatched || (models.length <= 1 ? detail.parsed.fxt[0] : null);
    if (useEntry && useEntry.name) {
      displayName += ` [FXT: ${useEntry.name}]`;
      activeFxtKey = useEntry.key || "";
      activeFxtName = useEntry.name || "";
    }
  }
  document.getElementById("targetVanillaName").textContent = displayName;
  const shopRaw = v && v.shop ? String(v.shop).trim() : "";
  const shopWrap = document.getElementById("identityShopWrap");
  const shopEl = document.getElementById("targetShopName");
  const shopIsNone = !shopRaw || shopRaw.toLowerCase() === "none";
  if (shopWrap) {
    if (shopIsNone) {
      shopWrap.hidden = true;
      if (shopEl) shopEl.textContent = "";
    } else {
      shopWrap.hidden = false;
      if (shopEl) shopEl.textContent = shopRaw.toUpperCase();
    }
  } else if (shopEl) {
    shopEl.textContent = shopIsNone ? window.t("inspect.targetNoneShop", "None") : shopRaw.toUpperCase();
  }

  let carDff = null;
  if (detail.files && detail.files.dff_files) {
    carDff = detail.files.dff_files.find(f => f.name.toLowerCase().startsWith(modelClean)) || detail.files.dff_files[0];
  }
  document.getElementById("targetDffSize").textContent = carDff ? `${(carDff.size / 1024).toFixed(1)} KB` : (loc({ en: "No DFF" }));

  // vehicles.ide line & source (compat: parsed.ide decomposed dicts OR legacy raw strings)
  let modIdeLine = "";
  const ideArr = (detail.parsed && (detail.parsed.vehicles_ide || detail.parsed.ide)) || [];
  if (ideArr && ideArr.length) {
    const foundIde = ideArr.find(line => {
      if (!line) return false;
      if (typeof line === "string") {
        const parts = line.split(",");
        return parts.length >= 2 && parts[1].trim().toLowerCase() === modelClean;
      }
      const mm = (line.model_name || line.model || "").toLowerCase();
      if (mm) return mm === modelClean;
      const raw = line.raw || "";
      const parts = String(raw).split(",");
      return parts.length >= 2 && parts[1].trim().toLowerCase() === modelClean;
    });
    if (foundIde) modIdeLine = (typeof foundIde === "string") ? foundIde : (foundIde.raw || "");
    else if (models.length <= 1 && ideArr[0]) {
      const first = ideArr[0];
      modIdeLine = (typeof first === "string") ? first : (first.raw || "");
    }
  }
  const ideRaw = ideCfg ? ideCfg.raw : modIdeLine;
  const ideSource = ideCfg ? ideCfg.source : (ideRaw ? "mod" : "");
  document.getElementById("vehiclesIdeRawPreview").textContent = ideRaw || "--";
  renderConfigBadge("vehiclesIdeSourceBadge", ideSource);
  document.getElementById("inputVehiclesIdeRaw").value = ideRaw || "";

  // 2. Handling Card (supports shared handling ID, e.g. 5 cars share PREMIER2)
  let modHandling = null;
  if (detail.parsed && detail.parsed.handling) {
    modHandling = detail.parsed.handling.find(h => h && h.identifier && h.identifier.toLowerCase() === modelClean);
    if (!modHandling) {
      // Resolve via this model's own vehicles.ide handling_id
      try {
        const ideArr2 = (detail.parsed.vehicles_ide || detail.parsed.ide) || [];
        let hid = "";
        const ideHit = ideArr2.find(x => {
          if (!x) return false;
          if (typeof x === "string") return false;
          return ((x.model_name || x.model || "").toLowerCase() === modelClean);
        });
        if (ideHit && ideHit.handling_id) hid = String(ideHit.handling_id).toLowerCase();
        else if (ideCfg && ideCfg.decomposed && ideCfg.decomposed.handling_id) hid = String(ideCfg.decomposed.handling_id).toLowerCase();
        if (hid) modHandling = detail.parsed.handling.find(h => h && h.identifier && h.identifier.toLowerCase() === hid) || null;
      } catch (e) {}
    }
    if (!modHandling && models.length <= 1 && detail.parsed.handling[0]) {
      modHandling = detail.parsed.handling[0];
    }
  }
  const vhCfg = activeConfigs.vanilla_handling;
  currentVanillaHandling = (vhCfg && vhCfg.decomposed) ? vhCfg.decomposed : null;
  currentIsAddonVehicle = isAddonVehicle;

  const hCfg = activeConfigs.handling;
  const hDecomp = (hCfg && hCfg.decomposed) ? hCfg.decomposed : modHandling;
  const hRaw = hCfg ? hCfg.raw : (hDecomp ? hDecomp.raw : "");
  const hSource = hCfg ? hCfg.source : (hRaw ? "mod" : "");
  renderHandlingPreview(hDecomp, currentVanillaHandling, currentIsAddonVehicle);
  document.getElementById("handlingRawPreview").textContent = hRaw || "--";
  renderConfigBadge("handlingSourceBadge", hSource);
  document.getElementById("inputHandlingRaw").value = hRaw || "";

  // 3. Carcols Card
  let modCarcols = null;
  if (detail.parsed && detail.parsed.carcols) {
    modCarcols = detail.parsed.carcols.find(c => c && c.model_name && c.model_name.toLowerCase() === modelClean);
    if (!modCarcols && models.length <= 1 && detail.parsed.carcols[0]) {
      modCarcols = detail.parsed.carcols[0];
    }
  }
  const cCfg = activeConfigs.carcols;
  const cDecomp = (cCfg && cCfg.decomposed) ? cCfg.decomposed : modCarcols;
  const cRaw = cCfg ? cCfg.raw : (cDecomp ? cDecomp.raw : "");
  const cSource = cCfg ? cCfg.source : (cRaw ? "mod" : "");
  renderCarcolsPreview(cDecomp);
  document.getElementById("carcolsRawPreview").textContent = cRaw || "--";
  renderConfigBadge("carcolsSourceBadge", cSource);
  document.getElementById("inputCarcolsRaw").value = cRaw || "";

  // 4. Carmods Card (compat: decomposed uses model_name, legacy uses model)
  let modCarmods = null;
  if (detail.parsed && detail.parsed.carmods) {
    modCarmods = detail.parsed.carmods.find(m => m && ((m.model || m.model_name || "").toLowerCase() === modelClean));
    if (!modCarmods && models.length <= 1 && detail.parsed.carmods[0]) {
      modCarmods = detail.parsed.carmods[0];
    }
  }
  const mCfg = activeConfigs.carmods;
  const mDecomp = (mCfg && mCfg.decomposed) ? mCfg.decomposed : modCarmods;
  const mRaw = mCfg ? mCfg.raw : (mDecomp ? mDecomp.raw : "");
  const mSource = mCfg ? mCfg.source : (mRaw ? "mod" : "");
  renderCarmodsPreview(mDecomp, summary);
  document.getElementById("carmodsRawPreview").textContent = mRaw || "--";
  renderConfigBadge("carmodsSourceBadge", mSource);
  document.getElementById("inputCarmodsRaw").value = mRaw || "";

  // 5. Load live FLA details
  loadFlaDetail(modelClean);
}


// ---------------- Special Features & Audio Handlers (FLA92) ----------------

let currentInspectedModel = "";
let currentFlaDetail = null;
let flaRequestSeq = 0;
let activeFxtKey = "";
let activeFxtName = "";

function populateSpecialFeatureTargets(targets) {
  // Targets cached in appStatus.special_targets
}

function getModFlaPreset(modelClean) {
  // Mod-folder preset from /api/mod-detail (preferred) or raw parsed fallback.
  // Returns {audio_raw, special_raw} or nulls.
  try {
    const ml = (modelClean || "").toLowerCase();
    const d = currentInspectorDetail;
    if (d && d.mod_fla && d.mod_fla[ml]) return d.mod_fla[ml];
    if (d && d.parsed) {
      let aud = null, sp = null;
      const audLines = d.parsed.audio_lines || d.parsed.vehicle_audio || [];
      for (const ln of audLines) {
        const s = (typeof ln === "string" ? ln : (ln && ln.raw) || "").trim();
        if (!s) continue;
        const parts = s.split(/\s+/);
        if (parts[0] && parts[0].toLowerCase() === ml) { aud = s; break; }
      }
      const spLines = d.parsed.special_features || [];
      for (const ln of spLines) {
        const s = (typeof ln === "string" ? ln : (ln && ln.raw) || "").trim();
        if (!s) continue;
        const parts = s.split(/\s+/);
        if (parts.length >= 2 && parts[0].toLowerCase() === ml) { sp = s; break; }
      }
      if (aud || sp) return { audio_raw: aud, special_raw: sp };
    }
  } catch (e) {}
  return { audio_raw: null, special_raw: null };
}

async function loadFlaDetail(model) {
  currentInspectedModel = (model || "").trim().toLowerCase();
  if (!currentInspectedModel) {
    resetFlaDisplay();
    return;
  }
  const mySeq = ++flaRequestSeq;
  const myModel = currentInspectedModel;

  // Set loading state AND clear stale per-model data (prevents previous
  // vehicle's phoenixr-style line lingering when switching to creado).
  const spBox = document.getElementById("specialFeatureStatusBox");
  const audBox = document.getElementById("audioStatusBox");
  if (spBox) spBox.className = "fla-status-box";
  if (audBox) audBox.className = "fla-status-box";

  const spText = document.getElementById("specialStatusText");
  const audText = document.getElementById("audioStatusText");
  if (spText) spText.textContent = window.t("inspect.flaReadingFile", "Reading configuration...");
  if (audText) audText.textContent = window.t("inspect.flaReadingFile", "Reading configuration...");
  const spRawLoading = document.getElementById("specialRawCode");
  const audRawLoading = document.getElementById("audioCurrentRawCode");
  if (spRawLoading) spRawLoading.textContent = "...";
  if (audRawLoading) audRawLoading.textContent = "...";
  const spBadgeLoading = document.getElementById("specialFeatureBadge");
  const audBadgeLoading = document.getElementById("audioStatusBadge");
  if (spBadgeLoading) { spBadgeLoading.textContent = "..."; spBadgeLoading.className = "badge"; }
  if (audBadgeLoading) { audBadgeLoading.textContent = "..."; audBadgeLoading.className = "badge"; }
  const audInputLoading = document.getElementById("audioRawInput");
  const spInputLoading = document.getElementById("specialFeatureCustomInput");
  if (audInputLoading) audInputLoading.value = "";
  if (spInputLoading) spInputLoading.value = "";

  try {
    const res = await fetch(`/api/fla/detail?model=${encodeURIComponent(myModel)}`);
    if (mySeq !== flaRequestSeq || myModel !== currentInspectedModel) return; // stale race, drop
    const data = await res.json();
    if (mySeq !== flaRequestSeq || myModel !== currentInspectedModel) return;
    if (data.success && data.detail) {
      // Attach mod preset so render can fall back when global data/ has no record
      // (common for addon new models not yet merged into data/).
      data.detail.mod_preset = getModFlaPreset(myModel);
      currentFlaDetail = data.detail;
      renderFlaDetail(data.detail);
    } else {
      // API returned failure: still try mod preset before blanking
      const preset = getModFlaPreset(myModel);
      if (preset && (preset.audio_raw || preset.special_raw)) {
        currentFlaDetail = { model: myModel, special: { exists: false }, audio: { exists: false }, mod_preset: preset };
        renderFlaDetail(currentFlaDetail);
      } else {
        resetFlaDisplay();
      }
    }
  } catch (err) {
    if (mySeq !== flaRequestSeq || myModel !== currentInspectedModel) return;
    console.error("Failed to load FLA status:", err);
    const preset = getModFlaPreset(myModel);
    if (preset && (preset.audio_raw || preset.special_raw)) {
      currentFlaDetail = { model: myModel, special: { exists: false }, audio: { exists: false }, mod_preset: preset };
      renderFlaDetail(currentFlaDetail);
      return;
    }
    resetFlaDisplay();
    const spText2 = document.getElementById("specialStatusText");
    const audText2 = document.getElementById("audioStatusText");
    if (spText2) spText2.textContent = loc({ en: "Failed to read special feature config" });
    if (audText2) audText2.textContent = loc({ en: "Failed to read audio config" });
  }
}

function renderFlaDetail(detail) {
  const model = detail.model || currentInspectedModel;
  if ((model || "").toLowerCase() !== (currentInspectedModel || "").toLowerCase()) return; // drop stale race
  // 1. Special Feature Rendering
  const spStatusBox = document.getElementById("specialFeatureStatusBox");
  const spDot = document.getElementById("specialDot");
  const spStatusText = document.getElementById("specialStatusText");
  const spRawCode = document.getElementById("specialRawCode");
  const spBadge = document.getElementById("specialFeatureBadge");
  const spInput = document.getElementById("specialFeatureCustomInput");

  // Highlight matched preset chip
  document.querySelectorAll("#specialPresetChips .chip-btn").forEach(btn => {
    btn.classList.remove("selected");
    if (detail.special && detail.special.target && btn.getAttribute("data-target") === detail.special.target.toLowerCase()) {
      btn.classList.add("selected");
    }
  });

  if (detail.special && detail.special.exists) {
    spStatusBox.className = "fla-status-box active";
    spDot.className = "status-indicator-dot active";
    const label = detail.special.target || (window.I18N && typeof window.I18N.pick === "function"
      ? (window.I18N.pick(detail.special, "label") || detail.special.label)
      : (detail.special.label || detail.special.target));
    
    if (detail.special.is_native) {
      spStatusText.innerHTML = `${window.t("inspect.specialNativeActive", "Built-in Special Feature: ")}<strong style="color:var(--accent-cyan);">${label}</strong> <span style="font-size:12px; color:var(--text-muted);">(${window.t("inspect.specialNativeDesc", "Built into the game; no extra entry in model_special_features.dat is needed.")})</span>`;
      spBadge.textContent = window.t("inspect.flaSpecialNative", "Native: {0}").replace("{0}", detail.special.target);
      spBadge.className = "badge badge-success";
    } else {
      spStatusText.innerHTML = `${window.t("inspect.specialActive", "Active Special Feature: ")}<strong style="color:var(--accent-cyan);">${label}</strong>`;
      spBadge.textContent = window.t("inspect.flaSpecialConfigured", "Active: {0}").replace("{0}", detail.special.target);
      spBadge.className = "badge badge-success";
    }
    if (detail.special.is_native) {
        spRawCode.textContent = (window.I18N ? window.I18N.pick(detail.special, "raw_line") : "") || loc({ en: `# (GTA:SA Native Archetype) ${model}` });
      } else {
        spRawCode.textContent = detail.special.raw_line || `${model} ${detail.special.target}`;
      }
    spInput.value = detail.special.target;
  } else {
    const modSp = detail.mod_preset && detail.mod_preset.special_raw;
    if (modSp) {
      spStatusBox.className = "fla-status-box active";
      spDot.className = "status-indicator-dot active";
      const parts = modSp.split(/\s+/);
      const tgt = (parts[1] || "").toLowerCase();
      spStatusText.innerHTML = `${window.t("inspect.specialActive", "Active Special Feature: ")}<strong style="color:var(--accent-cyan);">${tgt || modSp}</strong> <span style="font-size:11px; color:var(--accent-cyan);">(${window.t("inspect.sourceMod", "Mod Preset")})</span>`;
      spRawCode.textContent = modSp;
      spBadge.textContent = `${window.t("inspect.sourceMod", "Mod Preset")}: ${tgt || ""}`.trim();
      spBadge.className = "badge badge-info";
      document.querySelectorAll("#specialPresetChips .chip-btn").forEach(btn => {
        btn.classList.toggle("selected", !!tgt && btn.getAttribute("data-target") === tgt);
      });
      spInput.value = tgt || "";
    } else {
      spStatusBox.className = "fla-status-box inactive";
      spDot.className = "status-indicator-dot inactive";
      spStatusText.textContent = window.t("inspect.specialNotActive", "No custom special features; using this model’s built-in behavior.");
      spRawCode.textContent = window.t("inspect.specialNoRecord", "(No record in data/model_special_features.dat for this model)");
      spBadge.textContent = window.t("inspect.flaSpecialNotConfigured", "Not Configured");
      spBadge.className = "badge";
      spInput.value = "";
    }
  }

  // 2. Audio Settings Rendering
  const audStatusBox = document.getElementById("audioStatusBox");
  const audDot = document.getElementById("audioDot");
  const audStatusText = document.getElementById("audioStatusText");
  const audCurrentRawCode = document.getElementById("audioCurrentRawCode");
  const audBadge = document.getElementById("audioStatusBadge");
  const audInput = document.getElementById("audioRawInput");
  const audSelect = document.getElementById("soundPresetSelect");

  if (detail.audio && detail.audio.exists) {
    audStatusBox.className = "fla-status-box active";
    audDot.className = "status-indicator-dot active";
    const isVanilla = Boolean(detail.audio.is_vanilla);
    const isModified = Boolean(detail.audio.is_modified);
    const modAudFallback = detail.mod_preset && detail.mod_preset.audio_raw;
    let audDisplayRaw = detail.audio.raw_line;

    if (isVanilla && !isModified && modAudFallback) {
      // The deployed line is still the untouched vanilla baseline: surface
      // the mod's own audio preset instead of claiming "vanilla default".
      audStatusText.innerHTML = `${window.t("inspect.audioActive", "Custom audio configured")} <span style="font-size:11px; color:var(--accent-cyan);">(${window.t("inspect.sourceMod", "Mod Preset")})</span>`;
      audBadge.textContent = window.t("inspect.sourceMod", "Mod Preset");
      audBadge.className = "badge badge-info";
      audDisplayRaw = modAudFallback;
      if (audSelect) audSelect.value = "";
    } else if (isVanilla && !isModified) {
      audStatusText.innerHTML = window.t("inspect.audioNotActive", "Using default vehicle audio");
      audBadge.textContent = window.t("inspect.flaAudioVanilla", "Vanilla Audio");
      audBadge.className = "badge";
      if (audSelect) audSelect.value = "default";
    } else {
      const matchedLabel = (window.I18N && typeof window.I18N.pick === "function")
        ? (window.I18N.pick(detail.audio, "matched_preset_label") || detail.audio.matched_preset_label)
        : (detail.audio.matched_preset_label || detail.audio.matched_preset_label_zh);
      if (matchedLabel && detail.audio.matched_preset_id && detail.audio.matched_preset_id !== "default") {
        audStatusText.innerHTML = window.t("inspect.audioActivePreset", "Custom audio ({0})").replace("{0}", `<span style="color:var(--accent-cyan); font-weight:600;">${matchedLabel}</span>`);
        if (audSelect) audSelect.value = detail.audio.matched_preset_id;
      } else {
        audStatusText.innerHTML = window.t("inspect.audioActive", "Custom audio configured");
        if (audSelect) audSelect.value = "";
      }
      audBadge.textContent = window.t("inspect.flaAudioCustom", "Custom Audio");
      audBadge.className = "badge badge-success";
    }
    audCurrentRawCode.textContent = audDisplayRaw;
    audInput.value = audDisplayRaw;
  } else {
    const modAud = detail.mod_preset && detail.mod_preset.audio_raw;
    if (modAud) {
      audStatusBox.className = "fla-status-box active";
      audDot.className = "status-indicator-dot active";
      audStatusText.innerHTML = `${window.t("inspect.audioActive", "Custom audio configured")} <span style="font-size:11px; color:var(--accent-cyan);">(${window.t("inspect.sourceMod", "Mod Preset")})</span>`;
      audCurrentRawCode.textContent = modAud;
      audBadge.textContent = window.t("inspect.sourceMod", "Mod Preset");
      audBadge.className = "badge badge-info";
      audInput.value = modAud;
      if (audSelect) audSelect.value = "";
    } else {
      audStatusBox.className = "fla-status-box inactive";
      audDot.className = "status-indicator-dot inactive";
      audStatusText.textContent = window.t("inspect.audioNoRecord", "(Not listed in data/gtasa_vehicleAudioSettings.cfg)");
      audCurrentRawCode.textContent = window.t("inspect.audioNoRecord", "(Not listed in data/gtasa_vehicleAudioSettings.cfg)");
      audBadge.textContent = window.t("inspect.flaAudioVanilla", "Vanilla Audio");
      audBadge.className = "badge";
      if (detail.audio && detail.audio.vanilla_line) {
        audInput.value = detail.audio.vanilla_line;
        if (audSelect) audSelect.value = "default";
      } else {
        audInput.value = "";
        if (audSelect) audSelect.value = "";
      }
    }
  }
}

function resetFlaDisplay() {
  currentFlaDetail = null;
  const spBox = document.getElementById("specialFeatureStatusBox");
  const spDot = document.getElementById("specialDot");
  const spText = document.getElementById("specialStatusText");
  const spRaw = document.getElementById("specialRawCode");
  const spBadge = document.getElementById("specialFeatureBadge");
  const spInput = document.getElementById("specialFeatureCustomInput");

  if (spBox) spBox.className = "fla-status-box inactive";
  if (spDot) spDot.className = "status-indicator-dot inactive";
  if (spText) spText.textContent = loc({ en: "No vehicle selected" });
  if (spRaw) spRaw.textContent = "--";
  if (spBadge) { spBadge.textContent = window.t("inspect.flaSpecialNotConfigured", "Not Configured"); spBadge.className = "badge"; }
  if (spInput) spInput.value = "";
  document.querySelectorAll("#specialPresetChips .chip-btn").forEach(btn => btn.classList.remove("selected"));

  const audBox = document.getElementById("audioStatusBox");
  const audDot = document.getElementById("audioDot");
  const audText = document.getElementById("audioStatusText");
  const audRaw = document.getElementById("audioCurrentRawCode");
  const audBadge = document.getElementById("audioStatusBadge");
  const audInput = document.getElementById("audioRawInput");
  const audSelect = document.getElementById("soundPresetSelect");

  if (audBox) audBox.className = "fla-status-box inactive";
  if (audDot) audDot.className = "status-indicator-dot inactive";
  if (audText) audText.textContent = loc({ en: "No vehicle selected" });
  if (audRaw) audRaw.textContent = "--";
  if (audBadge) { audBadge.textContent = window.t("inspect.flaAudioVanilla", "Vanilla Audio"); audBadge.className = "badge"; }
  if (audInput) audInput.value = "";
  if (audSelect) audSelect.value = "";
}

function populateSoundPresets(presets) {
  const select = document.getElementById("soundPresetSelect");
  if (!select) return;
  select.innerHTML = `<option value="">${window.t("inspect.audioPresetPlaceholder", "-- Select a vehicle audio preset --")}</option>`;
  if (!presets) return;
  presets.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.id;
    const label = (window.I18N && typeof window.I18N.pick === "function")
      ? (window.I18N.pick(p, "label") || p.label)
      : (p.label_zh || p.label);
    opt.textContent = label;
    select.appendChild(opt);
  });
}

function setupFlaControls() {
  // 0. Collapsed-preview edit toggles (same interaction as the left cards)
  const btnToggleSpecial = document.getElementById("btnToggleEditSpecial");
  if (btnToggleSpecial) btnToggleSpecial.addEventListener("click", () => toggleFlaEdit("special"));
  const btnCancelSpecial = document.getElementById("btnCancelEditSpecial");
  if (btnCancelSpecial) btnCancelSpecial.addEventListener("click", () => toggleFlaEdit("special", false));
  const btnToggleAudio = document.getElementById("btnToggleEditAudio");
  if (btnToggleAudio) btnToggleAudio.addEventListener("click", () => toggleFlaEdit("audio"));
  const btnCancelAudio = document.getElementById("btnCancelEditAudio");
  if (btnCancelAudio) btnCancelAudio.addEventListener("click", () => toggleFlaEdit("audio", false));

  // 1. Preset Chips for Special Features
  const presetChips = document.querySelectorAll("#specialPresetChips .chip-btn");
  presetChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const target = chip.getAttribute("data-target");
      const input = document.getElementById("specialFeatureCustomInput");
      if (input) input.value = target;
      presetChips.forEach(c => c.classList.remove("selected"));
      chip.classList.add("selected");
      showToast(loc({ en: `Selected preset ${target}. Click Save to apply.` }));
    });
  });

  // 2. Save Special Feature
  const btnSaveSpecial = document.getElementById("btnSaveSpecialFeature");
  if (btnSaveSpecial) {
    btnSaveSpecial.addEventListener("click", async () => {
      if (!currentInspectedModel) {
        showToast(t("inspect.noVehicleSelected"), "error");
        return;
      }
      const targetVal = document.getElementById("specialFeatureCustomInput").value.trim();
      if (!targetVal) {
        if (!confirm(loc({ en: `Feature target code is empty. Remove special feature for ${currentInspectedModel}?` }))) {
          return;
        }
      }

      try {
        const res = await fetch("/api/fla/set-special", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model: currentInspectedModel,
            target: targetVal || null
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(loc({ en: `Successfully ${targetVal ? "updated" : "cleared"} feature for ${currentInspectedModel} with .bak backup!` }));
          if (data.detail) renderFlaDetail(data.detail);
          else loadFlaDetail(currentInspectedModel);
          loadSystemStatus();
          toggleFlaEdit("special", false);
        } else {
          showToast((loc({ en: "Failed to save feature: " })) + (data.error || (t("common.unknownError"))), "error");
        }
      } catch (err) {
        showToast((t("common.requestFailed")) + err, "error");
      }
    });
  }

  // 3. Remove Special Feature
  const btnRemoveSpecial = document.getElementById("btnRemoveSpecialFeature");
  if (btnRemoveSpecial) {
    btnRemoveSpecial.addEventListener("click", async () => {
      if (!currentInspectedModel) {
        showToast(t("inspect.noVehicleSelected"), "error");
        return;
      }
      if (!confirm(loc({ en: `Remove ${currentInspectedModel} from data/model_special_features.dat?\nVehicle will revert to default mechanics.` }))) {
        return;
      }

      try {
        const res = await fetch("/api/fla/remove-special", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: currentInspectedModel })
        });
        const data = await res.json();
        if (data.success) {
          showToast(loc({ en: `Removed special feature for ${currentInspectedModel} and created backup!` }));
          if (data.detail) renderFlaDetail(data.detail);
          else loadFlaDetail(currentInspectedModel);
          loadSystemStatus();
          toggleFlaEdit("special", false);
        } else {
          showToast((loc({ en: "Remove failed: " })) + (data.error || (t("common.unknownError"))), "error");
        }
      } catch (err) {
        showToast((t("common.requestFailed")) + err, "error");
      }
    });
  }

  // Helper to format an FLA audio configuration line with authentic column padding
  function formatAudioLineJs(model, rawLine) {
    const widths = [44, 14, 7, 7, 10, 13, 13, 10, 13, 12, 11, 11, 12, 18];
    const cleanRaw = String(rawLine || "").trim();
    if (!cleanRaw) return "";
    const tokens = cleanRaw.split(/\s+/);
    if (!tokens.length) return "";
    const m = String(model || "").trim().toLowerCase();
    if (m) {
      if (/^\d+$/.test(tokens[0])) {
        tokens.unshift(m);
      } else {
        tokens[0] = m;
      }
    } else {
      tokens[0] = tokens[0].toLowerCase();
    }
    if (tokens.length >= widths.length + 1) {
      let res = "";
      for (let i = 0; i < widths.length; i++) {
        res += (tokens[i] || "").padEnd(widths[i]);
      }
      res += tokens.slice(widths.length).join(" ");
      return res.trimEnd();
    } else if (tokens.length > 1) {
      let res = (tokens[0] || "").padEnd(widths[0]);
      for (let i = 1; i < tokens.length; i++) {
        const w = i < widths.length ? widths[i] : 10;
        res += (tokens[i] || "").padEnd(w);
      }
      return res.trimEnd();
    }
    return tokens[0];
  }

  // 4. Audio Preset Select Handler
  const audioSelect = document.getElementById("soundPresetSelect");
  if (audioSelect) {
    audioSelect.addEventListener("change", (e) => {
      const val = e.target.value;
      if (!val) return;
      if (!currentInspectedModel) {
        showToast(loc({ en: "Please select a vehicle from the list first" }), "error");
        return;
      }

      let generatedLine = "";
      let pLabel = "";

      if (val === "default") {
        pLabel = loc({ en: "Vanilla Default" });
        if (currentFlaDetail && currentFlaDetail.audio && currentFlaDetail.audio.vanilla_line) {
          generatedLine = currentFlaDetail.audio.vanilla_line;
        } else {
          showToast(loc({ en: `No vanilla audio baseline record for ${currentInspectedModel}` }), "error");
          return;
        }
      } else {
        const presets = (appStatus && appStatus.sound_presets) || [];
        const p = presets.find(item => item.id === val);
        if (!p) return;
        pLabel = (window.I18N && typeof window.I18N.pick === "function")
          ? (window.I18N.pick(p, "label") || p.label)
          : (p.label_zh || p.label);
        if (p.raw_line) {
          generatedLine = formatAudioLineJs(currentInspectedModel, p.raw_line);
        } else {
          showToast(loc({ en: `Template missing for preset ${pLabel}` }), "error");
          return;
        }
      }

      const audioInput = document.getElementById("audioRawInput");
      if (audioInput && generatedLine) {
        audioInput.value = generatedLine;
        audioInput.focus();
      }
      showToast(loc({ en: `Loaded [${pLabel}] parameters. Click [Save] to apply.` }));
    });
  }

  // 5. Reset Audio Input to Current Disk Value
  const btnResetAudio = document.getElementById("btnResetAudioInput");
  if (btnResetAudio) {
    btnResetAudio.addEventListener("click", () => {
      const audioInput = document.getElementById("audioRawInput");
      if (currentFlaDetail && currentFlaDetail.audio && currentFlaDetail.audio.raw_line) {
        if (audioInput) audioInput.value = currentFlaDetail.audio.raw_line;
        showToast(loc({ en: "Reset to current file line" }));
      } else {
        if (audioInput) audioInput.value = "";
        showToast(loc({ en: "No audio record in file. Cleared editor." }));
      }
    });
  }

  // 6. Save Audio Setting
  const btnSaveAudio = document.getElementById("btnSaveAudioSetting");
  if (btnSaveAudio) {
    btnSaveAudio.addEventListener("click", async () => {
      if (!currentInspectedModel) {
        showToast(t("inspect.noVehicleSelected"), "error");
        return;
      }
      const rawLine = document.getElementById("audioRawInput").value.trim();
      if (!rawLine) {
        showToast(loc({ en: "Audio line cannot be empty! Click [Revert] to reset." }), "error");
        return;
      }

      const parts = rawLine.split(/\s+/);
      if (parts.length < 8) {
        if (!confirm(loc({ en: "⚠️ Audio parameters has fewer than 8 columns and may crash the game. Save anyway?" }))) {
          return;
        }
      }

      try {
        const res = await fetch("/api/fla/set-audio", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model: currentInspectedModel,
            raw_line: rawLine
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(loc({ en: `Audio parameters saved for ${currentInspectedModel} with safety backup!` }));
          if (data.detail) renderFlaDetail(data.detail);
          else loadFlaDetail(currentInspectedModel);
          loadSystemStatus();
          toggleFlaEdit("audio", false);
        } else {
          showToast((loc({ en: "Failed to save audio: " })) + (data.error || (t("common.unknownError"))), "error");
        }
      } catch (err) {
        showToast((t("common.requestFailed")) + err, "error");
      }
    });
  }

  // 7. Remove Audio Setting
  const btnRemoveAudio = document.getElementById("btnRemoveAudioSetting");
  if (btnRemoveAudio) {
    btnRemoveAudio.addEventListener("click", async () => {
      if (!currentInspectedModel) {
        showToast(t("inspect.noVehicleSelected"), "error");
        return;
      }

      const isVanilla = Boolean(currentFlaDetail && currentFlaDetail.audio && currentFlaDetail.audio.is_vanilla);
      const confirmPrompt = isVanilla
        ? (loc({ en: `Revert ${currentInspectedModel} to official vanilla audio?` }))
        : (loc({ en: `Remove audio entry for ${currentInspectedModel} from data/gtasa_vehicleAudioSettings.cfg?` }));

      if (!confirm(confirmPrompt)) {
        return;
      }

      try {
        const res = await fetch("/api/fla/remove-audio", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: currentInspectedModel })
        });
        const data = await res.json();
        if (data.success) {
          showToast(loc({ en: `Reverted ${currentInspectedModel} to vanilla audio!` }));
          if (data.detail) renderFlaDetail(data.detail);
          else loadFlaDetail(currentInspectedModel);
          loadSystemStatus();
          toggleFlaEdit("audio", false);
        } else {
          showToast((loc({ en: "Revert failed: " })) + (data.error || (t("common.unknownError"))), "error");
        }
      } catch (err) {
        showToast((t("common.requestFailed")) + err, "error");
      }
    });
  }
}


// ---------------- Dry-Run & Merge Simulator ----------------

function setupModals() {
  const modal = document.getElementById("dryRunModal");
  const closeBtn = document.getElementById("closeDryRunModal");
  const cancelBtn = document.getElementById("cancelDryRunBtn");
  const dryRunBtn = document.getElementById("btnDryRun");
  const applyBtn = document.getElementById("btnApplyMerge");
  const confirmBtn = document.getElementById("confirmApplyMergeBtn");

  closeBtn.addEventListener("click", () => modal.classList.remove("active"));
  cancelBtn.addEventListener("click", () => modal.classList.remove("active"));

  dryRunBtn.addEventListener("click", async () => {
    if (!activeMod) return;
    showDryRunModal(activeMod.full_path);
  });

  applyBtn.addEventListener("click", async () => {
    if (!activeMod) return;
    if (confirm(loc({ en: `Apply and merge configurations to ModLoader shadow copies?\nTarget vehicle: ${activeMod.target_model}` }))) {
      executeApplyMerge(activeMod.full_path);
    }
  });

  confirmBtn.addEventListener("click", async () => {
    modal.classList.remove("active");
    if (activeMod) executeApplyMerge(activeMod.full_path);
  });

  // Game Path Modal
  const pathModal = document.getElementById("pathModal");
  const openPathBtn = document.getElementById("btnOpenPathModal");
  const closePathBtn = document.getElementById("closePathModal");
  const cancelPathBtn = document.getElementById("cancelPathModal");
  const browseNativeBtn = document.getElementById("btnBrowseFolderNative");
  const savePathBtn = document.getElementById("saveGamePathBtn");
  const inputGamePath = document.getElementById("inputCustomGamePath");
  const pathAlert = document.getElementById("pathValidationAlert");
  const chkRemember = document.getElementById("chkRememberDefaultPath");

  if (openPathBtn) {
    openPathBtn.addEventListener("click", () => openPathModal(false));
  }

  const hidePathModal = () => pathModal && pathModal.classList.remove("active");
  if (closePathBtn) closePathBtn.addEventListener("click", hidePathModal);
  if (cancelPathBtn) cancelPathBtn.addEventListener("click", hidePathModal);

  if (browseNativeBtn) {
    browseNativeBtn.addEventListener("click", async () => {
      try {
        const title = (window.t ? window.t("path.browseGameFolderTitle", "Select GTA: San Andreas Game Root Directory") : "Select GTA: San Andreas Game Root Directory");
        const res = await fetch("/api/browse-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            initial: inputGamePath ? inputGamePath.value.trim() : "",
            title,
            lang: window.currentLang || "en"
          })
        });
        const data = await res.json();
        if (data.success && data.path) {
          if (inputGamePath) inputGamePath.value = data.path;
          if (pathAlert) pathAlert.style.display = "none";
        }
      } catch (err) {
        console.error("Browse folder failed:", err);
        showToast(loc({ en: "Failed to open folder picker" }), "error");
      }
    });
  }

  if (savePathBtn) {
    savePathBtn.addEventListener("click", async () => {
      const newPath = inputGamePath ? inputGamePath.value.trim() : "";
      if (!newPath) {
        if (pathAlert) {
          pathAlert.className = "alert-box warning";
          pathAlert.style.display = "block";
          pathAlert.textContent = loc({ en: "Please enter or select GTA:SA installation directory." });
        }
        return;
      }

      const modalFolderInput = document.getElementById("inputModalDataFolder");
      const targetDataFolder = modalFolderInput ? modalFolderInput.value.trim() : undefined;
      const rememberDefault = chkRemember ? chkRemember.checked : false;

      savePathBtn.disabled = true;
      savePathBtn.textContent = window.t("path.validating", "Validating path...");

      try {
        const res = await fetch("/api/set-game-path", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            path: newPath,
            data_folder: targetDataFolder,
            remember_default: rememberDefault
          })
        });
        const data = await res.json();
        if (data.success) {
          hidePathModal();
          const rememberMsg = data.remember_default_path ? (loc({ en: " (Saved as default)" })) : (loc({ en: " (Will prompt on next launch)" }));
          showToast((loc({ en: "Game directory configured: " })) + `${data.game_path} ${rememberMsg}`, "success");
          discardInspectorContext();
          await loadSystemStatus();
          await loadMods();
          // A different game folder can contain competing config copies of its
          // own. The response already carries the guard's result, so the tree is
          // not scanned twice and a fresh rename keeps its "just disabled" label.
          foreignConfigsNotified = false;
          if (data.foreign_configs) {
            renderForeignConfigs(data.foreign_configs);
            if (data.foreign_configs.notify && !foreignConfigsNotified) {
              foreignConfigsNotified = true;
              openForeignConfigsModal(data.foreign_configs);
            }
          } else {
            await runForeignConfigGuard();
          }
        } else {
          if (pathAlert) {
            pathAlert.className = "alert-box warning";
            pathAlert.style.display = "block";
            pathAlert.textContent = data.error || (loc({ en: "Invalid path. Ensure gta_sa.exe and data/ exist." }));
          }
        }
      } catch (err) {
        if (pathAlert) {
          pathAlert.className = "alert-box warning";
          pathAlert.style.display = "block";
          pathAlert.textContent = (loc({ en: "Request error: " })) + err.message;
        }
      } finally {
        savePathBtn.disabled = false;
        savePathBtn.textContent = window.t("path.btnSave", "Confirm & Launch");
      }
    });
  }

  // FLA Status Banner & Actions
  const flaBanner = document.getElementById("flaWarningBanner");
  const btnDismissSession = document.getElementById("btnDismissFlaSession");
  const btnDismissPermanent = document.getElementById("btnDismissFlaPermanent");
  const flaStatusPill = document.getElementById("flaStatusPill");

  if (flaStatusPill) {
    flaStatusPill.addEventListener("click", () => {
      const fla = (appStatus && appStatus.fla) || {};
      if (fla.installed) {
        if (fla.is_pending_launch) {
          showToast(loc({ en: "FLA patch (ASI file) detected and ready! fastman92limitAdjuster_GTASA.ini will be created on first game launch." }), "info");
        } else {
          showToast(loc({ en: `Fastman92 Limit Adjuster (FLA) is active and ready (${fla.special_count} specials / ${fla.audio_count} audio)` }), "info");
        }
      } else if (fla.has_fla_ini || fla.ini_orphaned) {
        showToast(loc({ en: "FLA config (fastman92limitAdjuster_GTASA.ini) found, but the main $fastman92limitAdjuster.asi is missing; FLA will not load." }), "warning");
      } else {
        showToast(loc({ en: "Notice: the FLA main file fastman92limitAdjuster.asi was not found in the game directory (a config .ini alone has no effect)" }), "warning");
      }
    });
  }

  if (btnDismissSession) {
    btnDismissSession.addEventListener("click", () => {
      window._flaSessionDismissed = true;
      if (flaBanner) flaBanner.style.display = "none";
      showToast(loc({ en: "FLA status notice dismissed for this session" }), "info");
    });
  }

  if (btnDismissPermanent) {
    btnDismissPermanent.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/config/dismiss-fla", { method: "POST" });
        const d = await res.json();
        if (d.success) {
          if (appStatus) appStatus.dismiss_fla_warning = true;
          if (flaBanner) flaBanner.style.display = "none";
          showToast(loc({ en: "FLA notice disabled permanently for future startups" }), "info");
        }
      } catch (err) {
        showToast(loc({ en: "Failed to dismiss FLA notice: " + err.message }), "error");
      }
    });
  }

  const btnDownloadSevenZip = document.getElementById("btnDownloadSevenZip");
  const btnRecheckSevenZip = document.getElementById("btnRecheckSevenZip");
  const btnDismissSevenZip = document.getElementById("btnDismissSevenZipSession");
  const sevenZipBanner = document.getElementById("sevenZipWarningBanner");

  if (btnDownloadSevenZip) {
    btnDownloadSevenZip.addEventListener("click", () => openSevenZipDownload());
  }
  if (btnRecheckSevenZip) {
    btnRecheckSevenZip.addEventListener("click", () => recheckSevenZip());
  }
  if (btnDismissSevenZip) {
    btnDismissSevenZip.addEventListener("click", () => {
      window._sevenZipSessionDismissed = true;
      if (sevenZipBanner) sevenZipBanner.style.display = "none";
    });
  }
}

async function showDryRunModal(modPath) {
  const modal = document.getElementById("dryRunModal");
  const body = document.getElementById("dryRunModalBody");
  body.innerHTML = `<div class="loading-spinner">${window.t("dryrun.loading", "Simulating merge operations...")}</div>`;
  modal.classList.add("active");

  try {
    const res = await fetch("/api/dry-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: modPath })
    });
    const data = await res.json();
    if (!data.success) {
      body.innerHTML = `<div class="alert-box warning">${data.error}</div>`;
      return;
    }

    let reportHtml = `
      <div class="alert-box info">
        ${window.t("dryrun.summary", "<strong>Dry-run Complete:</strong> Detected <strong>{0}</strong> changes. Vanilla <code>data/</code> remains 100% untouched.").replace("{0}", data.total_actions)}
      </div>
    `;

    for (const [key, info] of Object.entries(data.changes)) {
      if (info.actions && info.actions.length > 0) {
        reportHtml += `
          <div style="margin-bottom:14px;">
            <h4 style="color:var(--text-bright); margin-bottom:6px;">📁 ${key} (${window.t("dryrun.actionsCount", "{0} changes").replace("{0}", info.actions.length)})</h4>
            <div style="background:#05070a; border:1px solid var(--border); border-radius:6px; padding:10px;">
        `;
        info.actions.forEach(a => {
          reportHtml += `
            <div style="margin-bottom:6px; font-size:12px;">
              <span style="color:var(--accent-emerald); font-weight:600;">+ [${a.type}]</span>
              <span style="color:var(--text-main); margin-left:6px;">${a.desc}</span>
              ${a.line ? `<pre style="margin-top:4px; max-height:80px; padding:6px;">${a.line}</pre>` : ''}
            </div>
          `;
        });
        reportHtml += `</div></div>`;
      }
    }

    body.innerHTML = reportHtml;
  } catch (err) {
    body.innerHTML = `<div class="alert-box warning">${loc({ en: "Failed to generate dry-run report: " })}${err.message}</div>`;
  }
}

async function executeApplyMerge(modPath) {
  try {
    const res = await fetch("/api/apply-merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: modPath })
    });
    const data = await res.json();
    if (data.success) {
      showToast(window.t("toast.applyMergeSuccess", "Merged successfully! Updated files: ") + data.applied_files.join(", "), "success");
      loadSystemStatus();
      await loadMods();
      if (activeMod && isSamePath(activeMod.full_path, modPath)) await inspectMod(activeMod);
    } else {
      showToast((loc({ en: "Errors during merge: " })) + data.errors.join("; "), "error");
    }
  } catch (err) {
    showToast(window.t("toast.applyMergeFailed", "Failed to apply merge"), "error");
  }
}

// ---------------- Readme Lab ----------------

function setupLab() {
  const btn = document.getElementById("btnTestParseRaw");
  const textarea = document.getElementById("labTextInput");
  const resultsBox = document.getElementById("labParsedResults");
  const dropZone = document.getElementById("labDropZone");
  const fileInput = document.getElementById("labFileInput");
  const browseLink = document.getElementById("labBrowseLink");
  const fileNameBadge = document.getElementById("labLoadedFileName");

  // Handle file loading via FileReader
  function handleFile(file) {
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      textarea.value = e.target.result;
      if (fileNameBadge) {
        fileNameBadge.textContent = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        fileNameBadge.style.display = "inline-block";
      }
      showToast(loc({ en: `Loaded ${file.name}, parsing automatically...` }));
      // Auto trigger parse
      btn.click();
    };
    reader.onerror = () => {
      showToast(loc({ en: "Failed to read file" }), "error");
    };
    reader.readAsText(file, "utf-8");
  }

  // Drag & Drop events
  if (dropZone) {
    ["dragenter", "dragover"].forEach(evt => {
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add("dragover");
      });
    });

    ["dragleave", "dragend"].forEach(evt => {
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove("dragover");
      });
    });

    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("dragover");
      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        handleFile(files[0]);
      }
    });

    dropZone.addEventListener("click", (e) => {
      if (e.target !== browseLink) {
        fileInput.click();
      }
    });
  }

  if (browseLink) {
    browseLink.addEventListener("click", (e) => {
      e.stopPropagation();
      fileInput.click();
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFile(e.target.files[0]);
      }
    });
  }

  // Manual parse button
  btn.addEventListener("click", async () => {
    const text = textarea.value.trim();
    if (!text) {
      showToast(loc({ en: "Please enter or drop Readme text on the left" }), "warning");
      return;
    }

    try {
      const res = await fetch("/api/parse-raw-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      const data = await res.json();
      if (data.success) {
        renderLabResults(data.parsed);
      }
    } catch (err) {
      resultsBox.innerHTML = `<p class="empty-hint">${loc({ en: "Parse failed: " })}${err.message}</p>`;
    }
  });
}

function renderLabResults(parsed) {
  const box = document.getElementById("labParsedResults");
  let html = "";

  const sections = [
    { title: window.t("lab.fxtTitle", "🔤 FXT / GXT Names"), items: parsed.fxt_text, color: "#f472b6" },
    { title: window.t("lab.handlingTitle", "🏎️ handling.cfg (Physics & Handling)"), items: parsed.handling_cfg, color: "var(--accent-cyan)" },
    { title: window.t("lab.ideTitle", "🏷️ vehicles.ide (Vehicle Definitions)"), items: parsed.vehicles_ide, color: "var(--accent-amber)" },
    { title: window.t("lab.carcolsTitle", "🎨 carcols.dat (Color Palettes)"), items: parsed.carcols_dat, color: "var(--accent-emerald)" },
    { title: window.t("lab.carmodsTitle", "🛠️ carmods.dat (Tuning Mods)"), items: parsed.carmods_dat, color: "var(--accent-rose)" },
    { title: window.t("lab.audioTitle", "🔊 vehicleAudioSettings (Audio)"), items: parsed.vehicle_audio, color: "var(--accent-purple)" },
    { title: window.t("lab.specialTitle", "✨ model_special_features (Special Features)"), items: parsed.special_features, color: "#fff" },
  ];

  let totalFound = 0;
  sections.forEach(s => {
    if (s.items && s.items.length > 0) {
      totalFound += s.items.length;
      const countStr = window.t("lab.linesCount", "{0} lines").replace("{0}", s.items.length);
      html += `
        <div style="margin-bottom:12px;">
          <h5 style="color:${s.color}; margin-bottom:4px;">${s.title} (${countStr}):</h5>
          <pre style="max-height:100px; padding:6px;">${s.items.join("\n")}</pre>
        </div>
      `;
    }
  });

  if (totalFound === 0) {
    html = `<p class="empty-hint">${window.t("lab.noDataFound", "No GTA:SA configuration lines recognized.")}</p>`;
  } else {
    const summaryStr = window.t("lab.extractedSummary", "Extracted <strong>{0}</strong> valid configuration entries.").replace("{0}", totalFound);
    html = `<div class="alert-box info" style="padding:6px 12px; margin-bottom:10px;">${summaryStr}</div>` + html;
  }

  box.innerHTML = html;
}

// ---------------- Mod Installer Logic ----------------

let vanillaVehicles = [];
// Stays false until the vanilla list is known-good. Name-clash checks are
// meaningless against an empty list, so they must fail closed rather than let
// a colliding model name through.
let vanillaVehiclesReady = false;
let currentInspectData = null;

function setVanillaListWarning(visible) {
  const banner = document.getElementById("vanillaListWarningBanner");
  if (banner) banner.style.display = visible ? "flex" : "none";
}

async function loadVanillaVehicles() {
  const MAX_ATTEMPTS = 3;
  let lastErr = null;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      const res = await fetch("/api/vehicles");
      const data = await res.json();
      if (data.success && Array.isArray(data.vehicles) && data.vehicles.length > 0) {
        vanillaVehicles = data.vehicles;
        vanillaVehiclesReady = true;
        setVanillaListWarning(false);
        return true;
      }
      lastErr = new Error("Vanilla vehicle list is empty or invalid response");
    } catch (err) {
      lastErr = err;
    }
    if (attempt < MAX_ATTEMPTS) {
      await new Promise(resolve => setTimeout(resolve, 300 * attempt));
    }
  }

  vanillaVehiclesReady = false;
  console.error("Failed to load vehicle list:", lastErr);
  setVanillaListWarning(true);
  return false;
}

function updateExcludedFilesBadge(count) {
  const badge = document.getElementById("installExcludedFilesBadge");
  if (!badge) return;
  if (count > 0) {
    badge.style.display = "inline-block";
    badge.textContent = window.t("assets.badgeExcluded", "{0} files excluded").replace("{0}", count);
  } else {
    badge.style.display = "none";
  }
}

async function handleInstallAssetsApply(excludedList, userParsedConfig, editedKeys) {
  updateExcludedFilesBadge((excludedList || []).length);
  if (!currentInspectData || !currentInspectData.inspection_id) return;

  const hasManualEdits = editedKeys && editedKeys.size > 0;
  if (userParsedConfig && hasManualEdits) {
    for (const k of editedKeys) {
      currentInspectData.parsed_config[k] = userParsedConfig[k] || [];
    }
    refreshInstallConfigBreakdown();
  }

  const lastExcluded = currentInspectData._lastReparseExcluded || [];
  const currExcluded = excludedList || [];
  const exclusionChanged = (
    lastExcluded.length !== currExcluded.length ||
    currExcluded.some(f => !lastExcluded.includes(f))
  );

  if (exclusionChanged) {
    try {
      const res = await fetch("/api/installer/reparse-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          inspection_id: currentInspectData.inspection_id,
          excluded_files: currExcluded
        })
      });
      const data = await res.json();
      if (data.success && data.parsed_config) {
        currentInspectData._lastReparseExcluded = [...currExcluded];
        let merged = data.parsed_config;
        if (hasManualEdits) {
          for (const k of editedKeys) {
            merged[k] = userParsedConfig[k] || [];
          }
        }
        currentInspectData.parsed_config = merged;
        if (window.InstallAssets && window.InstallAssets.updateParsedConfig) {
          window.InstallAssets.updateParsedConfig(merged);
        }
        refreshInstallConfigBreakdown();
      }
    } catch (err) {
      console.error("Failed to reparse configs:", err);
    }
  } else {
    if (userParsedConfig) {
      currentInspectData.parsed_config = { ...currentInspectData.parsed_config, ...userParsedConfig };
    }
    refreshInstallConfigBreakdown();
  }
}

function refreshInstallConfigBreakdown() {
  if (!currentInspectData) return;
  const cfg = currentInspectData.parsed_config || {};
  const cfgBits = [];
  if ((cfg.handling_cfg || []).length) cfgBits.push("handling");
  if ((cfg.carcols_dat || []).length) cfgBits.push("carcols");
  if ((cfg.carmods_dat || []).length) cfgBits.push("carmods");
  if ((cfg.special_features || []).length || (cfg.vehicle_audio || []).length) cfgBits.push("FLA");

  const breakdownDiv = document.getElementById("installFilesBreakdown");
  if (breakdownDiv) {
    const dffN = (currentInspectData.primary_dffs || []).length;
    const txdN = (currentInspectData.primary_txds || []).length;
    const tuneN = (currentInspectData.tuning_dffs || []).length + (currentInspectData.tuning_txds || []).length;
    const readmeN = (currentInspectData.readme_files || []).length;
    const chip = (n, key, label) => `<button type="button" class="asset-chip asset-chip-button${n ? " has-data" : ""}" data-asset-category="${key}" aria-haspopup="dialog" aria-controls="installAssetDialog" ${n ? "" : "disabled"}>${n} <span data-i18n="${label}">${window.t(label, label)}</span></button>`;
    let bHtml = `<div class="asset-chip-row">
      ${chip(dffN, "models", "install.assetModels")}
      ${chip(txdN, "textures", "install.assetTextures")}
      ${chip(tuneN, "tuning", "install.assetTuning")}
      ${chip(readmeN, "documents", "install.assetReadme")}
      ${(currentInspectData.asset_files && currentInspectData.asset_files.other && currentInspectData.asset_files.other.length) ? chip(currentInspectData.asset_files.other.length, "other", "assets.other") : ""}
      <button type="button" class="asset-chip asset-chip-button${cfgBits.length ? " has-data" : ""}" data-asset-category="configs" aria-haspopup="dialog" aria-controls="installAssetDialog">${cfgBits.length ? cfgBits.join(" · ") : `<span data-i18n="assets.configs">${window.t("assets.configs", "Configuration")}</span>`}</button>
    </div>`;
    bHtml += `<div id="installAddonIdSummaryHint" class="field-hint" style="margin-top:8px; display:none;"></div>`;
    if (currentInspectData.addon_name_conflicts && currentInspectData.addon_name_conflicts.length > 0) {
      bHtml += `<div class="asset-note">${window.t("install.addonNameConflict", "These models collide with vanilla names and will install as replace (rename for true addon):")}${currentInspectData.addon_name_conflicts.map(c => `${c.model}`).join(" · ")}</div>`;
    }
    breakdownDiv.innerHTML = bHtml;
  }

  // Update checkboxes state based on newly parsed configs
  const chkH = document.getElementById("chkMergeHandling");
  if (chkH) chkH.checked = (cfg.handling_cfg || []).length > 0;
  const chkC = document.getElementById("chkMergeCarcols");
  if (chkC) chkC.checked = (cfg.carcols_dat || []).length > 0;
  const chkM = document.getElementById("chkMergeCarmods");
  if (chkM) chkM.checked = (cfg.carmods_dat || []).length > 0;
  const chkFla = document.getElementById("chkMergeFla");
  if (chkFla) chkFla.checked = ((cfg.special_features || []).length > 0 || (cfg.vehicle_audio || []).length > 0);

  updateInstallChecklistSummary();
}

function setupInstaller() {
  window.InstallAssets.init();
  if (window.InstallAssets.onApply) {
    window.InstallAssets.onApply(handleInstallAssetsApply);
  }
  loadVanillaVehicles();

  const btnRetryVanilla = document.getElementById("btnRetryVanillaList");
  if (btnRetryVanilla) {
    btnRetryVanilla.addEventListener("click", async () => {
      btnRetryVanilla.disabled = true;
      const ok = await loadVanillaVehicles();
      btnRetryVanilla.disabled = false;
      showToast(ok
        ? window.t("vanilla.reloadOk", "Vanilla vehicle list reloaded")
        : window.t("vanilla.reloadFailed", "The vanilla vehicle list still could not be loaded; restart the app and try again"), ok ? "success" : "error");
      if (ok) validateNewInstallName();
    });
  }

  // Shortcut button in mods tab
  const btnGo = document.getElementById("btnGoToInstallTab");
  if (btnGo) {
    btnGo.addEventListener("click", () => switchTab("installTab"));
  }

  // Browse buttons
  const btnBrowseArchive = document.getElementById("btnBrowseInstallArchive");
  const btnBrowseFolder = document.getElementById("btnBrowseInstallFolder");
  const btnAnalyzePath = document.getElementById("btnAnalyzeManualPath");
  const inputManualPath = document.getElementById("inputManualSourcePath");

  if (btnBrowseArchive) {
    btnBrowseArchive.addEventListener("click", async () => {
      try {
        const title = (window.t ? window.t("install.browseArchiveDialogTitle", "Select Vehicle Mod Archive or Files") : "Select Vehicle Mod Archive or Files");
        const res = await fetch("/api/browse-file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            initial: "",
            title,
            lang: window.currentLang || "en"
          })
        });
        const data = await res.json();
        if (data.success && data.path) {
          inspectModSource(data.path);
        }
      } catch (err) {
        showToast(loc({ en: "Failed to open file browser dialog" }), "error");
      }
    });
  }

  if (btnBrowseFolder) {
    btnBrowseFolder.addEventListener("click", async () => {
      try {
        const title = (window.t ? window.t("install.browseFolderDialogTitle", "Select Vehicle Mod Folder") : "Select Vehicle Mod Folder");
        const res = await fetch("/api/browse-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            initial: "",
            title,
            lang: window.currentLang || "en"
          })
        });
        const data = await res.json();
        if (data.success && data.path) {
          inspectModSource(data.path);
        }
      } catch (err) {
        showToast(loc({ en: "Failed to open folder browser dialog" }), "error");
      }
    });
  }

  if (btnAnalyzePath) {
    btnAnalyzePath.addEventListener("click", () => {
      const p = inputManualPath ? inputManualPath.value.trim() : "";
      if (!p) {
        showToast(loc({ en: "Please enter a valid file or folder path" }), "warning");
        return;
      }
      inspectModSource(p);
    });
  }

  // Drop zone events
  const dropZone = document.getElementById("installDropZone");
  if (dropZone) {
    ["dragenter", "dragover"].forEach(evt => {
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add("dragover");
      });
    });

    ["dragleave", "dragend"].forEach(evt => {
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove("dragover");
      });
    });

    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("dragover");
      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        const f = files[0];
        if (f.path) {
          inspectModSource(f.path);
        } else {
          showToast(loc({ en: `Detected ${f.name}. Please use Browse button to locate.` }), "info");
        }
      }
    });
  }

  // Replace / addon install mode controls (custom model + TXD names)
  setupInstallModeControls();

  // Vehicle Select change
  const vehSelect = document.getElementById("installVehicleSelect");
  if (vehSelect) {
    vehSelect.addEventListener("change", () => {
      const selModel = vehSelect.value.toLowerCase();
      const badge = document.getElementById("installModelBadge");
      const renameHint = document.getElementById("installModelRenameHint");
      const fxtKey = document.getElementById("installFxtKey");

      const match = vanillaVehicles.find(v => v.model.toLowerCase() === selModel);
      if (match) {
        badge.textContent = `ID: ${match.id} (${match.name})`;
      } else {
        if (!(wizardVehicles && wizardVehicles.length > 1)) {
          const props = (currentInspectData && currentInspectData.addon_id_proposals) || {};
          if (props[selModel] != null) singleAddonId = props[selModel];
          paintBadgeFor(selModel, singleAddonId);
        } else {
          const wv0 = wizardVehicles[wizardCurrentIndex];
          paintBadgeFor(selModel, wv0 ? wv0.addon_id : null);
        }
      }

      // Rename hint compares against THIS vehicle's source, not the pack default
      const baseRef = (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex])
        ? wizardVehicles[wizardCurrentIndex].source_model
        : (currentInspectData && currentInspectData.target_model ? currentInspectData.target_model.toLowerCase() : selModel);
      if (selModel !== (baseRef || "").toLowerCase()) {
        renameHint.style.display = "block";
      } else {
        renameHint.style.display = "none";
      }

      // GXT naming on target change: vanilla replace-rename flows follow the
      // target model; a converted addon package defaults to the TARGET's
      // vanilla identity (key + name) unless the user typed a custom key.
      if (fxtKey && !(wizardVehicles && wizardVehicles.length > 1)) {
        if (!isAddonModel(baseRef)) {
          if (!fxtKey.value || (currentInspectData && fxtKey.value === currentInspectData.target_model.toUpperCase())) {
            fxtKey.value = selModel.toUpperCase();
          }
        } else if (currentInstallMode() === "replace") {
          applyConversionNameDefaults(selModel);
        }
      }

      if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
        wizardVehicles[wizardCurrentIndex].target_model = selModel;
        const vMatch = vanillaVehicles.find(v => v.model.toLowerCase() === selModel);
        wizardVehicles[wizardCurrentIndex].vanilla_name = vMatch ? vMatch.name : selModel.toUpperCase();
        renderWizardStepsTrack();
      }

      // Single install: follow the target kind between the two default folders
      // unless the user picked a custom category. Wizard mode handles this per
      // phase through the destination card.
      syncDefaultCategoryToTarget(selModel);
      refreshAddonIdRow();
      refreshAddonIdSummary();
      refreshInstallReplaceHint();
    });
  }

  // Multi-vehicle Wizard Prev / Next Buttons are wired per-state inside
  // loadWizardVehicleToForm (phase-aware); no static bindings here to avoid
  // double-stepping when phases are split.

  const chkSkipCar = document.getElementById("chkSkipCurrentCar");
  if (chkSkipCar) {
    chkSkipCar.addEventListener("change", (e) => {
      if (wizardVehicles && wizardVehicles[wizardCurrentIndex]) {
        wizardVehicles[wizardCurrentIndex].skip = e.target.checked;
        renderWizardStepsTrack();
        updateInstallPathPreview();
      }
    });
  }

  const wizFolderInp = document.getElementById("installWizardCarFolder");
  if (wizFolderInp) {
    wizFolderInp.addEventListener("input", () => {
      if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
        const val = wizFolderInp.value.trim();
        wizardVehicles[wizardCurrentIndex].folder_name = val;
        const subInp = document.getElementById("installSubfolderName");
        if (subInp && document.activeElement !== subInp) {
          const r = wizardResolvedFolder();
          subInp.value = val || (r ? r.shared : "");
        }
        updateInstallPathPreview(true);
      }
    });
  }
  const sepBtn = document.getElementById("btnSeparateFolders");
  if (sepBtn) {
    sepBtn.addEventListener("click", () => {
      if (!wizardVehicles || wizardVehicles.length <= 1) return;
      syncCurrentWizardFormToState();
      let n = 0;
      wizardVehicles.forEach(wv => {
        if (!wv || wv.skip) return;
        if (((wv.folder_name) || "").trim()) return;
        const base = ((wv.vanilla_name || wv.target_model || "").trim()) || (wv.source_model || "").trim();
        if (base) { wv.folder_name = base; n++; }
      });
      refreshWizardFolderPreview();
      updateInstallPathPreview();
      showToast(window.t("install.separateFoldersDone", "Assigned separate folders to {0} vehicle(s)").replace("{0}", n), n ? "success" : "info");
    });
  }
  const wizCatSel = document.getElementById("installWizardCarCategory");
  if (wizCatSel) {
    wizCatSel.addEventListener("change", () => {
      if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
        wizardVehicles[wizardCurrentIndex].category = wizCatSel.value;
        updateInstallPathPreview();
      }
    });
  }

  // Addon vehicle ID editor (visible only for addon targets)
  const addonIdInput = document.getElementById("installAddonIdInput");
  if (addonIdInput) {
    addonIdInput.addEventListener("input", () => {
      const slot = currentAddonSlot();
      if (!slot) return;
      const raw = (addonIdInput.value || "").trim();
      const v = parseInt(raw, 10);
      slot.set(!raw || isNaN(v) ? null : v);
      paintBadgeFor(slot.model, slot.get());
      refreshAddonOptionText(slot.model, slot.get());
      refreshAddonIdSummary();
      scheduleAddonIdCheck();
    });
  }
  const addonIdAuto = document.getElementById("btnAddonIdAuto");
  if (addonIdAuto) {
    addonIdAuto.addEventListener("click", async () => {
      const slot = currentAddonSlot();
      if (!slot || !addonIdInput) return;
      try {
        const exclude = [];
        if (wizardVehicles && wizardVehicles.length > 1) {
          wizardVehicles.forEach(wv => {
            if (wv && wv.target_model.toLowerCase() !== slot.model.toLowerCase() && wv.addon_id != null && wv.addon_id !== "") {
              const n = parseInt(wv.addon_id, 10);
              if (!isNaN(n)) exclude.push(n);
            }
          });
        }
        const res = await fetch("/api/ids/allocate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ count: 1, kind: "addon", exclude_ids: exclude })
        });
        const data = await res.json();
        if (data.success && data.allocated && data.allocated.length > 0) {
          slot.set(data.allocated[0]);
          addonIdInput.value = data.allocated[0];
          paintBadgeFor(slot.model, slot.get());
          refreshAddonOptionText(slot.model, slot.get());
          refreshAddonIdSummary();
          scheduleAddonIdCheck();
        }
      } catch (e) {}
    });
  }

  // Cancel button
  const cancelBtn = document.getElementById("btnCancelInstall");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      currentInspectData = null;
      wizardVehicles = [];
      wizardCurrentIndex = 0;
      displayedDestPhase = null;
      wizardFormLoaded = false;
      if (window.InstallAssets && window.InstallAssets.reset) window.InstallAssets.reset();
      updateExcludedFilesBadge(0);
      document.getElementById("installStep1").style.display = "block";
      document.getElementById("installStep2").style.display = "none";
      document.getElementById("installStep3").style.display = "none";
    });
  }

  // Install Another button
  const installAnotherBtn = document.getElementById("btnInstallAnother");
  if (installAnotherBtn) {
    installAnotherBtn.addEventListener("click", () => {
      currentInspectData = null;
      wizardVehicles = [];
      wizardCurrentIndex = 0;
      displayedDestPhase = null;
      wizardFormLoaded = false;
      if (window.InstallAssets && window.InstallAssets.reset) window.InstallAssets.reset();
      updateExcludedFilesBadge(0);
      document.getElementById("installStep1").style.display = "block";
      document.getElementById("installStep2").style.display = "none";
      document.getElementById("installStep3").style.display = "none";
    });
  }

  // Execute Install Button
  const executeBtn = document.getElementById("btnExecuteInstall");
  if (executeBtn) {
    executeBtn.addEventListener("click", async () => {
      if (!currentInspectData || tuningInstallBusy) return;
      tuningInstallBusy = true;
      updateTuningSelectionSummary();
      try {
        if (!(await refreshTuningValidation(true))) {
          showToast(window.t("install.tuningResolve", "Resolve the highlighted tuning IDs, auto-assign, or uncheck those parts to continue."), "error");
          return;
        }
        const tuningGenerationAtSubmit = tuningValidationGeneration;

        const subfolder = document.getElementById("installSubfolderName").value.trim();
        if (!subfolder) {
          showToast(loc({ en: "Please enter a mod folder name" }), "warning");
          return;
        }

        const targetCategory = document.getElementById("installCategorySelect").value;
        if (wizardVehicles && wizardVehicles.length > 1) syncCurrentWizardFormToState();
        if (!validateNewInstallName()) {
          showToast(window.t("install.newNameInvalidToast", "Fix the new model/texture name first (2-20 lowercase letters, digits or underscores, unique)"), "error");
          return;
        }
        const targetModel = effectiveInstallTarget();
        const targetTxd = effectiveInstallTxd();

        // Reverse conversion guard: an addon package may only replace a vanilla
        // vehicle of the same handling class (car vs bike vs ...). The backend
        // enforces this too; catching it here gives an instant, clear error.
        refreshInstallReplaceHint();
        const classMismatch = anyInstallClassMismatch();
        if (classMismatch) {
          showToast(window.t(
            "install.classMismatchError",
            "⚠️ Class mismatch: this package is a {0}, but {1} is a {2}. Physics and animation schemas differ between classes — pick a vanilla {0} target instead."
          ).split("{0}").join(classMismatch.srcType)
           .split("{1}").join(classMismatch.target.name)
           .split("{2}").join(classMismatch.tgtType), "error");
          return;
        }

        const payload = {
          inspect_dir: currentInspectData.inspect_dir,
          target_category: targetCategory,
          author_folder: document.getElementById("installAuthorFolder") ? document.getElementById("installAuthorFolder").value.trim() : "",
          folder_name: subfolder,
          target_model: targetModel,
          source_model: installTargetSourceModel() || targetModel,
          source_type: installSourceType(),
          target_txd: targetTxd,
          target_handling: effectiveInstallHandling(),
          copy_files: document.getElementById("chkCopyFiles").checked,
          merge_handling: document.getElementById("chkMergeHandling").checked,
          merge_carcols: document.getElementById("chkMergeCarcols").checked,
          merge_carmods: document.getElementById("chkMergeCarmods").checked,
          generate_shopping: document.getElementById("chkGenShopping").checked,
          generate_fxt: document.getElementById("chkGenFxt").checked,
          fxt_key: document.getElementById("installFxtKey").value.trim(),
          fxt_name: document.getElementById("installFxtName").value.trim(),
          merge_fla: document.getElementById("chkMergeFla").checked,
          variant_choices: collectVariantChoices(),
          excluded_files: Array.from(window.InstallAssets && window.InstallAssets.getExcludedFiles ? window.InstallAssets.getExcludedFiles() : []),
          excluded_tuning_parts: collectExcludedTuningParts(),
          tuning_id_assignments: collectTuningIdAssignments(),
          parsed_config: currentInspectData.parsed_config,
          is_temp_extracted: currentInspectData.is_temp_extracted
        };

        if (wizardVehicles && wizardVehicles.length > 1) {
          syncCurrentWizardFormToState();
          persistCurrentPhaseDest();
          const activeVehicles = wizardVehicles.filter(v => !v.skip);
          if (activeVehicles.length === 0) {
            showToast(loc({ en: "All vehicles are marked as skipped. Please keep at least one to install!" }), "warning");
            return;
          }
          // Materialize per-vehicle destination: explicit per-car override wins,
          // otherwise fall back to its PHASE shared destination (replace and
          // addon phases are configured independently).
          payload.vehicles = wizardVehicles.map(wv => {
            const pd = (hasBothPhases() && phaseDest[phaseOfVehicle(wv)]) || {};
            return Object.assign({}, wv, {
              folder_name: ((wv.folder_name || "").trim()) || ((pd.subfolder || "").trim()),
              category: ((wv.category || "").trim()) || ((pd.category || "").trim()),
              author: ((wv.author || "").trim()) || ((pd.author || "").trim())
            });
          });
          payload.target_model = activeVehicles[0].target_model;

          // Every converted addon vehicle must have a valid, unique model/TXD name.
          const seenAddonNames = new Set();
          for (const wv of activeVehicles) {
            if ((wv.install_mode || "replace") !== "addon") continue;
            const nm = String(wv.target_model || "").toLowerCase();
            const wt = String(wv.target_txd || nm).toLowerCase();
            const wh = String(wv.target_handling || suggestHandlingId(nm)).trim();
            const wk = String(wv.fxt_key || "").trim().toUpperCase();
            if (seenAddonNames.has(nm)
                || validateCustomModelName(nm, collectTakenModelNames(nm))
                || !/^[a-z0-9_]{2,20}$/.test(wt)
                || validateCustomHandlingId(wh)
                || (wk && !/^[A-Z0-9_]{2,7}$/.test(wk))) {
              showToast(window.t("install.newNameInvalidToast", "Fix the new model/texture name first (2-20 lowercase letters, digits or underscores, unique)"), "error");
              return;
            }
            wv.target_handling = wh;
            wv.fxt_key = wk;
            seenAddonNames.add(nm);
          }
        }

        // Addon vehicle IDs: user-editable, must be 612-65535 and free (or self)
        payload.addon_id_assignments = collectAddonIdAssignments();
        for (const [am, aid] of Object.entries(payload.addon_id_assignments)) {
          if (!Number.isInteger(aid) || aid < 612 || aid > 65535) {
            showToast(window.t("install.addonIdInvalid", "⚠️ Enter an ID between 612–65535"), "error");
            return;
          }
        }
        for (const [am, aid] of Object.entries(payload.addon_id_assignments)) {
          try {
            const cr = await fetch(`/api/ids/check?id=${aid}`);
            const cd = await cr.json();
            const occ = cd && cd.result;
            if (cd.success && occ && !occ.is_free && ((occ.name || "").toLowerCase() !== am)) {
              showToast(window.t("install.addonIdConflict", "Addon vehicle {0}: ID {1} unusable: {2}").replace("{0}", am.toUpperCase()).replace("{1}", aid).replace("{2}", occ.name || ""), "error");
              return;
            }
          } catch (e) {}
        }
        // FLA killable ceiling: warn (not block) when exceeding the ini limit
        const killCap = await ensureKillableLimit();
        if (killCap != null) {
          const over = Object.entries(payload.addon_id_assignments).filter(([, aid]) => aid >= killCap);
          if (over.length > 0) {
            const msg = window.t("install.addonIdOverKillableConfirm", "These addon vehicle IDs exceed the FLA killable limit {0}; destroyed vehicles may not register kills or crash the game (raise Count of killable model IDs in the ini and retry):\n{1}\nInstall anyway?").replace("{0}", killCap).replace("{1}", over.map(([am, aid]) => `${am.toUpperCase()} → ${aid}`).join(", "));
            if (!(await showAppConfirm(msg))) return;
          }
        }

        executeBtn.disabled = true;
        executeBtn.textContent = loc({ en: "Checking existing installations..." });

        const reminder = await window.InstallReminder.beforeInstall(payload);
        if (reminder.action === "library") {
          switchTab("modsTab");
          await loadMods();
          const normalizePath = path => String(path || "").replace(/\\/g, "/").toLowerCase();
          const first = reminder.matches[0];
          const existing = allMods.find(mod => normalizePath(mod.full_path) === normalizePath(first.path));
          const search = document.getElementById("modSearchInput");
          if (search) search.value = existing ? existing.name : "";
          currentFilter = "all";
          document.querySelectorAll(".filter-chips .chip").forEach(chip => {
            chip.classList.toggle("active", chip.dataset.filter === "all");
          });
          if (existing) {
            const button = document.getElementById(existing.mod_type === "addon" || existing.is_addon
              ? "partitionAddonBtn" : "partitionReplaceBtn");
            if (button) button.click();
          }
          applyFilter();
          return;
        }
        if (reminder.action !== "continue") return;
        if (tuningGenerationAtSubmit !== tuningValidationGeneration) {
          showToast(window.t("install.tuningChanged", "Tuning IDs changed during confirmation. Review them and install again."), "warning");
          return;
        }
        executeBtn.textContent = window.t("install.installingBtn", "🚀 Installing mod...");
        const res = await fetch("/api/installer/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
          showToast(loc({ en: `Mod ${subfolder} successfully installed into ${targetCategory}!` }), "success");
          renderInstallResult(data);
          // Identity columns the package declared but the target overrides get
          // their own dialog: silently ignoring them is what made the
          // vehicles.ide merge look like it never ran.
          if (Array.isArray(data.ide_notes) && data.ide_notes.length) {
            showAppAlert(window.t("install.ideNotesTitle", "Package data was adjusted") + "\n\n" + data.ide_notes.join("\n"));
          }
          loadSystemStatus();
          loadMods();
        } else {
          const errMsg = data.error || (data.errors && data.errors.length ? data.errors.join("; ") : (t("common.unknownError")));
          showToast((loc({ en: "Install failed: " })) + errMsg, "error");
        }
      } catch (err) {
        showToast((loc({ en: "Install request error: " })) + err.message, "error");
      } finally {
        tuningInstallBusy = false;
        updateTuningSelectionSummary();
        executeBtn.textContent = window.t("install.btnConfirm", "Install");
      }
    });
  }

  // Go to Library button
  const gotoLibBtn = document.getElementById("btnGoToModLibrary");
  if (gotoLibBtn) {
    gotoLibBtn.addEventListener("click", () => {
      switchTab("modsTab");
      const searchInput = document.getElementById("modSearchInput");
      if (searchInput && currentInspectData) {
        searchInput.value = document.getElementById("installSubfolderName").value.trim();
        filterMods();
      }
    });
  }

  // Live Path Preview Event Listeners
  const catSelect = document.getElementById("installCategorySelect");
  const authorInput = document.getElementById("installAuthorFolder");
  const subfolderInput = document.getElementById("installSubfolderName");

  if (catSelect) {
    catSelect.addEventListener("change", async () => {
      persistCurrentPhaseDest();
      updateInstallPathPreview();
      refreshInstallAuthors(catSelect.value);
    });
  }

  if (authorInput) authorInput.addEventListener("input", () => {
    persistCurrentPhaseDest();
    updateInstallPathPreview();
  });
  if (subfolderInput) subfolderInput.addEventListener("input", () => {
    if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
      const cur = wizardVehicles[wizardCurrentIndex];
      const val = subfolderInput.value.trim();
      if (cur.folder_name) {
        cur.folder_name = val;
        const wizFolder = document.getElementById("installWizardCarFolder");
        if (wizFolder && document.activeElement !== wizFolder) {
          wizFolder.value = val;
        }
      } else {
        persistCurrentPhaseDest();
      }
    } else {
      persistCurrentPhaseDest();
    }
    updateInstallPathPreview(true);
  });

  document.querySelectorAll("#installChecklistFold input[type=checkbox]").forEach(cb => {
    cb.addEventListener("change", updateInstallChecklistSummary);
  });
}

function pathSegHtml(cat, author, sub) {
  const mid = author ? ` / <span class="path-author">${author}</span>` : "";
  return `modloader / <span class="path-cat">${cat}</span>${mid} / <span class="path-folder">${sub}</span>`;
}

function updateInstallPathPreview(preserveInputs = false) {
  const catSelect = document.getElementById("installCategorySelect");
  const authorInput = document.getElementById("installAuthorFolder");
  const subfolderInput = document.getElementById("installSubfolderName");
  const preview = document.getElementById("installPathLivePreview");
  const listEl = document.getElementById("installPathVehicleList");
  const listWrap = document.getElementById("installPathVehicleListWrap");

  if (!preview) return;

  const cat = (catSelect ? catSelect.value : "") || "Modded Cars";
  const author = (authorInput ? authorInput.value.trim() : "");
  const subfolder = (subfolderInput ? subfolderInput.value.trim() : "") || "...";

  if (wizardVehicles && wizardVehicles.length > 1) {
    const curWv = wizardVehicles[wizardCurrentIndex];
    if (curWv) {
      const rc = resolveVehicleDeploy(curWv);
      preview.innerHTML = pathSegHtml(rc.cat, rc.author, rc.sub);
    } else {
      preview.innerHTML = pathSegHtml(cat, author, subfolder);
    }
    if (listEl && listWrap) {
      listWrap.hidden = false;
      const lineFor = (wv, idx) => {
        if (!wv) return "";
        const r = resolveVehicleDeploy(wv);
        const tag = wv.skip
          ? window.t("install.skipShort", "Skip")
          : (r.split
            ? window.t("install.perCarFolderOwn", "separate")
            : window.t("install.perCarFolderShared", "shared"));
        const name = wv.vanilla_name || (wv.target_model || "").toUpperCase();
        const cur = (idx === wizardCurrentIndex) ? "▶ " : "";
        const mid = r.author ? ` / ${r.author}` : "";
        return `<div>${cur}${name} → modloader / ${r.cat}${mid} / ${r.sub} (${tag})</div>`;
      };
      let lines;
      if (hasBothPhases()) {
        const grp = (ph, key, fallback) => {
          const idxs = phaseVehicleIndices(ph);
          if (idxs.length === 0) return "";
          return `<div class="path-group-label">${window.t(key, fallback)}</div>`
            + idxs.map(i => lineFor(wizardVehicles[i], i)).join("");
        };
        lines = grp("replace", "install.groupReplace", "Replace vehicles") + grp("addon", "install.groupAddon", "Addon vehicles");
      } else {
        lines = wizardVehicles.map((wv, idx) => lineFor(wv, idx)).join("");
      }
      listEl.innerHTML = lines;
    }
  } else {
    preview.innerHTML = pathSegHtml(cat, author, subfolder);
    if (listWrap) listWrap.hidden = true;
  }
  refreshWizardFolderPreview(preserveInputs);
}

function updateInstallChecklistSummary() {
  const el = document.getElementById("installChecklistSummary");
  if (!el) return;
  const items = [
    ["chkCopyFiles", "dff/txd"],
    ["chkMergeHandling", "handling"],
    ["chkMergeCarcols", "carcols"],
    ["chkMergeCarmods", "carmods"],
    ["chkGenShopping", "shopping"],
    ["chkGenFxt", "fxt"],
    ["chkMergeFla", "FLA"]
  ];
  const on = items.filter(([id]) => {
    const cb = document.getElementById(id);
    return cb && cb.checked;
  }).map(([, label]) => label);
  el.textContent = on.length ? on.join(" · ") : window.t("install.checklistNone", "Nothing selected");
}

function refreshFxtInheritHint() {
  const hint = document.getElementById("installFxtInheritHint");
  if (!hint) return;
  const wv = (wizardVehicles && wizardVehicles.length > 1) ? wizardVehicles[wizardCurrentIndex] : null;
  const proposal = wv
    ? { inherited: wv.fxt_inherited, key: wv.fxt_inherit_key }
    : { inherited: singleFxtInherited, key: singleFxtInheritKey };
  const keyEl = document.getElementById("installFxtKey");
  const nameEl = document.getElementById("installFxtName");
  const overridden = Boolean((keyEl && keyEl.value.trim()) || (nameEl && nameEl.value.trim()));
  const show = Boolean(proposal.inherited) && !overridden;
  hint.style.display = show ? "block" : "none";
  if (show) {
    hint.textContent = window.t("install.fxtInheritHint",
      "Package reuses the game's own GXT entry ({0}); no name override will be written.")
      .replace("{0}", proposal.key || "");
  }
}

async function inspectModSource(sourcePath) {
  window.InstallAssets.reset();
  const step1 = document.getElementById("installStep1");
  const step2 = document.getElementById("installStep2");
  const step3 = document.getElementById("installStep3");
  const loading = document.getElementById("installLoading");

  step1.style.display = "none";
  step3.style.display = "none";
  loading.style.display = "block";

  try {
    const res = await fetch("/api/installer/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_path: sourcePath })
    });
    const data = await res.json();
    loading.style.display = "none";

    if (!data.success) {
      if (data.error_code === "seven_zip_missing") {
        window._sevenZipSessionDismissed = false;
        checkSevenZipBanner({ seven_zip: { found: false, download_url: data.download_url } });
        showToast(window.t("sevenzip.missingToast", data.error || "7-Zip not detected"), "error");
      } else {
        showToast(data.error || (loc({ en: "Pre-check failed" })), "error");
      }
      step1.style.display = "block";
      return;
    }

    currentInspectData = data;
    renderInstallStep2(data);
    step2.style.display = "block";
  } catch (err) {
    loading.style.display = "none";
    showToast((loc({ en: "Analysis request failed: " })) + err.message, "error");
    step1.style.display = "block";
  }
}

let wizardVehicles = [];
let wizardCurrentIndex = 0;
let wizardFormLoaded = false;
let currentVariantGroups = [];
let singleAddonId = null;
let addonIdCheckTimer = null;
// Split-phase install: replace and addon vehicles are configured in two
// separate phases (single flow, single backend call). There is deliberately
// NO stored phase variable: the phase is always derived from the currently
// selected vehicle, so pills / progress / tabs / destination list can never
// disagree with each other the way two synced states could.
let phaseDest = {
  replace: { category: "", author: "", subfolder: "" },
  addon: { category: "", author: "", subfolder: "" }
};
// Which phase the left destination card currently represents. Pills/tabs
// derive their phase from the selected vehicle; this tracks the card so the
// two cannot drift (e.g. Addon tab active while the card still shows
// Modded Cars from the replace phase).
let displayedDestPhase = null;

function phaseOfVehicle(wv) {
  if (!wv) return "replace";
  // The user's mode choice wins over the package kind: an addon package can
  // be installed as a replacement (files re-keyed onto a vanilla target), and
  // that vehicle belongs in the replace phase/destination.
  const mode = wv.install_mode || (isAddonModel(wv.source_model) ? "addon" : "replace");
  return mode === "addon" ? "addon" : "replace";
}

function phaseVehicleIndices(phase) {
  const out = [];
  (wizardVehicles || []).forEach((wv, idx) => {
    if (phaseOfVehicle(wv) === phase) out.push(idx);
  });
  return out;
}

function hasBothPhases() {
  return phaseVehicleIndices("replace").length > 0 && phaseVehicleIndices("addon").length > 0;
}

function currentPhase() {
  if (!hasBothPhases()) return null;
  return phaseOfVehicle(wizardVehicles[wizardCurrentIndex]);
}

function isAddonModel(m) {
  const ml = (m || "").toLowerCase();
  return !!ml && !vanillaVehicles.some(v => v.model.toLowerCase() === ml);
}

// ---------------- Install mode: replace vs addon conversion ----------------

let singleInstallMode = "replace";
// Single-install FXT state: a package that reuses the game's own GXT entry
// keeps both FXT fields empty and writes no name override.
let singleFxtInherited = false;
let singleFxtInheritKey = "";

function installTargetSourceModel() {
  if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
    return String(wizardVehicles[wizardCurrentIndex].source_model || "").toLowerCase();
  }
  return (currentInspectData && currentInspectData.target_model)
    ? String(currentInspectData.target_model).toLowerCase() : "";
}

function effectiveInstallTarget() {
  if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
    return String(wizardVehicles[wizardCurrentIndex].target_model || "").toLowerCase();
  }
  if (singleInstallMode === "addon") {
    const inp = document.getElementById("installNewModelName");
    return inp ? inp.value.trim().toLowerCase() : "";
  }
  const sel = document.getElementById("installVehicleSelect");
  return sel ? sel.value.toLowerCase() : "";
}

function effectiveInstallTxd() {
  if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
    return String(wizardVehicles[wizardCurrentIndex].target_txd || "").toLowerCase();
  }
  const inp = document.getElementById("installNewTxdName");
  return inp ? inp.value.trim().toLowerCase() : "";
}

function suggestAddonName(source) {
  const base = String(source || "car").toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^_+/, "") || "car";
  const taken = collectTakenModelNames();
  if (isAddonModel(base) && !taken.has(base)) {
    return base.slice(0, 20);
  }
  let candidate = base;
  for (let i = 2; i <= 99; i++) {
    const suffix = String(i);
    const maxLen = 20 - suffix.length;
    candidate = (base.length > maxLen ? base.slice(0, maxLen) : base) + suffix;
    if (!taken.has(candidate)) {
      return candidate;
    }
  }
  return candidate;
}

function validateCustomModelName(name, taken) {
  const n = String(name || "").trim().toLowerCase();
  if (!n) return "empty";
  if (!/^[a-z0-9_]{2,20}$/.test(n)) return "charset";
  if (taken && taken.has(n)) return "taken";
  return "";
}

function suggestHandlingId(model) {
  const base = String(model || "car").toUpperCase().replace(/[^A-Z0-9_]/g, "_").replace(/^_+/, "") || "CAR";
  return base.slice(0, 14);
}

function validateCustomHandlingId(value) {
  const v = String(value || "").trim();
  if (!v) return "empty";
  if (!/^[A-Za-z0-9_]{2,14}$/.test(v)) return "charset";
  return "";
}

function effectiveInstallHandling() {
  if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
    return String(wizardVehicles[wizardCurrentIndex].target_handling || "");
  }
  const inp = document.getElementById("installNewHandlingId");
  return inp ? inp.value.trim() : "";
}

// ---------------- Addon package -> replacement install (reverse conversion) ----------------

// Classes sharing a handling.cfg schema. Re-keying physics between families
// corrupts the target (car lines and bike lines have different columns).
const VEHICLE_CLASS_FAMILY = { car: "car", mtruck: "car", bike: "bike", bmx: "bike", quad: "bike" };

function installSourceType() {
  if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
    return String(wizardVehicles[wizardCurrentIndex].source_type || "").toLowerCase();
  }
  const src = installTargetSourceModel();
  if (!src) return "";
  const tvs = (currentInspectData && currentInspectData.target_vehicles) || [];
  const tv = tvs.find(t => String(t.target_model || t.model || "").toLowerCase() === src);
  return tv ? String(tv.type || "car").toLowerCase() : "";
}

// Core class check for one vehicle slot: returns mismatch info when an addon
// package would be re-keyed onto a vanilla target of another class (an install
// that would corrupt handling data).
function vehicleClassMismatch(mode, src, srcType, tgt) {
  if (mode !== "replace") return null;
  if (!src || !isAddonModel(src) || !srcType || !tgt) return null;
  const match = vanillaVehicles.find(v => v.model.toLowerCase() === tgt);
  if (!match) return null;
  const tgtType = String(match.type || "car").toLowerCase();
  if (VEHICLE_CLASS_FAMILY[srcType] === VEHICLE_CLASS_FAMILY[tgtType]) return null;
  return { srcType, tgtType, target: match };
}

// Returns info when the current replace target's vanilla class differs from
// the addon package's class.
function installClassMismatch() {
  return vehicleClassMismatch(
    currentInstallMode(),
    installTargetSourceModel(),
    installSourceType(),
    effectiveInstallTarget());
}

// Install-time guard: checks every active vehicle in wizard mode, or the
// single target otherwise.
function anyInstallClassMismatch() {
  if (wizardVehicles && wizardVehicles.length > 1) {
    for (const wv of wizardVehicles) {
      if (!wv || wv.skip) continue;
      const m = vehicleClassMismatch(
        wv.install_mode || "replace",
        String(wv.source_model || "").toLowerCase(),
        String(wv.source_type || "").toLowerCase(),
        String(wv.target_model || "").toLowerCase());
      if (m) return m;
    }
    return null;
  }
  return installClassMismatch();
}

// Surfaces the reverse-conversion hint and the class-mismatch error for the
// currently selected target. Called whenever the mode, target or inspection
// data changes.
// Default the GXT key of a converted addon package to the TARGET vanilla
// vehicle's key, so the replacement never overrides the vanilla vehicles.ide
// identity. The in-game name keeps the package's proposal (e.g. "ALPHA
// Recursion"), so the modded car stays identifiable in-game. A key the user
// typed manually is respected: only empty values or values this helper set
// earlier are overwritten.
function applyConversionNameDefaults(targetModel) {
  const fxtKey = document.getElementById("installFxtKey");
  const match = vanillaVehicles.find(v => v.model.toLowerCase() === (targetModel || "").toLowerCase());
  if (!match || !fxtKey) return;
  const cur = fxtKey.value.trim().toUpperCase();
  if (cur && cur !== String(fxtKey.dataset.autoKey || "").toUpperCase()) return;
  fxtKey.value = match.model.toUpperCase();
  fxtKey.dataset.autoKey = fxtKey.value;
}

function refreshInstallReplaceHint() {
  const hintEl = document.getElementById("installAddonReplaceHint");
  const errEl = document.getElementById("installClassMismatchError");
  const mode = currentInstallMode();
  const src = installTargetSourceModel();
  const converting = mode === "replace" && src && isAddonModel(src);
  if (hintEl) {
    if (converting) {
      const tgt = effectiveInstallTarget();
      const match = vanillaVehicles.find(v => v.model.toLowerCase() === tgt);
      const tgtName = match ? `${match.name} (${match.model.toUpperCase()})` : "";
      hintEl.textContent = window.t(
        "install.addonReplaceHint",
        "📦 Addon package installed as a replacement: DFF/TXD are renamed to {1}, and this package's handling, colors, tuning parts and FLA audio replace {0}'s vanilla data. The target's vehicles.ide entry (wheel size etc.) stays vanilla; the GXT key below names the target in-game."
      ).replace("{0}", tgtName).replace("{1}", tgt ? tgt.toUpperCase() : "--");
      hintEl.style.display = "block";
    } else {
      hintEl.style.display = "none";
    }
  }
  const mismatch = installClassMismatch();
  if (errEl) {
    if (mismatch) {
      errEl.textContent = window.t(
        "install.classMismatchError",
        "⚠️ Class mismatch: this package is a {0}, but {1} is a {2}. Physics and animation schemas differ between classes — pick a vanilla {0} target instead."
      ).split("{0}").join(mismatch.srcType)
       .split("{1}").join(mismatch.target.name)
       .split("{2}").join(mismatch.tgtType);
      errEl.style.display = "block";
    } else {
      errEl.style.display = "none";
    }
  }
  return mismatch;
}

function collectTakenModelNames(exceptModel) {
  const taken = new Set();
  (vanillaVehicles || []).forEach(v => taken.add(String(v.model).toLowerCase()));
  if (wizardVehicles && wizardVehicles.length > 1) {
    wizardVehicles.forEach((v, idx) => {
      if (!v || v.skip) return;
      if (idx === wizardCurrentIndex) return;
      const m = String(v.target_model || "").toLowerCase();
      if (m) taken.add(m);
    });
  } else {
    const tvs = (currentInspectData && currentInspectData.target_vehicles) || [];
    tvs.forEach(tv => {
      const m = String(tv.target_model || tv.model || "").toLowerCase();
      if (m) taken.add(m);
    });
  }
  if (exceptModel) {
    const ex = String(exceptModel).toLowerCase();
    const isVanilla = (vanillaVehicles || []).some(v => v.model.toLowerCase() === ex);
    if (!isVanilla) {
      taken.delete(ex);
    }
  }
  return taken;
}

function currentInstallMode() {
  if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
    return wizardVehicles[wizardCurrentIndex].install_mode || "replace";
  }
  return singleInstallMode;
}

function validateNewInstallName() {
  const errEl = document.getElementById("installNewNameError");
  const mode = currentInstallMode();
  if (mode !== "addon") {
    if (errEl) errEl.textContent = "";
    return true;
  }
  const name = effectiveInstallTarget();
  const txd = effectiveInstallTxd() || name;
  // A missing vanilla list makes every name look free; refuse instead of
  // approving an install that could collide with an existing model.
  let err = vanillaVehiclesReady
    ? validateCustomModelName(name, collectTakenModelNames(name))
    : "listUnavailable";
  if (!err && wizardVehicles && wizardVehicles.length > 1) {
    const dup = wizardVehicles.some((v, i) => v && i !== wizardCurrentIndex && !v.skip
      && (v.install_mode || "replace") === "addon"
      && String(v.target_model || "").toLowerCase() === name);
    if (dup) err = "duplicate";
  }
  if (!err && txd && !/^[a-z0-9_]{2,20}$/.test(txd)) err = "charset";
  const hid = effectiveInstallHandling();
  if (!err && hid && validateCustomHandlingId(hid)) err = "handling";
  const fxtKeyEl = document.getElementById("installFxtKey");
  const fxtVal = fxtKeyEl ? fxtKeyEl.value.trim().toUpperCase() : "";
  if (!err && fxtVal && !/^[A-Z0-9_]{2,7}$/.test(fxtVal)) err = "gxt";
  if (errEl) {
    errEl.textContent = err === "empty"
      ? window.t("install.newNameEmpty", "Please enter a new model name")
      : err === "charset"
        ? window.t("install.newNameCharset", "Model/texture names allow 2-20 lowercase letters, digits or underscores")
        : err === "duplicate"
          ? window.t("install.newNameDuplicate", "Multiple vehicles in this install share the same model name")
          : err === "taken"
            ? window.t("install.newNameTaken", "That name is already used by a vanilla or in-package vehicle")
            : err === "handling"
              ? window.t("install.newHandlingCharset", "Handling ID allows 2-14 letters, digits or underscores")
              : err === "gxt"
                ? window.t("install.newGxtKeyCharset", "GXT key allows 2-7 uppercase letters, digits or underscores")
                : err === "listUnavailable"
                  ? window.t("install.newNameListUnavailable", "The vanilla vehicle list has not loaded, so duplicate names cannot be checked; use Reload in the banner above")
                  : "";
  }
  return !err;
}

// Shared replace/addon toggle for the single form and the wizard's current car.
function setInstallMode(mode, opts = {}) {
  const m = mode === "addon" ? "addon" : "replace";
  const wizard = wizardVehicles && wizardVehicles.length > 1;
  const wv = wizard ? wizardVehicles[wizardCurrentIndex] : null;
  if (wizard && wv) wv.install_mode = m;
  else singleInstallMode = m;

  const toggle = document.getElementById("installModeToggle");
  if (toggle) {
    toggle.querySelectorAll(".install-mode-btn").forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-mode") === m);
    });
  }
  const replaceBtn = document.querySelector('#installModeToggle .install-mode-btn[data-mode="replace"]');
  if (replaceBtn) replaceBtn.disabled = false;

  const select = document.getElementById("installVehicleSelect");
  const fields = document.getElementById("installAddonNameFields");
  const nameInput = document.getElementById("installNewModelName");
  const txdInput = document.getElementById("installNewTxdName");
  if (select) select.style.display = m === "addon" ? "none" : "";
  const pickerBar = document.getElementById("installVehiclePickerBar");
  if (pickerBar) pickerBar.style.display = m === "addon" ? "none" : "";
  if (fields) fields.style.display = m === "addon" ? "block" : "none";

  const src = installTargetSourceModel();
  if (m === "addon") {
    const curName = (wizard && wv ? wv.target_model : (nameInput ? nameInput.value : "")) || "";
    const curTxd = (wizard && wv ? wv.target_txd : (txdInput ? txdInput.value : "")) || "";
    let newName = String(curName).trim().toLowerCase();
    if (!newName || (!isAddonModel(newName) && !opts.keepName)) newName = suggestAddonName(src);
    let newTxd = String(curTxd).trim().toLowerCase();
    if (!newTxd || newTxd === String(curName).trim().toLowerCase()) newTxd = newName;
    if (wizard && wv) {
      wv.target_model = newName;
      wv.target_txd = newTxd;
    }
    if (nameInput) nameInput.value = newName;
    if (txdInput) txdInput.value = newTxd;

    // Internal handling identifier (handling.cfg first column + IDE Handling
    // column). Defaults to the model name; follows the model until edited.
    const hInp = document.getElementById("installNewHandlingId");
    if (hInp) {
      const curH = (wizard && wv ? wv.target_handling : hInp.value) || "";
      if (hInp.dataset.auto !== "0" || !String(curH).trim()) {
        hInp.value = suggestHandlingId(newName);
        hInp.dataset.auto = "1";
      } else {
        hInp.value = String(curH).trim().toUpperCase();
      }
      if (wizard && wv) wv.target_handling = hInp.value;
    }

    const fxtKey = document.getElementById("installFxtKey");
    // A vehicle that inherits the game's own GXT entry keeps both FXT fields
    // empty (no rename is written), so nothing may auto-fill them here.
    const fxtInherited = (wizard && wv && wv.fxt_inherited) || (!wizard && singleFxtInherited);
    if (fxtKey) {
      if (fxtInherited) {
        fxtKey.value = "";
      } else if (opts.keepName && wizard && wv && wv.fxt_key) {
        fxtKey.value = wv.fxt_key;
      } else if (!fxtKey.value.trim() || fxtKey.value.trim().toLowerCase() === src) {
        fxtKey.value = newName.toUpperCase().slice(0, 7);
      }
    }
    if (wizard && wv && fxtKey && !fxtInherited) wv.fxt_key = fxtKey.value.trim().toUpperCase();
    syncDefaultCategoryToTarget(newName);
  } else if (wizard && wv) {
    if (select && (!select.value || isAddonModel(select.value))) {
      if (isAddonModel(wv.source_model)) {
        // Reverse conversion: pre-select a same-class vanilla target so the
        // user starts from a compatible vehicle and only adjusts if needed.
        const srcType = String(wv.source_type || "").toLowerCase();
        const srcFamily = VEHICLE_CLASS_FAMILY[srcType] || srcType;
        const sameClass = vanillaVehicles.find(v => (v.type || "car") === srcType)
          || vanillaVehicles.find(v => (VEHICLE_CLASS_FAMILY[v.type || "car"] || v.type || "car") === srcFamily)
          || vanillaVehicles[0];
        select.value = sameClass ? sameClass.model : (wv.source_model || "");
      } else {
        select.value = wv.source_model || "";
      }
      if (select.value) select.dispatchEvent(new Event("change", { bubbles: true }));
      if (isAddonModel(wv.source_model)) {
        // A converted wizard car keeps the TARGET's vanilla GXT key by
        // default (vanilla IDE untouched) while the in-game name stays the
        // package's proposal; a manually chosen key is respected.
        const m0 = vanillaVehicles.find(v => v.model.toLowerCase() === (select.value || "").toLowerCase());
        if (m0 && (!wv.fxt_key || String(wv.fxt_key).toUpperCase() === String(wv.fxt_key_auto || "").toUpperCase())) {
          wv.fxt_key = m0.model.toUpperCase();
          wv.fxt_key_auto = wv.fxt_key;
          const fkEl = document.getElementById("installFxtKey");
          if (fkEl) fkEl.value = wv.fxt_key;
        }
      }
    }
    const selVal = (select ? select.value : "").toLowerCase();
    if (selVal) wv.target_model = selVal;
    wv.target_txd = "";
    syncDefaultCategoryToTarget(wv.target_model);
  } else {
    if (select && isAddonModel(installTargetSourceModel()) && (!select.value || isAddonModel(select.value))) {
      // Single install reverse conversion: same-class vanilla preselect. The
      // package-proposal GXT key counts as an auto value, so it can be
      // re-defaulted to the target's vanilla identity below.
      const fxtKeyEl0 = document.getElementById("installFxtKey");
      if (fxtKeyEl0 && fxtKeyEl0.value.trim().toUpperCase() === installTargetSourceModel().toUpperCase()) {
        fxtKeyEl0.dataset.autoKey = fxtKeyEl0.value;
      }
      const srcType = installSourceType();
      const sameClass = vanillaVehicles.find(v => (v.type || "car") === srcType)
        || vanillaVehicles.find(v => (VEHICLE_CLASS_FAMILY[v.type || "car"] || v.type || "car") === (VEHICLE_CLASS_FAMILY[srcType] || srcType))
        || vanillaVehicles[0];
      if (sameClass) {
        select.value = sameClass.model;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    syncDefaultCategoryToTarget(effectiveInstallTarget());
  }
  refreshAddonIdRow();
  validateNewInstallName();
  refreshInstallReplaceHint();
  applyVehiclePickerFilter();
}

// Promise-based themed confirm dialog. Replaces window.confirm so every
// confirmation shares the app's modal style and a stable app title.
function showAppConfirm(message) {
  return new Promise(resolve => {
    const modal = document.getElementById("appConfirmModal");
    const msgEl = document.getElementById("appConfirmMessage");
    const okBtn = document.getElementById("appConfirmOk");
    const cancelBtn = document.getElementById("appConfirmCancel");
    const closeBtn = document.getElementById("appConfirmClose");
    if (!modal || !okBtn || !cancelBtn) {
      resolve(window.confirm(message));
      return;
    }
    if (msgEl) msgEl.textContent = message;
    let done = false;
    const finish = (result) => {
      if (done) return;
      done = true;
      modal.classList.remove("active");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      if (closeBtn) closeBtn.removeEventListener("click", onCancel);
      resolve(result);
    };
    const onOk = () => finish(true);
    const onCancel = () => finish(false);
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    if (closeBtn) closeBtn.addEventListener("click", onCancel);
    modal.classList.add("active");
  });
}

// Promise-based themed alert dialog: the confirm dialog's look with a single
// acknowledgement button, so a warning cannot be missed in a toast.
function showAppAlert(message) {
  return new Promise(resolve => {
    const modal = document.getElementById("appAlertModal");
    const msgEl = document.getElementById("appAlertMessage");
    const okBtn = document.getElementById("appAlertOk");
    const closeBtn = document.getElementById("appAlertClose");
    if (!modal || !okBtn) {
      window.alert(message);
      resolve();
      return;
    }
    if (msgEl) msgEl.textContent = message;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      modal.classList.remove("active");
      okBtn.removeEventListener("click", finish);
      if (closeBtn) closeBtn.removeEventListener("click", finish);
      resolve();
    };
    okBtn.addEventListener("click", finish);
    if (closeBtn) closeBtn.addEventListener("click", finish);
    modal.classList.add("active");
  });
}

function setupInstallModeControls() {
  const toggle = document.getElementById("installModeToggle");
  if (toggle) {
    toggle.querySelectorAll(".install-mode-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (btn.disabled) return;
        const mode = btn.getAttribute("data-mode");
        // Entering replace mode on an addon package flips the install from a
        // self-contained addon to overwriting a vanilla vehicle. Confirm so a
        // stray click cannot silently start that conversion.
        if (mode === "replace" && currentInstallMode() !== "replace" && isAddonModel(installTargetSourceModel())) {
          const go = await showAppConfirm(window.t(
            "install.addonReplaceConfirm",
            "Install this addon package as a replacement? Its model files will be renamed to the selected vanilla vehicle, and its handling, colors, tuning parts and FLA audio will replace that vehicle's data. Continue?"
          ));
          if (!go) return;
        }
        syncCurrentWizardFormToState();
        setInstallMode(mode);
      });
    });
  }
  const nameInput = document.getElementById("installNewModelName");
  if (nameInput) {
    nameInput.addEventListener("input", () => {
      let val = nameInput.value.trim().toLowerCase().replace(/[^a-z0-9_]/g, "_");
      if (val !== nameInput.value) nameInput.value = val;
      const txdInput = document.getElementById("installNewTxdName");
      if (txdInput) {
        const prevModel = (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex])
          ? String(wizardVehicles[wizardCurrentIndex].target_model || "").toLowerCase() : "";
        const curTxd = txdInput.value.trim().toLowerCase();
        if (!curTxd || curTxd === prevModel || curTxd === (document.getElementById("installNewModelName").dataset.lastAuto || "")) {
          txdInput.value = val;
        }
      }
      nameInput.dataset.lastAuto = val;
      const hAuto = document.getElementById("installNewHandlingId");
      if (hAuto && hAuto.dataset.auto !== "0") {
        hAuto.value = suggestHandlingId(val);
      }
      if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
        wizardVehicles[wizardCurrentIndex].target_model = val;
        wizardVehicles[wizardCurrentIndex].target_txd = (document.getElementById("installNewTxdName") || {}).value
          ? document.getElementById("installNewTxdName").value.trim().toLowerCase() : val;
        // A vehicle that inherits the game's own GXT entry keeps its GXT key
        // empty, so renaming must not fill it back in.
        if (!wizardVehicles[wizardCurrentIndex].fxt_inherited) {
          wizardVehicles[wizardCurrentIndex].fxt_key = val.toUpperCase().slice(0, 7);
        }
        if (hAuto) wizardVehicles[wizardCurrentIndex].target_handling = hAuto.value;
      }
      const fxtKey = document.getElementById("installFxtKey");
      const inheritsFxtKey = Boolean(wizardVehicles && wizardVehicles.length > 1
        && wizardVehicles[wizardCurrentIndex] && wizardVehicles[wizardCurrentIndex].fxt_inherited);
      if (fxtKey && !inheritsFxtKey && (!fxtKey.value.trim() || fxtKey.value.trim().length <= val.length)) {
        fxtKey.value = val.toUpperCase().slice(0, 7);
      }
      const renameHint = document.getElementById("installModelRenameHint");
      if (renameHint) {
        const src = installTargetSourceModel();
        renameHint.style.display = (val && src && val !== src) ? "block" : "none";
      }
      syncDefaultCategoryToTarget(val);
      refreshAddonIdRow();
      validateNewInstallName();
    });
  }
  const txdInput = document.getElementById("installNewTxdName");
  if (txdInput) {
    txdInput.addEventListener("input", () => {
      let val = txdInput.value.trim().toLowerCase().replace(/[^a-z0-9_]/g, "_");
      if (val !== txdInput.value) txdInput.value = val;
      if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
        wizardVehicles[wizardCurrentIndex].target_txd = val;
      }
      validateNewInstallName();
    });
  }
  const fxtKeyInput = document.getElementById("installFxtKey");
  if (fxtKeyInput) fxtKeyInput.addEventListener("input", refreshFxtInheritHint);
  const fxtNameInput = document.getElementById("installFxtName");
  if (fxtNameInput) fxtNameInput.addEventListener("input", refreshFxtInheritHint);
  const hInput = document.getElementById("installNewHandlingId");
  if (hInput) {
    hInput.addEventListener("input", () => {
      let val = hInput.value.trim().toUpperCase().replace(/[^A-Z0-9_]/g, "_");
      if (val !== hInput.value) hInput.value = val;
      hInput.dataset.auto = "0";
      if (wizardVehicles && wizardVehicles.length > 1 && wizardVehicles[wizardCurrentIndex]) {
        wizardVehicles[wizardCurrentIndex].target_handling = val;
      }
      validateNewInstallName();
    });
  }
  const vSearch = document.getElementById("installVehicleSearch");
  if (vSearch) {
    vSearch.addEventListener("input", () => {
      vehiclePickerSearch = vSearch.value;
      applyVehiclePickerFilter();
    });
  }
  const vType = document.getElementById("installVehicleTypeFilter");
  if (vType) {
    vType.addEventListener("change", () => {
      vehiclePickerType = vType.value;
      applyVehiclePickerFilter();
    });
  }
}

function paintBadgeFor(model, addonIdOrNull) {
  const badge = document.getElementById("installModelBadge");
  if (!badge) return;
  const ml = (model || "").toLowerCase();
  const match = vanillaVehicles.find(v => v.model.toLowerCase() === ml);
  if (match) {
    badge.textContent = `ID: ${match.id} (${match.name})`;
  } else if (addonIdOrNull != null && addonIdOrNull !== "") {
    badge.textContent = `${window.t("inspect.targetIdBadgePrefixAddon", "Addon ID: ")}${addonIdOrNull}`;
  } else {
    badge.textContent = `ID: --`;
  }
}

function refreshAddonOptionText(model, id) {
  const sel = document.getElementById("installVehicleSelect");
  if (!sel) return;
  const ml = (model || "").toLowerCase();
  const opt = [...sel.options].find(o => (o.value || "").toLowerCase() === ml);
  if (opt && opt.dataset.dname) {
    const idTxt = (id != null && id !== "") ? id : (loc({ en: "unassigned" }));
    const tag = opt.dataset.dtype
      ? window.t("install.optionAddonTypedTag", " [{0} · Addon]")
          .replace("{0}", window.t("veh." + opt.dataset.dtype, opt.dataset.dtype))
      : window.t("install.optionAddonTag", " [Addon]");
    opt.textContent = `${opt.dataset.dname} (${ml.toUpperCase()} - ID: ${idTxt})${tag}`;
  }
}

// Slot for the addon-ID editor: current wizard vehicle or single-install target
function currentAddonSlot() {
  if (wizardVehicles && wizardVehicles.length > 1) {
    const wv = wizardVehicles[wizardCurrentIndex];
    if (!wv || !isAddonModel(wv.target_model)) return null;
    return { model: wv.target_model, get: () => wv.addon_id, set: (x) => { wv.addon_id = x; } };
  }
  const tm = effectiveInstallTarget();
  if (!isAddonModel(tm)) return null;
  return { model: tm, get: () => singleAddonId, set: (x) => { singleAddonId = x; } };
}

function refreshAddonIdRow() {
  const row = document.getElementById("installAddonIdRow");
  const input = document.getElementById("installAddonIdInput");
  if (!row || !input) return;
  const slot = currentAddonSlot();
  if (!slot) { row.style.display = "none"; refreshAddonIdSummary(); return; }
  row.style.display = "block";
  const cur = slot.get();
  if (document.activeElement !== input) input.value = (cur != null ? cur : "");
  paintBadgeFor(slot.model, cur);
  scheduleAddonIdCheck();
  refreshAddonIdSummary();
}

function scheduleAddonIdCheck() {
  clearTimeout(addonIdCheckTimer);
  addonIdCheckTimer = setTimeout(checkAddonIdLive, 350);
}

async function checkAddonIdLive() {
  const status = document.getElementById("installAddonIdStatus");
  const input = document.getElementById("installAddonIdInput");
  const slot = currentAddonSlot();
  if (!status || !input || !slot) return;
  const raw = (input.value || "").trim();
  const v = parseInt(raw, 10);
  if (!raw || isNaN(v) || v < 612 || v > 65535) {
    status.textContent = window.t("install.addonIdInvalid", "⚠️ Enter an ID between 612–65535");
    status.style.color = "var(--accent-amber)";
    return;
  }
  try {
    const res = await fetch(`/api/ids/check?id=${v}`);
    const data = await res.json();
    const r = data && data.result;
    const cap = await ensureKillableLimit();
    const overCap = (cap != null && v >= cap);
    const overTxt = overCap
      ? window.t("install.addonIdOverKillable", "⛔ ID {0} exceeds the FLA killable limit {1}; kills may not register or the game may crash. Lower it or raise the ini").replace("{0}", v).replace("{1}", cap)
      : "";
    if (data.success && r && r.is_free) {
      if (overCap) {
        status.textContent = overTxt;
        status.style.color = "#f85149";
      } else {
        status.textContent = window.t("install.addonIdFree", "🟢 ID {0} is free").replace("{0}", v);
        status.style.color = "var(--accent-emerald)";
      }
    } else if (r && !r.is_free && ((r.name || "").toLowerCase() === slot.model.toLowerCase())) {
      if (overCap) {
        status.textContent = overTxt;
        status.style.color = "#f85149";
      } else {
        status.textContent = window.t("install.addonIdSelf", "🟢 ID {0} already belongs to this vehicle").replace("{0}", v);
        status.style.color = "var(--accent-emerald)";
      }
    } else {
      const who = (r && (r.name || r.file)) || "";
      status.textContent = window.t("install.addonIdTaken", "🔴 ID {0} occupied ({1})").replace("{0}", v).replace("{1}", who);
      status.style.color = "#f85149";
    }
  } catch (e) {
    status.textContent = "";
  }
}

function collectAddonIdAssignments() {
  const map = {};
  if (wizardVehicles && wizardVehicles.length > 1) {
    wizardVehicles.forEach(wv => {
      if (wv && !wv.skip && isAddonModel(wv.target_model) && wv.addon_id != null && wv.addon_id !== "") {
        map[wv.target_model.toLowerCase()] = parseInt(wv.addon_id, 10);
      }
    });
  } else {
    const slot = currentAddonSlot();
    if (slot && slot.get() != null && slot.get() !== "") {
      map[slot.model.toLowerCase()] = parseInt(slot.get(), 10);
    }
  }
  return map;
}

function refreshAddonIdSummary() {
  const el = document.getElementById("installAddonIdSummaryHint");
  if (!el) return;

  const pairs = [];
  const seen = new Set();
  if (wizardVehicles && wizardVehicles.length > 0) {
    wizardVehicles.forEach(wv => {
      if (!wv) return;
      const tm = (wv.target_model || wv.source_model || "").toLowerCase();
      if (isAddonModel(tm) && !seen.has(tm)) {
        seen.add(tm);
        const idVal = (wv.addon_id != null && wv.addon_id !== "") ? wv.addon_id : (wv.proposed_addon_id != null ? wv.proposed_addon_id : "—");
        pairs.push(`${tm} → ${idVal}`);
      }
    });
  } else {
    const slot = currentAddonSlot();
    if (slot && isAddonModel(slot.model)) {
      const idVal = (slot.get() != null && slot.get() !== "") ? slot.get() : "—";
      pairs.push(`${slot.model} → ${idVal}`);
    } else if (currentInspectData && currentInspectData.addon_id_proposals) {
      Object.entries(currentInspectData.addon_id_proposals).forEach(([m, id]) => {
        const ml = m.toLowerCase();
        if (isAddonModel(ml) && !seen.has(ml)) {
          seen.add(ml);
          pairs.push(`${ml} → ${id}`);
        }
      });
    }
  }

  if (pairs.length > 0) {
    el.innerHTML = `${window.t("install.addonIdTitle", "🆔 Addon vehicle ID assignment:")} ${pairs.join(" · ")}`;
    el.style.display = "block";
  } else {
    el.style.display = "none";
  }
}

function syncCurrentWizardFormToState() {
  if (!wizardVehicles || wizardVehicles.length <= 1) return;
  if (!wizardFormLoaded) return;
  const curr = wizardVehicles[wizardCurrentIndex];
  if (!curr) return;

  const selVeh = document.getElementById("installVehicleSelect");
  const currMode = curr.install_mode || "replace";
  if (currMode === "addon") {
    const nameInp = document.getElementById("installNewModelName");
    const txdInp = document.getElementById("installNewTxdName");
    const hidInp = document.getElementById("installNewHandlingId");
    if (nameInp) curr.target_model = nameInp.value.trim().toLowerCase();
    if (txdInp) curr.target_txd = txdInp.value.trim().toLowerCase() || curr.declared_txd || curr.target_model;
    if (hidInp) curr.target_handling = hidInp.value.trim().toUpperCase();
  } else if (selVeh && selVeh.value) {
    curr.target_model = selVeh.value.toLowerCase();
    const vMatch = vanillaVehicles.find(v => v.model.toLowerCase() === curr.target_model);
    if (vMatch) curr.vanilla_name = vMatch.name;
  }

  const fxtKey = document.getElementById("installFxtKey");
  if (fxtKey) curr.fxt_key = fxtKey.value.trim();

  const fxtName = document.getElementById("installFxtName");
  if (fxtName) curr.fxt_name = fxtName.value.trim();

  const chkCopy = document.getElementById("chkCopyFiles");
  if (chkCopy) curr.copy_files = chkCopy.checked;

  const chkH = document.getElementById("chkMergeHandling");
  if (chkH) curr.merge_handling = chkH.checked;

  const chkC = document.getElementById("chkMergeCarcols");
  if (chkC) curr.merge_carcols = chkC.checked;

  const chkM = document.getElementById("chkMergeCarmods");
  if (chkM) curr.merge_carmods = chkM.checked;

  const chkShop = document.getElementById("chkGenShopping");
  if (chkShop) curr.generate_shopping = chkShop.checked;

  const chkFxt = document.getElementById("chkGenFxt");
  if (chkFxt) curr.generate_fxt = chkFxt.checked;

  const chkFla = document.getElementById("chkMergeFla");
  if (chkFla) curr.merge_fla = chkFla.checked;

  const chkSkip = document.getElementById("chkSkipCurrentCar");
  if (chkSkip) curr.skip = chkSkip.checked;

  const wizFolder = document.getElementById("installWizardCarFolder");
  if (wizFolder && curr) curr.folder_name = wizFolder.value.trim();
  const wizCat = document.getElementById("installWizardCarCategory");
  if (wizCat && curr) curr.category = wizCat.value;

  curr.tuning_id_assignments = collectTuningIdAssignments();

  const addonInp = document.getElementById("installAddonIdInput");
  if (addonInp && curr && isAddonModel(curr.target_model)) {
    const raw = (addonInp.value || "").trim();
    const nn = parseInt(raw, 10);
    curr.addon_id = (!raw || isNaN(nn)) ? null : nn;
  }

  curr.is_configured = true;
  refreshAddonIdSummary();
}

function sharedDeployInputs() {
  const catSel = document.getElementById("installCategorySelect");
  const authorInp = document.getElementById("installAuthorFolder");
  const sharedInp = document.getElementById("installSubfolderName");
  return {
    cat: (catSel && catSel.value) || "Modded Cars",
    author: ((authorInp && authorInp.value) || "").trim(),
    shared: ((sharedInp && sharedInp.value) || "").trim() || "..."
  };
}

function phaseSharedInputs(phase) {
  const live = sharedDeployInputs();
  if (!phase || !phaseDest[phase]) return live;
  // Live form is the source of truth only for the phase currently shown
  // on the left card (user may be typing in shared mode).
  const curWv = (wizardVehicles && wizardVehicles[wizardCurrentIndex]);
  if (phase === displayedDestPhase && (!curWv || !curWv.folder_name)) return live;
  const pd = phaseDest[phase];
  return {
    cat: (pd.category || "").trim() || live.cat,
    author: (pd.author || "").trim(),
    shared: (pd.subfolder || "").trim() || live.shared
  };
}

function resolveVehicleDeploy(wv) {
  const s = phaseSharedInputs(phaseOfVehicle(wv));
  const ownFolder = ((wv.folder_name) || "").trim();
  const ownCat = ((wv.category) || "").trim();
  return {
    cat: ownCat || s.cat, author: s.author, shared: s.shared,
    ownFolder, ownCat, sub: ownFolder || s.shared,
    split: !!(ownFolder || ownCat)
  };
}

function wizardResolvedFolder() {
  if (!wizardVehicles || wizardVehicles.length <= 1) return null;
  const wv = wizardVehicles[wizardCurrentIndex];
  if (!wv) return null;
  const r = resolveVehicleDeploy(wv);
  return { cat: r.cat, author: r.author, shared: r.shared, own: r.ownFolder, sub: r.sub };
}

function refreshWizardCategoryOptions() {
  const sel = document.getElementById("installWizardCarCategory");
  if (!sel || !wizardVehicles || wizardVehicles.length <= 1) return;
  const wv = wizardVehicles[wizardCurrentIndex];
  if (!wv) return;
  const s = phaseSharedInputs(phaseOfVehicle(wv));
  const folders = (appStatus && appStatus.modloader_folders) || [s.cat];
  const followTxt = `${window.t("install.perCarFolderShared", "shared")} (${s.cat})`;
  let html = `<option value="">${followTxt}</option>`;
  folders.forEach(f => {
    if (!f) return;
    html += `<option value="${f}">${f}</option>`;
  });
  const cur = (wv.category || "").trim();
  sel.innerHTML = html;
  sel.value = folders.includes(cur) ? cur : "";
  if (sel.value !== cur && cur) {
    const opt = document.createElement("option");
    opt.value = cur;
    opt.textContent = cur;
    sel.appendChild(opt);
    sel.value = cur;
  }
}

function refreshWizardFolderPreview(preserveInputs = false) {
  const inp = document.getElementById("installWizardCarFolder");
  const prev = document.getElementById("installWizardCarFolderPreview");
  if (!inp || !prev) return;
  if (!wizardVehicles || wizardVehicles.length <= 1) return;
  const wv = wizardVehicles[wizardCurrentIndex];
  const r = wizardResolvedFolder();
  if (!wv || !r) return;
  if (!preserveInputs && document.activeElement !== inp) inp.value = wv.folder_name || "";
  // Make the blank-means-follow semantics unmistakable: the placeholder shows
  // the exact shared name this car currently follows.
  try {
    inp.placeholder = window.t("install.perCarFolderPlaceholderDyn", "Empty = shared: {0}").replace("{0}", r.shared);
  } catch (e) {}
  if (!preserveInputs) refreshWizardCategoryOptions();
  const tag = r.split
    ? window.t("install.perCarFolderOwn", "separate")
    : window.t("install.perCarFolderShared", "shared");
  const mid = r.author ? ` / ${r.author}` : "";
  prev.innerHTML = `modloader / ${r.cat}${mid} / <b style="color:var(--accent-emerald);">${r.sub}</b> (${tag})`;

  const subInp = document.getElementById("installSubfolderName");
  if (subInp && !preserveInputs && document.activeElement !== subInp) {
    subInp.value = wv.folder_name || r.shared || "";
  }
}

function loadWizardVehicleToForm(targetIdx, skipSync = false) {
  if (!wizardVehicles || targetIdx < 0 || targetIdx >= wizardVehicles.length) return;
  if (!skipSync && wizardFormLoaded) syncCurrentWizardFormToState();
  // Drop input focus first so the focus-guarded editors below always load the
  // newly selected vehicle instead of keeping the previous one's text.
  try {
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  } catch (e) {}
  const nextWv = wizardVehicles[targetIdx];
  const nextPhase = hasBothPhases() ? phaseOfVehicle(nextWv) : null;
  if (nextPhase) syncDestCardToPhase(nextPhase);
  wizardCurrentIndex = targetIdx;
  const v = wizardVehicles[targetIdx];

  // Update vehicle select
  const vehSelect = document.getElementById("installVehicleSelect");
  if (vehSelect) {
    vehSelect.value = v.target_model;
    // Keep the newly selected car visible even when a search/class filter is
    // active; otherwise the pinned option would be hidden for this car only.
    applyVehiclePickerFilter();
  }

  // Replace / addon mode for this vehicle (custom model + TXD names)
  const wizardModeName = document.getElementById("installNewModelName");
  const wizardModeTxd = document.getElementById("installNewTxdName");
  const wizardModeHandling = document.getElementById("installNewHandlingId");
  if (wizardModeName) wizardModeName.value = isAddonModel(v.target_model) ? v.target_model : "";
  if (wizardModeTxd) wizardModeTxd.value = v.target_txd || (isAddonModel(v.target_model) ? v.target_model : "");
  if (wizardModeHandling) {
    const derivedH = isAddonModel(v.target_model) ? suggestHandlingId(v.target_model) : "";
    wizardModeHandling.value = v.target_handling || derivedH;
    wizardModeHandling.dataset.auto = (!v.target_handling || v.target_handling === derivedH) ? "1" : "0";
  }
  setInstallMode(v.install_mode || (isAddonModel(v.source_model) ? "addon" : "replace"), { keepName: true });

  // Update badge & rename hint
  const badge = document.getElementById("installModelBadge");
  const match = vanillaVehicles.find(item => item.model.toLowerCase() === v.target_model.toLowerCase());
  if (badge) {
    if (match) {
      badge.textContent = `ID: ${match.id} (${match.name})`;
    } else {
      paintBadgeFor(v.target_model, (v.addon_id != null ? v.addon_id : v.proposed_addon_id));
    }
  }

  const renameHint = document.getElementById("installModelRenameHint");
  if (renameHint) {
    renameHint.style.display = (v.target_model.toLowerCase() !== v.source_model.toLowerCase()) ? "block" : "none";
  }

  // Update FXT
  const fxtKey = document.getElementById("installFxtKey");
  if (fxtKey) fxtKey.value = v.fxt_key;

  const fxtName = document.getElementById("installFxtName");
  if (fxtName) fxtName.value = v.fxt_name;
  refreshFxtInheritHint();

  // Update Checkboxes
  const chkCopy = document.getElementById("chkCopyFiles");
  if (chkCopy) chkCopy.checked = v.copy_files;

  const chkH = document.getElementById("chkMergeHandling");
  if (chkH) chkH.checked = v.merge_handling;

  const chkC = document.getElementById("chkMergeCarcols");
  if (chkC) chkC.checked = v.merge_carcols;

  const chkM = document.getElementById("chkMergeCarmods");
  if (chkM) chkM.checked = v.merge_carmods;

  const chkShop = document.getElementById("chkGenShopping");
  if (chkShop) chkShop.checked = v.generate_shopping;

  const chkFxt = document.getElementById("chkGenFxt");
  if (chkFxt) chkFxt.checked = v.generate_fxt;

  const chkFla = document.getElementById("chkMergeFla");
  if (chkFla) chkFla.checked = v.merge_fla;

  const chkSkip = document.getElementById("chkSkipCurrentCar");
  if (chkSkip) chkSkip.checked = v.skip;

  refreshAddonIdRow();
  refreshWizardFolderPreview();
  updateInstallPathPreview();

  renderWizardNavigation();
  wizardFormLoaded = true;
}

// Text/navigation only; never reload the editable vehicle form on translation.
function renderWizardNavigation() {
  const targetIdx = wizardCurrentIndex;
  const v = wizardVehicles[targetIdx];
  if (!v) return;
  // Update Stepper track and progress (phase derived from current vehicle)
  const progressBadge = document.getElementById("installWizardProgressBadge");
  if (progressBadge) {
    const ph = currentPhase();
    if (ph) {
      const list = phaseVehicleIndices(ph);
      const pos = list.indexOf(targetIdx) + 1;
      const phLabel = ph === "addon"
        ? window.t("install.phaseAddon", "② Addon")
        : window.t("install.phaseReplace", "① Replace");
      progressBadge.textContent = `${phLabel} ${pos} / ${list.length}`;
    } else {
      progressBadge.textContent = window.t("install.wizardProgress", "Vehicle {0} of {1}").replace("{0}", targetIdx + 1).replace("{1}", wizardVehicles.length);
    }
  }

  const currentCarSpan = document.getElementById("installWizardCurrentCarName");
  if (currentCarSpan) {
    currentCarSpan.textContent = `${v.vanilla_name} (${v.source_model.toUpperCase()})`;
  }

  // Prev / Next button states (phase-aware when split: last replace car
  // continues into the addon phase instead of ending)
  const btnPrev = document.getElementById("btnWizardPrevCar");
  const btnNext = document.getElementById("btnWizardNextCar");
  const navList = currentPhase() ? phaseVehicleIndices(currentPhase()) : wizardVehicles.map((_, i) => i);
  const posInNav = navList.indexOf(targetIdx);
  if (btnPrev) {
    const prevPh = currentPhase();
    if (prevPh && posInNav === 0) {
      const other = prevPh === "addon" ? phaseVehicleIndices("replace") : [];
      if (other.length > 0) {
        btnPrev.disabled = false;
        btnPrev.textContent = window.t("install.backPhaseBtn", "⬅️ Back to replace");
        btnPrev.onclick = () => switchWizardPhase("replace", true);
      } else {
        btnPrev.disabled = true;
      }
    } else {
      btnPrev.disabled = (posInNav <= 0);
      btnPrev.textContent = window.t("install.btnPrevCar", "Previous");
      btnPrev.onclick = () => { if (posInNav > 0) loadWizardVehicleToForm(navList[posInNav - 1]); };
    }
  }

  if (btnNext) {
    const nextPh = currentPhase();
    if (nextPh && posInNav === navList.length - 1) {
      if (nextPh === "replace" && phaseVehicleIndices("addon").length > 0) {
        btnNext.textContent = window.t("install.nextPhaseBtn", "Next: addon vehicles ➡️");
        btnNext.disabled = false;
        btnNext.onclick = () => switchWizardPhase("addon", false);
      } else {
        btnNext.textContent = t("common.lastVehicle");
        btnNext.disabled = true;
        btnNext.onclick = null;
      }
    } else if (posInNav >= 0 && posInNav < navList.length - 1) {
      btnNext.textContent = window.t("install.btnNextCar", "Next");
      btnNext.disabled = false;
      btnNext.onclick = () => loadWizardVehicleToForm(navList[posInNav + 1]);
    } else {
      btnNext.textContent = t("common.lastVehicle");
      btnNext.disabled = true;
      btnNext.onclick = null;
    }
  }

  renderPhaseTabs();
  renderWizardStepsTrack();
}

function renderPhaseTabs() {
  const bar = document.getElementById("installPhaseTabs");
  if (!bar) return;
  const curPh = currentPhase();
  if (!curPh) { bar.style.display = "none"; bar.innerHTML = ""; return; }
  bar.style.display = "flex";
  const nR = phaseVehicleIndices("replace").length;
  const nA = phaseVehicleIndices("addon").length;
  const tR = window.t("install.phaseReplace", "① Replace");
  const tA = window.t("install.phaseAddon", "② Addon");
  bar.innerHTML = "";
  [["replace", `${tR} (${nR})`], ["addon", `${tA} (${nA})`]].forEach(([ph, label]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "phase-tab-btn" + (curPh === ph ? " active" : "");
    b.textContent = label;
    b.onclick = () => switchWizardPhase(ph, false);
    bar.appendChild(b);
  });
  refreshDestPhaseBadge();
}

function switchWizardPhase(phase, toLast) {
  if (!hasBothPhases() || (phase !== "replace" && phase !== "addon")) return;
  const list = phaseVehicleIndices(phase);
  if (list.length === 0) return;
  loadWizardVehicleToForm(toLast ? list[list.length - 1] : list[0]);
}

function persistCurrentPhaseDest() {
  const ph = displayedDestPhase || currentPhase();
  if (ph) savePhaseDest(ph);
}

function refreshDestPhaseBadge() {
  const badge = document.getElementById("installDestPhaseBadge");
  if (!badge) return;
  const ph = hasBothPhases() ? (displayedDestPhase || currentPhase()) : null;
  if (!ph) {
    badge.style.display = "none";
    badge.textContent = "";
    return;
  }
  badge.style.display = "inline-block";
  badge.textContent = ph === "addon"
    ? window.t("install.phaseAddon", "② Addon")
    : window.t("install.phaseReplace", "① Replace");
}

function ensureCategoryOption(selectEl, folderName) {
  if (!selectEl || !folderName) return;
  if ([...selectEl.options].some(o => o.value === folderName)) return;
  const opt = document.createElement("option");
  opt.value = folderName;
  opt.textContent = folderName;
  selectEl.appendChild(opt);
}

async function refreshInstallAuthors(category) {
  if (!category) return;
  try {
    const res = await fetch(`/api/installer/authors?category=${encodeURIComponent(category)}`);
    const d = await res.json();
    if (d.success && d.authors) {
      const authorDatalist = document.getElementById("existingAuthorsList");
      if (authorDatalist) {
        authorDatalist.innerHTML = "";
        d.authors.forEach(auth => {
          const opt = document.createElement("option");
          opt.value = auth;
          authorDatalist.appendChild(opt);
        });
      }
    }
  } catch (err) {}
}

// Single install: keep the destination category aligned with the target kind
// (addon -> Addon folder, replace -> replacement folder). Only flips between
// the two default folders so a custom category chosen by the user is kept.
// Wizard mode handles this per phase through the destination card instead.
function syncDefaultCategoryToTarget(targetModel) {
  if (wizardVehicles && wizardVehicles.length > 1) return;
  const catSel = document.getElementById("installCategorySelect");
  const replaceCat = (appStatus && appStatus.data_folder) || "Modded Cars";
  const addonCat = (appStatus && appStatus.addon_folder) || "Addon Cars";
  if (!catSel || replaceCat === addonCat) return;
  const selModel = (targetModel || "").toLowerCase();
  if (isAddonModel(selModel) && catSel.value === replaceCat) {
    ensureCategoryOption(catSel, addonCat);
    catSel.value = addonCat;
    refreshInstallAuthors(addonCat);
    updateInstallPathPreview();
  } else if (!isAddonModel(selModel) && catSel.value === addonCat) {
    ensureCategoryOption(catSel, replaceCat);
    catSel.value = replaceCat;
    refreshInstallAuthors(replaceCat);
    updateInstallPathPreview();
  }
}

// Swap the left destination card to match the vehicle's phase. Save the
// card first so typing in Modded Cars isn't lost when jumping to Addon Cars.
function syncDestCardToPhase(nextPhase) {
  if (!nextPhase || !phaseDest[nextPhase]) return;
  if (displayedDestPhase === nextPhase) {
    refreshDestPhaseBadge();
    return;
  }
  if (displayedDestPhase) savePhaseDest(displayedDestPhase);
  displayedDestPhase = nextPhase;
  loadPhaseDest(nextPhase);
  refreshDestPhaseBadge();
}

// Per-phase shared destination (category/author/subfolder inputs). The left
// cards always edit the CURRENT phase; switching vehicles/phases saves/loads them.
function savePhaseDest(phase) {
  if (!phase || !phaseDest[phase]) return;
  const cat = document.getElementById("installCategorySelect");
  const author = document.getElementById("installAuthorFolder");
  const sub = document.getElementById("installSubfolderName");
  const curWv = (wizardVehicles && wizardVehicles[wizardCurrentIndex]);
  const subVal = (curWv && curWv.folder_name)
    ? (phaseDest[phase].subfolder || "")
    : (sub ? sub.value : "");
  phaseDest[phase] = {
    category: cat ? cat.value : "",
    author: author ? author.value : "",
    subfolder: subVal
  };
}

function loadPhaseDest(phase) {
  if (!phase || !phaseDest[phase]) return;
  const d = phaseDest[phase];
  const cat = document.getElementById("installCategorySelect");
  const author = document.getElementById("installAuthorFolder");
  const sub = document.getElementById("installSubfolderName");
  if (cat && d.category) {
    ensureCategoryOption(cat, d.category);
    cat.value = d.category;
    refreshInstallAuthors(d.category);
  }
  if (author) author.value = d.author || "";
  const curWv = (wizardVehicles && wizardVehicles[wizardCurrentIndex]);
  if (sub) {
    sub.value = (curWv && curWv.folder_name) ? curWv.folder_name : (d.subfolder || "");
  }
  refreshDestPhaseBadge();
  updateInstallPathPreview();
}

function renderWizardStepsTrack() {
  const track = document.getElementById("installMultiCarStepsTrack");
  if (!track || !wizardVehicles) return;

  track.innerHTML = "";
  const ph = currentPhase();
  const list = ph ? phaseVehicleIndices(ph) : wizardVehicles.map((_, i) => i);
  list.forEach((idx, pos) => {
    const v = wizardVehicles[idx];
    if (!v) return;
    const chip = document.createElement("div");
    let stateClass = "";
    if (idx === wizardCurrentIndex) {
      stateClass = "active";
    } else if (v.skip) {
      stateClass = "skipped";
    } else if (v.is_configured) {
      stateClass = "configured";
    }

    chip.className = `wizard-step-chip ${stateClass}`;
    const skipMark = v.skip ? (loc({ en: " (Skip)" })) : "";
    chip.innerHTML = `<span>${pos + 1}. ${v.vanilla_name}${skipMark}</span>`;
    chip.addEventListener("click", () => {
      loadWizardVehicleToForm(idx);
    });
    track.appendChild(chip);
  });
}

function refreshInstallerLanguage() {
  // The inspection initializes defaults once. Language changes must not call
  // setData/reset or rebuild wizardVehicles, IDs, names, paths and checkboxes.
  updateInstallChecklistSummary();
  updateInstallPathPreview(true);
  refreshAddonIdSummary();
  renderWizardNavigation();
  const filesBadge = document.getElementById("installTotalFilesBadge");
  const partsBadge = document.getElementById("installTuningBadge");
  const data = currentInspectData;
  if (data && filesBadge) {
    const count = ["primary_dffs", "primary_txds", "tuning_dffs", "tuning_txds", "readme_files", "other_files"]
      .reduce((total, key) => total + (data[key] || []).length, 0);
    filesBadge.textContent = window.t("install.filesCount", "{0}").replace("{0}", count);
  }
  if (data && partsBadge) {
    const count = (data.tuning_parts_analysis || []).filter(p => p.status !== "registered").length;
    partsBadge.textContent = window.t("install.partsCount", "{0}").replace("{0}", count);
  }
  if (window.InstallAssets) updateExcludedFilesBadge(window.InstallAssets.getExcludedFiles().size);
  if (currentInspectData) renderVariantPicker(currentInspectData, true);
}

// ---------------- Vehicle picker: search box + class filter ----------------

// Class order for the filter dropdown; classes missing from the data are
// skipped, unknown ones are appended alphabetically.
const VEHICLE_TYPE_ORDER = ["car", "bike", "bmx", "quad", "heli", "plane", "boat", "trailer", "train"];
let vehiclePickerOptions = [];   // { opt, value, type, isAddon, haystack }
let vehiclePickerSearch = "";
let vehiclePickerType = "";

// Options are filtered through the `hidden` attribute instead of being removed
// from the DOM, so the select's value — and every option element other code
// (e.g. refreshAddonOptionText) mutates in place — stays valid regardless of
// the active filter.
function applyVehiclePickerFilter() {
  const sel = document.getElementById("installVehicleSelect");
  if (!sel) return;
  const q = vehiclePickerSearch.trim().toLowerCase();
  // A package-owned addon model is only a legal target while that vehicle is
  // installed as an addon. Offered as a replacement it reads as an installed
  // vehicle the game does not have - and picking it would replace nothing.
  const addonOffered = currentInstallMode() === "addon";
  let visible = 0;
  vehiclePickerOptions.forEach(e => {
    // Addon entries carry a class from the pack's vehicles.ide line (parsed
    // backend-side) and filter exactly like vanilla entries.
    const typeOk = !vehiclePickerType || e.type === vehiclePickerType;
    const textOk = !q || e.haystack.includes(q);
    const show = typeOk && textOk && (addonOffered || !e.isAddon);
    e.opt.hidden = !show;
    if (show) visible++;
  });
  // Keep the current selection visible even when it no longer matches, so the
  // target model never silently changes behind the user's back. This also
  // covers a selected addon target under a class filter it doesn't match.
  const cur = (sel.value || "").toLowerCase();
  if (cur) {
    const entry = vehiclePickerOptions.find(x => x.value === cur);
    if (entry && entry.opt.hidden) { entry.opt.hidden = false; visible++; }
  }
  const empty = document.getElementById("installVehiclePickerEmpty");
  if (empty) empty.style.display = (visible || !vehiclePickerOptions.length) ? "none" : "block";
}

function renderVehicleTypeFilterOptions() {
  const typeSel = document.getElementById("installVehicleTypeFilter");
  if (!typeSel) return;
  const present = new Set();
  vehiclePickerOptions.forEach(e => present.add(e.type));
  const ordered = VEHICLE_TYPE_ORDER.filter(t => present.has(t));
  [...present].filter(t => !VEHICLE_TYPE_ORDER.includes(t)).sort().forEach(t => ordered.push(t));
  typeSel.innerHTML = "";
  const allOpt = document.createElement("option");
  allOpt.value = "";
  allOpt.textContent = window.t("install.typeAll", "All classes");
  typeSel.appendChild(allOpt);
  ordered.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = window.t("veh." + t, t);
    typeSel.appendChild(opt);
  });
  if (ordered.includes(vehiclePickerType)) {
    typeSel.value = vehiclePickerType;
  } else {
    vehiclePickerType = "";
    typeSel.value = "";
  }
}

function renderInstallStep2(data) {
  window.InstallAssets.setData(data, vanillaVehicles);
  updateExcludedFilesBadge(0);
  const isMultiCar = data.target_vehicles && data.target_vehicles.length > 1;
  const wizardBar = document.getElementById("installMultiCarWizardBar");
  const btnPrev = document.getElementById("btnWizardPrevCar");
  const btnNext = document.getElementById("btnWizardNextCar");

  // Populate vehicle select dropdown
  const vehSelect = document.getElementById("installVehicleSelect");
  vehSelect.innerHTML = "";
  vehiclePickerOptions = [];

  const defaultModel = (data.target_model || "infernus").toLowerCase();

  vanillaVehicles.forEach(v => {
    const opt = document.createElement("option");
    opt.value = v.model;
    opt.textContent = `${v.name} (${v.model.toUpperCase()} - ID: ${v.id}) [${window.t("veh." + (v.type || "car"), v.type || "car")}]`;
    if (v.model.toLowerCase() === defaultModel) {
      opt.selected = true;
    }
    vehSelect.appendChild(opt);
    vehiclePickerOptions.push({
      opt,
      value: v.model.toLowerCase(),
      type: (v.type || "car").toLowerCase(),
      isAddon: false,
      haystack: `${v.name} ${v.model} ${v.id}`.toLowerCase(),
    });
  });

  // Addon models are not in the vanilla list: append them so the select can
  // actually represent (and keep) an addon target instead of going blank.
  // Their class comes from the package's vehicles.ide line when present
  // (parser default: "car"), so class filtering covers addon entries too.
  if (data.target_vehicles) {
    data.target_vehicles.forEach(tv => {
      const am = (tv.target_model || tv.model || "").toLowerCase();
      if (!am) return;
      if (vanillaVehicles.some(v => v.model.toLowerCase() === am)) return;
      if (vehiclePickerOptions.some(e => e.value === am)) return;
      const opt = document.createElement("option");
      opt.value = am;
      const aName = tv.name || am.toUpperCase();
      const aId = tv.proposed_addon_id ? `ID: ${tv.proposed_addon_id}` : `ID: ${loc({ en: "unassigned" })}`;
      const aType = String(tv.type || "car").toLowerCase();
      const aTypeText = window.t("veh." + aType, aType);
      opt.dataset.dname = aName;
      opt.dataset.dtype = aType;
      opt.textContent = `${aName} (${am.toUpperCase()} - ${aId})${window.t("install.optionAddonTypedTag", " [{0} · Addon]").replace("{0}", aTypeText)}`;
      if (am === defaultModel) opt.selected = true;
      vehSelect.appendChild(opt);
      vehiclePickerOptions.push({
        opt,
        value: am,
        type: aType,
        isAddon: true,
        haystack: `${aName} ${am} ${tv.proposed_addon_id ?? ""} ${tv.id ?? ""}`.toLowerCase(),
      });
    });
  }

  renderVehicleTypeFilterOptions();
  applyVehiclePickerFilter();

  const badge = document.getElementById("installModelBadge");
  const match = vanillaVehicles.find(v => v.model.toLowerCase() === defaultModel);
  if (match) {
    badge.textContent = `ID: ${match.id} (${match.name})`;
    singleAddonId = null;
  } else {
    const tvMatch0 = (data.target_vehicles || []).find(tv => ((tv.target_model || tv.model || "").toLowerCase() === defaultModel));
    singleAddonId = (tvMatch0 && tvMatch0.proposed_addon_id) || null;
    paintBadgeFor(defaultModel, singleAddonId);
  }
  document.getElementById("installModelRenameHint").style.display = "none";
  refreshAddonIdRow();

  // Category select
  const catSelect = document.getElementById("installCategorySelect");
  const addonCatName = (appStatus && appStatus.addon_folder) || "Addon Cars";
  catSelect.innerHTML = "";
  if (appStatus && appStatus.modloader_folders) {
    appStatus.modloader_folders.forEach(f => {
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      if (f === appStatus.data_folder) opt.selected = true;
      catSelect.appendChild(opt);
    });
  } else {
    const opt = document.createElement("option");
    opt.value = "Modded Cars";
    opt.textContent = "Modded Cars";
    catSelect.appendChild(opt);
  }

  // Addon-only packages belong under the Addon folder. Mixed packs are handled
  // per phase below; without this, single/all-addon packs inherit the
  // replacement shadow folder (Modded Cars) by default.
  const inspectTargets = data.target_vehicles || [];
  const hasAddonTarget = inspectTargets.some(tv => isAddonModel(tv.target_model || tv.model));
  const hasReplaceTarget = inspectTargets.some(tv => !isAddonModel(tv.target_model || tv.model));
  if (inspectTargets.length > 0 && hasAddonTarget && !hasReplaceTarget) {
    ensureCategoryOption(catSelect, addonCatName);
    catSelect.value = addonCatName;
    refreshInstallAuthors(addonCatName);
  }

  // Author Folder & Datalist
  const authorInput = document.getElementById("installAuthorFolder");
  if (authorInput) {
    authorInput.value = data.detected_author || "";
  }

  const authorDatalist = document.getElementById("existingAuthorsList");
  if (authorDatalist) {
    authorDatalist.innerHTML = "";
    if (data.existing_authors && data.existing_authors.length > 0) {
      data.existing_authors.forEach(auth => {
        const opt = document.createElement("option");
        opt.value = auth;
        authorDatalist.appendChild(opt);
      });
    }
  }

  // Folder name
  document.getElementById("installSubfolderName").value = data.proposed_folder_name;

  // Update live preview
  updateInstallPathPreview();

  // File breakdown
  const totalFiles = data.primary_dffs.length + data.primary_txds.length + data.tuning_dffs.length + data.tuning_txds.length + data.readme_files.length + data.other_files.length;
  document.getElementById("installTotalFilesBadge").textContent = window.t("install.filesCount", "{0} files").replace("{0}", totalFiles);

  const breakdownDiv = document.getElementById("installFilesBreakdown");
  const dffN = (data.primary_dffs || []).length;
  const txdN = (data.primary_txds || []).length;
  const tuneN = (data.tuning_dffs || []).length + (data.tuning_txds || []).length;
  // Keep the compact badge aligned with the existing Readme-file count.
  // The details dialog still exposes every text-like file in the package.
  const readmeN = (data.readme_files || []).length;
  const cfg = data.parsed_config || {};
  const cfgBits = [];
  if ((cfg.handling_cfg || []).length) cfgBits.push("handling");
  if ((cfg.carcols_dat || []).length) cfgBits.push("carcols");
  if ((cfg.carmods_dat || []).length) cfgBits.push("carmods");
  if ((cfg.special_features || []).length || (cfg.vehicle_audio || []).length) cfgBits.push("FLA");
  const chip = (n, key, label) => `<button type="button" class="asset-chip asset-chip-button${n ? " has-data" : ""}" data-asset-category="${key}" aria-haspopup="dialog" aria-controls="installAssetDialog" ${n ? "" : "disabled"}>${n} <span data-i18n="${label}">${window.t(label, label)}</span></button>`;
  let bHtml = `<div class="asset-chip-row">
    ${chip(dffN, "models", "install.assetModels")}
    ${chip(txdN, "textures", "install.assetTextures")}
    ${chip(tuneN, "tuning", "install.assetTuning")}
    ${chip(readmeN, "documents", "install.assetReadme")}
    ${(data.asset_files.other || []).length ? chip(data.asset_files.other.length, "other", "assets.other") : ""}
    ${cfgBits.length ? `<button type="button" class="asset-chip asset-chip-button has-data" data-asset-category="configs" aria-haspopup="dialog" aria-controls="installAssetDialog">${cfgBits.join(" · ")}</button>` : ""}
  </div>`;
  bHtml += `<div id="installAddonIdSummaryHint" class="field-hint" style="margin-top:8px; display:none;"></div>`;
  if (data.addon_name_conflicts && data.addon_name_conflicts.length > 0) {
    bHtml += `<div class="asset-note">${window.t("install.addonNameConflict", "These models collide with vanilla names and will install as replace (rename for true addon):")}${data.addon_name_conflicts.map(c => `${c.model}`).join(" · ")}</div>`;
  }
  breakdownDiv.innerHTML = bHtml;
  updateInstallChecklistSummary();

  // Multi-version variant picker (same-name files in variant subfolders)
  renderVariantPicker(data);

  // Tuning Parts & ID Assignment
  const tuningCard = document.getElementById("installTuningCard");
  const tuningBadge = document.getElementById("installTuningBadge");
  const conflictAlert = document.getElementById("installTuningConflictAlert");

  const customParts = (data.tuning_parts_analysis || []).filter(p => p.status !== "registered");
  if (customParts.length > 0) {
    if (tuningCard) tuningCard.style.display = "block";
    if (tuningBadge) tuningBadge.textContent = window.t("install.partsCount", "{0} parts").replace("{0}", customParts.length);
    const hasConflict = customParts.some(p => p.is_conflict);
    if (conflictAlert) conflictAlert.style.display = "none";
  } else {
    if (tuningCard) tuningCard.style.display = "none";
  }
  renderTuningPartsTable(customParts);

  // Multi-vehicle wizard initialization
  const sharedCatNow = (catSelect.value || "Modded Cars");
  if (isMultiCar) {
    wizardVehicles = data.target_vehicles.map((tv, idx) => {
      const model = (tv.target_model || tv.model || "infernus").toLowerCase();
      const vMatch = vanillaVehicles.find(v => v.model.toLowerCase() === model);
      const isAddonCar = isAddonModel((tv.source_model || tv.model || "").toLowerCase());
      // An addon keeps the TXD the author declared in vehicles.ide; only when
      // the package declares none does the name default to the model itself.
      const declaredTxd = String(tv.declared_txd || "").toLowerCase();
      const fxtProposal = tv.fxt_proposal || {};
      const fxtInherited = Boolean(fxtProposal.inherited);
      return {
        index: idx,
        source_model: (tv.source_model || tv.model || "").toLowerCase(),
        source_type: String(tv.type || "car").toLowerCase(),
        target_model: model,
        proposed_addon_id: tv.proposed_addon_id || null,
        addon_id: tv.proposed_addon_id || null,
        folder_name: "",
        category: "",
        vanilla_name: vMatch ? vMatch.name : (tv.name || model.toUpperCase()),
        // A package that points at a key the game already defines inherits that
        // display name: leave both fields empty and write no .fxt override.
        fxt_inherited: fxtInherited,
        fxt_inherit_key: fxtProposal.key || "",
        fxt_key: fxtInherited ? "" : (fxtProposal.key || model.toUpperCase()).slice(0, 7),
        fxt_key_auto: fxtInherited ? "" : (fxtProposal.key || model.toUpperCase()).slice(0, 7),
        fxt_name: fxtInherited ? "" : (fxtProposal.name || (vMatch ? vMatch.name : data.proposed_folder_name)),
        copy_files: true,
        merge_handling: tv.has_handling !== false,
        merge_carcols: tv.has_carcols !== false,
        merge_carmods: tv.has_carmods !== false,
        generate_shopping: true,
        generate_fxt: !fxtInherited,
        merge_fla: true,
        tuning_id_assignments: {},
        skip: Boolean(tv.alternative_of),
        alternative_of: tv.alternative_of || "",
        install_mode: isAddonCar ? "addon" : "replace",
        declared_txd: declaredTxd,
        target_txd: isAddonCar ? (declaredTxd || model) : "",
        target_handling: "",
        is_configured: false
      };
    });
    const altHintEl = document.getElementById("installAlternativeHint");
    if (altHintEl) {
      const alts = (data.target_vehicles || []).filter(tv => tv.alternative_of);
      if (alts.length) {
        altHintEl.style.display = "";
        altHintEl.textContent = alts.map(tv => window.t("install.alternativeHint", "This package ships the same car in multiple install modes: [{0}] and [{1}] are the same vehicle. [{0}] is skipped by default; uncheck \"Skip this vehicle\" to install it instead.").replace("{0}", String(tv.target_model || tv.model || "").toUpperCase())
         .replace("{1}", String(tv.alternative_of).toUpperCase())).join(" ");
      } else {
        altHintEl.style.display = "none";
        altHintEl.textContent = "";
      }
    }
    wizardCurrentIndex = 0;
    displayedDestPhase = null;
    wizardFormLoaded = false;
    // Split phases when the pack mixes both kinds: each phase owns its own
    // shared destination. Addon cars follow the Addon folder by default;
    // replace cars follow Modded Cars. Switching vehicles/tabs swaps the
    // left destination card so it always matches the phase in view.
    const authorVal = (authorInput && authorInput.value) || "";
    const subVal = data.proposed_folder_name || "";
    phaseDest.replace = { category: sharedCatNow, author: authorVal, subfolder: subVal };
    phaseDest.addon = { category: addonCatName || sharedCatNow, author: authorVal, subfolder: subVal };
    if (hasBothPhases()) {
      ensureCategoryOption(catSelect, addonCatName);
      displayedDestPhase = "replace";
      loadPhaseDest("replace");
    }
    if (wizardBar) wizardBar.style.display = "block";
    if (btnPrev) btnPrev.style.display = "inline-block";
    if (btnNext) btnNext.style.display = "inline-block";
    // Open the wizard on the first vehicle that will actually be installed so
    // a default-skipped alternative version does not take over the form.
    const firstActiveIdx = wizardVehicles.findIndex(wv => !wv.skip);
    loadWizardVehicleToForm(firstActiveIdx >= 0 ? firstActiveIdx : (hasBothPhases() ? phaseVehicleIndices("replace")[0] : 0), true);
  } else {
    wizardVehicles = [];
    wizardCurrentIndex = 0;
    displayedDestPhase = null;
    wizardFormLoaded = false;
    phaseDest.replace = { category: "", author: "", subfolder: "" };
    phaseDest.addon = { category: "", author: "", subfolder: "" };
    refreshDestPhaseBadge();
    const altHintEl = document.getElementById("installAlternativeHint");
    if (altHintEl) {
      altHintEl.style.display = "none";
      altHintEl.textContent = "";
    }
    if (wizardBar) wizardBar.style.display = "none";
    if (btnPrev) btnPrev.style.display = "none";
    if (btnNext) btnNext.style.display = "none";

    const singleFxt = data.fxt_proposal || {};
    const singleFxtInheritedHere = Boolean(singleFxt.inherited);
    singleFxtInherited = singleFxtInheritedHere;
    singleFxtInheritKey = singleFxt.key || "";
    document.getElementById("installFxtKey").value = singleFxtInheritedHere ? "" : (singleFxt.key || defaultModel.toUpperCase()).slice(0, 7);
    document.getElementById("installFxtName").value = singleFxtInheritedHere ? "" : (singleFxt.name || data.proposed_folder_name);
    document.getElementById("chkCopyFiles").checked = true;
    document.getElementById("chkMergeHandling").checked = true;
    document.getElementById("chkMergeCarcols").checked = true;
    document.getElementById("chkMergeCarmods").checked = true;
    document.getElementById("chkGenShopping").checked = true;
    document.getElementById("chkGenFxt").checked = !singleFxtInheritedHere;
    document.getElementById("chkMergeFla").checked = true;
    refreshFxtInheritHint();

    // Single install: initialize replace/addon mode and name fields.
    const singleIsAddon = isAddonModel(defaultModel);
    singleInstallMode = singleIsAddon ? "addon" : "replace";
    const modeNameInput = document.getElementById("installNewModelName");
    const modeTxdInput = document.getElementById("installNewTxdName");
    const modeHandlingInput = document.getElementById("installNewHandlingId");
    const singleTv = (data.target_vehicles || []).find(tv => ((tv.target_model || tv.model || "").toLowerCase() === defaultModel));
    const singleDeclaredTxd = String((singleTv && singleTv.declared_txd) || "").toLowerCase();
    if (modeNameInput) modeNameInput.value = singleIsAddon ? defaultModel : "";
    if (modeTxdInput) modeTxdInput.value = singleIsAddon ? (singleDeclaredTxd || defaultModel) : "";
    if (modeHandlingInput) {
      modeHandlingInput.value = singleIsAddon ? suggestHandlingId(defaultModel) : "";
      modeHandlingInput.dataset.auto = singleIsAddon ? "1" : "0";
    }
    setInstallMode(singleInstallMode, { keepName: true });
  }
  refreshAddonIdSummary();
}

function renderVariantPicker(data, preserveChoices = false) {
  const choices = preserveChoices ? collectVariantChoices() : {};
  currentVariantGroups = (data && data.variant_groups) || [];
  const card = document.getElementById("installVariantCard");
  const list = document.getElementById("installVariantGroups");
  const badge = document.getElementById("installVariantBadge");
  if (!card || !list) return;

  if (currentVariantGroups.length === 0) {
    card.style.display = "none";
    return;
  }
  card.style.display = "block";
  if (badge) badge.textContent = window.t("install.variantGroupCount", "{0} version groups").replace("{0}", currentVariantGroups.length);
  list.innerHTML = "";

  currentVariantGroups.forEach((g, gi) => {
    const kindLabel = g.kind === "vehicle"
      ? window.t("install.variantKindVehicle", "🚗 Vehicle")
      : window.t("install.variantKindTuning", "🛠️ Tuning");
    const groupEl = document.createElement("div");
    groupEl.className = "variant-group";
    let optsHtml = "";
    (g.options || []).forEach((op, oi) => {
      const kb = op.size ? `${(op.size / 1024).toFixed(1)} KB` : "--";
      const checked = (Object.prototype.hasOwnProperty.call(choices, g.key)
        ? choices[g.key] === op.rel : oi === 0) ? "checked" : "";
      optsHtml += `
        <label class="variant-option">
          <input type="radio" name="variant__${gi}" data-gkey="${g.key}" data-rel="${op.rel}" ${checked}>
          <span class="variant-dir">${op.dir}</span>
          <span class="variant-size">${kb}</span>
        </label>`;
    });
    groupEl.innerHTML = `
      <div class="variant-group-title">
        <span class="variant-filename">${g.name}</span>
        <span class="variant-kind">${kindLabel}</span>
      </div>
      <div class="variant-options">${optsHtml}</div>`;
    list.appendChild(groupEl);
  });

  // Variant tags: strip the common parent-dir prefix inside each group so
  // options get short comparable labels, e.g. "Rancher" vs
  // "Rancher/offroad wheels" -> "Standard" vs "offroad wheels".
  const stdLabel = window.t("install.variantStandard", "Standard");
  const groupTags = currentVariantGroups.map(g => {
    const segs = (g.options || []).map(op => String(op.dir || "").split("/").filter(Boolean));
    let common = 0;
    while (segs.length > 0 && segs.every(s => s.length > common && s[common] === segs[0][common])) common++;
    return segs.map(s => s.slice(common).join("/") || stdLabel);
  });
  // Quick-pick buttons: union of tags across groups, most common first.
  const tagFreq = new Map();
  groupTags.forEach(tags => { new Set(tags).forEach(t => tagFreq.set(t, (tagFreq.get(t) || 0) + 1)); });
  const tagList = [...tagFreq.entries()].sort((a, b) => (b[1] - a[1]) || (a[0] < b[0] ? -1 : 1)).slice(0, 8).map(e => e[0]);
  const quickRow = document.getElementById("variantQuickRow");
  if (quickRow) {
    quickRow.innerHTML = "";
    const pickLabel = window.t("install.variantQuickPick", "All");
    tagList.forEach(tag => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn-secondary btn-sm";
      b.textContent = `${pickLabel} ${tag}`;
      b.title = tag;
      b.style.maxWidth = "220px";
      b.style.overflow = "hidden";
      b.style.textOverflow = "ellipsis";
      b.style.whiteSpace = "nowrap";
      b.onclick = () => {
        currentVariantGroups.forEach((g, gi) => {
          const idx = groupTags[gi].indexOf(tag);
          if (idx >= 0) {
            const radio = list.querySelector(`input[name="variant__${gi}"]` + `[data-rel="${CSS.escape(g.options[idx].rel)}"]`);
            if (radio) radio.checked = true;
          }
        });
      };
      quickRow.appendChild(b);
    });
  }
}

function collectVariantChoices() {
  const choices = {};
  document.querySelectorAll('#installVariantGroups input[type="radio"]:checked').forEach(r => {
    if (r.dataset.gkey && r.dataset.rel) choices[r.dataset.gkey] = r.dataset.rel;
  });
  return choices;
}

function renderInstallResult(data) {
  document.getElementById("installStep2").style.display = "none";
  document.getElementById("installStep3").style.display = "block";

  const body = document.getElementById("installResultBody");
  const depListTitle = window.t("install.deployedFilesList", "📦 Deployed Files ({0}):").replace("{0}", data.copied_files_count);
  const upListTitle = window.t("install.updatedConfigsList", "📝 Updated Configurations ({0}):").replace("{0}", data.applied_configs.length);
  const depTo = window.t("install.deployedTo", "Successfully deployed to:");
  const warnTitle = window.t("install.mergeWarnings", "Warnings:");

  const multiCarBadge = (data.target_models && data.target_models.length > 1)
    ? `<div style="margin-bottom:12px; font-size:13px;"><span class="badge badge-success" style="font-size:12px;">${window.t("install.resultMultiPack", "🚗 Multi-vehicle pack ({0} vehicles):").replace("{0}", data.vehicles_count)}</span> <strong style="color:var(--accent-emerald); font-size:14px; margin-left:6px;">${data.target_models.join(", ").toUpperCase()}</strong></div>`
    : "";

  body.innerHTML = `
    ${multiCarBadge}
    <div style="font-size:14px; margin-bottom:14px;">
      ${depTo} ${(data.installed_paths && data.installed_paths.length > 1)
        ? `<div style="margin-top:6px; display:flex; flex-direction:column; gap:2px;">${data.installed_paths.map(p => `<code style="color:var(--accent-cyan); font-weight:700;">${p}</code>`).join("")}</div>`
        : `<code style="color:var(--accent-cyan); font-weight:700;">${data.installed_path}</code>`}
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:14px;">
      <div style="background:#090d16; border:1px solid var(--border); border-radius:6px; padding:12px;">
        <h5 style="color:var(--accent-emerald); margin-bottom:6px;">${depListTitle}</h5>
        <div style="max-height:120px; overflow-y:auto; font-size:12px; color:var(--text-main);">
          ${data.copied_files.map(f => `<div>✓ ${f}</div>`).join("")}
        </div>
      </div>
      <div style="background:#090d16; border:1px solid var(--border); border-radius:6px; padding:12px;">
        <h5 style="color:var(--accent-cyan); margin-bottom:6px;">${upListTitle}</h5>
        <div style="max-height:120px; overflow-y:auto; font-size:12px; color:var(--text-main);">
          ${data.applied_configs.map(f => `<div>✓ ${f}</div>`).join("")}
        </div>
      </div>
    </div>
    ${data.errors && data.errors.length > 0 ? `<div class="alert-box warning">${warnTitle} ${data.errors.join("; ")}</div>` : ''}
    ${data.warnings && data.warnings.length > 0 ? `<div class="alert-box warning" style="margin-top:10px;">⚠️ ${window.t("install.variantWarnings", "Same-name multi-version files detected, auto-selected one (details):")}<br>${data.warnings.join("<br>")}</div>` : ''}
  `;

  const btnOpen = document.getElementById("btnOpenInstalledFolder");
  if (btnOpen) {
    btnOpen.onclick = async () => {
      try {
        await fetch("/api/open-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: data.installed_path })
        });
      } catch (err) {
        showToast(loc({ en: "Failed to open folder" }), "error");
      }
    };
  }
}

// ---------------- Tuning Parts Table & Live ID Check ----------------

let tuningValidationGeneration = 0;
let tuningValidationTimer = null;
let tuningInstallBusy = false;

function tuningRows() {
  const tbody = document.getElementById("installTuningTableBody");
  return tbody ? Array.from(tbody.querySelectorAll("tr")) : [];
}

function setTuningRowState(row, state, detail = "") {
  row.dataset.idState = state;
  const labels = {
    safe: ["statusFree", "🟢 Free & Safe", "free"],
    registered: ["statusRegistered", "Keep ID", "registered"],
    excluded: ["statusExcluded", "Skipped", "excluded"],
    pending: ["statusChecking", "Checking ID...", "suggested"],
    duplicate: ["statusDuplicate", "Duplicate ID in this installation", "conflict"],
    invalid: ["statusInvalid", "❌ Invalid ID", "conflict"],
    occupied: ["statusConflict", "⚠️ Conflict: ID In Use", "conflict"],
    error: ["statusCheckFailed", "ID check failed — retry", "conflict"]
  };
  const [key, fallback, style] = labels[state];
  const badge = document.createElement(state === "error" ? "button" : "span");
  badge.className = `id-badge id-badge-${style}`;
  badge.textContent = window.t(`install.${key}`, fallback);
  badge.title = detail;
  if (state === "error") {
    badge.type = "button";
    badge.addEventListener("click", () => refreshTuningValidation(true));
  }
  const cell = row.querySelector(".tuning-status-cell");
  cell.innerHTML = "";
  cell.appendChild(badge);
  row.querySelector(".input-id-edit").classList.toggle("has-conflict",
    ["duplicate", "invalid", "occupied", "error"].includes(state));
}

function updateTuningSelectionSummary() {
  const rows = tuningRows();
  const active = rows.filter(row => row.querySelector(".chk-tuning-part").checked);
  const blocked = active.filter(row => !["safe", "registered"].includes(row.dataset.idState));
  const pending = blocked.some(row => row.dataset.idState === "pending");
  const conflicts = blocked.filter(row => row.dataset.idState !== "pending");
  const master = document.getElementById("chkAllTuningParts");
  if (master) {
    master.checked = rows.length > 0 && active.length === rows.length;
    master.indeterminate = active.length > 0 && active.length < rows.length;
  }
  const badge = document.getElementById("installTuningBadge");
  if (badge) badge.textContent = window.t("install.partsCountRatio", "{0} / {1} parts")
    .replace("{0}", active.length).replace("{1}", rows.length);
  const summary = document.getElementById("tuningTableSummaryText");
  if (summary) {
    if (conflicts.length) {
      summary.textContent = window.t("install.tuningBlocked", "{0} part(s) need a valid, conflict-free ID before installation")
        .replace("{0}", conflicts.length);
      summary.style.color = "var(--accent-red, #ef4444)";
    } else if (pending) {
      summary.textContent = window.t("install.tuningChecking", "Verifying selected tuning part IDs...");
      summary.style.color = "var(--accent-amber, #f59e0b)";
    } else if (!active.length) {
      summary.textContent = window.t("install.tuningAllExcluded", "All tuning parts excluded from installation");
      summary.style.color = "var(--text-muted)";
    } else {
      summary.textContent = window.t("install.tuningSelectedSafe", "All selected tuning parts verified conflict-free");
      summary.style.color = "var(--accent-emerald)";
    }
  }
  const alert = document.getElementById("installTuningConflictAlert");
  if (alert) {
    alert.style.display = "none";
    alert.textContent = window.t("install.tuningResolve", "Resolve the highlighted tuning IDs, auto-assign, or uncheck those parts to continue.");
  }
  const execute = document.getElementById("btnExecuteInstall");
  if (execute) execute.disabled = tuningInstallBusy || blocked.length > 0;
  return blocked.length === 0;
}

// Recompute local conflicts for the entire table immediately. Only the remote
// occupancy checks are debounced; a generation prevents stale replies winning.
function refreshTuningValidation(immediate = false) {
  clearTimeout(tuningValidationTimer);
  const generation = ++tuningValidationGeneration;
  const owners = new Map();
  const candidates = [];
  for (const row of tuningRows()) {
    const input = row.querySelector(".input-id-edit");
    const selected = row.querySelector(".chk-tuning-part").checked;
    row.classList.toggle("tuning-part-excluded", !selected);
    input.disabled = !selected || input.dataset.registered === "true";
    if (!selected) { setTuningRowState(row, "excluded"); continue; }
    const raw = input.value.trim();
    const id = Number(raw);
    if (!/^[0-9]+$/.test(raw) || !Number.isInteger(id) || id < 1000 || id > 65535) {
      setTuningRowState(row, "invalid", "Enter an integer between 1000 and 65535");
      continue;
    }
    if (!owners.has(id)) owners.set(id, []);
    owners.get(id).push(row);
    setTuningRowState(row, "pending");
    candidates.push({ row, id });
  }
  for (const [id, rows] of owners) {
    if (rows.length > 1) {
      const detail = `ID ${id}: ${rows.map(row => row.dataset.part).join(", ")}`;
      rows.forEach(row => setTuningRowState(row, "duplicate", detail));
    }
  }
  updateTuningSelectionSummary();
  const check = async () => {
    await Promise.all(candidates.filter(({ row }) => row.dataset.idState === "pending").map(async ({ row, id }) => {
      try {
        const res = await fetch(`/api/ids/check?id=${id}`);
        const data = await res.json();
        if (generation !== tuningValidationGeneration) return;
        if (!res.ok || !data.success || !data.result || typeof data.result.is_free !== "boolean") throw new Error("Invalid ID check response");
        const result = data.result;
        const self = String(result.name || "").toLowerCase() === String(row.dataset.part).toLowerCase();
        setTuningRowState(row, result.is_free || self ? "safe" : "occupied",
          result.is_free ? "" : `${result.name || ""} (${result.file || ""})`);
      } catch (err) {
        if (generation === tuningValidationGeneration) setTuningRowState(row, "error", err.message);
      } finally {
        if (generation === tuningValidationGeneration) updateTuningSelectionSummary();
      }
    }));
    return generation === tuningValidationGeneration && updateTuningSelectionSummary();
  };
  if (immediate) return check();
  tuningValidationTimer = setTimeout(check, 300);
}

function collectExcludedTuningParts() {
  return tuningRows().filter(row => !row.querySelector(".chk-tuning-part").checked)
    .map(row => row.dataset.part.toLowerCase());
}

function collectTuningIdAssignments() {
  const assignments = {};
  for (const row of tuningRows()) {
    const input = row.querySelector(".input-id-edit");
    if (row.querySelector(".chk-tuning-part").checked && input.dataset.registered !== "true") {
      // Preserve invalid text in saved wizard state; validation must reject it,
      // never truncate decimals or silently omit an invalid assignment.
      assignments[input.dataset.part] = input.value.trim();
    }
  }
  return assignments;
}

function renderTuningPartsTable(parts) {
  const tbody = document.getElementById("installTuningTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  parts.forEach(p => {
    const row = document.createElement("tr");
    row.dataset.part = p.part_name;
    const selection = document.createElement("td");
    selection.style.textAlign = "center";
    selection.style.padding = "6px 8px";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "chk-tuning-part";
    checkbox.dataset.part = p.part_name;
    checkbox.checked = true;
    checkbox.title = window.t("install.chkPartTooltip", "Include this tuning part in installation");
    selection.appendChild(checkbox);
    const name = document.createElement("td");
    name.className = "tuning-part-name-cell";
    name.style.fontFamily = "var(--font-mono)";
    name.style.fontWeight = "600";
    name.style.color = "var(--text-bright)";
    name.textContent = `🛠️ ${p.part_name}`;
    const category = document.createElement("td");
    const categoryBadge = document.createElement("span");
    categoryBadge.className = "badge";
    categoryBadge.style.cssText = "background:#1f293d; color:var(--accent-cyan); font-size:11px;";
    categoryBadge.textContent = p.name_en || (p.name_cn ? (p.name_cn.match(/\(([^)]+)\)/)?.[1] || p.name_cn) : (p.category || "Tuning"));
    category.appendChild(categoryBadge);
    const idCell = document.createElement("td");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1000";
    input.max = "65535";
    input.step = "1";
    input.className = "input-id-edit";
    input.dataset.part = p.part_name;
    input.dataset.registered = String(p.status === "registered");
    input.value = p.assigned_id || "";
    input.readOnly = p.status === "registered";
    idCell.appendChild(input);
    const status = document.createElement("td");
    status.className = "tuning-status-cell";
    row.append(selection, name, category, idCell, status);
    tbody.appendChild(row);
    checkbox.addEventListener("change", () => refreshTuningValidation());
    input.addEventListener("input", () => refreshTuningValidation());
  });
  const master = document.getElementById("chkAllTuningParts");
  if (master) master.onchange = () => {
    tuningRows().forEach(row => { row.querySelector(".chk-tuning-part").checked = master.checked; });
    refreshTuningValidation();
  };
  const auto = document.getElementById("btnAutoReassignIds");
  if (auto) {
    auto.tuningOperation = null;
    auto.disabled = false;
    auto.textContent = window.t("install.btnAutoResetIds", "Auto-assign");
    auto.onclick = async () => {
      const inputs = tuningRows().map(row => row.querySelector(".input-id-edit"))
        .filter(input => !input.disabled && input.dataset.registered !== "true");
      if (!inputs.length || tuningInstallBusy) return;
      const generation = tuningValidationGeneration;
      const operation = {};
      auto.tuningOperation = operation;
      auto.disabled = true;
      auto.textContent = window.t("install.autoAssigning", "⚡ Assigning IDs...");
      try {
        const res = await fetch("/api/ids/allocate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ count: inputs.length })
        });
        const data = await res.json();
        if (generation !== tuningValidationGeneration) return;
        if (!res.ok || !data.success || !Array.isArray(data.allocated) || data.allocated.length !== inputs.length) {
          throw new Error(data.error || "Unable to allocate IDs for all selected parts");
        }
        inputs.forEach((input, index) => { input.value = data.allocated[index]; });
        if (await refreshTuningValidation(true)) showToast(loc({ en: `Assigned safe IDs for ${inputs.length} parts!` }), "success");
      } catch (err) {
        if (generation === tuningValidationGeneration) showToast(loc({ en: "Failed to auto-assign IDs: " }) + err.message, "error");
      } finally {
        if (auto.tuningOperation === operation) {
          auto.disabled = false;
          auto.textContent = window.t("install.btnAutoResetIds", "Auto-assign");
        }
      }
    };
  }
  const pool = document.getElementById("btnOpenIdPoolFromInstall");
  if (pool) pool.onclick = () => openIdPoolModal();
  refreshTuningValidation();
}


// ---------------- ID Pool Inspector Modal ----------------

let currentGaps = [];
let currentGapFilter = "all";
let flaKillableLimit = null;

async function ensureKillableLimit() {
  if (flaKillableLimit != null) return flaKillableLimit;
  try {
    const res = await fetch("/api/ids/stats");
    const data = await res.json();
    const flaS = (data.success && data.fla_status) || {};
    if (flaS.has_fla && flaS.apply_id_limit_patch && flaS.count_of_killable_model_ids) {
      flaKillableLimit = flaS.count_of_killable_model_ids;
    }
  } catch (e) {}
  return flaKillableLimit;
}

function copyIdToClipboard(val) {
  const successMsg = window.t("idpool.idCopied", "Copied ID {0} to clipboard!").replace("{0}", val);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(String(val)).then(() => {
      showToast(successMsg, "success");
    }).catch(() => {
      fallbackCopy(val, successMsg);
    });
  } else {
    fallbackCopy(val, successMsg);
  }
}

function fallbackCopy(val, successMsg) {
  const ta = document.createElement("textarea");
  ta.value = String(val);
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
    showToast(successMsg, "success");
  } catch (e) {
    showToast("Failed to copy", "error");
  }
  document.body.removeChild(ta);
}

let diagnosticsDirPath = "";

const DIAGNOSTIC_OPERATION_KEYS = {
  install: "diag.operationInstall",
  apply_merge: "diag.operationMerge",
};

function setupDiagnostics() {
  const modal = document.getElementById("diagnosticsModal");
  const btnHeader = document.getElementById("btnOpenDiagnostics");
  const closeBtn = document.getElementById("closeDiagnosticsModal");
  const closeBtnFooter = document.getElementById("closeDiagnosticsModalBtn");
  const exportBtn = document.getElementById("btnExportDiagnostics");
  const folderBtn = document.getElementById("btnOpenDiagnosticsFolder");
  const refreshBtn = document.getElementById("btnRefreshDiagnostics");

  const hideModal = () => {
    if (modal) modal.classList.remove("active");
  };
  if (closeBtn) closeBtn.addEventListener("click", hideModal);
  if (closeBtnFooter) closeBtnFooter.addEventListener("click", hideModal);
  if (btnHeader) btnHeader.addEventListener("click", openDiagnosticsModal);
  if (refreshBtn) refreshBtn.addEventListener("click", loadDiagnostics);
  if (exportBtn) exportBtn.addEventListener("click", createDiagnosticsPackage);
  if (folderBtn) folderBtn.addEventListener("click", openDiagnosticsFolder);
}

async function openDiagnosticsModal() {
  const modal = document.getElementById("diagnosticsModal");
  if (!modal) return;
  modal.classList.add("active");
  await loadDiagnostics();
}

async function loadDiagnostics() {
  const list = document.getElementById("diagnosticsList");
  if (!list) return;
  try {
    const res = await fetch("/api/diagnostics?limit=50");
    const data = await res.json();
    if (!data.success) {
      showToast(window.t("diag.loadFailed", "Could not read the operation log"), "error");
      return;
    }
    diagnosticsDirPath = data.dir || "";
    renderDiagnostics(data.operations || []);
  } catch (err) {
    console.error("Failed to load the operation log:", err);
    showToast(window.t("common.requestFailed", "Request failed: ") + err, "error");
  }
}

function diagnosticsTargetLabel(entry) {
  const context = entry.context || {};
  const pairs = (context.vehicles || [])
    .filter(v => v && (v.source_model || v.target_model))
    .map(v => `${v.source_model || "?"} → ${v.target_model || "?"}`);
  if (pairs.length) return pairs.join(", ");
  if (context.target_model) return context.target_model;
  if (Array.isArray(context.target_models) && context.target_models.length) return context.target_models.join(", ");
  return context.folder_name || context.mod_dir || window.t("diag.noTarget", "(no target recorded)");
}

function renderDiagnostics(operations) {
  const list = document.getElementById("diagnosticsList");
  const detail = document.getElementById("diagnosticsDetail");
  if (!list) return;
  list.replaceChildren();
  if (detail) {
    detail.hidden = true;
    detail.textContent = "";
  }
  if (!operations.length) {
    const empty = document.createElement("p");
    empty.className = "field-hint";
    empty.textContent = window.t("diag.empty", "No operations recorded yet.");
    list.appendChild(empty);
    return;
  }
  operations.forEach((entry) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "diagnostics-row" + (entry.success ? "" : " failed");
    row.addEventListener("click", () => {
      if (!detail) return;
      detail.hidden = false;
      detail.textContent = JSON.stringify(entry, null, 2);
    });

    const head = document.createElement("div");
    head.className = "diagnostics-row-head";

    const status = document.createElement("span");
    status.className = "badge " + (entry.success ? "badge-success" : "badge-warning");
    status.textContent = entry.success
      ? window.t("diag.statusOk", "OK")
      : window.t("diag.statusFailed", "Failed");

    const kind = document.createElement("span");
    kind.className = "diagnostics-kind";
    kind.textContent = window.t(DIAGNOSTIC_OPERATION_KEYS[entry.operation] || "diag.operationOther", entry.operation || "");

    const target = document.createElement("span");
    target.className = "diagnostics-target";
    target.textContent = diagnosticsTargetLabel(entry);

    const time = document.createElement("span");
    time.className = "diagnostics-time";
    time.textContent = entry.timestamp || "";

    head.append(status, kind, target, time);
    row.appendChild(head);

    const message = entry.error || (entry.errors && entry.errors.length ? entry.errors[0] : "");
    if (message) {
      const text = document.createElement("span");
      text.className = "diagnostics-message";
      text.textContent = message;
      row.appendChild(text);
    }
    list.appendChild(row);
  });
}

async function createDiagnosticsPackage() {
  const notice = document.getElementById("diagnosticsNotice");
  const exportBtn = document.getElementById("btnExportDiagnostics");
  if (exportBtn) exportBtn.disabled = true;
  if (notice) {
    notice.hidden = false;
    notice.textContent = window.t("diag.exporting", "Writing the diagnostics package…");
  }
  try {
    const res = await fetch("/api/diagnostics/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json();
    if (data.success) {
      if (notice) notice.textContent = window.t("diag.exported", "Package ready: {0}").replace("{0}", data.path);
      showToast(window.t("diag.exportedToast", "Diagnostics package created"), "success");
      await loadDiagnostics();
    } else {
      const message = data.error || window.t("common.unknownError", "Unknown error");
      if (notice) notice.textContent = message;
      showToast(message, "error");
    }
  } catch (err) {
    console.error("Failed to write the diagnostics package:", err);
    showToast(window.t("common.requestFailed", "Request failed: ") + err, "error");
  } finally {
    if (exportBtn) exportBtn.disabled = false;
  }
}

async function openDiagnosticsFolder() {
  if (!diagnosticsDirPath) return;
  try {
    const res = await fetch("/api/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: diagnosticsDirPath }),
    });
    const data = await res.json();
    if (!data.success) {
      showToast(data.error || window.t("common.requestFailed", "Request failed: "), "error");
    }
  } catch (err) {
    console.error("Failed to open the diagnostics folder:", err);
  }
}

let foreignConfigsNotified = false;

function setupForeignConfigs() {
  const modal = document.getElementById("foreignConfigsModal");
  const closeBtn = document.getElementById("closeForeignConfigsModal");
  const gotItBtn = document.getElementById("btnForeignConfigsGotIt");
  const hideModal = () => {
    if (modal) modal.classList.remove("active");
  };
  if (closeBtn) closeBtn.addEventListener("click", hideModal);
  if (gotItBtn) gotItBtn.addEventListener("click", acknowledgeForeignConfigs);
}

// Competing copies of handling.cfg / carcols.dat / carmods.dat / vehicles.ide /
// shopping.dat / veh_mods.ide are renamed by the backend so ModLoader stops
// loading them; the user is told once per session and can still merge by hand.
async function runForeignConfigGuard() {
  try {
    const res = await fetch("/api/foreign-configs/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json();
    if (!data.success) {
      showToast(window.t("foreign.loadFailed", "Could not check for competing config copies"), "error");
      return;
    }
    renderForeignConfigs(data);
    // The backend decides whether this run is worth a notice: a rename that
    // just happened always is, copies disabled by an earlier run only once per
    // game folder (and never after "don't show this again").
    if (data.notify && !foreignConfigsNotified) {
      foreignConfigsNotified = true;
      openForeignConfigsModal(data);
    }
  } catch (err) {
    console.error("Failed to check for competing config copies:", err);
  }
}

function foreignFolderOf(filePath) {
  const parts = String(filePath || "").split(/[\\/]/);
  parts.pop();
  return parts.join("\\");
}

async function openContainingFolder(filePath) {
  const folder = foreignFolderOf(filePath);
  if (!folder) return;
  try {
    const res = await fetch("/api/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: folder }),
    });
    const data = await res.json();
    if (!data.success) {
      showToast(data.error || window.t("foreign.openFailed", "Could not open that folder"), "error");
    }
  } catch (err) {
    console.error("Failed to open the containing folder:", err);
  }
}

function foreignConfigRow(entry, justDisabled) {
  const filePath = entry.disabled_path || entry.path || "";
  const row = document.createElement("div");
  row.className = "foreign-row" + (justDisabled ? " foreign-row-new" : "");

  const head = document.createElement("div");
  head.className = "foreign-row-head";

  const title = document.createElement("span");
  title.className = "foreign-row-title";
  title.textContent = entry.name;

  const state = document.createElement("span");
  state.className = "badge" + (justDisabled ? " badge-warning" : "");
  state.textContent = justDisabled
    ? window.t("foreign.stateDisabledNow", "just disabled")
    : window.t("foreign.stateDisabled", "disabled earlier");

  const openBtn = document.createElement("button");
  openBtn.type = "button";
  openBtn.className = "btn btn-secondary btn-sm foreign-open";
  openBtn.textContent = window.t("foreign.btnOpenFolder", "📂 Open folder");
  openBtn.addEventListener("click", () => openContainingFolder(filePath));

  head.append(title, state, openBtn);

  const pathText = document.createElement("span");
  pathText.className = "foreign-path";
  pathText.textContent = filePath;

  row.append(head, pathText);
  return row;
}

function renderForeignConfigs(data) {
  const freshlyDisabled = data.disabled || [];
  const earlier = data.already_disabled || [];
  const list = document.getElementById("foreignConfigsList");
  if (list) {
    list.replaceChildren();
    if (!freshlyDisabled.length && !earlier.length) {
      const empty = document.createElement("p");
      empty.className = "field-hint";
      empty.textContent = window.t("foreign.none", "No competing copies found.");
      list.appendChild(empty);
    } else {
      freshlyDisabled.forEach(entry => list.appendChild(foreignConfigRow(entry, true)));
      earlier.forEach(entry => list.appendChild(foreignConfigRow(entry, false)));
    }
  }
  const badge = document.getElementById("foreignConfigsBadge");
  if (badge) {
    const total = freshlyDisabled.length + earlier.length;
    badge.className = "badge " + (total ? "badge-warning" : "badge-success");
    badge.textContent = total
      ? window.t("foreign.badgeCount", "{0} disabled").replace("{0}", total)
      : window.t("foreign.badgeNone", "None");
  }
}

function openForeignConfigsModal(data) {
  const freshlyDisabled = (data && data.disabled) || [];
  const earlier = (data && data.already_disabled) || [];
  const list = document.getElementById("foreignConfigsModalList");
  if (list) {
    list.replaceChildren();
    freshlyDisabled.forEach(entry => list.appendChild(foreignConfigRow(entry, true)));
    earlier.forEach(entry => list.appendChild(foreignConfigRow(entry, false)));
  }
  const remember = document.getElementById("chkForeignConfigsDontRemind");
  if (remember) remember.checked = false;
  const modal = document.getElementById("foreignConfigsModal");
  if (modal) modal.classList.add("active");
}

async function acknowledgeForeignConfigs() {
  const remember = document.getElementById("chkForeignConfigsDontRemind");
  const modal = document.getElementById("foreignConfigsModal");
  if (modal) modal.classList.remove("active");
  foreignConfigsNotified = true;
  try {
    await fetch("/api/foreign-configs/ack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ never: !!(remember && remember.checked) }),
    });
  } catch (err) {
    console.error("Failed to store the config-guard acknowledgement:", err);
  }
}

function setupIdPool() {
  const modal = document.getElementById("idPoolModal");
  const closeBtn = document.getElementById("closeIdPoolModal");
  const closeBtnFooter = document.getElementById("closeIdPoolModalBtn");
  const btnHeader = document.getElementById("btnOpenIdPoolHeader");

  const hideModal = () => {
    if (modal) modal.classList.remove("active");
  };
  if (closeBtn) closeBtn.addEventListener("click", hideModal);
  if (closeBtnFooter) closeBtnFooter.addEventListener("click", hideModal);

  if (btnHeader) btnHeader.addEventListener("click", openIdPoolModal);

  // Probe button & Enter key
  const probeBtn = document.getElementById("btnProbeId");
  const probeInput = document.getElementById("inputIdProbe");
  if (probeBtn && probeInput) {
    probeBtn.addEventListener("click", () => doProbeId(probeInput.value));
    probeInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") doProbeId(probeInput.value);
    });
  }

  // Gap category filter buttons
  document.querySelectorAll(".gap-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".gap-filter-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentGapFilter = btn.getAttribute("data-gap-filter") || "all";
      renderFreeGaps(currentGaps);
    });
  });

  // Search & Filter
  const searchInput = document.getElementById("inputIdSearch");
  const filterSelect = document.getElementById("selectIdFilterType");
  let searchTimer = null;
  const triggerSearch = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      doSearchIds(searchInput ? searchInput.value : "", filterSelect ? filterSelect.value : "all");
    }, 250);
  };
  if (searchInput) searchInput.addEventListener("input", triggerSearch);
  if (filterSelect) filterSelect.addEventListener("change", triggerSearch);
}

async function loadIdStats() {
  try {
    const res = await fetch("/api/ids/stats");
    const data = await res.json();
    if (data.success) {
      const occEl = document.getElementById("idKpiOccupied");
      if (occEl) occEl.textContent = data.total_occupied.toLocaleString();

      const bdEl = document.getElementById("idKpiBreakdown");
      if (bdEl) {
        bdEl.textContent = window.t("idpool.kpiBreakdown", "Vanilla: {0} | Addons: {1}")
          .replace("{0}", data.vanilla_total.toLocaleString())
          .replace("{1}", data.mod_addon_count.toLocaleString()) + (loc({ en: ` | Override: ${data.mod_override_count.toLocaleString()}` }));
      }

      const freeEl = document.getElementById("idKpiFree");
      if (freeEl) freeEl.textContent = `${data.total_free_in_range.toLocaleString()} ${loc({ en: 'free' })}`;

      const freeSubEl = document.getElementById("idKpiFreeSub");
      if (freeSubEl) {
        if (data.killable_limit != null && data.total_free_safe != null) {
          freeSubEl.textContent = window.t("idpool.kpiFreeSafeSub", "Safe (<{0}): {1} · Total: {2}")
            .replace("{0}", data.killable_limit)
            .replace("{1}", Number(data.total_free_safe).toLocaleString())
            .replace("{2}", Number(data.total_free_in_range).toLocaleString());
        } else {
          freeSubEl.textContent = window.t("idpool.kpiFreeSub", "Completely free of vanilla or mod conflicts");
        }
      }

      // Conflict card
      const confCard = document.getElementById("idKpiConflictCard");
      const confEl = document.getElementById("idKpiConflict");
      const confSubEl = document.getElementById("idKpiConflictSub");
      if (confEl && confCard) {
        if (data.conflict_count === 0) {
          confEl.textContent = window.t("idpool.conflictNone", "🟢 0 Conflicts (Clean)");
          if (confSubEl) confSubEl.textContent = window.t("idpool.conflictNoneSub", "All mod IDs operate without collision");
          confCard.className = "id-kpi-card highlight-green";
        } else {
          confEl.textContent = window.t("idpool.conflictFound", "⚠️ {0} Conflicts Detected!").replace("{0}", data.conflict_count);
          if (confSubEl) confSubEl.textContent = window.t("idpool.conflictFoundSub", "Click to view conflicting mod details");
          confCard.className = "id-kpi-card has-conflict";
          confCard.style.cursor = "pointer";
          confCard.onclick = () => {
            const searchInput = document.getElementById("inputIdSearch");
            if (searchInput && data.conflicts && data.conflicts.length > 0) {
              searchInput.value = data.conflicts[0].id;
              doSearchIds(String(data.conflicts[0].id), "all");
              searchInput.scrollIntoView({ behavior: "smooth", block: "center" });
            }
          };
        }
      }

      // FLA patch card (killable model ID ceiling for custom vehicle IDs).
      // Only cache the ceiling when the patch is actually active; otherwise
      // the default 800 must not trigger warnings.
      const flaS = data.fla_status || {};
      if (flaS.has_fla && flaS.apply_id_limit_patch && flaS.count_of_killable_model_ids) {
        flaKillableLimit = flaS.count_of_killable_model_ids;
      }
      const flaEl = document.getElementById("idKpiFla");
      const flaSubEl = document.getElementById("idKpiFlaSub");
      const flaCard = document.getElementById("idKpiFlaCard");
      if (flaEl && flaCard) {
        if (flaS.has_fla && flaS.apply_id_limit_patch) {
          flaEl.textContent = window.t("idpool.flaEnabled", "🟢 ID limit patch active");
          flaCard.className = "id-kpi-card highlight-green";
          if (flaSubEl) {
            flaSubEl.textContent = (flaKillableLimit != null)
              ? window.t("idpool.flaKillableSub", "Killable models limit: {0}").replace("{0}", flaKillableLimit)
              : window.t("idpool.flaVanillaSub", "Using vanilla limit");
          }
        } else {
          flaEl.textContent = window.t("idpool.flaDisabled", "⚪ FLA not detected");
          flaCard.className = "id-kpi-card";
          if (flaSubEl) flaSubEl.textContent = window.t("idpool.flaVanillaSub", "Using vanilla limit");
        }
      }

      currentGaps = data.gaps || [];
      renderFreeGaps(currentGaps);
    }
  } catch (err) {
    console.error("Failed to load ID pool stats:", err);
  }
}

async function openIdPoolModal() {
  const modal = document.getElementById("idPoolModal");
  if (!modal) return;
  modal.classList.add("active");
  await loadIdStats();
  doSearchIds("", "all");
}

function renderFreeGaps(gaps) {
  const container = document.getElementById("freeGapsContainer");
  if (!container) return;
  container.innerHTML = "";

  currentGaps = gaps || [];
  let filtered = currentGaps;

  if (currentGapFilter === "tuning") {
    filtered = currentGaps.filter(g => g.category === "tuning");
  } else if (currentGapFilter === "addon") {
    filtered = currentGaps.filter(g => g.category === "addon");
  } else if (currentGapFilter === "large") {
    filtered = currentGaps.filter(g => g.is_large || g.count >= 100);
  }

  if (filtered.length === 0) {
    container.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:16px; color:var(--text-muted); font-size:12px;">${loc({ en: "No prominent free blocks in this category" })}</div>`;
    return;
  }

  filtered.forEach(g => {
    const chip = document.createElement("div");
    chip.className = `free-gap-chip ${g.recommended ? 'recommended' : ''} cat-${g.category || 'general'}`;
    chip.title = window.t("idpool.gapCardTooltip", "Click to probe starting ID {0}").replace("{0}", g.start);

    const zoneLabel = (window.I18N ? window.I18N.pick(g, "zone_label") : "") || g.zone_label || "";
    const zoneShort = String(zoneLabel || "").split(" (")[0].split("（")[0].trim() || zoneLabel;
    const catKey = `idpool.gapCat_${g.category || 'general'}`;
    const catTag = window.t(catKey, loc({ en: { tuning: "🔧 Tuning", addon: "🚗 Addon", reserve: "📦 Reserve", fla: "⚡ FLA", general: "Free" }[g.category] || "Free" }));
    chip.innerHTML = `
      <div class="gap-range-title">
        <span>${g.recommended ? '⭐ ' : ''}${g.start} – ${g.end}</span>
        <span class="gap-count-pill">${window.t("idpool.freeCountBadge", "{0} free").replace("{0}", g.count)}</span>
      </div>
      <div class="gap-meta-row">
        <span class="gap-cat-tag">${catTag}</span>
        ${g.over_killable_limit ? `<span class="gap-cat-tag gap-over-cap" title="${window.t("idpool.gapOverKillableTitle", "This free block exceeds the FLA killable model-ID ceiling; destroyed vehicles may misbehave")}">${window.t("idpool.gapOverKillable", "⚠️ Over killable cap")}</span>` : ""}
        <span class="gap-label-text" title="${zoneLabel}">${zoneShort}</span>
      </div>
      <div class="gap-start-hint">${window.t("idpool.gapStartHint", "Start {0} · click to probe →").replace("{0}", g.start)}</div>
    `;

    chip.addEventListener("click", () => {
      document.querySelectorAll(".free-gap-chip").forEach(c => c.classList.remove("active-probing"));
      chip.classList.add("active-probing");

      const probeInput = document.getElementById("inputIdProbe");
      if (probeInput) {
        probeInput.value = g.start;
        probeInput.scrollIntoView({ behavior: "smooth", block: "center" });
        probeInput.style.borderColor = "var(--accent-cyan)";
        probeInput.style.boxShadow = "0 0 10px rgba(56, 189, 248, 0.4)";
        setTimeout(() => {
          probeInput.style.borderColor = "";
          probeInput.style.boxShadow = "";
        }, 1200);
        doProbeId(g.start);
      }
    });

    container.appendChild(chip);
  });
}

async function doProbeId(idVal) {
  const val = parseInt(idVal, 10);
  const resultDiv = document.getElementById("idProbeResult");
  if (!resultDiv) return;

  if (isNaN(val) || val < 0) {
    resultDiv.style.display = "block";
    resultDiv.className = "probe-result-box occupied";
    resultDiv.innerHTML = window.t("idpool.probeInvalid", "⚠️ Please enter a valid non-negative integer ID!");
    return;
  }

  resultDiv.style.display = "block";
  resultDiv.className = "probe-result-box";
  resultDiv.innerHTML = window.t("idpool.probing", "Probing ID status...");

  try {
    const res = await fetch(`/api/ids/check?id=${val}`);
    const d = await res.json();
    if (d.success && d.result) {
      const r = d.result;
      if (r.is_free) {
        resultDiv.className = "probe-result-box free";
        let gapInfo = "";
        if (r.gap) {
          gapInfo = loc({ en: ` (Inside free block <strong>${r.gap.start} - ${r.gap.end}</strong> with ${r.gap.count} contiguous free IDs)` });
        }
        let recBadge = r.is_recommended
          ? `<span style="background:rgba(251,191,36,0.2); color:var(--accent-amber); padding:2px 6px; border-radius:4px; margin-left:6px; font-weight:600;">${loc({ en: "⭐ Recommended Free Block" })}</span>`
          : "";
        const freeTitle = loc({ en: `🟢 ID ${val} is FREE and available!` });
        const freeDesc = loc({ en: `Not occupied in vanilla data or any ModLoader mod. Safe for tuning parts or new vehicles.${gapInfo}` });

        resultDiv.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div style="font-size:14px; font-weight:700;">${freeTitle}${recBadge}</div>
            <button class="btn-copy-id" onclick="copyIdToClipboard(${val})">📋 ${loc({ en: 'Copy ID' })}</button>
          </div>
          <div style="margin-top:6px; color:var(--text-main); font-size:12px;">${freeDesc}</div>
        `;
      } else {
        resultDiv.className = "probe-result-box occupied";
        let tagBadge = r.status_tag === "addon"
          ? `<span style="background:rgba(56,189,248,0.2); color:var(--accent-cyan); padding:2px 6px; border-radius:4px; margin-left:6px;">${loc({ en: "Mod Addon" })}</span>`
          : r.status_tag === "override"
          ? `<span style="background:rgba(251,191,36,0.2); color:var(--accent-amber); padding:2px 6px; border-radius:4px; margin-left:6px;">${loc({ en: "Mod Override" })}</span>`
          : `<span style="background:rgba(156,163,175,0.2); color:#9ca3af; padding:2px 6px; border-radius:4px; margin-left:6px;">${loc({ en: "Vanilla" })}</span>`;

        const typeLabel = r.is_vehicle
          ? (loc({ en: 'Vehicle' }))
          : (r.is_tuning ? (loc({ en: 'Tuning Part' })) : (loc({ en: 'Object / Map Asset' })));

        const nameLabel = loc({ en: "Model:" });
        const secLabel = loc({ en: "Section:" });
        const typLabel = loc({ en: "Type:" });
        const fileLabel = loc({ en: "File:" });
        const occTitle = loc({ en: `🔴 ID ${val} is OCCUPIED!` });

        resultDiv.innerHTML = `
          <div style="font-size:14px; font-weight:700;">${occTitle}${tagBadge}</div>
          <div style="margin-top:6px; font-size:12px; line-height:1.6;">
            <div><strong>${nameLabel}</strong> <code style="color:var(--text-bright);">${r.name || (loc({ en: 'Unknown' }))}</code> &nbsp;|&nbsp; <strong>${secLabel}</strong> <code>${r.section}</code> &nbsp;|&nbsp; <strong>${typLabel}</strong> ${typeLabel}</div>
            <div><strong>${fileLabel}</strong> <code style="color:var(--accent-cyan);">${r.file}</code></div>
          </div>
        `;
      }
    }
  } catch (err) {
    resultDiv.className = "probe-result-box occupied";
    resultDiv.innerHTML = (loc({ en: "Probe request failed: " })) + err.message;
  }
}

async function doSearchIds(query, filterType) {
  const tbody = document.getElementById("idSearchResultsBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:16px; color:var(--text-muted);">${loc({ en: "Searching model IDs..." })}</td></tr>`;

  try {
    const res = await fetch(`/api/ids/search?query=${encodeURIComponent(query)}&filter_type=${encodeURIComponent(filterType)}&limit=60`);
    const d = await res.json();
    if (d.success && d.results) {
      if (d.results.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:16px; color:var(--text-muted);">${loc({ en: "No matching occupied ID records found" })}</td></tr>`;
        return;
      }

      let html = "";
      d.results.forEach(item => {
        let tagHtml = "";
        const tag = item.status_tag || item.source;
        if (tag === "addon") {
          tagHtml = `<span class="badge" style="background:rgba(56,189,248,0.15); color:var(--accent-cyan);">${loc({ en: "Mod Addon" })}</span>`;
        } else if (tag === "override") {
          tagHtml = `<span class="badge" style="background:rgba(251,191,36,0.15); color:var(--accent-amber);">${loc({ en: "Mod Replaced" })}</span>`;
        } else {
          tagHtml = `<span class="badge" style="background:rgba(156,163,175,0.15); color:#9ca3af;">${loc({ en: "Vanilla" })}</span>`;
        }

        if (item.is_vehicle) {
          const vtypeKey = "veh." + (item.veh_type || "car");
          const vlabel = (window.I18N ? window.I18N.pick(item, "veh_type_label") : "") || window.t(vtypeKey, "🚗 Vehicle");
          tagHtml += ` <span class="badge" style="background:rgba(168,85,247,0.15); color:#c084fc;">${vlabel}</span>`;
        } else if (item.is_tuning) {
          tagHtml += ` <span class="badge" style="background:rgba(52,211,153,0.15); color:var(--accent-emerald);">${loc({ en: "🔧 Tuning" })}</span>`;
        }

        const displayNameHtml = (item.display_name && item.display_name.toLowerCase() !== item.name.toLowerCase())
          ? `<span style="color:var(--text-muted); font-size:11px; margin-left:6px; font-weight:normal;">(${item.display_name})</span>`
          : '';

        html += `
          <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
            <td style="padding:6px 10px; font-family:var(--font-mono); font-weight:700; color:var(--accent-cyan);">${item.id}</td>
            <td style="padding:6px 10px; font-family:var(--font-mono); font-weight:600; color:var(--text-bright);">${item.name}${displayNameHtml}</td>
            <td style="padding:6px 10px; color:var(--text-muted); font-size:11px;"><code>${item.section}</code></td>
            <td style="padding:6px 10px;">${tagHtml}</td>
            <td style="padding:6px 10px; color:var(--text-muted); font-size:11px; font-family:var(--font-mono);">${item.file}</td>
          </tr>
        `;
      });
      tbody.innerHTML = html;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:16px; color:#f85149;">${loc({ en: "Search failed" })}: ${err.message}</td></tr>`;
  }
}
