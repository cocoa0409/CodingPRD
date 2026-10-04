# Worklog — task_3336_tool_fleet_management_subscription_jobsite_service

## Step 1: Create Task Directory — 2026-09-30T21:31:00.000Z

Pre-allocated task directory `tasks/task_3336_tool_fleet_management_subscription_jobsite_service/` confirmed present with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T22:08:00.000Z

A `worklog.md` and `workspace/` directory already existed in the task dir (created at 21:31–21:32, before my writes at 22:04+) — left untouched as they're not part of my assignment.

Final lint verdict:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     29
  Calls scanned (§1.8+§1.9):  474

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3336_tool_fleet_management_subscription_jobsite_service/`):

- **SCAFFOLD.yaml** — §1.0–§1.7 only (no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level key `scaffold_difficulty_design`
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top-level key `scaffold_corner_design`

Counts:
- **Endpoints: 57** (deliberately above the Expert 20–32 band per the "much harder than expert level" instruction; note this exceeds the ~40-endpoint comfort threshold from prior impl-gen experience — a deliberate trade-off for difficulty)
- **Entities: 14** (ContractorAccount, RateCard, ToolModel, FleetAgreement, ToolAsset, Jobsite, UsageEvent, LoanerUnit, RepairTicket, TheftClaim, ConsumableProduct, ConsumableOrder, SupportCase, EndOfTermSettlement)
- **Errors: 16; Calculations: 7; State machines: 8; Validations: 12 priority levels; Roles: 6; OCC concurrency rules: 2**
- **§1.8: 19 instances** (9 rules × 2, plus combinatorial_formula carries 3 — one per mode (a) tiered/proration, (b) per-line pack rounding, (c) pinned theft-cost evaluation order)
- **§1.9: 29 active instances + 5 excluded_because stubs** (53 unique names across both files, verified)

Difficulty architecture: pricing-engine primary with quota-allocation secondary; cyclic state machines (repair reopen loop, account suspend/reinstate, loaner AVAILABLE→DISPATCHED→RETURNED→AVAILABLE), two transitive cascades (ticket close 3-deep via loaner two-hop + asset→jobsite; theft approval claim→asset→jobsite/agreement/account), dual-variant pairs in different domains (utilization ACTUAL 20.00 vs PROJECTED 37.50; settlement provisional 80000 vs final 40000), validation priority conflicts on distinct category pairs (state>fiscal; temporal>constraint), boundary precision (capacity `>=`, 48h inclusive window), two interval-overlap rules with opposing semantics (half-open jobsite windows vs closed rate-card intervals), compensating invariants on distinct quantities (jobsite counts vs fleet_size_target), and segregation of duties on theft claims. All formula-derived asserts were executed in Python and match the pinned literals.

## Step 3: Copy Shared Files — 2026-09-30T22:09:00.000Z

Copied ./INSTRUCTION.md → tasks/task_3336_tool_fleet_management_subscription_jobsite_service/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T04:13:09.893088376Z

Both are false positives ("around" inside "turnaround" — the grep was word-boundary-less). All contracts pass. Now let me verify Contract 2 rule coverage by walking the scaffold rule tables against the PRD.

Contract 2 verification walkthrough:

1. **Validations priority** — §2.8 states the full 12-level ordering in prose. ✓
2. **OCC rules** — §2.7 names both write operations (adjust-fleet, elect-end-of-term), `expected_agreement_version`, `ERR_STALE_VERSION`, HTTP 412. No race framing. ✓
3. **Cross-entity side effects** — account suspend/reinstate cascades with version increments (§3.1); ticket close cascades (loaner two-hop, asset redeploy, jobsite count, balance credit) (§3.6); theft approve cascade (asset LOST, jobsite count, deductible to balance) (§3.7); clock sweeps (§2.5). ✓
4. **`applies_to` scopes** — credit checks name all three operations (§3.1, §3.8); window checks name all three (verify/elect/reopen); duty segregation names decide; application-approval names submit; duplicate names all five create paths (§3.1, §3.2, §3.6, §3.8). ✓
5. **Field-level structured content** — `UsageEvent`/`EndOfTermSettlement` `updated_at`/`version` absence stated (§2.4); defaults (status at birth, balance 0, `billed_this_month_cents` 0, `deployed_asset_count` 0, `reopen_count` cap 2, `final_amount_cents` null until finalized — the "null until finalized" is expressed via "commits ... `finalized` becomes true"; the provisional/final distinction is in §3.9). ✓
6. **Sibling-branch symmetry** — transfer confirm vs cancel-transfer both fully specified; decide APPROVE vs DENY both specified; review APPROVE vs REJECT both; finalize BUYOUT/RETURN/RENEWAL all three branches. ✓
7. **All transitions** — all state machine transitions from scaffold are covered in §3.1–3.9 (verified above: all states present; each `from → to` pair narrated).
8. **All calculations** — monthly_fleet_billing (§3.3, tier split + min fee + sum + prorate + floor, both variants), repair_turnaround_penalty (§3.6, ceil days, daily credits 2500/9000, cap 50000), theft_replacement_cost (§3.7, age bands 100/70/40 pct, deductible 10% floor 50000 cap 250000, coverage cap 1000000), fleet_utilization (§3.5, 480-minute workday, clamp, both modes), consumable_order_total (§3.8, per-line ceil, no merge rule), end_of_term_settlement (§3.9, BUYOUT 20%, RETURN assessed_damage, RENEWAL 0, provisional vs final), loaner_allocation (§3.6, eligibility + created_at ranking + empty-pool error). ✓
9. **Endpoint side effects** — all covered in workflow narratives.

One point to double-check: `final_amount_cents` "null until finalized" — my §3.9 says "the result is committed to `final_amount_cents` and `finalized` becomes true", which implies it's unset before. Adequate.

Done. Final report.

---

**Generation complete.**

- **Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3336_tool_fleet_management_subscription_jobsite_service/workspace/PRD.md`
- **Line count:** 266 lines (endpoint table has 57 rows covering all 53 scaffold endpoints + header; error table has all 16 error codes)
- **Section list:**
  - §1 Introduction (2 paragraphs)
  - §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Resource Identity and Common Properties, 2.5 The Logical Clock and the Calendar Month, 2.6 Money/Precision/Rounding, 2.7 OCC on Fleet Agreements, 2.8 Validation Order, 2.9 Nested Paths and Cross-Account Scoping
  - §3 Business Logic: 3.1 Accounts & Credit Ledger, 3.2 Rate Cards & Catalog, 3.3 Agreements/Activation/Billing, 3.4 Fleet Sizing, 3.5 Jobsites/Deployment/Transfers/Usage, 3.6 Repair & Loaners, 3.7 Theft Claims, 3.8 Consumables & Engineering Support, 3.9 End of Term
  - §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Hard Contract reports:**
- Contract 1 Field-Name Coverage: 88 required identifiers (entity fields + request inputs + query/path params + output scalar keys), 88 present in backticks, 0 missing — PASS (two passes run; first pass found 4 missing — `account_id`, `agreement_id`, `asset_id`, `option` — repaired in §3.3/§3.5/§3.7/§3.9, second pass clean)
- Contract 2 Rule Coverage: all 12 validation priorities expressed in ordered prose (§2.8); both OCC rules expressed with write operation + `expected_agreement_version` + `ERR_STALE_VERSION`/412 (§2.7); all state-machine transitions with preconditions/error ids and side effects; all 7 calculations with pinned evaluation order and exact constants (3d/5d SLA, 2500/9000 daily credits, 50000 cap, 10% deductible with 50000 floor / 250000 cap, 1000000 coverage cap, 480-minute workday, 20% buyout); all `applies_to` scopes enumerated; `UsageEvent`/`EndOfTermSettlement` `updated_at`/`version` absence stated — PASS
- Contract 3 §3 Path Purity: 429 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path tokens — PASS

**Fidelity confirmation:** Every SCAFFOLD §1.1 entity field (all 14 entities), §1.2 state machine transition (incl. cascades and the loaner two-hop), §1.3 calculation (both variants of billing and settlement, both utilization modes), §1.4 validation rule with priority order, §1.5 endpoint (all 53, incl. the logical-clock capability), §1.6 error id, and §1.7 role (with entity-backed vs opaque identity prose) has verbatim PRD coverage. The withheld design-index files were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-10-01T04:39:18.622219237Z

Note: first two spawn attempts failed with a model endpoint error (k3-wave not available to subagents); succeeded on third attempt with model override. A fourth interim subagent completed the inventory but wrote no files before terminating; final subagent regenerated from scratch. Orchestrator verified on disk: 23 .py files py_compile clean, 71 tests, 71 Design: tags.

Subagent summary (verbatim):

## Summary

**Test infrastructure** (`test_helpers/`, 8 files): types.py (289), api_client.py (239), api_errors.py (44, registers all 16 error IDs with the framework), assertions.py (163), factories.py (114), constants.py (21), test_users.py (44, with per-instance builders for entity-backed ContractorManager/JobsiteSupervisor roles), fixtures.py (207, composite fixtures: `setup_agreement_with_assets`, `setup_deployed_asset`, ticket drivers, claim helpers, `setup_police_verified_claim`), plus `__init__.py` barrel.

**Test suite** (`test_suite/`, 15 test files + conftest.py):

| File | Lines | Tests |
|---|---|---|
| test_01_utilization_variants | 69 | 2 |
| test_02_end_of_term_variants | 86 | 2 |
| test_03_combinatorial_formulas | 183 | 6 |
| test_04_cyclic_state_machines | 129 | 4 |
| test_05_cascades | 122 | 4 |
| test_06_priority_pairs | 127 | 4 |
| test_07_boundaries | 100 | 4 |
| test_08_cross_entity_dependencies | 119 | 4 |
| test_09_overlap_and_invariants | 202 | 8 |
| test_10_corner_entities | 84 | 5 |
| test_11_corner_state_machines | 144 | 7 |
| test_12_corner_calculations | 108 | 4 |
| test_13_corner_validations | 150 | 6 |
| test_14_corner_endpoints | 118 | 4 |
| test_15_corner_rbac_errors_envelope | 115 | 7 |

**Total tests: 71** covering all 48 non-stub design instances (19 difficulty × ≥2, 29 corner × ≥1). The 5 corner stubs (`excluded_because:`) were not translated; all their `difficulty_instance` pointers resolve.

**Skipped instances: none** — every non-stub instance passed the PRD-first two-condition filter; all asserted literals (billing 29000/58000/87000, SLA credit 18000/balance 2000, deductible 50000/approved 20000 at 13 months, utilization 20.00/37.50, settlement 80000→40000, renewal term 13/end 2027-10-01, etc.) trace to verbatim PRD sentences and match the design-index pre-computed values.

**Verification sweeps**: `py_compile` on all 23 files OK; Design-tag sweep — 48/48 instances tagged exactly, 0 missing, 0 extra, 0 difficulty instances under 2 tests; zero skip/xfail markers; verbatim-citation grep sweep against PRD.md clean (one citation fixed to verbatim wording). One design-fixture correction made during authoring: the 13-month-age theft claim must be *reported* at the advanced clock (reported_at anchors age), so the test reports/verifies at 2027-10-15 rather than reporting early.

## Step 6: Generate Implementation — 2026-10-01T04:56:08.215695497Z

Note: spawned with model override (opus) after the k3-wave endpoint proved unavailable to subagents in Step 5. Orchestrator verified on disk: 5 .py files + start.sh + requirements.txt, all py_compile clean.

Subagent summary (verbatim):

## Summary

**Files written** in `/home/ubuntu/github/CodingPRD/tasks/task_3336_tool_fleet_management_subscription_jobsite_service/workspace/implementation/`:

| File | Bytes |
|---|---|
| app.py | 55194 |
| services.py | 9016 |
| response.py | 4122 |
| store.py | 3885 |
| errors.py | 2164 |
| start.sh | 396 (executable) |
| requirements.txt | 11 |

**py_compile sweep**: all 5 `.py` files compile clean.

**Boot verification**: `PORT=18771 bash start.sh &` booted in ~3s, then exercised live:
- `POST /fleet/_clock/set_current_utc` → 200, confirms default logical clock `2026-09-01T00:00:00Z`
- Unauthenticated request → `ERR_UNAUTHENTICATED` (401) with the exact scaffold envelope
- Full cycle: account → rate card → tool model → agreement → adjust-fleet (2 assets) → activate billed **20000** (2 units × 10000 tier-1, full-month proration on Sept 1) → stale OCC → `ERR_STALE_VERSION` (412) → paginated asset list with `limit/offset/total_count/has_more` meta → utilization report → empty settlement array
- Deploy → usage event (90 min) → repair ticket → SLA breach close (+4 days vs LIGHT 3-day promise → **2500** credit, balance 20000→17500) → support case DOCUMENTED → consumable order with two under-filled lines of the same product → **2000** (per-line pack rounding honored, no merging) → submit/decide APPROVE → balance 19500
- Server and its child process killed by exact PID; port confirmed free

**All 57 endpoints** from the endpoint table are implemented (clock, 5 account ops, rate cards, tool models, 9 agreement ops, 3 jobsite ops, 8 asset ops, 8 repair-ticket ops, 4 loaner ops, 4 theft-claim ops, 7 consumable ops, 4 support-case ops, plus list/get endpoints).

**Key implementation decisions on PRD ambiguities**:
- **Boot state**: store starts completely empty; logical clock pinned at `2026-09-01T00:00:00Z`; no seeding anywhere.
- **Cancel-transfer origin**: not stored in the entity table — kept as an internal `_transfer_origin_jobsite_id` field on the asset (never serialized).
- **Adjust-fleet in DRAFT**: OCC enforced in both DRAFT and ACTIVE (field is non-optional per PRD §2.7); billing recompute only when ACTIVE, per scaffold side effects.
- **Billing with a missing rate card for a category**: skipped (contributes 0); billing date is the logical-clock instant in all cases (sweep bills on the first day of the new month, so cards effective from the 1st select correctly).
- **OCC checked even in DRAFT adjust-fleet** so a stale writer never mutates; `expected_agreement_version` is a required integer (missing → `ERR_VALIDATION` before existence checks, per priority 3).
- **Support-case overlap**: half-open `[scheduled_for, scheduled_for+2h)` against non-REJECTED cases at the same jobsite; rate-card overlap uses closed-interval intersection within the same category among ACTIVE cards.
- **Cross-account access by entity-backed roles** (ContractorManager/JobsiteSupervisor, whose X-User-ID is the account id) returns `ERR_NOT_FOUND` everywhere, per PRD §2.9's hiding rule; provider roles see all.
- **Activation's fleet-size precondition** (not mapped to a specific error ID in the error catalog) is raised as `ERR_VALIDATION` (400).
- **`created_at` uniqueness** for loaner allocation's "oldest first" ranking is guaranteed by a microsecond sequence tick layered on the logical clock, so ordering is stable even when the clock doesn't advance.
- **Reopen decrements the jobsite count only when the asset is DEPLOYED** (the normal path after close); the ticket-side `reopen_count`/`sla_breach_credit_cents` immutability rules are enforced exactly as specified.

## Step 7: Run Tests and Iterate — 2026-10-01T05:11:43.678397462Z

Orchestrator verification before logging: all 8 results.*.json show passed=71 total=71 failed=0 errors=0; implementation/*.py mtimes (04:46–04:53) all predate the final sweep results (05:10), confirming no post-sweep impl edits.

Subagent summary (verbatim):

All 8 rounds pass 71/71. Clean sweep achieved.

## Summary

**Iterations run: 3** (collection-error sweep → 70-failure sweep → clean sweep)

**Tests deleted: none.** Every failure traced to a test-artifact bug, not to PRD-silence or unique-derivability collapse.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added the missing `create_consumable_product(**overrides)` fixture (wraps `create_consumable_product_payload` + `api_client.create_consumable_product` with ADMIN headers, matching the existing fixture pattern). Four test modules imported it but it was never defined, causing collection failure.
- `test_helpers/factories.py` — replaced `id(defaults) & 0xFFFFFFFF:x` inside dict literals with a `_uniq()` counter helper; the `id(defaults)` self-reference is an `UnboundLocalError` under Python 3.14 (was silently tolerated before), which broke every payload factory and thus every test.
- `test_helpers/fixtures.py` — `drive_ticket_to_in_shop` now routes a `REOPENED` ticket directly to `receive` instead of `schedule-pickup`. PRD's endpoint table states "Receive a PICKUP_SCHEDULED or REOPENED unit into IN_SHOP", so the REOPENED leg never passes through schedule-pickup; the fixture was the bug, the implementation's state gate was PRD-correct.

**Fixes applied to `test_suite/`:**
- `test_08_cross_entity_dependencies.py::test_deploy_unblocked_after_reinstate` — payment amount 4000 → 8500. Activation at 2026-09-16 prorates (PRD §3.3: 15/30 = 0.5 factor over the 67000 tier-split charge, floored to 33500), so 4000 left outstanding at 29500 > 25000 limit; reinstatement was correctly rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. 8500 pays down to exactly the limit per PRD §3.1.
- `test_10_corner_entities.py::test_agreement_end_date_computed_from_term` and `test_14_corner_endpoints.py::test_renewal_extends_term_and_returns_to_active` — `end_date` assertions now compare parsed instants (`_parse_iso`) instead of raw strings. PRD §2.4 pins the three-fractional-digit format only for `created_at`/`updated_at`; it is silent on `end_date`'s wire format, so the verbatim rule is the computed instant ("start_date plus term_months months"), not a specific serialization string.

**Fixes applied to `implementation/`: none** — the implementation was PRD-faithful in every failure investigated (billing proration math verified live: `billed_this_month_cents: 33500` on a scratch boot).

Final state: 8/8 parallel rounds at 71/71 passed, 0 failed, 0 errors.

## Step 8: Finalize PRD — 2026-10-01T05:11:50.264173381Z

SKIPPED. Step 7 exited with 0 deletions, 0 implementation/ fixes (only test_helpers/ and test_suite/ fixes). Per the skip condition, PRD.md already determines every behavior the implementation exhibits; no PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-10-01T05:35:25.944554899Z

Note: the first Step 9 subagent attempt produced PRD_COMPLETED.md (266→268 lines, 18 edits across 8 diff hunks) but was killed by the flaky model endpoint before returning its summary. A verification-only follow-up subagent audited every hunk against implementation/ and confirmed the file is complete and accurate; no fixes needed.

Verification subagent summary (verbatim):

## Verification Report

### Verdict per diff hunk (8 hunks — note: actual diff has 8 hunks, not 19; 19 appears to have counted changed line-groups)

1. **H1 — Pagination clamp/fallback (§2.3)** — **OK.** Matches `implementation/response.py:143-151` (`pagination_params`: try/except falls back to 10/0, `limit = max(1, min(100, limit))`, `offset = max(0, offset)`).
2. **H2 — `version` starts at 1 (§2.4)** — **OK.** All entity constructors initialize `"version": 1`, e.g. `implementation/app.py:331` (account), `:421` (rate card), `:549` (asset), `:889` (ticket).
3. **H3 — Clock backward sets + monotonic `created_at` tick (§2.5)** — **OK.** `implementation/store.py:26-32` (`advance_to` re-pins unconditionally; docstring "never moves backward — a past value simply re-pins") and `store.py:34-39` (`stamp()` adds a microsecond sequence tick).
4. **H4 — Flat-path contractor pre-filtering + cross-account `ERR_NOT_FOUND` hiding + theft-claim list provider-only (§2.9)** — **OK.** `implementation/app.py:709-710` (`list_assets` pre-filters by `asset_account_id(a) == uid` for ENTITY_ROLES), `app.py:1330-1331` (`list_support_cases` same), `app.py:62-68` (`scope_account` raises `not_found` for entity roles), `app.py:1107` (theft-claim list restricted to FleetAdmin/ClaimsAdjuster).
5. **H5 — Suspension freeze blocks QUALITY_CHECK close but not supervisor reopen (§3.1)** — **OK.** `implementation/app.py:980-982` (`close_ticket` calls `require_ticket_agreement_active`), while `app.py:1005-1024` (`reopen_ticket`) has no agreement-active gate.
6. **H6 — Rate-card miss skips category (§3.2)** — **OK.** `implementation/services.py:59-61` (`rc = _select_rate_card(...); if rc is None: continue`).
7. **H7 — `add_months` day-clamping (§3.3)** — **OK.** `implementation/services.py:27-32` (`d = min(dt.day, calendar.monthrange(y, m)[1])`).
8. **H8 — Zero-amount bills skip balance ledger entry (§3.3 activation + billing + §3.4)** — **OK.** `implementation/services.py:80-85` (`commit_billing`: sets `billed_this_month_cents` always; `if amount:` guards the balance add).
9. **H9 — Invalid utilization `mode` rejected with `ERR_VALIDATION` (§3.5)** — **OK.** `implementation/app.py:644-646`.
10. **H10 — SLA credit wording change to "ordinary never-below-0 flooring" (§3.6 close)** — **OK.** `implementation/app.py:998-999` (`if credit > 0: add_balance(...)`), and `services.py:218-221` (`add_balance` floors at 0). Behaviorally equivalent to the original wording; describes impl accurately.
11. **H11 — Loaner dispatch stamps no per-dispatch timestamp (§3.6)** — **OK.** `implementation/app.py:955-957` sets only `status`/`assigned_ticket_id` (+ `touch`); the loaner serializer `app.py:230-235` exposes no dispatch timestamp.
12. **H12 — `theft_claim_count` as derived count, no explicit mutation on sweep (§3.7)** — **OK.** `implementation/store.py:89-94` (computed from claim statuses); sweep at `services.py:230-233` only flips status.
13. **H13 — Denial drops derived count on its own (§3.7 adjudication)** — **OK.** `implementation/app.py:1142-1145` (DENY just sets status; count derives).
14. **H14 — Deductible floor-then-cap order (§3.7)** — **OK.** `implementation/services.py:117-118` (`min(max(50000, deductible), 250000)` — floor first, then cap; a 50000-floored value survives since 50000 < 250000).
15. **H15 — Support-case overlap is cross-account at the jobsite (§3.8)** — **OK.** `implementation/app.py:1311-1316` iterates all support cases filtered only by `jobsite_id` and non-REJECTED status, with no account filter.
16. **H16 — `assessed_damage_cents` absent treated as 0 (§3.9)** — **OK.** `implementation/app.py:599-601` (`opt_field(..., None)`) + `services.py:177` (`int(assessed_damage_cents or 0)`).
17. **H17 — `GET /fleet/assets` table row note (§4)** — **OK.** Restates the behavior verified in H4 (`app.py:709-710`).
18. **H18 — `GET /fleet/support-cases` table row note (§4)** — **OK.** Restates `app.py:1330-1331`.

That is 18 distinct edits within 8 `@@` hunks (several hunks bundle multiple paragraphs). No hunk is truncated or half-finished; none contradicts the implementation.

### Spot-check of 10 behaviors (PRD_COMPLETED.md vs implementation/)

1. **Billing formula** — pinned: tier split → per-category min fee → sum → prorate → single floor; sweep uses factor 1. Matches `services.py:48-77` exactly. OK.
2. **Repair SLA penalty** — ceil breach hours to days, ×2500 (LIGHT) / ×9000 (HEAVY), cap 50000 last. Matches `services.py:88-97`. OK.
3. **Theft deductible** — 10% of depreciated, half-up, floor 50000 then cap 250000. Matches `services.py:104-118`. OK.
4. **Loaner allocation ranking** — AVAILABLE, same `tool_model_id`, oldest `created_at` first, unique stamps so no tie-break. Matches `services.py:186-194`. OK.
5. **OCC handling** — `expected_agreement_version` mismatch → `ERR_VERSION_STALE`, checked before state validation. Matches `app.py:532-536` and `:572-575`. OK.
6. **Pagination defaults** — limit 10 (clamped 1..100), offset 0 (floored), malformed → defaults. Matches `response.py:143-151`. OK (pinned by H1).
7. **Cross-account hiding** — entity roles get `ERR_NOT_FOUND` on foreign resources, flat lists pre-filtered. Matches `app.py:62-68, 709-710, 1330-1331`. OK (pinned by H4).
8. **Support-case overlap window** — half-open 2-hour window, non-REJECTED cases, same jobsite regardless of account. Matches `app.py:1309-1316` (`start < c_end and c_start < end`). OK (pinned by H15).
9. **Rate-card overlap** — closed-interval overlap vs existing ACTIVE card of same category → `ERR_WINDOW_OVERLAP`. Matches `app.py:409-412`. OK.
10. **Settlement provisional vs final** — provisional computed at election over then-current billable fleet; final recomputed at finalization before any retirements; RETURN uses `assessed_damage_cents` (0 if absent); RENEWAL final is 0 with term +12. Matches `app.py:586-591, 607-634` and `services.py:172-183`. OK.

### Residual silence/mismatch found
None. The spot-check found no PRD-vs-impl divergence beyond what PRD_COMPLETED.md already pins.

### Fixes applied to PRD_COMPLETED.md
**None.** The file at `workspace/PRD_COMPLETED.md` was complete and accurate; every one of its edits is a legitimate ambiguity-pin or mismatch-revision consistent with `implementation/`.
