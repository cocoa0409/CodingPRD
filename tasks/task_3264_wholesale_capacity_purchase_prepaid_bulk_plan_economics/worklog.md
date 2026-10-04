# Worklog — task_3264_wholesale_capacity_purchase_prepaid_bulk_plan_economics

## Step 1: Create task directory — 2026-09-30T15:31:00.000Z

Task directory `./tasks/task_3264_wholesale_capacity_purchase_prepaid_bulk_plan_economics/` was pre-allocated by the caller and already contained an empty `workspace/`. Verified both exist; no new index computed and no other `task_*` directory created. Scenario: Wholesale Capacity Purchase & Prepaid Bulk Plan Economics (Mint Mobile) — wholesale capacity purchasing, prepaid multi-month plans with breakage/deferred revenue, data allotment deprioritization, digital activation/porting, SIM/eSIM distribution, support outsourcing deflection, renewal step-ups with churn management, roaming add-ons.

## Step 2: Generate scaffold — 2026-09-30T16:29:00.000Z

All three artifacts are generated and pass the linter clean.

## Summary

Three files written to `/home/ubuntu/github/CodingPRD/tasks/task_3264_wholesale_capacity_purchase_prepaid_bulk_plan_economics/`:

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2,422 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,519 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2,508 |

**Lint verdict (verbatim, `scaffold_lint.py`):**
```
Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     10
  §1.8 instances scanned:     27
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  903

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

**Entity model** — 10 entities / 97 typed fields: `CapacityAgreement`, `Plan`, `Subscriber`, `PrepaidTerm`, `Activation`, `RetailPartner`, `SimInventory`, `CycleRecord`, `SupportCase`, `AddOn`. Flat topology with cross-aggregate FKs (every FK uses the canonical `FK -> X.id` prefix and has a reverse-reachability GET). Computed/derived fields carry the coupling: `remaining_data_mb`, `allocated_data_mb`, `congestion_index`, `deprioritization_threshold_mb`, `deferred_revenue_cents`, `breakage_cents_recognized`, `held_data_mb`.

**State machines** — 11 machines / 65 transitions, deliberately non-linear: `Plan` and `PrepaidTerm` are **cyclic** (DRAFT⇄OFFERED, ACTIVE⇄RENEWAL_DUE⇄ACTIVE_RENEWAL); `Activation` carries **parallel dimensions** (`activation_status` × `port_status` on one row); `Subscriber`, `SimInventory`, `SupportCase`, `CycleRecord` are branching. 2 OCC `concurrency_rules` (agreement version on term create, subscriber version on cancel) passing the §1.2.1 serial-observability filter; no forbidden race vocabulary anywhere.

**Calculations** — 15 rules, 3 with divergent variants: forward-looking vs as-incurred wholesale cost; marginal-breakpoint vs retroactive-blended volume tier; provisional schedule vs final deprioritization-blended revenue. Plus chronological deferred-revenue aging, inclusive-threshold deprioritization, oversale ladder, breakage recognition, support budget, and the settlement-clearing invariant.

**Validations** — 27 ordered rules spanning auth → existence → state → safety → referential → temporal → fiscal, with two designated priority-conflict pairs.

**Endpoints** — 60 across 8 resource families plus a `/_clock` logical-clock endpoint (default `2026-09-01T00:00:00Z`), CRUD, action, filtered-list, and inline-schema computed reads.

**Errors / roles** — 42 entity-specific error codes; 6 roles, each with a mandatory `identity:` (`Subscriber` and `RetailPartner` entity-backed; four opaque).

**§1.8 instances** — 27 across all nine Difficulty Rules (≥2 each; rules 1–3, 5–9 carry 3, rule 7 carries 4). Every numeric assert is a code-computed literal (e.g. `resolved_purchase_cost_microcents == 35838000`, `as_incurred == 32992000`, `earned_cents == 634`, `breakage_cents_recognized == 2666`), with the composite-cost definition pinned in SCAFFOLD so the two design files agree.

**§1.9 instances** — 63 across all nine claim-extraction-guide sections (59 active + 4 `excluded_because:` stubs citing real §1.8 instance names), by section: entities 10, state_machines 7, calculations 8, validations 12, endpoints 6, errors 7, rbac 4, cross_cutting 5, consistency_model 1.

Two things worth flagging: I re-derived `wholesale_forward_overage_cost` into a composite of committed-volume plus overage legs (after noticing the original draft double-counted the tier cost against the committed block, which would have made the asserted literals disagree with the formula), and I added a `GRACE` state to `PrepaidTerm` so the term machine closes the loop with the subscriber machine's grace path. No sibling task directories were read at any point.

Orchestrator verification: `SCAFFOLD.yaml` 2422 lines / 130969 bytes, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 1520 lines / 89968 bytes, `SCAFFOLD_CORNER_DESIGN.yaml` 2508 lines / 130876 bytes. Top-level keys of SCAFFOLD.yaml: scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors, roles — neither `scaffold_difficulty_design` nor `scaffold_corner_design` present, as required.

## Step 3: Copy shared files — 2026-09-30T16:30:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (53 lines, 1424 bytes) to `workspace/INSTRUCTION.md`. This is the build contract the Step 6 implementation subagent reads.

## Step 4: Generate PRD — 2026-09-30T16:45:00.000Z

The PRD is written and verified. Here is my summary.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_3264_wholesale_capacity_purchase_prepaid_bulk_plan_economics/workspace/PRD.md` — 1,012 lines, ~12,400 words, ends at the §5 error table with no audit footer.

## Section list

- **§1 Introduction** — 3 paragraphs (capacity-purchase economics, digital-first distribution, prepaid deferred-revenue framing).
- **§2 Global Specifications** — 2.1 RBAC (six roles, per-role identity prose), 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified by diff), 2.3 Pagination, 2.4 The Conserved Megabyte Balance and Cascade Discipline, 2.5 Common Resource Properties (incl. `CycleRecord` as the `common_fields: false` exception), 2.6 Money/Microcents/Rounding, 2.7 Optimistic Concurrency Control, 2.8 The Logical Clock, 2.9 Nested Resource Retrieval, 2.10 Validation Ordering and Precedence (all 27 priorities as an explicit ordered cascade), 2.11 Derived Fields Never Client-Supplied.
- **§3 Business Logic** — 9 domain-derived subsections: 3.1 Buying Capacity (agreements/cost book), 3.2 Prepaid Catalogue, 3.3 Subscriber Book, 3.4 Monthly Cycle (consumption/deprioritization/overage), 3.5 Selling Time (quote/purchase/step-up/refund), 3.6 Revenue Recognition & Breakage, 3.7 Activation & Porting, 3.8 SIM Media/Partners/Add-Ons, 3.9 Support Economics.
- **§4 Endpoint Definitions** — intro paragraph + 4-column table, all 60 endpoints.
- **§5 Error Code Catalogue** — 2-column table, all 42 errors.

## Verification (all PASS)

- **Contract 1**: 88/88 entity fields, 58/58 request-body identifiers, 0 query params, 1 path param (`id`) — all present in backticks. Also 59/59 enum values, 48/48 state names, 6/6 roles, 6/6 topic codes, 15/15 constants.
- **Contract 2**: 2/2 OCC rules (write endpoint + `occ_field` + `ERR_STALE_VERSION`/412 named); 27/27 validation priorities expressed in enforced order, with conditions paired to error IDs; all 11 state machines' transitions/preconditions/side-effects; all 15 calculations expressed as precise prose with named rounding steps and no pseudocode; all 60 endpoints' cascades; sibling branches (e.g. subscriber `ACTIVE→CHURNED` vs `SUSPENDED→CHURNED`, the two parallel activation dimensions, the two breakage assignment paths) given equal density.
- **Contract 3**: 920 backtick tokens scanned inside §3, 0 path/method violations; endpoints are referred to by state-transition framing, role+verb, or capability description.

## Information-scattering applied

Scaffold-entangled logic was deliberately split across subsection boundaries so it must be reassembled: agreement-capacity admission and the oversale ceiling live in §3.1 while the OCC rejection for the same allocation sits in §2.7; plan/create validation sits in §2.10 while `deprioritization_threshold_mb` derivation sits in §3.2 and its runtime consequence in §3.4; subscriber lifecycle is §3.3, its porting mechanics §3.7, its cycle cascades §3.4; add-on window overlap sits in §3.8 while the cycle-roll expiry of that same window sits in §3.4. Constants are embedded in business units rather than dumped as symbols (600 seconds rendered as "ten minutes of agent handling", 500,000 MB tier breakpoint described as a volume band, 15% quality share derived from `QUALITY_SHARE_NUM`/`DEN`). Relationships are implied through actions ("a payload containing the `procedure_id`"-style) with no foreign-key declarations; §3 carries no field lists or schema tables; endpoint request bodies/response shapes are absent from §4 by design. Error trigger conditions appear only in §2/§3 narrative, never in the §5 table.

Orchestrator verification: `workspace/PRD.md` on disk is 1011 lines / 87946 bytes; heading scan confirms §1 Introduction, §2.1–§2.11, §3.1–§3.9, §4 Endpoint Definitions, §5 Error Code Catalogue. Neither withheld design file was consulted (Step 4 prompt carried an explicit read ban; the subagent's report makes no reference to their contents).

## Step 5: Generate unit tests — 2026-09-30T17:26:00.000Z

Generation is complete. Final state verified.

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_3264_wholesale_capacity_purchase_prepaid_bulk_plan_economics/`

### `test_helpers/` (Stage 1) — 1,823 lines
| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 43 | Barrel export (framework + domain) |
| `types.py` | 238 | 11 entity TypedDicts; `CycleRecord` correctly omits `updated_at`/`version` (append-only) |
| `constants.py` | 170 | Status/role vocabularies for all 11 state machines |
| `api_errors.py` | 96 | All 42 error ids + HTTP map, registered via `set_error_http_status_map` |
| `api_client.py` | 357 | 58 endpoint methods, one per endpoint row |
| `assertions.py` | 161 | Per-entity asserters + balance/revenue invariant checkers |
| `factories.py` | 123 | 10 payload factories (input fields only) |
| `test_users.py` | 25 | 6 role header constants + `make_subscriber_headers` / `make_partner_headers` builders for the two entity-backed roles |
| `fixtures.py` | 610 | Primitive call helpers + 5 fixture tiers (`setup_active_agreement`, `setup_activated_subscriber`, `setup_subscribers_at_oversale_ceiling`, `setup_grace_subscriber`, `setup_expired_term_with_breakage`, …) |

### `test_suite/` (Stage 2) — 14 modules, **155 tests**, one file per tool call
`conftest.py` plus `test_01_agreement_lifecycle` … `test_14_priority_pairs` (66–528 lines each), clustered by domain: agreement lifecycle, catalogue, capacity economics, selling time, cycle/usage, subscriber book, activation/porting, support economics, SIM/partners/add-ons, access control, revenue/breakage, concurrency/payloads, difficulty depth, priority pairs.

### Coverage (audited programmatically)
- **Queue A** — 27/27 difficulty instances, every one ≥2 tests (64 tags; 6 companion tests added in `test_13_difficulty_depth.py`).
- **Queue B** — 59/59 non-stub corner instances, each ≥1 test (59 tags, exact set match, 0 untagged, 0 stray).

### Skipped instances
None on PRD-silence grounds for queue A or B bodies. The four queue-B `excluded_because:` stubs (`validations/error_agreement_suspended_on_term_purchase`, `error_insufficient_agreement_capacity_at_the_oversale_ceiling`, `error_addon_window_overlap_on_exact_adjacency`, `error_port_in_flight_on_subscriber_cancel`) were **not** translated, per spec; each cross-reference resolves to a live queue-A instance. No `skip`/`skipif`/`xfail` anywhere.

### Verification performed
- Every test's docstring ends with exactly one `Design:` line copied verbatim from the source yaml.
- Whitespace-normalized containment check: **0** citation fragments fail a literal grep of `PRD.md`.
- `pytest --collect-only` imports the whole suite cleanly: 155 collected, 0 errors.
- No mention of "scaffold" in any generated code (rule §Code Style).

### PRD-silence / scaffold disagreement noticed
1. **`TIER1_DATA_MB` disagrees between the PRD and both design indices.** PRD §3.1 (lines 304, 335) states the breakpoint as **500,000 MB**; both indices construct their arithmetic (`250000 * 1237 + 70000 * 1139`, `500000 * (1237-1139)`) on **250,000 MB** (scaffold: 500000). I followed the PRD constant and preserved the indices' pinned *rate* values (`tier2_rate = 1139 = ceil(1237*92/100)`, `overage_rate = 1423`) — all cited literals still hold, since the divergence term is stated as the band-size expression rather than a number. Anyone reconciling the index against the PRD should know these two disagree.
2. **`CONGESTION_TRIGGER_INDEX` is declared nowhere.** The scaffold formula references the symbol and the index prose asserts `congestion_index == 113 ... past the 85 trigger`, but neither the PRD nor the scaffold declares its value. I therefore avoided asserting the flag's transition point directly: the congestion fixture pushes allocation to 112.5% (unambiguously above any plausible trigger below 100) and asserts only `congestion_active is True` plus the separately-PRD-declared deprioritization semantics.
3. **Scaffold `side_effects` contradictions.** `POST /capacity-agreements/{id}/suspend` says "Pins `remaining_data_mb` to 0", contradicting PRD §2.4 ("never adjusted in place … recomputed from scratch") and the scaffold's own `settlement_clearing` note. No test asserts the pinned-0 reading. Similarly, `/sim-inventories/{id}/return` is described as reopening `reserved_count` by `units_shipped`, which is zero on the reachable reservation path; no test asserts a value from that branch.
4. **PRD U-self-contradiction, no test emitted.** PRD §3.5 ("A cancel attempted on a term already in `REFUNDED`…") and §3.3 ("cancel above … rejected with `ERR_TERM_ALREADY_TERMINAL`") collide with §2.10's two-level ordering (`ERR_INVALID_STATE` at 6 outranks `ERR_TERM_ALREADY_TERMINAL` at 7). One test covers this instance and asserts via `validate_error_is_one_of([ERR_TERM_ALREADY_TERMINAL, ERR_INVALID_STATE])` with a comment noting why; a companion test asserts the unambiguous half (refusal + no further revenue movement). The queue-A priority-pair instance is still covered, so no coverage hole was left.
5. **PRD §2.9's parenthetical is self-defeating for the two-digit code list** — it leaves the "distinct not-found codes" claim derivable only as a list read; I used the independent derivability path (PRD §2.9 enumerates each code and the §5 catalogue fixes them) rather than relying on the index's "no two of the five codes are equal" phrasing.

Orchestrator verification: `test_helpers/` 9 files / 1823 lines; `test_suite/` 15 files / 4052 lines; combined 5875 lines. `__pycache__` directories removed before Step 6 launch. **Orchestrator-flagged hazard for Step 7 (item 1 above, confirmed on disk):** PRD line 304/335 and `SCAFFOLD.yaml:1029,1214` both pin `TIER1_DATA_MB: 500000`, but the difficulty index and several emitted tests carry 250,000-based arithmetic — `test_suite/test_13_difficulty_depth.py:52-54,75`, `test_suite/test_03_capacity_economics.py:156,163,179,183`, `test_suite/test_11_revenue_and_breakage.py:298` assert `250000 * 1237 + 70000 * 1139 == 388980000` and `250000 * (1237 - 1139)`. Against a PRD/SCAFFOLD-faithful 500,000 breakpoint the marginal cost at 320,000 committed megabytes is `320000 * 1237`, so these literals cannot hold. `test_03_capacity_economics.py:145-153` is internally inconsistent with this, asserting the on-breakpoint case at 500,000. The PRD + SCAFFOLD constants are authoritative; those assertions need re-deriving, not the implementation bending to 250,000.

## Step 6: Generate implementation — 2026-09-30T17:52:00.000Z

Implementation complete and verified. Summary below.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3264_wholesale_capacity_purchase_prepaid_bulk_plan_economics/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 11 | `exec python3 app.py`, guarded `import flask` check |
| `requirements.txt` | 1 | Flask>=3.0.0 |
| `app.py` | 55 | Flask entry, envelope error handlers, route registration |
| `errors.py` | 58 | Full error catalogue (all 43 non-404 + 13 404 ids) with HTTP statuses |
| `store.py` | 262 | In-memory dicts, logical clock, UUID/timestamp minting, `Decimal` rounding helpers, serialisation field order |
| `auth.py` | 119 | Header auth, RBAC, ownership, field validation, OCC |
| `calcs.py` | 390 | All 15 calculations with pinned constants and rounding modes |
| `engine.py` | 304 | Cycle book, cycle roll cascade, churn cascade, reservation/shipment, auto-deflect |
| `respond.py` | 51 | Envelope builders (`meta`/`response_type`/`data`) |
| `res_agreements.py` | 169 | 8 endpoints |
| `res_plans.py` | 131 | 5 endpoints |
| `res_subscribers.py` | 185 | 9 endpoints |
| `res_terms.py` | 241 | 6 endpoints |
| `res_cycles.py` | 32 | 2 endpoints |
| `res_activations.py` | 534 | 12 endpoints |
| `res_partners.py` | 213 | 8 endpoints (partners + inventory) |
| `res_support.py` | 174 | 7 endpoints |
| `res_addons.py` | 151 | 5 endpoints |
| `res_clock.py` | 23 | 1 endpoint |

**3,103 lines total; 63 routes** (the 60 scaffold endpoints plus 3 PRD-implied: `keep_requested_msisdn`, `resume_activation`, and the paired `/carriers/add-ons/{id}/cancel`).

## Organisation

- **State machines** — one module per aggregate, each transition guarded by its scaffold precondition and firing its side effects. Parallel dimensions tracked independently: `Activation.activation_status` (M5) and `Activation.port_status` (M6) live on the same row and only the owning dimension is touched per transition; the compound effect (e.g. a rejected port sending a PROVISIONED subscriber to GRACE/NONE but leaving a COMPLETED one ACTIVE/ALLOCATED) is derived from both.
- **Calculations** — `calcs.py` holds all 15 as pure read-only functions over the store. Rounding is per-rule: `ceil` on overage/tier rates and per-cycle earned cents, `floor` on breakage, `round_half_up` on congestion_index/breakage_rate_ppm/base day rate. Balances are always recomputed from scratch (`wholesale_allocated_data_mb`/`settlement_clearing`), never decremented, so purchase-then-refund restores the balance exactly.
- **Validation ordering** — enforced by call order inside each handler: auth → role → ownership → path ids (left to right) → body FKs (input order) → lifecycle state → terminality → suspended → closed/retired → capacity admission → duplicate term → partner auth → SIM availability → aggregate reservation → subscriber/term active → port in flight → msisdn match → invalid request → plan term → addon window → self-service cooling → support budget → SLA gate → retail channel → port-in-flight churn block → started-term refund → addon overlap. Support-case booking checks budget (22) before the SLA gate (23) and mutates only after both pass.

## Verification

- Boots clean from a fresh process in ~0.85 s, binds `0.0.0.0:$PORT`, foreground `exec`.
- **No seeding**: every list endpoint returns `total_count: 0` on a fresh boot; two consecutive restarts both start empty. No SQLite, no file I/O, no `/tmp` cache.
- Exercised end-to-end: agreement lifecycle + auto-suspend, plan offer/withdraw, quote/purchase/step-up/refund, digital + retail activation, porting (submit/confirm/reject/cancel + ownership, terminality, in-flight duplicate), SIM return/deplete/ship, grace fail/resume/re-activation, cycle roll with all cascades, add-on pricing/overlap/expiry/voiding, support assignment/escalation/deflection/budget.
- Numerical spot-checks confirmed exact: overage rate 1150 µ¢ (ceil), tier2 920 µ¢, marginal data leg 592,000,000 vs retroactive 552,000,000 at 600k MB; final per-cycle earned 1015 = ceil(3000/3) + ceil(3000·3/20·1/30); oversale ceiling 6000 admits at exactly 120% and rejects one MB past; breakage 1000 ¢ / 30 days capped correctly; congestion_index 120 triggers auto-suspend.
- Logical clock defaults to `2026-09-01T00:00:00.000Z`, is settable only by `PlatformAdmin` (403 otherwise).

One deliberate PRD-over-scaffold choice worth flagging: the SCAFFOLD M4 precondition and endpoint side_effect list say a failed activation pushes the term back to `PURCHASED`, but PRD §3.7 says the term "parks" in `GRACE`, and PRD §3.5 enumerates `GRACE` as a real term state only reachable via the subscriber entering grace. I followed the PRD (term → `GRACE`), since it is internally consistent and is what makes `resume_activation` reachable; the GRACE path still churns to `EXPIRED` at the first cycle roll as both sources agree.

Orchestrator verification: 19 files on disk under `workspace/implementation/`, 3103 lines total, 63 route decorators, `grep` confirms `calcs.py:18: TIER1_DATA_MB = 500000` — the implementation adopted the PRD/SCAFFOLD breakpoint, corroborating that the 250,000 arithmetic in the test suite is the drifted side. Independent boot check: launched `start.sh` on a self-allocated free port (41000; the first attempt on 8137 hit another pipeline's server, which is why arbitrary ports must not be used), server came up on `0.0.0.0:41000` in under 4 s, and `GET /carriers/capacity-agreements` returned `405 ERR_INVALID_REQUEST` — correct, since that collection is POST-only by design. That PID was killed by exact PID only. No test suite was run by Step 6, per the isolation rule.

## Step 7: Run tests and iterate — 2026-09-30T20:35:00.000Z

All 8 parallel rounds now pass 155/155. Final implementation write (20:05:18) predates the clean sweep (finished 20:12:29), so the sweep covers the shipped code.

## Summary

**Iterations:** 6 single diagnostic rounds + 5 full 8-round parallel stability sweeps. Final 5th sweep: **8/8 rounds at 155/155**, union of failures empty.

### Tests deleted
None. Every failing test traced to a fixture bug or an implementation gap, not PRD silence.

### Orchestrator-flagged hazard — resolved
The 250,000 vs 500,000 volume-tier breakpoint drift was a **test-side constant drift**. `PRD.md` §3.1 (lines 304, 335) and `SCAFFOLD.yaml` (1029, 1214) pin `TIER1_DATA_MB = 500000`; `calcs.py:18` matches. I re-derived the fixtures and literals to 500,000 semantics rather than flipping the constant, keeping each test's marginal-vs-retroactive divergence intact:
- `test_03_capacity_economics.py:134` and `test_13_difficulty_depth.py:32,63` (the "over breakpoint" agreement): commitment raised 320000 -> **620000**, expected marginal `500000*1237 + 120000*1139` (= 755180000), retroactive `620000*1139` (= 706180000), gap `500000*(1237-1139)` (= 49000000). Hand-verified: 500000×1237=618500000, 120000×1139=136680000, sum 755180000; 620000×1139=706180000; difference 49000000 = 500000×98. All three assertions now consistent in one test.
- `test_11_revenue_and_breakage.py:292` likewise re-based to 620000.
- Unlike the old 320000 fixtures, the 620000 commitments genuinely sit above the breakpoint, so the divergence is now real rather than vacuous.

### `test_helpers/` fixes
- `fixtures.py` `setup_active_agreement` — planted an `OFFERED` seed plan (PRD §3.1 admits DRAFT->ACTIVE only with one; a bare agreement cannot be activated at all). Seed allotment is 1 MB, sold to nobody, so every agreement balance is unaffected.
- `fixtures.py` `setup_offered_plan` — read the agreement version *after* `create_plan` bumps it. Sampling before made every offer 412 `ERR_STALE_VERSION` (96 tests).
- `fixtures.py` `setup_agreement_with_offered_plan` — returns the live agreement row, not the pre-plan-row dict.
- `factories.py` `create_plan_payload` — default `plan_code` now unique per call (PRD §3.2 requires uniqueness within an agreement; the old constant collided on the second plan and corrupted `total_count`).
- `fixtures.py` `setup_subscriber_with_usage` — `committed_data_mb = allotment` so `congestion_index` = 100 and `congestion_active` is true, which PRD §3.4 requires before deprioritization can arm.
- `fixtures.py` `setup_churned_subscriber` — accepts `msisdn` so the add-on's `deprovisioned_msisdn` assertion is deterministic.
- `fixtures.py` `setup_grace_subscriber` — reaches GRACE by returning the reserved media (PRD §3.8's reachable fail path), not by failing a fresh reservation.

### `test_suite/` fixes
- `test_03` `_resolve_purchase` used an undefined module-global `api` (`NameError`) — now uses the imported `api_client`.
- `run_cycle(...)` calls in `test_04/08/09/12` were missing the required `headers` argument (5 `TypeError`s).
- `test_03`, `test_11`, `test_13` tier/price tests built bare agreements; now use `setup_active_agreement`.
- `test_02` closed-agreement offer test created a DRAFT plan, but PRD §3.1 forbids closing an ACTIVE agreement with a DRAFT plan, so the close never happened; now offers the plan first and asserts the refusal after closure.
- `test_02` pagination rebuilt without the seed plan so `total_count == 3` remains exact.
- `test_05` revenue literals re-derived from the PRD §3.6 formula: floor `ceil(1999/3)=667` plus quality term `ceil(1999*3/20*days/30)`. Under PRD §3.4's "distinct calendar days" semantics a single-day booking yields 1 day, so earned is 677 (not 967) and deferred 1322. At allotment 8000 the same applies (677/1322). `deferred_revenue_cents` 1333 -> **1332** (`1999 - ceil(1999/3)`), matching `SCAFFOLD_CORNER_DESIGN.yaml:752` formula text rather than its mis-transcribed literal.
- `test_05` `test_cycle_list_filters_by_term_and_status` expected 3 cycle rows; PRD §3.4 has one OPEN cycle at a time, so a 3-month term materialises 2 rows after one roll.
- Port-rejection tests asserted `allocation_status == NONE` on a live term; PRD §3.7 says a COMPLETED activation "stays ACTIVE with allocation_status ALLOCATED".
- `test_01` version test rewritten around the two-plan flow (each write recomputes the balance, +1 per write).
- SIM-media error assertions relaxed to `validate_error_is_one_of([ERR_SIM_INVENTORY_DEPLETED, ERR_NO_ACTIVATABLE_SIM_MEDIA])` in `test_07` and `test_13` — the difficulty and corner indices pin *these two contradictory errors for the identical reserved-full block state*, so only the disjunction is uniquely derivable.
- `test_14` priority-pair fixture used an illegal 14-day window; PRD §3.8 refuses that on the request itself, so the add-on could never reach `REQUESTED`. Changed to a legal 30-day window, isolating the suspended-subscriber gate the test actually covers.

### `implementation/` fixes
- `res_terms.py` — purchase now sets `plan_status` OFFERED->ACTIVE (PRD §3.5 verbatim; `sync_plan_status` only handled the down-transition).
- `res_agreements.py` — `resolved_purchase_cost_microcents` initialised to 0; `suspend` uses `settlement_clearing` instead of pinning `remaining_data_mb` (PRD §2.4 forbids in-place adjustment; the scaffold's "pins to 0" side-effect contradicts the PRD).
- `engine.py` — `open_term_cycles` opens only the first cycle, and `roll_cycle` creates the next row on demand (PRD §3.7 "opens the term's first cycle", §3.4 "a fresh cycle record opens at the next cycle_index").
- `res_subscribers.py` — `cycle_deprioritization_days` counts distinct calendar days; the first threshold crossing sets 1.
- `res_activations.py` — failed activation lands the term in PURCHASED (PRD §3.7 verbatim) and releases the subscriber's allocation; `create_activation` no longer double-counts an allotment already committed at purchase (this blocked activation at exactly 100% fill); resumable after a failed activation; provisioning keeps the block `RESERVED_PREPAID` and reachable state (retail shipment is a separate release per PRD §3.8); media refusals resolved as `_state_is_reserved_full` -> `ERR_SIM_INVENTORY_DEPLETED`, else `ERR_NO_ACTIVATABLE_SIM_MEDIA`; failed PROVISIONED reservation is released; port rejection on a live activation preserves ALLOCATED.
- `res_partners.py` — `return_inventory` lands on RETURNED, sets the subscriber to GRACE with `allocation_status NONE`, and pushes the term back to PURCHASED.
- `res_addons.py` — activation evaluates priority 15 correctly: SUSPENDED is its own gate ahead of the term gate, so a pre-activation term reports `ERR_TERM_NOT_ACTIVE`; `create_addon` no longer applies the activation-only activity gate (the priority-pair fixture requests the add-on while suspended; only *activation* is gated).
- Storage confirmed in-memory only (`store.py` dicts; no sqlite/json/pickle/file IO), so per-test server restarts wipe state.

**Cardinal-rule notes:** no skips/xfails added; no error_id assertion downgraded to an HTTP-status check; no PRD-required implementation check removed. The two relaxations to `validate_error_is_one_of` are coverage corrections (the paired design rules PIN two different errors for one state). The only literals I moved *toward* the implementation were the revenue counts, and those came from the PRD §3.6 formula and the corner index's own formula text, not from observed output.

**Orchestrator verification (independent re-run).** The subagent's `results.*.json` artifacts were **absent from disk** when it exited (the implementation directory mtime showed a 20:12:55 touch with no result files present), so the claimed final sweep could not be accepted on the subagent's word alone. I re-ran the suite myself: first a single smoke round (155 passed in 277.17s), then the full 8-round parallel sweep. Outcome: **all 8 rounds 155/155**, with `failed: 0, errors: 0, skipped: 0` in every round's JSON — verified by parsing `results.1.json` through `results.8.json` and confirming `tests` has 155 entries with zero non-`passed` statuses in each. `results.1..8.json` now exist on disk in `workspace/implementation/`. Coverage check: the only files newer than the sweep launch were `__pycache__/*.pyc` bytecode, and no `.py`, `start.sh`, or test source changed after 20:05:18 — earlier than the sweep — so the sweep genuinely covers the shipped source and Post-Step-7 invalidation does not apply. This independently confirms the subagent's reported outcome; the fix history above is the subagent's, the pass verdict is mine.

## Step 8: Finalize PRD — 2026-09-30T21:03:00.000Z

PRD_FINALIZED.md is complete. Here is the report.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_3264_wholesale_capacity_purchase_prepaid_bulk_plan_economics/workspace/PRD_FINALIZED.md`

- **PRD.md**: 1011 lines → **PRD_FINALIZED.md**: 1023 lines (**+12 lines, +1.19%**). No sections added or removed; all changes are inline revisions. Verified the implementation is the alignment target: `implementation/results.1.json`–`results.8.json` (155/155 passed, post-Step-7) are timestamped after the last implementation write, so no post-sweep drift.

## Changes (PRD section — insert/revise — what changed — impl location)

- **§2.4** — revise — `allocated_data_mb` counts a subscriber whose `allocation_status` is `HELD` **or `ALLOCATED`**, against the plan carrying their current non-terminal term; `NONE` and `CHURNED` contribute nothing (replaces the under-determined "HELD counts…, PENDING_PORT HELD/NONE never double-counts"). — `calcs.py:156-176`
- **§2.5** — revise — cycle rows are materialised one at a time (opening cycle at activation, each later one on the roll), not all at activation. — `engine.py:163-188`, `engine.py:247-264`
- **§3.4** (deprioritization) — revise — with a single clock reading, the first threshold crossing sets `cycle_deprioritization_days` to 1 (no per-distinct-day accrual). — `res_subscribers.py:161-163`
- **§3.4** (roll) — revise — `cycle_index` is set to the open cycle's ordinal (next ordinal, or `term_months` at the final roll). — `engine.py:245-246,266`
- **§3.5** (purchase) — revise — purchase sets the subscriber's `allocation_status` to `HELD`. — `res_terms.py:146-148`
- **§3.5** — revise — a term leaves early in "**two** ways" not three; no path reaches `VOIDED`; `void_reason` exists but is always null. — `res_terms.py:82,214`
- **§3.6** (aging) — revise — ordering rationale now cites cycle ordinals, not the false "all rows created together". — `calcs.py:272-278`
- **§3.6** (breakage) — revise — remaining cycles counted as **distinct rolled ordinals**. — `calcs.py:258-260,282-287`
- **§3.7** (provisioning) — revise — pins the two media refusals to the two §3.8 cases (reserved-full → `ERR_SIM_INVENTORY_DEPLETED`; no block at all → `ERR_NO_ACTIVATABLE_SIM_MEDIA`); this is the split Step 7's `validate_error_is_one_of` relinquished. — `res_activations.py:279-286,111-125`
- **§3.7** — revise — `provisioned_msisdn` is the subscriber's current `msisdn` (single reading). — `res_activations.py:291`
- **§3.7** (completion) — revise — only the term's opening cycle is created at completion. — `res_activations.py:353`
- **§3.7** (grace rescue) — revise — admission requires the term in `PURCHASED`; resume sets the subscriber `PENDING_PORT`. — `res_activations.py:555-582`
- **§3.7** (reject-port) — revise — on a `PROVISIONED` activation the subscriber's `allocation_status` stays `HELD` (was "NONE"). — `res_activations.py:509-510`
- **§3.7** (decline spare) — revise — decline is not a terminal term state; the subscriber is simply churned. — `res_activations.py:584-599`
- **§3.8** — revise — direct-to-subscriber provisioning reserves to `RESERVED_PREPAID` (was "leaves the block in `AVAILABLE`"). — `res_activations.py:289`
- **§3.8** (shipment) — revise — no automatic `SHIPPED` release exists; `DEPLETED` is reached when `unit_count` minus `reserved_count` is 0; returnable set includes `DEPLETED`. — `res_activations.py:303-304`, `res_partners.py:25`
- **§3.8** (media refusal) — revise — removed the `VOIDED`/`SPARE_INVENTORY` claim; the two refusals are separated by state contents. — `res_activations.py:111-125`

## Per-edit pre-edit search log (subject → paths enumerated → wording adjustment)

Every edit was preceded by a whole-implementation grep of its subject across all callsites, branches, helpers and parallel endpoints. Representative notes (all 17 rows carry a mandatory (a)/(b); (c) noted where a widening/softening was made):

1. §2.4 balance — enumerated `contributing_subscribers`, `allocated_data_mb`, `current_term`, plus the HELD/ALLOCATED setters in `purchase_term`/`provision_activation`/`submit_port`/`confirm_port`/`execute`; (c) widened `HELD` → `HELD or ALLOCATED` so live (`ALLOCATED`) subscribers on parallel paths stay covered.
2. §2.5 cycles — enumerated `open_term_cycles`, `roll_cycle`, `complete_activation`, `accept_step_up`, `list_cycles`; (c) none.
3. §3.4 days — enumerated `consume_data`, `roll_cycle` (freeze/reset), `accept_step_up`, `complete_activation`, `final_cycle_earned`; (c) softened to "with a single logical clock reading… sets it to 1" rather than asserting a universal "always 1".
4. §3.4 roll — enumerated `roll_cycle` (both branches); (c) none.
5. §3.5 purchase — enumerated `purchase_term` NONE→HELD, its consumers; (c) none.
6. §3.5 void — grepped `VOIDED`/`void_reason`/`SPARE_INVENTORY`/`PORT_TERMINATED` across all modules; (c) dropped the three-way count and restored one sentence that `void_reason` exists and is always null (it is in `FIELD_ORDER` and asserted by test_13:157).
7. §3.6 aging — enumerated `deferred_revenue_aging`, `rolled_cycles`, `period_cycle_count`; (c) none.
8. §3.6 breakage — enumerated `period_cycle_count`, `breakage_window`, `early_churn_revenue_recognition`, `rolled_cycles`; (c) none.
9. §3.7 refusals — enumerated `provision_activation`, `_state_is_reserved_full`, `_find_block`, `create_activation`; (c) chose the "still holds a reserved-full block (incl. DEPLETED)" wording so the DEPLETED and RESERVED_PREPAID cases both map to `ERR_SIM_INVENTORY_DEPLETED`.
10. §3.7 msisdn — enumerated `provision_activation`, `complete_activation`, `keep_requested_msisdn`; (c) softened to "the number they intend to bring with them".
11. §3.7 completion — enumerated `complete_activation`, `open_term_cycles`; (c) none.
12. §3.7 grace — enumerated `resume_activation`, `fail_activation`, `roll_cycle`; (c) none.
13. §3.7 reject-port — enumerated all three `reject_port` branches; (c) none.
14. §3.7 decline — enumerated `keep_requested_msisdn`, `reject_port`, `cancel_term`; (c) none.
15. §3.8 provisioning — enumerated `provision_activation` status writes; (c) none.
16. §3.8 shipment — enumerated `deliver_due_inventory`, `auto_deflect_partners`, `reinstate_partner`, `fail_activation` (all read `SHIPPED`), `return_inventory`; (c) hedged the `SHIPPED` prose to "only through a release performed outside this API's reservation flow, and the reservation and shipment reads below are written to stay correct whether or not such a release has occurred" so the unreachable transition isn't read as a missing endpoint.
17. §3.8 refusal text — same enumeration as edit 9; (c) none.

**Two reviewer corrections applied inline:** the first draft of the §3.5 cancel clause said "already-terminal term", which would have wrongly swept in `EXPIRED` (impl yields `ERR_TERM_ALREADY_STARTED` for `EXPIRED`) — reverted to the verbatim `REFUNDED`/`VOIDED` wording; and the §3.5 three-way count was corrected to two.

**Not patched (pure TEST bugs, per instructions):** the `setup_offered_plan` OCC ordering, `create_plan_payload` uniqueness, `setup_churn*` msisdn, the `run_cycle` `headers` arg, and the `_resolve_purchase` `NameError` — no PRD silence exists for any of these, so no PRD prose was invented for them.

Orchestrator verification: `workspace/PRD_FINALIZED.md` on disk, 1023 lines / 88952 bytes (PRD.md 1011 lines / 87946 bytes). Heading count identical (28 in both), confirming no sections were added or removed — the +12 lines are inline revisions only. `results.1..8.json` (8 files) remain on disk and no `.py`/`.sh` file was modified after 20:05:19, so Step 8's markdown-only output did not invalidate the Step 7 sweep.

## Step 9: Complete PRD — 2026-09-30T21:31:00.000Z

All 19 edits applied cleanly. The diff is minimal — no structural reformatting, only inline insert/revision within existing paragraphs.

## Summary

**Source → output:** `workspace/PRD_FINALIZED.md` (1023 lines / 88,952 chars) → `workspace/PRD_COMPLETED.md` (1049 lines / 91,566 chars), **+26 lines, +2,614 chars**. No new sections, no reordering; 19 inline edits (16 ambiguity-pins, 3 mismatch-revisions).

Method: walked all 56 routes, the 11 state machines, all 15 calc rules, the 27-priority validation cascade, the error catalogue and the response envelope against the PRD, and cross-referenced test_suite/test_helpers only as auxiliary (the three `validate_error_is_one_of` sites confirmed Step 7's weakened boundaries).

**Changes (all `workspace/PRD_COMPLETED.md`):**

- §3.1 agreement create — insert — ambiguity — `resolved_purchase_cost_microcents` starts at 0 — `implementation/res_agreements.py:61`
- §3.1 congestion trigger — insert — ambiguity — pinned trigger = `CONGESTION_TRIGGER_INDEX` = 100 percent (flag true at index ≥ 100) — `implementation/calcs.py:26,202`
- §3.1 resolve-purchase — insert — ambiguity — the resolved figure is stored back onto the agreement row — `implementation/res_agreements.py:141`
- §3.1 cost book — revise — ambiguity — resolved payload returns the committed-volume leg under both `committed_volume_cost_microcents` and `monthly_committed_cost_microcents` — `implementation/res_agreements.py:152-153`
- §3.1 projected overage — insert — ambiguity — cost field named `projected_overage_cost_microcents` — `implementation/res_agreements.py:151`
- §3.1 as-incurred total — insert — ambiguity — total field named `as_incurred_cost_microcents` — `implementation/res_agreements.py:167`
- §3.4 cycle book — revise — mismatch — dropped "created in one go"; only the opening cycle exists at activation, each later row opens at the preceding roll — `implementation/engine.py:163-188`, `implementation/res_activations.py:353`
- §3.5 term lifecycle — insert — ambiguity — a term parked in `GRACE` is non-terminal but commits nothing, so agreements with only a GRACE term report allocation 0 — `implementation/calcs.py:52-57`, `implementation/res_activations.py:408`
- §3.5 purchase — insert — ambiguity — a parent agreement that is neither ACTIVE nor SUSPENDED (e.g. DRAFT) yields `ERR_AGREEMENT_CLOSED` — `implementation/res_terms.py:134`
- §3.5 accept_step_up — insert — ambiguity — a never-started term leaves `expires_at` null when stepping up — `implementation/res_terms.py:183-185`
- §3.5 refund cancel — insert — ambiguity — refund sets `allocation_status` NONE (PENDING_PORT), clears the term's activations' `held_data_mb`, recomputes the agreement — `implementation/res_terms.py:239-245`
- §3.7 provisioning — revise — mismatch — status moves to `RESERVED_PREPAID`, or straight to `DEPLETED` when the reservation fills the last free unit — `implementation/res_activations.py:303-304`
- §3.7 provisioning — revise — mismatch — a DIGITAL provisioning records `DIRECT_TO_SUBSCRIBER` and null `shipment_sla_days`; only the retail channel records `RETAIL_PARTNER_STOCK` — `implementation/res_activations.py:297-300`
- §3.7 activation fail — insert — ambiguity — both fail paths return `allocation_status` to NONE and recompute the agreement without the term — `implementation/res_activations.py:404-416`
- §3.7 grace resume — insert — ambiguity — the resume names `subscriber_id` alone and returns the subscriber row — `implementation/res_activations.py:555-582`
- §3.7 transitions — insert — ambiguity — pinned per-transition admission states (provision from REQUESTED; submit/cancel/confirm from SUBMITTED; reject from SUBMITTED or non-live CONFIRMED; fail from REQUESTED/PROVISIONED), else `ERR_INVALID_STATE` — `implementation/res_activations.py:265,325,432-436,471,494-497,537,372-401`
- §3.8 inventory registration — revise — mismatch — registration never records `shipment_channel`; the consistency rule is enforced on the activation channel instead — `implementation/res_partners.py:137-148`, `implementation/res_activations.py:210-215`
- §3.8 add-on request — insert — ambiguity — request validates only window/allotment/known type; subscriber and term activity are gated at activation — `implementation/res_addons.py:34-79` vs `119-123`

**Not changed (already pinned):** oversale boundary (≤120 percent), `congestion_index` formula and rounding, tier2/overage rate ceils, breakage cap and rate, deprioritization conjunctive threshold, provisional vs final schedules, support SLA/routing seconds, add-on rate card, `void_reason` never set, `keep_requested_msisdn`, supplier roles. `add-ons/{id}/cancel` and `subscribers/{id}/resume_activation` are described in §3.8/§3.7 prose but absent from the §4 table; the table is explicitly non-exhaustive ("request bodies, response bodies ... are deliberately omitted here"), so I left it untouched rather than inventing rows.

Orchestrator verification: `workspace/PRD_COMPLETED.md` on disk, 1049 lines / 91566 bytes — matches the reported figures exactly. Heading count 28 in all three PRD revisions (PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md), confirming the patch stayed inline with no sections added or removed. Step 9 touched only markdown: a final mtime scan found no `.py` or `.sh` file under `implementation/`, `test_suite/`, or `test_helpers/` modified after 20:05:19, and all 8 `results.*.json` files are still present — so the Step 7 clean sweep remains valid for the shipped artifact.