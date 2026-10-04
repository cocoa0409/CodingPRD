# Worklog — task_3439_carpet_tile_take_back_program_product_carbon

## Step 1: Create task directory — 2026-10-02T02:53:49.392929967Z

Pre-allocated directory ./tasks/task_3439_carpet_tile_take_back_program_product_carbon/ verified; workspace/ exists. No index computed (explicitly pre-allocated).

## Step 2: Generate scaffold — 2026-10-02T04:22:13.52146597Z

All checks green. The three artifacts are complete, lint-clean, and self-audited.

## Summary

**Task**: `task_3439_carpet_tile_take_back_program_product_carbon` — Carpet Tile Take-Back Program & Product Carbon Accounting, generated deliberately above Expert band per instruction.

**(a) Output files (line counts)**
- `/home/ubuntu/github/CodingPRD/tasks/task_3439_carpet_tile_take_back_program_product_carbon/SCAFFOLD.yaml` — 1097 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3439_carpet_tile_take_back_program_product_carbon/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1411 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3439_carpet_tile_take_back_program_product_carbon/SCAFFOLD_CORNER_DESIGN.yaml` — 2280 lines

**(b) Counts**: 12 entities / 10 state machines (+3 OCC concurrency rules) / 10 calculations / 12 ordered validation priorities / 55 endpoints / 46 errors / 6 roles (all `opaque`, SoD-modeled) / §1.8: 19 difficulty instances (all 9 rules ≥2; rule 2 has 3, one per mode a/b/c) / §1.9: 66 corner instances (55 active + 11 `excluded_because` stubs) across all 9 taxonomy sections. 982 recipe calls total.

**(c) Validity**: all three files parse as YAML; `SCAFFOLD.yaml` contains neither design key; the two design files each carry exactly their single required top-level key. `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Additional self-audits passed: zero unbound `${var}` placeholders, zero forbidden concurrency vocabulary, all 46 error ids have trigger venues, all `grounds:` resolve, cross-file instance names unique, all numeric asserts pre-computed with Decimal half-up math (e.g., PCF variants 5.950/6.090, credit variants 6000/8400, rounding-order pins 5.501-vs-5.500 and 6011-vs-6010, offset requirement 6590.0 with inclusive FULL boundary).

**(d) api_prefix**: `/carpetloop`; the logical clock endpoint lives outside it at `POST /_clock/set_current_utc` with the mandatory default `2026-09-01T00:00:00Z`.

**(e) Notable design decisions / ambiguities resolved**
- **Entity consolidation to stay implementable**: contractors and specifier firms are strings + cert snapshots on `CustomerSite` (ownership via `contractor_name == X-User-ID` / `created_by`) rather than account entities; verification engagements folded into `PCFReport` (`verification` action endpoint with ASSIGN/CLEAR/FAIL); sort records folded into `TakeBackRequest` (`/sort`). 55 endpoints exceeds the >40 impl-gen risk band in memory — the Step 6 prompt should pre-constrain (one file per message, per-domain modules, self-smoke-test).
- **Carbon-negative claims** require `boundary == CRADLE_TO_GRAVE` + a manufacturing target (new error `ERR_NEGATIVE_REQUIRES_CRADLE_TO_GRAVE`); two difficulty fixtures were re-derived to GRAVE chains to stay consistent.
- **Report-period rule** deliberately splits semantics: create-time overlap rejects only the in-verification pipeline (SUBMITTED/IN_VERIFICATION/VERIFIED), DRAFTs are superseded at create (OCC-guarded), PUBLISHED are superseded at publish — otherwise cascade A (publish → supersede → retire → revoke, depth 3) would be unreachable. Caught in end-state replay.
- **Rule 8** uses two genuinely different interval semantics: contractor install windows (closed intervals + 86400 s clear buffer, candidate set = INSTALLED|IN_SERVICE same-contractor sites) vs report periods (half-open, touching allowed) on the collection calendar.
- **Dual-variant calculations** sit in different entity domains: carbon (PCF operational vs lifecycle, divergence = transport + recovery-scaled end-of-life credit) and fiscal (take-back credit STANDARD vs CIRCULAR selected by `claim_intent`).
- **OCC ×3** all create-with-supersede: reports and packages on `ProductCollection.version`, replacement orders on `CustomerSite.version`; all version inputs in recipes are `${var}`-captured per lint rule (e).
- Process notes: two YAML flow-context pitfalls fixed mid-build (unquoted `${var}` and `$.data[0].x` inside flow mappings), caught by parse-after-every-append; the lint's sub-resource FK check requires the literal `{id}` placeholder, so the offsets sub-resource path uses it.

Orchestrator verification: files exist with claimed line counts; all three parse as YAML; SCAFFOLD.yaml top-level keys confirmed (no design keys); 114 hits for /carpetloop, 2 for _clock, 179 for domain terms — genuine task domain content.

## Step 3: Copy shared files — 2026-10-02T04:22:21.646803600Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-02T04:43:06.174431185Z

All audits pass. Sanity check against the ask: I read the skill and SCAFFOLD.yaml only (never opened SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml), wrote the PRD in sequential passes with no truncation, and verified coverage programmatically.

result: PRD generated at /home/ubuntu/github/CodingPRD/tasks/task_3439_carpet_tile_take_back_program_product_carbon/workspace/PRD.md (345 lines), all three hard contracts PASS.

**(a) Output** — `/home/ubuntu/github/CodingPRD/tasks/task_3439_carpet_tile_take_back_program_product_carbon/workspace/PRD.md`, 345 lines.

**(b) Section outline**
- §1 Introduction (2 paragraphs: program context, system goals)
- §2 Global Specifications: 2.1 RBAC (6 roles, opaque identity, action-split verification), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning (OffsetRetirement exception), 2.5 Logical Clock & Reporting-Period Semantics, 2.6 Units/Precision/Rounding, 2.7 OCC on Create-with-Supersede (3 rules), 2.8 Validation Pipeline & Error Precedence (12 priorities, first-failure-wins), 2.9 Cascades & Automatic State Reconciliation (A/B/C + decommission + auto transitions), 2.10 Nested Path Resolution
- §3 Business Logic: 3.1 Collections & Sunset Gate, 3.2 Feedstock Intake/QC/Batch Composition, 3.3 Sites/Installation/Zones, 3.4 Replacement Orders & Dye-Lot Matching, 3.5 Take-Back Loop & Credit, 3.6 PCF Reports & Verification, 3.7 Claims/Offsets/Targets, 3.8 Spec Packages
- §4 Endpoint table (55 rows, 4 columns) · §5 Error catalogue (46 rows, 2 columns)

**(c) Coverage audit (method: scripted YAML-vs-PRD diff)** — parsed SCAFFOLD.yaml with PyYAML, extracted fence-stripped backtick tokens from the PRD, and diffed: **Contract 1** — 101/101 required field/input/query/path-param names present, 0 missing (after repairing 5 gaps found on first pass: `action`, `order_id`, `takeback_id`, `target_id`, `package_id`). **Contract 2** — all 10 state machines' transitions/gates/side-effects, all 10 calculations (with pinned rounding orders), all 12 validation priorities with per-guard error variants, all 3 OCC rules (`expected_collection_version` ×2, `expected_site_version`, `ERR_STALE_VERSION`/412), and all endpoint side-effects expressed in prose; every one of the 46 error ids appears in §2/§3 narrative (not only §5), and §5 statuses match scaffold HTTP codes. **Contract 3** — 563 §3 backtick tokens scanned, 0 path/method violations. §2.2 verified byte-identical to the canonical block. Style scans: no fuzzy words, no operator-syntax pseudocode. All 55 method+path pairs appear in §4; all 6 role names and all enum/state values present.

**(d) Interpretations made** — (1) `TAKEBACK_LOT_CARBON_FACTOR` / `TAKEBACK_SUPPLIER_NAME` are named in the scaffold without values; projected as named program constants, no value invented. (2) `CONTRACTOR_BUFFER_SECONDS` is unpinned in the scaffold but the error catalog pins "1-day buffer"; written as one full day (86,400 seconds) at both ends. (3) Allocate/deallocate against a non-QUARANTINE batch and (4) offset retirement against a claim not `IN_REVIEW`/`APPROVED` have no dedicated error_id in the scaffold; both mapped to the generic `ERR_INVALID_STATE` (409). (5) All six roles are `identity: opaque`, so §2.1 states `X-User-ID` is never compared to entity ids but is compared to recorded `created_by`/`contractor_name` strings per validation priority 3. (6) `BONUS_CAP_FRACTION` 0.40 rendered as "forty percent of the base credit" (exact equivalence).

Orchestrator verification: PRD.md 344 lines by wc; 105 table rows; 87 ERR_ mentions; unprefixed clock endpoint + default 2026-09-01T00:00:00Z pinned (§2.5 line 89, §4 line 290); 86,400-second contractor buffer pinned (line 170); TAKEBACK_LOT_CARBON_FACTOR (2 mentions) and TAKEBACK_SUPPLIER_NAME (3 mentions) named but deliberately unvalued — drift risk flagged for Steps 5/6 hand-off (tests must not assert unvalued constants).

## Step 5: Generate unit tests (Stage 1: helpers frozen; Stage 2: test suite) — 2026-10-02T06:06:16.469238613Z

### Stage 1 (test_helpers + conftest) — subagent summary verbatim:

All checks pass. The `TAKEBACK_LOT_CARBON_FACTOR`/`TAKEBACK_SUPPLIER_NAME` names appear only in the constants.py NOTE explaining their deliberate omission — no values invented, no assertion helper built on them.

Stage 1 is complete. Final report:

(a) File list with line counts: 48 test_helpers/__init__.py; 322 test_helpers/api_client.py; 117 test_helpers/api_errors.py; 285 test_helpers/assertions.py; 52 test_helpers/constants.py; 271 test_helpers/factories.py; 581 test_helpers/fixtures.py; 78 test_helpers/test_users.py; 382 test_helpers/types.py; 56 test_suite/conftest.py — 2192 total. No test_*.py written.

(b) Helper API surface (signatures): api_client.py — `ApiClient(GenericApiClient)`; module singleton `api_client`. 56 methods covering every PRD §4 row: `set_clock(current_utc, headers)` (UNPREFIXED `/_clock/set_current_utc`); per entity `create_*`/`get_*`/`list_*(headers, params=None)`; actions `sunset_collection`, `release_batch`, `qc_feedstock_lot(lot_id, payload, headers)`, `allocate_feedstock`, `deallocate_feedstock`, `install_site`, `decommission_site`, `create_zone(site_id, payload, headers)`, `match/complete/cancel_replacement_order`, `schedule/collect/cancel/sort_takeback`, `submit/revise/verify/publish_pcf_report`, `submit/review/publish_carbon_claim`, `create/list_offset_retirements(claim_id, ...)`, `create_manufacturing_target`, `create_target_reading`, `create/get/list_spec_package`. All return raw `Response`. test_users.py — `TEST_USERS` (admin/manager/verifier/approver/specifier/installer headers; canonical ids `pa-admin`, `sm-carol`, `ver-dana`, `ap-erin`, `spec-ada`, `inst-bob`); `ALT_SPECIFIER_ID = "spec-eve"`; per-instance builders `make_{admin,manager,verifier,approver,specifier,installer}_headers(user_id)`. factories.py — `create_{collection,batch,feedstock_lot,virgin_lot,site,takeback_request,carbon_claim,manufacturing_target,offset,reading,review,qc,schedule,collect,sort,verification}_payload(...)`; FK/OCC-mandatory fields positional: `create_zone_payload(batch_id,...)`, `create_replacement_order_payload(site_id, zone_id, expected_site_version,...)`, `create_takeback_request_payload(site_id, collection_id,...)`, `create_pcf_report_payload(collection_id, expected_collection_version,...)`, `create_carbon_claim_payload(collection_id, report_id,...)`, `create_allocate_payload(batch_id, quantity_kg,...)`, `create_spec_package_payload(collection_id, report_id, expected_collection_version,...)`; plus `required_batch_mix_kg(produced_m2)`. fixtures.py — `_ok(resp, ctx)` ("Setup failed" wrapper over `get_success_data`); `set_clock(utc)`; `get_collection/site`, `get_collection_version/get_site_version` (OCC capture); `create_collection`, `sunset_collection`; `create_lot`, `qc_lot`, `create_qc_passed_lot`, `create_qc_failed_lot`, `allocate_to_batch`, `deallocate_from_batch`, `find_lots_by_origin_takeback`; `create_batch`, `release_batch`, `create_released_batch(collection_id, mix=None, **batch_overrides)` (local mass-balance guard: mix must sum to `produced_m2 × 4.0`), `setup_collection_with_batch`; `create_site(specifier_id=...)`, `install_site(site)` (threads `site["contractor_name"]`), `create_installed_site`, `lay_zone(site, batch_id, ...)`, `setup_site_with_zone(...)`; take-backs: `create_takeback(site, collection_id)` (defaults caller to `site["created_by"]`), `schedule/collect/sort/cancel_takeback`, `setup_collected_takeback`, `setup_credited_takeback`; orders: `create_order(site, zone)` (auto fresh site version), `match/complete/cancel_order`, `setup_matched_order`; reports: `create_report` (auto fresh collection version), `submit/revise/assign/clear/fail/publish_report`, `setup_published_report`; claims: `create_claim`, `submit/review/publish_claim`, `retire_offset`, `setup_claim_in_review`, `setup_published_claim` (retires exact requirement); `create_target`, `post_reading`; `issue_package` (auto fresh collection version). assertions.py — `validate_created(resp)` (= `validate_success(resp, 201)`); `assert_{collection,batch,feedstock_lot,site,zone,replacement_order,takeback_request,pcf_report,carbon_claim,offset_retirement,manufacturing_target,spec_package}(data)`; `assert_lot_mass_conserved(lot)`. `assert_offset_retirement` pins PRD §2.4's absence of `updated_at`/`version`. api_errors.py — `ApiErrorId` (46 ids), `HTTP_STATUS_CODES`, registered via `set_error_http_status_map` at import. conftest.py — session `api`; function-scoped `admin/manager/verifier/approver/specifier/installer_headers`.

(c) Verification output (verbatim): `python3 -m compileall -q test_helpers test_suite && echo "COMPILE_OK" && PYTHONPATH=. python3 -c "import test_helpers, test_suite.conftest; print('IMPORT_OK')"` → COMPILE_OK / IMPORT_OK. helpers error ids: 46; PRD §5 error ids: 46; in helpers but NOT in PRD: none; in PRD but NOT in helpers: none; status mismatches: none. Path audit: 54 `{PREFIX}`-carrying business usages + exactly one unprefixed literal `"/_clock/set_current_utc"`. Style audit: `grep -rin "scaffold..."` → `NO_SCAFFOLD_REFS`. No server started, no pytest run.

(d) PRD-vs-design-index inconsistencies found and resolutions:
1. Unvalued cascade constants asserted literally in a corner instance. Corner `endpoints/lots_traceability_filter_finds_cascade_created_lot` asserts the sort-cascade lot has `supplier_name == "TAKEBACK-PROGRAM"` and `carbon_factor_kgco2e_per_kg == 0.40`. PRD §2.9 cascade C names `TAKEBACK_SUPPLIER_NAME`/`TAKEBACK_LOT_CARBON_FACTOR` but never values them — a PRD-only implementer cannot derive those literals, so they fail the two-reader rule. Resolution (Stage 1): both constants omitted from constants.py, no assertion helper references them; factories take supplier/factor only as explicit test inputs. Flag for Stage 2: assert only the PRD-derivable fields of that recipe (`quantity_kg`, `POST_CONSUMER_TILE`, `RECEIVED`, `origin_takeback_id` linkage); drop the two literal supplier/factor asserts. Same caution applies to the parenthetical "(TAKEBACK_LOT_CARBON_FACTOR)" mention in `combinatorial_formula/credit_pathway_bonus_cap_binds`.
2. No list endpoints for sites or manufacturing targets. Both SCAFFOLD §1.5 and PRD §4 agree (single-GET only), so the client deliberately omits `list_sites`/`list_manufacturing_targets` — noting it so Stage 2 doesn't invent them.
3. `GET /carpetloop/sites/{site_id}` absent from §1.1-style "listable" corner recipes but present in PRD §4 — client includes it (used by every OCC order recipe to re-capture `expected_site_version`); consistent across all four inputs.

Everything else cross-checked clean: 201-vs-200 per endpoint verified against PRD §4's creation/action split, half-open vs closed interval semantics noted in factory/fixture docstrings, and OCC version fields are mandatory positional parameters in factories with auto-fresh-read fixtures behind them.

### Stage 2 (test_suite) — subagent summary verbatim:

All checks pass. Final report follows.

(a) Test files (all under test_suite/): test_01_collections_and_batches.py 235 lines 7 tests; test_02_feedstock_lots.py 257/8; test_03_sites_and_zones.py 415/12; test_04_replacement_orders.py 440/11; test_05_takeback_credit.py 364/11; test_06_pcf_reports.py 450/12; test_07_claims_offsets_targets.py 552/15; test_08_spec_packages.py 250/6; test_09_rbac_and_auth.py 271/8; test_10_read_models_and_errors.py 236/4. Total: 94 tests (queue A: 38; queue B: 56). No skip/xfail markers, no placeholders, no TODOs.

(c) Verbatim tag-audit output: tests collected by AST walk: 94; queue A emitted: 19/19 instances (38 tests); queue B emitted: 55/55 active instances (56 tests); queue B stubs (not translated): 11; orphan/misspelled tags: 0; stub tags wrongly emitted: 0; tag-count/shape problems: 0; queue A instances with <2 tests: {}; queue B active instances with 0 tests: {}; queue A instances with >2 tests: {}; queue B instances with >1 test: {'Corner/state_machines/report_fail_revise_resubmit_cycle': 2}; stub difficulty_instance cross-refs broken: {}; AUDIT: PASS. The one multi-test queue-B tag is intentional: the `report_fail_revise_resubmit_cycle` instance's own assert list includes the `findings_count >= 1` gate, which needs an IN_VERIFICATION report and could not ride in the cycle test without corrupting its state narrative. Independent citation pass: all 153 `PRD §…: "…"` docstring quote blocks were machine-checked as verbatim substrings of PRD.md (`ALL CITATIONS VERBATIM`). Four initial failures (a period inside a quote ×2, two non-contiguous sentences fused into one quote ×2) were fixed and re-verified.

(d) Skipped instances: None — every queue-A instance (19/19, 2 tests each) and every active queue-B instance (55/55) is translated. All 11 `excluded_because:` stubs were left untranslated, and every stub's `difficulty_instance` cross-reference resolves.

Assertion-level adjudications made inside emitted tests (instance kept, non-derivable sub-assertion dropped or corrected):
1. `Corner/endpoints/lots_traceability_filter_finds_cascade_created_lot` — per hand-off flag 1: asserts only PRD-derivable fields (exactly one lot, `quantity_kg == 80`, `POST_CONSUMER_TILE`, `RECEIVED`, `origin_takeback_id` linkage, plus `supplier_reliability_pct == 100.00`, which IS derivable: cascade C says reliability is "computed at creation exactly like any directly posted lot's" and the DB has no decided lots for the constant supplier string). The literal `TAKEBACK-PROGRAM` / `0.40` assertions were dropped — the PRD names but never values those constants.
2. `Corner/validations/decommission_blocked_by_inflight_takeback_then_succeeds` — design-index setup bug worked around: the recipe leaves the site INSTALLED, but PRD §3.3 allows decommission only from PLANNED or IN_SERVICE, so from INSTALLED the call would fail ERR_INVALID_STATE (priority 5) before the take-back guard (priority 6) could fire. The test lays one zone to reach IN_SERVICE; the asserted outcomes (ERR_TAKEBACK_IN_FLIGHT, then success after cancel) are unchanged.
3. `Difficulty/resource_temporal_overlap/contractor_install_window_buffer_semantics` — the instance's "two days out succeeds" assertion is not uniquely derivable: PRD §3.3 extends *each* closed window by one day at *both* ends, and under closed-interval intersection the recipe's S3 [10-12,10-16] touches S1's extended window at 10-11 (conflict), while the recipe's own "start > end + 86400s" reading succeeds. Emitted instead: (T1) the exactly-one-day gap conflicts — both readings agree; (T2) a three-day-gap install succeeds while overlapping a PLANNED middle site under every reading — proving both "beyond the buffer succeeds" and the INSTALLED|IN_SERVICE candidate-set restriction.
4. `Corner/entities/batch_created_quarantine_with_full_availability_and_empty_mix` — the `embodied_carbon_kg_per_m2 is null` assertion was dropped (computed-field silence: PRD never pins embodied's pre-allocation value, and the formula's empty-mix sum divided by produced_m2 could plausibly store intensity-only). The explicitly-stated `recycled_content_pct` null ("While the mix is empty … undefined (null)") is asserted.
5. `Corner/entities/site_create_missing_required_budget_returns_invalid_request` — the "GET /carpetloop/sites would be empty" assert dropped; no sites list endpoint exists (hand-off flag 2). Only the 400 is asserted.
6. Clock-stamp assertions (`created_at`, `retired_at`) use the clock instant (prefix match on `2026-09-01T00:00:00`), not literal string equality — PRD §2.4 mandates "three fractional digits", so a faithful serializer emits `.000Z`.
7. `Corner/entities/batches_list_filters_by_collection_and_paginates` — page contents asserted as sets, not row order: all batches share one logical-clock `created_at`, and PRD §2.3's created_at-ascending sort leaves same-instant tie order unspecified.

(e) Collect-only output tail: PYTEST_EXIT=0; 94 tests collected in 0.34s. Zero collection errors.

(f) Helper-layer bugs found (not fixed, per freeze): None blocking. Two informational notes for a future helper revision: (1) the frozen `fixtures.py` has no `get_batch`/`get_claim`/`get_target` read helpers — tests call `api_client.get_*` + `validate_success` directly for mid-test reads; (2) `fixtures.py` re-exports framework names (`validate_paginated`, `api_client`, `ADMIN`) through its star-import surface, which is relied upon by the suite and works, but widens the barrel beyond its documented contents.

result: Stage 2 delivered — 94 tests across 10 files, queues A 19/19 (≥2 tests each) and B 55/55 active instances, AST tag audit PASS with zero orphans/untagged/dual-tagged, all 153 PRD citations verified verbatim against PRD.md, pytest --collect-only exit 0 with zero errors.

Orchestrator verification: compileall + import OK; independent AST tag audit reproduced (94/94 tagged, 0 orphans, A=19 instances ×2 tests, B=55 instances ×1 test + the one explained 2-test corner); unprefixed clock literal present exactly once in api_client; no invented values for the two unvalued constants.

## Step 6: Generate implementation — 2026-10-02T06:56:23.291017462Z

All checks complete, artifacts cleaned. Final summary below.

(a) File list with line counts — workspace/implementation/ (2833 LOC total): start.sh (executable) 10; requirements.txt 1; constants.py 71; errors.py 9; store.py 71; util.py 189; envelope.py 68; auth.py 36; serialize.py 243; calcs.py 244; routes_collections.py 170; routes_feedstock.py 178; routes_sites.py 230; routes_orders.py 239; routes_takebacks.py 249; routes_reports.py 268; routes_claims.py 249; routes_targets.py 96; routes_packages.py 116; routes_clock.py 28; app.py 68.

(b) Module map: app.py — Flask bootstrap, blueprint registration, ApiError/404/405/500 envelope handlers, 0.0.0.0:$PORT (default 10000); constants.py — every program constant exactly once (see d); role and enum vocabularies; store.py — in-memory dict store singleton (empty at boot, no seeding), logical clock (starts 2026-09-01T00:00:00Z), new_common/touch (version+updated_at per mutation); util.py — half-up rounding at 0/2/3/4dp, ISO-8601 parse/format (3 fractional digits), Decimal coercion, priority-11 shape validators, pagination params (limit 1–100 default 10, offset ≥ 0); envelope.py — PRD §2.2 success/error envelopes, §2.3 list meta (limit/offset/total_count/has_more), created_at-ascending list helper; auth.py — pipeline priorities 1–3 (headers/role, endpoint roles incl. verification action split, ownership); serialize.py — per-entity JSON; OffsetRetirement carries no updated_at/version (PRD §2.4); calcs.py — all 10 calculations with pinned rounding orders (batch_recycled_content, batch_embodied_carbon, pcf_footprint, takeback_credit, replacement_quote, dye_lot_match, claim_offset_requirement, target_posture, supplier_reliability, plus zone-code/overlap helpers; site_replacement_spend is the stored spent_replacement_cents field); routes_collections.py — collections + batches + release; routes_feedstock.py — lots/QC/allocate/deallocate; routes_sites.py — sites/install/decommission cascade/zones; routes_orders.py — orders (OCC create-with-supersede, match, complete, cancel); routes_takebacks.py — take-back loop + cascade C; routes_reports.py — PCF reports (OCC, draft supersede, submit math, verification split, publish + cascade A); routes_claims.py — claims + offset retirements; routes_targets.py — targets/readings + cascade B; routes_packages.py — spec packages (OCC, pair sequence); routes_clock.py — unprefixed POST /_clock/set_current_utc.

(c) Smoke-test transcript: Boots on two dynamic ports across the session: 35475 (first server, PIDs 349204 wrapper / 349211 listener / stale probe 350123 — all killed) and 35905 (PID 372747, killed; port confirmed CLOSED via ss). Exercised live over HTTP: POST /_clock/set_current_utc → 200 echo verbatim; Collection → batch → read-back: 201/201/200 with correct envelope, QUARANTINE, available_m2 == produced_m2; 60+ assertions all PASS: 401/403/404 vocabulary; dye-lot conflict; allocate→DEPLETED; mass-balance release gate (ERR_MIX_MASS_MISMATCH then 200 at 400kg=100m²×4.0); batch math 75.0/7.9 and 14.0; supplier reliability 100.00 default and 0.0 after QC_FAILED history; install ownership 403, cert/window-buffer conflict 409; zone code conflict 409, area 422, EXHAUSTED at 0, site bubble v2→v3; order OCC 412, supersede-cancel, MATCH_FAILED empty pool, quote 60×1200×1.15=82800, complete (spent 82800, zone REPLACED, successor zone from matched batch); take-back window guards 422, CIRCULAR credit 8410 (25.00m²×250 + min(cap 2500.00, bonus 2160)), cascade C lot (factor 1.2, supplier constant, RECEIVED, origin_takeback_id, listed via the origin_takeback_id filter); report submit math 7.9/7.725, 5.8/6.15, 14.0/14.35 (all match pinned rounding: stored-3dp weighted mean, 2dp recovered m², 4dp EOL credit); verification action split 403, SoD 403, findings 400, FAIL→REJECTED→revise→DRAFT cleared; ERR_EMPTY_REPORT_INPUT 422; overlap vs in-pipeline 409 with touching-endpoints allowed; claim boundary/target guards 422, required 386.25 and 577.25 (500.0 buffer), coverage NONE→PARTIAL→FULL, publish gate 422, review SoD; cascade B (BREACHED → IN_REVIEW claim → DRAFT, required retained); cascade A (publish → SUPERSEDED → RETIRED → REVOKED); packages pair supersede v1→v2; sunset gates 409; decommission ERR_TAKEBACK_IN_FLIGHT then cascade reclaims zones with no availability restoration; pagination meta + limit 101/abc → 400. Every initial FAIL was traced to test-side arithmetic/sequencing (stale window, wiped server state, closed-interval touch), never to the implementation; one real bug found and fixed (missing req_decimal import in routes_targets.py).

(d) Chosen values for the unvalued constants: TAKEBACK_LOT_CARBON_FACTOR = Decimal("1.20") (kgCO2e per kg for cascade-C depolymerized feedstock); TAKEBACK_SUPPLIER_NAME = "CarpetLoop Take-Back Program". Both defined once in constants.py and referenced only from there (used in routes_takebacks.py sort cascade).

(e) Interpretation list — PRD-silent edges resolved (minimal/lenient):
1. Deallocate overdraft — PRD states no guard for deallocating more than the lot's mix entry; reject with ERR_INVALID_REQUEST/400 at priority 11 (mirrors "compensating action", prevents negative allocated_kg). Same for deallocating with no entry.
2. Missing OCC field (expected_collection_version/expected_site_version) — non-optional per §2.7; treated as priority-11 shape error (ERR_INVALID_REQUEST/400) rather than a 412 mismatch; the 412 comparison runs only when a well-typed integer is present.
3. Unknown/missing verification action — no transition to check at p5, so it falls through to priority-11 ERR_INVALID_REQUEST/400; parseable actions get the action-level role split at p2 as specified.
4. Completion new_zone_code uniqueness excludes the zone being replaced — it leaves IN_SERVICE in the same transition; the guard protects the post-state invariant. A same-code replacement is allowed.
5. Batch embodied_carbon_kg_per_m2 at creation — formula is defined for an empty mix (feedstock component 0), so stored as round(mfg_intensity, 3) from creation; only recycled_content_pct is null while the mix is empty (its PRD-explicit undefined clause).
6. Reading intensity range — no PRD bound; presence/numericity only (any finite Decimal accepted).
7. Pagination out-of-range/non-integer — ERR_INVALID_REQUEST/400 ("minimum accepted value" implies rejection).
8. Clock set semantics — any parseable timestamp accepted (backward jumps not prohibited); response echoes the input string verbatim per §2.5, stored parsed for comparisons.
9. Version bumps — one +1 per affected entity per client-visible operation (a mutation plus its automatic state reconciliation is one operation's worth, e.g. batch debit+EXHAUSTED on zone create = single bump).
10. Decommission from INSTALLED — the state machine lists only PLANNED and IN_SERVICE sources, so INSTALLED → ERR_INVALID_STATE/409 (no child effects exist yet anyway).
11. Cancel endpoint on MATCH_FAILED order — transitions table lists only DRAFT/MATCHED sources for the endpoint, so MATCH_FAILED → 409 (it remains cancellable via supersede/decommission as PRD states).
12. Timestamps — api_request_timestamp, created_at, recorded_at all read the logical clock (never wall time, §2.5); equal timestamps break ties by insertion sequence, also the final dye-lot-match tiebreak after created_at (PRD forbids id tie-breaks).
13. Order-complete guard order — PRD §3.4 prose lists budget before zone-code, but §2.8's explicit first-failure-wins pipeline ("fiscal guards, evaluated last") plus the scaffold priorities put zone-code (p11) before budget (p12); pipeline order implemented.
14. Allocate guard order — batch-left-QUARANTINE → ERR_INVALID_STATE/409 (p5) before lot-not-QC_PASSED 422 (p9), per pipeline; body FK existence (batch) checked after path lot (left-to-right), body FKs in canonical order (collection→batch→lot→site→zone→…).

Guards considered and rejected (not in PRD): take-back create gated on collection sunset (PRD gates only batch/report create + report submit); ownership check on site/spec-package creation (no pre-existing resource); deallocate requiring lot QC_PASSED (would break the DEPLETED→QC_PASSED revert path); availability restoration on decommission/zone reclaim (PRD restores only via order cancellation); cert checks at site creation (PRD evaluates them at install only); wall-clock fallback anywhere.

result: task_3439 implementation complete — 21-file Flask app (2833 LOC) in workspace/implementation/, compileall clean, boot-smoked on dynamic ports with all cascades (A/B/C), both OCC fields, all 10 calculations, and the 12-priority pipeline verified live; constants TAKEBACK_LOT_CARBON_FACTOR=1.20, TAKEBACK_SUPPLIER_NAME="CarpetLoop Take-Back Program".

Orchestrator verification: all 21 files present; compileall clean; constants.py:37-38 pin both constants exactly once; start.sh is foreground exec with conditional pip install; no stray listeners on smoke ports.

## Step 7: Test-fix loop — 2026-10-02T07:20:00Z

Baseline sweep: 8/8 rounds 90/94, identical 4 failures (no flakiness). All fixes test-side; implementation untouched (Step 6 code was PRD-faithful on all four).

1. test_03 test_planned_site_blocks_zone_and_takeback_and_quarantine_batch_blocked — first request tripped BOTH priority-6 guards (QUARANTINE batch + PLANNED site) and asserted ERR_SITE_NOT_INSTALLED; PRD §3.3/§2.8-rule-6 name both guards but never order them within a priority level, so the winner was not uniquely derivable (impl's batch-first reading equally faithful). Fixed by giving that request a RELEASED batch (setup_collection_with_batch) so only the site guard trips; the test's tail already isolated the batch guard (INSTALLED site + QUARANTINE batch). Both exact error ids retained.
2. test_04 test_complete_cancelled_order_returns_state_error_not_fiscal + test_failed_complete_leaves_cancelled_order_and_spend_untouched — expected ERR_INVALID_STATE; PRD §3.4 states verbatim "The order must be MATCHED — completing anything else is rejected with ERR_ORDER_NOT_MATCHED (HTTP 409)" (also §2.8 rule 6). The ERR_INVALID_STATE reading would make ERR_ORDER_NOT_MATCHED unreachable dead code, contradicting PRD. Fixed expected id to ERR_ORDER_NOT_MATCHED and re-cited §3.4; design intent (state guard p6 beats fiscal p12) preserved — setup still budget-breaching.
3. test_09 test_specifier_ownership_mismatch_returns_forbidden — asserted 403 on order-CREATE by a non-site-creator specifier. §3.4's create paragraph lists its guards (zone-site mismatch, zone state, OCC) with no ownership clause while §3.4-cancel/§3.5-cancel state ownership explicitly; §2.8 rule 3's generic "the resource's created_by" admits the create-vacuous reading (created_by is recorded BY the create call). Not uniquely derivable; split per partial-coverage: dropped the order-create assertion, replaced with the verbatim-covered order-CANCEL ownership mismatch (§3.4) alongside the existing take-back-cancel mismatch (§3.5); trailing non-mutation assertions updated (order remains DRAFT/listed, take-back remains REQUESTED). Imports adjusted (create_order in; create_replacement_order_payload, get_site_version out).

Post-fix sweep: 8/8 rounds 94/94. Docstring citations re-verified verbatim against PRD.md; 94 tests collect with zero errors; no skip/xfail added; results.{1..8}.json retained in workspace/implementation/.

Step 8 hand-off (assertions dropped, sibling paths now unexercised): (a) same-priority guard ordering within pipeline level 6 (batch-first vs site-first on a dual-failure zone create) is unasserted — impl checks batch first; (b) order-create and take-back-create by a non-site-creator specifier carry no ownership assertion — impl allows both (role-gate only); (c) ERR_INVALID_STATE is no longer asserted on the order-completion path specifically (it remains asserted on other endpoints).

## Step 7: Run tests and iterate — 2026-10-02T07:18:23.666803150Z

All artifacts verified: 8 results files from the clean sweep remain in workspace/implementation/, worklog updated, only test-suite files touched. The task loop is complete.

**Summary**

- **Iterations run:** 2 sweeps (baseline 8-round sweep → fixes → final 8-round sweep).

- **Tests deleted:** none. All 4 failures were adjudicated as test-side corrections (STEP 1c partial-coverage split / STEP 2 test-faithfulness fixes), not deletions; every PRD-covered assertion was preserved with its exact error id.

- **Fixes applied to `test_helpers/`:** none — fixtures, factories, and header builders were all PRD-consistent; the bugs were in the test functions themselves.

- **Fixes applied to `test_suite/`:**
  1. `test_suite/test_03_sites_and_zones.py` — `test_planned_site_blocks_zone_and_takeback_and_quarantine_batch_blocked`: the first zone-create request failed *both* priority-6 guards (QUARANTINE batch + PLANNED site) and asserted ERR_SITE_NOT_INSTALLED; PRD §3.3/§2.8-rule-6 name both guards but never order them within a priority level (impl's batch-first reading equally faithful → not uniquely derivable). Now uses a RELEASED batch for that request so only the site guard trips; the batch guard was already isolated at the test's tail. Both exact error ids retained.
  2. `test_suite/test_04_replacement_orders.py` — `test_complete_cancelled_order_returns_state_error_not_fiscal` and `test_failed_complete_leaves_cancelled_order_and_spend_untouched`: expected ERR_INVALID_STATE, but PRD §3.4 states verbatim "The order must be `MATCHED` — completing anything else is rejected with `ERR_ORDER_NOT_MATCHED` (HTTP 409)" (and §2.8 rule 6 repeats it); the tests' reading would render ERR_ORDER_NOT_MATCHED unreachable dead code, contradicting PRD. Expected id corrected to ERR_ORDER_NOT_MATCHED with re-cited docstrings; the budget-breaching setup is unchanged so the design instance's first-failure-wins intent (state guard p6 before fiscal p12) is still exercised.
  3. `test_suite/test_09_rbac_and_auth.py` — `test_specifier_ownership_mismatch_returns_forbidden`: dropped the order-*create* 403 assertion (§3.4's create paragraph lists its guards with no ownership clause while the cancel siblings state ownership explicitly; §2.8 rule 3's generic "the resource's `created_by`" admits the create-vacuous reading since `created_by` is recorded *by* the create — not uniquely derivable) and replaced it with the verbatim-covered order-*cancel* ownership mismatch (§3.4) alongside the existing take-back-cancel mismatch (§3.5); trailing assertions updated to the rejected-cancel post-state (order remains DRAFT and listed, take-back remains REQUESTED).

- **Fixes applied to `implementation/`:** none — Step 6's code was PRD-faithful on all four failure points.

- **Final sweep evidence:** rounds 1–8 each 94/94 passed; `results.1.json`–`results.8.json` retained in `workspace/implementation/`.

- **Step 8 hand-off (test-side fixes dominated; newly unexercised sibling paths):** (a) intra-priority-6 guard ordering on a dual-failure zone create (impl checks batch before site) is now unasserted; (b) order-create and take-back-create by a non-site-creator specifier carry no ownership assertion — the impl allows both (role-gate only); (c) ERR_INVALID_STATE is no longer asserted on the order-completion path specifically (it remains asserted on other endpoints, e.g. allocate-after-release and decommission-from-INSTALLED).

result: task_3439 Step 7 complete — all 94 tests pass in all 8 parallel sweep rounds after 3 test-suite fixes (zero implementation changes, zero deletions); results.{1..8}.json retained as artifacts.

Orchestrator verification: all 8 results files present, each passed=94/total=94/failed=0; no *.py source (excluding __pycache__) newer than results.1.json — sweep evidence is current; ERR_ORDER_NOT_MATCHED corrections and RELEASED-batch isolation confirmed in the named test files.

## Step 8: Finalize PRD — 2026-10-02T07:26:12.635992243Z

Diff confirms exactly the two intended inline edits; line counts identical (344/344, 0% delta, both changes are within-line revisions). All work is verified complete.

result: PRD_FINALIZED.md written at workspace/PRD_FINALIZED.md with 2 inline pins (zone-create guard order; create-endpoint ownership silence); 1 step_7_diff item adjudicated as no-edit.

**Line counts / delta:** PRD.md 344 lines, PRD_FINALIZED.md 344 lines, 0% line delta — both edits are inline revisions within existing paragraphs (no new sections).

**Changes (one bullet each):**
- §2.8 rule 3 (Ownership) — revise — appended: creation records the creator rather than checking ownership; the four Specifier creation endpoints (site registration, replacement-order opening, take-back opening, package issuance) are role-gated only; zone laying is carved out as an Installer operation on the parent site that does carry the ownership check — impl evidence: routes_orders.py:53-56, routes_takebacks.py:25-28, routes_sites.py:21-24, routes_packages.py:17-20 (no ownership check); routes_sites.py:163+70-77 (zone create checks contractor_name).
- §3.3 (zone laying) — revise — appended: "Both are specific-state guards of §2.8, and the batch guard is evaluated first: a laying request that would fail both is rejected with `ERR_BATCH_NOT_RELEASED`." — impl evidence: routes_sites.py:172-175 (batch guard at 172-173 precedes site guard at 174-175).

**Per-item adjudication of `<step_7_diff>`:**
1. test_03 intra-priority-6 guard order → EDIT MADE (§3.3). Impl pins batch-before-site within priority 6; PRD named both guards without ordering them.
2. test_04 ERR_ORDER_NOT_MATCHED on completion → NO EDIT. PRD §3.4 already pins it verbatim: "The order must be `MATCHED` — completing anything else is rejected with `ERR_ORDER_NOT_MATCHED` (HTTP 409)"; impl routes_orders.py:176-177 raises exactly that. The step_7_diff itself flagged this as already pinned.
3. test_09 create-endpoint ownership → EDIT MADE (§2.8 rule 3). Impl has no ownership check on any Specifier create; PRD rule 3's unqualified "Specifier operations require…" left creates ambiguous.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**
- Edit 1 (guard ordering): (a) subject = intra-priority-6 evaluation order on zone creation. (b) enumerated via grep of all four guard error IDs: routes_sites.py:172-175 (zone create, batch then site — the only ERR_BATCH_NOT_RELEASED site), routes_takebacks.py:42-43 (take-back create, sole site guard — ordering claim vacuous), routes_orders.py:176-180 (order completion, the only other dual-priority-6 site: order-MATCHED before zone-IN_SERVICE). (c) wording scoped explicitly to "a laying request" rather than a universal intra-priority ordering rule, so no claim is made about completion's different order.
- Edit 2 (ownership): (a) subject = where ownership checks apply. (b) enumerated every ownership callsite via grep of `forbid|created_by|contractor_name`: Specifier created_by checks exist only on order cancel (routes_orders.py:230-232) and take-back cancel (routes_takebacks.py:175-177); all four Specifier creates lack any check; Installer contractor_name checks exist on install/decommission/zone-create (_installer_site, routes_sites.py:70-77), match/complete (_installer_order, routes_orders.py:41-50), schedule/collect (_installer_takeback, routes_takebacks.py:96-105). (c) original draft said "creation endpoints perform no ownership check" universally — revised to enumerate only the four Specifier creations and explicitly carve out zone laying, because zone create is an Installer create that does check contractor_name; the original rule-3 first sentence kept verbatim to minimize divergence.

No SCAFFOLD*.yaml or worklog.md was read. Tests were treated only as step_7_diff evidence; both edits align to observed implementation behavior.

Orchestrator verification: diff PRD.md↔PRD_FINALIZED.md shows exactly the two claimed hunks (lines 113 and 172), no collateral edits; ERR_BATCH_NOT_RELEASED ordering pin present.

## Step 9: Complete PRD — 2026-10-02T07:47:29.452805787Z

Diff verified: 21 single-line `c` hunks (17 Edit calls, some spanning two lines), line count unchanged at 344, char delta +4052 — exactly my listed edits, nothing else touched.

**Source vs output:** `PRD_FINALIZED.md` 344 lines / 68,511 chars → `PRD_COMPLETED.md` 344 lines / 72,563 chars (+4,052 chars; 21 in-place line revisions, 0 lines added/removed).

**Counts:** 20 ambiguity-pins, 4 mismatch-revisions.

**Ambiguity-pins (PRD silent → pinned to impl):**
- §2.2 — insert — ambiguity — envelope `api_request_timestamp` is read from the logical clock, never wall-clock — envelope.py:22-29
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, or negative offset → `ERR_INVALID_REQUEST` (400) — util.py:164-184
- §2.3 — insert — ambiguity — identical `created_at` values (still clock) order by creation-acceptance sequence, never resource ids — envelope.py:66, util.py:187-189
- §2.3 — insert — ambiguity — list filters are exact-match equality; non-matching/out-of-enum filter values yield an empty page, not an error — envelope.py:62-68
- §2.4 — insert — ambiguity — one `version` increment per affected resource per operation, however many fields it writes — store.py:66-71
- §2.5 — insert — ambiguity — clock set accepts any parseable ISO-8601 timestamp and echoes the supplied string; missing/unparseable `current_utc` → 400 — routes_clock.py:20-28
- §2.7 — insert — ambiguity — `expected_collection_version`/`expected_site_version` must be integers; missing/non-integer → 400 at shape stage, `ERR_STALE_VERSION` (412) compares integer values only — routes_orders.py:73-91, routes_reports.py:36-72, routes_packages.py:39-66
- §2.9 — insert — ambiguity — values pinned for the two PRD-named-but-unvalued constants: `TAKEBACK_LOT_CARBON_FACTOR` = 1.20 kgCO2e/kg, `TAKEBACK_SUPPLIER_NAME` = "CarpetLoop Take-Back Program" — constants.py:37-38
- §3.2 — insert — ambiguity — a new batch stores `embodied_carbon_kg_per_m2` at creation (empty mix → feedstock component 0 → rounded mfg intensity) while `recycled_content_pct` stays null — routes_collections.py:110-114
- §3.2 — insert — ambiguity — deallocation overdraft (quantity exceeds this lot's mix entry, or no entry) → `ERR_INVALID_REQUEST` (400) — routes_feedstock.py:146-152
- §3.2 — insert — ambiguity — allocate and deallocate return the updated feedstock lot — routes_feedstock.py:129,163
- §3.3 — insert — ambiguity — install window end earlier than start → `ERR_INVALID_REQUEST` (400) — routes_sites.py:36-39
- §3.3 — insert — ambiguity — buffered contractor-window conflict test is inclusive: merely touching buffered windows conflict — routes_sites.py:117
- §3.4 — insert — ambiguity — site `version` increments on every order creation, supersede or not (tying §3.4 to §2.7) — routes_orders.py:97-98
- §3.4 — insert — ambiguity — `new_zone_code` uniqueness at completion excludes the zone being replaced — routes_orders.py:184, calcs.py:227-239
- §3.5 — insert — ambiguity — `ERR_PICKUP_WINDOW_INVALID` (422) applies only to parseable values; missing/unparseable window fields → `ERR_INVALID_REQUEST` (400) — routes_takebacks.py:119-143
- §3.6 — insert — ambiguity — verification `action` outside the three legal values → `ERR_INVALID_REQUEST` (400) at the shape stage; the action-level role split applies only to declared actions — routes_reports.py:160-170,192
- §3.7 — insert — ambiguity — a reading's `intensity_kgco2e_per_m2` is any finite number; no positivity/range bound — routes_targets.py:71-77
- §3.7 — insert — ambiguity — a claim's `collection_id` is not cross-checked against its report's collection — routes_claims.py:24-71 (absence of check)
- §3.8 — insert — ambiguity — a package's `collection_id` is not cross-checked against its report's/claim's collection — routes_packages.py:23-55 (absence of check)

**Mismatch-revisions (PRD described different behavior → revised to impl):**
- §2.9 — revise — mismatch — cascade B fires whenever a reading *leaves* posture `BREACHED` (re-firing if already `BREACHED`), not only on *entering* it; no PRD protection dropped, the entering case still fires — routes_targets.py:90-95
- §3.4 — revise — mismatch — dropped the unfalsifiable overclaim that `created_at` "resolves any full tie": under a still logical clock, exact-timestamp ties resolve by creation sequence (preserves the earliest-created-first intent; ids still never used) — calcs.py:142-150
- §3.4 — revise — mismatch — completion-guard narrative reordered: `new_zone_code` uniqueness (priority 11) is evaluated *before* the budget check (priority 12); the old prose listed budget first, contradicting both impl and §2.8's pipeline (self-contradiction resolved toward §2.8) — routes_orders.py:182-198
- §5 — revise — mismatch — catalogue's "every machine-readable error identifier" overclaim falsified by three transport-level ids: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500), now declared — app.py:46-60

**Lost-intent items (impl omits an implementable PRD claim):** none found. Every PRD-stated guard, cascade, formula, and side effect is present and wired in the impl.

**Dead-code / unwired-check findings:** method: cross-grep of all 46 catalogue ids against `implementation/*.py` (all raised) and all 49 impl-raised ids against the catalogue (only the 3 transport ids extra, now pinned in §5); plus a call-site walk of every guard helper. No defined-but-never-called or called-but-never-defined checks; every guarded field is written by some code path. One benign unreachable branch: `routes_orders.py:217-219` (completion sets a `RELEASED` batch with `available_m2 == 0` to `EXHAUSTED`) can never fire because every debit to zero already exhausts the batch at the debiting operation — it matches PRD §3.4's conditional sentence and needed no PRD change. Defensive `is None` fallbacks (release_reservation batch/zone, `_installer_order` site, submit_claim report) are unreachable since no delete operations exist.

**Diff confirmation:** `PRD_COMPLETED.md` exists and differs from `PRD_FINALIZED.md` by exactly the 21 single-line change hunks listed above (verified via `diff` hunk headers 43,72,74,83,89,105,130,132,154,160,168,170,178,180,184,192,208,214,224,228,294 — all `c` type, no line insertions or deletions).

Sanity check performed: re-read the ask (minimal patch pinning impl-adopted interpretations, zero remaining silence/mismatch, no impl edits), confirmed every edit traces to observed impl behavior with file:line evidence, and confirmed no edits outside the listed hunks.

result: PRD_COMPLETED.md produced at workspace/PRD_COMPLETED.md — 20 ambiguity-pins + 4 mismatch-revisions over PRD_FINALIZED.md (344 lines, +4,052 chars, 21 single-line hunks), fully aligned to implementation/ with no lost PRD intent and no unwired checks.

Orchestrator verification: diff -q confirms files differ (no silent no-op); exactly 21 change hunks; 344 lines / 72,563 chars as claimed; cascade-B revised wording read and coherent ("whether this reading pushed the posture into BREACHED or the target was already BREACHED — every IN_REVIEW claim referencing the target reverts to DRAFT; reviewed_by cleared; required_offset_kgco2e retained").
