# Worklog — task_3418_specialty_glass_co_development_capacity_commitment

## Step 1: Create task directory — 2026-10-01T21:57:37.886Z

Pre-allocated task directory `tasks/task_3418_specialty_glass_co_development_capacity_commitment/` verified present with empty `workspace/` inside (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate scaffold (subagent) — 2026-10-01T23:28:19.648Z

Verbatim subagent summary:

> All checks pass. Final state:
>
> **Files written** (all parse-validated after every append, and lint-clean):
> - `SCAFFOLD.yaml` — 1086 lines
> - `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 744 lines
> - `SCAFFOLD_CORNER_DESIGN.yaml` — 1475 lines
>
> **Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1010 calls scanned; 65 endpoints; 10 entities)
>
> **Counts:** 10 entities; 11 state machines (License carries two parallel dimensions: license_status × marketing_status); 5 calculations; 22 ordered validation rows; **65 endpoints**; 37 error codes; 6 roles; 2 OCC concurrency rules; 30 named constants.
>
> **§1.8:** 19 instances, all non-stub — dual_variant_calc 2, combinatorial_formula 3 (one per mode a/b/c), non_linear_state_machine 2, transitive_cascade 2 (depth-4 retire cascade; depth-3 IP-confirmation cascade), priority_pair_validation_conflict 2 (state-vs-fiscal; temporal-vs-referential), boundary_precision_check 2 (timestamp deadline vs integer days), cross_entity_state_dependency 2 (Campaign→Composition; License→Program), resource_temporal_overlap 2 (tank half-open+buffer vs license closed-interval), compensating_invariant 2 (supply units vs prepayment cents).
>
> **§1.9:** 61 non-stub + 8 stub — entities 6, state_machines 11, calculations 5, validations 10, endpoints 5, errors 16, rbac 2, cross_cutting_layers 5, consistency_model 1; stubs cite only existing difficulty instances (verified mechanically).
>
> **api_prefix:** `/glass`. **Constants:** 30 CONST.* (e.g. TANK_CONSTRUCTION_DAYS=540, MIN_CAMPAIGN_DAYS=365, CHANGEOVER_GAP_DAYS=45, MAX_QUAL_ATTEMPTS=3, YIELD steps 20000/80000 at 0.62/0.78/0.90, royalty tiers 100k/500k at 3.0/2.2/1.5%, MIN_PREPAYMENT_CENTS=1000000, TIER_A/B coverage 1.2/1.0, BREACH_GRACE_DAYS=90, DEFAULT_CLOCK_ISO=2026-09-01T00:00:00Z) — defined exactly once; grep audit: 30 referenced = 30 defined, no dups, no orphans.
>
> **Bootstrap/circularity check:** creation chain DeviceMaker → Program(NDA) → Composition → QualCycle → Commitment(sign/countersign/confirm, segregation-enforced) → Tank → Campaign → Allocation; License(program) → UsageReport(license). No mutually-dependent creation preconditions; every state reachable via declared endpoints.
>
> **Key design decisions downstream generators must honor:**
> 1. **Logical clock** defaults to 2026-09-01T00:00:00Z; all recipes only move it forward; tank readiness, freeze deadline, breach deadlines are all clock-gated.
> 2. **Multiple active commitments per program are allowed** (tranches) — I removed the single-active-commitment gate/error mid-design because it would have made the allocation waterfall trivially single-candidate; PROPOSED uniqueness is enforced by supersession (the OCC-backed create-with-supersede rule).
> 3. **Secondary-market licenses require a LOCKED base composition** (QUALIFIED insufficient) — otherwise the gate would be dead code, since freeze-design already guarantees a QUALIFIED composition exists.
> 4. **Royalty rounding order differs by design**: provisional = round-per-line-then-sum, final = sum-then-round-once (fixtures computed to diverge: 24 vs 25, 42 vs 41). Campaign cost ceils are applied per-component then summed. Commitment coverage tier derives from pre-bonus base_coverage only (order pinned; fixture base_coverage 1.18 → TIER_B exposes order-inverted implementations).
> 5. **IP monitoring folded into DeviceMaker.ip_review_status** (no separate IPCase entity) with a depth-3 cascade (confirm → licenses SUSPENDED/IP_REVIEW → reports HELD).
> 6. Every numeric assert is a pre-computed literal (verified with Python, including a float-hazard check on ceil(970/(30000/42000)) == 1358 under all plausible evaluation orders).
> 7. **Endpoint count is 65** — deliberately above the §0.4 Expert guideline band per the "much harder than expert" instruction (comparable to the in-repo lumen-loop example at 64). Pipeline owner note: implementation generation should chunk per-domain to avoid truncation.

Orchestrator verification (independent of subagent claims): all three YAMLs parse with `yaml.safe_load`; top-level keys correct (`scaffold_difficulty_design` / `scaffold_corner_design` present only in their own files); api_prefix `/glass`; 65 endpoints; 10 entities all glass-domain (DeviceMaker, Program, Composition, QualCycle, Tank, Campaign, Commitment, Allocation, License, UsageReport — no foreign-domain contamination); §1.8 = 19 instances, §1.9 = 61 instances counted structurally; constants audit: 30 defined keys, 30 unique referenced names, one-to-one match (an earlier 31st grep token was the bare prefix `CONST.` with empty name — artifact, not an orphan).

## Step 3: Copy shared files — 2026-10-01T23:29:21.720Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-10-01T23:47:27.616Z

Verbatim subagent summary:

> All checks pass. The PRD is complete and verified.
>
> **Output:** `workspace/PRD.md` — **355 lines**, ending at §5 Error Code Catalogue with no audit footer.
>
> **Confirmation counts (all mechanically verified against SCAFFOLD.yaml):**
> - **Constants pinned: 30/30** — every CONST.* value appears in prose, and each value is co-located with its CONST name inside a single sentence (e.g. "540 days (CONST.TANK_CONSTRUCTION_DAYS)", "0.62 (CONST.YIELD_STEP1_RATE)", "1000000 cents — CONST.MIN_PREPAYMENT_CENTS").
> - **Error IDs present: 37/37** — all in the §5 two-column table with correct HTTP statuses, and each also triggered in §2/§3 prose.
> - **Endpoint paths present: 65/65** (45 POST + 20 GET, matching the scaffold mix exactly); per-row role lists diffed against the scaffold with **0 mismatches**.
> - **State machines described: 11/11** — including both License dimensions (`license_status` × `marketing_status`) as separate machines; all 47 distinct state values present as exact UPPERCASE strings; every transition's from/to, preconditions, and hop-ordered side effects rendered in prose.
> - **Calculations with evaluation-order prose: 5/5** — royalty pinned as round-per-line-then-sum (provisional) vs sum-then-round-once (final); campaign cost pinned as two separately ceilinged components summed after; commitment coverage pinned as 7 ordered steps with tier derived from pre-bonus base coverage only; waterfall rank order (BREACH_WATCH first, tier descending, `signed_at` then `created_at` ascending, no ids); yield step curve with floor for `expected_good_units` and 6dp half-up for `realized_yield`.
> - **Contract 1 (field names): 90/90** scaffold field/request/query/path identifiers present as backticked tokens, plus usage-report line sub-fields `channel` and `net_revenue_cents`.
> - **Contract 2 (rules):** all 22 validation rows expressed in §2.8 in priority order with per-row error-id mappings (including rows 21/22's per-endpoint error lists and intra-row ordering), both OCC rules with exact `expected_*_version` fields and 412 error ids, and all cascade hops enumerated.
> - **Contract 3 (§3 path purity): 0 violations** across §3 (no backticked `/`-tokens, no bare HTTP methods, no method+path combos, no unbackticked `/glass/` strings).
> - **§2.2 block: byte-identical** to `section-2.2-response-structure.md`.
>
> **Ambiguities found and resolved in prose:**
> 1. `ERR_TANK_UNDER_CONSTRUCTION` serves two priorities (row 14 commission-timing; row 17 CONSTRUCTING-tank reference at campaign create/start) — rendered faithfully in both rows with the shared-priority note.
> 2. `apply-prepayment` carries no state gate anywhere in the scaffold — I deliberately did not invent one; only the positivity and over-apply caps are stated.
> 3. Supersession of `PROPOSED` commitments at creation: scaffold says released via the normal release cascade; since `PROPOSED` commitments can never hold allocations (allocation creation requires `SECURED`/`BREACH_WATCH`), the prose states the superseded proposals are released "exactly as the release cascade describes" without inventing allocation effects.
> 4. Campaign completion's dual trigger (planner action or ops checkpoint) shares one precondition (clock ≥ `end_date`) — stated once, both callers named.
>
> The two withheld test-targeting indices (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were never opened.

Orchestrator verification: PRD.md is 355 lines; mechanical grep confirms 30/30 CONST names, 37/37 error_ids, 65/65 endpoint paths present; `2026-09-01` clock start present; no foreign-domain terms.

## Step 5a: Generate test_helpers (subagent, stage 1 of 2) — 2026-10-02T00:08:54.454Z

Step 5 was split into 5a (helpers, frozen) + 5b (tests) per the oversized-generation-step playbook: 80 non-stub design instances (19 §1.8 + 61 §1.9) is too large for one pass.

Verbatim subagent summary:

> Stage 5a complete. Summary follows.
>
> **Files written (all under `test_helpers/`)**
>
> | File | Lines | Contents |
> |---|---|---|
> | `__init__.py` | 49 | Barrel: framework generics + all helper modules |
> | `types.py` | 311 | 18 enums (roles, 8 state machines, markets, tiers) + 11 TypedDicts (10 entities + CheckpointResult); all entities carry id/created_at/updated_at/version (all `common_fields: true` here) |
> | `api_client.py` | 241 | `ApiClient(GenericApiClient)` with all 48 endpoints under `/glass`; base URL from `API_BASE_URL` env via the framework constructor (verified the runner sets one fixed URL per pytest subprocess); `headers=None` permitted for unauthenticated requests |
> | `api_errors.py` | 93 | `ApiErrorId` (37 errors) + HTTP map, registered with `set_error_http_status_map` at import |
> | `assertions.py` | 229 | `assert_<entity>` for all 10 entities, `validate_created` (explicit 201 — never relies on the 200 default), plus invariants: `assert_campaign_supply_conservation`, `assert_prepayment_ledger_conserved`, `assert_standing_demoted_one_step` |
> | `factories.py` | 258 | 19 payload factories, input fields only, PRD-valid defaults |
> | `constants.py` | 122 | All 30 CONST values + pagination + role strings, each annotated with its PRD quote |
> | `test_users.py` | 102 | `TEST_USERS` header dicts (distinct UUIDs per opaque role) + `make_<role>_headers` builders for all six roles incl. entity-backed `make_device_maker_headers`, malformed-header helpers |
> | `fixtures.py` | 749 | ~45 composable fixtures (catalog below) |
>
> No `test_suite/`, `conftest.py`, or `pytest.ini` created.
>
> **Constants diff: 30/30 match PRD prose, zero mismatches.** Mechanical check confirmed each value equals the PRD-stated numeral and appears adjacent to its `CONST.*` name in PRD.md (§2.4, §3.3–§3.8). Notable anchors: DEFAULT_CLOCK_ISO `2026-09-01T00:00:00Z`, TANK_CONSTRUCTION_DAYS 540, MIN/MAX_CAMPAIGN_DAYS 365/1825, CHANGEOVER_GAP_DAYS 45, yield steps 20000/0.62, 80000/0.78, 0.90, energy tier 50000/120/60, base melt 850, changeover amortization 4000/day, prepayment credit 1000/min 1000000, coverage 1.2/1.0, bonuses 0.05/0.02, supply min 1.0, grace 90, royalty 100000/0.03, 500000/0.022, 0.015. Recipe date math re-derived independently: tank ready 2028-02-23 (= default clock + 540d), default window exactly 365 days, breach deadline 2028-03-01 + 90d = 2028-05-30, license terms ≥ 180d — all reachable forward from the default clock.
>
> **Fixture/factory catalog (per entity, PRD preconditions satisfied)**
> - **DeviceMaker** — `create_device_maker(name, region, standing_tier?, ip_review_status?)` (PlatformAdmin; IP posture walked via legal hops).
> - **Program** — `create_program`, `execute_nda`, `create_program_with_nda`, `begin_qualification` (deadline strictly future), `freeze_design`, `rework_program`, `close_program`, `terminate_program` (cascade).
> - **Composition** — `create_composition` (NDA gate, first-composition auto-advance), `create_tuned_composition`, `create_qualified_composition`, `create_locked_composition`, `lock_composition`, `retire_composition`.
> - **QualCycle** — `create_qual_cycle`, `begin_testing`/`record_qual_result` (ownership-threaded maker headers), `resubmit_qual_cycle`.
> - **Commitment** — `create_commitment` (re-observes `expected_program_version`), `sign_commitment` (X-User-ID = maker id), `countersign_commitment` (planner-01 default), `confirm_prepayment` (fin-01 default, ≠ countersigner), `create_secured_commitment`, `apply_prepayment`, `release_commitment`.
> - **Tank** — `create_tank` (SECURED gate), `commission_tank` (sets clock to the tank's own `construction_ready_date` first — works from any creation clock), `create_commissioned_tank`.
> - **Campaign** — `create_campaign`, `start_campaign` (clock to start_date), `create_running_campaign`, `record_production`, `abort_campaign`, `complete_campaign` (clock to end_date).
> - **Allocation** — `create_allocation` (re-observes `expected_commitment_version`), `fulfill_allocation`, `release_allocation`.
> - **License** — `create_license`, `activate_license`, `suspend_license`, `reinstate_license`, `submit_marketing` (maker-threaded), `review_marketing`; composite `setup_licensing_chain` (DESIGN_FROZEN program, optional LOCKED composition for secondary markets, optional clock move into term), `setup_active_license`, `setup_approved_marketing_license`.
> - **UsageReport** — `create_usage_report` (maker-threaded), `accept_usage_report`, `dispute_usage_report`, `create_accepted_report`.
> - **Composites** — `setup_supply_chain` (maker→…→SCHEDULED campaign; `standing_tier`, `composition_maturity` TUNED/QUALIFIED/LOCKED, all unit/prepayment knobs), `setup_supply_chain_with_allocation`, `setup_running_supply_chain`, `setup_running_chain_with_allocation`; plus `set_clock`, `shift_iso`, `run_checkpoint`.
>
> **Capabilities checklist — every recipe expressible, no skip candidates**
> §1.8 (19/19): both dual_variant (provisional/final cost & royalty rounding), all 3 combinatorial (changeover interaction, nested rounding, coverage order — default fixture arithmetic reproduces 1244/1358, 1192, 42/41, 14443), both non-linear machines (qual loop, parallel license dims), both cascades (retire 4-hop with STRATEGIC maker via `standing_tier=`, IP 3-hop), both priority pairs (PROPOSED+fiscal via raw `create_allocation`; temporal+referential via second EXPERIMENTAL composition), both boundary checks (clock-at-deadline, 365-day window is the fixture default), both cross-entity gates (TUNED via `composition_maturity="TUNED"`, pre-freeze license activate), both temporal overlaps (45-day gap via explicit dates; closed-interval license adjacency via `lock_composition=True` + date overrides), both compensating invariants (allocate/release pair; apply/release ledger pair).
>
> §1.9 sections (all 61 non-stub): entities (6) — defaults/404/pagination/multiplier/missing-field/maker-copy all direct; state_machines (11) — incl. checkpoint-driven EXPIRED/EXHAUSTED/BREACHED via `run_checkpoint` + `set_clock`; calculations (5) — yield 20000/80000 and energy 49999/50000 boundaries via `planned_units` overrides with same-composition adjacency, royalty 100000/100001 via line units, coverage 1.00/0.5 gates; validations (9+1) — auth/role/NDA/ownership/segregation/404-ordering/period-overlap/freeze-past-deadline/364-day/secondary-market; endpoints (5) — envelopes, allocation FK filters, waterfall two-commitment tier order (second `create_secured_commitment` on the same program), empty-pool waterfall; errors (16) — all reachable through raw client calls on fixture-built state, incl. cross-program allocation (two programs, one maker) and capacity-10 tank; rbac (2); cross_cutting_layers (5) — both OCC 412s via captured stale versions, version-bump, empty retire cascade, immediate reconciliation; consistency_model (1). The 8 `excluded_because:` stubs resolve to real difficulty instances.
>
> **PRD ambiguities resolved**
> 1. **License term length for the closed interval** — PRD §3.7: "must span at least 180 days (CONST.LICENSE_MIN_TERM_DAYS)". I treat span as `expiry_date - effective_date` in days (≥180); the design index's shortest recipe term (2028-12-31→2030-12-30 = 729d) satisfies this reading. Factories only emit ≥180-day terms.
> 2. **Tank commissioning clock move** — PRD §3.5: "`construction_ready_date` is fixed at creation to its `created_at` plus 540 days". `commission_tank` reads the server's own `construction_ready_date` and moves the clock there rather than assuming the default creation clock, so fixtures stay correct even when a test created the tank at a later clock reading.
> 3. **`DeviceMaker` list/get for a maker-role caller** — PRD §2.1 says ownership checks apply to the enumerated writes only; GETs accept all six roles with no ownership comparison. Helpers issue GETs with opaque-role headers (Manager/Planner) to avoid implying an ownership rule the PRD doesn't state.
>
> Verification done: `py_compile` clean on all 9 files; `import test_helpers` and each submodule succeeds with `socket.connect` broken (zero import-time side effects, no network); barrel exports spot-checked (25+ names).

Orchestrator verification: 9 files present (2154 lines total), `py_compile` clean, `import test_helpers` clean, all 34 exported constant values appear verbatim in PRD.md, no `test_suite/` directory created. Endpoint-route coverage: normalized path-skeleton diff confirms all 65 scaffold endpoints are reachable via `api_client.py` (an initial naive substring diff "found 43 missing" — the known camelCase `{paramId}` vs f-string `{param_id}` normalization false alarm; 0 skeletons missing after normalization).

## Step 5b: Generate test_suite (subagent, stage 2 of 2) — 2026-10-02T00:44:35.889Z

Verbatim subagent summary:

> Stage 5b is complete. All verification gates pass.
>
> **Files written (11 files, 2335 lines, all under `test_suite/`)**
>
> | File | Lines | Tests |
> |---|---|---|
> | `conftest.py` | 47 | — (session `api` fixture + 6 role-header fixtures; nothing else reset) |
> | `test_01_api_basics.py` | 174 | 9 — envelope, pagination, auth 401, role 403s, 404s |
> | `test_02_program_lifecycle.py` | 184 | 8 — maker defaults, DRAFT, NDA gate, terminate lockdown, freeze deadline both sides |
> | `test_03_composition_qualification.py` | 190 | 7 — shape/uniqueness rules, LOCKED retire, resubmit cap + loop, retire no-op |
> | `test_04_commitments_coverage_prepayment.py` | 274 | 10 — creation copy, coverage tiers/gate/order, ownership, SoD, ledger conservation, program OCC |
> | `test_05_tanks_campaign_scheduling.py` | 262 | 9 — funding gate, one-tank, construction readiness, window 364/365, capacity, start gate, temporal>referential priority, 45-day changeover |
> | `test_06_campaign_costs_execution_checkpoint.py` | 323 | 9 — yield steps, energy tier, provisional-vs-final cost, changeover cost interaction, complete gate, QUALIFIED start gate, abort cascade, exhaustion + breach checkpoint sweeps |
> | `test_07_allocations_waterfall.py` | 278 | 10 — positivity/need/headroom/program-mismatch, filtered listing, waterfall tier order + empty pool, state>fiscal priority, commitment OCC both directions |
> | `test_08_cascades_consistency.py` | 231 | 6 — retire 4-hop cascade, terminate cascade, IP 2-hop cascade, derived-field reconciliation, immediate visibility, supply conservation |
> | `test_09_licensing.py` | 199 | 7 — DESIGN_FROZEN gate, closed-interval overlap, checkpoint expiry, term/IP-hold/secondary-market gates, parallel status dimensions |
> | `test_10_royalty_reporting.py` | 173 | 5 — rounding-order divergence (both instances), tier boundary, period-overlap supersession, marketing gate |
>
> **Collection:** `python3 -m pytest test_suite --collect-only -q` → **80 tests collected, 0 errors** (run with `PYTHONPATH=.` from the task root; no server started, per constraint 7).
>
> **Coverage**
> - **§1.8 Difficulty: 19/19 emitted, 0 skipped.**
> - **§1.9 Corner: 61/61 non-stub emitted, 0 skipped** (entities 6, state_machines 11, calculations 5, validations 9+1, endpoints 5, errors 16, rbac 2, cross_cutting_layers 5, consistency_model 1). The 8 `excluded_because:` stubs were not translated; all 8 cross-references resolve to real difficulty instances.
> - **Final audit (AST walk):** 80 emitted tags vs 80 expected non-stub instances — exact set match; every tag is the last docstring line; zero untagged, zero duplicate, zero unknown tags.
> - **Citation pass:** 83 distinctive ≥8-word substrings drawn from every docstring citation all survive literal (whitespace-normalized) grep of `workspace/PRD.md`.
>
> **Decisions and notes**
> - **No skips.** This PRD is unusually complete: §2.8 states the validation order normatively in prose ("the failure reported is the one with the highest priority… the first failure wins"), which legitimizes both priority-pair difficulty instances; every error id has a narrative trigger; every constant is pinned in prose.
> - **No test_helpers additions or modifications** — the frozen Stage-5a stack covered everything; only new files under `test_suite/` were created.
> - **All design literals re-derived from PRD+constants and agreed with the index** (1244/1358 + realized 0.714286, royalty 24-vs-25 and 42-vs-41, coverage TIER_B/14443 at base 1.18, changeover costs 1192/1711, yield boundaries 15600/72000/38999/39000, royalty boundaries 3000/2200, 12240 at coverage exactly 1.0, breach deadline 2028-05-30, tank ready 2028-02-23). Zero discrepancies.
> - **Timestamp robustness:** where a computed instant is asserted (tank `construction_ready_date`, `breach_deadline`), tests compare parsed datetimes against `shift_iso(...)` rather than string equality, so a serializer emitting `.000Z` still passes; the PRD pins the instant, not the rendering.
> - Creation calls use `validate_created`/explicit 201 throughout; error calls use `validate_error` with the registered HTTP-status map; clock movement goes exclusively through `set_clock`/`shift_iso`; no date precedes the 2026-09-01 logical-clock default.

Orchestrator verification (independent AST audit): `pytest --collect-only -q` collects exactly 80 tests with 0 errors; AST-walked docstring `Design:` tags = 80, expected non-stub instances across both indices = 80, exact set match (missing: [], extra: []).

## Step 6: Generate implementation (subagent) — 2026-10-02T01:26:09.502Z

Launched sequentially AFTER Step 5b completed (endpoint duplicates parallel tool calls; concurrency ban). ISOLATION RULE and PROCESS SAFETY copied verbatim into the prompt.

Verbatim subagent summary:

> Implementation complete. Summary below.
>
> **Files written (23 files, 2,929 lines) in `workspace/implementation/`**
>
> | File | Lines | Role |
> |---|---|---|
> | start.sh | 10 | `$PORT`/`0.0.0.0`/foreground `exec`, guarded pip install |
> | requirements.txt | 1 | flask>=3.0,<4 |
> | constants.py | 47 | all 30 CONST values, verbatim |
> | errors.py | 90 | all 37 error ids + HTTP statuses |
> | clock.py | 40 | logical clock, default `2026-09-01T00:00:00Z` |
> | store.py | 34 | in-memory dicts, `touch()` version/updated_at discipline; no seeding |
> | validation.py | 116 | auth (priorities 1-2), shape helpers (3), pagination |
> | response.py | 51 | exact `meta`/`response_type`/`data` envelope |
> | serializers.py | 172 | 10 entity serializers, ms-precision timestamps |
> | calculations.py | 147 | yield curve, unit cost, royalty, coverage, supply coverage |
> | cascades.py | 138 | release/cancel/breach/demotion hops, campaign finalization |
> | routes_device_makers.py | 119 | 4 endpoints + infringement cascade |
> | routes_programs.py | 229 | 9 endpoints + terminate cascade |
> | routes_compositions.py | 140 | 5 endpoints + retire cascade |
> | routes_qual_cycles.py | 143 | 6 endpoints |
> | routes_tanks.py | 105 | 4 endpoints |
> | routes_campaigns.py | 321 | 8 endpoints + waterfall |
> | routes_commitments.py | 230 | 8 endpoints (OCC, supersession, coverage gate, SoD) |
> | routes_allocations.py | 206 | 5 endpoints |
> | routes_licenses.py | 258 | 9 endpoints (dual state dimensions) |
> | routes_usage_reports.py | 180 | 5 endpoints (per-line vs sum-then-round) |
> | routes_system.py | 85 | clock set + 5-sweep checkpoint |
> | app.py | 67 | factory, envelope error handlers (incl. 404/405/500) |
>
> **Endpoints: 65/65** (55 unique paths verified via `url_map`; both OCC rules with `expected_program_version`→412 `ERR_STALE_PROGRAM_VERSION` and `expected_commitment_version`→412 `ERR_STALE_COMMITMENT_VERSION`). All 37 error ids wired to live code paths. `py_compile` clean on all 20 modules; `import app` side-effect-free.
>
> **Self-smoke results (two fresh boots, dynamic ports, saved-PID kills)**
> - **Smoke 1 (49/49 pass)**: maker → program → **NDA-gate error check** (403, envelope `data.error_id == "ERR_NDA_REQUIRED"`) → NDA → composition (program auto-advance v3) → qual cycle (ownership 403, PASS→QUALIFIED) → begin-qualification → freeze → commitment (OCC 412 on stale version; SoD 403 when confirmer == countersigner; SECURED TIER_A eff 12600) → tank (commission blocked 422 early; succeeds at exact ready-date boundary) → campaign (expected 6200, provisional cost 2250) → start → record-production (realized 0.833333) → allocation (coverage 0.5, v5) → auto-allocate grants exactly headroom 1200 (coverage 0.62, v6) → license activate → marketing APPROVED → usage report (provisional 2400 / final 2400) → accept → checkpoint (1 completed, 1 expired, final cost 1675 = ceil(1395/0.833333)+0) → pagination meta.
> - **Smoke 2 (23/23 pass)**: fulfill → checkpoint EXHAUSTED; release → BREACH_WATCH + STRATEGIC→STANDARD demotion + deadline set; re-allocation → recovery to SECURED with deadline cleared; second release → STANDARD→PROBATION; checkpoint past deadline → BREACHED; stale SCHEDULED campaign cancelled by checkpoint; supersession releases PROPOSED commitment with refund (`prepayment_refunded_cents == 1500000`).
>
> **PRD ambiguities resolved (Step 7/8 audit targets), with the text relied on**
> 1. **All timestamps use the logical clock** (created_at, updated_at, signed_at, meta timestamp): "The system runs on a logical clock, never on wall-clock time" (§2.4). This makes `construction_ready_date = created_at + 540d` reachable by the clock.
> 2. **All datetimes serialized as ISO 8601 UTC with 3 fractional digits** (including echoed inputs like design_freeze_date); the clock-set response echoes `to_iso8601` **verbatim** as `current_utc`.
> 3. **version starts at 1**; each cascade hop that mutates an entity bumps it ("increments by exactly 1 on every mutation … including cascade-driven mutations", §2.5); a campaign cancelled with allocations released gets +2 (one per hop).
> 4. **Changeover-gap rule applies to all existing campaigns on the tank (any status); overlap rule only to non-terminal** — "must not overlap any existing **non-terminal** campaign window … and versus **every existing campaign** on that tank carrying a different composition_id, the gap …" (§2.8 row 13); gap measured via `(edge difference).days`, exactly 45 allowed.
> 5. **Terminate does NOT release commitments' allocations on RUNNING campaigns** — hop 2 covers only "every RESERVED allocation held by those cancelled campaigns" (§3.2); supersession/manual release do release them (§3.4).
> 6. **Reinstate skips the program-frozen/secondary-market checks** — PRD §3.7 lists only IP posture {CLEAR, CLEARED}, `clock <= expiry_date`, and overlap for reinstate (PRD wins over scaffold row 18's `applies_to` which also names reinstate).
> 7. **Reinstate with maker UNDER_REVIEW → ERR_IP_LITIGATION_HOLD** ("only when the maker's ip_review_status is CLEAR or CLEARED — any other posture fails").
> 8. **apply-prepayment allowed only on non-terminal commitments** ("While a commitment lives, finance may apply its prepayment", §3.4); terminal → 409.
> 9. **`committed_units`/`required_units`/`capacity_units_per_day` ≤ 0 → 400 ERR_INVALID_REQUEST** (row 21's ERR_NONPOSITIVE_UNITS names only `units`, `planned_units`, `good+scrap`; §2.8 row 3 is the catch-all for input-constraint violations).
> 10. **Negative `good_units`/`scrap_units` individually → 400; combined ≤ 0 → 422 ERR_NONPOSITIVE_UNITS** ("The two figures together must be strictly positive", §3.6).
> 11. **Coverage comparisons use the stored 4dp-rounded `supply_coverage`** ("its supply_coverage is recomputed, and if it has fallen below 1.0", §3.4).
> 12. **`final_unit_cost_cents` = null when final variant divides by zero** (cumulative_good = 0 with only-scrap records): PRD defines null only for "no production records", so I guarded the zero-yield/zero-good division as null rather than 500.
> 13. **auto-allocate has no campaign-state gate** (none stated in §3.6 or the endpoint table) and returns all created allocations with pagination meta `limit=max(len,1), offset=0, has_more=false`.
> 14. **Pagination clamps** (limit→[1,100], offset→≥0); non-integer limit/offset → 400; unknown list-filter enum values match nothing (no error).
> 15. **Creating compositions/commitments/licenses against TERMINATED/CLOSED programs is allowed** (only the DRAFT NDA gate is stated); the auto-advance fires only from NDA_EXECUTED per the state machine.
> 16. **`reason`, `materials_ref` validated but not persisted** (no entity fields exist for them); `effective_coverage` computed per pinned step 7 but not exposed (no such field in the entity table).
> 17. **QualCycle creation allowed on any composition status** (no gate stated; the TUNED→QUALIFIED side effect no-ops on LOCKED/RETIRED).
> 18. **Waterfall ties beyond `created_at` broken by insertion order** (stable sort) — "no id anywhere in the ordering" (§3.6).
> 19. **`prior_campaign` ties on equal `end_date`**: first-created wins (unspecified in PRD).
> 20. **DeviceMaker-role requests with non-entity X-User-ID still authenticate** (§2.1: rejection only for missing headers/undeclared role); ownership failures surface as 403 ERR_OWNERSHIP_MISMATCH at priority 5.

Orchestrator verification: 23 files (2928 lines by wc), `py_compile` clean on all modules; `start.sh` is `$PORT`/`0.0.0.0`/foreground with guarded pip install; all 65 scaffold route skeletons confirmed present by direct grep (an automated skeleton diff flagged 6 — all 6 then found verbatim as `@bp.route` decorators; checker artifact, not missing routes); impl `constants.py` wraps decimals in `Decimal("…")` — inner values match PRD (30/30, Decimal wrapper was a false positive in the naive grep). The 20 "interpretations chosen" items above are forwarded to Step 7 as candidate over-guard audit context.

## Step 7: Run tests and iterate (single long-lived subagent) — 2026-10-02T01:38:38.742Z

Verbatim subagent summary:

> ## Summary
>
> - **Iterations run:** 2 (first sweep: 77/80 × 8 rounds with 3 deterministic failures; second sweep after one helper fix: clean).
>
> - **Tests deleted:** none. All three failing tests were PRD-verbatim covered and uniquely derivable:
>   - `test_finance_cannot_activate_license` — PRD §2.1 forbidden-role rule + §4 endpoint table (activate = LegalCounsel only).
>   - `test_commitment_coverage_evaluation_order_pinned` — PRD §3.4 pinned 7-step coverage computation verbatim; math independently re-derived (credit 3160, base 14160, coverage 1.18 → TIER_B, `floor(14160*1.02)=14443`).
>   - `test_license_activate_requires_program_design_frozen` — PRD §3.7 "The referenced program must be `DESIGN_FROZEN`, failing otherwise with `ERR_PROGRAM_NOT_FROZEN`."
>
> - **Fixes applied to `test_helpers/`:** `test_helpers/fixtures.py` — `create_program_with_nda()` gained explicit `maker_name`/`maker_region` parameters (matching the convention used by the other chain fixtures at lines 434-435 and 613-614) which it forwards as `name=`/`region=` to `create_device_maker()`. The three failing tests all died at setup with `TypeError: create_device_maker() got an unexpected keyword argument 'maker_name'` before any HTTP request; the tests could not use plain `name=` because that parameter on `create_program_with_nda` names the *program*.
>
> - **Fixes applied to `test_suite/`:** none.
> - **Fixes applied to `implementation/`:** none — the implementation was correct on all three PRD rules.
>
> - **Sibling unasserted implementation paths** (test-side fix dominated, so naming per protocol):
>   1. **`effective_coverage` (PRD §3.4 step seven)** — "stored at four decimal places rounded half up": no test reads this field from a commitment response, and the implementation's interpretation #16 chose not to expose it. Step 8 should adjudicate whether §3.4's "stored" implies a response-visible field.
>   2. **`ERR_PROGRAM_NOT_FROZEN` from pre-QUALIFICATION states** — activation is only gated-tested from QUALIFICATION; NDA_EXECUTED/COMPOSITION_TUNING sources are never exercised.
>   3. **Forbidden-role on license activate for non-Finance roles** — only FinanceController is asserted; ProgramManager/CapacityPlanner/DeviceMaker/PlatformAdmin on activate are unexercised.
>   4. **TIER_C branch of the coverage gate** (base coverage ≥1.0 but tier derivation's otherwise-branch interplay) — TIER_A and TIER_B are asserted; the zero-bonus TIER_C success path at exactly 1.0 is covered only implicitly via the boundary test.
>
> - **Final sweep evidence:** rounds 1-8 each `passed/total = 80/80`; `results.1.json` … `results.8.json` all remain on disk in `workspace/implementation/` (verified above).

Orchestrator verification: all 8 `results.${i}.json` parsed — each passed=80, total=80, failed=0. Fixture fix confirmed present at test_helpers/fixtures.py:133-139 (plus the pre-existing convention sites). `find workspace/implementation -name "*.py" -newer results.1.json` (excluding `__pycache__`) returns nothing — no post-sweep implementation writes, so the sweep remains valid.

## Step 8: Finalize PRD (subagent) — 2026-10-02T01:45:28.479Z

Not skipped: Step 7 had 1 test_helpers fix (skip condition requires zero fixes of every kind). Zero-edit outcome was explicitly permitted in the prompt (fixture-only diff).

Verbatim subagent summary:

> Done. PRD_FINALIZED.md is written with exactly one inline revision; everything else is verbatim.
>
> **Line counts:** PRD.md 355 lines vs PRD_FINALIZED.md 355 lines — 0.0% line delta; the only change is an in-place sentence revision on line 179 (§3.4).
>
> **Changes (one edit):**
> - §3.4 (coverage confirmation calculation, step seven) — **revise** — "effective coverage … *stored* at four decimal places rounded half up" → "…*computed* at four decimal places rounded half up; the value is an intermediate of this confirmation calculation and is not stored on the commitment" — impl evidence: `workspace/implementation/calculations.py:118-125` computes `effective_coverage` (4dp, ROUND_HALF_UP) inside `coverage_snapshot`; `workspace/implementation/routes_commitments.py:193-195` persists only `coverage_tier` and `effective_units`; `workspace/implementation/routes_commitments.py:90-105` creates the commitment with no `effective_coverage` key; `workspace/implementation/serializers.py:106-127` never serializes it.
>
> **Diff items requiring no edit (with evidence):**
> - *Fixture fix (`create_program_with_nda` maker_name/maker_region)* — pure test-side signature bug; `TypeError` before any HTTP request. Verified at `test_helpers/fixtures.py:129-142` (new params forwarded as `name=`/`region=` to `create_device_maker`, fixtures.py:73-89). No PRD silence, no impl involvement — no edit.
> - *Sibling 2 (`ERR_PROGRAM_NOT_FROZEN` from pre-QUALIFICATION states)* — PRD §2.8 row 18 and §3.7 state the gate universally ("requires the program to be `DESIGN_FROZEN`, failing otherwise"); impl matches with a universal `!=` check at `workspace/implementation/routes_licenses.py:162-163`. NDA_EXECUTED/COMPOSITION_TUNING are already determined by the universal wording — no edit.
> - *Sibling 3 (forbidden-role on license activate)* — PRD §4 lists activate as LegalCounsel-only and §2.1/§2.8 row 2 pin `ERR_FORBIDDEN_ROLE` for any unlisted role; impl enforces `authenticate({ROLE_LEGAL_COUNSEL})` at `routes_licenses.py:143` via `validation.py:43-44`. Fully determined for all five other roles — no edit.
> - *Sibling 4 (TIER_C branch of the coverage gate)* — PRD §3.4 pins tier derivation (TIER_B at ≥1.0) and the gate (base coverage ≥1.0, exactly 1.0 passes); impl matches exactly (`calculations.py:109-114`, `constants.py:36` TIER_B_COVERAGE_MIN=1.0, gate at `routes_commitments.py:189`). The TIER_C branch (bonus 0) is reachable only when the gate fails, so it has no observable behavior; there is no "TIER_C success path" in PRD or impl — no edit.
>
> **Pre-edit search log (mandatory, for the single edit):**
> - (a) Subject: the confirmation coverage calculation's step-seven value (`effective_coverage`) and which computed values persist on the commitment.
> - (b) Impl paths enumerated and read/grepped: `calculations.py:104-126` (sole producer, `coverage_snapshot`); `routes_commitments.py:184` (sole callsite — confirmed by repo-wide grep for `coverage_snapshot`); `routes_commitments.py:193-195` (persist set = {coverage_tier, effective_units}); `routes_commitments.py:90-105` (creation initializer — no such key); `serializers.py:106-127` (commitment wire fields); `routes_campaigns.py:287` (waterfall consumes `coverage_tier` only, never `effective_coverage`); repo-wide grep for `effective_coverage` across `implementation/`, `test_suite/`, `test_helpers/` — hits only in `calculations.py`; PRD-wide grep for "effective coverage" — only §2.7 (line 98) and §3.4 (line 179).
> - (c) Wording adjustment: kept the formula, precision, and rounding mode verbatim ("`effective_units` divided by `required_units`", "four decimal places rounded half up") so the sentence stays true of `calculations.py:118-120`; changed only the persistence verb ("stored" → "computed") and added a non-persistence clause. §2.7 (line 98) left verbatim — its parenthetical pins the ratio's precision, which the revised §3.4 wording preserves, and §2.7 defers mode/precision to each §3 site. The paragraph's closing sentence ("On success the computed `coverage_tier` and `effective_units` are stored on the commitment; until then both are null.") left verbatim and now reads consistently with step seven. No enumerated path is mis-described; no new mismatch introduced.
>
> Output file: `workspace/PRD_FINALIZED.md`

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one revised line (179, the §3.4 effective_coverage persistence verb) — nothing else added, removed, or reordered; re-checked impl mtimes: still no post-sweep writes.

## Step 9: Complete PRD (subagent) — 2026-10-02T02:06:01.787Z

Verbatim subagent summary:

> The diff confirms exactly the 18 intended hunks, no collateral changes, file complete (355 lines in both, all edits in-paragraph). Work is done.
>
> **Files:** `PRD_FINALIZED.md` (source) 355 lines / 68,747 chars → `PRD_COMPLETED.md` 355 lines / 71,381 chars, char-delta **+2,634**. No new sections; all edits are inline inserts/revisions.
>
> **Counts:** 12 ambiguity-pins, 5 mismatch-revisions (18 diff hunks; the checkpoint "reached" pin spans two hunks).
>
> **Ambiguity pins (insert):**
> - §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — implementation/response.py:23
> - §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (non-integer → `ERR_INVALID_REQUEST`); `total_count` counts filtered matches; `has_more` ⟺ `offset`+`limit` < `total_count`; exact-match filters yield empty page on no match; `created_at` ties ordered by insertion — implementation/validation.py:105-116, response.py:34-43, routes_device_makers.py:78
> - §2.4 — insert — ambiguity — clock target may be any instant (no monotonicity guard); `current_utc` echoes the supplied `to_iso8601` string verbatim — implementation/routes_system.py:20-27
> - §2.5 — insert — ambiguity — `version` starts at 1; all server-stamped timestamps read the logical clock; every entity datetime field serialized ISO 8601 UTC with three fractional digits — implementation/store.py:25-28, clock.py:37-40, serializers.py:5-6
> - §2.8 row 3 — insert — ambiguity — shape gate also covers strictly-positive tank `capacity_units_per_day`, commitment `committed_units`/`required_units`, and non-negative production `good_units`/`scrap_units` (all → `ERR_INVALID_REQUEST` at shape priority) — implementation/routes_tanks.py:40, routes_commitments.py:62, routes_campaigns.py:245
> - §2.8 row 6 — insert — ambiguity — "acting on TERMINATED/CLOSED programs" scoped to the program's own lifecycle actions; child-resource creation under terminal programs is not state-gated — implementation/routes_programs.py:53-80, routes_commitments.py:66-77, routes_licenses.py:86-93, routes_qual_cycles.py:46-65
> - §3.3 — insert — ambiguity — qualification-cycle submission is not gated on composition status — implementation/routes_qual_cycles.py:52-53
> - §3.3 — insert — ambiguity — resubmit retains the previously stamped `result_recorded_at` until a new result is recorded — implementation/routes_qual_cycles.py:131-143
> - §3.4 — insert — ambiguity — new commitment starts `supply_coverage` and `fulfilled_units` at zero — implementation/routes_commitments.py:100-101
> - §3.6 — insert — ambiguity — final-variant changeover prior-campaign determination is re-evaluated at completion/abort time against then-current statuses; records totaling zero good units → `realized_yield` 0.000000 and `final_unit_cost_cents` null — implementation/cascades.py:128-138, calculations.py:53-56
> - §3.6 + §3.9 — insert — ambiguity — checkpoint cancels a still-SCHEDULED campaign whose `end_date` the clock has *reached* (>= boundary, matching impl, previously "passed") — implementation/routes_system.py:50
> - §3.6 — insert — ambiguity — waterfall is not gated on the campaign's own status (bounded only by `unallocated_units`); response lists created allocations in grant order; endpoint accepts no pagination parameters — implementation/routes_campaigns.py:265-321
>
> **Mismatch revisions (revise):**
> - §2.8 row 15 — revise — mismatch — reinstatement requires only clock at-or-before `expiry_date`, not the full closed interval (row previously said both bounds for activation and reinstatement; §3.7 and impl agree on expiry-only) — implementation/routes_licenses.py:203
> - §3.1 — revise — mismatch — `CLEARED` has no outgoing transitions (was "There are no terminal states in this machine"; impl `_IP_TRANSITIONS["CLEARED"] = set()`) — implementation/routes_device_makers.py:26-31
> - §3.2 — revise — mismatch — terminate's optional `reason` is accepted but not persisted — implementation/routes_programs.py:206
> - §3.4 — revise — mismatch — release's optional `reason` is accepted but not persisted — implementation/routes_commitments.py:225
> - §3.8 — revise — mismatch — dispute's optional `reason` is accepted but not persisted — implementation/routes_usage_reports.py:174
>
> **Verified already-pinned (no change):** the caution-listed interpretation choices that turned out to be pinned — changeover-gap scope ("every existing campaign on that tank", any status — routes_campaigns.py:86-106), waterfall tie-breaking (BREACH_WATCH first, tier desc, signed_at/created_at asc, no id — routes_campaigns.py:284-291), all 30 constants, all 37 error ids/HTTP statuses, validation priority order (spot-checked against every route's check sequence), coverage 7-step order, per-line vs sum-then-round royalty, cancel/abort cascade hop structure, and checkpoint sweep ordering. Recorded sweeps (implementation/results.1-8.json) all show 80/80 passing, consistent with a converged impl.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (not a mid-flight no-op); exactly 18 diff hunks; both files 355 lines (all edits in-paragraph). Spot-checked two mismatch revisions against impl source: `_IP_TRANSITIONS["CLEARED"] = set()` present at routes_device_makers.py:30 (§3.1 revision accurate); checkpoint sweep-2 uses `now >= camp["end_date"]` at routes_system.py:50 (§3.6/§3.9 "reached" pin accurate). Mismatch-revision review for stripped scaffold intent: all 5 revisions resolve intra-PRD drift or PRD-overstatement toward the tested implementation behavior (row 15 vs §3.7 internal consistency; CLEARED terminus; 3× optional-`reason` persistence claims for fields the scaffold entity tables never defined) — none removes a PRD-required check the implementation ships, so no impl fix was substituted and the Step 7 sweep remains valid. Post-Step-9 impl mtime check: no `.py` file newer than results.1.json (excluding `__pycache__`) — sweep not invalidated. All 8 `results.*.json` remain on disk (80/80 × 8).
