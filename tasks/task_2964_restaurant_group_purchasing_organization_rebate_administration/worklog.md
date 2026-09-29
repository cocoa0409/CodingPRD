# Worklog — task_2964_restaurant_group_purchasing_organization_rebate_administration

## Step 1: Create task directory — 2026-09-05T23:08:00.000Z

Created `tasks/task_2964_restaurant_group_purchasing_organization_rebate_administration/` and `workspace/` at the pre-assigned path (index fixed by scenario number 2964; no index scan performed, per orchestration directive).

## Step 2: Generate scaffold — 2026-09-06T00:49:25.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the linter is clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2964_restaurant_group_purchasing_organization_rebate_administration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2964_restaurant_group_purchasing_organization_rebate_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2964_restaurant_group_purchasing_organization_rebate_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1206

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Domain model (SCAFFOLD.yaml, §1.0–§1.7 only — no design keys present)
13 entities: ProgramTier, Distributor, Member, AuthorizationLetter, ManufacturerDeal, ContractedItem, RateCard, PurchaseBatch, PurchaseLine, RebateAccrual, ManufacturerClaim, RebateDispute, ComplianceReview. **61 endpoints**, 52 error ids, 41 validations (priority 1–41), 10 calculations, 13 state dimensions, 2 concurrency rules, 6 roles (GpoAdmin, RebateAnalyst, DisputeArbiter, MemberOperator [entity_backed:Member], DistributorFeed [entity_backed:Distributor], ManufacturerRep). Profile: ledger_reconciliation / compliance_audit, flat topology, parallel state machines, `segregation_of_duties`, `immediate` consistency, difficulty `beyond_expert`.

## §1.8 — SCAFFOLD_DIFFICULTY_DESIGN.yaml (1,990 lines)
9 rules / 19 instances: `dual_variant_calc` (marginal-batch vs blended-period rebase; as-purchased vs full-basket opportunity), `combinatorial_formula` (nested tier ladder + card selection; markup rounding order per-line-then-sum; frozen snapshot breaking the admin-fee circularity), `non_linear_state_machine`, `transitive_cascade` (dispute-upheld and deal-loss 4-hop cascades), `priority_pair_validation_conflict` (p12>p29, p16>p41), `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap` (half-open letters vs closed-interval rate cards), `compensating_invariant` (money triple reconciles to gross; case conservation).

## §1.9 — SCAFFOLD_CORNER_DESIGN.yaml (5,096 lines, 71 instances, 11 of them `excluded_because` stubs)
All nine guide sections: entities 12, state_machines 13, calculations 10, validations 12, endpoints 5, **errors 8** (auth-header 401s, pagination bounds, scoped duplicate business keys, period bounds vs future review window, suspended-distributor gate on exactly its three endpoints, dispute-amount bounds + duplicate-open-dispute across two statuses, the unaccrued-batch gate on both reconcile and close-period, plus one stub), **rbac 5** (positive exclusive-op walk across all six roles, cross-role 403s ahead of state/OCC gates, member scope via three paths, distributor scope via three paths, three-way segregation of duties), **cross_cutting_complexity_layers 5** (one OCC instance per §1.7 concurrency rule, the cumulative posture threshold at limit 2 with a one-way flip, plus stubs for cascading_side_effects and dual_variant_calculation), **consistency_model 1** (`immediate`). Every one of the 52 declared error ids is reachable somewhere in §1.8+§1.9; no instance name repeats across the two design files; all stub citations resolve to real §1.8 instance names.

## Sizes
```
-rw-rw-r-- 1 ubuntu ubuntu 151380 SCAFFOLD.yaml                  2942 lines
-rw-rw-r-- 1 ubuntu ubuntu 142205 SCAFFOLD_DIFFICULTY_DESIGN.yaml 1990 lines
-rw-rw-r-- 1 ubuntu ubuntu 352737 SCAFFOLD_CORNER_DESIGN.yaml     5096 lines
```

Notes for the orchestrator: `worklog.md` and `workspace/` were left untouched; only `.scratch/step2` was removed (parent `.scratch/` preserved). One pre-existing inconsistency was fixed while auditing — a §1.9 assert referenced a `purchase_batch_id` filter on `GET /accruals`, which §1.5 does not declare; it now uses `purchase_line_id`.

Orchestrator note: after the subagent exited, the line "Generate task harder than expert level!" was stripped from SCAFFOLD.yaml's `scenario:` key (known leak path into PRD.md). The scenario text itself is unchanged.

## Step 3: Copy shared files — 2026-09-06T00:49:25.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-06T01:02:22.000Z

Subagent summary (verbatim):

PRD generated at `workspace/PRD.md` — 476 lines, built in 6 incremental appends, ending cleanly on the last row of the §5 error table.

## Section list

- **§1 Introduction** (3 paragraphs: GPO business context, system scope, two design commitments)
- **§2 Global Specifications** — 11 subsections: 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim, verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Record Properties, Versioning and Immutable Records · 2.5 Flat Resource Topology and Identifier Resolution · 2.6 Cents, Basis Points and Rounding Discipline · 2.7 Order of Request Evaluation · 2.8 Optimistic Concurrency on Parent Records · 2.9 Segregation of Duties · 2.10 Cascade Integrity and Derived Counters · 2.11 Calendar Dates, Instants and the Logical Clock
- **§3 Business Logic** — 9 subsections: 3.1 Program config / enrollment / authorization letters · 3.2 Deals, items, rate-card governance · 3.3 Feed ingestion and normalization · 3.4 Accrual, rate selection, split waterfall · 3.5 Claims, reconciliation, accrual validation · 3.6 Disputes, evidence rounds, reversal cascade · 3.7 Cost-plus audit and recovery · 3.8 Compliance reviews and deal loss · 3.9 Period close, blended rebasing, savings reporting
- **§4 Endpoint Definitions** — 4-column table, all 61 endpoints
- **§5 Error Code Catalogue** — 2-column table, all 52 error codes

## Coverage

13 entities / 61 endpoints / 52 errors / 10 calculations (both dual-variant pairs — `MARGINAL_BATCH` vs `BLENDED_PERIOD`, `AS_PURCHASED` vs `FULL_BASKET` — rendered with equal density) / 13 state-machine dimensions including `PurchaseBatch`'s two parallel dimensions and both cyclic dimensions / all 41 validations / both OCC rules. All constants embedded in business prose (5,000,000-cent admin-fee band break as "fifty thousand dollars", 200-bps variance tolerance as "two percent", 500-bps warn band as "five percentage points wide", 365-day proration, 10000-bps denominator).

## Hard contract reports

```
Field coverage check:
- entities[].fields: 112 required, 112 present, 0 missing
- endpoints[].request_body: 63 required, 63 present, 0 missing
- endpoints[].query_params: 31 required, 31 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
- computed-read / clock response fields: 14 required, 14 present, 0 missing
Status: PASS   (3 passes; pass 2+ required standalone-backtick match, not substring)
```
```
Rule coverage check:
- validations[] with priority: 41 checked, 41 expressed as an explicit ordered ladder in §2.7, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_contracted_item_version /
  expected_deal_version + ERR_STALE_PARENT_VERSION + 412), 0 missing
- state_machines[].transitions: 13 dimensions / 63 transitions checked, 63 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (incl. 4 variants), 0 missing
- validations[] conditions: 41 checked, 41 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 61 checked, 61 expressed, 0 missing
- entities[].fields[] structured content: 112 checked, 112 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (countersign ACCEPT/DECLINE, audit CLEAN/OVERBILLED,
  settle RECOVERED/WRITTEN_OFF, decide UPHOLD/REJECT, reconcile fork, validate fork, 4 normalization
  outcomes, 2 gross variants, 2 savings bases), 9 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 966
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Note for the orchestrator

One deliberate scaffold-over-skill choice: the skill's generic contract says lists default to `created_at` **ascending**, but this scaffold states `created_at DESC` ("newest first") in 13 endpoint descriptions. I followed the scaffold — §2.3 and the §4 preamble both state descending. If the test generator assumes the skill's generic default, this is the one place PRD and suite could diverge.

Neither withheld design file was opened, no sibling task directory was touched, `worklog.md` was not modified, and `.scratch/step4` was removed while leaving `.scratch/` intact.

Orchestrator verification: `wc -l` = 476; `tail -6` ends at the final `ERR_MEMBER_PAYOUT_HELD | 409` table row, i.e. the complete §5 catalogue — a real section boundary, not mid-sentence. Grep for "harder than expert / expert level / scaffold / benchmark / difficulty" over PRD.md returned zero hits, so the Step 2 difficulty directive did not leak.

## Step 6: Generate implementation — 2026-09-06T01:32:58.000Z

(Recorded before Step 5 because the two ran concurrently and Step 6 returned first; Step 5 entry follows.)

Subagent summary (verbatim):

Implementation complete and verified.

## Module layout (23 files, 3357 lines)

| file | lines | role |
|---|---|---|
| `app.py` | 72 | Flask app, 4 blueprints, `ApiError`→envelope handler, `store.LOCK` request serialization, `PORT` bind |
| `store.py` | 167 | in-memory `Store` (13 dicts), logical clock, `new_record`/`touch`/version discipline, date/instant helpers |
| `errors.py` | 120 | `ApiError` + all 52 PRD §5 ids with pinned statuses |
| `shapes.py` | 207 | ladder step 7 (body shape) + step 8 (pagination) |
| `authz.py` | 111 | ladder steps 1–3, `@endpoint`, `resolve`/`find`, member & distributor scoping |
| `serializers.py` | 91 | pinned response projection per entity |
| `envelope.py` | 43 | meta/`req_` id/`response_type`/`has_more` |
| `money.py` | 42 | round-half-up vs floor-toward-zero, bps constants |
| `pageutil.py` | 15 | ordered+paginated list read |
| `svc_common.py` | 177 | navigation + counter recomputation |
| `svc_norm.py` | 110 | key resolution, 4-way line classification, renormalize reset |
| `svc_accrue.py` | 189 | rate-card selection, tiered marginal/blended, split waterfall, reversal |
| `svc_audit.py` | 100 | cost-plus markup audit, floored recovery allocation with remainder pass |
| `svc_close.py` | 106 | period close: rebase to `BLENDED_PERIOD`, pay, refreeze snapshot |
| `svc_compliance.py` | 119 | review figures + 4-branch verdict, breach, 5-hop deal-loss cascade |
| `svc_savings.py` | 103 | realized vs opportunity, both bases |
| `svc_clock.py` | 56 | clock advance + letter/rate-card expiry |
| `routes_reference.py` | 361 | tiers, distributors, members, authorization letters |
| `routes_deals.py` | 335 | deals, contracted items, rate cards |
| `routes_feed.py` | 325 | batches, lines, normalize/accrue/audit/recovery |
| `routes_rebate.py` | 497 | claims, accrual validation, close-period, disputes, reviews, savings, clock |
| `start.sh` | 10 | guarded pip, `exec python3 app.py`, reads `$PORT`, 0.0.0.0, foreground |

## Endpoint coverage: 61 / 61

Machine-diffed Flask's `url_map` against the PRD §4 table: both sides are exactly 61 (method, path) pairs and they match 1:1 (the only textual difference is `<id>` vs `{id}` placeholder syntax). Error catalogue also machine-checked: 52 PRD ids = 52 in `errors.py`, zero extra, zero missing; 39 raised as literals plus the 13 `*_NOT_FOUND` raised from the `authz._COLLECTIONS` table.

## State machines implemented

Member enrollment (PENDING/ACTIVE/SUSPENDED/TERMINATED + one-way `reconciliation_posture` CLEAR→RESTRICTED and `payout_hold`); distributor ACTIVE→SUSPENDED (terminal, no path back); letter SUBMITTED→ACTIVE/DECLINED→REVOKED/EXPIRED; deal DRAFT→ACTIVE↔SUSPENDED→LOST (terminal); item ACTIVE→DELISTED (terminal); rate card PROPOSED→APPROVED→SUPERSEDED/EXPIRED; batch's two **parallel** dimensions — `normalization_status` (RECEIVED→NORMALIZED→ACCRUED, renormalize back to RECEIVED) and `audit_status` (NOT_AUDITED→AUDIT_CLEAN|AUDIT_OVERBILLED→RECOVERY_REQUESTED→RECOVERED|WRITTEN_OFF); line UNMATCHED/MATCHED/AMBIGUOUS/EXCLUDED; accrual ACCRUED→VALIDATED/FLAGGED→DISPUTED→PAID/REVERSED; claim SUBMITTED→RECONCILED|VARIANCE_FLAGGED|SUPERSEDED; dispute OPEN↔EVIDENCE_REQUESTED→UPHELD/REJECTED. Cascades: member terminate (2 hops), dispute UPHOLD (4 hops incl. posture flip + batch payout holds), deal loss (hops 1, 2, 3, 3b, 4).

## Calculations implemented

41-step validation ladder (first failure wins); 5-step split waterfall (frozen `ytd_net_snapshot_cents` vs 5,000,000 band → admin fee → net → member share → retention as residual); dual-variant tiered volume (`MARGINAL_BATCH` per-batch ladder with straddle split at accrue time vs `BLENDED_PERIOD` one period-wide rate at close, `final_adjustment_cents` as the signed delta); rate-card selection (APPROVED, closed interval, `effective_from` DESC then `created_at` ASC); cost-plus ceiling `base + round_half_up(base × min(contracted_markup_bps, markup_cap_bps))`, per-case excess floored at 0; floored proportional recovery allocation with a one-cent-at-a-time remainder pass ordered by overbilling DESC then member `created_at` ASC; claim and accrual variance (floored bps, 200 bps tolerance); compliance review (inclusive `window_days`, prorated commitment round-half-up over 365, floored ratio, DEAL_LOST→PASS→WARN(−500)→BREACH); savings report both bases; optimistic concurrency on item/deal versions; segregation of duties on four `*_by_user_id` fields.

## Smoke test (port 21008, killed by PID)

21 scenarios, all as expected: 401 on missing/unknown role; tier create 201 with `reversal_posture_limit` defaulting to 2; 409 duplicate tier code; 422 unbalanced split; 422 `ERR_MEMBER_HAS_NO_ACTIVE_LOA` before any letter; letter → distributor-scoped countersign → both `active_letter_count`s to 1 → member activate; 412 `ERR_STALE_PARENT_VERSION`; rate-card approve pinning `pinned_item_version` **before** the item version advances; deal activate; batch → line → normalize (line matched on `KEY-1`) → accrue. Arithmetic verified by hand against the PRD: gross 2500, admin fee 25 (low band, snapshot 0), net 2475, member share 1733 (half-up on the exact .5), retention 742 as residual; markup audit 5650 overbilled from `min(300,500)` bps ceiling 4635 vs invoice 5200; review `window_days` 31, prorated 8,493,151, ratio 61 bps → BREACH. Pagination meta correct, `limit=0` → 400 `ERR_INVALID_PAGINATION`, unknown member → 404 `ERR_MEMBER_NOT_FOUND`, clock endpoint returns `{current_utc, letters_expired, rate_cards_expired}` and every later `api_request_timestamp` follows the logical clock.

Separately, a 3-round reboot test on port 31740 confirmed a clean fresh boot in **0.6–0.8 s** each time with `total_count` back to 0 on every boot (per-test-server isolation is safe) and no data files written to disk. Both smoke servers confirmed dead; `.scratch/step6` removed, sibling `.scratch/step5` untouched. `AST_OK` on all 23 `*.py`.

## PRD ambiguities resolved (for Steps 8/9)

1. **Tiered `min_cases` indexing** — chose *1-indexed cumulative position, and the case whose position equals `min_cases` earns that tier's rate*. Rationale recorded in `svc_accrue._rate_for_position`: it is the only reading self-consistent with the declared `BLENDED_PERIOD` rule, which compares the period-wide **total** to `min_cases`.
2. **`pinned_item_version` on approve** — pinned to the item's version *as observed at approval*, before the approval's own `touch(item)` advances it.
3. **`settle-recovery` payload** — `recovered_cents` is required for `RECOVERED` and must be **omitted** for `WRITTEN_OFF`; supplying it in the write-off case is `ERR_INVALID_REQUEST`.
4. **Zero-denominator variance** — where a variance ratio would divide by zero, 0 vs 0 yields 0 bps and 0 accrued against a non-zero claim yields the maximum 10000 bps.
5. **Member reinstatement** — clears `payout_hold` but never `reconciliation_posture`; RESTRICTED is one-way and survives every reinstatement.
6. **`EXCLUDED` block reason** — `ITEM_DELISTED` when every key candidate is delisted, otherwise `DEAL_NOT_ACTIVE`.
7. **Renormalize guard** — refused once the audit dimension has reached RECOVERY_REQUESTED/RECOVERED/WRITTEN_OFF, or when an ACCRUED batch holds any VALIDATED/DISPUTED/PAID accrual.
8. **`close-period` and `savings-report`** — per SCAFFOLD's priority-22 `applies_to`, neither runs a period-bounds check.
9. **Unexpected exceptions** — surface as HTTP 500 `ERR_INTERNAL` with a stderr traceback rather than being disguised as a declared 4xx, so any real defect is loud during Step 7.

## Step 5: Generate unit tests — 2026-09-06T01:50:19.000Z

Subagent summary (verbatim):

Step 5 complete. Both mandatory audit passes are clean.

## Deliverables

**`test_helpers/` — 9 files, 2157 lines** (task root, imports cleanly)

| file | lines |
| --- | --- |
| `__init__.py` | 84 |
| `api_client.py` | 294 |
| `api_errors.py` | 116 |
| `assertions.py` | 347 |
| `constants.py` | 113 |
| `factories.py` | 270 |
| `fixtures.py` | 573 |
| `test_users.py` | 77 |
| `types.py` | 283 |

**`test_suite/` — conftest + 15 test files, 12356 lines, 205 test functions (219 collected cases with parametrization)**

| file | lines | tests |
| --- | --- | --- |
| `conftest.py` | 67 | — |
| `test_01_dual_variant_rebate_and_savings.py` | 428 | 9 |
| `test_02_combinatorial_formulas.py` | 480 | 6 |
| `test_03_state_machines_and_cascades.py` | 524 | 10 |
| `test_04_priority_and_boundary.py` | 604 | 9 |
| `test_05_cross_entity_and_temporal_windows.py` | 684 | 9 |
| `test_06_compensating_invariants.py` | 486 | 9 |
| `test_07_entity_contracts.py` | 1089 | 22 |
| `test_08_lifecycle_transition_corners.py` | 793 | 15 |
| `test_09_cascade_transition_corners.py` | 687 | 10 |
| `test_10_calculation_corners.py` | 1144 | 16 |
| `test_11_validation_corners.py` | 1143 | 20 |
| `test_12_endpoint_and_consistency_corners.py` | 960 | 18 |
| `test_13_error_corners.py` | 1381 | 30 |
| `test_14_rbac_corners.py` | 1114 | 12 (26 cases) |
| `test_15_cross_cutting_corners.py` | 772 | 10 |

## Design-index coverage

- **Queue A (§1.8 difficulty): 19 / 19 instances consumed, 0 skipped** (all 9 rule_ids; the index carries no stubs).
- **Queue B (§1.9 corner): 60 / 60 non-stub instances consumed, 0 skipped** across `entities` 12, `state_machines` 11, `calculations` 6, `validations` 10, `endpoints` 5, `errors` 7, `rbac` 5, `cross_cutting_complexity_layers` 3, `consistency_model` 1.
- **79 distinct instances covered; audit reports 0 uncovered and 0 problems.**
- **Skipped: only the 11 `excluded_because:` stubs**, each of which the yaml itself redirects to an already-covered §1.8 instance: `batch_normalization_and_audit_dimensions_move_independently`, `deal_loss_cascade_delists_items_and_expires_cards`, `tiered_volume_ladder_splits_a_straddling_line`, `both_opportunity_bases_diverge_on_the_same_lines`, `closing_the_period_reconciles_the_marginal_accruals`, `admin_fee_band_is_chosen_from_the_frozen_snapshot`, `enrollment_gate_outranks_the_case_quantity_gate`, `claim_reconciliation_gate_outranks_the_payout_hold_gate`, `overlapping_authorization_letter_windows_are_rejected`, `the_four_hop_dispute_upheld_cascade_reaches_every_dependent_row`, `both_accrual_variants_produce_their_declared_totals`. **No instance was dropped for failing the PRD-first filter** — no gaps.

## Verification performed

- Audit pass 1 (design citation): every test has exactly one `Design:` line as the docstring's final line; every `rule_id`/`section` + `instance.name` resolves to a real non-stub entry in the corresponding yaml.
- Audit pass 2 (PRD citation): each docstring carries at least one ≥25-char quoted fragment that is a verbatim (whitespace-normalized) substring of `workspace/PRD.md`.
- `pytest --collect-only` collects 219 cases with zero import/collection errors; `import test_helpers` succeeds.
- No mocking, no `monkeypatch`, no `time.sleep`, no `skip`/`xfail`, no module-level API calls; the only session-scoped fixture is the stateless `api` client in `conftest.py`.
- Money is integer cents everywhere except one deliberate `"20000000"` negative probe in test_07 (mistyped-field → `ERR_INVALID_REQUEST`); all instants carry exactly three fractional digits.
- Nothing written under `workspace/`; `workspace/implementation/` never read or listed; `worklog.md` untouched by me; `test_suite/__pycache__` and `test_helpers/__pycache__` removed; `.scratch/step5` deleted and the parent `.scratch/` preserved.

## Design-vs-PRD conflicts resolved PRD-first (worth flagging to Step 6/7)

1. **`audit-markup` on a `RECEIVED` batch** — five separate design recipes do this; §3.7 requires `normalization_status` of `NORMALIZED`/`ACCRUED`, so a `normalize` hop was inserted in each setup. All pinned money literals unchanged.
2. **Symbol drift corrected throughout** — yaml's `RATE_APPLIED_WRONG`/`CASES_OVERSTATED` → the PRD's `RATE_MISMATCH`/`UNITS_MISMATCH`/`ITEM_MISMATCH`/`TIER_MISMATCH`; `cases_credited` → `accrued_cases`; `reversal_reason is null` → `"NONE"`.
3. **Unnamed list filters** — §4 declares lists "filterable by…" without naming params, so tests filter client-side over a wide page (`limit=100`) rather than inventing `?status=`.
4. **Absolute version literals replaced by relative deltas** where a §2.4 parent bump made the design's pinned `version == 2` unreachable.
5. **`tier_code` literals** `EDGE-LOW`/`OVER`/`UNDER` remapped to the declared enum (`CORE`/`PLUS`/`ELITE`) so the requests reach the bps-balance rung instead of dying at rung 7.
6. **One unreachable reconcile path** in test_04 rerouted through a restatement at the post-reversal amount to reach `ERR_MEMBER_PAYOUT_HELD`.
7. Two derivations resting on clause order rather than an explicit number are documented in-test: `pinned_item_version` as the pre-increment value, and `ERR_BATCH_NOT_FOUND` (not a scope violation) for an unknown batch id sent by a `DistributorFeed`.

## Step 7: Run tests and iterate — 2026-09-06T02:11:48.000Z

Subagent summary (verbatim):

Step 7 complete: all 8 rounds green at 219/219.

## Summary

**Iterations run:** 2 full 8-round sweeps.

**Iteration 1** — 219 total, 204 passed, **15 failed** identically in all 8 rounds (fully deterministic, so no load-induced flakiness to discount). The 15-test union traced to exactly three root causes.

**Tests deleted:** none. Every one of the 15 failures traced to a verbatim PRD sentence that uniquely determines the expected behaviour, so no PRD-silence deletion was warranted. No assertion was weakened, no test skipped or xfailed.

**Fixes to `test_helpers/` (1 file):**
- `test_helpers/factories.py` — variant factories `fries_line_payload`, `chicken_line_payload`, `fries_item_payload`, `chicken_item_payload`, `july_batch_payload`, `second_deal_payload`: they passed their fixed field values as explicit keyword arguments *and* splatted `**overrides` into the same call, so overriding any variant-set field raised `TypeError: ... got multiple values for keyword argument`. Each now builds the base payload then applies `payload.update(overrides)`, so overrides win. (Fixed 2 tests in `test_07_entity_contracts.py`; the other four factories had the same latent defect and were fixed alongside.)

**Fixes to `implementation/` (2 files):**
- `workspace/implementation/svc_accrue.py`, `tiered_marginal` / `_rate_for_position` — marginal ladder was off by one case: it priced each case at its 1-indexed cumulative position (`prior_cases + offset + 1`) instead of the cumulative volume lying *before* it, so the case that crosses a `min_cases` break was paid at the higher tier one case early. PRD §3.4 says "the cases falling below the threshold are paid at the lower tier's rate and the cases at or above it at the higher tier's". Line B now pays 20×120 + 20×180 = 6000 (was 6060); the 25,000-case case now gives 6,233,000 (was 6,233,130). `tiered_blended` compares the period-wide total to `min_cases` directly and was left untouched. (Fixed 11 tests, including the downstream fee/share/retention, close-period rebase, savings-basis and snapshot assertions.)
- `workspace/implementation/routes_rebate.py`, `create_dispute` — the priority-11 state gate refused anything outside `ACCRUED/VALIDATED/FLAGGED`, which made priority 38 `ERR_DUPLICATE_OPEN_DISPUTE` unreachable dead code (opening a dispute always moves the accrual to `DISPUTED`). PRD §3.6 names exactly `REVERSED` or `PAID` as the statuses drawing `ERR_INVALID_STATE`, so the gate now refuses only those two and a `DISPUTED` accrual falls through to the duplicate check. (Fixed 2 tests in `test_13_error_corners.py`.)

**Iteration 2 — final per-round results (all 8 rounds identical):**

| round | passed / total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 219 / 219 | 0 | 0 | 0 |
| 2 | 219 / 219 | 0 | 0 | 0 |
| 3 | 219 / 219 | 0 | 0 | 0 |
| 4 | 219 / 219 | 0 | 0 | 0 |
| 5 | 219 / 219 | 0 | 0 | 0 |
| 6 | 219 / 219 | 0 | 0 | 0 |
| 7 | 219 / 219 | 0 | 0 | 0 |
| 8 | 219 / 219 | 0 | 0 | 0 |

Union of failing tests across all 8 rounds: empty.

Housekeeping: no endpoint, field, side effect or capability was added to `implementation/`; storage remains in-memory dicts only, with no on-disk state (the only non-source files in `implementation/` are the runner's own `results.*.json`). `__pycache__` cleaned, `.scratch/step7` removed (parent `.scratch/` left intact), and `worklog.md` was not touched.

Orchestrator verification: independently re-read all 8 `results.$i.json` — every round reports 219/219. Step 7 applied 2 `implementation/` fixes, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-06T02:16:44.000Z

Subagent summary (verbatim):

`workspace/PRD_FINALIZED.md` is written.

## Size delta
- PRD.md: 476 lines / 100,072 bytes → PRD_FINALIZED.md: 476 lines / 100,882 bytes.
- Line count delta: 0 (0.00%); byte delta +810 (+0.81%). Three inline prose edits, no new sections, no removed sentences.

## Changes
- **§3.4 (accrual, `MARGINAL_BATCH` ladder)** — insert — after the existing straddle sentence, pinned the per-case boundary arithmetic: a case is priced by the last tier whose `min_cases` is ≤ the cumulative case count laid into the ladder *strictly before* that case, so the case that carries the total up to a `min_cases` is still priced by the preceding tier and the next case is the first at the new tier; illustrated with "a tier whose `min_cases` is 50 first prices the fifty-first case". — `implementation/svc_accrue.py:41-66` (`_rate_for_position`, `tiered_marginal`).
- **§3.9 (close, `BLENDED_PERIOD` rebase)** — revise — the single rate is "the last tier whose `min_cases` is at or below that total, so a total that merely reaches a tier's `min_cases` is already enough to select it", plus one clause stating the marginal per-case position rule plays no part here. — `implementation/svc_accrue.py:69-78` (`tiered_blended`), called from `implementation/svc_close.py:60`.
- **§3.6 (dispute filing, priority-11 gate)** — revise — contestability is now "any `status` other than `REVERSED` or `PAID`, and those two alone are refused as `ERR_INVALID_STATE`, so an accrual already sitting at `DISPUTED` passes this particular gate and is left to the gates that follow it" (replacing the `ACCRUED`/`VALIDATED`/`FLAGGED` enumeration, which made priority-38 `ERR_DUPLICATE_OPEN_DISPUTE` unreachable). — `implementation/routes_rebate.py:240-241`.

The `test_helpers/factories.py` fix (variant factories passing fixed kwargs *and* `**overrides`) is a pure fixture bug with no behavioral content, so it produced no PRD edit.

## Per-edit pre-edit search log

**Edit 1 — marginal ladder boundary**
- (a) Subject: the threshold convention used to pick a tier rate for a single case in `TIERED_VOLUME`.
- (b) Enumerated/read: `svc_accrue.py` `_sorted_breaks`, `_rate_for_position`, `tiered_marginal`, `tiered_blended`, `gross_for_line` (both callsites: `accrue_batch` with `cumulative_prior`, `svc_close.close_period` with `blended_total` — so marginal never runs at close), `accrue_batch`'s `cumulative` accumulation over MATCHED lines, `routes_deals.py:204-228` `tier_breaks` structural validation (first `min_cases` must be 0, strictly increasing → my "last tier whose `min_cases` ≤ …" is always well-defined and array order equals `_sorted_breaks` order), `svc_savings.savings_report` (uses stored `member_share_cents`, no ladder of its own), `money.py` rounding helpers. Cross-checked against fixture arithmetic 50×120 + 150×180 + 24800×250 = 6,233,000 and 20×120 + 20×180 = 6000.
- (c) Adjustment: first draft said "a `min_cases` of 50 leaves exactly 50 cases priced below that tier" — dropped, because a ladder that never receives 50 cases makes that a false universal; replaced with the position-based "first prices the fifty-first case laid into that ladder". Wording deliberately scoped to "case by case" so it cannot be read onto the blended variant, and phrased as "preceding/new tier" (ladder position) rather than "lower/higher rate", since the PRD only requires `rate_cents_per_case ≥ 1` and does not force rates to increase.

**Edit 2 — blended rate selection boundary**
- (a) Subject: the same threshold convention, but for the period-wide total in `BLENDED_PERIOD`.
- (b) Enumerated/read: `svc_accrue.tiered_blended` (`min_cases <= period_total_cases`, inclusive), `svc_close.blended_case_total` (MATCHED lines, member+item, inclusive date range), `svc_close.close_period` (rebase set `ACCRUED`/`VALIDATED`/`FLAGGED`, frozen `admin_fee_bps_applied` reused, `final_adjustment_cents` delta, payment and snapshot refreeze), `gross_for_line` dispatch, `routes_rebate.close_deal_period`.
- (c) Adjustment: kept the clause purely about rate selection (inclusive `min_cases`) and added the explicit disclaimer that the marginal per-case rule does not apply here, so Edit 1 cannot be generalized to blended; said nothing about the rebase set, statuses, or snapshot so no adjacent close-period behavior is re-described.

**Edit 3 — dispute contestability gate**
- (a) Subject: the accrual-status precondition on `POST /disputes` and the reachability of `ERR_DUPLICATE_OPEN_DISPUTE`.
- (b) Enumerated/read: `routes_rebate.create_dispute` in full (priority order 5 → 9 → 11 → 12 → 24 → 38 → 40), `decide_dispute` REJECT branch (restores `accrual_status_before`) and UPHOLD branch (`DISPUTED → REVERSED`), `request_evidence`/`submit_evidence` (accrual stays `DISPUTED`), `svc_accrue.reverse_batch_accruals` (touches only `ACCRUED`/`FLAGGED`, leaves `DISPUTED` alone), `svc_close.close_period` (rebases/pays only `ACCRUED`/`VALIDATED`/`FLAGGED`), `validate_accrual` (`ACCRUED` only), `svc_savings.REALIZED_ACCRUAL_STATUSES`; PRD grep for every `DISPUTED` and `ERR_INVALID_STATE` mention (lines 123, 243, 261, 285, 287, 291, 293, 343 and the error table) to confirm none is contradicted — in particular §3.6's "`accrual_status_before` … one of `ACCRUED`, `VALIDATED` or `FLAGGED`" stays true, since a `DISPUTED` accrual always has a live dispute and so never reaches the store step.
- (c) Adjustment: first draft said a `DISPUTED` accrual "is caught by the duplicate gate instead" — softened to "is left to the gates that follow it", because priority 24 (`ERR_DISPUTE_WINDOW_CLOSED`) can fire before the priority-38 duplicate check; the softer wording stays true on every ordering.

## Step 9: Complete PRD — 2026-09-06T02:52:32.000Z

Orchestrator decision: Step 9 was run as FOUR sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module, rather than one monolithic pass. Rationale: a single agent scanning a 476-line PRD against 23 implementation modules reliably under-scans, and the failure is silent (a byte-identical or barely-changed output). Pass 1 alone performed the `cp`; passes 2–4 edited in place with targeted Edit calls only. Pass 4 was a narrow reconciliation pass over the cross-pass contradictions the first three reported — partitioned passes report contradictions rather than fixing them, so a closing pass is required.

Cumulative result: PRD_FINALIZED.md 476 lines / 100,882 chars → PRD_COMPLETED.md 476 lines / 115,589 chars (+14,707 chars, +14.6%), 48 changed lines, no new sections, no line-count change.

### Pass 1 — infrastructure and cross-cutting layer (app, store, errors, shapes, authz, serializers, envelope, money, pageutil, svc_common)

7 ambiguity-pins, 0 mismatch-revisions. PRD_FINALIZED 100,882 chars → 105,349 chars.
- §2.2 `api_request_id` — revise — suffix pinned to exactly 20 chars from `A`–`Z`/`0`–`9` — envelope.py:14
- §2.2 `data` — insert — fixed per-type property set; internal bookkeeping never exposed; a declared-but-unset property is JSON `null`, not omitted — serializers.py:85-87
- §2.3 ¶1 — insert — `limit`/`offset` digit-run parsing; undeclared query params ignored not rejected; declared filter is raw-text exact equality so an unmatched value yields empty `data` with `total_count` 0 — shapes.py:180-207, routes_reference.py:25-32
- §2.3 ¶2 — insert — the `created_at` tie-break: because `created_at` is the frozen logical clock, ties are the norm; the server's monotonic creation sequence breaks them (later-created first under DESC, last under ASC), for list reads and §3's ascending walks alike — store.py:125-136. Verified against every ordering site (store.sort_desc/sort_asc, svc_common.py:41-46, svc_accrue.py:28-29, svc_audit.py:89): all use `_seq` ascending as final key, none uses `id`.
- §2.4 ¶2 — insert — `version` advances at most one step per record per request, however many fields or cascade hops touch it — store.py:106-118 (`_touched` dedupe reset by `store.begin_request`)
- §2.7 ladder step 7 — insert — scalar range/length/charset/format constraints §3 states without a dedicated code report `ERR_INVALID_REQUEST` here; the five that own a code are excluded; absent/empty/`{}` body passes when nothing is required; non-object JSON fails; explicit `null` fails a required field but takes the default on an optional one — shapes.py:93-167
- §2.11 ¶1 — insert — client instants accepted in any offset-fixing ISO 8601 form, converted to UTC and rewritten to canonical 3-digit form before storage/echo — shapes.py:20-21, store.py:56-62/159-167
Verified programmatically: §5's error-id→HTTP table is byte-for-byte identical to `errors.ERROR_HTTP` across all 52 entries; §2.6's rounding prose already pins half-up-away-from-zero and truncate-toward-zero exactly as money.py implements.

### Pass 2 — domain service layer (svc_norm, svc_accrue, svc_audit, svc_close, svc_compliance, svc_savings, svc_clock)

13 ambiguity-pins, 4 mismatch-revisions (17 edits / 16 lines). 105,349 → 110,447 chars; pass 1's 7 lines confirmed still intact.
- §2.11 — insert — clock moves before the expiry sweep, so every aged-out letter/card and every counter-decremented parent carries the new `current_utc` — svc_clock.py:12-13,24
- §3.3 — insert ×4 — a visited line advances `version` in all four branches incl. the unchanged `UNMATCHED`/`NONE` one; `last_purchase_date` is the greatest date across every `MATCHED` line system-wide and written only on change; manual mapping writes nothing else; renormalization rewrites every line — svc_norm.py:58,61-73,91,96-101
- §3.4 — insert — marginal ladder is keyed on (batch, item) with no member dimension; every `MATCHED` line lays cases in, including one resolving no card — svc_accrue.py:132-145
- §3.4 — revise — MISMATCH — straddle "the cases at or above it" → "the cases beyond it", which contradicted the same paragraph's 51st-case rule — svc_accrue.py:41-57
- §3.7 — insert ×2 — every visited line is written whether or not `overbilled_cents` moved; every participating member is written even when its slice floors to 0 — svc_audit.py:31-32,50,98-100
- §3.8 — revise ×2 — MISMATCH — "six figures" → "five" in both locations (serializer confirms five plus `result`) — svc_compliance.py:55-62, serializers.py:76-81
- §3.8 — insert ×2 — the review endpoint has no ACTIVE-member gate, so a BREACH on a PENDING/SUSPENDED/TERMINATED member is recorded and changes nothing; nothing beyond the four deal-loss hops moves — svc_compliance.py:65-71,74-119
- §3.9 — insert ×4 — all three rebase rewrites land on every touched accrual (so a PER_CASE/PERCENT_OF_SPEND accrual gets `final_adjustment_cents` 0 and basis BLENDED_PERIOD); "affected member" = owner of ≥1 touched accrual, each advancing `version` once even with all-zero deltas; "accruals in the period" is decided by the line's `invoice_date`; the FULL_BASKET cheapest-item lookup ignores item/deal status and breaks a cost tie on earlier `created_at` — svc_close.py:56,60,72-74,85; svc_savings.py:20-26,44-53
Handoff verdict on `serializers.FIELDS` vs §3 prose: exact match for all nine of PurchaseLine, PurchaseBatch, RebateAccrual, Member, ManufacturerDeal, ContractedItem, RateCard, AuthorizationLetter, Distributor; ComplianceReview's field list correct but §3.8's prose miscounted the frozen figures — revised.

### Pass 3 — HTTP route layer (routes_reference, routes_deals, routes_feed, routes_rebate)

12 ambiguity-pins, 13 mismatch-revisions. 110,447 → 114,992 chars; all 23 lines from passes 1+2 confirmed still modified. Walked all 61 endpoints; a scripted cross-check confirmed impl paths/methods/role-lists match the §4 table exactly on all 61.
- §2.1 — insert ×2 — the step-5/step-6 scope asymmetry: letter submission and batch open compare the raw body's `member_id`/`distributor_id` (absent/non-string ⇒ scope violation, not a body error), while dispute creation and line ingest take no scope decision when their parent id does not resolve — routes_reference.py:248, routes_rebate.py:226-228, routes_feed.py:34,229-231
- §2.7 step 7 — insert — MISMATCH — the blanket unknown-field rejection was a false universal: the 14 action endpoints that declare no body field never examine the body. Enumerated exactly.
- §3.2 — revise/insert ×3 — a `tier_breaks` entry must be an object with exactly the two integer keys (⇒ `ERR_RATE_CARD_SHAPE_INVALID`, not step 7); `supersede` optional defaulting false; approving a card on a DELISTED item draws `ERR_INVALID_STATE` ahead of the deal gate — routes_deals.py:213-220,243,251,323-326
- §3.6 — revise ×2 — `evidence_note` and `decision_note` are 1–500 chars; `evidence_note` is not a stored dispute property — routes_rebate.py:321,336
- §3.7 — insert — settle-recovery: both halves of the `recovered_cents`/`outcome` coupling are step-7 checks reported ahead of the state gate; the key counts as supplied when explicitly `null`; `recovered_cents` must be ≥ 0 — routes_feed.py:163-176
- §3.9 — insert — MISMATCH — close-period applies neither step 22 nor any deal-status gate; an inverted period is accepted, selects nothing, still bumps the deal's `version`; DRAFT/SUSPENDED/LOST deals may be closed — routes_rebate.py:201-208
- §3.9 — revise — savings report: `period_start`/`period_end` required query params, `basis` optional defaulting to `AS_PURCHASED`, bounds shape-checked only, not a collection so no pagination — routes_rebate.py:465-486
- §4 — insert/revise ×14 rows — MISMATCH — 3 list rows named no filter at all and 8 omitted declared filters (`reconciliation_posture`, `scope`, `rate_type`, `accrual_block_reason`, `basis`, `reason_code`, …); all now name their exact parameter strings, all optional, combining conjunctively.

### Pass 4 — reconciliation

4 edits, all closing cross-pass defects the first three passes reported rather than fixed.
- **A (verdict: CONFIRMED, fixed).** §2.7 step 22's "**every** period, window or effectivity range is correctly ordered" was a live false universal. Traced every `ERR_PERIOD_BOUNDS_INVALID` site: exactly six ranges enforce it (deal and rate-card `effective_to<effective_from`; letter `effective_to<=effective_from`, strict/half-open; batch, claim, and compliance-review period bounds) and exactly two endpoints apply none (`close_deal_period`, `member_savings_report`). Step 22 now scopes itself to the six declared ranges and explicitly excludes the close and the savings report — routes_deals.py:50,271, routes_reference.py:278, routes_feed.py:45, routes_rebate.py:56,418 vs routes_rebate.py:201-208,465-486
- **B (verdict: repaired, wording only).** Line 119 was co-owned by passes 1 and 3; pass 1's universal was retroactively hedged by pass 3's follow-on. Scope moved to the front of pass 1's sentence so pass 3's rule states directly; both passes' content preserved. Verified the 14 no-body POST routes named are precisely the 14 that never call `parse_body` (`countersign` correctly excluded — it declares `decision`).
- **C (verdict: agree with pass 1, nothing added).** The `HTTPException` handler can only fire off the documented surface — `get_json(silent=True, force=True)` means malformed JSON and a wrong `Content-Type` degrade to `{}` and report a normal 400 `ERR_INVALID_REQUEST`, leaving only unrouted URLs (404) and undeclared methods (405). `strict_slashes = False` is unobservable since no documented request carries a trailing slash. Documenting either would add a non-requirement.
- **D (verdict: two real defects found, both universal-quantifier class; no structural damage).** §2.3's "optionally sign-prefixed run of decimal digits" was false — the impl accepts only a leading minus and strips surrounding whitespace, so a `%2B`-encoded `+5` draws `ERR_INVALID_PAGINATION` (shapes.py:176-190). §3.7's "every participating member is written by the settlement" was violated at `recovered_cents` 0, which another pass had just declared legitimate — `allocate_recovery` returns before touching anyone (svc_audit.py:60-62). Both scoped. Re-verified all 47 prior changed lines against the impl; the line-91 "one version step per request" universal holds (`touch()` keys on `id(rec)` against a per-request `_touched` set).
- **E (verdict: all pass).** 476 lines; final line is the complete last §5 row `| ERR_MEMBER_PAYOUT_HELD | 409 |`; §4 has all 61 endpoint rows and §5 all 52 error rows with no malformed pipe counts; `cmp -s` vs PRD_FINALIZED.md reports DIFFERENT; and all nine forbidden meta strings ("harder than expert", "expert level", "SCAFFOLD", "scaffold", "benchmark", "difficulty", "test_suite", "test_helpers", "pytest") return 0 hits.

### Orchestrator final verification

- `PRD_COMPLETED.md` is 476 lines / 115,589 chars, 48 lines differing from `PRD_FINALIZED.md`, and is NOT byte-identical to it (the Step 9 failure mode is a no-op scan; it did not occur).
- Tail confirms the file ends at the complete final §5 error row — no truncation.
- All 8 `results.$i.json` re-read after Step 9: every round 219/219. Step 9 touched only `PRD_COMPLETED.md`, so the green sweep still describes the shipped implementation.
- Exactly one `worklog.md` exists, at the task root; no stray copies drifted into `workspace/`. `.scratch/` was removed by the passes with no sibling artifacts lost.
- `workspace/sweep.sh` is retained deliberately: it documents the exact reap-proof 8-round invocation (setsid + `SWEEP_DONE` sentinel) used for Step 7. The interleaved `sweep.log` and the `SWEEP_DONE` sentinel were deleted as non-artifacts.

PIPELINE COMPLETE.
