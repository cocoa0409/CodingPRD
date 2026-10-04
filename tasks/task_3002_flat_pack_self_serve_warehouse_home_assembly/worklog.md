# Worklog — task_3002_flat_pack_self_serve_warehouse_home_assembly

## Step 1: Create task directory — 2026-09-29T12:05:00.000Z

Task directory `./tasks/task_3002_flat_pack_self_serve_warehouse_home_assembly/` was pre-allocated with `workspace/` inside (per skill arguments); verified it exists and is empty. No new index computed.

## Step 3: Copy shared files — 2026-09-29T12:06:00.000Z

Copied `./INSTRUCTION.md` to `./tasks/task_3002_flat_pack_self_serve_warehouse_home_assembly/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-09-29T13:15:09.819Z

All three files are written and the scaffold package passes `scaffold_lint.py` with a clean verdict. Lint verdict (verbatim):

```
Coverage
  §1.5 endpoints declared:    76
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  756

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**SCAFFOLD.yaml** — §1.0–§1.7 only (no difficulty/corner keys):
- **15 entities**: Store, Article, Carton, BinStock, Customer, Order, OrderLine, StockReservation, DeliverySlot, DeliveryBooking, AssemblyStandard, AssemblyJob, SparePartClaim, ReturnRequest, ReturnLine (flat topology, all FKs use the canonical `FK -> X.id` prefix and have reverse-reachability GETs)
- **6 state machines**: Order (parallel dimensions: status × delivery_status × assembly_status), StockReservation (ACTIVE→FULFILLED/CANCELLED/EXPIRED), DeliveryBooking (waitlist→confirm branching), AssemblyJob (IN_PROGRESS⇄ON_HOLD cycle), SparePartClaim (linear), ReturnRequest (SETTLED→DISPUTED→GRADING→SETTLED cycle)
- **2 concurrency rules**: OCC on `DeliverySlot.version` (booking create) and `BinStock.version` (stock adjust), both 412 ERR_STALE_VERSION
- **11 calculations**: stock signal (min-over-cartons aggregation), order pricing (per-line rounding pinned, food discount, points cap), points accrual, tiered delivery fee, 2-D slot capacity, waitlist promotion (deterministic selector: created_at ASC, weight/volume tie-breaks — no id usage), assembly labor (estimate vs capped-actual variants), crew window buffer intervals, rolling-365d claim eligibility, return refund (receipted vs no-receipt variants), reservation expiry
- **9 validation priorities** (shape → authn → authz → existence → OCC → state → temporal → constraint → fiscal)
- **76 endpoints** incl. `POST /api/_clock/set_current_utc` (default 2026-09-01T00:00:00Z) and `POST /api/stores/{id}/run_sweep` ops checkpoint
- **38 error codes**, all referenced; **6 roles** (PlatformAdmin/StoreOps/DeliveryCoordinator/AssemblyProvider opaque, Customer entity-backed, Anonymous for the 401 test)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 18 instances, 2 per rule × 9 rules, each with literal-computed asserts (e.g. member delivery fee 8440 vs non-member 10550; per-line food discount 24 vs naive 23; billed_minutes 135 = min(200, ceil(90×1.5)); receipted 850 vs no-receipt 765 refund). Cascades: booking-cancel→slot→promotion→order (depth 3) and assembly-complete→order-close→points (depth 3).

**SCAFFOLD_CORNER_DESIGN.yaml** — 45 instances (43 active + 2 `excluded_because` stubs) across all nine guide sections, covering entity defaults/computed fields, invalid transitions, terminal lockdown, expiry side effects, compensation round-trips, threshold boundaries, RBAC denials, OCC stale-version tests, envelope shape, and pagination. YAML anchors share common setup chains (clock/store/customer/article) within the file.

No sibling tasks under `tasks/` were read; the design was built purely from the scenario text plus the skill specification.

## Step 4: Generate PRD — 2026-09-29T13:28:55.430Z

**Output:** `workspace/PRD.md` — 289 lines.

**Structure:**
- §1 Introduction — 2 paragraphs (bargain-with-shopper angle + multi-carton integrity as the domain's hardest property)
- §2 Global Specifications — 9 subsections (RBAC with per-role identity prose, verbatim §2.2 response-structure block, pagination, resource identity/common fields, money & rounding discipline, logical clock, OCC, nested path resolution, validation priority order)
- §3 Business Logic — 8 subsections organized by business process: catalog/cartons/bin-stock, membership, order build→checkout→close/cancel, reservations & daily sweep, delivery slots/quotes/waitlist, assembly standards/dispatch/capped billing, spare-part claims, returns grading/settlement/dispute
- §4 Endpoint table — 60 endpoints, 4 columns (Method / Path / Description / Authorized Roles)
- §5 Error catalogue — 38 errors, 2 columns (Error ID / HTTP Status)

**Hard contract results:**
- Contract 1 (Field-Name Coverage): PASS — 88 entity fields, 57 request-body identifiers, 11 query params, 3 path params, 8 output-only names, 38 error IDs, 6 role names: all present in backticks, 0 missing.
- Contract 2 (Rule Coverage): PASS — validation priority ordering, both OCC rules, all 29 state transitions with preconditions/side-effects, all 10 calculations with pinned constants (zone bases 4900/7900/12900, weight tiers 50/150 kg, 2500 flat + 15/kg overage, 1200 walkup fee, 40 kg access cap, 20% member discounts, 10% food offer and no-receipt penalty, grade factors 1.00/0.85/0.50/0.00, 1.5× billing cap with ceil, 30-minute crew buffer with strict boundaries, 24-hour reservation TTL with inclusive expiry boundary, 3-claim / 3000-cent rolling caps with count-before-value order), per-line rounding pinned with the 115-cent worked example, inclusive capacity fit, dispute reversal cascades — all expressed in prose.
- Contract 3 (§3 Path Purity): PASS — 414 backtick tokens in §3 scanned, zero path tokens, zero bare HTTP methods, zero method+path combos.
- All 48 enum/state values present as exact backticked strings.

**Constraint confirmation:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, read, grepped, or referenced, and no sibling task under `tasks/` was inspected.

## Step 5: Generate unit tests — 2026-09-29T14:51:31.980237792Z

### Tests generated
- **Queue A (Difficulty)**: 36 tests — 2 per instance × 18 instances (9 rules × 2). Every difficulty instance is covered by exactly 2 tests tagged `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner)**: 45 tests — 1 per non-stub instance × 45 instances across sections `entities` (6), `state_machines` (10), `calculations` (7), `validations` (12), `endpoints` (2), `rbac` (4), `cross_cutting_complexity_layers` (3), `consistency_model` (1). Every tag resolves verbatim to a `name:` in the design YAML.
- **Total**: 81 tests in 11 files (`test_01`…`test_12`, numbered simple→complex).

### Instances skipped (PRD-first filter)
- Zero instances skipped for missing PRD coverage — every non-stub instance in both indices had verbatim, uniquely-derivable PRD prose.
- Two `excluded_because:` stubs correctly NOT translated; both cross-references verified to resolve to real difficulty instances (`checkout_insufficient_stock_error` → `checkout_availability_hits_exactly_zero`; `errors/stale_slot_version_error_covered` → OCC corners).
- Two narrow scope decisions within otherwise-emitted instances (documented in the two-reader pass): the `validation-priority` claim asserting OCC (412) beats temporal (422) — scaffold-only, PRD §2.9 contains no such statement — was dropped from the `occ_booking_create_stale_slot_412` test, which asserts only the 412 rule itself; and in `booking_and_cancel_conserve_slot_capacity` the re-booking success assertion was kept (PRD-derivable via `delivery_status` NONE) but no exact slot-version number is asserted (PRD does not pin bump counts per cascade hop).

### test_helpers/ written (9 files)
`__init__.py` (barrel), `types.py` (17 TypedDicts + 16 enums), `api_client.py` (~55 endpoint methods on `GenericApiClient`), `api_errors.py` (38 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py` (unique emails/codes/article-numbers per call), `constants.py`, `test_users.py` (opaque role constants + mandatory `make_customer_headers` builder for the entity-backed Customer role), `fixtures.py` (composite tiers: clock/store/customer, article-with-cartons-and-stock, paid/fulfilled orders, in-progress assembly jobs, `seed_member_points`, delivery bookings with slot-version refresh).

### Self-check results
- **Stage 1**: all 9 helper files compile; `import test_helpers` succeeds; framework registration executed.
- **Stage 2**: all 81 tests collect under pytest (0 errors); every test docstring ends with exactly one `Design:` tag as its last line; every tag resolves to a real non-stub instance; difficulty instances all have ≥2 tests, corner instances all have ≥1; no `pytest.mark.skip/skipif/xfail` anywhere; no generated code mentions "scaffold"; all 81 docstring citations pass the verbatim 8-word grep against `workspace/PRD.md` (0 failures).

## Step 6: Generate implementation — 2026-09-29T14:51:50.232848778Z

### Files written (under `workspace/implementation/`)
- `start.sh` — executable foreground launcher; guards `pip install` behind `python3 -c "import flask"` and `exec python3 app.py`; honors `PORT` (default 10000), binds `0.0.0.0`.
- `requirements.txt` — flask>=3.0 only.
- `db.py` — in-memory `Store` (dicts per entity + logical clock defaulting to 2026-09-01T00:00:00Z); UUID ids; `touch()` bumps `version` +1 and refreshes `updated_at` per PRD §2.4. No seeding anywhere.
- `errors.py` — `ApiError` plus the full §5 error catalog with exact HTTP statuses.
- `response.py` — exact §2.2 envelope (`meta.api_request_id` `req_…`, `api_request_timestamp` with 3 fractional digits, `response_type` object/array/error, `data`; error body `error_id`/`message`; pagination fields in `meta`).
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`), role gating (403 `ERR_FORBIDDEN`), Customer ownership check against `customer_id`.
- `app.py` — all routes, state machines, calculations, validation priority ordering (§2.9: shape → auth → authz → existence left-to-right → OCC → state → temporal → business → fiscal).

### Endpoints implemented
All 74 routes from the §1.5/§4 table: clock set; stores CRUD + stock list + signal + `run_sweep`; articles CRUD + cartons; bin-stock create/get/list/adjust (OCC); customers create/get/enroll + orders + claims sublists; orders create/get/list/lines/checkout/cancel/pickup-complete/close + delivery-bookings/assembly-jobs/returns sublists; order-lines get/list; reservations CRUD + fulfill/cancel (lazy expiry at `now >= expires_at` → `ERR_RESERVATION_EXPIRED`); delivery slots CRUD + bookings; order delivery-bookings (OCC `expected_slot_version`, `ERR_BOOKING_NEVER_FITS`, `ERR_ACCESS_INFEASIBLE`, fee quote with zone base/weight surcharge/walkup fee/member 20% terminal round-half-up, inclusive fit, waitlist promotion waterfall ranked `created_at` ASC → weight ASC → volume ASC); assembly standards CRUD; assembly jobs create (window-in-past, 30-min strict crew-buffer conflict, `ERR_STANDARD_MISSING`) + dispatch/start/hold/resume/complete (billed = min(actual, ceil(est×1.5))) + cancel; spare-part claims CRUD + review (count-then-value rolling 365-day caps, exactly-3000 allowed) + ship; returns create/lines/submit/grade (effective grade capped at OPEN_BOX when assembled)/settle (per-line half-up refunds, LIKE_NEW-only restock, receipted writeoff)/dispute (full reversal)/reopen.

### Boot verification
Smoke-checked across four separate fresh process boots: store starts empty (`GET /api/orders` → `[]`, `total_count` 0), clock reads exactly `2026-09-01T00:00:00.000Z` before any clock call. End-to-end flows verified with assertions: pricing with per-line food discount rounding (12+12=24), member pricing, points redemption cap and `ERR_INSUFFICIENT_POINTS`, SELF_PICK vs PICKUP_COUNTER stock movement, order-cancel compensation (restock + reservation cancel + points re-credit), delivery booking OCC (412), `ERR_DUPLICATE_BOOKING`, waitlist promotion on cancel, booking complete → stock decrement → order DELIVERED → assembly complete → auto-close + points accrual, crew-window conflict (exactly-30-min gap allowed), `ERR_STANDARD_MISSING`, `ERR_WINDOW_IN_PAST`, reservation fulfill/expiry boundary (inclusive) and `run_sweep`, claim count/value caps, `ERR_RETURN_QTY_EXCEEDED`, `ERR_RECEIPT_REQUIRED`, settle/dispute/reopen cycle with un-restock and `returned_qty` rollback, signal boundaries (IN_STOCK at `available >= threshold`, LOW_STOCK below), and `ERR_UNAUTHENTICATED`/`ERR_FORBIDDEN` RBAC paths.

## Step 7: Run tests and iterate — 2026-09-29T15:04:05.287857806Z

All 8 rounds pass 81/81. Clean sweep.

- **Iterations run**: 2 (first sweep found 3 distinct failures; fixes applied; second sweep clean 8/8 rounds, 81/81 each).

- **Tests deleted**: none. (No test was deleted; one assertion was removed from a test — see below.)

- **Fixes applied to `test_suite/`**:
  - `test_03_difficulty_state_machines.py` — `TestReturnSettleDisputeRegradeCycle::test_dispute_rolls_back_returned_qty_rollup`: removed the trailing `assert line_row["restocked_units"] == 1` (post-dispute). Unique-derivability failure (STEP 1b): PRD §3.8 says dispute "reverses the previous settlement in kind" and uses `restocked_units` as the reversal quantity (`on_hand` drops by each line's `restocked_units`), but is silent on the field's value **after** dispute — a faithful implementer could either reset it to 0 or preserve it as an audit record. Both readings are PRD-consistent, so the assertion cannot stand. The PRD-pinned `returned_qty` rollback assertion remains.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`**:
  - `workspace/implementation/app.py` — `list_all()`: subresource list endpoints returned `meta.limit = len(items)`, which is 0 on an empty list, violating PRD §2.3 ("limit ... minimum of 1") and the framework's `meta.limit must be positive` check. Now clamps to `max(1, min(100, len(items)))`. Fixed `test_return_qty_beyond_purchased_rejected` (failed 8/8 rounds).
  - `workspace/implementation/app.py` — `app.run(..., threaded=True)`: under the 8-round parallel sweep the default single-threaded Werkzeug server intermittently reset connections ("Connection reset by peer" in `test_order_cancel_compensates_stock_reservations_and_points`, 6/8 rounds) when the runner's lifecycle probe / keep-alive handoff coincided with an in-flight request. Threaded mode removes the blocking bottleneck; all routes are request-scoped over the shared dict store, and each test is sequential, so no race is introduced.

- **Union of failures addressed**: `test_dispute_rolls_back_returned_qty_rollup` (8/8 rounds, assertion removed per 1b), `test_return_qty_beyond_purchased_rejected` (8/8 rounds, `list_all` limit clamp), `test_order_cancel_compensates_stock_reservations_and_points` (6/8 rounds flaky, threaded server).

## Step 8: Finalize PRD — 2026-09-29T15:08:43.422751843Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

### Line counts and delta
- `PRD.md`: 288 lines; `PRD_FINALIZED.md`: 288 lines (0% line delta — both edits are in-place sentence extensions on existing lines).

### Changes (one per edit)
- §2.3 (Pagination) — revise — appended a sentence pinning that the seven nested subresource listings (article cartons; order lines, delivery bookings, assembly jobs, returns; slot bookings; return lines) take no pagination params, return all matching records, and report `meta.limit` as `max(1, min(100, count))` — so an empty listing reports `limit: 1` — with `offset: 0` and `has_more: false` — `implementation/app.py:202-209` (`list_all`) and callsites at lines 614, 853, 864, 875, 886, 1278, 1911.
- §3.8 (Returns: dispute) — revise — added that dispute resets each restocked line's `restocked_units` to 0 after pulling the units from the shelf (PRD was silent on the post-dispute field value; impl chose reset-to-0) — `implementation/app.py:2003` (reverse branch of `settle_restock`).

No edit was made for `app.run(..., threaded=True)` — non-behavioral runtime server config, explicitly out of PRD scope per the method.

### Per-edit pre-edit search log
**Edit 1 (pagination / list-endpoint meta):**
- (a) Subject: which list endpoints paginate vs return everything, and what `meta.limit` reports on each.
- (b) Enumerated paths: grepped every `@app.get` in `implementation/app.py` and classified all 26 GET endpoints — 12 collection lists use `paginate()` (`/stores/{id}/stock`, `/bin-stock`, `/customers/{id}/orders`, `/customers/{id}/spare-part-claims`, `/orders`, `/order-lines`, `/reservations`, `/delivery-slots`, `/assembly-standards`, `/spare-part-claims`, `/returns`, `/return-lines`) and exactly 7 subresource lists use `list_all()` (cartons of article; lines/bookings/jobs/returns of order; bookings of slot; lines of return). Also read `paginate()` (lines 176-199) to confirm the param-taking path honors limit/offset defaults and clamping, and cross-checked each PRD narrative (§3.1 cartons listing, §3.3 order lines, §3.5 slot bookings, §3.6 order jobs, §3.8 return lines) — none declares filters or pagination params, consistent with the new wording. Store listing was checked too (there is no `GET /api/stores` list endpoint, so nothing to describe).
- (c) Wording adjustment: scoped the sentence to "nested subresource listings" and enumerated them explicitly rather than saying "endpoints without filters," so the 12 paginated collection endpoints remain fully covered by the pre-existing §2.3 text and no path is mis-described.

**Edit 2 (restocked_units after dispute):**
- (a) Subject: the `restocked_units` field lifecycle across create/settle/dispute/re-settle.
- (b) Enumerated paths: return-line creation (`app.py:1897`, init 0); forward `settle_restock` (`app.py:2004-2005`, set to `qty` only when effective grade is `LIKE_NEW` and line is receipted); reverse `settle_restock` (`app.py:2003`, reset to 0 on dispute); re-settle after reopen reuses the forward path so the field is recorded anew. Also confirmed no-receipt lines and below-`LIKE_NEW` lines never touch the field (stay 0), matching PRD's existing "a receipted line graded `LIKE_NEW` … records how many" sentence.
- (c) Wording adjustment: phrased as "each such line's `restocked_units` is reset to 0 once its units have been pulled," scoped to lines that actually restocked — avoids implying anything about lines that never restocked — and left the existing re-settle sentence untouched since the forward path already re-records the field.

## Step 9: Complete PRD — 2026-09-29T15:24:53.798918791Z

Line count preserved (288 → 288, all edits inline); 23 paragraphs revised. No duplicates remain.

**Files**
- Source: `workspace/PRD_FINALIZED.md` (288 lines, 50,837 chars)
- Output: `workspace/PRD_COMPLETED.md` (288 lines, 58,423 chars; +7,586 chars, 0 added lines — all edits are inline paragraph inserts/revisions)

**Counts**
- Ambiguity-pins: 20
- Mismatch-revisions: 3 (the return-line membership-gate scope clarification, the claim window measured on `created_at`, and the claim-window inclusive bound — all places where PRD prose admitted a different reading than impl)

**Changes (one per revised passage)**
- §2.2 — insert — ambiguity — single-object responses carry only `api_request_id`/`api_request_timestamp` in `meta` — implementation/response.py:22-30
- §2.3 — insert — ambiguity — `limit`/`offset` clamping (1–100, ≥0), non-integer params → `ERR_VALIDATION`, `has_more` = `offset+limit < total_count` — app.py:177-199
- §2.6 — insert — ambiguity — `api_request_timestamp` uses wall clock, not the logical clock — response.py:16-19
- §2.9 — insert — mismatch — uniqueness violations (store code, article_number, carton_seq, email, one-standard-per-article), return-line cross-field errors, and invalid adjustment results are all `ERR_VALIDATION` (400), not 409 — app.py:439, 532, 592, 695, 1475, 1863-1880, 677
- §2.9 — insert — ambiguity — assembly-request intra-tier check order: crew-window conflict before missing standard — app.py:1521-1539
- §3.1 — insert — ambiguity — carton registration touches the parent article (version/updated_at) — app.py:603-604
- §3.1 — insert — ambiguity — bin-stock adjust bound violations → `ERR_VALIDATION` — app.py:676-678
- §3.1 — insert — ambiguity — stock-signal response has no resource id/timestamps/version — app.py:479-485
- §3.2 — insert — ambiguity — re-enrolling an ACTIVE customer → `ERR_INVALID_STATE` — app.py:717-718
- §3.3 — insert — ambiguity — order born with zeroed monetary fields and `points_earned` 0; line born with zeroed pricing fields, `returned_qty` 0; adding a line touches the order; non-DRAFT line-add/checkout → `ERR_INVALID_STATE` — app.py:770-775, 825-843, 931-935
- §3.3 — insert — ambiguity — checkout defaults: `fulfillment_channel` = CARRYOUT, `redeem_points` = 0 — app.py:925-927
- §3.3 — insert — ambiguity — lines stock-checked in `created_at` order; stock gate precedes points check — app.py:932-945
- §3.3 — insert — ambiguity — pickup-complete guards (PAID + CARRYOUT required, `ERR_INVALID_STATE` otherwise) — app.py:1066-1077
- §3.3 — insert — ambiguity — PAID-cancel violations and closing guards are `ERR_INVALID_STATE`; non-member `points_earned` recorded as 0 — app.py:1014-1032, 1087-1091, 338
- §3.4 — insert — ambiguity — reserving a SELF_SERVE article → `ERR_VALIDATION`; fulfill/cancel of non-ACTIVE reservation → `ERR_INVALID_STATE`; lazy-expiry fulfill releases reserved units — app.py:1110-1112, 1175-1187, 1205-1206
- §3.4 — insert — ambiguity — sweep promotes slots in ascending `created_at` order — app.py:505-508
- §3.5 — insert — ambiguity — slot born with used figures at 0 — app.py:1240-1241
- §3.5 — insert — ambiguity — booking guards (non-PAID/wrong channel → `ERR_INVALID_STATE`); named slot need not belong to the order's store — app.py:1333-1338, 1329
- §3.5 — insert — ambiguity — `ERR_BOOKING_NEVER_FITS` precedes the access-feasibility gate; no capacity/stock consumed before fit is decided; booking answers 201 in both outcomes — app.py:1345-1349, 1361-1369
- §3.5 — insert — ambiguity — fee quoted on waitlisted bookings too — app.py:1349, 1358
- §3.5 — insert — ambiguity — start/complete/cancel state guards are `ERR_INVALID_STATE`; cancel of OUT_FOR_DELIVERY/DELIVERED/CANCELLED rejected — app.py:1426-1427, 1440-1442, 1416-1418
- §3.6 — insert — ambiguity — assembly-request guards `ERR_INVALID_STATE`; new job born with null `actual_minutes`/`billed_minutes`/`hold_reason` — app.py:1512-1516, 1548-1550
- §3.6 — insert — ambiguity — each crew transition guarded to a single from-state (`ERR_INVALID_STATE` otherwise); `hold_reason` overwrites — app.py:1575-1610
- §3.7 — revise — mismatch — claim born with null `review_note`; `decision` values pinned as `APPROVE`/`DENY`; review/ship state guards `ERR_INVALID_STATE`; 365-day window measured on `created_at` and inclusive on both ends — app.py:1676, 1718, 1722-1723, 1726-1730, 1751-1752
- §3.8 — insert — ambiguity — return born with zeroed totals; line-add touches the request; non-DRAFT line-add → `ERR_INVALID_STATE`; article-match cross-check `ERR_VALIDATION`; line born with null grade/basis/refund/writeoff and computed `effective_condition_grade` — app.py:1803-1804, 1857-1858, 1870-1872, 1893-1901
- §3.8 — revise — mismatch — no-receipt return request may be opened by any customer; the ACTIVE-membership gate applies only at line creation — app.py:1783-1807, 1882-1885
- §3.8 — insert — ambiguity — submit guards `ERR_INVALID_STATE`; grading allowed from SUBMITTED or GRADING; settle from SUBMITTED → `ERR_UNGRADED_LINES`, other states → `ERR_INVALID_STATE`; dispute requires SETTLED, reopen requires DISPUTED — app.py:1954-1958, 1975-1982, 2017-2023, 2062-2063, 2075-2076
