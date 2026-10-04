# Worklog — task_3266_configure_order_manufacturing_enterprise_asset_provisioning

## Step 1: Create task directory — 2026-09-30T15:49:00.000Z

Task directory `tasks/task_3266_configure_order_manufacturing_enterprise_asset_provisioning/` was pre-allocated (with `workspace/`) per the command args; verified it exists and is empty. No new index computed, no other task directory created.

## Step 2: Generate scaffold — 2026-09-30T16:16:00.000Z

All three artifacts are written and the lint is clean. Final verification of the end-state replay claims I should double-check: the `support_sla_response_hours` and `build_queue_sequencing` formulas are declared but only lightly exercised — both appear in grounds where needed and `build_queue_sequencing` is exercised by `build_out_of_sequence_rejected`; `support_sla_response_hours` constants underpin the parts-stocking instances. Acceptable.

Done. Summary of what was generated for `tasks/task_3266_configure_order_manufacturing_enterprise_asset_provisioning/`:

**Design** (Expert band, fresh from the scenario — no sibling tasks consulted):
- Archetype: graph constraint (component compatibility DAG) × quota/allocation (component stock pool), layered with optimistic concurrency, cascading side effects, dual-variant calculation, version-pinning on approval. Segregation-of-duties role model (customer approves substitutions, ops allocates, account manager locks program configs).

**Counts:**
- Entities: 15 (CustomerAccount, AccountProgram, ChassisModel, Component, CompatibilityRule, ConfigurationTemplate, Configuration, Order, OrderLine, BuildJob, SubstitutionRequest, DeploymentWave, Asset, SupportEntitlement, AssetRecoveryRequest)
- State machines: 7 — including a cyclic substitution negotiation loop (PENDING→REJECTED→PENDING with round counter), parallel build_status × ship_status dimensions on Order, and compound bubble-ups (job→order, shortage→hold)
- Calculations: 6 — dual-variant lead time (provisional vs committed), tiered promised-ship-date buffer, per-line-then-sum pinned rounding in order_pricing, weighted build-queue sequencing, SLA tier table, dual-variant recovery credit (estimated vs graded final)
- Endpoints: 77 (includes `/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default, discontinue endpoints for EOL closure, and all FK reverse-reachability GETs)
- Validations: 22 (ordered priority 1–20 with two extra priority-5 rows)
- Error catalog: 22 codes
- Concurrency rules: 2 OCC rules (Configuration version on order submit; Component version on restock)

**§1.8 difficulty design: 18 instances** (exactly 2 per rule, all nine rules, differentiation clauses honored — e.g., rounding-order divergence 184021 vs 184020 pinned with literal arithmetic; half-open wave adjacency vs closed entitlement intervals).

**§1.9 corner design: 45 instances** across all nine guide sections (entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, consistency model).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (673 calls scanned across 63 instances; instance names unique across the union.)

Notable fixes made during the build: added EOL `discontinue` endpoints (enum closure), an entitlement-cancel endpoint (parts-stocking compensating invariant), a declared ERR_SHORTAGE_PENDING validation row, and converted all flow-style payloads with nested arrays/bracketed grounds to valid YAML block/quoted forms.

## Step 3: Copy shared files — 2026-09-30T16:17:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3266_configure_order_manufacturing_enterprise_asset_provisioning/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T16:24:00.000Z

PRD generation complete. Summary:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3266_configure_order_manufacturing_enterprise_asset_provisioning/workspace/PRD.md` — 325 lines.

**Section structure**:
- §1 Introduction (2 paragraphs: dual-force framing of component pool + segregation of duties)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity prose, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit default 10, min 1, max 100, offset 0, `created_at` ascending), 2.4 Common Resource Properties (incl. CompatibilityRule exception — no `updated_at`/`version`), 2.5 Monetary Precision, 2.6 OCC (both `expected_configuration_version` → `ERR_STALE_CONFIGURATION_VERSION` 412 and `expected_component_version` → `ERR_STALE_COMPONENT_VERSION` 412), 2.7 Logical Clock (init `2026-09-01T00:00:00Z`, `to_iso8601`/`current_utc`), 2.8 Component Pool invariant (`available_units` = `stock_on_hand` − `reserved_units`), 2.9 Nested Retrieval + full validation priority ordering (auth → forbidden → not-found → invalid-state → priority-5 OCC/shortage freeze → business rules → malformed-request last), 2.10 Status Codes
- §3 Business Logic (9 subsections): accounts/programs/catalog, configurations & compatibility gate, lead time/pricing/promised ship date (provisional vs committed variants, per-line-then-sum rounding, tier discounts 0/8/12%, bulk threshold 50, FEDERAL/PREMier buffers), orders & lines (OCC + credit-limit + state preconditions on submit), factory floor (0.6/0.3/0.1 queue scoring, tie-breaks, inclusive exact-fit allocation), shortage/substitution (cyclic PENDING→REJECTED→PENDING loop, largest-shortfall tie-break, priority-4 state vs priority-10 fiscal ordering, SUPERSEDED cascade), deployment waves (half-open windows, adjacency allowed, shortage freeze, receivable settled at delivery), support entitlements (72/24/4-hour tiers, 17:00 NBD cutoff, SERVER+ONSITE_4H parts stocking, closed-interval overlap, reserved-part release on EXPIRED/CANCELLED), asset recovery (30% estimate vs 10/25/45% graded final, RECYCLE vs RESALE_CREDIT fork)
- §4 Endpoint table: 77 endpoints, 4 columns only (Method, Path, Description, Authorized Role)
- §5 Error catalogue: 22 errors, 2 columns only

**Zero-Silence / Hard Contract audit results**:
- Contract 1 (Field-Name Coverage): 81 required identifiers (all `entities[].fields[].name` + endpoint `input`/`query_params`), 81 present in backticks, 0 missing — **PASS**
- Contract 2 (Rule Coverage): all 20 priority-ordered validations expressed with error IDs and the priority ordering stated (including the priority-4-vs-10 and priority-5 freeze callouts); both `concurrency_rules[]` expressed with endpoint + `occ_field` + exact error id + 412 status; all state-machine transitions (Configuration incl. LOCKED→DRAFT cyclic revert and DRAFT→SUPERSEDED, Order dual-dimension build/ship incl. ON_HOLD cascades, BuildJob incl. shortage auto-transition, SubstitutionRequest cyclic + SUPERSEDED, DeploymentWave, SupportEntitlement, AssetRecoveryRequest) expressed with preconditions + side effects; all 6 calculations in precise prose with constants embedded (24-hour day, 50-unit bulk threshold, 0.6/0.3/0.1 weights, tier weights 3/2/1, 17:00 cutoff, 0.30/0.10/0.25/0.45 credit percentages); endpoint side effects (version bumps on restock/discontinue/submit, program-lock cascade, entitlement reservation ±1, asset minting) all covered — **PASS**
- Contract 3 (§3 Path Purity): 462 backticked tokens scanned in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations — **PASS**
- All 22 `errors[].id` strings appear in §2/§3 prose; all state enum values and enum-type field values present as exact strings.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or referenced.

## Step 5: Generate unit tests — 2026-09-30T16:45:00.000Z

Generation complete. Summary:

## Deliverables

**`test_helpers/` (9 files)** at `/home/ubuntu/github/CodingPRD/tasks/task_3266_configure_order_manufacturing_enterprise_asset_provisioning/test_helpers/`: `types.py` (all status enums + TypedDicts; `CompatibilityRule` correctly omits `updated_at`/`version`), `api_client.py` (all 76 PRD endpoints), `api_errors.py` (all 22 error IDs with HTTP map registered via `set_error_http_status_map` using `.value` keys), `assertions.py`, `factories.py`, `constants.py` (PRD thresholds: bulk 50, tier discounts, recovery grades, NBD cutoff), `test_users.py` (`make_customer_user_headers(account_id)` per-instance builder for the entity_backed role), `fixtures.py` (composite chains: `setup_validated_config`, `setup_submitted_order`, `setup_built_order`, `setup_shortage_blocked_order`, `setup_delivered_asset`, all identity-threaded), `__init__.py`.

**`test_suite/` (13 files, 83 tests)** — all collect cleanly under pytest; zero undefined names.

## Coverage

- **Queue A (Difficulty): 36 tests covering all 18/18 instances** — exactly ≥2 per instance (audit-verified).
- **Queue B (Corner): 47 tests covering all 45/45 non-stub instances** — ≥1 per instance (2 for `onsite_4h_server_requires_parts_stocking` and `build_out_of_sequence_rejected`, adding the satisfaction branches both recipes describe).

## Skipped assertions (no test emitted — PRD-silence gaps, not placeholders)

- `compatibility_rule_immutable_no_version_field` second assertion ("no PATCH/PUT endpoint exists") — absence of an endpoint is not observable as an HTTP assertion; the field-shape half is tested.
- `asset_report` image-inheritance check — the template-side fallback is covered by prose, but asserting `image_applied_ref` would couple to serializer details not uniquely pinned; the test asserts only the PRD-named report fields.

## Tag audit

Programmatic audit confirms every one of the 83 tests carries exactly one `Design:` line, every tag resolves to a real instance name in the source YAMLs, and there are no untagged/dual-tagged/dangling tags. No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings (PRD §-citations only).

## Step 6: Generate implementation — 2026-09-30T16:53:00.000Z

Done. Implementation generated for task_3266 (Configure-to-Order Manufacturing & Enterprise Asset Provisioning).

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3266_configure_order_manufacturing_enterprise_asset_provisioning/workspace/implementation/`):
- `start.sh` — guarded pip install (`import flask` check), `exec python3 app.py`, PORT env (default 10000), 0.0.0.0
- `requirements.txt` — flask
- `app.py` — entry point, blueprint registration, error handlers, entitlement-expiry sweep
- `db.py` — in-memory store (empty at boot, no seeding), logical clock fixed at 2026-09-01T00:00:00Z, id/timestamp/version helpers
- `errors.py` — ApiError + all 22 scaffold error IDs
- `response.py` — exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta for lists
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 4 roles, CustomerUser entity-backed ownership
- `helpers.py` — body/field validation (ERR_INVALID_REQUEST lowest priority), ISO8601 parsing, pagination (default 10, min 1, max 100), serializers with derived `available_units`, ownership chains
- `services/core.py` — calculations: lead_time (provisional on available_units vs committed on stock_on_hand, floor hours/24), per-line-round-then-sum pricing with Decimal ROUND_HALF_UP (STANDARD 0/PREMIER 8/FEDERAL 12 pct), promised_ship_date (tier buffer + bulk>=50 → +3d), build-queue weighted scoring (0.6/0.3/0.1, 4-decimal, rank desc, created_at tie-break), recovery credits (30% estimate; 10/25/45% final by grade), entitlement expiry sweep
- `routes/catalog.py`, `configurations.py`, `orders.py`, `build.py`, `waves.py`, `services_api.py` — one blueprint per resource group

**Endpoint count: 66** (all from the scaffold endpoint table, including `/api/_clock/set_current_utc`).

**Key semantics implemented**: dual order status dimensions (build × ship), shortage cascade (QUEUED→SHORTAGE_BLOCKED + auto SubstitutionRequest + order ON_HOLD, ERR_SHORTAGE_PENDING freeze on wave release/ship), substitution approve with state-before-fiscal precedence (ERR_INVALID_STATE 409 outranks ERR_CREDIT_LIMIT_EXCEEDED 402), cyclic reject→repropose loop with round increments, OCC on order submit (`expected_configuration_version`, 412) and component restock (`expected_component_version`, 412), half-open wave-window overlap (adjacency allowed), global build-queue min-rank start enforcement, asset minting with program-prefix tags, serial→PO asset report, per-cascade `updated_at`/`version` bumps (CompatibilityRule exempt — no version/updated_at).

**Boot verification**: two fresh-process boots on scratch ports 18791 and 18792 both succeeded. Smoke-tested the full lifecycle (account → chassis → component → configuration → validate → order → line → submit → allocate → start → complete → BUILT), pricing math (PREMIER 8%: 260000 → 239200, discount 20800), promised_ship_date from logical clock (2026-09-01 + 2d lead + 1d PREMIER buffer = 2026-09-04), 401/404 error envelope, clock setter, and empty-store fresh boot. Both PIDs killed exactly; ports confirmed free; `__pycache__` dirs removed.

## Step 7: Run tests and iterate — 2026-09-30T17:21:00.000Z

Clean sweep achieved: all 8 parallel rounds at 81/81.

## Summary

**Iterations run:** 3 sweeps (14 failures → 6 failures → clean).

**Tests deleted (2):**
- `test_lead_time_provisional_vs_committed_on_configuration` (test_03_calculations.py) — STEP 1b unique-derivability collapse. The asserted values (provisional 11 vs committed 1) require the lead-time shortfall to be measured against `config qty × order-line qty` (9); PRD §3.3 measures it against "the selected quantity" of the configuration alone (1), under which both variants read 0 shortfall. The line-qty scaling exists only in the scaffold's example numbers.
- `test_provisional_ignores_reservations_of_committed_variant` (test_03_calculations.py) — same collapse pattern (expected 10+1 vs 0+1 needs reservation 8 = 9−1, only possible under line-qty scaling).

**Fixes applied to `test_suite/`:**
- `test_03_calculations.py::test_order_pricing_round_per_line_then_sum` — STEP 1c: kept the PRD-covered per-line rounding assertions (92_005 / 92_016 / total 184_021) but corrected `discount_cents` to 16_001, the value the test's own quoted PRD formula yields (pre-discount 100_005+100_017=200_022 minus 184_021). The original 20_001 contradicted the PRD sentence it cited. (Note: I briefly flipped the line-total assertions on a hand-arithmetic slip — 92_004.60 rounds half-up to 92_005 — verified against Decimal and reverted.)
- `test_04_orders.py::test_submit_not_found_outranks_state` — STEP 2: submit is CustomerUser-only per PRD §4; the test sent PlatformAdmin, so ERR_FORBIDDEN (priority 2) correctly pre-empted the ERR_NOT_FOUND (priority 3) it was testing. Switched the caller to the owning account's CustomerUser headers.
- `test_06_substitutions.py::test_substitution_approve_state_outranks_fiscal` and `::test_stale_approval_never_reports_credit_limit_error` — STEP 2: both approved the auto-created substitution request directly, but per PRD §3.6 the factory's replacement reaches the table through the reject→repropose cycle (the auto-created request names no proposal; approval of a proposal-less request is correctly rejected ERR_SUBSTITUTION_INCOMPATIBLE). Added reject + FactoryOps repropose of the in-stock replacement before the first approve; the asserted priority (state over fiscal) is unchanged.

**Fixes applied to `test_helpers/`:**
- `fixtures.py::setup_delivered_asset` — the release/ship loop picked the role via bound-method identity (`fn is api_client.release_wave`), which silently sent FactoryOps headers to the AccountManager-only release endpoint whenever the helpers module was imported under two names (the runner's cwd/PYTHONPATH setup does exactly that). Replaced with two explicit calls: `release_wave(..., MANAGER)` then `ship_wave(..., OPS)` per PRD §4 roles. This was the single root cause of all 4 recovery-test setup failures (triage hint applied).

**Fixes applied to `implementation/`:**
- `helpers.py` — added `iso_z_logical()`: serializes whole-second instants without fractional digits (`2026-09-02T00:00:00Z`), matching PRD §2.7's canonical logical-clock representation.
- `routes/orders.py` — `submitted_at` and `promised_ship_date` (both logical-clock-derived; the latter at PRD-mandated day granularity) now use `iso_z_logical`.
- `routes/waves.py` — wave `ship_window_start`/`ship_window_end` echo via `iso_z_logical`; and in `release_wave` the ON_HOLD shortage freeze (PRD §3.7: "state-priority freeze (priority 5) is evaluated before any wave-window business rule") now runs before the BUILT state/business check, so an ON_HOLD order's wave release yields ERR_SHORTAGE_PENDING instead of ERR_INVALID_STATE.
- `routes/services_api.py` — `_clock/set_current_utc` response reports `current_utc` via `iso_z_logical`.
- `routes/build.py` — `repropose_sub`: the "must differ from the rejected one" comparison is skipped when the rejected request named no proposal (None), per PRD §3.6.

## Step 8: Finalize PRD — 2026-09-30T17:26:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_3266_configure_order_manufacturing_enterprise_asset_provisioning/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md 325 lines → PRD_FINALIZED.md 327 lines (+2 lines, +0.6%).

### Changes

- **§2.7 — insert** — Added a paragraph pinning the logical-clock canonical serialization: values reported against the logical clock (`current_utc` from the clock setter, order `submitted_at` and `promised_ship_date`, echoed wave `ship_window_start`/`ship_window_end`) omit the fractional-second part on whole-second instants (e.g. `2026-09-02T00:00:00Z`) and carry three fractional digits otherwise; explicitly distinct from the wall-clock `created_at`/`updated_at` format — `implementation/helpers.py:61-68`, `implementation/routes/orders.py:155-157`, `implementation/routes/waves.py:90-91`, `implementation/routes/services_api.py:305`.
- **§3.6 — revise** — The auto-created shortage `SubstitutionRequest` names no proposal: `proposed_component_id` null, `price_delta_cents` 0, `round` starts at 1; the first real replacement arrives via the reject→repropose cycle; approving a proposal-less request is `ERR_SUBSTITUTION_INCOMPATIBLE` (422) — `implementation/routes/build.py:101-110, 283-285`.
- **§3.6 — revise** — Reproposal "must differ from the rejected one" applies only when the rejected request named a proposal; a proposal-less rejected request accepts any otherwise-compatible component — `implementation/routes/build.py:333-341`.
- **§3.7 — revise** — On wave release, the ON_HOLD shortage freeze is evaluated after the wave's own `PLANNED` state check but before both the order-`BUILT` precondition and the window-overlap rule, so an ON_HOLD order's release yields `ERR_SHORTAGE_PENDING` not `ERR_INVALID_STATE` — `implementation/routes/waves.py:126-138`.

### Step-7 items that required no PRD edit

- Two deleted lead-time tests: PRD §3.3 already measures shortfall against "the selected quantity" of the configuration alone, matching `services/core.py:59-79` (`lead_time_days` uses per-configuration qty, no line-qty scaling).
- `discount_cents` test correction, `test_submit_not_found_outranks_state` caller-role fix, `setup_delivered_asset` role fix: pure test/fixture bugs; PRD already correct (§3.3 pricing formula, §4 role tables).

### Per-edit pre-edit search log

1. **§2.7 timestamp serialization** — (a) subject: serialization format of logical-clock-reported timestamps. (b) enumerated: `helpers.py:57-68` (`iso_z`, `iso_z_logical` incl. fractional fallback), `db.py:48-58` (`logical_now`, `set_logical_now`), `orders.py:154-157`, `waves.py:88-92`, `services_api.py:66-67` (entitlement coverage fields — use `iso_z`, NOT logical format), `services_api.py:297-305`. (c) reworded "derived from the logical clock" → "reported against the logical clock" because wave window bounds are client-supplied instants echoed in logical format; scoped the field list explicitly so entitlement `coverage_start`/`coverage_end` (3-digit `iso_z`) are excluded; added "three fractional digits otherwise" to cover `set_current_utc` with fractional instants.
2. **§3.6 auto-created request / proposal-less approval** — (a) subject: substitution-request proposal lifecycle. (b) enumerated: `build.py:89-114` (`_enter_shortage`), `build.py:271-309` (approve), `build.py:312-321` (reject), `build.py:324-349` (repropose) — the only creation/mutation sites. (c) moved "`round` starts at 1" out of the proposal-conditional clause so it covers the auto-created request (which also has round 1, build.py:107).
3. **§3.6 repropose must-differ scoping** — (a) subject: reproposal must-differ rule. (b) enumerated: `build.py:333-337` (None-skip), `build.py:101-110` (the None-proposal origin). (c) none beyond the conditional wording itself.
4. **§3.7 release freeze ordering** — (a) subject: release_wave check ordering. (b) enumerated: `waves.py:122-144` (release: PLANNED → freeze → BUILT → overlap), `waves.py:159-201` (ship: RELEASED → freeze → window membership), `_order_on_hold_with_pending_sub` at `waves.py:110-119`. (c) wording places the freeze after the wave's own state check (consistent with §2.9 priority 4 > 5 and with both release and ship paths) and before both release preconditions.

## Step 9: Complete PRD scan — 2026-09-30T17:31:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_3266_configure_order_manufacturing_enterprise_asset_provisioning/workspace/PRD_COMPLETED.md`, copied from `PRD_FINALIZED.md` (327 lines both; +4,001 chars across 17 inline hunks, no new sections).

**Counts: 14 ambiguity-pins, 3 mismatch-revisions (17 changes total).**

Changes:

- §3.1 — revise — ambiguity — pinned `ALLOWED` scoping: chassis with >=1 `ALLOWED` rule restricts selections to listed subjects; chassis with no `ALLOWED` rules imposes no membership constraint — `implementation/services/core.py:37-41`
- §3.2 — insert — ambiguity — non-`ACTIVE` account at configuration validate fails with `ERR_INVALID_STATE` (409) — `routes/configurations.py:119-121`
- §3.4 — insert — ambiguity — submitting an order with no lines is `ERR_INVALID_STATE` (409) — `routes/orders.py:131-132`
- §3.4 — insert — ambiguity — order cancellation from `SUBMITTED` is not blocked by `SHORTAGE_BLOCKED` jobs; all other states give `ERR_INVALID_STATE` — `routes/orders.py:191-199`
- §3.5 — revise — ambiguity — queue score's days-until-promised is signed (past-due dates score negative); queue is rescored on allocation and substitution approval as well as submission/completion — `services/core.py:134-156`, `routes/build.py:137,308`
- §3.5 — revise — mismatch — allocation shortfall does not reject with `ERR_INSUFFICIENT_COMPONENT_STOCK`; it triggers the §3.6 shortage cascade and returns 200 with the `SHORTAGE_BLOCKED` job — `routes/build.py:127-130`
- §3.5 — insert — ambiguity — job completion marks its order line `FULFILLED`; serials are `SN-` + 8-digit global counter; asset tags use a 6-digit global counter, bare (no prefix/dash) for template-less configs; `image_applied_ref` = template `pinned_image_ref` else program `custom_image_ref` else null — `routes/build.py:178-205`
- §3.6 — insert — ambiguity — approve requires request `PENDING` (else `ERR_INVALID_STATE`); approval clears the job's `shortage_component_id` to null — `routes/build.py:276-277,295`
- §3.6 — insert — ambiguity — reject requires request `PENDING` (else `ERR_INVALID_STATE`) — `routes/build.py:317-318`
- §3.6 — revise — ambiguity — the PENDING→SUPERSEDED auto-supersede fires only when a newer request is auto-created by a re-entering shortage allocation — `routes/build.py:97-100`
- §3.7 — revise — mismatch — wave quantity rule is incremental: a new wave is rejected only when cumulative live destination units would exceed drop-ship line totals (equality-only-at-end would break staged planning) — `routes/waves.py:53-68`
- §3.7 — revise — ambiguity — shipping moves every `STAGED` asset of the order's lines to `IN_TRANSIT`, stamping destination refs in asset-creation order until the wave's units are exhausted; final-wave order advance is `STAGED` (or `PARTIALLY_SHIPPED`) → `SHIPPED` — `routes/waves.py:147-200`
- §3.7 — revise — ambiguity — receipt settles only when no other wave is `RELEASED`/`SHIPPED` and order `ship_status` is in `STAGED`/`PARTIALLY_SHIPPED`/`SHIPPED`, so the receivable settles exactly once — `routes/waves.py:219-228`
- §3.8 — insert — ambiguity — parts-stocking reservability (unknown component or available stock < 1 → `ERR_PARTS_STOCKING_REQUIRED`) applies to any tier/chassis when stocking is requested; overlap "duplicate" includes identical windows — `routes/services_api.py:36-61`
- §3.9 — insert — ambiguity — recovery creation has no per-asset history check; a `DELIVERED` asset can be re-requested after a cancelled request — `routes/services_api.py:147-170`
- §3.9 — revise — ambiguity — issue-label/receive state violations surface `ERR_INVALID_STATE` (409); credit basis is the pre-discount configuration unit price; grade is exactly `poor`/`fair`/`good`; credit/recycle require matching `program_kind` else `ERR_INVALID_STATE` — `routes/services_api.py:205-280`
- §4 — insert — ambiguity — noted `ERR_INSUFFICIENT_COMPONENT_STOCK` is catalogued but unreachable because allocation shortfalls cascade instead of rejecting — `routes/build.py:127-130`

Notable verified no-changes: shortage tie-break by component `created_at` (build.py:91), OCC guards, logical-clock dual timestamp formats, per-line-round-then-sum pricing, recovery percentages, and RBAC/ownership scoping all matched PRD prose already.
