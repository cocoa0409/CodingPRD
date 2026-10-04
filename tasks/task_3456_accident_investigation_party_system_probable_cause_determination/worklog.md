# Worklog — task_3456_accident_investigation_party_system_probable_cause_determination

## Step 1: Create Task Directory — 2026-10-02T06:44:00.000Z

Pre-allocated task directory `./tasks/task_3456_accident_investigation_party_system_probable_cause_determination/` verified to exist with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-02T08:03:00.000Z

All three artifacts are complete, verified, and lint-clean. Summary of what was generated and the key design decisions:

## Deliverables (all in `/home/ubuntu/github/CodingPRD/tasks/task_3456_accident_investigation_party_system_probable_cause_determination/`)

**`SCAFFOLD.yaml`** — §1.0–§1.7 for the NTSB accident-investigation party system:
- **Profile**: compliance/audit × multi-party negotiation; graph topology (flat FK collections + junction entities); cyclic state machines; segregation-of-duties role model; immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, scheduled actions.
- **12 entities / 41 endpoints / 51 errors / 7 calculations / 12 state machines / 10 roles / 2 OCC rules**. Embedded sub-resources (LaunchDecision, GroupSeat, FactualReport, ReadoutSession) keep the endpoint surface dense rather than wide; `api_prefix: "/"` because the API is multi-root (required for the lint's collection-segment derivation).
- Hardness mechanisms: dual-variant launch scoring (statutory vs per-component-rounded risk-adjusted) and calendar-vs-business-day recommendation aging; launch-decision reconsider cycle; FACTUAL↔ANALYSIS revert loop; recommendation reclassification loop; 4-deep expulsion cascade (designation → seat → group → investigation pct); 3-deep board-adoption cascade (meeting → investigation → case); bench half-open vs room 60-minute-buffer overlap rules; strict-majority voting with dissent; 3 SoD rules (proposer≠adopter, chairman≠IIC, IIC barred from board); OCC on case proposals and meeting votes; logical-clock lazy transitions (sessions, recorder completion, meeting sessions).

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — exactly 2 instances per each of the 9 §0.5 rules (18 total), every distinction clause honored (different entity domains, different modes a/b, different cascade triggers/depths 4+3, different error-category pairs, different metrics/endpoints, different entity pairs, different interval semantics, different conserved quantities). Every formula-derived assert was computed and verified in Python (60/59 threshold pair, 62.6-vs-62.5 rounding order, 73.8 HAZMAT divergence, 83/59-GREEN and 84/60-AMBER aging, 90/91 overdue flip).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 52 full instances + 18 `excluded_because` stubs across all nine taxonomy sections; every one of the 51 error codes is triggered by at least one instance.

## Verification results
- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (41 endpoints, 12 entities, 18 §1.8 + 52 §1.9 instances, 892 calls scanned)
- Placeholder closure: zero unbound `${var}` in both design files; instance names unique across both files; all `excluded_because` citations resolve to real §1.8 instance names; all `grounds` refs resolve to declared §1.1–§1.7 elements.
- No forbidden concurrency vocabulary; enum closure clean (all system-owned enum values have producing transitions; remaining enums are `source: input` or computed-formula outputs).

## Design bugs caught and fixed during self-review
- A reopen-then-recomplete deadlock: group completion originally required a VERIFIED report, but docket release converts VERIFIED→DOCKETED, so post-reopen groups could never re-complete — fixed the gate to accept `{VERIFIED, DOCKETED}`.
- Selector non-determinism in recommendation classification: consecutive responses could leave two `classification_pending` entries — pinned that a response while OPEN_UNCLASSIFIED is rejected, keeping the pending entry unique.
- Added the missing close precondition (investigation must be BOARD_REVIEW) so the NOT_ADOPTED revert always has a valid from-state, and a pagination validation row so `ERR_INVALID_PAGINATION_PARAMETERS` is rule-referenced.
- Dropped an unwritable SoD check (`ERR_SOD_AUTHOR_CANNOT_VERIFY`) that the group-creation SoD made unreachable, per the dead-guard lesson.

## Step 3: Copy Shared Files — 2026-10-02T08:04:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3456_accident_investigation_party_system_probable_cause_determination/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T08:23:00.000Z

All contracts pass. The earlier "87 missing" was a verifier artifact (triple-backtick fences in §2.2 flipped regex pairing parity), not a document defect — with fences stripped, every check is clean.

## Report

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_3456_accident_investigation_party_system_probable_cause_determination/workspace/PRD.md` (332 lines) from `SCAFFOLD.yaml`, following the prd-bench-doc-generator skill. The two design-index files were not opened.

**Document skeleton (domain-derived, not templated):**
- §1: three-paragraph introduction (business context → segregation-of-duties angle → logical-clock technical constraint)
- §2: ten subsections — RBAC with per-role identity prose (9 opaque roles + `AddresseeContact` entity-backed by `PartyOrganization`), verbatim §2.2 envelope, pagination, the logical clock & lazy state evaluation, common/embedded resource properties, nested resolution order, OCC, the 10-stage validation pipeline, score/day-count precision conventions, cascading state propagation
- §3: eight lifecycle subsections (notification & scoring → launch decisions → party system → conduct/expulsion → factual record & docket → recorder custody → recommendations → board adoption), zero paths or HTTP methods
- §4: 4-column table, 41 endpoints; §5: 2-column table, 51 errors

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + embedded-entry fields: 71 required, 71 present, 0 missing
- endpoints[].input (incl. optional-marked and clock/occ fields): 22 required, 22 present, 0 missing
- path params {id, decision_id, seat_id, report_id}: 4 present, 0 missing
- (query filters covered via §2.3: status, category, phase, accident_case_id,
  investigation_id, organization_id, specialty, addressee_org_id, limit, offset)
- Total deduplicated: 93 required, 93 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority: 10 stages checked, 10 expressed as an ordered pipeline in §2.8 (incl. the 422-vs-409 split inside stage 7 and ERR_WINDOW_IN_PAST's 422 inside stage 8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed in §2.7 (write endpoint + expected_accident_case_version / expected_meeting_version + ERR_STALE_VERSION/412, pure stale-version framing), 0 missing
- state_machines[].transitions: 14 machines / ~40 transitions checked, all from→to pairs, preconditions paired with error ids, and side effects (supersede, cascades, lazy evaluations, catch-all phase rejection) expressed, 0 missing
- calculations[]: 7 checked, 7 expressed in precise prose (statutory score with inclusive damage-tier bounds; risk-adjusted with pinned round-before-sum order; two-pass docket completeness with stored-status rule and DISBANDED exclusion; dual calendar/business aging with strict-90 overdue and inclusive-60 AMBER; strict-majority adoption with tie/zero → NOT_ADOPTED and dissent ordering; inclusive 2-strike suspension; cross-designation seated_count), 0 missing
- validations[] conditions: all 51 error ids matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 41 checked, all expressed (version increments per mutation, recorder-protection gate scoped to both docket release and transcript verification, OCC scoped to exactly two endpoints), 0 missing
- entities[].fields[] structured content: defaults/initials/nullability/conditional-field rules reconstructible from prose (iic_user_id iff FULL_GO_TEAM, recorder_id iff RECORDER_TRANSCRIPT, dissent_text only with REJECT), 0 missing
- sibling-branch symmetry: 6 groups checked (3 adoption modes, 3 closure outcomes, 2 classify branches, 3 excluded-included org types, both cascade directions at close, both reopen sources for group revert), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 420
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks (all pass): §2.2 byte-identical to `section-2.2-response-structure.md`; all 40 state-enum strings and all 10 role names present verbatim; no fuzzy/approximating words; no operator pseudocode (`==`, `>=`, `+=`, …) outside code fences; §4 has exactly 41 endpoint rows; §5 has exactly 51 error rows. PRD.md ends at §5 with no audit footer.

## Step 5a: Generate Test Helpers (split stage 1) — 2026-10-02T08:50:00.000Z

Step 5a is complete. All nine helper files are written, compile cleanly, and pass an import-level smoke test (39/39 client methods, 51/51 errors registered, score calculators verified against every literal expectation in the design index, entity assertions exercised on synthetic payloads). Nothing was created under `test_suite/`.

## What was built

`test_helpers/` — `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. The API is root-mounted (`api_prefix: "/"`), and the platform clock endpoint `POST /_clock/set_current_utc` is unprefixed per PRD §2.4/§4 — the client reflects exactly that.

**Constants discipline:** every constant in `constants.py` was grep-verified against PRD.md prose (all 20 spot checks OK). SCAFFOLD.yaml and PRD agree on all numerics; the only notation gap is `CATASTROPHIC_FATALITY_THRESHOLD = 5`, which PRD expresses in words ("reaches five or more", §3.1) — value matches the design index's arithmetic. No scaffold-only values imported, no unused constants kept.

## Inventory for Step 5b

**api_client.py** — `ApiClient(GenericApiClient)` + module singleton `api_client`. 39 methods, one per PRD §4 route: `set_clock`; `create_accident_case`, `list_accident_cases`, `get_accident_case`, `propose_launch_decision`, `adopt_launch_decision`, `reconsider_launch_decision`; `list_investigations`, `get_investigation`, `advance_phase`, `reopen_factual`, `release_docket`; `create_party_organization`, `get_party_organization`; `create_party_designation`, `list_party_designations`, `get_party_designation`, `expel_party_designation`, `create_seat`, `record_conduct_violation`; `create_group`, `list_groups`, `get_group`, `complete_group`, `create_factual_report`, `verify_factual_report`; `create_recorder`, `list_recorders`, `get_recorder`, `create_readout_session`; `create_safety_recommendation`, `list_safety_recommendations`, `get_safety_recommendation`, `submit_response`, `classify_response`, `close_recommendation`; `create_board_meeting`, `list_board_meetings`, `get_board_meeting`, `cast_vote`, `close_board_meeting`.

**api_errors.py** — `ApiErrorId(str, Enum)` with all 51 catalogue IDs; `HTTP_STATUS_CODES` dict (400×3, 403×7, 404×11, 409×21, 412×1, 422×8 — including the three duplicate-conflict 409s and `ERR_WINDOW_IN_PAST` at 422), registered via `set_error_http_status_map()` at import.

**types.py** — 25 enums (UserRole, AccidentCategory, AccidentCaseStatus, LaunchMode, LaunchDecisionStatus, InvestigationPhase, DocketStatus, OrgType, PartyDesignationStatus, GroupSeatStatus, ViolationKind, GroupSpecialty, InvestigativeGroupStatus, ReportKind, FactualReportStatus, RecorderType, RecorderCondition, RecorderPackageStatus, ReadoutSessionStatus, SafetyRecommendationStatus, ResponseClassification, AgingBucket, BoardMeetingStatus, VotePosition incl. request-only RETRACT, BoardOutcome); entry shapes ConductLogEntry, ResponseLogEntry, MemberVote; embedded TypedDicts LaunchDecision, GroupSeat, FactualReport, ReadoutSession (no updated_at/version per PRD §2.5); top-level TypedDicts AccidentCase, Investigation, PartyOrganization, PartyDesignation, InvestigativeGroup, RecorderPackage, SafetyRecommendation, BoardMeeting.

**assertions.py** — `assert_common_fields(data)`; per-entity assert_launch_decision, assert_group_seat, assert_factual_report (enforces recorder_id conditional presence), assert_readout_session, assert_accident_case, assert_investigation, assert_party_organization, assert_party_designation, assert_investigative_group, assert_recorder_package, assert_safety_recommendation (incl. ≤1 pending response), assert_board_meeting; invariant checkers `assert_case_scores(case)` and `assert_meeting_tallies(meeting)`; calculators `compute_statutory_score(fatalities, injuries, damage_cents, is_public_transport, category) -> int`, `compute_risk_adjusted_score(...) -> float` (Decimal half-up per component, summed exactly — returns 62.6, not 62.5, for the MARINE case), `compute_suggested_mode(statutory_score) -> str`.

**factories.py** — `create_accident_case_payload(**overrides)` (canonical 60-point HIGHWAY fixture; `report_number` auto-unique via counter), `propose_launch_decision_payload(mode, expected_accident_case_version, **overrides)`, `adopt_launch_decision_payload(iic_user_id=None, **overrides)`, `reconsider_launch_decision_payload(**overrides)`, `advance_phase_payload(to_phase, **overrides)`, `create_party_organization_payload(**overrides)`, `create_party_designation_payload(investigation_id, organization_id, **overrides)`, `expel_party_designation_payload(**overrides)`, `create_seat_payload(group_id, **overrides)`, `conduct_violation_payload(violation_kind, detail, **overrides)`, `create_group_payload(investigation_id, specialty, chairman_user_id, **overrides)`, `factual_report_payload(report_kind, content, recorder_id=None, **overrides)`, `create_recorder_payload(investigation_id, recorder_type, condition, **overrides)`, `readout_session_payload(bench_id, window_start_utc, window_end_utc, **overrides)`, `create_safety_recommendation_payload(investigation_id, addressee_org_id, recommendation_text, **overrides)`, `recommendation_response_payload(response_text, **overrides)`, `classify_response_payload(classification, **overrides)`, `close_recommendation_payload(outcome, **overrides)`, `create_board_meeting_payload(investigation_id, room_id, window_start_utc, window_end_utc, sitting_member_ids=None, **overrides)`, `vote_payload(position, expected_meeting_version, dissent_text=None, **overrides)`.

**test_users.py** — `TEST_USERS` with 12 keys: duty_officer_headers, party_coordinator_headers, recorder_custodian_headers, docket_officer_headers, board_admin_headers, managing_director_headers, md_proposer_headers (md-1), md_adopter_headers (md-2), iic_headers (iic-1 fallback), group_chairman_headers (gc-1 fallback), board_member_headers (bm-1 fallback), addressee_contact_headers (fallback only). Builders: `make_managing_director_headers(user_id)`, `make_iic_headers(user_id)`, `make_group_chairman_headers(user_id)`, `make_addressee_contact_headers(org_id)` (entity-backed — pass the org's `id` / `recommendation["addressee_org_id"]`), `make_board_member_headers(user_id)`.

**fixtures.py** (57 public functions) — composites return dicts with documented keys; all setup uses `get_success_data`:
- Tier 0: `set_clock(to_iso8601=INITIAL_CLOCK_UTC)`, `create_case(**overrides)`, `get_case(case_id)`, `find_decision(case, decision_id)`, `get_proposed_decision(case)`, `get_investigation(inv_id)`, `get_investigation_for_case(case_id)` (asserts exactly 1 row), `create_org(**overrides)`, `get_org`, `create_designation(inv_id, org_id, **overrides)`, `get_designation`, `find_seat(designation, group_id=None, seat_id=None)`, `create_group(inv_id, iic_user_id=..., specialty=..., chairman_user_id=..., **overrides)`, `get_group`, `find_report(group, report_id=None)`, `create_recorder(inv_id, **overrides)`, `get_recorder`, `find_session(recorder, session_id=None)`, `get_recommendation`, `get_meeting`.
- Tier 1: `propose_launch_decision(case, mode="FULL_GO_TEAM", proposer_headers=None, **overrides)` (OCC version read off the case dict), `adopt_launch_decision(case_id, decision_id, iic_user_id=DEFAULT_IIC_USER_ID, adopter_headers=None)`, `reconsider_launch_decision(case_id, decision_id, md_headers=None, **overrides)`, `setup_case_with_adopted_decision(mode="LIMITED", iic_user_id=None, **case_overrides)` → `{case, decision_id}`, `setup_launched_investigation(iic_user_id=..., **case_overrides)` → `{case, decision_id, investigation, iic_user_id}`.
- Tier 2: `advance_phase(inv_id, to_phase, iic_user_id)`, `reopen_factual(inv_id, iic_user_id)`, `release_docket(inv_id)`, `create_seat(designation_id, group_id, iic_user_id)`, `setup_on_scene(iic_user_id, chairman_user_id, org_overrides=None, case_overrides=None)` → adds `{group, chairman_user_id, org, designation, seat_id}`, `create_factual_report(group_id, chairman_user_id, report_kind, content, recorder_id=None, **overrides)`, `verify_report(group_id, report_id, iic_user_id)`, `complete_group(group_id, chairman_user_id)`, `setup_factual(...)` → adds `report_id`, `setup_group_completed(**kwargs)`.
- Tier 3: `setup_docket_released(**kwargs)`, `setup_analysis(**kwargs)`, `issue_recommendation(inv_id, addressee_org_id, iic_user_id, **overrides)`, `setup_analysis_with_recommendation(**kwargs)` → adds `recommendation`, `submit_response(rec_id, org_id, response_text)`, `classify_pending_response(rec_id, classification, md_headers=None)`, `respond_and_classify(rec_id, org_id, classification, response_text)`, `close_recommendation(rec_id, outcome, md_headers=None)`, `build_unacceptable_streak(rec_id, org_id, count=2)`, `schedule_board_meeting(inv_id, **overrides)`, `setup_board_review(meeting_overrides=None, **kwargs)` → adds `meeting`, `setup_meeting_in_session(...)` (clock moved to window start — documented), `cast_vote(meeting, member_user_id, position, dissent_text=None)` (OCC version off the meeting dict), `cast_votes(meeting, votes)` (chains versions; entries `(member, position[, dissent])`), `close_meeting(meeting_id)`.
- Tier 4: `record_conduct_violation(designation_id, seat_id, iic_user_id, violation_kind, detail)`, `record_violations(designation_id, seat_id, count, ...)` (documents the ≤2-strike limit), `expel_designation(designation_id, md_headers=None, **overrides)`, `schedule_readout_session(recorder_id, bench_id, window_start_utc, window_end_utc, **overrides)`, `setup_recorder_with_pending_session(inv_id, bench_id, window_start_utc="2026-09-03T10:00:00Z", window_end_utc="2026-09-03T12:00:00Z", **recorder_overrides)`, `complete_readout(recorder)` (clock to latest session end + re-read; lazy eval, no version bump).
- Tier 5: `setup_adopted_case(meeting_overrides=None, votes=None, **kwargs)` — default votes bm-1 ADOPT / bm-2 ADOPT / bm-3 REJECT-with-dissent; returns full ctx with `meeting`, `investigation`, `group`, `case` refreshed post-cascade (case CLOSED_ADOPTED).

**constants.py** — clock (INITIAL_CLOCK_UTC), statutory score weights/tiers/thresholds (FATALITY_BASE_POINTS 40, CATASTROPHIC_FATALITY_THRESHOLD 5, CATASTROPHIC_FATALITY_BONUS 15, DAMAGE_TIER_MID_MIN_CENTS 1_000_000, DAMAGE_TIER_HIGH_MIN_CENTS 10_000_000, DAMAGE_POINTS_LOW/MID/HIGH 5/15/25, INJURY_CAP 10, PUBLIC_TRANSPORT_POINTS 20, MODAL_BUMP_POINTS 10, MODAL_BUMP_CATEGORIES, SCORE_MAX 100, FULL_LAUNCH_THRESHOLD 60, LIMITED_LAUNCH_THRESHOLD 20), risk weights (FATALITY_WEIGHT 1.0, INJURY_WEIGHT 1.25, PUBLIC_INTEREST_WEIGHT 0.5, CATEGORY_DAMAGE_MULTIPLIER), SUSPENSION_STRIKE_THRESHOLD 2, UNACCEPTABLE_STREAK_FOR_CLOSE 2, CLOSED_RECOMMENDATION_STATUSES, aging (RESPONSE_WINDOW_DAYS 90, AGING_AMBER_MIN_BUSINESS_DAYS 60, AGING_RED_MIN_BUSINESS_DAYS 90), board (MIN_SITTING_MEMBERS 3, ROOM_TURNAROUND_BUFFER_MINUTES 60), pagination (PAGINATION_DEFAULT_LIMIT 10, MIN 1, MAX 100), PHASE_ORDER, EXCLUDED_ORG_TYPES, canonical identities/windows (DEFAULT_IIC_USER_ID "iic-1", DEFAULT_CHAIRMAN_USER_ID "gc-1", DEFAULT_SITTING_MEMBER_IDS ["bm-1","bm-2","bm-3"], DEFAULT_ROOM_ID, DEFAULT_BENCH_ID, default meeting/session windows strictly after the initial clock).

**__init__.py** — re-exports the full framework surface (validate_success/error/paginated/error_is_one_of, get_success_data, is_valid_uuid, is_iso8601_timestamp, race utils, build_user_headers, NON_EXISTENT_UUID) plus all PRD-specific modules above.

One implementation note for Step 5b: creates return 201 (all `create_*`, `propose_launch_decision`, `create_seat`, `record_conduct_violation`, `create_factual_report`, `create_readout_session`, `submit_response`) while transitions/reads return 200 — tests must pass `expected_status=201` explicitly to `validate_success`; fixtures already use the lenient `get_success_data` internally.

## Step 5b: Generate Test Suite (split stage 2) — 2026-10-02T09:25:00.000Z

Step 5b is complete. The test suite is written, collects cleanly, and passes a full AST tag audit plus a verbatim-citation sweep.

## What was built

`test_suite/` — `conftest.py` (session `api` fixture + 12 role-header fixtures) plus 13 test files, **84 tests** total, grouped by domain concern: case registration/scores (6), launch thresholds/overrides (6), launch-decision lifecycle (7), designations/seats (8), conduct/expulsion (5), groups/reports (6), phases/docket (10), recorders/readouts (6), recommendations (7), board meetings (10), adoption cascade (4), RBAC/auth (6), 404s/pagination (3). No file exceeds 10 tests; one file per Write call.

**Verification (all real, run by the subagent; orchestrator spot-check confirmed 84 collected / 0 errors):**
- `pytest test_suite/ --collect-only -q` → **84 collected, 0 errors**.
- AST walk of every test docstring: exactly one `Design:` line, always the last line, every tag resolves to a real instance. Queue A: 16/18 instances with ≥2 tests (32 tests); Queue B: **52/52** non-stub instances with ≥1 test; 0 tests tagged to the 18 `excluded_because` stubs; all 18 stub cross-references resolve.
- Verbatim sweep: all 127 rule-bearing quoted passages (≥8 words) are literal substrings of PRD.md (whitespace-normalized). First pass caught 10 of the subagent's own ellipsis/period-placement violations; all fixed and re-verified.
- All 50 distinct asserted `ApiErrorId`s appear in PRD prose §1–§4 (not just the §5 table). No skip/xfail markers; no scaffold mentions in comments.
- Clock discipline: all design-index dates are reachable from `INITIAL_CLOCK_UTC` (2026-09-01T00:00:00Z, a Tuesday). Every recipe literal recomputed from the PRD formulas — aging (83 cal/59 biz/GREEN at 11-23; 84/60/AMBER at 11-24; day-90 not overdue; day-91 overdue) and all score literals (58/73.8, clamped 100, 62.6 vs 62.5 rounding-order, 58.8/66.3 category multipliers, 59/60 boundary, 78/79 overrides) — all confirmed, **no re-derived literals needed**.

## Skipped instances (2, both queue A — gaps stay gaps)

1. **`Difficulty/cross_entity_state_dependency/cross_entity_designation_gated_by_investigation_phase`** — asserts `POST /party-designations` in ANALYSIS → `ERR_INVESTIGATION_PHASE_INVALID`. **Neither the PRD nor SCAFFOLD.yaml declares any phase gate on designation creation** (§3.3 names only the FK pair, party-type exclusion, and duplicate rule; the endpoint row and PartyDesignation state machine have no phase precondition). A PRD-faithful implementer would *allow* it. The design index invented the guard.
2. **`Difficulty/priority_pair_validation_conflict/priority_pair_designation_phase_state_beats_party_exclusion`** — depends on the same non-existent gate (the state error must exist before it can shadow `ERR_PARTY_TYPE_EXCLUDED`).

(The queue-B stub `designation_creation_blocked_in_analysis_phase` points at skipped instance #1 — stubs produce no test regardless.)

## Corrected translation (not a skip — flagged for adjudication)

**`non_linear_launch_decision_reconsider_cycle`**: the design index's terminal leg claims the reconsidered decision adopts as FULL_GO_TEAM → LAUNCHED. That contradicts PRD §3.2: reconsideration carries only rationale + severity overrides (no mode), so the decision stays LIMITED, and `iic_user_id` "must be absent for the other modes (`ERR_INVALID_REQUEST`)". The two tests assert the PRD-derived outcomes: (T1) the full PROPOSED→ADOPTED→PROPOSED→ADOPTED cycle with the case LIMITED_TRACK→SCREENING→LIMITED_TRACK, recompute to 78, snapshot refresh, exactly-one-PROPOSED; (T2) the second adopt carrying `iic_user_id` on the still-LIMITED decision → 400 `ERR_INVALID_REQUEST`.

## Notes

- Timestamp assertions on logical-clock stamps (`issued_at`, `designated_at`) use `startswith("2026-09-01T00:00:00")` — the PRD pins the value but not the fractional-second rendering of domain timestamps, so exact string equality is not uniquely derivable.
- `test_helpers/` was not modified. One observation only: `fixtures.py` module constants `DUTY_OFFICER`, `MD_PROPOSER`, etc. are not re-exported (not in `__all__`), so tests pull headers from `TEST_USERS` / `make_*` builders directly — no defect, just the visible surface.
- Nothing was run against a server (no implementation exists yet), per the step boundary.

## Step 6: Generate Implementation — 2026-10-02T10:38:00.000Z

All verification complete. Final state of the deliverable:

## Report

**Task**: `task_3456_accident_investigation_party_system_probable_cause_determination` — full Python/Flask implementation generated in `workspace/implementation/`, one file per Write call, no truncation, in-memory-only storage, zero startup seeding.

### File inventory (24 files, 2,972 lines)
| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, guarded `pip install` (flask import check), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.2` |
| `app.py` | 68 | App factory, ApiError/404/405/500 handlers (envelope-shaped), `0.0.0.0:$PORT` |
| `constants.py` | 116 | All 49 named constants (scoring weights/tiers, aging windows, strike/quorum/buffer, clock default, pagination bounds, enum sets) |
| `errors.py` | 81 | `ApiError` + all 51 catalog IDs with PRD §5 statuses (single lookup site, no drift) |
| `clock.py` | 55 | Logical clock (default `2026-09-01T00:00:00Z`, raw-string echo, non-monotonic), ISO-8601 parse, wall-clock stamps |
| `db.py` | 66 | Dict store, UUID minting, creation-sequence ordering, per-request idempotent `touch()` (version+updated_at) |
| `envelope.py` | 98 | `meta`/`response_type`/`data` builders, list pagination fields, limit/offset validation |
| `validate.py` | 99 | Body/field validators → `ERR_INVALID_REQUEST` (strict int-vs-bool, enums, conditional helpers) |
| `auth.py` | 50 | X-User-ID/X-User-Role check, role gates, IIC/chairman ownership helpers |
| `scoring.py` | 98 | Statutory score (int, inclusive tiers, clamp) + risk-adjusted (Decimal, round-half-up per component **before** summing) + `suggested_mode` |
| `aging.py` | 51 | Calendar days (floor, strict >90 overdue), business days Mon–Fri in (issued, now], GREEN/AMBER(60–89 incl.)/RED buckets |
| `domain.py` | 258 | 404 resolvers, lazy clock evaluation (session COMPLETE / recorder READOUT_COMPLETE / meeting IN_SESSION — never bumps version), `seated_count` + two-pass `docket_completeness_pct` recomputes, vote tallies, dissenters, half-open overlap, 60-min room buffer |
| `serializers.py` | 205 | Public dicts for all 8 top-level + 4 embedded types; aging/dissenters computed at read |
| `routes/__init__.py` + 9 route modules | 23–319 each | All 41 endpoints, per-domain: clock, accident_cases (+launch decisions), investigations (+phase/reopen/docket), party_orgs, designations (+expel cascade/seats/strikes), groups (+reports/verify), recorders (+sessions), recommendations (+responses/classify/close), meetings (+votes OCC/close cascade) |

### Verification results
- **py_compile**: all 22 `.py` files pass (`PY_COMPILE_ALL_OK`, re-run after edits: `FINAL_COMPILE_OK`). (Orchestrator spot-check: 22 .py files, COMPILE_OK confirmed.)
- **Route registration**: exactly the 41 spec endpoints (+ Flask's static helper); **`/_clock/set_current_utc` mounted unprefixed** per `api_prefix: "/"`. (Orchestrator spot-check: `clock_routes.py:19` confirms `@bp.route("/_clock/set_current_utc", methods=["POST"])`.)
- **Constants cross-check**: 49 definitions, 0 duplicates, 0 referenced-but-undefined; caught and fixed one magic number (60-min buffer → `ROOM_TURNAROUND_BUFFER_MINUTES`).
- **Error-catalog cross-check**: all 51 catalog IDs raised at least once; no raise site references an undefined ID (guards against KeyError→500).
- **Smoke test** (dynamic port 45161, PID 1025632 started via `bash start.sh`, killed exactly that PID → `SERVER_STOPPED`): 60+ requests covering clock set/role-gate, case create with verified scores (92/78.8 — component-rounding order confirmed; 112→100 clamp; tier boundary 5,000,000→15 pts), propose/supersede/snapshot/OCC-412, SOD proposer≠adopter (403), threshold gates (422), iic-conditional (400), LIMITED/DECLINED/reconsider loop with `adopt_at` reset, IIC ownership, phase gates incl. docket-not-open, party-type exclusion (422), duplicate designation/seat (409), strikes→auto-suspend at 2, expulsion cascade (seats REMOVED → COMPLETE group reverts ACTIVE → pct recompute + inv bump), transcript verify blocked then allowed after lazy READOUT_COMPLETE, bench half-open overlap (touching allowed), release-docket safety gate (409) then RELEASED cascade with pct 100, reopen-factual, recommendation respond/classify/streak/close rules, aging (+95d → overdue True, biz 68 → AMBER; closed never overdue), quorum/window/SOD-on-board checks, room 60-min buffer conflict, vote OCC 412 / non-sitting 403 / retract-without-vote 409 / dissent rule 400, ADOPTED cascade (inv ADOPTED + docket FINAL + groups DISBANDED + case CLOSED_ADOPTED) and tie-vote NOT_ADOPTED → back to ANALYSIS.

### Key interpretation decisions (PRD-faithful)
- Validation pipeline per PRD §2.8: headers → endpoint role → path 404s → ownership → body basics → body-FK 404s in declared input order → state (outer-before-inner per §2.6) → OCC → recorder-safety → domain constraints → temporal → SOD; late conditional-field rules (adopt `iic_user_id`, vote `dissent_text`) placed where §3.2/§3.8 narrate them.
- `created_at`/`updated_at`/`api_request_timestamp` are wall-clock (3-fractional-digit Z per §2.5/§2.2); all domain stamps (`proposed_at`, `designated_at`, etc.) use the logical clock; clock echoes the raw supplied string ("arbitrary values accepted").
- Per-request `touch()` gives every cascade-mutated resource exactly one version bump (§2.10); lazy clock flips persist but never bump.
- Reconsider returns the decision to PROPOSED with `adopted_at` reset to null and snapshots refreshed (§3.2).

Isolation rule honored: only INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md were read — no test_suite/, test_helpers/, or design YAMLs were opened, and the test suite was not run.

## Step 7: Test-Fix Iteration Loop — 2026-10-02T10:55:00.000Z

Clean exit. Final summary:

## Summary

- **Iterations run**: 2 (sweep 1: 83/84 across all 8 rounds, one deterministic failure; sweep 2 after fix: 84/84 across all 8 rounds).

- **Failing test**: `test_seat_then_expel_conserves_group_seated_count` (test_04_party_designations_and_seats.py), `assert 0 == 1` at `assert group["seated_count"] == 1`, identical in all 8 rounds — deterministic, not flaky.

- **Diagnosis**:
  - STEP 1a/1b: PRD §3.3 verbatim-covers the rule — "A group's `seated_count` is the count of seats referencing that group, across every designation of the same investigation, whose status is `SEATED`; it is recomputed on every seat creation, suspension, or removal." After seating one seat on a fresh group, `seated_count == 1` is uniquely derivable. Test stays.
  - STEP 2: TEST WAS WRONG — specifically the fixture. `setup_on_scene()` in test_helpers/fixtures.py returned the group dict captured at creation time (before `create_seat` ran), so `ctx["group"]["seated_count"]` was a stale 0. The fixture's own docstring promises "one SEATED seat on the group", and every downstream fixture (`setup_factual`, `setup_group_completed`, `setup_docket_released`) already refreshes the group — only `setup_on_scene` leaked the stale snapshot. The implementation's recompute was correct all along (sibling tests using fresh `get_group()` reads passed from the start).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: `fixtures.py`, `setup_on_scene` — re-read the group via `get_group(group["id"])` after `create_seat` so the returned ctx reflects the post-seat `seated_count`. Blast radius audited: all other `ctx["group"]` consumers read only `["id"]` (immutable) or come from the already-refreshed downstream fixtures.

- **Fixes applied to `test_suite/`**: none.

- **Fixes applied to `implementation/`**: none.

- **Sibling unasserted paths**: the same PRD §3.3 rule's other two trigger points (recompute on suspension via 2-strike conduct violations; recompute on removal via expulsion cascade) are both asserted in test_04/test_05 and were already passing — no coverage gap left behind.

- **Output contract**: final passing sweep's `results.1.json` … `results.8.json` (all 84/84) remain in `workspace/implementation/`.

Orchestrator verification: all 8 results files read directly — each `passed: 84 / total: 84 / failed: 0`. Fixture fix confirmed at `test_helpers/fixtures.py:395` (`"group": get_group(group["id"])` with explanatory comment). Implementation source mtimes baselined (newest: `domain.py` 2026-10-02 10:29:11, predating all Step 7 sweeps — consistent with zero implementation edits).

## Step 8: Finalize PRD — 2026-10-02T11:05:00.000Z

Done. The analysis confirms the zero-edit outcome: PRD_FINALIZED.md is a byte-identical copy of PRD.md.

## Summary

**File produced:** `workspace/PRD_FINALIZED.md` — **byte-identical** to PRD.md (332 lines each, 0% delta, confirmed with `diff -q`).

### Changes made: zero

The Step 7 diff contains exactly one item — a `test_helpers/fixtures.py` staleness fix in `setup_on_scene` (re-read the group via `get_group(group["id"])` after `create_seat`) — with zero test deletions, zero `test_suite/` fixes, and zero `implementation/` fixes. This is a pure test-artifact bug (a creation-time snapshot dict going stale), which reveals no PRD silence and no PRD/impl mismatch.

### Evidence reads justifying the zero-edit outcome

- **PRD §3.3 (PRD.md:172)** verbatim-contains the exact rule the fixture comment cites: "A group's `seated_count` is the count of seats referencing that group, across every designation of the same investigation, whose status is `SEATED`; it is recomputed on every seat creation, suspension, or removal." The initial value is also pinned (PRD.md:170, "a new group opens `ACTIVE` with `seated_count` at zero"), as are the suspension recompute (line 176) and expulsion-cascade recompute (line 180).
- **Implementation matches the PRD exactly:** `recompute_seated_count` at `implementation/domain.py:173-186` counts SEATED seats on the group across all designations of the same investigation, and is called at all three PRD-named triggers: seat creation (`implementation/routes/designations.py:203`), strike-threshold suspension (`designations.py:251`), and expulsion-cascade removal (`designations.py:150`, including the COMPLETE→ACTIVE revert on zero seated parties, also per PRD line 180).
- **Fixture fix confirmed as fixture-side only:** `setup_on_scene` (`test_helpers/fixtures.py:390-400`) now returns `"group": get_group(group["id"])` with a comment citing PRD §3.3; `get_group` (fixtures.py:194) is a live `GET /groups/<id>` call, which serializes the stored recomputed value (`implementation/serializers.py:120`). The implementation's behavior was correct all along; the stale value existed only in the fixture's cached dict.

### Per-edit pre-edit search log

No edits were committed, so no NO-NEW-MISMATCH enumeration was required. Had an edit been contemplated, the subject would have been `seated_count` recompute semantics, and the enumerated impl paths (all consistent with the existing PRD sentence, requiring no wording change) are the four files listed above: `domain.py` (recompute definition), `routes/designations.py` (all three trigger callsites), `routes/groups.py:51` (initial zero at creation) and `routes/groups.py:107` / `routes/investigations.py:81` (read-only consumers of the field), plus `serializers.py:120` (output shape).

Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` → byte-identical (332/332 lines). Implementation mtime diff vs post-Step-7 baseline → untouched. Evidence spot-checks: PRD.md:172 contains the exact `seated_count` sentence verbatim; `domain.py:173-186` contains `recompute_seated_count` matching the PRD rule. Zero-edit outcome confirmed as adjudicated, not a no-op artifact.

## Step 9: Complete PRD — 2026-10-02T11:35:00.000Z

All changes applied cleanly. The diff is exactly the 19 intended patches, nothing else. Final verification of counts and integrity is done.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` (332 lines, 47,264 chars) → `PRD_COMPLETED.md` (334 lines, 50,123 chars; **+2 lines, +2,859 chars**, 19 patches). Only `PRD_COMPLETED.md` was written.

**Counts:** 18 ambiguity-pins, 1 mismatch-revision, 0 impl-bugs-reported.

**Changes (one per bullet):**
- §2.1 — insert — ambiguity — IIC ownership violations named as `ERR_INSUFFICIENT_PERMISSIONS`; for IIC actions addressed through another resource, the binding investigation is the one that resource references — implementation/auth.py:35-41, routes/designations.py:170-172, routes/groups.py:182-183
- §2.2 — insert — ambiguity — undeclared route/method and unexpected failures return the error envelope with `ERR_INVALID_REQUEST` at 404/405/500 — implementation/app.py:26-60
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected with `ERR_INVALID_PAGINATION_PARAMETERS` — implementation/envelope.py:62-94
- §2.3 — revise — ambiguity — list sort pinned to creation order with millisecond-timestamp ties broken by insertion sequence — implementation/db.py:40, 45-47
- §2.3 — insert — ambiguity — multiple filters combine conjunctively; unmatched filter yields empty page, never 404 — e.g. implementation/routes/accident_cases.py:135-140
- §2.4 — revise — mismatch — "All timestamps" scoped to "All domain timestamps"; `created_at`/`updated_at`/`api_request_timestamp` pinned as wall-clock UTC. Defect reason: the sentence was overbroad and in tension with §2.5's "domain timestamps…are logical-clock stamps" phrasing; impl's domain-logical/system-wall split is the only self-consistent reading — implementation/clock.py:43-55, db.py:36-38
- §2.4 — insert — ambiguity — lazy clock-driven flips never increment `version` or refresh `updated_at` — implementation/domain.py:139-166
- §2.6 — insert — ambiguity — lifecycle-check precedence reaches FK-loaded parents: group before its investigation's phase, meeting before its investigation's phase — implementation/routes/groups.py:93-102, routes/meetings.py:224-234
- §2.10 — insert — ambiguity — a resource mutated more than once in one request still increments exactly once — implementation/db.py:51-66
- §3.1 — insert — ambiguity — `occurred_at` must parse as ISO 8601 else `ERR_INVALID_REQUEST` — implementation/routes/accident_cases.py:82-86
- §3.1 — revise — ambiguity — `location_state` two-letter by convention; any non-empty string accepted (no format rule exists in §2.8's malformedness taxonomy and no error is named) — implementation/routes/accident_cases.py:87
- §3.2 — insert — ambiguity — reconsideration retains `proposed_by_user_id`/`proposed_at`, clears `adopted_at` to null, replaces `rationale` only when supplied — implementation/routes/accident_cases.py:311-316
- §3.3 — insert — ambiguity — new designation carries null `expulsion_reason` — implementation/routes/designations.py:64-74
- §3.3 — insert — ambiguity — no investigation-phase gate on group formation ("with the go-team assembled" is narrative; no error named) — implementation/routes/groups.py:27-55
- §3.3 — insert — ambiguity — no same-investigation constraint between designation and group at seating — implementation/routes/designations.py:165-205
- §3.4 — revise — ambiguity — conduct-violation recording explicitly requires designation `ACTIVE` (`ERR_DESIGNATION_NOT_ACTIVE`), checked before the seat per §2.6 — implementation/routes/designations.py:225-234
- §3.7 — revise — ambiguity — addressee may be any registered party organization; "regulator or industry organization" is descriptive (catalog names no org-type error) — implementation/routes/recommendations.py:40-42
- §3.7 — revise — ambiguity — aging figures computed on every serialization, reads and mutation responses alike — implementation/serializers.py:156-174
- §3.8 — insert — ambiguity — `dissenting_member_ids` computed from current votes on every serialization, visible before close — implementation/serializers.py:200, domain.py:233-244
- §4 — insert — ambiguity — operations addressed at embedded records return the containing parent document in `data` — all route handlers, e.g. implementation/routes/accident_cases.py:198

## IMPL BUGS

None found. Every PRD-named check, formula, threshold, cascade, and side effect was located in the implementation with matching semantics: scoring constants and rounding order (scoring.py matches §3.1/§2.9 exactly), the two-pass docket percentage (domain.py:189-218), all phase gates and their named errors, the expulsion/docket-release/adoption cascades with per-resource version bumps, and the vote/retract/streak state machines.

**Dead-code sweep result:** Automated diff of all `api_error("…")` raise sites vs the `ERROR_STATUS` catalog: 51 ids, all raised, all cataloged — no called-but-undefined (KeyError→500) and no defined-but-dead entries. Every PRD-named guard has a live callsite reachable from its endpoint (verified per-endpoint across all 9 route modules). Gating-field writers audited: `seat.status`, `recorder.status`, `group.status`, `docket_status`, `unacceptable_streak`, `meeting.status`, `member_votes`, `case.status`, `version` — no guard is made unsatisfiable by an earlier guard; the ANALYSIS→BOARD_REVIEW "effectively SCHEDULED" gate is reachable both ways because the lazy clock can pass a meeting's start before advance-phase is called. One impl-internal defensive fallback (classify's "no pending entry" branch, recommendations.py:157-161) is unreachable in practice but is not a PRD-named check, so it is not reported as a bug. Latest sweep on disk: 84/84 passed (results.8.json).

Orchestrator verification: `diff PRD_FINALIZED.md PRD_COMPLETED.md` → 19 patch hunks present, all matching the reported bullets (full diff read). Mismatch-revision adjudication per lost-scaffold-intent rule: the single §2.4 mismatch is a PRD self-contradiction (§2.4 "All timestamps" vs §2.5 "domain timestamps…logical-clock") — exonerated; §3.1/§3.7 softening revisions trace to clauses with no enforcement mechanism anywhere in PRD §5's error catalog or §2.8's pipeline — untestable as originally phrased, exonerated; no revision strips an impl-omitted but enforceable rule. Implementation mtimes diff vs post-Step-7 baseline → untouched, so the clean 8-round sweep remains valid; no re-sweep needed. results.1–8.json remain in workspace/implementation/.
