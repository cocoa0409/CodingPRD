# Worklog — task_2967_label_distribution_deal_recoupment_accounting

Scenario: 2967. Label Distribution Deal & Recoupment Accounting (independent record label)

## Step 1: Create task directory — 2026-09-05T23:14:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2967_label_distribution_deal_recoupment_accounting` and `.../workspace`. Index 2967 is pre-assigned by the orchestrating command; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocated indices).

## Step 2: Generate Scaffold — 2026-09-06T01:40:00.000Z

All three scaffold artifacts are complete and the linter is clean.

## Deliverables
- `/home/ubuntu/github/CodingPRD/tasks/task_2967_label_distribution_deal_recoupment_accounting/SCAFFOLD.yaml` — 3144 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2531 lines, single key `scaffold_difficulty_design`
- `.../SCAFFOLD_CORNER_DESIGN.yaml` — 7011 lines, single key `scaffold_corner_design`

`workspace/`, `worklog.md` and the sibling `.scratch/step*/` dirs are untouched. No sibling task directory was read at any point.

## SCAFFOLD.yaml surface
11 entities · 59 endpoints · 45 errors · 32 ordered validations (12 priority bands) · 7 calculations · 9 state-machine dimensions across 7 entities · 4 concurrency rules (OCC-only) · 5 roles (LabelAdmin, DistributionPartner, RoyaltyAnalyst, BusinessAffairs, Artist) · topology `flat` · shape `cyclic` · role_model `segregation_of_duties` · consistency `immediate` · layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers]`.

## §1.8 — 9 rule ids / 24 instances
dual_variant_calc 2 · combinatorial_formula 3 · non_linear_state_machine 3 · transitive_cascade 2 · priority_pair_validation_conflict 3 · boundary_precision_check 3 · cross_entity_state_dependency 3 · resource_temporal_overlap 2 · compensating_invariant 3.

## §1.9 — 9 sections / 81 instances (67 with recipes, 14 `excluded_because`)
entities 9 · state_machines 16 · calculations 14 · validations 12 · endpoints 6 · errors 7 · rbac 7 · cross_cutting_complexity_layers 8 · consistency_model 2.

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     11
  §1.8 instances scanned:     24
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1453

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Independently verified: all 45 §1.6 error ids are triggerable somewhere in §1.8 ∪ §1.9; no UPC is reused inside a single instance except the two instances that deliberately need it (duplicate-UPC 409, and the 400-rejected create that never persists); the forbidden concurrency vocabulary appears nowhere in the three files.

## Design adjudications
- Optional input tokens quoted (`"field?"`); §1.9 `section:` values all snake_case.
- §1.6 has no claim-type table in the guide, so the errors section uses the adjudicated claim_type `error_triggerable`; the RBAC section's per-role bullets likewise have no table, so `role_exclusive_operations` / `cross_role_denial` / `shared_operations` are adjudicated names alongside the real table rows `peer_roles` and `segregation_of_duties`.
- The three §1.0 layers already probed in depth by §1.8 (cascading_side_effects, dual_variant_calculation, rate_threshold_triggers) are recorded as `excluded_because` with the citing §1.8 instance; the `rate_threshold_triggers` "reset works" claim is documented as inapplicable because `units_returned` and `marketing_committed_cents` are both monotone.
- Six SCAFFOLD.yaml consistency fixes came out of the §1.9 walk: unreachable `AUDIT_DENIED` replaced by an audit-scope-containment guard; Release promotion precondition given `ERR_PERIOD_OUTSIDE_TERM` with widened `applies_to`/`check`/`condition`; de-contradicted `ERR_DEAL_NOT_COLLECTING`; recoupment-summary zero-baseline pin; a new priority-8 physical-format precondition on `POST /physical-runs` (reusing `ERR_INVALID_RELEASE_STATE`, so the error count stayed 45); and the stale surface-count comment in §1.0 corrected to 59/45/7/32.
- The one RBAC denial instance that needs an OCC field now sources it from a captured `version` of an unrelated Distributor row, satisfying the skill's "never a bare literal, always a captured `${var}`" rule while keeping the point that priority 2 fires before priorities 5 and 7.

Flag for the orchestrator: the supplied scenario was stored verbatim as instructed, so `scenario:` line 6 of SCAFFOLD.yaml still reads `Generate task harder than expert level!`. Per the known leak path that line should be stripped before the PRD step so the directive does not reach PRD.md.

### Orchestrator note
Acted on the subagent's flag: the difficulty directive line (and its trailing blank line) was removed from `SCAFFOLD.yaml`'s `scenario:` block by the orchestrator immediately after Step 2. `grep -rn "harder than expert\|expert level"` over all three scaffold files now returns nothing, so the directive cannot reach PRD.md via the scaffold. All three files re-verified: `SCAFFOLD.yaml` parses under `yaml.safe_load`, and all three tails end at real structural boundaries (no truncation).

## Step 3: Copy Shared Files — 2026-09-06T01:41:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `.../task_2967_label_distribution_deal_recoupment_accounting/workspace/INSTRUCTION.md` (bash-only step, no subagent).

## Step 4: Generate PRD — 2026-09-06T02:00:00.000Z

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2967_label_distribution_deal_recoupment_accounting/workspace/PRD.md` — **471 lines, 111,505 characters**, built incrementally (one `Write` + eight `cat >>` heredoc appends), ending at a real section boundary (last line is the final `ERR_LIQUIDATION_EXCEEDS_RESERVE` row of the §5 table).

**Section outline**
- `# Label Distribution Recoupment API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs: five coupled sub-ledgers, the term arc, conservation + determinism + flat mount)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC / identity, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Identity/Timestamps/Versions, 2.5 Logical Accounting Clock, 2.6 Money-Percentages-Rounding, 2.7 Version Echo on Ledger-Mutating Writes, 2.8 The Order in Which a Request Can Fail (12-rank ladder), 2.9 Conserved Quantities and Compensating Actions, 2.10 Flat Topology / Discovery
- `## 3. Business Logic & Workflows` — 3.1 Counterparties, Artists, Deal Formation; 3.2 Releases and Advance Allocation; 3.3 Agreements, Rates, Amendments; 3.4 Marketing Commitments and Recoupability; 3.5 Rate Cards and Digital Revenue Reporting; 3.6 Acceptance, the Advance Waterfall and Compensating Disputes; 3.7 Physical Manufacturing, Shipping and Returns Reserves; 3.8 Artist Statements and the Deduction Waterfall; 3.9 Objections, Audit Rights, Finalization and Catalog Wind-Down
- `## 4. Endpoint Definitions` (paragraph + 59-row, 4-column table)
- `## 5. Error Code Catalogue` (45-row, 2-column table)

**Contract 1 — Field-Name Coverage: PASS** (mechanical diff via `.scratch/step4/audit.py`)
- `entities[].fields`: 131 required, 131 present, 0 missing
- `endpoints[].input` (incl. query params, `variant`, `to_iso8601`, paging): 84 required, 84 present, 0 missing
- `concurrency_rules[].occ_field`: 2/2 · `errors[].id`: 45/45 · `roles[].name`: 5/5 · state names: 38/38
- entity enum members (68 across all `constraints`): 68/68 after one repair (`LABEL` on `audit_cost_bearer` was prose-only; now backticked alongside `ARTIST`)

**Contract 2 — Rule Coverage: PASS**
- 32 priority-ordered validations → the §2.8 ladder, each rank naming its error ids, HTTP status and `applies_to` scope (rank 3 left-to-right path resolution, rank 4 the seven ownership-enforced operations incl. the single-statement read, rank 6 the eight body-FK creators, rank 8 the four extra same-rank gates).
- 4 `concurrency_rules` → §2.7, each naming the operation, echo field, parent `version`, error id, 412, and why it is not a state error.
- 9 state-machine dimensions across 7 entities → all transitions incl. every system/cascade edge, both `PhysicalRun` axes and their single coupling, both `ArtistStatement` axes, the report cycle, the agreement amendment cycle, the spend revision cycle, all terminal states.
- 7 calculations → full prose reconstruction with pinned evaluation order and constant *values* (10,000 micros/cent; 0.1000/0.0500, 0.2500/0.1500, cap 0.5000, 0.0500 inventory; 0.3000 marketing cap; 1.0000/0.5000/0.0000 recoupability; 365 days; 0.05 materiality).
- Cross-entity side effects, sibling-branch symmetry (three `deal_type` branches; `CROSS_COLLATERALIZED` vs `SILOED`; `PROVISIONAL` vs `FINAL`; terminate vs expire; `ACCEPT` vs `REJECT`; `UPHELD` vs `DENIED`; `AUDIT_COMPLETED` vs `AUDIT_DENIED`; both `FINALIZED` source states) all written at equal density.

**Contract 3 — §3 Path Purity: PASS** — 956 backticked tokens scanned in §3 (299 unique); tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combinations: 0. Set-membership braces were also eliminated from §4 descriptions so no pseudocode syntax survives anywhere outside the §2.2 JSON block.

**Deliberate omissions:** §4 omits request/response bodies and side effects, §5 omits trigger conditions (both per spec); scaffold-internal references (`calculations.*`, `§1.2.1`, `test_recipe`-adjacent material) and constant *symbol* names were not carried into prose — the values are. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened; no sibling task directory was read.

**Adjudications** (scaffold gaps resolved explicitly rather than left vague): duplicate artist `email` → `ERR_INVALID_REQUEST`; `planned_release_date` outside term at registration → `ERR_INVALID_REQUEST` (that error's `applies_to` excludes release creation); executing a deal with no `PLANNED`/`RELEASED` release → `ERR_INVALID_DEAL_STATE`; `limit`/`offset` out of range → `ERR_INVALID_REQUEST` (400); `version` starts at 1; supersession balance carry-forward is additive on top of the successor's own seeded balances; stored-row quantity cross-checks (`units_shipped` vs `units_manufactured`, `settled_amount_cents` vs `amount_cents`) report `ERR_INVALID_REQUEST` but are evaluated after their transition's state gate, not at rank 5; `liquidation_pct` always applies to `reserve_initial_cents` (so two 0.6000 liquidations over-draw); `dispute_reason` is required and non-blank on both dispute source states; the marketing cap's period-net figure is the statement's two royalty bases (scaffold STEP 1); `DISPUTED → SUBMITTED` re-prices from scratch against current lines and cards; `audit_cost_bearer` is `ARTIST` on the `AUDIT_DENIED` edge even though the finding stays null; statement *creation* is also gated by `ERR_AGREEMENT_NOT_STATEMENTABLE` (from the validation's `applies_to`, though the state machine lists it only at prepare); the period-containment and `FINAL` overlap/contiguity tests apply on the `DRAFT → PREPARED` entry only, since the `REVISED` re-entry's precondition list omits them.

### Orchestrator verification
Guarded against the known doc-generator truncation failure: `wc -l -c` → 471 lines / 111,505 chars; the heading index shows all sections §1–§5 present and in order; the tail ends on the final complete `| ERR_LIQUIDATION_EXCEEDS_RESERVE | 422 |` table row, i.e. a real section boundary, not mid-sentence. No regeneration needed. Leak check: `grep -in "expert level|harder than expert|scaffold|test_recipe" PRD.md` returns nothing, so neither the difficulty directive nor any scaffold-internal reference reached PRD.md.

## Step 5: Generate Unit Tests — 2026-09-06T03:22:00.000Z

Stage 5 (unit-test generation) is complete for `task_2967_label_distribution_deal_recoupment_accounting`.

## Files written

**`test_helpers/` (task root, 3,369 lines)**

| file | lines |
|---|---|
| `__init__.py` | 47 |
| `api_client.py` | 418 |
| `api_errors.py` | 128 |
| `assertions.py` | 444 |
| `constants.py` | 378 |
| `factories.py` | 563 |
| `fixtures.py` | 1,029 |
| `test_users.py` | 107 |
| `types.py` | 255 |

**`test_suite/` (task root, 10,748 lines incl. conftest)**

| file | lines | tests |
|---|---|---|
| `conftest.py` | 65 | — |
| `test_01_dual_variant_and_combinatorial_math.py` | 932 | 12 |
| `test_02_lifecycle_cycles_and_cascades.py` | 1,188 | 11 |
| `test_03_priority_conflicts_and_boundaries.py` | 484 | 12 |
| `test_04_cross_entity_gates_and_temporal_overlap.py` | 669 | 14 |
| `test_05_compensating_invariants.py` | 633 | 6 |
| `test_06_entity_contracts_and_input_validation.py` | 712 | 13 |
| `test_07_state_machine_transitions.py` | 1,764 | 25 |
| `test_08_calculation_engine.py` | 1,315 | 16 |
| `test_09_validation_priority_ladder.py` | 788 | 12 |
| `test_10_endpoint_surface_and_error_catalogue.py` | 986 | 13 |
| `test_11_role_permissions_and_ownership.py` | 566 | 9 |
| `test_12_version_echo_and_response_visibility.py` | 648 | 9 |
| **total** | | **152** |

## Instance coverage

- **§1.8 (queue A, difficulty): 24 / 24 instances translated, 0 skipped** — 9 rules, 0 stubs in the index, >=2 tests per instance (58 tests).
- **§1.9 (queue B, corner): 67 / 67 non-stub instances translated, 0 skipped** (94 tests). The 14 stub instances (those carrying `excluded_because` and no `test_recipe`) were correctly left untested and carry no placeholders: 3 in `state_machines`, 5 in `calculations`, 1 in `validations`, 1 in `endpoints`, 1 in `errors`, 3 in `cross_cutting_complexity_layers`.
- **No instance was skipped by the PRD-first filter.** Sub-assertions that failed condition (ii) were trimmed rather than weakened — the notable ones: `release_breakdown` inner field names (PRD names the array but not its entry fields), several "null at creation" claims the PRD never states, and version bumps on neighbouring aggregates whose recomputation-vs-version relationship the PRD does not pin.

## Verification

- `python3 -m py_compile` passes on all 21 files.
- `pytest --collect-only`: **152 tests collected**, no import or collection errors, no duplicate test names, every signature `(api)`.
- Tag audit (`.scratch/step5/verify_tags.py`): **every one of the 152 tests carries exactly one `Design:` line, it is the last line of its docstring, and it resolves to a real non-stub instance under the exact rule_id/section named.** No untagged, dual-tagged, or dangling tags. All 91 non-stub instances across both queues are accounted for.
- All 152 docstrings carry a quoted PRD citation. No `pytest.skip`/`xfail`/`time.sleep`/`print`, no double envelope unwrap, no bare-float percentages.
- `test_helpers/` and `test_suite/` exist at the task root; `workspace/` contains only `INSTRUCTION.md` and `PRD.md` — no stray copy, and `workspace/implementation/` was never read or touched.

## Notable findings worth carrying into Step 7

Six recipe figures were **recomputed from the PRD and asserted differently** (PRD wins). If the implementation matches the recipe rather than the PRD on these, the failures are real defects, not test bugs:

1. Cross-collateralized advance split-back is a largest-remainder split: **568,749 / 81,251**, not the recipe's 595,000 / 55,000.
2. `active_deal_count` after for-cause termination stays **1** (`TERMINATION_NOTICE` is inside the counted set), not 0.
3. Audit-materiality net payable is **21,800** with a 1,090 threshold — the recipe omitted the recording bucket from the §3.8 waterfall.
4. A DRAFT agreement's two recoupment balances are **0/0** at creation; they seed only at activation.
5. With `advance_amount_cents: 0` the deal is RECOUPED at execute, so activation selects the **escalated** rate (0.1800), not the base rate.
6. `ERR_PERIOD_OUTSIDE_TERM` for statements fires at **prepare**, not at create.

One genuine PRD ambiguity was flagged: §3.7 states a run copies the distributor's `default_returns_reserve_pct` "from the moment it exists", but its later sizing paragraph re-states the fallback as "when it is null" — so an implementation that stores null would still size the reserve correctly. `test_10` asserts the stored value (0.1200); this is the single assertion in the suite resting on a self-inconsistent sentence and is the one candidate for a Step 8 PRD clarification.

## Step 6: Generate Implementation — 2026-09-06T03:52:00.000Z

Implementation complete and verified.

## Deliverables

`/home/ubuntu/github/CodingPRD/tasks/task_2967_label_distribution_deal_recoupment_accounting/workspace/implementation/`

| Module | Lines | Role |
|---|---|---|
| `app.py` | 61 | blueprint registration, `ApiError`/HTTPException handlers, `0.0.0.0:$PORT` |
| `db.py` | 189 | in-memory `Store` (11 dicts), logical clock, `_seq`, ISO/date helpers, `round_half_up`, `largest_remainder` |
| `errors.py` | 114 | 45 error IDs -> HTTP statuses + default messages |
| `middleware.py` | 102 | auth ladder ranks 1-2, Decimal-preserving body parse, pagination |
| `validation.py` | 241 | rank-5 field validators (4-dp percentages, UPC, DSP code, territory, enums) |
| `serializers.py` | 159 | explicit per-entity field projections + the two artist rollups |
| `response.py` | 70 | envelope, `req_` id, `array`/`object`/`error`, pagination meta |
| `routes/common.py` | 80 | 9 `find_*`, ownership, SoD, OCC checks |
| `routes/setup.py` | 159 | clock, distributors, artists, rate cards |
| `routes/deals.py` | 342 | formation, wind-down diamond, recoupment projection |
| `routes/releases.py` | 128 | releases + advance allocation |
| `routes/agreements.py` | 187 | agreements, supersession, amendments |
| `routes/marketing.py` | 176 | spend lifecycle, recoupability, budget |
| `routes/reports.py` | 337 | pricing, 5-hop accept, 4-hop compensating dispute |
| `routes/runs.py` | 254 | manufacture/ship/returns/reserve liquidation + void |
| `routes/statements.py` | 395 | deduction waterfall, objections, finalization, audits |
| `services/calculations.py` | 353 | the 7 calculations |
| `services/lookups.py` | 114 | FK traversal helpers |
| `services/ledger.py` | 28 | `marketing_committed_cents` recomputation |

3,489 Python lines total, plus `start.sh` (foreground `exec python3 app.py`, reads `$PORT`, guarded flask install) and `requirements.txt`. All modules compile (`compileall` clean).

## Coverage (machine-verified, not eyeballed)

- **Endpoints: 59/59.** I diffed the Flask url_map against the PRD §4 table programmatically — zero in-PRD-not-implemented, zero extra.
- **Errors: 45/45.** The catalogue is byte-identical to the set of `ERR_*` tokens in PRD.md (no extras, none missing), and all 45 are reachable from route code.
- **12-rank ladder**: encoded as call order inside every handler — `authenticate()` (1-2) -> `find_*()` (3) -> `require_owner()` (4) -> `v.*` validators (5) -> body-FK `find_*()` (6) -> `check_*_version()` (7) -> status/dimension gates (8) -> `require_separation()` (9) -> deadline checks (10) -> overlap/uniqueness (11) -> money ceilings (12). Read-the-row quantity comparisons (`units_shipped` vs manufactured, settled vs approved) are raised as `ERR_INVALID_REQUEST` *after* the rank-8 gate, per §2.8's carve-out.
- **OCC echo**: only the 4 documented operations accept `expected_deal_version` / `expected_run_version`; checked at rank 7, so a stale echo beats a wrong state.
- **7 calculations**: rate-card resolution + per-line micros->cents pricing; distributor share/net receipts (3 deal types, with the profit-share cut that only deducts marketing approved strictly before the period); largest-remainder allocation of the distributor share across lines; advance waterfall (CROSS vs SILOED); returns-reserve sizing (tier bumps, 0.5000 ceiling); marketing cap (30% + recoupability factors + cumulative-applied subtraction); artist-statement net payable (both `basis_variant` branches).
- **9 state dimensions / 7 entities**: deal, release, agreement, spend, report, run `status` + `reserve_status`, statement `status` + `audit_status`.

## Smoke test

`.scratch/step6/smoke.py` — a ~90-request PRD-derived end-to-end pass (deal formation -> execute -> release -> agreement activate -> marketing approve/settle -> rate card -> report price/accept with escalation -> physical run ship/returns/liquidate/void/full-liquidate -> PROVISIONAL and FINAL statements through object/uphold/re-prepare/issue/finalize/audit -> pagination -> expire/post-term/close cascade), plus deliberate probes at ladder ranks 1, 2, 4, 5, 6, 7, 9, 10, 11, 12. **0 failures**, twice: once on the first boot and again on a second fresh process. Verified between runs that a restart yields an empty store and the clock back at `2026-08-01T00:00:00.000Z`. Both servers ran on random high ports and were killed by their own pid (no `pkill`); ports confirmed free.

## PRD ambiguities resolved

1. **4-decimal percentages over JSON.** `json.dumps(0.1500)` emits `0.15`, so a literal exactly-4-dp rule would reject every happy path. Strings must match `^[+-]?\d+\.\d{4}$`; JSON numbers are range-checked and rejected only if they carry *more* than 4 dp.
2. **List ordering under a repositioned clock.** "created_at ASC" is implemented over a monotonic `_seq` counter, since two records can share a `created_at` after a clock jump.
3. **Marketing approve *and* settle bump the deal version.** §2.7 names "a marketing settlement" as a deal-version advancer; §2.4 says every mutation bumps. Both write `marketing_committed_cents`, so both bump.
4. **`PREPARED -> FINALIZED` guards have no stated error IDs.** Chose `ERR_INVALID_AGREEMENT_STATE` (409) when the agreement is not `POST_TERM` (rank 8) and `ERR_PROVISIONAL_NOT_ISSUABLE` (422) for a non-`FINAL` basis (rank 11) — the latter matching §3.8's "structural reason a PROVISIONAL statement can never be finalized". **This is the least-anchored choice in the implementation.**
5. **`ISSUED -> FINALIZED` `objection_resolution` check not enforced.** No error ID exists for it, and enforcing it literally makes an upheld-then-revised statement un-finalizable; an upheld objection has already left `ISSUED` anyway.
6. **`issue` from `OBJECTED`** allowed unconditionally (the table declares the edge; "when an objection has been denied" is unenforceable since denial already returns the statement to `ISSUED`).
7. **Dispute reversal** uses a private `_release_applied` map recorded at accept, so hop 3 subtracts the exact per-release cents it added (never serialized).
8. **Run creation** rejects a release that is not `PLANNED`/`RELEASED` as well as one with no physical format, both `ERR_INVALID_RELEASE_STATE`, per rank 8's "physically distributable *and not already reverting*".
9. **Distributor/artist rollups** (`active_deal_count`, `lifetime_paid_cents`, `unrecouped_advance_total_cents`) are derived at read time and never bump those records' versions — the PRD enumerates version bumps explicitly and never names them.

### Orchestrator note on Step 5/6 isolation
The skill requires Steps 5 and 6 to be launched in a single assistant message so that the implementation generator is *physically* unable to see `test_suite/`. In this run the orchestrator dispatched Step 5 alone and Step 6 afterwards, so `test_helpers/` and `test_suite/` already existed on disk when the implementation generator started. Mitigation applied at dispatch time: the Step 6 prompt carried an absolute, itemised prohibition on reading, listing, globbing or grepping either directory (as well as the two design indices and any sibling task), framed as a hard failure of the task. The Step 6 agent reported deriving the implementation from `PRD.md` + `SCAFFOLD.yaml` + `INSTRUCTION.md` only, and its own smoke test was written from the PRD rather than from the suite. Recorded here as a process deviation with a logical rather than physical guarantee; the six "PRD wins over recipe" figures Step 5 flagged remain a useful independent cross-check, since an implementation that had peeked at the suite would agree with the tests on all of them by construction.

## Step 7: Run Tests and Iterate — 2026-09-06T04:45:00.000Z

Clean sweep achieved.

## Step 7 — Iteration loop summary

**Iterations run: 3**

**Final sweep (all 8 parallel rounds):**
| round | passed/total |
|---|---|
| 1 | 152/152 |
| 2 | 152/152 |
| 3 | 152/152 |
| 4 | 152/152 |
| 5 | 152/152 |
| 6 | 152/152 |
| 7 | 152/152 |
| 8 | 152/152 |

Failure trajectory: iteration 1 = 145/152 in all 8 rounds (identical 7-test failure set, zero flakiness — no load-induced noise to filter); iteration 2 = 151/152 in all 8 rounds; iteration 3 = clean.

### Tests deleted
**NONE.** Every failing test's rule was traceable to a verbatim PRD sentence and was uniquely derivable, so no STEP 1a silence or STEP 1b collapse pattern applied.

### Fixes to `test_suite/`
- `test_suite/test_06_entity_contracts_and_input_validation.py` — local helper `_distribution_fee_deal_payload`: passed `distribution_fee_pct` both explicitly and again via `**overrides`, so every call that overrode it died with `TypeError: deal_payload() got multiple values for keyword argument`. Now builds a `kwargs` dict, applies `kwargs.update(overrides)`, and splats once.
- `test_suite/test_01_dual_variant_and_combinatorial_math.py` — fixture `_advance_catalog`: never set `marketing_budget_cents` (so it defaulted to 0) while the downstream `_statement_basis_catalog` approves 110,000 cents of marketing; the PRD-faithful impl correctly returned `ERR_MARKETING_BUDGET_EXCEEDED` (PRD §3.4). Added `marketing_budget_cents: 500000`. All downstream expected figures were verified unchanged by this.
- `test_suite/test_02_lifecycle_cycles_and_cascades.py` — `test_dispute_from_submitted_unwinds_nothing_and_the_cycle_still_closes`: expected `unrecouped_advance_share_cents == 100000` before any acceptance had run. PRD §3.2 states verbatim that all four release counters are "at 0" at creation and §3.6 recomputes this one only in the acceptance settle. Expectation corrected to 0.
- `test_suite/test_05_compensating_invariants.py` — `test_disputing_an_accepted_report_walks_back_release_report_and_rate`: same pre-acceptance `unrecouped_advance_share_cents` mis-translation (expected 50000). Corrected to 0.
- `test_suite/test_08_calculation_engine.py` — fixture `_two_finalized_statements_awaiting_audit` stored the finalize-time snapshot and *then* called `do_request_audit`, which is itself a mutation (+1 version per PRD §2.4) whose result was discarded, leaving `test_a_finding_exactly_on_the_five_percent_threshold_reopens_the_statement` asserting off a baseline stale by one. Fixture now captures `ctx[key + "_audit_requested"]` and the test asserts `+1` from it.

### Fixes to `test_helpers/`
**NONE.** `api_client.py` (Decimal-token wire encoding, `canonical_instant`), `factories.py` (`pct` / `pct4` / `_pct_arg`), `assertions.py` and `fixtures.py` were all audited and found faithful.

### Fixes to `implementation/`
- `workspace/implementation/services/calculations.py` — `statement_figures()`: now returns `marketing_cap_cents` from `marketing_recoupable()`. PRD §3.8 verbatim: "The cap, `marketing_cap_cents`, is thirty percent of that figure, rounded half up." — the value was computed but never persisted. (Judged a real field, not an intermediate: this PRD's consistent convention gives fields a backticked snake_case identifier while the neighbouring true intermediates — "The raw pool", "The recoupable pool", "The artist's share" — stay prose-only.)
- `workspace/implementation/routes/statements.py` — `create_statement()`: added `"marketing_cap_cents": 0` to the new-record dict, per PRD §3.8 "A new statement is `DRAFT` with `audit_status` at `NONE` and every money field zeroed".
- `workspace/implementation/serializers.py` — `STATEMENT_FIELDS`: added `marketing_cap_cents` so the field reaches the wire.
- `workspace/implementation/validation.py` — `percentage()`: the Decimal branch used `exponent < -4`, which only rejects *more* than four decimals, so `distribution_fee_pct: 0.15` was accepted with HTTP 201; and the bare-`int` branch accepted integer percentages. Now requires `exponent != -4` and rejects bare integers, per PRD §2.6 verbatim: "A value of 0.15 is not an acceptable substitute for 0.1500: the request-validation rank rejects a percentage that is not written with four decimals ... with `ERR_INVALID_REQUEST` (HTTP 400)." This defect had been masked in iteration 1 by the test_06 `TypeError`, which aborted the test before that assertion ran. Before tightening, I verified via grep that `f.pct(` has exactly one call site (the deliberate rejection case) and that no test sends a bare integer or non-4dp numeric literal to any percentage field — the string branch (`_PCT_RE`, already exactly-4) was left untouched since many tests legitimately send `"0.1000"`-style strings.

### Notes for Step 8
- No implementation check was weakened and no endpoint, field, side effect or capability was added that does not trace to a verbatim PRD sentence. Storage remains in-memory dicts only.
- Of the six pre-supplied "PRD wins over the scaffold's worked example" hypotheses, none produced a test failure — the suite and the implementation already agreed with the PRD reading on all six, so none needed adjudication.
- The PRD §3.7 self-inconsistency ("from the moment it exists" vs "when it is null" for `default_returns_reserve_pct`) never surfaced as a failure; `recompute_reserve()` implements the null-fallback reading and the tests agree with it.
- `workspace/SWEEP_DONE`, `workspace/sweep.log`, `workspace/round.$i.log` and `workspace/implementation/results.$i.json` are sweep artifacts from the final clean run (all timestamped 04:18). `worklog.md`, `PRD.md`, `INSTRUCTION.md` and the `SCAFFOLD*.yaml` files were not touched.

### Orchestrator verification
Re-verified the final sweep from the artifacts rather than trusting the subagent's report: all eight `workspace/implementation/results.$i.json` files exist (timestamped 04:18) and each reads `total: 152, passed: 152`, with a per-test `status` histogram of `{'passed': 152}` in every round — cross-checked on the `status` key (not `outcome`) and against `total - passed == 0`. Step 8 therefore does NOT qualify for the skip condition: Step 7 ran 3 iterations with 5 `test_suite/` fixes and 4 `implementation/` fixes.

## Step 8: Finalize PRD — 2026-09-06T04:52:00.000Z

PRD_FINALIZED.md is complete and verified (471 lines, ends at the `ERR_LIQUIDATION_EXCEEDS_RESERVE` row; all edits inline, no new sections).

## Line counts
- `PRD.md`: 471 lines / 111,505 bytes
- `PRD_FINALIZED.md`: 471 lines / 112,975 bytes
- Delta: 0 lines (+0.0%), +1,470 bytes (+1.32%) — four in-place sentence revisions

## Changes

- **§2.6** — revise — pinned that the four-decimal percentage test reads the wire literal (JSON number *or* string), that bodies are parsed keeping a numeric literal's own digits rather than collapsing to a binary float, and that any scale other than exactly four — including a bare integer with no decimals — is refused — `implementation/validation.py:67-99`, `implementation/middleware.py:57-69`
- **§3.2** — revise — pinned that a new release's `unrecouped_advance_share_cents` is a literal 0 regardless of `advance_share_cents`, and is first recomputed from its stated definition only by an acceptance or compensating dispute cascade — `implementation/routes/releases.py:69`, `implementation/routes/reports.py:229,318`
- **§3.8** — revise — pinned `marketing_cap_cents` as a field recorded on and returned with the statement, and the raw pool / recoupable pool / artist's share as non-exposed intermediates — `implementation/services/calculations.py:281,346`, `implementation/routes/statements.py:75`, `implementation/serializers.py:74`
- **§3.9** — revise — pinned the `PREPARED → FINALIZED` guard pair's identifiers and their ladder positions: `ERR_INVALID_AGREEMENT_STATE` (409, state-gate rank, before SoD) for a non-`POST_TERM` agreement, `ERR_PROVISIONAL_NOT_ISSUABLE` (422, rank 11, after SoD) for a non-`FINAL` basis — `implementation/routes/statements.py:280-290`

## Per-edit pre-edit search log

**Edit 1 (§2.6 percentage literal)**
(a) Subject: percentage payload validation across every percentage field, and the JSON body parse that feeds it.
(b) Paths enumerated: `validation.py::percentage` (string/`Decimal`/`int`/`bool`/fallback branches, `_PCT_RE`), `middleware.py::parse_body` (`json.loads(..., parse_float=Decimal)`), and every one of the 12 `v.percentage` call sites — `routes/deals.py:37,44,51`; `routes/agreements.py:32,34,42,44,145`; `routes/runs.py:37,195`; `routes/setup.py:45`. Confirmed a single shared validator, so the claim holds for all of them; confirmed `returns_reserve_pct` omitted → `_MISSING` → `None` default (distributor fallback), so the "bare integer rejected" clause does not disturb the optional-field path. Cross-read `test_helpers/api_client.py` and `factories.py` (`pct`/`pct4`) to confirm the wire form is a bare JSON number with exact digits, and that string percentages are also legitimately sent.
(c) Adjustment: worded as "identically whether … a JSON number or a JSON string" and explicitly listed `"0.1500"` as accepted, so the string branch (`_PCT_RE`, already exactly-4) is not accidentally excluded; said "parsed in a way that keeps a numeric literal's own digits" rather than naming a library setting.

**Edit 2 (§3.2 `unrecouped_advance_share_cents`)**
(a) Subject: every write of the release record's `unrecouped_advance_share_cents`.
(b) Paths enumerated by grep: `routes/releases.py:69` (creation, literal 0), `routes/reports.py:229` (acceptance hop 3), `routes/reports.py:318` (dispute compensation hop 3), `routes/deals.py:328` (the `release_breakdown` element of the read-only recoupment projection), `serializers.py:29`. Also checked `routes/deals.py` terminate/expire/close cascades — none of them touch this counter.
(c) Adjustment: scoped the wording to "on the new record" / "this deal's releases" and named both the acceptance *and* the compensating dispute, so it does not contradict `deals.py:328`, where the projection's same-named breakdown field is legitimately `share − amount` from a zero baseline for a release with no attribution.

**Edit 3 (§3.8 `marketing_cap_cents`)**
(a) Subject: `marketing_cap_cents` and the other three values `marketing_recoupable()` returns.
(b) Paths enumerated by grep: `services/calculations.py:259-285` (`marketing_recoupable`, sole caller `statement_figures` at :323), `:346` (only `marketing_cap_cents` promoted into the returned figures dict; `raw_marketing_cents`, `recoupable_marketing_cents`, `artist_marketing_share_cents` are consumed locally at :333 and dropped), `routes/statements.py:75` (create → 0), `:168-169` (prepare → `statement.update(figures)`, both the `DRAFT` and `REVISED` entries), `serializers.py:69-81` (`STATEMENT_FIELDS`). Confirmed no reset in `resolve_objection`, `conclude_audit`, or any VOID cascade.
(c) Adjustment: said "the raw pool, the recoupable pool and the artist's share described next are working intermediates the statement does not expose" — deliberately not claiming they are never computed, only never carried, which matches the dict `marketing_recoupable` still returns.

**Edit 4 (§3.9 `PREPARED → FINALIZED` guards)**
(a) Subject: the two guard identifiers on the `PREPARED` finalize path, and their position relative to the segregation-of-duties test.
(b) Paths enumerated by grep on both identifiers: `routes/statements.py:281` (finalize, agreement not `POST_TERM` → `ERR_INVALID_AGREEMENT_STATE`, at line 280-281, i.e. *before* `require_separation` at :283), `:290` (finalize, non-`FINAL` basis → `ERR_PROVISIONAL_NOT_ISSUABLE`, *after* :283), `:190` (issue, non-`FINAL` → same identifier), `:56` and `:140` (create/prepare use `ERR_AGREEMENT_NOT_STATEMENTABLE`, a different identifier — deliberately not touched), `routes/agreements.py:103,112,150,168` (the other four `ERR_INVALID_AGREEMENT_STATE` sites, all supersession/amendment gates), `errors.py:36,51`. Also confirmed finalize applies no statementability test at all, and that §2.8 already ranks these two identifiers at 8 and 11 respectively, so no ladder edit was required.
(c) Adjustment: phrased the ordering claims relative to the segregation-of-duties test rather than restating the whole ladder, and added "exactly as a `PROVISIONAL` statement is refused at issue" so the sentence stays consistent with the parallel check at `statements.py:190`.

Two items in `<step_7_diff>` were deliberately **not** patched: the §3.7 `returns_reserve_pct` self-inconsistency (I verified `routes/runs.py:51-52` *does* copy the distributor default at creation, so the sizing paragraph's null-fallback at `calculations.py:212-215` is dead code and both PRD sentences are simultaneously true of the implementation), and the four pure test-artifact fixes (test_06 kwargs splat, test_01 `marketing_budget_cents`, test_08 stale audit-request baseline) whose rules PRD §2.4/§3.4 already determine.

### Orchestrator verification
`PRD_FINALIZED.md` is 471 lines / 112,975 bytes vs PRD.md's 471 / 111,505 — not byte-identical (four in-place revisions confirmed by `diff`), and the tail still ends on the final `| ERR_LIQUIDATION_EXCEEDS_RESERVE | 422 |` row, so nothing was truncated.

## Step 9: Complete PRD — 2026-09-06T06:05:00.000Z

Orchestrator note on method: Step 9 was run as **four sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, because a single agent cannot hold a 3,489-line implementation plus a 471-line/113KB PRD and still do an exhaustive behavior-by-behavior scan. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2–4 were explicitly forbidden from copying anything over it and each verified the running line/char floor before returning, so no pass could clobber a predecessor. Pass 4 was a narrow reconciliation pass whose only job was to close the cross-pass contradictions the first three reported (partitioned passes report contradictions rather than fixing them).

### Pass 1 — cross-cutting layer (app, db, errors, middleware, validation, serializers, response, routes/common, services/lookups, services/ledger)

`PRD_FINALIZED.md` → `PRD_COMPLETED.md`: 471 → 471 lines, 112,975 → 118,183 chars (+5,208). 11 lines touched. **10 ambiguity-pins, 1 mismatch-revision.**

- **§2.2** — insert — ambiguity — `api_request_id` is the `req_` prefix plus exactly twenty characters from `A`–`Z` and `0`–`9` — `response.py:12-16`
- **§2.3** — insert — ambiguity — a `limit`/`offset` that is blank, decimal or non-numeric is `ERR_INVALID_REQUEST`, not a silent fallback to the default — `middleware.py:76-91`
- **§2.3** — insert — ambiguity — list order and every "earliest creation" tie-break resolve against **write order**, not the `created_at` value; repositioning the clock (including backwards) never reshuffles existing records — `db.py:183-189`
- **§2.4** — insert — ambiguity — payload leads with system fields (`id`, `created_at`, then `updated_at`/`version` on the nine mutable types), then exactly the fields §3 attributes to that type, with no internal bookkeeping (the write-sequence counter) on the wire — `serializers.py:9-93`
- **§2.5** — insert x2 — ambiguity — (a) calendar-date fields are bare `YYYY-MM-DD` in both directions, never widened to instants, while instant fields use the 3-fractional-digit UTC form (`db.py:108-111` / `db.py:66-74`); (b) supplied instants: trailing `Z` == `+00:00`, no offset => UTC, non-zero offset normalised, sub-millisecond precision **truncated** not rounded — `db.py:77-93`, `validation.py:161-172`
- **§2.6** — insert — ambiguity — the four-decimal rule governs the request literal and the held scale, not the response text: stored percentages come back as JSON **numbers** in shortest form (0.1500 -> `0.15`, 0.0000 -> `0.0`), and `null` is distinguishable from zero — `response.py:26-33`
- **§2.8 rank 5** — revise + insert — ambiguity — territory codes validated by **shape alone** (two uppercase ASCII letters, no registry check, so `ZZ` is accepted); unknown request keys ignored (incl. client-supplied `id`/`created_at`/`version`); explicit `null` on an optional field == omitted and takes the default, on a required field fails as missing; JSON-string literals accepted for integers (signed digits), booleans (`"true"`/`"false"`) and percentages (four decimals); absent/empty body read as `{}`, unparseable or non-object body is itself `ERR_INVALID_REQUEST` — `validation.py:14-246`, `middleware.py:57-69`
- **§2.8 rank 6** — insert — ambiguity — the 400/404 boundary: a foreign key that is missing, non-string, blank or whitespace-only fails at rank 5; only a well-formed identifier (whitespace trimmed before lookup) reaches rank 6 — `validation.py:118-124`
- **§2.10** — insert + revise — ambiguity — statements are additionally filterable by `audit_status`; every list filter (`status` included) is an unvalidated exact string match, cumulative across filters, so an unknown enum spelling or dangling id narrows the page to nothing rather than erroring; unlisted query params ignored — `routes/statements.py:113`, `routes/deals.py:121-124` (+7 sibling list routes)
- **§3.1** — insert — ambiguity — artist `email` shape: non-blank local part, single `@`, dotted domain, within 254 characters — `validation.py:16,175-181`
- **§4 intro** — insert — **mismatch** — trailing slash is equivalent to none; an unrecognised path answers `ERR_INVALID_REQUEST` at **404** and an unsupported method at **405**, not at that identifier's tabulated 400 — `app.py:21,31-45`

Verified no change needed: the §5 catalogue is byte-consistent with `errors.py` — all 45 identifiers present on both sides with identical HTTP statuses (checked programmatically).

Deliberately left unpatched: read-time roll-up computation (observationally indistinguishable from "recomputed"); `round_half_up`'s half-away-from-zero sign behavior (no reachable path rounds a negative); `largest_remainder`'s `total == 0` short-circuit (already implied); `app.py`'s catch-all 500 handler (no endpoint reaches it); `Store.reset()` (not exposed); `require_separation`'s null-counterpart no-op (unreachable); per-field text limits and initial values that live at route call sites, and `expected_*_version` field validation (later passes' modules).

### Pass 2 — formation routes (setup, deals, releases, agreements, marketing)

471 lines / 118,183 chars → 471 lines / 123,725 chars (+5,542). **14 ambiguity-pins, 2 mismatch-revisions.** A line-by-line diff against PRD_FINALIZED confirmed all 11 of pass 1's edited lines intact and only 16 further lines changed.

- **§2.7** — revise — **mismatch** — the deal-`version` writer list said "another report's acceptance, a dispute, or a marketing settlement"; a marketing **approval** bumps it too — `marketing.py:140-141`
- **§3.1** — insert — ambiguity — `active_deal_count` is a read-time derivation, so a deal transition never bumps the distributor's own `version`/`updated_at` (nothing ever mutates a distributor after registration) — `serializers.py:96-103`, `deals.py:145-268`
- **§3.1** — insert — ambiguity — same for the artist's `lifetime_paid_cents` / `unrecouped_advance_total_cents` — `serializers.py:106-123`
- **§3.1** — insert — ambiguity — `advance_payment_reference` is 1–200 characters and not blank — `deals.py:136-137`
- **§3.2** — revise — **mismatch** — the term-containment test on `planned_release_date` was called a rank-5 shape violation; impl evaluates it only after `deal_id`/`primary_artist_id` resolve, so a missing deal + out-of-term date yields the 404. Same edit pins that registration is ungated on the deal's status — `releases.py:35-41`
- **§3.2** — insert — ambiguity — on take-to-market the release's own status is tested before the deal's (`ERR_INVALID_RELEASE_STATE` wins) — `releases.py:104-108`
- **§3.3** — insert — ambiguity — drafting an agreement inspects only shape + reference existence: no release/deal status gate and no uniqueness, so several agreements may exist for the same artist+release and two drafts may name the same predecessor — `agreements.py:49-52`
- **§3.3** — insert — ambiguity — activation gate order (own `DRAFT`, then release, then predecessor); the parent deal's status is never consulted at activation — `agreements.py:102-112`
- **§3.3** — insert — ambiguity — `proposed_royalty_rate_pct` is a four-decimal 0.0100–0.5000 fraction, `proposed_advance_amount_cents` a non-negative integer, both required; the agreement's `ACTIVE` gate precedes the deal-status gate — `agreements.py:145-153`
- **§3.3** — insert — ambiguity — an accepted amendment's new base rate is never re-tested against `escalated_royalty_rate_pct`, so `royalty_rate_pct` may end up above it and a recouped deal then selects the lower escalated value verbatim — `agreements.py:169-181`, `calculations.py:187-190`
- **§3.4** — insert — ambiguity — spend creation examines the release's status only, not the parent deal's — `marketing.py:32-34`
- **§3.4** — insert — ambiguity — a resubmitted `amount_cents` must also be strictly positive; the spend's own state gate precedes the release-promotable gate — `marketing.py:79-85`
- **§3.4** — insert — ambiguity — APPROVE check order (deal status -> release promotable -> segregation of duties -> budget) and the three literal members of `recoupability_override` — `marketing.py:108-133`
- **§3.4** — insert — ambiguity — `revision_note` and `recoupability_override` are shape-checked on every arm (blank note or bad override -> 400 even on APPROVE/REJECT) and discarded by arms that don't use them — `marketing.py:110-114`
- **§3.6** — insert — ambiguity — the projection: an unrecognised `variant` is `ERR_INVALID_REQUEST` (400) rather than ignored; no state gate at all (a `DRAFT` deal answers with a zero pool); `recoupment_status` is `RECOUPED` exactly when projected unrecouped is 0; plus the full `release_breakdown` contract — one entry per `PLANNED`/`RELEASED`/`REVERSION_PENDING` release in creation order, its six fields defined, per-release pool from that release's own lines on `ACCEPTED` reports, cross-arm split by largest remainder with earliest-creation ties, including the corner where all release pools are zero yet deal-level `advance_applied_cents` is positive — `deals.py:272-342`
- **§3.9** — insert — ambiguity — closure recomputes the deal's `marketing_committed_cents` after voiding `APPROVED` spends, so an approved-but-unsettled commitment is released from the committed total — `deals.py:267`

Deliberately left unpatched: cascaded version bumps (§2.4 already determines them); `enter-post-term-collection` not recomputing `marketing_committed_cents` (derivable); free-text fields stored with surrounding whitespace while identifiers are trimmed (pass-1 territory); absence of uniqueness on distributor `name`, `dsp_code`, `vendor` (silence correctly means no constraint); `escalated_royalty_rate_pct` having no lower bound (unreachable).

### Pass 3 — revenue / physical / statement routes + the calculation engine (reports, runs, statements, calculations)

471 lines / 123,725 chars → 471 lines / 133,729 chars (+10,004). **24 ambiguity-pins, 8 mismatch-revisions** (32 substantive edits, all targeted `Edit`s).

- **§2.7** — revise — mismatch — deal-version writer list extended to name a shipment or a returns recording on one of the deal's physical runs (pass 2's flag, corrected: `_adjust_net_receipts` is called from ship and record-returns only, never from liquidate/void) — `routes/runs.py:101,162,185`
- **§3.5** — insert x6 — ambiguity — report `dsp_code` takes the same 2–24 uppercase/underscore form a rate card's does (`reports.py:29`); opening a report examines no deal status, no term containment and no uniqueness (`reports.py:25-53`); report creation is not ownership-checked, so a partner may open a report against another distributor's deal (`reports.py:25-28`); a line's release need only exist — no deal-membership and no status test (`reports.py:90`); the territory-licensed 400 sits after the report's state gate, so an `ACCEPTED` report reports `ERR_INVALID_REPORT_STATE` (`reports.py:81-108`); `accepted_at` is cleared by neither dispute nor re-submission (`reports.py:144,183`)
- **§3.6** — revise/insert x9 — hop-2 roll-up hits every referenced release whatever its status or parent deal, the attributable filter governing hop 3 only (`reports.py:196-206`); **mismatch** — the cross-collateralized split runs over the deal's *attributable* releases including zero-weight ones, so a contribution from a non-attributable release counts to the pool but not the split (`calculations.py:155-168`); the report retains its per-release attributions internally, off the wire, as the record a dispute unwinds (`reports.py:49,215`); hop 5 writes every accountable agreement whether or not the recomputed rate differs (`calculations.py:193-203`); each cascaded record bumps `version` once however many hops write it; `dispute_reason` has no maximum length (`reports.py:271`); the `SUBMITTED` dispute arm still writes the deal and bumps its `version`, which is why the version echo is required on both arms (`reports.py:266-334`); "a finalized statement reads this report" means the statement's period fully contains the report's (`reports.py:248-263`); **mismatch** — dispute hop 3 replays the retained per-release amounts exactly, not a fresh pro-rata split (`reports.py:304-324`)
- **§3.7** — insert/revise x9 — FKs resolved `release_id` then `distributor_id` (`runs.py:41-42`); no window/term comparison and no deal-status test at planning (`runs.py:25-53`); the partner default is copied once at planning, never re-derived (`runs.py:51-52`); full initial seeding — nine counters at 0, `returns_rate` 0.0000, `effective_reserve_pct` alone null (`runs.py:58-79`); **mismatch** — manufacture is not bounded by `units_planned`, and the run's own `PLANNED` gate is tested before the release's (`runs.py:121-138`); `units_shipped` and `wholesale_unit_price_cents` may both be zero (`runs.py:146-151`); `returned_units` of zero is an accepted no-op (`runs.py:167-187`); a zero net-receipts delta writes neither release nor deal, while the run is always written (`runs.py:101-117`); the liquidation landing state is decided by cumulative liquidated vs `reserve_initial_cents`, so a 0-cent reserve goes straight to `LIQUIDATED` (`runs.py:190-218`); the void guard applies no period test (`runs.py:221-233`, `calculations.py:309-318`)
- **§3.8** — revise/insert x7 — DRAFT seeding: `revision_count` 0 and the nine waterfall money fields 0, everything else null including the three objection/audit money fields (`statements.py:58-93`); physical base `window_end` window inclusive at both bounds (`calculations.py:313`); preparation reads the stored `active_royalty_rate_pct`, writes nothing to the agreement and never moves its `version` (`calculations.py:295`); the reserve basis is filtered by run status alone, with no period test (`calculations.py:309-318`); `prepared_by_user_id` is rewritten on every preparation, moving the segregation-of-duties target (`statements.py:170`); preparation clears no objection field, so a retained `objection_adjustment_cents` is added back again on a later revision (`statements.py:172-176`); **mismatch** — issue from `OBJECTED` applies no `objection_resolution` test, re-stamps `issued_at`/`objection_deadline` and leaves objection fields intact (`statements.py:186-198`)
- **§3.9** — revise/insert x6 — `objection_disputed_amount_cents` may be zero but not negative, `objection_narrative` non-blank with no maximum (`statements.py:212-215`); a repeat objection overwrites only the four objection-filing fields, leaving `objection_resolution`/`objection_adjustment_cents` from the prior cycle (`statements.py:226-231`); **mismatch** — finalize applies no `objection_resolution` test, so a statement finalizes with `UPHELD` still stored (`statements.py:264-291`); **mismatch** — finalize bumps the release's `version` too and writes agreement and release unconditionally (`statements.py:293-309`); `auditor_name` non-blank with no maximum (`statements.py:325`); the materiality comparison is inclusive, so a zero `net_payable_cents` makes every finding (zero included) material (`statements.py:372`, `calculations.py:355`); **mismatch** — the material reversal bumps the release's `version` too (`statements.py:385-389`)

Deliberately left unpatched: zero-weight line allocation (already uniquely implied); no `reserve_status` gate on liquidation (already stated); `PARTIALLY_LIQUIDATED`+`RECONCILED`, `ERR_RELEASE_NOT_FOUND` inside `prepare_statement`, and the `conclude-audit` reversal's extra `status == "FINALIZED"` condition (all proved unreachable — documenting dead branches adds prose without pinning behavior); the revenue-line `tier` enum and audit-scope end-not-before-start (already covered).

### Pass 4 — reconciliation

471 lines / 133,729 chars → 471 lines / 135,373 chars (+1,644, all inside existing paragraphs). Headings §1–§5 all intact; file still ends on `| ERR_LIQUIDATION_EXCEEDS_RESERVE | 422 |`.

Per-item verdicts:
- **Item 1 — §3.3's "five places" vs four (fixed).** Selection runs in exactly four places: `agreements.py:134` (activate), `agreements.py:180` (**ACCEPT arm only**; REJECT at :183 merely clears the parked fields), `reports.py:239` (accept hop 5), `reports.py:329` (dispute hop 4). Statement preparation copies the stored `active_royalty_rate_pct` (`calculations.py:295`) and writes nothing to the agreement. §3.3 narrowed to four with the ACCEPT/REJECT split spelled out and preparation explicitly excluded, so §3.3 now agrees with pass 3's §3.8 edit. The one other occurrence — the §4 prepare row's "runs the rate selection" — was fixed too.
- **Item 2 — §2.10 vs the validated `variant`: no change needed.** §2.10's "none of them is validated" is scoped by "Every one of these filters" and `variant` is not among them; §3.6 already carves it out. The tail "a query parameter the endpoint does not list is ignored" is true everywhere — recoupment-summary *does* list `variant` (`deals.py:276`) — and `limit`/`offset` are named separately as the paging parameters and pinned in §2.3.
- **Item 3 — §2.7 writer list (revised).** A full grep of `db.touch(deal)` gives ten writers: report accept (`reports.py:244`), report dispute on **both** arms (`reports.py:336`), marketing approve (`marketing.py:141`), marketing settle (`marketing.py:175`), ship/record-returns via `_adjust_net_receipts` (`runs.py:115`, guarded by `if delta == 0: return []` at :102), and the deal's own five lifecycle transitions (`deals.py:152,193,214,231,268`). The list as pass 3 left it was **missing all five lifecycle transitions** and did not admit the zero-delta case; both fixed.
- **Item 4 — §2.3 ordering universality: no change needed.** Every list endpoint and all 12 `lookups.py` helpers go through `db.ordered` (`db.py:189`, `key=r["_seq"]`); `largest_remainder` tie-breaks on caller-supplied `_seq` (`db.py:148`; call sites `calculations.py:148,166`, `deals.py:306`); `resolve_rate_card` sorts `-effective_from` then `_seq` ascending (`calculations.py:68`) — creation order, exactly as §2.3 states. No exception exists.
- **Item 5 — cross-pass self-contradictions: three found, all closed.** (1) §3.3↔§3.8 on rate selection at preparation — closed via Item 1. (2) §3.4↔§2.7 — §3.4 said only that `marketing_committed_cents` "is then recomputed", which read as the read-time derivation §3.1 attributes to `active_deal_count`, while §2.7 now names approval/settlement as deal-record writers; §3.4 clarified that it is a stored write (`ledger.py:26-28` + `db.touch(deal)`). (3) §2.10 claimed every list endpoint filters by `status`, but rate cards have no status field (`setup.py:152` filters only the triple) — carve-out added. Checked and found consistent with no change: the reserve identity §2.9↔§3.7; the void-liquidation guard §3.7↔§3.8 (code also tests `basis_variant == "FINAL"` at `runs.py:225`, but a PROVISIONAL statement can never reach FINALIZED, so §3.7's broader gloss is accurate); dispute containment §3.6↔§3.8; statement/run initial values; the once-per-record version dedupe in §3.6 hop 5; the unconditional triple write at finalize.
- **Item 6 — the deferred "pinned elsewhere" claims: all present exactly once and accurate.** `audit_status` list filter (§2.10 only, matches `statements.py:112`); unknown-key tolerance (body keys in §2.8 rank 5, query keys in §2.10 — one statement each, no overlap); the FK 400-vs-404 boundary (§2.8 rank 6 only, matches `validation.identifier`); instant normalisation (§2.5 only, matches `db.parse_instant`); the four-decimal rule (§2.6 only, §2.8 rank 5 merely cross-references it, matches `validation.percentage` plus the `Decimal -> float` response encoder). Nothing was silently deferred by both passes into silence.

Pass 4 changes:
- §3.3 — revise — "five places" -> "exactly four places"; ACCEPT-only amendment arm named, REJECT arm and statement preparation explicitly excluded — `routes/agreements.py:134,180`, `routes/reports.py:239,329`
- §3.3 — revise — the preparation sentence now says the freeze is a copy of the stored field, not a fifth selection, and writes nothing to the agreement — `services/calculations.py:295`, `routes/statements.py:168-177`
- §4 (prepare row) — revise — "runs the rate selection" -> freezes the stored rate, no selection re-run, agreement not written — `routes/statements.py:131-178`
- §2.7 — revise — deal-version writer list gains the five lifecycle transitions and the nonzero-delta qualifier on ship/record-returns — `routes/deals.py:152,193,214,231,268`, `routes/runs.py:101-117`
- §3.4 — insert — `marketing_committed_cents` is a stored write that bumps the deal's `version` on approve and on settle; REJECT/REQUEST_REVISION write no deal record — `routes/marketing.py:140-141,173-175`, `services/ledger.py:26`
- §2.10 — revise — the `status` filter applies only to types that carry a status; rate-card listing named as the exception — `routes/setup.py:152`

Known imperfection left in place by pass 4: §3.7's "Sizing the reserve" paragraph keeps the fallback to the shipping partner's `default_returns_reserve_pct` "when [the run's own value] is null", while the planning paragraph states the percentage is copied once at planning so it is never null. The code carries the same dead fallback (`calculations.py:213-215`), so the PRD mirrors the implementation; narrowing it would remove a branch the implementation genuinely has.

### Step 9 totals and orchestrator verification
`PRD_FINALIZED.md` 471 lines / 112,975 chars → `PRD_COMPLETED.md` 471 lines / 135,373 chars (+22,398 chars, +19.8%); 0 lines added or removed, every edit in-paragraph, no new sections. Across the four passes: 48 ambiguity-pins and 11 mismatch-revisions, plus 6 reconciliation edits.

Orchestrator checks, run independently of the subagents: `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran — the known "identical file" failure mode is excluded); all five `## ` section headings §1–§5 are present and in order; the file ends on the final complete `| ERR_LIQUIDATION_EXCEEDS_RESERVE | 422 |` table row, so no pass truncated it; and no difficulty-directive text appears anywhere in it. No implementation or test file was modified during Step 9, so the Step 7 clean 8-round sweep (8 × 152/152, `workspace/implementation/results.1..8.json`) remains the valid final evidence for this task.

## Pipeline complete — 2026-09-06T06:10:00.000Z

All nine steps finished. Final deliverables in place: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (conftest + 12 test files, 152 tests), and `workspace/` with `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` (19 modules + `start.sh` + `requirements.txt`) and `results.1..8.json` from the final all-green sweep.
