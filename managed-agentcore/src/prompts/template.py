import os
import re
from datetime import datetime


def filter_plan_for_agent(full_plan: str, agent_name: str) -> str:
    """Filter FULL_PLAN to only include steps assigned to the given agent.

    Prevents agents from seeing other agents' task instructions (e.g., Coder
    seeing Reporter's "create DOCX" task), which causes prompt violations.
    See: docs/incidents/2026-03-17-reporter-stream-timeout-incomplete-read.md
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


def apply_prompt_template(prompt_name: str, prompt_context={}) -> str:
    
    system_prompts = open(os.path.join(os.path.dirname(__file__), f"{prompt_name}.md")).read() ## Template.py가 있는 dir이 기준
    context = {"CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z")}
    context.update(prompt_context)
    system_prompts = system_prompts.format(**context)
        
    return system_prompts