# Worklog — task_3486_program_evaluation_study_design_federal_reporting

## Step 1: Create task directory — 2026-10-02T15:33:40.303Z

Used the pre-allocated directory `tasks/task_3486_program_evaluation_study_design_federal_reporting/` (with `workspace/` inside) exactly as instructed; no new index computed, no other task_* directory created. Difficulty instruction: "Generate task much harder than expert level!" (passed to scaffold-generator only).

## Step 2: Generate scaffold — 2026-10-02T15:33:40.303Z

All three artifacts are complete, lint-clean, and replay-verified. Exit summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3486_program_evaluation_study_design_federal_reporting/`):
- `SCAFFOLD.yaml` — 1782 lines — **PARSE OK**
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1910 lines — **PARSE OK** (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3051 lines — **PARSE OK** (single key `scaffold_corner_design`)

**Counts**: 12 entities, 12 state machines (5 cyclic: DesignPlan revision loop, IRBProtocol modifications/expiry loops, Wave suspend-resume, FindingsReport revision cycle, RestrictedUseFile reject-resubmit), 7 calculations, 10 validation priority groups, 57 endpoints, 39 error codes, 9 roles (Participant is `entity_backed:Participant`, others opaque), 1 OCC concurrency rule (`design-plan-create-stale-study` on Study.version). Difficulty design: **18 instances** (2 per each of the 9 rules). Corner design: **58 instances** — 51 active + 7 `excluded_because` stubs; per section: entities 7, state_machines 8, calculations 8 (5 stubs), validations 5 (1 stub), endpoints 2, errors 12, rbac 9, cross_cutting_layers 6 (1 stub), consistency_model 1.

**api_prefix**: `/evaluation`. Endpoints (method + path): POST/GET/terminate/closeout under `/evaluation/contracts…`; studies under `/evaluation/contracts/{id}/studies` + `/evaluation/studies/{studyId}`; design-plans (POST/GET list + submit/agency-decision/revise actions); irb-protocols (POST/GET list + submit/decision/continuing-review); sites (POST/GET list + outreach/sign-mou/activate/withdraw); participants (POST under site, GET filtered list, GET one, consent/randomize/withdraw); waves (POST/GET under study, GET `/evaluation/waves` filtered, GET one, open/close/link); records (POST/GET under wave, GET under participant); analysis-plans (POST/GET + register/amend); reports (POST/GET + submit/review/agency-decision/publish); restricted-use-files (POST/GET + submit-review/review-decision); dissemination-activities (POST/GET + complete); test-driving `POST /_clock/set_current_utc` (unprefixed, default 2026-09-01T00:00:00Z pinned in its description).

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (947 calls scanned; zero violations.)

**Constants**: 18 pinned exactly once in a top-level `constants:` block (Z_ALPHA_CRIT 1.96, Z_POWER_CRIT 0.84, QED_VARIANCE_INFLATION 1.44, YIELD_PROSPECTED 0.10, YIELD_CONTACTED 0.35, K_ANONYMITY_MIN 5, MAX_DISCLOSURE_RISK 0.20, MAX_TOTAL_BURDEN_MINUTES 480, three MODE_FACTORs, SITE_VISIT_MIN_GAP_DAYS 7, IRB_MAX_APPROVAL_DAYS 365, PEER_REVIEW_DAYS 45, AGENCY_COMMENT_DAYS 30, REVISION_DAYS 60, PUBLICATION_DAYS 90, CLOCK_DEFAULT_UTC). No unpinned constants; every formula-derived assert literal was computed by code (RCT 107/214, QED 155/310, icc=0 74/148, pipeline 270/210/165/215, burden 157 vs rejected 158, cap-exact 480, max_risk 0.20/mean 0.0426, deadlines 2026-12-14, 2027-01-13, 2027-02-12).

**Notes for downstream**: (1) endpoint count 57 deliberately exceeds the Expert band — the user asked for much-harder-than-expert; Step 6 should pre-constrain generation per the known >40-endpoint risk (per-domain modules, one file per message). (2) Self-audit removed one dead error (ERR_RECORDS_UNRESOLVED — unreachable since wave close auto-validates). (3) Nested sub-resource GETs use literal `{id}` path params to satisfy lint check (f). (4) Audits run: placeholder closure (zero unbound), name uniqueness across both design files, grounds resolvability, error-id cross-reference, and a gate-replay script over all 69 active recipes (two flags confirmed as intentional negative probes, not bugs).

Orchestrator verification: all three files exist with stated line counts, all parse via yaml.safe_load, SCAFFOLD.yaml contains neither design key, domain_name is `program-evaluation-federal-reporting` with api_prefix `/evaluation` — matches this task (no foreign-domain contamination).

## Step 3: Copy shared files — 2026-10-02T16:54:41.273Z

Copied `./INSTRUCTION.md` → `tasks/task_3486_program_evaluation_study_design_federal_reporting/workspace/INSTRUCTION.md` (1424 bytes, overwrote a stale Aug-15 copy).

## Step 4: Generate PRD — 2026-10-02T16:54:41.273Z

All verification passes are green. The PRD is complete.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3486_program_evaluation_study_design_federal_reporting/workspace/PRD.md` — 346 lines.

**Structure** (section list):
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (9 roles with identity translations; Participant entity-backed, others opaque), 2.2 API Response Structure (byte-identical verbatim block — diff-verified), 2.3 Pagination, 2.4 Logical Clock & Temporal Semantics, 2.5 Common Resource Properties, 2.6 Hierarchical Integrity/Cascades/Quarantine, 2.7 Nested Resource Retrieval, 2.8 Request Validation Order (10-stage ordered pipeline), 2.9 OCC, 2.10 Numeric Precision & Rounding
- §3 Business Logic (9 subsections): 3.1 Contract Award & Funds Ledger, 3.2 Study Setup & Design Planning, 3.3 IRB Protocol & Human-Subjects Compliance, 3.4 Site Recruitment & Feasibility Projections, 3.5 Participant Consent/Randomization/Withdrawal, 3.6 Waves & Response Records, 3.7 Analysis Preregistration & Findings Reports, 3.8 Publication/Payment/Dissemination, 3.9 Restricted-Use Files & Disclosure Review
- §4 Endpoint table (57 rows, 4 columns), §5 Error catalogue (39 rows, 2 columns)

**Constraint confirmations**:
- All 18 constants present with exact scaffold values (grep-verified: 1.96, 0.84, 1.44, 0.10, 0.35, 5, 0.20, 480, 1.0, 1.25, 0.5, 7, 365, 45, 30, 60, 90, 2026-09-01T00:00:00Z), each named in backticks next to its value.
- All 39 error_ids appear verbatim in §2/§3 prose at the rule that produces them (not only in the §5 table — verified against pre-§5 body).
- Clock endpoint described at exactly `POST /_clock/set_current_utc`, unprefixed, in §2.4 and the §4 table; all other 56 endpoints carry the `/evaluation` prefix (57 table rows counted).
- Contract 1: 96 required identifiers (entity fields + endpoint inputs + query params + envelope fields), 0 missing. Contract 3: 652 §3 backtick tokens, 0 path/method violations. All 44 state values and all enum literals present.

**Deliberate compressions/scattering** (nothing omitted, noted per instructions):
- §2.8 renders the scaffold's 10 validation priorities as one ordered pipeline naming every error family; per-trigger detail prose is then repeated at each workflow site in §3 (redundant reinforcement).
- Scaffold self-tension retained faithfully: randomize's state-machine precondition (ERR_PARTICIPANT_INVALID_STATE) plus the catalog's association of ERR_PARTICIPANT_NOT_CONSENTED with the randomize consent requirement are both stated in §3.5 without reconciling them.
- Scaffold worked examples (power 107/214 vs 155/310; pipeline 270; burden 157-vs-158; risk 0.20/0.0426) are kept as "For illustration" prose to pin the calculation reconstructions.

Orchestrator spot-check: 346 lines confirmed; `/_clock/set_current_utc` present ×2 with zero `evaluation/_clock` occurrences; sampled constants 1.96/0.84/1.44/0.10/0.35/480/365/2026-09-01 all present; 39 unique `ERR_*` tokens in PRD.

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T17:36:00.000Z

Orchestrator pre-measurement of design indices (verified against YAML, not the Step 2 summary): difficulty 18 active / 0 stub across 9 rules ×2; corner 51 active / 7 stub across 9 sections (entities 7, state_machines 8, calculations 3a+5s, validations 4a+1s, endpoints 2, errors 12, rbac 9, cross_cutting_layers 5a+1s, consistency_model 1); grand total 69 active. Step 2 subagent's counts were accurate. Corner active (51) < 100 → no per-section fan-out; Step 5 split as 5a (helpers, frozen) → 5b (tests) per oversized-step protocol.

Stage 1 (helpers only) for task_3486 is complete. Summary for the worklog:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3486_program_evaluation_study_design_federal_reporting/test_helpers/`):
- `types.py` — 339 lines: 18 status/type enums + 12 entity TypedDicts (all entities carry id/created_at/updated_at/version; no common_fields:false exemptions exist in this scaffold)
- `api_client.py` — 198 lines: ApiClient(GenericApiClient), 57 methods (56 business endpoints + clock)
- `api_errors.py` — 96 lines: ApiErrorId enum (39 errors) + HTTP_STATUS_CODES + set_error_http_status_map registration
- `assertions.py` — 244 lines: 12 assert_{entity} + 4 invariant checkers + strict validate_success
- `factories.py` — 204 lines: 22 payload factories, PRD-exact field names
- `constants.py` — 68 lines: PRD constants only
- `test_users.py` — 70 lines: TEST_USERS (9 roles) + 9 make_<role>_headers builders
- `fixtures.py` — 500 lines: 25 composite fixtures across 11 tiers
- `__init__.py` — 46 lines: barrel (framework generics + PRD-specific)

**Verification results:**
- `python3 -m py_compile test_helpers/*.py` → PY_COMPILE OK
- Import-shadowing check: `importlib.import_module('test_helpers.api_client')` → `<class 'module'>`; singleton identity confirmed (`test_helpers.api_client.api_client is api_client` across both import styles)
- Clock endpoint unprefixed: `set_clock` sends to bare `/_clock/set_current_utc`; all 56 business methods use `/evaluation` prefix (grep-verified: 56 `f"{PREFIX}/` call sites)
- constants.py grep-verified against PRD.md: 1.96, 0.84, 1.44, 0.10, 0.35, k=5, 0.20, 480, 1.0/1.25/0.5, 7, 365, 45, 30, 60, 90, clock default 2026-09-01T00:00:00Z, worked-example results 107/214/155/310 and 0.0426 — every value found in PRD text
- validate_success: package-level `test_helpers.validate_success` is the strict version from assertions.py with REQUIRED `expected_status` (framework's default-200 variant deliberately not re-exported); `validate_error_is_one_of` re-exported from framework
- No test_suite/ or test_*.py created (Stage 2's job); `__pycache__` removed after import checks

**Frozen helper surface for Stage 2:**

Fixtures (all return dict ctx bags or entity dicts; ctx keys documented per fixture):
- `set_clock(to_iso8601)` — unprefixed clock set
- `setup_contract(**overrides)`, `setup_contract_with_study(contract_overrides=None, **study_overrides)`
- `get_study/get_contract/get_participant/get_wave(id)` — fresh reads (get_study is the OCC-version source)
- `add_site(study_id, name, max_participants, target_state)` — PROSPECTED/CONTACTED/RECRUITED/DECLINED
- `setup_study_with_sites(site_specs=((cap, state), ...))` — default ((250,"RECRUITED"),)
- `create_design_plan(study_id, expected_study_version=None, **overrides)` — auto-fetches OCC version
- `setup_study_with_locked_plan(site_specs=..., plan_overrides=...)` — plan auto-LOCKED, study RECRUITMENT
- `approve_irb_protocol(study_id, with_modifications_cycle=False, approval_start=..., approval_end=..., estimated_burden_minutes=...)` — modifications cycle yields consent_form_version 2
- `setup_active_site_study(site_capacity=250, site_specs=None, activate_index=0, with_modifications_cycle=False, irb_overrides=None)` — LOCKED plan + APPROVED IRB (2026-09-01..2027-09-01) + ACTIVE site
- `add_participant(site_id, external_ref, consent=False, consent_form_version=None, randomize=False)` — consent threads `make_participant_headers(p["id"])`
- `add_consented_participants(site_id, count, consent_form_version=1, ref_prefix="P")`
- `create_wave(study_id, wave_type, site_id=None, open_at, close_at)`, `open_wave(wave_id, clock=...)`, `setup_open_wave(ctx, wave_type, site_id, ...)`
- `add_record(wave_id, participant_id, instrument_minutes=45, payload_ref=...)`
- `setup_registered_analysis_plan(ctx, primary_outcomes=None, secondary_outcomes=None)` — call before any wave closes
- `setup_study_in_analysis(**kwargs)` → ctx + analysis_plan + wave
- `create_report(study_id, **overrides)`, `setup_study_with_draft_report`, `setup_submitted_report`, `setup_peer_reviewed_report`, `setup_report_in_revision` (revision_due = now+60d), `setup_accepted_report` (publication_due = +90d), `setup_published_report` (study DISSEMINATION, contract re-read)
- `setup_completed_study(**kwargs)` → + activity COMPLETED, study COMPLETED
- `create_restricted_use_file(study_id, **overrides)`, `setup_ruf_in_review(ruf_overrides=None)`, `setup_released_ruf()`
- Worked-example scenarios (literals match PRD): `setup_pipeline_projection_scenario()` (60+300+300 → committed 60 / pipeline 270 / ADEQUATE with DRAFT 214 plan), `setup_burden_rounding_scenario()` (ACTIVE site, consented P1, OPEN SITE_VISIT + SURVEY waves, clock 2026-10-15; 45/45/45 → 157), `setup_participant_at_burden_cap()` (one SITE_VISIT 384 → billed exactly 480), `setup_worked_disclosure_risk_scenario()` (cells [5,4,12,30] → suppressed 1, max 0.20, mean 0.0426)

Role-header builders: `make_agency_officer_headers / make_principal_investigator_headers / make_study_director_headers / make_data_manager_headers / make_irb_reviewer_headers / make_peer_reviewer_headers / make_participant_headers / make_external_researcher_headers / make_platform_admin_headers` (all take user_id; SOD tests pass a colliding id across roles) + `TEST_USERS` dict keys: agency_officer_headers (ao-1), principal_investigator_headers (pi-1), study_director_headers (sd-1), data_manager_headers (dm-1), irb_reviewer_headers (irb-1), peer_reviewer_headers (peer-1), participant_headers (fallback only), external_researcher_headers (er-1), platform_admin_headers (admin-1).

Assertion helpers: `validate_success(response, expected_status)` (explicit status — 201 for creates), `validate_error` (auto HTTP cross-check via registered map), `validate_error_is_one_of`, `validate_paginated`, `get_success_data`, `assert_contract / assert_study / assert_design_plan / assert_irb_protocol / assert_site / assert_participant / assert_wave / assert_record / assert_analysis_plan / assert_report / assert_restricted_use_file / assert_dissemination_activity`, invariants: `assert_contract_funds_invariant`, `assert_enrollment_reconciliation(study, sites)`, `assert_burden_within_cap(participant, cap)`, `assert_risk_scores_consistent(ruf)`.

Notes for Stage 2: fixtures use small-capacity multi-site specs for boundary setups (e.g., capacity-exact needs `setup_active_site_study(site_specs=((2,"RECRUITED"),(300,"CONTACTED"),(300,"CONTACTED"),(300,"CONTACTED")))` so pipeline 317 ≥ 214 clears the submit gate); IRB expiry is reachable by `set_clock` past `IRB_APPROVAL_END`; all default fixture dates are ≥ the 2026-09-01 clock default.

Orchestrator verification: 9 files present, `py_compile` OK, 56 prefixed call sites + unprefixed clock call confirmed in api_client.py, strict `validate_success(response, expected_status)` confirmed in assertions.py.

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T17:55:00.000Z

Stage 2 complete. All work is in `/home/ubuntu/github/CodingPRD/tasks/task_3486_program_evaluation_study_design_federal_reporting/test_suite/`.

**Test files written** (14 test files + conftest.py, 2489 total lines):
- `conftest.py` — 59 lines, session `api` fixture + 9 role-header fixtures
- `test_difficulty_calcs.py` — 148 lines, 4 tests (queue A)
- `test_difficulty_state_cascades.py` — 308 lines, 6 tests (queue A)
- `test_difficulty_guards.py` — 167 lines, 4 tests (queue A)
- `test_difficulty_boundaries.py` — 208 lines, 4 tests (queue A)
- `test_corner_entities.py` — 167 lines, 7 tests
- `test_corner_state_machines.py` — 257 lines, 8 tests
- `test_corner_calculations.py` — 149 lines, 3 tests
- `test_corner_validations.py` — 132 lines, 4 tests
- `test_corner_endpoints.py` — 81 lines, 2 tests
- `test_corner_errors_a.py` / `test_corner_errors_b.py` — 177/151 lines, 6+6 tests
- `test_corner_rbac_a.py` / `test_corner_rbac_b.py` — 128/154 lines, 5+4 tests
- `test_corner_cross_cutting.py` — 175 lines, 5 tests
- `test_corner_consistency.py` — 28 lines, 1 test

**Skipped instances: none.** All 69 active instances (18 difficulty + 51 corner) passed the PRD-first two-condition filter and were translated. The 7 `excluded_because` stubs (5 calculations + priority_ordering + cascades) were verified against queue A and correctly not emitted.

**Recipe/PRD literal divergences re-derived (2):**
1. `Corner/cross_cutting_layers/entity_version_increments_on_mutation` — recipe asserts "updated_at advanced" on terminate, but the recipe never advances the logical clock, so a refreshed `updated_at` is not observably different; a PRD-faithful impl could fail that sub-assertion. Test asserts version 1→2 and TERMINATED only (both pinned by PRD §2.5).
2. Deadline fields (`revision_deadline_boundary_pass_and_miss`, `publication_deadline_boundary_pass_and_miss`) — recipes assert exact timestamp strings; PRD pins the arithmetic (+60d → 2026-12-14, +60d → 2027-02-12, +90d → 2027-01-13) but not the serialization (`Z` vs `.000Z`). Tests parse ISO8601 and compare datetimes; values match the recipe literals exactly.

**Inexpressible-with-frozen-helpers setups: none.** One nuance: `wave_suspend_resume_cycle_on_irb_expiry` — the frozen `open_wave(wave_id, clock=...)` always re-sets the clock; the recipe's final reopen must run at the already-set clock 2027-09-01 (inside both the new IRB window and the wave window), so the test calls `api.open_wave` directly rather than via the helper (which would have moved the clock backwards). No helper patch needed.

**pytest --collect-only:** 69 tests collected, 0 errors.

**AST tag audit (real `ast` parse + `yaml.safe_load` of both indices):** index active instances 69, emitted tags 69; missing `[]`, extra `[]`, malformed/duplicate/dual tags `[]`, untagged `[]`, stub instances wrongly emitted `[]`. Missing set reconciles exactly with the (empty) skip list.

**Citation verification:** 32 distinctive ≥8-word substrings from the test docstrings grep-verified verbatim against `workspace/PRD.md` — all present, including the em-dash and backtick-exact forms. One abbreviated (ellipsis) quote found during the sweep was replaced with the full PRD §2.8 state-stage sentence and re-verified.

Orchestrator independent re-audit: AST tag walk + yaml.safe_load of both indices → expected 69, emitted 69, unique 69, missing [], extra [], dupes 0; `pytest --collect-only` → 69 collected, 0 errors.

## Step 6: Generate implementation — 2026-10-02T18:20:00.000Z

All checks complete. The implementation is finished and verified. Final summary:

### File tree (all under `workspace/implementation/`)
```
start.sh                  9   (PORT env, 0.0.0.0, exec foreground, guarded pip install)
requirements.txt          1   (flask==3.1.3, already present on host)
app.py                   67   (factory, error handlers, blueprint registration)
store.py                 26   (12 in-memory dicts; empty at boot, zero seeding)
clock.py                 58   (logical clock, default 2026-09-01T00:00:00Z)
errors.py                56   (ApiError + all 39 catalog error_ids with HTTP statuses)
util.py                 101   (envelope meta/response_type/data, pagination, touch/version)
validation.py           122   (stage 1-4: auth headers, role lists, body schema)
calc.py                  81   (all 7 calculation rules, Decimal-pinned)
serialize.py            209   (per-entity out serializers)
services.py             299   (recomputes, IRB gate, all cascades, completion/expiry)
contracts.py            103   studies.py 67    design_plans.py 179
irb.py                  170   sites.py 140    participants.py 157
waves.py                188   records.py 82   analysis_plans.py 108
reports.py              195   restricted_use_files.py 130   dissemination.py 79
clock_route.py           21   (UNPREFIXED POST /_clock/set_current_utc)
```
`python3 -m py_compile` passes for every file (24 files, 2648 lines total).

### Smoke-test transcript
- **Shallow** (port 55345, PID 2518463, killed): missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; wrong role → 403 `ERR_UNAUTHORIZED_ROLE`; contract 201; study 201 (DESIGN/UNASSESSED/v1); OCC mismatch → 412 `ERR_STALE_VERSION`; OCC match → 201 with `n_per_arm=107, required_total_n=214` (PRD worked example); study bumped to v2/UNDERPOWERED; `POST /_clock/set_current_utc` (PlatformAdmin) → 200 echoes `current_utc`; clock with AgencyOfficer → 403; undeclared field → 400; list envelope has `limit/offset/total_count/has_more` in meta.
- **Deep** (port 48791→51327, all PIDs killed): 49 PASS, 0 FAIL — full lifecycle contract→study→sites→plan(submit 422 `ERR_INSUFFICIENT_POWER` then pass)→approve→sign-mou auto-LOCK→IRB→activate→consent→randomize→register→amend-frozen 409→wave open/close/link→record billed 45→report submit/review/accept/publish (ledger 400000/600000)→RUF risk (suppressed 1, max 0.2, mean 0.0426 — PRD example exact)→RELEASED→ExternalResearcher filtered list→activity complete→study COMPLETED cascade→closeout (forfeit 600000). Plus IRB expiry at exactly `approval_end` (half-open): protocol EXPIRED, wave SUSPENDED, record QUARANTINED, quarantine count 1, burden drops to 0, consent → `ERR_IRB_EXPIRED`; terminate cascade: study TERMINATED, participant WITHDRAWN/CONTRACT_TERMINATED, wave CANCELLED.
- **Edge** (port 51521, PID killed): 29 PASS, 0 FAIL — OCC staleness after create; supersede revision_number=2; IRB window >365d → 400; overlap → 409; touching endpoints allowed; continuing-review shorten → 400 / extend ok; Participant self-read 200 / other-read 403 / list 403 / consent-wrong-self 403; stale consent version → 409; deterministic alternation T,C; wave open at exactly `open_at` ok, before → 409; unreported primary → 422; `revision_due`=+60d exact; resubmit 1s late → 422, at exactly due → 200; `publication_due`=+90d exact; publish 1s late → 422, at exactly due → 200; double publish → 409; closeout blocked → 409 `ERR_STUDIES_NOT_COMPLETED`; overdraw publish → 402 `ERR_INSUFFICIENT_CONTRACT_FUNDS`.
- Error-catalog cross-check: every `raise_err` id exists in `ERROR_STATUS` (no latent 500s); all guard functions have call sites.

### Interpretations chosen (PRD admitted multiple readings)
1. `version` starts at 1 on create; a resource's version bumps **at most once per request** regardless of how many transitions/cascades touch it in that request (so agency-approve-with-immediate-lock is +1, design-plan create is exactly +1 on the study).
2. `created_at`/`updated_at`/`api_request_timestamp` use the **logical clock** at millisecond precision (`.000Z`, per §2.5/§2.2 examples); all other datetime fields emit second-precision `...Z` (matches CLOCK_DEFAULT_UTC format); clock endpoint echoes the request's `to_iso8601` string verbatim as `current_utc`.
3. Participant ownership check compares `X-User-ID` to the **path** participantId at the authorization stage (stage 2), so a mismatched Participant-role caller gets 403 even for nonexistent ids.
4. Error precedence follows the §2.8 pipeline stages wherever narrative order conflicts (see tensions below): record create checks wave-OPEN (6) → burden cap (7) → participant eligibility (9).
5. `ERR_ANALYSIS_PLAN_NOT_REGISTERED` is not slotted in §2.8's stage list; placed at the state-validity stage (409 family) right after the report state check, before the revision deadline (8) and coverage (9).
6. Body-supplied FK references (`participant_id` on record create; `site_id` on SITE_VISIT wave create): nonexistent or cross-parent → `ERR_NOT_FOUND`, checked after body schema and before state checks.
7. Record create does **not** require the participant to belong to the wave's study or site (PRD states only the consent-status requirement; no guard invented).
8. IRB coverage textures: no protocol ever APPROVED → `ERR_NO_APPROVED_IRB`; an APPROVED/EXPIRED protocol exists but none covers now (passed **or** not-yet-started window) → `ERR_IRB_EXPIRED`.
9. IRB expiry is evaluated **only** on `POST /_clock/set_current_utc` (the stated trigger); a protocol approved with an already-past window stays APPROVED until the next clock set.
10. `consent_form_version` bump: internal `_mods_pending` flag set on a MODIFICATIONS_REQUIRED decision, consumed (+1) by the next APPROVED decision; expiry/resubmission without modifications does not bump.
11. Site-visit gap measured as `later_start − earlier_end` between non-overlapping half-open windows; conflict iff gap < 7 days; exactly 7 days passes; only non-CANCELLED SITE_VISIT waves at the same site count.
12. Contract closeout with zero studies is allowed (vacuous truth of "every study COMPLETED").
13. Study completion (DISSEMINATION→COMPLETED) is evaluated on **both** report publish and activity complete — "the moment both exit conditions hold".
14. Report-submit coverage uses the **latest-created PREREGISTERED** analysis plan of the study; if none is PREREGISTERED → `ERR_ANALYSIS_PLAN_NOT_REGISTERED`.
15. RUF/dissemination/IRB-protocol creation gates: study must not be TERMINATED or COMPLETED (generic child rule); RUF/dissemination additionally require a PUBLISHED report. IRB-protocol creation has no narrower stage gate (not enumerated in §2.8 stage 6).
16. Amend with no `secondary_outcomes` still increments `amendment_count` (side effect unconditional); omitted secondary array left unchanged.
17. `reviewer_notes` (report review) and `reason` (site withdraw) are accepted but not persisted (no declared entity fields); participant `withdrawal_reason` is set by origin (`PARTICIPANT_INITIATED`/`SITE_WITHDRAWN`/`CONTRACT_TERMINATED`).
18. On IRB expiry, **all** OPEN waves of the study suspend even if another approved protocol's touching window already covers now (literal cascade).
19. List filters (`site_id`/`status`/`wave_type`/`study_id`) never error on unknown values; they just filter to empty.
20. Pagination `limit`/`offset` out of range (non-integer, limit<1 or >100, offset<0) → `ERR_INVALID_REQUEST`.
21. `linkage_key` = server-generated UUID string assigned at wave link.
22. `alpha`/`power_target` accepted as any JSON number, never used in the computation (informational; critical values pinned).
23. Release gate compares the stored (4-dp round-half-up quantized) `max_risk` against 0.20; exactly 0.20 passes.
24. Clock may be set backward (no prohibition); expiry only fires when the new time ≥ approval_end.
25. Explicit JSON `null` for an optional body field is treated as omitted.
26. Publish of an ACCEPTED report on a terminated contract gets no extra guard; only the fiscal gate applies (remaining is 0 after termination).

### Contradictions/tensions found (resolved as noted, not silently)
1. Record create: scaffold validations priorities 6/8 and §2.8 put the burden cap (stage 7) **before** participant eligibility (stage 9); §3.6 narrative lists eligibility first. Followed the pipeline (burden first).
2. Site activate: scaffold state-machine preconditions list IRB before plan-LOCKED; §2.8 places state (plan LOCKED, stage 6) before human-subjects (IRB, stage 7). Followed the pipeline: site state → plan LOCKED → IRB.
3. Wave open: scaffold PLANNED-branch lists the window check before IRB; §2.8 places IRB (7) before windows (8). Followed the pipeline: state → IRB → window.
4. Report resubmit: scaffold REVISION-branch lists `revision_due` before analysis-plan-registered; PRD §3.7 lists the registered/coverage gates first. Resolved via pipeline stages: registered (state-stage) → deadline (8) → coverage (9).
5. Error catalog associates `ERR_PARTICIPANT_NOT_CONSENTED` with randomize ("additionally associates"), but the state machine and §3.5 bind randomize-from-wrong-state to `ERR_PARTICIPANT_INVALID_STATE`. Used `ERR_PARTICIPANT_INVALID_STATE` for randomize; `ERR_PARTICIPANT_NOT_CONSENTED` only for record create.
6. `ERR_WAVE_WINDOW_NOT_STARTED` covers both "before open_at" and "at/after close_at" (single error id for the whole outside-window condition) — implemented as one check.

### Constants table (`grep -rn "^[A-Z_]* ="`)
```
calc.py:  CLOCK_DEFAULT_UTC="2026-09-01T00:00:00Z"  Z_ALPHA_CRIT=1.96  Z_POWER_CRIT=0.84
          QED_VARIANCE_INFLATION=1.44  YIELD_PROSPECTED=0.10  YIELD_CONTACTED=0.35
          K_ANONYMITY_MIN=5  MAX_DISCLOSURE_RISK=0.20  MAX_TOTAL_BURDEN_MINUTES=480
          MODE_FACTOR_SURVEY=1.0  MODE_FACTOR_SITE_VISIT=1.25  MODE_FACTOR_ADMIN_RECORDS=0.5
          SITE_VISIT_MIN_GAP_DAYS=7  IRB_MAX_APPROVAL_DAYS=365
          PEER_REVIEW_DAYS=45  AGENCY_COMMENT_DAYS=30  REVISION_DAYS=60  PUBLICATION_DAYS=90
clock.py: CLOCK_DEFAULT_UTC="2026-09-01T00:00:00Z" (authoritative clock init)
util.py:  PAGINATION_DEFAULT_LIMIT=10  PAGINATION_MIN_LIMIT=1  PAGINATION_MAX_LIMIT=100
          PAGINATION_DEFAULT_OFFSET=0
validation.py: ROLE_* = the 9 declared role names; STAFF_ROLES = the 6 staff roles
```
All values match SCAFFOLD.yaml exactly. No seeding anywhere; stores boot empty; `__pycache__` cleaned; all smoke server PIDs saved and killed exactly.

Orchestrator verification: 24 .py files + start.sh + requirements.txt all compile; constants grep matches PRD values exactly (1.96/0.84/1.44/0.10/0.35/5/0.20/480/1.0/1.25/0.5/7/365/45/30/60/90/2026-09-01T00:00:00Z); routes carry literal `/evaluation` prefixes per-decorator (app.py itself has zero matches — expected); clock route unprefixed at `POST /_clock/set_current_utc`; start.sh reads $PORT via app.py (proven behaviorally by smoke tests on dynamic ports 55345/48791/51327/51521), execs foreground, conditional pip install.

## Step 7: Test-fix iteration loop — 2026-10-02T19:16:00.000Z

All 8 rounds passed clean on the first sweep — 69/69 tests green in every round, zero failures, zero flakiness signals. The `results.1.json` through `results.8.json` deliverables are left in place in the implementation directory.

Summary:
- Iterations run: 1 (initial 8-round parallel sweep, all green — no fixes needed).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `implementation/`: none.

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_3486_program_evaluation_study_design_federal_reporting/workspace/implementation/` passes the full 69-test suite across all 8 concurrent rounds under per-test-server isolation. Final results files remain at `/home/ubuntu/github/CodingPRD/tasks/task_3486_program_evaluation_study_design_federal_reporting/workspace/implementation/results.{1..8}.json`.

Orchestrator verification: read all 8 results.{1..8}.json directly — each shows passed=69 total=69 failed=0 errors=0.

## Step 8: Finalize PRD — 2026-10-02T19:16:00.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no PRD_FINALIZED.md produced. Step 9 will start from PRD.md.

## Step 9: PRD completeness scan — 2026-10-02T19:35:00.000Z

The diff is exactly the 19 intended hunks (one edit spanned two diff hunks), all matching my plan. The task is complete. Final verification of counts is done: 346 → 346 lines, 66730 → 70196 bytes (+3466).

**Produced** `/home/ubuntu/github/CodingPRD/tasks/task_3486_program_evaluation_study_design_federal_reporting/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD.md` (Step 8 was skipped; `PRD_FINALIZED.md` did not exist).

- **Source vs output**: PRD.md 346 lines / 66730 chars → PRD_COMPLETED.md 346 lines / 70196 chars (**+3466 chars**, all inline inserts/revisions; no lines added or removed, no new sections).
- **Counts**: 18 ambiguity-pins, 1 mismatch-revision.

**Changes** (PRD line refers to PRD.md line):
- §2.2 (L43) — insert — ambiguity — `api_request_timestamp` read from the logical clock, never wall time — `util.py:19` (`now_iso3()`)
- §2.3 (L74) — insert — ambiguity — limit/offset range or non-integer violations → `ERR_INVALID_REQUEST` — `util.py:84-99`
- §2.3 (L76) — insert — ambiguity — `created_at` ties broken by insertion sequence; list filters match by exact equality, unknown values yield empty page — `util.py:73-74`, `participants.py:57-62`, `waves.py:93-104`
- §2.4 (L82) — insert — ambiguity — clock settable backward (no monotonicity); response `current_utc` echoes `to_iso8601` verbatim — `clock_route.py:19-21`
- §2.5 (L95) — insert — ambiguity — version bumps at most once per resource per request; `created_at`/`updated_at` stamped from logical clock; all other datetime fields emitted at whole-second precision — `util.py:56-70`, `serialize.py:9-10` (`_dt`→`fmt_dt`)
- §2.7 (L107) — insert — ambiguity — body-carried identifiers (`site_id`, `participant_id`) resolve with path-identifier semantics after schema stage, before state checks → `ERR_NOT_FOUND` — `waves.py:50-52`, `records.py:33-35`
- §2.8 stage 4 (L116) — insert — ambiguity — explicit JSON null ≡ omitted (presence-keyed rules still see the key) — `validation.py:107-122`
- §2.8 stage 6 (L118) — revise — ambiguity — `ERR_ANALYSIS_PLAN_NOT_REGISTERED` assigned to the state-validity stage — `reports.py:91-97`
- §3.1 (L150) — insert — ambiguity — zero-study closeout allowed (vacuous satisfaction) — `contracts.py:95-98`
- §3.3 (L172) — insert — ambiguity — `approval_start`/`approval_end` on a `MODIFICATIONS_REQUIRED` decision are type-checked but ignored — `irb.py:97-117,141-144`
- §3.3 (L174) — insert — ambiguity — continuing review does not re-run the overlap check — `irb.py:149-170`
- §3.4 (L184) — revise — ambiguity — site-withdraw `reason` accepted but not persisted (no site field carries it) — `sites.py:132`, `serialize.py:95-105`
- §3.5 (L196) — insert — ambiguity — participant-withdraw `reason` accepted but not persisted; `withdrawal_reason` holds only the origin enum — `participants.py:146-154`
- §3.6 (L206) — insert — ambiguity — record create requires consent status only; no participant↔wave study/site membership check — `records.py:45-48`
- §3.6 (L208) — insert — ambiguity — `linkage_key` is a freshly generated UUID — `waves.py:186`
- §3.7 (L214) — revise — ambiguity — amend without `secondary_outcomes` still bumps `amendment_count`; freeze fires on mere key presence, even explicit null — `analysis_plans.py:101-106`
- §3.7 (L218) — insert — ambiguity — coverage gate reads the latest-created `PREREGISTERED` plan — `services.py:64-69`, `reports.py:94`
- §3.7 (L220) — revise — ambiguity — `reviewer_notes` accepted but not persisted — `reports.py:125`, `serialize.py:162-180`
- §3.9 (L236) — revise — **mismatch** — RUF cell-structure revision has no API operation; resubmission from `RISK_REJECTED` re-runs the computation on stored arrays. Adjudication: the clause is unimplementable as specified — §3.9/§4 define no endpoint, payload, role, or state rule for revision (the §4 table lists only create/list/submit-review/review-decision), so it does not pin exactly one behavior; impl's reading pinned instead — `restricted_use_files.py:88-106`

**IMPL BUGS** (not fixed, not PRD-patched):
- `design_plans.py:156-159` + `services.py:220-231` — PRD §3.2: "A `decision` of `APPROVED` moves the plan to `AGENCY_APPROVED`, and if at that moment at least one site of the study is already `RECRUITED` or `ACTIVE`, the plan continues immediately, within the same request, to `LOCKED` — and the study, if still in `DESIGN`, advances to `RECRUITMENT` in the same breath." — Impl calls `maybe_lock_plan(study)`, which locks the study's *latest-created non-SUPERSEDED* plan rather than the decided plan. Triggering request shape: plan A submitted; create plan B (A is `SUBMITTED`, so not superseded — both plans live); a site reaches `RECRUITED` (allowed since current plan B is not `AGENCY_APPROVED`); then `POST /evaluation/design-plans/{A}/agency-decision {"decision":"APPROVED"}` → impl leaves A in `AGENCY_APPROVED` and the study in `DESIGN` (PRD: A → `LOCKED`, study → `RECRUITMENT`); A can never lock afterward. Untested corner — the suite only exercises the single-live-plan flow (`test_difficulty_state_cascades.py:52`).

**Targeted checks executed** (per §3a–3e): 3a — PRD "unique" declarations cover only server-generated values (`api_request_id`, `error_id`, resource `id`); all satisfied by uuid4 construction, no client-supplied uniqueness rule exists — no bug. 3b — every nullable-field read is behind a state gate guaranteeing non-None or an explicit None guard (`services.py:146,263`, `reports.py:100,175`); serializers are None-safe — no reachable 500. 3c — all 38 catalog error_ids have raise sites, no raise resolves outside the catalog; all helpers have call sites (`now_iso` unused but not PRD-required); `ERR_RECORDS_UNRESOLVED` check sits on the PRD-assigned link path — no dead-check bug. 3d — zero wall-clock calls; `set_now`/`evaluate_irb_expiry` reachable only via the unprefixed `POST /_clock/set_current_utc`. 3e — funds invariant maintained at create/terminate/closeout/publish (only writers); enrollment invariant maintained via single-recount recompute on consent, withdraw, site/terminate cascades, and study completion.

Orchestrator verification of Step 9 output: `diff PRD.md PRD_COMPLETED.md` = 38 changed lines (19 hunks, matches claim); §3.2 auto-lock sentence retained verbatim at PRD_COMPLETED.md L164 (impl bug NOT patched into the contract — correct); zero `implementation/*.py` files modified after the 19:16 sweep (Step 9 edited only PRD_COMPLETED.md, as instructed).

## Step 9b: Impl-defect fix + re-sweep — 2026-10-02T19:46:00.000Z

Orchestrator adjudication of the single IMPL BUG: PRD §3.2 pins the decided plan ("the plan continues immediately ... to LOCKED") and separately pins "a plan in AGENCY_APPROVED locks automatically" at first-site-RECRUITED — both unambiguous, both violated by `maybe_lock_plan`'s latest-created-non-SUPERSEDED target selection (`current_plan`). Two-live-plans is PRD-legal (creation supersedes only certain states), so the bug is reachable on a legal path the 69-test suite never exercises. Verdict: genuine impl bug; PRD_COMPLETED.md untouched (impl moves toward PRD).

Fix applied (orchestrator, 2 edits):
- `services.py` `maybe_lock_plan(study, plan=None)` — explicit decided-plan parameter; when omitted, targets the study's AGENCY_APPROVED-status plan (latest-created among approved) instead of latest-created non-SUPERSEDED. Behavior on all suite-exercised paths (single live plan) is identical.
- `design_plans.py:159` — agency-decision APPROVED branch now calls `maybe_lock_plan(study, plan)` with the decided plan.

Post-fix verification: `py_compile` OK on both files; full 8-round parallel sweep re-run by orchestrator (per-test-server isolation, fresh results.{1..8}.json regenerated and left in place) — **all 8 rounds 69/69, SWEEP CLEAN**.
