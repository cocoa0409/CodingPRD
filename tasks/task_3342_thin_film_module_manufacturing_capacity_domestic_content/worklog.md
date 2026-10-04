# Worklog — task_3342_thin_film_module_manufacturing_capacity_domestic_content

## Step 1: Create task directory — 2026-09-30T22:00:00.000Z

Pre-allocated directory `./tasks/task_3342_thin_film_module_manufacturing_capacity_domestic_content/` confirmed present with `workspace/` inside. No new index computed, no other task directory created.

## Step 2: Generate scaffold (attempt 1) — 2026-09-30T22:00:00.000Z

ABORTED — host killed all background processes under memory pressure mid-flight; subagent left zero output files (verified 2026-10-01: directory contains only worklog.md). Redoing Step 2 from scratch.

## Step 2: Generate scaffold (attempt 2, verified post-interrupt) — 2026-10-01T05:27:45.000Z

The Step 2 subagent's process was killed by host memory pressure after its file writes completed but before its summary was returned. Orchestrator verified the artifacts on disk directly (per memory: a lost subagent report does not imply a lost artifact):

- SCAFFOLD.yaml — 1318 lines, valid YAML. Top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Counts: 10 entities, 7 state machines, 9 calculations, 17 validations, 50 endpoints, 21 errors, 8 roles.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1282 lines, valid YAML, single top-level key scaffold_difficulty_design (list).
- SCAFFOLD_CORNER_DESIGN.yaml — 1577 lines, valid YAML, single top-level key scaffold_corner_design (list).

NOTE: endpoint count is 50, above the ≤40 overshoot guard; risk of Step 6 degradation is noted — orchestrator will verify implementation files on disk after Step 6 rather than trusting its report.

## Step 3: Copy shared files — 2026-10-01T05:27:45.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-01T05:33:53.000Z

All three contracts pass mechanically. Done.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3342_thin_film_module_manufacturing_capacity_domestic_content/workspace/PRD.md` — 273 lines (verified on disk: 272 lines, complete head+tail).

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 Roles & RBAC (all 8 roles, `identity:` prose for each), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties & Logical Clock (incl. startup default `2026-09-01T00:00:00Z` and `to_iso8601`), 2.5 Validation Order & Resource Resolution (priority order + per-endpoint ordering for the two multi-validation endpoints), 2.6 OCC on Capacity Booking (`expected_line_version` / `ERR_STALE_VERSION` 412), 2.7 Capacity Buckets & Derived Line Aggregates, 2.8 Precision & Rounding (2dp money / 4dp rates, half-up)
- §3 Business Logic (9 subsections): 3.1 Customers & Module Series, 3.2 Production Lines & Ramp Lifecycle (incl. quarter-close, re-ramp, suspend/resume cascade, decommission gate), 3.3 Production Runs & dual-variant Bin Energy Model, 3.4 Capacity Reservations (OCC create, tiered deposits, activation, close-out sweep, forfeiture waterfall), 3.5 Component Lots & Traceability Cascade, 3.6 Delivery Scheduling/Confirmation (dual state dimensions), 3.7 Attestations & Domestic-Content Qualification (printed/adjusted/manufactured-products, pinned order, forked adjudication), 3.8 Warranty Claims (pinned rounding, 10% line cap), 3.9 Recycling Obligations
- §4 Endpoint table (51 rows — 4 columns only)
- §5 Error catalogue (21 rows — 2 columns only)

**Coverage audit (which scaffold sections were rendered):**
- §1.0 response envelope → §2.2 verbatim + §2.3
- §1.1 all 10 entities, all fields → narrative (field-coverage check: 69 required, 69 present, 0 missing)
- §1.2 all 7 state machines, every transition/precondition/side-effect → §3.2–3.9 (all state enum values verified present)
- §1.2.1 OCC rule → §2.6
- §1.3 all 9 calculations → §2.7/§3 (ramp curve, dual-variant energy, dual-variant content %, deposit tiers, forfeiture waterfall with pinned order, liquidated amount with pinned rounding, warranty cap, half-open window overlap, recovery %)
- §1.4 all 17 validations with priority order → §2.5 + per-endpoint prose in §3
- §1.5 all 51 endpoints → §4 table; side effects in §3
- §1.6 all 21 errors → §5 table; every error id also mentioned in §2/§3 prose (verified: none missing)
- §1.7 all 8 roles + identity semantics → §2.1

**Hard contracts:** Contract 1 PASS (0 missing fields), Contract 2 PASS (priorities, OCC, side effects, cascades, calculations, applies_to scopes all expressed), Contract 3 PASS (384 §3 backtick tokens scanned, 0 path/method violations). One bug found and fixed during verification: the fenced JSON blocks in §2.2 unbalanced naive backtick pairing — contract checks must strip fenced code before tokenizing.

## Step 2 corrigendum: design indices are foreign-domain artifacts — 2026-10-01T05:36:05.000Z

Step 5's subagent discovered — and the orchestrator verified by grep — that SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml reference a different task's domain (`POST /module-factories/...`, Factory/ModuleTechnology/Supplier entities, ManufacturingPlanner roles, 0 occurrences of `/v1/`), while SCAFFOLD.yaml is the correct thin-film `/v1` scaffold. Root cause: the memory-pressure-killed Step 2 attempt wrote these two files from an earlier partial design pass; the re-run regenerated SCAFFOLD.yaml but its design-index writes were lost with the process, leaving stale files. SCAFFOLD.yaml is unaffected (verified correct domain). Regenerating both design indices from SCAFFOLD.yaml (Step 2-redo), then re-running Step 5.

## Step 2b (design-index regen, attempt 1) — 2026-10-01T08:26:43.000Z

INTERRUPTED — endpoint/model transition killed the subagent mid-write. It left a partial SCAFFOLD_DIFFICULTY_DESIGN.yaml (114 lines, 1 rule_id `dual_variant_calc` with 2 instances — correct domain but far short of §1.8's multi-rule coverage) and no SCAFFOLD_CORNER_DESIGN.yaml. Verified the partial file parses and has zero foreign tokens, but per spec it is incomplete → deleting and regenerating both files from scratch.

## Step 2b: Regenerate design indices (attempt 2) — 2026-10-01T09:11:53.000Z

Both design indices are generated, validated, and lint-clean. Summary:

**Files**
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1394 lines, single top-level key `scaffold_difficulty_design`
- SCAFFOLD_CORNER_DESIGN.yaml — 1776 lines, single top-level key `scaffold_corner_design`

**§1.8 (20 instances, all 9 rules, ≥2 each)** — dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c all exercised: ramp gate, warranty rounding, forfeiture order), non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2. All 9 §1.3 calculations appear in at least one `grounds` (bin_energy_wh, domestic_content_qualification, ramp_yield_rate, deposit_requirement, deposit_forfeiture, warranty_liquidated_amount, warranty_capacity_reservation, delivery_window_conflict, recovery_obligation).

**§1.9 (57 entries: 46 full + 11 `excluded_because` stubs)** — entities 9, state_machines 13, calculations 3 full + 1 stub, validations 9, endpoints 5, errors 6 stubs, rbac 5, cross_cutting_complexity_layers 1 full (OCC) + 4 stubs, consistency_model 1. All stub refs resolve to real §1.8 instance names; all 77 names unique across the union.

**Verification** — an independent audit script plus the official lint both pass: all 514 test_recipe calls resolve to §1.5 endpoints with exact method/path/role, payloads ⊆ `input:`, captures ⊆ `output:`, full `${var}` placeholder closure per instance, OCC `expected_line_version` always a captured `${var}`, zero forbidden tokens (module-factories/Factory/ManufacturingPlanner), no forbidden concurrency vocabulary, all asserted error ids exist in §1.6, all fixture timestamps ≥ the 2026-09-01T00:00:00Z clock start. `scaffold_lint.py` verdict: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." SCAFFOLD.yaml untouched.

**Notable scaffold facts encoded** (worth knowing downstream):
- Activation capacity check is self-counting per the pinned formula (`available = annual − committed − reserved`, and the activating reservation's own hold sits in `reserved`), so the aggregate-capacity instance uses 40/50 MW on a 100 MW line (activation of 60 MW would fail against itself).
- `ERR_SERIES_DISCONTINUED` is unreachable: ModuleSeries.status is `source: system` with no endpoint that sets DISCONTINUED, so no corner instance could trigger it (SCAFFOLD.yaml was not modified per instructions). `ERR_UNAUTHENTICATED` (401) has no instance because the structured call schema requires `as:` ∈ declared roles; all other 19 errors are triggered.
- The nominal energy-model endpoint exposes only the nominal variant, so the dual-variant energy instance asserts invariance (energy-model value unchanged by a realized run with run_yield_rate 0.8000) rather than an ambiguous per-kW literal.

**Orchestrator spot-check (post-exit):** both files parse as valid YAML; §1.8 has 9 rule_ids / 20 instances matching the report; §1.9 has 9 sections / 57 instances (46 full, 11 stubs) matching the report; zero foreign-domain tokens; all "unmatched" static call prefixes in a naive grep were placeholder-suffixed or query-string paths that the subagent's audit verified resolve to §1.5 endpoints.

## Step 5: Generate unit tests — 2026-10-01T09:53:52.000Z

Test generation complete for task_3342. Summary:

**Counts**
- Queue A (difficulty): 20 instances → 40 tests (≥2 each, audit-verified)
- Queue B (corner): 57 instances total = 46 non-stub → 46 tests (1 each) + 11 `excluded_because:` stubs skipped (all stub cross-references resolve to real queue-A instances)
- **Total: 86 tests**, all collected cleanly by pytest (`--collect-only` passes, no import errors)

**Skipped instances** — all 11 are `excluded_because:` stubs (not translated per spec): 6 error-triggerability stubs, 4 complexity-layer stubs, 1 `mpp_input_set_excludes_unverified_lots` (owned by `printed_vs_adjusted_content_pct`). No instance was dropped for PRD-coverage failure.

**Audits passed**
- Every test docstring ends with exactly one verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` tag resolving to a real instance; no phantom or double tags.
- Every docstring's quoted PRD span survives a whitespace-normalized literal match against PRD.md (5 initial mismatches fixed: 4 fused table-row citations, 1 truncated sentence).
- No skip/skipif/xfail markers; no "scaffold" mentions; `workspace/implementation/` never read.

**PRD-adjudication decisions worth noting**
1. `deposit_exact_minimum_boundary` (queue A): the recipe's below-minimum leg (create R2 at 299999.99, then fail at post-deposit) is unreachable — PRD §3.4 states "The same minimum is enforced at booking and again when the deposit is posted", so a faithful implementation rejects R2 at create. Test 2 asserts the booking-time rejection via `validate_error_is_one_of([ERR_DEPOSIT_INSUFFICIENT, ERR_INVALID_REQUEST])` because PRD pins the rejection but not its error_id; the exact-minimum-passes leg is asserted as written.
2. `bin_energy_nominal_ignores_realized_yield`: the recipe's `variant == "nominal"` sub-assertion was dropped — PRD names "a `variant` marker" without pinning its literal value (fails the two-reader test). The load-bearing claims (nominal read invariant to realized runs, run_yield_rate == 0.8000 at 4dp) are asserted.
3. `customer_create_success_system_fields`: asserts `version` presence/type but not `== 1` — PRD §2.4 pins increment-by-1 but not the initial value.

**Files written**
- `test_helpers/`: types.py, api_client.py (54 endpoint methods), api_errors.py (21 errors registered with framework), assertions.py, factories.py, constants.py, test_users.py (with `make_customer_admin_headers` for the entity-backed CustomerAdmin role), fixtures.py (composite setups incl. `create_ramping_line`, `create_promoted_line`, `setup_active_reservation`, `setup_delivered_reservation`), `__init__.py` barrel
- `test_suite/`: conftest.py + 12 domain-named test files (test_01…test_12)

**Clock/constant safety**: all fixture windows (2027-03+) and clock sets (2027-03-15, 2028-06-01) are ≥ the 2026-09-01T00:00:00Z startup default; every numeric constant asserted (tier fractions, 0.85 ramp exit, 0.40 content floors, 4.0 adjustment, 0.80/0.15 forfeiture, 1700.0/0.05 liquidation, 0.10 warranty cap, 0.90 recovery) is valued in both SCAFFOLD and PRD prose — no literalized guesses.

**Orchestrator spot-check (post-exit):** test_helpers/ has all 9 expected files; test_suite/ has conftest.py + 12 test files; exactly 86 `Design:` tags across the suite; `pytest --collect-only` collects 86 tests with no import errors.

## Step 6: Generate implementation (attempt 1) — 2026-10-01T10:11:44.000Z

INTERRUPTED — host session ended before the Step 6 subagent wrote any files. Verified on resume: workspace/implementation/ does not exist. Relaunching Step 6 from scratch. (Steps 1–5 verified intact: SCAFFOLD.yaml 1318 lines, both design indices regenerated and lint-clean, INSTRUCTION.md, PRD.md 272 lines, test_helpers/ 9 files, test_suite/ conftest + 12 files / 86 tests collected cleanly.)

## Step 6: Generate implementation (attempt 2) — 2026-10-01T10:37:56.000Z

Done. The implementation is complete and verified.

## Files written

| File | Lines |
|---|---|
| workspace/implementation/app.py | 1325 |
| workspace/implementation/start.sh | 10 |
| workspace/implementation/requirements.txt | 1 |

**start.sh confirmed**: executable, `cd`s to its own dir, guards `pip install` behind `python3 -c "import flask"` (no-op on reboots), and `exec python3 app.py` in the foreground. app.py reads `$PORT` (default 10000) and binds `0.0.0.0`. Storage is in-memory dicts only; no seeding anywhere — the store boots empty and the logical clock starts at exactly `2026-09-01T00:00:00Z`.

## Verification

A 57-check smoke run (server launched via `bash start.sh` on a saved PID, killed exactly that PID afterward) passed end-to-end: auth 401/403 ordering, ownership 403 before existence 404, OCC 412, tier-minimum deposit (incl. 422 at booking), capacity bucket movement and line version bumps, commission gating, run consistency, ramp advancement and AT_CAPACITY promotion at q>=2 with yield>=0.85, delivery window half-open overlap/touching, volume cap, confirm-window clock check, quarantine→RECALL cascade, attestation freeze (printed 0.5 / adjusted 0.5192 / manufactured 1.0 verified) and adjudication sweeps, suspend/resume CONSTRAINED compensation, warranty performance gate + liquidated amount (20000.0) + 10% line cap, recycling 0.90 requirement with exact-1.0 RECOVERED and zero-baseline OPEN→SETTLED, close-out sweep with forfeiture ($2.7M on 40/100 delivered), decommission guard, and pagination meta.

## Judgment calls on underspecified points (traceable to PRD prose)

- `warranty_reserved_mw` = sum of `contracted_mw` over ACTIVE/CONSTRAINED reservations on the line.
- Initial `qualification_tier` = `PROVISIONAL`; delivery `content_status` at schedule time: QUALIFIED+`tax_credit_flag` → `QUALIFIED_DOMESTIC`, UNQUALIFIED → `NON_QUALIFYING`, else `UNEVALUATED`.
- PRODUCT_DEFECT amount = `claimed_mw * price_usd_per_w` literally (no 1e6 factor), per PRD §3.8.
- Approving a non-payable performance claim (measured >= guaranteed) → 400 `ERR_INVALID_REQUEST` (no error id is pinned for it).
- `close_quarter`: +1 line version per RAMPING line per close; empty quarter leaves `actual_yield_rate` null but still advances the index.
- One additive route beyond the 50-endpoint table: `GET /v1/component-lots/{id}` (RBAC grants "GET on lots" but the table defines no lot read; additive only).

**Orchestrator spot-check (post-exit):** all 3 files exist with claimed line counts; `python3 -m py_compile app.py` passes; start.sh is foreground exec with guarded pip install; app.py binds 0.0.0.0 on $PORT; 51 `@app.route` decorators (50 spec + 1 additive lot read).

## Step 7: Run tests and iterate — 2026-10-01T10:56:54.000Z

Clean 8-round sweep achieved — 86/86 passing in every round, all `results.*.json` files retained in `workspace/implementation/` (orchestrator-verified post-exit: 8 files, each passed=86 total=86 failed=0 errors=0).

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each) — initial sweep, post-implementation-fix sweep (surfaced one bad assertion in my own test fix), post-assertion-fix sweep (clean).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_activation_capacity.py` — `test_activate_exactly_at_available_passes` (`TestLineCapacityAggregateBooking`): the fixture numbers encoded a self-excluding capacity reading that contradicts the sibling rejection test and PRD §2.7/§3.4 (its comment computed `available == 100 - 40 - 50 == 10` while omitting the activated reservation r3's own 10 MW from the reserved bucket; under the §2.7 field definition available was actually 0, so PRD requires rejection, not the asserted success). Changed r2 from 50 MW/deposit 625000 to 40 MW/deposit 500000 so the pre-activation available (`100 − 40 committed − 50 reserved`, r3's own hold included) is exactly r3's 10 MW — the boundary-inclusive leg the test was designed to pin — and corrected post-activation assertions to `reserved 40.0` / `available 10.0` (the reserved→committed move leaves `available` invariant).

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` — `activate_reservation()`: the capacity check subtracted the reservation's own `contracted_mw` from the reserved bucket (`annual − committed − (reserved − own)`), a self-excluding reading. PRD §3.4 pins the precondition on "the line's `available_capacity_mw`", the §2.7 field defined as nameplate − committed − reserved with the DEPOSIT_HELD reservation itself counted in reserved, evaluated pre-transition. Removed the `- D(res["contracted_mw"])` self-exclusion so the check uses the §2.7 field directly. This fixed `test_activate_beyond_available_rejected` (r1 ACTIVE 40 + r2 DEPOSIT_HELD 50 on a 100 MW line → available 10 < 50 → `ERR_CAPACITY_UNAVAILABLE` 422, reservation stays DEPOSIT_HELD, buckets unchanged).

**Root-cause note:** the two `TestLineCapacityAggregateBooking` siblings were generated with mutually inconsistent derivations of the same PRD rule — the rejection test used include-own arithmetic, the boundary test used exclude-own arithmetic. The implementation happened to match the latter, so only one failed per reading. PRD §2.7 + §3.4 uniquely determine the include-own reading (the named field's formula and pre-transition evaluation order), so the implementation was corrected to it and the boundary test's fixture numbers were repaired to genuinely hit the inclusive boundary.

## Step 8: Finalize PRD — 2026-10-01T11:06:57.000Z

Done. Summary:

**PRD.md vs PRD_FINALIZED.md:** 272 lines → 272 lines (0.0% line-count delta; one sentence inserted inline within the §3.4 activation paragraph). Produced at workspace/PRD_FINALIZED.md.

**Changes (one total):**
- §3.4 (Capacity Reservations: Booking, Deposits, Activation, Close-Out) — insert — added one sentence pinning the activation capacity precondition's evaluation basis: it is read on the pre-transition line with `available_capacity_mw` taken exactly as §2.7 defines it, so the `DEPOSIT_HELD` reservation being activated still counts toward `reserved_capacity_mw` (its own `contracted_mw` is not subtracted from the reserved bucket for this check) — `implementation/app.py:684-692` (the Step-7-fixed `activate_reservation`).

**Disposition of the step_7_diff items:**
- The `test_suite/test_06_activation_capacity.py` fixture repair is a pure test-side bug fix; it pins no behavior beyond the include-own reading, which the single edit above covers. No separate edit.
- The `app.py` `activate_reservation` fix is the one edit above. Note on the zero-edit option: my strict textual trace agrees with Step 7 that §2.7+§3.4 *formally* determine the include-own reading (field reference → §2.7 formula → preconditions evaluated before the "On activation" side effects). I nonetheless made the scoped insertion because the site sentence's evaluation basis requires a two-hop cross-reference and this task's own record shows it was misread twice (original impl-gen wrote the exclude-own check; one sibling test derived exclude-own arithmetic) — a demonstrated, site-local under-determination for PRD_FINALIZED's fresh-implementer equivalence goal. A byte-identical copy was the alternative and would have been defensible; I judged the pin lower-risk for the benchmark's stated purpose.

**Per-edit pre-edit search log (edit 1 of 1):**
- (a) Subject: evaluation basis of the activation capacity precondition — whether the reservation being activated counts toward `reserved_capacity_mw` in the `available_capacity_mw >= contracted_mw` check.
- (b) Impl paths enumerated and read/grepped: `app.py:674-699` (`activate_reservation`, the fix site — check at line 690 precedes the status flip at 696, so the subject reservation is `DEPOSIT_HELD` and included); `app.py:215-236` (`reservations_on_line`/`line_bucket`/`line_json`, the §2.7 serialization used by every line fetch); `app.py:600-648` (`create_reservation` — verified **no** capacity check at booking, matching §3.4's booking paragraph); `app.py:702-718` (`cancel_reservation`) and `app.py:1279-1323` (`close_quarter` sweep — bucket changes via status moves only, no ad-hoc available math); `app.py:1226-1232` (warranty cap, separate 10%-of-nameplate formula); `app.py:249-257` and `app.py:792-794` (per-reservation forfeiture and delivery-volume `contracted_mw` math, unrelated); grep-verified lines 687-692 are the only inline `available` computation and only `ERR_CAPACITY_UNAVAILABLE` site; also verified §2.7's "committed never exceeds annual_capacity_mw" invariant is preserved under the include-own check.
- (c) Wording adjustment: scoped the inserted sentence with "The capacity precondition … for this check" and anchored it to "exactly as §2.7 defines it", so it cannot be read as adding a booking-time capacity gate, as altering cancel/sweep behavior, or as redefining the serialized field (which stays governed by §2.7 verbatim).

**Orchestrator spot-check (post-exit):** `diff PRD.md PRD_FINALIZED.md` shows exactly the one reported sentence insertion at §3.4 and nothing else; no implementation/*.py or *.sh file is newer than results.8.json (app.py 10:48:53 < sweep 10:55:33) — the clean sweep remains valid.

## Step 9: Complete PRD — 2026-10-01T11:28:17.000Z

Done. The patch is written and verified. Final summary:

**Source vs output:** `PRD_FINALIZED.md` (272 lines / 41,533 chars) → `workspace/PRD_COMPLETED.md` (272 lines / 45,751 chars; +4,218 chars, +1 content row / −1 trailing blank line). 27 paragraphs revised in place, 1 endpoint-table row added, no new sections.

**Counts:** 22 ambiguity-pins, 12 mismatch-revisions (34 change bullets below; some bullets bundle two co-located micro-edits).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl file:line):**
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → ERR_INVALID_REQUEST 400; created_at ties break by insertion order — app.py:179-191
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — app.py:152-156
- §2.4 — insert — ambiguity — created_at/updated_at/api_request_timestamp are wall-clock; logical clock governs business rules only — app.py:57-59,154-156
- §2.5 — revise — mismatch — ownership order: creates compare body `customer_id` before resolution; path-targeted mutations resolve target (+parent reservation) first, ownership immediately after (missing target → 404) — app.py:608-610 vs 661-663,769-770,822-824,878-880,1256-1257
- §2.5 — insert — ambiguity — missing/wrong-typed fields and uniqueness violations (series_code/line_code/lot_code) → ERR_INVALID_REQUEST 400 — app.py:131-134,362-364,420-422,909-910
- §2.7 — revise — ambiguity — `warranty_reserved_mw`: all ACTIVE/CONSTRAINED reservations qualify by construction, so it always equals `committed_capacity_mw` — app.py:233-235 (known call site)
- §3.1 — revise — mismatch — `temp_coefficient`: any number accepted (conventionally negative) — app.py:347-348
- §3.1 — revise — mismatch — bin wattage-descending ordering is conventional, not validated — app.py:349-361
- §3.2 — revise — mismatch — `site_country`: any non-empty string accepted (alpha-2 conventional) — app.py:416-417
- §3.2 — insert — ambiguity — new line's `qualification_tier` is PROVISIONAL — app.py:427 (known call site)
- §3.2 — insert — ambiguity — target-yield curve not exposed by any endpoint; promotion uses the actual-yield rule only — app.py (no surface)
- §3.2 — insert — ambiguity — every RAMPING line's version increments per close; `closed_quarter` = zero-based count of prior closes, independent of line indexes — app.py:1282,1302-1306,1321-1323 (known call site)
- §3.2 — insert — ambiguity — reintroduce: discontinued series → ERR_SERIES_DISCONTINUED 422; same-as-latest-run series → ERR_INVALID_REQUEST 400 — app.py:464-471
- §3.2 — revise — mismatch — suspension cascade is unconditional (every ACTIVE → CONSTRAINED; each cascaded reservation's version increments) — app.py:486-491
- §3.3 — revise — mismatch — run `series_id` need not match a line-configured series; any registered series accepted — app.py:561
- §3.3 — revise — mismatch — nominal variant: 0.001 scale applied server-side, returned as `nominal_kwh_per_kw` with `variant`="nominal"; actual-yield variant is analytic-only (no endpoint; settlement/adjudication use §3.6 accumulation and §3.8 fixed guarantee) — app.py:260-263,385-386
- §3.4 — insert — ambiguity — booking validation order: schema 400s → OCC 412 → series-discontinued 422 → deposit minimum 422; `deposit_usd` ≥ 0 — app.py:614-645
- §3.4 — revise — ambiguity — below-minimum deposit at booking → ERR_DEPOSIT_INSUFFICIENT 422 (both steps) — app.py:643-645,666-668
- §3.4 — insert — ambiguity — activation with line not RAMPING/AT_CAPACITY → ERR_INVALID_STATE 409 — app.py:681-683
- §3.5 — revise — mismatch — `country_of_origin`: any non-empty string — app.py:905-906
- §3.5 + §4 — insert — ambiguity — additive `GET /v1/component-lots/{id}`, readable by all eight roles — app.py:921-926 (known call site)
- §3.6 — insert — ambiguity — malformed window (end not strictly after start) → ERR_WINDOW_OVERLAP 409, same as overlap — app.py:782-784,832-834
- §3.6 — revise — ambiguity — initial `content_status` pinned: QUALIFIED+tax_credit_flag → QUALIFIED_DOMESTIC; UNQUALIFIED → NON_QUALIFYING; else UNEVALUATED — app.py:741-747,806 (known call site)
- §3.6 — revise — mismatch — dropped "delivered batch feeds the actual-yield energy settlement" (confirmation only grows `delivered_mw`) — app.py:867-870
- §3.7 — revise — mismatch — "Once per period…seven cost figures" → no line-period uniqueness enforced; six cost figures; `period_year` integer — app.py:966-985
- §3.7 — revise — mismatch — `manufactured_products_pct` aggregates all registered VERIFIED lots (no period filter) — app.py:1016-1021
- §3.7 — insert — ambiguity — zero denominators: manufactured/printed = 0.0000; adjusted denominator always positive — app.py:1022-1026
- §3.8 — revise — ambiguity — review gate rejects reservations in PENDING/DEPOSIT_HELD/CANCELLED alike with ERR_CLAIM_ON_CANCELLED — app.py:1184-1186
- §3.8 — insert — ambiguity — approving a non-payable PERFORMANCE_SHORTFALL → ERR_INVALID_REQUEST 400 — app.py:1222-1224 (known call site)
- §3.8 — revise — mismatch — dropped "Approval recomputes the line's warranty_reserved_mw"; approval changes no line aggregate and does not bump line version — app.py:1228-1237
- §3.9 — insert — ambiguity — initial `fulfillment_pct` 0.0000 (1.0000 for zero baseline); `period_year` integer — app.py:1096-1099
- §3.9 — insert — ambiguity — collection volume must be > 0 (else 400); recording responds HTTP 201 with the updated obligation; collections only from OPEN/COLLECTING (else ERR_INVALID_STATE 409) — app.py:1108-1121
- §3.9 — insert — ambiguity — settling an already-SETTLED obligation → ERR_INVALID_STATE 409 — app.py:1135-1136

**Known judgment-call sites:** all seven confirmed against prose or pinned (warranty_reserved_mw, initial PROVISIONAL tier, schedule-time content_status, PRODUCT_DEFECT literal amount — already pinned in FINALIZED §3.8 and matches app.py:1227, non-payable approval → 400, close_quarter version/empty-quarter semantics, additive component-lot GET).

**Dead-code check:** clean. All 25 helpers in app.py have ≥1 real callsite (verified by grep). No PRD-required validation is defined-but-never-called. The reverse-direction overclaims (PRD prose with no impl surface — run series↔line match, actual-yield energy variant, target-yield curve exposure) were prose defects, not definable missing checks, and were resolved as PRD revisions listed above; none is an implementation bug.

**Orchestrator spot-check (post-exit):** `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (not a silent no-op); char counts match the report exactly (41,533 → 45,751, +4,218). No implementation *.py or *.sh file is newer than the final sweep's results files — the clean 8-round sweep remains valid.
