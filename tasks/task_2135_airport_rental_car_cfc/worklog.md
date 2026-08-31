# Worklog — task_2135_airport_rental_car_cfc

## Step 1: Create task directory — 2026-08-22T10:31:07.874Z

Created `tasks/task_2135_airport_rental_car_cfc/` and `tasks/task_2135_airport_rental_car_cfc/workspace/`.

## Step 3: Copy shared files — 2026-08-22T10:31:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2135_airport_rental_car_cfc/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-22T11:43:00.000Z

All three scaffold artifacts are generated and lint-clean.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2283 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2332 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2880 |

## SCAFFOLD.yaml contents (§1.0–§1.7)

- **Profile**: `ledger_reconciliation` + `quota_allocation`; layers = dual-variant calc, cascading side effects, OCC, rate/threshold triggers; topology **flat**; shape **branching**; relationships include **self_referential** (`CapitalProject.predecessor_project_id`); role model **segregation_of_duties**; consistency immediate. `api_prefix: /rac`.
- **15 entities**: Facility, Concessionaire, ConcessionAgreement, CounterSpace, CounterAssignment, FleetParkingZone, FleetAllocation, TransactionDayReport, CfcRemittance, DebtServiceObligation, ShuttleCostPeriod, ShuttleCostAllocation (immutable, `common_fields: false`), CapitalProject, CapitalDisbursement, TrueUpSettlement.
- **11 state machines** (ConcessionAgreement carries two independent status axes), **3 OCC concurrency rules** (agreement / zone / project version), **7 calculations**, **34 ordered validations**, **69 endpoints** (incl. `POST /rac/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`), **46 error codes**, **4 roles** (FacilityAdmin/AuditOfficer/FinanceOfficer opaque, ConcessionaireOperator `entity_backed:Concessionaire`).

## §1.8 — 26 instances (>=2 per rule, min 18 met)

dual_variant_calc 3 · combinatorial_formula 3 (modes b/c/a) · non_linear_state_machine 3 (cycle / two axes / fork) · transitive_cascade 2 (depth 5 and depth 3, different triggers) · priority_pair_validation_conflict 3 (state<->fiscal, temporal<->constraint, safety<->fiscal) · boundary_precision_check 3 (exact 1.2500 coverage, zero-day remittance, empty allocation set) · cross_entity_state_dependency 4 · resource_temporal_overlap 2 (half-open exclusive counter vs closed-interval aggregate zone) · compensating_invariant 3 (cash / stalls / rent-ledger identity).

## §1.9 — 70 instances (59 executable + 11 `excluded_because` stubs)

entities 13 · state_machines 15 · calculations 9 · validations 17 · endpoints 2 · errors 3 · rbac 4 · cross_cutting_complexity_layers 6 · consistency_model 1.

## Verification

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    69
  §1.1 entities declared:     15
  §1.8 instances scanned:     26
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  783
```

Additional checks run: all three files parse as YAML; zero duplicate instance names across both design files; every `grounds:` reference resolves against §1.1–§1.7 (0 issues); every `excluded_because.difficulty_instance` names a real §1.8 instance; no forbidden concurrency vocabulary; neither design key leaks into `SCAFFOLD.yaml`. All formula-derived assertions were computed by hand and written as literals (e.g. rent divergence 2,500,000 vs 3,000,000; largest-remainder split 333,334/333,333/333,333; true-up base 5,000,000 -> 300 bps -> net 4,850,000; waterfall 5,000,000/250,000/750,000).

No sibling task directories were read.

## Step 4: Generate PRD — 2026-08-22T11:54:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 440 lines (87,988 bytes), ends cleanly at the §5 error table (no truncation; final row `| ERR_SETTLEMENT_UNDERPAID | 422 |`).

**Structure:** §1 Introduction (3 paras) · §2 with 11 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination + list-filter catalogue, 2.4 Identity/versioning, 2.5 Path & FK resolution, 2.6 Request admission ladder, 2.7 Money/bps/rounding, 2.8 CFC trust ledger, 2.9 OCC, 2.10 Segregation of duties, 2.11 Logical clock & interval conventions) · §3 with 10 domain narratives (inventory, agreement two-axis lifecycle, counter occupancy, fleet/overflow allocation, reporting+audit+percentage rent, CFC collection+waterfall, debt service+coverage, capital projects+draws, shuttle allocation, true-up settlement) · §4 4-column endpoint table · §5 2-column error table.

**Coverage (machine-verified against SCAFFOLD.yaml):**
- Entities: 15/15 named; all 131 `fields[].name` present in backticks
- State machines: 11/11 (both `ConcessionAgreement` axes treated separately); every `from`/`to`/initial/terminal state string present
- Calculations: 7/7 (percentage rent dual-variant, CFC expected amount dual-basis, trust waterfall, coverage test + auto-fund selector, shuttle largest-remainder, true-up 3-step pinned order, fleet overflow waterfall) — all in prose, no pseudocode, no fuzzy words
- Validations: 34/34 — full priority ladder enumerated in §2.6 with each rule's condition and error restated in its owning narrative
- Endpoints: 69/69 in the §4 table; all 65 request-body identifiers, 17 query params, 15 path params covered
- Errors: 46/46 in §5, and every id also referenced in §2/§3 prose
- Roles: 4/4 with `identity:` translated (3 opaque, `ConcessionaireOperator` entity-backed on `Concessionaire`)

**Hard contracts:**
- Contract 1 Field-Name Coverage — entities 131/131, request_body 65/65, query_params 17/17, path_params 15/15, 0 missing. **PASS**
- Contract 2 Rule Coverage — 34 validations with priority expressed; 3 OCC rules each naming write operation + `expected_agreement_version`/`expected_zone_version`/`expected_project_version` + `ERR_STALE_VERSION` (412); all transitions with preconditions/side-effects; 7 calculations; sibling branches (authorize vs reject fork, five remittance landings, EXPIRED vs TERMINATED, explicit vs auto funding, both rent variants, both shuttle bases, both release branches) rendered at equal density. **PASS**
- Contract 3 §3 Path Purity — 790 backtick tokens scanned; 0 slash-leading, 0 bare HTTP methods, 0 method+path. **PASS**
- §2.2 matches the canonical block byte-for-byte.

**Expressed implicitly rather than verbatim:** endpoint `trigger:` strings (HTTP paths) are rendered in §3 as state-pair/role-verb framing per Contract 3, with paths appearing only in §4; `input_set` exclusion lists are woven into narrative rather than listed; the two `Facility` derived identities (`overflow_stalls_available`, `stalls_available`) are stated as invariants rather than as formulas. `Facility.code` uniqueness is stated as a constraint but the scaffold defines no dedicated error code for it, so none was invented.

Orchestrator verification: `grep -o 'ERR_[A-Z_]*' | sort -u | wc -l` = 46; endpoint table rows = 69; no mid-sentence truncation.

## Step 6: Generate implementation — 2026-08-22T12:10:00.000Z

Implementation complete at `workspace/implementation/`.

## Module layout (2,678 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | Guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `app.py` | 69 | Blueprint registration, error handlers, process-wide WSGI lock, `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 112 | All 46 error IDs -> HTTP status + messages, path-param -> not-found map |
| `store.py` | 109 | 15 in-memory dicts, UUID/`created_at`/`version` minting, logical clock (`2026-08-01T00:00:00Z`) |
| `response.py` | 44 | PRD §2.2 envelope (`meta`/`response_type`/`data`, `req_` + 20 alnum, 3-digit-ms ISO) |
| `validation.py` | 206 | Auth (`X-User-ID`/`X-User-Role`), RBAC, typed field parsers, pagination (10/1/100/0) |
| `calc.py` | 182 | 7 calculations: rent accrual (both variants), waterfall, coverage test, largest-remainder (exact `Fraction`), true-up tiers, overflow allocation, `expected_amount` |
| `serializers.py` | 178 | Per-entity field sets; `ShuttleCostAllocation` carries only `id`/`created_at` |
| `domain.py` | 138 | Idempotent per-request `bump()`, ownership check, project-release + auto-funding cascades |
| `routes_facility.py` | 396 | Facilities, brands, agreements, counter spaces, zones, `_clock` |
| `routes_space.py` | 270 | Counter assignments (half-open), fleet allocations (closed + overflow) |
| `routes_report.py` | 341 | Reports + 3-hop accept cascade, remittances + 5-hop receive cascade |
| `routes_finance.py` | 624 | Obligations, shuttle pools/lines, capital projects, draws, true-ups |

## Endpoint coverage: 69 / 69

Verified programmatically: `len([r for r in app.url_map.iter_rules() if str(r).startswith('/rac')]) == 69`.

## Smoke-test results — all 50 assertions pass

Launched via `PORT=18137 bash start.sh`, curled every domain area:

- **facility** — 201, envelope exactly matches §2.2; `bond_coverage_status` `DEFICIENT` at birth when `ds_reserve_requirement_cents > 0`, `SATISFIED` when 0
- **agreement** — draft/execute, dual status axes, rent ledger (`rent_billed_to_date_cents` 220000, `rent_tier` `PERCENTAGE`, `compliance_status` `COVENANT_BREACH` on positive variance)
- **counter** — assignment create (bumps agreement + space), `ERR_STALE_VERSION` 412 on OCC, activate
- **fleet** — 15 requested vs capacity 10 -> `zone_stalls_granted` 10 / `overflow_stalls_granted` 5, `inclusive_days` 10, surcharge 2500
- **report** — submit/begin-audit/accept, variance 200000 -> assessment 20000
- **cfc** — `PROVISIONAL` expected 500x1000, `due_date` 2026-03-20 (last day + 20 grace); receive -> `RECONCILED`, DEFICIENT full-sweep waterfall split 100000/50000/350000/0, covenant flips to `SATISFIED`
- **debt** — fund at exactly 1.25x -> 200, `coverage_ratio_at_funding` `1.25`; auto-funding fires from a receipt with `auto_funded: true`
- **capital** — approve holds in `APPROVED` with `funding_hold`, later released to `FUNDED` by the obligation reaching FUNDED; draw + `ERR_SEGREGATION_OF_DUTIES` on self-authorize
- **shuttle** — 3 agreements, basis 10/20/3 of 33, cost 100 -> floors 30/60/9, remainder pool 1 to rank 1 -> 30/61/9 summing to exactly 100; `share_bps` 3030/6061/909; lines have no `version`/`updated_at`
- **trueup** — SoD 403 for the auditing officer, issue base 800000 / credit_bps 0, underpay 422, settle -> compliance back to `COMPLIANT`
- **clock** — `current_utc` echoed, `expired_agreement_count` 1
- **cross-cutting** — 401 unauth, 403 RBAC, 400 `limit=200`, list `meta` (limit/offset/total_count/has_more), 404 with the resource-specific code

## Notes on judgment calls

- **Version bumping** follows §2.4's universal rule (any mutated row gets `version += 1`, at most once per request), a superset of every explicit "advances version by 1" statement in §3.
- **Un-coded preconditions** mapped to the ladder: `execute` with `term_start >= term_end` and `submit` against a non-ACTIVE/SUSPENDED agreement -> `ERR_INVALID_STATE` (409, ladder step 7); `activate` against a space whose `active_assignment_id` is non-null -> `ERR_COUNTER_SPACE_OCCUPIED` (409, after the step-11 agreement-active check).
- **No seeding**: verified by rebooting on a fresh port — all collections return `total_count: 0`.

## Step 5: Generate unit tests — 2026-08-22T12:31:00.000Z

Complete. All checks pass.

## What was generated

**`test_helpers/`** (9 files, ~1,930 lines) — `types.py` (17 enums + 15 entity TypedDicts, with `ShuttleCostAllocation` correctly carrying only `id`/`created_at`), `api_client.py` (73 endpoint methods), `api_errors.py` (46 error ids + HTTP map registered with the framework), `assertions.py` (per-entity assertions plus trust-conservation, covenant-posture, stall-identity and waterfall-split invariant checkers), `factories.py`, `constants.py`, `test_users.py` (opaque officer constants + `make_operator_headers(concessionaire_id)` for the one `entity_backed` role), `fixtures.py` (5 tiers, incl. `setup_two_receipt_trust`, `setup_single_receipt_trust`, `setup_funded_project_with_requested_draw`, `setup_issued_settlement`; every ownership-gated call threads the brand's real `id`, and every version-carrying create re-reads the parent's live `version`).

**`test_suite/`** (conftest + 12 domain-named files, ~4,140 lines).

## Verification results

| Check | Result |
|---|---|
| Total tests | **111** (collected by pytest) |
| Queue A tags (`Design: Difficulty/...`) | **52** — 26 instances x exactly 2 tests each |
| Queue B tags (`Design: Corner/...`) | **59** — 59 non-stub instances x exactly 1 test each |
| Every tag resolves to a real `name:` in its source yaml | yes |
| Tag counts | every Difficulty tag used exactly twice (skill requires >=2); every Corner tag exactly once; no tag points at an `excluded_because:` stub |
| Duplicate test function names | none |
| PRD citations verbatim | every quoted span >=20 chars in every docstring survives a whitespace-normalised substring match against `PRD.md` |
| `skip`/`skipif`/`xfail` | none |
| "scaffold" / table / §1.x leakage in emitted code | none |
| 11 stub `difficulty_instance` cross-references | all resolve to real difficulty instances |

## Instances skipped

**None.** All 26 difficulty instances and all 59 executable corner instances passed the PRD-first two-condition filter. Notably, the three priority-conflict instances survive because the PRD states the orderings explicitly rather than only in a scaffold priority table — §3.8 *"Those five business checks are evaluated in exactly that order"*, §3.3 *"Four business rules guard the reservation, and their relative order matters"*, and §3.10 *"that segregation-of-duties check is evaluated before the reports-finalised check"*. The 11 `excluded_because:` stubs were not translated, as specified.

## Two arithmetic notes worth flagging to the implementer side

- `SCAFFOLD_CORNER_DESIGN.yaml` -> `true_up_dispute_then_reissue_closes_the_negotiation_loop` has a `distinguishing_aspect` that says *"net_true_up_cents is still 0"*, which contradicts its own `assert:` block (`base_true_up_cents == 11000000`, `net_true_up_cents == 10670000`). The generator followed the assert block, which is the one consistent with the PRD formula.
- Every literal expected value in both indices was independently recomputed from PRD prose before being copied; all 85 instances reconciled.

## Step 7: Run tests and iterate — 2026-08-22T12:40:00.000Z

Clean exit after one iteration — no fixes or deletions were needed.

## Summary

**Iterations run: 1**

The 8-round parallel stability sweep was launched concurrently and joined with `wait`; all 8 rounds ran to completion under `--isolation per-test-server` (server rebooted via `start.sh` before each of the 111 tests).

| Round | Result | Duration |
|---|---|---|
| 1–8 | **111 / 111 passed**, 0 failed, 0 errors, 0 skipped | 144–145 s each |

Union of failing tests across all 8 rounds: **empty**. No flakiness surfaced — no test passed in one round and failed in another, so there is no timing-sensitive bug hiding behind a lucky round (the concurrency/OCC tests `test_stale_agreement_version_blocks_counter_assignment`, `test_stale_zone_version_blocks_fleet_allocation`, `test_stale_project_version_blocks_a_second_draw` were stable across all 8).

**Tests deleted: none.** The diagnostic protocol never engaged — STEP 0 produced an empty failure set, so no PRD-coverage or unique-derivability adjudication was required.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/`: none.**

### Integrity verification performed before exiting

Since a first-sweep clean run can mask a rigged artifact, the cardinal-rule invariants were checked directly rather than trusting the green result:

- **No suppression markers** — `grep` for `skip` / `skipif` / `xfail` across `test_suite/` and `test_helpers/` returns nothing.
- **In-memory storage only** — `implementation/store.py` holds all 15 collections as plain dicts on a `Store` object whose `reset()` re-initialises every collection and resets the logical clock to `2026-08-01T00:00:00Z`. No SQLite, no file `open()`, no `json.dump`, no `/tmp` cache, no external store anywhere in `implementation/*.py`.
- **No seeding** — `Store.__init__` calls `reset()` and nothing else; no module-level or startup population, so each per-test `start.sh` reboot wipes all state.
- **Test count intact** — 111 `def test_` functions across the 12 domain files, matching the reported total exactly (no silent collection loss).

### Orchestrator-side verification

- Re-read all 8 `results.N.json` independently: every one reports `passed=111, failed=0, total=111, errors=0, skipped=0`.
- **Design-index leak check**: grepped the Step 6 implementation-generator transcript for `SCAFFOLD_DIFFICULTY_DESIGN` / `SCAFFOLD_CORNER_DESIGN` — **0 hits**. The impl generator never touched either test-targeting index, so the first-sweep green reflects a genuinely complete PRD rather than an index leak.

## Step 8: Finalize PRD — SKIPPED — 2026-08-22T12:41:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 would have targeted. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-22T12:50:00.000Z

`workspace/PRD_COMPLETED.md` written.

**Source vs output**: `PRD.md` 440 lines / 87,988 chars -> `PRD_COMPLETED.md` 440 lines / 93,351 chars (**+5,363 chars**, 30 lines modified, 0 lines added/removed, 0 new sections).

**Counts**: 31 edits total — **28 ambiguity-pins**, **3 mismatch-revisions**.

Structural cross-checks first confirmed the §4 table's 69 (method, path, role-set) triples match the implemented Flask routes exactly, and the §5 catalogue's 46 (error_id, HTTP status) pairs match `errors.py::ERROR_HTTP` exactly with every code actually raised — so no table edits were needed.

### Changes

- §2.1 — insert — ambiguity — `X-User-ID` is never resolved as a row; an unregistered brand id authenticates and merely fails ownership — `validation.py:23`, `domain.py:24`
- §2.3 — insert — ambiguity — undeclared query params ignored; id-filters matching nothing yield an empty page, not 404; non-integer `period_year`/`period_month` -> `ERR_INVALID_REQUEST` — `validation.py:180`, `domain.py:33`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order, globally (lists, cascades, selectors, rankings) — `store.py:88`
- §2.4 — insert — ambiguity — a row's `version` rises by at most 1 per request no matter how many hops touch it — `store.py:79`
- §2.5 — insert — ambiguity — unmatched URL -> `ERR_INVALID_REQUEST`/404, unsupported method -> `ERR_INVALID_REQUEST`/405 — `app.py:38`
- §2.6 (step 3) — insert — ambiguity — required strings must be non-empty; undeclared body fields ignored; `null` reads as omitted; bodiless action endpoints ignore any body — `validation.py:53,84`
- §2.11 — insert — ambiguity — `to_iso8601` contract, verbatim echo, backward moves allowed, sweeps compare only the first 10 chars; sweep order remittances->obligations->agreements — `routes_facility.py:317,346`
- §3.1 — **revise** — **mismatch** — facility `code` uniqueness is convention only; no duplicate check exists — `routes_facility.py:31`
- §3.1 — insert — ambiguity — the two optional facility fields are unbounded integers; `null` = omitted — `routes_facility.py:38`
- §3.1 — insert — ambiguity — `contact_email` required non-empty, no syntax check — `routes_facility.py:84`
- §3.2 — insert — ambiguity — `facility_id`/`concessionaire_id` not cross-checked — `routes_facility.py:134`
- §3.2 — insert — ambiguity — execute's date condition raises `ERR_INVALID_STATE` (409) — `routes_facility.py:190`
- §3.2 — insert — ambiguity — clock termination leaves `counter_units_assigned` and `active_assignment_id` untouched — `routes_facility.py:377`
- §3.2 — **revise** — **mismatch** — `DELINQUENT -> COMPLIANT` tests surviving delinquencies only; a partial payment to `RECEIVED` clears it — `routes_report.py:334`
- §3.3 — **revise** — **mismatch** — activation order is state -> `ERR_AGREEMENT_NOT_ACTIVE` -> `ERR_COUNTER_SPACE_OCCUPIED` (PRD had the occupancy check listed first and gave it no code) — `routes_space.py:100`
- §3.3 — insert — ambiguity — counter release also advances the agreement's `version` — `routes_space.py:137`
- §3.4 — insert — ambiguity — the overflow lot drawn is the *zone's* facility's — `routes_space.py:171`
- §3.4 — insert — ambiguity — fleet release also advances the agreement's `version` — `routes_space.py:269`
- §3.5 — insert — ambiguity — `rejection_reason` is a mandatory non-empty string — `routes_report.py:120`
- §3.5 — insert — ambiguity — submit's agreement-status failure is `ERR_INVALID_STATE`, not `ERR_AGREEMENT_NOT_ACTIVE` — `routes_report.py:96`
- §3.5 — insert — ambiguity — hop three fires only on an actual `MAG_FLOOR -> PERCENTAGE` crossing — `routes_report.py:191`
- §3.6 — insert — ambiguity — the delinquency sweep bumps the agreement only when it actually stood `COMPLIANT` — `routes_facility.py:355`
- §3.6 — insert — ambiguity — `amount_received_cents` is a mandatory integer >= 0 — `routes_report.py:293`
- §3.6 — insert — ambiguity — receipt-side restatement of the `DELINQUENT -> COMPLIANT` rule plus the agreement version bump — `routes_report.py:334`
- §3.7 — insert — ambiguity — `coverage_ratio_at_funding` uses the pre-transfer available cents — `domain.py:104`
- §3.7 — insert — ambiguity — `coverage_requirement_bps` is an integer >= 0, no upper bound — `routes_finance.py:39`
- §3.7 — insert — ambiguity — paying an obligation does **not** lower `funded_obligation_count` — `routes_finance.py:96`
- §3.8 — insert — ambiguity — a predecessor need only resolve, at any facility in any status, at proposal time — `routes_finance.py:247`
- §3.8 — insert — ambiguity — no project-status condition guards the draw *request*; `FUNDED` bites at authorisation — `routes_finance.py:348`
- §3.9 — insert — ambiguity — no duplicate-period guard on a shuttle cost pool — `routes_finance.py:120`
- §3.10 — insert — ambiguity — `amount_paid_cents` is a mandatory integer >= 0 — `routes_finance.py:609`

### Integrity checks
- 440 lines (unchanged); headings byte-identical to `PRD.md`
- §4 endpoint table: **69 rows** ✓
- §5 error table: **46 rows** ✓
- Zero table rows touched — all 30 changed lines fall between L23 and L311 (§2/§3 prose); §4 starts at L313, §5 at L389
- Clean tail: file ends on `| ERR_SETTLEMENT_UNDERPAID | 422 |`

### Orchestrator-side verification
- `wc`: 440/87,988 -> 440/93,351 confirmed; `diff` reports exactly 60 changed lines (30 `<` + 30 `>`), matching the claimed 30 modified lines with no insertions or deletions.
- Independent recount on `PRD_COMPLETED.md`: 69 endpoint rows, 46 distinct `ERR_*` ids, clean tail.

---

# Pipeline complete — all 9 steps done (Step 8 skipped by its skip condition).
