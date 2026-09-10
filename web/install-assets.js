/* Read-only file browser for a single installer inspection. */
(() => {
  const categories = ["models", "textures", "tuning", "documents", "other", "configs"];
  const labelKeys = { models: "install.assetModels", textures: "install.assetTextures",
    tuning: "install.assetTuning", documents: "install.assetReadme", other: "assets.other", configs: "assets.configs" };
  const configNames = { vehicles_ide: "vehicles.ide", handling_cfg: "handling.cfg", carcols_dat: "carcols.dat",
    carmods_dat: "carmods.dat", veh_mods_ide: "veh_mods.ide", vehicle_audio: "gtasa_vehicleAudioSettings.cfg",
    special_features: "model_special_features.dat", fxt_text: "FXT" };
  let data = null, vehicles = [], category = "models", selected = null;
  let dialog, list, textPane, search, opener, request = null, sequence = 0;
  let groups = {}, visible = [], preview = null;
  let excludedFiles = new Set();
  let onApplyCallback = null;

  let editedConfigKeys = new Set();

  const t = key => window.t(key, key);
  const sizeLabel = size => size < 1024 ? `${size} B` : size < 1048576
    ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`;
  const pathLabel = file => String(file.rel || file.name).replace(/\\/g, "/");
  const fileKey = file => pathLabel(file);
  const isExcluded = file => excludedFiles.has(fileKey(file));

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function cancelRequest() {
    sequence++;
    if (request) request.abort();
    request = null;
  }

  function reset() {
    cancelRequest();
    if (dialog && dialog.open) dialog.close();
    data = null;
    groups = {};
    selected = null;
    preview = null;
    excludedFiles.clear();
    editedConfigKeys.clear();
    updateFooter();
  }

  // Rendered on demand rather than cached, so a language switch re-labels the
  // list without rebuilding the parsed data.
  function lineCountLabel(count) {
    if (!count) return t("assets.emptyConfig");
    const key = count === 1 ? "assets.linesCountOne" : "assets.linesCountMany";
    return t(key, "{0} lines").replace("{0}", count);
  }

  function configLabel(file) {
    return typeof file.lineCount === "number" ? lineCountLabel(file.lineCount) : pathLabel(file);
  }

  function buildConfigsGroup(parsed) {
    parsed = parsed || {};
    return Object.entries(configNames).map(([key, name]) => {
      const lines = parsed[key] || [];
      return {
        key,
        name,
        rel: name,
        lineCount: lines.length,
        content: lines.join("\n")
      };
    });
  }

  function setData(next, vehicleList) {
    reset();
    data = next;
    vehicles = vehicleList || [];
    groups = { ...(next.asset_files || {}) };
    groups.configs = buildConfigsGroup(next.parsed_config);
    updateFooter();
  }

  function updateParsedConfig(newParsedConfig) {
    if (!data) return;
    data.parsed_config = newParsedConfig || {};
    groups.configs = buildConfigsGroup(data.parsed_config);
    if (category === "configs") {
      renderFiles();
    }
  }

  function renderTabs() {
    const tabs = document.getElementById("assetCategoryTabs");
    tabs.replaceChildren();
    for (const key of categories) {
      let count = (groups[key] || []).length;
      if (key === "configs") {
        count = (groups.configs || []).filter(c => (c.content || "").trim().length > 0).length;
      }
      if (!count && key === "other") continue;
      const button = el("button", "asset-category-tab", `${t(labelKeys[key])} (${count})`);
      button.type = "button";
      button.disabled = (key !== "configs" && !count);
      button.dataset.category = key;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(category === key));
      button.setAttribute("aria-controls", "assetFilePanel");
      button.tabIndex = category === key ? 0 : -1;
      button.addEventListener("click", () => selectCategory(key));
      button.addEventListener("keydown", event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const buttons = [...tabs.querySelectorAll("button:not(:disabled)")];
        let index = buttons.indexOf(button);
        index = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        selectCategory(buttons[index].dataset.category);
        tabs.querySelector('[aria-selected="true"]').focus();
      });
      tabs.appendChild(button);
    }
  }

  function selectCategory(key) {
    cancelRequest();
    category = key;
    selected = null;
    preview = null;
    search.value = "";
    renderTabs();
    renderFiles();
  }

  function open(key, button) {
    if (!data) return;
    if (key !== "configs" && !(groups[key] || []).length) return;
    opener = button;
    document.getElementById("assetPackageName").textContent = data.original_name || "";
    selectCategory(key);
    dialog.showModal();
    search.focus();
    updateFooter();
  }

  function toggleExclusion(file, shouldInclude) {
    const k = fileKey(file);
    if (shouldInclude) {
      excludedFiles.delete(k);
    } else {
      excludedFiles.add(k);
    }
    updateFooter();
  }

  function updateFooter() {
    const countEl = document.getElementById("assetExcludedSummary");
    if (countEl) {
      if (excludedFiles.size > 0) {
        countEl.textContent = t("assets.excludedSummary").replace("{0}", excludedFiles.size);
      } else {
        countEl.textContent = "";
      }
    }
  }

  function selectAllVisible() {
    if (category === "configs") return;
    for (const file of visible) {
      excludedFiles.delete(fileKey(file));
    }
    renderFiles();
    updateFooter();
  }

  function deselectAllVisible() {
    if (category === "configs") return;
    for (const file of visible) {
      excludedFiles.add(fileKey(file));
    }
    renderFiles();
    updateFooter();
  }

  function updateTableCheckAllState() {
    const tableChk = document.getElementById("assetTableCheckAll");
    if (!tableChk || !visible.length) return;
    const allChecked = visible.every(f => !isExcluded(f));
    const noneChecked = visible.every(f => isExcluded(f));
    tableChk.checked = allChecked;
    tableChk.indeterminate = !allChecked && !noneChecked;
  }

  function renderFiles() {
    const query = search.value.trim().toLowerCase();
    visible = (groups[category] || []).filter(file => pathLabel(file).toLowerCase().includes(query));
    const isText = category === "documents" || category === "configs";
    document.getElementById("assetFilePanel").classList.toggle("asset-text-layout", isText);
    textPane.hidden = !isText;
    list.replaceChildren();
    list.classList.toggle("asset-document-list", isText);
    document.getElementById("assetVisibleCount").textContent = `${visible.length} / ${(groups[category] || []).length}`;

    const actionsGroup = document.getElementById("assetActionsGroup");
    if (actionsGroup) {
      actionsGroup.style.display = (category === "configs") ? "none" : "flex";
    }

    if (!visible.length) {
      list.appendChild(el("p", "asset-empty", t("assets.empty")));
      cancelRequest();
      selected = null;
      showPreview(null);
      return;
    }

    if (isText) {
      for (const file of visible) {
        if (category === "configs") {
          const button = el("button", "asset-document-button");
          button.type = "button";
          const isMod = editedConfigKeys.has(file.key);
          button.append(el("strong", "", file.name), el("span", "asset-relative-path", configLabel(file) + (isMod ? " *" : "")));
          button.title = pathLabel(file);
          button.addEventListener("click", () => selectText(file));
          list.appendChild(button);
        } else {
          // Documents category: with checkbox
          const item = el("div", "asset-document-item");
          const excluded = isExcluded(file);
          if (excluded) item.classList.add("is-excluded");
          item.dataset.rel = fileKey(file);

          const chk = document.createElement("input");
          chk.type = "checkbox";
          chk.className = "asset-item-checkbox";
          chk.checked = !excluded;
          chk.title = excluded ? t("assets.excluded") : "";
          chk.addEventListener("click", e => e.stopPropagation());
          chk.addEventListener("change", () => {
            toggleExclusion(file, chk.checked);
            item.classList.toggle("is-excluded", !chk.checked);
          });

          const button = el("button", "asset-document-button");
          button.type = "button";
          const titleRow = el("div", "asset-document-title-row");
          const strong = el("strong", "", file.name);
          const tag = el("span", "asset-excluded-tag", t("assets.excluded"));
          titleRow.append(strong, tag);
          button.append(titleRow, el("span", "asset-relative-path", pathLabel(file)));
          button.title = pathLabel(file);
          button.addEventListener("click", () => selectText(file));

          item.append(chk, button);
          list.appendChild(item);
        }
      }
      selectText(visible.includes(selected) ? selected : visible[0]);
      return;
    }

    const table = el("table", "asset-file-table");
    const head = el("thead");
    const header = el("tr");

    // Checkbox column in header
    const checkTh = el("th", "asset-check-col");
    const tableChk = document.createElement("input");
    tableChk.type = "checkbox";
    tableChk.className = "asset-item-checkbox";
    tableChk.id = "assetTableCheckAll";
    const allChecked = visible.length > 0 && visible.every(f => !isExcluded(f));
    const noneChecked = visible.length > 0 && visible.every(f => isExcluded(f));
    tableChk.checked = allChecked;
    tableChk.indeterminate = !allChecked && !noneChecked;
    tableChk.title = t("assets.selectAll");
    tableChk.addEventListener("change", () => {
      if (tableChk.checked) {
        selectAllVisible();
      } else {
        deselectAllVisible();
      }
    });
    checkTh.appendChild(tableChk);
    header.appendChild(checkTh);

    for (const key of ["assets.file", "assets.location", "assets.model", "assets.size"]) {
      const th = el("th", "", t(key));
      th.scope = "col";
      header.appendChild(th);
    }
    head.appendChild(header);
    table.appendChild(head);

    const body = el("tbody");
    for (const file of visible) {
      const row = el("tr");
      const excluded = isExcluded(file);
      if (excluded) row.classList.add("is-excluded");

      const checkTd = el("td", "asset-check-col");
      const rowChk = document.createElement("input");
      rowChk.type = "checkbox";
      rowChk.className = "asset-item-checkbox";
      rowChk.checked = !excluded;
      rowChk.addEventListener("change", () => {
        toggleExclusion(file, rowChk.checked);
        row.classList.toggle("is-excluded", !rowChk.checked);
        updateTableCheckAllState();
      });
      checkTd.appendChild(rowChk);

      const name = el("td", "asset-file-name");
      const nameText = document.createTextNode(file.name + " ");
      const tag = el("span", "asset-excluded-tag", t("assets.excluded"));
      name.append(nameText, tag);

      const location = el("td", "asset-relative-path", pathLabel(file));
      const model = file.model || "";
      const native = vehicles.find(v => v.model.toLowerCase() === model.toLowerCase());
      const modelCell = el("td", "asset-model-label", native
        ? `${t("assets.replacement")} ${native.name}` : model.toUpperCase() || "-");
      if (native) modelCell.classList.add("is-replacement");

      row.append(checkTd, name, location, modelCell, el("td", "asset-size", sizeLabel(file.size || 0)));
      body.appendChild(row);
    }
    table.appendChild(body);
    list.appendChild(table);
  }

  function showPreview(result) {
    preview = result;
    const pre = document.getElementById("assetTextContent");
    const editor = document.getElementById("assetConfigEditor");
    const editHint = document.getElementById("assetConfigEditHint");
    const status = document.getElementById("assetTextStatus");
    const copy = document.getElementById("assetCopyText");
    const retry = document.getElementById("assetRetryText");
    document.getElementById("assetTextPath").textContent = selected ? pathLabel(selected) : "";
    copy.disabled = !(result && result.success);
    retry.hidden = !(result && !result.success && result.error_code !== "binary");

    const isConfig = category === "configs";
    if (editHint) editHint.style.display = isConfig ? "inline-block" : "none";
    if (pre) pre.style.display = isConfig ? "none" : "block";
    if (editor) {
      editor.style.display = isConfig ? "block" : "none";
      if (isConfig && selected) {
        editor.value = selected.content || (result && result.content) || "";
      }
    }

    if (!selected) {
      if (pre) pre.textContent = "";
      if (editor) editor.value = "";
      status.textContent = "";
    } else if (isConfig) {
      const lineCount = (editor ? editor.value : "").split("\n").filter(Boolean).length;
      status.textContent = lineCountLabel(lineCount);
    } else if (!result) {
      if (pre) pre.textContent = "";
      status.textContent = t("assets.loading");
    } else if (result.success) {
      if (pre) {
        pre.textContent = result.content;
        pre.scrollTop = 0;
        pre.scrollLeft = 0;
      }
      status.textContent = result.truncated ? t("assets.truncated")
        : [result.encoding, selected.size !== undefined ? sizeLabel(selected.size) : ""].filter(Boolean).join(" / ");
    } else {
      if (pre) pre.textContent = "";
      status.textContent = t(result.error_code === "binary" ? "assets.binary" : "assets.unavailable");
    }
  }

  async function selectText(file) {
    cancelRequest();
    selected = file;
    const items = list.querySelectorAll(".asset-document-item, .asset-document-button");
    items.forEach((item, index) => {
      item.setAttribute("aria-pressed", String(visible[index] === selected));
    });
    if (category === "configs") {
      showPreview({ success: true, content: file.content });
      return;
    }
    showPreview(null);
    const currentSequence = sequence;
    request = new AbortController();
    try {
      const params = new URLSearchParams({ inspection_id: data.inspection_id || "", rel: pathLabel(file) });
      const response = await fetch(`/api/installer/preview-text?${params}`, { signal: request.signal });
      const result = await response.json();
      if (sequence === currentSequence) showPreview(result);
    } catch (error) {
      if (error.name !== "AbortError" && sequence === currentSequence) {
        showPreview({ success: false, error_code: "unavailable" });
      }
    }
  }

  function triggerApply() {
    if (onApplyCallback) {
      onApplyCallback(Array.from(excludedFiles), data ? data.parsed_config : null, editedConfigKeys);
    }
  }

  function refreshLanguage() {
    if (!dialog) return;
    document.getElementById("assetDialogClose").setAttribute("aria-label", t("assets.close"));
    updateFooter();
    if (dialog.open) {
      renderTabs();
      renderFiles();
    }
  }

  function init() {
    dialog = document.getElementById("installAssetDialog");
    list = document.getElementById("assetFileList");
    textPane = document.getElementById("assetTextPane");
    search = document.getElementById("assetFileSearch");

    document.getElementById("installFilesBreakdown").addEventListener("click", event => {
      const button = event.target.closest("button[data-asset-category]");
      if (button) open(button.dataset.assetCategory, button);
    });

    document.getElementById("assetDialogClose").addEventListener("click", () => {
      triggerApply();
      dialog.close();
    });

    const applyBtn = document.getElementById("assetApplyBtn");
    if (applyBtn) {
      applyBtn.addEventListener("click", () => {
        triggerApply();
        dialog.close();
      });
    }

    const selectAllBtn = document.getElementById("assetSelectAll");
    if (selectAllBtn) {
      selectAllBtn.addEventListener("click", selectAllVisible);
    }

    const deselectAllBtn = document.getElementById("assetDeselectAll");
    if (deselectAllBtn) {
      deselectAllBtn.addEventListener("click", deselectAllVisible);
    }

    dialog.addEventListener("click", event => {
      const rect = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right
          || event.clientY < rect.top || event.clientY > rect.bottom)) {
        triggerApply();
        dialog.close();
      }
    });

    dialog.addEventListener("close", () => {
      cancelRequest();
      triggerApply();
      if (opener && opener.isConnected) opener.focus();
    });

    search.addEventListener("input", renderFiles);

    const editor = document.getElementById("assetConfigEditor");
    if (editor) {
      editor.addEventListener("input", () => {
        if (category !== "configs" || !selected) return;
        selected.content = editor.value;
        const lines = editor.value.split("\n").map(l => l.trim()).filter(Boolean);
        if (data && data.parsed_config && selected.key) {
          data.parsed_config[selected.key] = lines;
          editedConfigKeys.add(selected.key);
        }
        selected.lineCount = lines.length;
        const status = document.getElementById("assetTextStatus");
        if (status) {
          status.textContent = lineCountLabel(lines.length) + t("assets.modifiedSuffix", " (modified)");
        }
        const activeBtnHint = list.querySelector('.asset-document-button[aria-pressed="true"] .asset-relative-path');
        if (activeBtnHint) {
          activeBtnHint.textContent = configLabel(selected) + " *";
        }
      });
    }

    document.getElementById("assetRetryText").addEventListener("click", () => selected && selectText(selected));
    document.getElementById("assetCopyText").addEventListener("click", async () => {
      let textToCopy = "";
      if (category === "configs") {
        const ed = document.getElementById("assetConfigEditor");
        textToCopy = ed ? ed.value : (preview ? preview.content : "");
      } else if (preview && preview.success) {
        textToCopy = preview.content;
      }
      if (!textToCopy) return;
      try {
        await navigator.clipboard.writeText(textToCopy);
        showToast(t("assets.copied"));
      } catch (_) {
        showToast(t("assets.copyFailed"), "error");
      }
    });

    refreshLanguage();
  }

  window.InstallAssets = {
    init,
    setData,
    reset,
    refreshLanguage,
    updateParsedConfig,
    getExcludedFiles: () => new Set(excludedFiles),
    setExcludedFiles: set => {
      excludedFiles = new Set(set);
      if (dialog && dialog.open) renderFiles();
      updateFooter();
    },
    getEditedConfigKeys: () => new Set(editedConfigKeys),
    onApply: cb => {
      onApplyCallback = cb;
    }
  };
})();
