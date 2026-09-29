## Step 1: Create task directory — 2026-09-04T17:57:05.457256095Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2765_medical_professional_liability_underwriting_claims and its workspace/ subdirectory (index pre-assigned by orchestrator input; no auto-allocation performed).


## Step 2: Generate scaffold — 2026-09-04T19:57:11.000Z

All three artifacts complete; scaffold_lint.py reports a clean run.

Lint report:
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     22
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1025
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Files (in task dir):
| file | lines | bytes |
| SCAFFOLD.yaml | 3801 | 182,540 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 1777 | 116,121 |
| SCAFFOLD_CORNER_DESIGN.yaml | 5697 | 349,324 |

Key-hygiene verified by PyYAML: SCAFFOLD.yaml contains neither design key; the other two files each have exactly one top-level key (scaffold_difficulty_design, scaffold_corner_design). No other directory was created under tasks/; the pre-existing worklog.md and workspace/ were left untouched.

SCAFFOLD.yaml contents:
- 14 entities: SpecialtyClass, Insured, RiskProgramEnrollment, PeerReviewCase, Policy, PolicyTerm, TailEndorsement, Claim, ReserveEntry, DefenseCounselFirm, CounselAssignment, SettlementNegotiation, NPDBReport, RateFiling (ReserveEntry is common_fields: false; all others true).
- 11 state machines, state_machine_shape: cyclic (negotiation VETOED->AUTHORITY_REQUESTED revision loop, Claim's two independent axes claim_status × coverage_status, PeerReviewCase fork-join, PolicyTerm three-way divergent branch, compound Policy.status).
- 15 calculations (claims-made step premium, program_credit_pct, peer-review surcharge, risk classification, dual-variant case_reserve_projection and claim_incurred_loss, counsel_panel_selection, severity trend, reserve_adequacy_ratio, rate indication ...), 4 OCC rules, 64 validations (priority ladder 1-87), 65 endpoints, 60 error codes, 8 roles (7 carrier + Insured, role_model: segregation_of_duties).
- complexity_layers: dual_variant_calculation, cascading_side_effects, optimistic_concurrency, derived_field_reconciliation; entity_topology: graph; consistency_model: immediate; difficulty_level: expert_plus.

SCAFFOLD_DIFFICULTY_DESIGN.yaml — 22 instances over all 9 rules:
dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

SCAFFOLD_CORNER_DESIGN.yaml — 113 instances / 9 sections (80 real + 33 excluded_because stubs):
entities 12 (12 real), state_machines 17 (8), calculations 13 (7), validations 9 (6), endpoints 5 (3), errors 40 (33), rbac 7 (7), cross_cutting_complexity_layers 9 (3), consistency_model 1 (1).
Audits beyond the linter, all clean: every stub's difficulty_instance resolves to a real §1.8 name and no stub carries a test_recipe; every real instance has one; all 113 + 22 names are globally unique; all 60 error codes are asserted by at least one real instance; every Entity.${var}.field assert resolves against §1.1 plus common_fields expansion.

Three disclosures:
1. Directive line omitted from scenario: — the leading "Generate task harder than expert level!" line was deliberately not copied into SCAFFOLD.yaml's scenario: key (it would leak downstream into PRD.md). The difficulty intent is carried structurally via complexity_profile.difficulty_level: expert_plus.
2. Error catalog is 60 codes, above the Expert 18-30 guidance band. Kept deliberately: the domain has nine independent write surfaces (credentialing, enrollment, peer review, policy/term/tail, claim/reserve/counsel, negotiation/consent/authority, NPDB, rate filing) and the §1.4 ladder relies on distinct codes to make "which validation answers first" falsifiable; collapsing them would erase the priority-pair corners.
3. Corrections made to already-written files while authoring §1.9 (each because a corner instance proved the original was unreachable or self-contradictory):
   - SCAFFOLD.yaml: tail-void cascade re-scoped to the policy; the Policy CANCELLED recompute made conditional on the branch; the authority-decision changed to allow a partial grant, which is what makes ERR_AUTHORITY_INSUFFICIENT reachable at all (4 edits).
   - SCAFFOLD_DIFFICULTY_DESIGN.yaml: repaired the counsel_request_on_denied_claim_rejected_for_coverage_not_empty_panel chain (4 edits); added a premature-vote trigger + assert to peer_review_fork_join_requires_both_tracks_before_committee_vote so ERR_PEER_REVIEW_STATE_INVALID is actually triggered somewhere (a §1.9 stub had cited it as covered when it was not).
   - Two §1.9 rows drafted as stubs (ERR_RESERVE_DEFICIENCY_BLOCKS_FILING, ERR_AGGREGATE_LIMIT_EXCEEDED) were promoted to full real instances, because no §1.8 instance actually triggers those codes and unbacked stubs are forbidden.

Orchestrator verification: all three files present; grep for "harder than expert" across all three returns no match (no difficulty-directive leak).

## Step 3: Copy shared files — 2026-09-04T19:57:18.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T20:14:19.000Z

PRD generation is complete and verified.

Output: workspace/PRD.md — 470 lines / 14,758 words, ending cleanly on the last row of the §5 error table (no truncation). Written incrementally in nine appends; no design/corner files were opened and no sibling task directory was read.

Section list:
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Actors, Headers and RBAC · 2.2 API Response Structure (verbatim from the skill contract, byte-identical) · 2.3 Pagination (incl. the per-collection filter catalogue) · 2.4 Record Identity, Audit Fields and Append-Only Postings · 2.5 Numeric Precision and Pinned Evaluation Order · 2.6 The Logical Clock and Scheduled Checkpoints · 2.7 Nested Resource Retrieval and Left-to-Right Path Resolution · 2.8 Validation Precedence (17-step ordered list) · 2.9 Optimistic Concurrency on Parent Records · 2.10 Derived Roll-Ups and the Re-Rating Cascade · 2.11 Interval and Window Conventions
- §3 Business Logic & Workflows — 3.1 Rate manual & actuarial governance (rate filings, credibility, reserve adequacy) · 3.2 Insured onboarding, credentialing, risk classification · 3.3 Risk-management credits and peer review surcharges · 3.4 Policy quoting and the claims-made step chain · 3.5 Binding, cancellation, tail/ERP endorsements · 3.6 Claim intake and coverage trigger resolution · 3.7 Reserving, defence panel selection, expense payment · 3.8 Settlement negotiation, consent to settle, hammer clause · 3.9 Resolution, NPDB reporting, severity trend analysis
- §4 Endpoint Definitions (4-column table, 65 rows)
- §5 Error Code Catalogue (2-column table, 60 rows)

Coverage audit (scripted against SCAFFOLD.yaml):
- Endpoints: 65/65 present in §4 as exact METHOD | path matches
- Error codes: 60/60 in §5, and all 60 also referenced in §1–§4 prose (none table-only)
- Calculations: 15/15 expressed in prose; every constant present as a literal or written-out value (e.g. 0.0125 as "one and a quarter percent", 1095 as "1,095 calendar days", the five PROGRAM_CREDIT_PCT rates as words)
- State machines: 11/11, all 50 transitions described (30 as explicit FROM -> TO pairs, 20 as system re-derivations/cascades in prose)
- Validations: 64/64 priorities mapped into the §2.8 ordered list, each tied to its error identifier; 4/4 OCC rules in §2.9

Hard Contract reports:
1. Field-Name Coverage — PASS. 219 distinct identifiers extracted from entities[].fields[].name, all endpoint input items (request bodies and query params) and all computed-read output keys; 0 missing from backticked PRD tokens (fenced code stripped before matching to avoid backtick-pairing skew).
2. Rule Coverage — PASS. Validation priorities, all four OCC rules with their expected_*_version fields / error ids / 412 status, every state transition with preconditions and side effects, all 15 calculations with pinned rounding and evaluation order, applies_to scopes, field-level defaults, and sibling-branch symmetry (flat vs pro-rata cancellation, CASE_BASIS vs FORMULA_BASIS, case vs actuarial incurred, severity scope vs verdict scope, the three payable negotiation statuses).
3. §3 Path Purity — PASS. Zero backticked tokens in §3 begin with /, name a bare HTTP method, or combine method+path; no raw /mpl/... string appears anywhere before §4, and §1–§2 mention only the /mpl mount.

Two accuracy notes from the generator: ERR_CONSENT_REQUIRED and ERR_COVERAGE_DENIED_NO_DEFENSE each serve two distinct checks at different priorities, and the PRD states both faces of each rather than collapsing them; and the scaffold's coverage-decision rule requires handling status INTAKE while permitting coverage positions UNDER_REVIEW or RESERVED_RIGHTS, which was transcribed literally rather than reconciled.

Orchestrator verification: wc -l = 470; tail shows a complete §5 error table ending at ERR_PER_CLAIM_LIMIT_EXCEEDED | 422 (a real section boundary, not mid-sentence); §5 contains 60 error rows; no difficulty-directive text ("expert level" / "expert_plus") appears in PRD.md.

## Step 5: Generate unit tests — 2026-09-04T21:50:58.000Z

Verification complete. Everything passes.

Files written — test_helpers/ (Stage 1, 2532 lines):
| constants.py | 162 |
| types.py | 525 |
| api_errors.py | 153 (60 ApiErrorId members, 60 status mappings) |
| api_client.py | 346 (ApiClient(GenericApiClient), PREFIX="/mpl", one method per endpoint + raw_get/raw_post) |
| factories.py | 354 (31 payload factories, all money as JSON numbers) |
| assertions.py | 327 (money/ratio tolerances, canonical_instant ISO normaliser, 14 per-entity asserters, fee-ladder + incurred invariants) |
| fixtures.py | 526 (48 builders, 21 pytest fixtures) |
| test_users.py | 98 |
| __init__.py | 41 |

test_suite/ (Stage 2, 9285 lines): conftest.py 13, then test_01 369, test_02 502, test_03 596, test_04 664, test_05 411, test_06 428, test_07 391, test_08 439, test_09 456, test_10 707, test_11 639, test_12 398, test_13 748, test_14 518, test_15 583, test_16 321, test_17 527, test_18 575.

Coverage — 102/102 live instances, zero skips:
| queue | live instances | translated | skipped | stubs (not translated) | tests emitted |
| A — Difficulty §1.8 | 22 | 22 | 0 | 0 (none exist) | 105 |
| B — Corner §1.9 | 80 | 80 | 0 | 33 | 178 |
| total | 102 | 102 | 0 | 33 | 283 |

Skipped instances: none. Every live instance passed the PRD-first two-condition filter, so there is no PRD-silent or not-uniquely-derivable exclusion list to report.

Machine-verified against yaml.safe_load of both indices:
- 0 uncovered live instances; 0 excluded_because: stubs translated; 0 unknown/typo'd tags; 0 tags spanning more than one file.
- Every queue-A instance has >=2 tests (min 3 in practice); minimum 2 per queue-B instance.
- 283 test functions, each with exactly one Design: line, and in every case it is the last docstring line.
- 283/283 PRD: quotes are byte-exact (whitespace-normalised) substrings of workspace/PRD.md.
- Zero occurrences of scaffold / design-yaml / rule_id / test_recipe vocabulary in any generated docstring or comment.
- Zero skip/xfail/TODO/placeholder markers; zero money values emitted as JSON strings.
- python3 -m py_compile clean on all 28 files; pytest --collect-only -> 305 tests collected in 0.79s, no collection errors (305 > 283 because two tests are parametrised).

ls -la verification — both dirs are task-root siblings; workspace/ holds only INSTRUCTION.md and PRD.md; find workspace -name test_helpers -o -name test_suite -> no output. workspace/implementation/ did not exist and was never read or created. worklog.md untouched. No process-killing command was run and no server was started.

Design-index defects found and worked around (tests assert only the PRD-derivable outcome, so the suite is correct as it stands; the index itself is wrong at these seven points):
1. coverage_decision_on_a_claim_denied_at_intake... asserts severity_band == "BAND_4" for demand_amount 800000.00; PRD §3.6 bands 750000.00-2000000.00 as BAND_3.
2. hammer_invocation_under_an_absolute_consent_clause_is_rejected asserts insured_share_amount == null; PRD §3.8 initialises those three hammer fields to 0.
3. adjacent_term_periods_pass_while_a_straddling_third_term_conflicts supplies a predecessor_term_id that makes ERR_TERM_PERIOD_GAP (precedence item 15) fire before the asserted ERR_TERM_PERIOD_OVERLAP; the predecessor must be omitted.
4. declined_assignment_restores_firm_capacity_counter_without_drift uses a free-text decline_reason; the PRD declares it an enum (CONFLICT_OF_INTEREST used instead).
5. enrollment_carrying_the_pre_credentialing_insured_version_returns_412 ends with a credit_pct_applied == 0.05 assertion unreachable from its own setup (no policy or term is built).
6. risk_score_of_exactly_three_lands_in_r2_while_two_point_nine_six_stays_r1 specifies specialty_code: "INTERNAL_MEDICINE", not one of the PRD's five declared specialty codes — the setup call would itself 422. Substituted EMERGENCY_MEDICINE (hazard 4.0) paired with FAMILY_MEDICINE (3.9); the asserted 2.96->R1->0.85 and 3.00->R2->1.00 outcomes are unchanged.
7. Four scattered sub-assertions in the test_11/test_12 instances are not pinned by the PRD and were dropped: post-issuance policy version, decided_by_user_id on a WITHDRAW, an unobservable clock read, and the initial npdb_reported_payment_total.

Independently re-derived and confirmed correct: premium_manual 19285.00 / admin 250.00 / guaranty 244.19 / term_total 19779.19; the 5% credit ladder 18320.75 -> 232.13 -> 18802.88 (and the sibling 18706.45/236.96/19193.41); the ILF-1.45 ladder 27963.25/500.00/355.79/28819.04; 33060.00/419.50/33979.50; pro-rata return 12298.08 against 12501.92 written; tail 55100.00 x 1.55 = 85405.00 with window close 2032-07-31; formula cap 1000000.00 with expense 280000.00 and the 15000.00 floor; required_reserve_total 6320.98 (per-claim rounding); hammer 640000.00/120000.00/520000.00; trend_index 0.6250; defense_win_rate 0.5000; expires_on 2028-08-09; MPL-000001.

ORCHESTRATOR NOTE (deviation from the skill, recorded for transparency): Steps 5 and 6 were intended to be launched in a single assistant message for concurrency + physical isolation, but the orchestrator issued only the Step 5 Agent call in that message, so Step 6 ran afterwards, at which point test_helpers/ and test_suite/ already existed on disk. Physical isolation was therefore replaced with an explicit, absolute prohibition in the Step 6 prompt (no read/list/glob/grep of test_helpers/, test_suite/, or either design YAML). The Step 6 subagent reported it honoured that isolation and never opened those paths. No corrective action taken; noted so Step 7 onward can weigh it.

## Step 6: Generate implementation — 2026-09-04T21:51:22.000Z

Implementation complete and verified.

Files written (workspace/implementation/, 3,854 lines total):
start.sh 10 (chmod +x), requirements.txt 1, app.py 70, constants.py 276, errors.py 85, store.py 146, envelope.py 103, val.py 276, auth.py 141, routes/common.py 32, routes/rate_manual.py 197, routes/insureds.py 290, routes/policies.py 394, routes/claims.py 278, routes/counsel.py 164, routes/negotiations.py 301, routes/npdb.py 78, routes/analytics.py 36, routes/clock.py 22, services/rating.py 300, services/claims.py 250, services/counsel.py 92, services/actuarial.py 203, services/clock.py 109.

Coverage:
- Endpoints: 65/65. url_map yields exactly 65 non-static rules, matching PRD §4 one-for-one (rate/manual 8, insureds 13, policies 12, claims 9, counsel 8, negotiations 9, NPDB 4, analytics 1, clock 1).
- Error codes: 60/60. ERROR_HTTP_STATUS has exactly 60 entries; every declared id is actually raised somewhere and no route raises an undeclared id. (ERR_NOT_FOUND/ERR_METHOD_NOT_ALLOWED exist only in the framework-level 404/405 fallback handlers with hardcoded statuses, for paths outside the PRD surface.)
- Storage is process-local dicts only — grep for sqlite, open(, json.dump, pickle, /tmp across the package returns nothing. Zero seeding: a fresh boot returns total_count: 0 for every collection.

Notable interpretation decisions where the PRD was ambiguous:
1. §2.7 vs §2.8 precedence. On nested-collection routes (e.g. POST /claims/{id}/reserve-entries) the path segment resolves to a 404 before payload validation, per §2.7's left-to-right rule, overriding the §2.8 tier order. Same for §3.7's assignment routes: assignment state is checked before assignment-claim mismatch.
2. Version unit of work. Cascades (policy money rollups, claim counters, re-rating) touch many records per request, so touch()/flush() guarantees exactly one bump per record per request; records minted in the same request are registered in g._fresh so a cascade cannot push a brand-new record to version 2.
3. Stacked enrollment credit is not stored. The PRD declares no stacked_credit_pct field on Insured, so credit is recomputed at rating time from live enrollments and only surcharge_pct is persisted.
4. ReserveEntry is versionless (PRD lists only id + created_at), so postings are created with versioned=False and emit no version/updated_at. The reserve of record is selected by (effective_date, created_at, seq) so a later-posted-but-earlier-effective entry does not govern.
5. Hammer exposure is capped at limit_per_claim before the 60/40 split, since the PRD's projected-exposure multiplier can otherwise exceed the policy limit.
6. Settlement payment disburses carrier_share_amount when the negotiation reached HAMMER_INVOKED, and proposed_amount otherwise; the insured share is accrued to claim.insured_share_receivable at invocation.
7. Logical clock echo. logical_now() returns the operator-supplied instant string verbatim so derived timestamps (issued_at, consent_requested_at) are byte-stable, while audit created_at/updated_at use real UTC with fixed 3-digit milliseconds.
8. Tail mature basis is premium_manual / step_factor (de-stepped), then multiplied by the tail factor; unlimited windows use the 9999-12-31 sentinel.

Smoke tests — both passed against a fresh start.sh boot on explicitly-chosen free ports, each killed by its own PID only (no broad kill was ever issued).
- Smoke 1 validated the happy path and pinned arithmetic: term ladder 42000.00 -> 42000.00 -> 60900.00 -> 21315.00, fee 250.00, guaranty 269.56; hammer 640000.00/120000.00/520000.00; NPDB due 2026-09-24 and 7 days late; trend index 1.04; clock sweep closing a resolved claim.
- Smoke 2 (57 assertions) exercised enrollment credit and duplicate/state refusals, credentialing, the claims-made step chain with gap/stale-version/overlap refusals, clock sweep + term expiry with the derived policy status, tail effective-date / DDR / duplicate-issuance refusals plus a successful ERP_5YR quote and issuance, prior-acts exclusion, report-before-incident, reserve method mismatch and effective-dated reserve of record, peer-review fork-join + majority + DEVIATION_MAJOR suspension, suspended-insured quote refusal, pro-rata cancellation with return premium 12910.38, and a rate filing through APPROVE with the base-rate rewrite (8480.00, rate_revision_index 1) and the severity-trend read. Every expected error id and HTTP status matched; exit 0.
- Launcher check. PORT=<free> ./start.sh bound 0.0.0.0 in the foreground; GET /mpl/insureds?limit=5 as UnderwritingOfficer returned 200 with the full envelope (meta.api_request_id = req_ + 20 uppercase alnum, api_request_timestamp, limit/offset/total_count/has_more, response_type: "array", data: []), and an unrecognised role returned 401 ERR_UNAUTHENTICATED.

Isolation honoured throughout: test_helpers/, test_suite/, both SCAFFOLD design YAMLs, and all sibling task directories were never opened. worklog.md was not touched.

## Step 7: Run tests and iterate — 2026-09-04T22:14:35.000Z

Loop complete — clean 8-round parallel sweep.

Iterations run: 2

Tests deleted: none. Both failures traced to real, PRD-verbatim-covered, uniquely-derivable rules, so STEP 1 kept both tests and the fixes landed in implementation/.

Fixes applied to test_helpers/: none — the fixture/factory/role-header layer was already PRD-faithful (no money-as-string bug, and assertions.canonical_instant already neutralised ISO sub-second width).

Fixes applied to implementation/:
1. workspace/implementation/store.py — now_iso() was minting created_at/updated_at from datetime.now(timezone.utc). PRD §2.6 states verbatim: "The server keeps a logical UTC clock rather than reading wall-clock time. Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to real time." Changed it to format db.clock_dt with three fractional digits. Safe for ordering: every ordering key that uses created_at (store.by_created, services/claims.py reserve-of-record, services/clock.py sweep order, services/counsel.py firm ranking, services/actuarial.py) already carries _seq as the final tiebreaker, so ties within one logical instant still resolve by insertion order.
2. services/rating.py::derive_policy_status + routes/policies.py::cancel_term — the compound cascade evaluated EXPIRED before CANCELLED, so a policy holding one EXPIRED term plus one CANCELLED_FLAT term read back EXPIRED. The PRD's two owning sentences conflict on that overlap: §3.4 flat cancellation says "its status set to CANCELLED once no term on it remains in DRAFT, ISSUED or IN_FORCE" (unqualified), while the issuance/sweep section says the status "bubbles up to EXPIRED once every term on it has reached a terminal status and at least one of them is EXPIRED". Per §2.5 ("Each of these is spelled out in the workflow that owns it; where a later section describes an evaluation order, that order governs") the precedence was made transition-driven: derive_policy_status(policy, driven_by="CANCELLED") from the cancellation route, default EXPIRED-first elsewhere. This keeps the pure-expiry cascade test in test_12 green while satisfying the sentence that owns the cancellation transition.

Final sweep numbers (8 parallel rounds, 533s each): rounds 1-8 all 305/305 (0 failed, 0 errors, 0 skipped). Union of failing tests across all 8 rounds: 0. No flakiness surfaced. (305 collected items from 283 def test_ functions — the delta is parametrised cases.) Storage remains in-memory-only; no seeding, no on-disk state; worklog.md untouched.

Orchestrator verification: all 8 results.$i.json present (mtime 22:13) and independently re-parsed — every round total=305 passed=305 failed=0 errors=0 skipped=0.

## Step 8: Finalize PRD — 2026-09-04T22:18:45.000Z

PRD_FINALIZED.md written with two surgical revisions.

Line counts: PRD.md 470 lines; PRD_FINALIZED.md 470 lines — 0.0% line delta (both edits are in-line sentence insertions into existing paragraphs; no new sections, no re-flow).

Changes:
- §2.4 (Record Identity, Audit Fields) — insert — server-minted stamps (created_at, updated_at, and §2.2's api_request_timestamp) are read from the logical clock of §2.6, not wall-clock time, rendered with three fractional digits; pre-advance records read 2026-08-01T00:00:00.000Z, and records a clock advance touches carry the newly set instant — implementation/store.py:22-31 (now_iso), store.py:89 (new_record), store.py:125 (flush), envelope.py:12.
- §2.10 (compound policy status cascade) — insert — pinned the EXPIRED-vs-CANCELLED overlap: when a policy holds both an EXPIRED term and a cancelled term, the triggering transition decides — a cancellation-driven re-derivation reads CANCELLED, anything else (notably the clock's expiry sweep) reads EXPIRED — implementation/services/rating.py:256-280 (derive_policy_status(..., driven_by)), callers routes/policies.py:282 and services/clock.py:59.

Per-edit pre-edit search log:

Edit 1 — subject: source and format of every server-minted timestamp.
(b) Paths enumerated: grep -rn "now_iso|logical_now|logical_date|clock_str|clock_dt|datetime.now|utcnow" across the whole implementation. Read store.py in full (now_iso, new_record created_at/updated_at, flush batch stamp, Store.__init__ epoch datetime(2026,8,1), logical_now = raw echoed clock_str, logical_date), envelope.py in full (_meta -> api_request_timestamp = now_iso(), flush() ordering before envelope build), services/clock.py (clock set happens in step 1, so sweep-touched records flush against the new instant), plus every logical_now() callsite: routes/policies.py:211 (issued_at), :392 (tail issued_at), routes/counsel.py:108,153 (assigned_at, closed_at), services/counsel.py:67,83, routes/negotiations.py:157 (consent_requested_at), and logical_date() callsites routes/insureds.py:104,279, services/rating.py:160.
(c) Adjustment: the first draft said "every timestamp the server mints ... with three fractional digits". That is false for the logical_now() family (issued_at, assigned_at, closed_at, consent_requested_at) which echo the operator-supplied instant verbatim rather than re-rendering it, and for current_utc. Narrowed the sentence to name exactly the three stamps produced by now_iso() (created_at, updated_at, api_request_timestamp) and left §2.4's existing prose about "logical timestamps written to issued_at, assigned_at, closed_at, consent_requested_at" untouched, so the raw-echo format stays under-determined rather than falsely pinned.

Edit 2 — subject: derivation of policy.status when terminal term statuses overlap.
(b) Paths enumerated: grep -rn "derive_policy_status|refresh_policy|derive_current_term" (only two live callsites: routes/policies.py:282 with driven_by="CANCELLED", services/clock.py:59 with the default; rating.refresh_policy is dead code), plus grep -rn '\["status"\] = ' over routes/ and services/ to find every direct writer of policy["status"] — routes/policies.py:217 (issuance sets ACTIVE outright) and services/rating.py:271-280. Read create_policy/create_term/issue_term/cancel_term in routes/policies.py:20-285 and all six sweep steps in services/clock.py.
(c) Adjustments: (i) confined the new sentence to the "both readings hold" case so it cannot be read as re-describing the ACTIVE branch (issuance writes ACTIVE directly without calling the deriver) nor the DRAFT-remaining branch (rating.py:272-274 keeps an already-ACTIVE policy ACTIVE and never demotes it, and create_term re-derives no status at all — deliberately left as PRD.md already had it). (ii) phrased the rule as trigger-driven rather than as a permanent property, because the flip is reachable in the other direction: a policy left CANCELLED that later gets a new term issued and then swept to EXPIRED re-derives to EXPIRED at clock.py:59. (iii) did not touch §3.5's two owning sentences (the flat/pro-rata "set to CANCELLED" clauses and the "bubbles up to EXPIRED" clause) — each remains literally true of its own trigger under the new tie-break, so rewording them would have risked a new mismatch for no gain.

Orchestrator verification: PRD_FINALIZED.md exists, 470 lines, and diff against PRD.md shows exactly the two described line-level revisions (§2.4 line 84, §2.10 line 150); files are not identical.

## Step 9: Complete PRD — 2026-09-04T22:48:42.000Z

Run as THREE sequential module-partitioned passes over one shared PRD_COMPLETED.md (pass 1 performed the cp from PRD_FINALIZED.md; passes 2 and 3 edited in place and were explicitly forbidden to cp). Partition: pass 1 = cross-cutting framework + rate manual + insureds (app/constants/errors/store/envelope/val/auth/routes.common/routes.rate_manual/routes.insureds/services.actuarial); pass 2 = policies/terms/tail/rating/clock (routes.policies/routes.clock/services.rating/services.clock); pass 3 = claims/reserves/counsel/negotiations/NPDB/analytics (routes.claims/routes.counsel/routes.negotiations/routes.npdb/routes.analytics/services.claims/services.counsel + the severity-trend portion of services.actuarial that pass 1 deferred).

Totals: PRD_FINALIZED.md 470 lines / 110,325 chars -> PRD_COMPLETED.md 470 lines / 122,744 chars (+12,419 chars, 0 line delta — every change is an in-paragraph insert or revision; no new sections). 45 changed lines. Counts across the three passes: 45 ambiguity-pins, 10 mismatch-revisions (55 edits).

=== PASS 1 (framework + rate manual + insureds): 15 ambiguity-pins, 3 mismatch-revisions, +3,834 chars ===
- §2 intro — insert — ambiguity — trailing slash on any route names the same route (app.py:19)
- §2.1 — insert — ambiguity — header absent or empty fails authn; role match is case-sensitive/exact (auth.py:21-24)
- §2.2 — insert — ambiguity — api_request_id is req_ + 20 upper-case-alphanumeric chars (store.py:34-36)
- §2.3 — insert — ambiguity — creation-timestamp ties (ubiquitous, since the logical clock stands still) break on the server's monotonic insertion sequence, here and everywhere else the doc orders/picks by created_at (store.py:133-138, 95)
- §2.3 — insert — ambiguity — empty-string filter reads as absent; reportable accepts true/false/1/0 any case, any other spelling matches nothing (routes/common.py:5-32)
- §2.4 — insert — ambiguity — clock-advance audit stamps render normalised ...mmmZ whatever spelling set the clock; current_utc is the only verbatim echo (store.py:22-31, Store.logical_now)  [NOTE: pass 2 later corrected this claim]
- §2.4 — revise — mismatch — version increments once per request, not per mutation; a record created by the same call returns at version 1 despite cascades (store.py:105-129)
- §2.5 — insert — ambiguity — numerics accept a JSON number or its decimal-string spelling; booleans never accepted for numerics (val.py:95-109)
- §2.8 tier 3 — revise — mismatch — ownership is tested against the resolved record only; an Insured addressing a nonexistent id gets the not-found error, not ERR_NOT_RESOURCE_OWNER (auth.py:107-135; routes/insureds.py:70, verified identical in policies/claims/negotiations)
- §2.8 tier 5 — insert — ambiguity — absent/unparseable body reads as {}; non-object JSON body rejected; whitespace-only required string fails (val.py:80-86, 121-129)
- §2.8 note — revise — mismatch — the ERR_VALIDATION enumeration omitted the enrollment completed_on >= enrolled_on rule, and it is evaluated after the step-13 enrollment state check (routes/insureds.py:170-173)
- §3.1 — insert — ambiguity — hazard_index may carry up to six decimal places (routes/rate_manual.py:25-31)
- §3.1 — insert — ambiguity — PURE_PREMIUM_METHOD yields null indicated_change_pct when claim count or the rounded target-premium x 0.6500 is zero, while experience_loss_ratio still reports (services/actuarial.py:108-119)
- §3.2 — insert — ambiguity — high_severity_procedure_pct up to six decimal places (routes/insureds.py:26-32)
- §3.2 — insert — ambiguity — new insured carries surcharge_pct, closed_paid_claim_count, open_claim_count, npdb_reported_payment_total present and zero (routes/insureds.py:53-57)
- §3.2 — insert — ambiguity — credentialing verdict overwrites credentialing_expires_on (omission clears it to null), and a reinstating verdict with no expiry leaves the insured SUSPENDED (routes/insureds.py:100-105)
- §3.3 — insert — ambiguity — stacked credit is derived on demand, so completion does not move the insured's version (routes/insureds.py:175-183)
- §3.3 — insert — ambiguity — peer review case opens with chair_user_id null (routes/insureds.py:210)
- §3.3 — insert — ambiguity — the stored surcharge_pct is the window position evaluated as of the current logical date (services/rating.py:158-162)
Consciously left unpinned (low value / non-observable): limit validated before offset when both are bad; v_int accepting integral floats; underscore-prefixed internal keys omitted from JSON; the catch-all Exception -> ERR_VALIDATION handler. §3.9's severity-trend prose deliberately deferred to pass 3.

=== PASS 2 (policies/terms/tail/rating/clock): 10 ambiguity-pins, 4 mismatch-revisions, +2,914 chars ===
- §2.4 — revise — mismatch — pass 1 claimed current_utc is "the one field" echoing the operator's clock string verbatim; issued_at, assigned_at, closed_at and consent_requested_at do too (all read db.logical_now() = raw clock_str, not the normalised now_iso()) (store.py:76, routes/policies.py:211,392)
- §2.6 — insert — ambiguity — accepted to_iso8601 spellings (optional Z, numeric offset converted to UTC, bare YYYY-MM-DD -> midnight), ERR_VALIDATION for absent/null/non-instant, clock may move backwards, and the five id lists are in sweep-processing order (routes/clock.py:18-22, val.py:65-76)
- §2.6 — insert — ambiguity — sweep steps 4, 5 and 6 process in creation order; an insured with no credentialing expiry date is passed over in step 5 (services/clock.py:65,79,83,92)
- §2.10 — insert — ambiguity — a policy that has become ACTIVE never falls back to QUOTED while a draft remains (services/rating.py:273)
- §2.10 — insert — ambiguity — term creation is not a status-re-deriving transition: it recomputes the money roll-ups only, so an EXPIRED/CANCELLED policy keeps that status while carrying a fresh draft (routes/policies.py:165-167)
- §3.5 — insert — ambiguity — a CREDENTIALED insured with a null credentialing_expires_on fails the issuance credential test (routes/policies.py:204)
- §3.5 — insert — ambiguity — issuance advances only a PROSPECT insured; ACTIVE/SUSPENDED are left as they stand (no underwriting-axis gate) (routes/policies.py:220-222)
- §3.5 — revise — mismatch — PRD said sweep promotion "changes only its own status and the policy's current_term_id"; the pointer actually lands on the same term (an ISSUED term is already a candidate) while the policy's version/updated_at are still refreshed, and status/roll-ups are untouched (services/clock.py:38-41, services/rating.py:240-253)
- §3.5 — insert — ambiguity — flat cancellation's mass denial does not re-derive the insured's claim counters or stored classification and re-rates no draft (routes/policies.py:255-272)
- §3.5 — revise — mismatch — pro-rata cancellation set the policy status to CANCELLED unconditionally; made it conditional on no term remaining in DRAFT/ISSUED/IN_FORCE (a policy with another in-force term stays ACTIVE) (routes/policies.py:282, services/rating.py:269-278)
- §3.5 — insert — ambiguity — trigger_reason is recorded as supplied and never cross-checked against tail_type (routes/policies.py:294-295)
- §3.5 — insert — ambiguity — ERP_5YR window end when the effective date is 29 February: anniversary read as 28 February before subtracting the day (val.py:56-62)
- §3.5 — revise — mismatch — "Finally, the new tail's closed window..." implied the overlap test runs last; it runs before applicability and DDR eligibility per §2.8 steps 15/16 (routes/policies.py:317-333)
- §3.5 — insert — ambiguity — tail issuance repeats only the one-issued-tail-per-term test; the window-overlap check is not re-run, so two tails quoted while both were QUOTED over different triggering terms can both be issued with intersecting windows (routes/policies.py:384-390)
Notes: left §3.5's "every settlement negotiation on those claims" wording alone — impl abandons negotiations on all claims responding to the flat-cancelled term including already-DENIED ones, but a live negotiation cannot exist on a DENIED claim (routes/negotiations.py:41-45), so the difference is unreachable. Left the prose order of applicability-vs-term-status in the tail-quote paragraph alone, since it carries no ordering word and §2.8 governs.

=== PASS 3 (claims/reserves/counsel/negotiations/NPDB/analytics): 20 ambiguity-pins, 3 mismatch-revisions, +5,637 chars ===
- §3.6 coverage-trigger — insert — ambiguity — candidate set spans all of the insured's policies at once whatever the form, each term tested by its own policy's trigger, single winner picked across the combined set; tails consulted only when that combined set is empty (services/claims.py:41-99)
- §3.6 claims-made — revise — mismatch — winner is selected first (latest effective date, ties by earlier creation), and the retroactive-date test is then applied to that winning term's own policy only; PRD had the retro test gating selection and referred vaguely to "the policy" (services/claims.py:63-69)
- §3.7 reserve entry — insert — ambiguity — effective_at echoed verbatim (never normalised) while ordering compares the instant denoted; accepts trailing Z, numeric offset (converted to UTC) or bare YYYY-MM-DD; absent/unparseable -> ERR_VALIDATION (routes/claims.py:137-142, val.py:65-76)
- §3.7 projection — insert — ambiguity — the entry also carries the client's raw indemnity_amount/expense_amount as supplied, both null on a formula-basis posting (routes/claims.py:172-176)
- §3.7 projection — insert — ambiguity — with no responding term there is no limit_per_claim to cap against, so the rounded raw indemnity stands (services/claims.py:113-115)
- §3.7 reserve of record — insert — ambiguity — a tie on both effective_at and created_at is won by the later insertion sequence (services/claims.py:124-126)
- §3.7 reserve of record — insert — ambiguity — the nested postings listing resolves the claim before checking pagination, so ERR_CLAIM_NOT_FOUND beats ERR_PAGINATION_INVALID (routes/claims.py:189-191)
- §3.7 panel firms — insert — ambiguity — conflict_insured_ids recorded as supplied and never resolved; an id naming no insured is accepted (routes/counsel.py:30, val.py:265)
- §3.7 decline — insert — ambiguity — open_assignment_count is floored at zero however the decrement arises (services/counsel.py:53-55)
- §3.7 panel standing — insert — ambiguity — no standing is terminal and none is a precondition; a REMOVED firm may be returned to ACTIVE without restoring replaced assignments (routes/counsel.py:72-83)
- §3.7 expense payment — revise — mismatch — check order is exists -> claim handling status -> ERR_ASSIGNMENT_STATE_INVALID -> ERR_ASSIGNMENT_CLAIM_MISMATCH; PRD had mismatch before state (routes/claims.py:229-234)
- §3.7 expense payment — insert — ambiguity — the call answers with the updated claim, not the assignment or firm (routes/claims.py:246)
- §3.8 negotiation create — insert — ambiguity — approver_note also opens null (routes/negotiations.py:69)
- §3.8 revision — revise — mismatch — the "only things carried forward" claim was false: approver_note and consent_requested_at also survive a revision (routes/negotiations.py:202-211)
- §3.8 payment — insert — ambiguity — the call answers with the negotiation, not the claim the cascade rewrote (routes/negotiations.py:301)
- §3.9 disposition — insert — ambiguity — verdict_amount required only on PLAINTIFF_VERDICT; supplied with another disposition it is validated and recorded but pays nothing (routes/claims.py:260-265, services/claims.py:213-214)
- §3.9 disposition — insert — ambiguity — the SETTLED refusal is part of the payload check and precedes claim existence (routes/claims.py:253-258)
- §3.9 resolution cascade — insert — ambiguity — disposition is recorded too, SETTLED on a payment, whose resolved_on is the negotiation's payment_date (routes/negotiations.py:294-300, services/claims.py:210-212)
- §3.9 resolution cascade — insert — ambiguity — the disposition path raises no aggregate or per-claim-headroom refusal (aggregate may go negative); with no responding term the gross verdict is uncapped and nothing is debited; the debit fires only when the paid figure exceeds zero (services/claims.py:220-234)
- §3.9 NPDB creation — insert — ambiguity — the obligation's payment_date is the claim's resolved_on; a fresh obligation carries submitted_on/submitter_note null, submitted_late false, days_late 0 (services/claims.py:187-193, 246)
- §3.9 severity trend — insert — ambiguity — all four query params validated (ERR_VALIDATION) ahead of the specialty lookup, including a venue_code outside the five declared venues; the read carries no pagination block and ignores limit/offset (routes/analytics.py:18-31, envelope.py:28-30)
- §3.9 severity scope — insert — ambiguity — no coverage-position filter applies here, unlike §3.1's experience scope (services/actuarial.py:144-158)
- §3.9 verdict scope — insert — ambiguity — venue_code echoes null when unsupplied and the two report-date bounds are not echoed at all (services/actuarial.py:191-202)
Verified as already uniquely pinned (no edit): severity banding and factors, both incurred-loss formulas and their clamps, panel eligibility gates and the quality/rate/creation ranking, candidate_pool_size/selection_rank_snapshot, assignment/decline/removal/resolution capacity accounting, hammer arithmetic and its pinned cap->excess->split order, authority-grant bounds, payment fiscal-check order, NPDB reportability tests and lateness derivation, and every endpoint's payload field order.

Orchestrator verification: PRD_COMPLETED.md is 470 lines / 122,744 chars, NOT byte-identical to PRD_FINALIZED.md (45 changed lines), and ends at the completed §5 error table. Each later pass independently re-confirmed the earlier passes' edits were still present (no cp clobber). Step 9 made no change to implementation/, so the Step 7 sweep result (8/8 rounds 305/305) still stands.
