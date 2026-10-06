#!/usr/bin/env python3
"""Run offline evaluation against mock providers and gold fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.schemas.transcript import MeetingMetadata, TranscriptSegment  # noqa: E402
from app.services.evidence import validate_meeting_intelligence  # noqa: E402
from app.services.meeting_intelligence import MockMeetingIntelligenceProvider  # noqa: E402
from app.services.qa import ContextSegment, MockQAProvider  # noqa: E402

EVALS = Path(__file__).resolve().parent
GOLD = EVALS / "gold"
FIXTURES = EVALS / "fixtures"
RESULTS = EVALS / "results"


@dataclass
class CaseResult:
    name: str
    passed: bool
    detail: str


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_segments(gold: dict) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for row in gold["segments"]:
        segments.append(
            TranscriptSegment(
                id=uuid4(),
                ordinal=row["ordinal"],
                speaker_label=f"speaker_{row['ordinal'] % 2}",
                speaker_display_name=row["speaker"],
                start_ms=row["start_ms"],
                end_ms=row["end_ms"],
                text=row["text"],
                language="en",
                confidence=0.9,
            )
        )
    return segments


async def eval_insights(fixture_id: str) -> list[CaseResult]:
    transcript = load_json(GOLD / f"{fixture_id}.transcript.json")
    gold = load_json(GOLD / f"{fixture_id}.insights.json")
    meta = load_json(FIXTURES / f"{fixture_id}.metadata.json")
    segments = build_segments(transcript)
    provider = MockMeetingIntelligenceProvider()
    result = await provider.extract(
        MeetingMetadata(
            title=meta["title"],
            meeting_type=meta["meeting_type"],
            participant_aliases=["Mina", "Noah"],
        ),
        segments,
        template=meta["meeting_type"],
    )
    issues = validate_meeting_intelligence(result, segments)
    cases = [
        CaseResult(
            "evidence_validation",
            not issues,
            "; ".join(f"{i.code}:{i.message}" for i in issues) or "ok",
        )
    ]
    joined = f"{result.one_sentence_summary} {result.executive_summary}".lower()
    for needle in gold.get("one_sentence_summary_contains", []):
        cases.append(
            CaseResult(
                f"summary_contains:{needle}",
                needle.lower() in joined,
                "found" if needle.lower() in joined else "missing",
            )
        )
    decision_text = " ".join(d.text for d in result.decisions).lower()
    for needle in gold.get("must_have_decision_keywords", []):
        cases.append(
            CaseResult(
                f"decision_contains:{needle}",
                needle.lower() in decision_text,
                "found" if needle.lower() in decision_text else "missing",
            )
        )
    action_text = " ".join(a.task for a in result.action_items).lower()
    for needle in gold.get("must_have_action_keywords", []):
        cases.append(
            CaseResult(
                f"action_contains:{needle}",
                needle.lower() in action_text,
                "found" if needle.lower() in action_text else "missing",
            )
        )
    return cases


async def eval_qa(fixture_id: str) -> list[CaseResult]:
    transcript = load_json(GOLD / f"{fixture_id}.transcript.json")
    gold = load_json(GOLD / f"{fixture_id}.qa.json")
    segments = build_segments(transcript)
    by_ordinal = {s.ordinal: s for s in segments}
    context = [
        ContextSegment(
            id=s.id,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            speaker_label=s.speaker_label,
            speaker_name=s.speaker_display_name or s.speaker_label,
            text=s.text,
        )
        for s in segments
    ]
    provider = MockQAProvider()
    cases: list[CaseResult] = []
    for item in gold["cases"]:
        answer = await provider.answer(item["question"], context)
        status_ok = answer.answer_status == item["answer_status"]
        cases.append(
            CaseResult(
                f"qa_status:{item['question'][:40]}",
                status_ok,
                f"got={answer.answer_status} expected={item['answer_status']}",
            )
        )
        if item["answer_status"] == "supported":
            text_ok = any(
                token.lower() in answer.answer.lower()
                for token in item.get("acceptable_answers", [])
            )
            cases.append(
                CaseResult(
                    f"qa_answer:{item['question'][:40]}",
                    text_ok,
                    answer.answer,
                )
            )
            expected_ids = {by_ordinal[i].id for i in item.get("evidence_ordinals", [])}
            cite_ok = bool(set(answer.citations) & expected_ids) if expected_ids else True
            cases.append(
                CaseResult(
                    f"qa_citation:{item['question'][:40]}",
                    cite_ok,
                    f"citations={answer.citations}",
                )
            )
        else:
            cases.append(
                CaseResult(
                    f"qa_empty_citations:{item['question'][:40]}",
                    answer.citations == [],
                    f"citations={answer.citations}",
                )
            )
    return cases


async def run(fixture_id: str) -> list[CaseResult]:
    results = await eval_insights(fixture_id)
    results.extend(await eval_qa(fixture_id))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline mock evaluations")
    parser.add_argument("--fixture", default="mtg_001")
    args = parser.parse_args()
    results = asyncio.run(run(args.fixture))
    passed = sum(1 for r in results if r.passed)
    payload = {
        "fixture_id": args.fixture,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "total": len(results),
        "cases": [asdict(r) for r in results],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{args.fixture}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
