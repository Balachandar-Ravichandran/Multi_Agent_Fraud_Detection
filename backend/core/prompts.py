"""Load system prompts from markdown files (PRD Section 5-10).

All prompts are defined as markdown files in backend/prompts/ rather than
hardcoded in Python, making them easier to audit, modify, and version-control.
"""
from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(filename: str) -> str:
    """Load a prompt markdown file and return its content (strips file header)."""
    path = PROMPTS_DIR / filename
    content = path.read_text(encoding="utf-8").strip()
    lines = content.split("\n")
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return "\n".join(lines).strip()


QA_PLAN = load_prompt("qa_plan.md")
INJECTION_ESCALATION = load_prompt("injection_escalation.md")
MODE_DETECTION = load_prompt("mode_detection.md")
GATE_POST_PLAN = load_prompt("gate_post_plan.md")
GATE_POST_RAG = load_prompt("gate_post_rag.md")
GATE_POST_STORAGE = load_prompt("gate_post_storage.md")
GATE_POST_FINDING = load_prompt("gate_post_finding.md")
GATE_POST_CLASSIFICATION = load_prompt("gate_post_classification.md")
GATE_POST_SUMMARY = load_prompt("gate_post_summary.md")
GATE_QA_GROUNDING = load_prompt("gate_qa_grounding.md")
NARRATIVE_GENERATION = load_prompt("narrative_generation.md")
