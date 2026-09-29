# Worklog — task_2769_public_access_television_studio_operations

## Step 1: Create task directory — 2026-09-04T18:38:34.686Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2769_public_access_television_studio_operations` and its `workspace/` subdirectory. Index was pre-assigned by the orchestrating caller (2769); no scan or auto-allocation of `./tasks/` was performed.

## Step 2: Generate scaffold — 2026-09-04T20:06:29.567Z

All three scaffold artifacts are complete and the lint is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2769_public_access_television_studio_operations/`)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 2862 | §1.0–§1.7 keys only (scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validation_order_bands, validations, priority_conflict_pairs, endpoints, constants, errors, roles) — no design keys |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2339 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5058 | `scaffold_corner_design` only |

**Scaffold surface**: 14 entities, 12 state machines (cyclic shape), 11 calculations (threshold, topological, interval_merge, chronological, tiered_pricing, 2x waterfall_allocation, constraint_propagation, weighted_scoring, forward_looking; 2 of them dual-variant), 42 validations across the priority ladder + 2 declared `priority_conflict_pairs`, 2 `concurrency_rules`, 70 endpoints, 56 error codes, 7 roles (`segregation_of_duties` role model, Producer entity-backed), 4 complexity layers, `immediate` consistency.

**§1.8**: 9 rule blocks x 2 instances = **18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**§1.9**: **86 instances** across all 9 taxonomy sections — entities 11, state_machines 14, calculations 18, validations 13, endpoints 7, errors 14, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1. Of these, 61 carry full `test_recipe` chains and 25 are `excluded_because:` stubs, each citing an existing §1.8 instance by name. Every one of the 56 error codes is referenced by at least one design instance (verified programmatically), and both `concurrency_rules` entries got real OCC instances since §1.8 does not cover them.

**Lint verdict** (`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2769_public_access_television_studio_operations`), verbatim:

```
Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1133

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Constraint notes: no sibling task directory was listed, read, globbed or grepped at any point — every fact used came from this task's own SCAFFOLD.yaml via `yaml.safe_load` introspection; no `pkill` was run; both design files were written incrementally with heredoc appends and re-parsed after each chunk. Also confirmed the "harder than expert level" directive did not leak into the scenario key or either design file.

Orchestrator verification: `grep -rn "harder than expert"` over the task dir returns nothing — difficulty directive did not leak. All three files present.

## Step 3: Copy shared files — 2026-09-04T20:06:44.966Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_2769_public_access_television_studio_operations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T20:21:40.380Z

PRD generation for task 2769 is complete.

**Output:** `workspace/PRD.md`
**Length:** 509 lines / 111,598 bytes, written in 8 incremental chunks (1 `Write` + 7 heredoc appends).

**Section list**
- `# Public Access TV Ops API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Studio Staff, Producers and Role-Based Access Control; 2.2 API Response Structure (Standard Success / Standard Error subsections); 2.3 Pagination; 2.4 Resource Identity, Timestamps and Versioning; 2.5 The Logical Broadcast Clock; 2.6 Money, Basis Points and Rounding Discipline; 2.7 Optimistic Concurrency on Hold Plans and Fiscal Restatements; 2.8 Refusal Order: Which Rule Reports the Error; 2.9 Cascade Discipline and Derived-Counter Reconciliation; 2.10 Path Resolution for Addressed Resources; 2.11 Enumerated Vocabularies
- `## 3. Business Logic & Workflows` — 3.1 Membership Admission and the Certification Curriculum; 3.2 Series Lineage, Seniority and Hold Plans; 3.3 Program Submission, Attestation Clearance and Content Review; 3.4 Channel Airtime: Window Fit, First Come, and Series Priority; 3.5 Volunteer Crew Staffing and Going to Air; 3.6 Equipment, Studio Reservations and the Deposit Hold; 3.7 Returns, Damage Review, Suspension and Reinstatement; 3.8 Franchise Fee and Capital Funding Administration; 3.9 Archive Retention, On-Demand Distribution and Community Impact
- `## 4. Endpoint Definitions`
- `## 5. Error Code Catalogue`

**Completeness confirmation**
- The document ends at a complete section boundary: the final line is the last full row of the §5 error table (`| ERR_CAPITAL_GRANT_EXCEEDS_BASE | 402 |`) — no mid-sentence, mid-table or mid-list truncation, and no audit footer.
- **70/70 endpoints.** The §4 table has exactly 70 method+path rows and a programmatic set-diff against `SCAFFOLD.yaml`'s `endpoints:` block shows zero rows missing in either direction.
- **56/56 error codes.** §5 has exactly 56 rows and 56 distinct `ERR_*` identifiers matching the scaffold's `errors:` block; all 38 error ids referenced by the `validations:` block also appear in §2.8's ordered refusal list.

**Hard Contract verification**

Contract 1 — Field-Name Coverage: **PASS** (two independent passes after stripping fenced code blocks from the token extraction). 134/134 `entities[].fields[].name` present verbatim in backticks, 0 missing; 89/89 distinct `endpoints[].input` identifiers present, 0 missing; 14/14 path parameters (`producerId`, `courseId`, `enrollmentId`, `seriesId`, `programId`, `attestationId`, `channelId`, `slotId`, `resourceId`, `reservationId`, `assessmentId`, `assignmentId`, `periodId`, `assetId`) present.

Contract 2 — Rule Coverage: **PASS**. All 42 validations rendered in §2.8 with error id, HTTP status and `applies_to` scope, plus both `priority_conflict_pairs`; both `concurrency_rules` (`expected_series_version`, `expected_funding_period_version`) expressed with rejection error and 412; all 42 state names across all 12 state-machine dimensions (Producer.status, CourseEnrollment.status, Series.status, Program.review_status, Program.clearance_status, PlaybackSlot.status, StudioResource.status, Reservation.status, DamageAssessment.status, CrewAssignment.status, FundingPeriod.report_status, ArchiveAsset.on_demand_status) appear in prose; all 11 calculations have full formula prose (`producer_certification_level`, `series_seniority_at`, `playback_window_fit`, `playback_conflict_resolution`, `reservation_deposit_hold`, `reservation_final_settlement`, `damage_penalty_assessment`, `crew_staffing_readiness`, `franchise_fee_allocation`, `community_impact_index`, `archive_retention_deadline`), including both dual-variant pairs (ACCRUAL/CASH x two reserve tiers; PROVISIONAL/FINAL); all 31 constants embedded as in-context values rather than symbolic names, per SKILL.md §194.

Contract 3 — §3 Path Purity: **PASS**. Of 1,126 backticked tokens in §3, zero start with `/`, zero are bare HTTP methods, and zero combine method+path; there are also zero unbackticked HTTP-method words and zero slash-path substrings in §3 prose.

§2.2 was pasted from `section-2.2-response-structure.md` and diffs byte-identical (only difference is the trailing section separator blank line).

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or grepped, no sibling task directory was read, and no broad `pkill` was run.

Orchestrator verification (truncation guard): `tail -c 1500` shows PRD.md ending on the final complete `| ERR_CAPITAL_GRANT_EXCEEDS_BASE | 402 |` table row of §5 — a real section boundary, not mid-sentence. Heading scan confirms all five top-level sections plus all sub-sections present. `grep -c "harder than expert" workspace/PRD.md` = 0, so the difficulty directive did not reach the PRD.

## Step 5: Generate unit tests — 2026-09-04T21:37:00.000Z

Both stages are complete and verified. Everything is at the task root (`/home/ubuntu/github/CodingPRD/tasks/task_2769_public_access_television_studio_operations/`); `workspace/` still contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` (untouched).

## File inventory (line counts)

Stage 1 — `test_helpers/` (9 files, 2194 lines)
`__init__.py` 37, `constants.py` 93, `types.py` 274, `api_errors.py` 134, `api_client.py` 380, `test_users.py` 109, `factories.py` 341, `assertions.py` 214, `fixtures.py` 612.

Stage 2 — `test_suite/` (19 files, 6023 lines; 100 tests)
`conftest.py` 23; queue A: `test_01_dual_variant_calc.py` 195 (4), `test_02_combinatorial_formula.py` 184 (4), `test_03_non_linear_state_machine.py` 248 (5), `test_04_transitive_cascade.py` 334 (6), `test_05_priority_pair_validation_conflict.py` 227 (4), `test_06_boundary_precision_check.py` 221 (4), `test_07_cross_entity_state_dependency.py` 202 (4), `test_08_resource_temporal_overlap.py` 194 (4), `test_09_compensating_invariant.py` 223 (4); queue B: `test_10_corner_entities.py` 441 (11), `test_11_corner_state_machines.py` 414 (8), `test_12_corner_calculations.py` 592 (11), `test_13_corner_validations.py` 641 (10), `test_14_corner_endpoints.py` 347 (5), `test_15_corner_errors.py` 883 (10), `test_16_corner_rbac.py` 264 (2), `test_17_corner_cross_cutting.py` 279 (3), `test_18_corner_consistency.py` 111 (1).

## Tests per design queue

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 39 tests over all 18 instances (0 stubs), every instance >=2 tests.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 61 tests over all 61 non-stub instances, exactly 1 each — entities 11, state_machines 8, calculations 11, validations 10, endpoints 5, errors 10, rbac 2, cross_cutting_complexity_layers 3, consistency_model 1. The 25 `excluded_because:` stubs emit nothing.

## Skipped design instances

None. Every non-stub instance in both queues passed the PRD-first two-condition filter and was translated; nothing was weakened, xfailed or stubbed.

## Verification performed

- AST pass over all 100 tests: exactly one `Design:` line each, always the last docstring line, all 79 tags resolving to real `name:` keys, no stub tagged, no tag without an instance, no "scaffold" mentions anywhere in either directory.
- Automated PRD-citation pass: every `PRD x.y: "..."` quote grepped (whitespace-normalised) against `workspace/PRD.md`. This found and fixed two line-wrap/case artifacts — `test_05` ("`BASIC`-certified" split across lines) and `test_10` ("Its" vs PRD's "its `sequence_number`"). All quotes now match verbatim.
- `python3 -m py_compile` clean on all 28 files; `__pycache__` removed.

## Design-yaml defects corrected while translating this session's remaining instances

- rbac queue wrote `X-Role` / `adm-9`; used the real `X-User-Role` and the existing `adm-2` identity.
- `corner_occ_funding_revision_rejects_superseded_version` asserted "allocable_base_cents is still 0 — revisions do not run the allocation before submission", which contradicts PRD §3.8 ("Both forms raise `revision_round` by 1, re-run the whole allocation under the effective basis"). Replaced with the recomputed allocation on both restatements (ACCRUAL 5000000 -> 250000/1762500/3087500/5100000; CASH 4900000 -> 392000/1677800/2930200/5000000, sum-back invariant asserted).
- Channel version increments on ledger-only mutations are not uniquely derivable from the PRD, so the ledger test asserts `scheduled_seconds`/`aired_seconds`/`slot_sequence_high` only, not `channel.version`.

## Step 6: Generate implementation — 2026-09-04T21:37:00.000Z

Implementation complete. All work confined to `workspace/implementation/`; I did not read `test_helpers/`, `test_suite/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task directory.

## File inventory (28 files, 3,925 lines)

Root — `workspace/implementation/`

| lines | file |
|---|---|
| 10 | `start.sh` (guarded pip install, `exec python3 app.py`) |
| 1 | `requirements.txt` (`flask>=2.0`) |
| 87 | `app.py` (blueprint registration, `ApiError`/404/405/HTTP/500 envelope handlers, `app.run(host="0.0.0.0", port=$PORT or 10000)`) |
| 113 | `constants.py` |
| 108 | `errors.py` (all 56 catalogue ids -> HTTP codes) |
| 126 | `util.py` (ISO parse/format, half-up integer rounding, bp math, calendar-month add) |
| 126 | `db.py` (in-memory dicts, logical clock, once-per-request `version` bump) |
| 54 | `response.py` / 52 `middleware.py` / 243 `validation.py` / 65 `support.py` |
| 296 | `calc.py` (all 11 calculations) |
| 395 | `serialize.py` (derived counters recomputed at serialization) |
| 259 | `cascades.py` |

`routes/` — 1 `__init__.py`, 23 `clock.py`, 129 `producers.py`, 214 `courses.py`, 119 `series.py`, 297 `programs.py`, 60 `channels.py`, 263 `slots.py`, 126 `crew.py`, 101 `resources.py`, 268 `reservations.py`, 98 `damage.py`, 177 `funding.py`, 114 `archive.py`.

Every file compiles (`python3 -m py_compile`); `__pycache__` removed.

## Endpoint count

**70/70.** Enumerated from `app.url_map` and diffed against the PRD §4 table — exact match, no extras, no omissions.

## Smoke test (port 21473, launched via `PORT=21473 bash start.sh`, killed by its own PID 3611367 resolved from that port only)

- Envelopes: 401 no-headers, 403 wrong role, 400 bad pagination, 404 typed not-found (`ERR_RESERVATION_NOT_FOUND`), 200 list with `limit/offset/total_count/has_more` in `meta` only, 201 create.
- Offline check of every PRD worked example passed exactly: deposit hold 17901 (three separately rounded lines) and 12962; late fee 1852 with settlement 1852/11110/0 and the repair variant 12962/0/108890; damage penalties (49999->1pt, 50000->2pt, 1200000 vs 900000->900000/4pt); ACCRUAL vs CASH franchise allocation (250000/1762500/3087500/5100000 and 384000/1645600/2870400/4900000); impact index 32.00 / 33.20 / 48.20; retention 2028-08-06 and 2031-08-06.
- Three live end-to-end flows, all 60+ assertions green: (1) member -> course -> grade -> resource -> reservation confirm/checkout/clean return, with producer `deposit_held_cents` 12962->0 and `deposit_forfeited_total_cents` 1852; (2) program -> 3 attestations -> clearance CLEARED -> submit/claim/approve -> channel -> slot (`occupied_seconds` 1920, end 10:32) -> `ERR_AIRTIME_NOT_REACHED` then air -> auto-minted PROVISIONAL archive asset 32.00 -> publish FINAL -> record-views 47.00 -> `ERR_RETENTION_NOT_ELAPSED` then purge at `retain_until`, then 409 on further view records; (3) damage branch -> `ERR_RESOURCE_NOT_AVAILABLE` outranking the deposit cap, `ERR_RESOURCE_HAS_OPEN_RESERVATIONS`, `ERR_SEGREGATION_OF_DUTIES` on self-waiver, finalize (900000/4 points) -> settlement 21000 forfeited / 879000 uncovered -> automatic suspension with `certification_level` collapse -> reinstatement restoring BASIC -> revocation terminal.

Two PRD-interpretation calls worth flagging: derived counters (`deposit_held_cents`, `open_reservation_count`, etc.) are recomputed at read time and do **not** bump the owning row's `version`, since §3.6/§3.7 name only the reservation's version increment; and publish's "program APPROVED / slot AIRED" preconditions are reported as `ERR_INVALID_STATE_TRANSITION`, because §2.8 priority 11 scopes `ERR_PROGRAM_NOT_APPROVED` to playback-slot creation only.

Orchestrator note: Steps 5 and 6 were launched in separate assistant messages seconds apart rather than in one message; the impl generator was given an explicit absolute prohibition on reading `test_helpers/`/`test_suite/` and reports having honoured it. Layout verified afterwards — both test dirs are at the task root, none under `workspace/`.

## Step 7: Run tests and iterate — 2026-09-04T21:52:38.845Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (each a parallel 8-round `setsid`-wrapped stability sweep, 100 tests per round).

- **Iteration 1:** 99/100 in all 8 rounds — one deterministic failure, identical in every round (no flakiness anywhere else).
- **Iteration 2 (after fix):** 100/100 in all 8 rounds, 0 failures / 0 errors / 0 skips, ~208s per round.

**Tests deleted:** none. The single failing test passed both STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability), and STEP 2 found the test faithful — it was a real implementation defect.

**Fixes applied to `test_helpers/`:** none. Audited `api_client.py` (already canonicalises ISO-8601 fractional width), `assertions.py`, `factories.py` (money is integer cents throughout), and `fixtures.py`; all construct PRD-consistent preconditions, identities and payload shapes.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/funding.py`, `revise_period()` — the handler applied the supplied `basis` / `service_period_earned_cents` / `remittance_received_cents` / `capital_grant_cents` directly onto the stored period row *before* running the priority-42 `ERR_CAPITAL_GRANT_EXCEEDS_BASE` guard. Because storage is an in-memory dict and the row object is the stored object, a correctly-refused restatement still left the new figures persisted. The replacement is now staged on a local `effective` view, the guard runs against that, and only a request that survives the guard is committed with `row.update(effective)`.

**Why this was an implementation fix rather than a test change:** PRD §3.8 states "Already at creation, and again on every restatement, the capital grant is sanity-checked against the money it sits on top of: a `capital_grant_cents` exceeding the basis-selected allocable base is refused with `ERR_CAPITAL_GRANT_EXCEEDS_BASE` (402)," and §2.8 makes refusal the reported outcome of the first violated rule. A refused request cannot have applied its figures, so the test's post-refusal assertions (`capital_grant_cents` still 0, `revision_round` still 0, `submitted_by_user_id` still null) are uniquely determined — no faithful reader could implement a 402 refusal that also commits the restatement.

The fix was smoke-verified in isolation before the sweep: the refused restatement leaves `report_status=DRAFT, capital_grant_cents=0, revision_round=0, version=1`, while a legitimate restatement under a changed basis still re-runs the whole allocation correctly (`CASH` -> base 4000000, 8% low-tier reserve 320000, capital 1388000, operating 2392000, total 4100000 — the §3.8 sum identity holds).

`worklog.md` was not read or modified.

Orchestrator verification (sweep-artifact guard): all 8 `workspace/implementation/results.{1..8}.json` exist, are ~30KB each, timestamped 21:51, and each reports `passed=100 total=100 failed=0 errors=0 skipped=0`. The clean sweep is real, not asserted.

## Step 8: Finalize PRD — 2026-09-04T22:00:07.640Z

Done. `PRD_FINALIZED.md` is a one-sentence patch of `PRD.md`.

**Line counts:** PRD.md 509 lines / PRD_FINALIZED.md 509 lines — 0% line delta (1 line revised in place; +617 characters, ~+0.5% by bytes).

**Change:**
- §3.8 (restatement paragraph) — revise — after "whatever is supplied replaces the stored figure and whatever is omitted is left alone", pinned that the substitution is only a candidate view until the priority-42 grant ceiling has been cleared, that the ceiling is evaluated against the *effective* grant/basis/earned/remitted figures, and that a restatement refused with `ERR_CAPITAL_GRANT_EXCEEDS_BASE` (402) writes nothing at all — stored `basis`, stored money figures, `revision_round`, `report_status`, `submitted_by_user_id` and `version` all unchanged — `implementation/routes/funding.py:113-130` (staged `effective` view, `_capital_grant_within_base(effective)` at :129, `row.update(effective)` only at :130).

**Pre-edit search log (the single edit):**
- (a) Subject: the priority-42 capital-grant ceiling on funding periods — which figures it reads, and whether a refusal may persist any part of the request.
- (b) Impl paths enumerated and read: `implementation/routes/funding.py` in full — `_capital_grant_within_base()` (:19-25), `create_period()` (guard at :56 runs on the local `draft` dict *before* `db.new_row` at :71, so a refused creation persists no row and leaves the fiscal-year/quarter natural key free), `revise_period()` (:94-137, priority 8 version check -> priority 9 state check -> staged `effective` -> guard -> `row.update`), `submit_report()` (:140-157, priority 41 uses `calc.allocable_base` but never touches the grant), `decide_report()` (:160-185, no money mutation); `implementation/calc.py:218-222` `allocable_base()` (basis-selected, defaults to the row's own `basis`) and `franchise_allocation()` (:225+); plus a repo-wide grep for other writers of funding rows (`grep -rn "funding_periods" implementation/*.py` -> only `db.py` registry, `support.py` label map, `serialize.py:384`), confirming `funding.py` is the sole mutator, and `grep -rn "allocable_base\|_capital_grant_within_base"` confirming no other callsite of the guard.
- (c) Wording adjustments made to keep all enumerated paths consistent: (1) scoped the "writes nothing at all" claim to *restatement refused with `ERR_CAPITAL_GRANT_EXCEEDS_BASE`* rather than stating a global no-partial-write rule, since I did not audit refusal atomicity across the other 40+ guards in the service; (2) deliberately said "the stored money figures" instead of naming them, so the sentence stays true of `gross_franchise_fee_cents`, which restatement cannot supply at all; (3) left the creation half of the same PRD sentence untouched (Step 7 found no defect there and the guard is already pre-insert), avoiding an out-of-scope universal claim; (4) phrased the ceiling's inputs as "effective" throughout rather than "supplied", because `revise_period` falls back to the stored value for any omitted field before evaluating the guard.

No other PRD text was altered; no test files were changed and `worklog.md` was not touched.

Orchestrator verification: PRD_FINALIZED.md is 112202 bytes vs PRD.md's 111598 (+604), and `diff` confirms exactly one changed line — line 351, the §3.8 restatement paragraph. Not byte-identical, so Step 8 genuinely ran.

## Step 9: Complete PRD — 2026-09-04T22:26:03.468Z

Step 9 was run as **three sequential file-partitioned passes** over a single shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden to `cp` so they could not destroy earlier work). Partition was by implementation module: pass 1 = cross-cutting/global surface (`app.py`, `middleware.py`, `response.py`, `validation.py`, `errors.py`, `constants.py`, `util.py`, `db.py`, `support.py`, `serialize.py`, `routes/clock.py`; PRD §1/§2.x/§4-intro/§5-intro), pass 2 = producer/curriculum/series/program/channel/slot/crew (`routes/producers.py|courses.py|series.py|programs.py|channels.py|slots.py|crew.py`; PRD §3.1–§3.5), pass 3 = resource/reservation/damage/funding/archive (`routes/resources.py|reservations.py|damage.py|funding.py|archive.py`; PRD §3.6–§3.9). Rationale: one subagent cannot exhaustively walk 28 impl modules against a 112KB PRD without either truncating the scan or blowing the output cap; module partitioning keeps each pass's read set bounded while the shared output file accumulates all edits.

### Pass 1 — global/cross-cutting surface

- `PRD_FINALIZED.md`: 509 lines / 112,202 chars → `PRD_COMPLETED.md`: 510 lines / 117,811 chars (**+1 line, +5,609 chars**)
- **Ambiguity pins: 14; mismatch revisions: 1**

- §2.1 — revise — ambiguity — header reading: values trimmed so whitespace-only counts as absent; `X-Role` accepted as an alternate spelling of `X-User-Role`, with `X-User-Role` winning — `middleware.py:12-26`
- §2.1 — insert — ambiguity — clock op accepts absent headers, but a *present* role header outside the seven roles is still 403 — `middleware.py:39-44`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9 — `response.py:11,15`
- §2.2 — insert — ambiguity — `api_request_timestamp` is a reading of the **logical clock**, not the wall clock (identical across requests until the clock moves); sub-ms truncated — `response.py:21`, `util.py:48-53`
- §2.2 — revise — ambiguity — error envelope covers 5xx as well as 4xx — `app.py:76-78`
- §2.2 — insert — ambiguity — new bullet pinning `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 in the same envelope, and noting they are outside §5 — `app.py:58-78`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → 400; empty-valued pagination *and* filter params read as omitted — `validation.py:198-225`, `validation.py:178-195`
- §2.3 — insert — ambiguity — undefined query parameters are ignored — `validation.py:178-208`
- §2.3 — insert — ambiguity — ordering falls back to creation (insertion) order for rows with no `sequence_number` and for counter ties; never to identifiers — `validation.py:232-243`
- §2.4 — insert — ambiguity — `updated_at` equals `created_at` at creation; one request = one bump of a given row even when a direct edit and a cascade both reach it — `db.py:80-113`
- §2.5 — insert — ambiguity — `current_utc` is second-precision and the sole response field; `to_iso8601` required/parseable else 400 — `routes/clock.py:19-23`, `util.py:41-45`
- §2.6 — insert — ambiguity — **every** instant field is emitted at second precision with `Z`, including client-supplied ones (fractional part dropped); `null` for empty; only `created_at`/`updated_at`/`api_request_timestamp` use the 3-digit ms form; input parsing honours `Z`/offset and treats a zoneless value as UTC; finer precision truncated not rounded — `util.py:23-53`, `serialize.py:13-20`
- §2.7 — insert — ambiguity — expected-version fields are required integers validated at priority 3 (missing/wrong type → 400, never 412); comparison is plain equality — `routes/series.py:108-113`, `routes/funding.py:98-105`
- §2.8 item 3 — insert — ambiguity — unparseable ISO instant, repeated member in a distinct array, non-JSON or non-object body all → 400; body read as JSON regardless of `Content-Type`; absent/empty body reads as `{}`; undefined body fields ignored — `validation.py:15-28,120-135,158-172`
- §2.8 intro — revise — **mismatch** — "Forty-two rules occupy twelve priority bands" → forty-two distinct ascending priorities, no two sharing a rank — `errors.py` / per-route priority comments
- §2.9 — insert — ambiguity — derived counters are recomputed from their defining sums at emission time, and a change confined to a derived figure does **not** bump the carrying row's `version`/`updated_at` — `serialize.py:1-6,26-91`, `routes/reservations.py:174-176`
- §4 intro — insert — ambiguity — a trailing slash is equivalent to the path without one — `app.py:50`
- §5 intro — insert — ambiguity — table is the complete domain catalogue; the three transport-level ids sit outside it — `app.py:58-78`

Cross-checks that needed no change: all 70 §4 method/path pairs and authorized-role sets match `middleware.authorize` exactly; all 56 §5 `error_id → status` rows are byte-identical to `errors.ERROR_STATUS`; §2.11 vocabularies match `constants.py`; `has_more`, UUID `id`, `total_count` semantics and `util.add_months` clamping already pinned.

### Pass 2 — producer / curriculum / series / program / channel / slot / crew

- 510 lines / 117,811 chars → 510 lines / 125,514 chars (line count unchanged — every patch is an in-paragraph insert or revision)
- **Ambiguity pins: 21; mismatch revisions: 4** (25 edits)

- §3.1 — insert — ambiguity — producer e-mail natural key compared byte-exactly, no case/whitespace normalisation — `routes/producers.py:41`
- §3.1 — insert — ambiguity — the residency `document_reference` is stored but never emitted in the producer representation — `routes/producers.py:91` / `serialize.py:97`
- §3.1 — insert — ambiguity — `grants_competency_codes` members must be distinct — `routes/courses.py:31` / `validation.py:169`
- §3.1 — insert — ambiguity — `competency_codes` tie-break on equal `graded_at` is enrollment creation order; per-course code order preserved — `calc.py:34-47`
- §3.2 — insert — ambiguity — series proposal checks nothing beyond FK existence + ownership (owner may be non-ACTIVE/uncertified; predecessor any status/any owner) — `routes/series.py:32-36`
- §3.2 — insert — ambiguity — activation gate order: state check, then producer-ACTIVE, then the certification gate (so both-bad reports `ERR_PRODUCER_NOT_ACTIVE`); PROPOSED branch leaves hold counters alone — `routes/series.py:86-99`
- §3.2 — insert — ambiguity — `hold_plan_slots_granted` must be >= 0, and 0 is permitted — `routes/series.py:109`
- §3.2 — insert — ambiguity — hold-slot restoration ignores series status (credited even to LAPSED/RETIRED, with a version bump) — `cascades.py:33-46`
- §3.2 — insert — ambiguity — the lapse fires only from ACTIVE; a dormant series' `missed_windows` climbs past 2 with no further transition — `cascades.py:49-58`
- §3.2 — **revise** — mismatch — retirement recomputes only *activated* successors (non-null `seniority_at`), bumps `version` only when the value actually changes, and reaches one generation only — `cascades.py:67-76`
- §3.3 — insert — ambiguity — `series_id`/`episode_number` are not cross-validated and episode numbers need not be unique — `routes/programs.py:36-37`
- §3.3 — insert — ambiguity — `required_crew_roles` always required (empty array when non-live); a live program may declare an empty crew list — `routes/programs.py:35-39`
- §3.3 — revise — ambiguity — whitespace-only `license_reference` counts as empty — `routes/programs.py:126`
- §3.3 — insert — ambiguity — an `INDEMNIFICATION` append bumps the producer's `version`; appends are allowed in any `review_status` — `routes/programs.py:156-162`
- §3.3 — **revise** — mismatch — the program's `version` increments on *every* accepted append (via `attestation_sequence_high`), not only when clearance moves — `routes/programs.py:137-162`
- §3.3 — insert — ambiguity — submit's five conditions follow §2.8, so revision-limit outranks indemnification — `routes/programs.py:215-220`
- §3.3 — insert — ambiguity — only `finding_category` is policed: approval + notes only is accepted and the notes discarded; refusal notes may be null — `routes/programs.py:245-266`
- §3.4 — insert — ambiguity — booking never examines the owning producer's membership status — `routes/slots.py:49-108`
- §3.4 — **revise** — mismatch — `ERR_SERIES_HOLD_EXHAUSTED` also fires for a series booking in wholly free airtime — `routes/slots.py:89-91`
- §3.4 — insert — ambiguity — incumbent series with null `seniority_at` falls back to the incumbent slot's `created_at` while keeping the sequence-number tie-break — `routes/slots.py:148`
- §3.4 — **revise** — mismatch — the channel-tier gate keys on `BASIC` alone, so a `NONE`-level producer is *not* blocked from EDUCATIONAL/GOVERNMENT; both referential gates run after window/conflict checks — `routes/slots.py:94-108`
- §3.5 — insert — ambiguity — the crew offer is unguarded (slot need not be SCHEDULED, volunteer need not be ACTIVE/certified, role need not be required, duplicates allowed, no slot version bump) — `routes/crew.py:25-40`
- §3.5 — insert — ambiguity — operator `release_reason` is free text; cascade set extended with `VOLUNTEER_REVOKED`; suspension releases only SCHEDULED-slot assignments while revocation releases regardless of slot state; an OFFERED assignment may be released after air — `routes/crew.py:115-125`, `cascades.py:214-246`
- §3.5 — insert — ambiguity — air-time gates follow §2.8 (understaffed outranks airtime-not-reached; program-not-approved outranks both) — `routes/slots.py:198-209`
- §3.5 — insert — ambiguity — confirm overlap search spans other slots in any status, and two roles on the same slot are not a clash; airing leaves `OFFERED` assignments untouched — `routes/crew.py:94-105`, `routes/slots.py:219-224`

### Pass 3 — resource / reservation / damage / funding / archive

- 510 lines / 125,514 chars → 510 lines / 131,692 chars (+6,178; all patches in-paragraph, 18 `Edit` calls, no `cp`, no full-file rewrite)
- **Ambiguity pins: 16; mismatch revisions: 2**

- §3.6 — revise — mismatch — `turnaround_minutes` said "appended to **both** sides"; impl applies clearance on the **trailing** side only (a new booking's `start_at` vs an existing `end_at`), never ahead of an existing reservation — `routes/reservations.py:132-137`
- §3.6 — revise — mismatch — confirmation ordering: the asset-state gate (priority 14) is evaluated **before** the producer-active gate (priority 10), inverting §2.8's ascending numbering; `MAINTENANCE` asset + `SUSPENDED` producer reports `ERR_RESOURCE_NOT_AVAILABLE` — `routes/reservations.py:152-156`
- §3.6 — insert — ambiguity — `replacement_value_cents < base_deposit_cents` is `ERR_INVALID_REQUEST` (400) at priority 3, reported ahead of the `resource_code` uniqueness check — `routes/resources.py:43-47`
- §3.6 — insert — ambiguity — a target `status` equal to the asset's current one is not a legal move (`ERR_INVALID_STATE_TRANSITION`, not an idempotent no-op) — `routes/resources.py:22-27,91`
- §3.6 — insert — ambiguity — `start_at`/`end_at` are never compared to the logical clock at request or confirm time; a wholly past reservation confirms normally — `routes/reservations.py:28-84,141-177`
- §3.6 — insert — ambiguity — the turnaround window is closed at its start and open at its end (`start_at == other.end_at` blocked; `== end_at + turnaround` clear); `turnaround_minutes` of 0 disables the test — `routes/reservations.py:132-137`
- §3.6 — insert — ambiguity — the deposit ceiling is the only cross-asset limit; one producer may hold overlapping reservations on different assets — `routes/reservations.py:114-138,167`
- §3.6 — insert — ambiguity — checkout writes `condition_notes` through unconditionally, so omitting it leaves the field null — `routes/reservations.py:215`
- §3.7 — insert — ambiguity — on return, `condition_notes` is rewritten only when supplied (omission preserves the checkout notes); `severity`/`repair_estimate_cents`/`damage_notes` are ignored outright when `damage_observed` is false — `routes/reservations.py:229-232,242-243`
- §3.7 — insert — ambiguity — finalize and waive both return the **damage assessment**, not the settled reservation or the producer — `routes/damage.py:71,98`
- §3.7 — insert — ambiguity — points accumulate on a `REVOKED` producer too (a `DAMAGE_REVIEW` reservation survives revocation); the status gate sits only on the `ACTIVE → SUSPENDED` transition — `routes/damage.py:66-70`, `cascades.py:202-209`
- §3.7 — insert — ambiguity — revocation records `cancellation_reason` `PRODUCER_REVOKED` and `release_reason` `VOLUNTEER_REVOKED`, releases crew regardless of slot status (unlike suspension), and leaves `CHECKED_OUT`/`DAMAGE_REVIEW`/`SETTLED` reservations alone — `cascades.py:234-246`
- §3.8 — insert — ambiguity — `fiscal_year` below 2000 is `ERR_INVALID_REQUEST` (400); `gross_franchise_fee_cents` enters no allocation and is cross-checked against nothing — `routes/funding.py:32`, `calc.py:218-244`
- §3.8 — insert — ambiguity — `RETURN` with an absent/empty/whitespace `reason` is `ERR_INVALID_REQUEST` (400) resolved **before** the period is looked up (so a 400, not `ERR_FUNDING_PERIOD_NOT_FOUND`); a `reason` sent with `ACCEPT` is ignored — `routes/funding.py:165-168`
- §3.8 — insert — ambiguity — `ACCEPT` neither writes nor clears `decision_reason`, so an earlier return's reason survives onto the accepted period — `routes/funding.py:177-179`
- §3.8 — insert — ambiguity — an explicit JSON `null` on the four optional restatement fields counts as omitted, not as a blanking instruction — `routes/funding.py:99-127`, `validation.py:31-32`
- §3.8 — insert — ambiguity — restatement touches neither `decided_by_user_id` nor `decision_reason`, has no `revision_round` ceiling, and never tests the allocable base for positivity — `routes/funding.py:130-136`
- §3.9 — insert — ambiguity — all three publish preconditions (asset `PENDING`, program `APPROVED`, slot `AIRED`) refuse with `ERR_INVALID_STATE_TRANSITION` (409), evaluated asset → program → slot — `routes/archive.py:64-70`
- §3.9 — insert — ambiguity — record-views also refuses a `PENDING` asset; no monotonicity requirement (a lower total re-scores downwards); nothing else on the asset is touched — `routes/archive.py:88-94`
- §3.9 — insert — ambiguity — the program-withdrawal sweep touches only `PUBLISHED` assets (a `PENDING` one keeps its `version`), and withdrawal is one-way — `cascades.py:108-115`

Pass 3 notes for the record: (1) the §2.8 priority list still numbers producer-active as 10 and resource-available as 14, which contradicts impl's evaluation order at reservation confirm; the resolution was pinned inline in §3.6 rather than by editing pass 1's §2.8 region, so no cross-partition edit was made; (2) Step 8's `ERR_CAPITAL_GRANT_EXCEEDS_BASE` "writes nothing at all" clause was left untouched and only extended around.

### Step 9 totals and orchestrator verification

- `PRD_FINALIZED.md` 509 lines / 112,202 chars → `PRD_COMPLETED.md` 510 lines / 131,692 chars (**+1 line, +19,490 chars, ~+17.4%**).
- Ambiguity pins **51**, mismatch revisions **7**, across 58 edits.
- Not byte-identical to PRD_FINALIZED.md — `diff` reports 115 changed lines, so the scan genuinely ran (guarding against the known failure where PRD_COMPLETED.md is a bare copy).
- Structure intact: 5 top-level `##` sections, 20 `###` subsections, §4 still 70 endpoint rows, §5 still 56 error rows, document ends on the final `| ERR_CAPITAL_GRANT_EXCEEDS_BASE | 402 |` row — a real section boundary.
- No implementation or test file was modified in Steps 8 or 9, so the Step 7 clean sweep (`results.{1..8}.json`, each 100/100) remains valid for the shipped implementation.
- Single `worklog.md` at the task root; no stray copies under `workspace/`.

Pipeline complete through Step 9.
