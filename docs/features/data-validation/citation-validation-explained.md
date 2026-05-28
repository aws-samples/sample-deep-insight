# Citation Validation — A Beginner's Guide

How Deep Insight makes sure every number in a generated report can be trusted.
This guide assumes no prior knowledge of the system.

---

## 1. The problem in one sentence

A report says things like *"total revenue was 16,431,923"*. A reader needs to know
that number is **real and verified**, not made up. A **citation marker** `[N]` is the
link from a number in the text to a verified calculation — like a footnote.

```
   "... total revenue was 16,431,923[1] ..."
                                      └──► [1] in the reference list:
                                           [1] Total revenue = SUM(Amount) = 16,431,923
```

If markers are missing, wrong, or dangling, readers lose trust. The validation system
exists to catch and fix those problems.

---

## 2. Key terms (plain language)

| Term | What it means |
|------|---------------|
| **Citation marker `[N]`** | A little tag like `[1]`, `[2]` placed right after a number, pointing to entry N in the reference list. |
| **`citations.json`** | The machine-readable reference list. Each entry has: an id (`"[1]"`), the value, the formula, a description, and a **status** (`verified` or `needs_review`). Produced by the **Validator**. |
| **`calculation_metadata.json`** | Every number the analysis computed (produced by the **Coder**), before filtering. A superset of `citations.json`. |
| **verified vs needs_review** | The Validator re-computes each number. `verified` = it checked out and may be cited. `needs_review` = it couldn't be confirmed → must NOT appear in the report. |
| **tolerance** | Numbers match if they're equal within a tiny margin (`max(value × 0.5%, 0.01)`), so rounding ("22.9%" vs "22.87%") still counts as a match. |

---

## 3. What is "prose"? (and what is NOT prose)

**Prose** = the flowing narrative sentences and paragraphs — the part of the report
that *makes claims in words*. This is where the report asserts findings as facts, so
**this is what needs citations**.

```
PROSE (makes claims → needs [N]):
   "Category A led all categories with 3,048,395[6], or 18.55%[7] of revenue."
        └─ a sentence stating a fact about a number

NOT prose (data artifacts / labels → do NOT need a [N] on every number):
   ┌─ Tables ─────────────┐   Charts (images)    Headings        Captions
   │ Category | Revenue   │   [bar chart .png]   "3. Sales"      "Figure 1: ... (2025.05)"
   │ A        | 3,048,395 │
   │ B        | 1,792,471 │   References list    Dates / scope counts
   └──────────────────────┘   "[1] Total = ..."  "2025", "176 products"
```

**Why the distinction matters:** a *table cell* is data being displayed — footnoting
every cell would clutter the report. A *sentence* that quotes a number is a claim the
reader might doubt — that deserves a citation. The validators are built to focus on
prose and ignore tables, charts, dates, and the reference list itself.

---

## 4. The four defect types (DeepTRACE taxonomy)

The Auditor classifies every problem into one of four types. Two **block** publication
(they make the report misleading); two are **warnings** (coverage/cleanliness).

| Type | Plain meaning | Severity | Example |
|------|---------------|----------|---------|
| **A** | A number is stated as a fact in **prose** but has **no `[N]`** (and can't be derived from nearby cited numbers). | ⚠️ warn | *"30s spent 3,758,703…"* with no marker — reader can't trace it. |
| **B** | A `[N]` **is** present, but the value it's attached to **doesn't match** what citation N actually says. | 🛑 **block** | Body *"…53.71%[1]…"* but citation `[1]` = 56.53%. The footnote points to the wrong number — actively misleading. |
| **C** | A `[N]` points to a citation id that **doesn't exist** in `citations.json`. | 🛑 **block** | Body *"…[9]…"* but there is no `[9]` defined — a dangling footnote. |
| **D** | A calculation was **computed and tracked** (`calculation_metadata.json`) but **never cited** anywhere. | ⚠️ warn | You computed a value, then didn't use it. Harmless to the reader, just unused. |

**Block vs warn — why:**
- **B and C make the report lie** (wrong/broken footnotes) → the report must be fixed (the system retries).
- **A and D are about coverage/tidiness** → flagged for a human, but publication is not blocked. (A number that is *correct but uncited* is not a lie; a tracked-but-unused calc hurts nobody.)

> Note on Type A: the value itself is usually correct (the Coder/Validator computed it).
> The gap is only the missing marker. That's why A is a *warning*, not a block.

---

## 5. Two cooperating tools

The system has **two** pieces that work together:

- **Resolver** (`resolve_body_citations`, inside the Reporter) — **fixes**: deterministically
  inserts a `[N]` for every prose number that equals a *verified* citation value but is
  missing its marker. Runs with no LLM, right after the report text is written.
- **Auditor** (a separate agent) — **detects & verifies**: reads the finished report and
  classifies any remaining defects (A/B/C/D), then emits a verdict.

Together they form a **generate → resolve → audit** pipeline (defense in depth): the
Reporter writes freely, the Resolver attaches markers it can prove, the Auditor checks
the result independently.

---

## 6. Walking through ONE number end-to-end (data-validation focus)

Theory is easy to nod at. Let's anchor everything in one concrete value that should
appear in the report:

> *"Category A's market share is 18.55%, on revenue of 3,048,395."*

We'll follow this single number through every stage and see exactly what "data
validation" means at each step.


### Step 1 — Raw data (the source of truth)

The dataset is just rows in a CSV. Everything downstream **must trace back to these
rows**:

```
sales.csv  (excerpt)
┌────────────┬─────────────┬───────────┐
│ category   │ amount      │ month     │
├────────────┼─────────────┼───────────┤
│ Category A │     812,400 │ 2025-03   │
│ Category A │     945,127 │ 2025-04   │   rows for Category A
│ Category A │   1,290,868 │ 2025-05   │    sum to 3,048,395
│ Category B │     601,200 │ 2025-03   │
│ Category C │     710,883 │ 2025-04   │
│ ...        │         ... │ ...       │   all other categories
└────────────┴─────────────┴───────────┘    sum to 13,383,528
                                         ─────────────────────
                                         SUM(amount) = 16,431,923
```


### Step 2 — Coder computes and records the recipe

The Coder agent derives the value, then writes **both the result AND the formula** to
`calculation_metadata.json`:

```
calculation_metadata.json (one entry)
┌──────────────────────────────────────────────────────────────────┐
│ {                                                                │
│   "id":          "ms_category_a",                                │
│   "value":       18.55,                                          │
│   "unit":        "%",                                            │
│   "formula":     "SUM(amount where category='A')                 │
│                   / SUM(amount) × 100",                          │
│   "description": "Category A's share of total revenue",          │
│   "importance":  "high",                                         │
│   "source_file": "sales.csv"                                     │
│ }                                                                │
└──────────────────────────────────────────────────────────────────┘
```

The key invariant: **the formula is recorded, not just the answer**. That's what makes
the next step possible.


### Step 3 — Validator re-computes from raw data ← the heart of data validation

The Validator does NOT trust the Coder. It re-runs the recorded formula **directly
against the CSV** and compares results:

```
   Coder's claimed value     :  18.55
                              │
   Validator independently   ─┤
   runs the recipe :          │
       numer = SUM(amount where category='A')   = 3,048,395
       denom = SUM(amount)                      = 16,431,923
       recomputed = 3,048,395 / 16,431,923 × 100 = 18.55
                              │
                              ▼
   |18.55 − 18.55|  ≤  tolerance ?
       YES → status: verified      → promoted to citations.json
       NO  → status: needs_review  → stays out (must not be cited)
```

Only verified entries are promoted into `citations.json`:

```
citations.json (one entry)
┌─────────────────────────────────────────────────────────────┐
│ {                                                           │
│   "citation_id":         "[7]",                             │
│   "calculation_id":      "ms_category_a",   ← link back     │
│   "value":               18.55,                             │
│   "description":         "Category A's share of revenue",   │
│   "verification_status": "verified"                         │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
```


### Step 4 — Reporter writes prose (and may attach the wrong marker)

The Reporter is an LLM. It drafts narrative — and at generation time it may forget the
marker, or attach the wrong one:

```
Three things the Reporter might write for the same fact:

  (a) forgot marker :  "Category A led with 18.55% of revenue."
  (b) right marker  :  "Category A led with 18.55%[7] of revenue."
  (c) WRONG marker  :  "Category A led with 18.55%[3] of revenue."
                                                  ^^ [3] is a different value!
```

If we trusted the LLM here, variant (c) would publish a lie: the marker points to
citation `[3]`, whose value is something else. This is exactly the **Type B defect**
the next step is built to prevent.


### Step 5 — Resolver finalizes markers deterministically (no LLM)

To make the LLM's mistakes irrelevant, the Resolver first **strips every `[N]` the LLM
wrote**, then re-inserts markers using *only* `citations.json`:

```
Resolver scan of body paragraphs:

  text after strip :  "Category A led with 18.55% of revenue."
  number found     :  18.55  (unit "%")
                        │
                        ▼
  scan verified citations for a value within tolerance:
                        citations.json[7].value = 18.55  ← match
                        │
                        ▼
  insert citation_id next to the number:
       "Category A led with 18.55%[7] of revenue."

  By construction:  body_value (18.55)  ==  cited_value (18.55)
                                      ↓
                         Type B is structurally IMPOSSIBLE
```

If the prose value matched **nothing** verified (e.g. prose says "22%" but no verified
value is within tolerance of 22), the Resolver leaves it uncited and the Auditor will
flag it later as Type A (warn, not block).


### Step 6 — Auditor cross-checks the finished report

The Auditor reads `final_report_with_citations.docx` independently and verifies every
`[N]` it finds:

```
For each marker in the docx body:

  body text     :  "...led with 18.55%[7] of revenue."
  marker id     :  [7]
  look up [7] in citations.json  →  value = 18.55
  |body − cited|  ≤  tolerance ?    YES   ✓
                                    │
                                    ▼
                       no defect for this marker

Across all markers in the report:
   Type B (value mismatch)   count = 0
   Type C (marker undefined) count = 0
                                    │
                                    ▼
                          Verdict: PASS  →  publish
```


### Sidebar — What if the Validator disagreed?

The whole chain pivots on Step 3. If the Validator's re-computation diverged from the
Coder's claim — say, because the Coder used the wrong filter or month range:

```
Coder       :  18.55
Validator   :  17.92        ← independent recompute differs
                  │
                  ▼
   verification_status = needs_review
   (the entry remains in calculation_metadata.json
    but is NOT promoted into citations.json)
                  │
                  ▼
   Resolver cannot find it among verified values
                  → no [N] is inserted for "18.55%" in prose
                  │
                  ▼
   Auditor sees "18.55%" stated as a fact with no marker
                  → Type A (warn) — published uncited, flagged for human
```

**Data validation, in one line:**
*Only numbers that two independent computations agree on can carry a citation marker.*

---

## 7. How it works — ASCII diagrams

### 7a. The full pipeline (who produces what)

```
 CODER ───────────────► calculation_metadata.json
   │  computes numbers      { id, value, importance, formula, source }
   ▼
 VALIDATOR ───────────► citations.json
   │  re-checks each value   [ { citation_id:"[1]", value, description,
   │  → verified/needs_review   verification_status, ... }, ... ]
   ▼
 REPORTER
   │  ① writes prose (LLM)  ── "30s spent 3,758,703 ..."  (a marker may be forgotten)
   │       │
   │       ▼
   │  ② resolve_body_citations(doc)   ◄── citations.json (verified entries only)
   │       │   deterministic, no LLM, BEFORE the reference list is added
   │       ▼
   │     final_report_with_citations.docx   (markers now filled in)
   │       └──(strip all [N])──► final_report.docx   (clean copy, no markers)
   ▼
 AUDITOR ─────────────► audit_findings.json   (verdict + any A/B/C/D findings)
      read-only check       reads docx + citations.json + calculation_metadata.json
      │
      ├─ found Type B or C? → RETRY → Reporter patches just those spots → re-audit
      └─ only Type A / D?   → warn (publish anyway, flag for human)
```

### 7b. Inside the Resolver — what happens to ONE prose number

```
 Look only at body paragraphs (tables & the reference list are skipped automatically)
        │
        ▼  find a number in the sentence (regex catches "1,234", "53.71%", etc.)
   already has a [N]? ──yes──► skip (don't double-cite)
        │ no
        ▼
   does it equal a VERIFIED citation value? (within tolerance)
        │
   ┌────┴───────────────┬─────────────────────────────┐
  0 matches         1 match                  2+ matches
   │                   │                          │
   ▼                   ▼                          ▼
 leave it          insert that [N]      pick the citation whose description
 uncited           next to the number   words overlap the sentence the most;
 (it's a date,                          if it's a tie → SKIP (never guess —
  scope count,                          a wrong [N] would be a Type B!)
  target, or
  unverified value)
```

### 7c. Why the Resolver is safe by design

```
 It only inserts [N] when  prose number == a VERIFIED citation value:

   • inserted [N]'s value == prose value      → a wrong marker (Type B) is IMPOSSIBLE
   • a year (2025), a scope count (176),       → matches nothing → stays uncited
     a future target (22,000)                    (no clutter, no false citations)
   • a needs_review value                      → not in the "verified" list → never cited
```

### 7d. Inserting a marker without breaking formatting

A paragraph is stored as several "runs" (each run can have its own bold/font). The
Resolver finds *which run* contains the number and inserts the `[N]` there, so styling
is preserved:

```
 paragraph runs:  [ "Total " ][ "836"(bold) ][ " orders" ]
 joined text:       "Total 836 orders"     match "836" ends at position 9
 walk runs:         run1 0..6 | run2 6..9 | run3 9..16   → 9 lands at end of run2/start run3
 insert "[2]":      "Total " + "836"(bold) + "[2]" + " orders"
 result:            "Total 836[2] orders"   ← the bold on "836" is preserved
```

(Rewriting the whole paragraph as one run would lose the bold — so insertion is done at
the run level. This logic is "pinned" so the system regenerates it exactly each run.)

---

## 8. The three verdicts

| Verdict | When | What happens |
|---------|------|--------------|
| **PASS** | No Type B or C found | Publish. |
| **RETRY** | Type B/C found, and fewer than 2 retries used | Send the specific defects back to the Reporter to patch, then audit again. |
| **NEEDS_REVIEW** | Type B/C still present after 2 retries | Publish as-is, flagged for a human (the document is not modified; the flag lives in the audit record + plan checklist). |

Type A and D never change the verdict — they are informational.

---

## 9. The big idea (for the audience)

A good report is **both trustworthy and readable**:

- **Trustworthy** → every *claim* in the prose can be traced to a verified number.
- **Readable** → tables and prose are not buried under redundant footnotes.

That balance is exactly why the validators focus on **prose claims** and leave tables,
charts, dates, and the reference list alone. The Resolver guarantees that any *verified*
value quoted in prose gets its marker; whatever it can't attach (an unverified value the
Reporter quoted) the Auditor reports as a Type A warning — a signal to improve the
upstream analysis, not a flaw in the validator.

---

## See also
- `citation-coverage-research.md` — research behind the post-hoc Resolver (generation-time vs post-hoc citation).
