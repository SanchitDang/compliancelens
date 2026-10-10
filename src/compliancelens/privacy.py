import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

import spacy
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text))
    return "".join(
        character
        for character in text
        if character in "\n\t" or unicodedata.category(character) not in {"Cf", "Cc"}
    )


QUERY_PATTERNS = {
    "EMAIL_ADDRESS": r"\b[\w.%+-]+\s*(?:\[at\]|\(at\)| at )\s*[\w.-]+"
    r"\s*(?:\[dot\]|\(dot\)| dot )\s*[a-z]{2,}\b",
    "DATE_OF_BIRTH": r"\b(?:DOB|date of birth|born)\s*[:=]\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})",
    "BANK_ACCOUNT": r"\b(?:bank\s+)?account(?:\s+(?:number|no\.?))?\s*[:=#]\s*"
    r"([0-9][0-9 -]{4,29}[0-9])",
    "STREET_ADDRESS": r"\b(?:home |mailing |street )?address\s*[:=]\s*"
    r"(\d{1,6}\s+(?:[\w'-]+\s+){0,5}"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Boulevard|Blvd)\b"
    r"(?:\s+[NSEW]{1,2})?)",
    "CA_POSTAL_CODE": r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?"
    r"\d[ABCEGHJ-NPRSTV-Z]\d\b",
}


@dataclass(frozen=True)
class RedactedText:
    text: str
    counts: dict[str, int]


class Redactor:
    policy = "presidio-english-sin-phone-section-v2"
    query_policy = "presidio-query-labelled-pii-normalized-v1"

    def __init__(self, model: str) -> None:
        if not model or not spacy.util.is_package(model):
            raise ValueError("PII_SPACY_MODEL must name an installed local model; run uv sync")
        self.model = model
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model}],
            }
        )
        self.analyzer = AnalyzerEngine(
            nlp_engine=provider.create_engine(), supported_languages=["en"]
        )
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="CA_SIN",
                patterns=[
                    Pattern("Canadian nine-digit identifier", r"\b\d{3}[- ]?\d{3}[- ]?\d{3}\b", 0.7)
                ],
            )
        )
        self.anonymizer = AnonymizerEngine()
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="PHONE_NUMBER",
                patterns=[
                    Pattern(
                        "North American phone",
                        r"\b(?:\+?1[-. ]?)?\(?[2-9]\d{2}\)?[-. ]\d{3}[-. ]\d{4}\b",
                        0.7,
                    )
                ],
            )
        )

    def redact(self, text: str) -> RedactedText:
        results = self.analyzer.analyze(
            text=text,
            language="en",
            entities=[
                "PERSON",
                "EMAIL_ADDRESS",
                "PHONE_NUMBER",
                "CREDIT_CARD",
                "IP_ADDRESS",
                "CA_SIN",
            ],
            score_threshold=0.5,
        )
        section_spans = [
            match.span(1)
            for match in re.finditer(
                r"\b(?:sections?|subsections?|paragraphs?)\s*:?\s*(\d+(?:\.\d+){3})\b",
                text,
                re.IGNORECASE,
            )
        ]
        results = [
            result
            for result in results
            if not (
                result.entity_type == "IP_ADDRESS" and (result.start, result.end) in section_spans
            )
        ]
        output = self.anonymizer.anonymize(text=text, analyzer_results=results)
        return RedactedText(output.text, dict(Counter(item.entity_type for item in output.items)))

    def redact_query(self, text: str) -> RedactedText:
        text = normalize_text(text)
        counts: Counter[str] = Counter()
        for entity, pattern in QUERY_PATTERNS.items():

            def replace(match: re.Match, entity: str = entity) -> str:
                counts[entity] += 1
                start, end = match.span(1) if match.lastindex else match.span()
                offset = match.start()
                return (
                    match.group()[: start - offset] + f"<{entity}>" + match.group()[end - offset :]
                )

            text = re.sub(pattern, replace, text, flags=re.IGNORECASE)
        result = self.redact(text)
        counts.update(result.counts)
        return RedactedText(result.text, dict(counts))
