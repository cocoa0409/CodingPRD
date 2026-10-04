# Worklog — task_3355_corps_member_recruitment_placement_certification_pathway

## Step 1: Create task directory — 2026-10-01T05:18:00.000Z

Task directory `./tasks/task_3355_corps_member_recruitment_placement_certification_pathway/` was pre-allocated by the caller with an empty `workspace/` inside. Verified it exists and is empty; no new index computed and no other `task_*` directory created, per the caller's explicit instruction.

## Step 2 (attempt 1 — FAILED, restarted): Generate Scaffold — 2026-10-01T08:29:53.272Z

First scaffold subagent was killed mid-append by a model-endpoint outage. It left a single partial `SCAFFOLD.yaml` (826 lines) that was verified CORRUPT: `yaml.safe_load` fails at line 603, where an incremental append lost its two-space indent (`- name: AlumniRecord` landed at column 1 instead of column 3), breaking the `entities:` block mapping. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never written. Corrupt partial backed up to `/tmp/task3355_corrupt_backup/SCAFFOLD.yaml.corrupt` and deleted; Step 2 restarted from scratch with an explicit parse-check-after-each-append instruction.

## Step 2: Generate Scaffold — 2026-10-01T09:22:38.000Z

All three artifacts are on disk, parse-clean, and lint-clean. Final sanity check done: re-ran the linter after the last edits (clean), replayed every formula-derived literal through code (all 22 pass), verified placeholder closure across all 74 instances, enum-value closure, error-code reachability, role/endpoint agreement, and confirmed no sentinel or forbidden concurrency vocabulary remains.

Files:
- `/home/ubuntu/github/CodingPRD/tasks/task_3355_corps_member_recruitment_placement_certification_pathway/SCAFFOLD.yaml` (1721 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3355_corps_member_recruitment_placement_certification_pathway/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1579 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3355_corps_member_recruitment_placement_certification_pathway/SCAFFOLD_CORNER_DESIGN.yaml` (2832 lines)

Counts: 10 entities · 5 state machines (29 transitions) · 2 concurrency rules · 9 calculations · 29 validations · 45 endpoints · 29 errors · 7 roles · §1.8 = 9 rules / 19 instances · §1.9 = 9 sections / 55 instances (44 full recipes + 11 `excluded_because` stubs).

Linter verdict, verbatim:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

How I read "much harder than expert level": difficulty from coupling density, not volume. Archetype `workflow_orchestration` + `quota_allocation`, `flat` topology, `segregation_of_duties` roles, 4 complexity layers. Concretely: every Rule-2 mode is exercised by a *different* calculation (nested min/bonus-stack on `selection_score`, per-week-then-sum nested rounding on `institute_stipend_cents` pinned against a 75114-vs-75115 cent divergence, and a circular-looking tier-keyed credit on `readiness_score` where the pinned order gives 80.00 and the wrong order gives 81.50); three cascades of depth 3, 2 and 3 from distinct triggers; two OCC rules on different parents; two temporal-overlap rules with genuinely different interval arithmetic (half-open coach adjacency *allowed* vs closed school-capacity adjacency *rejected*); two priority-conflict pairs across different error-category pairs; and two compensating invariants over different conserved quantities (a district placement count vs a member hour sum). Two defects the replay caught and I fixed: a wrong bonus-stack literal (95.13, not 90.13) and an unreachable `WITHDRAWN` enum member.

One caveat worth flagging downstream: at 45 endpoints this sits above the ~40 threshold that has previously caused the implementation-generator step to return a rambling report — worth verifying files on disk at that step rather than trusting its summary.

**Orchestrator verification (independent of the subagent's report):** all three files re-parsed with `yaml.safe_load` — OK. Counts confirmed: entities 10, state_machines 5, calculations 9, validations 29, endpoints 45, errors 29, roles 7; no `scaffold_difficulty_design`/`scaffold_corner_design` key inside SCAFFOLD.yaml. Design files each carry exactly one top-level key. `scaffold_lint.py` re-run by the orchestrator returned the same clean verdict (§1.5 endpoints 45, §1.1 entities 10, §1.8 instances 19, §1.9 instances 44, calls scanned 775). Caveat accepted: 45 endpoints > 40 — Step 6 output must be verified on disk.

## Step 3: Copy Shared Files — 2026-10-01T09:22:36.782173734Z

`cp ./INSTRUCTION.md ./tasks/task_3355_corps_member_recruitment_placement_certification_pathway/workspace/INSTRUCTION.md` — verified 1424 bytes, identical to the project-root original. Workspace now holds INSTRUCTION.md only.

## Step 4: Generate PRD — 2026-10-01T09:32:02.707622398Z

All checks green. Final state verified: 337 lines, no sentinel, §2.2 byte-identical to the canonical block, §4 is 45 rows × 4 columns, §5 is 29 rows × 2 columns.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3355_corps_member_recruitment_placement_certification_pathway/workspace/PRD.md` (337 lines)

**Headings emitted:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure [verbatim], 2.3 Pagination, 2.4 Regional Configuration as the Deadline Anchor, 2.5 Common Resource Properties, 2.6 Numeric Precision and Rounding Discipline, 2.7 Optimistic Concurrency Control, 2.8 Cascade Discipline and Derived-Counter Integrity, 2.9 Segregation of Duties, 2.10 Request Admissibility and the Validation Ladder, 2.11 Nested Resource Retrieval, 2.12 The Logical Clock); §3 Business Logic (3.1 Recruitment and the Applicant Record, 3.2 Entering the Pipeline, 3.3 Decisions/Offers/Regional Quota, 3.4 Pre-Service Institute, 3.5 Certification Milestones and State Deadline Compliance, 3.6 District Partnerships, 3.7 Placement Matching/Capacity/Activation, 3.8 Placement Endings and the Fee Ceiling, 3.9 Service Status/Coaching/Evaluation); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Coverage:** 10 entities (84 fields), 5 state machines (29 transitions), 9 calculations, 29 validations, 2 concurrency rules, 45 endpoints, 29 errors, 7 roles.

```
Field coverage check:
- entities[].fields: 84 required, 84 present, 0 missing
- endpoints[].request_body: 60 required, 60 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
- endpoints[].path_params: 1 required ({id}), 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + occ_field + error_id + status), 0 missing
- state_machines[].transitions: 29 checked, 29 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed (formula, constants, evaluation order, precision), 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 45 checked, 45 expressed, 0 missing
- entities[].fields[] structured content: 84 checked, 84 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked, 8 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 499
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold ambiguities and prose decisions:**
1. `expected_corps_member_version` is listed in the input array of milestone creation (`POST /corps/certification-milestones`) but no `concurrency_rules` entry covers it, and validation priority 13 says the OCC gate is evaluated *only* on `POST /corps/placements`. I followed the skill's rule that endpoints outside `concurrency_rules` take no version field; the name still appears (in §2.7) so Contract 1 holds.
2. Placement confirmation lists no `occupied_classrooms` increment, yet the field is described as a derived count of `CONFIRMED`/`ACTIVE` placements and early-exit/reinstate do decrement/increment it. I stated both the derived definition and the explicit ±1 side effects without inventing an increment on confirm.
3. Member `ACTIVE → EXITED` lists no placement-eligibility recompute, but the `employment_eligibility` calculation's trigger covers "CorpsMember service_status changes". I used the calculation's trigger wording rather than adding a cascade the transition didn't declare.
4. `ERR_DISTRICT_BUDGET_EXCEEDED` fires at placement *creation*, when the placement is still `MATCHED`. I rendered it as a projection ("as the invoice would stand once this placement is counted among `CONFIRMED`/`ACTIVE`").
5. Three calculation identifiers are not field names (`district_invoice_amount_cents`, `certification_deadline_status`, `employment_eligibility`); the scaffold references them only as "see calculation X". I expressed their rules fully in prose without leaking the internal identifiers.
6. Priority-1 validation exempts the clock endpoint from header checks while priority-2 applies the role check to all endpoints — a latent conflict. I stated it literally: header check skipped there, role check still enforced.
7. `coursework_fee_cents` is described as prorated by coursework progress but no calculation consumes it; I rendered it as pathway configuration only.

**Orchestrator verification (independent):** PRD.md present, 336 lines by `wc -l` (337 with trailing newline as counted by the subagent), no `<!-- APPEND -->` sentinel remains. §4 table = 45 data rows, §5 table = 29 data rows. §3 contains 499 backtick tokens, 0 of which start with `/` (path purity holds). All 29 scaffold `errors[].id` values and all 45 `endpoints[].path` values appear in the PRD text — 0 missing from either set.

## Step 5: Generate Unit Tests — 2026-10-01T09:47:01.888601599Z

Sanity checks all pass: every file compiles and imports, pytest collects 86 tests, all 63 Design tags resolve to real instances with correct counts, all 146 PRD quotes survive a literal grep of PRD.md, no sentinels/skips/`scaffold` mentions remain, and `workspace/implementation/` was not created.

**Files written**

`test_helpers/` (9): `__init__.py`, `types.py`, `api_client.py` (45 endpoint methods), `api_errors.py` (29 errors + HTTP map registered), `assertions.py`, `constants.py`, `factories.py`, `test_users.py`, `fixtures.py` (601 lines, 48 composite helpers).

`test_suite/` (16): `conftest.py` plus `test_01_selection_scoring`, `test_02_district_invoice`, `test_03_institute_and_readiness`, `test_04_application_lifecycle`, `test_05_cascades`, `test_06_placement_guards`, `test_07_validation_conflicts`, `test_10_entity_creation`, `test_11_state_machines`, `test_12_calculations`, `test_13_validation_errors`, `test_14_endpoints_envelopes`, `test_15_errors_and_occ`, `test_16_rbac`, `test_17_cross_cutting`.

**Counts**: 86 tests total. Queue A — all 19 §1.8 difficulty instances transcribed, each with 2–3 tests (40 tests). Queue B — all 44 non-stub §1.9 corner instances transcribed, 1 test each (46 tests, three instances got a second test).

**Skipped**: 11 §1.9 `excluded_because:` stubs (the index-declared ones owned by queue A) — not translated, and verified untagged. **Zero** non-stub instances were skipped for PRD silence; every non-stub instance had verbatim PRD coverage that uniquely derives its asserted outcome.

**PRD vs design-index disagreements** (PRD followed in each case):
1. `corps_member_exited_blocks_leave_and_placement` — index says leave-on-EXITED → `ERR_INVALID_STATE`; PRD §2.10 and §3.9 both name `ERR_ALREADY_TERMINAL` for member leave. Asserted `ERR_ALREADY_TERMINAL`.
2. `error_already_terminal_on_exited_member` — same conflict for return-from-leave. §3.9 names `ERR_ALREADY_TERMINAL`, but §2.10's enumeration omits return-from-leave, so I used `validate_error_is_one_of([ERR_ALREADY_TERMINAL, ERR_INVALID_STATE])` (error-precedence silence pattern).
3. `school_capacity_closed_interval_adjacency_rejected` — index asserts `occupied_classrooms == 1`, but PRD §3.8 defines that counter as placements whose window is *open at the current logical clock*, and at the default clock the `[2026-12-01, 2027-05-31]` window is closed. Dropped that sub-assertion; kept the closed-interval capacity outcomes.
4. `early_exit_reinstate_conserves_committed_count` — index asserts a school `occupied_classrooms` decrement, which contradicts the §3.8 clock-open definition (would be 0 → −1). Asserted only the district counters and invoice.
5. `error_institute_incomplete_on_activate` — index's setup yields readiness 30.00, which fails the §3.7 `readiness_score >= 60.0` gate, so its "identical activate succeeds" half cannot hold. Adjusted the fixture to verify COURSEWORK+PRACTICUM first (readiness 90.50), which isolates the institute gate the instance is about.
6. `milestone_subresource_list_is_ordered` — index asserts the *pathway* sub-resource list returns COURSEWORK first; PRD pins the canonical order only for a member's milestone collection. Asserted the pathway list returns its 4 rows instead.
7. `region_create_missing_required_field_returns_400` — index's non-persistence check used a list endpoint for regions, which the PRD does not define; replaced with a successful re-create under the same `region_code`.
8. `selection_score_provisional_vs_final_gpa` — index asserts `final_selection_score == 84.96` after a *refused* decision, but PRD §3.3 ties that write to the decision landing. Used a mirrored pair (gpa 3.90 reviewed at verified 4.00) to observe the final variant unambiguously, plus the refused case for the gate.

**Orchestrator verification (independent):** `test_helpers/` holds the 9 claimed modules; `test_suite/` holds `conftest.py` + 15 test files. `python3 -m pytest test_suite --collect-only -q` reports **86 tests collected**. `grep -rn 'APPEND'` finds no sentinel. `grep -rn 'pytest.mark.skip|pytest.mark.xfail'` finds no skip/xfail markers. `workspace/` still contains only `INSTRUCTION.md` and `PRD.md` — no `implementation/` was created, so the Step 5/6 isolation held. A scripted scan of all 86 `Design:` docstring tags found **0 unresolvable** tags, covering 19 distinct Difficulty instances and 44 distinct Corner instances — matching the subagent's reported counts exactly.

## Step 6: Generate Implementation — 2026-10-01T10:04:16.633634901Z

Sanity check performed before declaring done: `bash -n start.sh` clean, `python3 -m py_compile` clean on all 15 modules, `grep -rn APPEND` finds no sentinel, and the server was booted twice on free ports via `bash start.sh` — all 45 routes registered, 88 end-to-end behaviour checks + 31 response-shape checks passed, and a second boot accepted a `region_code` already used on the first boot (proving the store wipes). I worked in the foreground and read only INSTRUCTION.md, SCAFFOLD.yaml and PRD.md — never the design YAMLs, `test_suite/` or `test_helpers/`, and never ran the test suite.

**Files written** (all under `.../workspace/implementation/`): app.py 72, calc.py 303, envelope.py 110, errors.py 47, routes_cert.py 218, routes_core.py 229, routes_members.py 158, routes_misc.py 76, routes_placements.py 233, routes_selection.py 296, serialize.py 213, services.py 225, store.py 64, util.py 104, validation.py 135, start.sh 10, requirements.txt 1.

**Endpoints: 45/45** implemented and verified by enumerating the route decorators against the PRD §4 table.

**Smoke test:** server booted via `PORT=<free> bash start.sh`, `GET /corps/corps-members` returned 401 (unauthenticated) at readiness, then a full journey — region → district → school → pathway → applicant → application → review → decision → offer → acceptance (member + 4 milestones synthesized) → practice hours (stipend 40687¢) → institute complete → placement → confirm (fee 46000¢) → milestone verify → activate (employment_eligible true) → early-exit/reinstate → leave/return/exit → clock advance (placement auto-COMPLETED, district auto-EXPIRED). All 88 checks passed; response-shape run passed 31/31 with a clean server log.

**PRD ambiguities resolved (PRD wins over SCAFFOLD):**
1. `POST /corps/certification-milestones` lists `expected_corps_member_version` in the scaffold's input, but §2.7 states only the placement and school creations carry a version precondition and "no other endpoint requires, accepts or honours a version field" — so it is accepted-if-present and ignored, never required or checked.
2. `POST /corps/placements` resolves the corps member before the school (§2.11 body-parent left-to-right), overriding the scaffold's numeric existence priority which puts School (6) ahead of Member (10). Same for milestone creation (member before pathway).
3. Cascade version accounting: a transitioned entity gets exactly +1 (the scaffold's explicit bullet), each cascaded resource +1 per hop, and the acceptance cascade advances the member's version once per synthesized milestone as §2.8 states literally.
4. `occupied_classrooms` is treated as derived per §3.8 ("derived rather than authored" — placements CONFIRMED/ACTIVE whose term window is open at the logical clock), while the capacity rule counts overlapping placements directly from the closed-interval definition.
5. `return_reason` is accepted on return-for-revision but not stored/echoed, since Application declares no such field.
6. A pathway whose `state_code` disagrees with its region is accepted: no error identifier exists for it in the closed 29-code catalogue.
7. Offer-response ordering uses state → offer window → quota, so both failure modes return 409 as declared.

**Orchestrator verification (independent):** all 17 claimed files present on disk with matching sizes; `grep -rn APPEND` clean; no persistence (no sqlite/.db/json.dump/pickle/shelve/file-write) anywhere in the sources; no seeding (the only `seed`/`preload` hits are docstrings asserting the opposite). Booted the server myself on port 18773 via `bash start.sh`, killed exactly the PID I started (3307850). Readiness in 2s; `GET /corps/corps-members` unauthenticated → 401 `ERR_UNAUTHENTICATED`, proving the auth tier is live. A scripted extraction of `@bp.route(..., methods=[...])` decorators found **45 routes**, and a name-agnostic diff (normalising `{id}`/`{district_id}`-style params to a placeholder) against SCAFFOLD.yaml §1.5 gave **missing = [] and extra = []** — exact 45/45 correspondence. Note: my first probe used role `NationalDirector`, which is not in the 7-role set (`PlatformAdmin, SelectionManager, Applicant, PlacementCoordinator, InstituteDirector, CertificationOfficer, Coach`) and was correctly refused; that was a probe error, not an implementation defect. Step 6's 45-endpoint overshoot caveat did not materialise — the report matched disk exactly.

## Step 7: Run Tests and Iterate — 2026-10-01T10:24:27.87141449Z

NOTE — this step spanned a host-session interruption. A first Step 7 subagent was killed after its baseline sweep completed but before it diagnosed anything. That baseline sweep (results.{1..8}.json @ 10:08Z, all rounds 77/86 with the same 9 deterministic failures; impl sources last written 09:59Z, tests 09:45Z) was verified on disk to postdate all source, so it was handed to the second Step 7 subagent as a valid baseline rather than discarded. The second subagent then completed the step.

Sanity checks pass: all 8 rounds report `total 86 / passed 86 / failed 0 / errors 0 / skipped 0`, no skip/xfail markers exist in the suite, all 8 `results.*.json` are on disk, and every test edit (10:19–10:20Z) predates the sweep while the implementation sources (last write 09:59Z) were never touched this iteration — so the sweep is valid for the current code.

**Iterations run:** 1 (STEP 0 diagnosis from the existing 10:08Z baseline results, then one 8-round parallel sweep — clean).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; the two over-specified assertions (timestamp byte format, foreign-applicant error id) were split per STEP 1c rather than deleted.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `assert_same_instant(actual, expected)`: compares ISO 8601 timestamps by instant, not byte notation. PRD §2.2/§2.5 pin three-fractional-digit notation only for `api_request_timestamp`/`created_at`/`updated_at`; for a region's `term_start_date`, a support record's `session_start` and an application's `offer_expires_at` the PRD fixes only the instant, so a server rendering `...T15:00:00Z` as `...T15:00:00.000Z` is conforming. Used by three tests.

**Fixes applied to `test_suite/` (all STEP 2 "test is wrong" / STEP 1c splits):**
- `test_06_placement_guards.py` — 5 `validate_success(api.create_support_record(...))` calls now pass `201`: PRD §4 line 252 lists "a support record" among creations that answer `201 Created` (the helper's 200 default was the bug). Also line 153's byte-exact `session_start` echo → `assert_same_instant`.
- `test_10_entity_creation.py` — `term_start_date == "2026-12-01T00:00:00Z"` → `assert_same_instant` (same format-silence split; `assert_region` still enforces ISO-8601 shape).
- `test_11_state_machines.py` — the REJECT decision now uses `DECIDER` instead of `REVIEWER`: PRD §2.9/§3.3 require the deciding operator to differ from the reviewer, so the fixture's shared `X-User-ID` was the bug, not the server's `ERR_SOD_VIOLATION`.
- `test_13_validation_errors.py` — same SoD operator fix on the decision; `offer_expires_at` byte-exact echo → `assert_same_instant` (PRD §3.3 pins "clock plus 14 days", not the notation).
- `test_16_rbac.py` — foreign-applicant offer response relaxed from exact `ERR_INVALID_STATE` to `validate_error_is_one_of([ERR_FORBIDDEN_ROLE, ERR_INVALID_STATE])` plus the catalogue status check: PRD §3.3 says only that a non-owning applicant "is turned away" and names no error id, so both the authorization and the unmet-precondition readings are conforming; the pinned parts (refusal, offer left `OFFER_EXTENDED`, owner then succeeds) remain exact.
- `test_03_institute_and_readiness.py` — `assert_readiness_matches_formula` was handed the `milestones_by_type()` **dict** where it iterates a list, producing the `TypeError: string indices must be integers`; now passes `list(...values())`. Assertion unchanged.

**Fixes applied to `implementation/`:** none — every failure was a test-artifact defect, and no PRD-required check was weakened or removed.

**Orchestrator verification (independent):** re-read all 8 `results.*.json` directly — every round reports `passed=86 total=86 failed=0 errors=0 skipped=0`. Confirmed by mtime that the sweep (10:23:23–24Z) postdates the newest test edit (10:20:28Z) and that no `implementation/*.py` file was written after 09:59:59Z, so the green sweep genuinely covers the shipped code. `grep -rn 'pytest.mark.skip|pytest.mark.xfail'` over `test_suite/` and `test_helpers/` returns nothing.

**⚠ Carry-forward for Step 8 (per the "test-side fixes shadow the PRD" hazard):** this iteration produced **zero implementation fixes and seven test-artifact fixes**. A green sweep therefore proves tests agree with code, not that PRD agrees with code, on exactly these paths. Step 8's focus list must include: (a) the `201` status the PRD assigns to support-record creation and every other creation the implementation answers with 201; (b) the ISO-8601 notation the implementation emits for `term_start_date` / `session_start` / `offer_expires_at` (the tests were relaxed to instant-equality, so the notation the server actually chose is now unpinned by any assertion); (c) the segregation-of-duties operator rule the implementation enforces as `ERR_SOD_VIOLATION` on the decision path; (d) the error id the implementation returns to a non-owning applicant responding to an offer (the assertion was widened to a two-member set, so the concrete id is unpinned); (e) the readiness-formula helper's argument shape, which was a test bug only and implies nothing about the implementation.

## Step 8: Finalize PRD — 2026-10-01T10:31:43.959916570Z

Both edits are verified against the running implementation. Final state confirmed: PRD.md untouched (71,198 bytes, 09:31), implementation/ untouched, PRD_FINALIZED.md 336 lines / 71,762 bytes.

**Sanity check run:** in-process Flask test client against `workspace/implementation/` (no server, no ports, no processes started) — 40/40 checks passed: every timestamp field named in the new §2.5 sentence renders as `...T00:00:00.000Z`; support-record creation answers 201; a non-owning applicant's offer response answers 403 `ERR_FORBIDDEN_ROLE` with the offer left `OFFER_EXTENDED`; and the whole flow (region → pathway → applicant → review → decision → district → school → offer → acceptance → milestones → institute → placement → support record) ran end to end. `diff PRD.md PRD_FINALIZED.md` = 2 changed lines.

**Deliverable:** `workspace/PRD_FINALIZED.md`

**Size delta:** PRD.md 336 lines / 71,198 bytes → PRD_FINALIZED.md 336 lines / 71,762 bytes; +564 bytes (+0.79%), 2 changed lines (1 insert, 1 revise). No new sections.

**Changes**

- **§2.5 Common Resource Properties — insert** — after the `created_at`/`updated_at` sentence, added: every other ISO 8601 timestamp a resource carries (region `term_start_date`; application `offer_expires_at`/`returned_at`; member `service_started_at`/`leave_started_at`; placement `term_start_date`/`term_end_date`/`confirmed_at`/`activated_at`; milestone `due_date`/`completed_at`; support record `session_start`/`session_end`) is rendered in three-fractional-digit notation even when the client supplied the instant in another form — impl: `util.py:21-28` is the sole renderer, used at `routes_core.py:45`, `routes_selection.py:193,255`, `routes_members.py:56,71`, `routes_placements.py:96,97,147,172`, `routes_cert.py:128,131,193`, `services.py:122`, `routes_misc.py:40,41`.
- **§3.3 Decisions, Offers and the Regional Quota — revise** — the "answered by the applicant alone … is turned away" sentence now ends "…is turned away with `ERR_FORBIDDEN_ROLE` (HTTP 403)" — impl: `routes_selection.py:266-267`, `errors.py:6`.

**Diff items deliberately not edited (PRD already determines the behavior)**

- (a) 201 for support-record creation: §4 line 252 already lists "a support record" among the nine creations, and the impl's nine 201 sites match that list exactly (`routes_core.py:51,91,207`, `routes_selection.py:90,135`, `routes_cert.py:67,151`, `routes_placements.py:107`, `routes_misc.py:64`) — the helper's 200 default was the bug.
- (c) SoD on the decision path: §2.9/§3.3 already pin decider ≠ `reviewed_by_user_id` → `ERR_SOD_VIOLATION` 403 (`routes_selection.py:226-227`); the fixture's shared `X-User-ID` was the bug.
- (e) readiness helper argument shape: pure test bug, assertion unchanged, and the helper's formula already agrees with `calc.readiness_score` (`calc.py:184-229`).

**Pre-edit search log**

- **Edit 1** — (a) subject: the notation used to render ISO-8601 timestamp fields other than `api_request_timestamp`/`created_at`/`updated_at`. (b) read/grepped: `util.py:21-28` (single renderer, always `%Y-%m-%dT%H:%M:%S.%03dZ`); a repo-wide grep for `iso(|strftime|isoformat|clock_iso()` giving 13 emission sites plus `store.py`/`envelope.py`; `serialize.py` pick-lists (the complete set of exposed timestamp fields); `envelope.py:26` and `store.py:43,53` (already pinned by §2.2/§2.5); PRD grep for ISO literals (only the two §2.2 envelope examples and the §2.12 clock value, which is never rendered — the clock endpoint returns `{}`). (c) adjustment: enumerated every emitted field *and* stated the universal rule, so the wording can't be read as excluding a forgotten field, and scoped it to "a resource carries" so it cannot be misread as governing envelope timestamps or the clock's own literal.
- **Edit 2** — (a) subject: the response to a non-owning caller of `POST /corps/applications/{id}/offer/respond`. (b) read/grepped: `routes_selection.py:260-269` (role-list 403; body validation; 404 on missing application; ownership 403 at :266-267 *before* the `OFFER_EXTENDED` check at :268); `envelope.py:93-106`; a grep for `ERR_FORBIDDEN_ROLE|applicant_id` showing exactly two ownership sites (:203-204 resubmit, :266-267 respond), both `ERR_FORBIDDEN_ROLE`, so the wording is also consistent with the sibling applicant-only operation; `errors.py:6` and the §5 catalogue (403). (c) adjustment: named only the error id and status inside the existing sentence — no ordering claim added (body validation and entity resolution still precede it per §2.10), and deliberately not generalized to the resubmit site, which is outside the Step 7 diff.

**Orchestrator verification (independent):** `PRD_FINALIZED.md` exists at 336 lines / 71,762 bytes; `diff PRD.md PRD_FINALIZED.md` shows exactly two changed lines (84c84 and 160c160) and nothing else. `PRD.md` mtime is unchanged at 09:31:22Z, so the original was not modified. No file under `implementation/` was written after 09:59:59Z, so Step 8 did not invalidate the Step 7 sweep — the clean 8-round result still stands.

## Step 9: Complete PRD — 2026-10-01T10:45:55.290317388Z

Sanity checks passed: 25 changed lines, all 1:1 replacements; line count unchanged at 336; all headings identical; all 78 table rows intact; file differs from source; and an AST call-graph trace from all 45 registered routes confirms every error id raised in the codebase is reachable.

**Source vs output**
- Source: `workspace/PRD_FINALIZED.md` — 336 lines / 71,762 chars
- Output: `workspace/PRD_COMPLETED.md` — 336 lines / 75,335 chars (**+3,573 chars, +4.98%**, 0 line delta; 25 edited lines, no new lines, no new sections)

**Counts: 22 ambiguity-pins, 6 mismatch-revisions** (28 distinct changes across 25 edited lines)

**Mismatch-revisions (PRD described behavior impl does not have)**
- §2.4 — revise — mismatch — dropped the claim that a pathway's `state_code` must agree with the region's; it is stored as supplied and never cross-checked — `routes_cert.py:48,56-58`
- §3.5 — revise — mismatch — same `state_code` claim removed at the pathway-creation passage — `routes_cert.py:48`
- §3.3 — revise — mismatch — quota boundary re-pinned: acceptance is refused once the ACTIVE/ON_LEAVE count has *already reached* `max_corps_members` (inclusive ceiling), not "an acceptance that would reach the quota is refused"; the old prose was self-contradictory and its second clause contradicted the impl — `routes_selection.py:289-290`
- §3.7 — revise — mismatch — confirmation's five gates re-ordered to match evaluation order (subject-needs, grade-band vs school, grade-band vs preference, then district ACTIVE, then member ACTIVE), with a note that the first two decide the response when both they and a district/member gate fail — `routes_placements.py:127-138`
- §3.8 — revise — mismatch — `occupied_classrooms` no longer claimed to be "the counter that the capacity rule reads"; the capacity rule is a separate overlap-scoped count — `services.py:67-81` vs `serialize.py:68`
- §3.9 — revise — mismatch — the low-scoring EVALUATION no longer claims to store a flag on the member; recording stores nothing beyond the record — `routes_misc.py:53-63`

**Ambiguity-pins (PRD was silent)**
- §2.2 — revise — `api_request_timestamp` carries the logical clock instant, not wall-clock — `envelope.py:25-26`
- §2.3 — revise — a negative `offset` is a malformed request — `envelope.py:81-82`
- §2.4 — revise — `base_placement_fee_cents` must be non-negative — `routes_core.py:37`
- §2.10 — revise — a required string field must be non-blank — `validation.py:93-103`
- §2.12 — insert — the two clock-driven automatic transitions are applied before each request is handled — `app.py:38-43`, `services.py:215-225`
- §3.2 — insert — submission defaults: `final_selection_score` 0.0, and `verified_gpa`/`reviewed_by_user_id`/`decided_by_user_id`/`decision_reason`/`offer_expires_at`/`created_corps_member_id`/`returned_at` null — `routes_selection.py:121-131`
- §3.2 — revise — `return_reason` is accepted but neither stored nor echoed — `routes_selection.py:184`
- §3.2 — insert — resubmit by a caller whose `X-User-ID` mismatches is `ERR_FORBIDDEN_ROLE` — `routes_selection.py:203-204`
- §3.3 — revise — new member's `service_started_at`/`leave_started_at`/`exit_reason` start null; `service_started_at` written only on return-from-leave — `services.py:185-187`
- §3.3 — insert — multi-pathway synthesis order (`created_at`, then lower `id`) — `services.py:142-143`
- §3.4 — revise — `practice_hours_delta` is a non-negative integer, and recording after `COMPLETED` is `ERR_INVALID_STATE` — `routes_members.py:101-104`
- §3.5 — revise — `coursework_hours_completed` = sum of `required_hours` over COMPLETED COURSEWORK/ORIENTATION milestones, verified or not — `calc.py:172-178`
- §3.5 — insert — with no selectable pathway, practice and coursework ratios are 1.0 — `calc.py:198-206`
- §3.5 — revise — with several CONFIRMED/ACTIVE placements, they are considered in `created_at` order and the first whose region holds a pathway decides — `calc.py:130-146`
- §3.5 — revise — eligibility's required-hours sum is 0 when no pathway can be selected — `calc.py:268-272`
- §3.6 — revise — only DRAFT→ACTIVE, ACTIVE→SUSPENDED, SUSPENDED→ACTIVE are legal; any other `to_status` is `ERR_INVALID_STATE` — `routes_core.py:125-148`
- §3.6 — revise — an unknown `projection` value is `ERR_INVALID_REQUEST` — `routes_core.py:111-113`
- §3.7 — revise — a MATCHED placement carries `placement_fee_cents` 0 — `routes_placements.py:102`
- §3.7 — revise — the term-window instants are not cross-checked — `routes_placements.py:69-70,96-97`
- §3.9 — revise — `effectiveness_score` is an integer, and the session instants are not cross-checked — `routes_misc.py:32-34`
- §5 — insert — unknown path / disallowed method / unexpected failure answer `ERR_INVALID_REQUEST` at 404 / 405 / 500 — `app.py:51-68`

**DEAD-CHECK findings: none.** An import-aware AST call graph from all 45 registered Flask routes confirms all 29 `ERR_*` identifiers raised in the implementation are reachable from a route. The closest thing to a finding is that the PRD-required pathway/region `state_code` agreement was implemented *nowhere at all* (not a defined-but-uncalled helper) — surfaced above as the two mismatch-revisions. The genuinely uncalled symbols are all non-check utilities: `util.as_int`, `util.as_number`, `util.is_int`, `util.round_half_up_float`, `store.parse_clock`, `store.put`, `services.district_of_placement`, `services.region_of_district`, `serialize.school_or_none` — none is a PRD-required validation, gate or guard.

**Orchestrator verification (independent):** `PRD_COMPLETED.md` is 336 lines / 75,335 bytes vs `PRD_FINALIZED.md` 336 lines / 71,762 bytes; `diff -q` confirms the files DIFFER (not a `cp`-then-no-edit no-op), and `diff | grep -c '^[<>]'` counts 50 changed lines = 25 replaced pairs, matching the reported 25 edited lines with zero line-count change. No file under `implementation/` was written after 09:59:59Z, so Step 9 did not invalidate the Step 7 sweep. Spot-checked three of the subagent's claims directly against source: (1) `grep -rn state_code` over `implementation/*.py` returns only a `validation.state_code` format helper, a store write and two serializer pick-lists — no comparison against a region, confirming the dropped PRD claim; (2) `routes_selection.py:290` reads `if committed >= region["max_corps_members"]: raise ApiError("ERR_INVALID_STATE", ...)` — the inclusive ceiling as reported; (3) `envelope.py:26` builds `api_request_timestamp` from `clock_iso()`, the logical clock, not wall-clock. All three CONFIRMED.

## Step 10: Final validation sweep (orchestrator-run) — 2026-10-01T10:48:59.10511992Z

Ran the full 8-round parallel sweep myself, after Steps 8 and 9 had finished, against the frozen deliverable:

```
rm -f workspace/implementation/results.*.json
for i in 1..8: prd-bench-local-run --start-command "cd .../workspace/implementation && bash start.sh" \
  --test-dir .../test_suite --isolation per-test-server --timeout 120 --test-timeout 30 \
  --results-file .../workspace/implementation/results.${i}.json &
wait
```

**Result: ALL 8 ROUNDS GREEN — every round `passed=86 total=86 failed=0 errors=0 skipped=0`.**

Why this re-run was necessary rather than trusting the Step 7 sweep: Steps 8 and 9 run *after* the clean sweep and are both permitted to edit `workspace/implementation/`. Had either done so, the Step 7 evidence would have been invalidated. Verified by mtime that neither did (no `implementation/` file written after 09:59:59Z), and then re-ran the sweep anyway so the retained `results.{1..8}.json` are unambiguously from the final frozen state rather than inherited from an earlier one. The results files were regenerated by this run and all 8 are on disk.

**Final deliverable inventory** (all present, no stray directories):
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`
- `worklog.md`
- `test_helpers/` — 9 modules; `test_suite/` — `conftest.py` + 15 test files (86 tests)
- `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`
- `workspace/implementation/` — 15 Python modules + `start.sh` + `requirements.txt` + `results.{1..8}.json`
- Only `tasks/task_3355_corps_member_recruitment_placement_certification_pathway/` exists for this index — no other `task_*` directory was created, per the caller's instruction.

**Pipeline complete.** Scenario "Corps Member Recruitment, Placement & Certification Pathway (Teach For America)", generated at "much harder than expert level": 10 entities, 5 state machines (29 transitions), 2 concurrency rules, 9 calculations, 29 ordered validations, 45 endpoints, 29 errors, 7 roles; 19 §1.8 difficulty instances and 44 non-stub §1.9 corner instances, all transcribed into tests with resolvable `Design:` tags.
