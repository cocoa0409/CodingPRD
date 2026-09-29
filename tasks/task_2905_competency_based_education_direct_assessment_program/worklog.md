## Step 1: Create task directory — 2026-09-05T14:32:10.000Z

Created tasks/task_2905_competency_based_education_direct_assessment_program/ and its workspace/ subdirectory. Index 2905 was pre-assigned by the orchestrating invocation (no ./tasks scan performed, per concurrency constraint).

## Step 2: Generate scaffold — 2026-09-05T16:29:17.000Z

All three artifacts are complete, YAML-valid, and the linter is clean.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3028 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1909 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4992 |

## SCAFFOLD.yaml (§1.0–§1.7)
Top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present.

- **14 entities**, **68 endpoints**, **7 roles**
- 12 state machines, 3 §1.2.1 concurrency rules, 13 calculations, 39 validations (contiguous priorities 1–39), 66 errors
- complexity_profile: expert; layers `dual_variant_calculation, rate_threshold_triggers, cascading_side_effects, optimistic_concurrency`; topology flat; state-machine shape cyclic; role_model `segregation_of_duties`; consistency_model `immediate`

## Design files
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 9 rules × 2 instances = 18 instances**
- **SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 86 instances** — 68 full test recipes + 18 `excluded_because` stubs, across `entities` 13, `state_machines` 16, `calculations` 17, `validations` 10, `endpoints` 5, `errors` 12, `rbac` 5, `cross_cutting_layers` 7, `consistency_model` 1. All instance names unique across both design files; every cited `difficulty_instance` resolves.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2905_competency_based_education_direct_assessment_program/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2905_competency_based_education_direct_assessment_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2905_competency_based_education_direct_assessment_program/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  1118

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Two earlier findings — hardcoded `expected_competency_version: 1` and `expected_term_version: 1` in two negative instances — were fixed by adding real parent-create captures so both OCC tokens are now `${var}`.)

## Notes
- **One error was removed to keep §1.6 fully triggerable.** `ERR_ADJUDICATION_NOT_REQUIRED` (with its validation, formerly priority 38) was provably unreachable: `required_evaluator_count` is constrained to `1 | 2`, so a `reader_ordinal` 3 score can only exist once two non-VOIDED scores are present, at which point the attempt is either already resolved (priority 11 `ERR_ATTEMPT_NOT_UNDER_REVIEW` pre-empts) or in ADJUDICATION (rule satisfied). It was deleted, priorities 39/40 renumbered to 38/39, and the two `grounds:` references in the design files updated. Errors went 67 → 66, validations 40 → 39. A trailing YAML ledger in the corner file maps all 66 error ids to the instance that provokes each; nothing is uncovered.
- The `"Generate task harder than expert level!"` directive is kept only in a top-of-file YAML comment marked "meta, NOT part of the product scenario" — it is absent from `scenario:`, so it cannot leak into PRD.md.
- Endpoints (68) and errors (66) deliberately exceed the Expert bands (20–32 / 18–30): lint check (f) requires a scalar read plus a filtered list read per child entity across 14 entities, and 14 of the errors are per-entity 404s.
- No sibling task directory was read, listed, globbed or grepped at any point; every file was built with chunked `cat >>` appends and re-parsed with `yaml.safe_load` after each chunk. No `pkill` was run.

**Orchestrator post-step action:** the scaffold generator left the difficulty directive in a header comment of SCAFFOLD.yaml (line 6-7). Per known leak pathway (the doc generator reads the whole file, comments included), the orchestrator deleted those two comment lines. Verified: `grep -rn "harder than expert"` over the task dir now returns nothing. `scenario:` was already clean.

## Step 3: Copy shared files — 2026-09-05T16:29:22.000Z

Copied INSTRUCTION.md into tasks/task_2905_competency_based_education_direct_assessment_program/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T16:49:29.000Z

PRD generation is complete.

## Output
`workspace/PRD.md` — **573 lines / 132,333 bytes**, built entirely with chunked `cat >>` appends. The file ends cleanly at the last row of the §5 error table (`ERR_AID_CREDIT_EQUIVALENCY_SHORTFALL | 422`), with no truncation and no audit footer.

## Sections actually present (in file order)
1. `# Competency-Based Education & Direct Assessment API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, diff-verified) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Flat Collection Topology and Identifier Resolution · 2.6 Common Resource Properties and Append-Only Audit Rows · 2.7 Numeric Precision, Rounding and Monetary Representation · 2.8 The Program as the Policy Surface · 2.9 Optimistic Concurrency on Parent Records · 2.10 Cascade Discipline and Version Propagation · 2.11 Validation Precedence · 2.12 Conservation Invariants
4. `## 3. Business Logic & Workflows` — 3.1 Competency Map and Prerequisite Graph · 3.2 Assessment Blueprints and the Rubric Window Timeline · 3.3 Enrollment and the Subscription Term · 3.4 Faculty Mentoring: Caseload, Contact Cadence and Endorsements · 3.5 Opening and Submitting an Assessment Attempt · 3.6 Rubric Scoring, Reader Agreement and Evaluator Standing · 3.7 Academic Integrity Casework and Sanctions · 3.8 Mastery, Graduation and Satisfactory Academic Progress · 3.9 Federal Aid, Term Close-Out and Transcript Translation
5. `## 4. Endpoint Definitions` — 4-column table, **68 endpoint rows** (verified: 70 pipe rows = header + separator + 68)
6. `## 5. Error Code Catalogue` — 2-column table, **66 error rows** (68 pipe rows)

## Coverage verification (machine-checked against SCAFFOLD.yaml)
- **Contract 1 — Field-Name Coverage: PASS.** Two independent extraction passes. Pass 2 built the required set directly from the scaffold (all 14 entities' fields + `id`/`created_at`/`updated_at`/`version` for the 13 `common_fields: true` entities, all endpoint request-body inputs and query params with `?` stripped, the 3 OCC fields, the 16 `progress-summary` output keys, plus nested keys `weight`/`max_score`/`critical`/`score`/`code`/`competency_code`/`line_credit_hours`/`items`/`total_count`/`has_more`): **177 required names, 0 missing.**
- **Contract 2 — Rule Coverage: PASS.** All **66** error ids appear in backticks; all **57 transitions across 12 state machines** have every `from`/`to`/initial/terminal state value present in backticks (0 missing); all **39 validations** are enumerated in priority order 1–39 in §2.11 with their error ids and scopes; all **13 calculations** are described in prose (blueprint window resolution §3.2; rubric weighted score, 4-variant final score, IRR §3.6; caseload selector, cadence compliance §3.4; eligibility ladder §3.5; credit-hour equivalency dual variant, SAP pace §3.8; term-close aid return, transcript translation §3.9; both conservation invariants §2.12 + §3.8/§3.9).
- **Contract 3 — §3 Path Purity: PASS.** 1,103 backticked tokens in §3; **0** start with `/`, 0 are bare HTTP methods, 0 combine method+path.
- Style scan: no `approximately`/`roughly`/`conservatively`, no symbolic operators (`==`, `>=`, `IN {`, `round_half_up(`, `floor(`, `min(`), no leaked scaffold rule ids (`calculations.*`) or `logical_now` outside the verbatim §2.2 block.

## Notes
- Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.
- One scaffold enum value, `hold_reason` = `INTEGRITY_REVIEW`, is declared on `AidDisbursement` but produced by no state-machine transition. §3.9 now states the full permitted value set and identifies the two the system raises automatically, without inventing a transition for the third.
- Two documented scaffold inconsistencies were resolved toward the state machine, which is what tests assert: validation 21's `check` text says "status ACTIVE … certification_level is CERTIFIED" (mixing the two fields), so §3.6/§2.11 state it as "not `SUSPENDED` to score, exactly `CERTIFIED` to adjudicate"; and validation 7's `applies_to` list (rather than its prose) was treated as authoritative for scope.
- Resolved losslessly, as before: list envelopes carry `items`/`total_count`/`has_more` inside `data` while the same pagination values also appear in `meta`, satisfying both the scaffold and the fixed §2.2 contract.

**Orchestrator truncation check (per known doc-generator failure mode):** independently verified — 573 lines, 6 top-level headers at lines 1/3/11/221/429/504, and the file's last line is a complete `| \`ERR_AID_CREDIT_EQUIVALENCY_SHORTFALL\` | 422 |` table row. Ends at a real section boundary; no regeneration needed.

## Step 6: Generate implementation — 2026-09-05T17:48:42.000Z

The implementation is complete.

## Files (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 68 |
| `db.py` | 184 |
| `errors.py` | 105 |
| `middleware.py` | 98 |
| `response.py` | 146 |
| `routes/__init__.py` | 0 |
| `routes/aid.py` | 179 |
| `routes/attempts.py` | 456 |
| `routes/catalog.py` | 370 |
| `routes/clock.py` | 34 |
| `routes/integrity.py` | 153 |
| `routes/mentoring.py` | 294 |
| `routes/progress.py` | 81 |
| `routes/students.py` | 274 |
| `routes/transcripts.py` | 95 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 259 |
| `services/cascade.py` | 236 |
| `services/derive.py` | 345 |
| `services/lookup.py` | 173 |
| `services/nums.py` | 77 |
| `services/serialize.py` | 348 |
| `services/shape.py` | 176 |
| **total** | **4151** |

Plus `start.sh` (executable, 427 B) and `requirements.txt` (`flask>=2.0`). Every `.py` passes `py_compile`; `__pycache__` cleaned.

## Endpoints

**68 registered**, matching the PRD's §4 table exactly: 2 clock (`GET /_clock`, `POST /_clock/set_current_utc`) + 4 programs + 5 competencies + 3 blueprints + 8 students/progress-summary + 5 subscription-terms + 4 mentors + 6 mentor-assignments + 4 evaluators + 2 evaluator-scores + 7 assessment-attempts (incl. `/scores`) + 5 integrity-cases + 3 sap-reviews + 6 aid-disbursements + 4 transcript-records.

## Boot + smoke confirmation

Booted with a fresh `bash start.sh` on **PORT=22742** (last of several runs on random ports in 21000–22999, each recorded in `/tmp/task_2905_implgen/smoke_port.txt`). Each time I resolved the listening PID via `ss -ltnp` on my own port and killed **only that PID** (`kill 181103` for the final run; verified the port went free and ~40 other pipelines' `python3 app.py` processes were untouched). No `pkill` was ever used.

Two smoke suites against fresh processes, both fully green:
- Suite 1 (34 checks): empty store on boot (`total_count == 0` for programs and students), clock at `2026-08-01T00:00:00.000Z`, envelope/`req_` id, 401 on blank headers, program→competency→publish→blueprint→student→term→mentor(auto-select)→evaluator→attempt→submit→single-reader score (`weighted_score_pct` 86.00 on 0.6/0.4 weights), mastery cascade (units 6.00, `cumulative_credit_equivalency` 2.0), progress summary variance, aid schedule/disburse (`credit_equivalency_at_disbursement` 2), SAP review (append-only: no `version`/`updated_at`), transcript build + issue, clock move, term close (`attended_days` 45, `earned_pct` 0.5), aid return (unearned 100000 / school 75000 / student 25000) and the §2.12 ledger identity (retained 125000, outstanding 0, cancelled 0), 404 on unknown route.
- Suite 2 (46 checks): prerequisite edge, two-reader flow (`PROVISIONAL_SINGLE_READER` → disagreement → `ADJUDICATION` with `final_score_pct` cleared → ordinal-3 `ADJUDICATED` = adjudicator alone), IRR recompute (0.00 over 1 pair, no demotion), evaluator suspension terminality, revision loop (score void, counters reset) + reopen, integrity case open/investigate/`ERR_CASE_RESOLVER_IS_OPENER` (422)/substantiated `ATTEMPT_VOID` with the 4-hop reversal (units back to 0, strike 1, IRR denominator back to 0 pairs / 100.00), aid cancel, suspend/reinstate/withdraw with the withdrawal sweep (term CANCELLED, assignment ENDED), retire guard, list filters and pagination bounds.

Storage is in-memory only: the sole `json.dumps` in the codebase is response serialization; there is no file, sqlite, pickle or `/tmp` I/O anywhere, and nothing is seeded at import or boot.

Four PRD-vs-scaffold conflicts were resolved in the PRD's favour and are worth flagging for the test suite: term close holds SCHEDULED awards (`TERM_CLOSED`) but does **not** auto-return DISBURSED ones (otherwise `POST /aid-disbursements/{id}/return` is unreachable); evaluator `status` is CERTIFIED/PROVISIONAL/SUSPENDED (scaffold rule 21's "ACTIVE" is a scaffold error); `request-revision` is accepted from both UNDER_REVIEW and ADJUDICATION; and a PENDING term may only be closed as CANCELLED.

## Step 5: Generate unit tests — 2026-09-05T18:18:41.000Z

All queue-A and queue-B work is complete. Final audits are green.

## Output location (both at the task root, no strays under `workspace/`)

### `test_helpers/` — 2,429 lines
| file | lines |
|---|---|
| `__init__.py` | 46 |
| `api_client.py` | 361 |
| `api_errors.py` | 147 |
| `assertions.py` | 426 |
| `constants.py` | 82 |
| `factories.py` | 205 |
| `fixtures.py` | 551 |
| `test_users.py` | 86 |
| `types.py` | 525 |

### `test_suite/` — 5,535 lines, **152 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 51 | – |
| `test_01_score_variants_and_credit_translation.py` | 158 | 4 |
| `test_02_rubric_and_close_out_arithmetic.py` | 149 | 4 |
| `test_03_student_axes_and_attempt_cycles.py` | 158 | 4 |
| `test_04_mastery_and_integrity_cascades.py` | 223 | 4 |
| `test_05_validation_precedence_pairs.py` | 150 | 4 |
| `test_06_boundaries_and_empty_collections.py` | 162 | 4 |
| `test_07_cross_entity_preconditions.py` | 162 | 4 |
| `test_08_temporal_window_tiling.py` | 234 | 6 |
| `test_09_conservation_invariants.py` | 223 | 4 |
| `test_10_entity_shapes_and_references.py` | 410 | 13 |
| `test_11_lifecycle_transitions.py` | 693 | 20 |
| `test_12_derived_calculations.py` | 492 | 13 |
| `test_13_validation_rules.py` | 407 | 11 |
| `test_14_endpoint_contracts.py` | 268 | 9 |
| `test_15_error_catalog.py` | 772 | 24 |
| `test_16_role_authorization.py` | 497 | 11 |
| `test_17_cross_cutting_layers.py` | 526 | 13 |

## Queue split and design coverage
- **Queue A (Difficulty): 38 tests** covering **18/18** non-stub instances (that file has no stubs).
- **Queue B (Corner): 114 tests** covering **68/68** non-stub instances — entities 13, state_machines 13, calculations 8, validations 7, endpoints 5, errors 12, rbac 4, cross_cutting_layers 5, consistency_model 1.
- 86 distinct design instances tagged; every docstring ends in exactly one `Design:` line, every tag resolves to a real instance in the right section, and **none of the 18 `excluded_because:` stubs was translated** (verified mechanically by `/tmp/task_2905_teststgen/verify_tags.py`).
- Every `PRD: "…"` quote is a whitespace-normalised verbatim substring of `workspace/PRD.md` (`/tmp/task_2905_teststgen/verify_quotes.py`: 152 tests scanned, 0 problems).
- `python3 -m compileall` clean; `pytest --collect-only` collects all 152 with no import errors (`__pycache__`/`.pytest_cache` removed afterwards).

## Instances SKIPPED
**None.** Every non-stub instance in both indices passed the two-condition PRD filter and is translated.

Six instances were **narrowed** (assertion pulled back to what the PRD uniquely derives), rather than skipped:
1. `Corner/calculations/aid_cents_conservation_on_return` — the design implies aid auto-returns on term close, but PRD only moves a scheduled award to `HELD` on close and makes the return an explicit endpoint; the test closes the term `LAPSED` and then calls the return endpoint.
2. `Difficulty/…/term_close_refund_evaluation_order` (test_02) — refund-tier ordering asserted only where the PRD states the sequence.
3. `Difficulty/…/aid_disburse_requires_student_sap_state` (test_07) — SAP gate asserted at release, not at scheduling (PRD puts it only on release).
4. `Corner/…/competencies_list_filtered_by_program_and_status` — design says `created_at` ASC, PRD §2.3 pins competencies to `code` ASC; codes chosen so the two orders coincide, and the PRD rule is the one asserted.
5. `Corner/errors/blank_identity_headers_are_unauthenticated_before_role_check` — the design's whitespace-only `X-User-ID` is untransmittable (`requests` raises `InvalidHeader`); used `""` and no-header variants, both of which PRD line 17 treats as absent.
6. `Corner/consistency_model/cross_aggregate_derivations_are_visible_in_the_next_read` — the design asserts `credit_equivalency_variance == 1.3`, but the PRD derives it as `cumulative_credit_equivalency − aid_credit_equivalency_sum` = `1.3 − 1 = 0.3`; the test asserts the PRD identity (via `assert_credit_equivalency_variance`) plus `aid_credit_equivalency_sum == 1`. **This is a genuine design-vs-PRD arithmetic discrepancy worth flagging to Step 7** — if the implementation returns 1.3 there, the implementation is wrong, not the test.

**Orchestrator note:** verified independently that `test_helpers/` and `test_suite/` are at the task root and that no stray copies exist under `workspace/`. Steps 5 and 6 were launched concurrently in a single message, so the implementation generator could not see `test_suite/`.

## Step 7: Run tests and iterate — 2026-09-05T18:51:39.000Z

All 8 rounds are green: **152/152 in every round**.

## Summary

**Iterations run:** 1 diagnostic iteration (initial 8-round sweep → 146/152 in all 8 rounds, 6 deterministic failures), plus 2 targeted single-round verifications, then a confirming full 8-round sweep.

**Tests deleted:** none. All 6 failures were test-artifact bugs (STEP 2), not PRD-silence, and no implementation defect was found. `workspace/implementation/` was not modified at all.

**Fixes applied to `test_helpers/`:** none — the fixture layer was already PRD-faithful (money as integers, full ISO-8601 instants, entity-backed identities threaded correctly, `credit_equivalency_variance` derived from the response rather than hardcoded, so the generator's handover lead about 1.3 vs 0.3 was a false alarm).

**Fixes applied to `test_suite/`** (all making the test more faithful to PRD):

- `test_11_lifecycle_transitions.py::test_publishing_a_draft_program_stamps_the_clock_and_recounts_the_map` — asserted `version == 2` after publish, ignoring PRD §3.1 "Creation also increments the owning program's `competency_count` and its `version`"; now captures the draft's version after the map build and asserts exactly +1.
- `test_11_lifecycle_transitions.py::test_publishing_an_already_published_program_neither_restamps_nor_bumps` — same stale baseline; now asserts the refused second publication leaves the version the first publication produced.
- `test_15_error_catalog.py::test_the_officer_who_opened_the_case_may_not_also_resolve_it` — resolved as `officer-1` while the case was opened by `officer-open`, so the PRD-faithful server correctly *allowed* it; now resolves under `make_integrity_officer_headers("officer-open")` so the segregation-of-duties rule is actually the rule under test.
- `test_16_role_authorization.py::_seven_role_world` (feeds 2 failing tests) — enrolled the student *before* publishing the program, which PRD precedence rule 7 refuses with `ERR_PROGRAM_NOT_PUBLISHED`; enrollment moved after publication. Same helper also handed a stale `term` to `schedule_aid` (opening and submitting the attempt each increment the term's version), producing `ERR_STALE_VERSION`; the term is now re-read before return.
- `test_16_role_authorization.py::test_the_assessment_spine_admits_each_of_its_five_declared_holders` — asserted a response-visible `outcome` field on the integrity case, which the PRD declares only as a resolve-payload input and never as a case attribute (the PRD's own enumeration of case fields omits it); replaced with the verbatim-covered `resolved_by_user_id` / `resolved_at_utc` assertions.
- `test_16_role_authorization.py::_a_draft_program_beside_a_certified_reader` / `test_the_role_refusal_lands_before_the_nonsense_in_the_body_is_ever_read` — asserted the draft program was at `version == 1`, again ignoring the competency-creation bump; the helper now returns the refreshed draft and the test asserts the refusals left that version untouched.

**Final per-round results:** rounds 1–8 all `152 / 152` (0 failed, 0 errors). `worklog.md` untouched; scratch verification suite removed.

**Orchestrator verification of sweep artifacts:** independently confirmed, not taken on faith — all 8 `workspace/implementation/results.$i.json` exist (written 18:45 UTC, ~48 KB each) and each parses to `passed=152, failed=0, errors=0, total=152`.

## Step 8: Finalize PRD — 2026-09-05T18:57:19.000Z

`PRD_FINALIZED.md` is written at `workspace/PRD_FINALIZED.md`.

## Size
- PRD.md: 573 lines / 132,333 bytes. PRD_FINALIZED.md: 573 lines / 133,217 bytes.
- Line-count delta: 0% (all edits are inline inside existing very-long lines). Byte delta: +0.67%. Section count unchanged (26), no new sections.

## Changes (4 edits)

- **§3.7 (case resolution)** — insert — resolution writes the supplied `outcome` into the case's own `status`, so a resolved case reads `SUBSTANTIATED`/`DISMISSED`, and `outcome` is not a separate case field — `implementation/routes/integrity.py:119` + `services/serialize.py:229-244`
- **§3.7 (`TERM_SUSPENSION` sanction)** — revise — replaced "runs the full close-out arithmetic of §3.9 **including the aid return split**" (which the impl does not do) with: close-out arithmetic on the term itself + the same aid treatment as any `CANCELLED` close from `ACTIVE` (`SCHEDULED`→`HELD`/`TERM_CLOSED`, already-`DISBURSED` untouched, return being a separate explicit operation) — `implementation/services/cascade.py:156-174`, `routes/aid.py:140-168`
- **§3.3 (pending-term close path)** — insert — `CANCELLED` is the only outcome a `PENDING` term may be closed with; `COMPLETED`/`LAPSED` against a pending term is refused with `ERR_TERM_NOT_ACTIVE` — `implementation/routes/students.py:259-263`
- **§3.5 (attempt creation)** — insert — attempt creation also increments the owning term's and the pinned blueprint's `version` — `implementation/routes/attempts.py:138-139`

## Per-edit pre-edit search log

**Edit 1 — case resolved status**
(a) Subject: integrity-case `status` value space and the presence/absence of an `outcome` attribute.
(b) Paths enumerated: `routes/integrity.py` `open_case` (status `OPEN`), `investigate_case` (`OPEN`→`UNDER_INVESTIGATION`, else `ERR_CASE_ALREADY_RESOLVED`), `resolve_case` (`RESOLVED_STATUSES=("SUBSTANTIATED","DISMISSED")` gate, then `case["status"]=outcome`), `list_cases` status filter (raw string compare); `routes/attempts.py:272-287` auto-raised case (status `OPEN`); `services/serialize.py:integrity_case` (no `outcome` key); `services/derive.py:11 LIVE_CASE_STATUSES=("OPEN","UNDER_INVESTIGATION")` and its four consumers (`attempt_has_live_case`, `student_has_live_case`, `open_case_count`, reinstate/transcript gates).
(c) Adjustment: phrased as "the case's own `status` becomes the supplied `outcome`" rather than naming a new terminal enum, so the `LIVE_CASE_STATUSES`-driven hold logic (which only cares about `OPEN`/`UNDER_INVESTIGATION`) stays correctly described.

**Edit 2 — `TERM_SUSPENSION` / term-close aid treatment**
(a) Subject: what a term close does to each aid-award status.
(b) Paths enumerated: `cascade.close_term` (only `SCHEDULED`→`hold_award(TERM_CLOSED)`; no touch of `HELD`, `DISBURSED`, `RETURNED`, `CANCELLED`), `cascade.cancel_pending_term` (`SCHEDULED`/`HELD`→`cancel_award`), `cascade.withdraw_student` (close active terms + `cancel_award` on `SCHEDULED`/`HELD`), `cascade.after_mastery` (graduation → `close_term(COMPLETED)`), `cascade.aid_equivalency_sweep` (void cascade only: `SCHEDULED`→`HELD`/`CREDIT_EQUIVALENCY_SHORTFALL`, `DISBURSED`→`aid_review_required`), `routes/aid.py return_aid` (the only writer of `unearned_aid_cents`/`school_return_share_cents`/`student_return_share_cents`), `routes/students.py close_term_route`, `services/calc.return_figures`.
(c) Adjustment: anchored the `SCHEDULED`→`HELD` clause to "any `CANCELLED` close from `ACTIVE`" so it does not falsely cover `cancel_pending_term` (which cancels rather than holds); said "an award already `DISBURSED` is left exactly as it stands" without asserting anything about already-`HELD` awards (which keep an earlier `CREDIT_EQUIVALENCY_SHORTFALL` reason); scoped "no term close performs it" to the return operation, leaving the void cascade's `aid_review_required` flagging in §3.7 untouched.

**Edit 3 — pending-term close outcome restriction**
(a) Subject: gating order and error code on `POST /subscription-terms/{id}/close`.
(b) Paths enumerated: `routes/students.py:251-274` (`shape.req_enum(outcome, COMPLETED/LAPSED/CANCELLED)` and `req_instant` run *before* the status branch; `PENDING`+non-`CANCELLED`→`ERR_TERM_NOT_ACTIVE`; `PENDING`+`CANCELLED`→`cancel_pending_term`; non-`ACTIVE`→`ERR_TERM_NOT_ACTIVE`; `effective_utc` bound checks only on the `ACTIVE` branch), `services/shape.req_enum` (undeclared enum → `ERR_INVALID_REQUEST`), and all internal closers (`derive.active_terms` filters `status=="ACTIVE"`, so withdrawal, graduation and `TERM_SUSPENSION` never close a `PENDING` term).
(c) Adjustment: named only `COMPLETED`/`LAPSED` as the refused outcomes, so an undeclared outcome string still correctly falls to `ERR_INVALID_REQUEST` via the earlier shape gate; said nothing about closing an already-terminal term (out of Step 7 scope).

**Edit 4 — term/blueprint version on attempt creation**
(a) Subject: which rows the attempt lifecycle mutates, and their `version`.
(b) Paths enumerated: every `touch(term…)`/`touch(blueprint…)` callsite in the tree — `routes/attempts.py:138-139` (create: term + blueprint), `:268` (clean submit: term; the `INTEGRITY_HOLD` branch does *not* touch the term), reopen/`request_revision` (no term touch), `routes/aid.py:70`, `routes/students.py:247`, `cascade.py:105,168,185,202`, `catalog.py:128,186,256,259,347`; plus `db.touch` (updated_at + version+1) and `db.new_row` (version 1).
(c) Adjustment: worded as an additive consequence of the two recomputations already stated ("because each of those is a mutation of the row concerned") rather than an exhaustive list of what attempt creation touches, so the endorsement-consuming `touch(assignment)` on the same path is not excluded, and the `INTEGRITY_HOLD` submit branch's lack of a term bump is not contradicted.

## Items deliberately not patched (already uniquely determined by PRD.md)
- Program `version` +1 on publish and on competency creation (§3.1 states both verbatim); refused second publication mutates nothing.
- Enrollment before publication → `ERR_PROGRAM_NOT_PUBLISHED` (§2.11 rule 7).
- Term `version` +1 on submission (§3.5 states it verbatim).
- Resolver ≠ opener → `ERR_CASE_RESOLVER_IS_OPENER` (§2.11 rule 19, §3.7).
- Evaluator standing enum `CERTIFIED`/`PROVISIONAL`/`SUSPENDED` with no `ACTIVE` member (§3.6).
- `request-revision` accepted from both `UNDER_REVIEW` and `ADJUDICATION` (§2.11 rule 11, §3.6, §4).
- `credit_equivalency_variance` formula (§3.8) matches `serialize.progress_summary:340`.

**Orchestrator verification:** PRD_FINALIZED.md exists at 573 lines / 133,217 bytes, is NOT byte-identical to PRD.md (+884 bytes of inline edits), and still ends at the final error-table row.

## Step 9: Complete PRD — 2026-09-05T19:27:40.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from copying, and each was given the prior passes' hand-off notes so they would not re-edit the same sentences). Partitioning was by implementation module, not by PRD section, so no pass had to hold the whole 4,151-line codebase in context.

Totals: **PRD_FINALIZED.md 573 lines / 133,217 chars → PRD_COMPLETED.md 582 lines / 155,822 chars** (+22,605 chars, +9 lines). **66 changes: 50 ambiguity-pins, 16 mismatch-revisions.** No new sections (29 headings), all 66 error rows and all 68 endpoint rows intact.

### Pass 1 — app/db/errors/middleware/response, shape/nums/lookup, clock, catalog, students
574 lines / 140,186 chars at exit. 23 edits: 21 ambiguity-pins, 2 mismatch-revisions.
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `response.py:30,34`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time, so it repeats until the clock moves — `response.py:55`
- §2.3 — insert — ambiguity — blank/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; `offset` unbounded above, past-end yields empty page — `response.py:102-119,132`
- §2.3 — insert — ambiguity — list filters are exact-equality, blank filter value treated as absent, unmatched/invalid enum value yields empty page not an error — `catalog.py:30-35`, `students.py:36-41`
- §2.3 — insert — ambiguity — universal tie-break: ties on any ordering key fall back to `created_at` asc then creation sequence (load-bearing because the frozen clock makes many rows share `created_at`) — `db.py:142-155`
- §2.4 — insert — ambiguity — both clock endpoints return 200 with a `data` object whose only member is `current_utc`, and carry no `id`/`created_at`/`updated_at`/`version` — `clock.py:28,34`
- §2.4 — revise — **mismatch** — instant parsing is tolerant on input (any fractional width, `Z`/`z`/numeric offset, missing zone read as UTC, normalised to UTC); output is exactly 3 digits with finer precision **truncated**; only unparseable/blank/non-string rejected — `db.py:65-94`
- §2.5 — insert — ambiguity — undeclared path → `ERR_INVALID_REQUEST` at HTTP 404, undeclared method → `ERR_INVALID_REQUEST` at HTTP 405, trailing slash accepted — `app.py:31,40-51`
- §2.7 — insert — ambiguity — `sap_min_units_per_term` and `required_unit_total` have no fixed scale; echoed at the supplied precision — `catalog.py:48-52`, `serialize.py:22-23`
- §2.8 — insert — ambiguity — null policy value = omitted; bound violations → `ERR_INVALID_REQUEST`; the six count/day/hour policies must be integers — `catalog.py:40-76`, `shape.py:52-77`
- §2.8 — insert — ambiguity — `irr_tolerance_pct` carries no upper bound, unlike the other percentage policies — `catalog.py:53-54`
- §2.11 r6 — insert — ambiguity — required strings trimmed before length/uniqueness; uniqueness exact and case-sensitive with three separate `email` namespaces; `email` not pattern-checked; absent/empty body = `{}`, non-JSON or non-object body → `ERR_INVALID_REQUEST` — `shape.py:15-27`, `response.py:137-146`
- §3.1 — insert — ambiguity — publishing a program with no active competency → `ERR_INVALID_REQUEST`; draft check precedes it — `catalog.py:119-125`
- §3.1 — revise — **mismatch** — `mastered_by_student_count` counts mastered non-provisional attempts (PRD said "non-voided") — `derive.py:78-88`
- §3.1 — insert — ambiguity — omitting `prerequisite_competency_id` clears the edge exactly as null does — `catalog.py:222`, `shape.py:165-168`
- §3.1 — insert — ambiguity — retirement's three preconditions run in the stated order; only the first yields `ERR_COMPETENCY_RETIRED`, the other two `ERR_INVALID_REQUEST` — `catalog.py:238-249`
- §3.2 — insert — ambiguity — `critical` defaults false; weights rounded half up to 4 places **before** the sum-to-one test; blank/missing `code` and bad `max_score` → `ERR_RUBRIC_WEIGHTS_INVALID`, while absent/null/non-array `dimensions`, non-object element, non-boolean `critical` → `ERR_INVALID_REQUEST` — `catalog.py:265-307`
- §3.2 — insert — ambiguity — `required_evaluator_count` other than 1 or 2 → `ERR_INVALID_REQUEST` — `catalog.py:317-319`
- §3.3 — insert — ambiguity — activation evaluates the applicant check before the program-published check — `students.py:104-108`
- §3.3 — insert — ambiguity — suspension needs a non-empty `reason`; an `APPLICANT` or already-`SUSPENDED` student → `ERR_STUDENT_NOT_ACTIVE` — `students.py:134-138`
- §3.3 — insert — ambiguity — reinstatement blocked by a live case yields `ERR_INTEGRITY_HOLD_ACTIVE` (not listed in §2.11 rule 18), after the suspended-status check — `students.py:121-123`
- §3.3 — insert — ambiguity — withdrawal's `effective_utc` bound violations → `ERR_INVALID_REQUEST`, checked after the status checks — `students.py:150-159`
- §3.3 — insert — ambiguity — a second concurrently `ACTIVE` term at activation → `ERR_TERM_WINDOW_OVERLAP` — `students.py:240-244`
- §3.3 — insert — ambiguity — closing an already-closed term → `ERR_TERM_NOT_ACTIVE`; the `ACTIVE` path's `effective_utc` bounds → `ERR_INVALID_REQUEST` after the status check; the `PENDING`→`CANCELLED` path does not bound-check `effective_utc` at all — `students.py:259-273`

### Pass 2 — attempts, mentoring, integrity, derive
582 lines / 151,648 chars at exit. 30 edits: 21 ambiguity-pins, 9 mismatch-revisions.
Mismatch-revisions:
- §2.1 — revise — ownership list said "nine operations" and omitted attempt reopening, which impl does enforce — `routes/attempts.py:179`
- §2.3 — revise — the blanket "descending is the exact reverse of ascending" is false for mentor assignments: `sort_rows` stable-sorts descending over an ascending base, so `assigned_at_utc` ties stay earliest-created first — `db.py:149`, `routes/mentoring.py:168`
- §2.11 rule 3 — revise — ownership was pinned strictly before path resolution, but every path-addressed ownership check resolves the row first and reports its 404 — `routes/attempts.py:146-147`, `routes/mentoring.py:175-176`
- §2.11 rule 18 — revise — rule conjoined student-level and attempt-level hold checks for all four ops; impl uses student-level for creation/aid-release/reinstatement and attempt-level only for submit/score — `services/derive.py:145-151`
- §2.11 closing — insert — the numeric precedence contradicted §3.5's ladder; pinned attempt creation's real sequence: 7, 8, 9, 10, then 28, 27, 29, 30, 37, 34, 18 — `routes/attempts.py:62-111`
- §3.5 — revise — `ERR_TERM_NOT_ACTIVE` is settled before rung one, with the blueprint lookup between rungs two and three — `routes/attempts.py:68-88`
- §3.5 — revise — submit order is ownership → not-voided → `DRAFT` → term → attestation → hold; absent/null attestation is `ERR_INVALID_REQUEST`, present-but-wrong is `ERR_ATTESTATION_REQUIRED` — `routes/attempts.py:239-259`
- §3.6 — revise — scoring gates run COI → slot → standing → code set, matching §2.11 rules 19/20/21 — `routes/attempts.py:336-366`
- §3.7 — revise — `TERM_SUSPENSION` closes every `ACTIVE` term regardless of the clock, not "the student's `ACTIVE` term" — `routes/integrity.py:143-145`, `services/derive.py:214`

Ambiguity-pins: mentor status transitions unrestricted and self-transitions allowed with a `version` bump (`mentoring.py:79-87`); explicit `cadence_days` integer ≥ 1 (`:102`); a named mentor's caseload measured before supersession (`:108-121`); contact `note` validated then discarded (`:178`); mentee outside `ACTIVE`/`SUSPENDED` → `ERR_STUDENT_NOT_ACTIVE` (`:182-184`); endorsement's three preconditions, codes and order, with a consumed endorsement re-issuable (`:201-209`); cross-program attempts permitted, publication checked on the competency's program while policy constants read from the student's (`attempts.py:61-71`); cool-off anchored on the most recent failed attempt by creation instant, not `scored_at_utc` (`:92`); endorsement consumed is the oldest unconsumed for the pair across all assignments, bumping that assignment's `version` (`:33-44,133-136`); shared-device window inclusive at both ends, measured from the other attempt's `submitted_at_utc` (`:218-224`); the integrity-hold submit branch does not bump the term's `version` (`:265-289`); attempt list is not ownership-scoped (`:151-172`); COI gate skipped when the reader's `mentor_id` is null (`:336`); slot gate counts only non-voided scores (`:346-356`); out-of-range dimension score is `ERR_INVALID_REQUEST` after the code-set gate (`:372-375`); array shape rules run at §2.11 step 6 (`:294-311`); `reader_ordinal` 3 decided by `ADJUDICATION`, not score count (`:349-356`); `submitted_score_count` is a live count so voiding decrements it (`derive.py:258-261`); IRR tolerance drawn per-pair from that attempt's own student's program (`:285-288`); demotion test runs only after a slot-1/2 score on a two-reader blueprint, a revision request, or an integrity void (`attempts.py:396-397,427-428`, `integrity.py:141-142`); revision `reason` required but not persisted (`:408`); opening a case bumps the attempt's `version` on the flag-only branch too and a second case preserves the first `held_from_status` (`integrity.py:58-61`); investigating an already-`UNDER_INVESTIGATION` case also reports `ERR_CASE_ALREADY_RESOLVED` (`:96-97`); resolution bumps the attempt's `version` whether or not a restoration moved its status (`:135`); a voided attempt freezes its `attempt_number` and reports `integrity_hold` false unconditionally (`derive.py:310-313,334-336`).

### Pass 3 — aid, progress, transcripts, calc, cascade, serialize
582 lines / 155,822 chars at exit. 13 changes: 8 ambiguity-pins, 5 mismatch-revisions.
- §2.1 ¶27 — revise — mismatch — added the two ownership-scoped operations pass 2 flagged: reading a single aid disbursement and building a transcript record — `routes/aid.py:78`, `routes/transcripts.py:33`
- §3.8 ¶394 — insert — ambiguity — progress summary is a computed projection carrying exactly the 16 named fields and none of §2.6's four common properties — `services/serialize.py:330-348`
- §3.8 ¶396 — insert — ambiguity — the reviewed `term_id` is consumed only as the `term_start_utc` cut-off and is not required to belong to the named student — `routes/progress.py:35`, `services/calc.py:188-192`
- §3.8 ¶398 — insert — ambiguity — `pace_pct` divides the unrounded unit total by the unrounded product (single rounding); `expected_units` and `cumulative_mastered_units` each at 2 decimals — `services/calc.py:193-204`, `services/serialize.py:254-256`
- §3.8 ¶404 — revise — mismatch — SAP reviews are also listable by `pace_band` — `routes/progress.py:71`
- §3.9 ¶408 — insert — ambiguity — `term_id` must belong to the named student, else `ERR_INVALID_REQUEST`, examined inside the body-shape step and therefore ahead of the enrollment gate and the version compare — `routes/aid.py:38-40`
- §3.9 ¶410 — insert — mismatch — the release gate list is by subject, not precedence: `ERR_STUDENT_NOT_ACTIVE` first (the paragraph omitted this gate entirely), then term status, then award status — `routes/aid.py:110-124`
- §3.9 ¶414 — revise — mismatch — each `hold_reason` has exactly one producer: `CREDIT_EQUIVALENCY_SHORTFALL` only from §3.7 hop four, `TERM_CLOSED` only from a close-from-`ACTIVE` which never consults the equivalency figure; an already-`HELD` award survives a close untouched; `INTEGRITY_REVIEW` is never produced — `services/cascade.py:52-67,172-174`
- §3.9 ¶414 — revise — ambiguity — only a `CREDIT_EQUIVALENCY_SHORTFALL` hold is really recoverable, since release still demands an `ACTIVE` term — `routes/aid.py:112`
- §3.9 ¶416 — insert — ambiguity — cancel's `reason` is validated as a string then discarded, and the award is the only row mutated — `routes/aid.py:175`, `services/cascade.py:32-39`
- §3.9 ¶424 — insert — ambiguity — both term-side return preconditions report `ERR_INVALID_REQUEST` and are checked after the award's `DISBURSED` status; no enrollment-status precondition — `routes/aid.py:144-154`
- §3.9 ¶428 — insert — ambiguity — `issued_at_utc`/`voided_reason` begin null; `ISSUED` records are not superseded; a `Student` omitting `student_id` gets `ERR_INVALID_REQUEST` because `raw_id` skips the ownership check on a blank value — `routes/transcripts.py:31-33,43-49`
- §3.9 ¶430 — insert — ambiguity — line `unit_value` and `total_mastered_units` at 2 decimals; every transcript figure is frozen at creation and never recomputed at read, so §2.10 does not reach inside it — `services/calc.py:229-246`, `services/serialize.py:288-310`
- §3.7 ¶376 — insert — ambiguity — the aid sweep skips an award whose `aid_review_required` is already true, so its `version` does not move a second time — `services/cascade.py:65-67`

Verified clean by pass 3 with no change needed: `calc.py`'s scoring math (weighted accumulation order, critical-fail from raw ratios, all four `score_variant` branches, IRR demotion's dual condition), mentor auto-selection ranking, the `COMPLETED`-branch earned-percentage shortcut, the `PENDING`→`CANCELLED` figures, and `serialize.disbursement`/`serialize.transcript` key sets — all already pinned by §3.3/§3.4/§3.6/§3.9.

**Orchestrator final verification:** `workspace/PRD_COMPLETED.md` is 582 lines / 155,822 chars, is NOT byte-identical to PRD_FINALIZED.md (+22,605 chars), retains 66 error rows / 68 endpoint rows / 29 headings, and ends at the final error-table row. Step 9 ran as three real passes over one file with no pass overwriting another.

---

## Pipeline complete

All nine steps finished. Final state: 152 tests, all passing in 8/8 concurrent sweep rounds (`workspace/implementation/results.1..8.json`, each `152/152`), with `PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md` all present in `workspace/`.

