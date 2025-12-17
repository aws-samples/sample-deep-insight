"""
Skill Tool - Strands Agent SDK용 스킬 도구

에이전트가 스킬을 호출할 수 있도록 하는 tool 정의.
순수하게 툴 정의만 포함. 설정 및 프롬프트 생성은 skill_utils.py 참조.
"""

import logging
from typing import Any, Annotated

from strands.types.tools import ToolResult, ToolUse

from src.utils.skills.loader import SkillLoader, SkillNotFoundError

logger = logging.getLogger(__name__)

# Global reference to loader (set by skill_utils.setup_skill_tool)
_loader: SkillLoader | None = None

TOOL_SPEC = {
    "name": "skill_tool",
    "description": (
        "Load specialized skill instructions for specific tasks. "
        "Use this when you need detailed guidance on a particular topic."
    ),
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to invoke (e.g., 'pdf', 'docx', 'xlsx')"
                }
            },
            "required": ["skill_name"]
        }
    }
}


def setup_skill_tool(loader: SkillLoader, available_skills: dict[str, dict]):
    """
    Initialize the skill tool with loader and available skills.
    Updates TOOL_SPEC with available skill list.

    Args:
        loader: SkillLoader instance
        available_skills: Dictionary of skill metadata
    """
    global _loader
    _loader = loader

    # Update TOOL_SPEC description with available skills
    skill_list = "\n".join([
        f"  - {name}: {info['description']}"
        for name, info in available_skills.items()
    ])
    TOOL_SPEC["description"] = (
        "Load specialized skill instructions for specific tasks. "
        "Use this when you need detailed guidance on a particular topic.\n\n"
        f"Available skills:\n{skill_list}"
    )
    # Update the function attribute as well
    skill_tool.TOOL_SPEC = TOOL_SPEC

    logger.info(f"Skill tool initialized with {len(available_skills)} skills")


def handle_skill_tool(
    skill_name: Annotated[str, "Name of the skill to invoke"]
) -> str:
    """
    Load and return the full content of a skill.

    Args:
        skill_name: The name of the skill to load

    Returns:
        Formatted skill content with instructions

    Raises:
        ValueError: If skill_tool is not initialized or skill_name is invalid
    """
    if _loader is None:
        raise ValueError("Skill tool not initialized. Call setup_skill_tool() first.")

    if not skill_name:
        raise ValueError("skill_name is required")

    logger.info(f"Loading skill: {skill_name}")

    try:
        skill_content = _loader.load(skill_name)

        # 스킬 내용을 XML 태그로 감싸서 반환
        formatted_content = (
            f"<skill name='{skill_name}'>\n"
            f"{skill_content}\n"
            f"</skill>\n\n"
            f"The skill '{skill_name}' has been loaded. "
            f"Follow the instructions above to complete the task."
        )

        return formatted_content

    except SkillNotFoundError as e:
        logger.warning(f"Skill not found: {skill_name}")
        raise ValueError(str(e))


def skill_tool(tool: ToolUse, **kwargs: Any) -> ToolResult:
    """
    Strands SDK wrapper for skill tool.

    Args:
        tool: Strands ToolUse object (toolUseId, input)
        **kwargs: Additional parameters (e.g., agent)

    Returns:
        ToolResult with skill content or error message
    """
    tool_use_id = tool["toolUseId"]
    skill_name = tool["input"].get("skill_name", "")

    try:
        result = handle_skill_tool(skill_name)
        return {
            "toolUseId": tool_use_id,
            "status": "success",
            "content": [{"text": result}]
        }

    except ValueError as e:
        logger.error(f"Error in skill_tool: {e}")
        return {
            "toolUseId": tool_use_id,
            "status": "error",
            "content": [{"text": str(e)}]
        }
    except Exception as e:
        logger.error(f"Unexpected error in skill_tool: {e}")
        return {
            "toolUseId": tool_use_id,
            "status": "error",
            "content": [{"text": f"Error loading skill: {str(e)}"}]
        }


# Attach TOOL_SPEC to the function so Strands SDK can find it
skill_tool.TOOL_SPEC = TOOL_SPEC
