# Worklog — task_2777_marketplace_seller_account_health_policy_enforcement

## Step 1: Create task directory — 2026-09-04T20:13:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2777_marketplace_seller_account_health_policy_enforcement` and its `workspace/` subdirectory. Index 2777 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T22:30:00.000Z

All three scaffold artifacts are complete and the lint is clean.

Files:
- SCAFFOLD.yaml — 2659 lines (2657 after the post-step directive strip)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2287 lines
- SCAFFOLD_CORNER_DESIGN.yaml — 5868 lines

Top-level keys verified: SCAFFOLD.yaml holds only §1.0–§1.7 keys (no scaffold_difficulty_design / scaffold_corner_design); each design file has exactly one top-level key.

SCAFFOLD.yaml counts: 12 entities · 44 endpoints · 10 state machines (across 9 entities, parallel shape) · 2 concurrency rules · 13 calculations · 16 validation rules · 49 error codes · 5 roles. entity_topology: flat, api_prefix: "", consistency immediate.

Design-file instance counts:
- §1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rule groups, 23 instances (>=2 per rule).
- §1.9 SCAFFOLD_CORNER_DESIGN.yaml: 108 instances = 77 full recipes + 31 excluded_because stubs, in the 9 allowed sections: entities 14, state_machines 16, calculations 20, validations 27, endpoints 10, errors 4, rbac 11, cross_cutting_complexity_layers 5, consistency_model 1.

Cross-file checks beyond the lint: all 31 stub difficulty_instance citations resolve to real <rule_id>/<instance_name> pairs in §1.8; no stub carries a test_recipe; all 131 instance names unique across both files; every section/claim_type drawn from the claim-extraction-guide vocabulary; all 49 error codes triggered somewhere in §1.8+§1.9; all 44 declared endpoints exercised by at least one call.

Lint verdict (verbatim):
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    44
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1055

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Changes the lint forced in SCAFFOLD.yaml: five read endpoints added (39 -> 44): GET /violations/{id}, GET /health-evaluations/{id}, GET /plans-of-action/{id}, GET /disbursement-holds/{id}, GET /related-account-links/{id} — the lint derives an entity's collection segment only from a single-resource GET, so five entities with filtered lists but no by-id read could not satisfy reverse-reachability. One error code added (48 -> 49): ERR_EVALUATION_NOT_FOUND plus its slot in the priority-30 path-existence code list. Role shared_operations extended with the new by-id reads; two stale comments corrected. Corner-design capture fixes: requires_poa / poa_deadline_at moved from EnforcementAction to PolicyRule.requires_poa and PlanOfAction.deadline_at; resolution_reason is not an Appeal field (switched to Appeal.reinstatement_granted).

ORCHESTRATOR NOTE (post-step action, per known leak path): the scaffold subagent flagged that SCAFFOLD.yaml's `scenario:` block still began with the literal line "Generate task harder than expert level!". The orchestrator deleted that line (and its trailing blank line) from SCAFFOLD.yaml line 8 before Step 4, and re-validated the file parses as YAML (13 top-level keys). A repo-wide grep for "harder than expert" in the task directory now returns nothing, so the difficulty directive cannot reach PRD.md via the scaffold. Only the scaffold subagent ever received the directive.

## Step 3: Copy shared files — 2026-09-04T22:31:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T22:48:00.000Z

File: workspace/PRD.md — 429 lines (written in 9 chunked `cat >>` appends; no single giant Write).

Section headings:
```
1:# Marketplace Seller Account Health & Policy Enforcement API — Product Requirements Document
3:## 1. Introduction
11:## 2. Global Specifications & System-Wide Principles
15:### 2.1. User and Role-Based Access Control
29:### 2.2. API Response Structure
31:#### Standard Success Response Format
56:#### Standard Error Response Format
78:### 2.3. Pagination
86:### 2.4. Resource Identity, Timestamps and the Logical Clock
94:### 2.5. The Two Posture Dimensions and the Recompute Order
102:### 2.6. Rates, Points, Money and Rounding
112:### 2.7. Segregation of Duties
121:### 2.8. Order of Rejection
144:### 2.9. Path Resolution and Foreign-Key Existence
150:### 2.10. Optimistic Concurrency Control
160:### 2.11. Transparency Notices and Supersession
168:## 3. Business Logic & Workflows
170:### 3.1. Registration and the Hunt for Re-Registered Bans
188:### 3.2. The Policy Catalogue and the Seller's Listings
198:### 3.3. Filing Measured Performance Windows
208:### 3.4. Health Evaluation: Two Readings of Defect Rate, One Score, One Tier
234:### 3.5. Violation Reports, Investigation and Adjudication
244:### 3.6. Severity Weighting and the Enforcement Ladder
264:### 3.7. Plans of Action: Submission, Revision and Review
278:### 3.8. Appeals, Escalation, Reinstatement and the Final Ban
302:### 3.9. Seller Funds: Proceeds, Reserves, Release and Forfeiture
324:## 4. Endpoint Definitions
375:## 5. Error Code Catalogue
```

§2.2 was appended by `cat` from section-2.2-response-structure.md, so it is byte-identical to the fixed contract.

Hard Contract 1 — Field-Name Coverage: entities[].fields 125 required / 125 present / 0 missing; endpoints[].request_body 58/58/0; endpoints[].query_params 18/18/0. Status PASS. (125 distinct names across 148 field definitions in 12 entities; request-body set includes both OCC token fields.)

Hard Contract 2 — Rule Coverage: validations[] with priority 16/16/0; concurrency_rules[] OCC rejections 2/2/0 (write_endpoint + expected_<parent>_version + error_id all named); state_machines[].transitions 45/45/0; calculations[] 13/13/0; validations[] conditions 16/16/0; endpoints[].side_effects / applies_to 24 side-effect endpoints + 16 applies_to scopes = 40/40/0; entities[].fields[] structured content 148/148/0; sibling-branch symmetry 7 groups / 7 equal density / 0 asymmetric. Status PASS. Symmetry groups: ODR PROVISIONAL/FINAL; reserve ROLLING/CLAIM_EXPOSURE; violation SUBSTANTIATED/DISMISSED; plan ACCEPT/RETURN/REJECT; appeal GRANTED/DENIED; escalation GRANTED_ON_ESCALATION/FINAL_DENIED; link CONFIRMED/DISMISSED.

Hard Contract 3 — §3 Path Purity: 859 backtick tokens scanned; 0 starting with `/`; 0 bare HTTP-method tokens; 0 method+path combined tokens. Status PASS. §3 refers to operations by role + action verb and by state transition only.

Additional coverage notes: §4 is a 4-column table (Method | Path | Description | Authorized Role(s)) with all 44 endpoints; §5 is a 2-column table with all 49 error IDs at their scaffold HTTP statuses, every one reachable from prose in §2 or §3. All 10 state machines covered, including Seller's two parallel dimensions (enforcement_state, disbursement_state) and the pinned recompute order. Rounding order preserved exactly: per-penalty rounding for health_score, single rounding for severity_points_applied, single rounding at the end for severity_points_balance, rung selection after the post-issuance balance. Deliberate breach asymmetry preserved (three lower-is-better metrics breach at or above their threshold; valid-tracking breaches strictly below its floor). Three inverted list sort orders preserved (window_end desc, sent_at desc, submitted_at desc) with created_at ascending tie-breaks against the global default. All named constants rendered as literal values/prose rather than identifier names (four public email domains, 0.35/0.60 link thresholds, 17-day plan deadline, 30/14-day windows, 24-hour buffer, two-revision cap). No audit footer or contract-report block written into PRD.md; only workspace/PRD.md was written; SCAFFOLD.yaml and worklog.md untouched; neither design yaml was opened, grepped, or referenced.

ORCHESTRATOR VERIFICATION (truncation guard): independently confirmed PRD.md is 429 lines and its tail ends at a real section boundary — the final line is a complete §5 error-table row `| `ERR_FORFEIT_EXCEEDS_HOLD` | 422 |`, not a mid-sentence cut. All 49 error rows present (`grep -c '^| `ERR_'` = 49). Grep for "harder than expert", "expert level" and "scaffold" in PRD.md returns nothing, confirming no difficulty-directive or scaffold-reference leak. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T23:25:00.000Z

Implementation complete and smoke-verified.

Layout (`workspace/implementation/`, 3169 lines total):
Infrastructure: app.py 78 · start.sh 8 (chmod +x, reads $PORT, binds 0.0.0.0, foreground `exec python3 app.py`) · requirements.txt 1 (Flask==3.0.3) · constants.py 171 · errors.py 124 (49 error ids + HTTP statuses) · clock.py 63 (logical clock, default 2026-08-01T00:00:00Z, never wall-clock for entity data) · db.py 140 (12 in-memory dicts, set_field/commit version-bump machinery) · response.py 87 (envelope + pagination) · validators.py 187 · serializers.py 245 · guards.py 65 · middleware.py 56
Services: services/calc.py 260 (dual ODR, pinned health-score rounding, severity points, decay, ladder, risk tier, both reserve bases, related-account confidence) · services/posture.py 193 (balance -> enforcement -> disbursement, listing cascades, release/sweep) · services/notify.py 37 (supersession)
Routes: sellers.py 205 · appeals.py 249 · holds.py 179 · plans.py 177 · metrics.py 157 · enforcement.py 156 · violations.py 116 · links.py 74 · listings.py 65 · policy_rules.py 56 · clock_routes.py 20

Endpoints: 44/44. Programmatically diffed the Flask url_map against SCAFFOLD.yaml's endpoint table — exact 1:1 match on all 44 method/path pairs, no extras.

Verification done: booted on PORT=39777 and killed only that PID (port confirmed free afterwards; no broad pkill). Exercised: registration + related-account detection (score 1.00 cap, 5 signals, top-link root_seller_id, REGISTRATION_FLAGGED, WATCHLIST->RESERVE_HELD), policy rules, listings/relist, violation lifecycle, ladder issuance (8.00->10.00 with repeat factor -> ACCOUNT_SUSPENSION), suspension -> FULL_HOLD sweep, POA submit/review, appeal deny -> escalate -> FINAL_DENIED -> ban, appeal GRANT -> VACATED -> reinstatement + aggregate release, related-link CONFIRMED -> ban + sweep, hold create/overlap/stale/SoD/manual release/forfeit, health evaluation (hand-recomputed odr_provisional 0.0284, odr_final 0.0122, score 84.23 and a second case at 40.79 — both matched exactly), decay (3.75 -> 1.88 after 183 days), notification supersession, error envelope shapes for 401/403/404/405/409/412/422 and unknown routes. Restart showed total_count: 0, confirming state is wiped per boot. No file, SQLite, or /tmp persistence; nothing seeded.

Genuinely ambiguous PRD passages and chosen interpretations:
1. Second appeal on a terminal action. §2.8 orders state (10) before uniqueness (14), but §3.8/scaffold say a second appeal against an UPHELD/VACATED action returns ERR_APPEAL_ALREADY_EXISTS. Resolved by checking uniqueness only inside the terminal-state branch and keeping the general uniqueness check at position 14 (after the appeal window), so both readings are satisfied.
2. denial_reason on a denial is treated as conditionally required -> ERR_INVALID_REQUEST when missing on DENIED/FINAL_DENIED.
3. POA_DECISION rationale must be non-null (§2.11) but review_notes is optional -> falls back to "Plan of action review decision: <decision>".
4. GET /plans-of-action filters to the acting Seller's own plans (scaffold roles say "own plans only"); operators see all.
5. New POA when an ACCEPTED/REJECTED plan already exists -> ERR_INVALID_STATE.
6. Reviewing a plan bumps the parent action's version (§2.10 names it as a cause) even though the scaffold's side-effect list omits it.
7. Acknowledge: on ACKNOWLEDGED -> ERR_INVALID_STATE; on UPHELD/VACATED -> ERR_ACTION_NOT_APPEALABLE_STATE.
8. HEALTH_BREACH notice is emitted only when the auto-violation is actually minted (empty rule pool => no notice).
9. POST /metric-snapshots resolves seller_id after shape validation (§2.9 and scaffold priority 40 omit it from body-FK checking).
10. Notice ordering on cascades: FULL_HOLD -> lower posture emits one aggregate FUNDS_RELEASED anchored on the sweeping row; RESERVE_HELD -> NORMAL emits one per hold. ACCOUNT_BANNED is emitted before the funds step on a link confirmation (matching §2.5's step order and the §3.1 sentence order).
11. Manual release order: ERR_INVALID_STATE (not ACTIVE) is checked before ERR_HOLD_NOT_MANUALLY_RELEASABLE, following §3.9's prose order; both are priority-85 state errors.
12. Forfeit takes no ban check (scaffold priority 80 exempts it) and no minimum above 0 on forfeited_amount_cents.
13. List tie-breaks keep the scaffold's stated convention (primary DESC, tie-break created_at ASC) for notifications/snapshots/plans, since no tie-break is pinned for "newest first".
14. Datetimes accept Z/+00:00 with 0-6 fractional digits and reject naive/non-UTC; unknown list-filter enum values simply match nothing.
15. Body FKs are resolved only when the value is a non-empty string; otherwise the shape step owns the rejection with ERR_INVALID_REQUEST.

## Step 5: Generate unit tests — 2026-09-05T00:15:00.000Z

Generation is complete and audited.

Both directories are at the task root; nothing was created, read, or written under workspace/, and workspace/PRD.md and worklog.md are untouched.

test_helpers/ — 9 files, 1852 lines: __init__.py 53 · api_client.py 217 · api_errors.py 137 · assertions.py 292 · constants.py 116 · factories.py 298 · fixtures.py 428 · test_users.py 77 · types.py 234

test_suite/ — 19 files, 7861 lines, 126 tests:
conftest.py 53 (–) · test_01_dual_variant_calculations.py 202 (4) · test_02_combinatorial_formulas.py 269 (6) · test_03_non_linear_state_machines.py 362 (6) · test_04_transitive_cascades.py 408 (6) · test_05_validation_priority_conflicts.py 339 (6) · test_06_boundary_precision.py 339 (6) · test_07_cross_entity_state_dependency.py 243 (4) · test_08_resource_temporal_overlap.py 282 (5) · test_09_compensating_invariants.py 261 (4) · test_10_entities.py 647 (12) · test_11_state_machines.py 589 (9) · test_12_calculations.py 723 (11) · test_13_validations_a.py 804 (10) · test_14_validations_b.py 655 (10) · test_15_endpoints.py 485 (7) · test_16_errors.py 309 (6) · test_17_rbac.py 633 (11) · test_18_concurrency.py 258 (3)

Coverage: Queue A (Difficulty, §1.8) 23 of 23 non-stub instances, 47 tests, minimum 2 tests per instance. Queue B (Corner, §1.9) 76 of 77 non-stub instances (31 excluded_because stubs ignored), 79 tests, >=1 per instance. Total 126 tests / 99 distinct design instances.

Skipped instances:
- Corner/state_machines/state_second_poa_decision_notice_supersedes_the_first_and_both_remain_readable — non-unique-derivability. §2.11 admits both PLAN_OF_ACTION and ENFORCEMENT_ACTION as the POA_DECISION notice's related_entity_type, and §3.7 never pins which; the recipe's asserted supersession collision only occurs under the ENFORCEMENT_ACTION reading, so the PRD does not uniquely derive the outcome. No placeholder, xfail, or weakened test was emitted.

Two assertion-level (not instance-level) non-translations: the recipes' forfeited_amount_cents == null on a cascade-minted hold (PRD pins zero only for explicitly created holds) is simply not asserted, and the recipes' denial_reason: "NO_NEW_EVIDENCE" — absent from the §3.8 enum — was replaced with the PRD's EVIDENCE_UPHELD.

Verification performed: `python3 -m pytest test_suite --collect-only` -> 126 tests collected, no import or collection errors. pyflakes clean on every file in both directories (only the deliberate re-export warnings in test_helpers/__init__.py remain); three genuinely unused imports removed from assertions.py, factories.py, fixtures.py. Design-tag audit: every test has exactly one Design: line, it is the last docstring line, every tag name resolves to exactly one `- name:` in the source yaml, and every Corner/<section> and Difficulty/<rule_id> prefix matches the instance's actual yaml section/rule. PRD-citation audit: every quoted docstring sentence was whitespace-normalised and matched verbatim against workspace/PRD.md. One failure found and fixed — test_14_validations_b.py::test_the_rule_code_is_the_whole_uniqueness_key had truncated the §3.2 rule sentence at an em dash; it now carries the full sentence. No occurrence of "scaffold", no skip/xfail/TODO/placeholder markers, no monetary values sent as JSON strings, and ISO-8601 comparisons go through assert_instant_equals/canonical_instant.

ORCHESTRATOR NOTE: Steps 5 and 6 were launched as separate background agents; the impl generator was launched immediately after the test generator and was explicitly forbidden from reading test_helpers/ or test_suite/ or either design yaml, preserving the isolation the concurrent launch is meant to provide. Post-step sweep confirmed test_helpers/ and test_suite/ are at the task root (not under workspace/) and no stray worklog.md exists under workspace/.

## Step 7: Run tests and iterate — 2026-09-05T00:55:00.000Z

Clean 8-round sweep achieved: 126/126 passing in all 8 parallel rounds.

Iterations run: 2 (an initial launch had a shell-quoting bug that pointed all 8 rounds at one results.$i.json; the sweep was rebuilt as a setsid-launched script file, so iteration 1 is the first valid 8-round sweep). Iteration 1 result: 121/126 in every round, 5 deterministic failures (8/8 rounds each) — no flakiness anywhere in the suite.

Tests deleted: none.

Assertions removed (STEP 1c partial coverage):
- test_suite/test_03_non_linear_state_machines.py — test_the_revision_bound_blocks_only_the_return_edge: dropped read_action(...)["version"] == 4. PRD does not uniquely determine whether a plan review advances the parent action's version. §3.7's review paragraph lists the review's effects and never mentions the action's version, but §2.10 says a client's token goes stale "because a plan against it was reviewed". Those two readings give 4 vs 7 (the implementation gives 7). §2.10's own list is internally inconsistent with §3.7 (it names "reviewed" where §3.7 explicitly says submission bumps the action), so neither number is derivable. The test's real subject — ACCEPT moving SUBMITTED -> ACCEPTED, reviewed_by_user_id, and deadline_at = issued_at + 17 days — is retained.

Fixes applied to test_suite/:
- test_14_validations_b.py — test_one_violation_can_carry_only_one_live_action: asserted disbursement_state="NORMAL" for a seller at WATCHLIST with a 2.00 balance. PRD §3.9 verbatim: "if enforcement_state is WATCHLIST or RESTRICTED ... the target is RESERVE_HELD". Corrected to RESERVE_HELD — this also matches test_15_endpoints.py:262, which already asserts exactly that for the same posture and passes.
- test_16_errors.py — _suspended_seller_with_the_sweeping_hold published a rule with base_severity_weight=12.00, which PRD §3.2 forbids ("between 0.50 and 8.00 inclusive"), so the PRD-faithful server correctly returned ERR_INVALID_REQUEST and killed the setup for 2 tests. Rebuilt to reach the same 12.00 points legally via §3.6's rights-owner escalation: an INTELLECTUAL_PROPERTY rule at 8.00 cited by a RIGHTS_OWNER -> 8.00 x 1.00 x 1.50 = 12.00 -> ACCOUNT_SUSPENSION. Reporter type changed to RIGHTS_OWNER to satisfy §3.5's ERR_REPORTER_NOT_ELIGIBLE rule.
- test_18_concurrency.py — test_the_whole_suspension_cascade_is_readable_on_the_next_call: same out-of-range base_severity_weight=12.00 setup bug, same fix (both of its violations switched to RIGHTS_OWNER).

Fixes applied to test_helpers/:
- fixtures.py — suspended_seller(): its base_severity_weight default was 12.00, violating PRD §3.2's 8.00 ceiling, so the fixture could never succeed. Rebased on the same legal 8.00 IP + rights-owner path. (Latent only — no test in the suite currently calls it, nor banned_seller_via_escalation() which depends on it.)

Fixes applied to implementation/: none. All 5 failures were test-side. Notably, the implementation's base_severity_weight bound (routes/policy_rules.py:25, 0.50-8.00) and its WATCHLIST -> RESERVE_HELD funds target (services/posture.py:disbursement_target) were both correct and PRD-verbatim; the tests were rejecting behavior the PRD mandates.

ORCHESTRATOR VERIFICATION (sweep-artifact guard): independently confirmed all 8 results.$i.json files exist on disk (each ~38.7 KB, written 00:54) and parse as complete JSON, each reporting passed=126, failed=0, errors=0, skipped=0, total=126. The clean sweep is real, not a claimed one.

ORCHESTRATOR DECISION on Step 8: Step 7 applied 0 fixes to implementation/, but it did NOT exit on the first sweep with zero changes — it removed one assertion (STEP 1c), fixed three test_suite/ files and one test_helpers/ fixture. The skip condition in the skill requires 0 deletions AND 0 test_suite/ fixes AND 0 test_helpers/ fixes AND 0 implementation/ fixes; three of those four are non-zero here. Step 8 therefore RUNS. Its targets are the PRD-silence sites the Step 7 diff exposed: the §2.10-vs-§3.7 contradiction about whether reviewing a plan bumps the parent action's version (the removed assertion), and — as auxiliary evidence of where the PRD was mis-read rather than silent — the §3.9 WATCHLIST/RESTRICTED -> RESERVE_HELD target and §3.2's 0.50-8.00 base_severity_weight bound, both of which the PRD already states verbatim and which therefore need no patch. Per Step 8's hard scope, only PRD-silence or PRD/impl-mismatch items traceable to the diff may be edited.

## Step 8: Finalize PRD — 2026-09-05T01:00:00.000Z

Done. One edit was warranted; the other four Step 7 items were pure test/fixture bugs against behavior the PRD already pins verbatim.

Line counts: workspace/PRD.md 429 lines; workspace/PRD_FINALIZED.md 429 lines. Line-count delta 0 lines (0.00%). One line revised in place (0.23% of lines touched).

Change list:
- §3.7 (plan-of-action review paragraph) — revise — added that a successful review, whichever of ACCEPT/RETURN/REJECT runs, increments the parent EnforcementAction's version by one and thereby invalidates any expected_enforcement_action_version a client held, tying that back to §2.10's "a plan against it was reviewed" clause — implementation/routes/plans.py:170 (db.mark_dirty(action)), committed by implementation/db.py:74-85.

Per-edit pre-edit search log — Edit 1 (§3.7 review bumps the action's version):
(a) Subject: what mutates an EnforcementAction's version / updated_at.
(b) Impl paths enumerated (grepped mark_dirty|set_field across all of implementation/, then read each action-touching site):
  - routes/plans.py:170 — review: unconditional mark_dirty(action) after all guards, for all three decisions -> bump (the Step 7 site).
  - routes/plans.py:100 — submission: mark_dirty(action) -> bump (already in PRD §3.7, left verbatim).
  - routes/enforcement.py:154-155 — acknowledge: set_field(action, state/acknowledged_at) -> bump (already in PRD §3.6, left verbatim).
  - routes/enforcement.py:75-107 + services/posture.py:51 — issuance: the action row is newly created, so db.commit() skips it via _created_set(); removed_listing_count written on a LISTING_REMOVAL does not push it to 2. Action is version 1 after issuance. Not described by the new sentence — left alone.
  - routes/appeals.py:73-89 — filing an appeal: no mark_dirty(action) -> no bump. Deliberately not covered by the new wording.
  - routes/appeals.py:118-126 — start-review: touches only the appeal -> no action bump; PRD §3.8's "nothing but the state and updated_at changes" stays true.
  - routes/appeals.py:133-134 (grant -> VACATED), :178-179 (deny -> UPHELD), :232-242 (escalation grant/FINAL_DENIED -> resolution_reason) -> all bump, all already covered by §2.10's "an appeal outcome resolved it".
  - routes/appeals.py:202-204 — escalate: appeal-only -> no action bump, consistent with §3.8's "The appealed action stays in UPHELD throughout".
  - services/notify.py:24, services/posture.py — supersession and posture cascades touch notifications/sellers/listings/holds, never the action row outside issuance.
(c) Wording adjustment: kept the claim scoped to the review operation and placed it inside the existing "whichever branch runs" clause (matching the unconditional mark_dirty), rather than a general statement like "any operation against an action bumps its version" — that broader phrasing would have falsely covered appeal filing and start-review, both of which leave the action's version untouched. The §2.10 cross-reference was worded as "the sense in which §2.10 counts a reviewed plan among the reasons" instead of asserting §2.10's list is exhaustive, since submission also bumps the version and §2.10 does not name it.

No PRD edit made for the other Step 7 items, each of which the PRD already determines uniquely and the implementation already follows: test_14 WATCHLIST -> RESERVE_HELD (PRD §3.9 verbatim; services/posture.py:150-158 matches exactly); test_16 / test_18 / fixtures.py base_severity_weight=12.00 (PRD §3.2's "between 0.50 and 8.00 inclusive" is verbatim in routes/policy_rules.py:24-26, and the legal 12.00 rebuild path — IP rule at 8.00 x repeat 1.00 x rights-owner 1.50, clamped ceiling 12.00, >= 12.00 -> ACCOUNT_SUSPENSION — is fully pinned by §3.6 and matches services/calc.py:139-156,179-188, with the RIGHTS_OWNER requirement matching §3.5's ERR_REPORTER_NOT_ELIGIBLE).

ORCHESTRATOR VERIFICATION: diffed PRD.md against PRD_FINALIZED.md — exactly one changed line (line 270, the §3.7 review paragraph), 4 diff output lines total. Both files 429 lines. The diff is non-empty, so Step 8 genuinely ran; per the known-good case a near-identical PRD_FINALIZED.md is legitimate here because Step 7 made zero implementation fixes.

ORCHESTRATOR PLAN for Step 9: Step 9 must never produce a byte-identical PRD_COMPLETED.md, and a single pass over 3169 lines of implementation across 26 modules has historically under-scanned. Step 9 will therefore run as three SEQUENTIAL passes over one shared workspace/PRD_COMPLETED.md, partitioned by implementation module: pass 1 = infrastructure + cross-cutting (app.py, middleware.py, guards.py, validators.py, response.py, serializers.py, errors.py, constants.py, clock.py, db.py, clock_routes.py) and it alone does the initial cp from PRD_FINALIZED.md; pass 2 = services (calc.py, posture.py, notify.py) — no cp; pass 3 = routes (sellers, listings, policy_rules, metrics, violations, enforcement, plans, appeals, holds, links) — no cp. Each later pass edits the file the previous pass left behind.

## Step 9: Complete PRD — 2026-09-05T01:25:00.000Z

Ran as three SEQUENTIAL module-partitioned passes over one shared workspace/PRD_COMPLETED.md, per the Step 8 plan. Pass 1 alone did the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden to copy and edited the file in place. Each later pass received the list of what earlier passes had already pinned, so no pin was duplicated or contradicted. Totals: 429 lines / 93,861 chars in -> 430 lines / 109,985 chars out (+16,124 chars, +17.2%); 44 diff hunks versus PRD_FINALIZED.md; 53 edits total = 43 ambiguity-pins + 10 mismatch-revisions.

### Pass 1 — infrastructure and cross-cutting (app.py, middleware.py, guards.py, validators.py, response.py, serializers.py, errors.py, constants.py, clock.py, db.py, routes/clock_routes.py)

429 -> 429 lines; 93,861 -> 98,803 chars (+4,942). 13 changed line-regions (PRD lines 17, 50, 51, 53, 54, 80, 82, 84, 88, 90, 92, 104, 123, 131, 148 — all inside §2.1–§2.9). 15 ambiguity-pins, 1 mismatch-revision.

- §2.1 — revise — ambiguity — role name matched exactly (unrecognised/differently-cased => 401); X-User-ID present-but-empty is also ERR_UNAUTHENTICATED — middleware.py:18,21
- §2.2 — revise — ambiguity — api_request_id is req_ + exactly 20 upper-case letters/digits — response.py:14,18
- §2.2 — revise — ambiguity — api_request_timestamp reads the host's real time, not the logical clock (the one such timestamp; clock-setting does not affect it) — response.py:32
- §2.2 — revise — ambiguity — every named resource field is always present in a projection, null when unset; internal bookkeeping never exposed — serializers.py:4-12
- §2.2 — revise — ambiguity — pagination meta keys appear only on list responses; object responses carry request id + timestamp alone — response.py:45,49
- §2.3 — revise — ambiguity — limit/offset must be whole numbers (empty/non-numeric/fractional rejected), negative offset rejected, out-of-range offset returns an empty page not an error — validators.py:43-61
- §2.3 — insert — ambiguity — total_count counts filtered rows before slicing; has_more = offset + len(page) < total_count — response.py:54,86-87
- §2.3 — insert — ambiguity — every list (default-ordered and the three inverted ones) breaks residual ties by server row-creation sequence — db.py:88-98
- §2.3 — insert — ambiguity — query parameters other than limit/offset/declared filters are ignored, not rejected — validators.py:50-61
- §2.4 — revise — ambiguity — id is a random v4 UUID in canonical lower-case 36-char hyphenated form — db.py:31
- §2.4 — insert — ambiguity — version/updated_at advance at most once per row per request however many fields or cascade steps touch it, the advance precedes body projection, updated_at is the logical-clock reading, and a row created by the request is returned at version 1 even if later steps rewrite it — db.py:74-85, response.py:69-82
- §2.4 — insert — ambiguity — clock-set returns an empty data object and may move the clock backwards as freely as forwards — clock.py:52, routes/clock_routes.py:20
- §2.6 — insert — ambiguity — rates/points/money are JSON numbers, scale not significant (92.50 => 92.5, 0.0100 => 0.01) — response.py:21-26
- §2.8 — insert — ambiguity — routing precedes authentication: unmatched path => 404 ERR_INVALID_REQUEST, wrong method => 405 ERR_INVALID_REQUEST (never an entity not-found code), regardless of headers; trailing slash insignificant — app.py:45,53-63
- §2.8 step 7 — revise — MISMATCH + ambiguity — datetimes accept any ISO 8601 UTC instant (Z or +00:00, any/no fractional width; naive or non-zero offset rejected) — the three-fractional-digit rule is rendering only, not an input requirement. Same bullet also pins: absent body => {}; non-JSON / non-object body rejected here; explicit null counts as absent; int fields reject booleans and accept integral floats; bool fields accept only real JSON booleans; decimal fields accept number or numeric string, reject booleans/non-finite, and are rounded half-up BEFORE bound comparison; trimmed length bounds measure trimmed but store as supplied — validators.py:19-30,64-67,104-181; clock.py:8-25
- §2.9 — insert — ambiguity — a body FK is resolved only when the field carries a non-empty string; missing/null/empty/wrong-typed references are not not-found conditions but step-7 ERR_INVALID_REQUEST, and dependent ownership checks are skipped — guards.py:53-60

Pass 1 deliberately did not add ERR_INTERNAL/500 from app.py:65-68 (unreachable in normal operation; adding it would require a new §5 catalogue row). It kept wording under-determined where impl paths diverge: it did NOT claim "a request that changes nothing skips the version bump" (several routes call db.mark_dirty unconditionally), and did NOT universalise "body FK resolution precedes shape validation" — routes/metrics.py:35-51 validates the whole payload before resolving the body seller_id, a genuine §2.8 step-4-vs-7 deviation it handed to pass 3.

### Pass 2 — services (calc.py, posture.py, notify.py)

98,803 -> 102,757 chars (429 lines unchanged); 8 paragraphs touched, 10 logical changes: 6 ambiguity-pins, 4 mismatch-revisions.

- §3.4 (health score, overshoot ratios) — insert — ambiguity — the four overshoot ratios are not rounded to any scale; carried at full precision (cap included) into the weighting, where the penalty chain's first rounding happens — services/calc.py:39-52, 86-94
- §3.4 (zero-volume clause) — revise — MISMATCH — PRD claimed "all four ratios are zero" when order_volume_final is 0; impl skips the penalty chain and forces 100.00 while odr_final/valid_tracking_rate (independent denominators) are still computed, stored and breach-tested, so an EXEMPT evaluation can list breached metrics and still score 100.00 — services/calc.py:82-98, 100-118
- §3.4 (the input set) — revise — ambiguity — input_window_start/input_window_end are a field-by-field min/max over the set, not the endpoints of one chosen row (observable only on nested windows, which cross-source snapshots permit) — services/calc.py:122-123
- §3.2 (listing cascades) — insert — ambiguity — the suppression cascade fires on ENTRY into SUSPENDED and on each fresh ACCOUNT_SUSPENSION issuance, not on every later recompute, so a listing created while suspended stays ACTIVE — services/posture.py:161-171
- §3.2 (listing cascades) — revise — MISMATCH — PRD lumped ban with action-driven removal; impl's ban removal writes no removal_policy_category and no removed_listing_count, only clearing suppressed_by_suspension — services/posture.py:23-27 vs 37-51
- §3.6 (the cascades) — insert — ambiguity — a LISTING-scope removal moves the cited item only if it is ACTIVE/SUPPRESSED; an already-removed or uncited item (and an already-empty catalogue) is not an error and leaves removed_listing_count at zero — services/posture.py:37-51
- §3.8 (a granted appeal) — revise — MISMATCH — PRD released "every hold still in ACTIVE" and restored listings unconditionally; impl releases only when the funds dimension actually lowers (leaves FULL_HOLD, or RESERVE_HELD -> NORMAL) and restores listings only when the seller actually leaves SUSPENDED — services/posture.py:169-170, 178-184
- §3.9 (funds posture lands) — revise — MISMATCH — RESERVE_HELD -> NORMAL releases carry INVESTIGATION_CLOSED except when the recompute was driven by a grant, which passes APPEAL_GRANTED; notice is per released hold with that hold's own amount — services/posture.py:120-123, 182-183
- §3.9 (sweeping cascade) — insert — ambiguity — sweep runs only on ENTRY into FULL_HOLD (later credits just sit in available_balance_cents); the supersession releases emit no FUNDS_RELEASED notice; the snapshotted risk_tier is invariably TIER_3; a zero balance still mints a zero-amount ACTIVE sweeping row and a zero-amount FUNDS_HELD notice — services/posture.py:70-98, 178-179
- §3.9 (leaving FULL_HOLD) — insert — ambiguity — APPEAL_GRANTED is the reason on EVERY FULL_HOLD exit (decay-driven included), and the exit emits exactly one aggregate FUNDS_RELEASED notice: amount = sum of released holds, entity = the released FULL_HOLD row, else the earliest-created released hold — services/posture.py:101-123, 180-181

Pass 2 also confirmed no call site ever passes recompute_points=False and force_suspension_cascade is used only via apply_enforcement in the issuance path, so §2.5's fixed three-step order holds everywhere — nothing to pin there.

### Pass 3 — routes (sellers, listings, policy_rules, metrics, violations, enforcement, plans, appeals, holds, links)

102,757 -> 109,985 chars; 429 -> 430 lines (+1 = the new §2.7 bullet); 27 edits = 22 ambiguity-pins, 5 mismatch-revisions. Passes 1–2's 26 edits verified untouched (diff against PRD_FINALIZED.md shows 48 hunks at that point).

- §2.1 — revise — MISMATCH — "Seller callers are never granted the operator-wide list endpoints, so no ownership filtering of query results is required" is false: the plan-of-action list admits Seller and IS silently ownership-narrowed, the policy-rule catalogue admits Seller and is not — routes/plans.py:119-124, routes/policy_rules.py:48
- §2.7 — revise — MISMATCH — "Four conflicts" -> "Five conflicts" — routes/links.py:41
- §2.7 — insert — MISMATCH — new fifth bullet: link adjudication vs the link's candidate_seller_id, the one conflict comparing X-User-ID to a persisted seller id — routes/links.py:41
- §2.8 step 6 — revise — MISMATCH — "the four conflicts of §2.7" -> "the conflicts of §2.7" — consistency with the above
- §3.1 — revise — ambiguity — top-link ranking's final tie-break is server creation sequence — routes/sellers.py:47-48
- §3.1 — revise — ambiguity — ACCOUNT_BANNED is written BEFORE the posture recomputation, so FUNDS_HELD is the later of the two notices; noted as the opposite of §3.8's ban path — routes/links.py:62-64
- §3.2 — revise — ambiguity — code uniqueness compared exactly, not case-insensitively as email is — routes/policy_rules.py:31
- §3.2 — revise — ambiguity — relist tests the listing's own state before the seller's posture (ERR_LISTING_NOT_REMOVED wins) — routes/listings.py:55-58
- §3.3 — revise — ambiguity — window_end <= window_start is a step-7 ERR_INVALID_REQUEST; and the whole payload is validated BEFORE seller_id is resolved, a deliberate departure from §2.8's step 4-vs-7 order — routes/metrics.py:35-51
- §3.3 — revise — ambiguity — shipments_with_valid_tracking > shipments_total is a step-7 ERR_INVALID_REQUEST — routes/metrics.py:47-48
- §3.4 — revise — ambiguity — auto-violation rule pool's final tie-break is creation sequence — routes/metrics.py:116
- §3.4 — revise — ambiguity — an empty candidate pool emits no HEALTH_BREACH notice and recomputes nothing; minting the auto-violation is the ONLY branch that runs the §2.5 recomputation, so a non-breaching evaluation leaves the balance un-redecayed — routes/metrics.py:111-136
- §3.5 — revise — ambiguity — the three coherence rules are evaluated in the stated order (ERR_LISTING_REQUIRED_FOR_SCOPE beats ERR_REPORTER_NOT_ELIGIBLE) — routes/violations.py:41-46
- §3.6 — insert — ambiguity — both cascades dispatch on the post-override action_type, never ladder_rung_computed; overridden WARNING->LISTING_REMOVAL removes, overridden LISTING_REMOVAL->ACCOUNT_SUSPENSION removes nothing and keeps removed_listing_count 0 — routes/enforcement.py:100-107
- §3.6 — revise — ambiguity — re-acknowledging an ACKNOWLEDGED action yields ERR_INVALID_STATE, not ERR_ACTION_NOT_APPEALABLE_STATE — routes/enforcement.py:149-152
- §3.7 — revise — ambiguity — only the POA content THRESHOLDS are step-8 ERR_POA_INCOMPLETE; wrong TYPES (non-string root_cause, non-array measures, non-string element) are step-7 ERR_INVALID_REQUEST — routes/plans.py:47-54
- §3.7 — revise — ambiguity — submitting against an action whose plan already reached ACCEPTED/REJECTED is ERR_INVALID_STATE, reported ahead of the §2.10 version check — routes/plans.py:65-71
- §3.7 — revise — MISMATCH — with review_notes omitted the POA_DECISION rationale is the literal "Plan of action review decision: " + decision, not null — routes/plans.py:172-176
- §3.8 — revise — MISMATCH — on filing, ERR_APPEAL_ALREADY_EXISTS preempts ERR_ACTION_NOT_APPEALABLE_STATE (departure from §2.8's 10-before-14) — routes/appeals.py:50-55
- §3.8 — revise — ambiguity — a denial_reason supplied with GRANTED is discarded, field stays null — routes/appeals.py:170-175
- §3.8 — revise — ambiguity — the grant cascade's FUNDS_RELEASED notices precede the APPEAL_DECISION/ESCALATION_DECISION notice — routes/appeals.py:171-173, 237-248
- §3.8 — revise — ambiguity — the escalation's rationale/denial_reason overwrite the first-level values; decided_at is not touched — routes/appeals.py:232-239
- §3.8 — revise — ambiguity — the final-denial ban recomputes posture FIRST, then writes ACCOUNT_BANNED ahead of ESCALATION_DECISION — routes/appeals.py:241-248
- §3.9 — revise — ambiguity — external_reference is type-checked but persisted nowhere; a credit recomputes neither dimension and never re-sweeps a FULL_HOLD seller — routes/sellers.py:146-159
- §3.9 — revise — ambiguity — reserve_basis NONE is refused with ERR_INVALID_REQUEST, like hold_type FULL_HOLD — routes/holds.py:46
- §3.9 — revise — ambiguity — coverage_end <= coverage_start is a step-7 ERR_INVALID_REQUEST, decided before the separation test — routes/holds.py:49-50
- §3.9 — revise — ambiguity — a forfeited_amount_cents of zero is legal: hold -> FORFEITED, whole amount back to available, lifetime_debited_cents unchanged — routes/holds.py:159, 167-177

Pass 3's disposition of the four items pass 2 flagged: (1) enforcement.py:100-107 cascade dispatch — resolved, §3.6 "The cascades." now opens by pinning action_type as the dispatch key with both override directions spelled out; (2) sellers.py:143-157 credit never recomputes — resolved in §3.9's credit paragraph, worded to reinforce rather than restate pass 2's "the cents simply sit there"; (3) links.py:62-64 vs appeals.py:243-244 notice order — resolved on both sides (§3.1 pins notice-then-cascade so FUNDS_HELD is second and cross-references §3.8; §3.8 pins recompute-then-ACCOUNT_BANNED-then-ESCALATION_DECISION, plus the grant-path ordering); (4) metrics.py:35-51 shape-before-lookup — resolved, §3.3 states the deviation explicitly as scoped to that one endpoint so it cannot be read as overriding §2.8 generally. Two items were deliberately left alone as already-determined: filter values matching no row yielding an empty page (follows from "equality filters" plus pass 1's out-of-range-offset pin), and the step-10 internal order in manual hold release (§3.9's existing prose already lists ACTIVE before hold_type, matching the implementation).

ORCHESTRATOR VERIFICATION: PRD_COMPLETED.md is 430 lines / 109,985 chars versus PRD_FINALIZED.md's 429 / 93,861 — NOT byte-identical (44 diff hunks), so the scan genuinely ran rather than degenerating into a bare cp. The file's tail is intact (ends on the final §5 error-table row). No "scaffold" token appears anywhere in it. Neither Step 8 nor any Step 9 pass wrote to implementation/, test_suite/ or test_helpers/, so the verified 8-round green sweep (126/126 in all 8 rounds) remains valid for the shipped code.

PIPELINE COMPLETE. All nine steps done; workspace/PRD_COMPLETED.md written.
