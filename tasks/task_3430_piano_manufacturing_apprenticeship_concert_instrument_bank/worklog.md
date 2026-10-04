# Worklog — task_3430_piano_manufacturing_apprenticeship_concert_instrument_bank

## Step 1: Create task directory — 2026-10-02T01:02:00.000Z

Task directory was pre-allocated by the caller; verified `./tasks/task_3430_piano_manufacturing_apprenticeship_concert_instrument_bank/workspace/` exists and is empty. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T01:12:00.000Z

All checks pass. The scaffold package is complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3430_piano_manufacturing_apprenticeship_concert_instrument_bank/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 18 instances (9 rules × 2)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 61 instances (52 active + 9 `excluded_because` stubs)

**Counts**: 10 entities, 40 endpoints (at the ≤40 cap), 27 error codes, 5 roles, 7 state machines, 6 calculation rules, 1 OCC concurrency rule, 743 test-recipe calls lint-scanned.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Additional self-audits passed: all `grounds:` references resolve, zero unbound `${var}` placeholders, no forbidden concurrency vocabulary, instance names unique across both design files.

**Key design decisions**:
- **Profile**: workflow-orchestration + compliance/audit archetypes; flat topology, cyclic machines, segregation-of-duties role model; layers = optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, selector_policy. Dealer/consignment clauses of the scenario were deliberately dropped to stay within the endpoint budget while maximizing coupling density.
- **Named constants** (all pinned): `MOISTURE_READY_PCT 8.0`, `MIN_DRYING_DAYS 240`, `SEASONING_MIN_DAYS 365`, endorsement hours `{RIM_BENDING: 600, SEASONING_CHECK: 300}`, `FAIL_RETAIN_RATIO 0.75`, `MISMATCHED_SUPERVISION_RATIO 0.5` with per-entry round-then-sum pinned, stage rates/planned hours/material costs per model, loan fee `{MIN 55000, MAX 2000000, TECH_BUFFER_DAYS 1}`, `AUTHENTICITY_MIN_PCT 70.0` (`>=` exact-pass), logical clock default `2026-09-01T00:00:00Z`, forward-only.
- **Cyclic machines**: BuildOrder seasoning rework (SEASONING→RIM_BENT via wood-reject cascade only), SkillEndorsement ENDORSED↔REVOKED, RestorationCase QUOTED↔AUTHENTICITY_HOLD, Artist ACTIVE↔SUSPENDED.
- **Difficulty anchors**: dual-variant WIP valuation (BuildOrder) vs performance standing (Artist); combinatorial modes (a) tiered fee with nested clamp, (b) per-entry rounding, (c) pinned 4-step restoration evaluation order; depth-3 loan-return→grade→RESTORATION→case cascade vs depth-2 wood-reject→rework→WIP cascade; priority pairs state-vs-constraint and constraint-vs-temporal; half-open instrument overlap vs 1-day-buffered closed technician overlap; custody and endorsed-hours compensating invariants; SoD rule (assessor ≠ top supervisor).
- **Replay fix applied mid-design**: instrument-loan overlap was unreachable until eligibility admitted `ON_LOAN` chaining — patched into §1.2/§1.4/§1.5 so `ERR_LOAN_WINDOW_CONFLICT` is genuinely triggerable, and the selector ranking rule (grade, then `created_at` ASC, never `id`) was backfilled into the scaffold when the corner index referenced it.

Orchestrator verification: all three files exist (813 / 621 / 1205 lines), parse as YAML with the required top-level keys, and grep confirms on-domain vocabulary (255 hits for piano/instrument/rim/season/apprentice/artist/restoration/wood; api_prefix `/piano-works`).

## Step 3: Copy shared files — 2026-10-02T02:41:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T02:55:00.000Z

The PRD is complete and all audits pass. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3430_piano_manufacturing_apprenticeship_concert_instrument_bank/workspace/PRD.md` — 268 lines, built incrementally in 11 append steps with tail verification after each.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle, `/piano-works` mount named)
- §2 Global Specifications: 2.1 RBAC (5 roles, per-role identity prose — opaque for WorkshopManager/ArtistLiaison, entity-backed for MasterCraftsman/Apprentice/Artist) · 2.2 Response Structure (**byte-identical diff-verified** against the canonical source) · 2.3 Pagination · 2.4 Workshop Logical Clock (startup 2026-09-01T00:00:00Z, forward-only, `ERR_CLOCK_REGRESSION`) · 2.5 Common Resource Properties (BuildStageLog exception: only `id`/`created_at`) · 2.6 Precision & Rounding · 2.7 OCC (`expected_build_order_version` → `ERR_STALE_VERSION` 412) · 2.8 Validation Priority Order (7 tiers, OCC-before-state within tier 4) · 2.9 Path/FK Resolution · 2.10 Two WIP Ledgers
- §3 Business Logic (7 subsections, timeline+concern grouping): 3.1 Timber/Drying · 3.2 Build & WIP valuation · 3.3 Apprenticeship/Endorsement · 3.4 Instrument Bank · 3.5 Artist Standing · 3.6 Tour Loans · 3.7 Restoration/Authenticity
- §4 Endpoint table (40 endpoints, 4 columns) · §5 Error catalogue (27 errors, 2 columns)

**Zero-Silence self-audit (all PASS):**
- Contract 1 field coverage: every `entities[].fields[].name` (62), plus endpoint-only identifiers (`expected_build_order_version`, `condition_grade_observed`, `outcome`, `action`, `venue`, `performed_at`, `authenticity_concern`, `to_iso8601`, `current_utc`, `provisional_wip_cents`, `actual_wip_cents`, `delta_cents`, `hours`, `specialty_match`), query params, and envelope fields — mechanical diff: **0 missing**
- Contract 2 rule coverage: all 38 state transitions with preconditions/side-effects, all 6 calculations with exact constants (8.0%/240d/365d gates, material/rate/planned-hour tables, 0.5 mismatch ratio, 0.75 fail-retain, fee clamp 55,000–2,000,000 with both binding examples, pinned 4-step completion order, per-entry-then-sum pinning with the rejected alternative's worked example), all 25 validations matchable to their error IDs with applies_to scopes, 1 OCC rule fully expressed, sibling branches (4-way review, ENDORSE/FAIL, REVOKE/REOPEN, BANK/SHOWROOM exits) at equal density — **0 missing**
- Contract 3 §3 path purity: 454 backtick tokens scanned, **0** path/method violations
- All 27 error IDs appear in §2/§3 prose; all 49 enum/state literals present; §2.2 verbatim diff confirmed

One gap found and repaired during the audit: the positive precondition that `COMMISSIONED → RIM_BENT` requires a non-null `wood_batch_id` naming an `ALLOCATED` batch was initially implicit — added explicitly to §3.2.

Orchestrator verification: `workspace/PRD.md` exists (268 lines), tail shows the completed error catalogue, 51 `ERR_` mentions.

## Step 5a: Generate test helpers (frozen) — 2026-10-02T03:20:00.000Z

Stage A is complete and frozen. All files parse, the package imports, date arithmetic matches the design-index literals exactly, and no generated comment references scaffold internals.

## Files written

| Path | Lines |
|---|---|
| `test_helpers/__init__.py` | 33 |
| `test_helpers/types.py` | 262 |
| `test_helpers/api_client.py` | 172 |
| `test_helpers/api_errors.py` | 68 |
| `test_helpers/assertions.py` | 192 |
| `test_helpers/factories.py` | 180 |
| `test_helpers/constants.py` | 69 |
| `test_helpers/test_users.py` | 35 |
| `test_helpers/fixtures.py` | 561 |
| `test_suite/conftest.py` | 41 |

No `test_*.py` files generated (stage B owns those).

## Exported surface (names only, grouped by file)

- **types.py** — `UserRole`; enums `WoodSpecies`, `WoodBatchStatus`, `BuildModel`, `BuildOrderStatus`, `BuildStage`, `OperationType`, `EndorsementStatus`, `AssessOutcome`, `ReviewAction`, `InstrumentStatus`, `ConditionGrade`, `ArtistTier`, `ArtistStatus`, `LoanStatus`, `RestorationOrigin`, `RestorationStatus`; TypedDicts `WoodBatch`, `BuildOrder`, `BuildStageLog` (id+created_at only, no updated_at/version per PRD §2.5), `SupervisionEntry`, `Craftsman`, `Apprentice`, `SkillEndorsement`, `Instrument`, `Artist`, `ConcertLoan`, `RestorationCase`.
- **api_client.py** — `ApiClient(GenericApiClient)` with 40 methods covering every PRD §4 endpoint (wood batches ×5, build orders ×6 incl. stage-logs + valuation + advance, people ×4, endorsements ×6, instruments ×3, artists ×4, loans ×5, restorations ×6, `set_clock`); singleton `api_client`.
- **api_errors.py** — `ApiErrorId` (all 27 PRD §5 ids), `HTTP_STATUS_CODES`, registered with `set_error_http_status_map` at import.
- **assertions.py** — `assert_wood_batch`, `assert_build_order`, `assert_build_stage_log` (asserts updated_at/version *absent*), `assert_craftsman`, `assert_apprentice`, `assert_supervision_entry`, `assert_skill_endorsement`, `assert_instrument` (incl. `SERIAL_NUMBER_PATTERN` ^PIN-\d{8}$), `assert_artist` (incl. forward ≥ realized invariant), `assert_concert_loan`, `assert_restoration_case`, `assert_valuation` (incl. provisional ≥ actual and delta identity), `assert_clock_result`.
- **factories.py** — payload factories: `create_wood_batch_payload`, `moisture_reading_payload`, `create_build_order_payload`, `advance_build_payload`, `create_craftsman_payload`, `create_apprentice_payload`, `create_endorsement_payload`, `log_hours_payload` (null-supervisor capable), `assess_payload`, `review_endorsement_payload`, `create_artist_payload`, `performance_payload`, `create_loan_payload`, `confirm_loan_payload` (instrument_id omittable for selector tests), `return_loan_payload`, `create_restoration_payload`, `advance_restoration_payload` (authenticity_concern omittable), `resolve_authenticity_payload`, `complete_restoration_payload`, `set_clock_payload`. None-valued optionals are omitted; `**overrides` allow extra keys for strict-validation tests.
- **test_users.py** — `TEST_USERS` (5 shared entries), `make_master_craftsman_headers`, `make_apprentice_headers`, `make_artist_headers` (entity-backed identity threading).
- **fixtures.py** — clock: `iso_days_after`, `set_clock`, `ensure_clock_at_least` (regression-tolerant, solves multi-build setups), `set_clock_days_after`; wood: `create_wood_batch`, `record_moisture`, `get_wood_batch`, `condition_wood_batch`; people: `create_craftsman`, `create_craftsman_set`, `create_apprentice`; endorsement: `create_endorsement`, `get_endorsement`, `log_supervised_hours`, `assess_endorsement`, `review_endorsement`, `setup_endorsement`, `setup_endorsement_with_entries`, `setup_pending_endorsement`, `setup_endorsed_track` (SoD-safe assessor); build: `STAGE_CHAIN`, `STAGE_TO_OPERATION`, `DEFAULT_STAGE_HOURS`, `get_build_order`, `create_build_order`, `advance_build`, `advance_build_by_master`, `advance_build_by_apprentice`, `setup_commissioned_build`, `setup_build_in_stage` (auto seasoning clock move); instrument: `get_instrument`, `list_instruments`, `find_instrument_for_build`, `bank_intake`, `setup_completed_instrument`, `setup_bank_instrument`; artist: `create_artist`, `get_artist`, `log_performance`, `setup_artist_with_performances`, `review_artist`, `setup_suspended_artist`; loan: `get_concert_loan`, `list_concert_loans`, `create_loan`, `confirm_loan`, `return_loan`, `setup_on_tour_loan`; restoration: `get_restoration`, `list_restorations_for_instrument`, `create_restoration_case`, `advance_restoration_case`, `resolve_authenticity`, `complete_restoration_case`, `setup_rebuilt_case`.
- **__init__.py** — re-exports all framework generics (`validate_success/error/error_is_one_of/paginated`, `get_success_data`, `run_race`, `assert_race_outcome`, `assert_exactly_one_succeeds`, `assert_at_least_one_succeeds`, `assert_version_incremented`, `assert_timestamp_format`, `assert_cost_precision`, `is_valid_uuid`, `is_iso8601_timestamp`, `build_user_headers`, `NON_EXISTENT_UUID`) plus all PRD-specific names.
- **test_suite/conftest.py** — session `api` fixture + 5 role-header fixtures.

## Constants carried (each traced to PRD)

`CLOCK_START_ISO="2026-09-01T00:00:00Z"` §2.4 · `SECONDS_PER_DAY=86400` §2.4 · `PAGE_LIMIT_DEFAULT=10/MIN=1/MAX=100/OFFSET=0` §2.3 · `MOISTURE_READY_PCT=8.0` §3.1 · `MIN_DRYING_DAYS=240` §3.1 · `SEASONING_MIN_DAYS=365` §3.2 · `HOURS_APPLIED_MAX=500` §2.8/§3.2 · `MATERIAL_COST_CENTS={D:4200000,B:3600000,O:3100000,ART_CASE:9000000}` §3.2 · `STAGE_RATE_CENTS={RIM_BENDING:14500,SEASONING_CHECK:9500,ACTION_REGULATION:21000,VOICING:24000}` §3.2 · `PLANNED_HOURS={120,40,40,200,160}` §3.2 · `HOURS_REQUIRED={RIM_BENDING:600,SEASONING_CHECK:300}` §3.3 · `MATCHED/MISMATCHED_SUPERVISION_RATIO=1.0/0.5` §3.3 · `FAIL_RETAIN_RATIO=0.75` §3.3 · `WEEKLY_RATE_CENTS={D:85000,B:72000,O:64000,ART_CASE:150000}` §3.6 · `TIER_FACTOR={STANDARD:1.0,PRIVILEGED:0.8}` §3.6 · `MIN_FEE_CENTS=55000`/`MAX_FEE_CENTS=2000000` §3.6 · `DAYS_PER_WEEK=7` §3.6 · `TECH_BUFFER_DAYS=1` §3.6 · `REVIEW_PERIOD_DAYS=365` §3.5 · `AUTHENTICITY_MIN_PCT=70.0` §3.7. No dead/scaffold-only constants.

## Design-instance needs checklist (verified against both indices)

- Full-build pipeline to any stage incl. COMPLETED → instrument mint (`setup_build_in_stage`, `setup_completed_instrument`): covers all WIP, rework, cascade, boundary, selector, and instrument instances. Verified `iso_days_after` reproduces the design literals 2027-04-29 (day 240), 2028-04-28 (+365), 2028-04-27 (+364).
- Two-build setups (selector ranking, technician buffer): safe — clock targets derive from each batch's own `drying_started_at`, and `ensure_clock_at_least` tolerates an already-ahead clock (equal-value set is PRD-legal).
- Endorsement ladder: IN_TRAINING → per-entry-rounding entries → PENDING_ASSESSMENT → ENDORSED → REVOKED → REOPEN; FAIL scaling; SoD assessor separation (`setup_endorsement_with_entries`, `setup_pending_endorsement`, `setup_endorsed_track`).
- Apprentice advance crediting, supervised/unsupervised/endorsed (`advance_build_by_apprentice`, null-supervisor log payload).
- OCC stale/fresh replay: `advance_build_payload` threads `expected_build_order_version`; fixtures return fresh versioned entities.
- Bank/loan lifecycle: BANK instrument, ACTIVE/SUSPENDED artist, REQUESTED → ON_TOUR → RETURNED, selector-omitted confirm, grade-A/B return vs C/D restoration cascade (`setup_on_tour_loan`, `return_loan`, `list_restorations_for_instrument`).
- Restoration ladder: QUOTED/auto-HOLD → DISASSEMBLED → REBUILT → COMPLETED, resolve-authenticity, waiver variants (`setup_rebuilt_case`, `resolve_authenticity`, `complete_restoration_case`).
- Artist reviews: due/not-due, suspend/met/reinstate, catch-up performances, standing counters (`setup_suspended_artist`, `log_performance`, `review_artist`).
- RBAC/ownership denials: 3 entity-backed header builders + 2 opaque shared constants.
- Envelope/error/one-of/pagination assertions: framework re-exports; error HTTP map registered.
- Clock regression / forward-only: `set_clock` (strict) vs `ensure_clock_at_least` (tolerant) distinction exposed.

Freeze check result: AST parse of all 9 helper files + conftest.py — zero syntax errors; `import test_helpers` succeeds (183 exported names).

Orchestrator verification: all 9 helper files + conftest.py present, AST parse clean.

## Step 5b: Generate test suite — 2026-10-02T03:55:00.000Z

All checks pass. Stage B is complete.

## Summary

**Test files written** (all under `test_suite/`):

| File | Lines | Tests |
|---|---|---|
| test_01_wood_intake.py | 101 | 5 |
| test_02_build_commission.py | 117 | 7 |
| test_03_build_stage_legality.py | 142 | 6 |
| test_04_build_actor_gate.py | 118 | 4 |
| test_05_seasoning_and_rework.py | 173 | 7 |
| test_06_wip_valuation.py | 74 | 3 |
| test_07_completion_and_occ.py | 128 | 4 |
| test_08_endorsement_lifecycle.py | 128 | 6 |
| test_09_endorsement_hours.py | 143 | 6 |
| test_10_rbac_ownership.py | 127 | 6 |
| test_11_artist_standing.py | 168 | 7 |
| test_12_loan_windows_and_fees.py | 117 | 5 |
| test_13_loan_confirm_gates.py | 124 | 5 |
| test_14_loan_overlap_fences.py | 109 | 4 |
| test_15_loan_return_cascade.py | 130 | 6 |
| test_16_restoration.py | 141 | 5 |
| test_17_logical_clock.py | 27 | 1 |

**Total: 87 tests** (36 difficulty + 51 corner), 2067 lines.

**Coverage vs. index** (AST-walked tags vs `yaml.safe_load` of both indices):
- Queue A (difficulty): 18/18 instances, each with exactly 2 tests.
- Queue B (corner): 51/52 non-stub instances covered with ≥1 test; 9 `excluded_because:` stubs correctly untranslated (all cross-references resolve to real difficulty instances).
- Zero untagged, dual-tagged, or dangling tags.

**Deliberately skipped (1):**
- `Corner/entities/create_wood_batch_extra_field_rejected` — fails unique derivability (condition 2): PRD §2.8's shape rule enumerates "required fields present, types valid, enum members valid" and numeric ranges but never states that an unknown/system key in a create body is *rejected* rather than ignored; two faithful PRD-only readers could ship either behavior.

**Adjudication adjustments (derivability-driven, documented in docstrings):**
1. Absolute version literals (e.g. `version == 4`) replaced with captured-version + N assertions — PRD §2.5 pins "increments by one on every mutation" but never an initial value of 1.
2. `artist_review_suspend_met_and_reinstate_branches`: the design's re-armed date literals (2028-09-01, 2028-12-01) contradict strict 365-day arithmetic across the 2028 leap day (2028-08-31, 2028-11-30); both are faithful readings of "365 days", so dates are asserted as the 2-day envelope the two readings share. Statuses and counter reset/retention are asserted exactly. This is a design-index literal bug worth flagging upstream.
3. `build_completed_terminal_lockdown`: ERR_INVALID_STATE vs ERR_BUILD_STAGE_INVALID from COMPLETED is not uniquely derivable; used `validate_error_is_one_of` plus the solid no-mutation invariant (status/version/5 stage logs).
4. `endorsement_revoke_reopen_cycle`: dropped the `endorsed_by_craftsman_id`-after-REOPEN assertion (PRD silent on whether REVOKE clears it); kept the verbatim-covered status/hours-retention claims.
5. Two-instrument setups (selector ranking, technician buffer) shifted loan windows to 2030 — after the second full build cycle the logical clock is at ~2029-12-25, so the design's 2029 windows would violate the PRD's `tour_start >= current clock date` rule.

**Audits:**
- Citation check: all 87 docstrings contain a ≥8-word substring that greps verbatim in PRD.md.
- `python3 -m pytest test_suite/ --collect-only -q` (PYTHONPATH=task dir): **87 tests collected, 0 errors, 0 import failures**.

test_helpers/ and conftest.py were not modified.

Orchestrator verification: independent `pytest --collect-only` run confirms 87 tests collected, 0 errors; 87 `Design:` tags counted across test files (one per test).

## Step 6: Generate implementation — 2026-10-02T04:21:00.000Z

Implementation complete and smoke-tested. Summary below.

## Files written

All under `workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | Foreground launcher, `$PORT`/`0.0.0.0`, `exec`, guarded pip install |
| `requirements.txt` | 1 | flask |
| `app.py` | 62 | App factory, blueprint registration, envelope error handlers (404/405/500) |
| `db.py` | 91 | In-memory store (empty at boot), logical clock (starts exactly 2026-09-01T00:00:00Z), id/serial/timestamp helpers |
| `errors.py` | 47 | `ApiError` + all 27 error ids with HTTP statuses |
| `envelope.py` | 48 | `meta`/`response_type`/`data` envelope, list pagination meta, sort by `created_at` ASC |
| `validate.py` | 111 | Body shape/enum/int/number/timestamp/FK validators, pagination params |
| `auth.py` | 28 | `X-User-ID`/`X-User-Role` auth, entity-backed role resolution, role gates |
| `serialize.py` | 150 | Per-entity serializers (stage logs omit `updated_at`/`version`) |
| `calc.py` | 158 | All 6 calculation rules with pinned constants |
| `routes_wood.py` | 106 | 5 wood-batch endpoints incl. drying gate + rework cascade |
| `routes_builds.py` | 231 | 6 build-order endpoints incl. OCC-guarded advance, WIP, instrument minting |
| `routes_people.py` | 55 | craftsmen + apprentices (4 endpoints) |
| `routes_endorse.py` | 148 | 6 endorsement endpoints incl. SoD, FAIL 0.75 scaling, auto PENDING_ASSESSMENT |
| `routes_instruments.py` | 53 | 3 instrument endpoints |
| `routes_artists.py` | 91 | 4 artist endpoints incl. 4-branch annual review |
| `routes_loans.py` | 203 | 5 loan endpoints incl. selector policy, both scheduling fences, return cascade |
| `routes_restore.py` | 173 | 6 restoration endpoints incl. auto-hold and pinned 4-step completion |
| `routes_clock.py` | 21 | Forward-only logical clock endpoint |

**Endpoints wired:** 40 (39 under `/piano-works` + `POST /_clock/set_current_utc`). **Error catalog:** 27 ids, statuses per PRD §5. Validation priority order 1→7 implemented per §2.8 (OCC evaluated before state-transition checks inside priority 4; per-entry round-half-up-then-sum for both labor cents and training hours; Decimal arithmetic throughout; no entity seeding at boot).

## Interpretations chosen (PRD ambiguities resolved)

1. **`tour_start >= current clock date`** — compared at date granularity (`tour_start.date() >= clock.date()`), per the "clock date" wording (vs. "clock now" used elsewhere).
2. **OCC mismatch direction** — any `expected_build_order_version != current version` → `ERR_STALE_VERSION` (PRD §2.7 "no longer matches"; scaffold says "below").
3. **SEASONING re-allocation with `wood_batch_id` omitted** (post-rework) → `ERR_WOOD_NOT_CONDITIONED` (no conditioned batch named).
4. **Entering RIM_BENT without holding an ALLOCATED batch** → `ERR_INVALID_STATE` (defensive; unreachable in practice since ALLOCATED→REJECTED requires the build to be in SEASONING).
5. **Advance on terminal COMPLETED build** → `ERR_INVALID_STATE`; wrong non-terminal target → `ERR_BUILD_STAGE_INVALID` (matches catalog ordering).
6. **`supervising_craftsman_id: null` on log-hours** allowed only for ENDORSED tracks ("endorsed unsupervised work"); otherwise `ERR_VALIDATION`. Log-hours on a REVOKED track → `ERR_INVALID_STATE`.
7. **Bank intake on non-SHOWROOM instrument** → `ERR_INSTRUMENT_NOT_BANK_ELIGIBLE` (scaffold folds status into the priority-6 eligibility check).
8. **Restoration create against ON_LOAN instrument** → `ERR_INVALID_STATE`; against RESTORATION allowed structurally but blocked by the one-open-case rule. Auto-AUTHENTICITY_HOLD at create bumps the case to version 2 (machine transition on top of creation).
9. **`resolve-authenticity` with `total_parts_value_cents == 0`** → pct null, treated as authentic ("no parts replaced"); failed resolution mutates nothing (atomic rejection). Absent `waiver_accepted` keeps the stored value.
10. **Restoration advance `to_stage`** outside {DISASSEMBLED, REBUILT}: non-enum strings → 400, valid-but-illegal case states → 409 `ERR_INVALID_STATE`.
11. **Pagination** — out-of-range `limit`/`offset` are clamped to [1,100]/[0,∞); non-integer values → `ERR_VALIDATION`. Unknown list-filter values filter literally (empty page, no error).
12. **`meta.api_request_timestamp`** uses wall-clock receipt time; all domain timestamps use the logical clock (§2.4 scopes the ban to recorded domain timestamps).
13. **Integer-typed fields** (cents, quota, `expected_build_order_version`) reject JSON floats and booleans.

## Smoke-test result

Ports used: 59407 → 56869 → 37329 (each dynamically allocated; each server killed by its exact saved PID after use — no broad kill patterns). The first run caught a real bug (advance never assigned `status = to_stage`); fixed in `routes_builds.py` and re-verified from a fresh boot.

Exercised end-to-end on the final boot: clock set → wood batch create → +241 days → moisture reading at exactly 8.0 → CONDITIONED (boundary passes) → 4 craftsmen → build order (MODEL_O, wip 3,100,000) → advance RIM_BENT (wip 4,840,000) → stale-version advance → 412 `ERR_STALE_VERSION` → SEASONING → premature ACTION_REGULATION → 409 `ERR_SEASONING_INCOMPLETE` → +365 days → ACTION_REGULATION → VOICING → COMPLETED (wip 13,640,000, delta 0, serial `PIN-00000001`, batch CONSUMED) → bank-intake → BANK → artist create → loan create → selector confirm (fee 102,400 = 64,000×2 weeks×0.8; instrument ON_LOAN) → standing_forward 2 while ON_TOUR → return grade B → instrument BANK/B. Error spot-checks: 403 `ERR_UNAUTHORIZED_ROLE`, 404 `ERR_NOT_FOUND`, 422 `ERR_LOAN_WINDOW_INVALID`. Every response carried the §2.2 envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields on lists). No pytest or test-suite files were touched.

Orchestrator verification: 20 files present, `python3 -m compileall` clean, start.sh reads `$PORT`, binds via app, runs foreground with `exec`.

## Step 7: Test-and-iterate loop — 2026-10-02T04:42:00.000Z

Clean sweep: all 8 rounds pass 87/87 with 0 failures. The `results.*.json` files remain in `workspace/implementation/` per the output contract.

**Summary**

- **Iterations run:** 2 sweeps (initial: 8 rounds × 79/87 with the same 8 deterministic failures; post-fix: 8 rounds × 87/87, zero failures).

- **Tests deleted:** none. Every failing test traced to verbatim PRD prose.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/` (4 files, 2 root causes):**

  1. **Clock-timestamp serialization** — PRD §2.4 states the logical clock's startup value is "exactly `2026-09-01T00:00:00Z`" (no fractional digits) and §2.5 reserves "three fractional digits" for `created_at`/`updated_at` only; the impl had formatted *all* timestamps with `.000Z`.
     - `db.py`: added `fmt_clock()` (`%Y-%m-%dT%H:%M:%SZ`) alongside the existing 3-fractional-digit `fmt_dt()`.
     - `serialize.py`: switched clock-derived fields to `fmt_clock` — `drying_started_at`, `conditioned_at`, `seasoning_started_at`, stage-log `logged_at`, supervision-entry `logged_at`, `next_review_date`. `created_at`/`updated_at` keep `.000Z` per §2.5; user-supplied `tour_start`/`tour_end` untouched.
     - `routes_clock.py`: `current_utc` now echoes via `fmt_clock`.
     - Fixed 5 tests: `test_create_wood_batch_applies_system_defaults`, `test_moisture_exactly_eight_pct_conditions_at_day_240`, `test_review_before_due_date_rejected`, `test_artist_review_suspend_met_and_reinstate_branches`, `test_clock_regression_rejected`.

  2. **Endorsement per-entry rounding granularity** — `calc.py` `recompute_endorsement_hours` used `rhu_1dp` (one decimal) per entry; PRD §3.3's pinned worked example ("two 7-hour mismatched entries credit 4 plus 4 equals 8 under the pinned order, against 7 from rounding their 7.0 sum once") is only satisfiable with whole-hour round-half-up per entry (3.5→4). Changed to `rhu_int(hours * ratio)`.
     - Fixed 3 tests: `test_mismatched_entries_credit_per_entry_rounding` (8 not 7.0), `test_threshold_auto_advances_to_pending_assessment` (600 → auto `PENDING_ASSESSMENT` at equality), `test_assess_fail_scales_hours_per_entry_floor` (444/5/5 → effective 450, logged 454).

Pre-sweep smoke test on a dynamically allocated port verified both fixes end-to-end (server killed by its own saved PID). No PRD-required checks were weakened; no capabilities added beyond PRD prose; storage remains in-memory only.

Orchestrator verification: all 8 `results.*.json` independently re-read — every round `passed 87 / total 87, failed 0`; newest source file (`calc.py` 04:37:36) predates oldest results file (04:41:08), confirming the clean sweep ran after the final implementation write.

## Step 8: Finalize PRD — 2026-10-02T05:05:00.000Z

The file changed (diff exit=1), with exactly 3 lines revised — all traceable to the two Step 7 root causes. Line counts are identical (268/268, 0% delta). Final verification of the edits in context is complete.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 268 lines → 268 lines (0% delta); 3 lines revised in place, no sections added or removed.

**Changes (all trace to `<step_7_diff>`):**

- **§2.4 — insert (one sentence appended to the clock paragraph) — pins whole-second serialization for clock-derived timestamps: `drying_started_at`, `conditioned_at`, `seasoning_started_at`, stage-log and supervision-log `logged_at`, `next_review_date`, and the clock endpoint's `current_utc`; explicitly leaves the §2.2/§2.5 three-fractional-digit forms unaffected — `implementation/db.py:56-59` (`fmt_clock`), `implementation/serialize.py:22,23,34,53,82,115`, `implementation/routes_clock.py:21`.**
  - Justification: Step 7 fix 1. PRD pinned the clock's provenance and exact startup string but never stated the serialization precision of clock-derived fields; the Step 6 implementer chose `.000Z` everywhere and had to be corrected. Demonstrated non-uniqueness → pin the impl's choice.
- **§2.6 — revise — "Training hours are kept to one decimal place, with round-half-up applied per supervision entry before summing" → "Training-hour credit is rounded half up to whole hours per supervision entry before summing" — `implementation/calc.py:82-93` (`recompute_endorsement_hours` uses `rhu_int`, whole-hour ROUND_HALF_UP per entry).**
  - Justification: Step 7 fix 2. "Kept to one decimal place" matched nothing in the impl (hours stored raw via `req_number` with no quantization; `logged_hours` is a raw sum) and "one decimal place" granularity contradicts §3.3's pinned worked example.
- **§3.3 — revise — "each entry's credited value is rounded half up to one decimal place" → "rounded half up to whole hours" — `implementation/calc.py:91`.**
  - Justification: Step 7 fix 2. The phrase contradicted the paragraph's own pinned worked example (two 7-hour mismatched entries: 3.5→4 per entry, 4+4=8, not 7.0), which is only satisfiable with whole-hour rounding; the impl follows the example.

**Zero-change sub-items (PRD already pins; impl matches):** `created_at`/`updated_at` 3-fractional-digit format (§2.5); FAIL whole-hour floor scaling (§3.3 "whole-hour floor of three quarters" = `calc.py:106-108`); threshold auto-advance at equality (§3.3 "at least 600 … with equality passing" — the pre-fix failure was purely a downstream effect of the rounding granularity); clock monotonicity with equality accepted (§2.4). `tour_start`/`tour_end` echo format is PRD-silent but was untouched by Step 7 — left silent per hard scope.

**Per-edit pre-edit search log (NO-NEW-MISMATCH):**

- **Edit §2.4:** (a) Subject: serialization precision of clock-derived timestamps. (b) Enumerated and read every timestamp path: `serialize.py` lines 10-11, 22-23, 34, 45, 53, 82, 115, 127-128; `routes_clock.py:21`; `envelope.py:9-10` (wall-clock `api_request_timestamp`, 3-frac); `db.py:51-59, 83-97` (`touch`/`new_entity` set `created_at`/`updated_at` from `clock_now()` yet serialize 3-frac — a provenance-based universal claim would have been false); `routes_artists.py:42,60-62,80,88` (`performed_at` validated but never stored/echoed); `routes_wood.py:36,79`; `routes_builds.py:180-198`; `routes_endorse.py:100`; `routes_loans.py:63-77` (user-supplied tour window, echoed 3-frac, deliberately unmentioned). (c) Wording adjusted from a universal "every timestamp taken from the clock" claim to an explicit field enumeration plus a §2.2/§2.5 carve-out, avoiding the `created_at`/`updated_at` trap.
- **Edit §2.6:** (a) Subject: training-hour crediting granularity and storage precision. (b) Enumerated: `calc.py:49-54` (`rhu_int`/`rhu_1dp` — the latter used only by `authenticity_pct`, line 154), `calc.py:82-93, 96-103, 106-108, 111-125`; `routes_endorse.py:87-101, 126-128`; `routes_builds.py:201-212`; `validate.py:49-56` (no input quantization); `serialize.py:75-76`. (c) Dropped the false storage-precision clause ("kept to one decimal place") entirely rather than re-scoping it, since the impl quantizes hours nowhere; authenticity's separate 1-dp sentence left verbatim.
- **Edit §3.3:** (a) Subject: per-entry credited-value rounding granularity. (b) Same enumerated crediting paths as §2.6 edit, plus the FAIL-recompute path (`routes_endorse.py:126-128` → `calc.py:82-93`: 444/5/5 → effective 450) and the stage-advance credit path (`routes_builds.py:201-212`). (c) Single-phrase granularity swap ("one decimal place" → "whole hours"); all surrounding prose — ratios, pinned order, worked example, FAIL sentence — now self-consistent and matches the impl.

Verification: `diff -q` confirms PRD_FINALIZED.md differs from PRD.md; the exact diff is the three lines above (76, 91, 141).

Orchestrator verification: independent `diff PRD.md PRD_FINALIZED.md` shows exactly the 3 reported line revisions (lines 76, 91, 141), both files 268 lines.

## Step 9: Complete PRD — 2026-10-02T05:18:00.000Z

All edits verified coherent. The final file state is confirmed. Here is the summary.

## Summary

**Source vs output**: `workspace/PRD_FINALIZED.md` (268 lines / 42,989 chars) → `workspace/PRD_COMPLETED.md` (268 lines / 46,640 chars, delta **+3,651 chars**). `diff -q` confirms the files **differ** — 19 paragraphs revised in place, no sections added or removed.

**Walk coverage**: every implementation file read in full — `app.py`, `envelope.py`, `auth.py`, `errors.py`, `db.py`, `validate.py`, `serialize.py`, `calc.py`, and all nine route modules — covering every endpoint, state transition, formula, validation, error code, response shape, and side effect; tests cross-referenced as auxiliary only.

**Counts**: 20 ambiguity-pins, 2 mismatch-revisions.

**Changes** (section — insert|revise — kind — what — impl anchor):
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are clamped, non-integer fails `ERR_VALIDATION`; sort ties broken by creation order — validate.py:94-111, envelope.py:40-48
- §2.4 — insert — ambiguity — envelope `api_request_timestamp` is the sole wall-clock value (request metadata) — envelope.py:8-14
- §2.5 — revise — ambiguity — `created_at`/`updated_at` are logical-clock readings in 3-fractional-digit form — db.py:83-97, serialize.py:7-13
- §2.6 — revise — **mismatch** — moisture readings recorded exactly as posted, no server-side rounding (impl never enforces "two decimal places") — routes_wood.py:30/67/70
- §3.2 — insert — ambiguity — `to_stage` limited to the five enterable stages (else `ERR_VALIDATION`); advancing a `COMPLETED` order fails `ERR_INVALID_STATE` — routes_builds.py:146,156-157
- §3.2 — insert — ambiguity — RIM_BENT batch-holding precondition fails `ERR_INVALID_STATE` — routes_builds.py:161-163
- §3.2 — insert — ambiguity — ENDORSED apprentice may advance with/without supervisor; gate ignores supplied supervisor's specialty, stage log records it, credited entry's `specialty_match` reflects actual specialty — routes_builds.py:129-132,197,202
- §3.2 — insert — ambiguity — stripped-order SEASONING re-entry with no `wood_batch_id` fails `ERR_WOOD_NOT_CONDITIONED`; payload value otherwise existence-checked but ignored — routes_builds.py:143-145,165-172
- §3.3 — revise — ambiguity — null supervisor pre-endorsement fails `ERR_VALIDATION`; `REVOKED` track rejects logs with `ERR_INVALID_STATE` — routes_endorse.py:90-94
- §3.3 — insert — ambiguity — promotion bar re-evaluated only on hour-crediting events; a `FAIL` leaving hours above the bar does not re-promote — routes_endorse.py:124-128
- §3.3 — insert — ambiguity — wrong-state `REVOKE`/`REOPEN` fails `ERR_INVALID_STATE`; `effective_hours` and `endorsed_by_craftsman_id` retained through REVOKE/REOPEN — routes_endorse.py:139-147
- §3.4 — revise — ambiguity — non-`SHOWROOM` status folded into `ERR_INSTRUMENT_NOT_BANK_ELIGIBLE` — routes_instruments.py:42-50
- §3.6 — insert — ambiguity — `tour_start`/`tour_end` echoed normalized UTC, three-fractional-digit form — serialize.py:127-128
- §3.6 — insert — ambiguity — confirm only on `REQUESTED` loan, else `ERR_INVALID_STATE` — routes_loans.py:122-123
- §3.6 — revise — ambiguity — selector `created_at` ties then broken by creation order, never id — routes_loans.py:141
- §3.6 — insert — ambiguity — return only on `ON_TOUR` loan, else `ERR_INVALID_STATE` — routes_loans.py:168-169
- §3.6 — revise — ambiguity — auto-case diagnosis format pinned as `post-tour condition <grade>` — routes_loans.py:190
- §3.7 — insert — ambiguity — quote values required non-negative integers, total ≥ authentic, else `ERR_VALIDATION`; opening against `ON_LOAN` instrument fails `ERR_INVALID_STATE` — routes_restore.py:43-49
- §3.7 — insert — ambiguity — advance `to_stage` error taxonomy (lifecycle name → `ERR_INVALID_STATE`; unknown → `ERR_VALIDATION`; illegal transition → `ERR_INVALID_STATE`) — routes_restore.py:101-109
- §3.7 — revise — **mismatch** — resolve-authenticity requires both revised value fields (the "and/or" phrasing loosened); `waiver_accepted` optional, keeps current value; non-hold case → `ERR_INVALID_STATE` — routes_restore.py:121-127
- §3.7 — insert — ambiguity — final values required non-negative integers with total ≥ authentic (`ERR_VALIDATION`); non-`REBUILT` completion → `ERR_INVALID_STATE` — routes_restore.py:145-150

**Suspected impl bugs (PRD left unchanged)**:
- **Tour-weeks formula** — PRD pins "whole-day length divided by 7 and rounded up" (§3.6 fee, §3.5 standing_forward), where §2.4 defines a day count as floor(elapsed 86,400-second days); impl calc.py:128-131 computes `ceil(elapsed_seconds / 604800)`, which diverges for sub-day remainders (7 days + 1 hour: PRD 1 week, impl 2). The PRD rule is precise and deliberately tied to §2.4's floor-day definition; the impl reads as an accidental simplification. All test fixtures use midnight-aligned windows, so the suite never observes it.

## Post-Step-9: impl fix + re-validation sweep — 2026-10-02T05:23:00.000Z

Orchestrator adjudication of Step 9's flagged suspected impl bug (per pipeline policy: a precise PRD rule the impl violates is an impl bug, not a PRD edit):

- **Fix applied to `implementation/calc.py` (`tour_weeks`, lines 128-133):** was `ceil(elapsed_seconds / 604800)`; now `days = seconds // 86400; weeks = ceil(days / 7)` — matching PRD §3.6/§3.5 via the §2.4 whole-day floor definition. Verified via grep this is the only week computation (used by loan-fee confirm at routes_loans.py:152 and `standings` at calc.py:146). Orchestrator applied the edit directly (2-line, fully PRD-determined).
- **Step 9 mismatch revisions reviewed and accepted as-is:** the moisture "two decimal places" claim had no pinned rounding mode (genuinely under-determined → pinning impl's store-as-posted is legitimate); the resolve-authenticity "and/or" narrowing matches impl's require-both reading (impl behavior is a subset of PRD-admitted calls; Step 9's job is to pin the adopted interpretation).
- **Re-validation sweep (mandatory after post-Step-7 impl writes):** full 8-round parallel sweep re-run by the orchestrator after the calc.py edit — **all 8 rounds 87/87, 0 failures**. mtime ordering confirms the fix (calc.py 05:19:34) predates the sweep results (oldest 05:22:23). `results.{1..8}.json` regenerated and present in `workspace/implementation/` per the output contract.
