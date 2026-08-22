# Worklog — task_2126_wire_cable_distribution

## Step 1: Create task directory — 2026-08-21T14:11:14.345Z

Created `tasks/task_2126_wire_cable_distribution/` and `tasks/task_2126_wire_cable_distribution/workspace/`.

## Step 3: Copy shared files — 2026-08-21T14:11:14.345Z

Copied `./INSTRUCTION.md` → `tasks/task_2126_wire_cable_distribution/workspace/INSTRUCTION.md`. (Performed early alongside Step 1; no dependency on Step 2.)

## Step 2: Generate scaffold — 2026-08-21T15:13:30.000Z

Done. All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_2126_wire_cable_distribution/`.

## Files

- `SCAFFOLD.yaml` (2502 lines, §1.0–§1.7 + preamble; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2272 lines, single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (2668 lines, single key `scaffold_corner_design`)

## Counts

| | |
|---|---|
| Entities | 12 (Branch, Customer, CableProduct, CopperIndexEntry, Truck, Reel, Quote, QuoteLine, SalesOrder, OrderLine, Allocation, DeliveryRun) |
| State machines | 7 blocks over 6 entities, 37 transitions (SalesOrder has two parallel dimension blocks) |
| Concurrency rules | 2 OCC (`quote-line-add-stale-quote`, `order-allocate-stale-order`) |
| Calculations | 11 |
| Validations | 28 priorities |
| Endpoints | 42 (21 GET / 21 write, incl. one `/_clock/set_current_utc`) |
| Errors | 47 · Roles | 6 |
| §1.8 instances | 23 across all 9 rule_ids (2/3/3/2/3/3/3/2/2) |
| §1.9 instances | 52 (47 with recipes + 5 `excluded_because` stubs) across 8 guide sections |

Profile: `quota_allocation` × `pricing_engine`, topology **flat** (peer collections at root, `api_prefix: ""`), shape **parallel** (plus cyclic Reel/Quote/SalesOrder and branching Allocation), `role_model: segregation_of_duties`, `difficulty_level: expert_plus`.

Lint: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (799 calls scanned)

## Design adjudications made

1. **Above the Expert band on surface, deliberately.** The scenario asked for harder-than-expert, so endpoints (42), errors (47) and calculations (11) exceed §0.4's Expert ranges while entities stay at 12. Recorded as `difficulty_level: expert_plus` with rationale in the file. Endpoint count is inflated partly by the FK reverse-reachability requirement (singleton + filtered-list GET per child entity).
2. **`api_prefix: ""`** to get a genuinely flat topology (§0.3 flags flat as 0% in examples, PRIORITIZE). Every collection is a root peer; only `/quotes/{id}/lines` and `/customers/{id}/credit-adjustments` nest.
3. **Deferred remnant settlement.** First draft spawned a remnant on every cut, which stranded sibling reservations on the same reel. Rule now: settlement (deplete / scrap / spawn remnant) fires only when the cut leaves `allocated_length_ft == 0`; otherwise the reel keeps its remainder as ALLOCATED_PARTIAL.
4. **Quote `CONVERTED` is settled, not terminal.** Index shock could otherwise never reach a live order (converted quotes leave ISSUED). CONVERTED quotes are now voidable while their order is still physically uncommitted, which is what makes the depth-3 index-shock cascade real.
5. **CREDIT_HOLD holds only `PENDING_ALLOCATION` orders.** Holding `PARTIALLY_ALLOCATED` ones too made `ERR_CUSTOMER_CREDIT_HOLD` unreachable on allocate (state check would always win first).
6. **Return keeps `delivered_sales_order_id`** (clears only `delivered_at`), and the `returnable` check was moved ahead of the reel-identity check — otherwise `ERR_CUT_ITEM_NON_RETURNABLE` and `ERR_REEL_NOT_ON_JOBSITE` were both unreachable.
7. **Dropped two structurally unreachable errors** found during chain replay: `ERR_INSUFFICIENT_REEL_LENGTH` and `ERR_REEL_NOT_CUTTABLE` (reservations make both impossible); the corresponding preconditions are retained as stated invariants.
8. **All formula-derived asserts were computed in Python**, not estimated — e.g. 6737/6822 quoted-vs-invoiced line values, 170-cent metal variance, 13474 (round-per-line) vs 13473 (sum-then-round), 24675 vs the 14175 wrong-tier trap, the 500000/499999 free-freight boundary via branch surcharges 23400/23399, and the −8-cent credit-hold trip.
9. **PyYAML quoting workaround**: `input:` flow lists containing `field?` and `captures:` values containing `$.data[0].id` must be quoted, otherwise `yaml.safe_load` (used by `scaffold_lint.py`) fails. The skill's SKILL.md examples show them unquoted — worth noting for future scaffolds.

## Step 4: Generate PRD — 2026-08-21T15:24:00.000Z

PRD generated and verified end-to-end.

**Output:** `workspace/PRD.md` — **415 lines**, ending at §5 with no audit footer.

**Structure:** §1 Introduction (3 paras) → §2 with 10 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 pagination/ordering, 2.4 identity+version, 2.5 logical clock, 2.6 rounding, 2.7 admission ladder, 2.8 OCC, 2.9 SoD/branch scoping, 2.10 cascade discipline) → §3 with 9 workflow subsections (network/catalog → copper feed → quote composition → issue/pricing → revision/conversion → reel stock/allocation → commit fork → delivery → returns/credit) → §4 endpoint table (4 cols) → §5 error table (2 cols).

**Coverage tally (all verified mechanically against SCAFFOLD.yaml):**

| Category | Required | Covered | Missing |
|---|---|---|---|
| Entities | 12 | 12 | 0 |
| State-machine blocks / transitions | 7 / 37 | 7 / 37 | 0 |
| Calculation formulas | 11 | 11 | 0 |
| Validation priorities | 28 | 28 (ordered ladder in §2.7) | 0 |
| Endpoints | 42 | 42 rows | 0 |
| Error IDs | 47 | 47 rows + all 47 referenced in §2/§3 prose | 0 |
| Roles | 6 | 6, each with its `identity:` translated | 0 |
| Concurrency rules | 2 | 2 (endpoint + occ_field + error_id + 412) | 0 |

**Hard Contract reports:** Field coverage PASS (97/97 fields, 60/60 endpoint inputs, 24/24 state values, all enums). Rule coverage PASS (28/28 validations, 2/2 OCC, 37/37 transitions, 11/11 calculations, 42/42 endpoint side-effects, 97/97 field structures, 5 sibling-branch symmetry groups all balanced). Path purity PASS (742 backtick tokens in §3, 0 paths / 0 bare methods / 0 method+path).

§2.2 copied byte-for-byte from `section-2.2-response-structure.md`. Neither design index was opened, grepped, or referenced.

Two notes flagged: the scaffold lists `order_money_rollup` as triggered on quote line-add as well as issue, but elsewhere states `line_subtotal_cents` is 0 while `DRAFT` — the PRD resolves this the way the scaffold's SoD note requires (quote-level roll-up fields stay 0 until issue). Worked examples in the PRD (137-ft/5.6250 c/ft rounding; 400/1000/250-ft ranking) come from SCAFFOLD.yaml's own formula comments, not the withheld design files.

## Step 6: Generate implementation — 2026-08-21T15:48:00.000Z

Implementation complete and verified.

## Files written — `workspace/implementation/` (3,006 lines, 27 files)

| File | LOC | Role |
|---|---|---|
| `start.sh` | 10 | Guarded-install foreground launcher (`exec python3 app.py`) |
| `requirements.txt` | 1 | Flask 3.0.3 |
| `app.py` | 76 | Blueprint registration, error handlers, serialized WSGI dispatch |
| `errors.py` / `constants.py` | 110 / 48 | 47-error catalog; every pinned constant |
| `clock.py` / `db.py` / `response.py` | 79 / 75 / 49 | Logical clock, in-memory stores, envelope |
| `middleware.py` / `validation.py` / `listing.py` | 64 / 218 / 9 | Ladder 1/2/5, ladder 3, pagination |
| `calculations.py` / `serializers.py` | 308 / 224 | All 11 calc rules; 12 entity representations |
| `routes/` (6 files) | 1,025 | 42 endpoints |
| `services/` (6 files) | 710 | Allocation planner, pricing, cascades, index shock, credit |

## Coverage tally (machine-verified against SCAFFOLD.yaml)

- **Endpoints: 42/42**, with **role lists matching the scaffold exactly** — zero missing, zero extra, zero RBAC mismatches.
- **Errors: 47/47** defined with correct HTTP status, all reachable in code (grep-verified none orphaned).
- **Calculations: 11/11** — cut charge/billable length, quote line pricing (QUOTED+INVOICED), six-step money rollup, validity/index shock, reel allocation plan (both policies), branch available footage, deposit credit, cut-floor occupancy, truck window conflict, jobsite reel handling, credit posture.
- **State machines: 7 blocks / 37 transitions** — Quote (cyclic), SalesOrder × 2 parallel axes, Reel (cyclic), Allocation (branching), DeliveryRun, Customer.
- **Validations: 28 priorities** implemented in PRD §2.7 ladder order (PRD prose taken as authoritative over scaffold precondition ordering).
- **OCC: 2 rules** — `expected_quote_version` (412) and `expected_sales_order_version` (412), both at ladder position 28.
- **Roles: 6**, entity-backed ownership for BranchOps/Driver/Customer on exactly the ten operations §2.7 enumerates.

## Verification

Three self-written smoke suites (~250 assertions total) all report **FAILURES: 0** against fresh servers launched with `bash start.sh`, covering: the full quote→issue→convert→allocate→cut/pick→deliver→return lifecycle; both allocation policies diverging on the PRD's 300ft/400/1000/250 example; parallel-set same-lot rule; waterfall split + SHORT + restock top-up; the five-way cut settlement (deplete/defer/scrap/remnant/in-place); cut-floor closed-interval collisions vs. truck half-open adjacency; index-shock cascade through orders to reel reservations; credit-hold cascade in both directions; metal variance; free-freight waiver; aluminium zero-adder; and the full 404/422/409/402/412 error ladder.

`bash start.sh` binds `0.0.0.0:$PORT` (default 10000) and answers HTTP in ~520 ms; the pip install is guarded on `import flask` so per-test reboots are no-ops. Storage is in-memory dicts only — verified `all stores empty at boot`, no seeding, no disk persistence.

**Judgment calls worth flagging:** (1) version bumps follow the scaffold's explicit per-transition `increments X.version by 1` statements, so a delivery bumps the order twice (fulfillment axis + billing axis) while an index-shock cancel bumps once; (2) "every allocation is COMMITTED/RESERVED" gates ignore `RELEASED` rows, since a literal reading would permanently break staging after any release cycle; (3) `GET /sales-orders/{id}` enforces ownership for BranchOps as well as Customer, per §2.7's "for the entity-backed roles".

## Step 5: Generate unit tests — 2026-08-21T16:14:00.000Z

Test infrastructure and suite are complete and verified.

## Files written

**`test_helpers/`** (Stage 1, 9 files) — `types.py` (12 entity TypedDicts + 14 enums; `CopperIndexEntry` correctly omits `updated_at`/`version`), `api_client.py` (42 endpoint methods), `api_errors.py` (47 error ids + HTTP map registered with the framework), `assertions.py` (per-entity assertions + `assert_reel_footage_invariants`, `assert_customer_credit_invariants`, `assert_success_envelope`, `assert_same_instant`), `factories.py` (P1/P3/P4 catalog presets + payload factories), `constants.py`, `test_users.py` (shared constants for the three opaque roles + per-instance builders for the three entity-backed roles), `fixtures.py` (~600 lines, 5 tiers: single-resource creation → quote building → `setup_converted_order` → `setup_allocated_order` / `setup_staged_order_by_cut|pick` → `setup_delivered_master_reel_order` + `deliver_order` + `return_reel`), `__init__.py` barrel.

**`test_suite/`** (Stage 2) — `conftest.py` + 10 domain-named test files (`test_01_catalog_and_identity` … `test_10_listing_and_pagination`).

## Test counts

| | instances | translated | skipped | tests |
|---|---|---|---|---|
| Queue A (Difficulty) | 23 | 23 | 0 | 46 |
| Queue B (Corner, non-stub) | 47 | 47 | 0 | 47 |
| Queue B stubs | 5 | — | not translated (by spec) | 0 |

**93 test functions; 103 collected** (two 6-way `parametrize` families for the not-found catalogue expand to 12).

## Verification performed

An automated audit (AST walk of every `test_*` function) confirms:
- **0 bad citations** — every `PRD §x.y: "…"` quote survives a whitespace-normalised literal match against `PRD.md`.
- **0 untagged, 0 dual-tagged, 0 unknown tags** — each test ends with exactly one `Design:` line resolving to a real instance.
- **Coverage**: every difficulty instance ≥2 tests; every non-stub corner instance ≥1 test; all 5 stub `difficulty_instance` cross-references resolve.
- **0** occurrences of `skip` / `xfail` / `scaffold` / `§1.x` anywhere in generated code; `pyflakes` clean; `pytest --collect-only` clean.

## Instances skipped

None. All 23 difficulty and all 47 non-stub corner instances passed the PRD-first two-condition filter — this PRD is unusually complete: §2.7's 28-step admission ladder pins every precedence pair the design indices exercise, §3.4's six-step roll-up pins the freight/rebate circularity, and §3.6/§3.7/§3.9 spell out the allocator ranking, the five-way cut settlement and the four-check return sequence verbatim.

## PRD-coverage gaps found (design decisions made, not test weakenings)

1. **Input-datetime serialization is unspecified.** §2.4 fixes the format only for `created_at`/`updated_at`; it never says how caller-supplied `window_start`, `cut_window_start` or the server-derived `valid_until` are echoed back. Two faithful readers could return `…T10:00:00Z` or `…T10:00:00.000Z`. The design indices assert the `.000Z` literal; I assert **instant equality** instead via `assert_same_instant`, preserving the substance (the 24-hour validity window, the accepted adjacency) without hard-coding one of two PRD-consistent serializations. Affects 4 assertions in tests 04/06/07.
2. **Delivery-run creation on a non-`STAGED` order.** §3.8's prose opens with "schedules a run for one *staged* order" but then says "Three admission rules guard the schedule" and lists only truck-branch, active-run and truck-window; the `ERR_ORDER_NOT_STAGED` ladder entry (item 23) is scoped to *dispatch*. Two difficulty instances (`dispatch_gated_by_sales_order_reaching_staged`, `truck_half_open_window_exclusive_with_adjacency_allowed`) depend on creation succeeding for an `ALLOCATED`/`PENDING_ALLOCATION` order. I translated them as designed, reading the enumerated "three admission rules" as authoritative — but the introductory "staged order" wording is a latent ambiguity an implementer could read the other way.

## Step 7: Test and fix loop — 2026-08-21T16:23:00.000Z

All 8 parallel rounds pass 103/103. Exiting.

## Summary

**Iterations run:** 2 (each an 8-round parallel stability sweep, 103 tests/round).

- Sweep 1: 100/103 in all 8 rounds — the same 3 failures in every round (deterministic, not flaky).
- Sweep 2: **103/103 in all 8 rounds.**

**Tests deleted:** none. One test had two assertions removed under STEP 1c partial-coverage handling (see below).

**Fixes applied to `test_helpers/`:** none — the failures were not fixture-wide, so no helper changed.

**Fixes applied to `test_suite/`:**

- `test_suite/test_05_allocation.py` — `_short_order_then_credit_hold()`: restock the branch (500 ft, lot `L2`) after the first allocation run. The fixture drained the only reel, so the re-allocation attempt violated **two** ladder checks at once and PRD §2.7 ("the first violated check determines the response… The lowest number wins") makes item 20 `ERR_NO_ELIGIBLE_REEL` beat item 26 `ERR_CUSTOMER_CREDIT_HOLD`. The implementation was PRD-faithful; the setup masked the check under test. Assertion left exact.
- Same file — `test_stale_expected_sales_order_version_on_allocate_is_rejected`: same restock inserted between the first run and the stale-version call, for the same reason (item 20 outranks item 28 `ERR_STALE_ORDER_VERSION`). Assertion left exact.
- `test_suite/test_09_cascades_and_credit_posture.py` — `test_index_shock_releases_the_reservation_back_into_branch_stock`: dropped `line["allocated_length_ft"] == 0` and `line["allocation_status"] == "UNALLOCATED"`. **PRD silence — BRANCH-ASYMMETRIC SIDE EFFECT.** §3.2 Cascade link 3 renders only the allocation→`RELEASED` move, the reel's `allocated_length_ft` decrement, and the reel's `ALLOCATED_PARTIAL → IN_STOCK` return; it never says the *order line* is reset. The line reset appears verbatim only in §3.6's explicit release endpoint ("Every line is reset to `allocated_length_ft` 0 and `allocation_status` `UNALLOCATED`"), and §3.6's line recomputation is scoped to "afterwards" inside the allocation run. Two faithful readers diverge, so the assertion fails unique derivability. The covered assertions (allocation `RELEASED`, reel `IN_STOCK`, `allocated_length_ft == 0`, `current_length_ft == 200`) were kept. Scaffold rule that drove it: `Difficulty/transitive_cascade/index_shock_publication_cascade_depth3_to_released_reservations`.

**Fixes applied to `implementation/`:** none. All three failures traced to test-side setup or PRD silence; no implementation check was weakened or added.

**Feedback for the generators:**
- *doc-generator (Zero-Silence violation):* §3.2's Cascade link 3 omits the order-line `allocated_length_ft`/`allocation_status` write that §3.6 spells out for the sibling release path — a branch-asymmetric compression.
- *unit-test-generator (setup hygiene, not derivability):* two allocation tests built scenarios that violate an earlier ladder item than the one under test. When PRD pins an explicit admission ladder, a negative test must isolate its target check — every lower-numbered check has to be satisfiable in the fixture state.

The two ambiguities flagged going in did **not** materialise as failures: `assert_same_instant` datetime echoing and §3.8's delivery-run-creation-on-non-`STAGED` reading both held under the implementation as written.

## Step 8: Finalize PRD — 2026-08-21T16:26:00.000Z

Done. `PRD_FINALIZED.md` written with a single edit.

## Line counts
- `PRD.md`: 415 lines — `PRD_FINALIZED.md`: 415 lines — **0.0% line delta** (one line revised in place; +336 characters).

## Changes
- **§3.2, Cascade link 3** — *revise* — appended a sentence pinning that the index-shock release does **not** rewrite order lines: each line's `allocated_length_ft` / `allocation_status` are left exactly as they stood and the line resource is not touched (so no `version`/`updated_at` bump either), explicitly contrasted with §3.6's explicit release which does reset them — `implementation/services/index_shock.py:47-50` (calls `allocation_svc.release_allocation` directly) vs `implementation/services/allocation.py:177-189` (`release_allocation` touches only allocation + reel) and `implementation/routes/orders.py:133-136` (release endpoint resets lines).

## Per-edit pre-edit search log

**Edit 1 — §3.2 Cascade link 3**
- **(a) Subject:** who writes an order line's `allocated_length_ft` / `allocation_status`, and what the index-shock cascade touches.
- **(b) Impl paths enumerated** (grep `release_alloc|recompute_line|UNALLOCATED|"allocated_length_ft"\]` across all `.py`, then read each):
  - `services/index_shock.py:23-53` — links 1/2/3; touches quote, order, allocation, reel. No line write, no `db.touch(line)`.
  - `services/allocation.py:177-189` `release_allocation()` — allocation → `RELEASED`, reel decrement, `ALLOCATED_PARTIAL → IN_STOCK` guarded on `current_length_ft > 0`. No line write. Only two callers: index_shock and `release_allocations_of_order`.
  - `routes/orders.py:117-140` — explicit release endpoint: calls `release_allocations_of_order`, *then* separately resets every line to 0/`UNALLOCATED`. Confirms the line reset lives in the endpoint, not the shared helper.
  - `services/allocation.py:158-166` `recompute_line()` — the only other line write; sole caller `apply_allocation:152-155` (allocation run).
  - `routes/quotes.py:248-268` — line birth at conversion (`allocated_length_ft` 0, `allocation_status` `UNALLOCATED`).
  - `routes/allocations.py:66,121` (cut/pick) and `services/delivery.py` — read order lines, write `invoiced_extended_cents` only; never the allocation fields, so the commit/deliver paths stay consistent with the new sentence.
  - `§2.10` cascade rule (version bump for touched resources) — checked for consistency; the "does not touch" phrasing is what the impl exhibits.
- **(c) Wording adjustment:** drafted "keep whatever values the allocation run last computed" and **softened to "exactly as they already stood"** — a line can reach link 3 holding values written at conversion (never-allocated order, `PENDING_ALLOCATION`) or by a prior release, so attributing provenance to the allocation run would have been a false universal. Also scoped the claim to "this link" rather than the cascade as a whole.

## Items deliberately **not** patched
- `test_05_allocation.py` `_short_order_then_credit_hold()` and `test_stale_expected_sales_order_version_on_allocate_is_rejected` — pure fixture bugs. `routes/orders.py:88-103` evaluates ladder items 7 → 14/20 → 26 → 28 in exactly the order §2.7 already fixes ("The lowest number wins"), so PRD uniquely determines the behavior and the prose is kept verbatim.

## Step 9: Complete PRD — 2026-08-21T16:35:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 415 lines / 82,933 chars → `PRD_COMPLETED.md` 415 lines / 89,518 chars (**+6,585 chars, +0 lines**). Section headers (27) and table rows (93) are byte-identical — every change is an in-paragraph insert or revision; no new sections, no new table rows.

**Counts**: 38 changes — **28 ambiguity-pins**, **10 mismatch-revisions**.

Verified coverage: all 42 routes, all 47 error ids, the 28-step admission ladder walked endpoint-by-endpoint (impl order matches on every action endpoint), both OCC guards, all 11 calculations, all 7 state-machine blocks, and both cascades.

### Changes

- **2.1 Identity/RBAC** — insert — ambiguity — blank/whitespace-only headers also yield `ERR_UNAUTHENTICATED` — `middleware.py:23`
- **2.1 BranchOps** — insert — mismatch — the "concretely" list is exhaustive *plus* reading a single sales order; reel receipt is deliberately **not** branch-scoped — `routes/orders.py:25`, `routes/reels.py:17`
- **2.1 Customer** — insert — ambiguity — only the two single-resource reads are ownership-scoped; list endpoints apply no customer scoping — `routes/quotes.py:64`
- **2.2 Envelope** — insert — ambiguity — `api_request_timestamp` is real wall-clock, not the logical clock — `response.py:16`
- **2.3 Pagination** — insert — ambiguity — negative `offset`, non-integer `limit`/`offset`, and out-of-enum filter values → 422; identifier filters never resolved (empty page, not 404) — `validation.py:180-198`
- **2.4 Versioning** — revise — ambiguity — `version` advances once per *write step*, so one request can advance a resource more than once — `db.py:66`
- **2.5 Clock** — revise — ambiguity — `data` is the single field `current_utc`, ISO-8601 with 3 fractional digits; any parseable instant accepted — `routes/catalog.py:227-233`
- **2.6 Units** — revise — ambiguity — money is integer-strict; `min_cut_length_ft`/`master_reel_length_ft` integer-typed, other footage/weight fields accept any JSON number — `validation.py:54-104`
- **2.6 Rounding** — insert — ambiguity — copper adder appears as a plain JSON number (`5.625`) — `calculations.py:111`
- **2.7 Ladder 10** — revise — mismatch — "every allocation's reel sits at the order's branch" carries no rejection and is never re-tested — `routes/delivery.py:38`
- **3.1 Branch** — revise — mismatch — `region_code` accepts any non-blank string; length never validated — `routes/catalog.py:26`
- **3.1 Truck** — insert — ambiguity — `max_reel_slots` drives no logic — `routes/catalog.py:57`
- **3.1 Credit adjustment** — insert — ambiguity — omitted deltas are 0; no adjustment resource persisted; 200 with the customer — `routes/catalog.py:116-129`
- **3.1 Product** — insert — ambiguity — non-zero `copper_lbs_per_1000ft` on ALUMINUM → `ERR_INVALID_REQUEST` — `routes/catalog.py:149`
- **3.1 Product** — insert — ambiguity — `min_cut_length_ft` below 25 → `ERR_INVALID_REQUEST`, not `ERR_BELOW_ABSOLUTE_MIN_CUT`; whole feet — `routes/catalog.py:142`
- **3.1 Product** — revise — ambiguity — `master_reel_length_ft` must be a whole number — `routes/catalog.py:145`
- **3.1 Product** — insert — ambiguity — repeated `allowed_put_ups` member stored once, first-appearance order — `validation.py:141`
- **3.2 Cascade link 3** — revise — mismatch — reel returns to `IN_STOCK` only if it still carries physical footage — `services/allocation.py:186`
- **3.3 Quote lines** — revise — ambiguity — `parallel_set_size` may not be below 1 — `routes/quotes.py:91`
- **3.3 Quotes** — insert — ambiguity — quote list filters: `customer_id`, `branch_id`, `copper_index_entry_id`, `status` — `routes/quotes.py:67-70`
- **3.3 Quote lines** — insert — ambiguity — line-add advances the parent quote's `version`/`updated_at` — `routes/quotes.py:129`
- **3.4 Per-line pricing** — insert — ambiguity — issue advances each repriced line's `version`/`updated_at` — `services/pricing.py:59`
- **3.5 Reprice** — revise — mismatch — `physical_reel_count` is zeroed too; line `cut_charge_cents_total`/`deposit_cents_total` zeroed and re-derived at next issue — `services/pricing.py:79-92`
- **3.6 Master-reel pick** — revise — mismatch — count is `ceil(residual ÷ master_reel_length_ft)`, not the line's `reel_count` (equal only on a first run) — `services/allocation.py:92`
- **3.6 Allocation** — insert — ambiguity — `sequence_no` on a top-up run continues from one above the line's highest — `services/allocation.py:122`
- **3.6 Allocation** — revise — ambiguity — *every* line is recomputed and version-advanced, including skipped ones — `services/allocation.py:152-166`
- **3.6 Allocation run** — insert — ambiguity — answers 200 with the sales order — `routes/orders.py:114`
- **3.6 Release** — revise — mismatch — only `COMMITTED`/`CONSUMED` block; already-`RELEASED` allocations never block a later release — `routes/orders.py:128`
- **3.6 Release** — insert — ambiguity — answers 200 with the order — `routes/orders.py:140`
- **3.7 Cut** — revise — mismatch — `cut_charge_applied_cents` is the bare per-conductor charge, never × `parallel_set_size` — `routes/allocations.py:92`
- **3.7 Staging** — revise — mismatch — bubble tests only `RESERVED`/`COMMITTED` allocations (RELEASED ignored) and fires only from `ALLOCATED`; both branches answer 200 with the allocation — `services/allocation.py:239-250`
- **3.8 Scheduling** — insert — mismatch — creation never inspects the order's `fulfillment_status`; STAGED bites only at dispatch — `routes/delivery.py:23-50`
- **3.8 Scheduling** — insert — ambiguity — delivery window has no ordering constraint (`window_end` need not follow `window_start`) — `routes/delivery.py:27`
- **3.8 Dispatch** — insert — ambiguity — answers 200 with the run — `routes/delivery.py:115`
- **3.8 Deliver** — insert — ambiguity — response carries the run, not cascaded resources — `routes/delivery.py:135`
- **3.8 Cascade link 3** — insert — ambiguity — with no index effective on/before the delivery date, repricing is skipped whole (invoiced fields stay null) while `INVOICED`, deposit charge and balance still fire — `services/delivery.py:57-83`
- **3.9 Return** — insert — ambiguity — answers 200 with the returned reel — `routes/orders.py:173`
- **5 Catalogue intro** — insert — ambiguity — unrouted path/method answer `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405), outside the 47-entry catalogue — `app.py:36-41`
