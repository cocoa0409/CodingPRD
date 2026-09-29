# Worklog — task_2797_special_olympics_local_program_administration

## Step 1: Create task directory — 2026-09-04T22:43:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2797_special_olympics_local_program_administration` and its `workspace/` subdirectory. Index 2797 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed (concurrent pipelines on this host would collide with auto-allocation).

## Step 2: Generate scaffold (subagent → prd-bench-scaffold-generator) — 2026-09-05T00:38:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Output directory** `/home/ubuntu/github/CodingPRD/tasks/task_2797_special_olympics_local_program_administration/`

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 3207 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1788 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4295 |

**SCAFFOLD.yaml (§1.0–§1.7)** — 13 entities, 11 state machines, 2 `concurrency_rules` (session-OCC, team-OCC), 13 calculations, 54 validations across the 12-priority ladder, 52 endpoints, 65 errors, 6 roles. `complexity_profile`: role_model `segregation_of_duties`, consistency `immediate`, topology `flat`, state-machine shape `parallel`, layers `[rate_threshold_triggers, cascading_side_effects, derived_field_reconciliation, ops_run_checkpoint, optimistic_concurrency, selector_policy]`. Neither design key appears in this file.

**§1.8 `SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 9 rule_ids, 19 instances (single top-level key `scaffold_difficulty_design`).

**§1.9 `SCAFFOLD_CORNER_DESIGN.yaml`** — all 9 claim-extraction-guide sections, 84 instances = 62 full recipes + 22 `excluded_because` stubs (entities 11, state_machines 16, calculations 13, validations 10, endpoints 6, errors 16, rbac 5, cross_cutting_layers 5, consistency_model 2).

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1078

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Extra verifications run beyond the linter: **0 of 65 errors untriggered**, 0 unknown `ERR_` ids in either design file, 0 duplicate instance names across the two files, every `excluded_because` target resolves to a real `rule_id / instance_name` pair in §1.8, no stub carries a `test_recipe`, no unbound `${var}` in any chain, and every formula-derived date literal recomputed in Python (e.g. 2026-06-15+1095 = 2029-06-14, 2026-07-05+365 = 2027-07-05, 2023-08-01+1095 = 2026-07-31).

Three fixes made while finishing: (1) deleted the unreachable `ERR_ATTENDANCE_NOT_FOUND` (no endpoint addresses an attendance-record id), leaving 65 errors; (2) `POST /unified-teams/{id}/members` now documents `member_type ∈ {ATHLETE, PARTNER}`, which the recipes rely on; (3) all Coach-role session writes now send `as_user_id: "${vol}"` — with `identity: entity_backed:Volunteer`, an opaque user id would have tripped the priority-5 `ERR_NOT_CREDENTIAL_OWNER` rule and made those fixtures fail for the wrong reason. I also stripped the `Generate task harder than expert level!` directive line from the `scenario:` key (it otherwise leaks into PRD.md downstream); the domain description itself is verbatim.

**Orchestrator verification:** confirmed all three files exist with the reported line counts; `grep -rn -i "harder than expert"` over the task dir returns no match, so the difficulty directive did not leak into any scaffold artifact (guarding the known leak-via-scenario-key failure mode).

## Step 3: Copy shared files — 2026-09-05T00:39:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (bash only, no subagent).

## Step 4: Generate PRD (subagent → prd-bench-doc-generator) — 2026-09-05T00:58:00.000Z

PRD complete and verified.

## Output

`workspace/PRD.md` — **420 lines, 14,448 words, 28 headings.**

## Heading list (verified via `grep -n '^#'`)

```
1   # Special Olympics Local Program API — Product Requirements Document
3   ## 1. Introduction
11  ## 2. Global Specifications & System-Wide Principles
13  ### 2.1. User and Role-Based Access Control
23  ### 2.2. API Response Structure
25  #### Standard Success Response Format
50  #### Standard Error Response Format
72  ### 2.3. Pagination
80  ### 2.4. Resource Identity, Timestamps and Row Versions
86  ### 2.5. The Logical Clock and Calendar Arithmetic
92  ### 2.6. Rejection Precedence
111 ### 2.7. Compliance Posture as the Program's Throttle
123 ### 2.8. Segregation of Duties in Credentialing
127 ### 2.9. Stale-Version Rejection on Session and Roster Writes
133 ### 2.10. Precision, Rounding and Ledger Conservation
139 ### 2.11. Cascades, Derived Counters and Nested Path Resolution
145 ## 3. Business Logic & Workflows
147 ### 3.1. Standing Up a Program and Registering Athletes
157 ### 3.2. Medical Clearance and the Two Athlete Dimensions
173 ### 3.3. Building a Credentialed Workforce
191 ### 3.4. Seasons, Practice Sessions and the Practice-Minute Ledger
209 ### 3.5. Unified Teams and Getting an Entry Accepted
225 ### 3.6. Divisioning, Merging Undersized Divisions, and Starting Over
247 ### 3.7. Results, Placement and the Advancement Waterfall
263 ### 3.8. Healthy Athletes Screening and Referral Follow-Up
275 ### 3.9. Support, Recognition and the Periodic Compliance Checkpoint
291 ## 4. Endpoint Definitions
350 ## 5. Error Code Catalogue
```

## Truncation verification: PASS

`tail -30` ends on `| ERR_SEASON_ENTRY_BUDGET_EXCEEDED | 409 |` — a complete final table row of §5, at a real section boundary, not mid-sentence. All 28 planned headings present; §4 and §5 both landed intact. Document ends at §5 with no audit footer.

## Content coverage

- **§4:** 52 endpoints (22 GET + 30 POST) in the 4-column Method/Path/Description/Authorized Role(s) table. Machine-diffed against the scaffold's `endpoints` block: 52/52 method+path pairs match exactly, **0 role-list mismatches**, no extras, none missing.
- **§5:** 65 error IDs in the 2-column table — exactly the scaffold's 65 (the 66th grep hit, `ERR_XXX`, is a placeholder inside a scaffold response example, correctly excluded).

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 128/128 `entities[].fields[].name` identifiers appear verbatim in backticks; 78/78 endpoint `input` identifiers (including `limit`, `offset`, `to_iso8601`, `expected_session_version`, `expected_team_version`) appear verbatim in backticks. 0 missing.

**Contract 2 — Rule Coverage: PASS.** 45/45 distinct state-machine state names present (71 transitions across the parallel machines). All 24 scaffold constants translated to natural language with their literal values inlined and spot-verified (1095/365/730/45/three quarters/0.20/0.50/1.15/3/8/1.20/2/5/500,000/80%/3,348/10%/three/18/15) — constant *names* deliberately absent per the no-pseudocode rule. Both OCC rules, all 12 validation priority bands, all 13 calculations, and the 6-step checkpoint cascade have narrative coverage. `POINTS_HIGHER_BETTER`/`TIME_LOWER_BETTER` are internal pseudocode variables, not field enums, and are rendered as prose ("time-scored and lower is better").

**Contract 3 — §3 Path Purity: PASS.** 389 unique backticked tokens in §3 (lines 145–290): zero start with `/`, zero are bare HTTP methods, zero combine method+path, and zero contain a slash at all. A wider scan of unbackticked §3 prose also found no path-shaped text and no bare `GET`/`POST`/`PUT`/`PATCH`/`DELETE` tokens. The only URL in the whole document, `/_clock/set_current_utc`, sits in the §4 table alone; §2.5 describes the clock capability in prose without the path.

**§2.2 fidelity:** `diff` against `section-2.2-response-structure.md` shows a single extra trailing blank line (paragraph separator) and no content difference — byte-identical text.

**Constraints honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was touched. A leak grep for `SCAFFOLD|DIFFICULTY_DESIGN|CORNER_DESIGN|test_recipe|Hard Contract` in PRD.md returns nothing.

## Scaffold gaps I had to resolve (flagging for review)

1. **Invented constants.** `URGENT_REFERRAL_DUE_DAYS` and `ADVISORY_REFERRAL_DUE_DAYS` are referenced at scaffold lines 811, 1544 and 2856 but **never defined anywhere**. I wrote **14 days (urgent)** and **30 days (advisory)** into §3.8, because `referral_due_on` is otherwise uncomputable. If the withheld design files pin different numbers, §3.8 will disagree with the tests.
2. **Age-group boundaries undefined.** Only the enum names and `AGE_GROUP_ORDINAL` exist. I derived and stated: `U12` under 12, `AGE_12_15` 12–15, `AGE_16_21` 16–21, `AGE_22_29` 22–29, `AGE_30_PLUS` 30+.
3. **Scaffold self-contradictions, resolved in favour of the state machine** (which states each rule twice): medical-form rejection target is `NONE`, not `HOLD`; prior `APPROVED` forms become `SUPERSEDED` at approval of a newer form, not at creation.
4. **Resolved in favour of the endpoint table:** certify is `CredentialingOfficer`-only (the state machine's actor line and a `complexity_profile` comment both suggest `ProgramManager` involvement; the FLAGGED case is `ERR_FLAG_OVERRIDE_REQUIRED`, not a role change); the sweep's credential-expiry step is step 1, not step 3.
5. **Resolved in favour of the skill spec:** header is `X-User-Role` (a validation entry says "X-Role"); list order is `created_at` ascending (one GET description says "newest first").
6. **Other picks:** `advancement_slots_per_division` range 1..8 (field constraint) over ">= 0"; contribution void decrements the ledgers by the stored integers first, then zeroes both `recognized_value_cents` and `match_credit_cents`.
7. **Preconditions with no declared error code** were mapped to the nearest existing code rather than inventing new ones — notably second concurrent `SUBMITTED` form → `ERR_MEDICAL_FORM_STATE_INVALID`, `email`/`team_name` uniqueness and future `completed_on` → `ERR_INVALID_REQUEST`, minor-at-certify → `ERR_MINOR_CANNOT_BE_COACH`, and the certified-coach-count floor surfacing as `ERR_PROGRAM_POSTURE_FROZEN`.

**Orchestrator verification (truncation guard):** independently ran `wc -l` (420), `tail -25` (ends on the complete `| ERR_SEASON_ENTRY_BUDGET_EXCEEDED | 409 |` table row — a real section boundary, not mid-sentence), `grep -c '^#'` (28 headings), and a leak grep for `harder than expert|SCAFFOLD|test_recipe` (no match). PRD.md is intact; no regeneration needed.

## Step 5: Generate unit tests (subagent → prd-bench-unit-test-generator) — 2026-09-05T02:01:00.000Z

All 13 test files are complete and verified. Final state of the generation:

## Output

**`test_helpers/`** (9 files, 2,291 lines) — `types.py`, `api_client.py` (52 endpoint methods + `canonical_instant()` sub-second normaliser), `api_errors.py` (65-member `ApiErrorId` + status map), `assertions.py`, `factories.py`, `fixtures.py`, `constants.py`, `test_users.py`, `__init__.py`. Plus `test_suite/conftest.py`.

**`test_suite/`** — 13 test files, **100 tests**:

| file | tests | source |
|---|---|---|
| test_01_credential_expiry_and_renewal_depth | 9 | queue A |
| test_02_athlete_dimensions_and_medical_depth | 7 | queue A |
| test_03_practice_ledger_and_overlap_depth | 10 | queue A |
| test_04_competition_pipeline_depth | 9 | queue A |
| test_05_support_ledger_depth | 4 | queue A |
| test_06_entity_contracts | 11 | Corner/entities |
| test_07_state_machines | 11 | Corner/state_machines |
| test_08_calculations | 7 | Corner/calculations |
| test_09_validations | 5 | Corner/validations |
| test_10_endpoint_behaviour | 5 | Corner/endpoints |
| test_11_error_catalogue | 13 | Corner/errors |
| test_12_rbac_and_identity | 5 | Corner/rbac |
| test_13_cross_cutting_and_consistency | 4 | Corner/cross_cutting_layers + consistency_model |

## Design-index coverage

- **Queue A (§1.8): 19 / 19 instances translated, 0 skipped** (39 tests).
- **Queue B (§1.9): 61 / 62 non-stub instances translated** (61 tests); 22 stub instances carrying `excluded_because` were correctly not translated. Per section: entities 11/11, state_machines 11/11, calculations 7/7, validations 5/6, endpoints 5/5, errors 13/13, rbac 5/5, cross_cutting_layers 2/2, consistency_model 2/2.
- **Skipped (1):** `Corner/validations/unified_ratio_check_runs_before_age_span_check` — `ERR_UNIFIED_RATIO_VIOLATION` and `ERR_UNIFIED_AGE_SPAN_EXCEEDED` both sit in §2.6 band 11 and the PRD declares intra-band ordering only for band 3, so the asserted winner is not uniquely derived.

A machine check confirms every test docstring ends with exactly one `Design:` line, all 100 tags resolve to a real `name:` in the source yaml, and no tag is dual- or mis-sectioned.

## PRD-first adjudications applied (design instance contradicted the contract)

- `unified_roster_duplicate_and_noncompliant_entry` / `stale_team_version_...`: the design claims `roster_status == FORMING` for a 1-athlete/1-partner roster; §3.5 makes that `NON_COMPLIANT` (FORMING only while a side is empty, COMPLIANT needs >=2 athletes) — tests assert `NON_COMPLIANT`.
- `resolving_last_urgent_referral_...`: design discipline `FIT_FEET` is not in the PRD enum — substituted `FUNFITNESS`/`OPENING_EYES`.
- `pledge_fulfilment_...`: design fulfils with `received_on` after the clock, which §3.9 refuses — the test advances the clock first.
- Ambiguous success code for `POST /unified-teams/{id}/members` (design says 200, §4 says creates return 201) — the accepted retry uses the lenient setup validator so the OCC claim, not the status code, is what is tested.
- Fixed a latent setup bug in `test_03`: an URGENT screening with `screened_on` after the clock date (§3.8 requires <= clock).

## Verification

`python3 -m py_compile` over all 23 `.py` files: **OK, zero failures**. Nothing was written under `workspace/` (still only `INSTRUCTION.md`, `PRD.md`, `implementation/`); `worklog.md` untouched; no sibling task directory read.

**Orchestrator note:** Steps 5 and 6 were launched as background subagents. Step 6 was dispatched immediately after Step 5 (in the following message rather than the same one), but before Step 5 had created either output directory — verified by the fact that `test_helpers/`/`test_suite/` did not yet exist at Step 6's spawn instant, and Step 6 was additionally given an absolute prohibition on reading them. Physical isolation of the implementation generator from the test suite was therefore preserved.

**Orchestrator verification:** `ls -d workspace/test_helpers workspace/test_suite` returns nothing — the known "test dirs land under workspace/" failure mode did not occur; both directories sit correctly at the task root.

## Step 6: Generate implementation (subagent → prd-bench-implementation-generator) — 2026-09-05T01:32:00.000Z

The implementation is complete and verified.

## Modules (all in `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `core.py` | 514 | constants, logical UTC clock, Decimal rounding, error/envelope helpers, auth, validators, pagination |
| `db.py` | 98 | 13 in-memory dicts, `new_row`/`touch`/`apply_changes`, per-request version-bump guard |
| `serialize.py` | 275 | 13 `ser_*` functions (volunteer `status`/`is_minor` derived at read time) |
| `derive.py` | 441 | FK lookup + 404 mapping, posture gate, counter/ledger recomputes, cascades, waterfall |
| `app.py` | 59 | `create_app`, blueprint registration, error handlers, `0.0.0.0:$PORT` |
| `routes_program.py` | 388 | programs, athletes, withdrawal, contributions, clock, 6-step compliance sweep |
| `routes_medical.py` | 197 | medical forms: submit, review, resubmit |
| `routes_workforce.py` | 263 | volunteers, credentials, screening/training/certify fork-join with SoD |
| `routes_practice.py` | 324 | seasons, open-practice, practice sessions, attendance |
| `routes_competition.py` | 597 | unified teams, entries, results, divisioning/merge/redivision/lock |
| `routes_health.py` | 140 | Healthy Athletes screenings + referral follow-up |
| `start.sh` | — | `exec python3 app.py`, guarded pip install, reads `$PORT`, foreground, `chmod +x` |
| `requirements.txt` | — | `flask>=2.0.0` |

Total 3,296 lines of Python.

**Endpoints: 52 implemented, exactly matching the 52 rows in the PRD's endpoint table** (verified by comparing the route decorator list against the PRD table row count).

**py_compile:** `python3 -m py_compile *.py` on all 11 modules — clean, no output (`PY_COMPILE_OK`). `__pycache__` removed afterwards.

**Smoke test:** launched twice, on ports 21437 and 21438, via `PORT=... bash start.sh` in the background; both booted in under 5 s from a fresh process. Beyond a liveness probe an end-to-end pipeline ran: clock set -> program -> 3 athletes -> medical form submit + approve -> volunteer -> credential screening/training/certify with 3 distinct user ids -> season -> open-practice -> practice session (as `Coach` with `X-User-ID` = volunteer id) -> 3 attendance records with `expected_session_version` -> 3 competition entries -> divisioning -> redivision -> divisioning -> lock-entries -> 3 results with waterfall -> unified team -> contribution -> compliance sweep. Every call returned the expected status and envelope; ratios came back at 4 dp (e.g. `3.5185`), placements/seed ranks and `INELIGIBLE_MAXING` were assigned correctly, and negative paths behaved (`ERR_SCREENING_STATE_INVALID` on a follow-up after RESOLVED, `ERR_REGISTRATION_STILL_OPEN` for divisioning before the deadline, `ERR_SEASON_STATE_INVALID` for lock after a revert to `PRACTICE_OPEN`, `ERR_ENTRY_STATE_INVALID` for a second result post). Both servers were shut down by their exact port-derived PIDs (1313735, 1327490); no broad `pkill` was used, and both ports confirmed dead afterwards.

Nothing was written outside `workspace/implementation/` (smoke scripts live in `/tmp`); `worklog.md`, `test_suite/`, `test_helpers/` and the difficulty/corner design files were never read or touched.

Two interpretation calls flagged by the generator:
- Screening a `WITHDRAWN` athlete returns `ERR_ATHLETE_ALREADY_WITHDRAWN` (409) — the PRD states the rule without naming a code, and this is the only catalogued code about withdrawal.
- Referral follow-up uses the single live-state gate the PRD spells out (`REFERRED`/`FOLLOW_UP_LOGGED`/`ESCALATED` accepted, `NOT_REQUIRED`/`RESOLVED` refused) rather than per-outcome transition preconditions, so repeated `LOGGED` calls increment `followup_count` instead of erroring.

## Step 7: Run tests and iterate (long-lived fix subagent) — 2026-09-05T02:35:00.000Z

Clean sweep achieved.

## Summary

**Iterations run:** 2 (iteration 1: 93/100 in all 8 rounds, same 7 failures every round — no flakiness; iteration 2: clean).

**Tests deleted:** none. One assertion removed under STEP 1c partial-coverage handling:
- `test_10_endpoint_behaviour.py::test_05_only_the_last_urgent_resolution_releases_the_medical_hold` — dropped `assert resolved_second["followup_count"] == 1`. BRANCH-ASYMMETRIC SIDE EFFECT: PRD §3.8 states the `followup_count` increment explicitly for the `LOGGED` and `REREFER` outcomes and renders the `RESOLVED` branch without it, so a faithful reader may legitimately leave the counter untouched on resolution. The test's covered assertions (hold survives the first resolution, releases on the last, posture/counter cascade) were all kept. Scaffold rule that drove it: `Corner/endpoints/resolving_last_urgent_referral_releases_medical_hold`.

**Fixes applied to `test_helpers/`:** none — the fixture/factory layer was faithful throughout.

**Fixes applied to `test_suite/`:**
- `test_10_endpoint_behaviour.py` (3 sites), `test_11_error_catalogue.py` (1), `test_12_rbac_and_identity.py` (1) — read `body["response_type"]` instead of `body["meta"]["response_type"]`. PRD §2.2 places `response_type` at the top level of the envelope, not inside `meta`; §2.2 also says the error `meta` "contains only `api_request_id` and `api_request_timestamp`". These raised `KeyError: 'response_type'`.
- `test_06_entity_contracts.py::test_08_...` — assert `current_medical_form_id is None` after *filing* a form. PRD §3.1: "`current_medical_form_id` is null until a form is approved"; §3.2 sets it only on approval. The old assertion contradicted the PRD.
- `test_07_state_machines.py::test_08_fulfilling_an_already_received_pledge_is_refused` — the retry's `received_on` changed from `2026-08-02` to `2026-08-01`. The clock is `2026-08-01`, and PRD §3.9 requires `received_on` to "fall on or before the clock date", so the old payload tripped the band-4 schema check (`ERR_INVALID_REQUEST`) before the band-6 state check the test is about. Now it isolates `ERR_CONTRIBUTION_STATE_INVALID`.
- `test_12_rbac_and_identity.py::test_02_the_wrong_role_is_403_on_four_otherwise_valid_requests` — certify a second coach (`fx.setup_program_with_second_coach(world)`) before `open-practice`. `_role_matrix_world()` deliberately leaves its only credential at `READY_TO_CERTIFY`, so the program was `FROZEN`; PRD §3.4 requires "at least one live certified coach credential" to open the window, and the implementation correctly returned `ERR_PROGRAM_POSTURE_FROZEN`. `world["credential"]` still stays `READY_TO_CERTIFY` for the 403 probe and the closing certify.

**Fixes applied to `implementation/`:** none. All seven failures traced to test-side misreadings of PRD prose; no PRD-required check was removed or weakened.

**Final sweep (per-round `passed`/`total`, quoted from `results.$i.json`):** round 1 100/100, round 2 100/100, round 3 100/100, round 4 100/100, round 5 100/100, round 6 100/100, round 7 100/100, round 8 100/100.

`worklog.md` was not touched.

**Orchestrator verification (Step 7 sweep-artifact guard):** independently parsed all 8 `workspace/implementation/results.*.json` files with `json.load` and confirmed `passed == total == 100` in every one. The result files exist on disk with complete JSON — the sweep genuinely ran; this is not a subagent claiming a clean sweep with no artifacts behind it.

**Step 8 skip decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 5 `test_suite/` fixes plus 1 partial-coverage assertion removal, so Step 8 runs with those items as its `<step_7_diff>` focus list. Note that with 0 `implementation/` fixes a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome — the Step 7 items are test-side misreadings, and PRD.md may already pin every one of them correctly.

## Step 8: Finalize PRD (subagent → PRD finalizer) — 2026-09-05T02:31:00.000Z

PRD_FINALIZED.md written.

## Line counts
- `PRD.md`: 420 lines / `PRD_FINALIZED.md`: 420 lines — 0 lines added or removed; 2 of 420 lines revised in place (**0.48% of lines touched, 0% line-count delta**).

## Changes
- **§3.8 (referral follow-up)** — *revise* — added one clause to the `RESOLVED` paragraph pinning that resolution leaves the screening's `followup_count` unchanged, unlike the `LOGGED` and `REREFER` outcomes — `implementation/routes_health.py:122-124` (the `else:` branch sets only `referral_status` then `db.touch`; contrast `:113` and `:118`).
- **§3.9 (fulfilling a pledge)** — *revise* — pinned `received_on` as required and a future `received_on` as a band-4 request-shape violation returning `ERR_INVALID_REQUEST` (400), evaluated ahead of the `PLEDGED` state precondition — `implementation/routes_program.py:246-252`.

## Pre-edit search log

**Edit 1 — subject: `followup_count` on a screening**
- (b) Paths enumerated: `grep -rn "followup_count" implementation/*.py` → only 4 sites. `routes_health.py:88` (initialised 0 at creation), `:113` (`LOGGED` +1), `:118` (`REREFER` +1), `:122-124` (`RESOLVED` — no touch), `serialize.py:254` (read-only). Also read `routes_program.py:354-363` (compliance-sweep step four, `REFERRED → ESCALATED`) to confirm escalation does not touch the counter, and `routes_health.py:18-27` / `:100-140` for the whole follow-up endpoint. Cross-checked `test_suite/test_10_endpoint_behaviour.py::test_05` to confirm the failing flow had zero prior follow-ups, i.e. the impl leaves the counter at 0 rather than merely skipping a second increment.
- (c) Adjustment: scoped the sentence to the `RESOLVED` outcome ("leaves … exactly as it was") rather than writing a global claim such as "only `LOGGED` and `REREFER` ever change `followup_count`", which would have implicitly re-specified the sweep's escalation path. Also deliberately did **not** extend the sentence to `last_followup_note` (the impl likewise leaves it alone on `RESOLVED`, and on `REREFER`) — that is a pre-existing PRD silence with no Step 7 trace, so pinning it was out of scope.

**Edit 2 — subject: the fulfilment `received_on` vs. clock check and its band**
- (b) Paths enumerated: `routes_program.py:241-260` (fulfil: `req_date_field` → required, `received_on > clock_date()` → `bad_request`, *then* the `PLEDGED` check); `routes_program.py:192-238` (contribution creation — `opt_date_field`, **no** clock comparison, so creation accepts a future `received_on`); `routes_program.py:263-278` (void — no date input); `core.py` `req_date_field`/`bad_request` (confirmed `bad_request` maps to `ERR_INVALID_REQUEST` 400); and for consistency of the "date-after-clock => 400" pattern elsewhere, `routes_health.py:62-63` (`screened_on`) and the credential screening/training `completed_on` checks that PRD §3.3 already labels `ERR_INVALID_REQUEST`.
- (c) Adjustment: confined the new wording to *fulfilment* ("It carries a required `received_on` …") and did not touch §3.9's creation paragraph, because the create endpoint does not validate `received_on` against the clock — a general "a contribution's `received_on` may never be in the future" sentence would have been a brand-new mismatch. Phrased the precedence as "reported ahead of the state precondition that follows" rather than restating §2.6's band list, to avoid re-scoping band 4 globally.

## Items intentionally left unedited (PRD already determines the behavior)
- `response_type` at envelope top level and error `meta` holding only the two request fields — `core.py:269/279/284` match §2.2 verbatim; the test was reading `meta.response_type`.
- `current_medical_form_id` null after *filing* — only `routes_medical.py:154` (approval) and the sweep's clearing at `routes_program.py:333-334` ever write it; §3.1/§3.2 already say this.
- `open-practice` requiring a live certified coach and surfacing as `ERR_PROGRAM_POSTURE_FROZEN` — `routes_practice.py` open_practice matches §3.4 verbatim; the test's world simply had no certified coach.

**Orchestrator verification:** ran `diff workspace/PRD.md workspace/PRD_FINALIZED.md` and confirmed exactly 2 changed lines (271 and 285), both in-paragraph revisions with no new sections and no line-count change; `cmp` confirms the files differ. The reported edits match the actual diff.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (3 sequential module-partitioned subagent passes) — 2026-09-05T03:05:00.000Z

**Orchestrator design decision.** Step 9 was run as three *sequential* passes over one shared `workspace/PRD_COMPLETED.md`, each pass owning a disjoint slice of `implementation/`. A single subagent cannot hold an exhaustive walk of 3,296 lines of implementation plus a 420-line/103 KB PRD in context, and the known failure mode is a subagent that emits a byte-identical `PRD_COMPLETED.md` because the scan never really happened. Pass 1 alone performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to `cp` (that would have destroyed the earlier passes' edits) and were told what the earlier passes had already committed so they would not re-litigate or duplicate wording. Slices: pass 1 = `core.py`/`db.py`/`app.py`/`serialize.py`/`derive.py` (cross-cutting, mostly §2.x); pass 2 = `routes_program.py`/`routes_medical.py`/`routes_workforce.py` (§3.1–§3.3, §3.9); pass 3 = `routes_practice.py`/`routes_competition.py`/`routes_health.py` (§3.4–§3.8).

**Totals across the three passes: 54 edits — 34 ambiguity-pins, 19 mismatch-revisions, 1 (pass-1 §2.4) combining both. `PRD_FINALIZED.md` 420 lines / 103,200 bytes → `PRD_COMPLETED.md` 420 lines / 121,441 bytes (+18,241 bytes, +17.7%); line count unchanged and heading list byte-identical, so every edit was an in-paragraph insert or revision and no new section was added.**

### Pass 1 — cross-cutting slice (`core.py`, `db.py`, `app.py`, `serialize.py`, `derive.py`)

Performed the `cp`. 420 lines / 103,200 bytes → 420 lines / 109,134 bytes (+5,934; 13 lines changed). 9 ambiguity-pins, 4 mismatch-revisions.

- §2.2 (line 44) — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9, minted per request — `core.py:259-261`
- §2.2 (line 45) — insert — ambiguity — `api_request_timestamp` comes from the logical clock, so two requests without a clock change share it — `core.py:264-265`
- §2.3 (line 74) — insert — ambiguity — an empty-valued query parameter (`?limit=`) reads as omitted; same for optional filters — `core.py:446-447, 466-467`
- §2.3 (line 76) — insert — ambiguity — `created_at` ties break by server insertion sequence, everywhere the doc orders by `created_at` (pagination, divisioning, seeding, waterfall) — `core.py:501-502`, `db.py:39-41`
- §2.4 (line 82) — revise — mismatch — `version` bumps at most once per row per request; a row the request created stays at `version` 1; an all-identical write is not a mutation; plus every declared field always present as `null` rather than omitted, and all instants canonicalised to `...mmmZ` (including client-supplied `scheduled_start`) — `db.py:71-94`, `core.py:139-142`, `routes_practice.py:173-176`
- §2.4 (line 84) — insert — ambiguity — undeclared body fields are ignored, not rejected — `core.py:316-326`
- §2.5 (line 88) — insert — ambiguity — clock-set needs only `X-User-Role`; `X-User-ID` may be absent since no row mutates — `routes_program.py:285-287`, `core.py:290-299`
- §2.6 band 4 (line 99) — insert — ambiguity — absent/empty body reads as `{}`, non-object body rejected; optional field as `null` == omitted while required `null` fails; booleans strictly excluded from numeric fields and vice versa — `core.py:316-334, 348-407`
- §2.7 (line 113) — revise — mismatch — counters/ledgers are re-derived wholesale (so §3's "increments by one" is effect, not mechanism), an unchanged recompute bumps nothing, and reads never recompute (posture goes stale until the next write or checkpoint) — `derive.py:129-190`, `db.py:85-94`
- §2.10 (line 135) — insert — ambiguity — ratio fields serialise as JSON numbers (`0.0`, `1.15`), not fixed-width strings; money as JSON integers — `core.py:232-236`, `serialize.py:24`
- §2.11 (line 141) — revise — mismatch — cascade version bumps are once per request per row and only for rows actually changed; an emptied division keeps its last ability bands/spread ratio instead of nulling them — `db.py:71-94`, `derive.py:218-230`
- §3.3 (line 175) — revise — mismatch — `is_minor` and `status` are re-derived on every read (so `is_minor` flips as the clock passes 18 with no write); `INACTIVE` requires at least one credential, and a `CERTIFIED`-but-lapsed credential reads `PROSPECT` until the checkpoint expires it — `serialize.py:77-107`
- §5 preamble (line 352) — insert — ambiguity — unrouted path → 404, unsupported method → 405, unexpected server failure → 400, all carrying `ERR_INVALID_REQUEST` — `app.py:34-49`

Cross-checks that needed no edit: all 13 serializer field sets are already named in PRD prose (mechanically verified both directions — no response field undocumented, no documented field unserialised); `posture_gate`'s 4/9 blocked-operation split, the NOT_FOUND→error-code map, `practice_totals`, `recompute_team`, `recompute_season_counts` and `run_waterfall` ordering/maxing/slot rules already match the PRD uniquely; band-3-before-band-4 ordering confirmed in route bodies.

### Pass 2 — program / medical / workforce slice

420 lines / 109,134 bytes → 420 lines / 114,273 bytes. 15 ambiguity-pins, 6 mismatch-revisions. No `cp`, no full rewrite.

- §3.1 — insert — ambiguity — `birth_date` is never compared to the logical clock; a future date is accepted and stored — `routes_program.py:83`
- §3.1 — insert — ambiguity — withdrawal's entry-void cascade also re-derives each affected season's `entry_count`/`divisioned_entry_count` — `routes_program.py:156` → `derive.py:373-376`
- §3.2 — insert — ambiguity — omitted/`null` `restrictions` stores `null` (not `["NONE"]`) and counts as unrestricted wherever read — `routes_medical.py:29-35, 68-71`
- §3.2 — revise — mismatch — filing moves the medical dimension to `PENDING_REVIEW` from *any* non-`HOLD` value (incl. `CLEARED`/`RESTRICTED` renewals); `HOLD` sticks; filing re-derives neither program counters nor team rosters — `routes_medical.py:74-77, 117, 196`
- §3.2 — insert — ambiguity — review is gated on form state only: a withdrawn athlete's still-`SUBMITTED` form stays reviewable, registration untouched — `routes_medical.py:131-159`
- §3.2 — revise — mismatch — approval writes the medical dimension unconditionally, so it lifts a `HOLD` while the urgent referral stays open and still counted — `routes_medical.py:150-159`
- §3.2 — insert — ambiguity — resubmit keeps `reviewed_by_user_id`, leaves `approved_at` null, and is not blocked by another `SUBMITTED` form of the same athlete — `routes_medical.py:189-196`
- §3.3 — insert — ambiguity — volunteer `date_of_birth` likewise unchecked against the clock — `routes_workforce.py:38`
- §3.3 — insert — ambiguity — the minor-coach check is evaluated **ahead of** the role-class comparison (`ERR_MINOR_CANNOT_BE_COACH` wins over `ERR_ROLE_CLASS_MISMATCH`) — `routes_workforce.py:94-100`
- §3.3 — revise — ambiguity — `vendor_reference` is 1–120 chars — `routes_workforce.py:131`
- §3.3 — revise — ambiguity — `curriculum_code` is 1–120 chars — `routes_workforce.py:184`
- §3.3 — revise — mismatch — a `DISQUALIFYING` result is also recordable from `EXPIRED`/`RENEWAL_IN_PROGRESS`, stores all four branch fields, and leaves/clears `screening_expires_on` to null — `routes_workforce.py:140-163`
- §3.3 — revise — mismatch — `MINOR_AS_COACH` is declared but never written by any transition; `DISQUALIFYING_SCREENING` is the only `denial_reason_code` ever stored — `routes_workforce.py:95-97, 160, 247-249`
- §3.3 — revise — mismatch — certifying from `RENEWAL_IN_PROGRESS` requires both branch *expiries* live, not both branches re-recorded — `routes_workforce.py:231-240`
- §3.3 — revise — ambiguity — an empty or whitespace-only `flag_override_reason` also draws `ERR_FLAG_OVERRIDE_REQUIRED` — `routes_workforce.py:241-244`
- §3.3 — insert — ambiguity — certification, disqualifying denial and checkpoint expiry each re-derive the `roster_status` of teams where the volunteer is a partner — `routes_workforce.py:163, 261`; `routes_program.py:317-318`
- §3.3 — insert — ambiguity — a renewal `completed_on` not strictly later than the branch's previous date yields `ERR_CREDENTIAL_STEP_ALREADY_RECORDED` (409) — `routes_workforce.py:146, 199`
- §3.9 — insert — ambiguity — `received_on` at creation is stored as supplied with no clock comparison (future dates and pledge dates accepted); only fulfilment constrains it — `routes_program.py:201, 233`
- §3.9 — revise — ambiguity — non-numeric hours also yield `ERR_VOLUNTEER_HOURS_REQUIRED`; hours on the other four types and a missing `stated_value_cents` there are `ERR_INVALID_REQUEST`; `VOLUNTEER_HOURS` may carry `stated_value_cents` and ignores it — `routes_program.py:200-217`
- §3.9 — revise — ambiguity — sweep step three reads the second lapse condition off a null `current_medical_form_id`, so such an `ACTIVE` athlete lapses even with a future `registration_expires_on` — `routes_program.py:342-352`
- §3.9 — revise — mismatch — sweep step four escalates **every** overdue `REFERRED` referral, `ADVISORY` included, not only urgent ones — `routes_program.py:355-363`

Pass 1 integrity confirmed intact by spot-check (§3.3 re-derived-on-read sentence, §5-preamble 404/405 sentence, §2.4 canonical-timestamp clause — one occurrence each).

### Pass 3 — practice / competition / health slice

420 lines / 114,273 bytes → 420 lines / 121,441 bytes. 10 ambiguity-pins, 9 mismatch-revisions. No `cp`, no full rewrite.

- §3.4 — revise — mismatch — the four scheduling gates are evaluated in §2.6 band order, not narration order: season state, then start-in-past, then overlap, then credential-liveness last (so a past start under a lapsed credential yields `ERR_SESSION_START_IN_PAST`) — `routes_practice.py:143-169`
- §3.4 — insert — ambiguity — only role class, status and expiry of `coach_credential_id` are examined; its volunteer need not belong to the season's program — `routes_practice.py:167`
- §3.4 — insert — ambiguity — `minutes_present` above the session duration is a band-4 `ERR_INVALID_REQUEST`, reported ahead of the stale-version 412 — `routes_practice.py:243-250`
- §3.4 — insert — ambiguity — attendance applies no cross-program check to `athlete_id`, and no upper time bound (a row may be filed after `scheduled_end`) — `routes_practice.py:241, 270-274`
- §3.5 — revise — mismatch — `team_name` uniqueness is a band-4 shape rule evaluated ahead of the season-state and posture gates, so a duplicate on a non-`PRACTICE_OPEN` season draws the 400 — `routes_competition.py:49-56`
- §3.5 — insert — ambiguity — `member_type` is validated before `member_id` resolves; the 404 is `ERR_ATHLETE_NOT_FOUND` / `ERR_VOLUNTEER_NOT_FOUND` by declared type, never `ERR_PARTICIPANT_NOT_FOUND` — `routes_competition.py:75-82`
- §3.5 — insert — ambiguity — appending a member has no season-state gate (posture only), and neither member kind must belong to the season's program — `routes_competition.py:71-89`
- §3.5 — insert — ambiguity — `participant_type` validated before the polymorphic resolution; `event_code`/`skill_score` after it; team program membership read through the team's season — `routes_competition.py:186-204`
- §3.6 — insert — ambiguity — partitions are walked in ascending lexicographic `(participant_type, event_code, age_group)` order (age group by literal string, so `U12` last), which fixes division creation sequence and thus the merge tie-breaks — `routes_competition.py:379-386`
- §3.6 — revise — mismatch — redivision's `ERR_NO_ELIGIBLE_ENTRIES` population is entries in `SUBMITTED` **or** `DIVISIONED` with any `division_id`, not divisioning's null-division candidate set; no deadline check — `routes_competition.py:545-550`
- §3.6 — insert — ambiguity — the revert leaves `divisioning_run_count` unreset — `routes_competition.py:565`
- §3.6 — revise — mismatch — dropped the phantom "requires every `DIVISIONED` entry to carry a non-null `division_id`"; such entries (and those in a non-`VALID` division) are silently passed over; undersized check runs after the posture gate — `routes_competition.py:574-594`
- §3.7 — revise — mismatch — the entry's own state is tested before the season's, so `/result` on a `DIVISIONED` entry of a `DIVISIONED` season yields `ERR_ENTRY_STATE_INVALID`; season state code named; `disqualified` without a reason code is a band-4 400 — `routes_competition.py:291-303`
- §3.7 — insert — ambiguity — a disqualification still stores the submitted `result_value`; `advancement_status` stays `NOT_ADVANCED` — `routes_competition.py:305-310`
- §3.8 — insert — ambiguity — future `screened_on` → `ERR_INVALID_REQUEST` (400) ahead of withdrawn-athlete `ERR_ATHLETE_ALREADY_WITHDRAWN` (409); `finding_note` null when omitted; screening list also filters `discipline` — `routes_health.py:35, 62-66`
- §3.8 — revise — mismatch — an `URGENT` finding drops the athlete to `HOLD` only from `CLEARED`/`RESTRICTED` (`NONE`/`PENDING_REVIEW` keep their value) while the rest of the cascade runs regardless; added the season `entry_count` re-derivation and the unified-team `roster_status` re-derivation — `routes_health.py:91-96`
- §3.8 — revise — mismatch — `LOGGED` and `REREFER` are both accepted from all three live states (including `FOLLOW_UP_LOGGED → FOLLOW_UP_LOGGED`); `REREFER` uses clock+14 whatever the severity and ignores `note` — `routes_health.py:111-121`
- §3.8 — revise — mismatch — hold release additionally requires the dimension to still read `HOLD`; a hold already lifted by a newer approved form is not overwritten — `routes_health.py:125-127`
- §3.8 — revise — mismatch — resolution re-derives team `roster_status`, and `unresolved_urgent_referral_count` is re-derived on every urgent resolution whether or not the hold released — `routes_health.py:137-139`

Pass 1 / Pass 2 integrity verified: the diff against `PRD_FINALIZED.md` grew from 27 to 41 changed line groups, all 14 new groups inside §3.4–§3.8, and spot-checked markers from both earlier passes each still return exactly one hit.

### Orchestrator final verification

- `cmp -s workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` → **DIFFERS**. The known "byte-identical `PRD_COMPLETED.md` means the scan never ran" failure mode did not occur.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md | grep -c '^[0-9]'` → 41 changed line groups.
- `diff <(grep '^#' PRD_FINALIZED.md) <(grep '^#' PRD_COMPLETED.md)` → empty: heading list byte-identical, confirming no new sections were added and every edit stayed in-paragraph.
- Sizes: `PRD.md` 102,828 B → `PRD_FINALIZED.md` 103,200 B → `PRD_COMPLETED.md` 121,441 B, all 420 lines.
- `find workspace/implementation test_suite test_helpers -name '*.py' -newer workspace/implementation/results.1.json` → empty. No `.py` file was modified after the final passing sweep, so Step 9 was documentation-only and the 8×100/100 result stands for the artifacts as they now sit on disk.
- All 8 `workspace/implementation/results.*.json` still present; `find . -name worklog.md` returns only the task-root copy (no cwd-drift stray under `workspace/`); no stray `workspace/test_suite` or `workspace/test_helpers`.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
