## Step 1: Create task directory — 2026-10-01T14:27:33.328431601Z

Pre-allocated task directory used as-is: ./tasks/task_3392_school_affiliation_teacher_credentialing_classroom_standards (workspace/ already inside). Index was NOT recomputed; no other task_* directory was created.

## Step 2: Generate scaffold — 2026-10-01T16:04:37.9072333Z

All validation gates pass. The scaffold is complete.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (61 endpoints, 14 entities, 18 §1.8 instances, 51 §1.9 instances, 965 calls scanned)

**Manual audits beyond lint:** placeholder closure verified programmatically (0 unbound `${var}`, 0 duplicate captures, 0 name collisions across 71 instance entries); forbidden concurrency vocabulary absent; every error code referenced outside its catalog row; all role `identity:` fields resolve; two real bugs found and fixed during replay — a circular practicum-supervisor precondition (resolved by making `supervisor_credential_id` optional for bootstrap cohorts) and a validation-priority inversion (field-shape moved to priority 4 so a garbage enum yields `ERR_VALIDATION`, not `ERR_AGE_LEVEL_MISMATCH`; all `validations[priority=N]` references and prose remapped accordingly). All formula-derived assert literals were computed with Python before being pinned (dues floor 60000 / tier-boundary 207200 / cap 1500000; materials 0.9175-pass vs 0.8929-fail rounding divergence; CE cycle 10.0 vs rolling 40.0; ratio 15.00-pass vs 15.50-fail).

result: Scaffold generated and lint-clean at /home/ubuntu/github/CodingPRD/tasks/task_3392_school_affiliation_teacher_credentialing_classroom_standards/

**Final report:**
- **Line counts:** SCAFFOLD.yaml 2121, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1794, SCAFFOLD_CORNER_DESIGN.yaml 2924 — all three parse as valid YAML (verified after every append and in a final pass).
- **§1.8 difficulty instances:** 18 (exactly 2 per rule across all nine rules: CE cycle-vs-rolling + school latest-vs-no-fail dual variants; dues tiered/floor/cap (mode a) + materials rounding-order (mode b); SelfStudy and Credential cyclic machines; plan-overdue and credential-revocation depth-3 cascades from different triggers; state-vs-temporal and referential-vs-fiscal priority conflicts; ratio-cap and CE-threshold boundaries on different endpoints/metrics; Credential↔Placement and Application↔Plan cross-entity gates; half-open placement overlap vs buffered consultant-visit overlap; CE-ledger void conservation and enrollment-transfer conservation).
- **§1.9 corner instances:** 53 total (51 active + 2 `excluded_because` stubs), spanning all nine taxonomy sections; every one of the 52 error codes is triggerable by at least one instance.
- **API endpoints declared:** 61 (note: deliberately above the Expert band guideline per the "much harder than expert" instruction — the FK reverse-reachability rule forces ~27 read endpoints; flag to impl-gen to use per-domain modules).
- **api_prefix:** `/society`
- **Core entities:** StandardsCatalog, School (parallel dimensions: membership_level × standing), Classroom, ClassroomAudit, TeacherEducationProgram, AdultLearner, PracticumPlacement, Credential, SchoolApplication, SelfStudy, VerificationVisit (report fields inlined), ImprovementPlan, PDEvent, CECreditEntry.

Orchestrator verification: all three files exist and parse as valid YAML; top-level keys confirmed (SCAFFOLD.yaml has §1.x keys only, design files carry their single design key each); api_prefix `/society` present; domain-fidelity grep (society/School/Credential/Classroom/Practicum/SelfStudy/ImprovementPlan/PDEvent/CECredit/AdultLearner all present; restaurant/warehouse/hotel/etc. zero hits).

## Step 3: Copy shared files — 2026-10-01T16:04:37.28532288Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (byte-identical via cmp).

## Step 4: Generate PRD — 2026-10-01T16:33:25.525538783Z

All checks pass. The PRD is complete and verified against the scaffold. The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_3392_school_affiliation_teacher_credentialing_classroom_standards/workspace/PRD.md`

**PRD.md line count:** 340 lines.

**Document ends complete:** the final line is `| ERR_FEE_MISMATCH | 422 |` — the last row of the §5 Error Code Catalogue, not a dangling fragment. Document structure: §1 Introduction (2 paragraphs), §2.1–§2.10 (roles/identity, verbatim §2.2 envelope block, pagination, common resource properties, logical clock, catalog pinning, the ten-tier validation pipeline, OCC, precision, nested resolution), §3.1–§3.8 (standards publishing; onboarding/brand/dues; classrooms/audits; programs/learners/placements; credentials/CE/renewal/revocation; self-study/visits/plans; applications/standing/cascades; public directory), §4 endpoint table, §5 error catalogue.

**Constant/error-code coverage (grep-count comparison):**
- Error codes: 52 declared in scaffold → 52 found verbatim in PRD (52 rows in §5, each with the scaffold's exact HTTP status; all 52 also appear in §2/§3 prose — zero absent).
- Endpoints: 61 in scaffold → 61 rows in §4, exact method+path match, zero missing/extra.
- Field names (Contract 1): 121 required (all `entities[].fields[].name` + endpoint inputs + `id`), 0 missing from backticked prose.
- Numeric thresholds: all present — pagination 10/1/100/0; dues constants 40000/90000/150000/1500/1200/900/8000/60000/1500000 with all five worked anchors (48000→60000, 452000, 198000, 199200, 1780000→1500000); renewal fees 8500/5000; supervisor cap (fewer than 3 / exactly 3 allowed); 12-month NO_FAIL_IN_CYCLE window; 2dp/4dp/1-decimal precision rules; materials counter-example 0.9175 vs 0.8929; clock start 2026-09-01T00:00:00Z; `METHOD_NAME` = "Montessori". The only scaffold integer not literal in the PRD is `301`, rendered as "beyond 300" (the tier boundary 300 is pinned verbatim).
- §3 path purity (Contract 3): 642 backticked tokens scanned, 0 path/method violations.

**Contract 2 walk:** all state-machine transitions, preconditions and side effects expressed (including the revocation cascade's three tiers, the plan-overdue standing cascade, and the application suspend/resume/deny cascades); all 11 calculations in precise prose with rounding order pinned; all three OCC rules with `expected_school_version`/`expected_improvement_plan_version` + `ERR_STALE_VERSION` 412; ten-tier validation priority with first-failure-wins and OCC-before-state ordering; renewal's four checks in priority order.

**Scaffold ambiguities resolved in prose (listed explicitly):**
1. Early report filing (before `window_start`) has a precondition but no named error in the scaffold → mapped to `ERR_VISIT_WINDOW_INVALID` (422).
2. Log-hours on a non-`ACTIVE` placement has no named error → stated as `ERR_INVALID_STATE` (409).
3. Audit `visit_id` belonging to a different school sits in the priority-8 referential tier → described as "a referential failure, HTTP 422" (head code `ERR_AGE_LEVEL_MISMATCH` named at tier level in §2.7).
4. Classroom lead credential not `ACTIVE` at assignment → requirement stated; only the age-level half names a code (`ERR_AGE_LEVEL_MISMATCH`), matching the scaffold.
5. Directory endpoints list only `Anonymous` → prose states they accept unauthenticated callers; silent on whether identified roles are rejected rather than inventing a rule.
6. Program accreditation with no `ACTIVE` catalog → comparison stated against the `ACTIVE` catalog; `ERR_NO_ACTIVE_CATALOG` attached only to the scaffold's named scope (self-study/placement/audit creation).
7. `dues-payments` does not validate `amount_cents` against the dues quote — no such rule exists in the scaffold, so none was written.

result: PRD generated at workspace/PRD.md (340 lines); all three hard contracts PASS — 121/121 field names, 52/52 error codes with correct statuses, 61/61 endpoints, 0 §3 path-purity violations, all numeric thresholds verbatim.

Orchestrator verification: PRD.md is 340 lines and ends with the complete §5 error catalogue (last line `| ERR_FEE_MISMATCH | 422 |`); independent cross-check found 52/52 real scaffold error codes present (53rd scaffold token is the placeholder `ERR_XXX`) and 61/61 endpoints findable; key literals (clock start 2026-09-01, METHOD_NAME Montessori, dues floor 60000 / cap 1500000, ERR_STALE_VERSION, expected_school_version, /society prefix ×64) all present.

## Step 5a: Generate test helpers (Phase A of split Step 5) — 2026-10-01T17:06:59.912176769Z

All checks pass and the tree contains exactly the Phase A deliverable. Final report below.

---

## Phase A complete — `test_helpers/` frozen for task_3392

**Sanity checks run:** `python3 -m py_compile` on all 9 files (OK); `import test_helpers` with the task dir on `sys.path` (OK, no dangling imports); export-surface probe over 70+ names (none missing); error-catalog cross-check — all 52 `ERR_*` ids grepped from PRD.md are present in `ApiErrorId` and mapped in `HTTP_STATUS_CODES`; dues recomputation reproduces all five PRD worked anchors; date helpers reproduce every recipe-derived boundary (renewal open 2029-06-01, grace ends 2030-03-01/2033-03-02, plan dues 2026-10-31/2027-11-19, tenure 2027-09-01); materials pinned-order probe yields 0.9175-pass at 0.9; `ApiClient` has exactly 61 endpoint methods; `api_client.base_url` proven to come from `API_BASE_URL` (set to a dummy port, read back). No `test_suite/` exists.

### Files written (all under `.../test_helpers/`)

| file | lines | contents |
|---|---|---|
| `__init__.py` | 57 | barrel: framework generics + all PRD-specific modules |
| `types.py` | 401 | 21 enums, 16 TypedDicts (ClassroomAudit/CECreditEntry lean: no `updated_at`/`version`) |
| `api_client.py` | 289 | `ApiClient(GenericApiClient)`, 61 endpoint methods, `/society` prefix, `api_client` singleton |
| `api_errors.py` | 132 | `ApiErrorId` (52 ids) + `HTTP_STATUS_CODES` + `set_error_http_status_map` at import |
| `assertions.py` | 415 | 16 `assert_*` shape checks + invariants + `round_half_up`, `expected_annual_dues_cents`, `expected_renewal_fee_cents`, `expected_materials_score`, `expected_materials_pass` |
| `factories.py` | 418 | 24 payload factories, frozen "Standards 2026"/"Standards 2027" editions, unique-suffix naming |
| `constants.py` | 113 | PRD-derived constants (table below) |
| `test_users.py` | 124 | `TEST_USERS` (6 opaque + 3 entity-backed fallbacks + `anonymous_headers={}`), 5 `make_*_headers` builders |
| `fixtures.py` | 862 | 50+ builders: clock, catalogs, schools, classrooms, audits, programs, learners, placements, applications, self-studies, visits, plans, credentials, CE ledger, 8 composite `setup_*` tiers |

### Frozen constant table (name → value → PRD source)

- `CLOCK_START_ISO = "2026-09-01T00:00:00Z"` — PRD §2.5 "the logical clock reads exactly 2026-09-01T00:00:00Z"
- `METHOD_NAME = "Montessori"` — PRD §3.2 "the constant `METHOD_NAME`, whose value is 'Montessori'"
- `BASE_DUES_AFFILIATE_CENTS = 40000`, `MEMBER = 90000`, `ACCREDITED = 150000` (APPLICANT quotes AFFILIATE) — PRD §3.2
- `TIER1_UP_TO = 100`, `TIER1_RATE_CENTS = 1500`; `TIER2_UP_TO = 300`, `TIER2_RATE_CENTS = 1200`; `TIER3_RATE_CENTS = 900` — PRD §3.2 marginal tiers
- `PER_CLASSROOM_SURCHARGE_CENTS = 8000` — PRD §3.2
- `MIN_DUES_CENTS = 60000`, `MAX_DUES_CENTS = 1500000` (floor before cap) — PRD §3.2
- Dues anchors 60000 / 452000 / 198000 / 199200 / 1500000 — PRD §3.2 worked anchors
- `RENEWAL_BASE_FEE_CENTS = 8500`, `RENEWAL_LATE_FEE_CENTS = 5000` (13500 lapsed) — PRD §3.5 "the expected amount is 8500 cents, plus a 5000-cent late fee"
- `SUPERVISOR_MAX_ACTIVE_PLACEMENTS = 3` — PRD §3.4 "exactly 3 supervised placements is allowed"
- `CLEARANCE_CYCLE_WINDOW_MONTHS = 12` — PRD §3.7 "the trailing 12 calendar months"
- `RATIO_DECIMALS = 2`, `MATERIALS_GROUP_DECIMALS = 2`, `MATERIALS_SCORE_DECIMALS = 4`, `CE_HOURS_DECIMALS = 1` — PRD §2.9
- `PAGE_LIMIT_DEFAULT = 10`, `MIN = 1`, `MAX = 100`, `OFFSET = 0` — PRD §2.3
- Frozen edition values (in `factories.create_standards_catalog_payload`, identical in both design indices): EC work 180 min, EC cap 15, materials threshold 0.9, EC span 3, EC practicum 540 h, CE required 30 h, validity 36 mo, window 3 mo, grace 6 mo, tenure 12 mo, travel buffer 1 day, plan response 30 days. These are test-chosen catalog *inputs* (the PRD leaves edition values to the payload); both design indices' shared anchors agree byte-for-byte, so there is no drift to resolve.

### Date literals frozen (all ≥ clock start 2026-09-01T00:00:00Z; none re-derived)

- Placement default window `2026-09-15` → `2027-03-15`, default `work_date 2026-12-01` (inside window) — matches every bootstrap recipe; end strictly after clock start ✓
- Dues default period `2026-09-01` → `2027-09-01` (host schools); `2028-09-01` for MEMBER/ACCREDITED fixtures so `dues_current` survives the clock advancing to 2027-10-20 ✓
- Visit default window `2026-10-01` → `2026-10-03`; accreditation-stage window `2027-10-10` → `2027-10-12`, `submit_at 2027-10-20` — mirrors the recipes (in-window audit for NO_FAIL_IN_CYCLE, tenure satisfied)
- PD event defaults `2027-01-31T09:00:00Z` → `2027-02-01T17:00:00Z`; `create_completed_pd_event` advances the clock one day past `end_at`
- Mentee window `2027-04-01` → `2027-10-01` (supervisor-capacity recipe)
- No fixture date predates the clock start; no recipe window was clock-unreachable, so no literal needed re-derivation.

### Exported-helper signature list (Phase B targets)

- Client: 61 methods, conventions `create_*(payload, headers=None)`, `get_*(id, headers=None)`, `list_*(headers=None, params=None)`, actions `(id, payload=None, headers=None)`; full names in `api_client.py` (e.g., `set_clock`, `create_standards_catalog`, `activate_standards_catalog`, `create_school`, `update_school_brand`, `record_dues_payment`, `set_school_standing`, `list_directory`, `get_directory_school`, `create_classroom`, `transfer_students`, `create_classroom_audit`, `create_teacher_education_program`, `set_program_status`, `create_adult_learner`, `create_practicum_placement`, `log_placement_hours`, `verify_practicum_placement`, `cancel_practicum_placement`, `create_credential`, `renew_credential`, `revoke_credential`, `create_school_application`, `submit_school_application`, `review_school_application`, `create_self_study`, `submit_self_study`, `review_self_study`, `create_verification_visit`, `cancel_verification_visit`, `file_visit_report`, `get/list_improvement_plans`, `respond_to_improvement_plan`, `review_improvement_plan`, `create_pd_event`, `record_event_attendance`, `get/list_ce_entries`, `void_ce_entry`).
- Headers: `TEST_USERS` keys `society_admin_headers`, `accreditation_reviewer_headers`, `accreditation_reviewer_2_headers`, `registrar_headers`, `consultant_headers`, `consultant_2_headers`, `school_admin_headers` (fallback only), `program_director_headers` (fallback), `adult_learner_headers` (fallback), `anonymous_headers` (`{}`); builders `make_school_admin_headers(school_id)`, `make_program_director_headers(program_id)`, `make_adult_learner_headers(learner_id)`, `make_consultant_headers(consultant_id)`, `make_reviewer_headers(uid)`, `make_headers(uid, role)`. Opaque ids: `con-ada`, `con-zed`, `rev-quinn`, `rev-mira`, `reg-otto`, `soc-admin-1`.
- Factories: `set_clock_payload`, `create_standards_catalog_payload`, `create_next_catalog_payload`, `create_school_payload`, `update_brand_payload`, `record_dues_payment_payload`, `set_standing_payload(to_standing)`, `create_classroom_payload(school_id)`, `transfer_students_payload(to_id, count)`, `compliant_materials_groups()`, `create_classroom_audit_payload(classroom_id)`, `create_program_payload`, `set_program_status_payload(to_status)`, `create_adult_learner_payload(program_id)`, `create_practicum_placement_payload(learner_id, host_school_id)`, `log_hours_payload(hours, work_date)`, `create_credential_payload(learner_id, age_level)`, `renew_credential_payload(fee_cents)`, `create_school_application_payload(school_id, app_type, expected_school_version)`, `review_application_payload(outcome)`, `create_self_study_payload(school_id, expected_school_version, narrative=None)`, `review_self_study_payload(outcome)`, `create_verification_visit_payload(school_id, self_study_id, consultant_id)`, `file_visit_report_payload(verdict, findings)`, `respond_to_plan_payload(notes, expected_version)`, `review_plan_payload(outcome)`, `create_pd_event_payload`, `record_attendance_payload(credential_id, hours_earned=None)`.
- Assertions: `assert_{standards_catalog, school, classroom, classroom_audit, teacher_education_program, adult_learner, practicum_placement, credential, school_application, self_study, verification_visit, improvement_plan, pd_event, ce_credit_entry, directory_verification}(data)`; invariants `assert_school_invariants`, `assert_audit_verdict_consistency`; recomputers `expected_annual_dues_cents(level, total_enrollment, classroom_count)`, `expected_renewal_fee_cents(status)`, `expected_materials_score(groups)`, `expected_materials_pass(groups, threshold)`, `round_half_up(value, places)`.
- Fixtures (full signatures verified above): date helpers `date_of`, `add_calendar_months`, `add_days`, `instant_day_after`, `expected_plan_due_date`; clock `set_clock(to_iso8601)`, `reset_clock()`, `set_clock_past_expiry(credential)`, `set_clock_past_grace(credential)`, `renewal_window_open_date(credential)`; primitives `create_active_catalog`, `create_school`, `read_school`, `school_version`, `pay_dues`, `update_brand`, `set_standing`, `create_classroom`, `read_classroom`, `transfer_students`, `file_classroom_audit(classroom_id, consultant_id=..., **obs)`, `create_program`, `create_accredited_program`, `set_program_status`, `enroll_learner`, `create_placement`, `log_hours`, `verify_placement`, `cancel_placement`, `create_verified_placement`, `create_application` (self-reading OCC), `submit_application`, `review_application`, `advance_school_once`, `create_self_study` (self-reading OCC), `create_accepted_self_study`, `create_visit`, `file_visit_report`, `cancel_visit`, `read_improvement_plan`, `list_plans_for_school`, `get_only_plan_for_school`, `respond_to_plan` (self-reading OCC), `review_plan`, `make_plan_overdue`, `issue_credential`, `read_credential`, `renew_credential(credential_id, learner_id, fee_cents, as_learner)`, `revoke_credential`, `create_pd_event`, `create_completed_pd_event`, `record_attendance`, `grant_ce_hours`, `void_ce_entry`; composites `setup_affiliate_host_school`, `setup_member_school`, `stage_accreditation_application`, `setup_accredited_school`, `setup_credentialed_teacher`, `setup_supervisor_with_mentees`, `setup_school_with_reported_visit`, `setup_expired_credential`.

### Scaffold/PRD inconsistencies found and resolved

1. **Missing-catalog gap in composite fixtures (caught pre-freeze):** `setup_member_school` / `stage_accreditation_application` / `setup_school_with_reported_visit` file audits and create self-studies, which require an ACTIVE catalog (`ERR_NO_ACTIVE_CATALOG`), but initially created none. Fixed with `ensure_catalog=True` default that creates the standard edition first, opt-out for catalog-pinning tests. Since the API has no catalog list endpoint, existence can't be probed — hence the explicit flag.
2. **Dues horizon:** an ACCREDITATION-stage school submitted at clock 2027-10-20 fails `ERR_DUES_DELINQUENT` if dues run only to the host-school default 2027-09-01; the accreditation fixtures therefore default `dues_period_end="2028-09-01"` (matching the recipes' 2028-09-01 payments), while practicum-host fixtures keep 2027-09-01.
3. **member_since drift across recipes:** the difficulty index has one school "MEMBER since 2026-09-03" (clock stepped mid-chain) while others use 2026-09-01. The fixtures always advance levels at the clock-start instant (member_since = 2026-09-01); Phase B tests that need a different tenure anchor set the clock themselves before `advance_school_once`.
4. **`NON_EXISTENT_UUID` shape:** the corner recipes use `00000000-0000-4000-8000-000000000000` while the framework's constant is `00000000-0000-0000-0000-000000000000`; both are unallocated. The barrel re-exports the framework's and adds `NON_EXISTENT_UUID_ALT` for the recipe shape (and for two-distinct-unknown-id calls).
5. No PRD↔scaffold contradictions found in error ids, statuses, or constants; the PRD §5 table and scaffold §1.6 agree exactly (52 ids).

result: Phase A helper layer frozen for task_3392 — 9 files in test_helpers/ (2811 lines), compiles + imports clean, 61 endpoint methods, 52-error map registered, all constants traced to PRD prose, ready for Phase B test generation.

Orchestrator verification: all 9 files present; py_compile OK; `import test_helpers` OK (282 names); no test_suite/ exists; constants.py numeric and string constants all trace to PRD.md (sole exception NON_EXISTENT_UUID_ALT, an intentionally-unallocated id that must NOT appear in PRD).

## Step 5b: Generate test suite (Phase B of split Step 5) — 2026-10-01T17:58:56.718088003Z

Everything is green. Final report follows.

## Phase B complete — test suite generated for task_3392

**Files written** (all under `.../test_suite/`):

| File | Lines | Tests |
|---|---|---|
| conftest.py | 72 | 0 |
| test_01_school_onboarding_brand_and_classrooms.py | 278 | 6 |
| test_02_catalog_editions_and_pinning.py | 152 | 3 |
| test_03_audit_scoring.py | 245 | 8 |
| test_04_annual_dues.py | 62 | 2 |
| test_05_programs_learners_credential_issuance.py | 202 | 6 |
| test_06_practicum_placements.py | 271 | 8 |
| test_07_credentials_lifecycle.py | 216 | 7 |
| test_08_ce_ledger_and_renewal.py | 294 | 8 |
| test_09_application_submission_gates.py | 236 | 8 |
| test_10_self_study_lifecycle.py | 98 | 3 |
| test_11_verification_visits.py | 180 | 5 |
| test_12_improvement_plans_and_occ.py | 204 | 5 |
| test_13_cascades.py | 135 | 4 |
| test_14_accreditation_clearance.py | 131 | 3 |
| test_15_transfers_directory_consistency.py | 172 | 5 |
| test_16_security_and_not_found.py | 213 | 7 |

**Total: 88 tests.** Queue A: 36 (18 instances × 2). Queue B: 52 tags over the 51 non-stub instances (work_period got 2).

**pytest --collect-only verdict (verbatim tail):**
```
tasks/.../test_16_security_and_not_found.py::test_not_found_sweep_remaining_entities
88 tests collected in 0.23s
```
Zero collection errors (one early `create_credential` import typo in test_05 was fixed; the full package graph imports cleanly).

**AST tag audit (real `ast` parse, not a character window):** 88/88 tests carry exactly one `Design:` line; every tag resolves to exactly one non-stub instance. Coverage: queue A 18/18 instances with ≥2 tests; queue B 51/51 non-stub instances with ≥1 test. No untagged, dual-tagged, or dangling tags.

**Skipped instances (complete coverage diff):**
- `Corner/calculations/dues_formula_full_surface` — `excluded_because` stub; pointer `dues_marginal_tiers_floor_and_cap` RESOLVES; not translated per the skill.
- `Corner/calculations/materials_rounding_order` — `excluded_because` stub; pointer `materials_score_per_group_rounding_order` RESOLVES; not translated.
- Zero instances skipped for PRD-silence or non-unique-derivability — every other §1.8/§1.9 instance passed both filter conditions.

**Verbatim citation sweep:** 135 quoted citation spans extracted from docstrings; all 135 survive literal grep of `workspace/PRD.md` (modulo whitespace). No `skip`/`skipif`/`xfail` markers anywhere; no scaffold/§1.x references in comments or docstrings; create endpoints asserted with explicit 201.

**Two adjudicated deviations (PRD-first, noted not silent):**
1. `accreditation_submit_rejected_with_self_study_error_over_dues_error` — the recipe's clock bump to 2026-09-02 before the MEMBERSHIP approval would make member_since 2026-09-02, breaking the asserted "tenure boundary exactly satisfied" outcome. Re-derived per the instance's own distinguishing aspect: no clock advance, so member_since = 2026-09-01 and 2027-09-01 passes with equality. The audit at 2026-09-01 is still in the clearance window.
2. `transfer_rejects_overdraft_and_cross_school` — the recipe's first trigger was doubly-violating (cross-school AND 41 > 40), and PRD §3.3 names both errors with no same-tier sub-order, so its asserted error was not uniquely derivable. Split into two isolated single-failure scenarios (same-school overdraft → `ERR_TRANSFER_EXCEEDS_ENROLLMENT`; cross-school within count → `ERR_TRANSFER_CROSS_SCHOOL`), preserving the instance's exact error ids.
3. Version literals: recipes asserting absolute versions (`version == 1`) are not uniquely derivable from PRD §2.4 (only "increments by one on every mutation" is). Asserted increment relationships (`v2 == v1 + 1`) instead — the OCC stale/fresh behavior, the actual claim, is fully pinned.

**Fixture dates:** all ≥ clock start 2026-09-01T00:00:00Z; catalog `effective_from` values are ordering labels, not clock reads, so no clock-unreachable literals.

**Helper-layer gaps:** none. All fixtures/factories/assertions used against their frozen signatures; `test_helpers/` untouched (mtimes 16:45–17:03, all pre-Phase-B).

result: test_suite/ complete — 88 tests (36 difficulty + 52 corner tags covering all 18 §1.8 and all 51 non-stub §1.9 instances), collect-only clean, AST tag audit and 135-span PRD verbatim citation sweep both fully green.

Orchestrator verification: independent `pytest --collect-only` collects exactly 88 tests with zero errors; zero skip/skipif/xfail markers; independent AST audit (structure-aware: Difficulty/<rule_id>/<name>, Corner/<section>/<name>) confirms 88 resolvable tags, no dual/untagged tests, and 69/69 non-stub instances covered (18 difficulty + 51 corner); test_helpers mtimes all pre-Phase-B (freeze intact).

## Step 6: Generate implementation — 2026-10-01T18:44:47.807009364Z

The suspect PID was transient and is already gone — no leaked servers. All verification is complete.

result: Task 3392 (Montessori Society Accreditation) fully implemented — 22 files / 3,539 lines in workspace/implementation/, all 61 endpoints, compiles + imports clean, two dynamic-port smoke runs pass including the full catalog→school→classroom→program→learner→placement→credential→CE→renewal chain.

## Final Report

### Files written (all under `.../workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Guarded pip install (no-op once flask present), `exec python3 app.py`, `$PORT`/0.0.0.0/foreground |
| `requirements.txt` | 1 | flask>=3.0,<4 |
| `app.py` | 71 | Flask wiring, 12 blueprints under `/society`, ApiError/404/405/500 envelope handlers |
| `store.py` | 157 | In-memory dicts, logical clock (starts `2026-09-01T00:00:00Z`, never wall time), id/timestamp helpers, `add_months`, receipt-order seq |
| `errors.py` | 82 | All 52 PRD §5 error_ids with exact HTTP statuses |
| `envelope.py` | 77 | §2.2 success/error envelope, `req_` ids, 3-fraction-digit timestamps, §2.3 pagination (limit default 10 clamp [1,100], offset default 0) |
| `validation.py` | 167 | Tier 1/2 auth (`X-User-ID`/`X-User-Role`, 8 roles) + tier-4 shape helpers |
| `derived.py` | 187 | Dues schedule (constants from scaffold; floor-before-cap), brand/directory/total_enrollment/compliant count, LATEST_PASS + NO_FAIL_IN_CYCLE clearance, CE CYCLE/ROLLING totals |
| `serializers.py` | 262 | Per-entity public dicts; audits/CE entries lean (no `updated_at`/`version`) |
| `cascade.py` | 129 | Standing transition side effects (suspend/resume/deny applications), plan auto-creation, clock sweep (credential LAPSED/EXPIRED, plan OVERDUE→standing cascade, event COMPLETED) |
| `routes_clock.py` | 26 | Clock set + sweep |
| `routes_catalogs.py` | 109 | Catalog create/get/activate (effective-order + auto-retire) |
| `routes_schools.py` | 239 | School CRUD, brand, dues (201), standing ladder, public directory (anonymous) |
| `routes_classrooms.py` | 359 | Classrooms, transfer (conservation), audits with pinned per-group-first materials rounding (8/9,8/9,8/9,1/1 → 0.9175 pass) |
| `routes_programs.py` | 199 | Programs + status ladder + practicum-standard gate; learners |
| `routes_placements.py` | 220 | Placements (half-open overlap, supervisor ACTIVE/capacity-3, host eligibility), log-hours (auto HOURS_COMPLETE), verify, cancel |
| `routes_credentials.py` | 220 | Issuance, renewal (state→window→CYCLE-CE→fee, 8500/13500), revocation cascade |
| `routes_applications.py` | 305 | Application create (OCC + type-matches-level), submit (state→tenure→referential→constraint→fiscal), review (dues recheck, segregation of duties, level advance + anniversaries) |
| `routes_studies.py` | 158 | Self-study create (OCC, in-flight, catalog pin + label), submit, review (ACCEPTED pins school catalog, bumps school version) |
| `routes_visits.py` | 199 | Visit scheduling (travel-buffer conflict, touching counts), cancel, report filing (plan auto-create + NONCOMPLIANT→PROBATION) |
| `routes_plans.py` | 126 | Plan respond (OCC before state), review (VERIFIED auto-restores PROBATION→GOOD_STANDING; CHANGES_REQUESTED fresh due_date) |
| `routes_events.py` | 193 | PD events, attendance (COMPLETED-only, duplicate guard, `earned_at = end_at`), CE entry read/list/void |

### Compile + import proof
`python3 -m py_compile *.py` → OK on all 20 modules (twice, including post-fix). `import app` → IMPORT_OK; route table lists exactly the 61 scaffold endpoints under `/society`. Constant sweep: every `ERR_*` referenced is defined exactly once in `errors.py` and imported per module (import success proves resolution); remaining ALL-CAPS tokens are enum string literals, not constants.

### Self-smoke-test transcript (dynamic ports, servers killed by exact PID)
- Boot: `GET /society/directory` anonymous → 200, `{items: [], total_count: 0, has_more: false}`, `req_`-prefixed id.
- Catalog create 201 → activate 200 `ACTIVE`. School create 201: `APPLICANT`/`GOOD_STANDING`, `annual_dues_cents=60000` (floor), `version=1`. Dues payment 201 → `dues_current=true`, `version=2`.
- Classroom create 201. Bad `age_level` → 400 `ERR_VALIDATION` with exact envelope shape.
- Application create 201 → submit 200 `UNDER_REVIEW` → re-submit 409 `ERR_INVALID_STATE`. Self-study with stale version → 412 `ERR_STALE_VERSION`. Clock set → echoes `2027-01-15T00:00:00Z`.
- Deep chain: AFFILIATION submit+approve → `AFFILIATE` + `affiliated_since=2026-09-01`; program accredited; learner → placement (`target_hours=100` pinned) → 60+40h → `HOURS_COMPLETE` → verify → credential 201 (`cycle_start=2026-09-01`, `expires_at=2028-09-01…`) → learner `CREDENTIALED`; attendance on SCHEDULED event → 409 `ERR_INVALID_STATE`; clock advance → event `COMPLETED`; attendance 201 (`hours=40.0`, `earned_at`=event end); duplicate → 409 `ERR_DUPLICATE_ATTENDANCE`; renew too early → 422 `ERR_RENEWAL_WINDOW_CLOSED`; at window-open boundary (inclusive) wrong fee → 422 `ERR_FEE_MISMATCH`, correct fee → 200 (`renewed_count=1`, CYCLE rebased to 0.0); void → totals 0.0; audit 8/9×3+1/1 → `materials_score=0.9175`, `COMPLIANT`, `failed_checks=[]`, no `version` on audit; classroom `latest_audit_verdict=COMPLIANT`; school `compliant_classroom_count=1`.

### Interpretations chosen (each with the governing PRD sentence)
1. **All server-stamped timestamps use the logical clock** (created_at, updated_at, submitted_at, decided_at, report_filed_at, verified_at, issued_at, observed_at, api_request_timestamp), formatted with 3 fractional digits per §2.4 — "the server must never fall back to wall-clock time" (§2.5); "the server stamps `observed_at` with the logical clock" (§3.3). `current_utc` echoes the raw `to_iso8601` string (§2.5 shows `2026-09-01T00:00:00Z` unfractionated).
2. **Same-instant created_at ties break by a global receipt-order sequence** — "two audits filed in the same logical instant are tie-broken by server receipt order (the later-filed request wins) — never by id" (scaffold calculations, echoed §3.7).
3. **Ownership (tier 5) enforced on writes only; reads check role membership alone** — scaffold tier-5 row scopes to "all role-scoped write endpoints"; §4 grants e.g. SchoolAdmin `GET /credentials/{id}`, which has no school linkage, making read-ownership inapplicable.
4. **Unnamed tier-8 referential failures return ERR_AGE_LEVEL_MISMATCH (422)** — "reported as `ERR_AGE_LEVEL_MISMATCH` (HTTP 422) except where a named variant applies" (§2.7). Applied to visit-create study-belonging/acceptance ("failing the referential tier (HTTP 422)", §3.6) and audit-visit school belonging ("a referential failure, HTTP 422", §3.3).
5. **Classroom create with a non-ACTIVE lead credential → ERR_INVALID_STATE (409)** — "when supplied it must reference an `ACTIVE` credential whose age level equals the classroom's" (§3.3); only the level-mismatch error is named, so the posture failure uses the state-tier error.
6. **Reviewer restore to GOOD_STANDING with open plans → ERR_OPEN_IMPROVEMENT_PLAN (409)** — "permitted only when no improvement plan of the school remains in `OPEN`, `OVERDUE` or `SUBMITTED`" (§3.7); the named catalog error is reused.
7. **Credential-issuance guard order follows the tier pipeline, not §3.5's narrative** — age-level at tier 8 before PRACTICUM_NOT_VERIFIED → PROGRAM_NOT_ACCREDITED → DUPLICATE_CREDENTIAL at tier 9, because §2.7's ordering is "contractual, not descriptive".
8. **Self-study submit checks state (409) before narrative-non-empty (400)** — the narrative is stored state, not submit payload; §3.6 introduces the state first ("A study in `DRAFT` — or one returned for revision — is submitted…; the narrative must be non-empty").
9. **Renewal window is date-granular, inclusive, off the ACTIVE catalog** — "opens `renewal_window_months` before the date of `expires_at` and closes `renewal_grace_months` after it — both boundary dates themselves qualify" (§3.5); month arithmetic clamps the day to month end.
10. **Pagination limit/offset clamp rather than error** — "accepts a minimum of 1, and is capped at a maximum of 100" (§2.3).
11. **Non-listed directory read returns exactly `{display_name, listed: false}`** — "it answers with `listed` false and the `display_name` only" (§3.8); list items carry the full public payload.
12. **materials_groups.required_count must be ≥ 1 (400)** — division-by-zero guard under tier 4 "numeric ranges honored"; PRD names only `present_count <= required_count`.
13. **Placement creation advances the learner only from ENROLLED** — "its creation advances the learner from `ENROLLED` to `IN_PRACTICUM`" (§3.4) with the scaffold's learner-machine precondition `learner.status == ENROLLED`; no guard invented against placing a PRACTICUM_COMPLETE/CREDENTIALED learner.
14. **Clock `set_current_utc` accepts any parseable instant** (no monotonicity guard — none stated) and the sweep families run in §2.5 order: credentials, plans, events.
15. **Version starts at 1 at creation and bumps on every mutation** including sweep transitions ("increments by one on every mutation of the resource", §2.4); `School.version` bumps only on the §2.4 whitelist (dues payment, brand update, standing transition, level advance, application create, self-study create, self-study acceptance); audits and CE entries carry no version.
16. **`notes`/`reason` payloads are accepted and ignored** — no entity field stores them.

### PRD contradictions/silences resolved
- §3.5's narrative order (practicum-verified before age-level) vs §2.7's tier order — resolved for §2.7 (item 7).
- §3.7 names dues currency first in the submit narrative but declares "fiscal last" — dues checked at tier 10 after all constraint checks.
- No named error for visit-study belonging, audit-visit belonging, non-ACTIVE classroom lead, or standing-restore-with-open-plans — items 4–6.
- **Dormant rule noted**: §3.3 says `compliance_override` "clears when a valid `ACTIVE` lead of matching age level is (re)assigned to the room", but the API surface has no lead-reassignment endpoint; creation always starts at `NONE`.
- Defensive only (unreachable in a bootstrap-able graph): program accreditation with no ACTIVE catalog → `ERR_NO_ACTIVE_CATALOG`; missing per-level catalog map keys default to 0.

### Storage
Purely in-memory module-level dicts keyed by id; **no seed/preload/hardcoded entities at startup** — every smoke-test entity was built via the API. Fresh boot state: empty store + clock at `2026-09-01T00:00:00Z`, so per-test-server restarts are clean.

Orchestrator verification: 20 .py modules + start.sh + requirements.txt present; independent py_compile OK; independent import shows exactly 61 /society routes; start.sh is foreground `exec python3 app.py` with guarded install, app.py:71 binds 0.0.0.0 on $PORT; no .db/.sqlite/.json data files, no sqlite references; literal drift check (dues tiers/rates, floor/cap, renewal fees, clock start, METHOD_NAME) — zero drift vs PRD; no stray impl server processes.

## Step 7: Run tests and iterate — 2026-10-01T19:08:10.213116472Z

Clean sweep: all 8 rounds pass 87/87 (baseline was 85/88; one test deleted, two test bugs fixed, zero implementation changes). The `results.*.json` deliverables remain in place in `workspace/implementation/`.

Sanity check performed: confirmed all 8 `results.${i}.json` files exist and each reports `passed == total == 87` with zero failures — no flakiness across rounds.

**Summary**
- Iterations run: 2 (baseline sweep → fixes → final clean 8-round sweep).
- Tests deleted: 1
  - `test_05_programs_learners_credential_issuance.py::test_duplicate_credential_for_same_learner_and_level_rejected` — ERROR-PRECEDENCE/unique-derivability failure. PRD §2.7's contractual ten-tier ordering ("first failing tier determines the response") puts the learner-state gate (`ERR_PRACTICUM_NOT_VERIFIED`, tier 6) ahead of the tier-9 uniqueness gate (`ERR_DUPLICATE_CREDENTIAL`), and §3.5's issuance sentence lists the practicum gate first; §3.4 makes `CREDENTIALED` terminal, so a duplicate attempt on an already-credentialed learner can only ever trip the practicum gate under a PRD-faithful implementation. The scaffold's priority-9 prose (which lists the duplicate check before the practicum gate) drove the test's generation — a design-index-vs-PRD ordering drift.
- Fixes applied to `test_suite/`:
  - `test_01_school_onboarding_brand_and_classrooms.py::test_classrooms_list_paginates_with_total_count_and_has_more` — page-2 query combined `offset=2` with an `age_level=ELEMENTARY_I` filter while expecting 1 row, contradicting PRD §2.3's plain reading (offset skips items of the filtered list; the filtered set has 1 item). Split per the design's own `distinguishing_aspect`: offset=2 page with only the `school_id` filter (asserts 1 row = P3, `total_count==3`, `has_more==false`), plus a separate `age_level`-filtered query at default offset (asserts 1 row, `total_count==1`, `has_more==false`), preserving filter-scopes-the-count coverage.
  - `test_08_ce_ledger_and_renewal.py::test_pd_attendance_requires_completed_event_and_no_duplicates` — the two direct `api.record_event_attendance` calls omitted `headers`, failing tier-1 authentication (`ERR_UNAUTHENTICATED`) before reaching the PRD §3.5 gates under test; added `headers=SOCIETY_ADMIN` to both and imported `SOCIETY_ADMIN`.
- Fixes applied to `test_helpers/`: none — the `SOCIETY_ADMIN` header constant and the `record_attendance` fixture were already correct; the bug was only in the test function's raw client calls.
- Fixes applied to `implementation/`: none — the implementation was PRD-faithful in all three cases (standard filter→sort→paginate with `total_count` over the filtered set; §2.7 tier-ordered credential gates; tier-1 auth before state checks).

result: task_3392 sweep clean — 87/87 passing in all 8 parallel rounds after deleting 1 non-derivable test (duplicate-credential precedence contradicts PRD §2.7 tier order) and fixing 2 test bugs (pagination filter/offset semantics in test_01, missing SocietyAdmin auth headers in test_08); no implementation changes needed.

Orchestrator verification: all 8 results.{1..8}.json present and each reports passed==total==87, failed==0; pytest --collect-only now collects exactly 87 tests (consistent with 1 deletion); deleted test confirmed absent from test_suite/; test_08 SOCIETY_ADMIN header fix confirmed in place (import + 2 call sites); newest impl SOURCE mtime 18:38 predates oldest sweep results file 19:06 — no post-sweep impl writes.

## Step 8: Finalize PRD — 2026-10-01T19:20:10.385889029Z

Sanity check passed: the diff contains exactly the two intended in-place revisions, nothing else; both files remain 340 lines.

## Summary

**Line counts:** PRD.md 340 lines, PRD_FINALIZED.md 340 lines — 0% line-count delta; exactly 2 existing lines revised in place (no sections added, no lines inserted or removed).

**Changes (one bullet per change):**
- §3.5 (Credentials issuance, line 168) — revise — restates the issuance sentence as a fixed gate order matching the implementation (`age_level` equality → `ERR_AGE_LEVEL_MISMATCH`; learner `PRACTICUM_COMPLETE` → `ERR_PRACTICUM_NOT_VERIFIED`; program `ACCREDITED` → `ERR_PROGRAM_NOT_ACCREDITED`; duplicate `ACTIVE`/`LAPSED` credential → `ERR_DUPLICATE_CREDENTIAL`, first failure wins) and adds that a repeat issuance for the same learner and level trips the practicum gate, never the duplicate check — workspace/implementation/routes_credentials.py:84-100,118
- §2.3 (Pagination, line 74) — revise — pins that filtering applies first, then the `created_at` sort, then `offset`/`limit` slice the filtered list; `total_count` is the filtered set's size before slicing and `has_more` reports whether the filtered set holds items beyond the page — workspace/implementation/envelope.py:62-77, workspace/implementation/routes_classrooms.py:125-136

**Step 7 item disposition:** the deleted duplicate-credential test and the pagination test fix each produced one edit above; the attendance-headers fix was a pure test bug — `record_attendance` (routes_events.py:95-98) always required authentication plus the `SocietyAdmin` role, which PRD §2.1, §3.5 and the §4 table already pin, so no edit was made for it.

**Per-edit pre-edit search log:**
1. Edit §3.5 issuance gate order — (a) subject: error precedence among credential-issuance gates. (b) enumerated paths: `issue_credential` (routes_credentials.py:64-120, the only issuance path and only raiser of `ERR_PRACTICUM_NOT_VERIFIED`/`ERR_DUPLICATE_CREDENTIAL`); all learner-status writers via grep — routes_placements.py:163-164 (`ENROLLED`→`IN_PRACTICUM`), 241-242 (`IN_PRACTICUM`→`PRACTICUM_COMPLETE`), routes_credentials.py:118 (→`CREDENTIALED`, no path back, matching §3.4's "terminal state"); errors.py:40,62 (error definitions). (c) wording adjustment: ordered the gates exactly as implemented — `age_level` first — rather than keeping the original sentence's practicum-first listing, because impl line 84 runs the age-level check before line 88's practicum check; scoped the repeat-attempt claim to "same learner and level" so it stays true when the age-level gate legitimately fires first on a mismatched-level attempt; kept the claim endpoint-scoped ("the issuance gates") so §2.7's tier taxonomy is untouched.
2. Edit §2.3 pagination semantics — (a) subject: filter/sort/offset ordering and `total_count`/`has_more` definitions. (b) enumerated paths: `paginate`/`pagination_params`/`list_response` (envelope.py:41-77) plus a grep across all twelve list endpoints — classrooms, audits, credentials, applications, placements, CE entries, plans, learners, self-studies, schools, visits, and the public directory (routes_schools.py:219-230) — every one filters first, sorts by `(created_at, _seq)`, then paginates the filtered list with `total_count = len(filtered)`. (c) wording adjustment: none needed after enumeration; phrased as "filtering comes first, then the `created_at` sort" (referencing the existing sort sentence) and defined `has_more` as "items beyond the returned page", which matches `offset + len(page) < total` including the empty-page edge case, and covers the directory endpoint whose visibility predicate acts as its filter.

Output file: workspace/PRD_FINALIZED.md

result: PRD_FINALIZED.md written with 2 targeted revisions — §3.5 pins the credential-issuance gate order (age-level → practicum → program → duplicate, so repeat issuance fails ERR_PRACTICUM_NOT_VERIFIED) and §2.3 pins filter-then-sort-then-paginate with filtered-set total_count/has_more; the attendance-auth Step 7 fix needed no PRD change.

Orchestrator verification: independent diff confirms exactly two in-place revisions (line 74 pagination semantics, line 168 issuance gate order) and nothing else; both files 340 lines.

## Step 9: Complete PRD — 2026-10-01T19:49:18.387362608Z

All checks pass: 340 lines in both files (every edit is an in-paragraph insert/revision), 23 changed lines, +4818 chars. PRD_COMPLETED.md is written at the target path.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 340 lines / 63,065 chars → `PRD_COMPLETED.md` 340 lines / 67,883 chars (char-delta **+4,818**; 23 paragraphs touched, zero sections added, zero paragraphs added — all pins are inline sentence inserts/revisions).

**Counts:** 27 ambiguity-pins, 2 mismatch-revisions.

**Change log** (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl source}`):

- §2.1 — insert — ambiguity — entity-backed ownership gates mutating endpoints only; reads enforce role authorization alone — all routes_*.py GET handlers (no ownership check on any read)
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (into [1,100], ≥0), non-integer values fail `ERR_VALIDATION` (400) — envelope.py:41-59
- §2.5 — insert — ambiguity — `current_utc` echoes the supplied `to_iso8601` verbatim; bare date = midnight UTC; missing/unparseable → `ERR_VALIDATION` (400); no monotonicity check — routes_clock.py:19-26
- §2.5 — insert — ambiguity — one sweep can carry a credential `ACTIVE`→`LAPSED`→`EXPIRED`; grace read from the catalog ACTIVE at sweep time — cascade.py:91-105
- §2.7 — revise — ambiguity — Tier-3 body-FK list extended with `program_id` and `lead_credential_id` — routes_programs.py:139-145, routes_classrooms.py:70-76
- §2.9 — insert — ambiguity — supplied CE hour values (`ce_hours`, `hours_earned`) rounded half-up to 1dp when stored — routes_events.py:43-45,80,136-137
- §2.9 — insert — ambiguity — calendar-month arithmetic clamps day to target month end — store.py:112-124
- §3.1 — insert — ambiguity — catalog book fields required but maps get no per-key validation and numerics no ranges; missing level lookups read zero — routes_catalogs.py:60-71, routes_classrooms.py:271-291, routes_programs.py:116-119, routes_placements.py:156
- §3.2 — insert — ambiguity — brand update omitting `descriptor` clears it to null — routes_schools.py:145,154
- §3.2 — insert — ambiguity — dues payment is not a readable resource; endpoint answers 201 with the updated school — routes_schools.py:159-173
- §3.3 — insert — ambiguity — non-`ACTIVE` lead credential fails `ERR_INVALID_STATE` (409) — routes_classrooms.py:94-96
- §3.3 — revise — **mismatch** — PRD said the override "clears when a valid ACTIVE lead is (re)assigned"; no reassignment endpoint exists, so the override persists once set — grep confirms only routes_credentials.py:209 writes it
- §3.4 — insert — ambiguity — program registration per-level maps must key on age levels with non-negative integer values (`ERR_VALIDATION` 400) — routes_programs.py:54-63
- §3.4 — insert — ambiguity — `PROVISIONAL`→`ACCREDITED` with no ACTIVE catalog fails `ERR_NO_ACTIVE_CATALOG` (422) — routes_programs.py:111-115
- §3.4 — insert — ambiguity — learner status never moves backward: placement create/verify for a learner past the source state leaves status unchanged — routes_placements.py:163-165,241-243
- §3.5 — insert — ambiguity — fifth issuance gate: no ACTIVE catalog → `ERR_NO_ACTIVE_CATALOG` (422), after the duplicate check — routes_credentials.py:101-104
- §3.5 — insert — ambiguity — attendance may be posted for a credential in any status — routes_events.py:95-144 (no credential-status check)
- §3.5 — insert — ambiguity — ROLLING window opens exactly `credential_validity_months` before today, both boundaries inclusive, measured against the read-time ACTIVE catalog — derived.py:169-178
- §3.5 — insert — ambiguity — renewal with no ACTIVE catalog fails `ERR_NO_ACTIVE_CATALOG` (422) immediately after the state check — routes_credentials.py:161-164
- §3.6 — insert — ambiguity — self-study `narrative` required at creation but may be empty; fixed at creation; non-empty enforced only at submission — routes_studies.py:54-57,131-133
- §3.7 — insert — ambiguity — ACCREDITATION submission with no ACTIVE catalog fails `ERR_NO_ACTIVE_CATALOG` (422) ahead of the tenure check — routes_applications.py:184-187
- §3.7 — insert — ambiguity — multiple ACCEPTED studies: the most recently created (created_at, then receipt order) is pinned as `supporting_self_study_id` — routes_applications.py:70-77
- §3.7 — insert — ambiguity — NO_FAIL_IN_CYCLE window opens on the date exactly 12 calendar months before today, inclusive — derived.py:142-145
- §3.7 — revise — ambiguity — approval check order pinned (standing → visit verdict → segregation → dues last); standing and insufficient-verdict failures are `ERR_INVALID_STATE` (409); the supporting visit read is the latest REPORT_FILED on the pinned study — routes_applications.py:267-289
- §3.7 — revise — ambiguity — `APPROVED`/`DENIED` stamp `decided_at` + `reviewer_user_id`; `RETURNED` stamps neither — routes_applications.py:255-264,301-304
- §3.7 — insert — ambiguity — reviewer restore to `GOOD_STANDING` blocked by open plans fails `ERR_OPEN_IMPROVEMENT_PLAN` (409) — routes_schools.py:189-196
- §3.7 — revise — **mismatch** — "Leaving GOOD_STANDING suspends…" → "Entering PROBATION or SUSPENDED suspends…" (impl suspends UNDER_REVIEW apps on PROBATION→SUSPENDED too); revocation auto-denial stamps `decided_at`, leaves `reviewer_user_id` unset — cascade.py:34-58

**Per-module walk checklist:** (app.py, store.py, envelope.py, errors.py, validation.py, derived.py, cascade.py, serializers.py, routes_clock.py, routes_catalogs.py, routes_schools.py, routes_classrooms.py, routes_programs.py, routes_placements.py, routes_credentials.py, routes_applications.py, routes_studies.py, routes_visits.py, routes_plans.py, routes_events.py — all 20 modules walked; behaviors either already PRD-pinned or covered by the edits above.)

result: PRD_COMPLETED.md written at workspace/PRD_COMPLETED.md — 340 lines (unchanged), +4,818 chars over PRD_FINALIZED.md, 23 in-paragraph revisions (27 ambiguity-pins, 2 mismatch-revisions) aligning the PRD to the implementation after an exhaustive walk of all 19 implementation modules and 61 endpoints.

Orchestrator verification: PRD_COMPLETED.md exists (340 lines), diff -q confirms it differs from PRD_FINALIZED.md (not a silent no-op), and the diff touches exactly 23 lines matching the reported change count; impl sources untouched since 18:38 and test sources untouched since the 19:06 sweep, so the clean 8-round sweep remains valid; all 8 results.{1..8}.json still present.

## Final state — 2026-10-01T19:49:18.387362608Z

Pipeline complete. Final tree: SCAFFOLD.yaml (2121 lines) + SCAFFOLD_DIFFICULTY_DESIGN.yaml (1794) + SCAFFOLD_CORNER_DESIGN.yaml (2924); workspace/{INSTRUCTION.md, PRD.md (340), PRD_FINALIZED.md (340), PRD_COMPLETED.md (340)}; test_helpers/ (9 files, 2811 lines, frozen); test_suite/ (conftest + 16 test files, 87 tests after 1 PRD-derivability deletion, 69/69 non-stub design instances covered minus the deleted duplicate-credential precedence instance); workspace/implementation/ (20 modules + start.sh + requirements.txt, 3539 lines, 61 endpoints under /society, in-memory only, no seed data); final 8-round stability sweep: results.{1..8}.json all report 87/87 passed, 0 failed.
