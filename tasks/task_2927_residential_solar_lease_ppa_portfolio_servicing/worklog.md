## Step 1: Create task directory — 2026-09-05T17:40:20.346512447Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2927_residential_solar_lease_ppa_portfolio_servicing and its workspace/ subdirectory (pre-assigned path; no index auto-allocation). Also created .scratch/step{2,5,6,7,8,9}/ so each step has a private scratch dir.

## Step 2: Generate scaffold — 2026-09-05T19:51:51.406Z

All three scaffold artifacts are complete, parse cleanly, and lint clean.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2927_residential_solar_lease_ppa_portfolio_servicing/SCAFFOLD.yaml` | 3842 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2927_residential_solar_lease_ppa_portfolio_servicing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1959 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2927_residential_solar_lease_ppa_portfolio_servicing/SCAFFOLD_CORNER_DESIGN.yaml` | 4875 |

`SCAFFOLD.yaml` carries 13 top-level keys and neither design key; each design file has exactly one top-level key. The difficulty directive string appears nowhere.

## Domain model

`domain_name: residential-solar-portfolio-servicing`, `api_prefix: /servicing` — **12 entities**, **69 endpoints**, **6 roles** (Homeowner as `entity_backed`, ServicingAgent, CreditUnderwriter, TitleAgent, FieldOpsCoordinator, PortfolioAdmin), plus 12 state machines, 15 calculations, 34 validations on a 14-level priority ladder, 49 errors, 2 §1.2.1 concurrency rules. Profile: `ledger_reconciliation` / `multi_party_negotiation`, layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; flat topology, branching state machines, `segregation_of_duties` role model, immediate consistency.

## §1.8 — 9 rule_ids, 19 instances

dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

## §1.9 — 9 sections, 95 instances

entities 16, state_machines 16, calculations 15, validations 20, endpoints 7, errors 5, rbac 8, cross_cutting_complexity_layers 6, consistency_model 2.

## Verification

- `scaffold_lint.py`: **clean** — 977 calls scanned across 19 §1.8 + 83 §1.9 instances; all conform to §1.5 and every §1.1 FK has reverse-reachability.
- **Endpoint coverage is now total**: all 69 declared endpoints are hit by at least one structured call (previously 13 — the 9 collection GETs plus `mark-false-positive`, `roof-complete`, `reinstall`, `ucc terminate` — appeared only in prose). Closed with 4 new instances: a pagination-envelope sweep over the nine remaining collections, the full roof-work physical sequence (`remove-panels → roof-complete → reinstall` with the 15-of-31-day excusal driving August 2026 to `adjusted_expected_kwh` 525 / floor 499 / no credit vs. 4053 cents without it), the false-positive close-out, and the two-step UCC termination.
- All 49 declared error codes are triggered by some design instance; zero duplicate instance names across 114 instances.
- **Third SCAFFOLD.yaml defect repaired**: the §1.2 `APPROVED -> PANELS_REMOVED` clock precondition ("clock date on or after `suspension_start_date`") had no error code anywhere in §1.4/§1.6, and p8's own text excluded it. Added a priority-11 `roof_removal_not_before_window` rule reusing `ERR_ROOF_DATES_INVALID` (422), explicitly subordinate to the p8 state check, and extended that code's catalogue `when` to cover both creation and removal. (Earlier repairs: the `RECORDED -> CREDIT_ISSUED` double-version-bump ambiguity, and the reachability of `ERR_TRANSFER_IN_PROGRESS`.)

Orchestrator verification: all three files present; `yaml.safe_load` OK; top-level keys correct; grep for the difficulty directive string across all three returns nothing (no leak into SCAFFOLD.yaml scenario key).

## Step 3: Copy shared files — 2026-09-05T19:51:57.65701527Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T20:11:26.109Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **439 lines**, built incrementally with `Write` + seven `cat >>` heredocs. Last section heading is `## 5. Error Code Catalogue`; the file's final line is the last error row (`| \`ERR_APPROVED_AMOUNT_EXCEEDS_CLAIM\` | 422 |`), a real section boundary, no audit footer, no truncation.

**Structure:** §1 Introduction (3 paras); §2 with 10 subsections (2.1 RBAC, 2.2 verbatim response-structure block copied from the skill file, 2.3 pagination/filtering/ordering, 2.4 identity/timestamps/version, 2.5 logical clock, 2.6 units & ROUND_HALF_UP discipline, 2.7 optimistic concurrency, 2.8 the three independent agreement state dimensions, 2.9 credit-ledger invariants, 2.10 the 14-rung rejection ladder); §3 with 10 workflow subsections (3.1 foundations → 3.10 end-of-term); §4 endpoint table (4 columns, **69 rows** verified by count); §5 error table (2 columns, **49 rows** verified by count). No malformed table rows in either table.

**Hard Contract 1 — Field-Name Coverage: PASS.** Machine-verified: 161 distinct names extracted from the scaffold (every entity field, every endpoint request-body field, every query parameter, every path parameter) — all 161 appear in the PRD, in backticks or inside the §2.2 fenced examples. 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 6 roles named, and every one of the 17 `exclusive_operations` across the five operator roles is stated as exclusive in prose. All 35 scaffold validation rules described (the profile's "34" counts the two priority-11 `ERR_ROOF_DATES_INVALID` rules as one; both the creation-coherence and the removal-not-before-window forms are specified separately, including that a non-`APPROVED` order reports the priority-8 state error first). All 49 error codes appear in prose *outside* the §5 catalogue as well as in it. Both concurrency rules (`expected_agreement_version`, `expected_outage_event_version`) specified in §2.7. All 12 state machines covered: every initial, intermediate and terminal state name of all 12 dimensions appears in the PRD. All 15 calculations described with their constants; every literal constant value is present, with the seasonality curve written out as all twelve weights summing to 1.0000, and every rounding order pinned (per-bucket-then-sum NPV, the six-step settlement waterfall, round-to-4dp-then-floor residual, clamp-never-round credit sub-scores).

**Hard Contract 3 — §3 Path Purity: PASS.** 342 distinct backticked tokens in §3 (lines 151–308): none begins with `/`, none is a bare HTTP method, none is a method+path pair. Zero slash-prefixed path fragments and zero occurrences of `GET`/`POST`/`PUT`/`PATCH`/`DELETE` anywhere in §3, in or out of backticks. Endpoints are referenced only via state-transition framing and role+action verbs. Also swept §3 for fuzzy quantifiers — none (two "and so on" enumerations were rewritten into explicit bucket-index formulations).

**Two deviations you should know about:**
1. **Auth header naming.** The scaffold's validation conditions say `X-Role`; the doc-generator skill and the shared runner helper `prd-bench-local-runner/src/prd_bench_local_runner/testing/headers.py` both hardcode `X-User-ID` / `X-User-Role`. The PRD specifies `X-User-ID` and `X-User-Role`, matching the test-side helper, since a PRD saying `X-Role` would make every generated auth test fail.
2. **`MAX_TRUCK_ROLL_WINDOW_HOURS` omitted.** The constant is named in the scaffold but carries no numeric value anywhere and has no reachable error code. The PRD states only that `scheduled_window_end` must be strictly after `scheduled_window_start`, rather than inventing a cap that would reject otherwise-valid test windows.

Three scaffold preconditions have no error id attached (activation with a future `contract_start_date`, reopening a month covered by a `POSTED` true-up, and the early-close and false-positive guards); all were attributed to the priority-8 generic `ERR_INVALID_STATE_TRANSITION`.

Constraints honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read; no `pkill` was run; the only scratch artifact is `.scratch/step4/contract1.py` and the `.scratch` parent was not deleted.

Orchestrator truncation check (per the known doc-generator failure mode): `tail -25 PRD.md` ends on a complete final table row of §5, the last section; 49 distinct ERR_ codes in the catalogue; endpoint table has 69 data rows. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-05T20:51:47.117Z

(Steps 5 and 6 ran concurrently; Step 6 returned first, so its entry is appended first. Step 5's entry follows below.)

Implementation is complete, compiles cleanly, and passes a breadth smoke test across all ten route modules.

## Modules written (`workspace/implementation/`, 3,414 lines total)

| file | lines | role |
|---|---|---|
| `core.py` | 308 | 49-code error catalogue + HTTP map, `ApiError`, ISO-8601 instant/date parse+format (3 fractional digits), calendar helpers, `LogicalClock` (default `2026-08-01T00:00:00Z`), `Decimal`/`ROUND_HALF_UP` helpers, request-id + `meta` builder, the 12-dict in-memory `Store`, `stamp_new`/`touch`/`sorted_rows`/`public` |
| `calc.py` | 435 | all 15 calculations: escalation, contract-year mapping, monthly expected/guarantee floor, six-step invoice waterfall inputs, shortfall credit, closed/half-open interval merging, excused-day derivation, severity grading, monitoring projections, truck-roll cost allocation, payoff quote, credit qualification, savings projection, election window + pricing |
| `web.py` | 249 | envelope helpers (`ok`/`created`/`ok_list`/`error_response`), `authenticate` (`X-User-ID`/`X-User-Role`, six roles), the declarative `validate_body` engine (34 validations), pagination, filter parsing/application |
| `serialize.py` | 66 | per-entity views; re-derives `monitoring_status`, `open_outage_count`, `excused_downtime_minutes`, `current_contract_year`; floats `downtime_minutes` while an outage is open |
| `guards.py` | 79 | FK lookup → per-entity `ERR_*_NOT_FOUND`, homeowner scoping, lifecycle/decommission gates |
| `r_core.py` | 287 | homeowners, tariff book, agreements, activate, apply-tariff, savings-projection |
| `r_periods.py` | 240 | metered months + the six-step reconcile waterfall, reopen |
| `r_trueups.py` | 185 | annual true-ups, OCC on the agreement, post (with the 25%-of-ACV credit cap), void with ledger reversal |
| `r_outages.py` | 142 | alarms, triage, mark-false-positive |
| `r_truckrolls.py` | 191 | dispatch with OCC + half-open technician-window conflict, complete (SoD + cost allocation), cancel |
| `r_roofwork.py` | 218 | request/quote/approve (3-day-buffered closed-interval conflict + 2-per-year cap), remove-panels, roof-complete, reinstall, cancel |
| `r_transfers.py` | 341 | three-arm transfer cases, credit review, title clearance, close fan-out (assumption/prepayment/relocation successor minting) |
| `r_ucc.py` | 156 | fixture filings, subordination request/record (SoD), termination request/record |
| `r_elections.py` | 226 | end-of-term elections, accept, execute fan-out, withdraw |
| `r_warranty.py` | 206 | claims, submit/request-info revision loop, approve/deny + the single `billable_to` re-point |
| `app.py` | 74 | blueprint registration, the `/_clock/set_current_utc` endpoint, `ApiError`/404/405/500 handlers |
| `start.sh` | 10 | guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask` |

## Endpoint coverage
**69/69.** I diffed the PRD §4 endpoint table against `app.url_map` programmatically: `PRD only: []`, `impl only: []`. The clock endpoint is one of the 69.

## Organisation
- **State machines** (12) live in the route module that owns the entity, as explicit `if status != ...: raise ERR_INVALID_STATE_TRANSITION` guards placed at the ladder rung the PRD assigns them; SoD checks that the PRD says "precede any state check" are physically written above them.
- **Calculations** (15) are all pure functions in `calc.py`, taking records and returning values, so reconcile/true-up/payoff/election paths share one implementation. All money/rate math is `Decimal` with `ROUND_HALF_UP`; bodies are parsed with `parse_float=Decimal` and serialised via `float()`.
- **Validations** (34) are declarative field specs (`kind`/`required`/`min`/`max`/`dp`/`one_of`/`pattern`/`nonblank`) fed to `web.validate_body`, so the shape rung is uniform; the 14-rung rejection ladder is enforced by statement order inside each handler.

## Smoke test (port 45301; 39271 was already occupied by another pipeline)
`bash start.sh` with `PORT` set was verified repeatedly. Verified behaviours: envelope shape (`meta.api_request_id` `req_`+20 upper alnum, `api_request_timestamp` with 3 fractional digits, `response_type` `object`/`array`/`error`, `data`); list `meta` carrying `limit`/`offset`/`total_count`/`has_more`; 401 with no headers, 403 wrong role, 403 `ERR_NOT_AGREEMENT_HOMEOWNER`, 404 per-entity and 404 unrouted, 405 wrong method. A 45-call end-to-end script then drove every blueprint: agreement create→activate→apply-tariff, 12 metered months with `auto_reconcile`, reopen/reconcile, true-up create (`412 ERR_STALE_AGREEMENT_VERSION` on a stale version) → post → void (`403` SoD then success), outage→triage→dispatch (`409 ERR_TECHNICIAN_WINDOW_CONFLICT`, abutting window accepted) → complete (SoD then success) → warranty claim submit/request-info/resubmit/approve with the `billable_to` re-point, roof order quote→approve→remove-panels→roof-complete→reinstall, UCC filing + subordination (SoD), transfer case credit review→clear-title→close, and election submit→accept→execute. All returned the expected status and state.

**Fresh-boot isolation confirmed:** after a kill/relaunch, `GET /servicing/agreements` and `/servicing/homeowners` both return `total_count: 0`, and a newly created record's `created_at` is `2026-08-01T00:00:00.000Z` — the clock default is the only pre-set value. `grep` confirms no sqlite, no file I/O, no `/tmp`, no seeding. Server stopped by resolving the pid from port 45301 (cwd verified) and `kill <pid>`; no `pkill` was ever run.

## Bug found and fixed this session
`app.py`'s 404/405/500 handlers called `ApiError(..., http_status=...)`, which the 2-arg constructor did not accept — a guaranteed `TypeError` on any unrouted request. `core.ApiError.__init__` now takes an optional `http_status` that falls back to `ERROR_STATUS.get(error_id, 400)`.

## PRD ambiguities resolved by choosing an interpretation (feeds Steps 8/9)
1. `api_request_timestamp` uses host wall clock; `created_at`/`updated_at` use the logical clock.
2. Default list order is `(created_at, insertion_seq)`; metered months order by `(period_year, period_month, seq)` when an `agreement_id` filter is present.
3. The clock endpoint requires no auth, ignores headers, and echoes `current_utc` canonicalised to 3 fractional digits + `Z`.
4. Integer fields reject JSON floats and booleans.
5. `severity` is set at creation, recomputed at triage and at `SERVICE_COMPLETE` resolution; `mark-false-positive` leaves it unchanged; `downtime_minutes` floats against the clock while open.
6. On a `RECORDED` month, `escalated_*`, `guarantee_floor_kwh`, `shortfall_kwh`, `credit_rate_millicents` and `credit_cents` are all 0.
7. `auto_reconcile` does not impose the reconcile endpoint's ServicingAgent-only restriction; its elapsed check runs after the duplicate check.
8. Ladder followed literally: `ERR_PERIOD_NOT_ELAPSED` before `ERR_DUPLICATE_PERIOD` and before `ERR_PERIODS_INCOMPLETE`.
9. Homeowner list endpoints are scoped to own records; a foreign `agreement_id`/`homeowner_id` filter yields `ERR_NOT_AGREEMENT_HOMEOWNER`.
10. `monitoring_status`, `open_outage_count`, `excused_downtime_minutes` are derived on read; the three credit counters are stored and mutated explicitly.
11. `clear-title` stamps `requested_by_transfer_case_id` only where currently null, bumping exactly those filings.
12. UCC `terminate` is blocked by any `TITLE_CLEARED` case on the same agreement.
13. `savings-projection` on a non-`ACTIVE`/non-`END_OF_TERM_PENDING` agreement → `ERR_INVALID_STATE_TRANSITION`.
14. The relocation successor snapshots `grandfathered_export_rate_millicents`, re-evaluates `tariff_grandfathered`, copies `state_code`/`homeowner_id`, re-derives `contract_end_date`, and starts `renewal_count` at 0.
15. No maximum truck-roll window length is enforced (the PRD sets none).
16. Unknown body fields → `ERR_INVALID_REQUEST`; unknown query params are ignored; enum/int filters are validated.
17. Explicit `null` on an optional field is treated as absent.
18. `parse_float=Decimal` on the way in, `float()` on the way out.
19. Auth headers are `X-User-ID`/`X-User-Role` (PRD beats the scaffold's `X-Role`).
20. `current_contract_year` is clamped to `1..term_years + 12*renewal_count`; a period's `contract_year` is left unclamped.
21. Reconcile against a decommissioned agreement → `ERR_AGREEMENT_DECOMMISSIONED`; reconcile checks period state, then agreement lifecycle, then elapsed.
22. True-up, UCC-filing and warranty-claim creation are not lifecycle-gated.
23. `system_dc_kw` minimum is 0.01 (strictly positive at ≤2dp).
24. `UtilityTariff` carries only `id` + `created_at` (no `updated_at`/`version`).
25. Truck-roll `scheduled_window_end <= scheduled_window_start` → rung 3 `ERR_INVALID_REQUEST`, before the FK lookup.
26. `disposition`/`root_cause` incoherence at close-out → `ERR_INVALID_STATE_TRANSITION` (a transition precondition, per "does not satisfy either completion transition").
27. `filed_date` after the clock date → rung 3 `ERR_INVALID_REQUEST` (no dedicated code exists), before the agreement FK lookup.
28. Transfer-create rung order: `ERR_AGREEMENT_NOT_ACTIVE` → `ERR_TRANSFER_ALREADY_OPEN` → generic state → `ERR_AGREEMENT_DECOMMISSIONED` → `ERR_CLOSING_DATE_IN_PAST` → `ERR_BUYER_FIELD_MISMATCH`.
29. Election-create rung order with `TRANSFER_PENDING` deliberately falling through rung 8 to rung 12 (`ERR_TRANSFER_IN_PROGRESS`).
30. Buffered roof conflict implemented as `(start-3d) <= (o_end+3d) and (o_start-3d) <= (end+3d)`; verified a 3-day gap conflicts and a 7-day gap does not.
31. `remove-panels`/`reinstall` set `service_status` unconditionally; "freezes `suspension_end_date`" means no change to it.
32. **Cascade scope conflict:** §3.10 says a `PURCHASE`/`REMOVAL` execution terminates "every `UccFiling` not already `TERMINATED`", while §3.9 says it "terminates every filing out of `FILED` or `SUBORDINATED`" and explicitly contrasts that with `PREPAYMENT`, which "terminates filings out of `FILED`, `SUBORDINATED` and `TERMINATION_REQUESTED` alike". I implemented §3.9's narrower enumeration for elections (so a `TERMINATION_REQUESTED` filing survives an election execution) because that sentence is the one drawing the distinction deliberately; `PREPAYMENT` close reaches all three states and stamps `requested_by_transfer_case_id` only on `FILED`/`SUBORDINATED` sources.
33. The subordination requester is kept in a private `_subordination_requested_by` key (no public field exists for it); `public()` strips `_`-prefixed keys.
34. `/request-subordination` with no open case → `ERR_INVALID_STATE_TRANSITION`; when several cases qualify, the earliest by `(created_at, _seq)` is stamped.
35. A Homeowner may read/list a transfer case where they are the `buyer_homeowner_id`, not only where they own the agreement.
36. Unrouted URLs, wrong methods and unexpected exceptions return off-catalogue `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) inside the standard error envelope.

Isolation was maintained: I never read `test_suite/`, `test_helpers/`, or any sibling `task_*/`. Scratch artifacts (`smoke.py`, `server*.log`) are confined to `.scratch/step6/`.

## Step 5: Generate unit tests — 2026-09-05T21:59:58.983Z

(Ran concurrently with Step 6; returned second, so this entry is appended after Step 6's.)

Step 5 is complete. 134 tests across 13 suite files, plus 9 helper modules.

## Files written

`test_helpers/` (2405 lines)

| file | lines |
|---|---|
| `__init__.py` | 20 |
| `api_client.py` | 580 |
| `api_errors.py` | 147 |
| `assertions.py` | 213 |
| `constants.py` | 240 |
| `factories.py` | 400 |
| `fixtures.py` | 676 |
| `test_users.py` | 103 |
| `types.py` | 26 |

`test_suite/` (7459 lines)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 17 | — |
| `test_01_registry_and_envelope.py` | 654 | 17 |
| `test_02_activation_and_grandfathering.py` | 424 | 9 |
| `test_03_monthly_cycle_and_settlement.py` | 567 | 12 |
| `test_04_true_ups_and_the_credit_cap.py` | 488 | 10 |
| `test_05_monitoring_and_dispatch.py` | 755 | 13 |
| `test_06_diagnosis_and_warranty.py` | 717 | 11 |
| `test_07_roof_work_and_suspension_windows.py` | 541 | 9 |
| `test_08_transfers_and_credit_review.py` | 591 | 11 |
| `test_09_payoff_quotes_and_closing_cascades.py` | 381 | 6 |
| `test_10_ucc_filings_and_the_title_chain.py` | 447 | 8 |
| `test_11_end_of_term_elections.py` | 705 | 12 |
| `test_12_authorization_and_the_rejection_ladder.py` | 725 | 10 |
| `test_13_versioning_consistency_and_uniqueness.py` | 447 | 6 |

**Total: 134 tests.**

## Coverage against the two design indices

Verified programmatically (AST-parses every `Design:` tag, cross-checks it against the instance names in both yaml files):

- **Queue A (Difficulty, §1.8): 19 instances, 0 stubs — 19 translated, 0 skipped.** Every one has >=2 tests (0 under-covered).
- **Queue B (Corner, §1.9): 95 instances, 12 source-stubbed — 83 live, 83 translated, 0 skipped.**
- 134 tests carry exactly one `Design:` line each; 102 distinct tags = 19 + 83, so no tag points at a stub or at a non-existent instance, and no test is untagged or dual-tagged.

**No instance failed the PRD-first filter** — every live instance had verbatim, uniquely-deriving PRD coverage for at least its headline outcome, so there are no gap lines to report. The 12 skipped corner instances are all pre-marked `excluded_because` in `SCAFFOLD_CORNER_DESIGN.yaml` itself (each defers to a §1.8 difficulty instance that already walks the same rule): `calculations/ppa_escalated_rate_is_rounded_before_it_multiplies_kwh`, `calculations/annual_true_up_methods_diverge_on_the_same_twelve_months`, `calculations/metered_kwh_exactly_at_the_guarantee_floor_earns_nothing`, `calculations/monitoring_status_is_reprojected_not_toggled`, `cross_cutting_complexity_layers/cascading_side_effect_chains`, `cross_cutting_complexity_layers/dual_variant_calculation_pairs`, `endpoints/transfer_creation_endpoint_forks_on_transfer_type`, `rbac/true_up_void_two_person_control`, `state_machines/transfer_creation_fork_between_assumption_and_prepayment`, `state_machines/warranty_claim_info_request_cycle_is_capped`, `state_machines/voiding_a_posted_true_up_reverses_its_ledger_movement`, `state_machines/prepayment_close_terminates_filings_and_locks_child_writes`.

## Where I narrowed a design instance's asserts (PRD did not uniquely derive them)

Three design asserts reach past the PRD; I dropped those individual assertions while still translating the instance:

1. `rbac/homeowner_touching_another_homeowners_agreement_is_forbidden` asked for a 403 on `GET /servicing/production-periods?agreement_id=<peer>` and for an unfiltered list to return only own rows. §2.3 declares no homeowner list-scoping rule and rung 6 speaks only of "the resolved target agreement", so I asserted only the single-resource and child-write 403s.
2. `errors/every_unknown_path_id_returns_its_own_not_found_code` implied an exclusive `{error_id, message}` error body. The §2.2 prose bullets ground presence, not exclusivity, so I assert presence and non-emptiness.
3. `validations/product_terms_that_contradict_product_type_are_rejected_both_ways` asserted `escalated_monthly_rent_cents 12900` / `escalated_rate_millicents 0` on the **agreement** create response. §3.2 records both fields "on a metered month", not on the agreement, so I get them from a reconciled contract-year-1 month instead.

## Verification performed

- `python3 -m py_compile test_suite/*.py test_helpers/*.py` — all clean.
- Citation audit over all 13 files: 296 quoted fragments checked, 7 flagged — every one a `...` elision whose two halves are individually verbatim in `workspace/PRD.md`. Zero paraphrases remain (I fixed four fabricated citations in test_02 and test_03 in this pass).
- Independently re-derived the new June-2026 literals from §3.3 before asserting them (rate 14750x1.029 -> 15178 millicents; 9600x0.1120 -> 1075 kWh; floor 1021; shortfall 121; credit 1837 cents; gross due 13660) — all match the design index.
- `grep -rniE "scaffold|§1\.[0-9]|SCAFFOLD_"` over both output dirs: no matches.
- Placement confirmed: `test_helpers/` and `test_suite/` are at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — nothing leaked. I never read, listed or grepped `workspace/implementation/`, never touched a sibling task, and never started/stopped a server or ran `pkill`. Scratch work stayed in `.scratch/step5/`.

Two design-index bugs found earlier and worth passing to Step 7 if failures cluster there: `TransferCase.title_cleared_at` is not a PRD field, and the corner index's `monitoring_status_is_reprojected_not_toggled` stub rationale points at a difficulty instance that covers the dispatch-cancel pair but not the two-dispatched-rolls case.

Orchestrator note on concurrency: Steps 5 and 6 were launched as two background Agent calls in immediate succession rather than in a single assistant message. Physical isolation still held — when Step 6 began writing its first module, `test_helpers/` and `test_suite/` did not yet exist on disk, and both agents were additionally given an explicit hard prohibition on reading the other's output directories. Step 6 reported it never read the test dirs; Step 5 reported it never read `implementation/`.

## Step 7: Run tests and iterate — 2026-09-05T22:20:53.377Z

All 144 tests pass in all 8 rounds. worklog.md untouched.

## Summary

**Iterations run:** 2 (each an 8-round parallel `--isolation per-test-server` sweep, 144 tests x 8 rounds).

Iteration 1 baseline: 136/144 passed in **every** round — 8 deterministic failures, zero flakiness, zero timeouts/connection errors. Two root causes, both test-artifact bugs; **no implementation change was needed**.

**Tests deleted:** none. Every failing assertion traced to verbatim PRD prose and survived the unique-derivability check (one needed a partial-coverage correction, below).

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` -> `successor_tariff_payload()`: the six schedule terms it pins (`utility_code`, `generation`, the two rates, `monthly_fixed_charge_cents`, `effective_from_date`) were hard-coded in the delegated `tariff_payload(...)` call while callers' overrides arrived through `**overrides`, so any caller supplying one of them raised `TypeError: got multiple values for keyword argument 'effective_from_date'` before a request was ever issued. Hoisted all six into explicit keyword parameters. This was the classic shared-fixture bug masquerading as many independent failures — it accounted for **7 of the 8** failures across `test_01` and `test_02` (the grandfathering, apply-tariff and savings-projection tests all need a successor schedule with a specific `effective_from_date` to exercise §3.2's three-part strict-comparison test).

**Fixes applied to `test_suite/`:**
- `test_suite/test_12_authorization_and_the_rejection_ladder.py` -> `test_authentication_is_settled_before_the_path_and_before_the_body`: replaced the raw string compare `assert echoed == CLOCK` with `assert_instant_equals(echoed, CLOCK)`. PRD §2.5 says only that the clock endpoint "moves the clock to the instant supplied as `current_utc` and echoes back `{ current_utc }`" — it does not pin the echo's sub-second width, so a faithful implementer may echo the literal input (`...T00:00:00Z`) or the §2.4 three-fractional-digit canonical form (`...T00:00:00.000Z`). That is partial coverage (STEP 1c): the instant identity is PRD-required, the string width is not. The suite's own `test_helpers/assertions.py` documents exactly this convention ("every instant comparison in the suite goes through `canonical_instant`") and this was the single call site that bypassed it.

**Fixes applied to `implementation/`:** none. No implementation defect was found in either iteration.

**Final tally: 144 / 144 passed, confirmed identically across all 8 parallel rounds** (259 s per round, 0 failed / 0 errors / 0 skipped in each). `results.1.json` ... `results.8.json` from the clean sweep are left in `workspace/implementation/`; `SWEEP_DONE` deleted. Scratch confined to `.scratch/step7/` (added `spotcheck.sh`, a pid-scoped per-test-server harness used to verify the two fixes before spending a sweep — no `pkill`, no sibling scratch touched).

Orchestrator verification (per the known "clean sweep with no artifacts" failure mode): re-read all eight `results.$i.json` independently — every file reports `passed=144/144 failed=0 errors=0 skipped=0`, all eight written at 22:15, and `SWEEP_DONE` is gone. The sweep was run from the pre-written `.scratch/step7/sweep.sh` under `setsid nohup`, which avoids both the inline-quoting bug and the early-return relaunch bug.

Orchestrator decision on Step 8: Step 7 exited with 0 deletions and 0 `implementation/` fixes, but it did apply one `test_helpers/` fix and one `test_suite/` fix, so this is NOT the zero-iteration skip case the skill defines (that requires 0 deletions AND 0 test_suite AND 0 test_helpers AND 0 implementation fixes). Step 8 therefore runs, with the two test-artifact fixes handed over as the `<step_7_diff>` focus list. Expect a small or possibly empty diff: the `factories.py` fix was a pure Python keyword-argument bug with no PRD content, and the `test_12` fix is a genuine PRD silence (the clock echo's sub-second width) that PRD_FINALIZED.md should pin to what the implementation actually emits.

## Step 8: Finalize PRD — 2026-09-05T22:23:32.963Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 439 lines; PRD_FINALIZED.md: 439 lines. 1 line revised, 0 added/removed → **0.23% of lines changed, 0% line-count delta.**

## Changes (1)
- **§2.5 The Logical Clock** — revise — pinned the width/normalization of the clock endpoint's `current_utc` echo: it is the clock's new value re-rendered as an ISO 8601 UTC instant with exactly three fractional-second digits (the §2.4 form), so the echo need not be byte-identical to the supplied string — `implementation/app.py:43` (`return ok({"current_utc": fmt_instant(clock.now())})`), `implementation/core.py:132-139`.

## Per-edit pre-edit search log

**Edit 1 — §2.5 clock echo**
- (a) Subject: how the API renders an instant it returns — specifically the width/normalization of the clock echo, and by extension every instant-valued field the implementation serializes (the risk being a wording that pins `.000Z` here while some other path echoes a client's literal string).
- (b) Paths enumerated and read/grepped: `core.py:132` `fmt_instant` (hard-codes `%.03dZ`); `core.py:87-116` `parse_instant`/`_INSTANT_RE` (accepts optional seconds, 1-9 fractional digits, `Z`/`z`/`±HH:MM` or no zone, and converts offsets to UTC — hence the echo can differ from the input in zone as well as width); `core.py:235` `_json_default` (any stray `datetime` reaching the JSON encoder also goes through `fmt_instant`); `core.py:248` `api_request_timestamp`; `core.py:282/292` `created_at`/`updated_at`; `app.py:38-43` the clock endpoint itself. Then every remaining instant-producing site, to check for any un-normalized echo: `r_outages.py:53` `detected_at` (client-supplied, re-rendered), `r_outages.py:134` `resolved_at`, `r_truckrolls.py:74-75` `scheduled_window_start`/`_end` (client-supplied, re-rendered), `r_truckrolls.py:148/156` `completed_at`/`resolved_at`, `r_trueups.py:157` `posted_at`, `r_elections.py:143/190` `accepted_at`/`executed_at`. A grep of `kind": "instant"` confirmed the only client-supplied instants in the whole API are `detected_at`, the two truck-roll window bounds, and `current_utc` — all four re-rendered via `fmt_instant`, so no path echoes a client literal.
- (c) Adjustment: I dropped an earlier draft phrase that generalized to "like every other instant this API returns" and instead scoped the sentence to this endpoint's echo, referring to §2.4 rather than restating a universal rule — the universal claim is in fact true of the current implementation, but scoping it keeps the edit local to the Step 7 site and leaves the general convention under-determined for Step 9. I also chose "need not be byte-identical to the one the client supplied" over an explicit mention of UTC-offset normalization, so the sentence covers both the fractional-width and offset cases without newly asserting that non-`Z` offsets are accepted on input (they are, but that is off the Step 7 site).

## Items deliberately not patched
- `test_helpers/factories.py` `successor_tariff_payload()` — pure fixture bug (`TypeError: got multiple values for keyword argument`, raised before any request). Verified §3.2 (PRD lines 157, 167, 169) already pins the tariff field set, the three-part strict-comparison grandfathering test, and apply-tariff's re-evaluation without re-snapshotting `grandfathered_export_rate_millicents`, and that `calc.evaluate_grandfathered` (`calc.py:118`) plus its three callsites (`r_core.py:259`, `r_core.py:272`, `r_transfers.py:285`) match that prose. No PRD silence → no edit.
- `implementation/` — Step 7 applied no implementation fixes, so there was no impl-vs-PRD mismatch to reconcile.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 98, §2.5), both files 439 lines. This is the expected shape given a `<step_7_diff>` containing zero implementation fixes — the HARD SCOPE was respected and no speculative Step 9 work leaked in.

## Step 9: Complete PRD — 2026-09-05T22:55:15.757Z

Orchestrator decision: rather than one subagent scanning all 17 implementation modules in a single shot (which reliably under-scans and can leave PRD_COMPLETED.md byte-identical to its source), Step 9 was run as **three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`**. Pass 1 owned the single `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from copying, opened the file as their predecessor left it, and edited in place with the Edit tool only. Each pass received its predecessors' hand-off notes.

Partition: pass 1 = cross-cutting layer (`core.py`, `web.py`, `serialize.py`, `guards.py`, `calc.py`, `app.py`); pass 2 = `r_core.py`, `r_periods.py`, `r_trueups.py`, `r_outages.py`, `r_truckrolls.py`; pass 3 = `r_roofwork.py`, `r_transfers.py`, `r_ucc.py`, `r_elections.py`, `r_warranty.py` plus a final §4/§5 consistency read-through.

### Aggregate result

- Source `PRD_FINALIZED.md`: 439 lines / 107,921 chars. Output `PRD_COMPLETED.md`: 439 lines / 129,606 chars — **+21,685 chars (+20.1%), 0 line-count delta, 54 of 439 lines changed**. Every edit is an in-paragraph insert or revision; no new sections, no new paragraphs. All 28 section headings intact; the file still ends at a real boundary (the last §5 error row).
- **Totals across the three passes: 61 edits — 44 ambiguity-pins, 17 mismatch-revisions.**

### Pass 1 — cross-cutting layer (14 edits: 13 ambiguity-pins, 1 mismatch-revision)

- §2.1 — insert — ambiguity — acting `X-User-ID` is never resolved against the homeowner collection (a bogus id is not a 404, it just owns nothing); collection reads are silently narrowed to owned rows with `total_count` reflecting the narrowed set, but an explicit `agreement_id` filter naming an unowned or nonexistent agreement is `ERR_NOT_AGREEMENT_HOMEOWNER`, never a 404 or empty page — `guards.py:34-40`, `r_core.py:231-235`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `core.py:224-228`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host wall clock, not the logical clock — `core.py:245-249`
- §2.2 — insert — ambiguity — pagination `meta` fields appear on list responses only — `web.py:29-50`
- §2.3 — insert — ambiguity — `limit`/`offset` must be bare decimal integer literals; ordering ties broken by insertion order — `web.py:176-200`, `core.py:297-299`
- §2.3 — insert — ambiguity — filters match by exact equality (no match => empty page, not an error); enum/bool/int filter validation; undeclared query params ignored — `web.py:203-244`
- §2.4 — insert — ambiguity — `created_at` reads the logical clock; full accepted instant input grammar (space or `T`, lower-case `t`/`z`, optional seconds, 1-9 fractional digits, `+HH:MM`/`+HHMM` normalised, no zone => UTC) vs dates (`YYYY-MM-DD` only) — `core.py:87-145,279-288`
- §2.4 — insert — ambiguity — reference fields need not look like UUIDs (any non-empty unmatched string => 404), but `""` is rung 3 `ERR_INVALID_REQUEST` — `web.py:145-147`, `guards.py:24-31`
- §2.5 — insert — ambiguity — `current_utc` mandatory and parsed by §2.4 rules; missing/null/non-string/unparseable or any extra field => `ERR_INVALID_REQUEST`; rungs 1-2 don't apply to this endpoint but rung 3 does — `app.py:38-43`
- §2.6 — insert — ambiguity — exact decimals in and through, but emitted as bare JSON numbers so trailing zeros are lost (`72.00`->`72.0`); whole-year date advances clamp a short target month (29 Feb -> 28 Feb) — `web.py:76`, `core.py:231-242,156-162`
- §2.8 — insert — ambiguity — `monitoring_status`, `open_outage_count`, `excused_downtime_minutes`, `current_contract_year` recomputed on every serialisation and a read advances neither `version` nor `updated_at` — `serialize.py:6-13`
- §2.10 rung 3 — insert — ambiguity — numeric bounds inclusive both ends; explicit `null` = absence; any undeclared field rejected with the whole-body unknown-key check running before per-field checks; absent/empty body = `{}` — `web.py:71-170`
- §3.5 — insert — ambiguity — read-time split: `downtime_minutes` refreshed against the clock while open and floored at 0; `severity` stored — `serialize.py:32-42`, `r_outages.py:110-114`
- §5 preamble — revise — **mismatch** — PRD claimed the error envelope carries `success: false` and a nested `error` object with a `code`; impl emits `response_type: "error"` with `data.error_id` + `data.message`. Same edit pins the three off-catalogue transport codes `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) and `strict_slashes = False` — `web.py:47-50`, `app.py:27,51-69`

Pass 1 verified all 15 `calc.py` calculations reproduce the PRD exactly (constants, rounding points, clamping, step order) — no change needed there.

### Pass 2 — r_core / r_periods / r_trueups / r_outages / r_truckrolls (26 edits: 19 ambiguity-pins, 7 mismatch-revisions)

- §2.1 — insert — ambiguity — the agreement collection has no `agreement_id` filter, so `homeowner_id` is the strictly-checked one — `r_core.py:231-235`
- §2.3 — insert — ambiguity — `contract_year`/`period_year`/`period_month` filters parsed leniently, unlike the strict `limit`/`offset` rule — `web.py:211-215`
- §2.7 — insert — ambiguity — both expected-version fields are plain integers with no range bound; zero/negative reaches the comparison and reports the stale-version code — `r_trueups.py:26`, `r_truckrolls.py:30`
- §2.9 — revise — mismatch — "`credit_balance_cents` ... is never negative" qualified by the reopen case — `r_periods.py:228-230`
- §3.1 — insert — ambiguity — email uniqueness is case-insensitive but the list `email` filter is exact and case-sensitive — `r_core.py:60`, `web.py:239`
- §3.1 — insert — ambiguity — the `(utility_code, tariff_code)` uniqueness pair compared as exact case-sensitive strings — `r_core.py:86-87`
- §3.1 — insert — ambiguity — the first-of-month rule on `contract_start_date` is rung 3 decided before FKs resolve; the required base-rate field may be 0 — `r_core.py:161-163,132-133`
- §3.1 — insert — ambiguity — booking initialises `grandfathered_export_rate_millicents` to 0 and `tariff_grandfathered` to false — `r_core.py:195-196`
- §3.2 — insert — ambiguity — apply-tariff is gated on neither lifecycle nor asset dimension and re-checks no product terms — `r_core.py:264-274`
- §3.2 — insert — ambiguity — the savings-projection lifecycle gate reports `ERR_INVALID_STATE_TRANSITION` (409), after the homeowner-scope check — `r_core.py:282-285`
- §3.3 — insert — ambiguity — both auto flags default false; a reconcile refused with `ERR_PERIOD_NOT_ELAPSED` still leaves the new month persisted in `RECORDED` (no rollback), so a retry reports `ERR_DUPLICATE_PERIOD` — `r_periods.py:30-31,144-151`
- §3.3 — insert — **mismatch** — the month's own `status` is tested before every parent check, so re-reconciling a settled month reports `ERR_INVALID_STATE_TRANSITION` even where §2.10's precedence would have given `ERR_AGREEMENT_NOT_ACTIVE`/`ERR_AGREEMENT_DECOMMISSIONED` — `r_periods.py:195-199`
- §3.3 — insert — ambiguity — reconciliation also rewrites `gross_expected_kwh`, `escalated_rate_millicents`, `escalated_monthly_rent_cents` — `r_periods.py:48-60`
- §3.3 — insert — **mismatch+ambiguity** — reopen consults neither `lifecycle_state` nor `service_status`; leaves six settled fields at their settled values; and drives `credit_balance_cents` below 0 when a later month already consumed the reopened month's credit — `r_periods.py:211-240`
- §3.4 — revise — **mismatch** — `ERR_PERIOD_NOT_ELAPSED` is evaluated first over whatever months the year holds, so five months with one unelapsed reports it rather than `ERR_PERIODS_INCOMPLETE`; neither test consults the agreement's state — `r_trueups.py:44-53`
- §3.4 — revise — ambiguity — `posted_at` is also null on a `DRAFT` true-up — `r_trueups.py:87`
- §3.4 — insert — ambiguity — under `MONTHLY_ROLLING` a never-reconciled month contributes 0 to both sums while still counting toward the twelve — `r_trueups.py:61-62`
- §3.4 — insert — ambiguity — the three post-status tests' fixed order; a `VOID` true-up reports `ERR_TRUE_UP_ALREADY_POSTED` when a posted sibling exists and `ERR_INVALID_STATE_TRANSITION` otherwise — `r_trueups.py:135-153`
- §3.4 — insert — ambiguity — voiding retains `posted_at`/`posted_by_user_id`; a `DRAFT` void leaves the agreement's `version`/`updated_at` untouched — `r_trueups.py:172-184`
- §3.5 — revise — **mismatch** — corrected pass 1's "`severity` ... revised only by triage": it is also re-graded when a serviced visit resolves the event; false-positive and `NO_ACCESS` close-outs do not re-grade — `r_truckrolls.py:158`
- §3.5 — insert — ambiguity — triage leaves the agreement wholly alone; `excused` stays false — `r_outages.py:110-118`
- §3.5 — insert — ambiguity — `scheduled_window_end > start` is rung 3 decided before `outage_event_id` resolves; dispatch consults no agreement state — `r_truckrolls.py:43-48`
- §3.6 — revise — ambiguity — the disposition/`root_cause` pairing violation is `ERR_INVALID_STATE_TRANSITION` (409), tested after the duty check and the roll's `SCHEDULED` status — `r_truckrolls.py:127-137`
- §3.6 — insert — ambiguity — `severity` re-graded off the frozen downtime figure at resolution — `r_truckrolls.py:158`
- §4 (activate row) — revise — **mismatch** — activation does not open the asset/monitoring dimensions — `r_core.py:255-259`
- §4 (triage row) — revise — **mismatch** — triage does not decide `excused` — `r_outages.py:110-117`

Pass 2 resolved pass 1's hand-offs: the `auto_reconcile`/`auto_issue_credit` leak does NOT exist (`create_period` never copies them onto the row, so §3.3's "never stored or echoed back" is correct against the bare `period_view`); the version-field specs, email case asymmetry, and savings-projection gate code were all pinned. It deliberately left the `grandfathered_export_rate_millicents`-defaults-to-0-when-tariff-missing path unpinned as unreachable, noting that pinning the `0` alone would be misleading since the non-grandfathered branch would instead 500.

### Pass 3 — r_roofwork / r_transfers / r_ucc / r_elections / r_warranty (21 edits: 12 ambiguity-pins, 9 mismatch-revisions)

- §2.1 — insert — ambiguity — buyer's read access to a transfer case: single read skips the ownership comparison, collection read returns the union of own-agreement cases and cases naming the caller as buyer, explicit `agreement_id` filter still checked strictly — `r_transfers.py:131,154-155`
- §2.8 — insert — ambiguity — asset-dimension arrows are unconditional assignments; the source value is a precondition only where §3 says so — `r_roofwork.py:173,202`, `r_transfers.py:229`, `r_elections.py:146,186`
- §2.10 rung 8 — revise — **mismatch** — `ERR_AGREEMENT_NOT_ACTIVE` enumerated to the same five record kinds as rung 10; fixture filings and warranty claims explicitly ungated — `r_ucc.py:34-58`, `r_warranty.py:40-84`
- §3.6 — insert — ambiguity — `approved_amount_cents` of 0 is a valid approval (min 0, not min 1) — `r_warranty.py:165-166`
- §3.7 — revise — ambiguity — roof-work `contract_year` uses §3.3's month-index arithmetic and is left unclamped, unlike the agreement's `current_contract_year` — `r_roofwork.py:68`, `calc.py:70`
- §3.7 — insert — ambiguity — all six post-creation transitions gated on the order's own `status` alone; the agreement's dimensions are consulted only at creation — `r_roofwork.py:107-218`
- §3.8 — insert — ambiguity — `new_site_address` bounds (1-200 characters, not blank) — `r_transfers.py:32-33`
- §3.8 — insert — ambiguity — only an `ACTIVE` agreement may open a case; `END_OF_TERM_PENDING` yields `ERR_INVALID_STATE_TRANSITION`, checked after the already-open search — `r_transfers.py:63`
- §3.8 — insert — ambiguity — buyout arms carry `payoff_method` null and `payoff_quote_cents` 0 until clearance — `r_transfers.py:108`
- §3.8 — insert — ambiguity — `remaining_term_months` of 0 produces no buckets and a `payoff_quote_cents` of 0 — `calc.py:311-320`
- §3.8 — revise — **mismatch** — clearance stamps `requested_by_transfer_case_id` only on filings whose value is still null (including `TERMINATED` ones) and bumps each stamped filing's `version` — `r_transfers.py:224-227`
- §3.8 — revise — **mismatch** — successor copy list corrected: removed the non-existent `base_rate_millicents_per_kwh`, named both real base-rate fields plus `homeowner_id`/`state_code`, added `renewal_count` 0, recomputed `contract_end_date`, fresh export-rate snapshot, re-evaluated `tariff_grandfathered`, initial dimensions, version 1 — `r_transfers.py:250-288`
- §3.9 — insert — ambiguity — `filing_number` duplicates compared case-sensitively; a future `filed_date` is rung 3 ahead of `agreement_id` resolution and the duplicate search — `r_ucc.py:37-44`
- §3.9 — insert — ambiguity — no qualifying open case yields `ERR_INVALID_STATE_TRANSITION`; the subordination requester is retained internally and exposed as no field — `r_ucc.py:94-101,112-115`, `core.py:302-308`
- §3.9 — revise — **mismatch** — the termination request stamps nothing, and the terminate block fires on any `TITLE_CLEARED` case on the agreement regardless of the filing's `requested_by_transfer_case_id` — `r_ucc.py:125-152`
- §3.9 — revise — **mismatch** — election cascade reaches only `FILED`/`SUBORDINATED`; a `TERMINATION_REQUESTED` filing survives it, only PREPAYMENT sweeps it up, and only PREPAYMENT stamps the case id — `r_elections.py:151-161`, `r_transfers.py:235-247`
- §3.10 — insert — ambiguity — the window dates are computed at submission and recorded on the election, not on the agreement — `r_elections.py:80-81`
- §3.10 — revise — **mismatch** — PURCHASE acceptance is blocked only by a strictly positive `credit_balance_cents`; a negative balance passes — `r_elections.py:138`
- §3.10 — revise — **mismatch** — PURCHASE/REMOVAL execution terminates only `FILED`/`SUBORDINATED` filings (was "every filing not already TERMINATED"), plus the REMOVAL `DECOMMISSION_PENDING` precondition's ordering and error code — `r_elections.py:186,197-203`
- §4 (elections POST row) — revise — **mismatch** — "pricing all applicable options" -> prices the elected option and leaves the other two price fields at 0 — `r_elections.py:75-92`, `calc.py:407-435`
- §4 (warranty request-info row) — revise — **mismatch** — `revision_count` is moved by the re-submission, not by request-info — `r_warranty.py:128-133` vs `137-150`

**The §3.9/§3.10 UCC-cascade contradiction flagged by the implementation generator (its ambiguity note 32) is now resolved in both places**, matching the code: the narrower `FILED`/`SUBORDINATED` enumeration for election execution, the wider three-status sweep for PREPAYMENT close, and the case-id-stamping asymmetry, all stated explicitly.

**Pass 3's final §4/§5 consistency read-through: clean.** All 69 §4 rows match the 68 registered blueprint routes plus `POST /_clock/set_current_utc` — identical paths, methods and authorised-role sets. The §5 catalogue's 49 error ids and HTTP statuses match `core.ERROR_STATUS` exactly, with the three transport codes correctly documented as off-catalogue.

Pass 3 deliberately left two things unpinned as unreachable-and-misleading-if-pinned: the `UNAMORTIZED_SYSTEM_COST` `total_term_months == 0` coercion (`term_years` is always one of 10/15/20/25), and the PREPAYMENT sweep's "anything not `TERMINATED`" phrasing (observationally identical to the three-status enumeration, since a `SUBORDINATION_REQUESTED` filing cannot survive to a prepayment close).

### Orchestrator verification

- `PRD_COMPLETED.md` exists, is **not** byte-identical to `PRD_FINALIZED.md` (54 changed lines, +21,685 chars) — the known "the scan never ran" failure mode did not occur.
- Exactly one `cp` happened, in pass 1; passes 2 and 3 confirmed they never copied, and each pass verified its predecessors' edits survived.
- All 28 section headings intact; the file still ends on the final §5 error row, so no pass truncated it.
- `implementation/` file mtimes are all from Step 6 (20:23-20:42) — Steps 8 and 9 changed documentation only, so Step 7's clean sweep still characterises this code. Re-read all eight `results.$i.json`: still 144/144 in every round.
- Single `worklog.md` at the task root; no stray copies under `workspace/` or `implementation/`.

Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.

