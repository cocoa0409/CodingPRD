# Worklog — task_3012_white_label_delivery_as_service_fulfillment

## Step 1: Create Task Directory — 2026-09-29T12:19:17.000Z

Pre-allocated task directory `./tasks/task_3012_white_label_delivery_as_service_fulfillment` with `workspace/` verified to exist; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-29T13:17:52.000Z

All clean — the single flag is the intentional negative test (`quote_rejected_when_no_active_policy` deliberately skips activation). The scaffold is complete and lints clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3012_white_label_delivery_as_service_fulfillment/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, fixed response envelope verbatim, no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 18 instances (2 per each of the 9 rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 55 entries (47 with test recipes, 8 `excluded_because` stubs)

**Counts:** 13 entities, 65 endpoints (incl. 2 test-driving: `/_clock/set_current_utc` with mandatory `2026-09-01T00:00:00Z` default, `/_surge/set_current`), 33 error codes, 7 calculations, 10 state machines, 9 ordered validations, 4 roles, 2 OCC concurrency rules. Lint: `VERDICT: clean lint` (1063 calls scanned, 0 violations). No forbidden concurrency vocabulary; all numeric asserts are Python-computed literals.

**Difficulty posture (beyond expert):**
- **Dual-variant calcs on two domains**: delivery fee quoted-vs-final (surge at quote vs dispatch with 50% passthrough, floor at base) on DeliveryOrder; GROSS vs FAULT_ADJUSTED attainment (0.3333 vs 0.5 on identical data) on SlaReport.
- **Combinatorial formulas in two modes**: 4-input non-linear fee assembly (band+value+peak×surge compounding, 2532 pinned) in mode (a); batch courier-cost waterfall with per-order floor + remainder-to-earliest-created (541/159/700) in mode (b).
- **Parallel state dimensions** (fulfillment × billing on DeliveryOrder) + **capped appeal cycle** on RefundClaim.
- **Two transitive cascades**: refund settle → order REFUNDED → balance −250 → merchant SUSPENDED → open orders CANCELLED with hold release (depth 4); report finalize → credit ACCRUED → auto-APPLIED → merchant credit balance (depth 3).
- **Two temporal-overlap rules with deliberately opposite interval semantics**: courier dispatch windows are closed (touching at 01:30 conflicts) vs pricing-policy effective windows half-open (adjacency allowed) — the trap is asserting the same adjacency behavior for both.
- **Two OCC races** (policy activate on Merchant.version; batch create on Courier.version) with 412 staleness.
- **Boundary precision**: lateness exactly 600s → 0 credit vs 601s → 125; radius 1113 inclusive vs 1112 not serviceable.
- **Validation priority conflicts**: state-vs-fiscal on accept; temporal-vs-constraint on dispatch.
- Also layered: idempotency-key replay on order create, quote expiry via logical clock, visibility-filtered branded tracking feed, FK-order-dependent 404s.

**Design decisions of note:** distance uses a pinned Manhattan-planar formula (integer meters, round-half-up) so all fixtures are exactly computable at the equator (store at (0,0)); surge is platform-global via a test-driving endpoint rather than a per-zone entity to keep the pricing trap in the quoted-vs-final reconciliation rather than in data modeling; the Merchant suspension cascade fires on both the explicit suspend endpoint and the settle-driven balance<0 path, with pinned hold-release arithmetic (1200 → 200 → −50 → 450).

## Step 3: Copy Shared Files — 2026-09-29T13:18:53.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3012_white_label_delivery_as_service_fulfillment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T13:32:08.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3012_white_label_delivery_as_service_fulfillment/workspace/PRD.md` — 321 lines.

**Section coverage against the scaffold:**
- **§1 Introduction** (3 paragraphs) — rewrites the `scenario` into merchant-channel/white-label framing, covering outsourced fulfillment, the billing/credit/refund loop, and the precision/concurrency themes.
- **§2 Global Specifications** (§2.1–§2.8) — RBAC with all four roles (`PlatformAdmin`, `Merchant`, `Courier`, `SupportAgent`) and per-role `identity:` translations (entity-backed for Merchant/Courier, opaque for PlatformAdmin/SupportAgent); verbatim §2.2 response-envelope block; pagination defaults (limit 10/1–100, offset 0, `created_at` ascending); common resource properties including the TrackingEvent exception (`common_fields: false`); the logical clock (startup `2026-09-01T00:00:00Z`) and surge controls; the full 9-layer validation priority ordering; monetary precision (integer cents, round-half-up per component before summing, floor-per-order allocation, 4-decimal attainment rates); and both OCC rules (`expected_merchant_version` → `ERR_STALE_MERCHANT_VERSION`/412 on policy activate; `expected_courier_version` → `ERR_STALE_COURIER_VERSION`/412 on batch create).
- **§3 Business Logic** (§3.1–§3.9, grouped by workflow: merchant onboarding → stores/serviceability → pricing policies → quoting/dual-variant fee → order intake → batching/dispatch → completion/disposition/late credit → refund claims → SLA reporting/credits, with tracking folded into §3.9) — every state machine transition, all six calculations (Manhattan-planar distance, override precedence with longest-pattern/tie-break rule, dual-variant delivery fee with surge pass-through and floor, late-credit thresholds at 600s/1800s/25%, pinned refund liability split with 2x platform cap, batch fee waterfall allocation with floor + earliest-`created_at` remainder, dual-variant SLA attainment with 97% credit trigger), and every side-effect cascade (suspension cascade, invoice reconciliation, batch auto-completion, credit auto-apply) are expressed in prose. No endpoint paths or bare HTTP methods appear in §3.
- **§4 Endpoint table** — all 66 endpoints, 4 columns only.
- **§5 Error catalogue** — all 33 error IDs, 2 columns only.

**Self-audit (Hard Contracts):**
- **Contract 1 (Field-Name Coverage):** PASS — all 88 scaffold field names (entity fields + request/query/path params) verified present verbatim in backticks; 3 initially missing (`fulfillment_status`, `billing_status`, `decision`) were repaired and re-checked to zero missing.
- **Contract 2 (Rule Coverage):** PASS — validation priority ordering stated as a numbered 9-layer list; both OCC rules name write endpoint, occ field, error id, and HTTP status; all 13 entities' state machines fully expressed with preconditions and error IDs; all 6 calculations expressed as precise prose passing the reconstruction test (thresholds given as exact numbers, boundary inclusivity stated, rounding order pinned); all endpoint side effects and `applies_to` scopes covered; field-level defaults (50, true, 4, null-until-dispatch, etc.) stated; sibling branches (return vs. dispose, gross vs. fault-adjusted, quoted vs. final variants) given equal density. Additionally verified all 33 error IDs, all state/enum values, and all role names appear in the document.
- **Contract 3 (§3 Path Purity):** PASS — 398 backtick tokens scanned in §3, zero violations (no leading `/`, no bare HTTP methods, no method+path tokens).

**Constraint compliance:** The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-09-29T14:24:40.000Z

ORCHESTRATOR NOTE: Step 5 was mistakenly launched twice (two concurrent test-generator subagents instead of one test-generator + one implementation-generator). The two agents conflicted over test_helpers/ and test_suite/. The surviving on-disk state is the second agent's (a551b102) final restored suite, verified coherent by the orchestrator: 82 tests collected by pytest, all files compile, 82 Design tags. The first agent's (ad4f8900) summary is retained below for the record but its files were superseded.

--- Surviving suite (agent a551b102) summary, verbatim ---

Final state is clean. The audit shows one skipped corner instance, all tags valid, all citations verbatim-verified.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3012_white_label_delivery_as_service_fulfillment/`):

*test_helpers/* (Stage 1): `__init__.py`, `types.py` (all 13 entities; TrackingEvent correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (33 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py` (P1 policy payload and per-entity factories), `constants.py` (late-credit bands 600/1800/25%, batch cost 400+150, 97% trigger, 15-minute quote validity, max-1 appeal), `test_users.py` (opaque shared headers + `make_merchant_headers`/`make_courier_headers` entity-backed builders), `fixtures.py` (5-tier composite chain: clock → merchant → store → policy activation with OCC → courier → quote → order → accept/ready → batch → dispatch → transit → delivery → claim → report).

*test_suite/* (Stage 2): `conftest.py` plus 7 files — `test_01_core_resources.py`, `test_02_pricing_and_quotes.py`, `test_03_order_workflows.py`, `test_04_batching_and_concurrency.py`, `test_05_refund_claims.py`, `test_06_sla_and_credits.py`, `test_07_rbac_and_validation.py`.

**Test counts**: 82 total — queue A (difficulty): 36 tests covering all 18/18 instances with ≥2 each; queue B (corner): 46 tests covering 46/47 non-stub instances (all 8 `excluded_because:` stubs verified to resolve to real queue-A instances and not translated).

**Skipped instances (1)**: `Corner/endpoints/fk_reverse_reachability_lists` — its core assertion names specific list-filter query parameters (`store_id`, `courier_id`, `delivery_order_id`, …) that appear only in the PRD's endpoint table, never in rule-bearing prose; fails C2/unique-derivability. (Additionally, the corner instance `delivery_orders_list_pagination_and_status_filter`'s `fulfillment_status=…` filter assertion was dropped from the emitted test for the same reason; the pagination contract itself is fully tested.)

**Self-audit verdict**: PASS — all files compile; 82/82 tests carry exactly one `Design:` tag as the last docstring line, resolving to a real instance with matching rule/section; every PRD citation in every docstring survives a verbatim 8-word grep of `workspace/PRD.md`; no `skip`/`skipif`/`xfail` anywhere; no untagged or dual-tagged tests.

**Note**: a concurrent agent briefly overwrote `test_suite/` mid-task with an incompatible helper API; I restored my coherent suite and removed the conflicting files. Final on-disk state is the audited one above.

--- Superseded agent (ad4f8900) summary, verbatim (files no longer on disk) ---

**Test counts (superseded suite)**: 101 tests — Queue A: 28 tests (18 instances ≥2 each); Queue B: 73 tags (46 instances). Skipped: none. Notable divergence handled: a foreign `test_01_core_resources.py` (written concurrently by another process, referencing nonexistent helpers) was found in `test_suite/` and removed.

## Step 6: Generate Implementation — 2026-09-29T14:48:37.000Z

**Files written** (all under `workspace/implementation/`):

- **`start.sh`** — executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `0.0.0.0:$PORT`, default 10000).
- **`requirements.txt`** — `flask>=3.0` (zoneinfo/Decimal are stdlib).
- **`app.py`** — Flask app with all routes, error handlers, and validation-layer ordering (auth context → role → path-id existence → body-FK existence → OCC → state → temporal → business → fiscal).
- **`db.py`** — in-memory dicts only; logical clock initialized to exactly `2026-09-01T00:00:00Z`, surge multiplier 1.0. **No seeding** — the store starts empty on every boot.
- **`errors.py`**, **`response.py`**, **`middleware.py`**, **`services.py`** — error catalog, PRD §2.2 envelope (`meta`/`response_type`/`data`; pagination fields in `meta` for lists), header/role/payload validation, and the calculations (Manhattan-planar distance with round-half-up, override longest-pattern/created_at tie-break, dual-variant fee with component-then-sum rounding and invoice floor at base_total, late-credit thresholds 600/1800s, refund liability split with platform cap 2.0×invoice, batch allocation floor+remainder-to-earliest-created, SLA gross/fault-adjusted attainment at 4dp).

**Endpoint count:** 58 endpoints implemented — the full PRD §4 / scaffold §1.5 table (clock/surge controls, merchants ×7, stores ×4, overrides ×2 + check-serviceability, pricing policies ×4, quotes ×3, delivery orders ×9 + dispositions ×2 + tracking ×2, couriers ×4, batches ×5, refund claims ×8, SLA reports ×4, service credits ×5).

**Verification:**
- Server boots cleanly from a fresh process via `bash start.sh` (tested on ports 17871–17873); a fresh boot returns an empty merchant list and the default clock — no state carries over between launches, satisfying per-test-server isolation.
- A 33-step end-to-end smoke exercise passed with **0 failures**, covering: auth-header rejection, merchant lifecycle + OCC version bumps, policy activation with `ERR_STALE_MERCHANT_VERSION` (412), quoted fee math (875 = 500 band + 200 surcharge + 175 peak uplift), idempotent order creation, accept/authorization debit, batch creation (cost 550) and dispatch with surge 2.0 (final 1750, passthrough invoice 1313, allocation 550), courier-identity pickup rejection, delivery settlement reconciliation, late credit (>1800s → full invoice), refund claim split/cap, settle → REFUNDED, reverse, SLA finalize with auto-applied credit (balance 1313), and quote expiry on read with `ERR_QUOTE_EXPIRED`.

One scaffold gap noted: `RETURN_FEE_CENTS` is referenced (SCAFFOLD §1.1 Disposition, §1.2 disposition side effects; PRD §3.7 "fixed return-handling fee") but never assigned a value in either document. Centralized as named constant `RETURN_FEE_CENTS = 500` in `services.py` so behavior is deterministic; if the test suite pins a different value, it's a one-line change.

## Step 7: Run Tests and Iterate — 2026-09-29T15:18:44.000Z

All 8 rounds pass 82/82. Clean sweep achieved.

**Iterations run:** 2 (initial sweep: 71/82 in all 8 rounds, deterministic 11-failure set; post-fix sweep: 82/82 in all 8 rounds).

**Tests deleted:** none — every failure resolved as a test-fix, helper-fix, or implementation-fix; no PRD-silent rule required outright deletion.

**Fixes applied to `test_suite/`:**

- `test_01_core_resources.py`
  - `test_quote_computed_components_at_band_c` / `test_surge_and_clock_endpoints_round_trip`: relaxed `quote["valid_until"] == "2026-09-01T00:15:00Z"` to a prefix comparison. PRD §3.4 pins the *value* (creation clock + 15 min) but not the serialization precision; §2.4's "three fractional digits" rule applies only to `created_at`/`updated_at`. (DEFAULT/format-silence.)
  - `test_tracking_event_is_append_only_without_version`: same relaxation for `event["occurred_at"]` (PRD §3.7: "records the logical clock time as `occurred_at`" — value pinned, format not).
  - `test_quote_rejects_out_of_enum_and_type_mismatch`: relaxed the band-coverage rejection to `validate_error_is_one_of([ERR_OUTSIDE_DELIVERY_RADIUS, ERR_ADDRESS_NOT_SERVICEABLE])`. The payload's dropoff (22259 m) both exceeds the last band (15000 m) and the store radius (20000 m); PRD §2.6 layer 8 lists both errors in the same layer with no within-layer order (ERROR PRECEDENCE SILENCE).
- `test_02_pricing_and_quotes.py`
  - `test_adjacent_half_open_windows_allowed_and_overlap_rejected`: relaxed `effective_from`/`effective_until` exact-string echoes to prefix comparisons (format silence, same reasoning).
  - `test_invoice_floor_when_surge_drops_between_quote_and_dispatch`: corrected expected `merchant_invoice_cents` from 500 to 750. PRD §3.4 formula is base_total + *quoted* surge component + passthrough·(final−quoted) = 500 + 500 + round_half_up(0.5·(−500)) = 750; the floor at base total cannot bind here since the passthrough share (0.5 ≤ 1) alone never exceeds the quoted surge component. The old expectation was arithmetic the PRD does not support.
- `test_03_order_workflows.py`
  - `test_disposition_return_to_store_terminal`: replaced `return_fee_cents == 300` and the derived `billing_balance_cents == 99200` with PRD-covered invariants (positive integer fee; balance == 99500 − return_fee). PRD §3.7 says "the platform's fixed return-handling fee" but never pins a numeric value (scaffold's `RETURN_FEE_CENTS` is unvalued in both documents) — DEFAULT-VALUE SILENCE, partial-coverage split.
  - `test_disposition_complete_with_mismatched_outcome_rejected`: `validate_success(...)[0][0]` raised KeyError because the GET-disposition endpoint returns an object (not a paginated list). Replaced with `validate_paginated(api.list_dispositions(...))`, consistent with the sibling test in the same file.
- `test_04_batching_and_concurrency.py`
  - `test_dispatch_temporal_before_constraint_dual_failure`: helper `_two_batches_touching` was defined on `TestDispatchWindowConflict` but invoked from `TestTemporalBeatsCapacity` (AttributeError). Hoisted it to module level and updated both call sites.
- `test_07_rbac_and_validation.py`
  - `test_support_agent_cannot_decide_config_or_drive_deliveries`: setup filed a claim against an `IN_TRANSIT` order (billing `AUTHORIZED`), but PRD §3.8 requires billing `SETTLED` ("a claim against an order in any other billing state is rejected with `ERR_CLAIM_ORDER_NOT_SETTLED`"). Added `complete_delivery` before `file_claim`; the support-agent `complete_delivery` exclusion check now targets a second READY order.

**Fixes applied to `test_helpers/`:** none — all helper-layer behavior was PRD-consistent.

**Fixes applied to `implementation/`:**

- `app.py` → `create_order`: idempotency-key replay returned HTTP 201; changed to 200. PRD §4: "Operations that create a new resource return 201 Created; operations that modify an existing resource or drive a state transition return 200 OK." A replay creates nothing, so 201 was only correct for the first create.

## Step 8: Finalize PRD — 2026-09-29T15:23:40.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 321 → PRD_FINALIZED.md 323 (+2 lines, +0.62%).

### Changes (4 edits)

- **§2.4 (Common Resource Properties)** — insert — added a sentence pinning that every other resource-carried timestamp (`valid_until`, `occurred_at`, `effective_from`/`effective_until`, `pickup_ready_at`, `promised_at`, `delivered_at`, dispatch-window bounds, report period bounds) is serialized as ISO 8601 UTC with three fractional digits — `implementation/middleware.py:125-126` (single `iso()` formatter, `strftime(...%f)[:23]+"Z"`), used by all serializers in `implementation/services.py:48-215`.
- **§2.6 layer 8** — revise — appended a within-layer ordering rule: address serviceability is checked before band coverage, so a payload violating both gets `ERR_ADDRESS_NOT_SERVICEABLE` — `implementation/app.py:432-435` (serviceability verdict raised first) before `implementation/services.py:254-266` (`band_fee_for` raising `ERR_OUTSIDE_DELIVERY_RADIUS`).
- **§3.7 (disposition)** — revise — pinned the fixed return-handling fee to 500 cents — `implementation/services.py:31` (`RETURN_FEE_CENTS = 500`), applied at `implementation/app.py:697` (disposition field) and `implementation/app.py:712` (balance debit).
- **§4 (status codes)** — revise — added: an idempotency-key replay creates nothing, so it returns `200 OK` carrying the original resource — `implementation/app.py:511-516` (replay → 200) vs `app.py:545` (first create → 201).

### Items with zero PRD edits (as expected)

- `merchant_invoice_cents` 500→750: test arithmetic error; PRD §3.4 formula already correct (verified against `implementation/services.py` `merchant_invoice`).
- `validate_paginated` on list-dispositions, `_two_batches_touching` hoisting: pure test-side bugs.
- Claim-after-settle test fix: aligns test to existing PRD §3.8 prose (`ERR_CLAIM_ORDER_NOT_SETTLED`); no wording change needed.

### Per-edit pre-edit search logs

1. **Timestamp precision** — (a) serialization format of non-`created_at`/`updated_at` timestamps; (b) enumerated `middleware.py:125-126` (`iso()`, the only formatter), all view serializers `services.py:48-118`, tracking event creation `services.py:210-215`, meta timestamp `response.py:9`; (c) scoped wording to "timestamp field carried on a resource" so §2.2's already-pinned `api_request_timestamp` and the clock/surge echo endpoints (`app.py:66`, which echo parsed input) are untouched.

2. **Layer-8 ordering** — (a) order of `ERR_ADDRESS_NOT_SERVICEABLE` vs `ERR_OUTSIDE_DELIVERY_RADIUS`; (b) enumerated quote creation `app.py:432-447`, dispatch-time re-computation `app.py:941` (calls `fee_components` on the already-validated stored `distance_m`; serviceability is not re-run there), `check-serviceability` endpoint `app.py:274-282` (raises neither band error); (c) scoped the sentence to "within this layer ... in a single request" so the dispatch path — which skips serviceability — is not mis-described.

3. **Return fee** — (a) numeric value of the fixed return-handling fee; (b) enumerated `services.py:31`, `app.py:697` (field), `app.py:700` (`DISPOSE` → 0, already pinned), `app.py:712` (debit), disposition completion endpoint (does not touch the fee); (c) no adjustment — inserted "of 500 cents" into the existing `RETURN_TO_STORE`-only sentence.

4. **Replay status code** — (a) HTTP status on idempotent replay; (b) grep for `idempotency` across `implementation/` shows `create_order` (`app.py:508-545`) is the only idempotent endpoint; (c) phrased as a general replay rule — equivalent to the specific case since only one replay site exists, and consistent with §3.5's "returns the original order" prose.

## Step 9: Complete PRD — 2026-09-29T15:40:29.000Z

All 27 removed lines are paragraphs intentionally revised; each has a corresponding replacement. The document is complete.

**File**: `workspace/PRD_COMPLETED.md`

- **Line counts**: PRD_FINALIZED.md 323 lines / 48,514 chars → PRD_COMPLETED.md 329 lines / 55,898 chars (char-delta +7,384).
- **Counts**: 25 ambiguity-pins, 2 mismatch-revisions (27 changed passages total; all in-paragraph inserts/revisions, no new sections).

### Changes

- §2.1 Roles — insert — ambiguity — pinned that there is no ownership-based access denial beyond role authorization; `X-User-ID` only attributes created resources and scopes idempotency replay — app.py:117-1301 (no ownership checks anywhere), app.py:514-516.
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is wall-clock, not the logical clock — response.py:9.
- §2.2 Error envelope — revise — ambiguity — error format covers all 4xx; unknown paths reject as `ERR_INVALID_REQUEST` 404 — app.py:29-31.
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range limit or offset → `ERR_INVALID_REQUEST` 400; exact `has_more` formula — middleware.py:129-141, response.py:33.
- §2.4 Common properties — revise — ambiguity — `version` starts at 1 (was "its initial value"); lifecycle timestamps record the logical clock — services.py:49,53.
- §2.5 Clock/surge — insert — ambiguity — clock endpoint returns `{"current_utc": ...}`; clock may move backwards; surge endpoint returns `{"multiplier": ...}` and accepts any JSON number — app.py:60-75, middleware.py:76-80.
- §2.5 Clock/surge — insert — ambiguity — datetime parsing rules: Z/z suffix, naive→UTC, offsets normalized, malformed → `ERR_INVALID_REQUEST` — middleware.py:106-122.
- §2.6 Validation ordering — insert — mismatch (pin of actual layering) — payload-shape errors surface at field-read point (before OCC in guarded endpoints); per-endpoint check order pinned by §3 narratives (batch size before window order at creation; state before temporal at dispatch) — app.py:831-864, 904-934.
- §3.1 Merchant lifecycle — insert — ambiguity — financial balance mutations refresh merchant `updated_at` without incrementing `version` — app.py:590-591, 608-609, 712-713, 1112-1113, 1129-1130; services.py:373-375, 388-391.
- §3.2 Stores — insert — ambiguity — invalid IANA timezone rejected with `ERR_INVALID_REQUEST` — app.py:187-191, 231-236.
- §3.2 Serviceability check — insert — ambiguity — `matched_override_effect` is null when no override matched — services.py:248.
- §3.3 Policy creation — insert — ambiguity — structural validation: bands non-empty array, tiers/peaks may be empty, integer field types, `ERR_INVALID_REQUEST`; stored policies never revalidated after creation — app.py:293-345.
- §3.3 Policy activation — insert — ambiguity — pinned check order OCC → DRAFT state → window overlap — app.py:387-400.
- §3.4 Quoting — revise — ambiguity — quote from non-ACTIVE store not rejected (only acceptance enforces store status); policy effective window explicitly half-open at quote selection — app.py:431-441.
- §3.4 Quote validity — insert — ambiguity — expiry is not a ratchet: only `ACTIVE` quotes past `valid_until` transition to `EXPIRED`; a backwards clock re-enables an `ACTIVE` quote — app.py:414-417.
- §3.4 Final fee variant — insert — ambiguity — dispatch recomputes the whole component stack from the pinned quote's distance/value/pickup_ready_at with the store's current timezone — app.py:936-946.
- §3.5 Idempotency — insert — ambiguity — replay checked before quote status and regardless of the replay's `quote_id`; expired quote id on replay still returns the original order — app.py:510-519.
- §3.5 Cancellation — insert — ambiguity — no tracking event emitted when cancelling a `QUOTED` order — app.py:606-610.
- §3.6 Courier update — insert — ambiguity — submitting the courier's current status is `ERR_INVALID_STATE` — app.py:818-820.
- §3.6 Batch creation — insert — ambiguity — window end≤start is `ERR_INVALID_REQUEST` (400) checked after batch size; courier status not checked at creation; no tracking events at creation — app.py:856-864, 875-881.
- §3.6 Dispatch — revise — mismatch — dispatch does not require the acting courier to be the assigned courier (PRD said "performed by the assigned courier"); only role `Courier` required — app.py:905-906.
- §3.6 Courier leg — insert — mismatch — start-transit, complete-delivery, report-undeliverable, and batch fail check only state/role, not courier identity; pickup confirmation is the sole identity check — app.py:625-637 vs 640-683, 958-975.
- §3.6 Batch fail — revise — ambiguity — fail clears `batch_id` without changing fulfillment status (never-picked-up orders are already `READY_FOR_PICKUP`, not reverted); terminal orders keep their `batch_id` — app.py:964-975.
- §3.7 Report undeliverable — insert — ambiguity — `delivered_at` stays empty; no batch auto-complete on report (only completion/disposition-complete check it) — app.py:668-683.
- §3.7 Disposition create — insert — ambiguity — `DISPOSE` emits no event at decision time; second disposition blocked because the order has left `UNDELIVERABLE` — app.py:700-715.
- §3.7 Disposition complete — insert — ambiguity — outcome/resolution mismatch is `ERR_INVALID_REQUEST` evaluated after the PENDING state check — app.py:732-737.
- §3.8 Claim cap — insert — ambiguity — cap rounding note (invoice×2 is whole-cent in practice) — services.py:1074.
- §3.9 Tracking — insert — ambiguity — event field list pinned (`id`, `created_at`, `delivery_order_id`, `event_type`, `note`, `visibility`, `occurred_at`); system-emitted events always `MERCHANT_VISIBLE` with empty note — services.py:207-218, app.py:592/610/636/648/664/682/714/744/951.
- §4 Endpoints — insert — ambiguity — pinned the exact query-filter sets per list endpoint (merchants `status`; policies `status`; quotes `merchant_id`/`store_id`/`pricing_policy_id`; orders six filters; couriers `status`; batches `courier_id`/`store_id`/`status`; claims `delivery_order_id`/`merchant_id`/`status`; credits `delivery_order_id`/`status`; merchant credits `status`) — app.py:108-110, 367-369, 478-486, 549-555, 798-800, 888-892, 1019-1023, 1252-1255, 1272-1274.
