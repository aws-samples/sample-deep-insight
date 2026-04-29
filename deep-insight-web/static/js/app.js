// ==================== State ====================
let currentUploadId = null;
let currentSessionId = null;
let currentRequestId = null;
let countdownTimer = null;
let analysisStartTime = null;
let elapsedTimer = null;
let firstOutputReceived = false;

// ==================== DOM References ====================
let uploadForm, uploadBtn, statusDiv, analyzeSection, analyzeBtn, queryInput;
let outputSection, outputDiv, downloadSection, downloadList;
let planModal, planText, modalRevision, modalMax, modalCountdown;
let feedbackInput, approveBtn, rejectBtn;

function initDOMRefs() {
    uploadForm = document.getElementById("upload-form");
    uploadBtn = document.getElementById("upload-btn");
    statusDiv = document.getElementById("status");
    analyzeSection = document.getElementById("analyze-section");
    analyzeBtn = document.getElementById("analyze-btn");
    queryInput = document.getElementById("query");
    outputSection = document.getElementById("output-section");
    outputDiv = document.getElementById("output");
    downloadSection = document.getElementById("download-section");
    downloadList = document.getElementById("download-list");
    planModal = document.getElementById("plan-modal");
    planText = document.getElementById("plan-text");
    modalRevision = document.getElementById("modal-revision");
    modalMax = document.getElementById("modal-max");
    modalCountdown = document.getElementById("modal-countdown");
    feedbackInput = document.getElementById("feedback-input");
    approveBtn = document.getElementById("approve-btn");
    rejectBtn = document.getElementById("reject-btn");
}

// ==================== View tabs ====================
// Active view name: 'analysis' (default) or 'chat'. Switched via activateView().
let activeView = "analysis";

function activateView(name) {
    const tabAnalysis = document.getElementById("tab-analysis");
    const tabChat = document.getElementById("tab-chat");
    const viewAnalysis = document.getElementById("view-analysis");
    const viewChat = document.getElementById("view-chat");

    // Q&A tab is disabled until upload completes
    if (name === "chat" && tabChat.disabled) return;

    activeView = name;
    tabAnalysis.classList.toggle("active", name === "analysis");
    tabAnalysis.setAttribute("aria-selected", name === "analysis");
    tabChat.classList.toggle("active", name === "chat");
    tabChat.setAttribute("aria-selected", name === "chat");
    viewAnalysis.classList.toggle("view-active", name === "analysis");
    viewChat.classList.toggle("view-active", name === "chat");

    if (name === "chat") {
        // Lazy render Q&A welcome on first open
        if (typeof initChatWelcomeIfNeeded === "function") initChatWelcomeIfNeeded();
    }
}

function enableChatTab(uploadId) {
    const tabChat = document.getElementById("tab-chat");
    tabChat.disabled = false;
    tabChat.classList.remove("disabled");
    if (typeof setChatUploadId === "function") setChatUploadId(uploadId);
}

// ==================== Init ====================
document.addEventListener("DOMContentLoaded", () => {
    initDOMRefs();
    applyLanguage();
    loadSampleData();
    loadSampleReports();
    initUpload();
    initAnalyze();
    initPlanModal();
    initChat();
});
