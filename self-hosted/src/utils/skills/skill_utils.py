"""
Skill Utils - 스킬 시스템 초기화 및 설정 유틸리티

스킬 디스커버리, 로더, 툴 설정, 프롬프트 생성을 처리하는 유틸리티 함수 제공.
"""

import logging
from typing import Tuple

from .discovery import SkillDiscovery
from .loader import SkillLoader
from src.tools.skill_tool import setup_skill_tool

logger = logging.getLogger(__name__)


def get_skill_prompt(available_skills: dict[str, dict]) -> str:
    """
    Generate skill-related system prompt section to append to base prompts.

    Args:
        available_skills: Dictionary of skill metadata

    Returns:
        Formatted skill prompt section (Markdown + XML hybrid format)
    """
    skill_list = "\n".join([
        f"  - {name}: {info['description']}"
        for name, info in available_skills.items()
    ])

    return f"""
## Skill System
<skill_instructions>
You have access to specialized skills that provide detailed guidance for specific tasks.
Use skill_tool to load relevant skill instructions when working on specialized tasks.

How to use skills:
- Invoke skills using skill_tool with the skill name
- The skill's prompt will expand and provide detailed instructions
- Follow the loaded skill instructions precisely to complete the task

Important:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already loaded in the current conversation
- Skills provide code examples, best practices, and domain-specific guidance
</skill_instructions>

<available_skills>
{skill_list}
</available_skills>
"""


def initialize_skills(
    skill_dirs: list[str] = None,
    verbose: bool = False
) -> Tuple[dict, str]:
    """
    스킬 시스템 초기화 (디스커버리 + 로더 + 툴 설정)

    Args:
        skill_dirs: 스킬 디렉토리 경로 리스트 (기본값: ["./skills"])
        verbose: True면 초기화 과정 출력

    Returns:
        (available_skills, skill_prompt) 튜플
        - available_skills: 스킬 메타데이터 딕셔너리
        - skill_prompt: 시스템 프롬프트에 append할 스킬 프롬프트

    Example:
        >>> from src.utils.skills.skill_utils import initialize_skills
        >>> available_skills, skill_prompt = initialize_skills(["./skills"])
        >>> system_prompt = base_prompt + skill_prompt
    """
    if skill_dirs is None:
        skill_dirs = ["./skills"]

    # 1. 스킬 디스커버리
    if verbose:
        print("\n[Skill Init] Discovering skills...")

    discovery = SkillDiscovery(skill_dirs=skill_dirs)
    available_skills = discovery.discover()

    if not available_skills:
        logger.warning("No skills found in directories: %s", skill_dirs)
        if verbose:
            print("No skills found. Please check the skill directories.")
        return {}, ""

    if verbose:
        print(f"Discovered {len(available_skills)} skills:")
        for name, info in available_skills.items():
            desc = info['description'][:80] + "..." if len(info['description']) > 80 else info['description']
            print(f"  - {name}: {desc}")

    # 2. 스킬 로더 생성 + 툴 설정
    if verbose:
        print("\n[Skill Init] Setting up skill tool...")

    loader = SkillLoader(available_skills)
    setup_skill_tool(loader, available_skills)

    # 3. 스킬 프롬프트 생성
    skill_prompt = get_skill_prompt(available_skills)

    logger.info(f"Skill system initialized with {len(available_skills)} skills")

    return available_skills, skill_prompt
