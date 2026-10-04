# Worklog — task_3365_seasonal_kettle_campaign_bell_ringer_staffing_corps

Scenario: Seasonal Kettle Campaign, Bell Ringer Staffing & Corps Service Delivery (The Salvation Army)

## Step 1: Create task directory — 2026-10-01T09:18:00.000Z

Pre-allocated task directory `./tasks/task_3365_seasonal_kettle_campaign_bell_ringer_staffing_corps/` verified to exist with an empty `workspace/` subdirectory. No new index computed, no other `task_*` directory created (per invocation instruction).

## Step 2: Generate scaffold — 2026-10-01T10:14:45.477549817Z

Subagent (prd-bench-scaffold-generator) produced all three artifacts. The first attempt died on the 32000-token output cap with zero files written; a retry under an explicit chunked-write protocol (<=300 lines per tool call, one tool call per message, bash heredoc appends) completed the artifacts. The launching session was then interrupted before the subagent's report was recorded, so the record below is orchestrator-verified from disk rather than pasted from the subagent.

Files written and parse-verified (python yaml.safe_load, all three OK — no truncation):
- SCAFFOLD.yaml                    3124 lines / 142 KB
- SCAFFOLD_DIFFICULTY_DESIGN.yaml  1483 lines /  99 KB
- SCAFFOLD_CORNER_DESIGN.yaml      1322 lines /  82 KB

SCAFFOLD.yaml top-level: scenario, domain_name, api_prefix (/api), complexity_profile, response_envelope, entities[13], state_machines[11], concurrency_rules[3], calculations[13], validations[41], endpoints[83], errors[43], roles[14].
- Entities: Unit, Campaign, HostSite, KettleLocation, BellRinger, Shift, KettleCollection, DigitalGiving, AssistanceProgram, AssistanceApplication, CorpsProgram, DisasterDeployment, ReallocationDecision
- State machines (11): Campaign, HostSite, KettleLocation, BellRinger, Shift, KettleCollection, DigitalGiving, AssistanceApplication, CorpsProgram, DisasterDeployment, ReallocationDecision
- Roles (14): PlatformAdmin, TerritorialCommander, DivisionalOfficer, CorpsOfficer, KettleCoordinator, VolunteerCoordinator, BellRinger, CountingRoomTeller, FinanceOfficer, AssistanceCaseworker, ProgramDirector, DisasterServicesCoordinator, DigitalGivingProcessor, HostSiteManager
- Endpoints by method: POST 55, GET 28

SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rules x 2 instances = 18 (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
SCAFFOLD_CORNER_DESIGN.yaml: 4 sections = 24 instances (entities 8, state_machines 6, calculations 5, validations 5).

NOTE for Step 6: 83 endpoints is well above the ~40 endpoint threshold at which implementation generation has previously degraded into a rambling report with incomplete files. The chunked-write protocol must be enforced on the Step 6 subagent and the on-disk implementation/ must be verified independently.

## Step 3: Copy shared files — 2026-10-01T10:14:50.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes, byte-identical to the project-root copy). This is the build contract the evaluator relies on: `bash start.sh` from `./implementation/`, server on `$PORT` (default 10000), bound to 0.0.0.0, running in the foreground.

## Step 4: Generate PRD — 2026-10-01T10:30:36.317193388Z

Subagent (prd-bench-doc-generator) generated workspace/PRD.md — 480 lines / 98 KB, §1–§5. Subagent summary (verbatim):

> The PRD is complete and all three hard contracts pass mechanically. Sanity checks I ran: field-name diff against the scaffold (0 missing of 116 entity fields and 103 endpoint input names), §3 backtick scan (700 tokens, 0 path/method violations), §2.2 byte-comparison against the canonical source file (identical), and table shape checks (§4 = 4 columns x 83 rows, §5 = 2 columns x 43 rows).
>
> **Output:** workspace/PRD.md — 480 lines.
>
> **Sections:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Organizational Hierarchy, 2.5 Common Resource Properties, 2.6 Posture Gating, 2.7 Permission/Placement/Exclusivity, 2.8 Money and Rounding, 2.9 Retrieval and the 41-step Validation Order, 2.10 Optimistic Concurrency, 2.11 The Logical Clock); §3 Business Logic (3.1 Kettle Network, 3.2 Campaign Governance, 3.3 Staffing, 3.4 Counting Room, 3.5 Digital Giving, 3.6 Seasonal Assistance, 3.7 Corps Programs, 3.8 Disaster Deployment, 3.9 Performance/Reallocation/Totals); §4 Endpoints; §5 Error Catalogue.
>
> **Coverage audit (all stated in prose):** 13/13 entities and 116/116 fields; 83/83 endpoints in §4 with role lists; 103/103 request inputs; 11/11 state machines with 64/64 transitions (from/to states, preconditions and side effects); 13/13 calculations with formulas, constants, precision and ordering; 41/41 validations in explicit precedence order; 3/3 concurrency rules (write endpoint + expected_*_version + ERR_STALE_VERSION 412); 43/43 errors, every one cited outside §5 as well as inside it; 14/14 roles with identity: translated; all enum/state values and 32/32 numeric constants present.
>
> **Deliberate omissions / flags for downstream:**
> 1. corps-programs/{id}/activate and /resume appear in CorpsProgram's state-machine triggers but have no row in the scaffold's endpoint list — described as state transitions without inventing routes.
> 2. Scaffold self-conflict: validation priority 28 (ERR_PROGRAM_INTAKE_FULL at screening when at household_cap) directly negates the SCREENING -> WAITLISTED transition's identical condition. I stated both — the guard and its code, and the waitlist routing — and made waitlist the primary outcome because the screen endpoint's own side effects list ELIGIBLE/WAITLISTED/INELIGIBLE.
> 3. The three optional version inputs (expected_campaign_version, expected_host_site_version, optional expected_kettle_location_version) are named as optional with no rejection semantics, since only the three concurrency_rules entries pin OCC rejection.
> 4. Calculation identifiers (e.g. kettle_collection_variance) are never used as scaffold key names — every formula is pure prose. The only internal key name surfaced is enrollment_log, which the scaffold's enroll side effect and capacity calculation reference directly.
>
> result: PRD generated at workspace/PRD.md (480 lines, §1–§5), covering all 83 endpoints, 64 state transitions, 13 calculations, 41 validations, 3 OCC rules, 43 errors and 14 roles, with all three hard contracts passing.

Orchestrator verification on disk (independent of the report): file present, 480 lines / 98237 bytes, ends cleanly on the §5 error table; 43 distinct ERR_* ids; §4 pipe-table 85 lines (83 rows + header + separator); §5 pipe-table 45 lines (43 + header + separator); 24 section headings matching the reported outline. Numeric-constant audit against SCAFFOLD.yaml: of 76 distinct literals in calculations+validations, 71 appear verbatim; the 5 non-verbatim are all faithfully paraphrased in prose — OVERTIME_MULTIPLIER 1.5 -> "by one and a half" (line 248), LATE_CANCEL_DELTA -5 -> "subtracts five points" (line 236), NO_SHOW_DELTA -15 -> "subtracts fifteen points" (line 236), 86400 -> "the number of whole 24-hour periods ... rounded up" (line 324), SURGE_MULTIPLIER 0.6 -> "60 percent of the base rate" (line 324). No unpinned-constant drift.

Flagged for Step 5/7 (carry forward): the scaffold self-conflict on validation priority 28 vs the SCREENING -> WAITLISTED transition (item 2 above) is a live contradiction that tests must not assert both ways.

## Step 5: Generate unit tests — 2026-10-01T10:51:53.724507829Z

Subagent (prd-bench-unit-test-generator) generated test_helpers/ + test_suite/. Subagent summary (verbatim):

> All checks pass. Final verification: 68 tests collected with zero import errors, every docstring ends with exactly one resolvable Design: tag, all 18 queue-A instances carry >=2 tests, all 24 queue-B instances carry >=1, and every PRD citation has a >=8-word window that greps against PRD.md.
>
> **Files written** (19 files, 3947 lines):
> test_helpers/ — __init__.py 55, api_client.py 326, api_errors.py 99, assertions.py 168, constants.py 80, factories.py 202, fixtures.py 627, test_users.py 55, types.py 449
> test_suite/ — conftest.py 64, test_01_units_campaigns_and_host_sites.py 339, test_02_kettle_placements_and_exclusivity.py 211, test_03_screening_and_shift_scheduling.py 296, test_04_shift_lifecycle_and_reliability.py 150, test_05_counting_room_and_deposits.py 207, test_06_digital_giving_and_campaign_totals.py 217, test_07_assistance_programs_and_eligibility.py 91, test_08_performance_and_reallocation.py 207, test_09_corps_programs_and_canteen_deployments.py 104
>
> **68 tests emitted** — queue A 39 (15 instances x2, 3 instances x3), queue B 29 (19 instances x1, 5 instances x2). **SKIPPED: none** — every instance in both indices passed the PRD-first two-condition filter.
>
> Queue A (all 18 translated, >=2 tests each): both dual_variant_calc instances, both combinatorial_formula, both non_linear_state_machine, both transitive_cascade, both priority_pair_validation_conflict, both boundary_precision_check, both cross_entity_state_dependency, both resource_temporal_overlap, both compensating_invariant. Queue B (all 24 non-stub translated): 8 entities, 6 state_machines, 5 calculations, 5 validations.
>
> **Hazard (a) re-derivations** (recipe literals that were unreachable or self-contradictory as written):
> - digital_giving_outside_campaign_window_rejected — recipe leaves the campaign in PLANNING; ladder step 12 (ERR_CAMPAIGN_NOT_ACTIVE) pre-empts step 31, so I activated the campaign before the gift calls.
> - labor_budget_exceeded_on_shift_completion — recipe's note says clock 2026-11-20T09:00 but its call list omits the clock call; check-in's window makes it unreachable, so I added the clock set.
> - shift_duration_boundary_480_accepted_481_rejected — asserts paid_hours 7.5 / paid_amount_cents 11625 "after completion" but never completes the shift; I added clock + check-in + complete.
> - shift_creation_depends_on_kettle_location_state — recipe reuses the pre-activation expected_kettle_location_version; activation advances the version, so I re-read it (PRD 2.10).
> - reallocation_expected_lift_frozen_at_approval — source's remaining shift dated 2026-11-19 but apply runs at 2026-11-20; I moved it to 2026-11-21 so "remaining" is unambiguous.
> - Design prose cites validation priorities 13/32 for the collection-create conflict; the PRD ladder has them at 14/33 — asserted against the PRD numbering.
>
> **Hazard (b)**: no emitted test depends on the PRD 3.6 cap site, so neither the SCREENING -> WAITLISTED routing nor ERR_PROGRAM_INTAKE_FULL is asserted; the two statements are never tested together.
>
> **Other adjudications**: host_site_denied_is_terminal_lockdown uses validate_error_is_one_of([ERR_ALREADY_TERMINAL, ERR_INVALID_STATE_TRANSITION]) because 2.9 orders step 10 before step 11; digital_giving_attribution_empty_candidate_pool asserts only the ERR_NO_ELIGIBLE_LOCATION rejection (the post-rejection status is not uniquely derivable — PRD says "left UNATTRIBUTED", the recipe says RECEIVED); campaign_creation_defaults_status_to_planning drops the active_location_count assertion. Check-in threads X-User-ID = bell_ringer_id via make_bell_ringer_headers (3.3 owner-scoped).
>
> python3 -m pytest --collect-only -q test_suite -> 68 tests collected in 0.28s, 0 errors.
>
> result: Generated 68 design-index-tagged tests across 19 files (3947 lines) in test_helpers/ and test_suite/ for task_3365, covering all 18 queue-A instances (>=2 tests each) and all 24 queue-B instances (>=1 each) with zero skips and a clean pytest --collect-only.

Orchestrator verification on disk (independent of the report): 19 .py files totalling 3947 lines exactly as reported; pytest --collect-only reports "68 tests collected in 0.20s" with 0 errors; Design-tag audit found 68 tags / 42 distinct instances, ZERO untagged or dual-tagged tests, ZERO tags pointing to non-existent instances, and ZERO design instances left uncovered. The Step 5 contract holds mechanically.

## Step 6: Generate implementation — 2026-10-01T11:23:46.871471603Z

Subagent (prd-bench-implementation-generator) generated workspace/implementation/. Isolation rule was enforced in the prompt (no SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml / test_suite/ / test_helpers/ reads, no suite runs). Subagent summary (verbatim):

> Implementation complete and verified. I checked: all modules compile, 85 API routes register, a harness-style PORT=<free> bash start.sh boots and serves within 1 second, the envelope shape validates programmatically, and a fresh process starts with an empty store (0 units, 0 campaigns) and the clock at its pinned 2026-09-01T00:00:00Z. All servers I started were stopped by exact PID; no broad kill patterns were used, and I never opened SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/ or test_helpers/, and never ran the suite.
>
> **Files** (all under workspace/implementation/): start.sh (10), requirements.txt (1), app.py (70), core/ — clock.py (88), errors.py (108), store.py (97), envelope.py (84), auth.py (99), validate.py (133), calcs.py (471), blueprint.py (4); domain/ — units.py (118), campaigns.py (215), hostsites.py (260), locations.py (311), ringers.py (211), shifts.py (454), collections.py (240), giving.py (190), assistance.py (394), programs.py (207), deployments.py (216), reallocation.py (216), system.py (14). **4200 Python lines total.**
>
> **Endpoints:** 85 — the 83 in the PRD 4 table plus POST /api/corps-programs/{id}/activate and /resume, which the CorpsProgram state machine names as triggers but 4 omits.
>
> **Boot/smoke:** PORT=59503 bash start.sh -> ready in 1s; POST /api/units -> 201 with {"meta":{"api_request_id":"req_RKBVJ230DCXTYTGG","api_request_timestamp":"2026-09-01T00:00:00.000Z"},"response_type":"object","data":{...,"version":1}}. Live flows verified by hand: handling fee 128 cents (per-denomination floor-then-sum), paid_amount 12750 (7h base + 1h at 1.5x), provisional score 63 -> final 83, deployment cost 760000, campaign total 30000 = 25000 counted + 5000 attributed, reallocation 480->420/540, rest buffer 15-min rejected / 30-min accepted, curfew at exactly 20:00 accepted, 481-min rejected, OCC 412 on all three mandatory tokens, campaign auto-close cascade, host-site expiry cascade.
>
> **Could not implement / judgment calls:** (1) ERR_HOUSEHOLD_LIMIT_EXCEEDED is unimplementable as written — no per-application "assistance value" field exists in the entity model, so it ships as a guard that never fires on valid data. (2) ERR_PROGRAM_INTAKE_FULL is defined but unreachable: the validations table lists it for POST /screen, but the PRD ("queued rather than discarded") and the SCREENING->WAITLISTED transition both say waitlist, so I waitlisted. (3) The attribution selector's "host site's campaign owner unit" constraint has no Unit link on Campaign/HostSite, so the selector ranks the campaign's ACTIVE locations with APPROVED host sites. (4) Host-site renewal ignores the payload permission_starts_on (PRD: the renewed window begins at the current clock instant). (5) The PRD's unit-parent rule has no catalog error ID, so only a supplied-but-missing parent is rejected (404), not a missing parent outright.
>
> result: Delivered a complete Python/Flask implementation (22 modules, 4200 lines, 85 endpoints, in-memory store, pinned envelope/pagination/rounding/OCC/logical clock) at workspace/implementation/ that boots empty in ~1s via bash start.sh and passed live smoke tests of every domain; two PRD items are noted as unimplementable/unreachable.

Orchestrator verification on disk (independent of the report): all 22 source modules + start.sh + requirements.txt present, line counts match the report; start.sh is `exec python3 app.py` with a conditional pip install (good for 8-way concurrent reboot); grep for sqlite/shelve/pickle/JSON-file/open( found ZERO persistence — in-memory confirmed. Independent boot smoke test on my own port (PORT=59731, killed by exact PID): server ready, clock pinned at 2026-09-01T00:00:00.000Z, GET /api/units without headers -> ERR_UNAUTHENTICATED, POST /api/units with headers but missing territory_code -> ERR_INVALID_REQUEST, unknown route -> 404. Envelope shape matches PRD 2.2.

Carry forward to Step 7: the subagent's judgment call (2) — ERR_PROGRAM_INTAKE_FULL unreachable, waitlist chosen — is the SAME site Step 4 flagged and Step 5 deliberately declined to test. Expect no test to depend on it.

## Step 7: Run tests and iterate — 2026-10-01T11:48:51.874Z

Single long-lived fix subagent owned the run-diagnose-fix loop. Subagent summary (verbatim):

> Sanity checks complete: no source file was written after the sweep started (newest source mtime 11:44:23, sweep start 11:45:00), all 8 results files are present and complete, and each round collected 67 tests with 0 errors.
>
> ## Summary
>
> **Iterations run:** 2 (sweep 1: 58/68 — 10 deterministic failures; sweep 2 after fixes: 67/67 in all 8 rounds).
>
> **Tests deleted (1):**
> - `test_dual_violation_reports_rest_buffer_before_overlap` (test_03) — *unique-derivability collapse / design-index-only precedence*. It asserted that a request which both overlaps an existing shift and leaves no rest gap reports `ERR_RINGER_REST_BUFFER_VIOLATION` (ladder step 19) over `ERR_SHIFT_OVERLAP` (step 22). PRD §3.3 scopes the rest buffer to "the ringer's nearest **adjacent** shift" and states the overlap rule separately; §3.3's auto-assign pool lists "no overlapping shift" and "no shift whose boundary lies within 30 minutes" as *two distinct* exclusions. The precedence came only from the withheld index (`Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_shift_create`), and the sibling `test_shift_overlapping_existing_shift_rejected` (16:30–17:30 over 09:00–17:00 → `ERR_SHIFT_OVERLAP`) requires the opposite outcome for the same request class. Its other half duplicates `test_shift_gap_exactly_rest_buffer_accepted`.
>
> **Fixes to `test_helpers/`:**
> - `fixtures.py::setup_campaign_with_approved_host_site` — derived the host site's permission window from the campaign's own `starts_on`/`ends_on` instead of the hardcoded 2026 defaults. A 2027 campaign got a 2026 permission, so its in-campaign placement was correctly rejected with `ERR_PLACEMENT_WINDOW_OUTSIDE_PERMISSION` (fixed `test_duplicate_location_code_allowed_in_other_campaign`).
> - `assertions.py` (+`__init__.py`) — added `assert_same_instant()`: PRD §2.5 pins only `created_at`/`updated_at` to "exactly three fractional digits" and is silent on the echo format of caller-supplied instants, so `occurred_at`/`placement_starts_on` are now compared as instants, not strings (used in test_02 and test_06).
>
> **Fixes to `test_suite/`:**
> - `test_06` line 180 — location total corrected 70000 → 95000; PRD §3.9 says "a single location's `location_total_cents` is the same construction scoped to that location" (counted collections + attributed digital gifts).
> - `test_08::setup_two_location_network` — banked both collections *before* the shifts complete, so the PRD-mandated completion-time recompute of `cents_per_hour`/`performance_tier` (§3.3) sees the money; the lift preview then reads well-defined 3000/7500 figures. (PRD §3.4/§3.5 enumerate what a deposit/attribution recomputes and the grading is not among them, so this was a fixture-ordering ambiguity, not an implementation defect.)
>
> **Fixes to `implementation/`:**
> - `domain/locations.py` — the performance read returned the *stored* `performance_tier` snapshot (stale after any money or no-show that isn't one of §3.9's four recompute triggers) instead of the grade computed from live counters that §3.9 says the read exposes; now returns `snap["performance_tier"]`.
> - `domain/collections.py::recount_collection` — replacing `coin/currency/check_cents` now re-derives `counted_total_cents` and `handling_fee_cents`; PRD §3.4 defines the total as "the sum of the coin, currency and cheque counts", so a recount that left 72345 against counts summing to 70000 was self-contradictory.
>
> **Test-side fixes outnumbered implementation fixes (5 test files vs 2 impl files).** Implementation paths/behaviors no test asserts, for Step 8:
> 1. `calcs.apply_variance_demotion` (called from `domain/collections.py` on `VARIANCE_HOLD`) writes a one-step tier downgrade to the location row; the performance read now recomputes the tier live, so the §3.4 demotion is visible only on `GET /kettle-locations/{id}` and is wiped by the next recompute. No test asserts the demotion at all.
> 2. `calcs.recompute_location` is not triggered by deposit, attribution, or reversal, so a location's stored `cents_per_hour`/`performance_tier` can disagree with its own `location_total_cents` (PRD §3.3 calls these "derived from live rows"). No test asserts freshness after a deposit.
> 3. The no-show path recomputes a location's grading only via the suspension cascade (cancelled future shifts), never for the no-show itself, though no-shows feed the disruption record.
> 4. Carried from Step 6: `ERR_HOUSEHOLD_LIMIT_EXCEEDED` and `ERR_PROGRAM_INTAKE_FULL` ship as guards that never fire on valid data; host-site renewal ignores the payload `permission_starts_on`.
>
> **Final sweep:** rounds 1–8 all `passed=67 total=67 failed=0 errors=0 skipped=0` (results files left in place at `workspace/implementation/results.{1..8}.json`).
>
> result: All 67 tests pass in all 8 parallel rounds of the stability sweep for task_3365 (1 design-index-only test deleted, 4 test-side fixes, 2 implementation fixes).

Orchestrator verification on disk (independent of the report): all 8 `results.{1..8}.json` present (20.7 KB each, written 11:47:05); each parses to `{'passed': 67, 'total': 67, 'failed': 0, 'errors': 0, 'skipped': 0}`. Newest *source* file mtime is 11:44:23 (`domain/collections.py`) — BEFORE the results were written at 11:47:05 — so no implementation edit post-dates the passing sweep (pycache excluded). Test count 68 -> 67 consistent with the single reported deletion.

## Step 8: Finalize PRD — 2026-10-01T12:03:25.909Z

Step 8 ran (not skipped): Step 7 had 1 deletion + 4 test-side fixes + 2 implementation fixes. Subagent (PRD finalizer) summary (verbatim):

> All 12 edits are in, verified by diff: 8 hunks, nothing else touched, 480 lines before and after.
>
> **Sanity check run:** `diff -u PRD.md PRD_FINALIZED.md` shows exactly the 8 intended hunks (12 changed lines each way); §5's error catalogue is intact; the file is complete; no other file was written. Line counts: PRD.md 480 lines / 98,237 B → PRD_FINALIZED.md 480 lines / 100,780 B (**0% line delta**, +2.6% bytes from inline insertions).
>
> **Changes** (each traced to a `<step_7_diff>` item):
> - **§2.5 — insert** — every timestamp a resource carries, including a caller-supplied one (`starts_on`, `placement_starts_on`, `occurred_at`, `starts_at`), is normalized to the same three-fractional-digit UTC form rather than echoed verbatim — `implementation/core/clock.py:30-35` (`fmt`), applied at `domain/giving.py:87`, `domain/locations.py:128-129`, `domain/shifts.py:106-107`, `domain/ringers.py:84,182`, `domain/hostsites.py:96-97,246-247`, `domain/collections.py:62`, `domain/assistance.py:78-79,342`, `domain/campaigns.py:90-91`, `domain/deployments.py:166,207`, `domain/reallocation.py:53,212`. *(test_helpers `assert_same_instant` item)*
> - **§2.9 rung 28 — revise** — the cap rung no longer claims `ERR_PROGRAM_INTAKE_FULL`; a full program waitlists — `domain/assistance.py:254-261`. *(carried Step 6 guard item)*
> - **§2.9 rung 41 — revise** — the ceiling rung restated as the negative-configured-limit guard — `domain/assistance.py:280-284`. *(same item)*
> - **§3.1 — insert** — renewal accepts and ignores a payload `permission_starts_on`; the window always starts at the clock instant — `domain/hostsites.py:211-224`. *(carried Step 6 item)*
> - **§3.3 — insert** — the rest-buffer test applies only to the ringer's live non-overlapping shifts, and a rest-buffer violation is the one reported when a request both overlaps one shift and comes within 30 minutes of another — `domain/shifts.py:59-72` (both `create_shift:145` and `rebook_shift:404`). *(deleted `test_dual_violation_...` item)*
> - **§3.4 verify — revise** — the downgrade is written to the location row's stored `performance_tier`, shows on a plain location read, and is replaced by the next recompute — `core/calcs.py:287-291`, `domain/collections.py:150-155`. *(impl no-test path 1)*
> - **§3.4 recount — revise** — a recount re-derives `counted_total_cents` and `handling_fee_cents` from the new counts — `domain/collections.py:179-190`. *(implementation fix)*
> - **§3.6 screening — revise** — screening never returns `ERR_PROGRAM_INTAKE_FULL`; it waitlists — `domain/assistance.py:254-261`. *(carried Step 6 item)*
> - **§3.6 approval — revise** — no household assistance value is accumulated; the guard fires only on a negative configured limit — `domain/assistance.py:280-284`. *(same item)*
> - **§3.9 grading — revise** — variance hold applies only the one-step demotion (no full recompute); the recompute stores four figures on the row; deposit/attribution/reversal refresh only `location_total_cents`, so stored `cents_per_hour`/`performance_tier` can lag — `core/calcs.py:276-291`, `domain/collections.py:13-16`, `domain/giving.py:14-27`. *(impl no-test paths 1-2, test_08 fixture fix)*
> - **§3.9 performance read — insert** — the read computes every returned figure from live rows — `domain/locations.py:298-315`, `core/calcs.py:246-273,304-318`. *(implementation fix)*
> - **§3.9 reallocation preview — revise** — the two cents-per-hour figures are the stored row values — `domain/reallocation.py:21-22,56-58`. *(test_08 fixture fix)*
>
> **Per-edit pre-edit search log** (subject → paths enumerated → wording adjustment):
> 1. *Instant string form* → all 12 writers of caller-supplied instants plus `store.public` and `clock.fmt` → scoped the claim to "timestamps a resource carries" so it does not overreach to `meta.api_request_timestamp` or the clock endpoint's `current_utc`.
> 2. *Cap rung* → `screen_assistance_application`, `accepted_application_count`, `create_assistance_application`, `approve`, `distribution_no_show`, `errors.py` (grep: never raised) → replaced the error outcome, kept the comparison framing.
> 3. *Ceiling rung* → `approve_assistance_application`, program creation, grep for any household accumulation (none exists) → replaced the accumulation comparison with the shipped guard, scoped to approval.
> 4. *Renewal inputs* → `renew_host_site` only; `create_host_site` uses its own payload start → scoped to "on the renewal request".
> 5. *Rest/overlap precedence* → `check_schedule_window` (live-status filter, overlap `continue` before gap, rest raised first), its two callers, `select_auto_assign_ringer` (collapses both exclusions into `ERR_NO_ELIGIBLE_RINGER`) → **adjusted**: dropped a blanket "rest precedes overlap" claim (false for the single-overlap case) in favour of the scoped dual-violation statement; left curfew ordering untouched.
> 6. *Demotion landing site* → `verify_collection` (demotes), `reconcile_collection` (VARIANCE_HOLD, **no** demotion), `apply_variance_demotion`, `recompute_location`, `location_performance` → **adjusted**: scoped the demotion to the verification path and added "stored", because a blanket "a location in VARIANCE_HOLD is demoted" misdescribes the reconcile sibling.
> 7. *Recount re-derivation* → `recount_collection`, `verify_collection`, `create_collection`, `deposit_collection`, `calcs.counted_total`/`handling_fee_cents` → no adjustment; deliberately silent on `variance_cents`/`deposited_cents` and on totals refresh, which recount does not touch.
> 8. *Screening at cap* → same set as (2) → no adjustment beyond removing the false error claim.
> 9. *Approval ceiling* → same set as (3) → no adjustment.
> 10. *Stored vs live grading* → all writers/readers of `covered_minutes`, `location_total_cents`, `cents_per_hour`, `performance_tier` (incl. `refresh_location_total`, `giving.refresh_totals`, `select_attribution_location` which ranks by the **stored** `covered_minutes`) → **adjusted**: listed exactly the four figures the row stores, and stated the recompute-trigger list minus variance hold rather than making any global "grading is always live" claim.
> 11. *Performance read source* → `location_performance` + `performance_snapshot` + `coverage_for_date` → **adjusted**: scoped to "the read" so it cannot be read as covering the reallocation preview or the attribution selector, which do use stored values.
> 12. *Preview cents-per-hour* → `_location_cents_per_hour` and its two callers → no adjustment; the clause stays about the preview and makes no claim about the approval step.
>
> **Observed but deliberately not edited** (not in `<step_7_diff>`, so out of HARD SCOPE): `check_schedule_window` evaluates the minor-curfew rule *after* overlap (`domain/shifts.py:73-74`) while §2.9 rung 20 precedes rung 22; the auto-attribution selector ignores the gift's credited unit (`domain/giving.py:153`, `core/calcs.py:402-414`) though §3.5 names a unit filter; approval re-derives `expected_lift_cents` from the stored figures rather than literally freezing the preview (`domain/reallocation.py:126-130`); and cascade cancels (suspend/close/permission-expiry) cancel shifts without recomputing the location grading (`domain/hostsites.py:24-42`).
>
> result: PRD_FINALIZED.md written — 12 inline edits across 8 hunks (480 lines, 0% line delta), each traced to a step_7_diff item and each preceded by a whole-implementation path search.

Orchestrator verification on disk (independent of the report): PRD.md 98,237 B / PRD_FINALIZED.md 100,780 B; `diff -u` yields exactly 8 hunks and 24 changed lines (12 insertions + 12 deletions); `diff -q` confirms the files differ (not a silent no-op copy). The 4 items the subagent listed under "observed but deliberately not edited" are explicitly handed to Step 9 as residual mismatch candidates.

## Step 9: Complete PRD — 2026-10-01T12:16:06.547Z

Step 9 ran (always runs). Subagent (PRD completeness scan) summary (verbatim):

> Sanity checks done: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md; all 31 inserted phrases verified present by grep; the §4 route table now matches the implementation exactly (85/85 routes, zero role-set diffs); edited paragraphs re-read for coherence.
>
> **Output:** workspace/PRD_COMPLETED.md
> **Source:** PRD_FINALIZED.md — 480 lines / 100,780 chars → 482 lines / 105,371 chars (**+2 lines, +4,591 chars**; 29 modified lines + 2 new table rows).
> **Counts:** 20 ambiguity-pins, 11 mismatch-revisions.
>
> **Change list**
> - §2.3 — insert — ambiguity — limit/offset out of range are clamped, negative offset becomes 0, non-integer non-empty values give `ERR_INVALID_REQUEST` — core/envelope.py:58-76
> - §2.4 — revise — mismatch — unit-tree shape (TERRITORY root / every other unit parented) is not enforced; any type may be created with or without a parent; unresolvable parent = body-FK error — domain/units.py:49-75
> - §2.9 rung 7 — insert — ambiguity — `ERR_PARENT_NOT_FOUND` unreachable, no route names two path resources — all domain routes
> - §2.9 rung 20 — insert — mismatch — curfew is evaluated **after** overlap, so a both-violating request reports `ERR_SHIFT_OVERLAP` (focus a) — domain/shifts.py:69-74
> - §2.9 rung 26 — insert — mismatch — duplicate `location_code` is checked before containment/exclusivity on creation — domain/locations.py:116-142
> - §2.10 — insert — ambiguity — stale token is compared **before** the operation's state checks — core/validate.py:123-133
> - §2.11 — insert — ambiguity — clock-driven transitions fire on the single reads (campaign, campaign summary, host site, ringer), not on list routes — domain/campaigns.py:149,190; hostsites.py:143; ringers.py:133
> - §3.1 renewal — revise — ambiguity — refusal codes: `ERR_INVALID_REQUEST` (400) for end ≤ clock, `ERR_INVALID_STATE_TRANSITION` (409) for double-booking, touching windows count as overlapping — domain/hostsites.py:208-243
> - §3.1 suspension — revise — mismatch — cancels `SCHEDULED` **and `CONFIRMED`** shifts — domain/locations.py:227-243, hostsites.py:24-42
> - §3.2 close cascade — insert — mismatch — does not recompute host sites' `active_kettle_count` or the locations' grading — domain/campaigns.py:46-61
> - §3.2 summary — insert — ambiguity — `attainment_pct` = floor(100·raised/goal), zero when goal is zero — domain/campaigns.py:194
> - §3.3 duration — insert — ambiguity — `ends_at <= starts_at` is `ERR_INVALID_REQUEST` (400), checked before the 480-minute ceiling — domain/shifts.py:40-44
> - §3.3 screening request — insert — ambiguity — a `PENDING` or `CLEARED` screening is refused with `ERR_INVALID_STATE_TRANSITION` — domain/ringers.py:149-155
> - §3.3 separate — insert — ambiguity — only an `ACTIVE` engagement may be separated — domain/ringers.py:200-208
> - §3.3 auto-assign — insert — ambiguity — the minor-curfew rule is not part of the selector's pool — core/calcs.py:430-471
> - §3.4 reconcile — insert — ambiguity — omitted `bank_confirmed_cents` defaults to `deposited_cents` — domain/collections.py:234-236
> - §3.4 reconcile — insert — ambiguity — every outcome other than matched-over-equal (incl. not-matched-over-equal) takes `VARIANCE_HOLD` — domain/collections.py:240-244
> - §3.5 selector — revise — mismatch — the credited `unit_id` is not consulted (focus b) — core/calcs.py:402-414, domain/giving.py:153
> - §3.5 empty pool — revise — ambiguity — a `RECEIVED` gift is moved to `UNATTRIBUTED` before `ERR_NO_ELIGIBLE_LOCATION` is returned — domain/giving.py:154-158
> - §3.5 attribution pass — revise — mismatch — the `UNATTRIBUTED` move is driven by an explicit attribution attempt, not a background pass — domain/giving.py:152-158
> - §3.6 screening — insert — ambiguity — a `DRAFT` program is refused with `ERR_INVALID_STATE_TRANSITION` — domain/assistance.py:238-239
> - §3.6 approval — insert — ambiguity — a non-`CORPS` distribution unit is `ERR_INVALID_REQUEST` (400) — domain/assistance.py:276-278
> - §3.6 booking — insert — ambiguity — a start before the clock is `ERR_INVALID_STATE_TRANSITION` (409) — domain/assistance.py:315-316
> - §3.6 no-show — insert — ambiguity — the no-showed application is excluded from the immediate waitlist promotion — domain/assistance.py:392
> - §3.8 cost — insert — ambiguity — a not-yet-deployed row bills zero days/costs zero; the read recomputes into the response without advancing `version` — core/calcs.py:360-381, domain/deployments.py:87-100
> - §3.9 grading — revise — mismatch — recompute happens on completion, route cancellation, the no-show suspension cascade and reallocation apply; location/campaign/host-site expiry cascades do not recompute (focus d) — domain/hostsites.py:24-42, campaigns.py:36-58, locations.py:241,270
> - §3.9 coverage — insert — ambiguity — a `COMPLETED` shift belongs to the date of its `starts_at`; omitted `on_date` = current clock date — core/calcs.py:304-318, domain/locations.py:289-296
> - §3.9 approval — revise — mismatch — approval re-derives `expected_lift_cents` from current stored `cents_per_hour` (focus c) — domain/reallocation.py:126-130
> - §4 table — revise — mismatch — suspend description now says `SCHEDULED` and `CONFIRMED` shifts — domain/locations.py:241
> - §4 table — insert — ambiguity — two undocumented endpoints added (`POST /api/corps-programs/{id}/activate`, `POST /api/corps-programs/{id}/resume`, both ProgramDirector/CorpsOfficer/PlatformAdmin) — domain/programs.py:89-129
>
> **Dead-code sweep:** every `def` in `core/` (49) and `domain/` (79) was grepped for callsites. Defined-but-never-called: `core/errors.py:107 fail()`, `core/validate.py:119 stale()`, `core/auth.py:73 is_entity_backed()`, `core/auth.py:92 backing_entity_guard()`, `core/calcs.py:94 shift_duration_hours()`, `domain/campaigns.py:22 recompute_campaign()`, `domain/units.py:37 recompute_unit()`, `domain/ringers.py:16 screening_valid_for()`. None is a PRD-required check that is skipped: the screening check PRD requires is implemented and called at `domain/shifts.py:93 ringer_is_screened()`; unit commitment is recomputed by `domain/deployments.py:22 refresh_unit_commitment()`; campaign figures are recomputed live by the summary/close paths. Left in place (not deleted) and no PRD text was changed for them. Error reachability: `ERR_PARENT_NOT_FOUND` is never raised (pinned), and `ERR_PROGRAM_INTAKE_FULL` / `ERR_HOUSEHOLD_LIMIT_EXCEEDED` were already pinned by Step 8 — I re-verified both against `domain/assistance.py:255-260,282-284` and left them unchanged.
>
> **Not papered over (residual, pinned as actual behavior rather than fixed):** the auto-assign selector can schedule a minor past curfew; campaign close leaves host-site counters and location grading stale; the attribution selector ignores the gift's credited unit.
>
> result: PRD_COMPLETED.md produced — 482 lines (+2), +4,591 chars over PRD_FINALIZED.md, with 31 inline pins/revises (20 ambiguity-pins, 11 mismatch-revisions) covering all four focus items, the route-table gap, and a full dead-code sweep.

Orchestrator verification on disk (independent of the report): PRD_COMPLETED.md present (105,371 B, 12:14); `diff -q` confirms it differs from PRD_FINALIZED.md (not a killed-mid-flight no-op); `diff -u` yields 16 hunks / 56 changed lines. Post-sweep integrity re-checked: newest implementation source mtime is 11:44:23 and newest test-file mtime 11:44:14, both still BEFORE the results files written at 11:47:05 — neither Step 8 nor Step 9 modified any code or test, so the Step 7 green sweep remains valid and does not need re-running.
