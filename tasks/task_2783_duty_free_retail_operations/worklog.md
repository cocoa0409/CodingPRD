# Worklog — task_2783_duty_free_retail_operations

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2783_duty_free_retail_operations` and `workspace/` (pre-assigned path; no index allocation performed).

## Step 2: Generate scaffold — 2026-09-04T21:48:00.000Z

All three artifacts are complete and the linter is clean.

## Files

| Path | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2956 | 138102 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2145 | 133464 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3607 | 223098 |

## SCAFFOLD.yaml (§1.0–§1.7)

- **Complexity profile**: primary `compliance_audit`, secondary `quota_allocation`; topology `flat`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`; layers `dual_variant_calculation`, `cascading_side_effects`, `optimistic_concurrency`, `rate_threshold_triggers`.
- **14 entities**, **9 state machines**, **2 concurrency rules**, **7 calculations**, **62 validations** (priority ladder 10→85), **62 endpoints**, **62 errors**, **5 roles** (`Passenger` is `entity_backed:PassengerItinerary`, the other four `opaque`).
- Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears as a top-level key; `api_prefix` is the empty string.

## §1.8 — 24 instances across all nine Difficulty Rules

`dual_variant_calc` 2, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 2, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 2, `compensating_invariant` 3.

## §1.9 — 56 instances (44 with full test recipes + 12 `excluded_because` stubs)

entities 10, state_machines 13, calculations 4, validations 9, endpoints 4, errors 4, rbac 3, complexity_layers 8, consistency_model 1 — the nine claim-extraction-guide sections, no invented categories.

## Verdict

```
Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  980

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Findings worth flagging for downstream steps

1. **§1.9 must be section-grouped, not a flat instance list.** My first draft emitted `- section: X` + instance keys at the same level; the linter silently reported `§1.9 instances scanned: 0` and skipped all 500+ corner calls without any violation. The structure the lint (and skill schema) expects is `- section: X` / `instances:` / `- name: ...`. A "clean lint" with a zero instance count is a false pass — worth checking that number on every task.
2. **Five HTTP-status mismatches** between asserts and the §1.6 catalog were caught by cross-checking every `HTTP <n> ... ERR_*` pair against `errors[].http`: `ERR_RESERVATION_WINDOW_INVALID` (422 not 409), `ERR_ITINERARY_NOT_INTERNATIONAL`, `ERR_EMPTY_BASKET` and `ERR_SEGREGATION_OF_DUTIES` (all 409 not 422). All fixed; the check now reports zero.
3. **Stub shape**: six early stubs used `excluded_because: >- <prose>` with no `grounds:`; the skill requires `excluded_because: {difficulty_instance, rationale}` plus `grounds`. Rewritten. All 12 `difficulty_instance` references resolve to real §1.8 instance names.
4. Verified independently: all 62 error ids are triggered by at least one recipe; 80 instance names are unique across both design files; zero unbound `${var}` placeholders across all recipes and asserts; no `harder than expert level` directive leaked into any artifact.

Orchestrator verification: `grep -rn -i "harder than expert"` over the task dir returned nothing; `scenario:` in SCAFFOLD.yaml begins at the "2783." line with no difficulty directive.

## Step 3: Copy shared files — 2026-09-04T21:50:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T22:06:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **424 lines**. Ends at a real boundary (final row of the §5 error table, `ERR_VOID_AFTER_PERIOD_CLOSE | 409`), not mid-sentence.

**Section list**
- `# Duty-Free Retail Operations API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination and Collection Filters · 2.4 The Logical Clock · 2.5 Resource Identity, Timestamps and Versioning · 2.6 Money, Basis Points and Rounding Discipline · 2.7 Stale-Version Guards on Reservation and Basket Writes · 2.8 Rejection Precedence · 2.9 The Append-Only Bonded Ledger · 2.10 Segregation of Duties and Period Sealing
- `## 3. Business Logic & Workflows` — 3.1 The Commercial Estate (Terminals, Brands, Exclusivity, Arrival Allowances) · 3.2 Admitting Products into the Assortment · 3.3 Bonded Stock Under Duty Suspension · 3.4 Passenger Itineraries and Boarding-Pass Verification · 3.5 Building the Basket and Pricing the Exemption · 3.6 Sealed Bags for Connecting Passengers · 3.7 Handover at the Gate, and Compensating a Void · 3.8 Pre-Orders and the Pick-Up-on-Return Programme · 3.9 Customs Audits, Shrinkage and Unaccounted-Goods Duty · 3.10 Concession Settlement: Percentage Rent, Minimum Guarantees and Net Rent
- `## 4. Endpoint Definitions` (62-row table: Method / Path / Description / Authorized Role(s))
- `## 5. Error Code Catalogue` (62-row table: Error ID / HTTP Status)

**Coverage verified programmatically against the scaffold (not by eye)**
- Endpoints: 62/62. Table row set is exactly equal to the scaffold's `(method, path)` set — no extras, no omissions, roles transcribed from `roles`.
- Errors: 62/62 ids present with scaffold HTTP statuses; all 62 also named in §2.8's 14-tier precedence ladder or the §3 prose that raises them.
- State machines: all 9 (`Sale.fulfillment_status`, `Sale.duty_status`, `PassengerItinerary`, `CustomsAudit`, `SealedBag`, `PreOrder`, `ConcessionAgreement`, `Product`, `Brand`, `ExclusivityGrant` — Sale carrying the parallel pair) with every state literal present, including the cyclic `SCANNED → AMENDED → SCANNED` and `SUBMITTED → INFO_REQUESTED → SUBMITTED` loops.
- Calculations: all 7, with both variants each for `duty_exemption_accounting` (SUSPENDED_ESTIMATE / EXEMPT_CONFIRMED_FINAL) and `concession_rent_accrual` (PROVISIONAL_PERIODIC / FINAL_PERIOD_CLOSE), plus `net_rent_settlement`, `unaccounted_goods_duty_assessment`, `terminal_nationality_mix`, `bonded_duty_suspended_value`, `sealed_bag_liquid_volume`.

**Hard Contract reports**
1. Field-Name Coverage — **PASS.** All 111 entity field names and all 74 distinct endpoint `input` / path-parameter identifiers appear verbatim inside backticks. Zero missing.
2. Rule Coverage — **PASS.** All 62 validations expressed in prose with their precedence position; both OCC guards (`expected_stock_item_version` → `ERR_STALE_STOCK_ITEM_VERSION` 412, `expected_sale_version` → `ERR_STALE_SALE_VERSION` 412); every transition's preconditions and side effects including the pickup and void cascades; every formula reconstructible (pinned rounding order, floor vs round-half-up, 10000 bps denominator, tier floors 5,000,000 / 2,000,000 cents at 400/250/100 bps keyed on the gross figure, 200 bps tolerance, penalty multiplier 2 at `round_count` >= 3, `SEAL_VALIDITY_HOURS` 96, 30-day mix window, +/-24h reservation buffer); every `applies_to` scope, field default and sibling-branch symmetry (CLOSED_CLEAN vs CLOSED_ASSESSED, INTACT vs TAMPERED, PERCENTAGE vs MINIMUM_GUARANTEE).
3. §3 Path Purity — **PASS.** Zero backticked tokens in §3 contain `/` or begin with an HTTP method, and zero bare method words appear in §3 prose. Endpoints are referenced only by state-transition pair, role + action verb, or capability description. Paths appear only in §2.7 and the §4 table.

Additional checks: §2.2 is byte-identical to `section-2.2-response-structure.md`; only 4 code fences in the file, both JSON blocks inside the fixed §2.2 — no pseudocode anywhere; fuzzy/approximating-word scan clean. Neither design yaml was opened, grepped or referenced, and no sibling task directory was read.

Scaffold inconsistencies resolved by decision, so the implementer sees one consistent rule (flagged for the scaffold owner): `sealed_bag_required` documented with the three-condition form (`ICAO_STEB` regime + `has_connection` + at least one `is_liquid` line) rather than the entity field's two-condition form; `arrival_advisory` ordered by category name ascending rather than `created_at`; superseded `AllowanceRule` stated to bump `updated_at`/`version`; itinerary amend stated to refresh the terminal mix and bump the terminal `version`; seal-expiry clock precondition applied to both verify outcomes; non-postable `movement_type`, zero `qty_delta`, non-positive RECEIPT, and `final_destination_country` mismatch when `has_connection` is false all mapped to `ERR_INVALID_REQUEST`; brand `name` uniqueness stated as convention with no dedicated code.

Orchestrator truncation check (per the known doc-generator failure mode): `tail -15 PRD.md` ends on a complete error-table row and `grep "^#"` shows all sections 1-5 present, so no regeneration was needed.

## Step 6: Generate implementation — 2026-09-04T22:35:00.000Z

Implementation complete for task 2783.

## Files written — `workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` (executable, guarded pip, `exec python3 app.py`) | 10 |
| `requirements.txt` (`flask==3.0.3`) | 1 |
| `app.py` (blueprint registration, ApiError/HTTPException/500 handlers, `0.0.0.0:$PORT`) | 63 |
| `db.py`, `clock.py`, `errors.py`, `response.py`, `middleware.py` | 65 / 75 / 96 / 52 / 53 |
| `services/`: `money.py` 19, `mix.py` 40, `scope.py` 45, `ledger.py` 84, `rent.py` 90, `lookup.py` 94, `validate.py` 95, `pricing.py` 141 | 608 |
| `routes/`: `clock_routes.py` 20, `agreements.py` 104, `bonded.py` 110, `itineraries.py` 145, `preorders.py` 154, `audits.py` 155, `estate.py` 324, `sales.py` 334 | 1346 |
| **total** | **2369** |

## Endpoint coverage
62 routes registered. Mechanically diffed the Flask URL map against the 62 rows of the PRD §4 endpoint table (method + path, params normalised) — the two sets are **identical, zero drift**.

## Boot / behaviour verification
Booted via `bash start.sh` on port 56913 (killed afterwards by captured PID only; port confirmed released, other pipelines' servers untouched). Fresh boot serves an **empty store** and a logical clock at exactly `2026-08-01T00:00:00.000Z` — no seeding anywhere.

Two end-to-end smoke scripts passed against the live server, exercising:
- estate setup, nationality-mix refresh from scans, product listing gating;
- bonded receipt -> derived `on_hand/reserved/available` and `duty_suspended_value_cents` (100 x 16000 x 2200bps = 352000);
- allowance waterfall on a direct journey (`sealed_bag_required` false) and on a connecting journey (`SUSPENDED_ESTIMATE` on the connection country -> duty 3520, `ERR_SEALED_BAG_REQUIRED` at pickup, bag issue + `INTACT_VERIFIED`, then `EXEMPT_CONFIRMED_FINAL` on the final destination with duty back to 0);
- rent projection (period_days 31, elapsed_days 5, prorated MG 80645, basis MINIMUM_GUARANTEE) and settlement (final 500000, tier 100bps -> credit 5000, net 495000);
- pre-orders: hold on the ledger, buffered +/-24h capacity -> `ERR_RESERVATION_CAPACITY_OVERLAP` 409, OCC -> `ERR_STALE_STOCK_ITEM_VERSION` 412, ownership -> `ERR_NOT_ITINERARY_OWNER` 403, conversion creating a `PRE_ORDER` sale + `RESERVATION_RELEASE`;
- customs audit: `ERR_AUDIT_NOT_SUBMITTED`, `ERR_SEGREGATION_OF_DUTIES`, INFO_REQUESTED round-count loop, and the full CLOSED_ASSESSED cascade — movements came out exactly `RECEIPT +10 / RESERVATION_HOLD +8 / SHRINKAGE_WRITE_OFF -9 / RESERVATION_RELEASE -8`, pre-order -> RELEASED, terminal liability += 1350, `last_reconciled_at` stamped;
- envelope and auth: 401 unknown role, 403 wrong role, 404 entity-specific, 422 backwards clock.

## Key spec decisions (PRD wins over SCAFFOLD/corner-design, per the skill)
- `ERR_AGREEMENT_NOT_ACTIVE` (DRAFT check) precedes `ERR_AGREEMENT_ALREADY_ACTIVE` on activate; `ERR_ITINERARY_NOT_INTERNATIONAL` is 409; `sku` uniqueness is global; `arrival_advisory` sorted by category name ASC; state checks (tier 8) precede temporal (12) and SoD/business-constraint checks on audits and pre-order convert.
- `BondedMovement` carries only `id`/`created_at` (+ mutable `reversed`); stock-item `version` bumps exactly once per appending request even when a close appends several entries.

## Step 5: Generate unit tests — 2026-09-04T23:20:00.000Z

Test suite generation is complete and verified.

## Files written

`test_helpers/` — 1,696 lines: `__init__.py` 7, `constants.py` 111, `api_errors.py` 158, `test_users.py` 68, `types.py` 212, `api_client.py` 270, `factories.py` 341, `assertions.py` 216, `fixtures.py` 313.

`test_suite/` — 4,616 lines, 108 tests: `conftest.py` 21; `test_01_estate_registration_defaults.py` 417 (14 tests), `test_02_request_validation_and_precedence.py` 405 (15), `test_03_exclusivity_windows_and_assortment_gates.py` 420 (10), `test_04_bonded_ledger_and_reversal.py` 156 (3), `test_05_itinerary_scan_and_amendment.py` 204 (4), `test_06_basket_assembly_and_occ.py` 279 (6), `test_07_duty_exemption_waterfall.py` 483 (10), `test_08_sealed_bags_and_transport_safety.py` 432 (9), `test_09_handover_and_void_compensation.py` 377 (9), `test_10_pre_orders_and_reservation_capacity.py` 299 (6), `test_11_customs_audit_and_shrinkage.py` 486 (10), `test_12_concession_settlement.py` 320 (8), `test_13_role_authorization_and_ownership.py` 240 (3), `test_14_not_found_and_error_catalogue.py` 77 (1).

Nothing was created under `workspace/`, and `workspace/implementation/` and `worklog.md` were never touched.

## Test counts per queue

- Queue A (Difficulty, §1.8): 48 tests, every surviving instance carrying at least 2.
- Queue B (Corner, §1.9): 60 tests, every surviving non-stub instance carrying at least 1.
- 108 `Design:` lines for 108 test functions — exactly one per test, none dual-tagged, none untagged.

## Verification

- `python3 -m pyflakes test_suite/*.py test_helpers/*.py` — silent.
- Citation checker (greps every `PRD <section>: "<sentence>"` capture against `workspace/PRD.md`) — `missing: 0`, so all 108 citations are verbatim PRD text.
- Call-binding checker (`inspect.signature(...).bind` over every `api.*`, `fx.*`, `f.*` and local-helper call) — `problems: 0`.
- Design-tag checker against both yamls — 0 tags pointing at unknown instances; of the 80 instances, 12 are `excluded_because:` stubs and all 68 non-stub instances are covered at or above their minimum.
- `pytest --collect-only` — 108 tests collected, no import or collection errors.
- No occurrence of "scaffold" anywhere in the generated text.

## Skipped design instances

No surviving instance was skipped. The only untranslated instances are the 12 `excluded_because:` stubs, which the spec excludes by construction.

## Instances translated with PRD-driven corrections

Where a design digest contradicted the PRD, the PRD won and the instance was still translated:

- Audit `round_count` starts at 1 (not 0) and the snapshot field is `expected_qty_snapshot`.
- A newly activated agreement keeps `final_rent_cents` null, not 0 (affects `rent_projection_and_nationality_mix_reads_never_mutate_state`).
- Peer-role denials are `ERR_FORBIDDEN_ROLE`, not `ERR_UNAUTHORIZED`.
- Errors ride under `data` as `{error_id, message}`, so the digests' "data null" claims were dropped.
- `repeating_a_completed_lifecycle_trigger_is_refused_per_entity` lost its re-activate leg: PRD §3.10 yields `ERR_AGREEMENT_NOT_ACTIVE`, not the design's `ERR_AGREEMENT_ALREADY_ACTIVE`; the product-list and grant-revoke repeats carry the instance.
- The nine 404 probes use valid hex v4 UUIDs from `constants.MISSING_UUIDS` because the design's placeholder ids contain non-hex characters; the allowance-rule probe uses an operator role rather than Passenger, since no itinerary exists to back a passenger identity.

## One real latent bug fixed in the helpers

`test_helpers/assertions.py::assert_stock_quantities` took `(stock_item, on_hand_qty, reserved_qty, duty_suspended_value_cents=None)` but 12 call sites passed `on_hand=`, `reserved=`, `available=`, which would have raised `TypeError` at runtime. The signature now accepts both spellings plus an explicit `available` assertion; the call-binding checker proves no remaining call site mis-binds.

Orchestrator check: `test_helpers/` and `test_suite/` are both at the task root; nothing test-shaped landed under `workspace/`; only one `worklog.md` exists (task root).

## Step 7: Run tests and iterate — 2026-09-04T23:41:00.000Z

Clean exit after 2 iterations.

## Summary

**Iterations run:** 2 (each an 8-round parallel sweep under `setsid nohup`).

**Tests deleted:** none. No test failed STEP 1 — both failures traced to a fixture defect, not to PRD silence or non-unique derivability.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `stocked_ledger()`: guard the receipt post behind `if qty > 0`. The helper unconditionally posted a `RECEIPT` movement with the caller's quantity, so `liquor_estate(api, receipt_qty=0, ...)` issued `qty_delta=0`. PRD §3.3 states verbatim that "a `qty_delta` of zero or a non-positive `RECEIPT`, is refused as a malformed request with `ERR_INVALID_REQUEST`", so the implementation's 422 was correct and the fixture's request was the PRD violation. A caller asking for zero units wants an empty ledger, so no movement is posted at all.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the PRD-required zero-delta rejection was deliberately left in place rather than weakened to accommodate the fixture.

**Failures diagnosed (iteration 1, both deterministic in all 8 rounds — same root cause):**
- `test_a_ledger_movement_carries_no_updated_at_and_no_version` (`test_suite/test_02_request_validation_and_precedence.py:311`)
- `test_a_ledger_movement_offers_no_editing_route` (`test_suite/test_02_request_validation_and_precedence.py:339`)

Both died in setup with `Expected 201, got 422: ERR_INVALID_REQUEST — Field 'qty_delta' must not be zero.`

**Final sweep, per-round figures quoted from `results.$i.json`:** rounds 1-8 all 108 / 108 passed, 0 failed, 0 errors.

No flakiness surfaced: the union of failing tests across all 8 final rounds is empty. `worklog.md` was not touched, and the implementation writes no on-disk storage (no SQLite or JSON dump found).

Orchestrator verification (independent re-read of all 8 `results.$i.json`): `108 108` for every round i = 1..8.

Step 8 skip decision: NOT skipped. The skill's skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; Step 7 made one `test_helpers/` fix across 2 iterations, so Step 8 runs. Since there were no `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate outcome here.

## Step 8: Finalize PRD — 2026-09-04T23:42:00.000Z

Done. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` — no PRD silence or PRD/impl mismatch is traceable to `<step_7_diff>`.

## Line counts
- `PRD.md`: 424 lines
- `PRD_FINALIZED.md`: 424 lines
- Delta: 0 lines, 0.0% (identical md5)

## Changes
None.

## Analysis of each `<step_7_diff>` item

**1. `test_helpers/fixtures.py` — `stocked_ledger()` guarded behind `if qty > 0`** (the only fix in the diff)

- Subject: rejection of a zero / non-positive `qty_delta` on a manually posted bonded movement.
- Impl paths enumerated and read: `implementation/routes/bonded.py` `create_movement()` (`MANUAL_TYPES` gate, the required/int/`== 0`/`RECEIPT <= 0` ladder, then the `on_hand_qty + qty_delta < 0` -> `ERR_BONDED_STOCK_INSUFFICIENT` check), `reverse_movement()` (reversibility gate + insufficiency guard), and `services/ledger.append` as the shared writer for every synthesised movement type.
- PRD coverage: `PRD.md:181` (§3.3) already states verbatim that a synthesised-type post, "like a `qty_delta` of zero or a non-positive `RECEIPT`, is refused as a malformed request with `ERR_INVALID_REQUEST`". The impl's 422 is exactly this rule; the fixture's `receipt_qty=0` request was the PRD violation. Nothing to pin.

**2. Two iteration-1 setup failures** (`test_02_request_validation_and_precedence.py:311` and `:339`)

- Both died in *setup* with the same 422, i.e. the same fixture defect — neither reached its own assertions, so neither is evidence of ambiguity in the behavior it tests.
- The behaviors those tests do assert are also already pinned verbatim: `PRD.md:98` (§2.5) — "A movement is an immutable accounting entry: it carries `id` and `created_at` only, and has neither `updated_at` nor `version`" — and `PRD.md:183` (§3.3) — "A manual entry is never edited or deleted" plus the compensating-`REVERSAL` route and its 201. The impl matches: no PUT/PATCH/DELETE route exists on the movement resource, only the reverse POST.

**3. Fixes to `implementation/`: none; tests deleted: none.** With no implementation change and no weakened/removed assertion, there is no site where Step 7 revealed the PRD failing to uniquely determine what the code does.

Per the method's explicit allowance, the copy was left unchanged rather than inventing edits.

Orchestrator note: byte-identical `PRD_FINALIZED.md` (both 90036 bytes) is the expected and legitimate outcome when Step 7 made zero `implementation/` fixes. Step 9, by contrast, must not be byte-identical — it is a full impl scan and will be run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, with only pass 1 performing the `cp`.

## Step 9: Complete PRD — 2026-09-05T00:10:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 performed the `cp`; passes 2 and 3 edited in place only). Total: **26 ambiguity-pins, 4 mismatch-revisions**; 424 lines, 62 changed lines vs `PRD_FINALIZED.md` (90036 -> 98540 bytes).

### Pass 1 — core + `routes/clock_routes.py` + `routes/estate.py` + `routes/itineraries.py`

Performed `cp PRD_FINALIZED.md PRD_COMPLETED.md` (md5 `7a4dbc27...`, 424 lines), then edited in place. 13 ambiguity-pins, 0 mismatch-revisions.

- §2.1 — revise — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty for the 401 — `middleware.py:14-17`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus twenty uppercase-alphanumeric characters — `response.py:12-13`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1-100, negative `offset` -> `ERR_INVALID_REQUEST` (422) — `services/lookup.py:56-75`
- §2.3 — insert — ambiguity — identical `created_at` values are routine under the logical clock and ties break by creation sequence — `db.py:57-58`
- §2.4 — insert — ambiguity — inbound timestamps normalised (non-UTC offset converted, naive taken as UTC, sub-millisecond truncated) and echoed in canonical `...sssZ` form — `clock.py:29-62`, `routes/estate.py:199-200`
- §2.8 tier 3 — insert — ambiguity — on passenger-scoped *reads*, existence resolves before ownership, so a bogus id yields the 404 not `ERR_NOT_ITINERARY_OWNER` — `routes/itineraries.py:68-69`
- §2.8 tier 5 — insert — ambiguity — absent/unparseable/non-object body treated as `{}`, so it fails on the first missing required field; explicit null counts as absent; whole-number fields reject booleans and fractions — `middleware.py:32-33`, `services/validate.py:16-42`
- §2.8 tier 11 — insert — ambiguity — for assortment admission, `ERR_BRAND_SUSPENDED` is reported ahead of `ERR_EXCLUSIVITY_CONFLICT` — `routes/estate.py:297-315`
- §3.1 — insert — ambiguity — `iata_code` carries no uniqueness constraint and no rejection code — `routes/estate.py:25-46`
- §3.2 — insert — ambiguity — a product with no bonded ledger anywhere clears the exclusivity and mix gates vacuously — `routes/estate.py:302-320`
- §3.4 — insert — ambiguity — `connection_country`/`connection_departure_utc` stay optional even when `has_connection` is true, and are forced to null on a direct journey even if supplied — `routes/itineraries.py:29-37`
- §3.4 — insert — ambiguity — scan checks follow the §2.8 ladder, so the barcode comparison is reported last — `routes/itineraries.py:87-94`
- §3.4 — insert — ambiguity — amendment evaluates `ERR_DEPARTURE_PASSED` against the *stored* `departure_utc`; omitted fields keep stored values; the direct-journey coherence rule is not re-applied and lowering `has_connection` does not clear the connection fields — `routes/itineraries.py:111-133`
- §3.4 — revise — ambiguity — reverted sale lines are not versioned by the reset, and `duty_status` stays where it was including `DUTY_LIABLE` — `services/pricing.py:106-119`, `routes/itineraries.py:138-141`

Output: 424 lines, md5 `89f609e4f5245c08fe9d2b7ed2286796`.

### Pass 2 — `routes/bonded.py`, `routes/sales.py`, `services/{pricing,ledger,money,scope,mix}.py`

No re-copy (confirmed; pass 1's 13 edits verified intact by diff). 4 ambiguity-pins, 3 mismatch-revisions.

- §2.9 — insert — ambiguity — a compensating entry inherits the discriminator of the aggregate it reverses, so no movement ever carries `REVERSAL` in `source_ref_type` even though the enum lists it — `services/ledger.py:63-78`, `routes/bonded.py:108`, `routes/sales.py:245`
- §3.3 — insert — ambiguity — the manual-entry insufficiency guard covers `on_hand_qty` only: a negative `AUDIT_ADJUSTMENT` that leaves `reserved_qty` above `on_hand_qty` is accepted, releases no reservation, and drives `available_qty` negative — `routes/bonded.py:75`, `services/ledger.py:22-39`
- §3.5 step 2 — revise — **mismatch** — PRD keyed already-consumed allowance on lines with a *strictly earlier* `created_at`; under the logical clock every line of a basket shares `created_at`, which would zero consumption for every line. Revised to the run's own ascending order (creation-sequence tie-break), each line's full `qty` counting against the category — `services/pricing.py:51-66`
- §3.5 — insert — **mismatch** vs §2.5's blanket cascade-versioning claim — neither waterfall run versions the lines it rewrites; only the basket's `version` moves — `services/pricing.py:43-83`
- §3.6 — revise — ambiguity — the onward-leg seal-window check is skipped not only for a direct journey but also for a connecting itinerary whose `connection_departure_utc` is still null — `routes/sales.py:280-282`
- §3.6 — insert — **mismatch/silence** — forfeiture does not version the lines, and a tampered bag on a basket whose `duty_status` has already left `SUSPENDED` transitions the bag alone, leaving the basket, its lines and its `version` untouched — `routes/sales.py:330-333`, `services/pricing.py:90-103`
- §3.7 — insert — ambiguity — a void preserves every trace of the pricing run (`eligibility_variant`, `effective_destination_country`, `arrival_advisory`, `sealed_bag_required`, `cleared_at`, `picked_up_at`, all per-line figures) unversioned; only sale-level `exempt_amount_cents`/`duty_liability_cents` are zeroed — `routes/sales.py:232-237`

Output: 424 lines, md5 `9e540e958d504d4a8c76c54e949da810`.

### Pass 3 — `routes/{preorders,audits,agreements}.py`, `services/{rent,validate,lookup}.py`

No re-copy (confirmed; 20 prior edits verified intact). 12 ambiguity-pins, 1 mismatch-revision.

- §2.3 — insert — ambiguity — undeclared query parameters are ignored rather than rejected, and a declared filter matches on the exact string rendering of the stored value — `services/lookup.py:78-85`
- §2.8 tier 4 — insert — ambiguity — a body identifier that is absent, null, or not a string is unresolvable and reports that identifier's own 404 rather than a missing-field error — `services/lookup.py:43-53`
- §2.8 tier 5 — revise — ambiguity — tightened "fractional number" to any number written with a decimal point, `2.0` included — `services/validate.py:39-42`
- §3.8 — insert — ambiguity — tier-3 ownership precedes resolution, so an omitted `itinerary_id` yields `ERR_NOT_ITINERARY_OWNER`, not a 422/404 — `routes/preorders.py:29-30`
- §3.8 — insert — ambiguity — `posted_by_user_id` on the hold is the Passenger's `X-User-ID` (their itinerary id); the cancellation release entry carries the same stamping plus `source_ref_type` `PRE_ORDER` / `source_ref_id` of the reservation — `routes/preorders.py:84,152`
- §3.8 — revise — **mismatch** — PRD listed the collection-window check third; impl reaches it last, after `ERR_AGREEMENT_NOT_ACTIVE` and `ERR_PRODUCT_NOT_LISTED` (tier 12 vs tier 8) — `routes/preorders.py:111-128`
- §3.8 — insert — ambiguity — the basket created on conversion initialises every remaining field exactly as a §3.5 walk-up basket — `routes/preorders.py:129`, `routes/sales.py:35-56`
- §3.9 — insert — ambiguity — `period_code` is four digits + hyphen + month `01`-`12`; `terminal_id` and `stock_item_id` are not cross-checked; no uniqueness per item/period — `routes/audits.py:26-28`
- §3.9 — insert — ambiguity — `info_request_note` is required and may not be empty — `routes/audits.py:88`
- §3.9 — insert — ambiguity — the release entries on an assessed close carry `source_ref_type` `PRE_ORDER`, `source_ref_id` of the released reservation, and the closing auditor as `posted_by_user_id` — `routes/audits.py:152-153`
- §3.10 — insert — ambiguity — `rent_pct_bps` must lie between 0 and 10000 inclusive — `routes/agreements.py:28`
- §3.10 — insert — ambiguity — a sub-one-day period leaves `period_days` and `elapsed_days` at 0 and `prorated_minimum_guarantee_cents` equal to the full guarantee (no division) — `services/rent.py:42-51`
- §3.10 — insert — ambiguity — the projection read also echoes `percentage_rent_cents`, and applies to an agreement in any standing with no state precondition — `services/rent.py:52-60`, `routes/agreements.py:68-72`

Closing sanity check (pass 3, re-verified by the orchestrator): `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — md5 `f6b24623d98b840996435279aec24196` vs `7a4dbc279757f1a9cabdf2de7d6d29e8`, 62 changed lines, 90036 -> 98540 bytes. `tail` ends on the final row of the §5 error-code table (`ERR_VOID_AFTER_PERIOD_CLOSE | 409`), so no truncation.

Pipeline complete. `workspace/PRD_COMPLETED.md` written; the eight `results.{1..8}.json` from the final clean sweep (108/108 each) are retained in `workspace/implementation/`. `__pycache__` directories removed from `implementation/`, `test_helpers/` and `test_suite/`.
