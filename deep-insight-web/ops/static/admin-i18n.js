// ==================== Admin i18n ====================
const adminI18n = {
    en: {
        // Shared header
        admin_title: 'Deep Insight Admin',
        admin_badge: 'Admin',
        admin_webui: 'Web UI',
        admin_logout: 'Logout',
        admin_refresh: 'Auto-refresh: 30s',

        // Login
        login_title: 'Deep Insight Admin',
        login_subtitle: 'Sign in to the admin console',
        login_email: 'Email',
        login_email_ph: 'admin@example.com',
        login_password: 'Password',
        login_password_ph: 'Enter password',
        login_btn: 'Sign In',
        login_btn_loading: 'Signing in...',
        login_back: 'Back to Deep Insight',
        login_err_empty: 'Please enter email and password',
        login_hint_title: 'First time signing in?',
        login_hint_body: 'Use the temporary password from your Cognito welcome email.',
        login_err_connection: 'Connection error',
        login_err_failed: 'Login failed',

        // Change password
        change_title: 'Set New Password',
        change_subtitle: 'Your temporary password must be changed on first login',
        change_new: 'New Password',
        change_new_ph: 'Enter new password',
        change_hint: 'Min 12 characters, uppercase, lowercase, number, symbol',
        change_confirm: 'Confirm Password',
        change_confirm_ph: 'Confirm new password',
        change_btn: 'Set Password',
        change_btn_loading: 'Setting password...',
        change_err_empty: 'Please enter a new password',
        change_err_mismatch: 'Passwords do not match',
        change_err_connection: 'Connection error',
        change_err_failed: 'Password change failed',

        // Jobs list
        filter_all: 'All',
        filter_start: 'Start',
        filter_success: 'Success',
        filter_failed: 'Failed',
        th_timestamp: 'Timestamp',
        th_input: 'Input',
        th_output: 'Output',
        th_latency: 'Latency',
        drawer_close: 'Close (Esc)',
        tv_trace: 'Trace',
        tv_turn_final: 'wrap-up',
        wf_time: 'Time',
        wf_tool: 'Tool',
        wf_result: 'Result',
        wf_kind: 'Kind',
        wf_name: 'Name',
        wf_status: 'Status',
        wf_all: 'All',
        wf_failed_only: 'Failed only',
        wf_pick_row: 'Select a row to see its input and output.',
        tv_failed: 'failed',
        drawer_tab_trace: 'Trace',
        drawer_tab_files: 'Files',
        tv_name: 'Name',
        tv_timeline: 'Timeline',
        tv_latency: 'Latency',
        tv_tokens: 'Tokens',
        tv_model: 'Model',
        tv_started: 'Started',
        tv_error: 'Error',
        tv_input: 'Input',
        tv_output: 'Output',
        tv_process: 'Process',
        tv_metadata: 'Metadata',
        tv_input_not_recorded: 'Not recorded (trace from before agent inputs were captured)',
        th_status: 'Status',
        th_tokens: 'Tokens',
        status_start: 'Start',
        status_success: 'Success',
        status_failed: 'Failed',
        jobs_empty: 'No jobs found',
        jobs_running: 'running...',
        jobs_stale: 'STALE',

        // Side panel: trace and files
        trace_loading: 'Loading trace...',
        trace_unavailable: 'No trace yet. A running job shows its trace once its first agent finishes; jobs that ran before trace recording have none.',
        trace_load_error: 'Failed to load trace',
        trace_text: 'Response',
        trace_reasoning: 'Reasoning',
        trace_tool_call: 'Tool call',
        trace_tool_result: 'Tool result',
        trace_plan: 'Plan shown for review',
        trace_running: 'Running',
        trace_plan_feedback: 'Plan review result',
        trace_expand_all: 'Expand all',
        trace_collapse_all: 'Collapse all',
        hitl_title: 'Human review (HITL)',
        hitl_feedback: 'User feedback',
        hitl_no_feedback: 'No feedback text',
        hitl_waited: 'Waited',
        hitl_approved: 'Approved',
        hitl_revision_requested: 'Revision requested',
        hitl_auto_approved_timeout: 'Auto-approved (timeout)',
        hitl_auto_approved_max_revisions: 'Auto-approved (max revisions)',
        files_loading: 'Loading files...',
        files_images: 'Generated images',
        files_input: 'Input data',
        files_none: 'None',
        files_download_report: 'Download report',
        files_load_error: 'Failed to load files',
        files_results: 'Result files',
        files_all: 'All generated files',
        files_report_badge: 'Report',
    },
    ko: {
        // Shared header
        admin_title: 'Deep Insight 관리자',
        admin_badge: '관리자',
        admin_webui: '웹 UI',
        admin_logout: '로그아웃',
        admin_refresh: '자동 갱신: 30초',

        // Login
        login_title: 'Deep Insight 관리자',
        login_subtitle: '관리자 콘솔에 로그인하세요',
        login_email: '이메일',
        login_email_ph: 'admin@example.com',
        login_password: '비밀번호',
        login_password_ph: '비밀번호를 입력하세요',
        login_btn: '로그인',
        login_btn_loading: '로그인 중...',
        login_back: 'Deep Insight로 돌아가기',
        login_err_empty: '이메일과 비밀번호를 입력하세요',
        login_hint_title: '처음 로그인하시나요?',
        login_hint_body: 'Cognito 환영 이메일의 임시 비밀번호를 사용하세요.',
        login_err_connection: '연결 오류',
        login_err_failed: '로그인 실패',

        // Change password
        change_title: '새 비밀번호 설정',
        change_subtitle: '첫 로그인 시 임시 비밀번호를 변경해야 합니다',
        change_new: '새 비밀번호',
        change_new_ph: '새 비밀번호를 입력하세요',
        change_hint: '최소 12자, 대문자, 소문자, 숫자, 특수문자 포함',
        change_confirm: '비밀번호 확인',
        change_confirm_ph: '새 비밀번호를 다시 입력하세요',
        change_btn: '비밀번호 설정',
        change_btn_loading: '비밀번호 설정 중...',
        change_err_empty: '새 비밀번호를 입력하세요',
        change_err_mismatch: '비밀번호가 일치하지 않습니다',
        change_err_connection: '연결 오류',
        change_err_failed: '비밀번호 변경 실패',

        // Jobs list
        filter_all: '전체',
        filter_start: '시작',
        filter_success: '성공',
        filter_failed: '실패',
        th_timestamp: '시각',
        th_input: '입력',
        th_output: '출력',
        th_latency: '소요 시간',
        drawer_close: '닫기 (Esc)',
        tv_trace: 'Trace',
        tv_turn_final: '마무리',
        wf_time: '시간',
        wf_tool: '도구',
        wf_result: '결과',
        wf_kind: '종류',
        wf_name: '이름',
        wf_status: '상태',
        wf_all: '전체',
        wf_failed_only: '실패만',
        wf_pick_row: '행을 선택하면 입력과 출력을 볼 수 있습니다.',
        tv_failed: '실패',
        drawer_tab_trace: '실행 기록',
        drawer_tab_files: '파일',
        tv_name: '이름',
        tv_timeline: '타임라인',
        tv_latency: '소요 시간',
        tv_tokens: '토큰',
        tv_model: '모델',
        tv_started: '시작',
        tv_error: '오류',
        tv_input: '입력',
        tv_output: '출력',
        tv_process: '진행 과정',
        tv_metadata: '메타데이터',
        tv_input_not_recorded: '기록되지 않음 (에이전트 입력을 저장하기 전의 trace)',
        th_status: '상태',
        th_tokens: '토큰',
        status_start: '시작',
        status_success: '성공',
        status_failed: '실패',
        jobs_empty: '조회된 작업이 없습니다',
        jobs_running: '실행 중...',
        jobs_stale: '지연',

        // Side panel: trace and files
        trace_loading: '실행 기록을 불러오는 중...',
        trace_unavailable: '아직 실행 기록이 없습니다. 실행 중인 작업은 첫 에이전트가 끝나면 표시되고, 기록 저장 이전에 실행된 작업은 기록이 없습니다.',
        trace_load_error: '실행 기록을 불러오지 못했습니다',
        trace_text: '응답',
        trace_reasoning: '추론',
        trace_tool_call: '도구 호출',
        trace_tool_result: '도구 결과',
        trace_plan: '검토 요청된 계획',
        trace_running: '실행 중',
        trace_plan_feedback: '계획 검토 결과',
        trace_expand_all: '모두 펼치기',
        trace_collapse_all: '모두 접기',
        hitl_title: '사람 검토 (HITL)',
        hitl_feedback: '사용자 피드백',
        hitl_no_feedback: '피드백 내용 없음',
        hitl_waited: '대기 시간',
        hitl_approved: '승인',
        hitl_revision_requested: '수정 요청',
        hitl_auto_approved_timeout: '자동 승인 (시간 초과)',
        hitl_auto_approved_max_revisions: '자동 승인 (최대 수정 횟수)',
        files_loading: '파일을 불러오는 중...',
        files_images: '생성된 이미지',
        files_input: '입력 데이터',
        files_none: '없음',
        files_download_report: '보고서 다운로드',
        files_load_error: '파일을 불러오지 못했습니다',
        files_results: '결과 파일',
        files_all: '생성된 전체 파일',
        files_report_badge: '보고서',
    }
};

let adminLang = localStorage.getItem('adminLang') || 'ko';

/** Get translated string by key */
function t(key) {
    return adminI18n[adminLang][key] || adminI18n['en'][key] || key;
}

/** Toggle between Korean and English */
function toggleAdminLang() {
    adminLang = adminLang === 'ko' ? 'en' : 'ko';
    localStorage.setItem('adminLang', adminLang);
    applyAdminLang();
}

/** Apply current language to all data-i18n elements */
function applyAdminLang() {
    var btn = document.getElementById('admin-lang-toggle');
    if (btn) btn.textContent = adminLang === 'ko' ? 'EN' : 'KR';

    document.querySelectorAll('[data-i18n]').forEach(function(el) {
        var key = el.getAttribute('data-i18n');
        var val = adminI18n[adminLang][key];
        if (val !== undefined) el.textContent = val;
    });

    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
        var key = el.getAttribute('data-i18n-placeholder');
        var val = adminI18n[adminLang][key];
        if (val !== undefined) el.placeholder = val;
    });

    // Call page-specific re-render if defined
    if (typeof onLangChange === 'function') onLangChange();
}
