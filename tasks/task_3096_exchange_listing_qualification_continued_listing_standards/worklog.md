# Worklog — task_3096_exchange_listing_qualification_continued_listing_standards

## Step 1: Create task directory — 2026-09-29T00:00:00.000Z

Task directory `./tasks/task_3096_exchange_listing_qualification_continued_listing_standards/` was pre-allocated by the invocation (with `workspace/` inside); verified it exists. No new index computed, no other task directory created.

## Step 2: Generate scaffold — 2026-09-29T00:10:00.000Z

All three scaffold artifacts are generated, cross-checked, and lint-clean.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_3096_exchange_listing_qualification_continued_listing_standards/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Surface counts:**
- Entities: 11 (Issuer, ListingApplication, Listing, MarketDataSnapshot, Deficiency, ComplianceRecord, CompliancePlan, HearingsReview, Appeal, FeeAssessment, CorporateAction)
- State machines: 7 with 31 transitions (Deficiency is cyclic incl. reopen-on-reversal; Appeal is fork-join through panel→council; Listing has an in-request ACTIVE→SUSPENDED→DELISTED pair)
- Calculations: 4 (`evaluate_tier_standards` entry-vs-continued variants, `deficiency_streak_detection` chronological streaks, `bid_price_regain_projection` split-adjusted replay, `fee_assessment` tiered bracket clamp with pinned ordering and dual variants)
- Validations: 21 ordered priorities (incl. auth/ownership at 1–2.5, state at 4, segregation-of-duties at 5, readmission bar at 6, governance at 7, temporal windows at 12–15, fiscal at 17–18, schema at 19, OCC at 20)
- Endpoints: 71 (incl. `/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default, plus flat `/listings`, `/deficiencies`, `/appeals`, `/fee-assessments`, etc. index GETs for FK reverse-reachability)
- Errors: 31 (all referenced by at least one validation or transition)
- Concurrency rules: 2 (OCC on `Issuer.version` for application approval and annual fee runs)
- Roles: 5 (IssuerOfficer entity-backed by Issuer; ListingAnalyst/HearingsOfficer/ListingsCouncil/FinanceOfficer opaque — segregation-of-duties model)

**Difficulty design (§1.8):** 18 instances — 2 per rule across all 9 rule_ids, each with fully structured `setup_api_calls`/`trigger` chains (literal payloads, `${var}` placeholders only for server-minted ids/versions, YAML anchors for shared 30-day snapshot fixtures, pre-computed fee literals verified by executing the bracket formula: e.g. ENTRY GLOBAL_SELECT@1 share = 1500000, ANNUAL = 450000, CAPITAL bracket flip 15000000→650000 vs 15000001→800000, mid-year surcharge ordering 800000+1000000=1800000).

**Corner design (§1.9):** 49 instances (45 active + 4 `excluded_because` stubs pointing at §1.8 instances), spanning all 9 claim-guide sections.

**Notable design decisions:**
- `api_prefix: /` — required so the lint's FK reverse-reachability check can derive collection segments for both issuer-nested and flat (`/hearings-reviews`, `/deficiencies`, …) resources.
- Delisting execution is a single endpoint that drives Listing ACTIVE→SUSPENDED→DELISTED in-request, then cascades to Issuer status, fee invoicing/fill (with delisted-mid-year surcharge), deficiency/appeal/corporate-action closure — a depth-3 transitive chain.
- Panel/council REVERSE decisions close the old deficiency and mint a fresh OPEN row, conserving the issuer's actionable-deficiency cardinality (compensating invariant).
- Deficiency detection uses strict `<` thresholds over consecutive trading days with trigger counts 30 (bid) vs 10 (others) and a 10-day regain window — boundary instances pin 29-vs-30 and 100-cents-exactly.

Final lint verdict: **clean lint** (71 endpoints, 11 entities, 18 §1.8 + 45 §1.9 instances, 2124 calls scanned, 0 violations).

## Step 3: Copy shared files — 2026-09-29T00:20:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3096_exchange_listing_qualification_continued_listing_standards/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T00:30:00.000Z

PRD generation complete.

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3096_exchange_listing_qualification_continued_listing_standards/workspace/PRD.md` — 288 lines.

**Section structure:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 10 subsections: RBAC (2.1), fixed verbatim Response Structure (2.2, emitted byte-identical from `section-2.2-response-structure.md`), Pagination (2.3), Common Resource Properties (2.4, including the `common_fields: false` exception for MarketDataSnapshot/ComplianceRecord), Logical Clock (2.5), Precision (2.6), OCC (2.7), Cascading Finalization (2.8), Nested Resource Retrieval (2.9), Segregation of Duties (2.10)
- §3 Business Logic — 10 lifecycle-ordered subsections (registration → submit/evaluate → adjudication → surveillance → plans → staff determination → hearings/appeals → delisting execution → reverse splits → fees)
- §4 Endpoint table — 4 columns, 71 endpoints
- §5 Error catalogue — 2 columns, 31 error IDs

**Coverage audit results:**
- Contract 1 (Field-Name Coverage): 65 required identifiers (all entity fields + endpoint inputs/query params), all present in backticks. First pass missed 6 (`amount_cents`, `announced_at`, `application_id`, `deficiency_id`, `fee_kind`, `filed_at`); repaired by weaving them into existing narrative sentences. PASS.
- Contract 2 (Rule Coverage): all state-machine transitions expressed with from/to states, preconditions paired with their `error_id`, and side effects stated (including the delisting cascade, the `DELIST_REVERSED` → new `OPEN` deficiency row, plan supersession on reverse-split regain, and mid-year annual-fee fill with halving per effective reverse splits); both OCC rules expressed with `expected_issuer_version` + `ERR_STALE_VERSION`/412; all four calculations rendered as precise prose with all constants embedded (entry thresholds, continued thresholds, streak triggers 30/10, regain 10, cure 180 days, appeal 7 days, full bracket tables, 1,000,000-cent mid-year surcharge); all 20 validation rules matchable to error IDs in §2/§3 prose. PASS.
- Contract 3 (§3 Path Purity): 407 backtick tokens scanned in §3; zero tokens starting with `/`, zero bare HTTP methods, zero method+path combos. PASS.
- All 31 scaffold error IDs mentioned in §2/§3 prose.

**Notable rendering decisions:**
- Underscore-style scaffold constants (e.g., `45_000_000_000_00`) rendered as plain integer-cent amounts (45,000,000,000,000 cents) to avoid pseudocode while preserving exact values.
- Threshold asymmetry preserved exactly: entry eligibility uses "at least" (≥) while deficiency detection uses "strictly fails"/"below" (<).
- The `PRE_LISTING`/`LISTED`/`DELISTED` issuer status machine has no scaffold transitions table (transitions are side effects of application approval and delisting execution); expressed narratively in §3.1/§3.3/§3.8.
- The two difficulty-design files were not read, per the hard constraint.

## Step 5: Generate unit tests — 2026-09-30T00:00:00.000Z

All checks pass. Final summary:

### Files written

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_3096_exchange_listing_qualification_continued_listing_standards/test_helpers/`):
- `types.py` — status/role/tier enums + TypedDicts; `MarketDataSnapshot` and `ComplianceRecord` correctly omit `updated_at`/`version` (append-only logs).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. logical clock, cross-issuer indexes, monitor run, execute-delisting, appeal/panel/council chain, fees, corporate actions).
- `api_errors.py` — full 32-entry `ApiErrorId` enum + HTTP status map registered via `set_error_http_status_map`.
- `assertions.py` — per-entity validators; append-only entities assert absence of `version`/`updated_at`.
- `factories.py` — payload factories; the default application payload passes CAPITAL entry standard A1, the default snapshot payload is non-bid compliant at every tier.
- `constants.py` — entry/continued thresholds, trigger/regain day counts, full ENTRY/ANNUAL bracket tables, mid-year surcharge, plus `compute_fee_amount_cents`.
- `test_users.py` — shared headers for the four opaque roles + `make_issuer_officer_headers(issuer_id)` for the entity-backed IssuerOfficer role.
- `fixtures.py` — composite helpers: `reset_clock`, `create_issuer`, application lifecycle, `setup_listed_issuer`, day-by-day snapshot streak feeder (`record_snapshot_days`), `setup_bid_deficiency`, `setup_staff_determined_deficiency`, `setup_filed_appeal`, `setup_panel_reviewing_appeal`, `run_annual_fee`, `get_entry_fee`, `advance_clock_past_cure`.
- `__init__.py` — barrel export.

**`test_suite/`**: `conftest.py` + 5 test files (`test_01` CRUD/envelope, `test_02` application lifecycle & tier standards, `test_03` deficiency monitor / plans / fee brackets, `test_04` delisting cascade / appeals / reverse splits, `test_05` validations / RBAC / temporal / OCC).

### Coverage
- **Queue A (Difficulty): 36 tests** — all 18 instances at ≥2 tests each.
- **Queue B (Corner): 45 tests** — all 36 non-stub instances at ≥1 test each. The 4 `excluded_because:` stubs were verified to resolve to live difficulty instances and were not translated.
- Every test docstring ends with exactly one verbatim `Design: Difficulty/<rule>/<instance>` or `Design: Corner/<section>/<instance>` line; a programmatic audit confirmed each tag resolves to a real instance and each instance meets its count floor.

### Instances skipped
- Queue A: none.
- Queue B: only the four declared stubs (not translatable by design).

### Verification results
- All 16 files compile; `pytest --collect-only` collects 81 tests cleanly.
- Verbatim-citation sweep: all 115 quoted PRD citations contain a distinctive ≥8-word substring that survives literal grep of `workspace/PRD.md` (this surfaced and fixed PRD's backtick formatting and corrected the cascade's `2027-04-09` date arithmetic to `2027-04-10` where clock offsetting mattered).
- No `skip`/`skipif`/`xfail` markers; no scaffold section references in comments/docstrings (only the mandated `Design:` tags).

One note: tests were statically validated (compile, collect, citation-grep, tag-coverage). They were not executed against a live implementation — that's the runner/implementation stages' job.

## Step 6: Generate implementation — 2026-09-30T00:10:00.000Z

Implementation complete. Summary:

## Files written
All in `/home/ubuntu/github/CodingPRD/tasks/task_3096_exchange_listing_qualification_continued_listing_standards/workspace/implementation/`:
- **`start.sh`** (executable) — guards the dep install with `python3 -c "import flask"`, then `exec python3 app.py` in the foreground; binds `0.0.0.0:$PORT` (default 10000) via `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`.
- **`requirements.txt`** — `flask>=3.0` (already installed on the host, so install is a no-op on reboots).
- **`core.py`** — logical clock (default `2026-09-01T00:00:00Z`, settable only via `/_clock/set_current_utc`, never wall-clock), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type` object/array/error, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`), `ApiError`, in-memory `Store` (11 dicts, empty at boot, zero seeding), auth context (`X-User-ID`/`X-User-Role`), ownership enforcement, left-to-right path-id lookups with entity-specific 404s, pagination, payload validators.
- **`services.py`** — entry-standards evaluation (GLOBAL_SELECT S1–S3, GLOBAL S1–S3, CAPITAL base+A1–A3 with per-standard margins), continued-standards evaluation, governance composition validation, snapshot-based deficiency streak detection/regain (bid 100c trigger 30d; others trigger 10d; regain 10d; GLOBAL_SELECT MVPHS n/a), fee bracket tables (ENTRY inclusive vs ANNUAL exclusive, clamp semantics, +1,000,000c mid-year surcharge), full execute-delisting cascade, reverse-split projection (10-snapshot window, 0-bid days never qualify).
- **`app.py`** — all routes plus error handlers.

## Endpoint count
All **57 endpoints** from the scaffold endpoint table are implemented (clock, issuers, applications incl. cross-issuer index, listings incl. index, snapshots incl. index, deficiency monitor, deficiencies + per-deficiency records/plans/appeals lookups, compliance records incl. index, plans incl. index + review, hearings reviews + close + per-panel appeals, appeals + panel/council review/decision, fee assessments + run-annual-fees/mark-paid/waive, corporate actions + effect/reject/cancel). [Orchestrator verification: `grep -cE '@app\.(route|get|post|put|patch|delete)' app.py` = 71, matching the PRD §4 table's 71 endpoints (72 grep rows include the header row); the subagent's "57" count was a miscount of its own route decorators.]

## State machines covered
ListingApplication (DRAFT→SUBMITTED with governance + auto-REJECT on zero passing standards, APPROVED with listing/ENTRY-fee/listing-tier side effects, REJECTED with readmission barring), Listing (ACTIVE→SUSPENDED→DELISTED in-request), Deficiency (OPEN/PLAN_SUBMITTED→REGAINED/STAFF_DELIST_DETERMINED→PANEL_REVIEW→DELIST_UPHELD/DELIST_REVERSED with new OPEN row on reversal), CompliancePlan (PENDING_REVIEW→APPROVED/REJECTED with TIER_TRANSFER listing mutation), Appeal (FILED→PANEL_REVIEWING→PANEL_AFFIRMED/REVERSED→COUNCIL_REVIEWING→COUNCIL_AFFIRMED/REVERSED), FeeAssessment (PENDING→INVOICED immediately→PAID/WAIVED), CorporateAction (SUBMITTED→EFFECTIVE/REJECTED/CANCELLED with regain projection + superseded-plan rejection).

## Calculations
Tier-standard thresholds per scaffold constants (integer cents, no rounding); fee `clamp(shares, bracket_min, bracket_max)` per bracket row with top-row clamp and flat mid-year surcharge; consecutive-day streaks with strict `<` failure comparisons; split-adjusted bid projection.

## Validations
Priority order honored: missing headers (400) → role (403) → IssuerOfficer ownership (403) → existence (404, left-to-right) → state (409) → segregation of duties (403, plan filer vs reviewer / appeal filer vs decider) → business rules (readmission bar, governance, multiple pending, no-standard-met/tier-transfer-target, snapshot date/uniqueness, plan allowed, cure period, appeal window, delisting blocked, council availability, qualifying deficiency, fee-already-assessed) → OCC.

## Logical clock and OCC
Clock is module-level state initialized to exactly `2026-09-01T00:00:00Z`, advanced only by `POST /_clock/set_current_utc`; all temporal rules (180-day cure, 7-day appeal window, snapshot date match, billing year, `detected_at`/`staff_determined_at`/`announced_at`/`regained_at`) read from it. OCC: `expected_issuer_version` on application approve and run-annual-fees only; mismatch → `ERR_STALE_VERSION` (412); both endpoints increment `Issuer.version`.

Verified via three smoke suites (each on a fresh `bash start.sh` boot confirming empty store + default clock): full happy path, governance/SoD/RBAC/404/422/409/412 errors, tier-transfer plans and applications, reverse-split regain, appeal→panel→council→execute-delisting cascade with mid-year fee fill and split-halved shares, and readmission barring. All passed.

## Step 7: Run tests and iterate — 2026-09-30T00:40:00.000Z

All 8 parallel rounds pass 81/81. Clean sweep achieved.

**Iterations run:** 4 (initial baseline 68/81 → 78/81 → 80/81 → 81/81 in all 8 rounds).

**Tests deleted:** None. Every failing rule was at least partially PRD-covered; per the partial-coverage rule (1c) tests were restructured to keep PRD-verbatim assertions and drop only the PRD-silent ones.

**Fixes applied to `test_helpers/`:**
- `constants.py` — all entry/continued/tier-transfer thresholds were authored at the scaffold's dollars-scale shorthand (10–100x below PRD's verbatim cent values, e.g. `45_000_000_000_00` vs PRD's 45,000,000,000,000). Corrected every constant to the PRD number. Fee bracket tables already matched PRD.
- `factories.py` — `create_snapshot_payload` defaults (MVPH 500,000,000; MVLS 600,000,000,000) were *non-compliant* under PRD §3.4 continued thresholds and would have spawned spurious MVPHS/MVLS deficiencies once the implementation was corrected; raised to 6,000,000,000 / 6,000,000,000,000 (compliant at every tier). Same for the application factory's default MVLS (600,000,000,000 → 6,000,000,000,000, now also passes CAPITAL A2).
- `fixtures.py` — `advance_clock_past_cure` advanced 2 days past `compliance_due_at`; PRD §3.6 requires only "strictly after", so the earliest valid day is +1. All downstream appeal-window dates (2027-04-02 etc.) derived from the +2 choice; now the staff determination lands on 2027-03-31 per PRD arithmetic (detected 2026-10-01 + 180d = 2027-03-30, strictly-after = 2027-03-31).

**Fixes applied to `test_suite/`:**
- `test_02…fee_convention_…_a/b` — exact amount expectations used scaffold-scale numbers and assumed the scaffold-only `clamp(shares, min, max)` formula; PRD §3.10 states only ranges. Replaced with PRD-verbatim range membership plus the PRD-covered "strictly lower" ordering (kept only in `_a`, where the entry/annual ranges are disjoint; at 5,000,000 shares in `_b` the ranges touch, so ordering is not uniquely derivable there).
- `test_02…tier_standards_…_b` — expected a TIER_TRANSFER app with entry-failing metrics to reach SUBMITTED, but PRD §3.2 evaluates entry standards at submit with no kind exemption (auto-reject). Restructured: first a TIER_TRANSFER with metrics passing both gates approves (continued-gate path, listing tier rewritten), then the borderline set (MVUPH exactly 5,000,000,000 — passes GLOBAL continued, fails all GLOBAL entry standards) auto-rejects at submit.
- `test_03…entry_fee_tier_and_year…`, `…fee_bracket_upper_boundary_membership_a/b` — exact in-bracket amounts are not uniquely derivable from PRD's range-only tables; replaced with range-membership assertions (PRD-verbatim bracket bounds) while keeping fee_kind/tier/year/shares/status assertions.
- `test_04…appeal_filing_moves…`, `…panel_reversal_conserves…`, `…execute_delisting_transitive_cascade_a`; `test_05…appeal_window_half_open…_a/b` — recomputed all baked-in dates per PRD arithmetic (staff determination 2027-03-31; appeal boundary 2027-04-07 inside / 2027-04-08 outside; reversal due 2027-09-27; delisting executed 2027-04-08).
- `test_04…fee_bracket_clamp_order_with_mid_year_surcharge_a/b` — exact clamped amounts rely on the scaffold-only formula; kept the PRD-covered surcharge rule via a same-tier/same-shares control issuer (`fill.amount == control.amount + 1,000,000`, "surcharge never bracket-adjusted").
- `test_05…approve_with_stale_issuer_version_returns_412` — the replayed request violates both the duplicate-year rule (409) and OCC (412); PRD names both but ranks neither → relaxed to `validate_error_is_one_of(["ERR_STALE_VERSION", "ERR_FEE_ALREADY_ASSESSED"])` per the permitted precedence-silence exception.

**Fixes applied to `implementation/`:**
- `services.py` — `evaluate_entry_standards`, `evaluate_continued_standards`, and the monitor thresholds (`_CONT_MVPH`/`_CONT_MVLS`) used values 10–100x smaller than PRD (e.g. GLOBAL_SELECT continued MVLS 3e12 vs PRD's 30,000,000,000,000; GLOBAL S2 MVLS 7.5e11 vs 7,500,000,000,000; CAPITAL A2 5e10 vs 5,000,000,000,000; MVPHS 5e8/1e8 vs 5e9/1e9). Corrected all to PRD-verbatim numbers.
- `app.py` — `council_decision` REVERSE previously skipped the deficiency transition once the panel had closed it as `DELIST_UPHELD`; PRD §3.7 states council REVERSE "transitions the deficiency to `DELIST_REVERSED` with the same new-`OPEN`-deficiency side effect as a panel reversal" (unconditional, unlike the conditional AFFIRM). Now transitions from `PANEL_REVIEW` or `DELIST_UPHELD`.

Orchestrator verification of final sweep: all 8 `results.{1..8}.json` files present, each `total=81, passed=81, failed=0, errors=0, skipped=0`.

## Step 8: Finalize PRD — 2026-09-30T00:50:00.000Z

Done. Summary:

## Line counts / delta
- `PRD.md`: 288 lines
- `PRD_FINALIZED.md`: 288 lines (one in-place sentence insertion inside §3.10, no lines added/removed)
- `wc -c` delta: +216 bytes (+0.6%)

## Changes (one edit, two hunks forming a single inserted rule)
- **§3.10 — insert** — Added the in-bracket fee rule after "counts above the top row's upper bound clamp to the top row's maximum": *"Within a bracket row, the charged amount equals the share count expressed in cents and clamped to the row's stated range—that is, raised to the row's minimum when below it and lowered to the row's maximum when above it. The same in-bracket rule applies to both the entry table and the annual table below."* — `implementation/services.py:189-207` (`compute_fee`: `amt = min(max(shares, mn), mx)` per bracket row, else-branch clamps to top row max; surcharge added after). This is the only place where Step 7 revealed genuine PRD silence with an impl-pinned choice: PRD §3.10 gave only per-bracket ranges, while the implementation concretely charges the share count clamped into the range. Step 7 weakened tests (`test_02 fee_convention a/b`, `test_03 entry_fee_tier_and_year`, `test_03 fee_bracket_upper_boundary_membership a/b`) to range membership precisely because the exact amount was PRD-undetermined.

## Items from `<step_7_diff>` deliberately producing NO edit
- `constants.py` / `factories.py` threshold and default fixes — pure test-helper bugs; PRD already had the verbatim cent values (§3.2/§3.4/§3.5) that the impl was corrected to.
- `fixtures.py` `advance_clock_past_cure` (+2 → +1) — PRD §3.6 already says "strictly after"; fixture arithmetic bug only.
- `test_02 tier_standards..._b` restructure — confirms PRD §3.2 (entry standards evaluated at submit for every application kind, no TIER_TRANSFER exemption); impl `app.py:246-254` already did this.
- Date recomputations in test_04/test_05 — recalibration to PRD §3.4/§3.6/§3.7 arithmetic already stated.
- Surcharge clamp-order tests — PRD §3.10 already says "adds a flat surcharge of 1,000,000 cents after the bracket clamp; the surcharge is never bracket-adjusted"; impl matches.
- `test_05 stale_issuer_version` 409-vs-412 relaxation — Step 7 explicitly invoked the permitted precedence-silence exception; pinning the impl's 409-first order was intentionally avoided (looser PRD is recoverable; a pinned order would add an assertion Step 7 declined to enforce).
- `services.py` threshold corrections and `app.py` council-REVERSE fix — impl brought *to* existing PRD-verbatim text (§3.2/§3.4 thresholds; §3.7 unconditional council REVERSE).

## Pre-edit search log
**Edit 1 (§3.10 in-bracket fee rule):**
- (a) Subject: how the fee `amount_cents` is computed from `shares_outstanding` within a bracket row, for both ENTRY and ANNUAL fees, including the mid-year surcharge interaction and the delisting-cascade fee fill.
- (b) Impl paths enumerated and read: `services.py:157` (`MID_YEAR_SURCHARGE_CENTS`), `services.py:159-180` (all four bracket tables), `services.py:183-207` (`_pick_table`, `compute_fee` — both branch forms incl. the `else` clamp-to-top-row-max), `services.py:385-418` (delisting cascade ANNUAL fill: shares source selection, floor-halving per EFFECTIVE REVERSE_SPLIT, `shares < 1 → 1` guard, `delisted_mid_year=True` surcharge), `app.py:309-323` (ENTRY fee at approval), `app.py:1169-1205` (`run-annual-fees`). Cross-checked against the Step-7-relaxed tests (`test_03:433-549`, `test_02:258-336`, `test_04:371-472`) to confirm every surviving assertion (range membership, inclusive bounds, surcharge-after-clamp, ordering where disjoint) is entailed by the new wording.
- (c) Wording adjustment: initial draft read "the charged amount equals the share count clamped to the row's stated range"; revised to "the share count expressed in cents and clamped..." because the clamp floor of 1 is applied *before* the bracket rule in the cascade fill (which would otherwise mis-describe the fill when halving drives shares to 0), and "expressed in cents" matches the impl's unit-agnostic arithmetic (all bracket bounds are cent magnitudes compared against raw share counts). No other path conflicted.

## Step 9: Complete PRD — 2026-09-30T01:10:00.000Z

Done. PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_3096_exchange_listing_qualification_continued_listing_standards/workspace/PRD_COMPLETED.md`.

**Size delta:** PRD_FINALIZED.md 288 lines / 39,644 chars → PRD_COMPLETED.md 289 lines / 45,171 chars (+1 line, +5,527 chars). 29 paragraphs touched (30 output lines incl. one added row).

**Counts:** ambiguity-pins: 22; mismatch-revisions: 2.

Changes:
- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as wall-clock generation time, not logical clock — core.py:60-64
- §2.3 — insert — ambiguity — pagination clamping of limit (1–100), offset (min 0), ERR_INVALID_REQUEST on non-integers; sort tie-break by `id` — core.py:312-328
- §2.5 — insert — ambiguity — clock set stores string verbatim, missing/non-string `current_utc` → ERR_INVALID_REQUEST 400, response body `{"current_utc": ...}` — app.py:52-60
- §2.7 — revise — mismatch — `expected_issuer_version` is optional (omitted ⇒ check skipped) on approve and run-annual-fees — app.py:290-293, app.py:1187-1190
- §2.9 — insert — ambiguity — unknown snapshot/record ids, unmatched routes, and disallowed methods yield generic `ERR_NOT_FOUND` 404 — core.py:283-308, app.py:34-41
- §2.10 — insert — ambiguity — segregation-of-duties does not apply to panel-review/council-review (take-under-review) steps — app.py:1066-1084, 1118-1130
- §3.1 — insert — ambiguity — ticker uniqueness is exact case-sensitive string comparison — app.py:71-74
- §3.1 — insert — ambiguity — `readmission: true` forces `application_kind=READMISSION`; bar checks any prior application with `readmission_rejected`; new application has `evaluated_standards: []`; numeric fields non-negative ints, committees arrays — app.py:128-156, 137-143
- §3.2 — insert — ambiguity — submit requires DRAFT (else ERR_INVALID_STATE 409); check order: state → multiple-pending → TRANSFER flag → governance → evaluation — app.py:234-246
- §3.2 — insert — ambiguity — `evaluated_standards` entry shape: `standard_code` (`GLOBAL_SELECT_S1`…`CAPITAL_A3`), `passed`, `margin` = min of per-leg (value − threshold) — services.py:14-94
- §3.3 — revise — mismatch — non-SUBMITTED approve → ERR_INVALID_STATE 409; OCC optional; TIER_TRANSFER continued standards read app's `market_value_listed_securities_cents` / `market_value_unrestricted_publicly_held_cents` / `round_lot_holders` — app.py:259-293, 282-289
- §3.3 — insert — ambiguity — entry fee created PENDING then immediately INVOICED in the same request — app.py:309-323
- §3.4 — insert — ambiguity — monitor response body `{"deficiencies_created": [...], "deficiencies_regained": [...]}`; monitor tier = most recent non-DELISTED listing (fallback: any listing, then CAPITAL); MVPHS never created at GLOBAL_SELECT; no snapshots ⇒ no deficiencies — app.py:520-527, services.py:282-303
- §3.4 — insert — ambiguity — regain check measured against `tier_at_detection`; deficiencies in other non-terminal statuses and GLOBAL_SELECT-MVPHS keep `still_open` true without regain check — services.py:326-355
- §3.5 — insert — ambiguity — missing/invalid `proposed_target_tier` on TIER_TRANSFER plan → ERR_INVALID_REQUEST 400; CURE_IN_PLACE stores proposed tier as supplied/null; plan records `filed_by` — app.py:720-745
- §3.5 — insert — ambiguity — TIER_TRANSFER continued-standards validation only on APPROVE; missing snapshot → ERR_TIER_TRANSFER_TARGET_INVALID; snapshot picked by max `trade_date` — app.py:818-842
- §3.6 — insert — ambiguity — staff-determine from any status other than OPEN/PLAN_SUBMITTED → ERR_INVALID_STATE 409 — app.py:629-643
- §3.6 — insert — ambiguity — appeal filing: wrong deficiency status or second appeal → ERR_APPEAL_WINDOW_CLOSED 422; appeal records `filed_by` — app.py:973-991
- §3.7 — insert — ambiguity — closing a non-OPEN panel → ERR_INVALID_STATE 409; panel-review requires FILED appeal and OPEN panel; decisions require PANEL_REVIEWING/COUNCIL_REVIEWING — app.py:914-923, 1066-1077, 1094-1096, 1140-1142
- §3.7 — insert — ambiguity — new OPEN deficiency on reversal also carries the closed deficiency's `consecutive_days_failed` — app.py:1051-1058
- §3.7 — insert — ambiguity — council REVERSE applies while deficiency is PANEL_REVIEW or DELIST_UPHELD, no-op otherwise — app.py:1159-1164
- §3.8 — insert — ambiguity — listing must be ACTIVE (else ERR_INVALID_STATE 409); authorization evaluated across all issuer deficiencies; blocked-but-elsewhere-allowed proceeds — app.py:399-432
- §3.8 — insert — ambiguity — mid-year annual fee shares fallback to 1 if approving application missing; halved result clamped to ≥1 — services.py:394-404
- §3.9 — insert — ambiguity — effect requires SUBMITTED action (else ERR_INVALID_STATE 409); action becomes EFFECTIVE even when projection fails; superseded plan must be PENDING_REVIEW to become REJECTED; deficiency `closed_at` set on regain — app.py:1373-1376, services.py:445-476
- §3.9 — insert — ambiguity — reject/cancel require SUBMITTED (else ERR_INVALID_STATE 409); resulting statuses REJECTED/CANCELLED — app.py:1379-1403
- §4 — insert — ambiguity — endpoint-table notes for ERR_NOT_FOUND on snapshot/record get; `ERR_NOT_FOUND | 404` row added to §5 error catalogue — app.py:34-41, core.py:283-308

No new sections were added; all changes are in-paragraph inserts/revisions plus one table row and two endpoint-table annotations.
