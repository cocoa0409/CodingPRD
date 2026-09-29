# Worklog — task_2837_hybrid_work_policy_attendance_compliance

## Step 1: Create task directory — 2026-09-05T04:36:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2837_hybrid_work_policy_attendance_compliance` and `.../workspace`. Index pre-assigned by the orchestrator prompt (2837); no scan of ./tasks/ performed, per instruction that concurrent pipelines share this host.

## Step 2: Generate scaffold — 2026-09-05T06:23:00.000Z

All three scaffold artifacts are complete and lint-clean.

Lint verdict (verbatim, final run):

```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     13
  §1.8 instances scanned:     27
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  1001

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Output files

- `SCAFFOLD.yaml` — 3309 lines (175 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2289 lines (167 KB)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3892 lines (281 KB)

SCAFFOLD.yaml (§1.0–§1.7) counts

13 entities, 10 state machines, 3 concurrency rules, 14 calculations, 62 validation rules, 61 endpoints, 71 error codes, 7 roles. Profile: `entity_topology: graph`, `state_machine_shape: parallel`, `consistency_model: immediate`, `role_model: peer_roles`, layers `[optimistic_concurrency, dual_variant_calculation, rate_threshold_triggers, cascading_side_effects]`. Top-level keys confirmed to contain neither design key.

Design indices

- §1.8 `scaffold_difficulty_design` — 9 rule_id groups, **27 instances**, every one with a full test recipe.
- §1.9 `scaffold_corner_design` — all nine claim-extraction sections, **69 instances** (48 with test recipes, 21 stubs): entities 12, state_machines 13, calculations 12, validations 11, endpoints 6, errors 4, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. The 21 stubs cite 17 distinct §1.8 owners; all citations resolve by name and no name collides across §1.8 ∪ §1.9.

Two cleanups applied to SCAFFOLD.yaml at the end

- Stripped the meta-directive line `Generate task harder than expert level!` from the `scenario:` block (it would otherwise propagate verbatim into PRD.md); the domain description itself is unchanged and still verbatim.
- Corrected a stale inline comment on `api_prefix` that said "flat topology" while §1.0 declares `graph`.

Orchestrator verification: all three files present; `grep -i "harder than expert" SCAFFOLD.yaml` returns nothing (no difficulty-directive leak); `workspace/` and `worklog.md` survived the subagent.

## Step 3: Copy shared files — 2026-09-05T06:24:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T06:41:00.000Z

PRD generation is complete.

## Output
`workspace/PRD.md`
- **462 lines, 102,291 characters**
- Ends at a real boundary: the last line of the §5 error table (`| \`ERR_EQUITY_FLAG_BLOCKS_ADOPTION\` | 409 |`). No audit footer, no truncation.

## Top-level sections in order
1. `# Hybrid Work Attendance Compliance API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Resource Identity, Audit Timestamps and Record Versioning · 2.5 Flat Collections and Path Parameter Resolution · 2.6 The Logical Clock and Calendar Conventions · 2.7 Numeric Precision, Rounding and Monetary Amounts · 2.8 Stale-Version Guards on Parent Records · 2.9 Cycle Posture as a Cycle-Wide Write Gate · 2.10 Validation Precedence · 2.11 Segregation of Duties and Manager Ownership (**11 subsections**)
4. `## 3. Business Logic & Workflows` — 3.1 Policy Cycle & Teams · 3.2 Employees & Employment Status · 3.3 Role Eligibility · 3.4 Attendance Weeks & Compliance Signals · 3.5 Week Settlement & the Non-Compliance Ladder · 3.6 Exceptions & the Interactive Process · 3.7 Remote Locations: Two Parallel Reviews · 3.8 Space: Neighborhoods, Allocations, Desks, Chargeback · 3.9 Recalibration (**9 subsections**)
5. `## 4. Endpoint Definitions` — intro paragraph + 4-column table
6. `## 5. Error Code Catalogue` — 2-column table

## Coverage (all verified mechanically against SCAFFOLD.yaml with PyYAML)
- **Entities 13/13**, **state machines 10/10** (every declared state name appears in backticks in §1–§3), **calculations 14/14** (all constants rendered as prose numbers, including the two pinned-order worked divergences: seat entitlement 28-not-27 and chargeback 77,995-not-77,994), **validations 62/62**, **endpoints 61/61** (table row count = 61, every method+path pair matched), **error codes 71/71** (table row count = 71, every id/status pair matched exactly), **roles 7/7**.
- All 3 OCC rules, both interval conventions (half-open week windows vs. closed date intervals), the parallel tax × security fork-join, and all five cyclic state machines documented.

## Hard Contract reports
- **Contract 1 (Field-Name Coverage): PASS** — 143 required identifiers extracted mechanically from `entities[].fields[].name`, endpoint `input`, `query_params` and `path_params`; **0 missing**. 424 distinct backticked tokens present.
- **Contract 2 (Rule Coverage): PASS** — every validation `error_id` appears in §1–§4 prose (the sole exception is the scaffold's own placeholder `ERR_<ENTITY>_NOT_FOUND`, whose 13 concrete codes are all documented in §2.5); all transitions, side-effect cascades, `applies_to` scopes, field defaults and sibling-branch symmetries covered (ADOPT/REJECT, APPROVE/DENY, RESERVED/COMMITTED release).
- **Contract 3 (§3 Path Purity): PASS** — 0 violations: no backticked token in §3 starts with `/`, is a bare HTTP method, or combines method+path; also 0 un-backticked `METHOD /path` mentions.

## Notes for downstream steps
Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened. Three scaffold internal inconsistencies were resolved by pinning the error catalogue + state machine over the looser `validations[].rule` text, most notably `ERR_ALLOCATION_NOT_RESERVED` (one validation line claims release requires `COMMITTED`, while the state machine declares RESERVED→RELEASED and the catalogue scopes the code to commit only — the PRD documents release as legal from both, refusing only `RELEASED` with `ERR_ALLOCATION_TERMINAL`). Scratch files are in `/tmp/task_2837_prd/`; nothing was written outside the task dir, and `worklog.md`/`SCAFFOLD*.yaml` were not modified.

Orchestrator truncation check (the known doc-generator failure mode): `tail -25 PRD.md` ends on a complete error-table row and `grep "^## "` shows all 5 planned top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoint Definitions, §5 Error Code Catalogue). Not truncated — no regeneration needed. Difficulty-directive leak check: `grep -i "harder than expert"` → 0 hits.

## Step 6: Generate implementation — 2026-09-05T07:09:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, so the impl generator started before `test_suite/` existed. Step 6 returned first; the Step 5 entry follows below out of numeric order.)

Implementation complete and verified for task 2837.

## Files written (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (executable) | 10 |
| `requirements.txt` | 1 |
| `app.py` | 56 |
| `errors.py` | 95 |
| `response.py` | 53 |
| `clock.py` | 135 |
| `db.py` | 92 |
| `middleware.py` | 255 |
| `serialize.py` | 98 |
| `calc.py` | 435 |
| `recompute.py` | 179 |
| `guards.py` | 69 |
| `routes/__init__.py` | 0 |
| `routes/cycles.py` | 192 |
| `routes/employees.py` | 261 |
| `routes/attendance.py` | 182 |
| `routes/exceptions.py` | 216 |
| `routes/relocation.py` | 161 |
| `routes/space.py` | 351 |
| `routes/escalation.py` | 123 |
| `routes/recalibration.py` | 148 |
| **total** | **3112** |

## Endpoint count
`app.url_map` enumeration prints **TOTAL_ROUTES 61**, matching the scaffold endpoint table one-for-one.

## Module organization

- **Envelope / errors**: `response.py` builds `meta` (`req_` + 20 alnum id, ISO-8601 UTC with exactly 3 fractional digits, plus `limit`/`offset`/`total_count`/`has_more` on lists only), `response_type`, `data`; error bodies nest `error_id`/`message` *inside* `data`. `errors.py` holds `ERROR_STATUS` mapping all ~75 error ids to 401/403/404/409/412/422 plus `ApiError`/`fail()`.
- **Validation bands**: `middleware.py` owns bands 1–2 and 6 (auth 401, role 403 *before* existence, and every shape validator → `ERR_INVALID_REQUEST` 422) plus band 3 existence and pagination bounds. `guards.py` owns bands 4 (ownership), 8 (OCC via `STALE` map), 9 (cycle posture) and lifecycle gates. Bands 5, 7, 10–17 live inline in each route in PRD §2.10 order so precedence is readable at the call site.
- **Calculations**: `calc.py` centralizes every pinned constant and formula (pressure with its multiply→streak→round→clamp order, compliance/stage derivation, preliminary + final relocation risk, seat entitlement with buffer tiers, chargeback per-line rounding, collaboration index, equity variance, aggregate compliance rate, changeover predicate, and the deterministic desk selector). All money/rates use `Decimal` + `ROUND_HALF_UP`; no float arithmetic.
- **State machines & cascades**: transitions live in their route module; the 6-link recomputation chain and all fan-out (`settle_employee` → ladder → case → mirror, team/cycle rollups, zone load, relief re-credit) is in `recompute.py`, recomputed from scratch so band-crossing counters are counted once.
- **Store**: `db.py` — 13 in-memory dicts, empty at boot (verified: `TABLES_EMPTY_AT_BOOT` all 0), uuid4 ids, `version` starting at 1 and bumped on every mutation including cascades, and an internal `_seq` insertion counter as the `created_at` tie-breaker (the surrogate `id` is never consulted in ordering). No SQLite, no file I/O, no disk cache — grep audit for `sqlite|open(|json.dump|pickle|shelve|/tmp` returns only the false positive `gate_cycle_open`.

## Smoke test: 100+ assertions, 0 failures
Booted on port 21837 and drove a full scenario: clock rebind (unauthenticated, returns `2026-08-05T09:00:00.000Z`); 401/403 precedence; cycle create + duplicate label; team entitlement (25 heads @ 5 days → base 25, buffer 3, **28 entitled** — matches the PRD worked example); employee defaults; ownership 403; OCC 412 then classification draft→submit→approve with eligibility mirroring; attendance week Monday validation, 3 signals + dedupe 409 + outside-week 422, finalize → `SIGNAL_UNION`, credited 3, shortfall 2, pressure **3.00** → `BREACH` → `COACHING` case with `opened_pressure` 3.0; manual escalate/de-escalate with SoD 409, role 403 and floor 409; exception request interactive-process pending → request-info → respond → approve → relief 2 cures the week, pressure → 0.00, case → `CURED`; revoke restores pressure to 3.00 and threads a new case via `prior_case_id`; neighborhood band validation, seat allocation half-open window (2 weeks), commit → `line_chargeback_cents` 43330, zone `peak_committed_seats` 5 / `utilization_pct` 62.50 / `committed_seats` 0 (clock sits in W32, window covers W33–W34 — per PRD §"Zone load"); manual desk + changeover 409 + outside-window 409; `/desk-assignments/auto` → desk_index 1; vacate + `ERR_ASSIGNMENT_NOT_ACTIVE`; relocation preliminary risk 36, `ERR_REVIEWS_INCOMPLETE`, nexus budget 409, fork-join tax+security reviews, approve → final risk 45 / `BOTH_REVIEWS_CLEARED`; recalibration submit (collaboration_index 60.00, chargeback 43330) with self-approval SoD 409, stale cycle 412, ADOPT shifting the team 5→4 days and re-deriving entitlement 23, cycle reopened to `OPEN`; LOCKED cascade freezing weeks → `LOCKED` and zones → `FROZEN` with `ERR_CYCLE_LOCKED` afterwards and `ERR_INVALID_POSTURE_TRANSITION` on the terminal posture; pagination bounds 422 and meta echo; 404 error id.

Both smoke servers were killed by port (`fuser -k 21837/tcp`, `fuser -k 21838/tcp`) — no broad pkill was ever issued. A separate cold boot on 21838 from a pycache-free tree returned 200 immediately, confirming the fresh-process boot the `--isolation per-test-server` harness requires. `python3 -m compileall -q` returns `COMPILE_OK`; all `__pycache__` directories were removed afterwards. No files outside `implementation/` were read or written (`test_helpers/`/`test_suite/` untouched, `worklog.md` and `SCAFFOLD.yaml` not modified).

## Step 5: Generate unit tests — 2026-09-05T08:51:00.000Z

Suite complete. Both output directories are at the task root (`test_helpers/` and `test_suite/`); nothing was written under `workspace/`, and `workspace/implementation/`, `workspace/PRD.md`, `worklog.md` and the three `SCAFFOLD*.yaml` files were read-only throughout.

## Files written

`test_helpers/` (2,555 lines)
- `__init__.py` 48, `api_client.py` 307, `api_errors.py` 161, `assertions.py` 402, `constants.py` 174, `factories.py` 310, `fixtures.py` 814, `test_users.py` 116, `types.py` 423

`test_suite/` (9,292 lines, 16 test modules + conftest)
- `conftest.py` 68
- `test_01_policy_cycles_and_team_enrollment.py` 270 (7 tests)
- `test_02_employee_registration_and_status.py` 359 (5)
- `test_03_eligibility_classification.py` 383 (5)
- `test_04_attendance_weeks_and_signals.py` 779 (9)
- `test_05_pressure_and_severity_multipliers.py` 441 (5)
- `test_06_escalation_ladder_and_case_history.py` 591 (7)
- `test_07_exception_requests_and_the_interactive_process.py` 599 (6)
- `test_08_relief_credit_and_its_cascades.py` 455 (5)
- `test_09_remote_location_reviews_and_the_join.py` 334 (5)
- `test_10_relocation_decision_gates_and_risk_caps.py` 521 (7)
- `test_11_seat_allocation_windows_and_zone_capacity.py` 515 (7)
- `test_12_space_chargeback_and_seat_release.py` 439 (5)
- `test_13_desk_assignments_and_automatic_selection.py` 684 (7)
- `test_14_cycle_posture_and_recalibration_decisions.py` 728 (7)
- `test_15_validation_precedence_and_the_error_envelope.py` 1105 (8)
- `test_16_role_authorization_and_ownership.py` 821 (7)

## Coverage

- **Total test functions emitted: 102**, and exactly 102 `Design:` tags — one per test, no untagged, dual-tagged or dangling tag.
- **Difficulty index (queue A): 27 live instances, 0 stubs — all 27 translated**, each with at least 2 tests (the minimum), so 54 of the tests come from queue A.
- **Corner index (queue B): 69 instances — 48 live, all 48 translated** (1+ test each, 48 tests).
- **21 corner instances skipped**, all for the same reason: they are `excluded_because:` stubs carrying no `test_recipe`, so per the skip policy nothing was emitted for them (no placeholder, no xfail). They are the stubs under `scaffold_corner_design`: `cycle_lock_cascades_into_weeks_and_neighborhoods_and_blocks_child_writes`, `credited_days_diverges_between_the_union_and_corroborated_variants`, `pressure_is_a_capped_three_input_expression`, `neighborhood_peak_load_aggregates_half_open_week_windows`, `chargeback_rounds_each_line_before_summing`, `seat_entitlement_tier_is_keyed_on_the_base_not_the_total`, `relocation_selects_the_preliminary_variant_at_creation`, `duplicate_signal_outranks_the_observed_date_containment_gate`, `seat_allocation_capacity_is_an_aggregate_per_week_check`, `desk_changeover_buffer_rejects_abutting_intervals`, `relocation_eligibility_depends_on_a_different_entitys_state`, `stale_neighborhood_version_outranks_the_entitlement_ceiling`, `auto_desk_assignment_is_allowed_only_with_a_committed_allocation`, `release_reverses_every_side_effect_the_commit_applied`, `review_submit_is_the_computed_read_of_four_measures`, `a_locked_cycle_answers_one_error_for_every_child_write`, `data_residency_masks_the_risk_ceiling_error`, `authorisation_is_answered_before_existence`, `both_credited_day_variants_run_on_the_same_evidence`, `one_finalize_propagates_through_six_causal_links`, `the_neighborhood_occ_carrier_under_a_competing_ceiling`.
- No live instance was skipped; every live instance passed the PRD-first two-condition filter.

## Validation performed

- `python3 -m compileall -q test_helpers test_suite` — clean.
- Citation checker over all 16 modules: **474 PRD quotes checked, 0 problems** (each quote grep-survives against `workspace/PRD.md` after whitespace collapse, each ≥8 words).
- Import/attribute checker (imports `test_helpers` for real and resolves every imported name and every `api_client.X` attribute): **0 problems**; unused-import scan clean on every module.
- Coverage audit: `difficulty live 27 stubs 0 / corner live 48 stubs 21 / tests 102 tagged 102`, no under-covered instance, no tag pointing at a stub or a nonexistent instance.

## Notable claim-vs-PRD deviations (asserted the PRD, not the index)

Five design-index claims contradicted the PRD and were narrowed rather than asserted as written: the "refused write advances nothing" instance claimed `Employee.version` equals its registration-time value and `PolicyCycle.version == 1` (both impossible once the §3.5 settlement cascade has run — I captured the pre-refusal versions and asserted those unchanged); one instance named a nonexistent field `expected_days_aggregate` (used the PRD's `expected_daily_attendance`); plus the three earlier-noted omissions (a manager approving another manager's row, a second-`SEPARATED` `ERR_EMPLOYEE_NOT_ACTIVE`, and a `neighborhood_id` claim on the desk-assignment corner).

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root; `find workspace -maxdepth 2 -name "test_*" -type d` returns nothing (no stray test dirs under `workspace/`, the known Step 5 drift failure mode). 16 test modules, 102 test functions counted independently.

## Step 7: Run tests and iterate — 2026-09-05T09:31:00.000Z

All 8 rounds are green.

## Summary

**Iterations run:** 2 (iteration 1: 88/102 in all 8 rounds, 14 deterministic failures; iteration 2: 102/102 in all 8 rounds)

**Tests deleted:** none deleted outright. One assertion removed under STEP 1c partial coverage / BRANCH-ASYMMETRIC SIDE EFFECT:
- `test_suite/test_07_exception_requests_and_the_interactive_process.py` — `test_05`, dropped `assert from_submitted["adjudicated_by_user_id"] == "hrbp-1"`. PRD §3.6 enumerates the withdraw branch's stored fields as `status` and `closure_reason` only, while naming `adjudicated_by_user_id` explicitly for the DENY and APPROVE branches; whether WITHDRAW also stamps attribution is not uniquely derivable. The surrounding status/`granted_relief_days`/`closure_reason` assertions were kept.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — `assert_attendance_week`, iso_week shape check was off by one (`iso_week[4] == "W"`); PRD §2.6's `YYYY-Www` shape carries the hyphen, so `W` is at index 5 and the ordinal digits at 6:8. (2 failures)
- `test_helpers/fixtures.py` — `register_employee` now pops `manager_user_id` / `hr_partner_user_id` out of `**overrides` and passes them positionally; previously any test redirecting an owner by keyword hit `TypeError: employee_payload() got multiple values for argument 'manager_user_id'`. (4 failures in test_13)

**Fixes applied to `test_suite/`:**
- `test_05_pressure_and_severity_multipliers.py::test_01` — `opened_pressure` corrected from `12.00` to `8.50`; PRD §3.5 stamps `opened_pressure` at the instant the case opens (first settlement: 5 × 1.5 + 1.0), and never re-stamps it on later cascades.
- `test_06_escalation_ladder_and_case_history.py::test_05` — the loop chose role headers with `lever is api_client.escalate_case`, which is always False for a freshly bound method, so escalate ran as `MANAGER` and drew `ERR_UNAUTHORIZED`; headers are now carried in the loop tuple.
- `test_11_seat_allocation_windows_and_zone_capacity.py` — added the missing `release_allocation` import (`NameError`).
- `test_14_cycle_posture_and_recalibration_decisions.py` — four stale-version-baseline bugs: `test_01` reads the cycle version immediately before the lock instead of reusing the fixture's creation-time value; `test_02` captures the neighborhood version *after* the lock, because the FROZEN recompute mutates the zone and PRD §2.10 ranks band 8 (optimistic concurrency) above band 9 (`ERR_CYCLE_LOCKED`), so a pre-lock version legitimately returned `ERR_STALE_NEIGHBORHOOD_VERSION`; `test_04` replaces every hardcoded cycle version (`2`/`3`) with live values, since team enrolment advances the cycle version per PRD §3.1; `test_07` asserts `recalibrating_version + 1` per PRD §3.9 instead of a hardcoded `3`.

**Fixes applied to `implementation/`:** none. All 14 failures were test-artifact defects; no implementation change was needed and none was made.

**Final per-round results** (quoted from `workspace/implementation/results.{1..8}.json`): round 1 `102/102`, round 2 `102/102`, round 3 `102/102`, round 4 `102/102`, round 5 `102/102`, round 6 `102/102`, round 7 `102/102`, round 8 `102/102` — `failed=0` in every round.

`worklog.md`, `SCAFFOLD*.yaml` and `workspace/PRD.md` were not touched.

Orchestrator verification (the known "clean sweep with no artifacts" failure mode): all 8 `results.$i.json` exist (~33 KB each, written 09:20) and `json.load` each reports `passed=102 total=102 failed=0`. Confirmed independently, not taken on the subagent's word.

Step 8 decision: Step 7 made 0 `implementation/` fixes but DID make 1 assertion removal, 2 `test_helpers/` fixes and 4 `test_suite/` fixes, so this is NOT the zero-iteration skip case. Step 8 runs, with the caveat that a byte-identical `PRD_FINALIZED.md` is a legitimate outcome here — every Step 7 item was a test-artifact defect rather than a PRD silence, so there may be nothing for Step 8 to pin.

## Step 8: Finalize PRD — 2026-09-05T09:39:00.000Z

Done. Three surgical edits to `PRD_FINALIZED.md`; the remaining Step 7 items were pure test/fixture artifacts and needed no PRD change.

**Line counts:** `PRD.md` 462 lines → `PRD_FINALIZED.md` 462 lines (0.00% line delta; 3 lines revised in place, no lines added or removed).

**Changes**

- §2.6 (Logical Clock and Calendar Conventions) — revise — the ISO-week shape gloss now reads "four digits, a hyphen, a literal `W`, then two digits", matching the canonical `YYYY-Www` form string it sits beside; the old gloss omitted the hyphen, which is exactly the off-by-one the Step 7 `assertions.py` fix corrected — `implementation/clock.py:14` (`ISO_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")`), consumed at `clock.py:89-101`.
- §3.5 (Settling a Week / escalation ladder) — revise — case opening now says `opened_pressure` is recorded at that instant "and never re-stamped as later cascades move that pressure", pinning the stamping instant that the `test_05::test_01` `12.00` → `8.50` fix turned on — `implementation/recompute.py:112-120`.
- §3.6 (Attendance Exceptions) — revise — the withdrawal branch now states it "leaves `adjudicated_by_user_id` null — only a denial and an approval stamp the adjudicating user", pinning the branch-asymmetric attribution behind the deleted assertion in `test_07::test_05` — `implementation/routes/exceptions.py:159-163` (vs. `:155` DENY and `:168` APPROVE).

**Per-edit pre-edit search log**

1. ISO-week shape. (a) Subject: the accepted lexical shape of an `iso_week` / week-window label and every place labels are parsed or compared. (b) Enumerated: `clock.py` `ISO_WEEK_RE`, `week_monday`, `week_index`, `week_dates`, `weeks_touched`, `iso_week_label`, `current_week_label`; label callers in `routes/attendance.py` (week open, `ERR_INVALID_REQUEST`), `routes/space.py` (allocation window labels → `ERR_INVALID_INTERVAL`), `calc.neighborhood_derived`/`cycle_week_labels`. All require the hyphenated form and derive from the same regex. (c) Adjustment: restricted the edit to the shape clause only — I deliberately did not touch the "refused with `ERR_INVALID_REQUEST`" clause, because malformed labels on `POST /seat-allocations` surface as `ERR_INVALID_INTERVAL` per §3.8, and widening the error claim would have created a new mismatch. Also left §3.4's back-reference to "that shape" untouched.

2. `opened_pressure` stamping instant. (a) Subject: every write of `opened_pressure` and every path that changes an open case. (b) Enumerated: `grep -rn opened_pressure` over `implementation/` — only `recompute.py:116` (insert-time) and `serialize.py:71` (read model); reviewed `recompute.apply_ladder` / `settle_employee` / `mirror_stage`, and all three manual levers in `routes/escalation.py` (escalate, de-escalate, discretionary hold write `stage`, `discretionary_hold`, `last_action_by_user_id`, `action_note` only). Also confirmed each new post-cure case gets its own opening stamp, so "never re-stamps it" is per-case and true. (c) Adjustment: phrased as "never re-stamps it as later cascades move that pressure" rather than "is immutable", so the fresh-case-per-breach behavior in `apply_ladder` is not mis-described.

3. WITHDRAW attribution. (a) Subject: every writer and clearer of `adjudicated_by_user_id` across the exception-request lifecycle. (b) Enumerated: `routes/exceptions.py` create (`:72` null), `request-info` (`:91`), `respond` (`:106`), adjudicate DENY (`:155` stamps), WITHDRAW (`:159-163` does not), APPROVE (`:165-172` stamps), `revoke` (`:190-194` writes `status`/`granted_relief_days`/`closure_reason` and leaves attribution as-is), plus `serialize.py:45`. Verified withdrawal is only reachable from `SUBMITTED`/`INFO_REQUESTED`, so the field is provably still null at that point. (c) Adjustment: wrote "only a denial and an approval **stamp** the adjudicating user" instead of "no other step touches the field" — revocation preserves an earlier approver's value, so a "no other step touches it" phrasing would have been a false universal.

Orchestrator verification: `PRD_FINALIZED.md` is 462 lines / 102,464 chars (vs PRD.md 462 / 102,291); `diff PRD.md PRD_FINALIZED.md` shows exactly 3 changed lines (100, 226, 252) matching the three reported edits — not byte-identical, not truncated.

## Step 9: Complete PRD — 2026-09-05T10:11:00.000Z

Orchestrator note on method: Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. A single subagent cannot hold a 3,100-line implementation plus a 462-line/112 KB PRD and still do an exhaustive behavior-by-behavior scan; the known failure mode is a subagent that returns a byte-identical `PRD_COMPLETED.md`, meaning the scan never actually ran. Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying and edited the shared file in place. Partition: pass 1 = `app.py`, `errors.py`, `response.py`, `clock.py`, `db.py`, `middleware.py`, `serialize.py`, `guards.py`; pass 2 = `calc.py`, `recompute.py`, `routes/attendance.py`, `routes/escalation.py`, `routes/exceptions.py`; pass 3 = `routes/cycles.py`, `routes/employees.py`, `routes/relocation.py`, `routes/space.py`, `routes/recalibration.py`.

### Pass 1 (infrastructure and cross-cutting) — 462 lines / 102,464 → 109,184 chars (+6,720; 13 changed lines)

13 edits — **13 ambiguity-pins, 0 mismatch-revisions.** The error-id→HTTP-status table in `errors.py` was diffed programmatically against §5: all 71 ids match exactly in both directions. Every field name in `serialize.FIELDS` was confirmed already present in the PRD, so no serializer field set diverges.

- §2.1 — insert — ambiguity — missing/empty `X-User-Role` is also `ERR_UNAUTHENTICATED` (401), header values are whitespace-trimmed, and an unrecognized role string is `ERR_UNAUTHORIZED` — `middleware.py:38-54`
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` + exactly 20 chars from lowercase letters and digits (PRD's example implied uppercase) — `response.py:9,17-18`
- §2.2 (`api_request_timestamp`) — insert — ambiguity — read from the logical clock, so constant until rebound, and truncated not rounded to ms — `response.py:24`, `clock.py:29-31`
- §2.2 (`data`) — insert — ambiguity — a resource object carries exactly the named fields, always all of them, no internal keys; the optional `note` on posture/status moves is shape-checked then discarded — `serialize.py:93-94`, `routes/cycles.py:108`, `routes/employees.py:113`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; an empty query value counts as omitted (also for filters); undefined query params ignored — `middleware.py:229-255`
- §2.3 — insert — ambiguity — every ordering ends with `created_at` then the internal insertion sequence (never `id`); the two descending collections reverse the whole key, so ties come back newest-first — `db.py:85-92`, `guards.py:59-65`
- §2.4 — insert — ambiguity — a write that leaves every field at its existing value advances neither `updated_at` nor `version`, except the three explicitly forced advances — `db.py:66-82`, `routes/employees.py:187`, `routes/space.py:145`, `routes/relocation.py:82,101`
- §2.5 — insert — ambiguity — trailing slash insignificant; unknown path / unsupported method return `ERR_INVALID_REQUEST` at 404 / 405, decided before authentication — `app.py:18,34-43`
- §2.5 — insert — ambiguity — payload FKs resolve before the rest of body validation; a missing FK wins over other shape violations, a non-string FK yields that entity's NOT_FOUND code — `middleware.py:77-81`, `db.py:48-51`
- §2.6 — insert — ambiguity — `current_utc` accepted grammar (date + `HH:MM` minimum, optional seconds/fraction/zone, `T` or space, offsets converted to UTC) and the exact `data` payload `{"current_utc": …}` with truncating ms rendering — `clock.py:9-12,38-60`, `routes/cycles.py:33-41`
- §2.6 — insert — ambiguity — a shape-valid but unreal ISO week label (`W00`, `>W53`, `W53` of a 52-week year) is refused the same way, except inside a seat-allocation window where it surfaces as `ERR_INVALID_INTERVAL` — `clock.py:89-101`, `routes/space.py:105-109`
- §2.7 — insert — ambiguity — two-decimal quantities travel as bare JSON numbers with no trailing zeros (`0.00` → `0.0`); the four cycle dials also accept numeric strings, are range-checked before quantization, and quantize half-to-even at an exact midpoint — `serialize.py:85-90`, `middleware.py:176-190`
- §2.8 — insert — ambiguity — the three expected-version inputs must be genuine JSON integers (string/float/bool/null → 422); any integer including negatives is well formed and fails at 412 — `middleware.py:142-160`, `guards.py:27-30`
- §2.10 band 6 — insert — ambiguity — wrong-JSON-type fields are band-6 failures; explicit null counts as missing; absent/non-JSON/unparseable body is treated as `{}`, while a JSON body that is not an object is itself `ERR_INVALID_REQUEST` — `middleware.py:84-97`

### Pass 2 (calculation/cascade engine + attendance/compliance domain) — 109,184 → 111,809 chars (+2,625; 14 changed lines)

**8 ambiguity-pins, 6 mismatch-revisions.**

- §3.4 credited days L210 — insert — ambiguity — `site_code` is never matched: badge and network evidence for one date satisfy their sources independently even from different sites — `calc.py:96-110`
- §3.4 variants L212 — revise — mismatch — the "corroborated yields strictly fewer days" claim was false when the date also carries an attestation, and when the union count already exceeded the 5-day cap; now "never more, strictly fewer when a date has exactly one qualifying automated source and no attestation, subject to the cap" — `calc.py:104-113`
- §3.5 ladder L226 — revise — mismatch — **a newly opened case immediately takes its pressure-derived stage in the same cascade** (a first settlement at pressure ≥4.00 lands in `WRITTEN_WARNING`, ≥10.00 in `REFERRED`); `COACHING` is only the birth rung, and `escalation_stage` mirrors the stage the case settles on. Also pins `last_action_by_user_id`/`action_note` null at open — `recompute.py:107-127`
- §3.5 discretionary hold L234 — insert — ambiguity — `discretionary_hold` and `action_note` are both required, and the hold has no stage precondition (a `CURED`/`CLOSED_SEPARATION` case accepts it, 200) — `routes/escalation.py:93-105`
- §3.5 amendment L236 — revise — mismatch — (a) "recomputed downward" was false: dropping a zero-shortfall week out of the settled set can rejoin two breach streaks and *raise* pressure; (b) the amendment cascade is the only cascade that never opens a case, so a `BREACH` employee with no live case keeps `escalation_stage` `NONE`; (c) `required_days`, `variant_applied`, `finalized_at` survive the reopen and `amendment_reason` survives later settlements — `routes/attendance.py:155-162`, `recompute.py:110`, `calc.py:151-160`
- §3.6 interactive loop L248 — insert — ambiguity — each round overwrites `info_needed`, each reply overwrites `response_note`, neither is ever cleared — `routes/exceptions.py:91,106-110`
- §3.6 adjudication L250 — revise — mismatch — `granted_relief_days` is an integer ≥0 read only on `APPROVE`; `closure_reason` is optional on **all three** decisions and stored whenever supplied, approvals included (PRD said denial/withdrawal only) — `routes/exceptions.py:124-125,171`
- §3.6 adjudication L250 — insert — ambiguity — the relief ceiling is a policy check: 9 granted against 5 requested is `ERR_RELIEF_EXCEEDS_REQUEST` (409), a negative value is `ERR_INVALID_REQUEST` (422) — `routes/exceptions.py:124,150-152`
- §3.6 revocation L256 — insert — ambiguity — `adjudicated_by_user_id` is *not* reversed by a revoke; it stays as the audit trace — `routes/exceptions.py:190-194`
- §3.7 risk scoring L266 — revise — mismatch — "the two differ whenever any gap count or nexus cost is non-zero" was false for a nexus cost under 250,000 cents (truncates to 0 points) — `calc.py:187-197`
- §4 `GET /attendance-weeks` L343 — insert — ambiguity — filters `employee_id`, `iso_week`, `status`; an out-of-enum `status` value matches nothing rather than 422 — `routes/attendance.py:74-77`
- §4 `GET /compliance-signals` L348 — insert — ambiguity — filters `attendance_week_id`, `signal_source` — `routes/attendance.py:177-180`
- §4 `GET /exception-requests` L355 — insert — ambiguity — filters `employee_id`, `status`, `category` — `routes/exceptions.py:212-215`
- §4 escalate/de-escalate L375-376 — revise — mismatch — both rows listed `PeopleManager, HRBusinessPartner`; impl authorizes **escalate = HRBusinessPartner only** and **de-escalate = PeopleManager only** (the table contradicted §3.5, which was already correct) — `routes/escalation.py:28,60`

Left alone as already uniquely pinned: `required_days`, the 240-minute floor, relief waterfall and its `created_at` order + `required_days` cap, pressure order/ceiling, `compliance_state` bands, stage thresholds, seat entitlement's five steps, chargeback line/total rounding order, collaboration index double-rounding, equity small-cell suppression, aggregate compliance rate, the one-day changeover predicate, the desk selector's rank keys, and the six-link settlement cascade. Verified the amendment carve-out is genuinely amend-only (`allow_case_open=False` has exactly one caller) and that the classification-approval and revoke/approve cascades do still open cases, so the new universal wording holds everywhere.

### Pass 3 (remaining domain routes) — 111,809 → 117,113 chars (+5,304; 23 changed lines)

**19 ambiguity-pins, 5 mismatch-revisions.**

- §3.1 — insert — ambiguity — an `effective_to` not strictly after `effective_from` is `ERR_INVALID_REQUEST` (422), never `ERR_INVALID_INTERVAL` — `routes/cycles.py:54`
- §3.1 — insert — ambiguity — the lock cascade re-runs the *whole* zone-load derivation per neighborhood (`committed_seats`/`peak_committed_seats`/`utilization_pct` refreshed against the current logical week), not just `allocation_state` — `routes/cycles.py:131-134`
- §3.2 — insert — ambiguity — `home_timezone` is any non-empty string, never checked against a zone database; `tenure_start_date` is only shape-checked and may be in the future — `routes/employees.py:45-46`
- §3.3 — revise — **mismatch** — classification submit moves "Only `posture`" → only the classification's own `state` and `version`; no roll-up recomputed — `routes/employees.py:203`
- §3.3 — insert — ambiguity — the manager-ownership 403 necessarily sits below the existence band (unresolvable `classification_id` → `ERR_CLASSIFICATION_NOT_FOUND`) but above the shape band — `routes/employees.py:210-217`
- §3.3 — insert — ambiguity — a decision omitting `decision_note` leaves the prior note rather than nulling it; the supersede write also requires the prior row to still be `APPROVED` — `routes/employees.py:228-235`
- §3.3 — revise — **mismatch** — an `APPROVE` runs the full §3.5 employee-settlement cascade (all five counters, case opening at `BREACH`, stage drive/mirror, team + cycle roll-ups), not just a pressure/state/stage refresh — `routes/employees.py:236-237` via `recompute.py:90-104`
- §3.7 — insert — ambiguity — the residency and risk-ceiling gates are evaluated on *every* `APPROVE`, so an approval of a `BLOCKED` request at score ≥ 60 is refused rather than converted to a denial; a `DENY` consults neither — `routes/relocation.py:117-127`
- §3.8 — insert — ambiguity — neighborhood FKs resolve `policy_cycle_id` then `anchor_team_id`, and the anchor team is not checked for cycle membership — `routes/space.py:27-30`
- §3.8 — revise — ambiguity — the `FROZEN`-at-create branch is unreachable (the create is refused once the cycle locks) — `routes/space.py:45,64`
- §3.8 — insert — ambiguity — seat-allocation FKs resolve zone before team — `routes/space.py:95-98`
- §3.8 — insert — ambiguity — manual desk assignment does not gate the allocation's `status` (`RESERVED`/`RELEASED` accepted); `desk_index` < 1 is 422, out-of-band is 409 — `routes/space.py:244-265`
- §3.9 — insert — ambiguity — the days-floor gate compares the raw unclamped `expected + delta` — `routes/recalibration.py:106`
- §3.9 — revise — **mismatch** — the "team at 0 receiving −1 stays at 0" clamp example is unreachable; only the upper clamp at 5 ever fires — `routes/recalibration.py:106,125`
- §4 preamble — insert — ambiguity — filters are exact string matches; an out-of-enum or non-existent-id filter yields an empty window (`total_count` 0), not a 422/404 — `middleware.py:251-255`
- §4 `/policy-cycles` — insert — ambiguity — filter `posture` — `routes/cycles.py:96`
- §4 `/teams` — revise — ambiguity — "filtered by cycle" → `policy_cycle_id` — `routes/cycles.py:189`
- §4 `/employees` — insert — ambiguity — filters `team_id`, `status`, `compliance_state`, `escalation_stage`, `current_eligibility_class` — `routes/employees.py:96-99`
- §4 `/eligibility-classifications` — insert — ambiguity — filters `employee_id`, `supersedes_classification_id`, `state` — `routes/employees.py:255`
- §4 `/remote-location-requests` — insert — ambiguity — filters `employee_id`, `status`, `jurisdiction_code` — `routes/relocation.py:157`
- §4 `/neighborhoods` — insert — ambiguity — filters `policy_cycle_id`, `anchor_team_id`, `allocation_state` — `routes/space.py:80`
- §4 `/seat-allocations` — insert — ambiguity — filters `neighborhood_id`, `team_id`, `status` — `routes/space.py:230`
- §4 `/desk-assignments` (GET) — insert — ambiguity — filters `seat_allocation_id`, `employee_id`, `status` — `routes/space.py:346`
- §4 `/desk-assignments` (POST) — revise — **mismatch** — "inside a committed allocation's window" → any allocation status — `routes/space.py:244-262`
- §4 `/recalibration-reviews` — insert — ambiguity — filters `policy_cycle_id`, `state` — `routes/recalibration.py:144`

Verified-and-left-alone: posture/status transition tables, lock and separation cascades, entitlement/capacity/changeover gates, the auto-desk selector ranking, review submit measurements, and every gate ordering in these five files already matched §2.9/§2.10 and §3.x uniquely.

### Step 9 totals and orchestrator verification

**51 edits total: 40 ambiguity-pins, 11 mismatch-revisions.** `PRD_FINALIZED.md` 462 lines / 102,464 chars → `PRD_COMPLETED.md` 462 lines / 117,113 chars (**+14,649 chars, +14.3%**, 51 changed lines, 0 lines added or removed — every edit in-paragraph).

Orchestrator checks: `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the tell that the scan never ran); `diff` shows 51 changed line-pairs; `tail -3` ends on a complete §5 error-table row; `grep -c "^## "` = 5, so all five top-level sections survive — not truncated. Each pass independently reported that the prior passes' hunks were still present and byte-identical.

Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.
