# Worklog — task_2176_school_supply_backpack_program

## Step 1: Create task directory — 2026-08-29T14:39:51.847Z

Created `tasks/task_2176_school_supply_backpack_program/` and `tasks/task_2176_school_supply_backpack_program/workspace/`. Index 2176 chosen as max existing index (2175) + 1.

## Step 2: Generate scaffold — 2026-08-29T15:34:00.000Z

Done. All three artifacts are generated, YAML-valid, and pass the skill's linter clean on the first run.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2176_school_supply_backpack_program/`)
- `SCAFFOLD.yaml` (2,635 lines, §1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,092 lines, single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (2,864 lines, single key `scaffold_corner_design`)

**Profile** — expert-plus: primary archetype quota/allocation + secondary ledger reconciliation; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; topology **flat**, state-machine shape **cyclic**, role model **segregation_of_duties**, consistency immediate. `api_prefix: ""` (all collections top-level, FK in body).

**Contents**
- **14 entities**: School, SupplyItem, GradeKitSpec, KitSpecLine, DriveCycle, CollectionSite, DonationBatch, InventoryPosition, CashDonation, PurchaseOrder, VolunteerEvent, DistributionEvent, StudentRegistration, TeacherRequest (20 FKs, all reverse-reachable).
- **11 state machines** incl. cyclic School ACTIVE<->SUSPENDED, cadence-gated DriveCycle DISTRIBUTION->COLLECTING (YEAR_ROUND only), fork-join DonationBatch INSPECTED->{ACCEPTED, QUARANTINED->REMEDIATED->ACCEPTED}, **parallel dimensions** on CollectionSite (operational_status x pledge_status), cyclic StudentRegistration CONFIRMED<->WAITLISTED. Two OCC concurrency rules (registration<->DistributionEvent.version, purchase-order<->DriveCycle.version, both 412).
- **9 calculations**: dual-variant fill projection (PROVISIONAL 100.00 vs FINAL 50.00 on identical data), dual-variant school impact index (INTERIM 43.10 vs AUDITED 35.92), volunteer throughput (nested minima + stepped fatigue), purchase costing (per-pack rounding then sum; fee tier pinned to subtotal, not total), cash waterfall (restricted->unrestricted, created_at ASC), supplemental budget threshold, plus two conservation invariants (physical units, donated cents).
- **32 ordered validations**, **51 endpoints** (incl. `POST /_clock/set_current_utc`, default clock 2026-08-01T00:00:00Z), **54 error codes**, **5 roles** (ProgramDirector/DonorRelations/WarehouseLead opaque; SchoolLiaison->School, SiteCoordinator->CollectionSite entity-backed; PO submitter barred from approving).
- **§1.8: 22 instances** across all nine rules (2–3 each), every numeric assert computed from the pinned formulas.
- **§1.9: 69 instances** over 9 guide sections (60 executable + 9 `excluded_because` stubs).

**Verification run**: `VERDICT: clean lint` (746 calls scanned); plus my own checks — zero unbound `${var}`, all `grounds` refs resolve (errors/priorities/calcs/fields/transitions/concurrency ids), unique names across both design files, every stub's `difficulty_instance` exists, every one of the 54 error codes exercised, and no forbidden concurrency vocabulary anywhere.

## Step 3: Copy shared files — 2026-08-29T15:34:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2176_school_supply_backpack_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-29T15:47:00.000Z

PRD generated at `workspace/PRD.md` — **442 lines**, written incrementally in six appends (no one-shot write).

**Sections emitted**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 10 subsections: 2.1 Operator Identity & RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination & List Ordering, 2.4 Resource Identity/Timestamps/Version, 2.5 The Logical Program Clock, 2.6 Path Resolution & Reverse-Reachability Reads, 2.7 The Rejection Ladder, 2.8 OCC on the Governing Parent, 2.9 Precision/Rounding/Conservation Identities, 2.10 Cascades & Derived Fields
- §3 Business Logic — 9 domain-derived subsections
- §4 Endpoint Definitions, §5 Error Code Catalogue

**Coverage vs scaffold**: entities 14/14; state machines 11/11; transitions 59/59; calculations 9/9; validations 32/32 (full ordered ladder in §2.7); endpoints 51/51; errors 54/54; roles 5/5; concurrency rules 2/2.

**Hard Contract reports**: Field coverage PASS (100 fields, 66 request bodies, 13 query params, 0 missing). Rule coverage PASS (32 validations, 2 OCC, 59 transitions, 9 calcs with all 18 constants and pinned rounding orders, 51 endpoint side-effect scopes, 100 field-structure items, 9 sibling-branch symmetry groups — 0 missing/asymmetric). Path purity PASS (1021 backtick tokens scanned in §3, 0 paths/methods leaked).

Both withheld design indices were never opened, grepped, or referenced.

Orchestrator verification: `grep '^## '` confirms §4 at line 325 and §5 at line 383, file ends mid-error-table at `ERR_SCHOOL_SUBCAP_EXCEEDED` — no silent truncation of sections 4–5.

## Step 6: Generate implementation — 2026-08-29T16:10:00.000Z

(Ran concurrently with Step 5; completed first, so it is recorded first.)

Implementation complete and verified.

**Files created** in `workspace/implementation/`: `start.sh` (foreground launcher, `exec python3 app.py`, guarded `pip install`), `requirements.txt` (Flask==3.0.3), `app.py` (blueprint registration, error handlers, global request lock, `0.0.0.0:$PORT` default 10000), `db.py` (in-memory `Store` with 14 dicts, logical clock default `2026-08-01T00:00:00Z`, common fields, `touch()`, serializer, `round_half_up`), `errors.py` (54-code catalogue + `ApiError` HTTP status map), `response.py` (meta/response_type/data envelope, limit/offset/total_count/has_more), `middleware.py` (X-User-ID/X-User-Role auth ladder 1–2, school/site scope 6–7), `validators.py` (ladder step 3 shape checks, enum sets, pagination, ISO-8601), `calc.py` (9 calculations), `derive.py` (derived fields, reservation legs, waitlist promotion sweep, cascade helpers), `find.py` (per-entity 404 resolution), `routes/` (`schools.py`, `kitspecs.py`, `cycles.py`, `donations.py`, `cash.py`, `events.py`, `students.py`, `__init__.py`).

**Coverage**: 51 routes registered — exactly matching the scaffold's 51-endpoint table (verified by enumerating `url_map`). 14 entities, 11 state machines (incl. cyclic CONFIRMED<->WAITLISTED, cadence-gated cycle reopen, CollectionSite's two independent dimensions, DonationBatch fork/join), 5 roles, 54 error codes. 32-rule rejection ladder in strict priority order per endpoint, including PRD §2.7's step-9 scope limit and the registration-before-event state ordering. Both OCC guards (`expected_distribution_event_version`, `expected_drive_cycle_version`) at ladder step 10. All money in integer cents with Decimal/ROUND_HALF_UP; pinned rounding order (per-pack fee rounded then summed; fee tier keyed off subtotal).

**Verification**: booted via `bash start.sh` and exercised with four end-to-end scripts — all assertions pass. PO costing edge case: gap 19, pack 3, 175c -> ordered_qty 21 / subtotal 3675 / admin_fee 329 / total 4004 (not 331). Funding waterfall + reverse-replay compensation restores gift `allocated_cents` exactly. Acceptance cascade takes the declared figure; unit-conservation identity holds after accept/discard/adjust/reserve/release/fulfil. Waitlist promotion sweep fires on inventory-crediting movements with `verified_at ASC` ordering, stops at seat capacity. Close cascade (CONFIRMED->NO_SHOW, others WITHDRAWN), four-hop school-suspension cascade, one-way cancellation on reactivation. Audited impact index hand-checked: 100 x (0.55*0.25 + 0.30*1.0 + 0.15*0.40) x (1 - 0.5*2/3) = 33.17. Concurrent confirmations against one seat: one 200, one 412 ERR_STALE_EVENT_VERSION, `confirmed_count` stays 1.

Storage is in-memory dicts only — no SQLite, no disk writes; grep confirms no seed/preload path, store empty on every boot.

## Step 5: Generate unit tests — 2026-08-29T16:22:00.000Z

(Launched concurrently with Step 6; completed second.)

Test infrastructure and suite generated.

**Files created** — `test_helpers/` (9 files): `__init__.py` (barrel export), `types.py` (14 entity TypedDicts + 14 status/role enums), `api_client.py` (`ApiClient(GenericApiClient)`, one method per PRD endpoint incl. `/_clock/set_current_utc`), `api_errors.py` (55 error IDs + HTTP map via `set_error_http_status_map`), `assertions.py` (per-entity assertions plus `assert_unit_conservation` / `assert_cash_conservation` / `assert_pct_equals`), `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + `make_school_liaison_headers` / `make_site_coordinator_headers` per-instance builders for the two entity_backed roles), `fixtures.py` (~600 lines, 8 tiers: state progression -> composite programme scenarios such as `setup_backpack_program`, `setup_three_line_program`, `setup_supplemental_budget`, `setup_site_with_scheduled_session`, `setup_funded_purchase_order`, `setup_three_active_partners`; version-reading wrappers thread OCC fields automatically). `test_suite/`: `conftest.py` + 11 domain-named test files (`test_01_catalogue_and_needs_lists.py` … `test_11_identity_scope_and_not_found.py`).

**Test count and coverage** — **104 tests**, all tagged, all executing (no skip/xfail/placeholders). Queue A (Difficulty): 22/22 instances translated, 44 tests (exactly 2 per instance, split so the two tests assert different halves of each instance's `assert` block), 0 skipped. Queue B (Corner): 60/60 executable instances translated, 60 tests (>=1 each), 0 skipped. The 9 `excluded_because:` stubs were not translated; all 9 `difficulty_instance` cross-references verified to resolve.

**Verification performed** — AST-based audit script confirms per test function: exactly one `Design:` tag; namespace/section/rule_id matches source yaml; instance name resolves; every double-quoted docstring fragment >=20 chars survives whitespace-normalised literal match against `workspace/PRD.md`. Result: no citation problems. Also pyflakes clean, all modules import against installed `prd_bench_local_runner.testing`, no scaffold references leak into comments/docstrings, no skip/skipif/xfail.

**PRD-first filter notes** — no instance skipped; every one passed coverage and unique-derivability. Two judgement calls flagged: (1) `inventory_position_is_created_lazily_by_first_adjustment` asserts `adjustment_qty == 12` with `delta_damaged_qty` omitted — PRD does not name that field's default explicitly, but §3.3's "adds the sum of those two deltas to `adjustment_qty` so that the conservation identity continues to hold" pins the observable outcome; kept. (2) Both `priority_pair_validation_conflict` "beats" tests are backed by explicit PRD precedence prose (§2.7 ladder plus the registration-vs-event ordering paragraph), so they assert exact winners rather than `validate_error_is_one_of`.

## Step 7: Run tests and iterate — 2026-08-29T16:35:00.000Z

**Iterations run:** 2 (two full 8-round parallel sweeps).
- Sweep 1: 103/104 in all 8 rounds — one deterministic failure, `test_adjustment_response_already_shows_the_recomputed_position`, identical in every round (not flaky).
- Sweep 2 (after fix): **104/104 in all 8 rounds.**

**Tests deleted:** none. The single failing test passed both STEP 1 sub-checks:
- *1a coverage* — PRD §2.4 states verbatim: "`version` is an integer that starts at 1 when the resource is created and is incremented by exactly 1 on every mutation of that resource"; PRD §3.3 states the position "is created if it does not yet exist" and that on success "both the position's `version` and the cycle's `version` are incremented by 1."
- *1b unique derivability* — the creating cycle-count call is the resource's creation instant, so §2.4 pins it at `version` 1; the second adjustment is the first mutation, so `version` 2. §3.3's increment clause describes the adjustment of an already-existing row and cannot also apply to the same write that mints it without contradicting "starts at 1 when the resource is created" — a rule every other create endpoint in the system already honours.

**Fixes applied to `test_helpers/`:** none. STEP 2 traced the test end-to-end (fixture `create_collecting_cycle` / `create_pencil`, `adjust_inventory` helper, `WL` warehouse-lead headers, `validate_success`) and every precondition, identity and payload matched PRD §3.3's declared input shape and §2.1's role mapping. Test was faithful -> STEP 3.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/donations.py`, `adjust_position()` — the lazily-created `InventoryPosition` was minted at `version` 1 by `base_record()` and then immediately `touch()`ed by the same request, so it surfaced at `version` 2 and the next adjustment produced 3. Captured whether the position pre-existed (`existed = derive.get_position(...) is not None`) and now applies the `touch()` version bump only when the row already existed; a position created by its own first cycle count emerges at `version` 1 per PRD §2.4, with `created_at`/`updated_at` already stamped at the logical instant by `base_record()`.

No implementation check was removed or weakened, no assertion downgraded, no endpoint/field/side-effect added beyond PRD prose, and no entity data is seeded at startup (storage remains in-memory dicts).

Orchestrator verification: all 8 `results.{1..8}.json` present, each reporting `passed == total == 104`.

## Step 8: Finalize PRD — 2026-08-29T16:40:00.000Z

`PRD_FINALIZED.md` written. One edit, tracing to the single `implementation/` fix in `<step_7_diff>`.

**Line counts** — `PRD.md`: 442 lines; `PRD_FINALIZED.md`: 442 lines; **0.00% line delta** (one line revised in place; +2 sentences within §3.3's cycle-count paragraph).

**Change**
- **§3.3 (cycle-count adjustment paragraph, PRD line 221)** — *revise* — replaced "both the position's `version` and the cycle's `version` are incremented by 1" with: the cycle's `version` is always incremented by 1, while the position's `version` is incremented only when the position already existed before the adjustment; an adjustment that is itself the creating write does not count as a mutation of the row, so it stands at `version` 1 per §2.4 "before any further cascade hop touches it" — `implementation/routes/donations.py:203-218`.

**Per-edit pre-edit search log — Edit 1 (§3.3 adjustment version rule)**
(a) Subject: the `version` counter of an `InventoryPosition`, specifically the interaction between lazy position creation and the `touch()` bump — including every operation anywhere in the system that may mint a position as a side effect.
(b) Impl paths enumerated (grep `get_position|refresh_in_transit|touch(pos` across `routes/` + `derive.py`, then read each site): `derive.py:101-121` `get_position(..., create=True)` (sole creation point, mints at version 1); `derive.py:141-153` `refresh_in_transit()` (creates then touches whenever `in_transit_qty` changed; reached from batch creation `routes/donations.py:53`, inspect/quarantine/remediate `:114/:133/:143`, cycle SORTING->DISTRIBUTION `routes/cycles.py:109`, PO submit/cancel `routes/cash.py:238/:270` — a position first minted by any of these emerges at version 2); `routes/donations.py:164-184` acceptance cascade hop 2 (unconditional touch -> version 2); `routes/donations.py:146-157` DISCARDED branch (same); `routes/cash.py:249-253` PO receipt (same); `derive.py:317-357` `reserve_units`/`release_units`/`distribute_units` (unconditional, reachable inside the same adjustment request via the hop-five promotion sweep at `routes/donations.py:216`); `routes/students.py:333-339` teacher-request fulfilment (touch on existing position); `derive.py:224/242/366` read-only `get_position` (no version effect).
(c) Wording adjustments made: two. First, the claim was scoped strictly to *this adjustment endpoint* rather than to newly created positions in general — every other lazily-creating path does bump on creation, so a universal "a freshly minted position is at version 1" would have been a brand-new mismatch. Second, "stands at `version` 1" was softened with "before any further cascade hop touches it", because the same request's hop-five promotion sweep can call `reserve_units` on the just-created position and bump it to 2. No other §3.3/§2.4/§2.10 prose was altered.

## Step 9: Complete PRD — 2026-08-29T16:52:00.000Z

`workspace/PRD_COMPLETED.md` written.

**Source vs output**: `PRD_FINALIZED.md` 442 lines / 99,615 chars -> `PRD_COMPLETED.md` 442 lines / 103,812 chars. Char delta **+4,164**, 25 lines touched, 0 new sections, 0 new paragraphs — every change an in-paragraph insert or revision.

**Counts**: 28 changes total — **22 ambiguity-pins**, **6 mismatch-revisions**.

### Changes
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock, not the logical clock — `response.py:19` / `db.py:66`
- §2.3 — insert — ambiguity — ties on `created_at` (the normal case, clock is static) resolve to server insertion order — `db.py:117-119`
- §2.5 — insert — ambiguity — `current_utc` rendered with three fractional-second digits — `students.py:362`
- §2.7 step 16 — revise — mismatch — cycle-phase gate applies only to batch *acceptance*, order *submission*, event *publish/lock*, request *approval*; all other transitions of those entities are ungated — `donations.py:125`, `cash.py:221`, `events.py:287,299`, `students.py:305`
- §2.7 step-9 boundary — insert — ambiguity — adds the site-active guards on inspection/session-start, the open-batch guard on site close, remaining pledge preconditions, and the draft-list guard on line creation to step 9's covered set — `donations.py:111`, `events.py:103`, `cycles.py:203`, `kitspecs.py:116`
- §4 preamble — insert — ambiguity — a two-role route where §3 reserves a target for one role refuses the other with `ERR_UNAUTHORIZED` at step 2, before path resolution — `donations.py:92`, `cash.py:181-184`, `students.py:287-290`
- §3.1 — insert — ambiguity — `title_i_pct` accepted/stored as supplied; extra precision not rejected — `schools.py:42`
- §3.1 — insert — mismatch — archival also refreshes both impact indices — `schools.py:159`
- §3.1 — insert — ambiguity — adding a line to a non-`DRAFT` list is `ERR_INVALID_SPEC_STATE`, before the item-active rule — `kitspecs.py:116-119`
- §3.2 — insert — ambiguity — remaining pledge preconditions and the site-close open-batch guard report `ERR_INVALID_SITE_STATE` — `cycles.py:203,246,251`
- §3.3 — insert — ambiguity — batch creation mints the position if absent, and the in-transit refresh counts as a mutation (new position -> `version` 2) — `donations.py:53` / `derive.py:141-149`
- §3.3 — revise — mismatch — inspection may be driven by `SiteCoordinator` **or** `WarehouseLead`; both its guards report `ERR_INVALID_BATCH_STATE` — `donations.py:92,108-112`
- §3.3 — revise — mismatch — `qty_rejected` optional/default 0; the <= `qty_declared` bound is judged after step 9 and before hygiene and the phase gate, still as `ERR_INVALID_REQUEST` 400 — `donations.py:94,118-126`
- §3.3 — insert — ambiguity — defines `total_items_on_hand` as the sum of `on_hand_qty` over the cycle's positions — `derive.py:155-161`
- §3.3 — revise — mismatch — hop-five version accounting: an event takes one increment per mutation (fill move + each promotion), not a single one — `derive.py:422-431`, `derive.py:381-404`
- §3.3 — insert — ambiguity — `hold_reason` optional, recorded as null when absent — `donations.py:95,132`
- §3.3 — insert — ambiguity — `delta_damaged_qty` treated as 0 when omitted — `donations.py:197`
- §3.3 — insert — ambiguity — the position created by an adjustment stands even when the adjustment is refused — `donations.py:203-206`
- §3.3 — insert — ambiguity — no floor is applied to `damaged_qty` — `donations.py:209`
- §3.4 — insert — ambiguity — both session-start guards report `ERR_INVALID_EVENT_STATE` — `events.py:100-104`
- §3.4 — insert — ambiguity — the `IN_PROGRESS` from-state is checked before `assembled_kit_count`'s presence; a missing field is `ERR_INVALID_REQUEST` — `events.py:106-113`
- §3.5 — insert — ambiguity — cash-gift body refs resolve in order (cycle, item, school) before the restriction-consistency rule, so a bad id is 404 even when the type forbids the field — `cash.py:21-42`
- §3.5 — revise — mismatch — order cancellation may be performed by `WarehouseLead` **or** `ProgramDirector` — `cash.py:178-184`
- §3.6 — insert — ambiguity — a projection with no published needs list is `0.00` — `derive.py:217-219,235-237`
- §3.6 — revise — mismatch — the closing cascade increments the drive cycle's `version` unconditionally — `events.py:257-259`
- §3.6 — insert — ambiguity — event cancellation refreshes cycle total and school aggregates without incrementing either `version` — `events.py:319-322`
- §3.7 — insert — ambiguity — every unit-moving registration leg refreshes `total_items_on_hand`, but only the compensating waitlist leg bumps the cycle's `version` — `students.py:153-202`
- §3.9 — revise — mismatch — adds event cancellation and `target_student_count` moves (needs-list publish/retire, school archival) to the index-recompute occasions — `events.py:322`, `kitspecs.py:80,95`, `schools.py:159`

Nothing in `implementation/`, `test_helpers/` or `test_suite/` was modified; `SCAFFOLD*.yaml` and `worklog.md` were not read.
