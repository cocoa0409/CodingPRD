# Worklog — task_3390_grant_competition_host_country_placement_exchange_visitor

## Step 1: Create task directory — 2026-10-01T14:10:27.000Z

Pre-allocated directory ./tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/ verified to exist with workspace/ inside (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate scaffold — 2026-10-01T15:40:14.000Z

All three artifacts are complete, parse cleanly, and pass the official lint with zero violations. 

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/`):
- `SCAFFOLD.yaml` (1369 lines) — §1.0–§1.7 only; no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1897 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (2139 lines) — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **12** (CompetitionCycle, CountryProgram, Applicant, Application, ReviewScore, PlacementRound, Grant, VisaSponsorship, ResidencyLedger, Report, EmergencyIncident, AlumniProfile)
- Endpoints: **39** (under the ~40 cap; includes `POST /_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z)
- State machines: **8** (Application fork-join + promotion loop, PlacementRound cyclic rounds, Grant ACTIVE↔SUSPENDED cycle, ResidencyLedger waiver loop, Report revision cycle, plus Cycle/Visa/Incident)
- Calculations: **10**, all constants concretely valued (quorums, weights, 70.00 threshold, 730 days, DEPENDENT_CAP 2, 25% cap, 30 days/month, strike/engagement points, etc.)
- Validations: 50 ordered rows (auth → authz → existence → OCC → ownership → state → safety → temporal → constraint → referential → fiscal); Errors: 50, catalog closed against all references both directions; Roles: 7 (Applicant entity-backed, 6 opaque); Concurrency rules: 2 (both OCC on Application.version)
- §1.8 instances: **22** (every rule ≥2; combinatorial covers modes a+b+c, boundaries on 3 different metrics/endpoints, cascades from 2 different triggers at depths 3 and 3)
- §1.9 instances: **73** (51 full + 22 `excluded_because` stubs)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1072 calls scanned, exit 0)

**Key design decisions for "harder than expert" within the endpoint cap:** difficulty is concentrated in (1) dual-variant award math where provisional vs final differ via band branch + dependent-cap evaluation order (pinned literals: 4350000 vs 4937500, and 4987500 vs the wrong-order 6187500), (2) round-per-month-then-multiply termination rounding with a nonzero reconciliation adjustment (-1 cent on 1060001), (3) a depth-3 cascade (3rd placement decline → PLACEMENT_FAILED → slot release → auto-promotion by recommend_seq), (4) half-open grant-period vs closed stay-interval overlap semantics on different resources, and (5) two validation priority conflicts (state>fiscal, safety>temporal) plus a pinned p2 rule splitting role-family authz from stage-binding so the state error survives.

**Issues caught and fixed during generation:** a flow-mapping typo, `?`-optional markers needing quotes in YAML flow sequences, path placeholders renamed to `{id}` for the lint's literal sub-resource prefix match, three error ids referenced in validations but missing from the catalog, one unreachable error removed (ERR_QUOTA_BELOW_CONSUMED — quota changes are DRAFT-only while consumption starts later), weighted-score storage pinned to the quorum-th score post so the 69.99 boundary is observable pre-decision, and all arithmetic literals verified by hand against the formulas.

Orchestrator verification: all three files exist on disk, parse cleanly with yaml.safe_load, top-level keys confirmed (SCAFFOLD.yaml has no difficulty/corner keys; the two design files each have exactly their single declared key), and domain grep confirms Fulbright vocabulary (grant/applicant/placement/residency/visa/commission; api_prefix: /exchange).

## Step 3: Copy shared files — 2026-10-01T15:40:34.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-01T16:02:54.000Z

PRD generation complete. All three hard contracts verified mechanically.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/workspace/PRD.md` — 297 lines, ends cleanly on the final error-table row (`ERR_STALE_VERSION`). The withheld design-index files were never opened.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, diff-verified) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Money, Scores, and Precision · 2.7 Validation Order and Error Precedence (11 priorities) · 2.8 Optimistic Concurrency Control · 2.9 Nested Resource Retrieval · 2.10 Cross-Entity Consistency and Cascades
- §3 Business Logic (9 subsections): cycles/programs · registration/submission · scoring/quorums/thresholds · selection/slot accounting · placement rounds · grant terms/dependent cap · visa/orientation/activation · incidents/suspension/completion/termination · reports/residency/alumni
- §4 Endpoint Definitions — 39 rows, 4 columns
- §5 Error Code Catalogue — 50 rows, 2 columns

**Contract 1 — Field-Name Coverage: PASS.** 103 required identifiers (all `entities[].fields[].name`, all endpoint `input`/`query_params`, common fields, envelope fields) — 103 present in backticks, 0 missing. (First checker run false-positived because fenced JSON blocks in §2.2 break naive backtick pairing; stripping fences before extraction fixed the checker, not the PRD.)

**Contract 2 — Rule Coverage: PASS.** All 11 validation priorities expressed as an ordered list with precedence rationale; both OCC rules name the field `expected_application_version`, the guarded writes, and `ERR_STALE_VERSION`/412 in stale-version terms; all 51 state transitions across 8 machines have from/to/precondition/side-effect prose (including the `RESOLVED` terminal state, added after the enum sweep flagged it); all 8 calculations expressed in reconstructible prose with pinned evaluation/rounding orders (weighted score 0.40/0.35/0.25 round-half-up, dependent cap keyed on the allowance-exclusive base, termination reconciliation round-per-month-first, stays closed-interval +1 day, engagement clamp 0–100, alternate promotion `recommend_seq` asc with `created_at` fallback); every `applies_to` scope enumerated (e.g. `ERR_CYCLE_PHASE_FORBIDS` on decisions + program PATCH, `ERR_GRANT_NOT_ACTIVE` split reports-vs-incidents); all 50 error IDs appear in §2/§3 narrative; all 63 enum/state values present.

**Contract 3 — §3 Path Purity: PASS.** 270 backticked tokens in §3 scanned: 0 paths, 0 bare HTTP methods, 0 method+path combos. Endpoints are named via state-pair framing (`PLACEMENT → GRANT_PENDING`), role+verb ("a `ProgramOfficer` confirms the final terms"), or capability description (the clock capability lives in §2.4).

## Step 5a: Generate test helpers (Part 1 of Step 5, frozen helpers) — 2026-10-01T16:23:58.000Z

All checks pass. Part 1 is complete. Summary:

## Files written (all compile + AST-parse; package imports cleanly)

`/home/ubuntu/github/CodingPRD/tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/test_helpers/`:

| File | Lines | Public API surface |
|---|---|---|
| `types.py` | 329 | `UserRole`, `CycleStatus`, `ApplicationStatus` (13 states), `PlacementRoundStatus`, `GrantStatus`, `VisaSponsorshipStatus`, `ResidencyLedgerStatus`, `ReportStatus`, `IncidentStatus`, `ApplicantType`, `LanguageRequirement`, `InstitutionBand`, `ScoreStage`, `ReportType`, `IncidentCategory`, `IncidentOutcome`, `FollowOnEligibility`; TypedDicts for all 12 entities. `ReviewScore` correctly omits `updated_at`/`version` (PRD §2.5 exception); all others carry id+created_at+updated_at+version |
| `api_errors.py` | 132 | `ApiErrorId` (all 45 catalog IDs), `HTTP_STATUS_CODES` (401/403/404/400/409/422/412 per PRD §5), registered with `set_error_http_status_map` at import |
| `api_client.py` | 249 | `ApiClient(GenericApiClient)` + `api_client` singleton; one method per endpoint: `set_clock`, cycle CRUD/transition, country-program create/get/list/patch, applicant create/get, application create/get/list/patch/transition, `post_score`/`list_scores`, placement-round create/list/transition, `list_application_grants`/`confirm_grant`/`get_grant`/`transition_grant`, visa create/get/list, ledger list/get/`add_residency_stay`/transition, report create/list/transition, incident create/list/resolve, both alumni-profile listings |
| `constants.py` | 96 | Every literal grep-verified against PRD prose: `LOGICAL_CLOCK_START=2026-09-01T00:00:00Z`, quorums (2/2), weights (0.40/0.35/0.25), `RECOMMEND_SCORE_THRESHOLD=70.00`, `MIN_AVG_FEASIBILITY=50`, language gates 80/60, `DEPENDENT_CAP=2`, `DEP_CAP_PCT_OF_BASE=0.25`, `DAYS_PER_MONTH=30`, `RESIDENCY_REQUIRED_DAYS=730`, `INTERIM_REPORT_DUE_MONTHS=4`, `FINAL_REPORT_DUE_DAYS=30`, `MAX_COMPLIANCE_STRIKES=2`, engagement 50/10/20, `MAX_PLACEMENT_ROUNDS=3`, `SLOT_CONSUMING_STATES`, `EV-` prefix + canonical base-pipeline dates (all ≥ clock start) |
| `factories.py` | 257 | One factory per creatable entity, input fields only: `create_cycle_payload`, `cycle_transition_payload`, `create_country_program_payload`, `patch_country_program_payload`, `create_applicant_payload` (uuid-unique emails), `create_enrolled_applicant_payload`, `create_application_payload`, `patch_application_payload` (OCC field mandatory), `application_transition_payload`, `create_score_payload`, `create_placement_round_payload` (OCC), `placement_round_transition_payload`, `confirm_grant_payload`, `grant_transition_payload`, `create_visa_sponsorship_payload`, `create_stay_payload`, `residency_transition_payload`, `create_report_payload`, `report_transition_payload`, `create_incident_payload`, `resolve_incident_payload` |
| `assertions.py` | 323 | `assert_{cycle,country_program,applicant,application,review_score,placement_round,grant,visa_sponsorship,residency_ledger,report,incident,alumni_profile}` + invariants `assert_slot_conservation`, `assert_award_conservation`, `assert_engagement_index_bounds`. `assert_review_score` asserts `updated_at`/`version` are **absent**; ledger assertion verifies accrued_days == sum(stay day_counts); visa assertion checks the `EV-`+6-digit format |
| `test_users.py` | 73 | `TEST_USERS` (9 entries: admin, officer `po-1`, host `hc-1`, two national reviewers `nr-1`/`nr-2`, two campus reviewers `cr-1`/`cr-2`, anonymous, plus an applicant fallback marked non-ownership-only) + builders: `make_applicant_headers(user_id)` (entity-backed, mandatory for ownership-gated calls), `make_{platform_admin,program_officer,host_commission,national_reviewer,campus_reviewer,anonymous}_headers` |
| `fixtures.py` | 791 | ~70 helpers, all using `get_success_data` with named-step "Setup failed" errors, all Applicant-role calls threaded through `make_applicant_headers(applicant["id"])` |
| `__init__.py` | 39 | Barrel: framework generics + all PRD-specific modules |

`/home/ubuntu/github/CodingPRD/tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/test_suite/conftest.py` (117 lines, the ONLY file in test_suite/): session-scoped `api` fixture, 9 role-header fixtures, 7 `make_*_headers_factory` fixtures.

## Fixture tiers available to Part 2

- **Primitives**: `set_clock_to`, `create_cycle`, `add_country_program`, `open/close/begin_screening/finalize_awards/complete_cycle`, `register_applicant`, `register_enrolled_applicant`, `create_draft_application`, `submit/withdraw/decline_application`, `post_national_score`/`post_campus_score` (explicit reviewer_id), `post_{national,campus}_quorum_scores` (distinct-reviewer pairs, per-reviewer score override via `scores=(a,b)`), `endorse_application`, `recommend_application`, `host_decide`, `get_application_grant`, `open_placement_round` (auto-fetches current version when OCC value not passed), `accept/decline/expire_placement_round`, `confirm_grant`, `issue_visa_sponsorship` (auto-advances clock past orientation), `get_visa_ledger`, `activate_grant` (auto-advances clock to start_date), `submit_report`, `accept_report`, `request_report_revision`, `resubmit_report`, `declare_incident`, `resolve_incident`, `add_residency_stay`, `request_residency_waiver`, `decide_residency_waiver`, `get_alumni_profiles`
- **Composites** (return dict bundles keyed `cycle`/`program`/`applicant`/`application`/`grant`/`round`/`visa`/`ledger`/`report`/`profile`, pair variant adds `applicant_b`/`application_b`): `setup_open_cycle`, `setup_draft_application`, `setup_submitted_application`, `setup_application_in_national_screening` (walks the enrolled campus leg when asked), `setup_application_in_host_review` (closes cycle first so host decisions are phase-legal), `setup_host_review_pair` (two recommended applications, recommend_seq 1/2), `setup_selected_application`, `setup_grant_pending(band=...)`, `setup_confirmed_grant`, `setup_active_grant(subject_to_home_residency=...)`, `setup_suspended_grant`, `setup_completed_grant`, `setup_accruing_ledger`, `setup_terminated_grant` (default clock 40 days in → 1 served month)
- **Expected-value calculators** (verified against every design-index literal: 4350000 / 4937500 / 3850000 / 4987500 / 353334+706668-1 / 69.99-vs-70.00): `expected_provisional_total`, `expected_final_total` (integer-exact pinned cap order), `expected_termination_split` (round-per-month-first), `expected_weighted_score`, `expected_duration_months`, `round_half_up_div`, `round_half_up_2dp`

## Clock-rule compliance

All fixture dates are reachable from the 2026-09-01T00:00:00Z pinned start: creation/submission/scoring/selection/placement/confirmation run at the default clock; the clock is advanced via `POST /_clock/set_current_utc` to 2027-06-15 (visa), start_date (activate), 2027-11-01 (suspend), 2027-10-11 (terminate), end_date (FINAL report + complete). No hardcoded date precedes the epoch start.

Confirmed: no `test_*.py` files written, no server started, no `implementation/` created.

Orchestrator verification: all 9 helper files + conftest.py compile; api_errors.py contains exactly the 50 PRD §5 error IDs (the "45" in the subagent's own table was a miscount — the artifact is correct); constants.py spot-checked against PRD literals (clock start 2026-09-01T00:00:00Z, 70.00 inclusive, 730 inclusive, weights, DEPENDENT_CAP 2, 0.25 cap — all verbatim in PRD); design-index worked literals (4350000 etc.) correctly absent from PRD and handled via expected-value calculators on the test side.

## Step 5b: Generate test suite (Part 2 of Step 5) — 2026-10-01T17:17:21.000Z

Everything is clean. The suite is complete and verified.

## Summary

**Task:** Stage 2 test generation for `task_3390_grant_competition_host_country_placement_exchange_visitor` — 17 test files, 95 tests, all collected cleanly.

### Test files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/test_suite/`)

| File | Tests | Content |
|---|---|---|
| test_01_cycles_and_programs.py | 6 | cycle/program creation, OPEN/FINALIZE preconditions, program PATCH freeze |
| test_02_applicants_and_registration.py | 5 | enrolled-institution requirement, duplicate email, unknown-field create, application 404, follow-on without history |
| test_03_submission_gates.py | 6 | draft-cycle create block, withdrawn lockout, deadline, duplicate-on-submit, + submit_requires_cycle_open ×2 |
| test_04_review_scoring.py | 9 | score system fields, duplicate score, campus quorum, invalid outcome, stage segregation, weighted 74.25, PROFICIENT gate, + fork/join ×2 |
| test_05_host_selection_and_slots.py | 9 | immediate consistency, + threshold-70 ×2, zero-slots ×2, slot conservation ×2, state>fiscal priority ×2 |
| test_06_placement_rounds.py | 10 | offer expiry, expire timing, single-open-round, double response, + cyclic renegotiation ×2, confirm-needs-placement ×2, exhaustion cascade ×2 |
| test_07_grant_award_terms.py | 10 | confirm 422, start-in-past, + provisional/final divergence ×2, band/duration combinatorics ×2, dep-cap order ×2, half-open overlap ×2 |
| test_08_visa_and_activation.py | 6 | duplicate visa, early activate, + visa-needs-CONFIRMED ×2, orientation>temporal priority ×2 |
| test_09_incidents_and_suspension.py | 4 | incident on CONFIRMED, second open incident, + suspension cycle ×2 |
| test_10_reports.py | 3 | FINAL window, duplicate INTERIM, lateness boundaries |
| test_11_completion_and_termination.py | 8 | completion gates ×2, + termination rounding ×2, termination cascade ×2, award conservation ×2 |
| test_12_residency.py | 8 | accrual-start gate, PENDING gate, waiver deny/approve, + 729/730 boundary ×2, closed-interval overlap ×2 |
| test_13_alumni_engagement.py | 4 | + provisional/certified divergence ×2, follow-on eligible path, two-strikes ineligibility |
| test_14_authz_and_ownership.py | 3 | missing headers 401, applicant-DECIDE 403, foreign PATCH 403 |
| test_15_optimistic_concurrency.py | 2 | stale PATCH 412, stale round-create 412 |
| test_16_application_listing.py | 1 | pagination + filters |
| test_17_not_found_family.py | 1 | nine entity-specific 404 probes |

### Tag audit (real AST parse, diffed against both YAMLs)
- Queue A (Difficulty): 22 instances, **44 tests emitted, 0 shortfalls** (every instance ≥2 tests)
- Queue B (Corner): 51 non-stub instances, **51 tests emitted, 0 shortfalls**; 22 `excluded_because` stubs correctly not translated (all cross-references resolve)
- **Skipped instances: none** — every non-stub instance passed the PRD-first two-condition filter
- Dangling tags (non-existent instance): **0**; dual-tagged/untagged/misplaced Design lines: **0**
- Citation audit: 138 quoted PRD spans across all docstrings — **all verbatim in PRD.md** (whitespace-normalized)

### Collection
`python3 -m pytest test_suite/ --collect-only -q` → **95 tests collected, 0 errors**.

### Helper workarounds / judgment calls (no helper files modified)
1. **Visa-on-PROVISIONAL test:** the design recipe pairs `orientation_completed_at: 2027-06-01` with the default clock 2026-09-01 — but PRD §2.7 puts structural validation (priority 9, "orientation not in the future") ahead of the referential phase check (priority 10, `ERR_GRANT_NOT_CONFIRMED`), so the recipe as written would produce `ERR_VALIDATION`. I used `orientation_completed_at: 2026-08-01` (past at the default clock) so the targeted gate is the one that fires.
2. **Decimal scores (69.98 / 71.5):** PRD §3.3 says "integer from 0 to 100" but §2.6 explicitly states "Screening scores and their averages are decimal numbers carried to exactly 2 decimal places" — I followed §2.6 (the global precision spec) and kept the design's decimal literals.
3. **`version == 1` on freshly created resources** (cycle create, rejected program PATCH): PRD §2.5 pins the increment but not the initial value; I kept the design's literal 1, anchored by the OCC examples.
4. **`post_national_score(score=..., language_score=...)` kwargs collision** (would pass `language_score` twice): the language-gate test posts via `api.post_score` + `create_score_payload` directly instead.
5. Timestamp assertions compare parsed instants (tolerant of `Z` vs `+00:00` vs fractional-digit formatting), since PRD does not pin the serializer's exact string format; all asserted *values* are the design's literals.

Orchestrator independent verification: `pytest --collect-only -q` → 95 tests, 0 errors; own AST tag audit → 95 tests all singly-tagged, all 22 queue-A instances covered with ≥2 tests each, all 51 queue-B non-stub instances covered, zero dangling tags, zero uncovered instances.

## Step 6: Generate implementation — 2026-10-01T18:09:38.000Z

Implementation complete and verified. Summary:

## Files written (all in `/home/ubuntu/github/CodingPRD/tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Executable launcher: guarded `pip install` (no-op when flask present), `exec python3 app.py`, `$PORT` (default 10000), binds 0.0.0.0 |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 55 | Entry point, blueprint registration, ApiError/HTTPException handlers |
| `constants.py` | 82 | Every PRD constant with exact value (quorums 2/2, weights 0.40/0.35/0.25, threshold 70.00, MIN_AVG_FEASIBILITY 50, language gates 80/60, DEPENDENT_CAP 2, DEP_CAP_PCT_OF_BASE 0.25, DAYS_PER_MONTH 30, RESIDENCY_REQUIRED_DAYS 730, INTERIM 4 months, FINAL 30 days, MAX_COMPLIANCE_STRIKES 2, engagement 50/10/20, MAX_PLACEMENT_ROUNDS 3) |
| `timeutil.py` | 41 | ISO8601 parse/format (3-fractional-digit Z), day-clamped `add_months` |
| `errors.py` | 9 | `ApiError(error_id, http_status, message)` |
| `store.py` | 72 | In-memory dicts only; logical clock default exactly `2026-09-01T00:00:00Z`; `stamp_new`/`bump` (version starts 1, +1 per mutation incl. cascades); zero seeding |
| `envelope.py` | 52 | PRD 2.2 envelope: `meta{api_request_id, api_request_timestamp}`, `response_type` object/array/error, `data{error_id,message}`; pagination fields in meta |
| `validate.py` | 118 | Required/unknown fields, types, enums, 0–100 integer scores, datetimes, OCC version type, pagination (limit 1–100 default 10, offset ≥ 0) |
| `auth.py` | 46 | Priority-1 header auth (7 roles), priority-2 role admission, priority-5 Applicant ownership |
| `domain.py` | 440 | Slot accounting (live aggregation), provisional/final award terms with pinned cap order, weighted score (round-half-up 2dp per average then sum), alternate auto-promotion (recommend_seq asc), termination reconciliation (round-per-month-then-multiply, adjustment = remainder), suspension extension, completion/termination cascades, alumni engagement indices recomputed on read |
| `serialize.py` | 62 | Entity serializers; computed `slots_remaining` and live alumni fields |
| `routes_clock.py` | 21 | `POST /_clock/set_current_utc` |
| `routes_cycles.py` | 238 | Cycles + country programs (5 endpoints) |
| `routes_applicants.py` | 92 | Registration + read + alumni-by-applicant (3) |
| `routes_applications.py` | 527 | Application CRUD/transition/scores (7) |
| `routes_rounds.py` | 171 | Placement rounds (3) |
| `routes_grants.py` | 204 | Grants, confirmation, transition, alumni-by-grant (5) |
| `routes_visa.py` | 248 | Visa sponsorships + residency ledgers/stays/waivers (7) |
| `routes_reports.py` | 166 | Reports (3) |
| `routes_incidents.py` | 115 | Incidents (3) |

**All 39 endpoints implemented** per the scaffold table (1 clock + 38 `/exchange/*`).

## Self-smoke-test evidence (three fresh boots, each on a dynamic port, each killed by exact saved PID)
- Boot + cycle create 201 (envelope `{meta, response_type:"object", data}`, status DRAFT, created_at `2026-09-01T00:00:00.000Z` from logical clock) → clock set 200 → program create 201 (`slots_remaining: 2`) → OPEN → applicant 201 → application 201 DRAFT → missing headers → 401 `ERR_UNAUTHENTICATED`.
- Deep lifecycle: INDEPENDENT submit → NATIONAL_SCREENING; two scores (90/90/90, 80/80/80) → `national_weighted_score` 85.0 stored; RECOMMEND → HOST_REVIEW seq 1; SELECT → PROVISIONAL grant (200000 monthly, total 2715000 with dependents=3 capped at 2); `slots_remaining` 0; round OCC-guarded open → ACCEPT → GRANT_PENDING; confirmation HIGH band → `final_total_cents` 3435000 (cap 723750 not binding over dep_raw 540000 — verified formula order); visa `EV-000001` + ledger PENDING/730; ACTIVATE → interim due 2027-05-15, final due 2027-11-14; TERMINATE at day 90/270 → rate 381667, earned 1145001, repayment 2290002, adjustment −3 (conservation exact); alumni profile INELIGIBLE (terminated early), residency ACCRUING.
- Edge suite: enrolled fork CAMPUS_REVIEW, stale OCC → 412 before state-409 (priority order), stage-segregation 403, quota exhausted → `ERR_COUNTRY_QUOTA_EXHAUSTED`, DECLINE → auto-promotion of lowest-seq ALTERNATE with grant + slot re-consumed, `ERR_RESIDENCY_NOT_ACCRUING`, `ERR_FINAL_REPORT_MISSING`, completion cascade (visa COMPLETED, ledger ACCRUING from end_date), touching-endpoint stay → `ERR_STAY_OVERLAP`, 732 days → FULFILLED, alumni ELIGIBLE → follow-on create 201 (fresh applicant → `ERR_FOLLOW_ON_INELIGIBLE`), pagination meta shape, `ERR_DEADLINE_PASSED`, FINALIZE_AWARDS sweep DRAFT→WITHDRAWN.

## Interpretation choices (PRD-ambiguous points)
1. **Nonexistent body cross-references** (applicant_id/cycle_id/country_program_id on create, or program not belonging to cycle) → `ERR_VALIDATION` 400, since priority-3 404s apply only to path identifiers.
2. **Missing `action`/`outcome` or unknown `action`** → `ERR_VALIDATION` 400 (PRD p6: "unknown action or outcome … is ERR_VALIDATION instead"); DECIDE with present-but-wrong outcome → `ERR_INVALID_OUTCOME`.
3. **Missing `expected_application_version`** → `ERR_VALIDATION` 400 (field is non-optional per §2.8); type must be integer.
4. **`national_weighted_score` recomputed on every NATIONAL score post once quorum ≥ 2** (not only exactly the quorum-th post), so the stored value always reflects all scores — consistent with both "computed at quorum-th post" and the RECOMMEND-time recomputation side effect; gates use all current NATIONAL scores.
5. **Entity timestamps use the logical clock** (created_at/updated_at/submitted_at/responded_at/opened_at/resolved_at); only `meta.api_request_timestamp` uses wall time (unpredictable to tests either way).
6. **CountryProgram version is not bumped on slot consumption** — `slots_remaining` is a live-computed field, and §2.10 cascade bumps apply to mutated entities; only PATCH bumps the program version (per endpoint side-effects).
7. **Cascaded round DECLINE (from application DECLINE while PLACEMENT) stamps `responded_at`** with the logical clock (field is "clock at ACCEPT/DECLINE"; a cascade decline is a decline).
8. **Applicant-role list of applications silently confines to own records** (PRD: "confined to the caller's own records") rather than 403ing on a foreign `applicant_id` filter; single-resource GETs 403 `ERR_NOT_RESOURCE_OWNER`.
9. **Incident-resolve with outcome=TERMINATE enforces the same clock < end_date guard** as manual TERMINATE (state machine lists the precondition for both triggers) → `ERR_INVALID_STATE` at/past end_date.
10. **Pagination params out of range** (limit <1 or >100, offset <0, non-integer) → `ERR_VALIDATION` 400; all list endpoints paginate uniformly and carry the meta fields, including 0-or-1-entry listings.
11. **Country-program creation allowed in any cycle phase** — PRD restricts only PATCH to DRAFT (`ERR_CYCLE_PHASE_FORBIDS`); no create-phase guard is stated, so none was invented.
12. **No format validation on country/email codes** beyond non-empty string (PRD states no such error condition); negative `dependents_count` rejected as `ERR_VALIDATION`; no min≤max duration-bound guard on programs (not stated).

Orchestrator verification: all 21 files present (start.sh executable, guarded pip install), every .py compiles with py_compile.

## Step 7: Run tests and iterate — 2026-10-01T18:22:57.000Z

Clean 8-round parallel sweep: 95/95 passing in every round. The `results.{1..8}.json` files remain in place in `workspace/implementation/`.

## Summary

- **Iterations run:** 2 (initial sweep + verification sweep after fixes)

- **Tests deleted:** none

- **Fixes applied to `test_helpers/`:** none

- **Fixes applied to `test_suite/`:** 2 tests, both the same bug class — request payloads violated PRD §3.3's verbatim input contract ("carrying `feasibility_score`, `country_fit_score`, and `language_score` — each an integer from 0 to 100, with anything outside that range rejected as `ERR_VALIDATION`"), so the PRD-faithful implementation correctly 400'd the setup/primary requests.
  - `/home/ubuntu/github/CodingPRD/tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/test_suite/test_04_review_scoring.py` — `test_score_post_records_system_fields_without_version`: `feasibility_score=71.5` → `71`, and the echo assertion `== 71.5` → `== 71`. All PRD-covered assertions (stage derivation from application status, `reviewer_id` from `X-User-ID`, §2.5 immutable-score field shape via `assert_review_score`, `application_id`) are unchanged.
  - `/home/ubuntu/github/CodingPRD/tasks/task_3390_grant_competition_host_country_placement_exchange_visitor/test_suite/test_05_host_selection_and_slots.py` — `test_recommend_below_threshold_rejected`: quorum scores `(70, 69.98)` → `(70, 69)`, expected `national_weighted_score` `69.99` → `69.50` (per-axis means 69.50, weighted sum 69.50 — the closest integer-composable step below the inclusive 70.00 threshold), docstring arithmetic updated to match. The `ERR_SCORE_BELOW_THRESHOLD` assertion and status-stays-`NATIONAL_SCREENING` check are unchanged; the impl's threshold-before-language-gate ordering (routes_applications.py:402 before :410) matches PRD's "RECOMMEND then requires… On top of that stands the country language gate" sequencing, so the integer payload isolates the same gate the test was designed for.

- **Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on both failure paths.

- **Note:** final `results.{1..8}.json` files are left in place in `workspace/implementation/` as required output artifacts.

Orchestrator verification: all 8 results.{i}.json files present, each passed=95/total=95/failed=0; newest implementation source (routes_reports.py 18:01) predates the sweep (18:21) — sweep covers final state; the two test-suite edits spot-checked on disk (integer payloads, 69.50 expectation) and match the report.

## Step 8: Finalize PRD — 2026-10-01T18:30:06.000Z

Done. PRD_FINALIZED.md is written with exactly two in-place revisions, both traceable to the Step 7 diff items. Final report:

## Summary

**Line counts / delta:** PRD.md 297 lines → PRD_FINALIZED.md 297 lines (0% line-count delta; 2 of 297 lines revised in place, no sections added or removed).

**Changes:**
- **§2.6 (Money, Scores, and Precision)** — revise — replaced "Screening scores and their averages are decimal numbers carried to exactly 2 decimal places" with wording scoping the 2-decimal round-half-up rule to the *computed* averages and weighted scores, and stating the posted scores themselves are integers per §3.3 — `implementation/domain.py:202-215` (q2 ROUND_HALF_UP per-axis means and weighted sum), `implementation/domain.py:218-224` (stored `national_weighted_score`), `implementation/validate.py:68-76` (raw scores stored as ints), `implementation/serialize.py:31-32` (ints echoed verbatim).
- **§3.3 (Campus and National Review)** — revise — extended the score input contract clause: a non-integer value (fractional number such as 71.5, a boolean, or any non-numeric value) is rejected as `ERR_VALIDATION`, while an integral-valued JSON number such as 71.0 is accepted and stored as its integer value — `implementation/validate.py:68-76` (`as_score`: bool rejected, `float.is_integer()` coerced to int, non-integral/out-of-range/non-numeric rejected), sole callsite `implementation/routes_applications.py:480-482`.

**Step 7 items disposition:** both test fixes (`test_04`'s 71.5→71, `test_05`'s 69.98→69 / 69.99→69.50) were fixture violations of the integer input contract — they reveal the §2.6/§3.3 tension the two edits resolve. The `test_05` ordering note (threshold gate at routes_applications.py:402 before language gate at :410) already matches PRD §3.3's "RECOMMEND then requires… On top of that stands the country language gate" sequencing, so no edit was needed there. No implementation fixes and no deletions occurred, so nothing else required pinning.

**Per-edit pre-edit search log:**
- **Edit 1 (§2.6):** (a) subject: which values the 2-decimal rounding rule applies to. (b) enumerated via grep for `as_score|feasibility_score|country_fit_score|language_score` across impl and `score` across PRD: `validate.py:68-76` (intake coercion), `routes_applications.py:479-514` (only score-intake endpoint + storage), `serialize.py:31-32` (echo), `domain.py:28-34,202-224` (q2 rounding, averages, weighted storage as `float(weighted)`), `routes_applications.py:397-416` (RECOMMEND Decimal comparisons vs 70.00/50/80/60); also verified the adjacent §2.6 sentences (money, durations, engagement indices) are untouched. (c) wording says "averages and weighted scores — the values computed from posted scores" rather than "scores", and claims nothing about JSON serialization format of the weighted score (impl emits 69.5 for 69.50 — numerically equal, PRD never pinned representation), avoiding a new mismatch.
- **Edit 2 (§3.3):** (a) subject: accepted value domain for the three score input fields. (b) enumerated: `validate.py:68-76` is the only score validator, called only from `routes_applications.py:480-482`; `check_unknown` at :479 confines the payload to the three score fields + comment, so no other endpoint accepts these fields; PRD §2.7 priority 9's "scores within 0–100" remains true as a subset of the structural checks; test evidence `test_04` line 67 (`== 71` integer echo) and `test_05` lines 107-112 (69.50 from integer quorum scores). (c) wording explicitly covers all four `as_score` branches — out-of-range (pre-existing clause, kept verbatim), fractional number, boolean (named because Python `bool` subclasses `int`, so a fresh implementer needs the explicit exclusion), non-numeric — plus the integral-float acceptance-and-coercion branch, which a strict reading of "each an integer" alone would have left ambiguous against the impl's actual acceptance of `71.0`.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the two claimed line revisions (86 and 138) and nothing else; both files 297 lines.

## Step 9: Complete PRD — 2026-10-01T18:59:42.000Z

All changes verified — the diff contains exactly the 21 intended edits and nothing else. Work complete.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` (297 lines, 55075 chars) → `workspace/PRD_COMPLETED.md` (299 lines, 59213 chars; **+2 lines, +4103 chars**). No files other than PRD_COMPLETED.md were created or modified.

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions (21 changes total). All edits are in-paragraph inserts/revisions except one continuation sentence appended to the §2.2 error-format block; no new sections.

**Mismatch-revisions:**
- §3.1 — revise — mismatch — program registration was gated "while the cycle is DRAFT"; now states registration is permitted in any cycle phase and only the edit operation is DRAFT-gated — `implementation/routes_cycles.py:168-186` (create_program has no phase check; only patch_program:230-235 does).
- §3.9 — revise — mismatch — FINAL-report window: the "or when the grant has already reached COMPLETED or TERMINATED_EARLY" disjunct now explicitly exempts only the window comparison; the ACTIVE/SUSPENDED filing gate still rejects such filings with `ERR_GRANT_NOT_ACTIVE` — `implementation/routes_reports.py:50-56, 67-73`.

**Ambiguity-pins:**
- §2.2 — insert — ambiguity — unmatched path/method answered in the error envelope with `ERR_NOT_FOUND` (404/405), unexpected faults `ERR_INTERNAL` (500) — `implementation/app.py:38-47`.
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION`; filters exact-match with unmatched values yielding empty pages; `total_count`/`has_more` definitions; `created_at` ties broken by creation order — `implementation/validate.py:94-118`, `implementation/routes_applications.py:178-183`.
- §2.4 — insert — ambiguity — server-stamped entity timestamps (`created_at`, `updated_at`, `submitted_at`, `responded_at`, `opened_at`, `resolved_at`) come from the logical clock; only the envelope's `api_request_timestamp` is wall-clock; clock-set accepts any instant including earlier ones — `implementation/store.py:49-72`, `implementation/envelope.py:20`, `implementation/routes_clock.py:20`.
- §2.7 (priority 3) — insert — ambiguity — body-carried ids (`applicant_id`/`cycle_id`/`country_program_id`) that resolve to nothing are `ERR_VALIDATION` (400) at priority 9, never 404 — `implementation/routes_applications.py:116-122`.
- §2.7 (priority 9) — insert — ambiguity — no format validation beyond non-emptiness on `country_code`/`citizenship_country_code`/`academic_year`; unparseable values rejected as `ERR_VALIDATION` at read time, possibly ahead of the earlier-priority check that consumes them — `implementation/validate.py:37-91`, `implementation/routes_reports.py:46-56`.
- §3.2 — insert — ambiguity — `dependents_count` must be a non-negative integer (`ERR_VALIDATION` otherwise) — `implementation/routes_applications.py:110-112`.
- §3.2 — insert — ambiguity — email uniqueness compared exactly, no case folding — `implementation/routes_applicants.py:56`.
- §3.2 — insert — ambiguity — follow-on "most recent profile by `created_at`" ties broken by creation order, later-created winning — `implementation/domain.py:433-440`.
- §3.3 — insert — ambiguity — each further NATIONAL-stage score after quorum recomputes and re-stores `national_weighted_score`, bumping the application's `version` — `implementation/domain.py:218-224`, `implementation/routes_applications.py:513`.
- §3.3 — insert — ambiguity — DECIDE `rationale` accepted but not persisted — `implementation/routes_applications.py:266` (allowed key, never stored).
- §3.4 — insert — ambiguity — selection/release/promotion never write the program row; its `version`/`updated_at` move only via the edit operation — `implementation/domain.py:95-101, 149-164`.
- §3.5 — insert — ambiguity — round opening not gated on cycle phase; `response_deadline` recorded as supplied with no clock comparison at creation — `implementation/routes_rounds.py:58-72`.
- §3.5 — insert — ambiguity — EXPIRE does not stamp `responded_at` — `implementation/routes_rounds.py:161-170`.
- §3.5 — insert — ambiguity — cascaded decline from PLACEMENT stamps the collapsed round's `responded_at` with the logical clock — `implementation/domain.py:171-176`.
- §3.7 — insert — ambiguity — `sponsor_program_number` is zero-padded six digits starting at EV-000001, +1 per issuance — `implementation/routes_visa.py:65-68`.
- §3.7 — insert — ambiguity — interim due-date month arithmetic clamps day-of-month to the target month's length — `implementation/timeutil.py:35-41`, `implementation/domain.py:277`.
- §3.9 — insert — ambiguity — `revision_note` optional on REQUEST_REVISION; resubmission does not clear it — `implementation/routes_reports.py:146-164`.
- §3.9 — insert — ambiguity — `waiver_reason` optional on REQUEST_WAIVER — `implementation/routes_visa.py:231-234`.
- §3.9 — insert — ambiguity — stay-record endpoint answers 201 with the updated residency ledger (a stay is not separately addressable) — `implementation/routes_visa.py:184-196`.

**Dispositions of the 12 documented interpretation choices:** pinned — body cross-reference 400-vs-404 (400), weighted-score recomputation timing, logical-vs-wall clock, program version untouched by slot consumption, cascaded-decline `responded_at`, pagination validation, program create in any phase (revised), no format validation on codes; left alone (PRD already determines) — missing/unknown action handling (§2.7 p6/p9), OCC field requiredness ("non-optional" in §2.8), applicant list confinement (§3.2), incident-resolve termination guard (§3.8 cascade requirement).

**Areas scanned and found already aligned (no change):** all endpoint paths/roles/status codes vs §4; cycle phase corridor and FINALIZE_AWARDS sweeps; submission fork, deadline inclusivity, duplicate-application state set; score immutability/quorums/thresholds/language gates/`recommend_seq`; slot live-aggregation and conservation; alternate promotion ranking; round OCC/state/expiry gates and 3-round cap; provisional vs final award formulas and the pinned cap-rounding order; visa issuance side effects; activation/completion/termination gates and the early-termination reconciliation math; incident RESUME/TERMINATE cascades; report lateness/strike-once semantics; residency stay arithmetic/overlap/fulfillment at 730; alumni dual engagement indices and follow-on eligibility rule; envelope shape; per-endpoint validation ordering against §2.7 priorities.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (297→299 lines, 38 diff lines consistent with the 21 claimed edits — not a silent no-op); every implementation source file predates the 18:21 clean sweep, so Steps 8/9 did not invalidate it; all 8 results.{i}.json remain in place.
