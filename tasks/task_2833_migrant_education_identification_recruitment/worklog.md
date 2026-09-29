# Worklog — task_2833_migrant_education_identification_recruitment

## Step 1: Create task directory — 2026-09-05T04:05:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment` and its `workspace/` subdirectory. Index 2833 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide with auto-allocation).

## Step 2: Generate scaffold — 2026-09-05T05:25:00.000Z

Scaffold generation for task 2833 is complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/SCAFFOLD.yaml` | 2887 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1719 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/SCAFFOLD_CORNER_DESIGN.yaml` | 3268 |

Key separation verified: `SCAFFOLD.yaml` carries only the 13 §1.0–§1.7 keys (no design keys); each design file has exactly one top-level key (`scaffold_difficulty_design` / `scaffold_corner_design`).

## SCAFFOLD.yaml (§1.0–§1.7)
- `domain_name: migrant-education-identification-recruitment`, `api_prefix: /mep`, scenario copied verbatim.
- Complexity profile: `compliance_audit` + `temporal_windowing`, `graph` topology, `cyclic` state shape, `segregation_of_duties`, `immediate` consistency, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`.
- **12 entities**, **6 state machines**, **2 concurrency rules**, **8 calculations**, **55 validation rows** (priorities 1–30), **55 endpoints** (28 POST / 23 GET / 4 PATCH), **48 errors**, **5 roles**.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
All **9 §0.5 rules**, **21 instances** (2/2/2/2/3/3/3/2/2) — above the ≥18 floor. Every numeric assert was computed by executing the formula (e.g. provisional window 2029-06-14 vs final 2029-06-30; allocation split 28.12/18.75/28.13 = 75.00; transfer cap 7.00 → 13.00 total with 4.55 pinned as the trap).

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
All **9 claim-extraction-guide sections**, **74 instances** = **49 full recipes + 25 `excluded_because:` stubs**:

| section | instances |
|---|---|
| entities | 12 |
| state_machines | 13 |
| calculations | 13 |
| validations | 10 |
| endpoints | 6 |
| errors | 10 |
| rbac | 4 |
| complexity_layers | 5 |
| consistency_model | 1 |

All `claim_type:` values are rows of the guide's own tables; every stub cites a difficulty instance that exists by name.

## Verification performed
- 95 instance names unique across both design files; 0 duplicates.
- 0 unbound `${var}` placeholders (every one bound by an earlier `captures:`).
- 0 unknown `Entity.${var}.field` references in asserts; 0 invalid enum literals in payloads.
- All 48 catalogue errors are triggerable (checked programmatically); the `errors` section carries a comment mapping the codes already triggered elsewhere.
- Forbidden vocabulary sweep ("simultaneously", "in parallel", "first-writer-wins", "race winner") across all three files: NONE.

One lint violation surfaced and was fixed: a deliberate `ExchangeLiaison` PATCH denial sat inside a positively-named rbac instance, so check (b) flagged it; the call was relocated into the negatively-named denial instance (now 7 denials) rather than suppressing the check.

Final lint run, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     12
  §1.8 instances scanned:     21
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  694

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory under `tasks/` was listed, globbed, grepped or read at any point — the scaffold was derived solely from the scenario text and the generator skill's own spec plus its `claim-extraction-guide.md`.

**Orchestrator post-check (difficulty-directive leak):** the scaffold generator copied the line `Generate task harder than expert level!` into `SCAFFOLD.yaml`'s `scenario:` block, from which it would reach PRD.md via Step 4. Stripped lines 2–3 of `SCAFFOLD.yaml` (the directive plus its blank separator); `grep -c "harder than expert" SCAFFOLD.yaml` now returns 0, and the `scenario:` key begins directly at "2833. Migrant Education…". A pre-strip copy was kept at `/tmp/t2833_scaffold_prestrip.yaml`. All three YAMLs re-validated with `yaml.safe_load` after the edit; top-level keys confirmed as reported above.

## Step 3: Copy shared files — 2026-09-05T05:26:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T05:41:00.000Z

PRD generation complete and verified.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/workspace/PRD.md` — 438 lines / 97,532 bytes. Written incrementally (1 `Write` + 9 heredoc appends + 1 script-generated §4/§5 tail); ends cleanly on the last error-catalogue row, no truncation. No stray scratch files left in `workspace/` (only `INSTRUCTION.md` and `PRD.md`).

**Sections**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Caller Identity and RBAC · 2.2 API Response Structure (verbatim from `skills/prd-bench-doc-generator/section-2.2-response-structure.md`) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps and Record Versioning · 2.5 The Logical Program Clock · 2.6 Numeric Precision, Date Arithmetic and Rounding Discipline · 2.7 Stale-Version Guards on Capacity- and Plan-Bearing Writes · 2.8 The Validation Ladder (30 numbered rungs) · 2.9 Cascades, Conserved Quantities and Derived Mirrors
- §3 Business Logic & Workflows — 3.1 Recruitment Geography and the Recruiter Roster · 3.2 Placing Seasonal Coverage · 3.3 Identifying a Child and Scoring Priority for Services · 3.4 Recording, Documenting and Adjudicating the Qualifying Move · 3.5 The Certificate of Eligibility: Drafting, Correction and Submission · 3.6 Quality Control: Risk Flags, Sampling and the Re-Interview Decision · 3.7 Approval, the Continuation-of-Eligibility Term, and Reidentification · 3.8 The National Record Exchange and Credit Reconciliation · 3.9 Service Plans, Hour Allocation and the Delivery Ledger
- §4 Endpoint Definitions (Method | Path | Description | Authorized Role(s))
- §5 Error Code Catalogue (Error ID | HTTP Status Code)

**Coverage vs SCAFFOLD.yaml (all machine-verified)**
- Endpoints: 55/55 rows present with exact method+path match; 0 missing
- Errors: 48/48 present, 0 missing, 0 with a wrong HTTP status
- Entities: 12/12 documented; entity fields 98/98 present, 0 missing
- Endpoint `input` identifiers: 79/79 · dict-shaped `output` keys: 24/24 · path params: 12/12 · roles: 5/5
- Validations: 55 rows spanning 30 distinct priorities (1–30) → the §2.8 ladder has exactly 30 rungs
- All state-machine states and enum literals present

**Hard Contracts**
- Contract 1 (Field-Name Coverage): PASS. Ran both the lenient pass (dot-splitting `Entity.field`) and the strict pass — `only reachable inside a dotted token: []`, i.e. every required identifier also appears as a standalone backticked token.
- Contract 2 (Rule Coverage): PASS. All 55 validations, both `concurrency_rules`, all 8 calculations (including both dual-variant pairs), all 6 state machines, both multi-hop cascades, all cross-entity side effects and all field-level defaults/ranges/initial values are stated. One gap found during the final walk and fixed: the newly identified child's initial `eligibility_expires_on` (null) and four derived ledger fields at 0.00 were previously implicit; now explicit in §3.3.
- Contract 3 (§3 Path Purity): PASS. 1,036 backticked tokens scanned in §3 — 0 beginning with `/`, 0 bare HTTP-method tokens, 0 method+path pairs. All routes live only in §2.7, §4 and the §1 mount reference.

**Scaffold contradictions I adjudicated — worth flagging downstream**
1. `AgriculturalArea.recruiter_capacity` default: entity table says `default: 1`, but `POST /mep/areas` description says "defaults to 2". I used **1** (structured entity content outranks endpoint prose).
2. `limit` default: `pagination_defaults` and the fixed §2.2 block say 10; a §1.5 comment says 20. I used **10**.
3. List ordering: the generator default is `created_at` ascending, but the scaffold twice states newest-first. I used **newest-first by `created_at`, tie-broken by `id`**.
4. Three preconditions had no dedicated error code in the scaffold: COE ownership on correct/submit → `ERR_UNAUTHORIZED` (403); interview/COE same-student mismatch and PASS-with-codes / FAIL-without-codes → `ERR_INVALID_REQUEST` (422), as priority-4 shape violations.
5. `Student.version` on COE submit increments **only** when the `NOT_ELIGIBLE`/`TERM_EXPIRED` → `PENDING_DETERMINATION` transition actually fires; the approval cascade increments the child's `version` by exactly 1 across hops 3 and 4 combined.

The two withheld design indices (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Orchestrator post-check (truncation guard):** `wc -l` = 438; `tail -12` ends on the complete table row `| ERR_NO_QC_CANDIDATES | 409 |` — a real section boundary at the end of §5, the document's last section. Not truncated, so no regeneration needed. Grep for `harder than expert`, `scaffold`, `difficulty_design`, `corner_design` in PRD.md returns no matches: the Step 2 difficulty directive did not reach the PRD.

## Step 5: Generate unit tests — 2026-09-05T06:48:00.000Z

All four remaining Stage-2 files are written, compiled, and audited. Task 2833 test generation is complete.

## Deliverables (all at the TASK ROOT, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/`

**Stage 1 — `test_helpers/` (9 files, 1861 lines)**
`api_client.py` 346, `assertions.py` 321, `factories.py` 293, `fixtures.py` 377, `constants.py` 225, `api_errors.py` 131, `test_users.py` 97, `types.py` 37, `__init__.py` 34.
(`fixtures.py` gained `read_move`, `read_coe`, `read_qc_review` this session.)

**Stage 2 — `test_suite/` (30 files, 5544 lines, 91 tests)**
Queue A: `conftest.py` 15 + `test_01`…`test_18` (2343 lines, 42 tests).
Queue B: `test_20_corner_entities` 486/12, `test_21_corner_state_machines` 444/8, `test_22_corner_calculations` 293/4, `test_23_corner_validations` 287/4, `test_24_corner_endpoints` 369/5, `test_25_corner_errors` 777/10, `test_26_corner_rbac` 306/3, `test_27_corner_complexity_layers` 153/2, `test_28_corner_consistency_model` 86/1 — 3201 lines, 49 tests.

## Coverage against the two design indices
- **Queue A (Difficulty)**: 21 executable instances → 42 tests, every instance with exactly 2 (target ≥2 met, none under).
- **Queue B (Corner)**: 49 executable instances → 49 tests, one each (target ≥1 met). The 25 `excluded_because:` stubs were not translated, as specified.
- **Skipped instances: none.** Every non-stub instance in both queues passed the PRD-first two-condition filter and was translated; no gaps to report.

## Tag and citation audit (scripted, all green)
- 91 test functions, 91 `Design:` lines — exactly one per test, none untagged, none dual-tagged.
- Zero dangling tags: every leaf name resolves verbatim to a `name:` in its own source yaml; zero tags point at an excluded stub.
- 115 quoted PRD citations checked against `workspace/PRD.md`: 106 byte-identical after the declared glyph normalisation, the other 9 word-for-word identical and differing only in markup (backtick placement around `DRAFT → SUBMITTED`-style pairs, `**bold**` markers).
- No generated file mentions "scaffold", a design-yaml key, or a scaffold section/table reference.
- `python3 -m py_compile` clean over `test_suite/*.py` and `test_helpers/*.py`; `__pycache__` removed.
- `workspace/` contains only `INSTRUCTION.md` and `PRD.md` — no `test_helpers/`, no `test_suite/`, and `workspace/implementation/` was never read, run or created.

## Two places where PRD overrode the corner design (PRD wins, per the spec)
1. Corner `validations` asserts HTTP 200 for a successful QC-selection run; PRD line 249 states "A successful run answers 201, since it creates review resources." `test_22` and `test_23` assert **201**.
2. Corner `errors`/`rbac` recipes assert "GET /mep/areas returns exactly 1 row", but the PRD endpoint table declares **no `GET /mep/areas` list endpoint** (GET-by-id only). Those two tests instead prove "nothing was written" via GET-by-id — the surviving area still reads at `version` 1 with its original `name`.

## Fixture hazards handled
Money/hours/credits/distances all sent as JSON numbers; every calendar field sent date-only and every clock move as a full ISO-8601 instant, matching PRD's declared widths. `coe_payload` defaults `qc_hold_exempt: True`, so QC-pool tests pass `qc_hold_exempt=False` explicitly. Tests asserting PFS components override `student_payload`'s non-default academic profile (or use `factories.DROP` to fall back to PRD-declared defaults, e.g. the `grade_level` null assertion in `test_26`) — without that, the default profile scores exactly 60 and would flip `priority_tier` to `PFS`, changing the 75.00 allocation.

**Orchestrator note (isolation repair):** I mistakenly launched Step 5 alone rather than issuing Steps 5 and 6 as two Agent calls in a single message, so `test_helpers/` and `test_suite/` already existed on disk when Step 6 was due to start — defeating the physical isolation that normally prevents the implementation generator from reading the test suite. Rather than rely on a prompt-level prohibition, I restored the isolation physically: both directories were moved to `/tmp/t2833_hidden/` before spawning Step 6, so the implementation generator ran against a task tree containing no tests at any path, and were moved back to the task root immediately after Step 6 returned. Post-restore verification: `test_suite/` 28 `.py` files, `test_helpers/` 9 `.py` files, and `find workspace -maxdepth 2 -name "test_*" -type d` returns nothing.

## Step 6: Generate implementation — 2026-09-05T07:13:00.000Z

Done. Both smoke servers are killed (pids 206634/39833 and 245094/39834, killed by port lookup — no pattern kills), the implementation directory is listed, and `__pycache__` was removed so the tree contains only source.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2833_migrant_education_identification_recruitment/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `app.py` | 78 | app factory, blueprint registration, error handlers, `$PORT` entry point |
| `store.py` | 124 | in-memory `Store` (12 dicts), logical clock, id/timestamp minting, version bookkeeping |
| `envelope.py` | 130 | meta/response_type/data envelope, Decimal-preserving JSON writer, pagination meta |
| `errors.py` | 83 | all 48 `error_id → (status, message)` entries + `ApiError` |
| `validation.py` | 337 | typed body/query readers, pagination bounds, `round_half_up`, `add_months`/`add_years` |
| `auth.py` | 86 | rung-1 authentication (entity-backed Recruiter/QC roles), rung-2 authorization |
| `calc.py` | 379 | the eight named calculations |
| `flows.py` | 273 | CASCADE-A, CASCADE-B, allocation re-runs, service-status re-derivation, term sweep |
| `support.py` | 75 | per-entity 404 mapping, ordering/paging, list filters |
| `routes_areas.py` | 326 | areas, recruiters, assignments |
| `routes_students.py` | 372 | students, qualifying moves, interview records |
| `routes_coes.py` | 411 | certificates, QC selection, QC reviews |
| `routes_terms.py` | 295 | eligibility terms, reidentification, transfer requests |
| `routes_services.py` | 314 | service plans, deliveries, clock endpoint |
| `requirements.txt` / `start.sh` | 1 / 10 | `Flask>=2.0`; foreground `exec python3 app.py` on `$PORT`, bind `0.0.0.0`, no reloader |

**3294 lines total.** `python3 -m py_compile *.py` → COMPILE_OK.

## Coverage vs the PRD

- **Endpoints: 55/55** — verified by counting registered `@bp.route` decorators (exactly 55).
- **Entities: 12/12** — one dict per entity in `store.py`.
- **Error codes: 48/48 present and all 48 reachable** — a static scan confirms every catalogue key is raised by at least one code path. Three extra framework fallbacks (`ERR_NOT_FOUND` for unmatched paths, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`) exist outside the catalogue as defensive handlers.
- **Validation ladder: all 30 rungs**, with the ordering-sensitive ones commented rung-by-rung at the call sites (assignment create, COE submit, QC decide, delivery create, transfer match).

## Smoke-test result

Two independent scenario scripts under `/tmp/t2833_impl_scratch/`, each against a freshly booted process:

- `smoke.py` → **ALL_PASS** (~66 assertions): envelope shape, auth ladder, area/recruiter/assignment lifecycle, PFS derivation (35 → 53 after verification), provisional vs final eligibility windows, QC selection + `ERR_NO_QC_CANDIDATES`, approval cascade minting an ACTIVE term, allocation `75.00` alone then `50.00`/`25.00`, quarter-hour grid rejection, exact ledger conservation on reversal, credit reconciliation and rejection compensation, all three sweep branches with boundary probes, reidentification, pagination bounds.
- `smoke2.py` → **ALL_PASS** (58 assertions): 3-day buffered area capacity (day 3 rejected, day 4 accepted) vs unbuffered recruiter overlap (back-to-back legal), PRIMARY slot release on close, OSY score floor, allocation residual landing on the earliest plan (`28.12`/`28.13`/`18.75`), supersession, re-allocation on a `pfs_flag` flip, derived-field writes silently dropped, three risk flags, duplicate-live-COE 409, non-owner 403, **segregation of duties outranking the credential check**, QC FAIL → `RETURNED_FOR_CORRECTION` with the child walked back, age-out cap binding (`2027-12-31`, `age_out_capped: true`), full CASCADE-B, and credit tiers keyed on the pre-cap total at exactly `12.00`/`24.00`/`11.99`.

Constraints honoured: no seeded data (state is empty on every boot, nothing written to disk — a `find` for `*.db`/`*.sqlite*`/`*.json` returns nothing), `start.sh` reads `$PORT` and runs in the foreground with the reloader off, all long files were built with chunked appends and absolute paths, scratch confined to `/tmp/t2833_impl_scratch/`, and no `SCAFFOLD_*_DESIGN.yaml` or test files were read or written.

## Step 7: Run tests and iterate — 2026-09-05T07:29:00.000Z

Clean. All 8 rounds pass, storage is in-memory only, and `worklog.md` is untouched (mtime still 07:14, before I started).

## Summary

**Iterations run:** 2 (sweep 1 → 9 deterministic failures; sweep 2 → clean).

Sweep 1 showed **zero flakiness**: the identical 9 tests failed in all 8 rounds, so no timing/load noise had to be filtered out.

**Tests deleted:** none. All 9 failures survived STEP 1 (PRD verbatim-covers + uniquely derivable); each was either a test-layer bug or a genuine implementation defect.

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py` — renamed the acting-recruiter positional parameter of `file_interview` / `file_reinterview` from `recruiter_id` to `acting_recruiter_id`. PRD §3.4 says the server "stamps `recruiter_id` from `X-User-ID`, and a `recruiter_id` supplied in the payload is ignored"; the old signature made that rule untestable because a body override named `recruiter_id` collided with the header identity (`TypeError: got multiple values`).

**Fixes applied to `test_suite/`** (STEP 2 — test did not faithfully express the pinned PRD sentence)
- `test_04_transfer_credit_cap.py::_received_request` — the predecessor-student call passed `full_name=` alongside `**STUDENT_A`, which already contains `full_name` (`TypeError`). Now merges the override into a copy of the profile. Broke 2 tests.
- `test_25_corner_errors.py::test_transfer_self_match_is_refused_and_a_rejected_request_locks` — the test rejected a request still in `INITIATED` and expected 200, but PRD §3.8 states rejection "is permitted from `RECEIVED` and from `RECONCILED`, and from anywhere else it is refused with `ERR_TRANSFER_INVALID_STATE`". The implementation's 409 was correct; the test now matches against the genuine predecessor and receives before rejecting, keeping every downstream lock assertion intact.
- `test_25_corner_errors.py::test_second_certificate_submit_hits_the_duplicate_active_coe_guard` — the sibling certificate was drafted on a *different* qualifying move, but the guard PRD §3.5 pins is scoped to "the same pairing of `student_id` and `move_id`", so the PRD-faithful implementation correctly allowed the submit. The sibling now rests on the approved certificate's own move (expected provisional window updated to `2029-06-14`, i.e. move_date `2026-06-15` + 36 months − 1 day).

**Fixes applied to `implementation/`** (STEP 3 — test faithful, implementation wrong)
- `workspace/implementation/store.py::Store.now_iso` — `created_at` / `updated_at` were stamped from `time.time()` (the wall clock), violating PRD §2.5's categorical "Nothing in this service reads the wall clock." Now derived from the logical clock instant, with a one-millisecond forward nudge whenever a stamp would repeat or regress. This keeps the first row written after any clock move carrying the clock instant exactly (what the 4 failing tests assert) while preserving `created_at` as a strict total order — which the hour-allocation rule depends on, since PRD §3.9 says `created_at` ascending is "the only sort key, and no further tie-break is needed because plan creates are serialised." A naive pure-logical-clock stamp would have tied every same-request row and made the residual-on-earliest-plan tests nondeterministic. Removed the now-unused `time` import; added the epoch constant. Broke 4 tests.

`adjudicated_on` and `decided_on` already read `clock_instant()` correctly. `meta.api_request_timestamp` remains the only wall-clock read; PRD §2.2 constrains it merely to "server-generated", and no test asserts its value, so it was left alone rather than expanding scope.

**Final sweep evidence** (from `workspace/implementation/results.$i.json`):

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 91/91 | 91/91 | 91/91 | 91/91 | 91/91 | 91/91 | 91/91 | 91/91 |

0 failures and 0 errors in every round.

**Orchestrator post-check (sweep artifacts):** independently re-read all 8 `results.$i.json` from disk rather than trusting the subagent's claim — 8 files present, every one reporting `passed=91 total=91 failed=0 errors=0`. The subagent did not write to `worklog.md` (still exactly the 6 orchestrator-written step headings at that point).

## Step 8: Finalize PRD — 2026-09-05T07:33:00.000Z

Step 8 was NOT skipped: Step 7 ran 2 iterations and applied 1 `implementation/` fix, 1 `test_helpers/` fix and 3 `test_suite/` fixes, so the skip condition (zero fixes of every kind) did not hold.

Done. `PRD_FINALIZED.md` written with two edits.

## Line counts
- `PRD.md`: 438 lines → `PRD_FINALIZED.md`: 440 lines (+2 lines, **+0.46%**). Two paragraphs touched, no sections added.

## Changes
- **§2.4 — insert** — new paragraph pinning that `created_at`/`updated_at` are read from the logical clock (not the wall clock) and issued from one shared never-repeating/never-regressing sequence (clock instant when it is later than the last stamp issued, else last stamp + 1 ms); the first row after a forward clock move carries the clock instant exactly; a new row's `updated_at` is a single stamp equal to its `created_at`. — `implementation/store.py:41-53` (`now_iso`), `store.py:106-112` (`base_row`), `store.py:87-103` (`bump`/`touch_only`).
- **§2.5 — revise** — the categorical "Nothing in this service reads the wall clock" now names `meta.api_request_timestamp` as the single exception and the only wall-clock read; the clock's consumer list gains the `created_at`/`updated_at` row stamps (via §2.4's sequencing) and notes that `adjudicated_on`/`decided_on` are the raw clock instant with no sequencing adjustment. — `implementation/envelope.py:27-33` + `envelope.py:86-93`; `routes_students.py:276`; `routes_coes.py:384`.

## Pre-edit search log

**Edit 1 — subject: derivation and sequencing of every `created_at`/`updated_at` row stamp.**
(b) Enumerated/read: `store.py` (`now_iso`, `base_row`, `bump`, `touch_only`, `mark_fresh`, `sort_newest_first`, `sort_oldest_first`), `envelope.py` (`iso_from_epoch_ms`, `wall_timestamp`, `_meta`); every writer of `created_at` — `routes_areas.py:48,119,221`, `routes_students.py:73,213,333`, `routes_coes.py:68,275`, `routes_terms.py:95,148`, `routes_services.py:76,223,278`, `flows.py` term create via `base_row`; every consumer of `created_at` ordering — `calc.py:127` (allocation input set), `calc.py:225,238` (QC pool ranking), `calc.py:342` (sweep batch), `flows.py:98,160,164,191`, plus §2.3 list ordering through `sort_newest_first`.
(c) Adjustments: (i) wrote "keeps `created_at` an ordering over rows written in sequence" instead of asserting a universal strict total order, so §2.3's `id` tie-break and §3.9's "no further tie-break is needed" stay true rather than contradicted; (ii) scoped the sentence to `created_at`/`updated_at` only, since `adjudicated_on`/`decided_on` use `clock_instant()` and never consume the sequence; (iii) added the "`updated_at` stamped once, equal to its `created_at`" clause — without it, an implementer applying the never-repeat rule would emit `created_at` + 1 ms as the initial `updated_at`, which every create path in the impl contradicts (all assign one stamp to both fields, and `mark_fresh` keeps the in-request allocation/cascade bumps from refreshing it).

**Edit 2 — subject: the wall-clock prohibition and the set of fields the logical clock feeds.**
(b) Enumerated/grepped: all `datetime.now`/`time.` reads across `implementation/` → only `envelope.py:29` (`wall_timestamp`), reached from `_meta` and therefore from `success`, `success_list` and `error`, i.e. every response; confirmed `store.py` no longer imports `time`; all `clock_instant()` callsites — `routes_students.py:276` (`adjudicated_on`), `routes_coes.py:384` (`decided_on`), `routes_services.py:314` (`current_utc` in the clock-set response).
(c) Adjustments: named `meta.api_request_timestamp` as the single exception rather than deleting the prohibition (softening, not widening); appended "the last two taken as the clock instant itself, with no sequencing adjustment" so the new §2.4 sequence is not read as applying to `adjudicated_on`/`decided_on`, which the impl stamps un-nudged.

## Step 7 items that needed no PRD change
- `test_helpers/fixtures.py` `acting_recruiter_id` rename — pure fixture-signature bug; §3.4 already states verbatim that the server stamps `recruiter_id` from `X-User-ID` and ignores a body value (§3.5 says the same for `initiating_recruiter_id`).
- `test_04_transfer_credit_cap.py::_received_request` duplicate-`full_name` `TypeError` — pure test bug, no behavior involved.
- `test_25` transfer-rejection-from-`INITIATED` fix — §3.8 already pins rejection to `RECEIVED`/`RECONCILED` with `ERR_TRANSFER_INVALID_STATE` elsewhere; verified `routes_terms.py:266-300` matches, and the downstream match/receive/reconcile locks follow from the existing per-step state guards.
- `test_25` duplicate-active-COE fix — §3.5 already scopes the guard to "the same pairing of `student_id` and `move_id`", and §3.5's provisional-window rule already determines the corrected `2029-06-14` expectation.

**Orchestrator post-check:** `cmp` confirms `PRD_FINALIZED.md` differs from `PRD.md`; `diff` shows exactly the two reported hunks (one §2.4 insert, one §2.5 revise) and nothing else — 438 → 440 lines.

## Step 9: Complete PRD — 2026-09-05T08:14:00.000Z

**Orchestrator decision on structure:** a single subagent scanning 3,294 lines of implementation across 16 modules against a 440-line PRD reliably under-scans (the failure mode is a `PRD_COMPLETED.md` byte-identical to its source, i.e. the scan never really ran). I therefore ran Step 9 as **three sequential passes partitioned by implementation module** over one shared `PRD_COMPLETED.md`. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited the file in place. Each pass was told what earlier passes had already adjudicated as correct, so later passes would not re-flag or contradict settled prose. Partition: pass 1 = `app.py`, `store.py`, `envelope.py`, `errors.py`, `validation.py`, `auth.py`, `support.py`, `routes_areas.py`; pass 2 = `calc.py`, `flows.py`, `routes_students.py`, `routes_coes.py`; pass 3 = `routes_terms.py`, `routes_services.py`.

**Aggregate:** `PRD_FINALIZED.md` 440 lines / 98,721 bytes → `PRD_COMPLETED.md` 440 lines / 110,723 bytes (**+12,002 bytes, +12.2%**; 0 new lines, 0 new sections — every edit is in-paragraph). **44 ambiguity-pins, 5 mismatch-revisions** across the three passes.

### Pass 1 — infrastructure + areas (16 ambiguity-pins, 1 mismatch-revision)

440 lines / 98,721 bytes → 440 lines / 103,293 bytes (+4,572 bytes). 13 paragraphs touched, 17 discrete changes.

- §2.1 — revise — ambiguity — a present-but-blank/whitespace-only `X-User-ID` is also `ERR_UNAUTHENTICATED` — auth.py:27-28
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — envelope.py:19,23-24
- §2.3 — revise — ambiguity — the `created_at` tie-break is `id` **ascending** (impl stable-sorts by id asc, then created_at desc) — store.py:115-118
- §2.3 — insert — ambiguity — enum-valued list filters reject out-of-set values with 422 (not an empty page), free-form identifier filters just match nothing, boolean filters accept `true/false` any case plus `1/0`, undeclared query params ignored — validation.py:270-288, support.py:69-75
- §2.4 — insert — **mismatch** — a row created by a request never takes a later-hop version increment in that request: it is read back at `version` 1 with `updated_at == created_at` (§3.9's "each touched plan's version is incremented by 1" would otherwise imply a fresh plan reads version 2 after the create-time allocation run) — store.py:82-97 (`mark_fresh` / `bump` dedupe), routes_services.py:94-100
- §2.4 — insert — ambiguity — a pre-existing row advances `version` by exactly 1 across a whole request however many hops touch it, with the sweep's per-term steps named as the one exception (`force=True` can bump one child once per term moved) — store.py:87-97, flows.py:236-266
- §2.5 — insert — ambiguity — every server start also begins from an entirely empty in-memory store (nothing seeded/persisted) — store.py:1-5,19-35
- §2.5 — insert — ambiguity — `to_iso8601` accepts `T` or space separator, optional seconds/fraction, and `Z` / `±HH:MM` (normalised) / no designator (read as UTC); `current_utc`, `adjudicated_on`, `decided_on` render with exactly three fractional digits and `Z` — validation.py:205-233, store.py:56-61
- §2.6 — insert — ambiguity — hour/credit values are emitted as JSON **numbers** at exact 2-decimal scale (`75.00`, not `"75.00"`, not `75.0`) — envelope.py:41-52,80-83
- §2.8 rung 4 — insert — ambiguity — absent/empty body reads as `{}`; non-JSON or non-object body fails on rung 4; explicit `null` is treated as an absent key (satisfies no required field, displaces no default); integer fields accept `"5"`/`5.0`, decimal fields accept numeric strings; boolean fields require a JSON literal — validation.py:30-46,98-135
- §3.1 — insert — ambiguity — an area amendment supplying only one peak-season date validates the **effective** pair (supplied vs stored) — routes_areas.py:86-92
- §3.1 — insert — ambiguity — an area amendment carrying no writable key is still accepted and still increments `version` — routes_areas.py:94-103
- §3.1 — insert — ambiguity — reading one area recomputes `assigned_primary_slots_used` while serving the read and never touches `version`/`updated_at` — routes_areas.py:70-73, flows.py:21-22
- §3.1 — insert — ambiguity — same for a recruiter read and `active_assignment_count`; recruiter amendment ignores non-writable keys and a keyless amendment still bumps — routes_areas.py:138-141,146-160
- §3.1 — insert — ambiguity — a `SUSPENDED` recruiter still authenticates at rung 1 and may still file interviews, open/correct certificates and decide reviews (suspension gates coverage only) — auth.py:31-38
- §3.2 — insert — ambiguity — an accepted assignment create refreshes the recruiter's `updated_at` but does **not** increment the recruiter's `version` (unlike activate/close) — routes_areas.py:240-241, store.py:100-103
- §4 — insert — ambiguity — paths match with or without a trailing slash — app.py:36
- §5 — insert — ambiguity — two routing-layer identifiers outside the 48-row table: `ERR_NOT_FOUND` (404) for an undefined path and `ERR_METHOD_NOT_ALLOWED` (405) for an unsupported method, both in the standard error envelope — app.py:50-60

Judged already-pinned-and-correct (flagged to later passes so they would not re-open): the §2.4 `created_at`/`updated_at` minting sequence; all 48 `ERROR_CATALOG` ids and statuses vs the §5 table; `has_more` as `(offset + limit) < total_count`; the assignment-create ladder (shape → area 404 → recruiter 404 → 412 → peak season → overlap → recruiter standing → area standing → capacity) and the §3.2 activation/closure state sets and counter effects; envelope shape, UUID ids with no prefix, clock init to `2026-08-01T00:00:00Z`.

### Pass 2 — calculations, cascades, students, certificates (15 ambiguity-pins, 3 mismatch-revisions)

440 lines / 103,293 bytes → 440 lines / 107,745 bytes (+4,452 bytes).

- §3.3 — revise — **mismatch** — the list of triggers that re-persist the PFS assessment wrongly included the continuation sweep; corrected to exactly the five real call sites (student create, student amend, move adjudication, approval cascade, invalidation cascade) — flows.py:210-273 (`run_sweep` never calls `persist_pfs`)
- §3.5 — revise — **mismatch** — certificate create with a move belonging to another child was left unnamed/implied as a not-found or not-qualifying error; pinned to `ERR_INVALID_REQUEST`, raised before the `work_type == "NONE"` check — routes_coes.py:52-56
- §3.9 — revise — **mismatch** — "that is the only sort key" for open plans was false (there is an `id` tie-break), and move adjudication was missing from the allocation-trigger list — calc.py:127, routes_students.py adjudicate
- §2.4 — insert — ambiguity — the "created row never takes a later-hop version increment" rule (`mark_fresh`) now stated for the certificate minted by reidentification and the plan minted by create — store.py:82-97
- §2.6 — insert — ambiguity — `distance_miles` has no upper bound and is rounded half up to two decimals inbound, rendered as a two-decimal JSON number — routes_students.py move create
- §2.7 — insert — ambiguity — `grade_level` is the only field anywhere where an explicit JSON `null` is meaningful (clears the value); everywhere else explicit null is an absent key — routes_students.py:159-160, validation.py:45
- §3.1 — insert — ambiguity — `birth_date` on or after the current logical clock date fails `ERR_INVALID_REQUEST` *before* the area is resolved, so a bad date beats an unknown `area_id` — routes_students.py create_student
- §3.2 — insert — ambiguity — move create does no birth-date/move-date ordering check and writes nothing on the child row — routes_students.py create_move
- §3.2 — insert — ambiguity — interview create resolves student, move and certificate before the move-belongs-to-child `ERR_INVALID_REQUEST` — routes_students.py create_interview
- §3.4 — insert — ambiguity — move adjudication re-persists PFS and bumps the child unconditionally on *both* VERIFY and REJECT — routes_students.py adjudicate_move
- §3.5 — insert — ambiguity — ownership (`ERR_UNAUTHORIZED`) is checked immediately after the certificate is fetched on both correct and submit, ahead of body parsing and the status gate — routes_coes.py:119,150
- §3.5 — insert — ambiguity — correct sets `status` back to `DRAFT` and bumps unconditionally, even from `DRAFT` with no field supplied — routes_coes.py:141-142
- §3.5 — insert — ambiguity — submit, approve, invalidate-selection and QC selection read no request body at all — routes_coes.py:148,211,261
- §3.6 — insert — ambiguity — the decide-review ladder order is pinned (payload/decision consistency → re-interview resolution → already-decided → certificate no longer `QC_SELECTED` → segregation of duties → credential → re-interview linkage), and the response body is the review row — routes_coes.py:330-411
- §3.6 — insert — ambiguity — the FAIL walk-back to `NOT_ELIGIBLE` requires both `PENDING_DETERMINATION` and no `ACTIVE`/`EXPIRING` term — routes_coes.py:401-409
- §3.7 — insert — ambiguity — approval hop three writes `ELIGIBLE` unconditionally rather than guarded on the prior value, and the repaired reidentified term takes a `version` increment — flows.py:140,167
- §3.7 — insert — ambiguity — invalidation hop three is caused by hop two's terminations, so it is skipped entirely when nothing terminated — flows.py:202
- §3.7 — insert — ambiguity — per-branch sweep write conditions: branch 1 writes the child unconditionally (`force=True`, so a child already `TERM_EXPIRED` is written again and still takes the increment); branch 2 writes only a child currently reading `ELIGIBLE` while the term still moves regardless; branch 3 bumps only when re-derivation actually changes `service_status` — flows.py:210-273

Judged already-pinned-and-correct: PFS formulas / `MOVE_BAND` / `_ceil_blocks` / the 13-field assessment payload; provisional vs final window arithmetic incl. the 22-year age-out clip and `age_out_capped`; hour allocation (budget, weights, round-each-share-before-summing, residual on earliest open plan); credit reconciliation's six steps and the cap tier keyed on the *pre-cap* tier; QC pool / `target_n = max(ceil(count/10), 1)` / mandatory ∪ quota union / `selection_reason` / 201 on selection; the three risk-flag indicators and `risk_flag_count` stamped at submit; sweep batch ordering `(term_end_on, created_at, id)` and one-branch-per-term; delivery-ledger aggregates and coverage geometry; submission's five conditions and approval's two entry legs. Two **deliberate non-edits** passed forward: §3.9's "on every closure" claim is vacuously true (cascade closures leave the allocation input set empty) and "service_status re-derived after every plan mutation" is not observably violated — both correct as written, not to be tightened.

### Pass 3 — terms, exchange, services (13 ambiguity-pins, 1 mismatch-revision)

440 lines / 107,745 bytes → 440 lines / 110,723 bytes (+2,978 bytes).

- §2.5 — insert — ambiguity — clock response `data` carries `current_utc` **and no other field** — routes_services.py:314
- §2.5 — insert — ambiguity — instant precision finer than a millisecond is **truncated, not rounded**, when `current_utc`/`adjudicated_on`/`decided_on` are rendered — store.py:59-64
- §2.8 rung 4 — revise — ambiguity — extended the "declares no body fields, never reads the payload" example list with the continuation sweep, transfer receive, transfer reconcile, plan activation and delivery reversal — routes_terms.py:53,230,244; routes_services.py:127,269
- §3.7 reidentification — insert — ambiguity — the four conditions are listed in narrative, not evaluation order; ladder order is `new_move_id` 404 → term state → move verification → residency ordering → grace window — routes_terms.py:62-90
- §3.7 reidentification — insert — ambiguity — the minted `DRAFT` certificate takes the §3.5 creation defaults (`qc_hold_exempt` false, nothing inherited from the superseded term's certificate; counts 0; `invalidation_reason` and all four window fields null) — routes_terms.py:96-114
- §3.7 reidentification — insert — ambiguity — the child's move to `PENDING_DETERMINATION` is **unconditional** (a child reading `ELIGIBLE`/`CONTINUATION` is written too, and always takes the version increment) — routes_terms.py:118-122
- §3.7 reidentification — insert — ambiguity — **any** `Recruiter` may reidentify; no ownership comparison to the originating recruiter — routes_terms.py:58
- §3.8 transfer create — revise — ambiguity — `reported_prior_credits` range-checked as supplied, then rounded half up to two decimals on the way in rather than refused for a third decimal — routes_terms.py:138-155
- §3.8 match — insert — ambiguity — the three guards run in §2.8 ladder order, so an unresolvable `matched_prior_student_id` 404s even after the request has left `INITIATED` — routes_terms.py:195-210
- §3.9 activation — insert — ambiguity — plan-state check outranks the eligibility check, and those two are the **only** guards: the `plan_type`/`schooling_status` gates of the draft step are not re-evaluated at activation — routes_services.py:128-139
- §3.9 closure — insert — ambiguity — `closure_reason` and starting status are independent (a `DRAFT` plan may be closed `COMPLETED`), unlike §3.2 assignment closure — routes_services.py:154-160
- §3.9 delivered sessions — revise — **mismatch** — `credits_awarded` must also be **at least 0.00**: a negative amount is off the grid even though it divides evenly by 0.25 (PRD as written admitted −0.25; impl rejects it with `ERR_INVALID_SERVICE_HOURS`) — routes_services.py:31-38,217
- §3.9 reversal — insert — ambiguity — reversibility is the only gate; the target's plan is not re-examined, so a reversal succeeds against a `SUPERSEDED`/`CLOSED` plan — routes_services.py:270-276
- §3.9 reversal — insert — ambiguity — the reversal record's own `is_reversed` is false and never becomes true, so an `is_reversed=false` filter returns it alongside unreversed forward records — routes_services.py:287

Pass 3's own four final-integrity checks: 440 lines / 110,723 bytes; head is the H1 and tail is the last §5 error row (not truncated); the ordered `^#` heading lists of `PRD_FINALIZED.md` and `PRD_COMPLETED.md` diff empty (26 headings, identical order); `cmp` confirms the files are not byte-identical.

**Orchestrator post-check (independent, per the known "Step 9 never ran" failure mode):** `PRD_COMPLETED.md` is 110,723 bytes vs `PRD_FINALIZED.md`'s 98,721 — `cmp` DIFFERS, so the scan genuinely ran and was not a silent `cp`. `diff` of the `^#` heading lists is empty, so no section was dropped; 37 lines changed relative to `PRD_FINALIZED.md`; the tail still ends on the complete row `| ERR_NO_QC_CANDIDATES | 409 |`. Additionally verified that no Step 8/9 subagent mutated the tested artifacts: `find` for `*.py` newer than `results.1.json` returns nothing under `implementation/`, `test_suite/`, or `test_helpers/` — so the Step 7 evidence of 8×91/91 still describes the code as it stands at pipeline end.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
