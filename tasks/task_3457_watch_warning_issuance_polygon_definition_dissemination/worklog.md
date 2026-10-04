# Worklog — task_3457_watch_warning_issuance_polygon_definition_dissemination

## Step 1: Create task directory — 2026-10-02T06:45:00.000Z

Task directory pre-allocated by the invocation: `./tasks/task_3457_watch_warning_issuance_polygon_definition_dissemination/` with `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T08:41:00.000Z

Scaffold generation complete. Lint verdict block (verbatim):

```
Coverage
  §1.5 endpoints declared:    39
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  552

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3457_watch_warning_issuance_polygon_definition_dissemination/`):
- `SCAFFOLD.yaml` (73 KB) — §1.0–§1.7; no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (88 KB) — single `scaffold_difficulty_design:` key, 19 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` (130 KB) — single `scaffold_corner_design:` key, 43 live instances + 11 `excluded_because:` stubs across all 9 taxonomy sections

**Counts**: 12 entities, 6 state machines, 11 calculations, 11 validations, 39 endpoints (deliberately kept under 40), 35 error codes, 5 roles, 2 OCC concurrency rules. All 9 difficulty rules carry ≥2 differentiated instances (3 for combinatorial_formula — one per mode a/b/c).

**Notable design decisions:**
- **Flat topology under `/alerts`**, archetype temporal-windowing × event-sourcing (verification stats replay confirmed events against issued warning windows). Self-referential `Product.supersedes_product_id` drives upgrade/continuation/correction chains; `NeighborAgreement` is the office-to-office junction gating cross-CWA coordination.
- **Deterministic geometry**: zones are axis-aligned rectangles with surveyed areas; warning polygons are convex (3–12 vertices); overlap via rectangle-clipped shoelace with pinned round-then-divide order (2dp area, then 3dp pct, ≥0.10 inclusive). PLANAR vs GEODETIC office config is one dual-variant pair (identical vertices at lat 60 → 246.42 vs 123.21); POLYGON_STRICT vs COUNTY_FALLBACK verification matching is the other (pod 0.500 vs 1.000 on identical data).
- **Hazard criteria are pinned constants** (e.g. severe wind ≥58, hail ≥1.00, tornado rotation/debris, durations per hazard) rather than a config entity — keeps boundary tests literal and avoids a whole CRUD surface.
- **Cascades spelled per hop**: coordination decline → product revert → sibling-request cancellation (depth 3); warning upgrade → watch supersession → QUEUED record withdrawal (depth 3). Clock advance (`/_clock/set_current_utc`, startup default `2026-09-01T00:00:00Z`) is the sole driver of product expiry, coordination deadline expiry+revert, and dissemination dispatch, in a pinned order.
- **OCC exactly where it belongs**: `expected_product_version` on issue (cascade-bumped versions make literals stale — exercised by the pre-revert 412 corner) and `expected_storm_event_version` on storm PUT. The supersede "race" was re-classified as a plain state precondition per the §1.2.1 filter.
- **WEA rendering is the mode-(c) formula**: message-length ↔ zone-set circularity broken by a pinned order (inclusion threshold computed once, then smallest-overlap drops with zone_code tie-break, budget `min(360, channel.max_message_chars)`, atomic `ERR_MESSAGE_FORMAT_OVERFLOW` when one zone still doesn't fit).
- Every negative-test trigger captures `$.data.error_id` (or matches the lint's negative-name patterns) so role/payload checks are intentionally skipped there; all 552 setup/trigger calls replay cleanly against §1.2/§1.4/§1.6, and all FK reverse-reachability is satisfied via office sub-resources plus filtered lists keyed on the exact FK field names (`issuing_office_id?` on the products list was a lint catch, now fixed).

Orchestrator verification: all three YAMLs exist, parse cleanly (single `scaffold_difficulty_design` / `scaffold_corner_design` top-level keys on the design files; §1.0–§1.7 keys on SCAFFOLD.yaml), and grep confirms NWS domain content (159 hits for watch|warning|polygon|office|hazard; api_prefix `/alerts`).

## Step 3: Copy shared files — 2026-10-02T08:44:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T08:50:00.000Z

Done. PRD generated and all three hard contracts pass.

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3457_watch_warning_issuance_polygon_definition_dissemination/workspace/PRD.md` — 295 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (5 roles + identity prose: `Forecaster`/`MeteorologistInCharge` entity-backed vs `PlatformAdmin`/`VerificationAnalyst`/`EmergencyManager` opaque), 2.2 Response Structure (verified byte-identical to the verbatim source), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Common Resource Properties & Logical Clock, 2.5 Precision/Rounding/Time Windows, 2.6 OCC, 2.7 Domain Vocabulary (all enums), 2.8 Validation Pipeline & Error Precedence (11 tiers), 2.9 Atomic Mutations & Clock-Driven Transitions
- §3 Business Logic: 3.1 Offices/Zones/Agreements, 3.2 Channels & Forecaster Roster, 3.3 Storm Events, 3.4 Drafting Products (geometry, zone resolution, impact tags), 3.5 Coordination & Issuance, 3.6 Dissemination, 3.7 Cancellation/Supersession/Clock, 3.8 Verification & Performance Bands, 3.9 Emergency Actions
- §4 Endpoint Definitions (39-row, 4-column table), §5 Error Code Catalogue (35-row, 2-column table)

**Scaffold rules rendered carefully:**
- *Constants*: all thresholds embedded in prose — wind/hail/rain criteria for all 5 hazards at both WARNING and ADVISORY floors, duration ranges (15–120/15–90/30–180/60–720 min), 0.10 zone-inclusion overlap, 360-char WEA budget, 3-retry maximum, 60-minute evacuation re-entry buffer (equality allowed), far > 0.70 / pod < 0.50 strict band thresholds (pod exactly 0.500 stays SATISFACTORY), KM_PER_DEG 111.0 with PLANAR vs GEODETIC cosine factor, coordination_timeout_minutes default 15, 3–12 polygon vertices, clock default `2026-09-01T00:00:00Z` never wall-clock.
- *Formulas*: shoelace area, two-step rounding order for overlap (area rounded to 2 decimals BEFORE the percentage division — forbidden alternative order stated), pinned WEA truncation order (include-once, drop smallest-overlap with lexicographically-greatest tiebreak, never recompute the 0.10 threshold, single-zone overflow → `ERR_MESSAGE_FORMAT_OVERFLOW`), per-event lead floored to whole minutes before averaging, half-open `[issued_at, window_end)` matching with boundary-inclusive polygon points.
- *Cascades*: decline → product revert + sibling requests CANCELLED (attributed to the reversion); supersession → prior SUPERSEDED + QUEUED records WITHDRAWN + still-REQUESTED requests CANCELLED; cancel/expire → QUEUED withdrawn; clock advance order pinned (product expiry → coordination expiry/revert → dispatch); adjudicate-CONFIRM → `verified_event_count` +1 and UNVERIFIED→VERIFIED flip; statistic create → office `performance_band` + `last_statistic_at` + version.
- *Error precedence*: the subtle DRAFT-issue split is rendered — satisfiable-but-unsubmitted coordination → `ERR_COORDINATION_NOT_ACKED`, unsatisfiable office → `ERR_ZONE_OUTSIDE_CWA`/`ERR_POLYGON_OUTSIDE_CWA` from the final referential tier, never the former. Per-error HTTP statuses follow the §1.6 catalog (e.g. overlap/evacuation/duplicate at 409, supersede-chain/geometry at 422).

**Hard contract reports:**
```
Field coverage check:
- entities[].fields + endpoint input/query/path identifiers: 109 required, 109 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 11 tiers expressed in fixed-order prose with consequence sentences
- concurrency_rules[] OCC rejections: 2/2 expressed (write op + expected_*_version + ERR_STALE_VERSION/412, no race framing)
- state_machines[].transitions: 22/22 expressed with preconditions and side effects
- calculations[]: 11/11 expressed as precise reconstructible prose
- validations[] conditions: all matchable to error_id in prose; all 35 error IDs appear in §1–§3
- endpoints[].side_effects / applies_to: all expressed; structured field content (defaults/nullability) placed on owning entities
- sibling-branch symmetry: impact-tag branches, per-hazard threshold/duration pairs, matching variants, settle/respond/adjudicate outcomes rendered at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 414
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
Status: PASS
```

The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened or referenced at any point.

Orchestrator verification: PRD.md is 295 lines, 58 `ERR_` tokens present, spot-grep confirms pinned constants (clock default 2026-09-01T00:00:00Z, 58 mph, 1.00 in, 360 chars, 0.10 overlap, 111.0 km/deg) and notes the clock capability mounted outside `/alerts`.

## Step 5a: Generate test_helpers — 2026-10-02T09:15:00.000Z

Stage 1 is complete and audited. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3457_watch_warning_issuance_polygon_definition_dissemination/test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `types.py` | 427 | 21 enums (roles, hazards, levels, all six lifecycle machines) + TypedDicts for all 12 entities (all `common_fields: true`, so all carry id/created_at/updated_at/version), `Vertex`/`Polygon`, `WeaPreview` |
| `constants.py` | 139 | All PRD thresholds (below) + canonical 0.1°×0.1°/123.21 sq km geometry |
| `api_errors.py` | 109 | `ApiErrorId` — all **35** catalog entries — + HTTP map, registered via `set_error_http_status_map` at import |
| `api_client.py` | 209 | `ApiClient(GenericApiClient)`, one method per endpoint (38 business + 2 platform), `api_client` singleton |
| `test_users.py` | 111 | `TEST_USERS` (opaque roles canonical; entity-backed fallbacks clearly marked non-ownership-only), `make_forecaster_headers`/`make_mic_headers` taking live Forecaster ids, `headers_without_identity`, `make_undeclared_role_headers` |
| `factories.py` | 353 | One factory per creatable entity; counter-generated unique codes (office_code kept to 2–4 letters via base-26); `square_polygon`/`triangle_polygon`; `warning_polygon_payload`, `zone_product_payload`, OCC payloads |
| `assertions.py` | 292 | `assert_<entity>` ×12, `assert_product_window_consistent`, `assert_wea_preview`, and `validate_created` (explicit 201 wrapper — create helpers never default to 200) |
| `fixtures.py` | 723 | 45 helpers over 3 tiers: primitives (clock/settle/CRUD/transitions), `setup_office_with_{forecaster,zone,storm}`, `setup_issued_{warning,watch}`, `setup_coordinated_offices`, `setup_pending_coordination_watch`, `setup_issued_coordinated_watch`, `setup_mic_pair`; all setup via `get_success_data`; identity always threaded from live forecaster rows |
| `__init__.py` | 76 | Barrel: framework generics + all PRD-specific names |

## Constants cross-checked against PRD.md (grep-verified, no scaffold/PRD divergence)

Wind/hail/rain floors at WARNING (58/1.00, rotation+debris, 2.0, 74, 35) and ADVISORY (40/0.75, rotation, 1.0, 39, 25) — line 163; durations 15–120/15–90/30–180/60–720/60–720 — line 165; impact tiers 80/2.75/debris and 70/1.75 — line 149; overlap ≥ 0.10 — line 145; WEA min(360, channel budget) — lines 125/177; MAX_RETRIES=3 ("exactly three failed attempts") — line 181; evacuation buffer 60 min, equality allowed — line 205; far > 0.70 / pod < 0.50 strict — line 199; KM_PER_DEG 111.0 — line 147; coordination_timeout default 15 — line 121; polygon 3–12 vertices — line 103; clock start exactly 2026-09-01T00:00:00Z — line 83. No adjudication was needed anywhere.

## Clock/prefix edge cases handled

- **Unprefixed platform endpoints**: `set_clock` → `POST /_clock/set_current_utc`, `settle_dissemination_record` → `POST /_dissemination/settle`, both without the `/alerts` prefix (PRD §2.4 "mounted outside the /alerts path prefix"; §4 table). All 38 business methods use `ALERTS = "/alerts"`.
- **Clock reachability**: every design-recipe literal is ≥ the 2026-09-01T00:00:00Z start and monotonically non-decreasing within its recipe; fixture defaults mirror them (canonical issue clock 10:00, per-hazard `DEFAULT_WARNING_EXPIRES` inside each duration range, zone-product default window 2026-09-02 so no clock set is needed before drafting).
- **Singleton/module shadowing**: the `api_client` singleton coexists with the `api_client` submodule; verified via importlib that each of the 8 submodules imports as a true `ModuleType`.

## Audit output

- AST parse: all 9 files OK.
- Import audit: `import test_helpers` + `importlib.import_module` over every submodule — all OK; barrel smoke-import (`validate_success`, `ApiErrorId`, `TEST_USERS`, `setup_issued_warning`, constants) OK.
- No "scaffold" references remain in generated code (one English-use comment reworded).
- Per-file tails re-read after each write; no truncation.

Ready for Stage 2 (test_suite generation).

Orchestrator verification: 9 files / 2439 lines on disk; independent re-run of the import audit passes (all 8 submodules import as modules; barrel names resolve); grep confirms `/_clock/set_current_utc` is unprefixed in api_client.py.

## Step 5b: Generate test_suite — 2026-10-02T10:10:00.000Z

Stage 2 is complete. Final summary:

## Files written (13, all under `/home/ubuntu/github/CodingPRD/tasks/task_3457_watch_warning_issuance_polygon_definition_dissemination/test_suite/`)

| File | Lines | Tests |
|---|---|---|
| conftest.py | 33 | — |
| test_01_config_entities.py | 338 | 9 |
| test_02_product_geometry.py | 172 | 5 |
| test_03_impact_and_wea_rendering.py | 230 | 6 |
| test_04_issuance_criteria.py | 247 | 6 |
| test_05_coordination_lifecycle.py | 311 | 8 |
| test_06_coordination_gates.py | 216 | 6 |
| test_07_supersede_chains.py | 286 | 7 |
| test_08_dissemination.py | 246 | 7 |
| test_09_product_lifecycle.py | 199 | 6 |
| test_10_verification.py | 290 | 8 |
| test_11_emergency_actions.py | 184 | 5 |
| test_12_rbac_and_occ.py | 273 | 8 |

**Total: 81 tests** (38 queue-A + 43 queue-B).

## Audit results
- **AST parse**: all 13 files parse cleanly.
- **Tag audit (real AST walk + pyyaml source parse)**: 81 tests, each with exactly one `Design:` tag; zero unknown tags, zero tags pointing at `excluded_because:` stubs, zero tagless/dual-tagged tests. All 19 difficulty instances have ≥2 tests; all 43 live corner instances have ≥1 test. The 11 corner stubs were correctly not translated (their `difficulty_instance` cross-references all resolve to emitted queue-A tags).
- **PRD citation sweep**: 136 quoted spans of ≥8 words, all survive whitespace-normalized literal grep of PRD.md (7 elided/abbreviated quotes were caught and fixed to full-sentence verbatim form per C3).
- **Collection**: `pytest test_suite --collect-only -q` → 81 collected, 0 errors.

## Adjudications (no instances skipped, two recipe-level corrections)
1. **`product_created_in_initial_state_draft`** — the recipe asserted `window_end` is null at creation, but PRD §3.4's formula ("the earliest non-null value among `cancelled_at`, `superseded_at`, and `expires_at`") makes `window_end == expires_at` for a fresh draft. The test was emitted with all PRD-consistent assertions; only the PRD-contradicted `window_end`-null claim was omitted (asserting it would fail a PRD-faithful implementation).
2. **Both emergency-action difficulty recipes** (`emergency_order_requires_linked_product_issued`, `evacuation_reentry_buffer_gap_45_rejected_gap_60_allowed`) — the recipe's `expires_at: 2026-09-01T12:00:00Z` with an 08:30 issue instant is 210 minutes, outside the SEVERE_THUNDERSTORM 15..120 duration gate (PRD §3.5), so the setup's issue step could never succeed. Re-derived the literal to 10:30 (exactly 120 min, the inclusive ceiling); all asserted outcomes unchanged.
3. Timestamp assertions use ISO-8601 parse-compare (or server-field-to-server-field equality) rather than raw string equality with `Z`-suffixed literals, since PRD §2.4 renders system timestamps with three fractional digits.

Orchestrator verification: independent `pytest --collect-only` collects exactly 81 tests with 0 errors; grep counts 81 `Design:` tag lines with 62 unique tags (19 §1.8 + 43 §1.9 — matches both indices).

## Step 6: Generate implementation — 2026-10-02T10:50:00.000Z

Implementation complete. Final report:

## Files written (all in `/home/ubuntu/github/CodingPRD/tasks/task_3457_watch_warning_issuance_polygon_definition_dissemination/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, `exec python3 app.py`, guarded pip install, `PORT` default 10000, `0.0.0.0` |
| `requirements.txt` | 1 | flask>=3.0 |
| `constants.py` | 91 | Every named constant, defined once (thresholds, enums, duration ranges, pagination, clock start) |
| `errors.py` | 53 | `ApiError` + full §5 catalogue (37 error_ids → HTTP status) |
| `db.py` | 41 | In-memory dict store (empty at boot, no seeding) + logical clock starting exactly `2026-09-01T00:00:00Z` |
| `util.py` | 168 | Envelope, pagination (`limit`/`offset`/`total_count`/`has_more`), ISO parse/format (3 fractional digits), round-half-up via Decimal, `touch()` (updated_at + version++) |
| `geometry.py` | 186 | Shoelace area, convex/self-intersection/degenerate checks, Sutherland–Hodgman clip in km space, boundary-inclusive point-in-polygon |
| `calculations.py` | 411 | All §1.3 rules: overlap resolution (round2 area → divide → round3 pct, pinned order), impact tiers, issuance criteria, coordination requirement, WEA rendering/truncation, verification matching (both variants), statistics aggregation (floor-then-mean lead), performance band, window-overlap, evacuation buffer |
| `auth.py` | 54 | Pipeline tiers 1–3 (auth headers, role lists, MIC override, office scope) |
| `serialize.py` | 35 | Drops internal `_` fields, renders datetimes, injects computed `window_end` on products |
| `routes_config.py` | 289 | Offices (+5 sub-collections), zones, agreements (duplicate-pair 409), channels (WEA ≤360), forecasters |
| `routes_storms.py` | 149 | Storm create/GET/PUT (OCC + DETECTED→TRACKING)/dissipate |
| `routes_products.py` | 535 | Draft create (per-level geometry rules, frozen computed block), submit-coordination, issue (full 11-tier pipeline, OCC, supersede cascade, dissemination record creation, WEA overflow), cancel, wea-preview |
| `routes_coordination.py` | 85 | Get/list/respond; DECLINED reverts product to DRAFT and cancels sibling REQUESTED |
| `routes_dissemination.py` | 40 | Record get/list |
| `routes_verification.py` | 168 | Event report/adjudicate (POLYGON_STRICT matching bumps `verified_event_count`), statistic compute + office band cascade |
| `routes_emergency.py` | 143 | Recommend/order (3 gates in tier order)/lift (ORDERED→LIFTED, RECOMMENDED→WITHDRAWN) |
| `routes_platform.py` | 127 | **Unprefixed** `POST /_clock/set_current_utc` (ordered sweeps: product expiry → coordination expiry+revert → record dispatch) and `POST /_dissemination/settle` (retry→QUEUED, DEAD at 3) |
| `app.py` | 65 | App assembly, ApiError/404/405/500 envelope handlers |

All 37 business endpoints under `/alerts` + 2 unprefixed platform endpoints registered (verified via route dump).

## Smoke-test transcripts (dynamic ports, servers killed by saved `$!` PID)

**Smoke 1 (happy path)**: office 201 → zone 201 → MIC forecaster 201 → EAS channel 201 → storm 201 (DETECTED) → WARNING draft 201 (polygon 0.7°×0.7° PLANAR → `polygon_area_sq_km` 6037.29 = 77.7×77.7 ✓, zone resolved, `damage_threat` NONE at wind 60) → issue 200 (OCC v1, `effective_from` overwritten with `issued_at`, version→2) → list filtered 200 → record QUEUED with rendered message → clock +5min → record auto-CONFIRMED (`requires_confirmation=false`) → negatives: missing headers → 401 `ERR_UNAUTHENTICATED`; re-issue → 409 `ERR_INVALID_PRODUCT_STATE`.

**Smoke 2 (coordination/OCC/verification)**: submit with non-covering agreement → 422 `ERR_ZONE_OUTSIDE_CWA`; reversed duplicate pair → 409 `ERR_DUPLICATE_AGREEMENT`; issue-from-DRAFT unsatisfiable → 422 `ERR_ZONE_OUTSIDE_CWA` (never `ERR_COORDINATION_NOT_ACKED`); satisfiable-but-unsubmitted → 409 `ERR_COORDINATION_NOT_ACKED`; submit → PENDING v2; wrong-office respond → 403 `ERR_OFFICE_SCOPE_VIOLATION`; DECLINED → product reverts DRAFT v3; resubmit→ACK→issue 200 (revert loop works); stale storm PUT → 412; valid PUT flips DETECTED→TRACKING v2; TORNADO warning issued, event inside polygon CONFIRMED → `matched_product_ids=[warning]`, product `verified_event_count=1`, `verification_status=VERIFIED`; statistic POLYGON_STRICT → `(total_warnings=1, events_total=1, events_warned=1, false_alarms=0, pod=1.0, far=0.0, avg_lead_time_minutes=30.0)`; office cascade → `SATISFACTORY`, `last_statistic_at` set, version 2.

## Audits

- **Constants**: all 26 scaffold-derived constants defined exactly once in `constants.py`, each referenced (script output: `defined=1 referenced_in_files>=1` for every one). No referenced-but-undefined names.
- **Errors**: every `api_error("ERR_*")` literal resolves to a catalogue key in `errors.py` (zero undefined).
- **Checks called**: every validation/calculation function in `calculations.py`/`geometry.py`/`auth.py`/`util.py` has a live callsite (one initially-dead helper, `div_round_half_up`, was removed).
- All files compile; every file tail re-read intact; no seeding; no stray server processes.

## Interpretation decisions (PRD admitted more than one reading)

1. **All timestamps from the logical clock** — including `meta.api_request_timestamp` and `created_at`/`updated_at` ("every system timestamp … is taken from this clock"); rendered with `.000Z` 3-fractional-digit format. Input datetimes truncated to whole seconds ("comparisons resolve to the second").
2. **`version` starts at 1** at creation; +1 on every mutation including cascades.
3. **MIC override requires both** role `MeteorologistInCharge` AND `Forecaster.level == "MIC"` ("only role permitted" + "requires the caller's row to carry level MIC"), else `ERR_MIC_REQUIRED`.
4. **`expected_product_version`/`expected_storm_event_version` are required** (endpoint tables list them un-`?`ed, PRD says "requires the request to carry"); missing/non-integer → 400 (tier 4), not a skipped check.
5. **Office-scope check on path-loaded entities runs right after the 404 load** (scope needs the entity); body-office scope (storm/product create) runs on the raw body value at tier 3, before FK existence.
6. **Duration gate is issue-time-only** for WARNING/ADVISORY (PRD: "issuance fails"); at creation only `expires_at > effective_from` (+ `ERR_EFFECTIVE_IN_PAST` for OUTLOOK/WATCH). `effective_from` defaults to now when omitted.
7. **Zone-based ADVISORY may carry `storm_event_id`** (scaffold says "required for WARNING and polygon ADVISORY; null for OUTLOOK and zone-based WATCH" — advisory zone-based left optional). Without a storm its criteria read zero/false, so it can never meet advisory floors (literal reading).
8. **OUTLOOK/WATCH with a supplied `storm_event_id`**: ignored, stored null (only polygon-on-OUTLOOK/WATCH is a catalogued forbidden combination).
9. **`supersedes_reason` without `supersedes_product_id`** (and vice versa) → 400 ("both are null for a fresh issuance" read symmetrically). Chain shape checked only at issue (PRD §3.4: "checked at issuance time").
10. **Unsatisfiable hurricane-pulled required office** (agreement exists but doesn't cover the hazard) maps by product geometry: zone-based → `ERR_ZONE_OUTSIDE_CWA`, polygon-based → `ERR_POLYGON_OUTSIDE_CWA` (PRD defines only zone/polygon kinds).
11. **Coordination "rounds" tracked** (`_coord_round` on product + request): issue/expiry-revert consider only the current submit round's requests, so old-round ACKED/CANCELLED requests after a decline-revert + resubmit can't wedge the product.
12. **Non-WEA dissemination records** store the same rendered message format with no truncation (budget effectively unlimited), `included_zone_ids` = all resolved zones in zone_code order; zone-based products render with overlap_pct treated as 0 for truncation ties (lexicographically greatest zone_code dropped first).
13. **WEA preview** accepts any channel type, budget `min(360, max_message_chars)`; polygon-less product → 400; overflow reported as `would_overflow: true` rather than an error.
14. **Pagination clamps** out-of-range `limit` into [1,100] and `offset` to ≥0 rather than rejecting (PRD states bounds, no error defined).
15. **Clock set accepts any parseable instant**; sweeps are threshold-conditional so a non-forward value triggers nothing (PRD describes forward motion; no error defined for backward).
16. **Zone-based `resolved_zone_ids` preserves input order** ("simply a copy"); polygon products sort by `zone_code` ascending.
17. Dispatch auto-confirm (QUEUED→SENT→CONFIRMED in one advance) increments the record version once per transition step touched (SENT then CONFIRMED = 2 bumps); record versions aren't OCC-guarded anywhere.

Orchestrator verification: 18 files / 2652 lines on disk; `python3 -m py_compile` passes on all; grep confirms `/_clock/set_current_utc` and `/_dissemination/settle` registered unprefixed in routes_platform.py.

## Step 7: Test-fix iteration loop — 2026-10-02T11:20:00.000Z

Summary — clean 8-round parallel sweep achieved.

**Iterations run:** 2 (baseline sweep: 4 unique failures stable across all 8 rounds; post-fix sweep: all green).

**Tests deleted (1):**
- `test_resolved_zone_ids_sorted_by_zone_code_not_input_order` (`test_suite/test_02_product_geometry.py`, Design: Corner/calculations/resolved_zone_ids_sorted_by_zone_code_not_input_order) — STEP 1b unique-derivability collapse. PRD §3.4 states "For a zone-based product, `resolved_zone_ids` is simply a copy of `zone_ids`" and places "The resolved list is sorted by `zone_code` ascending" inside the polygon-product passage; the scaffold likewise scopes sorting to the polygon-triggered `zone_overlap_resolution` calc and describes the zone-based value as "a copy of zone_ids". A faithful PRD-only reader (as the implementation chose) preserves input order for zone-based products, so the test fails on a PRD-consistent implementation. Unused imports (`create_zone`, `create_watch_draft`, `setup_office_with_forecaster`) removed with it.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/` (2):**
- `test_07_supersede_chains.py` — `TestContinuationOfCancelledTarget._setup` (shared by `test_continuation_of_cancelled_target_reports_state_error` and `test_state_error_precedes_temporal_window_error`): added `effective_from="2026-09-01T08:00:00Z"` to the W2 draft. With `effective_from` omitted, creation depended on the PRD-undetermined default-onset behavior for warnings (impl defaults to the 10:00 clock, making `expires_at` 09:00 reject at creation). With the onset supplied, `expires_at`(09:00) > `effective_from`(08:00) passes creation under every PRD reading (the `ERR_EFFECTIVE_IN_PAST` gate is verbatim scoped to OUTLOOK/WATCH), while at issue the clock (10:00) still makes the window violation present — so tier-7 `ERR_INVALID_PRODUCT_STATE` correctly beats tier-9 `ERR_WINDOW_INVALID`, exactly the recipe's intent.
- `test_10_verification.py` — `test_performance_band_pod_exactly_050_stays_satisfactory`: added the missing `hazard_type="FLASH_FLOOD"` to the W2 `create_warning_draft` call. The design recipe's W2 payload carries `hazard_type: FLASH_FLOOD`; the test omitted it, so the factory default (SEVERE_THUNDERSTORM) was checked against a rain-only FLASH_FLOOD storm and correctly failed issuance criteria. This also matches the test's own assertions (`total_warnings == 2` for the FLASH_FLOOD statistic).

**Fixes applied to `implementation/`:** none — all failures traced to test-side artifacts; no PRD-required check was weakened or removed.

**Final sweep evidence:** rounds 1–8 each report passed=80/80, failed=0, errors=0; all 8 `results.*.json` files remain on disk under `workspace/implementation/` (verified above; none deleted post-sweep).

Orchestrator verification: 8 results files each read back passed=80/total=80; no `.py` source in implementation/, test_suite/, or test_helpers/ is newer than the sweep outputs (mtime ordering clean, __pycache__ excluded); the three touched test files (test_02 deletion, test_07 + test_10 fixes) match the report exactly. Suite is now 80 tests (81 − 1 deletion).

## Step 8: Finalize PRD — 2026-10-02T11:35:00.000Z

Done. PRD_FINALIZED.md written with two surgical pins, both in §3.4, traced to the Step 7 diff.

**Line counts:** PRD.md 295 lines, PRD_FINALIZED.md 295 lines — 0% line-count delta (two in-place sentence revisions on lines 143 and 145; no lines added or removed). Not a zero-edit outcome: two edits earned by the analysis below.

**Changes (one bullet each):**
- §3.4 — revise — inserted "When a draft request omits `effective_from`, it defaults to the logical clock's current reading at creation, whatever the product level." into the window-fields paragraph — `implementation/routes_products.py:160` (`effective = effective_from if effective_from is not None else now()`; `now()` is the logical clock, `db.py:28-32`).
- §3.4 — revise — extended the zone-resolution sentence to "…is simply a copy of `zone_ids`, preserving the supplied order" and re-scoped the closing sentence to "For a polygon product, the resolved list is sorted by `zone_code` ascending." — `implementation/routes_products.py:169` (zone-based: `list(zone_ids)`, input order) and `implementation/calculations.py:68` (polygon: `resolved.sort(key=lambda zid: STORE["zones"][zid]["zone_code"])`).

**Per-diff-item evidence log:**
1. Deleted `test_resolved_zone_ids_sorted_by_zone_code_not_input_order` → **edit made**. (a) PRD quote: §3.4 "For a zone-based product, `resolved_zone_ids` is simply a copy of `zone_ids`." … "The resolved list is sorted by `zone_code` ascending." — the sort sentence's scope (polygon-only vs global) is genuinely undetermined; the two sentences give conflicting readings for multi-zone zone-based products. (b) Impl: zone-based preserves input order (`routes_products.py:169`), polygon sorts (`calculations.py:68`), and serialization passes the stored order through unchanged (`serialize.py:23-35`), so the ordering is observable in product GET responses. (c) Verdict: ambiguity pinned to the impl's reading.
2. `test_07_supersede_chains.py` `_setup` (`effective_from="2026-09-01T08:00:00Z"` added) → **edit made**. (a) PRD silence: §3.4 line 139 lists the required draft fields (`product_level`, `hazard_type`, `issuing_office_id`, `expires_at`) so `effective_from` is optional, and line 143 says only that it "may name a future onset" — no default-on-omission is stated anywhere (grep of `effective_from` across the PRD confirms; other entities' defaults — `area_method`, `coastal`, `coordination_timeout_minutes`, `requires_confirmation`, storm readings — are all explicitly stated, products' `effective_from` is the lone omission). The default is behaviorally load-bearing: it feeds the creation-time `ERR_WINDOW_INVALID` check (`routes_products.py:161-162`), which is exactly why the unfixed test's `expires_at=09:00` with clock at 10:00 was rejected at creation. (b) Impl: `routes_products.py:160` defaults to the logical clock for every level; stored on the draft (`:186`); overwritten at issue for WARNING/ADVISORY (`:369-370, 433`). (c) Verdict: silence pinned.
3. `test_10_verification.py` (missing `hazard_type="FLASH_FLOOD"` added to W2) → **no edit, pure test artifact**. (a) PRD quote: §3.5 "A `WARNING` is issuable exactly when any warning threshold for its hazard is met: … for `FLASH_FLOOD`, rainfall rate of at least 2.0 inches per hour" — per-hazard criteria are verbatim-determined. (b) Impl: `calculations.py:116-147` (`criteria_met`) implements exactly those per-hazard thresholds; the pre-fix test inherited the factory default `hazard_type="SEVERE_THUNDERSTORM"` (`test_helpers/factories.py:199`) against a rain-only storm (wind 0 < 58, hail 0 < 1.00), so `ERR_ISSUANCE_CRITERIA_NOT_MET` was the PRD-correct rejection. (c) Verdict: recipe mistranslation in the test, no PRD silence or mismatch.

**Per-edit pre-edit search log (NO-NEW-MISMATCH):**
- Edit 1 (ordering). Subject: ordering of the stored `resolved_zone_ids` list. Enumerated every impl path touching it: creation (`routes_products.py:166-169` — the only writer; frozen at creation), `compute_impact` (`calculations.py:87-101`, set-of-tiers, order-irrelevant), `render_wea` (`calculations.py:222-225` — re-sorts by `zone_code` itself for the message, so §3.6's "zone_code values sorted ascending" stays true independent of stored order; `included_zone_ids` "in rendered order" likewise unaffected), `find_overlap_conflict` (`calculations.py:275`, set intersection), COUNTY_FALLBACK matching (`calculations.py:302`, membership), emergency-action gate (`routes_emergency.py:115`, membership), serialization (`serialize.py`, passthrough). Wording adjustment: rather than declaring a universal sort rule, the sort sentence was re-scoped with "For a polygon product," and the copy sentence gained "preserving the supplied order" — both paths described exactly, none mis-described.
- Edit 2 (effective_from default). Subject: default value of product `effective_from` when omitted at draft creation. Enumerated impl paths: creation parse (`routes_products.py:92-96`), default (`:160`, level-agnostic), creation window check (`:161-162`), creation `ERR_EFFECTIVE_IN_PAST` scoped to OUTLOOK/WATCH (`:163-164` — with default == clock, "equal" is not "earlier", so no spurious rejection), storage (`:186`), issue-path overwrite for WARNING/ADVISORY vs stored value for OUTLOOK/WATCH (`:368-385, 432-433`), and `find_overlap_conflict` (`calculations.py:273`, reads `effective_from` of already-issued products — unaffected). Emergency actions carry their own `effective_from` (§3.9; `routes_emergency.py`), a different entity — wording was scoped with "a draft request" and "product level" so it cannot bleed onto §3.9. Wording adjustment: added the explicit qualifier "whatever the product level" because the impl default at `:160` is level-agnostic and an unqualified sentence adjacent to the outlook/watch passage could be misread as scoped to those levels only.

Orchestrator verification: `diff` shows exactly the two claimed revisions at lines 143 and 145 and nothing else; both files 295 lines.

## Step 9: Complete PRD scan — 2026-10-02T11:55:00.000Z

All edits verified. The diff shows 26 hunks covering all 29 edits (three same-line merges). Final state: 295 lines in both files, 51,346 → 56,311 chars (+4,965).

## Summary

**Source vs output:** `PRD_FINALIZED.md` 295 lines / 51,346 chars → `PRD_COMPLETED.md` 295 lines / 56,311 chars (+4,965 chars, +0 lines; all in-paragraph edits, no new sections).

**Counts:** 26 ambiguity-pins, 3 mismatch-revisions (29 edited sentences total).

**Changes (one per bullet):**

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned to the logical clock, not wall clock — implementation/util.py:65
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (never rejected), non-integer values fall back to defaults, meta echoes clamped values, same-instant ordering by creation sequence, `has_more` ≡ offset+returned < total_count — util.py:82-110
- §2.4 — insert — ambiguity — `version` starts at 1, +1 per mutation including cascades — util.py:116-130
- §2.4 — insert — ambiguity — clock set accepts any parseable instant (no forward-ordering check); missing/unparseable `to_iso8601` → ERR_INVALID_REQUEST — routes_platform.py:90-93
- §2.5 — insert — ambiguity — all supplied datetimes truncated to whole seconds at ingestion — util.py:35-50
- §2.6 — insert — ambiguity — omitted or non-integer `expected_product_version`/`expected_storm_event_version` → ERR_INVALID_REQUEST (400) — routes_storms.py:97-101, routes_products.py:311-315
- §2.8 — insert — ambiguity — office-scope interleave: body-office scope applies to the raw value at tier 3; path-entity scope applies immediately after the tier-5 load (missing id → 404, existing foreign-office resource → ERR_OFFICE_SCOPE_VIOLATION) — auth.py:48-54, routes_storms.py:36-37/122-124
- §3.2 — revise — mismatch — channel `status` may be supplied at creation (default ACTIVE); strict "begins ACTIVE" reading is self-defeating since no endpoint mutates channel status, making SUSPENDED unreachable — routes_config.py:248-250
- §3.3 — insert — ambiguity — reading value types pinned (wind/motion/speed integers; hail/rainfall numbers; rotation/debris booleans) — routes_storms.py:16-18
- §3.3 — insert — ambiguity — an update carrying no reading fields still succeeds, bumps version, flips DETECTED→TRACKING — routes_storms.py:131-133
- §3.4 — insert — ambiguity — WARNING takes no zone_ids (non-empty list + polygon → 400); empty zone_ids treated as absent; zone-based ADVISORY may link a storm_event_id; OUTLOOK/WATCH silently discard supplied storm_event_id — routes_products.py:101-133
- §3.4 — insert — ambiguity — supersedes_product_id and supersede_reason must be supplied together; either alone → ERR_INVALID_REQUEST — routes_products.py:135-141
- §3.4 — insert — ambiguity — explicit `effective_from: null` treated as omitted — routes_products.py:93-96
- §3.4 — insert — ambiguity — duration gate is issue-time-only; drafts carry any window length — routes_products.py (no duration check in create_product)
- §3.4 — insert — ambiguity — supplied `zone_ids` stored on the draft, null on polygon products — routes_products.py:180
- §3.4 — insert — ambiguity — GEODETIC "centroid latitude" = arithmetic mean of vertex latitudes — geometry.py:16-18
- §3.5 — insert — ambiguity — "non-zero overlap" for coordination means the rounded 3-decimal overlap percentage is > 0 — calculations.py:64-65
- §3.5 — insert — ambiguity — required-office set frozen at creation; satisfiability evaluated live against current agreements — routes_products.py:171-173, calculations.py:195-208
- §3.5 — insert — ambiguity — each submission begins a coordination round; issuance and clock reversion consider only the current round — routes_products.py:246/264/338, routes_platform.py:48-51
- §3.5 — insert — ambiguity — unsatisfiable HURRICANE-pulled office reports by product geometry kind (polygon → ERR_POLYGON_OUTSIDE_CWA, zone-based → ERR_ZONE_OUTSIDE_CWA) — routes_products.py:285-294
- §3.5 — revise — mismatch — reversion condition re-evaluated for every still-pending product on every clock advance, not only when a new request expires — routes_platform.py:45-63 (literal reading wedges a product whose round ends EXPIRED+ACKNOWLEDGED with no new expiry event)
- §3.5 — revise — mismatch — issue from PENDING_COORDINATION requires no current-round request still REQUESTED (an expired-unanswered request does not block once siblings left REQUESTED), replacing "every linked request must be ACKNOWLEDGED"; also pins `coordination_override` must be boolean — routes_products.py:334-343, 306-308 (same wedge justification)
- §3.5 — insert — ambiguity — outlooks/watches re-validate window at issuance (expires_at > stored effective_from; effective_from behind the clock → ERR_EFFECTIVE_IN_PAST) — routes_products.py:378-385
- §3.6 — insert — ambiguity — non-WEA records render the full message against an effectively unbounded budget; every record persists rendered_message and included_zone_ids — routes_products.py:463-478
- §3.6 — insert — ambiguity — WEA preview accepts a channel of any type; missing channel_id → 400, unknown → ERR_CHANNEL_NOT_FOUND — routes_products.py:515-523
- §3.6 — insert — ambiguity — auto-confirm at dispatch is two mutations, so the record's version advances twice in one clock advance — routes_platform.py:72-79
- §3.6 — insert — ambiguity — FAILED→QUEUED retry retains the earlier sent_at — routes_platform.py:119-125
- §3.8 — insert — ambiguity — matched_product_ids listed in matched products' creation order — calculations.py:305-313
- §3.8 — insert — ambiguity — no ordering constraint on period_start/period_end; an inverted period scopes to nothing — routes_verification.py:140-143

All 16 known interpretations (a)–(p) adjudicated and pinned; suite state before patching was 80/80 green across all 8 sweeps.

## Impl bugs found

1. **§3.1** — "a `unique` two-to-four-letter identifier such as KAKQ" (office_code) — `implementation/routes_config.py:45-66` (`create_office`) performs no duplicate-office_code check; identical codes are accepted repeatedly. Suggested minimal fix: scan `STORE["offices"]` for an existing `office_code` and reject duplicates (PRD pins no error identifier; `ERR_INVALID_REQUEST` is the natural fit).
2. **§3.1** — "a `unique` public `zone_code` such as TXC001" — `implementation/routes_config.py:137-179` (`create_zone`) never enforces zone_code uniqueness. Same suggested fix pattern.
3. **§3.2** — "a `unique` `name` such as WEA-PRIMARY" — `implementation/routes_config.py:225-261` (`create_channel`) never enforces channel-name uniqueness. Same suggested fix pattern.
4. **§3.2** — "a `unique` `employee_code`" — `implementation/routes_config.py:267-289` (`create_forecaster`) never enforces employee_code uniqueness. Same suggested fix pattern.
5. **§3.6** — "The surviving zone ids are persisted on the record as `included_zone_ids` in rendered order, the final text as `rendered_message`, and removed zones are remembered in removal order" — `implementation/routes_products.py:457-480` (`issue_product` record creation) persists only `rendered_message` and `included_zone_ids`; the dropped-zone list is never stored on the record, so `GET /alerts/dissemination-records/{id}` cannot expose it. Suggested minimal fix: persist the dropped list (e.g. `dropped_zone_ids`, in removal order) on the record at creation.

Note on bugs 1-4: the PRD declares uniqueness but pins no error identifier for violations (only `ERR_DUPLICATE_AGREEMENT` exists in the catalogue, explicitly scoped to agreements), which is likely why impl-gen dropped the checks. PRD_COMPLETED.md leaves all five sites unrevised per the impl-bug protocol.

## Step 9b: Orchestrator impl-bug fixes + re-sweep — 2026-10-02T12:01:00.000Z

Orchestrator adjudicated all 5 Step 9 impl bugs as genuine (PRD declares the rule, impl omits it, no test covers it) and fixed them directly:

**Implementation fixes:**
- `routes_config.py` `create_office` — added `office_code` uniqueness scan → `ERR_INVALID_REQUEST` on duplicate (after field validation, before write; mirrors the `ERR_DUPLICATE_AGREEMENT` constraint-tier pattern).
- `routes_config.py` `create_zone` — added `zone_code` uniqueness scan → `ERR_INVALID_REQUEST` (after the office-FK existence check).
- `routes_config.py` `create_channel` — added `name` uniqueness scan → `ERR_INVALID_REQUEST` (after status validation).
- `routes_config.py` `create_forecaster` — added `employee_code` uniqueness scan → `ERR_INVALID_REQUEST` (after the office-FK existence check).
- `routes_products.py` `issue_product` — `render_plan` now carries the 3-tuple `(message, included, dropped)`; both WEA and non-WEA record creation persist `dropped_zone_ids` (removal order; `[]` for non-WEA under the unbounded budget) on the record. Serializer is a passthrough, so `GET /alerts/dissemination-records/{id}` now exposes it. Pre-checks: `assert_dissemination_record` in test_helpers is non-strict (no exact field-set assertion) and no test asserts record-field absence, so the new field cannot break the sweep; factories counter-generate unique codes, so the uniqueness checks cannot fire in any existing test.

**PRD_COMPLETED.md pins (5 inline inserts, mirroring the doc's existing "rejected as a malformed request (`ERR_INVALID_REQUEST`)" idiom):**
- §3.1 offices — duplicate `office_code` → `ERR_INVALID_REQUEST`.
- §3.1 zones — duplicate `zone_code` → `ERR_INVALID_REQUEST`.
- §3.2 channels — duplicate `name` → `ERR_INVALID_REQUEST`.
- §3.2 forecasters — duplicate `employee_code` → `ERR_INVALID_REQUEST`.
- §3.6 — "removed zones are remembered in removal order as the record's `dropped_zone_ids`."

**Re-sweep evidence (Step 9b, orchestrator-run):** `python3 -m py_compile` clean on both edited files; full 8-round parallel `prd-bench-local-run --isolation per-test-server` sweep after the fixes: rounds 1–8 each passed=80/80, failed=0, errors=0 → ALL-GREEN. All 8 `results.*.json` files regenerated on disk post-fix.
