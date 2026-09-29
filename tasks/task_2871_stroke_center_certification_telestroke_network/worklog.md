# Worklog — task_2871_stroke_center_certification_telestroke_network

## Step 1: Create task directory — 2026-09-05T09:41:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2871_stroke_center_certification_telestroke_network` and its `workspace/` subdirectory. Index 2871 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate Scaffold — 2026-09-05T12:48:00.000Z

All three scaffold files for task 2871 are complete and lint-clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2871_stroke_center_certification_telestroke_network/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3,832 | 210,293 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 4,530 | 202,624 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 17,172 | 684,173 |

Top-level keys verified: `SCAFFOLD.yaml` carries only §1.0–§1.7 (`scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`) with **no** `scaffold_difficulty_design`/`scaffold_corner_design` keys; the other two files each have exactly one top-level key.

## SCAFFOLD.yaml counts
10 entities · 63 endpoints · 10 state machines · 13 calculations · 46 validation rules (priorities 1–80) · 59 error ids · 2 concurrency rules · 6 roles. Profile: `compliance_audit` / `workflow_orchestration`, layers `[selector_policy, optimistic_concurrency, dual_variant_calculation, cascading_side_effects, rate_threshold_triggers]`, `role_model: segregation_of_duties`, `consistency_model: immediate`, `difficulty_level: expert_plus`. Scenario text is the verbatim 695-char brief (it still contains the leading `Generate task harder than expert level!` line, as instructed — strip it in post-processing if the orchestrator does not want that reaching PRD.md).

## SCAFFOLD_DIFFICULTY_DESIGN.yaml
9 rule ids × 2 instances = 18: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## SCAFFOLD_CORNER_DESIGN.yaml
List of 9 groups, 110 instances (87 with full `test_recipe`, 23 stubs deferring to a named §1.8 instance): `entities` 12 · `state_machines` 15 · `calculations` 17 · `validations` 38 · `endpoints` 9 · `errors` 5 · `rbac` 6 · `cross_cutting_complexity_layers` 6 · `consistency_model` 2.

## Verification
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(2,992 calls scanned across 18 §1.8 + 87 §1.9 recipes.) Three earlier violations were fixed: two captures of a non-existent `StrokeCenter.last_readiness_attested_at` (→ `updated_at`/`version`, asserts reworded) and one `CodeStrokeCase.activated_at` (→ `activation_at`).

Extra checks beyond the linter: all 110 instance names unique and disjoint from the 18 difficulty-design names; every stub cites an existing `difficulty_instance` and carries no `test_recipe`; a custom scan found **0** unbound `${var}` references across all recipe calls and asserts. Domain facts re-derived from SCAFFOLD.yaml while writing the last sections (and used to correct drafts): close from `ELIGIBILITY_DETERMINED` requires an INELIGIBLE determination; deviation field is `opened_by_user_id`; one readiness flag false → `DEGRADED` (not `OFFLINE`); report create itself increments `StrokeCenter.version`; `open_case_count` = own active cases + ACCEPTED inbound transfers with `OPEN_CASE_DIVERT_THRESHOLD` 3 inclusive.

`worklog.md` was not touched and no new directories were created under `tasks/`.

**Orchestrator post-step action (per skill: difficulty directive must never reach PRD.md):** the subagent left the line `Generate task harder than expert level!` as the first line of `SCAFFOLD.yaml`'s `scenario:` block, from which the doc generator would have copied it into PRD.md. The orchestrator stripped that line (and its trailing blank line) from `SCAFFOLD.yaml` before Step 4; `grep -c "harder than expert" SCAFFOLD.yaml` now returns 0 and the file still parses as YAML with the same 13 top-level keys. `SCAFFOLD.yaml` is now 3,830 lines.

## Step 3: Copy Shared Files — 2026-09-05T12:49:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_2871_stroke_center_certification_telestroke_network/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-09-05T13:09:00.000Z

PRD generation is complete.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2871_stroke_center_certification_telestroke_network/workspace/PRD.md`
**546 lines / 111,606 characters.** Built entirely with chunked `cat >>` heredoc appends (largest ~30 lines of prose per call); §2.2 was appended byte-for-byte from `skills/prd-bench-doc-generator/section-2.2-response-structure.md` rather than retyped.

## Section list

§1 Introduction · §2 Global Specifications & System-Wide Principles — 2.1 RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Numeric Precision/Rounding/Clock Arithmetic, 2.7 Stale-Version Rejection, 2.8 Cascade Discipline & Derived Aggregates, 2.9 Equipment Readiness & EMS Routing Advisory, 2.10 Segregation of Duties, 2.11 Validation Precedence (27-step ladder), 2.12 Flat Addressing · §3 Business Logic & Workflows — 3.1 Facilities/Agreements/Proxy Credentialing, 3.2 Code Stroke Activation & Time Window, 3.3 Consult Routing, 3.4 Video Sessions & Consult Completion, 3.5 Thrombolytic Checklist, 3.6 Imaging Clock & Thrombolysis, 3.7 Transfers/Congestion/Handoff, 3.8 Close/Abort/Deviation Review, 3.9 Abstraction, Reporting & Certification · §4 Endpoint Definitions (63 rows) · §5 Error Code Catalogue (59 rows).

**Tail confirmation:** the document ends on the final row of the §5 table (`| \`ERR_CENTER_NOT_CERTIFIED\` | 409 |`) — a complete two-column table at a real section boundary, no audit footer, no truncated sentence.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Mechanically extracted all `entities[].fields[].name`, all endpoint `input` identifiers (optional markers stripped), all list query params and all path params from SCAFFOLD.yaml = **159 distinct identifiers**; all 159 appear verbatim inside backticks in PRD.md. **Missing: 0.** Common fields (`id`, `created_at`, `updated_at`, `version`) are specified in §2.5.

**Contract 2 — Rule Coverage: PASS.** All 59 error identifiers appear in §2/§3 narrative prose (not only in the §5 table). All enum values declared in every `constraints: one of {...}` appear (0 missing). All 6 role names appear. Every state token of all 10 state machines appears. All 13 calculations are specified in prose — `clock_interval_metrics` (§2.6), `ems_routing_posture` (§2.9), `thrombolytic_window_classification` (§3.2), `consult_routing_selection` (§3.3, 8-clause filter + 4-key ranking + empty-pool escalation), `video_session_validity` (§3.4), `eligibility_score` (§3.5, both SCREENING/ATTESTED variants + outcome ladder), `projected_door_in_door_out` (§3.7, pinned 4 steps), `handoff_settlement_sequence` (§3.7, pinned 7 steps), `abstraction_numerator_denominator` (§3.9, both variants + ordered exclusions), `measure_compliance_rate` (§3.9, both variants), `composite_certification_score`, `dtn_excess_reporting`, `public_dtn_rollup` (§3.9). Every named constant's *value* is stated numerically in business context (targets 45/60/300/120/180/270/30; scoring 15.0/12.0/100.0/6.0/8.0/15.0, thresholds 55.0/40.0; session 180 s / 2 disconnects; cooldown 10 min; decline limit 3; divert threshold 3; congestion 1.00/1.25; overheads 20/10; DIDO 120; weights 0.40/0.35/0.25; penalties 8.0/18.0 capped 24.0; credits 5.0/2.0 at 20/10; multipliers 1.00/0.95/1.05; decision cut-offs 85.00/70.00), together with all `INC_*` and `HP_*` code literals and the worked boundary examples (33.33 / 66.67 / 78.38 / 55.58 / 100.00 clamp / 17.00 / 8.50). Both OCC rules, the two segregation-of-duties barriers, all `applies_to` scopes, all field defaults and all sibling-branch symmetries (complete vs. cancel, accept vs. decline, denial vs. acceptance) are stated.

**Contract 3 — §3 Path Purity: PASS.** 1,137 backtick tokens in §3 scanned: **0** begin with `/`, **0** are a bare HTTP method, **0** combine method+path; the literal string `/stroke-network` occurs **0** times anywhere in §3. All routing information is confined to §4.

One interpretive decision worth flagging to the orchestrator: the scaffold is internally inconsistent about the consult-request agreement-expiry error (the state-machine note says `ERR_AGREEMENT_WINDOW_CLOSED`, while validation priority 66 and the error catalogue both say the expiry path yields `ERR_AGREEMENT_NOT_ACTIVE`). The PRD follows the validations/catalogue majority: clock before `effective_from` → `ERR_AGREEMENT_WINDOW_CLOSED`; clock at/after `effective_until` → auto-terminate then `ERR_AGREEMENT_NOT_ACTIVE`. Similarly, the imaging self-loop is specified permissively (later instant replaces earlier, per the endpoint description and its "recomputed" side effect) rather than by the state machine's `imaging_at == null` guard, and handoff step 5 decrements **both** origin and destination `open_case_count` per the endpoint's pinned 7-step sequence.

**Orchestrator truncation check (guard from the run prompt):** `wc -l -c` = 546 lines / 111,606 chars; the tail is the final `| \`ERR_CENTER_NOT_CERTIFIED\` | 409 |` table row, a real section boundary — NOT mid-sentence. Independently verified the §5 table carries exactly 59 `| \`ERR...` rows (matching the scaffold's 59 errors) and the §4 table carries 63 endpoint rows + 2 header rows (matching the scaffold's 63 endpoints). `grep -c` for `harder than expert|SCAFFOLD|difficulty_design|corner_design|test_recipe` in PRD.md = **0**, so neither the difficulty directive nor any withheld-index vocabulary leaked. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-05T13:57:00.000Z

Implementation complete and verified.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2871_stroke_center_certification_telestroke_network/workspace/implementation/`

| File | Lines |
|---|---|
| `requirements.txt` | 1 |
| `start.sh` | 10 |
| `app.py` | 83 |
| `constants.py` | 160 |
| `db.py` | 192 |
| `errors.py` | 92 |
| `middleware.py` | 212 |
| `response.py` | 66 |
| `services/calculations.py` | 163 |
| `services/derive.py` | 174 |
| `services/reporting.py` | 184 |
| `services/routing.py` | 60 |
| `routes/centers.py` | 123 |
| `routes/agreements.py` | 148 |
| `routes/neurologists.py` | 101 |
| `routes/cases.py` | 272 |
| `routes/consults.py` | 308 |
| `routes/checklists.py` | 264 |
| `routes/transfers.py` | 224 |
| `routes/deviations.py` | 176 |
| `routes/abstractions.py` | 145 |
| `routes/reports.py` | 257 |
| **total** | **3415** |

Plus empty `routes/__init__.py` and `services/__init__.py`. `python3 -m compileall` → COMPILE_OK; `__pycache__` dirs removed.

## Endpoints: 63 (exact match to PRD §4)

A programmatic diff of `app.url_map` against the 63 rows of the PRD §4 table shows zero missing and zero extra routes — 62 blueprint routes under `/stroke-network` plus `POST /_clock/set_current_utc` at the root (outside the mount, as PRD specifies). Storage is in-memory dicts only; nothing is seeded at boot; `start.sh` reads `$PORT`, binds `0.0.0.0`, and `exec`s in the foreground.

## Notable interpretive decisions (PRD ambiguities)

- **Rule 16 outranks rule 17.** §3.6 prose lists the eligibility check before the absolute-contraindication check, but §2.11 numbers absolute contraindication 16 and calls it "the highest-precedence clinical safety rule," so `ERR_ABSOLUTE_CONTRAINDICATION` fires first. §2.11 is treated as authoritative wherever it contradicts §3 prose.
- **Window-expired refusal persists the recomputed class** (§2.11 rule 21 says the reclassification happens before the guard) without bumping `version`/`updated_at`.
- **Imaging gates on `ct_scanner_ready`**, not the aggregate posture; a second imaging on `CONSULT_IN_PROGRESS` replaces the earlier instant (PRD line 297 overrides the scaffold's `imaging_at == null` precondition).
- **Undeclared case nodes → `ERR_CASE_NOT_ACTIVE`** per rule 13's last sentence: consult request only from `ACTIVATED`/`IMAGING_COMPLETE`, transfer only from `ELIGIBILITY_DETERMINED`/`THROMBOLYSIS_ADMINISTERED`, close only from `THROMBOLYSIS_ADMINISTERED` or an `INELIGIBLE` `ELIGIBILITY_DETERMINED`.
- **Checklist sub-action state violations** have no per-entity code in §5, so they also return `ERR_CASE_NOT_ACTIVE`; determination gates only on `determination_status == PENDING` so an under-documented checklist yields `ERR_CHECKLIST_INCOMPLETE` (rule 18) rather than a state error.
- **Unknown and duplicate inclusion codes both return `ERR_DUPLICATE_INCLUSION_ITEM`** (rule 27 words it as "no duplicate or unrecognised inclusion item"; `item_code` is a free string, not an enum).
- **Video-session append is gated on `IN_SESSION`** (scaffold description; the corner design carries no error expectation for that endpoint).
- **Report submit gates on freshly derived counts** computed before the re-gather, so a rejected submit detaches nothing. Note the residual PRD tension: `closed_case_count_in_period` is only *stored* at the recompute points PRD enumerates, so a report created before its cases close holds a stale stored count while the submit gate reads the live derivation (per §2.6's "must always agree with those records"). Post-submit the stored value is refreshed.
- **Retraction recomputes counts/rates/mean but not the composite** (§3.9 line 377 lists exactly five fields).
- **Denial escalation** suspends each `ACTIVE` hubbed agreement and, at `WITHDRAWN`, terminates all hubbed agreements; per-request touch-once bookkeeping keeps each entity to one `version` bump per request.

## Smoke test (PORT=41871, killed by specific PID only)

Booted clean, then ~150 calls across nine scenarios; killed PID 2736827 alone (`kill <pid>`, never a pattern kill) and confirmed the port closed. Verified correct: envelope shape (`meta.api_request_id`, millisecond `api_request_timestamp`, `response_type`, list `limit`/`offset`/`total_count`/`has_more`), logical clock echoed verbatim on domain instants, full happy path (activate → imaging DTI 20 → route/accept/video/complete → 4 inclusion items → determine ELIGIBLE 66.00 → administer DTN 40, dose 9.0, LKW-to-needle 70 → transfer 1.00/35/65 matching PRD's worked example → handoff DIDO 90 → close), ineligible path (absolute contraindication → score clamped 0.00 → INELIGIBLE → `ERR_ABSOLUTE_CONTRAINDICATION` on administer → NO_TREATMENT close), override path (relative contraindication → `ERR_OVERRIDE_JUSTIFICATION_REQUIRED` → `ELIGIBLE_WITH_RELATIVE_OVERRIDE` 54.00), amend → `ERR_ELIGIBILITY_NOT_DETERMINED` → re-determine → administer, dose rounding 8.55 → 8.6, deviation review lifecycle (start-review → `ERR_DEBRIEF_REQUIRED` → return-for-info → resubmit round 2 → round-limit → debrief → substantiate, rolling into the report's sentinel count), transfer decline unwind and late handoff (DIDO 180 → MAJOR `DIDO_EXCEEDED`), report create/supersede/OCC/overlap, submit gates, composite 20.90, DENIED → SUSPENDED count 1 → second denial → WITHDRAWN, publish refusal on a non-accepted report, the four-hop direct suspension cascade (agreement SUSPENDED "hub certification suspended", consult CANCELLED "agreement suspended", neurologist released to `ON_CALL` with no cooldown, MAJOR `CONSULT_UNFILLED` opened, BYPASS postures), abort cascade, cooldown-driven `ESCALATED_UNFILLED`, `ERR_AGREEMENT_CONSULT_CAPACITY`, roster-rank selector ordering, board-certification filter on TIER_1, readiness attestations driving DEGRADED/OFFLINE → `ERR_CENTER_EQUIPMENT_OFFLINE`, and the error envelope for 401/403/404/405/409/412/422. Every deviation between my expectation and the response traced back to a wrong literal in my probe script (enum values, body field names), not to the implementation — each was re-checked against the PRD sentence and the server was right in all cases.

**Orchestrator note:** Step 5 (unit-test generator) was still running when this entry was written; the two steps were launched concurrently in a single message so the implementation generator could not see `test_suite/`. Its Step 5 entry follows below.

## Step 5: Generate Unit Tests — 2026-09-05T14:39:00.000Z

Queue B complete. The full suite is generated, audited, and static-clean.

## Files written (all at the task root, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2871_stroke_center_certification_telestroke_network/`

| file | lines | tests |
|---|---|---|
| `test_helpers/__init__.py` | 46 | — |
| `test_helpers/constants.py` | 163 | — |
| `test_helpers/types.py` | 523 | — |
| `test_helpers/api_errors.py` | 136 | — |
| `test_helpers/api_client.py` | 391 | — |
| `test_helpers/test_users.py` | 106 | — |
| `test_helpers/factories.py` | 394 | — |
| `test_helpers/assertions.py` | 586 | — |
| `test_helpers/fixtures.py` | 986 | — |
| `test_suite/conftest.py` | 75 | — |
| `test_suite/test_01_checklist_scores_and_determination.py` | 421 | 9 |
| `test_suite/test_02_consult_routing_and_video_sessions.py` | 644 | 12 |
| `test_suite/test_03_case_clocks_and_transfer_settlement.py` | 248 | 4 |
| `test_suite/test_04_reporting_rates_and_composite.py` | 305 | 6 |
| `test_suite/test_05_report_calendar_ledger_and_suspension.py` | 337 | 6 |
| `test_suite/test_06_entity_defaults_and_read_consistency.py` | 843 | 14 |
| `test_suite/test_07_lifecycle_transitions_and_cascades.py` | 1020 | 14 |
| `test_suite/test_08_derived_numerics_and_layered_gates.py` | 1410 | 14 |
| `test_suite/test_09_validation_gates_case_and_consult.py` | 1530 | 24 |
| `test_suite/test_10_validation_gates_quality_and_state_errors.py` | 1079 | 15 |
| `test_suite/test_11_endpoint_surface_errors_and_rbac.py` | 1458 | 15 |

**133 tests**, 12701 lines total (3331 helpers + 9370 suite).

## Coverage

- Queue A (difficulty): 18/18 instances, every one at >= 2 tests (one at 3) — 37 tests.
- Queue B (corner): **87/87 non-stub instances**, 96 tests. The 23 `excluded_because:` stubs were not translated, as specified.
- **Instances skipped for PRD-first failure: none.** Every non-stub instance had verbatim PRD coverage and a uniquely-derived outcome.

## Verification

- `verify_citations.py`: `tests: 133, problems: 0` — every test's docstring ends in exactly one `Design:` line and carries >= 1 verbatim PRD quotation of >= 8 words; no scaffold/Table-1 references.
- `check_tags.py --coverage`: `bad tags: 0` — every tag resolves to a real instance name.
- `pyflakes` clean across `test_suite/` and all substantive `test_helpers/` modules (only the intentional re-export warnings in `__init__.py` remain).
- All 11 test modules import successfully under `PYTHONPATH=.`.
- Zero `skip` / `skipif` / `xfail` / `pytest.skip` in the suite.
- No smoke server was started and the suite was not executed (no implementation to run against yet); `workspace/implementation/`, `worklog.md`, and sibling task dirs were untouched.

## One real infrastructure bug found and fixed

Three subagents independently flagged it and I confirmed and fixed it in `test_helpers/fixtures.py`: `determine()` and `decide_report()` called `api_client.determine_checklist(id, payload, headers)` / `decide_certification_report(id, payload, headers)` positionally, but both client methods are declared `(id, headers=None, payload=None)` — so the payload went out as the header map and the headers as the JSON body, leaving those requests with no `X-User-ID`. Both call sites now pass `headers=` / `payload=` by keyword. This had latent blast radius over `setup_eligible_case`, `setup_treated_case`, `setup_closed_treated_case`, `setup_reportable_case`, `setup_report_scenario`, `setup_accepted_transfer` and therefore most of queue A. I then AST-swept every `api_client.*` call in `test_helpers/` and `test_suite/` for the same argument-order class of error: no other occurrences. (`test_09` and `test_11` carry their own local keyword-passing determine/decide helpers written as a workaround; they remain correct.)

## Design index vs PRD — PRD followed in every case

Ten divergences, all resolved in the PRD's favour and asserted accordingly, e.g.: handoff decrements the destination's `open_case_count` too (PRD 3.7 step 5 vs the index's "not released"); `routing_attempt_count` is 3 after the pool-emptying second decline, and 1 (not 0) on an empty-pool creation; `on_call_state` stays `ON_CALL` at assignment (it flips only on acceptance); the disposition enum has no `DRIP_AND_SHIP_TRANSFER` and no `OFF_CALL` on-call state (used `DRIP_AND_SHIP` / `OFF_DUTY`); the status is `THROMBOLYSIS_ADMINISTERED`, not `THROMBOLYTIC_GIVEN`; a report denial suspends unconditionally rather than only from `CONDITIONAL`; a declined transfer unwinds the case to `ELIGIBILITY_DETERMINED`/`PENDING`; administering on a non-determined case yields `ERR_CASE_NOT_ACTIVE` per the §2.11 ladder; `review_round` rises on entry into review, not on each return-for-info; and an unreproducible 82.33 composite was rebuilt as the PRD-derived 71.25 while preserving the instance's actual claim.

**Orchestrator verification:** `find` confirms `test_helpers/` and `test_suite/` exist only at the task root — nothing stray under `workspace/` (a known failure mode of this generator). `grep -c "^def test_"` across `test_suite/*.py` = **133**, matching the reported count. The 4 `grep` hits for `skip|xfail` are all benign prose (a comment and a test name about the routing selector *skipping* ineligible candidates, a `Design:` tag line, and a docstring sentence) — zero pytest skip/xfail markers.

## Step 7: Run Tests and Iterate — 2026-09-05T15:08:00.000Z

Done — clean 8-round sweep.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one fix batch, one verification sweep).

**Final per-round results (iteration 2):** rounds 1–8 all `133 passed / 133 total`, 0 failed, 0 errors.

**Iteration 1 baseline:** all 8 rounds `128/133` with the *same* 5 failures in every round — fully deterministic, no load-induced flakiness.

**Tests deleted:** none. All 5 failures traced to test bugs (STEP 2), not PRD silence.

**Fixes applied to `test_suite/`:**

- `test_04_reporting_rates_and_composite.py` — `test_draft_report_pools_the_draft_row_and_reads_a_fifty_percent_rate`: asserted `included_abstraction_count == 2`, counting an attached `DRAFT` row. PRD §2.8 states verbatim: *"A report's `included_abstraction_count` is the number of abstractions whose `report_id` names it and whose `status` is `FINALIZED`"* (corroborated by §3.9's `ERR_NO_FINALIZED_ABSTRACTIONS` wording). Corrected to `== 1`; the §2.8 quote was added to the docstring. The test still proves the draft row *attaches* (`report_id`) and *pools* (rate reads 50.00), which is what its cited PRD sentences actually govern.
- `test_05_report_calendar_ledger_and_suspension.py` — `test_a_draft_row_on_a_still_open_case_attaches_and_perturbs_the_ledger` and `test_retraction_restores_the_ledger_by_recomputation_and_frees_the_pair`: same `included_abstraction_count == 2` mis-translation in three places (two assertions plus the post-replacement re-check). Corrected to `== 1` against the same §2.8 sentence.
- `test_11_endpoint_surface_errors_and_rbac.py` — `test_a_composite_of_zero_is_denied_returned_and_unpublishable_but_resubmittable`: the test asserted `decided_at == 2026-09-05T10:00:00Z` but never advanced the logical clock past the `09:00:00Z` used for submission, so the PRD-faithful implementation correctly stamped `09:00`. Added the missing `fx.set_clock("2026-09-05T10:00:00Z")` before the decide — this makes the assertion *stronger*, since `decided_at` is now distinguishable from `submitted_at`.
- `test_11_endpoint_surface_errors_and_rbac.py` — `test_the_five_shared_operations_admit_exactly_their_two_declared_roles`: read a non-existent field `checklist["eligibility_verdict"]` (`KeyError`). PRD §3.5 names the field `determination_status` (*"`determination_status` — `PENDING`, `ELIGIBLE`, `INELIGIBLE` or `ELIGIBLE_WITH_RELATIVE_OVERRIDE`"*). Renamed the field reference rather than adding an untraceable alias to the implementation.

**Fixes applied to `test_helpers/`:** none needed — no shared setup error, and the fixtures/factories were consistent with PRD.

**Fixes applied to `implementation/`:** none. All 5 failures were the tests disagreeing with verbatim PRD prose that the implementation had followed correctly; no PRD-required check was weakened and no field, endpoint or side effect was added.

**Note on triage:** two extra failures appeared when I hand-ran `test_11` against a single shared server on port 21871 (`test_consult_filters_compose...`, `test_the_five_opaque_roles...`). Both are cross-test state bleed from reusing one server — they assert on unfiltered `total_count` — and both pass under the runner's `per-test-server` isolation in all 8 rounds. That server was killed by PID; no broad pattern kill was used. `worklog.md` was not touched.

**Orchestrator verification:** independently re-read all 8 `results.$i.json` — every round reports `133/133` passed, 0 failed. The orchestrator also observed the iteration-1 sweep directly (all 8 rounds `128/133`), confirming the deterministic-5-failure baseline the subagent reported. The sweep ran via the pre-written `workspace/sweep.sh` under `setsid nohup`, so no round was reaped; no `Terminated` pattern appeared.

**Orchestrator decision on Step 8's skip condition:** Step 7 made 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, but **4 `test_suite/` fixes**, so the skip condition (which requires all four counts to be zero) is NOT met and Step 8 runs. Expectation recorded up front: because every Step 7 fix corrected a *test* that contradicted verbatim PRD prose the implementation had already followed, `PRD_FINALIZED.md` may legitimately come back byte-identical to `PRD.md` — there is no PRD silence at these four sites to pin. That outcome is acceptable for Step 8 (unlike Step 9, which must actually scan).

## Step 8: Finalize PRD — 2026-09-05T15:11:00.000Z

`$TASK_DIR/workspace/PRD_FINALIZED.md` is written and is byte-identical to `PRD.md` (md5 `2fc79161a69ce65a94f741b084bd8975`), which is the legitimate outcome here: all four Step 7 fixes were tests contradicting verbatim PRD prose the implementation already followed.

## Line counts
- `PRD.md`: 546 lines
- `PRD_FINALIZED.md`: 546 lines
- Delta: 0 lines, 0.00%

## Changes
None. No PRD section required an insert or revise.

## Per-item analysis (all four `<step_7_diff>` items)

**Item 1 + 2 — `included_abstraction_count == 2` → `== 1`** (`test_04_reporting_rates_and_composite.py`, `test_05_report_calendar_ledger_and_suspension.py`, 3 sites)
- (a) Subject: definition of `included_abstraction_count`, and the separation between *attachment* (`report_id`), *rate pooling*, and *counting*.
- (b) Impl paths enumerated: `grep -rn included_abstraction_count` across all of `implementation/` returned exactly 4 write/read sites, all read: `services/reporting.py:142-145` (`recompute_counts` — `sum(1 for a in attached_abstractions(report) if a["status"] == "FINALIZED")`), `routes/reports.py:80` (create default `0`), `routes/reports.py:169` + `:178` (submission re-gather then feed into `calc.composite_score`), `services/calculations.py:139-149` (volume credit thresholds 20/10). Also read `services/reporting.py:106-112` (`compute_rate`: `PROVISIONAL` pool = `("DRAFT","FINALIZED")`, `CERTIFIED` = `("FINALIZED",)`) and `:92-101` (`draft_report_for_case`, the single-match attach rule).
- Verdict: PRD §2.8 (line 123) already states verbatim that the count is *"the number of abstractions whose `report_id` names it and whose `status` is `FINALIZED`"*; §3.9 line 383 already states the `PROVISIONAL` pool includes `DRAFT`. Together these uniquely determine the impl's split behavior — a `DRAFT` row attaches and moves the rate to 50.00 while leaving the count at 1. Line 373 and line 381 are consistent (they say the count is *recomputed*, deferring to §2.8's definition). No silence, no mismatch.
- (c) No wording adjustment (no edit).

**Item 3 — missing `fx.set_clock("2026-09-05T10:00:00Z")` before decide** (`test_11_endpoint_surface_errors_and_rbac.py`)
- (a) Subject: when `decided_at` is stamped.
- (b) Impl paths enumerated: `grep -rn decided_at` → `routes/reports.py:92` (create default `None`), `routes/reports.py:201` (`record["decided_at"] = db.now_raw()`). Read `routes/reports.py:187-215` (full `decide_report`) to confirm nothing else writes it and that the resubmission-from-`RETURNED` path (which resets `decision`/`decided_by_user_id`) is separate.
- Verdict: PRD line 82 lists `decided_at` among the server-assigned instants that are *"always the logical clock as it stands at the moment the write is applied"*, and §3.9 line 400 repeats *"`decided_at` is stamped from the logical clock"*. The impl's `db.now_raw()` is exactly that. Pure fixture bug — the test never advanced the clock. No silence, no mismatch.
- (c) No wording adjustment (no edit).

**Item 4 — `checklist["eligibility_verdict"]` → `checklist["determination_status"]`** (`test_11_endpoint_surface_errors_and_rbac.py`)
- (a) Subject: the name of the checklist verdict field.
- (b) Impl paths enumerated: `grep -rn determination_status` → `routes/checklists.py:76` (create default `PENDING`), `:108` (list filter key), `:189-192` (`PENDING` precondition + `ERR_CASE_NOT_ACTIVE`), `:223` (determination writes verdict), `:256` (amendment resets to `PENDING`), and the two consumers in `routes/cases.py:163` (thrombolytic eligibility gate) and `:210` (`INELIGIBLE` disposition check). Separately grepped `eligibility_verdict` across `PRD.md`, all of `implementation/`, `test_suite/` and `test_helpers/` — zero hits anywhere (exit 1), confirming the name was invented by the test and now exists nowhere.
- Verdict: PRD §3.5 (lines 270, 272) and the endpoint table (line 451) all name the field `determination_status` and enumerate its four values. The impl uses that name at all seven sites. No silence, no mismatch.
- (c) No wording adjustment (no edit).

**Item 5 — `test_helpers/` fixes: none; `implementation/` fixes: none; deletions: none** → nothing to trace, no candidate edit.

## Note
Because there were zero edits, the NO-NEW-MISMATCH rule had nothing to constrain, but I still ran the mandatory pre-edit enumeration for each of the four candidate subjects (logged above) before concluding that no patch was warranted. Relevant impl evidence: `.../implementation/services/reporting.py:142-145` and `:106-112`, and `.../implementation/routes/reports.py:201`.

**Orchestrator verification:** `md5sum` on both files confirms the byte-identical claim. Per the skill, a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome when Step 7 applied no implementation fixes — the constraint that the document must actually change applies to Step 9, not Step 8. Step 9 will therefore start from `PRD_FINALIZED.md` and is expected to produce a genuinely different `PRD_COMPLETED.md`.

**Orchestrator plan for Step 9:** because a single subagent scanning 3,415 lines of implementation against a 546-line/111k-char PRD reliably runs out of room and returns an unchanged file, Step 9 is executed as **three sequential passes**, each a fresh subagent partitioned by implementation module, all editing the same shared `workspace/PRD_COMPLETED.md`. Pass 1 performs the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 must NOT re-copy (that would discard the previous pass's edits). Partition: pass 1 = infrastructure + network standing-up (`app.py`, `middleware.py`, `response.py`, `db.py`, `errors.py`, `constants.py`, `routes/centers.py`, `routes/agreements.py`, `routes/neurologists.py`); pass 2 = the acute case flow (`routes/cases.py`, `routes/consults.py`, `routes/checklists.py`, `services/routing.py`, `services/derive.py`); pass 3 = transfer/quality/reporting (`routes/transfers.py`, `routes/deviations.py`, `routes/abstractions.py`, `routes/reports.py`, `services/calculations.py`, `services/reporting.py`).

## Step 9: Complete PRD — 2026-09-05T15:36:00.000Z

Executed as **three sequential passes**, each a fresh subagent partitioned by implementation module, all editing the same shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the one and only `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy, and each confirmed the prior passes' edits were still present before and after its own work.

**Aggregate: 55 changes — 41 ambiguity-pins, 14 mismatch-revisions.** `PRD_FINALIZED.md` 546 lines / 111,606 chars → `PRD_COMPLETED.md` 546 lines / 128,256 chars (**+16,650 chars, +14.9%**; line count unchanged because every edit was an in-paragraph insert or revision — no new sections, no new paragraphs).

### Pass 1 of 3 — infrastructure + network standing-up
Slice: `app.py`, `middleware.py`, `response.py`, `db.py`, `errors.py`, `constants.py`, `routes/centers.py`, `routes/agreements.py`, `routes/neurologists.py`. Result: 546 lines / 111,606 → 117,324 chars (+5,718). **15 ambiguity-pins, 7 mismatch-revisions.**

- §2.1 — insert — ambiguity — authentication does no entity lookup; an `X-User-ID` naming no `Neurologist` authenticates fine and fails only at a declared ownership check — middleware.py:18-27
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from A–Z/0–9, minted per request incl. failures — db.py:100-105
- §2.2 — insert — ambiguity — `api_request_timestamp` is the logical clock normalised to UTC, 3 fractional digits, trailing `Z` — db.py:90-93, response.py:9-13
- §2.3 — insert — ambiguity — `limit`/`offset` are whitespace-trimmed before parsing — middleware.py:37-48
- §2.3 — insert — ambiguity — records sharing `created_at` order by server creation sequence, earliest first — db.py:157
- §2.3 — insert — ambiguity — filters matched literally and never enum-validated (bad value ⇒ empty set, not 422); boolean filters accept true/false/1/0 any case; unknown query params ignored — middleware.py:194-212
- §2.4 — insert — ambiguity — clock endpoint declares exactly one field `current_utc`, answers 200 with empty `data` — app.py:37-51, response.py:39
- §2.4 — insert — **mismatch** — server-assigned instants echo the clock's supplied spelling verbatim (incl. non-UTC offset form); only the envelope timestamp is normalised — db.py:85-87, 118-127
- §2.5 `created_at` — revise — **mismatch** — removed "with three fractional digits"; stamped in the clock's own spelling — db.py:120
- §2.5 `updated_at` — revise — **mismatch** — same — db.py:130-139
- §2.5 `version` — insert — **mismatch** — increments at most once per request per record (counts touching requests, not field assignments); re-deriving to an unchanged value adds nothing — db.py:110-147
- §2.11 rule 5 — insert — ambiguity — declared numeric ranges, length limits and patterns are shape failures (`ERR_INVALID_REQUEST`, not enum); bool never satisfies int/num; explicit `null` == omission; absent body == `{}` — middleware.py:90-156
- §2.11 rule 8 — insert — **mismatch** — path existence outranks rules 5 and 7 (the one departure from the strict ladder), per §2.12; verified `load_path` precedes `read_body` in every route module — centers.py:104, agreements.py:128, neurologists.py:84
- §3.1 registration — insert — ambiguity — PATCH fields independently optional; supplying neither still bumps `updated_at`/`version` — centers.py:88-98
- §3.1 attestation — insert — ambiguity — the free-text `note` is length-unbounded, never persisted, absent from the response — centers.py:36, 101-111
- §3.1 activation — insert — ambiguity — no body fields declared; closed window and withdrawn spoke both return `ERR_INVALID_AGREEMENT_STATE` (not `ERR_AGREEMENT_WINDOW_CLOSED`); clock need not have reached `effective_from` — agreements.py:86-109
- §3.1 agreement suspension — revise — ambiguity — `suspension_reason` must be non-empty — agreements.py:30
- §3.1 suspension cascade — insert — ambiguity — cancelled consults get `cancellation_reason` 'agreement suspended' and a `CONSULT_UNFILLED`/`MAJOR` system deviation — agreements.py:120-121, derive.py:149-151
- §3.1 proxy credentials — insert — ambiguity — `EXPIRED` is never written (grants stay `GRANTED`, filtered by §3.3's strict expiry); `expires_at` not checked against the clock at grant time — agreements.py:140-146, routing.py:13-17
- §3.1 neurologists — revise — **mismatch** — `home_center_id` need only exist; a spoke/thrombectomy-capable facility is accepted — neurologists.py:46
- §3.1 availability — insert — ambiguity — no ownership check on `on-call-state`; any `Neurologist` caller may move any neurologist — neurologists.py:81-101
- §5 intro — insert — **mismatch** — catalogue was declared exhaustive; added the off-contract `ERR_NOT_FOUND` (404 unmatched path, 405 undeclared method) — app.py:59-68

Verified with no change needed: all 60 `HTTP_STATUS` entries match the §5 table; `NOT_FOUND_BY_COLLECTION` matches rule 8's list; every enum domain in constants.py that §2/§3.1 names matches; §2.9's three-clause posture rule and inclusive-3 threshold match `derive.recompute_ems_posture` exactly; `DEFAULT_CLOCK_RAW` matches §2.4; empty-store-on-boot matches §1/§2; the §3.9 hub-suspension cascade literals already match `derive.suspend_center_cascade`. Deliberately left unpinned: the catch-all `Exception` handler (app.py:71-78, an internal-error path, not contract behaviour); leading `+`/`-` sign tolerance in pagination parsing (unobservable — both spellings end at the same error code); `roster_rank` uniqueness (neither PRD nor impl constrains it; ties resolved by §3.3).

### Pass 2 of 3 — the acute case flow
Slice: `routes/cases.py`, `routes/consults.py`, `routes/checklists.py`, `services/routing.py`, `services/derive.py`. No `cp` performed. Result: 117,324 → 122,393 chars (+5,069); confirmed pass 1's +5,718 still present. **15 ambiguity-pins, 3 mismatch-revisions.**

- §3.2 — insert — ambiguity — enumerated the case fields that begin null at activation (`imaging_at`, `needle_at`, the three interval fields, agent, dose, `abort_reason`) — routes/cases.py:85-97
- §3.6 — insert — ambiguity — `imaging_modality` is required/non-empty but is never persisted and appears nowhere in the response — routes/cases.py:40,128
- §3.6 — **revise** — **mismatch** — the absolute-contraindication guard runs *before* the eligibility guard (PRD prose had them reversed, contradicting §2.11 rule 16 > 17); also pinned `thrombolytic_dose_mg` >= 0 with no max and stored rounded to 1 dp half-up, and that a case with no checklist trips `ERR_ELIGIBILITY_NOT_DETERMINED` — routes/cases.py:153,159-167,184
- §3.6 — insert — ambiguity — a null `imaging_at` refuses with `ERR_CASE_NOT_ACTIVE` — routes/cases.py:168-170
- §3.6 — insert — ambiguity — a window-expired refusal still leaves the freshly recomputed `OUT_OF_WINDOW` on the case while `updated_at`/`version` stay put — routes/cases.py:173-176
- §3.8 — insert — ambiguity — a live consult blocks close with `ERR_CASE_NOT_ACTIVE`, checked after the status/verdict gate — routes/cases.py:217-220
- §3.8 — insert — ambiguity — `abort_reason` non-empty; `THROMBOLYSIS_ADMINISTERED` is not abortable — routes/cases.py:47,235
- §3.8 — insert — ambiguity — abort-cancelled consults and transfers both record `cancellation_reason` = 'case aborted' — routes/cases.py:246,255
- §3.3 — **revise** — **mismatch** — the agreement-expiry auto-termination is *not* "the very first thing": it runs behind the equipment, spoke-match and `effective_from` gates and immediately before the `ACTIVE` guard, so an earlier rejection leaves the expired agreement untouched; only an `ACTIVE` agreement is auto-terminated — routes/consults.py:110-118
- §3.3 — **revise** — **mismatch** — on an empty pool `routing_attempt_count` is *not* incremented again; a first-pass escalation reports 1, not 2 — routes/consults.py:136,146
- §3.3 — insert — ambiguity — a consult request is declared only from `ACTIVATED`/`IMAGING_COMPLETE`; any other status (including `CONSULT_IN_PROGRESS`, so no second consult per case) is `ERR_CASE_NOT_ACTIVE` — routes/consults.py:95-98
- §3.3 — insert — ambiguity — accept: non-`ON_CALL` state is `ERR_INVALID_ONCALL_TRANSITION` and precedes the other-`IN_SESSION` check, which is `ERR_INVALID_CONSULT_STATE` — routes/consults.py:181-189
- §3.4 — insert — ambiguity — video append requires `IN_SESSION` (`ERR_INVALID_CONSULT_STATE`), returns the updated consult, `disconnect_count` >= 0 with no max, and `started_at`/`ended_at` are unordered/unchecked so a reversed pair yields a negative `duration_seconds` — routes/consults.py:42-47,250-254
- §3.4 — insert — ambiguity — the null-`ended_at` completion condition is unreachable because `ended_at` is required on the append — routes/consults.py:44,290-293
- §3.5 — insert — ambiguity — documentation writes are declared only from `NOT_STARTED`/`IN_PROGRESS`/`AMENDED`; a `DOCUMENTED` checklist refuses both write kinds with `ERR_CASE_NOT_ACTIVE`; an empty `item_code` is `ERR_INVALID_REQUEST` — routes/checklists.py:39,119-127
- §3.5 — insert — ambiguity — determination additionally requires case `status` `CONSULT_IN_PROGRESS` or `ELIGIBILITY_DETERMINED` (a `TRANSFER_INITIATED` case cannot be re-determined); an empty `override_justification` is `ERR_INVALID_REQUEST` — routes/checklists.py:193-195,36
- §3.5 — insert — ambiguity — non-`INELIGIBLE` verdicts set case `disposition` to `PENDING`, and the case's `version` increments even on a no-change re-determination — routes/checklists.py:233-234
- §3.5 — insert — ambiguity — an amendment bumps the case's `updated_at`/`version` even when `disposition` was already `PENDING` — routes/checklists.py:262-263

Deliberately left unpinned: `services/routing.py` needed no edits (every candidate clause, the four-key sort and empty-pool behaviour are already uniquely pinned by §3.3 clauses 1–8 and line 244; the `_seq` tiebreak is covered by "the earlier-registered neurologist wins"); `derive.open_system_deviation`'s initial-null fields (deferred to pass 3, which picked them up); `derive`'s posture/aggregate recomputation (pass 1's lane); `last_decline_reason` non-empty (already implied by §2.11 rule 5).

### Pass 3 of 3 — transfer, quality review and reporting
Slice: `routes/transfers.py`, `routes/deviations.py`, `routes/abstractions.py`, `routes/reports.py`, `services/calculations.py`, `services/reporting.py`. No `cp` performed; 15 targeted `Edit` calls, no `Write`. Result: 122,393 → 128,256 chars (+5,863); verified both prior passes intact (diff vs `PRD_FINALIZED.md` shows 50 changed lines covering pass 1's, pass 2's and its own). **11 ambiguity-pins, 4 mismatch-revisions.**

- §3.7 — revise — mismatch — destination guards reordered to the actual/§2.11 precedence (thrombectomy → BYPASS → self-referral, not thrombectomy → self-referral → BYPASS), plus a note that `certification_status` is not consulted at proposal time — routes/transfers.py:66-73
- §3.7 — revise — ambiguity — decline is declared only from `PROPOSED`; any other status is `ERR_INVALID_TRANSFER_STATE`; `decline_reason` is non-empty — routes/transfers.py:154-158
- §3.7 step 2 — insert — ambiguity — `handoff_packet_items` is an unconstrained string list stored verbatim (order preserved, no dedup, extra and unrecognised codes accepted, no enum failure); only required-code presence is tested — routes/transfers.py:36-38,184-196
- §3.7 step 4 — insert — ambiguity — the handoff close carries no consult-settlement condition (unlike §3.8's direct close); a live consult and its neurologist are left untouched — routes/transfers.py:203-205
- §3.8 — insert — ambiguity — deviation create pins the four initial nulls `reviewed_by_user_id`, `info_request`, `additional_info`, `debrief_summary` (pass 2's deferred item; also governs `services/derive.py:96-111`) — routes/deviations.py:53-58
- §3.8 — revise — ambiguity — return-for-info records `reviewed_by_user_id`; resubmit leaves both `reviewed_by_user_id` and the earlier `info_request` intact rather than clearing them — routes/deviations.py:114-116,132-134
- §3.8 — insert — ambiguity — the debrief has **no** state precondition (accepted from every status incl. `SUBSTANTIATED`/`DISMISSED`), is repeatable/overwriting, and writes nothing else — routes/deviations.py:139-148
- §3.9 — revise — mismatch — abstraction attach-on-create also refreshes `closed_case_count_in_period`; the two substantiated counts and the composite are not touched — routes/abstractions.py:30-35,73
- §3.9 — revise — mismatch — finalise also refreshes `closed_case_count_in_period` and `mean_dtn_excess_pct`; and the unfinished-case gate returns `ERR_INVALID_ABSTRACTION_STATE`, not `ERR_CASE_NOT_ACTIVE` — routes/abstractions.py:107-109,122
- §3.9 — revise — ambiguity+mismatch — retract: an unattached `FINALIZED` row is freely retractable; recompute also covers `closed_case_count_in_period`, and rates use the report's current `rate_variant` (so `CERTIFIED` out of a `RETURNED` report) — routes/abstractions.py:131-144
- §3.9 — insert — ambiguity — pins the population of `substantiated_major_count`/`substantiated_sentinel_count`: `SUBSTANTIATED` deviations on the same in-period **`CLOSED`** cases; an in-period `ABORTED` case's deviation and any `MINOR` one count toward neither — services/reporting.py:148-162
- §3.9 — revise — mismatch — both submission volume gates read the **live** population, not the stored counters, and in the pinned order; re-gather also recomputes `closed_case_count_in_period` — routes/reports.py:145-156,168
- §3.9 — revise — ambiguity — `reviewer_note` is of any length and is never persisted — routes/reports.py:32,191
- §3.9 — insert — ambiguity — nothing on the submit/decide path gates on the facility's `certification_status`, so a decision can lift a facility out of `SUSPENDED` or `WITHDRAWN`, and a denial on an already-`WITHDRAWN` facility takes the ordinary branch back to `SUSPENDED` with the counter +1 — routes/reports.py:208-224
- §3.9 — insert — ambiguity+mismatch — denial hop 3 pins the agreement `suspension_reason` 'hub certification suspended', the 'agreement suspended' cancellation and the `CONSULT_UNFILLED`/`MAJOR` deviation; and pins that withdrawal's termination runs **after** that hop, so an `ACTIVE` agreement is suspended first and only then `TERMINATED` — routes/reports.py:227-233

Deliberately left unpinned: **all arithmetic in `services/calculations.py`** was verified against §2.6/§3.5/§3.7/§3.9 and needed no change — eligibility screening/attested cores, clamp-then-round-once ordering, `compliance_rate` 0.00-on-zero-denominator, `per_case_dtn_excess_percent` (clamp-at-0 then `ROUND_HALF_UP` to a whole percent), `mean_dtn_excess` (null on empty, 2dp half-up), `composite_score` (weighted base off stored rounded rates, 24.0 penalty cap, 20/10 volume-credit thresholds, multiplier over the whole bracket, clamp then one 2dp rounding), `decision_for_score` thresholds and the 1dp public rollup are each already uniquely pinned, worked examples included; it was further confirmed that no per-case DTN-excess value can land on a `.5` tie (the ratio is `5e/3`), so no tie-break prose was needed. Also unpinned: `window_class`/`session_duration_seconds`/`session_valid` (pass 2's territory, verified consistent); `services/reporting.py:165 recompute_report()` is dead code with no call sites; `create_transfer` not checking the checklist verdict and `create_deviation` having no case-active gate (both already resolved by §2.11 rule 13's exhaustive enumeration); unreachable `if case is None` / `if center is None` defensive branches.

### Orchestrator verification of the Step 9 artifact
- `wc -l -c`: `PRD_COMPLETED.md` = **546 lines / 128,256 chars** vs `PRD_FINALIZED.md` 546 / 111,606 — a real +16,650-char delta, so the scan genuinely ran (md5 `5a106bbf35f16dcee968edb3c5dd2ba7` vs `2fc79161a69ce65a94f741b084bd8975`; a byte-identical Step 9 output would have meant the passes never executed).
- `diff` against `PRD_FINALIZED.md`: **50 changed line regions**, consistent with all three passes' edits surviving — pass 3 did not clobber passes 1–2.
- `diff` of the `^#` heading lists between the two files is **empty** — no new sections or headings were added, as the method requires.
- Tail is still the final `| \`ERR_CENTER_NOT_CERTIFIED\` | 409 |` row and the §5 catalogue still carries all **59** `ERR` rows — the document is not truncated.
- No test or implementation file was touched by Step 9 (documentation-only), so the Step 7 result stands: the 8 `results.{1..8}.json` in `workspace/implementation/` all record **133/133** passing.

**Pipeline complete.** All nine steps finished; `workspace/PRD_COMPLETED.md` is written.
