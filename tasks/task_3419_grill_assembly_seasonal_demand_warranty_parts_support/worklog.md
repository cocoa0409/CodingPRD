# Worklog — task_3419_grill_assembly_seasonal_demand_warranty_parts_support

## Step 1: Create task directory — 2026-10-01T22:28:00.000Z

Pre-allocated task directory `./tasks/task_3419_grill_assembly_seasonal_demand_warranty_parts_support/` with `workspace/` inside verified to exist. No new index computed, no other task_* directory created, per orchestration arguments. Scenario: Grill Assembly, Seasonal Demand & Warranty Parts Support (Weber); difficulty instruction "much harder than expert level" passed to scaffold generator only.

## Step 2: Generate scaffold — 2026-10-02T00:02:00.000Z

All three artifacts are complete and verified. Final report:

(a) Files (all parse as valid YAML — `PARSE OK` / `ALL PARSE OK` on every chunk boundary and final pass):
- `SCAFFOLD.yaml` — 1249 lines (§1.0–§1.7; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 798 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1339 lines (single key `scaffold_corner_design`)

(b) Counts: 12 entities, 11 state machines (5 cyclic/branching: WarrantyClaim reopen loop, AssemblyJob no-show reschedule loop, PartSku restock loop, Assembler suspend/reinstate loop, ConnectedDevice update cycle), 40 endpoints (exactly at cap), 40 error codes, 5 roles (PlannerAdmin/ServiceAgent/AppUser opaque; ChannelRep/Assembler entity-backed), 10 calculations, 2 OCC concurrency rules, 47-entry constants block. Difficulty design: all 9 rules, 19 instances (combinatorial_formula carries 3 — modes a/b/c). Corner design: 52 active + 4 `excluded_because` stubs across all 8 taxonomy sections; 75 unique instance names across both files.

(c) Lint verdict (verbatim, final state): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. §1.5 endpoints: 40 | §1.1 entities: 12 | §1.8 instances: 19 | §1.9 instances: 52 | calls scanned: 1026`

(d) Constants: all 47 symbolic constants (coverage years, markdown tiers, fee components, buffer minutes, thresholds, caps, clock default `2026-09-01T00:00:00Z`) carry concrete values in `constants:` and are mirrored in each calculation's `constants:` map; an automated scan found zero named-but-unvalued tokens. All formula-derived asserts are pre-computed literals (e.g., clearance price 32000, assembly fee 12375 with a real per-component-vs-sum-then-round divergence, waterfall redistribution 42/37/available-11, settlement 12300→13800).

(e) Endpoint count = 40 ≤ 40 ✓ — consolidated via action endpoints (`respond`, `adjudicate`, `transition`, `advance`, `lifecycle`) and filtered-list FK reverse views.

Key design choices: quota-allocation archetype with posture gating (Season lifecycle gates allocations/sales/clearance); dual-variant calcs on three distinct domains (warranty settlement, assembler quality, build sizing); depth-3 cascade (NO_SHOW → counter → auto-suspend → mass unassign) and depth-2 cascade (season transition → model discontinuation → lot closeout); two OCC true-races (allocation create-with-supersede on `Season.version`, accept-after-revise on `Allocation.version`); three interval semantics (closed-interval season disjointness, half-open sale windows, buffer-padded in-home assembler windows); acyclic creation graph verified (every gate's dependency is creatable first).

Orchestrator verification: all three files exist, parse as valid YAML (`PARSE OK` ×3), line counts confirmed 1249/798/1339.

## Step 3: Copy shared files — 2026-10-02T00:04:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T00:20:00.000Z

(a) Output. `workspace/PRD.md` — 325 lines, ending at §5 Error Code Catalogue with no audit footer. The design-index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

(b) Constants. All 47 entries from SCAFFOLD.yaml's `constants:` block appear as concrete literals in the PRD prose. Programmatic check against the parsed YAML: `CONSTANTS: total=47 present=47 missing=0` (each name mapped to its literal rendering — e.g. `2026-09-01T00:00:00Z`, "10 years", "3200", "4500", "10000 cents", "15 included miles", "149", "45 minutes", "threshold of 3", "1200 basis points", "11000 basis points", "26").

(c) Endpoints and errors. All 40 scaffold endpoints appear verbatim as paths in PRD §4 (40 table rows, paths-missing=0). All 40 error codes appear backticked in the PRD (missing=0) and all 40 appear as §5 catalogue rows.

Hard Contract reports:
- Contract 1 (Field-Name Coverage): `required=106` (entity fields + endpoint request/query identifiers, `id` universal), `present=106, missing=0` — PASS (two passes; first-pass tooling false-alarmed on §2.2's code fences, re-run with fences stripped).
- Contract 2 (Rule Coverage): validations priority ladder 10/10 expressed in §2.9 with ordering prose; OCC rules 2/2 (both `write_endpoint` + `expected_*_version` + `ERR_STALE_VERSION`/412, no race framing); transitions 79/79 with preconditions, error ids, and side effects; calculations 10/10 with operand order, rounding mode, and constant values in prose; validation conditions all matchable to error ids; endpoint side effects and applies-to scopes expressed; structured field content (defaults, initial values, computed derivations) reconstructible; sibling variants (provisional/final settlement, retail/in-home fee, in-season/clearance pricing, official/provisional quality, forward/actual sizing) at equal density — PASS.
- Contract 3 (§3 Path Purity): 634 backtick tokens scanned in §3, 0 path/method violations — PASS. No pseudocode operators in backticks; no fuzzy/approximating words anywhere.

(d) Scaffold internal ambiguities/contradictions found (not silently resolved — noted here; where the PRD had to say something, the choice is stated):
1. Multi-lot per (season, model). `units_available`/`units_consumed` and the clearance coverage ratio all reference "the InventoryLot of (season, model)" singular, but no uniqueness constraint prevents two lots of the same model in one season (different `build_week`); the formula would double-subtract the same allocation totals. PRD mirrors the singular phrasing.
2. CONSUMED supersede gap. The uniqueness constraint counts `CONSUMED` among live states and says "creating a second supersedes the first," yet no `CONSUMED → SUPERSEDED` transition exists. PRD states the constraint plus the three defined supersede branches; the CONSUMED case is left unspecified.
3. Sale over-consumption. Nothing pins behavior when `quantity` exceeds an allocation's remaining units (no error, no guard). PRD describes only the pinned consumption transitions and invents no rejection.
4. ASSIGN existence vs certification error. The transition precondition bundles "assembler exists and CERTIFIED → else `ERR_ASSEMBLER_NOT_CERTIFIED`," while the existence ladder/catalog implies `ERR_ASSEMBLER_NOT_FOUND` for an unresolvable body reference. Both rules appear in the PRD as scaffolded.
5. Reinstate/decertify guard failures have no nominated error_id (preconditions `provisional_quality_bp` ≥ 7000 / `official_quality_bp` ≤ 4000 exist, no code named anywhere). PRD says the attempt "is rejected" without naming a code.
6. Claim `serial_number` membership violation has no nominated error. PRD maps it to `ERR_VALIDATION` (the only coherent reading, since serial-shape failures are already category-6) — flagged here as a choice.
7. PartSku creation with `stock_quantity` = 0: endpoint description mentions auto-`LOW_STOCK` at ≤ 10 but not `EXHAUSTED`-at-create; the state machine derives `EXHAUSTED` at 0. PRD states the full derivation including at creation.
8. RESTOCK actor mismatch: state machine says `PlannerAdmin`; endpoint table and RBAC ("part transitions shared") grant `ServiceAgent` too. PRD follows the endpoint table + RBAC (both roles).
9. `units_available` formula asymmetry: subtracts `committed_units` (not `allocated_units`) of dead allocations — equivalent only because release/expiry/supersede rewrite `allocated_units := committed_units` first. Mirrored as written.
10. Capacity-check phrasing tension: validations[9] says "sum of active `allocated_units` ≤ `units_available`" while the error catalog says "`allocated_units` exceeds the lot's `units_available` (after supersession recapture); exact fit passes" — since `units_available` already nets out active allocations, the two readings differ. PRD blends both formulations and the tension is preserved here.

Orchestrator verification: PRD.md exists (325 lines); header and §1–§2 prose confirmed on-domain (grill seasonal ops, /grillops prefix, 5 roles).

## Step 5a: Generate test_helpers — 2026-10-02T00:45:00.000Z

Stage 1 of two-stage test generation (helpers frozen first, then test_suite in 5b). Subagent report:

(a) Files (all under `test_helpers/`): `__init__.py` 33 | `types.py` 442 | `api_client.py` 143 | `api_errors.py` 107 | `assertions.py` 373 | `factories.py` 307 | `constants.py` 114 | `test_users.py` 40 | `fixtures.py` 646.

(b) Import smoke test (verbatim): `HELPERS IMPORT OK`. Plus 18/18 calc self-checks passed (fee 12375 / 6399, clearance 32000 / 45000, provisionals 12300/7700/6900/4000, quality 7600/8875, attach 0.75/0.6667/0.3333/0.0, rates 2500/5000, sizing 550/260) — exactly the literals the difficulty/corner instances assert.

(c) Frozen helper API surface for Stage 2:
- Clock (PRD §2.4): `set_logical_clock(to_iso8601)`, `create_clock_payload(to_iso8601)`.
- Headers: `TEST_USERS[...]` shared constants for non-ownership probes; `make_channel_rep_headers(channel_account_id)`, `make_assembler_headers(assembler_id)`.
- ApiClient: all 40 PRD endpoints, raw Response; list methods take `(headers, params=None)`.
- Factories: payload builders for every entity + action payloads (`advance_season_payload`, `respond_allocation_payload(action, expected_allocation_version, ...)`, `job_assign_payload`, `sale_transition_payload`, `adjudicate_claim_payload`, `part_transition_payload`, `firmware_payload`, etc.); uniqueness via `unique_suffix()`, `unique_serial()`.
- Fixtures: creation + state walkers (`walk_season_to`, `walk_claim_to_state`, `setup_claim_in_state`, posture bundles `setup_season_in_allocation`/`setup_offered_allocation`/`setup_accepted_allocation`/`setup_in_season`/`setup_in_season_with_sale`, `setup_in_clearance`, `setup_transitioned_season`, `setup_closed_season`, job lifecycle helpers, `setup_assembler_with_no_shows` (rejects >3 — auto-suspend), OCC-safe `create_allocation` that re-reads season version).
- Assertions: per-entity `assert_*` validators + calc re-derivations (`expected_provisional_settlement_cents`, `expected_final_settlement_cents`, `expected_clearance_price_cents`, `expected_assembly_fee_cents`, `expected_official_quality_bp`, `expected_provisional_quality_bp`, `expected_attach_rate`, `expected_consumption_rate_bp`, `expected_forward_build_units`, `expected_actual_build_units`), `assert_lot_units_conserved`, `round_half_up`.
- Errors: `ApiErrorId` enum (all 40 codes) + `HTTP_STATUS_CODES`; statuses never hardcoded — Stage 2 passes explicit expected status to `validate_success` (201 for POST creates, 200 for actions/reads per PRD §4).

(d) Clock reachability: no design-index date needed re-derivation. PRD's only declared clock mechanism is `POST /grillops/_clock/set_current_utc` with caller-supplied absolute `to_iso8601` (§2.4); PRD states no monotonicity constraint or rejection rule for past instants. Most recipes set the clock backward from the 2026-09-01T00:00:00Z boot value (to 2026-02-01; three recipes to 2018) before building seasons whose windows line up with later forward sets (2026-04-01 ≥ in_season_start 2026-03-01; 2026-08-05/09-06 ≥ clearance_start 2026-08-01; 2026-10-01 ≥ season_end 2026-09-30; 2036-04-01 for the 10-year burner boundary). Reachable iff the clock endpoint is set-anywhere; since PRD names no error for backward moves and index recipes pervasively depend on it, set-anywhere is the uniquely-derivable reading. `set_logical_clock()` is the single helper all fixtures route through.

(e) Constants verification: every value in `constants.py` grep-verified against PRD.md literals: 48/48 patterns matched (clock ISO, coverage years 10/5/3/2, support 7, goodwill 90d, reopen 30d, settlement schedule 3200/2400/4800/1500 + 4500/4500/7500/2500, cap 10000, tiers 15/30/50 with week starts 3/5, coverage bands 6000/2000, ±10/5 pct, cap 70, fee 7999/5005/15mi/149, subsidies 2000/1000/0, buffer 45, jobs default 4, threshold 3, penalty 1200, bonus 25, window 90d, reinstate 7000, decertify 4000, waterfall 5000/4000, low-stock 10, growth 11000, weeks 26, bp base 10000, "APP-PAIR", "1.0.0"). No dead constants.

Orchestrator verification: `HELPERS IMPORT OK` reproduced; 9 files, 2205 total lines.

## Step 5b: Generate test_suite — 2026-10-02T01:30:00.000Z

Stage 2 of two-stage test generation. Subagent report:

(a) Test files (all under `test_suite/`): conftest.py 42 | test_01_season_lifecycle.py 140/6 | test_02_models_and_lots.py 176/6 | test_03_channels_and_allocations.py 258/9 | test_04_allocation_occ_and_waterfall.py 164/4 | test_05_sales_pricing_and_attach.py 242/9 | test_06_assembly_jobs.py 225/7 | test_07_assembler_lifecycle.py 181/4 | test_08_warranty_claims.py 224/9 | test_09_parts_catalog.py 283/9 | test_10_devices.py 88/3 | test_11_auth_and_rbac.py 119/5.

(b) Totals: 71 tests for 71 active instances (19 difficulty + 52 corner), one test per instance, each carrying exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` docstring tag as its last line. The 4 `excluded_because` corner stubs got no test (their difficulty cross-references all resolve).

(c) Skip list: ZERO skips. Every active instance passed the PRD-first two-condition filter. Two judgment notes:
- `Corner/entities/season_create_returns_initial_state_and_echoed_fields`: instance asserts `version == 1`, but PRD §2.5 pins only "increments by exactly 1 on every modification" — no initial value. Asserted 201/PLANNING/all echoed fields (plus positive-int version via `assert_season`), dropped only the `== 1` literal as not uniquely PRD-derivable.
- `Corner/state_machines/assembler_suspend_and_reinstate_with_score_gate`: DECERTIFY-guard rejection's error code not named in PRD §3.6 ("An attempt that fails either guard is rejected."). Kept asserted `ERR_INVALID_STATE` based on PRD §3.2's explicit precedent (`MARK_PARTS_ONLY` before obligation expiry "is `ERR_INVALID_STATE`" — same shape) and §2.9 rung 5's 409-code list; `ERR_VALIDATION` excluded because the body is well-formed.

(d) Collect-only tail (verbatim): `71 tests collected in 0.22s`.

(e) AST tag-audit output (verbatim): `emitted tags: 71; expected non-stub instances: 71; stubs excluded: 4; tags-without-instance: []; instances-without-test: []; matched count: 71; duplicate tags: []; stub cross-references: all 4 resolve to difficulty instances`.

(f) Helper-API gaps: none blocking. Conventions: trigger calls use raw `api_client` + `validate_success(resp, 201|200)` with explicit statuses; setup chains use fixtures' lenient `get_success_data`; `validate_error` relies on registered status map (verified `ERR_STALE_VERSION` → 412). 18 distinctive docstring citation substrings grep-verified verbatim against PRD.md; no "scaffold" mentions and no skip/xfail markers in the suite.

Orchestrator verification: independent `pytest --collect-only` reproduced `71 tests collected in 0.22s`; test_suite totals 2142 lines.

## Step 6: Generate implementation — 2026-10-02T02:30:00.000Z

(a) Files — `workspace/implementation/` (21 files, 3002 total lines, largest 408 — all under the ~500-line cap): requirements.txt 1 | start.sh 10 (executable; guarded pip install; exec python3 app.py; $PORT, 0.0.0.0, foreground) | auth.py 43 | routes_channels.py 55 | store.py 57 (in-memory dicts, empty at boot, no seeding) | app.py 66 | errors.py 66 (full error catalog with exact HTTP statuses) | clock.py 71 (logical clock, boots at 2026-09-01T00:00:00Z, set-anywhere) | routes_devices.py 96 | serialize.py 122 (per-entity field whitelists + lazy clock-dependent refresh) | routes_models.py 126 | routes_assemblers.py 133 | constants.py 137 (all 47 PRD constants literal) | routes_parts.py 137 | util.py 138 | routes_orders.py 170 | routes_allocations.py 199 | routes_claims.py 220 | routes_sales.py 233 | routes_jobs.py 239 | routes_clock_seasons.py 275 (clock endpoint, season lifecycle + advance cascades, lots) | derive.py 408 (all 10 calculations).

(b) compileall verbatim: `IMPORT-OK` / `COMPILE-ALL-OK`.

(c) Constant proof: AST check "unresolved ALL_CAPS name loads: NONE"; "all 47 PRD constants defined exactly once: True".

(d) Smoke tests — five fresh boots, dynamic ports, own PID killed each time:
- Smoke 1 (port 52041) mandated chain: season create 201 PLANNING v1 → clock set 200 → advance BUILD 200 v2 → model create 201 (coverage 10/5/3/2, support 7y, firmware 1.0.0) → lot create 201 (recommended_build_forward_units 550) → advance ALLOCATION v3 → channel HOME_CENTER 201 (subsidy_bp 2000) → allocation create 201 OFFERED v1 (season v4) → lots list units_available 60 → stale OCC 412 ERR_STALE_VERSION → ChannelRep ACCEPT 200 v2 → cross-channel read 403 ERR_FORBIDDEN_OWNERSHIP → missing headers 401 ERR_UNAUTHENTICATED.
- Deep smoke: ALL 39 CHECKS PASSED — in-season price 49900; retail fee 6399 / in-home 11595; exposure 1497000; attach 1.0/0.0; padded-buffer conflict 409 with adjacency allowed; claim REVIEW→APPROVE (provisional 7700)→SETTLE (final 8000, delta 300, auto PartsOrder ALLOCATED, stock decremented); backorder→restock FIFO fill; device pair (sale auto-REGISTERED "APP-PAIR"); firmware UPDATE; waterfall exact (expired 20→0, laggard RELEASED→10, survivor +12 → 42, avail 48); clearance sale 38174 (tier-1 15% then 10% subsidy, two round-half-up); return restores committed units on terminal allocation.
- Edge smoke: ALL 45 CHECKS PASSED — touching-interval ERR_SEASON_OVERLAP; misordered milestones ERR_VALIDATION; early/skip advance ERR_INVALID_STATE; max-concurrent-jobs 409; 3rd no-show auto-SUSPEND (official 6400) with 4th job cascade to REQUESTED; reinstate/decertify guards; electronics claim cap 422 from review, bypass from ESCALATED; settle with empty selector pool; reopen window then ERR_REOPEN_WINDOW_EXPIRED; TRANSITIONED cascade (DISCONTINUED, support_obligation_until 2034-08-31, lots CLOSEOUT); coverage day-granularity boundaries (expiry day IN_COVERAGE, +90d GOODWILL_ELIGIBLE, +91d OUT_OF_COVERAGE); ERR_PARTS_OBLIGATION_EXPIRED 422 free-only; MARK_PARTS_ONLY/RETIRE; REVISE→stale-ACCEPT 412; same-tuple create supersedes.
- Final-path smoke: ALL 34 CHECKS PASSED — SHIP/DELIVER/CANCEL stock restoration (12−2−9=1 LOW_STOCK, cancel→10); MARK_EXHAUSTED zeroing; restock threshold flips; late REGISTER + token; duplicate serial 409; serial-membership on claims; SETTLE-before-APPROVED 409; INFO_REQUESTED loop; UNPAIR/re-pair; CLOSED terminal; pagination meta; posture 409 on TRANSITIONED season.
- One mid-run orphan (bash quoting crash in the subagent's own test script) killed by exact PID via its unique port; no broad kill patterns used.

(e) PRD ambiguities resolved (28 interpretations — full list retained in subagent transcript; key ones): advance-guard failures → ERR_INVALID_STATE 409; reinstate/decertify guard failure → ERR_INVALID_STATE 409; OCC ladder placed after body well-formedness, before capacity/credit, posture rung masks stale-version; sale oversell → ERR_ALLOCATION_CAPACITY_EXCEEDED 409; numeric minima violations → ERR_VALIDATION; duplicate name/code uniqueness → ERR_VALIDATION; RESTOCK only from LOW_STOCK/EXHAUSTED; MARK_EXHAUSTED zeroes stock; SUPERSEDE nonexistent successor → ERR_VALIDATION; PartsOrder create returns version 2 (born REQUESTED v1, synchronous resolution +1); coverage day-granularity inclusive, REOPEN exact timestamps; no-change recompute doesn't bump version; multi-lot per (season,model) aggregates capacity, per-lot stored fields literal; ChannelRep list scoping force-filters (conflicting filter → empty list not 403); return with no live allocation decrements most-recent terminal allocation with committed units; claim serial membership validated only when sale.serials non-empty; settle-created PartsOrder skips obligation gate; unknown action → ERR_VALIDATION, known-forbidden → ERR_UNAUTHORIZED_ROLE; backorder fill strict FIFO no skipping; device view returns only live PAIRED/UPDATING; pagination clamps limit [1,100], offset ≥0, non-integer → ERR_VALIDATION; season overlap checked against ALL seasons closed-interval; TRANSITIONED cascade only discontinues still-ACTIVE/CLEARANCE_ELIGIBLE models; unknown route 404 ERR_NOT_FOUND / wrong method 405 ERR_METHOD_NOT_ALLOWED in standard envelope.

(f) Isolation confirmation: never opened/listed/grepped SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, test_helpers/; read only SKILL.md, INSTRUCTION.md, SCAFFOLD.yaml, PRD.md + own files. Test suite never run. Pure in-memory storage, boots empty, no seeding.

Orchestrator verification: 21 files present; `python3 -m compileall -q .` → COMPILE-ALL-OK; `bash -n start.sh` → STARTSH-SYNTAX-OK; start.sh executable.

## Step 7: Test-iterate fix loop — 2026-10-02T02:50:00.000Z

All 8 rounds are clean: 71/71 passed in every round. The 8 `results.*.json` files remain in `workspace/implementation/` as output-contract evidence.

**Summary**

- **Iterations run:** 2 (sweep 1 identified the failure; fix applied; sweep 2 clean across all 8 parallel rounds).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** `test_suite/test_10_devices.py` — `test_device_firmware_update_cycles_and_unpair_locks`. The final assertion listed the sale's device view *after* UNPAIR and demanded the UNPAIRED record appear (`devices[0]["firmware_version"] == "2.1.0"` → IndexError). PRD 3.9 states only "The devices of a sale are listed through the sale's device view, which returns zero or one entries" plus "A sale supports at most one device in `PAIRED` or `UPDATING`" — post-unpair visibility is not uniquely derivable (a live-only view and a latest-record view are both PRD-faithful and diverge exactly here; the all-records reading actually contradicts "zero or one entries" after unpair+re-pair). Per STEP 1c partial-coverage handling, the device-view assertion was moved to *before* the UNPAIR call (device still `PAIRED`, where every faithful reading agrees the one live device is listed) and now also asserts `meta["total_count"] == 1`; the uncovered post-unpair visibility assertion was removed. The unpair-lockout assertion (`ERR_DEVICE_NOT_PAIRED` on update-after-unpair) is retained and passes.
- **Fixes applied to `implementation/`:** none — the live-only device-view filter in `workspace/implementation/routes_devices.py` (`list_sale_devices`) is one of the PRD-faithful readings and was kept as-is.
- **SHADOW-PATH NOTE:** the only fix was test-side. The post-unpair branch of `GET /grillops/sales/{id}/devices` in `routes_devices.py` — i.e., what the view returns when a sale's sole device is `UNPAIRED` (currently the empty list via the `status in ("PAIRED","UPDATING")` filter) — is no longer exercised by any test. Step 8 should treat that status-filter branch as unasserted when finalizing the PRD.

Orchestrator verification: all 8 `results.{1..8}.json` independently re-read — each `passed=71 total=71 failed=0`; 8 files present. Spot-checked `test_suite/test_10_devices.py` (mtime 02:41, post-dating impl files): `meta["total_count"] == 1` assertion at line 56 precedes the UNPAIR call at line 58, matching the claimed edit; `test_helpers/fixtures.py` mtime 00:47 (Step 5a, untouched); `routes_devices.py` mtime 02:13 (Step 6, untouched). Hand-back claims consistent with source.

## Step 8: Finalize PRD — 2026-10-02T03:05:00.000Z

Line counts / delta: PRD.md 325 lines, PRD_FINALIZED.md 325 lines. 0% line-count delta — one in-place sentence revision on line 231 (§3.9); files are not byte-identical.

Changes:
- §3.9 — revise — The device-view sentence now pins the live-only reading: "lists only the sale's live device — one in `PAIRED` or `UPDATING` — and so returns zero or one entries: once the device is unpaired it no longer appears, and a sale whose only device is `UNPAIRED` yields an empty view." — `workspace/implementation/routes_devices.py:90-94` (`list_sale_devices` filter `d["status"] in ("PAIRED", "UPDATING")`).

Per-edit pre-edit search log (edit 1 of 1):
- (a) Subject: visibility semantics of the sale's device view (GET `/grillops/sales/{id}/devices`) — specifically whether an `UNPAIRED` device record is listed.
- (b) Impl paths enumerated and read/grepped: `routes_devices.py:81-96` (`list_sale_devices`, the view itself); `routes_devices.py:19-51` (`pair_device` — the ERR_DEVICE_ALREADY_PAIRED guard uses the same `("PAIRED","UPDATING")` status pair, so re-pairing after unpair is allowed and the view then returns exactly the new live device while the old UNPAIRED record stays hidden — "zero or one entries" still holds); `routes_devices.py:54-78` (`device_firmware` — UNPAIR sets `UNPAIRED`, UPDATE requires currently-PAIRED); `serialize.py:66,121-122` (`device_out`, status-agnostic); `store.py:23`, `constants.py:112`, `errors.py:36-37`, `app.py:13,33` (no view/filter logic); repo-wide grep for `PAIRED|UPDATING|UNPAIRED` confirmed no other status-filter path exists.
- (c) Wording adjustment: kept the original "zero or one entries" claim (still true under the at-most-one-live-device guard) and scoped the new clause to listing behavior only — no claim about record persistence or deletion, since the impl retains the UNPAIRED row in `db.devices` and merely excludes it from the view.

No other edits: the retained Step 7 assertions needed no pinning — the unpair-lockout (`ERR_DEVICE_NOT_PAIRED` on update-after-unpair) is already verbatim in §3.9, and `meta["total_count"]` semantics are covered by §2.3. Section 4's index line "List devices paired to a sale" is summary-level and already consistent with the pinned reading.

Orchestrator verification: `diff workspace/PRD.md workspace/PRD_FINALIZED.md` shows exactly one hunk (line 231 §3.9), matching the reported revision verbatim; both files 325 lines.

## Step 9: Complete PRD scan — 2026-10-02T03:45:00.000Z

Source vs output: `PRD_FINALIZED.md` 325 lines / 65,536 chars → `PRD_COMPLETED.md` 329 lines / 73,538 chars (+4 lines, +8,002 chars; not byte-identical — 33 diff hunks: 31 inline line-revisions, 2 pure additions).

Counts: 31 ambiguity-pin edits (several bundle multiple sites) and 5 mismatch-revisions. All 28 known interpretation sites verified: 24 needed pins (applied), 4 already pinned and confirmed consistent (SUPERSEDE-successor → ERR_VALIDATION; claim serial-membership rule; device view live-only; season-overlap closed-interval).

Change log (33 bullets; abridged grouping — full detail in subagent transcript): §2.1 undeclared-action ERR_VALIDATION + ChannelRep sub-view ownership/list-filter scoping; §2.2 unknown-path 404 ERR_NOT_FOUND / wrong-method 405 ERR_METHOD_NOT_ALLOWED; §2.3 pagination clamps + non-integer ERR_VALIDATION + created_at ties break by insertion order; §2.4 clock set-anywhere, unparseable to_iso8601 ERR_VALIDATION, serialize as-held, Feb 29 → Feb 28 clamp; §2.5 version starts at 1 + (mismatch) no-op recompute doesn't touch updated_at/version; §2.7 OCC ladder pinned (after body rung 6, before 7/9/10; posture masks stale on create, valid-from masks stale on respond; missing OCC field → ERR_VALIDATION); §2.9 rung 4 ownership extended to sale read + claims/devices views, rung 6 numeric minima, rung 9 uniqueness → ERR_VALIDATION + sale remaining-units under ERR_ALLOCATION_CAPACITY_EXCEEDED; §3.1 advance-guard failures → ERR_INVALID_STATE; §3.2 TRANSITIONED cascade only ACTIVE/CLEARANCE_ELIGIBLE + demand_share_bp bounds inclusive; §3.4 capacity = aggregate units_available over all (season,model) lots + TRANSITIONED sweep leaves CONSUMED untouched; §3.5 oversell → ERR_ALLOCATION_CAPACITY_EXCEEDED + REGISTER requires non-empty proof token / non-SOLD → ERR_INVALID_STATE + return-with-no-live-allocation decrements most-recent terminal (floor 0, none → no adjustment); §3.6 reinstate/decertify guard + wrong-from → ERR_INVALID_STATE + job creation not ownership-scoped / any sale state / distance_mi ≥ 0 priced only IN_HOME + (mismatch) ASSIGN unknown assembler_id → ERR_ASSEMBLER_NOT_FOUND 404; §3.7 reopen window exact timestamps + settlement-created PartsOrder skips §3.8 create gates / decrements stock inside settle + claims view ChannelRep scope; §3.8 chain successor = exactly chain_position+1 + (mixed) RESTOCK only LOW_STOCK/EXHAUSTED / strict-FIFO drain stops at first unfillable / post-drain ladder re-derive / MARK_EXHAUSTED from AVAILABLE-LOW_STOCK zeroes stock + SUPERSEDED/OBSOLETE off the stock ladder + obligation gate no-op while support_obligation_until null / body part_id resolves before sale_id + (mismatch) seq_no from server-wide counter + (mixed) born REQUESTED v1 → create response v2 / short-stock exhausted-chain ERR_PART_UNAVAILABLE / BACKORDERED total_cost fixed at creation / failed-walk REQUESTED residue; §3.9 pairing doesn't gate sale status / RETURNED sale pairs and stays RETURNED / UNPAIR requires PAIRED; §5 catalogue rows for ERR_NOT_FOUND/ERR_METHOD_NOT_ALLOWED.

Rule-violation-suspect mismatches (flagged for adjudication, PRD revised in each case):
1. §3.6 assembler existence — PRD named ERR_ASSEMBLER_NOT_CERTIFIED for nonexistent assembler; impl raises ERR_ASSEMBLER_NOT_FOUND 404 (routes_jobs.py:192-196). Defensible via §2.8 body-reference rule and ladder rung 3 < 7.
2. §2.5 recomputation sentence — plain reading bumps version on every recompute; impl touches only on actual change (derive.py:103-104, 175-176, 215-216). Explains occasional double bumps on guarded assembler actions (routes_assemblers.py:108-132).
3. §3.8 restock landing — PRD said "LOW_STOCK otherwise"; impl re-derives via stock ladder so fully drained restock lands EXHAUSTED (routes_parts.py:117-120; derive.py:393-398).
4. §3.8 failed create residue — PRD said "the create fails with ERR_PART_UNAVAILABLE"; impl persists a REQUESTED order (v1, null resolved_part_id/total_cost_cents) — row inserted before walk, never rolled back (routes_orders.py:107-112, raise sites 41 and 59).
5. §3.8 seq_no — PRD said "per-entity monotonic insertion counter starting at 1"; impl uses one global counter across all entity types (store.py:24, 30-32; routes_orders.py:105). Tie-break purpose intact.
6. §3.8 chain-walk "next higher position" (borderline) — impl walks to exactly position+1 (routes_orders.py:46); sparse chain (1,3,7) ends walk early. Pinned to impl.

Dead-code sweep findings: all 39 PRD-catalogue error codes raised by ≥1 code path (grep-verified); two impl-only ids (ERR_NOT_FOUND, ERR_METHOD_NOT_ALLOWED) pinned into §2.2/§5. **app.py:55-57 defines a 500 handler calling `api_error(...)` without importing it (only `ApiError` imported at app.py:19) — would NameError if a 500 occurred. PRD silent on 5xx; no pin added; reported as broken-but-dormant.** PartsOrder REQUESTED reachable only via failed-create residue (now documented); device UPDATING transitory within a request — not dead. No invoked-but-undefined or defined-but-unreachable PRD behaviors otherwise.

Confirmation: nothing outside PRD_COMPLETED.md written (mtime-verified).

Orchestrator verification: `wc` confirms 325→329 lines, 65536→73538 chars; diff shows 64 changed lines (31 revisions ×2 + 2 additions = 64 ✓ consistent with 33-hunk claim); files differ (not byte-identical).

## Post-Step-9 repair + re-sweep — 2026-10-02T03:26:00.000Z

Step 9's dead-code sweep found a real latent bug: `app.py:57`'s 500-handler called `api_error(...)` — a name never imported (only `ApiError` is imported at app.py:19) — so any 500 would have raised NameError instead of returning the error envelope. Orchestrator action:

1. Read `app.py` and confirmed the defect verbatim.
2. Repaired minimally using the module's own existing idiom (same shape as the 404/405 handlers above it): `return error_response(ApiError("ERR_VALIDATION", 500, "internal server error"))` — preserves the author's chosen error code, uses only imported names, introduces no new error code (so no new PRD mismatch; PRD is silent on 5xx).
3. Per the post-sweep-impl-write rule, invalidated and re-ran the full 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 8 concurrent rounds, fresh `results.{1..8}.json`).

Result: **all 8 rounds pass 71/71, 0 failed** (verified by re-reading every results file; results mtimes 03:25 post-date the app.py edit at 03:23). The final sweep evidence in `workspace/implementation/results.{1..8}.json` is therefore against the exact shipped code.

## Pipeline complete — final artifact state

```
tasks/task_3419_grill_assembly_seasonal_demand_warranty_parts_support/
├── SCAFFOLD.yaml                    (1249 lines, §1.0–§1.7)
├── SCAFFOLD_DIFFICULTY_DESIGN.yaml  (798 lines, 19 instances)
├── SCAFFOLD_CORNER_DESIGN.yaml      (1339 lines, 52 active + 4 stubs)
├── worklog.md                       (this file)
├── test_helpers/                    (9 files, 2205 lines)
├── test_suite/                      (12 files, 2142 lines, 71 tests, 71/71 active instances, zero skips)
└── workspace/
    ├── INSTRUCTION.md
    ├── PRD.md                       (325 lines — generator output)
    ├── PRD_FINALIZED.md             (325 lines — Step 8: §3.9 live-only device view pinned)
    ├── PRD_COMPLETED.md             (329 lines — Step 9: 31 ambiguity pins + 5 mismatch revisions)
    └── implementation/              (21 files, 3002 lines + app.py 500-handler repair)
        ├── start.sh                 ($PORT, 0.0.0.0, foreground)
        └── results.{1..8}.json      (final 8-round sweep: 71/71 ×8, 0 failed)
```

Difficulty: "much harder than expert level" realized as — quota-allocation archetype with season-posture gating; 12 entities, 11 state machines (5 cyclic), 40 endpoints, 40 error codes, 10 calculations (3 dual-variant), 47 constants; depth-3 cascade (NO_SHOW → counter → auto-suspend → mass unassign) and depth-2 cascade (season transition → model discontinuation → lot closeout); two OCC true-races; three interval semantics; round-half-up multi-step pricing (clearance tier → subsidy; per-component assembly fee vs sum-then-round divergence); 10-year component warranty boundaries with day-granularity coverage vs exact-timestamp reopen; strict-FIFO backorder drain; waterfall reallocation.
