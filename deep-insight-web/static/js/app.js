// ==================== State ====================
var currentUploadId = null;
var currentSessionId = null;
var currentRequestId = null;
var countdownTimer = null;
var analysisStartTime = null;
var elapsedTimer = null;
var firstOutputReceived = false;
var sseCompleted = false;
var analysisInProgress = false;  // For concurrent request prevention

// ==================== DOM References ====================
var uploadForm, uploadBtn, statusDiv, analyzeSection, analyzeBtn, queryInput;
var outputSection, outputDiv, downloadSection, downloadList;
var planModal, planText, modalRevision, modalMax, modalCountdown;
var feedbackInput, approveBtn, rejectBtn;

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

// ==================== Init ====================
document.addEventListener("DOMContentLoaded", () => {
    initDOMRefs();
    applyLanguage();
    loadSampleData();
    loadSampleReports();
    initUpload();
    initAnalyze();
    initPlanModal();
});
