# Worklog — task_3337_franchise_mobile_tool_truck_routes_customer_credit

## Step 1: Create Task Directory — 2026-09-30T21:32:17.000Z

Used the pre-allocated task directory `./tasks/task_3337_franchise_mobile_tool_truck_routes_customer_credit/` exactly as instructed (did not compute a new index). Verified `workspace/` already exists inside it. No other `task_*` directory was created.

## Step 2 (attempt 1): Generate Scaffold — INTERRUPTED 2026-10-01T04:0x:xxZ

The Step 2 scaffold subagent was stopped mid-flight when the host killed background processes under memory pressure. Post-interruption inspection on 2026-10-01T04:07:20Z found:

- `SCAFFOLD.yaml` — present, 2518 lines, 141914 bytes. Parses cleanly as YAML. All §1.0–§1.7 sections present and structurally complete (clean final section, `roles:` last top-level key): scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities (15), state_machines (11), concurrency_rules, calculations (19), validations (22), endpoints (58), errors (64), roles (7). Confirmed NOT truncated. Correctly contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` as top-level keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — MISSING (never written).
- `SCAFFOLD_CORNER_DESIGN.yaml` — MISSING (never written).

Verdict: Step 2 is INCOMPLETE. §1.1–§1.7 are usable as-is; the two design indices (§1.8 / §1.9) must still be produced. Resuming Step 2 by keeping the existing complete `SCAFFOLD.yaml` as the §1.1–§1.7 base and authoring both design-index files against it (the §1.9 walk doubles as the §1.5 empty-DB reachability audit, so §1.5 may be repaired in place via the skill's priority ladder if a gap is found).

## Step 2 (attempt 2): Complete Scaffold — design indices — 2026-10-01T04:36:27.263Z

Resumed Step 2 with the existing complete `SCAFFOLD.yaml` as the authoritative §1.1–§1.7 base, authoring the two missing design indices against it (the §1.9 walk doubling as the §1.5 empty-DB reachability audit).

NOTE ON HAND-BACK: the subagent's final report was truncated mid-sentence ("Now §1.9 batch 3: endpoints, errors, RBAC."), so its own summary was not usable as a verbatim record. The following is therefore the ORCHESTRATOR-VERIFIED state read back off disk, not the subagent's claim.

Files on disk (all three verified present and parsing as valid YAML):
- `SCAFFOLD.yaml` — 2536 lines / 143263 bytes. Top-level keys unchanged: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Confirmed to contain NEITHER `scaffold_difficulty_design` NOR `scaffold_corner_design`. Grew 2518 → 2536 lines (+18) vs the interrupted attempt.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 864 lines / 112570 bytes, single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 938 lines / 126125 bytes, single top-level key `scaffold_corner_design`.

Verification performed by the orchestrator:
- `scaffold_lint.py` (the skill's sibling validator) on the task dir: §1.5 endpoints declared 60 (up from 58 — consistent with §1.5 priority-ladder repairs made during the §1.9 walk), §1.1 entities 15, §1.8 instances scanned 18, §1.9 instances scanned 38, calls scanned 704. VERDICT: **clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.**
- §1.8 depth coverage: 9 rule_id groups × exactly 2 instances each = 18 — dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
- Name uniqueness: 18/18 unique in §1.8, 38/38 unique in §1.9, ZERO duplicates across the union.

Caveat carried forward: the exact per-instance §1.5 repairs the subagent made are not itemized in the truncated hand-back; the 58 → 60 endpoint delta plus the clean lint verdict are the evidence that they landed coherently.

## Step 3: Copy Shared INSTRUCTION.md — 2026-10-01T04:08:01.955Z

Copied `./INSTRUCTION.md` → `./tasks/task_3337_franchise_mobile_tool_truck_routes_customer_credit/workspace/INSTRUCTION.md` (1424 bytes, 53 lines). Bash-only step, no subagent.
## Step 4: Generate PRD — 2026-10-01T04:46:00.000Z

Subagent summary (verbatim, from its final report):

> The PRD is complete and all mechanical contracts pass. Final report:
>
> ## Result
>
> **Output:** `workspace/PRD.md` — **1,409 lines**.
>
> **Section list** (domain-derived skeleton, deliberately not the example's):
> - §1 Introduction (3 paragraphs: the weekly-truck business, the interface scope, the correctness stance)
> - §2 Global Specifications — 2.1 RBAC; **2.2 API Response Structure (verbatim, byte-identical to `section-2.2-response-structure.md`)**; 2.3 Pagination; 2.4 The Logical Clock and the Weekly Cadence; 2.5 Common Resource Properties; 2.6 Nested Resource Retrieval and Validation Order; 2.7 Money, Rounding and Precision; 2.8 Optimistic Concurrency Control on Contended Writes; 2.9 Unique Keys and Protected Fields; 2.10 Franchisee Standing, Certification and Territory Qualification; 2.11 Resale Pricing and the Buyer's Training Discount; 2.12 Route Derivation: Schedule Anchor and Inventory Aggregates; 2.13 Credit Facilities, Lines and Fiscal Ceilings; 2.14 Account Posture, Delinquency and the Charge-Off Anniversary
> - §3 Business Logic — 3.1 Franchisee Standing, Route Lifecycle and Territory Development; 3.2 Shops, Technicians and the Cascade of a Route Suspension; 3.3 Credit Applications: Scoring and Adjudication; 3.4 The Truck's Order Book: Sales Orders, Pricing and Stock; 3.5 Credit Accounts, Recourse, Accrual and Collection; 3.6 Replenishment, Ceiling Fill and Share Pledges; 3.7 Product Launches and Route Allocation; 3.8 Warranty Claims and Tool Replacement at the Truck; 3.9 The Fixed Order of Refusals
> - §4 Endpoint Definitions (60-row table, 4 columns, plus preamble with 201/200 rules and the per-endpoint request-key/query-param narrative)
> - §5 Error Code Catalogue (64-row table, 2 columns, no trigger column)
>
> **§1.1–§1.7 coverage: complete.** §1.1 entities/fields → §2.5/§2.12/§2.13/§2.14 + §3 narratives; §1.2 state machines (11 SMs, 56 transitions) → §3.1–3.8 with every from/to pair, precondition and side-effect; §1.3 calculations (19) → §2.7/§2.11/§2.12 plus §3.3–3.8, each named in backticks; §1.4 validations (22, priority-ordered) → §3.9 states the ladder explicitly, lowest priority number wins; §1.5 endpoints → §4; §1.6 errors → §5 + trigger prose in §2/§3; §1.7 roles → §2.1 with every role's `identity:` translated.
>
> **Hard-contract results (all PASS):**
> - Contract 1 — entities fields 141/141 present; request/body inputs 88/88 present; query params 62/62; path params 3/3 (`id`, `paymentId`, `claimId`). 0 missing.
> - Contract 2 — 22 validation priorities expressed in order; 5/5 OCC rules with write endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412; 56/56 transitions; 19/19 calculations with constants and rounding pinned; 22/22 validation conditions matchable to their error_id; endpoint side-effects/applies_to expressed; field structured content reconstructible; sibling branches (franchisor vs franchisee approval, suspended vs active miss, charge vs credit warranty basis, prior vs settled accrual basis, provisional vs final financing basis) rendered at equal density. 0 missing.
> - Contract 3 — §3 backtick tokens scanned: 322; tokens starting with `/`: 0; bare HTTP methods: 0; method+path combined: 0.
>
> **Literal lock applied:** constants written as exact literals (mixes 1.0075/1.0150/1.0025, tiers 50000/200000, rates 0.1560/0.1820/0.2080, 52 weeks, score base 40 / weights / clamp 1–100, limit tiers 750/500/250 over score bands 40/60, rate ceiling 500000, 26-week charge-off window, anchor `08:00:00Z` strict, FEE_NOT_ENROLLED 900000 / FEE_ENROLLED 650000 / FEE_CERTIFIED 250000, 10 points per discount unit capped at 60, 15000 per unit, floor 200000, cap 900000, CAP_RATE 0.40, CREDIT_RATE 0.60, TIER_WEIGHT A3/B2/C1, RISK_LOW 120 / RISK_MEDIUM 60, 25000/150000/0.05/0.10/0.20/2500, lease 0.2400, 1.25 uplift, startup clock `2026-09-01T00:00:00Z`).
>
> **Judged untranslatable to prose (with reason):**
> 1. **`state_machines` SM2's `PENDING_TRANSFER` state** — declared on the `Route.route_status` enum but the scaffold defines no transition into or out of it. Stated as an enum member only; no rule attached, so nothing to assert.
> 2. **The `state_machines[].note` fields marked "see §1.2 … chain below"** — those chain sections live in the withheld design indices; I expressed each cascade's contents directly from the `side_effects` arrays instead, so no rule is lost.
> 3. **`validations[].applies_to` paths use the un-prefixed short form** (e.g. `/routes/{id}/resale`) while the same operations are also listed with the `/retail` prefix elsewhere. I mapped both spellings to the same §4 endpoints and stated each rule's guards in prose; this is a scaffold-internal inconsistency, not a behaviour difference.
> 4. **`calculations[].trigger` and `endpoints[]` `output` shapes** — these are contract metadata, not behavioural rules; they are covered as request-key lists in §4, and the response side is fully determined by §2.2, §2.5 and the entity field prose.
> 5. **`ERR_WARRANTY_ALREADY_CLAIMED`'s "non-terminal" set** — the scaffold does not enumerate which statuses count as non-terminal for the duplicate-filing guard, so I stated the guard without inventing a status list; that is the one wording gap in the scaffold rather than in the PRD.
>
> No scaffold-derived file other than `SCAFFOLD.yaml` was opened, and no sibling task directory was read or listed.

Orchestrator verification: `workspace/PRD.md` present, 1408 lines / 112890 bytes, ends cleanly at the §5 error table. `workspace/INSTRUCTION.md` still present. Sections confirmed: §1 Introduction, §2 Global Specifications & System-Wide Principles, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue. (Subagent reported 1,409 lines; disk shows 1,408 — trailing-newline counting, immaterial.)

Noted for Step 7: item 5 (`ERR_WARRANTY_ALREADY_CLAIMED` "non-terminal" set) is a genuine scaffold wording gap. Orchestrator check of the `WarrantyClaim` SM shows states OPEN/SUBMITTED/APPROVED/REJECTED, where APPROVED and REJECTED each have a reopen transition back to SUBMITTED — so "terminal" is not cleanly defined by outgoing-edge count. If a Step 5 test asserts a specific non-terminal status list, Step 7 should treat it as PRD-ambiguous (STEP 1b collapse) rather than an implementation bug.

## Step 2 (attempt 3): Complete §1.9 corner design — 2026-10-01T05:24:30.000Z

Trigger: the Step 5 subagent reported tags covering only four §1.9 sections (calculations, entities, state_machines, validations). Orchestrator verification confirmed `SCAFFOLD_CORNER_DESIGN.yaml` held only 38 instances across 4 of the claim-extraction guide's nine sections — the truncated Step 2 attempt had been cut off at "Now §1.9 batch 3: endpoints, errors, RBAC", exactly where the file stopped. Step 2 was therefore incomplete, not merely mis-reported.

Completing the §1.9 file was briefly blocked by repeated subagent endpoint failures (5 consecutive `model_not_found` 404s for `deepseek-v4p1-flash-wave`; the same endpoint had served Steps 2/4/5 minutes earlier, so this was transient). A later retry succeeded.

Subagent summary (verbatim from its final report):

> Done. Note the interrupted step had in fact already landed all nine sections before I picked it up, so my work was a §1.9 contract audit + targeted repair rather than authoring from a half-file.
>
> ```
> §1.9 counts (five requested sections) — real / stub
>   endpoints                          8 / 0
>   errors                             8 / 0
>   rbac (slug "RBAC")                 7 / 0
>   cross-cutting complexity layers    8 / 0   (6 pre-existing + 2 added)
>   consistency model                  5 / 1   (4 reals + 1 genuine stub)
> New total §1.9 instances: 74  (73 real + 1 stub)
> §1.5 repairs by me: none — SCAFFOLD.yaml unchanged; the file already declares
>   60 endpoints (the earlier interrupted pass made the 58→60 ladder repairs).
> Defects found and fixed (3):
>   1. dangling ground: state_machines.Product.launch_status (no such SM)
>      → entities.Product.fields.launch_status
>   2. two FALSE stubs (pledge-create-stale-order, order-receive-stale-order)
>      cited §1.9 instances, not §1.8, and mis-attributed coverage → replaced
>      with real OCC instances (occ_stale_version_on_pledge_create_against_draft_order,
>      occ_stale_version_on_product_order_receive) inside cross-cutting layers; stubs deleted
>   3. remaining stub cited nonexistent §1.8 name cascading_side_effects_route_suspend_deactivates_shops
>      → repointed to real §1.8 instance non_linear_cyclic_loops_on_franchisee_and_route
> Final lint VERDICT: clean lint (60 endpoints, 15 entities, §1.8 18, §1.9 73, 1122 calls)
> Union uniqueness: 92 names (18 §1.8 + 74 §1.9), 0 duplicates; 0 unbound ${var};
>   all grounds resolve to §1.1–§1.7; stub citations resolve to real §1.8 names.
> ```

Orchestrator independent verification (the subagent's claim that "all nine sections were already present" could NOT be reproduced — the pre-retry read showed only 4 sections / 38 instances, so either a failed-then-retried attempt landed writes or the report's recollection is off; disk state is what governs):
- `SCAFFOLD_CORNER_DESIGN.yaml` — 256132 bytes, parses as YAML, `scaffold_corner_design` single top-level key.
- Section census read off disk: entities 8, state_machines 8, calculations 5, validations 17, endpoints 8, errors 8, RBAC 7, cross-cutting complexity layers 8, consistency model 4 real + 1 stub = **74 instances, 1 stub**. All nine guide sections present.
- `scaffold_lint.py` re-run by the orchestrator: §1.5 endpoints 60, §1.1 entities 15, §1.8 instances 18, §1.9 instances 73 (lint scans non-stub instances), calls scanned 1122. VERDICT: **clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.**
- Union name uniqueness re-checked by the orchestrator: 18 §1.8 + 74 §1.9 = 92 names, ZERO duplicates.

**Step 2 is now COMPLETE.** Design indices: §1.8 = 9 rules × 2 = 18 instances; §1.9 = 74 instances (73 real + 1 `excluded_because:` stub) across all nine guide sections.

## Step 5: Generate Unit Tests — 2026-10-01T08:40:00.000Z

Regenerated from scratch (the orchestrator deleted the earlier truncated `test_helpers/` + `test_suite/` at 05:25 because they had been built against the incomplete 4-section §1.9 index). Output discipline (one tool call per message, one file per message, ≤~350 lines/file, sentinel-append) was imposed up front per known output-cap failures on this endpoint.

Subagent summary (verbatim, from its final report):

> All checks pass. Here is the final report.
>
> ## Deliverable
>
> `test_helpers/` (9 modules, 1,159 lines) and `test_suite/` (conftest + 19 test files, 3,898 lines) under `.../task_3337_franchise_mobile_tool_truck_routes_customer_credit/`.
>
> | File | Tests | Lines |
> |---|---|---|
> | test_helpers/types.py | – | 429 |
> | test_helpers/api_client.py (60 endpoints) | – | 227 |
> | test_helpers/api_errors.py (64 ids) | – | 141 |
> | test_helpers/assertions.py | – | 169 |
> | test_helpers/constants.py | – | 94 |
> | test_helpers/factories.py | – | 180 |
> | test_helpers/test_users.py | – | 42 |
> | test_helpers/fixtures.py | – | 284 |
> | test_helpers/fixtures_ops.py | – | 220 |
> | test_suite/conftest.py | – | 45 |
> | test_01_difficulty_dual_variant.py | 1 | 68 |
> | test_02_difficulty_combinatorial.py | 2 | 80 |
> | test_03_difficulty_state_machine.py | 2 | 83 |
> | test_04_difficulty_cascade.py | 2 | 109 |
> | test_05_difficulty_priority.py | 2 | 87 |
> | test_06_difficulty_boundary.py | 2 | 92 |
> | test_07_difficulty_cross_entity.py | 2 | 98 |
> | test_08_difficulty_temporal.py | 2 | 100 |
> | test_09_difficulty_compensating.py | 2 | 116 |
> | test_10_corner_entities.py | 8 | 185 |
> | test_11_corner_state_machines.py | 8 | 268 |
> | test_12_corner_calculations.py | 5 | 188 |
> | test_13_corner_validations_a.py | 9 | 249 |
> | test_14_corner_validations_b.py | 8 | 303 |
> | test_15_corner_endpoints.py | 8 | 263 |
> | test_16_corner_errors.py | 8 | 231 |
> | test_17_corner_rbac.py | 7 | 217 |
> | test_18_corner_cross_cutting.py | 8 | 309 |
> | test_19_corner_consistency.py | 4 | 158 |
>
> **Total: 90 tests.** Queue A (difficulty) 18 instances → **17 translated, 1 skipped**; queue B (corner) 74 instances → **73 translated, 0 skipped, 1 `excluded_because` stub not translated** (its pointer to `non_linear_cyclic_loops_on_franchisee_and_route` resolves).
>
> **Self-verification:** `py_compile` clean on all 28 files; `grep -rn '__APPEND__'` → none; no `skip`/`skipif`/`xfail`; no "scaffold" strings. Design-tag checker (parses the index as lists of `{rule_id|section, instances[]}` blocks): **90/90 tags resolve, exactly one per test, no duplicates, no untagged tests**. Citation checker: **90/90 tests carry a ≥8-word PRD citation that matches PRD.md verbatim on a single line**. `python3 -m pytest --collect-only -q` → **90 tests collected, 0 errors** (tests not executed; no implementation exists).
>
> ## Skipped instance (1)
>
> - `Difficulty/dual_variant_calc/dual_variant_finance_charge_basis_on_lease_account` — the instance's whole claim is a 60-cent divergence between a revolving and a lease accrual on the same 20000-cent same-week collection, which requires the lease basis to be reduced by the payment's *full amount* (45338→25338). PRD §3.5 reduces the basis by the payment's `charge_applied_cents` (the amount that went to charges — 136 here), so both accounts accrue 136 and the asserted 76 is not PRD-derivable. Skipped, not weakened.
>
> ## Recipe corrections applied (design index contradicted PRD arithmetic)
>
> Both design files were linted structurally, but several recipes are arithmetically unsatisfiable. I replayed each setup chain and corrected only what the PRD forbids; every deviation is listed here:
>
> 1. **Mix-factor drift (11 instances).** Recipes name `mix_profile: POWER_TOOLS` while asserting the DIAGNOSTIC_WEIGHTED gross (45000 × 1.0075 = 45338). PRD §3.4 pins POWER_TOOLS = 1.0025 (→ 45113). I switched those orders' `mix_profile` to `DIAGNOSTIC_WEIGHTED`, preserving every asserted cent (45338 / 25474 / 45474 / 4526 / 4547 / 4662 / 24526 / 136): difficulty 02b, 04a, 04b, 08a, 09b; corner 11d, 15e, 16a, 19a, 19c, 19d.
> 2. **Warranty clock (3).** A 4800-cent allocation (0.40 × 12000) only exists *outside* the 12-month term; the recipes resolved the claim inside warranty (charge 0). Added a clock advance to 2027-09-13 before approval: difficulty 01a, corner 11e, 19b.
> 3. **Charge-basis direction (2).** `dual_variant_financing_principal_on_sales_order` and `consistency_warranty_reopen_restores_principal_before_next_read` asserted the account principal *dropping* by 4800; PRD §3.8 writes a CLAIM allocation as new principal. Corrected to 35025 and 50138; order-side final-basis asserts kept.
> 4. **Score arithmetic (1).** `calc_credit_decision_limit_marginal_tiering_and_requested_cap` needs score 72 (⇒ months_in_trade 40, not 100) for the asserted 43000/≠54000.
> 5. **Order-line edits (2).** 30226 needs two 1-unit lines, not one 2-unit line (`validation_sales_line_cannot_exceed_remaining_stock` patched to two lines; `endpoint_patch_order_rejects_empty_line_array` and `occ_stale_version_on_sales_order_confirm` corrected 30226 → 30225).
> 6. **Typo (1).** `consistency_cross_entity_reference…` asserted `revolving_available_cents == 5464`; PRD-derived 100000 − 45474 = 54526.
> 7. **Unreachable states (5).** MISS before the anniversary week (moved to 2026-09-14 ⇒ charge-off 2027-03-15); develop-before-activate leaving the territory IN_DEVELOPMENT and blocking resale (reordered to activate-then-develop in 4 instances, plus the mandatory `expected_route_version` on retire); out-of-range `line_index` refused at *filing* not submit; RECEIVE missing its mandatory `expected_product_order_version`; over-pledge fixture that could not confirm (position built at 3, adjusted to 1).
> 8. **Determinism (1).** `occ_version_increments_on_every_parent_write`'s stale pledge named a non-existent account (404 would pre-empt 412); fixture now creates a real account.
> 9. **PRD-ambiguous step (1).** `validation_replenishment_ceiling_exceeded_at_creation`: PRD §3.6 pins the refusal at SUBMIT, the instance at creation; the test accepts either step but always asserts `ERR_ALLOCATION_CEILING_EXCEEDED` / 422.
>
> **Residual risk to flag:** `validation_requested_limit_above_absolute_cap_rejected` relies on `CREDIT_ABSOLUTE_CAP_CENTS`, which is symbolic in both PRD and SCAFFOLD (never valued). The test is sound for any implementation cap in [500000, 9000000); a cap below 500000 would break its accept-side assert.

Orchestrator independent verification:
- On-disk census: `test_helpers/` 10 files / 1808 lines; `test_suite/` 19 test files + conftest / 3204 lines; **90 test functions**. Zero `__APPEND__` sentinels left; zero `skip`/`xfail`.
- **Own design-tag resolution script** (independent of the subagent's): built `{name → rule_id}` from §1.8 and `{name → section}` from §1.9, parsed `Design: (Difficulty|Corner)/<slot>/<instance>` out of each test body. Result: **90/90 tags resolve, exactly one tag per test function, zero unresolved, zero slot-mismatches, zero dual-tagged, zero untagged.** Translated: 17 difficulty + 73 corner. Untranslated: exactly the 1 skipped difficulty instance and the 1 `excluded_because` stub.
- **Spot-check of the largest correction claim (mix factors), against source:** PRD line 746–747 states "`DIAGNOSTIC_WEIGHTED` uses `1.0075`, `TOOL_STORAGE` uses `1.0150`, and `POWER_TOOLS` uses `1.0025`"; SCAFFOLD lines 1190–1192 declare the same mapping. The design-index recipes did assert the DIAGNOSTIC_WEIGHTED gross while naming POWER_TOOLS, so the subagent's switch to DIAGNOSTIC_WEIGHTED was CORRECT and PRD-faithful. (This is the known "design index silently contradicts PRD+SCAFFOLD" failure mode.)
- **Spot-check of the warranty-clock correction:** PRD line 1108 defines inside-warranty as elapsed months *strictly less than* `warranty_terms.months`; the corrected tests advance the clock to 2027-09-13, giving elapsed = 12 against a 12-month term → outside warranty → the 4800-cent charge exists. CORRECT.

## Orchestrator PRD edit — pin the unpinned cap constant — 2026-10-01T08:42:00.000Z

`CREDIT_ABSOLUTE_CAP_CENTS` was named in PRD §2.9 and SCAFFOLD but **never assigned a value in either** (verified by exhaustive grep of both files). This is the known "unpinned constant drifts between Step 5 and Step 6" failure mode: the Step 5 test `validation_requested_limit_above_absolute_cap_rejected` asserts only that 9000000 is refused and 500000 is accepted (sound for any cap in [500000, 9000000)), while the Step 6 implementation would have to guess a number independently.

Fix (orchestrator-owned, minimal, PRD-only — the PRD is the contract both Steps 5 and 6 read):
- `workspace/PRD.md` §2.9 — the "Two constants are symbolic in this specification" paragraph now fixes `CREDIT_ABSOLUTE_CAP_CENTS` at **2000000** cents and `FRANCHISEE_RESALE_FEE_CAP_CENTS` at **900000** cents (the latter matching SCAFFOLD's `FRANCHISEE_RESALE_FEE_CAP_CENTS: 900000`, which the PRD already echoed as 900000 in its resale-fee prose).
- 2000000 sits comfortably inside the test's required window, is above `LIMIT_TIER_BOUNDARY` (500000), and keeps the tier arithmetic meaningful.
- Checked: the Step 5 test remains valid (9000000 > 2000000 → refused; 500000 < 2000000 → accepted), and `test_helpers/constants.py` carries no conflicting value for this constant.

## Step 5 verification of other numeric constants — 2026-10-01T08:43:00.000Z

Scanned every numeric-looking constant identifier (`*_CENTS`, `*_RATE`, `*_WEIGHT`, `*_BOUNDARY`, `*_CAP`, `*_FEE`, `*_MONTHS`, `*_TIER`, `*_PCT`, …) referenced anywhere in `test_suite/` or `test_helpers/` (48 candidates) against PRD + SCAFFOLD: **no other named-but-unvalued numeric constant remains.** The only prior hits were enum members and action verbs (ACTIVATE, CANCELLED, DIAGNOSTICS, …), which carry no numeric drift risk.

## Step 6: Generate Implementation — 2026-10-01T09:20:00.000Z

Run with the ISOLATION RULE imposed explicitly (Steps 5 and 6 were sequential in this run rather than concurrent, so the physical isolation of a not-yet-existing `test_suite/` did not hold and the read ban had to be stated), plus output discipline (one tool call per message, one file per message, ≤~350 lines/file, many small domain modules) per the known output-cap failure on this endpoint.

Subagent summary (verbatim, from its final report):

> Implementation complete and verified.
>
> ## Deliverable
>
> `workspace/implementation/` — 26 files, **3868 lines total**, no file over 400 lines (max `calc.py` at 399).
>
> | File | Lines | File | Lines |
> |---|---|---|---|
> | calc.py | 399 | api_shops.py | 93 |
> | recompute.py | 286 | clock.py | 92 |
> | api_sales_orders.py | 264 | app.py | 66 |
> | api_applications.py | 258 | api_inventory.py | 60 |
> | api_routes.py | 247 | api_clock.py | 26 |
> | api_product_orders.py | 203 | start.sh | 10 |
> | api_payments.py | 193 | requirements.txt | 1 |
> | api_technicians.py | 179 | errors.py | 153 |
> | api_franchisees.py | 178 | envelope.py | 167 |
> | api_warranty.py | 178 | lookup.py | 116 |
> | api_launch.py | 144 | store.py | 100 |
> | auth.py | 123 | api_accounts.py | 117 |
> | api_pledges.py | 117 | api_products.py | 98 |
>
> ## Verification (all numbers from the run)
>
> - **py_compile**: all 25 `.py` files compiled OK; `bash -n start.sh` OK; `grep -rn '__APPEND__'` → nothing.
> - **Endpoints**: **61 registered = all 60 declared in SCAFFOLD §1.5, none missing**, plus one extra `PUT /retail/products/{id}` (declared in the RBAC matrix but absent from the endpoint table). Verified by enumerating `app.url_map`.
> - **Boot**: fresh `bash start.sh` on PORT=34117 became HTTP-ready in **0.55 s**, bound `0.0.0.0`. Fresh-boot lists return `response_type: "array"`, `data: []`, `meta` with `limit/offset/total_count/has_more` for all 13 list resources — **zero seeding**.
> - **Smoke tests** (3 scripts, each on a fresh server boot; server killed by its exact saved PID, port released): full happy path plus product orders/pledges/ceiling fill, launch plan + reallocate + review, resale FILE/APPROVE, suspend/reinstate/retire, technician change/cancel-shop and trade-exit cascade, payment book/miss/collect/reverse, account posture, 26-week charge-off sweep, lease amortisation, warranty inside/outside term, idempotent replay, OCC 412s, RBAC 403s, and error-priority ordering. All three printed OK.
> - No files written to disk at runtime; no broad kill patterns used (only `$!`-saved PIDs).
>
> ## Notable decisions where the PRD is the authority
>
> - Version semantics: **one bump per row per request** (`store.begin_unit()`), so a freshly created row is `version: 1` and one state transition yields `version: 2` — derived-field recomputation inside a creation write does not inflate the version.
> - `ERR_STALE_VERSION` (412) is checked before state admissibility on the five OCC writes; `expected_route_version` / `expected_sales_order_version` / `expected_product_order_version` are **required** for RETIRE / CONFIRM / RECEIVE and **rejected with `ERR_INVALID_REQUEST`** on the other actions of those endpoints, per §2.8.
> - `ENROLL` applies `franchisee_training_progress` (≥40 points certifies), per §2.10's explicit scalar expression; `CERTIFY` below 40 → `ERR_CERTIFICATION_POINTS_SHORT`.
> - Territory-product-mix uniqueness per franchisee is enforced (`ERR_UNIQUENESS_VIOLATION`) — declared in §2.9, §3.9 and scaffold validation 11.
> - Stock is checked at sales-order **creation, line edit and advancement** (§3.9), with a missing position reported as `ERR_INVENTORY_POSITION_NOT_FOUND`.
> - Warranty `elapsed_months` uses whole calendar-month difference, so the charge switches on exactly at the nominal expiry week.

Orchestrator independent verification:
- On-disk census: **24 `.py` files / 3857 lines** (the report's "25 .py files" counts `start.sh` or `requirements.txt`; the 26-file total is right). Zero `__APPEND__` sentinels. Largest file `calc.py` at 399 lines — no file over 400.
- `start.sh` inspected directly: `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded `pip install` (skipped when flask is already importable — important because the harness re-invokes it before every test across 8 concurrent rounds), then `exec python3 app.py` in the foreground. Reads `$PORT` via the app; binds `0.0.0.0`.
- **Independent boot + smoke test by the orchestrator** on two separate free ports (34771, 34773), each time saving `$!` and killing exactly that PID:
  - Server became ready in ~1.5 s, no traceback in the log.
  - `GET /retail/franchisees` with no headers → `ERR_MISSING_USER_CONTEXT` (correct: PRD line 49 requires **both** `X-User-ID` and `X-User-Role`; my first probe sent only the role header, and the implementation correctly refused it).
  - `POST /retail/franchisees` with both headers → 201-shaped `data` object carrying exactly the defaults the design index expects: `training_status: NOT_ENROLLED`, `can_resell_territory: false`, `active_route_count: 0`, `credit_ceiling_cents: 0`, `certified_on: null`, `version: 1`, plus `api_request_id`/`api_request_timestamp` meta and the logical clock pinned at `2026-09-01T00:00:00.000Z`.
  - `GET` list → `data` array envelope; the list contained **only** the entity just created, confirming zero startup seeding and true fresh-boot state.
- **`PUT /retail/products/{id}` provenance check.** The subagent flagged it as an extra endpoint absent from the §4 endpoint table. Verified: PRD §2.1 states verbatim "`PlatformAdmin` alone may set the logical clock and create or update products." (PRD line 81–82), so the endpoint DOES trace to PRD prose — it is a §4 endpoint-table gap in the PRD, not an implementation-hacking addition. No test exercises it (`test_helpers/api_client.py` has no product-update method). Noted for Steps 8/9 as a PRD endpoint-table gap rather than an impl defect.

## Step 7: Run Tests and Iterate — 2026-10-01T10:13:00.000Z

Long-lived fix subagent owning the run/diagnose/fix loop with the 8-round parallel `prd-bench-local-run --isolation per-test-server` sweep per iteration.

Subagent summary (verbatim, from its final report):

> Clean 8-round sweep achieved. Final state verified.
>
> ## Summary
>
> **Iterations run:** 3 (25/90 → 81/90 → 90/90).
>
> **Tests deleted:** none. The suite is still 90 test functions; `test_helpers/` is byte-identical to its pre-iteration state (no fixture/factory/role-header bug was found — every failure traced to a test-body call-site error, a wrong literal, or an implementation defect).
>
> **Fixes applied to `implementation/`**
>
> 1. `clock.py` — added `fmt_week()` (ISO 8601 second resolution). `created_at`/`updated_at`/`api_request_timestamp` keep the PRD §2.5 three-digit form.
> 2. 13 modules (`api_clock`, `api_payments`, `api_accounts`, `api_applications`, `api_products`, `api_franchisees`, `api_routes`, `api_technicians`, `api_sales_orders`, `api_warranty`, `recompute`) — the §2.4 week-valued fields, `schedule_anchor_utc` (§2.12 "the anchor is second-resolution"), the clock capability's `current_utc`/`current_week_start`, and the instants stamped straight from the logical clock (`account_status_changed_at`, `certified_on`) now emit `…T00:00:00Z` instead of `…T00:00:00.000Z`.
> 3. `api_sales_orders.py::_deliver` — added the missing `ERR_ACCOUNT_NOT_ACTIVE` gate before the fiscal checks. PRD §3.9 puts state admissibility (6th) ahead of the fiscal ceilings (last) and §2.14 requires an `ACTIVE` account for financing; the handler was returning 402 `ERR_ACCOUNT_LIMIT_EXCEEDED` where 409 was due. (Check added, never removed.)
> 4. `api_inventory.py::write_position` — added `store.stamp(route)`. PRD §2.5 makes recomputing a route's aggregates a modification of the route row, so its `version` advances even when `inventory_at_risk_cents`/`over_pledge_cents` hold their previous value.
> 5. `api_routes.py::advance_territory` — a round opened with ≥60 points on an `IN_SERVICE` route now reaches `QUALIFIED` in the same call (PRD §2.10: "a round qualifies when the route's `territory_points` reach at least 60 while the route's `route_status` is `IN_SERVICE`"), with the §3.1 certification precondition evaluated before any mutation so a refused request cannot half-write.
>
> **Fixes applied to `test_suite/`** (the offending layer in every remaining case)
>
> - `validate_success` contract misuse, ~105 sites across all 19 files: the framework returns `data`, the suite uniformly assumed the full envelope and subscripted `["data"]`. Removed the redundant subscript; also removed 3 redundant wrappers where the argument was already an unwrapped payload (`create_order` ×2 in `test_02`, `deliver_order` in `test_19`).
> - `, 201` added at 17 creation call sites per PRD §4 ("a warranty claim, an inventory position, a replenishment order and a share pledge are all created that way"); includes one latent case inside an alternative-path branch in `test_14`.
> - Missing imports added: `validate_success` (`test_04`, `test_05`), `setup_product_with_stock` (`test_15`), `create_order` (`test_18`), `get_franchisee` (`test_11`).
> - `test_07` confirm-gate: added the §2.8-mandatory `expected_sales_order_version` — the malformed body was refused 400 before the state gate the test targets.
> - `test_14` payment-week: moved `set_clock("2026-09-14")` after the storefront setup, which pins the clock to 2026-09-07 (clock only moves forward).
> - `test_11`/`test_13` certification: dropped a redundant second `ENROLL` — §3.1 makes ENROLL valid only from `NOT_ENROLLED`, and the fixture already enrolled.
> - `test_07`/`test_13` shop tests: the second route on the same franchisee now uses a distinct `mix_plan`; §2.9 makes territory-level product mix unique per franchisee.
> - `test_14` stock: restructured. §3.9 makes the stock rule guard creation and line editing as well as advancement, so the old fixture could not legally create an over-stock order; the test now asserts the rule at all three guarded steps.
> - `test_17` RBAC stock: the fixture pre-created the position, contradicting the test's own "route holds no position after the refusal"; product is now created without stock.
> - Wrong literals corrected against PRD arithmetic: `credit_available_cents` 4662→4526 (`test_09`, twice — §2.13 `credit_limit − current_balance`, and the same test asserts `current_balance == 45474`); `outstanding_credit_cents` 45338→45474 (`test_08`, §2.10 sums `current_balance_cents`); `accrual_seq` 2→1 (`test_08`, §3.5 "restarts at 1 within each week" — the design index contradicted the PRD here); new position `version` 3→1 (`test_18`, §2.5 starts at 1 — the route's own `== 3` assertion kept); `permitted["data"]`→`permitted` (`test_17`).
> - `test_15`/`test_18` retire-while-resale-pending: relaxed the identifier to `validate_error_is_one_of([ERR_RESALE_ALREADY_PENDING, ERR_INVALID_STATE])` with an explicit 409 check. §3.1 states the refusal but names `ERR_RESALE_ALREADY_PENDING` only for a second *filing*; the retire rule names no identifier, so the specific choice is not uniquely derivable (SCAFFOLD's own condition for that id is the filing case only).
>
> **Final: per-round passed/total**
>
> | round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
> |---|---|---|---|---|---|---|---|---|
> | passed/total | 90/90 | 90/90 | 90/90 | 90/90 | 90/90 | 90/90 | 90/90 | 90/90 |
>
> All 8 `results.*.json` files are on disk under `workspace/implementation/`, and no implementation source file is newer than them, so the sweep is valid for the shipped code.

Orchestrator independent verification performed at the time:
- All 8 `results.*.json` present, each `passed 90 / total 90 / failed 0`.
- mtime check: newest implementation source 09:57:26, newest test source 10:04:33, results 10:07:31 — results NEWER than every source, so the sweep tested the shipped code. (`__pycache__` excluded, per the known directory-mtime false positive.)
- **`validate_success` semantics verified against the framework source**: `prd_bench_local_runner.testing.validate_success` documents and implements "Returns the 'data' payload for further assertions". The suite's `validate_success(...)["data"]` really was a double-unwrap call-site bug, so removing the subscript is a legitimate test-body correction, NOT an assertion weakening. Confirmed the helper still asserts status code + envelope shape + `meta` fields.
- The subagent's `, 201` correction matches the known failure mode "validate_success defaults to 200, creates return 201" — the test was wrong, not the implementation.

NOTE: the 8 results files were subsequently deleted by the orchestrator's own verification sweep script (`rm -f results.*.json` at its head) when the host session was killed mid-sweep, so they are regenerated at the end of the pipeline (after Step 9) as the pipeline's final evidence.

## Step 8: Finalize PRD — 2026-10-01T10:26:00.000Z

Not skipped: Step 7 applied 5 `implementation/` fixes and many `test_suite/` fixes, so PRD.md did not already determine every behavior the implementation exhibits. The Step 7 worklog entry was inlined verbatim as `<step_7_diff>` in the subagent prompt as the focus list.

Subagent summary (verbatim, from its final report):

> Done. `PRD_FINALIZED.md` is written as a minimal patch of `PRD.md`.
>
> ## Size
> - `PRD.md`: 1409 lines / 112,923 bytes → `PRD_FINALIZED.md`: 1424 lines / 114,347 bytes (**+15 lines, +1.06%**); 6 diff hunks, 26 lines inserted, 11 reflowed.
>
> ## Changes (each traced to a `<step_7_diff>` item)
> - **§2.4 (Logical Clock / Weekly Cadence) — insert** — Pinned the wire form of every non-common timestamp: week-valued fields, `schedule_anchor_utc`, the clock capability's `current_utc`/`current_week_start`, and `account_status_changed_at`/`certified_on` are serialised at second resolution (`2026-09-07T00:00:00Z`, no fractional digits); only `created_at`, `updated_at`, `api_request_timestamp` keep the three fractional digits. — `implementation/clock.py:60-70` (new `fmt_week`), `store.py:68,76-77`, `envelope.py:21`, `api_clock.py:24-25`, `api_franchisees.py:116-117,166`, `api_routes.py:150,182-183,209`, `api_applications.py:217`, `api_accounts.py:103`, `api_payments.py:42,134,148,156,161,175`, `api_technicians.py:170`, `api_warranty.py:71,133,164`, `api_sales_orders.py:88`, `api_products.py:39,97`, `recompute.py:40,252,256,259,283`
> - **§2.12 (Inventory Aggregates) — revise** — The inventory-position write now also "refreshes the route row itself, so the route's `updated_at` is refreshed and its `version` advances even when both aggregates keep their previous value." — `implementation/api_inventory.py:48-52`
> - **§3.1 (Retirement) — insert** — A retirement from any status other than `DRAFT`/`SUSPENDED`, and a retirement while `resale_status` is `PENDING`, are both refused with `ERR_INVALID_STATE` at 409 (the identifier was previously unnamed). — `implementation/api_routes.py:143-146`
> - **§3.1 (Territory Qualification) — insert** — A round opened from `UNASSIGNED` with ≥60 points on a route already `IN_SERVICE` reaches `QUALIFIED` on that same call, and a refused qualification leaves the route's development state untouched. — `implementation/api_routes.py:167-185`
> - **§3.4 (Delivery) — insert** — Delivery additionally requires the credit account named on the order to be `ACTIVE`, refused with `ERR_ACCOUNT_NOT_ACTIVE` (409) before any fiscal ceiling is evaluated. — `implementation/api_sales_orders.py:213-216`
> - **§4 (Endpoint table) — insert** — Added the missing `PUT /retail/products/{id}` row ("Update a product.", PlatformAdmin), permitted by the orchestrator note. — `implementation/api_products.py:72-98`
>
> Not edited (step-7 items that are pure test/fixture bugs or already PRD-determined): the ~105 `validate_success` unwrap fixes, the 17 `, 201` creation sites, missing imports, the confirm-gate `expected_sales_order_version`, payment-week clock ordering, redundant ENROLLs, distinct `mix_plan`, stock-rule restructuring, the corrected literals (`accrual_seq`, position version, `credit_available_cents`, `outstanding_credit_cents`), and the two cap constants the orchestrator had already pinned.
>
> ## Per-edit pre-edit search log
> 1. **§2.4 timestamps** — (a) subject: serialisation format of every timestamp the API emits. (b) Enumerated by grepping all of `implementation/` for `fmt(`, `fmt_week(`, `_at"`, `_week`, `_utc`, `_on`, `iso_week`, `anchor`, then reading `store.py`, `envelope.py`, `api_clock.py`, `api_franchisees.py`, `api_routes.py`, `api_applications.py`, `api_accounts.py`, `api_payments.py`, `api_technicians.py`, `api_warranty.py`, `api_sales_orders.py`, `api_products.py`, `recompute.py`; also confirmed `decision_note` carries no timestamp. (c) Adjustment: instead of a blanket "all other timestamps", I explicitly enumerated the non-week fields (`schedule_anchor_utc`, `current_utc`, `current_week_start`, `account_status_changed_at`, `certified_on`) after verifying the enumeration is exhaustive — so the "only created_at/updated_at/api_request_timestamp" clause is provably true.
> 2. **§2.12 route version** — (a) subject: row stamping on an inventory-position write. (b) Enumerated every `recompute_route` and `store.stamp` callsite (`api_routes.py:44,93,129,152,211,254`, `api_sales_orders.py:179,204,243,267`, `api_product_orders.py:175`, `api_inventory.py:48,52`) plus `store.set_field`/`stamp` semantics; noted that recomputes elsewhere bump only when a value moves (e.g. the side-effect-free repeated draft-summary read asserted in test_18). (c) Adjustment: scoped the claim to the inventory-position write only, rather than restating §2.5 globally (a global "recompute always bumps" would have mis-described read paths and `set_field`).
> 3. **§3.1 retire identifier** — (a) subject: refusal identifiers on the RETIRE action. (b) Read `api_routes.advance_route` in full and the two tests that were relaxed (test_15:230, test_18:115). (c) Adjustment: covered both `ERR_INVALID_STATE` branches (wrong status and pending resale) in one sentence, and deliberately left the §2.8 `ERR_STALE_VERSION`/`ERR_INVALID_REQUEST` paths untouched so the new sentence cannot be read as reordering them.
> 4. **§3.1 same-call qualification** — (a) subject: when a territory reaches `QUALIFIED`. (b) Enumerated all four `DEVELOP` branches (UNASSIGNED open, QUALIFIED restart, IN_DEVELOPMENT ≥60, IN_DEVELOPMENT <60) and the SURRENDER branch, plus the certification/route-status checks; cross-checked tests test_03 (same-call qualify), test_05 (open at 90 while DRAFT stays `IN_DEVELOPMENT`), test_16 (develop-then-activate). (c) Adjustment: scoped the clause to openings from `UNASSIGNED` so it cannot be misread as also qualifying the `QUALIFIED`-restart path, and softened "writes nothing at all" to "leaves the route's development state untouched" to avoid an over-claim about the request-level sweeps.
> 5. **§3.4 delivery** — (a) subject: preconditions of the `DELIVER` action. (b) Enumerated every `ERR_ACCOUNT_NOT_ACTIVE` raise site (`api_sales_orders.py:191,216`, `api_accounts.py:70`, `api_payments.py:125`) and every financing write (`_confirm`, `mint_account`, warranty allocation) to check the wording would not spill onto them. (c) Adjustment: scoped the sentence to delivery ("the credit account named on the order") instead of a general "financing requires an ACTIVE account", which would have mis-described minting and collection.
> 6. **§4 products table row** — (a) subject: the product-update endpoint. (b) Read `api_products.py` in full to confirm method, path, role (`PlatformAdmin`) and status (200), and checked the surrounding table's column format. (c) No adjustment; I deliberately did not add payload-key prose for the update (its key set is not stated anywhere in the PRD), keeping the change to the authorized table row.

Orchestrator verification:
- `workspace/PRD.md` 1409 lines → `workspace/PRD_FINALIZED.md` 1424 lines (+15, +1.06%), 37 diff lines — matches the reported 26 insertions + 11 reflows. File ends cleanly at the §5 error table.
- **`implementation/` was NOT modified by Step 8** (mtime check: newest impl source `1790848646` = 09:57:26 < results `1790849771` = 10:16:11), so the Step 7 verification sweep remains valid at this point.

## Step 9: Complete PRD — 2026-10-01T10:50:00.000Z

Full PRD-vs-implementation scan (always runs; no skip). Source: `PRD_FINALIZED.md` (present), copied to `PRD_COMPLETED.md` and edited in place.

Subagent summary (verbatim, from its final report):

> The work is complete. Here is the report.
>
> ## Deliverable
>
> `workspace/PRD_COMPLETED.md` — copied from `PRD_FINALIZED.md` and edited in place. `PRD_FINALIZED.md`, `PRD.md`, and everything under `implementation/` are untouched (0 files in `implementation/` newer than session start).
>
> - Source `PRD_FINALIZED.md`: 1424 lines / 114347 bytes. Output `PRD_COMPLETED.md`: **1516 lines / 122486 bytes** (+92 lines, **+8055 characters / +8139 bytes**).
> - Structural invariants preserved: 31 headings identical (no section added or removed), 127 table rows identical, error catalogue still 64 rows with unchanged statuses.
> - **49 ambiguity-pins, 19 mismatch-revisions** (68 diff hunks; a few changes span two hunks).
>
> ## Changes (section — insert/revise — kind — what changed — impl ref)
>
> **§2.1–§2.14 (global)**
> - §2.1 — revise — ambiguity — a `Technician` reads only its own accounts/payments/orders **and its own technician row**; naming another technician's row/account/order/history → `ERR_UNAUTHORIZED` — `auth.py:120-123`, `api_accounts.py:32-33`, `api_technicians.py:66-68`, `api_sales_orders.py:100-101,116-117`
> - §2.1 — insert — mismatch — where a §4 table lists several roles, any listed role may invoke **any** action the endpoint offers; only the payment, credit-application and warranty-claim actions narrow the role per action (the "FranchiseManager alone"/"FranchiseOwner alone" prose was not enforced) — `api_routes.py:99,159,217`, `api_technicians.py:99`, `api_accounts.py:59`, `api_product_orders.py:116`, `api_inventory.py:20` vs `api_payments.py:88-95`, `api_applications.py:101-160`, `api_warranty.py:103-106`
> - §2.3 — insert — ambiguity — a negative `offset` is refused with `ERR_INVALID_REQUEST` — `envelope.py:58-60`
> - §2.4 — revise — mismatch — the clock call runs the §2.14 sweep, not one "over every non-closed account" (SUSPENDED is excluded) — `recompute.py:272-283`
> - §2.5 — revise — ambiguity — recomputation advances `version` only when a value actually moves; the inventory-position write refreshes its route unconditionally — `store.py:85-91`, `api_inventory.py:48-52`
> - §2.6 — insert — ambiguity — a missing pledge id → `ERR_PRODUCT_ORDER_NOT_FOUND`; a missing allocation id → `ERR_PRODUCT_NOT_FOUND` — `lookup.py:98-109`
> - §2.9 — revise — mismatch — the territory-mix collision is **always** `ERR_UNIQUENESS_VIOLATION`; the other three use their own ids — `api_franchisees.py:147-150`, `api_routes.py:79-84`
> - §2.10 — insert — ambiguity — a franchisee's accounts are those whose `territory_id` is one of its routes — `recompute.py:71-87`
> - §2.10 — insert — ambiguity — `active_account_count` = the franchisee's `ACTIVE` accounts — `api_franchisees.py:61-63`
> - §2.13 — revise — mismatch — `credit_line_status` is set `ACTIVE` at onboarding and **no endpoint moves it** (the described line-termination request does not exist) — `api_technicians.py:39,73-94`
> - §2.14 — revise — mismatch — `ERR_ACCOUNT_NOT_DELINQUENT` fires when a `MISSED` payment is collected on a non-`DELINQUENT` account, not on a "cure" — `api_payments.py:126-128`
> - §2.14 — revise — mismatch — closure with a non-zero balance → `ERR_ACCOUNT_HAS_BALANCE`, not `ERR_CHARGE_OFF_NOT_DUE` — `api_accounts.py:96,100`
> - §2.14 — insert — mismatch — the sweep skips an `ACTIVE` account carrying fewer than 3 missed payments (never satisfiable, so only `DELINQUENT` accounts flip); the sweep runs on every request — `recompute.py:275-285`
>
> **§3.1–§3.4**
> - §3.1 — revise — mismatch — `ENROLL` applies `franchisee_training_progress`, so ≥40 points certifies in the same move — `api_franchisees.py:97-101`
> - §3.1 — insert — ambiguity — a new route also starts `resale_buyer_training_status=NOT_ENROLLED`, `resale_trained_points=0`, `reopening_fee_cents=0`, `launch_risk_band=HIGH` — `api_franchisees.py:171-175`
> - §3.1 — insert — ambiguity — activation refused for empty `zip_codes` or `inventory_invested_cents<1` → `ERR_INVALID_STATE` — `api_routes.py:121-124`
> - §3.1 — insert — ambiguity — a `QUALIFIED`→`IN_DEVELOPMENT` restart clears `in_force_to_week` and keeps the original `in_force_from_week` — `api_routes.py:186-189`
> - §3.1 — insert — ambiguity — surrender with a live resale → `ERR_INVALID_STATE` — `api_routes.py:206-207`
> - §3.1 — insert — ambiguity — approving a fee above the cap → `ERR_INVALID_STATE` — `api_routes.py:246-247`
> - §3.1 — revise — mismatch — no endpoint performs the buyer's takeover, so `resale_status` never returns to `NONE`; re-filing from `APPROVED` → `ERR_INVALID_STATE` — `api_routes.py:224-252`
> - §3.2 — revise — mismatch — a `CLOSED` account **blocks** a shop change (PRD said the opposite); non-`ACTIVE` target shop / closed account → `ERR_INVALID_STATE` — `api_technicians.py:110-121`
> - §3.2 — revise — mismatch — trade exit blocks on **any** `CONFIRMED` order, not only one holding unreserved stock — `api_technicians.py:155-158`
> - §3.2 — insert — ambiguity — the exited-technician check precedes the ownership comparison — `api_technicians.py:77-79,101-103`
> - §3.2 — revise — mismatch — `active_technician_count` counts `ACTIVE` technicians at the shop regardless of the shop's own `shop_status`; suspension does not reduce it — `recompute.py:17-23`
> - §3.3 — insert — ambiguity — applicant/shop mismatch → `ERR_INVALID_REQUEST` — `api_applications.py:40-42`
> - §3.3 — insert — ambiguity — a revolving application records `requested_term_months` as 0 — `api_applications.py:55`
> - §3.3 — insert — ambiguity — score-hurdle and unverified-employment refusals → `ERR_INVALID_STATE` — `api_applications.py:117-127`
> - §3.3 — insert — ambiguity — withdraw on a decided application → `ERR_INVALID_STATE` — `api_applications.py:150-151`
> - §3.3 — revise — ambiguity — the stale-version assertion is evaluated **before** the `APPROVED` check at mint — `api_applications.py:186-190`
> - §3.3 — insert — ambiguity — the account's `term_months` comes from `approved_term_months` — `api_applications.py:215`
> - §3.3 — insert — ambiguity — a successful mint advances the application's own `version` — `api_applications.py:234`
> - §3.4 — insert — ambiguity — `sale_iso_week` is stamped at creation — `api_sales_orders.py:88`
> - §3.4 — insert — ambiguity — buyer whose `home_route_id` differs → `ERR_INVALID_STATE` — `api_sales_orders.py:195-196`
> - §3.4 — insert — ambiguity — PATCH is DRAFT-only (`ERR_INVALID_STATE`) and re-runs stock + reprices — `api_sales_orders.py:126-140`
> - §3.4 — revise — mismatch — settlement has **no** "charge allocated to a reversed payment" condition — `api_sales_orders.py:246-252`
> - §3.4 — insert — ambiguity — cancel outside DRAFT/CONFIRMED → `ERR_INVALID_STATE` — `api_sales_orders.py:256-257`
>
> **§3.5–§3.9**
> - §3.5 — insert — ambiguity — accrual runs on every request; baseline for a charge-less account is the week of its `created_at`; one charge row per evaluation; `opening_balance_cents` is `principal_balance_cents` — `recompute.py:236-266`
> - §3.5 — insert — ambiguity — booking is not gated on the account's posture — `api_payments.py:22-49`
> - §3.5 — insert — ambiguity — collect on `CHARGED_OFF` → `ERR_ACCOUNT_NOT_ACTIVE`; collect `MISSED` on non-`DELINQUENT` → `ERR_ACCOUNT_NOT_DELINQUENT` — `api_payments.py:124-130`
> - §3.5 — insert — ambiguity — miss that is not overdue, or on a non-ACTIVE/SUSPENDED account → `ERR_INVALID_STATE` — `api_payments.py:166-171`
> - §3.5 — insert — ambiguity — cancel of a non-`BOOKED` payment → `ERR_PAYMENT_NOT_BOOKED` — `api_payments.py:107-108`
> - §3.6 — insert — ambiguity — the investment ceiling is enforced at creation as well as submission — `api_product_orders.py:72-73`
> - §3.6 — insert — ambiguity — ship with a still-`HELD` pledge → `ERR_INVALID_STATE` — `api_product_orders.py:149-151`
> - §3.6 — insert — ambiguity — zero-quantity ordered lines post nothing and create no position — `api_product_orders.py:157-159`
> - §3.6 — insert — ambiguity — allocate with a non-`BOUND` pledge → `ERR_INVALID_STATE` — `api_product_orders.py:180-182`
> - §3.6 — insert — ambiguity — a pledge's `line_index` is its filing position; the DRAFT test precedes account resolution; oversubscription is cumulative over non-`RELEASED` pledges; advancing a non-`HELD` pledge → `ERR_INVALID_STATE` — `api_pledges.py:43-47,55-66,68-77,113-114`
> - §3.7 — revise — mismatch — `run_priority` is validated but does not change the guard; a product is plannable once in its lifetime — `api_launch.py:39-41`
> - §3.7 — insert — ambiguity — open order count = DRAFT/CONFIRMED/DELIVERED; `priority_score` is an unrounded JSON number; `allocation_status` is always `ALLOCATED` — `api_launch.py:16-26,55`
> - §3.7 — insert — ambiguity — non-`IN_SERVICE` target → `ERR_INVALID_STATE`; over-large move → `ERR_INVALID_REQUEST`; response carries the target row — `api_launch.py:89-92,123`
> - §3.8 — revise — mismatch — `apply_to_account_id` is stored for a `WARRANTY_REPLACEMENT` (resolved as a reference) but never used — `api_warranty.py:50-53,153-165`
> - §3.8 — insert — ambiguity — an idempotent replay returns the existing claim with 201 — `api_warranty.py:36-40`
> - §3.8 — insert — ambiguity — a `CLAIM` filed without an account → `ERR_ACCOUNT_NOT_FOUND` at approval — `api_warranty.py:154-155`
> - §3.8 — revise — mismatch — the credit basis allocates 0 and writes no account — `api_warranty.py:161-162`
> - §3.9 — revise — mismatch — closure with a non-zero balance → `ERR_ACCOUNT_HAS_BALANCE` — `api_accounts.py:96,100`
>
> **§4**
> - §4 — insert — mismatch — the inventory-position write returns 201 for an adjustment as well as a creation — `api_inventory.py:53`
> - §4 — insert — ambiguity — the action vocabularies for all twelve action endpoints (`ENROLL/CERTIFY/RECERTIFY`, `ACTIVATE/SUSPEND/REINSTATE/RETIRE`, `DEVELOP/SURRENDER`, `FILE/APPROVE/DECLINE`, `CHANGE_SHOP/CONFIRM_SHOP/CANCEL_SHOP/EXIT_TRADE`, `REVIEW/APPROVE/DECLINE/WITHDRAW/REOPEN`, `SUSPEND/REINSTATE/CHARGE_OFF/SETTLE_CHARGE_OFF/CLOSE`, `COLLECT/MISS/REVERSE/CANCEL`, `CONFIRM/DELIVER/SETTLE/CANCEL`, `SUBMIT/APPROVE/REJECT/REOPEN`, `SUBMIT/SHIP/RECEIVE/ALLOCATE/CANCEL`, `BIND/RELEASE`) and the product-update payload — the corresponding `api_*.py` handlers
> - §4 — revise — mismatch — `GET /routes`, `GET /routes/{id}` and `GET /warranty-claims` are "Any except Technician" — `api_routes.py:16-17`, `api_warranty.py:16-17`
>
> ## Implementation gaps found (not papered over with prose)
>
> 1. **`calc.warranty_principal_allocation` (`implementation/calc.py:377`) is dead code** — never called anywhere. The PRD's credit-basis rule for `WARRANTY_REPLACEMENT` (credit the allocation away from an account, capped at its principal) ships unimplemented; `api_warranty.py:161-162` hard-codes `allocated = 0`. The observable outcome coincides only because `warranty_credit_amount_cents` is itself 0 for that claim kind — I pinned the observable behavior, not the helper's described crediting. `lookup.route_of_franchisee` (`implementation/lookup.py:26`) is likewise defined but never called.
> 2. **The charge-off sweep's `ACTIVE` branch is effectively unreachable** — `recompute.py:280-281` skips an `ACTIVE` account unless `missed_payment_count >= 3`, but an `ACTIVE` account can never hold a missed payment (a miss moves it to `DELINQUENT`, and the cure requires `missed_payment_count == 0`). The sweep therefore only ever flips `DELINQUENT` accounts; the gate looks like it was meant to read "three payments delinquent" rather than "status ACTIVE".
> 3. **`_settle` omits a PRD-required condition** — the PRD required settlement to fail when the order "carries no outstanding charge allocated to a reversed payment"; `api_sales_orders.py:246-252` only checks for OPEN/SUBMITTED claims. I removed the clause from the PRD because implementation is the alignment target, but the check itself is genuinely absent.
> 4. **`api_applications._approve`'s `ERR_CREDIT_REQUEST_ABOVE_CAP` check (`api_applications.py:169-170`) is unreachable** — filing already refuses any request above the cap, so no application can reach a decision carrying one. Harmless (the PRD requires the rule at both points), but it can never fire.
> 5. **Catalogue/behaviour drift on `ERR_ACCOUNT_NOT_DELINQUENT`** — its only callsite is collecting a `MISSED` payment on a non-delinquent account (`api_payments.py:128`), while its message in `errors.py:97` still says "The cure requires a DELINQUENT credit account". The PRD now matches the behaviour; the message string was not changed (implementation is read-only for this step).

Orchestrator verification:
- **`diff -q PRD_FINALIZED.md PRD_COMPLETED.md` → files DIFFER**, so Step 9 was not a silent no-op (the known `cp`-then-edit failure mode leaves a byte-identical file, not a truncated one).
- Line counts: PRD.md 1409 → PRD_FINALIZED.md 1424 → PRD_COMPLETED.md **1516**. Ends cleanly at the §5 error table.
- **`implementation/` untouched by Step 9**: newest impl source `1790848646` (09:57:26) and newest test source `1790849073` (10:04:33) are both older than `results.1.json` (`1790849771` = 10:16:11). Programmatic check across `implementation/*.py`, `implementation/*.sh`, `test_suite/*.py`, `test_helpers/*.py` for any file newer than the results → **NONE**, so the 8-round sweep remains valid evidence for the shipped code.

## Final verification sweep + pipeline completion — 2026-10-01T10:53:00.000Z

**Independent 8-round sweep re-run by the orchestrator** (not the Step 7 subagent), launched as a background job after Step 7, on the exact command the pipeline specifies:

```
prd-bench-local-run --start-command "cd .../workspace/implementation && bash start.sh" \
  --test-dir .../test_suite --isolation per-test-server --timeout 120 --test-timeout 30 \
  --results-file .../workspace/implementation/results.${i}.json     # i = 1..8, concurrent
```

Result: **8/8 rounds at 90/90, zero failures.** Per-round wall time ~165 s (all 8 concurrent). Round 1's own log line reports `Duration: 164.8s`.

Because `--isolation per-test-server` restarts the server via `start.sh` before every individual pytest test, this sweep exercised **720 successful fresh-process boots** (90 tests × 8 rounds) — direct evidence that the implementation boots cleanly from a cold process every time, with in-memory-only state and zero seeding.

**Sweep validity**: a programmatic mtime check across `implementation/*.py`, `implementation/*.sh`, `test_suite/*.py` and `test_helpers/*.py` found **no source file newer than the results files**, and Steps 8 and 9 (documentation-only) did not touch `implementation/` — so this evidence describes the shipped code, not a stale revision. (`__pycache__` excluded, per the known directory-mtime false positive.)

**Output contract — all artifacts present:**
- `SCAFFOLD.yaml` (2536 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (18 instances), `SCAFFOLD_CORNER_DESIGN.yaml` (74 instances across all nine guide sections)
- `test_helpers/` (10 modules), `test_suite/` (conftest + 19 files, 90 tests)
- `workspace/INSTRUCTION.md`, `workspace/PRD.md` (1409), `workspace/PRD_FINALIZED.md` (1424), `workspace/PRD_COMPLETED.md` (1516)
- `workspace/implementation/` — 24 Python modules (~3886 lines), `start.sh`, `requirements.txt`, `results.1..8.json`

**Pipeline complete.** Final state: 90 tests, all passing across 8 concurrent rounds under per-test-server isolation.

### Carried-forward notes (not blocking; recorded for downstream consumers)

1. **One difficulty instance deliberately untranslated**: `Difficulty/dual_variant_calc/dual_variant_finance_charge_basis_on_lease_account`. The design recipe asserts a 60-cent revolving-vs-lease accrual divergence that PRD §3.5's own accrual rule does not derive (both accounts accrue the payment's `charge_applied_cents`). Skipped under the PRD-first two-condition filter rather than weakened. Suite size is therefore 90, not 91.
2. **One §1.9 corner instance is an `excluded_because:` stub** and correctly has no test.
3. **Implementation gaps Step 9 found and reported but did not paper over** — see the Step 9 entry above: `calc.warranty_principal_allocation` and `lookup.route_of_franchisee` are dead code; the charge-off sweep's `ACTIVE` branch is unreachable; `_settle` omits a condition the original PRD required (the clause was removed in `PRD_COMPLETED.md` to match the implementation, since implementation is the alignment target); the approve-time `ERR_CREDIT_REQUEST_ABOVE_CAP` check is unreachable; and `ERR_ACCOUNT_NOT_DELINQUENT`'s message string still describes the pre-alignment semantics.
4. **PRD §2.9 constant pinning** (orchestrator edit, pre-Step-6): `CREDIT_ABSOLUTE_CAP_CENTS` = 2000000, `FRANCHISEE_RESALE_FEE_CAP_CENTS` = 900000 — both were previously named but never valued, the known Step 5/6 drift source.
