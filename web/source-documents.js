/* Inspector document viewer. Source text is never interpreted as HTML or configuration. */
(function () {
  let generation = 0;
  let controller = null;
  let currentDetail = null;
  let selectedPath = "";
  let currentRoot = "";
  const t = (key) => window.t(key);
  const el = (id) => document.getElementById(id);

  function render(detail) {
    generation += 1;
    if (controller) controller.abort();
    controller = null;
    const select = el("sourceDocumentSelect");
    const content = el("rawReadmeContent");
    if (!select || !content) return;
    const root = detail ? (detail.mod_dir || "") : "";
    if (root !== currentRoot) selectedPath = "";
    currentRoot = root;
    currentDetail = detail;
    const files = detail && Array.isArray(detail.source_documents) ? detail.source_documents : [];
    select.replaceChildren();
    el("sourceDocumentStatus").textContent = "";
    el("sourceDocumentSize").textContent = "";
    el("sourceDocumentNotice").hidden = true;
    select.disabled = !files.length;
    select.onchange = () => loadSelected();
    if (!files.length) {
      selectedPath = "";
      content.textContent = t(detail ? "sources.empty" : "sources.selectMod");
      return;
    }
    for (const file of files) {
      const option = document.createElement("option");
      option.value = file.path;
      option.textContent = file.path;
      select.appendChild(option);
    }
    select.value = files.some(f => f.path === selectedPath) ? selectedPath : files[0].path;
    return loadSelected();
  }

  async function loadSelected() {
    const ticket = ++generation;
    if (controller) controller.abort();
    controller = new AbortController();
    const select = el("sourceDocumentSelect");
    const content = el("rawReadmeContent");
    const notice = el("sourceDocumentNotice");
    selectedPath = select.value;
    const file = (currentDetail.source_documents || []).find(f => f.path === selectedPath);
    if (!file) return;
    el("sourceDocumentStatus").textContent = t(file.archived ? "sources.archived" : "sources.active");
    el("sourceDocumentSize").textContent = `${(file.size / 1024).toFixed(1)} KB`;
    content.textContent = t("sources.loading");
    content.scrollTop = 0;
    notice.hidden = true;
    try {
      const query = new URLSearchParams({ full_path: currentRoot, document: selectedPath });
      const response = await fetch(`/api/mod-document?${query}`, { signal: controller.signal });
      const result = await response.json();
      if (ticket !== generation) return;
      if (!response.ok || !result.success) throw new Error("unavailable");
      content.textContent = result.content;
      notice.textContent = result.truncated ? t("sources.truncated") : t("sources.encoding").replace("{0}", result.encoding);
      notice.hidden = false;
    } catch (error) {
      if (ticket !== generation || error.name === "AbortError") return;
      content.textContent = t("sources.failed");
    }
  }

  window.SourceDocuments = { render };
})();
