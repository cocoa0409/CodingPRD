## Step 1: Create task directory — 2026-09-06T02:05:04.866141367Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2987_termite_bond_wood_destroying_organism_inspection and its workspace/ subdirectory (pre-assigned path from the orchestrator invocation; no index scan performed). Also created per-step scratch dirs under .scratch/.

## Step 2: Generate scaffold — 2026-09-06T04:09:59.37436792Z

All three scaffold artifacts are complete and lint-clean.

Files written (all under tasks/task_2987_termite_bond_wood_destroying_organism_inspection/):

| File | Lines | YAML parse | Top-level key |
|---|---|---|---|
| SCAFFOLD.yaml | 3196 | OK (yaml.safe_load) | scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — no scaffold_difficulty_design / scaffold_corner_design keys |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 2241 | OK | scaffold_difficulty_design only |
| SCAFFOLD_CORNER_DESIGN.yaml | 5747 | OK | scaffold_corner_design only |

Domain model (§1.0–§1.7): 12 entities, 48 endpoints, 8 state machines, 2 OCC concurrency rules, 12 calculations, 44 priority-ordered validations, 58 error codes, 6 roles (ComplianceOfficer, BranchManager, FieldInspector, Applicator, ClaimsAdjudicator, PropertyOwner; three of them entity_backed). Logical clock endpoints included, startup default 2026-08-01T00:00:00Z.

Instance counts: §1.8 = 18 instances (9 hard-reasoning rule_ids x 2). §1.9 = 100 instances across the nine guide sections — entities 12, state_machines 19, calculations 16, validations 19, endpoints 6, errors 12, rbac 6, cross_cutting_complexity_layers 8, consistency_model 2 — of which 74 carry full test_recipe chains and 26 are excluded_because: stubs (all citing §1.8 instances that exist by name; none carries a forbidden test_recipe).

Lint verdict, verbatim (first run, no iteration needed):
    VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
with Calls scanned (§1.8+§1.9): 1372, §1.8 instances scanned: 18, §1.9 instances scanned: 74.

Other checks: all 118 instance names unique across both design files; all 58 declared error codes are triggerable by at least one §1.8/§1.9 instance (verified programmatically, zero uncovered); the difficulty directive does not appear anywhere in SCAFFOLD.yaml (no "harder than expert", no "Generate task"); workspace/ and worklog.md both still present; only .scratch/step2/ scratch files were removed and no sibling task directory was read.

Orchestrator verification: independently grepped SCAFFOLD.yaml for "harder than|expert level|Generate task" — no matches, difficulty directive confirmed not leaked.

## Step 3: Copy shared files — 2026-09-06T04:09:59.48680353Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-06T04:30:13.241193349Z

PRD generation complete and self-verified.

Output: workspace/PRD.md — 468 lines, 97,704 bytes, written in 8 incremental chunks (1 Write + 7 heredoc appends, PRDEOF terminator). No one-shot write; no truncation.

Section headings (29 total): §1 Introduction; §2 Global Specifications (2.1 Callers/Roles/Identity, 2.2 API Response Structure, 2.3 Collection Reads, 2.4 Resource Identity/Timestamps/Version Counters, 2.5 The Logical Clock, 2.6 Rejection Precedence, 2.7 Stale-Parent Guards, 2.8 Money/Rounding/Repair-Liability Invariant, 2.9 Licence Discipline & Segregation of Duties, 2.10 State Jurisdiction, 2.11 Cascades/Ledger Conservation/Version Propagation); §3 Business Logic & Workflows (3.1 Structures & Conducive-Condition Ledger, 3.2 Licensing/Suspending/Reinstating, 3.3 Graphing a Structure, 3.4 Real-Estate Transactions, 3.5 Choosing and Pricing a Treatment, 3.6 Discharging Chemical & Record Retention, 3.7 Underwriting the Bond, 3.8 The Renewal Cycle, 3.9 Bait-Station Monitoring & Escalation Cascade, 3.10 Damage Claims); §4 Endpoint Definitions; §5 Error Code Catalogue.

Document ends at a real boundary — the last row of the §5 error table (ERR_REPAIR_CAP_EXHAUSTED | 409).

Hard Contract results:
- Contract 1 — Field-Name Coverage: PASS. 131 distinct required names (123 entity fields + 62 request/query/path identifiers, deduped). Pass 1 found one gap, bait_station_id; repaired in §3.9. Final: 0 missing of 131.
- Contract 2 — Rule Coverage: PASS. All 58 error identifiers explained in prose before the catalogue. All 44 validation rules map to prose. Both concurrency rules documented in §2.7 with 412 and precedence slot. All 38 state-machine transitions across 8 stateful entities covered, including cyclic (ACTIVE_HIT->ACTIVE_HIT, ACTIVE_HIT->INSTALLED, ISSUED->AMENDED->ISSUED, ACTIVE->ACTIVE term roll-forward, LAPSED->ACTIVE) and every system-triggered one (report VOID on supersession, renewal VOID on lapse, station REMOVED on termination, claim DENIED on lapse). All 12 calculations checked constant-by-constant; every numeric constant recoverable from prose (0.12 as "12 percent / 1.12", 0.07/0.05 as "7 percent", 0.05 as "5 percent"). Every entity field's numeric bound stated. Sibling-branch symmetry written at equal density for the three adjudication branches, two exclusion bases, two renewal pricing variants, two reinstatement settlements. Priority ordering rendered as a 23-stage ladder in §2.6 including three documented conflict pairs (body-reference 404 before stale-version 412; target-state 409 before renewal-window 409; licence-expiry 409 before payment 402).
- Contract 3 — §3 Path Purity: PASS. §3 spans lines 172-349, 283 distinct backticked tokens; 0 start with /, 0 bare HTTP methods, 0 method+path combos. Raw-prose scan for unbackticked METHOD /path and bare collection paths in §3 also 0. Paths appear only in §2.7 and the §4 table.

Two internal-consistency decisions flagged by the generator:
1. The seed table declares the precondition "projected payout must exceed 0.00" for a repair approval but names no error. Mapped to ERR_REPAIR_CAP_EXHAUSTED (409) — a zero projection is what an exhausted ceiling produces — and §2.6 stage 23 widened so the ladder and §3.10 agree.
2. Ownership: claim-verification and claim-withdrawal owner checks (verifying graph's inspector_id; bond's property_id) stated with ERR_NOT_RESOURCE_OWNER, matching that error's declared condition; §2.6 stage 3 widened to list them. Claim filing has no ownership precondition, so the phrase "against their own bond" was removed from §3.10 to avoid implying a nonexistent check.
Also resolved: list ordering is created_at ascending everywhere, with the single documented exception of the plan's station listing (station_index ascending).

Constraints honoured: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped or referenced; no sibling task directory read. Scratch confined to .scratch/step4/. worklog.md, both SCAFFOLD*.yaml and workspace/INSTRUCTION.md untouched. PRD.md contains 0 occurrences of "scaffold"/"SCAFFOLD", "§1.", "difficulty", "expert level", "test suite", or "pytest", and no pseudocode/operator syntax outside the fixed §2.2 block.

Orchestrator verification: independently confirmed 468 lines / 97,704 bytes, tail ends at the final error-table row (complete section boundary, not mid-sentence), 29 headings present, and grep for "scaffold|expert level|harder than" returned no matches.

## Step 6: Generate implementation — 2026-09-06T05:00:54.179320378Z

(Note: Steps 5 and 6 were launched concurrently in a single message. Step 6 returned first, so it is logged here ahead of Step 5; the Step 5 entry follows below.)

The implementation is complete, compiles, and passes two end-to-end smoke suites.

Files written (all under workspace/implementation/):

| File | Lines | Role |
|---|---|---|
| app.py | 72 | Flask factory, blueprint registration, ApiError/HTTPException handlers, __main__ bind |
| start.sh | 17 | launcher (executable) |
| requirements.txt | 1 | Flask>=2.2 |
| store.py | 109 | in-memory dict store, new_id (uuid4), new_row/touch, ordering + reverse-index helpers |
| clock.py | 53 | logical clock pinned to 2026-08-01T00:00:00Z, days_between, plus_days, plus_hours |
| errors.py | 65 | ApiError + the 404/409 code maps |
| envelope.py | 115 | meta/response_type/data envelope, req_+20-char id, 3-digit-ms instants, pagination |
| auth.py | 43 | header auth, role gate, ownership refusals |
| validate.py | 213 | stage-5 shape validation (all typed getters + regexes) |
| calc.py | 316 | every enum domain, all constants, all 12 calculations |
| serialize.py | 244 | one projection per entity (immutable rows carry only id/created_at) |
| ledger.py | 218 | recomputed property/bond ledgers plus the three 3-deep cascades |
| common.py | 124 | path/body resolution, reusable ladder rungs, filtering |
| routes_core.py | 165 | clock, properties, inspectors + licence transitions |
| routes_inspection.py | 245 | graphs, notations, signing, supersession |
| routes_plan.py | 270 | plans, pricing/sizing freeze, applications, closeout, station install |
| routes_station.py | 95 | station read, visits, interval grading, escalation trigger |
| routes_bond.py | 239 | issuance, term review (lapse/terminate), reinstatement, invoice opening |
| routes_renewal.py | 98 | invoice reads, repricing, payment, term roll-forward |
| routes_wdo.py | 131 | statutory reports, turnaround, closing lead time, amendments |
| routes_claim.py | 252 | filing, verification pricing, adjudication, withdrawal |

3085 lines total. All 21 .py files pass python3 -m py_compile. 48 routes register, exactly matching the PRD §4 table.

Contract confirmations:
- No seeded data. The only entity containers are the twelve = {} literals in Store.__init__; no module writes a row at import time. Grep confirms no sqlite, no json.dump, no pickle, no /tmp, no file I/O anywhere — storage is plain dicts, so bash start.sh starts from an empty database with the clock at 2026-08-01T00:00:00Z.
- start.sh reads $PORT with a 10000 fallback, app.run(host="0.0.0.0", ...), and runs in the foreground via exec python3 app.py (no &, no nohup). The pip install is guarded by an import flask probe so a warm host boots instantly.

Smoke test (port 21806, single captured PID, killed by PID; port confirmed free afterwards). First attempt used port 21473, which was already occupied by another pipeline — no interference, that process exited on its own.

Pass 1 (40 checks, all green): header-exempt GET /_clock/current returned exactly 2026-08-01T00:00:00.000Z; property/inspector registration; graph open -> 2 notations -> duplicate-cell 409 -> wrong-owner 403 -> sign; property ledger 1/0/1 + infestation flag; plan quote 1288.00 and target_gallons 191 (hand-verified against §3.5); incompatible product 422; stale-version 412; application with retention_until 2030-07-31 (FL, 4x365d); completion; bond base 231.84 / cap 13910.40 / annual 287.48, term 2026-08-01..2027-08-01, window 2027-06-02; ledger flip to 1/1/0 on waiver; duplicate-bond 409; out-of-window renewal 409; no-deadline term-review 409; claim file + withdraw; clock jump then in-window invoice 99.18 + 132.41 = 231.59; second invoice 409; real-estate graph -> wrong-form 422 -> report with FL 72h due_at -> issue (turnaround measured) -> amend; 401/403/404/400 negatives.

Pass 2 (fresh boot, 46 checks, all green): schedule-overlap 409; FUMIGATION-on-crawlspace 422; bait plan installing 9 stations A1..A9; three HEAVY visits driving INSTALLED -> ACTIVE_HIT -> ACTIVE_HIT -> ESCALATED with correct ON_TIME grades and 14-day next_due_at; the full 3-deep cascade (station -> plan retreat_required at threshold 1 -> bond coverage_watch, each row taking its own version bump); rewound-clock service 422; claim priced under AGGREGATE_PRORATION (eligible 7500.00, deductible 525.00, projected 6975.00); conservation law asserted exactly before and after payout (13103.40 = 6975.00 + 0.00 + 6128.40); segregation-of-duties 403; DENY-without-reason 400; verifier-is-applicator 422; lapse via term-review with lapse_date = term_end+30 (2027-08-31), pending invoice -> VOID, new claim on lapsed bond 409; underpaid reinstatement 402; prorated reinstatement returning ACTIVE with the anniversary preserved (2027-08-31..2028-07-31, window 2028-06-01, term_index 2, reinstatement_count 1).

Scratch stayed inside .scratch/step6/ and was removed at the end; sibling step2/4/5/7/8/9 dirs are untouched. The agent never read or listed test_helpers/ or test_suite/, and did not modify worklog.md, PRD.md, INSTRUCTION.md or any SCAFFOLD*.yaml.

Two late corrections worth flagging, both caught by re-reading §2.6/§5 against what had been written: ERR_RENEWAL_WINDOW_NOT_OPEN and ERR_REINSTATEMENT_WINDOW_EXPIRED are 409 (not 422), and both payment-insufficiency codes are 402. The reinstatement staleness gate now compares instants (graph_completed_at >= now - 30d) rather than floored whole days.

## Step 5: Generate unit tests — 2026-09-06T05:37:59.305124567Z

(Logged after Step 6 because Steps 5 and 6 ran concurrently and Step 6 returned first.)

Step 5 complete. All seven Stage 2 writers finished and every audit passes.

Files written (task root, not under workspace/):
test_helpers/ — 2,709 lines: __init__.py 37, api_client.py 288, api_errors.py 152, assertions.py 356, constants.py 497, factories.py 467, fixtures.py 587, test_users.py 105, types.py 220.
test_suite/ — 12,597 lines, 332 test functions, 374 collected cases: conftest.py 39, test_01_reinstatement_and_exclusion_variants.py 461, test_02_pricing_component_order.py 338, test_03_report_cycle_and_claim_fork.py 472, test_04_escalation_and_lapse_cascades.py 616, test_05_rejection_precedence_pairs.py 381, test_06_interval_and_turnaround_boundaries.py 330, test_07_cross_entity_state_gates.py 415, test_08_occupation_and_coverage_occupancy.py 410, test_09_conservation_invariants.py 617, test_10_entity_contracts_and_defaults.py 867, test_11_lifecycle_state_machines.py 1271, test_12_derived_calculations.py 833, test_13_validation_precedence.py 1319, test_14_endpoint_behaviour.py 770, test_15_error_catalogue_reachability.py 1263, test_16_role_access_control.py 905, test_17_cross_cutting_and_consistency.py 1290.

Design-index coverage:
- §1.8 (queue A, difficulty): 18/18 instances translated, 0 skipped. 76 tagged tests, every instance >=2 (range 2-7). No stubs exist in that file.
- §1.9 (queue B, corner): 74/74 non-stub instances translated, 0 skipped on PRD grounds. 256 tagged tests, every instance >=1 (range 1-8). The 26 excluded_because: stubs were not translated (contract requirement); all 26 difficulty_instance cross-references verified to resolve to a real instance in the difficulty file.
- Two sub-outcomes inside otherwise-translated rbac instances were dropped, with categories: a 403 on an owner filing a NEW claim against another owner's bond (not-uniquely-derivable — claim filing is absent from the PRD's closed ownership-check enumeration), and a requested_by_role field assertion (no-verbatim-PRD-coverage — PRD §3.4 declares no such field). All other outcomes of both instances are covered.

Verification:
- python3 -m py_compile clean over all 9 helper files and all 18 suite files.
- pytest --collect-only: 374 tests collected, zero import/collection errors — every helper name and ApiClient method referenced actually exists.
- pyflakes: 0 findings outside the intentional re-export barrel in test_helpers/__init__.py.
- Design-tag audit (.scratch/step5/audit_design_tags.py): "no tag problems found" — exactly one Design: line per test, always the final docstring line, every rule_id/section matching the source yaml, no stub translated, no banned design-file vocabulary (0 hits for scaffold / corner design / difficulty design / design index), 0 skip/xfail markers.
- Location check: test_helpers/ and test_suite/ exist only at the task root; find workspace/ -name test_helpers -o -name test_suite returns 0 hits; workspace/ contains only PRD.md and implementation/ (never read or touched). worklog.md untouched. All scratch confined to .scratch/step5/; __pycache__ swept.
- Fixture-correctness sweep: no money-as-string literals, no whitespace-only header literals, no raw ISO string equality on _at fields, and the four ["data"] occurrences are envelope-shape assertions on raw response.json(), not double-unwraps.

One Stage 1 bug found and fixed: test_helpers/fixtures.py:315 (completed_bait_plan) sent product_epa_number="70103-12" — it was "70103-2", which fails both the PRD §3.6 pattern \d{3,5}-\d{2,4} and the helper's own validator, so every caller would have returned ERR_INVALID_REQUEST in Step 7. Fixed to a valid number.

Design-vs-PRD conflicts resolved in the PRD's favour (worth knowing for Step 7 triage): beyond the four pre-identified (conducive-code spellings, gallons_applied: 0.00 -> 0.10, no product_epa_number correspondence assertion, no 404 on unknown applicator_id), the writers found five more and followed the PRD: claim filing DOES bump Bond.version (§3.10, contradicting the yaml); amendment_reason_code: SCOPE_CORRECTION is not a declared member (used CLERICAL_CORRECTION); a completed renewal is PAID, not COMPLETED; ERR_INVALID_REQUEST is 400 per §2.6 stage 5, not the yaml's 422 (only the error id is asserted, the registered map supplies the status); and list order is ascending created_at per §2.3, not newest-first.

Orchestrator verification: confirmed test_helpers/ and test_suite/ are at the task root with no stray copies under workspace/ (workspace/ holds only INSTRUCTION.md, PRD.md, implementation/, plus the orchestrator's own sweep.sh and summarize.py); 332 Design: tags counted across the suite.

## Step 7: Run tests and iterate — 2026-09-06T06:23:08.883784263Z

Task complete — all 8 rounds clean at 374/374.

Iterations run: 2 full 8-round sweeps (sweep 1 = baseline diagnosis, sweep 2 = verification).

Baseline was unusually healthy: 369/374 in all 8 rounds, with zero flakiness — 5 deterministic failures reducing to 3 distinct root causes, one in each layer.

Tests deleted:
None. No test asserted a scaffold-only rule, and no test failed the coverage check outright. One assertion was removed under the partial-coverage split rule (below).

Fixes applied to test_suite/:
- test_14_endpoint_behaviour.py — test_renewal_opens_exactly_on_the_window_date: removed the single assertion invoice["amount_paid_usd"] is None. DEFAULT-VALUE SILENCE, handled as a STEP 1c partial-coverage split. PRD §3.8 names amount_paid_usd only as a field completion "records ... as the amount tendered" and never states what a PENDING invoice carries; §3.10's claim precedent ("every money field at 0.00") makes the implementation's 0.00 an equally faithful reading of a money field. The covered assertions (PENDING, term_index, due_on, inspection_id null, paid_at null) were all kept and all pass. Design tag: Corner/endpoints/renewal_creation_opens_exactly_on_the_window_date_and_prices_provisionally.
- test_10_entity_contracts_and_defaults.py — test_station_service_is_written_once_and_exposes_no_version: the test serviced a bait station at the exact instant of its installation (a fresh station's last_serviced_at is its plan's completed_at, and the test never moved the clock off the 2026-08-01T00:00:00Z startup value). PRD §3.9 requires serviced_at to be strictly after last_serviced_at, so the PRD-faithful implementation correctly returned ERR_SERVICE_TIME_INVALID and the setup blew up. Added a clock advance before the visit and retargeted the serviced_at assertion to that instant. The PRD-2.4 immutability assertions the test exists to make are untouched — the fix makes the test more PRD-faithful, not less.

Fixes applied to test_helpers/:
None. The helper layer was sound: money as JSON numbers, full ISO-8601 instants, tolerant instant comparison, both paginated and unpaginated list validators present, per-inspector non-overlapping diary slots, and correct per-role identity binding (inspector id for FieldInspector/Applicator, property id for PropertyOwner, opaque constants for the three operator roles).

Fixes applied to implementation/:
- routes_bond.py, create_bond (bond issuance, stage-20 gate): ERR_PLAN_NOT_COMPLETED was raised with HTTP 422; PRD §2.6 stage 20 and the §5 error catalogue both state 409 verbatim. Changed to 409. This one-character fix cleared 3 of the 5 failures.

Final round-by-round figures: all 8 rounds 374/374. Union of tests failing in >=1 round: 0. No skips, no xfails, no weakened assertions.

Notes: sweep.sh and summarize.py had no bugs and were used unmodified. worklog.md and workspace/PRD.md were never touched. No load-induced false positives appeared in either sweep — every failure was deterministic across all 8 rounds, which made triage unambiguous.

Orchestrator verification: independently read all 8 results.*.json — every round reports passed=374 total=374; baseline sweep had been 369/374 in all 8 rounds. Test count unchanged at 374, consistent with zero deletions.

## Step 8: Finalize PRD — 2026-09-06T06:33:40.654497981Z

PRD_FINALIZED.md is a one-line patch of PRD.md.

Line counts:
- PRD.md — 468 lines / 97,704 bytes
- PRD_FINALIZED.md — 468 lines / 97,907 bytes
- Delta: 0 lines (0.00%), +203 bytes; one paragraph rewritten in place.

Changes:
- §3.8 (renewal invoice creation) — insert — pinned amount_paid_usd to 0.00 at invoice creation, and stated it stays 0.00 while no payment has been recorded (so an invoice that never gets paid reports 0.00, not null) — implementation/routes_bond.py:228 ("amount_paid_usd": calc.ZERO), paid value at implementation/routes_renewal.py:90.

Pre-edit search log — Edit 1 (amount_paid_usd default on a renewal invoice):
- (a) Subject: the amount_paid_usd field on a BondRenewal row — its value at creation and at every later status it can reach.
- (b) Paths enumerated: grep -rn "amount_paid_usd" implementation/ returned exactly three sites, all read in full context — routes_bond.py:198-231 open_renewal (creation, sets calc.ZERO = Decimal("0.00") per calc.py:130, alongside paid_at: None); routes_renewal.py:41-98 complete_renewal (the only writer after creation; sets calc.r2(amount) on the PENDING -> PAID transition); serialize.py:158-174 renewal_out (emits the raw money value as a two-decimal JSON number, no null-coalescing, so the stored 0.00 is what the client sees). Also checked the only other renewal-mutating path, ledger.py:149-170 lapse_bond — the PENDING -> VOID hop sets status and touch()es the row but never touches amount_paid_usd, so a voided invoice keeps 0.00. No reinstate, term_review, or terminate_bond path writes the field.
- (c) Wording adjustment: the first draft said only "0.00 at creation". Because the VOID path (ledger.py:155) leaves the field untouched, a creation-only claim would have left the voided-invoice value undetermined, so it was widened to "stays 0.00 for as long as no payment has been recorded against the invoice", covering PENDING and VOID alike without asserting anything about the PAID value that the following sentences in §3.8 already pin ("records amount_paid_usd as the amount tendered"). Deliberately did NOT also pin inspection_id/paid_at null-at-creation, since Step 7 kept those assertions as already-covered and no impl divergence exists there.

Step 7 items that produced NO edit:
- test_10 station-service fix (test layer) — no edit. Pure fixture bug. routes_station.py:60-63 rejects a visit whose clock instant is <= the station's last_serviced_at with ERR_SERVICE_TIME_INVALID (422), which is verbatim PRD §3.9 ("strictly after ... A clock rewound to, or exactly onto, the previous visit is refused with ERR_SERVICE_TIME_INVALID") and §5. The precondition the test tripped over — a fresh station's last_serviced_at being the plan's completed_at — is already stated verbatim in PRD §3.6. PRD determines this uniquely; nothing to pin.
- routes_bond.py ERR_PLAN_NOT_COMPLETED 422 -> 409 — no edit, as anticipated. Verified at implementation/routes_bond.py:50: the raise now carries 409. PRD §2.6 stage 20 lists ERR_PLAN_NOT_COMPLETED (409) and the §5 catalogue row reads | ERR_PLAN_NOT_COMPLETED | 409 |; §3.7 names the code without a status. The fix moved the implementation INTO agreement with already-correct PRD prose, so this is a pure impl bug, not a PRD silence or mismatch.
- Test deletions — none occurred, so nothing to trace.
- test_helpers/ fixes — none occurred, so nothing to trace.

Verification:
- wc -l -c: 468/97,704 vs 468/97,907 — no truncation, line count identical.
- diff PRD.md PRD_FINALIZED.md: exactly one hunk, 287c287, 2 changed lines (1 <, 1 >) — the §3.8 paragraph, with the inserted sentence as the only textual difference. No other hunks.
- Tail check: PRD_FINALIZED.md still ends with the final §5 error-table row | ERR_REPAIR_CAP_EXHAUSTED | 409 |.
- PRD.md, implementation/, test_suite/, test_helpers/ and worklog.md were not modified; SCAFFOLD*.yaml and worklog.md were not read. No scratch files were created.

Orchestrator note on Step 8 scope: Step 8 was NOT skipped — Step 7 applied one implementation/ fix and two test_suite/ changes, so the skip condition (zero iterations beyond baseline) did not hold. A near-identical PRD_FINALIZED.md is legitimate here because only one of those three items was a genuine PRD silence.

## Step 9: Complete PRD — 2026-09-06T07:09:18.329230571Z

Orchestrator design decision: Step 9 was run as FOUR SEQUENTIAL subagent passes over one shared PRD_COMPLETED.md, partitioned by implementation module, rather than as a single subagent. Rationale: a single agent cannot hold a 21-module / 3085-line implementation plus a 470-line PRD in context densely enough to do an exhaustive behavior-by-behavior scan, and a one-shot rewrite of a ~100KB document truncates at the output cap. Pass 1 performed the cp from PRD_FINALIZED.md; passes 2-4 were explicitly forbidden from running cp so earlier edits survived. A 4th reconciliation pass was added because partitioned passes report cross-pass contradictions instead of fixing them.

Partition:
- Pass 1 (foundations/core): app.py, store.py, clock.py, errors.py, envelope.py, auth.py, validate.py, common.py, serialize.py, routes_core.py -> PRD §1, §2.1-§2.7, §2.9, §2.10, §3.1, §3.2.
- Pass 2 (inspection/WDO/plan/station): routes_inspection.py, routes_wdo.py, routes_plan.py, routes_station.py -> PRD §3.3, §3.4, §3.5, §3.6, §3.9.
- Pass 3 (bond/renewal/claim/money/cascades): routes_bond.py, routes_renewal.py, routes_claim.py, calc.py, ledger.py -> PRD §2.8, §2.11, §3.7, §3.8, §3.10.
- Pass 4 (reconciliation): §2.6 ladder + cross-pass contradiction sweep + verification of the earlier passes' riskiest claims.

--- PASS 1 (foundations) ---
cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md was run. Source 468 lines / 97,907 bytes; target after edits 470 lines / 102,794 bytes. 11 ambiguity-pins, 3 mismatch-revisions, 13 diff hunks.
- §2.1 — revise — ambiguity — a whitespace-only header is ERR_UNAUTHENTICATED; both header values are trimmed before role matching and before any owner comparison — auth.py:24-28
- §2.2 — revise — ambiguity — api_request_id is req_ plus exactly twenty chars from A-Z0-9 — envelope.py:15,24
- §2.2 — revise — ambiguity — api_request_timestamp is read from the logical clock, not wall clock, so two responses without an intervening clock move share it — envelope.py:52-56
- §2.3 — revise — ambiguity — offset has no upper bound (past-the-end read is a valid empty page with true total_count, has_more false); params tolerate whitespace and a leading sign, but an empty value is rejected rather than defaulted — envelope.py:78-100,112
- §2.3 — revise — ambiguity — created_at ties break on server creation order, making the ordering total — store.py:59-66
- §2.3 — revise — ambiguity — an unrecognised filter value (bad enum, nonexistent id, non-boolean boolean) matches no rows instead of erroring; only limit/offset can fail a collection read — validate.py:192-213, common.py:111-124
- §2.5 — revise — ambiguity — the clock read is exempt from the role check too; both clock endpoints answer 200 with data.current_utc; sub-millisecond input is stored to microseconds but rendered at three digits — routes_core.py:27-39, envelope.py:27-33, validate.py:133-152
- §2.6 stage 5 — revise — MISMATCH — a state code must be one of the five declared jurisdictions, not merely any two uppercase letters (STATE_CODE_RE is dead code; every state field is an enum check) — routes_core.py:52,98, calc.py:12
- §2.6 stage 5 — revise — ambiguity — instants take an optional 1-9-digit fractional part; strings-for-numbers and booleans-for-integers/money fail as type errors; an optional field sent as null equals omission and takes its default while a required null fails; an absent/empty body reads as {} and a non-object body fails here — validate.py:16,25-33,36-37,81-131
- §2.9 — revise — MISMATCH — license_number uniqueness within license_state is nominal only; the server enforces format and does not refuse a duplicate — routes_core.py:96-97 (no uniqueness check anywhere)
- §2.9 — revise — ambiguity — license_categories is echoed in the order supplied, not reordered — serialize.py:44
- §3.1 — revise — MISMATCH — ledger recompute also fires on graph supersession, not just signing/issuance/termination — ledger.py:110-120
- §3.1 — insert — ambiguity — a recompute producing identical values is not a mutation (no updated_at/version change); one that changes >=1 of the four values raises version by exactly 1 once — ledger.py:59-68
- §3.2 — revise — ambiguity — registration stores any shape-valid license_expires_on, including an already-past date, and the record is still ACTIVE — routes_core.py:102-107
- §3.2 — revise — ambiguity — lifting a suspension on a run-out credential is ERR_LICENSE_EXPIRED (409), not a reinstatement error — routes_core.py:146-149
- §3.2 — revise — ambiguity — only the reinstatement path writes license_expires_on/ce_credits; supplied on the other three moves they are validated then ignored — routes_core.py:135-161
- §4 intro — revise — ambiguity — trailing-slash-insensitive routing; unmatched path -> ERR_INVALID_REQUEST 404, undeclared method -> ERR_INVALID_REQUEST 405, and neither needs headers — app.py:28,45-57
Left for later passes: the §2.11 cascade-mutation claim (property-ledger recompute only touches the row on a real change); ledger.py cascade machinery; calc.py formulas; errors.py message strings deliberately left unpinned (PRD never constrains message text). §2.10 was checked against calc.py (form map, turnaround hours, retention years, retention_until = applied date + years*365) and needed no edit.

--- PASS 2 (inspection/WDO/plan/station) ---
No cp run; pass 1's 13 hunks confirmed still present. 16 Edit calls -> 13 new hunks; 13 ambiguity-pins, 5 mismatch-revisions (18 distinct behaviors). File grew to 470 lines / 107,546 bytes; total 26 hunks.
- §3.3 — insert — ambiguity — body identifiers resolve in the order property_id, inspector_id, supersedes_inspection_id, leftmost unknown wins — routes_inspection.py:62-64
- §3.3 — insert — ambiguity — the schedule-overlap diary includes every graph naming that inspector, any status (DRAFT/GRAPHED/SUPERSEDED) and any structure — routes_inspection.py:77-82
- §3.3 — insert — ambiguity — a later graph may name an already-SUPERSEDED graph; the 3 hops re-run, re-touching the retired graph (version +1) and finding its reports already VOID — ledger.py:110-120
- §3.3 — insert — MISMATCH — for notating/signing, the path-addressed graph must resolve before ownership: unknown id => ERR_INSPECTION_NOT_FOUND (404) even for a non-owner; existing-but-foreign graph => 403 ahead of shape/cross-field/state — routes_inspection.py:136-138, 215-217
- §3.3 — insert — ambiguity — ACTIVE_INFESTATION + organism: NONE is ERR_INVALID_REQUEST (400), not the stage-6 cross-field code — routes_inspection.py:154-155
- §3.3 — insert — ambiguity — a DRAFT graph keeps reporting all four rollups at 0/0/false/0.00 no matter how many notations it carries; they are computed only at signing — routes_inspection.py:99-105, 238
- §3.4 — revise — MISMATCH — report creation examines neither the graph's status nor its purpose (both belong to issuance), no uniqueness rule limits reports per graph, and the snapshotted closing_date may be null — routes_wdo.py:31-53
- §3.4 — insert — ambiguity — a new report starts with issued_at/turnaround_hours/amendment_reason_code null, sla_breached false, amendment_count 0 — routes_wdo.py:42-55
- §3.4 — insert — ambiguity — re-issue leaves the last amendment_reason_code standing rather than clearing it — routes_wdo.py:100-107
- §3.5 — insert — ambiguity — proposal resolves property_id -> inspection_id -> applicator_id, and tests neither the graph's status/purpose nor anything about the applicator's licence — routes_plan.py:58-60, 126-130
- §3.5 — insert — ambiguity — a new plan starts gallons_applied_total 0.00, escalated_station_count 0, retreat_required false, completed_at null — routes_plan.py:82-89
- §3.5 — insert — ambiguity — pricing step 4 reads active_infestation_found as the graph reports it now, so a DRAFT-justified plan never takes the 12% surcharge — calc.py:175-178
- §3.5 — revise — MISMATCH — on approval the GRAPHED test precedes both licence tests (ERR_INSPECTION_NOT_GRAPHED wins over ERR_LICENSE_NOT_ACTIVE), and neither categories nor license_state are checked — routes_plan.py:126-130
- §3.6 — revise — MISMATCH — product_epa_number is format-validated only; it is NEVER cross-checked against the plan's chemical_product_code (PRD previously claimed it must correspond) — routes_plan.py:160
- §3.6 — revise — MISMATCH — closeout has NO ownership check: any Applicator may complete any plan (PRD previously said "the plan's own applicator") — routes_plan.py:222-223
- §3.6 — revise — ambiguity — failing the per-method completion gate is itself ERR_INVALID_PLAN_STATE — routes_plan.py:229-240
- §3.6 — insert — ambiguity — cascade-installed stations start consecutive_activity_count/service_count/matrix_replacement_count at 0 — routes_plan.py:249-259
- §3.9 — insert — ambiguity — a service against a plan that is not COMPLETED is ERR_INVALID_PLAN_STATE, evaluated right after the station's own state test — routes_station.py:50-52
Deliberately deferred to pass 4: §2.6 stage 3/4 ownership-before-path-existence (same behavior also at routes_plan.py:155-157 and routes_station.py:40-42); §2.6 stage 11/12 vs stage 20 ordering on plan approval; the §2.11 cascade-mutation claim. §4 endpoint rows and §5 error rows for these four modules were checked exhaustively (paths, methods, role lists, all 23 error/status pairs) and matched exactly — no edits needed.

--- PASS 3 (bond/renewal/claim/money/cascades) ---
No cp run; the earlier 26 hunks confirmed still present. 16 ambiguity-pins, 3 mismatch-revisions; 19 edits -> 18 new hunks; total 44 hunks. File grew to 470 lines / 115,043 bytes.
- §2.8 — revise — MISMATCH — money is emitted as a JSON NUMBER, not a two-decimal string; JSON does not pad trailing zeros (0.00 -> 0.0, 1234.50 -> 1234.5), so money must be compared numerically — envelope.py:42-44
- §2.11 — insert — ambiguity — bond termination named as a fourth (two-level) chain: bond -> surviving stations + property ledger — ledger.py:173-184
- §2.11 — revise — ambiguity — the cascade no-op carve-out (open item 1; wording quoted below) — ledger.py:59-68,114-120,127-142,149-184
- §3.7 ¶1 — insert — MISMATCH — the five issuance refusals resolve in §2.6 stage-20/21 order (GRAPHED -> PURPOSE -> PLAN_NOT_COMPLETED -> PROPERTY_MISMATCH -> DUPLICATE_ACTIVE_BOND), not in the order the paragraph narrates them — routes_bond.py:46-59
- §3.7 ¶2 — insert — ambiguity — conducive_waiver_codes members must be distinct (ERR_INVALID_REQUEST), no length bound, order preserved, and an unmatched code waives nothing — routes_bond.py:38-40, validate.py:183-188, ledger.py:57
- §3.8 — insert — ambiguity — ERR_RENEWAL_ALREADY_PENDING outranks ERR_RENEWAL_WINDOW_NOT_OPEN — routes_bond.py:205-211
- §3.8 — insert — ambiguity — opening an invoice takes no body and is NOT a bond mutation (bond version unmoved), so a claim filed right after still matches expected_bond_version — routes_bond.py:198-231
- §3.8 — insert — ambiguity — a new invoice's inspection_id and paid_at are both null until completion — routes_bond.py:217-228
- §3.8 — insert — ambiguity — amount_usd shape bound: JSON number, <=2 decimals, 0 <= x <= 9999999.99, out-of-bound is ERR_INVALID_REQUEST — routes_renewal.py:47, validate.py:107-130
- §3.8 — insert — MISMATCH — completion preconditions resolve in §2.6 ladder order (invoice state -> bond state -> licence -> graph status/purpose/property -> window -> payment), not in the narrated order — routes_renewal.py:52-80
- §3.8 — insert — ambiguity — coverage_watch is never cleared by a renewal and retreat_credit_count carries across the term boundary; the bond's version rises whether or not a flag moved — routes_renewal.py:93-96
- §3.8 — insert — ambiguity — lapse requires the clock date STRICTLY AFTER current_term_end + 30; exactly on the deadline is too early — routes_bond.py:123
- §3.8 — insert — ambiguity — termination requires STRICTLY AFTER lapse_date + 90; on exactly that date reinstatement is still possible — routes_bond.py:127-128 vs 159
- §3.8 — insert — ambiguity — a review of an already-TERMINATED bond is also ERR_INVALID_BOND_STATE — routes_bond.py:122-132
- §3.8 — insert — ambiguity — reinstatement amount_usd carries the same 0-9999999.99 bound — routes_bond.py:145
- §3.8 — insert — ambiguity — the "live activity" refusal reuses ERR_REINSTATEMENT_INSPECTION_STALE (422) and is reached only after the signature-age test — routes_bond.py:164-169
- §3.8 — insert — ambiguity — reinstatement leaves money components, the three watch fields, and the lapse-voided invoices / lapse-denied claims untouched; no ledger recomputation is needed because a bond of record is ACTIVE or LAPSED; bond version +1 once — routes_bond.py:185-191, ledger.py:33-38
- §3.10 — insert — ambiguity — filing has NO ownership test; any PropertyOwner may file against any bond — routes_claim.py:34-43
- §3.10 — insert — ambiguity — verifying_inspection_id resolves before the ownership test (unknown id -> ERR_INSPECTION_NOT_FOUND even for a non-owner), and claim state is tested before bond state — routes_claim.py:107-119
- §3.10 — insert — ambiguity — claim state before bond state; denial_reason_code is shape-validated on every decision but ignored on approvals, leaving the claim's field null — routes_claim.py:176-186,193-216
- §3.10 — insert — ambiguity — the adjudication rerun's exact inputs: stored eligible_damage_usd, re-keyed tier, current claims_paid_to_date_usd, and reserved_claim_amount_usd LESS this claim's own projected_payout_usd; the single-reserve rule makes it always reproduce the reserve, and the >0 test applies to the rerun figure — routes_claim.py:198-205
- §3.10 — insert — ambiguity — withdrawal makes no demand on bond status; from SUBMITTED the bond is untouched (version unmoved) and approved_payout_usd stays 0.00; from UNDER_ADJUDICATION the release raises the bond's version by one — routes_claim.py:238-251

Open item 1 resolution (§2.11 cascade no-op), final wording verbatim:
"A row that a cascade reaches but leaves unchanged is not a mutation, and its updated_at and version are left exactly as they were: a statutory report already VOID when its graph is superseded, a bait station already REMOVED when the covering bond terminates, a renewal invoice that is not PENDING or a damage claim that has already settled when the bond lapses, and a structure whose recomputed conducive counters and active_infestation_on_record all come out equal to the values already stored, exactly as §3.1 spells out. A hop whose own precondition never fires touches nothing at all: a station escalation that does not carry its plan's escalated_station_count up to the escalation threshold never reaches the bond, so the bond's version does not move, while the plan's always does because its escalation count itself changed. The lapsing or terminating bond, by contrast, always changes its own status and is therefore always a mutation."
Checked against supersede_graph (ledger.py:110-120), escalation_cascade (127-142), lapse_bond (149-170) and terminate_bond (173-184); consistent with pass 1's §3.1 sentence, which it cites rather than restates.

Further §2.6 divergence recorded for pass 4: on POST /damage-claims/{id}/attach-verification the BODY reference verifying_inspection_id (a stage-8 concern) resolves before the stage-3 ownership test, because the ownership subject is the body-referenced graph — distinct from pass 2's path-row cases. Same-family instance confirmed on POST /damage-claims/{id}/withdraw (routes_claim.py:231-236), which resolves the path claim and the bond it points at before ownership. Also left to pass 4: §2.6 stage 10's silence on within-stage entity order (impl always tests the path-addressed row's state first, the referenced bond's second).

--- PASS 4 (reconciliation) ---
No cp run; all 44 pre-existing hunks confirmed byte-for-byte present. 9 mismatch-revisions, 4 ambiguity-pins across 11 Edit operations. File grew to 470 lines / 120,358 bytes; 49 hunk records.

Task A — §2.6 ladder made true of the implementation (no stages renumbered; still 23):
- Stage 3 (Ownership) — revise — ownership cannot run until the row carrying the ownership key is located, so the 404 outranks the 403. Three cases: (a) path-addressed key -> path row plus any row it points at resolved first (routes_inspection.py:135-138, 215-217; routes_plan.py:154-157; routes_station.py:39-42 station->plan; routes_claim.py:231-236 claim->bond); (b) body-referenced key -> that one reference resolved first (routes_claim.py:107-112); (c) opening a graph is the exception in the other direction — routes_inspection.py:30-34 compares the raw payload inspector_id against X-User-ID only when it is a string, resolving nothing, so it fires ahead of stage 5 and stage 8, and a non-string/absent inspector_id skips the test and falls through to shape.
- Stage 8 (Body-reference existence) — revise — the false universal now carries one carve-out: when the stage-3 ownership subject IS the body-referenced row (verifying_inspection_id, and only that), it resolves ahead of stage 3; every other body reference resolves at stage 8, after ownership. Evidence routes_claim.py:107-112 vs routes_claim.py:43 (filing: get_bond 404 before the 412, so the existing stage-8/9 claim stands).
- Stage 10 (Target state) — insert — within-stage entity order stated once: path-addressed row first, referenced row second (routes_renewal.py:52-57 invoice->bond; routes_claim.py:114-119 and 176-186 claim->bond; routes_station.py:47-52 station->plan).
- Stage 11 (Licence active) — revise — "five operations" -> SIX, adding treatment-plan approval (routes_plan.py:128-129); noted that on renewal completion and plan approval the licence examined is the consumed worker's, not the caller's; and stated the A3 exception, explicitly scoped to plan approval so renewal completion is unaffected (routes_plan.py:126-130).
- Stage 12 (Licence unexpired) — revise — same op-list correction (routes_plan.py:130) plus the back-reference to stage 11's hoist; also fixed a dangling "stage 27" -> "stage 23" in a 23-stage ladder.
- Stage 20 (Referential state of consumed rows) — insert — records the plan-approval hoist from the stage-20 side and pins within-stage order for the two operations testing status/purpose/structure: routes_renewal.py:65-69 and routes_bond.py:152-156 both run GRAPHED -> PURPOSE_MISMATCH -> PROPERTY_MISMATCH.
Cross-checked against §3.3 line 208, §3.5 line 253, §3.8 line 291, §3.9 line 311, §3.10 line 325 before editing, so no opposite-direction contradiction was created. Pass 3's two "no change needed" §2.6 items were verified correct and left alone: stage 6 is scoped to graph creation/cell notation only (so routes_claim.py:180-181's ERR_INVALID_REQUEST 400 for DENY without denial_reason_code is consistent), and stage 20's ordering already matches routes_bond.py:152-156 and routes_renewal.py:65-69.

Task B — verification of the three riskiest earlier claims:
- B1 money wire format — CLAIM CORRECT, prose untouched. envelope.py:41-44 _json_default returns float(obj) for Decimal and _respond calls json.dumps(body, default=_json_default); serialize.py passes money through raw (no str() anywhere). So Decimal("0.00") -> 0.0 and Decimal("1234.50") -> 1234.5 on the wire, exactly as §2.8 states. test_helpers/assertions.py:120-136 asserts isinstance(actual, (int, float)) and compares numerically.
- B2 state-code enum — CLAIM CORRECT, prose untouched. STATE_CODE_RE at validate.py:20 has ZERO call sites (genuinely dead). Both and only the two client-supplied state-bearing fields go through the enum: routes_core.py:52 state_code and routes_core.py:98 license_state, each v.get_enum(..., calc.STATE_CODES) with calc.py:12 = ("AL","FL","GA","TX","CA"); get_enum (validate.py:68-78) raises invalid_request -> ERR_INVALID_REQUEST (400), matching stage 5. Every other state_code is derived from a property row (routes_wdo.py:35, routes_plan.py:194-199), never client-supplied. The claim is universal as written.
- B3 closeout — BOTH CLAIMS CORRECT, prose untouched. routes_plan.py:220-223 complete_plan authenticates ("Applicator",), fetches the plan, tests status — no applicator_id comparison anywhere, and it does not even bind user_id. product_epa_number is only pattern-checked (routes_plan.py:158, EPA_RE); chemical_product_code appears only at routes_plan.py:35, routes_plan.py:78 and serialize.py:97, never in a comparison against the EPA number.

Task C — whole-document integrity:
- C1: 49 diff hunk records; all 44 pre-existing ones verified byte-for-byte present; the 5 new hunks are 21c21, 102c102, 107c107, 109,111c109,111, 119c119. Four pass-4 edits landed on already-modified lines and created no new hunk record. Hunk list saved at .scratch/step9/pass4_hunks.txt.
- C2: PRD_FINALIZED.md 468/97,907; PRD_COMPLETED.md 470/120,358 — grew by 5,315 bytes, never shrank; cmp reports DIFFERENT.
- C3: tail is the final §5 row | ERR_REPAIR_CAP_EXHAUSTED | 409 |; grep -c '^#' = 29; §2.6 still has exactly 23 numbered stages.
- C4 contradiction sweep — three real contradictions found and fixed, three subjects verified clean:
  * FIXED: §2.1 said "Ownership is enforced on FIVE write operations" and omitted attach-verification, while §2.6 stage 3 listed six and §3.10 demands it (routes_claim.py:111-112). Corrected to six in both §2.1 sentences, with the sixth binding spelled out (subject is the offered graph, not the claim). Consequential edits: §3.6 "the five ownership-checked operations of §2.1" -> six; §3.10 "Of the three claim writes, only withdrawal is ownership-guarded" -> four writes, two guarded (verification and withdrawal), two role-only (filing and adjudication).
  * FIXED: §3.9 listed station-service preconditions in a narrative order that read as state-before-ownership; added the resolution-order clause (ownership first, station+plan resolved before it -> ERR_BAIT_STATION_NOT_FOUND per errors.py:42, then station state, then plan state, then licence).
  * VERIFIED CONSISTENT, no edit: cascade version propagation / no-op rule (§2.11 vs §3.1, §3.3, §3.8 — the four ledger-recompute triggers and the "reached but unchanged is not a mutation" rule agree everywhere); money format (§2.8 is the only wire-format statement; §2.2 carries no money example to contradict it); amount_paid_usd (§3.8 "0.00 at creation, never null" = routes_bond.py:228 calc.ZERO; "records the amount tendered" = routes_renewal.py:90 calc.r2(amount)).

--- STEP 9 TOTALS ---
PRD_FINALIZED.md 468 lines / 97,907 bytes -> PRD_COMPLETED.md 470 lines / 120,358 bytes (+2 lines, +22,451 bytes, +22.9%). 49 diff hunks. Aggregate across the four passes: 44 ambiguity-pins and 20 mismatch-revisions.

Orchestrator verification: PRD_COMPLETED.md is 470 lines / 120,358 bytes and is NOT byte-identical to PRD_FINALIZED.md (so the scan demonstrably ran); 29 headings intact; tail ends at the final §5 error-table row; no implementation/ or test file has an mtime newer than results.1.json from the clean Step 7 sweep, so the 374/374 x 8-round result still describes the shipped code; a single worklog.md exists at the task root with no strays under workspace/.

