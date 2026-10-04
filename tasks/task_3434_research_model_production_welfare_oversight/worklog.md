# Worklog — task_3434_research_model_production_welfare_oversight

## Step 1: Create task directory — 2026-10-02T02:15:00.000Z

Task directory `tasks/task_3434_research_model_production_welfare_oversight/` was pre-allocated by the caller and already existed with an empty `workspace/` inside; verified existence, computed no new index, created no other task_* directory. Difficulty instruction for scaffold generator: "Generate task much harder than expert level!"

## Step 2: Generate scaffold — 2026-10-02T03:25:00.000Z

All three artifacts are complete, parse cleanly, and pass `scaffold_lint.py` with a clean verdict.

**Files delivered** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3434_research_model_production_welfare_oversight/`):
- `SCAFFOLD.yaml` — 2493 lines; top-level keys: scenario (verbatim), domain_name `research-model-production-welfare`, api_prefix `/api`, complexity_profile, response_envelope (fixed block), entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Contains **neither** `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1523 lines; single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2513 lines; single top-level key `scaffold_corner_design`.

**Structure:** 13 entities (Facility, BarrierRoom, ModelStrain, Colony, Cohort, HealthScreen, Customer, CustomerOrder, Allocation, Shipment, IACUCProtocol, WelfareInspection, ServiceContract), 49 endpoints (incl. unprefixed `POST /_clock/set_current_utc` with the mandated `2026-09-01T00:00:00Z` default), 13 state machines (Colony carries parallel lifecycle × genetic dimensions; order SOURCING⇄BACKORDERED and protocol review and cryo-validation loops are cyclic), 8 calculations, 37 priority-ordered validations, 37 errors (bidirectionally closed: every declared error is referenced, every referenced error is declared), 7 roles (segregation-of-duties model: protocol approver ≠ submitter, inspection verifier ≠ reporter; Customer is `entity_backed:Customer`), 2 OCC concurrency rules on `CustomerOrder.version`.

**Difficulty (beyond-expert density):** 18 §1.8 instances, 2 per rule, all differentiated — dual-variant calcs on two entity domains (colony PROJECTED vs CONFIRMED forecast = 48 vs 0; customer GROSS vs NET credit = 50000 vs 20000), combinatorial formulas in modes (a) and (b) (tiered+surcharge quote = 156600; per-line-ceiling box count = 5 vs rejected 4), a 4-hop health-screen→room→cohort→allocation→order cascade and a 3-hop overdue-inspection→facility→shipment→order cascade, two validation priority conflicts on distinct category pairs, boundary checks on quota (== passes) and zero-quantity, cross-entity gates (Order×Cohort, Shipment×Facility), vehicle half-open transit windows vs aggregate cage capacity, and two compensating invariants (cohort headcount, gross exposure). §1.9: 50 corner entries (46 active + 4 excluded_because stubs) across all nine taxonomy sections.

**Verification:** `scaffold_lint.py` verdict verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (762 calls scanned). Additional scripted checks: 68 unique instance names across both design files, zero unbound `${var}` placeholders, no forbidden race vocabulary, all stub targets resolve, all numeric asserts pre-computed as literals (e.g. 156600, 48, 50000/20000, 5 boxes, 9→11 cage rejection). Domain greps confirm the content covers breeding colonies/genetic monitoring, barrier exclusion lists and surveillance, age/weight/sex-ratio order specs, barrier-preserving transport with receiving protocol, IACUC review, veterinary/welfare inspection at both site types, custom generation + cryopreservation with IP terms, immunocompromised capacity constraints, and regulatory registration — not any sibling task's domain.

**One design note for downstream steps:** the welfare-inspection machine deliberately has no `REPORTED` resting state (report lands directly in CORRECTIVE_ACTION or CLOSED_VERIFIED) — I removed it mid-design as an unobservable enum value; the shipped files are self-consistent on this point.

[Orchestrator verification: files exist and parse; SCAFFOLD.yaml top keys = scenario, domain_name, api_prefix(/api), complexity_profile, response_envelope, entities(13), state_machines(13), concurrency_rules, calculations(8), validations(37), endpoints(49 — incl. exactly one unprefixed: POST /_clock/set_current_utc), errors(37), roles(7); §1.8 ≈ 18 instances, §1.9 ≈ 50 entries. Claims verified against source.]

## Step 3: Copy shared files — 2026-10-02T03:26:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_3434_research_model_production_welfare_oversight/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T03:45:00.000Z

The disk change was my own trailing-whitespace strip; the file now ends cleanly at the §5 table. Generation and verification are complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3434_research_model_production_welfare_oversight/workspace/PRD.md` — 312 lines, no truncation, ends at §5.

**Sections:** 1. Introduction · 2. Global Specifications (2.1 RBAC & role identity, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Versioning, 2.5 The Logical Clock, 2.6 Barrier Health-Status Rank Order, 2.7 Validation Priority, 2.8 OCC on Order Writes, 2.9 Numeric Precision) · 3. Business Logic (3.1 Facilities/Rooms, 3.2 Strains/Colonies/Genetic Monitoring, 3.3 Cohorts/Culls, 3.4 Cage & Quota Accounting, 3.5 Surveillance/4-hop Downgrade Cascade, 3.6 Customers/Credit/Order Intake/Quote, 3.7 Allocation/Supply Loop, 3.8 Transport/Receiving, 3.9 Protocol Review/Welfare Inspection, 3.10 Contracts/IP Terms) · 4. Endpoint Definitions · 5. Error Code Catalogue.

**Verification results (all mechanical checks pass):**
- **Endpoints:** 49/49 scaffold paths present in the §4 table with exact scaffold role lists (script-verified, including the restricted role sets on `GET /api/customers/{id}/inspections` and `GET /api/orders/{id}`).
- **Clock endpoint:** documented unprefixed as `POST /_clock/set_current_utc` in both §2.5 prose and §4, explicitly called out as the sole non-`/api` endpoint, with startup default `2026-09-01T00:00:00Z` and no-wall-clock-fallback semantics.
- **Error IDs:** 37/37 appear verbatim both in the §5 table (2 columns) and in §2/§3 prose sentences with triggering condition and HTTP status.
- **Contract 1 (Field-Name Coverage):** 115 required names (all entity fields + endpoint inputs + query/path params), 115 present in backticks, 0 missing. Status: PASS.
- **Contract 2 (Rule Coverage):** all 37 validations paired to their error_id in ladder-ordered prose; both OCC rules (`POST /api/allocations`, `POST /api/shipments` → `expected_order_version` → `ERR_STALE_VERSION`/412); all 13 state machines with preconditions and side effects; all 8 calculations with constants and pinned evaluation order (86400 s/day, 7 days/week, survival 0.8, tiers 100/10% and 250/20%, surcharges 25%/20%/40%, box tiers 15 g/25 g → 10/6/4 per box, cage density 5, viability floor 70, royalty (0,100], 72 h sanitization, equality-passes quota/capacity/credit gates). Status: PASS.
- **Contract 3 (§3 Path Purity):** 0 path/method tokens in §3. Status: PASS.
- **§2.2:** byte-identical to the canonical `section-2.2-response-structure.md` block (script-verified).
- **Design-file isolation:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; a token sweep (`test_recipe`, `worked_example`, `corner`, `DIFFICULTY`) confirms no leak.

**One judgment call to flag:** the scaffold names two constants without values — `MIN_ORDER_LEAD_DAYS` and `MAX_TRANSIT_HOURS`. Per the Zero-Silence requirement (and the known Step 5/6 drift failure mode), the PRD pins them concretely: minimum order lead time **14 days** (§3.6) and maximum transit duration **48 hours** (§3.8). Test and implementation generation will now read the same values from the PRD.

[Orchestrator verification: PRD.md = 312 lines; 49/49 scaffold endpoint paths present; 37/37 error ids present; zero design-file leak tokens; `/api/_clock` absent and `/_clock/set_current_utc` present (unprefixed, correct). Claims verified against source.]

## Step 5a: Generate test helpers — 2026-10-02T04:05:00.000Z

(Step 5 was split into 5a helpers / 5b tests per the oversized-generation-step rule: 49 endpoints × 7 roles × 64 design instances exceeds the single-subagent output cap.)

All checks pass. Step 5a is complete.

**Files generated** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3434_research_model_production_welfare_oversight/`):

| File | Lines |
|---|---|
| `test_helpers/__init__.py` | 33 |
| `test_helpers/types.py` | 464 |
| `test_helpers/api_client.py` | 258 |
| `test_helpers/api_errors.py` | 102 |
| `test_helpers/assertions.py` | 481 |
| `test_helpers/factories.py` | 279 |
| `test_helpers/constants.py` | 233 |
| `test_helpers/test_users.py` | 105 |
| `test_helpers/fixtures.py` | 773 |
| `test_suite/conftest.py` | 53 |

**Frozen public API surface (contract for Step 5b):**

- **api_client.py** — `ApiClient(GenericApiClient)` with exactly 49 endpoint methods (verified): 48 under `/api` + `set_current_utc(payload, headers)` → `POST /_clock/set_current_utc` **unprefixed**. Module singleton `api_client`.
- **api_errors.py** — `ApiErrorId` (37 members, PRD §5), `HTTP_STATUS_CODES` (registered with framework via `set_error_http_status_map`).
- **types.py** — `UserRole` (7 roles, PRD-spelled), 20 status/domain enums, 13 entity TypedDicts. The four PRD §2.4 light resources (`ModelStrain`, `HealthScreen`, `Allocation`, `WelfareInspection`) omit `updated_at`/`version`; the other nine carry the full audit triple.
- **assertions.py** — `assert_{facility,room,strain,colony,cohort,health_screen,customer,order,allocation,shipment,protocol,inspection,contract}(data)`; calculators `compute_age_weeks`, `compute_expected_quote`, `compute_expected_box_count`, `compute_occupied_cages`, `compute_projected_pipeline`, `box_capacity_for_weight`, `barrier_rank`, `assert_barrier_rank_at_least`, `assert_cohort_availability_invariants`, `assert_order_coverage_invariants`. Light-resource assertions also demand *absence* of `updated_at`/`version`.
- **factories.py** — `create_{facility,room,strain,protocol,colony,cohort,health_screen,customer,order,allocation,shipment,inspection,contract}_payload`, `create_finding`, `create_screen_result_entry`, `create_new_strain_spec`, `DEFAULTS`. Unique-constrained fields (`site_code`, `account_number`, `protocol_number`, `strain_code`, `vehicle_code`) get UUID suffixes per call.
- **constants.py** — all values verified against PRD prose: `MIN_ORDER_LEAD_DAYS=14` (§3.6), `MAX_TRANSIT_HOURS=48` (§3.8), `SANITIZATION_WINDOW_HOURS=72` (§3.8), `SURVIVAL_RATE=0.8` (§3.2), `TIER1_QTY=100/TIER1_DISCOUNT=0.10/TIER2_QTY=250/TIER2_DISCOUNT=0.20` (§3.6), `IMMUNO_SURCHARGE=0.25/VF_PREMIUM=0.20/GERM_FREE_PREMIUM=0.40` (§3.6), `LIGHT_MAX_G=15.0/HEAVY_MIN_G=25.0/LIGHT_PER_BOX=10/STANDARD_PER_BOX=6/HEAVY_PER_BOX=4` (§3.8), `CAGE_DENSITY=5` (§3.4), `ANIMALS_PER_BREEDING_PAIR=2` (§3.4), `VIABILITY_FLOOR_PCT=70` (§3.10), `CLOCK_DEFAULT_ISO="2026-09-01T00:00:00Z"` (§2.5), `BARRIER_RANKS` 1–4 (§2.6), `DEFAULT_SNP_PANEL_INTERVAL_WEEKS=12` (§3.2), `SECONDS_PER_DAY=86400/DAYS_PER_WEEK=7` (§3.3), GROSS/NET_BILLED status sets (§3.6), pagination 10/1/100/0 (§2.3), `OVERDUE_CORRECTIVE_ACTION` (§3.1), plus clock-reachable standard fixture instants.
- **test_users.py** — `TEST_USERS` (7 shared header constants) + `make_{admin,facility_manager,veterinarian,iacuc_reviewer,customer,logistics,inspector}_headers(user_id)`; `make_customer_headers` is documented as mandatory for ownership-gated calls.
- **fixtures.py** — read helpers (incl. sublist-based `read_allocation`/`read_shipment`/`read_health_screen`/`read_protocol`, since PRD §4 has no single-GET for those); Tier 1 creators; `create_approved_protocol` (SoD-separated submitter/reviewer); `setup_production_site`; `setup_colony_with_cohorts` (FOUNDING→EXPANDING→cohorts→PRODUCTION→HOLD, per-cohort specs); `create_order_submitted`/`source_order`/`backorder_order`/`transition_order`; OCC-aware `allocate_order_to_cohort(order, cohort, m, f) -> (alloc, refreshed_order)` and `create_shipment_for_order(order, **over) -> (shipment, refreshed_order)`; `setup_sourcing_order`/`setup_allocated_order`/`setup_scheduled_order`/`setup_shipped_order`/`setup_delivered_order`; health-screen, inspection (reporter/verifier ids explicit), and contract fixtures; `advance_clock(to_iso8601)`.
- **conftest.py** — session-scoped `api` + 7 role-header fixtures (customer fixture documented as fallback-only).

**Self-check results:** `py_compile` passed on all 10 files; real import of all 9 modules + conftest execution passed; barrel surface (120+ names) resolves; `/_clock/set_current_utc` confirmed unprefixed at `api_client.py:253`, zero `/api/_clock` occurrences; zero scaffold or design-instance-name references in helpers; every create path asserts 201 explicitly via `get_success_data(resp, 201)`; all fixture default dates proven reachable from the 2026-09-01T00:00:00Z clock (default cohort is exactly 6 weeks at the standard 2026-10-13 delivery, inside the default [4,6] window; transit 24 h ≤ 48 h; sanitization 2 h before departure); calculators spot-checked against the pinned design arithmetic (quote 156600; 5 boxes; projected 48).

[Orchestrator verification: all 9 helper modules import cleanly from the task dir; api_client.py:253 issues `POST /_clock/set_current_utc` unprefixed; zero `/api/_clock` occurrences; constants.py carries MIN_ORDER_LEAD_DAYS=14, MAX_TRANSIT_HOURS=48, SANITIZATION_WINDOW_HOURS=72, CLOCK_DEFAULT_ISO=2026-09-01T00:00:00Z; test_suite/ contains only conftest.py (no test_*.py yet, as intended). Claims verified against source.]

## Step 5b: Generate test suite — 2026-10-02T04:40:00.000Z

All audits pass. Step 5b is complete.

**Files generated** (12 files, 82 tests) under `/home/ubuntu/github/CodingPRD/tasks/task_3434_research_model_production_welfare_oversight/test_suite/`:

| File | Tests | Content |
|---|---|---|
| test_01_entity_basics.py | 9 | creation envelope/defaults, light-resource shape, 404/400/enum/duplicate paths, inspection site XOR, pagination meta, 401 auth floor |
| test_02_colony_lifecycle.py | 8 | parallel lifecycle/genetic dimensions (×2), immediate read-after-write, drift→PHASING_OUT, RETIRED lockdown, HOLD blocked by PANEL_DUE, immunocompromised mixing, barrier insufficiency |
| test_03_colony_forecasts.py | 5 | PROJECTED vs CONFIRMED (×2), drift drops pipeline, reserved excluded from confirmed, age_weeks at logical clock |
| test_04_protocols.py | 6 | quota exact-fit boundary (×2: cohort-side + colony-side), resubmission loop, REJECTED lockdown, expiry blocks cohort creation, protocol SoD |
| test_05_cohorts_capacity.py | 4 | cage aggregate boundary (×2: reject + equality-passes leg), partial cull accounting, double-release rejected |
| test_06_orders_credit.py | 11 | zero-quantity (×2), cancel conserves GROSS (×2), GROSS vs NET_BILLED (×2), SOURCING↔BACKORDERED cycle (×2), credit equality-then-exceed, 14-day lead, DELIVERED lockdown |
| test_07_allocations.py | 9 | order/cohort state gates (×2), reserve-release conservation (×2), strain/weight/age window rejections, panel-overdue gate, dual sublist reachability |
| test_08_shipments.py | 10 | per-line box ceiling (×2), half-open vehicle windows (×2: adjacency legal + overlap rejected), facility-gated departure (×2), transit duration, sanitization chronology, vehicle cert floor, ALLOCATED-order gate |
| test_09_inspections_cascades.py | 7 | positive-screen 4-hop cascade (×2), overdue-inspection facility suspension (×2), empty-findings close, day-slot conflict, verify SoD |
| test_10_contracts.py | 3 | cryo viability retry loop, custom-generation strain minting, IP-terms conditional validation |
| test_11_quote_rbac_priority.py | 8 | quote tier×surcharge stacking (×2), constraint-beats-fiscal (×2 with control leg), safety-beats-temporal (×2 with control leg), Customer RBAC denial, ownership mismatch |
| test_12_occ.py | 2 | OCC stale version on allocation and on shipment creation |

**Audit (a) — AST tag audit: PASS.** 82 emitted tests; 36 tags resolve to §1.8 instances (all 18 difficulty instances × exactly 2 tests each); 46 tags resolve to §1.9 non-stub instances (all 46 × 1 test); 0 untagged; 0 dual-tagged; 0 tags pointing to non-existent instances; 0 tests tagged to the 4 `excluded_because` stubs; 0 design instances without tests.

**Audit (b) — collection: PASS.** `python3 -m pytest test_suite --collect-only -q` → **82 collected, 0 errors**.

**Audit (c) — grep sweep: PASS.** No `/api/_clock` anywhere (clock only via `advance_clock`/`api_client.set_current_utc`); no executable hardcoded literals competing with constants.py — rate/threshold numerals appear only inside verbatim PRD citations or comments, with all arithmetic asserts cross-checked against the frozen calculators (`compute_expected_quote`, `compute_projected_pipeline`, `compute_expected_box_count`, `compute_occupied_cages`, `compute_age_weeks`). A separate verbatim-citation audit confirmed all 117 quoted PRD spans survive literal grep of PRD.md (4 initially-failing endpoint-titular quotes were replaced with rule-bearing prose).

**Skip ledger: empty.** Every non-stub instance passed the PRD-first filter. The 4 corner stubs (`shipment_acceptance_posts_billing_side_effect`, `order_quote_constants_applied`, `validation_priority_ordering`, `cohort_reserved_reconciliation_after_release`) were not translated; their difficulty-instance cross-references all resolve.

**Adjudication notes:**
- `delivery_lead_below_minimum_rejected`: the design narrative claims a "5-day lead" but constants.py/PRD pin 14 days; the trigger date (2026-09-05) still violates the real rule, so the asserted `ERR_DELIVERY_WINDOW_INFEASIBLE` stands — the wrong narrative literal was not copied.
- `cohort_hold_blocked_when_panel_due`: `ERR_INVALID_STATE` judged uniquely derivable (PRD §3.3 conditions the HOLD edge on `genetic_status == CLEAR`; §2.7 maps undeclared transitions to that error; `ERR_PANEL_OVERDUE`/`ERR_GENETIC_DRIFT` are PRD-scoped to allocations/cohort creation only).
- Clock discipline: all fixture dates verified reachable from 2026-09-01T00:00:00Z (birth dates ≤ clock, deliveries ≥ 14-day lead, transit ≤ 48 h, sanitization within 72 h, SNP sweep at >12 weeks, protocol expiry/inspection deadlines crossed only where intended).

**Helpers untouched**: `test_helpers/` and `test_suite/conftest.py` were read-only; no modifications.

[Orchestrator verification: re-ran the AST tag audit myself — 82 test functions, 0 tag problems, 36 Difficulty tags covering 18/18 instances, 46 Corner tags covering 46/46 instances, no phantom tags. My walker's raw instance count showed 19/47 vs the claimed 18/46 — traced the extra 'Site Alpha' to a facility-payload `name:` field inside test recipes in both yamls, i.e. fixture data, not a design instance; subagent's ledger correct. Re-ran `pytest --collect-only -q` myself: 82 collected, 0 errors. Claims verified against source.]

## Step 6: Generate implementation — 2026-10-02T05:00:00.000Z

The two remaining `python3 app.py` processes (543936, 546766) belong to a different task's pipeline (cwd task_3360) and are left untouched per process-safety rules. My smoke servers were killed by their exact PIDs.

**Delivered**: complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_3434_research_model_production_welfare_oversight/workspace/implementation/` — all 49 endpoints (48 under `/api` + unprefixed `POST /_clock/set_current_utc`), in-memory dict storage only, zero seeding, boots clean from a fresh process.

**File list (line counts)**:
- `start.sh` (10) — guarded install (`if ! python3 -c "import flask"`), `exec`, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` (1) — flask>=2.2
- `store.py` (97) — db dicts, logical clock (default `2026-09-01T00:00:00Z`, no wall-clock fallback), ISO-8601 parse/format (3-frac-digit Z), request-scoped `touch()` enforcing "one increment per entity per request"
- `responses.py` (50) — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), error envelope, pagination fields
- `auth.py` (50) — X-User-ID/X-User-Role, 7 roles, ownership
- `validation.py` (160) — typed field validators, enum sets, barrier ranks, paginate
- `calc.py` (437) — all 8 calculations with pinned constants (14-day lead, 48 h transit, 72 h sanitization, 0.8 survival, tiers 100/250 @ 10%/20%, surcharges 25%/20%/40%, box 15 g/25 g → 10/6/4, cage density 5, viability 70, 86400/7) + serializers
- `domain.py` (205) — cohort/order recompute, release, shipment cancel, facility suspension cascade, 4-hop barrier-downgrade cascade, pinned 3-step clock sweep
- `routes_facilities.py` (234), `routes_catalog.py` (463), `routes_orders.py` (402), `routes_shipments.py` (213), `routes_oversight.py` (410), `app.py` (45)

**py_compile**: all 12 `.py` files OK.

**Smoke transcript** (dynamic port, server killed by its own PID): `POST /_clock/set_current_utc` → 200 `data:{}`; unauthenticated → 401 `ERR_UNAUTHENTICATED`; facility/strain/protocol/room/colony/cohort/customer creates → 201 with correct computed fields (`occupied_cages` 58, `animals_used` 260, forecast 240/304); zero-qty order → 422 `ERR_INVALID_QUANTITY`; short-lead order → 422 `ERR_DELIVERY_WINDOW_INFEASIBLE`; order 100 animals @1000c → quote 90000 (10% tier); stale allocation → 412 `ERR_STALE_VERSION`; allocation → order ALLOCATED 60/40, cohort PARTIALLY_ALLOCATED; shipment → 201 `box_count` 17, order SCHEDULED; LOADED → IN_TRANSIT (cohort 60/80 post-consume) → ARRIVED → wrong-owner accept → 403 `ERR_OWNERSHIP_MISMATCH` → ACCEPTED → order DELIVERED, outstanding 90000; order CLOSED → exposure 0, outstanding stays 90000; positive screen → room QUARANTINED MPF→CONVENTIONAL + cohort downgrade; clock → 2026-12-01 → colony PANEL_DUE; SNP CLEAR → CLEAR. **45/45 checks passed.**

**Interpretation ledger** (PRD-silent or ambiguous edges):
1. §2.4/3.x — Transition *precondition* failures not otherwise catalogued (facility reinstate blocked by ESCALATED inspection, EXPANDING→PRODUCTION with no live cohort, quarantine lift without a later negative screen, full cull with RESERVED allocations, cohort HOLD while colony not EXPANDING/PRODUCTION/CLEAR) → `ERR_INVALID_STATE` 409. Payload-value problems (missing/stale `registration_expires_at`, cull counts exceeding available, missing `received_male/female`, missing `viability_pct`, future `birth_date`) → `ERR_INVALID_REQUEST` 400. routes_facilities.py, routes_catalog.py, routes_shipments.py.
2. §2.1/4 — Per-target actor restrictions inside shared transition endpoints (e.g. Vet-only QUARANTINED/ACTIVE, FM-only DECOMMISSIONED) → `ERR_UNAUTHORIZED_ROLE` 403, checked after endpoint role, before state.
3. §3.6/2.5 — `meta.api_request_timestamp` uses the logical clock (PRD: platform never reads wall-clock).
4. §3.8 vs 1.3 — `outstanding_balance_cents` is a persisted billing accumulator (PRD: "unchanged" on DELIVERED→CLOSED, which pure DELIVERED-sum computation contradicts); `credit_exposure_cents` is computed live from the status set. Customer `version` is NOT bumped by billing (scaffold side-effect lists only CustomerOrder.version). calc.py credit_positions, routes_shipments.py ACCEPTED.
5. §3.9 — Allocation creation gates on colony protocol `APPROVED` → `ERR_PROTOCOL_NOT_APPROVED` (PRD: expired-protocol colonies "can no longer accept allocations"); placed at priority 6 after drift/panel checks. No quota check at allocation (quota binds at creation gates only; the endpoint description's "protocol quota" mention treated as loose).
6. §3.5 hop 2 — Cohort downgrade applies to all cohorts of the room's colonies (no status filter stated); hop 3 releases only allocations on cohorts actually downgraded in this cascade.
7. §3.2 — Immunocompromised mixing: reject only when the incoming strain is IMMUNOCOMPROMISED and (room rank < VF) or (a non-RETIRED colony of a *different* IMMUNOCOMPROMISED strain exists in the room); same-strain second colony and immunocompetent neighbors allowed, per the validation rule's precise wording.
8. §2.5 — Clock accepts any parseable ISO-8601 instant (backward sets simply fire no strict-past transitions); `room_code` uniqueness-per-factory enforced as `ERR_DUPLICATE_KEY` 409 though the catalog lists only four keys.
9. §2.8/priority — Ladder runs strictly in priority order; checks whose inputs are absent/mistyped are skipped and surface at priority 8 as `ERR_INVALID_REQUEST`/`ERR_INVALID_ENUM` (per scaffold: missing field is not 404). OCC (p5) therefore precedes quarantine/drift/panel (p6), age (p7), quantity (p8), strain/weight/allocatable/order-status (p9).
10. §3.7 — Manual release of a RESERVED allocation on a SCHEDULED order decrements coverage and bumps order version but does not revert SCHEDULED (only ALLOCATED→SOURCING is declared); cascade-driven coverage loss on SCHEDULED cancels the shipment then routes to SOURCING.
11. §4 — Unknown `target_state` string → `ERR_INVALID_STATE` 409; missing `target_state` → 400. List filter params (`lifecycle_status`, `status`) are equality filters; unmatched values yield empty lists. Contract `new_strain_spec.strain_code` uniqueness checked at COMPLETED minting (scaffold DUPLICATE_KEY applies_to), not at creation.
12. §3.1 — Inspection escalation cascade suspends a facility only from REGISTERED/UNDER_INSPECTION (states from which the cascade is declared); already-SUSPENDED/REVOKED left as-is.

**Isolation compliance**: I never opened SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/, and never ran pytest. Only PIDs I started were killed (one orphaned smoke server cleaned up by exact PID; foreign-pipeline servers untouched).

[Orchestrator verification: 12 .py files + start.sh + requirements.txt present; all 12 compile; route decorators total 49 with exactly `/_clock/set_current_utc` unprefixed and 48 under /api; zero sqlite/json.dump persistence hits — in-memory only. Claims verified against source.]

## Step 7: Test-fix iteration loop — 2026-10-02T05:10:00.000Z

Clean sweep confirmed. All 8 parallel rounds ran to completion with every test passing, and the `results.*.json` files remain in place per the output contract.

**Summary**

- **Iterations run:** 1 (single 8-round parallel stability sweep, no rerun needed)
- **Sweep outcome:** 82/82 passed in every round — rounds 1 through 8 all report `passed == total == 82`, `failed == 0`. Spot-check of `results.1.json` confirms 82 real test entries with outcome `passed`; no flaky-test union to diagnose (zero tests failed in any round).
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `test_suite/`:** none
- **Fixes applied to `implementation/`:** none — the Step 6 implementation (12 Python modules + `start.sh`, 49 endpoints, in-memory storage, interpretation ledger items 1–12) passed the full 82-test suite on the first sweep with no drifted constants, no shadowing test-side edits, and no flakiness surfacing under 8× concurrency.
- **Artifacts preserved:** all 8 `results.${i}.json` files (i = 1..8) remain in `/home/ubuntu/github/CodingPRD/tasks/task_3434_research_model_production_welfare_oversight/workspace/implementation/` per the output contract.
- **Step 8 hand-off note:** no test-side fixes were applied this iteration, so there is no shadowing risk; the 4 known untranslated corner stubs (`shipment_acceptance_posts_billing_side_effect`, `order_quote_constants_applied`, `validation_priority_ordering`, `cohort_reserved_reconciliation_after_release`) remain the sibling PRD-declared paths with no asserting test, as recorded in the Step 5 skip ledger.

[Orchestrator verification: all 8 results.{1..8}.json files present in workspace/implementation/; each parsed: passed=82 total=82 failed=0 with 82 real test entries. Claims verified against source.]

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T05:11:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. PRD.md already determined every behavior the implementation exhibits; no PRD_FINALIZED.md is produced. Step 9 will start from PRD.md.

## Step 9: PRD completeness scan — 2026-10-02T05:26:00.000Z

All 18 edits are present (two §3.9 edits share one paragraph line, hence 17 diff hunks). Task complete. Final summary:

**Files**: `workspace/PRD.md` (312 lines, 73307 chars) → `workspace/PRD_COMPLETED.md` (312 lines, 76147 chars, +2840). Line count identical — all pins are in-paragraph; ends intact at §5 (ERR_SUPPLY_INSUFFICIENT row); heading structure unchanged.

**Counts**: 17 ambiguity-pins, 1 mismatch-revision (PRD-revised), 1 mismatch-resolution by impl-fix (RULE M option a). 18 PRD edits total across 17 diff hunks.

### Ambiguity pins (PRD silent → pinned to impl)
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` → `ERR_INVALID_REQUEST` 400; `created_at` ties broken by creation order — validation.py:139-157, store.py:96-97
- §2.4 — insert — ambiguity — unrouted path or undeclared method → `ERR_NOT_FOUND` 404 — app.py:26-32
- §2.5 — revise — ambiguity — clock control accepts any well-formed instant (no monotonicity constraint); empty-object data payload — routes_oversight.py:402-410
- §2.7 — insert — ambiguity — unknown `target_state` → `ERR_INVALID_STATE` 409, not `ERR_INVALID_ENUM` — e.g. routes_facilities.py:100-101
- §3.1 — revise — ambiguity — manual suspension `reason` is optional; string-when-present; null when omitted — routes_facilities.py:88-91
- §3.1 — revise — ambiguity — quarantine lift is a `Veterinarian` action — routes_facilities.py:195-209
- §3.2 — revise — ambiguity — RETIRED colonies don't count toward the one-immunocompromised-strain room limit — routes_catalog.py:143-156
- §3.2 — insert — ambiguity — SNP `CLEAR` only from `PANEL_DUE`, `DRIFT_DETECTED` only from `CLEAR`/`PANEL_DUE`; else `ERR_INVALID_STATE` — routes_catalog.py:252-261
- §3.3 — revise — ambiguity — future `birth_date` → `ERR_INVALID_REQUEST` 400 — routes_catalog.py:310-311
- §3.3 — revise — ambiguity — full cull blocked by reservations → `ERR_INVALID_STATE` 409; partial cull exceeding available → `ERR_INVALID_REQUEST` 400 — routes_catalog.py:373-387
- §3.5 — revise — ambiguity — result entries: `agent` non-empty string, `positive` boolean; result against DECOMMISSIONED room → `ERR_INVALID_STATE` — routes_catalog.py:440-457
- §3.6 — revise — ambiguity — order intake: `X-User-ID` naming no customer → `ERR_NOT_FOUND` 404; age bounds non-negative ints; weight bounds strictly positive numbers — routes_orders.py:139-172
- §3.7 — revise — ambiguity — coverage triggers at allocated ≥ requested ("first reach", not "first equal"); creation applies no cap against outstanding need — domain.py:43-52
- §3.8 — revise — ambiguity — `received_male`/`received_female` must be non-negative integers — routes_shipments.py:190-191
- §3.9 — revise — ambiguity — finding shape: non-empty `deficiency` string + `severity` enum; escalation leaves an already-`SUSPENDED`/`REVOKED` facility or already-`SUSPENDED` customer untouched — routes_oversight.py:218-230, domain.py:168-179
- §3.10 — revise — ambiguity — minting re-validates spec fields as strain registration; `viability_pct` absent → `ERR_INVALID_REQUEST` 400, non-numeric/out-of-range → `ERR_IP_TERMS_INVALID` 422 — routes_oversight.py:367-391

### Mismatch resolutions
- §3.6 — revise — mismatch (PRD-revised) — `outstanding_balance_cents` re-pinned from "sums over DELIVERED only" + "always NET ≤ GROSS" to the cumulative billed-pipeline accumulator (rises at DELIVERED, never revoked; can exceed GROSS after a close). Rationale: PRD 3.8 explicitly pins posting-at-acceptance and unchanged-at-close; impl's `_billed_cents` accumulator matches 3.8; the 3.6 formula sentences were the drifted half of an internal PRD contradiction. No test asserts post-close balances — calc.py:81-96, routes_shipments.py:196-200
- §3.2 (retirement gate) — mismatch (impl-added) — `routes_catalog.py` RETIRED branch scanned *all* cohorts system-wide for RESERVED allocations, blocking a PRD-legal retirement when an unrelated colony held reservations. Fixed impl (3-line guard restricting the scan to the colony's own cohorts), per RULE M option (a): the PRD sentence is verbatim and load-bearing, no test asserts the over-guard, fix is minimal — routes_catalog.py:231-238

### Implementation touched: YES
Re-sweep verdict: 8 fresh `results.{1..8}.json` files left in place, every round **passed == total == 82, failed == 0** (~142 s per round, parallel).

[Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md ≠ PRD.md (not a silent no-op), both 312 lines; routes_catalog.py mtime 05:20:18 precedes all 8 results.*.json mtimes 05:24:39 — the re-sweep ran AFTER the impl fix; all 8 post-Step-9 rounds parsed: passed=82 total=82 failed=0. Spot-checked the impl fix at routes_catalog.py:231-238 — the RESERVED-allocation scan now skips cohorts whose colony_id ≠ the retiring colony (`if c["colony_id"] != cid: continue` at line 232), exactly as claimed. Claims verified against source.]


