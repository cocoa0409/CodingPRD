## Step 1: Create task directory — 2026-09-05T21:00:03.652670543Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2950_pediatric_private_duty_nursing_authorization_staffing and its workspace/ subdirectory. Index 2950 was pre-assigned by the orchestrating caller; no index scan was performed.

## Step 2: Generate scaffold — 2026-09-05T22:38:54.591059433Z

Step 2 complete. All three scaffold artifacts are written, mutually consistent, and lint-clean.

Deliverables (lines / bytes):
- SCAFFOLD.yaml — 2923 / 134,924
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2234 / 137,093
- SCAFFOLD_CORNER_DESIGN.yaml — 4599 / 257,777
Total 9756 lines. worklog.md and workspace/ untouched by the subagent.

SCAFFOLD.yaml (§1.0–§1.7):
- Keys exactly: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — no design keys leaked in.
- Counts: 13 entities · 8 state machines · 2 concurrency rules · 12 calculations · 39 validations · 65 endpoints · 49 errors · 6 roles.
- complexity_profile: primary quota_allocation, secondary temporal_windowing, layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy], topology flat, state-machine shape parallel, role model segregation_of_duties, consistency immediate.
- api_prefix /pdn, with logical-clock endpoint POST /pdn/_clock/set_current_utc (default 2026-08-01T00:00:00Z); all corner recipes park the clock at 2026-08-03T06:00:00Z (ISO week 32 of 2026).

Design files:
- §1.8: 9 rule_ids × 2 instances = 18 instances (utilization dual-variant divergence, continuity scoring, per-timesheet rounding, deduction-tier selection, parallel staffing/EVV axes, billing-edit resubmit cycle, 4-hop hospitalization cascade, reduction-appeal waterfall trim, two priority-conflict pairs).
- §1.9: 73 instances across all 9 claim-extraction sections — 53 with full test_recipes and 20 excluded_because stubs, each citing a real §1.8 instance name. Per section: entities 12, state_machines 12 (3 stubs), calculations 11 (6), validations 20 (7), endpoints 5 (2), errors 2, rbac 5, complexity_layers 5 (2), consistency_model 1.

Notable consistency work:
- Every literal derived from actual §1.3 formulas (480 scheduled minutes for 08:00–16:00, ceil(14/2)=7 DEFICIENT vent cadence, round_half_up(2/3,4)=0.6667, renewal ratio exactly 0.5000); all 49 error ids are triggered by an error_id assertion somewhere in §1.8+§1.9.
- Two SCAFFOLD.yaml edits made corner claims reachable: apply-reduction side effect now spells out the trim cascade (surplus ASSIGNED shifts → CANCELLED/AUTH_REDUCTION with their assignments), and validation priority 9 (ERR_INVALID_STATE) carries a carve-out note for POST /pdn/authorization-disputes so ERR_DISPUTE_ALREADY_OPEN (p28) and ERR_AUTHORIZATION_NOT_ACTIVE (p11) are reachable.
- The lint's FK reverse-reachability check requires the parent placeholder to be literally {id}, so all named path placeholders ({case_id}, {nurse_id}, …) were renamed to {id} across all three files (225/10/32 replacements) with ${var} substitutions protected.
- Forbidden concurrency vocabulary absent; no business decision keys off id/UUID — only created_at ASC/DESC tie-breaks.

Lint verdict (verbatim): "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." Coverage: 65 endpoints, 13 entities, 18 §1.8 instances, 53 §1.9 instances, 1077 calls scanned. No sibling task directory was read, listed, or grepped.

ORCHESTRATOR POST-STEP-2 ACTION: the scaffold generator copied the difficulty directive line "Generate task harder than expert level!" verbatim into SCAFFOLD.yaml's scenario: block (line 2), from which it would have reached PRD.md via the doc generator. Stripped that line plus its following blank line from SCAFFOLD.yaml (2923 -> 2921 lines); grep now confirms the phrase is absent from SCAFFOLD.yaml. The directive remains only in the two design files, which are withheld from the doc generator by design.

## Step 3: Copy shared files — 2026-09-05T22:38:54.591059433Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T22:55:54.278001648Z

PRD.md is complete: workspace/PRD.md — 534 lines, 98,111 bytes, built in 14 incremental heredoc appends (no one-shot Write; no truncation).

Sections written (26 headings): §1 Introduction; §2 Global Specifications with 12 subsections (2.1 Roles/RBAC, 2.2 API Response Structure byte-verbatim, 2.3 Pagination, 2.4 Common Properties/Versions/Audit, 2.5 Logical Clock, 2.6 OCC, 2.7 Path Resolution & Not-Found, 2.8 Validation Precedence, 2.9 Units/Precision/Rounding, 2.10 Cascade Discipline, 2.11 Segregation of Duties, 2.12 Conserved Quantities); §3 Business Logic & Workflows with 9 domain-derived subsections (3.1 Reference Data -> 3.9 Reductions/Appeals/Renewal/Expiry); §4 Endpoint Definitions; §5 Error Code Catalogue. No audit footer, no contract-report section inside the file.

CONTRACT 1 — FIELD-NAME COVERAGE: PASS. Run twice with independent extractors plus a third sweep. (a) All 102 distinct entity field names across all 13 entities (Payer, Patient, PlanOfCare, Authorization, Nurse, NurseCompetency, Case, Shift, ShiftAssignment, Timesheet, SupervisoryVisit, IncidentReport, AuthorizationDispute) appear in backticks — diff empty. (b) All 104 distinct endpoint input/output field names appear in backticks — diff empty. (c) All 13 entity names and every state-machine field present. An initial pass falsely reported 102 misses; cause was the generator's own regex tripping over the ```json fences in §2.2 flipping backtick parity — after stripping fenced blocks the diff is empty.

CONTRACT 2 — RULE COVERAGE: PASS. All 39 validations enumerated in §2.8 in ascending priority order (priorities 1–39 all named; every validation error_id reachable, the 12 not-found codes delegated to §2.7's explicit list from checks 5 and 6). All 8 state machines / 42 transitions covered with every declared state, initial state and terminal state present. Both concurrency_rules in §2.6 and §2.8 check 8. All 12 calculations expressed in prose. All 49 error IDs referenced in §2/§3 narrative, not merely catalogued. All 31 symbolic constants (UNIT_MINUTES, TIER_*_PCT, AVAILABILITY_STEP_MINUTES, RENEWAL_MIN_RATIO, cadence days, etc.) translated to literal numbers per the no-pseudocode rule — the symbol names deliberately do not appear.

CONTRACT 3 — §3 PATH PURITY: PASS. §3 spans lines 225–407 (183 lines). Zero backtick tokens beginning with /, zero backtick tokens containing a bare HTTP method, zero occurrences of GET|POST|PUT|PATCH|DELETE anywhere in §3 prose, zero occurrences of /pdn in §3. Operations framed as state transitions (OPEN -> ASSIGNED), role+gerund, or capability descriptions.

Additional verification: §4 table = exactly 65 rows / 4 columns, method+path set matches the scaffold exactly (0 missing, 0 extra, 0 dups), all 65 role lists match the scaffold verbatim. §5 table = exactly 49 rows / 2 columns with statuses matching the scaffold. The 15 endpoints named as 201 in the §4 preamble are exactly the scaffold's 15 success_status: 201 endpoints.

Constraints honoured: the two design YAMLs were never opened, grepped, or referenced. No other file created, modified or deleted. Scratch confined to .scratch/step4/ and rm -rf'd at that level only (parent .scratch/ intact). No pkill run.

ORCHESTRATOR VERIFICATION (truncation guard): independently confirmed PRD.md = 534 lines / 98,111 bytes, headings §1–§5 all present at lines 3/11/225/408/480, 49 ERR_ table rows, and the file ends on the complete final table row "| `ERR_PAYER_MISMATCH` | 422 |" — a real section boundary, not mid-sentence. Also grepped PRD.md for the Step 2 difficulty directive: absent. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T23:31:46.285067716Z

(Note on ordering: Steps 5 and 6 were launched concurrently in a single message per the skill. Step 6 returned first, so its entry is recorded here ahead of Step 5's; Step 5's entry follows below.)

Implementation complete and verified. Deliverables in workspace/implementation/:

| file | lines | role |
|---|---|---|
| start.sh (executable) | 8 | cd $(dirname $0), guarded pip install (only when import flask fails), exec python3 app.py |
| requirements.txt | 1 | flask>=2.0 |
| app.py | 87 | 4 blueprints under /pdn, global RLock per request, cascade.begin() in before_request, ApiError/404/405/500 handlers, 0.0.0.0:$PORT (default 10000) |
| timeutil.py | 119 | lenient ISO-8601 parsing, canonical ...THH:MM:SS.mmmZ output, ISO-week half-open windows |
| errors.py | 70 | all 49 error IDs -> HTTP status, ApiError, fail() |
| envelope.py | 45 | meta/response_type/data, pagination meta (limit 10/1/100, offset 0) |
| store.py | 77 | in-memory dicts only, clock default 2026-08-01T00:00:00Z, hidden _seq tie-break |
| derive.py | 548 | all calculations (utilization both bases, 4-step billing edit, match/continuity score, selector, cadence, fill metrics, EVV outcome, renewal gate) |
| auth.py / validate.py / serialize.py / lookup.py / cascade.py | 87 / 281 / 232 / 41 / 231 | RBAC + entity-backed ownership, shape checks, per-entity projections, cascades + version/updated_at bookkeeping via derived-signature diff |
| routes_reference.py / routes_plans.py / routes_cases.py / routes_shifts.py | 290 / 473 / 293 / 541 | endpoints 1-15 / 16-33 / 34-46 / 47-65 |

Total 3,424 lines. No seeding: every dict starts empty on boot (verified by rebooting and reading a pre-reboot id -> ERR_PAYER_NOT_FOUND, GET /pdn/patients -> total_count: 0).

Endpoint coverage: 65 / 65. Enumerated app.url_map — exactly the 65 paths+methods of PRD §4, including PATCH /pdn/timesheets/{id}, both _clock/_ops controls and all four nested lists.

Smoke test (port 21437, killed by that PID only, no pkill): four scripted suites, ~250 requests, 0 tracebacks and 0 HTTP 500s in the server log.
- Happy path: payer -> nurse+competency -> patient -> plan -> submit -> authorization -> activate -> case -> activate -> shift -> candidates -> auto-staff -> clock-in/out -> submit -> ACCEPT. match_score 40, scheduled_minutes 480, gross/net = 32/32, billed_units_to_date 32; 401/403/404/400 negative probes all correct.
- Appeals/holds: vent cadence 14 -> DEFICIENT visit -> cadence_days_applied 7; escalate TIER1 -> TIER3 (no parent backup) and parent-backup -> ERR_NO_PARENT_BACKUP; reduce -> dispute -> review -> out-of-band decide 422 -> PARTIALLY_GRANTED -> auth REDUCED @ 40.0; HIGH incident -> ON_HOLD/INCIDENT_REVIEW, resume blocked (409), segregation (403), resume by another supervisor, close -> patient DISCHARGED.
- Manual staffing/billing: ERR_NURSE_EXCLUDED_FROM_CASE, ERR_STALE_SHIFT_VERSION, ERR_COMPETENCY_DUPLICATE, ERR_LICENSE_NUMBER_TAKEN, continuity match_score 80; cancel returns shift to OPEN and hours_committed_this_week to 0.0 (conserved minutes exact); STRICT_15MIN MANUAL late clock-in -> gross 31, deduct 8, net 23 with [EVV_EXCEPTION, LATE_START, MANUAL_ENTRY]; nurse PATCH -> EDITED, net 25, POST_EDIT added and LATE_START dropped.
- Renewal/expiry: settled ratio 0.8 from the last completed week, ERR_APPROVED_EXCEEDS_REQUESTED, successor PENDING depth 1 abutting at 2026-09-01, activation -> predecessor SUPERSEDED + case repointed, checkpoint -> expired_authorization_count 1 and case ON_HOLD/AUTHORIZATION_EXPIRED. Voiding an accepted timesheet returned billed_units_to_date to 0 and settled units to 0 exactly.

Notes worth flagging:
- Test isolation respected: test_suite/ and test_helpers/ were never read, listed or grepped.
- PRD-vs-scaffold conflict resolved in the PRD's favour: §3.3 pins "issuing the authorization is only possible while the plan sits in SUBMITTED", so a second create against an UNDER_REVIEW plan yields ERR_INVALID_STATE (409) at precedence check 9, ahead of the OCC/cap checks — despite §2.6's narrative about a second create superseding the first.
- Scratch space .scratch/step6/ was used and removed; sibling step5* dirs untouched. Nothing outside workspace/implementation/ was created or modified.

## Step 5: Generate unit tests — 2026-09-05T23:40:53.957132774Z

Step 5 complete. All deliverables are at the task root, nothing under workspace/. `find workspace -name test_helpers -o -name test_suite` returns nothing.

Per-file line counts:
- test_helpers/ (9 modules, 2,153 lines): __init__.py 26, api_client.py 515, api_errors.py 115, assertions.py 178, constants.py 84, factories.py 403, fixtures.py 504, test_users.py 108, types.py 220
- test_suite/ (5,981 lines): conftest.py 32; test_01_utilization_and_continuity_bases.py 191 (4 tests), test_02_billing_unit_arithmetic.py 148 (4), test_03_shift_axes_and_billing_cycle.py 199 (5), test_04_cascades_and_trim_waterfall.py 240 (6), test_05_validation_precedence.py 207 (6), test_06_boundary_precision.py 191 (6), test_07_cross_entity_state_dependency.py 221 (6), test_08_resource_temporal_overlap.py 174 (6), test_09_compensating_invariant.py 197 (6), test_10_reference_data_and_shape.py 621 (16), test_11_lifecycle_state_machines.py 662 (18), test_12_scoring_and_cadence_calculations.py 424 (9), test_13_gating_and_validation_rules.py 1057 (24), test_14_endpoint_contracts.py 296 (8), test_15_error_catalogue.py 245 (5), test_16_rbac_and_ownership.py 392 (10), test_17_layered_flows_and_consistency.py 484 (9)

Tests emitted: 148. pytest --collect-only collects all 148 with no import errors; python3 -m pyflakes test_suite test_helpers exits 0.

Coverage:
- Queue A (difficulty): 18/18 non-stub instances, 49 tests, every instance with >=2 tests. Per rule: dual_variant_calc 4, combinatorial_formula 4, non_linear_state_machine 5, transitive_cascade 6, priority_pair_validation_conflict 6, boundary_precision_check 6, cross_entity_state_dependency 6, resource_temporal_overlap 6, compensating_invariant 6.
- Queue B (corner): 53/53 non-stub instances, 99 tests. Per section: entities 16, state_machines 18, calculations 9, validations 24, endpoints 8, errors 5, rbac 10, complexity_layers 7, consistency_model 2.

A scripted audit confirms every test docstring ends with exactly one Design: line, no test is dual-tagged, every tag resolves to a real non-stub instance in the section/rule that owns it, and no tag points at a stub. Zero problems.

Skipped instances: only the 20 excluded_because: stubs, never translated by contract (state_machines 3, calculations 6, validations 7, endpoints 2, complexity_layers 2). Each points at a difficulty instance already covered in queue A. No instance was dropped on PRD-derivability grounds — the two-condition filter passed everywhere.

Three sub-claims inside otherwise-covered instances were omitted as non-assertable: "no pagination fields present" on a single-object read, the documentation claim that §1.5 declares no PATCH/PUT/DELETE route, and "a client-supplied id/version in the body is ignored" (unknown-field handling is unspecified in the PRD).

Judgement calls worth passing to the implementation side:
1. Correcting a BILL_ACCEPTED timesheet expects ERR_TIMESHEET_ALREADY_BILLED 409 — PRD §3.7's explicit sentence outranks a literal read of §2.8 priority 3, under which the documented BILL_REJECTED -> EDITED rework loop would be unreachable.
2. A second authorization against the same plan with a refreshed expected_plan_of_care_version must answer 201, not ERR_INVALID_STATE (PRD §2.6).
3. A continuity swap onto an already-ASSIGNED shift must exclude the target shift from its own patient-concurrency count, mirroring §3.5's explicit self-exclusion on the nurse ceiling.
4. One design/PRD contradiction resolved without weakening: the design recipe voids a CAPTURED timesheet, but PRD §3.7 admits a void only from SUBMITTED/BILL_ACCEPTED/BILL_REJECTED, so test_11 reaches VOIDED by the PRD-legal route (submit first) while keeping the instance's core claim intact.

Nested sub-agent report (corner calculations + validations, folded into the above counts): test_12 424 lines/9 tests and test_13 1057 lines/24 tests, ast.parse OK, covering all 5 non-stub calculations and all 13 non-stub validations instances. Design-index corrections applied with PRD winning: (a) two instances recorded visit_at 2026-08-04T06:00:00Z while the clock read 2026-08-03T06:00:00Z, which PRD 3.4 forbids — the clock is parked at the visit instant first (equality allowed) with all asserted outcomes preserved; (b) the renewal-gate instance asserted date-only week_start/week_end, but PRD 3.3 makes both instants and PRD 2.5 makes the week half-open, so the test asserts canonicalize_instant(C.WEEK32_START)/(C.WEEK32_END) = 2026-08-03T00:00:00Z / 2026-08-10T00:00:00Z; (c) the partial-grant instance asserts the dispute's status plus decided_hours_per_week/decided_at rather than an outcome response field the PRD never declares.

Hygiene: worklog.md, workspace/PRD.md, SCAFFOLD*.yaml and workspace/implementation/ were never written or read by the test generator. .scratch/step5/ removed; sibling empty .scratch/step5_corner_{b,c}/ left in place. No servers, no pytest runs against a live app, no pkill.

ORCHESTRATOR VERIFICATION: confirmed test_helpers/ (9 .py) and test_suite/ (18 .py incl. conftest) exist at the TASK ROOT with no stray copies under workspace/, and independently re-ran `pytest --collect-only -q` => "148 tests collected" with zero collection errors.

## Step 7: Run tests and iterate — 2026-09-05T23:59:42.376610016Z

Done. All 8 rounds green.

Iterations run: 2 sweeps (iteration 1 = baseline diagnosis; iteration 2 = verification after the single fix).

Iteration 1 result: 147/148 in all 8 rounds — one perfectly deterministic failure, no flakiness, no load-induced failures, no connection/timeout noise.

Tests deleted (1):
- test_the_refreshed_plan_version_lets_the_second_authorization_through in test_suite/test_17_layered_flows_and_consistency.py — STEP 1b failure, not uniquely derivable from PRD (the PRD contradicts itself on this point).
  - The test issued a first authorization against a SUBMITTED plan (which drives the plan SUBMITTED -> UNDER_REVIEW), then re-issued a second authorization against the same plan while it sat in UNDER_REVIEW with a refreshed version token, and asserted 201. The implementation returned ERR_INVALID_STATE 409.
  - PRD 2.6 (line 119) says: "Writing a second authorization against the same plan of care is a legitimate operation — it supersedes the earlier PENDING grant and drives the plan through UNDER_REVIEW again — so state alone cannot distinguish a deliberate re-issue from a reviewer whose view of the approval history is out of date."
  - PRD 3.3 (line 251) says the opposite for this scenario: "Issuing the authorization is only possible while the plan sits in SUBMITTED; it creates the authorization in PENDING ... moves the plan SUBMITTED -> UNDER_REVIEW, and increments the plan's version." PRD 2.8 check 9 reinforces a state gate on transition endpoints.
  - Both readings are articulable by a faithful PRD-only implementer: (A) no state gate, only the version guard — but then PRD never says what happens to the plan's status/version on the second write, so the outcome is under-specified; (B) the 3.3 gate holds and a legitimate second issuance happens only after RETURNED -> SUBMITTED, which still makes 2.6's "state alone cannot distinguish" true because a stale reviewer replaying an old token against the re-submitted plan is caught by the 412. Reading (B) is what the implementation does. Per the cardinal rule (two articulable implementations from the cited sentence -> DELETE), the test was removed rather than the implementation weakened — adding an issue-from-UNDER_REVIEW capability would have contradicted the verbatim 3.3 sentence and violated the "never add a capability that does not trace to verbatim PRD" rule.
  - Coverage is not lost: the sibling test in the same file (...stale_plan_of_care_version_is_refused...) still covers the 412 optimistic-concurrency guard, its precedence ahead of the state check, and the no-write guarantee, and it passes.

Fixes applied to test_helpers/: none — no shared fixture/factory/assertion bug surfaced (no setup-error clusters at all).

Fixes applied to test_suite/: only the deletion above. No assertion was weakened, no skip/xfail added, no error_id downgraded to an HTTP-status check.

Fixes applied to implementation/: none. The single failure was a test-side PRD-ambiguity issue; the implementation was faithful to PRD 3.3 and no code was touched.

Final sweep evidence (workspace/implementation/results.1..8.json, left in place): round 1: 147/147 · round 2: 147/147 · round 3: 147/147 · round 4: 147/147 · round 5: 147/147 · round 6: 147/147 · round 7: 147/147 · round 8: 147/147 — failed=0, errors=0, skipped=0 in every round.

Housekeeping: worklog.md, workspace/PRD.md, and all three SCAFFOLD*.yaml files untouched; sweep.sh unmodified; .scratch/step7/ removed (sibling step5_corner_b/step5_corner_c left intact); no name-based pkill used.

ORCHESTRATOR VERIFICATION: independently parsed all 8 workspace/implementation/results.$i.json — every round reports passed=147 failed=0 total=147 errors=0 skipped=0 (files all present, ~46.7 KB each, mtime 23:52, SWEEP_DONE 2026-09-05T23:52:58Z). `pytest --collect-only` now collects 147 tests, consistent with 148 minus the one deletion. Grepped every workspace/sweep.round.$i.log for "Terminated": absent in all 8, so the sweep was not reaped and the green result is trustworthy. PRD.md (22:52) and SCAFFOLD.yaml (22:38) retain pre-Step-7 mtimes.

Step 8 skip condition NOT met (1 deletion, 1 test_suite change), so Step 8 runs. Note for Step 8: the sole Step 7 finding is a genuine PRD self-contradiction between §2.6 and §3.3 on re-issuing an authorization against a plan already in UNDER_REVIEW; the implementation enforces the §3.3 state gate, so §2.6's wording is the side that must be reconciled to implementation.

## Step 8: Finalize PRD — 2026-09-06T00:08:23.38476260Z

Step 8 complete. workspace/PRD_FINALIZED.md written; only 3 lines differ from PRD.md.

Line counts: PRD.md 534 lines; PRD_FINALIZED.md 534 lines (0.0% line delta; 3 lines revised in place, no insertions/deletions/new sections). Tail verified not truncated: last 3 lines are the Section 5 error-catalogue rows ERR_DECIDED_HOURS_OUT_OF_RANGE | 422, ERR_NO_ELIGIBLE_NURSE | 422, ERR_PAYER_MISMATCH | 422 — byte-identical to PRD.md's tail, ending at the real end of the Section 5 table.

Changes (all trace to the single Step 7 item: §2.6 vs §3.3 contradiction on re-issuing an authorization):
- §2.6 para 1 (line 117) — revise — the blanket claim that both OCC-guarded writes "cannot be blocked on state alone" now reads that the version guard exists because parent state alone cannot identify a stale writer, and is "a supplement to the state gates of Section 3, not a replacement for them" — implementation/routes_plans.py:135-139, implementation/routes_shifts.py:156-165.
- §2.6 "Creating an authorization" (line 119) — revise — dropped the false sentence that a second authorization "supersedes the earlier PENDING grant and drives the plan through UNDER_REVIEW again"; replaced with the impl-true justification (a plan can be authorized more than once over its life, e.g. after return-and-resubmit it is SUBMITTED again), plus the OCC-before-state precedence (checks 8 then 9) and the list of events that bump PlanOfCare.version. The 412 / ERR_STALE_PLAN_OF_CARE_VERSION / "nothing is written" sentence is kept verbatim — implementation/routes_plans.py:134-139, 78-90, 93-111, 206-209.
- §3.3 (line 251) — insert — after the existing "only possible while the plan sits in SUBMITTED" sentence, added that a plan in any other status is refused ERR_INVALID_STATE (409), explicitly including a plan already UNDER_REVIEW from an earlier issuance and one already AUTHORIZED, that a current expected_plan_of_care_version does not open that door, and that a second grant therefore arrives either via a fresh issuance after the plan returns to SUBMITTED or via the §3.9 renewal endpoint — implementation/routes_plans.py:138-139, 274-311.

Per-edit pre-edit search log:
1. Edit 1 — subject: the framing of what the two OCC guards do and whether their operations carry state gates. (b) Enumerated/read: routes_plans.create_authorization (OCC at :135, state gate at :138), routes_shifts._guard_assignable (:156-165, shift staffing_status gate, started-shift gate, case-open/ACTIVE gates), the shift OCC callsites on manual assign and auto-staff (:179+), errors.py:21-23 (412/409 mapping), and grepped every ERR_INVALID_STATE site across implementation/*.py to confirm no OCC-guarded write is state-free. (c) Adjustment: rejected keeping "cannot be blocked on state alone" (false for both writes — each has a state gauntlet) and rejected any wording implying the guard replaces the state gate; settled on "supplement ... not a replacement", true of both the plan and the shift path.
2. Edit 2 — subject: what happens on a second authorization against the same plan, and what moves PlanOfCare.version. (b) Enumerated/read: every writer of a plan row — create_plan (:32), submit_plan (:78-90, allows DRAFT and RETURNED), return_plan (:93-111, RETURNED, revision_round+1, PENDING->EXPIRED), create_authorization (:157-158, plan->UNDER_REVIEW), activate_authorization (:206-209, plan->AUTHORIZED only when plan is UNDER_REVIEW), and renew_authorization (:274-311, creates a second authorization on the same plan, touches no plan row and takes no version field). Grepped db.plans across all modules to prove no other plan mutation exists (derive.py:85 is read-only; cascade.touch is never applied to plans outside routes_plans). (c) Adjustments: first draft said "activation increments the plan's version" — false for renewal-successor activations where the plan is already AUTHORIZED, so narrowed to "the activation that carries the plan to AUTHORIZED". Also deliberately did not claim renewal is version-guarded, and used the loose "can be authorized more than once over its life" with one example rather than an exhaustive list, so the renewal path is not excluded.
3. Edit 3 — subject: the plan-status gate on authorization issuance. (b) Enumerated/read: routes_plans.py:138-139 (single != "SUBMITTED" test, so DRAFT/UNDER_REVIEW/AUTHORIZED/RETURNED all 409), its position relative to the OCC check (:135) and the two cap checks (:140-143) — matching §2.8's 8 -> 9 -> 34 -> 35 order; renew_authorization (:287-294, gated on authorization status only, never on plan status) to confirm the "or from the renewal endpoint" clause; PRD.md:400 renewal prose for consistency; activate_authorization (:195-217) for the AUTHORIZED terminal claim. (c) Adjustment: wrote the refusal as "a plan in any other status" (universal over the enum) rather than naming only UNDER_REVIEW, and added the renewal escape hatch so the sentence cannot be read as "a plan may only ever hold one authorization".

Verification: the surviving sibling test test_replaying_the_pre_create_plan_version_is_refused_and_writes_nothing (412, precedence ahead of the state check, no-write guarantee) remains fully described by the edited §2.6 — the OCC guard's specification survives intact. Scratch dir .scratch/step8/ removed; sibling .scratch/step5_corner_b and step5_corner_c left untouched.

ORCHESTRATOR VERIFICATION: PRD_FINALIZED.md is NOT byte-identical to PRD.md (cmp differs). diff confirms exactly 3 changed lines — 117c117, 119c119, 251c251, i.e. 6 diff lines total, no insertions or deletions — matching the reported edit set. Both files are 534 lines and PRD_FINALIZED.md ends on the complete final §5 table row.

## Step 9: Complete PRD — 2026-09-06T00:36:27.237122768Z

ORCHESTRATOR DECISION: Step 9 was run as THREE sequential passes partitioned by implementation module, all editing one shared workspace/PRD_COMPLETED.md. Rationale: a single agent scanning 65 endpoints / 3,424 lines of implementation reliably under-scans, and the known failure signature is a PRD_COMPLETED.md byte-identical to its source. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from copying and were told which sections the earlier passes had already edited so they would append clauses rather than restructure paragraphs.

PASS 1 (app.py, timeutil.py, errors.py, envelope.py, store.py, auth.py, lookup.py, serialize.py, routes_reference.py — endpoints 1-15):
534 -> 538 lines, char delta +6,203, 16 diff hunks / 19 modified lines. 15 ambiguity-pins, 3 mismatch-revisions.
- §2.1 — revise — ambiguity — auth headers are trimmed, so a whitespace-only header counts as empty -> 401 — auth.py:27-29
- §2.1 — revise — MISMATCH — PayerReviewer scope resolution rewritten: authorization directly / via dispute / via timesheet->assignment->shift->case->authorization, body payer_id on authorization creation, and plan-of-care return scoped via the plan's patient's payer OR any authorization of that plan (PRD had claimed plan-of-care scope ran through the timesheet); unresolvable chain => check is vacuous — auth.py:41-61, routes_plans.py:97,123
- §2.1 — revise — ambiguity — Nurse ownership: no ACTIVE assignment (or unresolvable timesheet assignment) skips the comparison; latest-created ACTIVE assignment is authoritative — auth.py:64-87
- §2.2 — revise — ambiguity — api_request_id is req_ + exactly 20 uppercase-alphanumeric chars — envelope.py:19
- §2.2 — revise — ambiguity — pagination meta fields absent from single-resource responses — envelope.py:25-27
- §2.3 — revise — ambiguity — non-integer limit/offset => 400; empty-string value treated as omitted — validate.py:231-250
- §2.3 — revise — ambiguity — created_at ties broken by server insertion order, never by identifier — store.py:75-77
- §2.3 — revise — ambiguity — total_count = post-filter/pre-page count; has_more = offset + len(page) < total_count; over-large offset => empty page, has_more false — envelope.py:30-36
- §2.4 — revise — ambiguity — every named field is always present, empty => JSON null not omitted; internal sequence key never exposed — serialize.py:1-232, store.py:53
- §2.5 — revise — ambiguity — clock response data carries exactly one field current_utc in canonical form — routes_reference.py:31-37
- §2.5 — insert — ambiguity — input parsing leniency (1-9 fractional digits or none, "," decimal, space for T, omitted seconds, Z or +/-HH:MM normalised, bare date => midnight UTC; date fields accept a full instant) vs strictly canonical output — timeutil.py:11-91
- §2.7 — insert — ambiguity — four envelope-level failures outside the §5 catalogue: unknown path => ERR_NOT_FOUND 404, wrong method => ERR_INVALID_REQUEST 405, unparseable => ERR_INVALID_REQUEST 400, fault => ERR_INTERNAL 500; trailing slash insignificant — app.py:28,55-73
- §2.8 check 9 — revise — ambiguity — competency revocation tests already-REVOKED before reading the body, so 409 wins over a missing revoked_reason — routes_reference.py:214-218
- §3.1 — revise — ambiguity — nurse list: skill filter matches verified_skills, filters combinable, illegal enum value => 400 — routes_reference.py:135-148
- §3.1 — revise — ambiguity — nurse-status write has no state gate; repeating the current status still bumps updated_at/version and cascades nothing — routes_reference.py:151-162
- §3.1 — revise — ambiguity — patient list: unknown payer_id filter => empty page (not 404), illegal status => 400, and a PayerReviewer's list is not payer-scoped — routes_reference.py:277-290
- §3.2 — revise — ambiguity — revoked_reason mandatory and non-blank; VALID or EXPIRED may be revoked, only REVOKED refuses; competency list resolves the path nurse first (404) — routes_reference.py:197-223
- §3.6 — revise — ambiguity — case_id is a mandatory query param (nurse 404 first, then 400 if absent, then 404 on unknown case); illegal basis => 400; the read returns exactly those five fields — routes_reference.py:229-245
- §3.9 — revise — ambiguity — checkpoint cancels stale shifts with cancel_reason SCHEDULER (start_at strictly before the clock), runs its four passes in a pinned order over created_at-ordered tables, the supervisory pass mutates nothing, and data carries exactly the four counts — routes_reference.py:43-72
- §4 — revise — MISMATCH — GET /pdn/timesheets/{id} no longer claims a "worked minutes" field (serialize exposes clock instants + unit figures only) — serialize.py:163-180
- §4 — insert — ambiguity — unauthenticated GET /healthz outside /pdn returns bare {"status": "ok"}, no envelope — app.py:75-77
Verified no-change areas: the §5 catalogue matches errors.py exactly (49 IDs, identical statuses, identical order); every field name emitted by serialize.py already appears in the PRD.

PASS 2 (validate.py, cascade.py, routes_plans.py — endpoints 16-33):
538 -> 538 lines (all in-paragraph), 105,404 -> 111,945 chars (+6,541). 13 ambiguity-pins, 3 mismatch-revisions.
- §2.8 check 7 — insert — ambiguity — pinned the accepted-input-form contract: JSON null counts as absent (required -> "missing", optional -> default); integer fields accept int / integral float / signed digit-string and reject fractions, booleans and other strings; hour fields accept any JSON number or numeric string; booleans accept true/false or the strings in any case; required strings must be non-blank after trimming while optional ones may be empty; strings stored untrimmed except ordering_physician_npi; empty query params = omitted; absent/unparseable body = empty object, non-object body = 400 — validate.py:27-228
- §2.8 check 7 — revise — MISMATCH — the blanket "numbers strictly positive" wrongly covered version fields; now exempts expected_plan_of_care_version / expected_shift_version, which accept any integer (incl. 0 and negatives) and are settled by check 8 — validate.py:88-96, routes_plans.py:134-137
- §2.4 recomputation paragraph — insert — ambiguity — the derived-signature reconciliation is settled once just before the response, against a pre-mutation snapshot, and reaches exactly Nurse, Authorization, Case (with their field lists); no other row bumps for a derived change; an already-mutated row bumps only once per request; reads never bump — cascade.py:22-94
- §2.10 — insert — MISMATCH — the enumeration stopped at six cascades; added the seventh (nurse leaving ACTIVE releases not-yet-started assignments and reopens shifts rather than cancelling them) — cascade.py:192-202
- §3.3 plan list — insert — ambiguity — unknown patient_id yields an empty page, bad status is 400 — routes_plans.py:62-75
- §3.3 submission — revise — MISMATCH — PRD said "only while the plan is still DRAFT"; impl accepts DRAFT or RETURNED on the same endpoint, and applies the discharged-patient bar ONLY to a DRAFT submission, so a RETURNED resubmission proceeds for a discharged child — routes_plans.py:82-87
- §3.3 issuance — revise — MISMATCH — "The payer_id ... must be the payer that the plan's patient is enrolled under" is not enforced at issuance; reworded to note scope compares only against the acting reviewer and ERR_PAYER_MISMATCH at case opening is the real enforcement — routes_plans.py:118-143
- §3.3 issuance — insert — ambiguity — supersedes_authorization_id, when supplied, must resolve (404); payer_id is read and scope-checked before any other identifier; resolution order is plan_of_care_id, payer_id, supersedes_authorization_id — routes_plans.py:122-128
- §3.3 activation — insert — ambiguity — the plan hop is conditional on the plan sitting in UNDER_REVIEW; otherwise the plan is untouched, its version does not move, and activation still succeeds — routes_plans.py:206-209
- §3.3 authorization list — insert — ambiguity — identifier filters are exact-match / empty page; bad status is 400 — routes_plans.py:168-187
- §3.3 utilization read — insert — ambiguity — bad basis or unparseable week_of is 400, empty counts as omitted, and the read is not payer-scoped — routes_plans.py:220-229
- §3.9 reduction notice — insert — ambiguity — the noticed < approved bound is check 7 (400) and precedes the ACTIVE gate (409); a missing payer row falls back to ten notice days — routes_plans.py:238-247
- §3.9 dispute filing — insert — ambiguity — the per-type entry conditions are tested last (after the window and already-open checks) and fail with ERR_INVALID_STATE (409), including the granted-in-full case — routes_plans.py:345-362
- §3.9 dispute decision — insert — ambiguity — a decided_hours_per_week sent with UPHELD/OVERTURNED is validated then discarded; review and decide both answer with the dispute row, not the authorization — routes_plans.py:426-448, :473
- §3.9 apply reduction — insert — ambiguity — the open-dispute bar is tested after the effective-instant check and refused with ERR_INVALID_STATE (409) — routes_plans.py:258-264
- §3.9 trim cascade — insert — ambiguity — the target minutes figure is truncated to a whole minute — cascade.py:141
- §3.9 renewal — insert — ambiguity — effective_end must be strictly after the inherited effective_start (400, check 7); renewal only from ACTIVE or REDUCED (409); the utilization-gate denominator is the incumbent's current approved_hours_per_week, not the requested successor figure — routes_plans.py:284-295, derive.py:207-215
- §3.9 handover — insert — ambiguity — a predecessor outside ACTIVE/REDUCED refuses activation with ERR_INVALID_STATE (409); an unresolvable supersedes_authorization_id skips the handover and activation still succeeds; cases are repointed in created_at order — routes_plans.py:199-216
Pass 2 confirmed by grep that all 19 distinctive pass-1 / Step-8 phrases survive intact — no pass 1 edit reverted or reworded.

PASS 3 (derive.py, routes_cases.py, routes_shifts.py — endpoints 34-65):
538 -> 538 lines, 111,945 -> 118,149 chars (+6,204). 24 edits on 23 lines — 20 ambiguity-pins, 4 mismatch-revisions.
- §2.8 check 9 — insert — MISMATCH — appended a second local inversion: on timesheet correction/submit/billing-decision the already-billed test (check 39) runs BEFORE this check, so BILL_ACCEPTED/VOIDED reports ERR_TIMESHEET_ALREADY_BILLED, never ERR_INVALID_STATE — routes_shifts.py:475, 494, 518
- §2.8 check 11 — revise — MISMATCH — six->seven operations: resuming a case also carries the staffable-authorization check, evaluated out of numeric order last (after 12 and 13) — routes_cases.py:140
- §2.9 — revise — ambiguity — hours->minutes cap products are truncated toward zero, not rounded — routes_shifts.py:173
- §3.3 — insert — ambiguity — all utilization fields are populated under either basis; basis selects only which minutes feed utilization_ratio/hours_remaining — derive.py:171-193
- §3.4 — insert — ambiguity — continuity_nurse_id must resolve (404); excluded_nurse_ids members are never resolved — routes_cases.py:38-43
- §3.4 — insert — ambiguity — case-list identifier filters match nothing rather than 404; illegal status is 400 — routes_cases.py:73-88
- §3.4 — revise — ambiguity — latest-visit residual created_at tie broken by insertion order (last created wins) — derive.py:276
- §3.4 — insert — ambiguity — recording a supervisory visit has no case-state gate at all — routes_cases.py:171-197
- §3.4 — insert — ambiguity — closing clears hold_reason but leaves hold_incident_report_id intact — routes_cases.py:161-163
- §3.5 — insert — ambiguity — the continuity swap is gated on the staffing axis only; evv_status need not be NOT_STARTED — routes_shifts.py:156-165
- §3.5 — insert — ambiguity — match_score_at_assignment is evaluated before the incumbent is released — routes_shifts.py:136-139
- §3.6 — insert — ambiguity — availability points read the CURRENT clock's week, not the shift's week — derive.py:388
- §3.6 — insert — ambiguity — the selector's weekly-ceiling test does NOT exclude the target shift's own minutes (unlike §3.5), and the eligibility list is exhaustive: concurrent_nurse_limit is never consulted by the selector — derive.py:450-452, routes_shifts.py:179-196
- §3.6 — insert — ambiguity — residual created_at tie in the candidate ordering broken by insertion order — derive.py:472
- §3.6 — insert — ambiguity — candidates read: top_match_score is the first-ranked score; empty pool gives 0/[]/null/0 and is not an error; no state gates apply — routes_shifts.py:117-131
- §3.6 — insert — ambiguity — a third and later escalation re-affirms TIER3_PAYER_NOTIFICATION, still bumping version — routes_shifts.py:225
- §3.7 — insert — ambiguity — at capture the three unit figures are 0 and edit_codes already carries MANUAL_ENTRY for a MANUAL method — routes_shifts.py:290, derive.py:490-494
- §3.7 — insert — ambiguity — the verification axis is settled before the money is computed, so step three reads the freshly written evv_status — routes_shifts.py:318-323
- §3.7 — insert — ambiguity — the ruleset payer is reached through the patient's payer_id, not the authorization's, and an unresolvable payer means no strict surcharge — derive.py:543-548
- §3.7 step one — revise — MISMATCH — dropped "must be greater than zero" (no such gate exists): partial minutes discarded, capped figure floored at 0, a non-positive interval accepted as zero units — derive.py:497-500
- §3.7 step three — insert — ambiguity — an exact whole product is not pushed one unit higher; gross 0 gives deduction 0 — derive.py:516
- §3.7 correction — insert — ambiguity — null clock_out_at is ERR_INVALID_REQUEST (400) ahead of both later tests; edit_codes is rebuilt (so LATE_START can vanish); the verification outcome is never re-evaluated — routes_shifts.py:472-484
- §3.8 — insert — ambiguity — the case hop is conditional on the case being ACTIVE; a PENDING_STAFFING/ON_HOLD case is untouched while the patient still becomes HOSPITALIZED and triggered_case_hold stays true — routes_cases.py:241-250
- §3.8 — insert — MISMATCH — pinned the resume gate order: report closure, patient status, segregation, authorization last — routes_cases.py:127-142
Pass 3 diffed against PRD_FINALIZED.md: 62 differing lines of which exactly its 23 are new; every pass 1 / pass 2 / Step 8 line still present and unmodified. Its two edits inside earlier-pass paragraphs (§2.8 check 9, §3.3) are pure appends.

AGGREGATE: PRD.md 534 lines / 98,111 chars -> PRD_FINALIZED.md 534 / 99,174 -> PRD_COMPLETED.md 538 / 118,149. Total Step 9 growth +18,975 chars over PRD_FINALIZED.md across 65 edits (48 ambiguity-pins, 10 mismatch-revisions in the passes' own tallies, plus pass-1's 3 counted separately).

ORCHESTRATOR VERIFICATION: PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (cmp differs; 120 diff lines), so all three scans genuinely ran. Structural integrity intact: all 5 top-level headings present (§1 line 3, §2 line 11, §3 line 229, §4 line 412, §5 line 484), §4 still holds exactly 65 endpoint rows, §5 still holds exactly 49 ERR_ rows, and the file ends on the complete final row "| `ERR_PAYER_MISMATCH` | 422 |" — no truncation. No difficulty-directive leak. Confirmed via `find ... -newer workspace/SWEEP_DONE` that nothing under implementation/, test_suite/ or test_helpers/ was modified after the green 8-round sweep, so the 147/147 x 8 result remains valid for the shipped artifacts; results.1..8.json are left in place.

PIPELINE COMPLETE. Final deliverables: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 modules), test_suite/ (17 test files, 147 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, workspace/implementation/ (3,424 lines, 65 endpoints, results.1..8.json all 147/147).
