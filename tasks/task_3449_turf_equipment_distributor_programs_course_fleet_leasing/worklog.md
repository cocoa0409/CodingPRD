# Worklog — task_3449_turf_equipment_distributor_programs_course_fleet_leasing

## Step 1: Create task directory — 2026-10-02T05:27:00.000Z

Task directory pre-allocated by harness: `tasks/task_3449_turf_equipment_distributor_programs_course_fleet_leasing/` with `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T07:00:00.000Z

All artifacts are complete and verified. Final summary:

## Generated scaffold: task_3449_turf_equipment_distributor_programs_course_fleet_leasing

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3449_turf_equipment_distributor_programs_course_fleet_leasing/`):
- `SCAFFOLD.yaml` — 83,189 bytes (§1.0–§1.7; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 76,106 bytes (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 120,534 bytes (single key `scaffold_corner_design`)

**Design** ("much harder than expert", density-first; workflow_orchestration × pricing_engine, 4 complexity layers incl. OCC + cascading side effects + dual-variant calc + scheduled actions):
- **11 entities**: Distributor (channel-split EQUIPMENT/IRRIGATION), Technician, GolfCourse, EquipmentModel, Part (self-referential supersession graph), PartsOrder, FleetLease, LeaseUnit (absorbs remarketing), TradeInAppraisal, WarrantyClaim, IrrigationProject
- **40 endpoints** (held at the ≤40 ceiling deliberately), incl. `POST /turf/_clock/set_current_utc` (default 2026-09-01T00:00:00Z) and `POST /turf/admin/run_season_rollover` ops-run checkpoint
- **11 state machines** — cyclic machines on Distributor (review-driven standing), Technician (cert renewal), TradeInAppraisal (dispute rounds), WarrantyClaim (fork + dispute loop), LeaseUnit (reserve/expiry loop), IrrigationProject (design revision loop)
- **10 calculations** — dual variants on trade-in (BOOK 3,571,429 vs MARKET 2,773,125) and warranty labor (claimed vs factory allowance, min adjudication); combinatorial formulas in all three modes: (a) tier×seasonal×credit lease rate, (b) per-line-pinned incentive rounding (3,500 not 3,501), (c) pinned evaluation-order irrigation design fee
- **27 errors**, 13 ordered validation priorities (state→OCC→referential→temporal→safety→constraint→fiscal), 2 OCC concurrency rules (lease + claim transitions, `expected_*_version` on every call)
- **19 difficulty instances** (9 rules, ≥2 each; combinatorial has 3) — all formula-derived asserts pre-computed as literals (e.g., monthly rate 1,032,874; decay chain 1,309,000→1,232,021→floor 785,400; billing invariant 3,204,000 + 35,244,000 = 38,448,000)
- **41 active corner instances + 4 excluded stubs** across 8 claim-extraction sections

**Verification results** (all re-run after final edits):
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (615 calls scanned)
- All three files parse with `yaml.safe_load`; SCAFFOLD.yaml has neither design key; each design file has exactly its required top-level key
- CONST closure: 6 `CONST.*` names referenced across the three files, all defined in calculation `constants:` blocks
- Grounds resolution: 127 refs across both design files all resolve to declared §1.1–§1.7 elements; instance names unique across both files; every error code is exercised; excluded stubs cite real difficulty instances
- No forbidden concurrency vocabulary anywhere

Two authoring pitfalls hit and fixed en route (parse-checked after every append per process rules): YAML flow collections reject bare `field?` markers and unquoted `$.data[0].id` / `validations[priority=N]` tokens — all quoted and re-verified.

Orchestrator verification: all three files exist, parse with yaml.safe_load, correct top-level keys, on-domain (turf references present).

## Step 3: Copy shared files — 2026-10-02T07:02:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-10-02T07:25:00.000Z

The PRD is complete and passes all audits. Final summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3449_turf_equipment_distributor_programs_course_fleet_leasing/workspace/PRD.md` — **324 lines, 55,780 bytes**

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced. The document was written in 7 sequential chunks (Write + quoted-heredoc appends, so backticks survived intact), ending at §5 with no audit footer.

### Coverage self-audit (scaffold sections transcribed)

- **Entities (11/11):** Distributor, Technician, GolfCourse, EquipmentModel, Part, PartsOrder, FleetLease, LeaseUnit, TradeInAppraisal, WarrantyClaim, IrrigationProject — every field name appears in backticks; **Contract 1: 117/117 required identifiers present, 0 missing** (includes all endpoint inputs, query params, `to`, `level`/`expires_at`, `to_iso8601`, `current_utc`, `advanced_to`, `transitions_applied`, and line-element names `part_id`/`qty`/`model_id`).
- **State machines (11/11):** all 47 state values present verbatim; every transition's from/to, preconditions, and side effects expressed in prose — including the cyclic loops (certification renewal, lease spec-review revision, appraisal negotiation, claim re-review, reservation expiry), Cascade C1 (3 links: unit return → lease closure → course renewal) and Cascade C2 (3 links on the two failing standing transitions; explicit no-cascade on TERMINATED), and the strict `>` boundary on the 240-month model sales window.
- **Calculations (10/10):** all formulas in precise prose with evaluation order and pinned rounding — lease rate (1.15/1.08/1.00 tier multipliers, 1.06 spring factor for March/April/May, round-product-once-then-monthly-once), dual-variant trade-in (50 h/month norm, 84-month schedule, 15% floor, 60% base, 4,000-hour cap with 0.50 decay, condition multipliers 1.00/0.85/0.70/0.50), off-season incentive (Nov–Feb, 200,000/50,000-cent tiers at 12%/7%/3%, per-line round-then-sum pinned), warranty adjudication (min of two pricings, +10% parts handling as sole rounding step), compliance (365-day inclusive window, 0.92 inclusive fill boundary, vacuous 1.0), remarketing (55% base, 60% floor, 2% compounding decay, 7-day hold), irrigation design (ceil zones/8; 250,000 + 45,000/controller + 12,000/acre; GPD 22,000/16,000/20,000/18,000 by turf), spec compliance tier sets, billing progression with final-month absorption and INV-1 invariant, model aging.
- **Validations (13/13 priorities):** §2.8 enumerates the full priority order with per-tier error IDs and the first-failure-wins rule; each `applies_to` scope is named in the relevant §3 workflow.
- **RBAC (4/4 roles):** exact role spellings; per-role `identity:` translated (CorporateAdmin opaque; DistributorManager/IrrigationDealer entity-backed by Distributor; CourseManager entity-backed by GolfCourse, including the unit-lease-course and `reserved_by_course_id` ownership paths).
- **Endpoints (40/40):** §4 table rows match the scaffold exactly (verified programmatically, 0 missing / 0 extra); §3 is path-pure — **Contract 3: 571 backticked tokens scanned, 0 paths, 0 bare HTTP methods, 0 method+path combos**.
- **Errors (27/27):** all in the 2-column §5 table and each mentioned with its trigger context in §2/§3 prose.
- **Common fields / envelope / pagination:** §2.2 emitted byte-identical to the canonical source (verified); pagination defaults (limit 10, min 1, max 100, offset 0; `created_at` ascending with the `unit_seq` exception documented); clock default 2026-09-01T00:00:00Z with no wall-clock fallback; both OCC rules with `expected_lease_version`/`expected_claim_version`, exact error IDs, and HTTP 412.

**Contract 2 (Rule Coverage): PASS** — all six high-risk categories (priority ordering, OCC rejections, cross-entity cascades, applies_to scopes, field defaults/initials, sibling-branch symmetry) verified entry-by-entry against the scaffold.

**Hard contract reports:** Field coverage 117/117 PASS; Rule coverage PASS; Path purity 571 tokens / 0 violations PASS.

Orchestrator verification: PRD.md present (324 lines, 55,780 bytes), on-domain (turf prefix, 45 matches).

## Step 5a: Generate test helpers (Stage 1, frozen) — 2026-10-02T07:45:00.000Z

Stage 1 is complete and frozen. Summary:

## Files written

| Path | Bytes |
|---|---|
| `test_helpers/__init__.py` | 1,054 |
| `test_helpers/types.py` | 8,619 |
| `test_helpers/api_client.py` | 10,615 |
| `test_helpers/api_errors.py` | 2,876 |
| `test_helpers/assertions.py` | 12,588 |
| `test_helpers/factories.py` | 5,327 |
| `test_helpers/constants.py` | 5,344 |
| `test_helpers/test_users.py` | 2,640 |
| `test_helpers/fixtures.py` | 22,379 |
| `test_suite/conftest.py` | 942 |

No `test_*.py` files generated (Stage 2's job).

## Import smoke test (verbatim)

```
OK test_helpers
OK test_helpers.types
OK test_helpers.api_client
OK test_helpers.api_errors
OK test_helpers.assertions
OK test_helpers.factories
OK test_helpers.constants
OK test_helpers.test_users
OK test_helpers.fixtures
singleton binding OK; clock mirror = 2026-09-01T00:00:00Z
clock path check: set_current_utc posts to /turf/_clock/set_current_utc
```

Run via `importlib.import_module` per module (no `as`-binding tricks); the `ApiClient` class and `api_client` singleton resolve identically through both the submodule and the package barrel. `test_suite/conftest.py` also byte-compiles.

## Clock endpoint path

`/turf/_clock/set_current_utc` — **under** the `/turf` prefix in this task. Verified at SCAFFOLD.yaml line 1366 (`path: "/turf/_clock/set_current_utc"`) and PRD.md line 289 (§4 endpoint table); rollover at `/turf/admin/run_season_rollover` (SCAFFOLD line 1374, PRD line 290). `api_client.set_current_utc(to_iso8601, headers)` posts there and mirrors the reported `current_utc` into the `current_utc` property (startup default `2026-09-01T00:00:00Z` per PRD §2.5); `run_season_rollover(headers)` exposes the admin op. OCC params are explicit required args: `transition_lease(..., expected_lease_version, ...)`, `transition_warranty_claim(..., expected_claim_version, ...)`.

## Constants verification

`constants.py` carries **44 names** (32 distinctive PRD literals plus derived composites `CONDITION_MULTIPLIERS` / `GPD_PER_ACRE` / `SPEC_REQUIRED_TIERS`). Every numeric was diffed against PRD prose — a grep sweep over PRD.md confirmed each value verbatim: `PRD-OK` for all 32 probes (1.15 / 1.08 / 1.06 / 50-hour norm / 84-month / 15% floor / 60% base / 4,000-hr cap / 0.50 decay / 0.85 / 0.70 / 200,000 / 12% / 50,000 / 7% / 3% / 10% handling / 0.92 fill / 365-day window / 55% remarket / 2% decay / 7-day hold / 8 zones / 250,000 / 45,000 / 12,000 / 22,000 / 16,000 / 20,000 / 18,000 / 240 months / 2026-09-01T00:00:00Z). Tier sets and month tuples come from the PRD's named months (March/April/May; November–February) and PRD §3.4's tier-admission prose. No scaffold-only dead constants emitted.

## Other requirement confirmations

- **Roles**: CorporateAdmin opaque (shared constant canonical); `make_distributor_manager_headers` / `make_irrigation_dealer_headers` take a Distributor id, `make_course_manager_headers` takes a GolfCourse id; fixtures thread entity ids through these builders on every ownership-gated call.
- **Fixtures**: all preconditions built via PRD endpoints with `get_success_data` (lenient; 201 creates safe); the ONBOARDING→ACTIVE gate is honored (technician enrolled + certified + review, asserted ACTIVE).
- **validate_success**: untouched (framework default 200); fixtures never wrap creates in it, and `test_suite` creates in Stage 2 will need explicit 201 passing per the framework contract — noted for the Stage 2 handoff.

## Step 5b: Generate test suite (Stage 2) — 2026-10-02T08:25:00.000Z

Stage 2 is complete. Final report:

## Test files written (10 files, 79 tests, all under `test_suite/`)

| File | Bytes | Tests |
|---|---|---|
| test_01_auth_and_request_shape.py | 6,851 | 8 |
| test_02_distributor_standing.py | 11,536 | 8 |
| test_03_catalog_and_parts.py | 4,828 | 4 |
| test_04_parts_orders.py | 10,125 | 9 |
| test_05_lease_creation.py | 12,845 | 10 |
| test_06_lease_transitions_and_approval.py | 14,579 | 12 |
| test_07_appraisals.py | 6,122 | 4 |
| test_08_warranty_claims.py | 13,322 | 10 |
| test_09_fleet_turnover_and_remarketing.py | 11,965 | 8 |
| test_10_irrigation_projects.py | 7,980 | 6 |

## pytest collect-only output tail (verbatim)

```
tasks/task_3449_turf_equipment_distributor_programs_course_fleet_leasing/test_suite/test_10_irrigation_projects.py::test_interior_overlap_rejected
tasks/task_3449_turf_equipment_distributor_programs_course_fleet_leasing/test_suite/test_10_irrigation_projects.py::test_adjacent_window_allowed
tasks/task_3449_turf_equipment_distributor_programs_course_fleet_leasing/test_suite/test_10_irrigation_projects.py::test_irrigation_approve_stale_controller_reference_rejected

79 tests collected in 0.22s
```

## AST tag audit (real `ast` parse of every test_*.py, diffed against both YAML indices)

- Tags found: **79** (one per test; each is the last docstring line)
- Untagged tests: **0**; multi-tagged tests: **0**; tags not resolving to an instance: **0**
- §1.8 difficulty instances: **19/19 covered with ≥2 tests each** (38 tests)
- §1.9 corner non-stub instances: **41/41 covered with ≥1 test each** (41 tests)
- §1.9 stubs (`excluded_because`, 4): not translated, per spec; all four cross-references verified to resolve to real §1.8 instances (`trade_in_book_vs_market_divergence`, `state_beats_fiscal_on_lease_approve`, `referential_beats_temporal_on_lease_create`, `irrigation_halfopen_adjacency_allowed_overlap_rejected`), and no stub tags were emitted.
- Separate verbatim-citation sweep: all **120** quoted docstring spans (≥4 words) grep verbatim against `workspace/PRD.md` (whitespace-normalized). Zero failures.

## Skipped instances

None. Every non-stub instance in both queues passed the PRD-first two-condition filter and was translated.

## Adjudications made while translating (assertions narrowed to what PRD uniquely derives)

1. `warranty_claim_dispute_reopens_review_cycle` — assert final `version == created_version + 6` (relative) instead of the index's absolute `7`: PRD §2.4 pins initial version 1 only for FleetLease, not for claims; the six-transitions × "+1 per transition" claim (§3.8) is what PRD pins.
2. `part_create_defaults_support_status_active` — asserted only `support_status == ACTIVE`; dropped the index's `superseded_by_part_id is null` and `version == 1` asserts (PRD never states the part's initial version or the field's null-at-create presence).
3. `model_auto_discontinued_after_sales_window` — asserted the observable `ERR_MODEL_DISCONTINUED` on a new lease; dropped the direct `lifecycle_status == DISCONTINUED` read because PRD §4 declares no GET endpoint for EquipmentModel.
4. `order_cancel_voids_discount_and_releases_commitment` — asserted `CANCELLED` + `committed_parts_cents == 0`; dropped "order retains discount_cents == 3500" because PRD's "the order's `discount_cents` is voided along with the order" does not uniquely derive retention vs zeroing.

## Formula recomputation (hard requirement 5)

Every literal was recomputed from PRD prose with pinned evaluation order and round-half-up; **all matched the design index** — no disagreements: book 3,571,429 / market 2,773,125 (hours 2200, grade B, list 7,500,000); lease stack base 35,600,000 → total 40,754,880 (×1.08 ×1.06, rounded once) → credit 3,571,429 → net 37,183,451 → monthly 1,032,874; incentive per-line 1,750+1,750 = 3,500 (not 3,501) on subtotal 50,010 → total 46,510; irrigation 3 controllers / fee 1,825,000 / 2,640,000 gpd (BENTGRASS 120ac) and 985,000 / 800,000 (BERMUDA 50ac); claim min(56,000, 38,000) → payable 62,200, partial 43,200; billing 3×1,068,000 = 3,204,000 with net 38,448,000 conserved; remarketing 1,309,000 → floor 785,400 → 1,232,021 after three compounding 2% steps.

## Clock reachability

All dates derive from the fixed default `2026-09-01T00:00:00Z` via `/turf/_clock/set_current_utc`: 2027-01-15 (off-season submits), 2026-10-02/2026-10-10 (cycle-1 turnover; 7-day reservation hold lapses), 2026-12-01 (3 elapsed billing months), 2027-02-01 (cert expiry past 2027-01-01), 2028-10-01 (25-month unit age vs 24-month warranty, no rollover so cert standing untouched), 2046-10-01 (model age 241 > 240 months). Creates under test pass `validate_success(resp, 201)` explicitly; entity-backed roles use the `make_*_headers(entity_id)` builders throughout. No `test_helpers` files were modified; no helper bugs found.

## Step 6: Generate implementation — 2026-10-02T09:00:00.000Z

Implementation complete and verified. Final summary:

## Files written (all in `workspace/implementation/`)

| File | Bytes | Contents |
|---|---|---|
| `storage.py` | 1,389 | In-memory dict stores (11 entities), common-field record factory, no seeding |
| `clock.py` | 1,871 | Logical clock (default `2026-09-01T00:00:00Z`, no wall-clock fallback), month arithmetic |
| `helpers.py` | 7,500 | Envelope builders (`meta`/`response_type`/`data`), 27-id error catalog, auth P1–P3, pagination, validators |
| `calculations.py` | 10,644 | All 10 pinned calculations (Decimal, round-half-up at pinned steps only, exact-rational fill rate) |
| `distributors.py` | 6,477 | Distributors + compliance review (outcome mapping + Cascade C2) + technicians/certify |
| `catalog.py` | 6,566 | Courses, equipment models, parts, supersession graph with cycle walk |
| `parts_orders.py` | 6,948 | Order pipeline, off-season incentive, commitment ledger |
| `leases.py` | 9,622 | Lease create (unit expansion), lifecycle, OCC, approval economics |
| `units.py` | 5,691 | Unit lifecycle, duplicate-serial check, Cascade C1 closure, remarketing/reservations |
| `appraisals.py` | 5,611 | Dual-variant trade-in valuation, negotiation loop, revert compensation |
| `warranty.py` | 6,695 | Claim filing gates, adjudication min-rule, dispute loop, cap-gated payment |
| `irrigation.py` | 7,419 | Dealer-channel projects, pinned design-spec order, half-open window overlap |
| `admin.py` | 3,419 | `POST /turf/_clock/set_current_utc`, `POST /turf/admin/run_season_rollover` (6 phases in PRD order) |
| `app.py` | 1,381 | App factory, 40 routes mounted under `/turf`, envelope error handlers, `0.0.0.0:$PORT` |
| `start.sh` | 381 | Guarded pip install, `exec python3 app.py`, foreground |
| `requirements.txt` | 11 | `flask>=2.2` |

## Verification
- **py_compile**: all 14 modules — OK.
- **Boot smoke test** (dynamic port 57563, killed exactly the PIDs started): verbatim curl outputs are inline above — clock set echoes `{"current_utc":"2026-11-15T00:00:00Z"}` (200); no-headers → 401 `ERR_UNAUTHENTICATED`; missing field → 400 `ERR_INVALID_REQUEST`; distributor create → 201 with zeroed counters and `fill_rate: 1.0`; technician list → 200 with `meta.limit/offset/total_count/has_more`; wrong role → 403 `ERR_UNAUTHORIZED`; unresolved DM identity → 403 `ERR_FORBIDDEN_OWNERSHIP`; certify → 200 `CERT_ACTIVE`; compliance review → 200 `ONBOARDING→ACTIVE` via the technician/territory gate; STOCK order submit in November → 7% tier, `discount_cents: 7000`, `total_cents: 93000`, `committed_parts_cents: 93000`; `SUBMITTED→SHIPPED` → 409 `ERR_INVALID_STATE`; lease OCC with wrong version → 412 `ERR_STALE_LEASE_VERSION`; approval math base 1,000,000 × 1.08 (CLUB) × 1.00 (Dec) = `total 1080000`, `monthly_rate 45000`, version 3; rollover → 200 `{"advanced_to":"2026-11-15T00:00:00Z","transitions_applied":0}`.
- **Error ids**: 27 defined, 27 raised on live, reachable paths (25 in route modules; `ERR_UNAUTHENTICATED` in `helpers.auth()` invoked by every handler; `ERR_NOT_FOUND` in `helpers.get_or_404()` + app 404/405 handlers). Spellings match PRD exactly.
- **Calculations**: 10/10 implemented (`equipment_spec_compliance`, `fleet_lease_rate`, `trade_in_valuation`, `offseason_incentive_discount`, `warranty_labor_adjudication`, `parts_stocking_compliance`, `remarketing_pricing`, `irrigation_design_spec`, `lease_billing_progression`, `model_sales_window_expiry`).
- 40 routes = scaffold endpoint table; in-memory dicts only; empty store at boot; no test files read.

## Interpretation decisions (Step 7 audit candidates)
1. Unknown `to` target → `ERR_INVALID_STATE` 409 (PRD §2.8 tier 6 over scaffold's `ERR_INVALID_REQUEST` condition text).
2. Certify with `expires_at <= clock`, and non-IN_SERVICE unit on claim create → `ERR_INVALID_STATE` 409 (no specific error named).
3. SUPERSEDED successor not `ACTIVE` → `ERR_INVALID_REQUEST` 400 (no error named); cycle check implemented and called though vacuous given the ACTIVE-successor precondition.
4. `model_code`/`sku` uniqueness stated but no error id → not enforced (anti-invent rule).
5. Entity `created_at`/`updated_at` from the **logical** clock (required by the compliance window math); `meta.api_request_timestamp` from wall clock; `set_current_utc` echoes the input string verbatim as `current_utc`.
6. Parts-order create does NOT check part `support_status` (PRD §3.3 checks it at submit only, despite scaffold P11 `applies_to` listing create); submit order is standing-then-channel per §3.3 prose, lease submit is channel-then-standing per §3.4 prose.
7. Compliance review bumps `version`/`updated_at` only when status changes (endpoint side-effect text); counters always recomputed; review on TERMINATED returns 200 unchanged.
8. Per-transition actor enforcement → `ERR_UNAUTHORIZED` 403 when the role is listed on the endpoint but is not the transition's actor (e.g., CA attempting an order SUBMITTED).
9. Lease approve check order follows §2.8 tiers — overlap (P10) → models (P11) → standing/spec (P12) → credit (P13) — not the SM's listed order.
10. Appraisal create requires `lease.distributor_id == X-User-ID` → 403; `ACCEPTED` when the lease left DRAFT/SPEC_REVIEW → 409 `ERR_INVALID_STATE`.
11. Claim-create ref resolution in canonical §2.8 type order (technician before unit; model before lease on appraisal create); terminated distributor blocked from new leases/orders/claims/projects via `ERR_DISTRIBUTOR_NOT_ACTIVE` (§2.9 read-only).
12. Warranty expiry boundary: expired iff `now > delivered_at + factory_warranty_months` (inclusive); labor cents rounded half-up (observationally exact for integral products; PRD pins rounding on parts reimbursement only).
13. RECEIVED: `received_lines` required; unknown/duplicate part or qty outside [0, ordered] → 400; omitted lines count as 0 received.
14. Pagination: non-integer limit/offset → 400; out-of-range clamped to [1,100]/[0,∞); non-matching filter values yield empty lists.
15. Rollover runs the six phases sequentially in PRD order; the decay step also hits units just released from reservation in the same run; `transitions_applied` counts status changes only (not billing/decay updates).

Orchestrator verification: 16 files in workspace/implementation/, all compile (py_compile OK).

## Step 7: Run tests and iterate — 2026-10-02T09:20:00.000Z

Clean sweep: all 8 rounds pass 79/79, with all `results.${i}.json` deliverables in place under `workspace/implementation/`.

## Summary

**Iterations run:** 2 (initial 8-round sweep → 2 deterministic failures → fixes → final 8-round sweep, 79/79 clean in every round).

**Tests deleted:** none. Both failing tests passed STEP 1 (PRD verbatim coverage + unique derivability) and STEP 2 (test-vs-PRD consistency); both failures were implementation-side interpretation errors.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:**

1. `workspace/implementation/catalog.py`, `transition_part` — successor-not-`ACTIVE` on an `ACTIVE→SUPERSEDED` transition now raises `ERR_SUPERSESSION_CYCLE` (422) instead of `ERR_INVALID_REQUEST` (400). PRD §3.2 attaches the single named error to the compound precondition ("the successor must reference an existing part still in `ACTIVE` support, and the supersession graph must remain acyclic … or the request fails with `ERR_SUPERSESSION_CYCLE`"), and §2.8's only tier mentioning supersession is tier 12 with that error; tier 5's description ("required fields present, enum members valid, types match") does not cover a reference-state violation, so the old mapping was invented and made the PRD-named cycle error unreachable. Fixes `test_part_supersede_cycle_rejected`.

2. `workspace/implementation/admin.py`, `run_season_rollover` — units whose reservation expired in the same rollover run are now excluded from that run's remarketing decay step (released ids collected in phase 4, skipped in phase 5). PRD §3.7 states the rollover returns the unit to `REMARKET_LISTED` "leaving the ask untouched, since reservation expiry is not a decay step"; the impl's interpretation #15 (decay hits just-relisted units) made the ask observably decayed (1,309,000 → 1,282,820), contradicting the explicit sentence. Fixes `test_rollover_expires_reservation_relists_unit`.

**Unasserted paths worth noting (out of scope for the green sweep, flagged for audit):**
- The supersession cycle *walk* in `catalog.py` is now practically unreachable: a not-`ACTIVE` successor raises before it, and an `ACTIVE` successor never has `superseded_by_part_id` set, so no cycle is walkable. Observable behavior is still PRD-correct (both conditions yield the same named error), but the walk is dead code.
- The not-`ACTIVE`-successor-*without*-cycle case (successor in `LAST_BUY`/`DISCONTINUED`) has no test; mapped to `ERR_SUPERSESSION_CYCLE` per the PRD sentence's compound-"or" reading, but a narrower reading (error attaches only to the acyclicity clause) would leave that error unnamed. This was Step 6 interpretation #3's original ambiguity.

Orchestrator verification: all 8 `results.{i}.json` present, each 79/79 passed / 0 failed; newest source mtime (admin.py) ≤ newest results mtime — no post-sweep writes, sweep is final.

## Step 8: Finalize PRD — 2026-10-02T09:40:00.000Z

The diff is exactly the four intended revisions; both files are 324 lines. All verification complete.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 324 lines each; 4 lines revised in place (~1.2% of lines, 0% line-count delta). Not byte-identical — both step_7_diff items traced to genuinely ambiguous PRD prose (each had produced a real Step-6 misreading), so each received a minimal clarifying edit.

**Changes (one bullet per edit):**
- **§3.2 (line 169)** — revise — the compound supersession precondition's trailing "or the request fails with `ERR_SUPERSESSION_CYCLE`" grammatically attached only to the acyclicity walk (Step 6 had mapped a not-ACTIVE successor to `ERR_INVALID_REQUEST` 400); now an explicit sentence binds both violations — a successor that resolves but is not in `ACTIVE` support, or a cyclic walk — to `ERR_SUPERSESSION_CYCLE` (HTTP 422) — `workspace/implementation/catalog.py:161-162, 168`.
- **§2.8 tier 12 (line 134)** — revise — "supersession acyclicity" widened to "supersession validity and acyclicity" so the tier description covers both raise sites of `ERR_SUPERSESSION_CYCLE` — `workspace/implementation/catalog.py:162, 168` (the only raise sites in the codebase).
- **§2.5 (line 93)** — revise — rollover decay target changed from "every unit sitting in `REMARKET_LISTED`" to "every unit already sitting in `REMARKET_LISTED` when the run began", pinning the run-start snapshot semantics — `workspace/implementation/admin.py:80-81`.
- **§3.7 (line 223)** — revise — the reservation-expiry sentence now states explicitly that a unit released back to `REMARKET_LISTED` by a rollover's reservation-expiry step is not subject to that same run's decay step — `workspace/implementation/admin.py:64-85`, `workspace/implementation/calculations.py:218-222`.

**Per-edit pre-edit search log (NO-NEW-MISMATCH):**
- **Edit 1** — (a) subject: error identity/status for ACTIVE→SUPERSEDED precondition violations. (b) enumerated paths: `catalog.py:144-174` (all four outcomes — missing field→`ERR_INVALID_REQUEST` 400 via `helpers.req` at `helpers.py:191-194`; nonexistent successor→`ERR_NOT_FOUND` 404 via `get_or_404` at `helpers.py:248-251`; not-ACTIVE→`ERR_SUPERSESSION_CYCLE` 422; cycle walk→422, dead code); full-impl grep for `ERR_SUPERSESSION_CYCLE`/`superseded_by_part_id`/`SUPERSEDED` (no other raise sites; `parts_orders.py:129-130` checks `support_status` only); `helpers.py:18-46` error catalog; PRD §2.8 tier 4 (line 119) reference-resolution rule. (c) wording adjustment: used "resolves but is not still in `ACTIVE` support" so nonexistent successors stay under §2.8 tier-4 404 semantics (as impl does) and only the resolvable-but-inactive case maps to 422.
- **Edit 2** — (a) subject: tier-12 constraint label scope. (b) paths: grep confirmed `ERR_SUPERSESSION_CYCLE` is raised only at `catalog.py:162` (validity) and `catalog.py:168` (acyclicity); `helpers.py:40` is just the status map. (c) none beyond the two-word widening; error list and tier ordering untouched.
- **Edit 3** — (a) subject: which units receive a rollover's decay step. (b) paths: `admin.py:66-75` (phase 4 is the only mid-run source of `REMARKET_LISTED`), `admin.py:80-85` (phase 5 condition `status == REMARKET_LISTED and id not in released_this_run`), `units.py:121-125` (client-initiated listing), `units.py:127-134` (reserve/sale), `calculations.py:218-222` (decay fn, called only from `admin.py:82`). Verified "already sitting when the run began" is exactly equivalent to the impl condition, since no rollover phase moves a listed unit out of `REMARKET_LISTED`. (c) chose snapshot wording over referencing reservation expiry, to be independent of phase-ordering details.
- **Edit 4** — (a) subject: reservation-expiry relist × same-run decay interaction. (b) paths: same enumeration as edit 3 plus the test evidence `test_suite/test_09_fleet_turnover_and_remarketing.py:166` (ask must remain 1,309,000 after the lapsed-hold rollover). (c) appended clause constrained strictly to the same-run interaction; all other ask-mutation paths (listing, sale, decay) unaffected.

No edits were made for behavior the PRD already pinned uniquely; test-suite and test-helpers required no changes (Step 7 made none). SCAFFOLD*.yaml and worklog.md were not read.

Orchestrator verification: PRD_FINALIZED.md exists, 324 lines; diff vs PRD.md shows exactly the 4 claimed revisions (§2.5 line 93, §2.8 line 134, §3.2 line 169, §3.7 line 223).

## Step 9: Complete PRD — 2026-10-02T10:10:00.000Z

All 28 edits verified in place. No implementation files were touched, so per the task contract no test-suite re-run was required (the pre-existing sweep evidence shows 79/79 passing).

## Summary

**Source vs output:** `PRD_FINALIZED.md` (324 lines / 55,866 chars) → `PRD_COMPLETED.md` (324 lines / 61,063 chars); char delta **+5,197**; 27 paragraphs touched (28 edits, all in-paragraph inserts/revisions; no new sections, no new paragraphs).

**Counts:** 24 ambiguity-pins, 4 mismatch-revisions, 0 implementation fixes (suite not re-run — no impl changes).

**Mismatch-revisions:**
- §2.1 — revise — mismatch — PRD's "for unit actions, the course of the unit's owning lease" would bar an unrelated course from reserving a listed unit; impl allows any resolved course to reserve (only SOLD checks `reserved_by_course_id`) — `implementation/units.py:96-104`.
- §2.1 — revise — mismatch — PRD's blanket "X-User-ID that resolves to no entity … is rejected" covers reads; impl resolves identity/ownership only on create/transition calls, GETs enforce role membership only — `implementation/helpers.py:121-134` and its call sites.
- §2.6 — revise — mismatch — "parts reimbursement is the only rounded step in claim adjudication" dropped; impl also rounds the claimed/factory-allowance/adjudicated labor pricings half-up (required for fractional `labor_hours`, which impl admits) — `implementation/calculations.py:134-148`.
- §3.3 — revise — mismatch — "the order's `discount_cents` is voided along with the order" replaced: impl leaves all recorded incentive fields unchanged on the cancelled order; only the commitment ledger is compensated — `implementation/parts_orders.py:163-165`.

**Ambiguity-pins:**
- §2.3 — insert — out-of-range `limit`/`offset` clamp to bounds; non-integer values are `ERR_INVALID_REQUEST` — `helpers.py:150-163`.
- §2.3 — insert — unit-list `unit_seq` ties across leases fall back to creation order — `units.py:50`.
- §2.4 — insert — client-supplied system-managed/computed fields on writes are ignored — `leases.py:88-106` (and test_05's injected-fields test).
- §2.5 — insert — clock-set echoes `current_utc` in the supplied form — `clock.py:42-46`, `admin.py:22`.
- §2.5 — insert — `transitions_applied` counts state changes only (not billing/decay); cert/reservation expiry requires deadline strictly before the clock; no-change billing/decay steps don't touch version — `admin.py:31-94`.
- §2.9 — insert — opening a lease/order/claim/project under a `TERMINATED` distributor is `ERR_DISTRIBUTOR_NOT_ACTIVE` (409) — `parts_orders.py:64-65`, `leases.py:86-87`, `warranty.py:61-62`, `irrigation.py:48-49`.
- §3.1 — insert — certification allowed only from `CERT_PENDING`/`CERT_EXPIRED`; already-active or non-future `expires_at` fails `ERR_INVALID_STATE` — `distributors.py:169-172`.
- §3.1 — insert — review window selects orders by `created_at`; a no-standing-change review stores counters without version/`updated_at` bump; a `TERMINATED` review stores counters and returns 200 — `calculations.py:175-185`, `distributors.py:84-117`.
- §3.2 — insert — catalog age measured from the model's `created_at` — `calculations.py:267-270`.
- §3.3 — insert — order creation open to any standing short of `TERMINATED`; `total_cents` equals `subtotal_cents` until submission — `parts_orders.py:64-76`.
- §3.3 — insert — `discount_tier_pct` recorded as a decimal fraction (0.12/0.07/0.03) — `calculations.py:127`.
- §3.3 — insert — `received_lines` shape rules (unknown part, duplicate part, out-of-range qty → `ERR_INVALID_REQUEST`; omitted parts count as zero) — `parts_orders.py:142-160`.
- §3.4 — insert — `cycle_months` ≥ 1 and non-empty lines with qty ≥ 1, else `ERR_INVALID_REQUEST` — `leases.py:28-42,69-70`.
- §3.4 — insert — `end_date` month addition clamps day-of-month to the target month's last day — `clock.py:55-63`.
- §3.4 — insert — lease economics null at creation (`spec_compliant`, base/total/net/monthly/remaining), `trade_in_credit_cents`/`billed_to_date_cents` start at 0 — `leases.py:95-102`.
- §3.4 — insert — approval gates evaluated in §2.8 priority order (overlap → models → standing → spec → credit) — `leases.py:187-203`.
- §3.5 — insert — appraisal `hours` integer ≥ 0 (`ERR_INVALID_REQUEST`); target-lease state gate is `ERR_INVALID_STATE` (409) — `appraisals.py:59-65`.
- §3.5 — insert — acceptance after the lease leaves DRAFT/SPEC_REVIEW fails `ERR_INVALID_STATE` (409) — `appraisals.py:133-135`.
- §3.6 — insert — delivery with lease not APPROVED/ACTIVE fails `ERR_INVALID_STATE` (409) — `units.py:106-108`.
- §3.6 — insert — `hours_used` integer ≥ 0, else `ERR_INVALID_REQUEST` — `units.py:89-91`.
- §3.6 — insert — whole-months billing counts day-of-month anniversaries — `clock.py:66-71`.
- §3.8 — insert — fractional `labor_hours` admitted; `parts_cost_cents` ≥ 0; unit must be `IN_SERVICE` else `ERR_INVALID_STATE`; gates evaluated in §2.8 order; warranty coverage boundary inclusive — `warranty.py:40-62`.
- §3.8 — insert — full approval records `approved_labor_hours` as null; denial records no figures and leaves earlier-round figures untouched — `warranty.py:130-139`.
- §3.9 — insert — `acreage`/`zone_count` integers ≥ 0, else `ERR_INVALID_REQUEST` — `irrigation.py:40-45`.
- §3.9 — insert — design-submission gates evaluated in §2.8 order (window gates before controller catalog standing) — `irrigation.py:125-137`.
- §4 — insert — a caller outside a transition's actor subset of the endpoint's listed roles gets `ERR_UNAUTHORIZED` (403) — e.g. `leases.py:168-169`, `units.py:96-97`.

Output file: `workspace/PRD_COMPLETED.md`.

Orchestrator verification: PRD_COMPLETED.md present (324 lines, 61,329 bytes); diff vs PRD_FINALIZED.md = 54 changed lines; Step 8's edits retained verbatim; implementation untouched since the clean sweep (newest source mtime ≤ results mtime); spot-check of §2.1 reservation claim against `units.py:96-104` confirms RESERVED has no ownership check, only SOLD checks `reserved_by_course_id` — claim accurate.
