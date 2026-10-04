# Worklog — task_3252_enterprise_agreement_true_up_license_position_assurance

## Step 1: Create Task Directory — 2026-09-30T14:32:10.702Z

Used pre-allocated task directory `./tasks/task_3252_enterprise_agreement_true_up_license_position_assurance` (already contained `workspace/`). No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T14:54:28.525Z

Scaffold generation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3252_enterprise_agreement_true_up_license_position_assurance/`)

| File | Lines | Content |
|---|---|---|
| `SCAFFOLD.yaml` | 1924 | §1.0–§1.7 (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1087 | `scaffold_difficulty_design:` — 9 rule blocks |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1588 | `scaffold_corner_design:` — 9 sections |

## Counts

- **Endpoints: 74** (all under `api_prefix: /licensing`, including the `POST /licensing/_clock/set_current_utc` test-driving clock with the mandated `2026-09-01T00:00:00Z` default)
- **Entities: 16** — Organization, Agreement, Product, EnrollmentAnniversary, LicenseEntitlement, Deployment, LicensePositionSnapshot, TrueUpReport, TrueUpLine, AssuranceBenefitGrant, BenefitRedemption, StepUpConversion, CloudCommitment, CloudConsumptionEvent, HostingAuthorization, ShortfallAssessment
- **State machines: 6** — Agreement (branching renewal fork: RENEWAL_PENDING→{ACTIVE back-branch, RENEWED, NON_RENEWED} plus EXPIRED), TrueUpReport (DRAFT→SUBMITTED→REJECTED→DRAFT revision cycle, 7 states), StepUpConversion, AssuranceBenefitGrant (ACTIVE→DEPLETED/EXPIRED/FORFEITED), CloudCommitment (ACTIVE→EXHAUSTED/EXPIRED), HostingAuthorization (APPROVED↔SUSPENDED cycle)
- **Calculations: 8** — price_level_tiering, license_position_computation (dual variant per_host/per_vm), core_count_normalization (16-core host min / 8-core VM min / min-cap), true_up_retroactive_pricing (proration vs full-year variants, per-line-round-then-sum pinned), benefit_accrual (3-tier threshold), cloud_consumption_waterfall (partial-cap), step_up_conversion, shortfall_exposure_projection (perpetual-survives/subscription-lapses variants)
- **Validations: 28** ordered rules; **errors: 27**; **roles: 4** (CustomerAdmin entity_backed by Organization; others opaque); **OCC concurrency rules: 2** (agreement renew, entitlement adjust)
- **Difficulty instances (§1.8): 18** — 2 per rule × 9 rules, all with structured `setup_api_calls`/`trigger`/`assert` and pre-computed literal numerics (e.g., prorated 833333 vs full-year 1000000; per-line rounding 100002 vs sum-then-round 100001; PER_VM 16 vs PER_HOST 64 on identical 64-core hardware; step-up charge 560000)
- **Corner instances (§1.9): 40** across all nine claim-guide sections (entities 6, state_machines 5, calculations 5, validations 7, endpoints 6, errors 3, rbac 4, cross_cutting_layers 3, consistency_model 1)

## Verification

`scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (447 calls scanned, 0 violations). Two structural fixes were needed to get there: prefixing all paths with `/licensing` (the lint derives FK collection segments only from single-GETs under the api_prefix root) and adding single-GET endpoints for TrueUpLine and ShortfallAssessment so their filtered-list FK reachability resolves. Additionally verified: no forbidden concurrency vocabulary, unique instance names across both design files, zero unbound `${var}` placeholders, and correct top-level key separation across the three files.

## Step 3: Copy Shared Files — 2026-09-30T14:54:54.443Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T15:03:49.860Z

All 74 endpoints and all 27 error IDs match exactly. PRD is complete and verified.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3252_enterprise_agreement_true_up_license_position_assurance/workspace/PRD.md` — 319 lines.

**Sections covered:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (10 subsections): RBAC with per-role identity semantics; verbatim §2.2 response envelope (byte-identical to the canonical source file); pagination (limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending); resource identity/versioning (including the four append-only record types that lack `updated_at`/`version`); logical clock (startup default 2026-09-01T00:00:00Z); money/precision/rounding (integer cents, round half-up, per-line-then-sum and per-server-then-sum rounding order); price levels A/B/C/D with multipliers 1.00/0.95/0.90/0.85; OCC (`expected_agreement_version` on renew, `expected_entitlement_version` on entitlement PATCH, `ERR_STALE_VERSION`/412); validation priority ordering narrative; cascading terminal-state side effects
- §3 Business Logic (10 subsections): enrollment, catalog/entitlements, anniversaries/deployments, license position (incl. core normalization: 16-core host minimum, 8-core VM minimum, ceil per server, PER_HOST vs PER_VM cap), true-up lifecycle (pinned snapshot, growth flooring, both proration variants with (12 − months_growth + 1)/12, submit repricing, revision loop, settle cascade), renewal/expiry/shortfall projection, SA benefits (tier thresholds at $500K/$2M/$5M, 365-day TTL, redemption rules, event-driven expiry sweep), cloud commitments (waterfall, silent partial consumption, EXHAUSTED/EXPIRED), step-up conversions (family/edition/kind gates, delta charge), license mobility hosting authorizations
- §4 Endpoint table — all 74 endpoints, 4 columns only
- §5 Error catalogue — all 27 error IDs, 2 columns only

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 67/67 entity fields, 50/50 endpoint input names, 2/2 query params present in backticks — PASS
- Contract 2 (Rule Coverage): all 28 validations (priority-ordered narrative in §2.9 plus per-rule trigger prose near each workflow), both OCC rules, all state-machine transitions with preconditions/side effects across 6 machines, all 7 calculations with constants embedded, all endpoint side effects — PASS
- Contract 3 (§3 Path Purity): 422 backtick tokens scanned in §3, 0 slash-prefixed, 0 bare HTTP methods, 0 method+path combos — PASS

**Confirmation:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, read, grepped, or referenced at any point. Only `SCAFFOLD.yaml` and the skill's own `SKILL.md` / `section-2.2-response-structure.md` were read.

## Step 5: Generate Unit Tests — 2026-09-30T15:17:38.243Z

Generation complete. Summary:

## Files written

**test_helpers/** (under `/home/ubuntu/github/CodingPRD/tasks/task_3252_enterprise_agreement_true_up_license_position_assurance/test_helpers/`):
- `__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 16 entity TypedDicts (append-only `LicensePositionSnapshot`/`BenefitRedemption`/`CloudConsumptionEvent`/`ShortfallAssessment` correctly carry only `id`+`created_at`) and 13 enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~60 methods)
- `api_errors.py` — 27 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + grant invariant checker
- `factories.py` — payload factories with unique sku/enrollment generators
- `constants.py` — price-level tiers, multipliers, core minimums, benefit tier thresholds
- `test_users.py` — `TEST_USERS` for the 4 roles + `make_customer_admin_headers(user_id)` builder for the entity-backed `CustomerAdmin` role
- `fixtures.py` — composite helpers: `setup_active_agreement_with_anniversary`, `setup_report_in_state` (full DRAFT→SETTLED lifecycle), `setup_settled_report_with_ratified_baseline`, `setup_agreement_in_renewal_pending`, `setup_expired_agreement`, `setup_snapshot_context`

**test_suite/**: `conftest.py` + 8 test files, **77 tests, all collected cleanly**.

## Coverage
- **§1.8 queue A (Difficulty):** 18/18 instances, each with exactly 2 tests → 36 difficulty-tagged tests
- **§1.9 queue B (Corner):** 41/41 non-stub instances (no `excluded_because:` stubs exist in this index), each with ≥1 test → 41 corner-tagged tests

## Instances skipped
None — every design-index instance passed the PRD-first two-condition filter (all asserted rules have verbatim PRD coverage and unique derivability).

## Self-check results
- Tag audit: 0 unknown tags; every difficulty instance has exactly 2 tests, every corner instance ≥1
- Per-test audit: all 77 test functions have exactly one `Design:` tag as the final docstring line
- PRD citation audit: all quoted citations verbatim-grep against `workspace/PRD.md` (0 mismatches)
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere
- All files compile; `pytest --collect-only` collects 77 tests with zero errors

One judgment call worth noting: `renew_stale_version_occ_conflict` uses `validate_error_is_one_of([ERR_STALE_VERSION, ERR_INVALID_STATE])` for the second renew — the recipe itself allows both outcomes (the second attempt from RENEWED hits the state check, not the OCC check), matching the instance's own `assert:` text.

## Step 6: Generate Implementation — 2026-09-30T16:03:22.490Z

(First attempt terminated early on an upstream API error before writing anything; rerun from scratch in foreground.)

Done. Complete implementation for task_3252 generated and verified.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3252_enterprise_agreement_true_up_license_position_assurance/workspace/implementation/`:

- `start.sh` — guarded pip install (no-op when flask present), `exec python3 app.py`, PORT env (default 10000), binds 0.0.0.0
- `requirements.txt` — flask
- `app.py` — blueprint registration, ApiError/HTTP error handlers
- `db.py` — in-memory dict stores (empty at boot, no seeding), logical clock fixed at `2026-09-01T00:00:00Z` until `set_current_utc`
- `helpers.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10/min 1/max 100), `created_at`/`updated_at`/`version` stamping
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), role RBAC (403), CustomerAdmin entity-backed ownership (X-User-ID == Organization.id, 403)
- `services.py` — price-level tiering (A<250<=B<2400<=C<6000<=D, multipliers 1.00/0.95/0.90/0.85 round-half-up), core normalization (ceil per server, min 16/host, min 8/VM, PER_VM capped at host demand), true-up proration ((12-months+1)/12 round-half-up per line, then summed), benefit accrual tiers ($500k/$2M vouchers+incidents, $5M upgrade right, +365 days expiry), cloud waterfall (partial consumption, EXHAUSTED at zero), step-up delta (floored at 0), grant-expiry sweep, terminal sweep (grants FORFEITED, commitments EXPIRED)
- `routes/` — 14 modules: clock_orgs, agreements, products, anniversaries, entitlements, stepups, deployments, snapshots, trueup, trueup_transitions, benefits, cloud, hosting, shortfall

**Endpoint count: 74** (all from SCAFFOLD §1.5, including the clock endpoint and all 9 flat filtered lists).

**Boot verification:** fresh-process boot on two separate ports succeeded; list endpoint returns correct envelope with empty data and pagination meta (logical clock reads exactly `2026-09-01T00:00:00.000Z` at startup). A 56-check end-to-end verification script passed 100%, covering: tiering/price locks, duplicate errors, activation window, anniversary sequencing, scope mismatch, hosting authorization gate + full PENDING_REVIEW/APPROVED/SUSPENDED/REVOKED cycle, core normalization (PER_VM/PER_HOST), snapshot shape (no `version` on append-only records), full true-up lifecycle with pinned snapshot/repricing/revision loop/settle ratification, OCC 412 on both renew and entitlement PATCH, review lock, step-up charge arithmetic, benefit redemption/depletion/expiry, cloud waterfall partial + EXHAUSTED + expiry rejection, renewal window + terminal sweeps, and shortfall assessment (subscription zero coverage after expiry). Test suite was not run per the isolation rule.

## Step 7: Run Tests and Iterate — 2026-09-30T16:19:15.153Z

All 8 rounds pass 77/77. Clean sweep achieved.

## Summary

- **Iterations run:** 3 sweeps (1 baseline + 2 fix rounds; final sweep clean).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `fixtures.py` — added missing `create_benefit_grant_payload` import (was called in `create_benefit_grant` but never imported → NameError in 12 tests).
  - `constants.py` — `TEST_DEFAULTS["DEPLOYMENT_DATE"]` changed from `"2026-09-02"` to `"2026-09-01"`. PRD §3.3 rejects a deployment date in the future of the logical clock (fixed at startup to 2026-09-01T00:00:00Z); the old default was one day ahead and caused `ERR_INVALID_DATE_RANGE` in 30 tests. The implementation was PRD-faithful; the fixture was the bug.
  - `fixtures.py` — three inline deployment-date defaults in `create_user/device/server_deployment` changed from `"2026-09-02"` to `"2026-09-01"` (same reason).
  - `fixtures.py` — `setup_agreement_in_renewal_pending` gained `grants=` / `commitments=` parameters, creating benefit grants and cloud commitments while the agreement is still ACTIVE (PRD §3.1 gates both creations on ACTIVE; creating them after the agreement enters RENEWAL_PENDING must be rejected with `ERR_AGREEMENT_NOT_ACTIVE`).

- **Fixes applied to `test_suite/`:**
  - `test_02_agreement_lifecycle.py` — `test_decline_renewal_continue_returns_to_active` and `test_non_renewal_cascade_grants_forfeited_commitments_expired` now create their grant (and commitment) via the new fixture parameters while the agreement is ACTIVE, instead of issuing creation calls against a RENEWAL_PENDING agreement that the PRD-faithful implementation correctly rejects.
  - `test_05_true_up_reports.py` — `test_settle_cascade_entitlement_baseline_anniversary_closure_benefit_accrual` had a unit-scale bug: PRD §3.7's first accrual tier starts at five hundred thousand **dollars** (= 50,000,000 cents), but the test settled a report totaling 600,000 cents ($6,000) and asserted 5 vouchers accrued. Rescaled to deployment_users=505 / entitlement_qty=5 → settled total exactly 50,000,000 cents (the inclusive lower tier boundary), so the 5-voucher/1-incident assertion is PRD-correct.
  - `test_06_deployments_and_hosting.py` (3 places) and `test_04_license_position.py` (1 place) — inline `"deployment_date": "2026-09-02"` changed to `"2026-09-01"` (same future-date fixture bug). The deliberate future date `"2026-09-05"` in `test_clock_default_is_2026_09_01` was left untouched.

- **Fixes applied to `implementation/`:** none — every failure traced to test/fixture artifacts; the implementation's checks (future-date rejection, ACTIVE-only grant/commitment creation, dollar-denominated benefit tiers) all matched PRD verbatim.

**Final state: 77/77 passing in all 8 parallel rounds.** Orchestrator independently re-ran the full 8-round sweep after the subagent exited: 77/77 × 8 rounds, 0 failures.

## Step 8: Finalize PRD — 2026-09-30T16:22:08.810Z

Done. One edit, scoped to the single genuine PRD silence the Step 7 diff exposed.

## Summary

**Line counts:** PRD.md 319 lines, PRD_FINALIZED.md 319 lines (0% line delta; one inline revision within §3.7, character count grew on that one line only).

### Changes

- **§3.7 — revise — pinned the benefit-accrual tier thresholds in integer cents alongside the dollar denominations:** "five hundred thousand dollars" → 50,000,000 cents, "two million dollars" → 200,000,000 cents, "five million dollars" → 500,000,000 cents. The settled total is `total_amount_cents`, and the PRD's bare dollar phrasing left the unit conversion implicit — exactly the ambiguity that produced the Step 7 unit-scale bug in `test_05_true_up_reports.py`. — `implementation/services.py:114-120` (thresholds `< 50_000_000`, `< 200_000_000`, `>= 500_000_000`).

All other `<step_7_diff>` items were pure test/fixture bugs where the PRD already pins behavior verbatim, so no edits were made for them:
- Future deployment-date rejection — PRD §3.3 already says "The deployment date must not lie in the future of the logical clock"; impl `routes/deployments.py:37-38` matches; the old fixture default of 2026-09-02 was one day ahead of the §2.5 startup clock (2026-09-01), a fixture bug only.
- Grant/commitment creation gated on ACTIVE — PRD §3.1 already lists "granting benefits, creating commitments" among ACTIVE-gated operations rejected with `ERR_AGREEMENT_NOT_ACTIVE`; impl `routes/benefits.py:27-28` and `routes/cloud.py:27-28` match.
- Logical clock startup value — PRD §2.5 already pins 2026-09-01T00:00:00Z; impl `db.py:6-7` matches.

### Per-edit pre-edit search log

**Edit 1 (§3.7 tier thresholds):**
- (a) Subject: the monetary thresholds governing software-assurance benefit accrual at true-up settlement, and the unit (cents vs dollars) in which the settled `total_amount_cents` is compared against them.
- (b) Impl paths enumerated (via `grep -rn "50_000_000\|200_000_000\|500_000_000\|accrue_benefits"`): `services.py:112-138` `accrue_benefits` (the only definition of the thresholds, plus grant row creation with `expires_on` = logical clock date + 365 days, matching the PRD's existing sentence); its two callsites — `routes/trueup_transitions.py:114` (settle transition, passing `report["total_amount_cents"]`) and the import in `routes/trueup.py:10` (unused there). Confirmed no other endpoint or cascade touches these thresholds, and no other PRD section references the dollar figures.
- (c) Wording adjustment: none needed beyond the cent-denomination parentheticals; each cent value was attached directly to its dollar phrase (inclusive-lower-side semantics preserved, matching the final sentence "exactly five hundred thousand dollars enters the first tier" and impl's `elif < 200_000_000` / `>= 500_000_000` boundaries), so the existing prose about grant-row creation, expiry, and tier inclusivity remains accurate.

## Step 9: Complete PRD — 2026-09-30T16:28:41.299Z

(First attempt stopped after the analysis phase — file was copied but zero edits applied, detected via byte-identical diff; agent resumed to apply the enumerated edits.)

All 19 changed lines are in-paragraph edits (no sections added). Here is the required summary.

## Summary

**Source:** `PRD_FINALIZED.md` (319 lines, 54,262 chars) → `PRD_COMPLETED.md` (319 lines, 57,629 chars). Char-delta: **+3,367 chars**. No lines added or removed — every change is an in-paragraph insert/revision; no new sections.

**Counts:** 16 ambiguity-pins, 3 mismatch-revisions (19 changed paragraphs total).

### Changes

- §2.3 Pagination — insert — ambiguity — pinned `offset >= 0`, 400 on non-integer/out-of-range pagination params, `has_more` = `offset + limit < total_count`, and `id`-ascending tie-break after `created_at` — implementation/helpers.py:82-114
- §2.4 Resource Identity — revise — mismatch — fixed the garbled "Two resource kinds" sentence to the actual four append-only kinds (snapshot, redemption, consumption event, shortfall assessment) — implementation/helpers.py:117-123, routes/snapshots.py:27, routes/benefits.py:99, routes/cloud.py:99, routes/shortfall.py:73
- §2.4 — insert — ambiguity — pinned initial `version` = 1 and `updated_at` = `created_at` at creation; true-up lines are versioned resources — implementation/helpers.py:117-123, routes/trueup.py:150
- §2.5 Logical Clock — insert — ambiguity — malformed/missing `to_iso8601` → `ERR_INVALID_REQUEST` 400; naive instants interpreted as UTC — implementation/routes/clock_orgs.py:18-22, db.py:14-22
- §2.1 RBAC — insert — ambiguity — flat list endpoints silently filter records to the CustomerAdmin's own organization rather than rejecting — implementation/middleware.py:53-57
- §2.9 Validation Ordering — revise — mismatch — on agreement-nested endpoints the `ERR_AGREEMENT_NOT_ACTIVE` gate fires immediately after the path agreement resolves, before body references (impl checks ACTIVE before product/anniversary resolution everywhere) — implementation/routes/entitlements.py:30-36, anniversaries.py:17-20, deployments.py:23-29, snapshots.py:35-43, trueup.py:48-56, benefits.py:27-30, cloud.py:27-30, hosting.py:29-33
- §3.1 Agreement creation — revise — mismatch — zero-length span (`end_date` == `start_date`) is accepted; only `end_date < start_date` is rejected (PRD had said "at least one day") — implementation/routes/agreements.py:35-36
- §3.2 Product catalog — insert — ambiguity — `annual_unit_price_cents` must be an integer ≥ 0, else `ERR_INVALID_REQUEST` 400 — implementation/routes/products.py:25
- §3.2 Entitlement adjustment — insert — ambiguity — new `quantity` must be a non-negative integer (400, checked before the baseline floor) — implementation/routes/entitlements.py:95-100
- §3.3 Deployment retirement — insert — ambiguity — retiring an already-retired deployment is permitted and increments `version`; `include_retired` compared case-insensitively — implementation/routes/deployments.py:130, 140-150
- §3.4 License position — insert — ambiguity — snapshot `lines` order products by first appearance among qualifying deployments — implementation/services.py:66-69
- §3.5 True-up lines — insert — ambiguity — line-add on a non-`DRAFT` report → `ERR_INVALID_STATE` 409; a product absent from the pinned snapshot's lines yields `growth_quantity` 0 — implementation/routes/trueup.py:120-121, 132-137
- §3.5 True-up report lists — insert — ambiguity — agreement-scoped report list accepts a `status` filter; flat report list filters by `agreement_id`/`anniversary_id` — implementation/routes/trueup.py:92-94, 105-109
- §3.5 Settlement — insert — ambiguity — a line whose product has no matching entitlement under the agreement ratifies nothing and creates no entitlement — implementation/routes/trueup_transitions.py:101-107
- §3.6 Renewal — insert — ambiguity — renew rejected with `ERR_INVALID_STATE` 409 when the clock has passed the current `end_date`; `new_end_date` on/before `end_date` → `ERR_INVALID_DATE_RANGE` 422 — implementation/routes/agreements.py:95-98
- §3.6 Expiry — insert — ambiguity — expiry attempt on or before `end_date` → `ERR_INVALID_STATE` 409 — implementation/routes/agreements.py:137-138
- §3.7 Manual grants — insert — ambiguity — `expires_on` accepted without temporal constraint, even a past date — implementation/routes/benefits.py:34-37
- §3.8 Cloud commitments — insert — ambiguity — `expires_on` unconstrained at creation; consumption validates `requested_cents` (400) before the expiry/status checks; event against an already-terminal commitment → `ERR_INVALID_STATE` 409 — implementation/routes/cloud.py:34-37, 81-90
- §3.9 Step-up execution — insert — ambiguity — insufficient source `quantity` at execute → `ERR_INVALID_STATE` 409 — implementation/routes/stepups.py:110-111
- §3.10 Hosting authorization — revise — ambiguity (ordering) — creation checks `effective_on` (date-range) before `license_mobility`, reversing the PRD's prose order to match impl — implementation/routes/hosting.py:42-46

Output file: `workspace/PRD_COMPLETED.md`

**Post-Step-9 integrity check:** implementation/*.py mtimes all ≤ 15:55, before the final clean 8-round sweep (16:16–16:19) — Steps 8/9 edited PRD files only, sweep remains valid. PRD_COMPLETED.md verified on disk: 57,629 chars, differs from PRD_FINALIZED.md.
