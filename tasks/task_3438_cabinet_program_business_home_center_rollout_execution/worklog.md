# Worklog — task_3438_cabinet_program_business_home_center_rollout_execution

## Step 1: Create task directory — 2026-10-02T02:53:00.000Z

Task directory was pre-allocated by the invoker at `./tasks/task_3438_cabinet_program_business_home_center_rollout_execution/` with `workspace/` inside; verified existence, computed no new index, created no other task directory. Scenario difficulty instruction: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 2: Generate scaffold — 2026-10-02T03:45:00.000Z

All checks pass. Scaffold generation is complete and verified.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3438_cabinet_program_business_home_center_rollout_execution/`):
- `SCAFFOLD.yaml` — 1391 lines (§1.0–§1.7 only; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1063 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1449 lines (single top key `scaffold_corner_design`)

**Counts**: 40 endpoints, 11 entities, 11 state machines (+1 OCC concurrency rule), 7 calculations, 9 ordered validation priorities, 32 error codes, 8 roles. Difficulty design: 19 instances (9 rules; combinatorial_formula has 3 covering modes a/b/c). Corner design: 44 instances (41 active + 3 `excluded_because` stubs) across all 9 taxonomy sections.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (40 endpoints, 11 entities, 19 §1.8 + 41 §1.9 instances, 623 calls scanned, 0 violations.)

**api_prefix**: `/cabinet` (flat topology, all business endpoints prefixed). **Logical clock**: `POST /_clock/set_current_utc` — deliberately UNPREFIXED (outside api_prefix), default `2026-09-01T00:00:00Z` (= ISO week 2026-W36) stated in its description.

**Domain check**: 110/284/361 `/cabinet/` references per file; all 11 entity names present; foreign-domain scan empty; 63 unique instance names; no forbidden concurrency vocabulary.

**Key difficulty mechanics**: quoted-vs-invoiced pricing across line supersede (pinned literals 525240 vs 577800, computed by code); per-line-round-then-sum pinning (6143 vs 6144 trap); tier keyed on pre-discount gross (475000); promised-vs-capacity-aware delivery weeks; credit hold at strict `>` boundary; deltaE ≤ 2.0 inclusive color match; designer windows (half-open + 30-min cross-store buffer); slot aggregate capacity with expedite 10% overbook; disposition unit conservation; supersede→sunset→reprice→exposure→hold depth-4 cascade; segregation of duties on claims.

**Interpretations chosen where the scenario was open** (density over volume, to hold the ≤40-endpoint line): Plant and Store are not entities — `plant_code` enum on ProductionSlot, `store_codes` array on Account. Product families nest inside `ProgramLine.families[]`; order lines nest inside `Order.lines[]` (claims reference `order_id` + `line_index`). Program transition IS a superseding line creation (OCC on `Program.version`), with display resets auto-created per store and disposition initialized from `old_line_disposition_qty`; the program auto-returns to ACTIVE when all sunsetting lines retire. Retail orders exist only via design-job conversion; dealer/builder order directly. Shipments auto-create at MFG_COMPLETE; claims require DELIVERED + 14-day inclusive window. Deadlines: display resets +45d, disposition +90d (DESTROY exempt), design revisions capped at 3, delivery attempts at 3 then auto-RETURNED.

Orchestrator verification (post-hand-back): all three YAMLs parse via yaml.safe_load; SCAFFOLD.yaml top keys = scenario/domain_name/api_prefix/complexity_profile/response_envelope/entities/state_machines/concurrency_rules/calculations/validations/endpoints/errors; endpoints list length = 40; api_prefix = /cabinet; `/_clock/set_current_utc` present and unprefixed (line 973).

## Step 3: Copy shared files — 2026-10-02T03:46:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T04:10:00.000Z

All verifications pass. The PRD is complete and shipped.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3438_cabinet_program_business_home_center_rollout_execution/workspace/PRD.md` — 272 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2.1 User and Role-Based Access Control · §2.2 API Response Structure (verbatim) · §2.3 Pagination · §2.4 The Logical Clock and the ISO Week Calendar · §2.5 Common Resource Properties and Mutation Semantics · §2.6 Monetary Precision and Rounding Discipline · §2.7 Optimistic Concurrency Control on Program Lineage · §2.8 Credit Exposure and the Hold Boundary · §2.9 Validation Order and Automatic Reconciliation
- §3.1 Channel Partners and Program Onboarding · §3.2 The Retail Design Service · §3.3 Order Placement and Quoted Pricing · §3.4 Plant Capacity and Production Scheduling · §3.5 Delivery, Damage Claims, and Replacement Logistics · §3.6 Cancellations, Invoicing, and the Payment Dimension · §3.7 Program Transition: Supersede, Display Resets, and Disposition
- §4 Endpoint Definitions (all 40 endpoints, 4-column table) · §5 Error Code Catalogue (all 32 errors, 2-column table)

**Named constants pinned with concrete values:** logical clock default `2026-09-01T00:00:00Z` via unprefixed `POST /_clock/set_current_utc`; credit-hold boundary (strictly greater than `credit_limit_cents`, equality passes); display-reset deadline 45 days and disposition deadline 90 days from transition start; design-job revision cap 3; shipment attempt cap 3 with auto-`RETURNED`; 14-day claim window (inclusive); deltaE tolerance 2.0 (inclusive, boundary passes, full floating point); expedite overbook floor of one-tenth of capacity (10 percent); strict-variant slip window 4 weeks; EXTENDED lead-time +2 weeks; tier thresholds 500,000 cents ($5,000) at 5 percent and 2,000,000 cents ($20,000) at 8 percent keyed on pre-discount gross; channel multipliers 1.00/0.95/0.90; `program_discount_pct` range 0 to 0.5; settlement cap 1.20 (120 percent of list), early-full age 7 days, late factor 0.8; 30-minute different-store designer travel buffer; pagination limit default 10 / min 1 / max 100, offset default 0.

**Scaffold shorthand expanded to prose:** all pseudocode formulas were translated operator-free — the tiered `order_pricing` formula as a pinned rounding-sequence narrative (channel unit price rounded half-up, tier selection on pre-discount gross, two per-line rounding steps before quantity multiplication, sum after per-line rounding); `credit_exposure` as a contribution-case enumeration with strict/lenient boundary language; `capacity_slot_selection` strict vs expedite windows in calendar prose with week→plant→`created_at` ranking ("never by `id`"); `color_match_delta_e` as "square root of the sum of the squared differences" of the CIELAB coordinates; `damage_settlement` as a lesser-of-two-figures cap plus age-tier narrative; the half-open measurement-window rule as same-store adjacency allowed vs different-store 30-minute gap; the 9-stage validation priority ladder stated explicitly in §2.9 with all 32 error IDs assigned to stages.

**Hard Contract reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs/outputs + array sub-fields: 88 required, 88 present, 0 missing
- error IDs in prose: 32 required, 32 present, 0 missing
- enum/state values: 59 required, 59 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority: 9 stages checked, 9 expressed as an explicit ordered ladder, 0 missing
- concurrency_rules[] OCC: 1 checked, 1 expressed (line create + expected_program_version + ERR_STALE_VERSION/412, no race framing), 0 missing
- state_machines[].transitions: 52 checked, 52 fully expressed (preconditions + error IDs + side effects), 0 missing
- calculations[]: 7 checked, 7 fully expressed (order_pricing, delivery_week_estimation, credit_exposure, capacity_slot_selection, color_match_delta_e, damage_settlement, disposition_reconciliation), 0 missing
- validations[] conditions: 32 error IDs matchable to triggers in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all multi-entity cascades enumerated (supersede 6-effect chain, shipment→order cascades, claim→replacement creation, slot release/auto-lock, batch auto-retire, line auto-retire→program completion), 0 missing
- entities[].fields[] structured content: defaults/initials/nullability reconstructible, 0 missing
- sibling-branch symmetry: backward revisions, cancel states, deny/complete/waive pairs, strict/expedite and quoted/invoiced variants at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 508
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks: §2.2 block is byte-identical to `section-2.2-response-structure.md`; §4 table matches the scaffold's 40 (method, path) pairs exactly; §5 table matches the catalog's 32 error IDs with the catalog's HTTP statuses (including the 409 for `ERR_DESIGNER_WINDOW_OVERLAP`, `ERR_SLOT_EXISTS`, `ERR_ACCOUNT_HAS_OPEN_ORDERS`, which the validation table groups differently); zero fuzzy words and zero operator-syntax tokens in prose.

Orchestrator verification (post-hand-back): PRD.md = 272 lines; `POST /_clock/set_current_utc` unprefixed in §2.4 prose (line 80) and §4 table (line 196); constants present: 2026-09-01T00:00:00Z ×2, 2.0 ×2, 14 days ×2 + 14-day ×1, 90 days, 45 days, 500,000, 2,000,000, 120 percent, 10 percent, 1.20, 0.95, 0.90, 0.8.

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T04:35:00.000Z

Stage 1 is complete. The `test_helpers/` package for task_3438 is generated, compile-clean, and import-verified.

**File list (all under `.../test_helpers/`):** `__init__.py` 37 · `constants.py` 87 · `types.py` 359 (8-role enum, 13 status/value enums, 11 entity TypedDicts) · `api_errors.py` 83 (32 ApiErrorId members + HTTP map) · `api_client.py` 244 (40 endpoint methods + `canonical_instant` normalizer) · `factories.py` 316 · `test_users.py` 149 · `assertions.py` 310 · `fixtures.py` 576 (5-tier composite fixtures) — 2161 lines total.

**Constants cross-check (each greps ≥1× in PRD.md):** CLOCK_DEFAULT 2026-09-01T00:00:00Z (§2.4); TIER1/TIER2_GROSS_CENTS 500,000/2,000,000 pre-discount gross inclusive (§3.3); TIER rates 0.05/0.08 (§3.3); channel multipliers 1.00/0.95/0.90 (§3.3); PROGRAM_DISCOUNT_PCT_MAX 0.5 inclusive (§3.1); COLOR_MATCH_TOLERANCE 2.0 inclusive (§3.5); EXPEDITE_OVERBOOK_PCT 0.10 floor (§3.5); MAX_SLIP_WEEKS 4 (§3.4); EXTENDED_CLASS_EXTRA_WEEKS +2 (§3.3); REVISION_CAP/ATTEMPT_CAP 3/3 (§3.2/§3.5); CLAIM_WINDOW_DAYS 14 inclusive (§3.5); DISPLAY_RESET/DISPOSITION deadlines 45/90 days (§3.7); SETTLEMENT_CAP_MULT 1.20 / EARLY_FULL_DAYS 7 / LATE_FACTOR 0.8 (§3.6); DIFFERENT_STORE_BUFFER_MINUTES 30 (§3.2); pagination default 10/min 1/max 100/offset 0 (§2.3); credit-hold strict `>` documented (§2.8). Error map diffed programmatically vs PRD §5: 32/32 identical, including ERR_DESIGNER_WINDOW_OVERLAP=409 and ERR_STALE_VERSION=412.

**Role/identity scheme (PRD §2.1):** DealerRep entity-backed (X-User-ID = Account id; shared fallback marked non-ownership-only); RetailDesigner opaque-but-recorded, one designer id threaded across a job's lifecycle; ClaimsAdjuster two shared identities + builder for segregation-of-duties (default filer lc-1 LogisticsCoordinator ≠ default decider ca-1); PlatformAdmin/ProgramManager/PlantScheduler/LogisticsCoordinator/FieldServiceRep opaque shared constants + builders; malformed-credential helpers cover the 401 tier.

**Clock handling:** `ApiClient.set_clock` posts to `/_clock/set_current_utc` UNPREFIXED (exactly 1 unprefixed call, 39 `/cabinet`-prefixed = 40). All week/date fixtures derive from CLOCK_DEFAULT via iso_week_of/add_weeks_to_week/add_days — verified to reproduce the design index's landmarks (W36 default, W37/W40 fixture weeks, 2026-10-16 for +45d, 2026-11-30 for +90d). Fixtures build at the default clock and never advance it; tests advance it themselves. `canonical_instant` normalizes timestamp spellings.

**Verification:** compileall COMPILE_OK; full package import IMPORT_OK (no dangling imports); error map 32/32; client method count 40; no-network smoke SMOKE_OK (every factory, calendar helper, header builder, entity assertion, all 34 public fixture functions resolve and execute). No test_suite/ files created — Stage 2 owns that.

Orchestrator verification (post-hand-back): 9 helper files present, 2161 lines; compileall clean; api_client.py line 9 documents the unprefixed clock exception, `set_clock` at line 55; constants TIER1=500_000, TIER2=2_000_000, EXPEDITE_OVERBOOK_PCT=0.10, COLOR_MATCH_TOLERANCE=2.0 confirmed; test_suite/ absent as required.

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T05:15:00.000Z

Stage 2 is complete. 19 files in `test_suite/` (conftest.py + 18 test files), importing only from the frozen `test_helpers/` package and the framework. **79 test functions total.**

Per-file test counts: conftest.py 0 (api fixture) · test_01_difficulty_pricing 6 · test_02_difficulty_damage_settlement 2 · test_03_difficulty_design_job_cycles 4 · test_04_difficulty_payment_dimensions 4 · test_05_difficulty_supersede_cascades 4 · test_06_difficulty_validation_precedence 4 · test_07_difficulty_delivery_scheduling 4 · test_08_difficulty_color_match 2 · test_09_difficulty_cross_entity_gates 4 · test_10_difficulty_compensating_invariants 4 · test_11_corner_entities 6 · test_12_corner_state_machines 7 · test_13_corner_calculations 4 · test_14_corner_validations 12 · test_15_corner_endpoints 2 · test_16_corner_errors 2 · test_17_corner_rbac 5 · test_18_corner_complexity_consistency 3.

**Coverage: queue A 19/19 instances (38 tests, exactly 2 each), 0 skipped. Queue B 41/41 active instances (41 tests), 0 skipped; 3 `excluded_because` stubs not translated (cross-references verified resolving to real queue-A instances).**

Adjudication notes (PRD-first filter applied):
1. Corner/state_machines/order_mfg_complete_auto_creates_planned_shipment — the recipe's literal setup (DEALER account + STORE order to ST-7) is PRD-illegal: §3.1 says store_codes "stays empty for DEALER and BUILDER accounts", so a dealer STORE order always draws ERR_STORE_NOT_SERVICED. Translated the same claim via the PRD-reachable path (retail account [ST-7] → design job → quote → convert with destination STORE/ST-7), preserving every asserted observable (exactly one PLANNED shipment, destination copied).
2. Difficulty/priority_pair/state_precondition_beats_fiscal_gate_on_schedule — kept the priority claim (ERR_INVALID_STATE, order stays CANCELLED) but did not pin the cancelled order's `payment_status`: §2.8's release sentence does not exclude cancelled orders, so two faithful readers diverge. The second test covers the fiscal gate in isolation (ERR_CREDIT_HOLD on a live held order).
3. All money/week literals re-derived against PRD-pinned formulas (525240/577800 across the supersede, 6143 pinned vs 6144 unpinned, 475000 tier-keyed-on-gross, 9500/7600 settlement age tiers, W36+3=W39 promise vs W37→W40 / W38→W41 scheduled) and match the index.

Status-code honesty: every create asserts via `validate_success(resp, 201)`; errors via `validate_error` against the registered HTTP map (412 passed explicitly for OCC). Clock discipline: all fixtures build at the default 2026-09-01T00:00:00Z; later instants set by tests through the unprefixed `POST /_clock/set_current_utc`.

AST audit (subagent-run, verbatim in its report): total 79; tags not in indices 0; queue A uncovered 0/19; queue B uncovered 0/41; stubs translated 0; tag-policy violations 0; every Difficulty tag exactly 2 tests, every Corner tag exactly 1. Verbatim-citation pass: all 153 `PRD §...: "..."` docstring quotes are literal substrings of workspace/PRD.md — 0 failures. pytest --collect-only: 79 tests collected, 0 errors.

Orchestrator verification (post-hand-back): independent `pytest --collect-only` = 79 collected in 0.22s; independent AST walk = 79 tests, all final-docstring-line Design tags; tags-not-in-indices NONE; non-stub instances without test 0 (60/60 covered: 19 difficulty + 41 corner); stubs wrongly translated NONE; duplicate tags only the by-design 2× on Difficulty tags.

## Step 6: Generate implementation — 2026-10-02T05:50:00.000Z

The matched PID was transient and is already gone — no stray servers. Implementation complete.

**Task**: task_3438_cabinet_program_business_home_center_rollout_execution — 40 endpoints, 11 entities, 32 error codes.

**Files (2,429 lines total) in `workspace/implementation/`:** start.sh 10 (exec-launcher, flask-import-guarded install, $PORT/0.0.0.0) · requirements.txt 1 · app.py 69 (Flask entry, unprefixed POST /_clock/set_current_utc, envelope error handlers) · errors.py 53 (ApiError + full §5 catalogue, single definition point) · util.py 88 (ISO-week math, datetime parse, ms timestamps, Decimal round-half-up) · db.py 40 (empty in-memory store; clock defaults 2026-09-01T00:00:00Z) · envelope.py 65 (meta/response_type/data envelope; limit/offset/total_count/has_more pagination 10/1/100) · auth.py 40 (X-User-ID/X-User-Role extraction, role-list enforcement) · services.py 435 (pricing, delivery weeks, credit exposure/holds, strict+expedite capacity, deltaE, settlement, supersede cascade, auto-retire) · routes_accounts.py 102 · routes_programs.py 263 (OCC + supersede, disposition actions) · routes_finishes.py 66 · routes_slots.py 73 · routes_design.py 305 · routes_orders.py 316 · routes_shipments.py 92 · routes_claims.py 314 · routes_resets.py 97.

**Compile/import:** compileall clean; `import app` clean; all 35 URL rules (40 endpoints; 5 paths serve POST+GET) registered; pyflakes clean.

**Gate audit (each check → PRD source):** auth 401 / role-list 403 (§2.1); per-transition role pins (order ACK=ProgramManager, SCHEDULED/IN_PRODUCTION/MFG_COMPLETE=PlantScheduler; replacement SCHEDULED/IN_PRODUCTION/CANCELLED=PlantScheduler, SHIPPED/RECEIVED/REMAKE=LogisticsCoordinator; reset SCHEDULED/COMPLETE=FieldServiceRep, WAIVED=ProgramManager — §4 role column); DealerRep ownership (X-User-ID == account_id), RetailDesigner job ownership, claim intake ownership (§2.1/§3.3/§3.5); segregation of duties on APPROVED/DENIED 403 (§3.5); OCC expected_program_version → 412 only on line create (§2.7); state edges per machine incl. TRANSITIONING blocking activate/line-create 409, quote staleness, cancel-window, shipment-not-delivered (§3.1–3.7 stage 5); family coverage / store serviced / no-current-batch / channel-discipline (stage 6); window shape & 30-min cross-store buffer, delivery-week feasibility, 14-day inclusive claim window, slot-week-past, disposition deadline DESTROY-exempt (stage 7); slot uniqueness 409, revision cap 3, aggregate claim quantity, deltaE ≤ 2.0 inclusive, capacity no-partial-commit, disposition overage, open-orders-on-close 409 (stage 8); credit gate payment_status==UNINVOICED at SCHEDULED → ERR_CREDIT_HOLD 409 (stage 9). No invented gates: revised layout_lines NOT re-checked for family coverage (PRD lists only presence + cap for QUOTED→LAYOUT_READY); auto-retire fires only on disposition/complete/waive events, not at supersede (PRD enumerates those three triggers).

**Error-id two-direction grep:** all 32 catalogue ids have ≥1 raise site; only non-catalogue id is ERR_INTERNAL (defensive 500 handler); 32/32 raised ids in catalogue.

**Constants grep:** all 19 PRD-pinned values verified programmatically: 500000/2000000, 0.05/0.08, 1.00/0.95/0.90, cap 0.5, deltaE 2.0, overbook 10%, slip 4, EXTENDED +2, revision 3, attempt 3, claim 14d, reset 45d, disposition 90d, settlement 1.20, early-full 7d, late 0.8, buffer 30min, pagination 10/1/100. No referenced-but-undefined names.

**Smoke transcripts (dynamic ports, exact PIDs killed via Popen handle):** Port 57397: clock 200 → account 201 → program 201 → line 201 → activate 200 → order 201 → read 200 (quoted=27000 ✓ = 10000×1.00×0.9×3; promised 2026-W40 ✓) → no-auth 401 ERR_UNAUTHENTICATED. Port 55145: OCC stale 412; slot-dup 409 ERR_SLOT_EXISTS; exposure 30000 > limit 25000 → CREDIT_HOLD at ack, schedule blocked 409 ERR_CREDIT_HOLD; schedule W36→deliv W38; batch pinned at IN_PRODUCTION; shipment cascade to DELIVERED order; filer-approve blocked 403 ERR_SEGREGATION_OF_DUTIES; CREDIT settlement 10000 ✓; supersede → TRANSITIONING with deadlines; DESTROY 2 → line RETIRED → program back ACTIVE. Zero 500s in both runs.

Orchestrator verification (post-hand-back): 19 files / 2429 lines; compileall clean; start.sh exec-launches app.py in foreground with flask-import-guarded install; app.py line 69 `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`; app.py line 32 registers unprefixed `/_clock/set_current_utc`.

## Step 7: Test-fix iteration loop — 2026-10-02T06:01:00.000Z

All 8 rounds pass 79/79. The results.*.json artifacts are in place.

**Iterations run:** 2 full 8-round parallel sweeps (initial: 4 tests failing consistently in all 8 rounds; final: clean 79/79 × 8), plus 1 single-round sanity pass between fix batches.

**Tests deleted:** none.

**Fixes applied to `implementation/`:**

1. `workspace/implementation/db.py` — `new_entity()` and `bump()` stamped `created_at`/`updated_at` from wall-clock (`datetime.now`). PRD §1/§2.4 state verbatim that the API reads a single logical clock, "never from wall-clock time," with default reading `2026-09-01T00:00:00Z`; the impl already stamped every PRD-named timestamp (`delivered_at`, `filed_at`, `completed_at`, disposition `created_at`) from `store.clock`, leaving the §2.5 common fields as the sole wall-clock leak. Now both stamp from `store.clock`. (Fixed `test_account_creation_applies_defaults_and_system_fields`.)

2. `workspace/implementation/services.py` — `recompute_credit()` applied a universal hold-sweep: at every recompute with exposure > limit, ALL of the account's UNINVOICED orders flipped to CREDIT_HOLD. PRD §3.4 scopes hold entry to the acknowledged order ("the order's payment_status becomes CREDIT_HOLD"); §2.8's only universal quantifier is the release direction ("every order ... sitting in CREDIT_HOLD flips back to UNINVOICED"). The sweep was an over-guard not stated in PRD — it held sibling orders, which broke the §3.6 dimension-independence scenario. Removed the hold-sweep; kept the verbatim exposure formula and release sweep.

3. `workspace/implementation/routes_orders.py` — ACKNOWLEDGED branch of `transition_order()`: after the recompute, apply the §3.4 evaluation to the acknowledged order only — `open_exposure_cents` strictly greater than `credit_limit_cents` → this order to CREDIT_HOLD, else stays UNINVOICED (equality passes, per §2.8 "an exposure exactly equal to the limit passes without a hold").

**Fixes applied to `test_suite/`** (`test_suite/test_04_difficulty_payment_dimensions.py`):

4. `test_exact_limit_boundary_single_orders`, `test_exposure_equal_to_limit_passes_one_cent_over_holds`, `test_payment_release_unblocks_scheduling` — all three placed every sibling order BEFORE acknowledging any, then asserted boundary arithmetic that only holds if SUBMITTED orders don't contribute to exposure. That contradicts PRD §2.8's verbatim formula ("every order not in CANCELLED contributes its quoted_total_cents while its payment_status is UNINVOICED or CREDIT_HOLD" — a SUBMITTED order is UNINVOICED per §3.3) and contradicts three currently-passing cascade tests that load-bearing-assert SUBMITTED orders DO count (`test_cancel_submitted_order_relieves_held_acknowledged`: o1 holds at its own ack only because SUBMITTED o2's 19000 pushes the total to 104500; supersede tests assert post-reprice totals including still-SUBMITTED orders). The setup ordering was the test bug; each test now acknowledges an order before placing the next, preserving every asserted number (9500/19000, 57000/95000/104500, 95000/104500) and every assertion — only the interleaving changed, making the setups faithful to §2.8.

**Key adjudication:** the design index itself was split (boundary recipes assumed acked-only exposure; cascade recipes assumed all-non-CANCELLED exposure). The suite-consistent, PRD-verbatim resolution: exposure = literal §2.8 formula (SUBMITTED counts), hold entry = §3.4 per-order at acknowledgement only, release = §2.8 universal sweep at any recompute at-or-below limit. All six credit tests (3 failing + 3 passing) plus the full 79-test suite now pass under that single semantics.

Orchestrator verification (post-hand-back): all 8 results.{1..8}.json present, each passed=79/79 failed=0; no implementation .py file is newer than results.1.json (newest impl edit routes_orders.py 05:54:51Z < results 06:00:39Z), so the clean sweep covers the final code.

## Step 8: Finalize PRD — 2026-10-02T06:20:00.000Z

Done. The diff is exactly two inline sentence revisions — no new sections, no other changes.

**Line counts / delta:** PRD.md 272 lines, PRD_FINALIZED.md 272 lines — 0% line-count delta; 2 lines revised inline.

**Changes (one bullet each):**
- §2.5 — revise — `created_at`/`updated_at` now pinned as "stamped from the logical clock of §2.4 rather than wall-clock time" (PRD §1/§2.4 scope "never wall-clock" to deadlines/windows/week-arithmetic, leaving the §2.5 common fields genuinely undetermined; the fixed impl stamps them from `store.clock`) — `implementation/db.py:37-38,44`
- §2.8 — revise — hold entry scoped to the acknowledged order only: "An order moves onto `CREDIT_HOLD` only at its own acknowledgement (§3.4)… No other event moves an order onto `CREDIT_HOLD` — a recompute triggered by creation, cancellation, invoicing, payment, supersede repricing, or unsuspension never adds a hold." (The old universal phrasing licensed the hold-sweep Step 7 removed; the negative list mirrors §2.8's own recompute-trigger list minus acknowledgement) — `implementation/routes_orders.py:183-191`, `implementation/services.py:180-211`

**Per-edit pre-edit search log:**
- Edit 1 — (a) subject: clock source of the §2.5 common timestamp fields. (b) enumerated: `db.py:31-44` (new_entity/bump → `store.clock`); `envelope.py:9` + `util.py:28-29` (`api_request_timestamp` → `now_iso()`, wall-clock); `routes_shipments.py:75` (`delivered_at`), `routes_claims.py:120` (`filed_at`), `routes_resets.py:85` (`completed_at`), `routes_programs.py:258` (disposition `created_at`), `services.py:364-368` (transition fields) — all `store.clock`; `services.py:218` slot ranking and all list sorts read `created_at`. (c) wording kept inside §2.5's existing "Every resource … carries the same four system-managed fields" scope so the envelope's wall-clock `api_request_timestamp` (§2.2) is not swept in; entity-specific timestamps were left as-is (separately pinned or harmlessly under-determined — the new clause is consistent with all of them since they all read `store.clock`).
- Edit 2 — (a) subject: credit-hold entry semantics. (b) enumerated: sole entry site `routes_orders.py:188-191` (acknowledged order only, strict `>`); sole release site `services.py:209-211`; all eight `recompute_credit` callsites (`routes_orders.py:125,183,288,296,323`; `routes_design.py:304`; `services.py:391`; `routes_accounts.py:101`) — every non-acknowledgement callsite is release-only in the fixed impl; scheduling gate `routes_orders.py:196-197` (reads only); §3.4's existing ack-scoped sentence; §3.6 dimension-independence passage. (c) added the explicit negative trigger list ("creation, cancellation, invoicing, payment, supersede repricing, or unsuspension") so the sentence describes every callsite, and cross-referenced §3.4 rather than restating its condition to avoid dual-source drift; release-sweep sentence kept verbatim.

**Per-item zero-edit evidence:**
- Item 3 (boundary strictness aspect) — already pinned verbatim: §2.8 "strictly greater than its `credit_limit_cents`; an exposure exactly equal to the limit passes without a hold" and §3.4 "if including the order pushes the account's `open_exposure_cents` strictly above its `credit_limit_cents`, the order's `payment_status` becomes `CREDIT_HOLD`; otherwise it stays `UNINVOICED`." (Only the sweep-scoping aspect needed Edit 2.)
- Item 4 (test-suite setup fix; no PRD edit) — already pinned verbatim: §2.8 "every order not in `CANCELLED` contributes its `quoted_total_cents` while its `payment_status` is `UNINVOICED` or `CREDIT_HOLD`" plus §3.3 "A newly placed order enters `SUBMITTED` with `payment_status` `UNINVOICED`" — a SUBMITTED order therefore contributes; the bug was test-setup ordering, not PRD ambiguity.

Orchestrator verification (post-hand-back): `diff workspace/PRD.md workspace/PRD_FINALIZED.md` shows exactly the 2 reported line revisions (§2.5 clock-source clause; §2.8 acknowledgement-scoped hold entry with negative trigger list) and nothing else; no implementation .py file is newer than results.1.json — Step 8 touched no code.

## Step 9: Complete PRD — 2026-10-02T06:39:00.000Z

All verification complete. Final state: PRD_COMPLETED.md written, one impl fix applied and swept green.

**Source vs output:** `PRD_FINALIZED.md` (272 lines / 47,285 chars) → `PRD_COMPLETED.md` (272 lines / 49,923 chars; +2,638 chars, 13 paragraphs touched, 0 new sections, 0 deletions).

**Counts:** 14 ambiguity-pins (PRD silent/multi-reading → pinned to impl's behavior), 0 mismatch-revisions, 1 impl fix.

**Impl fix (PRD sound, impl deviated — fixed impl, not the contract):**
- `workspace/implementation/routes_orders.py` — `transition_order` (SCHEDULED branch, lines 194–216) — the fiscal gate (`ERR_CREDIT_HOLD`) was evaluated *before* strict capacity selection; PRD §2.9 pins "(8) constraint checks (`ERR_NO_CAPACITY`…) ; **and finally** (9) the fiscal gate (`ERR_CREDIT_HOLD`)". For an order violating both, PRD answers `ERR_NO_CAPACITY`, impl answered `ERR_CREDIT_HOLD`. Selection is read-only until commit, so the reorder is safe and minimal. Verified: full `prd-bench-local-run --isolation per-test-server` sweep re-run post-fix, 79/79 passed (`/tmp/3438_verify3.json`, 06:38 > edit 06:28). The existing hold test (`test_06…::test_credit_hold_gate_blocks_live_schedule`) still passes because its slot is eligible, so the gate still fires after selection.

**Ambiguity-pins:**
- §2.1 — insert — reads are role-scoped only, never ownership-scoped — `routes_orders.py:15-16` READ_ROLES etc. on all GET endpoints
- §2.3 — insert — equal `created_at` ties keep creation sequence — dict insertion order + stable `sorted` in every `list_*`
- §2.9 — insert — absent required body field → `ERR_INVALID_REQUEST` (not 404); ownership of a path-identified resource evaluates after its existence (`ERR_NOT_FOUND` first), body-decidable ownership (DealerRep `account_id` at order placement) at stage 2 — `routes_orders.py:44-51`, `routes_design.py:251-256`, `routes_claims.py:62-81`
- §3.1 — insert — unrecognized/self-transition/out-of-CLOSED `to_status` → `ERR_INVALID_STATE` — `routes_accounts.py:82-90`
- §3.1 — revise — `effective_start_week` is informational; no validation gate consults it — `routes_programs.py:141-144` (shape-checked only)
- §3.1 — insert — second line create on DRAFT-with-ACTIVE-line → `ERR_INVALID_STATE`; `old_line_disposition_qty` accepted on any create, consumed only by supersede — `routes_programs.py:131-133, 178-194`
- §3.2 — revise — booking against DEALER/BUILDER account → `ERR_CHANNEL_REQUIRES_DESIGN_JOB` — `routes_design.py:116-118`
- §3.4 — insert — scheduling family data (`units`, `base_lead_weeks`, `scheduled_delivery_week` lead) resolves against the order's most-recently-priced line, not necessarily the current ACTIVE line — `services.py:58-63`, `routes_orders.py:195-222`
- §3.4 — revise — `IN_PRODUCTION → MFG_COMPLETE` pinned to `PlantScheduler` — `routes_orders.py:19-24`
- §3.5 — insert — segregation of duties binds only APPROVED/DENIED; `FILED → UNDER_REVIEW` open to the filer — `routes_claims.py:164-167`
- §3.5 — insert — replacement demand = `quantity` × (claimed line's `units`/`quantity`) — `routes_claims.py:273-274`
- §3.6 — revise — settlement cap's "line the order was priced against" = most recent pricing (submit / supersede reprice / lock-broken invoice) — `services.py:330-343`
- §3.7 — insert — `repricing_required` set at reprice, never cleared — `services.py:386` (only writer)
- §4 — insert — undefined path / unsupported method → standard envelope `ERR_NOT_FOUND` (404) — `app.py:53-60`

**Two-direction dead-check evidence:**
- Catalogue → raise sites: all 32 PRD §5 error ids have ≥1 `api_error("ERR_X", …)` site. Two raise sites are defensive-unreachable in practice (`ERR_LINE_NOT_COVERED` in the SCHEDULED branch — order families always resolve against the recorded priced line; `ERR_NO_ACTIVE_LINE` inside `price_items` — shadowed by earlier coverage checks), but both ids have live reachable sites elsewhere (`create_order`, `activate_program`), so no catalogue entry is dead.
- Helpers → callers: every function in `services.py`, `util.py`, `auth.py`, `envelope.py`, `db.py`, `errors.py` has ≥1 call site from a request path. No dead validators.

**Deliberately not pinned** (single-reading already or sub-contract): lock-at-exact-capacity vs overbook crossing (PRD's "reach exactly its capacity" already forces impl's reading), claim-window/disposition/deadline inclusivity (impl matches PRD's strict->/inclusive statements verbatim), shipment RETURNED leaving the order in SHIPPED (PRD names exactly two order movements), raw-string echo of datetime inputs (assertions accept any ISO 8601 form), program↔account linkage on order/booking (no catalogue error exists for it, so the gated reading is unsupported).

Orchestrator verification (post-hand-back): `wc -lc` confirms 272 lines / 47,285 → 49,923 chars (+2,638); diff vs PRD_FINALIZED.md = 26 changed lines across 13 paragraphs, 0 section additions; routes_orders.py mtime 06:28:27Z postdates the Step-7 sweep (06:00:39Z) and the SCHEDULED branch source shows capacity selection before the fiscal gate with the §2.9 stage-ordering comment — the impl fix is real. Because the impl changed after the Step-7 clean sweep, the orchestrator re-ran the full 8-round stability sweep itself against the final code at 06:41–06:43Z: all 8 rounds 79/79, 0 failed, ALL_GREEN; `workspace/implementation/results.{1..8}.json` regenerated against the final code (all ports released, holders → 0).
