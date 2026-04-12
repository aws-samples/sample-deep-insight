// ==================== Drag & Drop ====================
function initUpload() {
    const dropZone = document.getElementById("drop-zone");
    const dataFileInput = document.getElementById("data-file");

    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
    dropZone.addEventListener("dragleave", () => { dropZone.classList.remove("dragover"); });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            dataFileInput.files = e.dataTransfer.files;
            showSelectedFile(e.dataTransfer.files[0].name);
        }
    });
    dataFileInput.addEventListener("change", () => {
        if (dataFileInput.files.length > 0) {
            showSelectedFile(dataFileInput.files[0].name);
        }
    });

    // Column definition drag & drop
    const coldefZone = document.getElementById("drop-zone-coldef");
    const coldefInput = document.getElementById("col-def");

    coldefZone.addEventListener("dragover", (e) => { e.preventDefault(); coldefZone.classList.add("dragover"); });
    coldefZone.addEventListener("dragleave", () => { coldefZone.classList.remove("dragover"); });
    coldefZone.addEventListener("drop", (e) => {
        e.preventDefault();
        coldefZone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            coldefInput.files = e.dataTransfer.files;
            showSelectedColdef(e.dataTransfer.files[0].name);
        }
    });
    coldefInput.addEventListener("change", () => {
        if (coldefInput.files.length > 0) {
            showSelectedColdef(coldefInput.files[0].name);
        }
    });

    // Auto-generate column definitions
    initColdefAutogen();

    // Upload form submission
    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const dataFile = document.getElementById("data-file").files[0];
        if (!dataFile) return;

        const formData = new FormData();
        formData.append("data_file", dataFile);
        const colDef = document.getElementById("col-def").files[0];
        if (colDef) {
            formData.append("column_definitions", colDef);
        } else if (_generatedColdefJson) {
            // Use auto-generated column definitions
            const blob = new Blob([JSON.stringify(_generatedColdefJson, null, 2)], { type: "application/json" });
            formData.append("column_definitions", blob, "column_definitions.json");
        }

        uploadBtn.disabled = true;
        statusDiv.textContent = translations[currentLang].status_uploading;
        statusDiv.style.color = "var(--text-muted)";

        try {
            const res = await fetch("/upload", { method: "POST", body: formData });
            const data = await res.json();
            if (data.success) {
                currentUploadId = data.upload_id;
                const fileNames = colDef ? dataFile.name + ", " + colDef.name : dataFile.name;
                statusDiv.textContent = translations[currentLang].status_upload_complete + data.upload_id + "\n📄 " + fileNames;
                statusDiv.style.whiteSpace = "pre-line";
                statusDiv.style.color = "var(--green)";
                analyzeSection.classList.remove("hidden");
                analyzeBtn.disabled = false;
                analyzeSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } else {
                statusDiv.textContent = translations[currentLang].status_upload_failed + (data.error || "Unknown error");
                statusDiv.style.color = "var(--red)";
            }
        } catch (err) {
            statusDiv.textContent = translations[currentLang].status_upload_failed + err.message;
            statusDiv.style.color = "var(--red)";
        } finally {
            uploadBtn.disabled = false;
        }
    });
}

function showSelectedFile(name) {
    const t = translations[currentLang];
    const selectedFileDiv = document.getElementById("selected-file");
    const dropZone = document.getElementById("drop-zone");
    const span = document.createElement("span");
    span.className = "file-selected";
    span.textContent = "📄 " + (t.file_selected || "") + name + " ";
    const removeBtn = document.createElement("span");
    removeBtn.className = "remove-file";
    removeBtn.addEventListener("click", clearFile);
    removeBtn.title = "Remove";
    removeBtn.textContent = "✕";
    span.appendChild(removeBtn);
    selectedFileDiv.textContent = "";
    selectedFileDiv.appendChild(span);
    selectedFileDiv.classList.remove("hidden");
    dropZone.classList.add("hidden");
    // Show auto-generate option if CSV-like file and no coldef selected
    updateAutogenVisibility();
}

function clearFile() {
    const dataFileInput = document.getElementById("data-file");
    const selectedFileDiv = document.getElementById("selected-file");
    const dropZone = document.getElementById("drop-zone");
    dataFileInput.value = "";
    selectedFileDiv.textContent = "";
    selectedFileDiv.classList.add("hidden");
    dropZone.classList.remove("hidden");
    hideAutogenArea();
}

function showSelectedColdef(name) {
    const t = translations[currentLang];
    const selectedDiv = document.getElementById("selected-coldef");
    const coldefZone = document.getElementById("drop-zone-coldef");
    selectedDiv.textContent = "";
    const span = document.createElement("span");
    span.className = "file-selected";
    span.textContent = "📄 " + (t.file_selected || "") + name + " ";
    const removeBtn = document.createElement("span");
    removeBtn.className = "remove-file";
    removeBtn.title = "Remove";
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", clearColdef);
    span.appendChild(removeBtn);
    selectedDiv.appendChild(span);
    selectedDiv.classList.remove("hidden");
    coldefZone.classList.add("hidden");
    hideAutogenArea();
}

function clearColdef() {
    const coldefInput = document.getElementById("col-def");
    const selectedDiv = document.getElementById("selected-coldef");
    const coldefZone = document.getElementById("drop-zone-coldef");
    coldefInput.value = "";
    selectedDiv.textContent = "";
    selectedDiv.classList.add("hidden");
    coldefZone.classList.remove("hidden");
    _generatedColdefJson = null;
    updateAutogenVisibility();
}

// ==================== Auto-generate Column Definitions ====================
let _generatedColdefJson = null;
let _isEditing = false;
let _viewMode = "table"; // "table" or "json"

function updateAutogenVisibility() {
    const area = document.getElementById("coldef-autogen-area");
    const divider = document.getElementById("coldef-manual-divider");
    const dataFile = document.getElementById("data-file").files[0];
    const colDef = document.getElementById("col-def").files[0];
    const reviewPanel = document.getElementById("coldef-review-panel");
    const isReviewing = reviewPanel && !reviewPanel.classList.contains("hidden");

    if (dataFile && !colDef && !isReviewing && !_generatedColdefJson) {
        area.classList.remove("hidden");
        divider.classList.remove("hidden");
    } else {
        area.classList.add("hidden");
        divider.classList.add("hidden");
    }
}

function hideAutogenArea() {
    document.getElementById("coldef-autogen-area").classList.add("hidden");
    document.getElementById("coldef-manual-divider").classList.add("hidden");
    document.getElementById("coldef-review-panel").classList.add("hidden");
    document.getElementById("coldef-autogen-status").classList.add("hidden");
    _generatedColdefJson = null;
    _isEditing = false;
}

function initColdefAutogen() {
    const autogenBtn = document.getElementById("coldef-autogen-btn");
    const regenBtn = document.getElementById("coldef-regen-btn");
    const editToggleBtn = document.getElementById("coldef-edit-toggle-btn");
    const confirmBtn = document.getElementById("coldef-confirm-btn");
    const cancelBtn = document.getElementById("coldef-cancel-btn");

    const viewToggleBtn = document.getElementById("coldef-view-toggle-btn");

    autogenBtn.addEventListener("click", () => generateColdef());
    regenBtn.addEventListener("click", () => generateColdef());
    viewToggleBtn.addEventListener("click", toggleColdefView);
    editToggleBtn.addEventListener("click", toggleColdefEdit);
    confirmBtn.addEventListener("click", confirmColdef);
    cancelBtn.addEventListener("click", cancelColdef);
}

async function generateColdef() {
    const dataFile = document.getElementById("data-file").files[0];
    if (!dataFile) return;

    const t = translations[currentLang];
    const autogenBtn = document.getElementById("coldef-autogen-btn");
    const statusDiv = document.getElementById("coldef-autogen-status");
    const reviewPanel = document.getElementById("coldef-review-panel");

    // Show loading
    autogenBtn.disabled = true;
    autogenBtn.textContent = t.coldef_generating || "⏳ 생성 중...";
    statusDiv.classList.remove("hidden");
    statusDiv.textContent = t.coldef_generating_hint || "AI가 컬럼 정의를 분석하고 있습니다...";
    statusDiv.style.color = "var(--text-muted)";
    reviewPanel.classList.add("hidden");

    try {
        const formData = new FormData();
        formData.append("data_file", dataFile);
        formData.append("lang", currentLang);

        const res = await fetch("/generate-column-definitions", { method: "POST", body: formData });
        const data = await res.json();

        if (data.success) {
            _generatedColdefJson = data.column_definitions;
            showColdefReview(data.column_definitions);
            statusDiv.classList.add("hidden");
            document.getElementById("coldef-autogen-area").classList.add("hidden");
            document.getElementById("coldef-manual-divider").classList.add("hidden");
        } else {
            statusDiv.textContent = (t.coldef_gen_failed || "생성 실패: ") + (data.error || "Unknown error");
            statusDiv.style.color = "var(--red)";
        }
    } catch (err) {
        statusDiv.textContent = (t.coldef_gen_failed || "생성 실패: ") + err.message;
        statusDiv.style.color = "var(--red)";
    } finally {
        autogenBtn.disabled = false;
        autogenBtn.textContent = t.coldef_autogen_btn || "🤖 컬럼 정의 자동 생성";
    }
}

function showColdefReview(coldefArray) {
    const preview = document.getElementById("coldef-review-preview");
    const tableDiv = document.getElementById("coldef-review-table");
    const editor = document.getElementById("coldef-review-editor");
    const panel = document.getElementById("coldef-review-panel");

    const jsonStr = JSON.stringify(coldefArray, null, 2);
    preview.textContent = jsonStr;
    editor.value = jsonStr;
    renderColdefTable(coldefArray);

    _isEditing = false;
    _viewMode = "table";
    tableDiv.classList.remove("hidden");
    preview.classList.add("hidden");
    editor.classList.add("hidden");
    updateViewToggleBtn();
    panel.classList.remove("hidden");
    panel.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderColdefTable(coldefArray) {
    const t = translations[currentLang];
    const tableDiv = document.getElementById("coldef-review-table");
    const headerName = t.coldef_table_col_name || "컬럼명";
    const headerDesc = t.coldef_table_col_desc || "설명";

    let html = `<table class="coldef-table"><thead><tr><th>${headerName}</th><th>${headerDesc}</th></tr></thead><tbody>`;
    for (const col of coldefArray) {
        const name = (col.column_name || "").replace(/</g, "&lt;");
        const desc = (col.column_desc || "").replace(/</g, "&lt;");
        html += `<tr><td class="coldef-table-name">${name}</td><td>${desc}</td></tr>`;
    }
    html += "</tbody></table>";
    tableDiv.innerHTML = html;
}

function toggleColdefView() {
    if (_isEditing) return; // Don't toggle while editing

    const preview = document.getElementById("coldef-review-preview");
    const tableDiv = document.getElementById("coldef-review-table");

    if (_viewMode === "table") {
        _viewMode = "json";
        tableDiv.classList.add("hidden");
        preview.classList.remove("hidden");
    } else {
        _viewMode = "table";
        preview.classList.add("hidden");
        tableDiv.classList.remove("hidden");
    }
    updateViewToggleBtn();
}

function updateViewToggleBtn() {
    const btn = document.getElementById("coldef-view-toggle-btn");
    const t = translations[currentLang];
    if (_viewMode === "table") {
        btn.textContent = t.coldef_view_json || "{ } JSON";
        btn.classList.remove("btn-view-active");
    } else {
        btn.textContent = t.coldef_view_table || "📊 테이블";
        btn.classList.add("btn-view-active");
    }
}

function toggleColdefEdit() {
    const preview = document.getElementById("coldef-review-preview");
    const editor = document.getElementById("coldef-review-editor");
    const t = translations[currentLang];
    const btn = document.getElementById("coldef-edit-toggle-btn");

    _isEditing = !_isEditing;
    if (_isEditing) {
        editor.value = preview.textContent;
        preview.classList.add("hidden");
        document.getElementById("coldef-review-table").classList.add("hidden");
        editor.classList.remove("hidden");
        editor.focus();
        btn.textContent = t.coldef_preview_btn || "👁 미리보기";
    } else {
        // Validate JSON on switch back
        try {
            const parsed = JSON.parse(editor.value);
            preview.textContent = JSON.stringify(parsed, null, 2);
            _generatedColdefJson = parsed;
            renderColdefTable(parsed);
        } catch {
            // Keep editor open if invalid
            _isEditing = true;
            editor.style.borderColor = "var(--red)";
            setTimeout(() => { editor.style.borderColor = ""; }, 1500);
            return;
        }
        editor.classList.add("hidden");
        // Restore the active view mode
        if (_viewMode === "table") {
            document.getElementById("coldef-review-table").classList.remove("hidden");
            preview.classList.add("hidden");
        } else {
            preview.classList.remove("hidden");
            document.getElementById("coldef-review-table").classList.add("hidden");
        }
        btn.textContent = t.coldef_edit_btn || "✏️ 직접 수정";
    }
}

function confirmColdef() {
    const t = translations[currentLang];

    // If editing, save current editor content
    if (_isEditing) {
        try {
            _generatedColdefJson = JSON.parse(document.getElementById("coldef-review-editor").value);
        } catch {
            return;  // Invalid JSON, don't confirm
        }
    }

    // Show as selected coldef
    const selectedDiv = document.getElementById("selected-coldef");
    const coldefZone = document.getElementById("drop-zone-coldef");
    selectedDiv.textContent = "";
    const span = document.createElement("span");
    span.className = "file-selected";
    span.textContent = "🤖 " + (t.coldef_auto_generated || "자동 생성됨: column_definitions.json") + " ";
    const removeBtn = document.createElement("span");
    removeBtn.className = "remove-file";
    removeBtn.title = "Remove";
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", clearColdef);
    span.appendChild(removeBtn);
    selectedDiv.appendChild(span);
    selectedDiv.classList.remove("hidden");
    coldefZone.classList.add("hidden");

    // Hide review panel, autogen area, and divider
    document.getElementById("coldef-review-panel").classList.add("hidden");
    document.getElementById("coldef-autogen-area").classList.add("hidden");
    document.getElementById("coldef-manual-divider").classList.add("hidden");
    _isEditing = false;
}

function cancelColdef() {
    document.getElementById("coldef-review-panel").classList.add("hidden");
    _generatedColdefJson = null;
    _isEditing = false;
    updateAutogenVisibility();
}

// ==================== Refresh on language change ====================
function refreshSelectedFileDisplays() {
    const dataFile = document.getElementById("data-file").files[0];
    const selectedFileDiv = document.getElementById("selected-file");
    if (dataFile && !selectedFileDiv.classList.contains("hidden")) {
        showSelectedFile(dataFile.name);
    }

    const colDef = document.getElementById("col-def").files[0];
    const selectedColdef = document.getElementById("selected-coldef");
    if (colDef && !selectedColdef.classList.contains("hidden")) {
        showSelectedColdef(colDef.name);
    } else if (_generatedColdefJson && !selectedColdef.classList.contains("hidden")) {
        // Re-render auto-generated badge with updated language
        const t = translations[currentLang];
        selectedColdef.textContent = "";
        const span = document.createElement("span");
        span.className = "file-selected";
        span.textContent = "🤖 " + (t.coldef_auto_generated || "자동 생성됨: column_definitions.json") + " ";
        const removeBtn = document.createElement("span");
        removeBtn.className = "remove-file";
        removeBtn.title = "Remove";
        removeBtn.textContent = "✕";
        removeBtn.addEventListener("click", clearColdef);
        span.appendChild(removeBtn);
        selectedColdef.appendChild(span);
    }

    // Refresh review table headers if visible
    const reviewPanel = document.getElementById("coldef-review-panel");
    if (_generatedColdefJson && reviewPanel && !reviewPanel.classList.contains("hidden")) {
        renderColdefTable(_generatedColdefJson);
        updateViewToggleBtn();
    }
}

// ==================== Sample Data ====================
let allSampleDatasets = [];

async function loadSampleData() {
    try {
        const res = await fetch("/sample-data");
        const data = await res.json();
        allSampleDatasets = data.datasets || [];
    } catch (err) {
        allSampleDatasets = [];
    }
    renderSampleDataLinks();
}

function renderSampleDataLinks() {
    const container = document.getElementById("sample-data-links");
    const t = translations[currentLang];
    const suffix = currentLang === "ko" ? "-kr" : "-en";
    const filtered = allSampleDatasets.filter(ds => ds.name.endsWith(suffix));
    if (filtered.length === 0) {
        container.innerHTML = `<span style="color:var(--text-muted)">${t.sample_none}</span>`;
        return;
    }
    container.innerHTML = "";
    for (const ds of filtered) {
        for (const file of ds.files) {
            const a = document.createElement("a");
            a.className = "sample-link";
            a.href = `/sample-data/${encodeURIComponent(ds.name)}/${encodeURIComponent(file)}`;
            a.download = file;
            a.textContent = file;
            container.appendChild(a);
        }
    }
}

// ==================== Sample Reports ====================
let allSampleReports = [];

async function loadSampleReports() {
    try {
        const res = await fetch("/sample-reports");
        const data = await res.json();
        allSampleReports = data.reports || [];
    } catch (err) {
        allSampleReports = [];
    }
    renderSampleReportsLinks();
}

function renderSampleReportsLinks() {
    const container = document.getElementById("sample-reports-links");
    const t = translations[currentLang];
    const langTag = currentLang === "ko" ? "_kr_" : "_en_";
    const filtered = allSampleReports.filter(name => name.includes(langTag));
    if (filtered.length === 0) {
        container.innerHTML = `<span style="color:var(--text-muted)">${t.sample_reports_none}</span>`;
        return;
    }
    container.innerHTML = "";
    for (const file of filtered) {
        const a = document.createElement("a");
        a.className = "sample-link";
        a.href = `/sample-reports/${encodeURIComponent(file)}`;
        a.download = file;
        a.textContent = file;
        container.appendChild(a);
    }
}
