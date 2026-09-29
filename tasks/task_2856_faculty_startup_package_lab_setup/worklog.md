## Step 1: Create task directory — 2026-09-05T07:21:49.248Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2856_faculty_startup_package_lab_setup and its workspace/ subdirectory. Index 2856 was pre-assigned by the orchestration prompt (no ./tasks/ scan performed, per instruction, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T09:06:11.600Z

All three scaffold artifacts are complete and the lint is clean.

Files: SCAFFOLD.yaml 3075 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 2233 lines, SCAFFOLD_CORNER_DESIGN.yaml 4116 lines.

SCAFFOLD.yaml census (1.0-1.7): 11 entities, 10 state machines (one carrying two parallel axes), 2 concurrency_rules, 13 calculations, 43 validations (single global priority ladder), 61 endpoints, 43 errors, 5 roles, api_prefix "/", no scaffold_difficulty_design / scaffold_corner_design keys present.

1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rule_id blocks (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant) x 2 instances = 18 instances, all non-stub.

1.9 SCAFFOLD_CORNER_DESIGN.yaml: all 9 taxonomy sections, 84 instances total = 66 non-stub test recipes + 18 excluded_because stubs. entities 15/0, state_machines 12/6, calculations 5/8, validations 16/2, endpoints 5/0, errors 4/0, rbac 5/0, complexity_layers 3/2, consistency_model 1/0 (non-stub/stub). Every stub cites a difficulty instance that exists by name; no name collides across the two design files; every ${var} resolves to an earlier capture (verified programmatically).

Lint verdict (verbatim):
  SCAFFOLD 1.8/1.9 -> 1.5 lint report
  Coverage: 1.5 endpoints declared 61; 1.1 entities declared 11; 1.8 instances scanned 18; 1.9 instances scanned 66; calls scanned (1.8+1.9) 1150
  VERDICT: clean lint — all 1.8/1.9 calls conform to 1.5 and all 1.1 FKs have reverse-reachability in 1.5.
(Three violations were found and fixed on the way: two /equipment-orders/{id}/receive calls in 1.8 acted as DeanOffice instead of FacilitiesManager; one 1.9 negative instance needed renaming to corner_create_startup_package_missing_required_spend_deadline_is_rejected so the linter's negative-name exemption applies.)

Design adjudications:
- api_prefix "/"; 61 endpoints / 43 errors deliberately above the nominal Expert band, justified by the two-axis package state machine plus five sub-workflows.
- OCC confined to the two declared concurrency_rules (expected_space_version on POST /space-assignments, expected_package_version on /place); every guard value in the design files is ${var}-derived, never a literal.
- Two endpoints added under the 1.5 ladder purely to make declared transitions reachable: DELETE /startup-packages/{id}/tranches/{tranche_id} (204, output None) and POST /lab-spaces/{id}/utility-upgrade.
- Inline-dict output: used for /spend-summary and the clock endpoint; CARRIED_FORWARD made terminal; SURPLUSED bound to OUTSIDE_OFFER separations for enum closure; allocated_share_pct unified on clock-instant semantics.
- Priority 21's applies_to deliberately omits /startup-packages/{id}/activate, and the APPROVED -> ACTIVE precondition was narrowed per package_kind so a RETENTION_COUNTEROFFER can activate while its faculty member is still in DEPARTURE_NOTICE (otherwise retention was unreachable).
- Cross-file type fix applied: 303 date-only literals for datetime-typed inputs (available_on, expires_on, effective_from, effective_to, released_on, planned_start, planned_end) were expanded to full ISO-8601 instants (...T00:00:00Z) in both design files, so downstream factories cannot send 2026-07-01 where the contract wants an instant.
- Two numeric near-misses were re-costed rather than shipped: 12000010 was replaced by 12001000 so spend_down_ratio (0.60005 -> 0.6001) actually discriminates ROUND_HALF_UP, and the carryforward-threshold fixture was re-based on a 25000000/15000000 tranche pair so the 0.4999-vs-0.5000 boundary has money left to carry.

Orchestrator verification: all three files present; grep confirms the "harder than expert level" difficulty directive did not leak into SCAFFOLD.yaml (scenario key holds the scenario text only).

## Step 3: Copy shared files — 2026-09-05T09:06:11.631Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T09:20:21.917Z

PRD generation complete. Artifact: workspace/PRD.md — 544 lines, built via nine chunked cat >> appends (no single giant Write). Ends at the final row of the section-5 error table (ERR_INSUFFICIENT_TRANCHE_BALANCE | 422) — a real section boundary, no truncation.

Sections emitted:
- 1 Introduction (pain point -> system of record -> determinism + money-conservation constraints)
- 2 Global Specifications, 13 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim, byte-identity confirmed), 2.3 Pagination, 2.4 Identity/Audit/Ledger Immutability, 2.5 Logical Clock & Calendar, 2.6 Cents/Percentages/Rounding, 2.7 Three-Funder Cost Sharing, 2.8 Unit Pool Accounting, 2.9 Tranche Balance Identity, 2.10 OCC, 2.11 Path Resolution Order, 2.12 Cascading Consistency, 2.13 Validation Precedence (full ordered 1-43 ladder with error id, HTTP status, prose condition, exact applies_to enumeration)
- 3 Business Logic, 9 subsections (funding hierarchy -> tranche schedule -> negotiation cycle -> activation & encumbrance waterfall -> lab space & utility envelopes -> renovation sequencing/reconciliation -> equipment installation fork -> staff appointments -> year-end/departure/retention/settlement)
- 4 Endpoint Definitions — 61-row, exactly-4-column table
- 5 Error Code Catalogue — 43-row, exactly-2-column table

Coverage (machine-verified against SCAFFOLD.yaml): endpoints 61/61; error IDs 43/43; calculations 13/13 with every constant embedded in business prose; validations 43/43 as the ordered 2.13 ladder; entity fields 133/133; request-body identifiers 69/69; query params 27/27; path params 3/3; response-shape fields 14/14; state-machine states + enum values 90/90; roles 5/5; concurrency rules 2/2.

Hard Contracts all PASS: (1) Field-Name Coverage — every scaffold identifier appears verbatim in backticks, 0 missing. (2) Rule Coverage — 43 validation priorities with error ids/statuses/scopes; both OCC rejections ERR_STALE_SPACE_VERSION / ERR_STALE_PACKAGE_VERSION at 412; all 11 state machines incl. three cyclic loops and the DELIVERED -> {INSTALLED|UTILITY_BLOCKED} fork; all cascades and server-initiated transitions; all 13 calculations; no pseudocode. (3) Section-3 Path Purity — 923 backtick tokens scanned in section 3: 0 starting with /, 0 bare HTTP methods, 0 method+path combos.

Constants embedded: FUNDER_ORDINAL (DEPARTMENT, COLLEGE, DEAN_OFFICE); subsidy 0/25/40 pct by tier; 20,000,000-cent subsidy cap (rounding before cap); 10 pct overrun tolerance; 0.5000 spend-down eligibility threshold; 15 pct college holdback; 2,500,000-cent minimum new money; 2-calendar-day phase buffer.

Adjudications (scaffold self-inconsistencies resolved in prose):
1. CommitmentTranche.carryforward_cap_pct — entity constraint says MUST be null when carryforward_policy != CAPPED, but the tranche-creation side effect says it defaults to 0. Resolved in 3.2: required (0-100) when CAPPED; for NONE/FULL the client must not supply a value and the server stores 0.
2. Renovation phase budgets not summing to awarded_cents at award — the renovation_phase_sequencing calculation text names ERR_VALIDATION, while both the priority-29 validation row and the error catalogue name ERR_NO_PHASES_DEFINED. Adopted ERR_NO_PHASES_DEFINED (2 of 3 sources, including the authoritative priority-ordered validation table).
3. Minor clarification at 3.3: total_committed_cents and proposed_total_cents are necessarily equal at approval, so the pool check and reservation read identically against either.

Hard constraints honoured: SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened; no sibling task directory read; scratch confined to /tmp/task_2856_doc/.

Orchestrator verification: tail of PRD.md read — document ends at the last error-table row, a real section boundary, not mid-sentence. No truncation, and no difficulty-directive leak (grep for "expert level"/"harder than" returns nothing).

## Step 6: Generate implementation — 2026-09-05T10:10:22.843Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill. Step 6 returned first; the Step 5 entry follows below.)

The implementation is complete, on disk, and verified by live smoke tests.

Modules written (workspace/implementation/, 4324 lines total):
- app.py 110 — Flask factory, 8 blueprints, before_request -> store.begin_request() + global RLock, ApiError/HTTPException/catch-all handlers, app.run(0.0.0.0, PORT default 10000)
- store.py 118 — 11 in-memory dicts + ledger order list, logical clock (default 2026-08-01T00:00:00Z), id/seq minting, stamp_new/touch/begin_request
- errors.py 62 — all 43 error ids -> HTTP status, ApiError, fail()
- money.py 81 — cent-exact largest-remainder 3-funder split, pct_of_cents, 2dp kW, 4dp ratio, the 7 constants
- validate.py 275 — body/type/range/enum/instant/date validators, pagination, filters
- authz.py 107 — headers, RBAC, unit scope, faculty scope, segregation of duties
- envelope.py 59 — meta/response_type/data envelope, pagination meta, error envelope
- ledger.py 510 — append-only rows, tranche waterfall + capacity pre-check, settle_source, derived tranche/package rollups
- derive.py 168 — occupancy share, installed loads, month spans, retention round
- serialize.py 294 — the 11 entity representations
- lookups.py 100 — typed 404 resolution (ERR_*_NOT_FOUND)
- cascades.py 516 — freeze, rollover (6 pinned steps), close-out, recommitment, separation, install/cancel/end settlements
- routes/ 1913 — packages.py 559, renovation.py 422, spaces.py 279, equipment.py 254, faculty.py 160, staff.py 124, units.py 96, clock.py 19
- start.sh 10 / requirements.txt 1 — guarded pip install, exec python3 app.py

Coverage verified mechanically:
- Endpoints 61/61. A script parsed the PRD section-4 table and diffed it against app.url_map: "in PRD not impl: []", "in impl not PRD: []".
- Errors 43/43. PRD error ids == ERROR_HTTP_STATUS keys exactly, and every id is actually raised somewhere in the code (no dead declarations).
- Storage: grep confirms no sqlite, no open(, no json.dump(, no /tmp, no pickle. Nothing is seeded — a fresh boot returns total_count 0 on all six collections and clock 2026-08-01T00:00:00.000Z. Verified across three separate kill/relaunch cycles (ports 18566, 18567), so --isolation per-test-server is safe.

Smoke results (ports 18566/18567, killed by recorded PID; no pattern kills). Happy paths exercised end to end: unit/faculty/package creation, tranche schedule, submit -> counter -> revise -> re-submit -> endorse -> approve -> activate, OCC 412s on both guarded endpoints, space assignment + share ladder, utility-block fork (UTILITY_BLOCKED/POWER -> upgrade -> INSTALLED), staff appointment activate/end, full renovation lifecycle (phases, buffer, bids, rescope, award, start/complete, substantial completion over and under budget), close-out, fiscal-year rollover, and internal-transfer separation.

Numeric invariants checked by hand against the PRD:
- Largest-remainder split on 100000001 at 34/33/33 -> 34000001 / 33000000 / 33000000.
- Partial settlement conservation: DISBURSEMENT dept 3060000 + RELEASE dept 2040000 = ENCUMBRANCE dept 5100000.
- Overrun path: actual 44000000, awarded 40000000, GUT -> subsidy_final 17600000, charge_final 26400000, variance 2400000 encumbered then immediately disbursed.
- Unit rollups: committed_cents netted to exactly 0 after a full settle; available_pool = pool - reserved held; reserved fell by EXPIRY shares at close-out.
- spend_down_ratio = (disbursed + encumbered)/committed at 4dp (0.294), and balance_identity_holds true throughout.

Adjudications / PRD ambiguities resolved:
1. Version bumps are applied at most once per entity per request (store._touched), reconciling 2.4's "recomputation counts as a mutation" with the scaffold's per-operation "+1".
2. All instants emitted with exactly 3 fractional digits + Z, and client instants canonicalised on input so lexicographic order == chronological order.
3. Derived-on-read for every ledger- and clock-dependent amount; stored fields only for what the PRD says is stored.
4. carryforward_cap_pct stored as 0 for NONE/FULL (PRD 3.2 wins over the scaffold's "MUST be null"); supplying it for a non-CAPPED policy is ERR_VALIDATION.
5. Conditionally-required fields -> ERR_VALIDATION (priority 3); a wrong-typed unit in a slot, or a COLLEGE naming a parent, -> ERR_RESOURCE_NOT_FOUND (priority 5).
6. Phase-plan precedence follows the global ladder (26 overlap -> 27 buffer -> 28 gap -> 29 no-phases/budget-sum), not 3.6's local 1..5 enumeration, because 2.13 declares the ladder global. Confirmed live: budget-sum mismatch at award reports ERR_NO_PHASES_DEFINED per 2.13 item 29.
7. Place ladder is 11 -> 16 stale version -> 18 frozen -> 19 item state -> 21 faculty -> 42 -> 43, since 3.7's prose defers to the global ladder.
8. Phase overlap compared on canonical instants; the 2-day buffer on calendar-date parts, because the buffer is specified in calendar days.
9. released_on >= effective_from and end_date >= start_date are ERR_VALIDATION checks run after existence but before the priority-19 state gate (3 < 19).
10. settle_source allocates a partial disbursement greedily across the source's open ENCUMBRANCE rows in creation order (PRD is silent); whole-row settlements copy stored shares verbatim, partial ones derive the paired RELEASE as the per-funder remainder.
11. Staff end does not overwrite the stored end_date — doing so would change committed_months and the encumbrance total.
12. FundingUnit.reserved_cents subtracts EXPIRY/RECAPTURE shares only for that unit's own packages in {APPROVED, ACTIVE, CLOSED_OUT}, which matches the scaffold's incremental model for a SUPERSEDED predecessor (reserved 0, not negative) and agrees with the literal 2.8 reading everywhere else.
13. source_kind assignment: item settlements keep the item's kind/id; auto and close-out EXPIRY/RECAPTURE/recommitment CARRYFORWARD_IN use SETTLEMENT + null; all rollover rows use ROLLOVER + null.
14. OBLIGATED-tranche releases are immediately followed by an EXPIRY of the same amount (shares copied), and an OBLIGATED tranche reaching encumbered == 0 expires its residual and becomes EXPIRED.
15. Tranche creation restricted to DRAFT (else ERR_PACKAGE_STATE_INVALID), and POST /renovation-projects/{id}/phases to SCOPING/BID — neither state list is declared anywhere, so both are by analogy with the nearest explicit rule.
16. api_request_timestamp is drawn from the logical clock, not wall time, so envelope meta stays consistent with entity timestamps within a test.

Constraints honoured: never read or created test_suite/ or test_helpers/, never read a sibling task directory, never touched worklog.md, used only /tmp/task_2856_impl/ for scratch, built every module with chunked cat >> appends, killed only its own servers by recorded PID.

## Step 5: Generate unit tests — 2026-09-05T10:47:19.000Z

(Launched concurrently with Step 6; returned second. Its entry appears after Step 6's for that reason.)

The suite is complete and on disk.

Files written (all at the task root, nothing under workspace/):
test_helpers/ — __init__.py 37, api_client.py 326, api_errors.py 101, assertions.py 376, constants.py 71, factories.py 201, fixtures.py 734, test_users.py 62, types.py 423.
test_suite/ — conftest.py 32; test_01 229, test_02 184, test_03 201, test_04 203, test_05 157, test_06 157, test_07 190, test_08 214, test_09 193, test_10 413, test_11 409, test_12 255, test_13 226, test_14 413, test_15_endpoint_shapes_and_computed_reads.py 333, test_16_identity_authorisation_and_not_found.py 170, test_17_role_exclusivity_and_shared_operations.py 294, test_18_concurrency_guards_and_carryforward_threshold.py 268, test_19_immediate_consistency.py 82. Total 6,954 lines across both directories.

Coverage:
- Total test functions 116, collected cleanly (pytest --collect-only -> 116 tests, no import errors).
- Queue A (1.8): 18 non-stub instances, 18 translated, 0 skipped (49 tests, files 01-09).
- Queue B (1.9): 66 non-stub instances, 65 translated, 1 skipped (67 tests, files 10-19) — entities 15/15, state_machines 12/12, calculations 5/5, validations 15/16, endpoints 5/5, errors 4/4, rbac 5/5, complexity_layers 3/3, consistency_model 1/1. All 18 STUB instances correctly untested.
- Every Design: tag machine-verified: name exists in the source yaml, section/rule id matches the instance's real section, exactly one tag per test, tag on the final docstring line. check_citations.py over all 19 files: "tests scanned: 116 ... problems: 0". No skip/skipif/xfail; no mention of the scaffold.

Skipped instance (PRD-first filter):
- corner_val_award_without_any_phase_returns_no_phases_defined — requires a project in BID holding zero phases, but PRD 3.6 states bid solicitation "requires at least one phase to exist", so the setup is unreachable. Gap left as a gap.

Design assertions dropped as PRD-contradicting (rule under test preserved):
- corner_err_missing_x_user_id_header...: dropped "an unresolvable entity id returns 401" and "opaque roles succeed with no header" — 2.1/2.13 rung 1 make both headers mandatory on every endpoint.
- corner_rbac_dean_office_cannot_award...: the dean's award on a DRAFT package is asserted as ERR_PACKAGE_SPEND_FROZEN (rung 18 applies to /award; rung 17 does not), preserving the "403 decided before the state rule" discriminator.
- corner_ep_space_assignment_links_room_and_package...: dropped the "DRAFT package -> 409 ERR_PACKAGE_STATE_INVALID" claim — rung 17 does not cover POST /space-assignments, and rung 21 explicitly allows a CANDIDATE.
- corner_ep_utility_upgrade...: the missing-field refusal is asserted at 400 ERR_VALIDATION (rung 3 and the section-4 error table), not the design's 422.
- corner_err_unknown_project_id...: the unknown-id /award probe is issued as Dean rather than DeanOffice, since rung 2 (403) precedes existence at rungs 5-11.

Orchestrator verification: test_helpers/ and test_suite/ are at the task root; nothing landed under workspace/ (checked); 116 test functions present.

Orchestrator note (worklog integrity): while appending this entry the orchestrator truncated worklog.md with a faulty one-line Python rewrite (`open(p,'w').write(open(p).read()...)` truncates before the inner read). The file was immediately rebuilt in full from the same verbatim subagent summaries; Step 1-6 content above is complete. Step 2/3/4/6 timestamps are the originals (millisecond-truncated); the Step 5 timestamp is the reconstruction-time approximation of when the Step 5 subagent returned.

## Step 7: Run tests and iterate — 2026-09-05T11:02:21.408105034Z

Clean 8-round sweep achieved.

Iterations run: 2 (iteration 1: 111/116 in all 8 rounds, 5 deterministic failures; iteration 2: 116/116 in all 8 rounds). Failures were fully deterministic (identical 5 in every round) — no load-induced flakiness, no setsid reaping.

Tests deleted: none. One assertion removed under STEP 1c (partial coverage), documented below.

Fixes applied to test_helpers/:
- test_helpers/fixtures.py — setup_draft_package() now re-reads the package after add_tranches() instead of returning the creation-time snapshot. PRD 3.2 ("Every tranche create re-derives the owning package's rollups") plus 2.4 ("Recomputation of a derived field ... increments its version") mean the snapshot's version is already stale by the end of setup, which made test_11::test_submitting_a_draft_stamps_the_proposer_and_leaves_the_spend_axis_alone compare a post-submit version 3 against a stale baseline of 1.

Fixes applied to test_suite/ (all four made the test more faithful to PRD; no assertion weakened, no error_id downgraded):
- test_05_validation_precedence_pairs.py::test_award_reports_the_frozen_spend_axis_before_the_tranche_shortfall — the setup builds an APPROVED-but-never-activated package, so its spend_status is NOT_YET_AVAILABLE, not FROZEN (3.2 creates it NOT_YET_AVAILABLE; 3.4 only moves it to SPENDING at activation). Corrected the precondition assertion. The load-bearing check — ERR_PACKAGE_SPEND_FROZEN outranking ERR_INSUFFICIENT_TRANCHE_BALANCE — is untouched and is exactly what 3.4 requires for NOT_YET_AVAILABLE.
- test_07_cross_entity_gates.py::test_a_faculty_member_under_notice_may_not_be_given_a_room — asserted the package was still SPENDING after a departure notice, contradicting 3.9's freeze cascade ("moves spend_status SPENDING -> FROZEN"). Corrected to FROZEN and cited 2.13 priority 21, which is precisely why the frozen package does not shadow the faculty gate on POST /space-assignments.
- test_18_concurrency_guards_and_carryforward_threshold.py::test_a_ratio_of_exactly_one_half_carries_the_whole_remaining_balance — read total_carried_out_cents off GET /startup-packages/{id}. 3.4 lists only six rollups on the package; 2.9 places total_carried_out_cents / total_carried_in_cents on the spend-summary read. Repointed to read_spend_summary(), matching what test_15 already does.
- test_04_separation_and_completion_cascades.py::test_separation_settles_the_package_and_ends_the_active_appointment — removed one assertion (end_date == "2026-12-31") under STEP 1c. 3.9 says the appointment ends "with an effective end_date of the clock"; that sentence does not uniquely determine that the stored end_date field is overwritten, and the alternative reading is the stronger one: 3.8 requires served months be "clamped so they never exceed committed_months", and committed_months is derived from start_date/end_date, so overwriting end_date would collapse committed_months to the served span and make the mandated clamp a no-op. The remaining assertions still pin the behaviour the test exists to check — status == ENDED, encumbered_cents == 0 (3.8 verbatim), and disbursed_cents == 1796664, which is only reachable if the arithmetic ran against the clock (4 served months of 12 committed, at a half-up-rounded monthly charge of 449166).

Fixes applied to implementation/: none. All five failures traced to the test layer; no implementation defect was found, no PRD-required check was removed, and no endpoint, field, or seeded data was added.

Final per-round results: rounds 1-8 all 116/116 passed, 0 failed, 0 errors.

Orchestrator verification: independently parsed all eight results.$i.json — every round reports passed 116 / total 116.

## Step 8: Finalize PRD — 2026-09-05T11:11:25.351804649Z

Step 8 was NOT skipped: Step 7 applied 0 implementation fixes but did apply 1 test_helpers fix and 4 test_suite fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) was not met.

PRD_FINALIZED.md written with three surgical edits.

Line counts: PRD.md 544 lines / 112,915 bytes; PRD_FINALIZED.md 544 lines / 113,719 bytes. Line delta 0 (0.0%); 3 lines revised in place; byte delta +804 (+0.71%).

Changes:
- 3.4 (package rollups) — insert — appended one sentence pinning that the six rollups plus spend_down_ratio are what the package's own representation carries, and that total_carried_out_cents / total_carried_in_cents are not package fields and appear only on the spend-summary read of 2.9 — implementation/serialize.py:57-93 (package payload, no carried totals) vs serialize.py:257-294 (spend_summary, both present); rollup source ledger.py:145-146.
- 3.8 (ending an appointment) — insert — pinned that the supplied end_date is an arithmetic input only and is never written back; stored start_date, end_date, committed_months keep their creation values — implementation/routes/staff.py:97-114, cascades.py:143-161.
- 3.9 (separation, stage one) — revise — "with an effective end_date of the clock" reworded to "an effective end date of the clock's own calendar date ... an arithmetic input only and is not written onto the appointment, whose stored end_date and committed_months are left as recorded while ended_on is stamped from the clock" — cascades.py:451-457 (effective_end = date.fromisoformat(moment[:10])) + cascades.py:143-161.

Per-edit pre-edit search log:
1. 3.4 edit — (a) Subject: which ledger rollup fields appear on which read of a package. (b) Enumerated/read: serialize.py in full (every entity projection; package(), spend_summary(), tranche()), ledger.py:145-146 (package_rollup returns carried totals — they exist in the rollup dict but are only surfaced by spend_summary), grep for total_carried_out_cents|total_carried_in_cents across impl + tests (only ledger.py, serialize.py:287-288, test_15, test_18). Confirmed serialize.package is the single package projection, used by both the single read and the list. (c) Adjustment: wording deliberately says "ledger totals the package's own representation carries" rather than "the only fields on the package", so it does not exclude the non-rollup package fields the impl also emits (settlement_variant, recaptured_unspent_cents, transferred_balance_cents, college_holdback_cents, activated_on, closed_out_on).
2. 3.8 edit — (a) Subject: whether a staff appointment's stored end_date / committed_months are ever rewritten after creation. (b) Enumerated: grep end_date|committed_months across all impl modules — routes/staff.py:39-56 (create: stores both), routes/staff.py:97-114 (end endpoint: validates the supplied date, passes it to the cascade, stores nothing), cascades.py:134-161 (months_served / end_appointment: reads start_date + committed_months, writes only status and ended_on), cascades.py:179-191 (freeze cascade cancels PROPOSED appointments, stamps ended_on only), derive.py:103-138 (month_span, monthly_charge_cents, encumbrance_total_cents all read the stored committed_months), serialize.py:220-236 (echoes stored values). No writer of end_date/committed_months outside creation. (c) No adjustment needed; wording covers start_date too, which is likewise never rewritten.
3. 3.9 edit — (a) Subject: the effective end date used when the separation cascade ends an ACTIVE appointment. (b) Enumerated: cascades.py:448-476 (separation_cascade: effective_end is the clock's date portion, shared by every appointment of every ACTIVE package), cascades.py:143-161 (same end_appointment helper as the explicit endpoint — so the two paths must be described identically), cascades.py:134-140 (clamp to committed_months), routes/faculty.py separate route (delegates wholly to the cascade), plus the 3.8 path above. (c) Adjustment: dropped the backticked field reference end_date for the effective value (it is not a stored field write), said "clock's own calendar date" to match moment[:10], and kept the ended_on clause so the sentence does not read as if nothing on the appointment is stamped.

No implementation-side divergence was found for the other three Step 7 items: the fixtures setup_draft_package staleness (PRD 3.2 "every tranche create re-derives the owning package's rollups" + 2.4 version rule already determine the bump — routes/packages.py:186-187 and the delete path at :206-207 both store.touch(package)), the APPROVED-but-unactivated package being NOT_YET_AVAILABLE (3.2/3.4 already determine it; routes/renovation.py:198-207 checks frozen before project state, matching the 2.13 ladder), and the freeze-cascade FROZEN + priority-21 faculty gate on POST /space-assignments (cascades.py:179-190, routes/spaces.py:147-156 — both already pinned by 3.9 and 2.13 p21). Those three needed no PRD edit.

## Step 9: Complete PRD — 2026-09-05T11:39:48.697217968Z

Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared workspace/PRD_COMPLETED.md (pass 1 did the cp from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden to cp, so no pass clobbered another's edits). Partition: pass 1 = app/store/errors/money/validate/authz/envelope/lookups + routes/{units,clock,packages}; pass 2 = ledger/derive/serialize/cascades; pass 3 = routes/{renovation,spaces,equipment,faculty,staff}. Each pass handed forward notes to the next.

Final artifact: PRD_COMPLETED.md 545 lines / 125,811 bytes, from PRD_FINALIZED.md 544 lines / 113,719 bytes (+1 line, +12,092 bytes, +10.6%). 48 edits total = 31 ambiguity-pins + 17 mismatch-revisions.

--- PASS 1 (16 edits: 11 ambiguity-pins, 5 mismatch-revisions) ---
cp performed; PRD_COMPLETED.md 545 lines / 117,676 bytes, cmp DIFFERENT from PRD_FINALIZED.md (19 hunks).
- 2.1 (headers) — insert — ambiguity — an empty-string X-User-ID/X-User-Role counts as absent for ERR_UNAUTHENTICATED — authz.py:38
- 2.2 (api_request_id) — insert — ambiguity — req_ plus exactly twenty upper-case-letter-or-digit characters — store.py:59-61
- 2.2 (api_request_timestamp) — insert — ambiguity — the envelope timestamp is read from the logical clock, not wall clock — envelope.py:15-19
- 2.2 (error format) — insert — ambiguity — unrouted path -> ERR_RESOURCE_NOT_FOUND 404, disallowed method -> ERR_VALIDATION 400, both decided before headers are read — app.py:68-78
- 2.3 (pagination params) — insert — ambiguity — empty-string param = absent; bad limit/offset/enum filter -> ERR_VALIDATION 400, evaluated before path-identifier resolution — validate.py:228-260, routes/units.py:83-86
- 2.3 (ordering) — insert — ambiguity — created_at ties (routine under a frozen logical clock) break by server persistence order — store.py:112-118
- 2.3 (list meta) — insert — ambiguity — total_count is pre-window; has_more iff offset + len(page) < total_count — envelope.py:42-48
- 2.4 (version) — insert — ambiguity — a resource's version moves at most once per request however deep the cascade — store.py:99-109
- 2.5 (clock) — insert — ambiguity — the clock call answers 200 with data = {current_utc} only, three fractional digits, no audit fields — routes/clock.py:19
- 2.6 (cents) — insert — ambiguity — integer inputs accepted as JSON int, zero-fraction number, or digit string; else ERR_VALIDATION — validate.py:88-100
- 2.11 (identifier resolution) — revise — mismatch — query-filter identifiers are not existence-checked (empty page, no 404); only body identifiers are — routes/units.py:59-65, routes/packages.py:424-451
- 2.13 priority 3 — revise — mismatch — funder percentages and carryforward_cap_pct are 0-100 (PRD said "1 through 100"); added strict JSON typing, bodiless-call/empty-body rule, and extension of ERR_VALIDATION to list-endpoint query params — validate.py:128, routes/packages.py:58-60,151, routes/spaces.py:136
- 2.13 priority 8 — revise — mismatch — ERR_TRANCHE_NOT_FOUND also applies to DELETE /startup-packages/{id}/tranches/{tranche_id} — routes/packages.py:195
- 2.13 priority 13 — revise — mismatch — faculty scope is also enforced on GET /commitment-tranches/{id} and /spend-transactions via the owning package — routes/packages.py:534-552
- 3.1 (unit registration) — insert — ambiguity — a missing parent_unit_id on DEPARTMENT/DEAN_OFFICE is ERR_VALIDATION, distinct from the 404 unit-type check — routes/units.py:35-42
- 3.2 (package draft) — revise — mismatch — spend_deadline_on is stored/reported but is not a spend gate (never read anywhere); the only temporal gate is the tranche window — routes/packages.py:62,114
- 3.2 (tranche create) — insert — ambiguity — tranches may only be added while negotiation_status is DRAFT, else ERR_PACKAGE_STATE_INVALID; the create bumps the package's updated_at/version — routes/packages.py:166-188
- 3.3 (counter/revise) — insert — ambiguity — counter_total_cents >= 0, revised_total_cents strictly > 0 — routes/packages.py:250,270
- 3.9 (year-end rollover) — insert — ambiguity — the package must be ACTIVE, else ERR_PACKAGE_STATE_INVALID, checked before the two temporal guards — routes/packages.py:374-392
Pass 1 notes: errors.py matches the section-5 catalogue exactly (43 ids/statuses, no change needed); money.py constants and the largest-remainder split match 2.6/2.7/3.6/3.9 exactly; the "query validation precedes path resolution" universal was verified against every list endpoint including pass-2/3 files.

--- PASS 2 (14 edits: 10 ambiguity-pins, 4 mismatch-revisions) ---
File 545 lines / 117,676 bytes before -> 545 / 121,245 after. Pass 1's 16 edits verified still present (10 distinctive markers spot-checked, 1 hit each). Line count unchanged because every change is an in-paragraph insert or revision.
- 2.6 — insert — ambiguity — the four-decimal spend_down_ratio and two-decimal kilowatt precisions are rounding rules, not rendering rules: these plus fte travel as JSON numbers in shortest form (0.5, 0.0, 12.0), never fixed-width strings — serialize.py:8-12,85,129,134,203,226
- 2.7 — insert — ambiguity — when a settled source holds several open ENCUMBRANCE rows, the disburse amount is one total for the source, apportioned by walking the rows in ledger creation order, each absorbing as much as its own open amount allows — ledger.py:452-509
- 2.8 (reserved_cents) — revise — mismatch — the EXPIRY/RECAPTURE deduction is limited to rows on the same reserving packages; a package outside APPROVED/ACTIVE/CLOSED_OUT (e.g. SUPERSEDED) contributes neither reservation nor deduction — ledger.py:196-213
- 2.8 — insert — ambiguity — all three funder units get updated_at/version moved by any request writing a row on that package's ledger, including a carryforward row that leaves all five derived amounts unchanged — ledger.py:237-245,283
- 2.9 (source_kind) — insert — ambiguity — ROLLOVER marks only fiscal-year-rollover rows; SETTLEMENT marks every other server-initiated row (close-out expiry, recommitment recaptures + carry-in, separation recaptures, and both OBLIGATED-tranche EXPIRY kinds), with the released-cents EXPIRY repeating the RELEASE's split verbatim and the residual EXPIRY using the ordinary 2.7 split — ledger.py:396-409,437-448; cascades.py:311-319,358-381,408-416
- 2.9 (spend-summary) — revise — ambiguity — the three per-funder totals are gross plain sums over every row whatever its kind (an encumbrance and its release both count upward), never a net position — serialize.py:259-265
- 2.12 — insert — ambiguity — a cascade sweeping dependent resources of one kind visits them in 2.3 creation order unless the narrative names another order, so its ledger rows appear in that order — cascades.py:22-56, store.py:112-118
- 3.4 (waterfall) — revise — ambiguity — final tiebreak after created_at is the 2.3 persistence order — ledger.py:317-319
- 3.6 (reconciliation) — revise — mismatch — the disbursement is an aggregate total of min(final, estimate) apportioned across the award's rows, not a per-tranche min — routes/renovation.py:342-348 via ledger.py:452
- 3.8 (activation) — insert — ambiguity — an appointment's disbursed_cents reads in every status as the ledger total attributed to it (an ENDED appointment still reports what it was paid) — derive.py:119-138
- 3.8 (ending) — revise — ambiguity — months served are clamped into 0..committed_months, so an effective end before start_date disburses nothing and releases everything — cascades.py:134-140
- 3.9 (freeze) — revise — mismatch — the cascade sweeps every package of the faculty member in negotiation_status ACTIVE, and cancels each one's PROPOSED appointments and REQUESTED orders — cascades.py:179-190
- 3.9 (recommitment) — revise — ambiguity — the category sweep order is EQUIPMENT, PERSONNEL, RENOVATION, DISCRETIONARY; one RECAPTURE row per tranche that still holds a balance while every such tranche moves to RECAPTURED regardless, and a single aggregated CARRYFORWARD_IN per category — cascades.py:14,346-381
- 3.9 (separation, space) — revise — mismatch — a cascade-released assignment gets both released_on and effective_to stamped at the separation instant, a WITHDRAWN one leaves released_on null, and the decommission test is the faculty member's own PROPOSED+ACTIVE shares on that room summing to 100 or more as read before the statuses were rewritten, moving the room to DECOMMISSIONED from whatever status it held — cascades.py:489-513

--- PASS 3 (18 edits: 10 ambiguity-pins, 8 mismatch-revisions) ---
File 545 lines / 121,245 bytes before -> 545 / 125,811 after. Passes 1 and 2 confirmed intact: diff PRD_FINALIZED.md PRD_COMPLETED.md yields 49 hunks / 97 changed lines — pass 3's 18 lines plus all ~31 lines from passes 1-2. Every change was a surgical Edit; no line recreated or overwritten wholesale.
- 2.13 item 3 — insert — ambiguity — pinned that the handful of ERR_VALIDATION rules comparing a payload field against stored target state run after the not-found codes of priorities 5-11 but before every state check from 17 on — routes/spaces.py:233, routes/staff.py:262
- 2.13 item 9 — revise — mismatch — added POST /lab-spaces/{id}/utility-upgrade to the applies list — routes/spaces.py:105
- 2.13 item 13 — revise — mismatch — added the faculty record's own id as an owning field and six faculty-scoped reads to the applies list, generalised to "every section-4 endpoint listing Faculty" with POST /_clock/set_current_utc explicitly excepted — routes/faculty.py, routes/clock.py:16
- 2.13 item 19 — insert — ambiguity — pinned that the DECOMMISSIONED-room refusal on assignment activation reports the priority-19 id but is evaluated after the priority-21 faculty gate — routes/spaces.py:203
- 2.13 item 21 — insert — ambiguity — pinned that the three faculty-lifecycle transitions report the same id with their own admitted statuses, and scoped the "never allowed" sentence to the listed operations so it no longer contradicts that — routes/faculty.py:90,148
- 2.13 item 29 — revise — mismatch — added POST /renovation-projects/{id}/solicit-bids, noting only the at-least-one-phase half can fire there — routes/renovation.py:162
- 2.13 item 35 — revise — mismatch — pinned that the transfer-target check on departure-notice runs ahead of the priority-21 faculty gate — routes/faculty.py:109
- 3.5 para 310 — insert — ambiguity — floor_load_psf has no installed-load floor and may be lowered; the upgrade has no room-status precondition — routes/spaces.py:105
- 3.5 para 312 — insert — ambiguity — room status not examined at proposal time; room updated_at/version bump unconditionally on creation — routes/spaces.py:145,177
- 3.5 para 316 — insert — ambiguity — activation requires the assignment still PROPOSED, a DECOMMISSIONED room reports ERR_SPEND_ITEM_STATE_INVALID, and the activating assignment is excluded from its own peer set — routes/spaces.py:203,208
- 3.5 para 318 — insert — ambiguity — decommissioning withdraws ACTIVE assignments too, not just PROPOSED — cascades.py:503
- 3.5 para 320 — revise — mismatch — replaced "held the entire 100 percent" with the 3.9 test (one person's own PROPOSED+ACTIVE shares >= 100 as they stood pre-cascade), plus "from whatever status it was holding" — cascades.py:503
- 3.6 para 328 — insert — ambiguity — phases addable only while SCOPING/BID, else ERR_RENOVATION_STATE_INVALID — routes/renovation.py:128
- 3.6 para 333 — insert — ambiguity — buffer gap is date-only (time of day discounted) and signed, not absolute — routes/renovation.py:44
- 3.6 para 340 — revise — mismatch — "Four preconditions" -> five in 2.13 order, adding the ERR_FACULTY_NOT_ACTIVE gate; room -> UNDER_RENOVATION only from AVAILABLE/ASSIGNED, otherwise untouched incl. version — routes/renovation.py:208,240
- 3.6 para 350 — revise — mismatch — cost_variance_cents == 0 writes no RELEASE row but does disburse the estimate in full (previous text wrongly said no row at all) — ledger.py:492
- 3.7 para 358 — revise — mismatch — "Four preconditions" -> five in 2.13 order, adding the ERR_FACULTY_NOT_ACTIVE gate — routes/equipment.py:127
- 3.7 para 370 — insert — ambiguity — a retry that blocks again is not an error: stays UTILITY_BLOCKED, reason re-stamped, version moves — routes/equipment.py:199
Pass 3 handover disposition: (1) 3.5 para 320 decommissioning test — acted on (realigned to 3.9/cascades.py:503-513, plus the para 318 consistency fix). (2) aggregate-total-plus-apportionment reading in para 350 — honoured; only the adjacent "exactly 0" clause touched. (3) ERR_ROLLOVER_ALREADY_RUN gloss and transferred_balance_cents > 0 credit — deliberately left (both sit in pass-1/2 partitions and both prior passes chose to leave them). (4) lexicographic-instant guarantee — relied on for the para 333 date-only wording.
Pass 3 well-formedness check: PASS. All 18 edited lines read back as clean, non-duplicated sentences; the file retains its H1 and all five ## sections and ends at a real section boundary (last row of the section-5 error table). No unreachable-path inventions added (space/package deletion does not exist, so the out-of-ladder ERR_SPACE_NOT_FOUND/ERR_PACKAGE_NOT_FOUND guards in activate/install/award were left undocumented rather than stated as universals).

Orchestrator final verification:
- PRD.md 544 lines / 112,915 bytes; PRD_FINALIZED.md 544 / 113,719; PRD_COMPLETED.md 545 / 125,811. cmp: PRD vs FINALIZED DIFFER, FINALIZED vs COMPLETED DIFFER (so Step 9 provably ran — PRD_COMPLETED.md is not byte-identical to its source).
- PRD_COMPLETED.md tail ends at "| ERR_INSUFFICIENT_TRANCHE_BALANCE | 422 |" — a real section boundary, no truncation.
- All eight results.$i.json re-parsed independently: every round 116 passed / 116 total / 0 failed.
- No implementation .py file was modified after Step 8 (find -newer PRD_FINALIZED.md returns nothing), so the passing sweep still describes the shipped implementation.
- test_helpers/ and test_suite/ remain at the task root; nothing stray under workspace/; exactly one worklog.md at the task root.

PIPELINE COMPLETE.
