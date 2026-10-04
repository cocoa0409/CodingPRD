# Worklog — task_3482_multistate_investigation_coordination_settlement_fund_distribution

## Step 1: Create task directory — 2026-10-02T14:13:51.975Z

Pre-allocated task directory `tasks/task_3482_multistate_investigation_coordination_settlement_fund_distribution/` verified to exist with `workspace/` inside; used as-is per command args (no new index computed). Difficulty instruction: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 2: Generate scaffold — 2026-10-02T15:55:16.179Z

All gates pass. Final report.

### Summary

**Task**: Generated a fresh scaffold for `task_3482_multistate_investigation_coordination_settlement_fund_distribution` purely from the scenario text + skill spec (no sibling tasks read).

#### 1. Files written
| File | Size | Content |
|---|---|---|
| `SCAFFOLD.yaml` | 88,583 B | §1.0–§1.7 (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 122,096 B | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 270,759 B | single key `scaffold_corner_design` |

#### 2. Parse-check output
```
SCAFFOLD.yaml -> dict 13 ['api_prefix','calculations','complexity_profile','concurrency_rules','domain_name','endpoints','entities','errors','response_envelope','roles','scenario','state_machines','validations']
SCAFFOLD_DIFFICULTY_DESIGN.yaml -> dict 1 ['scaffold_difficulty_design']
SCAFFOLD_CORNER_DESIGN.yaml -> dict 1 ['scaffold_corner_design']
```

#### 3. Structural counts
- **Endpoints: 44** (at the cap; incl. `POST /_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z`)
- **Entities: 10** (StateOffice, Investigation, Participation, Demand, ConsolidatedResponse, Settlement, AllocationLine, Disbursement, Claimant, MonitoringPeriod — SignOn and injunctive terms embedded on Settlement)
- **State machines: 12** entries — Investigation (cyclic NEGOTIATION⇄DISCOVERY bounce + COLLAPSED return), Participation (parallel status × cia_status × committee_role), Settlement (cyclic PROPOSED⇄COUNTERED + parallel fund_status), Demand, ConsolidatedResponse, sign_ons embedded machine, AllocationLine, Disbursement (HELD⇄CERTIFIED cure loop), Claimant, MonitoringPeriod (auto-close compound)
- **Calculations: 10** (activation quorum, pinned-order circular lead-cost, weight normalization, per-line-floor-then-remainder shares, provisional-vs-final allocation, sign-on quorum, restitution proration dual-variant, reversion sweep, breach escalation, negotiation round cap)
- **Validations: 47** rows across 12 priority tiers; **Errors: 47**, all referenced
- **Roles: 7** (segregation of duties: Lead proposes / Defendant counters / Chair executes / Legislature certifies / FundAdministrator releases)
- **Concurrency rules: 3** OCC entries (settlement counter, revise, office PATCH — all 412 ERR_STALE_VERSION)

#### 4. Design indices
- **§1.8: 18 instances** (9 rules × 2), all with full structured replayable chains; every formula assert precomputed as literals (e.g., distributable 85,500,000; shares 10,687,500/32,062,500/42,750,000; remainder-rounding world 100,000,007 → NY 42,750,004; NEGOTIATED renormalization 2222/3333/4445)
- **§1.9: 65 instances** (59 active + 6 `excluded_because` stubs, all stubs verified to reference real §1.8 instance names)

#### 5. Difficulty trims to hold the 44-endpoint cap
Extra difficulty was redirected into state machines/calculations rather than endpoints: dropped a standalone SignOn entity (embedded array on Settlement), dropped InjunctiveTerm as an entity (term_index findings), dropped Claimant self-service role (administrator-driven), dropped the consolidated-response counter-cycle (kept the settlement cycle instead), merged pay-into-compute for restitution, and made period close automatic on term-coverage completion. Net: depth preserved (depth-5 release→closeout cascade, breach→hold→HELD cascade, dual-variant calcs in two domains, two interval semantics, bps-vs-cents conservation invariants) at exactly 44 endpoints.

#### 6. Constants
All 14 named constants carry exact values: LEAD_MIN_COUNT=2, ACTIVE_PARTICIPATION_MIN=3, SIGN_ON_WINDOW_DAYS=45, SIGN_ON_QUORUM_BPS=8000, SIGN_ON_MIN_STATES=3, MAX_SETTLEMENT_ROUNDS=4, LEAD_COST_BPS=500, LEAD_COST_CAP_CENTS=25000000, APPROPRIATION_WINDOW_DAYS=180, CLAIM_WINDOW_DAYS=90, MONITORING_PERIOD_DAYS=180, MONITORING_MAX_PERIODS=6, BREACH_ESCALATION_THRESHOLD=2, TOTAL_WEIGHT_BPS=10000. Forbidden-vocabulary sweep: 0 hits in all three files (one "simultaneously" found and fixed during QA).

#### Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(44 endpoints, 10 entities, 18 §1.8 + 59 active §1.9 instances, 1,921 calls scanned.)

Orchestrator verification: all three files re-parsed independently; api_prefix `/multistate`, domain `multistate-settlement-coordination`, 44 endpoints, 10 entities confirmed — scaffold describes the correct domain.

## Step 3: Copy shared files — 2026-10-02T15:56:07.331Z

Copied `./INSTRUCTION.md` → `tasks/task_3482_multistate_investigation_coordination_settlement_fund_distribution/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-10-02T16:17:28.846Z

PRD generation is complete and all gates pass. Final report:

### Summary

**Output:** `workspace/PRD.md` — 326 lines, 58,964 bytes, ending at §5 with no audit footer.

#### Self-verification gate counts
1. **Endpoints: 44/44** paths appear verbatim (including `POST /_clock/set_current_utc`, explicitly flagged as living outside the `/multistate` prefix).
2. **Constants: 14/14** values appear verbatim (LEAD_MIN_COUNT 2, ACTIVE_PARTICIPATION_MIN 3, MAX_SETTLEMENT_ROUNDS 4, LEAD_COST_BPS 500, LEAD_COST_CAP_CENTS 25000000, TOTAL_WEIGHT_BPS 10000, SIGN_ON_WINDOW_DAYS 45, SIGN_ON_QUORUM_BPS 8000, SIGN_ON_MIN_STATES 3, CLAIM_WINDOW_DAYS 90, APPROPRIATION_WINDOW_DAYS 180, BREACH_ESCALATION_THRESHOLD 2, MONITORING_PERIOD_DAYS 180, MONITORING_MAX_PERIODS 6), plus the clock default `2026-09-01T00:00:00Z` and pagination defaults (10/1/100/0).
3. **Error IDs: 47/47** appear in the §5 catalogue and in §2/§3 narrative.
4. **Last line** is the complete, well-formed final error-table row (`ERR_USE_CODE_NOT_PERMITTED | 422`) — not truncated.

Supplementary hard contracts: Contract 1 field coverage 91/91 backticked identifiers present (the initial regex-based run false-negatived because fenced code blocks in the verbatim §2.2 shift backtick pairing; a substring re-check confirmed full coverage); Contract 3 §3 path purity clean (no slash-prefixed, bare-method, or method+path backtick tokens); §2.2 block byte-identical to the canonical source.

#### Section outline
§1 Introduction (3 paragraphs) · §2.1 Roles/RBAC with per-role identity prose · §2.2 verbatim envelope · §2.3 Pagination · §2.4 Logical clock (unprefixed endpoint) · §2.5 Common properties + OCC (3 version-field rules) · §2.6 Precision/rounding · §2.7 Provisional vs final variants · §2.8 12-rung first-failure-wins validation ladder · §2.9 Cascades · §3.1–3.7 lifecycle narrative (committee formation → demands/responses → negotiation counter–revise → sign-on/execution → funding/disbursement → restitution → monitoring/closure) · §4 endpoint table (4 columns, 44 rows) · §5 error table (2 columns, 47 rows).

#### Ambiguities resolved in prose
- **First monitoring period contiguity**: scaffold's "previous period must be CLOSED_*" has no predecessor for period 1; prose scopes the contiguity gate to periods with a predecessor.
- **Defensive-looking transitions** (`ELIGIBLE → DISBURSED` on full-coverage release, `ELIGIBLE → REVERTED` on sweep) are technically hard to reach since creation flips lines to `DISBURSING`; transcribed faithfully without editorializing.
- **Lead-window overlap** rendered both as the phase-set form (OPEN/DISCOVERY/NEGOTIATION/SETTLEMENT_PENDING on another investigation) and the half-open `[opened_at, settled_at)` interval form with adjacency permitted, matching the scaffold's two phrasings.
- The provisional weight tie-break by `invited_at` ascending (vs `decided_at` for final) was caught as a Contract 2 gap mid-review and added to §2.7.

#### Design-index isolation
Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point; sources used were only `SCAFFOLD.yaml`, the doc-generator skill, its `section-2.2-response-structure.md`, and the example PRD.

Orchestrator verification: `wc -lc` = 326 lines / 58,964 B; §4 table = 44 endpoint rows (43 under `/multistate/` + 1 unprefixed clock, mentioned twice); error table = 47 `ERR_` rows; tail is a complete error-table row.

## Step 5a: Generate test helpers (Stage 1) — 2026-10-02T16:38:32.424Z

Step 5 was split into 5a (helpers, frozen) + 5b (tests) per oversized-generation-step practice. Orchestrator pre-measured design indices: queue A = 18 active instances (9 rules × 2, 0 stubs), queue B = 59 active + 6 stubs across 9 sections (entities 7, state_machines 12, calculations 7, validations 2+4s, endpoints 4, errors 17+2s, rbac 6, complexity_layers 3, consistency_model 1) = 77 active total. Counts passed into 5a/5b prompts.

Stage 1 is complete and verified. Here is the full exit summary.

### 1. Files written (all under the task directory)

| File | Lines |
|---|---|
| `test_helpers/__init__.py` | 35 |
| `test_helpers/types.py` | 336 |
| `test_helpers/api_client.py` | 263 |
| `test_helpers/api_errors.py` | 107 |
| `test_helpers/assertions.py` | 231 |
| `test_helpers/factories.py` | 141 |
| `test_helpers/constants.py` | 97 |
| `test_helpers/test_users.py` | 43 |
| `test_helpers/fixtures.py` | 503 |
| `test_suite/conftest.py` | 53 |

No `test_*.py` files written; SCAFFOLD*.yaml and PRD.md untouched.

### 2. Verification outputs (verbatim)

```
$ python3 -c "import test_helpers, test_helpers.types, test_helpers.api_client, test_helpers.api_errors, test_helpers.assertions, test_helpers.factories, test_helpers.constants, test_helpers.test_users, test_helpers.fixtures; print('IMPORTS OK')"
IMPORTS OK

$ python3 -m py_compile test_helpers/__init__.py test_helpers/types.py test_helpers/api_client.py test_helpers/api_errors.py test_helpers/assertions.py test_helpers/factories.py test_helpers/constants.py test_helpers/test_users.py test_helpers/fixtures.py test_suite/conftest.py && echo "PY_COMPILE OK"
PY_COMPILE OK
```

### 3. Frozen public interface (Stage 2 codes against this)

- **api_client**: `api_client` singleton; `ApiClient(GenericApiClient)` with 44 methods — one per endpoint. Critical: `set_clock(payload, headers)` posts to `/_clock/set_current_utc` **without** the `/multistate` prefix (PRD §2.4); all other 43 methods use `BASE="/multistate"`. Payload-free actions (`designate_lead`, `withdraw_participation`, `accept_response`, `fulfill_response`, `agree_terms`, `open_sign_on`, `execute_settlement`, `restitution_compute`, `certify_disbursement`, `release_disbursement`, `create_monitoring_period`) send an explicit empty JSON body `{}`.
- **api_errors**: `ApiErrorId` (45 members), `HTTP_STATUS_CODES` (registered with `set_error_http_status_map` at import).
- **types**: 20 enums (`UserRole`, `InvestigationPhase`, `SettlementTermStatus`, `FundStatus`, `SignOnStatus`, `DisbursementStatus`, `ClaimantStatus`, `MonitoringPeriodStatus`, …) + 11 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` — every entity in this scaffold is `common_fields: true`) + `SignOnEntry`/`Finding` embedded TypedDicts + `World` composite.
- **assertions**: `assert_state_office/investigation/participation/demand/consolidated_response/settlement/allocation_line/disbursement/claimant/monitoring_period(data)`, `assert_sign_on_entry(entry)`, plus invariants `assert_line_gross_invariant(line)` (disbursed+reverted+remaining == gross) and `assert_weights_sum_to_total(lines, total_bps=10000)`.
- **factories**: 18 `*_payload(**overrides)` builders (create/patch per input-carrying endpoint; canonical defaults: total 100000000, reserve 10000000, POPULATION, 3 terms).
- **test_users**: `TEST_USERS` with 7 keys (`committee_chair_headers`, `lead_state_ag_headers`, `participating_state_ag_headers`, `defendant_counsel_headers`, `fund_administrator_headers`, `state_legislature_headers`, `compliance_monitor_headers`) + builders `make_lead_state_ag_headers(user_id)`, `make_participating_state_ag_headers(user_id)`, `make_state_legislature_headers(user_id)` for the 3 entity-backed roles.
- **fixtures**: 31 primitive creators + 16 composites. Composite chain (each returns/refreshes a `World` dict with `offices`/`participations` keyed by state code): `setup_offices` → `setup_draft_world` → `setup_open_world` → `setup_negotiation_world` → `setup_proposed_world` → `setup_sign_on_open_world` → `setup_executed_world` (records sign-ons then executes; returns `lines` in decided_at order) → `fund_world` → `setup_fully_disbursed_world` (full deposit, SETTLED, all lines released — handles NY's certify step) → `setup_monitoring_world` → `setup_all_periods_compliant_world(period_count=6)` (drives the CLOSED_OUT→CLOSED cascade). Ownership-gated calls thread `make_*_headers(office["id"])`; AG role selection follows the participation's `committee_role`. All setup calls use `get_success_data`, with `201` passed explicitly on every create endpoint.
- **conftest**: session-scoped `api` fixture + 7 role-header fixtures (named exactly as the TEST_USERS keys).

### 4. Frozen constants (exact values)

`LEAD_MIN_COUNT=2`, `ACTIVE_PARTICIPATION_MIN=3`, `MAX_SETTLEMENT_ROUNDS=4`, `LEAD_COST_BPS=500`, `LEAD_COST_CAP_CENTS=25000000`, `SIGN_ON_WINDOW_DAYS=45`, `SIGN_ON_QUORUM_BPS=8000`, `SIGN_ON_MIN_STATES=3`, `TOTAL_WEIGHT_BPS=10000`, `APPROPRIATION_WINDOW_DAYS=180`, `CLAIM_WINDOW_DAYS=90`, `MONITORING_PERIOD_DAYS=180`, `MONITORING_MAX_PERIODS=6`, `BREACH_ESCALATION_THRESHOLD=2`, `CLOCK_DEFAULT="2026-09-01T00:00:00Z"`. Derived dates were recomputed arithmetically and match the design recipes' literals exactly: sign-on deadline 2026-10-16 (past: 2026-10-17), claim window end 2026-11-30 (past: 2026-12-01), appropriation end 2027-02-28 (past: 2027-03-01), monitoring period starts `["2026-09-01","2027-02-28","2027-08-27","2028-02-23","2028-08-21","2029-02-17"]`. Canonical-world economics also frozen: lead cost 4500000, distributable 85500000, weights {CA 1250, TX 3750, NY 5000}, provisional weights {CA 1000, TX 3000, NY 4000, FL 2000}, shares {CA 10687500, TX 32062500, NY 42750000}, lead bonus {CA/TX 2250000}, gross {CA 12937500, TX 34312500, NY 42750000}.

### 5. Unsatisfiable skill requirements

None. Both design indices were pre-scanned (18 difficulty + 59 non-stub corner instances, 6 excluded stubs whose pointers resolve): every non-trivial `setup_api_calls` chain maps onto a frozen composite, and the two custom-office recipes (AA/BB/CC/DD count-clause; ZZ uninvited-office) are reachable via `setup_offices(office_codes, office_specs)` / `create_state_office` primitives.

Orchestrator verification: 10 files / 1,809 lines on disk; all 15 constants re-read from `test_helpers/constants.py` match the scaffold values; `import test_helpers.api_client` resolves to the real module file and exposes the `api_client` singleton.

## Step 5b: Generate test suite (Stage 2) — 2026-10-02T17:27:04.849Z

All exit gates pass. Final report:

### Stage 2 complete — task_3482 (77/77 instances emitted, 0 skipped)

#### Files written (11 files, 77 tests)
| File | Tests |
|---|---|
| `test_01_office_registry.py` | 6 |
| `test_02_committee_formation.py` | 6 |
| `test_03_discovery_and_advance_gates.py` | 8 |
| `test_04_settlement_negotiation.py` | 7 |
| `test_05_sign_on_and_execution_gates.py` | 8 |
| `test_06_execution_economics.py` | 8 |
| `test_07_funding_and_disbursement_gates.py` | 8 |
| `test_08_disbursement_lifecycle.py` | 5 |
| `test_09_restitution.py` | 7 |
| `test_10_monitoring_and_closure.py` | 8 |
| `test_11_auth_ownership_and_withdrawal.py` | 6 |

All under `test_suite/`.

#### Exit gate outputs (verbatim)
- AST audit tail: `test functions found: 77` / `unique tags resolved: 77` / `queue A covered: 18/18` / `queue B covered: 59/59` / `instances skipped (PRD-filter): 0` / `AUDIT_OK` (full 77-row resolution table printed; every row OK, no duplicates, no stub tags, every docstring ends with exactly one Design line; instance lists were re-derived from the two yamls by the audit script itself, confirming the orchestrator-measured 18+59 and 6 stubs).
- Collect tail: `77 tests collected in 0.25s` (0 errors).
- `python3 -m py_compile test_suite/*.py` → `COMPILE_OK`.
- Bonus C1 sweep: all 144 quoted docstring fragments (≥25 chars, splice-split) grep verbatim in `workspace/PRD.md` — 0 misses (two initial misses, a paraphrased "section 2.8" vs the PRD's "§2.8" and a spliced "and", were fixed and re-verified).

#### Skip list
None — every one of the 77 active instances passed the PRD-first two-condition filter.

#### Helper-interface workarounds (test_helpers/ untouched; for Step 7 tracking)
1. **Timestamp rendering**: PRD §2.5 mandates three fractional digits for `created_at`/`updated_at` while the clock default is written `2026-09-01T00:00:00Z`; all timestamp equality assertions use a per-file `_same_instant()` datetime-parse helper instead of the recipes' literal string equality.
2. **Version start value not pinned in PRD** ("starts at its initial value"): OCC tests (`settlement_counter_cycle`, both 412 tests) capture the created version and assert relative increments (v+1/v+2) per "increments by exactly 1 on every mutation"; the create-defaults test asserts `version` is an int rather than the recipe's literal `== 1`.
3. **Tied timestamps → unspecified list order**: all sign-ons/lines share the frozen clock, so the recipes' positional captures (`$.data[0]` etc.) are not PRD-derivable; allocation lines are matched by `state_code` and claimants by `id`.
4. **`execute_lapses_silent_eligible_state`**: a LAPSED entry's `decided_at` is not PRD-pinned for silent offices — asserted status/entry-count only, not that timestamp.
5. **`period_limit_reached`**: clock moved to period 7's `window_start` before the trigger so the rung-10 temporal gate passes and `ERR_PERIOD_LIMIT_REACHED` (rung 11) fires unambiguously under the §2.8 ladder.
6. **Unobservable sub-assertions dropped**: `office_missing_required_population`'s "no StateOffice persisted" (no list-offices endpoint exists); claimant/disbursement status checks go through list endpoints matched by id (no single-GET for those resources).
7. **Mixed-outcome periods**: frozen `run_compliant_period` files one uniform outcome per term, so breach periods (2× BREACH then COMPLIANT) are filed manually via `file_finding` in the three cascade/hold tests.

Orchestrator verification: independent AST audit re-run from the two source yamls — 77 test functions, 77 unique resolved tags, 0 bad tags, 0 uncovered instances, 6 stubs correctly untested; `pytest --collect-only` = 77 collected, 0 errors.

## Step 6: Generate implementation — 2026-10-02T18:08:59.856Z

All checks complete. Final report:

### Step 6 Implementation Complete — task_3482_multistate_investigation_coordination_settlement_fund_distribution

#### 1. File tree with line counts (`workspace/implementation/`, 2411 lines total)

```
start.sh                       10   (executable, exec python3 app.py, guarded pip install)
requirements.txt                1   (flask>=3.0)
app.py                         74   (app factory, blueprint registration, envelope'd error handlers, global RLock)
db.py                         105   (in-memory stores, logical clock default 2026-09-01T00:00:00Z, id/seq/touch)
errors.py                      76   (ApiError + catalog constructors)
envelope.py                    44   (§2.2 envelope: meta/api_request_id/api_request_timestamp, response_type, data, pagination meta)
auth.py                        80   (§2.1: 7 roles, entity-backed vs opaque, ownership + LEAD+ACTIVE lead-gate)
validate.py                   183   (rung-3 body schema, pagination clamp 1..100/default 10, rung-4 path resolvers)
serialize.py                  141   (per-entity field lists, 3-fractional-digit ISO rendering, "_" private keys stripped)
calc.py                       132   (all 10 calculation constants + round-half-up, lead-cost, weight normalization, share floors, lead bonus, quorum)
services.py                    65   (provisional variant, settlement child lookups, DISBURSING→DISBURSED check)
routes_offices.py             111   (clock unprefixed + state-offices CRUD/OCC + office-scoped lists)
routes_investigations.py      188   (create/get/advance with all phase gates + lead-window overlap + 3 investigation lists)
routes_participations.py      134   (invite/execute-cia/designate-lead/withdraw)
routes_demands_responses.py   144   (demand create/list, response create/accept/fulfill with fold cascade)
routes_settlements.py         180   (propose/get/counter/revise/agree-terms, provisional variant, OCC, round cap, bounce/return)
routes_settlement_flow.py     237   (open-sign-on, sign-ons, execute: quorum/collapse/final allocation/line creation, deposit)
routes_lines_disbursements.py 176   (line reads, disbursement create w/ auto-certify, certify, release cascade)
routes_claimants.py           172   (register/list/validate, restitution-compute: reversion sweep then proration)
routes_monitoring.py          158   (period open/list, findings with auto-close, breach escalation, cure, close-out cascade)
```

#### 2. py_compile: all 18 `.py` modules compile cleanly (`ALL_OK`).

#### 3. Smoke-test transcript (self-written, NOT the test suite; forbidden files untouched)

Round 1 — port 50387, pid 2402071: **73/73 PASS**. Slice: clock set (200, `current_utc: "2026-09-01T00:00:00.000Z"`) → `/multistate/_clock/...` correctly 404s → 3 offices 201 → duplicate state_code 400 → investigation DRAFT → premature advance 422 ERR_ACTIVATION_QUORUM_MISSING → 3 invites → execute-cia (RESTRICTED/LEAD_ONLY/STANDARD) → cross-office withdraw 403 → 2 designate-lead → STANDARD-tier designation 422 ERR_CIA_TIER_INSUFFICIENT → advance OPEN/DISCOVERY → NEGOTIATION blocked 422 ERR_NO_ACCEPTED_RESPONSE → demand 201 → response 201 → accept 200 (demand folded CONSOLIDATED) → advance NEGOTIATION → propose 201 (provisional_distributable 8550000, weights {CA:1666, NY:3333, TX:5001} sum 10000) → counter stale 412 ERR_STALE_VERSION → counter 200 round 1 + phase bounced DISCOVERY → revise 200 + phase returned NEGOTIATION → agree-terms → SETTLEMENT_PENDING → open-sign-on → early execute 422 ERR_QUORUM_NOT_MET → 3 sign-ons 201 → duplicate 409 → execute 200 EXECUTED (distributable 8550000, lead 450000, 3 LOCKED, 3 lines, gross sum 9,000,000, lead bonus 225000/225000/0) → pagination meta (limit=2, total_count=3, has_more true→false) → deposits (PARTIALLY_FUNDED → 422 overshoot → FUNDED) → GENERAL_FUND_ONLY+PROGRAM 422 → PREAPPROPRIATED auto-CERTIFIED → CERTIFICATION_REQUIRED REQUESTED → certify wrong-state 403 → certify 200 → release 200 (fund DISBURSING, released_cents 1000) → claimant register/validate (6000→422 ERR_VALIDATION_EXCEEDS_CLAIM, 4000→200 estimated=4000) → early compute 422 ERR_CLAIM_WINDOW_CLOSED → advance SETTLED/MONITORING → period 1 OPEN → 2 COMPLIANT findings auto-close CLOSED_COMPLIANT → filing on closed period 409. Server killed by exact saved pid.

Round 2 — port 54907 (first run exposed a script bug: disbursement before funding correctly 409'd; added the deposit step), port 54955 rerun: **14/14 PASS**. Sign-on past deadline 422 ERR_SIGN_ON_WINDOW_CLOSED → post-deadline execute 200 COLLAPSED (investigation bounced to NEGOTIATION, active_settlement_id null) → re-propose 201 → execute 200 → deposit FUNDED → REQUESTED disbursement → claim after window 422 → compute at +181d: sweep reverted 2000 into reserve, payout 4000, remainder 998000, reserve balance 998000 → claimant PAID → second compute 409 ERR_RESTITUTION_LOCKED → line reverted/remaining recomputed. Killed by saved pid.

#### 4. Interpretations chosen (candidate over-guard audit list)

1. **Clock echo + all timestamps** rendered ISO-8601 UTC with 3 fractional digits (`...T00:00:00.000Z`), applying §2.5's rendering rule uniformly; `current_utc` echoes the parsed value canonically, not the raw input string.
2. **`meta.api_request_timestamp` uses the logical clock** (not wall clock) per §2.4 "no business operation ever consults wall-clock time".
3. **`version` starts at 1** ("starts at its initial value" is unvalued in PRD).
4. **Dangling `state_office_id` on invite → 404 ERR_STATE_OFFICE_NOT_FOUND** (rung 4); PRD names no other error for it.
5. **Sign-ons rung-5 ownership is vacuous** — the settlement has no office FK; the office identity comes from X-User-ID itself; the real gate is rung-9 ERR_NOT_A_PARTICIPANT.
6. **Deposit has no positivity guard** (PRD states only the overshoot check; a 0 deposit simply doesn't meet the `0 < deposited_cents` fund-transition trigger). Deliberately no invented guard.
7. **Revise does not re-validate total > reserve** (PRD states no check on revise; type-checked only).
8. **Restitution-compute on a never-executed settlement → 409 ERR_INVALID_STATE** (executed_at null makes the claim window undefined; no PRD error named). On CLOSED_OUT it's allowed (no term-status gate stated; only window + once checks).
9. **LAPSED sign-on entries carry `decision: null, decided_at: null`** (the office never decided).
10. **Pagination limit/offset clamped** to [1,100]/[0,∞); non-integer → 400.
11. **Eligible quorum set snapshotted at open-sign-on time** (§3.4 "ACTIVE participations as of open-sign-on time"); signed set taken from entries, raw values from live registry — so a late-activated office can sign (literal rung-9 reading) and counts in the numerator only.
12. **`distributable_cents` field always = base − lead_cost** (entity table's fixed formula) even when the no-lead-signed fold adds the pool back for share computation.
13. **Advance legality**: `to_phase` not among the 8 declared phase values → 400 (schema); valid-but-unreachable/skip/backward/CLOSED → 409 ERR_INVALID_PHASE.
14. **Rung-6 intra-order** follows scaffold/PRD mention order (e.g., participation-inactive before phase; term-status before phase; ERR_RESTITUTION_LOCKED before the executed-guard).
15. **Fund → DISBURSED only from DISBURSING** (machine-literal), re-evaluated after releases and after the reversion sweep.
16. **CLOSED_OUT check only at final-period close** (the machine's trigger); a fund reaching DISBURSED afterward does not retroactively close out.
17. **`unknown id fields`/extra body fields ignored** per rung 3 (e.g., `note` on counter/revise is accepted and not stored).
18. **Accept folds every listed demand unconditionally** ("folds every demand it lists"), re-stamping even an already-consolidated one.

#### 5. "No invented gates" self-report (every gate → PRD citation)

- ERR_UNAUTHENTICATED/ERR_UNAUTHORIZED_ROLE/ERR_NOT_RESOURCE_OWNER — §2.1, §2.8 rungs 1/2/5.
- ERR_INVALID_REQUEST (schema, total≤reserve, reserve<0, empty terms, claimed≤0, dup state_code, missing validated_loss on VALIDATED) — §2.8 rung 3, §3.1, §3.3, §3.6, §5.
- All nine 404s — §2.8 rung 4.
- ERR_STALE_VERSION (counter/revise/PATCH office, rung 7, after state gates) — §2.5.
- ERR_INVALID_PHASE (advance legality, demand create, response create, settlement create, open-sign-on, execute, designate-lead) — §2.8 rung 6, §3.1–3.4.
- ERR_INVALID_STATE (withdraw from non-ACTIVE, execute-cia non-INVITED, accept/fulfill/counter/revise/agree from wrong status, deposit non-EXECUTED, claimant ops non-EXECUTED/non-REGISTERED, certify/release from wrong status, SETTLED advance without EXECUTED, findings on non-OPEN period, second live settlement, compute pre-execution) — rung 6, §3.x.
- ERR_PARTICIPATION_INACTIVE (demand create, designate-lead) — §3.1/§3.2. ERR_LINE_NOT_DISBURSABLE, ERR_SETTLEMENT_NOT_FUNDED (disb create, advance MONITORING), ERR_RESTITUTION_LOCKED, ERR_SIGNED_STATE_CANNOT_WITHDRAW — rung 6, §3.1/§3.5–3.7.
- ERR_COMPLIANCE_HOLD_ACTIVE (create+release, rung 8) — §2.8, §3.5, §3.7.
- ERR_NOT_A_PARTICIPANT / ERR_RESPONSE_DEMANDS_INVALID / ERR_INVALID_TERM_INDEX (rung 9) — §3.4/§3.2/§3.7.
- ERR_SIGN_ON_WINDOW_CLOSED / ERR_CERTIFICATION_WINDOW_CLOSED / ERR_CLAIM_WINDOW_CLOSED (register ≤ +90d; compute strictly after) / ERR_LEAD_WINDOW_OVERLAP (rung 10, before quorum rung 11) / ERR_PERIOD_NOT_CONTIGUOUS / ERR_PERIOD_NOT_STARTED — rung 10, §3.1, §3.4–3.7.
- ERR_DUPLICATE_PARTICIPATION / ERR_DUPLICATE_SIGN_ON / ERR_DUPLICATE_FINDING / ERR_NEGOTIATED_SHARES_INVALID (incl. missing map → 422 per §5 wording "missing/mismatched") / ERR_ACTIVATION_QUORUM_MISSING / ERR_NEGOTIATION_EXHAUSTED (cap 4, rounds 1–4 allowed) / ERR_QUORUM_NOT_MET (≤deadline only; >deadline collapses) / ERR_CIA_TIER_INSUFFICIENT / ERR_PERIOD_LIMIT_REACHED (6) / ERR_NO_ACCEPTED_RESPONSE / ERR_NO_AGREED_SETTLEMENT (rung 11) — §3.1–3.7.
- ERR_DEPOSIT_EXCEEDS_TOTAL / ERR_INSUFFICIENT_FUND_BALANCE / ERR_AMOUNT_EXCEEDS_REMAINING / ERR_VALIDATION_EXCEEDS_CLAIM / ERR_USE_CODE_NOT_PERMITTED (rung 12) — §3.5/§3.6.

Calculations implemented per §1.3/§2.6/§2.7: activation quorum (2/3 inclusive), round cap 4, lead-cost pinned order (min(25,000,000, round-half-up(5% of base))), weight normalization (floor + largest-raw remainder, ties decided_at/invited_at ASC, never id), line shares (floor then remainder, weight DESC then decided_at ASC), lead bonus (equal split, remainder to earliest-designated lead; fold-back when no lead signed), provisional vs final inclusion sets, sign-on quorum (round-half-up ratio ≥ 8000 bps AND ≥ 3 states, eligible snapshotted at open), reversion sweep (requested_at ASC), restitution proration (floor then validated-DESC/created-ASC remainder), breach escalation (≥2 hold+HELD, ==0 cure, 1 untouched), monitoring windows (half-open 180-day, index ≤ 6), close-out (period 6 clean + DISBURSED → CLOSED_OUT → investigation CLOSED). Cascade mutations bump `version` exactly once per touched entity (§2.9).

#### 6. Isolation confirmation

Read only `INSTRUCTION.md`, `SCAFFOLD.yaml`, `workspace/PRD.md`, and the generator `SKILL.md`. Never opened or grepped `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/`, and never ran pytest. The store starts empty on every boot; no seeding anywhere (verified by grep). Servers were launched only by smoke scripts on dynamically allocated ports and killed by exact saved PIDs.

Orchestrator verification: all 18 modules compile (independent `py_compile`); independent boot check on dynamic port 34999 — server came up, unprefixed `POST /_clock/set_current_utc` answered with proper envelope error for a bad field (`to_iso8601` is the PRD-pinned request field; PRD §2.4 + SCAFFOLD line 976 confirm impl matches PRD), `POST /multistate/state-offices` likewise validated schema (requires `harm_measure_cents`); `meta.api_request_timestamp` reflects logical clock. Server killed by exact PID; port freed (first boot attempt orphaned a server on port 38721 due to an orchestrator shell-grouping bug `cmd1 && cmd2 &`; orphan found via `ss -tlnp` and killed by exact PID 2416326).

## Step 7: Test–fix iteration loop — 2026-10-02T18:23:18.351Z

Clean sweep: all 8 rounds pass 77/77, and the `results.{1..8}.json` artifacts remain on disk.

### Summary

- **Iterations run:** 2 (initial sweep → 2 fixes → clean re-sweep).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py` — `setup_negotiation_world()`: the default demander was hardcoded to `CANONICAL_LEAD_CODES[0]` ("CA"), so any world built with custom `office_codes`/`lead_codes` that excludes CA crashed with `KeyError: 'CA'` during setup. Now defaults to the world's own first lead code (`kwargs.get("lead_codes", CANONICAL_LEAD_CODES)[0]`). Fixed `test_quorum_count_clause_isolated_collapse`.

- **Fixes applied to `test_suite/`:**
  - `test_04_settlement_negotiation.py::test_revise_with_new_total_recomputes_provisional` — the expected `provisional_weight_bps_by_state` of `{CA:1000, TX:3000, NY:4000}` was the design index's arithmetic error: those are the canonical 4-office weights (FL pop 200 in the denominator, total 1000), but the test's own setup builds only 3 offices (CA 100 / TX 300 / NY 400, total 800), so PRD §2.7's normalization over ACTIVE participations uniquely yields `{CA:1250, TX:3750, NY:5000}` — exactly what the implementation returned. Assertion corrected to the PRD-derived values (with a comment recording the discrepancy); rule itself remains PRD-verbatim and uniquely derivable.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on both paths.

- **Final sweep artifacts:** `results.1.json` … `results.8.json` all present in `workspace/implementation/`, each `passed=77/total=77`. Not modified after the clean sweep.

- **Test-side fixes dominated (2 test-side, 0 impl-side).** Sibling unasserted paths implied for Step 8:
  1. The fixture bug meant no custom-world test ever exercised `setup_negotiation_world`'s demand-issuance with a non-CA lead; other custom worlds (e.g., `test_06`'s 5-office NV world) still default to canonical leads — the discovery-demand flow with alternate lead orderings is only thinly covered.
  2. The corrected weight assertion means the recompute-on-revise path is now verified against a non-canonical denominator, but the companion claim in the same design instance — provisional weights *unchanged* from proposal when only the total changes — is asserted only implicitly (same expected dict pre/post revise is never diffed against the proposal-time value); a dedicated proposal-vs-revise weight comparison remains unasserted.

Orchestrator verification: all 8 `results.{i}.json` re-read — each `passed=77, failed=0, total=77, errors=0`; `find test_suite test_helpers workspace/implementation -name '*.py' -newer workspace/implementation/results.1.json` is empty (no post-sweep source edits; `__pycache__` mtime noise excluded by checking source files only). Spot-checked both claimed fixes in source: `fixtures.py:338` carries the new demander default; `test_04:146-151` carries the corrected {CA:1250, TX:3750, NY:5000} assertion with explanatory comment.

## Step 8: Finalize PRD — 2026-10-02T18:28:27.712Z

Step 8 ran (Step 7 had 2 test-side fixes, so the skip condition was not met). The zero-edit outcome was explicitly permitted in the prompt since both diff items were test-side.

Zero-edit outcome confirmed. `PRD_FINALIZED.md` is in place at `workspace/PRD_FINALIZED.md`, byte-identical to `PRD.md`.

### Summary

**Line counts / delta:** PRD.md 326 lines, PRD_FINALIZED.md 326 lines, 0% delta — zero edits, confirmed via `diff -q` (byte-identical). Both `<step_7_diff>` items are test-side fixes; neither reveals a PRD silence nor a PRD/impl mismatch, so no PRD edit was warranted.

**Per-item analysis:**

- `test_helpers/fixtures.py setup_negotiation_world() demander default` — no PRD edit needed — this was a pure fixture-internal Python default bug: the helper hardcoded `CANONICAL_LEAD_CODES[0]` ("CA") and crashed with `KeyError: 'CA'` during test *setup* (fixtures.py:338), before any API semantics were exercised. The implementation's demand endpoint (`implementation/routes_demands_responses.py:17-44`) pins its own rule — any AG-role caller whose own office's participation is `ACTIVE` may issue a demand in OPEN or DISCOVERY phase — and that rule is already pinned by the PRD (the demand-issuance gate is the executed-CIA/ACTIVE-participation requirement reflected at routes_demands_responses.py:24-29, with the phase gate at lines 30-32). Which office a *test* picks as demander is scenario freedom, not an implementation behavioral choice; nothing the impl does here is under-determined by the PRD.

- `test_04_settlement_negotiation.py::test_revise_with_new_total_recomputes_provisional` — no PRD edit needed — the design index's expected weights `{CA:1000, TX:3000, NY:4000}` used the canonical 4-office denominator (FL pop 200 included, total 1000), but the test builds only 3 offices (CA 100 / TX 300 / NY 400, total 800). PRD §2.7 already uniquely determines the result with the verbatim sentence: "it evaluates the lead-cost and distributable-pool formulas and the weight-normalization formula over the investigation's `ACTIVE` participations at proposal time, reading live state-office registry values" (PRD.md:108), with the normalization discipline pinned at PRD.md:104 (integer bps summing to exactly 10000, floor + one-at-a-time remainder) and the revise-recompute trigger at PRD.md:171 ("the provisional allocation variant is recomputed against the new total"). The impl matches exactly: `implementation/services.py:15-37` (`compute_provisional` over ACTIVE participations, live registry values, `invited_at` ASC tie-break), `implementation/calc.py:59-79` (`normalize_weights`: floor then remainder to largest raw), and the revise path `implementation/routes_settlements.py:159-161` recomputes on `revised_total_cents` — yielding `{CA:1250, TX:3750, NY:5000}`, exactly what the impl returned and the corrected test now asserts.

**Per-item enumeration log (what was read to conclude pure test-side bugs):**

- Item 1: read `test_helpers/fixtures.py:290-368` (the fixture family: `setup_draft_world` → `setup_open_world` → `setup_negotiation_world` → `setup_proposed_world`, confirming the fixed line 338 is a world-construction default, not an API behavior); read `implementation/routes_demands_responses.py:1-60` (full `create_demand` gate chain: role check, own-office check, ACTIVE check, phase check — no first-lead or canonical-office constraint anywhere); confirmed the KeyError occurred in fixture setup before `issue_demand` was called.
- Item 2: read `PRD.md:104-108` (§2.7 provisional-variant definition and rounding disciplines), `PRD.md:165-171` (proposal stores provisional outputs; revise-with-new-total recomputes), `PRD.md:183` (final-variant normalization formula, which §2.7 shares with different inclusion set); read `implementation/services.py` in full (ACTIVE-participation inclusion set at lines 7-12 and 24, live registry read at 25/31, tie-break fields at 32-33); read `implementation/calc.py:40-133` (`raw_basis_value` POPULATION → `office["population"]`, `normalize_weights` floor+remainder); read `implementation/routes_settlements.py:140-168` (revise endpoint: COUNTERED gate, OCC guard, recompute-on-new-total, DISCOVERY→NEGOTIATION auto-return — all PRD-verbatim); read the corrected test at `test_suite/test_04_settlement_negotiation.py:125-151` (assertion now PRD-derived with the discrepancy comment). Since zero edits were made, no pre-edit search log applies.

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical; both 326 lines / 58,964 B.

## Step 9: Complete PRD — 2026-10-02T18:57:35.386Z

All 22 edits landed; the diff touches exactly 22 lines with no line-count change (all inline, per the minimal-patch rule). The walk, adjudication, and sweeps are complete. Final report:

### Result

**Source vs output:** `PRD_FINALIZED.md` 326 lines / 58,964 chars → `PRD_COMPLETED.md` 326 lines / 62,114 chars (char-delta **+3,150**; 22 lines edited in place, zero lines added/removed, zero new sections).

**Counts:** 22 ambiguity-pins, 1 mismatch-revision (23 behavior pins across 22 edits), **0 impl bugs reported**.

### Changes (one bullet each)

1. §2.1 — insert — ambiguity — empty `X-User-ID` for an entity-backed role counts as missing → 401 — `auth.py:34`
2. §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; integer `limit` clamped to [1,100], negative `offset` clamped to 0 — `validate.py:96-110`
3. §2.3 — insert — ambiguity — `created_at` ties in list ordering broken by creation sequence, never id (ties are the norm under the frozen clock) — `validate.py:113-117`
4. §2.4 — insert — ambiguity — clock value parsing: explicit offsets normalized to UTC, naive values read as UTC, unparseable → 400 — `db.py:28-46`, `routes_offices.py:22-26`
5. §2.5 — revise — ambiguity — `version` starts at **1** on creation — `db.py:95`
6. §2.6 — insert — ambiguity — when a rule's pinned tie-break timestamp is itself identical, remaining order is record creation sequence — `calc.py:73,90`, `routes_settlement_flow.py:106,125`, `routes_claimants.py:139,155`
7. §2.8 rung 3 — revise — ambiguity — **all** extraneous body fields ignored, not only id fields — `validate.py:14-25`
8. §2.9 — revise — **mismatch** — fund reaches `DISBURSED` only from `DISBURSING` ("from there"); a never-disbursing fund does not jump to `DISBURSED` even if every line reverts — `services.py:49-58`. Losing passage: the unconditional reading of §2.9's summary sentence; the detailed §3.5 rule ("moves to DISBURSING on the first release … and on to DISBURSED …") wins.
9. §3.1 — insert — ambiguity — office PATCH updatable fields are `population`/`harm_measure_cents`/`appropriation_rule`; `state_code` immutable (supplied value ignored); a no-field update still bumps `version`/`updated_at` — `routes_offices.py:62-85`
10. §3.1 — insert — ambiguity — invitations accepted in any investigation phase; unregistered `state_office_id` in the body → `ERR_STATE_OFFICE_NOT_FOUND` (404) — `routes_participations.py:18-37`
11. §3.1 — insert — ambiguity — re-designating an already-`LEAD` participation is accepted and re-stamps the designation order used for lead-bonus remainder cents — `routes_participations.py:82-103` (`_lead_seq` reassigned)
12. §3.1 — insert — ambiguity — withdrawal of a non-`ACTIVE` participation (`INVITED`/already `WITHDRAWN`) → `ERR_INVALID_STATE` — `routes_participations.py:113-114`
13. §3.2 — insert — ambiguity — repeated ids in `demand_ids` are not rejected; each entry validated independently, folded idempotently at acceptance — `routes_demands_responses.py:76-94,123-130`
14. §3.3 — insert — ambiguity — `negotiated_shares` under `POPULATION`/`HARM_MEASURE` is accepted and stored unvalidated; share values are not sign-checked (only key set + 10000-sum) — `routes_settlements.py:30,50-65,73`
15. §3.3 — revise — ambiguity — a counter omitting `counter_total_cents` leaves the previously recorded value unchanged; the free-text `note` is never persisted — `routes_settlements.py:116-117,131-133`
16. §3.3 — revise — ambiguity — a revise does not re-validate the new total against `restitution_reserve_cents`; its `note` likewise never persisted — `routes_settlements.py:149-161`
17. §3.4 — insert — ambiguity — `LAPSED` sign-on entries carry `decision` null / `decided_at` null and are appended in participation creation order — `routes_settlement_flow.py:99-118`
18. §3.5 — insert — ambiguity — deposit `amount_cents` has no pinned lower bound (zero/negative accepted); only the cumulative-total cap is enforced — `routes_settlement_flow.py:217-226`
19. §3.5 — insert — ambiguity — deposits made after the fund reaches `DISBURSING`/`DISBURSED` still raise `deposited_cents` up to the cap but never move `fund_status` backward — `routes_settlement_flow.py:227-235`
20. §3.6 — revise — ambiguity — `VALIDATED` omitting `validated_loss_cents` → `ERR_INVALID_REQUEST` (400); a non-positive value → `ERR_VALIDATION_EXCEEDS_CLAIM` (same error as over-claim); `validated_loss_cents` supplied with `DENIED` is ignored — `routes_claimants.py:72-90`
21. §3.6 — insert — ambiguity — restitution-compute against a never-executed settlement → `ERR_INVALID_STATE` (409) — `routes_claimants.py:104-105`
22. §3.7 — revise — ambiguity — `term_index` is **0-based** — `routes_monitoring.py:98`
23. §5 — insert — ambiguity — failures outside the catalogue are reported in the same envelope as `ERR_INTERNAL` (HTTP 500) — `app.py:62-66`

### IMPL BUGS

**None found.** Sweep evidence:

- **Uniqueness sweep** — PRD grep (`unique|at most one|no two|duplicate|only one`) yields 5 entity-level declarations; all enforced by store scans: `state_code` uniqueness (`routes_offices.py:39-41` → `ERR_INVALID_REQUEST`), one non-WITHDRAWN participation per office per investigation (`routes_participations.py:27-37` → `ERR_DUPLICATE_PARTICIPATION`), one live settlement per investigation (`routes_settlements.py:44-48` → `ERR_INVALID_STATE`), one sign-on per office (`routes_settlement_flow.py:62-66` → `ERR_DUPLICATE_SIGN_ON`), one finding per term per period (`routes_monitoring.py:104-110` → `ERR_DUPLICATE_FINDING`).
- **Dead-check sweep** — all 47 catalog error ids appear at ≥1 raise site; helper-mediated errors confirmed via call-site counts (`invalid_request`:19, `invalid_state`:20, `invalid_phase`:7, `stale_version`:3, every 404-helper ≥1). Every guard's triggering field is writable: `compliance_hold` written at `routes_monitoring.py:129,139`, `restitution_computed` at `routes_claimants.py:170`, `eligible_snapshots` at `routes_settlement_flow.py:35`, `sign_on_deadline` at `:32`. Reachability spot-checked for the exotic ones (`ERR_PERIOD_NOT_STARTED`, `ERR_LEAD_WINDOW_OVERLAP`, `ERR_SIGNED_STATE_CANNOT_WITHDRAW`, `ERR_RESTITUTION_LOCKED`, `ERR_INSUFFICIENT_FUND_BALANCE`) — all reachable.
- **Nullable-field crash audit** — every read of `executed_at` (`routes_claimants.py:31,107,115`, `routes_lines_disbursements.py:127`, `routes_monitoring.py:39`) sits behind a `term_status == "EXECUTED"` gate or an explicit None guard (`routes_claimants.py:104`); `sign_on_deadline` reads behind `SIGN_ON_OPEN` gates; `decided_at` reads (`routes_settlement_flow.py:125,137`) iterate only `SIGNED`/`LOCKED` entries, never `LAPSED` (null) ones; empty `sign_ons`/empty `lines`/zero validated-claimant sets all handled (`calc.py:64-65,128-131`, `services.py:55`, `routes_claimants.py:147`); the only unguarded derefs (`release` line 154, `certify` line 123) require orphaned rows that no endpoint can produce (no delete paths exist).

### Walk coverage

- **Endpoints: 44/44** walked (43 under `/multistate` + the unprefixed clock), each checked for role admission, ladder ordering, gate set, OCC fields, response code (201-vs-200 against §4's list — all match), response body shape, and cascades. Route inventory matches the §4 table exactly; no extra or missing routes.
- **Calculations: 10/10** — lead-cost pinned order (`calc.py:35-43`), round-half-up divisor, weight normalization incl. zero-total fallback (`calc.py:59-79`), floor-then-remainder line shares (`calc.py:82-95`), designation-order lead-bonus split (`calc.py:98-111`), quorum ratio + 3-state conjunction (`calc.py:114-132`), provisional variant (`services.py:15-37`), final variant + line creation (`routes_settlement_flow.py:93-181`), reversion sweep + proration (`routes_claimants.py:114-171`), fund-status transitions (`routes_settlement_flow.py:227-235`, `routes_lines_disbursements.py:172-174`, `services.py:49-58`).
- **State machines: 11/11** — investigation phase chain, participation status/cia_status/committee_role, demand, response, settlement term_status, settlement fund_status, allocation line, disbursement, claimant, monitoring period, sign-on entry.
- **Latent oddity (PRD and impl agree literally, noted not flagged):** the per-request `amount_cents ≤ remaining_cents` cap permits multiple `REQUESTED` disbursements summing past a line's gross; releasing them can push `disbursed_cents` past `gross_share_cents`, after which the `==` DISBURSED check never fires. The PRD pins both the per-request cap and the equals-moment transition verbatim, so no edit was made.

Orchestrator adjudication + verification:
- Diff shape: 44 diff lines vs PRD_FINALIZED.md (= 22 in-place edits), line count unchanged 326 — not a no-op kill casualty.
- **Mismatch revision #8 exonerated against scaffold**: SCAFFOLD.yaml's `fund_status` machine has `DISBURSING → DISBURSED` as the ONLY transition into `DISBURSED` (initial UNFUNDED; deposit/release-driven); the revision matches scaffold intent and the PRD's own detailed §3.5 rule — the losing passage was an over-broad reading of §2.9's summary sentence. No impl fix needed.
- Spot-checks against impl source: `db.py:95` has `"version": 1` in the base record; `services.py:49-58` returns early unless `fund_status == "DISBURSING"`; `routes_monitoring.py:98` checks `term_index < 0 or >= len(terms)` (0-based). All three pins present in PRD_COMPLETED.md (lines 98, 131, 217) with wording consistent with the §3.5 detailed rule at line 195.
- Latent-oddity adjudication confirmed: PRD pins the per-request cap (`§3.5`, line 191) and the equals-moment transition (line 195) verbatim; impl follows both literally — PRD-faithful, correctly not edited.
- **Step 9b not required**: 0 impl bugs reported, and the independent re-checks above found none.
- Sweep validity: no `.py` under test_suite/, test_helpers/, or workspace/implementation/ is newer than `results.1.json` — Steps 8/9 touched only `workspace/*.md`; the clean 8×77/77 sweep stands. `results.{1..8}.json` all present.
