# Worklog — task_3220_classroom_book_club_flyer_ordering_teacher_reward

## Step 1: Create Task Directory — 2026-09-30T00:00:00.000Z

Used pre-allocated task directory `./tasks/task_3220_classroom_book_club_flyer_ordering_teacher_reward` (already created with `workspace/` inside); no new index computed.

## Step 2: Generate Scaffold — 2026-09-30T11:52:00.000Z

All done. The lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Generated the complete scaffold for **task_3220_classroom_book_club_flyer_ordering_teacher_reward** (Classroom Book Club Flyer Ordering & Teacher Reward Points), calibrated beyond Expert per the user instruction. No sibling tasks were consulted.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3220_classroom_book_club_flyer_ordering_teacher_reward/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**SCAFFOLD.yaml contents:**
- Complexity profile: pricing_engine × posture_driven_gating, layers = optimistic_concurrency + cascading_side_effects + dual_variant_calculation + rate_threshold_triggers; parallel state-machine shape; peer_roles
- **14 entities**: School (posture derived from ProgramEnrollment), Teacher, Title (license/royalty ledger), Promotion, FlyerCycle, FlyerOffering (pinned club price + fair_overlap), ClassOrder (3 parallel state dimensions: status × ship_status × points_status), OrderLine, BookFair, FairTitle, DonationRequest, Redemption, ProgramEnrollment, PointsLedger
- **9 state machines** (parallel dimensions on ClassOrder, clock-driven BookFair, cyclic license flips on Title)
- **2 OCC concurrency rules** (class-order submit, title acquire — both lint rule (e) compliant)
- **6 calculations**: tier_discount_band (whole-subtotal single rounding, pinned), reward_points_base (AWARDED vs CLAWED_BACK variants, pinned-clawback), club_price_derive (floor 70%), shipping_fee_resolve (school-level vs order-level waiver), title_royalty_accrue (chronological, strict `>` cap), points_expiry_sweep (FIFO 12-month expiry)
- **25 validation rules**, **31 error codes**, **64 endpoints** (incl. `/_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z`, `/_ops/run-ops`, `/_ops/run-shipping`), **5 roles** all with `identity:`

**Design files:**
- Difficulty design: 9 rules × 2 instances = **18 instances**, each with fully structured, placeholder-closed setup chains; all formula-derived asserts pre-computed as literals (e.g. subtotal 6300 → discount 315 → net 5985; 2x promo + stacked incentives → 70 points)
- Corner design: **47 instances** across 7 sections (39 active + 8 `excluded_because` stubs referencing §1.8 instances)

All setup chains were rule-replayed against §1.2/§1.4/§1.6 (including subtle replays like enrollment-before-publish posture gating and fair_overlap counting SCHEDULED fairs so the October-fair fixture works at publish time); `scaffold_lint.py` reports clean (520 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-09-30T11:53:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3220_classroom_book_club_flyer_ordering_teacher_reward/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T12:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3220_classroom_book_club_flyer_ordering_teacher_reward/workspace/PRD.md` (348 lines). The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

## Document structure

- **§1 Introduction** — 2 paragraphs, business-context angle.
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC (5 roles, per-role identity semantics incl. entity-backed `Teacher`), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1–100, offset 0, `created_at` ASC, filter params), 2.4 Common Resource Properties (UUID `id`, ISO 8601 3-fraction-digit timestamps, `version`), 2.5 Logical Clock (default `2026-09-01T00:00:00Z`, `to_iso8601`, clock-driven transitions), 2.6 OCC (`expected_class_order_version` / `expected_title_version` → `ERR_STALE_VERSION` 412, no race framing), 2.7 Monetary Precision (whole cents, round-half-up once on aggregate, floor for points/club price), 2.8 Validation Order (all 25 priorities as an explicit ordered list with a worked precedence example), 2.9 Nested Path Validation (left-to-right, `ERR_NOT_FOUND` vs `ERR_REFERENCE_NOT_FOUND`).
- **§3 Business Logic** — 12 subsections: schools/posture cascade, teachers & ledger, titles/royalty (90¢/unit, strict-above-cap flip, non-blocking suspension), promotions, flyer cycles/offerings (70/100 club price pin, publish gates in priority order), class orders/lines (3 parallel dimensions, line snapshots, parent ownership via `submitted_by`), order economics (tier table 0/5000/15000/40000 at 0/500/1000/1500 bp, per-line rounding forbidden, shipping 750¢ with inclusive 2500¢ waiver, 100¢/point base + best-multiplier + stacking incentives, remainder attribution), submit/cancel/shipping sweep, book fairs (half-open windows, overlap cap 2 inclusive, `fair_overlap` recompute triggers), donations (all-or-nothing match, ad-hoc force-published cycle on fulfill), redemptions (BOOK vs SUPPLY at 200 pts/unit), ops run/12-month FIFO expiry.
- **§4 Endpoint table** — all 64 endpoints, 4 columns only. **§5 Error catalogue** — all 31 errors, 2 columns only.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 65 required, 65 present, 0 missing
- endpoints[].request_body: 38 required, 38 present, 0 missing
- path params: {id} present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed in §2.8 ordered list, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 19 checked, 19 fully expressed (from/to, preconditions + error ids, side effects incl. cascades), 0 missing
- calculations[]: 6 checked, 6 fully expressed in prose (constants 70/100, 100¢/pt, 750¢, 2500¢ inclusive, 90¢, 12 months, tiers, remainder tie-break), 0 missing
- validations[] conditions: 25 checked, 25 matchable to error_id in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (posture gates 5 ops, license gates 4 ops, OCC guards 2 ops, ownership 5 ops), 0 missing
- entities[].fields[] structured content: defaults (low_income_program=false, donation_funded=false, note=""), computed fields, pinning semantics all reconstructible, 0 missing
- sibling-branch symmetry: fair cancel SCHEDULED vs ACTIVE, order cancel OPEN vs SUBMITTED, promo BONUS_POINTS vs TITLE_INCENTIVE, ship PENDING→PARTIAL/SHIPPED and PARTIAL→SHIPPED all rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 492
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 31 error IDs, all state enum values, all enum-type field values (`K_2`/`G3_5`/`G6_8`, `HARDCOVER`/`PAPERBACK`/`CLUB_PAPERBACK`, ledger/promotion/redemption kinds), and all 5 role names verified present verbatim.

## Step 5: Generate Unit Tests — 2026-09-30T12:30:00.000Z

Generation complete. Here is the summary.

## Summary

**Task**: `task_3220_classroom_book_club_flyer_ordering_teacher_reward` — Classroom Book Club Flyer Ordering & Teacher Reward Points.

### Instance counts

**Queue A (Difficulty)** — 9 rule_ids × 2 instances = 18 instances; target ≥2 tests each:
- Emitted: **18/18** instances, **36 tests** (exactly 2 per instance).
- Skipped: 0.

**Queue B (Corner)** — 39 instances total; 8 are `excluded_because:` stubs (cross-references all verified to resolve), leaving 31 non-stub; target ≥1 test each:
- Emitted: **31/31** instances, **39 tests** (several instances covered by multiple tests).
- Skipped: 0.

Every instance passed the PRD-first two-condition filter — the PRD's narrative sections plus the §2.8 priority list verbatim-cover all asserted rules, including the two validation-precedence pairs (PRD §2.8 explicitly enumerates priority 7 before 24 and 9 before 25, so both priority-pair difficulty instances were derivable).

### Files written

`test_helpers/` (10 files): `__init__.py`, `types.py` (17 status/kind enums + 15 entity TypedDicts), `api_client.py` (one method per each of the 42 endpoints under `/club`), `api_errors.py` (31 error IDs + HTTP status map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque role headers + `make_teacher_headers` for the entity-backed Teacher role), `fixtures.py` (composite helpers: `make_school_world`, `setup_published_cycle`, `setup_open_order`, `setup_submitted_order`, donation/redemption creators, shipping/ops/clock runners).

`test_suite/` (16 files, 75 tests): `conftest.py`, `test_01_reward_points_economics.py`, `test_02_royalty_licensing.py`, `test_03_order_pricing_and_shipping.py`, `test_04_class_order_lifecycle.py`, `test_05_points_conservation.py`, `test_06_validation_precedence.py`, `test_07_book_fairs_and_cycles.py`, `test_08_donations_and_redemptions.py`, `test_09_optimistic_concurrency.py`, `test_10_entities_and_catalog.py`, `test_11_state_machines.py`, `test_12_validations.py`, `test_13_error_paths_and_ownership.py`, `test_14_endpoints_and_consistency.py`, `test_15_roles.py`.

### Stage 2 self-check results

- **Tag audit**: 57 expected instance tags, 57 emitted; every difficulty instance has exactly 2 tests, every non-stub corner instance ≥1; no extra/unknown tags; all 8 stub cross-references resolve.
- **Citation audit**: all 49 docstring PRD citations survive a normalized verbatim grep of `workspace/PRD.md` (markdown-escape tolerant); every docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance.
- **Compile + collect**: `compileall` clean; `pytest --collect-only` reports 75 tests, 0 errors.
- **No skip/xfail markers**, no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-09-30T12:45:00.000Z

Implementation complete for task_3220 (classroom book club flyer ordering & teacher reward points).

**File list** (all under `tasks/task_3220_classroom_book_club_flyer_ordering_teacher_reward/workspace/implementation/`):
- `start.sh` — exec launcher, guarded pip install, `app.py` in foreground
- `requirements.txt` — flask
- `app.py` — Flask entry, blueprint registration, ApiError/404/500 handlers, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores (14 dicts) + logical clock pinned at `2026-09-01T00:00:00Z` on every boot; no seeding
- `errors.py` — ApiError + full 31-error catalog with HTTP statuses
- `response.py` — `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination (defaults 10/0, max 100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401) + role checks (403)
- `services.py` — all calculations (tier discount half-up on whole subtotal, reward points pinned 3-step order with best-multiplier + stacking title incentives, club 70% floor pricing, shipping waivers, royalty accrual/reversal with strict `>` cap flip, FIFO points expiry, shipping sweep), derived fields (posture, active_fair_id, license_status, fair_overlap, fair_count_used), suspension cascade, clock transitions
- `routes/` — `common.py` helpers + 10 blueprints

**Endpoint coverage: 42/42** — all endpoints from the scaffold §1.5 table are implemented (schools 11, teachers 7, titles 10, promotions 3, cycles/offerings 8, orders/lines 7, fairs 5, donations 5, redemptions 4, ops/clock 3 — several path groups cover multiple table rows).

**Verified live** (server booted on test ports, exercised end-to-end, then killed):
- Full happy path: school → enroll → teacher → title → cycle → offering (CLUB_PAPERBACK pins 2100 from 3000) → publish → order → line → submit with OCC; aggregates exact (subtotal 6300, tier-1 discount 315, base points 63)
- Royalty crossing cap mid-submit → license SUSPENDED after event, lines BACKORDERED, ship stays PENDING; cancel-from-SUBMITTED clawback reverses royalty and flips license back to ACTIVE; balance/earned/ledger all reconcile
- Fair SCHEDULED→ACTIVE on clock advance, `active_fair_id` derivation, half-open overlap rejected / adjacency allowed, `fair_count_used` counting
- Donation match (all-or-nothing) → fulfill creates SUBMITTED donation-funded order, `donated_books_received` increments, royalty accrues
- Points expiry FIFO: EARN 100, REDEEM 40 consumed oldest first, clock +13 months expires exactly 60, one aggregated EXPIRE entry, balance reconciles to 0
- Error precedence: 401 → 403 → path 404 → body-ref 404 → state → posture → ownership → OCC 412; `ERR_STALE_VERSION` on title acquire, suspension cascade cancels OPEN orders, reinstate restores NORMAL

`start.sh` boots cleanly from a fresh process on `$PORT`/`0.0.0.0` in the foreground (confirmed via three separate invocations); state wipes on every restart since all storage is module-level dicts.

## Step 7: Run Tests and Iterate — 2026-09-30T13:00:00.000Z

All 8 rounds pass 75/75.

## Summary

- **Iterations run:** 2 (initial sweep: 64/75 in all 8 rounds; after fixes: 75/75 in all 8 rounds).
- **Tests deleted:** none.
- **Fixes applied to `test_suite/`:**
  - `test_03_order_pricing_and_shipping.py` — added missing `publish_cycle` import (NameError on 6 tests; the helper exists in `test_helpers.fixtures` and was used by every other module).
  - `test_05_points_conservation.py` — three tests (`test_cancel_after_promo_expiry_claws_back_the_pinned_amount`, `test_submit_then_cancel_round_trip_restores_balance_and_reconciles`, `test_submit_then_cancel_restores_royalty_headroom_exactly`) cancelled SUBMITTED orders whose titles' licenses stayed ACTIVE, so per PRD §3.8 ("if zero non-cancelled lines are backordered after the pass, `ship_status` advances directly from `PENDING` to `SHIPPED`" and cancel-from-SUBMITTED requires PENDING) the orders were SHIPPED and legally uncancellable. Setups adjusted to force a backorder (low `royalty_cap_cents` on the line's title, or a decoy capped title alongside the headroom title) so `ship_status` stays PENDING — making the cancel legal per PRD without touching any asserted rule.
  - `test_13_error_paths_and_ownership.py` (`test_cancel_blocked_when_clawback_would_drive_balance_negative`) — same SHIPPED-vs-PENDING setup bug; the solvency gate (priority 19) is only reachable when the order is PENDING. Setup now uses `royalty_cap_cents=89` (suspends at submit → backordered → PENDING) and spends points via a BOOK redemption on a second, license-ACTIVE title.
- **Fixes applied to `implementation/`:**
  - `workspace/implementation/services.py` (`fire_clock_transitions`) — a fair whose entire window was skipped by a single clock advance stayed `SCHEDULED` forever because the `if/elif` fired only one transition per advance. Added a `SCHEDULED` + `today >= _end` branch that completes the fair directly (PRD §2.7: fairs move "from `ACTIVE` to `COMPLETED` when the clock date reaches or passes `end_date`", fired by clock advancement). Fixed `test_11_state_machines.py::test_completed_fair_cannot_be_cancelled`.

## Step 8: Finalize PRD — 2026-09-30T13:10:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_3220_classroom_book_club_flyer_ordering_teacher_reward/workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 348 lines, PRD_FINALIZED.md 348 lines — 0% line-count delta; two sentences revised in place, nothing added or removed structurally.

**Changes (one per edit):**
- §"logical clock" paragraph (the section Step 7's worklog labeled §2.7) — **revise** — pinned that a single clock advance that jumps past a fair's entire window moves the fair directly from `SCHEDULED` to `COMPLETED` — `workspace/implementation/services.py:599-603` (the added `SCHEDULED` + `today >= _end` branch in `fire_clock_transitions`).
- §book fairs paragraph (fair state machine sentence) — **revise** — same rule restated parenthetically where the fair lifecycle is defined, so both statements of the state machine agree — `workspace/implementation/services.py:598-611`.

**Step 7 diff triage:** the three test_suite items were pure fixture bugs (a missing `publish_cycle` import; SHIPPED-vs-PENDING setup errors where the PRD already pins the behavior — §3.8's PENDING→SHIPPED rule and §cancel-from-SUBMITTED PENDING requirement), so no PRD edits for them. Only the `fire_clock_transitions` implementation fix revealed a genuine PRD silence: the PRD described `SCHEDULED`→`ACTIVE` and `ACTIVE`→`COMPLETED` as if each advance fires one transition, but said nothing about a whole-window-skipping advance, which the implementation now completes directly.

**Per-edit pre-edit search log:**
- Edit 1 (clock paragraph): (a) subject = fair status transitions fired by clock advancement. (b) enumerated paths: `services.py:592-614` (`fire_clock_transitions` — the only clock-advance mutator of fair status, all three branches read); `services.py:96-97` (`active_fair_id` derivation — status-based, path-agnostic); `services.py:286-289` (`fair_overlap` recompute — reads status, unaffected by how completion was reached); `routes/fairs.py:74-97` (cancel/add-title gates on status); `routes/ops.py:45,53` (clock set + ops epoch both call `fire_clock_transitions`); `test_11_state_machines.py:149-167` (the fixed test). (c) wording written as an additive clause ("and when a single advance jumps past the entire window…") rather than replacing the existing `ACTIVE`→`COMPLETED` sentence, so the normal single-transition path remains pinned.
- Edit 2 (book fairs paragraph): (a) same subject. (b) same enumerated set; verified this paragraph is the second and only other PRD statement of the fair lifecycle. (c) used a parenthetical "(a clock advance that jumps past the entire window moves the fair directly from `SCHEDULED` to `COMPLETED`)" so the sentence's existing claims ("both transitions are fired by clock advancement", `active_fair_id` recompute) stay verbatim and consistent with `fire_clock_transitions`' `affected_schools` recompute for the jumped case.

## Step 9: Complete PRD — 2026-09-30T13:30:00.000Z

All 17 edits applied cleanly (25 paragraphs touched, matched 1:1 — pure in-place revisions, no sections added or removed).

## Summary

**Source vs output:** `PRD_FINALIZED.md` (348 lines, 53,539 chars) → `PRD_COMPLETED.md` (348 lines, 58,695 chars; +5,156 chars). Same section structure; every change is an in-paragraph insert or revision.

**Counts:** 17 changes total — 16 ambiguity-pins, 1 mismatch-revision.

**Changes (section — insert|revise — ambiguity|mismatch — what — impl):**

- §2.3 — revise — ambiguity — pinned pagination-param validation errors (`ERR_INVALID_REQUEST`), `id` tie-break on `created_at` sort, exact `has_more` formula — response.py:40-63, all list endpoints
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — services.py:33
- §2.5 — revise — ambiguity — clock set accepts Z/offset ISO forms normalized to UTC, unparseable → `ERR_INVALID_REQUEST`, responds 200 empty object; clock may move backward; fair transitions fire in created_at/id order and bump fair `version`; promotion status and `active_fair_id` are derived-on-read — ops.py:15-46, services.py:220-221, 94-102, 592-614
- §2.8 item 3 — insert — ambiguity — unmatched routes / unsupported methods surface as `ERR_NOT_FOUND` 404 — app.py:23-32
- §2.8 item 6 — insert — ambiguity — terminal lockdown detected before generic transition legality (terminal state → `ERR_ALREADY_TERMINAL`, never `ERR_INVALID_STATE`) — cycles.py:51-54, 120-123; orders.py:162-165; redemptions.py:60-63; donations.py:57-60
- §2.8 item 23 — revise — ambiguity — field-shape check includes integer/string type checks — common.py:35-48
- §3.1 — revise — ambiguity — suspend/reinstate bump the school's own `version`; reinstate from non-`RESTRICTED` → `ERR_INVALID_STATE`; `ERR_ENROLLMENT_EXISTS` checked before `enrolled_on` date parsing — schools.py:112-160
- §3.2 — insert — ambiguity — new teacher starts with all five points counters at zero; `full_name`/`email` must be strings — teachers.py:27-44
- §3.3 — revise — mismatch — non-positive `royalty_cap_cents` at acquisition is `ERR_INVALID_REQUEST` (field shape), never `ERR_ROYALTY_CAP_INVALID`, since accrued is 0 at creation — titles.py:36-39
- §3.4 — revise — ambiguity — `BONUS_POINTS` must not carry `bonus_points_per_unit`; `TITLE_INCENTIVE` must not carry `multiplier_bp`; absent kind-dependent fields treated as null; incentive `title_id` must reference an existing title — promotions.py:34-45
- §3.5 — revise — ambiguity — offering-add gates evaluated license → grade-band → format, after DRAFT-state check (CLOSED → `ERR_ALREADY_TERMINAL`, other non-DRAFT → `ERR_INVALID_STATE`); `fair_overlap` is derived, not stored — cycles.py:51-71, services.py:278-296
- §3.5 (close) — revise — ambiguity — close changes only the cycle's own `status`/`version`; `fair_count_used` drops mechanically because it counts only PUBLISHED-cycle offerings; no offering version bumps — cycles.py:143-156, services.py:178-188
- §3.6 — revise — ambiguity — line PATCH/DELETE on a `CANCELLED` line → `ERR_ALREADY_TERMINAL` before the open-order gate; Parent must create lines with `submitted_by` `PARENT_ONLINE` (else `ERR_FORBIDDEN_OWNERSHIP`), checked before the open-order gate — orders.py:115-152, 92-94
- §3.8 — revise — ambiguity — submit check order pinned: posture → cycle-published → ownership → non-empty → OCC — orders.py:157-183
- §3.8 — revise — ambiguity — cancel: `ERR_ORDER_HAS_SHIPPED` checked before ownership and clawback solvency; failed solvency check changes no state — orders.py:221-260
- §3.9 — revise — ambiguity — overlap check ignores CANCELLED fairs; fair-title add allowed on SCHEDULED or ACTIVE (COMPLETED/CANCELLED → `ERR_ALREADY_TERMINAL`); duplicate title at same fair → `ERR_INVALID_REQUEST` before the cap check; fair-title add bumps fair `version` and recomputes overlap school-wide; `active_fair_id` derived as earliest-created ACTIVE fair containing today — fairs.py:33-100, services.py:94-102
- §3.10 — revise — ambiguity — fulfill on OPEN → `ERR_DONATION_NOT_MATCHED`, on FULFILLED/CANCELLED → `ERR_ALREADY_TERMINAL`; fulfillment creates a single line (`student_name` "DONATION", `submitted_by` TEACHER); ad-hoc cycle keyed to clock's current month; offering for the title created (price 0) when missing; cancel of MATCHED → `ERR_INVALID_STATE`; `qty_matched` is null pre-match — donations.py:53-178
- §3.11 — revise — ambiguity — redemption create: shape check after `teacher_id` reference and `qty` shape validations; BOOK `title_id` must reference an existing title; cancel of CONFIRMED → `ERR_INVALID_STATE` — redemptions.py:18-47, 88-100
- §3.12 — revise — ambiguity — ops run sweeps expiry (teachers in created_at/id order) then re-fires clock transitions; expiry threshold is entry-date + 12 calendar months (day clamped to month end) ≤ clock date — ops.py:49-57, services.py:619-667

No test files, SCAFFOLD files, or worklog were read. No new sections added; no behavior invented beyond what `implementation/` exhibits.
