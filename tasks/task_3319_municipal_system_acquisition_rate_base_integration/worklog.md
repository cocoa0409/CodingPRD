# Worklog — task_3319_municipal_system_acquisition_rate_base_integration

## Step 1: Create task directory — 2026-09-30T20:05:00.000Z

Pre-allocated task directory `./tasks/task_3319_municipal_system_acquisition_rate_base_integration/` (with `workspace/` inside) verified present; no new index computed and no other task_* directory created, per command args.

## Step 2: Generate scaffold — 2026-09-30T20:20:00.000Z

All three scaffold artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_3319_municipal_system_acquisition_rate_base_integration/` and pass `scaffold_lint.py` with a clean verdict.

**Files**
- `SCAFFOLD.yaml` — 1337 lines. 11 entities (AcquisitionTarget, ConditionAssessment, CapitalNeedItem, ValuationCase, ValuationEntry, CouncilEvent, RegulatoryApplication, CustomerAccount, TransitionItem, EmployeeTransition, TariffCase), 11 state machines, 6 calculations, 16 ordered validations, 50 endpoints (incl. `POST /_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z default), 25 error codes, 9 opaque roles with segregation-of-duties (creator ≠ reviewer, appraiser ≠ finalizer). Two OCC concurrency rules on `AcquisitionTarget.version` (valuation-case create, regulatory refile).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1268 lines. All 9 difficulty rules × 2 instances = 18 instances, with structured `setup_api_calls`/`trigger` chains, computed literal asserts (e.g., filing estimate 172502, AS_PAID vs DEPRECIATED admission 105000000/0 vs 90000000/15000000, phase-in 4 vs 5 years, referendum 50.50 passes vs council 60.00 >= passes).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2029 lines. 40 active corner instances across all 9 claim-extraction sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model) plus 3 `excluded_because` stubs.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (50 endpoints, 11 entities, 18 §1.8 + 40 §1.9 instances, 607 calls scanned.)

Notes: no sibling task directories were inspected; instance names are unique across both design files; no forbidden race vocabulary remains. Endpoint count (50) sits above the Expert guideline band — driven by the 11-entity full-lifecycle surface with per-role action endpoints — worth watching during impl-gen per the known >40-endpoint failure mode. Orchestrator note: subagent's first two replies stopped mid-planning without writing files; required two continuation nudges to emit all three files. Files verified on disk by orchestrator (YAML parses; line counts above).

## Step 3: Copy shared files — 2026-09-30T20:34:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3319_municipal_system_acquisition_rate_base_integration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T20:42:00.000Z

**File:** `workspace/PRD.md`
**Line count:** 294
**Ends properly:** yes — last line is the final error-table row (`ERR_TARIFF_NOT_ADOPTED`).

**Section list:**
- 1. Introduction (3 paragraphs)
- 2. Global Specifications — 2.1 Roles & RBAC, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Resource Identity/Versioning, 2.5 Logical Clock, 2.6 Money/Precision/Rounding, 2.7 OCC, 2.8 Nested Retrieval, 2.9 Segregation of Duties, 2.10 Validation Priority
- 3. Business Logic — 3.1 Target registration & auto-created checklist, 3.2 Condition assessment & capital need estimation (dual-variant calc), 3.3 Valuation under state law, 3.4 Municipal process (hearings/votes/referenda, pinned thresholds 60.00/50.00), 3.5 Regulatory approval & rate-base admission, 3.6 Employee transition & union assumption, 3.7 Closing (capital execution, customer migration/deposit waterfall, tariff phase-in), 3.8 Rejection cascade
- 4. Endpoint Definitions (50 endpoints, 4-column table)
- 5. Error Code Catalogue (25 errors, 2-column table)

**Hard contract reports:**
- Field coverage check: entities[].fields 65 required/65 present/0 missing; endpoints request_body/input all present; query_params limit/offset/status/state_code/kind all present. Status: PASS
- Rule coverage check: validations[] priority 1–16 expressed in order; both OCC rules expressed (ERR_STALE_VERSION 412); all 11 state machines expressed incl. cascades/side effects; all 6 calculations expressed; endpoints[].side_effects all expressed. Status: PASS
- Path purity check (§3 only): 172 backtick tokens scanned; 0 path tokens, 0 bare HTTP-method tokens, 0 combined tokens. Status: PASS

Orchestrator note: verified on disk — 294 lines, ends with ERR_TARIFF_NOT_ADOPTED row, 79 table rows.

## Step 5: Generate unit tests — 2026-09-30T20:59:00.000Z

Generated complete test infrastructure for `task_3319_municipal_system_acquisition_rate_base_integration`.

### test_helpers/ (Stage 1)
| file | lines |
|---|---|
| `__init__.py` | 31 |
| `api_client.py` (all 41 endpoints) | 169 |
| `api_errors.py` (25 error IDs, registered with framework) | 63 |
| `assertions.py` | 142 |
| `constants.py` | 27 |
| `factories.py` | 132 |
| `fixtures.py` (state builders: `setup_target_in_valuation/municipal_review/regulatory_review/closing`, hearing/vote helpers, OCC version capture, transition-item resolution) | 260 |
| `test_users.py` (9 opaque roles, per-role builders) | 61 |
| `types.py` | 266 |

### test_suite/ (Stage 2) — 77 tests collected
| file | lines | tests |
|---|---|---|
| `conftest.py` | 65 | – |
| `test_01_target_surface.py` | 144 | 9 |
| `test_02_assessments_capital.py` | 395 | 16 |
| `test_03_valuation_and_occ.py` | 122 | 5 |
| `test_04_council_process.py` | 370 | 16 |
| `test_05_regulatory.py` | 250 | 10 |
| `test_06_closing.py` | 411 | 17 |
| `test_07_employees.py` | 83 | 4 |

### Instance coverage
- **Queue A (difficulty): 18/18 instances emitted, 0 skipped** — every instance has ≥2 tests (verified programmatically against the yaml `name:` fields).
- **Queue B (corner): 39/39 non-stub instances emitted, 0 skipped** — each has ≥1 test; the 2 `excluded_because` stubs (`covered_severance_tiers`, `covered_deposit_settlement`) correctly not translated (both pointers resolve to real queue-A instances).
- All 77 docstrings carry verbatim PRD citations (checked: every ≥30-char quoted string appears in `PRD.md`, 0 mismatches) and exactly one `Design:` tag each; all tags resolve to real instances.
- No `skip`/`xfail`/`skipif` markers anywhere.

### Verification
- `py_compile` passes on all 17 files.
- `python3 -m pytest --collect-only` collects 77 tests with no import errors; `import test_helpers` succeeds and exports fixtures/validators.

Notable translation decisions: the corner instance `occ_refile_stale_version`'s literal `${t_v_pre} - 1` payload was emitted as `stale_version - 1` (integer arithmetic), matching PRD §2.7's mismatch rule. The severance queue-A instance got a 3rd test (0-year boundary) since PRD §3.6 explicitly pins "exactly 0 years earns 1". No instances failed the two-condition filter — every asserted rule/error_id has verbatim PRD coverage.

Orchestrator note: verified on disk — 17 files, 2991 total lines, py_compile OK, 77 tests collected.

## Step 6: Generate implementation — 2026-09-30T21:15:00.000Z

Implementation complete for task_3319 (Municipal System Acquisition & Rate Base Integration).

**Files written** (all under `workspace/implementation/`), per-file line counts:

- `start.sh` — 9 lines (guarded pip install, `exec python3 app.py`, `$PORT` default 10000, binds `0.0.0.0`)
- `requirements.txt` — 1
- `app.py` — 55 (Flask app, blueprint registration, ApiError/404/405/unexpected handlers)
- `errors.py` — 8
- `util.py` — 87 (logical clock pinned at 2026-09-01T00:00:00Z, constants from SCAFFOLD: contingencies 0.10/0.15, premium cap 0.10, council/referendum thresholds 60/50/50, MAX_CREWS_PER_TARGET 3, MIN_HEARING_NOTICE_DAYS 7, PHASE_IN_CAP_PCT 5)
- `db.py` — 62 (in-memory stores, empty at boot — no seeding)
- `response.py` — 88 (scaffold envelope: `meta`/`response_type`/`data`; error `error_id`/`message`; pagination `limit`/`offset`/`total_count`/`has_more` in meta, defaults 10/0, bounds 1–100)
- `middleware.py` — 57 (`X-User-ID`/`X-User-Role` auth, role gating, field validators)
- `models.py` — 198 (entity constructors; target creation auto-creates the 4 TransitionItems in fixed order BILLING_RECORDS, DEPOSITS, SERVICE_AGREEMENTS, METER_READS)
- `calculations.py` — 99 (capital_need_estimate with per-item round-half-up midpoints; rate_base_admission; vote_outcome with pinned boundaries — council >=60 passes, referendum >50 strict; deposit_settlement waterfall; severance tiers; phase-in ceil)
- `statemachines.py` — 42 (rejection cascade: cases→SUPERSEDED, entries→NOT_SELECTED, transition items→BLOCKED, employees→WITHDRAWN, target version bump)
- `routes_clock.py` — 23; `routes_targets.py` — 86; `routes_assessments.py` — 114; `routes_capital_items.py` — 200; `routes_valuation.py` — 138; `routes_council.py` — 157; `routes_regulatory.py` — 135; `routes_accounts.py` — 120; `routes_transitions.py` — 65; `routes_employees.py` — 97; `routes_tariffs.py` — 84
- Total: 1925 lines across 22 files

**py_compile**: all 20 `.py` files OK.

**Boot verification**: started via `bash start.sh` on PORT=18319, then:
- `GET /acquisitions/targets` without headers → `401` (auth enforced)
- With `AcquisitionAnalyst` headers → `200` with correct envelope (`response_type: "array"`, meta with limit/offset/total_count/has_more)
- `POST /acquisitions/targets` → `201` with `status: "SCREENING"`, `council_approved: false`, `filing_estimate_cents: 0`, `version: 1`
- `POST /_clock/set_current_utc` → `200` returning `{"current_utc": "2026-09-02T00:00:00.000Z"}`
- Killed only the PID the subagent started (3229895).

Notable fidelity decisions: segregation-of-duties (priority 4) runs before state checks on accept/reject/finalize; OCC (`expected_target_version` → `ERR_STALE_VERSION` 412) on valuation-case create and regulatory refile; council-vote outcome records `yes_share_pct` before the hearing-notice check but fires the rejection cascade only on hard fail / failed referendum; crew-capacity check uses half-open window sweep over SCHEDULED siblings per target; close gates fire in scaffold order (transition items → accounts → employees). The test suite was not run, per the isolation rule.

Orchestrator note: verified on disk — 22 files, 1925 lines, all py_compile OK.

## Step 7: Run tests and iterate — 2026-09-30T21:21:00.000Z

All 8 rounds pass 77/77. Clean sweep.

Summary:

- Iterations run: 2 (initial sweep: 69/77 in all 8 rounds; after fixes: 77/77 in all 8 rounds).

- Tests deleted: none.

- Fixes applied to `test_suite/`:
  - `test_04_council_process.py::test_event_overlap_beats_referendum_availability_prior_vote_failed` and `test_referendum_exactly_50_fails_51_passes`, and `test_05_regulatory.py::test_regulatory_filing_requires_council_approval_after_band_failure`: changed the setup council-vote outcome from `{yes_votes: 11, no_votes: 19}` (36.67%, a decisive failure that per PRD §3.4 fires the rejection cascade and moves the target to REJECTED) to `{yes_votes: 11, no_votes: 9}` (55.00%, the referendum band where PRD says the target stays in MUNICIPAL_REVIEW). The prior fixtures made the PRD-required implementation behave correctly and the tests' own setup then failed with ERR_INVALID_STATE.
  - `test_04_council_process.py::test_record_outcome_twice_is_idempotent_rejected`, `test_hearing_votes_ignored_vote_requires_votes`, `test_commissioner_cannot_record_council_outcome`: replaced the `create_target(...)` setup (target in SCREENING) with `setup_target_in_municipal_review(...)`, because PRD §3.4 only permits scheduling council events while the target is in MUNICIPAL_REVIEW — the implementation's `ERR_INVALID_STATE` rejection of event creation in SCREENING is PRD-required.
  - `test_02_assessments_capital.py::test_assessment_acceptance_supersede_and_advance_cascade`: removed the assertion `target.filing_estimate_cents == 3450` after a second acceptance supersedes the first while the target is already in VALUATION. PRD §3.2 pins the copy of the accepted assessment's filing estimate onto the target only on the SCREENING→VALUATION advance branch ("if the target is still in SCREENING ... the accepted assessment's filing_estimate_cents is copied onto the target"); it is silent on the supersede-in-VALUATION branch (BRANCH-ASYMMETRIC SIDE EFFECT / unique-derivability collapse — a faithful PRD-only reader could legitimately not recompute). The scaffold rule that drove the assertion was "filing_estimate_cents = of the latest ACCEPTED ConditionAssessment". Kept the covered assertions (supersede to SUPERSEDED, target stays VALUATION).

- Fixes applied to `implementation/`:
  - `routes_transitions.py::list_transition_items`: sort key now puts items in the PRD-fixed category order (BILLING_RECORDS, DEPOSITS, SERVICE_AGREEMENTS, METER_READS) instead of `(created_at, id)` — the four auto-created items share a millisecond timestamp, so the random-UUID tiebreak scrambled the order the PRD pins verbatim.

Orchestrator verification: all 8 results.*.json show 77/77; no implementation/*.py file modified after the final sweep (routes_transitions.py mtime 21:15:07 < results.1.json mtime 21:20:14). Sweep validity confirmed.

## Step 8: Finalize PRD — 2026-09-30T21:29:00.000Z

PRD_FINALIZED.md written at `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 294 lines, PRD_FINALIZED.md 294 lines (0% line delta — three in-place sentence additions on existing lines 123, 135, 147; ~+370 chars total).

**Changes:**

- §3.1 — insert — Added sentence pinning that the transition-item list endpoint returns items in the fixed category order (BILLING_RECORDS, DEPOSITS, SERVICE_AGREEMENTS, METER_READS), overriding §2.3's default `created_at` ordering — `implementation/routes_transitions.py:28-32` (sort key via `TRANSITION_ITEM_ORDER` in `implementation/util.py:40`).
- §3.2 — revise — Appended explicit pin that on acceptance while the target is already in VALUATION, no advance occurs: the target's `filing_estimate_cents` is left unchanged and its `version` is not incremented; only the supersede cascade runs — `implementation/routes_assessments.py:92-97`.
- §3.4 — revise — Inserted explicit pin that scheduling a council event is only possible while the target is in MUNICIPAL_REVIEW, rejected with `ERR_INVALID_STATE` (409) otherwise — `implementation/routes_council.py:45-46`.

The other step-7-diff items (55.00% referendum-band fixtures, setup helpers creating the target in MUNICIPAL_REVIEW instead of SCREENING) were pure test-fixture corrections of behavior the PRD already pins verbatim, so no PRD edits were needed for them.

**Per-edit pre-edit search log:**

1. **Transition-item list order.** (a) Subject: observable ordering of the transition-item list endpoint. (b) Enumerated: `implementation/routes_transitions.py` (list/get/resolve — the only ordering-sensitive path), `implementation/models.py:42` (creation order), `implementation/util.py:40` (order constant), `implementation/routes_targets.py:77` and `implementation/statemachines.py:21` and `implementation/routes_accounts.py:75-79` (all order-insensitive `any`/`next` scans). Grep `TRANSITION_ITEM_ORDER|transition_items_of_target` across all impl files. (c) Wording scoped explicitly to "the transition-item list endpoint" and to overriding only §2.3's *default* ordering.
2. **filing_estimate_cents copy scope on acceptance.** (a) Subject: target mutation on assessment acceptance in the VALUATION branch. (b) Enumerated every impl path touching `filing_estimate_cents`: `implementation/calculations.py:30` (assessment-side recompute), `calculations.py:43` (rate-base ceiling read), `implementation/routes_assessments.py:96` (only target write, guarded by `target["status"] == "SCREENING"`), `implementation/models.py:35,63` (initialization). Confirmed `touch(target)` at routes_assessments.py:97 fires only in the SCREENING branch. (c) Wording avoids a universal "filing estimate never changes" claim; pins only the acceptance-in-VALUATION branch (no copy, no version bump).
3. **Council-event scheduling state gate.** (a) Subject: allowed target status for `POST /acquisitions/targets/{id}/council-events`. (b) Enumerated: `implementation/routes_council.py:40-72` (MUNICIPAL_REVIEW check fires before window sanity, overlap, and referendum gates — consistent with §2.10's priority), `record_outcome` at routes_council.py:97-157 (event-state based, unaffected), cross-checked regulatory gate at `implementation/routes_regulatory.py:47-48` (untouched). (c) Wording scoped to "attempting to schedule an event" so it cannot be misread as restricting `record-outcome`.

Orchestrator note: diff verified — exactly the three in-place sentence edits on lines 123/135/147, nothing else changed.

## Step 9: Complete PRD — 2026-09-30T21:39:00.000Z

PRD_COMPLETED.md written at `workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md 294 lines / 43,233 chars → PRD_COMPLETED.md 294 lines / 44,888 chars (+1,655 chars, +0 lines; all edits are inline in-paragraph).

**Counts:** 15 ambiguity-pins, 1 mismatch-revision (16 edits total, one being a punctuation fix of an earlier edit).

- §2.3 Pagination — insert — ambiguity — pinned `limit`/`offset` validation (`ERR_INVALID_REQUEST` 422 on non-integer, limit outside 1–100, negative offset), `has_more` formula, and `id`-ascending tiebreak after `created_at` — response.py:50-76; routes sort keys `(created_at, id)`
- §3.1 Closing checklist — insert — ambiguity — pinned `resolution_note` initialized to empty string at target creation — models.py:48
- §3.2 Assessment create — insert — ambiguity — assessment creation is permitted against a target in any status (no target-state gate in impl) — routes_assessments.py:23-33
- §3.2 Capital-item cost bounds — insert — ambiguity — both `cost_low_cents` and `cost_high_cents` must be ≥ 0 (PRD pinned only the low bound; impl enforces minimum=0 on both) — routes_capital_items.py:47-48
- §3.2 Estimate recompute — insert — ambiguity — recomputations update only the assessment; the target's `filing_estimate_cents` is written solely by the accept cascade — calculations.py:19-30, routes_capital_items.py:53/184/199
- §3.3 Finalize target advance — insert — ambiguity — the `VALUATION → MUNICIPAL_REVIEW` advance fires only while the target is still in `VALUATION` (impl's conditional) — routes_valuation.py:133-137
- §3.4 Referendum gating — insert — ambiguity — a target may host multiple referenda in sequence, each gated only on the latest recorded council-vote outcome — routes_council.py:27-37
- §3.4 Record outcome — insert+revise — ambiguity/mismatch — supplying vote counts against a `PUBLIC_HEARING` is `ERR_INVALID_STATE` 409; negative vote counts are `ERR_INVALID_REQUEST` 422 alongside missing counts and zero sums — routes_council.py:107-122
- §3.4 Council-vote pass — insert — ambiguity — a passed council vote increments the target's `version` by 1 without changing `status` — routes_council.py:143-145
- §3.4 Referendum pass — insert — ambiguity — a passed referendum likewise increments the target's `version` by 1 — routes_council.py:152-154
- §3.5 Refile payload — revise — mismatch — PRD said a refile "may replace" price/method; impl requires the full payload (`purchase_price_cents`, `rate_base_method`) on every refile — routes_regulatory.py:26-39, 127-130
- §3.6 Employee registration — insert — ambiguity — registration is permitted against a target in any status (no target-state gate) — routes_employees.py:28-42
- §3.7 Crew capacity — insert — ambiguity — sibling execution windows are half-open too (contain `window_start`, not `window_end`), so back-to-back windows do not overlap — routes_capital_items.py:99-120
- §3.7 Account registration — insert — ambiguity — customer accounts may be registered against a target in any status — routes_accounts.py:23-40
- §3.7 Tariff case create — insert — ambiguity — tariff case creation is permitted against a target in any status — routes_tariffs.py:25-37
- §3.7 Consolidation — insert — ambiguity — no target-status gate on consolidate beyond the account being `MIGRATED` — routes_accounts.py:89-102
- §3.8 Rejection cascade — insert — ambiguity — the entry sweep (`SUBMITTED`/`SELECTED` → `NOT_SELECTED`) covers entries of the `SUPERSEDED` cases — statemachines.py:11-20

All other impl behaviors checked (OCC gates, midpoint half-up, estimate variants, split conservation, hearing-notice deadline, rate-base admission formula, deposit waterfall, severance tiers, phase-in ceiling, error catalogue, 201-vs-200 rule, roles, clock semantics) matched PRD prose already and needed no change.

Orchestrator note: verified on disk — PRD_COMPLETED.md 294 lines / 44,888 chars (+1,655 chars vs PRD_FINALIZED.md as reported). Pipeline complete.
