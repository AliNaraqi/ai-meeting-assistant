"""Meeting template catalog for extraction focus areas."""

from __future__ import annotations

from typing import Any

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "general",
        "label": "General",
        "description": "Summary, key points, actions, decisions, questions, and risks.",
        "focus": ["summary", "actions", "decisions", "questions", "risks"],
    },
    {
        "id": "standup",
        "label": "Stand-up",
        "description": "Yesterday, today, blockers, and dependencies.",
        "focus": ["yesterday", "today", "blockers", "dependencies", "actions"],
    },
    {
        "id": "interview",
        "label": "Interview",
        "description": "Questions, answers, competencies, and follow-up topics.",
        "focus": ["questions", "answers", "competencies", "follow_ups"],
    },
    {
        "id": "sales",
        "label": "Sales",
        "description": "Customer needs, objections, commitments, and next steps.",
        "focus": ["needs", "objections", "commitments", "next_steps"],
    },
    {
        "id": "research",
        "label": "Research",
        "description": "Hypotheses, evidence, methods, and unknowns.",
        "focus": ["hypotheses", "evidence", "methods", "unknowns"],
    },
    {
        "id": "lecture",
        "label": "Lecture",
        "description": "Concepts, definitions, examples, and study notes.",
        "focus": ["concepts", "definitions", "examples", "study_notes"],
    },
]


def list_templates() -> list[dict[str, Any]]:
    return list(TEMPLATES)


def get_template(template_id: str) -> dict[str, Any] | None:
    for item in TEMPLATES:
        if item["id"] == template_id:
            return item
    return None
