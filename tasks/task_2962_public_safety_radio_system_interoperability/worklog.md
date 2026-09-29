# Worklog — task_2962_public_safety_radio_system_interoperability

## Step 1: Create Task Directory — 2026-09-05T22:53:18.791Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2962_public_safety_radio_system_interoperability` and `.../workspace`. Index 2962 was pre-assigned by the orchestrator invocation (no scan of ./tasks/, no auto-allocation) because up to 32 pipelines run concurrently on this host and auto-allocation would collide.

## Step 2: Generate Scaffold — 2026-09-06T00:14:00.000Z

Scaffold generation for task 2962 is complete and lint-clean.

## Deliverables

`/home/ubuntu/github/CodingPRD/tasks/task_2962_public_safety_radio_system_interoperability/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2577 | 134,398 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1593 | 102,686 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3686 | 223,755 |

All three `yaml.safe_load` cleanly. `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; each design file has exactly its one required top-level key.

## Lint verdict (verbatim)

```
SCAFFOLD 1.8/1.9 -> 1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2962_public_safety_radio_system_interoperability/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2962_public_safety_radio_system_interoperability/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2962_public_safety_radio_system_interoperability/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  1.5 endpoints declared:    54
  1.1 entities declared:     11
  1.8 instances scanned:     18
  1.9 instances scanned:     68
  Calls scanned (1.8+1.9):  703

VERDICT: clean lint — all 1.8/1.9 calls conform to 1.5 and all 1.1 FKs have reverse-reachability in 1.5.
```

## Content shape

- **1.0–1.7**: domain `public-safety-radio-interoperability`, prefix `/radio-system`; 11 entities, 7 state machines (parallel shape), 3 `concurrency_rules`, 12 calculations, 39 validations in one priority ladder, 54 endpoints, 45 errors, 8 roles (`segregation_of_duties` role model, `graph` topology, `immediate` consistency).
- **1.8 depth probe**: 9 difficulty rules x 2 differentiated instances = 18.
- **1.9 breadth probe**: 82 instances across all nine claim-extraction sections — entities 10, state_machines 12, calculations 13, validations 17, endpoints 4, errors 13, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1. 68 are full recipes; 14 are `excluded_because:` stubs (no `test_recipe`), and every stub's `difficulty_instance` reference resolves by name into `SCAFFOLD_DIFFICULTY_DESIGN.yaml`. All 100 instance names are unique across the two design files.
- Every error id in the 45-entry catalogue is triggerable from 1.8/1.9; all three `concurrency_rules` entries have an OCC stale-version instance (site coverage and template revision as recipes, fee reassessment via a stub into the difficulty file), and each declared complexity layer (`optimistic_concurrency`, `cascading_side_effects`, `version_pinning_on_approval`, `conditional_feature_flags`) has its own instance.

## Notes

- The directive line "Generate task harder than expert level!" was deliberately **excluded** from `scenario:` (verified: `'harder than expert' in scenario` is `False`), so it cannot leak into PRD.md at Step 4. Only the numbered 2962 domain description is present.
- No sibling `task_*/` directory was listed, read, globbed, or grepped at any point; the scaffold came solely from the scenario text plus the generator skill and its `claim-extraction-guide.md`.
- `workspace/` and `worklog.md` are intact and untouched. Scratch use was confined to `.scratch/step2/` (now empty); nothing outside it was deleted.

Orchestrator verification: independently grepped `SCAFFOLD.yaml` for "harder than expert" / "expert level" — zero hits, so the Step 2 difficulty directive cannot reach PRD.md.

## Step 3: Copy Shared Files — 2026-09-06T00:15:28.803Z

Copied `INSTRUCTION.md` (1424 bytes) from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-06T00:31:37.782520157Z

PRD.md is complete at `.../workspace/PRD.md` — 465 lines, 97,263 bytes, written incrementally in 13 appends. Ends cleanly at the last row of the Section 5 table. `.scratch/step4/` removed; `.scratch/step2/`, `worklog.md`, all three `SCAFFOLD*.yaml`, and `workspace/INSTRUCTION.md` untouched. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory was read.

Top-level section list: 1. Introduction / 2. Global Specifications & System-Wide Principles / 3. Business Logic & Workflows / 4. Endpoint Definitions / 5. Error Code Catalogue. Plus 19 `###` subsections: 2.1-2.10 and 3.1-3.9.

Last 5 lines verbatim:
```
| `ERR_REVISION_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_AGENCY_VOTING_SUSPENDED` | 403 Forbidden |
| `ERR_FEE_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_NO_PREEMPTABLE_TALKPATH` | 409 Conflict |
```

## Hard Contract 1 — Field-Name Coverage: PASS
Extracted every `entities[].fields[].name` (11 entities) plus every `request_body` / `input` / `query_params` / `path_params` identifier across all 54 endpoints from SCAFFOLD.yaml, normalised optional-marker `?` suffixes, and diffed against the set of backtick-delimited tokens in PRD.md (fenced code blocks stripped first so the fences could not desync inline-code pairing). Total distinct scaffold identifiers: 134. Absent from PRD.md in backticks: 0.

## Hard Contract 2 — Rule Coverage: PASS
- 39/39 validations — every `error_id` appears in Sections 1-3, and 2.4 states the full 13-group rejection ladder with group 13 explicitly sub-ordered by ascending validation priority.
- 12/12 calculations — every output field of every calculation appears in prose; all variant pairs are given as sibling branches (`agency_fee_assessment` SNAPSHOT/PRORATED, `fleet_migration_readiness` STRICT/PLANNED, `talkpath_grant_decision` NORMAL/PRIORITY/EMERGENCY).
- 7/7 state machines — SubscriberUnit (parallel `provision_status` x `key_status`), ProgrammingChangeRequest (cyclic revision loop, limit stated as the literal 2), SiteEvent (branching by `event_class`), Keyset, Talkgroup, InteropPatch, TalkpathRequest. A mechanical sweep of state/enum tokens found only these absences, all intentional: `POST` (HTTP methods barred from Section 3 by Contract 3, appear only in Section 4), `NULL` (rendered as "null"/"unset"), `ASC`/`DESC` (rendered as "ascending"/"descending"), `MAX_REVISIONS` and `PATCH_RETENTION_MIN_DAYS` (constants expanded to literals 2 and 180), and `BUSY` — only the internal decision label of `talkpath_grant_decision`; the persisted enum is `BUSIED`, which is present.
- 3/3 concurrency rules — `expected_agency_version`, `expected_site_version`, `expected_template_version`, each with `ERR_STALE_VERSION` / 412.
- Cascades — keyset-compromise cascade, site-event Tier-3 four-link cascade, billing-sanction four-link cascade, unit suspension/retirement talkpath eviction, and every derived-counter recomputation are all spelled out, including which counters are query-defined and the single monotonic exception (`peak_talkpaths`).
- No pseudocode operator and no fuzzy word survives anywhere in the document — both greps return empty.

## Hard Contract 3 — Section 3 Path Purity: PASS
Scanned lines 165-355 (all of Section 3): backticked tokens beginning with `/`: 0. Bare HTTP method words: 0. Method+path combinations: 0. Endpoints are referenced in Section 3 only by state-transition framing, by role plus action verb, or by capability description.

Structural checks also confirmed: Section 4 has exactly 4 columns and all 54 endpoints with no duplicates, extras, or omissions; Section 5 has exactly 2 columns and all 45 errors with statuses matching the scaffold exactly; 2.2 is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`; there is no audit footer. One correction to carry forward: the error catalogue has 45 entries, not 43 as an earlier note stated.

Orchestrator truncation verification (the known doc-generator failure mode): independently ran `wc -l -c`, `grep -n '^## '`, and `tail -25` on PRD.md. The file ends at `| ERR_NO_PREEMPTABLE_TALKPATH | 409 Conflict |` — a complete final table row of the last section, not mid-sentence. All 5 top-level sections and all 19 subsections present. No regeneration needed. Also grepped PRD.md for "harder than expert" / "expert level" / "scaffold" — zero hits.

## Step 6: Generate Implementation — 2026-09-06T01:12:42.408073130Z

Implementation complete.

## Deliverable

`.../workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip, `exec python3 app.py`) | 8 |
| `requirements.txt` (`flask>=2.3.0`) | 1 |
| `app.py` — 12 blueprints, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0:$PORT` (default 10000), `strict_slashes=False` | 89 |
| `db.py` — in-memory `Store`, logical clock, `base_row`, `touch` (one version bump per row per request via `g.touched_rows`) | 95 |
| `errors.py` — all 44 error ids + PRD Section 5 status codes | 106 |
| `response.py` — Section 2.2 envelope, `req_...` id, 3-frac-digit ISO | 74 |
| `serialize.py` — 11 entity serializers | 243 |
| `validate.py` — precedence steps 1-7, pagination, filters | 325 |
| `compute.py` — every constant + calculation/cascade | 584 |
| `enums.py`, `common.py` (`list_endpoint`, `require_scope`, `check_occ`) | 62 / 34 |
| `routes/` — agencies 140, changes 161, units 163, patches 154, siteevents 202, talkpaths 118, talkgroups 109, campaigns 109, keysets 99, sites 93, templates 92, misc 32, `__init__` 0 | 1472 |
| **Total** | **3084** |

## Endpoint coverage: 54 / 54

Dumped `app.url_map` and diffed it against the scaffold's `method`+`path` pairs — exact match on all 54, no extras, no omissions (agencies 7, sites 4, templates 5, change-requests 6, units 4, keysets 5, otar-campaigns 4, talkgroups 4, interop-patches 5, site-events 4, talkpath-requests 4, clock + migration-readiness 2).

## `python3 -m py_compile`

Passes on all 22 modules (`py_compile: ALL 22 MODULES OK`).

## Smoke test (port 39621, own PID only, killed by exact PID)

No 500s and no tracebacks anywhere in the server log across ~90 requests. Verified:

- Envelope/meta shape on object, array (limit/offset/total_count/has_more) and error responses; `api_request_timestamp` always the logical clock.
- Fresh boot on a second port: all collections empty, clock exactly `2026-08-01T00:00:00.000Z` — nothing seeded, nothing persisted.
- Auth: missing/blank headers -> `ERR_UNAUTHENTICATED`; wrong role -> `ERR_UNAUTHORIZED`; agency-backed `X-User-ID` that isn't a MemberAgency -> `ERR_UNAUTHENTICATED`; cross-agency write -> `ERR_AGENCY_SCOPE_VIOLATION`.
- Coverage engine: 995/1000 -> tier A, `99.0` MISSION_CRITICAL; 940/1000 on a BATTERY_ONLY site -> tier B, `90.5` GENERAL (single-pass tier selection + 2.0pp battery penalty). Stale pin -> `ERR_STALE_VERSION` 412.
- Fee assessment SNAPSHOT: 3 billable units -> 12600c, +8% PATCH_AUTHORITY surcharge -> `13608`, `payment_due_at` = period_end + 30d; payment + governance-standing (quorum weights) correct.
- Full template -> change-request cycle: publish, revision (lineage v2, parent RETIRED), submit, SoD rejection (`ERR_SEGREGATION_OF_DUTIES`), approve with pins (`pinned_template_version` 2 / record 5), deploy -> DEPLOYED, 3 units re-templated.
- Keyset approve -> OTAR execute (3 rekeyed) -> compromise: units -> `KEY_STALE` with `active_keyset_id` retained (per cascade link 2), `loaded_unit_count` -> 0, re-compromise -> `ERR_KEYSET_NOT_ACTIVE`.
- Interop patch request -> ACTIVATE (`recorder_retention_days_at_activation` snapshot) -> RELEASE (`OPERATOR`, duration recomputed).
- Talkpath waterfall: `usable = capacity - 1`, GRANTED with `priority_class_at_grant` snapshot (null on BUSIED), release -> `hold_seconds` 90, `busy_talkpaths` back to 0 while `peak_talkpaths` stays 1; double release -> `ERR_INVALID_STATE_TRANSITION`.
- Outage arm end-to-end on a BATTERY_ONLY site (generator contribution correctly dropped: 100 min, not 640): BACKUP_ENGAGED -> DEGRADED, ESCALATE tier 1->2->3 monotonic, tier 3 cascade set EMERGENCY_ONLY, preempted the NORMAL talkpath (`PREEMPTED`, count 1), recomputed counters, then RESTORE -> CLOSE -> `ERR_ALREADY_TERMINAL`.
- Maintenance windows: 45-min closed buffer violation caught, non-conflicting adjacent window accepted.
- Duplicates: `ERR_DUPLICATE_RADIO_ID` (serial/radio_id), `ERR_DUPLICATE_TALKGROUP_ID` (agency_code/site_code/tg_decimal_id); retention floor -> `ERR_RECORDER_RETENTION_BELOW_MINIMUM`; `limit=0` and bad enum filters -> `ERR_INVALID_REQUEST`.

One change made after the walkthrough: `app.run(threaded=True)` (Flask's default) instead of `threaded=False`, to avoid any chance of the dev server serializing a probe against a test request.

Constraints honoured: never read `test_helpers/`, `test_suite/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task; scratch confined to `.scratch/step6/` and removed at the end (siblings `step2`/`step5` untouched); `worklog.md`, `SCAFFOLD.yaml`, `workspace/PRD.md`, `workspace/INSTRUCTION.md` all intact; every server killed by its exact PID — no broad `pkill`.

Orchestrator note: the agent reports "all 44 error ids" in `errors.py` while the Step 4 audit counted 45 entries in PRD Section 5. Left unreconciled here deliberately — if the one-error delta is real and a test exercises it, Step 7 will surface it as a concrete failure with a traceback, which is a far more reliable signal than a count comparison between two agents' self-reports. Not treated as a blocker.

## Step 5: Generate Unit Tests — 2026-09-06T02:10:57.923Z

Orchestrator note on execution: the Step 5 subagent was killed mid-run by an infrastructure API error ("The system encountered an unexpected error during processing"), after finishing all of `test_helpers/` but before writing a single file into `test_suite/`. Rather than respawn a fresh generator — which would have produced a test suite written against a different mental model than the helpers it must call, i.e. a suite that diverges from itself — the orchestrator resumed the SAME agent via SendMessage with a verified on-disk state report (helpers complete at 2444 lines; test_suite empty, not even conftest.py) and the precise remaining scope (18 queue-A + 68 non-stub queue-B candidates). The resume also mandated a `.scratch/step5/PROGRESS.md` ledger appended after each file, so a second infra kill would be cheap to resume from. The agent then ran to completion. Full summary follows verbatim.

Step 5 is complete. Both directories exist at the task root; nothing under `workspace/`.

## Deliverables

`test_suite/` (11 test files + conftest, 7,860 lines, **104 tests**)

| file | lines | tests |
|---|---|---|
| conftest.py | 35 | — |
| test_01_agency_registry_and_console_config.py | 228 | 5 |
| test_02_sites_and_coverage.py | 369 | 7 |
| test_03_templates_and_change_control.py | 1048 | 14 |
| test_04_subscriber_units.py | 856 | 13 |
| test_05_keysets_and_otar.py | 714 | 11 |
| test_06_key_compromise_cascade.py | 368 | 3 |
| test_07_talkgroups_and_patching.py | 1180 | 14 |
| test_08_site_events_and_escalation.py | 792 | 9 |
| test_09_talkpath_allocation.py | 918 | 9 |
| test_10_fees_governance_and_migration.py | 1160 | 15 |
| test_11_access_control_and_not_found.py | 227 | 4 |

`test_helpers/` (Stage 1, unchanged after the resume): `__init__.py` 11, `api_client.py` 359, `api_errors.py` 129, `assertions.py` 245, `constants.py` 358, `factories.py` 421, `fixtures.py` 574, `test_users.py` 123, `types.py` 224 — 2,444 lines.

## Design-index coverage (design-index-only contract honoured)

- **Queue A (difficulty): 18 / 18 instances translated, exactly 2 tests each = 36 tests.** No skips.
- **Queue B (corner): 68 / 68 non-stub instances translated, 1 test each = 68 tests.** No skips.
- The 14 corner entries carrying `excluded_because:` are deliberately untranslated — every one is a pure cross-reference to a difficulty instance (`difficulty_instance: <rule>/<name>`), and all 14 of those difficulty instances are covered twice via queue A. So there are **zero real coverage gaps**; nothing was dropped for failing the PRD two-condition filter.
- Coverage by corner section: entities 10, state_machines 9, calculations 7, validations 14, endpoints 4, errors 13, rbac 6, cross_cutting_complexity_layers 4, consistency_model 1.

## Verification performed

- `python3 -m py_compile` passes on **all 21 files** in `test_helpers/` and `test_suite/` (`ALL_COMPILED`).
- `pytest --collect-only`: **104 tests collected, 0 errors** — proves every module imports cleanly (py_compile alone cannot catch a used-but-unimported symbol; an AST auditor was also run per file, all clean apart from one nested-`def` false positive).
- Automated final audit over all 104 tests: **exactly one `Design:` line per test, and it is the last line of the docstring; 0 tag problems.** Every tag resolves to a real instance name in the correct yaml (verified by name lookup).
- **196 PRD citations, each verified to occur exactly once in `workspace/PRD.md`** by whitespace-normalised literal match; every test carries at least one citation.

## Notable adjudications made while writing

- Difficulty instance `fee_assessment_stale_version_outranks_invalid_fee_period` asserts `last_assessed_fee_cents == null` for a never-assessed agency, contradicting corner instance line 2069 and PRD 3.1 ("all open at 0"). Tests assert `0`, citing PRD 3.1.
- `rbac_dispatcher_cannot_create_a_site` proposes `sites?site_code=RBD-1`, but PRD 2.4 declares only `status`/`coverage_class`/`capacity_mode` as site-list filters. The test lists the register unfiltered and asserts `total_count == 0` instead of inventing an undeclared filter.
- `error_not_found_for_every_path_resource_family` was widened from the recipe's 10 GETs to all 11 declared path-identifier families (adding `site_id` -> `ERR_SITE_NOT_FOUND`, verbatim in PRD 2.4), and asserts 11 mutually distinct `error_id` values.

Cleanup: `.scratch/step5/` removed (sibling `.scratch/step2/` untouched); `__pycache__` from compile checks removed. `worklog.md`, `SCAFFOLD*.yaml`, `workspace/PRD.md`, `workspace/INSTRUCTION.md` all intact; `workspace/implementation/` was never read, listed, or touched, and no server was started.

Orchestrator verification: confirmed `workspace/test_helpers` and `workspace/test_suite` do NOT exist (the known mislocation failure mode of this step did not occur); both directories are at the task root. Independently counted 104 `def test_` functions across 11 files.

Steps 5 and 6 were launched in a single assistant message so they ran concurrently — this is what gave the Step 6 implementation generator physical isolation from `test_suite/`, which did not yet exist when it started.

## Step 7: Run Tests and Iterate — 2026-09-06T02:32:31.548130994Z

Orchestrator pre-note: to defuse three known failure modes of this step at once, the orchestrator pre-wrote `workspace/sweep.sh` before Step 7 started and instructed the subagent to launch only that script under `setsid nohup`, polling for a `SWEEP_DONE` sentinel touched after `wait`. The script file eliminates the inline `'"'"'$T'"'"'` quoting bug (which injects literal quotes into `--start-command` and kills all 8 rounds at t=0 with ServerStartError); the sentinel eliminates the relaunch-on-early-return bug (the setsid wrapper returns in under a minute while the rounds run on); and `setsid` eliminates sweep reaping (backgrounded rounds taking SIGTERM when any unrelated foreground Bash call returns, which mimics a flaky implementation). The subagent was also told to diagnose only from per-round `results.$i.json`, never from `sweep.log`, since 8 concurrent rounds share one fd and its text is spliced.

Clean 8-round sweep achieved. Summary:

## Iterations run: 2

**Iteration 1**: 100/104 passing in all 8 rounds — 4 deterministic failures, identical across every round (no flakiness anywhere in the suite).

**Iteration 2**: 104/104 passing in all 8 rounds.

## Tests deleted: 0

## Fixes applied to `test_helpers/`: 0
The helper layer (api_client instant canonicalisation, factories' integer-cents/full-instant conventions, per-agency role-header builders) was already PRD-faithful. All four failures were in `test_suite/`.

## Fixes applied to `test_suite/`: 4 edits across 3 files

**1-3. Response-envelope double-unwrap** (3 call sites) — the runner's `validate_error` returns the *error data dict* (`{error_id, message}`), not the full envelope. Three minority call sites indexed `body["error"]["error_id"]`, producing `KeyError: 'error'`. The majority of the suite (test_07:1120, test_08:723) already uses the return value directly, so the minority was made to match:
- `test_suite/test_11_access_control_and_not_found.py:92` (`test_not_found_error_id_differs_for_every_path_resource_family`)
- `test_suite/test_11_access_control_and_not_found.py:129` (`test_undeclared_role_header_is_unauthenticated_not_unauthorized`)
- `test_suite/test_10_fees_governance_and_migration.py:911` (`test_fee_assessment_stale_version_outranks_invalid_fee_period`)

This is a pure test-artifact symbol bug — the tracebacks carried no response body at all, and in each case the *primary* `validate_error(...)` assertion had already passed, meaning the implementation was returning the correct `error_id` and HTTP status all along.

**4. `ERR_UNIT_RETIRED` asserted on an action PRD does not gate** — `test_04_subscriber_units.py:453` (`test_error_unit_retired_blocks_further_lifecycle_actions`) retired a radio and then expected `ZEROIZE` to be refused with `ERR_UNIT_RETIRED`. PRD is silent on that specific pairing and, under STEP 1b, does not uniquely determine it:
- PRD 3.4 names exactly two `ERR_UNIT_RETIRED` triggers: *"retiring a radio that is already `RETIRED` is rejected with `ERR_UNIT_RETIRED`"* and *"a talkpath request naming a `RETIRED` unit is rejected with `ERR_UNIT_RETIRED`"*. Neither is `ZEROIZE`.
- PRD 3.4 affirmatively pushes the other way: the unit carries *"two state machines on one row, and they never touch each other"*; `ZEROIZE`'s stated precondition is on `key_status` only (`KEYLESS`/`KEYED`/`KEY_STALE`) and it *"leaves `provision_status` exactly as it was"*; and `RETIRE` explicitly notes *"a retired radio may still hold a key."*
- The only support for the test's reading is PRD 2.4's group-13 *ordering* list, which fixes precedence among guards but never states the retired guard's scope — a heading-level mention, not a rule sentence.

Per STEP 1c (partial coverage -> keep the covered assertion, drop the uncovered one), the refused action was retargeted from `ZEROIZE` to `RETIRE`, which is the PRD-verbatim trigger and preserves the test's stated intent. This was the suite's only coverage of the already-`RETIRED` guard, so retargeting kept a real PRD rule under test rather than losing it to deletion. The docstring's cited rule was updated to the matching PRD 3.4 sentence. The test's remaining assertions (`retired_at` stamped, `billable` false, `key_status` untouched, agency `billable_subscriber_count` recomputed to 0) all hold unchanged.

## Fixes applied to `implementation/`: 0
`routes/units.py` was already correct on the one point in dispute: it raises `ERR_UNIT_RETIRED` for `RETIRE`-on-`RETIRED` and guards `ZEROIZE` solely on the encryption dimension. No implementation check was weakened or added, and no PRD-required guard was stripped to accommodate a test.

## Orchestrator independent verification of the final sweep

Because a Step 7 subagent can report a clean sweep while leaving no artifacts behind, the orchestrator re-read the artifacts directly rather than trusting the claim:
- All 8 `results.$i.json` exist, all written within 200ms of each other at 2026-09-06T02:23:26Z, alongside the `SWEEP_DONE` sentinel — i.e. a genuine joined 8-round sweep, not a partial run.
- Each round independently parsed: `passed=104, failed=0, errors=0, total=104`. All 8 green.
- Per-round wall time 180.4-180.5s, tightly clustered — consistent with 8 concurrent rounds under per-test-server isolation, and showing none of the same-instant mass-death signature of reaping.
- `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` and `test_helpers/`: NONE. So the green sweep was not bought with skips.
- Test count still 104 with 104 `Design:` tags — consistent with the reported 0 deletions, and every surviving test still traceable to its design instance.

## Step 8: Finalize PRD — 2026-09-06T02:35:36.443533436Z

Orchestrator note on the skip decision: Step 7 ran 2 iterations with 4 `test_suite/` fixes, so the skip condition (zero deletions AND zero test_suite fixes AND zero test_helpers fixes AND zero implementation fixes) did not hold and Step 8 was run. The subagent was told explicitly that a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome given 0 implementation fixes, so that it would not manufacture edits to look productive.

Done. One edit.

## Line counts
- `PRD.md`: 465 lines; `PRD_FINALIZED.md`: 465 lines. Delta: 1 line revised in place (0.2% of lines; no lines added/removed, no new sections).

## Changes
- **PRD 3.4 (`ZEROIZE` paragraph, PRD_FINALIZED.md:231)** — revise (append two sentences to the existing paragraph) — pins that `ZEROIZE` never consults `provision_status` (permitted from `INVENTORY`, `ASSIGNED`, `SUSPENDED`, and `RETIRED`), that `ERR_UNIT_RETIRED` fires only at the two sites the PRD already names, and that a non-`RETIRE` lifecycle action aimed at a radio in an invalid source `provision_status` is refused by the group-12 state-transition rule rather than by `ERR_UNIT_RETIRED` — `implementation/routes/units.py:84-95`, `:97-99`, `:109`, `:131`, `:156`; `implementation/routes/talkpaths.py:27-28`.

## Pre-edit search log (the single edit)
- **(a) Subject**: scope of the retired-unit guard (`ERR_UNIT_RETIRED`) and the guard set of the `ZEROIZE` lifecycle action.
- **(b) Impl paths enumerated** (repo-wide grep for `ERR_UNIT_RETIRED`, `ZEROIZE`, `RETIRE`, `provision_status`, then full read of `units.py`):
  - `implementation/routes/units.py:72-163` — the whole lifecycle handler: `ZEROIZE` branch guards only `key_status == "ZEROIZED"` (-> `ERR_INVALID_STATE_TRANSITION`) and has no `provision_status` test; `RETIRE` branch is the only `ERR_UNIT_RETIRED` raiser here; `ASSIGN`/`SUSPEND`/`REINSTATE` raise `ERR_INVALID_STATE_TRANSITION` on a wrong source state (never `ERR_ALREADY_TERMINAL`, never `ERR_UNIT_RETIRED`).
  - `implementation/routes/talkpaths.py:27-28` — the only other `ERR_UNIT_RETIRED` raiser in the codebase (talkpath creation).
  - `implementation/routes/campaigns.py:89,94` and `implementation/routes/changes.py:103,148,151` — `RETIRED` units are silently excluded from OTAR/change fan-out target sets, not error paths, so no `ERR_UNIT_RETIRED` interaction.
  - `implementation/compute.py:107,376,387,545,558,568` — billable count, fee candidates, migration readiness: all read `provision_status` for set membership only.
  - `implementation/errors.py:32,80`, `implementation/enums.py:24-27`, `implementation/response.py` (envelope shape) — confirmed status code 409, and that the error envelope is `data.{error_id,message}` exactly as PRD 2.2 states.
- **(c) Wording adjustments made**: scoped the "nowhere else" claim to `ERR_UNIT_RETIRED` only (the grep proves exactly two raisers) rather than asserting anything general about retired-unit handling, which would have mis-described the silent-exclusion paths in `campaigns.py`/`changes.py`/`compute.py`; and restricted the final clause to invalid **`provision_status`** sources for non-`RETIRE` actions, deliberately not touching the already-`ZEROIZED` case (a `key_status` guard, whose error code is outside the Step 7 site and where PRD group 11 vs. impl's `ERR_INVALID_STATE_TRANSITION` is a separate question for Step 9).

## Items with no PRD patch
- **Items 1-3 (envelope double-unwrap in `test_11`/`test_10`)**: pure test-artifact symbol bugs. `implementation/response.py:error()` emits `{meta, response_type:"error", data:{error_id, message}}`, byte-for-byte the envelope PRD 2.2 lines 56-73 specifies; the failures were the tests re-indexing a helper return value that was already the `data` dict. No PRD silence, no mismatch, no edit.
- **Item 4**: the implementation was already PRD-faithful (`units.py` raises `ERR_UNIT_RETIRED` for `RETIRE`-on-`RETIRED`, guards `ZEROIZE` on the encryption dimension alone), so no behavioral realignment was needed — but PRD 2.4's group-13 ordering line mentions "the retired-unit guard" without stating its scope, which is exactly the ambiguity the deleted assertion exploited. The single edit closes that scope gap in the section that owns the rule, without moving any behavior.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (231, the `ZEROIZE` paragraph), 465 lines both files, +689 bytes; all 24 section headings intact and the file still ends at the final error-catalogue row. The edit is an in-paragraph append, no new section — consistent with the minimal-diff mandate. The subagent also flagged one question it deliberately left for Step 9: PRD group 11 vs the implementation's `ERR_INVALID_STATE_TRANSITION` for the already-`ZEROIZED` case.

## Step 9: Complete PRD — 2026-09-06T03:14:46.210641699Z

Orchestrator note on execution strategy: a single-pass scan of a 3084-line implementation against a 97KB PRD reliably under-covers, and a scan that produces a byte-identical output means it never really ran. Step 9 was therefore executed as FOUR SEQUENTIAL subagent passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module. Pass 1 alone did the `cp` from `PRD_FINALIZED.md`; passes 2-4 were explicitly forbidden from re-copying (that would silently destroy prior passes' edits) and were each given the running line/byte count so they could detect an accidental clobber. Each pass handed its out-of-scope observations forward to the next as an explicit to-do list, and pass 4 was a dedicated RECONCILIATION pass — partitioned passes report cross-pass contradictions rather than fixing them, so a narrow fourth pass is required to close them.

Partition:
- Pass 1 — cross-cutting core: app.py, db.py, response.py, validate.py, common.py, enums.py, errors.py, serialize.py.
- Pass 2 — compute.py + routes/{agencies,sites,templates,changes,units,misc}.py.
- Pass 3 — routes/{keysets,campaigns,talkgroups,patches,siteevents,talkpaths}.py.
- Pass 4 — reconciliation only: six named open items plus a bounded consistency sweep.

### Pass 1 (core modules) — 16 changes: 15 ambiguity-pins, 1 mismatch-revision

Created `PRD_COMPLETED.md` by cp from `PRD_FINALIZED.md` (both 465 lines / 97,952 bytes at that point). Verified as no-change-needed with zero drift: `enums.py` all 37 member sets match PRD prose member-for-member; `errors.py ERROR_STATUS` all 46 ids match the Section 5 status column exactly; `serialize.py` all 11 serializers' field sets match the entity narratives, no missing/extra, `_seq` correctly hidden.

Changes: 2.1 whitespace-only headers count as empty + exact case-sensitive role match (`validate.py:52-57`); 2.2 `api_request_id` = `req_` + exactly 20 chars of `[A-Z0-9]` regenerated per response including errors (`response.py:10-14`); 2.2 `api_request_timestamp` read from the logical clock, never host wall clock (`response.py:35-42`); 2.2 unknown path 404 / disallowed method 405 / unexpected failure 500 all carry `ERR_INVALID_REQUEST` in the normal envelope (`app.py:54-74`); 2.3 `limit`/`offset` must be canonical decimal integer literals with no upper bound on offset (`validate.py:272-296`); 2.3 `created_at` ties broken by creation sequence never by `id` (`db.py:57-60`); 2.4 absent/null FK falls to the required-field pass while a present non-string FK yields the reference's not-found error (`validate.py:86-104,315-325`); 2.4 step 7 explicit `null` == omitted, no JSON type coercion, undeclared members ignored, absent body read as `{}` (`validate.py:132-197`); **2.4 group 11 MISMATCH** — group 11 fires on exactly five resources, unit `RETIRED` -> `ERR_UNIT_RETIRED`, unit `ZEROIZED` -> `ERR_INVALID_STATE_TRANSITION`, terminal keyset ruling -> `ERR_INVALID_STATE_TRANSITION` (`errors.py:30-31`, `routes/units.py:85-86,98-99`, `routes/keysets.py:69-70`); 2.4 filters are exact equality before pagination, enum filters validated, id filters opaque (`validate.py:299-312`, `common.py:12-20`); 2.5 `version` opens at 1, `created_at == updated_at` at creation (`db.py:63-74`); 2.5 version advances at most once per request however many rules reach the row (`db.py:77-95`); 2.5 every declared field always present, unset rendered as JSON null never omitted (`serialize.py`); 2.5 fresh process holds no data, all eleven collections empty, storage process-local (`db.py:13-40`); 2.6 the OCC pin is a required integer >= 0 validated in group 7 so a bad pin is `ERR_INVALID_REQUEST` 400 not `ERR_STALE_VERSION` (`common.py:29-34`); 2.8 which four fields emit as JSON reals vs bare integers, no number ever a string (`response.py:24-32`, `serialize.py`); 2.8 fractional widths other than 0/3/6 rejected and 6-digit input TRUNCATED not rounded on read-back (`validate.py:200-222`, `response.py:17-21`); 4 intro trailing slash ignored (`app.py:45`); 3.4 already-`ZEROIZED` refusal is `ERR_INVALID_STATE_TRANSITION` not `ERR_ALREADY_TERMINAL` (`routes/units.py:85-86`).

Verdict on the question Step 8 forwarded: the implementation is right and PRD group 11 was over-broad. Already-`ZEROIZED` is `ERR_INVALID_STATE_TRANSITION` (409). `ERR_ALREADY_TERMINAL` appears nowhere in `routes/units.py`. While settling it, pass 1 found two more group-11 exceptions PRD was equally silent on and pinned all three so the ladder is self-consistent.

### Pass 2 (compute.py + routes A) — 17 changes: 14 ambiguity-pins, 3 mismatch-revisions

2.7 a recomputation storing a value the field already holds is not a mutation, with a carve-out list of unconditional writes (`compute.py:75-84`); **2.10 MISMATCH** the 180-day interop floor keys on STANDING `interop_privilege == PATCH_AUTHORITY`, not on any history of patching (`compute.py:522-526`); 2.10 the floor is tested only against a value the request actually supplies and is not applied at registration (`routes/agencies.py:29,84`); 2.10 a field-less console-config PATCH is an accepted no-op that still refreshes `updated_at` and bumps `version` (`routes/agencies.py:80,90`); 3.2 `covered_test_points > total_test_points` is a group-7 rejection and so precedes the OCC comparison (`routes/sites.py:83-88`); 3.3 publish is an edge out of `DRAFT` only (`routes/templates.py:88-89`); 3.3 `review_comment` stored only by `REQUEST_CHANGES`/`REJECT`, accepted and discarded with `APPROVE` (`routes/changes.py:89,105-116`); 3.3 a radio already carrying the deployed `template_id` is counted but not mutated, and `deployed_unit_count` ignores `provision_status` (`routes/changes.py:149`, `compute.py:131-136`); **3.3 MISMATCH** the sum does not "always" equal `target_unit_count` — a fleet change after approval leaves the request in `DEPLOYING` with `deployed_at` null and it never re-tries (`routes/changes.py:157-160`); 3.4 `SUSPEND` also computes `hold_seconds` on evicted talkpaths and recomputes the whole counter set (`routes/units.py:144-150`); 3.6 backwards-clock interval treated as zero duration (`compute.py:181-189`); 3.7 ELAPSED time itself clamped to 0 when the clock is behind `detected_at`, distinct from flooring the result (`compute.py:265-272`); 3.8 preemption candidates tie-break past `created_at` by creation sequence (`compute.py:495-498`); 3.8 `hold_seconds` 0 rather than negative on a backwards clock (`compute.py:501-509`); 3.9 period length is complete 24-hour days with the trailing part-day discarded, and a sub-day period makes every `PRORATED` per-unit amount 0 cents instead of dividing by zero (`compute.py:334-335,395-397`); **3.9 MISMATCH** days-in-service enumerated by opening midnights in `[period_start, period_end)`, so days can exceed the period length and the arithmetic is not clamped (`compute.py:321-347`); 3.9 the readiness `agency_id` filter is opaque and never resolved, unknown agency gives empty scope and `readiness_pct` 0.0 (`routes/misc.py:29-31`, `compute.py:555-560`).

All four findings handed forward from pass 1 were pinned.

### Pass 3 (routes B) — 16 changes: 13 ambiguity-pins, 3 mismatch-revisions

3.5 `keyset_name` uniqueness spans all statuses, exact and case-sensitive (`routes/keysets.py:26-28`); 3.5 supersession rewrites nothing but `status` — displaced keyset keeps its approver, crypto period and `loaded_unit_count`, and its radios stay `KEYED` (`routes/keysets.py:78-84`); **3.5 MISMATCH** campaign-execution check order is terminal -> keyset-active -> clock-window LAST, so a superseded keyset plus an out-of-window clock yields `ERR_KEYSET_NOT_ACTIVE` (`routes/campaigns.py:74-86`); 3.5 only the campaign's own keyset has `loaded_unit_count` recomputed, so a keyset a rekeyed radio previously pointed at may overstate (`routes/campaigns.py:108`); **3.5 MISMATCH** endpoints declaring no body input never parse one, so any payload including invalid JSON is ignored; 3.6 `DECOMMISSION` leaves `lock_reason` as it stands (`routes/talkgroups.py:96-100`); 3.6 activation repeats exactly three request-time guards and the coverage-class gate is not among them (`routes/patches.py:121-126`); 3.6 operator release is not gated on the reserved window (`routes/patches.py:144-153`); 3.7 `BACKUP_ENGAGED` leaves `capacity_mode` exactly as it stands (`routes/siteevents.py:158`); 3.7 the tier-three site posture write is unconditional so site `version` advances even when it already stood there (`routes/siteevents.py:107-110`); 3.7 tier-three victims also get `hold_seconds` computed (`routes/siteevents.py:113`); **3.7 MISMATCH** the `DECLARE_SURGE`-is-SystemAdmin refinement is not group 3 — it fires after path/body validation but before the terminal and edge tests, so `ERR_UNAUTHORIZED` beats `ERR_ALREADY_TERMINAL` (`routes/siteevents.py:131-135`); 3.7 `RESTORE`/`CLOSE` settle the site onto `IN_SERVICE`/`NORMAL` without consulting any other open event, and neither revives a preempted talkpath (`routes/siteevents.py:190,196`); 3.8 `site_event_id` need not belong to the named site and is resolved after `request_kind` validation (`routes/talkpaths.py:24-25`); 3.8 `EMERGENCY` alone never consults `capacity_mode` and no surge reserve is subtracted for it (`routes/talkpaths.py:45-53`); 3.8 a busied request leaves `priority_class_at_grant` null as well as `granted_at` (`routes/talkpaths.py:63,70-72`).

Dispositions of the five findings handed forward: tier-3 unconditional touch PINNED in agreement with pass 2's 2.7 carve-out; keyset supersession needed no no-op carve-out (the write always changes status); the forbidden "unit already KEYED is not re-mutated" sentence was correctly NOT written; the `created_by_user_id is not None` SoD conjunct judged genuinely unreachable dead code and deliberately NOT pinned (PRD must not describe unobservable behaviour); pass 1's group-11 keyset wording verified correct and not duplicated.

### Pass 4 (reconciliation) — 9 net changes: 1 de-duplication, 5 contradiction fixes, 3 new pins

- ITEM 1 (the real contradiction) — pass 3's bodiless-endpoint sentence in 3.5 locally contradicted pass 1's group-7 "the body parses ... otherwise `ERR_INVALID_REQUEST`". Pass 4 enumerated every handler against `validate.get_body()` (`validate.py:110-125`, the sole entry point) and found the bodiless set is SEVEN action endpoints, not the four pass 3 named: keyset compromise, campaign execute, change submit, change deploy, patch release, talkpath release, template publish — plus every GET; `/_clock/set_current_utc` does parse a body and is correctly excluded. Resolution: group 7's opener scoped to "for an endpoint that declares body input", the general bodiless rule stated ONCE in 2.4, and the 3.5 duplicate reduced to a cross-reference. 3.3 did not state it, so no third duplicate existed. Also pinned that a present-but-non-object body is `ERR_INVALID_REQUEST` (`validate.py:121-123`), which the old wording missed.
- ITEM 2 — grep proved `routes/siteevents.py:132` is the ONLY action-dependent role check in the codebase (the only `ERR_UNAUTHORIZED` raise outside `validate.authenticate`, the only `actor.role` comparison anywhere), so a general 2.4 claim would have been a false universal about a plural pattern. 2.4 group 3 now says it tests the endpoint's role list "and nothing finer", that an action-scoped refusal is evaluated later, and that exactly one action is restricted that way.
- ITEM 3 — 2.4's ladder asserted an order the code contradicts in TWO places, not one (`routes/campaigns.py:74-86` and `routes/patches.py:106-132`). Added a group-12 carve-out paragraph naming both, and confirming the other clock-derived refusals (planned-maintenance start `siteevents.py:142`, escalation monotonicity `siteevents.py:172`) do sit at group 12.
- ITEM 4 — 2.5 "at most once per request" and 2.7 "a no-op is not a mutation" compose correctly (zero is a subset of at-most-one), no edit needed. BUT pass 2's carve-out list was a false universal: `routes/campaigns.py:94-98` touches the unit unconditionally on OTAR rekey, and it is reachable and observable (a second campaign for the same keyset+agency is creatable once the first is `COMPLETED`, since overlap is only tested against `SCHEDULED` rows; executed at the same clock instant it stores identical values yet bumps `version`). Added to the list.
- ITEM 5 — pass 4 first wrote the 3.6 activation order as observable, then disproved its own claim and retracted: all three re-checks are genuinely unreachable, because every talkgroup exit from `ACTIVE` releases the naming patches (`routes/talkgroups.py:103-108`, `compute.py:456-462`), `sanction_cascade` releases the agency's open patches in the same breath as the privilege downgrade (`compute.py:305-318`), and `retention_floor` blocks a `PATCH_AUTHORITY` agency from configuring below 180 (`compute.py:521-526`). 3.6 now states the code's actual order and says plainly that it is a formality, with the reason — rather than claiming provocable behaviour.
- ITEM 6 — idempotence of the sanction-cascade re-run confirmed link by link (`recompute_vote_weight` already special-cases `SUSPENDED_FROM_VOTING`; link 2 only fires while privilege is still `PATCH_AUTHORITY`; link 3's doomed set is necessarily empty; both call sites already touch the agency as the addressed resource). Left deliberately unpinned — documenting it would describe unobservable internals.
- Bounded consistency sweep additionally fixed three contradictions the partitioned passes introduced without noticing: 2.7's "every row a cascade touches is mutated" was an unqualified universal that its own no-op rule negated three sentences later (rewritten to "actually rewrites"); 3.7's tier-3 paragraph stopped the preemption tie-break at `created_at` and read as complete, now defers to 3.8's three-key ranking; and 3.7's blanket claim that `DECLARE_SURGE` on an `UNPLANNED_OUTAGE` yields `ERR_INVALID_STATE_TRANSITION` is true only for a SystemAdmin, now qualified. Verified consistent with no edit: every `group N` cross-reference across 2.4/2.6/3.2-3.7, all three backwards-clock clamps, the retention floor in 2.10 vs the 180-day gates in 3.6, and the deploy fan-out's conditional write vs the OTAR rekey's unconditional one.

Pass 4 verdict: `PRD_COMPLETED.md` is internally self-consistent and aligned to `implementation/`, with one deliberate under-determination — 3.9's silence on the sanction cascade's unobservable re-run.

### Orchestrator verification of Step 9

- Totals across the four passes: **58 edits** (42 ambiguity-pins, 7 mismatch-revisions, 9 reconciliation changes).
- `PRD_COMPLETED.md` is 472 lines / 121,763 bytes vs `PRD_FINALIZED.md` 465 lines / 97,952 bytes — `cmp` confirms they are NOT identical (103 changed lines, +23,811 bytes). A byte-identical Step 9 output would have meant the scan never ran; this is a genuine scan.
- Heading count 27, unchanged across all four passes — no sections were added or lost, as the minimal-diff mandate requires. File still opens with the document title and closes on the final error-catalogue row, so no pass truncated it.
- `find` confirms NO file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the green sweep at 2026-09-06T02:23:26Z. The 8/8 x 104-test result therefore still describes exactly the code on disk; Step 9 changed only documentation.

PIPELINE COMPLETE — `workspace/PRD_COMPLETED.md` written.
