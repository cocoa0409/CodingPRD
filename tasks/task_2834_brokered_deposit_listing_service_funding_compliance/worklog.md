# Worklog — task_2834_brokered_deposit_listing_service_funding_compliance

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `tasks/task_2834_brokered_deposit_listing_service_funding_compliance/` and `.../workspace/` at the pre-assigned path. Index fixed by scenario number (2834); no auto-allocation scan performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T06:03:00.000Z

All three scaffold artifacts for task 2834 are complete and the linter is clean.

**Output directory** `/home/ubuntu/github/CodingPRD/tasks/task_2834_brokered_deposit_listing_service_funding_compliance/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2925 | 168,518 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1848 | 130,706 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4567 | 320,539 |

**SCAFFOLD.yaml (§1.0–§1.7)** — 12 entities: Institution, NationalRateCap, Broker, BrokerAgreement, PrimaryPurposeException, DepositProgram, DepositClassification, DepositPlacement, RateCapCheck, ConcentrationLimit, LiquidityContingencyPlan, CallReportFiling. **46 endpoints** (no DELETE route anywhere; the single PATCH is `/institutions/{id}/capital-category`), 7 state-machine blocks (DepositPlacement carries two parallel dimensions: `funding_status` and `compliance_status`), 2 concurrency rules, 19 calculations, 50 validations with a strict priority ladder 1–50, 50 error codes, 6 roles (`role_model: segregation_of_duties`, with `BrokerRepresentative` as `entity_backed:Broker`). Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; topology `graph`; shape `cyclic`; `immediate` consistency. Contains neither forbidden top-level key.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single key `scaffold_difficulty_design`; **9 rules / 22 instances**: dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (3), boundary_precision_check (3), cross_entity_state_dependency (3), resource_temporal_overlap (2), compensating_invariant (2).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single key `scaffold_corner_design`; all nine claim-extraction-guide sections, **79 instances (67 full recipes + 12 `excluded_because:` stubs)**: entities 12, state_machines 13, calculations 14, validations 9, endpoints 6, errors 14, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. Every one of the 50 error codes is triggerable across §1.8+§1.9; all 12 stubs cite a real `<rule_id> / <instance_name>` pair, and the 101 instance names across both design files are unique.

**Lint verdict** (verbatim):
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2834_brokered_deposit_listing_service_funding_compliance/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2834_brokered_deposit_listing_service_funding_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2834_brokered_deposit_listing_service_funding_compliance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1001

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes for the caller:
- The `scenario:` key holds the scenario text verbatim as instructed, which means it still begins with the line `Generate task harder than expert level!`. That directive is known to leak into PRD.md through this key — strip that one line before Step 3 if your pipeline does not already.
- No sibling task directory was read, listed, or grepped; the design came only from the scenario text plus `skills/prd-bench-scaffold-generator/` (SKILL.md, `references/claim-extraction-guide.md`, `scaffold_lint.py`).
- Defects caught and fixed during self-review of the corner design: three wrong field names/paths (`test_ratio_bps`→`business_line_deposit_ratio_bps`, `qualification_outcome`→`test_outcome`, a nonexistent `/institutions/{id}/deposit-programs` route→`GET /deposit-programs?institution_id=`), a `check_reason` payload key that does not exist on `RateCapCheck` (→ `check_date`), a wrong `outcome` literal (`PASS`→`EXEMPT_NO_CAP` for a null cap), and one arithmetic slip (322 vs 323 bps).

**Orchestrator post-step action (per known-leak guard):** deleted lines 2–3 of `SCAFFOLD.yaml` (the `Generate task harder than expert level!` directive line plus its blank line) from the `scenario:` block so the difficulty directive cannot reach PRD.md via the doc generator. Verified with `grep -rn "harder than expert" .` → no hits. All three YAMLs re-parsed cleanly with `yaml.safe_load` after the edit.

## Step 3: Copy shared files — 2026-09-05T06:04:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2834_brokered_deposit_listing_service_funding_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T06:22:00.000Z

PRD complete.

**Output:** `workspace/PRD.md` — **461 lines**, ~112 KB, written via eight chunked heredoc appends (no single giant Write).

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC, 2.2 API Response Structure (byte-identical to the skill's canonical block, verified programmatically), 2.3 Pagination, 2.4 Money/Rates/Rounding Discipline, 2.5 Record Identity/Timestamps/Versioning, 2.6 Observed-Version Guards, 2.7 Reference Resolution & Path Segments, 2.8 Rule Precedence (all 50 rules numbered in priority order with error IDs, scopes and the three declared conflict pairs), 2.9 Segregation of Duties, 2.10 The Logical Clock, 2.11 Derived Balances/Cascade Ordering/Conserved Quantities
- §3 Business Logic & Workflows — 3.1 Registering a Bank and Publishing the Rate Benchmark; 3.2 Counterparty Onboarding and the Diligence Cycle; 3.3 Claiming a Primary Purpose Exception; 3.4 Opening a Funding Program and Determining Its Class; 3.5 Booking, Funding and Settling Deposits; 3.6 Rate-Cap Surveillance; 3.7 Board Limits, Headroom and Liquidity Contingency Planning; 3.8 The Maturity Sweep and the Rollover Ladder; 3.9 Call Report Accuracy and the Examiner Cycle
- §4 Endpoint Definitions — 4-column table (Method, Path, Description, Authorized Role(s)), 46 rows, all rows exactly 4 columns
- §5 Error Code Catalogue — 2-column table (Error ID, HTTP Status Code), 50 rows, all rows exactly 2 columns

**Hard Contract results (mechanically verified, not eyeballed)**
- Contract 1 — Field-Name Coverage: **PASS**. 134/134 entity field names, 90/90 endpoint input identifiers (request body + query + path), 27/27 computed-read output keys all present verbatim in backticks; 0 missing. Also verified: all 30 `action` enum literals and every declared entity enum member appear verbatim. One gap was found and repaired during verification — the `action` discriminator and 14 of its literals (`ATTEST_CLASSIFICATION`, `SUBMIT_FOR_REVIEW`, `OPEN_EXAM_REVIEW`, `REARM`, etc.) were only described in prose; the seven action-endpoint rows in §4 now enumerate their literals explicitly.
- Contract 2 — Rule Coverage: **PASS**. All 50 validations appear in §2.8 in priority order with their error IDs and `applies_to` scopes; all 7 state machines' states (0 missing) and every declared transition are covered, including both independent `DepositPlacement` dimensions, all four cascades (3-hop agreement suspend, 4-hop exception revoke, capital re-categorisation, reclassification), both OCC rules, all 19 calculations, the three round caps, the five segregation-of-duties comparisons, and both conserved quantities. Every error ID is stated in §1–§4 before its §5 row.
- Contract 3 — §3 Path Purity: **PASS**. Of 1036 backticked tokens inside §3, 0 start with `/`, 0 are a bare HTTP method, and 0 combine method+path; §3 also contains no unbacktick'd method or path mentions.

**Tail confirmation:** the file ends at a real section boundary — the final line is the last row of the §5 table, `| \`ERR_BUFFER_SHORTFALL_UNFUNDED\` | 422 |`. No audit footer, no PASS report and no truncation artifact in the file.

Constraints honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read; scratch confined to `/tmp/task_2834_prd/`.

**Orchestrator verification (truncation guard):** independently confirmed `wc -l` = 461, tail ends on the complete final `ERR_BUFFER_SHORTFALL_UNFUNDED` table row (a real section boundary, not mid-sentence), 5 top-level sections present, §4 has 46 endpoint rows and §5 has 50 error rows. `grep -in "harder than expert\|expert level" PRD.md` → no hits, so the Step 2 difficulty directive did not leak into the PRD. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T07:17:00.000Z

Suite is complete and verified. Closing mechanics done: both output dirs listed, `__pycache__`/`.pytest_cache` removed, nothing written under `workspace/`, `worklog.md` untouched (mtime 06:22, predates all suite writes).

## test_helpers/ — 9 files, 2,242 lines

| file | lines |
|---|---|
| types.py | 489 |
| fixtures.py | 490 |
| assertions.py | 464 |
| api_client.py | 229 (46 methods, one per §4 endpoint) |
| factories.py | 217 |
| api_errors.py | 114 (all 50 error ids + `set_error_http_status_map`) |
| __init__.py | 91 |
| test_users.py | 83 |
| constants.py | 65 |

## test_suite/ — conftest + 12 test files, 11,638 lines

| file | lines | tests |
|---|---|---|
| conftest.py | 60 | — |
| test_01_dual_variant_calculations.py | 280 | 4 |
| test_02_composed_formulas.py | 496 | 8 |
| test_03_state_machines_and_cascades.py | 965 | 14 |
| test_04_precedence_and_boundaries.py | 751 | 12 |
| test_05_cross_entity_gates_and_invariants.py | 1376 | 17 |
| test_06_entity_surface.py | 1231 | 24 |
| test_07_lifecycle_transitions.py | 1155 | 22 |
| test_08_derived_calculations.py | 819 | 9 |
| test_09_input_validation.py | 609 | 7 |
| test_10_endpoint_behaviour.py | 865 | 13 |
| test_11_error_catalogue.py | 1634 | 42 |
| test_12_access_control_and_consistency.py | 1397 | 18 |

**190 test functions → 263 collected pytest items** (`--collect-only -q`: 263 collected, 0 import/collection errors).

## Design-index coverage
- Queue A (SCAFFOLD_DIFFICULTY_DESIGN.yaml): **22/22 instances**, every one with >=2 tests.
- Queue B (SCAFFOLD_CORNER_DESIGN.yaml): **67/67 non-stub instances**, every one with >=1 test. The 12 `excluded_because:` stubs deliberately received zero tests; each stub's `difficulty_instance:` cross-reference was checked to resolve to a real queue-A instance.
- Every docstring carries exactly one trailing `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, copied verbatim. Audit: unknown tags = 0, untagged = 0, dual-tagged = 0.

## Skipped instances
**None.** No instance failed the PRD-first two-condition filter at instance level. Assertion-level drops were made instead (each kept the instance testable on its PRD-derivable core):
- wholesale-funding-summary field names the PRD never enumerates -> asserted on `GET /institutions/{id}` instead
- `attested_by_user_id == null` after the revoke cascade -> dropped (PRD only clears it for operator-driven `START_RECLASSIFICATION`)
- `updated_at == created_at` at creation -> dropped
- `classified_as` asserted only on activated tranches
- no-DELETE probe asserts only "not 2xx"
- two design-yaml values corrected against the PRD: `breach_state NONE` -> `WITHIN`; `program_version_at_determination 2` -> `3`; and a `total_liabilities_cents: 0` setup replaced with `core_deposits_cents: 0` + `total_liabilities_cents: 1` because §3.1 requires liabilities strictly positive.

## Verification gates (implementation not runnable — concurrent agent still generating it)
1. `pytest --collect-only` — 263 tests, clean.
2. Design-index audit — 190 tests, queue-A/queue-B shortfalls 0, unknown tags 0, hygiene 0 (no `xfail`/`mark.skip`/`skipif`, no scaffold or §1.x leakage).
3. Verbatim-PRD check — 190/190 docstrings contain a verbatim >=8-word run from PRD.md.
4. Fixture hygiene — all money/bps are JSON ints, instants full ISO-8601, distinct owners get distinct `X-User-ID`. One `principal_cents="2000000000"` string in `test_06_entity_surface.py:869` is the intentional `non_integer_cents` branch of `test_type_and_range_violations_rejected` asserting `ERR_INVALID_REQUEST` — not a bug; do not "fix" it.

Two pre-emptive `assertions.py` relaxations worth flagging to Step 7: `net_settlement_cents` is no longer required non-negative (with `principal_erosion_allowed` the penalty can exceed principal + interest), and `prepared_by_user_id` is allowed to be null on sweep-born rollover successors.

## Step 6: Generate implementation — 2026-09-05T06:52:00.000Z

Implementation complete and smoke-tested.

## Files written (`workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (chmod +x) | 10 |
| `requirements.txt` | 1 |
| `app.py` | 68 |
| `util.py` (logical clock, instants, floor_div, round_half_up, `_seq`) | 131 |
| `errors.py` (all 50 PRD §5 codes + `ERR_NOT_FOUND`) | 118 |
| `response.py` (meta/response_type/data envelope, pagination) | 56 |
| `db.py` (12 empty in-memory dicts) | 67 |
| `middleware.py` (auth, typed body/query readers) | 172 |
| `calc.py` (19 calculation rules) | 593 |
| `cascades.py` (depth-3 agreement, depth-4 revocation) | 99 |
| `routes/__init__.py` | 0 |
| `routes/clock.py` | 16 |
| `routes/institutions.py` | 186 |
| `routes/ratecaps.py` | 52 |
| `routes/brokers.py` | 245 |
| `routes/exceptions.py` | 195 |
| `routes/programs.py` | 197 |
| `routes/classifications.py` | 122 |
| `routes/placements.py` | 282 |
| `routes/limits.py` | 65 |
| `routes/plans.py` | 143 |
| `routes/filings.py` | 139 |
| `routes/maturity.py` | 87 |
| **Total** | **3044** |

## Endpoints

**46 of 46** from PRD §4 registered (Flask URL map reports 47 rules incl. Flask's own `/static`). Verified by enumerating `app.url_map`.

## Smoke test — passed

Booted `PORT=38829 bash start.sh` (bound `0.0.0.0`, foreground, guarded pip install), then drove a full end-to-end flow and killed only PID 59380 afterwards (`SMOKE_SERVER_STOPPED`; port confirmed free). No broad `pkill` was ever used — I did hit two ports (39834/39836) already occupied by sibling pipelines and switched to a kernel-allocated free port instead of killing anything foreign.

Envelope confirmed against PRD §2.2: `meta{api_request_id: req_+20 upper-alnum, api_request_timestamp}` / `response_type` (`object`|`array`|`error`) / `data`; error body `{error_id, message}`; instants carry exactly 3 fractional digits (`2026-08-10T00:00:00.000Z`); fresh boot reads the logical clock at `2026-08-01T00:00:00Z` and `GET /institutions` returns `[]` with `total_count: 0` — no seeding.

Chain exercised, all with correct derived arithmetic:
- clock set -> institution (regime `CAPPED`) -> benchmark (`cap_bps` 525 = 450+75, `non_maturity_cap_bps` 500) -> broker -> agreement -> `START_DILIGENCE`/`APPROVE` (`diligence_score` 84 from 8425/100, half-up) -> program (`tenor_bucket` `DAYS_91_180`, `effective_cap_bps` 525) -> classification (`BROKERED`, `program_version_at_determination` 2) -> attest (`OPEN_FOR_PLACEMENT`, version 2) -> concentration limit -> placement (`PENDING`/`UNREVIEWED`, `maturity_date` derived) -> activate (`fee_accrual_cents` 25000 = 10,000,000x25/10000) -> wholesale summary (`wholesale_funding_ratio_bps` 909, `single_broker_max_ratio_bps` 909, `brokered_headroom_cents` 32857142 matching the closed form `(3000*110000000 - 10000*10000000 - 1)//7000`) -> rate-cap check (`PASS`) -> two-phase maturity sweep (1 matured, 1 rolled, 1 successor created) -> contingency plan -> call report filing + `PREPARE` (`variance_bps` 1000 -> `VARIANCE_MATERIAL`).
- Error paths: 401 unauthenticated, 403 unauthorized role, 404 body-FK not-found, 404/405 unknown route with `ERR_NOT_FOUND` envelope, 409 duplicate key and state-invalid, and pagination bounds (`limit=0`, `limit=101`, `offset=-1`, `limit=abc` all `ERR_INVALID_REQUEST`).

## Notes

- Only two fidelity fixes were needed after the initial write: cascade-driven program transitions use `db.touch` not `db.bump` (PRD §2.11 — only a classification determination and the capital-recategorisation cascade advance a program's `version`), and the contingency-plan / call-report list sorts were switched from `created_at` to the PRD §2.3 declared orders (`effective_from` ASC and `report_period` ASC, `created_at` as tie-break).
- Isolation held: no read of `test_suite/`, `test_helpers/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task; scratch confined to `/tmp/task_2834_impl/`; `worklog.md` untouched.

**Orchestrator layout verification before Step 7:** `test_helpers/` and `test_suite/` are both at the task root (not under `workspace/`); `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`. No `__pycache__`/`.pytest_cache` strays, no `results.*.json` yet, `start.sh` reads `$PORT` and execs the server in the foreground with a guarded pip install.

## Step 7: Run tests and iterate — 2026-09-05T07:48:00.000Z

All 8 parallel rounds are green. Exiting.

## Summary

**Iterations run:** 2

**Tests deleted:** none. No test failed the STEP 1 PRD-coverage or unique-derivability checks.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** one test bug (STEP 2 — request inconsistent with PRD).

- `test_suite/test_06_entity_surface.py`, `test_unknown_body_foreign_keys_return_the_addressed_not_found_codes` — the unknown-counterparty probe posted a program with `broker_id=NON_EXISTENT_UUID` but **no** `agreement_id`. PRD §3.4 states verbatim: "Where `broker_id` is present, `agreement_id` is required and must name an agreement belonging to that same counterparty". A missing required input field is a §2.8 priority-3 request-shape violation (`ERR_INVALID_REQUEST`), which correctly pre-empts counterparty existence at priority 5 — so the implementation's `ERR_INVALID_REQUEST` was PRD-faithful and the test's expectation of `ERR_BROKER_NOT_FOUND` was unreachable from a malformed request. Fixed by having the test build a real cleared counterparty/agreement via `fx.setup_approved_agreement()` and pass that real `agreement_id` alongside the unknown `broker_id`, so the request is well shaped and §2.8's ordering (5 counterparty existence ahead of 6 agreement existence and 45 broker/agreement mismatch) uniquely yields `ERR_BROKER_NOT_FOUND`. The assertion itself was not weakened — it still demands the exact `error_id`.

**Fixes applied to `implementation/`:** none. `routes/programs.py:59-60` (the `agreement_id`-required guard) is PRD-required and was left intact rather than relaxed to accommodate the malformed fixture request.

**Final per-round figures** (from `workspace/implementation/results.$i.json`):

| Round | passed/total |
|---|---|
| 1 | 263/263 |
| 2 | 263/263 |
| 3 | 263/263 |
| 4 | 263/263 |
| 5 | 263/263 |
| 6 | 263/263 |
| 7 | 263/263 |
| 8 | 263/263 |

No flakiness surfaced across the two sweeps — the single failure was deterministic in all 8 rounds of iteration 1 and absent in all 8 rounds of iteration 2. `worklog.md` was not touched.

**Orchestrator independent verification (per known Step-7 false-clean-sweep failure mode):** re-read all 8 `results.$i.json` from disk myself (all 8 present, ~88 KB each, mtime 07:40, written by the same sweep). Every round reports `passed == total == 263` with an empty non-passed list. Hygiene re-checked: zero `mark.skip` / `mark.xfail` / `skipif` occurrences anywhere in `test_suite/` or `test_helpers/`, so the green sweep was not bought with skips.

**Step 8 gating decision:** Step 7 reported 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, but **1 `test_suite/` fix**. The skip condition requires all four counts to be zero, so Step 8 is NOT skipped — the §3.4 `agreement_id`-required / §2.8 precedence interaction that the fix turned on is exactly the kind of PRD site worth pinning.

## Step 8: Finalize PRD — 2026-09-05T07:57:00.000Z

`PRD_FINALIZED.md` is written. One edit, traced to the single Step 7 item.

## Line counts
- `PRD.md`: 461 lines / 112,911 bytes
- `PRD_FINALIZED.md`: 461 lines / 113,278 bytes
- Delta: 0.0% by lines (1 line revised in place), +0.33% by bytes

## Changes
- **§3.4 (Opening a Funding Program), line 259 — revise** — pinned that the conditional requirement "`agreement_id` is required where `broker_id` is present" is a **request-shape** violation reported as `ERR_INVALID_REQUEST` at §2.8 priority 3, evaluated before the counterparty or agreement is looked up; and re-scoped the existing `ERR_AGREEMENT_BROKER_MISMATCH` clause to the case where an `agreement_id` *is* present — `implementation/routes/programs.py:59-60` (guard) vs `:92-93` (mismatch).

## Pre-edit search log

**(a) Subject identified:** the presence/absence pairing of `broker_id` and `agreement_id` on a program create — which error identity and which §2.8 priority each mis-pairing takes.

**(b) Impl paths enumerated (read/grepped):**
- `routes/programs.py:45-46` — both read via `mw.opt_id`, i.e. declared default null; explicit JSON `null` is indistinguishable from absent (`middleware.py:136-139`).
- `routes/programs.py:59-60` — `broker_id is not None and agreement_id is None` -> `mw.bad(...)` = `ERR_INVALID_REQUEST`, raised **before** any DB lookup.
- `routes/programs.py:64-73` — institution (p4), broker (p5), agreement (p6) existence, all strictly after the guard.
- `routes/programs.py:92-93` — `agreement is not None and (broker_id is None or agreement["broker_id"] != broker_id)` -> `ERR_AGREEMENT_BROKER_MISMATCH`; note the `agreement is not None` precondition, so the "agreement without counterparty" case is still priority 45, **not** priority 3.
- `routes/programs.py:31-37` `_agreement_cleared` — the parallel `broker_id`-present/`agreement_id` path used by `ATTEST_CLASSIFICATION` and `RESUME`, which yields `ERR_AGREEMENT_NOT_APPROVED`, not a shape error; and `:79-83` the create-time cleared check.
- `middleware.py:39-44` — every `mw.bad` / field-reader failure is `ERR_INVALID_REQUEST` at priority 3; `grep -rn "mw.bad"` over all routes to see the other conditionally-required-field sites (`routes/placements.py:154-155` `withdrawal_date` for `EARLY_WITHDRAW`, `routes/institutions.py:166` `period_start`/`period_end` under `basis=AVERAGE_DAILY`) — all consistent with a priority-3 reading, confirming the impl's convention is uniform.
- `routes/placements.py:73-76` — the only other consumer of a program's `agreement_id` (the `ERR_ISSUE_BEFORE_AGREEMENT` gate), which tolerates a null `agreement_id`; untouched by the new wording.

**(c) Wording adjustment made:** two. First draft said the malformed pairing "is never reported as a not-found or a mismatch" — dropped, because `programs.py:92-93` *does* report the agreement-without-counterparty pairing as a mismatch; I instead opened the surviving mismatch clause with "Once an `agreement_id` is present," so the mismatch scope matches the `agreement is not None` precondition exactly. Second, added "(or supplying it as null)" to match `mw.opt_id`'s treatment of explicit null, and scoped the priority-3 claim to the program create alone rather than to conditionally-required fields in general, so §2.8 item 3 needed no edit and no universal claim was introduced.

No other PRD edit was warranted: Step 7 applied no `implementation/` or `test_helpers/` fixes and deleted no tests, and `routes/programs.py:59-60` was explicitly left intact as PRD-faithful.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one hunk (`259c259`), an in-place revision of the §3.4 paragraph — no new sections, no line-count change, tail still ends on the complete final §5 error row. The edit is legitimately scoped to the one Step 7 `test_suite/` fix site.

## Step 9: Complete PRD — 2026-09-05T08:20:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md` rather than a single scan. Rationale: a single-pass scan over a 462-line / 113 KB PRD against a 3044-line implementation has repeatedly produced a byte-identical `PRD_COMPLETED.md` (i.e. the scan silently never ran). Partitioning by implementation module bounds each pass's reading load so the walk is genuinely exhaustive. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to `cp` so they could not destroy earlier edits. Partitions: (1) `app.py`, `util.py`, `errors.py`, `response.py`, `db.py`, `middleware.py`, `routes/{clock,institutions,ratecaps}.py`; (2) `calc.py`, `cascades.py`, `routes/{brokers,exceptions,programs,classifications}.py`; (3) `routes/{placements,limits,plans,filings,maturity}.py`.

### Pass 1 of 3 (core, envelope, middleware, institutions, rate caps)
- Did the `cp PRD_FINALIZED.md PRD_COMPLETED.md` (sole pass to do so). Source 461 lines / 113,278 chars -> 462 lines / 118,963 chars (+1 line, +5,685 chars; the +1 line is the new `ERR_NOT_FOUND` §5 row).
- **14 ambiguity-pins, 2 mismatch-revisions.**
- §2.1 — revise — mismatch — an identity header present but empty-valued is `ERR_UNAUTHENTICATED` — `middleware.py:22`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 upper-case-alnum chars — `response.py:10,14`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock, not wall clock — `response.py:20`
- §2.3 — insert — ambiguity — empty-string `limit`/`offset` default; non-integer/out-of-range is `ERR_INVALID_REQUEST`, never clamped — `middleware.py:145-165`
- §2.3 — insert — ambiguity — insertion order is the final tie-break under every declared ordering (both directions); out-of-set/empty filter value matches nothing rather than erroring — `util.py:26-29`, `db.py:61`, `institutions.py:83`, `ratecaps.py:51`
- §2.7 — insert — mismatch — path-segment resolution precedes body reading on *every* endpoint, so §2.8's ordering governs only body/query references — `institutions.py:90,126`
- §2.8 rule 3 — revise — ambiguity — rule 3 also covers read query strings; explicit `null` == omitted; undeclared fields ignored; strings need a non-whitespace char and are stored untrimmed; booleans/floats are not integers; dates must be real calendar dates; instants accept `Z`, an offset, or no zone (read as UTC) — `middleware.py:46-126`
- §2.10 — insert — ambiguity — clock accepts any zone form, stores UTC, returns a bare `{"current_utc": ...}` object with 3 fractional digits — `clock.py:14-16`, `util.py:39-40`
- §3.1 — revise — ambiguity — `total_liabilities_cents` of zero is `ERR_INVALID_REQUEST` at priority 3 — `institutions.py:36-37`
- §3.1 — revise — ambiguity — re-categorisation bumps the bank's own `version` by 1; a program's `effective_cap_bps` becomes null (never `ERR_NO_RATE_CAP_PUBLISHED`) when no publication governs its bucket — `institutions.py:101-118`, `calc.py:106-118`
- §3.1 — insert — ambiguity — balance adjustment always bumps `version`/`updated_at` even with empty body/unchanged value; examiner lock tested only after shape validation — `institutions.py:128-146`
- §3.7 — insert — ambiguity — bad `basis`, or missing/malformed period bound under `AVERAGE_DAILY`, is `ERR_INVALID_REQUEST`; an inverted period returns zeros — `institutions.py:154-169`, `calc.py:514-517`
- §3.7 — insert — ambiguity — exact 14-key payload of the wholesale-funding-summary computed read — `institutions.py:170-186`
- §4 intro — insert — ambiguity — trailing slashes accepted; unlisted path -> `ERR_NOT_FOUND` 404; wrong method on a listed path -> `ERR_NOT_FOUND` 405; both bypass header inspection — `app.py:35,45-49`
- §4 rate-cap list row — revise — ambiguity — as-of filter accepted under `as_of_date`, `as_of` or `effective_date`, first non-empty wins — `ratecaps.py:48-50`
- §5 — insert — ambiguity — added the missing `ERR_NOT_FOUND` | 404 row plus a preamble clause noting it is the one identifier that also appears at 405 — `errors.py:63`, `app.py:45-49`

### Pass 2 of 3 (calculations, cascades, counterparties, exceptions, programs, classifications)
- Found 462 lines / 118,963 chars -> left 462 lines / 122,896 chars. No `cp`, no Write; targeted Edits only.
- **11 ambiguity-pins, 6 mismatch-revisions.**
- §3.1 — insert — ambiguity — governing-publication tie-break: equal `effective_date` *and* equal `created_at` resolves to the later-inserted row — `calc.py:102-103`
- §3.2 — insert — mismatch basis — the mirroring write advances the counterparty's `version`/`updated_at` only when it actually changes `diligence_status` or `approved_agreement_count` — `brokers.py:156-166`
- §3.2 — revise — mismatch — PRD asserted `version` always "+1" on START_DILIGENCE; impl leaves a counterparty already `IN_DILIGENCE` untouched — `brokers.py:186`
- §3.2 — insert — ambiguity — RESUME_DILIGENCE does not re-stamp `reviewed_by_user_id` — `brokers.py:198-206`
- §3.2 — insert — ambiguity — the termination cascade also cancels each closed program's `PENDING` placements and recomputes rollup/posture; counterparty mirror left as suspension left it — `cascades.py:34-45`, `brokers.py:238-243`
- §3.3 — revise — mismatch — asset-denominator and `enabling <= total_transaction_count` checks are basis-independent; only the `total_transaction_count > 0` floor is enabling-basis-specific — `exceptions.py:51-56`
- §3.3 — insert — ambiguity — a withdraw blocked by non-zero `reliant_program_count` is refused with `ERR_EXCEPTION_STATE_INVALID` — `exceptions.py:131-133`
- §3.3 — insert — ambiguity — revocation hop two also clears each moved program's `attested_by_user_id`, and `reliant_program_count` is zeroed whether or not any program moved — `cascades.py:81-85`
- §3.4 — insert — ambiguity — a non-maturity product with non-zero `tenor_days` is `ERR_INVALID_REQUEST` at priority 3 — `programs.py:61-62`
- §3.4 — insert — ambiguity — the `effective_cap_bps` re-derivation is tolerant: null when `EXEMPT` and equally when `CAPPED` with no governing publication — `classifications.py:68-72`
- §3.4 — revise — mismatch — a re-determination naming the *same* exception moves no count; decrement floored at zero — `classifications.py:75-83`
- §3.5 — revise — mismatch — the activation gate tests **every** `ACTIVE` limit against its own post-activation metric value, recomputed from the placement book with the tranche counted `ACTIVE` — `calc.py:455-470`, `calc.py:424-452`
- §3.5 — insert — ambiguity — accrued-interest day count is a plain date difference, not floored at one; settlement not strictly after `issue_date` yields 0 — `calc.py:127-131`
- §4 `POST /brokers/{id}/agreements` — revise — mismatch — description claimed an agreement "between the counterparty and a bank"; the record names no bank — `brokers.py:84-105`
- §4 `GET /brokers` — revise — ambiguity — diligence-status filter accepted under `diligence_status` or alias `registration_status`, former wins — `brokers.py:71`
- §4 `GET /primary-purpose-exceptions` — revise — ambiguity — outcome filter accepted under `test_outcome` or alias `test_type`, former wins — `exceptions.py:99`
- §4 `GET /deposit-classifications` — revise — ambiguity — added `relied_exception_id`, defined "superseded", pinned truthy parsing of the `superseded` parameter — `classifications.py:112-120`

### Pass 3 of 3 (placements, limits, plans, filings, maturity sweep) — also owned the closing integrity check
- Found 462 lines / 122,896 bytes -> left 462 lines / 126,744 bytes. No `cp`, no Write; 15 targeted Edits across 13 lines.
- **12 ambiguity-pins, 3 mismatch-revisions.**
- §2.8 rule 3 — revise — mismatch — the blanket non-whitespace string rule now excepts the optional free-text `note` / `examiner_finding_note`, which `opt_str` accepts empty — `middleware.py:59-62`, `plans.py:117`, `filings.py:135`
- §2.8 rule 22 — insert — mismatch — an activation re-tests rules 21 and 33 only *after* the `PENDING -> ACTIVE` transition is admitted, so a non-`PENDING` tranche reports `ERR_PLACEMENT_STATE_INVALID` first — `placements.py:161-167`
- §2.8 rule 37 — revise — mismatch — endpoint list extended to plan lifecycle actions with the approve action — `plans.py:124-128`
- §3.5 — insert — ambiguity — zero/negative `principal_cents` is `ERR_INVALID_REQUEST` at priority 3 — `placements.py:29-31`
- §3.5 — insert — ambiguity — a rollover source is "already rolled" as soon as any placement names it, whatever that successor's later `funding_status` — `placements.py:81-86`
- §3.5 — insert — ambiguity — the `issue_date`/agreement bound applies only where the program names an agreement — `placements.py:73-78`
- §3.5 — revise — ambiguity — placement list filters name `institution_id`, matched via the placement's program — `placements.py:138-142`
- §3.5 — insert — ambiguity — a `withdrawal_date` on/after `maturity_date` is `ERR_INVALID_REQUEST` but compared only after the transition is admitted — `placements.py:180-183`
- §3.6 — insert — ambiguity — the benchmark selector runs even for an `EXEMPT` bank, so `national_rate_bps_snapshot` is populated when a publication governs and null when none does — `placements.py:238-253`
- §3.6 — insert — ambiguity — a review whose outcome names no transition is still created 201 but moves nothing and advances neither `version` nor `updated_at` — `placements.py:216-267`
- §3.7 — insert — ambiguity — a superseding limit's 201 body already carries evaluated `current_value_bps`/`breach_state` while its `version` stays at 1 — `limits.py:47-50`
- §3.7 — insert — ambiguity — `effective_from` on/after `effective_to` is `ERR_INVALID_REQUEST` at priority 3, before window-overlap and trigger-ordering — `plans.py:47-48`
- §3.8 — insert — ambiguity — the rollover successor's `tenor_bucket` derives from `product_type` + current `tenor_days`, `prepared_by_user_id` is the sweep operator, and none of the §3.5 booking gates are re-run — `maturity.py:44-78`
- §3.9 — insert — ambiguity — an amending preparation may supply any subset of the three figures (omitted keep stored value); `examiner_finding_note` written unconditionally, so omitting it stores null — `filings.py:107-137`
- §3.9 — insert — ambiguity — reported figures on a `DRAFT` preparation or any other action are disregarded without validation — `filings.py:107-112`

**Pass 3's closing integrity check:** `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l` = 166; `grep -c '^## '` = 5 (§1–§5, no new section); §4 = 46 endpoint rows; §5 error table intact at 51 `ERR_*` rows; final 462 lines / 126,744 bytes ending on the last §5 row.

**Pass 3 observation, deliberately NOT encoded in the PRD:** `routes/filings.py:125-135` mutates `filing["status"]`/`amendment_round` before `opt_str(data, "examiner_finding_note")` can raise, so a `REQUIRE_AMENDMENT` carrying a non-string note returns 400 with the filing already advanced to `AMENDMENT_REQUIRED`. The PRD asserts nothing about atomicity of rejected requests, so there is no mismatch to revise, and pinning the partial write would encode an ugly contract. Recorded here as a latent defect rather than patched.

### Orchestrator final verification
- Totals: **31 ambiguity-pins + 11 mismatch-revisions = 42 edits** across the three passes.
- `PRD.md` 461 lines / 112,911 B -> `PRD_FINALIZED.md` 461 lines / 113,278 B -> `PRD_COMPLETED.md` 462 lines / 126,744 B (+12.2 % chars over the finalized source).
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` -> **differs** (the byte-identical failure mode did not occur); `diff | wc -l` = 166.
- 5 top-level sections, tail ends on the complete `| \`ERR_NOT_FOUND\` | 404 |` row — a real section boundary, not a truncation.
- `grep -in "harder than expert\|SCAFFOLD" PRD_COMPLETED.md` -> no hits, so neither the difficulty directive nor a scaffold reference leaked into the delivered contract.
- `find workspace/implementation test_suite test_helpers -name "*.py" -newer results.1.json` -> **empty**: no implementation or test file changed after the green sweep, so the Step 7 result (8 rounds x 263/263) still describes the delivered artifacts exactly. No re-sweep required.

**PIPELINE COMPLETE** — Step 9 wrote `workspace/PRD_COMPLETED.md`.
