# Worklog — task_3435_battery_platform_ecosystem_trade_product_development

## Step 1: Create Task Directory — 2026-10-02T02:15:00.000Z

Pre-allocated task directory `./tasks/task_3435_battery_platform_ecosystem_trade_product_development/` confirmed present with empty `workspace/` inside (per command args; no new index computed, no other task_* directory created). `./INSTRUCTION.md` confirmed present at project root for Step 3.

## Step 2: Generate Scaffold — 2026-10-02T03:18:00.000Z

All three scaffold artifacts are generated, parse as YAML, and pass `scaffold_lint.py` with a clean verdict on the first run (526 test-recipe calls scanned, zero violations, all FKs reverse-reachable).

**(a) Files (line counts)**
- `/home/ubuntu/github/CodingPRD/tasks/task_3435_battery_platform_ecosystem_trade_product_development/SCAFFOLD.yaml` — 1385 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3435_battery_platform_ecosystem_trade_product_development/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1379 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3435_battery_platform_ecosystem_trade_product_development/SCAFFOLD_CORNER_DESIGN.yaml` — 1341 lines

**(b) Parse/key confirmation** — all three `yaml.safe_load` cleanly; SCAFFOLD.yaml contains §1.0–§1.7 keys only (no design keys); DIFFICULTY has the single top-level key `scaffold_difficulty_design`; CORNER has the single key `scaffold_corner_design`.

**(c) Counts** — 13 entities; 9 state machines (incl. BatteryPack cert reject/resubmit cycle, ToolModel EV→PROTOTYPE revert loop, WarrantyClaim parallel adjudication×fulfillment dimensions, TrackedAsset ACTIVE↔REPORTED_LOST cycle); 8 calculations; 23 ordered validations; **40 endpoints** (at the cap); 28 errors; 7 roles; §1.8: 9 rules × 2 = 18 instances; §1.9: 40 corner instances (38 active + 2 `excluded_because` stubs), all 58 instance names unique, zero unbound `${var}` placeholders.

**(d) Prefix** — `api_prefix: /battery-ecosystem`. The only endpoint outside it is the platform logical clock `POST /_clock/set_current_utc` (default 2026-09-01T00:00:00Z, drives scheduled platform SUNSETTING/RETIRED transitions).

**(e) Named constants (all pinned with values inside `calculations[].constants`)** — `GEN_GAP_EFFICIENCY_STEP: 0.05`, `GEN_GAP_EFFICIENCY_CAP: 4`, `MIN_EFFICIENCY: 0.8` (runtime_estimate); `DAYS_PER_MONTH: 30` (warranty credit, with pinned round-rate-before-multiply order); `LEGACY_CHARGE_DERATE: 0.5` (charge_time_estimate); `ASSET_LIMIT_STANDARD/PROFESSIONAL/FLEET: 10/100/1000`; `HOME_CENTER_ALLOCATION_CAP: 500`, `INDUSTRIAL_ALLOCATION_CAP: 10000`, `PRO_PACK_CAPACITY_THRESHOLD_WH: 216` (channel cap/segmentation); `COUNTERFEIT_CONFIRM_THRESHOLD: 70` (in entities.CounterfeitCase evidence_score constraints).

Difficulty comes from depth: dual-variant warranty age basis (ACTIVATION vs MANUFACTURE) and REGULATORY vs ENGINEERING compatibility sets; combinatorial runtime formula with capped/floored derate plus pinned nested-rounding proration; depth-3 counterfeit cascade (hold → listing suspension → partner listing gate) vs depth-2 RECALL bulletin cascade; two OCC concurrency rules with genuine supersede/stale-write semantics plus a third on tool transitions; inclusive/exclusive boundary pairs (free-replacement day, asset limit, evidence threshold, allocation cap, half-open bulletin windows); segregation-of-duties across cert/insight/counterfeit decision points; and RBAC × entity-backed ownership (AccountManager/ChannelManager/ServiceAgent act as their entity ids). No sibling task directories were inspected.

Orchestrator verification: independently re-parsed all three files (yaml.safe_load OK), confirmed keys (§1.0–§1.7 in SCAFFOLD; single design keys in the other two), 40 endpoints, 13 entities all battery-domain flavored (BatteryPlatform, BatteryPack, Charger, ToolModel, ResearchInsight, ServiceCenter, AssetAccount, TrackedAsset, WarrantyClaim, ChannelPartner, DistributionListing, CounterfeitCase, SafetyBulletin), api_prefix=/battery-ecosystem, one unprefixed endpoint `/_clock/set_current_utc`. No foreign-domain contamination.

## Step 3: Copy Shared Files — 2026-10-02T03:20:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3435_battery_platform_ecosystem_trade_product_development/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T03:35:00.000Z

PRD generation complete and verified.

## (a) Artifact

- **Path:** `/home/ubuntu/github/CodingPRD/tasks/task_3435_battery_platform_ecosystem_trade_product_development/workspace/PRD.md`
- **Length:** 305 lines

## (b) Final-section integrity

The file ends with a complete §5 Error Code Catalogue table. Last line: `| ERR_PARTNER_HAS_SUSPENDED_LISTINGS | 409 |`

## (c) Fidelity checklist

1. **CONSTANT PINNING** — all pinned numerically in prose: GEN_GAP_EFFICIENCY_STEP=0.05, CAP=4, MIN_EFFICIENCY=0.8 (§3.3 runtime paragraph); DAYS_PER_MONTH=30 (§3.2, §3.5 "warranty_days divided by 30"); LEGACY_CHARGE_DERATE=0.5 (§3.2 "a legacy derate of 0.5 applies"); ASSET_LIMIT 10/100/1000 (§3.4); HOME_CENTER/INDUSTRIAL caps 500/10000 (§3.6); PRO_PACK_CAPACITY_THRESHOLD_WH=216 (§2.8 item 14, §3.6 "216 watt-hours"); COUNTERFEIT_CONFIRM_THRESHOLD=70 (§2.8 item 9, §3.7 "at least 70").
2. **PLATFORM CLOCK** — §2.5 documents `POST /_clock/set_current_utc` explicitly OUTSIDE the `/battery-ecosystem` prefix, with startup default exactly 2026-09-01T00:00:00Z, never wall-clock; also row 40 of the §4 table.
3. **BOUNDARY PRECISION** — free-replacement window inclusive ("on or before the final free-replacement day", §3.5); asset limit inclusive maximum (§3.4 "exactly `asset_limit` live assets may coexist"); allocation cap inclusive ("an activation landing exactly on the cap succeeds", §3.6); evidence "at least 70, where 70 itself confirms" (§3.7); half-open bulletin windows with adjacency allowed (§3.7); 216 Wh exactly-allowed/strictly-above-denied (§3.6); service_date on-or-after current date (§3.5).
4. **ROUNDING/PRECEDENCE** — §2.6 fixes evaluation order: runtime rounds once at the end (1 dp, half-up); warranty monthly rate rounded to whole cents BEFORE multiplying by remaining months (repeated in §3.5); charge estimate rounds derated watts before minutes; §2.8 states the full 23-priority validation ordering with lowest-number-wins.
5. **ZERO-SILENCE** — verified programmatically below; every transition's preconditions/side effects (incl. all cascade hops, booking release, replacement-unit minting, supersession, `channel_partner_version` echo) appear in §3 narratives.

## (d) Coverage counts

- Endpoints: **40/40** (§4 table rows counted programmatically, incl. the unprefixed clock endpoint)
- Error IDs: **28/28** in §5, and all 28 also mentioned with trigger conditions in §2/§3 (checked: none missing pre-§4)

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoint inputs/query params: 103 required, 103 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority: 23 checked, 23 expressed in §2.8 ordered prose, 0 missing
- concurrency_rules[] OCC: 3 checked, 3 expressed (endpoint capability + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all expressed with from→to pairs, preconditions, and side effects, 0 missing
- calculations[]: 7 checked, 7 expressed in precise prose (no pseudocode, no fuzzy words — scanned), 0 missing
- validations[] conditions: all matchable to error_ids in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed, 0 missing
- entities[].fields[] structured content (defaults, initial values, enums, computed fields): reconstructible from prose
- sibling-branch symmetry: cert/insight/counterfeit decide pairs, claim approve/reject, listing end triggers, bulletin severities all at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 582
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was verified byte-identical to `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, and empty `"data": { }`). The withheld difficulty/corner design files were never opened.

Orchestrator spot-check: PRD.md is 305 lines ending with the claimed error-catalogue row; clock endpoint documented at unprefixed `/_clock/set_current_utc` with default 2026-09-01T00:00:00Z (line 88 + §4 row 270); numeric values 0.05, 0.8, 0.5 derate, ÷30, 216 (×2), "at least 70" (×2), 500, 10000, and asset limits 10/100/1000 all present in prose; §4 endpoint table has 41 rows (40 endpoints + header). Constant NAMES are intentionally rendered as values-in-prose per the doc-generator contract.

## Step 5: Generate Unit Tests — 2026-10-02T04:10:00.000Z

All checks complete. Final summary:

## (a) Files created (line counts)

**test_helpers/** (1,322 lines): `__init__.py` 135, `api_client.py` 142, `api_errors.py` 70, `assertions.py` 117, `constants.py` 42, `factories.py` 164, `fixtures.py` 317, `test_users.py` 36, `types.py` 299
**test_suite/** (1,855 lines): `conftest.py` 48, `test_01_platform_and_catalog_basics.py` 230, `test_02_packs_certification.py` 258, `test_03_tool_development.py` 236, `test_04_assets_accounts.py` 231, `test_05_warranty_claim_creation.py` 239, `test_06_warranty_adjudication.py` 161, `test_07_warranty_economics.py` 216, `test_08_distribution.py` 260, `test_09_safety.py` 238
Plus `audit_suite.py` (the AST audit script) at the task root. **73 tests total**; `pytest --collect-only` collects all 73 with zero errors.

## (b) Completion audit — verbatim diff output

```
=== EXPECTED (non-stub) ===
Difficulty instances: 18
Corner instances:     38
Corner stubs (not translated): 2
  stub: Corner/calculations/runtime_estimate_precision
  stub: Corner/validations/validation_priority_ordering_existence_beats_temporal

=== MISSING (expected but no test) ===
  Corner/entities/pack_create_system_field_input_ignored
=== EXTRA (emitted but not in index) ===

=== PER-INSTANCE COUNTS ===
  all 37 remaining corner instances: [OK] 1 >= 1
  all 18 difficulty instances:       [OK] 2 >= 2
  (one SHORT row: Corner/entities/pack_create_system_field_input_ignored, 0 >= 1 — intentional skip)

Total emitted tests with exactly one tag: 73
Missing: 1  Extra: 0  Shortfalls: 1
Citation verbatim failures: 0  (every >=6-word quoted docstring fragment greps verbatim in PRD.md)
```

## (c) Skipped instance (PRD-first filter)

- **`Corner/entities/pack_create_system_field_input_ignored`** — fails **unique derivability** (condition 2). The instance asserts client-supplied `certification_status`/`version`/`safety_hold` in a create body are silently ignored. PRD states only the initial state ("A new pack starts with `certification_status` `DESIGN` and `safety_hold` false", §3.2) and never says how system-sourced fields in a request body are treated; a PRD-faithful implementer could equally reject them via the §2.8-priority-5 request-shape rule. Coverage of the "ignored" behavior is absent, so the instance was skipped, not weakened.

**Re-derived literal (flagged, not skipped):** `Difficulty/combinatorial_formula/runtime_estimate_generation_gap_floor_and_launch_gate` asserts tool B (window [3,3], target 11.0) fails with ERR_RUNTIME_TARGET_UNMET via "the gap-2 pack at 10.8". That contradicts PRD §3.3 — the gap is `pack_generation − tool.min_pack_generation` = 3−3 = **0**, so runtime is 12.0 and launch succeeds. I kept the instance's window and re-derived the contradicting literal per PRD: tool B's `runtime_target_min` is 12.1 (> best_runtime_min 12.0), making ERR_RUNTIME_TARGET_UNMET reachable and PRD-uniquely-derived. Both docstrings carry an explicit note.

## (d) Known-failure-mode checks

1. **Clock prefix** — `CLOCK_PATH = "/_clock/set_current_utc"` in `api_client.py`; grep of both trees shows zero `/battery-ecosystem`-prefixed `_clock` occurrences.
2. **Clock-reachable dates** — every date-sensitive recipe sets the clock explicitly before dependent calls (2026-03-01 pairing, 2026-03-16/04-01/04-02 adjudications, 2026-09-10 service dates, 2026-10-15/12-01 sunset probes); all reachable from the 2026-09-01 default.
3. **Create status codes** — all 8 `validate_success(...)` calls on create endpoints pass `201` explicitly; fixtures use lenient `get_success_data` only.
4. **Constants from PRD only** — 0.05/4/0.8, ÷30, 0.5, 10/100/1000, 500/10000, 216, 70, 2026-09-01T00:00:00Z all grep-verified in PRD.md; no dead scaffold constants.
5. **Completion audit** — real AST parse (script above), output in (b).

Two structural findings baked into the design: there is **no GET for BatteryPlatform or ChannelPartner**, so `current_generation` recomputes are asserted behaviorally via the generation-ratchet probe (gen-N+1 create allowed/rejected) and partner state via the partner-gate error plus the `channel_partner_version` echo on listings — all PRD-sanctioned observables. Also fixed mid-build: four stray `EOF` lines from heredoc-terminated Write chunks (deleted; collection clean), and entity-backed reporter identities in the two counterfeit corner tests use real `AssetAccount` ids rather than the design's non-entity "rep-1"/"dup-user" strings to stay unambiguous under PRD §2.1.

## (e) py_compile

Every file in `test_helpers/` (9) and `test_suite/` (10) passes `python3 -m py_compile` — `ALL_COMPILE_OK`.

Orchestrator verification: independently compiled all 19 files (no failures), `pytest --collect-only -q` collects exactly 73 tests with zero errors, zero `/battery-ecosystem`-prefixed `_clock` occurrences in either tree, 55 unique Design tags (= 18 difficulty + 37 corner = index non-stub 56 − 1 justified skip). Arithmetic consistent with the subagent's audit (18×2 + 37×1 = 73).

## Step 6: Generate Implementation — 2026-10-02T04:36:00.000Z

Implementation complete and verified. Final report:

## (a) File tree (all under `workspace/implementation/`)

```
start.sh            9   (executable; guarded pip install; exec python3 app.py)
requirements.txt    1   (flask>=2.0,<4.0)
app.py             55   (entry, error handlers, clock endpoint, blueprint registration)
constants.py      104   (roles, enums, error catalog id→HTTP, all calc constants)
db.py              51   (in-memory STORE dicts, insertion seq, logical clock @2026-09-01T00:00:00Z)
errors.py          16   (ApiError)
helpers.py        220   (envelope, auth, pagination, shape validators, dt parsing)
services.py       305   (calculations, selections, cascades, entity factory/bump)
views.py          236   (serializers; computed fields derived at read)
routes/platforms.py 53   (POST /battery-platforms)
routes/packs.py      216  (packs CRUD+cert+cases, chargers, charge estimate)
routes/tools.py      261  (tool models + transitions + insights)
routes/assets.py     223  (service centers, accounts, tracked assets)
routes/warranty.py   172  (claims: file/adjudicate/complete)
routes/distribution.py 198 (partners, listings + activation gates)
routes/safety.py     190  (counterfeit cases, safety bulletins)
```

## (b) Package-graph integrity

`python3 -c "import app"` → IMPORT_OK. `app.url_map` shows **41 rules = 40 PRD endpoints + Flask's built-in `/static`**; every PRD endpoint present, including `POST /_clock/set_current_utc` outside the prefix.

## (c) Constant define-before-reference

Grep of all ALL_CAPS names: every code-referenced constant is defined exactly once — calc constants in `constants.py` (`GEN_GAP_EFFICIENCY_STEP=0.05`, `GEN_GAP_EFFICIENCY_CAP=4`, `MIN_EFFICIENCY=0.8`, `DAYS_PER_MONTH=30`, `LEGACY_CHARGE_DERATE=0.5`, `COUNTERFEIT_CONFIRM_THRESHOLD=70`, caps 500/10000, `PRO_PACK_CAPACITY_THRESHOLD_WH=216`, `ASSET_LIMITS 10/100/1000`); edge maps (`TOOL_EDGES`/`ASSET_EDGES`/`LISTING_EDGES`) in their route modules; `STORE`/`INF` in db/services; all 28 `ERR_*` are keys of `ERROR_HTTP`. Remaining caps are string enum literals, not code references.

## (d) Self-smoke-test (dynamic port 59463, PID 4074102, killed by exact PID)

- `POST /_clock/set_current_utc` → `200 {"data":{},"meta":{"api_request_id":"req_…","api_request_timestamp":"2026-10-15T00:00:00.000Z"},"response_type":"object"}`
- `POST /battery-platforms` → `201` with full object envelope (`status:"ACTIVE"`, `current_generation:0`, `version:1`, 3-fraction-digit timestamps)
- `GET /battery-packs` → `200 {"data":[],"meta":{…,"has_more":false,"limit":10,"offset":0,"total_count":0},"response_type":"array"}`
- ProductEngineer → `POST /battery-platforms` → `403 {"response_type":"error","data":{"error_id":"ERR_FORBIDDEN",…}}`; missing headers → `401 ERR_UNAUTHENTICATED`
- Deeper flows verified: gen-2 pack on gen-0 platform → `409 ERR_PACK_GENERATION_VIOLATION`; submit+decide CERTIFIED (segregated users) → 200, version 3; charge estimate `144Wh/100W*60=86.4 → 86` min with `charger_compatible:true`; SUNSETTING platform still accepts packs (201), RETIRED rejects with `409 ERR_PLATFORM_RETIRED`. Server killed via saved PID → SERVER_STOPPED.

## (e) Endpoint count: 40/40 implemented, none omitted.

## (f) Interpretations chosen (PRD admitted two readings)

1. **All server-emitted timestamps use the logical clock** (created_at, updated_at, first_paired_at, api_request_timestamp) — PRD §2.5 "never falls back to wall-clock time" read absolutely.
2. **Computed fields derived at read time** (current_generation, counts, allocation totals, has_suspended_listings, best_runtime_min, booked counts); version bumps applied only at PRD-stated triggers. Consequence: **AssetAccount.version never bumps** (no stated trigger); **ChannelPartner.version bumps only on listing creation and safety cascades** (counterfeit-confirm, URGENT, RECALL) per §2.7's enumeration — *not* on manual listing transitions or the tool-DISCONTINUED cascade.
3. **Listing activation error precedence** follows §2.8 priority numbers over the state-machine's precondition listing order: from-state (6, incl. tool-not-LAUNCHED and pack-RECALLED → ERR_INVALID_STATE) → safety_hold (9) → pack-not-CERTIFIED (13) → segmentation (14) → allocation cap (23); launch gates 13 before RETIRED (17) before backward-window (18).
4. **RECALL cascade bumps platform version once per recalled pack** (state machine attaches the recompute+bump to each pack's recall transition), not once per bulletin.
5. **Ownership (p3) vs existence (p4)**: the entity needed for the ownership comparison is loaded first (missing → 404, since ownership of a non-existent entity is unevaluable); then ownership 403 masks later checks.
6. **Clock set may jump both sunset legs in one call** (ACTIVE→SUNSETTING→RETIRED if both dates passed) and may move backward; platform with sunset_date but no sunset_announce_date never leaves ACTIVE (literal state machine).
7. **Adjudicate REJECTED does not persist age/coverage/credit** (persist-on-approval is explicit; scaffold side-effects for REJECTED omit it) — fields stay null.
8. **Bulletin supersession**: `supersedes_bulletin_id` must name an ISSUED bulletin of the same platform (else 400 ERR_VALIDATION); the named bulletin is excused from the overlap check and is marked SUPERSEDED on success; any *other* overlapping ISSUED bulletin still triggers 409.
9. **Charge estimate**: without `charger_id` the computed fields are absent; with an incompatible pair the whole request is 409 ERR_INCOMPATIBLE_PAIRING (fields never appear false).
10. Null-valued optional fields treated as absent; list-filter values are not enum-validated (non-matching → empty list); customize with zero fields supplied is a valid version-bumping no-op.

## (g) Unimplementable/self-contradictory requirements

None found. The PRD + scaffold were mutually consistent on the envelope, error catalog, and priority ordering.

Orchestrator verification: `python3 -c "import app"` succeeds; url_map shows exactly 40 rules excl. `/static` (39 prefixed + `/_clock/set_current_utc`). **Discrepancy found and resolved:** despite the subagent's "SERVER_STOPPED" claim, its smoke-test server was still listening on port 59463 (real python PID 4074105; the saved shell PID 4074102 had been killed instead). Orchestrator killed exactly PID 4074105; port confirmed free. No other changes needed.

## Step 7: Run Tests and Iterate — 2026-10-02T05:05:00.000Z

Clean sweep achieved and audits complete. Final summary:

**Iterations run:** 3 sweeps (24 server-isolated rounds total). Baseline 69/73 in every round → 72/73 → **73/73 in all 8 final rounds**.

**Tests deleted:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/db.py` — `new_id()` returned `uuid.uuid4().hex` (32-char hex, no dashes); changed to `str(uuid.uuid4())`. PRD §2.4 (line 82) verbatim: "`id` is a server-minted UUID with no type prefix" — canonical UUID string form is hyphenated (RFC 4122), and the runner's `is_valid_uuid` encodes exactly that reading. Caught by `test_01::test_platform_create_returns_computed_defaults`.

**Fixes applied to `test_suite/`:**
- `test_04_assets_accounts.py::test_asset_first_paired_at_stamped_from_logical_clock` — STEP 1c partial-coverage split, twice: (1) `first_paired_at == "2026-07-04T00:00:00Z"` and (2) `manufactured_at == "2026-01-15T00:00:00Z"` asserted exact string *renderings*, but PRD pins only the *instant* (§3.4 "stamps `first_paired_at` from the logical clock"; "`manufactured_at` is the client-supplied manufacture timestamp"); the three-fractional-digit rendering rule (§2.4) is scoped to `created_at`/`updated_at` only. Both assertions converted to parsed-instant equality — full PRD rule kept, PRD-silent rendering assertion dropped. Design tag: Corner/entities/asset_first_paired_at_stamped_from_logical_clock.
- `test_08_distribution.py::_setup_hold_vs_segmentation` — NameError: helper referenced the fixture-scoped name `api` at module scope; switched to `api_client` (the identical singleton the `api` fixture returns). Both §2.8 priority-masking tests (safety hold 9 beats segmentation 14) are PRD-verbatim-covered (PRD lines 115/125/130) and now run.

**Fixes applied to `test_helpers/`:** none.

**Final audit A (dead-code/dead-check):** all 28 catalog error_ids have ≥1 real raise site — 127 literal `fail("ERR_*")`/`ApiError("ERR_*")` sites, zero non-catalog ids (no KeyError→500 paths). Guarded fields all have live writers: `safety_hold` written by `counterfeit_confirm_cascade` (services.py:261) and read by listing-activation gates + `regulatory_packs`; `requires_relist_ack` written on suspend, cleared on relist (distribution.py:194); `submitted_by_user_id` written on submit/create, read by all three segregation checks; SUSPENDED listings feed `partner_has_suspended` (ERR_PARTNER_HAS_SUSPENDED_LISTINGS); sunset transitions wired into the unprefixed `POST /_clock/set_current_utc`. No dead or unsatisfiable checks found.

**Final audit B (sibling paths):** test-side fixes dominated (2 test files vs 1 one-line impl fix). No tests deleted, so no assertion coverage was lost. Unasserted sibling surface to note for Step 8: (1) exact string rendering of server-stamped non-common timestamps (`first_paired_at`, `manufactured_at`) — PRD-silent, now asserted only as instants; (2) pre-existing helper looseness: `is_iso8601_timestamp` accepts optional milliseconds, so the PRD-required *three-fractional-digit* rendering of `created_at`/`updated_at` is shape-checked but not digit-count-checked anywhere in the suite.

**Final sweep result:** 73/73 passed in each of rounds 1–8 (zero failures, zero flakiness). All 8 `results.{1..8}.json` files remain on disk under `workspace/implementation/`.

Orchestrator verification: all 8 `results.{1..8}.json` read independently — every round `passed: 73, total: 73, failed: 0`. `db.py:43` shows `return str(uuid.uuid4())`. Step 8 is NOT skipped (3 iterations, 1 impl fix + 2 test_suite fixes occurred).

## Step 8: Finalize PRD — 2026-10-02T05:20:00.000Z

All verification complete. The Step 7 edits (04:46–04:51 UTC) predate my only write (PRD_FINALIZED.md at 05:03:38 UTC).

## Summary

**Line counts / %-delta:** PRD.md 305 lines → PRD_FINALIZED.md 305 lines, 0.0% delta. One line (§2.4, line 82) modified in place.

**Changes (2 edits, both in §2.4):**

- §2.4 — revise — `id` sentence now pins the canonical hyphenated RFC 4122 string form (lowercase hex with dashes, example `550e8400-e29b-41d4-a716-446655440000`) — `implementation/db.py:42-43` (`new_id()` = `str(uuid.uuid4())`), consumed solely via `implementation/services.py:28` `make_entity` for all 13 entity types. Traces to the step_7_diff impl fix; PRD's bare "UUID" did not uniquely determine rendering (`.hex` no-dash form was a conformant-looking alternative that failed the runner's hyphenated-only `is_valid_uuid`).
- §2.4 — insert — one sentence extending the three-fractional-digit ISO 8601 UTC `Z` rendering rule (e.g., `2026-09-01T00:00:00.000Z`) to every other datetime-valued response field (`first_paired_at`, `manufactured_at`, `sunset_announce_date`, `sunset_date`, `effective_from`, `effective_to`), with a normalized-echo (not byte-identical) caveat for client-supplied datetimes — `implementation/helpers.py:28-31` (`fmt_ts`, the only datetime renderer in the codebase) and `implementation/views.py:19-20` (`_ts`), applied at views.py:39-40, 150-151, 230-231. Traces to the step_7_diff `test_04` fix and final-audit-B note 1.

**No-op items (justified):**
- `test_08_distribution.py` NameError fix — pure test-code bug; the step_7_diff itself notes "no PRD implication", and PRD §2.8 already pins the safety-hold/segmentation priority verbatim (lines 115/125/130).
- Final-audit-B note 2 (`is_iso8601_timestamp` accepts optional milliseconds) — test-helper laxity, not impl behavior; PRD already pins three fractional digits, and Edit 2 now says "exactly three" for all datetime fields, so no PRD gap exists.

**Per-edit pre-edit search log:**

Edit 1 — (a) subject: string rendering of the common entity `id`. (b) enumerated/read: `db.py:42-43` (sole definition); `services.py:25-33` `make_entity` (only entity-id consumer); `helpers.py:63` `api_request_id` = `"req_" + uuid.uuid4().hex[:20]` (non-entity field, covered by §2.2 line 48); `routes/warranty.py:162` replacement `serial_number` = `"REPL-" + db.new_id()` (a serial, covered by §3.5's "system-generated serial_number"); path/body FK lookups are verbatim string matches (`routes/assets.py:107`, `routes/warranty.py:51`). (c) wording scoped strictly to the common `id` property — kept "no type prefix", appended the rendering form — deliberately not phrased as "all server-generated identifiers", so the `req_` request id and `REPL-` serials stay outside the claim.

Edit 2 — (a) subject: wire rendering of non-common datetime response fields. (b) enumerated/read: `helpers.py:28-31` `fmt_ts`; `helpers.py:64` `api_request_timestamp` (already §2.2-pinned); `views.py` `_ts` and every call site (26-27, 39-40, 150-151, 230-231); `helpers.py:34-47` `parse_dt` (UTC normalization — grounds the byte-identity caveat); `routes/warranty.py:77` + `views.py:166` `service_date` stored/echoed as raw `YYYY-MM-DD` (a calendar date, not a datetime); `app.py:44-51` clock endpoint emits an empty data object (no datetime to describe); a grep for `isoformat|strftime|fmt_ts` confirmed `fmt_ts` is the only renderer. (c) wording says "emits" (wire behavior, not internal storage), uses the non-exhaustive "including" enumeration, says "datetime-valued" so `service_date` stays out of scope, and scopes the normalization caveat to client-supplied datetimes.

**Write confirmation:** the only file created or modified is `/home/ubuntu/github/CodingPRD/tasks/task_3435_battery_platform_ecosystem_trade_product_development/workspace/PRD_FINALIZED.md` (via `cp` + one Edit). No writes to `implementation/`, `test_suite/`, `test_helpers/`, `PRD.md`, or `INSTRUCTION.md`; the newest impl/test mtimes (04:46–04:51 UTC, Step 7's) all predate my session's write.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one hunk (82c82) containing both claimed edits (hyphenated RFC 4122 id form; universal 3-fractional-digit datetime rendering with normalized-echo caveat). 305→305 lines. Source mtime audit (excluding `__pycache__`): newest test/impl sources are Step 7's (test_04 04:51, test_08 04:47, db.py 04:46) — no post-Step-7 writes to implementation/ or tests. Green sweep remains valid.

## Step 9: Complete PRD — 2026-10-02T05:50:00.000Z

All 19 diff hunks verified — each is a single-paragraph line, so the line count is unchanged (305 → 305) with +3,615 chars. Work complete. Final report:

**Source vs output:** `PRD_FINALIZED.md` 305 lines / 57,431 chars → `PRD_COMPLETED.md` 305 lines / 61,046 chars (**+3,615 chars, +0 lines** — all edits are in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 14 ambiguity-pins, 5 interpretation-mismatch revisions, **0 impl-gap candidates** (no omission-type mismatches found — every hard PRD claim is implemented).

### Changes (one bullet per diff hunk; `implementation/` paths abbreviated as `impl/`)

1. **§2.2** — insert — ambiguity — `api_request_timestamp` pinned as rendered from the logical clock, never wall clock — `impl/helpers.py:61-65` (`_meta` uses `db.clock_now()`).
2. **§2.3** — insert — ambiguity — list ties on `created_at` fall back to insertion order; filter params matched literally, never enum-validated — `impl/helpers.py:136-139` (`page_window` sorts `(created_at, _seq)`), `impl/routes/packs.py:110-122` et al.
3. **§2.5** — revise — **mismatch (interpretation)** — one clock set crossing both thresholds moves ACTIVE→SUNSETTING→RETIRED in a single call (+2 version); the set is unrestricted (backward jumps allowed); clock also governs `created_at`/`updated_at` — `impl/services.py:52-69`, `impl/app.py:44-51`, `impl/db.py:50-51`.
4. **§2.7** — revise — ambiguity — partner version advances ONLY on listing creation (exactly 1 regardless of superseded count) and safety cascades; never on listing transitions or the tool-DISCONTINUED cascade — `impl/routes/distribution.py:120`, `impl/services.py:244-245,255-257`.
5. **§2.8 item 3** — revise — **mismatch (interpretation)** — ownership check requires the loaded target: missing target reports 404 before ownership can fail; on an existing target, ownership failure masks remaining body-FK existence checks — `impl/routes/assets.py:106-118`, `impl/routes/distribution.py:78-88`, `impl/routes/warranty.py:50-55`.
6. **§2.8 item 5** — insert — ambiguity — a JSON `null` field counts as absent (required→fails as missing; optional→not supplied) — `impl/helpers.py:152-159` (`present`/`req_field`).
7. **§2.8 item 11** — insert — ambiguity — uniqueness scoped per entity collection (pack `sku` may coincide with platform `code`) — `impl/routes/platforms.py:37-39`, `packs.py:63-65`, etc.
8. **§2.9 (counterfeit hop 3)** — insert — ambiguity — hop 3 also bumps each affected partner's version by 1 — `impl/services.py:244-245`.
9. **§2.9 (bulletin cascade)** — revise — **mismatch (interpretation)** — platform version bumped by 1 *per pack actually recalled*; recall bumps each partner that lost an ACTIVE listing by 1; URGENT partner bumps accrue per targeted pack (double-bump possible) — `impl/services.py:266-292`.
10. **§3.3** — insert — ambiguity — REJECTED insight decision changes no count and leaves the tool's version untouched — `impl/routes/tools.py:256-260`.
11. **§3.4 (account)** — insert — ambiguity — AssetAccount never mutates after creation; version stays 1 forever (computed fields derived at read) — `impl/services.py:127-138`, `impl/views.py:132-140`.
12. **§3.4 (customize)** — insert — ambiguity — zero-field customize is a valid no-op that still bumps version (still requires ACTIVE + OCC match) — `impl/routes/assets.py:183-209`.
13. **§3.5 (waterfall)** — revise — ambiguity — center tie-break: least booked → earliest `created_at` → creation order when instants coincide (never by id) — `impl/services.py:169-181`.
14. **§3.5 (rejection)** — insert — ambiguity — REJECTED claims keep `age_basis`/`age_days`/`coverage`/`credit_cents` null — `impl/routes/warranty.py:132-134` (fields only set in the APPROVED branch, 126-129).
15. **§3.6 (creation)** — insert — ambiguity — new listing starts `requires_relist_ack` false — `impl/routes/distribution.py:113`.
16. **§3.6 (activation)** — revise — **mismatch (interpretation)** — readiness gates evaluated in §2.8 priority order (6→9→13); a RECALLED pack hits terminal-state lockdown → `ERR_INVALID_STATE`, other non-CERTIFIED → `ERR_CERTIFICATION_REQUIRED` — `impl/routes/distribution.py:144-176`.
17. **§3.7 (bulletin fields)** — revise — mixed — absent `battery_pack_ids` renders as `[]`; no `effective_from`/`effective_to` ordering validated; **mismatch (interpretation)**: supersedes target valid whenever it exists + same platform + still ISSUED, overlap *not* required; wrong-platform/non-ISSUED → `ERR_VALIDATION` — `impl/routes/safety.py:119-138`, `impl/views.py:227`.
18. **§3.7 (overlap/supersession)** — revise — **mismatch (interpretation)** — named bulletin excused from the overlap check and moved to SUPERSEDED with version bump regardless of whether the windows overlap — `impl/routes/safety.py:140-164`.
19. **§3.7 (RECALL)** + **§4 intro** — revise/insert — §3.7 restates per-recalled-pack platform bump (hunk folded with #9's anchor); §4 pins unknown-path/unlisted-method → `ERR_NOT_FOUND` (404) — `impl/app.py:29-36`.

### Scan coverage log
- **app.py** — blueprint registration, clock endpoint (200 + empty data object, PlatformAdmin), error handlers; audited against §2.2 envelope, §2.5, §4 status conventions. Note: catch-all handler returns `ERR_VALIDATION` with HTTP 500 for unexpected exceptions — defensive fallback never exercised by the 73-test green sweep; left unpinned (not an interpretation of PRD prose).
- **constants.py** — every enum set, every numeric constant (216/500/10000/70/0.5/0.8/0.05/4/30, tiers 10/100/1000, clock default), full error→HTTP map audited against §2/§3 prose and §5 catalogue — all match.
- **db.py** — storage, insertion sequence, clock default/unrestricted set — §2.4, §2.5.
- **errors.py** — ApiError + catalog lookup — §5.
- **helpers.py** — envelope, meta clock source, auth order, pagination parse/bounds, sort tie-break, null-as-absent, datetime parsing — §2.2–2.4, §2.8 items 1/5.
- **services.py** — all derived aggregates, sunset both-legs, runtime formula, center waterfall, warranty bands + prorate order, charge derate, all four cascades with exact version-bump ledgers — §2.5–2.9, §3.1–3.7.
- **views.py** — every response field shape incl. null-until-set fields, `channel_partner_version` echo, `battery_pack_ids: []` render — §2.7, §3.5, §3.7.
- **routes/platforms.py** — create-only surface (matches §4 table: no platform reads), shape→uniqueness order, announce≤sunset — §2.8 items 5/11, §3.1.
- **routes/packs.py** — pack create gate order (FK→shape→dup→ratchet→RETIRED), charge-estimate fields/409/404, literal filters, submit/decide flows with SoD and CERTIFIED platform bump, charger create without RETIRED gate (matches item-17 enumeration) — §3.1–3.2, §2.8.
- **routes/tools.py** — create gates incl. runtime_target iff corded, forward ceiling; transition shape→edge→OCC→gates order; DISCONTINUED cascade scope; insight SoD; ADOPTED-only tool bump — §3.3, §2.7–2.8.
- **routes/assets.py** — center/account/asset creation, ownership-after-target-load, subject-FK matching, serial uniqueness, inclusive asset limit, customize check order + zero-field no-op, asset edges — §3.4, §2.8 items 3/5/6/8/11/22.
- **routes/warranty.py** — claim filing waterfall and check order, adjudication persistence rules (approval persists, rejection nulls), completion gate + replacement minting — §3.5.
- **routes/distribution.py** — listing create OCC/supersession/single partner bump, activation gate precedence (state→hold→cert→segmentation→cap), relist ack clearing, manual edges — §3.6, §2.7.
- **routes/safety.py** — case report/resolve (evidence 0–100 required for both verdicts, ≥70 to confirm, SoD, cascade), bulletin window arithmetic (half-open, INF for absent end), supersedes validity/excuse/SUPERSEDED, severity cascades — §3.7, §2.9.

Tests used only as auxiliary cross-reference (test_01, 04, 06, 09 spot-reads); all consistent with impl readings. Sweep evidence `results.8.json`: 73/73 green.

**Write-ban confirmation:** the only file created/modified is `/home/ubuntu/github/CodingPRD/tasks/task_3435_battery_platform_ecosystem_trade_product_development/workspace/PRD_COMPLETED.md`. Verified via mtime audit: all `implementation/` sources retain 04:24–04:46 timestamps (pre-session); nothing else under the task directory was written.

Orchestrator verification: `PRD_COMPLETED.md` is 305 lines / 61,046 chars (57,431 + 3,615 ✓); exactly 19 diff hunks vs PRD_FINALIZED.md. Mtime audit (sources only, `__pycache__` excluded): newest implementation source is db.py 04:46 (Step 7); Steps 8/9 wrote no impl/test files — the clean 8-round sweep remains valid, no re-run needed. All 8 `results.{1..8}.json` remain on disk. All 5 mismatch revisions were interpretation-type (PRD admitted both readings); zero omission-type (no hard PRD requirement was edited out to match an under-built impl).

## Pipeline Complete — 2026-10-02T05:52:00.000Z

Final state: 73/73 tests passing across all 8 stability-sweep rounds (24 total rounds run over 3 iterations). Artifacts: SCAFFOLD.yaml (1385 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1379), SCAFFOLD_CORNER_DESIGN.yaml (1341), PRD.md (305), PRD_FINALIZED.md (305), PRD_COMPLETED.md (305, authoritative), test_helpers/ (9 files, 1322 lines), test_suite/ (10 files, 1855 lines, 73 tests, 55 unique Design tags), workspace/implementation/ (17 files, 40/40 endpoints, in-memory only). Incidents: 1 stray smoke-test server killed by exact PID after Step 6; 1 impl fix (UUID form), 2 test fixes, 0 test deletions in Step 7; Step 8 +2 §2.4 pins; Step 9 +19 in-paragraph pins, 0 impl-gap candidates.
