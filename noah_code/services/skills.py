"""Skill system — load and manage SKILL.md-based skills.

Skills are markdown files with YAML frontmatter that teach Noah new behaviors.
They live in:
  - ~/.noah/skills/<name>/SKILL.md  (personal, all projects)
  - .noah/skills/<name>/SKILL.md    (project-specific)

Frontmatter fields (all optional):
  name:                     Display name / slash-command name (defaults to directory name)
  description:              When to use — Noah uses this for auto-invocation
  allowed-tools:            Tools allowed without permission when skill is active
  disable-model-invocation: true = only user can invoke manually
  user-invocable:           false = hidden from /menu, only Noah can trigger
  context:                  'fork' = run in isolated subagent (future)
  argument-hint:            Autocomplete hint for arguments
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..config import get_config_dir

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """A loaded skill."""
    name: str
    description: str
    content: str  # markdown body (without frontmatter)
    base_dir: str  # directory containing SKILL.md
    source: str  # 'personal' | 'project'

    # Frontmatter options
    allowed_tools: list[str] = field(default_factory=list)
    disable_model_invocation: bool = False
    user_invocable: bool = True
    argument_hint: str | None = None
    context: str | None = None  # 'fork' | None
    agent: str | None = None


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown text.

    Returns (frontmatter_dict, markdown_body).
    """
    if not text.startswith("---"):
        return {}, text

    # Find closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    yaml_str = text[3:end].strip()
    body = text[end + 4:].strip()

    try:
        fm = yaml.safe_load(yaml_str)
        if not isinstance(fm, dict):
            return {}, text
        return fm, body
    except yaml.YAMLError as e:
        logger.warning("Failed to parse SKILL.md frontmatter: %s", e)
        return {}, text


def _extract_description(content: str) -> str:
    """Extract first paragraph from markdown as fallback description."""
    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:250]
    return ""


def _parse_allowed_tools(value: Any) -> list[str]:
    """Parse allowed-tools from frontmatter (string or list)."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return value.split()
    return []


def load_skill(skill_dir: Path, source: str) -> Skill | None:
    """Load a single skill from a directory containing SKILL.md."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None

    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to read %s: %s", skill_file, e)
        return None

    fm, body = _parse_frontmatter(text)

    name = str(fm.get("name", skill_dir.name)).lower().strip()
    # Validate name: lowercase, numbers, hyphens only
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
        name = skill_dir.name.lower()

    description = str(fm.get("description", "")) or _extract_description(body)

    return Skill(
        name=name,
        description=description,
        content=body,
        base_dir=str(skill_dir),
        source=source,
        allowed_tools=_parse_allowed_tools(fm.get("allowed-tools")),
        disable_model_invocation=bool(fm.get("disable-model-invocation", False)),
        user_invocable=fm.get("user-invocable", True) is not False,
        argument_hint=fm.get("argument-hint"),
        context=fm.get("context"),
        agent=fm.get("agent"),
    )


def load_skills_from_dir(base_path: Path, source: str) -> list[Skill]:
    """Load all skills from a skills directory.

    Expects structure: base_path/<skill-name>/SKILL.md
    """
    if not base_path.is_dir():
        return []

    skills = []
    try:
        for entry in sorted(base_path.iterdir()):
            if not entry.is_dir():
                continue
            skill = load_skill(entry, source)
            if skill:
                skills.append(skill)
    except OSError as e:
        logger.warning("Failed to scan skills dir %s: %s", base_path, e)

    return skills


def discover_skills(cwd: str = "") -> list[Skill]:
    """Discover all skills from all directories.

    Priority (later overrides earlier): agents-standard < project < personal.
    """
    seen: dict[str, Skill] = {}

    # Agent Skills open standard: ~/.agents/skills/ (lowest priority)
    agents_skills_dir = Path.home() / ".agents" / "skills"
    for skill in load_skills_from_dir(agents_skills_dir, "agents"):
        seen[skill.name] = skill

    # Project-level skills
    if cwd:
        project_skills_dir = Path(cwd) / ".noah" / "skills"
        for skill in load_skills_from_dir(project_skills_dir, "project"):
            seen[skill.name] = skill

    # Personal skills (highest priority — overwrites project)
    personal_skills_dir = get_config_dir() / "skills"
    for skill in load_skills_from_dir(personal_skills_dir, "personal"):
        seen[skill.name] = skill

    return list(seen.values())


def substitute_arguments(content: str, args: str) -> str:
    """Replace argument placeholders in skill content.

    Supports:
      $ARGUMENTS  — all arguments
      $ARGUMENTS[N] or $N — Nth argument (0-based)
    """
    if not args:
        return content

    parts = args.split()

    # Replace indexed arguments: $ARGUMENTS[N] and $N
    def replace_indexed(m: re.Match) -> str:
        idx = int(m.group(1))
        return parts[idx] if idx < len(parts) else ""

    result = re.sub(r"\$ARGUMENTS\[(\d+)\]", replace_indexed, content)
    result = re.sub(r"\$(\d+)(?!\w)", replace_indexed, result)

    # Replace $ARGUMENTS with all args
    result = result.replace("$ARGUMENTS", args)

    # If no placeholder was present, append args
    if "$ARGUMENTS" not in content and "$0" not in content and "$ARGUMENTS[" not in content:
        result = content + f"\n\nARGUMENTS: {args}"

    return result


def render_skill_prompt(skill: Skill, args: str = "") -> str:
    """Render a skill's content for injection into the conversation.

    Performs argument substitution and prepends base directory info.
    """
    content = skill.content

    # Substitute arguments
    if args:
        content = substitute_arguments(content, args)

    # Replace ${NOAH_SKILL_DIR} with the skill's directory
    content = content.replace("${NOAH_SKILL_DIR}", skill.base_dir.replace("\\", "/"))

    # Prepend base directory so the model can find supporting files
    header = f"Base directory for this skill: {skill.base_dir}\n\n"

    return header + content


def get_skills_description(skills: list[Skill], max_chars: int = 8000) -> str:
    """Build a compact description of available skills for the system prompt.

    Only includes skills where disable_model_invocation is False.
    Truncates to stay within token budget.
    """
    invocable = [s for s in skills if not s.disable_model_invocation]
    if not invocable:
        return ""

    lines = ["# Available Skills", ""]
    total = 0
    for s in invocable:
        desc = s.description[:250]
        line = f"- /{s.name}: {desc}"
        if total + len(line) > max_chars:
            lines.append(f"... and {len(invocable) - len(lines) + 2} more skills")
            break
        lines.append(line)
        total += len(line)

    lines.append("")
    lines.append(
        "To use a skill, invoke it with /skill-name or recommend it to the user. "
        "Skills with detailed instructions will be loaded when invoked."
    )
    return "\n".join(lines)
