# Worklog — task_2828_ethanol_plant_operations_co_product_marketing

## Step 1: Create task directory — 2026-09-05T03:04:49.929Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2828_ethanol_plant_operations_co_product_marketing` and its `workspace/` subdirectory. Index 2828 was pre-assigned by the invocation; no scan of `./tasks/` was performed.

## Step 2: Generate scaffold — 2026-09-05T04:51:30.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and lint-clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2828_ethanol_plant_operations_co_product_marketing/`)

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 4783 | 220396 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1806 | 115658 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3436 | 202775 |

## Contents

**SCAFFOLD.yaml** (§1.0–§1.7 only; top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no design keys): 15 entities, 13 state machines, 2 concurrency rules, 18 calculations, 59 validations, 64 endpoints, 59 errors, 8 roles. Profile: `compliance_audit` / `ledger_reconciliation`, graph topology, cyclic state machines, `segregation_of_duties`, immediate consistency, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (single key `scaffold_difficulty_design`): 19 instances across all 9 rule_ids (2/2/2/2/2/2/3/2/2).

**SCAFFOLD_CORNER_DESIGN.yaml** (single key `scaffold_corner_design`): 79 instances — entities 12, state_machines 16, calculations 14, validations 14, endpoints 5, errors 7, rbac 3, cross_cutting_complexity_layers 7, consistency_model 1. 62 carry full `test_recipe`s; 17 are `excluded_because` stubs citing §1.8 instances by exact name.

## Verification

- `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py <task-dir>` -> **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (639 calls scanned across 81 recipe-bearing instances).
- Independent checks I ran: all 98 instance names unique across both design files; every `grounds` reference resolves to a declared §1.1–§1.7 element (entity fields checked field-by-field); every `excluded_because.difficulty_instance` names a real §1.8 instance and no stub carries a `test_recipe`; zero unbound `${var}` placeholders; all 59 error codes triggered somewhere in §1.8+§1.9; zero forbidden concurrency vocabulary ("simultaneously", "first-writer-wins", ...) in any file.
- All money/yield/RIN/CI literals recomputed with `Decimal` + ROUND_HALF_UP (e.g. settlement 940.00 bu / 413600 cents; batch 2679.00 gal -> RIN 2732; invoice 265900.00 gal x 181.50 = 48260850; CI baseline 58.000 - 8.000 = 50.000; grind cap CURTAILED+SHORT = 54000).

## Design adjudications made

1. **CarbonProject CERTIFY preconditions** referenced request-body fields that don't exist (`certification_tier`) or contradicted the default-to-claim rule; rewritten to read the stored tier and an "effective verified reduction" (body value when present, else stored claim).
2. **`ERR_CONTRACT_FULLY_DELIVERED` was unreachable.** Validation 55 originally covered only the roll path while the error text described a delivery. Resolved by having 55 cover both delivery booking and roll, and by rewriting validation 23 to defer the FILLED-contract delivery case to priority 55 (23 still refuses deliveries on a ROLLED contract). A §1.9 instance now pins the 55-before-23 outcome.
3. **Validation 49 vs `ERR_CLOCK_REGRESSION`**: "not earlier than" admitted an equal instant; tightened to strictly later, matching the error.
4. `ERR_PLANT_ALREADY_EXISTS` condition path typo `/plant` -> `/plants`.
5. §1.9 setups avoid the full distill+blend chain where possible by seeding tanks via `opening_gallons`; only instances that genuinely need ground corn run the 8-call settle chain, always with grader `scale-01` != settler `acct-01` so the SoD rule isn't tripped accidentally.
6. Corner cases were chosen not to duplicate §1.8 (e.g. CURTAILED+SHORT cap 54000 rather than §1.8's RESTRICTED/SUSPENDED cases); five calculation corners, three state-machine corners, two priority-conflict corners, two endpoint corners and five cross-cutting corners were demoted to stubs.

**Flag for the pipeline:** the directive line `Generate task harder than expert level!` sits verbatim as the first line of `scenario:` (SCAFFOLD.yaml line 8) because the scenario had to be used unmodified. Per the known leak path it should be stripped after Step 2 so it can't reach PRD.md.

Orchestrator note: acted on that flag — removed the two directive lines from `SCAFFOLD.yaml`'s `scenario:` block immediately after the subagent exited. `grep -rn "harder than expert"` over the task dir now returns nothing, and `yaml.safe_load` confirms SCAFFOLD.yaml still parses with exactly the 13 expected top-level keys and no design keys.

## Step 3: Copy shared files — 2026-09-05T04:52:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T05:09:00.000Z

Subagent summary (verbatim):

PRD generation complete.

**Output:** `workspace/PRD.md`
**Final line count:** 504 lines (built in 12 chunked `cat >>` appends, `wc -l` verified after each: 31 -> 102 -> 168 -> 192 -> 217 -> 241 -> 260 -> 282 -> 304 -> 334 -> 368 -> 405 -> 439 -> 504)

**Section list**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operating Authority and Role-Based Access Control · 2.2 API Response Structure (emitted verbatim from the skill's `section-2.2-response-structure.md`, lines 32–80 = 49 lines) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Path Resolution and Reference Checking · 2.6 Units, Precision and Rounding · 2.7 Reservation Version Guards on Tanks and Tracks · 2.8 Plant Posture: Compliance, Procurement and the Grind Cap · 2.9 Order of Rejection · 2.10 Cascade and Version Propagation
- `## 3. Business Logic & Workflows` — 3.1 Commissioning the Facility and Posting the Market Marks · 3.2 Corn Procurement: Basis Contracts, Pricing and Rolls · 3.3 The Scale House: Inbound Loads, Grading and Settlement · 3.4 Fermentation: Charging, Health Watch, Intervention and Distillation · 3.5 The Tank Farm: Service State, Denaturant Blending and the E100 Specification · 3.6 Rail Logistics: Track Capacity, Loading, Billing and Cancellation · 3.7 Co-Product Marketing: Quoting, the Collar, Rebates and Shipment · 3.8 Renewable Credits and the Carbon-Intensity Waterfall · 3.9 Permit Compliance, the Futures Book and Margin Reporting
- `## 4. API Endpoint Definitions` — 4-column table, 64 rows verified
- `## 5. Error Code Catalogue` — 2-column table, 59 rows verified. File ends here; no audit footer.

**Coverage counts:** 15/15 entities, 64/64 endpoints, 59/59 errors, 18/18 calculations, 59/59 validations, 13 state machines / 55 transitions, 2 concurrency rules, 8 roles.

**Field coverage check:**
- entities[].fields: 203 required, 203 present, 0 missing
- endpoints[].request_body: 119 required, 119 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
- Status: PASS

(One gap found and repaired on the first pass — `submitted_at` on `CarbonProject` was unnamed in §3.8; the submit paragraph now records `verification_body` "alongside `submitted_at`". Second pass clean.)

**Rule coverage check:**
- validations[] with priority: 59 checked, all 59 error identifiers explained in §1–§4 prose with their triggering condition; the 12-tier rejection ladder plus the two named precedence pairs (distill: `ERR_INVALID_BATCH_STATE` before `ERR_TANK_NOT_IN_SERVICE`; load: `ERR_PLANT_SUSPENDED` before `ERR_INSUFFICIENT_TANK_VOLUME`) documented in §2.9
- concurrency_rules: 2 checked — `expected_destination_tank_version` -> `ERR_STALE_TANK_VERSION` and `expected_track_version` -> `ERR_STALE_TRACK_VERSION`, both in §2.7 and re-stated at their use sites
- cross-entity side effects: all cascades documented, incl. the hold fork (OFF_SPEC vs MECHANICAL), delivery-settlement chain, shipment-cancel four-way compensation, RIN separate/revert, waterfall re-run rewriting every certified row, and mark-post re-pricing of open positions
- validations[].applies_to scopes: all documented (uniqueness of the 11 natural keys under `ERR_DUPLICATE_CODE`, singleton plant, per-tank vs per-track scoping)
- field-level structured content: all enum domains, decimal widths, defaults, null-until conditions and inclusive/exclusive bounds stated
- sibling-branch symmetry: FLAT/INDEX, LONG/SHORT, FULL/PROVISIONAL, CERTIFY/RETURN, ACCEPT/DECLINE, OFF_SPEC/MECHANICAL, AIR_EMISSIONS/WATER_DISCHARGE all given symmetric treatment
- tail: 55/55 transitions, 18/18 calculations (all constants either quoted numerically or rendered in prose), all endpoint side effects
- Status: PASS

**Path purity check (§3 only):**
- backtick tokens scanned: 953
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- raw `/ethanol-ops` occurrences outside backticks in §3: 0
- Status: PASS

Also verified: no fuzzy quantifiers ("approximately", "roughly", "conservatively", "etc."), and no pseudocode operators anywhere in the document — all translated to prose.

**Verbatim last 5 lines:** the final five rows of the §5 error table, ending `| ERR_INSUFFICIENT_COPRODUCT_INVENTORY | 422 |`. The file ends at a real section boundary (the final row of the §5 table), not mid-sentence. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read. Scratch files were confined to `/tmp/task_2828_prd/`; no `pkill` was run.

Orchestrator verification (anti-truncation guard from the invocation): independently ran `wc -l` (504), `tail -25` (ends on the last `ERR_INSUFFICIENT_COPRODUCT_INVENTORY` table row — a real boundary, not mid-sentence), and enumerated the heading structure (all 5 top sections + 10 §2 subsections + 9 §3 subsections present, §4 at line 369, §5 at line 440). No regeneration needed. `grep -in "harder than expert|expert level|scaffold"` over PRD.md returns nothing — the difficulty directive did not leak.

## Step 6: Generate implementation — 2026-09-05T05:47:00.000Z

Subagent summary (verbatim):

Implementation complete. All 64 endpoints from PRD §4 are live and the server boots clean from a fresh process.

## Modules (`workspace/implementation/`, 3,633 lines total)

Foundation:
- `util.py` 82 — Decimal helpers (`rhu` ROUND_HALF_UP, floor/ceil), fixed-3-digit ISO instants, month regex
- `errors.py` 83 — all 59 error IDs -> HTTP status, `ApiError`/`fail()`
- `envelope.py` 118 — `meta`/`response_type`/`data` envelope, `req_` + 16 alnum IDs, list meta (`limit`/`offset`/`total_count`/`has_more`), hand-rolled JSON writer so Decimals emit exact declared widths (`0.00`, `2.850`, `0.022483`)
- `store.py` 73 — in-memory dicts only, logical clock default `2026-08-01T00:00:00Z`, `_seq` insertion counter, `new_row`/`touch`
- `shape.py` 214 — auth (`X-User-ID`/`X-User-Role`, 8 roles), body validation with unknown-field rejection, decimal-place/range gates, pagination
- `calc.py` 426 — every constant and formula (settlement discounts, health index, yield, RIN gross-up, denaturant band, CI waterfall, LCFS, crush margin, collar, rebate ladder, hedge P&L, grind cap, both interval conventions)
- `derive.py` 205 — all aggregates re-derived from primary records (tank balances, track commitments, plant inventories, postures, rolling yield, CI state, RIN counters)
- `serialize.py` 369, `guards.py` 143, `app.py` 55, `start.sh`, `requirements.txt`

Routes: `plant.py` 137 (5), `corn.py` 312 (10), `ferment.py` 241 (8), `tanks.py` 287 (9), `rail.py` 262 (9), `sales.py` 172 (5), `rins.py` 63 (3), `carbon.py` 153 (5), `hedge.py` 103 (4), `permits.py` 132 (6).

Programmatic parity check against the PRD endpoint table: **64 in code, 64 in PRD, zero missing, zero extra.**

## Smoke test (booted on ports 18287 then 18288, each killed by exact PID)

Booted in ~2s and answered. Verified end-to-end: plant create + read-back, marks, crush margin, contract -> price -> delivery -> grade -> settle (947.27 net dry bu, 370572 cents), batch charge -> reading -> distill -> complete (2578.50 gal / 7.650 t / 540.00 lb) -> RIN mint (2630.07 eligible, floor 2630), tank commissioning, blend schedule (occupancy conflict at the touching 14:00 boundary correctly refused), execute, track + shipment (aggregate capacity refusal at 110 cars), load -> BOL (RIN separation) -> invoice -> retire, cancel-after-invoice locked, index sale collar (280.83/326.37) + rebate + freight cap, hedge close (realized 1595000, unrealized 0 — matches the PRD worked example), permit exceedance -> posture CURTAILED -> grind cap 54000, deviation resolution, CI waterfall (8.000 then truncated 4.000, ci_score 17.100, LCFS 5106.602 — matches PRD). Auth/role/validation/404/405/clock-regression envelopes all correct.

Second boot on a new port confirmed the store starts **empty** (`ERR_PLANT_NOT_FOUND`, zero-row lists) — no seeding anywhere. Both smoke servers killed by PID; no broad `pkill` used; scratch confined to `/tmp/task_2828_impl/`; `worklog.md`, `test_suite/`, `test_helpers/` untouched.

Two judgement calls worth flagging (both resolved in favour of PRD §2.9's explicit precedence ladder over narrative order): BOL checks the loading dimension before the billing dimension, and carbon-project review enforces its segregation of duties purely by the role split (§2.1 says so explicitly; no `X-User-ID` comparison), unlike delivery settlement which does compare user IDs.

## Step 5: Generate unit tests — 2026-09-05T06:36:00.000Z

Subagent summary (verbatim):

Test generation for task_2828 is complete. Both design queues are fully translated.

## Files written (all under the task root, none under `workspace/`)

- `test_helpers/` — 9 files, 2054 lines (`__init__.py` 33, `api_client.py` 469, `api_errors.py` 160, `assertions.py` 209, `constants.py` 145, `factories.py` 316, `fixtures.py` 497, `test_users.py` 77, `types.py` 148)
- `test_suite/` — `conftest.py` (74) plus 17 test modules, 7151 lines total. New this session: `test_15_error_catalogue.py` (611, 15 tests), `test_16_role_authorization.py` (342, 6 tests), `test_17_version_guards_and_limits.py` (384, 6 tests). Earlier: `test_01`–`test_09` (queue A, 39 tests), `test_10` (554/15), `test_11` (936/22), `test_12` (999/17), `test_13` (706/16), `test_14` (454/8).

## Coverage

- **144 tests total.**
- **Queue A (§1.8 difficulty index): 19 instances, 0 stubs, 19/19 translated** -> 39 tests in `test_01`–`test_09`.
- **Queue B (§1.9 corner index): 79 instances, 17 `excluded_because` stubs, 62 non-stub, 62/62 translated** -> 105 tests in `test_10`–`test_17`. By section: entities 11, state_machines 13, calculations 9, validations 12, endpoints 3, errors 7, rbac 3, cross_cutting_complexity_layers 3, consistency_model 1.
- **Skips: none beyond the design's own stubs.** No non-stub instance failed the PRD-first filter. The 17 stubs (calculations 5, cross_cutting 4, state_machines 3, validations 2, endpoints 2, entities 1) each carry an `excluded_because` pointing at the queue A instance that already owns the claim, and were deliberately not emitted.

## Verification run

- Machine-checked every test: exactly one `Design:` line, always the last docstring line; no dual tags; no tag pointing at a stub or a non-existent instance; zero untagged tests.
- Machine-checked every `PRD x.y: "..."` citation against `workspace/PRD.md` after whitespace normalisation — **all verbatim, 0 failures**; no docstring mentions the scaffold.
- All 17 modules `compileall` clean and importable; every `api.*`, `fx.*`, `f.*` and `assert_*` reference resolves against the helpers.
- `ls -la` confirms `workspace/` holds only `INSTRUCTION.md`, `PRD.md` and `implementation/` — no `test_helpers/` or `test_suite/` there. `worklog.md` untouched, no broad `pkill`, scratch confined to `/tmp/task_2828_tests/` (now removed), implementation directory never read.

## Design defects corrected while translating (asserted outcomes preserved)

- `project_type: "CHP"` / `"PROCESS_EFFICIENCY"` are not PRD enum members -> used `COMBINED_HEAT_POWER`; `claimed/verified_reduction 8.000 / 2.500` and `baseline_ci 58.000` violate the declared 1-decimal precision -> `8.0 / 2.5 / 58.0`.
- The stale-tank-version instance asserts "scheduling a blend does not itself bump the destination version", which PRD §3.5 directly contradicts ("A successful schedule ... increments the destination tank's `version`"). I asserted the PRD-derived `version == 4` instead of the design's 3, keeping the instance's actual claim (412 on the stale guard, 201 on the fresh one, `occupancy_end` 2026-09-04T12:00:00Z).
- The design's "success false" envelope assertion has no such field in this PRD; asserted `response_type == "error"` plus the §2.2 error-meta shape.
- Avoided two exact half-up rounding boundaries (a 176.50 x 2.850 ethanol leg and an LCFS figure) by asserting other legs of the same response that land exactly.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk and could not have read it.

## Step 7: Run tests and iterate — 2026-09-05T07:09:00.000Z

Subagent summary (verbatim):

Done. All 8 rounds green.

## Summary

**Iterations run:** 2

**Tests deleted:** none. Both failures were deterministic (failing in 8/8 rounds) and both traced to verbatim PRD sentences that uniquely determine the asserted outcome, so both were implementation defects.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or assertion-helper bug was found.

**Fixes applied to `implementation/`:**

1. `workspace/implementation/derive.py` — `ci_state()`: `lcfs_credit_tonnes_per_million_gal` was unconditionally derived from the formula, so a brand-new plant with the default 60.0 baseline reported 1609.823 instead of 0.000. PRD §3.1 states verbatim "`lcfs_credit_tonnes_per_million_gal` starts at 0.000" and §3.8 scopes its recomputation to "Both are re-derived on every certification", so the figure now stays at its seeded 0.000 until at least one project is `CERTIFIED`. The post-certification value (test_12's 2587.943) is unchanged.

2. `workspace/implementation/derive.py` — new `position_mark()` / `reprice_position()` helpers: `unrealized_pnl_cents` is now a stored, explicitly re-derived field rather than a read-time computation.

3. `workspace/implementation/routes/hedge.py` — `create_position()` stamps `unrealized_pnl_cents: 0` per PRD §3.9 "opens the position at `status` `OPEN` with `contracts_closed` at 0, `contracts_open` equal to `contracts`, both `realized_pnl_cents` and `unrealized_pnl_cents` at 0"; `close_position()` calls `reprice_position()` so a partial close re-prices the remainder and a full close falls to 0.

4. `workspace/implementation/routes/plant.py` — `post_market_marks()` now calls `reprice_position()` for every `OPEN`/`PARTIALLY_CLOSED` position before bumping its version, which is the PRD-named re-derivation trigger ("posting new marks re-prices every `OPEN` and `PARTIALLY_CLOSED` position and leaves `CLOSED` ones alone").

5. `workspace/implementation/serialize.py` — `position_out()` now reads the stored `unrealized_pnl_cents` instead of recomputing it, and the now-dead plant/mark lookup was removed.

Key finding: the old read-time derivation of `unrealized_pnl_cents` made a position opened *after* marks were posted report a non-zero P&L at creation, contradicting the explicit creation-state sentence in §3.9. Confining re-derivation to the two triggers PRD actually names (mark posting, close) satisfies both that sentence and the §3.9 worked examples (-1000000 corn, 300000 natgas, 580000 remainder after a partial close, 1595000 realized on full close — all verified by hand against a live server before the sweep).

**Final sweep:** all 8 parallel rounds green — round 1: 144/144, round 2: 144/144, round 3: 144/144, round 4: 144/144, round 5: 144/144, round 6: 144/144, round 7: 144/144, round 8: 144/144. Zero failures, zero flakes.

Orchestrator verification: independently read all 8 `workspace/implementation/results.$i.json` (timestamped 06:59, i.e. after the fixes) and confirmed `passed == total == 144` in every round. Iteration 1 had been 142/144 in all 8 rounds — a deterministic 2-test gap with no round-to-round variance, consistent with the two real implementation defects the subagent found rather than load-induced flakiness. Step 8 is therefore NOT skipped (5 `implementation/` fixes).

## Step 8: Finalize PRD — 2026-09-05T07:12:00.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` is a 3-line patch of `PRD.md`.

**Counts:** PRD.md 504 lines / 108,112 bytes -> PRD_FINALIZED.md 504 lines / 109,415 bytes. Line count delta 0% (3 lines revised in place, +1,303 bytes, +1.2% by size).

**Changes (one bullet each):**

- §3.8 (line 333) — revise — appended that the certification-driven derivation is the only source of `lcfs_credit_tonnes_per_million_gal`: while no project is `CERTIFIED` it holds the §3.1 opening 0.000 rather than the formula's output for an untouched baseline (explicitly: default baseline 60.0 reports 0.000, not 1609.823), and that `ci_score_g_per_mj` remains unconditionally baseline-less-total — `implementation/derive.py:172-182` (`lcfs = calc.lcfs_credit(score) if certified else D("0.000")`).
- §3.9 (line 353) — revise — `unrealized_pnl_cents` is restated as a **stored** figure re-derived on exactly two triggers (mark posting for `OPEN`/`PARTIALLY_CLOSED`, and closing contracts, using the marks and post-close open count at that instant), with the formula/mark-selection body kept verbatim; the old "read from the plant at evaluation time" read-time semantics is replaced, and it is now explicit that a position opened while marks are already posted still carries 0 until the next trigger — `implementation/derive.py:209-216`, `routes/hedge.py:47`, `routes/hedge.py:105`, `routes/plant.py:80-83`, `serialize.py:298`.
- §3.9 (line 355) — revise — the worked-example paragraph now says the two unrealized figures are what a trigger (a mark posting after the open, or a close) left behind, not a read-time computation, so the examples can't be read back into read-time derivation — same impl sites as above.

**Pre-edit search log:**

1. Edit 1 — (a) subject: `lcfs_credit_tonnes_per_million_gal` / `ci_score_g_per_mj` derivation and their zero states. (b) enumerated: `derive.ci_state()` (only producer), its sole caller `serialize.py:17,43` (plant read path — read-time recompute), `calc.lcfs_credit` / `calc.ci_score` / `calc.ci_waterfall` (`calc.py:251-282`), `derive.certified_projects_in_order`, `derive.recompute_credited`, plus a repo-wide grep for `verification_status` to confirm `CERTIFIED` is terminal with no de-certification/revocation path (`routes/carbon.py:100-146`) — so "while no project has been certified" cannot be re-entered later. (c) adjustment: worded the gate as "while no project has been certified" (state-based, matching the impl's `if certified` list test) rather than "until the first certification" (event-based), and added the explicit clause that the *score* is unaffected so the sentence does not accidentally suggest `ci_score_g_per_mj` is also suppressed.

2. Edit 2 — (a) subject: every write and read of `unrealized_pnl_cents` and everything that changes `contracts_open` or the marks. (b) enumerated by repo-wide grep for `positions|unrealized`: `routes/hedge.py:32-52` (create — literal 0), `:82-107` (close — reprice after `contracts_closed`/status update, so full close hits `contracts_open == 0`), `routes/plant.py:69-85` (mark posting — reprice + `touch` for `OPEN`/`PARTIALLY_CLOSED` only), `derive.reprice_position` / `derive.position_mark` (`derive.py:198-216`, incl. the `plant is None` -> `None` mark path), `calc.hedge_unrealized` (`calc.py:398-403`, the `contracts_open == 0 or mark is None` -> 0 branch), `serialize.position_out` (`serialize.py:283-302`, reads stored), `guards.py:90` and `routes/hedge.py:63-79` (GET/list — pure reads, no reprice), `store.py:28`; also confirmed `post_market_marks` is the only writer of the five mark fields and that no endpoint clears them. (c) adjustments: kept "re-derived from scratch ... rather than accumulated" so the existing 0-when-no-mark and 0-when-flat branches still read as part of the formula rather than as extra triggers; scoped the close trigger to "the position closed" (not "every position") since `close_position` reprices only its own row; said "against the contract count left open after the close" to match the ordering in `hedge.py:98-105`; and left §3.1's mark-posting sentence and §3.9's creation sentence verbatim because both already describe the impl exactly.

Orchestrator note: verified PRD_FINALIZED.md is NOT byte-identical to PRD.md (108112 -> 109415 bytes), so the finalizer genuinely ran.

## Step 9: Complete PRD — 2026-09-05T07:47:00.000Z

Orchestrator decision: Step 9 was run as THREE sequential file-partitioned passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module, rather than one subagent scanning all 3,654 impl lines against the 504-line PRD. A single-shot scan of an implementation this size reliably under-covers, and the failure mode is silent (a `PRD_COMPLETED.md` byte-identical or near-identical to its source). Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from repeating it and were told what earlier passes had already covered. Total: 61 edits (48 ambiguity-pins, 13 mismatch-revisions).

### Pass 1 — global/envelope layer + plant + corn procurement (subagent summary, verbatim)

Performed the `cp` from `PRD_FINALIZED.md` -> `PRD_COMPLETED.md` (only pass 1 does this). PRD_FINALIZED.md 504 lines / 109,415 chars -> PRD_COMPLETED.md 508 lines / 119,433 chars. Char delta +10,018. 23 diff hunks, all inline within existing sections; no new sections.

Counts: ambiguity-pins 16, mismatch-revisions 7.

- §2.1 — insert — ambiguity — whitespace-only auth headers count as empty (`ERR_MISSING_AUTH_HEADERS`); both header values trimmed before role matching — `shape.py:32-36`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 16 chars from upper-case letters and digits (20 total) — `envelope.py:18,28`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, not wall time, so responses with no intervening clock advance share a timestamp — `envelope.py:83,90-95`
- §2.2 — insert — ambiguity — the same error envelope/`meta` pair is used for every non-2xx including 404/405 and 5xx — `app.py:35-46`
- §2.3 — insert — ambiguity — `limit`/`offset` must be canonical base-ten integer literals (trimmed first; `010`/`+10`/`10.0` refused), empty value falls back to default, `offset` has no upper bound and past-the-end yields an empty page with `has_more` false — `shape.py:155-177`, `envelope.py:106`
- §2.3 — insert — ambiguity — every ordering takes the server's insertion sequence as final tiebreak; an empty filter value means "not supplied"; unrecognised enum filter member is `ERR_VALIDATION` — `store.py:65-73`, `shape.py:180-203`, `routes/corn.py:118`
- §2.4 — insert — ambiguity — clock advance answers 200 with `data` = `{current_utc}`; all instants accept any explicit offset (normalised to UTC), a naive string is read as UTC, a date-only string is midnight UTC, output truncated (not rounded) to milliseconds — `util.py:48-69`, `serialize.py:358`, `routes/plant.py:130-138`
- §2.5 — insert — ambiguity — trailing slash insignificant; unmatched path -> 404 and wrong method -> 405, both `ERR_VALIDATION`, both decided by routing before the §2.9 ladder — `app.py:28,37-40`
- §2.5 — revise — mismatch — "four filtered collection lists" corrected to the seven that exist (contracts, shipments, sales, RINs, projects, positions, conditions) — `routes/*.py` list endpoints
- §2.6 — insert — ambiguity — `discount_cents_per_bushel` added to the two-decimal per-unit price list — `calc.py:118`
- §2.6 — insert — ambiguity — decimals serialise as unquoted JSON numbers with full declared width, no exponent form; declared widths are also input gates on the literal (`12.500` refused by a 2-place field), numbers must be finite, whole-number fields accept `5.0`, precision gate precedes range gate — `envelope.py:31-33,43-44`, `shape.py:100-126`
- §2.9 (step 2) — insert — ambiguity — sub-order inside shape validation: JSON-object requirement (absent/empty/`null` body -> `{}`, array/string/number refused), unknown fields rejected before any declared field, declared fields validated in contract order, explicit `null` == omission, no-body endpoints reject any field, string fields non-empty after trimming yet stored verbatim — `shape.py:44-56,129-152,60-68`
- §3.1 — insert — ambiguity — `base_grind_cap_bushels` and `coverage_floor_bushels` are whole bushels; `baseline_ci_g_per_mj` normalised to exactly one decimal (`62` -> `62.0`) — `routes/plant.py:14-22,47`
- §3.1 — insert — ambiguity — a plant path naming an id other than the singleton's own `id` is `ERR_PLANT_NOT_FOUND` even when a plant exists — `guards.py:9-15`
- §3.1 — insert — ambiguity — the five marks are unconstrained decimals (negative/zero/any width) stored and echoed verbatim; marks body validated before plant lookup — `routes/plant.py:24-31,70-78`
- §3.2 — insert — ambiguity — `supplier_name` non-empty with no length cap; `bushels_contracted`/`basis_cents_per_bushel` normalised to exactly 2 places; the entire corn chain requires no plant row and is never gated on `compliance_posture` — `routes/corn.py:16-21,71-88,194-220`
- §3.2 — revise — mismatch — roll preconditions reordered to impl/§2.9 order (state -> open deliveries -> remainder), plus successor `delivery_month` is not required to be later than the source's — `routes/corn.py:146-158`
- §3.2 — revise — ambiguity — a roll answers 201 with the successor row in `data`, never the source — `routes/corn.py:176`
- §3.3 — insert — ambiguity — a `REJECTED` load still stores the five readings, `graded_by_user_id`, both bushel figures and all four discount components plus the total; only the two money fields are suppressed — `routes/corn.py:247-268`
- §3.3 — insert — ambiguity — grading does not require pricing: `net_price_cents_per_bushel` filled at grade only when the contract is already `PRICED`, otherwise null until settlement — `routes/corn.py:273-276`
- §3.3 — revise — mismatch — settlement preconditions reordered: `ERR_SEGREGATION_OF_DUTIES` before `ERR_INVALID_DELIVERY_STATE`, then `ERR_CONTRACT_NOT_PRICED`; the comparison is vacuous while `graded_by_user_id` is null — `routes/corn.py:286-296`
- §3.9 — revise — mismatch — zero-bushel `REALIZED` case reports all four legs as 0.00 with shared costs NOT subtracted; settled-bushels-zero case zeroes the corn leg alone; missing-mark clause removed as unreachable — `calc.py:305-317`
- §3.9 — insert — ambiguity — crush-margin response is a computed view with no `id`/`created_at`/`version` and no `variant` field; shared cost legs named `natgas_cost_cents_per_bushel` / `conversion_cost_cents_per_bushel`; `rolling_yield` to three decimals — `calc.py:320-336`
- §4 `POST /corn-contracts` — revise — mismatch — dropped the non-existent "basis, hedge-to-arrive or flat pricing type" — `routes/corn.py:16-21`
- §4 `GET /corn-contracts` — revise — mismatch — filters corrected to status, delivery month, pricing status, predecessor contract — `routes/corn.py:102-105`
- §4 `POST /corn-contracts/{id}/roll` — revise — mismatch — "in a later month" replaced with "for a named delivery month, returning the successor" — `routes/corn.py:142-176`

Modules scanned: `app.py`, `envelope.py`, `errors.py`, `shape.py`, `store.py`, `util.py`, `guards.py`, `routes/plant.py`, `routes/corn.py`, plus `routes/__init__.py` and only the cross-cutting functions these call. Notes: `errors.py` matches §5 exactly; `store.py` defaults already match §2.4 verbatim.

### Pass 2 — fermentation + tank farm + rail (subagent summary, verbatim)

Did NOT re-`cp`; every edit an in-place `Edit`, and a `difflib` opcode comparison against `PRD_FINALIZED.md` confirms pass 1's edit regions (lines 15–218, 367, 371, 385–389) still present and untouched. 508 lines / 119,433 chars -> 510 lines / 126,432 chars. No new sections (5 `##`, 19 `###`, 127 table rows — all unchanged).

Counts: ambiguity-pins 19, mismatch-revisions 3.

- §2.7 — insert — ambiguity — version-guard fields have a floor of 1 enforced as `ERR_VALIDATION` (not a stale-version failure); comparison is exact equality both directions; both guard values persisted and echoed — `shape.py:33`, `tanks.py:203`, `rail.py:71`, `serialize.py:162,194`
- §3.4 charge — insert — ambiguity — charging requires the plant row (`ERR_PLANT_NOT_FOUND`) and that lookup sits after the `batch_code` uniqueness gate; other fermentation actions never 404 on it — `ferment.py:52-53`
- §3.4 charge — insert — ambiguity — `corn_bushels_charged` normalised to 2 dp but `charge_test_weight_lb_per_bu` stored/echoed exactly as supplied — `ferment.py:56,67`
- §3.4 charged batch — insert — ambiguity — explicit null set on a fresh batch (4 yield fields, 3 volumes, 4 instants/reason) — `ferment.py:73-83`
- §3.4 readings — insert — ambiguity — `hours_elapsed` and `temperature_c` echoed as supplied, not padded to 1 dp — `ferment.py:107,110`
- §3.4 health index — insert — mismatch — window tiebreak is insertion sequence DESCENDING (whole key reversed), contradicting §2.3's earlier-sorts-earlier rule; a low-`hours_elapsed` append leaves the index unchanged yet still bumps `version` — `ferment.py:37-38,124`
- §3.4 state machine — revise — mismatch — `DISTILLING` also refuses readings (PRD named only `COMPLETED`/`DUMPED`); readings list ordering includes the reversed seq tiebreak and accepts `offset` — `ferment.py:102,133-134`
- §3.4 intervene — insert — ambiguity — `intervention_penalty_gal_per_bushel` is the only yield component written before distillation — `ferment.py:151`
- §3.4 distill — revise — mismatch — plant suspension evaluated BEFORE tank service state (PRD prose listed tank first) — `ferment.py:167-168`
- §3.4 complete — revise — ambiguity — complete takes no request body — `ferment.py:188`
- §3.4 complete — insert — ambiguity — with no plant row the RIN switch reads as enabled and a credit batch is still minted — `ferment.py:211`
- §3.5 commission — insert — ambiguity — `opening_gallons > capacity_gallons` is `ERR_VALIDATION`, evaluated before the `tank_code` uniqueness check — `tanks.py:60-62`
- §3.5 OFF_SPEC hold — insert — ambiguity — the loading track row is not rewritten, so its `version` does not move — `tanks.py:142-146`
- §3.5 blend schedule — insert — ambiguity — body field order for the three tank refs vs destination-first existence; product-type tests in that same order; scheduling consults no tank service state and no plant — `tanks.py:29-32,199-209`
- §3.5 blend schedule — insert — ambiguity — null set on a newly scheduled blend — `tanks.py:229-232`
- §3.5 blend execute — insert — ambiguity — a spec violation leaves `output_gallons`/`denaturant_pct` null on a still-`SCHEDULED` blend; execution never gated on the clock or the reserved window — `tanks.py:260-265`
- §3.5 blend list — insert — ambiguity — `tank_role` trimmed/upper-cased and accepts nine alias spellings (three per role), anything else `ERR_VALIDATION` — `tanks.py:43-53,104-109`
- §3.6 schedule — insert — ambiguity — product type is the only source-tank gate; no plant, posture or service-state check; a train scheduled onto an already-held tank lands `SCHEDULED`, not `BLOCKED` — `rail.py:68-84`
- §3.6 schedule landing — insert — ambiguity — null set on a newly scheduled shipment — `rail.py:100-107`
- §3.6 load — insert — ambiguity — the suspension test reads the derived posture, so loading succeeds with no plant registered; the track is not rewritten on load — `rail.py:157,167-168`
- §3.6 cancel — insert — ambiguity — `cancellation_reason` required and stored but NOT in the shipment representation (contrast `dump_reason`) — `serialize.py:189-213`
- §3.6 cancel — insert — ambiguity — only `loaded_gallons` is unwound; `loaded_at`, `bol_number`, `bol_issued_at` left standing — `rail.py:240-246`
- §3.6 shipment list — insert — ambiguity — both id filters existence-checked with `source_tank_id` first, so an unknown tank wins over an unknown track — `rail.py:130-133`

Modules scanned: `routes/ferment.py`, `routes/tanks.py`, `routes/rail.py`, cross-referencing only called functions elsewhere.

Handoff raised to pass 3: pass 1's new §2.6 sentence ("full declared width") is not true of every field — `envelope.py:31` emits a `Decimal` at its own stored exponent, so any field stored without an `rhu()` normalisation echoes the client literal. Pass 2 pinned its own three such fields; pass 3 to audit sales/carbon/permit/hedge for the same pattern and re-scope the sentence.

### Pass 3 — co-products, RINs, carbon, hedging, permits + the §2.6 cross-cutting correction (subagent summary, verbatim)

Did NOT `cp` anything — every change an in-place `Edit`; spot-verified pass 1's §2.1/§2.3 and pass 2's §3.4 edits still present. Before first edit: 510 lines / 126,432 chars. After last: 510 lines / 131,447 chars (+5,015 chars, zero new lines — every change in-paragraph).

Counts: ambiguity-pins 13, mismatch-revisions 3.

- §2.6 — revise — mismatch — pass 1's false universal "carrying their full declared width" re-scoped: a decimal renders at the scale the server holds it; computed/normalised fields padded to declared width, exceptions named — `plant.py:78`
- §2.9 — insert — ambiguity — `contracts_to_close`'s floor of 1 exempted from the "contract counts strictly positive" shape gate; it is a step-11 capacity check reporting `ERR_CLOSE_EXCEEDS_OPEN_CONTRACTS` — `routes/hedge.py:25,92`
- §3.7 — insert — ambiguity — `quote_expires_at` has no relation to the clock at create; a quote may open already expired — `routes/sales.py:20`
- §3.7 — revise — mismatch — mirror-image checks run only after every field passes its own gate, and on `FLAT` the `index_pct`-must-be-null check precedes `quoted_price`-is-required — `routes/sales.py:42-46`
- §3.7 — insert — ambiguity — `quote_reference_mark` is a verbatim copy of the posted mark, echoed at the width it was posted at — `routes/sales.py:57`
- §3.7 — insert — ambiguity — `responded_at` stamped on both decisions, before either branch — `routes/sales.py:130`
- §3.7 — insert — ambiguity — ship takes no request body and rejects any field — `routes/sales.py:153`
- §3.8 — insert — ambiguity — `rin_year` filter must be a plain base-ten integer literal — `routes/rins.py:27`
- §3.8 — insert — ambiguity — a draft's `predecessor_project_id` only existence-checked; full set of fields null at `DRAFT` — `routes/carbon.py:40-60`
- §3.8 — insert — ambiguity — project list filter names are `predecessor_project_id` / `verification_status` / `certification_tier` — `routes/carbon.py:76-78`
- §3.8 — insert — ambiguity — resubmission clears nothing: `review_note`, `reviewed_at`, `revision_count` survive — `routes/carbon.py:111-114`
- §3.8 — insert — ambiguity — review segregation of duties discharged purely by the role split; no `X-User-ID` comparison, so `ERR_SEGREGATION_OF_DUTIES` never arises on a project — `routes/carbon.py:121-124`
- §3.8 — insert — ambiguity — the newly certified project's `version` advances by exactly 1, not 2 (waterfall skips its bump); waterfall ties break on insertion sequence — `routes/carbon.py:152`, `derive.py:185-195`
- §3.9 — insert — ambiguity — a condition opens with `last_exceedance_at` and `resolution_note` null — `routes/permits.py:47-48`
- §3.9 — revise — mismatch — readings may be appended by `ProcessOperator` OR `ComplianceOfficer` (PRD prose named only the officer, contradicting its own §4 table), and the contract validates `value` before `measured_at` — `routes/permits.py:24-28,83`
- §3.9 — insert — ambiguity — every reading append rewrites the condition row (`updated_at` + `version`) even when nothing changed — `routes/permits.py:99`
- §3.9 — insert — ambiguity — the "average still above the limit / gone null" failure on resolve-deviation carries the same `ERR_CONDITION_NOT_IN_EXCEEDANCE`; `exceedance_count` and `last_exceedance_at` survive resolution — `routes/permits.py:126-131`

§2.6 cross-cutting resolution: widened rather than deleted. The sentence now says a decimal is rendered at exactly the scale the server holds it — which for almost every field IS its full declared width, since computed figures and normalised inputs are padded — and then names the closed set of un-normalised fields that echo the client literal: the five market marks of §3.2, the sale's `quote_reference_mark`, plus pass 2's `charge_test_weight_lb_per_bu`, `hours_elapsed` and `temperature_c`. The "not quoted, no exponent form, trailing zeros included, widths fixed because tests compare exact strings" content all preserved.

Audit for part (a): the five pass-3 route modules `rhu()`-normalise every decimal they store; the only un-normalised decimal reaching the wire from that partition is `quote_reference_mark`, a verbatim copy of `plant.mark_soybean_meal_usd_per_ton` / `mark_sbo_cents_per_lb`. Root cause in pass 1's territory (`MARKS_SPEC` declares no `places`); pinned the downstream echo in §3.7 and folded both into the §2.6 exception list.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is 510 lines / 131,447 bytes vs `PRD_FINALIZED.md` 504 / 109,415 — NOT byte-identical to either predecessor, so the scan genuinely ran (the silent-failure mode this partitioning guards against).
- Section structure intact: 5 `##` and 19 `###`, matching the source; no new sections were added by any pass.
- File ends at a real boundary — the final `ERR_INSUFFICIENT_COPRODUCT_INVENTORY` row of the §5 error table.
- Sampled a distinctive token from each pass's edits and confirmed all three survived into the final file (pass 1 `req_`, pass 2 `cancellation_reason`, pass 3 `quote_reference_mark`, `ERR_CLOSE_EXCEEDS_OPEN_CONTRACTS`), so no pass clobbered an earlier one.
- `grep -in "harder than expert|SCAFFOLD"` returns nothing — the difficulty directive never reached any PRD variant.
- Steps 8 and 9 edited only `PRD_*.md`; neither touched `implementation/`, `test_suite/` or `test_helpers/`, so the Step 7 green state (144/144 in all 8 rounds, `results.1.json`–`results.8.json`) remains the valid final test evidence.

## Pipeline complete — 2026-09-05T07:47:00.000Z

All nine steps finished. Final artifacts: SCAFFOLD.yaml + two design indices, workspace/PRD.md, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 17 modules, 144 tests), workspace/implementation/ (21 modules, 64 endpoints), and results.1–8.json all at 144/144.
