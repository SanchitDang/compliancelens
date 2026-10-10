# Phase 4 measured comparison

All scores below belong to verification run `4d154436ccef4f2fa5e2b03ffc44ef87`, completed October 10, 2026 UTC (October 9 in Toronto). Answer generation and reference-guided judging used **Azure AI Foundry**, provider model **gpt-5.4-mini-2026-03-17**, API version **2024-12-01-preview**, with a 2048-token output cap. Retrieval used **Azure text-embedding-3-small**, 1536 dimensions, against the same 530-chunk corpus. [Machine-readable results](phase-4.json) contain full corpus, manifest, benchmark, and code checksums and usage for every run.

The benchmark contains 34 questions: 30 supported questions across ten official documents and four expected refusals. This is a development set, with the same model acting as answerer and judge. These are rubric results, not independently verified legal accuracy.

| Variant | Top-k | Exact gold retrieval | Judge answer accuracy | Judge citation correctness | Expected refusals |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 6 | 28/30 (93.3%) | 23/30 (76.7%) | 90/96 (93.8%) | 4/4 |
| Wider | 10 | 29/30 (96.7%) | 23/30 (76.7%) | 97/105 (92.4%) | 4/4 |
| Focused | 3 | 28/30 (93.3%) | 27/30 (90.0%) | 91/94 (96.8%) | 4/4 |

All variants kept the 0.30 similarity threshold, corpus, prompt, backend, output cap, and gold references fixed. Each completed all 34 questions, with zero failed questions or missing judgments. Focused context improved answer scoring by four questions, or 13.3 percentage points, without losing gold-chunk hit rate. Wider context found another gold chunk but did not improve answer scoring. Defaults remain unchanged because these experiments use the development set and a subjective judge.

## Metric definitions

- Retrieval hit: a supported question retrieves at least one annotated exact gold chunk after the similarity gate. Divide by all 30 supported questions. Another valid chunk can answer correctly while failing this strict retrieval measure.
- Answer accuracy: the judge accepts coverage of every reference fact and material part of the question, with no materially false or unsupported claims. Divide by all 30 supported questions; errors, refusals, and missing judgments score zero. This includes reference-fact completeness, which can penalize a narrower correct answer.
- Citation correctness: directly supported claim/source pairs divided by every emitted claim/source pair. A claim citing multiple sources produces multiple decisions; each source must support the entire claim. Missing or malformed judgments score zero for those pairs and are reported separately. Refusals emit no pairs; a zero denominator is null, not perfect correctness.
- Expected refusal: refused unsupported questions divided by all four unsupported questions, independently of supported-answer accuracy.

Gold labels are never passed to retrieval or answer generation. The judge receives public reference facts/excerpts and the answer's individual cited excerpts. Numbered pair IDs, exact coverage, strict booleans, and completion checks reject malformed judgments. Retrieval and provenance are checked deterministically; semantic scores remain subjective.

## Usage and cache verification

The following totals cover all Phase 4 development, comparison, and verification runs, using the Azure models identified above. They include the interrupted judge-development run rather than hiding its cost.

| Provider role | Requests started | Usage responses | Reported input tokens | Reported output tokens | Requests with unknown usage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Azure embeddings | 34 | 34 | 549 | 0 | 0 |
| Azure answers | 104 | 103 | 142539 | 10487 | 1 |
| Azure judges | 103 | 103 | 121478 | 4059 | 0 |

The final verification reused all 102 query vectors, 95 answer responses, and 82 judge responses. It made four new answer requests and five new judge requests. Detected-sensitive or incomplete responses are excluded from caching; changed redacted judge prompts also require new requests. Cache hits add zero new provider tokens. The journal records original cached response tokens separately from new usage. Token counts are not dollar costs; exact charges depend on Azure deployment pricing, and the interrupted answer request has unknown usage.

The initial judge-development run was interrupted after the judge returned the wrong number of citation decisions. Its incomplete scores are not reported as benchmark results. The revised judge explicitly numbers each pair. The first complete comparison used run `3bdba837f31d4838a12a8cafc518d071`; verification tightened decoded-field redaction, removed three cache entries failing those checks, and re-evaluated changed prompts. Answer accuracy stayed unchanged; individual citation decisions changed. The JSON preserves both runs' usage, while this table reports the final verified implementation.

## Limits and reproduction

A spot check found that baseline q23 explicitly appointed a person responsible for PIPEDA compliance, yet the judge marked the answer inaccurate. Baseline q25 incorrectly assigned reasonable notice to the organization, illustrating a substantive error. These checks establish neither a human agreement rate nor independent accuracy. The strict gold rubric, alternative evidence, extra claims, redaction false positives, stochastic generation, and same-model judgment can affect scores. Expert review and a held-out set remain future work.

From the repository root, with the matching ingested corpus and configured Azure credentials:

```bash
export PATH="/opt/homebrew/bin:$PATH"
RETRIEVAL_TOP_K=6 uv run compliancelens eval
RETRIEVAL_TOP_K=6 uv run compliancelens eval --variant baseline
uv run pytest --db-integration
uv run pre-commit run --all-files
```

Use `--refresh-cache` after a deployment alias changes; it triggers paid requests. A fresh cache cannot reproduce the exact stochastic scores automatically. Caches are local and ignored, so a fresh checkout requires live inference. Bedrock and Ollama remain mock-tested only; neither produced these scores.
