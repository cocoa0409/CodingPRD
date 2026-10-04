# Worklog — task_3350_pre_sale_home_improvement_advance_repayment_closing

## Step 1: Create Task Directory — 2026-10-01T04:55:00.000Z

Task directory was pre-allocated by the command invocation: `tasks/task_3350_pre_sale_home_improvement_advance_repayment_closing/workspace/` verified to exist. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T05:23:00.000Z

(Executed as detached `claude -p` child session because the Agent tool rejects the session model on the subagent path; the child completed all writes before exiting with a final-turn model error. Orchestrator verified artifacts directly.)

Files written (verified on disk by orchestrator, all valid YAML, no truncation):
- SCAFFOLD.yaml (58,388 bytes): top-level keys scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors. 11 entities, 7 state machines, 9 calculations, 12 validations, 58 endpoints, 18 errors. No scaffold_difficulty_design / scaffold_corner_design keys present (correct).
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (79,416 bytes): single top-level key scaffold_difficulty_design; 9 rules (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, +1) with 18 total instances.
- SCAFFOLD_CORNER_DESIGN.yaml (109,894 bytes): single top-level key scaffold_corner_design; 9 sections (entities 11, state_machines 8, calculations 4, validations 7, endpoints 3, errors 2, roles 3, cross_cutting_complexity_layers 3, consistency_model 1) with 42 total instances.

Note: 58 endpoints exceeds the 40-endpoint impl-gen overshoot threshold; orchestrator will verify Step 6 files on disk itself and require incremental writes.

## Step 3: Copy Shared Files — 2026-10-01T05:25:00.000Z

Copied ./INSTRUCTION.md to tasks/task_3350_pre_sale_home_improvement_advance_repayment_closing/workspace/INSTRUCTION.md.

## Step 4 (attempt, interrupted): Generate PRD — 2026-10-01T05:39:00.000Z

First child session wrote PRD.md through §2.10 then died on the endpoint outage; a resumed session continued through §3.4 (146 lines) before the endpoint went offline entirely. Orchestrator inspection on resume (08:26Z) confirmed the document was missing the per-endpoint coverage required for a 58-endpoint scaffold — judged truncated/incomplete. Per recovery protocol the partial PRD.md was deleted and Step 4 is rerun from scratch.

## Step 4: Generate PRD — 2026-10-01T08:45:15.000Z

(Subagent via Agent tool, foreground.) PRD generation complete. All three hard contracts pass.

**Output**: workspace/PRD.md — 254 lines (~40 KB), plus 2 lines net from orchestrator constant-pinning patch below.

**Section list**
- 1. Introduction (2 paragraphs)
- 2. Global Specifications: 2.1 RBAC (all 6 roles, identity binding per role), 2.2 API Response Structure (verified byte-identical to canonical section-2.2-response-structure.md), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Identity/Timestamps/Versioning + left-to-right nested path validation, 2.5 Money/Precision/Rounding (integer cents, round-half-up per line, floor for caps), 2.6 Program Clock (startup 2026-09-01T00:00:00Z), 2.7 OCC, 2.8 Validation Order (all 12 priorities in explicit order), 2.9 Case Posture gate
- 3. Business Logic: 3.1 Reference Data, 3.2 Case Intake & Eligibility, 3.3 Improvement Plan, 3.4 Vendor Engagement & Capacity, 3.5 Disbursements & Change Orders, 3.6 Disputes & Readiness, 3.7 Listing & Market Events, 3.8 Closing Statement & Settlement
- 4. Endpoint Definitions — exactly 58 table rows, 4 columns
- 5. Error Code Catalogue — 18 errors, 2 columns

**Contract reports**
- Field coverage: all 66 entity-field names, all endpoint input/query identifiers, and all 9 path params appear in backticks. PASS
- Rule coverage: 12/12 validation priorities; 2/2 OCC rules; all transitions of all 7 state machines with preconditions + side effects; 8/8 calculations with pinned constants verbatim; endpoint side effects and applies_to scopes surfaced. PASS
- §3 path purity: 448 backticked tokens scanned, 0 starting with /, 0 bare HTTP methods. PASS

**Subagent flag**: scaffold referenced MIN_EQUITY_RATIO (eligibility) and LATE_GRACE_DAYS (completion deadline) without values; PRD initially named them symbolically.

**Orchestrator adjudication (pre-Steps-5/6 drift prevention)** — verified against both design indexes before pinning:
- MIN_EQUITY_RATIO := 1.10. Constraint source: corner instance eligibility_approve_with_insufficient_equity_returns_eligibility_failed requires proceeds/value = 81M/80M = 1.0125 to FAIL; every happy-path recipe uses 100M/80M = 1.25 or 110M/90M ≈ 1.222 which must PASS. 1.10 is the round value satisfying all. (Design indexes pin no other value.)
- LATE_GRACE_DAYS := 7. No design instance asserts a late completion (every /complete runs at clock 2026-09-01 against end_dates 09-10/09-20, always on-time for any non-negative grace), so any small positive value is safe; 7 chosen.
- ADVANCE_LIMIT_RATE was already pinned at 0.15 in SCAFFOLD.yaml §1.3 constants; PRD already carried it verbatim.
- Applied to: SCAFFOLD.yaml (constants block + 3 inline references), workspace/PRD.md (§3.2 eligibility sentence, §3.4 engagement creation sentence). Design-index files untouched (they never named the symbols).

## Step 5: Generate Unit Tests — 2026-10-01T09:23:55.000Z

(Subagent via Agent tool, foreground. Orchestrator spot-verified claims against disk: 9 helper files + 8 suite files present; 74 test functions; 74/74 "Design:" tags; zero skip/xfail; constants.py pins 1.10/0.15/7 + fee rates + clock 2026-09-01T00:00:00Z; the 9550→9500 re-derivation and listing_window_days=30 override confirmed in the shipped files.)

Generation complete. All static audits pass: 74 tests, 74/74 Design tags resolve to real instances, 110/110 quoted PRD spans verified verbatim against PRD.md, zero skip/xfail markers, no scaffold leakage.

Files written: test_helpers/ (9 files, 50.9 KB): __init__.py, types.py (6.7 KB — 11 entity TypedDicts), api_client.py (10.2 KB — 64 endpoint methods), api_errors.py (18 error IDs + HTTP map), assertions.py, factories.py, constants.py (pinned: MIN_EQUITY_RATIO 1.10, ADVANCE_LIMIT_RATE 0.15, LATE_GRACE_DAYS 7, fee rates 0.03/0.01/0.005/0.002, clock 2026-09-01T00:00:00Z), test_users.py, fixtures.py (17.2 KB — composite pipelines: eligible case → approved project → plan approved → FUNDED → IN_PROGRESS → READY_TO_LIST → LISTED → CLOSED_SOLD/CLOSED_UNSOLD, all OCC writes fetch a fresh case version). test_suite/ (8 files, 78.4 KB): conftest.py + 7 test files, 74 tests (17/11/8/12/8/15/3).

Coverage: Queue A (difficulty): 17 of 18 instances translated, 34 tests. Queue B (corner): 40 of 42 non-stub instances translated, 40 tests.

Instances skipped (PRD-first filter):
- Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_engagement_create — asserts ERR_CASE_FROZEN on engagement create, but PRD §2.9 exhaustively limits the FROZEN gate to homeowner cancel/withdraw actions; engagement create is a ListingAgent op for which the PRD derives ERR_PROJECT_NOT_APPROVED instead. (Recipe's FROZEN fixture was also unreachable — it posts LISTED from SCOPE_PLANNING.)
- Corner/entities/concierge_case_create_missing_listing_agreement_signed_returns_invalid_request — PRD §3.2 says both listing-agreement attestations "default to false when not supplied"; omission cannot be a 400.
- Corner/entities/advance_total_cents_is_computed_from_disbursements_not_input — PRD §3.2 explicitly permits seeding advance_total_cents at create, contradicting the instance's "client-supplied value is ignored" premise (and its asserted 5,000,000 ignores the project-approval ledger contribution).

Design-index literals re-derived against the PRD (PRD wins):
1. vendor_quality_score_dual_variant_recovery_vs_penalty: asserted 9550 → 9500, because PRD caps the +50bp recovery at 10000 (min(10000, 10050) − 500).
2. state_vs_business_fiscal_on_disbursement_approve: recipe passed a stale expected_case_version at trigger (would 412); re-derived to the fresh version so the asserted ERR_ADVANCE_LIMIT_EXCEEDED fires.
3. advance_limit_exact_boundary: recipe's 14,999,999 disbursement on top of a 14,999,999 project approval would double-consume headroom; re-derived to project 14,999,999 + 1-cent (X) and 2-cent (X+1) disbursements.
4. advance_total_cents_conserved_on_void and derived_field_reconciliation_advance_total_after_void: absolute 0 / 5,000,000 assertions ignored the project-approval contribution; re-derived to relative baseline±amount assertions (the PRD-pinned conservation).
5. case_cancel_cascade_projects_engagements (and its corner twin): the "LISTED case with APPROVED project + SCHEDULED engagement" fixture is unreachable (LISTED requires all projects VERIFIED/CANCELLED); re-derived to cancel from SCOPE_PLANNING, which the PRD names with the identical cascade side effect.
6. reserved_crew_days_conserved_on_engagement_cancel: start→cancel is invalid (IN_WORK can't be cancelled); re-derived to cancel-from-SCHEDULED (reserved stays 0) plus an IN_WORK-cancel ERR_INVALID_STATE test.
7. engagement_start_requires_project_approved: a SCHEDULED engagement on a DRAFT project is unreachable (create gates first); translated as engagement-create rejection on DRAFT and PROPOSED projects, the reachable form of the same PRD rule.
8. All LISTED-dependent fixtures (listing_window_days_boundary, listing_event_sequence_closed_interval, listing_event_records_price_reduced, etc.): recipes posted LISTED while the case was in SCOPE_PLANNING; re-derived through the full READY_TO_LIST pipeline (plan approve → disbursement approve → engagement start → complete → verify → LISTED).
9. Waive fixture: set market_risk_flag: true on both the LISTED and CLOSED_UNSOLD events so the "most recent listing event recorded before closed_at" precondition holds under either strict or inclusive reading.
10. disbursement_release_blocked_by_active_dispute: dispute filed after on-time completion (an IN_WORK engagement would move to DISPUTED and fail the state check first), so only ERR_DISPUTE_ACTIVE can fire.
11. Case-create test asserts presence/type of version but not == 1 — the PRD never pins the initial version value.
12. (Orchestrator addendum) Design note "LISTED 2026-09-01, CLOSED_UNSOLD 2026-10-15 (45 days late, 2 months)" is unreachable under the PRD-pinned default listing_window_days=180 (44 < 180 → ERR_LISTING_WINDOW_NOT_ELAPSED). Step 5 re-derived: fixtures pass listing_window_days=30 at case create (a PRD-declared optional input), giving months_late = ceil((44−30)/30) = 1; asserted fees 75,000 / 10,000 / net 5,085,000 all verified PRD-consistent by the orchestrator.

Test suite was not executed (no implementation exists yet, per instructions).

## Step 6: Generate Implementation — 2026-10-01T10:02:51.000Z

(Subagent via Agent tool, foreground. Orchestrator verified on disk: 21 files; Flask url_map reports exactly 58 routes (33 POST, 25 GET); calc.py pins all constants 1.10/0.15/7d/0.03/0.01/0.005/0.002/500/200/50 bp/window 180 via Decimal; start.sh boots on $PORT and answers the clock endpoint correctly; in-memory store only, no seeding. Note: subagent's per-file byte-size claims did not match disk — file list and route count do; treat size figures as unreliable.)

Files written (21 files) under workspace/implementation/: start.sh (foreground, $PORT, 0.0.0.0, guarded dep install), requirements.txt, app.py, errors.py (19 error IDs), db.py (in-memory dicts, logical clock 2026-09-01T00:00:00Z, UUID ids), envelope.py, validate.py, auth.py (6 roles), calc.py, logic.py, routes/ (clock, agents, vendors, cases, projects, engagements, disbursements, change_orders, disputes, listing_events, closing). 58/58 endpoints.

Subagent smoke verification (its own runs, fresh server each): happy path eligibility → plan (OCC 412) → engagement → FUNDED → IN_PROGRESS → on-time completion → READY_TO_LIST → LISTED/OFFER_ACCEPTED/CLOSED_SOLD → variant-A finalize (fee 15000, net 515000 on 500000) → pay; variant-B unsold (window-not-elapsed 409, months_late=1 → fee 6000, late 800, net 406800); dispute lifecycle; frozen gates; duplicate LISTED; vendor-ownership 403.

PRD ambiguities resolved by implementer (candidates for Step 8/9 pinning):
1. required_crew_days: computed ceil((end_date − start_date)/86400) over half-open span; exposed as engagement field.
2. Plan-approve when posture ≠ OPEN: ERR_INVALID_STATE (409) for RESTRICTED and FROZEN.
3. Release vs DISPUTED engagement precedence: state check (priority 4) before ERR_DISPUTE_ACTIVE (priority 9) per §2.8 order.
4. Case cancel from LISTED with uncovered RELEASED disbursements: ERR_INVALID_STATE (409).
5. Waive market-risk gate: strict reading (event_at < closed_at, latest by event_at then insertion order); flag on the closing event itself does not qualify.
6. On-time +50 bp: any dispute record referencing the engagement (any status) suppresses the bonus.
7. Version starts at 1, +1 per mutation; PLAN_APPROVED→FUNDED auto-flip rides the disbursement-approve single bump; posture changes bump version only when the value changes.
8. DRAFT closing statement: payoff_basis and advance_repayment_cents at creation; four fee fields null until finalize; advance_repayment recomputed at finalize.
9. Body-FK chain mismatches → ERR_NOT_FOUND (404).
10. Timestamps use the logical clock.
11. Pagination out-of-range clamps into [1,100]/[0,∞); non-integer → ERR_INVALID_REQUEST; unknown trade/status filters return empty lists.

## Step 7: Test-Fix Iteration Loop — 2026-10-01T10:37:01.000Z

(A first Step 7 subagent ran the baseline sweep at 10:07Z then died on the host-session interruption without analyzing; a second foreground subagent owned the loop from there. Orchestrator verified the final claims against disk: results.{1..8}.json all show 73/73 passed / 0 failed; 0 implementation source files newer than the results; the deleted test is absent; test count is 73; no skip/xfail markers anywhere.)

All 8 rounds pass 73/73 with zero stray processes and all 8 results.*.json evidence files in place.

**Iterations run:** 2 sweeps total — baseline (45/74, 29 deterministic failures) + 1 fix round → clean 8-round sweep (73/73 × 8, no flakiness).

**Root cause of 26/29 failures (one test-side bug):** test_helpers/fixtures.py setup_engagement_scheduled created the VendorEngagement while the case was still SCOPE_PLANNING. Per PRD §3.4 ("when a project's first engagement becomes SCHEDULED the project itself advances automatically from APPROVED to SCHEDULED"), that flipped the only project out of APPROVED, so the follow-up plan approval was correctly rejected with ERR_NO_APPROVED_PROJECTS (PRD §3.3 gate: "At least one project must be in APPROVED status"). PRD §3.4 narrates "With the plan approved, the ListingAgent engages vendors" — the fixture order was backwards.

**Tests deleted (1):**
- test_engagement_spanning_two_windows_is_rejected (test_03) — unique-derivability collapse. The test read "covering the engagement" as full containment and asserted ERR_VENDOR_CAPACITY_EXCEEDED, but PRD §3.4's only operational definition is the verbatim overlap formula ("start_date falls strictly before the window's window_end and end_date falls strictly after the window's window_start"), under which the [09-10, 09-20) engagement IS covered by window [09-01, 09-15) and the start succeeds. Both readings are articulable from the same sentence (scaffold driver: Difficulty/resource_temporal_overlap/vendor_capacity_window_half_open_overlap).

**Fixes applied to test_helpers/:**
- fixtures.py — setup_engagement_scheduled(..., plan_approved=False): when True, approves the plan BEFORE creating the engagement (PRD narrative order); default preserves SCOPE_PLANNING for the PRD-valid cancel-cascade tests in test_07. setup_ready_to_list_case now uses plan_approved=True and dropped its internal approve_plan call.
- factories.py — resolve_dispute_payload default "VENDOR_FAULT" → "RESOLVED_VENDOR_FAULT" (PRD §3.6 names the resolution input values verbatim).
- types.py — DisputeResolution enum values corrected to RESOLVED_VENDOR_FAULT/RESOLVED_HOMEOWNER_FAULT.

**Fixes applied to test_suite/:**
- test_04_disbursements_change_orders.py — 7 setup sites switched to setup_engagement_scheduled(plan_approved=True), redundant approve_plan calls and import removed (the double-approval would now correctly fail ERR_INVALID_STATE).
- test_03_engagements_capacity.py — test_cancel_engagement_with_released_disbursement_rejected same fixture fix; its final assertion relaxed to validate_error_is_one_of([ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT, ERR_INVALID_STATE]) — permitted error-precedence relaxation: a RELEASED disbursement implies the engagement left SCHEDULED (release requires IN_WORK/COMPLETE_*), and PRD §2.8's priority list ranks state-appropriateness fourth while never ordering the released-funds check, so both errors are PRD-consistent serializations.
- test_05_disputes_posture.py — 3 inline payloads: "VENDOR_FAULT"→"RESOLVED_VENDOR_FAULT" (×2), "HOMEOWNER_FAULT"→"RESOLVED_HOMEOWNER_FAULT" (×1), matching PRD §3.6 verbatim.

**Fixes applied to implementation/:** none — every failure traced to test-side artifacts; the implementation was PRD-faithful on all 29 paths (spot-verified the project auto-advance, plan-approval gate, capacity overlap formula, dispute resolution enum, and cancel precedence against PRD §2.8/§3.3–3.6).

**Evidence:** workspace/implementation/results.{1..8}.json regenerated from the final clean sweep (all 73/73) and left in place.

**Orchestrator note for Step 8 (test-side-fix dominance):** all fixes were test-side, so a green sweep here proves tests match code, not PRD vs code. The Step 8 focus list: (a) the deleted containment-reading test → PRD §3.4 capacity-coverage sentence admits two readings; (b) the relaxed cancel-with-released-disbursement precedence → PRD never orders the released-funds check vs the state check; (c) unasserted sibling paths worth pinning: engagement spanning two windows (accepted under overlap reading), engagement create on FROZEN case (impl behavior untested since the difficulty instance was skipped at Step 5), plan-approve under RESTRICTED/FROZEN posture (impl chose ERR_INVALID_STATE), body-FK chain mismatch → 404, pagination clamping.

## Step 8: Finalize PRD — 2026-10-01T10:49:49.000Z

(Subagent via Agent tool, foreground. Orchestrator verified: diff PRD.md→PRD_FINALIZED.md is exactly 14 changed lines (7 paragraph-lines out / 7 in), no new sections; 0 implementation or test files modified after the clean sweep — sweep evidence remains valid.)

PRD_FINALIZED.md written (254 lines vs PRD.md's 254 — all edits inline; 7 of 254 paragraph-lines touched, ~2.8%). No new sections; every edit traces to a <step_7_diff> item.

Changes (section — insert|revise — what — impl evidence):
- §2.3 — insert — out-of-range limit/offset are clamped (limit→[1,100], offset→[0,∞)); non-integer values rejected with ERR_INVALID_REQUEST — implementation/validate.py:101-112 (page_params), consumed globally via implementation/logic.py:54-59.
- §2.4 — insert — body-carried FK chains (concierge_case_id/improvement_project_id/vendor_engagement_id on disbursement & dispute creation; improvement_project_id/vendor_engagement_id on change-order creation) get the same existence-and-nesting validation as URL paths; chain mismatch → ERR_NOT_FOUND 404 — implementation/routes/disbursements.py:35-39, implementation/routes/disputes.py:45-49, implementation/routes/change_orders.py:32-35.
- §2.8 — insert — in engagement cancellation, the ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT guard is evaluated after the state check and after the FROZEN check (impl order: state→FROZEN→released-funds; since RELEASED implies the engagement left SCHEDULED, the state check fires first in practice) — implementation/routes/engagements.py:166-181 (sole raiser, grep-confirmed).
- §2.9 — revise — plan approval under RESTRICTED/FROZEN posture is rejected with ERR_INVALID_STATE (HTTP 409) — implementation/routes/cases.py:130-131.
- §3.3 — revise — same gate pinned at its operative transition sentence (mirrors §2.9 wording) — implementation/routes/cases.py:130-131.
- §3.4 — insert — engagement creation is gated only on the referenced project's APPROVED status; neither the case's lifecycle status nor its posture is consulted (creation succeeds while the case is still SCOPE_PLANNING and under any posture) — implementation/routes/engagements.py:41-70.
- §3.4 — insert — capacity "coverage" requires overlap only, not containment (spanning engagements start successfully); the full required_crew_days is reserved against a single window, the earliest-created qualifying OPEN window (creation order breaks ties) — implementation/logic.py:151-165, implementation/routes/engagements.py:110-124.

Pure test-side items in the diff needed no PRD change: the RESOLVED_VENDOR_FAULT/RESOLVED_HOMEOWNER_FAULT enum values were already pinned verbatim in §3.6, and the fixture ordering bug (engagement created before plan approval) was a fixture artifact — PRD §3.4's narrative order already matched intent.

Per-edit pre-edit search log:
1. Pagination clamping — (a) subject: out-of-range/non-integer limit/offset. (b) enumerated: validate.py:101-112 (sole impl), logic.py:54-59 (sole consumer); grep confirmed all list routes (cases, vendors, capacity-windows, engagements, disbursements, change-orders, disputes, listing-events, project/vendor/case-scoped lists) return via list_response, so clamping is uniform. (c) wording kept endpoint-generic ("list endpoints") to match the shared helper.
2. Body-FK chain → 404 — (a) subject: request-body related-resource validation. (b) enumerated every get_or_404 callsite repo-wide: body-FK chains exist only in disbursements.py:35-39, disputes.py:45-49, change_orders.py:32-35; engagements.py:45-46 resolves project+vendor as independent FKs (no chain possible); all other callsites are URL-path IDs already covered by §2.4. (c) scoped the sentence with "names a resource together with its parent or a longer ancestor chain" so engagement creation cannot be mis-read as chain-checked.
3. Cancel-engagement released-funds ordering — (a) subject: check ordering in engagement cancellation. (b) enumerated: engagements.py:163-185 (state→FROZEN→released); grep proved ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT is raised nowhere else; cross-checked the sibling released-funds guard in cases.py:148-154 (case-cancel from LISTED → ERR_INVALID_STATE) and scoped the new sentence to engagement cancellation only; §3.4's narrative lists conditions without claiming order, so §2.8 (the ordering owner) received the pin. (c) appended to the fifth item rather than renumbering "Sixth…Twelfth".
4. Plan-approval posture error (§3.3) — (a) subject: non-OPEN posture at plan approval. (b) enumerated all posture reads in routes/: the only != "OPEN" gate is cases.py:130-131; the four other gates are FROZEN-only ERR_CASE_FROZEN checks (projects.py:124, engagements.py:171, cases.py:146, disputes.py:151), none reachable by plan approval. (c) named both RESTRICTED and FROZEN (impl checks != "OPEN"); deliberately left the posture check's position among the other plan-approve checks unpinned (not a Step 7 item).
5. Same gate (§2.9) — (a)/(b) identical enumeration to edit 4. (c) mirrored edit 4's phrasing so the two sections cannot diverge.
6. Engagement-creation gating — (a) subject: what gates POST /concierge/engagements. (b) enumerated engagements.py:41-70 — role, body JSON, project/vendor 404, project-status, price/date validation; no case lookup at all; cross-checked §2.9's exclusive FROZEN-blocked list and the Step 7 root-cause (fixture created the engagement while the case was SCOPE_PLANNING and the impl accepted it). (c) pinned both non-gates (lifecycle status AND posture) since the impl consults neither.
7. Capacity coverage semantics — (a) subject: window coverage/selection/reservation at start. (b) enumerated logic.py:151-165 (overlap formula, OPEN-only, headroom, (created_at, _seq) sort), engagements.py:110-124 (sole find_capacity_window caller; full reservation on the single returned window), logic.py:168-179 + callers engagements.py:182/cases.py:163 (release uses the stored window — untouched by the wording), vendors.py:46-65 (windows born OPEN). (c) added "earliest-created (creation order breaks ties)" to match the sort key exactly; scoped strictly to the start path.

## Step 9: Complete PRD — 2026-10-01T11:09:01.000Z

(Subagent via Agent tool, foreground. Orchestrator verified: PRD_COMPLETED.md genuinely differs from PRD_FINALIZED.md (32 changed lines, 16 paragraph-lines — not a cp-no-op); 0 implementation/test source files modified after the clean sweep, so the 73/73 × 8 evidence stands; all 8 results.*.json still present and passing.)

File: workspace/PRD_COMPLETED.md
Size: PRD_FINALIZED.md 254 lines / 42,854 chars → PRD_COMPLETED.md 254 lines / 46,627 chars (+3,773 chars, +0 lines — all in-paragraph inserts/revisions across 16 paragraph-lines; two edits landed in the same §3.4 paragraph).

Counts: 17 ambiguity-pins, 0 mismatch-revisions. The FINALIZED PRD was already well-aligned (advance-limit clamp, cost_overrun's max(0,Σdeltas) − approved_cost quirk, capacity overlap/earliest-created rules, fee variants, OCC endpoints all pinned correctly); every change pins prose silence against what implementation/ does.

DEAD-CODE findings: none. All gate helpers are wired: enforce_vendor_ownership (engagements.py:104,142; change_orders.py:36; disputes.py:50), find_capacity_window (engagements.py:110), release_reservation (engagements.py:182; cases.py:163), maybe_project_complete (engagements.py:159), maybe_case_ready (projects.py:114,128; disputes.py:140,157), recompute_posture (disputes.py:62,118,138,155; listing_events.py:95), engagement_has_dispute (engagements.py:149), compute_advance_limit (cases.py:94), compute_fees (closing.py:86). All 19 error IDs in the catalog are raised.

Changes (section — action — class — what — impl ref):
1. §2.3 — insert — ambiguity — list ties broken by creation order; has_more = offset + returned < total_count; filter params exact-match, unknown values yield empty 200 pages — logic.py:49-59, envelope.py:31, vendors.py:40-42
2. §2.4 — insert — ambiguity — version starts at 1; naive request datetimes interpreted as UTC — logic.py:17-24, validate.py:82-94
3. §2.6 — insert — ambiguity — created_at/updated_at/api_request_timestamp all read the logical clock — logic.py:20-21, envelope.py:17, db.py:36-37
4. §2.8 — insert — ambiguity — ownership checks after existence/before state; enumerated non-negative vs positive (≥1) integer fields; window_end strictly after window_start; end_date == start_date accepted; undefined path 404, unsupported method 405 with ERR_NOT_FOUND — auth.py:61-69, validate.py:39-56, vendors.py:53-54, engagements.py:52-53, app.py:24-30
5. §2.9 — insert — ambiguity — "latest listing event" = most recently recorded, regardless of event_at — logic.py:94-100
6. §3.2 — insert — ambiguity — new case has advance_limit_cents and listing_price_target_cents null — cases.py:48,52
7. §3.3 — insert — ambiguity — project born with approved_cost_cents null, cost_overrun_cents 0; creation not gated on case status/posture — projects.py:42-56
8. §3.3 — insert — ambiguity — plan-approval version check ordered after case-state check, before approved-projects/headroom/posture checks — cases.py:119-131
9. §3.4 — insert — ambiguity — required_crew_days = ceil((end−start)/86400), 0 when dates coincide, computed at creation and returned on the engagement — logic.py:143-148, engagements.py:61
10. §3.4 — insert — ambiguity — window becomes FULL when reserved reaches capacity, returns to OPEN when cancellation drops below — engagements.py:119-122, logic.py:168-179
11. §3.4 — revise — ambiguity — on-time +50bp suppressed by any dispute record regardless of status (incl. WITHDRAWN/terminal) — engagements.py:149-152, logic.py:137-138
12. §3.5 — insert — ambiguity — sequence_in_case starts at 1, +1 per created disbursement including voided ones — disbursements.py:42
13. §3.5 — insert — ambiguity — disbursement-approval version check after disbursement state check, before engagement-state/headroom checks — disbursements.py:86-97
14. §3.7 — revise — ambiguity — PRICE_REDUCED/DELISTED accepted only while LISTED or UNDER_CONTRACT, else ERR_LISTING_EVENT_ORDER — listing_events.py:64-66
15. §3.7 — insert — ambiguity — case-cancel cascade releases cancelled engagements' reserved crew-days — cases.py:161-165
16. §3.8 — insert — ambiguity — DRAFT statement's program_fee_cents/late_fee_cents/vendor_holdback_cents/net_repayment_cents null until finalize — closing.py:46-56
17. §3.8 — revise — ambiguity — waive gate: most recent event with event_at strictly before closed_at, ties broken by recording order — closing.py:126-138

## Pipeline Complete — 2026-10-01T11:09:01.000Z

Final tree: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml; worklog.md; test_helpers/ (9 files) + test_suite/ (73 tests); workspace/INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md; workspace/implementation/ (Flask, 58/58 endpoints, in-memory store) with results.{1..8}.json all 73/73 passing from the final clean 8-round per-test-server sweep.
