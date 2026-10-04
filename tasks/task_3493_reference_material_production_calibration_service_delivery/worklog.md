# Worklog — task_3493_reference_material_production_calibration_service_delivery

## Step 1: Create task directory — 2026-10-02T16:35:00.000Z

Task directory pre-allocated by caller: `tasks/task_3493_reference_material_production_calibration_service_delivery/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created. Difficulty instruction: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 2: Generate scaffold — 2026-10-02T18:05:00.000Z

Orchestrator verification before logging: all three files exist and parse as YAML — SCAFFOLD.yaml (1348 lines, keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles; 0 forbidden design keys), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1437 lines, single `scaffold_difficulty_design` key), SCAFFOLD_CORNER_DESIGN.yaml (2456 lines, single `scaffold_corner_design` key). Domain fidelity spot-check: api_prefix `/metrology`, domain_name `reference-material-calibration`, 71 mentions of core entities, unprefixed `POST /_clock/set_current_utc` with pinned startup default 2026-09-01T00:00:00Z present.

Subagent summary (verbatim):

All checks pass. Final summary:

### Files written

- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

### Counts

- **Entities**: 11 (ReferenceMaterialProgram, MaterialLot, ValueAssignmentMethod, CertificateOfAnalysis, Customer, SalesOrder, CalibrationServiceOffering, CalibrationOrder, TraceabilityLink, PTRound, PTParticipantResult)
- **Endpoints**: 32 (exactly at the skill's Expert upper bound; 19 mutations + 13 GETs, incl. unprefixed `POST /_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z`)
- **Error catalog**: 31 codes; **validations**: 23 ordered priority rows; **roles**: 7 (segregation-of-duties model, Customer is entity-backed); **state machines**: 7; **calculations**: 9; **OCC concurrency rules**: 2 (pricing-update on Program, certificate-create on MaterialLot)
- **§1.8**: 18 instances (9 rules × 2); **§1.9**: 58 instances (54 active + 4 `excluded_because:` stubs)
- **Lint**: `VERDICT: clean lint` — 683 calls scanned, all conform to §1.5; all 12 FKs reverse-reachable; grounds audit (calculations/entity fields/errors/transitions/validations/concurrency rules) resolves with zero bad refs; instance names unique across both design files.

### Key difficulty levers (depth, not sprawl)

- **Dual-variant calcs on two domains**: WEIGHTED_MEAN vs UNWEIGHTED_MEAN value assignment (103.2 vs 102.0 on identical methods) and ORDER_DATE vs SHIP_DATE pricing (quoted 900 vs final 1080 after a pricing-update).
- **Combinatorial formulas in different modes**: (a) PRO_RATA shortage waterfall with tier weights + floor + leftover redistribution (7-pool over 4 backorders → 4/3/1/0, releaser excluded from its own sweep); (b) pinned round-per-unit-then-multiply pricing (896×2=1792 vs forbidden 1791).
- **Non-linear machines**: lot retest cycle + homogeneity FAIL self-loop; calibration hold/resume cycle; PT evaluation→reopen cycle with fail-count compensation.
- **Transitive cascades**: PT evaluation → result FAIL → standing SUSPENDED → credit hold (depth 3); certificate expiry → lot DISTRIBUTION_HOLD → order block, and recert-publish → distribution recovery → backorder promotion (depth 3).
- **Priority-pair conflicts**: state vs business_fiscal (`ERR_LOT_NOT_DISTRIBUTABLE` beats `ERR_CREDIT_LIMIT_EXCEEDED`), business_safety vs business_temporal (traceability beats window overlap).
- **Boundary precision**: F-ratio == 3.0 passes, |z| == 2.0 passes, chi² == n−1 CONSISTENT, quantity == available exact-empty, capacity == 480 allowed, now == expiration_date expires.
- **Two interval semantics**: half-open link bookings (adjacency legal) vs aggregate daily lab capacity.

Notable design adjudications while replaying recipes: `ERR_HOMOGENEITY_NOT_ESTABLISHED` was removed because the state machine structurally shadows it (a certifiable lot always has verdict PASS); `DEPLETED` was changed from auto-trigger to a manual zero-units-gated transition so backordered orders survive stock exhaustion for later release/recert sweeps; and the endpoint budget was held at 32 by folding the uncertainty budget into certificate creation, merging PT rounds with key-comparison studies via `round_type`, and using single `transitions` endpoints with per-target actor rules.

## Step 3: Copy shared files — 2026-10-02T18:06:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T18:25:00.000Z

Orchestrator verification before logging: `workspace/PRD.md` exists (271 lines, 75 `ERR_` mentions); spot-checked clock startup default `2026-09-01T00:00:00Z` in prose, `F_CRITICAL` of 3.0 pinned in homogeneity prose, unprefixed `/_clock/set_current_utc` in the endpoint table, domain-correct introduction.

Subagent summary (verbatim):

PRD generation complete. The withheld design-index files were never opened.

**Output:** `workspace/PRD.md` — 271 lines.

**Section list:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Logical Clock and Certificate Expiration, 2.5 Resource Identity/Audit/Version, 2.6 Precision and Rounding Doctrine, 2.7 OCC on Pricing and Certification, 2.8 Validation Cascade order); §3 Business Logic (3.1 Programs/price book, 3.2 Lot production/homogeneity, 3.3 Value assignment/method adjudication, 3.4 Certificates of Analysis lifecycle, 3.5 Distribution/orders/shortage allocation, 3.6 Calibration/traceability/scheduling, 3.7 PT/KC studies/accreditation standing); §4 Endpoint Definitions (32 rows, 4 columns); §5 Error Code Catalogue (31 rows, 2 columns).

**Self-audit against the scaffold:**
- **7 state machines / 41 transitions** — all transitions rendered in prose with actors, from/to state pairs, precondition error IDs, and side effects (incl. lot cascades on publish/withdraw/expire, release-sweep exclusion of the released order, reopen compensation decrementing `pt_fail_count`, and the no-auto-deplete note).
- **9 calculations** — all formulas in precise natural language passing the reconstruction test (homogeneity F-test with `F_CRITICAL`=3.0 and ddof=1 variance, WEIGHTED/UNWEIGHTED variants, pinned u_c-rounds-before-doubling with `COVERAGE_K`=2, FIFO and PRO_RATA sweeps with tier weights 3/2/1 and leftover dealing order, ORDER_DATE vs SHIP_DATE pricing with per-unit-first rounding, expedite fee branch, z-score vs `Z_PASS_THRESHOLD`=2.0 on the rounded value, KC chi-squared vs n−1 with `MIN_KC_RESULTS`=2, standing thresholds at 2/3 fails).
- **23 validation rows** — all expressed as an explicitly ordered 23-stage cascade in §2.8 with error IDs and HTTP statuses, plus trigger conditions restated near each workflow in §3.
- **31 error codes** — all appear in §2/§3 prose; §5 table carries ID + status only.
- **2 concurrency rules** — `expected_program_version` on pricing-update and `expected_lot_version` on certificate creation, both rejected `ERR_STALE_VERSION`/412, framed purely as stale-view rejection; all other endpoints stated to take no version field.
- **Logical-clock contract** — startup default exactly `2026-09-01T00:00:00Z`, no wall-clock fallback, `to_iso8601` input, response fields `current_utc`/`expired_certificate_count`/`transitioned_lot_count`, sweep boundary (expiration at or before the new value), and the unprefixed path `/_clock/set_current_utc` in §4.

**Hard contracts:** Contract 1 — 113/113 field names present in backticks, 0 missing (PASS). Contract 2 — all categories walked; 0 missing (PASS). Contract 3 — 488 §3 backtick tokens scanned, 0 path/method violations (PASS). §2.2 verified byte-identical to the canonical block. No pseudocode operators or fuzzy quantifiers leak into prose (mechanical scan clean). Two gaps found and fixed during audit: the `COMPLETED`/`FULFILLED` state literals and the `accreditation_standing` field name.

## Step 5: Generate unit tests — 2026-10-02T18:50:00.000Z

Orchestrator verification before logging: 9 test_helpers files + conftest.py + 17 test files present; `pytest --collect-only -q test_suite/` → 90 tests collected, 0 errors. Independent AST tag audit (orchestrator-run): 90 test functions, 0 untagged, 0 dual-tagged, 0 tags to non-existent instances, difficulty covered 18/18, corner covered 54/54 — matches subagent claims exactly.

Subagent summary (verbatim):

Task complete. Summary:

### Files written

**test_helpers/** (9 files): `types.py` (status/role enums), `constants.py` (F_CRITICAL 3.0, COVERAGE_K 2, Z_PASS_THRESHOLD 2.0, PT fail thresholds 2/3, MIN_KC_RESULTS 2, tier weights 3/2/1, CLOCK_START 2026-09-01T00:00:00Z — all grep-verified verbatim against PRD.md), `api_errors.py` (31 error IDs + HTTP map registered with the framework), `api_client.py` (one method per endpoint; `/_clock/set_current_utc` deliberately **unprefixed** per PRD §2.4), `test_users.py` (shared opaque-role headers + `make_customer_headers(customer_id)` for the entity-backed Customer role; distinct met-1/met-2/co-1/co-2 ids for segregation-of-duties), `factories.py`, `assertions.py`, `fixtures.py` (composite pipelines: value-assignment lot with 2 ACCEPTED methods, lot-in-distribution, calibration scenario, PT round driver, failing-PT-round cascade, clock setter), `__init__.py` barrel.

**test_suite/** (13 files): `conftest.py` + `test_01…test_17` split by domain (programs/customers, lots/homogeneity, methods, certificates, dual-variant, sales orders, pricing, allocation boundaries/waterfall, calibration corner/cycles/capacity, PT gates/scoring/difficulty, clock+recert+listing).

### Test counts
- **Queue A (difficulty): 36 tests** — 18/18 instances covered with ≥2 tests each.
- **Queue B (corner): 54 tests** — 54/54 non-stub instances covered with ≥1 test each.
- **Skipped: none.** The 4 `excluded_because:` stubs (`uncertainty_budget_combination_literals`, `accreditation_standing_threshold_boundaries`, `release_sweep_excludes_releaser`, `dual_variant_coverage_stub`) were not translated; their difficulty-instance cross-references all resolve.

### Verification results
- `pytest --collect-only -q test_suite/`: **90 tests collected, 0 errors** (clean package graph, no dangling imports).
- AST tag audit (ast-walked docstrings vs `yaml.safe_load` indices): **90 tags found, 0 untagged, 0 dual-tagged, 0 tags pointing to non-existent instances, 72 unique instances covered (18 difficulty + 54 corner), 0 shortfalls**.
- Verbatim citation sweep: **127 PRD quote fragments checked, all survive literal grep** of PRD.md (one backtick mismatch fixed).
- Constants grep: every constant in `constants.py` matches PRD verbatim. No `skip`/`skipif`/`xfail` markers. All files byte-compile.

### Adjudication notes
- The two `priority_pair_validation_conflict` instances were kept (not skipped) because PRD §2.8 explicitly makes the cascade order authoritative ("A request that fails an earlier stage is rejected immediately…"), uniquely deriving the winner; each pair also got an isolated single-failure test as the second tag.
- FIFO tie-break under the frozen logical clock relies on insertion order (stable sort) — the natural unique reading; asserted literals match the pre-computed design values.
- `published_at`/`expiration_date` are asserted as exact clock strings (`2026-09-01T00:00:00Z` + 30 days) per the two-family timestamp rule; audit fields use `is_iso8601_timestamp` instead.
- All scheduling windows (2026-10-05+) are reachable from the 2026-09-01 logical-clock start; window-in-past test uses 2026-08-01.

## Step 6: Generate implementation — 2026-10-02T19:20:00.000Z

Orchestrator verification before logging: all 13 source files + start.sh + requirements.txt present under workspace/implementation/; `compileall` clean; resource ids use dashed `str(uuid.uuid4())` (only the opaque meta `api_request_id` uses `.hex` — acceptable); clock route registered unprefixed at `/_clock/set_current_utc`; start.sh is foreground `exec python3 app.py` with `$PORT` (default 10000), host 0.0.0.0, guarded pip install; no seeding (in-memory dict stores empty at boot).

Subagent summary (verbatim):

Done. Full implementation generated, byte-compiled, and self-smoke-tested end to end.

### Files written (all under `workspace/implementation/`)

- `start.sh` — guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, `$PORT` default 10000, `0.0.0.0`, foreground
- `requirements.txt` — flask>=3,<4
- `db.py` — in-memory dict stores (empty at boot, zero seeding), logical clock pinned at `2026-09-01T00:00:00Z`, dashed-UUID id generation, insertion sequence
- `util.py` — error catalog, envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`), auth stages 1–2, payload validators, pagination (limit 1–100 default 10, offset), both timestamp families
- `domain.py` — entity factories + serializers, `bump()` (version+1, updated_at refresh), standing thresholds (2/3), `units_available`
- `engine.py` — all 9 calculations + cascades: homogeneity (F_CRITICAL 3.0, compared on stored 6dp value), WEIGHTED/UNWEIGHTED value assignment, uncertainty budget (u_c rounded 6dp before doubling, COVERAGE_K 2), shortage sweep (FIFO created_at/quantity; PRO_RATA weights 3/2/1 with floor shares + leftover round-robin by weight DESC/created_at/quantity), ORDER_DATE/SHIP_DATE pricing (per-unit rounded before quantity), calibration fees (expedite multiplier), PT (Z_PASS 2.0 on stored 3dp z) and KC evaluation (chi² vs n−1 on stored value), reopen compensation, publish/withdraw/expire cascades
- `routes_programs.py`, `routes_lots.py`, `routes_methods.py`, `routes_certificates.py`, `routes_sales.py`, `routes_calibration.py`, `routes_pt.py`, `routes_clock.py`, `app.py`

### Verification

- `python3 -m compileall` → COMPILE_OK (re-run after edits)
- **32 routes registered** (31 under `/metrology` + unprefixed `POST /_clock/set_current_utc`)
- Smoke tests (fresh `start.sh` boots on high ephemeral ports, each killed by its exact listener PID): envelope shape + both timestamp families verified; program→lot→homogeneity (f=0.25 PASS auto-advance)→2 methods→accept→cert (weighted 10.0/0.070711, expanded 0.141422 — pinned rounding order)→publish→distribute→order (ALLOCATED, unit 900)→fulfill (subtotal 4500, fee 250, total 4750); clock sweep expired the cert at exactly `expiration_date == clock` and held the lot (`CERTIFICATE_EXPIRED`); missing headers→400, wrong role→403, stale OCC→412, bad body-ref→404 before state gates; calibration scheduling (dur 60, expedite fee 2100), overlap 409, adjacency allowed, capacity 422 (120+420>480); PT eval z=3.536 FAIL / z=0.707 PASS, close settled counters (qc 3→5, reserved→0)

### Interpretations chosen (for the fix-loop subagent)

1. **Sweep version bumps**: created order keeps version 1 (sweep outcome is its birth state); the lot bumps at order creation only if `units_reserved` changed; release/cancel bump the lot exactly once per scaffold; sweep-promoted pre-existing orders each bump (PRD §2.5 universal mutation rule); publication bumps lot version even when its state is unchanged (PRD §3.4 explicit).
2. **`the program` for calibration**: calibration orders carry no program FK; capacity/expedite config resolves to the earliest-created program; with zero programs, capacity check is skipped and expedite multiplier treated as 100.
3. **System-only transition targets** (e.g. lot `to: CERTIFIED`): not role-rejected at stage 2; fall through to stage 8 → `ERR_INVALID_STATE` 409. DEPLETED mapped to InventoryManager (state machine actor) despite the RBAC matrix listing only IN_DISTRIBUTION/WITHDRAWN for that role.
4. **Certificate creation requires `uncertainty_components`** (may be `[]`) and `expected_lot_version` — missing → 400.
5. **Uncertainty budget inputs**: combination uses the *stored* (6dp-rounded) `characterization_uncertainty` and `homogeneity_u_hom`; UNWEIGHTED `u_char` deviations use the unrounded mean; KC `chi_squared`/`d_i`/`U_i` computed from stored rounded `x_ref`/`u_ref`.
6. **Customer may pass an explicit `customer_id`** at order/calibration creation without an ownership check (PRD silent; stage 4.5 existence still enforced); InventoryManager omitting it → 400.
7. **Clock may move to any value** (no monotonicity rule stated); sweep fires on every set with inclusive `expiration_date <= clock` expiry.
8. **Pagination**: out-of-range/non-integer `limit`/`offset` → 400 (not clamped); list ties on `created_at` broken by insertion sequence; FIFO candidate order is (created_at, quantity, seq), PRO_RATA leftover cycle is (−weight, created_at, quantity, seq).
9. **Audit family** (`created_at`/`updated_at`/`api_request_timestamp`) renders from the logical clock with 3-digit millis; domain fields (`published_at`, `expiration_date`, `fulfilled_at`, `current_utc`, echoed window/date inputs) render as the clock reads (seconds + Z).
10. **Naive ISO datetimes** (no suffix) accepted as UTC; method-accept ordering is method-state → lot-state → SoD (PRD §3.3 prose order); result-filing round-state check precedes duplicate-participation; `rejection_reason` optional on REJECTED (stored null if omitted); unknown extra body fields ignored.
11. **PT z with zero reference uncertainty** (unreachable in normal flows): z=0 if diff=0 else ±999999.999 sentinel → deterministic PASS/FAIL.

## Step 7: Run tests and iterate — 2026-10-02T19:40:00.000Z

Orchestrator verification before logging: all 8 `results.${i}.json` present in workspace/implementation/, each `passed=90 total=90 failed=0`. Mtime ordering: newest impl source 19:21, newest test source (test_15_pt_scoring.py, Step 7's edit) 19:36, results files 19:39 — the clean sweep covers the current state of both trees. Evidence files left in place.

Subagent summary (verbatim):

All 8 rounds pass 90/90. Clean sweep achieved. The 8 `results.${i}.json` evidence files remain in place in `workspace/implementation/` per the output contract.

### Summary

**Iterations run:** 2 (initial sweep identified the failure; 1 fix; verification sweep clean).

**Tests deleted:** None (no whole-test deletions).

**Test assertion removed (partial-coverage split, STEP 1c):**
- `test_15_pt_scoring.py::test_kc_inconsistent_verdict_and_doe_literals` — removed the single assertion `b["equivalence_uncertainty"] == 2.683282`. **Silence/collapse pattern:** rounding-order silence breaking unique derivability. PRD §2.6 pins exactly two rounding orders ("Two rounding orders are pinned and may not be rearranged" — uncertainty budget combined→expanded; order unit pricing) and pins stored-value usage only for verdict/flag threshold comparisons; it is silent on whether the KC equivalence formula consumes the *stored rounded* `reference_uncertainty` (→ 2.683281, the implementation's behavior at `engine.py:388`) or the exact in-flight intermediate (→ 2.683282, the design index's literal in `SCAFFOLD_CORNER_DESIGN.yaml:1297`). Both readings are PRD-faithful, verified numerically with 50-digit Decimal arithmetic. All other assertions in the test (assigned_value 103.2, chi_squared 3.2, INCONSISTENT, DoE −3.2/0.8, a's equivalence_uncertainty 4.38178, both PASS flags) are numerically identical under both readings and were kept. A NOTE comment in the test records the omission rationale. The scaffold rule driving the original generation was `calculations.kc_evaluation` (`equivalence_uncertainty U_i = COVERAGE_K * sqrt(u_i^2 + u_ref^2)`), which the design index literalized without PRD pinning the input precision.

**Fixes applied to test_helpers/:** None.

**Fixes applied to test_suite/:** One — the assertion removal above (with explanatory comment).

**Fixes applied to implementation/:** None. The implementation's stored-input convention is one of the two PRD-faithful readings, and its behavior is stable: all 8 rounds were byte-identical in outcome both before the fix (89/90, same single failure every round — deterministic, not flaky) and after (90/90 × 8).

## Step 8: Finalize PRD — 2026-10-02T19:50:00.000Z

Step 8 NOT skipped: Step 7 had 1 test_suite/ fix (partial-coverage assertion removal revealing a PRD rounding-input silence). Orchestrator verification before logging: `diff PRD.md PRD_FINALIZED.md` shows exactly one in-place revision on line 192 (the reported KC equivalence_uncertainty stored-input pin); both files 271 lines.

Subagent summary (verbatim):

The diff is exactly one line. Task complete.

### Summary

**Line counts / %-delta:** `PRD.md` 271 lines, `PRD_FINALIZED.md` 271 lines — 0% line-count delta; one in-place sentence revision on line 192.

**Changes (one edit, matching the single `<step_7_diff>` item):**
- **§3.7 (KEY_COMPARISON evaluation paragraph) — revise** — the `equivalence_uncertainty` formula clause now reads "…twice the square root of the sum of its own squared uncertainty and the squared **stored, rounded `reference_uncertainty`**" (was: "the squared reference uncertainty"), pinning that the formula consumes the round's stored q6-rounded reference uncertainty rather than the exact in-flight intermediate — `implementation/engine.py:388` (`u_stored = q6(D(COVERAGE_K) * (ui ** 2 + u_ref_stored ** 2).sqrt())`, with `u_ref_stored = q6(u_ref)` at engine.py:371/379). This resolves the 2.683281 (stored-input, impl behavior) vs 2.683282 (exact-input) ambiguity behind the deleted assertion in `test_15_pt_scoring.py::test_kc_inconsistent_verdict_and_doe_literals`.

**Per-edit pre-edit search log:**
- **(a) Subject:** the input value of `reference_uncertainty` consumed by the KEY_COMPARISON `equivalence_uncertainty` formula (stored rounded vs exact in-flight).
- **(b) Impl paths enumerated:** `engine.py:365-397` (KC branch — computes exact `u_ref` at 369, stores `q6(u_ref)` at 371/379, consumes the stored value in the equivalence formula at 388, flag comparison at 392-393); `engine.py:333-364` (PT branch — `equivalence_uncertainty` set `None` at 352; PT `reference_uncertainty` copied from an already-stored certificate field at 336/338, no KC formula involved, and the edit sits inside the KC-scoped paragraph); `engine.py:400-424` (`reopen_round` clears both fields, covered by the existing reopen paragraph); `domain.py:218,237` (field init), `domain.py:406,424` (serialization passthrough via `num()`); `util.py:96-97` (`q6` = 6dp ROUND_HALF_UP, so "stored, rounded" unambiguously denotes the §2.6 storage rule). Grep confirmed no other readers of either field. Also noted the analogous stored-`assigned_value` consumption by `chi_squared` (engine.py:373) and `degree_of_equivalence` (engine.py:387).
- **(c) Wording adjustment:** chose the minimal two-word insertion ("stored, rounded" + backticked field name) scoped strictly to the `equivalence_uncertainty` clause inside the `KEY_COMPARISON` paragraph. Deliberately did **not** pin the analogous stored-input behavior of `chi_squared`/`degree_of_equivalence` (no step_7_diff item traces to them; left under-determined per the prefer-loose-wording rule), and did not touch §2.6's "Two rounding orders are pinned" count, since this is a formula-input pin, not a rounding order. All enumerated paths remain correctly described.

File produced: `workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-10-02T20:10:00.000Z

Orchestrator verification before logging: `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` → files differ (not a mid-flight no-op); 49209 → 50689 chars (+1480, matches report); 26 diff lines = 13 in-place edits. Step 9 wrote only PRD_COMPLETED.md — no implementation/ or test_suite/ writes, so the Step 7 clean-sweep evidence (results.1–8.json, all 90/90) remains valid for the current code state.

Subagent summary (verbatim):

All 13 edits landed exactly as intended; `diff -q` confirms the files differ, line count unchanged (271 → 271), 49209 → 50689 chars (+1480).

### Summary

**Output**: `workspace/PRD_COMPLETED.md`
**Source vs output**: PRD_FINALIZED.md 271 lines / 49209 chars → PRD_COMPLETED.md 271 lines / 50689 chars (+1480 chars). `diff -q`: files differ (edits verified present).

**Counts**: 13 ambiguity-pins, 0 mismatch-revisions. The exhaustive walk found no point where an unambiguous PRD sentence contradicts the code — the PRD's §2.8 cascade ordering, all 31 error IDs, every endpoint in the §4 table, both rounding orders, and all state machines match implementation/ exactly.

**Changes (all insert/revise of ambiguity, inline in existing paragraphs):**

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as taken from the logical clock — implementation/util.py:160-164
- §2.3 — insert — ambiguity — list-sort `created_at` ties broken by insertion sequence; `has_more` pinned as `offset + limit < total_count` — implementation/util.py:376-379, 177
- §2.4 — insert — ambiguity — clock-set adopts any parseable instant unconditionally (no monotonic guard); `current_utc` renders as the clock reads — implementation/routes_clock.py:19-27
- §2.5 — revise — ambiguity — `version` pinned to start at 1 — implementation/domain.py:28
- §2.5 — revise — ambiguity — `created_at`/`updated_at` pinned as sourced from the logical clock — implementation/domain.py:19-26
- §2.5 — insert — ambiguity — request-supplied datetimes (`scheduled_start`, `scheduled_end`, `calibrated_date`, `calibration_due_date`) render in the domain family: second precision on whole seconds, six fractional digits otherwise — implementation/util.py:138-144, domain.py:317,349,376-377,392-393
- §3.3 — insert — ambiguity — `rejection_reason` is optional on rejection; omission stores null — implementation/routes_methods.py:95-97,158
- §3.4 — revise — ambiguity — uncertainty budget combines the *stored, six-decimal* `characterization_uncertainty` and the lot's *stored* `homogeneity_u_hom` (raw vs rounded inputs was unpinned) — implementation/engine.py:116-120
- §3.4 — insert — ambiguity — certificate withdrawal in any lot state other than the two named leaves the lot untouched — implementation/engine.py:281-294
- §3.5 — insert — ambiguity — a `Customer` supplying `customer_id` explicitly may name any existing customer (no self-equality gate at creation) — implementation/routes_sales.py:57-68
- §3.5 — insert — ambiguity — creation-time sweep outcome is the new order's birth state (version stays 1); lot's version advances only when the sweep changed `units_reserved` — implementation/routes_sales.py:96-105, engine.py:230-242
- §3.6 — insert — ambiguity — calibration-order `customer_id` when supplied explicitly may name any existing customer — implementation/routes_calibration.py:155-160
- §3.6 — insert — ambiguity — with multiple programs, `daily_lab_capacity_minutes`/`expedite_multiplier_pct` resolve to the earliest-created program — implementation/engine.py:28-35, routes_calibration.py:266,290
- §3.7 — insert — ambiguity — zero `reference_uncertainty` degenerate guard: `z_score` 0.000 when deviation is zero, ±999999.999 otherwise — implementation/engine.py:343-348
- §3.7 — revise — ambiguity — KC `chi_squared` and `degree_of_equivalence` computed against the *stored, rounded* assigned value — implementation/engine.py:372-375,387

**IMPL BUGS FOUND: none.** Evidence from the three mandated audits:

- *Uniqueness grep*: every PRD-declared uniqueness rule is enforced — `program_code` (routes_programs.py:57-63), `service_code` (routes_calibration.py:85-91), one open (`DATA_SUBMITTED`/`ACCEPTED`) method per analyst per lot (routes_methods.py:65-75), one result per customer per round (routes_pt.py:180-186); the one-PUBLISHED-certificate-per-lot rule holds structurally via supersede-on-publish (engine.py:254-262). No prose-only unique field lacks a check.
- *Nullable-field crash-path enumeration*: all reads of PRD-nullable fields are None-safe — serializers pass None through `num()`/`render_domain` (util.py:140,149); `homogeneity_u_hom` None is guarded to 0 in the budget (engine.py:117); PT evaluation's certificate read is gated by `ERR_NO_REFERENCE_CERTIFICATE` immediately prior (routes_pt.py:126-133); z-score division-by-zero is guarded (engine.py:343); reopen reads `performance_flag` only on `EVALUATED` results, which evaluation always sets (engine.py:400-419). No legal state combination can produce a 500.
- *Dead-check audit*: all 31 catalog error IDs have live raise sites (verified per-constant); every engine/domain helper (`run_homogeneity`, `compute_certificate_numbers`, `publish_certificate`, `withdraw_certificate`, `expiration_sweep`, `evaluate_round`, `reopen_round`, `allocation_sweep`, `sweep_and_bump`, `first_program`, `unit_price_cents`, `final_fee_cents`, `recompute_standing`, `require_target_role`, …) has ≥1 call site. No defined-but-never-called or called-but-never-defined checks.
- *Over-guard sweep*: no impl check rejects a PRD-legal request; field ranges match §2.8 stage 3's enumeration exactly (no extra minimums on price/fee/capacity fields), method-adjudication SoD is scoped to the method's own analyst per §3.3 (not widened), and publish SoD covers only `ACCEPTED` methods' analysts per §3.4.
