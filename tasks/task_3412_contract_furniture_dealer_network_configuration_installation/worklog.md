# Worklog — task_3412_contract_furniture_dealer_network_configuration_installation

## Step 1: Create Task Directory — 2026-10-01T20:04:00.000Z

Task directory pre-allocated per command args: `./tasks/task_3412_contract_furniture_dealer_network_configuration_installation/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created. Difficulty instruction "Generate task much harder than expert level!" will be passed to prd-bench-scaffold-generator only.

## Step 2: Generate Scaffold — 2026-10-01T21:25:00.000Z

All checks are green. The "unused capture" lines are response-value bindings referenced by field name in the assert prose (per the §1.8 contract, asserts cite exact field names + literals) — documentary, not violations; lint and closure are clean.

Final state of the verification battery:

- **YAML parse check**: all three files `yaml.safe_load` clean; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` has exactly the single top key `scaffold_difficulty_design`, `SCAFFOLD_CORNER_DESIGN.yaml` exactly `scaffold_corner_design`, and `SCAFFOLD.yaml` contains neither design key.
- **scaffold_lint.py verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (809 calls scanned across 21 §1.8 + 51 §1.9 instances; 40 endpoints, 10 entities.)
- **My own deeper audit**: every `grounds:` entry resolves to a declared calculation/state-machine/validation/entity-field/error/concurrency-rule/endpoint; every error is referenced by ≥1 validation or transition; every endpoint role exists in §1.7; both OCC rules have `expected_*_version` as required input plus version-bump side effects; no forbidden race vocabulary; zero unbound `${var}` placeholders and no duplicate captures in any recipe.
- **Literal re-derivation**: every worked-example number was recomputed from SCAFFOLD.yaml's own pinned constants — BOM per-unit costs (85837/104737/180737/66300/125000), the rounding trap (270387+90129=360516 vs naive 360515), tier math (22500000/21250000/11250000/10625000/11137500/106250 at the exact 25000000 boundary), fabric upcharge (96137, 86523), lead times (52/45/31/35/40) — all OK. Date math verified: +52d=2026-10-23, +2d notice boundary 2026-09-03, transit boundary 2026-12-11, parts warranty +1826d=2031-12-01, labor +366d=2027-12-02, parts horizon 2026-10-05+2557d=2033-10-05, punch escalation Thu 2026-12-03 → business age 4 on 12-09 (not escalated) vs 5 on 12-10 (escalated).
- **Foreign-domain grep**: dealer 725, configuration 396, phase 395, agreement 295, territory 147, punch 124, fabric 109, installation 83, warranty 75, elevator 45, workstation 30, union 28; foreign nouns (hospital/invoice/loan/flight/etc.) = 0 hits.

Design highlights (much-harder-than-expert via depth, not endpoint count): provisional-vs-final tier pricing where a single order tips itself across a tier boundary; per-line-then-sum rounding pinned against the merged-quantity trap; tier↔total circular dependency resolved by pinned evaluation order; family×fabric lead-time matrix with unit-count queue tiers; forward-only product-line lifecycle with a 2557-day parts-support horizon that interleaves correctly with the 1826-day parts warranty; floor/phase sequencing with a punch-severity gate; two interval semantics (15-minute-buffered elevator exclusivity vs aggregate zone-crew capacity); dealer-suspension and order-cancel cascades; OCC on spec lock and order submit; three disjoint validation-priority conflict pairs (state>temporal, referential>constraint, safety>temporal); logical clock pinned to default 2026-09-01T00:00:00Z.

result: Task 3412 scaffold complete and clean — /home/ubuntu/github/CodingPRD/tasks/task_3412_contract_furniture_dealer_network_configuration_installation/{SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml}: 40 endpoints, 10 entities, 10 state-machine entries (9 entities; InstallationPhase declares two status dimensions), 7 calculations, 29 validations, 38 errors, 3 roles, 2 OCC concurrency rules; 21 difficulty instances (all 9 rules ≥2) + 64 corner entries (51 live, 13 excluded-because stubs); YAML parse OK on all three; scaffold_lint.py VERDICT: clean lint; foreign-domain grep confirms the contract-furniture domain throughout.

Orchestrator spot-check: all three YAML files present (81K/89K/129K), yaml.safe_load clean, top-level keys correct, `endpoints:` list length 40, dealer|workstation|fabric grep = 116 hits in SCAFFOLD.yaml. Hand-back claims verified against source.

## Step 3: Copy Shared Files — 2026-10-01T21:29:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T21:38:00.000Z

PRD generation complete and verified. Summary follows.

**PRD path:** `/home/ubuntu/github/CodingPRD/tasks/task_3412_contract_furniture_dealer_network_configuration_installation/workspace/PRD.md`
**Line count:** 304

**Section list:**
- §1 Introduction (3 paragraphs: network context, configure-to-order core, physical execution/after-sale)
- §2 Global Specifications: 2.1 Roles & Access Control, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties & OCC, 2.6 Money/Precision/Rounding, 2.7 Module Catalog: BOMs & Fabric Program, 2.8 Manufacturing & Building-Logistics Constants, 2.9 Validation Order & Error Surfaces
- §3 Business Logic (8 subsections): 3.1 Dealer Onboarding & Standing, 3.2 End Users & Volume Agreements, 3.3 Product Families & Lifecycle, 3.4 Configurations & BOM Expansion, 3.5 Project Orders (submit/price/ack/cancel), 3.6 Manufacturing Slots & Installation Phasing, 3.7 Freight Windows & Zone Crew Logistics, 3.8 Punch Lists & Warranty Service
- §4 Endpoint Definitions (4-column table, all 40 endpoints)
- §5 Error Code Catalogue (2-column table, all 38 errors)

**15-literal grep (literal → found verbatim):** 2026-09-01T00:00:00Z yes; 25000000 yes; 75000000 yes; 2557 yes; 1826 yes; 366 yes; 85837 yes; 104737 yes; 180737 yes; 66300 yes; 125000 yes; 48900 yes; 22800 yes; 3100 yes; 18700 yes — 15/15. (Also present: queue tiers 3/7/12 at 49/50/199/200, fabric deltas 0/7/14/21, upcharges 0/5/12/18, transit 4/6, capacities 120/80, notice 2 days, buffer 15 minutes, crew 10, union 4, capability 3/1/2, escalation 5 business days.)

**Logical-clock statement location:** §2.4 "The Logical Clock" (lines 78–82) — states the default 2026-09-01T00:00:00Z before any clock-set call, date-only fields comparing against the clock's UTC calendar date, and the admin-only `to_iso8601`/`current_utc` capability; repeated in the §4 row for `/_clock/set_current_utc`.

**Scaffold items omitted:** none of substance. Mechanical-only renderings intentionally not reproduced: scaffold trigger strings that embed HTTP paths (e.g. "PATCH /dealers/{dealerId} with status=SUSPENDED") are rendered as prose per Contract 3, and `complexity_profile` metadata is internal scaffolding, not a rule table.

**Hard Contract reports:**
- Contract 1 (Field-Name Coverage): all entity fields, request-body inputs, query params, path params, module inner fields (`module_type`/`fabric_grade`/`qty`), and BOM output keys (`lines`, `parts_total_cents`, `total_units`) checked mechanically — 82/82 backticked, 0 missing. PASS.
- Contract 2 (Rule Coverage): validation priority ordering expressed globally (§2.9 steps 1–8) and per-endpoint (submit gate §3.5, lock gate §3.4, reserve-slot §3.6, complete gates §3.6, window rules §3.7, claim windows §3.8); both OCC rules with `expected_order_version`/`expected_configuration_version` + `ERR_STALE_VERSION`/412 (§2.5); all 30 state-machine transitions with preconditions and side effects; all 7 calculations with formulas, constants, precision, and variants (incl. queue-boundary semantics 49→3/50→7/199→7/200→12, PROVISIONAL-vs-FINAL tier basis, BUSINESS-vs-CALENDAR punch age with the Thursday/Tuesday example, flat-vs-marginal discount note, plant reserved+available invariant); multi-entity cascades (dealer suspend/reinstate, order cancel × 4 departing states, phase cancel → windows/punches/plant release, complete bubble-up, punch-resolve auto-claim); sibling branches rendered symmetrically (verify CONFIRMED/REJECTED, review APPROVE/DENY, cancels from DRAFT/SUBMITTED/ON_HOLD/ACKNOWLEDGED). PASS.
- Contract 3 (§3 Path Purity): 523 backticked tokens scanned in §3; 0 start with `/`, 0 bare HTTP methods, 0 method+path tokens. PASS.

result: PRD.md (304 lines) generated for task_3412 from SCAFFOLD.yaml; 15/15 literals verbatim, all three hard contracts PASS, 40 endpoints and 38 errors tabulated, logical clock stated in §2.4.

Orchestrator spot-check: PRD.md on disk = 304 lines; literals 2026-09-01T00:00:00Z (2 hits), 25000000 (2), 2557 (2), 1826 (1), 85837 (1), 48900 (1) all present; dealer|fabric|punch grep = 81 hits; opens with "Contract Furniture Dealer Network API". Hand-back claims verified against source.

## Step 5a: Generate Test Helpers (split of Step 5; helpers frozen first) — 2026-10-01T21:55:00.000Z

All verification gates pass. Step 5a is complete.

result: test_helpers/ for task_3412 written, compiled, import-verified, and numerically self-checked against every design-index literal

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3412_contract_furniture_dealer_network_configuration_installation/test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 43 | barrel: framework generics + all PRD-specific modules |
| `types.py` | 289 | 18 enums + 10 entity TypedDicts (all carry id/created_at/updated_at/version — every entity has common_fields) |
| `constants.py` | 148 | domain constants, each with a PRD line citation |
| `api_errors.py` | 101 | all 37 PRD §5 error ids + HTTP map, registered with the framework at import |
| `api_client.py` | 205 | `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (40) + `api_client` singleton |
| `assertions.py` | 237 | `assert_<entity>` x10 + `assert_agreement_volume_invariant` |
| `factories.py` | 216 | payload factories, clock-reachable date defaults, auto-unique family_code |
| `calc_helpers.py` | 192 | `bom_expand`, `configuration_lead_time`, `price_order`, `tier_for_basis`, `queue_days_for_units`, `business_age_days`, `escalated_expected`, `add_calendar_days`, `module_unit_parts_cents` |
| `test_users.py` | 39 | TEST_USERS (admin canonical; dealer/enduser unbound fallbacks) + `make_{admin,dealer,end_user}_headers` |
| `fixtures.py` | 484 | ~35 primitives (identity-threaded, lenient `get_success_data`, exact 201/200) + 8 composite worlds (`setup_dealer_world` … `setup_completed_phase`, `acknowledge_chair_order`) |
| `HELPERS_MANIFEST.md` | — | frozen signature-level contract for Step 5b |

No Stage-2 directory or pytest modules were created (the skill assigns `conftest.py` to Stage 2 §2.0; the manifest tells Step 5b exactly what to put in it).

## Verification output

- `python3 -m py_compile test_helpers/*.py` → COMPILE OK (after every append and at the end)
- `python3 -c "import test_helpers"` from task root → IMPORT OK (203 names; 80-name surface spot-check passed)
- `grep -rn "test_suite\|results\.json" test_helpers/` → no matches (exit 1)
- Calc helpers reproduce every worked literal in both design indices: 25000000/22500000/21250000 (tier-tip order), 360516/324464 (per-line rounding), 11250000/10625000 (cumulative basis), lead 52/45/31/35, BOM 237974/352411 with PN-PNL-FAB merged 8×9600=76800, grade-C 96137/86523, business-age 4-then-5 across 2026-12-09→10, tier boundaries 24999999/25000000/74999999/75000000, warranty dates 2027-12-02/2031-12-01, parts horizon 2033-10-05 and 2033-09-01 (both exactly clock+2557), chair unit 125000 etc.

## Constants → PRD traceability

Every constant in `constants.py` carries its PRD.md line in a comment (table also in the manifest): clock default → line 80; BOM recipes → lines 98–102; module→category → line 96; fabric deltas 0/7/14/21 and upcharges 0/5/12/18 → line 104; capability 3/1/2 → line 106; plant capacities 120/80, transit 4/6, notice 2, queue 49/199→3/7/12 → line 110; tiers 25000000/75000000 → line 138; warranty 1826/366 → line 210; parts horizon 2557 → line 144; escalation 5 business days → line 202; buffer 15 / zone crew 10 / union crew 4 → line 112; pagination 10/1/100/0 → line 76. No dead constants — each is used by a fixture, calc helper, or a design recipe.

## Clock-reachability

All date-bearing recipes in both indices are reachable from the 2026-09-01 default with forward-only clock moves; the manifest documents this and the punch-escalation weekday chain (2026-12-03 is a Thursday given the Tuesday default — business age 4 on 12-09, 5 on 12-10, matching the design's asserts exactly).

## Design-index issues found (resolutions for Step 5b)

1. **PN-WRK-SRF divergent recipe pricing (real bug caught by self-check):** the worksurface is 15800c in workstation recipes but 21500c in PRIVATE_OFFICE. The design's pinned `parts_total_cents == 352411` proves extended amounts must sum each contribution's *own* recipe price. `bom_expand` implements that and returns `unit_list_price_cents=None` for divergent parts; per-line JSON key names (`total_qty`/`extended_cents`) are not PRD-pinned, so the manifest warns Step 5b to assert `parts_total_cents`/`total_units` exactly and treat line-field names as advisory.
2. **Off-by-one in corner index prose:** `val_parts_support_boundary_ok_then_rejected` says "warranty still valid until 2036-10-06" for a 2031-10-06 completion; true arithmetic (leap days 2032 and 2036 inside the span) gives 2036-10-05. Asserted behavior is unaffected (both far past the 2033-10-06 rejection point). Helpers are authoritative.
3. **`sm_deliver_before_production_date_rejected` has an empty `trigger:`** — the intended call is obviously `POST /phases/{id}/start-install` at clock 2026-09-01 (production 2026-11-02). Step 5b should supply that trigger and note PRD does not name the error id for early start-install on a SCHEDULED phase (only for PLANNED) — a two-reader adjudication point.
4. **`sm_verified_punch_terminal_rejects_reverify` payload contains a stray `territory_install_date` key** alongside the correct `territory_code` — harmless (PRD §2.9 ignores unknown fields); Step 5b should emit only the correct keys.
5. **`val_occ_beats_state_on_submit_returns_412` uses a template expression `"${ord_v_now} - 1"`** as the OCC payload — Step 5b must compute `version - 1` in code, not pass the string.

Orchestrator spot-check: test_helpers/ on disk has all 10 .py files + HELPERS_MANIFEST.md; py_compile OK; `import test_helpers` OK (203 names); no test_suite/results.json references; test_suite/ does not yet exist. Hand-back claims verified against source.

## Step 5b: Generate Test Suite (split of Step 5; tests against frozen helpers) — 2026-10-01T22:35:00.000Z

result: Step 5b complete for task_3412 — 93 tests across 24 files + conftest, all AST-tag-audited against both design indices, pytest --collect-only 0 errors, 2 corner instances skipped with named PRD-derivability reasons.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3412_contract_furniture_dealer_network_configuration_installation/test_suite/`)

conftest.py (35) — session `api` fixture + three role-header fixtures per the manifest. Corner queue: test_01 entities (183), test_02 state-machines core (175), test_03 state-machines terminal (200), test_04 calculations (161), test_05 validations shape (158), test_06 validations business (166), test_07 validations warranty (164), test_08 endpoints (110), test_09 errors (74), test_10 rbac (152), test_11 cross-cutting (83), test_12 consistency (55). Difficulty queue: test_13 dual-variant calc (144), test_14 combinatorial rounding (112), test_15 combinatorial lead time (89), test_16 non-linear state machine (123), test_17 transitive cascade (154), test_18 priority state-vs-temporal (63), test_19 priority referential-vs-capacity (105), test_20 priority safety-vs-temporal (67), test_21 boundary precision (102), test_22 cross-entity state (155), test_23 resource overlap (139), test_24 compensating invariant (147). Total 3116 lines, 93 test functions.

## Disposition

**Queue A (Difficulty): 21/21 instances emitted, each with ≥2 tests** (19 instances × 2 tests, 2 instances × 3 tests = 44 tests). No difficulty skips — the three priority-pair instances are covered by explicit PRD ordering prose (§3.5 "The gate then evaluates its checks in this order, returning the first failure", §3.6 "The checks evaluate in this order", §3.7 "in this order: the union minimum, the elevator conflict rule, and the zone crew aggregate", §2.9 global order).

**Queue B (Corner): 49 emitted, 13 stubs excluded (cross-references verified), 2 skipped:**
- `Corner/entities/entity_configuration_rejects_unknown_module_type` — fails unique derivability. PRD pins unknown-`module_type` rejection only at LOCK ("an unknown `module_type` ... is rejected with `ERR_INVALID_MODULE`", §3.4) and there is no edit-modules endpoint, so a PRD-only reader can plausibly accept any module_type at create (201) and reject at lock; the instance asserts 400 ERR_VALIDATION at create. The two readers split → skipped, not weakened.
- `Corner/state_machines/sm_deliver_before_production_date_rejected` — per adjudication #3 (empty trigger). PRD §3.6 names `ERR_INVALID_STATE` only for "a phase still `PLANNED` rejects the action"; for a SCHEDULED phase with clock < production_date the PRD states the requirement but no error id → not uniquely derivable → skipped.

## AST tag-audit output (verbatim)

```
tests-with-tags: 93
distinct tags used: 70
tags-matching-instances: 70
untagged tests: []
dual-tagged tests: []
tag-not-final-line: []
tags on STUB instances: []
tags on NON-EXISTENT instances: []
live instances without tests: ['Corner/entities/entity_configuration_rejects_unknown_module_type', 'Corner/state_machines/sm_deliver_before_production_date_rejected']
stub instances (not translated, correct): 13
difficulty instances with <2 tests: []
corner instances with !=1 test: []
```

Separately, the PRD-citation verbatim pass: 127 double-quoted docstring spans extracted via AST, whitespace-normalized, all found literally in PRD.md (13 initial failures from my `...`-compressed quotes were rewritten to full verbatim sentences and re-audited to 0 failures).

## Collection gate (verbatim tail)

```
93 tests collected in 0.31s
```
0 errors. Tests were not executed (no server until Step 6).

## Step 5a adjudications honored

1. BOM test asserts `parts_total_cents == 352411` / `total_units == 3` exactly, cross-checked against the frozen `bom_expand()`; per-line values (PN-PNL-FAB merged qty 8, sort order, first line PN-DOOR) are read through a tolerant key extractor since PRD pins the merge/sort behavior but not per-line JSON key spellings; no assertion on the divergent PN-WRK-SRF unit price.
2. Parts-support test uses the recipe's asserted behavior (2033-10-05 accepted / 2033-10-06 → ERR_PARTS_SUPPORT_EXPIRED); a comment notes the parts window stays open past both dates per `add_calendar_days` arithmetic (2036-10-05).
3. Covered above (skip).
4. No `territory_install_date` anywhere — orders are built via `make_project_order_payload` only.
5. `val_occ_beats_state_on_submit_returns_412` computes `live["version"] - 1` in Python from a fresh GET.

## Helper notes (no edits made, no bugs found)

- Observation, not a bug: PRD §2.5 pins only "increments by 1 on every mutation" and never states the initial value; the frozen helpers' `_assert_common` already requires `version >= 1`, and the design instances pre-compute create-time `version == 1`. I followed the frozen contract and the design literals (version ladders 1→2→3→4) since the helpers are authoritative.
- `punch_escalation` tests cross-check the flag against the frozen `escalated_expected()` helper in addition to the literal expectations.

Orchestrator spot-check: test_suite/ has 26 entries (24 test files + conftest.py + __pycache__); `pytest --collect-only -q` = 93 tests, 0 errors; independent AST walk = 93 tagged tests, 70 distinct tags. Hand-back claims verified against source.

## Step 6: Generate Implementation — 2026-10-01T23:10:00.000Z

result: Task 3412 implementation complete — 21 files (2,466 lines) in `workspace/implementation/`, package graph imports cleanly, and a 105-check end-to-end smoke test passes on a fresh boot against a dynamically allocated port.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3412_contract_furniture_dealer_network_configuration_installation/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `constants.py` | 123 | every constant, exactly once |
| `clock.py` | 60 | logical clock singleton (default `2026-09-01T00:00:00Z`), 3-fractional-digit ISO formatting |
| `state.py` | 36 | empty-at-boot dict stores, UUID minting, `touch()` (updated_at + version) |
| `errors.py` | 70 | `ApiError` + catalog-pinned raisers + error envelope |
| `envelope.py` | 70 | success envelope, pagination parse (limit default 10, clamp 1–100; offset default 0), `created_at`-ascending sort with insertion-seq tiebreak |
| `validate.py` | 143 | body-shape/enum/date/datetime validators |
| `authz.py` | 78 | `X-User-ID`/`X-User-Role` auth, role lists, DealerRep/EndUserRep ownership scope |
| `calc.py` | 245 | bom_expansion (divergent part pricing), lead time, tiered pricing (Decimal, per-line then total ROUND_HALF_UP), plant capacity, business-day escalation, elevator/crew rules |
| `serialize.py` | 183 | full-field serializers per entity |
| `dealers.py` | 144 | dealers + end-users; suspend/reinstate cascades |
| `agreements.py` | 102 | agreements CRUD-lite, lazy EXPIRED, activate |
| `families.py` | 98 | catalog + forward-only lifecycle |
| `configurations.py` | 193 | configs, OCC lock, revise loop, BOM endpoint |
| `orders.py` | 211 | orders create/submit/acknowledge/cancel with pinned gate order |
| `phases.py` | 207 | phase create/list, reserve-slot, start-install, complete + bubble-up, cancel cascade |
| `windows.py` | 129 | install windows + cancel |
| `punches.py` | 180 | punch tickets, resolve (auto-claim), verify loop |
| `claims.py` | 140 | warranty claims + review |
| `clockroute.py` | 23 | `POST /_clock/set_current_utc` |
| `app.py` | 51 | bootstrap, blueprint registration, error handlers (41 URL rules = 40 endpoints + Flask static) |
| `start.sh` / `requirements.txt` | 10/1 | guarded `pip install` (import check first), `exec python3 app.py`, `PORT` env, `0.0.0.0` |

Dependency graph: `app.py` → 10 route blueprints → {`authz`, `validate`, `envelope`, `serialize`, `calc`, `errors`} → {`state`, `clock`, `constants`}. `orders.py` → `phases.py` (cancel cascade); `phases.py` never imports `orders.py` (order lookup via `state`), so no cycles. All route modules share `_new_entity` from `dealers.py`. Verified: every file `py_compile`s, `import app` succeeds, and a grep diff of `constants.*` references vs definitions shows zero used-but-undefined names.

## Constants table (name → value → source)

CLOCK_DEFAULT_ISO `2026-09-01T00:00:00Z` (PRD §2.4) · TIER2_MIN/TIER3_MIN 25000000/75000000 (§3.2) · PARTS_WARRANTY_DAYS 1826, LABOR_WARRANTY_DAYS 366, MIN_PARTS_SUPPORT_DAYS 2557 (§3.8/§3.3) · queue tiers 3/7/12 at ≤49/≤199/≥200 (§2.8) · FABRIC_LEAD_DELTA A0/B7/C14/COM21, FABRIC_UPCHARGE A0/B5/C12/COM18 (§2.7) · PLANT_DAILY_CAPACITY GR 120/DAL 80, TRANSIT_DAYS GR 4/DAL 6, PRODUCTION_NOTICE 2 (§2.8) · FREIGHT_TURN_BUFFER 15 min, ZONE_MAX_CREW 10, UNION_MIN_CREW 4 (§2.8) · ESCALATION_BUSINESS_DAYS 5 (§3.8) · CAPABILITY_REQUIRED SYSTEMS 3/SEATING 1/STORAGE 2 (§2.7) · pagination 10/1/100/0 (§2.3) · MODULE_BOM_RULES reproducing the pinned per-unit totals 85837/104737/180737/66300/125000 (§2.7).

## Smoke-test transcript (port allocation + key results)

Port allocated dynamically: `PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")`, then `bash start.sh &`, PID saved, readiness-polled via curl, killed exactly that PID afterward (orphans from my earlier mis-grouped runs identified by `/proc/<pid>/cwd` and killed by PID; two `app.py` processes belonging to the concurrent task_3360 pipeline were left untouched). Script: `/tmp/smoke_3412.py`.

Full happy path passed: dealer → end user → agreement → activate → 3 families → config → BOM (`parts_total_cents=237974`, lines merged/sorted) → lock (OCC, `max_lead_time_days=33`) → order → submit (`provisional_total_cents=214177`, revision pinned) → acknowledge (final pricing, ledger) → phase → reserve GR slot → clock advance → start-install → punch → escalate check → resolve/verify loop → complete (bubble-up to CLOSED) → LABOR claim → APPROVE. Negatives all passed: 401/403 auth, stale-version 412 on both OCC endpoints, suspend cascade + `ERR_DEALER_SUSPENDED`, reinstate cascade, tier boundary exactly at 25,000,000 (provisional tier 1 → final tier 2, total 21,250,000), queue tier at 200 units (12 days), capacity 130>120 and 120+1, production-notice and transit 422s, union crew 3 → 422, elevator 14-min gap → 409 / 15-min gap → 201, crew 6+5 → 422, floor-sequence and CRITICAL-punch gates (incl. RESOLVED-still-blocks), duplicate category/family_code/phase_sequence 400s, lazy agreement EXPIRED, lifecycle date-window 400s + skip 409, lock-after-last_order_date 422, DISCONTINUED lock 422, ACKNOWLEDGED-cancel ledger compensation with phase/window/punch cascade and COMPLETE phases untouched, warranty-expired 422 at 366+1 days, list scoping and pagination envelope. Fresh-boot check: `GET /project-orders` returns `total_count: 0`; clock reads `2026-09-01T00:00:00Z` before any set.

## PRD ambiguities I resolved (Step 8/9 should review these)

1. **Divergent part pricing in BOM merge** (biggest one): `PN-WRK-SRF` is priced 15800/17400/21500 by module type, but §3.4 says merged-line extended = total qty × unit price. I made the merged line's `extended_cents` the sum of per-module-context contributions (the only reading consistent with the pinned per-unit totals and order_pricing step 1); `unit_list_price_cents` is the price when uniform, else `null`.
2. **`created_at`/`updated_at`/meta timestamps use the logical clock** (not wall clock) — required for reproducible escalation and for `created_date` in business-age math; §2.5 doesn't say which clock.
3. **Lazy EXPIRED applies no version bump** (scaffold transition has empty side_effects; §2.5's "every mutation" arguably conflicts).
4. **Activate after `effective_end`** → `ERR_INVALID_STATE` (no error id pinned anywhere for this).
5. **start-install before `production_date`** → `ERR_INVALID_STATE` (only the PLANNED case is pinned in §3.6).
6. **PATCH dealer with `status` equal to current state** → `ERR_INVALID_STATE` (only the two transitions are listed; same-state is not a no-op success).
7. **Body-FK resolution order for POST /warranty-claims** follows the §2.9 listing literally: `installation_phase_id` 404 before `project_order_id` 404.
8. **Order create referencing another dealer's configuration** → `ERR_FORBIDDEN_OWNERSHIP` (ownership read of §2.1 applied to FK references).
9. **Auto-created warranty claim on punch resolve** copies the ticket's `description` (field unpinned by scaffold).
10. **BOM line field names** (`part_number`, `qty`, `unit_list_price_cents`, `extended_cents`) — PRD names concepts, not keys.
11. **Pagination out-of-range integers clamp** to [1,100]/[0,∞); non-integer → `ERR_VALIDATION` (behavior unpinned).
12. **`part_number` sent with `requires_part=false` / `claim_type=LABOR`** is ignored, stored null ("required exactly when" read as not forbidden).
13. **`current_utc` echoes the exact string supplied** to the clock-set; internally normalized to UTC.
14. **Missing family row for a module category at lock** → `ERR_INVALID_MODULE` (catalog lists no specific error; 404 felt wrong for a non-id reference).

## Isolation confirmation

I never opened, read, grepped, or executed anything under these paths: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, `test_helpers/` (all under `/home/ubuntu/github/CodingPRD/tasks/task_3412_contract_furniture_dealer_network_configuration_installation/`). Implementation was built from `workspace/INSTRUCTION.md`, `SCAFFOLD.yaml`, and `workspace/PRD.md` only; the test suite was never run by me.

Orchestrator spot-check: implementation/ has 20 .py files + start.sh + requirements.txt; all compile; `import app` OK; app.py reads `$PORT` (default 10000) and binds 0.0.0.0; start.sh is `set -euo pipefail` + guarded pip + `exec python3 app.py` (foreground); the "5000/8000" grep hits were money constants (25000000/75000000/25000), not ports. Hand-back claims verified against source.

## Step 7: Test-and-Fix Iteration Loop — 2026-10-01T23:36:00.000Z

All 8 rounds of the first sweep came back clean — 93/93 in every round, no flakiness. Sanity checks performed: suite collection count re-verified at 93 (matches the expected 44 difficulty + 49 corner total with the two deliberate skips absent), all 8 `results.*.json` files parse as valid JSON, each shows `passed == total == 93` and `failed == 0`, and all 8 files remain on disk in `workspace/implementation/`.

result: Clean 8-round parallel sweep on iteration 1 for task_3412 — all 8 rounds passed 93/93 with zero failures and zero flaky tests; no deletions or fixes required.

Summary:
- Iterations run: 1
- Tests deleted: none. All 93 tests are PRD-derivable and pass as generated; the two deliberately skipped corner instances (`Corner/entities/entity_configuration_rejects_unknown_module_type`, `Corner/state_machines/sm_deliver_before_production_date_rejected`) remain absent as intended.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.
- Final sweep evidence (all files at `/home/ubuntu/github/CodingPRD/tasks/task_3412_contract_furniture_dealer_network_configuration_installation/workspace/implementation/`):
  - results.1.json: 93/93
  - results.2.json: 93/93
  - results.3.json: 93/93
  - results.4.json: 93/93
  - results.5.json: 93/93
  - results.6.json: 93/93
  - results.7.json: 93/93
  - results.8.json: 93/93
  - All 8 files confirmed present on disk after the passing sweep.

Orchestrator independent verification (per hard-won practice, the sweep was re-run by the orchestrator, not just trusted from the hand-back): full 8-round parallel sweep re-executed at 2026-10-01T23:36–23:39Z; every round reported `Results: 93/93 passed, 0 failed, 0 errors, 0 skipped` (~158s/round); regenerated `results.{1..8}.json` on disk all read 93/93 failed:0. Step 7's claim confirmed against source.

## Step 8: Finalize PRD — SKIPPED — 2026-10-01T23:40:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline. PRD.md already determines every behavior the implementation exhibits; `PRD_FINALIZED.md` is not produced. Step 9 will start from PRD.md directly.

## Step 9: Complete PRD — 2026-10-01T23:50:00.000Z

Write scope verified: PRD.md untouched (mtime 21:42, pre-session), no implementation or test files modified. The deliverable is complete.

## Summary

**Source vs output:** `workspace/PRD.md` 304 lines / 53,224 chars → `workspace/PRD_COMPLETED.md` 304 lines / 56,132 chars (+2,908 chars; 16 paragraph-line revisions, no added/removed sections).

**Counts:** 20 ambiguity-pins across 16 edits · 0 mismatch-revisions · 0 impl-gaps · 0 dead/missing checks.

**Changes (one per bullet):**
1. §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_VALIDATION`; out-of-range integers clamp to [1,100]/[0,∞) — envelope.py:38-61
2. §2.3 — insert — ambiguity — `created_at` sort ties break by creation/insertion order — envelope.py:67, state.py:20
3. §2.4 — insert — ambiguity — all emitted timestamps (`created_at`, `updated_at`, §3 stamps, `meta.api_request_timestamp`) read the logical clock — clock.py:54-56, state.py:32-36, envelope.py:12, errors.py:57
4. §2.4 — insert — ambiguity — `current_utc` echoes the exact supplied `to_iso8601` string; internally normalized to UTC — clock.py:28-32, clockroute.py:23
5. §2.9 — revise — ambiguity — body FKs resolve in the listed order (`installation_phase_id` before `project_order_id`) — claims.py:43-48
6. §2.9 — insert — ambiguity — JSON `null` on an optional field counts as absent; on a required field counts as missing — validate.py:36-43, dealers.py:55-57
7. §3.1 — insert — ambiguity — `status` payload equal to the dealer's current state → `ERR_INVALID_STATE`, not a no-op — dealers.py:99-109
8. §3.2 — revise — ambiguity — activate after `effective_end` (or when not `DRAFT`) → `ERR_INVALID_STATE` — agreements.py:94-98
9. §3.2 — insert — ambiguity — lazy `ACTIVE → EXPIRED` changes only `status`; no `version` bump, no `updated_at` touch — calc.py:135-141
10. §3.4 — revise — ambiguity — config create validates shape only (non-empty `module_type` string, integer `qty` ≥ 1; `fabric_grade` optional, stored null); module-type/fabric rules enforced at lock — configurations.py:25-49,52-72
11. §3.4 — insert — ambiguity — module category with no family row at lock → `ERR_INVALID_MODULE` — configurations.py:60-62
12. §3.4 — insert — ambiguity — merged BOM line fields are exactly `part_number`, `qty`, `unit_list_price_cents`, `extended_cents` — calc.py:39-46
13. §3.4 — revise — ambiguity — divergent part pricing (`PN-WRK-SRF` 15800/17400/21500): merged `extended_cents` = sum of per-module-context contributions; `unit_list_price_cents` = shared price when uniform else `null` — calc.py:11-47, constants.py:53-85
14. §3.4 — revise — ambiguity — the API exposes no module-edit operation; a revised spec re-locks its unchanged module list (also resolves the acknowledgment-repricing reading) — configurations.py:167-179, orders.py:176-178
15. §3.5 — insert — ambiguity — order create naming another dealer's `configuration_id` → `ERR_FORBIDDEN_OWNERSHIP` — orders.py:49-51
16. §3.6 — revise — ambiguity — start-install with clock date before `production_date` → `ERR_INVALID_STATE` — phases.py:156-159
17. §3.7 — insert — ambiguity — window `start_at`/`end_at` stored and echoed verbatim; arithmetic parses/normalizes to UTC — windows.py:77-78
18. §3.8 — insert — ambiguity — punch `part_number` sent with `requires_part=false` ignored, stored null — punches.py:56-60
19. §3.8 — insert — ambiguity — auto-created claim on punch resolve copies the ticket's `description` — punches.py:121-132
20. §3.8 — insert — ambiguity — claim `part_number` sent with `claim_type=LABOR` ignored, stored null — claims.py:58-62

**Focus-list disposition:** all 14 pinned — #1 at §3.4 (bullet 13), #2 at §2.4 (bullet 3), #3 at §3.2 (bullet 9), #4 at §3.2 (bullet 8), #5 at §3.6 (bullet 16), #6 at §3.1 (bullet 7), #7 at §2.9 (bullet 5), #8 at §3.5 (bullet 15), #9 at §3.8 (bullet 19), #10 at §3.4 (bullet 12), #11 at §2.3 (bullet 1), #12 at §3.8 (bullets 18+20), #13 at §2.4 (bullet 4), #14 at §3.4 (bullet 11).

**Judgment call flagged:** item #3 sits against §2.5's "increments on every mutation … including mutations driven by system cascades." I read "system cascades" as the two cascades §3 names (dealer-suspension, order-cancel); a lazy read-time transition is not a cascade, so this is a silence, pinned per impl. If §2.5 is instead read as covering lazy expiry, this is an impl bug at calc.py:135-141 (no `state.touch` on the transition) — no impl change made per write scope.

**Exhaustive-walk evidence:** all 40 §4 endpoints walked (impl blueprint count matches 40: dealers 3, agreements 4, families 2, configurations 6, orders 6 + 2 nested phase routes, phase actions 3, windows 4, punches 5, claims 4, clock 1); all 7 calculations walked (BOM expansion, config lead time, order pricing provisional/final, agreement volume/tier, plant capacity, punch escalation, window elevator+crew); all 38 §5 error ids grep-audited — each has a live raise site reachable from a route handler (no defined-but-never-called, no called-but-never-defined). Boundary audit all matched impl↔PRD: queue 49/199, tiers 25M/75M, production notice ≥2d inclusive, transit ≤ install−transit inclusive, capacity ≥ planned, union ≥4, zone ≤10, 15-min buffer strict inequalities, warranty 1826/366 inclusive last day, 2557-day parts horizon, escalation ≥5 business days, lead time ≥ clock+`max_lead_time_days`. Impl-only error ids `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` (app.py:30-46) are Flask fallbacks for undefined routes, outside the §5 endpoint surface — noted, no PRD edit.

result: PRD_COMPLETED.md written for task_3412 — 20 ambiguity pins over PRD.md (all 14 focus items verified in code), zero impl edits, zero dead checks, 38/38 error ids live.

Orchestrator spot-check: `diff -q` confirms PRD_COMPLETED.md differs from PRD.md (not a silent no-op); on-disk sizes match the report exactly (53,224 → 56,132 chars, 304 lines both); PRD.md mtime untouched (21:42); newest impl source (calc.py 23:26) predates both Step 7's sweep and the orchestrator's verification re-run, so the green sweep evidence remains valid; newest test_helpers source 22:01 and test_suite source 22:54 both predate the sweeps. Flagged lazy-EXPIRED-vs-§2.5 judgment call is recorded above; the pin matches impl behavior that all 93 tests pass against, so it stands as the final contract wording. Hand-back claims verified against source.
