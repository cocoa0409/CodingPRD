# Worklog — task_2933_craft_brewery_taproom_self_distribution_operations

## Step 1: Create task directory — 2026-09-05T18:27:39.275418704Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2933_craft_brewery_taproom_self_distribution_operations and /home/ubuntu/github/CodingPRD/tasks/task_2933_craft_brewery_taproom_self_distribution_operations/workspace (pre-assigned path from orchestrator args; no index scan performed).

## Step 2: Generate scaffold — 2026-09-05T19:49:50.604823424Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the lint is clean.

Lint verdict (verbatim, final run):

```
SCAFFOLD 1.8/1.9 -> 1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2933_craft_brewery_taproom_self_distribution_operations/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2933_craft_brewery_taproom_self_distribution_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2933_craft_brewery_taproom_self_distribution_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  1.5 endpoints declared:    58
  1.1 entities declared:     12
  1.8 instances scanned:     18
  1.9 instances scanned:     58
  Calls scanned (1.8+1.9):  965

VERDICT: clean lint — all 1.8/1.9 calls conform to 1.5 and all 1.1 FKs have reverse-reachability in 1.5.
```

Files (all parse with yaml.safe_load):
- SCAFFOLD.yaml — 2960 lines
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1604 lines, single key scaffold_difficulty_design
- SCAFFOLD_CORNER_DESIGN.yaml — 3991 lines, single key scaffold_corner_design

Scaffold surface (1.0–1.7): 12 entities; 13 state-machine dimensions / 56 transitions (shape parallel); 2 OCC concurrency rules (packaging-run-create-stale-batch -> ERR_STALE_BATCH_VERSION, appointment-create-stale-license -> ERR_STALE_LICENSE_VERSION); 7 calculations (2 dual-variant); 29 validations, priorities 10–61; 58 endpoints (23 GET / 35 POST) plus the POST /_clock/set_current_utc logical clock; 64 error codes; 5 roles (BreweryAdmin, ComplianceOfficer, CellarOperator, TaproomStaff, StateRegulator) under segregation_of_duties; complexity layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; consistency immediate; difficulty expert_plus.

Rule families covered: brewers-notice / formula / COLA prerequisites gating every sale path; tank-and-batch scheduling with a 12 h CIP buffer on half-open occupation intervals; packaging runs with a barrel-conservation ledger and a dual-basis loss allocation (PRO_RATA vs LAST_RUN_ABSORBS); taproom pour metering with growler/crowler sanitation bands (150–400 ppm, >=60 s) and label completeness; keg float lifecycle with depletion variance and a 2% shrinkage tolerance; self-distribution licence windows, territory coverage and annual barrel caps; wholesaler franchise appointment, scope exclusivity, good cause and statutory termination notice; landed cost with tiered freight discounts plus a 3% franchise fee; excise reporting with CBMA federal tiering, the split state rate and a 50% small-brewer credit under 15 000 bbl, including amending/superseding returns; off-site event/festival permits with a per-state concurrency cap of 2 and a 25.00 bbl annual event ceiling.

1.8: 9 rule_ids x 2 = 18 instances. 1.9: 76 instances across all nine guide sections (58 with full test_recipe, 18 excluded_because stubs, every stub citing an existing 1.8 instance name). All 64 declared error codes are exercised by at least one 1.8/1.9 recipe.

Two fixes made during the final pass: 13 stubs cited difficulty_instance as "<rule_id> / <name>" and were rewritten to the bare instance name (the skill requires a name-level match), and the not-found instance was extended so the six remaining 404 codes (batch, state licence, appointment, order, report, event permit) are triggered. One earlier SCAFFOLD.yaml edit closed a spec gap: PackagingRun.bbl_removed now defines BBL_PER_UNIT numerically. worklog.md and workspace/ were not touched; scratch stayed in .scratch/step2/.

Orchestrator verification: all three files present; SCAFFOLD.yaml scenario key contains only the scenario text (difficulty directive did not leak); workspace/ intact.

## Step 3: Copy shared files — 2026-09-05T19:49:50.611807449Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T20:08:36.585258480Z

Subagent summary (verbatim):

PRD generation for task 2933 is complete.

Deliverable: workspace/PRD.md — 527 lines, 118,914 bytes, built with one Write plus eight chunked `cat >> ... <<PRDEOF` appends (no single-shot write, no truncation).

Section list: title; 1. Introduction; 2. Global Specifications (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Version Counter, 2.5 Logical Clock, 2.6 Barrels/Ounces/Cents and Rounding, 2.7 Optimistic Concurrency on Parent Records, 2.8 The Rejection Ladder, 2.9 Cascade Discipline and Conservation of Packaged Barrels, 2.10 Flat Collections/Reverse Reachability/Filters); 3. Business Logic & Workflows (3.1 Federal Prerequisites, 3.2 Cellar Vessels/Brew Scheduling/Batch Lifecycle, 3.3 Packaging Runs/Barrel Ledger/Loss Allocation, 3.4 The Keg Float, 3.5 Taproom Bar: Pours/Growlers/Crowlers, 3.6 State Licences/Wholesaler Appointments/Franchise Trap, 3.7 Distribution Orders, 3.8 Excise Determination, 3.9 Off-Site Events/Festivals/Farmers Markets); 4. Endpoint Definitions (58 rows verified); 5. Error Code Catalogue (64 rows verified).

Hard Contract reports: Contract 1 Field-Name Coverage PASS (159 candidate identifiers, 0 missing; all 30 CONSTANT_NAME symbols absent by design with numeric values present). Contract 2 Rule Coverage PASS (all 64 error IDs in prose not only the table; 2.8 renders all 29 validations as ladder rungs in scaffold priority order 10-61; all 13 state-machine dimensions over 11 entities including system-triggered transitions and deliberate absences; all 7 calculations, both OCC rules, three depth-3 cascades, sibling-branch symmetry, field defaults, all 5 roles). Contract 3 Path Purity PASS (1,184 backticked tokens in 3 scanned: 0 slash-paths, 0 bare methods).

Also verified: 2.2 byte-identical to the shared response-structure section; no fuzzy-language or pseudocode hits; document ends cleanly at the last row of the 5 table.

Constraints honoured: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped or referenced; no sibling task read; worklog.md untouched; scratch confined to .scratch/step4/.

Two scaffold ambiguities resolved explicitly in prose: (1) DistributionOrder.channel — a "live" appointment is one whose state is ACTIVE or TERMINATION_REQUESTED; PROPOSED does not count. (2) Keg movements — both CellarOperator and TaproomStaff may record any of the five movement_type values (RBAC is endpoint-level), rather than inventing a role restriction the scaffold does not declare.

Orchestrator truncation guard: verified 527 lines / 118,914 bytes; tail ends at the final ERR_EVENT_BARREL_CAP_EXCEEDED row of the 5 table (a real section boundary, not mid-sentence); heading scan shows all sections 1-5 present. No difficulty-directive leak (grep for "expert"/"scaffold" returns nothing).

## Step 6: Generate implementation — 2026-09-05T20:39:09.426399474Z

Subagent summary (verbatim):

Implementation complete for task_2933_craft_brewery_taproom_self_distribution_operations.

Modules written (workspace/implementation/): derive.py 509 (derived fields + 12 serialisers); validation.py 344 (ladder rungs 1-3, field/query validators); routes_excise.py 319 (excise returns + event permits); routes_kegs.py 318 (keg float + taproom pours); routes_licensing.py 258 (state licences + appointments); routes_brewery.py 257 (brewery, notice, beers/filings); routes_cellar.py 243 (tanks + batches); cascades.py 235 (depth-3 cascades, lazy expiry, loss allocation); routes_orders.py 213 (submit/allocate/ship/cancel); calc.py 192 (7 calculations + all constants); routes_runs.py 155 (packaging runs); store.py 138 (in-memory dicts + logical clock); helpers.py 116; errors.py 103 (64-entry status map); app.py 87 (factory, blueprints, error handlers, /_clock/*); envelope.py 62; start.sh 16; requirements.txt 1. Total 3,566 lines. All modules py_compile-clean.

Endpoints: 59 Flask rules = the 58 declared endpoints (23 reads, 35 writes incl. POST /_clock/set_current_utc) plus one extra read-only GET /_clock/current_utc used for boot verification.

Smoke + behavioural verification (PORT=18933, then a fresh boot on 18934): envelope shape confirmed on 2xx object, 2xx array (limit/offset/total_count/has_more), and error paths: 401 blank headers, 403 role-before-body, 400 limit=0, 404 ERR_BREWERY_NOT_FOUND, 409/412/422 families. Two scripted end-to-end walkthroughs (~110 assertions, all matching expected status) covered: notice lifecycle + depth-3 suspend/reinstate cascade, formula/COLA filings, tank CIP + schedule-conflict buffer, batch auto-close, OCC 412 on both rules, keg clean/fill/tap/return with depletion variance and run reconciliation, growler sanitation/label/SOD gates, allocation waterfall (success and all-or-nothing INSUFFICIENT_INVENTORY), shipment cap, cancel compensation, appointment approve/terminate timeline, excise draft/file, permit submit/decide with both ceilings, and lazy licence expiry on clock advance. PRD worked examples reproduced exactly: PRO_RATA loss shares 0.334/0.333/0.333, LAST_RUN_ABSORBS 0.000/0.000/1.000, void re-allocation 3.000/3.000, freight/franchise landed cost 160000 + 31320 + 5740 = 197060. Fresh boot from a foreign cwd: clock reads exactly 2026-08-01T00:00:00.000Z, all 11 collections total_count 0, brewery 404 — no seeding, no persistence. Both smoke servers were killed by their own listener PID/process-group looked up from ss -ltnp on ports 18933/18934. No pkill was used at any point.

Two spec ambiguities flagged for Step 7: (1) conditional required fields (notice reason, CIP readings, cola_id, returned_volume_gal, good_cause_code) are validated AFTER transition legality, since a transition-error test may omit them — unconditional fields stay at rung 3; (2) ERR_LICENSE_NOT_ACTIVE is enforced on POST /distributor-appointments/{id}/approve per the state-machine precondition even though ladder priority 33 applies_to omits it.

## Step 5: Generate unit tests — 2026-09-05T21:25:41.888249014Z

Subagent summary (verbatim):

Both remaining files are written and verified. Step 5 is complete.

Files written in the final session: test_suite/test_17_cross_cutting_layers.py 340 lines / 3 tests (3 x Corner/cross_cutting_complexity_layers/); test_suite/test_18_consistency_model.py 151 lines / 1 test (1 x Corner/consistency_model/). Both py_compile clean and pyflakes clean (zero warnings on any file in test_suite/; the only pyflakes output across the tree is the deliberate noqa-marked re-export facade in test_helpers/__init__.py).

Full Step 5 output (task root — verified, nothing under workspace/):
- test_helpers/ — 9 files, 2356 lines (__init__ 98, api_client 272, api_errors 160, assertions 191, constants 321, factories 463, fixtures 482, test_users 112, types 257)
- test_suite/ — conftest.py (16) + 18 test modules, 6825 lines, 94 tests. Queue A: test_01-test_09, 36 tests / 2113 lines. Queue B: test_10 (429/11), test_11 (441/8), test_12 (623/8), test_13 (487/7), test_14 (396/5), test_15 (1209/12), test_16 (626/3), test_17 (340/3), test_18 (151/1) — 58 tests.
- find under workspace/ returns no test_helpers/test_suite; workspace/ holds only INSTRUCTION.md, PRD.md, implementation/, sweep.sh (implementation never read or written). worklog.md untouched. Scratch confined to .scratch/step5/.

Coverage: Queue A (Difficulty 1.8) 18 non-stub instances, 18 translated, 0 skipped (each rendered as a two-test pair, variant A / variant B, hence 36 tests). Queue B (Corner 1.9) 58 non-stub instances, 58 translated, 0 skipped (13 stubs correctly not translated: 4 state_machines, 4 calculations, 4 validations, 1 endpoints, 5 cross_cutting — all pointing at a difficulty instance that already owns the claim). Skipped instances: none. No skip/xfail/placeholder anywhere. Tag audit: 94 tests / 94 Design: lines, exactly one per docstring, all 76 distinct instance names verified to exist verbatim as a name: value in the correct source yaml and under the claimed section (queue B) / rule_id (queue A). No untagged, dual-tagged, or dangling tags.

Design-vs-PRD adjudications in the final two files (PRD wins; assertion dropped, never the PRD narrowed):
- stale_license_version...: dropped the design assertion StateLicense.version == lic_v2 + 1 after the accepted proposal. 3.6/3.14 say approval increments the licence version; nothing makes a PROPOSED proposal a licence mutation (it changes no derived field — active_appointment_count counts only ACTIVE/TERMINATION_REQUESTED), so the bump is not uniquely derivable. The instance core claim (412 on the stale token, total_count == 0 after it, lic_v2 == lic_v_after, then 201 PROPOSED) is fully asserted, plus active_appointment_count == 0 and empty franchise_locked_state_codes.
- small_brewer_state_credit...: dropped the design assertion tier2_bbl == 0.000 (no such field in the PRD excise-report shape). The design stray "federal_tax_cents 1" typo resolved to the value its own parenthetical derives, 175. All figures re-derived by hand: August 14999.500 + 0.500 = 15000.000 <= 15,000 -> 543 raw halved to 272, total 447; September re-derives ytd_bbl_before_period 15000.000 -> credit lost -> 543, total 718, a 271-cent divergence on identical 0.500 bbl.
- every_derived_field_is_current...: landed cost recomputed from 3.7 pinned step order — product 168000, raw freight 3000 + 4800 = 7800, 10% tier (product >= 100000), discount 780 -> freight_cents 7020, franchise_fee_cents 0, landed_cost_cents 175020. Added the 3.1-backed assertion that the brewery distribution_bbl_ytd is still 0.000 after shipment (aggregates come only from FILED returns), which sharpens rather than weakens the immediate-consistency claim.

Fixture-correctness checklist re-checked in both files: all money/quantity fields sent as JSON numbers; every datetime a full ISO-8601 instant; no ["data"] double-unwrap (validate_success/validate_error already return the payload); enum/constant symbols imported from test_helpers so spellings cannot drift; no blank-header cases in these two files.

Orchestrator verification: test_helpers/ and test_suite/ both present at the task root; nothing under workspace/.

## Step 7: Run tests and iterate — 2026-09-05T21:46:40.571313295Z

Subagent summary (verbatim):

Clean 8-round sweep achieved: 94/94 passing in all 8 rounds.

Iterations run: 2 (iteration 1: 91/94 in all 8 rounds, 3 deterministic failures; iteration 2: clean).

Tests deleted: none. All three failures traced to a real implementation gap or a test-setup precondition that violated PRD, not to PRD silence.

Fixes applied to test_helpers/: none.

Fixes applied to test_suite/:
- test_suite/test_14_endpoint_behaviour.py, TestBreweryComputedRead.test_the_brewery_read_derives_its_ytd_position_and_franchise_locks — the test filed an excise return for 2026-08-01 -> 2026-09-01 while the logical clock still sat at its default 2026-08-01T00:00:00Z, so the PRD-faithful implementation correctly answered ERR_PERIOD_NOT_CLOSED (3.8: "the logical clock must have reached or passed period_end_utc"). Added set_clock(api, "2026-09-01T00:00:00Z") before the draft/file, placed after the notice activation and the pours so notice_effective_utc and the in-window poured_at_utc assertions still hold.
- test_suite/test_04_transitive_cascades.py, fixture _two_kegs_one_already_returned (feeds TestKegReturnCascade) — the fixture returned KEG-0001 before KEG-0002 was filled, so kegs_outstanding_count hit zero on the first return and the run reconciled one keg early at -32.00 oz; 3.3 makes RECONCILED terminal on that dimension, so the run could never re-reconcile at -96.00. Reordered so both kegs are filled/tapped/poured before either is returned, which is the precondition the asserted PRD sentence describes ("the sum of depletion_variance_oz over every keg asset still linked to the run") and matches the already-passing sibling in test_06_boundary_precision.py (-80.64 oz). The other test on this fixture, test_the_tolerance_flags_one_sibling_keg_and_spares_the_other, is order-independent and still passes.

Fixes applied to implementation/:
- workspace/implementation/routes_brewery.py, create_brewery() — it validated the optional carry_in_taproom_bbl / carry_in_distribution_bbl inputs and then discarded them, hardcoding both to 0.000. PRD 4 declares them verbatim for POST /brewery ("Create the brewery singleton from legal_name, home_state_code, ttb_brewers_notice_number and the optional carry_in_taproom_bbl and carry_in_distribution_bbl"); 3.1 0.000 is the omitted-field default. Now the supplied values are persisted (defaulting to 0), which is what made ytd_bbl_before_period read 59999.000 instead of 0.000 in the federal-tier-straddle test. No new field, endpoint, or seeding was introduced; storage remains in-memory only.

Final sweep (per round passed/total): 94/94 x8 — 0 failed, 0 errors in every round.

worklog.md was not touched; scratch use was confined to .scratch/step7/ (nothing written), and the smoke server used for spot-verification was killed by port-specific PID from ss -ltnp (no pkill).

Orchestrator verification: independently parsed all 8 results.$i.json — every round reports passed 94 / failed 0 / errors 0 / total 94. Step 8 will run (1 implementation fix + 2 test_suite fixes, so the skip condition does not apply).

## Step 8: Finalize PRD — 2026-09-05T21:55:38.82424414Z

Subagent summary (verbatim):

Done. PRD_FINALIZED.md created as a one-line patch of PRD.md.

Line counts: PRD.md 527 lines; PRD_FINALIZED.md 527 lines — 0.0% line delta (1 of 527 lines revised, 0.19% of lines touched; no lines added or removed, no new sections).

Changes:
- 3.1 (brewery singleton creation, line 204) — revise — POST /brewery is now documented as accepting the two optional opening carry-in figures (carry_in_taproom_bbl, carry_in_distribution_bbl, each >= 0, three decimal places) and PERSISTING them, with 0.000 restated as the omitted-field default rather than an unconditional minted value; the sentence also notes that a creation naming them opens with the brewery YTD aggregates / opening excise tier position already shifted, exactly as a later carry-in adjustment would shift them — implementation/routes_brewery.py:46-61 (validation with places=3, minimum=0, required=False, default=0; persistence at lines 59-60).

Per-edit pre-edit search log — Edit 1 (both halves of line 204; same subject, one search):
(a) Subject: the brewery fields carry_in_taproom_bbl / carry_in_distribution_bbl — where accepted, where stored, everything that reads them.
(b) Impl paths enumerated (grep -rn "carry_in" implementation/ plus targeted reads): routes_brewery.py:39-63 create_brewery() — the Step 7 site; optional, 3-dp, min 0, default 0, stored via calc.bbl; validation runs before the ERR_BREWERY_ALREADY_EXISTS check, which the existing ladder (rung 3 above rung 7) already covers, so no ladder wording was needed. routes_brewery.py:109-127 brewery_ytd_adjustments() + _carry_in() — the other writer of the same two fields; overwrites outright and additionally accepts the aliases taproom_bbl / distribution_bbl. Wording kept scoped to creation so it makes no exclusivity claim about how the fields can be set (3.1 later carry-in paragraph and 4 /brewery/ytd-adjustments row left verbatim). derive.py:61-75 taproom_bbl_ytd() / distribution_bbl_ytd() and derive.py:99-104 serialize_brewery() — both read the stored fields with an or-0 fallback and re-emit at three decimals. routes_excise.py:67-68 — ytd_bbl_before_period sums both carry-ins, the path the federal-tier-straddle test exercises. routes_licensing.py:83,93-104 carry_in_barrels_ytd — the licence-level carry-in, a different field; confirmed the sentence never generalises over it. calc.py:101-102 bbl() — 3-dp round-half-up, matching 2.6.
(c) Wording adjustment made: initially drafted as "the supplied values are persisted"; widened/re-scoped twice — (i) phrased as "whatever figure the creation payload supplied for it, or 0.000 where that field was omitted" so the two fields are independent rather than an all-or-nothing pair; (ii) said "it may additionally carry" instead of "the carry-ins are only set here", so the /brewery/ytd-adjustments writer and its alias handling are not contradicted; (iii) described the downstream effect as shifting "the brewery year-to-date aggregates and opening excise tier position" (covering both derive.py and routes_excise.py readers) rather than naming only ytd_bbl_before_period.

Items deliberately NOT patched:
- test_14 set_clock before the draft/file — 3.8 already pins it verbatim ("the logical clock must have reached or passed period_end_utc") and routes_excise.py:161-162 matches exactly. Pure test-precondition bug, no PRD silence.
- test_04 _two_kegs_one_already_returned fixture reorder — 3.3 already makes RECONCILED terminal on the reconciliation dimension and 3.4 already defines keg_shrinkage_oz as the sum over "every keg asset still linked to the run"; cascades.reconcile_run_after_return() reconciles only from OPEN, only at kegs_outstanding_count == 0, and sums kegs whose packaging_run_id is the run. Fixture ordering bug, no PRD silence.

Orchestrator verification: diffed PRD.md against PRD_FINALIZED.md — exactly one line (204) differs; the file is not byte-identical, so the pass genuinely ran. 527 lines / 119,429 bytes.

## Step 9: PRD completeness scan (pass 1 of 3 — core, brewery, cellar) — 2026-09-05T22:27:25.807512757Z

Orchestrator note: Step 9 was split into three sequential module-partitioned passes over one shared PRD_COMPLETED.md (pass 1 does the cp; later passes must not). Pass 1 owned app.py, envelope.py, errors.py, store.py, helpers.py, validation.py, routes_brewery.py, routes_cellar.py.

Subagent summary (verbatim):

Pass 1 complete. cp PRD_FINALIZED.md -> PRD_COMPLETED.md performed as the first action. PRD_FINALIZED.md 527 lines / 119,429 chars; PRD_COMPLETED.md after edits 528 lines / 127,863 chars (+1 line = the new endpoint table row; +8,434 chars). Counts: 19 ambiguity-pins, 7 mismatch-revisions (26 changes over 22 Edit calls). PRD.md, PRD_FINALIZED.md, implementation/, test_*/, worklog.md untouched.

Changes: 2.1 RBAC insert (blank/whitespace-only headers count absent; both headers stripped before role match and before X-User-ID stamping/SoD compare, validation.py:36-47). 2.2 success envelope insert (api_request_id is req_ + exactly twenty uppercase-alnum chars, store.py:75-77). 2.2 success envelope insert MISMATCH (api_request_timestamp reads the host real clock, not the logical clock, envelope.py:11-15). 2.2 data bullet insert (barrel/ounce/percentage values are JSON numbers in shortest form 0.500->0.5, 2.000->2.0; cents and counters are integers, envelope.py:18-30). 2.2 error envelope insert (same envelope carries 5xx, app.py:75-77). 2.3 insert (empty-string limit/offset fall back to default; 10.0 counts as an integer; offset past end returns empty data with true total_count, validation.py:286-308, envelope.py:47). 2.3 insert (created_at ties broken by server write sequence, never by id, store.py:112,125-130). 2.4 insert/revise (updated_at equals created_at on a fresh row; both audit stamps are the only persisted instants from the host clock, store.py:92-94,105-113). 2.5 p1 revise MISMATCH ("Nothing in this system reads wall-clock time" narrowed to business rules, naming the two host-clock exceptions). 2.5 p2 insert (clock setter/reader return current_utc as sole data field; a read-only companion capability exists for all five roles; the clock may be set backwards, app.py:42-53, store.py:53-55). 2.5 p3 insert (Z == +00:00, non-zero offsets converted, naive strings read as UTC, date-only read as midnight UTC; responses always canonical 3-digit form, validation.py:184-197, store.py:80-89). 2.8 rung 3 insert (empty body parses as {}; explicit null counts absent; undeclared fields ignored; numerics accept decimal strings but not booleans; trailing zeros ignored by place checks; blank strings always rejected, validation.py:54-68,75-96,115-157). 2.8 rung 3 insert MISMATCH (state-dependent conditional fields — notice reason, ingredient_list, label cola_id, tank CIP readings — are read only after rung 9 clears, so a doubly-bad request answers the transition error). 2.8 rung 4 insert MISMATCH (the brewery-singleton 404 surfaces at rung 10 position, so an already-illegal transition reports rung 9 first, helpers.py:57-61). 2.8 rung 6 insert (code uniqueness is exact, case-sensitive, untrimmed, helpers.py:48-54). 2.10 filters insert (identifier filters never 404; empty filter = absent; conjunctive combination; boolean filter grammar; enum filters matched exactly). 3.1 ytd-adjustments insert (both carry-in figures required; taproom_bbl/distribution_bbl accepted as aliases with the canonical name winning). 3.1 beer registration insert (a beer may be registered before the brewery singleton exists; both flags read false). 3.1 FORMULA filing insert (ingredient_list accepted as non-blank string / non-empty array / non-empty object only). 3.1 LABEL filing insert (definition of a blank label_fields member; object stored verbatim including extra members). 3.1 filing decision insert (note is never persisted; an unrecognised filingType path segment is ERR_INVALID_REQUEST raised only after the beer resolves). 3.1 filing decision insert (REVOKED on the formula dimension is always ERR_FILING_TRANSITION_INVALID). 3.2 sanitation insert (present-but-implausible readings are verdict failures, not schema failures). 4 intro revise MISMATCH (fifty-NINE endpoints; every path reachable with or without a trailing slash). 4 table insert MISMATCH (added the missing GET /_clock/current_utc row, all five roles, 200). 5 intro revise MISMATCH (ERR_NOT_FOUND 404, ERR_METHOD_NOT_ALLOWED 405 and ERR_INTERNAL 500 exist outside the sixty-four-entry catalogue).

errors.py needed no patch: its 64 entries match 5 table exactly (verified programmatically).

Deliberately left for pass 2/3: cascade internals (cascades.py) incl. the REVOKE/EXPIRED licence edge; serializer/derived-field shapes (derive.py); rounding constants and formulas (calc.py); the keg-clean rung-3 ordering (routes_kegs.py:85-90), worded as a named non-exhaustive list so pass 2 can pin it; the GET /state-licenses four-filter discrepancy (routes_licensing.py:33-36).

## Step 9: PRD completeness scan (pass 2 of 3 — runs, kegs, cascades, derive) — 2026-09-05T22:27:25.816599317Z

Subagent summary (verbatim):

PASS 2 OF 3 complete. No cp performed. Before first edit (pass 1 output): 528 lines / 127,863 chars. After last edit: 528 lines / 136,827 chars. md5 of the pass-1 baseline was 80a2f431341919c3bf328be7bfb2ae28; the file grew +8,964 chars in place with the line count steady at 528 (every patch an in-paragraph insert or revision). Pass 1 edits intact — verified by three pass-1-only sentinel sentences. diff PRD_FINALIZED.md PRD_COMPLETED.md now shows 93 changed lines. Counts: 18 ambiguity-pins, 8 mismatch-revisions.

Changes: 2.6 revise (enumerated exact ounce-valued 2dp fields, adding a pour volume_oz and a run keg_shrinkage_oz). 2.8 rung 3 insert (a keg wash sanitizer_ppm/contact_time_seconds are unconditionally required and validated BEFORE the state check — the exact opposite of tank CIP, routes_kegs.py:85-90). 2.8 rung 4 insert MISMATCH (two keg-side exceptions resolve the brewery singleton at rung 4: a keg movement and a taproom pour). 2.8 rung 19 revise MISMATCH (fires only when label_fields omits one of the five members; absent or non-object label_fields fails at rung 3). 2.9 bullet 1 revise (a revocation hop 1 moves every licence not already SUSPENDED, EXPIRED included, but hops 2 and 3 follow only from formerly-ACTIVE licences). 2.9 bullet 3 revise (a keg return hop 2 always lands on the run (version +1) whatever the outstanding count; hop 3 needs count 0 AND OPEN AND kegs_filled_count >= 1). 3.1 p4 revise (REVOKE detail). 3.1 p5 revise MISMATCH (franchise_locked_state_codes requires a live appointment (ACTIVE or TERMINATION_REQUESTED), de-duplicates as a set, sorts, computed at read time without mutating the brewery row). 3.1 last p insert (taproom_sellable/distribution_sellable recomputed at every serialisation; one notice action flips them portfolio-wide while touching no beer updated_at or version). 3.3 insert (units_produced is not tied to units_planned in either direction). 3.3 revise (completion three demands re-ordered to ladder order: run state -> notice -> batch state). 3.3 insert (the certifying run, mutated twice in one request, still increments version by exactly 1). 3.3 loss allocation insert (the zero branch leaves a run already at 0.000 untouched; a null share is written and versioned). 3.3 void p PLANNED insert (owning batch neither rewritten nor re-derived, version stays put). 3.3 void p COMPLETED insert (outside PACKAGED no loss allocation runs and total_loss_bbl is left as it stands; loss_share_bbl cleared on either path). 3.3 barrel-ledger insert (packaged_bbl sums bbl_removed over COMPLETED runs only). 3.3 reconciliation revise MISMATCH (shrinkage sums only kegs still citing the run and still holding a variance figure; the dimension opens only from NOT_APPLICABLE). 3.4 p1 insert (a non-catalogue size_bbl is ERR_INVALID_REQUEST; the match is numeric with no decimal-place limit). 3.4 wash insert x2 (both readings unconditionally required and checked before the state transition; the wash leaves filled_volume_oz, poured_volume_oz, remaining_volume_oz, deployment_channel, tapped_at_utc and cycle_count alone). 3.4 deploy revise (event_permit_id narrows rather than widens the search; the window is inclusive; a bogus event_permit_id is a rung-5 ERR_EVENT_PERMIT_NOT_FOUND on any movement type). 3.4 return revise (returned_volume_gal has no decimal-place limit; returned_volume_gallons accepted as an alias with the canonical name winning). 3.5 insert x3 (a pour increments the keg version while the pour row carries none; a draft pour five sealed fields all read back null with sanitation_verdict NOT_REQUIRED; label_fields absent/non-object fails at rung 3 and what passes is stored verbatim). 4 endpoint table revise x3 (packaging-run list row gains reconciliation_state; movements row returned_volume_oz corrected; pours row drops poured_by_user_id as a client input, noting the server stamps it from X-User-ID).

Deliberately left for pass 3: the POST /distributor-appointments brand_scope payload row; the 3.6 lazy-expiry trigger set; rung 4 exception list left extensible for order submission.

Three drafting errors were caught and corrected before committing, each by a NO-NEW-MISMATCH check: a false claim that a run barrel split can shift during allocation (refuted by routes_orders.py:157); a void-path wording that omitted DUMPED as a possible owner of a COMPLETED run; and a near-universal "no row versions twice per request" claim, scoped down to the certifying run instead.

## Step 9: PRD completeness scan (pass 3 of 3 — licensing, orders, excise, calc) — 2026-09-05T22:38:08.503638610Z

Subagent summary (verbatim):

Pass 3 of 3 — Step 9 complete. PRD_COMPLETED.md was 528 lines / 136,827 chars before the first edit; now 528 lines / 145,043 chars (+8,216). Line count unchanged because every edit was an in-paragraph insert/revision; no cp was run and the 52 prior edits are intact. Counts: 25 Edit calls, 24 substantive changes — 14 mismatch-revisions, 10 ambiguity-pins.

Changes: 2.8 rung 4 revise MISMATCH (two keg-side operations -> three; order submission resolves the brewery singleton at rung 4, routes_orders.py:61). 2.8 rung 11 revise MISMATCH (ERR_LICENSE_NOT_ACTIVE now names appointment approval; proposal deliberately not status-gated). 2.8 rung 12 revise MISMATCH x2 (ERR_FORMULA_NOT_APPROVED now names event-permit submission in both the path list and the guarded-operation list). 2.8 rung 14 insert MISMATCH (lazy expiry runs first, so a closed window answers ERR_LICENSE_NOT_ACTIVE on the three order ops and ERR_LICENSE_EXPIRED is reachable only on appointment proposal). 2.10 revise MISMATCH (state-licence filters are four, state_code added, matched as an opaque string). 2.10 insert (venue_state_code likewise matched as an opaque string). 3.6 insert (licence carry-in accepts aliases carry_in_bbl/barrels_ytd with canonical precedence; consults neither notice nor expiry). 3.6 revise (replaced "any request that reads the licence" with the exact closed trigger set — read, list-all-before-filter, proposal, approval, order submit/allocate/ship — plus explicit non-triggers). 3.6 insert MISMATCH (three-failure-modes paragraph: approval added to ERR_LICENSE_NOT_ACTIVE). 3.6 insert MISMATCH (brand_scope is never a client input, ignored under rung 3; good_cause_code stored from creation). 3.6 revise MISMATCH (approval four conditions restated in ladder order). 3.6 insert (good_cause_code is a rung-3 optional enum on every phase; only absence on a franchise-state REQUEST yields ERR_GOOD_CAUSE_REQUIRED). 3.7 insert (allocation sort gains the server write sequence as third key). 3.8 insert (with no brewery row the two carry-in terms contribute nothing; drafting and filing never raise ERR_BREWERY_NOT_FOUND). 3.9 insert (the venue-licence test is pure existence, status- and window-agnostic). 3.9 insert (permit submission names ERR_NOTICE_NOT_ACTIVE and ERR_FORMULA_NOT_APPROVED, never ERR_LABEL_NOT_APPROVED). 3.9 revise MISMATCH (the decision note is optional on every decision, not required for DENIED/INFO_REQUESTED; a note on APPROVED is validated then discarded). 3.9 revise MISMATCH (decision paragraph opener no longer implies the note is required). 4 table revises: GET /state-licenses gains franchise_state plus the all-licence expiry refresh note; GET /state-licenses/{id} gains the single-licence refresh note; POST /state-licenses marks termination_notice_days optional default 90; POST /state-licenses/{id}/ytd-adjustments names the aliases; POST /distributor-appointments drops brand_scope and adds good_cause_code; POST /event-permits/{id}/decision marks the note optional.

Hand-off resolutions: (1) four licence filters resolved in both 2.10 and the 4 row. (2) brand_scope removed from the 4 row; 3.6 states it is never a client input. (3) lazy-expiry trigger set replaced with the exact closed set plus explicit non-triggers; cascades.refresh_license_expiry mechanics left untouched. (4) rung 4 exception set extended from two to three, adding order submission. (5) ERR_LICENSE_NOT_ACTIVE on approve confirmed in impl (routes_licensing.py:179-180 calls refresh_license_expiry then license_active_guard) and pinned in rung 11, the 3.6 failure-mode paragraph and the 3.6 approval paragraph. (6) conditional-required-fields: no rung-3 edit warranted — good_cause_code has its own code at rung 24, so the ladder already pins its precedence below rung 9; instead pinned the genuinely silent parts in 3.6.

Final integrity check — PASS. All five top-level sections present plus all 19 subsections (2.1-2.10, 3.1-3.9). 4 table: 59 endpoint rows, matching its own "fifty-nine endpoints" claim. 5 table: 64 rows, 64 unique error IDs. File ends cleanly on the ERR_EVENT_BARREL_CAP_EXCEEDED row — a real section boundary.

## Pipeline complete — 2026-09-05T22:38:08.510298081Z

Orchestrator final verification:
- PRD.md 527 lines / 118,914 chars; PRD_FINALIZED.md 527 / 119,429; PRD_COMPLETED.md 528 / 145,043. PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (67 lines differ), so all three Step 9 passes genuinely ran; 78 total Step 9 changes (26 + 26 + 24 -2 reconciled) across the three passes.
- Independently re-verified section structure: sections 1-5 all present; 4 table 61 markdown rows = header + separator + 59 endpoints; 5 table 64 ERR_ rows; file ends at a real section boundary.
- Implementation and test files were last modified at 21:32/21:20, i.e. before the final green sweep at 21:36 — Steps 8 and 9 touched only PRD copies, so the recorded 94/94 x8 result still describes the shipped implementation.
- Test artifacts live at the task root (test_helpers/, test_suite/); nothing under workspace/.
- No stray worklog files outside the task root.
