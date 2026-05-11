// ==================== Data Q&A Chat (DuckDB / SQL mode) ====================

let chatStreaming = false;
let chatUploadId = null;
let chatWelcomeRendered = false;
let chatMessagesEl, chatInputEl, chatSendBtnEl;

function initChat() {
    chatMessagesEl = document.getElementById("chat-messages");
    chatInputEl = document.getElementById("chat-input");
    chatSendBtnEl = document.getElementById("chat-send-btn");

    if (!chatInputEl) return; // view not rendered yet

    // Auto-resize textarea
    chatInputEl.addEventListener("input", function () {
        this.style.height = "auto";
        this.style.height = Math.min(this.scrollHeight, 160) + "px";
    });

    // Enter sends, Shift+Enter newline
    chatInputEl.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey && !chatStreaming) {
            e.preventDefault();
            sendChatMessage();
        }
    });
}

// Called from upload.js after a successful upload
function setChatUploadId(uploadId) {
    // A new upload invalidates any prior Q&A session in-page
    if (chatUploadId && chatUploadId !== uploadId) {
        chatMessagesEl.innerHTML = "";
        chatWelcomeRendered = false;
    }
    chatUploadId = uploadId;
}

// Lazy welcome: only run when user first opens the Q&A tab
function initChatWelcomeIfNeeded() {
    if (chatWelcomeRendered || !chatUploadId) return;
    chatWelcomeRendered = true;
    renderWelcome();
}

// ==================== Welcome card ====================

function renderWelcome() {
    chatMessagesEl.innerHTML = "";

    const metaBox = document.getElementById("qna-meta");
    if (metaBox) metaBox.innerHTML = '<div class="qna-meta-loading">데이터 불러오는 중...</div>';

    const welcome = document.createElement("div");
    welcome.className = "qna-welcome";
    welcome.innerHTML =
        '<div class="qna-welcome-icon">' +
            '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>' +
        '</div>' +
        '<h2 class="qna-welcome-title" data-i18n="chat_title">Data Q&amp;A</h2>' +
        '<p class="qna-welcome-desc" data-i18n="chat_welcome">업로드된 데이터에 대해 자유롭게 질문해보세요.</p>' +
        '<div class="qna-welcome-chips" id="welcome-chips"></div>';
    chatMessagesEl.appendChild(welcome);

    // Apply current language to static i18n strings in the welcome block
    if (typeof applyLanguage === "function") applyLanguage();

    // Fetch dataset summary
    fetch("/chat/meta?upload_id=" + encodeURIComponent(chatUploadId))
        .then(r => r.json())
        .then(data => {
            if (!metaBox) return;
            if (!data.success) {
                metaBox.innerHTML = '<div class="qna-meta-error">' + escapeHtml(data.error || "metadata load failed") + '</div>';
                return;
            }
            renderMetaPanel(metaBox, data);
        })
        .catch(() => {
            if (metaBox) metaBox.innerHTML = "";
        });

    // Fetch dynamic suggestions
    fetch("/chat/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: chatUploadId })
    })
        .then(r => r.json())
        .then(data => {
            const chipsEl = document.getElementById("welcome-chips");
            if (!chipsEl) return;
            const suggestions = (data && data.suggestions) || [];
            renderChips(chipsEl, suggestions);
        })
        .catch(() => {});
}

// ==================== Dataset meta panel + column chips ====================

const DEFAULT_COL_CHIPS_VISIBLE = 12;

function renderMetaPanel(metaBox, data) {
    const summaryRow =
        '<div class="qna-meta-summary">' +
            '<span class="qna-meta-item"><span class="qna-meta-item-label">파일</span> ' + escapeHtml(data.filename) + '</span>' +
            '<span class="qna-meta-sep">·</span>' +
            '<span class="qna-meta-item"><span class="qna-meta-item-label">행</span> ' + data.rows.toLocaleString() + '</span>' +
            '<span class="qna-meta-sep">·</span>' +
            '<span class="qna-meta-item"><span class="qna-meta-item-label">컬럼</span> ' + data.columns.length + '</span>' +
        '</div>';

    const chipsHtml = renderColumnChipsHtml(data.columns);

    metaBox.innerHTML =
        '<div class="qna-meta-panel">' +
            summaryRow +
            '<div class="qna-columns" id="qna-columns">' + chipsHtml + '</div>' +
        '</div>';
}

function renderColumnChipsHtml(columns) {
    const total = columns.length;
    const limit = total > DEFAULT_COL_CHIPS_VISIBLE ? DEFAULT_COL_CHIPS_VISIBLE : total;
    const chips = columns.map((c, idx) => {
        const hidden = idx >= limit ? " qna-col-hidden" : "";
        const tooltip = buildColumnTooltip(c);
        return (
            '<button class="qna-col-chip' + hidden + '"' +
            ' data-col="' + escapeHtml(c.name) + '"' +
            ' data-type="' + escapeHtml(c.type) + '"' +
            ' title="' + escapeHtml(tooltip) + '"' +
            ' onclick="onColumnChipClick(this)">' +
                '<span class="qna-col-name">' + escapeHtml(c.name) + '</span>' +
                '<span class="qna-col-type">' + escapeHtml(shortType(c.type)) + '</span>' +
            '</button>'
        );
    }).join("");

    let more = "";
    if (total > DEFAULT_COL_CHIPS_VISIBLE) {
        const hiddenCount = total - DEFAULT_COL_CHIPS_VISIBLE;
        more =
            '<button class="qna-col-more" onclick="toggleMoreColumns(this)">' +
                '+' + hiddenCount + ' 더보기' +
            '</button>';
    }
    return chips + more;
}

function buildColumnTooltip(c) {
    // name (TYPE) — description. Fallback: CAST hint if no desc.
    let tip = c.name + " (" + c.type + ")";
    if (c.desc) {
        tip += "\n" + c.desc;
    } else {
        tip += "\n타입이 의도와 다르면 SQL에서 CAST(컬럼 AS DOUBLE) 등으로 변환하세요.";
    }
    return tip;
}

function shortType(t) {
    // Compact type label for the chip body
    if (!t) return "";
    const up = t.toUpperCase();
    if (up.startsWith("VARCHAR")) return "TEXT";
    if (up === "BIGINT" || up === "INTEGER" || up === "HUGEINT") return "INT";
    if (up === "DOUBLE" || up === "FLOAT" || up === "DECIMAL") return "NUM";
    if (up.startsWith("TIMESTAMP")) return "TIME";
    return up;
}

function toggleMoreColumns(btn) {
    const panel = btn.parentElement;
    const chips = panel.querySelectorAll(".qna-col-chip");
    const expanded = panel.classList.toggle("qna-columns-expanded");
    if (expanded) {
        chips.forEach(el => el.classList.remove("qna-col-hidden"));
        btn.textContent = "접기";
    } else {
        chips.forEach((el, idx) => {
            el.classList.toggle("qna-col-hidden", idx >= DEFAULT_COL_CHIPS_VISIBLE);
        });
        const hiddenCount = chips.length - DEFAULT_COL_CHIPS_VISIBLE;
        btn.textContent = "+" + hiddenCount + " 더보기";
    }
}

// Clicking a column chip → fill the input with a type-aware starter question.
function onColumnChipClick(btn) {
    const col = btn.dataset.col;
    const type = (btn.dataset.type || "").toUpperCase();
    const q = buildColumnQuestion(col, type);
    if (!chatInputEl) return;
    chatInputEl.value = q;
    chatInputEl.focus();
    chatInputEl.dispatchEvent(new Event("input"));  // trigger autosize
}

function buildColumnQuestion(col, type) {
    // Heuristic: pick a question template based on inferred type.
    const q = (s) => '"' + s + '"';
    if (/DATE|TIME/.test(type)) {
        return q(col) + "별 추이를 라인 차트로 보여줘";
    }
    if (/INT|DOUBLE|DECIMAL|FLOAT|HUGEINT|BIGINT/.test(type)) {
        return q(col) + "의 기본 통계(min / max / 평균 / 합계)를 보여줘";
    }
    // VARCHAR / category-like
    return q(col) + "별 건수 TOP 10을 차트로 보여줘";
}

function renderChips(container, suggestions) {
    if (!container) return;
    container.innerHTML = "";
    suggestions.forEach(text => {
        const chip = document.createElement("button");
        chip.className = "qna-chip";
        chip.textContent = text;
        chip.onclick = () => {
            chatInputEl.value = text;
            sendChatMessage();
        };
        container.appendChild(chip);
    });
}

function showFollowUpChips(suggestions) {
    const container = document.createElement("div");
    container.className = "qna-followup";
    renderChips(container, suggestions);
    chatMessagesEl.appendChild(container);
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function extractAndShowSuggestions(bubble) {
    // Prefer the segmented source of truth so the bubble re-renders cleanly.
    if (bubble._segments) {
        const re = /\[SUGGESTIONS\]([\s\S]*?)\[\/SUGGESTIONS\]/;
        let captured = null;
        for (const seg of bubble._segments) {
            if (seg.kind !== "text") continue;
            const m = seg.raw.match(re);
            if (m) {
                captured = m[1];
                seg.raw = seg.raw.replace(m[0], "").replace(/\n+$/, "");
                break;
            }
        }
        if (captured) {
            // Re-render without the [SUGGESTIONS] payload
            let html = "";
            for (const s of bubble._segments) {
                html += s.kind === "text" ? renderMarkdown(s.raw) : s.html;
            }
            bubble.innerHTML = html;
            const items = captured.split("|").map(s => s.trim()).filter(Boolean);
            if (items.length) showFollowUpChips(items);
            return;
        }
    }
    // Fallback (legacy bubbles without segments)
    const html = bubble.innerHTML;
    const match = html.match(/\[SUGGESTIONS\]([\s\S]*?)\[\/SUGGESTIONS\]/);
    if (!match) return;
    bubble.innerHTML = html.replace(match[0], "").replace(/<br>\s*$/, "");
    const items = match[1].split("|").map(s => stripTags(s).trim()).filter(Boolean);
    if (items.length) showFollowUpChips(items);
}

// Idempotent tag stripping. A single regex pass leaves overlapping tags
// behind ("<scr<script>ipt>" → "<script>"), so we iterate to a fixed point.
// Suggestion text feeds chip labels (textContent today), but downgrading the
// stripper is the kind of change that silently re-opens XSS if a later edit
// flips the chip target to innerHTML.
function stripTags(s) {
    let prev;
    let cur = String(s == null ? "" : s);
    do {
        prev = cur;
        cur = cur.replace(/<[^>]*>/g, "");
    } while (cur !== prev);
    return cur;
}

// ==================== Bubbles / indicators ====================

function appendBubble(role, html) {
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble chat-bubble-" + role;
    if (html) bubble.innerHTML = html;
    chatMessagesEl.appendChild(bubble);
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    return bubble;
}

function appendToolIndicator(toolName) {
    let label = "처리 중...";
    if (toolName === "create_chart") label = "차트 생성 중...";
    else if (toolName === "query_sql") label = "SQL 실행 중...";
    else if (toolName === "describe_schema") label = "스키마 조회 중...";

    const el = document.createElement("div");
    el.className = "chat-tool-indicator";
    el.innerHTML = '<span class="chat-tool-spinner"></span> ' + label;
    chatMessagesEl.appendChild(el);
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    return el;
}

function removeToolIndicator(el) {
    if (el && el.parentNode) el.parentNode.removeChild(el);
}

// ==================== SQL block (inline view / edit / re-run) ====================

let _sqlBlockSeq = 0;
function renderSqlBlock(sql) {
    const id = "sql-block-" + (++_sqlBlockSeq);
    const escaped = escapeHtml(sql.trim());
    // Default: collapsed — only the header chip is visible; click to expand.
    return (
        '<div class="sql-block sql-collapsed" id="' + id + '">' +
            '<div class="sql-block-header" onclick="toggleSqlCollapse(\'' + id + '\')">' +
                '<span class="sql-block-label">SQL</span>' +
                '<svg class="sql-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>' +
                '<div class="sql-block-actions" onclick="event.stopPropagation()">' +
                    '<button class="sql-btn sql-btn-run" title="Run this SQL again" onclick="rerunSqlBlock(\'' + id + '\')">' +
                        '<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>' +
                        ' 실행' +
                    '</button>' +
                    '<button class="sql-btn" title="Edit the SQL" onclick="toggleSqlEdit(\'' + id + '\')">' +
                        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>' +
                        ' 편집' +
                    '</button>' +
                    '<button class="sql-btn" title="Copy" onclick="copySqlBlock(\'' + id + '\', this)">' +
                        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
                    '</button>' +
                '</div>' +
            '</div>' +
            '<div class="sql-body">' +
                '<pre class="sql-code"><code>' + escaped + '</code></pre>' +
                '<div class="sql-editor-area hidden">' +
                    '<textarea class="sql-editor" spellcheck="false">' + escaped + '</textarea>' +
                    '<div class="sql-editor-actions">' +
                        '<button class="btn btn-sm btn-green" onclick="runSqlBlock(\'' + id + '\')">▶ 실행</button>' +
                        '<button class="btn btn-sm btn-outline" onclick="toggleSqlEdit(\'' + id + '\')">취소</button>' +
                        '<span class="sql-editor-hint">Ctrl/Cmd + Enter</span>' +
                    '</div>' +
                '</div>' +
                '<div class="sql-rerun-result hidden"></div>' +
            '</div>' +
        '</div>'
    );
}

function toggleSqlCollapse(id) {
    const block = document.getElementById(id);
    if (!block) return;
    block.classList.toggle("sql-collapsed");
}

function toggleSqlEdit(id) {
    const block = document.getElementById(id);
    if (!block) return;
    // Expanding edit mode also expands the block
    block.classList.remove("sql-collapsed");
    const editor = block.querySelector(".sql-editor-area");
    const code = block.querySelector(".sql-code");
    const hidden = editor.classList.contains("hidden");
    editor.classList.toggle("hidden", !hidden);
    code.classList.toggle("hidden", hidden);
    if (hidden) {
        // Opening the editor: focus and place caret at end
        const ta = editor.querySelector("textarea");
        if (ta) {
            ta.focus();
            ta.setSelectionRange(ta.value.length, ta.value.length);
        }
    }
}

function copySqlBlock(id, btn) {
    const block = document.getElementById(id);
    const sql = block.querySelector("code").textContent;
    navigator.clipboard.writeText(sql).then(() => {
        const orig = btn.innerHTML;
        btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>';
        setTimeout(() => { btn.innerHTML = orig; }, 1600);
    });
}

// Re-run the SQL *as currently displayed* (no editor interaction).
// Used by the "실행" button in the header row.
async function rerunSqlBlock(id) {
    const block = document.getElementById(id);
    if (!block) return;
    const code = block.querySelector("code");
    if (!code) return;
    // Ensure the block is expanded so the result is visible
    block.classList.remove("sql-collapsed");
    await _runSqlOnServer(block, code.textContent.trim());
}

async function runSqlBlock(id) {
    const block = document.getElementById(id);
    if (!block) return;
    // The textarea itself carries the .sql-editor class; not a child of it.
    const textarea = block.querySelector("textarea.sql-editor");
    if (!textarea) return;
    const sql = textarea.value.trim();
    if (!sql) return;
    // Replace the displayed SQL with the user-edited version so subsequent
    // reruns / edits start from the latest query.
    block.querySelector("code").textContent = sql;
    await _runSqlOnServer(block, sql);
}

// Core: POST /sql/execute and render the result into the block's result area.
async function _runSqlOnServer(block, sql) {
    if (!chatUploadId || !sql) return;
    const resultArea = block.querySelector(".sql-rerun-result");
    resultArea.classList.remove("hidden");
    resultArea.innerHTML = '<div class="chat-tool-indicator"><span class="chat-tool-spinner"></span> 실행 중...</div>';

    try {
        const res = await fetch("/sql/execute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ upload_id: chatUploadId, sql: sql })
        });
        const data = await res.json();
        if (!data.success) {
            resultArea.innerHTML = '<div class="chat-error">' + escapeHtml(data.error || "SQL error") + '</div>';
            return;
        }
        const header = data.truncated
            ? '전체 ' + data.total.toLocaleString() + ' rows 중 ' + data.rows + ' rows 표시'
            : data.rows + ' rows';
        resultArea.innerHTML =
            '<div class="sql-rerun-header">' + header + '</div>' +
            '<div class="chat-table-wrapper">' + data.html + '</div>';
    } catch (err) {
        resultArea.innerHTML = '<div class="chat-error">Connection error: ' + escapeHtml(err.message) + '</div>';
    }
}

// Ctrl/Cmd + Enter inside a SQL editor runs it
document.addEventListener("keydown", function (e) {
    if (!(e.ctrlKey || e.metaKey) || e.key !== "Enter") return;
    const active = document.activeElement;
    if (!active || active.tagName !== "TEXTAREA") return;
    if (!active.classList.contains("sql-editor")) return;
    e.preventDefault();
    const block = active.closest(".sql-block");
    if (block) runSqlBlock(block.id);
});

// ==================== Send message ====================

async function sendChatMessage() {
    if (chatStreaming || !chatUploadId) return;
    const message = chatInputEl.value.trim();
    if (!message) return;

    // Remove welcome on first real message
    const welcome = chatMessagesEl.querySelector(".qna-welcome");
    if (welcome) welcome.remove();

    appendBubble("user", escapeHtml(message));
    chatInputEl.value = "";
    chatInputEl.style.height = "auto";

    chatStreaming = true;
    chatSendBtnEl.disabled = true;
    chatInputEl.disabled = true;

    let assistantBubble = null;
    let currentIndicator = null;

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ upload_id: chatUploadId, message: message })
        });

        if (!res.ok) {
            appendBubble("assistant", '<span class="chat-error">Error: ' + res.status + '</span>');
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split("\n");
            buffer = lines.pop();

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed.startsWith("data: ")) continue;
                let event;
                try { event = JSON.parse(trimmed.slice(6)); } catch (e) { continue; }
                handleEvent(event);
            }
        }
    } catch (err) {
        appendBubble("assistant", '<span class="chat-error">Connection error: ' + escapeHtml(err.message) + '</span>');
    } finally {
        chatStreaming = false;
        chatSendBtnEl.disabled = false;
        chatInputEl.disabled = false;
        chatInputEl.focus();
    }

    function ensureAssistantBubble() {
        if (!assistantBubble) {
            assistantBubble = appendBubble("assistant", "");
            // Each assistant message is rendered in "segments":
            //   - "text" segments accumulate raw markdown (so cross-chunk ** pairs work)
            //   - "html" segments are prebuilt HTML (sql / table / chart / error)
            // We keep them in order and re-render the whole bubble on each event.
            assistantBubble._segments = [];
        }
        return assistantBubble;
    }

    function lastTextSegment() {
        const segs = assistantBubble._segments;
        const last = segs[segs.length - 1];
        if (last && last.kind === "text") return last;
        const seg = { kind: "text", raw: "" };
        segs.push(seg);
        return seg;
    }

    function rerenderBubble() {
        const segs = assistantBubble._segments;
        let html = "";
        for (const s of segs) {
            html += s.kind === "text" ? renderMarkdown(s.raw) : s.html;
        }
        assistantBubble.innerHTML = html;
    }

    function handleEvent(event) {
        switch (event.type) {
            case "text":
                removeToolIndicator(currentIndicator); currentIndicator = null;
                ensureAssistantBubble();
                lastTextSegment().raw += event.text;
                rerenderBubble();
                chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
                break;
            case "tool_call":
                removeToolIndicator(currentIndicator);
                currentIndicator = appendToolIndicator(event.tool);
                break;
            case "sql":
                removeToolIndicator(currentIndicator); currentIndicator = null;
                ensureAssistantBubble();
                assistantBubble._segments.push({ kind: "html", html: renderSqlBlock(event.sql) });
                rerenderBubble();
                chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
                break;
            case "table":
                removeToolIndicator(currentIndicator); currentIndicator = null;
                ensureAssistantBubble();
                assistantBubble._segments.push({ kind: "html", html: '<div class="chat-table-wrapper">' + event.html + '</div>' });
                rerenderBubble();
                chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
                break;
            case "chart":
                removeToolIndicator(currentIndicator); currentIndicator = null;
                ensureAssistantBubble();
                const imgSrc = "data:image/png;base64," + event.image;
                assistantBubble._segments.push({ kind: "html",
                    html: '<img class="chat-chart" src="' + imgSrc + '" alt="chart" title="클릭하면 확대" onclick="showChartModal(this.src)">' });
                rerenderBubble();
                chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
                break;
            case "error":
                removeToolIndicator(currentIndicator); currentIndicator = null;
                ensureAssistantBubble();
                assistantBubble._segments.push({ kind: "html", html: '<span class="chat-error">' + escapeHtml(event.text) + '</span>' });
                rerenderBubble();
                break;
            case "done":
                removeToolIndicator(currentIndicator); currentIndicator = null;
                if (assistantBubble) extractAndShowSuggestions(assistantBubble);
                assistantBubble = null;
                break;
        }
    }
}

// ==================== Reset ====================

function resetChat() {
    if (!chatUploadId) return;
    fetch("/chat/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: chatUploadId })
    }).catch(() => {});
    chatMessagesEl.innerHTML = "";
    chatWelcomeRendered = false;
    renderWelcome();
    chatWelcomeRendered = true;
}

// ==================== Chart modal ====================

function showChartModal(src) {
    const modal = document.getElementById("chart-modal");
    const img = document.getElementById("chart-modal-img");
    if (!modal || !img) return;
    img.src = src;
    modal.classList.add("active");
}

function closeChartModal() {
    const modal = document.getElementById("chart-modal");
    if (modal) modal.classList.remove("active");
}

// ==================== Utilities ====================

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
}

function renderMarkdown(text) {
    if (!text) return "";
    let html = escapeHtml(text);
    // **bold** — must run before single * to not be consumed by it
    html = html.replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>");
    // *italic*
    html = html.replace(/(^|[\s(])\*([^*\n]+?)\*(?=[\s.,;:)!?]|$)/g, "$1<em>$2</em>");
    // `inline code`
    html = html.replace(/`([^`]+?)`/g, "<code>$1</code>");
    html = html.replace(/\n/g, "<br>");
    return html;
}
