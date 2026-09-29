# Worklog — task_2813_grocery_delivery_shopper_network_batch_dispatch

## Step 1: Create task directory — 2026-09-05T01:03:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2813_grocery_delivery_shopper_network_batch_dispatch/` and its `workspace/` subdirectory. Index 2813 was pre-assigned by the invocation; no scan of `./tasks/` was performed.

## Step 2: Generate scaffold — 2026-09-05T02:42:00.000Z

All three scaffold artifacts are complete and the linter is clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2813_grocery_delivery_shopper_network_batch_dispatch/`

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2869 | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1810 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4948 | single key `scaffold_corner_design` |

**SCAFFOLD.yaml counts**: 12 entities, 6 state machines (parallel shape: Order carries independent fulfillment/payment dimensions), 2 `concurrency_rules`, 17 calculations, 55 validation rules, 53 endpoints, 52 error codes, 5 roles (Customer, Shopper, RetailerManager, DispatchAdmin, CustomerSupport; `role_model: peer_roles`), `api_prefix: ""`, `difficulty_level: expert_plus`.

**§1.8**: 9 rule_ids × 2 instances = 18 instances.

**§1.9**: 86 instances across all nine guide sections — entities 12, state_machines 17, calculations 20, validations 16, endpoints 5, errors 6, rbac 3, complexity_layers 6, consistency_model 1. 65 are active `test_recipe` instances, 21 are `excluded_because` stubs (each with `grounds` and a citation that resolves to a real §1.8 instance name; no stub carries a `test_recipe`). All 52 `ERR_*` codes are triggered by at least one instance; instance names are unique across the union of both design files.

**Lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2813_grocery_delivery_shopper_network_batch_dispatch/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2813_grocery_delivery_shopper_network_batch_dispatch/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2813_grocery_delivery_shopper_network_batch_dispatch/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1169

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design adjudications**
- Expert+ band deliberately exceeds the §0.4 caps (the scenario asks for "harder than expert level"; the extra endpoints are mostly the mandatory reverse-reachability GETs).
- `ERR_ORDER_ALREADY_BATCHED` was unreachable behind the priority-8 `fulfillment_status == PLACED` gate; it was relocated to priority 7 with an explicit ordering rationale and the §1.2 `PLACED -> IN_BATCH` preconditions were reordered to match.
- `DispatchAdmin` is a peer, not a hierarchical override — the rbac section pins that it is refused `POST /order-lines/{id}/pick` with `ERR_UNAUTHORIZED_ROLE` before the state gate.
- `selector_policy` is a declared complexity layer with no row in the claim-extraction guide, so no `claim_type` was invented for it; its behavior is covered by the dispatch-ranking calculation instances instead. `bulk_action` was omitted from the endpoints section because the API declares no bulk endpoints.
- Both OCC rules got active instances (`ERR_STALE_BATCH_VERSION` on `POST /batches/{id}/orders`, `ERR_STALE_ORDER_VERSION` on `POST /orders/{id}/tip-adjustments`); `cascading_side_effects`, `dual_variant_calculation` and `derived_field_reconciliation` are stubs pointing at the §1.8 chains that already pin them.
- Scenario text in `SCAFFOLD.yaml` is the domain description only — the "harder than expert level" directive does not appear in any of the three files.
- Three test-driving endpoints exist by §1.5's last-resort rule: `POST /_clock/set_current_utc`, `POST /_ratings/backfill`, `POST /_shoppers/{id}/history`.

Two lint findings were fixed en route: `POST /orders/{id}/tip-adjustments` takes `tip_amount_cents` (not `new_tip_amount_cents`), and `POST /replacement-requests` requires `batch_id`. The system-field entity instance was renamed to `customer_system_and_computed_fields_are_input_ignored` so its intentionally illegal payload is recognised as a negative trigger.

Orchestrator verification: all three files present; `grep -ri "harder than expert"` over the task dir returns nothing (no difficulty-directive leak).

## Step 3: Copy shared files — 2026-09-05T02:43:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T03:02:00.000Z

PRD generation is complete and verified.

**Artifact:** `workspace/PRD.md` — **489 lines**, built with 14 incremental appends (no single write anywhere near the 64k cap). The file ends at a real boundary: the last row of the §5 error table (`ERR_ORDER_PAYMENT_HELD | 409`). Scratch files were confined to `/tmp/task_2813_prd/`. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, and all sibling task directories were never opened.

**Section headings (5 H2, 19 H3):**
- 1. Introduction
- 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control / 2.2 API Response Structure (verbatim, incl. its two H4 blocks) / 2.3 Pagination / 2.4 Resource Identity, Timestamps and Versioning / 2.5 The Logical Clock and Lazy Expiry / 2.6 Money, Weight and Rounding Discipline / 2.7 Optimistic Concurrency on Orders and Batches / 2.8 Rejection Precedence / 2.9 Identifier Resolution and Reverse Lookup / 2.10 Derived Fields, Cascades and Conservation
- 3. Business Logic & Workflows — 3.1 Retailer Catalogs, Shelf Prices and Customer Accounts / 3.2 Composing an Order / 3.3 The Shopper Network: Enrollment, Ratings and Tier Access / 3.4 Batch Construction and Store-Level Concurrency / 3.5 Dispatch, Offers and the Claim Gate / 3.6 In-Aisle Execution: Picks, Weights and Substitutions / 3.7 Checkout: Final Pricing, Split Tender and Parity / 3.8 Delivery, Tip Windows and Shopper Pay / 3.9 Abandonment, Suspension and Reassignment
- 4. Endpoint Definitions (4-column table, 53 rows)
- 5. Error Code Catalogue (2-column table, 52 rows)

**Coverage audit (all mechanically checked against the scaffold, not by eye):**
- Entities 12/12; all 108 scaffold-declared field names plus all 7 computed parity-read output keys present in backticks.
- Endpoints 53/53 present in the §4 table with exact paths, descriptions and role lists; 201/200 split matches every scaffold `code` value (11 creation endpoints at 201, including `POST /batches/{id}/orders`; the three underscore test-driving endpoints at 200).
- Errors 52/52 in §5 with correct HTTP statuses, and 52/52 also attached to a triggering condition somewhere in §1–§3 (none appears only in the table).
- Calculations 17/17 documented in prose; every numeric constant in every calculation is present either as the digit string or as its spelled-out equivalent (0.6 -> "0.60 ... sixty percent", 0.2 -> "twenty percent", 0.7/0.3 -> "0.70 times / 0.30 times", 0.92 -> 0.9200, 0.1 -> "ten percent"/0.10, 0.05 -> "five percent", 0.50 -> "at least half" via integer cross-multiplication).
- Validations 55/55: all `applies_to` scopes, the full 14-rank precedence ladder, and the ERR_INVALID_REQUEST field-level constraints (PER_LB weight > 0 with qty 1, EACH weight 0, `shop_window_end` strictly after start, stars 1-5, tip 0-20000, limit 1-100).
- State machines: all 35 transitions covered; all entity enum values appear; both OCC rules and both conservation invariants documented; 35 field defaults/initial values stated (added "starts as an empty list" for `declined_shopper_ids` during the audit).

**Hard Contracts: all three PASS.**
- Contract 1 (field-name coverage): two independent extractions — 114 tokens from a pre-built required set and 108 re-extracted fresh from the scaffold — both 0 missing.
- Contract 2 (rule coverage): all eight categories walked; see coverage audit above.
- Contract 3 (§3 path purity): 201 distinct backticked tokens in §3, 0 violations — no `/`-leading token, no bare HTTP method, no method+path pair; a grep for un-backticked paths and bare methods in §3 is also empty. No fuzzy quantifier words ("approximately", "roughly", "conservatively") anywhere in the document.

**Adjudications made** (scaffold conflicts or silences, resolved and documented in the PRD):
1. `BatchOrder.units` — endpoint prose said "from the order's line count", the calculation said sum of `requested_qty` over EACH lines plus 1 per PER_LB line; the calculation wins.
2. `retailer.status == ACTIVE` at order submit has no error code in the catalogue — requirement stated without nominating a code (no invention).
3. "no member line still `REQUESTED`" at checkout has no error code — likewise stated without a code.
4. Rank-7 intra-band order: OCC stale-version check precedes the one-batch-membership rule.
5. Rank-8 intra-band order: order status, then batch status, then line/replacement/payout status.
6. Claim gate order: batch `OFFERED` -> ownership vs `offered_shopper_id` -> offer expiry -> window conflict -> suspension -> tier floor -> capacity; generalised as the rule that a state gate on a state-dependent ownership field is evaluated before the ownership comparison.
7. Replacement rejection also adds the line's snapshot-priced amount to `Order.refunded_cents` (from endpoint side effects; the state machine is silent).
8. Pick with omitted `picked_qty`/`final_weight_lb` falls back to `requested_qty`/`requested_weight_lb`, per the pricing formula's own fallback.
9. `DIAMOND` band with `completed_batch_count < 3` falls through to the next satisfied band (stated explicitly for sibling-branch symmetry).
10. `POST /_ratings/backfill` returns 200 despite creating rating rows — matches the scaffold's declared code and is stated in the §4 preamble.

Orchestrator verification (truncation guard): `wc -l` = 489; `tail -25` ends cleanly on the final error-table row `| ERR_ORDER_PAYMENT_HELD | 409 |`; all 5 H2 and 19 H3 headings present. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T04:15:00.000Z

Orchestrator note: the Step 5 subagent was terminated mid-run by a transient API error after finishing queue A and 43 of 65 queue-B instances (last on-disk file `test_23_validations.py` at 451 lines). Rather than respawning a fresh generator — which would have made the second half of the suite diverge from the first, since a new agent rebuilds its own helper conventions — the orchestrator computed the exact residual to-do list (22 active §1.9 instances, enumerated by section, by diffing `Design:` tags on disk against non-stub instance names in both design yamls) and SendMessage'd it back to the SAME agent, with its context intact. The resumed run completed the remaining 22. Both halves therefore share one set of test_helpers conventions. Summary below is the agent's own, covering the whole Step 5 run.

Step 5 is complete. All queue A and queue B instances are translated, everything compiles, pytest collects 101 tests, and pyflakes is clean across `test_helpers/` and `test_suite/`.

## Instance counts

**Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8):** 18 instances, all 18 translated, **36 tests** (4 per rule x 9 rules, i.e. 2 tests per instance minimum met everywhere).

**Queue B — `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9):** 65 non-stub instances, all 65 translated, **65 tests** — entities 12, state_machines 13, calculations 12, validations 12, endpoints 3, errors 6, rbac 3, complexity_layers 3, consistency_model 1. The 21 `excluded_because:` stubs were not translated; all 21 `difficulty_instance` cross-references were verified to resolve to real §1.8 instance names.

**Total: 101 tests, 101 `Design:` tags, 0 untagged, 0 dual-tagged, 0 tags pointing at a non-existent or stub instance** (verified by script against both yamls). Every docstring cites PRD verbatim and ends with its single tag line.

## Instances skipped
None. No instance failed the PRD-first two-condition filter, so no gaps were left and no placeholder/xfail was emitted.

## Files (line counts)

- `test_helpers/`: `__init__.py` 47, `api_client.py` 358, `api_errors.py` 139, `assertions.py` 249, `constants.py` 196, `factories.py` 304, `fixtures.py` 359, `test_users.py` 86, `types.py` 198
- `test_suite/`: `conftest.py` 35, `test_10` 231, `test_11` 225, `test_12` 298, `test_13` 342, `test_14` 240, `test_15` 193, `test_16` 292, `test_17` 319, `test_18` 347, `test_20_entities` 496, `test_21_state_machines` 966, `test_22_calculations` 1004, `test_23_validations` 856, `test_24_endpoints` 261, `test_25_errors` 549, `test_26_rbac` 382, `test_27_complexity_layers` 358, `test_28_consistency_model` 143

Nothing was written under `workspace/`, no `worklog.md` touch, scratch confined to `/tmp/task_2813_tests/`.

## Design adjudications (5)
1. `SCAFFOLD_DIFFICULTY_DESIGN.yaml:1808` asserts `tip_paid_cents == 0` on a FORFEITED payout; the PRD/SCAFFOLD field is `tip_pass_through_cents`. Asserted the PRD field.
2. `Corner/validations/finalizing_before_the_window_closes_is_rejected_then_allowed` asserts `ShopperPayout.tip_baseline_cents == 1000`; no such field exists (PRD §3.8 treats the baseline as an intermediate). Assertion dropped, the other three money fields kept.
3. `Corner/validations/an_expired_pending_replacement_cannot_be_approved_but_can_be_rejected` asserts `resolved_at`; that field appears nowhere in PRD.md or SCAFFOLD.yaml. Dropped.
4. `Corner/validations/offer_expiry_is_strict_and_a_reoffer_reopens_the_claim` asserts `Batch.claimed_at`; Batch has no such field. Dropped (status / `claimed_shopper_id` / `committed_units` kept).
5. `Corner/rbac/every_role_exercises_its_own_exclusive_writes` and `Corner/consistency_model/every_write_response_already_carries_its_derived_effects` both assert `payment_status == ESTIMATE_AUTHORIZED`, which is not a member of the PRD's enum (`UNAUTHORIZED`, `AUTHORIZED`, `REAUTH_HELD`, `CAPTURED`, `REFUNDED`). Asserted `AUTHORIZED`.

## Incidental cleanups
The three pre-existing pyflakes warnings are gone: unused `factories as f` import in `test_10`, unused `read_replacement` import in `test_12`, and the unused local `sc` in `test_18`.

Orchestrator verification: `test_helpers/` and `test_suite/` both at the task root (no stray copies under `workspace/`); every .py compiles; `pytest --collect-only` reports 101 tests collected.

## Step 6: Generate implementation — 2026-09-05T04:15:00.000Z

**Implementation:** `workspace/implementation/`

| Module | Lines | Role |
|---|---|---|
| `app.py` | 49 | Flask factory, blueprint registration, `ApiError`/404/405/500 handlers, `PORT` bind |
| `store.py` | 142 | In-memory dicts, logical clock, id/timestamp helpers, per-request `touch()` |
| `errors.py` | 84 | All 52 error ids -> HTTP status + default messages |
| `response.py` | 41 | `meta`/`response_type`/`data` envelope, pagination meta |
| `auth.py` | 35 | `X-User-ID`/`X-User-Role`, role gate, ownership (opaque roles short-circuit) |
| `validation.py` | 177 | Typed body/query extraction, Decimal coercion, pagination bounds |
| `calc.py` | 238 | All constants + 17 pure calculations (ROUND_HALF_UP Decimal only) |
| `derive.py` | 584 | Store-aware re-derivations, dispatch selector, parity, payouts, cascades |
| `serializers.py` | 246 | 12 entity serializers |
| `lookup.py` | 69 | FK resolution -> correct 404 id; shared paged-list helper |
| `db_helpers.py` | 8 | Conditional version bump |
| `routes/catalog.py` | 213 | Retailers + catalog items (7 endpoints) |
| `routes/customers.py` | 91 | Customers + credit ledger (5) |
| `routes/shoppers.py` | 165 | Shoppers, ratings, reinstate, 2 test-driving endpoints (8) |
| `routes/orders.py` | 282 | Orders, lines, submit, tip, reauthorize, parity read (10) |
| `routes/batches.py` | 244 | Batches, membership, dispatch/claim/start/reassign (10) |
| `routes/aisle.py` | 203 | Pick + replacement requests (5) |
| `routes/fulfillment.py` | 192 | Checkout, deliver, abandon, payouts, clock (7) |
| `start.sh` | 10 | Guarded pip install, `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |

**53 endpoints — exactly matching the PRD §4 table**, verified route-by-route. Every `.py` compiles; store boots empty (no seeding, no disk I/O anywhere).

**Verification:** three smoke passes, ~110 assertions, all green after correcting the agent's own test's wrong guesses (every discrepancy traced back to the PRD and the implementation was right each time): full happy path with exact money (estimate 1920 -> ceiling 3107 -> EBT/card split 720/2387; capture 2040; parity credit 170; payout 775+270+500=1545; finalize with tip-bait protection 400), replacement approve/reject with `price_delta_cents` -840 and `LINE_REPLACED`/`LINE_REFUNDED`, checkout sweep, post-checkout abandon reversal, offer lapse -> re-offer with decline-list exclusion, OCC 412 on both guarded endpoints, and the full 4-link abandonment cascade -> `SUSPENDED_REVIEW` -> sibling system-release (3 batches held, 2 abandoned, 3rd released without a third `abandonment_count` increment) -> reinstate.

**Adjudications where the PRD was ambiguous** (reading chosen):
- **Version bumps:** at most one per row per HTTP request (request-scoped set); `touch_if` where the PRD frames the write as conditional on an input actually changing (catalog re-pricing on parity-policy PATCH, snapshot re-take at submit, line re-pricing at checkout).
- **`created_at`/`updated_at` come from the logical clock**; only `api_request_timestamp` uses wall time. List order is `(created_at, insertion_seq)` so equal logical instants stay stable.
- **Ownership enforced on mutating endpoints only**, not GETs.
- **Checkout's "no member line still REQUESTED" gate** -> `ERR_LINE_NOT_PICKABLE` (409); the PRD names no id.
- **Retailer `PAUSED` at submit**, and **`store_code`/per-retailer `sku` uniqueness** -> `ERR_INVALID_REQUEST` (400); no dedicated ids exist.
- **Timestamp comparisons are exact datetime comparisons**, not minute-truncated.
- **Rank-4 hoisting** (PRD §2.8 refinement) applied to claim, start-shopping, pick, replacement-create, checkout, deliver, abandon; on approve/reject, ownership precedes the PENDING gate and the expiry check.
- **Omitted `requested_weight_lb` on a PER_LB line falls back to the item's `estimated_weight_lb`** (per §3.1's description of that field); an explicit or fallen-back 0 is a 400.
- **CHECKED_OUT abandon** zeroes only `final_price_cents` on returned lines (literal reading), unlike the SHOPPING case which zeroes all three fields.
- **System release** does *not* increment `abandonment_count`, reset lines, or reverse captures.
- **Failed dispatch leaves the batch byte-identical** (the lapsed offeree is added to a temporary declined set and only persisted on success).
- **List filter enums are not validated** (unknown value matches nothing); boolean query filters accept `true/1/false/0`, else 400.
- **`finalize-payout`** requires a PROVISIONAL row; missing/FINAL/FORFEITED -> `ERR_PAYOUT_NOT_PROVISIONAL`, and a null `tip_window_closes_at` counts as still open.

The agent did not read `test_suite/`, `test_helpers/`, either design file, or any sibling task; it did not touch `worklog.md`. Smoke servers were killed by recorded PID; scratch confined to `/tmp/task_2813_impl/`.

## Step 7: Run tests and iterate — 2026-09-05T05:00:00.000Z

All 8 parallel rounds green: **101/101 passing in every round.**

## Summary

**Iterations run:** 2 (iteration 1 sweep -> 5 deterministic failures in all 8 rounds; iteration 2 sweep -> clean).

Iteration 1 failed the identical 5 tests in all 8 rounds — no flakiness, no load-induced noise. (Note: `setsid` detaches and returns immediately on this host, so the sweep must be polled via `results.*.json` rather than trusted to block.)

**Tests deleted:** none.

**Assertions removed (STEP 1b / 1c — unique-derivability collapse):**
- `test_suite/test_26_rbac.py::test_peers_cannot_reach_each_others_rows_but_share_the_catalog_read` — removed the single assertion that `GET /orders/{id}` by a non-owning `Customer` yields `ERR_NOT_RESOURCE_OWNER`. Pattern: **read-surface ownership scope silence**. PRD 2.1 states the ownership comparison generically, but PRD 2.8 explicitly scopes it — "Ranks 1, 2, and 5 apply to every endpoint in the API. The scopes of the remaining ranks are stated alongside the workflows they guard in section 3" — and section 3 names ownership only for mutations. Decisive evidence: the same test asserts `GET /catalog-items/{id}` **succeeds** for a rival `RetailerManager`, even though PRD 2.1 states that ownership mapping in identical language. No uniform reading of PRD 2.1 satisfies both assertions, so the order-read assertion is not uniquely derivable. It was also the only read-ownership assertion in the whole 101-test suite; every other `ERR_NOT_RESOURCE_OWNER` assertion targets a write. The test retains its Shopper-ownership, RetailerManager-ownership, and shared-catalog-read assertions. Design tag: `Corner/rbac/peers_cannot_reach_each_others_resources_but_share_the_catalog`.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `retailer_payload()`: the default `store_code` was the fixed literal `"BFM-01"`, but PRD 3.1 requires `store_code` to be unique across all retailer rows. Any test building its world twice in one server lifetime had its second retailer refused with `ERR_INVALID_REQUEST`, surfacing as `Setup step failed`. Now defaults to a per-process counter (`BFM-%04d`); an explicit `store_code=` still wins.

**Fixes applied to `test_suite/`:**
- `test_suite/test_17_resource_temporal_overlap.py` — `_store_cap_world()` hardcoded `store_code="SGG-07"` and is invoked twice inside `test_the_capped_attachment_writes_nothing_and_an_idle_neighbour_never_counts` (refused case + control case); dropped the override so the factory's unique default applies.
- `test_suite/test_25_errors.py` — `test_each_detail_read_reports_its_own_not_found_code` asserted `is_valid_uuid(meta.api_request_id)`, contradicting PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`" (example `req_RANDOMALPHANUM123456`). Assertion now checks the `req_` prefix, which is what PRD actually pins.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/fulfillment.py` — `checkout()`: the PRD 3.7 sweep moves unanswered replacement lines to `REFUNDED`, but the batch's composition was never re-derived afterwards, so `total_weight_lb` kept counting a refunded line (observed 1.0 where 0.0 was correct). PRD 3.4 defines `total_weight_lb` as a sum "skipping every line whose `status` is `REFUNDED`" and PRD 2.10 requires "Whenever any input to a derived field changes, the field is recomputed from its definition in the same operation." Added a conditional `derive.recompute_batch_aggregates(batch)` immediately after the sweep, gated on the sweep having actually refunded a line so no spurious `version` bump occurs when nothing was swept. This also matters downstream: `heavy_pay_cents` is computed from `total_weight_lb` at delivery.

Orchestrator verification (independent of the subagent's claim): all 8 `workspace/implementation/results.{1..8}.json` exist on disk and each reports `passed=101, total=101`.

## Step 8: Finalize PRD — 2026-09-05T05:06:00.000Z

`PRD_FINALIZED.md` is written: 491 lines vs PRD.md's 489 (+0.41%), tail intact at the last row of the §5 error table (`| ERR_ORDER_PAYMENT_HELD | 409 |`). Two edits, both traced to `<step_7_diff>` items; the other three items needed no PRD change.

## Changes

- **§2.1 (ownership) — insert** — new paragraph after the `ERR_NOT_RESOURCE_OWNER` sentence: the ownership comparison is made only on operations that create or change state; reads (single-resource, filtered list, and the computed parity-disclosure read) never perform it, are answered for any role §4 authorizes, are not narrowed to the caller's own rows, and can never fail with `ERR_NOT_RESOURCE_OWNER`. — `implementation/auth.py:26` + all `require_owner` callsites.
- **§3.7 (checkout sweep) — revise** — the sweep paragraph now states that when the sweep refunds at least one line the batch's composition is re-derived from its membership rows per §3.4 (notably `total_weight_lb`, which skips `REFUNDED` lines) before any pricing; a sweep that refunds nothing leaves the composition alone; the re-derivation runs inside the same checkout operation and does not advance the batch's `version` a second time; the corrected `total_weight_lb` is what delivery reads to size `heavy_pay_cents`. — `implementation/routes/fulfillment.py:54-60`.

## No-change decisions

- `test_helpers/factories.py` `store_code` counter — pure fixture bug. §3.1 already requires `store_code` uniqueness across all retailer rows, and §2.8 rank 5 maps section-3 field-shape violations to `ERR_INVALID_REQUEST`, which is exactly what `routes/catalog.py:51-53` raises.
- `test_suite/test_17` `SGG-07` override — same fixture bug, no PRD surface.
- `test_suite/test_25` `api_request_id` — §2.2 already pins "starts with `req_`"; `store.py:request_id()` emits `req_` + 20 alnum. Test was wrong, PRD was right.

## Per-edit pre-edit search log

**Edit 1 — subject: scope of the ownership (rank-4) comparison.**
(b) Enumerated/read: `auth.py` (`require_owner`, `OPAQUE_ROLES`), every `require_owner` callsite (`routes/orders.py:42,107,181,218,246`; `routes/aisle.py:32,71,139,185`; `routes/batches.py:186,215`; `routes/catalog.py:81,131,185`; `routes/shoppers.py:68`; `routes/fulfillment.py:31,115,139`), and every `@bp.get` handler in all six route modules (`orders.py:74,81,151,158,258`; `catalog.py:70,155,162`; `customers.py:47,68,75`; `shoppers.py:53,88,95`; `batches.py:57,64,130,138`; `aisle.py:104,111`; `fulfillment.py:169,176`) plus `lookup.paged` for hidden per-principal filtering. Result: every entity-backed-role write has an ownership check; zero reads do, including the `parity-disclosure` computed read; lists apply only explicit query filters.
(c) Adjustments: wrote "operations that create or change state" rather than naming path fields, so `POST /orders` (compares the *body's* `customer_id`, `orders.py:42`) and `POST /catalog-items` (compares the body's `retailer_id`, `catalog.py:131`) are not mis-described; added "and without narrowing a list to the acting principal's own rows" to cover `lookup.paged`; said "no read" rather than "no `GET`" so the sentence stays true independent of method spelling.

**Edit 2 — subject: re-derivation of batch composition (`total_weight_lb`) triggered by a member-line status change at checkout, and its version effect.**
(b) Enumerated/read: `derive.recompute_batch_aggregates` (unconditional `touch(batch)`) and all its callsites — `routes/batches.py:126` (attach), `routes/aisle.py:51` (pick), `:175` (approve), `:202` (reject), `routes/orders.py:254` (reauthorize), `routes/fulfillment.py:60` (checkout sweep); `derive.batch_line_weight` / `PRICED_LINE_STATUSES`; `store.touch` (per-request `g.touched_rows` dedup — a row's version rises at most once per request); the other `touch(batch)` sites (`fulfillment.py:99` checkout status, `:118` deliver, `batches.py:150,203,219`, `derive.py:483` release); `derive.payout_money`/`calc.work_pay` for the downstream `heavy_pay_cents` dependency; and `derive.abandon_batch` (which does *not* re-derive aggregates).
(c) Adjustments: scoped the sentence to the checkout sweep and phrased it as "as section 3.4 prescribes" so it neither implies checkout is the only re-derivation site nor denies the reject/approve/pick/reauthorize sites; added the explicit "does not advance the batch's `version` a second time" clause because §2.10's generic "recomputation ... increases its version" would otherwise lead a fresh implementer to two batch version bumps per checkout where `store.touch` produces exactly one (this is the only row in the whole implementation mutated twice in one request); added "a sweep that refunds nothing leaves the composition as it stands" to match the `if swept_a_line:` gate.

## Step 9: Complete PRD — 2026-09-05T05:45:00.000Z

Orchestrator note: Step 9 was run as **three sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, because a single-agent whole-repo scan of a 53-endpoint implementation reliably degenerates into a no-op `cp`. Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place. Each later pass read `PRD_COMPLETED.md` (not `PRD_FINALIZED.md`) as its working text and spot-checked earlier passes' pins for survival.

Partition:
- **Pass 1 — infrastructure**: `app.py`, `store.py`, `errors.py`, `response.py`, `auth.py`, `validation.py`, `lookup.py`, `db_helpers.py`, `serializers.py`
- **Pass 2 — calculation/derivation layer**: `calc.py`, `derive.py`
- **Pass 3 — route layer**: all seven `routes/*.py` (53 endpoints)

### Pass 1 — infrastructure (14 ambiguity-pins, 3 mismatch-revisions)

491 lines / 97,593 chars -> 493 lines / 103,196 chars (+2 lines, +5,603 chars).

- §2.1 — insert — ambiguity — an empty header value counts as absent; role name matched case-sensitively — `auth.py:13`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `store.py:61`
- §2.2 — revise — mismatch — `api_request_timestamp` is the one value read from the host's real clock, feeds nothing — `store.py:74`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and negative `offset` are `ERR_INVALID_REQUEST`; empty value = omitted — `validation.py:138`
- §2.3 — insert — ambiguity — `created_at` ties break by creation sequence; `has_more` = `offset + len(page) < total_count` — `store.py:136`, `response.py:29`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read from the logical clock; every payload instant uses the same 3-digit format; client instants normalized to UTC, naive read as UTC — `store.py:66,104`
- §2.4 — revise — mismatch — `version` advances at most 1 per row **per request**, however many writes/cascade links touch it — `store.py:113`
- §2.4 — insert — ambiguity — every declared field is always present, empty values are JSON `null` not omitted; relationships are id-only, never nested — `serializers.py:15`
- §2.5 — revise — mismatch — "nothing reads wall-clock time" scoped to domain logic, carving out the envelope timestamp — `store.py:74`
- §2.5 — insert — ambiguity — clock setter stores the instant as given and may wind the clock backwards — `store.py:57`
- §2.6 — insert — ambiguity — all quantities travel as JSON numbers, never quoted strings — `serializers.py:7`
- §2.8 rank 5 — insert — ambiguity — absent/empty body = empty object; non-object/unparseable body = 400; JSON `null` = omitted; booleans rejected for integers; strings must be non-empty — `validation.py:22,36,59`
- §2.9 — insert — ambiguity — empty filter value = omitted; filters matched literally without enum validation (unknown value => empty page, not a rejection); `is_ebt_eligible` accepts `true/false/1/0` any case — `validation.py:161`
- §2.10 — insert — ambiguity — a no-op recompute is not a mutation (no `updated_at`, no `version`) — `db_helpers.py:5`
- §3.4 — insert — ambiguity — `declined_shopper_ids` serialized as an array of bare id strings in append order, oldest first — `serializers.py:170`
- §3.7 — insert — ambiguity — the effective markup fraction is not stored on the order and absent from its payload; only `parity_markup_cents`/`parity_disclosed` are — `serializers.py:108`
- §5 — insert — mismatch/ambiguity — unrouted path => `ERR_INVALID_REQUEST` 404, wrong method => 405, unexpected fault => 500, all in the standard envelope and outside the table's status mapping — `app.py:29`

Pass 1 also machine-checked all 103 emitted field names across the 12 serializers against the PRD text: every one already appears in prose and no PRD-named field of those families is missing from its serializer. Residual silence was in presence/typing discipline, now pinned globally in §2.4/§2.6 rather than per entity.

### Pass 2 — calc.py + derive.py (14 ambiguity-pins, 5 mismatch-revisions)

493 lines / 102,966 chars -> 493 lines / 108,982 chars (+6,016 chars, 0 new lines). PASS 1 pins verified intact.

- §2.6 — insert — ambiguity — markup fraction rounded **half up** to 2 dp on the way in; the quantized value is what every price derivation reads — `calc.py:68`
- §3.1 — insert — ambiguity — an item revision re-derives no batch; `unit_weight_lb` read live at the *next* composition re-derivation — `derive.py:210`
- §3.2 — revise — mismatch — reauthorize re-derives the batch's **whole** composition, not just the blocked counter — `derive.py:227`
- §3.3 — revise — mismatch — supplied `completed_batch_count`/`abandonment_count` becomes the **whole stored counter** (injected component = supplied - events already recorded); an omitted counter is untouched — `derive.py:267`
- §3.4 — insert — ambiguity — weight contributions accumulate at full precision; the **total** is rounded half up to 1 dp exactly once, after summation — `derive.py:248`
- §3.5 — insert — ambiguity — a **fifth** dispatch sort key after `created_at`: server creation sequence, earliest first — `derive.py:378`
- §3.6 — insert — ambiguity — the 20 % tolerance test runs on the weight **as supplied**, before 1 dp rounding — `calc.py:119`
- §3.6 — insert — ambiguity — `price_delta_cents` uses the **raw supplied** weight, before rounding for storage — `routes/aisle.py:21,91`
- §3.6 — insert — ambiguity — on approval the other member of the `picked_qty`/`final_weight_lb` pair is written to 0 — `routes/aisle.py:154-158`
- §3.6 — insert — ambiguity — the re-estimate multiplies the **new** snapshot price by the **originally requested** qty/weight, never by `proposed_*` — `derive.py:125,88`
- §3.6 — revise — mismatch — approval re-derives the batch's **whole** composition, not only `checkout_blocked_count` — `routes/aisle.py:175`
- §3.6 — insert — ambiguity — rejection adds the **estimate-variant** money to `refunded_cents`, not `final_price_cents`; composition re-derived — `derive.py:88`
- §3.7 — insert — ambiguity — parity applied in ascending membership `sequence_no` order, so `PARITY_ADJUSTMENT` ledger entries land in that order — `routes/fulfillment.py:102`
- §3.8 — insert — ambiguity — "the batch's payout row" = earliest-created row with status `PROVISIONAL`/`FINAL` (forfeited skipped), and only while still `PROVISIONAL` — `derive.py:73`
- §3.9 — revise — mismatch — system release differs in **two** respects: member orders move to `REASSIGN_PENDING` from whatever held status, credit sized by the same disruption rule, and **none** of the `SHOPPING`/`CHECKED_OUT` unwinding runs — `derive.py:487-498`
- §3.9 — revise — mismatch — a `CHECKED_OUT` abandonment does **not** always land in the 10 % band; enough `REFUNDED` lines drop it to 5 %, and an all-refunded order earns only the flat 500 — `calc.py:216`
- §3.9 — insert — ambiguity — neither unwinding re-derives batch composition; `total_weight_lb` carries unchanged into reassignment — `derive.py:501`
- §3.9 — insert — ambiguity — `refunded_cents` is **set** (overwriting rejected-replacement accumulation); `card_captured_cents` never zeroed — `derive.py:514-518`
- §3.9 — insert — ambiguity — the `POST_CHECKOUT_REVERSAL` entry is written only when the card slice > 0, entries written reversal-first — `derive.py:521,553-558`

Pass 2 noted `calc.priced_line_cents`, `calc.weight_of`, `calc.qty_of`, `calc.MARKUP_PCT_MAX` and `calc.TIERS` as dead code with no PRD surface.

### Pass 3 — routes/ (17 ambiguity-pins, 5 mismatch-revisions)

493 lines / 109,250 chars -> 493 lines / 116,641 chars (+7,391 chars, 0 new lines). All edits in-paragraph; 27 section headers and 109 table rows byte-identical to `PRD_FINALIZED.md`. PASS 1 and PASS 2 pins verified intact.

- §2.8 rank 4 — insert — ambiguity — rank 4 can only run once the owner's identity is known, so on the four body-named-owner operations ownership follows ranks 5-6 — `routes/catalog.py:131`, `routes/orders.py:42`, `routes/shoppers.py:68`, `routes/aisle.py:71`
- §2.8 rank 6 — revise — **mismatch** — the "exhaustive" body-FK list omitted `retailer_id` on catalog publish, `order_id` on rating creation, the optional `order_id` on a credit entry, and `batch_id` on replacement creation; added left-to-right resolution order — `routes/customers.py:63`, `routes/shoppers.py:67`, `routes/aisle.py:66-68`
- §2.8 rank 5 — revise+insert — ambiguity — a body key the operation does not declare is ignored, not rejected — `routes/catalog.py:186-207`
- §2.8 closing — revise — **mismatch** — "Ranks 1, 2 and 5 apply to every endpoint" was false: the ten payload-free transitions never read the body, so a malformed body there is ignored — `routes/orders.py:178`, `routes/batches.py:154`, `routes/fulfillment.py:150`
- §3.1 — insert — ambiguity — duplicate `store_code` is `ERR_INVALID_REQUEST` (400), tested after all field validation — `routes/catalog.py:51-53`
- §3.1 — insert — ambiguity — duplicate `sku` is `ERR_INVALID_REQUEST` (400) and is the last gate, after retailer resolution and ownership — `routes/catalog.py:132-134`
- §3.1 — insert — ambiguity — a credit entry's `order_id` need not belong to the addressed customer and no order status is examined; only 3 of the 5 reason codes are system-written, so `REPLACEMENT_REFUND`/`SUPPORT_GOODWILL` are support-only and a rejected replacement writes no ledger entry — `routes/customers.py:62-64`, `routes/aisle.py:188-202`
- §3.2 — insert — ambiguity — `delivery_deadline` is never compared to the logical clock at creation; a past deadline is accepted — `routes/orders.py:37`
- §3.2 — insert — ambiguity — a line may draw from another retailer's catalog item, and adding a line rewrites nothing on the order — `routes/orders.py:112,147`
- §3.2 — revise — **mismatch** — placement's two unnamed refusals are `ERR_INVALID_REQUEST` (400) and, since placement declares no body, are evaluated *after* the `DRAFT` gate rather than at rank 5 — `routes/orders.py:182-189`
- §3.3 — insert — ambiguity — the rated shopper is not verified to have delivered the order; duplicate rule is strictly per (shopper, order); `order_id` required and ownership precedes the delivery gate — `routes/shoppers.py:63-73`
- §3.3 — insert — ambiguity — both non-clock test-driving endpoints answer 200 with the re-scored shopper row and bump its version; `stars_sequence` required array of 1-5 ints validated before the shopper 404; empty array accepted — `routes/shoppers.py:126-165`
- §3.6 — insert — ambiguity — a line whose order holds no batch membership gets `ERR_BATCH_NOT_SHOPPING`, not a 404 — `routes/aisle.py:29-31`
- §3.6 — insert — ambiguity — `picked_qty` bounded 1-50, `final_weight_lb` non-negative; the inapplicable member of the pair is validated then ignored — `routes/aisle.py:34-47`
- §3.6 — insert — ambiguity — a pick never touches the owning order: `captured_subtotal_cents` and the order's version stay put until the register — `routes/aisle.py:48-51`
- §3.6 — insert — ambiguity — the proposal's `batch_id` is not checked against the line's own membership; gate order is batch status -> claimant -> line status — `routes/aisle.py:66-73,90-91`
- §3.6 — revise — **mismatch** — approval compares ownership *before* the `PENDING` gate, so a stranger on a resolved request gets `ERR_NOT_RESOURCE_OWNER` — `routes/aisle.py:139-141`
- §3.6 — revise — **mismatch** — same inversion on rejection — `routes/aisle.py:185-187`
- §3.6 — insert — ambiguity — rejection never revisits `payment_status`; an existing `REAUTH_HELD` and its `checkout_blocked_count` survive the refund — `routes/aisle.py:188-202`
- §3.7 — insert — ambiguity — a still-`REQUESTED` member line is refused with `ERR_LINE_NOT_PICKABLE` (409), evaluated before the payment-hold refusal — `routes/fulfillment.py:33-37`
- §3.7 — insert — ambiguity — checkout answers with the batch row, not the re-priced member orders — `routes/fulfillment.py:106`
- §3.8 — insert — ambiguity — delivery answers with the batch, not the payout row it just created — `routes/fulfillment.py:129-130`

Route-layer behavior found already uniquely pinned (no change): all 53 endpoints' authorized-role lists match §4 exactly; attach-order gate order and 201 membership response; claim's seven-check sequence; dispatch/reassign selector guards and "batch left exactly as it was"; start-shopping inclusivity; finalize-payout's payout-then-window order; the clock setter's `current_utc` payload and empty `data`.

### Step 9 totals

- `PRD_FINALIZED.md` 491 lines / 97,593 chars -> `PRD_COMPLETED.md` 493 lines / 116,641 chars (+2 lines, **+19,048 chars**).
- **45 ambiguity-pins, 13 mismatch-revisions** across the three passes (58 changes).
- Orchestrator verification: `PRD_COMPLETED.md` exists, is NOT byte-identical to `PRD_FINALIZED.md` (`cmp` differs), and its tail still ends at the final §5 error-table row. The 8 sweep result files remain on disk at 101/101 each.

Pipeline complete through Step 9.
