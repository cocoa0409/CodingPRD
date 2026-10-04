## Step 1: Create task directory — 2026-10-02T02:27:00.000Z

Pre-allocated task directory `./tasks/task_3436_frozen_potato_processing_foodservice_specification_supply/` confirmed to exist with `workspace/` inside; used exactly this path (no new index computed, no other task_* directory created).

## Step 2: Generate scaffold — 2026-10-02T03:33:00.000Z

All three scaffold artifacts are complete and validated. Final summary:

## Files written

1. **`/home/ubuntu/github/CodingPRD/tasks/task_3436_frozen_potato_processing_foodservice_specification_supply/SCAFFOLD.yaml`** — §1.0–§1.7 only (no design keys)
2. **`/home/ubuntu/github/CodingPRD/tasks/task_3436_frozen_potato_processing_foodservice_specification_supply/SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — single top key `scaffold_difficulty_design`
3. **`/home/ubuntu/github/CodingPRD/tasks/task_3436_frozen_potato_processing_foodservice_specification_supply/SCAFFOLD_CORNER_DESIGN.yaml`** — single top key `scaffold_corner_design`

## Counts

- **SCAFFOLD.yaml**: 12 entities, **46 endpoints** (45 business under `/potato-ops` + unprefixed `POST /_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z`), 45 error codes, 13 calculations, 12 ordered validations, 9 state machines, 9 roles (peer-role model, `Grower`/`ChainCustomer` entity-backed), 1 OCC concurrency rule (`contract-amend-accept-stale`, 412).
- **§1.8 difficulty design**: **20 instances** — all nine rules with ≥2 instances (combinatorial_formula and cross_entity_state_dependency carry 3).
- **§1.9 corner design**: **40 instances** across all 9 taxonomy sections (38 full recipes + 2 `excluded_because` stubs citing §1.8 instances).
- **60 unique instance names** across both design files; 660 recipe calls total.

## Verification

`scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (0 violations; 46 endpoints / 12 entities / 20+38 instances scanned.)

## Key design decisions

- Archetypes: quota/allocation (100000-case weekly plant pool, shortage waterfall) × posture-driven gating (facility NORMAL/WATCH/QUARANTINED from sprout/disease readings); flat topology, cyclic state shape (contract amendment loop, spec revision loop with `ever_locked` branch, run rework loop).
- Depth-4 credit-hold cascade (chain→agreements→runs→lots) and depth-2 rejection→fill-rate→SLA-flag cascade; two conserved-quantity invariants (facility stock cwt, weekly case pool).
- Endpoint count rose from a planned 40 to **46**: `scaffold_lint.py` check (f) derives child collection segments only from single-resource GETs, so 7 read-back GETs were added after the first lint run flagged 13 FK_REVERSE_UNREACHABLE violations.
- All formula-derived asserts were pre-computed and float-checked; the credit-memo rounding fixture was rebased from 305→299 cents/case because 305 made `2×305×0.85 = 518.4999…` sit on the float boundary and collapse the intended per-line-vs-sum-first divergence (now 1270 vs 1271, boundary-safe).

## Step 3: Copy shared files — 2026-10-02T03:35:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-02T03:45:00.000Z

All checks pass. The `potato-ops` prefix appears only in §2.5 and §4 (allowed zones); §3 is path-pure, and the OCC prose uses no race framing. The PRD is complete and verified.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3436_frozen_potato_processing_foodservice_specification_supply/workspace/PRD.md` — 350 lines, built via sequential validated appends.

**Section headings:**
- `## 1. Introduction` (2 paragraphs)
- `## 2. Global Specifications & System-Wide Principles`
  - 2.1 User and Role-Based Access Control — all 9 roles with per-role `identity:` prose (Grower→entity-backed Grower, ChainCustomer→entity-backed CustomerChain, 7 opaque roles named individually)
  - 2.2 API Response Structure — fixed block, confirmed byte-identical to `section-2.2-response-structure.md`
  - 2.3 Pagination — `limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending, meta fields
  - 2.4 Common Resource Properties — UUID/timestamps/`version` semantics; `ByproductBatch` explicitly carries only `id`+`created_at`
  - 2.5 The Logical Clock and the Term-End Sweep — **`POST /_clock/set_current_utc` stated verbatim and explicitly NOT under `/potato-ops`**; initial reading exactly `2026-09-01T00:00:00Z`, no wall-clock fallback, term-end sweep side effect
  - 2.6 Money, Precision, and the Pinned Rounding Order — cents, round-half-up, per-lot/per-line pinned rounding with the 1297-vs-1296 worked example
  - 2.7 The Plant Weekly Case Pool — 100,000-case pool, inclusive zero boundary, atomic re-reservation
  - 2.8 Storage Posture as a Food-Safety Gate — `NORMAL`/`WATCH`/`QUARANTINED` gating
  - 2.9 Optimistic Concurrency Control — `expected_crop_contract_version` on amendment acceptance only, `ERR_STALE_VERSION` 412, stale-version framing only
  - 2.10 Validation Order and Error Precedence — all 12 scaffold priorities in explicit first-failure-wins order
- `## 3. Business Logic & Workflows` — 8 subsections (3.1 contracting/amendment/settlement, 3.2 lot intake/grading, 3.3 storage posture/disposal, 3.4 cut specs, 3.5 agreements/capacity/credit cascade, 3.6 production runs/QA gate, 3.7 shipments/fill-rate loop, 3.8 shortage allocation/import sourcing)
- `## 4. Endpoint Definitions` — 46-row table, 4 columns, status-code paragraph
- `## 5. Error Code Catalogue` — 45-row table, 2 columns

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].request_body (incl. query params): 73 required, 73 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose (§2.10), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (endpoint + expected_crop_contract_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 9 machines checked (CropContract 5, PotatoLot 4, StorageFacility 6, CutSpecification 6, CustomerChain 2, SupplyAgreement 5, ProductionRun 10, Shipment 2, ShortageEvent 1), all fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed in reconstruction-safe prose, 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (depth-4 credit cascade, settlement cascade, spec-stale cascade, fill-rate/SLA loop, clock sweep), 0 missing
- entities[].fields[] structured content: defaults, nulls, bounds, immutability, derived formulas all reconstructible, 0 missing
- sibling-branch symmetry: validate 3-branch, activate 2-branch, shortage 2-variant, posture 6-transition, provisional-vs-final — all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 572
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional verifications:** all 45 error IDs, all 35 state values, all 35 enum literals, and all 9 role names appear verbatim in backticks; no pseudocode operators (`==`, `>=`, `round_half_up(`, etc.) or fuzzy words leaked into prose; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task was consulted.

## Step 5: Generate unit tests — 2026-10-02T04:12:00.000Z

All checks pass. Final report:

## (a) test_helpers/ — 9 files
`/home/ubuntu/github/CodingPRD/tasks/task_3436_frozen_potato_processing_foodservice_specification_supply/test_helpers/`: `__init__.py` (barrel), `types.py` (12 entities; `ByproductBatch` correctly omits `updated_at`/`version` per common_fields:false), `api_client.py` (32 endpoint methods; clock endpoint unprefixed at `/_clock/set_current_utc`), `api_errors.py` (46 IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (7 opaque roles shared; per-instance builders for entity-backed Grower/ChainCustomer), `fixtures.py` (tiered composites: `setup_procurement`, `setup_full_pipeline`, `setup_released_run`, posture drivers, run lifecycle shortcuts).

## (b) test_suite/ — 13 files, 77 tests
`conftest.py` + `test_01_growers_and_contracts` (8), `test_02_delivery_window_overlap` (2), `test_03_contract_settlement` (5), `test_04_lot_intake` (6), `test_05_lot_grading_boundaries` (8), `test_06_storage_posture_disposal` (5), `test_07_specifications_agreements` (7), `test_08_credit_cascade_capacity` (6), `test_09_production_runs` (5), `test_10_production_run_gates` (8), `test_11_shipments_fill_rate` (9), `test_12_shortage_events` (4), `test_13_rbac_auth` (4).

## (c) Coverage audit (real AST walk of docstring `Design:` tags vs both YAMLs)
- **Difficulty: 20/20 instances, each with exactly ≥2 tests** (40 tests).
- **Corner: 37/38 non-stub instances covered.** Both `excluded_because` stubs verified to resolve to real difficulty instances and not translated. No unknown/dual/untagged tags.
- **Intentionally skipped (1):** `Corner/cross_cutting_layers/released_unshipped_cases_reconcile_across_release_shipment_rejection` — fails unique derivability: PRD §3.5 (`released_unshipped_cases` = released − shipped, with shipped counting only IN_TRANSIT/DELIVERED) yields 620 after an arrival rejection while §3.7 ("does not grow back") yields 120; the instance asserts both `lifetime_shipped_cases == 0` and `released_unshipped_cases == 120`, which are mutually inconsistent under either reading, and its recipe ships 100 cases while its asserts assume 500.
- **Accidentally missing: 0.**
- One adjudication: `run_create_requires_spec_locked_not_just_validated`'s dual-failure ordering (spec-lock beats agreement-state) is unpinned in PRD (both priority 6; §3.6's prose order is provably not evaluation order since it lists a priority-8 gate before a priority-6 one). Per the skill's remedy I split it into two single-failure tests (VALIDATED-spec-only failure → `ERR_SPEC_NOT_LOCKED`; DRAFT-agreement-only failure → `ERR_AGREEMENT_NOT_ACTIVE`), both tagged to the instance.

## (d) pytest --collect-only
`77 tests collected in 0.23s`, zero import errors, zero skip/xfail markers.

## (e) Constants vs PRD
All 41 constants in `constants.py` verified against distinctive PRD prose pins (grading tiers, 0.02/1.5/3.0/15.0/10.0 decay, 6.0/4.0/3.0/2.0 posture, 0.62/0.58/0.66/0.55 yields, 0.96 rework, 60-min changeover, 100,000 pool, 0.90/0.85/30/85.0 shipment rules, 98% fulfillment, 900/1400/0 tariffs, clock start) — **0 drift, 0 invented values**.

## (f) Clock reachability / fixtures
No design recipe required an unreachable clock state — every recipe starts at the PRD-mandated `2026-09-01T00:00:00Z` and moves forward only (PRD states no forward-only constraint anyway). One new fixture date was self-derived for the downgrade-boundary second test: `2028-01-14T00:00:00Z` = exactly 500 storage days at NORMAL posture (loss exactly 10.0%, not > 10.0, so no downgrade; 900.0 cwt × 2500 × 1.08 = 2430000). The 299-cent credit-memo fixture keeps the deliberately divergent 762+508=1270 vs sum-first 1271, and the PRD's own 305-cent worked example (778+519=1297 vs 1296) is the second test of that instance. All create calls assert 201 explicitly.

## Step 6: Generate implementation — 2026-10-02T04:42:00.000Z

Implementation complete and verified. Here is the full report.

## Files written (all under `.../workspace/implementation/`)

| File | Role |
|---|---|
| `start.sh` | Foreground launcher, `exec python3 app.py`, flask-import-guarded pip install, `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | `flask>=2.2,<4` (flask 3.1.3 already present on host) |
| `app.py` | App factory, blueprint registration, ApiError/404/405/500 envelope handlers |
| `constants.py` | All enums, thresholds, tariffs, yields as exact-Decimal-safe strings |
| `errors.py` | `ApiError(error_id, message, http_status)` |
| `util.py` | ids, ISO-8601 3-fractional-digit timestamps, datetime parsing, Decimal helpers, request-shape validators |
| `db.py` | In-memory store (11 dicts, empty at boot — no seeding), logical clock defaulting to exactly `2026-09-01T00:00:00Z` |
| `response.py` | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination (default 10, clamp 1–100, offset ≥ 0) |
| `middleware.py` | Priorities 1–2 auth: `X-User-ID`/`X-User-Role` presence + nine-role validity (400), per-endpoint role list (403) |
| `calcs.py` | Pure calc rules: grading, provisional/final payments, storage loss, posture, yields, invoice/credit per-line rounding, fill rate, byproduct revenue |
| `domain.py` | Cross-entity logic: derived fields, `touch()` version policy, settlement, auto-fulfill, credit cascade (depth 4), clock sweep, spec-revision stale cascade, fill-rate/SLA loop, shortage allocation, all serializers |
| `routes_clock.py` | `POST /_clock/set_current_utc` — **unprefixed**, verified |
| `routes_growers.py` / `routes_contracts.py` / `routes_lots.py` / `routes_facilities.py` / `routes_specs.py` / `routes_chains.py` / `routes_agreements.py` / `routes_runs.py` / `routes_shipments.py` / `routes_shortage.py` | Per-domain route modules (shortage module also hosts byproduct-batch reads; facilities module also hosts processing-line create) |

**Module split rationale:** foundation (constants/errors/util/db/response/middleware) → pure calculations (calcs) → cross-entity mutations and serializers (domain) → one route module per aggregate. All 46 endpoints registered (verified via `url_map` dump; clock endpoint unprefixed, prefixed variant 404s).

**py_compile:** every file compiled individually right after writing; final sweep of all 21 `.py` files → ALL COMPILE OK.

**Self-smoke-test (server booted via `bash start.sh` on dynamically allocated ports; exact `$!` PID killed each time; no leftover listeners verified via `/proc/*/cwd`):**
- `POST /_clock/set_current_utc` (PlatformAdmin) → **200**, `{"data":{}, "response_type":"object", ...}` 
- `POST /potato-ops/growers` → **201**, full entity, `version: 1`
- `GET /potato-ops/crop-contracts` → **200**, `response_type:"array"`, meta carries `limit/offset/total_count/has_more`
- `POST /potato-ops/growers` without headers → **400** `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` in the error envelope
- Plus ~110 deeper assertions across three rounds, all passing: grading matrix + boundaries, provisional math, auto-FULFILLED at ≥98% (rounded half-up 1dp), storage-decay settlement with WATCH downgrade (926794) and QUARANTINED 15% cap (875500), amendment OCC (412), overlap/adjacency, posture gates, rework loop (62→59), line schedule + 60-min changeover, shipment invoice/credit per-line rounding, excursion flag (>30 strict), fill-rate SLA set/block/clear, pro-rata and waterfall allocation, credit-hold cascade + atomic resume failure (422, nothing changes), clock sweep completion, import-lot role gate.

## Interpretation decisions (for the Step-7/8 auditor)

1. **Readings return 200, not 201.** PRD §4 explicitly lists "readings" among modify operations returning 200; this contradicts the scaffold endpoint table's `code: 201`. Per the PRD-wins rule I shipped 200.
2. **`pinned_spec_version` is captured AFTER the activation's spec-lock increment.** Otherwise the revision cascade (`pinned == pre-revision version`) could never fire for first-generation pins — my round-2 test caught this; fixed in `routes_agreements.py`.
3. **Fill-rate/SLA update is symmetric on both terminal shipment events** (per the `fill_rate_pct` calc rule): ≥85.0 clears `under_sla_review` on all of the chain's agreements; <85.0 sets it on every ACTIVE one.
4. **Waterfall allocation stops at `remaining == 0`** — unprocessed participants get no `allocation_results` entry and keep their current allocation ("allocation stops when the remaining pool reaches zero").
5. **Pro-rata `allocation_results` order** is unspecified by the PRD; I use agreement `created_at` ASC (insertion-seq tiebreak), deterministic.
6. **Accept-amendment ordering:** overlap check (priority 8) runs before the OCC check (priority 12), per PRD §2.10, overriding the state machine's listed precondition order.
7. **Version/timestamp policy:** version starts at 1 at creation; every mutation — including derived-field reconciliation (facility stock, delivered volume, lifetime/shipped counters, fill rate) and cascaded changes — is one `+1` per logical change per entity, per PRD §2.4. All timestamps (`created_at`, `updated_at`, meta `api_request_timestamp`) come from the logical clock so storage-decay math is deterministic.
8. **`ERR_BATCH_NOT_FOUND` (404)** is my chosen id for `GET /byproduct-batches/{id}` misses — the catalog defines no batch-specific not-found id. Generic route 404/405/500 fallbacks use `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL_ERROR` envelopes (off-catalog; only reachable on undeclared paths or true bugs).
9. **Entity-backed ownership is skipped when the target doesn't exist** (falls through to the 404 existence check), since the comparison needs the resource; import-mode with a `Grower` role → `ERR_OWNERSHIP_MISMATCH` regardless; ambiguous mode (both ids) → `ERR_LOT_SOURCE_MODE_INVALID` shape error.
10. **Bounds enforced from PRD prose** even where the scaffold lacks explicit checks: `sugar_end_rating` 1.0–5.0, `defect_pct` 0–100, `target_color_units` 0–4, `available_week_cases` 1–100000, `minutes_above_setpoint` ≥ 0, shipment line `cases` ≥ 1. Panel score < 0 with `sensory_panel_required: false` → `ERR_PANEL_SCORE_BELOW_STANDARD` ("any score >= 0 passes").
11. **Pagination clamps** out-of-range limit/offset (min 1 / max 100 / offset ≥ 0); non-numeric values → 400. Code uniqueness (`grower_code` etc.) is not enforced — the catalog defines no duplicate error.
12. **GrowerRelationsManager cannot create CONTRACTED lots** ("the caller must be the Grower whose X-User-ID equals the contract's grower_id" → 403); its lot role is import-only.

One real bug was found and fixed by the smoke tests (item 2); all other smoke failures during development were arithmetic/design errors in my own throwaway test scripts, not the implementation. No test-suite files, design YAMLs, or helper files were read at any point.

## Step 7: Test-fix iteration loop — 2026-10-02T05:41:00.000Z

Clean sweep confirmed: 8/8 rounds, 77/77 tests passing, all 8 `results.*.json` on disk.

**Summary**

- **Iterations run:** 2 (first sweep: 1 deterministic failure in all 8 rounds; fix applied; second sweep: 77/77 × 8 rounds, zero failures/flakes).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3436_frozen_potato_processing_foodservice_specification_supply/test_suite/test_02_delivery_window_overlap.py` — `test_delivery_window_adjacency_allowed_overlap_rejected`: replaced the exact-string echo assertion `c2["delivery_window_start"] == "2026-10-15T00:00:00Z"` with a representation-tolerant value check (`.startswith("2026-10-15T00:00:00")`). Why: PRD §2.4 pins the three-fractional-digit ISO-8601 format **only** for system-managed `created_at`/`updated_at` (and the envelope `api_request_timestamp`); PRD §3.1 says only that the contract "names its `delivery_window_start`" — the echo representation of a client-supplied window is unpinned, so two faithful PRD-only implementations (verbatim echo vs canonical `.000Z` normalization, which the implementation chose) diverge. STEP 1b unique-derivability collapse (representation silence, sibling of DEFAULT-VALUE SILENCE); per STEP 1c the covered assertions (201 = adjacency allowed; 409 `ERR_DELIVERY_WINDOW_OVERLAP` on true overlap; rejected contract not persisted) were kept and only the uncovered format assertion was relaxed. No implementation change was warranted — the impl's normalization is PRD-consistent.

- **Fixes applied to `implementation/`:** none.

- **Sibling unasserted paths** (test-side fix dominated; these could hide PRD-vs-impl divergence):
  - Echo representation of other client-supplied datetime fields — `delivery_window_end`, amendment `pending_amendment.delivery_window_start/end`, supply-agreement `term_end`, facility-reading `recorded_at` — same unpinned status, asserted nowhere.
  - The PRD-**pinned** three-fractional-digit format of `created_at`/`updated_at` values (§2.4) is asserted only for presence, never for the exact `.dddZ` shape — an impl emitting `Z`-without-fractional on system timestamps would pass the whole suite despite violating §2.4.

## Step 8: Finalize PRD — 2026-10-02T05:46:00.000Z

Task complete. The output file is written and verified.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3436_frozen_potato_processing_foodservice_specification_supply/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 350 lines, PRD_FINALIZED.md = 352 lines (+2 lines, +0.57%). Not byte-identical — exactly one substantive edit, matching the single substantive `<step_7_diff>` item.

### Change
- **§2.4 (Common Resource Properties)** — **insert** — one new paragraph after the immutability note, pinning that client-supplied datetime fields are echoed in responses normalized to the same canonical UTC three-fractional-digit representation as the system-managed `created_at`/`updated_at`, rather than echoed verbatim — impl: `util.py:23-26` (`fmt_ts`, canonical `.dddZ`), `util.py:29-44` (`parse_dt` normalizes to UTC), serializers at `domain.py:380-381, 394-395, 433, 514-515, 537-538`.

### Pre-edit search log (NO-NEW-MISMATCH rule)
- **(a) Subject:** echo representation of client-supplied datetime fields (the Step 7 site was `delivery_window_start` on contract creation).
- **(b) Impl paths enumerated and read/grepped:**
  - Parse/format: `util.py:29-44` (`parse_dt` — accepts `Z`/`z`, offsets, naive-as-UTC), `util.py:161-166` (`req_dt` → `ERR_INVALID_REQUEST` on unparseable), `util.py:23-26` (`fmt_ts`).
  - Write sites (all client datetime inputs): `routes_contracts.py:46-47` (create) and `:127,137-138` (propose-amendment via `_read_terms`); `routes_agreements.py:35-36` (`term_start`/`term_end`); `routes_facilities.py:50` (`recorded_at`); `routes_runs.py:80-81` (`scheduled_start`/`scheduled_end`); `routes_clock.py:22` (`current_utc` — input-only, response is empty data).
  - Echo sites: `domain.py:380-381` (pending amendment window), `394-395` (contract window), `433` (reading), `514-515` (agreement term), `537-538` (run schedule); envelope `response.py:20`.
  - Negative check: grep over `routes_shipments.py`, `routes_lots.py`, `routes_shortage.py`, `routes_growers.py`, `routes_specs.py`, `routes_chains.py` confirms no other client-supplied datetime inputs exist.
- **(c) Wording adjustments made:** (1) scoped the sentence to "echoed in responses" with an explicit field list, so the clock endpoint's `current_utc` — parsed the same way but never echoed on any resource — is not falsely claimed to be echoed; (2) used the loose phrase "accepted as ISO 8601 timestamps" rather than pinning accepted input forms, since `parse_dt` accepts offset/naive/lowercase-`z` forms that Step 7 did not evidence; (3) said "normalized ... rather than echoed verbatim" to pin exactly the behavioral choice (canonicalization) the relaxed test exposed, without claiming anything about fields the impl doesn't have.

The sibling-unasserted paths noted in the diff (`delivery_window_end`, pending-amendment windows, `term_end`, `recorded_at`) are all covered by the single inserted sentence, since the implementation routes every one of them through the same `parse_dt` → `fmt_ts` normalization.

## Step 9: PRD completeness scan — 2026-10-02T06:18:00.000Z

All edits verified in place. The work is complete. Final summary:

## Summary

**Source vs output:** `PRD_FINALIZED.md` (352 lines / 60,161 chars) → `PRD_COMPLETED.md` (355 lines / 65,492 chars), char-delta **+5,331**. 27 edit sites, all inline inserts/revisions; no new sections.

**Counts:** 26 ambiguity-pins, 2 mismatch-revisions (both are the single `ERR_BATCH_NOT_FOUND` omission, fixed in two places: the §2.10 rule-5 list and the §5 catalogue table, whose exhaustiveness claim conflicted with the impl returning it on the defined `GET /byproduct-batches/{id}` endpoint — domain.py:113-114).

**Change log** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl source}`):

- §2.3 — revise — ambiguity — limit/offset clamp (not reject), non-integer → ERR_INVALID_REQUEST 400, created_at ties break by creation order, `has_more` = offset+returned < total_count — response.py:55-89
- §2.4 — revise — ambiguity — one logical change = one version increment; conditional reconciliations that find the target value already correct skip the write — domain.py:287-289, 300-317, 351-353
- §2.4 — insert — ambiguity — human-facing codes (grower/facility/line/spec/chain) are unique by convention only; no server-side duplicate rejection — routes_growers.py:16-28 et al.
- §2.5 — revise — ambiguity — logical clock supplies all server timestamps (created_at/updated_at/api_request_timestamp); clock accepts any valid timestamp, no monotonicity check — db.py:41-46, response.py:20, routes_clock.py:29
- §2.10 r3 — revise — ambiguity — ownership comparisons evaluate only when the target resolves (else rule-5 404); the role-based half (non-Grower contracted intake, non-GRM import intake) fires regardless — routes_lots.py:39-59, routes_specs.py:126-134
- §2.10 r4 — revise — ambiguity — numeric-scale bounds (defect 0-100, sugar 1.0-5.0, color 0-4, available week cases 1-100,000) pinned as shape errors — routes_lots.py:85-91, routes_specs.py:38-44, routes_shortage.py:26-32
- §2.10 r5 — revise — **mismatch** — added `ERR_BATCH_NOT_FOUND` to the not-found list — domain.py:113-114
- §3.1 — revise — ambiguity — a threshold-crossing delivery increments contract version twice (volume reconciliation + fulfill/settle) — routes_lots.py:174-175, domain.py:216-225
- §3.3 — revise — ambiguity — `capacity_cwt` is an integer — routes_facilities.py:22
- §3.3 — revise — ambiguity — `recent_readings` retains the last ten *appended* (not by recorded_at); latest-reading selection runs over retained entries — routes_facilities.py:65-73
- §3.3 — revise — ambiguity — every recorded reading increments facility version, posture change or not — routes_facilities.py:75
- §3.4 — revise — ambiguity — `max_cook_time_sec` is an integer — routes_specs.py:45
- §3.4 — revise — ambiguity — negative panel_score with sensory_panel_required=false → ERR_PANEL_SCORE_BELOW_STANDARD 422 — routes_specs.py:107-112
- §3.5 — revise — ambiguity — integer `weekly_contracted_cases`; DRAFT carries `current_week_allocation_cases` = 0 — routes_agreements.py:25, 57
- §3.5 — revise — ambiguity — `pinned_spec_version` captures the post-lock-increment version of the LOCKED spec — routes_agreements.py:121-128
- §3.5 — revise — ambiguity — re-acknowledgment branch re-checks only spec LOCKED; credit/pool gates not re-run — routes_agreements.py:130-140
- §3.6 — revise — ambiguity — integer `rated_throughput_cases_per_hour` — routes_facilities.py:98
- §3.6 — insert — ambiguity — creation-gate evaluation order: spec LOCKED → agreement ACTIVE → lots IN_STORAGE → quarantine → cut-family → stale pin → schedule — routes_runs.py:93-132
- §3.6 — revise — ambiguity — `total_input_cwt` sums listed ids with multiplicity (duplicate id counts twice) — routes_runs.py:134-136
- §3.7 — revise — ambiguity — line `cases` integer ≥ 1; per-line RELEASED/ownership checks run after run resolution and before the agreement-ACTIVE check; `excursion_flag` false until delivery — routes_shipments.py:47-60, 93
- §3.7 — revise — ambiguity — `minutes_above_setpoint` integer ≥ 0 — routes_shipments.py:128-130
- §3.7 — revise — ambiguity — 85.0 floor applied symmetrically after either terminal event (deliver below floor flags ACTIVE agreements; reject at/above floor clears flags) — domain.py:294-317
- §3.8 — revise — ambiguity — integer `available_week_cases` — routes_shortage.py:26
- §3.8 — revise — ambiguity — PRO_RATA processes participants by created_at asc (creation-order tiebreak) and records an entry for every participant, zero-share included — domain.py:330-335
- §3.8 — revise — ambiguity — PRIORITY_WATERFALL created_at ties break by creation order; unreached participants get no entry and keep prior allocation — domain.py:336-348
- §3.8 — revise — ambiguity — allocation overwrite with an unchanged value performs no write and no version increment — domain.py:349-353
- §5 — revise — ambiguity — exhaustiveness scoped to business operations; undefined paths → ERR_NOT_FOUND 404, unsupported methods → ERR_METHOD_NOT_ALLOWED 405, both in the standard envelope — app.py:53-63
- §5 table — insert — **mismatch** — `ERR_BATCH_NOT_FOUND` | 404 row added — domain.py:113-114

**Already uniquely pinned by PRD_FINALIZED (verified, no change needed):** readings return 200; amendment-accept order (state → overlap → OCC per §2.10 6/8/12); version increments on cascades/derived reconciliation (§2.4); all the prose-derived numeric bounds (sugar 1.0-5.0, defect 0-100, color 0-4, available_week_cases 1-100,000); waterfall stops at remaining==0; GRM-only import lots; 98% threshold rounding; posture thresholds inclusive; per-lot/per-line rounding orders.

**Impl-side defects found, deliberately NOT papered over:** none that violate a concrete, well-formed PRD rule. Two borderline observations, both pinned as defensible readings rather than flagged as defects: (1) the PRD's "unique" code declarations carry no rejection semantics or error identifier anywhere in the document, so non-enforcement is a defensible reading — pinned as a data-entry convention in §2.4; (2) `qa_release` touches the agreement unconditionally, so in the unreachable-in-practice corner of `actual_cases == 0` the agreement version increments without an observable field change — the §2.4 no-op phrasing was deliberately scoped to *conditional reconciliations* to stay truthful to this. The 500 fallback (`ERR_INTERNAL_ERROR`, app.py:65-69) was left unpinned: the §2.2 error envelope is explicitly scoped to 4xx responses, and a 500 fires only on server bugs, not contract behavior.
