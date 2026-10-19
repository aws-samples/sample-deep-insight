import os
import re
from datetime import datetime


def filter_plan_for_agent(full_plan: str, agent_name: str) -> str:
    """Filter FULL_PLAN to only include steps assigned to the given agent.

    Prevents agents from seeing other agents' task instructions (e.g., Coder
    seeing Reporter's "create DOCX" task), which causes prompt violations.
    See: docs/incidents/2026-03-17-reporter-stream-timeout/incident.md
    """
    if not full_plan or not full_plan.strip():
        return full_plan

    agent_lower = agent_name.lower()
    sections = re.split(r'(?=^### \d+\.)', full_plan, flags=re.MULTILINE)

    result_parts = []
    for section in sections:
        header_match = re.match(r'^### \d+\.\s*(\w+)', section)
        if header_match:
            section_agent = header_match.group(1).lower()
            if section_agent == agent_lower:
                result_parts.append(section)
            else:
                header_line = section.split('\n')[0]
                result_parts.append(header_line + '\n(handled by ' + header_match.group(1) + ' agent)\n')
        else:
            result_parts.append(section)

    return '\n'.join(result_parts)


def detect_output_language(user_request: str) -> str:
    """Language every agent writes in, decided once from the user's request.

    Left to each agent ("same language as USER_REQUEST"), an English request
    still got Korean reports: the prompts' examples are Korean, and once one
    agent's files (all_results.txt, calculation descriptions) were Korean the
    next agent followed them. Only the text inside <user_request> counts, and
    file and column names (a `.`, `_` or `-` inside) and abbreviations (CTR,
    ROAS) are left out, so a Korean request naming English files and columns
    stays Korean: Korean when Hangul is at least 30% of the remaining letters.
    """
    m = re.search(r"<user_request>(.*?)</user_request>", user_request or "", re.S)
    text = m.group(1) if m else (user_request or "")
    text = re.sub(r"[\w./-]*[._/-][\w./-]*|\b[A-Z]{2,}\b", " ", text)
    hangul = len(re.findall(r"[\uac00-\ud7a3]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if hangul and hangul >= 0.3 * (hangul + latin):
        return "Korean"
    if latin:
        return "English"
    return "the language of USER_REQUEST"


def apply_prompt_template(prompt_name: str, prompt_context={}) -> str:
    
    system_prompts = open(os.path.join(os.path.dirname(__file__), f"{prompt_name}.md")).read() ## Template.py가 있는 dir이 기준
    context = {"CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z")}
    context["OUTPUT_LANGUAGE"] = detect_output_language(prompt_context.get("USER_REQUEST", ""))
    context.update(prompt_context)
    system_prompts = system_prompts.format(**context)
        
    return system_prompts