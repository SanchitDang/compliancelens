import re
from collections import Counter
from dataclasses import dataclass

import spacy
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine


@dataclass(frozen=True)
class RedactedText:
    text: str
    counts: dict[str, int]


class Redactor:
    policy = "presidio-english-sin-phone-section-v2"

    def __init__(self, model: str) -> None:
        if not model or not spacy.util.is_package(model):
            raise ValueError("PII_SPACY_MODEL must name an installed local model; run uv sync")
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
