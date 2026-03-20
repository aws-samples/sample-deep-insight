// ==================== Streaming Indicator ====================
function createBulbSVG() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.classList.add("streaming-indicator-logo");

    const defs = document.createElementNS(ns, "defs");
    const grad = document.createElementNS(ns, "linearGradient");
    grad.setAttribute("id", "bulb-grad");
    grad.setAttribute("x1", "0%");
    grad.setAttribute("y1", "0%");
    grad.setAttribute("x2", "100%");
    grad.setAttribute("y2", "100%");
    const stop1 = document.createElementNS(ns, "stop");
    stop1.setAttribute("offset", "0%");
    stop1.setAttribute("stop-color", "#c084fc");
    const stop2 = document.createElementNS(ns, "stop");
    stop2.setAttribute("offset", "100%");
    stop2.setAttribute("stop-color", "#f472b6");
    grad.appendChild(stop1);
    grad.appendChild(stop2);
    defs.appendChild(grad);
    svg.appendChild(defs);

    const bulb = document.createElementNS(ns, "path");
    bulb.setAttribute("d", "M9 21h6M12 3a6 6 0 0 0-4 10.5V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-3.5A6 6 0 0 0 12 3z");
    bulb.setAttribute("stroke", "url(#bulb-grad)");
    bulb.setAttribute("stroke-width", "1.8");
    bulb.setAttribute("stroke-linecap", "round");
    bulb.setAttribute("stroke-linejoin", "round");
    svg.appendChild(bulb);

    const lines = document.createElementNS(ns, "path");
    lines.setAttribute("d", "M10 17v1M14 17v1");
    lines.setAttribute("stroke", "url(#bulb-grad)");
    lines.setAttribute("stroke-width", "1.5");
    lines.setAttribute("stroke-linecap", "round");
    svg.appendChild(lines);

    const glow = document.createElementNS(ns, "circle");
    glow.setAttribute("cx", "12");
    glow.setAttribute("cy", "9");
    glow.setAttribute("r", "1.5");
    glow.setAttribute("fill", "url(#bulb-grad)");
    glow.setAttribute("opacity", "0.7");
    svg.appendChild(glow);

    return svg;
}

function showStreamingIndicator() {
    removeStreamingIndicator();
    const el = document.createElement("div");
    el.className = "streaming-indicator";
    el.id = "streaming-indicator";
    el.appendChild(createBulbSVG());
    const txt = document.createElement("span");
    txt.className = "streaming-indicator-text";
    txt.textContent = currentLang === "ko" ? "처리 중..." : "Processing...";
    el.appendChild(txt);
    outputDiv.appendChild(el);
    outputDiv.scrollTop = outputDiv.scrollHeight;
}

function removeStreamingIndicator() {
    const el = document.getElementById("streaming-indicator");
    if (el) el.remove();
}

// ==================== Output ====================
var MAX_OUTPUT_NODES = 500;  // Keep only last N nodes to prevent DOM bloat
var pendingOutput = [];
var flushScheduled = false;

function _flushOutput() {
    flushScheduled = false;
    if (pendingOutput.length === 0) return;

    removeStreamingIndicator();
    var frag = document.createDocumentFragment();
    for (var i = 0; i < pendingOutput.length; i++) {
        var item = pendingOutput[i];
        var span = document.createElement("span");
        span.className = item.cls || "";
        span.textContent = item.text;
        frag.appendChild(span);
    }
    pendingOutput = [];
    outputDiv.appendChild(frag);

    // Trim old nodes to prevent browser freeze
    while (outputDiv.childNodes.length > MAX_OUTPUT_NODES) {
        outputDiv.removeChild(outputDiv.firstChild);
    }

    showStreamingIndicator();
    outputDiv.scrollTop = outputDiv.scrollHeight;
}

function appendOutput(text, className) {
    if (!firstOutputReceived) {
        firstOutputReceived = true;
        document.getElementById("output-info").classList.add("hidden");
    }
    pendingOutput.push({ text: text, cls: className });
    if (!flushScheduled) {
        flushScheduled = true;
        requestAnimationFrame(_flushOutput);
    }
}

function stopElapsedTimer() {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
}

// ==================== Analyze ====================
function initAnalyze() {
    analyzeBtn.addEventListener("click", async () => {
        const query = queryInput.value.trim();
        if (!query || !currentUploadId) return;
        if (analysisInProgress) {
            alert(currentLang === "ko" ? "분석이 이미 진행 중입니다." : "Analysis is already in progress.");
            return;
        }

        analysisInProgress = true;
        analyzeBtn.disabled = true;
        outputSection.classList.remove("hidden");
        outputDiv.textContent = "";
        analysisStartTime = new Date();
        firstOutputReceived = false;

        const outputInfo = document.getElementById("output-info");
        const elapsedEl = document.getElementById("elapsed-timer");
        outputInfo.classList.remove("hidden");
        if (elapsedTimer) clearInterval(elapsedTimer);
        elapsedTimer = setInterval(() => {
            const sec = Math.floor((new Date() - analysisStartTime) / 1000);
            const m = Math.floor(sec / 60);
            const s = sec % 60;
            elapsedEl.textContent = ` (${m}:${s.toString().padStart(2, "0")})`;
        }, 1000);

        // Track last event time for stale connection detection
        var lastEventTime = Date.now();
        var sseDisconnectTime = null;
        sseCompleted = false;
        var stallCheckTimer = null;

        // Polling fallback: if no SSE event for 60s, check if reports are ready
        stallCheckTimer = setInterval(async function () {
            if (sseCompleted) { clearInterval(stallCheckTimer); return; }
            if (Date.now() - lastEventTime > 60000) {
                if (!sseDisconnectTime) {
                    sseDisconnectTime = new Date(lastEventTime);
                    stopElapsedTimer();
                }
                appendOutput(currentLang === "ko" ? "\n[리포트 확인 중...]\n" : "\n[Checking for reports...]\n", "event-text");
                var found = await fetchArtifacts(currentUploadId);
                if (found) {
                    sseCompleted = true;
                    clearInterval(stallCheckTimer);
                    removeStreamingIndicator();
                    appendOutput(currentLang === "ko" ? "\n[분석 완료 — 리포트가 준비되었습니다]\n" : "\n[Analysis complete — reports ready]\n", "event-done");
                    var elapsed = ((sseDisconnectTime - analysisStartTime) / 1000).toFixed(1);
                    appendOutput("Elapsed: " + elapsed + "s (" + (elapsed / 60).toFixed(1) + "min)\n", "event-done");
                    removeStreamingIndicator();
                }
            }
        }, 30000);

        try {
            const res = await fetch("/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ upload_id: currentUploadId, query }),
            });
            if (res.status === 429) {
                appendOutput(currentLang === "ko" ? "\n[다른 분석이 진행 중입니다. 완료 후 다시 시도해주세요]\n" : "\n[Another analysis is in progress. Please try again later]\n", "event-error");
                return;
            }
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                lastEventTime = Date.now();
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    try { handleSSEEvent(JSON.parse(line.slice(6))); } catch (_) {}
                }
            }
        } catch (err) {
            // SSE connection lost — record disconnect time and check for reports
            if (!sseCompleted) {
                if (!sseDisconnectTime) sseDisconnectTime = new Date(lastEventTime);
                stopElapsedTimer();
                appendOutput(currentLang === "ko" ? "\n[연결이 끊어졌습니다. 리포트 확인 중...]\n" : "\n[Connection lost. Checking for reports...]\n", "event-error");
                var found = await fetchArtifacts(currentUploadId);
                if (found) {
                    sseCompleted = true;
                    appendOutput(currentLang === "ko" ? "[리포트가 준비되었습니다]\n" : "[Reports ready]\n", "event-done");
                    var elapsed = ((sseDisconnectTime - analysisStartTime) / 1000).toFixed(1);
                    appendOutput("Elapsed: " + elapsed + "s (" + (elapsed / 60).toFixed(1) + "min)\n", "event-done");
                } else {
                    appendOutput(currentLang === "ko" ? "[아직 처리 중입니다. 잠시 후 새로고침 해주세요]\n" : "[Still processing. Please refresh later]\n", "event-error");
                }
            }
            removeStreamingIndicator();
        } finally {
            if (stallCheckTimer) clearInterval(stallCheckTimer);
            removeStreamingIndicator();
            analysisInProgress = false;
            analyzeBtn.disabled = false;
        }
    });
}

function handleSSEEvent(event) {
    switch (event.type) {
        case "agent_text_stream":
            let text = event.text;
            if (text.startsWith("Tool calling")) {
                text = "\n\n" + text + "\n";
            }
            else if (/^#{1,4}\s/.test(text.trimStart())) {
                text = "\n\n" + text + "\n";
            }
            else if (/[!.:\n]$/.test(text.trimEnd())) {
                text = text + "\n";
            }
            appendOutput(text, "event-text");
            break;
        case "agent_reasoning_stream": appendOutput(event.text, "event-reasoning"); break;
        case "workflow_complete":
            currentSessionId = event.session_id || null;
            sseCompleted = true;
            stopElapsedTimer();
            removeStreamingIndicator();
            appendOutput("\n[Analysis complete]\n", "event-done");
            removeStreamingIndicator();
            var endTime = new Date();
            var elapsed = ((endTime - analysisStartTime) / 1000).toFixed(1);
            appendOutput("Start: " + analysisStartTime.toLocaleTimeString() + "  End: " + endTime.toLocaleTimeString() + "  Elapsed: " + elapsed + "s (" + (elapsed / 60).toFixed(1) + "min)\n", "event-done");
            // Use filenames from event directly if available (no 15s delay)
            if (event.filenames && event.filenames.length > 0 && currentSessionId) {
                renderReportList(event.filenames, currentSessionId);
                downloadSection.classList.remove("hidden");
            } else if (currentSessionId) {
                fetchArtifactsWithRetry(currentSessionId);
            }
            break;
        case "error":
            stopElapsedTimer();
            removeStreamingIndicator();
            appendOutput("\nError: " + event.text + "\n", "event-error");
            removeStreamingIndicator();
            break;
        case "done": break;
        case "plan_review_request": showPlanModal(event); break;
        case "plan_review_keepalive": updateCountdown(event.timeout_seconds - event.elapsed_seconds); break;
        default: if (event.text) appendOutput(event.text, "event-text");
    }
}

// ==================== Plan Modal ====================
function initPlanModal() {
    approveBtn.addEventListener("click", () => submitFeedback(true));
    rejectBtn.addEventListener("click", () => submitFeedback(false));

    feedbackInput.addEventListener("input", () => {
        rejectBtn.disabled = feedbackInput.value.trim().length === 0;
    });

    feedbackInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && feedbackInput.value.trim().length > 0) {
            e.preventDefault();
            submitFeedback(false);
        }
    });
}

function showPlanModal(event) {
    currentRequestId = event.request_id;
    planText.textContent = event.plan;
    modalRevision.textContent = event.revision_count;
    modalMax.textContent = event.max_revisions;
    feedbackInput.value = "";
    startCountdown(event.timeout_seconds);
    planModal.classList.remove("hidden");
    appendOutput("\n[Plan review requested — revision " + event.revision_count + "/" + event.max_revisions + "]\n", "event-text");
}

function hidePlanModal() {
    planModal.classList.add("hidden");
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
}

function startCountdown(seconds) {
    if (countdownTimer) clearInterval(countdownTimer);
    let remaining = seconds;
    modalCountdown.textContent = remaining;
    countdownTimer = setInterval(() => {
        remaining--;
        modalCountdown.textContent = Math.max(remaining, 0);
        if (remaining <= 0) { clearInterval(countdownTimer); countdownTimer = null; }
    }, 1000);
}

function updateCountdown(remaining) {
    modalCountdown.textContent = Math.max(Math.round(remaining), 0);
}

async function submitFeedback(approved) {
    if (!currentRequestId) return;
    const fb = feedbackInput.value.trim();
    hidePlanModal();
    appendOutput(approved ? "[Plan approved]\n" : "[Plan rejected: " + (fb || "no feedback") + "]\n", approved ? "event-done" : "event-error");
    try {
        await fetch("/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ request_id: currentRequestId, approved, feedback: fb }),
        });
    } catch (err) {
        appendOutput("Feedback submit failed: " + err.message + "\n", "event-error");
    }
}

// ==================== Reports ====================
const EXT_GROUPS = {
    documents: { label_key: "report_group_documents", extensions: [".docx", ".pdf"] },
    text:      { label_key: "report_group_text",      extensions: [".txt"] },
    images:    { label_key: "report_group_images",     extensions: [".png", ".jpg", ".jpeg", ".gif", ".svg"] },
};
const EXT_BADGE_CLASS = {
    ".docx": "ext-docx", ".pdf": "ext-pdf", ".txt": "ext-txt",
    ".png": "ext-img", ".jpg": "ext-img", ".jpeg": "ext-img", ".gif": "ext-img", ".svg": "ext-img",
};

function getFileExtension(name) {
    const dot = name.lastIndexOf(".");
    return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function renderReportList(filenames, sessionId) {
    downloadList.innerHTML = "";
    const t = translations[currentLang];
    const grouped = {};
    for (const gk of Object.keys(EXT_GROUPS)) grouped[gk] = [];
    for (const name of filenames) {
        const ext = getFileExtension(name);
        for (const [gk, gd] of Object.entries(EXT_GROUPS)) {
            if (gd.extensions.includes(ext)) { grouped[gk].push(name); break; }
        }
    }
    for (const [gk, gd] of Object.entries(EXT_GROUPS)) {
        const files = grouped[gk];
        if (files.length === 0) continue;
        const groupDiv = document.createElement("div");
        groupDiv.className = "report-group";
        const title = document.createElement("div");
        title.className = "report-group-title";
        title.setAttribute("data-i18n", gd.label_key);
        title.textContent = t[gd.label_key] || gk;
        groupDiv.appendChild(title);
        for (const name of files.sort()) {
            const ext = getFileExtension(name);
            const item = document.createElement("div");
            item.className = "report-item";
            const badge = document.createElement("span");
            badge.className = "ext-badge " + (EXT_BADGE_CLASS[ext] || "ext-txt");
            badge.textContent = ext.replace(".", "");
            item.appendChild(badge);
            const link = document.createElement("a");
            link.className = "report-link";
            link.href = "/download/" + encodeURIComponent(sessionId) + "/" + name.split("/").map(encodeURIComponent).join("/");
            link.textContent = name.split("/").pop();
            item.appendChild(link);
            groupDiv.appendChild(item);
        }
        downloadList.appendChild(groupDiv);
    }

    // Add "Delete All Data" button
    const deleteDiv = document.createElement("div");
    deleteDiv.style.cssText = "margin-top: 16px; padding-top: 12px; border-top: 1px solid #e5e7eb;";
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "btn-cleanup";
    deleteBtn.textContent = currentLang === "ko" ? "분석 데이터 전체 삭제" : "Delete All Analysis Data";
    deleteBtn.style.cssText = "background: #ef4444; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px;";
    deleteBtn.addEventListener("click", async function () {
        var msg = currentLang === "ko"
            ? "업로드한 파일과 분석 결과가 모두 삭제됩니다. 계속하시겠습니까?"
            : "All uploaded files and analysis results will be deleted. Continue?";
        if (!confirm(msg)) return;
        deleteBtn.disabled = true;
        deleteBtn.textContent = currentLang === "ko" ? "삭제 중..." : "Deleting...";
        try {
            var res = await fetch("/cleanup/" + encodeURIComponent(sessionId), { method: "DELETE" });
            var data = await res.json();
            if (data.success) {
                downloadList.innerHTML = "";
                deleteDiv.remove();
                appendOutput(currentLang === "ko" ? "\n[데이터가 삭제되었습니다]\n" : "\n[Data deleted successfully]\n", "event-done");
            } else {
                alert(data.error || "Delete failed");
                deleteBtn.disabled = false;
                deleteBtn.textContent = currentLang === "ko" ? "분석 데이터 전체 삭제" : "Delete All Analysis Data";
            }
        } catch (err) {
            alert("Delete failed: " + err.message);
            deleteBtn.disabled = false;
            deleteBtn.textContent = currentLang === "ko" ? "분석 데이터 전체 삭제" : "Delete All Analysis Data";
        }
    });
    deleteDiv.appendChild(deleteBtn);
    downloadList.appendChild(deleteDiv);
}

async function fetchArtifacts(sessionId) {
    try {
        const res = await fetch("/artifacts/" + encodeURIComponent(sessionId));
        const data = await res.json();
        if (data.success && data.filenames.length > 0) {
            renderReportList(data.filenames, sessionId);
            downloadSection.classList.remove("hidden");
            return true;
        }
    } catch (err) {
        appendOutput("Failed to fetch artifacts: " + err.message + "\n", "event-error");
    }
    return false;
}

async function fetchArtifactsWithRetry(sessionId, retries = 10, delayMs = 15000) {
    appendOutput("[Waiting for reports to upload...]\n", "event-text");
    for (let i = 0; i < retries; i++) {
        await new Promise(r => setTimeout(r, delayMs));
        const found = await fetchArtifacts(sessionId);
        if (found) {
            const endTime = new Date();
            const elapsed = ((endTime - analysisStartTime) / 1000).toFixed(1);
            const fmt = d => d.toLocaleTimeString();
            appendOutput("[Reports ready]\n", "event-done");
            appendOutput("Start: " + fmt(analysisStartTime) + "  End: " + fmt(endTime) + "  Elapsed: " + elapsed + "s (" + (elapsed / 60).toFixed(1) + "min)\n", "event-done");
            return;
        }
    }
    appendOutput("[Reports not available yet. Try refreshing later.]\n", "event-error");
}
