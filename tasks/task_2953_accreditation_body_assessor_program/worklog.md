# Worklog — task_2953_accreditation_body_assessor_program

## Step 1: Create task directory — 2026-09-05T21:25:40.159949195Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2953_accreditation_body_assessor_program and workspace/ (pre-assigned path; no index scan performed per orchestrator instruction).

## Step 2: Generate scaffold — 2026-09-05T23:00:26.131219572Z

All three scaffold artifacts are complete and lint-clean.

Lint verdict (verbatim, final run):

    SCAFFOLD §1.8/§1.9 -> §1.5 lint report
    ============================================================
      SCAFFOLD:           tasks/task_2953_accreditation_body_assessor_program/SCAFFOLD.yaml
      Difficulty design:  tasks/task_2953_accreditation_body_assessor_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
      Corner design:      tasks/task_2953_accreditation_body_assessor_program/SCAFFOLD_CORNER_DESIGN.yaml

    Coverage
      §1.5 endpoints declared:    60
      §1.1 entities declared:     13
      §1.8 instances scanned:     18
      §1.9 instances scanned:     49
      Calls scanned (§1.8+§1.9):  1093

    VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Deliverables (all under tasks/task_2953_accreditation_body_assessor_program/):
- SCAFFOLD.yaml — 3017 lines, 165115 bytes
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2005 lines, 145956 bytes
- SCAFFOLD_CORNER_DESIGN.yaml — 3781 lines, 253712 bytes

SCAFFOLD.yaml top-level keys are exactly scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — neither design key leaked into it; each design file has exactly its one top-level key.

§1.0–§1.7 counts: domain_name: accreditation-body-assessor-program, api_prefix: /accreditation. 13 entities, 12 state machines, 2 concurrency rules, 9 calculations, 40 validations, 60 endpoints (34 writes + 26 reads), 51 errors, 7 roles. Profile: compliance_audit / multi_party_negotiation, graph topology, cyclic state machines, segregation_of_duties role model, immediate consistency, layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

§1.8 rule ids × instances (18 total, 2 each): dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

§1.9 sections × instances (61 total; 49 full recipes + 12 excluded_because stubs): entities 12, state_machines 9, calculations 6, validations 7, endpoints 5, errors 10, rbac 5, cross_cutting_complexity_layers 5, consistency_model 2. All 79 instance names are unique across both design files, and every stub's cited difficulty_instance resolves to a real §1.8 instance name.

Audit fixes made to SCAFFOLD.yaml during the §1.9 pass:
- ERR_PLAN_NOT_APPROVED was untriggerable — every reachable path was shadowed by priority 8/9. Widened the rule (and its applies_to) to also guard POST /accreditation/assessment-plans/{plan_id}/witness-sessions, which makes it reachable by booking under a superseded CANCELLED plan while a sibling plan is APPROVED. That is now §1.9 endpoints/scheduling_a_session_under_a_superseded_draft_plan_rejected.
- ERR_BLOCKING_NONCONFORMITY_OPEN contradicted the state machine — close-assessment is explicitly declared to branch IN_ASSESSMENT → NC_OPEN when nc_blocking_open_count >= 1, so the rule could never fire (a second attempt is caught by priority 9). Removed the validation row and its error-catalog entry (errors 52 → 51, validations 41 → 40); the branch itself is asserted by the §1.8 instance close_assessment_with_only_observation_findings_treats_blocking_set_as_empty.
- All 51 remaining error ids are now referenced by at least one §1.8/§1.9 instance (verified mechanically; zero uncovered).

ORCHESTRATOR ACTION TAKEN: the subagent flagged that SCAFFOLD.yaml's scenario: block still began with the literal line "Generate task harder than expert level!". Per the known leak path (scenario → PRD.md), the orchestrator stripped that line (and its blank separator) from SCAFFOLD.yaml before Step 3/4; SCAFFOLD.yaml is now 3015 lines and re-parses as valid YAML with the same 13 top-level keys. grep for "harder than expert" across all three scaffold files now returns 0 hits.

## Step 3: Copy shared files — 2026-09-05T23:00:26.147198830Z

Copied ./INSTRUCTION.md to tasks/task_2953_accreditation_body_assessor_program/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T23:16:31.858Z

PRD.md is finished at 505 lines / 104,843 bytes, ending at a real section boundary (the final `ERR_MRA_ESCALATION_NOT_ELIGIBLE | 422` row of §5, followed by a single trailing newline — no mid-sentence truncation).

Deliverable: workspace/PRD.md

Section list:
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 Actors/Identity Headers/RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Audit Fields and the Logical Clock · 2.5 Rule-Revision Pinning · 2.6 Optimistic Concurrency on Cycles and Findings · 2.7 Precision, Rounding and Arithmetic Conventions · 2.8 Cascade Discipline and Hierarchical Consistency · 2.9 Path Resolution Order and Validation Precedence (13-rank normative list) · 2.10 The Independence Doctrine
- §3 Business Logic & Workflows — 3.1 Scheme Rule Development · 3.2 Recruiting Assessors and Competence · 3.3 Impartiality Disclosure/Screening/Conflict Verdict · 3.4 Organizations, Opening a Cycle, Conflict-Free Team · 3.5 Planning: Effort and Fee · 3.6 Witnessing and Closing the Assessment · 3.7 Findings, Corrective Action, Effectiveness, Escalation · 3.8 The Independent Decision Panel · 3.9 Scopes, Surveillance Cadence, Reassessment · 3.10 Complaints, Appeals, Mutual Recognition
- §4 Endpoint Definitions (intro + 60-row table)
- §5 Error Code Catalogue (intro + 51-row table)

Mechanical coverage: entity fields 141/141; request_body identifiers 74/74; query_params 28/28; path_params 13/13; endpoint paths in §4 60/60; error ids in §5 51/51; error ids also in §1–§4 narrative 51/51; validation error ids in narrative 40/40; state values (all 12 machines) 45/45; enum values 97/97; roles 7/7; entities substantively covered 13/13; calculations 9/9 with all 48 constants present; validations with an unreferenced field identifier 0/40.

Hard Contract results:
- Contract 1 (Field-Name Coverage): PASS. All 234 required identifiers (141 entity fields + 93 endpoint request/query/path identifiers) appear verbatim in backticks. A wider sweep of every snake_case token in SCAFFOLD.yaml left 65 absent, all of which are scaffold metadata keys (complexity_profile, entity_topology, occ_field, test_recipe, …), calculation names, or intra-formula intermediates (raw_points, recency_factor, prior_cycle_raw) that the skill forbids projecting as pseudocode variables. No persisted field or wire identifier is missing.
- Contract 2 (Rule Coverage): PASS. All 65 transitions across the 12 machines, both OCC rules, all 9 calculations with every constant, all 40 validations paired to their error ids, all cross-entity cascades (the 5-hop escalation, the 3-hop scope suspension, the 2-hop assessor suspension, the ledger-restore compensations), all field-level defaults, and sibling-branch symmetry (ACCEPT/REJECT, PASS/FAIL, UPHELD/DISMISSED, GRANT/REFUSE/DEFER, suspend/restore/withdraw) are stated in prose.
- Contract 3 (§3 Path Purity): PASS. 1,169 backticked tokens in §3 (328 unique): zero contain `/`, zero are bare HTTP methods, zero are method+path pairs.

Also verified: no fuzzy quantifiers (the 4 hits for "about" are all ordinary English), no pseudocode (the only 2 fenced blocks are the verbatim §2.2 JSON envelopes), and no Hard-Contract/scaffold/test-recipe metadata leaked into the document.

One repair made during verification: the four fee day rates were originally rendered with digit-group spaces ("145 000 cents"), which is ambiguous for an implementer. They are now plain backticked integers `145000`, `96500`, `132500`, `87500`. No other number in the document uses digit grouping.

Intentional interpretations (scaffold self-inconsistencies resolved) — six places where a loose endpoints[].side_effects summary contradicted the more detailed state-machine/entity-field definitions; in each the generator followed the transition table plus the field descriptions:
1. ImpartialityDeclaration → RESTRICTED on filing: written as STRUCTURAL-only with a null ended_on (the endpoint blurb also said SERVICE). An ongoing SERVICE relationship still yields a BLOCKED conflict verdict, so the model stays coherent.
2. conflict_verdict / conflict_checked_at: computed at proposal purely to enforce the gate, persisted only at confirmation (per the entity fields' "null while PROPOSED" and the PROPOSED→CONFIRMED transition).
3. ApplicantOrganization APPLIED → UNDER_ASSESSMENT: happens as cascade hop 2 of the first CONFIRMED LEAD_ASSESSOR, not at cycle creation.
4. rule_revision increment: at publication when published_at was already non-null (first publication leaves it at 1), not on PUBLISHED → UNDER_REVIEW.
5. Panel independence: written as the superset "no team assignment of any status", explicitly including RECUSED and REJECTED.
6. The return-to-draft precondition "no WitnessSession under this plan is COMPLETED" has no dedicated error id; mapped to ERR_INVALID_STATE_TRANSITION, whose applies_to includes that endpoint.

No scaffold content was intentionally omitted. Scratch artifacts remain in .scratch/step4/ (required.json, tables.md); nothing outside that subdir was created or deleted, and worklog.md was not touched.

ORCHESTRATOR VERIFICATION: independently confirmed PRD.md is 505 lines, tail ends on the completed §5 error table (real section boundary, not mid-sentence), section headers are §1–§5 as reported, and grep for "harder than expert"/"test_recipe"/"scaffold" in PRD.md returns 0 hits. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-06T00:27:05.264830436Z

Step 5 is complete. (Steps 5 and 6 were launched concurrently in a single assistant message per the skill; this entry is written first to keep the worklog in step order.)

Files written. Both trees are at the task root; workspace/ contains only INSTRUCTION.md, PRD.md, implementation, sweep.sh — no test_helpers or test_suite.

test_helpers/ — 2708 lines total
- __init__.py 16, api_client.py 433, api_errors.py 158, assertions.py 361, constants.py 297, factories.py 384, fixtures.py 924, test_users.py 111, types.py 24

test_suite/ — 4369 lines total, 65 tests
- conftest.py 17
- test_01_scheme_registry_and_rule_revisions.py 279
- test_02_assessor_competence_and_points.py 333
- test_03_impartiality_and_cycle_opening.py 467
- test_04_team_assembly_and_conflict_gates.py 316
- test_05_assessment_planning_effort_and_fees.py 395
- test_06_witness_scheduling_and_capacity_ledger.py 617
- test_07_findings_and_corrective_action.py 505
- test_08_effectiveness_closure_and_escalation.py 366
- test_09_decision_panel_scope_and_case_handling.py 566
- test_10_platform_envelope_and_authorization.py 508

All files python3 -m py_compile clean (COMPILE_OK); __pycache__ removed.

Coverage:
- Queue A (Difficulty, §1.8): 17 / 18 live instances translated, 0 stubs.
- Queue B (Corner, §1.9): 48 / 49 live instances translated. The yaml holds 61 Corner entries; 12 carry excluded_because.difficulty_instance (they are deduplication stubs pointing at a queue-A instance already translated, e.g. Corner/validations/segregation_rule_outranks_the_effectiveness_evidence_floor -> the queue-A pair covered in test_08), so 49 are live. Earlier arithmetic that showed "stubs 0" was a bad marker key in the dumper (is_stub); the real marker is excluded_because / absent test_recipe.
- Audit: tests=65 problems=0 — every test carries exactly one Design: line, every tag resolves to a live (non-stub) instance, no duplicate tags, no untagged or dual-tagged tests, every quoted docstring citation >=20 chars survives a whitespace-normalized literal match against workspace/PRD.md, and no docstring mentions "scaffold".

Skipped instances (2, both failed filter condition 2 — the PRD does not uniquely derive the asserted outcome):
1. Difficulty/cross_entity_state_dependency/plan_creation_requires_the_pinned_scheme_revision_to_still_be_current — asserts 422 ERR_SCHEME_VERSION_SUPERSEDED on plan creation, but PRD §2.5 states plan approval and decision finalization "are the only two operations that compare the two numbers," so a compliant server returns 201 on creation.
2. Corner/state_machines/raise_nonconformity_before_the_assessment_starts_rejected — asserts 409 ERR_APPLICATION_STATE_INVALID for a finding raised against a TEAM_ASSIGNED cycle, but the PRD never enumerates which cycle statuses admit findings, so 201 is equally compliant.

Both were left as gaps: no weakened assertion, no skip/xfail marker, no placeholder test.

Scratch (.scratch/step5) removed; sibling .scratch/orchestrator and .scratch/step4 untouched. worklog.md and workspace/implementation/ were never read or modified.

## Step 6: Generate implementation — 2026-09-06T00:27:05.277458747Z

Step 6 complete. The implementation is in workspace/implementation/.

Modules (3142 lines total, all py_compile clean):
- app.py 57 — app factory, blueprint registration, per-request g.touched reset, ApiError/HTTPException/Exception handlers (404 ERR_NOT_FOUND, 405 ERR_METHOD_NOT_ALLOWED, 400 ERR_INVALID_REQUEST, 500 ERR_INTERNAL)
- store.py 156 — in-memory dict store, _seq ordering, logical clock, version-bump discipline (touch/set_fields, one bump per record per request)
- envelope.py 99 — §2.2 envelope: req_ + 20 alnum id, ISO-8601 UTC ms timestamp, object/array/error shapes, pagination meta
- errors.py 88 — all 51 error ids with their canonical HTTP statuses
- validators.py 184 — shape/type/range/enum/date/instant helpers, pagination parsing
- auth.py 84 — X-User-ID/X-User-Role, whitespace-only -> ERR_UNAUTHENTICATED, 7 roles, ownership predicates
- calc.py 311 — all 9 calculations (Decimal + ROUND_HALF_UP), qualification points, effort/fees, day counts, risk scores, panel outcome, surveillance schedule
- domain.py 321 — cross-aggregate cascades: rule-revision pinning, witness-day ledger, scope suspension -> org -> cycle freeze, decision-record creation, risk recomputation
- routes/__init__.py 23 — blueprint registry
- routes/read.py 198 — 26 GET list/detail endpoints with filters + pagination
- routes/schemes.py 104 — scheme lifecycle + rule revisions
- routes/assessors.py 244 — assessors, qualifications, evidence verification, screening, declarations
- routes/applications.py 239 — organizations, cycles, team assignments, confirm/recuse
- routes/planning.py 325 — plans, approve/return-to-draft, witness sessions, outcomes, close-assessment
- routes/findings.py 247 — nonconformities, responses, review, effectiveness, escalate, reopen
- routes/decisions.py 278 — panel votes, finalize, scope status, follow-on cycles
- routes/complaints.py 155 — complaints/appeals, reviewer assignment, resolution, MRA escalation
- routes/clock.py 19 — POST /_clock/set_current_utc
- start.sh 9 — exec python3 app.py, reads $PORT, binds 0.0.0.0, foreground
- requirements.txt 1 — flask>=2.3.0

Endpoint coverage: mechanically diffed app.url_map against the PRD §4 tables: 60 PRD endpoints, 0 missing, 0 extra (59 domain endpoints + the /_clock/set_current_utc hook).

Smoke results (69 checks, all passing). Two urllib suites, each against a freshly booted server on a self-chosen high port, PID killed individually afterwards (all three ports confirmed down; no broad pkill).
- Suite 1 (35 checks) — grant path end to end: 401/403/400 rejections, scheme publish, qualification 100 points, plan effort + 3*145000 + 132500 fee, OCC 412, session day counts, close-assessment -> DECISION_PENDING, panel independence 422, quorum 422, SoD 422, GRANT finalize, scope schedule (365 / 2027-08-01 / 2030-07-31), org ACCREDITED, pagination meta + ERR_INVALID_PAGINATION, clock set, surveillance cycle, duplicate-active 409, and the full suspend -> org cascade -> cycle freeze -> restore -> withdraw chain.
- Suite 2 (34 checks) — findings and appeals: non-team author 422, pinned 60-day due date, observation with no deadline, ledger split, NC_OPEN routing, ERR_NOT_RESOURCE_OWNER, stale-version 412, reject/resubmit round counting, reviewer-cannot-verify SoD, evidence-count 422, closure -> DECISION_PENDING, reopen with round deferral, ERR_NOT_YET_OVERDUE, ERR_RESPONSE_WINDOW_CLOSED, escalation risk lift, refusal majority, appeal-reviewer conflicts, upheld appeal reopening a REFUSED cycle, MRA ineligibility.

Envelope conformance is asserted structurally, not by eye: exact meta key sets per response type, req_+20 alnum ids, 24-char millisecond timestamps.

Two smoke-script bugs surfaced and were fixed in the script, not the implementation — one expected CLEAR where PRD prose specifies CLEARED, and one attempted an overdue response while the finding sat in RESPONSE_SUBMITTED, where §2.9 rank 8 (target's own status) correctly masks the rank-12 window check. The masking behaviour is now itself an assertion.

Fresh-boot verification: all eight collection endpoints return total_count = 0 on a new process, and no .db/.sqlite/.json/dump artifacts exist in the implementation dir — storage is dicts only, with zero seeding. .scratch/step6 removed; step4 and step5 left untouched. worklog.md, test_suite/ and test_helpers/ were never read or written.

ORCHESTRATOR NOTE: Steps 5 and 6 ran concurrently (single message, two Agent calls), giving the implementation generator physical isolation from test_suite/ — that directory did not exist when it started. Step 6 finished first; its verbatim summary was stashed to .scratch/orchestrator/step6_summary.md and inlined here so the worklog reads in step order.

## Step 7: Run tests and iterate — 2026-09-06T00:43:39.968360043Z

Drove to a clean 8-round sweep.

## Iterations run
2. Iteration 1: 62/65 in every round (3 deterministic failures, identical across all 8). Iteration 2: 65/65 in every round.

## Tests deleted
None. All three failures survived STEP 1a/1b — each asserted a rule stated verbatim in PRD.md and uniquely derivable from it. Two were test-artifact bugs; one was a real implementation bug.

## Fixes applied to test_suite/
- test_01_scheme_registry_and_rule_revisions.py — test_withdrawn_scheme_rejects_every_further_status_change: the second probe sent `to_status: DRAFT` with no `revision_note`. Because §3.1 makes `revision_note` mandatory for a DRAFT target, rank-3 shape validation (ERR_INVALID_REQUEST) legitimately masks the rank-8 rule the test quotes — and rank 3 must precede rank 8, since a shape check that consulted the resource's current status would invert §2.9's own precedence. Supplied the note so the request violates only the state-transition rule. Assertion unchanged (ERR_INVALID_STATE_TRANSITION, 409).
- test_06_witness_scheduling_and_capacity_ledger.py — test_shared_site_buffer_rejects_a_fourteen_day_gap_across_organizations: the same_applicant exemption probe was booked at 2026-09-12, exactly 14 days from the org2 session created immediately before it. That trips the §3.6 buffer under both the literal signed reading and an absolute-value reading, so the probe could never isolate the exemption. Moved it ahead of the org2 bookings and to 2026-09-10, where the only session at the venue is its own organization's. Re-verified the surrounding arithmetic still holds: the 09-25 probe still rejects at a 14-day gap, and the 09-26 probe still clears at 15 and 16 days.

## Fixes applied to implementation/
- domain.py — added recompute_risk_at_surveillance_planning(), mirroring the existing recompute_risk_at_decision(): writes the score onto the organization and bumps its version per §2.8.
- routes/decisions.py — open_follow_on_cycle() now routes through that helper. It previously computed the at-surveillance-planning figure and wrote it only to scope.surveillance_risk_score, leaving organization.risk_score stranded at its at-decision value (12 instead of 6). §3.7 names "when a surveillance, reassessment or unannounced cycle is opened against a scope" as one of the four moments the organization risk score is recomputed, and §3.9 says the request "recomputes the organization's risk under the at-surveillance-planning variant" — under the alternative reading §3.7's fourth moment would be vacuous. Confirmed the only other test opening a follow-on cycle asserts nothing about org risk or version, so the fix is non-regressive.

## Fixes applied to test_helpers/
None — no fixture, factory, or role-header bug surfaced. Notably, none of the known recurring fixture traps applied here (money already sent as integers, instants at full ISO precision, blank headers using "" rather than whitespace, no envelope double-unwrap).

## Final sweep evidence
Round 1..8: 65/65 each. failed=0, errors=0, skipped=0 in all eight results.$i.json. No @skip/@xfail added, no assertion weakened, no PRD-required implementation check removed. Scratch dir .scratch/step7 removed; sibling .scratch/orchestrator and .scratch/step4 untouched; worklog.md not read or written.

ORCHESTRATOR VERIFICATION: independently confirmed the clean sweep is genuine rather than a claimed one. All 8 workspace/implementation/results.$i.json exist with passed=65 total=65 failed=0 errors=0 skipped=0; their mtimes are 00:37:40, i.e. AFTER the last fix (routes/decisions.py at 00:35:28, domain.py at 00:35:23, test_06 at 00:35:03, test_01 at 00:34:44), so the sweep exercised the fixed code. test_suite/ contains 65 `def test_` functions and grep for pytest.mark.skip/xfail returns 0 hits. Step 8 will run: Step 7 applied 2 implementation fixes and 2 test_suite fixes, so the skip condition (zero fixes) does not hold.

## Step 8: Finalize PRD — 2026-09-06T00:52:43.433439937Z

Done. PRD_FINALIZED.md is a two-sentence-level patch of PRD.md.

Line counts:
- PRD.md: 505 lines / 104,843 bytes
- PRD_FINALIZED.md: 505 lines / 105,777 bytes
- Line delta: 0 (0.0%); byte delta +934 (+0.89%). Both edits are in-place revisions of existing paragraphs; no new sections. File still ends on the ERR_MRA_ESCALATION_NOT_ELIGIBLE row of the §5 error catalogue — a real section boundary.

Changes:
- §2.9, precedence rank 3 — revise — added that requiredness at rank 3 is decided from the request body alone, keyed on a companion body field (revision_note when to_status is DRAFT; reason when an assessor to_status is SUSPENDED/WITHDRAWN; outcome when result_status is COMPLETED), never on the target's current status, so such a request is rejected with ERR_INVALID_REQUEST rather than reaching rank 8 — routes/schemes.py:88-89, routes/assessors.py:211-212, routes/planning.py:249-252.
- §3.9, "Opening a follow-on cycle" — revise — the at-surveillance-planning recomputation is also written onto the applicant organization's own risk_score with the organization's version bumped (the fourth of §3.7's four moments), in addition to the scope's surveillance_risk_score — implementation/domain.py:219-229, routes/decisions.py:262-264.

Per-edit pre-edit search log:

Edit 1 — §2.9 rank 3
- (a) Subject: precedence rank of a conditionally-required body field versus the rank-8 state-transition check.
- (b) Enumerated: grep -rn "required=(" implementation/ -> only routes/schemes.py:89 (revision_note iff to_status=="DRAFT") and routes/assessors.py:212 (reason iff to_status in SUSPENDED/WITHDRAWN); read both status-change handlers in full and confirmed the string_field call precedes domain.find(...) and the transition-set test in each. Also read the other conditional shape checks: routes/planning.py:47-52 (mode/day-count coupling, ERR_INVALID_REQUEST before find), routes/planning.py:249-252 (outcome required for COMPLETED, forbidden for ABORTED, both before find("sessions")), routes/decisions.py:177-179 (scope reason — unconditionally optional, so deliberately excluded from the sentence), routes/applications.py notice-period/duplicate/unannounced checks (separate errors at later ranks, untouched).
- (c) Adjustment: initially considered pinning this only in §3.1 for revision_note; widened to a rank-3 general rule keyed on "a companion body field" so the assessor reason and witness outcome paths are described too, and explicitly excluded the scope-status reason (kept out of the example list) since it is optional for every to_status in routes/decisions.py. Also worded as "a transition its target does not declare" rather than naming the scheme lifecycle, to avoid narrowing to one endpoint.

Edit 2 — §3.9 follow-on cycle
- (a) Subject: which resources the at-surveillance-planning risk recomputation writes to.
- (b) Enumerated every risk_score / recompute site: grep -n "recompute_risk\|risk_score" *.py routes/*.py -> domain.py:212-216 (recompute_risk_at_decision, writes org + store.touch), domain.py:219-229 (the new surveillance-planning helper, same shape), and its four/one callers: domain.py:283 (decision-record creation), routes/findings.py:199 (escalation hop 1), routes/complaints.py:113 (upheld case), routes/decisions.py:137 (finalize REFUSE) and :169 (finalize GRANT), routes/decisions.py:262-264 (follow-on cycle). Also read routes/decisions.py:144 (risk_score_at_grant reads the org's current risk_score at scope creation — unaffected, since the surveillance recompute happens only on the follow-on endpoint), routes/applications.py:99 (org seeded at 0), calc.py:151-161 (both variants return the same clamped integer written to org and scope), and store.py:86-97 (touch bumps at most once per record per request, consistent with §2.8's "version increases by 1").
- (c) Adjustment: wrote "the figure is written onto the applicant organization's own risk_score and the organization's version is bumped, exactly as it is at the other three moments" only after confirming all three other recompute callers likewise touch the organization unconditionally; avoided any claim about ordering relative to the new cycle's creation or about the scope schedule being derived from the org field, since the impl derives the schedule from the same local risk value.

Step 7 item with no PRD edit:
- test_06 site-buffer fix (probe relocation) was a pure test-artifact bug. §3.6 already determines the impl's behaviour verbatim: routes/planning.py:212-214 computes gap = starts_at.date() - other["_ends"].date() (signed) and rejects gap <= 14, which is exactly the PRD's "strictly greater than the fourteen-day site buffer; a gap of exactly 14 days is rejected, and so is anything smaller" — "anything smaller" already covers the negative gap the relocated probe would have produced. Same-org exemption and the "other session must be ON_SITE" asymmetry also already match the PRD, so its prose was left byte-identical.

ORCHESTRATOR VERIFICATION: diffed PRD.md against PRD_FINALIZED.md directly — exactly 2 changed lines (151 and 361), both in-place paragraph revisions matching the two reported edits, no added or removed lines, and the file still ends on the completed §5 error table. PRD_FINALIZED.md is NOT byte-identical to PRD.md, which is the expected shape here since Step 7 applied implementation fixes.

## Step 9: Complete PRD — 2026-09-06T01:31:03.539140599Z

ORCHESTRATOR DECISION (recorded per the autonomy directive): Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared PRD_COMPLETED.md rather than a single scan. Rationale: the implementation is 3,142 lines across 19 modules, and a single agent asked to scan all of it against a 505-line PRD reliably under-scans and can return a byte-identical file. Partition: pass 1 = platform layer (app/envelope/errors/validators/auth/store) + routes/read + routes/clock + routes/schemes + routes/assessors; pass 2 = calc.py + domain.py + routes/applications + routes/planning; pass 3 = routes/findings + routes/decisions + routes/complaints. Pass 1 alone performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from copying and edited in place. Each pass was told what the previous passes had already pinned so it would neither redo nor contradict them, and pass 3 additionally performed a closing whole-document consistency read.

Total: 73 changes — 55 ambiguity-pins, 15 mismatch-revisions, plus 3 edits pass 3 classified jointly while reconciling passes. Source PRD_FINALIZED.md 505 lines / 105,777 chars -> PRD_COMPLETED.md 513 lines / 133,154 chars (+8 lines, +27,377 chars, +25.9%).

### Pass 1 — platform layer + schemes/assessors (28 changes: 25 ambiguity-pins, 3 mismatch-revisions)
Performed the cp of PRD_FINALIZED.md -> PRD_COMPLETED.md. 505 -> 513 lines, 105,777 -> 118,283 chars.
- §2.1 headers — revise — ambiguity — whitespace-only header value counts as empty (401); header values compared verbatim, untrimmed — auth.py:39
- §2.1 ownership — insert — ambiguity — the rank-2 ownership check is narrow: body-driven ops fire only on a string organization_id; the response case yields to the rank-5 404 when the finding or its cycle does not resolve — auth.py:66-85
- §2.2 success envelope — revise — ambiguity — api_request_id is req_ + exactly 20 chars from A-Z0-9 — envelope.py:14-15
- §2.2 success envelope — revise — ambiguity — api_request_timestamp is real wall-clock, explicitly not the logical clock — envelope.py:18-20
- §2.2 error envelope — insert — ambiguity — message wording is not contractual — errors.py:83-88
- §2.2 error envelope — insert — ambiguity — ERR_NOT_FOUND/404, ERR_METHOD_NOT_ALLOWED/405, ERR_INTERNAL/500 use the same envelope; trailing slashes tolerated — app.py:33-47, app.py:20
- §2.3 pagination — insert — ambiguity — query-text leniency (whitespace, leading +, empty rejected, fractional rejected); over-large offset is not an error — envelope.py:62-89
- §2.3 ordering — insert — ambiguity — logical-clock created_at ties broken by insertion order; filters compared as text; a null field matches no filter value; unknown query params ignored — store.py:148-150, read.py:15-29
- §2.4 audit fields — insert — ambiguity — created_at/updated_at are minted from the logical clock — store.py:112-116
- §2.4 version — insert — ambiguity — bumped at most once per request, not per hop; a created resource is never re-bumped (always version 1); a no-op counter/flag write bumps nothing — store.py:86-121
- §2.4 clock — insert — ambiguity — current_utc parsing (T required, Z/offset normalised, naive read as UTC); clock may move backwards; 200 + empty data — validators.py:156-171, routes/clock.py:13-19
- §2.4 instants — insert — ambiguity — sub-millisecond precision truncated, not rounded — store.py:48-49
- §2.7 multiplier — revise — MISMATCH — PRD said "exactly 4 decimal places"; impl accepts at most 4 (1.5 == 1.5000) — validators.py:90-92
- §2.7 decimals — insert — MISMATCH — decimal fields are bare JSON numbers, so trailing zeros are lost (1.0, 60.0); numeric strings accepted on input — calc.py:48-52
- §2.9 rank 3 — insert — ambiguity — absent/empty body == {}; explicit null == absent; every length/range/places/type/list/date/instant/FK-shape/uniqueness violation is ERR_INVALID_REQUEST; uniqueness checked last — validators.py:17-184
- §3.1 scheme creation — revise — ambiguity — program_code collision -> ERR_INVALID_REQUEST — routes/schemes.py:55-57
- §3.1 lifecycle — insert — ambiguity — revision_note on non-DRAFT transitions is validated then ignored; the publication range re-check is unfailable because rule values are immutable after creation — routes/schemes.py:88-102
- §3.2 recruitment — revise — ambiguity — email 1-320 chars, duplicate/malformed -> ERR_INVALID_REQUEST, case-sensitive uniqueness — routes/assessors.py:34-43
- §3.2 declared evidence — insert — ambiguity — duplicate triple -> ERR_INVALID_REQUEST, and REVOKED/EXPIRED records still occupy the triple — routes/assessors.py:78-83
- §3.2 verification — insert — ambiguity — verified_years_experience 0-50, other two non-negative unbounded, all required; non-PENDING -> ERR_INVALID_STATE_TRANSITION — routes/assessors.py:117-124
- §3.2 screening — insert — ambiguity — screening never raises ERR_INVALID_STATE_TRANSITION from any qualification_status; the dimension just stays put — routes/assessors.py:194-203
- §3.2 assessor status — insert — ambiguity — to_status enum is all five names but only four pairs are legal; SCREENING -> QUALIFIED is not requestable here — routes/assessors.py:20-26,216-218
- §3.2 reinstatement/withdrawal — insert — ambiguity — reinstatement without a granted qualification -> ERR_INVALID_STATE_TRANSITION; a reason on reinstatement is discarded; withdrawal writes suspension_reason; the withdrawal cascade writes the literal "assessor suspended" — routes/assessors.py:219-242
- §3.3 newest-disclosure rule — insert — ambiguity — same-created_at ties broken by filing order — calc.py:237-239
- §3.3 restriction on filing — insert — ambiguity — a fresh row is always newest for its pair; a second open-ended structural disclosure still bumps the assessor's version — routes/assessors.py:180-187
- §3.3 screening verdict — insert — ambiguity — an assessor with no disclosures screens to SCREENED — calc.py:248-262
- §4 intro — insert — MISMATCH — PRD implied detail views expose more than lists; impl serialises the identical full field set everywhere, minus _-prefixed internals — read.py:32-37, store.py:124-135
- §5 intro — insert — ambiguity — the three out-of-catalogue infrastructure identifiers named explicitly — app.py:33-47
Pass 1 also verified mechanically that errors.py matches the §5 table exactly (51 ids, 51 statuses, zero discrepancies; no table rows touched) and that all 26 GET endpoints and their filter sets match §3/§4 exactly (no filter missing or extra).

### Pass 2 — calc.py, domain.py, applications, planning (18 changes: 15 ambiguity-pins, 3 mismatch-revisions)
Confirmed it did NOT run the cp step. 118,283 -> 124,312 chars, line count unchanged (all in-paragraph).
- §3.4 (organization registration) — insert — ambiguity — contact_email bound 1-320 chars; legal_name uniqueness is exact/case-sensitive and validated last — routes/applications.py:82-92
- §3.4 (cycle creation) — revise — MISMATCH — PRD implied non-INITIAL cycles carry a scope id; this endpoint always writes origin_scope_id null regardless of cycle_type — routes/applications.py:127
- §3.4 (propose) — insert — ambiguity — a lapsed qualification is skipped by the gate but not moved to EXPIRED; lazy expiry fires only at confirm — domain.py:149-172, routes/applications.py:151
- §3.4 (propose) — insert — ambiguity — proposal never tests qualification_status; only confirmation requires QUALIFIED — routes/applications.py:145-152 vs 182
- §3.4 (confirm) — insert — ambiguity — the not-QUALIFIED gate reports ERR_INVALID_STATE_TRANSITION and is evaluated after the cycle freeze/status gate — routes/applications.py:175-184
- §3.4 (confirm) — insert — ambiguity — the organization hop fires only from APPLIED; any other status is left unbumped — routes/applications.py:206-209
- §3.4 (recuse) — insert — ambiguity — cycle-status gate is ERR_INVALID_STATE_TRANSITION, and recusal ignores suspension_blocked — routes/applications.py:225-227
- §3.5 (plan creation) — revise — MISMATCH — "Once a cycle has a confirmed team" was wrong: drafting imposes no team requirement — routes/planning.py:36-58
- §3.5 (plan creation) — insert — ambiguity — "a status that permits planning" pinned to SUBMITTED or TEAM_ASSIGNED — domain.py:10, routes/planning.py:57
- §3.5 (approve) — insert — ambiguity — the no-lead, remote-not-allowed and remote-with-witness-floor gates all report ERR_INVALID_STATE_TRANSITION, in that order — routes/planning.py:113-122
- §3.5 (return-to-draft) — insert — ambiguity — non-PLANNED cycle gives ERR_INVALID_STATE_TRANSITION; freeze flag not consulted — routes/planning.py:146-149
- §3.5 (return-to-draft) — revise — MISMATCH — "fee lines are not preserved" implied clearing; impl leaves all day counts and fee lines on the plan until the next approval — routes/planning.py:155-158
- §3.5 (plan terminal states) — insert — ambiguity — a plan cancelled by the suspension cascade keeps superseded_by_plan_id null — domain.py:242-245
- §3.6 (scheduling) — insert — ambiguity — the freeze flag is the only cycle-level gate; no cycle status is required — routes/planning.py:189-192
- §3.6 (scheduling) — insert — ambiguity — booking applies no team/qualification/impartiality gate to the nominated assessor — routes/planning.py:185-238
- §3.6 (site buffer) — insert — ambiguity — only the other session's delivery_mode must be ON_SITE; the requested slot's own mode is not consulted — routes/planning.py:203-214
- §3.6 (completion) — revise+insert — ambiguity — evidence_note optional and may stay null; every GRANTED qualification for the programme is refreshed (all role types); completed_witness_session_count spans every plan of the cycle — routes/planning.py:277-287, domain.py:68-70,317-322
- §3.6 (abort) — insert — ambiguity — abort ignores both the plan's status and the cycle freeze; evidence_note optional — routes/planning.py:260-274
- §3.6 (close) — insert — ambiguity — the response carries the cycle, not the plan or decision record — routes/planning.py:325
- §3.7 (risk model) — insert — ambiguity — a recomputation always writes and always bumps the organization's version, even when unchanged (risk_score is outside §2.4's derived-counter exemption); null resolved_on cases drop out of the complaint term — domain.py:212-229, calc.py:102-116
- §3.7 (at-surveillance-planning) — insert — ambiguity — both raw scores are the full six-term score, so a qualifying upheld case is counted twice (half weight + full weight) — calc.py:155-161

### Pass 3 — findings, decisions, complaints (27 changes: 18 ambiguity-pins, 9 mismatch-revisions)
Confirmed it did NOT run the cp step; all 46 prior-pass sentences intact. 124,312 -> 133,154 chars, line count unchanged.
- §3.7 — revise — ambiguity — the five cycle statuses that permit findings, ERR_APPLICATION_STATE_INVALID, gate before team-membership — findings.py:32
- §3.7 — insert — ambiguity — review's non-RESPONSE_SUBMITTED status is ERR_INVALID_STATE_TRANSITION (not ..._NONCONFORMITY_STATE_INVALID), before the membership gate — findings.py:115
- §3.7 — insert — ambiguity — same for verification's non-RESPONSE_ACCEPTED status — findings.py:137
- §3.7 — insert — ambiguity — escalation's status/classification tests both ERR_INVALID_STATE_TRANSITION, status first, an OBSERVATION never reaches the overdue test; escalation ignores cycle status and freeze flag — findings.py:179-190
- §3.7 — insert — ambiguity — reopen's two gates are ERR_INVALID_STATE_TRANSITION, freeze flag not consulted — findings.py:216-222
- §3.7 — insert — ambiguity — the auto-deferred record keeps decided_by_user_id null — findings.py:240-245
- §3.8 — revise — ambiguity — rationale >=1 char, no max; ERR_INVALID_STATE_TRANSITION / ERR_ASSESSOR_NOT_FOUND / ERR_INVALID_STATE_TRANSITION for the first two guards, order normative — decisions.py:34-46
- §3.8 — insert — ambiguity — the four guards are exhaustive; a ballot reads neither cycle status nor freeze flag — decisions.py:29-61
- §3.8 — revise — MISMATCH — finalize gate order rewritten to impl/§2.9 order (VOTING -> cycle -> SoD -> pinned revision -> scope-line membership -> quorum -> shape); granted_scope_lines bounds 0-20/1-80 unique; omission on a granting outcome is ERR_CONDITIONS_REQUIRE_REDUCED_SCOPE; GRANT needs element-for-element order equality; quorum also guards DEFER — decisions.py:71-107
- §3.8 — insert — ambiguity — every branch responds with the decision record, not the scope/cycle/organization — decisions.py:120,138,171
- §3.8 — revise — MISMATCH — on REFUSE the organization is written to ACCREDITED unconditionally (a SUSPENDED org with another live scope is returned to ACCREDITED) — decisions.py:131-137
- §3.9 — insert — ambiguity — follow-on notice_days default 30 / 0-120; requested_scope_lines defaults to a verbatim copy of the scope's lines and is never subset-checked; four-gate order — decisions.py:241-259
- §3.9 — insert — MISMATCH — duplicate-cycle check runs before the unannounced-authority gate; the authority gate and interval constants read the granting cycle's pinned revision; no publication-status test on this path — decisions.py:255-257
- §3.9 — insert — ambiguity — the follow-on cycle pins the programme's current rule_revision — applications.py:61 via decisions.py:260
- §3.9 — insert — ambiguity — the re-derivation bumps the scope's version, leaves next_reassessment_due and risk_score_at_grant alone, and responds 201 with the new cycle — decisions.py:262-278
- §3.9 — revise — MISMATCH — suspension reason is optional; omitted, null is written onto scope and organization — decisions.py:179-187
- §3.9 — revise — MISMATCH — the blanket "a frozen cycle rejects every further assessment action" narrowed to the ten flag-testing operations, with the freeze-free compensating paths named — grep of suspension_blocked across routes/
- §3.9 — revise — MISMATCH — restoration clears the scope's suspension_reason only (the organization's is left standing), a surviving ESCALATED finding is ERR_INVALID_STATE_TRANSITION, a supplied reason is discarded — decisions.py:190-215
- §3.9 — insert — ambiguity — withdrawal discards reason, lifts no freeze, leaves the organization's suspension_reason, and leaves its standing alone unless the count hits 0 — decisions.py:217-234
- §2.9 rank 9 — revise — MISMATCH — "seven operations" -> the correct ten (adds confirming a team member, submitting a response, recording a COMPLETED witnessing outcome); notes the three cycle-status dependencies that live at rank 8 instead — 10 grep sites
- §2.9 rank 9 — insert — ambiguity — for session scheduling and COMPLETED outcome only the flag is tested, not the cycle's status — planning.py:189,260
- §2.5 — revise — MISMATCH — the ERR_SCHEME_NOT_PUBLISHED claim narrowed to initial cycles and qualifications; a follow-on cycle never tests publication — decisions.py:237-260
- §3.10 — insert — ambiguity — kind/application_id coherence is ERR_INVALID_REQUEST before FK resolution; organization_id unbounded; the appealed cycle need not belong to the organization nor be decided — complaints.py:30-37
- §3.10 — revise — ambiguity — nominee resolves first (ERR_ASSESSOR_NOT_FOUND even on a non-RECEIVED case); case-status and non-QUALIFIED nominee are ERR_INVALID_STATE_TRANSITION; CLEARED_WITH_NOTE passes and is recorded nowhere — complaints.py:61-74
- §3.10 — revise — ambiguity — non-UNDER_REVIEW resolve is ERR_INVALID_STATE_TRANSITION; status becomes the supplied outcome verbatim — complaints.py:99-104
- §3.10 — insert — ambiguity — the upheld recompute is scoped to the case's application_id, so an upheld COMPLAINT scores no findings at all (score = 2 x qualifying cases, capped) and can lower the stored score — complaints.py:113 + calc.py:129-148
- §3.10 — revise — MISMATCH — MRA escalation's status test is ERR_INVALID_STATE_TRANSITION at rank 8; only the kind and live-scope tests carry ERR_MRA_ESCALATION_NOT_ELIGIBLE, in that order — complaints.py:132-141

Pass 3 closing consistency read: (a) no contradictions among pass-1/2/3 sentences — the two it did find were resolved while reading (the §2.9 rank-9 "seven operations" list now matches the §3.9 freeze sentence and pass 2's §3.6 flag-only scheduling pin; the §3.9 follow-on gate-order sentence is now explicitly reconciled with the prose that follows it). (b) Valid markdown: backticks balanced, all five ## sections present and in order, 20 ### subsections, §4 table still 60 endpoint rows. (c) File ends at the completed §5 table with all 51 ERR_* rows intact, ERR_MRA_ESCALATION_NOT_ELIGIBLE | 422 last.

ORCHESTRATOR VERIFICATION: PRD_COMPLETED.md is 513 lines / 133,154 chars and is NOT byte-identical to PRD_FINALIZED.md (the scan genuinely ran). Structure re-checked independently: 5 `## ` sections, 51 `| `ERR_` catalogue rows, file ends on the completed §5 table. Steps 8 and 9 touched no code — `find workspace/implementation -name "*.py" -newer results.1.json` returns nothing, so the green 8-round sweep (8/8 at 65/65, written 00:37:40) still describes exactly the shipped implementation; no re-sweep was needed. test_helpers/ and test_suite/ are at the task root and workspace/ contains no test directories. Only one worklog.md exists (task root) — no cwd-drift strays. Pipeline complete.
