# Worklog — task_3388_low_income_student_college_match_partner_placement

## Step 1: Create Task Directory — 2026-10-01T13:55:00.000Z

Pre-allocated task directory `./tasks/task_3388_low_income_student_college_match_partner_placement/` verified present with `workspace/` inside (per command args — no new index computed, no other task_* directory created). Scenario: Low-Income Student College Match & Partner Placement (QuestBridge). Difficulty instruction for scaffold-generator: "Generate task much harder than expert level!"

## Step 2: Generate Scaffold — 2026-10-01T15:41:00.000Z

All three artifacts are written and pass every check. Summary of what was produced:

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_3388_low_income_student_college_match_partner_placement/`)

- **SCAFFOLD.yaml** (1464 lines) — §1.0–§1.7: 13 entities, 51 endpoints, 24 error codes, 12 calculations, 13 ordered validations, 9 state machines, 2 OCC concurrency rules, 6 roles. Domain: QuestBridge-style match — MatchCycle (9-phase gated pipeline), Student/Counselor/CommunityPartner/Referral (polymorphic referrer), PrepProgram, Application (13-state branching machine with ranking-revision self-loop and release re-entry), RankingEntry (immutable, `common_fields: false`), PartnerCollege (slot quota), Match, AidPackage (PROVISIONAL→FINALIZED↔REVISED cycle), IncomeVerification, OutcomeRecord (stop-out/re-enroll loop). Archetype: quota/allocation + workflow orchestration; layers: OCC, dual-variant calc, cascading side effects, selector policy; segregation-of-duties role model; flat topology; logical clock endpoint with the mandatory `2026-09-01T00:00:00Z` default.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1236 lines) — 9 rules × 2 instances = 18, all differentiated per §0.5 (EFC provisional-vs-verified 340000→453200; persistence 7500bp vs 2500bp; need-aware branch flips regular-pool order 1065>1060 vs 1050<1060; per-component rounding pins grant 900004 vs naive 900005; 4-hop run-match cascade vs 3-hop release cascade; state-vs-temporal and referential-vs-constraint priority pairs; income-cap 6500000/6500001 vs 12/13-rank boundaries; suspended-college skip vs finalize-verification gate; half-open prep intervals vs closed cycle windows; slot conservation 0→1→0 and full-need coverage across revise pairs). Every formula assert is a pre-computed literal.
- **SCAFFOLD_CORNER_DESIGN.yaml** (1685 lines) — 49 active instances + 7 `excluded_because` stubs across all nine guide sections; all 24 error codes have at least one trigger somewhere in §1.8/§1.9.

## Verification

- `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (963 calls scanned)
- Additional checks I ran beyond lint (it doesn't cover them): placeholder closure — caught and fixed one unbound `${col}` (a reused `*rank1` anchor in `application_revision_loop_and_release_reentry`); error-reference coverage (all 24 referenced); enum-value closure (only input-supplied enums flagged, which is correct); instance-name uniqueness across both design files (56 unique); stub→difficulty-instance references all resolve; forbidden concurrency vocabulary absent; file split honored.

## Notes / residual risks

- Endpoint count is 51, above the Expert guideline band (20–32) — deliberate given the "much harder than expert" instruction and the scenario's genuine multi-party surface; per project memory, >40 endpoints can strain Step 6 impl-gen unless the orchestration prompt pre-constrains it (one file per message, per-domain modules).
- Two YAML tooling incidents were repaired in place: unquoted `$.data[N]` captures and `errors[...]`/`{id}` tokens in flow-style `grounds:` lists break YAML flow parsing (fixed via targeted sed), and two heredoc appends left a stray `YAML_EOF` line in the file (detected by parse failure, removed, re-verified). All files now parse with `yaml.safe_load` and anchors resolve correctly.

Orchestrator verification: all three files exist (78K/62K/79K), parse with `yaml.safe_load`, and carry the correct top-level keys.

## Step 3: Copy Shared Files — 2026-10-01T15:42:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T16:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3388_low_income_student_college_match_partner_placement/workspace/PRD.md` (303 lines). The withheld design indices (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

**Document structure** (domain-derived, not template-copied):
- §1: two paragraphs (undermatching problem → pipeline scope)
- §2.1 RBAC with all six role identities translated (incl. `CollegeOfficer` → `X-User-ID` = `PartnerCollege.id`); §2.2 emitted byte-identical to the canonical source (verified by diff); §2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending); §2.4 logical clock (default `2026-09-01T00:00:00Z`, `to_iso8601`/`current_utc`); §2.5 common properties (incl. `RankingEntry` carrying only `id`/`created_at`); §2.6 integer-cents + pinned round-half-up; §2.7 nine-phase pipeline with the full phase-gate map; §2.8 the two OCC rules; §2.9 slot conservation; §2.10 the 13-priority validation order
- §3: nine subsections (cycle/college/people setup → referrals+prep → application+eligibility screens → review/ranking/locking → match run → income verification → aid packages → regular decision/release/enrollment → outcome tracking); all 12 calculations rendered as precise prose with constants embedded in dollar terms (e.g. "$65,000 — 6,500,000 cents")
- §4: 51-row, 4-column endpoint table; §5: 24-row, 2-column error catalogue; no audit footer

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints input/query/path params: 76 required, 76 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in prose (§2.10 ordered list + per-site triggers), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation + expected_<parent>_version + ERR_STALE_VERSION/412 all named; no race framing), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed (incl. 4-link run-match and release cascades, checkpoint sibling asymmetry), 0 missing
- calculations[]: 12 checked, 12 fully expressed with constants, precision, and boundary inclusivity, 0 missing
- validations[] conditions: 13 checked, 13 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 51 checked, 51 expressed, 0 missing
- entities[].fields[] structured content: defaults/initials/sources reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (review decisions, ADMIT/DENY, VERIFY/WAIVE, finalize outcomes, loan-policy branches, EFC variants, rate variants, checkpoint moves), 8 with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 484
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: all 24 error IDs appear in §2/§3; all 6 role names and 64 enum/state values present verbatim; no fuzzy/approximating words at any threshold; file ends at §5.

Orchestrator verification: PRD.md = 303 lines; grep for `test_recipe|scaffold_difficulty_design|scaffold_corner_design|Difficulty/|Corner/` → 0 hits (no design-index leakage).

## Step 5a: Generate Test Helpers (Part A of split Step 5) — 2026-10-01T16:30:00.000Z

Part A is complete. Summary follows.

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_3388_low_income_student_college_match_partner_placement/test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `types.py` | 363 | `UserRole` (6 roles) + 20 domain enums + `CYCLE_PHASE_ORDER` + 13 entity TypedDicts + `OutcomeSummary`/`RunMatchResult`. `RankingEntry` TypedDict carries only `id`/`created_at` (+ own fields) — no `updated_at`/`version`, per the PRD's single exception |
| `constants.py` | 197 | All thresholds pinned to PRD-verbatim values + pure calc mirrors (`household_cap_cents`, `efc_provisional_cents`, `efc_verified_cents`, `aid_components`, `academic_index_for`, `need_tier_half_cap_cents`, `priority_score_for`, `discrepancy_outcome`, `rate_bp`, `round_half_up_cents`) |
| `api_errors.py` | 66 | `ApiErrorId` (24 errors) + `HTTP_STATUS_CODES` + `set_error_http_status_map()` registration at import |
| `api_client.py` | 194 | `ApiClient(GenericApiClient)` with exactly **51 endpoint methods** (one per PRD endpoint) + module-level `api_client` instance |
| `assertions.py` | 311 | `assert_{entity}` × 13 + `assert_outcome_summary`/`assert_run_match_result`; invariants `assert_aid_package_balances` (work+loan+grant+efc == coa) and `assert_slot_conservation`; response wrappers `expect_success(resp, expected_status=200, payload=None)`, `expect_created(resp)` (201), `expect_error(resp, error_id)` — all attach URL, payload, and body to failure messages via `describe_response` |
| `factories.py` | 211 | `create_*_payload` per creatable resource (input fields only, computed fields never emitted) + `submit_rankings_payload`, `ranking_entry`, `review_payload`, `regular_decision_payload`, `release_match_payload`, `decide_verification_payload`, `revise_aid_package_payload(expected_aid_package_version, coa_cents=None)`, `checkpoint_payload(to_status, credits_completed=None)`, `close_prep_program_payload`, `set_clock_payload`. Unique student emails via counter |
| `test_users.py` | 81 | `TEST_USERS` dict (keys: `program_admin_headers`, `student_headers`, `counselor_headers`, `partner_staff_headers`, `college_officer_headers`, `anonymous_headers` — the last is role-only, no X-User-ID) + per-instance builders `make_student_headers(student_id)`, `make_counselor_headers(counselor_id)`, `make_partner_staff_headers(partner_id)`, `make_college_officer_headers(college_id)`, `make_program_admin_headers()`, `make_anonymous_headers()` |
| `fixtures.py` | 674 | Step helpers (`set_clock`, `reset_clock`, `create_cycle/college(s)/counselor/community_partner/student/referral/prep_program/application`, `submit_application`, `review_application`, `submit_rankings`, `withdraw_application`, `create_income_verification`, `decide_verification`, `advance_cycle`, `run_match`, `advance_cycle_to_phase` — auto-handles the RANKING→MATCH_RUN clock gate and MATCH_RUN→REGULAR_DECISION run-match gate), lookup helpers (`find_match_for_application`, `find_aid_package_for_match`, `find_aid_packages_for_application`, `list_outcomes_for_cycle`, getters), and composite setups (below) |
| `__init__.py` | 210 | Barrel: framework generics + all of the above |

## Verification output (exact)

```
$ python3 -m py_compile test_helpers/__init__.py test_helpers/types.py test_helpers/api_client.py test_helpers/api_errors.py test_helpers/assertions.py test_helpers/factories.py test_helpers/constants.py test_helpers/test_users.py test_helpers/fixtures.py
FINAL_PY_COMPILE_OK

$ PYTHONPATH=$PWD python3 -c "..."   (import + mirror sanity)
IMPORT_OK
endpoint methods: 51
errors registered: 24
fixture/helper exports: 63
CALC_MIRRORS_OK
```

The mirror sanity block asserted (all passed): EFC provisional 340000 / verified 453200 on the design figures; composition splits 300000/0/7360000 and the pinned per-component rounding 100001/900004 at coa 1000005; academic indexes 1142/985/670; caps 6500000 (size 4) and 5700000 (size 2); half-cap 3250000; discrepancy 10%-exact VERIFIED vs one-cent-over DISCREPANCY; rates 7500/2500/0 bp. No server was started and no ports were touched.

## PRD-vs-scaffold constants

**No discrepancies found.** PRD.md renders every scaffold `calculations[].constants` value identically (prose uses thousand separators — "6,500,000 cents" — for the same integers; rates 0.20/0.12/0.22 appear literally). All values in `constants.py` were grep-verified against PRD.md before writing. No dead constants: every constant has consumers in the two design indices. The canonical Cycle A window literals (`2026-09-01T00:00:00Z` … `2026-10-31T23:59:59Z`) come from the design indices and are PRD-consistent: the app window opens exactly at the PRD's logical-clock default and both bounds are inclusive, so the default clock is inside the window. Prep-program intervals are historical records with no clock-window gate (only the half-open per-student overlap check), so pre-2026-09-01 intervals are legal and used.

## API decisions Part B needs

- **Composite fixture signatures** (all return dicts keyed by entity name, plural keys hold lists):
  - `setup_application_open(cycle_overrides=None)` → `{cycle}` (APPLICATION_OPEN)
  - `setup_draft_application(app_overrides=None, cycle_overrides=None)` → `{cycle, student, application(DRAFT)}`
  - `setup_submitted_application(...)` → adds UNDER_REVIEW app + `application_version`
  - `setup_finalist_application(...)` → cycle in REVIEW, app FINALIST + `application_version`
  - `setup_ranking_submitted(college_count=1, college_overrides=None, app_overrides=None, with_prep=False, with_referral=False, referrer="counselor")` → cycle in RANKING, clock in-window, list accepted; keys `cycle, college, colleges, student, application(RANKING_SUBMITTED), application_version, ranking_entries` (+`counselor`/`partner`/`referral`/`prep_program` when flagged)
  - `setup_matched(college_overrides=None, app_overrides=None, with_referral=False)` → full run through MATCH_RUN; adds `match(BINDING)`, `aid_package(PROVISIONAL, guaranteed_full_need=True)`, `run_match_result`; refreshed `college`/`application`/`cycle`
  - `setup_finalized_package(decision="VERIFY", verification_overrides=None, ...)` → counselor files, unrelated partner decides, officer finalizes; adds `counselor, partner, income_verification, aid_package(FINALIZED), aid_package_version`
  - `setup_released_match(reason=..., **kwargs)` → post-cascade refreshed `match(RELEASED), aid_package(VOID), application(REGULAR_POOL), college, student`
  - `setup_regular_pool_application(...)` → finalist, no ranking, cycle in MATCH_RUN, app REGULAR_POOL
  - `setup_admitted_regular(...)` → cycle REGULAR_DECISION, officer ADMIT; adds `aid_package(PROVISIONAL, guaranteed_full_need=False, match_id=None)`
  - `setup_enrolled_match(**kwargs)` → adds `match(ENROLLED), application(ENROLLED), outcome_record(ENROLLED_Y1)`
  - `setup_matched_students(count, college_overrides=None, app_overrides_list=None)` → N students matched to one N-slot college; `app_overrides_list[i]` controls per-student academic_index ordering; returns `students/applications/matches/aid_packages` lists in creation order
  - `setup_enrolled_matches(count=4, ...)` → all enrolled in REGULAR_DECISION; adds `outcome_records` (creation order)
  - `checkpoint_outcome_record(outcome_id, to_status, college_id=None, credits_completed=None)` — officer headers when `college_id` given, else ProgramAdmin
- **Statuses**: creation endpoints are asserted 201 inside fixtures (strict, via `get_success_data(resp, 201)`); tests should use `expect_created(resp, payload)` for create assertions and `expect_success(resp, 200, payload)` / `expect_error(resp, ApiErrorId.X, payload)` otherwise. HTTP status is auto-checked from the registered map inside `expect_error`. `validate_error_is_one_of` is re-exported for precedence-relaxed cases.
- **Versions**: fixtures capture `application_version` / `aid_package_version` from responses — Part B should use those for OCC tokens rather than assuming counts.
- **Segregation default**: `setup_finalized_package` files via a counselor and decides via an unrelated partner, so the segregation rule is satisfied by construction; for segregation tests Part B should build manually with a partner-filed referral.
- No `test_suite/` or `test_*.py` was created; helpers are frozen for Part B.

Orchestrator verification: all 9 helper files present, `python3 -m py_compile test_helpers/*.py` → COMPILE_OK, spot-grep of `6500000|340000|453200|2026-09-01` hits both `test_helpers/constants.py` and `workspace/PRD.md` (values PRD-verbatim), `test_suite/` absent (correct for Part A).

## Step 5b: Generate Test Suite (Part B of split Step 5) — 2026-10-01T17:15:00.000Z

Part B is complete. Final summary:

## Test suite generated — task_3388

**Files (test_suite/, 85 tests total):**
| File | Lines | Tests | Instances covered |
|---|---|---|---|
| `conftest.py` | 19 | — | api + admin/anonymous header fixtures |
| `test_01_registration_envelope_and_listing.py` | 155 | 6 | 6 corner (entities/validations/errors) |
| `test_02_application_creation.py` | 223 | 6 | 4 corner + Difficulty `referential_beats_constraint_on_application_create` ×2 |
| `test_03_submission_eligibility.py` | 181 | 6 | 4 corner + Difficulty `income_exactly_at_cap_eligible_one_cent_over_rejected` ×2 |
| `test_04_review_and_ranking_rules.py` | 275 | 9 | 9 corner (review/rankings/OCC/version counter) |
| `test_05_ranking_boundaries_and_priorities.py` | 158 | 4 | Difficulty `twelfth_rank_accepted_thirteenth_rejected` ×2, `state_error_beats_window_closed_on_rankings` ×2 |
| `test_06_cycle_pipeline_referrals_and_calendars.py` | 254 | 9 | 5 corner + Difficulty both `resource_temporal_overlap` instances ×2 each |
| `test_07_match_run.py` | 319 | 9 | 3 corner + Difficulty `run_match_four_hop_cascade`, `suspended_college_skipped_in_match_run`, `slot_conservation_across_match_and_release` ×2 each |
| `test_08_match_release_and_regular_pool.py` | 311 | 8 | 2 corner + Difficulty `match_release_compensation_cascade`, `application_revision_loop_and_release_reentry`, `priority_score_need_aware_branch_flips_regular_pool_order` ×2 each |
| `test_09_regular_decision_and_enrollment.py` | 175 | 5 | 5 corner |
| `test_10_aid_packages.py` | 460 | 14 | 4 corner + Difficulty `efc_provisional_vs_verified_same_application`, `aid_composition_per_component_rounding`, `finalize_blocked_until_verification_decided`, `aid_package_finalize_revise_finalize_cycle`, `full_need_coverage_survives_revise_pair` ×2 each |
| `test_11_verification_and_rbac.py` | 252 | 7 | 7 corner |
| `test_12_outcome_tracking.py` | 83 | 2 | Difficulty `persistence_on_track_vs_cohort150` ×2 |

**AST tag audit (exact output):**
```
difficulty instances (non-stub): 18
corner instances non-stub: 49  stubs: 7
stub cross-refs broken: none
total test functions: 85
untagged tests: none
dual-tagged tests: none
tests whose Design line is not the last docstring line: none
tags naming non-existent instances: none
tags naming corner STUBS (forbidden): none
difficulty instances with no test: none
corner non-stub instances with no test: none
difficulty instances with < 2 tests: none
tagged tests: 36 difficulty + 49 corner = 85
AUDIT PASS
```

**pytest --collect-only (PYTHONPATH = runner src + task root):** `85 tests collected in 0.26s` — collected count equals tagged-test count; package graph imports cleanly. Additionally, a whitespace-normalized grep check confirmed all 144 quoted PRD citations appear verbatim in `workspace/PRD.md`. No skip/xfail markers anywhere.

**Skip log:** none. All 18 difficulty + 49 non-stub corner instances passed the two-condition filter; all 7 corner stubs verified as pointing at existing difficulty instances and were not translated.

**test_helpers/ fix (one, proven bug):** `fixtures.py` `advance_cycle_to_phase` unconditionally re-ran `run_match` when crossing out of MATCH_RUN — but run-match is once-per-cycle (`ERR_MATCH_ALREADY_RUN` on a completed run), which made the frozen composite fixtures `setup_enrolled_match`, `setup_enrolled_matches`, and `setup_admitted_regular` (all advance MATCH_RUN → REGULAR_DECISION after a completed run) fail in setup, and would have broken the release-re-entry difficulty test. Minimal fix: gate the call on `not cycle.get("match_run_completed")` (the cycle read carries that flag). Behavior unchanged when the run has not yet executed (the lazy-run path `setup_regular_pool_application` relies on still works). No signature or constant changes.

**Notable derivability choices (no skips, but two assertions deliberately scoped):**
- `application_version_increments_on_each_mutation`: the PRD pins "increments by exactly 1 on every mutation" but never states the seed value, so the test asserts relative increments (v_create+1 after submit, +1 after review, +1 after rankings) plus OCC acceptance of the post-review version — not absolute 1/2/3/4.
- `regular_pool_tie_break_uses_created_at`: since every system-assigned timestamp reads the logical clock, the two equal-score applications are created at distinct clock instants (2026-09-01 vs 2026-09-02, both inside the application window) so the created_at tie-break is deterministic under both logical- and wall-clock readings of created_at.
- No server started, no ports hardcoded; all clock movement via `set_clock`/`advance_cycle_to_phase` with the canonical Cycle A windows.

Orchestrator verification: 13 files in test_suite/ (2865 lines total); fixtures.py line 187 carries the `match_run_completed` gate; `grep -rn "pytest.mark.skip|xfail" test_suite/` → 0; 67 unique Design tags (18 difficulty + 49 corner), consistent with 85 = 36 + 49 test functions.

## Step 6: Generate Implementation — 2026-10-01T18:10:00.000Z

Done. The implementation is complete, compiles clean, and passed both the required `start.sh` smoke test and a 131-assertion in-process end-to-end run.

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_3388_low_income_student_college_match_partner_placement/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | Guarded pip install, `exec python3 app.py`, foreground |
| requirements.txt | 1 | flask>=3.0,<4.0 |
| app.py | 58 | create_app wiring + envelope error handlers only |
| clock.py | 41 | Logical clock, default 2026-09-01T00:00:00Z, ISO fmt/parse |
| errors.py | 63 | All 24 error IDs with catalog HTTP statuses |
| store.py | 51 | In-memory dicts only; `create`/`touch` (version starts 1, bumps on every mutation incl. cascades) |
| response.py | 57 | `meta`/`response_type`/`data` envelope, pagination meta |
| validation.py | 110 | Priority-1 body validation (types, enums, datetimes), pagination clamping |
| auth.py | 43 | X-User-Role/X-User-ID auth (401), role membership (403) |
| calculations.py | 229 | All 12 calcs with Decimal round-half-up at pinned points + package create/recompute helpers |
| serializers.py | 233 | All 13 entities; `slots_committed`/`enrolled_count` computed on read; RankingEntry gets id+created_at only |
| routes/__init__.py | 35 | Blueprint registration |
| routes/clock_routes.py | 19 | POST /_clock/set_current_utc |
| routes/cycles.py | 243 | create/get/advance (all gates+cascades)/run-match/outcome-summary |
| routes/colleges.py | 135 | CRUD + suspend/reinstate + ranking-entries + regular-pool scoring |
| routes/people.py | 119 | counselors, community-partners, students, student prep list |
| routes/referrals.py | 97 | nominate (polymorphic referrer), revoke, list, get |
| routes/prep.py | 78 | create (half-open overlap), close, get |
| routes/applications.py | 196 | create/list/get/submit (5 screens in global order)/withdraw |
| routes/application_actions.py | 224 | review, rankings POST (OCC) + GET, verifications list, regular-decision, enroll |
| routes/matches.py | 123 | get/list, release (4-link compensation cascade), enroll |
| routes/aid.py | 108 | get/list, revise (OCC), finalize (VERIFIED/WAIVED divergence) |
| routes/verifications.py | 102 | submit, decide (segregation of duties, exact 10% cross-multiplication) |
| routes/outcomes.py | 108 | checkpoint (persistence ladder + re-entry), get, list |

Total 2,483 lines across 22 Python files + start.sh + requirements.txt. All 51 endpoints implemented, no placeholders.

## py_compile

All 22 files compile clean (Python 3.14.4, Flask 3.1.3 present). Final sweep after edits: no failures.

## Smoke test (via `start.sh`, dynamic port)

Port chosen programmatically: **40231**. `PORT=40231 bash start.sh &` (PID 1924714), up after 4 probes, killed exactly that PID.
- `POST /students` (Anonymous) → 201, `student_stage: PROSPECT`, `created_at: 2026-09-01T00:00:00.000Z` (logical clock default)
- `POST /cycles` as Student → 403 `ERR_UNAUTHORIZED`
- `POST /_clock/set_current_utc` (ProgramAdmin) → 200 `{"current_utc": "2026-10-20T08:30:00.000Z"}`; a subsequent college create showed `created_at` reading the new clock
- Zero 500s in the server log

An earlier smoke round also verified 400 (`ERR_INVALID_REQUEST`) and 401 (`ERR_UNAUTHENTICATED`) envelopes. Additionally, a 131-check in-process e2e drove two full cycles through every phase: eligibility screens, referral convert/expire, rankings OCC 412/lock, run-match waterfall with slot conservation, PROVISIONAL/VERIFIED aid math (hand-computed to the cent, invariant `ws+loan+grant+efc==coa` verified), segregation 403s, release cascade, both enroll paths, checkpoint credit rules, and outcome-summary basis points. Two real bugs were found and fixed: a missing `validate` import (500 on review), and superseded ranking rows being deleted when PRD §3.4 requires the per-college listing to expose rows "across all submissions, past and present" (now retained; the application's own list read filters to max `list_seq`).

## Interpretation decisions (Step 8/9 patching candidates)

1. **Ranking OCC order**: PRD §2.10 priority 5 groups `ERR_STALE_VERSION` with state checks, but §3.4's explicit per-endpoint narrative fires it *after* the window check. I followed §3.4: state → phase → window → OCC → college existence → ACTIVE → size → shape. PRD self-contradicts; this is the more specific passage.
2. **Envelope `api_request_timestamp` reads the logical clock** (§2.4 "never the wall clock" for system-assigned timestamps), despite the §2.2 example showing a 2025 date.
3. **`version` starts at 1**; `created_at == updated_at` at creation (PRD never pins the initial value).
4. **Cycle overlap uses UTC calendar-date coverage** ("shares even one date"), stricter than instant-interval overlap; identical for midnight-aligned windows.
5. **`slots_committed`/`enrolled_count` are global and computed on read** — literal §1.1/§2.9 wording has no per-cycle qualifier, though `match_slots` says "per cycle". No college version bump on match/enroll events.
6. **Empty ranking list** → 400 `ERR_INVALID_REQUEST` at body-validation time (before state checks), per the calc note + global priority 1.
7. **GET ownership**: Student 403s on other students' records/applications/matches/packages/outcomes/prep-programs/referrals; CollegeOfficer 403s on other colleges' matches/packages/outcomes/checkpoints/enrolls/ranking-entries/regular-pool; Counselor/PartnerStaff 403 on each other's referrals. List endpoints are role-gated but not owner-filtered. Counselor/CollegeOfficer may GET any single application.
8. **Pagination clamps** (limit→[1,100], offset→≥0); non-integer → 400.
9. **`enrolled_count` in outcome-summary** = count of all outcome records of the cycle (= both denominators).
10. **`credits_completed` applies only on ENROLLED_Y1→PERSISTED_Y2 and PERSISTED_Y2→PERSISTED_Y3**; ignored on GRADUATED/NOT_PERSISTED/STOPPED_OUT/re-enrollment (§3.9 "the two year-to-year persistence advances").
11. **Withdraw from ADMITTED_REGULAR → ERR_INVALID_STATE** (only MATCHED gets `ERR_MATCH_BINDING`).
12. **Cited referral no longer NOMINATED at submit** → conversion silently skipped (no error specified).
13. **Nonexistent college as CollegeOfficer X-User-ID on ADMIT** → `ERR_COLLEGE_INACTIVE` (not ACTIVE); DENY performs no college check.
14. **`last_checkpoint_at` stamped at OutcomeRecord creation**; `academic_index`/`need_tier` null and `prep_alum` false pre-submit.
15. **Ties on equal `created_at`** broken by insertion order via stable sort ("never id" honored); `match_slots >= 0` and `household_size >= 1` enforced as 400s; naive datetimes treated as UTC.

Isolation rule honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, and `test_helpers/` were never opened; the test suite was never run. Only PIDs I started were killed.

Orchestrator verification: 22 .py files + start.sh + requirements.txt present (2472 lines of Python); grep for `rest omitted|similar for other|TODO|FIXME|NotImplemented` → 0 hits; constants grep shows `BASE_CAP_CENTS = 6500000`, `Decimal("0.20")/("0.12")/("0.22")` PRD-verbatim in calculations.py (EFC 340000/453200 are computed fixture values, not literals — no drift at the 6→7 hand-off).

## Step 7: Run Tests and Iterate — 2026-10-01T18:45:00.000Z

All 8 rounds pass 85/85. Clean sweep achieved.

**Summary**

- **Iterations run:** 2 (sweep 1 diagnosed; sweep 2 confirmed clean — 85/85 in all 8 rounds).

- **Tests deleted:** none. Both failing tests assert PRD §3.4 verbatim: "the list must hold at least 1 and at most 12 entries — more than twelve is `ERR_TOO_MANY_RANKS`" — coverage and unique derivability both hold.

- **Fixes applied to `test_helpers/`:** one fix in `/home/ubuntu/github/CodingPRD/tasks/task_3388_low_income_student_college_match_partner_placement/test_helpers/fixtures.py`, helper `get_current_rankings` — it now passes `params={"limit": 100}` on the GET. Root cause: PRD §2.3 states an omitted `limit` defaults to 10, while PRD §3.4 permits ranking lists of up to 12 rows; the helper fetched only the default first page (10 rows), so `test_twelve_rank_entries_accepted` and `test_thirteen_rank_entries_rejected_and_prior_list_intact` saw a truncated list and failed `assert len(rows) == 12`. The fixture, not the implementation, violated the PRD's pagination contract.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on both rules in play — `pagination_params()` defaults `limit` to 10 clamped to [1, 100] (PRD §2.3), and `MAX_RANKS = 12` with the `ERR_TOO_MANY_RANKS` guard at `count > 12` (PRD §3.4, `routes/application_actions.py`).

- The final `results.1.json` … `results.8.json` evidence artifacts remain in `workspace/implementation/` as required.

Orchestrator verification: all 8 on-disk results files show 85/85 with failed: 0; `test_helpers/fixtures.py` line 231 carries the `params={"limit": 100}` fix.

## Step 8: Finalize PRD — 2026-10-01T19:00:00.000Z

Verification complete. Here is the summary.

## Result: zero-edit PRD_FINALIZED.md (byte-identical copy)

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3388_low_income_student_college_match_partner_placement/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 303 lines, PRD_FINALIZED.md = 303 lines, 0% delta (`diff -q` reports identical).

### Changes

None. No insert or revise bullets — there is nothing to patch.

### Why zero edits is the correct outcome

The single `<step_7_diff>` item is a pure `test_helpers/` fixture bug, not an implementation behavior choice. I confirmed both rules in play are already uniquely determined by the PRD and match the implementation verbatim:

1. **PRD §2.3 (line 70)** — "`limit` ... when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. `offset` ... defaults to 0."
   Impl: `workspace/implementation/validation.py:84-109` — `pagination_params()` defaults `limit` to 10 and clamps to [1, 100]; `offset` defaults to 0. The docstring even cites "PRD section 2.3". No PRD silence.

2. **PRD §3.4 (line 166)** — "the list must hold at least 1 and at most 12 entries — more than twelve is `ERR_TOO_MANY_RANKS`".
   Impl: `workspace/implementation/calculations.py:48` (`MAX_RANKS = 12`) and `workspace/implementation/routes/application_actions.py:103-104` (`if count > MAX_RANKS: raise ApiError(ERR_TOO_MANY_RANKS, ...)`). No PRD silence.

The Step 7 failure was that `get_current_rankings` in `test_helpers/fixtures.py:225-232` fetched only the default 10-row page for a list PRD §3.4 allows to hold 12 rows; the fix passes `params={"limit": 100}`. The fixture violated the PRD's pagination contract — the implementation did not. Since the implementation pinned nothing the PRD leaves open, any edit would invent behavior; per the task note, a byte-identical copy is the valid result.

### Pre-edit search log

No edits were committed, so no per-edit (a)/(b)/(c) entries exist. The verification reads performed in place of edit-time searches: PRD §2.3 (lines 68-74) and §3.4 (lines 162-170); impl `validation.py:80-109`, `calculations.py:48`, `routes/application_actions.py:77-119`, `errors.py:22,48`, `response.py:45`; fixture `test_helpers/fixtures.py:225-232`.

Orchestrator verification: `PRD_FINALIZED.md` exists (50494 bytes); `diff -q PRD.md PRD_FINALIZED.md` → byte-identical, consistent with the reported deliberate zero-edit outcome (report contains concrete verification reads, ruling out a killed-mid-flight no-op).

## Step 9: Complete PRD — 2026-10-01T19:45:00.000Z

All edits applied and verified. Final summary:

**Source vs output:** `PRD_FINALIZED.md` 303 lines / 50,494 chars → `PRD_COMPLETED.md` 305 lines / 55,021 chars (Δ +2 lines, +4,527 chars; 16 Edit calls, all in-paragraph inserts/revisions plus one error-catalogue row; no new sections).

**Counts:** 19 ambiguity-pins, 4 mismatch-revisions. All 15 known candidates verified independently against `implementation/`: 12 needed pins, 3 already pinned (candidate 4 — §3.1 "share a single date" plus new §2.4 UTC pin covers it; candidate 6 — §3.4 "empty list is ERR_INVALID_REQUEST" at priority 1; candidate 10 — §3.9 "otherwise simply carries forward").

**Changes** (section — insert|revise — class — what — impl evidence):
- §2.1 — insert — ambiguity — ownership binds on single-resource/per-parent/college-scoped reads; global list endpoints role-gated only, never owner-filtered — routes/referrals.py:79-88, matches.py:35-45, aid.py:40-50, outcomes.py:98-108 vs single-get ownership checks (people.py:103, matches.py:26-32)
- §2.2 — insert — ambiguity — `api_request_timestamp` reads logical clock — response.py:19
- §2.2 — insert — ambiguity — undeclared paths/methods → ERR_NOT_FOUND envelope; unexpected failures → ERR_INTERNAL 500 — app.py:25-50
- §2.3 — insert — ambiguity — limit/offset clamped ([1,100], ≥0); non-integer → ERR_INVALID_REQUEST — validation.py:84-110
- §2.3 — insert — ambiguity — stable created_at tie-break (insertion order) incl. match-run and pool orderings — cycles.py:163, colleges.py:134, response.py:47
- §2.3 — insert — ambiguity — total_count pre-pagination; has_more = offset+page_len < total — response.py:31-48
- §2.4 — insert — ambiguity — naive ISO 8601 inputs interpreted as UTC, offsets normalized — clock.py:29-41
- §2.5 — revise — ambiguity — version starts at 1; updated_at == created_at at creation — store.py:36-43
- §2.7 — insert — ambiguity — advancing CLOSED → ERR_INVALID_STATE — cycles.py:104-105
- §2.9 — insert — ambiguity — slots_committed/enrolled_count computed on read over all cycles; college version/updated_at never move on match/release/enroll — serializers.py:17-25, cycles.py:203-218
- §2.10 p1 — revise — ambiguity — absent body → {}, non-object body → 400, JSON null = absent; match_slots ≥ 0 / household_size ≥ 1 are ERR_INVALID_REQUEST enforced after role authorization — validation.py:21-31,50-59; colleges.py:37-38; applications.py:71-72
- §2.10 p3 — revise — mismatch — endpoint-role at priority 3; entity ownership evaluated after path existence (404 precedes ownership 403) — aid.py:56-58 and uniform endpoint pattern
- §2.10 p5 — revise — mismatch — ranking-submission ERR_STALE_VERSION fires after phase+window (as §3.4 narrates); aid-revision at priority 5 — application_actions.py:86-95 vs aid.py:75-78 (candidate 1)
- §2.10 p6 — revise — mismatch — body-supplied gating cycle must resolve first (404 before phase check) — referrals.py:44-49, verifications.py:47-50, applications.py:74-78
- §3.3 — revise — ambiguity — draft has academic_index/need_tier null, prep_alum false pre-submit — applications.py:105-107 (candidate 14)
- §3.3 — revise — ambiguity — cited referral no longer NOMINATED at submit is skipped silently — applications.py:169-173 (candidate 12)
- §3.3 — insert — ambiguity — withdraw from any other status (incl. ADMITTED_REGULAR) → ERR_INVALID_STATE — applications.py:189-192 (candidate 11)
- §3.8 — insert — ambiguity — regular-pool missing cycle_id → 400; unknown cycle → 404 — colleges.py:114-119
- §3.8 — revise — ambiguity — ADMIT with nonexistent college X-User-ID → ERR_COLLEGE_INACTIVE; DENY performs no college check — application_actions.py:168-177 (candidate 13)
- §3.8 — revise — mismatch — regular-enroll outcome record takes college from package, cycle from application (packages carry no cycle_id) — application_actions.py:198-206
- §3.9 — revise — ambiguity — last_checkpoint_at stamped from logical clock at record creation — application_actions.py:205, matches.py:111 (candidate 14)
- §3.9 — revise — ambiguity — outcome-summary enrolled_count equals the shared denominator — cycles.py:228-243 (candidate 9)
- §5 — insert — ambiguity — ERR_INTERNAL | 500 catalogue row — app.py:40-50

Orchestrator verification: `PRD_COMPLETED.md` = 305 lines (Δ+2 vs PRD_FINALIZED.md, matches report). All implementation source files (excluding `__pycache__`) have mtimes ≤17:58, predating the Step 7 clean sweep (~18:10+) — Steps 8/9 wrote no implementation files, so the 8-round sweep evidence remains valid (no post-sweep impl writes). All 8 `results.{1..8}.json` files still present in `workspace/implementation/`, each 85/85.

## Pipeline Complete — 2026-10-01T19:50:00.000Z

All 9 steps done. Final state: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml (lint-clean); workspace/INSTRUCTION.md; workspace/PRD.md (303 lines); workspace/PRD_FINALIZED.md (byte-identical — Step 7's only fix was a test-side fixture bug); workspace/PRD_COMPLETED.md (305 lines, +19 ambiguity pins / +4 mismatch revisions); test_helpers/ (9 files) + test_suite/ (85 tests, 67 unique Design tags, AST-audit clean); workspace/implementation/ (22 Python files + start.sh + requirements.txt, 51 endpoints); final 8-round per-test-server sweep: 85/85 passed in every round, 0 deletions, 1 test_helpers fix, 0 implementation fixes.
