# Worklog — task_2843_neighborhood_camera_video_request_community_safety_portal

## Step 1: Create task directory — 2026-09-05T05:29:00.000Z

Created `tasks/task_2843_neighborhood_camera_video_request_community_safety_portal/` and `tasks/task_2843_neighborhood_camera_video_request_community_safety_portal/workspace/`. Index 2843 was pre-assigned by the orchestrating command; no index scan performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T07:08:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files

| File | Lines | Size |
|---|---|---|
| `SCAFFOLD.yaml` | 3208 | 177 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2782 | 180 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3886 | 243 KB |

All three parse under PyYAML and end at real YAML boundaries. `SCAFFOLD.yaml` carries neither design key; the other two each have exactly one top-level key (`scaffold_difficulty_design`, `scaffold_corner_design`).

## SCAFFOLD.yaml counts (§1.0–§1.7)
13 entities · 50 endpoints · 9 state machines over 8 entities (39 transitions; VideoRequest carries two parallel dimensions) · 9 calculation rules (2 with explicit variants) · 45 validation rows (priorities contiguous 1..45) · 54 error codes · 3 OCC `concurrency_rules` · 6 roles. Profile: `compliance_audit` × `multi_party_negotiation`, graph topology, parallel state machines, `segregation_of_duties` role model, `immediate` consistency, layers = optimistic_concurrency / cascading_side_effects / rate_threshold_triggers / derived_field_reconciliation.

## §1.8 depth probe
9 Difficulty Rules × 19 instances (each rule >= 2).

## §1.9 breadth probe
67 instances across all nine claim-extraction-guide sections — **52 with full `test_recipe` chains, 15 `excluded_because:` stubs** (every cited `difficulty_instance` resolves by name in the §1.8 file): entities 12, state_machines 8, calculations 9, validations 10, endpoints 6, errors 9, rbac 5, cross_cutting_complexity_layers 6, consistency_model 2.

## Verification
`scaffold_lint.py` -> **`VERDICT: clean lint`** (50 endpoints, 13 entities, 19 §1.8 + 52 §1.9 instances, 959 calls scanned; all §1.5 conformance and FK reverse-reachability checks pass). Independently checked: no duplicate instance names within or across the two design files, and all 54 declared error codes are triggered by at least one instance.

## Notable repairs made while auditing §1.1–§1.7 against the design chains
- Deleted a dead validation rule + its error (`ERR_REVISION_LIMIT_REACHED` was unreachable because the revision-cap decision moves the post to REMOVED), renumbering 44/45/46 -> 43/44/45 and updating all cross-file references.
- Added `TransparencyReport.compiled_by_user_id` (system) plus its create side effect, so validation 7's segregation-of-duties clause for certification is actually enforceable.
- Fixed three enum/prose mismatches (`SUSPENDED` device status in a comment, `duty_role IN {AUDITOR, BOTH}`, `auto_decline_source ... OWNER`).
- Corrected the `difficulty_level` comment's stale counts (55 errors / 46 validations -> 54 / 45).

The scenario block holds only the verbatim numbered scenario text; the "Generate task harder than expert level!" directive is not present in any of the three files (difficulty is carried as `difficulty_level: above_expert`). Orchestrator independently verified with grep: NO LEAK.

## Step 3: Copy shared files — 2026-09-05T07:08:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T07:26:00.000Z

PRD generation for task 2843 is complete.

**Output:** `workspace/PRD.md`
**Final line count:** 506 lines (built incrementally: one `Write` + five `cat >>` heredoc appends, no truncation).

**Top-level sections in order**
1. `# Neighborhood Safety Portal API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 Callers, Roles and Identity / 2.2 API Response Structure / 2.3 Pagination / 2.4 Resource Identity, Timestamps and Versioning / 2.5 The Logical Clock / 2.6 The Municipal Planning Grid / 2.7 Exact Decimal Arithmetic, Rounding and Basis Points / 2.8 Optimistic Concurrency on Parent Versions / 2.9 Order of Refusal / 2.10 Flat Addressing and Path Resolution / 2.11 Cascade Discipline and Ledger Invariants (11 subsections)
4. `## 3. Business Logic & Workflows` — 3.1 Agency onboarding/discipline/duty split / 3.2 Resident accounts, cameras, data controls / 3.3 Drawing, locking, invalidating a canvass area / 3.4 Justifying, auditing, submitting a video request / 3.5 Consent: sharing, declining, lapsing / 3.6 Retention, legal hold and the sweep / 3.7 Notification dispatch and fatigue controls / 3.8 The neighbourhood feed / 3.9 Transparency reporting and certification (9 subsections)
5. `## 4. Endpoint Definitions` — 50 rows
6. `## 5. Error Code Catalogue` — 54 rows

**Tail check:** the file ends on `| ERR_AGENCY_PERIOD_QUOTA_EXCEEDED | 409 |`, the final row of the §5 table — a clean section boundary, not mid-sentence.

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** 168 required identifiers (153 entity fields + 8 input-only identifiers + 7 sweep/clock output fields). 168 present, 0 missing.
- **Contract 2 — Rule Coverage: PASS.** 54/54 error codes, 45/45 validation rules (§2.9 enumerated 1–45 in priority order), 39/39 state transitions (each present in explicit `FROM -> TO` form), 9/9 calculations, 3/3 optimistic-concurrency rules, 85/85 enum literal values, 6/6 roles, 50/50 endpoints.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 beginning with `/`, zero bare HTTP method names, zero method+path pairs, zero occurrences of `/neighborhood-safety` or `/_clock` anywhere in §3.

**Other verifications:** §2.2 is byte-identical to `section-2.2-response-structure.md`. Neither design yaml was opened; no sibling task directory was read. Scratch confined to `/tmp/task_2843_prd_scratch/`.

**Scaffold contradictions resolved into one unambiguous reading:** audit flag fires at justification time on `radius_m` > 1000 **or** `eligible_device_count` > 4; the submit gate is `compliance_state != JUSTIFICATION_PENDING`; the auth header is `X-User-Role`; `NotificationDispatch.kind` uses `CONSENT_SOLICITATION`; audit `duty_role` accepts `AUDITOR` or `DUAL_ROLE`; withdrawal is legal only from `DRAFT` and `SOLICITING`, terminal states refused with `ERR_REQUEST_NOT_SOLICITING`.

**Orchestrator truncation guard:** independently verified — 506 lines / 115117 bytes, §4 contains exactly 50 method rows, §5 exactly 54 error rows, tail is the last table row of §5. Not truncated. Grep for difficulty-directive leak: NO LEAK.

## Step 5: Generate unit tests — 2026-09-05T07:47:00.000Z

Step 5 is complete. Test infrastructure and test suite are on disk at the task root.

## Files

**`test_helpers/` — 3,039 lines**

| lines | file |
|---|---|
| 163 | `__init__.py` (re-exports) |
| 371 | `api_client.py` (50 endpoint methods + `canonical_instant`) |
| 151 | `api_errors.py` (54 error ids + HTTP status map) |
| 338 | `assertions.py` (envelope, common-field, ledger, precision, ordering) |
| 359 | `constants.py` |
| 475 | `factories.py` (payload builders, length-pinned justification texts) |
| 782 | `fixtures.py` (6 tiers of composite setups + read-through helpers) |
| 124 | `test_users.py` |
| 276 | `types.py` |

**`test_suite/` — 12,329 lines, 157 tests**

`conftest.py` (32) · `test_01_entity_shapes` 900/16 · `test_02_state_machines` 582/12 · `test_03_calculations` 558/6 · `test_04_validations` 598/11 · `test_05_endpoints` 779/10 · `test_06_errors` 1061/18 · `test_07_rbac` 852/9 · `test_08_cross_cutting` 620/8 · `test_09_consistency_model` 457/6 · `test_10_dual_variant_calc` 462/6 · `test_11_combinatorial_formula` 723/10 · `test_12_non_linear_state_machine` 562/6 · `test_13_transitive_cascade` 1079/7 · `test_14_priority_pair_validation_conflict` 425/4 · `test_15_boundary_precision_check` 602/7 · `test_16_cross_entity_state_dependency` 662/5 · `test_17_resource_temporal_overlap` 786/10 · `test_18_compensating_invariant` 589/6

## Coverage

- **Queue A (difficulty): 19/19 translatable instances**, every one with >=2 tests. (Note: the index holds **19**, not 18 — `combinatorial_formula` has three instances.)
- **Queue B (corner): 52/52 translatable instances** (67 total - 15 `excluded_because:` stubs). No stub was translated.
- **Instances skipped for PRD silence or non-unique derivability: none.** Two *sub-assertions* inside translated instances were dropped as non-derivable rather than weakened: `auto_flag_reason` after `REMOVED` (test_12), and list *position* where two rows share a logical-clock `created_at` and the PRD forbids an id tie-break (test_05, test_13) — those compare by id/set instead.

## Verification (all green)

A machine pass over every test confirmed: exactly one `Design:` line per test as the last docstring line; every tag names a real non-stub instance in the correct section/rule_id; **all ~350 `PRD:` citations verbatim-greppable in `PRD.md`**; no forbidden vocabulary. Plus: `py_compile` clean, `pyflakes` clean, all 18 modules import successfully, no `pytest.skip`/`xfail`, no envelope double-unwrap, and `ls -d workspace/test_*` finds nothing. `worklog.md` untouched; `implementation/` never read.

## Findings worth attention before Step 7

Several PRD-vs-design-yaml conflicts were resolved **in the PRD's favour**; these are where an implementation is most likely to diverge:

1. **Audit trigger timing.** The yamls place `AUDIT_FLAGGED` on *submit*; PRD §3.4 says the trigger "fires in the same operation, immediately after that move" — i.e. inside the *justification* call. Three files assert the PRD's reading.
2. **Audit device trigger is strictly `> 4`.** Two yaml scenarios seed exactly 4 eligible cameras and expect escalation, which is unreachable. Those tests seed 5.
3. **`ERR_AREA_RADIUS_EXCEEDS_LIMIT` vs `ERR_INVALID_REQUEST`** for `radius_m > 1500` — §3.3 states both a bound and a specific error; tests assert the specific one (422).
4. **Order of refusal beats §3.4's narrative ordering** for the submit gates (rule 9 outranks rules 13/14).
5. All drift-table substitutions applied: `CONSENT_SOLICITATION`, `RESIDENT_MUTED`, `FATIGUE_BUDGET_EXHAUSTED`, `AUTO_SCORE`/`RESIDENT_FLAGS`, `OWNER_DECLINE`, `OPT_OUT_OF_REQUESTS`.

## Step 6: Generate implementation — 2026-09-05T07:48:00.000Z

Implementation complete and verified.

## Modules (`workspace/implementation/`, 17 files, 3170 lines)

| file | lines | role |
|---|---|---|
| `app.py` | 69 | app factory, blueprint registration, error handlers, `__main__` bind |
| `store.py` | 110 | in-memory `db` dicts, logical clock, ISO-8601 formatting, `by_created` |
| `errors.py` | 81 | all 54 error ids -> HTTP status |
| `envelope.py` | 51 | ok/created/collection/error response envelopes |
| `validators.py` | 175 | body/query field coercion, pagination |
| `auth.py` | 105 | role auth, resident scope, segregation-of-duties |
| `calc.py` | 218 | the 9 calculations (score, bps, retention, dispatch rank, min devices...) |
| `serialize.py` | 132 | per-entity field projections |
| `fetch.py` | 34 | FK resolution -> `ERR_NOT_FOUND` |
| `engine.py` | 392 | shared state machine: fan-outs, cascades, counter reconciliation, `touch` |
| `routes_agency.py` | 213 | agency onboarding/suspension |
| `routes_area.py` | 140 | request areas, locking, geometry |
| `routes_request.py` | 294 | video requests, justification, submit, solicitation dispatch |
| `routes_consent.py` | 225 | share/decline/purge + reads |
| `routes_feed.py` | 302 | posts, flags, revisions, moderation cases |
| `routes_report.py` | 247 | transparency reports, retention sweep, `_clock/set_current_utc` |
| `routes_resident.py` | 382 | residents, devices, data-control cascades |

Plus `requirements.txt` (`flask>=2.0`) and executable `start.sh`.

## Verification

- **50/50 endpoints** matching `SCAFFOLD.yaml` exactly (`missing: []`, `extra: []`); 54 error ids present; all modules `py_compile` clean.
- **`start.sh` honours `$PORT`, binds `0.0.0.0`, runs in the foreground** (`exec python3 app.py`; `app.run(host="0.0.0.0", port=int(os.environ["PORT"]), use_reloader=False)`). Confirmed booting both via `nohup ./start.sh` and via `subprocess.Popen`, each time with an empty store.
- **No persistence**: no `sqlite`, no `open(`, no `json.dump`, no `/tmp` paths in any module. Nothing is ever seeded.
- Two end-to-end smoke suites pass on fresh boots (worked score example 0.61; `effective_min_devices` 3 and 7; audit escalation -> `CASE_ANCHORED`/`LEGAL_HOLD`; legal-hold refusals and PlatformAdmin `LEGAL_RELEASE`; dispatch ranks 0/100/400/900/1600; overlap 409 / out-of-window 422 on share; agency-suspension cascade with solicitation ledger balancing 5 = 5; strike ladder 2 -> `REVIEW_REQUIRED`, 4 -> `POSTING_SUSPENDED`; revision lap back to `PUBLISHED`; sweep idempotence; clock date-advance daily-counter reset).
- Smoke server on port 41843 shut down by its exact resolved pid. No broad `pkill` used.

## PRD ambiguities and interpretations chosen

- Second justification attempt on a submitted request -> `ERR_REQUEST_NOT_IN_DRAFT`.
- An AUDITOR locking an area -> `ERR_SEGREGATION_OF_DUTIES`.
- `radius_m < 50` fails at rule 5 (400) while `> 1500` fails at rule 37 (422), following rule ordering rather than collapsing both into one code.
- Purge state/reason mismatches outside the legal-hold cases -> `ERR_INVALID_REQUEST`, evaluated after rules 20/21.
- Envelope timestamps and every `created_at` come from the logical clock, never the wall clock.
- Rows touched only by a cascade still get exactly one version increment for the operation.
- `auto_decline_requests` is excluded from the eligibility-collapse recount predicate.
- A `DECOMMISSIONED` device is inert for solicitations and pending counts; only the area recount runs.
- The clock-driven daily counter reset does not bump `version`.
- `revise` treats omitted discrimination signals as 0.
- Report compile enforces `ONBOARDED` (per rule 9's `applies_to`), ahead of the stale-version and window checks.
- `created_at` ties resolve to insertion order via a stable sort.
- `decide` guards a post not in `UNDER_REVIEW` with `ERR_POST_NOT_FLAGGED`.
- `shared_clip_count` counts all clips of a request, including `PURGED` ones.

**Isolation confirmed by orchestrator:** Step 6 was launched while `test_helpers/` and `test_suite/` did not yet exist on disk.

## Step 7: Run tests and iterate — 2026-09-05T08:24:00.000Z

Clean 8-round sweep. Exiting.

## Summary

**Iterations run:** 2 (iteration 1 surfaced 3 deterministic failures; iteration 2 clean).

**Iteration 1 results:** 154/157 in all 8 rounds — the same 3 tests failed in every round (no flakiness, no load artifacts, no `Terminated` pattern):
- `test_13::test_resident_opt_out_cascade_reaches_the_agency_open_request_counter` — `Expected version == 2, got 3`
- `test_13::test_resident_opt_out_leaves_a_neighbours_camera_and_the_locked_area_alone` — `Expected version == 1, got 2`
- `test_16::test_share_reports_the_decommissioned_camera_not_the_open_solicitations_state` — `Expected eligible_device_count == 3, got 2`

**Tests deleted:** none. All three failures traced to verbatim, uniquely-derivable PRD rules.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`** (STEP 2 — assertion mis-translation; both made strictly more faithful, no assertion weakened):
- `test_suite/test_13_transitive_cascade.py`, `test_resident_opt_out_cascade_reaches_the_agency_open_request_counter`: the absolute literal `"version": 2` on the owner's row assumed the resident was still at version 1 before the data control. PRD §3.7 states the submit-time dispatch batch raises "the recipient's `notifications_sent_today` ... by 1" and re-derives `fatigue_state`, and §2.4/§2.11 make any such mutation advance the row's `version` (§2.11 explicitly warns "a caller cannot assume a resource's `version` is unchanged simply because it did not write to it"). Replaced with a pre-trigger read plus `owner_before["version"] + 1`, which is exactly PRD's "Every data control advances the resident's `version` by 1."
- Same file, `test_resident_opt_out_leaves_a_neighbours_camera_and_the_locked_area_alone`: identical issue on the neighbour's row (`"version": 1`). The neighbour's three cameras are also on the roster, so it too was solicited and mutated at submit. Replaced with a pre-trigger read and `neighbour_before["version"]` (unchanged), which is the rule the test actually means to prove.

**Fixes applied to `implementation/`:**
- `workspace/implementation/engine.py`, `check_eligibility_collapse()`: it was writing the recomputed count back into `RequestArea.eligible_device_count` and `touch()`ing the area, advancing its `version` even when the area stayed `LOCKED`. PRD §3.3 says only that "the eligible count is recomputed against the frozen roster" and ties the version advance to the `LOCKED -> INVALIDATED` move; §3.3 writes the count once at lock ("The number of cameras on this frozen roster is written to `eligible_device_count`") and §3.4 reads it back twice as "the area's frozen `eligible_device_count`" / "its frozen `eligible_device_count`". The recount is therefore transient. Now it is used only for the threshold comparison; the persisted field and the area's version are left alone unless the area actually invalidates. This one fix resolved the `test_16` failure and the area-version leg of the `test_13` neighbour test.

**Final counts (clean sweep):** 157/157 passed in each of rounds 1–8, 0 failed, 0 errors.

Notes on the Step 5 hearsay, verified against PRD.md: (1) the `AUDIT_FLAGGED` trigger does fire inside the justification call (§3.4 "fires in the same operation, immediately after that move"); (2) the device trigger is strictly `> 4` (§3.4); (3) `radius_m > 1500` -> `ERR_AREA_RADIUS_EXCEEDS_LIMIT` 422 (§3.3, §2.9 rule 37); (4) §2.9 ordering governs submit ("The gates are evaluated in the order of §2.9"). The implementation already matched all four — no changes needed there.

**Orchestrator verification:** all 8 `results.$i.json` present on disk (timestamps 08:23), each parsed independently: `passed=157, failed=0, total=157, errors=0`. Step 8 will NOT be skipped (1 implementation fix + 2 test_suite fixes).

## Step 8: Finalize PRD — 2026-09-05T08:30:00.000Z

Both edits applied. Verification: `PRD.md` and `PRD_FINALIZED.md` are both 506 lines, `diff` shows exactly two modified paragraphs — nothing truncated, no new sections.

## Line counts
- PRD.md: 506 lines; PRD_FINALIZED.md: 506 lines (0% line delta; 2 paragraphs revised in place).

## Changes
- **§3.3 (eligibility collapse, line 256) — revise** — pinned that the post-lock recount is transient: it serves the threshold comparison only, is never written back to `eligible_device_count` (which keeps its lock-time value), and does not advance the area's `version`/`updated_at` unless the area actually moves `LOCKED -> INVALIDATED` — `implementation/engine.py:277-298` (`check_eligibility_collapse`), with the sole writers of the field at `implementation/routes_area.py:82,110`.
- **§3.7 (post-batch fatigue re-derivation, line 338) — revise** — pinned that the post-batch `fatigue_state` re-derivation is a write to each recipient's row: every resident the batch aimed at least one dispatch at has `version` advanced and `updated_at` refreshed, whether or not any dispatch was delivered and whether or not the derived state changed — `implementation/engine.py:233-237` (`emit_batch`).

## Per-edit pre-edit search log

**Edit 1**
- (a) Subject: the value and version lifecycle of `RequestArea.eligible_device_count` and area-row version advances triggered by an eligibility recount.
- (b) Paths enumerated: grepped `eligible_device_count`, `check_eligibility_collapse`, `rosters`, `roster_member_still_eligible` across all of `implementation/`. Read `engine.check_eligibility_collapse` (engine.py:277-298); the only writers `routes_area.py:82` (create, 0) and `routes_area.py:110` (lock, `len(roster)`); both readers `routes_request.py:104` (audit trigger `> 4`) and `routes_request.py:158` (submission gate); `serialize.py:45`; the parallel invalidation path `routes_agency.py:120-126` (`_invalidate_locked_areas`); and all four collapse callsites `routes_resident.py:216, 320, 334, 381`.
- (c) Wording adjustments: (i) scoped the no-version-advance claim to "the recount by itself", so the `AGENCY_SUSPENDED` enforcement branch and request-creation's `derived_request_count` bump are not contradicted; (ii) said the recount "serves the threshold comparison alone" rather than restating which cameras count, so `calc.roster_member_still_eligible` is not narrowed; (iii) replaced "comes out of the check byte-for-byte as it went in" with "is left exactly as the check found it".

**Edit 2**
- (a) Subject: whether emitting a notification batch mutates (versions) the recipient `Resident` row, and under what conditions.
- (b) Paths enumerated: grepped `emit_batch`, `rederive_fatigue`, `touch(resident`, `notifications_sent_today`. Read `engine.emit_batch` (engine.py:175-238), its callers `routes_request.py:225` (submit) and `engine.post_fanout` -> `routes_feed.py:93, 153, 263`; the non-batch re-derivation paths `engine.rederive_fatigue` (241-244) used by `routes_resident.py:95-96` and `routes_report.py:238-243` (clock date-boundary reset, re-derives but does not touch); `engine.touch` per-row-per-operation dedupe (engine.py:24-33).
- (c) Wording adjustments: scoped the claim to "every resident the batch aimed at least one dispatch at ... by the batch" so it cannot be read as covering the §2.5 clock-boundary reset or an empty batch; used "advanced"/"refreshed" rather than an exact-increment claim to stay compatible with the per-row-per-operation single increment.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly 2 changed lines (256, 338), both whole-paragraph revisions; both files 506 lines; files are NOT identical.

## Step 9: Complete PRD — 2026-09-05T09:15:00.000Z

Step 9 was run as three sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 edited in place). Final: 506 lines / 136,423 chars, 47 changed lines vs `PRD_FINALIZED.md` (+20,436 chars), tail intact at the last §5 error row.

### Pass 1 — core modules (app, store, errors, envelope, validators, auth, fetch, serialize, calc)
`cp PRD_FINALIZED.md -> PRD_COMPLETED.md` performed. 121,674 chars after pass. **12 ambiguity-pins, 1 mismatch-revision.**
- §2.1 — revise — ambiguity — `X-User-ID` treated as absent when whitespace-only; self-registration exemption pinned (supplied role must still be admitted -> `ERR_UNAUTHORIZED`) — auth.py:38-51
- §2.1 — insert — ambiguity — entity-backed `X-User-ID` resolving to no row is `ERR_IDENTITY_MISMATCH`, never a not-found; reads are not ownership-scoped — auth.py:73-94
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + exactly 20 upper-case-alphanumeric chars — envelope.py:9-13
- §2.2 — revise — ambiguity — `api_request_timestamp` read from the logical clock, not wall-clock — envelope.py:19
- §2.3 — insert — ambiguity — `offset` unbounded, over-run yields empty page with true `total_count`; bad `limit`/`offset` -> `ERR_INVALID_REQUEST`; empty value falls back to default — validators.py:121-141
- §2.3 — insert — ambiguity — global ordering tie-break is creation order, never `id` — store.py:108-110
- §2.3 — insert — ambiguity — filter-value validation: out-of-set enum -> `ERR_INVALID_REQUEST`; booleans accept `true/false/1/0` any case; id filters literal, no existence check — validators.py:144-170
- §2.4 — insert — ambiguity — every instant field rendered with exactly three fractional digits (truncated for display, microseconds kept for comparison); every declared field always present, `null` when unset — serialize.py:109-128, store.py:49-57
- §2.7 — insert — ambiguity — two-decimal value carried as a JSON number (0.60 renders `0.6`, zero `0.0`); every other quantity an exact integer — serialize.py:112-115, calc.py:46-51
- §2.9 rule 4 — insert — ambiguity — non-string FK resolves to no row and reports not-found rather than a body-shape error — fetch.py:24-27
- §2.9 rule 5 — insert — ambiguity — JSON type strictness; explicit `null` == omission incl. partial updates; absent/empty body = empty object, unparseable/non-object -> `ERR_INVALID_REQUEST`; datetime leniency — validators.py:18-114, store.py:60-91
- §3.3 — insert — ambiguity — eligibility-collapse recount re-tests exactly three predicates (camera status, owner account status, owner opt-out) — calc.py:143-157
- §5 — revise — **mismatch** — "every error identifier ... is listed below" was false: unmatched paths -> 404 `ERR_NOT_FOUND`, unsupported methods -> 405 `ERR_UNAUTHORIZED`, both outside the table and the §2.9 ladder — app.py:24,36-50

### Pass 2 — engine + agency/area/request routes
126,495 chars after pass. No `cp` run; pass 1 sentinels verified present. **17 ambiguity-pins, 4 mismatch-revisions (21 edits).**
- §2.11 — insert — ambiguity — version increments once per row per operation, not per write — engine.py:24-44
- §2.11 — insert — ambiguity — `shared_clip_count` counts purged clips (monotonic); reconciliation is compare-then-write, a no-op advances no `version` — engine.py:89-150
- §3.1 — insert — ambiguity — fresh agency's `onboarding_agreement_version`, `reviewer_note`, `status_reason` all null — routes_agency.py:45-48
- §3.1 — insert — ambiguity — `reviewer_note` required but empty string accepted — routes_agency.py:78
- §3.1 — insert — ambiguity — duplicate `badge_number` within an agency -> `ERR_INVALID_REQUEST`; reuse across agencies free — routes_agency.py:163-166
- §3.1 — insert — ambiguity — `duty_role` consulted at exactly two points (lock, audit review) — routes_area.py:97, routes_request.py:122
- §3.2 — revise — **mismatch** — `alert_radius_m` 0 is a closed disc of radius 0, not "no alerts whatsoever" — engine.py:258-262
- §3.3 — revise — **mismatch** — `radius_m` 50-floor is a body bound (`ERR_INVALID_REQUEST`); 1500 is the dedicated cap — routes_area.py:31,52
- §3.3 — insert — ambiguity — `area_label` defaults null, accepts empty string — routes_area.py:34
- §3.3 — insert — ambiguity — AUDITOR-only officer locking -> `ERR_SEGREGATION_OF_DUTIES`, ahead of onboarding and DRAFT checks — routes_area.py:97-99
- §3.4 — insert — ambiguity — `derived_request_count` monotonic — routes_request.py:69
- §3.4 — insert — ambiguity — justification requires agency still `ONBOARDED`; second justification -> `ERR_REQUEST_NOT_IN_DRAFT` — routes_request.py:85-91
- §3.4 — revise — **mismatch** — `statutory_basis` non-empty after trimming; both fields stored untrimmed — routes_request.py:92-99
- §3.4 — insert — ambiguity — `audit_note` required but may be empty — routes_request.py:116
- §3.4 — insert — ambiguity — audit review consults neither `lifecycle_state` nor agency onboarding — routes_request.py:110-135
- §3.4 — revise — **mismatch** — submit gate prose reordered so the area check precedes the DRAFT check per §2.9 positions 13/14 — routes_request.py:149-154
- §3.4 — insert — ambiguity — withdrawal `reason` required, may be empty, stored nowhere; `withdraw_reason` from the fixed vocabulary — routes_request.py:242,255
- §3.5 — insert — ambiguity — auto-resolution fires only from `SOLICITING` — engine.py:151-153
- §3.5 — insert — ambiguity — a resolved request is never re-resolved; later compensating withdrawal leaves `FULFILLED` with `shared_count` 0 — engine.py:151-168,341-350
- §3.7 — insert — ambiguity — post-batch `fatigue_state` judged against the batch-start effective budget — engine.py:235-236
- §3.8 — insert — ambiguity — auto-opened cases carry `decision` `NONE` and a snapshotted `post_discrimination_score_at_open`, created in ascending `created_at` — engine.py:382-394

Deliberately left under-determined (impl paths unreachable, so no universal claim was safe): revocation's request cascade, `distance_sq_m2` frozen-vs-recomputed at submit, withdrawal's missing onboarding gate.

### Pass 3 — consent/feed/report/resident routes
136,423 chars after pass. No `cp` run; pass 1 and 2 sentinels verified present. **17 ambiguity-pins, 2 mismatch-revisions (19 edits + 2 corrective re-edits removing false universals).**
- §2.5 — insert — ambiguity — day-rollover counter reset is not a versioned write; residents visited in ascending `created_at`; `fatigue_state` re-derived against the reset counter of 0 — routes_report.py:237-242
- §3.2 — revise — **mismatch** — impl re-derives fatigue on *every* accepted alert-settings update (not only a budget change), and both the re-derivation and the `version` advance are unconditional — routes_resident.py:95-96
- §3.2 — insert — ambiguity — camera patch: `auto_decline_requests` false always writes `auto_decline_source` `NONE` and leaves `data_sharing_opt_out` untouched; recount runs only when stored `status` changes — routes_resident.py:208-216
- §3.2 — insert — ambiguity — per-action meaning of the four receipt counts (`OPT_IN` spans `DECOMMISSIONED` cameras; `PURGE_HISTORY`'s `affected_solicitation_count` counts only `SHARED -> WITHDRAWN` cascades); `reason` stored verbatim, null when omitted — routes_resident.py:267-379
- §3.2 — insert — ambiguity — opt-in runs the same recount, which can only invalidate, never revive an area — routes_resident.py:334-335
- §3.2 — insert — ambiguity — `PURGE_HISTORY` reaches only `RETAINED` clips in ascending `created_at` — routes_resident.py:340-348
- §3.2 — insert — ambiguity — `DEACTIVATE_ACCOUNT` declines every `SOLICITED` solicitation regardless of camera posture, moves clips to `PURGE_PENDING`, processes its three sets in ascending `created_at`, runs the recount last — routes_resident.py:354-382
- §3.5 — insert — ambiguity — declining consults neither camera `status` nor `data_sharing_opt_out` (ladder 19/30 guard the share path alone) — routes_consent.py:110-133
- §3.6 — insert — ambiguity — posture-disallowed but enum-legal `purge_reason` is `ERR_INVALID_REQUEST`, after ladder 20/21 rather than at position 5 — routes_consent.py:135-167
- §3.6 — insert — ambiguity — the two clip passes each walk in ascending `created_at`, `clips_purged_count` is their sum; legal-hold census uses the same at-or-before comparison — routes_report.py:192-214
- §3.6 — revise — **mismatch** — a second sweep at a fixed clock does not "report zeroes across the board": `clips_held_count` is a census and repeats — routes_report.py:204-207
- §3.8 — insert — ambiguity — `flag_reason` required and non-empty; flagger id recorded as given without resolution (unknown id succeeds, resolvable `DEACTIVATED` refused) — routes_feed.py:102-104
- §3.8 — insert — ambiguity — `AUTHOR_SUSPENDED` is a cascade convention, not a validation — routes_feed.py:198, engine.py:384
- §3.8 — insert — ambiguity — case-state check outranks post-state check; `decision_note` required but may be empty — routes_feed.py:240-250
- §3.8 — revise — ambiguity — revision is a replacement: omitted signals fall back to 0; removed stale "possibly-changed position" phrasing — routes_feed.py:130-144
- §3.9 — insert — ambiguity — `ERR_AGENCY_NOT_ONBOARDED` precedes both the `expected_agency_version` and window checks — routes_report.py:91-97
- §3.9 — insert — ambiguity — whitespace-only `certification_note` refused, tested after trimming yet stored untrimmed; certification never consults the owning agency — routes_report.py:123-128
- §3.9 — insert — ambiguity — certification rebuilds the entire tally from current rows over the same window — routes_report.py:133-137
- §4 — revise — ambiguity — solicitation collection ordered by ascending `created_at` then ascending `dispatch_rank` — routes_consent.py:192

Two drafted claims were narrowed before commit under the no-new-mismatch rule (the "only unversioned mutation" and "only trimmed-for-measurement string" universals); a third about receipt counts was dropped.

### Orchestrator final verification
- `PRD.md` 506 lines / 115,117 chars; `PRD_FINALIZED.md` 506 / 115,987; `PRD_COMPLETED.md` 506 / 136,423. `PRD_COMPLETED.md` is NOT identical to `PRD_FINALIZED.md` (47 changed lines) — the scan genuinely ran.
- `PRD_COMPLETED.md` tail is the last §5 error row; not truncated.
- No file under `workspace/implementation/` was modified after the 08:23 clean sweep (latest impl mtime 08:13), and no file under `test_suite/`/`test_helpers/` was modified after 08:24 — the 8×157/157 result still describes the artifact on disk.
- Exactly one `worklog.md` in the task tree (no `workspace/` stray).

**PIPELINE COMPLETE.**
