"""
Skill Discovery - 스킬 디렉토리를 스캔하여 메타데이터만 추출

시작 시 한 번만 실행하여 available_skills를 구성한다.
전체 스킬 내용은 로드하지 않고 name, description만 추출한다 (Lazy Loading 준비).
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class SkillDiscovery:
    """스킬 디렉토리를 스캔하여 메타데이터만 추출"""

    def __init__(self, skill_dirs: list[str]):
        """
        Args:
            skill_dirs: 스킬을 검색할 디렉토리 목록 (예: ["./skills"])
        """
        self.skill_dirs = skill_dirs
        self.available_skills: dict[str, dict] = {}

    def discover(self) -> dict[str, dict]:
        """
        모든 스킬 디렉토리를 스캔하여 메타데이터 수집

        Returns:
            {skill_name: {description, path}} 형태의 딕셔너리
        """
        self.available_skills = {}

        for skill_dir in self.skill_dirs:
            expanded_path = Path(skill_dir).expanduser().resolve()

            if not expanded_path.exists():
                logger.warning(f"Skill directory not found: {expanded_path}")
                continue

            self._scan_directory(expanded_path)

        logger.info(f"Discovered {len(self.available_skills)} skills: {list(self.available_skills.keys())}")
        return self.available_skills

    def _scan_directory(self, base_path: Path) -> None:
        """
        디렉토리를 재귀적으로 스캔하여 SKILL.md 파일 찾기

        중첩 디렉토리 지원 (예: document-skills/pdf/SKILL.md)
        """
        for skill_md_path in base_path.rglob("SKILL.md"):
            try:
                metadata = self._parse_frontmatter(skill_md_path)

                if metadata and 'name' in metadata and 'description' in metadata:
                    skill_name = metadata['name']

                    # 중복 스킬 경고
                    if skill_name in self.available_skills:
                        logger.warning(
                            f"Duplicate skill '{skill_name}' found. "
                            f"Keeping: {self.available_skills[skill_name]['path']}, "
                            f"Ignoring: {skill_md_path}"
                        )
                        continue

                    self.available_skills[skill_name] = {
                        'description': metadata['description'],
                        'path': str(skill_md_path),
                        'metadata': metadata  # 추가 메타데이터 (license, allowed-tools 등)
                    }

                    logger.debug(f"Discovered skill: {skill_name} at {skill_md_path}")
                else:
                    logger.warning(f"Invalid SKILL.md (missing name or description): {skill_md_path}")

            except Exception as e:
                logger.error(f"Error parsing {skill_md_path}: {e}")

    def _parse_frontmatter(self, skill_md_path: Path) -> Optional[dict]:
        """
        SKILL.md에서 YAML frontmatter 파싱

        SKILL.md 형식:
        ---
        name: skill-name
        description: What the skill does
        license: Optional license info
        allowed-tools: Optional list of tools
        ---
        # Markdown content...

        Returns:
            파싱된 YAML frontmatter 딕셔너리, 실패 시 None
        """
        try:
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # YAML frontmatter 추출 (--- 로 둘러싸인 부분)
            frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)

            if not frontmatter_match:
                logger.warning(f"No YAML frontmatter found in {skill_md_path}")
                return None

            frontmatter_text = frontmatter_match.group(1)
            metadata = yaml.safe_load(frontmatter_text)

            return metadata

        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {skill_md_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading {skill_md_path}: {e}")
            return None

    def get_skill_info(self, skill_name: str) -> Optional[dict]:
        """특정 스킬의 메타데이터 반환"""
        return self.available_skills.get(skill_name)

    def list_skills(self) -> list[str]:
        """발견된 모든 스킬 이름 목록 반환"""
        return list(self.available_skills.keys())
