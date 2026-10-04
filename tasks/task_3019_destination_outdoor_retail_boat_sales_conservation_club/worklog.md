# Worklog — task_3019_destination_outdoor_retail_boat_sales_conservation_club

## Step 1: Create task directory — 2026-09-29T00:00:00.000Z

Task directory `./tasks/task_3019_destination_outdoor_retail_boat_sales_conservation_club/` was pre-allocated by the caller with `workspace/` already present. No index computation performed; no other `task_*` directory created. `workspace/` verified empty and ready for generated artifacts.

## Step 2: Generate scaffold artifacts — 2026-09-29T15:29:00.000Z

Note: the first subagent attempt was killed by the harness with `API Error: Claude's response exceeded the 32000 output token maximum` and wrote no files. Re-spawned with explicit chunked-write mechanics (Write first chunk, append subsequent chunks via quoted heredoc at ≤400 lines per tool call); that attempt completed successfully.

All three scaffold artifacts are generated and the lint is clean. No sibling tasks were read (verified: I only ever touched the skill directory and this task's own directory).

### Deliverables

`/home/ubuntu/github/CodingPRD/tasks/task_3019_destination_outdoor_retail_boat_sales_conservation_club/`
- `SCAFFOLD.yaml` (3242 lines) — §1.0–§1.7, no `scaffold_difficulty_design:` / `scaffold_corner_design:` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1386 lines) — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` (2737 lines) — single top-level `scaffold_corner_design:`

### Counts

| §1.1–§1.7 | |
|---|---|
| Entities | 19 |
| State machines | 12 (55 transitions) |
| Calculations | 16 |
| Validations | 41 priority rows |
| Endpoints | 111 |
| Error codes | 39 |
| Roles (all with `identity:`) | 18 |
| Concurrency rules | 2 (both OCC on `version`, 412) |

§1.8: 9 rules × 2 instances = **18**. §1.9: **57** instances across 9 sections (entities 10, state_machines 8, calculations 9, validations 11, endpoints 5, errors 6, rbac 3, cross_cutting_layers 5, difficulty_overlap 4 `excluded_because:` stubs) plus 4 excluded stubs. Every FK has reverse-reachability; 729 call objects lint clean.

Difficulty: `expert` — primary archetype compliance/audit (permit remittance + title work with segregation of duties), secondary posture-driven gating (`Store.attraction_posture` gates every session transition), topology `graph`, `parallel` state shape, `saga` consistency. All nine §0.5 rules met with distinct differentiation (longest cascade depth 6; Rule 2 spans modes (a) and (b); Rule 3 uses a cyclic revert on BoatDeal and a fork-join on AttractionSession; Rule 8 contrasts aggregate cumulative-capacity windows against buffered bay exclusivity).

### Design adjudications

1. **Remit remittance variance sign.** Pinned so `interpretative_gross_cents - gross_fee_cents >= 0` always (the agency revises fees upward), giving Rule 1 two dual-variant instances with opposite polarity (permit `+1` vs boat `+5075`).
2. **Cascade-vs-recompute ambiguity.** Rather than hand-waving, `deal_fee_and_tax_relay` is an explicit `circular_ordered` single-pass with the evaluation order pinned (contract price settled first, then fees), and `boat_deal_contract_price` applies a rounding gate before the trade-credit cap.
3. **Auto-delivery is deferred, not nested.** Every "would auto-transition" side effect is worded as *"auto-delivered on the next call against it (BoatDeal is not terminal)"*, so OCC version reads are deterministic.
4. **Order-independent test recipes.** Because `setup_api_calls` and `trigger` are step *types* the caller may interleave, every cascade-bearing recipe pins **read pseudo-calls** (a `GET` `call:` with no `as:`) at each snapshot boundary and its asserts name the read position (R0/R1, "before the correction", etc.). A header comment in each design file states this convention for the downstream unit-test-generator.
5. **OCC endpoints.** Both `concurrency_rules` write endpoints carry `expected_*_version` in `input:` and bump the parent version in `side_effects:`; `POST /stores/{store_id}/permit-sales` necessarily takes `permit_remit_batch_id` as a body field to make that rule expressible.
6. **Two new §1.5 endpoints** were added via the priority ladder (business endpoints, not `/_` shims): `PUT /stores/trade-in-appraisals/{id}` and `PUT /stores/{store_id}/service-intakes/{id}`, to make `ERR_TYPE_IMMUTABLE` reachable.
7. **Cleanups for enum/consistency:** removed dead enum members (`BoatUnit.status=CONSIGNED`, `funding_status=VOIDED`); added a `CORRECTED → CORRECTED` self-loop so a batch can take several correction rounds; removed `BoatDeal.balance_due_cents` from the trade-credit formula (it now excludes `settlement_variance_cents` by design); retuned `DWELL_CRITICAL_MINUTES` to 30 and the frozen-vs-restricted capacities to 100/140 so the ordered posture if-chain is observable.
8. **Deferred time-dependent reachability** (documented in `setup:` prose rather than papered over): reaching `ERR_NO_SHOW_STRIKE_LIMIT` needs three prior no-shows, and `ServiceIntake → ABANDONED` needs a 90-day pickup window; both are reachable with the existing `/_clock` + `ops-run` endpoints using additional chains beyond the two-instance minimum.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-29T15:30:52.769Z

Copied `./INSTRUCTION.md` → `./tasks/task_3019_destination_outdoor_retail_boat_sales_conservation_club/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD document — 2026-09-29T15:47:00.000Z

PRD generated and verified. Final report:

### Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3019_destination_outdoor_retail_boat_sales_conservation_club/workspace/PRD.md` — **468 lines**, built incrementally (one Write + four heredoc appends + two targeted patches). The difficulty/corner-design scaffolds were never opened.

### Section list

- **§1 Introduction** — 3 paragraphs, angled from the destination-store dwell economics, the compliance spine (permit counter + title work), and the club programme.
- **§2 Global Specifications** — 11 domain-derived subsections (not the template pattern): 2.1 RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Store Clock and the Ops-Run Checkpoint, 2.6 Nested Path Resolution and the Priority Order of Failure, 2.7 The Attraction Posture Gate and the Dwell Budget, 2.8 Monetary Precision and Rounding Discipline (with **2.8.1**, a full 16-calculation sub-table), 2.9 Segregation of Duties, 2.10 Optimistic Concurrency Control, 2.11 Validation Order and Deterministic Failure.
- **§3 Business Logic & Workflows** — 9 subsections grouped by floor/process ownership, not by the standard lifecycle template: 3.1 Destination Floor (venues, sessions, dwell budget), 3.2 Conduct on the Floor (waivers, no-shows, strike decay), 3.3 Store Calendar, 3.4 Boat Dealership (contracting/funding/four dimensions), 3.5 Trade-Ins, Title Work and the Cyclic Revert, 3.6 Rigging, Service Orders and Delivery Handover, 3.7 Permit Counter and the State Remittance Ledger, 3.8 Conservation Club, 3.9 Clock and Ops-Run Sweep.
- **§4 Endpoint Definitions** — 111 rows, 4 columns.
- **§5 Error Code Catalogue** — 39 rows, 2 columns.

### How information scattering was handled

- **Parameters split across subsections.** `expected_deal_version` is introduced in §3.4 (contracting) and reused in the funding/settle narrative; `rm_cross_check_code` appears in §2.9 (duty separation) and again in §3.6 (release gate); `waiver_id` is defined in §3.2 but gates both venue sessions and the §3.6 boat-orientation release; `deposit_cents` threads §3.4 (applied at contracting), §3.6 (intake floor) and §3.7 (nothing). `to_iso8601` lives only in §3.9's capability description.
- **Constants embedded in business context with unit conversion.** 95 000 → "ninety-five thousand cents"; 725 bps → "seven hundred twenty-five basis points"; the no-show quarter is stated as "half a strike for each elapsed ninety-day quarter" rather than as `0.5 * quarters_elapsed`; the 90-day abandonment window, the 15-minute bay buffer, the 21-day curing extension and the 30-minute critical dwell band all appear only inside the sentence describing the workflow.
- **Calculations deliberately relocated.** Rather than leaving the 16 formulas in one computation chapter, the three highest-value ones are also re-derived as narrative in the workflow that triggers them: `boat_deal_contract_price` in §3.4, `permit_fee` in §3.7, `trade_in_credit` in §3.5, `no_show_strike` in §3.2. §2.8.1 carries the precise operand-for-operand form; §3 carries the business reading.
- **Relationships via action, no foreign keys.** Foreign references are always phrased as "a payload containing the `procedure_id`"-style actions ("naming the `member_id` and the `boat_unit_id`", "the work order whose `boat_unit_id` is this unit").

### Hard contract reports

```
Field coverage check:
- entities[].fields: 127 required, 127 present, 0 missing
- endpoints[].request_body/input: 93 required, 93 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 41 checked, 41 expressed in prose (4 pinned cross-band orderings stated explicitly in §2.11), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_booking_version→ERR_STALE_VERSION/412, expected_remit_batch_version→ERR_STALE_VERSION/412, plus expected_deal_version on all four deal writes), 0 missing
- state_machines[].transitions: 55 across 12 machines checked, 55 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed (all 16 constant tables audited), 0 missing
- validations[] conditions: 41 checked, 41 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 136 + 147 checked, expressed, 0 missing
- entities[].fields[] structured content: 177 fields (76 with defaults/source metadata) checked, reconstructible, 0 missing
- sibling-branch symmetry: 12 groups checked (approve/decline, promote/cancel, issue/reject, fund/refund, publish/cancel/complete, etc.), equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 720
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verified invariants: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 39 error IDs appear in §2 or §3 (not only §5); all 18 role names and every enum/state string appear in backticks; no fuzzy or approximating words anywhere (the single "around " match is the word "turnaround"). One enum value (`CLOSED` on `Attraction.status`) required an explicit sentence to reach the PRD, as did the `amount_cents` request field.

## Step 5: Generate unit tests — 2026-09-29T16:11:00.000Z

All 98 tests collect cleanly. Generation is complete and verified.

### Summary

**Files written**

`test_helpers/` (9 modules): `__init__.py`, `types.py` (19 entity TypedDicts + status/role enums; every entity is a full common-field resource per PRD §2.4), `api_client.py` (~110 endpoint methods), `api_errors.py` (all 39 error IDs + framework registration), `assertions.py`, `factories.py` (19 payload factories), `constants.py`, `test_users.py` (17 opaque roles + `make_member_headers` for the one entity-backed role), `fixtures.py` (design-recipe executor + 5 tiers of composite setup helpers).

`test_suite/` (17 files): `conftest.py` + `test_01`…`test_16`. **98 tests, 0 Stage-2 violations.**

| Queue | Instances declared | Covered | Tests |
|---|---|---|---|
| A — Difficulty | 18 | 18 (≥2 each) | 40 |
| B — Corner | 57 non-stub | 57 (≥1 each) | 58 |

Per-section corner counts: entities 10, state_machines 8, calculations 10, validations 11, endpoints 5, errors 6, rbac 3, cross_cutting_layers 5.

**Skipped instances: none.** Every non-stub instance in both indices passed the two-condition filter and is translated. The 4 `difficulty_overlap` stubs are correctly not translated (all 4 cross-references resolve to real queue-A instances); none carry a tag.

**Two design-index / PRD contradictions surfaced (gaps left as gaps, not papered over):**

1. **`attraction_dwell_charge` is internally contradictory across the two indices.** The corner instance `cancel_restore_conserves_the_exact_committed_dwell` requires `dwell_committed_minutes == 900` for `dwell_cost_minutes 30 × party_size 10`, but PRD §2.8.1's verbatim text says the base is "the per-guest rate multiplied by that band multiplier" (= 90), and SCAFFOLD's formula is `per_group * size_multiplier`. Every *other* instance in both indices uses the PRD form (`39 * 30`, `8 * 30`, `4 * 30`). `900` is reachable only by re-reading "per band to the whole party" as a per-member rate — which is genuinely open in the prose, so no implementer can be pinned. I therefore did **not** assert `900`: the two tests for that instance assert only the PRD-derivable conserved quantity (`dwell_free == capacity − committed`, `committed == Σ dwell_charge_minutes`, `committed_after_cancel == committed_before_confirm`). The same pin was dropped from the corner `lane_and_party_size_boundaries` (180), the difficulty `lane_and_party_size_boundaries_on_two_endpoints` (180), `attraction_session_confirmation_requires_open_posture` (300 vs −180) and `attraction_session_fork_join_posture_gate` (1185 / 75) — those now assert the derivation identity plus a threshold that holds under either reading.

2. **`event_dwell_charge` cap 31 asserts an arithmetically wrong literal.** Corner `event_dwell_charge_two_phase_and_rounding_order` expects `24` for cap 31, but the PRD's own algorithm gives `round_half_up(16 × 0.5 + 15 × 1.0) = 23`. The cap-30 test (23) is kept verbatim; the cap-31 test asserts only what both readings agree on.

**test_helpers design decisions:** `Member` is entity-backed, so `make_member_headers(member_id)` is used for every ownership-gated or member-acting call and `MEMBER_FALLBACK` only for the shared-constant case. Fixtures use `get_success_data()` internally so setup failures read as "Setup failed"; `execute_recipe` mirrors the indices' `${var}` / `${v ± N}` capture syntax directly. The recipe executor is used for the permit-remit chain (whose setup is otherwise 11 steps); the long boat-deal delivery chain was extracted into `setup_delivered_deal`, reused by six tests.

## Step 6: Generate implementation — 2026-09-29T16:11:00.000Z

Implementation complete and verified.

### Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3019_destination_outdoor_retail_boat_sales_conservation_club/workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `start.sh` | 11 | Launcher: guarded `import flask` check, `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `core.py` | 245 | Error catalog (39 IDs), envelope/clock helpers, in-memory `DB` (19 tables) |
| `calc.py` | 616 | All 16 calculations + constants |
| `services.py` | 572 | Request-shape checker, ownership/priority helpers, deal cascades, ops-run sweep |
| `routes_floor.py` | 840 | Store, Member, Attraction, Session, Waiver, Event — 37 endpoints |
| `routes_deal.py` | 1158 | BoatUnit, Appraisal, TitleFiling, BoatDeal, ServiceOrder, ServiceIntake, BayBooking, OrderFulfillment — 54 endpoints |
| `routes_permit.py` | 469 | PermitSale, PermitRemitBatch, ClubCardApplication, PointEvent — 20 endpoints |
| `app.py` | 204 | Flask shell, auth middleware, envelope, route registry |

**111 endpoints implemented** — exactly matching the scaffold's 111 `method:` entries.

### Smoke test results

Booted via `PORT=8099 bash start.sh`: binds `0.0.0.0`, answers within ~2s, `GET /stores` → 401 unauth, `POST /stores` → 201. Restart test: 1 store before kill → 0 stores and clock reset to `2026-09-01T00:00:00.000Z` after re-invoking `start.sh`. No file written to disk anywhere; nothing seeded (`DB.tables` empty at import). Server killed and port 8099 freed; `__pycache__` removed.

Verified end-to-end: full deal lifecycle (quote → contract → rigging order → title submit/issue → funding → auto-delivery → settle → 608 points), the cyclic title-rejection revert (`DELIVERED→CONTRACTED`, unit `SOLD→DEAL_PENDING`, RIGGING order `DELIVERED→COMPLETED`, `rigging_status COMPLETE→SCHEDULED`, variance reset), permit seal/transmit/correct-variance/acknowledge, segregation-of-duties at both seal and decide, bay 15-minute turnover buffer, cross-check release gate, posture `OPEN→FROZEN→RESTRICTED` gating, waitlist promotion at ops-run, and 3-strike no-show escalation.

### Three judgement calls worth flagging

1. **`LAND_ACCESS_UNIT_MICRO_CENTS` is internally inconsistent.** The scaffold's constant (`125000` ÷ `10000`) and the PRD's own prose ("twelve and a half cents") both imply 12.5 cents/unit, but both contradict the pinned worked example the PRD states in the same sentence — a FISHING/RESIDENT/LE_7 sale with three land-access units must price at **3204** exact-rational vs **3203** per-unit-rounded. Only 1.25 cents/unit reproduces that pair (3200+3.75→3204; floor 1¢/unit→3203). I implemented 1.25 cents/unit, since the worked example is the observable contract; the scaffold's literal constant is commented in `calc.py`. **If the test suite asserts 12.5 cents/unit, this one constant is the only thing to change.**

2. **Contracting creates the `BOAT_TITLE` filing with status `DRAFT`**, not `FILED`. The transition table's side effect says `FILED`, but that is not in `TitleFiling`'s own enum and would make `/submit` unreachable, so no deal could ever reach `ISSUED` or `DELIVERED`. Only `BoatDeal.title_status` uses `FILED` (as the scaffold's §1.1 explicitly states).

3. **`concurrency_rules` is authoritative over `validations[priority: 25]`** for the two OCC rules: `POST /order-fulfillments` checks `expected_booking_version` against the `LoadingBayBooking`, and `POST /permit-sales` checks `expected_remit_batch_version` against the `PermitRemitBatch` — not against the direct parent. Deal mutations use `expected_deal_version` per PRD §2.10.

Two smaller reading decisions: publishing a free demo with `registration_cap != 0` is rejected with `ERR_INVALID_REQUEST` (the cap field doubles as the "is uncapped" signal), and the store's death spiral where confirming a session pushes the store to `FROZEN` still returns the 201 (the session did confirm; siblings in `REQUESTED` are then cancelled per §1.2).

## Step 7: Run tests and iterate to green — 2026-09-29T18:20:00.000Z

Orchestrator verification: all 8 `results.{1..8}.json` report `passed=97 failed=0 errors=0 total=97`; live `def test_` count in `test_suite/` is 97 (the single deletion is reflected on disk).

Subagent summary, verbatim:

All 8 parallel rounds pass 97/97 with zero failures. Here is the summary.

**Iterations run:** 8 verification rounds (1 initial sweep + 7 fix/verify cycles), ending with the required 8-round parallel stability sweep — **all 8 rounds: 97/97 passed, 0 failed, 0 errors**.

**Tests deleted (1):**
- `test_a_negative_points_delta_for_a_plain_award_is_rejected_as_a_bad_request` (test_06) — PRD silence/contradiction. The scaffold-derived rule ("numeric fields are non-negative, **except** `PointEvent.points_delta` which is signed by design") drove the test, but PRD §3.8 says "The delta is signed by design: a redemption or a reversal carries a negative movement, and the general non-negativity rule that guards every other numeric field explicitly exempts this one." PRD §2.11's `p24` text does list "negative numeric fields", but the §3.8 exemption makes a negative AWARD delta a legal request — a faithful PRD-only implementer correctly accepts it. Not uniquely derivable → deleted.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` `setup_contracted_deal`: re-read the deal after issuing the title filing before using its version to fund. Issuance advances `title_status`, which PRD §2.4 counts as a mutation (cascade), so §2.10 makes the pre-issuance version stale. Affected 15 tests.
- `fixtures.py` `setup_fulfilled_rigging_order`: moved bay check-in before the order's start hop and the fulfilment release after delivery. PRD §3.6 makes the check-in the act that releases a linked `OVERSIZE_LOADING` order to `IN_PROGRESS`, and gates the release on the pre-service order being `DELIVERED`.

**Fixes applied to `implementation/`:**
- `calc.py` `is_provisional`: the contract-price variant is quote-only (`deal_stage == "QUOTED"`); PRD §3.4 pins contracting as "the contracted variant — the rigging fee restored and the full tier credit applied". Delivering (which adds no funding record) must not flip the price back. Fixed the contracted price 11220000 / fee 882193 / balance 12102193.
- `routes_floor.py` `session_create`: reordered the gate ladder to the reading PRD §2.11 pins — `p8` posture (so a FROZEN store returns `ERR_POSTURE_FROZEN` before capacity is consulted), then `p13` overlap, then `p17` aggregate. A request colliding with a confirmed party is judged on the shared capacity alone (`ERR_SESSION_OVERLAP` when the pair won't fit); a non-colliding request over the venue's current occupancy parks in `WAITLIST_FALLBACK` while the store is OPEN, else `ERR_VENUE_CAPACITY_EXCEEDED`.
- `routes_floor.py`: waiver liveness is `expires_on <= clock` (§3.2 "at or after the store clock's current instant"); same fix in `routes_deal.py` orientation release.
- `routes_floor.py` `member_create`: `strike_epoch_started_at` starts unset. §3.2 names exactly two resets (session completion, card activation), so a freshly enrolled member's no-shows must count.
- `routes_floor.py` `_workshop_material_shortfall`: only bites when the store declares a stock (PRD's `workshop_material_stock` is not a declared store field; a fresh store must not silently park every workshop).
- `routes_deal.py` `service_order_deliver`: an `OVERSIZE_LOADING` order may only be delivered once its bay is `CHECKED_IN`/`COMPLETED` (§3.6's check-in precondition).
- `routes_deal.py` `deal_refund`: a SETTLED deal returns `ERR_INVALID_STATE` (funding-dimension gate), not `ERR_ALREADY_TERMINAL` — §3.4 makes refund a funding-dimension act.
- `routes_permit.py` `club_app_decide`: check `decision_reason` (p24 required-field) before the p21 credit-limit floor; approval is a `CLASSIC`-only path for a BASE member per §3.8's tier reservation.

**Test-side corrections (12 tests):** permit-fee recipe chain (removed the acknowledge step that made the batch terminal before correction; assertions now derive from the pinned 3204 worked example rather than the internal 3238/440700 literals); settlement-variance assertions derive from the PRD's stated derivation instead of the design index's unreachable 5075 literal; no-show waiver fixtures signed one day before the clock rather than a month; `create_bay_booking` helper calls replaced with direct API calls to the correct role; points-reversal test now sends the signed-negative delta PRD §2.8.1 describes, with derived expectations; several capacity/budget fixtures retuned so the assertion under test (not an upstream posture or cap) is what fires; `test_14` bound a response object that a helper was discarding.

## Step 8: Finalize PRD against implementation — 2026-09-29T19:05:00.000Z

Step 8 ran (Step 7 was not a clean first sweep: 1 deletion, 2 `test_helpers/` fixes, 8 `implementation/` fixes). Orchestrator verification: `PRD_FINALIZED.md` exists, 468 lines matching `PRD.md`, heading count identical (no sections added or removed), +3183 bytes.

Subagent summary, verbatim:

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_3019_destination_outdoor_retail_boat_sales_conservation_club/workspace/PRD_FINALIZED.md`.

### Size
- PRD.md: 468 lines / 123,181 bytes → PRD_FINALIZED.md: 468 lines / 126,354 bytes (no line added or removed; 13 paragraphs revised in place). Character delta ≈ +2.6%.

### Changes (one per bullet)
- §2.8.1 `boat_deal_contract_price` — revise — variant selection is a function of `deal_stage` alone; quote variant is `QUOTED` only, contracted variant from the moment the deal leaves `QUOTED` regardless of funding records. (calc.py:116-122)
- §2.8.1 `permit_fee` — revise — land-access unit is "one and a quarter cents", not "twelve and a half cents" (pinned worked example 3204/3203 requires 1.25¢). (calc.py:55-65)
- §2.8.1 `no_show_strike` — revise — completion reset sets the epoch to the completed session's start instant; a fresh member carries no epoch at all. (routes_floor.py:611, routes_permit.py:427, calc.py:424-442)
- §3.1 posture gate — revise — posture is consulted before capacity/overlap; FROZEN → `ERR_POSTURE_FROZEN`, RESTRICTED → `ERR_POSTURE_RESTRICTED`. (routes_floor.py:375-429)
- §3.1 capacity measure — revise — collision-with-a-party judged on shared capacity; non-colliding request judged on the `in_use_units` aggregate. (routes_floor.py:419-422, 479-511)
- §3.1 parking — revise — only a non-colliding aggregate overshoot parks; a colliding overflow is refused, never parked. (routes_floor.py:419-426)
- §3.1 shortfalls — revise — `ERR_VENUE_CAPACITY_EXCEEDED` fires for the RESTRICTED non-colliding shortfall; `ERR_SESSION_OVERLAP` for colliding breach; `ERR_POSTURE_FROZEN` decided before capacity. (routes_floor.py:422-429)
- §3.2 waiver liveness — revise — liveness boundary is inclusive (`expires_on` at or past the clock), same test on venue session and orientation release. (routes_floor.py:393-396, routes_deal.py:1125-1127)
- §3.2 no-show reset — revise — as §2.8.1 above.
- §3.3 workshop materials — revise — shortfall branch only bites a store that has declared a stock; undeclared stock → no shortfall. (routes_floor.py:865-890)
- §3.4 contracting — revise — the contracted-variant price stands for the deal's remaining life; delivery does not revert it. (calc.py:116-122, 195-207, services.py:313-330)
- §3.4 refund — revise — refund is gated on the funding dimension; non-FUNDED and SETTLED both return `ERR_INVALID_STATE`, never `ERR_ALREADY_TERMINAL`. (routes_deal.py:487-504)
- §3.6 oversize deliver — revise — an `OVERSIZE_LOADING` order may be handed over only once its booking is `CHECKED_IN`/`COMPLETED`; earlier → `ERR_INVALID_STATE`. (routes_deal.py:683-689)
- §3.8 club decide — revise — `decision_reason` validated before the credit-limit floor (absent → `ERR_INVALID_REQUEST`); approved limit stored as presented. (routes_permit.py:366-402)

### Per-edit pre-edit search log

1. **Contract-price variant.** (a) Subject: which variant `boat_deal_contract_price` selects. (b) Grepped all `is_provisional`/`provisional_quote_price`/`contracted_settlement_price`/`recompute_deal_money` callers — calc.py:116-170/195-214, routes_deal.py:90 (unit PATCH), 362 (quote), 442 (contract), 473/481 (funding), 501 (refund), 523 (settle), services.py:349 (auto-revert), 375 (title reject); read all of routes_deal.py:330-530, services.py:299-380. (c) Confirmed every recompute site is at `QUOTED` or later, so a stage-only rule is consistent everywhere; added the "raises its stored price" claim to satisfy the test that asserts contracted > quote.

2. **Permit-fee add-on.** (a) Subject: land-access per-unit rate. (b) Read calc.py:272-287 and the constant block (calc.py:54-65) and identified the only value reproducing the PRD's own 3204/3203 pair (1.25¢). (c) Inserted "one and a quarter" replacing the contradictory "twelve and a half" in the same sentence, so the rest of the §2.8.1 dual-variant prose stays consistent.

3. **Strike epoch reset.** (a) Subject: `strike_epoch_started_at` reset semantics. (b) Grepped all three write sites (routes_floor.py:127 create, 611 complete; routes_permit.py:427 activate) and the reader calc.py:424-442; read routes_floor.py:589-617, routes_permit.py:415-430. (c) Added "to that session's start instant" and the fresh-member-epoch sentence; verified the `>= epoch` counting in calc.py:434-436 makes "in-window" the only relevant event, so no over-specification.

4. **Posture 5/6/7/8 edit.** (a) Subject: posture-vs-capacity evaluation order in `session_create`. (b) Read the whole of routes_floor.py:340-470 and helpers 456-530; grepped for parallel posture gates in `session_check_in` (routes_floor.py:575-579: FROZEN before RESTRICTED before start-time) and promotion logic (services.py:432-459). (c) Softened "blocks any operation" to name only the session-request refusal, and added "before any occupancy arithmetic runs" — verified `session_check_in` has no capacity arithmetic, so the wording stays true there.

5. **Capacity measure (collision vs aggregate).** (a) Subject: which capacity metric each request shape uses. (b) Read `_has_interval_collision`/`_overlap_capacity_breach`/`_venue_capacity_overflow` (routes_floor.py:479-511) and the promotion `_venue_capacity_ok` (services.py:195-197). (c) Framed the split as "depends on whether the requested interval collides", and retained the original half-open adjacency sentences verbatim so the collision rule does not read as excluding them.

6. **Parking.** (a) Subject: `WAITLIST_FALLBACK` trigger. (b) Read routes_floor.py:411-476 and the promotion path services.py:423-465. (c) Added the "collides with no existing party" qualifier and the explicit "a colliding breach is never parked" sentence; verified the promotion path uses the same aggregate check, so the added qualifier does not contradict it.

7. **Capacity shortfalls / errors.** (a) Subject: `ERR_VENUE_CAPACITY_EXCEEDED` vs `ERR_SESSION_OVERLAP` vs `ERR_POSTURE_*`. (b) Same reads as 4-6 plus test_06:140-175 / test_08:88-114. (c) Rewrote the "already over its cap through its other committed sessions" phrasing (which would mis-describe the colliding branch) into the non-overlapping-aggregate form.

8. **Waiver liveness.** (a) Subject: `expires_on` vs clock comparison. (b) Grepped every `expires_on` read — routes_floor.py:394-396 and routes_deal.py:1125-1127 both `<= now`; ops-run expiry services.py:399-400 `exp < now`; posture count calc.py:344-349 `exp < now`. (c) **Reverted** a first-pass edit to §2.7 (line 116) that would have defined the posture count as "arrived or passed" (= `<=`): the implementation genuinely uses strict `<` there while session liveness uses `<=`, so loosening §2.7 would have created a new mismatch. The edit was confined to the two liveness gates, and §2.7's original text was restored verbatim.

9. **Workshop materials.** (a) Subject: `_workshop_material_shortfall` trigger. (b) Read routes_floor.py:832-890; confirmed `workshop_material_stock` is read only in that helper and is not a declared store field (store_create routes_floor.py:39-51); checked the KIDS_WORKSHOP tests (test_04:203-232, test_12:113-119) which never declare a stock. (c) Added the "relative to the store's declared stock" sentence; kept "synthesises an OUTFITTING work order" even though that branch is unreachable for undeclared stores, so the description stays faithful to the code that is present.

10. **Refund gate.** (a) Subject: `deal_refund` precondition. (b) Read routes_deal.py:487-504 and `deal_auto_revert` services.py:341-350; grepped `ERR_ALREADY_TERMINAL` in routes_deal.py to confirm settle/fund use it but refund does not; checked test_11:154-182. (c) Described the gate as a funding-dimension check (soft, not an enumerated priority claim) so it stays consistent with the two refund branches.

11. **Oversize deliver gate.** (a) Subject: `service_order_deliver` precondition for `OVERSIZE_LOADING`. (b) Read routes_deal.py:677-698; checked `bay_booking_check_in` (routes_deal.py:1014-1028) and the fixture/test flows (fixtures.py:528-590, test_07:25-135, test_11:187-230). (c) Phrased the status set as `CHECKED_IN`/`COMPLETED`; verified the only call sites deliver after check-in, so no path is mis-described.

12. **Club-card decide ordering.** (a) Subject: `club_app_decide` validation order. (b) Read routes_permit.py:366-412; grepped tests (test_02:105-130, test_15:340-388) — all supplies `decision_reason` and `credit_limit_cents` together. (c) Added "validated before the floor" and dropped an initial "reachable only for CLASSIC" clause after confirming the tier/product gate is generic (not CLASSIC-only), then softened "the general request-shape rule" to avoid an unverifiable p24/p21 priority claim.

## Step 9: Complete PRD — residual ambiguity/mismatch scan — 2026-09-29T19:22:00.000Z

Orchestrator verification: `PRD_COMPLETED.md` exists, 468 lines (unchanged from base), 26 headings — identical heading count across `PRD.md` / `PRD_FINALIZED.md` / `PRD_COMPLETED.md`, confirming no sections were added.

Subagent summary, verbatim:

All edits are in place and verified. Here is the final report.

### Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3019_destination_outdoor_retail_boat_sales_conservation_club/workspace/PRD_COMPLETED.md`

- Source: `PRD_FINALIZED.md` (126,354 chars / 468 lines) → `PRD_COMPLETED.md` (130,503 chars / 468 lines). **Char delta +4,149; line count unchanged** (every change is an in-paragraph insert or revision; no new paragraphs, sections, or reflows).
- **22 changes: 13 ambiguity-pins, 9 mismatch-revisions.**
- Step 8's 13 already-revised paragraphs were left structurally untouched (only the two that were themselves divergent were touched: the §2.8.1 permit_fee paragraph, where Step 8's arithmetic change left residual silence, and none other).

### Change list

- §2.1 — insert — ambiguity — `decision_reason` and `agency_reference` are written as unvalidated opaque strings — routes_permit.py:400, routes_deal.py:286
- §2.3 — insert — ambiguity — `limit`/`offset` out-of-range values are clamped, not refused — services.py:158-165
- §2.4 — insert — ambiguity — `version` initial value is 1; point events and both session-creation paths mint at 0 — core.py:209, services.py:261, routes_floor.py:444,472
- §2.6 — insert — ambiguity — parent-mismatch is wired route-by-route; flat reads and the parent-addressed transition actions resolve by `id` alone — routes_deal.py:1155, routes_permit.py:142,325, routes_floor.py:836,896,980,1033
- §2.6 — revise — mismatch — venue sessions carry no offering link; the event-capacity constraint on sessions does not exist — routes_floor.py:342-453
- §2.8.1 `permit_fee` — insert — ambiguity — invalid permit type/residency raises `ERR_INVALID_REQUEST` — calc.py:275
- §2.8.1 `permit_fee` — insert — ambiguity — term >365 is priced (not refused); `land_access_units` is optional; the tier base is always whole cents — calc.py:262-287, routes_permit.py:24-25
- §2.8.1 `intake_project_charge` — insert — ambiguity — evaluated at the five gates only; the description edit, release and abandonment do not recompute it — routes_deal.py:760,832,850,865,882
- §2.8.1 `permit_remit_snapshot` — insert — ambiguity — an unsealed batch's live total and variance track the window sum after each sale create — routes_permit.py:65, calc.py:604
- §2.10 intro — revise — mismatch — guards are "built around", not "require", the expected version — routes_deal.py:1068
- §2.10 fulfilment guard — revise — mismatch — `expected_booking_version` is carried, not required — routes_deal.py:1058-1070
- §2.10 permit-sale guard — revise — mismatch — `expected_remit_batch_version` is carried, not required — routes_permit.py:28,44
- §2.10 deal guard — revise — mismatch — `expected_deal_version` is accepted, not required — routes_deal.py:387-394
- §2.10 closing — insert — ambiguity — every guard skips the comparison when the field is omitted — routes_deal.py:389, routes_permit.py:44, routes_deal.py:1068
- §2.11 — insert — ambiguity — optional fields are left unset rather than defaulted; only declared-required fields raise — services.py:15-86
- §3.3 publishing — insert — ambiguity — `dwell_charge_minutes` is pinned once at publish from the cap, never recomputed from a live seat count — routes_floor.py:758-763
- §3.4 contracting — insert — ambiguity — the card-status basis for the settlement award is pinned at contract time — routes_deal.py:360,423, calc.py:229
- §3.4 funding — revise — mismatch — the `PENDING` branch is unreachable; a below-balance recording is always `ERR_FUNDING_SHORTFALL` — routes_deal.py:466-479
- §3.5 appraisals — revise — mismatch — the appraisal row has no free-text description to amend — routes_deal.py:152-167
- §3.6 verification — revise — mismatch — verification refreshes the order's lateness without extending its promise — routes_deal.py:834-837
- §3.7 batch window — insert — ambiguity — a non-positive window raises `ERR_INVALID_SLOT_WINDOW` — routes_permit.py:124-125
- §3.8 point events — insert — ambiguity — system-posted point events (settlement, consolation, attendance, deposit refund) run the full replay — services.py:544,566, routes_deal.py:525,715, routes_floor.py:912

### Notes

- Highest-value mismatch found: the §3.4 funding `PENDING` state is documented as reachable but the implementation makes it dead — the `ERR_FUNDING_SHORTFALL` check precedes the `PENDING` write, so `funding_status` never leaves `UNFUNDED` except to `FUNDED`/`REFUNDED` (routes_deal.py:464-479).
- Tests were used only to confirm intent on the contested §3.1 overlap/park split; no assertion or test file informed any revision's content.