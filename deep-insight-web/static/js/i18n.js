// ==================== i18n ====================
const translations = {
    ko: {
        hero_tagline_prefix: "리포팅 등의 다양한 에이전트 응용 개발 위한 ",
        hero_tagline_highlight: "커스텀 에이전트 구축 플랫폼",
        hero_subtitle: "Built on Strands Agent & Amazon Bedrock AgentCore",
        guide_title: "사용 가이드",
        hero_learn: "안전한 오픈소스 아키텍처와 코드를 통해 나만의 에이전트를 구축하세요",
        guide_browser_hint: "Chrome 브라우저 사용을 권장합니다",
        guide_security_note: "업로드된 데이터와 생성된 보고서는 고객의 S3 버킷에 저장되며, 프론트엔드는 사내 IP 대역으로 제한되고 백엔드는 프라이빗 VPC에서 운영됩니다. 데이터는 안전하게 관리됩니다.",
        guide_lang_hint: "우측 상단의 EN/KR 버튼으로 언어를 전환할 수 있습니다. 모든 텍스트, 샘플 데이터, 샘플 보고서가 선택한 언어로 변경됩니다.",
        guide_step1: "데이터 파일(CSV, Excel 등)과 컬럼 정의 파일을 업로드합니다",
        guide_step2: "분석 프롬프트를 입력합니다",
        guide_step3: "분석 계획이 표시되면 승인하거나 수정을 요청합니다",
        guide_step4: "에이전트가 분석을 완료할 때까지 기다립니다",
        guide_step5: "Reports 섹션에서 생성된 보고서를 다운로드합니다",
        guide_coldef_tip: "컬럼 정의 파일은 선택사항이지만 권장합니다. 컬럼명이 도메인 고유 의미를 가질 수 있으며(예: 매출 = 순매출 vs 총매출), 분석에 적용할 수식도 정의할 수 있습니다.",
        guide_time_note: "소요 시간은 프롬프트 복잡도, 데이터 크기, LLM 서버 상태에 따라 달라집니다. 샘플 데이터 기준 약 15~30분 소요될 수 있습니다.",
        prompt_examples_label: "예시를 클릭하면 자동 입력됩니다",
        prompt_tag_simple: "간단",
        prompt_tag_detailed: "상세",
        prompt_simple_1: "데이터의 핵심 지표를 요약해줘",
        prompt_simple_2: "총 매출액을 계산해줘",
        prompt_detailed_1: "데이터에서 비즈니스 성장 기회를 발굴해줘: 숨겨진 고객 패턴과 세그먼트를 발견하고, 수익 최적화 방안을 제시하며, 마케팅과 운영 효율성을 높일 수 있는 개선점을 찾고, 다음 달 매출을 크게 늘릴 수 있는 실행 가능한 전략 3가지를 우선순위와 기대 효과를 포함해서 제안해줘",
        sample_title: "샘플 데이터",
        sample_hint: "데이터가 없거나 테스트 실행을 원하면 아래 샘플 CSV 파일과 컬럼 정의 JSON 파일을 다운로드한 후 업로드하세요",
        sample_loading: "로딩 중...",
        sample_none: "사용 가능한 샘플 데이터가 없습니다",
        sample_reports_title: "샘플 보고서",
        sample_reports_hint: "위 샘플 데이터로 생성된 보고서 예시입니다. 분석 결과물이 어떤 형태인지 미리 확인해보세요.",
        sample_reports_chrome: "Chrome에서 다운로드 시 우측 상단에 보안 경고가 표시되면 \"Keep\" 버튼을 클릭하세요 (HTTP 연결)",
        sample_reports_none: "사용 가능한 샘플 보고서가 없습니다",
        learn_title: "직접 만들어보기",
        learn_desc: "Deep Insight는 안전한 오픈소스 플랫폼입니다. 멀티 에이전트 시스템의 아키텍처를 이해하고 직접 구축하는 방법을 핸즈온 워크숍과 소스 코드를 통해 배워보세요.",
        learn_workshop: "🎓 핸즈온 워크숍",
        learn_github: "💻 소스 코드 (GitHub)",
        upload_title: "데이터 업로드",
        upload_data_label: "데이터 파일",
        upload_data_hint: "CSV, Excel, TSV, TXT, JSON",
        upload_coldef_label: "컬럼 정의",
        upload_coldef_tag: "권장",
        upload_coldef_hint: "컬럼의 도메인 고유 의미와 수식을 정의하는 JSON 파일",
        drop_text_coldef: "JSON 파일을 여기에 끌어다 놓거나 ",
        section_start: "시작하기",
        upload_btn: "업로드",
        drop_text: "파일을 여기에 끌어다 놓거나 ",
        drop_browse: "클릭하여 선택",
        file_selected: "선택됨: ",
        analyze_title: "분석",
        analyze_query_label: "프롬프트",
        analyze_placeholder: "예: 매출 트렌드를 분석하고 보고서를 만들어주세요",
        analyze_btn: "🔍 분석 시작",
        output_title: "분석 진행",
        output_note: "스트리밍 출력은 5분 이상 소요될 수 있습니다. <strong>Tool calling → Coder</strong> 표시 후 다음 스트리밍까지 <strong>약 2분 이내</strong> 걸립니다.",
        output_waiting: "분석 중... 스트림이 연결되면 출력이 표시됩니다. 데이터 크기와 프롬프트에 따라 약 15분 정도 소요될 수 있습니다.",
        reports_title: "보고서",
        reports_note: "Chrome 브라우저에서 다운로드 시 보안 경고가 표시되면 우측 상단의 \"Keep\" 버튼을 클릭하세요 (HTTP 연결)",
        modal_title: "분석 계획 검토",
        modal_guide_desc: "아래 분석 계획을 검토한 후 승인 또는 수정 요청을 선택하세요.",
        modal_guide_approve: "✓ 승인",
        modal_guide_approve_desc: "이 계획대로 분석을 시작합니다",
        modal_guide_revise: "✎ 수정 요청",
        modal_guide_revise_desc: "피드백을 입력하면 계획이 수정됩니다 (최대 10회)",
        modal_guide_examples: "예: \"주간 매출 추이를 추가해줘\", \"매출 건수 차트는 삭제해줘\", \"시계열 차트를 추가해줘\"",
        modal_revision: "수정 횟수",
        modal_timeout: "남은 시간",
        modal_zone_approve: "이 계획대로 진행",
        modal_zone_revise: "수정 요청",
        modal_feedback_placeholder: "수정할 내용을 입력하세요...",
        modal_approve: "승인",
        modal_revise_btn: "수정 요청",
        report_group_documents: "문서",
        report_group_text: "텍스트",
        report_group_images: "이미지",
        status_uploading: "업로드 중...",
        status_upload_complete: "✓ 업로드 완료. Upload ID: ",
        status_upload_failed: "업로드 실패: ",
        coldef_or: "또는",
        coldef_autogen_btn: "🤖 컬럼 정의 자동 생성",
        coldef_autogen_desc: "업로드한 데이터 파일을 기반으로 AI가 컬럼 정의를 자동 생성합니다",
        coldef_generating: "⏳ 생성 중...",
        coldef_generating_hint: "AI가 컬럼 정의를 분석하고 있습니다...",
        coldef_gen_failed: "생성 실패: ",
        coldef_review_title: "생성된 컬럼 정의",
        coldef_regen_btn: "🔄 재생성",
        coldef_edit_btn: "✏️ 직접 수정",
        coldef_preview_btn: "👁 미리보기",
        coldef_confirm_btn: "✓ 이 정의 사용",
        coldef_cancel_btn: "취소",
        coldef_auto_generated: "자동 생성됨: column_definitions.json",
        coldef_view_table: "📊 테이블",
        coldef_view_json: "{ } JSON",
        coldef_table_col_name: "컬럼명",
        coldef_table_col_desc: "설명",
    },
    en: {
        hero_tagline_prefix: "A platform for building diverse agent applications including reporting — ",
        hero_tagline_highlight: "Custom Agent Builder",
        hero_subtitle: "Built on Strands Agent & Amazon Bedrock AgentCore",
        guide_title: "QUICK START GUIDE",
        hero_learn: "Build your own agent with our secure, open-source architecture and code",
        guide_browser_hint: "Chrome browser is recommended",
        guide_security_note: "Uploaded data and generated reports are stored in your S3 bucket. The frontend is restricted to internal company IP ranges, and the backend runs in a private VPC. Your data is securely managed.",
        guide_lang_hint: "Use the EN/KR button in the top-right corner to switch languages. All text, sample data, and sample reports will change to the selected language.",
        guide_step1: "Upload your data file (CSV, Excel, etc.) and column definitions",
        guide_step2: "Enter an analysis prompt describing what you want to analyze",
        guide_step3: "Review the analysis plan when prompted and approve or request changes",
        guide_step4: "Wait for the agents to complete the analysis",
        guide_step5: "Download the generated reports from the Reports section",
        guide_coldef_tip: "Column definitions are optional but recommended. Column names may have domain-specific meanings (e.g., sales = net vs gross), and you can define formulas to apply during analysis.",
        guide_time_note: "Elapsed time varies by prompt complexity, data size, and LLM server load. For sample data, it may take approximately 15-30 minutes.",
        prompt_examples_label: "Click an example to auto-fill",
        prompt_tag_simple: "Simple",
        prompt_tag_detailed: "Detailed",
        prompt_simple_1: "Summarize key metrics from the data",
        prompt_simple_2: "Calculate total sales",
        prompt_detailed_1: "Discover business growth opportunities from the data: find hidden customer patterns and segments, suggest revenue optimization strategies, identify improvements for marketing and operational efficiency, and propose 3 actionable strategies to significantly increase next month's sales with priorities and expected impact",
        sample_title: "SAMPLE DATA",
        sample_hint: "If you don't have data prepared or want to try a test run, download the sample CSV and column definition JSON files below, then upload them",
        sample_loading: "Loading...",
        sample_none: "No sample data available",
        sample_reports_title: "SAMPLE REPORTS",
        sample_reports_hint: "Example reports generated from the sample data above. Preview what analysis results look like.",
        sample_reports_chrome: "In Chrome, if a security warning appears in the upper-right corner when downloading, click the \"Keep\" button (HTTP connection)",
        sample_reports_none: "No sample reports available",
        learn_title: "LEARN TO BUILD",
        learn_desc: "Deep Insight is a secure, open-source platform. Learn how to build your own multi-agent system through the hands-on workshop and source code.",
        learn_workshop: "🎓 Hands-on Workshop",
        learn_github: "💻 Source Code (GitHub)",
        upload_title: "UPLOAD DATA",
        upload_data_label: "Data file",
        upload_data_hint: "CSV, Excel, TSV, TXT, or JSON",
        upload_coldef_label: "Column Definitions",
        upload_coldef_tag: "Recommended",
        upload_coldef_hint: "JSON file defining domain-specific column meanings and formulas",
        drop_text_coldef: "Drop your JSON file here or ",
        section_start: "Get Started",
        upload_btn: "Upload",
        drop_text: "Drag & drop your file here or ",
        drop_browse: "click to browse",
        file_selected: "Selected: ",
        analyze_title: "ANALYZE",
        analyze_query_label: "Prompt",
        analyze_placeholder: "e.g. Analyze sales trends and generate a report",
        analyze_btn: "🔍 Analyze",
        output_title: "ANALYSIS PROGRESS",
        output_note: "Streaming output may take more than 5 minutes. After <strong>Tool calling → Coder</strong> appears, the next streaming output takes <strong>under 2 minutes</strong>.",
        output_waiting: "Analyzing... Output will appear once the stream is available. This may take about 15 minutes depending on data size and prompt complexity.",
        reports_title: "REPORTS",
        reports_note: "In Chrome, if a security warning appears when downloading, click the \"Keep\" button in the upper-right corner (HTTP connection)",
        modal_title: "Plan Review",
        modal_guide_desc: "Review the analysis plan below, then choose to approve or request revisions.",
        modal_guide_approve: "✓ Approve",
        modal_guide_approve_desc: "Start analysis with this plan",
        modal_guide_revise: "✎ Request Revision",
        modal_guide_revise_desc: "Enter feedback to revise the plan (up to 10 times)",
        modal_guide_examples: "e.g. \"Add weekly sales trend\", \"Remove sales count chart\", \"Add time-series chart\"",
        modal_revision: "Revisions",
        modal_timeout: "Time left",
        modal_zone_approve: "Proceed with this plan",
        modal_zone_revise: "Request Revision",
        modal_feedback_placeholder: "Enter what you'd like to change...",
        modal_approve: "Approve",
        modal_revise_btn: "Request Revision",
        report_group_documents: "Documents",
        report_group_text: "Text",
        report_group_images: "Images",
        status_uploading: "Uploading...",
        status_upload_complete: "✓ Upload complete. Upload ID: ",
        status_upload_failed: "Upload failed: ",
        coldef_or: "or",
        coldef_autogen_btn: "🤖 Auto-generate Column Definitions",
        coldef_autogen_desc: "AI generates column definitions based on your uploaded data file",
        coldef_generating: "⏳ Generating...",
        coldef_generating_hint: "AI is analyzing your columns...",
        coldef_gen_failed: "Generation failed: ",
        coldef_review_title: "Generated Column Definitions",
        coldef_regen_btn: "🔄 Regenerate",
        coldef_edit_btn: "✏️ Edit",
        coldef_preview_btn: "👁 Preview",
        coldef_confirm_btn: "✓ Use These Definitions",
        coldef_cancel_btn: "Cancel",
        coldef_auto_generated: "Auto-generated: column_definitions.json",
        coldef_view_table: "📊 Table",
        coldef_view_json: "{ } JSON",
        coldef_table_col_name: "Column",
        coldef_table_col_desc: "Description",
    }
};

let currentLang = "ko";

function toggleLanguage() {
    currentLang = currentLang === "ko" ? "en" : "ko";
    applyLanguage();
}

function applyLanguage() {
    const t = translations[currentLang];
    document.getElementById("lang-toggle").textContent = currentLang === "ko" ? "EN" : "KR";
    const workshopUrl = currentLang === "ko"
        ? "https://catalog.us-east-1.prod.workshops.aws/workshops/ee17ba6e-edc4-4921-aaf6-ca472841c49b/ko-KR"
        : "https://catalog.us-east-1.prod.workshops.aws/workshops/ee17ba6e-edc4-4921-aaf6-ca472841c49b/en-US";
    ["workshop-link", "hero-workshop-link", "learn-workshop-link"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.href = workshopUrl;
    });
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const key = el.getAttribute("data-i18n");
        if (t[key] !== undefined) el.textContent = t[key];
    });
    document.querySelectorAll("[data-i18n-html]").forEach(el => {
        const key = el.getAttribute("data-i18n-html");
        if (t[key] !== undefined) el.innerHTML = t[key];
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
        const key = el.getAttribute("data-i18n-placeholder");
        if (t[key] !== undefined) el.placeholder = t[key];
    });
    renderPromptExamples();
    renderSampleDataLinks();
    renderSampleReportsLinks();
    if (typeof refreshSelectedFileDisplays === "function") {
        refreshSelectedFileDisplays();
    }
}

// ==================== Guide ====================
let guideExpanded = true;
function toggleGuide() {
    guideExpanded = !guideExpanded;
    document.getElementById("guide-body").classList.toggle("hidden", !guideExpanded);
    document.getElementById("guide-arrow").classList.toggle("collapsed", !guideExpanded);
}

// ==================== Prompt Examples ====================
function renderPromptExamples() {
    const container = document.getElementById("prompt-examples");
    const t = translations[currentLang];
    const examples = [
        { tag: t.prompt_tag_simple, tagClass: "tag-simple", text: t.prompt_simple_1 },
        { tag: t.prompt_tag_simple, tagClass: "tag-simple", text: t.prompt_simple_2 },
        { tag: t.prompt_tag_detailed, tagClass: "tag-detailed", text: t.prompt_detailed_1 },
    ];
    container.innerHTML = "";
    for (const ex of examples) {
        const div = document.createElement("div");
        div.className = "prompt-chip";
        div.innerHTML = `<span class="prompt-tag ${ex.tagClass}">${ex.tag}</span>${ex.text}`;
        div.addEventListener("click", () => {
            const q = document.getElementById("query");
            if (q) { q.value = ex.text; q.focus(); }
        });
        container.appendChild(div);
    }
}
