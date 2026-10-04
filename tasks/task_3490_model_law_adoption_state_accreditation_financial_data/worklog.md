# Worklog — task_3490_model_law_adoption_state_accreditation_financial_data

## Step 1: Create task directory — 2026-10-02T16:05:00.000Z

Pre-allocated task directory verified at ./tasks/task_3490_model_law_adoption_state_accreditation_financial_data/ with workspace/ inside (per command args; no index computed, no other task_* directory created). Difficulty instruction: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 2: Generate scaffold — 2026-10-02T17:35:00.000Z

All three scaffold artifacts are generated, parse as valid YAML, and pass `scaffold_lint.py` clean (484 §1.8/§1.9 calls checked, 0 violations, all FKs reverse-reachable).

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/SCAFFOLD.yaml` (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 9 sections, each appearing once)

## Counts
- Endpoints: **40** (flat topology under `/naic`, incl. `POST /naic/_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z default)
- Entities: **14** (ModelAct, ExposureDraft, MemberBallot, State, StateAdoption, AccreditationReview, Insurer, FinancialFiling, RBCReport, Producer, ProducerLicense, MarketConductCall, MarketConductResponse, ValuationStandard)
- State machines: **11** (cyclic: ModelAct ballot-revision loop, State accreditation fail/reinstate loop, Insurer supervision loop; branching: adoption certification, review outcomes, filing edits)
- Calculations: **7** (ballot quorum/supermajority, RBC rounding-order aggregation, RBC action-level bands with covariance-vs-additive variants, desk-vs-onsite accreditation score, tiered exam-priority score, two-pass cost-share renormalization, core-act coverage)
- Validations: **32** (priority-ordered: auth → authz → existence → shape → state → OCC → safety → constraint → temporal → referential → fiscal)
- Error catalog: **50** (every id referenced by at least one validation/transition/concurrency rule)
- Roles: **6** with segregation-of-duties (reviewer rotation, actuary self-activation ban, insurer/producer/state ownership identity rules)
- Concurrency rules: **2** true OCC races (filing refile on Insurer.version, adoption supersede on State.version), both 412 ERR_STALE_VERSION
- §1.8 difficulty instances: **19 non-stub** (every rule ≥2; combinatorial_formula has 3 covering modes a/b/c)
- §1.9 corner instances: **46 non-stub + 19 excluded_because stubs** (every stub cites an existing difficulty instance)

## Hard-difficulty highlights (per the "much harder than expert" instruction)
- Dual-variant calcs on disjoint domains: RBC covariance vs additive (2.8284 NONE vs 1.6667 COMPANY_ACTION on identical inputs) and desk 90.0 vs onsite 60.0 accreditation scoring.
- All three combinatorial modes pinned: tiered+min exam score (a), sqrt→round-2dp→divide rounding order (b, pinned literal 1.7341 vs 1.7321), single-renormalization cost-share floor (c).
- Depth-4 publish cascade (supersede act → supersede adoptions → coverage recompute → auto-review creation) and depth-3 validate cascade (RBC report → supervision → escalation flags), each hop caused by the previous.
- Two disjoint validation-priority conflicts (state vs constraint at P6/P21; safety vs temporal at P18/P28), two boundary checks on different metrics/endpoints (vote count ceil(2/3×5)=4; ratio 2.0000 vs 1.9999), two interval semantics (half-open adjacency-allowed exposure windows vs closed+180-day-buffer review periods), two compensating invariants of different quantity types (license count; monetary surplus sum under supersede).

All formula-derived assert literals were executed in Python before being pinned; placeholder closure, name uniqueness across both design files, grounds resolvability, and forbidden-vocabulary scans all pass with zero findings. Note: the task directory also contains a pre-existing `worklog.md` and `workspace/` (not created by me, left untouched).

[Orchestrator verification: all three files exist and parse as valid YAML; endpoint count 40 confirmed; difficulty 19 non-stub / 0 stub confirmed; corner 46 non-stub / 19 stub confirmed. Per-rule and per-section breakdowns measured from YAML: difficulty {dual_variant_calc:2, combinatorial_formula:3, non_linear_state_machine:2, transitive_cascade:2, priority_pair_validation_conflict:2, boundary_precision_check:2, cross_entity_state_dependency:2, resource_temporal_overlap:2, compensating_invariant:2}; corner {entities:6, state_machines:10, calculations:6, validations:9, endpoints:2, rbac:5, cross_cutting_layers:5, errors:2, consistency_model:1}.]

## Step 3: Copy shared files — 2026-10-02T17:40:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T18:05:00.000Z

The PRD is complete and all three hard contracts pass. Final summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/workspace/PRD.md` — 316 lines.

**Sections:** 1. Introduction (2 paragraphs); 2. Global Specifications (2.1 Roles & RBAC with per-role identity prose, 2.2 API Response Structure — byte-identical to the fixed verbatim block, verified programmatically, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 Precision & Rounding, 2.6 OCC, 2.7 Registries/Version Lines/Supersession, 2.8 Validation Pipeline & Error Precedence); 3. Business Logic (7 subsections: model-instrument lifecycle, publication/adoption/coverage, accreditation reviews, filings & RBC, valuation standards, producer licensing & expiry sweep, market conduct calls & cost allocation); 4. Endpoint Definitions (40 rows, 4 columns, path set diff vs scaffold: empty); 5. Error Code Catalogue (50 rows, 2 columns, id set diff: empty). File ends at §5 — no audit footer.

**Contract 1 — Field-Name Coverage: PASS.** 85 required names (all `entities[].fields[].name`, all endpoint `input`/`query_params` identifiers); after fence-aware token extraction, 0 missing (one gap, `call_id`, was found by the sweep and repaired in §3.7).

**Contract 2 — Rule Coverage: PASS.** All 32 validations expressed with the §2.8 ordered pipeline plus explicit per-endpoint evaluation order in §3 (e.g., exposure create: state → window length → overlap; ballots: BALLOTING → suspended → duplicate; reviews: rotation → overlap → gap; filings: refs → OCC → standard currency). Both OCC rules name write endpoint, `expected_insurer_version`/`expected_state_version`, `ERR_STALE_VERSION`/412, no race framing. All 11 state machines' transitions expressed with preconditions, error ids, and side effects (publish 4-hop cascade, validate 3-hop cascade, ballot-fail void cascade, six State standing loops, three symmetric certify branches). All 7 calculations in precise reconstruction-tested prose with constants (60% quorum, two-thirds supermajority, 75.0 pass threshold, 30-day comment window, 180-day review period/gap, 50.0 coverage floor, 100000-cent cost floor, 5% share floor, 0.5 complaint weight, caps 50/100) and the scaffold's own pinned-ordering worked examples (1.7341 vs 1.7321; 2.8284 `NONE` vs 1.6667 `COMPANY_ACTION`; 90.0 desk vs 60.0 onsite). Every `errors[].id` appears in §1–§4 prose (0 missing). All enum/state values present.

**Contract 3 — §3 Path Purity: PASS.** 426 backticked tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path tokens.

One adjudication to note: the scaffold's StateAdoption state machine phrases the certified→`SUPERSEDED` trigger as "a successor adoption … is certified," but the `POST /naic/adoptions` endpoint states twice (description + side effects) that creation supersedes the prior `CERTIFIED_*` adoption, and the OCC rule description repeats that. I followed the endpoint (creation-time supersession) — stated three times in the scaffold versus once. The withheld design files were never opened.

[Orchestrator verification: PRD.md exists at 316 lines, 81 ERR_ token mentions; title and section structure confirmed. ADJUDICATION FLAG for Step 7: adoption supersession is creation-time per PRD (endpoint semantics won over SM phrasing).]

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T18:35:00.000Z

All checks pass. Stage 1 is complete.

## Summary

Created `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/test_helpers/` (9 files, 2487 lines). No `test_suite/` was created — that is Stage 2's job.

**File list (lines · public surface):**
- `types.py` (364) — aliases (`JsonObject`, `Headers`, `Params`, `ResourceId`, `Instant`); `UserRole`; 19 status/type enums (`ModelActStatus`, `AdoptionStatus`, `ReviewStatus`, `ActionLevel`, `FilingStatus`, `LicenseStatus`, …); 14 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` — every entity in this scaffold is `common_fields: true`; nullable fields typed `Optional`).
- `constants.py` (160) — thresholds + clock helpers `days_after`, `days_after_clock_start`, `format_instant`.
- `api_errors.py` (148) — `ApiErrorId` (41 ids), `HTTP_STATUS_CODES`, `PATH_ID_NOT_FOUND_CODES`, registers with `set_error_http_status_map` at import.
- `api_client.py` (235) — `ApiClient(GenericApiClient)` with 40 endpoint methods (one per endpoint, all under `/naic`, clock included at `/naic/_clock/set_current_utc` — verified prefixed in both scaffold and PRD, so the unprefixed-clock trap does not apply here); `create_api_client(base_url=None)` factory; module-level shared instance `api_client` plus module `__getattr__` delegation so the module itself is callable like a client.
- `api_errors.py`/`test_users.py` (126) — `TEST_USERS` (opaque roles only: association_staff, actuary_author, actuary_activator, review_team_lead), `make_*_headers` builders for all six roles (entity-backed roles — StateRegulator/InsurerUser/ProducerUser — are builder-only, since a non-resolving `X-User-ID` is a 401), `headers_for_role`, `headers_without_identity`, `headers_with_unknown_role`, `SECOND/THIRD_LEAD_HEADERS`.
- `factories.py` (308) — `DROP` sentinel + 16 payload builders (input fields only); all default datetimes ≥ 2026-09-01 clock start.
- `assertions.py` (467) — `assert_{entity}` ×14; two timestamp families: `assert_system_timestamp` (exactly 3 fractional digits — created_at/updated_at only) vs `assert_clock_timestamp` (no forced fraction — cast_at, published_at, windows, periods); Decimal math checkers `compute_expected_rbc`, `expected_action_level`, `compute_expected_exam_priority`, `compute_expected_allocations` (pinned two-pass floor + largest-remainder with naic_code tie-break + empty-set fallback), `assert_rbc_report_matches_filing`, `assert_allocation_invariant`.
- `fixtures.py` (571) — `Bundle`; clock, state, act-lifecycle (`create_act_in_balloting`/`create_adopted_act`/`create_published_act` with `state_map` injection + `exposure_start/end` overrides), adoption/certify, review (`run_review`, `drive_state_to` PROBATION/SUSPENDED with 180-day spacing and lead rotation, `next_review_period`), standard/insurer/filing chains (`setup_filing_ready`, `setup_validated_filing`, `create_validated_filing`), producer/license (`setup_issued_license`), call/response (`setup_call_with_responses`), and `setup_publish_cascade_ready`. OCC creates re-read parent version unless pinned; entity-backed calls always thread live entity ids.
- `__init__.py` (108) — framework re-exports + submodule bindings. The name `test_helpers.api_client` is never rebound to the instance (verified programmatically: `import test_helpers.api_client as ac` binds the module, `ac.ApiClient` and `ac.create_state` both work, `ac.create_state.__self__ is` the shared instance).

**Constants pinned (all match PRD.md verbatim; no scaffold/PRD disagreement found):**
QUORUM 0.60 (§3.1 "at least 60 percent"), SUPERMAJORITY 2/3 (§3.1 "two-thirds"), MIN_COMMENT_DAYS 30 (§3.1), PASS_THRESHOLD 75.0 (§3.3), MIN_REVIEW_GAP_DAYS 180 (§3.3), AUTO_REVIEW_PERIOD_DAYS 180 (§3.2), MIN_COVERAGE_PCT 50.0 (§3.2), COVERAGE_WHEN_NO_CORE_ACTS 100.0 (§3.2), RBC floors 2.0/1.5/1.0/0.7 (§3.4), MIN_CALL_COST_CENTS 100000 (§3.7), MIN_SHARE_PCT 0.05 (§3.7 "5 percent"), COMPLAINT_WEIGHT 0.5, COMPLAINT_CAP 50, NEUTRAL_RBC_POINTS 25, SCORE_CAP 100, share tiers 0.25→20 / 0.10→10 (§3.7), pagination 10/1/100 (§2.3), CLOCK_START 2026-09-01T00:00:00Z (§2.4), edit ids E101/E103/E106/E107 (§3.4).

**Self-checks:** (1) import check prints "helper imports OK"; (2) `py_compile` clean on all 9 files; (3) constants grep confirms every pinned value with PRD cites. Additionally verified the math helpers reproduce every design-index literal exactly (2.8284/1.6667, 1.7341-vs-1.7321 pinned rounding order, 0.9428 AUTHORIZED_CONTROL, 2.0000/1.9999 band boundary, 80.0 and 45.0 exam scores, 1000000 two-pass floor, 33335/33334/33334 tie-break, empty-set fallback) and date helpers match the design instances' 180-day arithmetic (2026-06-30 + 180 = 2026-12-27).

**Note for Stage 2:** design-instance review periods dated before the clock start (e.g. 2026-01-01) are legal as-is — review periods are pure caller data and never compare against the logical clock; only exposure-window closes, license expiry, and AUTO_COVERAGE review periods touch the clock. My fixture defaults anchor at/after the clock start regardless.

[Orchestrator verification: 9 helper files present; `import test_helpers.*` prints OK from task dir; test_suite/ absent as required. 41 error ids in api_errors vs 50 in catalog — 5a says PATH_ID_NOT_FOUND_CODES separate; Step 5b/7 to confirm no test asserts an unregistered id.]

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T19:10:00.000Z

All checks pass. Stage 2 is complete.

## Summary

**Test files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/test_suite/`):

| File | Tests |
|---|---|
| `conftest.py` | — (api + staff_headers fixtures) |
| `test_01_model_acts.py` | 8 |
| `test_02_ballots.py` | 7 |
| `test_03_adoptions.py` | 7 |
| `test_04_accreditation.py` | 10 |
| `test_05_filings_rbc.py` | 9 |
| `test_06_licensing.py` | 6 |
| `test_07_market_conduct.py` | 7 |
| `test_08_valuation_standards.py` | 5 |
| `test_09_cross_cutting.py` | 6 |

**Emitted: 65 / 65** (Queue A Difficulty 19/19, Queue B Corner 46/46). **Skipped instances: none.** All 19 `excluded_because` stubs were left untranslated (cross-references verified against the difficulty index during the AST audit).

**Self-checks (all green):**
1. AST tag audit (real `ast` parse): 65 tests, exactly one `Design:` tag each, tag is the docstring's final line, every tag resolves to a non-stub instance, no duplicates, no uncovered instances → "queue A covered 19/19, queue B covered 46/46".
2. `PYTHONPATH=. python3 -m pytest test_suite --collect-only -q` → 65 collected, exit 0.
3. `py_compile` on all 10 files → OK.
4. Bonus verbatim-citation pass: 122/122 docstring quotes grep literally against PRD.md.

**Adjudications made (assertion shape adjusted, instances still emitted):**
1. `model_act_creation_defaults`, `state_create_system_fields_input_ignored`, `version_increments_on_mutation` — the PRD never pins an initial `version` value (§2.4 only states "increments by exactly one on every mutation"), so absolute `version == 1` / `1 → 2` asserts fail the two-reader test. I assert the derivable parts instead: positive-int version + PRD-covered defaults; `id != supplied` / `version != 99` for the ignored-inputs case; and relative +1 increments across two indisputable standing changes (FAIL then PASS finalize) for the mutation case.
2. `ballot_supermajority_count_boundary` and `ballot_abstain_counts_for_quorum_not_favorable` — the recipes capture `votes_cast`/`favorable_votes` from the close-ballot *response*, but PRD §3.1 pins "the counters themselves reset to zero" on failure, so post-fail tallies of 5/3 or 5/2 are self-contradictory. I observe the live tallies via a pre-close act read (PRD: counters recomputed on each successful cast) and assert the reset-to-0 afterward; the boundary claims (3 < ceil(2/3×5) = 4; ABSTAIN counts toward quorum but not favorable) are preserved.

**Helper concerns (reported, not fixed — helpers are frozen):** none blocking. `fixtures.create_act_in_balloting` ignores its `states` argument when `state_map` is passed (harmless; documented behavior works). No other issues found.

[Orchestrator verification: `pytest --collect-only -q` from task dir reports 65 tests collected, exit 0. STEP-7 FLAGS: (i) PRD silent on initial `version` value — tests assert only relative +1; (ii) ballot close-failure resets counters to 0 — tests read tallies pre-close; (iii) adoption supersession is creation-time per PRD.]

## Step 6: Generate implementation — 2026-10-02T19:55:00.000Z

All 40 endpoints registered, everything verified. Implementation is complete.

## Report

### Module list (workspace/implementation/, all paths absolute)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Guarded pip install + `exec python3 app.py`, `$PORT`/0.0.0.0 |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 98 | Flask wiring, error handlers, `POST /naic/_clock/set_current_utc` + license expiry sweep |
| `errors.py` | 9 | `ApiError(error_id, message, http_status)` |
| `db.py` | 71 | In-memory dict store (empty at boot, no seeding), logical clock default `2026-09-01T00:00:00Z`, `base_record`/`touch` |
| `util.py` | 222 | Envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamp 1–100), two-family timestamp rendering, shape validators, `rhu` half-up rounding |
| `auth.py` | 75 | X-User-ID/X-User-Role, six roles, entity-backed resolution for StateRegulator/InsurerUser/ProducerUser (401 otherwise) |
| `serialize.py` | 210 | Per-entity serializers, exact scaffold field names |
| `calc.py` | 227 | ballot_adoption_rule (integer ceil via Fraction), rbc_capital_aggregation + rbc_action_level (pinned sqrt→round→divide order, Decimal prec 60), accreditation_score, exam_priority_score, cost_share_assessment (two-pass largest remainder, empty-set fallback, naic_code tie-break), core_act_coverage, AUTO_COVERAGE review factory |
| `routes_model_acts.py` | 162 | act create/read/close-ballot/publish + 4-hop publish cascade |
| `routes_exposure.py` | 194 | exposure drafts + ballots |
| `routes_states.py` | 182 | states + adoptions + certify |
| `routes_reviews.py` | 166 | reviews + issue-findings + finalize + state standing cascade |
| `routes_insurers.py` | 65 | insurer registry |
| `routes_filings.py` | 244 | filings CRUD-ish, submit, validate + RBC/supervision/escalation cascade, rbc-reports list |
| `routes_licensing.py` | 176 | producers + licenses + issue/revoke |
| `routes_market.py` | 154 | market conduct calls + responses + close/cost-share |
| `routes_valuation.py` | 72 | standards create/activate + retirement cascade |

**Endpoint count: 40** (verified via Flask url_map dump — matches the PRD §4 table exactly).

### Self-smoke-test transcript (dynamic port 35335, then 42911 after restart; server killed by exact PID, port verified free)

- `POST /naic/_clock/set_current_utc` → 200, empty-object data envelope
- `POST /naic/states` → 201 (`core_act_coverage_pct: 100.0`, `created_at: "2026-09-01T00:00:00.000Z"`)
- `POST /naic/model-acts` → 201 (DRAFTING); `GET /naic/model-acts/{id}` → 200
- Bad enum → 400 `ERR_INVALID_REQUEST`; unknown act → 404 `ERR_MODEL_ACT_NOT_FOUND`; missing headers → 401 `ERR_UNAUTHENTICATED`; Actuary creating state → 403
- Draft create → 201 (`exposure_number: 1`, act → EXPOSURE_OPEN); close too early → 409 `ERR_COMMENT_WINDOW_OPEN`; after clock advance close → 200, act → BALLOTING
- Ballot YEA → 201 (`cast_at: "2026-10-20T00:00:00Z"` — domain family, no forced fraction); close-ballot pass → ADOPTED; publish → PUBLISHED
- Adoption OCC: stale → 412 `ERR_STALE_VERSION`; then correct version → 201; duplicate pending → 409 `ERR_DUPLICATE_ADOPTION`; certify → CERTIFIED_SIMILAR, coverage 100.0
- Review: desk 18/20 → 90.0; wrong lead issue-findings → 403; lead 12/20 → onsite 60.0, proposed FAIL; finalize → FINAL_FAIL, state PROBATION/fails 1; rotation → 422 `ERR_REVIEWER_ROTATION_REQUIRED`; gap → 422 `ERR_REVIEW_GAP_TOO_SHORT`; overlap → 409 `ERR_REVIEW_WINDOW_OVERLAP`; second fail → SUSPENDED/fails 2; pass finalize from SUSPENDED → ACCREDITED/fails 0 (reinstatement loop)
- Standards: self-activation → 422 `ERR_SELF_ACTIVATION_FORBIDDEN`; other actuary activates → ACTIVE; v2 activation retires v1 → filing pinned to v1 fails validate with 422 `ERR_VALUATION_STANDARD_NOT_ACTIVE`
- RBC pinned example: charges (1,1,1), surplus 3 → `acl_covariance_cents 1.73`, `ratio_covariance 1.7341` (pinned order), `ratio_additive 1.0`; insurer latest_* set; supervision at 0.2887 → MANDATORY_CONTROL → UNDER_SUPERVISION; escalation hop 3 flips a pre-existing response's `escalation_flag` true; refile of same period → old VALIDATED filing SUPERSEDED, RBC report kept (list total 1), latest_* → null
- Licenses: touching-endpoint window → 409 `ERR_LICENSE_WINDOW_OVERLAP`; cross-producer apply → 403; issue → count 1; clock advance past `valid_until` → EXPIRED, count 0; revoke after expiry → 409 `ERR_LICENSE_NOT_ISSUED`; SUSPENDED state: ballot → 422 `ERR_VOTING_STATE_SUSPENDED`, issue → 422 `ERR_STATE_SUSPENDED`
- Publish cascade: v2 publish → v1 SUPERSEDED, certified adoption SUPERSEDED, AA coverage 50.0 → 0.0, AUTO_COVERAGE review created (null lead, desk 0.0, period [now, now+180d])
- Cost share: premiums 100000/100000/1000, cost 100001 → N6 excluded (share 0.49% < 5%) with 0; survivors floor 50000+50000, remainder 1, fractional tie broken by naic_code ASC → N4 50001, N5 50000, sum invariant 100001
- Ballot fail: NAY-only close-ballot → act DRAFTING, counters 0, ballot VOID
- Pagination meta: `limit 1 offset 0 total 2 has_more true`, `response_type: "array"`

### Interpretations chosen where the PRD does not pin unique behavior

1. **Validation edits E101/E103/E106/E107** — neither PRD nor scaffold defines any failure condition — all edits always pass; EDITS_FAILED is unreachable (routes_filings.py `validate_filing`). Most consequential gap; flag for the fix loop.
2. **State `code` uniqueness** — PRD §2.7 declares it unique but assigns no catalogue error id — enforced with `ERR_INVALID_REQUEST` 400 (routes_states.py `create_state`).
3. **RBC division by zero** (all three risk charges 0) — PRD silent — ratio := 0.0000 → MANDATORY_CONTROL rather than a 500 (calc.py `rbc_values`).
4. **Cascade version bumps** — §2.4 "each touched resource's version increments individually" vs narratives that pointedly name one resource — bump version/updated_at on every cascade-mutated resource (voided ballots, superseded acts/adoptions/filings, retired standards, escalated/allocated responses, expired licenses) EXCEPT producer on `active_license_count` changes (§3.6 pins only the license's version) and state on coverage-only recompute (§3.2 pins the state's exact +1 at adoption recording) (db.py `touch` call sites).
5. **Superseding a VALIDATED filing** — §3.4 "recomputed to null until a successor filing validates" taken literally — latest_* := null even if other periods hold validated filings; insurer `status` untouched until next validate (routes_filings.py `create_filing`).
6. **Escalation hop 3 trigger** — "when the insurer became UNDER_SUPERVISION" — fired whenever validate lands the insurer in UNDER_SUPERVISION (idempotent since the flag is monotonic; equivalent outcomes) (routes_filings.py `validate_filing`).
7. **Resource-dependent ownership placement** — §2.8 puts ownership (stage 2) before path resolution (stage 3), but submit/issue/revoke/close/issue-findings ownership needs the resolved resource — body-derived ownership (ballot/adoption state_code, filing insurer_id, license producer_id) runs pre-path-resolution; resource-derived ownership runs immediately after path resolution, before shape/state gates (all route modules).
8. **Ownership field absent from body** — can't compare — falls through to shape 400 rather than 403.
9. **Pagination out-of-range** — min/max declared without an error — `limit` clamped to [1,100], `offset` to ≥0; non-integer values → 400 `ERR_INVALID_REQUEST` (util.py `pagination_params`).
10. **Filing list filters** — invalid `period_year` (non-int) or unknown `status` → 400 `ERR_INVALID_REQUEST` (routes_filings.py `list_insurer_filings`).
11. **Clock semantics** — no monotonicity rule stated — any settable instant accepted; expiry sweep (strictly-greater-than `valid_until`) runs on every set; response is 200 with `response_type "object"`, `data {}` (app.py).
12. **Auto-created reviews** bypass manual rotation/overlap/gap checks (system creation per cascade hop 4) (calc.py `auto_create_coverage_review`).
13. **"Most recent" FINAL review for rotation** — determined by creation order (`_seq`), not period dates (routes_reviews.py).
14. **`api_request_timestamp` is wall-clock** (PRD §2.2 example shows a non-logical-clock date); `created_at`/`updated_at` read the logical clock and render 3-digit fractions; all other domain timestamps render as the clock reads (no forced fraction) — two serializer families in util.py/serialize.py.
15. **Initial `version` = 1** on every created resource (PRD pins increments, not the start).

### Error-id cross-check
Both directions clean: all 50 PRD-catalogue ids have at least one reachable raise site in code; the only code-side id absent from the catalogue is `ERR_INTERNAL`, used solely by the defensive 500 catch-all handler (not a business path). Flask routing 404/405 fallbacks emit `ERR_INVALID_REQUEST` in the error envelope.

[Orchestrator hand-off verification: uuid4 used in dashed form only (db.py:43); 39 domain routes + 1 clock route = 40; 51 distinct ERR ids raised in code vs 50 in PRD — delta is exactly {ERR_INTERNAL}, zero PRD ids unraised. Claim verified against source.]

## Step 7: Test-fix iteration loop — 2026-10-02T20:05:00.000Z

All 8 result files are from the final passing sweep (the pre-sweep `rm -f` guarantees freshness; content verified 65/65 per round).

## Summary

- **Iterations run:** 2 (initial sweep: 64/65 in all 8 rounds — one deterministic failure; post-fix sweep: 65/65 in all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/test_helpers/factories.py` — `insurer_payload()`. The `name` named parameter consumed the `DROP` sentinel before `_merge()` could strip it, so `name=factories.DROP` placed the non-JSON-serializable `_Drop` object directly into the base payload (`TypeError: Object of type _Drop is not JSON serializable`). Fixed by omitting the `name` key from the base dict when `name is DROP`, preserving the default-name and explicit-name paths. This honors the module's own documented contract ("pass DROP as an override value to omit a key entirely — for missing-required-field cases"). The other DROP call site (`is_core=DROP` in test_01) flows through `**overrides` and was already correct.

- **Fixes applied to `test_suite/`:** none. The failing test (`test_insurer_create_missing_name_returns_invalid_request`) is PRD-faithful: §3.4 names `name` as a required insurer field and §2.8 pins `ERR_INVALID_REQUEST` (400) for missing required fields — verbatim coverage, uniquely derivable.

- **Fixes applied to `implementation/`:** none needed — the implementation correctly rejected the payload; it was the factory that never sent the intended missing-field request.

- **Untested-sibling-path concerns (for Steps 8/9):** pre-flagged by Step 6 and still standing — (1) validation edits E101/E103/E106/E107 always pass, making the EDITS_FAILED state unreachable (neither PRD nor scaffold defines a failure condition); (2) on refile-supersede of a VALIDATED filing, insurer `latest_*` fields are nulled but insurer `status` is left untouched until the next validate (§3.4 "recomputed to null until a successor filing validates" taken literally).

- **Confirmation:** `results.1.json` … `results.8.json` from the FINAL passing sweep (65/65 × 8) remain on disk at `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/workspace/implementation/`.

[Orchestrator verification: all 8 results.*.json read back passed=65 failed=0 total=65 errors=0; factories.py line 172 carries the `if name is not DROP:` fix; newest implementation/*.py mtime is 19:21 (Step 6 era) — no post-Step-6 impl writes, consistent with the 0-impl-fix claim. STEP-8 DIFF = exactly one item, the factories.py fixture fix (a pure test-side bug — likely zero-edit PRD_FINALIZED).]

## Step 8: Finalize PRD — 2026-10-02T20:20:00.000Z

The evidence chain is complete and the zero-edit outcome is confirmed. PRD_FINALIZED.md is byte-identical to PRD.md.

## Summary

**Line counts / %-delta:** PRD.md 316 lines, PRD_FINALIZED.md 316 lines — 0% delta, md5-identical (`7baa1572...`). Zero edits.

**Changes:** none (zero bullets is the correct output — the single Step 7 item is a pure test-side fixture bug).

**Evidence log** (what I read to confirm the Step 7 item reveals no PRD silence or PRD/impl mismatch):

1. **The Step 7 fix itself** — `test_helpers/factories.py:162-174`. The fix is entirely inside the payload factory: `insurer_payload()` now omits the `name` key from the base dict when `name is DROP` (line 172: `if name is not DROP:`), instead of letting the named parameter swallow the sentinel and serialize the non-JSON `_Drop` object. No implementation or test-suite file was touched.

2. **The failing test** — `test_suite/test_09_cross_cutting.py:148-159`. `test_insurer_create_missing_name_returns_invalid_request` asserts that creating an insurer without `name` returns `ERR_INVALID_REQUEST`, citing PRD §2.8 and §3.4 verbatim in its docstring.

3. **PRD already uniquely determines this behavior:**
   - `PRD.md:160` (§3.4): "An insurer enters the system when `AssociationStaff` registers it with a unique `naic_code`, a legal `name`, and a `domicile_state_code`..." — `name` is a required field.
   - `PRD.md:108` (§2.8 stage 5): "required fields are present... any violation is `ERR_INVALID_REQUEST` (400)."

4. **Implementation matches the PRD exactly** — `workspace/implementation/routes_insurers.py:39` calls `req_str(body, "name")`, which via `util.py:145-148` (`req_field`) raises `ApiError("ERR_INVALID_REQUEST", "Missing required field: name", 400)` when the key is absent or null. No behavioral choice was left open — the impl does verbatim what the PRD already pins.

Since the only Step 7 item was a client-side serialization bug in a test factory, and the behavior it was trying to exercise is already fully determined by PRD §3.4 + §2.8 stage 5 and correctly implemented, no PRD patch is warranted.

[Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` → byte-identical as reported; no implementation/*.py file is newer than results.1.json — the clean sweep remains valid.]

## Step 9: Complete PRD — 2026-10-02T20:50:00.000Z

All verification sweeps are complete. Final report:

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_3490_model_law_adoption_state_accreditation_financial_data/workspace/PRD_COMPLETED.md`
- Source `PRD_FINALIZED.md`: 316 lines / 47,634 chars → `PRD_COMPLETED.md`: 316 lines / 51,427 chars (**+3,793 chars, +0 lines**; all edits are in-paragraph inserts/revisions, no new sections).
- **Counts: 17 ambiguity-pins (via 12 targeted edits), 0 mismatch-revisions, 0 impl bugs.**

### Changes (all inserts/revisions of ambiguity; impl file:line per change)

- **§2.2** — insert — ambiguity — `api_request_timestamp` pinned to server wall clock, logical clock scoped to persisted resource timestamps (decisive context: the §2.2 example timestamp 2025-05-24 predates the clock's 2026-09-01 initial reading, so it cannot be logical-clock-sourced) — `util.py:33-39`
- **§2.3** — insert — ambiguity — `limit` clamped to [1,100], `offset` clamped to ≥0, non-integer either → `ERR_INVALID_REQUEST` (400) — `util.py:103-117`
- **§2.3** — insert — ambiguity — `created_at` ties broken by creation sequence — `util.py:120-122`
- **§2.3** — insert — ambiguity — `has_more` defined as `offset + len(items) < total_count` — `util.py:47-53`
- **§2.3** — insert — ambiguity — non-integer `period_year` / out-of-lifecycle `status` filter → 400 — `routes_filings.py:133-144`
- **§2.4** — revise — ambiguity — `version` starts at 1 at creation — `db.py:46-58`
- **§2.4** — insert — ambiguity — `active_license_count` and `core_act_coverage_pct` side-effect updates do not by themselves increment the producer's/state's `version` — `routes_licensing.py:154-156,173-175`, `app.py:91-93`, `calc.py:186-205`
- **§2.4** — insert — ambiguity — all non-system timestamps (windows, `enacted_on`, periods, license bounds, `cast_at`, `published_at`) render as the instant reads, fractional part only when sub-second precision exists — `util.py:73-81`
- **§2.4** — revise — ambiguity — clock accepts any well-formed instant (no monotonicity); expiry sweep runs on every set; endpoint answers 200 with empty `data` object — `app.py:78-94`
- **§2.7** — revise — ambiguity — duplicate state `code` rejected with `ERR_INVALID_REQUEST` (400) since §5 assigns it no catalogue id (making a 409-with-id unimplementable); two-letter form is convention only, no format validation — `routes_states.py:38-43`
- **§2.8 stage 2** — insert — ambiguity — resource-dependent ownership runs immediately after path resolution; body-derived ownership runs before it; an omitted ownership field falls through to stage 5 as 400, not 403 — `routes_reviews.py:116-120`, `routes_exposure.py:138-140`, `routes_filings.py:45-47`
- **§3.2** — insert — ambiguity — auto-created review's `desk_score` computes to 0.0 from its 0/1 counts — `calc.py:218`
- **§3.3** — revise — ambiguity — "most recent" FINAL review defined as latest-created; the rotation/overlap/gap triplet guards staff scheduling only, auto-created reviews skip all three — `routes_reviews.py:58-66`, `calc.py:208-227`
- **§3.4** — insert — ambiguity — supersession nulling of `latest_*` applies even when other periods hold validated filings; insurer `status` unchanged by supersession — `routes_filings.py:99-106`
- **§3.4** — insert — ambiguity — E101/E103/E106/E107 have no defined failure conditions beyond creation-time shape rules, so validation always passes; `EDITS_FAILED` specified for completeness but unreachable — `routes_filings.py:1-7,193-195`
- **§3.4** — insert — ambiguity — all-zero risk charges → both ratios defined as 0.0000 → `MANDATORY_CONTROL` — `calc.py:82-91`
- **§3.4** — revise — ambiguity — hop 3 fires whenever hop 2 *leaves* the insurer in `UNDER_SUPERVISION` (newly or already supervised); already-flagged responses left untouched — `routes_filings.py:225-232`

### IMPL BUGS

**None.** Every divergence candidate adjudicated as genuine PRD ambiguity, not a uniquely-derivable PRD violation. The two closest calls: (a) wall-clock `api_request_timestamp` vs §2.4 "never falls back to wall-clock time" — resolved by §2.2's own example timestamp preceding the clock's initial instant, so the logical-clock reading is not faithful; (b) state-code duplicate at 400 vs §2.8 stage 9 "all 409" — resolved because §2.7 assigns the rule no error identifier and §5's catalogue has none, so no 409 form is implementable.

### Dead-check audit — CLEAN

Every catalogue error id (§5) has a reachable raise site; every PRD-required guard (state gates, ownership comparisons, OCC ×2, uniqueness ×6, rotation/gap/overlap, suspended-state gates, cost floor, no-responses floor, standard-currency checks at both create and validate) was traced to a live call site in pipeline order. Writer-side check: every guard's field has a writer that keeps the guard satisfiable. The only unreachable branch is `EDITS_FAILED`, now pinned in PRD as specified-but-unreachable. Framework fallbacks (undeclared-path 404/405 with `ERR_INVALID_REQUEST`, 500 with `ERR_INTERNAL`) exist in `app.py:47-75` but are outside the declared API surface and were deliberately left unpinned.

### Nullable-field crash audit — CLEAN

All reads of PRD-nullable fields are guarded: `latest_rbc_ratio` None-checked (`calc.py:122-124`), `team_lead_id` None-checked before comparison (`routes_reviews.py:119`), `published_at`/findings fields/`allocated_cost_cents`/`cost_share_excluded` serialize None-safely, and all `.get()` lookups on cascade paths are None-checked. No division path can hit a zero denominator.

### Recording-vs-carry — CLEAN

Every field the PRD says is "recorded"/"pinned"/"derived" persists and is readable: `cast_at`, `published_at`, `author_user_id`, `team_lead_id`, `valuation_standard_version_label`, `insurer_naic_code`, `lead_state_code`. No request-supplied field is silently dropped.

[Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (real edits, not a silent no-op); 316 lines as reported; spot-grep confirms the wall-clock, pagination-clamp, version-1, EDITS_FAILED-unreachable, and latest_*-nulling pins present in the text; 0 implementation/*.py files newer than results.1.json (impl untouched since clean sweep); 8 results.*.json files on disk. Zero impl bugs → no Step 9b fix/re-sweep needed. PIPELINE COMPLETE.]
