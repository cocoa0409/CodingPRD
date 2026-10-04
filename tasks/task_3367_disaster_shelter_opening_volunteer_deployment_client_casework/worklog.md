# Worklog — task_3367_disaster_shelter_opening_volunteer_deployment_client_casework

## Step 1: Create task directory — 2026-10-01T09:27:00.000Z

Task directory pre-allocated by the caller: `./tasks/task_3367_disaster_shelter_opening_volunteer_deployment_client_casework/` with `workspace/` inside. No index computation performed (per caller instruction). Verified directory exists and `workspace/` is empty; `./INSTRUCTION.md` present at project root for Step 3 copy.

## Step 2: Generate scaffold — 2026-10-01T10:14:30.000Z

The Step 2 subagent was killed mid-flight when the host session ended; its return report was lost. Per the "a lost subagent report ≠ a lost artifact" rule, the artifacts were verified against source rather than blindly re-running the step.

Verification performed by orchestrator (all three files present and complete, none truncated):
- `SCAFFOLD.yaml` (118,115 B) — `yaml.safe_load` OK; top-level keys `scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors, roles`. Counts: 15 entities, 11 state machines, 3 concurrency rules, 16 calculations, 9 validations, **69 endpoints**, 43 errors, 8 roles. `domain_name: disaster-shelter-operations`, `api_prefix: /api/v1`. `complexity_profile.primary_archetype: posture_driven_gating`, secondary `quota_allocation`; layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation`; role model `segregation_of_duties`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (148,557 B) — parses; single top-level key `scaffold_difficulty_design`, a list of 9 rule groups × 3 instances = **27 difficulty instances**, each with `name, grounds, distinguishing_aspect, test_recipe`.
- `SCAFFOLD_CORNER_DESIGN.yaml` (165,650 B) — parses; single top-level key `scaffold_corner_design`, a list of 9 section groups = **47 corner instances**, each with `name, claim_type, grounds, distinguishing_aspect` + `test_recipe` (42) or `excluded_because` (5).

Difficulty rule groups: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
Corner sections: entities(8), state_machines(6), calculations(3), validations(8), endpoints(6), errors(8), rbac(2), cross_cutting_complexity_layers(5), consistency_model(1).

Note for Step 6: 69 endpoints exceeds the 40-endpoint threshold at which impl-gen has historically degraded into a rambling report — orchestrator must verify implementation files on disk directly rather than trusting the subagent's self-report.

## Step 3: Copy shared files — 2026-10-01T10:14:50.944Z

`cp ./INSTRUCTION.md ./tasks/task_3367_disaster_shelter_opening_volunteer_deployment_client_casework/workspace/INSTRUCTION.md` — verified present (1,424 B) in `workspace/`.

## Step 4: Generate PRD — 2026-10-01T10:26:16.520Z

Subagent report (verbatim):

The PRD is complete and all three hard contracts pass. Here is my report.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_3367_disaster_shelter_opening_volunteer_deployment_client_casework/workspace/PRD.md` — **406 lines**, complete (ends at the last row of the §5 error table, no truncation, no leftover markers).

## Section list

- **§1 Introduction** (3 paragraphs)
- **§2 Global Specifications** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Shelter Posture as the Master Operational Gate · 2.5 Credentialing, Site Agreements and Inspection Currency · 2.6 The Deployable Pool and Volunteer Readiness · 2.7 Interval Integrity, Workload Caps and Occupancy Conflicts · 2.8 Donor-Restricted Money and the Cost Ledger · 2.9 Derived Fields, Precision and Common Resource Properties · 2.10 The Logical Clock and Automatic Transition Evaluation · 2.11 Nested Resource Retrieval and Validation Order · 2.12 Optimistic Concurrency Control
- **§3 Business Logic & Workflows** — 3.1 Regional Footprint and Shelter Site Readiness · 3.2 Shelter Occupancy: Registration, Dormitory Beds and Client Departure · 3.3 Feeding, Health Services and Shelter Cost Accounting · 3.4 Volunteer Credentialing, Deployment and Rotation Management · 3.5 Disaster Relief Operation Lifecycle and Deployment Candidate Selection · 3.6 Recovery Casework: Eligibility, Recovery Planning and Referrals · 3.7 Immediate Financial Assistance: Entitlement, Awards and the Card Lifecycle · 3.8 Donor Fund Pools and the Operation Cost Ledger · 3.9 Blood Collection Continuity
- **§4 Endpoint Definitions** (69 rows, 4 columns) · **§5 Error Code Catalogue** (43 rows, 2 columns)

## Hard contract reports

```
Field coverage check:
- entities[].fields: 110 required, 110 present, 0 missing
- endpoints[].input (request body + query params): 85 required, 85 present, 0 missing
- endpoints[].query_params: 0 declared as a separate key in this scaffold (all folded into input)
- endpoints[].path_params: 0 declared as a separate key (paths use {id}; `id` present)
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 9 checked, 9 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 59 checked, 59 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed, 0 missing
- validations[] conditions: 9 checked, 9 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 69 checked, 69 expressed, 0 missing
- entities[].fields[] structured content: 110 checked, 110 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 state machines checked, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 675
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 43 error IDs, all 8 role names, all 43 state values and all 101 enum field values appear verbatim in backticks; every `calculations[].constants` numeric value is embedded in prose; no fuzzy/approximating words; no `scaffold`/design-file references leaked into the document.

## Scaffold contradictions I had to adjudicate (4)

Nothing was unrenderable — these are places where the scaffold contradicts itself and I had to pick one reading. Flagging them because the test generator reads the same scaffold:

1. **`end-rotation` availability** — the `VolunteerDeployment` state machine's `ON_SHIFT → ROTATION_ENDED` side effect says the volunteer moves to `AVAILABLE` (with recall's boilerplate text), but the `end-rotation` endpoint's side effects say `RESTING`. **I rendered `RESTING`**: the endpoint table is the more specific contract for that endpoint, `RESTING` is otherwise an unreachable enum member, and the credential-refresh transition explicitly says it clears a `RESTING` availability. Recall remains `AVAILABLE` in both places.
2. **`duplication_of_benefits_offset` STEP 3** — the calculation says `0 < approved < MIN` sets the award to 0 and transitions to `DENIED`; the `AssistanceRequest` state machine note and `ERR_ASSISTANCE_BELOW_MINIMUM` say that band is rejected at 409 and stays `ELIGIBILITY_VERIFIED`. **I rendered the rejection path**, which is the only reading consistent with the `DENIED` precondition (`approved_amount_cents == 0`) and with the error catalog.
3. **`SAME_REGION_MILES` / `CROSS_REGION_MILES` are overloaded** — 0/400 in `volunteer_deployment_priority_score` but 120/400 in `travel_cost_estimate`. I gave each calculation its own values in prose and deliberately stated no global constant.
4. **Named-but-unvalued constants** — `INSPECTION_VALIDITY_DAYS`, `CREDENTIAL_VALIDITY_DAYS` and `NO_SHOW_GRACE_MINUTES` are referenced symbolically in the validation/transition tables with the value pinned elsewhere (365 in the error catalog, 30 in the credential-refresh endpoint description, 240 in the shift transition trigger). I used the pinned values rather than inventing.

---

**Orchestrator verification of the hand-back** (artifact checked against source, per the "verify subagent hand-back claims against source" rule): `PRD.md` present at 406 lines / 89,851 B, ends cleanly at the §5 error table; heading tree matches the reported section list exactly. Adjudications 1–3 confirmed in prose (lines 106/108/112 for `RESTING`, line 256 for the below-minimum rejection path, lines 216/234 for the per-calculation mileage split). Adjudication 4 confirmed: the symbolic names appear nowhere, and the pinned literals do appear (`365` ×1, `240 minutes` ×1, `30 days` ×3). All other pinned constants present as literals (21 days, 40 rotation days, 5,000 cents, 45,000/2,500/12,000/55 cents, 120/400 miles, `divided by 20`, `capped at 25`, `capped at 40 points`, `20 points`).

## Step 5: Generate unit tests — 2026-10-01T10:50:00.582Z

Subagent report (verbatim):

All work is complete and verified. Final summary:

## Files written

**`test_helpers/` (Stage 1)** — 9 files, 1,843 lines
| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 35 | barrel export (framework generics + PRD code) |
| `types.py` | 415 | 15 entity TypedDicts (all `common_fields: true`), 22 status/role enums |
| `api_client.py` | 265 | `ApiClient(GenericApiClient)`, one method per endpoint (75 public methods) |
| `api_errors.py` | 100 | `ApiErrorId` (43 ids) + HTTP map, registered via `set_error_http_status_map` |
| `assertions.py` | 203 | per-entity `assert_*`, domain invariants, `assert_instant_equals`/`parse_instant` (format-tolerant instant compare) |
| `factories.py` | 226 | 21 payload factories, input fields only |
| `constants.py` | 103 | all pinned thresholds (365/30/240/120/400/0-mile split honoured) |
| `test_users.py` | 38 | shared constants + `make_<role>_headers()` builders for the 3 entity-backed roles |
| `fixtures.py` | 458 | composite setups (`setup_open_shelter`, `setup_shelter_with_client`, `setup_casework_scenario`, `setup_funded_casework_scenario`, `setup_disbursed_assistance`, `setup_shifted_deployment`, `setup_operation_with_shelter`) with identity threading |

**`test_suite/` (Stage 2)** — 12 files, 2,955 lines: `conftest.py` + `test_01_shelter_posture.py` … `test_11_optimistic_concurrency.py` (99 tests, 0 skips/xfails).

## Coverage
- **Queue A (difficulty): 27/27 instances, all ≥2 tests** → 55 tests.
- **Queue B (corner): 42/42 non-stub instances, all ≥1 test** → 44 tests.
- 5 `excluded_because` stubs verified against their `difficulty_instance` cross-references and **not** translated.
- 99 tests collected; 137/137 PRD quotes verified as ≥8-word verbatim substrings of `PRD.md`; exactly one `Design:` tag per test, all resolving to real instance names; no skip/xfail; pyflakes clean.

## Instances SKIPPED
**None.** All 27 difficulty and all 42 non-stub corner instances passed the two-condition filter; only the 5 `excluded_because` stubs were skipped (`endpoints/deployment_candidates_computed_read_ranking`, `endpoints/shelter_cost_computed_read_reporting_mode`, `endpoints/shelter_close_conditional_action`, `endpoints/registration_conditional_action_blocked_by_posture`, `cross_cutting_complexity_layers/derived_field_reconciliation_after_recall`).

## Index bugs repaired (translated faithfully, not weakened)
1. **`priority_pair…/safety_beats_referential_on_expired_credential_mismatched_shelter`** — the recipe creates a deployment pointing at another operation's shelter and expects approval to reject it. PRD §3.4 pins that mismatch as a *creation-time* refusal, so the recipe's precondition is unreachable. Re-derived onto the creation request (PRD §2.5 explicitly extends the credential gate to "a deployment request or an approval"), which keeps both asserted outcomes: `ERR_VOLUNTEER_NOT_CREDENTIALED`, not `ERR_DEPLOYMENT_SHELTER_MISMATCH`.
2. **`validations/annual_rotation_cap_enforced_at_approval`** — the recipe checks in 8 h before `shift_start_at`, outside the PRD's 60-minute window. Clock re-derived to 07:30 (index setup was clock-unreachable).
3. **`non_linear_state_machine/client_case_reopen_cycle`** — the recipe writes a recovery plan straight after reopening, but PRD pins reopening to `eligibility_status: PENDING`; added the intermediate verification the PRD requires.
4. **`transitive_cascade/assistance_reversal_restores_restricted_fund_chain`** — the index asserts "exactly 2 ledger entries" while its own setup books 3. Asserted the load-bearing PRD claim instead (exactly one `REVERSAL` entry mirroring the 50000 award).
5. **`errors/card_issue_twice_returns_already_issued`** — issuing as the approver would trip `ERR_SOD_VIOLATION` first; the second issuance is made by a distinct officer so the card-state error is isolated.

No implementation exists under `workspace/` yet, so the suite was validated by collection + static checks rather than an end-to-end run.

---

**Orchestrator verification of the hand-back:** 21 `.py` files present, 4,800 lines total, matching the reported per-file line counts exactly. `grep` confirms exactly **99 `Design:` tags**, resolving to **27 unique `Design: Difficulty/...`** and **42 unique `Design: Corner/...`** instance names — no untagged, dual-tagged, or dangling tags. **0** `skip`/`xfail`/`skipif` occurrences. `python3 -m pytest test_suite --collect-only -q` exits cleanly: **99 tests collected in 0.20s** (the real collection run, which is the only check that catches a dangling-import package graph).

## Step 6: Generate implementation — 2026-10-01T11:21:49.807Z

Subagent report (verbatim):

Implementation complete and verified. Summary below.

## Files written (`workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher: guarded `import flask` check, `exec python3 app.py`, executable |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 77 | Blueprint wiring, error-envelope handlers, per-request lock, sweep hook |
| `errors.py` | 63 | `ApiError` + full 43-id error→HTTP catalogue |
| `core.py` | 372 | Logical clock (default `2026-09-01T00:00:00Z`), 15 in-memory dict tables, envelope/pagination, body validation, auth/RBAC, `touch`/`apply` mutation helpers |
| `calc.py` | 434 | All 16 calculations (dual-variant costs/entitlement/continuity, bed selector, scoring, travel, funds, sufficiency, closure) |
| `auto.py` | 157 | Clock-driven automatic transitions, fixed-point on every read/write |
| `routes_region.py` | 308 | Regions + sub-lists, operations, phase advance, candidates, fund pools, cost ledger |
| `routes_site.py` | 117 | Shelter sites + inspections (OCC, FAIL cascade) |
| `routes_shelter.py` | 351 | Shelter open/close cascade, registrations/bed selector, feeding, health |
| `routes_volunteer.py` | 342 | Volunteers, deployments, approvals, recall/end-rotation, shifts |
| `routes_client.py` | 77 | Clients (incl. Client self-read scoping), registration reads |
| `routes_case.py` | 426 | Cases, eligibility, recovery plans (OCC), referrals, assistance/card lifecycle |
| `routes_blood.py` | 125 | Blood drives + `/api/v1/_clock/set_current_utc` |

2,860 lines total. Storage is in-memory dicts only — no file, DB, or `/tmp` cache; no entity is seeded at boot.

## Verified boot + HTTP

`cd implementation && PORT=8137 bash start.sh` (PID saved, then killed by exact PID only). Fresh-process checks: `POST /api/v1/regions` → **201** with full envelope; `GET /api/v1/blood-drives` → **200**; previously created region id after reboot → **404**; `GET /clients` → `{"data":[], ... "total_count":0}` (state fully wiped per boot).

Three end-to-end smoke suites (≈120 assertions, all passing) covered: full shelter lifecycle incl. open-gate on staffing, the 21-client RESTRICTED flip, close cascade recalling deployments, all auto transitions (travel, credential/site expiry, NO_SHOW/COMPLETED, case closure hold), card approve→issue→redeem→reverse with exact pool restoration, every tested error id, pagination, and both calculation variants. `python3 -m py_compile` passes on all 12 modules.

## Judgment calls / PRD-vs-scaffold conflicts (PRD followed)

- **CONSOLIDATING→RESTRICTED on registration** (scaffold state machine) is unreachable: PRD §2.4 states CONSOLIDATING admits neither registration nor check-in, so those return `ERR_INVALID_STATE`.
- **Reunification**: no verify endpoint exists, so check-out with `reunification_verified_by_user_id` records the verifier and releases `REUNIFIED`; `ERR_SOD_VIOLATION` when the verifier equals the actor (or a previously recorded verifier).
- **Pool restriction compatibility** is never enumerated: UNRESTRICTED and DONOR_RESTRICTED_DISASTER accept all assistance types; DONOR_RESTRICTED_BLOOD accepts none of the client assistance types; DONOR_RESTRICTED_LOCAL requires `pool.region_id == client.region_id`.
- **PASS inspection failing its bed/accessibility precondition** → `ERR_INVALID_STATE` 409 (no dedicated error id exists).
- **`verify-eligibility` from REOPENED** allowed (payload value recorded); otherwise a reopened case could never reach RECOVERY_PLANNING again, since the PRD forces `eligibility_status=PENDING` on reopen.
- **`case_closure_eligible_at`** exposed as an extra ClientCase field (named in PRD/scaffold, absent from the entity table).
- **Collections on a PLANNED drive** are accepted; only COMPLETED/CANCELLED are refused. Region `code` uniqueness is not enforced (no error id exists for a duplicate).

---

**Orchestrator verification of the hand-back:** 13 files present, 2,859 lines — matches the reported 2,860 (±1 line from the trailing-newline count). `python3 -m py_compile *.py` passes on all 12 modules. Static route-decorator count = **69**, exactly matching SCAFFOLD.yaml's 69 endpoints. Booted the server myself on `PORT=8137` (PID saved, killed by exact PID only): Flask reports `Running on all addresses (0.0.0.0)` / `http://127.0.0.1:8137`, and `GET /api/v1/clients` with no auth headers returns **401 UNAUTHORIZED**, which is the PRD-required response — the server is genuinely serving, not just binding a port. `start.sh` is executable and guards the `pip install` behind an `import flask` check (correct for per-test-server isolation, which re-runs it before every test).

## Step 7: Run tests and iterate — 2026-10-01T12:10:05.280Z

Subagent report (verbatim):

All 8 rounds pass. Final verification is clean: no source file was written after the sweep (newest `.py` 11:56:34, results written 12:00:32), and all 8 results files exist with `passed == total`.

## Summary

**Iterations run:** 3 sweeps. Round 1 = 45/99, round 2 = 96/99, round 3 = **99/99 in all 8 parallel rounds**.

**Tests deleted: 0.** Every one of the 54 failures resolved without invoking the PRD-silence deletion criterion.

### Fixes to `implementation/` (3)

| File | Function | Why |
|---|---|---|
| `workspace/implementation/routes_region.py` | `deployment_candidates` | Returned `list_response(ranked)`, which re-sorted by `created_at`+`id` and destroyed the score ordering PRD §3.5 requires ("Candidates are returned highest score first"). All three volunteers share one `created_at`, so the tiebreak fell to random UUIDs — this was the flakiness source behind the 5/8 and 7/8 candidate tests. Now emits the ranked window directly via `ok_array`. |
| `workspace/implementation/routes_case.py` | `create_referral` | Carried a case-status gate (`RECOVERY_PLANNING`/`REFERRED`/`MONITORING`) that neither PRD §3.6 nor the scaffold endpoint declares. It rejected every referral raised from `ELIGIBILITY_REVIEW`, which is where `setup_casework_scenario` leaves the case. |
| `workspace/implementation/routes_shelter.py` | `close_shelter` | `OPEN`/`RESTRICTED` with `registered_client_count == 0` returned `ERR_INVALID_STATE`. PRD §2.4 states verbatim that closing with zero clients "moves it straight to `CLOSED`"; the strict §3.1 reading made `CLOSED` unreachable for an empty shelter, contradicting §2.4's "reaches its only terminal value, `CLOSED`, at the end of its life". Now closes directly and runs the recall cascade. |

### Fixes to `test_helpers/` (2)

- `fixtures.py` → `setup_open_shelter`: added `bundle["shelter_created"]`, the raw POST response. PRD §3.1 pins the *creation* snapshot (zero counts, 0.0 sufficiency); the fixture was re-reading, which recomputes those derived fields from children.
- `fixtures.py` → `setup_disbursed_assistance`: issues the card as `second_finance_officer_headers` instead of the approver. PRD §3.7 forbids the approver from issuing (`ERR_SOD_VIOLATION`).

### Fixes to `test_suite/` (test-side; PRD-faithfulness)

- **52 call sites** across `test_01`–`test_09`, `test_11`: `validate_success(api.<create>(...))` now passes `expected_status=201`. The runner's `validate_success` defaults to 200 and **0 of 211** sites passed 201 — this single mismatch caused 30 of the 54 failures. Reverted for `record_collection`, which PRD §4's 201 enumeration does not cover (stays 200).
- `test_01::test_new_shelter_operation_starts_pending_open`: asserts on `bundle["shelter_created"]`.
- `test_03` (4 tests): the pending deployment is now raised while the volunteer is ACTIVE/AVAILABLE, because PRD §2.5 gates the *request* as well as the approval; the credential is then allowed to lapse before approval. A recall frees the volunteer first so the rotation cap — not the credential gate — is the reported error (PRD §2.11 ranks credentialing 5th, caps 7th).
- `test_05::_cost_scenario`: approves twice. PRD §3.7 approval is a two-step operation; the fixture's single call left the request at `ELIGIBILITY_VERIFIED`, which PROVISIONAL cost correctly ignores (it counts only `APPROVED`/`CARD_ISSUED` money).
- `test_06` (2 tests): inserted the `ACCEPT` step before `COMPLETE` — PRD §3.6 says "`COMPLETE` moves an `ACCEPTED` referral to `COMPLETED`".
- `test_07` (5 tests): card issued by the second FinanceOfficer; corrected the pre-redemption pool balance to 225000 (PRD §2.8 — an APPROVED award is already committed).
- `test_08` (2 tests): the logical clock is set into the drive's window **before** the drive is scheduled. Automatic transitions run on every write, so a drive whose window already sat in the past was completed before a single unit could be collected.

### Sibling unasserted paths (test-side fixes dominated: ~55 test edits vs 3 implementation edits)

The implementation still owns these PRD rules that no test exercises — Step 8 should address them:

- **Check-out reunification SOD** (PRD §3.2): `reunification_verified_by_user_id` appears nowhere in `test_suite/`, so the `ERR_SOD_VIOLATION` release guard is unasserted.
- **`verify-eligibility` from `REOPENED`** is accepted by the implementation (a judgment call — PRD forces `eligibility_status=PENDING` on reopen and offers no other path back to `RECOVERY_PLANNING`); only `CLOSED → REOPENED` is asserted.
- **PASS/CONDITIONAL_PASS inspection failing its bed/accessibility precondition** → `ERR_INVALID_STATE`; no dedicated error id exists in PRD and no test covers it.
- **Pool restriction matrix** for `DONOR_RESTRICTED_DISASTER`/`_BLOOD`/`_LOCAL` is an implementation judgment (PRD never enumerates compatibility); only BLOOD-rejects-HOUSING and LOCAL-rejects-cross-region are asserted.
- **`restricted_fund_balance_cents` excluding UNRESTRICTED pools** (PRD §2.8) — the exclusion is unasserted.
- **Region `code` uniqueness** (PRD §3.1) is not enforced; PRD names no error id for a duplicate.
- **`case_closure_eligible_at`** is exposed on ClientCase but never asserted.

`results.1.json` … `results.8.json` are present in `workspace/implementation/` and all report `passed == total == 99`. They have not been deleted or cleaned up.

---

**Orchestrator verification of the hand-back:** all 8 `results.{1..8}.json` present in `workspace/implementation/` (≈31 KB each) and each independently parsed to `passed=99 total=99 failed=0` with an empty failure list. Post-sweep-write audit (the check that a green sweep is still valid): newest **implementation** source is `routes_shelter.py` at 11:36:40Z and newest **test** source is `test_suite/test_07_assistance_and_fund_pools.py` at 11:56:34Z — both strictly predate the results files at 12:00:31Z, so no source edit landed after the sweep. (The subagent's "newest .py 11:56:34" refers to the test-side file; my own earlier stat covered only `implementation/`, which is why the two figures differ — they are consistent.) The `__pycache__` entries at 11:40/11:57 are bytecode caches, not source. Step 7's exit is therefore a genuine 3-iteration, 0-deletion, 99/99 result.

Step 8 skip condition evaluated: 3 iterations with 0 deletions, 2 `test_helpers/` fixes, ~55 `test_suite/` fixes and 3 `implementation/` fixes — **not** the zero-change baseline, so Step 8 MUST run.

## Step 8: Finalize PRD — 2026-10-01T12:19:10.766Z

Subagent report (verbatim):

All 10 edits are applied and verified. Final state check confirms the file is complete (406 lines, identical tail to PRD.md).

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_3367_disaster_shelter_opening_volunteer_deployment_client_casework/workspace/PRD_FINALIZED.md`

**Size**: PRD.md 406 lines / 89,851 bytes → PRD_FINALIZED.md 406 lines / 91,266 bytes (**+1,415 bytes, +1.57%**; line count delta 0%). No `implementation/`, `test_suite/` or `test_helpers/` file was touched.

### Changes (10 edits, all in §2/§3 prose; no new sections)

1. **§2.4 — revise** — Deleted the false "registration at a `CONSOLIDATING` shelter returns it to `RESTRICTED`" mechanism; replaced with the implemented rule that the only exit from `CONSOLIDATING` is `CLOSED` and that registration/check-in are refused with `ERR_INVALID_STATE` 409 — `implementation/routes_shelter.py:235-239`, `implementation/routes_volunteer.py:311-313`, `implementation/routes_shelter.py:110-115`.
2. **§2.5 — revise** — Scoped the `PASS`/`CONDITIONAL_PASS` bed/accessibility precondition to inspections that would move the agreement to `APPROVED`, pinned `ERR_INVALID_STATE` 409 on failure (was "the agreement does not advance"), and noted an already-`APPROVED` site is re-inspected without re-testing — `implementation/routes_site.py:93-98`.
3. **§2.8 — insert** — Enumerated the pool restriction compatibility matrix (UNRESTRICTED / DISASTER accept all; BLOOD accepts none of the client assistance types; LOCAL requires pool region == client region) — `implementation/calc.py:316-326`, used at `implementation/routes_case.py:341`.
4. **§3.1 — revise** — Dropped region `code` uniqueness (and length) as an enforced requirement; duplicates are accepted — `implementation/routes_region.py:40-43`.
5. **§3.1 — revise** — Close from `OPEN`/`RESTRICTED` in `DEMOBILIZATION`: clients > 0 → `CONSOLIDATING`, clients == 0 → straight to `CLOSED` (was "only if … greater than zero", which made `CLOSED` unreachable for empty shelters); cascade now stated for both paths — `implementation/routes_shelter.py:95-109`, `123-142`.
6. **§3.2 — revise** — Check-out: supplying `reunification_verified_by_user_id` is what verifies the match (records verifier, sets `VERIFIED`, releases `REUNIFIED`, then `reunification_status = REUNIFIED`); ordinary path leaves `reunification_status` untouched; `ERR_SOD_VIOLATION` now covers both the previously recorded verifier and the incoming verifier equalling the actor — `implementation/routes_shelter.py:279-298`.
7. **§3.6 — insert** — `verify-eligibility` is also accepted from `REOPENED`: payload status and acting operator are recorded, case stays `REOPENED` — `implementation/routes_case.py:119-121`.
8. **§3.6 — revise** — Referral raise has no case-status precondition (may be raised against a case in any status) — `implementation/routes_case.py:172-201`.
9. **§3.6 — revise** — Renamed the closure instant to the field the resource actually exposes, `case_closure_eligible_at` (was `closure_eligible_at`) — `implementation/calc.py:355-376`, `implementation/routes_case.py:67,244`.
10. **§3.9 — revise** — Collection events are accepted against a `PLANNED` or `ACTIVE` drive (was "an active drive") — `implementation/routes_blood.py:65-68`.

### Per-edit pre-edit search log

1. **Subject**: shelter `CONSOLIDATING` posture admissibility/exit. **Paths enumerated/read**: `routes_shelter.py:86-142` (close), `:219-269` (register), `routes_volunteer.py:299-323` (check-in), `calc.py:149-205` (`shelter_derived`, `refresh_shelter`, `apply_posture_gate`), `auto.py` sweep (no posture writes). **Adjustment (c)**: avoided naming an error id for registration at `PENDING_OPEN`/`CLOSED` (impl uses `ERR_INVALID_STATE` there too but that is outside the flagged item), so the new sentence is scoped to `CONSOLIDATING` only.
2. **Subject**: inspection PASS/CONDITIONAL_PASS preconditions. **Paths enumerated**: `routes_site.py:71-117` (only inspection writer), `auto.py:46-57` (EXPIRED), `routes_shelter.py:55-83` (open-time consumers). **Adjustment**: scoped the precondition with "would move the agreement to `APPROVED`" rather than the original unconditional claim, because the impl skips the check on already-`APPROVED` sites.
3. **Subject**: pool restriction compatibility. **Paths enumerated**: `calc.py:264-273` (`restricted_fund_balance`), `:281-301` (`pool_remaining`/`refresh_pool`), `:316-326` (`restriction_compatible`), `routes_case.py:337-343` (sole callsite), `routes_region.py:215-246` (pool creation). **Adjustment**: stated LOCAL as "any assistance type but only when region matches" (impl ignores `assistance_type` for LOCAL) and described BLOOD negatively rather than as a type list.
4. **Subject**: region `code` validation. **Paths enumerated**: `routes_region.py:28-58` (`create_region` — only `strip()` non-empty), `:61-67` (read), `_region_children` filters. **Adjustment**: softened the same clause to "not checked for uniqueness or length" so the retained "two-letter" phrasing cannot be read as an enforced rule (the impl rejects nothing on length).
5. **Subject**: closing a shelter. **Paths enumerated**: `routes_shelter.py:86-120` (all posture branches), `:123-142` (`_cascade_close` — runs on both CLOSED paths), `calc.py:181-205` (posture gate never exits to CLOSED), `auto.py` (no posture writes), `routes_case.py`/`routes_region.py` (operation refresh only). **Adjustment**: re-scoped "That final step cascades" → "Reaching `CLOSED` by either path cascades", since the cascade also runs on the zero-client path.
6. **Subject**: check-out / reunification. **Paths enumerated**: `routes_shelter.py:272-302` (sole writer of `reunification_verified_by_user_id`, `reunification_status`, registration status), `calc.py:149-170` (`reunification_pending_count` counts PENDING/VERIFIED with no status filter), `routes_shelter.py:253-266` (registration initial values), `calc.py:329-335` (redemption window reads shelter posture, not reunification). **Adjustment**: added the "left as it was" clause so the ordinary path's unchanged `PENDING` value is pinned; kept "Both paths stamp…" intact since both branches do.
7. **Subject**: `verify-eligibility` admissible states. **Paths enumerated**: `routes_case.py:104-128` (all four branches), `:131-154` (recovery plan requires `VERIFIED`), `:45-71` (case creation), `calc.py:338-352` (entitlement uses `status == "REOPENED"`), `auto.py:140-157` (case sweep). **Adjustment**: none — worded as "admits a further verification too" rather than enumerating the full admissible-state set, since `INTAKE`/`CLOSED`/`REOPENED` were already covered and the else-branch `ERR_INVALID_STATE` is not part of the flagged item.
8. **Subject**: referral raise preconditions. **Paths enumerated**: `routes_case.py:160-201` (agency gate, duplicate gate, `case["status"] = "REFERRED"` unconditional), `:204-246` (resolve), `auto.py:143-150` (REFERRED→MONITORING), `calc.py:379-385`. **Adjustment**: phrased as "may be raised against a case in any status" (true for all statuses, including `CLOSED`, which the impl also flips to `REFERRED`), leaving the existing "the case moves to `REFERRED`" sentence to carry the transition.
9. **Subject**: the case closure-eligibility field name. **Paths enumerated**: `calc.py:355-376` (`case_closure_eligible_at` / `refresh_case_closure`), `routes_case.py:67,244`, `auto.py:148,152`, `routes_case.py:262`. **Adjustment**: none — the PRD was internally inconsistent (line 246 already used the correct name); only the stale name was fixed.
10. **Subject**: blood collection recording. **Paths enumerated**: `routes_blood.py:59-77` (sole collection writer; refuses only COMPLETED/CANCELLED), `:80-94` (cancel — PLANNED with collections → `ERR_INVALID_STATE`), `:17-56` (create), `auto.py:123-137` (PLANNED→ACTIVE→COMPLETED), `calc.py:95-119` (continuity reads usable_units). **Adjustment**: none — "PLANNED or ACTIVE" matches the impl's accepted set exactly.

### Examined and deliberately not edited (no PRD silence/mismatch)

- `deployment_candidates` re-sort fix: PRD §3.5 already pins "highest score first" with the `credential_refreshed_at`/`created_at` tie-breaks, and §2.3's created_at default is explicitly overridden by "unless a workflow states otherwise" — `implementation/routes_region.py:199-209` now matches; no PRD change needed.
- `shelter_created` fixture fix: §3.1 already pins the creation snapshot (zeros / 0.0) — `routes_shelter.py:34-52`.
- `setup_disbursed_assistance` fix: §3.7 already pins approver ≠ issuer — `routes_case.py:363-365`.
- 201-vs-200 test fix: §4's create enumeration matches the impl exactly, including `record_collection` returning 200 — `routes_blood.py:77`.
- test_03/05/06/07/08 fixes: all already determined by §2.5+§2.11, §3.7, §3.6, §2.8+§3.7 and §2.10 respectively.
- `restricted_fund_balance_cents` excluding UNRESTRICTED pools: §2.8's wording already matches `calc.py:264-273` verbatim.

---

**Orchestrator verification of the hand-back:** `PRD_FINALIZED.md` present at 406 lines / 91,266 B — exactly the reported size (+1,415 B over PRD.md, +1.57%). `diff` of the last 3 lines against `PRD.md` reports **no difference**, so the file is complete and not truncated. Spot-checked two of the ten edits in the rendered file: `case_closure_eligible_at` appears 3× (the renamed field), and line 276 carries the revised "recorded against a drive that is `PLANNED` or `ACTIVE`" wording. Critically, the mtime audit confirms Step 8 touched **only** `PRD_FINALIZED.md`: the newest implementation/test source is still `test_suite/test_07_assistance_and_fund_pools.py` at 11:56:34Z, which predates the Step 7 results files at 12:00:31Z — so the green sweep remains valid and was not invalidated by this step.

## Step 9: Complete PRD — 2026-10-01T12:30:37.564Z

Subagent report (verbatim):

All edits are in place. Final verification confirms the file is structurally identical to the source (same headings, same 116 table rows, matching tail), and no `implementation/` or test file was touched (all retain their pre-existing mtimes; only `PRD_COMPLETED.md` is new).

## Result

**Source vs output:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md`
- Lines: 406 → 408 (+2)
- Chars: 91,081 → 94,197 (**+3,116**, +3.4%)
- Headings identical; endpoint table (69 rows) and error catalogue untouched; tail byte-identical.

**Counts:** 22 change-sites — **5 mismatch-revisions**, **17 ambiguity-pins**.

### Mismatch-revisions (PRD described a different behavior)
- §2.4 — revise — mismatch — a shelter knocked into `RESTRICTED` by a `FAIL` cascade does not recover merely by being at ≥0.60; the gate is consulted only when `staffing_sufficiency` actually moves to a new value ≥0.60 — `calc.py:181-198`, `routes_shelter.py:145-155`
- §2.7 — revise — mismatch — `rotation_days_used_ytd` is a running total incremented only by end-of-rotation; a `RECALLED`/`CANCELLED` deployment adds nothing (PRD had said "sum … `ROTATION_ENDED` or `RECALLED`") — `routes_volunteer.py:190` (increment), `:198-219` (recall, no increment)
- §2.11 — revise — mismatch — validation priority reordered to header-presence → **role** → **body shape** → existence → …, with ordinals renumbered Third…Tenth (impl authorizes the role before parsing the body on every route) — `routes_*.py` (all handlers call `authenticate()` before `validate_body()`)
- §3.2 — revise — mismatch — `dormitory_bed_code` is never null; a registration that can get no bed is refused outright (PRD had described a null-bed registration) — `routes_shelter.py:251`
- §3.6 — revise — mismatch — the recovery-plan precondition now also admits `RECOVERY_PLANNING`, resolving a PRD-internal contradiction in favor of the revision rule stated two sentences later — `routes_case.py:142-149`

### Ambiguity-pins (PRD was silent)
- §2.1 — insert — ambiguity — `ERR_INVALID_REQUEST` 400 also covers out-of-vocabulary enum values and numeric values below a declared floor — `core.py:342-346`, `routes_region.py:227-228,278-279`
- §2.3 — insert — ambiguity — `limit`/`offset` are never validated: out-of-range clamps, negative offset reads as 0, non-numeric falls back to default — `core.py:253-267`
- §2.4 — insert — ambiguity — the close cascade also cancels non-terminal shifts of the deployments it recalls — `routes_shelter.py:138-141`
- §2.5 — insert — ambiguity — only an already-`APPROVED` site is exempt from the bed/accessibility preconditions; a `SUSPENDED` site must satisfy them again — `routes_site.py:93-98`
- §2.7 — insert — ambiguity — shift interval ending at/before its start → `ERR_INVALID_REQUEST` 400 — `routes_volunteer.py:263-265`
- §2.7 — insert — ambiguity — blood-drive window ending at/before its start → `ERR_INVALID_REQUEST` 400 — `routes_blood.py:33-35`
- §2.8 — insert — ambiguity — a `DONOR_RESTRICTED_LOCAL` pool declaring no `region_id` is incompatible with every client — `calc.py:325`
- §2.9 — insert — ambiguity — a newly created resource carries `version` 1 — `core.py:153-160`
- §2.12 — insert — ambiguity — the version comparison precedes the remaining state/reference/value checks on all three guarded writes — `routes_case.py:140`, `routes_site.py:87`, `routes_region.py:273`
- §3.1 — insert — ambiguity — failing `inspection_result`, phase, or staffing on open → `ERR_INVALID_STATE` 409 — `routes_shelter.py:67-78`
- §3.3 — insert — ambiguity — negative `meals_planned`/`meals_served`/`unit_cost_cents` → `ERR_INVALID_REQUEST` 400 — `routes_shelter.py:320-322`
- §3.3 — insert — ambiguity — the per-client health increment lands on the most recent registration at that shelter; with none, only the shelter total moves — `routes_shelter.py:351-357`
- §3.3 — insert — ambiguity — `reporting_mode` selects the variant on its own (only exact `FINAL` yields FINAL; anything else, including omission, yields PROVISIONAL, `CLOSED` included) — `routes_shelter.py:151-154`
- §3.4 — insert — ambiguity — `rotation_days` below 1 → `ERR_INVALID_REQUEST` 400 — `routes_volunteer.py:117-118`
- §3.4 — insert — ambiguity — a shift against a terminal deployment → `ERR_INVALID_STATE` 409, and the shift's shelter is not cross-checked against the deployment's shelter — `routes_volunteer.py:259-267`
- §3.5 — insert — ambiguity — `role_code` is required on candidate ranking; omission → `ERR_INVALID_REQUEST` 400 — `routes_region.py:191-193`
- §3.6 — insert — ambiguity — `duplication_check_result` is `PARTIAL_OVERLAP` iff the case already holds a non-cancelled referral of the same `assistance_type`, else `CLEAR` — `routes_case.py:187-195`
- §3.9 — insert — ambiguity — any `continuity_mode` other than `FORWARD_LOOKING` yields `TRAILING` — `routes_region.py:66`
- §4 — insert — ambiguity — recording a blood collection returns 200 (updates the drive in place), not 201 — `routes_blood.py:77`

### Dead-code check (PRD-required checks vs. live callsites)

Grepped callsites for every PRD-required predicate: `restriction_compatible`, `assistance_award`, `duplication_offset`, `redemption_window_days`, `client_entitlement`/`refresh_case_entitlement`, `case_closure_eligible_at`/`refresh_case_closure`, `case_status_after_referrals`, `travel_cost`, `priority_score`, `usable_units`, `feeding_line_cost`, `operational_cost`, `lead_days`, `apply_posture_gate`, `blood_continuity`, `restricted_fund_balance`, `pool_remaining`, `refresh_pool`, `refresh_operation`, `refresh_shelter`. **All have at least one live call path** — no PRD-required check is uncalled.

**Two checks are wired but unreachable** (the inverse of the hazard — the callsite exists, the condition cannot be produced). Both survive a green sweep because no test asserts them:

1. **`ERR_SOD_VIOLATION` on the *previously recorded* reunification verifier is dead.** `routes_shelter.py:279-285` refuses when `registration["reunification_verified_by_user_id"] == X-User-ID`, but that field is only ever written at `:290`, inside the same handler, immediately before the status becomes `REUNIFIED`/`CHECKED_OUT`. The `status != "REGISTERED"` terminal check at `:279-280` therefore always fires first, so the recorded-verifier half of PRD §3.2's SOD rule can never trigger. The *supplied*-verifier half (`:286-289`) is live and reachable. I left the PRD sentence in place rather than deleting a check the code genuinely contains, and flag it here as instructed.
2. **`ERR_INVALID_STATE` on `duplication_check_result == "DUPLICATE_BLOCKED"` is dead.** `routes_case.py:218` guards `ACCEPT`, but the only writer (`:195`) produces `CLEAR` or `PARTIAL_OVERLAP`, never `DUPLICATE_BLOCKED`. The guard cannot fire; `ERR_DUPLICATION_BLOCKED` in the §5 catalogue is likewise unreachable (the live duplicate rule uses it only as a *raise-time* refusal on the referral-create path, which is fine).

Other unused symbols (`calc.refresh_drive`, `calc.TERMINAL_REGISTRATION`, `core.plus_minutes_iso`, `core.now_dt`, `errors.fail`) are internal helpers with no PRD-required behavior behind them — the behavior they would wrap is implemented inline and live (e.g. `usable_units` is applied directly at `routes_blood.py:75`), so none represents a missing PRD check.

---

**Orchestrator verification of the hand-back:** `PRD_COMPLETED.md` present at **408 lines / 94,388 B** (the subagent reported 91,081→94,197 chars; my byte count is 187 higher, a measurement-method difference, and the +2 line delta and +3.4% growth match). Structural checks pass: heading count identical to `PRD_FINALIZED.md`, all **116** table rows preserved (69 endpoint rows + 43 error rows + headers), and the last 3 lines `diff` clean against the source. `find -newermt '2026-10-01T12:00:31'` over `implementation/`, `test_suite/` and `test_helpers/` returns **nothing** — Step 9 wrote only `PRD_COMPLETED.md`, so the Step 7 green sweep remains valid.

**Independent adjudication of the two dead-code findings** (checked against source rather than taken on trust):
1. Confirmed by reading `routes_shelter.py:272-302` and grepping every writer of `reunification_verified_by_user_id` — the only assignment is line 290, and line 292-293 immediately drives `status` to `REUNIFIED`, so line 279's `status != "REGISTERED"` terminal check always shadows lines 283-285. The guard is genuinely unreachable.
2. Same shape at `routes_case.py:195/218`.

**Verdict — no action taken, and none needed.** Both are *defensive redundancy shadowed by a rule the PRD itself states*, not PRD-vs-implementation mismatches: PRD_COMPLETED line 194 already ends "The three departure states — `CHECKED_OUT`, `TRANSFERRED` and `REUNIFIED` — are terminal, so a checked-out registration cannot be checked out again", and the duplicate-referral rule is documented as the live raise-time refusal. A fresh implementer reading PRD_COMPLETED would produce observationally equivalent behavior whether or not they write the redundant guards. Editing `implementation/` to make the guards reachable would in fact *violate* §2.11's validation-priority order (state admissibility is 4th, SOD is 7th) and would invalidate the green sweep — so the correct disposition is to leave the code and record the finding here.

## Pipeline complete — 2026-10-01T12:31:15.615Z

All nine steps finished. Final output contract verified by the orchestrator:

```
tasks/task_3367_disaster_shelter_opening_volunteer_deployment_client_casework/
├── SCAFFOLD.yaml                          (118,115 B — 15 entities, 11 state machines, 16 calcs, 69 endpoints, 43 errors, 8 roles)
├── SCAFFOLD_DIFFICULTY_DESIGN.yaml        (148,557 B — 9 rule groups × 3 = 27 instances)
├── SCAFFOLD_CORNER_DESIGN.yaml            (165,650 B — 9 sections = 47 instances, 42 testable)
├── worklog.md
├── test_helpers/                          (9 files, 1,843 lines)
├── test_suite/                            (12 files, 2,957 lines — 99 tests)
└── workspace/
    ├── INSTRUCTION.md                     (1,424 B)
    ├── PRD.md                             (406 lines / 89,851 B)
    ├── PRD_FINALIZED.md                   (406 lines / 91,266 B — Step 8, 10 edits)
    ├── PRD_COMPLETED.md                   (408 lines / 94,388 B — Step 9, 22 change-sites)
    └── implementation/                    (12 modules + start.sh + requirements.txt, 2,859 lines)
        └── results.{1..8}.json            (all 8 rounds passed == total == 99)
```

Final sweep evidence re-verified after Steps 8 and 9: all 8 `results.*.json` present and each parses to `passed=99 total=99`; `find -newermt '2026-10-01T12:00:31'` over `implementation/`, `test_suite/` and `test_helpers/` returns nothing, confirming the green sweep was not invalidated by the two documentation steps.

Pipeline totals: 3 Step 7 iterations (45/99 → 96/99 → 99/99), 0 tests deleted, 3 `implementation/` fixes, 2 `test_helpers/` fixes, ~55 `test_suite/` fixes, 10 Step 8 PRD edits, 22 Step 9 PRD change-sites.
