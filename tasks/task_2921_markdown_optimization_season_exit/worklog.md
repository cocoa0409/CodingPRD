# Worklog — task_2921_markdown_optimization_season_exit

## Step 1: Create task directory — 2026-09-05T16:56:02.505Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2921_markdown_optimization_season_exit` and its `workspace/` subdirectory. Index 2921 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed.

## Step 2: Generate scaffold — 2026-09-05T18:36:20.172941113Z

All three scaffold artifacts for task 2921 are complete and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2921_markdown_optimization_season_exit/`
- `SCAFFOLD.yaml` — 2996 lines, §1.0–§1.7 only (verified: neither `scaffold_difficulty_design` nor `scaffold_corner_design` key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2543 lines, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5380 lines, single top-level key `scaffold_corner_design`

Nothing else in the task dir was touched (`workspace/` and `worklog.md` untouched, timestamps unchanged).

## Counts

§1.0–§1.7: 14 entities, 12 state machines, 2 concurrency rules, 9 calculations, 36 validations (fully ordered priority chain 1–36), 67 endpoints, 58 errors, 5 roles, `api_prefix: "/"`. Complexity profile: primary `pricing_engine`, secondary `quota_allocation`, layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency]`, topology `flat`, machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`.

§1.8: 24 instances across all 9 Difficulty Rules (2/3/3/2/3/3/3/2/3 — every rule ≥2 with differentiated mechanics).

§1.9: 73 instances = 58 real recipes + 15 `excluded_because:` stubs, over all nine claim-guide sections — entities 12, state_machines 13, calculations 11, validations 17, endpoints 6, errors 4, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. All four declared complexity layers and the `immediate` consistency model have their own instances.

## Verification

- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (67 endpoints, 14 entities, 24 + 58 instances, 1472 calls scanned)
- Error triggerability audit: **0 of 58** catalog error ids unreferenced.
- Name uniqueness across both design files: 0 duplicates (97 names).
- Placeholder closure: 0 instances with an unresolved `${var}`.
- `tail` on each file shows a complete final structure; scenario key holds the verbatim scenario text with the "harder than expert level" directive line excluded (avoids the known leak into PRD.md).

## Design adjudications

- **Lint FK reverse-reachability** forced five extra read endpoints: `GET /sales-weeks`, `GET /sales-weeks/{sales_week_id}`, `GET /markdown-steps`, `GET /exit-reviews`, `GET /exit-reviews/{exit_review_id}`.
- **Priority 8 / `ERR_INVALID_STATE` generalized** to also cover apply-before-effective-date and roll-back-with-a-RECOGNIZED-claim, so those corners have a declared home.
- **`price_relative_pct` precision instance dropped** — no such field exists on Item; replaced with the `sell_through_pct` 42.83 / `weeks_of_supply` 5.34 half-up rounding instance.
- **SoD is deliberately two different comparisons** under one error id: plan approve compares user ids, agreement accept compares `last_offer_by_role`. The rbac instance asserts both, which is the sharpest falsifier for that rule.
- **StoreManager ownership is scope-conditional**: `ERR_STORE_NOT_OWNED` only for STORE-scope executions (which carry `store_id`); ZONE-scope signage is postable by any store manager — asserted with the same manager both refused and accepted.
- **Rate-threshold corner set one unit below** (599 committed vs the 600 trigger = 60% of `exit_units_target` 1000) so the full apply cascade runs while the auto EXIT_WINDOW hop is provably skipped; the 600 case lives in §1.8's `transitive_cascade` instance, referenced by the stub.
- Every chain posts and verifies signage before the clock advances to the effective date, and respects priority 20 (lead-time), 24 (7-day spacing on `(price_zone_id, item_id)`), 28 (aggregate units ≤ on_hand 343) and SoD (`md-1 ≠ pa-1`) so no positive control fails for an incidental reason.

## Step 3: Copy shared files — 2026-09-05T18:36:24.999832180Z

Copied `INSTRUCTION.md` from the project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T18:50:52.292609560Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 441 lines, 103,968 bytes. Built in 10 sequential `cat`/heredoc appends (no single giant Write), so no 64k truncation. Ends at a real boundary: the completed §5 error table, last row `| `ERR_INSUFFICIENT_AVAILABLE_UNITS` | 409 |`. No other file in the task directory was created, modified or deleted; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

**Section list**
- `# Markdown Optimization & Season Exit API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-identical, concatenated from `skills/prd-bench-doc-generator/section-2.2-response-structure.md`); 2.3 Pagination; 2.4 Resource Identity, Versioning and Audit Timestamps; 2.5 The Logical Clock; 2.6 Stale-Version Guards on Supersede-Style Creates; 2.7 Rejection Precedence (all 36 validation priorities enumerated); 2.8 Cents, Percentages and Pinned Rounding Orders; 2.9 Cascades, Counters and Compensating Reversals
- `## 3. Business Logic & Workflows` — 3.1 Season, Price-Zone and Store Foundations; 3.2 Item Intake, Protected Periods and Weekly Sales History; 3.3 Lifecycle Classification and the Eligibility Gates; 3.4 Elasticity Estimation and Certification; 3.5 Plan Authoring, the Depth Ladder, Review and Approval; 3.6 Zone Execution, Signage Compliance and the Apply Cascade; 3.7 Clearance Space Allocation and the Exit-Window Trigger; 3.8 Vendor Allowance Negotiation and Funding Recognition; 3.9 Residual Disposition, the Exit Scorecard and Season Close
- `## 4. Endpoint Definitions` — intro paragraph + 4-column table, 67 rows
- `## 5. Error Code Catalogue` — intro paragraph + 2-column table, 58 rows

**Coverage**
- Endpoints: **67/67** present as `| METHOD | \`path\` |` rows in §4 (0 missing).
- Errors: **58/58** error ids present (0 missing).

**Hard Contract reports (all PASS)**
1. Field-Name Coverage — PASS. `entities[].fields[].name`: 122 required / 122 present. Endpoint `input` identifiers (request-body + query params, `?` stripped): 73 required / 73 present. `path_params`: 14/14. All state-machine state names: 0 missing.
2. Rule Coverage — PASS. All 36 validations appear with their priority ordering in §2.7 and their behavioural home in §3; both `concurrency_rules` (OCC on `Item.version` and `Season.version`) in §2.4/§2.6; all 12 state machines including the two dual-dimension entities (`Item` lifecycle/pricing, `ZoneExecution` execution/signage) and the four cyclic machines; all 9 calculations with pinned rounding orders (§2.8); the five-hop apply cascade, five-hop allowance-cap exhaustion cascade, clearance waterfall ordering, `EXIT_WINDOW` auto-trigger, `PRELIMINARY`/`FINAL` scorecard variants and all three conserved invariants (§2.9, §3.6–§3.9); every `applies_to` scope and both sibling-branch symmetries (apply/roll-back, recognize/reverse) written out.
3. §3 Path Purity — PASS. 304 unique backticked tokens in §3; 0 violations (no `/`-leading token, no bare HTTP method, no method+path combo). Paths appear only in §2.6 and §4.

**Adjudications of scaffold internal inconsistencies** (7)
1. Pagination `limit` default 10 / min 1 / max 100 taken from `response_envelope.pagination_defaults`, overriding a §1.5 comment saying "defaults to 50".
2. Verify-signage restricted to `MerchandiseDirector` per §1.5/§1.7, despite the §1.2 precondition text also naming `StoreManager` for ZONE/STORE scope.
3. Certify-elasticity authorized to `PricingAnalyst` and `MerchandiseDirector` per §1.5, despite §1.2 naming only `PricingAnalyst`.
4. Plan supersession written as the §1.2 superset {`DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`} rather than the endpoint description's narrower "DRAFT or APPROVED".
5. Reopen-plan ladder clearing tied to the endpoint's optional `clear_ladder` flag (endpoint contract wins over the unconditional prose).
6. `AUTO` elasticity resolution written from the §1.3 `own_history_ok` predicate rather than the looser endpoint side-effect wording.
7. Two cross-entity coherence checks with no dedicated error code (`Item.category` must equal `Season.category`; `SalesWeek.week_ending_date` must exceed `Item.first_receipt_date`) assigned `ERR_VALIDATION` (400).

**Orchestrator verification:** independently confirmed PRD.md is 441 lines, has all 5 top-level sections, ends at the completed §5 error table (not mid-sentence), and contains no leak of the difficulty directive.

## Step 6: Generate implementation — 2026-09-05T19:30:57.440155446Z

All modules are complete and the implementation is verified end to end.

## Modules (23 files, 3,849 lines)

`/home/ubuntu/github/CodingPRD/tasks/task_2921_markdown_optimization_season_exit/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded launcher (`if ! python3 -c "import flask"` then `exec python3 app.py`) |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 54 | app factory, 9 blueprints, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 81 | `ApiError` + all 58 catalogue IDs → HTTP status |
| `common.py` | 183 | uuid, `req_` + 20 uppercase alnum request ids, monotonic instants, date/week arithmetic, `Decimal` ROUND_HALF_UP helpers |
| `db.py` | 98 | `Database` (RLock, logical clock default `2026-08-01T00:00:00Z`, 14 collections), `new_row`/`touch` |
| `response.py` | 136 | `meta`/`response_type`/`data` envelope, pagination (`limit` 10/1/100, `offset` 0), filters |
| `validation.py` | 145 | strict typed payload extractors → `ERR_VALIDATION` |
| `serializers.py` | 156 | explicit per-entity field tuples |
| `middleware.py` | 79 | `X-User-ID`/`X-User-Role`, 5 roles, `endpoint()` decorator (lock → auth → RBAC) |
| `services/lookup.py` | 112 | FK resolution → 12 not-found codes; season-status gates |
| `services/calc.py` | 194 | all 9 calculations + every pinned constant |
| `services/lifecycle.py` | 438 | relationship helpers, 6-rule classification, counter recomputation, apply/exit cascades |
| `services/review.py` | 119 | PRELIMINARY/FINAL scorecard |
| `routes/registry.py` | 238 | seasons, transitions + close sweep, zones, stores |
| `routes/items.py` | 230 | items, sales weeks, elasticity estimate + certify |
| `routes/plans.py` | 276 | plans, ladder rungs, submit/request-revision/reopen/approve |
| `routes/executions.py` | 311 | schedule, post/verify signage, apply, roll-back |
| `routes/clearance.py` | 147 | waterfall allocation, release |
| `routes/vendor.py` | 246 | agreements, counter/accept, claims, recognize/reverse |
| `routes/disposition.py` | 154 | create/approve/settle/cancel |
| `routes/reviews.py` | 58 | exit reviews, `/_clock/set_current_utc` |
| `routes/reads.py` | 394 | all 33 GET endpoints |

**Endpoints: 67 registered rules = 33 GET + 34 writes**, exactly matching PRD §4.

## Notable interpretation decisions
- PRD wins over SCAFFOLD: pagination default `limit` 10 (not the scaffold's 50); `verify-signage` is MerchandiseDirector-only for all scopes; plan supersession spans DRAFT/SUBMITTED/REVISION_REQUESTED/APPROVED; counter needs `round_index < 4` while reopen needs `revision_round <= 3`.
- `created_at`/`updated_at` use a monotonic wall clock; only the six explicitly-named stamps (`generated_at`, `applied_at`, `released_at`, …) read the logical clock, keeping `created_at` tie-breaks strictly ordered.
- Rule 8 precedes rule 9, so a transition on a CLOSED season reports `ERR_INVALID_STATE`; `ERR_SEASON_CLOSED` guards every other write with a governing season.
- Clearance allocation fully simulates release + cap + waterfall before mutating, so `ERR_CLEARANCE_SPACE_EXCEEDED` writes nothing.
- `permanent_markdown_reserve_cents` / `promo_discount_cents` are recomputed from APPLIED executions, which is what makes the three conservation invariants hold across rollback and later sales weeks.
- `RESERVED → COMMITTED` is implemented as a general consequence of the item's stage reaching CLEARANCE/EXIT_PENDING (PRD line 266), not only inside apply's hop 4; a re-entrancy guard prevents the exit-window trigger from recursing.
- Exit-window auto-trigger compares `committed_clearance_units` against 60% of `exit_units_target` (PRD line 268), not the space budget.
- `sales_week_id`/`exit_review_id` 404s reuse the parent entity's not-found code, since the catalogue defines none.

## Smoke test — passed
Booted via `bash start.sh` on random high ports, driven by `/tmp/task_2921_impl_scratch/smoke2.py` (~60 assertions), then each server killed by its own captured PID; no `pkill` was ever used and all pre-existing `python3 app.py` processes from other pipelines were left untouched.

Full lifecycle exercised and verified: season → CHAIN zone (default `signage_lead_days` 10) → 2 stores → item (`protected_until_date` 2026-07-13 from APPAREL+42d) → 4 sales weeks (`price_relative_pct` 90.00) → ACTIVE → AUTO elasticity resolving OWN_HISTORY with the coefficient clamped to −0.2000 → plan (`recommended_depth_pct` 14.66) → 2 rungs (4000 / 3250 cents, windows tiled half-open) → submit → approve → schedule → post/verify signage → apply (per-unit 1000, line 50000, item PERM_MARKED + CLEARANCE, plan EXECUTING) → clearance waterfall (200 then 50 units, ranks 1-2) → agreement PROPOSED → counter → accept → claim → recognize (15000 = 30% of 50000, remaining cap 385000) → roll-back blocked by the RECOGNIZED claim → reverse → roll-back restoring retail 5000 / reserve 0 / stage AGING → clock advance → automatic ACTIVE→EXIT_WINDOW via the commitment trigger → disposition JOBBER (16560 = 900×20×92%) → approve → settle (on-hand 72→52) → FINAL review (gross margin 95560) → CLOSED with the sweep releasing both reservations and restoring both stores to full bay capacity → post-close write refused `ERR_SEASON_CLOSED`.

Also confirmed: auth/RBAC/SoD statuses (401/403/403), OCC 412 on both `expected_item_version` and `expected_season_version`, the 422 temporal-vs-structural rung precedence, pagination validation, all 14 flat list endpoints plus nested collections, and a fresh boot returning `total_count = 0` for every collection (no seeding, no on-disk persistence — the only `json`/`open` references in the tree are envelope serialisation and a docstring).

## Step 5: Generate unit tests — 2026-09-05T20:19:37.871002215Z

Stage 1 + Stage 2 generation for task 2921 is complete. Final state:

**Output location (verified)** — `test_helpers/` and `test_suite/` sit at the task root `/home/ubuntu/github/CodingPRD/tasks/task_2921_markdown_optimization_season_exit/`; neither exists under `workspace/`. `workspace/implementation/` was never read, written or listed, and `worklog.md` was not touched. `__pycache__` dirs from `py_compile` removed.

**test_helpers/ (Stage 1, 3134 lines)**
`__init__.py` 152, `api_client.py` 481, `api_errors.py` 152, `assertions.py` 490, `constants.py` 175, `factories.py` 420, `fixtures.py` 902, `test_users.py` 128, `types.py` 234.

**test_suite/ (Stage 2, 6382 lines, 191 tests)**
`conftest.py` 78; queue A: `test_01_dual_variant_calculations.py` 197, `test_02_combinatorial_formulas.py` 225, `test_03_non_linear_state_machines.py` 250, `test_04_transitive_cascades.py` 204, `test_05_priority_conflicts.py` 202, `test_06_boundary_precision.py` 303, `test_07_cross_entity_state_dependency.py` 223, `test_08_resource_temporal_overlap.py` 253, `test_09_compensating_invariants.py` 324; queue B: `test_10_entity_registry.py` 510, `test_11_state_machines.py` 573, `test_12_calculations.py` 657, `test_13_validation_gates.py` 653, `test_14_validation_limits.py` 554, `test_15_endpoint_behaviour.py` 338, `test_16_error_identity.py` 259, `test_17_authorization.py` 298, `test_18_concurrency_and_consistency.py` 281.

**Coverage audit (machine-checked against both design YAMLs)**
- Queue A (§1.8): 24/24 instances covered, 82 tests, every instance >=2 tests. Per rule: dual_variant_calc 2->6, combinatorial_formula 3->9, non_linear_state_machine 3->10, transitive_cascade 2->10, priority_pair_validation_conflict 3->7, boundary_precision_check 3->10, cross_entity_state_dependency 3->9, resource_temporal_overlap 2->8, compensating_invariant 3->13.
- Queue B (§1.9): 73 instances = 58 live + 15 `excluded_because` stubs. All 58 live covered, 109 tests, no stub touched. Per section (live->tests): entities 12->12, state_machines 7->15, calculations 8->17, validations 14->31, endpoints 5->10, errors 4->8, rbac 4->8, cross_cutting_complexity_layers 3->6, consistency_model 1->2.
- Tags: 191 `Design:` lines, 0 untagged, 0 dual-tagged, 0 pointing at a non-existent instance.
- Citations: every test carries >=1 whole-sentence verbatim PRD quote; gate reports 0 bad citations.
- `python3 -m py_compile` clean on all files; `pyflakes` clean on all of `test_suite/` (only the intentional re-export warnings in `test_helpers/__init__.py`).

**Instances skipped: none.** Every live instance survived the PRD-first filter. Where a design recipe was internally inconsistent with the PRD I re-authored the *world*, never the assertion:
- validations #3: the design's fifth rung (11-day cadence) would have reported `ERR_CADENCE_TOO_TIGHT` (priority 18) instead of `ERR_MAX_LADDER_STEPS` (22); ladder re-dated to 10-12/10-26/11-09/11-23 + 12-07 so the cap genuinely fires.
- validations #6: a ZONE-scope call on the CHAIN zone at 2026-10-19 trips `ERR_SIGNAGE_LEAD_VIOLATION` (20) before `ERR_ZONE_SCOPE_MISMATCH` (25); the rung moved to 2026-11-16.
- HTTP statuses always taken from the PRD error table where the design disagreed: `ERR_PLAN_NOT_APPROVED` 409 (design said 422), `ERR_SEGREGATION_OF_DUTIES` 403 (design said 409), `ERR_EMPTY_LADDER` / revision / negotiation ceilings 409.
- cross_cutting #1: the design's fifth sales week (20 units) lifts sell-through to 46.17 %, so the item stops being a slow seller and rule 6 of §3.3 reclassifies it `CORE`; the recomputed `recommended_depth_pct` is therefore 10.28 ((5.00 + 0 + 2.75) x 1.3267), not the AGING-based figure.

**Orchestrator verification:** confirmed `test_helpers/` and `test_suite/` are at the task root (not under `workspace/`), 19 files in `test_suite/`, 191 `def test_` functions.

## Step 7: Run tests and iterate — 2026-09-05T20:57:15.254748481Z

Clean exit. All 8 parallel rounds pass 191/191.

## Summary

**Iterations run: 2.** Iteration 1 had 30 failures, identical in all 8 rounds (fully deterministic — no flakiness, no load/reaping artifacts). Iteration 2 was green.

**Tests deleted: none.** Every failing test's rule was verbatim in `PRD.md` and uniquely derivable, so all 30 were coverage-legitimate.

### Fixes applied to `test_helpers/`
- **`fixtures.py` — `exit_window_scenario`** (fixed 10 failures, the whole `AttributeError: execution` cluster). It passed an *allocated* scenario straight into `applied_execution_scenario`, whose `sc = sc or verified_execution_scenario(...)` short-circuit then skipped the entire schedule→post→verify chain, so `sc["execution"]` was never created. Now spells the chain out (`scheduled_ → verified_ → applied_`), matching the idiom every other call site in `test_suite/` already used. This one line was the upstream cause of all failures in `TestApplyCascadeCommitsAndOpensExitWindow` and `TestRollBackRestoresExposureAndReservations`.

### Fixes applied to `test_suite/`
- **`test_05`, `test_06`, `test_07`, `test_08` — 10 `ApiErrorId.ERR_*` call sites** (fixed 10 failures). Pure symbol bug: enum members are `SEASON_CLOSED`, not `ERR_SEASON_CLOSED` (the `ERR_` prefix is the *value*). The majority of the suite passes plain strings; these 10 minority sites raised `AttributeError` before reaching the server. Values are identical, so no assertion changed.
- **9 sites (`test_02`, `test_03`, `test_04`, `test_11`, `test_14`, `test_15`, `test_16`, `test_18`x2) — plan status `EXECUTING` → `COMPLETED`** (fixed 8 failures). PRD §3.5: *"The plan then moves `EXECUTING → COMPLETED` once every rung that has not been superseded has reached `EXECUTED`."* All these scenarios are single-rung, and PRD §3.6 hop one moves that rung `SCHEDULED → EXECUTED`, so the plan necessarily lands on `COMPLETED` in the same request. Four of the tests *themselves* assert the rung is `EXECUTED` alongside plan `EXECUTING`, which PRD forbids — self-evidencing mis-translation. The docstrings cited §3.6's "moves `APPROVED → EXECUTING` on its first applied execution", which is a real transition the plan passes *through*, not where it stops.
- **`test_09` — `test_the_plan_loses_the_line_but_keeps_its_executing_status`**: relaxed the plan-status assertion to `in ("EXECUTING", "COMPLETED")`. PRD §3.6 enumerates exactly what roll-back undoes and plan status is not in the list, so whether a `COMPLETED` plan falls back to `EXECUTING` (derived-state reading) or latches (one-way-transition reading) is **not uniquely derivable** — STEP 1c partial-coverage handling. The PRD-covered assertions (`gross`/`net` = 0, rung back to `SCHEDULED`) are untouched.
- **`test_14` — `test_four_incoherent_payloads_share_one_error`** (fixed 1 failure). `salvage_order_payload(..., 300, unit_recovery_cents=None)` and the donation equivalent passed the money field both positionally and as a keyword → `TypeError` before any request. PRD §3.9 wants the field *"omit[ted]"*, so the payload is now built and the key deleted, which is genuine absence rather than JSON null.

### Fixes applied to `implementation/`
- **`routes/executions.py` — `create_zone_execution`** (fixed 1 failure): `price_cents_applied` opened as `None`. PRD §3.6 groups it with the fields that open at zero — *"leaves `per_unit_markdown_cents`, `line_markdown_cents` and `price_cents_applied` at 0 and `applied_at`, `posted_at`, `posted_by_user_id` and `verified_by_user_id` null"*. Now `0`.
- **`services/lifecycle.py` — `PLAN_TERMINAL`** (fixed 1 failure, newly surfaced once the fixture bug stopped masking it): was `("COMPLETED", "SUPERSEDED")`, which made `reservations_of_item` return nothing for a `COMPLETED` plan, so roll-back silently skipped the `COMMITTED → RESERVED` flip-back. PRD qualifies only the *forward* direction with "the item's non-terminal plans"; the reverse is *"it reverts that plan's `COMMITTED` reservations back to `RESERVED`"* with no qualifier. PRD never declares `COMPLETED` terminal for a plan — §3.4 still counts it in `projected_exit_units` and §3.5 says *"Both `EXECUTING` and `COMPLETED` are claimable"*. Narrowed to `("SUPERSEDED",)`; that is inert in the forward direction because §3.5 has already moved a superseded plan's reservations to `RELEASED`.

Note the two implementation bugs were causally linked to the `COMPLETED` interpretation: once the plan correctly completes on a single-rung apply, the `PLAN_TERMINAL` filter silently disabled a PRD-required compensating side effect. No PRD-required check was weakened, no test skipped or xfailed, no endpoint or field added without a verbatim PRD sentence, and storage remains in-memory only.

### Final sweep evidence
`workspace/implementation/results.{1..8}.json` — **191/191 passed, 0 failed, 0 errors** in every one of the 8 parallel rounds.

`worklog.md` and `workspace/PRD.md` were not modified. Scratch dir `/tmp/task_2921_step7_scratch` and stray `__pycache__` removed; `test_suite/` and `test_helpers/` remain at the task root.

**Orchestrator verification:** independently re-read all 8 `results.$i.json` (all written at the same instant, 20:42:03Z) and confirmed `passed=191 / total=191, failed=0, errors=0` in every round. No live task_2921 runner or sweep process remains.

## Step 8: Finalize PRD — 2026-09-05T21:06:36.462065177Z

Verification complete. `PRD.md` untouched; only `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 441 lines / 103,968 bytes
- `PRD_FINALIZED.md`: 441 lines / 104,765 bytes (0.0% line delta — all three edits are inline; +797 bytes / +0.77%)
- `tail` confirms the file still ends at the completed §5 table with `| ERR_INSUFFICIENT_AVAILABLE_UNITS | 409 |`.

## Changes (3 edits, all traced to step_7_diff items)

- **§3.3 (transition reading, forward reservation side effect)** — revise — defined the previously undefined qualifier "the item's non-terminal plans": a plan counts as non-terminal unless its status is `SUPERSEDED`, so an `EXECUTING` or `COMPLETED` plan is still in scope. Traces to the `implementation/` fix `PLAN_TERMINAL = ("SUPERSEDED",)` — `services/lifecycle.py:16`, consumed at `services/lifecycle.py:96-100`.
- **§3.3 (reverse `CLEARANCE → AGING` side effect)** — revise — stated the flip-back reads the same non-terminal plan set, so a `COMPLETED` plan's `COMMITTED` reservations do revert. Same impl fix — `services/lifecycle.py:398-404` via `reservations_of_item`.
- **§3.6 (apply cascade closing sentence)** — insert — pinned that the same apply request carries the plan on from `EXECUTING` to `COMPLETED` when every non-superseded rung has reached `EXECUTED`, which a single-rung ladder does on the first apply. Traces to the 9 `test_suite/` sites Step 7 corrected from `EXECUTING` to `COMPLETED` — `routes/executions.py:258-261` + `services/lifecycle.py:312-327`.
- **§3.6 (roll-back paragraph)** — insert — pinned that roll-back does not touch the plan's own `status`; a plan at `EXECUTING` or `COMPLETED` stays there even with no `APPLIED` execution left. Traces to the test_09 relaxation Step 7 made for a genuinely underdetermined rule — `routes/executions.py:272-314` (no plan-status write).

## Per-edit pre-edit search log

**Edit 1+2 (plan terminality for reservation commit/revert)**
- (a) Subject: which plan statuses gate the `RESERVED <-> COMMITTED` reservation side effects, and what "terminal plan" means.
- (b) Enumerated: `grep -rn "PLAN_TERMINAL|reservations_of_item|SUPERSEDED|COMPLETED"` across `services/` and `routes/`. Read `services/lifecycle.py` in full — `PLAN_TERMINAL` (16), `reservations_of_item` (96-100), `_stage_side_effects` both directions (388-404), `recompute_season` projected-units filter (268, counts `APPROVED/EXECUTING/COMPLETED`), `maybe_complete_plan` (312-327). Read `routes/plans.py:40-107` (supersession uses the separate `PLAN_SUPERSEDABLE` set and releases the prior plan's reservations, so `SUPERSEDED` plans hold no live reservation), `routes/plans.py:240-258` (reopen only supersedes `PLANNED` rungs), `routes/clearance.py:36,93,139` (release paths, plan-scoped, unaffected), `routes/vendor.py:115` (`EXECUTING`/`COMPLETED` claimable), `routes/reads.py:39` (plan status enum).
- (c) Adjustment: I did *not* rewrite §3.6 hop four ("every clearance reservation of this plan") to be item-scoped, and I deliberately worded the reverse direction as "reading the same non-terminal plan set" rather than "that plan only" or "all the item's plans". `_stage_side_effects` is item-scoped over all non-`SUPERSEDED` plans, which can differ from "that plan" only in the rare two-live-plans-per-item case (reachable when an `EXECUTING`/`COMPLETED` plan's sole applied execution was rolled back). Under-determined wording avoids a false universal in either direction.

**Edit 3 (`EXECUTING -> COMPLETED` inside the apply request)**
- (a) Subject: the plan status an apply request lands on, and when the completion check runs.
- (b) Enumerated: every `maybe_complete_plan` callsite — `routes/executions.py:261` (apply, after `plan["status"]="EXECUTING"` at 258-259 and `recompute_plan`) and `routes/disposition.py:134-135` (settle, over `plans_of_item`); the guard itself at `services/lifecycle.py:312-327` (requires `EXECUTING`, requires a non-empty live-rung set, or `markdown_state == "SETTLED"`); `live_steps_of_plan` (62); hop one's rung write at `routes/executions.py:238-240`. Also confirmed the apply preconditions (`routes/executions.py:213`, `units_in_scope >= 1`) make the `SETTLED` branch unreachable during an apply, so the rung-based condition is the only one that can fire there.
- (c) Adjustment: conditioned the sentence on "every rung of the plan that has not been superseded has reached `EXECUTED`" and attributed the general rule to §3.5 rather than asserting that any apply completes a plan — a multi-rung ladder correctly stays `EXECUTING`.

**Edit 4 (roll-back leaves plan status alone)**
- (a) Subject: whether a roll-back can move a plan's `status` backwards.
- (b) Enumerated: `grep -rn 'plan\["status"\] ='` — the only plan-status writes in the whole tree are `routes/plans.py:86` (`-> SUPERSEDED`, guarded by `PLAN_SUPERSEDABLE`, so unreachable from `EXECUTING`/`COMPLETED`), `plans.py:213/230/251/273`, `routes/executions.py:259` (`APPROVED -> EXECUTING`) and `services/lifecycle.py:321` (`EXECUTING -> COMPLETED`). Read `roll_back_execution` end to end (`routes/executions.py:272-314`): it writes execution, item, step, then `refresh_item` + `recompute_plan`, neither of which touches `status`, and it never calls `maybe_complete_plan`. Traced the cascade `refresh_item -> _stage_side_effects -> recompute_season -> maybe_trigger_exit_window -> reclassify_season_items` to confirm no plan-status write hides in it.
- (c) Adjustment: scoped the claim to roll-back rather than writing the tempting general "plan status only ever moves forward" — `plans.py:251` moves `REVISION_REQUESTED -> DRAFT`, which would have made the broader wording a new mismatch.

Items in the step_7_diff that I deliberately did **not** patch: the `fixtures.py` scenario-chain fix, the 10 `ApiErrorId.ERR_*` symbol sites, and the `salvage_order_payload` duplicate-argument `TypeError` are pure test-artifact bugs with no behavioral content; and the `price_cents_applied` impl fix aligned the code to a sentence PRD.md already states verbatim in §3.6, so that prose is kept unchanged.

## Step 9: Complete PRD — 2026-09-05T22:08:04.248653268Z

Run as **four sequential module-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than a single subagent. Rationale (orchestrator decision, recorded per the autonomy directive): the implementation is 23 files / 3,849 lines and a single-pass full scan reliably under-scans a tree this size — the known failure mode is a subagent that emits a `PRD_COMPLETED.md` byte-identical to its input, which would mean the scan never actually ran. Pass 1 owned the `cp`; passes 2-4 were explicitly forbidden from re-copying so they could not clobber earlier edits. Every pass was told to use surgical `Edit` calls and never a whole-file `Write` (at 104-132KB a full rewrite hits the 64k output cap and truncates silently).

Partition: pass 1 = `app.py`, `common.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `serializers.py`, `validation.py`, `services/lookup.py`, `routes/registry.py|items.py|reads.py`. Pass 2 = `services/calc.py`, `services/lifecycle.py`, `routes/plans.py`, `routes/executions.py`. Pass 3 = `services/review.py`, `routes/clearance.py|vendor.py|disposition.py|reviews.py`. Pass 4 = a targeted reconciliation of one cross-pass inconsistency (below).

### Totals
- Source `PRD_FINALIZED.md`: 441 lines / 104,765 chars → `PRD_COMPLETED.md`: 442 lines / 132,461 chars (**+1 line, +27,696 chars / +26.4%**). The single added line is one new `§5` error-table row (`ERR_NOT_FOUND` 404); every other change is an in-paragraph insert or revision. Section-header count unchanged at 26 — no new sections.
- **73 changes total: 55 ambiguity-pins, 18 mismatch-revisions.** Pass 1: 22 (18 pins / 4 mismatches). Pass 2: 27 (21 / 6). Pass 3: 22 (16 / 6). Pass 4: 2 (0 / 2).

### Pass 1 — core infrastructure, registry, items, reads (22 changes)
- §2.1 — revise — ambiguity — identity headers judged literally with no trimming (whitespace-only clears 401 then fails 403); role matched case-sensitively; `X-User-ID` otherwise unconstrained — `middleware.py:32,41`
- §2.2 — revise/insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9`; `api_request_timestamp` from the real clock not the logical clock; multi-row create returns 201 + `response_type` `array` with no pagination in `meta`; pagination `meta` only on paginated list reads; error envelope covers 5xx and `response_type` is `error` for every non-2xx — `common.py:25-27`, `response.py:16-20,31-37,44-50`, `app.py:41-44`
- §2.3 — insert — ambiguity — integer query params must be an optionally-signed digit run (`limit=`, `abc`, `1.5`, `+5` all 400); `offset` unbounded, past-`total_count` offset is an empty page with `has_more` false; default `created_at` ordering is exactly insertion order; only enum/date filters validated, identifier filters are exact case-sensitive equality with no existence check (unresolvable id ⇒ empty page, not 404); undeclared query params ignored; nested sales-week list also accepts `week_ending_date`, nested estimates accept `status`/`confidence` — `response.py:82-136`, `common.py:38-58`, `reads.py:52-58,194,222-225`
- §2.4 — revise/insert — ambiguity + **mismatch** — `id` is canonical lowercase hyphenated UUIDv4, malformed identifier is 404 never `ERR_VALIDATION`; `created_at`/`updated_at` from a strictly increasing ms counter; body instants parsed leniently (optional seconds/fraction/zone, lowercase `t`/`z`, space separator, offsets normalised to UTC, fraction truncated to ms); **`sales_week_id` reports `ERR_ITEM_NOT_FOUND` and `exit_review_id` reports `ERR_SEASON_NOT_FOUND`** (14 path ids but only 12 codes); unknown route ⇒ `ERR_NOT_FOUND` 404, wrong method on a known path ⇒ `ERR_VALIDATION` 400, trailing slash insignificant; projections fixed not sparse — `common.py:20-22,66-95`, `db.py:51-54`, `services/lookup.py:11,20`, `app.py:16,28-38`, `serializers.py:99-100`
- §2.5 — insert — ambiguity — whole-week division truncates towards zero, so −13 days is −1 week not −2 — `common.py:128-132`
- §2.7 rule 3 — insert — ambiguity — absent/empty body reads as `{}`; non-object JSON is 400; explicit `null` treated as omitted; no type coercion; every string field has an implicit min length of 1 — `middleware.py:48-61`, `validation.py:13-145`
- §2.7 rule 9 — revise — **mismatch** — the season-transition endpoint is governed by rule 8, so moving a `CLOSED` season yields `ERR_INVALID_STATE` not `ERR_SEASON_CLOSED` — `registry.py:89-92`, `services/lookup.py:92-96`
- §2.8 — insert — ambiguity — all cents/percentages/elasticity travel as bare JSON numbers (strings rejected); stated precision is rounding precision not textual width — `common.py:165-172`, `validation.py:75-86`
- §2.9 — insert — ambiguity — nested reads validate pagination/filters ahead of the outer identifier; childless parent is an empty page; reads never gated on parent status — `reads.py:89-99`
- §3.1 — insert/revise — ambiguity + **mismatch** — `sell_through_target_pct` stored rounded half-up to 2dp and calendar checks precede `code` uniqueness; `zone_code` 1–64 chars, `region_code` non-empty-or-null, **a supplied `parent_zone_id` resolves before the zone-type coherence and uniqueness rules so an unresolvable value reports `ERR_ZONE_NOT_FOUND` even on a `CHAIN` zone**; a store `PATCH` naming neither field still recomputes and bumps `version` by 1, `available_clearance_units` is unclamped and may go negative, revision not season-gated — `registry.py:45-70,149-176,222-238`, `services/lifecycle.py:247-255`
- §3.2 — insert — **mismatch** — registration immediately runs §3.3 classification, so a created item may be persisted and returned in `CORE`/`AGING`/`CLEARANCE` rather than `NEW_ARRIVAL`, while `version` stays 1 and `updated_at == created_at`; category-equality check precedes the CLOSED gate and `sku` uniqueness — `items.py:36-45,74`, `services/lifecycle.py:380`
- §3.4 — insert — ambiguity — the stored estimate echoes the requested `method` verbatim (reads `AUTO` when omitted) alongside `resolved_method` — `items.py:187-188`
- §4 — revise/insert — **mismatch** + ambiguity — `/seasons` "newest first" contradicted `created_at ASC` (now `created_at ASC, code ASC`); `/exit-reviews` `created_at` ASC tie-break under `generated_at`; `/markdown-steps` sorts by `step_index` across the whole filtered set with `created_at` tie-break so rungs of different plans interleave — `reads.py:80,120,291-292`
- §5 — insert — ambiguity — added `| ERR_NOT_FOUND | 404 |` — `errors.py:73`

### Pass 2 — calculations, lifecycle, plans, executions (27 changes)
- §2.5 — insert — ambiguity — a clock set that flips reservations to `COMMITTED` can carry the season `ACTIVE → EXIT_WINDOW` in the same request and re-reclassify; items swept in `created_at` order, then each season's counters; an unchanged row is not written — `lifecycle.py:333-349,427-437`
- §3.1 — insert/revise — ambiguity + **mismatch** — counters restated from rows not by delta, cascade-driven recomputation bumps season `version` only on a real change while allocation/release always bump; **"each transition increments `version` by 1" was wrong** — it is +1 for the status write plus one per item whose reclassification shifts the clearance counters, and close is ordered sweep → reclassify → recompute so a closed season reports 0/0 with `projected_exit_units` intact — `lifecycle.py:258-281`, `registry.py:110-116`
- §3.3 — insert — ambiguity — a no-op reclassification writes nothing, a real one costs exactly one `version` increment however many fields move; only a move into `AGING` out of `CLEARANCE`/`EXIT_PENDING` flips reservations back, while `CORE`, `NEW_ARRIVAL` (clock rewind) and `DISPOSED` leave them `COMMITTED` — `lifecycle.py:359-404`
- §3.4 — insert — ambiguity — a zero or positive raw slope is clamped to −0.2000, not reported as-is — `calc.py:118-120`
- §3.5 — insert — ambiguity + **mismatch** — body FKs resolve season → item → estimate and the `exit_date_target` overshoot is `ERR_VALIDATION` reported ahead of the stale-version guard and season gate; supersession leaves the prior plan's executions alone (a `SCHEDULED` one can never apply yet still occupies the on-hand pool, store window and zone rhythm); `recommended_depth_pct` frozen at creation; **the rung price is computed from the depth as submitted while the stored `depth_pct` is rounded to 2dp** (32.455 prices off 32.455, reports 32.46); rewriting the earlier rung's `window_end_date_exclusive` increments that rung's `version`; "the previous rung" means the last non-`SUPERSEDED` rung so a cleared ladder constrains nothing; `revision_reason` bounded 1..1024 — `plans.py:36-49,69,84-99,117,124,136,160,170,177-179,223`
- §3.6 — insert/revise — ambiguity + **mismatch** — execution body FKs resolve plan → rung → zone → store; the named rung's status is never checked (a `SUPERSEDED`/`EXECUTED` rung is accepted) and only a `PLANNED` rung is advanced; `posted_at` from the logical clock; **hop four commits reservations of every non-terminal plan of the item, not just the executed plan**; the plan is written twice when one apply carries it to `COMPLETED` (`version` +2) and the item exactly once; promo accrual is week-granular; the two unspecified hop-two combinations move the pricing dimension nowhere (`PROMOTIONAL` at ≥50%, `PERMANENT` at ≥50% from `FULL_PRICE`/`PROMO_ACTIVE`); **`SETTLED` fires whenever on-hand reaches zero from any cause** while `DISPOSED` additionally needs `units_disposed_total > 0`; `rollback_reason` bounded 1..1024; `EXIT_PRICED`/`SETTLED` survive a roll-back even when the ticket is restored; **roll-back flips back reservations of every non-terminal plan of the item**; **for apply only the `SCHEDULED` requirement sits at ladder rule 8** — the four dependent preconditions run after the season gate, so a `CLOSED` season wins — `executions.py:39-42,143-145,170,201-219,245-261,275,298-300`, `lifecycle.py:175-176,194-226,370-404`
- §3.7 — insert/revise — ambiguity — the `RESERVED → COMMITTED` flip is driven by the stage *change*, so a reservation allocated against an item already in `CLEARANCE`/`EXIT_PENDING` stays `RESERVED`; `released_at` comes from the logical clock on every route into `RELEASED` — `lifecycle.py:383-397`, `plans.py:96`, `clearance.py:94,140`, `registry.py:135`

### Pass 3 — review service, clearance, vendor, disposition, reviews (22 changes)
- §2.7 rule 13 — revise — **mismatch** — dropped the `season_id` limb from claim scope; scope is `vendor_code` + `item_category_scope` only — `vendor.py:119-122`
- §3.7 — insert/revise — ambiguity + **mismatch** — the named plan need not belong to the addressed season (nothing compares the two `season_id`s); **the supersede release is settled in the arithmetic first but committed to stored rows only after both refusals clear**, so a cap breach or all-or-nothing failure writes nothing and leaves prior reservations live; candidate filter *and* ordering both read post-release availability and `store_number` ascending is a string comparison so `S10` precedes `S9`; the per-store take is bounded by post-release availability; each touched store is restated exactly once and obeys the change-only rule; response is the created rows in `allocation_rank` order; `release_reason` bounded at 1024; release is not exit-window gated (any status but `CLOSED`) and rule 8 outranks rule 9 so a re-release under a closed season reports `ERR_INVALID_STATE` — `clearance.py:28-30,41-96,66-75,83,100-137`
- §3.8 — insert/revise — ambiguity + **mismatch** — opening share stored rounded half-up to 2dp and creation gated only on the season not being `CLOSED`; counter `share_pct` normalised to 2dp on the way in; counter/accept consult the agreement's own season with state check before season gate before round ceiling; acceptance's transition check is role-blind so the wrong party gets `ERR_SEGREGATION_OF_DUTIES` never `ERR_INVALID_STATE`; **same `season_id` drop** — the only season consulted is the plan's; filing never inspects the agreement's status (the `AGREED` requirement bites at recognition only); hop five is arithmetically inert and writes nothing so sibling plans keep their `version` while the recognised claim's own plan is always written once; `reversal_reason` required 1–1024 — `vendor.py:29-36,60-99,119-122,144-158,177,203-215,223,234`
- §3.9 — insert/revise — ambiguity + **mismatch** — the one-cent floors are 422 channel coherence (rule 33) not 400 shape (rule 3), and `DONATION` may state an explicit 0 while `SALVAGE`/`JOBBER` reject `fmv_cents` on presence alone; **`markdown_state → SETTLED` only out of `PERM_MARKED`/`EXIT_PRICED`** (an item disposed while `FULL_PRICE`/`PROMO_ACTIVE` reaches `DISPOSED` keeping its state) and settlement re-runs §3.5's completion test over the item's plans in `created_at` order; cancellation is the one non-exit-window operation of the four with `cancel_reason` optional up to 1024; **a season with `units_received_total` 0 is reviewable and reports `sell_through_pct` 0.00** rather than being impossible; no plan-status filter on either markdown term, so a `SUPERSEDED` plan's stranded `SCHEDULED` executions count in a preliminary scorecard — `disposition.py:20-49,133-149`, `services/review.py:27-29,98-99`
- §4 — revise — **mismatch** — clearance-allocations row: "the season's open stores" → "the chain's open stores" (stores belong to zones, never seasons) — `clearance.py:66`

### Pass 4 — cross-pass reconciliation (2 changes)
Pass 3 reported one residual defect it declined to fix because the sentence belonged to pass 1's territory: §2.9 still carried the **global** claim that "every row touched by a hop has its `updated_at` refreshed and its `version` incremented", which passes 2 and 3 had contradicted locally with the change-only rule. Since Step 9's mandate is zero residual mismatch, the orchestrator spawned a fourth, narrowly-scoped pass to reconcile it plus any §2 claim of the same shape.
- §2.9 — revise — **mismatch** — replaced the global claim with the change-only rule: a hop is a write only when it actually changes something (one `version` increment however many fields move); a hop reproducing every value it held writes nothing; that is the default for every merely-cascade-reached row (unmoved item, sibling plan, store landing back on its committed total, season whose three counters match); the exception is the row the request is itself about, written unconditionally and bumping by exactly 1. Closes with a pointer to §3.1/§3.3/§3.7/§3.8 rather than restating them — `db.py:73,90`, `services/lifecycle.py:258-281,359-385`, `clearance.py:121,146`, `vendor.py:203-215`, `registry.py:222-238`
- §2.6 — revise — **mismatch** — the enumeration of why an item's `version` may have moved omitted two real causes: disposition **approval** also force-refreshes the item, and a clock advance or season transition bumps it when the reclassification actually moves a value — `disposition.py:105`, `items.py:113`, `services/lifecycle.py:359-385,416-436`

§2 universal claims pass 4 checked and found **TRUE** (left verbatim, recorded so the file shows they were verified rather than skipped): §2.4 L88 no two rows share a `created_at` (`common.py:38-44`, lock-guarded strictly increasing counter); §2.4 L90 `version` starts at 1 and increases by exactly 1 on every mutation (`db.py:63-78` — per-mutation, so the change-only rule does not falsify it; confirmed no single-row double-bump on the direct-target path); §2.5 L98 clock-sweep ordering and no-write-if-unchanged (`services/lifecycle.py:426-437`); §2.6 L106 only two writes accept a version field (`plans.py:34`, `clearance.py:25`); §2.9 L161 first sentence on same-request counter recomputation (`services/lifecycle.py:306-309,396-413`, `vendor.py:190-215`); §2.9 L163 both conservation invariants (`vendor.py:125-132`, `services/lifecycle.py:249-256`).

### Consciously not pinned
Recognising/reversing against a `FUNDED` or `EXPIRED` agreement (already implied by §3.8's terminality plus rule 8 precedence); `allocate_clearance`'s `recompute_season(force=True)` reaching the exit-window trigger (unreachable as a *new* trigger — fresh rows are `RESERVED`, so `committed_clearance_units` never grows from an allocation); message-text ordering inside the channel-coherence check (same error code either way); the skip of a `SCHEDULED` execution with a missing step or item row (unreachable under FK integrity). Incidental finding with no doc impact: `services/lifecycle.py:356` `_sweeping` is set by both sweep helpers but never read — dead flag, not a behaviour the PRD needs to describe.

**Orchestrator verification:** `PRD_COMPLETED.md` is 442 lines / 132,461 chars, is NOT byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran), still has exactly 26 headers (no new sections), and still ends at the completed §5 error table with `| ERR_INSUFFICIENT_AVAILABLE_UNITS | 409 |`. All 8 sweep rounds remain at 191/191. `worklog.md` exists only at the task root — no strays under `workspace/`.
