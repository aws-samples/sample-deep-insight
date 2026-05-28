# Citation Coverage — Research & Recommended Approach

**Date:** 2026-05-26
**Context:** Follow-on to `citation-marker-misuse.md` (the DeepTRACE Auditor PoC). The Auditor (Phase 1) is run-verified and reliably catches marker *integrity* defects (Type B/C). E2E runs then surfaced a *different*, genuine problem: **citation coverage** — the Reporter quotes many specific numbers in prose without `[N]` markers.

---

## 1. The issue: generation-time citation has unreliable recall

Across four E2E runs on the `moon_market` sample (all verdict PASS, Type B/C = 0), the count of uncited prose numbers (Type A, after the table-cell / date / references guards) varied wildly by run:

| Run | Type A (genuine prose, noise-filtered) | Reporter writing style |
|-----|----------------------------------------|------------------------|
| run3 | 3 (borderline: scope count, future target) | sparse inline numbers |
| run4 | 42 (real: per-segment revenues quoted inline) | number-dense narrative |

Same data, same pipeline — the only variable is **whether the Reporter LLM remembered to attach `[N]` to each value it quoted.** run4 wrote sentences like *"30대가 3,758,703원(22.9%)으로 최다 구매 연령대이며, 60대(3,446,426원)…"* — every number is a real, Validator-computed value, but only some carry markers.

This is the well-studied **generation-time citation** weakness: relying on the model to insert citations *while generating* gives unstable coverage. It is NOT a marker-integrity bug (those numbers are correct) and NOT an Auditor regression (the Auditor's guards only *skip*, never *add*, findings — so the 42 reflect the document, not the audit code).

## 2. Research landscape

Two paradigms (see Sources):

- **Generation-time citation** — model emits `[N]` as it writes. Simple, but recall is model-dependent and unstable. (Deep Insight today.)
- **Post-hoc attribution** — generate freely, then attribute each claim to evidence in a separate pass. Examples: **RARR** (Retrofit Attribution using Research and Revision: a *Research* step finds evidence, a *Revision* step edits/annotates), **Attribute-First-then-Generate**, **Ground-Every-Sentence** (interleaved reference–claim). Holistic evaluations find post-hoc generally improves *coverage*.

A counter-argument ("Generate → Ground is wrong") warns that a model may generate *unsupported* claims first, which post-hoc grounding then rubber-stamps.

## 3. Why Deep Insight is structurally advantaged

The "Generate → Ground is wrong" critique **does not apply here**, because Deep Insight's claims and sources are unusual:

- **Claims = numbers**; **sources = Validator-verified calculations** with exact values in `citations.json`.
- Numeric attribution is therefore **deterministic exact-match (== within tolerance)**, not fuzzy NLI entailment over web text.
- The prose does **not invent** numbers — every value originates from the Coder/Validator pipeline. The only thing missing is the *marker*, not the *fact*.

So post-hoc attribution is both **reliable** (deterministic matching) and **safe** (values are pre-validated) — a strictly better fit than for general web-grounded report writers (incl. Gemini Deep Research, which must attribute prose to retrieved web sources).

## 4. Key observation: the detection half already exists

The Auditor's `classify()` already computes, for every uncited numeric claim:

- `in_cite` — does this number match the `value` of an existing citation (within tolerance)?
- `in_metadata` — does it match a Coder-tracked calc that the Validator ≤20 priority filter dropped?

That is ~90% of a post-hoc attribution engine (extract every numeric claim + match against the evidence store). **The missing 10% is remediation** (insert the marker) — currently the Auditor only *reports*.

## 5. Recommended approach: deterministic post-hoc CitationResolver

Turn detection into insertion. The Reporter writes prose freely (no pressure to remember `[N]`); a deterministic resolver then attributes:

```
For each uncited prose numeric claim (already filtered: not in table / not date / not refs / >= threshold):
  ├─ matches an existing citation value (in_cite)      → insert that [N]                  (safe, deterministic)
  ├─ matches a tracked-but-filtered calc (in_metadata) → promote calc into citations.json + insert [N]
  │                                                       (fixes the ≤20-filter root cause for body-quoted values)
  └─ matches nothing                                   → leave uncited; flag for human    (never fabricate)
```

This is RARR's Research+Revision with **deterministic numeric matching** in place of fuzzy retrieval + NLI. After it runs, the Auditor's Type A should converge to near-zero (everything attributable has been attributed); whatever remains is genuinely unverifiable (e.g., a forward-looking target) and correctly stays uncited.

### Over-citation guard (audience protection)
The resolver attributes **only numbers that match a validated value**. Scope counts (e.g., "176개 제품") and future targets (e.g., "22,000원 목표") match nothing → correctly stay uncited. Reuse the Auditor's existing "what is a citeable prose claim" definition (skip table cells, dates, references section, `<100`). This keeps both **trust** (claims traceable) and **readability** (tables/prose not cluttered with redundant markers) — the audience-centric balance.

## 6. Placement

- **Option A (recommended): Reporter final step.** Promote the existing `audit_body_citations()` (today advisory-only, in `reporter_report_utils.py`, called from `reporter_final.py`) into an **active resolver** that runs deterministically (no LLM) right after the DOCX is assembled. The Auditor then verifies the result.
- **Option B: Auditor RETRY remediation.** More complex — Type A is warn (non-blocking), so it would need a new trigger; and remediation belongs with the artifact builder (Reporter), not the read-only Auditor.

## 7. Relationship to prior ideas & Gemini

- **R1 idea** (in `citation-marker-misuse.md` / memory): replace Reporter `[N]` output with `<ref calc_id=.../>` tokens + a CitationResolver. The approach here is the same direction but **simpler** — no special token emission needed; the resolver matches finished-prose numbers to citation values directly.
- **Gemini Deep Research** (next-gen) markets "collaborative planning" (≈ Deep Insight HITL plan review), "real-time streaming thoughts" (≈ `agent_text_stream`), and "professional-grade, fully cited analyses." Deep Insight already matches the first two; this resolver closes the "fully cited" gap — and does so more robustly than a web-grounded system can, thanks to deterministic numeric sources.

## 8. Trade-offs / open questions

- **Ambiguity:** one number may match multiple citations (e.g., two calcs both = 836). Disambiguate by proximity / matching description keywords in the same sentence (the Auditor already faces this for Type B).
- **Promotion budget:** `in_metadata` promotion bypasses the ≤20 filter — promote only body-quoted values, not all, to avoid bloating `citations.json`.
- **Derived values:** ratios like "15.0% 높게" may not equal any single raw calc → classify as DERIVED (cite the inputs or exempt), or have the Coder `track_calculation` the derivation.
- **Decision needed:** is near-zero Type A the goal (full coverage), or is a small reviewed warn-set acceptable? Resolver scope should match that bar.

## 9. Status / next
- This is research/design only — **not implemented**. Phase 1 Auditor changes remain uncommitted (see memory `project_citation_auditor`).
- If pursued: design the resolver API, integrate into `reporter_report_utils.py` (`audit_body_citations` → `resolve_body_citations`), and verify that post-resolver Auditor Type A → ~0 while Type B/C stay 0.

---

## Audit process — measured cost (E2E run6, `moon_market`; ~29 min total run)

Wall-clock derived from artifact mtimes; tokens from the per-agent `TokenTracker` summary.
Total run ≈ 29 min (`02:23:13` Coder start → `02:52:14` final verdict), ~3.6M tokens across all agents.

**Auditor stage (per pass).** The 3 batched audit scripts (extract → classify → verdict) run
in ~30 s; the full agent turn (read artifacts + 3 steps + streamed verdict) ≈ **~1 min**.
Tokens ≈ **145K per audit pass** (~4% of the run).

**Clean PASS (no retry, e.g. run5):** Auditor adds ≈ **1 min / ~145K tokens (~4%)**.

**With one RETRY (run6):** audit#1 (~1 min) → Reporter surgical patch via the content-locator
(~1.5 min) → audit#2 (~1 min) ≈ **~3.5 min (~12% of the run)**; Auditor tokens **247,698**
(the 2nd audit adds ~100K). The retry was triggered by 3 Type-B *rounding* mismatches
(body "3.4%" vs cited 3.3749%, diff 0.025 > tolerance 0.017) and converged to PASS — the
first E2E exercise of the retry / content-locator path.

**Resolver (`resolve_body_citations`):** deterministic, no LLM, runs inside `reporter_final` —
**negligible** (sub-second).

**verify-all-high (related, NOT negligible).** Raising the Validator cap from 20 → "all high"
roughly **doubled Validator tokens: 158,685 (20 verified) → 324,588 (144 verified), +166K**.
The earlier "batched → cheap" assumption was optimistic; verifying ~144 calcs costs ~2× the
20-calc baseline (more per-calc reasoning + larger `citations.json` generation). Justified by
the coverage win (Type A 17 → 2), but it is the **largest hidden cost of the citation system —
larger than the Auditor itself.**

**Net overhead** ≈ +145K (Auditor, clean) + 166K (verify-all-high) ≈ **~10% tokens** and
**~1 min** wall-clock on a clean run; a retry adds ~2.5 min and ~200K (patch + re-audit).
Highest-leverage cost reductions if needed: (a) force Validator verification into a single
batched script to cut the 2× factor; (b) loosen the Auditor's percentage tolerance to avoid
rounding-triggered retries.

---

## Sources
- Gemini Deep Research (next generation) — https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/
- Attribution, Citation, and Quotation: A Survey of Evidence-based Text Generation with LLMs — https://arxiv.org/html/2508.15396v1
- Generation-Time vs. Post-hoc Citation: A Holistic Evaluation of LLM Attribution — https://arxiv.org/html/2509.21557
- Attribute First, then Generate: Locally-attributable Grounded Text Generation — https://arxiv.org/pdf/2403.17104
- Ground Every Sentence: Improving RAG with Interleaved Reference-Claim Generation — https://arxiv.org/html/2407.01796v1
- "Generate → Ground" critique — https://dejan.ai/blog/generate-then-ground/
