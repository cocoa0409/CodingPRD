# Worklog — task_3296_government_reseller_contract_vehicle_schedule_pricing_compliance

## Step 1: Create Task Directory — 2026-09-30T18:10:29.000Z

Pre-allocated task directory confirmed in place: `tasks/task_3296_government_reseller_contract_vehicle_schedule_pricing_compliance/workspace/`. No new index computed (directive: use exactly this path).

## Step 2: Generate Scaffold — 2026-09-30T18:26:00.000Z

All three files parse as YAML, lint is clean, and the structural counts exceed expert-level targets.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3296_government_reseller_contract_vehicle_schedule_pricing_compliance/`):

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 1605 | `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 677 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 499 | `scaffold_corner_design` only |

**§1.1–§1.7 counts (SCAFFOLD.yaml):**
- 13 entities (Manufacturer, ManufacturerAgreement, ContractVehicle, PriceList, PriceLine, TeamingArrangement, TeamingScope, Order, Invoice, Dispute, SalesReport, ComplianceAudit, PriceModification)
- 10 state machines — non-linear: Order uses **parallel dimensions** (compliance × billing); PriceList exhibits a **cycle** (DRAFT→SUBMITTED→ACTIVE→DRAFT via reopen); ManufacturerAgreement posture-driven gating
- 4 OCC concurrency rules (`price-modification-stale-list`, `agreement-update-stale-version`, `vehicle-update-stale-version`, `order-cancel-stale-version`), each 412-guarded
- 9 calculations — includes dual-variant MFC floor (FED vs STATE_COOP cap), dual-variant TAA origin evaluation (manufacturer-attested vs line-evidence), combinatorial teaming surcharge (nested min/max/floor/cap), per-line-rounding order pricing, posture derivation, PRC accumulator, ceiling consumption, SB-goal attainment, audit materiality
- 22 ordered validations across all 6 categories
- 77 endpoints (incl. 3 reverse-FK GETs added during lint iteration, `/_clock/set_current_utc` with mandatory `2026-09-01T00:00:00Z` default)
- 26 error codes
- 7 roles with `identity:` field on each — segregation-of-duties model (Auditor opens/issues but cannot close; PriceModification creator cannot approve)

**§1.8 instances:** 18 (9 rules × 2) — all §0.5 differentiation clauses honored: dual variants on different entity domains (Order TAA vs PriceLine MFC), combinatorial formulas in different modes ((a) min/max nested vs (b) per-line rounding), non-linear machines on different entities (Order parallel vs PriceList cyclic), transitive cascades of depth 4 and 2 from different triggers, priority-pair conflicts on different category pairs (state×fiscal vs safety×referential), boundary precision on different metrics/endpoints, cross-entity dependencies on different pairs (Order×Agreement vs Vehicle×Manufacturer), temporal overlap with different interval semantics (range vs set-membership), compensating invariants on different conserved quantities (dispute ledger vs sales report total).

**§1.9 instances:** 25 across 8 sections (entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_complexity_layers).

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes on the path: initial run had 16 violations (15 FK reverse-reachability + 1 sentinel role). Fixes: set `api_prefix: ""` (the lint derives collection segments only for paths under the prefix; with empty prefix all top-level paths qualify), added 3 sub-resource reverse-FK GETs (`/vehicles/{id}/teaming-scopes`, `/price-lists/{id}/orders`, `/teaming/{id}/orders`), and replaced the `__NO_ROLE__` sentinel with a normal role + a comment that the header is omitted.

## Step 3: Copy Shared Files — 2026-09-30T18:26:56.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3296_government_reseller_contract_vehicle_schedule_pricing_compliance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T18:33:51.000Z

Note: the first subagent turn exited after only planning (8 tool calls, no file written — PRD.md missing). Orchestrator verified absence on disk and resumed the same agent, which then completed the work. Verified on disk: PRD.md = 385 lines, begins with `# Government Reseller Contract Vehicle and Schedule Pricing Compliance API — Product Requirements Document`, ends with the §5 error table (`ERR_PERIOD_NOT_CLOSED | 422`).

Subagent's returned summary (verbatim):

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3296_government_reseller_contract_vehicle_schedule_pricing_compliance/workspace/PRD.md`
**Line count:** 385 lines

### Per-section coverage

- **§1 Introduction** — three paragraphs covering system goals, regulated-resale drivers, and the segregation-of-duties / OCC / logical-clock pillars.
- **§2 Global Specifications** — ten subsections:
  - 2.1 RBAC with `X-User-ID` / `X-User-Role`, all 7 roles spelled exactly, opaque identity per role, with `ERR_MISSING_AUTH_HEADERS` and `ERR_UNAUTHORIZED` referenced.
  - 2.2 API Response Structure emitted verbatim from `section-2.2-response-structure.md` (placeholders `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, empty `data` preserved byte-for-byte).
  - 2.3 Pagination (limit default 10 / min 1 / max 100 / offset 0; `created_at` ascending; four `meta` fields).
  - 2.4 Resource identity, timestamps, versioning; explicit note that `PriceLine` and `TeamingScope` lack `updated_at` and `version`.
  - 2.5 Logical clock (starts 2026-09-01T00:00:00Z, lazy evaluation, `to_iso8601` / `current_utc`).
  - 2.6 Agreement posture derivation (negative 100000-cent threshold, inclusive boundary).
  - 2.7 Precision and round-half-up, per-line-then-sum ordering.
  - 2.8 OCC — all four concurrency rules with exact `expected_*_version` field, error id, and 412 status; `ERR_STALE_VERSION` backstop noted.
  - 2.9 Hierarchy and left-to-right path validation, `ERR_NOT_FOUND` vs `ERR_FK_NOT_FOUND`.
  - 2.10 Validation pipeline: all 22 validations enumerated in priority order with their error ids and HTTP statuses.
- **§3 Business Logic** — nine subsections (manufacturer/agreement, vehicles, price lists/MFC, price modifications/PRC, teaming, orders, TAA variants, invoices/sales-reports, disputes/posture/audits/termination). All 10 state machines' transitions expressed with preconditions and side effects; all 9 calculations rendered as precise business prose (no pseudocode, no fuzzy words); all cascades (agreement suspend/terminate, vehicle expire, audit finding) listed. No paths or HTTP methods inside §3.
- **§4 Endpoint Definitions** — 77-row table with Method / Path / Description / Authorized Roles columns only; status-code paragraph (201 for create, 200 for modify) above the table.
- **§5 Error Code Catalogue** — 26-row table with Error ID / HTTP Status Code columns only.

### Hard-contract reports

```
Field coverage check:
- entities[].fields + endpoints input/output union: 74 required, 74 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 22 enumerated in priority order in §2.10 with category, error_id, status, and scope
- concurrency_rules[] OCC rejections: 4 named with write op + occ field + error id + 412 (§2.8)
- state_machines[].transitions: all expressed (agreement 4, vehicle 4, price-list 5, teaming 4, order 7, invoice 3, dispute 3, sales-report 1, audit 3, price-modification 2) with preconditions and side effects
- calculations[]: 9 expressed in prose (order_pricing, teaming_surcharge, mfc_floor + 2 variants, taa_origin_evaluation + 2 variants, prc_accumulator, posture_derivation, sb_goal_attainment, audit_mfc_variance, ceiling_consumption) with all numeric constants embedded (0.30, 0.015, 500000, 0.25, -100000, 250000, statutory 12-country list)
- validations[] conditions: all 22 matchable to error_id via §2.10 + §3 narratives
- endpoints[].side_effects / applies_to: cascades, PRC recompute triggers, sales-report upsert, posture recompute all surfaced in §3
- entities[].fields[] structured content: defaults (taa_required=true, designated_countries=[], sold_qty=0, subcontract_cents=0, origin_flag=NOT_APPLICABLE, posture=GOOD_STANDING), enum sets, and uniqueness constraints all placed on owning entity in prose
- sibling-branch symmetry: dispute-resolution three branches (CREDIT / DEBIT / REJECT) and audit-close two branches (OPEN / FINDING_ISSUED) rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 516
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three hard contracts PASS. PRD.md ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-09-30T18:51:06.000Z

Orchestrator disk verification: all 9 test_helpers files + conftest.py + 15 test files present; `py_compile` clean on all; 68 `def test_` functions and exactly 68 `Design:` tags (1:1).

Subagent's returned summary (verbatim):

68 tests collected cleanly. Done.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3296_government_reseller_contract_vehicle_schedule_pricing_compliance/`):

test_helpers/ (1307 lines):
- `types.py` (337) — 13 status/type enums + 15 entity TypedDicts; PriceLine and TeamingScope correctly omit `updated_at`/`version` per PRD §2.4
- `api_client.py` (296) — `ApiClient(GenericApiClient)` with 81 methods, one per PRD §4 endpoint
- `api_errors.py` (66) — 26 `ApiErrorId` values with PRD §5 HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (157) — per-entity assertions (append-only entities assert absence of `updated_at`/`version`)
- `factories.py` (148), `constants.py` (38), `test_users.py` (45), `fixtures.py` (190) — composite chain builders (active chain, cleared/delivered orders, approved teaming, ON_HOLD driver, finalized reports)
- `__init__.py` (30) — barrel export

test_suite/ (1886 lines): `conftest.py` (45) + 15 test files, **68 tests total**, all collecting cleanly.

**Test counts per source:**
- Queue A (Difficulty): 43 tests across 17 of 18 instances (each covered instance has ≥2 tests)
- Queue B (Corner): 25 tests, one per each of the 25 non-stub instances

**Instances skipped (1):**
- `Difficulty/priority_pair_validation_conflict/business_safety_vs_business_posture... ` — specifically `business_safety_vs_business_referential_conflict_on_order_create`: the PRD's posture gate (§2.10 item 8) applies to "order submission, vehicle authorization, and teaming approval" — not order creation, where §2.10 item 14 (pinned list active) governs. The recipe's asserted outcome (ERR_AGREEMENT_NOT_GOOD_STANDING fires on POST /orders before ERR_PRICE_LIST_NOT_ACTIVE) is not uniquely derivable from the PRD; a faithful PRD-only implementer would return ERR_PRICE_LIST_NOT_ACTIVE. Skip reason documented in the header of `test_05_validation_ordering.py`.

**Clock check:** all recipe dates (2026-01/06/08/09/10/11, 2027-01) are reachable from the 2026-09-01T00:00:00Z logical-clock start; the vehicle-window recipe's authorize step runs at clock 2026-06-01 (inside the [2026-01-01, 2026-10-01) window) before advancing to the exclusive boundary — matches PRD §2.5/§3.2.

**Design-tag audit:** every test docstring carries exactly one `Design: Difficulty/...` or `Design: Corner/...` line as its final line; all 68 tags resolve to real instance names in the source yamls (0 unresolved). No `skip`/`skipif`/`xfail` markers; no scaffold/§1.x/Table-N references in generated code. PRD-citation sweep: 97 quoted passages across all docstrings, 100% verbatim-match PRD.md (whitespace/backtick/bold-insensitive grep).

## Step 6: Generate Implementation — 2026-09-30T19:08:10.000Z

Orchestrator disk verification (independent of subagent claims): 17 files present under workspace/implementation/ (incl. executable start.sh with guarded pip install + `exec python3 app.py`); all .py files pass `py_compile`; routes use `@app.get/post/patch/...` decorators — exactly 77 registrations, 77 unique method+path pairs (matches scaffold's 77 endpoints). ISOLATION RULE held: subagent never touched test_suite//test_helpers/ or the design yamls.

Subagent's returned summary (verbatim):

Implementation complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3296_government_reseller_contract_vehicle_schedule_pricing_compliance/workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 10 |
| `requirements.txt` | 1 |
| `app.py` (entry: imports server_core + routes, runs 0.0.0.0:$PORT) | 7 |
| `server_core.py` (Flask app, global RLock gate, envelope error handlers) | 51 |
| `db.py` (in-memory stores, empty at boot, logical clock init `2026-09-01T00:00:00.000Z`) | 27 |
| `errors.py` (all 26 error IDs from the catalog) | 54 |
| `util.py` (envelope, pagination, ISO-8601 parse/format, entity helpers) | 161 |
| `middleware.py` (X-User-ID/X-User-Role auth + full RBAC route table) | 141 |
| `rules.py` (9 calculations: order_pricing, teaming_surcharge, mfc_floor with STATE_COOP 0.25 cap, dual-variant TAA, prc_accumulator, posture_derivation (-100000 threshold), sb_goal_attainment, audit_mfc_variance (250000), ceiling_consumption; cascades; lazy EXPIRED/OVERDUE) | 354 |
| `routes/admin.py` (clock + manufacturers) | 74 |
| `routes/agreements.py` | 196 |
| `routes/vehicles.py` | 186 |
| `routes/pricing.py` (price lists, lines, modifications, SoD, OCC) | 263 |
| `routes/teaming.py` | 153 |
| `routes/orders.py` (parallel compliance/billing dimensions) | 191 |
| `routes/billing.py` (invoices + disputes/ledger) | 186 |
| `routes/reporting.py` (sales reports + audits) | 159 |

Total: 2214 lines. All 16 Python files pass `python3 -m py_compile`.

**Endpoint coverage: 77/77** — the middleware RBAC table has 77 method+path entries and the Flask url_map has exactly 77 rules, matching the scaffold's 77-endpoint table.

**Boot smoke test:** `PORT=<port> bash start.sh` boots cleanly in under 3s. Verified: 401 without auth headers, 403 for undeclared role, 200 envelope for `GET /manufacturers` with PlatformAdmin headers (correct `meta`/`response_type`/`data` shape with `limit`/`offset`/`total_count`/`has_more` on lists). Full workflow exercised end-to-end: manufacturer → agreement activate → vehicle authorize → price list submit/activate (MFC floor, TAA, scope) → order create (per-line round-half-up totals) → submit (auto-CLEARED with manufacturer-attested TAA) → deliver (ceiling check, sold_qty, PRC recompute = 4000) → invoice (amount = total + surcharge, logical-clock issued_at, due_at = +30 days) → pay → sales-report totals and sb_goal_met all correct.

**Notes:**
- One bug found and fixed during self-verification: `python3 app.py` runs as `__main__`, so routes importing `from app import app` registered on a second Flask instance. Resolved by moving the app object into `server_core.py`.
- Fixed at exactly the killed PID only; no broad kill patterns used; no leftover listeners on test ports.
- Test suite was not run (isolation rule); no seeded entities — the store boots empty.

## Step 7: Run Tests and Iterate — 2026-09-30T19:24:00.000Z

Orchestrator disk verification: all 8 `results.{1..8}.json` present, each `passed: 68, total: 68, failed: 0` — clean 8-round sweep confirmed independently of the subagent's report.

Subagent's returned summary (verbatim):

All 8 rounds pass: 68/68 in every round. Clean sweep.

## Summary

- **Iterations run:** 2 sweeps (round 1: 64 failures; round 2 after fixes: all 8 rounds 68/68).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/factories.py` — `_next_duns()` formatted the `itertools.count` object instead of calling `next(_counter)`; caused `TypeError: unsupported format string passed to itertools.count.__format__` in 64/68 tests.

- **Fixes applied to `test_suite/`:**
  - `test_01_dual_variant_calculations.py` — `_make_taa_pair` built an unreachable precondition (an ACTIVE price list with BR-origin lines on a STATE_COOP vehicle, which PRD §3.3's activation-time TAA re-validation rejects). Split into `_make_fed_taa_chain` (FED order path unchanged) and `_make_state_coop_taa_chain` (list left SUBMITTED); rewrote `test_br_origin_fails_state_coop_blocks_order` → `test_br_origin_fails_state_coop_blocks_activation` asserting activation is rejected with `ERR_TAA_ORIGIN_VIOLATION` (PRD §3.3 + §3.7 statutory list verbatim-cover this), and `test_same_line_diverges_across_variants` now asserts divergence as FED clears / STATE_COOP activation rejected. No assertions weakened — the order-level BLOCKED-via-TAA path is unreachable per PRD because activation already gates origin.
  - `test_08_temporal_overlap.py` — `_vehicle_at_window_end` created the order after advancing the clock to `effective_to`, at which point the vehicle lazily expires and its list supersedes (order create then fails `ERR_PRICE_LIST_NOT_ACTIVE`). Moved `create_order` before the clock advance so the submit-time `ERR_OUTSIDE_VEHICLE_WINDOW` rule (PRD §3.6/§3.2) is what the test actually exercises.

- **Fixes applied to `implementation/`:**
  - `routes/pricing.py` `price_lists_activate` — replaced the sibling-ACTIVE `ERR_UNIQUENESS_VIOLATION` rejection with PRD §3.3's supersede semantics ("that sibling is atomically moved to SUPERSEDED and the vehicle's PRC accumulator is recomputed against only the newly active list"; also matches the scaffold's ACTIVE→SUPERSEDED sibling-activation transition).
  - `routes/orders.py` `orders_submit` — moved `assert_vehicle_window_open` before the vehicle-AUTHORIZED check so submission at/past `effective_to` yields `ERR_OUTSIDE_VEHICLE_WINDOW` (PRD §3.6) instead of `ERR_INVALID_STATE` after lazy expiry; lazy expiry still runs first so the vehicle flips to EXPIRED for the subsequent read (PRD §3.2).

Note: PRD §3.3 contains an internal contradiction (activation both rejects and supersedes on sibling-ACTIVE); I resolved it toward the supersede branch per the detailed side-effect sentence and the scaffold state machine — the branch three tests assert.

## Step 8: Finalize PRD — 2026-09-30T19:27:57.000Z

Orchestrator disk verification: PRD_FINALIZED.md exists (385 lines, same as PRD.md); `diff` shows exactly 5 revised lines (§2.10 item 21, §3.3 activation, §3.6 submission ordering, §3.6 screening, §3.7 TAA) matching the subagent's report; `find workspace/implementation -newermt <sweep time>` empty — no post-sweep implementation edits, sweep still valid.

Subagent's returned summary (verbatim):

All five edits are in place; exactly five lines changed, line count unchanged at 385 (0% delta). The task is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3296_government_reseller_contract_vehicle_schedule_pricing_compliance/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 385 lines, PRD_FINALIZED.md 385 lines (0.0% delta; 5 lines revised in place, no sections added).

### Changes

- **§3.3 (price-list activation)** — revise — removed the internal contradiction (activation both rejecting with `ERR_UNIQUENESS_VIOLATION` and superseding on sibling-ACTIVE); now unambiguously states that an already-`ACTIVE` sibling on the same vehicle is not an error and is atomically moved to `SUPERSEDED` in the same operation, with the PRC recompute running against only the newly active list — `implementation/routes/pricing.py:118-149` (`price_lists_activate`: sibling found at 140-142, superseded at 143-147, `recompute_prc` at 148; no uniqueness raise).
- **§2.10 item 21 (Uniqueness)** — revise — removed price-list activation from the `ERR_UNIQUENESS_VIOLATION` applicability list and pointed at §3.3's supersede semantics; DUNS and sales-report uniqueness retained verbatim — confirmed impl raises uniqueness only at `routes/admin.py:33` (DUNS), `routes/reporting.py:39` (sales report), plus two pre-existing off-scope sites left untouched (`routes/agreements.py:113`, `routes/billing.py:45`).
- **§3.6 (order submission)** — revise — pins the Step-7-fixed check ordering in `routes/orders.py:108-139`: lazy vehicle expiry (`maybe_expire_vehicle`, line 114) runs first and persists even on failed submission; the window check (`assert_vehicle_window_open`, line 115) precedes the vehicle-state check (line 116), so submission at/past `effective_to` yields `ERR_OUTSIDE_VEHICLE_WINDOW` rather than `ERR_INVALID_STATE`; also pins that a failed TAA evaluation at submission raises `ERR_TAA_ORIGIN_VIOLATION` and leaves the order in `DRAFT` with `origin_flag` recording the failure (lines 130-133).
- **§3.6 (screening resolution)** — revise — removed the claim that a `TAA_FAIL` origin moves the order `SCREENING → BLOCKED`; impl only ever sets `BLOCKED` from the buyer-tier check (`routes/orders.py:137` — sole BLOCKED write in the codebase). Buyer-tier-outside-tiers still produces `BLOCKED` as before.
- **§3.7 (TAA)** — revise — replaced "a failing evaluation ... forces the order's screening outcome to `BLOCKED`" with the impl behavior: `TAA_FAIL` surfaces as `ERR_TAA_ORIGIN_VIOLATION` at submission, the order stays `DRAFT` with `origin_flag = TAA_FAIL`, and no `BLOCKED` transition occurs (`routes/orders.py:130-133`).

The `test_helpers/factories.py` `_next_duns()` fix was a pure fixture bug — no PRD edit.

### Per-edit pre-edit search log

1. **§3.3 supersede edit** — (a) subject: sibling-ACTIVE behavior at price-list activation. (b) enumerated: `routes/pricing.py:118-149` (activate), grep for `ERR_UNIQUENESS_VIOLATION` across all impl files (admin.py:30,33; agreements.py:113; reporting.py:39; billing.py:45; pricing.py import-only, never raised), `rules.py:recompute_prc` (sums only the ACTIVE list — consistent), `rules.py:expire_vehicle_cascade`/`cascade_terminate_agreement` (ACTIVE→SUPERSEDED cascades — consistent). (c) added "so at most one list per vehicle is `ACTIVE` at any time" to preserve the invariant's spirit without claiming a rejection, and scoped the PRC-recompute clause to match lines 143-148 exactly.
2. **§2.10 item 21 edit** — (a) subject: which endpoints raise `ERR_UNIQUENESS_VIOLATION`. (b) enumerated: same grep as above; verified agreement-activation uniqueness (agreements.py:113) and invoice uniqueness (billing.py:45) are pre-existing PRD silences outside the Step-7 scope. (c) wording narrowed only the price-list-activation claim; did not add agreement/invoice sites (out of scope) and did not assert exclusivity ("Applies to manufacturer creation and sales-report creation" mirrors original sentence structure).
3. **§3.6 submission-ordering edit** — (a) subject: order of lazy expiry, window check, and state check on submit. (b) enumerated: `routes/orders.py:108-139` (submit), grep for all `assert_vehicle_window_open`/`maybe_expire_vehicle` callsites (rules.py:229,234,241; vehicles.py:72,106-107,116,143,153,165,183; pricing.py:58,107,124; orders.py:43,114-115,148); checked `vehicles_authorize` (vehicles.py:94-110) where state check precedes window check but lazy expiry cannot fire from PENDING, so no conflict; confirmed test_08 expectation that the EXPIRED flip persists after the failed submit. (c) scoped the ordering pin to order submission explicitly ("Submission first touches the vehicle ... Submission then enforces the vehicle-window check before the vehicle-state check") so it does not constrain vehicle authorization, and noted the expiry persists, matching the test_08 read-back.
4. **§3.6 screening edit** — (a) subject: which screening failures produce `BLOCKED`. (b) enumerated: grep for `BLOCKED` across impl (rules.py:289 read-only; orders.py:137 sole write — buyer-tier only; orders.py:169 read-only); verified teaming ineligibility raises at submit (orders.py:125-126) before any transition, and origin failure raises at 132-133. (c) wording keeps the three-condition CLEARED rule intact, names buyer-tier as the BLOCKED cause, and states the origin path never reaches BLOCKED via submission; deliberately left the teaming clause un-renamed in the CLEARED conditions since the submission paragraph already pins the teaming re-check.
5. **§3.7 TAA edit** — (a) subject: consequence of `TAA_FAIL`. (b) enumerated: `routes/orders.py:130-133` (origin_flag set, bump, then raise), `rules.py:compute_origin_flag` (101-109) and `compute_origin_flag_for_origin` (116-121), `routes/pricing.py:133-135` (activation-time TAA raise — consistent with "enforced as a validation on order submission" wording since it speaks only to submission), plus the test_01 rewritten assertions (activation-level `ERR_TAA_ORIGIN_VIOLATION`). (c) removed "forces the order's screening outcome to `BLOCKED`" and spelled out the DRAFT-with-`TAA_FAIL` outcome so §3.7 no longer contradicts the revised §3.6.

## Step 9: Complete PRD — 2026-09-30T19:40:53.000Z

Orchestrator disk verification: PRD_COMPLETED.md exists (385 lines, source PRD_FINALIZED.md); `find` confirms ZERO `implementation/`, `test_helpers/`, or `test_suite/` files modified after the Step 7 clean sweep (19:23) — Step 8/9 edited PRD docs only, sweep remains valid (all 8 results.*.json still passed==total==68, failed==0). No sweep re-run required.

Subagent's returned summary (verbatim):

All changes are in place. Final report:

## Summary

**Source**: `workspace/PRD_FINALIZED.md` → `workspace/PRD_COMPLETED.md` (both 385 lines; char-delta +7,818, from 61,457 → 69,275 bytes; all edits are in-paragraph inserts/revisions, no new sections).

**Counts**: 22 ambiguity-pins, 9 mismatch-revisions (31 edited passages total).

### Changes (one bullet each)

- §2.1 — insert — ambiguity — blank `X-User-ID` treated as missing; undeclared method/path with a declared role yields `ERR_UNAUTHORIZED` (403) — middleware.py:131,136
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (never an error); non-integer values fall back to defaults — util.py:96-111
- §2.4 — revise — ambiguity — `version` starts at exactly 1 at creation — util.py:153
- §2.5 — insert — ambiguity — unparseable `to_iso8601` on clock-set yields `ERR_INVALID_PRICE_PERIOD` (422) — routes/admin.py:21
- §2.6 — revise — mismatch — posture threshold boundary flipped: exactly -100000 yields `GOOD_STANDING`, -100001 yields `ON_HOLD` (impl uses strict `<`) — rules.py:149; consistent with agreements.py:140
- §2.10 item 7 — revise — ambiguity — manufacturer-liveness check also applies to agreement reinstatement — agreements.py:139
- §2.10 item 8 — revise — ambiguity — posture gate also applies to vehicle reinstatement and teaming reinstatement — vehicles.py:131, teaming.py:138
- §2.10 item 14 — revise — ambiguity — pinned-list-ACTIVE check also applies at order submission — orders.py:122
- §2.10 item 21 — revise — ambiguity — uniqueness rule extended to malformed DUNS, agreement activation, and invoice issuance — admin.py:30, agreements.py:113, billing.py:45
- §3.1 (manufacturer) — insert — ambiguity — malformed DUNS yields `ERR_UNIQUENESS_VIOLATION` (409); manufacturer suspend requires `ACTIVE` else `ERR_INVALID_STATE` — admin.py:30,70
- §3.1 (agreement create) — revise — mismatch — removed the phantom `MFC_BASE_DISCOUNT` system floor and 0–0.5/0–1 range claims; percentages recorded as supplied, no creation-time range validation; invalid `scope_tiers` yields `ERR_SCOPE_VIOLATION` — agreements.py:44-45 (no such constant exists in impl)
- §3.1 (activate) — insert — ambiguity — non-DRAFT, bad term ordering, empty scope all yield `ERR_INVALID_STATE` (409); second ACTIVE agreement yields `ERR_UNIQUENESS_VIOLATION` (409) — agreements.py:103-113 (flagged site `agreements.py:113`)
- §3.2 (vehicle create) — insert — ambiguity — creation does NOT require agreement ACTIVE; malformed `buyer_tiers` yields `ERR_SCOPE_VIOLATION`; other fields recorded as supplied, window ordering checked only at authorization — vehicles.py:38-52
- §3.2 (authorize) — revise — mismatch — check order corrected to manufacturer-before-posture (per §2.10); `effective_from >= effective_to` yields `ERR_OUTSIDE_VEHICLE_WINDOW`; non-PENDING/agreement-not-ACTIVE yield `ERR_INVALID_STATE` — vehicles.py:97-107
- §3.2 (suspension) — revise — mismatch — suspended vehicle blocks submissions (`ERR_INVALID_STATE`) but does NOT block order creation (creation only requires the ACTIVE list); reinstatement failure yields `ERR_AGREEMENT_NOT_GOOD_STANDING` — vehicles.py:113-137, orders.py:47
- §3.3 (create) — revise — mismatch — price-list creation does NOT require an AUTHORIZED vehicle; line fields recorded as supplied (SKU scope/MFC/TAA enforced only at activation); `sold_qty` initialized to 0 — pricing.py:52-74
- §3.3 (submit) — insert — ambiguity — non-DRAFT / vehicle-not-AUTHORIZED / no lines all yield `ERR_INVALID_STATE` (409), after lazy vehicle expiry — pricing.py:104-111
- §3.3 (activate) — insert — ambiguity — non-SUBMITTED and vehicle-not-AUTHORIZED yield `ERR_INVALID_STATE` (409) — pricing.py:121-126
- §3.3 (reopen) — insert — ambiguity — reopen blocked by delivered/invoiced orders or non-ACTIVE status yields `ERR_INVALID_STATE` (409) — pricing.py:165-169
- §3.4 (propose) — insert — ambiguity — proposal allowed against a list in any status; `new_offered_price_cents`/`reason_code` recorded as supplied; unknown `sku` yields `ERR_FK_NOT_FOUND` (404) — pricing.py:194-215
- §3.4 (approve) — insert — ambiguity — non-PENDING mod / non-ACTIVE list yield `ERR_INVALID_STATE` (409); MFC check evaluated before SoD check — pricing.py:231-243
- §3.5 (create) — insert — ambiguity — `revenue_share_pct` range not validated; scope with unresolvable `vehicle_id` yields `ERR_FK_NOT_FOUND`; empty `sku_prefixes` yields `ERR_SCOPE_VIOLATION` — teaming.py:44-51
- §3.5 (approve) — insert — ambiguity — non-PROPOSED, agreement-not-ACTIVE, scope-vehicle-not-AUTHORIZED all yield `ERR_INVALID_STATE` (409) — teaming.py:104-116
- §3.5 (reinstate) — insert — ambiguity — reinstatement failure yields `ERR_AGREEMENT_NOT_GOOD_STANDING` (422) — teaming.py:138
- §3.6 (create) — insert+revise — ambiguity/mismatch — invalid `buyer_tier` yields `ERR_ORDER_LINE_INVALID`; teaming eligibility requires a SINGLE scope covering both vehicle and all SKUs; creation consults neither window, vehicle status, nor posture — orders.py:71-73, rules.py:248-256
- §3.6 (surcharge) — revise — mismatch — surcharge recomputed on EVERY price-mod approval against the pinned list for UNBILLED orders, regardless of price direction (PRD said "lower ... only") — pricing.py:251-254
- §3.6 (submit) — revise — mismatch — check order pinned as window → vehicle-state → posture → pinned-list → teaming (PRD listed list before posture); error names pinned (`ERR_INVALID_STATE`, `ERR_PRICE_LIST_NOT_ACTIVE`); version increments twice on success, once on TAA failure — orders.py:114-138
- §3.6 (deliver/cancel) — insert — ambiguity — delivery state failure yields `ERR_INVALID_STATE`; cancellation state failure yields `ERR_INVALID_STATE` and OCC check runs BEFORE the state check — orders.py:145, 166-170
- §3.8 (invoice) — insert — ambiguity — order not DELIVERED/CLEARED yields `ERR_INVALID_STATE`; existing non-VOID invoice yields `ERR_UNIQUENESS_VIOLATION` (409), checked before terms; invalid `payment_terms_days` yields `ERR_ORDER_LINE_INVALID`; malformed `period_label` yields `ERR_INVALID_PRICE_PERIOD` — billing.py:40-48 (flagged site `billing.py:45`)
- §3.8 (sb subcontract) — revise — ambiguity — period attribution pinned: order's delivery timestamp must precede period end, with no lower bound — rules.py:178-183
- §3.8 (pay/void/report) — insert — ambiguity — pay/void on wrong status yields `ERR_INVALID_STATE`; manual report starts zeroed with `sb_goal_met` true; malformed `period_label` yields `ERR_INVALID_PRICE_PERIOD`; finalizing non-DRAFT yields `ERR_INVALID_STATE` — billing.py:93,109, reporting.py:36-84
- §3.9 (disputes) — insert — ambiguity — `kind` recorded as supplied; missing/non-integer/zero `amount_cents` yields `ERR_ORDER_LINE_INVALID`; resolving non-OPEN dispute yields `ERR_INVALID_STATE`; invalid `outcome` yields `ERR_ORDER_LINE_INVALID` — billing.py:131-133,169-173
- §3.9 (reinstate) — insert — ambiguity — non-SUSPENDED yields `ERR_INVALID_STATE`; manufacturer inactive yields `ERR_MANUFACTURER_INACTIVE`; ledger below -100000 yields `ERR_AGREEMENT_NOT_GOOD_STANDING` — agreements.py:135-141
- §3.9 (finding) — insert — ambiguity — finding on a non-ACTIVE agreement leaves its status and downstream entities unchanged — reporting.py:137-142
- §3.9 (terminate) — insert — ambiguity — non-ACTIVE yields `ERR_INVALID_STATE`; a non-FINALIZED report blocks with the same `ERR_SB_GOAL_NOT_MET` and refreshes that report's `sb_goal_met` as a side effect — agreements.py:152-158

Both Step-8-flagged silence sites (`agreements.py:113`, `billing.py:45`) are now pinned. The most consequential mismatch fixes: the phantom `MFC_BASE_DISCOUNT` floor (never implemented), the posture threshold boundary (PRD's "inclusive" contradicted impl's strict `<`), the surcharge recompute trigger, the suspended-vehicle order-intake gate (creation is NOT blocked), and the double version bump on order submission.
