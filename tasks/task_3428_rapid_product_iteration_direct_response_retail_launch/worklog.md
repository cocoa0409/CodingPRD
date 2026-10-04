# Worklog — task_3428_rapid_product_iteration_direct_response_retail_launch

## Step 1: Create Task Directory — 2026-10-01T23:53:00.000Z

Task directory pre-allocated by the caller at `./tasks/task_3428_rapid_product_iteration_direct_response_retail_launch/` with `workspace/` inside; verified existence, no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-02T01:31:00.000Z

Scaffold generation complete for `task_3428_rapid_product_iteration_direct_response_retail_launch`. All three artifacts are written, parse clean, and pass `scaffold_lint.py` with a clean verdict (1145 test-recipe calls scanned, 0 violations; all 12 FKs reverse-reachable).

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_3428_rapid_product_iteration_direct_response_retail_launch/SCAFFOLD.yaml` (§1.0–§1.7, 1512 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3428_rapid_product_iteration_direct_response_retail_launch/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design` key, 1246 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3428_rapid_product_iteration_direct_response_retail_launch/SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design` key, 2161 lines)

**Counts**: 12 entities; 13 state-machine entries (ModelVariant carries two parallel dimensions: `lifecycle` × `claim_clearance`); 8 calculations + 2 pinned conservation invariants; 49 endpoints; 41 errors; 7 roles (all `opaque`, segregation-of-duties role model); 10 validation priority rows; 2 OCC concurrency rules. §1.8: 18 instances (9 rules × 2). §1.9: 56 live instances + 9 `excluded_because` stubs across all 9 taxonomy sections.

**Design shape** (beyond-expert levers, per the difficulty instruction)
- Archetype blend: `compliance_audit` × `posture_driven_gating`; layers: optimistic concurrency, cascading side effects, dual-variant calculation, ops-run checkpoint. Flat topology, cyclic state machines.
- Dual-variant calcs on two different domains: media MER (provisional 1.5 vs settled 8.504/4.252 with pinned per-line commission rounding) and litigation reserve (provisional 0.30-prior vs actual settlement/award).
- Two depth-3 cascades from different triggers: adverse judgment → case final amount → category exposure (×3 adverse multiplier) → season GUARDED → media air blocked; run-review retirement → variant RETIRED → OPEN commitments CANCELLED → partner capacity released.
- Priority-conflict pairs on different error categories: state-vs-fiscal (frozen season beats capacity) and safety-vs-temporal (SEVERE litigation beats window overlap at sign). This required scoping GUARDED to throttle only media air, so the p7-vs-p8 race at sign is observable.
- Boundary pins verified by executing the formulas: margin 0.1500 inclusive (115/100 passes, 114/100 fails), replenishment raw_need == 0 rejected, MER per-line rounding (8504→4.252 vs whole-sum 8503→4.2515), momentum decay (50.0 pass / 15.66 fail), exposure band edge 20 = SEVERE.
- OCC on the two create-with-supersede writes: `expected_variant_version` (replenishments) and `expected_agreement_version` (commitments).
- Logical clock with pinned default 2026-09-01T00:00:00Z; all cadence rules (120-day concept kill, 21-day round expiry, 28-day infomercial decision window, 240+30-day refresh-to-retire cadence) fire through `run-review`.

**Decisions worth flagging**
- 49 endpoints exceeds the expert band (deliberate, per the difficulty instruction) — Step 6 impl-gen will need its pre-constraining prompt (per-domain modules, one-file-per-message) given the known >40-endpoint overshoot risk.
- `ERR_ROUND_LIMIT_REACHED` was dropped during authoring: the prototype-budget cap is enforced by the synchronous revert-to-RESEARCHING transition, so a create-time limit error was unreachable dead code.
- Every `${var}` in both design files is capture-bound (verified), all formula-derived asserts are pre-computed literals, and the domain-noun grep confirms the files describe this scenario (prototype ×60, infomercial ×8, model_number ×25, patent ×88, replenishment ×92, litigation ×32, refresh ×27).

Orchestrator verification: all three files exist; `yaml.safe_load` parses each; SCAFFOLD.yaml top-level keys are [scenario, domain_name, api_prefix, complexity_profile, constants, response_envelope, entities, state_machines] (no design keys); each design file has exactly its single top-level key; 142 domain-noun hits in SCAFFOLD.yaml.

## Step 3: Copy Shared Files — 2026-10-02T01:33:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3428_rapid_product_iteration_direct_response_retail_launch/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T01:45:00.000Z

All checks pass. The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3428_rapid_product_iteration_direct_response_retail_launch/workspace/PRD.md` — 306 lines, ends cleanly at the §5 error table (verified with `tail -5`).

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (7 opaque roles, individually named), 2.2 API Response Structure (**verified byte-verbatim** against `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 The Logical Clock (default 2026-09-01T00:00:00Z, `to_iso8601`, no wall-clock fallback), 2.5 Common Resource Properties (incl. OCC-parent version bumps), 2.6 Precision and Rounding (2dp momentum, 4dp margin/MER, integer cents, half-up), 2.7 Season Posture Gate (FROZEN/CLOSED/GUARDED semantics, exemption list, `POST /categories` repair-path nuance), 2.8 OCC (both rules: `expected_variant_version`→`ERR_STALE_VARIANT_VERSION` 412, `expected_agreement_version`→`ERR_STALE_AGREEMENT_VERSION` 412), 2.9 Conservation Invariants (capacity + reserve ledgers), 2.10 Validation Priority Ordering (all 10 tiers, in order), 2.11 Resource Identification and Lookup Order (all 11 NOT_FOUND ids)
- §3 Business Logic (9 subsections): 3.1 seasons/categories, 3.2 research/momentum/prototype cycles, 3.3 variants/tooling/suspension cascade, 3.4 claim substantiation + segregation of duties, 3.5 media tests + pinned per-line MER rounding, 3.6 agreements/windows/commitments, 3.7 replenishment 5-step pinned evaluation, 3.8 patent cases/exposure contagion, 3.9 run-review (all 11 steps in order), freeze/unfreeze, close
- §4 Endpoint table (49/49 rows, path set matches scaffold exactly), §5 Error catalogue (41/41 ids)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 89 required (entities + request bodies + query/path params + nested `order_lines`/insight fields), 89 present, 0 missing — PASS (fence-aware extraction; no odd-backtick lines)
- Contract 2 (Rule Coverage, manual audit): validations priority 1–10 expressed in eval order (§2.10); 2/2 OCC rules with write op + field + error id + 412 (§2.8); all state-machine transitions with from/to states, preconditions, side effects — incl. both freeze paths, both claim-clearance re-entry siblings, both media KILL paths, retirement and suspension cascades, supersede cascade, and all 11 run-review steps; 8/8 calculations as prose with pinned constants (0.85 decay, 40.0, 75/4-budget/21d, 0.1500 inclusive/30 samples, provisional vs settled MER with per-line rounding order, 0.30 reserve, 2/5/9 weights ×3 adverse with 8/20 bands, 50-velocity/3-week/zero-reject/case-pack/capacity order, 150¢ penalty); 2/2 invariants; `applies_to` scopes enumerated (posture-gate exemptions, priority-7 compliance endpoints) — PASS
- Contract 3 (§3 Path Purity): 515 backtick tokens scanned, 0 path-like, 0 bare methods, 0 method+path combos — PASS
- Enum sweep: 55/55 state/enum strings present; constants sweep: 21/21 anchors pinned; fuzzy-word scan: clean

Orchestrator verification: PRD.md exists at 306 lines, ends at the §5 error table (ERR_REPLENISHMENT_NOT_NEEDED / ERR_CAPACITY_EXCEEDED / ERR_VARIANT_NOT_RETAIL_READY rows), 5 hits on pinned constants (0.1500, 2026-09-01, both STALE_VERSION error ids), 0 hits on design-file leakage tokens (SCAFFOLD_DIFFICULTY / scaffold_difficulty / scaffold_corner / test_recipe).

## Step 5a: Generate Test Helpers (Stage 1 of split Step 5) — 2026-10-02T02:05:00.000Z

Stage 1 is complete and verified. Summary:

**Files created (all under `test_helpers/`)**

| File | Lines | Contents |
|---|---|---|
| `types.py` | 366 | 19 enums (7 roles, postures, exposure levels, all 13 state-machine state sets, channels, severities, judgment outcomes, media decisions) + 12 entity TypedDicts + `ResearchInsight`/`OrderLine`; every entity carries §2.5 common fields (all 12 are `common_fields: true`) |
| `api_client.py` | 232 | `ApiClient(GenericApiClient)` with one method per endpoint — all 49 PRD §4 endpoints; no-body action POSTs send an explicit `{}`; `api_client` singleton |
| `api_errors.py` | 106 | `ApiErrorId` enum with all **41** catalog codes (4×400/401/403-class, 11×404, 12×409, 2×412, 12×422) + `HTTP_STATUS_CODES` map registered via `set_error_http_status_map` at import |
| `assertions.py` | 338 | 12 `assert_<entity>()` functions, `assert_capacity_conservation` + `assert_reserve_reconciliation` (the two §2.9 invariants), plus `validate_created(resp)` (201) / `validate_ok(resp)` (200) wrappers so no call site can silently default to 200 against a create's 201 |
| `factories.py` | 333 | 21 payload factories, input fields only; defaults match the design-index backbone (FW26, crowding_base 6, 115/100/40 → margin 0.15, spend 1000, window [2026-10-01, 2027-01-01), etc.); optional fields (`feedback`, `award_cents`) omitted when None |
| `constants.py` | 119 | 31 constants, each with a PRD-section citation comment |
| `test_users.py` | 89 | `TEST_USERS` (9 header sets) + per-role `make_<role>_headers` builders |
| `fixtures.py` | 686 | Primitive validated wrappers + composite fixtures: `setup_season_with_category`, `setup_engineering_locked_concept`, `setup_tooled_variant`, `setup_draft_variants`, `setup_substantiated_study`, `setup_airing_media`, `setup_decided_scale_media`, `setup_signed_agreement`, `setup_launch_ready`, `setup_retail_live_fulfilled`, `setup_retail_live_open_commitment`, `advance_variant_to_refresh_candidate`, `advance_variant_to_retired`, `setup_severe_guarded_season`, `setup_active_high_case`, `iso_plus_days` |
| `__init__.py` | 49 | Barrel export: framework generics + all PRD-specific modules |

**Constant anchors pinned (name=value, all grep-verified against PRD.md)**
`CLOCK_DEFAULT_ISO=2026-09-01T00:00:00Z`, `RESEARCH_DECAY_PER_WEEK=0.85`, `RESEARCH_SCORE_MIN=40.0`, `CONCEPT_MAX_AGE_DAYS=120`, `ROUND_MAX_OPEN_DAYS=21`, `MAX_ROUNDS_PER_CYCLE=4`, `ROUND_PASS_SCORE=75`, `CLAIM_MIN_MARGIN=0.15`, `CLAIM_MIN_SAMPLES=30`, `AGENCY_COMMISSION_RATE=0.15`, `MER_SCALE_MIN=2.0`, `MEDIA_DECISION_MAX_DAYS=28`, `PRIOR_ADVERSE_PROB=0.30`, `CASE_WEIGHT_LOW/MED/HIGH=2/5/9`, `ADVERSE_WEIGHT_MULTIPLIER=3`, `EXPOSURE_ELEVATED_MIN=8`, `EXPOSURE_SEVERE_MIN=20`, `GUARDED_GRACE_REVIEWS=2`, `SHORTFALL_PENALTY_CENTS=150`, `COVER_WEEKS=3`, `REPLENISH_MIN_WEEKLY_UNITS=50`, `MODEL_MAX_AGE_DAYS=240`, `REFRESH_GRACE_DAYS=30`, `TOOLING_WINDOW_DAYS=14`, `TOOLING_PARALLEL_SLOTS=2`, pagination `10/1/100/0`. All 27 pinning sentences confirmed present in PRD via grep; no unused constants kept.

**Role/header model**
All 7 roles are opaque (PRD §2.1 — X-User-ID never equals any entity id), so shared constants are canonical. Segregation of duties is served by pinned distinct operator ids matching the design indices: scientists `sci-anna` (conducts) / `sci-bob` (substantiates), counsels `lc-jane` (files) / `lc-john` (settles). No entity-backed builders were needed; generic per-role `make_*_headers(user_id)` builders exist for extra operators.

**Clock reachability**
All fixture dates derive from the 2026-09-01T00:00:00Z startup default and move only forward via `set_clock` (09-10 lock read at momentum exactly 50.0, 10-16 go-live review, 2027-06-14 candidacy at 241 days, 2027-07-15 retirement at 31 days). Insight `observed_at` 2026-09-08 while the clock reads 09-01 is PRD-legal (future timestamps clamp to zero weeks, §3.2).

**Verification**
- `python3 -m compileall -q test_helpers/` → OK
- Package import (`sys.path` insert + `import test_helpers`) → OK; 41 error ids, 9 header sets, 53 public client methods
- AST import-graph check: every relative import resolves inside `test_helpers/`, every absolute import resolves to stdlib/installed packages → `IMPORT_GRAPH_OK`
- No "scaffold" strings in any helper file (grep exit 1); no `test_suite/` or test file created

Ready for Stage 2, which should treat these helpers as frozen.

Orchestrator verification: 9 helper files present (incl. `__init__.py`), `python3 -m compileall -q test_helpers/` → COMPILE_OK, no `test_suite/` directory yet, fixtures.py/factories.py/assertions.py contain 54/22/21 `def`s respectively.

## Step 5b: Generate Test Suite (Stage 2 of split Step 5) — 2026-10-02T02:40:00.000Z

All verification gates pass. Final summary below.

**Stage 2 complete — test_suite generated**

**Files created** (all under `test_suite/`):

| File | Tests | Contents |
|---|---|---|
| `conftest.py` | — | Session `api` fixture + 9 role-header fixtures |
| `test_01_envelope_and_lookup.py` | 9 | Envelope shape, typed 404s, pagination, unknown-FK |
| `test_02_creation_input_discipline.py` | 6 | Defaults, ignored client/system fields, enum/range, uniqueness |
| `test_03_auth_rbac_sod.py` | 7 | 401/403, per-endpoint RBAC, both SoD pairs |
| `test_04_research_prototype_cycles.py` | 8 | Momentum decay/gate, round budget, revert, deadline kill |
| `test_05_claim_substantiation.py` | 7 | Sample floor, margin 0.15 boundary, TOOLED gate, challenge/retest cycle |
| `test_06_media_economics.py` | 10 | Provisional vs settled MER, per-line rounding pin, decision band, parallel dimensions |
| `test_07_retail_windows.py` | 6 | Window-elapsed, expiry at window_end, half-open overlap/adjacency, p7-beats-p8 |
| `test_08_commitments_capacity.py` | 8 | Window rule, fulfillment, suspend penalty, create/cancel conservation, frozen-beats-capacity, OCC agreement |
| `test_09_replenishment.py` | 9 | 5-step clamp (216), zero-need boundary, velocity-first, capacity, supersede, OCC variant, retired lockdown |
| `test_10_patent_exposure_posture.py` | 11 | Exposure bands, reserve dual-variant, favorable-ledger conservation, adverse cascade, guard/freeze/recover, close gate |
| `test_11_season_posture_admin.py` | 5 | Frozen/closed blankets, guarded scope, unfreeze precondition, review inertness |
| `test_12_tooling_and_retirement.py` | 6 | Tooling slot cap + elapse, partner-active gate, retirement cascade |

**AST tag audit (real parse, not grep):** 92 tests emitted; 0 untagged; 0 dual-tagged; 0 tags pointing to non-existent instances; 0 tests tagged to excluded stubs. Queue A (Difficulty): **18/18 instances, exactly 2 tests each**. Queue B (Corner): **56/56 live instances, ≥1 test each**; the 9 `excluded_because:` stubs were correctly not translated (all 9 stub `difficulty_instance` pointers resolve). No `skip`/`skipif`/`xfail` anywhere. Every docstring's last line is exactly one `Design:` tag. Every quoted PRD citation fragment survives a whitespace-normalized literal grep of PRD.md (0 misses).

**Verification:** `compileall` clean; `pytest test_suite/ --collect-only -q` → **92 collected, 0 errors** (no server needed; collection executes no requests).

**Skipped instances:** none — every live instance passed the PRD-first filter.

**Judgment calls / re-derivations (flagged):**
1. **`invalid_enum_and_range_values_rejected`** — PRD never names an error_id for an out-of-set enum (`severity: LOW|MED|HIGH` is stated verbatim, the rejection error is not). Kept on unique-derivability grounds: `ERR_INVALID_REQUEST` is the only 400 in the §5 catalogue, so two PRD-only readers converge. Same reasoning for **`study_create_missing_claim_text_rejected`** (required-field omission).
2. **`commitment_with_unknown_agreement_fk_returns_not_found`** — the recipe made *both* `agreement_id` and `variant_id` bogus, but PRD §2.11 pins no body-FK resolution order, so the error id wasn't uniquely derivable. I used a valid DRAFT variant so `agreement_id` is the only unresolvable FK (existence p3 precedes state p5, so DRAFT never interferes). Claim preserved.
3. **Clock-literal robustness** — recipes asserted string equality `created_at == "2026-09-10T00:00:00Z"` / `last_review_at == "2026-09-01T00:00:00Z"`, but PRD §2.5 pins "three fractional digits", so a faithful emitter may produce `.000Z`. I assert instant-equality via `datetime.fromisoformat` parse-compare instead. All recipe dates were verified reachable from the 2026-09-01 default and day-count arithmetic re-derived (121>120, 22>21, 29>28, 241>240, 31>30, tooling window [09-10, 09-24) vs 09-25) — all consistent with PRD-pinned constants; no drift found.

Orchestrator verification: 12 test files + conftest.py present; independent `pytest --collect-only -q` → 92 collected, 0 errors; tag frequency audit confirms 18 Difficulty tags × exactly 2 + 56 Corner tags × exactly 1 = 92 total, zero Corner duplicates, no skip/xfail marks anywhere in test_suite/.

## Step 6: Generate Implementation — 2026-10-02T03:15:00.000Z

Done. The implementation is complete and verified. Final report:

**Module list (18 files, `workspace/implementation/`)**

| Module | Contents | Endpoints |
|---|---|---|
| `app.py` | Flask app, blueprint registration, ApiError/HTTPException handlers, request lock, `0.0.0.0:$PORT` (default 10000) | — |
| `start.sh` / `requirements.txt` | Guarded install (`import flask` check) + `exec python3 app.py` | — |
| `constants.py` / `errors.py` / `state.py` | 27 pinned constants; `ApiError`; in-memory store (empty at boot, no seeding), logical clock at `2026-09-01T00:00:00Z` | — |
| `util.py` / `auth.py` / `serializers.py` | ISO-8601 (3-frac Z) parse/format, Decimal half-up rounding, exact-Fraction momentum, envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`, pagination in `meta`), 400 validators; X-User-ID/X-User-Role auth (401/403); 12 entity serializers with live computed fields | — |
| `services.py` | FK/path lookup, season resolution chains, posture gate, exposure engine + GUARDED contagion, live capacity ledger, suspend/retire cascades, 11-step run-review | — |
| `routes_admin.py` | clock, seasons, freeze/unfreeze/close/run-review, categories | 12 |
| `routes_concepts.py` | concepts, insights, advance ladder, rounds, round complete | 8 |
| `routes_partners.py` | partners + suspend cascade | 3 |
| `routes_variants.py` | variants, tooling slots, 3 reverse lookups | 7 |
| `routes_studies.py` | claim studies (segregation-guarded) | 5 |
| `routes_media.py` | media tests, air, decide (pinned per-line rounding) | 3 |
| `routes_retail.py` | agreements/sign, commitments (OCC), replenishments (OCC) | 8 |
| `routes_patent.py` | patent cases, settle (segregation), record-judgment | 3 |
| **Total** | | **49** (verified via `app.url_map`) |

**CONST completeness check (constraint 4)**
Grep of all `CONSTANTS["X"]` references vs `constants.py`: **27 referenced / 27 defined, 0 missing, 0 unused — PASS.**

**Guard audit (constraint 5)**
- **Catalog → site (all 41 covered)**: e.g. `ERR_SEGREGATION_OF_DUTIES` → `routes_studies.substantiate_study`, `routes_patent.settle_case`; `ERR_CLAIM_NOT_SUBSTANTIATED` → `air_media_test`; `ERR_CATEGORY_LITIGATION_BLOCKED` → `sign_agreement`; `ERR_STALE_*` (412) → the two OCC writes; `ERR_DECISION_BAND_MISMATCH` → `decide_media_test`; `ERR_VELOCITY_BELOW_THRESHOLD`/`ERR_REPLENISHMENT_NOT_NEEDED`/`ERR_CAPACITY_EXCEEDED` → replenishment's pinned 5-step order; posture trio → `services.posture_gate` + run-review; 11 NOT_FOUNDs → `get_or_404`/`req_fk`. Composed gates both enforced (e.g. air = posture×lifecycle×clearance; sign = posture×DRAFT×SEVERE×overlap×elapsed, in §2.10 priority order).
- **Site → PRD sentence**: every raise traces to PRD §3/§2.10 text; the only non-catalog raise is the defensive catch-all `ERR_INTERNAL` (500). Smoke caught and I fixed one real bug (season-resolution helper called with a variant where a child was expected — 7 call sites corrected).

**Interpretations chosen (ambiguous points, simpler/literal reading)**
1. **Version bumps** only where scaffold side_effects say "increments X.version by 1" (precedent: air flips variant TOOLED→DR_TESTING with no variant bump); system/cascade transitions refresh `updated_at` only. Round complete does **not** bump the round's version (both texts omit it).
2. **Run-review steps all scoped to the reviewed season** (step 2 rounds via concept→category→season).
3. **OCC fields required**: missing/non-int `expected_*_version` → 400; mismatch → 412.
4. **Commitment on non-SIGNED agreement** → `ERR_INVALID_STATE` (409, priority 5).
5. **Exclusivity check applies regardless of the signing agreement's own flag** (literal scaffold precondition).
6. **`GET /launch-commitments` FK-filter quirk**: unresolvable `agreement_id`/`variant_id` filter → 404 `ERR_COMMITMENT_NOT_FOUND` (catalog's "(or FK filter)" clause).
7. Pagination limit outside [1,100]/non-integer → 400. Datetime echoes normalized to UTC `...T....sssZ`. `api_request_timestamp` = wall clock; all domain timestamps/rules = logical clock.
8. System media-kill at run-review sets status only (`decided_at`/`settled_mer` stay null — scaffold attributes those to the manual path).

**Smoke transcript (dynamic port 57883, fresh `bash start.sh`)**
48/48 PASS: 201 create + envelope/meta/defaults; 200 read; 400 missing-field envelope; 401/403/404; clock set → `{}`; full chain category→concept→insight (momentum 50.0)→advance ladder→round (incl. `ERR_ROUND_ALREADY_OPEN`)→complete→ENGINEERING_LOCKED; partner; variant (incl. `ERR_MODEL_NUMBER_CONFLICT`); tool; study complete (margin 0.2); self-substantiate 403; second-scientist substantiate → clearance flips; media air (provisional 2.5, variant→DR_TESTING); KILL-vs-band 422; decide SCALE (settled 2.55 per-line rounding); agreement sign; stale-agreement 412 then 201; capacity ledger 500→650 after replenishment (raw need 150, case-pack 25); run-review → RETAIL_LIVE; freeze → `ERR_SEASON_FROZEN` on create; run-review under FROZEN; unfreeze. Server killed by exact PID afterward; no other processes touched. Isolation rule honored — no test-suite or difficulty-design files were read.

Orchestrator verification: 18 files present in workspace/implementation/ (15 .py + start.sh + requirements.txt), `python3 -m compileall -q` → COMPILE_OK, 2142 total source lines, start.sh is a guarded-install + `exec python3 app.py` launcher.

## Step 7: Test-Fix Iteration Loop — 2026-10-02T03:10:00.000Z

Clean sweep on the first iteration — no diagnostic work required.

**Summary**

- **Iterations run:** 1 (8 parallel rounds, all to completion).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.
- **Shadowed-fix list:** none — the sweep was green with zero test-side or implementation-side edits, so there are no sibling paths left unasserted by my changes. (Per the standing caveat: a green sweep proves tests match code, not PRD vs code — but no edits were made here, so nothing was shadowed by this step.)
- **Final sweep evidence:** all 8 results files present on disk at `workspace/implementation/results.{1..8}.json`, each verified with `passed == total == 92`, `failed == 0`. Files left in place per the results-file preservation contract.

The Step 6 implementation (18 files, 49 endpoints, in-memory state, logical clock at 2026-09-01T00:00:00Z) passes the full 92-test suite under `per-test-server` isolation with 8 concurrent rounds showing zero flakiness — no timing-sensitive races, no fixture-ordering artifacts, no port collisions.

Orchestrator verification: all 8 `results.{1..8}.json` files exist on disk; independent parse of each shows `passed=92, total=92, failed=0` for every round.

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T03:11:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-10-02T03:35:00.000Z

Done. The full report:

**Files**: `PRD.md` 306 lines → `PRD_COMPLETED.md` 306 lines (all edits in-paragraph), char-delta **+4291**. `diff -q` confirms they differ; 24/24 inserted-phrase grep checks passed. The task directory is untracked in git, so the byte-difference is evidenced by `diff` directly.

**Counts**: 9 ambiguity-pins (PRD-side), 0 mismatch-revisions of PRD claims, **2 impl-fixes** — both verified by a fresh 8-round sweep: all 8 `results.{1..8}.json` on disk show **92/92 passed, 0 failed, 0 errors** (run after the impl edits per the mandatory re-sweep rule).

### Impl-fixes (rule (a): PRD explicit, impl deviated)
- **§4 / routes_concepts.py:80** — impl-fix — mismatch — `POST /concepts/{id}/insights` returned `201`; PRD §4 explicitly assigns "append to a resource's collection" to `200 OK` and reserves `201` for the twelve enumerated resources (insights are not one; the response carries the *updated concept*, matching the 200 semantics). Changed to `return ok_object(ser_concept(c), 200)`.
- **§3.2 / routes_concepts.py:170-181 + services.py:153-165** — impl-fix — mismatch — `complete_round`/`expire_round` incremented the concept's `rounds_used` only while `PROTOTYPE_CYCLING`, but PRD §3.2 states the increment unconditionally ("Completing a round … incrementing the concept's `rounds_used` by one"; expiry "also increments `rounds_used`"), and §2.5's "`updated_at` refreshes on every mutation" was violated on a bare increment. Now: unconditional increment + `touch(concept)`; the revert stays scoped to `PROTOTYPE_CYCLING` (PRD pins it "from `PROTOTYPE_CYCLING` to `RESEARCHING`"). Behavior inside the cycle (all that tests exercise) is unchanged; sweep confirms.

### Ambiguity-pins (rule (b): PRD silent/admits impl's reading)
- **§2.2** — insert — ambiguity — `meta.api_request_timestamp` pinned as wall-clock request-receipt time; logical clock governs entity state only (`util.py:77-81`).
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; creation-timestamp ties broken by insertion sequence; `has_more` ⇔ `offset + len(page) < total_count`, `total_count` counts the full filtered collection (`util.py:111-135`).
- **§2.5** — insert — ambiguity — client-supplied system-managed/derived fields are ignored, not rejected (`routes_admin.py:160-168`, `routes_variants.py:36-52`); version-bump enumeration made exhaustive — unlisted mutations (round completion/expiry + `rounds_used`, reverts, run-review cascades, clearance flips, `TOOLED`→`DR_TESTING` on air, supersession, exposure recompute, contagion, penalty accrual) refresh `updated_at` only, never `version` (`routes_concepts.py:170`, `services.py` throughout, `routes_studies.py:22-26`, `routes_media.py:76-79`, `routes_retail.py:238-243`).
- **§2.8** — insert — ambiguity — missing/non-integer `expected_*_version` is `ERR_INVALID_REQUEST` (400), surfacing before the version comparison (`routes_retail.py:119`, `:205`).
- **§2.10** — insert — ambiguity — `ERR_INVALID_REQUEST` field validation occupies no ladder rung (enforced at point of use, so it may surface before or behind ranked failures per endpoint); within one priority tier, failures surface in narrative enumeration order.
- **§2.11** — revise — ambiguity — "no nested write paths" carved out for §4's action/append endpoints; "every resource can be fetched by its `id`" pinned to the §4 index (7 types fetch-by-id; rounds/studies/media/replenishments/cases read via create response + reverse lookups — impl matches the authoritative §4 table); absent/blank/non-string body FK → 400 vs well-formed-but-unknown → 404 (`services.py:25-29`); list filters match literally except the commitments list, whose `agreement_id`/`variant_id` filters resolve as FKs and 404 with `ERR_COMMITMENT_NOT_FOUND` (`routes_retail.py:159-164`); undefined routes → `ERR_INVALID_REQUEST` at the transport status (404/405) (`app.py:50-56`).
- **§3.2** — revise — ambiguity — insight `points` outside 1–100 → `ERR_INVALID_REQUEST`; appending permitted in every concept status incl. `LAUNCH_KILLED` (`routes_concepts.py:70-80`); "the current cycle" pinned as rounds opened since last entering `PROTOTYPE_CYCLING` (`cycle_base`, `routes_concepts.py:104-113`); revert threshold pinned "at least 4" (impl uses `>=`, covering passing rounds beyond the budget).
- **§3.5** — insert — ambiguity — `projected_gross_cents` is an integer ≥ 0 (`routes_media.py:68`); order-line fields are integers ≥ 0 (`routes_media.py:83-98`); a successful decision also records the supplied `order_lines` (`routes_media.py:127`).
- **§3.8** — insert — ambiguity — `settlement_cents` is an integer ≥ 0 (`routes_patent.py:59`); a FAVORABLE judgment ignores any supplied `award_cents` (`routes_patent.py:83-85`).

### Scan evidence (modules walked, behaviors checked)
All 15 impl modules (`app.py`, `auth.py`, `constants.py`, `errors.py`, `state.py`, `util.py`, `serializers.py`, `services.py`, all 8 route modules) were walked endpoint-by-endpoint: all 48 endpoints in the §4 table exist 1:1 with correct roles; validation priority order verified per endpoint against §2.10 (incl. test-backed orderings: litigation-beats-window, frozen-beats-capacity, posture-before-state on air); all formulas (momentum decay, margin, provisional/settled MER per-line rounding, reserve, exposure weights/banding, replenishment 5-step, tooling windows, penalties) match PRD constants exactly; all state machines, cascades, OCC guards, and the 11 run-review steps match. Every PRD-stated rule not listed above was found implemented as written.

Orchestrator verification: (1) mtime ordering — newest impl source edits (services.py 03:26:24, routes_concepts.py 03:26:17) precede the fresh results files (03:31:29), confirming the sweep ran AFTER the Step 9 impl edits; (2) independent parse of all 8 results files → 92/92/0 each, ALL_GREEN; (3) `diff -q PRD.md PRD_COMPLETED.md` → files differ (not a silent no-op), 306 lines each (in-paragraph edits); (4) spot-checks — 'wall-clock' pin ×2, §3.2 cycle/revert-threshold pins present at lines 130/134, `return ok_object(ser_concept(c), 200)` at routes_concepts.py:82, unconditional `rounds_used += 1` at routes_concepts.py:178 and services.py:162.
