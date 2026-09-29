## Step 1: Create task directory — 2026-09-06T00:42:21.578416042Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2979_rail_demurrage_detention_billing_dispute and its workspace/ subdirectory. Index 2979 was pre-assigned by the invoking harness; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-06T02:29:55.330387377Z

Done. `VERDICT: clean lint`.

## Deliverables

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2398 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2624 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6466 |

Structure verified: `SCAFFOLD.yaml` has no `scaffold_difficulty_design`/`scaffold_corner_design` key; each design file has exactly one top-level key. All three parse with `yaml.safe_load`. Final lint: 51 endpoints, 13 entities, 24 §1.8 instances, 93 §1.9 instances, 1605 calls scanned, zero violations, all §1.1 FKs reverse-reachable.

## Domain model

`api_prefix: /demurrage`; profile = `ledger_reconciliation` × `multi_party_negotiation`, layers `[dual_variant_calculation, rate_threshold_triggers, cascading_side_effects, optimistic_concurrency]`, cyclic state machines, `segregation_of_duties`, `immediate` consistency, `expert_plus`.

**13 entities:** Customer, RailCar, Facility, TariffRuleSet, PlacementCycle, ArrivalNotification, DemurrageCharge, Invoice, DemurrageDispute, DisputeEvidence, BunchingClaim, AverageAgreement, RegulatoryComplaint.

**51 endpoints** across 5 roles with non-overlapping exclusive ladders: BillingAdmin (clock, customers, credit-hold, facilities, invoices/issue/close, average-agreements/reconcile, cycle void), RailroadAgent (rail-cars, cycles, constructive-placement, notify, actual-placement, access-mode, complaint answer), Customer (acknowledge, refuse, release, bunching claims, disputes/evidence/submit/resubmit/appeal, regulatory complaints), DemurrageAdjudicator (analyze, begin-review, request-info, decide — the only persisted `X-User-ID`), RegulatoryOfficer (tariff create/publish, complaint decide).

**8 state machines**, all cyclic where it matters: PlacementCycle carries independent movement (`ORDERED -> CONSTRUCTIVELY_PLACED -> ACTUALLY_PLACED -> RELEASED | VOIDED`) and billing axes; DemurrageDispute loops `DRAFT -> SUBMITTED -> UNDER_REVIEW <-> INFO_REQUESTED -> DECIDED -> APPEALED -> UNDER_REVIEW -> DECIDED -> ESCALATED`, with a second-round `begin-review` barred to the round-1 adjudicator; TariffRuleSet `PUBLISHED -> CHALLENGED -> WITHDRAWN | PUBLISHED` driven by the regulatory complaint.

**9 calculations, hardest rules:** C1 clock-basis selection (constructive placement + 4 h EDI grace vs FAX positive acknowledgement, `ACTUAL` only if actual placement lands inside constructive free time); C2 whole-day counting with the `gate_close_hour` rule that charges the release day; C3 storage under two clocks (calendar-midnight vs hourly-ceiling) over the same dwell; C4 the three-tier per-diem ladder split by car ownership (RAILROAD_OWNED / PRIVATE / PRIVATE_ASSIGNED takes railroad free time on the private ladder); C5 dispute credit as per-line `ROUND_HALF_UP` (which beats sum-then-round by a cent) then a claim-cap waterfall trimming the *last* line; C6 bunching attribution with two baselines (declared capacity vs `FLOOR(prior-7-date/7)`) exempting the last arrivals per date; C7 average-agreement credit staged and `FLOOR`-capped on gross; C9 adjudication due date = `CEIL(20 x grounds_multiplier) - MIN(5, FLOOR(evidence_weight/2))` business days.

**Validation ladder:** 29 rules on an explicit priority ladder (auth 10/12 -> role 20 -> ownership 22 -> SoD 24 -> existence 30/32 -> schema 34/36 -> state 40 -> OCC 412 at 44 -> domain gates 50-79), 58 error codes, 2 `concurrency_rules` (`expected_invoice_version` on dispute create, `expected_rail_car_version` on cycle create, the latter deliberately ranked above the car-overlap check).

## Counts

- §1.8: **9 rules / 24 instances** (dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2).
- §1.9: **113 instances over all nine sections — 93 with full `test_recipe`s, 20 legitimately `excluded_because`** (each citing a real §1.8 instance; all citations validated against §1.8 names). Breakdown: entities 24, state_machines 22, calculations 12, validations 24, endpoints 6, errors 9, rbac 8, complexity_layers 6, consistency_model 2.
- Every one of the 58 declared error codes is cited by at least one §1.8/§1.9 instance.

Every money and timestamp literal was computed with a reference implementation of C1-C9 left at `.scratch/step2/calc.py` (plus `endpoints.txt` and `vals.txt` lookups). `worklog.md` untouched by the subagent. No sibling task directory was read.

Orchestrator note: grepped the whole task dir for the string "harder than expert level" after Step 2 — zero hits, so the difficulty directive did not leak into SCAFFOLD.yaml's scenario key (a known scaffold-generator failure mode). No strip needed.

## Step 3: Copy shared files — 2026-09-06T02:30:00.490031087Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (%s bytes).

## Step 4: Generate PRD — 2026-09-06T02:50:59.754454697Z

PRD.md is complete and verified. **490 lines, 115,910 bytes.**

## Outline checklist (grep-verified, all present)

All 24 headings present: title; §1 Introduction; §2 Global Specifications with 9 subsections (2.1 Actors/Identity Headers, 2.2 API Response Structure incl. both fixed sub-blocks, 2.3 Pagination and List Ordering, 2.4 Resource Identity/Version Counters/Logical Clock, 2.5 Three Day Calendars, 2.6 Money Discipline integer cents, 2.7 Optimistic Concurrency, 2.8 The Rejection Ladder with 28 ordered bands, 2.9 Derived Fields/Cascades/Version Semantics); §3 Business Logic with 9 subsections (3.1 Reference Data, 3.2 Ordering/Constructive Placement, 3.3 Arrival Notice/Acknowledgement/Clock-Basis Election, 3.4 Spotting/Refusal/Track Limits, 3.5 Release/Free-Time Settlement/Two Storage Clocks, 3.6 Rating the Charge/Tier Ladder/Bunching/Re-Laddering, 3.7 Invoicing/Average Agreements/Closing/Voiding, 3.8 Disputes filing through supersession, 3.9 Regulatory Escalation); §4 Endpoint Definitions (51 rows); §5 Error Code Catalogue (58 rows).

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Re-derived the required identifier set from SCAFFOLD.yaml (146 names) and diffed against every backticked token in PRD.md: 0 missing. All 93 distinct enum member values present; all 58 error_id values present. The 51 `METHOD path` pairs in §4 diff byte-identically against the scaffold's 51; §5's 58 rows diff byte-identically against the scaffold `errors:` block.

**Contract 2 — Rule Coverage: PASS.** All 29 validations rendered as the 28-item ordered ladder in §2.8 (two attempt-counter and two not-found bands consolidated exactly as the scaffold's own combined error_id fields prescribe), with applies_to scopes named in prose. Both concurrency_rules (expected_rail_car_version, expected_invoice_version, both 412) in §2.7 and restated at call sites. All 9 state machines have prose homes including the transient ANALYZED state and the cyclic CHALLENGED -> PUBLISHED loop. All 9 calculations translated with constants, rounding modes and edge_cases. Sibling-branch symmetry preserved in all four forks. Zero pseudocode residue; zero fuzzy words (the scaffold's one fuzzy phrase, "roughly 2.8x the tier-1 rate", was replaced with exact 35050-vs-12550 figures).

**Contract 3 — §3 Path Purity: PASS.** No endpoint paths, bare HTTP methods, or method+path combinations anywhere in §3. Paths appear only in §2.7 and §4, where the contract permits.

## Verbatim final 5 lines

    | `ERR_APPEAL_NOT_EXHAUSTED` | 422 |
    | `ERR_ORDERED_CREDIT_EXCEEDS_CLAIM` | 422 |
    | `ERR_CLAIM_NO_DELIVERIES` | 422 |
    | `ERR_NO_PENDING_NOTIFICATION` | 422 |
    | `ERR_NOTIFICATION_NOT_SENT` | 422 |

File ends on a complete table row at a real document boundary, not a mid-sentence cut.

## Two decisions the orchestrator should know

1. **Header naming normalized.** The scaffold says `X-Role-Name` throughout, but the doc-generator skill (and its example-prd.md) fixes the auth headers as `X-User-ID` and `X-User-Role`. The PRD uses `X-User-Role`. The test generator must be told to use `X-User-Role`, not the scaffold's `X-Role-Name`.
2. **Two scaffold gaps were closed by placement, not invention.** `ERR_SUPERSEDE_TARGET_INVALID` has no validations[] entry (errors[]-only), so it is documented in §3.8 in the referential-integrity band. `ERR_NOTIFICATION_NOT_SENT` has no declared priority, so §2.8 places it last, below the credit-hold check, and §3.5 states the same.

The withheld design indices were never opened. No sibling task directory was read.

Orchestrator verification (independent of the subagent's own report): `wc -l` = 490; `tail -12` ends on the complete table row `| ERR_NOTIFICATION_NOT_SENT | 422 |`; `grep '^#'` returns all 24 planned headings in order; `grep -c X-Role-Name` = 0 and `grep -c X-User-Role` = 4, so the header normalization is clean in the PRD itself. No truncation — no regeneration needed.

Decision carried forward: because the PRD is the only contract the implementer reads, the Step 5 test-generator prompt is being told explicitly that PRD.md wins over SCAFFOLD.yaml on the auth header name (`X-User-Role`, never `X-Role-Name`). Steps 5 and 6 are launched in a single assistant message so the impl generator is physically unable to read test_suite/.

## Step 6: Generate implementation — 2026-09-06T03:32:39.116403847Z

Implementation complete: 17 files, 3793 lines of Python in workspace/implementation/.

| lines | file |
|---|---|
| 86 | `errors.py` |
| 160 | `clockcal.py` |
| 81 | `store.py` |
| 96 | `envelope.py` |
| 81 | `auth.py` |
| 199 | `schema.py` |
| 297 | `calc.py` |
| 428 | `derive.py` |
| 275 | `cascade.py` |
| 104 | `guards.py` |
| 289 | `routes_reference.py` |
| 489 | `routes_cycles.py` |
| 214 | `routes_billing.py` |
| 706 | `routes_disputes.py` |
| 220 | `routes_regulatory.py` |
| 68 | `app.py` |
| — | `start.sh` (executable), `requirements.txt` (flask>=3.0) |

## Module decomposition and where each PRD rule lives

- **errors.py** — full 58-entry §5 catalogue as error_id -> HTTP status, verified programmatically against PRD §5: 58 vs 58, no missing ids, no extras, no status mismatches. `fail()` is the single raise point.
- **clockcal.py** — §2.4/§2.5 time. Three calendars (`is_eligible` for the tariff's weekend_excluded, `is_business` unconditional Mon-Fri, plain calendar dates), `nth_eligible`/`nth_business` (strictly-after semantics), `eod()` -> 23:59:59.999Z, `fmt_instant` with exactly 3 fractional digits, COLD_START_CLOCK = 2026-08-01T00:00:00Z, integer-millisecond whole_ms.
- **store.py** — in-memory only: 13 plain dicts, an RLock, a monotonic sequence, the logical clock. `base_record(kind, versioned=)` omits updated_at/version for CarNotification and DisputeEvidence per §2.4. Nothing seeded, preloaded, or hardcoded.
- **envelope.py** — §2.2 envelope (`req_` + 20 uppercase alnum request id) and §2.3 pagination (band 9).
- **auth.py** — ladder bands 1-5: X-User-Role/X-User-ID (PRD names, NOT the scaffold's X-Role-Name), role authorization, `require_owner` (no-op for non-Customer), and the round-2 ERR_SEGREGATION_OF_DUTIES bar.
- **schema.py** — band 8 only; typed validators plus Decimal-based number checks.
- **guards.py** — bands 6-7 (one 404 code per entity) and the §2.1 ownership chain.
- **calc.py** — all nine §3 calculations: free-time election and clock basis, chargeable-day counting (release-day-vs-gate-close, early release), storage days, three-tier ladder with integer-cent arithmetic, grounds multipliers, evidence weight points, adjudication-deadline arithmetic (ceil-multiplier then floor-halved evidence credit capped at 5, 5-day floor, 0.50 appeal multiplier).
- **derive.py** — every read-side derivation (invoice rollup and compound status, credit_balance_cents, dispute_posture precedence, occupied spots, last switch, evidence weight) plus all 13 JSON projections.
- **cascade.py** — cross-entity rewrites: charge repricing with the ladder re-walked from tier one, invoice re-derivation, agreement day rebuild, the 8-step `apply_agreement_credit` (FLOOR cap, entries ordered by descending rate) and its exact reversal.
- **routes_reference.py** — §3.1 + the logical clock. **routes_cycles.py** — §3.2-§3.6 movement two-dimension state machine, notices, release ordering. **routes_billing.py** — §3.7 invoicing/closing/agreements. **routes_disputes.py** — §3.6 bunching claims and §3.8 dispute lifecycle including per-line ROUND_HALF_UP then the backwards claim-ceiling waterfall. **routes_regulatory.py** — §3.9 complaints and the tariff challenge loop.
- **app.py** — blueprints under /demurrage, ApiError -> error envelope, HTTPException -> ERR_INVALID_REQUEST at 404/405, threaded=True, use_reloader=False, host 0.0.0.0, port $PORT.

Contract conflicts were resolved for PRD.md every time: X-User-Role/X-User-ID headers; no version bump on the agreement at invoice issue (§2.9 "where §3 is silent, no increment occurs"); no tariff version bump when a complaint is filed but one when it is decided (§3.9 states it explicitly only there); release band order state(10) -> embargo(12) -> chronology(19) -> credit hold(23) -> notification(28).

## Smoke-test evidence (port 51979, killed by captured PID only — never a pattern kill)

Boot: `PORT=51979 bash start.sh` -> GET /health -> {"status":"ok"}; GET /demurrage/invoices as BillingAdmin -> total_count 0; unauthenticated -> 401.

Full lifecycle against a fresh process, all responses as expected: customer -> tariff publish -> facility -> car -> cycle -> constructive placement -> notify (DELIVERED, sequence_number 1) -> actual placement (clock_basis ACTUAL) -> clock move -> release (chargeable_days 6, gross 127500 = 2x12550 + 3x22450 + 1x35050, release day not charged because 10:00 precedes gate_close_hour 16) -> invoice DRAFT (totals 0) -> issue (dispute_deadline_at 2026-09-19) -> dispute -> evidence (weight_points 3) -> submit (adjudication_due_at 2026-09-16 = 19 business days: 20x1.00 ceil minus floor(3/2)) -> begin-review -> decide PARTIALLY_ALLOWED 0.5 (credit clipped to the 1000 claim ceiling) -> appeal (deadline recomputed to 2026-09-03 = 10 business days from the appeal date) -> review by a second adjudicator -> decide ALLOWED -> regulatory complaint (docket_number D-00001, response_due_at 2026-09-10 = 15 business days) with tariff -> CHALLENGED, challenge_count 1, dispute -> ESCALATED -> answer -> decide DECIDED_FOR_CUSTOMER with ordered_credit_cents 500: tariff -> WITHDRAWN with challenge_count preserved, and the consignee's credit_balance_cents stayed 1000 — the regulator's order was recorded, not posted.

Second flow (fresh process): 4 yard cycles -> bunching claim ORDERED_VS_CAPACITY -> analyze PARTIALLY_GRANTED (baseline 2, 4 arrivals, last 2 exempted at k=1 and k=2 -> 3 exempt days of 28) -> invoice gross 225000 = 25 storage days x 9000 -> agreement reconcile FORFEITED at net_days -28 -> close -> cycles SETTLED. Error envelopes verified for 404 unknown path, 405, ERR_INVALID_PAGINATION, unknown role (401), missing X-User-ID (401), ERR_ROLE_FORBIDDEN (403), ERR_REGULATORY_COMPLAINT_NOT_FOUND (404).

Zero-seed re-verified on a final fresh boot: placement-cycles, charges, invoices, disputes, regulatory-complaints all total_count 0 and the clock reads 2026-08-01T00:00:00.000Z. Every server killed by captured PID (876076, 882694, 884511, 884808), each confirmed gone with `ps -p`, 0 listeners left on 51979.

`python3 -m compileall -q .` clean. Nothing written outside workspace/implementation/ except .scratch/step6/, removed with a scoped `rm -rf .scratch/step6`. test_helpers/, test_suite/, worklog.md and PRD.md were never created, read, or modified.

Orchestrator note: Step 6 finished while Step 5 was still emitting test files, which confirms the intended physical isolation — the impl generator could not have read test_suite/ because most of it did not exist during its run.

## Step 5: Generate unit tests — 2026-09-06T05:41:47.775641272Z

Step 5 is complete.

## Deliverables (task root, not workspace/)

`test_helpers/` — 2,647 lines: __init__.py 17, api_client.py 371, api_errors.py 152, assertions.py 336, constants.py 337, factories.py 332, fixtures.py 755, test_users.py 128, types.py 219.

`test_suite/` — 10,988 lines: conftest.py 69; test_01_dual_variant_calc 419, test_02_combinatorial_formula 433, test_03_non_linear_state_machine 724, test_04_transitive_cascade 378, test_05_priority_pair_validation_conflict 335, test_06_boundary_precision_check 427, test_07_cross_entity_state_dependency 409, test_08_resource_temporal_overlap 270, test_09_compensating_invariant 391, test_10_corner_entities 1178, test_11_corner_state_machines 1679, test_12_corner_calculations 788, test_13_corner_validations 1664, test_14_corner_endpoints 545, test_15_corner_errors 129, test_16_corner_rbac 551, test_17_corner_complexity_layers 378, test_18_corner_consistency_model 221.

## Coverage: 141 tests, all design-index-derived

**Queue A (§1.8 difficulty) — 24/24 instances translated, 0 skipped, 48 tests** (exactly 2 per instance): dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**Queue B (§1.9 corner) — 93/113 instances translated, 93 tests, 20 skipped**: entities 24/24, state_machines 19/22, calculations 8/12, validations 21/24, endpoints 6/6, errors 1/9, rbac 8/8, complexity_layers 4/6, consistency_model 2/2.

All 20 skips fall in ONE category: the instance carries an `excluded_because:` block in SCAFFOLD_CORNER_DESIGN.yaml naming the §1.8 difficulty instance that already drives the same claim, so translating it would duplicate a queue-A test rather than add coverage. A mechanical check confirmed a perfect one-to-one partition — every instance with `excluded_because` is untested, every instance without it has exactly one test, zero mismatches. Breakdown: state_machines 3, calculations 4, validations 3, errors 8, complexity_layers 2.

## Audit results

- **Design tags**: 141 tests, 141 tagged, exactly one `Design:` line each, 117 distinct tags (queue-A instances legitimately carry 2 tests; no Corner tag reused); every tag's instance name validated verbatim against a `name:` in the source scaffold.
- **PRD citations**: an AST-based audit checks every quoted run of >=40 chars in every docstring against a normalized PRD — 0 failures. This pass caught and fixed a systemic defect cluster manual review had missed: 10 paraphrased §2.8 ladder-band quotes in test_10, four dropped section glyphs (test_02 x2, test_05, test_07), three sentences truncated by an invented trailing period (test_09, test_13, test_16), a hyphen-minus where PRD §2.3 writes U+2212, and one quote-spanning regex artifact in test_16's §4 table docstring.
- **Section-attribution audit** (does the cited `PRD X.Y` name the section that actually holds the quote?): found and fixed 4 mis-attributions — test_08 x3 (§3.3 -> §3.2), test_09 (§2.4 -> §2.9), test_16 (§2.2 -> §2.1). Now 0 failures.
- **Envelope**: zero `body["error"]` reads; `data` is unwrapped in exactly one place (assertions.py:79) — the known double-unwrap hazard is structurally excluded.
- **Headers**: X-User-Role / X-User-ID throughout per the PRD-wins adjudication; zero occurrences of the scaffold's X-Role-Name.
- **pyflakes**: clean across both directories (two now-unused imports removed from fixtures.py).
- **Final gate**: compileall clean; __pycache__ removed afterwards.

`.scratch/step5/` deleted with a scoped rm; sibling scratch dirs (step2, step4, step7) untouched. workspace/ still contains only INSTRUCTION.md, PRD.md, implementation/ — never read or referenced by this agent. worklog.md untouched.

## Orchestrator verification (independent of the subagent's report)

- `ls workspace/test_helpers workspace/test_suite` -> both absent, so neither directory landed under workspace/ (a known Step 5 misplacement mode); both are correctly at the task root.
- `python3 -m compileall -q test_helpers test_suite workspace/implementation` -> COMPILEALL CLEAN across all three trees.
- Test functions counted from source: 141. `Design:` tag lines: 141. Exact match, so no untagged test slipped through.
- `grep -rn X-Role-Name` across test_helpers, test_suite and implementation -> 0 hits. The scaffold/PRD header conflict is resolved consistently on both sides of the harness, which is the precondition for the sweep not wiping out on auth.
- `grep -rn 'pytest.mark.skip|pytest.mark.xfail'` -> 0 hits, so the "gaps stay gaps" rule was honoured by omission rather than by marker.
- `.scratch/` still holds step2, step4 and step7 — the pre-written Step 7 sweep script survived both concurrent agents' cleanup.

## Step 7: Run tests and iterate — 2026-09-06T06:23:46.89062250Z

Clean sweep achieved. Final report:

## Step 7 — Test/Fix Iteration Report

### Iterations run: 3 full 8-round sweeps

| Sweep | Result |
|---|---|
| 1 (baseline) | 8/8 rounds `passed=130 total=141` — union of 11 failures, each failing 8/8 |
| 2 (after 9 fixes) | 8/8 rounds `passed=139 total=141` — union of 2 failures, each failing 8/8 |
| 3 (final) | **8/8 rounds `passed=141 total=141`, union of failing tests = 0** |

### Final sweep evidence

    results.1.json: passed=141 total=141 nonpassing_rows=0
    results.2.json: passed=141 total=141 nonpassing_rows=0
    results.3.json: passed=141 total=141 nonpassing_rows=0
    results.4.json: passed=141 total=141 nonpassing_rows=0
    results.5.json: passed=141 total=141 nonpassing_rows=0
    results.6.json: passed=141 total=141 nonpassing_rows=0
    results.7.json: passed=141 total=141 nonpassing_rows=0
    results.8.json: passed=141 total=141 nonpassing_rows=0
    UNION of failing tests across all rounds: 0

No key mismatch, no ServerStartError, no traceback in any workspace/round.$i.log. Per-round artifacts: workspace/implementation/results.{1..8}.json and workspace/round.{1..8}.log.

### Tests deleted: NONE

All 141 tests survive. Every failure traced to a test-artifact defect or to an assertion that quoted a rule the PRD does state but that the test mis-translated; no test asserted a scaffold-only rule outright, so no PRD-silence deletion was warranted. Where an individual *assertion* was PRD-silent, STEP 1c partial-coverage splitting was used (keep the covered assertion, drop the uncovered one) rather than deleting the test.

### Fixes to `test_helpers/` (1 file)

`test_helpers/fixtures.py`
- `make_cycle` — removed the `cycle["_rail_car_id"] = fresh["id"]` private breadcrumb. It was redundant: PRD §3.2 makes `rail_car_id` a projected field of the placement cycle and `derive.cycle_json` renders it, so callers can read the real field. The breadcrumb was the root cause of the 3-test `ERR_RAIL_CAR_NOT_FOUND — No such resource: None` setup cluster in sweep 1 (composites that re-read from the server dropped the private key, handing callers `None`), and an intermediate fix that copied the breadcrumb onto re-read bodies then broke two `assert frozen == cycle` snapshot-identity tests in sweep 2 by making a fixture dict unequal to a pure server read. Deleting the breadcrumb fixes both classes at once and makes every fixture return value exactly a server projection.
- `constructively_placed_cycle`, `noticed_cycle`, `actually_placed_cycle`, `released_cycle` — all four now return a plain `get_cycle(api, cycle["id"])`, i.e. an unadulterated server read.

### Fixes to `test_suite/` (7 files)

- `test_08_resource_temporal_overlap.py` (shared helper, feeding `test_the_car_interval_is_open_at_released_at_to_the_millisecond` and `test_a_voided_cycle_occupies_no_interval_at_all`) — read the car id from the PRD-projected `cycle["rail_car_id"]` instead of the private breadcrumb.
- `test_12_corner_calculations.py::test_a_voided_line_leaves_the_rollup_without_being_detached` — same breadcrumb -> `rail_car_id` change.
- `test_11_corner_state_machines.py::test_voided_is_terminal_and_the_second_void_frees_nothing` — same breadcrumb -> `rail_car_id` change.
- `test_09_compensating_invariant.py::test_both_sides_of_the_ledger_are_rebuilt_rather_than_decremented` — same breadcrumb -> `rail_car_id` change, plus corrected the post-release expectation from `active_cycle_count == 1` to `== 0`: PRD §3.1 defines the count as "the number of placement cycles on this car whose `movement_status` is neither `RELEASED` nor `VOIDED`", so the release itself already drops it to zero.
- `test_11_corner_state_machines.py::test_a_dismissal_returns_the_challenged_tariff_and_keeps_the_scar` — dropped the filing-time assertion on the tariff rule set's own `version`. PRD §3.9's filing cascade states only the `PUBLISHED -> CHALLENGED` move and the `challenge_count` increment, and §2.9 says "where §3 is silent, no increment occurs on that secondary resource" (STEP 1c). The later dismissal-time `version` increment, which PRD §3.9 does state explicitly, is retained.
- `test_13_corner_validations.py::test_a_submit_one_day_past_the_deadline_is_refused` — expected `evidence_weight` corrected from 0 to the filed exhibit's weight. PRD §3.8: "Every exhibit re-derives the dispute's `evidence_weight` as the sum of the `weight_points` of its exhibits", so a DRAFT dispute holding one `SWITCH_LIST` already reads 3; added an explicit `== EVIDENCE_WEIGHT_POINTS[EVIDENCE_SWITCH_LIST]` check so the constant is still pinned.
- `test_13_corner_validations.py::test_a_withdrawn_tariff_blocks_new_cycles_without_touching_the_old_one` — moved the `tariff_rule_set_id` assertion off the charge line and onto the placement cycle. PRD §3.2's charge-line field inventory has no `tariff_rule_set_id`; the cycle is where PRD pins the rule set.
- `test_13_corner_validations.py::test_a_failed_notice_leaves_nothing_to_acknowledge` — expected `free_days` corrected from 0 to `DEFAULT_FREE_TIME_HOURS_RAILROAD // 24` (= 2). PRD §3.3 step 3 computes `free_days` from the tariff unconditionally; only step 5 nulls `clock_start_at`/`free_time_expires_at`. Added the missing constant import.
- `test_14_corner_endpoints.py::test_voiding_an_ordered_cycle_reverses_nothing_because_nothing_exists` — dropped `"void_reason": VOID_REASON` from the voided-cycle projection assertion. PRD §3.7 takes `void_reason` on the request but, unlike `constructive_reason_code` ("is stored as"), `access_mode_reason` ("recorded in") and `credit_hold_reason`, never declares it a recorded/rendered cycle field — DEFAULT/COMPUTED-FIELD SILENCE (STEP 1c). The request still sends it, so the schema requirement is still exercised.
- `test_16_corner_rbac.py::test_a_consignees_charge_list_is_narrowed_rather_than_refused` — gave the stranger consignee its own industry track. Setup was failing `ERR_FACILITY_SWITCH_BUFFER` because PRD §3.5 re-derives the shared facility's `last_switch_at` from Cycle A's 2026-08-10T16:00Z release, which lands after Cycle B's 2026-08-07T12:00Z actual placement and trips the PRD §3.4 switch-buffer guard for a reason unrelated to the RBAC rule under test. This is the pattern already documented in `fixtures.released_pair`.
- `test_17_corner_complexity_layers.py::test_the_replayed_invoice_version_is_told_its_read_is_stale` — dropped `grounds=GROUNDS_BUNCHING` from the retry payload (and its now-unused import). PRD §3.8 requires `BUNCHING` grounds to be paired with a `bunching_claim_id`, so the fixture was issuing a request the PRD forbids and setup died on `ERR_DISPUTE_SCOPE_MISMATCH`; the test is about `expected_invoice_version` OCC, and the default `RAILROAD_CAUSED_DELAY` grounds is PRD-consistent.

### Fixes to `implementation/`: NONE

Zero implementation files were modified — mtimes are all still 03:00-03:25 (Step 6 generation), well before this step's work. All 13 distinct failures across the two non-clean sweeps were test-artifact defects. Each "the implementation is right" verdict was verified against the source rather than the test's claim: `derive.charge_json` correctly omits `tariff_rule_set_id`; `derive.cycle_json` correctly omits `void_reason` (`routes_cycles.py:436` only schema-validates it); `calc.resolve_clock` correctly returns `free_days` even on the `"NONE"` clock-basis branch; and `routes_regulatory.py:99-106` deliberately increments only `challenge_count` on the challenge cascade with an in-code citation of §2.9.

### Load-induced failures: NONE

Every failure in both non-clean sweeps was deterministic at 8/8 rounds and carried a concrete assertion diff or a concrete error_id — never a timeout, connection reset or ServerStartError. No failure was written off as host load.

### Hygiene

worklog.md untouched by the subagent (mtime 05:41, predates all of this step's edits). compileall and pyflakes both clean over test_helpers/ and test_suite/. __pycache__ removed from both test dirs. `.scratch/step7/` still holds exactly sweep.sh and summarize.py; no sibling scratch dir was touched and no broad pattern kill was ever run.

## Orchestrator verification (independent of the subagent's report)

- Read all 8 results.$i.json myself: every round `passed=141 total=141`. I also read the baseline sweep myself at the time (`passed=130 total=141` in all 8 rounds), so the 130 -> 139 -> 141 progression is corroborated rather than self-reported.
- `ls -la --time-style=+%H:%M workspace/implementation/*.py` -> all 16 modules carry mtimes 02:57-03:25, i.e. Step 6 generation. Step 7 started at 05:41. The "0 implementation fixes" claim is therefore independently confirmed, not taken on trust.
- `grep -rh 'Design: ' test_suite/*.py | wc -l` -> 141, unchanged from Step 5. No test was quietly dropped while reporting zero deletions.
- `grep -rn 'mark.skip|mark.xfail'` -> 0. No failure was dodged with a marker.
- The pre-written sweep.sh + SWEEP_DONE sentinel design worked as intended: the setsid wrapper returned within a minute each time while the rounds ran on, and polling the sentinel (never relaunching) gave three clean joins with no reaping, no quoting corruption, and no ServerStartError.

Note for Step 8: because Step 7 applied 0 implementation fixes, the alignment target is unchanged code. The Step 8 focus list is therefore the PRD-silence sites the test fixes exposed — chiefly `void_reason` not being a rendered cycle field, the tariff `version` not incrementing at complaint filing (only at decision), `tariff_rule_set_id` absent from the charge-line projection, `free_days` being computed even when the notice fails, and `active_cycle_count` excluding RELEASED as well as VOIDED cycles. Step 8 is NOT skipped: the skip condition requires zero fixes in every layer, and test_suite/ and test_helpers/ both changed.

## Step 8: Finalize PRD — 2026-09-06T06:35:22.854512577Z

workspace/PRD_FINALIZED.md produced. Two edits; sibling scratch dirs (step2/step4/step7) intact.

**Line counts:** PRD.md 490 lines / 115910 B -> PRD_FINALIZED.md 490 lines / 116458 B. Line delta 0 (+0.0%); byte delta +548 (+0.47%). Two lines revised in place (193, 303), nothing added or removed. `tail -5` confirms the error-code table still terminates at ERR_NOTIFICATION_NOT_SENT — no truncation.

### Changes

- **§3.2 (charge line birth inventory)** — revise — added that the charge line carries no tariff reference of its own, is not projected with a `tariff_rule_set_id`, and that rating reaches the rule set through the `tariff_rule_set_id` pinned on the owning cycle — `derive.py:291-307` (charge_json), `cascade.py:24`.
- **§3.7 (Voiding a cycle)** — revise — added that `void_reason` is required and must be a non-empty string, but is a request-schema obligation only: not retained on the cycle, not present in the cycle projection — `routes_cycles.py:436`, `derive.py:246-269`.

### Per-edit pre-edit search log

**Edit 1 — §3.2 charge-line tariff reference**
- (a) Subject: whether a charge line carries/projects a tariff rule set reference, and how the charge's governing tariff is resolved.
- (b) Paths enumerated: `grep -rn "tariff_rule_set_id" implementation/*.py` -> all 13 hits read. derive.py:291-307 charge_json (full key list, no tariff key); derive.py:252 cycle projection has it; derive.py:414 the **regulatory complaint** projection also has its own tariff_rule_set_id; cascade.py:24 rating resolves db.tariffs[cycle["tariff_rule_set_id"]]; routes_disputes.py:420 adjudication-deadline base also resolves the tariff via cycle["tariff_rule_set_id"]; routes_cycles.py:88/96/126/159 (cycle create + list filter); routes_regulatory.py:48/56/82/130/171/208 (complaint's own field). Also read derive.py:169-174 _common to confirm no shared injection of the key.
- (c) Adjustment: the first draft said the cycle "is the only place a tariff_rule_set_id lives" — false, because derive.py:414 puts one on the regulatory complaint. Re-scoped the sentence to the charge line only ("The line carries no tariff reference of its own"), and worded the resolution path as "every rating or re-rating of the line reaches the governing rule set through ... its owning cycle", which is true of both enumerated consumers (cascade.py:24, routes_disputes.py:420) without claiming global exclusivity.

**Edit 2 — §3.7 void_reason**
- (a) Subject: the lifecycle of `void_reason` — validated? stored? projected? — and, by extension, the cycle projection's key set.
- (b) Paths enumerated: `grep -rn "void_reason" implementation/*.py` -> exactly one hit, routes_cycles.py:436 `schema.req_str(data, "void_reason", 1)`; read schema.py:62-65 to confirm req_str(minlen=1, maxlen=None) i.e. required, non-empty, no upper bound. Read the whole void_cycle handler (routes_cycles.py:430-460) to confirm the value is never assigned to the record and never reaches a cascade. Read derive.py:246-269 cycle_json plus derive.py:240-243 _CYCLE_INSTANTS and derive.py:169-174 _common to confirm the projected key set is fixed and state-independent. Also checked the sibling reason fields so the contrast drawn is accurate: constructive_reason_code IS stored and projected (constructive-placement handler, derive.py:256); access_mode_reason and credit_hold_reason live on facility/consignee, not the cycle; and refusal_reason (routes_cycles.py:354) is, like void_reason, validated-only and unprojected.
- (c) Adjustment: the first draft contrasted void_reason against "the other reason codes, which are recorded" — that would have implied §3.4's refusal_reason is stored, which routes_cycles.py:354 contradicts and which is outside the Step 7 scope anyway. Narrowed the contrast to the single field verified as stored (constructive_reason_code) and made no general claim about reason fields. Added "reads back with exactly the same field inventory it had before" only after confirming cycle_json emits a fixed key set on every branch.

### Step 7 items deliberately NOT patched

- **fixtures.py breadcrumb removal + the four *_cycle fixtures now returning plain server reads** — pure fixture bug. rail_car_id is already a PRD §3.2 projected field and derive.cycle_json:250 renders it. No silence.
- **test_08 / test_12 / test_11 / test_09 breadcrumb -> rail_car_id** — same fixture bug, no PRD silence.
- **test_09 active_cycle_count 1 -> 0 after release** — PRD §3.1 already pins it verbatim: "the number of placement cycles on this car whose movement_status is neither RELEASED nor VOIDED". Test mis-translated a stated rule; prose kept verbatim.
- **test_11 tariff version not bumped on challenge filing** — already determined by the interaction of §3.9 (filing cascade names only the PUBLISHED -> CHALLENGED move and the challenge_count increment) and §2.9's explicit default ("where §3 is silent, no increment occurs on that secondary resource"). routes_regulatory.py:99-106 matches, with an in-code §2.9 citation. No silence to close.
- **test_13 evidence_weight on a DRAFT dispute** — PRD §3.8 states "Every exhibit re-derives the dispute's evidence_weight as the sum of the weight_points of its exhibits" and fixes SWITCH_LIST at 3. Determined.
- **test_13 free_days = 2 on a failed notice** — PRD §3.3 already determines it: the election "writes three fields — clock_basis, clock_start_at and free_time_expires_at — alongside free_days", step 3 computes free_days with no branch on the basis, and step 5 nulls only clock_start_at/free_time_expires_at. calc.resolve_clock:117-119 returns free_days even on the NONE branch. Prose kept verbatim per the "already determined => verbatim" rule.
- **test_16 RBAC stranger given its own industry track** — pure fixture bug; setup was tripping the §3.4 switch-buffer guard via §3.5's last_switch_at re-derivation, both of which the PRD already states. No silence.
- **test_17 dropped grounds=GROUNDS_BUNCHING** — pure fixture bug; the fixture was issuing a payload PRD §3.8 forbids (BUNCHING grounds unpaired with bunching_claim_id). No silence.

Net: of the 13 distinct Step 7 failures, 11 traced to rules the PRD already states and 2 to genuine default/computed-field silences — hence the deliberately small patch.

## Orchestrator verification (independent of the subagent's report)

- `wc -l -c` both files: 490/115910 vs 490/116458, matching the reported delta.
- `diff PRD.md PRD_FINALIZED.md` read in full: exactly two changed lines, `193c193` and `303c303`, both pure in-place sentence expansions. No line was added, removed, or reordered anywhere else in the document, so nothing was lost to a truncating rewrite.
- `tail -3 PRD_FINALIZED.md` ends on `| ERR_NOTIFICATION_NOT_SENT | 422 |` — same terminal row as PRD.md, confirming the §5 catalogue is intact.
- Step 8 was correctly NOT skipped: the skip condition requires zero fixes in every layer, and test_suite/ plus test_helpers/ both changed even though implementation/ did not. A near-identical PRD_FINALIZED.md is the legitimate outcome here precisely because Step 7 made no implementation fixes — there was no impl-drifted-from-PRD divergence to reconcile, only two genuine silences.

Plan for Step 9: because a single agent scanning 3793 lines of implementation against a 490-line PRD reliably under-covers (and a byte-identical PRD_COMPLETED.md is the signature of a scan that never ran), Step 9 is being run as three sequential module-partitioned passes over one shared PRD_COMPLETED.md, followed by a fourth narrow reconciliation pass to close any cross-pass contradictions the partitioning introduces. Pass 1 performs the `cp` from PRD_FINALIZED.md; passes 2-4 must not.

## Step 9: Complete PRD — 2026-09-06T07:31:41.23487494Z

Step 9 was run as **three sequential module-partitioned passes over one shared PRD_COMPLETED.md, plus a fourth narrow reconciliation pass**, rather than as a single scan. Rationale recorded here as the orchestrator's judgement call: one agent scanning 3793 lines of implementation against a 490-line PRD reliably under-covers, and a byte-identical PRD_COMPLETED.md is the signature of a scan that never ran. Partitioning by implementation module guarantees every module is actually walked; the cost is that partitioned passes report cross-pass contradictions instead of fixing them, which is exactly what pass 4 exists to close. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2-4 were explicitly forbidden from copying, so no pass could clobber its predecessors.

Partition: pass 1 = app/errors/envelope/auth/guards/schema/store/clockcal/routes_reference (PRD §2 entire + §3.1). Pass 2 = routes_cycles/calc (§3.2-§3.6 write-side + all nine calculations). Pass 3 = routes_billing/routes_disputes/routes_regulatory/cascade/derive (§3.6 claim endpoints, §3.7-§3.9, and every JSON projection). Pass 4 = reconciliation, whole document.

**Cumulative result: PRD_FINALIZED.md 490 lines / 116,458 chars -> PRD_COMPLETED.md 492 lines / 158,410 chars (+2 lines, +41,952 chars, +36.0%). 69 edits from passes 1-3 plus 10 reconciliation edits from pass 4. 64 diff hunks, zero deletion-only hunks.**

---

### PASS 1 (globals + reference data) — 13 ambiguity-pins, 3 mismatch-revisions, +7,245 chars

- §2.1 P1 — revise — mismatch — "must carry two headers — without exception" contradicted impl, where X-User-ID is required only for two roles; also pinned whitespace-only = absent, role trimmed before matching, user-id compared exactly as sent — auth.py:47-59
- §2.1 P2 — insert — ambiguity — the X-User-ID requirement keys on the *presented* role, not the endpoint's authorized list, and precedes role authorization (Customer w/o id -> 401 even on a BillingAdmin-only endpoint) — auth.py:28,54-63
- §2.1 P4 — insert — ambiguity — consignee/rail-car/tariff records are outside the ownership chain (no owner check); the two consignee-nested lists narrow silently to an empty page, while a cycle's notices and a dispute's exhibits *do* 403 — routes_reference.py:79-86,116-118,131-132, routes_cycles.py:275, routes_disputes.py:357
- §2.2 bullet — insert — ambiguity — api_request_id = `req_` + exactly 20 chars from [A-Z0-9] (24 total) — envelope.py:11,19-20
- §2.2 bullet — insert — ambiguity — api_request_timestamp is the sole value read from the **host** clock, not the logical clock — envelope.py:8,26, clockcal.py:59-60
- §2.3 P1 — insert — ambiguity — pagination parser strictness ("", +5, 5.0, 10abc, abc -> ERR_INVALID_PAGINATION), whitespace trimmed, and an out-of-range offset is an empty page not an error — envelope.py:54-84
- §2.3 P2 — insert — mismatch — notices and exhibits tie-break on an internal creation sequence, **not** id, which matters because the logical clock is explicit — store.py:38-40,68, derive.py:40,47
- §2.3 P2 — insert — ambiguity — list filters are exact-equality string matches, never enum-validated; unknown value -> empty page, total_count 0 — verified in all six route modules
- §2.4 P2 — insert — ambiguity — exact instant grammar (case-insensitive T/Z, mandatory seconds, 1-9 fractional digits, +00:00 rejected) and sub-millisecond truncation on render — clockcal.py:17-19,48-56
- §2.4 P3 — revise — mismatch — "the service does not read the host clock" rescoped to business calculations, naming the envelope exception — clockcal.py:59-60
- §2.4 P3 — insert — ambiguity — the clock is *assigned*, may be wound backwards, no chronology guard — routes_reference.py:39-46
- §2.8 band 2 — revise — mismatch — same role-keyed vs endpoint-keyed correction as §2.1 P2 — auth.py:57-59
- §2.8 band 7 — insert — ambiguity — a non-string body reference is ERR_INVALID_REQUEST, not a 404 — schema.py:179-187
- §2.8 band 8 — insert — ambiguity — five conventions: absent/empty/null body -> {}, unparseable or non-object body -> 400; explicit null field == omitted; undeclared fields ignored; bool never an int/number and float never an int; the three uniqueness collisions are ERR_INVALID_REQUEST 400, not 409 — schema.py:23-36,39-40,76,132,196-199
- §3.1 access-mode — insert — ambiguity — both fields mandatory; not a state machine, any posture from any other including a no-op re-set, each call bumps version — routes_reference.py:246-257
- §3.1 tariff — revise — mismatch — "fifteen further parameters" -> **fourteen** (impl declares 14); plus tariff_code is explicitly non-unique — routes_reference.py:144-171,176-177

NO-NEW-MISMATCH highlights: the header claim was scoped to the presented role after grepping that no route reads the headers directly; the ownership sentence was written as two halves after grepping all 21 require_owner call sites, rather than one sweeping claim; the §2.2 host-clock insert forced a same-pass rescope of §2.4's "does not read the host clock"; list-filter universality was verified across all six route modules before being asserted (and worded as "the value the resource projects in its own JSON" because list_invoices compares a *derived* compound status); the ordering tie-break was scoped to notices and exhibits only after confirming db.ordered() tie-breaks on id everywhere else.

---

### PASS 2 (cycles + calculations) — 6 ambiguity-pins, 10 mismatch-revisions, +8,470 chars, +2 lines

- §3.2 L189 — revise — mismatch — "Two tariff conditions" -> "Three"; added that the pinned rule set's status is re-read *afresh* at constructive placement (a since-superseded tariff blocks an already-ordered cycle), and that no later movement re-checks it — routes_cycles.py:41-50,106,197
- §3.2 L191 — insert — ambiguity — constructive placement mints a charge line but returns the **cycle** at HTTP 200, and does not hand back the new line's id — routes_cycles.py:221
- §3.2 L193 — revise — mismatch — computation_basis was described as "frozen when the line is finalised"; it is in fact rewritten on **every** recomputation: a STORAGE line is born already carrying its facility's basis, a DEMURRAGE/DETENTION line is born null and mirrors clock_basis (returning to null when a refusal drops the election to NONE); the bunching re-rating never touches it — cascade.py:54,62, routes_cycles.py:208
- §3.2 L195 — insert — ambiguity — cycle list narrows a Customer caller to its own cycles (PRD stated this only for charges and left cycles to "likewise") — routes_cycles.py:172-173
- §3.3 L201 — insert — ambiguity — notify returns the new notification at HTTP 201, not the cycle — routes_cycles.py:267
- §3.3 L205 — insert — ambiguity — "most recently moved to ACKNOWLEDGED" pinned to *application order*, explicitly **not** greatest acknowledged_at; a back-dated second acknowledgement moves the field backwards — calc.py:58-65, routes_cycles.py:300
- §3.3 L207 — insert — ambiguity — (a) pick_acknowledgeable full tie on both sent_at and created_at resolves to the last-written notice; (b) **acknowledgement carries no movement_status precondition at all** — it is the one cycle action the §2.8 state band does not gate, so a RELEASED or VOIDED cycle can be acknowledged, re-running the election and rewriting clock_basis/clock_start_at/free_time_expires_at on an already-finalised line without repricing it — calc.py:68-75, routes_cycles.py:283-305
- §3.3 L221 — revise — mismatch — "flips ACTUAL back to CONSTRUCTIVE and moves expiry backwards — the only situation where a derived expiry retreats" was a false universal. Refusal re-runs the whole election: it can drop to NONE with both fields null, and when the effective-notice instant sits on a later UTC date than the placement did the expiry moves *forward* — calc.py:95-128, routes_cycles.py:364-367
- §3.4 L231 — revise — mismatch — three fixes in the refusal cascade: refusal_reason is a non-empty string with no maximum and is not retained; the election "reverts clock_basis to CONSTRUCTIVE" is now "...or all the way to NONE"; and the facility's last_switch_at also re-derives **backwards** (the nulled actual_placement_at leaves the max), so the track's switch buffer is released. Also noted refusal is not gated on access_mode — routes_cycles.py:347-372, derive.py:106-115
- §3.5 L239 — revise — mismatch — the ERR_NOTIFICATION_NOT_SENT guard keys on the facility's kind being INDUSTRY_TRACK, not merely on the ACTUALLY_PLACED source state; a car actually placed at a yard/terminal releases with no notice check — routes_cycles.py:410-414
- §3.5 L243 — revise — mismatch — "a provisional charge is **always** at least one day lighter" is false; the variants agree exactly when the reference date is ineligible or falls on/before the expiry date — calc.py:135-150, cascade.py:64-75
- §3.5 L245 — revise — mismatch — "at most one of chargeable_days and early_release_days can be non-zero for **any** cycle" scoped to demurrage/detention; a storage cycle draws the two from two clocks and both can be positive — calc.py:135-163, cascade.py:101-107
- §3.5 L247 — revise — mismatch — two false boundary claims corrected: a release at 00:30 the day after expiry accrues **zero** days at the default gate_close_hour 16 (that single candidate date *is* the release date), and a release **on** the expiry date yields **both** counts zero, not a positive early_release_days — calc.py:135-170
- §3.5 L249 — revise — mismatch — "notification timing is simply irrelevant at a yard" -> "irrelevant to the storage day count", so it no longer contradicts the yard election below — cascade.py:33-41
- §3.5 L251 — insert — ambiguity — *(new paragraph, the only structural addition in all of Step 9)* both storage modes need released_at, so a storage line's chargeable_days/billable_days/gross_amount_cents stay zero for its whole provisional life; and the §3.3 election **still runs on a yard cycle** (all five events fire it), so its early_release_days is counted from the placement free_time_expires_at while its chargeable_days comes from the storage clock — letting a yard cycle earn average-agreement credit days off a clock that never priced anything — calc.py:177-196, cascade.py:33-41,55,101-107
- §3.7 L305 — revise — mismatch — *(cross-partition, taken because the write path is in routes_cycles.py)* the void enumeration "FINAL, ADJUSTED or PROVISIONAL" is wrong both ways: on a RELEASED cycle the line is FINAL, ADJUSTED or **DISPUTED**, never PROVISIONAL — routes_cycles.py:438-453

Hand-off adjudications: (1) **acknowledgement ordering — genuine silence, patched.** §3.3's "most recently moved to ACKNOWLEDGED" was *readable* as pinning application order but diverges from the equally natural "greatest acknowledged_at" reading whenever an ack instant is back-dated, which the chronology check permits (it only requires ack_at >= sent_at). (2) **facility_last_switch_at — confirmed, no patch needed in §3.4**, which refers to last_switch_at by name and defers to §3.1's (correct) definition. But the *converse* was a real silence: §3.4 never said that nulling actual_placement_at on refusal makes last_switch_at retreat and frees the buffer. Patched at L231.

NO-NEW-MISMATCH highlights: computation_basis wording widened from "set at birth" to "rewritten on every recomputation" after confirming reprice_charge never touches it and nothing calls recompute_charge after release; the refusal-expiry claim was softened to "ordinarily moves backwards" only after constructing a concrete forward-movement case (cp 21:00Z, ap 23:00Z, notice grace pushing the effective instant past midnight); last_switch_at retreat written as "can move backwards ... to another cycle's instant, or to null" because the refused spot need not have been the maximum; the both-positive storage claim was asserted only after constructing a concrete case (storage 2 days + early_release_days 1); the void status list was written after confirming PROVISIONAL is unreachable at void and DISPUTED is reachable.

---

### PASS 3 (billing + disputes + regulatory + cascades + all projections) — 31 ambiguity-pins, 6 mismatch-revisions, +20,127 chars, 0 new lines

§3.6: exempted_cycle_ids intra-date tie-break past created_at is the service's write order, not id (routes_disputes.py:165-166); **mismatch** — re-pricing after exemption is a fresh ladder walk on DEMURRAGE/DETENTION but flat storage_daily_rate_cents on STORAGE, and the cluster set filters on movement status and window only, never facility kind (cascade.py:85-87, routes_disputes.py:102-113); analysis increments only the claim's version, rewritten lines and their cycles stand still (routes_disputes.py:192-198).

§3.1 / §3.3: **mismatch** — last_switch_at is null while *no cycle recorded either instant* (not "no cycles at all"); the sweep ignores movement_status, so a VOIDED cycle's instants still count; a refusal moves it backwards (derive.py:106-115). sequence_number tie-break on a shared created_at is write order; derived per read and stable (derive.py:37-41,272-288).

§3.7: attachment moves invoice_id/billing_status with no version increment on lines or cycles (routes_billing.py:61-72); credit-day entry sort's final effective tie-break is the line's id (cascade.py:219-225, derive.py:55-61); landing agreement credit leaves line status alone (never ADJUSTED) and increments neither the agreement nor the lines (cascade.py:241-250); **two invoices in one agreement month** — the ledger has no memory of credit already granted (same days spendable twice), the cap is per-invoice, and the agreement's agreement_credit_cents is *overwritten* by the latest issue while forfeiture still reverses both (cascade.py:205-251,254-274); an invoice landing non-zero agreement credit derives ADJUSTED immediately at issue (derive.py:143-157); dispute_count counts every dispute ever filed whatever its status and never falls (derive.py:51-52,139); **mismatch** — the universally-stated rollup is overridden for money only, all three totals report 0 while derived status is DRAFT while attached_charge_count/dispute_count report true (derive.py:310-334); forfeiture reversal is per-line and exact, subtracting this agreement's recorded amount, flooring at 0, zeroing each touched invoice's own agreement_credit_cents, leaving statuses (cascade.py:254-274); **mismatch** — closing settles only cycles behind **live** lines, a voided line's cycle keeps its billing_status (routes_billing.py:140-143); closing increments only the invoice's version, not settled cycles nor swept disputes (routes_billing.py:139-149); re-closing a CLOSED invoice is ERR_INVOICE_INVALID_STATE and the gate reads the derived compound status (routes_billing.py:132-137); void moves only the invoice's and the cycle's version — consignee, rail car and rebuilt agreement deliberately not incremented, asymmetric with §3.5 release and §3.8 decide (routes_cycles.py:454-459 + cascade.py:118-152).

§3.8: filing bumps only the invoice and dispute_posture stays CLEAR because DRAFT is not an under-review status (routes_disputes.py:313-315, derive.py:84-93); supersession is a record of intent — predecessor untouched, still counted, still sweepable, both ERR_SUPERSEDE_TARGET_INVALID conditions share one code, no limit on how many name the same predecessor (routes_disputes.py:269-274); the WHOLE_INVOICE ceiling is the *reported* total_gross_cents and filing has no invoice-status gate, so a WHOLE_INVOICE filing on a DRAFT invoice always fails ERR_CLAIM_EXCEEDS_CHARGE while SINGLE_CHARGE can succeed (routes_disputes.py:206-212,276-283); filing an exhibit moves evidence_weight (live sum) without incrementing the dispute (routes_disputes.py:367-378, derive.py:160-161); **mismatch** — "Four conditions" enumerated five, replaced with five plus the §2.8 evaluation order invoice state -> line states -> window -> evidence -> bunching (routes_disputes.py:448-472); under WHOLE_INVOICE the FINAL test resolves over *every live line* (so a second WHOLE_INVOICE submission is impossible while one holds a line DISPUTED) and target_charge_count counts all live lines, while a voided SINGLE_CHARGE target still resolves and fails (routes_disputes.py:400-411,453-457); **mismatch** — submission does **not** freeze evidence_weight, it freezes target_charge_count and reads the weight once for the deadline while the projected field stays live and grows on an exhibit filed during INFO_REQUESTED (derive.py:354-380, routes_disputes.py:474-477); the adjudication base comes from the **first** charge in the resolved target order, so a mixed-tariff invoice takes its earliest-released line's rule set, falling back to 20 (routes_disputes.py:414-423); first_level_adjudicator_id is written only into a null while appeal_adjudicator_id is rewritten on every round-2 entry (routes_disputes.py:502-508); requested_items union type, exact rejection set, no length/count cap, validated then discarded, band-8 precedence (routes_disputes.py:514-537); "after the information request" = the service's write order via an internal marker, not created_at, and only the latest marker counts (routes_disputes.py:551,566-571); allowance_pct is schema-bounded 0..1 **inclusive** so out-of-range is ERR_INVALID_REQUEST and never ERR_ALLOWANCE_PCT_MISMATCH, decision_rationale 1..2000 and retained (routes_disputes.py:619-638, schema.py:127-156); resolved target order's final tie-break is the charge's id (routes_disputes.py:394-397); decide **replaces** credit_applied_cents, absorbing agreement credit, and DENIED writes 0 and returns the line to FINAL (routes_disputes.py:648-650); decide increments only dispute/invoice/consignee, rewritten lines and their cycles unversioned (routes_disputes.py:648-662); appeal — appeal_narrative 1..2000 and discarded, decision_rationale returns to null, the reversed set is the *recorded* decided set so a line voided in between returns to DISPUTED, and the consignee is **not** versioned though decide versions it (routes_disputes.py:672-706).

§3.9: challenge_count increments unconditionally whatever the cited set's status while only PUBLISHED transitions, nothing restricts which rule set may be cited, and filing increments no version on the dispute or the rule set (routes_regulatory.py:99-106); answer_narrative 1..2000, retained and projected (routes_regulatory.py:150-157); ordered_credit_cents is a required integer >= 0, negative => ERR_INVALID_REQUEST, and the two money rules are tested outcome-first (routes_regulatory.py:184,194-199); "still cites" defined exactly — another complaint, status FILED or RAILROAD_ANSWERED, self excluded — only the return to PUBLISHED consults it, both branches require CHALLENGED else no transition and no version move, and BILLING_PRACTICE touches no rule set (routes_regulatory.py:166-216).

Hand-off adjudications: (1) **requested_items** — genuine silence, patched: non-empty string or non-empty list of non-empty strings; absent/null/empty string/empty list/non-string element/any other type => ERR_INVALID_REQUEST 400 at band 8, above the state and limit tests; no length or element cap; validated then discarded. (2) **_info_request_seq** — genuine silence about *how* "after" is measured, patched: internal write order via a marker, not created_at (identical created_at is routine); only the latest marker counts. (3) **DRAFT totals = 0** — the creation sentence pinned it but the rollup paragraph stated the totals universally; patched as a mismatch, money-only, both counts explicitly exempted. (4) **STORAGE inside a bunching cluster** — confirmed genuine mismatch, patched. (5) **Void version asymmetry** — confirmed: void touches only invoice + cycle, the agreement ledger is rebuilt *without* a touch (whereas §3.5 release does touch the agreement), and neither consignee nor rail car is touched; technically consistent with §2.9's silence rule but confusable enough to warrant the explicit clause.

NO-NEW-MISMATCH highlights: every target-set claim was scoped to its operation after enumerating all three _resolved_targets call sites; the DRAFT-zeroing exception was confined to the three money fields with the two counts explicitly exempted so §2.6's invariant stays valid (it holds trivially at 0+0=0); the decide-overwrites and forfeiture-subtracts sentences were made mutually consistent rather than each locally true; the credit-day tie-break was worded as the *effective* (not explicit) final tie-break after verifying the sort is stable over an (created_at, id)-ordered input.

---

### PASS 4 (reconciliation) — 10 edits closing every queued cross-pass contradiction

Passes 1–3 were instructed to *report* contradictions that crossed their partition boundary rather than reach outside it. Seven were queued (Q1–Q7); pass 4 owned the whole file and closed all seven, plus one it found itself.

- **Q1 (§2.9 universal version sentence vs the many unversioned writes)** — the sentence said every mutation increments its subject's version; §3.6 analysis, §3.7 attachment/credit, §3.8 exhibit filing and the rewritten lines of decide all mutate without incrementing. Reconciled by making §2.9's rule explicitly subordinate to §3: a version moves only where §3 says it moves; §3's silence means no increment, and that silence is deliberate throughout.
- **Q2 (§2.8 band 25 vs the storage clock)** — band 25 was written as if it applied to every cycle kind; the storage clock has no notice predicate. Scoped band 25 to non-storage cycles and stated that a storage cycle skips it entirely.
- **Q3 (§3.5 release versions the agreement vs §3.7 void rebuilds it without a touch)** — both are true. Stated both in place, side by side, as an intentional asymmetry rather than leaving each locally plausible.
- **Q4 (§3.3 election on a yard cycle vs §3.5 provisional storage lines)** — the one structural addition of Step 9 (§3.5 L251): storage lines stay zero for their provisional life, and the §3.3 election still runs on a yard cycle. Neither section had to be weakened.
- **Q5 (target_charge_count frozen vs evidence_weight live)** — pass 3 established the freeze applies to the count only. Pass 4 propagated that to §2.6's field table so the invariant list and §3.8's prose agree on which of the two is a snapshot.
- **Q6 (DRAFT invoice totals zeroed vs the §2.6 money invariant)** — confirmed the invariant holds trivially at 0 + 0 = 0 and said so, so a reader does not conclude the zeroing breaks it.
- **Q7 (chronology guard on constructive placement)** — passes 2 and 3 both asserted the guard existed. Re-read from source: `routes_cycles.py:182-226` contains **no** `_chronology` call. The four real call sites are notify:241, acknowledge:296, actual placement:334, release:399+402. Observable behaviour is identical either way (constructive placement is the cycle's first instant, so there is nothing prior to violate), but the PRD prose was rewritten to describe the guard as attaching to the four later instants rather than to all five. **The two subagents' agreement was not evidence; source was.**
- **Found in pass 4 (not queued): §2.3's list-ordering universal vs §3.6's `exempted_cycle_ids`.** §2.3 stated a single ordering rule for all list responses; the exempted-cycle set is ordered by the service's write order, not created_at then id. Carved the exception into §2.3 and cross-referenced it from §3.6.

Error-id consistency check: 58 catalogue entries in §5; all 58 referenced at least once outside §5; zero orphaned entries; zero references to an id not in the catalogue.

Verification output at pass 4 exit: 492 lines / 158,410 chars; 64 diff hunks against PRD_FINALIZED.md, grown from the 57 standing after pass 3; zero deletion-only hunks.

---

## Orchestrator verification of Step 9 (independent, not subagent-reported)

- `workspace/PRD_COMPLETED.md` exists and **differs** from `PRD_FINALIZED.md` — the scan genuinely ran (a byte-identical file would mean it did not).
- `diff` shows **0 deletion-only hunks**: nothing was removed from the contract, only pinned or corrected.
- Heading list is **byte-identical** between PRD_FINALIZED.md and PRD_COMPLETED.md — 26 headings, no section invented, no section dropped. (Note for the record: `grep -c '^#'` reports 26, not 24; §2.2 carries two `####` sub-blocks.)
- Tail terminates at `| \`ERR_NOTIFICATION_NOT_SENT\` | 422 |` — the last row of the §5 error catalogue, a real section boundary, not mid-sentence. No truncation.
- `workspace/implementation/` max mtime 03:25 — untouched by Steps 7, 8 and 9. The contract was documented to match the code; the code was never bent to match a test.
- `test_suite/` + `test_helpers/` max mtime 06:11 — untouched by Steps 8 and 9.
- All 8 `results.{1..8}.json` present from the final sweep, every round 141/141.
- `.scratch/` holds exactly `step2/`, `step4/`, `step7/` — no sibling pipeline's scratch was destroyed by any of this task's subagents.

## Pipeline complete — Step 9 has written workspace/PRD_COMPLETED.md.
