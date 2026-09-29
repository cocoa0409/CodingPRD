# Worklog — task_2922_reinsurance_broker_placement_treaty_marketing

## Step 1: Create task directory — 2026-09-05T17:00:10.260Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2922_reinsurance_broker_placement_treaty_marketing` and its `workspace/` subdirectory. Index 2922 was pre-assigned by the orchestrating prompt; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-05T19:28:00.000Z

Scaffold generation for task 2922 is complete and lint-clean.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2922_reinsurance_broker_placement_treaty_marketing/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3385 | 198,258 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2476 | 165,195 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 7635 | 500,458 |

`SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key leaks into it; each design file has a single top-level key.

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2922_reinsurance_broker_placement_treaty_marketing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2922_reinsurance_broker_placement_treaty_marketing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2922_reinsurance_broker_placement_treaty_marketing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    84
  §1.1 entities declared:     14
  §1.8 instances scanned:     22
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1740

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

- **SCAFFOLD.yaml (§1.0–§1.7):** 14 entities, 11 state machines, 2 concurrency rules, 10 calculations (3 dual-variant), 72 validations across 8 priority bands, 84 endpoints, 69 error ids, 7 roles. Profile: `multi_party_negotiation` / `quota_allocation`, flat topology, parallel state-machine shape, `segregation_of_duties` role model, `immediate` consistency.
- **§1.8 difficulty design:** 9 rules / 22 instances.
- **§1.9 corner design:** 9 sections / 78 instances = 65 full test recipes + 13 `excluded_because` stubs — entities 15, state_machines 20 (15+5 stubs), calculations 11 (6+5), validations 11, endpoints 7, errors 3, rbac 4, cross_cutting_complexity_layers 6 (4+2), consistency_model 1.

## Work completed this session (the three remaining §1.9 sections + audits)

- **rbac (4):** all seven roles' `exclusive_operations` walked end to end in one ~45-call placement; 16 `ERR_UNAUTHORIZED`/auth-band negatives pinning 1→2→3 ordering and 3-before-existence; `shared_operations` + `ERR_FOREIGN_RESOURCE` (4 before 23/25/26, two lead identities, six-role read set); `Segregation of duties` proving the check compares identities not roles (acct-1 refused on its own booking, acct-2 admitted).
- **cross_cutting_complexity_layers (6):** one OCC instance per §1.2.1 rule (`ERR_STALE_LAYER_VERSION`, `ERR_STALE_PROGRAM_VERSION` — including which child writes do and do not bump the parent version, and 412's place in the ladder); `derived_field_reconciliation` across SigningLine→Layer→Program and →Reinsurer for create/update/release; `pagination_with_filtering` (offset-window shift across a mutation, conjunctive filters, empty pages, limit/offset bounds); stubs for `cascading_side_effects` and `dual_variant_calculation` citing existing §1.8 instances.
- **consistency_model (1):** `immediate` — every cascade asserted in the causing response *and* in the immediate re-read, including hops landing off the response's output entity.
- **endpoints (+1):** added `every_declared_read_surface_answers_from_one_fully_walked_placement`, which closed the last endpoint-coverage gap — **all 84 declared endpoints are now exercised** by at least one §1.8/§1.9 call (was 14 uncovered read endpoints).

## Audit findings folded back into SCAFFOLD.yaml

1. **`ERR_SEGREGATION_OF_DUTIES` was unreachable** (approve was ComplianceOfficer-exclusive, booking BrokerAccountant-exclusive ⇒ priority 3 pre-empted priority 42 forever). Fixed via §1.5 ladder rung 1/2: approve now `[ComplianceOfficer, BrokerAccountant]`, §1.7 shared/exclusive lists and `approved_by_user_id` reworded, and the `PENDING→APPROVED` transition's `actor:` widened to match.
2. **Priority-2 identity roster made explicit** (admin-1; lead-1/lead-2; act-1; acct-1/acct-2; compl-1; entity-backed cedent/reinsurer ids) so the duty check compares identities, not roles.
3. **`ERR_VALIDATION` condition contradicted validation 7** ("limit > 200" vs `[1,100]`) — corrected to `limit < 1 / limit > 100`.
4. **No collection ordering was declared**, making pagination unassertable — added `response_envelope.collection_ordering` pinning `created_at ASC` + insertion-sequence tie-break (id never participates), plus the `total_count`/`has_more` semantics.

Coverage checks: all 69 error ids and all 72 validation priorities are cited by at least one design instance (13 errors are §1.8-only, 55 §1.9-only, the rest in both); instance names are unique across both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance; no difficulty directive ("harder than expert level") leaked into any artifact. No sibling task directory was read at any point.

**Orchestrator verification:** all three files present and non-trivial; `grep -i "harder than expert\|expert level"` on SCAFFOLD.yaml returned nothing, confirming the difficulty directive did not leak into the scenario key.

## Step 3: Copy shared files — 2026-09-05T19:29:20.366Z

Copied `./INSTRUCTION.md` to `tasks/task_2922_reinsurance_broker_placement_treaty_marketing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T19:47:00.000Z

PRD complete and verified.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2922_reinsurance_broker_placement_treaty_marketing/workspace/PRD.md`
**Size:** 527 lines / 118,593 bytes (built with 12 incremental appends; no single giant Write).

**Section list**
- `# Reinsurance Treaty Placement API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure; 2.3 Pagination; 2.4 The Logical Clock; 2.5 Common Resource Properties; 2.6 Money, Percentages and Rounding Discipline; 2.7 Optimistic Concurrency on Parent Versions; 2.8 Path Resolution and the Validation Ladder; 2.9 Cascade Discipline and Derived-Field Reconciliation; 2.10 Segregation of Duties over Fiduciary Money (10 subsections, inside the 8–12 band)
- `## 3. Business Logic & Workflows` — 3.1 The Counterparty Registry and the Treaty Placement File; 3.2 Exposure Packaging and Actuarial Sign-Off; 3.3 Program Structure and the Layer Technical Premium; 3.4 Marketing the Layers: Submissions, Quotes and Negotiation Rounds; 3.5 Firm Orders, Signing Lines and Aggregate Market Capacity; 3.6 Signing Down, Compensation Disclosure and Binding the Placement; 3.7 Contract Certainty and the Slip-to-Contract Trail; 3.8 Fiduciary Premium Handling; 3.9 Claims Advocacy, Dispute Resolution and Placement-Year Closure (9 subsections, inside the 5–9 band)
- `## 4. API Endpoint Definitions`
- `## 5. Error Code Catalogue`

**Coverage (verified programmatically against SCAFFOLD.yaml, not estimated)**
- Endpoints: **84/84** present in the §4 table; table has exactly 84 data rows and exactly 4 columns on every row.
- Entities: **14/14** named in prose (Cedent, Reinsurer, Program, ExposureSubmission, Layer, MarketSubmission, Quote, SigningLine, ContractDocument, BrokerageDisclosure, FiduciaryTransaction, ClaimAdvocacy, CessionDispute, RenewalReport).
- State machines: **11/11**, all **83** transitions' from/to states, initial states and terminal states appear in backticks in §1–§3; **0** missing.
- Calculations: **10/10** (layer_technical_premium §3.3, submission_completeness_score §3.2, reinsurer_aggregate_capacity §3.5 both variants, signing_down_allocation §3.6 both variants, brokerage_and_net_remittance §3.6, ceding_commission_settlement §3.6 PROVISIONAL_FLAT + §3.9 FINAL_SLIDING, contract_certainty_window §3.1/§3.7, fiduciary_holding §3.8, claim_cession_waterfall §3.9, renewal_analytics §3.9).
- Validations: **72/72** — every rule's error id appears in the §2.8 priority ladder with its `applies_to` scope; **0** missing.
- Error ids: **69/69** in the §5 table (2 columns, 69 rows) **and 69/69 also stated in §1–§3 prose** at the rule that raises them.
- Roles: **7/7** in backticks.
- Both concurrency rules covered in §2.7 (`expected_layer_version`/`ERR_STALE_LAYER_VERSION`, `expected_program_version`/`ERR_STALE_PROGRAM_VERSION`, both 412).

**Hard Contract reports**
- **Contract 1 (Field-Name Coverage): PASS** — 148/148 required identifiers (131 entity `fields[].name` + 85 input/query identifiers + 14 path params, de-duplicated) appear verbatim in backticks. Initial run showed 7 missing (`claim_advocacy_id`, `disclosure_id`, `dispute_id`, `document_id`, `report_id`, `submission_id`, `transaction_id` — present only inside braced path tokens); fixed by adding a path-parameter glossary paragraph to §2.8. Re-run: 0 missing.
- **Contract 2 (Rule Coverage): PASS** — priority ordering stated as an explicit ladder in §2.8 plus per-endpoint orderings where they matter (firm-order's 8-gate sequence, sign-off status-before-score, `ERR_LAYER_NOT_BOUND` before `ERR_LAYER_STATE_INVALID`, staleness at priority 35 pre-empting safety/temporal/structural/fiscal); both OCC rules; all cross-entity cascades including the 4-hop firm-order chain, the 3-hop release/security-suspension reverts, the 3-hop collection erosion chain and the withdraw cascade; all field defaults and initial values; sibling-branch symmetry (both `CERTAINTY_BREACHED` origins, both `RESOLVED` join branches, both `COLLECTED` origins); all 83 transitions, 10 calculations (all variants) and their side effects.
- **Contract 3 (§3 Path Purity): PASS** — 309 distinct backtick tokens in §3 scanned; 0 start with `/`, 0 are bare HTTP methods, 0 combine method+path.

**Additional checks:** §2.2 is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (48 content lines, verified by diff). No fuzzy words (`approximately`/`roughly`/`etc.`/`TBD`…) and no pseudocode operators anywhere in the file. No leakage of difficulty/corner-design language. Neither design yaml was opened, grepped or referenced; no sibling task directory was read. Scratch files stayed under `/tmp/task_2922_prd/`.

**Truncation check:** `tail -40` ends inside the complete §5 error table at a well-formed final row, not mid-sentence — the document terminates at a real section boundary.

**Orchestrator verification:** independently confirmed `wc -l` = 527 and that `tail -12` ends at a complete error-catalogue table row (`| ERR_PROGRAM_HAS_OPEN_TRANSACTIONS | 409 |`) — a real section boundary, so the known doc-generator truncation failure did NOT occur; no regeneration needed. `grep -i` for "harder than expert", "expert level", "test_recipe", "SCAFFOLD" on PRD.md returned nothing: no difficulty-directive or scaffold leakage.

## Step 5: Generate unit tests — 2026-09-05T21:34:00.000Z

Step 5 complete. The full unit-test artifact set is written at the task root and the audit exits 0.

## Files written

`test_helpers/` — 2,824 lines
| file | lines |
|---|---|
| `__init__.py` | 41 |
| `api_client.py` | 457 |
| `api_errors.py` | 156 |
| `assertions.py` | 376 |
| `constants.py` | 136 |
| `factories.py` | 269 |
| `fixtures.py` | 816 |
| `test_users.py` | 95 |
| `types.py` | 478 |

`test_suite/` — 14,343 lines, `conftest.py` (64) + 22 test modules: test_01 327, test_02 318, test_03 577, test_04 427, test_05 397, test_06 444, test_07 370, test_08 451, test_09 455, test_10 595, test_11 569, test_12 551, test_13 591, test_14 637, test_15 1066, test_16 976, test_17 919, test_18 1272, test_19 483, test_20 1160, test_21 604, test_22 1090.

## Coverage

- **300 tests** total: 66 tagged `Design: Difficulty/...`, 234 tagged `Design: Corner/...`.
- **Queue A: 22/22 difficulty instances with >=2 tests** (per rule: non_linear_state_machine 15, transitive_cascade 9, compensating_invariant 7, boundary_precision_check 6, combinatorial_formula 6, cross_entity_state_dependency 6, priority_pair_validation_conflict 6, resource_temporal_overlap 6, dual_variant_calc 5).
- **Queue B: 65/65 non-stub corner instances with >=1 test** (validations 49, state_machines 45, entities 36, endpoints 24, calculations 17, consistency_model 17, cross_cutting 16, rbac 20, errors 10). All **13** `excluded_because:` stubs resolve to real §1.8 instances and emit zero tests (78 corner names - 13 stubs = 65 live).

## Verification performed

`/tmp/task_2922_tests/audit.py` exits 0: exactly one `Design:` line per test and always the last docstring line, every name/bucket matching the yaml verbatim, no stub tagged, and every `PRD: "..."` citation >=40 chars and a byte-exact whitespace-normalised substring of `workspace/PRD.md`. `python3 -m py_compile` clean on all 31 files; all 22 modules import and expose 300 `test_*` functions. No `pytest.mark.skip`/`xfail`, TODO, FIXME or placeholder anywhere. Fixture hygiene greps clean: no money-as-JSON-string, no date-only value in an instant field, no whitespace-only auth header. The 4 explicit `expected_status=` sites all agree with the PRD §5 map (400/404/409/422); every other assertion lets the registered map decide. `__pycache__` removed. Both dirs are at the **task root** and `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — nothing leaked.

## Probes dropped under the PRD-first filter (no instance skipped)

Every instance is covered; these individual yaml probes were not derivable from the PRD and were replaced or omitted:

1. **Undeclared query filters** (`txn_type`, `status`, `is_lead`, `line_of_business`, `security_status`, plus root-list `program_id`/`reinsurer_id`/`layer_id`) — §4 declares filters only on `/programs`, `/quotes`, `/signing-lines`, `/fiduciary-transactions`, `/cession-disputes`. Replaced by declared FK filters or bare unfiltered calls plus client-side agreement checks.
2. **Collections from `NOTIFIED`/`COLLECTED` returning `ERR_ADVOCACY_STATE_INVALID`** (corner `errors` instances 8 and 9) — §3.9 states no admitting-status set for collections, so neither the priority-30 refusal nor its precedence over `ERR_COLLECTION_EXCEEDS_COLLECTIBLE` is derivable. All other assertions in both instances are kept.
3. **Whitespace-only `X-User-ID` probe** — `requests` raises `InvalidHeader` client-side; translated as the absent-identity and unknown-identity equivalents.
4. **Yaml HTTP statuses contradicting §5** for `ERR_VALIDATION`, `ERR_ALREADY_REVERSED`, `ERR_CEDENT_SUSPENDED`, `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, `ERR_CERTAINTY_NOT_BREACHED` — resolved in the PRD's favour by omitting `expected_status`.
5. **Yaml `financial_rating: "BBB"`** (not in the cedent enum) — replaced with `B_PLUS`.
6. **Yaml capturing `status == REVERSED` from the reverse endpoint** — the PRD returns a new compensating `REMITTANCE_REVERSAL` row (201); the test asserts the compensating row and re-reads the original.
7. **Unspecified items**: error-message wording, the `release_reason` default, the `DISPUTED -> RESOLVED` edge, the sign-down-from-`IN_MARKET` error identity, the withdrawn-program market-submission ladder contradiction, and the "§1.5 declares no DELETE endpoint" bullet (a claim about the spec, not observable behaviour).

## Step 6: Generate implementation — 2026-09-05T21:00:00.000Z

Implementation complete and verified.

## Files written

`workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 (Flask==3.0.3) |
| `app.py` | 62 |
| `db.py` | 82 (14 in-memory dicts, logical clock) |
| `util.py` | 153 |
| `errors.py` | 105 |
| `response.py` | 69 |
| `middleware.py` | 134 |
| `validate.py` | 227 |
| `enums.py` | 108 |
| `calc.py` | 326 |
| `serialize.py` | 266 |
| `services.py` | 796 |
| `routes/__init__.py` | 29 |
| `routes/_common.py` | 57 |
| `routes/counterparties.py` | 210 |
| `routes/programs.py` | 675 |
| `routes/exposures.py` | 156 |
| `routes/layers.py` | 275 |
| `routes/quotes.py` | 293 |
| `routes/lines.py` | 52 |
| `routes/money.py` | 205 |
| `routes/claims.py` | 277 |
| `routes/evidence.py` | 50 |
| **total** | **4618** |

`__pycache__` removed; no data files, no SQLite, no JSON dumps — storage is Python dicts only, all 14 collections empty at boot (asserted programmatically).

## Coverage (verified mechanically, not by eye)

- **Endpoints: 84/84.** Flask `url_map` yields exactly 84 method+path pairs; diffed against the PRD §4 table — `missing: []`, `extra: []`.
- **Errors: 69/69.** Every catalogued id is present in `errors.HTTP_STATUS` with the declared HTTP status (0 mismatches), and every one of the 69 is actually raised at some call site (`catalogued ids never raised: []`).
- **Entities: 14/14** dict-backed collections. **Roles: 7/7** in `middleware`, with the 7 opaque broker/compliance identities.
- **State machines: 11**, including the two parallel program dimensions (placement x documentation), the compound derived layer status, the cyclic quote negotiation with the 3-round cap, and the ClaimAdvocacy fork-join.
- **Calculations: 10** in `calc.py` (Decimal/Fraction, ROUND_HALF_UP, integer minor units, 4-dp percentages, `floor_4dp` only in the sign-down residue).
- **Validations: 72** across the 8 priority bands, path segments resolving left-to-right before body FKs; both OCC rules (`expected_layer_version` -> 412 `ERR_STALE_LAYER_VERSION`, `expected_program_version` -> 412 `ERR_STALE_PROGRAM_VERSION`).

## Smoke tests

Two scripts under `/tmp/task_2922_impl/` (`smoke.py`, `smoke2.py`), each run against a fresh `bash start.sh` process on a random high port; each recorded PID killed individually (no broad pkill), all ports confirmed free afterwards.

- **`smoke.py` -> SMOKE OK** — envelope shape per §2.2, full happy path (registry -> program -> exposure signoff -> layer -> market -> quote -> firm order -> bind -> documents -> fiduciary book/approve/settle/reverse -> claim -> dispute -> collection -> program settle -> renewal report), 15 negative paths, pagination sweep over all 14 list endpoints. All arithmetic assertions exact (e.g. quoted GWP 23,750,000 after the 5% tier discount; brokerage 593,750; net 23,156,250; loss_ratio_pct 1.0526; final commission 8,312,500; rate on line 47.5).
- **`smoke2.py` -> SMOKE2 OK** — the cascade/edge suite: exposure reject -> revise -> re-signoff, layer restructure recompute, `ERR_STALE_LAYER_VERSION` beating an oversized line, PRO_RATA sign-down (60/60 -> 50/50) and LEAD_PROTECTED sign-down (lead keeps 70, follower 60 -> 30), signing-line release reverse-cascade (layer -> PARTIALLY_PLACED, program -> IN_MARKET, capacity freed), security suspension cascade (line -> RELEASED/SECURITY_FAILURE, quote LAPSED), quote decline cascade, negotiation round cap, market-sweep (SENT past deadline -> EXPIRED, QUOTED untouched, future deadline untouched), documentation checkpoint breach -> HELD money keeping its approver -> `AGREED_WORDING` remediation releasing it back to PENDING with `approved_by_user_id` cleared, program withdraw cascade, segregation of duties, insufficient fiduciary balance, and the claim advocacy fork-join through dispute -> route -> resolve -> collection -> COLLECTED with layer erosion and `ERR_AGGREGATE_LIMIT_EXHAUSTED`.

Two implementation fixes came out of this cycle: `validate.percent` now accepts `Decimal` (the `brokerage_pct` default flowed through as a Decimal and was rejected as "not a number"), and `reverse_transaction` tests the "already reversed" reference **before** the state gate, since a reversed original leaves `SETTLED` and would otherwise make `ERR_ALREADY_REVERSED` unreachable (PRD §3.8 requires it). Five apparent failures in the first `smoke2` run were script-expectation bugs confirmed against the PRD, not implementation defects: the sweep expires only `SENT` submissions, `ERR_DOCUMENTATION_NOT_AGREED` is 409 not 422, and only `AGREED_WORDING` is accepted out of `CERTAINTY_BREACHED`.

No files were created or read under `test_suite/`, `test_helpers/`, the `SCAFFOLD_*_DESIGN.yaml` pair, `worklog.md`, or any sibling task directory.

**Orchestrator verification (Steps 5+6):** launched in a single assistant message so the impl generator was physically isolated from `test_suite/` (the directory did not exist at its spawn). Confirmed `test_helpers/` and `test_suite/` sit at the TASK ROOT and did NOT leak into `workspace/` (workspace contains exactly `INSTRUCTION.md`, `PRD.md`, `implementation/`). Independently counted 300 `def test_` functions in `test_suite/`. Reviewed `start.sh`: foreground `exec python3 app.py`, conditional pip install (avoids per-reboot contention across 8 concurrent rounds). Removed all stray `__pycache__` directories before the sweep.

## Step 7: Run tests and iterate — 2026-09-05T22:30:00.000Z

All 8 rounds report `passed == total`. Cleanup done (`_diag_suite/` and every `__pycache__` removed; `worklog.md` untouched).

## Summary — Step 7, task_2922_reinsurance_broker_placement_treaty_marketing

**Iterations run:** 2 full 8-round sweeps (baseline + verification), plus 2 fast subset runs against a scratch symlink test dir for mid-iteration diagnosis.

**Final per-round results** (quoted from `workspace/implementation/results.$i.json`):

| round | passed / total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 300 / 300 | 0 | 0 | 0 |
| 2 | 300 / 300 | 0 | 0 | 0 |
| 3 | 300 / 300 | 0 | 0 | 0 |
| 4 | 300 / 300 | 0 | 0 | 0 |
| 5 | 300 / 300 | 0 | 0 | 0 |
| 6 | 300 / 300 | 0 | 0 | 0 |
| 7 | 300 / 300 | 0 | 0 | 0 |
| 8 | 300 / 300 | 0 | 0 | 0 |

Baseline sweep was 267/300 in **all eight** rounds — union of failures = 33, perfectly deterministic, zero flakiness and zero load-induced reds.

### Tests deleted
None. No test was PRD-silent as a whole; two had a single uncovered assertion removed (below).

### Fixes to `test_helpers/`
- `test_helpers/fixtures.py` — **new `place_lines(ctx, specs, layer_index, response_deadline)`**: issues every market submission and quote for a layer *before* any firm order, then firm-orders each accepted line in spec order (preserving `ctx["market_submissions"]` / `ctx["quotes"]` / `ctx["signing_lines"]` ordering and the `[0]` aliases). Why: `place_line` bundled submission->quote->firm-order, so the 2nd+ call on the same layer sent a market submission against a layer the previous firm order had already carried to `PARTIALLY_PLACED`. PRD §3.4 states verbatim *"The program must be `IN_MARKET` and the layer must be either `OPEN` or `IN_MARKET`, else `ERR_PROGRAM_STATE_INVALID` or `ERR_LAYER_STATE_INVALID` respectively"*, so the implementation's 409 was correct and this was a fixture-ordering bug. **This single root cause accounted for 30 of the 33 failures.**
- same file — `setup_oversubscribed_layer` rewritten onto `place_lines`. `place_line` is retained unchanged for the single-line and one-line-per-layer cases (`setup_firm_ordered_layer`, `setup_bound_program*`, `setup_notified_claim`, `setup_disputed_claim`, test_15, test_17), which were always PRD-legal.

### Fixes to `test_suite/`
- `test_01_signdown_variants_and_ceding_commission.py` — `_twin_oversubscribed_programs()`: its inline per-market loop interleaved `submit_to_market`->`quote_on`->`firm_order`; hoisted both submissions and quotes ahead of both firm orders (same PRD §3.4 reason). Also picks up `setup_oversubscribed_layer` via `_oversubscribed_at_60_and_50`.
- `test_02_layer_premium_tiering_and_brokerage_rounding.py` — `_four_line_xol_program_awaiting_bind()` converted to `place_lines` (4 markets, 35/30/20/15).
- `test_06_signoff_score_signdown_and_aggregate_boundaries.py` — `_layer_written_to()` converted to `place_lines`.
- `test_09_reversal_and_release_conservation.py` — `_oversubscribed_at_ninety_and_twenty()` phased by hand rather than via `place_lines`, because it must read `ctx["layer_after_lead"]` *between* the two firm orders (asserted `PARTIALLY_PLACED` at line 411); imports switched from `place_line` to `send_submission` / `add_quote` / `firm_order`.
- `test_14_certainty_holds_security_cascade_and_line_lockdown.py` — `_fully_placed_by_two_markets()` and `_oversubscribed_by_three_markets()` converted to `place_lines` (the latter keeps its 0->2->1 market order, so `signing_lines[1]` is still Charlie).
- `test_16_creation_constraints_and_validation_precedence.py` — `_lead_protected_layer_with_two_lead_lines()` converted to `place_lines`.
- `test_18_layer_restructure_market_ageing_and_scoped_reads.py` — `_sixty_forty_placement()` converted to `place_lines`; the single-line site at line 656 keeps `place_line`.
- `test_04_firm_order_and_collection_cascades.py::test_a_collection_closing_the_collectible_amount_carries_the_file_to_collected` — expected `collected_minor` corrected from `1_000_000_000` to `1_600_000_000` (assertion mis-translation, made **more** faithful). PRD §3.9 verbatim: *"The file's `collected_minor` is then recomputed as the sum of `amount_minor` over the `CLAIM_COLLECTION` movements linked to the file's signing lines whose status is `PENDING`, `APPROVED` or `SETTLED`."* Echo Re writes the whole layer, so the first file's 600,000,000 collection sits on the *same* signing line; a fiduciary movement carries no advocacy link anywhere in PRD §3.8 (only `signing_line_id`), so shared-line aggregation is the only derivable reading and 1,600,000,000 is what the formula yields.
- `test_04_...::test_the_consumed_reinstatement_appends_a_pending_reinstatement_premium_movement` — removed the assertion `row["signing_line_id"] == ctx["signing_lines"][0]["id"]`, replaced with a `program_id` check. **Collapse category: BRANCH-ASYMMETRIC SIDE EFFECT / attribution silence.** PRD §3.9 says only *"The second hop, only when a reinstatement was consumed, appends a `REINSTATEMENT_PREMIUM` fiduciary movement on the program in status `PENDING` for the reinstatement premium computed above"* — silent on any `signing_line_id` for the system-created row, and silent on which of a multi-market layer's lines would be named. §3.8's "required" rule governs the *booking endpoint*, not the cascade. Two implementations articulable (leave null vs. stamp the sole/lead line), so the assertion goes; amount 58,275,000, status `PENDING` and row cardinality are all retained.
- `test_13_invalid_transitions_and_terminal_lockdown.py::test_declining_a_quote_closes_its_own_market_submission_and_no_other` — removed `declined["decline_reason"] == ...` (was a `KeyError`). **Collapse category: COMPUTED-FIELD / response-visibility silence.** `decline_reason` appears exactly once in PRD.md (§3.4 line 242) and only as *"with an optional `decline_reason`"*, i.e. an input; it is absent from the quote's enumerated response attributes, in deliberate contrast to the counter, where PRD says *"the note is stored as `last_counter_note`"*. The covered assertions (quote `DECLINED`, own submission `DECLINED`, Bravo's quote and submission untouched) are all kept.

### Fixes to `implementation/`
**None.** No file under `workspace/implementation/` was modified. Every one of the 33 baseline failures traced to the test artifact; in particular the layer-status gate in `routes/layers.py` (market submission) and the `recompute_advocacy_collected` shared-line aggregation in `services.py` were both verified PRD-faithful and left intact. No endpoint, field, side effect or seeded data was added; storage remains in-memory dicts only.

**Orchestrator verification:** independently confirmed from the eight `results.$i.json` that the baseline sweep was 267/300 in every round (identical counts -> deterministic, so the reaping/contention failure modes did not occur) and the final sweep is 300/300 in every round with `total` still 300 — i.e. the suite was not shrunk to reach green. Sweep was run from the pre-staged `workspace/sweep.sh` under `setsid nohup`, with a `SWEEP_DONE` sentinel and per-round log files, so neither the early-return relaunch bug nor the interleaved-log bug applied.

**Step 8 gate decision:** Step 8 is NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; there were 0 implementation fixes but substantial `test_suite/`+`test_helpers/` fixes, including two assertion removals that explicitly identify PRD silences (`REINSTATEMENT_PREMIUM` cascade attribution; `decline_reason` response visibility) and one assertion correction that pins the shared-signing-line reading of the `collected_minor` recomputation. Those three are precisely what Step 8 must pin in prose.

## Step 8: Finalize PRD — 2026-09-05T22:15:00.000Z

PRD_FINALIZED.md written. Three edits, all traced to Step 7 items.

## Line counts
- PRD.md: 527 lines / 118,593 bytes
- PRD_FINALIZED.md: 527 lines / 119,701 bytes (line-count delta 0.0%; byte delta +0.93%)
- Ends at the same real boundary: last line is `| ERR_PROGRAM_HAS_OPEN_TRANSACTIONS | 409 |`. Not truncated.

## Changes
- **§3.9 Collections** — revise — the `collected_minor` recompute set is now pinned as *every* signing line sitting on the file's layer whatever that line's status, matched by `signing_line_id` alone rather than by advocacy file (so two files on one layer see each other's collections, and a `CLAIM_COLLECTION` booked directly on the ledger against a line of that layer counts), with only the file being collected against recomputed at that point — `implementation/services.py:319-334` (`recompute_advocacy_collected`), gate at `implementation/routes/claims.py:265`, sole callsite `routes/claims.py:273`.
- **§3.9 second hop of the COLLECTED cascade** — insert — the system-created `REINSTATEMENT_PREMIUM` row carries a null `signing_line_id` and stamps `created_by_user_id` with the accountant whose collection closed the file — `implementation/services.py:742-746` via `new_transaction` default at `services.py:709-726`, actor from `routes/claims.py:275`.
- **§3.4 Declining** — insert — `decline_reason` is purely inbound: not kept on the quote and absent from every quote response — `implementation/routes/quotes.py:232-247` (validated, never assigned) and `implementation/serialize.py:136-155` (no such key).

## Per-edit pre-edit search log
1. **Edit 1** — (a) Subject: `collected_minor` and its aggregation/threshold semantics. (b) Enumerated & read: `services.recompute_advocacy_collected` (only definition; `lines_of_layer` at `services.py:147-148` confirmed status-agnostic, so RELEASED lines' collections count); every callsite of the recompute (`grep` across impl -> only `routes/claims.py:273`); the collectible gate `routes/claims.py:265`; the COLLECTED threshold `routes/claims.py:274` -> `services.collected_cascade`; initialisation `routes/layers.py:255`; exposure `serialize.claim_advocacy` (`serialize.py:228`); the other, unrelated recompute `recompute_advocacy_figures` (`services.py:300-316`); the parallel `CLAIM_COLLECTION` booking path `routes/programs.py:544` (`LINK_REQUIRED`), which can create a linked collection outside the collections endpoint. (c) Adjustment: two. First, I phrased the set by movement linkage rather than "collections booked against files of that layer", because the ledger-booking endpoint can also create a linked `CLAIM_COLLECTION` that the impl counts. Second, I explicitly *narrowed the refresh claim* — since no code recomputes a sibling file's `collected_minor`, I added "Only the file the collection was booked against has its figure recomputed at this point", to avoid asserting a cross-file refresh cascade the impl does not perform.
2. **Edit 2** — (a) Subject: attribution fields of the cascade-created `REINSTATEMENT_PREMIUM` movement. (b) Enumerated & read: `grep REINSTATEMENT_PREMIUM` across impl -> `services.py:742-746` (only cascade creator), `services.new_transaction` (`signing_line_id=None`, `approved_by_user_id`/`hold_reason`/`reverses_transaction_id` null defaults), `routes/programs.py:544` `LINK_REQUIRED` (booking endpoint still requires the link — untouched by my wording), `routes/money.py:154` (settlement documentation gate on this type), `services.py:275-281` (cedent `outstanding_reinstatement_premium_minor`), `services.py:686` (certainty-breach hold set), `calc.reinstatement_premium_minor`, sole cascade caller `routes/claims.py:275`. (c) Adjustment: scoped the sentence to "That row is created by the system rather than booked" and restated that §3.8's link rule still governs the booking endpoint, so the null-link statement cannot be read as relaxing `ERR_TRANSACTION_TYPE_LINK_INVALID`. I deliberately did not touch the "only when a reinstatement was consumed" clause, leaving the impl's `premium > 0` short-circuit under-determined rather than asserting a cardinality rule.
3. **Edit 3** — (a) Subject: `decline_reason`. (b) Enumerated & read: `grep -rn decline_reason implementation/` -> single hit `routes/quotes.py:233`; the whole decline handler `routes/quotes.py:225-247` (no assignment to the quote row, no submission field); `serialize.quote` (`serialize.py:136-155`, no key); `validate.Shape.string`/`_raw` (`validate.py:48-77`) to confirm the field is still shape-checked when supplied; the contrasting counter path storing `last_counter_note`. (c) Adjustment: wrote "purely inbound ... not kept on the quote and never appears among the quote's attributes" rather than "ignored", so the sentence does not deny the shape validation the impl still performs; I did not import the impl's 1-500 character bound, as no Step 7 item exercised it.

## Step 7 items judged pure fixture bugs — no PRD edit
- All eight `place_lines` / phased-ordering conversions: the diff itself attributes them to `place_line` bundling submission->quote->firm-order, which sent a market submission against a layer already carried to `PARTIALLY_PLACED`. PRD §3.4 already states the rule verbatim, and `implementation/routes/layers.py:124-125` gates on exactly `("OPEN", "IN_MARKET")`. PRD determines the behaviour uniquely, so prose stays verbatim.
- The `test_04` `collected_minor` value correction (1,000,000,000 -> 1,600,000,000) is *not* a pure fixture bug — it exposed the shared-signing-line aggregation, which is Edit 1. No implementation file was modified by Step 7, so no impl-side mismatch needed reconciling.

**Orchestrator verification:** confirmed `PRD_FINALIZED.md` exists (119,701 bytes vs PRD.md's 118,593) and is NOT byte-identical to `PRD.md` — `diff` reports 6 changed lines, consistent with 3 in-paragraph edits. PRD.md was left intact.

## Step 9: Complete PRD — 2026-09-05T23:10:00.000Z

**Orchestrator decision (recorded per the AUTONOMY directive):** Step 9 was run as **three sequential, module-partitioned passes** over one shared `PRD_COMPLETED.md` rather than a single subagent. Rationale: `implementation/` is 4,618 lines across 24 modules; a single pass cannot walk it exhaustively without exhausting context, and the known failure signature of that is a `PRD_COMPLETED.md` byte-identical to its source (i.e. the scan silently never ran). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and required to prove earlier passes survived via verification greps before exiting. Partition: pass 1 = foundations/envelope/validation/registry (`app, db, util, errors, response, middleware, validate, enums, serialize, routes/_common, counterparties, exposures, evidence`); pass 2 = structure & marketing (`calc, routes/programs, layers, quotes, lines`); pass 3 = money, claims & the cascade engine (`services.py` in full, `routes/money, claims`).

### Aggregate result

- Source `PRD_FINALIZED.md`: 527 lines / 119,701 chars -> `PRD_COMPLETED.md`: **533 lines / 147,913 chars** (+6 lines, +28,212 chars, +23.6%).
- **99 edits total: 89 ambiguity-pins, 10 mismatch-revisions.**
- Ends at the real terminal boundary (`| ERR_PROGRAM_HAS_OPEN_TRANSACTIONS | 409 |`); §4 still has all 84 endpoint rows; §-heading count unchanged at 24 (no new sections).

### Pass 1 — foundations, envelope, validation, registry (27 edits: 25 pins, 2 mismatches)

Modules audited: `app.py, db.py, util.py, errors.py, response.py, middleware.py, validate.py, enums.py, serialize.py, routes/_common.py, routes/__init__.py, routes/counterparties.py, routes/exposures.py, routes/evidence.py`. After pass 1: 533 lines / 127,898 chars.

- §2.1 — revise — **mismatch** — PRD implied each opaque identity is bound to one role; impl checks membership of a single seven-identity pool, so any opaque identity resolves under any of the five opaque roles — `middleware.py:45,90`
- §2.1 — insert — headers never trimmed; an unrecognised role still resolves identity against the union of all three pools first (-> `ERR_UNKNOWN_USER`), reaching `ERR_UNAUTHORIZED` only if the identity resolves — `middleware.py:99`
- §2.2 — insert — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `response.py:13,23`
- §2.2 — insert — `api_request_timestamp` reads the logical clock, not wall clock — `response.py:40`
- §2.2 — insert — single-resource `meta` carries only the two request fields; pagination members absent, not null — `response.py:44`
- §2.3 — insert — empty parameter value (`?limit=`) counts as omitted; `offset` past the end yields empty `data` with `has_more` false — `validate.py:180`, `response.py:48`
- §2.3 — insert — filters are exact-equality and NOT vocabulary-checked (unknown value matches nothing, `total_count` 0); boolean filters accept `true/false/1/0` case-insensitively else `ERR_VALIDATION`; filters conjunctive; pagination validated before any path id resolves — `routes/_common.py:40,46`, `validate.py:211`, `routes/counterparties.py:102`
- §2.4 — insert — clock may move backwards; the call answers 200 with `data.current_utc` echoing the instant — `routes/counterparties.py:22`
- §2.5 — insert — serialisation is complete and explicit: all declared fields always present, unset -> JSON `null` (never omitted), nothing extra (`_seq` internal), arrays never null — `serialize.py:1-266`, `db.py:73`
- §2.6 — insert — money/percentages are JSON numbers not strings; 4dp/2dp is arithmetic not display precision (`2.5000`->`2.5`, `82.00`->`82.0`) — `response.py:26`, `util.py:78`
- §2.8 — insert — body must be a JSON object (absent/empty body = `{}`); strict JSON typing for money/percent/boolean/id; undeclared members **ignored**; explicit `null` is equivalent to omission including in patch bodies — `validate.py:24,48,63,102,124`
- §2.8 — insert — the two evidence path segments report `ERR_CONTRACT_DOCUMENT_NOT_FOUND` / `ERR_RENEWAL_REPORT_NOT_FOUND`, both 404 — `routes/evidence.py:29,48`
- §3.1 — insert — market name uniqueness is case-insensitive; the two registers are independent — `routes/counterparties.py:35,128`
- §3.1 — insert — `suspension_reason` required 1-500 chars even when setting `ACTIVE`, stored verbatim (never nulled); a no-op status set still bumps `version`; market `reason` is required but not persisted — `routes/counterparties.py:88,171`
- §3.2 — insert — `decision` closed to `SIGNED_OFF`/`REJECTED`; `review_note` write is unconditional so omitting it stores null over any prior note — `routes/exposures.py:65,89`
- §3.2 — insert — the `SUBMISSION_READY` bubble-up fires only if the program is still `DRAFT`; otherwise sign-off succeeds leaving placement status and program `version` untouched — `routes/exposures.py:103`
- §3.2 — insert — revision: null is equivalent to omitted, empty body legal (rescore only), flags<=records re-tested on **merged** values as `ERR_VALIDATION` and only after the status gate, ownership check precedes the package's existence check, program status untouched — `routes/exposures.py:113,137`
- §4 — insert — trailing slash equivalent; transition POSTs answer 200 — `app.py:20`
- §4 (8 rows) — insert — declared the real query filters for `GET /cedents`, `/cedents/{id}/programs`, `/reinsurers`, `/reinsurers/{id}/signing-lines`, `/market-submissions`, `/exposure-submissions`, `/contract-documents`, `/renewal-reports`
- §5 — revise — **mismatch** — PRD claimed every error carries a catalogued id; impl also emits `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405 and `ERR_INTERNAL` 500 in the same envelope — `app.py:28,33,47`
- §5 — insert — added the two missing 404 rows for the evidence readers — `routes/evidence.py:29,48`

### Pass 2 — structure & marketing (43 edits: 39 pins, 4 mismatches)

Modules audited: `calc.py, routes/programs.py, routes/layers.py, routes/quotes.py, routes/lines.py`. After pass 2: 533 lines / 136,821 chars. Verified pass 1 survived (`grep -c "api_request_id"` = 5; 27 pass-1 hunks still present).

Mismatch-revisions:
- §3.4 — revise — requote's overwrite list was missing `is_lead`; requote does reassign the lead flag from the payload (default `false`), so a lead that omits it silently stops leading — `routes/quotes.py:218`
- §3.6 — revise — sign-down residue ordering named four keys where impl sorts on five; added insertion sequence as final tiebreak — `calc.py:133-142`
- §3.6 — revise — bind's blocking-layer list omitted `OPEN`; impl skips only `LAPSED` and demands `FULLY_PLACED`/`SIGNED_DOWN`, so `OPEN` blocks too — `routes/programs.py:183`
- §3.7 — revise — the ladder implied the placement-state gate precedes the documentation-sequence gate; impl tests the sequence first — `routes/programs.py:452-461`

Ambiguity-pins: withdraw `reason` 1-500 (`programs.py:213`); merged-figure re-check runs after layer-status and program-state gates (`layers.py:102-106`); layer create/restructure never bumps program `version` (`programs.py:406-408`); go-to-market gate order `SUBMISSION_READY` -> cedent suspension -> open-layer/documentation (`programs.py:152-167`); subsequent submissions leave layer status *and* `version` untouched, neither path touches program `version` (`layers.py:152-155`); quoting bumps the submission's `version` only (`quotes.py:140-141`); `counter_note` 1-500 (`quotes.py:172`); quote-expiry check precedes the round-cap check (`quotes.py:175-182`); requote ignores the current `expires_at` and the program's placement state (`quotes.py:201-210`); `decline_reason` optional 1-500 (`quotes.py:232-234`); market sweep leaves layer/program `version` alone and answers 200 with the program (`programs.py:230-255`); `accepted_line_pct` range, `expected_layer_version` integer >= 0, 201 with the line, layer status ungated (`quotes.py:258-293`); `effective_line_pct` stored never null, each line carries its own `committed_capacity_minor` (`services.py:226-227,408-412`); first-hop line field initialisation (`services.py:403-415`); `signed_line_total_pct` definition, both totals rounded half up to 4dp *after* summation (`services.py:182-198`); layer `version` bumps on every firm order even with no status change (`services.py:422-424`); an empty non-`LAPSED` layer set does not promote the program (`services.py:371-385`); releasing a line on a `BOUND` layer is `ERR_LAYER_STATE_INVALID`, gate order line -> layer -> program, 200 with the line (`lines.py:38-52`); release writes only `status` and `release_reason`, capacity returns by live-set exclusion not by zeroing (`services.py:431-436`); sign-down's layer-status gate and its position ahead of the program and oversubscription gates (`layers.py:180-188`); `LEAD_PROTECTED` lead share, two degenerate cases, the two-leads failure, and that `PRO_RATA` ignores leads entirely (`calc.py:99-118`, `layers.py:190-200`); zeroed-line fields, written total recomputed, signed total set to the literal `100.0000`, program `version` untouched, 200 with the layer (`services.py:566-592`); disclosure `brokerage_pct` spans 0-100 (`programs.py:503`); drafting is ungated, repeatable, leaves program `version` untouched (`programs.py:499-524`); bind gate order (`programs.py:175-185`); bind sets line status/`effective_line_pct`/capacity and recomputes totals (`services.py:605-634`); `ceded_claim_minor` frozen at notification (`layers.py:246-256`); plus §4 filter sets for the 15 rows whose handlers live in this partition.

Forwarded notes resolved: `LIVE_LINE_STATUSES` was already pinned (§3.5 names `PROVISIONAL`/`SIGNED`/`BOUND` live, `RELEASED` excluded) — pass 2 additionally pinned that the same live set drives `signed_line_total_pct`, which was genuinely silent. `SIGNOFF_MIN_SCORE = 70.00` was already pinned in §3.2 (>= 70.00, exactly 70.00 passes, status gate before score gate) — no change.

### Pass 3 — fiduciary money, claims, cascade engine (29 edits: 25 pins, 4 mismatches)

Modules audited exhaustively: `services.py` (all 796 lines), `routes/money.py` (205), `routes/claims.py` (277). After pass 3: 533 lines / 147,913 chars. Verified earlier passes survived (`grep -c "api_request_id"` = 5; `grep -c "insertion sequence"` = 3; §4 still 84 rows; 24 §-headings).

Mismatch-revisions:
- §2.8 — revise — `ERR_ALREADY_REVERSED` is hoisted above the own-state tier on the reverse endpoint; the ladder as written made it unreachable — `routes/money.py:176-186`
- §3.6 — revise — release accepts `DRAFT` **or** `REJECTED` (PRD said `DRAFT` only, contradicting its own later "REJECTED is not terminal"); plus gate order, the null-clearing, and that the program is not written — `routes/money.py:51-66`
- §3.6 — revise — `REJECT` **sets** `disclosure_acknowledged` to false rather than "leaving" it false, so it can take a previously-acknowledged program back down — `routes/money.py:97`
- §3.8 — revise — reversal: already-reversed test precedes the state gate; the original keeps `value_date`, `approved_by_user_id`, amount and link with `reverses_transaction_id` null; the compensating row's `created_by_user_id` is the reversing officer with `approved_by_user_id`/`hold_reason` null — `routes/money.py:176-203`

Ambiguity-pins: §2.9 the four *aggregate-only* refreshes write the row only when a stored figure actually moves while status-writing cascades write unconditionally (`services.py:229,278,295,332,343`, `routes/claims.py:237`); §3.1 an already-`LAPSED` layer is not rewritten by the withdraw cascade (no `version` bump) yet still counts for every later hop, released lines keep all capacity fields (`services.py:510-529`); §3.5 the security cascade's layer revert is **unconditional** and deliberately does not re-derive from the recomputed total, so an `OVERSUBSCRIBED` layer still >= 100.0000 lands `PARTIALLY_PLACED` while `SIGNED_DOWN`/other statuses are preserved yet still written (`services.py:486-493`); §3.6 `decision` enum error, `decision_note` 1-500 optional, written unconditionally (`routes/money.py:80-91`); §3.7 the `AGREED_WORDING` release preserves every field but the three named, is indiscriminate as to `txn_type`, and returns held reinstatement premium to the cedent aggregate (`services.py:696-706`); §3.7 the breach writes nothing else on a held movement and does not move `fiduciary_holding_minor`, but does drop held `REINSTATEMENT_PREMIUM` out of the cedent's outstanding aggregate (`services.py:681-693`); §3.8 approval status gate precedes the segregation check, only the movement is written and the cedent aggregate never actually changes (`routes/money.py:131-142`); §3.8 settlement gate order status -> documentation -> balance, the balance compared is the *stored* pre-settlement figure, program `version` always increments (`routes/money.py:150-167`); §3.8 reversal tests neither program state dimension so a closed `SETTLED` year's balance can still move (`routes/money.py:172-190`); §3.9 dispute raise requires the line's `reinsurer_id` to equal the caller's `X-User-ID` (`ERR_FOREIGN_RESOURCE`, pri. 4), file must be `UNDER_REVIEW` or `DISPUTED`, gate order status -> layer -> cap (`routes/claims.py:119-147`); §3.9 a raise writes only the file (`routes/claims.py:161-164`); §3.9 the fork is admitted only from `DISPUTED` and is one-shot/irrevocable in both directions, writing only the file (`routes/claims.py:97-109`); §3.9 resolve inputs `resolution` enum, required non-negative `settled_minor`, `resolution_note` 1-500 (`routes/claims.py:204-207`); §3.9 being on a branch is a *precondition* of the join, so a file whose disputes all resolve while still `DISPUTED` stays `DISPUTED`, and the layer is written only on the joining hop (`routes/claims.py:232-239`); §3.9 collections' five admitting statuses, `ADVOCACY_ARBITRATION` passing the status gate and being rejected later so `ERR_LINE_LAYER_MISMATCH` outranks the arbitration freeze, four-gate order, the movement's null field defaults, no `expected_program_version` and no program write (`routes/claims.py:256-277`); §3.9 the reinstatement-premium hop fires only when the computed premium is strictly greater than zero (`services.py:743-746`); §3.9 the collected cascade writes the layer once and the file once (`services.py:748-749`); §3.9 program settle gate order and the open-movement scan spanning the whole ledger regardless of `txn_type` (`routes/programs.py:195-203`); §3.9 `loss_ratio_pct` is `0.0000` on a zero `quoted_gross_premium_minor`, non-`BOUND` layers skipped and unwritten (`calc.py:206-208`, `services.py:661-666`); §3.9 a non-`QUOTA_SHARE` bound layer keeps both commission fields null but still has incurred, loss ratio and `version` written, and nothing else on the program is rewritten by the close (`services.py:667-678`); plus §4 filter sets for `GET /fiduciary-transactions`, `/claim-advocacies/{id}/cession-disputes`, `/cession-disputes`, `/brokerage-disclosures`, `/claim-advocacies`.

Forwarded notes resolved: (1) the zero-premium `loss_ratio_pct` is now pinned in §3.9's settle paragraph as exactly `0.0000` rather than an arithmetic error; (2) all four undeclared §4 filter rows now declare their real filter sets, and pass 3 found and fixed a **fifth** undeclared row in its partition (`GET /claim-advocacies/{claim_advocacy_id}/cession-disputes`) — every `GET` collection row in §4 now carries a filter clause.

Cross-pass consistency: pass 3's §2.9 "aggregate-only" exception was written to explicitly carve out pass 2's pin that the layer is written on **every** firm order, so the two do not conflict; and pass 3's §2.8 ladder-exception clause is the counterpart to its §3.8 reversal revision, so ladder and workflow prose agree.

**Orchestrator verification:** `PRD_COMPLETED.md` is 533 lines / 147,913 chars and is **NOT** byte-identical to `PRD_FINALIZED.md` (`diff` reports 80 hunks), so the completeness scan genuinely ran in all three passes. The file ends at the real terminal boundary. `grep -i` for "harder than expert", "expert level" and "test_recipe" across `PRD.md`, `PRD_FINALIZED.md` and `PRD_COMPLETED.md` returns nothing — no difficulty-directive or design-index leakage into any PRD. The eight `results.$i.json` from the final Step 7 sweep are retained in `workspace/implementation/`, all reading 300/300 with 0 failures. Sweep scaffolding (`sweep.sh`, `sweep.log`, `sweep.round*.log`, `SWEEP_DONE`) and all `__pycache__` directories were removed; no worklog strays were written outside the task root.

## Pipeline complete — 2026-09-05T23:10:00.000Z

All nine steps finished. Final deliverable tree matches the skill's Output contract: three scaffold YAMLs, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (conftest + 22 modules, 300 tests), and `workspace/` holding `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` (24 files + `start.sh` + `requirements.txt` + the 8 passing results files).

## Step 9 (addendum): Pass 4 — cross-pass reconciliation of false universals — 2026-09-05T23:35:00.000Z

**Orchestrator decision:** after the three partitioned passes completed, a fourth narrow **reconciliation** pass was run. Rationale: module partitioning is what stops the passes clobbering each other, but §1/§2's global-specification prose is written by pass 1 and constrained by every later pass's findings — and nobody owns it after pass 1 exits. The known failure mode is that a later pass *notices* a false §2 universal, pins the correct local truth in its own §3 paragraph, and leaves the §2 falsehood standing because the sentence is outside its module scope. Step 9's mandate is zero residual mismatch, so shipping a known-false universal claim would fail the step even with all three passes "succeeding". Pass 4 was scoped to exactly two things: grep §1/§2 for universal quantifiers and check each against the tree, and fix only the false ones. No fresh implementation audit, no new §3 silence hunting.

Final size: **533 lines / 149,885 chars** (+1,972 chars over pass 3). Eight targeted Edit calls; no `cp`, no wholesale write. All integrity checks held: `grep -c "api_request_id"` = 5, `grep -c "insertion sequence"` = 3, §4 table still exactly 84 data rows, 24 numbered headings, terminal boundary intact.

### Verdict on the flagged §2.9 interaction
**Already consistent — no fix needed.** §2.9's aggregate-only carve-out and §3.5's "on **every** firm order" pin agree: the four aggregate-only refreshes are genuinely conditional (`services.py:229-233` market capacity pair, `services.py:278-282` cedent aggregates, `routes/money.py:166-167`/`201-202` program balance, `routes/claims.py:237-238` layer incurred on dispute resolution), while all five status-writing sites are unconditional `db.touch(layer)` (`services.py:422-424` firm order, `586-589` sign-down, `627-634` binding, `664-675` accounting close, `748-749` collection close). The two sentences describe the same behaviour from opposite ends.

### Universals found FALSE and fixed (8)
- **§1** — "the person who books a movement must never be the person who **releases** it" -> "…who **approves** it" — `routes/money.py:148`: `settle_transaction` requires only `BROKER_ACCOUNTANT` and performs no comparison against `created_by_user_id`, so the booker may settle their own movement; the identity comparison lives only in `approve_transaction`. (A genuine PRD/impl mismatch naming the wrong operation for the segregation rule.)
- **§2.1** — `ReinsurerUnderwriter` "never sees another market's quotes or lines" -> can never *act* on another market's resources but does see them; ownership is enforced on writes only and no read endpoint is narrowed to the caller's market — `routes/quotes.py:33,60` (`list_quotes`/`read_quote` require `REINSURER_READ` with no `own_reinsurer` filter), same for `routes/lines.py` and the market-submission reads.
- **§2.1** — `ComplianceOfficer` "can never **originate** a transaction" -> "can never **book** a movement onto the ledger", naming the compensating reversal row as the one ledger row carrying its identity as creator — `routes/money.py:190-197`; reconciles §2.1 with §3.8's pin.
- **§2.8** — the ladder's implied universal that checks are always evaluated in ascending priority -> the tiers fix the **default** order, several operations pin their own gate order in §3, and the §3 statement governs; five named inline — `routes/programs.py:453` before `:458` (doc-sequence 22 before placement 21), `routes/programs.py:156` before `:159/:162` (cedent suspension 39 before both `ERR_PROGRAM_STATE_INVALID` conditions), `routes/programs.py:177` before `:180` (disclosure 41 before layer status 24), `routes/lines.py` release (line status 27 before layer status 24), `routes/money.py:179-186` (`ERR_ALREADY_REVERSED` above own-state).
- **§2.9** — "Suspending a market runs it in reverse across **every** program that market participates in" -> "across the programs that market participates in, reaching only the layers that actually lose a line and only the programs that own them" — `services.py:468-505`: the cascade visits only lines in `PROVISIONAL`/`SIGNED` on non-`BOUND` layers, so a program all of whose layers are `BOUND` is never visited.
- **§2.9** — "a compound status is **always** re-derived, never assumed … totals recomputed first and the status follows" -> scoped to layers that stay in the placement, with two departures named — `services.py:508-544` (`withdraw_program_cascade` releases lines and forces layers to `LAPSED` with **no** `recompute_layer_totals` call anywhere in the function, so totals go stale) and `services.py:486-494` (the security cascade recomputes totals but forces `FULLY_PLACED`/`OVERSUBSCRIBED` to `PARTIALLY_PLACED` without consulting them).
- **§3.5** (knock-on) — "the one place where the re-derivation rule of §2.9 is deliberately not applied" -> "the one place where a layer's recomputed totals are written without its status being re-derived from them", which stays true now that withdrawal is also named as a departure (withdrawal writes no totals at all).
- **§3.8** (knock-on) — the reversal hoist described as "the only one in this system" -> "the only place where a structural constraint outranks an entity's own state", true given the document-filing inversion is within the own-state tier (22 above 21).

### Universals checked and found TRUE (recorded so the file distinguishes verified-true from never-looked-at)
§2.1 — 7 role spellings; single 7-identity opaque pool accepted for any of the 5 opaque roles; unrecognised role falls to the union-of-pools branch then `ERR_UNAUTHORIZED` (`middleware.py:79-109`); ownership guards exactly seven writes; `BrokerActuary` the only broker-side role excluded from `LEDGER_READ`; §2.10's "may always approve" holds because no `PENDING` row can carry a compliance officer as `created_by_user_id` (the compensating row is born `SETTLED`). §2.2 — `_meta()` is exactly the two request fields, clock-sourced; list `meta` adds exactly the four pagination members; errors carry exactly `error_id` + `message`. §2.3 — `db.ordered` sorts `(created_at, _seq)`; filters not vocabulary-checked (`validate.query_enum` exists but no route calls it); `query_bool` the single boolean exception; pagination-before-path-resolution verified at all 14 nested list endpoints. §2.4 — `CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"` and a tree-wide grep for `datetime.now|utcnow|time.time|date.today` returns nothing, so "never the host's wall clock" is literally true. §2.5 — `_common(row, versioned=False)` used by exactly two serialisers, confirming "twelve of the fourteen"; every declared field always emitted; arrays never null; `_seq` never serialised; "`version` increments on every mutation" survives because aggregate-only recomputations assign nothing when unchanged. §2.6 — every money field ends `_minor` and every money value is a Python `int`; `round_half_up`/`pct4`/`score2` exact (Fraction/Decimal, no binary float); `floor_4dp` has exactly one call site (`calc.py:124`, sign-down allocation), confirming "used only in signing-down allocation"; `percent(places=4)` rejects a fifth decimal. §2.7 — exactly two `expected_*_version` sites (`routes/quotes.py:260`, `routes/programs.py:553`), confirming "no other endpoint accepts a version field". §2.8 — body coercion of absent/`null`/non-object; unknown members ignored (`Shape.reject_unknown` is a `pass`); money must be a JSON integer; booleans reject `"true"`/`1`; explicit `null` equals omission; path segments before body FKs. §2.9 rules one and two; §2.10's four distinct acts.

### Judged out of scope by pass 4
- §2.8's causal clause on claim notification states its causation backwards, but its factual universals are true against `notify_claim` (which checks only `ERR_LAYER_NOT_BOUND`) — prose repair, not a false-universal fix.
- §2.1's "reached directly on a program" over-describes a cedent-ownership resolution path that no endpoint exercises; nothing testable to falsify.
- §2.9 rule one's "every derived field … brought up to date" survives on its "named in the cascade" qualifier; §3.9 already pins that sibling advocacy files are left as they stand.

**Orchestrator final verification:** `PRD_COMPLETED.md` = 533 lines / 149,885 chars, differs from `PRD_FINALIZED.md` by 85 hunks (not byte-identical, so the scan demonstrably ran), ends at `| ERR_PROGRAM_HAS_OPEN_TRANSACTIONS | 409 |`, §4 retains exactly 84 endpoint rows, and no `__pycache__` remains anywhere under the task. Step 9 total across four passes: **107 edits** (89 ambiguity-pins + 10 mismatch-revisions from passes 1-3, plus 8 false-universal fixes in pass 4).
