# Worklog — task_3441_refrigerated_pet_food_chiller_placement_cold_chain

## Step 1: Create task directory — 2026-10-02T03:34:00.000Z

Task directory pre-allocated by the invoker at `tasks/task_3441_refrigerated_pet_food_chiller_placement_cold_chain/` with `workspace/` inside; verified it exists and is empty. No new index computed, no other task_* directory created. Difficulty instruction: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 2: Generate scaffold — 2026-10-02T04:36:00.000Z

All artifacts are complete and verified. Final report:

## Files written (all parse as YAML, lint clean)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1772 | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1088 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1954 | single key `scaffold_corner_design` |

## Counts
- **Endpoints: 40** (at cap; 39 business under `/cold-chain` + unprefixed `POST /_clock/set_current_utc`)
- **Entities: 12** (Store, SiteEvaluation, PlacementAgreement, Chiller, Placement, TemperatureReading, ServiceTicket, Shipment, ProductLot, InventoryPosition, CapacityProject, TrialCampaign)
- **State machines: 9** (Placement parallel-dimension machine performance×operational; Chiller cyclic repair loop; Agreement with revise self-loop; ServiceTicket/Shipment/ProductLot/InventoryPosition branching; CapacityProject sequenced; TrialCampaign lazy-completing)
- **Calculations: 9** (incl. dual-variant site score and payback, pinned rounding-order quote/payback, tiered frequency plan, excursion accumulator, two conservation invariants, expansion ledger)
- **Errors: 34**, all referenced by ≥1 design instance; **Roles: 7** (2 entity-backed/opaque mix, SoD on capacity approval); **OCC concurrency rules: 2** (both on PlacementAgreement.version)
- **§1.8: 18 instances** (exactly 2 per rule, all differentiation clauses honored); **§1.9: 54 entries** (50 active + 4 excluded_because stubs); 72 unique instance names across both files
- **Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (522 calls scanned)

## Key design decisions / ambiguities resolved
1. **Endpoint budget:** dropped a Technician entity (dispatch windows model the service calendar on the Chiller instead); folded shipment "depart" into create (`departed_at` = creation); removal folded into the date-check sweep; retire covers REMOVE+RELOCATE via `mode`.
2. **Constants all pinned:** temp band 0.0–4.0 °C inclusive, 120 excursion-min/24h, 45-day shelf life, 7-day removal lead, 48h transit (inclusive), velocity floor 40/wk, streak ≥2 for underperformance removal, payback ≤36.0 inclusive, score ≥60.0, base capacity 200 units, 14-day trial gap (exactly-14 allowed), per-model capacity/cost/footprint, 180-cent unit margin, 13/3 weeks-per-month.
3. **Rounding orders pinned with worked literals:** quote = per-component round-then-sum; payback = round monthly units to integer FIRST (cost 291600 @ 10.4/wk → **36.00** pinned vs 35.95 unpinned — also drives the inclusive-boundary ELIGIBLE instance).
4. **Validation priority conflicts pinned:** state>fiscal, safety>temporal, temporal>fiscal, existence>state; trial overlap checked before trial gap (explicit intra-tier order after I caught a shadowing conflict between ERR_TRIAL_WINDOW_OVERLAP and ERR_TRIAL_GAP_VIOLATION).
5. **Rule-8 semantic contrast:** chiller service calendar = half-open `[start,end)` (adjacency legal) vs store trial calendar = closed intervals + mandatory gap.
6. **Bootstrap replay clean:** base manufacturing capacity 200 avoids a capacity deadlock at empty DB; full empty→active-placement→delivery→sweep chain replayed.
7. **Self-healed during generation:** YAML flow-separator quoting for `field?` optionals, `$.data[N].x` captures, and `{id}` in grounds; made chiller serial minting accept an optional `serial_start_seq` so ERR_SERIAL_NOT_UNIQUE is actually reachable; pinned `as_user_id` on capacity-project calls so the segregation-of-duties test is deterministic.
8. **Clock:** unprefixed endpoint, startup default `2026-09-01T00:00:00Z`, forward-only; all fixture dates sit after the default; lazy time transitions (lot EXPIRED, shipment SPOILED, campaign COMPLETED) materialize on read/write, with the failed-past-window deliver persisting SPOILED before returning 422.

Orchestrator verification: all three files exist at the stated line counts (1772/1088/1954), parse as YAML, top-level keys correct (`scenario`/`domain_name`/`api_prefix`/... in SCAFFOLD.yaml; single design keys in the two design files), 40 `path:` entries, `POST /_clock/set_current_utc` present and unprefixed at SCAFFOLD.yaml:1307.

## Step 3: Copy shared files — 2026-10-02T04:38:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3441_refrigerated_pet_food_chiller_placement_cold_chain/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T04:50:00.000Z

All verification checks pass. The PRD is complete and validated.

## Report

**Output:** `workspace/PRD.md` — 298 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle; names the `/cold-chain` mount and the unprefixed clock endpoint)
- §2 Global Specifications: 2.1 RBAC (7 roles + identity semantics: `StoreOperator` entity-backed vs 6 opaque roles), 2.2 API Response Structure (verified **byte-identical** to `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Logical Clock & Lazy Materialization (unprefixed `POST /_clock/set_current_utc`, startup default `2026-09-01T00:00:00Z`, forward-only, `ERR_CLOCK_REGRESSION`), 2.5 Common Resource Properties (incl. `TemperatureReading` carrying only `id`/`created_at`), 2.6 Nested Retrieval, 2.7 Validation Priority Order (all 9 tiers with intra-tier trial order and OCC placement), 2.8 OCC (both rules, `expected_agreement_version`, 412 `ERR_STALE_VERSION`), 2.9 Precision/Rounding (pinned rounding orders), 2.10 Temperature Governance (0.0–4.0 inclusive band, 120-minute severe threshold), 2.11 Conservation Invariants (lot buckets + 3 fleet invariants + 4-decimal shrink rate), 2.12 Capacity Ledger (pinned 6-step order, base 200, atomic headroom rejection)
- §3 Business Logic (8 subsections: site evaluation/scoring, agreements, manufacturing/capacity, installation gate, telemetry/service, performance/removal, distribution/sweep, trials)
- §4 Endpoint table — 40 rows, 4 columns
- §5 Error catalogue — 34 rows, 2 columns

**Rendered counts:** 34/34 error_ids, 9 state machines (41 transitions, all cascades spelled out hop-by-hop), 9 calculations (all formulas in precise prose with pinned rounding orders and the scaffold's worked examples: 66.50/71.00, 36.00/35.95, 2.56/5.12), 2 OCC rules, all constants carried verbatim (32, 60.0, 36.0, 120 min, 200, 40, 2, 48h, 90d, 7d, 14d, 45d, 1.25, 180, 325000/218000/45000/1250/925, weights 0.45/0.25/0.20/0.10/0.20/0.55/0.15/0.10, 240/120 capacities, 8/5 footprints, tiers 300/150/60/25, 13/3 weeks-per-month).

**Contract results:**
- Contract 1 (field coverage): 90 required identifiers (entity fields + endpoint inputs/query/output keys), 90 present in backticks, 0 missing — PASS
- Contract 2 (rule coverage): priority ordering, OCC, transitions, calculations, validation scopes, structured field content, sibling branches all expressed — PASS
- Contract 3 (§3 path purity): 465 backtick tokens scanned, 0 path/method violations — PASS
- Error-id grep cross-check: every real `ERR_*` token from the scaffold appears verbatim (the only non-hit was `ERR_XXX`, the envelope-template placeholder, not an error id) — PASS

The two forbidden design-index files were never opened or referenced.

Orchestrator verification: PRD.md is 298 lines; clock endpoint rendered unprefixed (`POST /_clock/set_current_utc` at lines 76 and 218, "lives outside the `/cold-chain` prefix"); independent scaffold-vs-PRD error-id diff confirms 35 scaffold `ERR_*` tokens, only `ERR_XXX` (template placeholder) absent from PRD — all 34 real error ids covered.

## Step 5: Generate unit tests — 2026-10-02T05:22:00.000Z

Generation complete. Summary:

## Stage A — test_helpers/ (frozen before Stage B)
9 files: `types.py` (11 entity TypedDicts; TemperatureReading correctly omits `updated_at`/`version` per PRD §2.5), `constants.py` (all PRD-pinned values verbatim: temp band 0.0–4.0, 120 min, 45-day shelf life, 7-day lead, 48h transit, floor 40, streak 2, payback ≤36.0, score ≥60.0, base 200, 14-day gap, margin 180, 13/3, per-model costs/footprints/capacities, both weight rows), `api_errors.py` (34 error IDs + HTTP map registered with the framework), `api_client.py` (40 endpoint methods; the clock method calls `/_clock/set_current_utc` unprefixed — grep-verified), `assertions.py` (per-entity + lot-conservation checker), `factories.py` (STORE_ALPHA/BETA/GAMMA/DELTA presets + per-entity payloads), `test_users.py` (7 roles + `make_store_operator_headers` for the entity-backed role), `fixtures.py` (composite fixtures: `setup_active_placement`, `setup_activated_placement`, `setup_suspended_placement`, `trigger_severe_excursion`, `create_released_lot`, `create_delivered_inventory`, etc., all on `get_success_data`).

## Stage B — test_suite/ (13 files, 86 tests)
`conftest.py` + `test_01_store_registration` (5) through `test_12_trials_and_platform` (5).
- **Queue A (Difficulty): 18/18 instances, exactly 2 tests each = 36 tests.**
- **Queue B (Corner): 50/50 non-stub instances, 1 test each = 50 tests.**
- The 4 `excluded_because:` stubs (calculations section) were not translated; all four difficulty cross-references resolve.

## Skip list
None. Every non-stub instance passed the PRD-first two-condition filter.

## Re-derived literals (design index contradicted PRD; PRD wins)
1. **Quote 399000 → 399250**: the PRD §3.1 formula on Store Alpha (STANDARD, 16 sqft, 10 mi) gives 325000+45000+20000+9250 = 399250. All quote/capex/snapshot assertions use 399250 (payback 2.56/5.12 unaffected — both round identically).
2. **Payback 100.76 → 100.82** for forecast 5 (399250/3960); verdict INELIGIBLE unchanged.
3. **Clock-reachability fixes**: two recipes posted readings with `recorded_at` ahead of the 2026-09-01 startup clock (would 400) — a forward clock set was added; the mixed-sweep recipe created lot2 with a future `produced_at` — reordered so the clock advances first. No asserted outcome changed.

## Mandatory audits (all run, all clean)
- **AST audit** over all 12 test files: 86 tests, 68 distinct `Design:` tags; tag set equals exactly the union of non-stub instances; every tag is the docstring's final line; zero untagged / dual-tagged / dangling.
- **PRD citation check**: all 86 docstrings have a ≥10-word quoted fragment surviving literal grep of whitespace-normalized PRD.md.
- `python3 -m py_compile`: all 21 files pass. `pytest --collect-only -q`: **86 collected, 0 import errors.** No skip/xfail markers anywhere.

Orchestrator verification: test_helpers/ has all 9 files, test_suite/ has conftest + 12 test files; 86 `Design:` tags counted via grep; 0 skip/xfail markers; `api_client.py:13` calls `/_clock/set_current_utc` unprefixed; re-derived `STORE_ALPHA_STANDARD_QUOTE_CENTS = 399250` present at constants.py:81 with derivation comment.

## Step 6: Generate implementation — 2026-10-02T05:58:00.000Z

Implementation complete. Final report:

## Files delivered (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| start.sh | 9 | Foreground launcher, guarded pip install, `exec python3 app.py`, `$PORT`/`0.0.0.0` |
| requirements.txt | 1 | `flask>=2.2` |
| app.py | 56 | Flask entry, 12 blueprint registrations, ApiError/404/405/500 envelope handlers |
| state.py | 90 | In-memory DB dicts (boot empty, no seeding), logical clock (default `2026-09-01T00:00:00Z`), `base_entity`/`touch`, datetime parse/format |
| errors.py | 9 | `ApiError(error_id, http_status, message)` |
| envelope.py | 37 | `meta`/`response_type`/`data` envelope, error envelope |
| validate.py | 166 | X-User-ID/X-User-Role auth (7 roles), role gate, body/field/range/enum validation, limit/offset pagination (10/1-100/0) |
| calc.py | 137 | All 7 calculation rules with Decimal round-half-up and pinned orders |
| cascade.py | 123 | Lazy materialization (lot EXPIRED / shipment SPOILED / trial COMPLETED), chiller degrade/repair/retire/terminate cascades, auto-ticket minting |
| serializers.py | 178 | Per-entity serializers (TemperatureReading without updated_at/version) |
| clock.py | 22 | `POST /_clock/set_current_utc` — **unprefixed**, forward-only |
| stores.py | 133 | Stores, site-evaluations, agreements create/list |
| agreements.py | 71 | revise (OCC) / sign / terminate + cascade |
| chillers.py | 105 | Batch registration (serial minting, atomic capacity+uniqueness), list/get, decommission |
| readings.py | 78 | Telemetry post (activation + severe-excursion cascade), list |
| placements.py | 278 | Install gate chain, list/get, evaluate-performance, retire REMOVE/RELOCATE |
| tickets.py | 108 | Ticket open/list/dispatch (half-open overlap)/resolve-as-repair |
| shipments.py | 168 | Shipment dispatch/list/get (lazy SPOILED)/deliver with persist-SPOILED-before-422 |
| lots.py | 77 | Lot registration, get (lazy EXPIRED), QC release |
| inventory.py | 93 | Positions list/get, date-check sweep (EXPIRED → COLD_CHAIN_BREACH → NEAR_EXPIRY order) |
| capacity.py | 79 | Project propose/approve (SoD + sequence pin)/commission (strict order) |
| trials.py | 75 | Campaign create (overlap-409 before gap-422, 14-day boundary inclusive), list (lazy COMPLETED) |

**Total: 2093 lines. All 20 Python modules pass py_compile. 40/40 endpoints registered** (route table verified against scaffold §1.5 exactly, clock unprefixed).

## Smoke-test results (self-run, test-suite-free, dynamic ports)

Happy-path chain: store 201 → eval 201 (composite 70.25, quote 282250, verdict ELIGIBLE) → agreement 201 → sign 200 → chiller batch 201 (FP-0001) → install 201 → reading 201 (chiller ACTIVE) → clock set 200 → list placements 200 (envelope + pagination verified) → unauth probe 401. Deep probe: excursion cascade (2×60min → NEEDS_REPAIR at boundary 120, placement SUSPENDED, AUTO_EXCURSION ticket minted), dispatch/resolve repair (accumulator→0, placement OK), lot→release→ship→deliver→position merge (buckets 400/0/100/0/0), lazy SPOILED past 48h + buckets + deliver-after-spoil 409, revise non-PROPOSED 409, clock regression 400, trial overlap 409 / 13-day gap 422 / exactly-14-day gap 201, sweep near-expiry 100 units + ownership 403, capacity exceeded 422 / SoD 403 / sequence/commission / post-expansion batch 201. Calc self-checks pass all four scaffold worked examples (66.50/71.00, 36.00, 2.56/5.12). Fresh-boot isolation verified (empty store on relaunch). All servers I started were killed by exact PID; ports confirmed freed.

## Interpretations chosen (candidate over-guards for the fix loop)

1. **footprint_score rounds to whole integer** (formula gives no decimal spec; composite rounds to 2dp separately).
2. **forecast_weekly_units one-decimal enforced** — >1 decimal → 400 ERR_VALIDATION ("one decimal place allowed").
3. **trailing_weekly_units validated as integer ≥ 0** (entity field `last_reported_weekly_units` is integer-typed; 0 allowed to exercise the payback zero-velocity guard).
4. **No SiteEvaluation at install/relocate** → staleness skipped, fails fiscal gate as 422 ERR_PAYBACK_INELIGIBLE.
5. **Relocate target agreement not SIGNED** → 409 ERR_AGREEMENT_NOT_SIGNED (PRD says "state-tier precondition" without naming a code; matched the same-named catalog condition rather than generic ERR_INVALID_STATE).
6. **RELOCATE does NOT check duplicate ACTIVE placement at target store** — PRD lists no such gate for relocate; deliberately not invented.
7. **Service-ticket create by StoreOperator: no ownership check** (tier-2 ownership is scoped to readings + sweep only).
8. **Serial "next free sequence"** = 1 + max numeric suffix for the exact prefix (1 if none); `serial_start_seq` must be int ≥ 1.
9. **Datetime echo format**: whole seconds → `...Z`; else 3-digit ms. `created_at`/`updated_at`/meta timestamp always 3-fractional-digit per §2.5/§2.2.
10. **Lot `version` bumps on bucket mutations** (shipment create/deliver/spoil/sweep) and position version bumps on delivery merge — §2.5 "every mutation… including cascade side effects originating on another entity".
11. **REMOVE accepts any of the 3 retired_reason enum values**; only UNDERPERFORMANCE_REMOVAL is streak-gated.
12. **Mode-mismatched retire fields ignored** (target_* under REMOVE, removal_reason under RELOCATE) — declared-optional, inert, not 400/404.
13. **Trial overlap/gap checked against all campaigns at the store regardless of status** (after lazy COMPLETED materialization).
14. **Out-of-range/non-integer limit/offset → 400** (rejected, not clamped).
15. **Unknown GET query params ignored**; non-matching filter values yield empty lists.
16. **Delivery merges into the single non-REMOVED position even when QUARANTINED** (at-most-one-non-REMOVED invariant dominates; status preserved, quarantine awaits sweep).
17. **Deliver with EXPIRED lot → 422 ERR_LOT_EXPIRED before window check**, and no spoil persisted in that case (safety before temporal per PRD 3.7).
18. **Ordering where tiers force entity loads**: sweep ownership (string compare) before store existence → 403 first; readings existence before ownership (needs placement); approve existence → SoD → state (SoD tier 2 < state tier 4).
19. **OCC uses `!=` (exact match)** against current version for both revise and install.
20. **Required string fields are type-checked only** (empty string accepted; PRD states no non-empty rule).

Orchestrator verification: 20 .py files, 2093 total lines, all py_compile clean; `clock.py:12` routes `@bp.post("/_clock/set_current_utc")` unprefixed; `app.py:55` binds `host="0.0.0.0", port=int(os.environ.get("PORT", "10000"))`; 12 blueprint modules registered; start.sh is foreground (`exec python3 app.py`) with guarded pip install.

## Step 7: Run tests and iterate — 2026-10-02T06:09:00.000Z

The 8-round parallel stability sweep is clean on the first iteration. Exiting per protocol.

**Summary**

- **Iterations run:** 1 (initial sweep passed; no fix iteration needed)
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `implementation/`:** none

**Sweep evidence:** All 8 parallel rounds of `prd-bench-local-run --isolation per-test-server` against `test_suite` report `passed == total == 86`, `failed == 0`, `errors == 0`. No flakiness surfaced across the union of rounds — every one of the 86 tests passed in all 8 rounds, so the union of failing tests is empty and the diagnostic protocol (STEP 0–3) had no work to do.

**Artifacts left in place:** `results.1.json` through `results.8.json` remain in `workspace/implementation/` as required output artifacts (each ~25 KB, written 06:05). No edits were made to `worklog.md`, `PRD.md`, `test_suite/`, `test_helpers/`, or `implementation/`.

**Note on earlier exit code:** the sweep's bash wrapper exited 1 only because my post-`wait` inline summary snippet assumed a `nodeid` key in the results schema; the actual schema uses `name`/`file`/`status`. The 8 runs themselves all completed successfully — verified by reading each results file directly.

Orchestrator verification: all 8 `results.${i}.json` files exist (~25 KB each, mtime 06:05) and each independently parses to `passed: 86, total: 86, failed: 0, errors: 0`.

## Step 8: Finalize PRD — 2026-10-02T06:10:00.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline, so `PRD.md` already determined every behavior the implementation exhibits. No `PRD_FINALIZED.md` produced; Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-10-02T06:45:00.000Z

Verification complete: `diff -q` reports the files differ (exit 1), PRD.md untouched at 298 lines/49676 chars. PRD_COMPLETED.md is final. Here is the summary.

## Output

- **Source**: `workspace/PRD.md` — 298 lines, 49676 chars
- **Produced**: `workspace/PRD_COMPLETED.md` — 300 lines, 54767 chars (+2 lines, +5091 chars)
- **Counts**: 27 ambiguity-pins, 3 mismatch-revisions, 2 LOST-RULE flags (left unchanged in the PRD text, per protocol)
- Only `PRD_COMPLETED.md` was edited (cp + Edit-tool only; no heredocs). Implementation, tests, helpers, and worklog untouched.

## Changes (one bullet each)

- §2.3 — insert — ambiguity — pagination: non-integer or out-of-range `limit`/`offset` rejected with 400 `ERR_VALIDATION` (never clamped); `created_at` ties break by creation order; undeclared query params ignored; filters are exact string equality and a non-matching value yields an empty page — `implementation/validate.py:135-166`, `implementation/chillers.py:77-82`
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — `implementation/state.py:46-55`
- §2.5 — insert — ambiguity — datetime echo format: business datetimes (`signed_at`, `departed_at`, `recorded_at`, `expires_at`, `current_utc`, etc.) echo with `Z` suffix, three fractional digits only when sub-second precision exists, plain seconds otherwise; inputs without timezone read as UTC, offsets normalized — `implementation/state.py:64-82`, `implementation/serializers.py`
- §2.7 tier 1 — insert — ambiguity — empty string satisfies required free-text string fields (only presence + JSON type enforced) — `implementation/validate.py:76-79`
- §2.7 tier 2 — insert — **mismatch** — carve-out: where ownership derives from the target resource's stored references (reading-posting), existence resolves first, so 404 precedes 403 on such paths — `implementation/readings.py:32-40`
- §2.8 — revise — ambiguity — OCC is exact equality: behind *or* ahead both yield 412 — `implementation/agreements.py:36-38`, `implementation/placements.py:100-102`
- §3.1 — revise — ambiguity — `footprint_score` rounds half up to a **whole number** before the 100 cap — `implementation/calc.py:56-61`
- §3.1 — revise — ambiguity — `forecast_weekly_units` with more than one decimal place → 400 `ERR_VALIDATION` — `implementation/stores.py:59`, `implementation/validate.py:94-97`
- §3.1 — revise — ambiguity — `distance_miles_from_plant` may be fractional — `implementation/stores.py:31`
- §3.3 — revise — ambiguity — `serial_start_seq` must be ≥ 1; default next-free = 1 + largest numeric suffix in use for the prefix, else 1 — `implementation/chillers.py:22-30,40`
- §3.3 — insert — ambiguity — batch registration responds 201 with the **array** of minted chiller objects — `implementation/chillers.py:69`
- §3.4 — revise — ambiguity — 90-day staleness boundary inclusive; a store with no SiteEvaluation at all is not stale and fails at the fiscal gate with 422 `ERR_PAYBACK_INELIGIBLE` — `implementation/placements.py:40-42,104-107,122-124`
- §3.5 — revise — ambiguity — reading-post ownership: chiller existence (404) resolved first; StoreOperator posting for a chiller with no ACTIVE placement → 403 — `implementation/readings.py:32-40`
- §3.5 — revise — **mismatch** — replaced "arrival order is irrelevant to ordering" with ties on `recorded_at` breaking by arrival order — `implementation/readings.py:76`
- §3.5 — insert — ambiguity — manual ticket creation performs no store-ownership check; any ServiceDispatcher/StoreOperator may open for any existing chiller — `implementation/tickets.py:22-43`
- §3.6 — revise — ambiguity — `trailing_weekly_units` must be a non-negative integer — `implementation/placements.py:159`
- §3.6 — revise — ambiguity — `removal_reason` enum is `UNDERPERFORMANCE_REMOVAL`/`AGREEMENT_TERMINATION`/`RELOCATION`; the streak gate applies only to `UNDERPERFORMANCE_REMOVAL` — `implementation/placements.py:188-190,213-219`
- §3.6 — insert — ambiguity — mode-mismatched retire fields are inert (target fields under REMOVE / `removal_reason` under RELOCATE accepted, ignored, not even resolved) — `implementation/placements.py:197-208,212-219`
- §3.6 — revise — **mismatch** — RELOCATE gates restated in validation-tier order (freshness → footprint → referential → capex → payback), superseding the PRD's original prose order which contradicted §2.7 — `implementation/placements.py:220-261`
- §3.6 — insert — ambiguity — non-SIGNED target agreement yields 409 `ERR_AGREEMENT_NOT_SIGNED` (PRD named no code) — `implementation/placements.py:221-223`
- §3.6 — insert — ambiguity — RELOCATE applies the capex fiscal gate at the target (422 `ERR_CAPEX_BUDGET_EXCEEDED` before the payback gate) — `implementation/placements.py:253-258`
- §3.6 — insert — ambiguity — the duplicate-active-placement gate of §3.4 does not apply to relocation targets — absence of check in `implementation/placements.py:262-278`
- §3.6 — insert — ambiguity — target store with no SiteEvaluation → 422 `ERR_PAYBACK_INELIGIBLE` (not staleness) — `implementation/placements.py:229-231,259-261`
- §3.6 — insert — ambiguity — successor placement's plan fields initialize from the target's latest evaluation forecast and `installed_quote_cents` re-snapshots at target terms; both retire modes respond 200 with the retired placement object — `implementation/placements.py:266-278`
- §3.7 — revise — ambiguity — lazy expiry materializes before the release-state check, so an expired lot yields 422 `ERR_LOT_EXPIRED` even if never released from `QUARANTINE` — `implementation/shipments.py:56-61`
- §3.7 — revise — ambiguity — `accepted_units`/`rejected_units` are non-negative integers; delivery merges into the single non-`REMOVED` position regardless of status (a `QUARANTINED` position absorbs units and stays `QUARANTINED`) — `implementation/shipments.py:113-115,146-156`
- §2.11 — revise — ambiguity — `conservation_invariant` pinned verbatim as `quantity_units == unshipped_qty + in_transit_qty + in_store_qty + removed_qty + spoiled_qty` — `implementation/lots.py:17-18`
- §3.8 — insert — ambiguity — trial overlap/gap rules are checked against every campaign at the store regardless of status, including materialized `COMPLETED` ones — `implementation/trials.py:34-51`

## LOST-RULE flags (PRD text left unchanged pending orchestrator adjudication)

- §2.12 — "`placement_backlog` is the count of `PlacementAgreement` rows in `SIGNED` or `ACTIVE` status that have no `Placement` with `status` `ACTIVE`. `expansion_priority` is `placement_backlog` multiplied by 100 and divided by the larger of `headroom` and 1, reported for information only at 2 decimal places, round half up." — `grep -rn "expansion_priority\|placement_backlog" implementation/` returns zero hits; neither value is computed anywhere, and no endpoint in §4 (nor the impl) exposes a ledger read where "reported" could land. Recommendation: **prd-revise** — the rule has no observable API surface, so an impl-fix would be invisible; revise to mark items 5–6 as informational definitions not surfaced on any endpoint (or drop the "reported" wording).
- §3.8 — "The campaign carries a `name`, a `start_date`, and an `end_date`, each a date at 00:00:00Z delimiting a closed interval" — impl's `dt` validation (`implementation/validate.py:105-115`, `implementation/trials.py:20-25`) accepts any ISO 8601 timestamp for `start_date`/`end_date`; midnight is never enforced, so a non-midnight campaign is accepted (with day-granular `.days` gap arithmetic flooring sub-day remainders). Recommendation: **prd-revise** — the phrase reads as representational, the test suite only ever submits midnight dates (e.g. `test_suite/test_12_trials_and_platform.py:25`), and adding a midnight 400-check post-sweep would risk the clean 8-round sweep for an unexercised path.

## Orchestrator adjudication of the two LOST-RULE flags (checked against SCAFFOLD.yaml, which Step 9 was forbidden to read)

1. **§2.12 expansion_priority/placement_backlog — exonerated, prd-revise applied.** The scaffold defines both terms only inside the capacity-ledger calculation (SCAFFOLD.yaml:1183–1193, "(reported for information; 2 decimals, round_half_up)"); no endpoint output field in scaffold §1.5 carries either one, so there is no observable API surface an impl-fix could attach to. Minimal revision applied to PRD_COMPLETED.md:138 — definitions and derivation order kept verbatim; tail now reads "...an informational ledger quantity at 2 decimal places, round half up, that is not surfaced on any endpoint response."
2. **§3.8 midnight campaign dates — exonerated, prd-revise applied.** The scaffold's only trial validations are ERR_TRIAL_WINDOW_OVERLAP (409) and ERR_TRIAL_GAP_VIOLATION (422); the "(date at 00:00:00Z)" phrasing appears only in entity field descriptions (SCAFFOLD.yaml:516,520) — representational, not an enforced validation, and no midnight-rejection error exists in the 34-error catalog. Adding a server-side midnight rejection would be an invented guard the scaffold never stated. Revision applied to PRD_COMPLETED.md:212 pinning actual impl behavior (ISO-8601 accepted; midnight conventional not enforced; overlap = exact closed-interval timestamp comparison `trials.py:40`; gap day-granular via `timedelta.days` floor `trials.py:43-51`, exactly-14-days allowed, 13d23h59m violates).

Both adjudicated edits applied by the Step 9 subagent via SendMessage continuation. Final report after adjudication:

- `diff -q workspace/PRD.md workspace/PRD_COMPLETED.md` → differ (exit 1); `PRD.md` untouched (298 lines / 49,676 chars); `PRD_COMPLETED.md` final at **300 lines / 55,281 chars** (+2 lines, +5,605 chars vs source).
- Final totals: **27 ambiguity-pins, 3 mismatch-revisions, 2 adjudicated revisions, 0 LOST-RULE flags remaining** — every PRD passage now matches implementation/ behavior uniquely.
- The 3 mismatch-revisions were independently adjudicated by the orchestrator as non-stripping: §2.7 tier-2 carve-out matches scaffold line 1249 (ownership derivation requires entity load → 404 before 403); §3.5 tie-break widens determinism, removes doc-gen over-specification; §3.6 resolves a PRD self-contradiction between §3.6 prose order and §2.7 tier order.

Orchestrator verification: PRD_COMPLETED.md confirmed at 300 lines/55,281 chars with both adjudicated sentences present verbatim (lines 138, 212); all implementation source mtimes ≤ 05:59:22 (before the 06:05 clean sweep — no post-sweep impl writes, sweep remains valid); all 8 `results.*.json` artifacts present.
