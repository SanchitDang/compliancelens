import hashlib
import json
import re
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import uuid4

from compliancelens.privacy import Redactor, normalize_text

GUARD_POLICY = "normalized-injection-and-output-v1"
INJECTION_PATTERNS = (
    r"\b(?:ignore|disregard|forget)\b.{0,60}\b(?:instructions|rules|system prompt)\b",
    r"\b(?:reveal|show|print|repeat|display|expose)\b.{0,50}\b(?:system|developer) "
    r"(?:prompt|instructions|message)\b",
    r"\b(?:override|bypass|disable)\b.{0,40}\b(?:guardrails|safety|policy|filters)\b",
    r"<\|(?:im_start|system|developer)\|>|\[INST\]|</?(?:system|developer)>|"
    r"(?:^|\n)\s*(?:SYSTEM|DEVELOPER)\s*:",
    r"\b(?:send|upload|exfiltrate)\b.{0,100}\b(?:secret|credentials|api key|environment)\b",
    r"\b(?:pretend|act)\b.{0,25}\b(?:unrestricted|unfiltered|jailbroken)\b",
)


def injection_detected(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        re.search(pattern, normalized, re.IGNORECASE | re.DOTALL) for pattern in INJECTION_PATTERNS
    )


def output_violation(text: str, redactor: Redactor) -> str | None:
    if injection_detected(text):
        return "output_injection"
    if re.search(
        r"<(?:script|iframe|img|object)\b|javascript:|data:|mailto:|\]\(",
        normalize_text(text),
        re.IGNORECASE,
    ):
        return "unsafe_output_markup"
    if redactor.redact_query(text).counts:
        return "output_pii"
    return None


def assess_safety(root: Path, redactor: Redactor) -> dict[str, Any]:
    fixture_bytes = (root / "tests" / "fixtures" / "safety.json").read_bytes()
    fixtures = json.loads(fixture_bytes)
    pii = []
    for case in fixtures["pii"]:
        baseline = redactor.redact(case["text"]).text
        improved = redactor.redact_query(case["text"]).text
        pii.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected_values": len(case["values"]),
                "baseline_removed": sum(
                    normalize_text(value).casefold() not in normalize_text(baseline).casefold()
                    for value in case["values"]
                ),
                "query_removed": sum(
                    normalize_text(value).casefold() not in normalize_text(improved).casefold()
                    for value in case["values"]
                ),
            }
        )
    controls = [
        {
            "id": case["id"],
            "baseline_changed": redactor.redact(case["text"]).text != case["text"],
            "query_changed": redactor.redact_query(case["text"]).text != case["text"],
            "injection_flagged": injection_detected(case["text"]),
        }
        for case in fixtures["controls"]
    ]
    attacks = [
        {"id": case["id"], "channel": case["channel"], "caught": injection_detected(case["text"])}
        for case in fixtures["attacks"]
    ]
    report = {
        "run_id": uuid4().hex,
        "kind": "safety",
        "executed_at": datetime.now(UTC).isoformat(),
        "provider": "local_presidio_and_regex",
        "embedding_requests": 0,
        "chat_requests": 0,
        "document_policy": redactor.policy,
        "query_policy": redactor.query_policy,
        "guard_policy": GUARD_POLICY,
        "fixture_hash": hashlib.sha256(fixture_bytes).hexdigest(),
        "versions": {
            "presidio_analyzer": version("presidio-analyzer"),
            "spacy": version("spacy"),
            "nlp_model": redactor.model,
            "nlp_model_version": version(redactor.model),
        },
        "pii": pii,
        "controls": controls,
        "attacks": attacks,
        "totals": {
            "pii_cases": len(pii),
            "expected_values": sum(case["expected_values"] for case in pii),
            "baseline_removed": sum(case["baseline_removed"] for case in pii),
            "query_removed": sum(case["query_removed"] for case in pii),
            "attacks": len(attacks),
            "attacks_caught": sum(case["caught"] for case in attacks),
            "controls": len(controls),
            "controls_flagged": sum(case["injection_flagged"] for case in controls),
            "baseline_controls_changed": sum(case["baseline_changed"] for case in controls),
            "query_controls_changed": sum(case["query_changed"] for case in controls),
        },
    }
    path = root / "data" / "runs" / f"{report['run_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report["report_file"] = str(path.relative_to(root))
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report
