"""
Skill Loader - 스킬 호출 시 전체 내용을 로드 (Lazy Loading)

캐싱 없음: 매번 파일에서 읽어 항상 최신 내용 반영
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillNotFoundError(Exception):
    """요청한 스킬을 찾을 수 없을 때 발생하는 예외"""
    pass


class SkillLoader:
    """스킬 호출 시 전체 내용을 로드 (Lazy Loading, 캐싱 없음)"""

    def __init__(self, available_skills: dict[str, dict]):
        """
        Args:
            available_skills: SkillDiscovery에서 생성된 스킬 메타데이터 딕셔너리
                              {skill_name: {description, path, metadata}}
        """
        self.available_skills = available_skills

    def load(self, skill_name: str) -> str:
        """
        스킬의 전체 SKILL.md 내용 반환 (매번 파일에서 읽음)

        Args:
            skill_name: 로드할 스킬의 이름

        Returns:
            SKILL.md의 전체 내용

        Raises:
            SkillNotFoundError: 스킬을 찾을 수 없을 때
        """
        if skill_name not in self.available_skills:
            available = list(self.available_skills.keys())
            raise SkillNotFoundError(
                f"Skill '{skill_name}' not found. Available skills: {available}"
            )

        skill_path = self.available_skills[skill_name]['path']

        try:
            with open(skill_path, 'r', encoding='utf-8') as f:
                content = f.read()

            logger.info(f"Loaded skill '{skill_name}' from {skill_path} ({len(content)} chars)")
            return content

        except FileNotFoundError:
            raise SkillNotFoundError(
                f"Skill file not found: {skill_path}. "
                f"The skill may have been deleted after discovery."
            )
        except Exception as e:
            logger.error(f"Error loading skill '{skill_name}': {e}")
            raise

    def get_skill_description(self, skill_name: str) -> str:
        """스킬의 description만 반환 (전체 로드 없이)"""
        if skill_name not in self.available_skills:
            raise SkillNotFoundError(f"Skill '{skill_name}' not found")

        return self.available_skills[skill_name]['description']

    def skill_exists(self, skill_name: str) -> bool:
        """스킬 존재 여부 확인"""
        return skill_name in self.available_skills
