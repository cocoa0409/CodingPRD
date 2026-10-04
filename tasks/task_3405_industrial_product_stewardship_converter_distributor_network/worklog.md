# Worklog — task_3405_industrial_product_stewardship_converter_distributor_network

## Step 1: Create Task Directory — 2026-10-01T19:03:00.000Z

Task directory `./tasks/task_3405_industrial_product_stewardship_converter_distributor_network/` was pre-allocated by the caller with `workspace/` inside; verified it exists and is empty. No new index computed, no other task_* directory created. Scenario: Industrial Product Stewardship & Converter Distributor Network (3M) — formulation regulatory review across jurisdictions, converter slit/die-cut/laminate network with authorization (equipment capability, quality system, territory), technical service / application engineering / adhesion testing, distributor+converter pricing tiers with rebates and channel conflict management, product change notification + last-time-buy on discontinuation, regulated substance phase-out with reformulation and customer qualification, counterfeit detection in secondary channels. Difficulty instruction: "much harder than expert level" (applies to scaffold generation only).

## Step 2: Generate Scaffold — 2026-10-01T20:15:00.000Z

All three scaffold artifacts are generated, lint-clean, and verified.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_3405_industrial_product_stewardship_converter_distributor_network/`)

- `SCAFFOLD.yaml` (§1.0–§1.7; no design keys) — 1559 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 18 instances, exactly 2 per each of the 9 rules
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 49 entries: 46 active + 3 `excluded_because` stubs

**Counts:** 15 entities, 9 state machines, 9 calculations, 28 ordered validations, 58 endpoints, 29 error codes, 9 roles (7 opaque + 2 entity-backed: Converter, Distributor), 3 OCC concurrency rules, 592 test-recipe calls — `scaffold_lint.py` verdict: **clean lint** on the first run, including FK reverse-reachability for all 24 declared FKs.

**Domain fidelity (check e):** `api_prefix: /stewardship`; entities cover all 8 scenario pillars — formulations + jurisdiction clearances + disclosure levels (regulatory review), Converter + ConverterAuthorization capability/territory windows (converter network), audit→authorize with SoD (quality system), ApplicationCase + adhesion pass calc (technical service), PriceAgreement/Order/RebateProgram/RebateAccrual + channel floor (pricing tiers, rebates, channel conflict), discontinue + LTB pool (PCN/last-time-buy), PhaseOutProgram with successor qualification gates (phase-out/reformulation), CounterfeitReport sweeps (counterfeit detection).

**Difficulty profile:** compliance/audit × pricing engine; flat topology; cyclic machines (clearance resubmission loop, converter suspend/reinstate/revoke, case retest loop) plus parallel fulfillment×compliance axes on Order; dual-variant calcs on two domains (rebate provisional-vs-final with bracket re-baselining; adhesion nominal-vs-derated); combinatorial calcs in modes (a) average-rate tier+breakpoint pricing and (b) pinned per-order-then-sum rounding; depth-3 phase-out cascade vs depth-2 counterfeit cascade; disjoint validation-priority pairs (state-vs-fiscal, safety-vs-temporal); half-open authorization windows vs aggregate bench-hours; LTB-pool-units vs bench-hours compensating invariants. Every numeric assert is a pre-computed literal (e.g., floor 8856c, unit 15400c/line 4620000c, accrual 70000→10000c, rounding 999c≠1000c, derated threshold 15.9). All fixture dates are reachable from the pinned clock default `2026-09-01T00:00:00Z`.

**Adjudicated design decisions:**
1. **Endpoint count 58** — above the Expert guideline (20–32). The requester demanded "much harder than expert," and the lint's FK reverse-reachability rule forces a single-GET + filtered-list GET per child entity, which alone floors the surface near 40. I folded PCN into `POST /formulations/{id}/discontinue`, qualification runs into a `record-qualification` action on PhaseOutProgram, and per-transition actions into state-driven `/advance` endpoints to keep the count from going higher. Note for downstream: per your memory, Step 6 impl-gen should be pre-constrained (one file per message, per-domain modules).
2. **Compliance flags are absorbing** — my first draft let a later CLEARED_GENUINE disposition release flags, but the triggering CONFIRMED report is terminal and can't be re-dispositioned, making release contradictory; simplified to CLEAR→FLAGGED only.
3. **OCC parents chosen to pass the serial-observability filter** — Formulation (successor create), Converter (authorization create), PriceAgreement (order create); each write endpoint bumps the parent version so the stale-version loser is deterministic with strictly sequential calls.
4. **Clearance resubmission is an upsert** on `POST /clearances` keyed by (formulation, jurisdiction) from CHANGES_REQUESTED/SUSPENDED (200 vs 201 pinned), avoiding a separate endpoint while keeping the cycle testable.
5. **One fix during verification:** `ERR_ACCRUAL_NOT_FINALIZED` was cataloged and corner-tested but not wired into any validation/transition — added it as the specialized priority-8 state error on the accrual claim transition.

Orchestrator verification: all three files parse as YAML; SCAFFOLD.yaml top-level keys exclude both design keys; design files each carry exactly their single top-level key; api_prefix=/stewardship; entity list matches this scenario's domain (Jurisdiction, Substance, Formulation, FormulationComponent, JurisdictionClearance, Converter, Distributor, ConverterAuthorization, ApplicationCase, PriceAgreement, Order, RebateProgram, RebateAccrual, PhaseOutProgram, CounterfeitReport).

## Step 3: Copy Shared Files — 2026-10-01T20:17:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T20:40:00.000Z

PRD generation is complete and all three hard contracts pass.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3405_industrial_product_stewardship_converter_distributor_network/workspace/PRD.md` — 348 lines, written incrementally in 9 chunks (each verified on disk; no truncation).

**Section list:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC (9 roles, opaque vs entity-backed identity prose), 2.2 API Response Structure (byte-identical to the canonical verbatim block — verified by diff), 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties & Version Semantics, 2.6 OCC, 2.7 Units/Precision/Rounding, 2.8 Half-Open Windows, 2.9 Validation Order & Error Precedence, 2.10 Cascades/Bubble-Ups/Compensations
- §3 Business Logic (9 subsections): 3.1 Reference Data & disclosure-level computation, 3.2 Formulation lifecycle/clearance/discontinuation, 3.3 Converter onboarding/audit/authorization, 3.4 Application engineering/bench capacity/adhesion testing, 3.5 Pricing agreements & channel floor, 3.6 Orders/fulfillment/LTB pool, 3.7 Rebate programs & accrual settlement, 3.8 Phase-out & reformulation, 3.9 Counterfeit detection
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Coverage self-audit (scaffold → PRD):**
- §1.1 entities: **fully covered** — all 15 entities; every field name present (106/106 required identifiers verified programmatically, exact-token match, 0 missing — includes tricky pairs like `audit_score` input vs `quality_audit_score` field, and `last_time_buy_deadline` input vs `ltb_deadline` field, with the mapping stated explicitly); FormulationComponent's missing `updated_at`/`version` stated.
- §1.2 state machines: **fully covered** — all 9 machines, all **34/34 transitions** expressed with from/to states, preconditions, error_ids, and side effects (manually walked); parallel Order dimensions and all terminal states named.
- §1.2.1 concurrency rules: **3/3** — each names write endpoint, OCC field, `ERR_STALE_VERSION`, 412 (verified programmatically).
- §1.3 calculations: **9/9 fully expressed in prose** — including pinned rounding order (unit price before multiply; per-tier portion before sum; floor at each step), both adhesion variants with same-peel-divergence note, both rebate variants with re-baselining consequence, sweep selection orders (`created_at` ASC), and successor-exclusion in the phase-out sweep.
- §1.4 validations: **28/28** — full priority ladder 1–28 rendered explicitly in §2.9, including the `ERR_ACCRUAL_NOT_FINALIZED` priority-8 specialization and the both-absent (`ERR_INVALID_REQUEST`) vs both-present/inconsistent (`ERR_BUYER_AMBIGUOUS`) split.
- §1.5 endpoints: **58/58** table rows (verified programmatically); status-code rules plus the 201/200 resubmission and 200-no-op qualification exceptions stated; list filters enumerated per endpoint.
- §1.6 errors: **29/29** in the catalogue and in narrative (verified programmatically).
- §1.7 roles: **9/9** named with identity translations; SoD rules stated.

**Contract 3 (§3 path purity):** 535 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos. PASS.

Two intentionally unpinned points (scaffold itself assigns no error_id): the discontinue preconditions and the rebate-program activation clock check are stated as preconditions without invented error codes.

Orchestrator spot-check: 348 lines; 67 `ERR_` mentions; 58 endpoint table rows; logical-clock default `2026-09-01T00:00:00Z` matches scaffold; zero matches for design-index leakage tokens (test_recipe / scaffold_difficulty / scaffold_corner / Corner/ / Difficulty/).

## Step 5: Generate Unit Tests — 2026-10-01T21:20:00.000Z

All verification gates pass. The task is complete.

## Summary

**Stage 1 — `test_helpers/` (9 files, all compile-checked, frozen before Stage 2):**
- `types.py` — 18 enums + 15 entity TypedDicts (FormulationComponent correctly omits `updated_at`/`version` per PRD §2.5)
- `constants.py` — 16 thresholds, all valued verbatim in PRD prose (75 audit floor, 8.0 bench hours, 0.08 channel margin, tier discounts, adhesion thresholds, derate 0.03/step, etc.); zero invented constants
- `api_errors.py` — 29 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `api_client.py` — `ApiClient(GenericApiClient)` with 45 methods, one per PRD §4 endpoint including `/_clock/set_current_utc`
- `factories.py` — 21 payload factories; optional fields omitted when unset
- `assertions.py` — 15 entity assertions + LTB pool invariant checker
- `test_users.py` — `TEST_USERS` for all 9 roles + mandatory `make_converter_headers`/`make_distributor_headers` entity-backed builders
- `fixtures.py` — ~40 composite helpers (OCC-guarded writes re-fetch parent version; entity-backed callers always authenticate with the real entity id; every chain drives the logical clock to 2026-10-01 first), plus two heavy composites: `setup_phaseout_enforceable_scenario` (through QUALIFYING with 2 qualified customers) and `setup_rebate_flagged_scenario` (two SHIPPED orders, one FLAGGED via confirmed report)

**Stage 2 — `test_suite/` (conftest + 10 files, 82 tests):**

| File | Tests | Content |
|---|---|---|
| test_01_formulation.py | 9 | 8 corner entities + active_clearance_count reconciliation |
| test_02_clearance_disclosure.py | 8 | 6 corner + clearance resubmission cycle ×2 |
| test_03_converter_authorization.py | 8 | 4 corner + converter-state gate ×2, window adjacency ×2 |
| test_04_application_cases.py | 11 | 1 corner + adhesion dual-variant, bench 8.0 boundary, bench aggregate, terminal-vs-capacity priority, book/result conservation (×2 each) |
| test_05_pricing_orders.py | 12 | 8 corner + average-rate pricing ×2, clearance-gated order ×2 |
| test_06_ltb.py | 6 | LTB deadline inclusivity ×2, pool conservation ×2, clearance-vs-LTB priority ×2 |
| test_07_rebate.py | 11 | 7 corner + provisional/final dual variant ×2, per-portion rounding ×2 |
| test_08_phase_out.py | 4 | 2 corner + enforcement cascade ×2 |
| test_09_counterfeit.py | 5 | 1 corner + counterfeit cascade ×2, dual-axis order ×2 |
| test_10_cross_cutting.py | 8 | envelope, RBAC ×3, pagination, OCC ×3 |

**AST tag audit:** 82/82 tests carry exactly one valid `Design:` line; 18/18 difficulty instances at exactly 2 tests; 46/46 non-stub corner instances at exactly 1; all 3 `excluded_because` stubs untranslated (cross-references resolve); zero unknown tags.

**PRD verbatim sweep:** every ≥8-word docstring quote greps literally in PRD.md — 2 initial failures fixed (table-quote trailing period, abbreviated §2.9 quote) and 5 `...` elisions rewritten to full sentences.

**Collection:** `PYTHONPATH=. python3 -m pytest test_suite/ --collect-only -q` → **82 collected, 0 errors**. No skip/xfail marks; no scaffold references in generated code.

**Skipped instances: none** — all 64 non-stub instances passed the PRD-first filter. Two adjudications worth noting: (a) the channel-floor test sets up its reference converter agreement on an AUTHORIZED converter instead of the recipe's APPLIED one (PRD gates converter standing on orders/grants, not agreement creation — removes a two-reader wobble, floor assertion unchanged); (b) `program_close_before_period_end_rejected` kept as ERR_INVALID_STATE since §3.7 names the period-end requirement and the §2.9 gauntlet offers no other candidate error for a state-targeted advance.

Orchestrator verification: all 9 helper files + conftest + 10 test files exist on disk; independent `pytest --collect-only` re-run → 82 collected, 0 errors.

## Step 6: Generate Implementation — 2026-10-01T22:10:00.000Z

All audits pass and no stray processes remain (the pgrep hit was the audit command's own shell wrapper). Implementation complete.

## Summary

**Task**: task_3405_industrial_product_stewardship_converter_distributor_network — Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_3405_industrial_product_stewardship_converter_distributor_network/workspace/implementation/`

**Modules (21 Python files + start.sh + requirements.txt, 2,956 lines total)**:
- `app.py` (52) — blueprint registration, error handlers, `0.0.0.0:$PORT` foreground entry
- `start.sh` (10) — guarded pip install (import-check first), `exec python3 app.py`
- `constants.py` (45) — every SCAFFOLD `constants:` literal defined once
- `errors.py` (66) — `ApiError` + all 29 catalog entries
- `store.py` (119) — in-memory dict stores, logical clock (default `2026-09-01T00:00:00Z`), ISO-8601 3-fractional-digit formatting, `stamp_new`/`touch` (version+updated_at), insertion-seq tie-break
- `envelope.py` (53) — `meta`/`response_type`/`data` envelope, pagination in `meta` for lists only
- `validation.py` (161), `auth.py` (41), `serialization.py` (237) — shape validators, X-User-ID/X-User-Role + 9 roles, field-exact serializers (FormulationComponent without version/updated_at)
- `calcs.py` (242) — disclosure level, order unit price (avg-rate, round-at-unit), marginal chronological rebate (per-portion half-up), adhesion thresholds (derated 2dp), channel floor, bench capacity, phase-out affected-set
- `cascades.py` (201) — flag/unflag, provisional accrual recompute, converter-suspension cascade, counterfeit confirm/release sweeps, phase-out enforcement sweep
- Routes by domain: `routes_clock.py` (24), `routes_reference.py` (84), `routes_formulations.py` (199), `routes_clearances.py` (143), `routes_converters.py` (215), `routes_cases.py` (140), `routes_pricing.py` (150), `routes_orders.py` (265), `routes_rebates.py` (244), `routes_phaseout.py` (170), `routes_counterfeit.py` (94)

**58-endpoint audit**: programmatic check of PRD §4's 58 rows against Flask's url_map — 58 registered, 0 missing, 0 extra.

**ERR_* audit**: 29 catalog ids, each defined exactly once; zero referenced-but-undefined (the 500 fallback uses out-of-catalog `ERR_INTERNAL_ERROR` via direct `ApiError` construction, never the catalog guard). The three helpers (`invalid_request`/`invalid_state`/`stale_version`) raise their ids inside errors.py.

**Dead-check / wiring audit**: every calc/cascade/validation helper is called from a request path (only `sort_key` appeared "uncalled" — it's passed by reference at 13 sort sites); every guard field (`status` fields, `failure_count`, `ltb_pool_remaining`, `active_clearance_count`, `audited_by`, `created_by`, `flagged_by_report_id`, `paid_out_cents`, `qualified_customers`, `provisional/final_amount_cents`, `excluded_order_count`, `submission_count`) has confirmed writer and reader sites.

**Smoke test**: two fresh boots on auto-allocated ports 41431 and 37591, both killed by exact PID afterward. 54 probes passed covering: 401/403/404 envelopes, pagination meta + bad-limit 400, clock echo, jurisdiction/substance uniqueness, disclosure computation + resubmission upsert (200, count=2), bubble-up DRAFT→ACTIVE, converter SoD 403, OCC 412 on both guarded creates, authorization adjacency vs overlap, order pricing (8200/82000), ownership 403, ALLOCATED→SHIPPED stamping, rebate SoD, close-before-period-end 409, marginal-tier accrual math (5740 = 4100+1640), FINALIZED→CLAIMED→PAID with `paid_out_cents`, counterfeit confirm flagging a SHIPPED order by lot match, converter suspension by implication, and the SHIPPED-order exemption from the converter cascade. One initial smoke expectation (provisional ≠ 0) was my driver's error — the ship predated activation, and §3.7 pins provisional to 0 at activation with recompute only on events while ACTIVE; the final-at-close correctly picked up the earlier ship (4100).

**Interpretations chosen (Step 8/9 focus candidates)**:
1. `api_request_timestamp` comes from the logical clock (deterministic), not wall clock.
2. Clock endpoint echoes the payload `current_utc` verbatim rather than normalized.
3. Discontinue's three preconditions (no pinned error id anywhere) → `ERR_INVALID_REQUEST` 400, after the ACTIVE state check.
4. Rebate advance temporal failures (activate at/after period_end; close before period_end) → `ERR_INVALID_STATE` 409.
5. Out-of-range/non-integer pagination params → 400 (PRD names no error).
6. Clearance resubmission resets `decided_by`/`decided_at` to null.
7. A pair whose clearance is terminally REJECTED gets a fresh row (201) — upsert only for CHANGES_REQUESTED/SUSPENDED.
8. Order ownership (tier 3) evaluated only when the caller's own-kind id is present and a string; both-absent → 400 shape, role-inconsistent id → 422 ambiguous.
9. Path-entity 404 precedes ownership/SoD in practice (those checks need the loaded entity).
10. Duplicate-pair checks (component, qualification customer_ref) run after existence/state gates.
11. `rate_pct`/`extra_discount_pct` treated as fractions (0.05 = 5%), consistent with the 0.18/0.12/0.08 constants.
12. Provisional accrual = 0 at activation even with prior in-period ships; recompute only on SHIP/FLAG/UNFLAG while ACTIVE.
13. Counterfeit link 2b fires only on an actual AUTHORIZED→SUSPENDED transition (not on SUSPENDED→REVOKED).
14. Phase-out gate checks successor lineage only (per validation 23); the sweep additionally excludes the successor from the affected set per the calc note.
15. Accrual recompute bumps version/updated_at only when a value actually changes.
16. `audit_score` validated 0–100 inclusive; `samples_passed` >= 0.
17. Breakpoint/tier arrays accept non-decreasing order ("sorted ascending" unpinned on strictness).
18. `bench_date` accepts date-only strings (midnight UTC); capacity groups by UTC calendar day.
19. `reviewer_note` accepted but not persisted (no entity field); `investigator_note` persisted (field exists).
20. Unknown paths return the ERR_NOT_FOUND envelope; no entity seeding anywhere at startup.

Orchestrator verification: all 23 files exist; independent `py_compile` of all 21 .py files passes; constants cross-diff impl vs test_helpers — 16 shared names all equal, zero drift; `review_sla_days` default 30 consistent across scaffold line 93 / impl inline / test constant.

## Step 7: Run Tests and Iterate — 2026-10-01T22:05:00.000Z

All 8 rounds pass cleanly — 82/82 in every round, no flakiness across the union. The results files remain in `workspace/implementation/` per the output contract.

**Summary**

- Iterations run: 1 (single 8-round parallel sweep, all rounds clean on first pass).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `implementation/`: none.

The prior pipeline steps had already converged: all 82 tests in `test_suite/` (test_01 through test_10) passed in all 8 concurrent rounds of `prd-bench-local-run --isolation per-test-server`. Evidence files `workspace/implementation/results.{1..8}.json` are intact and left in place.

Orchestrator verification: independently re-read all 8 results files — each reports passed=82, total=82, failed=0. Mtime audit: newest impl source 21:50, newest test source 21:18, results files 22:04 — sweep ran after all source writes; nothing edited post-sweep. **Step 8 skip condition met** (0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes).

## Step 8: Finalize PRD — SKIPPED — 2026-10-01T22:06:00.000Z

Step 7 exited on the first 8-round sweep with zero deletions and zero fixes in every layer, so `PRD.md` already determined every behavior the implementation exhibits at the tested surface. No PRD_FINALIZED.md produced (per skip condition).

## Step 9: Complete PRD — 2026-10-01T23:00:00.000Z

All edits verified. The task is complete. Here is the summary.

## Summary

**Source vs. output:** `PRD.md` = 348 lines / 64,601 chars; `PRD_COMPLETED.md` = 348 lines / 69,012 chars (+4,411 chars; line count unchanged — all edits are in-paragraph inserts/revisions).

**Counts:** 21 ambiguity-pins, 1 mismatch-revision, **0 impl-fixes** (no file under `implementation/` was touched — verified by mtimes: all impl sources 21:36–21:50, pre-dating this session; the orchestrator does not need to re-run the sweep).

Every one of the 15 generation-time candidate leads was verified against PRD text and impl source. Most were already pinned by the PRD (counterfeit link-2 firing only on actual suspension, phase-out successor sweep exclusion, both-absent/both-present buyer splits, provisional=0 at activation) or resolved as genuine PRD silence now pinned. The single mismatch was a wrong *rationale clause* in §3.8 whose operative rule the impl honors.

**Change list** (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

1. §2.2 — revise — ambiguity — `api_request_timestamp` pinned as stamped from the logical clock, never wall-clock — `envelope.py:24`, `store.py:17-19`
2. §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400; negative `offset` → 400 — `validation.py:127-150`
3. §2.3 — revise — ambiguity — list ordering ties on `created_at` break by creation (insertion) order; filters are exact-match equality — `store.py:113-115`, `validation.py:153-161`
4. §2.4 — revise — ambiguity — clock endpoint accepts any parseable value (date-only → midnight UTC), no monotonicity constraint, echoes the submitted string verbatim — `routes_clock.py:14-24`, `store.py:26-46`
5. §2.7 — insert — ambiguity — global timestamp parsing (date-only → midnight UTC, offsets → UTC, naive → UTC) and serialization (millis + `Z`; absent nullables → JSON null) — `store.py:26-54`, `serialization.py`
6. §2.9 tier 5 — insert — ambiguity — body fields an endpoint does not name are ignored, not rejected — `validation.py:13-112` (no strict-schema rejection anywhere)
7. §2.9 closing — insert — ambiguity — path-identified resources are loaded first, so a missing path id yields `ERR_NOT_FOUND` 404 ahead of ownership/SoD/state/business tiers; order placement ownership stays payload-based at tier 3 — `routes_orders.py:218-219`, `routes_rebates.py:203-206`, etc.
8. §3.1 — insert — ambiguity — duplicate jurisdiction `code` → `ERR_INVALID_REQUEST` 400 — `routes_reference.py:32-34`
9. §3.1 — insert — ambiguity — duplicate substance `cas_number` → `ERR_INVALID_REQUEST` 400 — `routes_reference.py:65-67`
10. §3.2 — revise — ambiguity — discontinue's three preconditions each fail with `ERR_INVALID_REQUEST` 400; pool-quantity is intake-tier, the two date guards run after the state check (non-`ACTIVE` → `ERR_INVALID_STATE` first); deadline == clock admitted — `routes_formulations.py:118-132`
11. §3.2 — revise — ambiguity — resubmission resets `decided_by`/`decided_at` to null; a pair whose clearance is terminally `REJECTED` gets a fresh row (`submission_count` 1, HTTP 201) — `routes_clearances.py:60-86`
12. §3.2 — insert — ambiguity — `reviewer_note` accepted but not persisted (clearance resource carries no such field) — `routes_clearances.py:115`, `serialization.py:72-85`
13. §3.2 — insert — ambiguity — successor creation admits a predecessor in any status (no state gate beyond OCC) — `routes_formulations.py:77-110`
14. §3.4 — insert — ambiguity — `bench_date` is an ISO timestamp (date-only → midnight UTC); bench capacity accounted per UTC calendar day — `routes_cases.py:90`, `calcs.py:211-222`
15. §3.5 — revise — ambiguity — `volume_breakpoints` non-decreasing by `min_qty` (equal consecutive admitted); all percentage fields (`extra_discount_pct`, `rate_pct`) are fractions (0.18 = 18%) — `routes_pricing.py:34-37`, `calcs.py:79-88,198-202`
16. §3.5 — insert — ambiguity — no formulation-status gate at agreement creation (existence only) — `routes_pricing.py:69-78`
17. §3.6 — revise — ambiguity — phase-out sweep flags carry `flagged_by_report_id` null (like manual suspension); a null-report flag never clears through the reporting cascade — `cascades.py:201,129-140`
18. §3.7 — revise — ambiguity — `rebate_tiers` non-empty, non-decreasing by `threshold_qty` (equal consecutive admitted), `rate_pct` a fraction — `routes_rebates.py:35-52`
19. §3.7 — revise — ambiguity — rebate advance temporal failures pinned: activation at/after `period_end` → `ERR_INVALID_STATE` 409; close before `period_end` → `ERR_INVALID_STATE` 409 — `routes_rebates.py:143-145,161-163`
20. §3.7 — revise — ambiguity — accrual chronological ties beyond `created_at` break by creation order — `calcs.py:124`
21. §3.7 — insert — ambiguity — recomputation targets only `PROVISIONAL` accruals (finalized figures frozen); a recompute changing neither value leaves the accrual untouched (no version bump) — `cascades.py:52-59`
22. §3.8 — insert+revise — ambiguity (validation pins) + **mismatch** (rationale clause) — missing/empty `successor_formulation_id` → `ERR_PHASEOUT_SUCCESSOR_REQUIRED` 409, unknown id → `ERR_NOT_FOUND` 404, gate examines lineage only (successor's own composition not screened); replaced the false "since the advance gate required it to be free of the trigger" rationale with "excluded from the affected set by id, regardless of its composition" (the operative exclusion rule was and remains honored by impl) — `routes_phaseout.py:92-112`, `cascades.py:161-169`
23. §3.8 — revise — ambiguity — duplicate `customer_ref` rejected with `ERR_INVALID_REQUEST` regardless of `samples_passed`; the sub-3-samples no-op applies only to non-duplicates — `routes_phaseout.py:161-169`

**Impl files edited:** none.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD.md (not an interrupted no-op); char counts match the claim exactly (64,601 → 69,012, +4,411); all impl source mtimes ≤21:50 (pre-sweep, untouched by Step 9); all 8 results.*.json still present from the clean Step 7 sweep; spot-checks against impl source confirm edit 19 (rebate activation requires now < period_end else ERR_INVALID_STATE; close requires now >= period_end — matches PRD_COMPLETED §3.7) and edit 22 (cascades.py excludes successor purely by id — matches the revised §3.8 wording).
