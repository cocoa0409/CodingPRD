# Worklog — task_3309_membership_based_furniture_retail_design_services_trade

## Step 1: Create Task Directory — 2026-09-30T19:20:00.000Z

Pre-allocated task directory `./tasks/task_3309_membership_based_furniture_retail_design_services_trade/` verified to exist with `workspace/` inside. No new index computed (per command args).

## Step 2: Generate Scaffold — 2026-09-30T19:41:00.000Z

All three files are written, lint is clean, and counts verified. Summary:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_3309_membership_based_furniture_retail_design_services_trade/`)

| File | Bytes | Lines |
|---|---|---|
| `SCAFFOLD.yaml` | 58,822 | 762 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 47,252 | 552 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 62,698 | 750 |

`SCAFFOLD.yaml` contains only §1.0–§1.7 keys (no difficulty/corner top-level keys); the two design files each carry their single mandated top-level key.

## Structure

- **Entities: 11** (Expert band, flat topology, all-FK reverse-reachable): Member, TradeAccount, Gallery, Product, SourceBook, Order, OrderLine, ProductionSlot, DesignConsultation, DeliveryAppointment, ReturnRequest
- **Endpoints: 39** (kept under the >40 overshoot threshold per prior pipeline experience), including two test-driving endpoints (`/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z, `/_ops/run_daily_cycle`)
- **Errors: 35** (24 domain-specific + 11 per-entity NOT_FOUND)
- **Roles: 8**, Member/TradeDesigner entity-backed, rest opaque
- **9 state machines** with cyclic shapes on Member (GRACE→ACTIVE renewal loop) and ProductionSlot (COMMITTED→OPEN release cycle), depth-3 cascades on Member-lapse and SourceBook-release, OCC concurrency rules on CONFIRMED-order line mutation
- **§1.8: 19 instances** across all 9 difficulty rules (every rule ≥2; combinatorial_formula has 3 covering modes a/b/c). All numeric asserts are pre-computed literals (e.g., fee-waiver boundary 1000000 vs 999999; per-line restock 300 vs sum-round 301; day-30 cancel boundary).
- **§1.9: 44 instances (42 active + 2 excluded stubs)** across all 9 claim-extraction-guide sections.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(414 calls scanned, 0 violations. One fix applied mid-run: quoted bracketed `errors[ERR_X]` grounds entries in the corner file that broke YAML flow-sequence parsing; no design content changed.)

## Step 3: Copy Shared Files — 2026-09-30T19:42:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3309_membership_based_furniture_retail_design_services_trade/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T19:50:00.000Z

The PRD is written and verified. Summary:

## Output

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_3309_membership_based_furniture_retail_design_services_trade/workspace/PRD.md` — 344 lines, ~49.6 KB.

## Section list

- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (all 8 roles with identity prose), 2.2 API Response Structure (verbatim contract block — byte-checked against `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Scheduled Operations (5-step daily cycle ordering, startup default 2026-09-01T00:00:00Z), 2.6 Money/Units/Rounding (incl. the pinned 150+150=300 restocking example), 2.7 Pricing Tracks & tier snapshot, 2.8 OCC (`expected_order_version` → `ERR_STALE_VERSION` 412, optional-and-ignored in QUOTE), 2.9 Nested Resource Retrieval (left-to-right 404s), 2.10 Validation Ordering (8-tier priority)
- §3 Business Logic (8 subsections): membership lifecycle, trade program, catalog & source books, orders & pricing engine, custom production, design consultations, white-glove delivery, returns
- §4 Endpoint Definitions — 39 rows, 4 columns (Method / Path / Description / Authorized Roles)
- §5 Error Code Catalogue — 34 rows, 2 columns

## Hard contract results

- **Contract 1 (Field-Name Coverage): PASS** — 83 required identifiers (all entity fields, endpoint inputs, query params, path params, common fields); initial pass missed `region`, which was added to §3.3 gallery-creation narrative; re-run shows 0 missing. Verified twice (yaml-driven diff + independent probe of 80 tokens).
- **Contract 2 (Rule Coverage): PASS** — all 34 error IDs and all state/enum values appear backticked; 48 targeted rule probes pass (OCC write-endpoint + field + error_id + 412; all transition preconditions/side-effects incl. Cascade A hops 2/2b/3 and Cascade B hops 2/3 + archival; all 7 calculations with constants 17500 / 19900 / 14900 / 1000000 / 50000 / 25000 / 25% / 30% / 40% / 10% / 1.25 / 15% / 30-min buffer / 365d / 30d grace / 30d refund inclusive / 21d print lead; validation priority ordering; applies_to scopes; version-increment and updated_at semantics; sibling-branch symmetry for cancel/renew/advance/record-outcome/settle pairs).
- **Contract 3 (§3 Path Purity): PASS** — 422 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combos.

## Coverage confirmation

Every scaffold entity (Member, TradeAccount, Gallery, Product, SourceBook, Order, OrderLine, ProductionSlot, DesignConsultation, DeliveryAppointment, ReturnRequest), all 39 endpoints, all 34 errors, and all 8 state machines (Member, TradeAccount, Order, ProductionSlot, DesignConsultation, DeliveryAppointment, SourceBook, ReturnRequest) are covered in prose. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or referenced.

## Step 5: Generate Unit Tests — 2026-09-30T20:08:00.000Z

Clean — no skip markers, no scaffold references. Done.

## Summary

**Task 3309** — Membership-Based Furniture Retail, Design Services & Trade Program. Test infrastructure and suite generated per the design-index-only contract.

### Coverage
- **Queue A (Difficulty): 19/19 instances translated, each with ≥2 tests** (19 primary + 19 second-pass)
- **Queue B (Corner): 42/42 non-stub instances translated, each with ≥1 test**
- **2 corner stubs correctly not emitted**: `Corner/calculations/restocking_rounding_corner_covered` (owned by Difficulty `restocking_per_line_round_then_sum`) and `Corner/errors/stale_version_error_covered` (owned by `occ_stale_version_rejected_on_confirmed_amendment` — cross-reference verified to resolve)
- **0 instances skipped** — every instance passed the PRD-first two-condition filter; the PRD is unusually precise (pinned evaluation orders, boundary inclusivity, and the §2.10 validation-priority ordering are all in prose)
- **81 test functions total**, each with exactly one `Design:` tag resolving to a real instance, and every docstring citation machine-verified to grep verbatim against `PRD.md` (0 failures)

### Files
- `test_helpers/` — `types.py` (13 entities, 13 enums, role enum), `api_client.py` (all 38 endpoints), `api_errors.py` (35 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance `make_member_headers` / `make_trade_designer_headers` for the two entity-backed roles), `fixtures.py` (composite helpers incl. `deliver_order`, `setup_delivered_stock_order`, `setup_confirmed_custom_order`, `setup_in_production_custom_order`, `setup_delivered_custom_order`, `setup_member_quote_with_consultation`, `setup_requested_return`), `__init__.py` barrel
- `test_suite/` — `conftest.py` + 8 test files: `test_01_membership.py`, `test_02_pricing.py`, `test_03_orders.py`, `test_04_production.py`, `test_05_delivery.py`, `test_06_returns.py`, `test_07_validation_and_access.py`, `test_08_depth_second_pass.py`

### Verification
- `py_compile` passes on all 18 files ("SYNTAX OK")
- Tag audit: no missing/short instances, no unknown tags, no stub tags emitted, every test has exactly one tag
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code
- Suite not executed (no implementation exists yet), per instructions

## Step 6: Generate Implementation — 2026-09-30T20:15:00.000Z

Implementation complete for task 3309 (membership-based furniture retail / RH analog).

## Files written

All in `/home/ubuntu/github/CodingPRD/tasks/task_3309_membership_based_furniture_retail_design_services_trade/workspace/implementation/`:

- `start.sh` — guarded Flask install (no-op when flask importable), `exec python3 app.py`, `$PORT` default 10000, binds 0.0.0.0
- `requirements.txt` — flask>=3.0
- `core.py` — in-memory `db` dicts (empty at boot, no seeding), logical clock defaulting to exactly `2026-09-01T00:00:00Z`, ISO-8601 UTC 3-fractional-digit formatting, Decimal-based round-half-up money helpers, full error catalog with exact HTTP statuses from the scaffold, envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta), `X-User-ID`/`X-User-Role` auth, common `id`/`created_at`/`updated_at`/`version` handling
- `services.py` — pricing engine (pinned eval order: promo 0.90 → TRADE flat off base ignoring promo → MEMBER 0.75 off promo price → RETAIL promo price; per-unit round-half-up then × qty), white-glove fee (19900 member/retail, waived ≥1000000 subtotal; 14900 trade never waived; 0 for empty QUOTE), custom deposits (0.5 rate / 50000 floor standard, 0.25 / 25000 trade), quote recompute from remaining COMPLETED consultations, Cascade A (lapse → cancel SCHEDULED consultations → recompute QUOTE expiry → re-price member QUOTE orders as RETAIL), Cascade B (release: archive other RELEASED books, toggle promo_active, re-price affected QUOTE orders), pinned 5-step daily cycle
- `app.py` — all 36 endpoints from the endpoint table

## Endpoint count

36 routes implemented (full §1.5 endpoint table, including `/_clock/set_current_utc` and `/_ops/run_daily_cycle`). [Orchestrator verification: 39 `@app.route` decorators on disk, matching the 39-endpoint table; subagent's count was a miscount.]

## Boot verification

- `python -m py_compile` passes on all three .py files
- Server launched via `bash start.sh` on port 19309 (PID saved, killed exactly that PID afterward — confirmed stopped)
- Verified live: member enrollment (fee 17500, net −17500), duplicate email 409, auth 401/403, member order with 25% pricing (100000 → 75000, fee 19900, quote_total frozen), zero-custom confirm → READY_FOR_DELIVERY, appointment → daily-cycle dispatch → COMPLETED → order DELIVERED, member savings recognized (gross 25000, net 7500), custom PREMIUM line (250000 base, charged 187500, deposit 93750), `ERR_DEPOSIT_REQUIRED` / `ERR_DEPOSIT_AMOUNT_MISMATCH` / confirm with exact deposit, slot commit → `reserved_production_minutes` 120, IN_PROGRESS advance, `ERR_LINE_NON_CANCELABLE`, `ERR_STALE_VERSION` (412) on CONFIRMED amendment, CONSUMED bubble-up → READY_FOR_DELIVERY and minutes released, GRACE → LAPSED daily-cycle cascade with `pricing_tier` flipping to RETAIL.

## Step 7: Run Tests and Iterate — 2026-09-30T20:32:00.000Z

All 8 rounds pass 81/81. Sweep progression was 9 → 25 → 72 → 76 → 81, with the final sweep clean across all 8 parallel rounds.

Summary:

- **Iterations run:** 5 sweeps (4 diagnostic rounds + 1 final clean confirmation).

- **Tests deleted:** none. Every failure traced to a test-artifact or implementation bug whose rule was PRD-covered and uniquely derivable; no PRD-silence or collapse-pattern deletions were needed.

- **Fixes applied to `test_helpers/`:**
  - `fixtures.py` — `import uuid as _uuid` while code used bare `uuid` (NameError on every fixture build, 72 failures). Changed to `import uuid`.
  - `fixtures.py` — `setup_gallery()` passed `name=_uniq(...)` plus `**overrides`, so any caller passing `name=` raised `TypeError: got multiple values for keyword argument 'name'` (53 failures). Changed to `overrides.setdefault("name", ...)`.
  - `api_client.py` — `remove_order_line()` used the framework's `_request`, which sends DELETE payloads as **query params**, while the PRD-faithful implementation reads `expected_order_version` from the JSON body (PRD §2.8: "the request must carry `expected_order_version`"). This silently dropped the OCC field, producing `ERR_STALE_VERSION: expected_order_version is required` on every confirmed-order line removal (and one masked pricing failure where the intended removal was rejected, leaving two lines on the order). Now sends the payload as a JSON body on DELETE.
  - `fixtures.py` — added `extend_quote_via_consultation(order_id, member_id=None, days=14*N)`: books and completes N consultations on a QUOTE order, each extending `quote_expires_at` by 14 days per PRD §3.6.

- **Fixes applied to `test_suite/`:**
  - `test_01_membership.py`, `test_03_orders.py`, `test_05_delivery.py`, `test_07_validation_and_access.py` — timestamp equality assertions expected `...T00:00:00Z`, but PRD §1 (lines 57/99/100) requires every server timestamp to carry three fractional digits (`...T00:00:00.000Z`), which the implementation emits. Updated the 7 assertion literals to `.000Z`.
  - `test_03_orders.py` — `test_confirm_gated_by_member_standing_grace_passes`, `test_confirm_rejected_when_member_lapsed`, `test_confirm_state_error_beats_fiscal_error`: setups moved the clock to 2027-09-02 / 2027-10-02 to force GRACE/LAPSED, but the quotes expired at 2026-09-15, so the tier-6 temporal check (`ERR_QUOTE_EXPIRED`, PRD §2.10) legitimately pre-empted the tier-4 standing check under test. Extended each quote past the target date via completed consultations (28×14d / 29×14d / 32×14d) so the intended rule fires.
  - `test_02_pricing.py` — `test_quote_total_frozen_while_settlement_repriced_on_promo_release`: same masking — the promo release needed clock 2026-09-22 but the quote expired 2026-09-15; extended by 2 completions (+28d).

- **Fixes applied to `implementation/`:**
  - `app.py` `add_order_line()` — the `quote_total_cents` snapshot fired whenever a line was added to an empty QUOTE order, so after a full remove + re-add it was rewritten, violating PRD §2.7's "The very first time a line is added to a quote, the resulting total is also captured into `quote_total_cents`, which thereafter **never changes**". Guarded the write with `o["quote_total_cents"] == 0` so it captures exactly once per order.

[Orchestrator verification: app.py mtime 20:25:22 predates all results.*.json mtimes 20:29:28, so the final 8-round sweep covers the implementation fix. All 8 results files confirm passed=81/81, failed=0.]

## Step 8: Finalize PRD — 2026-09-30T20:40:00.000Z

Done. PRD_FINALIZED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_3309_membership_based_furniture_retail_design_services_trade/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md 344 lines; PRD_FINALIZED.md 344 lines; 0% line-count delta (one in-place sentence extension, no lines added or removed).

**Changes (1 edit):**

- **§2.7 (Pricing recalculation)** — revise — Extended the `quote_total_cents` capture sentence with "; this capture happens exactly once per order, so if every line is later removed and a new line is then added, the existing snapshot is kept and not re-captured." This pins the semantics that Step 7's `app.py` fix (`quote_total_cents == 0` guard at `implementation/app.py:716-717`) brought the implementation into conformance with, and closes the "first add to an *empty* quote" misreading that caused the original bug.

**Per-edit pre-edit search log:**

- Edit 1:
  - (a) Subject: when `quote_total_cents` is captured and whether it can ever be re-captured.
  - (b) Impl paths enumerated and read/grepped: `implementation/app.py:599` (order creation initializes to 0); `implementation/app.py:716-717` (sole write site, guarded by `not had_lines and status == "QUOTE" and quote_total_cents == 0`); `implementation/app.py:723-760` (`remove_order_line` — recomputes pricing, never touches snapshot); `implementation/app.py:839` (confirm re-pricing — leaves snapshot frozen); `implementation/services.py:34` (`recompute_order_pricing` — never writes snapshot); `implementation/services.py:176` (Cascade A lapse re-price — snapshot unchanged, matches PRD line 174); `implementation/services.py:217` (Cascade B release re-price — snapshot unchanged, matches PRD line 194). Also confirmed via grep that only `app.py` lines 143/599/716/717 reference `quote_total_cents` at all.
  - (c) Wording adjustment: scoped the new clause to the capture event only ("exactly once per order ... not re-captured"), avoiding any claim about the snapshot's *value* relative to current lines, so it stays consistent with Cascade A/B re-pricing and confirm-time settlement, which intentionally let `total_cents` diverge from the frozen snapshot.

**Diff items requiring no PRD change, and why:**

- `fixtures.py` `import uuid` fix — pure test-fixture NameError bug; no behavioral surface in the PRD.
- `fixtures.py` `setup_gallery()` name/`**overrides` collision — pure fixture TypeError bug; no PRD implication.
- `api_client.py` `remove_order_line()` DELETE body — client was wrong; PRD §2.8 already requires `expected_order_version` in the JSON body and implementation reads it there. PRD already correct.
- `fixtures.py` new `extend_quote_via_consultation()` helper — exercises the existing, fully-specified PRD §3.6 rule. No PRD silence.
- 4 test files' timestamp literals — PRD §1 already pins three fractional digits; implementation conforms. Tests were wrong, not the PRD.
- `test_03_orders.py` confirm tests + `test_02_pricing.py` promo-release test — confirmed PRD §2.10 validation-priority ordering as implemented; PRD already enumerates the exact order. No edit needed.

[Orchestrator verification: diff PRD.md PRD_FINALIZED.md shows exactly the single reported §2.7 sentence extension.]

## Step 9: Complete PRD — 2026-09-30T20:55:00.000Z

The diff is exactly the 25 intended in-paragraph changes (24 revisions + 1 added bullet). All behaviors verified against `implementation/app.py`, `core.py`, and `services.py`.

## Summary

**File stats**: `PRD_FINALIZED.md` 344 lines / 49,773 chars → `PRD_COMPLETED.md` 345 lines / 53,616 chars (char-delta +3,843).

**Counts**: ambiguity-pins: 23; mismatch-revisions: 2. [Reconciled in report tail: ambiguity-pins 26, mismatch-revisions 2 (items 15 and 26 are the mismatch-revisions; item 12 is a revise-in-place ambiguity pin counted among the 26).]

**Changes** (all inserts inline in existing paragraphs; one new bullet in §2.2):

1. §2.1 — insert — ambiguity — Member ownership rule now also covers delivery appointments (member reads an appointment only via its order's `member_id`) — app.py:1144-1147
2. §2.2 — revise — ambiguity — `api_request_timestamp` pinned to real wall clock while all business timestamps use the logical clock — core.py:155-157 vs core.py:244-255
3. §2.2 — insert — ambiguity — new bullet: unmatched routes/405 → 404 `ERR_NOT_FOUND`; unhandled exceptions → 400 `ERR_INVALID_REQUEST` — app.py:33-47
4. §2.3 — insert — ambiguity — invalid `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400); `has_more` pinned as `offset + returned_count < total_count` — core.py:190-204, 169-175
5. §2.3 — insert — ambiguity — list sort ties broken by `id` ascending — app.py:458, 514, 649, 1048, 1166, 1290
6. §2.10 tier 4 — revise — ambiguity — `ERR_STALE_VERSION` assigned to the state-precondition tier (before referential rules); within-tier checks fire in each endpoint narrative's order — app.py:683-687, 736-740
7. §2.10 tier 6 — insert — ambiguity — `ERR_QUOTE_EXPIRED` on line mutations fires only after stale-version/product/kind/non-cancelable failures are ruled out — app.py:689-696, 741-745
8. §3.1 — insert — ambiguity — enrollment initializes `lifetime_net_savings_cents` to −17500 — app.py:293
9. §3.1 — insert — ambiguity — auto-renew renews exactly one elapsed period per ops run even after multi-period overshoot — services.py:228-236
10. §3.1 — insert — ambiguity — `grace_end` cleared to null on lapse and cancellation, not only renewal — services.py:247, app.py:359
11. §3.1 — insert — ambiguity — cancellation permitted only from `ACTIVE`/`GRACE`; other states → `ERR_INVALID_STATE` — app.py:345-346
12. §3.2 — revise — ambiguity — verify reordered: enum check before state check; re-verifying a decided account → `ERR_INVALID_STATE`; missing tier on `APPROVE` → `ERR_INVALID_REQUEST` — app.py:400-406
13. §3.3 — insert — ambiguity — multiple eligible books releasing in one daily cycle archive each other in turn; flags of the last-released edition stand — services.py:251-255, 190-193
14. §3.4 — insert — ambiguity — unknown `gallery_id` on order creation → `ERR_GALLERY_NOT_FOUND`; unknown `member_id` → `ERR_MEMBER_NOT_FOUND` — app.py:558-560, 569-571
15. §3.4 — insert — mismatch — GalleryAssociate may create orders with `member_id` or unverified `trade_account_id` (verified gate applies only to TradeDesigner callers) — app.py:580-588
16. §3.4 — insert — ambiguity — line add gated to QUOTE/CONFIRMED with `ERR_INVALID_STATE`; QUOTE adds after expiry → `ERR_QUOTE_EXPIRED` — app.py:669-670, 695-696
17. §3.4 pricing step 3 — insert — ambiguity — trade discount defaults to 30% when the account record is missing or untiered — services.py:57-58
18. §3.4 amendment — insert — ambiguity — adding a line to CONFIRMED collects no fresh deposit; `deposit_paid_cents` unchanged; line removal deletes the record and returns the order — app.py:715-718, 757-760
19. §3.4 cancellation — insert — ambiguity — cancelling an expired QUOTE is still permitted — app.py:868-869 (no expiry check in cancel)
20. §3.5 — insert — ambiguity — cross-gallery slot commit → `ERR_INVALID_REQUEST` (400); schedule-production returns the slot object — app.py:798-800, 811
21. §3.5 bubble-up — revise — ambiguity — order flips to `READY_FOR_DELIVERY` only when at least one custom line exists and all are `COMPLETE` — services.py via app.py:966-968
22. §3.6 — insert — ambiguity — malformed `scheduled_at` → `ERR_INVALID_REQUEST`; GalleryAssociate may attach a consultation to any order regardless of the named member — app.py:995-999, 1005-1008
23. §3.6 — insert — ambiguity — completing a non-`SCHEDULED` consultation → `ERR_INVALID_STATE` — app.py:1061-1062
24. §3.7 — insert — ambiguity — dispatching hub gallery need not equal the order's selling gallery; capacity/booked minutes tracked on the dispatching hub — app.py:1092-1112
25. §3.7 — insert — ambiguity — omitted `packaging_removed` on COMPLETED defaults to false — app.py:1185
26. §3.7 — revise — mismatch — delivery trigger pinned to order state `READY_FOR_DELIVERY` (impl checks state, not "first COMPLETED appointment") — app.py:1193-1194
27. §3.8 — insert — ambiguity — `order_line_ids` must be non-empty; unresolvable line id → `ERR_LINE_NOT_FOUND`; member ownership enforced on create — app.py:1234, 1237-1238, 1244-1247
28. §3.8 — insert — ambiguity — settling a non-`REQUESTED` return → `ERR_INVALID_STATE` — app.py:1306-1307

[Orchestrator verification: PRD_COMPLETED.md on disk — 345 lines / 53,616 chars vs PRD_FINALIZED.md 344 / 49,773; diff spans 51 changed lines, consistent with the reported 25 in-paragraph edits + 1 added bullet.]
