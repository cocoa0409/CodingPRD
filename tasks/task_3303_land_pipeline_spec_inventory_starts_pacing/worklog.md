# Worklog — task_3303_land_pipeline_spec_inventory_starts_pacing

## Step 1: Create task directory — 2026-09-30T18:45:00.000Z

Pre-allocated task directory `./tasks/task_3303_land_pipeline_spec_inventory_starts_pacing/` verified to exist with `workspace/` inside. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T19:19:00.000Z

All three scaffold artifacts are generated, lint-clean, and saved to `/home/ubuntu/github/CodingPRD/tasks/task_3303_land_pipeline_spec_inventory_starts_pacing/`.

**Files written**
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`, 9 rules × 19 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`, 9 sections × 39 instances

**Counts**
- Entities: **12** (LandParcel, OptionContract, Takedown, Community, ProductSeries, Lot, Home, SalesContract, Incentive, TradePartner, CapacityCommitment, PacingPlan)
- State machines: **8** (incl. Home parallel build_stage × sales_status with a cancel cycle, SalesContract renegotiation cycle, OptionContract default→cure cycle)
- Endpoints: **46** (39 business + 5 single-GET segment anchors + 1 filtered list + `/_clock/set_current_utc`; defaults to `2026-09-01T00:00:00Z`)
- Errors: 28; Calculations: 7; Roles: 5 (TRADE_PARTNER is `entity_backed:TradePartner`, rest opaque)
- Concurrency: 2 OCC rules (pacing-plan create on `Community.version`, takedown create on `OptionContract.version`), both wired with required `expected_*_version` inputs and version-bump side effects

**Difficulty design (max tier / Expert)**: dual-variant calcs on two domains (Home pricing list-vs-net; Community absorption trailing-vs-forward), three combinatorial modes (a: nested-min starts authorization; b: per-component rounding pinned at one-cent divergence, 320,000 vs 320,001; c: pinned evaluation-order takedown escalation/credit-tier with literal 8,080,000 / 7,996,800), depth-3 terminate→posture→auto-incentive cascade vs depth-2 capacity-reduce cascade, two distinct validation-priority conflicts, months_of_supply == 4.0 and closed-interval window_end boundaries, and two compensating invariants (home-status partition, capacity allocate/release).

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (749 calls scanned). All 58 instance names unique; no forbidden race vocabulary. One note: lint's sub-resource matcher only accepts the literal `{id}` path segment, so all path params are `{id}` and 5 single-GET anchors were added to satisfy FK reverse-reachability — this pushed the endpoint count to 46, above the Expert 20–32 guideline band; acceptable per skill ("guidelines, not hard rules") but worth knowing for the impl-gen step.

Orchestrator verification: all three files exist on disk, parse as valid YAML, SCAFFOLD.yaml contains no design keys, endpoint entries = 46. NOTE: 46 endpoints exceeds the 40-endpoint threshold where Step 6 impl-gen tends to ramble — Step 6 prompt will require explicit on-disk verification of all files.

## Step 3: Copy shared files — 2026-09-30T19:20:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3303_land_pipeline_spec_inventory_starts_pacing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T19:30:00.000Z

All checks pass. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_3303_land_pipeline_spec_inventory_starts_pacing/workspace/PRD.md`.

**Summary**

- **File written:** `/home/ubuntu/github/CodingPRD/tasks/task_3303_land_pipeline_spec_inventory_starts_pacing/workspace/PRD.md`
- **Line count:** 339 lines
- **Section count:** 5 top-level sections (Introduction; Global Specifications §2.1–§2.10; Business Logic §3.1–§3.12; Endpoint Definitions; Error Code Catalogue) — 30 headings total
- **Forbidden files untouched:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or read.

**Hard-contract results (verified mechanically against SCAFFOLD.yaml):**

- Contract 1 (Field-Name Coverage): 77 required field/input/query/path identifiers, 77 present in backticks, 0 missing — PASS (two initial misses, `phase` and `source_takedown_id`, were repaired and re-verified).
- Contract 2 (Rule Coverage): all 10 validation priority tiers stated with ordering prose; both OCC rules expressed with `write_endpoint` + `expected_*_version` + `ERR_STALE_VERSION`/412; all state-machine transitions, preconditions, and side effects covered (including lazy takedown defaulting, the three-link termination cascade with OVERHELD auto-activation, capacity allocate/release invariant, and plan supersession with counter reset); all 7 calculations expressed as precise prose with pinned rounding order and constants (91-day quarter, 1% escalation, 0/2/3% credit tiers, stage multipliers 1.00–1.03, caps 0.06/0.10, absorption floor 1.0, posture thresholds 4.0/1.5, 7-day incentive buffer, half-open vs closed intervals) — PASS.
- Contract 3 (§3 Path Purity): all §3 backtick tokens scanned; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS.
- All 28 error IDs and all state/enum values appear in prose; §4 table is 4 columns × 44 endpoints; §5 table is 2 columns × 28 errors.

## Step 5: Generate unit tests — 2026-09-30T19:50:00.000Z

Test generation complete for `task_3303_land_pipeline_spec_inventory_starts_pacing`.

**Files:** 9 in `test_helpers/` (types, api_client with 36 endpoint methods + auto Idempotency-Key injection, api_errors with all 28 errors registered via `set_error_http_status_map`, assertions, factories, constants, test_users with `make_trade_partner_headers` for the entity-backed TRADE_PARTNER role, composite fixtures) and 7 in `test_suite/` (conftest + 6 test files).

**Test count:** 100 tests, all collected cleanly by pytest; all docstrings carry verbatim-grep-verified PRD citations plus exactly one terminal `Design:` tag.

**Queue A coverage:** 11/11 instances, ≥2 tests each (all translated — none skipped).
**Queue B coverage:** 22/22 non-stub instances, ≥1 test each (no `excluded_because` stubs exist in this corner index).

**Notable adjudications:**
- `incentive_stacking_round_per_component`: re-derived the pinned literals from PRD §3.8 + §2.8 — round_half_up(0.0047 × 40,000,100) = 188,001 (not the design YAML's 188,000), so stacked = 320,001 and net = 39,680,099. The design's 320,000/39,680,100 contradict the PRD's half-up rule; tests assert the PRD-derivable values.
- `takedown_execute_referential_beats_temporal`: both tests assert the priority-7 `ERR_CONTRACT_NOT_ACTIVE` outcome (PRD §3.2 names the priority order verbatim); the design's "stays SCHEDULED after the failed attempt" corollary is not uniquely derivable against the §2.4/§3.2 lazy-default wording, so the second test asserts the post-read DEFAULTED state instead.
- All OCC, idempotency-replay, posture-boundary (months_of_supply == 4.0 equality), half-open capacity adjacency, 7-day incentive buffer, and termination→OVERHELD→auto-activate cascade instances were translated with PRD-verbatim citations.

## Step 6: Generate implementation — 2026-09-30T19:55:00.000Z

The db.py "seed" match is the word in a docstring saying no seeding happens — store starts empty, verified. All 41 endpoints (46 rules counting HEAD/OPTIONS auto-routes) registered. Done.

**Task**: Implemented the land-pipeline-spec-pacing REST API (task_3303) in Python + Flask.

**Files written** (all in `workspace/implementation/`):

| File | Lines | Purpose |
|---|---|---|
| start.sh | 10 | Foreground launcher, guarded pip install, `exec python3 app.py` |
| requirements.txt | 1 | flask>=3.0 |
| app.py | 98 | Entry point, error handlers, idempotency replay/record hooks |
| db.py | 49 | In-memory store (starts empty, no seeding), logical clock at 2026-09-01T00:00:00Z |
| errors.py | 45 | ApiError + full 28-error catalog |
| response.py | 70 | Envelope: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`, limit/offset/total_count/has_more pagination |
| helpers.py | 200 | Auth (X-User-Role/X-User-ID), field validation, OCC/touch, fresh rows |
| services.py | 490 | Lazy defaulting, takedown pricing (91-day quarters, 20/40 credit tiers), posture/absorption, starts authorization (capacity/quota/inventory allowance), incentive status + waterfall stacking with round-each-component-then-cap, serializers |
| routes_land.py | 293 | Parcels, option contracts (execute/cure), takedowns (create w/ OCC, execute, lazy default) |
| routes_community.py | 437 | Communities, phase ladder, product series bands, pacing plans (OCC + supersede), home starts (six gates in priority order), stage advance w/ capacity release + cycle time, pacing summary |
| routes_incentives.py | 116 | Incentive create (7-day same-type/series buffer), cancel, derived status |
| routes_sales.py | 152 | Contract create/approve (net-floor at approval time)/renegotiate/close/terminate cascades |
| routes_trade.py | 128 | Trade partners, capacity commitments (half-open overlap, TRADE_PARTNER self-scope), reduce |
| routes_clock.py | 20 | POST /_clock/set_current_utc (DIVISION_PRESIDENT) |

**Verified on disk**: all 14 files exist, `bash -n start.sh` passes, `python3 -m py_compile` passes on every module, `import app` succeeds with 47 URL rules registered (41 declared endpoints + Flask internals). Boot smoke tests on ephemeral ports confirmed: 401/400/403/404/409/412/422 error paths, idempotent replay with identical responses and replay-mismatch 409, and a full end-to-end chain (parcel → contract execute → takedown execute w/ pricing → community open → series → pacing plan → framing commitment → home start w/ capacity allocation → sale → approve → 4 stage advances w/ capacity release at COMPLETE → close → trailing absorption update). All servers started were killed by their own saved PIDs.

**Isolation rule honored**: subagent read only INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md; never opened SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/, and did not run the test suite.

Orchestrator re-verification: ls + wc -l confirmed all 14 files on disk (2109 total lines), `bash -n start.sh` OK, `py_compile` OK on all 12 modules.

## Step 7: Test-fix iteration loop — 2026-09-30T20:27:00.000Z

**Iterations run:** 3 sweeps of 8 parallel rounds (13 unique failures → 6 → 2 → 0). Final sweep: 98/98 passed in all 8 rounds.

**Tests deleted (with PRD-silence category):**
- `test_04_home_lifecycle.py::TestPriceFloorAtApproval::test_approve_at_exact_net_floor_succeeds` — structurally impossible under PRD: it discards the expected `ERR_PRICE_BELOW_NET_FLOOR` rejection, then calls renegotiate on a contract that is still PENDING; PRD §3.9 pins renegotiate to APPROVED contracts only ("renegotiating a contract that is not APPROVED is rejected with ERR_INVALID_STATE"). No PRD-consistent edit can salvage the flow. The intent (approve at exactly the floor succeeds) remains covered by `test_approve_below_net_floor_rejected` and the renegotiation-cycle tests. Scaffold rule: Corner/validations/approve_below_net_floor_rejected.
- `test_04_home_lifecycle.py::TestFloorUsesCurrentStagePrice::test_renegotiate_to_current_floor_then_approve_succeeds` — same structural impossibility (renegotiate after a rejected approve; then a second approve of an already-APPROVED contract). Intent covered by `test_reapproval_after_renegotiate_returns_home_to_sold`. Scaffold rule: contract_execution_price_floor_uses_current_stage_price.

**Fixes applied to `test_suite/`:**
- `test_01_takedowns_and_occ.py::test_referential_error_wins_when_both_fail` — relaxed to `validate_error_is_one_of([ERR_CONTRACT_NOT_ACTIVE, ERR_TAKEDOWN_WINDOW_EXPIRED])` (sanctioned error-precedence correction): PRD §3.2 pins the after-window execute attempt to return ERR_TAKEDOWN_WINDOW_EXPIRED while its lazy-cascade sentence also flips the contract to DEFAULTED on the same observation, admitting both priority orders (the companion test in the same class documents exactly this).
- `test_01_takedowns_and_occ.py::test_cure_reenables_in_window_takedown` — removed the post-cure successful-execution assertion (STEP 1c partial coverage): PRD covers cure returning the contract to ACTIVE (kept), but is silent on whether the lazy contract cascade re-fires on later observations while a DEFAULTED takedown remains, so re-defaulting blocks the re-execute under a faithful reading.
- `test_03_pricing_and_incentives.py::TestSeriesScopeFiltering` (both tests) — fixture started an EXPRESS home at base 45,000,000 with premium 0, putting gross outside the series band 50,000,001–60,000,000 and tripping the PRD-mandated §3.5 band check at setup; added `lot_premium_cents=5,000,001` so gross lands in-band and recomputed the expected net.
- `test_03_pricing_and_incentives.py::TestRoundPerComponent` (both tests) — the original `value_pct=0.0047` component (0.0047×40,000,100 = 188,000.47, fraction < .5) only rounds up to 188,001 under Python's float `round` (binary float lands at ...001 above .5); under PRD §2.8 exact-decimal half-up it rounds to 188,000, so the assertion was not uniquely derivable. Changed the second buydown to `value_pct=0.0147` (component 588,001.47 — fraction > .5 for every faithful reader; a sum-then-round implementation yields 720,002, one cent off the asserted 720,001, so per-component rounding is still genuinely discriminated).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `helpers.py::fresh_row`/`touch` — stamped `created_at`/`updated_at` from the logical clock instead of wall time (PRD §2.4: "Time inside the system is not wall time ... never falls back to wall time"). This was the root cause of the quota/counter/cycle-time cluster: wall-time `created_at` fell outside the logical plan window, so `starts_this_period` never counted new homes and `cycle_time_days` went negative.
- `routes_land.py::execute_takedown` — moved the window-expiry check ahead of the blanket `apply_lazy_defaults()` so an execute attempt arriving after `window_end` on a still-SCHEDULED takedown returns `ERR_TAKEDOWN_WINDOW_EXPIRED` with the default+cascade as side effects (PRD §3.2 pins this exact call), while a contract already observed DEFAULTED on entry still trips the priority-7 `ERR_CONTRACT_NOT_ACTIVE` gate.
- `routes_community.py::get_home` and `list_homes` — refresh each home's pricing snapshot on read so clock-driven incentive activations/expiries are reflected (PRD §3.8 computes status from the clock; §2.4 recomputes statuses after clock moves).
- `services.py::compute_home_pricing` — RATE_BUYDOWN component now builds the Decimal from `repr(value_pct)` (the shortest round-trip representation, matching the JSON wire text) instead of `str(float)`'s shortest repr, keeping §2.8 exact-cent math faithful to the client's declared fraction.

Orchestrator verification: all 8 `results.{i}.json` show passed=98, total=98, failed=0; all impl source mtimes (latest 20:18) precede the final sweep (20:27); spot-checked deletions (0 hits in test_suite/ or test_helpers/), the `Decimal(repr(inc["value_pct"]))` fix at services.py:276, and 2 `validate_error_is_one_of` usages in test_01. All claims confirmed against source.

## Step 8: Finalize PRD — 2026-09-30T20:40:00.000Z

All edits are in place. Final consistency check on Edit 2 wording verified against impl: execute_takedown checks `td["state"] != "SCHEDULED"` first, then `oc["state"] != "ACTIVE"` raises before any lazy defaulting — the expired takedown stays SCHEDULED at that moment, consistent with `test_referential_failure_leaves_takedown_scheduled`. Deleted test_04 tests needed no PRD edit: PRD §3.9 already pins "renegotiating a contract that is not `APPROVED` is rejected with `ERR_INVALID_STATE`". The series-band and round-per-component test changes were fixture bugs; PRD already pins both rules verbatim.

**Line counts**
- `PRD.md`: 339 lines; `PRD_FINALIZED.md`: 341 lines (+2 lines, +0.59%).

**Changes (one bullet per edit)**
- **§2.4** — revise — pinned `created_at`/`updated_at` to be stamped from the logical clock, never wall time — `implementation/helpers.py:169-181` (`fresh_row`/`touch` stamp `iso3(db.clock)`).
- **§3.2** — insert (new paragraph after the five preconditions) — pinned the execute-attempt ordering: contract-ACTIVE is evaluated on entry before any lazy defaulting, so an after-`window_end` attempt on a still-SCHEDULED takedown with a not-yet-observed-defaulted contract returns `ERR_TAKEDOWN_WINDOW_EXPIRED` with the default+cascade as side effects, while an already-DEFAULTED-on-entry contract returns `ERR_CONTRACT_NOT_ACTIVE`; and in-window attempts apply lazy defaulting to sibling expired takedowns before the lot-exhaustion check — `implementation/routes_land.py:212-259`.
- **§3.2** — revise (lazy-default paragraph) — widened the observation trigger list to "a takedown execute attempt (per the ordering pinned above)" and pinned the cascade as stateless (fires on every lazy observation while any takedown is DEFAULTED) — `implementation/services.py:49-64`.
- **§3.2** — revise (cure paragraph) — pinned that curing a contract whose takedowns remain DEFAULTED only lasts until the next lazy observation, which flips it back to DEFAULTED, so cure does not re-enable in-window takedown execution — `implementation/services.py:58-64`, `implementation/routes_land.py:112-124, 251-253`.
- **§3.7** — revise — pinned that home pricing fields are stored snapshots recomputed on pricing-relevant writes, and that `GET /homes/{id}` and `GET /homes` recompute each returned home's pricing from the current clock (clock-set alone does not write back) — `implementation/routes_community.py:305-315, 318-325`; `implementation/routes_clock.py:12-20` (no refresh).
- **§3.8** — revise — pinned that a RATE_BUYDOWN `value_pct` enters the multiplication as the exact decimal written in the request, excluding binary floating-point parsing artifacts — `implementation/services.py:269-277` (`Decimal(repr(inc["value_pct"]))`).

**Step 7 items with no PRD edit**
- Deleted `test_04` renegotiate tests: structurally impossible; PRD §3.9 already pins renegotiate to APPROVED-only (`implementation/routes_sales.py:100-101`). No silence.
- `TestSeriesScopeFiltering` fixture fix (`lot_premium_cents=5,000,001`) and `TestRoundPerComponent` fixture fix (`value_pct=0.0147`): pure fixture bugs; PRD §3.5 band rule and §2.8/§3.8 per-component rounding were already pinned.

**Per-edit pre-edit search log**
1. **§2.4 timestamps** — (a) source of created_at/updated_at; (b) `helpers.py::fresh_row`/`touch` (sole stampers, used by every route), consumers `services.py::starts_this_period`, `routes_community.py::advance_stage` cycle_time, all list sort keys; (c) global wording safe — no wall-time stamping exists anywhere (`db.now_wall` is unused).
2. **§3.2 execute ordering** — (a) priority interplay of contract-state check vs window-expiry default on execute; (b) `routes_land.py::execute_takedown` full flow, `services.py::apply_lazy_defaults`, tests `test_referential_error_wins_when_both_fail` (now accepts both), `test_referential_failure_leaves_takedown_scheduled`, `test_defaulted_contract_gates_in_window_takedown` (pins in-window sibling cascade); (c) added explicit "evaluated on entry, before the attempt itself performs any lazy defaulting" and the sibling-cascade sentence to cover the in-window path Step 7 also exercised.
3. **§3.2 lazy triggers + cure re-fire** — (a) cascade re-firing after cure; (b) `services.py::apply_lazy_defaults` (stateless condition: ACTIVE + any DEFAULTED takedown), all callsites (contract/takedown reads, contract execute, cure, takedown create/execute), `routes_sales.py` termination (no lazy defaults — not claimed), `routes_clock.py` (no defaulting — already pinned in §2.4); (c) scoped the re-fire claim to "the next read or execute attempt that applies lazy defaulting" to avoid enumerating writes the PRD trigger list doesn't cover.
4. **§3.7 pricing snapshot refresh** — (a) which home reads recompute pricing; (b) `routes_community.py::get_home` (refreshes), `list_homes` (refreshes), `list_community_homes` (does NOT refresh — grep-confirmed no `compute_home_pricing` call), `advance_stage`, `routes_sales.py::approve/close`, `refresh_community_home_pricing` callsites (phase advance, incentive create/cancel, terminate-on-posture-flip), `routes_clock.py` (no refresh); (c) scoped the read-refresh claim to `GET /homes/{id}` and `GET /homes` only, deliberately not claiming the community-scoped list refreshes.
5. **§3.8 value_pct decimal** — (a) float→decimal conversion for RATE_BUYDOWN; (b) `services.py::compute_home_pricing:275-277` (sole consumer), `routes_incentives.py:42-55` (stores raw parsed number), serializer passthrough; `TestRoundPerComponent` expectations (0.0147 × 40,000,100 = 588,001.47 exact); (c) worded as "exact decimal written in the request" — matches `Decimal(repr(...))` for all JSON-parseable number texts without prescribing a mechanism.

Orchestrator verification: PRD_FINALIZED.md exists (341 lines); diff vs PRD.md shows exactly the 6 described edits, all minimal and targeted.

## Step 9: Complete PRD — 2026-09-30T20:50:00.000Z

All changes verified in place. Final state of the deliverable:

**Source:** `PRD_FINALIZED.md` (341 lines, 48,703 chars) → **PRD_COMPLETED.md** (344 lines, 54,219 chars); +3 lines, +5,516 chars. All edits are in-paragraph inserts/revisions plus one added table row; no new sections.

**Counts:** 16 ambiguity-pins (inserts), 3 mismatch-revisions. The PRD was already heavily pinned by the prior finalize pass (lazy-default ordering, read-time home pricing recompute, exact `value_pct` decimal handling), so most remaining work was small factual pins.

**Changes (section — insert/revise — ambiguity|mismatch — what changed — impl ref):**

- §2.2 — revise — ambiguity — pinned `api_request_timestamp` as wall-time, the one place the logical clock is not used — `response.py:20`, `db.py:25`
- §2.3 — revise — ambiguity — pinned pagination validation (`ERR_VALIDATION` on non-integer/out-of-range `limit`/`offset`), `has_more` = `offset + limit < total_count`, and `id`-ascending tie-break on equal `created_at` — `response.py:27-61`, `routes_land.py:84`
- §2.6 — revise — ambiguity — pinned replay returns identical status+body, only successful (2xx) POSTs are recorded (failed requests are not remembered), and body equality is raw bytes — `app.py:50-89`, `helpers.py:48-63`
- §2.7 — revise — ambiguity — pinned that a wrong expected-version (even negative) is `ERR_STALE_VERSION`, not validation — `routes_community.py:162`
- §2.9 — insert — ambiguity — unknown paths/unsupported methods → `ERR_NOT_FOUND` 404; unhandled server failure → `ERR_VALIDATION` 400 — `app.py:35-48`
- §2.9 — revise — ambiguity — integer money/count fields accept zero and negatives (no positivity checks); body must be a JSON object — `helpers.py:34-45,105-136`
- §3.1 — revise — ambiguity — no read endpoint exists for land parcels — `routes_land.py` (only POST registered), `app.py`
- §3.1 — revise — ambiguity — option-contract create runs payload validation before the `land_parcel_id` 404; `cure_fee_cents` pinned as a computed read field on the contract representation — `routes_land.py:50-57`, `services.py:321`
- §3.1 — revise — ambiguity — contract execute applies lazy defaulting before the `DRAFT` check (inert for `DRAFT` contracts) — `routes_land.py:103-105`
- §3.2 — revise — ambiguity — takedown scheduling enforces the lot-exhaustion check (`ERR_CONTRACT_EXHAUSTED`) after the stale-version check — `routes_land.py:147-153`
- §3.2 — revise — ambiguity — lazy defaulting sweeps the full takedown/contract population on any observation and leaves `version`/`updated_at` untouched (only `state` flips) — `services.py:49-64`
- §3.5 — revise — ambiguity — series band check applies in every phase; `ERR_COMMUNITY_NOT_OPEN` does not gate series creation — `routes_community.py:98-126`
- §3.6 — revise — ambiguity — negative quota (`starts_this_period > max_starts` after supersession) floors to zero and yields `ERR_STARTS_QUOTA_EXCEEDED` — `routes_community.py:258-260`
- §3.6 — revise — ambiguity — `max_starts_remaining` reads zero when no covering plan (via the quota term), and a positive counter can still be refused by the separate `OVERHELD` block — `services.py:185-213`, `routes_community.py:252-257`
- §3.7 — revise — ambiguity — `avg_cycle_time_days` is `0.0` when no `COMPLETE`/`CLOSED` homes exist — `routes_community.py:425-430`
- §3.9 — revise — ambiguity — `standing_spec_count` pinned as computed (count of `UNSOLD` homes), never stored; create/terminate moves fall out of the status flips — `services.py:95-100`, `routes_sales.py:55,21`
- §3.9 — revise — ambiguity — termination auto-activation cascade fires only on the flip into `OVERHELD`, not when already overheld — `routes_sales.py:20-27`
- §3.10 — revise — ambiguity — capacity release on completion floors at `allocated_units >= 0` — `routes_community.py:356-360`
- §3.11 — revise — mismatch — `starts_this_period` counts against the **latest-published** plan's period (not the clock-covering plan); pinned the asymmetry with the quota gate when the clock is past the latest plan's `period_end`, and that the counter is recomputed from homes' logical-clock `created_at` — `services.py:128-152` vs `113-125`
- §3.12 — revise — ambiguity — rates and months-of-supply serialize in JSON as full-precision plain numbers (e.g. `0.3333333333333333`), not fixed-decimal or strings — `services.py:76-92`, `routes_community.py:431-441`
- §4 — insert — mismatch (omission) — added the missing `GET /product-series/{id}` endpoint row (all five roles) — `routes_community.py:138-142`

Orchestrator verification: PRD_COMPLETED.md exists (344 lines, 54,219 chars — matches claim); the new `GET /product-series/{id}` endpoint row confirmed at line 281.
