# Worklog — task_3021_connected_fitness_hardware_delivery_activation_subscription_entitlement

Scenario: Connected Fitness Hardware Delivery, Activation & Subscription Entitlement (Peloton): hardware order with in-home delivery, assembly and stair-carry surcharges, activation linking a device serial to a household membership with concurrent-user limits, membership pause, cancellation and reactivation with proration and content lockout, hardware financing origination with delinquency handling that must not disable safety functions, refurbished device resale with warranty reset, class content scheduling with live and on-demand libraries and instructor licensing windows, member metrics and leaderboard integrity, service dispatch for hardware faults with parts logistics

## Step 1: Create task directory — 2026-09-29T00:00:00.000Z

Task directory was pre-allocated by the caller at `./tasks/task_3021_connected_fitness_hardware_delivery_activation_subscription_entitlement/` with `workspace/` inside. No index computation performed; no other task_* directory created.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-29T00:00:00.000Z

Copied `./INSTRUCTION.md` to `./tasks/task_3021_connected_fitness_hardware_delivery_activation_subscription_entitlement/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-09-29T00:00:00.000Z

Clean lint on the final pass. All three artifacts are written.

### Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3021_connected_fitness_hardware_delivery_activation_subscription_entitlement/`):

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2605 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1384 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1464 |

**Counts (from the lint verdict block, pasted verbatim):**
```
  §1.5 endpoints declared:    91
  §1.1 entities declared:     11
  §1.8 instances scanned:     20
  §1.9 instances scanned:     34
  Calls scanned (§1.8+§1.9):  761
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

- **Entities:** 11 — Membership, HouseholdUser, Device, HardwareOrder, DeliveryAppointment, FinancingPlan, ServiceOrder, PartsInventory, ClassSession, ClassEnrollment, RefurbBatch
- **Endpoints:** 91 (89 business + 2 `/_` test-driving: logical clock and ops sweep)
- **State machines:** 10 — cyclic on Membership, HouseholdUser, FinancingPlan, ServiceOrder, DeliveryAppointment; parallel dimensions on Device; compound posture on Membership
- **Calculations:** 15 · **Validations:** 10 ordered rows · **Errors:** 38 · **Concurrency rules:** 5 (all OCC, all verified to take `expected_*_version` in `input:` and bump `<parent>.version` in `side_effects:`)
- **§1.8 queue-A instances: 20** — 9 rule blocks (dual_variant 2, combinatorial_formula 3, non_linear 2, cascade 2, priority_conflict 2, boundary 3, cross_entity 2, temporal_overlap 2, compensating 2)
- **§1.9 queue-B instances: 34** across 9 sections (entities 8, state_machines 4, calculations 2, validations 5, endpoints 4, errors 4, rbac 5, cross_cutting 2, consistency_model 1 — no `excluded_because:` stubs were needed because §1.9 was scoped to claims §1.8 does not exercise)
- **Profile:** Workflow orchestration + Temporal windowing, flat topology, layered with cascading side effects, dual-variant calculation, rate/threshold triggers, optimistic concurrency

**Notable design adjudications**

1. **Stair-carry/assembly fees vs. dual-variant totals.** The scenario requires both surcharges *and* a forward-looking-vs-chronological total. A stair-dependent fee inside the order total would degenerate the §1.8 dual-variant (the forward variant has no zone yet). Adjudicated: the nested-rounding stair formula survives as an **advisory value** exposed by `POST /fitness/delivery-quotes` (pinning round-per-term **935** against the forbidden round-at-end **939**), while `HardwareOrder.stair_carry_fee_cents` and `assembly_fee_cents` are pinned to 0 by explicit `SHIPPED_*` constants. Both totals then key only on the zone, making the divergence deterministic. Same leak, two legal fixes — deliberately iterable later.
2. **Second validation-priority pair.** Row 8 (`business_referential`) was extended with `ERR_REFUND_DISPUTE_DENIED` so the redemptive-credit path fails *dispute gate (8) vs purchase block (10)* — a genuinely different category pair from the first instance's *state (5) vs fiscal (10)*.
3. **`concurrent_limit_override`** was added because the fixed 4/10 tier defaults make the stream-ceiling boundary (Rule 6) unreachable. It also gives the global-constraint row (priority 9) an owned error.
4. **OCC fixtures always GET-then-write.** Creating household users/devices recomputes `Membership.posture`, which bumps `Membership.version` — so every OCC call in both design files is preceded by a `GET` capturing the parent version, never a creation-time capture.
5. **No random `id` in any decision.** Eviction tie-break is `created_at ASC` then `eviction_count DESC`; waitlist promotion is `enrolled_at ASC` then `created_at ASC`; parts ordering is `part_lot_key ASC` then `created_at ASC`. The §1.2.1 OCC section contains no forbidden race vocabulary (a grep audit of all three files is clean; two uses of "simultaneous" in entity descriptions were rewritten).
6. **Hardest single mechanic:** `order_totals` — a circular-looking total/finance-fee dependency with the evaluation order pinned (tier keyed on the *pre-finance* basis), which is what makes the forward variant land at 310800 and the chronological variant at 330550 for the identical order.

`worklog.md` and `workspace/` were already present in the task directory before my run; I left them untouched.

## Step 4: Generate PRD — 2026-09-29T00:00:00.000Z

PRD generation complete and verified.

### Output

`/home/ubuntu/github/CodingPRD/tasks/task_3021_connected_fitness_hardware_delivery_activation_subscription_entitlement/workspace/PRD.md` — 416 lines, ends at §5 with no audit footer.

### Section list

- **§1. Introduction** — 3 paragraphs (commercial model + hardest requirements framing)
- **§2. Global Specifications** — 12 domain-derived subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Household Identity/Ownership/Member Roles, 2.5 Stream Concurrency Ceiling & Eviction, 2.6 Posture & Device Entitlement Latch, 2.7 Hardware Safety Supremacy Over Financing, 2.8 Monetary Precision & Dual-Variant Order Total, 2.9 Temporal Windowing, 2.10 Certification Lineage Integrity, 2.11 Resource Addressability & Common Properties, 2.12 OCC
- **§3. Business Logic** — 10 subsections, lifecycle-and-role mixed grouping: 3.1 Quote→Installation, 3.2 Completion Cascades & Damage, 3.3 Minting/Linking/Activation, 3.4 Pause/Cancel/Reactivate, 3.5 Financing & Delinquency, 3.6 Service Dispatch & Parts Logistics, 3.7 Refurbishment & Warranty Reset, 3.8 Class Library & Licensing Windows, 3.9 Enrollment/Waitlist/Leaderboard Integrity, 3.10 Operations Sweep
- **§4. Endpoint Definitions** — 4-column table, 91 rows (matches scaffold endpoint count exactly)
- **§5. Error Code Catalogue** — 2-column table, 38 rows, same order as scaffold

### Hard contract reports

```
Field coverage check:
- entities[].fields: 113 required, 113 present, 0 missing
- endpoints[].request_body (input): 76 required, 76 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing  (scaffold defines none; path ids reach the PRD via §4 paths)
Status: PASS

Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 5 checked, 5 expressed (write_endpoint + occ_field + error_id + 412 all named), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed, 0 missing
- calculations[]: 15 checked, 15 fully expressed, 0 missing
- validations[] conditions: 28 error conditions checked, 28 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 91 endpoints checked, all expressed in narrative, 0 missing
- entities[].fields[] structured content: 113 checked, 113 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 transition groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 627
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: all 34 state enum values appear verbatim in backticks; all enum field values (including `ACTIVATED`, `PRIORITY_WARRANTY`, `PRIORITY_STANDARD`) present; all 5 role names spelled exactly; every `errors[].id` mentioned in §2/§3 narrative (not only the §5 table); §2.2 is byte-identical to `section-2.2-response-structure.md` (only divergence is the conventional `---` separator preceding §2.3); no fuzzy/approximating language anywhere; no banned OCC framings ("simultaneously", "first-writer-wins", etc.).

### Adjudications and deliberate choices

**Pinned verbatim from scaffold (no softening):**
- The two rounding-order hazards in the order-total and stair-carry formulas were stated as explicit prohibitions — "rounding the combined sum in one step produces a different, incorrect answer and must not be done" and the pinned pre-finance basis for the tier. These are the scaffold's own embedded warnings and are test-targeting, so I kept them sharp rather than paraphrasing them away.
- Eviction tie-break rendered as "creation timestamp ascending, with ties broken by `eviction_count` descending" (scaffold's prose says `created_at ASC` then `eviction_count DESC`; the sort-key comment's stray `status ASC` is constant inside the filter set and I did not promote it to a real ordering key).
- `safety_stock_qty` admission boundary pinned as "exactly that remaining reservable quantity is admitted; one unit beyond it is refused" — matching the scaffold's `<=` vs `+1` worked pair.
- `retry_count` boundary pinned as "two failures leave the plan current, and the third makes it delinquent."

**Adjudicated / left deliberately narrow:**
- **Order total tier boundary** — scaffold gives `BASIS_TIER_CENTS: 300000` alongside `basis_cents >= 300000 ? HIGH : LOW`. I expressed the constant as "at least 300,000 cents" and did not invent a separate worked example, leaving the tier selection to the threshold rule alone.
- **`expected_membership_version` on `resume` and `redeem-refund`** — these two fields appear in `endpoints[].input` but have no `concurrency_rules` entry. Rather than silently omitting them (Contract 1 would fail) or over-claiming an OCC rejection that the scaffold never defines, I stated them in §2.12 as accepted version fields that carry the caller's last-observed version, and explicitly separated them from the five guard-listed writes. This is the one place I had to choose between "field exists" and "rejection rule exists"; I kept them distinct.
- **`_run_ops` / `_clock/set_current_utc` panel** — the scaffold lists the clock endpoint as `applies_to` exclusion for `ERR_UNAUTHENTICATED` but still assigns it roles `[MembershipOwner, PlatformAdmin]`. I noted it in §3.10 as the only capability not requiring an authenticated header pair, without asserting it is fully unauthenticated.
- **`assembly_required`** — appears only as an optional input to the advisory quote and has no field/rule behind it, so it is named once in §3.1 with no behaviour attached rather than given invented semantics.
- **Terminal-guard coverage** — `ERR_ALREADY_TERMINAL` is stated in §3 for membership `TERMINATED`, batch `SOLD`, plan `PAID_OFF`, service order `RESOLVED`, session `ARCHIVED`/`CANCELLED`, and order `ACTIVATED`/`CANCELLED`, but I did not enumerate the scaffold's validation-rule prose about "membership resume" as a terminal-guard example in §3 because the citation in `validations[].applies_to` is generic; the state-machine transitions carry that rule instead.

One small correction made during self-check: the §3.1 heading had a typo ("Ofers" → "Orders") which was fixed before final count. No unresolved gaps remain — the final field-coverage diff is empty.

## Step 5: Generate unit tests — 2026-09-29T00:00:00.000Z

Done. Final summary of the work.

### Files written

**`test_helpers/` (1,646 lines)**
| file | lines |
|---|---|
| `__init__.py` | 19 |
| `types.py` | 463 |
| `api_client.py` | 459 |
| `api_errors.py` | 89 |
| `assertions.py` | 214 |
| `factories.py` | 160 |
| `constants.py` | 111 |
| `test_users.py` | 33 |
| `fixtures.py` | 498 |

**`test_suite/` (3,087 lines)**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 40 | — |
| `test_01_membership_lifecycle.py` | 777 | 21 |
| `test_02_order_delivery.py` | 386 | 12 |
| `test_03_service_and_parts.py` | 865 | 25 |
| `test_04_class_library.py` | 513 | 15 |
| `test_05_refurbishment.py` | 272 | 9 |
| `test_06_auth_and_roles.py` | 274 | 8 |

### Counts

- **Total tests: 90** (all collect cleanly; `py_compile` passes; none skip/xfail)
- **Queue A (Difficulty): 50 tests across 20/20 instances**, every instance at ≥2
- **Queue B (Corner): 40 tests across 34/34 non-stub instances**, every instance at ≥1

Audits run mechanically and passing: exactly one `Design:` tag per test, every tag resolving to a real yaml `name:`; every docstring ending on its tag line; every docstring carrying a ≥8-word span that survives a literal normalized substring match against `workspace/PRD.md`; no `pytest.mark.skip`/`skipif`/`xfail`; no occurrence of "scaffold" in generated code.

### Instances SKIPPED

One instance group, under the `concurrency-occ` silence pattern — **`membership_activation_stale`, `membership_pause_stale`, `membership_cancel_stale`, `membership_reactivation_stale`, `device_link_stale`** (`SCAFFOLD.yaml` §1.2.1, not in either design index). Reason: **non-unique derivability**. §2.12 names the version fields and the two 412 error ids, but §2.11's "`version` is an integer that begins at its initial value" never fixes *that* value, so what a correct request supplies is not pinned; two PRD-only readers can disagree, and any test asserting a specific expected version would fail a faithful implementation. No queue-A or queue-B instance was skipped, so there is no gap in either index's coverage target.

Two adjacent observations, not test gaps: `test_07_concurrency_occ.py` was written and then deleted once this skip decision was made; and `ERR_PART_MISMATCH_SAFETY` has PRD prose but no design-index instance, so per "no freelance test discovery" it was left untested.

## Step 6: Generate implementation — 2026-09-29T00:00:00.000Z

Implementation complete and verified. Final report:

### Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3021_connected_fitness_hardware_delivery_activation_subscription_entitlement/workspace/implementation/` (21 files, 5,073 lines total):

| Lines | File |
|---:|---|
| 9 | `start.sh` (executable, guarded dep install, `exec python3 app.py`) |
| 1 | `requirements.txt` |
| 76 | `app.py` — Flask entry, API/HTTP error handlers, 5xx envelope guard |
| 67 | `clock.py` — logical clock, default `2026-09-01T00:00:00Z`, never real time |
| 275 | `db.py` — in-memory store, id/token minting, half-open interval + lineage helpers |
| 109 | `errors.py` — all 38 error ids with scaffold HTTP statuses |
| 75 | `response.py` — exact `meta`/`response_type`/`data` envelope |
| 1002 | `routes/api.py` — all 91 routes |
| 438 | `services/common.py` — auth, payload validation, view projections |
| 507 | `services/calc.py` — all 15 calculation rules |
| 393 | `services/classes.py`, 394 `membership.py`, 303 `service_order.py`, 279 `delivery.py`, 235 `financing.py`, 191 `refurb.py`, 187 `order.py`, 171 `household.py`, 171 `ops.py`, 124 `device.py`, 64 `parts.py` |

### Endpoint count
**91 / 91 declared endpoints implemented** — verified by diffing `app.url_map` against `SCAFFOLD.yaml §1.5` with path-param names normalized: zero missing, zero extra.

### Verification performed
- Full lifecycle smoke run (membership → device → order → delivery → link → activate → pause/resume/cancel/reactivate, financing delinquency, dispatch/parts logistics, class library, refurbishment resale) — all paths exercised green.
- 49-check error-path/RBAC/edge probe: **49 pass, 0 fail** (401/403/400/404/412/409 matrix, OCC, ownership, safety-cap, part boundaries, dispute-gate ordering, eviction discipline, waitlist).
- **Restart isolation:** 3 sequential `bash start.sh` reboots each ready in 0.56–0.63 s; a fresh boot returns `total_count: 0` for all 11 entity collections. No SQLite/pickle/file I/O anywhere; no `seed_*`, no `db.STORE` population at import.
- `pyflakes` clean (one intentional re-export in `routes/__init__.py`); all readings confined to the three permitted files.

### Ambiguous PRD passages and resolutions
1. **Stair-carry/assembly fees vs. the order total** — PRD §2.8/§3.1 pin `HardwareOrder.stair_carry_fee_cents` and `assembly_fee_cents` to 0 (`SHIPPED_*` constants) while stating the taxed round-per-term formula. Resolved: the formula is exposed **only** through `POST /delivery-quotes`; order totals key solely on the zone. Verified advisory values: 3 flights/elevator → 812, 4 flights/no elevator → 1332, cap → 2500.
2. **Integrity benchmark: scheduled end vs. session duration** — §3.9 says "the session end measured in whole seconds floored" but also `benchmark_seconds` and ties the flag to "one second past the scheduled end." Taken literally, the flag is unreachable for any output swallowing a whole session. Resolved: `STRICT_BENCHMARK` scores the **scheduled length** (`floor(ends_at − starts_at)`), `INDULGENT_BENCHMARK` that length + 600. This makes the flag reachable and keeps the two variants observably different (`output_points: 1801` → strict 0/flagged, indulgent 2/unflagged; Stripe durations give 130 for a 13-minute window, matching the alternate reading).
3. **`REFURB_*` SKUs are "only legal on a resale-originated device"** — the moderate-degradation rule that forces non-performance resales to `ROWER` (per the scaffold's own descriptions) conflicts with the `hardware_sku` enum, which excludes ROWER→REFURB_ROWER. Resolved: minting a `REFURB_*` device directly is refused with `ERR_INVALID_REQUEST`; a `performance_resale_enabled == false` batch mints `ROWER`; an enabled batch maps `BIKE→REFURB_BIKE`, `TREAD→REFURB_TREAD`, and **keeps the source SKU otherwise** rather than emitting an illegal value. Same-SKU list prices are pinned in `db.SKU_LIST_PRICE_CENTS` (the scaffold never enumerates them) so grade pricing is reproducible.
4. **Unspecified repair crew code** — §3.6 describes repair-window overlap "for the crew" but no endpoint accepts a crew for service orders. Resolved: `technician_crew_code` is an internal field (never required, never serialized as a request input); `schedule` checks overlap only when a crew is named, so two orders both with no crew do not self-collide.
5. **Waitlist promotion condition** — §3.9 states promotion once "the count sits below capacity," where `live_enrollment_count` counts `ENROLLED` **and** `WAITLISTED`. Implemented literally: dropping one seat from a full session leaves count == capacity, so the waiter stays `WAITLISTED`; promotion fires only once a `COMPLETED`/`DROPPED`/`EXPIRED` cascade removes a counted row.
6. **Priority collisions** — resolved strictly from the scaffold's priority numbers, which §1.4 deliberately pins against intuition. `pause` checks window validity (7) before the unpaid-financing block (10); `redeem-refund` checks the dispute gate (8) before the purchase gate (10); `publish` checks licence containment (7) before instructor overlap (7) and creation checks instructor overlap (7) before source eligibility (8).
7. **`expected_membership_version` on resume / redeem-refund / start-stream** — §2.12 declares these accept a version without belonging to the guarded set. Resolved: compared when supplied (mismatch → the stale error), but not required. Order placement and `_run_ops` bump the membership version, as the OCC rule's premise ("a derivative recompute has legitimately moved the membership forward") and the worklog's note that `Membership.posture` recomputes bump the version require; `start-stream` deliberately does **not** bump, preserving the scaffold's eviction precondition `active_user_count + 1 > limit`.
8. **`REACTIVATED` settling** — no endpoint declares the automatic `REACTIVATED → ACTIVE` step. Resolved: the ops sweep carries it, matching §3.4's "on the next system step it settles automatically into `ACTIVE`."
9. **`order_totals` re-run trigger** — the scaffold's own CHRONOLOGICAL prose ("For any non-METRO zone the two variants disagree") implies the capture-time recompute fires only when the zone is not METRO. Resolved: the fee and captured total are always re-derived, but the forward value is never overwritten; for METRO the two agree, satisfying the scaffold's example (`subtotal 300000` → 330000 forward, 335280 chronological for SUBURBAN).

## Step 7: Run tests and iterate — 2026-09-29T00:00:00.000Z

Suite is green. Both 8-round parallel sweeps passed 90/90 with zero union failures, and I've left the 8 results.json files as the evidence.

### Summary

**Iterations run:** 2 stability sweeps (plus targeted single-test runs for diagnosis). Initial sweep: 8 rounds, 58–59/90 passing, 33-test union of failures. Final two sweeps: 8/8 rounds at 90/90, zero union failures.

**Tests deleted:** 1
- `test_platform_admin_is_denied_the_student_work_it_does_not_own` (test_04) — asserted a **scaffold-only rule**. PRD §4's endpoint table verbatim lists PlatformAdmin as permitted on `POST /fitness/class-enrollments/{enrollmentId}/complete` ("MembershipOwner, PlatformAdmin"), and PRD §2.1 says opaque roles are never ownership-compared. The scaffold's RBAC matrix contradicted its own endpoint table; the test encoded the scaffold side. Replaced with `test_the_platform_admin_can_complete_a_workout_on_the_shared_surface`, which traces to the PRD endpoint table.

**Fixes to `test_helpers/`:**
- `fixtures.py` — added `decommission_device()` (drives a device to DECOMMISSIONED via the PRD §3.4 cancel-then-sweep cascade, anchored on the real `billing_cycle_start_at`), `setup_refurb_source()`, `setup_buying_household()`, and `create_service_order()`. Reworked `setup_refurb_chain` to source a DECOMMISSIONED seed and to sell into a separate live buyer (the cancelled seed household is FROZEN and correctly refused under the PRD §3.7 posture gate).

**Fixes to `test_suite/` (all assertions/fixtures made *more* PRD-faithful; no assertion weakened, no skip/xfail):**
- `test_02` — monetary tests carried copy-pasted wrong numbers. Corrected to the PRD formula's outputs (`delivery_charge` RURAL/TREAD = 4800 not 9000; `stair_carry_surcharge` = 541/1082/1353 for the round-half-up-per-term rule, not 542/813/1084 ceil values; forward quote 310800, captured 330550/330880). Boxed the early-start case to schedule first (PRD: start moves `SCHEDULED`→`IN_PROGRESS`).
- `test_01` — `installments_late` boundary on the first DELINQUENT→CURRENT cure is 1 (PRD §3.5: one cure increments once), removed the unpinned `version == 1` default (PRD §2.11 says only "begins at its initial value"), corrected RURAL order totals, and made the decommissioned-repair setup reserve a part first so the decommission clause is the sole failure.
- `test_03` — reservation boundary tests now exercise a single reservation of exactly `on_hand - safety_stock` (the multi-reserve form they used hits `PART_RESERVED`, a state PRD does not admit for reservation); stream-ceiling test reordered so the boundary is crossed exactly once; empty-shelf test split into the cosmetic (parks, `ERR_PART_INSUFFICIENT`) and safety-critical (never parks) branches.
- `test_04` — 601 points under INDULGENT is legitimately below the one-hour bar (3600+600); corrected to 4201; paid one installment before recording a failure (PRD requires a CURRENT plan).
- `test_05`/`test_06` — all refurb sources now DECOMMISSIONED/resale-originated per PRD §3.7; chain-depth-bound test builds a depth-4 source (the depth-3 source is admissible under the verbatim `depth > 3` rule).

**Fixes to `implementation/`:** 1
- `services/service_order.py` — `schedule()` admitted only `PART_RESERVED`/`DISPATCH_PENDING_PART`. Added `DISPATCHED` to the schedulable set and changed the no-part gate to key on `part_id is None and fault_class != SAFETY_CRITICAL`. PRD §3.6 requires a safety-critical repair to proceed without a part, and a refused safety-critical reservation correctly never parks the order (it stays `DISPATCHED`), so it must remain schedulable. No PRD-required check was removed; the cosmetic `ERR_PART_REQUIRED_FOR_SCHEDULING` and decommission/state gates are intact.

## Step 8: Finalize PRD — 2026-09-29T00:00:00.000Z

Both edits applied. Verification complete: line counts unchanged.

### Result

**Line counts:** `PRD.md` 415 lines → `PRD_FINALIZED.md` 415 lines — **0.00% delta** (2 single-line edits, no structural changes).

### Changes

- **§2.11 Resource Addressability** — revise — `version` "begins at **its initial value**" → "begins at **zero**" — `implementation/db.py:91` (`row["version"] = 0`).
- **§3.6 Service Dispatch and Parts Logistics** — revise — "**A `DISPATCH_PENDING_PART` order** is schedulable only when its fault class is `SAFETY_CRITICAL`" → "**An order with no part reserved** is schedulable only when its fault class is `SAFETY_CRITICAL` (whether the order sits in `DISPATCH_PENDING_PART`, or remains in `DISPATCHED` because a safety-critical reservation was itself refused)" — `implementation/services/service_order.py:28` (`SCHEDULABLE_STATES`), `:207` (`part_id is None and fault_class != SAFETY_CRITICAL` gate).

### Per-edit pre-edit search log

**Edit 1 — §2.11 `version` initial value**
- (a) Subject: the initial value of the common `version` field.
- (b) Enumerated/read every path that creates or reads `version`: `db.py:77-94` (`create` — the only mint site, all 11 collections), `db.py:116-127` (`touch`, the only increment site), `services/common.py` (all 11 `*_view` projections that expose it), plus every version comparison — `membership.py:88-98`, `device.py:60-66`, `order.py:113-122`, `household.py:91-103`. Confirmed no path overrides it at creation to any value other than 0.
- (c) Kept the rest of the sentence untouched ("begins at its initial value **and is incremented by one on every mutation**") so the increment clause still holds on all enumerated paths; replaced only the 3-word initial-value clause with the concrete literal. Type unchanged (integer).

**Edit 2 — §3.6 schedulable-set**
- (a) Subject: the exact status set from which a repair window may be booked (the `SCHEDULABLE_STATES` concept).
- (b) Enumerated/read: `service_order.py` `schedule()` (the state gate `:182`, the no-part gate `:207`), `RESERVABLE_STATES`/`RESERVABLE` path `reserve_part` (`:96-146`, which sets `PART_RESERVED` or parks `DISPATCH_PENDING_PART` on `ERR_PART_INSUFFICIENT`, or leaves `DISPATCHED` on `ERR_PART_SAFETY_STOCK` for safety-critical), `fail_repair` → `SCHEDULED`, `resolve`'s parallel `part_id is None and fault_class != SAFETY_CRITICAL` gate (`:253`), `_new_service_order` (`DISPATCHED`), `release_reservation` → `DISPATCH_PENDING_PART`, `start_repair`, and the scheduler callsite `routes/api.py:689-694`. Cross-checked against `test_suite/test_03` cases that exercise both the `DISPATCH_PENDING_PART`-safety branch and the `DISPATCHED`-safety branch.
- (c) Widened the subject from "a `DISPATCH_PENDING_PART` order" to "an order with no part reserved," and parenthesized the two concrete ways that state arises, so the sentence now covers `DISPATCHED` (safety-critical reservation refused at `ERR_PART_SAFETY_STOCK`) and `DISPATCH_PENDING_PART` (cosmetic parking) alike. The following sentence ("a cosmetic order with no part reserved is refused…") and the `ERR_TEMPORAL_OVERLAP`/`safety_functions_maintained` clauses were left verbatim, so the gate's behavior on every *other* enumerated path is unchanged. Under-determined enough (loose "no part reserved") that it does not falsely exclude any off-site branch.

### Deliberately left unchanged (PRD silence, but NO-NEW-MISMATCH disfavors narrowing)

- The Step 7 `fixtures.py` reworks (`decommission_device`, `setup_refurb_source`, `setup_buying_household`, `setup_refurb_chain`) are pure test-fixture bugs, not PRD silences about product behavior — the PRD already pins the `DECOMMISSIONED`/resale-eligibility and separate-live-buyer rules (§3.7). No edit.
- The delete of `test_platform_admin_is_denied_the_student_work_it_does_not_own` reveals a scaffold/PRD contradiction; the PRD's §4 table and §2.1 opaque-role rule already determine the retained behavior. No edit.
- Profile-name conventions revealed by the corrected test numbers (`BIKE`/`TREAD`/`ROWER`/`REFURB_*` = **standard** vs. `performance_resale_enabled: false` minting = "performance model", §3.7) and the NewSale/REFURB_* mint SKU map (§3.3 "a refurbishment SKU is only ever legal on a device that originated as a resale"). These are genuine silences (`db.SKU_LIST_PRICE_CENTS` is also entirely absent from the PRD), but any definition would attach "performance" to a subset of the five SKUs, contradicting §3.7's `performance_resale_enabled: true` + grade `A` batch — so per the NO-NEW-MISMATCH rule I left the §3.7 prose under-determined rather than introduce a false universal. (Flagged here for the caller since §3.7's minted-SKU choice is the largest remaining implementation-pinned behavior the PRD does not fix.)
- The `test_04` numeric corrections (601→4201) and the `test_01`/`test_03` boundary reorderings revealed no behavior the PRD fails to determine; no edits.

## Step 9: Complete PRD — 2026-09-29T00:00:00.000Z

I've completed the alignment pass. Here is the summary.

### Output
`/home/ubuntu/github/CodingPRD/tasks/task_3021_connected_fitness_hardware_delivery_activation_subscription_entitlement/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, edited in place).

- **Source** `PRD_FINALIZED.md`: 415 lines / 80,679 chars
- **Result** `PRD_COMPLETED.md`: 415 lines / 87,749 chars
- **Delta**: 0 net lines (all edits are inline inserts/rewrites within existing paragraphs) / **+7,070 chars**
- **Counts**: 23 ambiguity-pins, 6 mismatch-revisions (29 edits across 27 edited prose passages; no new sections/paragraphs)

### Changes (one per edit)

**Mismatch-revisions**
- §2.7 — revise — mismatch — the PRD claimed "any request that would clear `safety_gate_open`… is refused with `ERR_SAFETY_DISABLE_FORBIDDEN`", but no endpoint ever clears the gate or latches safety; reworded so the gate is creation-opened and re-asserted true on every recompute and the error is reserved as the guard — `services/calc.py:276-291`, `services/membership.py:58`, `services/financing.py:72-225`
- §2.8 — revise — mismatch — tier basis said "subtotal plus delivery legs plus…"; impl sums the delivery **fee** — reworded to "the delivery fee component" — `services/calc.py:119-143`
- §2.11 — revise — mismatch — `updated_at` was left unqualified; pinned to second precision — `clock.py:28-32`
- §3.5 — revise — mismatch — recovery of a `DELINQUENT` plan was stated as always returning it to `CURRENT`; added that the term's final payment settles straight to `PAID_OFF` — `services/financing.py:145-157`
- §3.7 — revise — mismatch — `library_availability` was described as flipping "once a terminal state of the source device makes the batch un-listable"; pinned it as recomputed and `UNAVAILABLE` once the batch leaves its three-state window (i.e. once sold) — `services/refurb.py:188-191`
- §3.10 — revise — mismatch — "the batched form of four rules" understated the sweep; reworded to the time-dependent rules — `services/ops.py:135-160`

**Ambiguity-pins**
- §2.1 — insert — ambiguity — ownership comparison applies to single-resource and parent-nested reads, not to the top-level/device/order/part/session lists — `services/common.py:64`, `routes/api.py:157-167,231-245,256-266`
- §2.2 — insert — ambiguity — absent/empty/unparseable body is treated as `{}` and judged by the operation's own rules — `routes/api.py:56-68`
- §2.5 — insert — ambiguity — eviction tie-break on equal `created_at` selects the more-evicted member first (`-eviction_count`) — `services/calc.py:368-381`
- §2.10 — insert — ambiguity — depth is an edge count from the source (0 for a root), and a missing parent ends the lineage rather than erroring — `db.py:254-275`
- §2.12 — insert — ambiguity — start-stream also accepts and compares `expected_membership_version` (optional), alongside resume/redemption — `services/household.py:78-103`
- §3.1 — insert — ambiguity — `captured_total_cents` stays null until the visit completes — `services/order.py:52-53`
- §3.1 — insert — ambiguity — appointment creation requires the order in `PLACED` (`ERR_INVALID_STATE`), a start-before-end window (`ERR_INVALID_REQUEST`), and stamps the order's `device_id` — `services/delivery.py:53-89`
- §3.1 — insert — ambiguity — scheduling with start ≥ end yields `ERR_INVALID_REQUEST` — `services/delivery.py:104-108`
- §3.2 — insert — ambiguity — the auto `DAMAGED` service order opens `DISPATCHED`, records the parent order as `order_id`, carries no diagnosis note, leaves the device lock untouched — `services/service_order.py:91-93,47-65`
- §3.3 — insert — ambiguity — a duplicate serial is `ERR_INVALID_REQUEST`; membership comes from the path, not the body — `services/device.py:31-43`
- §3.3 — insert — ambiguity — a `DELIVERED` order with a null `device_id` is never closed by activation — `services/order.py:83-85`
- §3.5 — insert — ambiguity — `monthly_installment_cents` tracks the next amount owed (first → base → remaining total) — `services/calc.py:200-220`
- §3.5 — insert — ambiguity — a `DEFAULTED` cure beyond 30 days is `ERR_INVALID_STATE`; a cure after the term was already collected settles to `PAID_OFF` without adding an installment — `services/financing.py:105-123`
- §3.6 — insert — ambiguity — a dispatch `order_id` must match the device's membership (`ERR_DEVICE_NOT_ON_MEMBERSHIP`); an owner may report only on its own device — `services/service_order.py:79-85`, `routes/api.py:643-647`
- §3.6 — insert — ambiguity — release is addressed at the reserved part row (unrelated part → `ERR_RESOURCE_NOT_FOUND`); an over-quantity release is clamped — `services/service_order.py:156-171`
- §3.7 — insert — ambiguity — a resale-originated source is counted at depth 1, not 0 — `services/refurb.py:59`, `db.py:254-275`
- §3.7 — insert — ambiguity — pinned `SKU_LIST_PRICE_CENTS` (BIKE 250000, TREAD 350000, ROWER 300000, REFURB_BIKE 150000, REFURB_TREAD 210000); certify's `certification_grade` is optional (defaults to the open-time grade) — `db.py:21-27`, `services/refurb.py:74-88`
- §3.7 — insert — ambiguity — minted-SKU map: flag true → `BIKE`→`REFURB_BIKE`, `TREAD`→`REFURB_TREAD`, any other source keeps its SKU, `REFURB_*` never minted directly; flag false → standard `ROWER`; plus the standard-vs-performance naming convention — `services/refurb.py:143-149`
- §3.7 — insert — ambiguity — warranty reset requires `ACTIVE` (`ERR_INVALID_STATE`) before the `RESALE` check — `services/device.py:102-106`
- §3.8 — insert — ambiguity — publishing a non-`DRAFT` session is `ERR_INVALID_STATE` (terminal → `ERR_ALREADY_TERMINAL`) — `services/classes.py:75-81`
- §3.9 — insert — ambiguity — `benchmark_variant` defaults to `STRICT_BENCHMARK`; `output_points`/`completion_pct` default to 0 — `services/classes.py:347-352`
- §3.10 — insert — ambiguity — the sweep also advances `PUBLISHED`→`STREAMING` and settles `REACTIVATED`→`ACTIVE` — `services/ops.py:145-146,8-30,76-89`
- §4 — insert — ambiguity — the membership summary returns its aggregate plus a `devices` array — `routes/api.py:216-225`

### Notes
- Checked and found **already consistent, no change needed**: `version` starting at 0 (§2.11, per the Step-8 patch in `PRD_FINALIZED.md`); `db.SKU_LIST_PRICE_CENTS` had no prior PRD mention (now pinned); the §3.6 schedulable-states patch was already correct.
- Two candidate items were deliberately **not** changed after checking impl paths: household-user `email` uniqueness is claimed by PRD §2.4 but never enforced (`services/household.py` only validates presence) — left alone since adding a uniqueness rule would invent behavior impl lacks; and the §3.6 `shipping_order_key` tie-break helper (`services/parts.py:56`) is unused by any endpoint, and the existing prose already calls it "a side note", so it remains accurate.
- One wording pitfall was caught and corrected mid-pass: my first §2.1 insert implied all §4 list reads are unscoped, which is false — nested `memberships/{id}`/`household-users/{id}` reads do carry the owner check — so it was rewritten to scope the claim correctly.

### Orchestrator follow-up edit (post-Step-9)

The subagent's "deliberately not changed" item above was re-examined by the orchestrator and judged a genuine mismatch, not a silence, so it was patched:

- **§2.4 Household Identity/Ownership/Member Roles** — revise — mismatch — "a unique `email`" → "an `email` … The `email` is required and stored as supplied; no uniqueness constraint is enforced on it." — evidence: `services/household.py:21-37` (only `field_str(presence)` validation, no unicity scan), and `grep -rn "ERR_EMAIL\|already.*email\|duplicate" workspace/implementation/` returns zero hits, confirming the 38-error catalogue has no duplicate-email error id. Rationale: the subagent's own stated reason for leaving it (it would invent behavior impl lacks) applies to *adding* a uniqueness rule; the PRD already claimed one, so the PRD — not the impl — is the outlier. A fresh PRD-only implementer would have added a check the reference lacks, diverging from `implementation/`.

Final verification after the follow-up edit: `PRD.md` 415 / `PRD_FINALIZED.md` 415 / `PRD_COMPLETED.md` 415 lines. Final 8-round sweep evidence retained at `workspace/implementation/results.{1..8}.json`, all `passed == total == 90`.