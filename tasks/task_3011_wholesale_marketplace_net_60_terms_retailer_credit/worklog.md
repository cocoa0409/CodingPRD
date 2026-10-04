# Worklog — task_3011_wholesale_marketplace_net_60_terms_retailer_credit

## Step 1: Create task directory — 2026-09-29T00:00:00.000Z

Pre-allocated directory `./tasks/task_3011_wholesale_marketplace_net_60_terms_retailer_credit` with `workspace/` inside verified to exist; no new index computed (per command args).

## Step 2: Generate scaffold — 2026-09-29T12:49:15.000Z

All files are written and the scaffold passes lint cleanly. Here is the summary.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3011_wholesale_marketplace_net_60_terms_retailer_credit/`:

- **SCAFFOLD.yaml** — §1.0–§1.7 plus preamble; no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level key `scaffold_difficulty_design` (§1.8)
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top-level key `scaffold_corner_design` (§1.9)

## Counts (per lint report)

- **Entities:** 12 (Retailer, Brand, CreditAccount, Order, OrderLine, Invoice, Payment, ReturnAuthorization, ReturnLine, Payout, ExclusivityGrant, FraudFlag)
- **Endpoints:** 53 (all business resources under `/wholesale`; one test-driving `POST /_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z`)
- **State machines:** 9 — including a cyclic Retailer verification loop with a 3-resubmission cap, parallel Order(fulfillment) × Invoice(collection) dimensions, and a depth-4 fraud cascade
- **Calculations:** 5 (underwriting, return rate, commission tiers, return credit, territory conflict)
- **Validations:** 17 ordered priorities; **Errors:** 21 (all cross-referenced); **Concurrency rules:** 2 (OCC on CreditAccount and Brand versions)
- **Difficulty instances:** 18 (9 rules × 2, all differentiated per §0.5)
- **Corner instances:** 38 authored across 9 sections (30 scanned by lint; the rest are `excluded_because` stubs pointing at §1.8 coverage)

## Design highlights (harder-than-expert calibration)

- Dual-variant calcs on two different entity domains (CreditAccount underwriting provisional/behavioral; ReturnAuthorization credit opening-free/reorder-fee)
- Combinatorial formulas in two distinct modes: (a) tiered multi-input clamp in underwriting, (c) pinned evaluation order for the circular-looking return-credit/invoice-balance dependency
- Boundary precision on distinct metrics: credit `available >= subtotal` exact-cent gate vs strict-`<` haversine territory boundary (on-circle allowed)
- Compensating invariants on different conserved quantities: brand `payout_balance_cents` (process→fail round-trip) and zero-clawback decoupling of brand payouts from retailer write-offs
- Priority-conflict pairs spanning different error categories (state vs business_fiscal; business_safety vs quantity integrity)

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Note: the lint's collection-segment derivation requires resource paths under the declared `api_prefix`, so all business endpoints live under `/wholesale` (test-driving clock endpoint stays at root). No sibling task directories were inspected.

## Step 3: Copy shared files — 2026-09-29T12:49:28.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-29T12:57:02.000Z

Done. The PRD is written to `workspace/PRD.md`.

**PRD line count:** 285 lines

**Section list:**
- §1. Introduction (business context + scope, plus the logical-clock note)
- §2. Global Specifications & System-Wide Principles (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock and Lazy Time Evaluation, 2.6 Nested Resource Retrieval, 2.7 Money/Units/Rounding, 2.8 OCC, 2.9 Cross-Entity Consistency and Cascades, 2.10 Payout Ledger Principle)
- §3. Business Logic & Workflows (11 subsections: retailer verification loop, brand onboarding, credit underwriting, order placement + validation ladder, shipment/invoicing/payout scheduling, returns + abuse guard, fraud cascades, exclusivity/territory, collections/write-offs, payout processing, browsing/reverse reachability)
- §4. Endpoint Definitions (53-endpoint, 4-column table)
- §5. Error Code Catalogue (21-error, 2-column table)

**Coverage audit (machine-verified against SCAFFOLD.yaml):**
- Contract 1, Field-Name Coverage: PASS — entities[].fields 63/63; endpoints[].input 36/36
- Contract 2, Rule Coverage: PASS — 17/17 validations, 2/2 OCC rules, all transitions across 9 state machines, 5/5 calculations with all constants, 21/21 error IDs, 28/28 state enum values, 40/40 enum field values, 53/53 endpoints
- Contract 3, §3 Path Purity: PASS — 338 backtick tokens scanned, 0 paths/methods
- The two prohibited files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were never opened or referenced.

## Step 5 (attempt 1, voided): Concurrent duplicate generation — 2026-09-29T13:42:29.000Z

Orchestrator error: the Step 5 (test generation) Agent prompt was mistakenly included twice in a single message, so two test-generator subagents ran concurrently and both wrote to test_helpers/ and test_suite/. On-disk state is an interleaved mix (11 test files but overlapping/duplicated coverage; each subagent reported 72 tests). Both directories were deleted (rm -rf) and Step 5 will be re-run as a single clean subagent. No implementation/ exists yet; Step 6 was never launched.

## Step 5: Generate unit tests (clean re-run) — 2026-09-29T14:31:09.000Z

All checks pass. Final state:

**Files written**: test_helpers/ (Stage 1): __init__.py, types.py (Payment omits updated_at/version per PRD §2.4), api_client.py (one method per PRD §4 endpoint), api_errors.py (21 error IDs registered), constants.py, factories.py, test_users.py, assertions.py, fixtures.py. test_suite/ (Stage 2): conftest.py plus 11 test files (test_01..test_21 naming).

**Test counts**: queue A (Difficulty) — 37 tests; queue B (Corner) — 30 tests; total 67. pytest collects cleanly (67 collected, no import errors).

**Coverage audit**: PASS. All 11 queue-A instances have ≥2 tests; all 20 non-stub queue-B instances have ≥1 test. All 5 excluded_because stubs skipped without emitting tests. One corner stub (Corner/errors/error_stale_version_covered_by_occ_instances) points to a difficulty_instance that does not resolve in the difficulty index — a corner-design bug; stub skipped per spec, and both OCC rules are covered by Corner/cross_cutting OCC instances.

**Instances skipped or reduced on PRD-first grounds** (no placeholders):
- Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_return_receive — validation-priority silence (PRD never orders ERR_RETURN_ABUSE_GUARD vs ERR_RETURN_QTY_EXCEEDED across endpoints). Emitted instead: isolated abuse-guard rejection and below-threshold approval tests.
- Corner/endpoints/clock_default_and_set — reduced to clock-echo assertions; unverifiable pre-set read dropped (no read endpoint in PRD).

**PRD-citation audit**: every test docstring ends with exactly one Design: tag resolving to a real instance; every quoted PRD passage (≥30 chars) survives whitespace-normalized literal search of workspace/PRD.md (0 unmatched across 67 tests).

**Notable design decisions**: return-authorization fixtures resolve order_line_id via GET /wholesale/orders/{id}/lines; territory boundary test uses true double-precision haversine value 111.19492664455873 km (design yaml's 110.5743885 was a computed mismatch).

## Step 6: Generate implementation — 2026-09-29T14:45:59.000Z

Done. Summary:

**Files written** (all under workspace/implementation/): app.py (~1100 lines, single-file Flask app), start.sh (executable foreground launcher; guarded pip install; exec python3 app.py; binds 0.0.0.0:$PORT default 10000), requirements.txt (flask>=2.2,<4).

**Endpoint count: 46 routes** — clock setter, 7 retailer routes, 5 brand routes, 6 credit-account routes (incl. OCC-guarded limit-review), 9 order routes (incl. nested reads + ship/deliver/cancel), 4 invoice routes, 6 return routes, 5 payout routes, 4 exclusivity-grant routes, 5 fraud-flag routes.

**Key behaviors**: logical clock fixed at 2026-09-01T00:00:00Z with lazy OVERDUE/EXPIRED flips; response envelope per §2.2; 5-role auth with validation ladder in scaffold priority order; underwriting calc (base by store type, +50k/on-time, −100k/late-or-written-off, clamp 50k–1M), provisional at open, behavioral at limit-review; order placement ladder (fraud → case-pack/brand-active → haversine territory strict < → min order → credit); ship atomically issues invoice + payout (2500/1500/0 bps tiers, half-up) and credits brand ledger; return receive pinned evaluation order (merchandise → fee → clamp to amount_due), return_rate recomputed final-variant after marking RECEIVED; payout ledger with exact fail compensation; fraud cascades (STRAW_STOREFRONT/CONSUMER_RESELLER confirm → suspend/freeze/cancel PLACED orders with compensating 0-bps PAID payouts; RETURN_ABUSE debits 5000, auto-suspend at 5); OCC on limit-review and grant create; no seeding.

**Boot sanity check**: passed. Fresh start.sh boots in <2s; end-to-end scenario verified (registration → verification → credit account → order → ship → invoice/payout → deliver → return → payment → payout processing → OVERDUE flip → write-off → OCC stale rejection → exclusivity conflict → resubmission cap). No 500s in any server log. Note: return_rate recomputation ordering bug found and fixed during smoke testing.

## Step 7: Run tests and iterate — 2026-09-29T15:16:53.000Z

All 8 rounds pass 67/67. Clean sweep achieved.

**Iterations run:** 3 eight-round parallel sweeps (round 1: 9/67; round 2: 56/67; round 3: 67/67 in all 8 rounds).

**Tests deleted:** none.

**Fixes applied to test_helpers/:** none — fixtures were PRD-faithful; initial mass failure (58/67, "Invalid decision") traced to implementation rejecting PRD-derived decision vocabulary.

**Fixes applied to test_suite/ (all STEP 2 test bugs):**
- test_04_return_credit_evaluation_order.py — both tests: removed "fully return the opening order" setup step (drives PRD-defined return_rate to 1.0, making reorder return approval unreachable under §3.6 abuse guard). Second test restructured to exercise PAID flip via full opening-order return (fee 0), since on a partially-paid reorder PRD's pinned credit formula (clamp to amount_due_cents) uniquely yields balance −2000/OPEN, never PAID.
- test_07_cascades.py::test_return_receive_recomputes_retailer_return_rate — expected rate 0.5 → 1.0: PRD §3.6 sequences net_sold_qty drawdown before rate recompute, so 2 returned / 2 remaining = 1.0.
- test_10_boundary_precision.py::test_subtotal_one_cent_over_available_credit_is_rejected — shipped first order (only shipped orders create invoices; only outstanding invoice balances reduce available_cents per §3.3), raised second order subtotal 1 → 1000 cents to clear min-order rung.
- test_11_cross_entity_gates.py (both frozen-account tests) — expected error ERR_CREDIT_LIMIT_EXCEEDED → ERR_FRAUD_HOLD: FROZEN account only reachable via fraud cascade which also suspends retailer; §3.4 ladder puts fraud gate before credit check. FROZEN assertion retained.
- test_16_calculation_corners.py — commission tier tests: retailer store_type ONLINE → BRICK_AND_MORTAR so two 100000-cent orders fit provisional limit; test_return_rate_excludes_cancelled_orders expected values corrected to 1.0 / 0.3333 / 1.0 per drawdown-then-recompute ordering.

**Fixes applied to implementation/ (workspace/implementation/app.py):**
- review_document — accept CONFIRM/REJECT (PRD §4 vocabulary) in addition to CONFIRMED/REJECTED; accept RESALE_CERT document_type spelling matching PRD's resale_cert_status field naming.
- verify_retailer and review_return_auth — accept APPROVE/REJECT (PRD §3.1 "an approving decision", §3.6 "approves or rejects") alongside lowercase forms.
- ts() — omit milliseconds when zero so logical clock reports PRD-pinned 2026-09-01T00:00:00Z format (§2.5).
- sync_account_available — bump credit account version when payment/shipment/return/write-off mutate derived fields, per §2.8 OCC rule.
- create_order, cancel_order, fraud-confirm cascade — recompute retailer return_rate on order placement and cancellation per §3.6 ("recomputed on every unit-affecting mutation").

Earlier flaky connection resets in test_repeat_cancel_rejected_invalid_state did not recur once stale manual-test servers were cleared; all 8 rounds completed cleanly at 67/67.

## Step 8: Finalize PRD — 2026-09-29T15:21:54.000Z

PRD_FINALIZED.md written. Line counts: PRD.md 284 → PRD_FINALIZED.md 284 (0.00% delta; all inline revisions/inserts, no new sections).

**Changes:**
- §2.5 — revise — pins now_iso8601 omits milliseconds when zero (e.g. 2026-09-01T00:00:00Z) — app.py:29-34 (ts()), call site app.py:427.
- §2.8 — insert — payment/shipment/return receipt/write-off mutating derived fields advances credit account version + updated_at — app.py:328-334; call sites 926 (ship), 997 (payment), 1024 (write-off), 1206 (return receive).
- §3.1 — insert — pins document_type spellings (storefront_proof/STOREFRONT_PROOF, resale_certificate/RESALE_CERTIFICATE/resale_cert/RESALE_CERT) and decision vocabulary CONFIRM/CONFIRMED, REJECT/REJECTED, others → ERR_INVALID_REQUEST — app.py:490-510.
- §3.1 — insert — pins verify decision vocabulary APPROVE (also approve, APPROVED) / REJECT (also reject, REJECTED) — app.py:513-534.
- §3.6 — insert — same decision vocabulary for return-authorization review — app.py:1115-1123.
- §3.6 — revise — return_rate recomputed on order placement (denominator grows) and cancellation (denominator shrinks), in addition to return receipt — app.py:826, 956, 1447, 1205, 1135.

**Step-7 test-suite items needing no PRD edit:** test_04/test_07/test_10/test_11/test_16 fixes were pure fixture/expectation bugs — PRD already pinned abuse guard, drawdown-before-recompute, ship-before-invoice availability, fraud-before-credit ladder, commission credit check.

**Per-edit pre-edit search log (NO-NEW-MISMATCH):** 6 edits, each with (a) subject, (b) enumerated impl paths (all ts() call sites; all sync_account_available call sites + fraud cascade + limit_review; review_document as sole document_type endpoint; verify_retailer + review_return_auth shared tuples; grep confirming only 3 endpoints take decision; all 5 recompute_return_rate call sites), (c) wording adjustments — full detail in subagent report; all edits verified consistent with every enumerated path.

## Step 9: Complete PRD — 2026-09-29T15:41:09.000Z

PRD_COMPLETED.md written. Source: PRD_FINALIZED.md (284 lines, 45,925 chars) → PRD_COMPLETED.md (286 lines, 53,072 chars); net +2 lines / +7,147 chars across 21 edited passages (27 diff hunks).

**Counts:** ambiguity-pins: 20; mismatch-revisions: 1.

**Changes (per passage):**
- §2.2 — insert — ambiguity — unmatched routes (404)/wrong methods (405) return standard envelope with ERR_INVALID_REQUEST — app.py:135-152
- §2.3 — revise — ambiguity — limit/offset out-of-range clamped (not rejected), non-integer → ERR_INVALID_REQUEST 400, created_at ties break by creation sequence, total_count/has_more semantics, process-due returns paginated array of moved payouts — app.py:234-254, 1229-1244
- §2.4 — revise — ambiguity — version starts at 1; created_at/updated_at follow clock fractional-second rendering — app.py:29-34, 81-90
- §2.5 — revise — ambiguity — unparsable to_iso8601 → ERR_INVALID_REQUEST 400; naive instants treated as UTC; response shape {"now_iso8601": ...} — app.py:37-49, 422-427
- §2.7 — insert — ambiguity — return_rate surfaced as JSON number equal to 4-decimal rounded ratio — app.py:392
- §3.1 — revise — ambiguity — invalid store_type → ERR_INVALID_REQUEST 400; non-matching referral_code registers unbound without failing — app.py:446-453
- §3.1 — revise — ambiguity — new retailer carries return_rate 0 and null risk_tier until account opening — app.py:462-467
- §3.1 — revise — ambiguity — non-PENDING retailer → ERR_INVALID_STATE 409 for approve and reject — app.py:522-524
- §3.1 — revise — ambiguity — request-more-info from non-PENDING → 409; resubmit state gate (409) checked before resubmission limit (422) — app.py:542-544, 559-564
- §3.2 — insert — ambiguity — referral_code is REF--prefixed alphanumeric — app.py:597
- §3.2 — revise — ambiguity — activation from non-DRAFT → 409, incomplete config → ERR_INVALID_REQUEST 400, reinstate of non-SUSPENDED → 409 — app.py:626-632, 643-644
- §3.3 — revise — ambiguity — non-VERIFIED retailer or duplicate account → 409; opening assigns retailer risk_tier — app.py:658-663
- §3.3 — revise — ambiguity — 409 pins for unfreeze preconditions; close applies lazy overdue evaluation first — app.py:711-715, 726-731
- §3.4 — revise — ambiguity — uniform body-shape rules (non-object 400, unknown/missing/mistyped fields 400, missing body = empty object) and order-line shape — app.py:203-224, 751-767
- §3.4 — revise — ambiguity — missing credit account also yields ERR_CREDIT_LIMIT_EXCEEDED — app.py:796-800
- §3.4/§3.5 — revise — MISMATCH — ship endpoint fails with ERR_FRAUD_HOLD (not only the two errors PRD named) when purchasing retailer no longer VERIFIED; ship from non-PLACED → 409 — app.py:878-888
- §3.5 — insert — ambiguity — deliver from non-SHIPPED and cancel from non-PLACED → ERR_INVALID_STATE 409 — app.py:936-937, 949-950
- §3.6 — revise — ambiguity — return-line shape validation (400), order_line_id must belong to order (400), no order-status gate at request time — app.py:1041-1064
- §3.6 — insert — ambiguity — new authorization carries return_fee_cents/credit_cents at 0 until receipt — app.py:1065-1071
- §3.6 — revise — ambiguity — approval against order not in DELIVERED/PARTIALLY_RETURNED → 409; review of non-REQUESTED authorization → 409 — app.py:1126-1133
- §3.6 — revise — ambiguity — receipt requires order DELIVERED/PARTIALLY_RETURNED (409); lazy invoice evaluation precedes credit clamp; no-invoice degenerate case clamps at zero; receipt recomputes available_cents; final return-rate recompute includes this authorization's units — app.py:1149-1206
- §3.7 — revise — ambiguity — invalid flag_type → 400; confirm/dismiss of non-OPEN flag → 409; conditional cascade steps pinned (suspend only if VERIFIED, freeze only if ACTIVE, RETURN_ABUSE with no linked order applies no assessment); cascade cancellations recompute return_rate — app.py:1373-1374, 1427-1456, 1465-1466
- §3.8 — revise — ambiguity — OCC check precedes window/overlap validation; revoke applies lazy expiry first, rejects non-ACTIVE with 409 — app.py:1293-1299, 1353-1355
- §3.9 — insert — ambiguity — lazy overdue evaluation before payment; non-OPEN/OVERDUE invoice → 409 — app.py:975, 979-980
- §3.10 — revise — ambiguity — batch processes due payouts in ascending created_at order; complete/fail on non-PROCESSING → 409 — app.py:1233-1234, 1252-1253, 1264-1265
- §3.11 — insert — ambiguity — order-invoice listing applies lazy evaluation; order-line return-lines listing unfiltered by authorization status — app.py:858-861, 1110-1112
