# Worklog — task_3495_federal_aid_highway_project_authorization_reimbursement

Scenario: Federal-Aid Highway Project Authorization & Reimbursement (FHWA). Difficulty instruction: "Generate task much harder than expert level!"

## Step 1: Create task directory — 2026-10-02T17:15:00.000Z

Pre-allocated directory `./tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/` verified to exist with `workspace/` inside; no new index computed, no other task directory created.

## Step 2: Generate scaffold — 2026-10-02T17:40:00.000Z

Verbatim subagent summary:

Scaffold generation complete. All three artifacts are written, parse cleanly, and pass `scaffold_lint.py` with `VERDICT: clean lint` (1,221 recipe calls scanned, 0 violations).

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys inside)
- `/home/ubuntu/github/CodingPRD/tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts**
- Endpoints: **40** (kept at the impl-gen safety ceiling despite "harder than expert" — difficulty is carried by density, not surface)
- Entities: **11** (FundingProgram, Apportionment, StateProgram, PublicComment, Project, ProjectClearance, Authorization, Bid, Voucher, ChangeOrder, Audit)
- State machines: **8** (cyclic STIP amendment loop, cyclic voucher reject→resubmit, auto FULLY_DRAWN↔OBLIGATED, branching clearances/change-orders, audit closeout)
- Difficulty-design instances (§1.8, non-stub): **19** — every rule ≥2 (combinatorial_formula has 3, covering modes a/b/c)
- Corner-design instances (§1.9): **65 total, 61 non-stub** (+4 `excluded_because` stubs)
- Also: 32 validations (priorities 1–32), 32 errors, 7 calculations, 5 roles (all `opaque` with two X-User-ID segregation-of-duties gates), 1 OCC rule on `PATCH /projects`

**Hardness levers (beyond expert band)**: provisional-vs-determined federal share (interstate bump, safety 100% override, land sliding scale with cap); chronological vs forward-looking apportionment availability producing opposite verdicts on identical rows; per-line-then-sum rounding pinned (105+105 @ 0.90 → 190, not 189); cumulative change-order participation cap with pinned evaluation order; depth-3 closeout cascade (repayment → audit close → deobligation → apportionment availability); two compensating invariants (apportionment identity, net federal outlay identity); half-open voucher periods vs closed-interval STIP windows; state-beats-fiscal and compliance-beats-temporal priority pairs.

**Self-audits run**: every `CONST.*` reference resolves to the constants block (the `BASE_SHARE_<code>` template expands over all five defined codes); zero forbidden concurrency vocabulary; all 23 fixture timestamps ≥ the 2026-09-01T00:00:00Z clock default; 84 unique instance names across both design files; all `grounds:` resolve; domain anchored on `/federal-aid` throughout (no foreign-domain drift). One latent dead check was caught and removed pre-lint (`ERR_AUTHORIZATION_EXISTS` was shadowed by the ELIGIBLE state gate), and the body-FK existence check was pinned to run *after* the path resource's state gate so the `award_while_bidding` corner returns `ERR_INVALID_STATE` rather than 404.

## Step 3: Copy shared files — 2026-10-02T18:40:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/workspace/INSTRUCTION.md`.

Orchestrator verification of Step 2 artifacts (independent of subagent report): all three YAMLs parse; difficulty non-stub = 19 (9 rules), corner = 65 total / 61 non-stub (stubs: authorization_fully_drawn_on_exact_draw, layer_dual_variant_calculation, layer_cascading_side_effects, layer_rate_threshold_triggers); endpoints = 40; api_prefix = /federal-aid (131 anchors). Total test-queue size = 80 instances.

## Step 4: Generate PRD — 2026-10-02T18:55:00.000Z

Verbatim subagent summary:

All contracts pass. The PRD is complete and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/workspace/PRD.md` — 324 lines.

**Structure**: §1 Introduction (2 paragraphs, business-context angle) · §2 with 10 domain-derived subsections (RBAC, verbatim §2.2 response structure, pagination, logical clock/FFY/timestamp-rendering, common resource properties, money/rounding, validation ordering, OCC, nested retrieval, apportionment ledger invariants) · §3 with 9 lifecycle-stage subsections (fiscal foundation → STIP/public involvement → nomination & dual share variants → clearances → authorization → bidding/award → vouchers → change orders → closeout audit) · §4 endpoint table (4 columns) · §5 error catalogue (2 columns). Document ends at §5 with no audit footer.

**Contract reports**:

```
Field coverage check:
- entities[].fields: 71 required, 71 present, 0 missing
- endpoints[].request_body/input: 47 required, 47 present, 0 missing
- endpoints[].query_params (optional filter params): 20 required, 20 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: all 32 expressed as an explicit 32-step succession in §2.7, with the two decisive orderings called out (STIP submit: participation 15 outranks window 16; award: DBE 14 outranks bid family 25–27; pool-empty 25 → named-bid 26 → lowest 27)
- concurrency_rules[] OCC: 1 checked, 1 expressed (PATCH project requires expected_project_version; mismatch → ERR_STALE_VERSION 412; no other endpoint takes a version field)
- state_machines[].transitions: all 8 machines fully expressed, including cyclic edges (APPROVED→PUBLIC_INVOLVEMENT amendment loop, FULLY_DRAWN→OBLIGATED, REJECTED→UNDER_REVIEW resubmission) and all system-triggered transitions (ELIGIBLE→AUTHORIZED, UNDER_CONSTRUCTION→COMPLETE, COMPLETE→CLOSED_OUT, OBLIGATED→FULLY_DRAWN, auto-close at FINAL when repayment_due is 0)
- calculations[]: 7/7 expressed in precise prose (dual share variants with pinned branch order and 4-decimal half-up rounding; both apportionment_availability variants; fiscal constraint with equality-passes boundary; per-line-then-sum voucher rounding with the 95+95=190 counterexample; 4-step change-order cap with 0.20 constant; lowest-responsive selection with submission_seq-only tiebreak; ledger reconciliation with both pinned invariants)
- validations[] conditions: 32/32 matchable to error_ids in §2.7/§3 prose
- endpoints[].side_effects / applies_to: 40/40 expressed in workflow narratives
- entities[].fields[] structured content: defaults, nullability, computed-vs-input sources, and the PublicComment exception (only id + created_at; no updated_at/version) all stated
- sibling-branch symmetry: APPROVE/REJECT branches, CLEARED/REJECT branches, OBLIGATED/FULLY_DRAWN→CLOSED legs all rendered at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 497
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Pinning confirmations**: (a) all 32 scaffold error_ids appear verbatim at least once (scaffold header comment says 33 but the catalog lists 32 rows — all 32 covered); (b) every named constant appears with its concrete value (clock start `2026-09-01T00:00:00Z`, 4-year STIP span, 30/45/21/30-day windows, 1-comment minimum, 0.80/0.80/0.90/0.80/0.80 base shares, 0.10 bump / 0.90 cap, 1.00 safety share, 0.05 land threshold / 0.95 cap, 0.20 overrun cap, all 6 activity codes and 5 program codes); (c) all 40 endpoints documented in the §4 table, including the unprefixed `/_clock/set_current_utc` platform endpoint. Boundary inclusivity is stated per gate (equality passes on availability/fiscal/DBE/21-30-45-day windows; strictly-greater on the 0.05 land threshold; half-open voucher periods with adjacency allowed; closed STIP intervals where a shared boundary year is an overlap). The two timestamp families are distinguished explicitly (3-fraction-digit `created_at`/`updated_at`/`api_request_timestamp` vs clock-read domain timestamps). The two withheld design files were never opened.

Orchestrator verification of Step 4 output (independent): PRD.md = 324 lines; 32/32 scaffold error_ids found verbatim; `/_clock/set_current_utc` documented unprefixed; clock-start constant present.

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T19:21:00.000Z

Verbatim subagent summary:

Stage 1 (helpers) is complete and verified. Summary:

## Files written — all under `/home/ubuntu/github/CodingPRD/tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/test_helpers/`

| File | Lines | Contents |
|---|---|---|
| `constants.py` | 207 | Clock start `2026-09-01T00:00:00Z`, all PRD windows (30/45/21/30 days), share table (0.80/0.80/0.90/0.80/0.80), interstate bump/cap, safety override + activities, land threshold/cap, overrun cap 0.20, plus pinned computation helpers (`expected_determined_share`, `expected_voucher_reimbursable`, `expected_change_order_participation`, `federal_fiscal_year`, `iso_plus_days`, `max_iso`, `round_half_up`) — all Decimal-based |
| `types.py` | 294 | 15 enums (roles, statuses, kinds, decisions) + 11 entity TypedDicts; PublicComment correctly omits `updated_at`/`version` (PRD §2.5 exception) |
| `api_client.py` | 255 | `ApiClient(GenericApiClient)` with exactly 40 endpoint methods; `/_clock/set_current_utc` is unprefixed, everything else under `/federal-aid`; base URL from `API_BASE_URL` then `$PORT` fallback |
| `api_errors.py` | 78 | All 32 `ApiErrorId`s + HTTP map from PRD §5, registered via `set_error_http_status_map` at import |
| `assertions.py` | 301 | Per-entity `assert_*` (11), two timestamp-family helpers (`assert_bookkeeping_timestamp` = exactly 3 fraction digits; `assert_clock_timestamp` = exact clock-string equality), `assert_apportionment_invariant` (I-APPORTION), `assert_closeout_net_share_invariant` (I-NETSHARE) |
| `factories.py` | 312 | One payload factory per write endpoint, input fields only (21 factories incl. line-item/bid-entry builders) |
| `test_users.py` | 85 | `TEST_USERS` with the 5 roles + `_alt` engineer/reviewer pairs for the two X-User-ID segregation-of-duties gates; per-role `make_*_headers` builders |
| `fixtures.py` | 806 | Tiered composites, all API-only, clock threaded forward monotonically |
| `__init__.py` | 30 | Barrel export of framework + PRD-specific surface |

## Helper API surface Stage 2 should call
- **Lifecycle chains:** `create_submitted_stip` / `create_approved_stip` → `setup_stip_pipeline` (program + apportionments + projects + APPROVED) → `determine_project_eligible` / `clear_project` / `authorize_project` → `progress_project_to_under_construction` / `setup_project_under_construction` → `create_approved_voucher`, `setup_project_complete` → `create_audit` / `setup_audit_issued` / `setup_finalized_audit` / `setup_closed_out_project`; `setup_fully_drawn_authorization` (HSIP 0.90, lines [105,105] → 190 == obligated)
- **Change orders:** `create_change_order` (primary engineer) → `concur_change_order` (alt engineer, SoD-safe) → `federal_decide_change_order`; `create_approved_change_order`
- **Leaf helpers:** `set_clock`, `create_funding_program`, `create_apportionment`, `select_winning_bid`, `list_bids`, `submit_voucher(revisions=...)`, `decide_voucher(ineligible_line_indexes=...)`

## Verification (all from the task dir, `PYTHONPATH=$PWD`)
1. `python3 -m py_compile test_helpers/*.py` → OK
2. `importlib.import_module` on all 9 modules → all OK (importlib used, not the singleton-shadowing form)
3. Surface assertions: 32 error ids + 32 mappings; exactly 40 ApiClient methods (set-equality check); `validate_success` carries explicit `expected_status`
4. Frozen math checked against the design index's pinned values: HSIP+land-0.40 → 0.92, safety override → 1.00, interstate cap → 0.90, land 0.05 → 0.80, per-line rounding 95+95=190, change-order cap 200,000 then 0, final-eligible 360,000, FFY rule, all clock arithmetic
5. Barrel export: all 96 expected names present; zero "scaffold" references in generated code

## PRD ambiguities resolved (frozen)
- **Clock is write-only** (no GET) → fixtures thread explicit dates; milestones carry 1-day slack except EIS which uses exactly 45 days (boundary passes per PRD "exactly 45 days passes"); EIS raises the authorization clock to keep movement monotonic (stays in FFY 2027).
- **Error count:** scaffold header says "33 errors" but §1.6 and PRD §5 both enumerate exactly 32 — froze 32.
- **Base URL:** `API_BASE_URL` (runner-injected) first, `http://localhost:$PORT` fallback.
- **Empty-body actions** (submit/advertise/finalize/state-concur/open-amendment) send `{}` rather than no body.
- **Creates return 201:** fixtures use lenient `get_success_data`; nothing hardcodes 200 — Stage 2 must pass `expected_status=201` to `validate_success` for the 10 create endpoints.
- **All roles opaque** (PRD §2.1: X-User-ID never compared to resource ids) — SoD handled purely via distinct user-id pairs, matching the design index's `as_user_id` markers (`eng_req`/`eng_concur`, `fhwa_rev_m`/`fhwa_rev_a`).

Orchestrator verification of Step 5a output (independent): all 9 files present; py_compile clean; importlib import of all 9 modules OK; CLOCK_START and OVERRUN_PARTICIPATION_CAP_PCT=0.20 match PRD.

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T19:55:00.000Z

Verbatim subagent summary:

Stage 2 is complete and fully verified. Summary:

## Files written (24, one Write per file)

`/home/ubuntu/github/CodingPRD/tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/test_suite/`:

| File | Tests | Queue coverage |
|---|---|---|
| conftest.py | 0 | api + 7 role-header fixtures |
| test_01_difficulty_dual_variant_calc.py | 2 | Difficulty/dual_variant_calc |
| test_02_difficulty_combinatorial_formula.py | 3 | Difficulty/combinatorial_formula |
| test_03_difficulty_state_machine_cycles.py | 2 | Difficulty/non_linear_state_machine |
| test_04_difficulty_transitive_cascade.py | 2 | Difficulty/transitive_cascade |
| test_05_difficulty_priority_pairs.py | 2 | Difficulty/priority_pair_validation_conflict |
| test_06_difficulty_boundary_precision.py | 2 | Difficulty/boundary_precision_check |
| test_07_difficulty_cross_entity_state.py | 2 | Difficulty/cross_entity_state_dependency |
| test_08_difficulty_temporal_overlap.py | 2 | Difficulty/resource_temporal_overlap |
| test_09_difficulty_compensating_invariant.py | 2 | Difficulty/compensating_invariant |
| test_10_corner_entities_core.py | 7 | Corner/entities |
| test_11_corner_entities_projects.py | 6 | Corner/entities |
| test_12_corner_sm_stip.py | 5 | Corner/state_machines |
| test_13_corner_sm_clearances.py | 3 | Corner/state_machines |
| test_14_corner_sm_bids_award.py | 5 | Corner/state_machines |
| test_15_corner_sm_voucher_co_auth.py | 3 | Corner/state_machines |
| test_16_corner_calc_share.py | 3 | Corner/calculations |
| test_17_corner_calc_money.py | 4 | Corner/calculations |
| test_18_corner_auth_rbac.py | 4 | Corner/validations (3) + Corner/rbac (1) |
| test_19_corner_occ.py | 2 | Corner/validations |
| test_20_corner_authorization_gates.py | 4 | Corner/validations |
| test_21_corner_voucher_gates.py | 5 | Corner/validations |
| test_22_corner_award_audit_gates.py | 6 | Corner/validations |
| test_23_corner_envelope_consistency.py | 4 | Corner/endpoints (3) + Corner/consistency_model (1) |

**Total: 80 tests = 19 difficulty + 61 corner non-stub, one per instance.**

## Verification results
- `py_compile test_suite/*.py`: clean.
- `pytest --collect-only` (PYTHONPATH=$PWD, no server): **80 collected** — import graph sound.
- AST tag audit (real `ast` parse, tags diffed against both YAMLs): emitted 80, expected 80, **missing 0, orphan 0, duplicate 0**; the 4 `excluded_because` stubs (endpoints/authorization_fully_drawn_on_exact_draw + 3 cross_cutting_layers) correctly have no test. Tag is the last docstring line in all 80.
- Verbatim-citation sweep: every quoted PRD sentence in every docstring survives whitespace-normalized literal grep of PRD.md (one lowercase-`A` typo found and fixed).
- No `skip`/`skipif`/`xfail`, no scaffold references. All 33 error ids asserted are named in PRD prose. Skipped instances: **none** — every instance passed the two-condition filter.

## Recipe re-derivations (setup-side only; no asserted outcome changed)
1. **Fiscal-constraint reachability (systemic).** Any recipe that nominates projects before STIP approval but creates no Apportionment rows is unreachable per PRD §3.2 (capacity 0 < programmed → ERR_FISCAL_CONSTRAINT_VIOLATED before the trigger). Repaired by adding state-consistent capacity cells sized to cover programmed estimates: Difficulty `provisional_vs_determined...` (CA/2027 10,000,000), Difficulty `safety_override...` (CA/2027 5,000,000), Corner `interstate_share_capped...` (UT 5,000,000), Corner `land_adjustment_skipped...` (CO 5,000,000); pipeline-fixture users inherit its default {2027: 5,000,000} cell.
2. **`change_order_draw_blocked_when_apportionment_short`**: recipe's project cost 1,500,000 (prov 1,200,000) exceeds its own 1,100,000 apportionment, so approval would fail before the change order exists. Re-derived cost to 1,000,000 (prov 800,000 ≤ 1,100,000); the asserted 200,000-vs-100,000 shortfall (driven by initial_obligated 1,000,000) is untouched.
3. **`authorize_without_apportionment_row_returns_no_cell_error`**: "no Apportionment rows at all" is unreachable with a counted project (approval would fail). Repaired with a single FFY-2028 row: approval passes, and the clock's FFY-2027 cell at authorization stays missing → the asserted ERR_NO_APPORTIONMENT_FOR_FFY holds.
4. **`stip_amendment_cycle_requires_fresh_comment_window`** (the one PRD-vs-recipe assertion conflict): after open-amendment resets `comment_period_opened_at`, the original comment no longer counts, and PRD §2.7 explicitly pins participation (15) ahead of the window (16) — so the recipe's bare immediate-resubmit would uniquely yield ERR_PUBLIC_INVOLVEMENT_INCOMPLETE, not its asserted ERR_COMMENT_PERIOD_OPEN. Resolved per PRD by recording one fresh in-window comment before the immediate submit, which isolates the window gate and preserves the instance's asserted error and distinguishing aspect.

No PRD contradictions were left as gaps; all four items above are reflected in the shipped tests with the PRD sentence governing the assertion.

Orchestrator verification of Step 5b output (independent): AST tag audit re-run from scratch — expected 80, emitted 80, missing 0, orphan 0, duplicate 0, no dual-tagged tests; `pytest --collect-only` = 80 collected; test_helpers/ mtimes all ≤19:21 (untouched during 5b — freeze held).

## Step 6: Generate implementation — 2026-10-02T20:20:00.000Z

Verbatim subagent summary:

All processes cleaned up and the deliverable is complete. Here is the final report.

## Implementation complete: task_3495

### File tree (all under `/home/ubuntu/github/CodingPRD/tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/workspace/implementation/`)

```
start.sh                  10   guarded pip install + exec python3 app.py
requirements.txt           1   flask>=3.0,<4
app.py                     67   app assembly, 10 blueprints, 404/405/Exception envelope handlers
db.py                      78   in-memory STORE (11 dicts), logical clock, dashed uuid4 ids, touch()
errors.py                  51   ApiError + full 32-entry error catalog with HTTP statuses
response.py                37   success/error envelope builders (meta/response_type/data)
middleware.py              42   require_roles decorator (401 ERR_UNAUTHENTICATED / 403 ERR_FORBIDDEN)
helpers.py                129   body-shape validators, pagination (limit/offset), FFY rule, body-FK resolver
calculations.py           189   all 7 calculation rules + named constants (Decimal, ROUND_HALF_UP)
serializers.py            190   explicit per-entity serializers (internal _-keys never leak)
routes_platform.py         20   POST /_clock/set_current_utc (UNPREFIXED)
routes_funding.py         122   funding-programs POST; apportionments POST/GET/GET-list
routes_stips.py           198   STIP CRUD lifecycle, submit/decide/open-amendment, comments POST/GET
routes_projects.py        206   projects POST/GET/list/PATCH(OCC)/determine-eligibility
routes_bidding.py         133   advertise, open-bids, award, bids list
routes_clearances.py      118   clearances POST/decide, project clearances list
routes_authorizations.py  153   authorizations POST/GET/list
routes_vouchers.py        293   vouchers POST/submit/decide, authorization vouchers list
routes_change_orders.py   137   change-orders POST/state-concur/federal-decide, CO list
routes_audits.py          205   audits POST/issue-findings/finalize/record-repayment, audits list
```

### Verification evidence

- **Compile**: `python3 -m py_compile` on all 18 .py files → `COMPILE OK`.
- **Route table**: app introspection shows exactly 40 endpoints — 39 under `/federal-aid` + unprefixed `POST /_clock/set_current_utc`. Prefixed clock path correctly 404s.
- **Smoke test** (booted via `bash start.sh` on a dynamic free port, saved and killed exactly my own PIDs): `/tmp/smoke_3495.py` ran a full two-project lifecycle → `ALL SMOKE CHECKS PASSED`. Covered: 401/403/404 envelopes; clock set/echo; program share pinning; duplicate-apportionment 409; STIP overlap (shared boundary year rejected); submit precedence (ERR_PUBLIC_INVOLVEMENT_INCOMPLETE before ERR_COMMENT_PERIOD_OPEN); amendment cascade on project-create-into-APPROVED; fiscal-constraint fail→add capacity→approve; share variants (NHPP land-slide 0.845, HSIP safety override 1.0); nepa_class conditional-field 400s; EIS 45-day gate; clearance-kind uniqueness + replacement-after-REJECT; ERR_APPORTIONMENT_EXCEEDED; ERR_PROJECT_NOT_ELIGIBLE on second authorization; advertisement 21-day gate; DBE-before-bid-family precedence (422 ERR_DBE_GOAL_NOT_MET masking a bad named bid); ERR_BID_NOT_RESPONSIVE / ERR_AWARD_NOT_LOWEST_RESPONSIVE; per-line rounding (999895 × 0.845 = 844911); billing-period overlap + adjacency-allowed; resubmission_count; doc-incomplete 422; final-voucher uniqueness; SoD on state-concur and audit creation; CO cap clamp (participation 80000 of eligible 100000); FULLY_DRAWN → voucher-intake 409 → CO reopens to OBLIGATED; LEVEL_2_CONDITIONAL blocking final voucher (ERR_ROW_NOT_CERTIFIED outranking ERR_OPEN_CHANGE_ORDERS); audit window gate; repayment overpay 422; closeout cascade arithmetic (obligated 8845000 → 2450411, cell released, project CLOSED_OUT).
- **Guard audit**: every helper has ≥1 callsite (grep-verified); resource ids use `str(uuid.uuid4())` (dashed) — `uuid4().hex` appears only for `req_` request ids.
- **Fresh-boot contract**: second boot on a new port showed empty store (`total_count: 0`), working clock endpoint, correct 401 envelope.

### Interpretations chosen

1. **Pagination bounds** (PRD §2.3 "minimum of 1 … capped at a maximum of 100"): out-of-range `limit`/`offset` are *clamped* (limit→[1,100], offset→≥0), not rejected; non-integer query values → ERR_INVALID_REQUEST. `helpers.py:95` (`pagination_params`), `query_int`.
2. **Missing X-User-ID** (PRD §2.1 requires both headers but the catalog only penalizes role failure): only `X-User-Role` is validated; a missing `X-User-ID` records `null` in attribution fields, never an error. `middleware.py:20`.
3. **Body-FK vs body-shape order on plain creates** (priority 3 < 4; §2.9 "before all business rules"): a *present* but unresolvable FK → 404 before required-field/type checks; an *absent* FK → 400. All `create_*` handlers.
4. **Award body-FK placement** (§2.9 carve-out): state gate (6) → bid_id resolution (404) → DBE (14) → pool (25) → belongs-to-project+responsive (26) → lowest (27). A bid_id belonging to a *different* project → ERR_BID_NOT_RESPONSIVE; a wholly nonexistent id → 404. `routes_bidding.py:93-131`.
5. **ineligible_line_indexes scope**: validated (400) only when `decision=APPROVE` and present; ignored on REJECT (field stays null). On APPROVE without the field, stores `[]` (reading "null until decided" as non-null after an approval). Duplicates treated as a set. `routes_vouchers.py:222-243`.
6. **good_faith_effort_documented** default: False when absent or null; non-bool → 400. `routes_bidding.py:97-102`.
7. **row_cert_level on non-ROW/REJECT decides**: ignored, not rejected (PRD only requires presence for CLEARED+RIGHT_OF_WAY). `routes_clearances.py:81-87`.
8. **state_code "two-letter"**: descriptive only; string-type enforced, no length check (no error_id exists for it).
9. **FundingProgram code uniqueness**: not enforced — no PRD sentence or error_id supports it.
10. **Version bumps on compound operations**: one request = one mutation per affected resource = exactly one version increment per resource. The finalize-with-auto-close path touches the audit once despite FINAL→CLOSED happening in one operation. `routes_audits.py` + `db.py:touch`.
11. **Clock set semantics**: echoes the supplied string verbatim as `current_utc`; raw string stored so domain timestamps (`comment_period_opened_at`, `advertised_on_date`, `findings_issued_at`, `closed_at`) render exactly as the clock read (PRD §2.4 family 2). No monotonicity guard invented. `db.py:_Clock`, `routes_platform.py`.
12. **api_request_timestamp source**: the logical clock (§2.4 "never consults wall-clock time"), rendered with exactly 3 fractional digits. `response.py:11`.
13. **Comment-window comparison**: comments keep the underlying clock datetime (`_created_dt`) for the `created_at >= comment_period_opened_at` comparison, so sub-millisecond clock precision can't false-exclude a comment through 3-digit truncation. `routes_stips.py:104`.
14. **Partial period revision on voucher resubmit**: effective (payload-over-stored) start/end must satisfy end > start → 400. `routes_vouchers.py:159-180`.
15. **Overlap-check sibling set**: "non-REJECTED sibling" includes DRAFT and UNDER_REVIEW vouchers, self always excluded; half-open intersection, adjacency allowed. `routes_vouchers.py:196-209`.
16. **Change-order cascade does NOT recompute `provisional_federal_estimate_cents`**: §3.3 pins recomputation to creation and cost-changing *patches*; §3.8 only grows `total_estimated_cost_cents` (+updated_at/version). `routes_change_orders.py:116-119`.
17. **Authorization.repaid_cents timing**: increments at each record-repayment (it's "sum of recorded audit repayments applied to this authorization"), not deferred to closeout. `routes_audits.py:178-179`.
18. **Repayment amount positivity**: `amount_cents` > 0 enforced as 400 ("amounts positive where required"); the outstanding-balance check is the 422. `routes_audits.py:168-170`.
19. **List ordering**: `created_at` ascending with insertion order breaking ties (stable sort — many resources share one logical instant); bids list explicitly sorted by `submission_seq` per §3.6.
20. **FULLY_DRAWN→OBLIGATED only on real headroom**: a 0-participation approval (cap exhausted) on a FULLY_DRAWN authorization leaves it FULLY_DRAWN ("raises obligated_cents above reimbursed_cents"). `routes_change_orders.py:107-112`.
21. **405 responses**: return the ERR_NOT_FOUND envelope with 404 (PRD silent). `app.py:52`.

### PRD contradictions found

- **I-NETSHARE vs the reimbursement clamp** (§2.10 vs §3.7): the invariant `reimbursed − repaid == final_eligible_federal_share_cents` at closeout is arithmetically unsatisfiable when a voucher's reimbursement was clamped by the remaining-obligation cap below the audited eligible share (e.g. eligible 200 × 0.8 = 160 but only 100 obligated-remaining → reimbursed 100; finalize then computes final_eligible 160, due 0, and closeout sets obligated := 100 ≠ 160). Resolution: implemented the pinned formulas literally (net = reimbursed − repaid) rather than forcing the invariant.
- **EIS window on REJECT**: scaffold places the 45-day gate only on the CLEARED transition while §3.4's prose sits under "a decision of CLEARED carries two kind-specific gates" — consistent; applied only to CLEARED (REJECT of an EIS clearance is immediate).

### Deliberately unimplemented PRD behavior

None.

Orchestrator verification of Step 6 output (independent): 18 .py files + start.sh + requirements.txt present; py_compile clean; resource ids use str(uuid.uuid4()) dashed (only req_ envelope ids use .hex); clock route unprefixed in routes_platform.py:13.

## Step 7: Test-fix iteration loop — 2026-10-02T21:00:00.000Z

Verbatim subagent summary:

Clean 8-round parallel sweep achieved. Summary:

**Iterations run:** 2 (round 1: 6 deterministic failures, 74/80 in all 8 rounds; round 2 after fixes: 80/80 in all 8 rounds).

**Tests deleted:** none — every failing test traced to a verbatim PRD rule with a uniquely determined outcome; all fixes were test-artifact bugs.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3495_federal_aid_highway_project_authorization_reimbursement/test_helpers/fixtures.py` — `setup_project_complete`: re-fetch the project via `api_client.get_project` after the final-voucher approval. The fixture's own contract ("project lands COMPLETE" per PRD §3.7) was violated by returning the stale pre-voucher snapshot; this unblocked `test_record_repayment_cascades_through_authorization_to_apportionment`.

**Fixes applied to `test_suite/`:**
- `test_03_difficulty_state_machine_cycles.py` and `test_22_corner_award_audit_gates.py` — added the missing `get_success_data` import (a framework helper exported by `test_helpers`); fixed the NameError in 3 tests (`test_stip_amendment_cycle_requires_fresh_comment_window`, `test_award_with_zero_responsive_bids_returns_no_responsive_bids`, `test_record_repayment_above_due_rejected_then_exact_accepted`).
- `test_06_difficulty_boundary_precision.py` (`test_dbe_commitment_exactly_at_goal_passes_below_fails`) — project B was advertised at the clock left by A's bid-opening, then its own opening reset the clock to the same instant (0 of 21 days elapsed → ERR_ADVERTISEMENT_PERIOD_SHORT). Gave each loop iteration its own forward-only bids clock (A: 2026-11-06, B: 2026-11-28); the DBE assertions are unchanged.
- `test_08_difficulty_temporal_overlap.py` (`test_voucher_half_open_periods_adjacent_ok_overlap_rejected`) — voucher C (a DRAFT sibling whose period intersects B's) was created before B's submission, so the impl's PRD-correct sibling-overlap check rejected B. Moved C's creation to after B's accepted submission, matching the test's documented intent (adjacency accepted for B, then C rejected for intersecting A and B).

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on all 6 failures (half-open overlap math, final-voucher → COMPLETE cascade, window restamp, and award/audit gates all verified correct against PRD §3.2/§3.6/§3.7/§3.9).

**Confirmation:** all 8 final `results.{1..8}.json` files remain in `workspace/implementation/` and each shows `passed == total == 80`.

Orchestrator verification of Step 7 exit (independent): all 8 results.*.json present, each passed=80/total=80/failed=0; implementation/*.py mtimes (≤20:33) predate the final sweep (20:59) — no post-sweep impl writes; test-side fixes at 20:55–20:56 precede the passing sweep.

## Step 8: Finalize PRD — 2026-10-02T21:10:00.000Z

Verbatim subagent summary:

Byte-identity confirmed. All four step_7_diff items trace to pure test-side bugs whose behavior the PRD already uniquely pins. PRD_FINALIZED.md ships as the unmodified copy.

## Summary

**PRD.md vs PRD_FINALIZED.md**: 324 lines each, **byte-identical** (0.0% delta). `diff -q` confirms no differences. Zero edits — the permitted zero-edit outcome applies: every Step 7 fix was a test-artifact bug, and for each, the PRD prose already uniquely determines the implementation's behavior.

**Changes**: none.

### Per-item evidence log

1. **`test_helpers/fixtures.py` — `setup_project_complete` re-fetch** — verdict: **fixture-bug** (stale client-side snapshot; the fixture returned the pre-voucher project object instead of re-reading the server). PRD §3.7 already pins the cascade verbatim: *"if the voucher's `is_final` is true, the Project moves from `UNDER_CONSTRUCTION` to `COMPLETE`."* Impl confirms at `workspace/implementation/routes_vouchers.py:279-282` (`if voucher["is_final"]: project["status"] = "COMPLETE"`). The fixed fixture (fixtures.py:657-663) now re-fetches via `api_client.get_project`, matching the PRD-pinned server behavior.

2. **`test_03_difficulty_state_machine_cycles.py` / `test_22_corner_award_audit_gates.py` — missing `get_success_data` import** — verdict: **test-bug** (pure Python NameError in 3 tests; zero behavioral content, nothing for a PRD to pin or fail to pin). Import now present at test_03 line 13 and test_22 line 17. No PRD passage implicated; no impl line implicated.

3. **`test_06_difficulty_boundary_precision.py` — `test_dbe_commitment_exactly_at_goal_passes_below_fails` per-iteration bids clock** — verdict: **test-bug** (clock threading: the test set the open-bids clock 21 days after project A's advertise but 0 days after project B's own advertise, so the impl correctly raised `ERR_ADVERTISEMENT_PERIOD_SHORT` for B). PRD §3.6 pins the per-project window verbatim: *"advertises the Project, which stamps `advertised_on_date` from the logical clock … the logical clock must have reached at least 21 days after `advertised_on_date` — exactly 21 days passes — else `ERR_ADVERTISEMENT_PERIOD_SHORT` (409)"*; §2.4 pins that the clock moves only via the PlatformAdmin capability. Impl confirms: `routes_bidding.py:26-27` stamps `_advertised_dt` from the clock per project; `routes_bidding.py:51` checks `clock.dt < project["_advertised_dt"] + timedelta(days=MIN_ADVERTISEMENT_DAYS)`; `calculations.py:13` sets `MIN_ADVERTISEMENT_DAYS = 21`. Fixed test (test_06:138-141) gives each project its own forward-only clock (A: 2026-11-06, B: 2026-11-28).

4. **`test_08_difficulty_temporal_overlap.py` — `test_voucher_half_open_periods_adjacent_ok_overlap_rejected` setup ordering** — verdict: **test-bug** (ordering: DRAFT voucher C, whose period intersects B's, was created before B's submission, so the impl's PRD-correct sibling-overlap check rejected B; C's creation moved after B's accepted submission). PRD §3.7 pins the rule verbatim: *"the half-open period must not intersect the period of any non-`REJECTED` sibling voucher on the same authorization, else `ERR_BILLING_PERIOD_OVERLAP` (409)"* — DRAFT is non-REJECTED by the plain reading. Impl confirms at `routes_vouchers.py:170-182`: the submit check scans siblings with `sib["status"] != "REJECTED"` using `_half_open_overlap` (`routes_vouchers.py:44-46`).

### Per-edit pre-edit search log

No edits were committed, so no pre-edit searches were required. (Verification searches performed anyway and reported above: final-voucher → COMPLETE cascade, per-project 21-day advertisement window, and the non-REJECTED-sibling overlap check — each is the unique reading of the cited PRD passage, and no alternate code path in `implementation/` contradicts it.)

Orchestrator verification of Step 8 output (independent): `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical confirmed; both 324 lines.

## Step 9: Complete PRD — 2026-10-02T21:35:00.000Z

Verbatim subagent summary:

The PRD_COMPLETED.md is complete and verified. All 13 in-paragraph edits applied; structure, section headers, and tables intact.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 324 lines / 52,710 chars → `PRD_COMPLETED.md` 324 lines / 55,119 chars (+2,409 chars, 13 paragraphs revised inline, no new sections, not byte-identical).

**Counts:** 12 ambiguity-pins, 1 mismatch-revision.

**Changes (one bullet each):**
- §2.1 — insert — ambiguity — missing `X-User-ID` is not rejected; attribution fields record null and SoD compares recorded values as read — `middleware.py:36` (no enforcement), `routes_change_orders.py:68`.
- §2.2 — insert — ambiguity — cascade operations return the created resource for creations, the path-addressed resource otherwise (open-bids/award → Project; finalize/record-repayment → Audit) — `routes_bidding.py:73,123`, `routes_audits.py:161,195`.
- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range values clamp (limit→[1,100], offset→0); non-integer → `ERR_INVALID_REQUEST`; `created_at` ties keep creation order — `helpers.py:74-93`, stable sorts e.g. `routes_funding.py:120`.
- §2.4 — revise — ambiguity — clock `current_utc` must parse as ISO 8601 (else 400), adopted exactly as supplied with no monotonicity constraint, response data echoes the new `current_utc` — `routes_platform.py:17-20`.
- §2.7 item 4 — revise — ambiguity — null required field treated as missing; value-type checks incl. ISO 8601 parseability and non-object body; unknown top-level fields ignored, line-item objects stored/returned as supplied — `helpers.py:14-71`, `routes_vouchers.py:101`.
- §2.10 — revise — **mismatch (self-contradictory PRD)** — closeout net-share invariant now stated to hold when a repayment was due; pins the zero-due-below-share corner (see below).
- §3.2 — revise — ambiguity — `REJECT` decision leaves `amendment_count` unchanged — `routes_stips.py:137-142`.
- §3.3 — revise — ambiguity — only `description`/`total_estimated_cost_cents`/`dbe_goal_pct` patchable; other supplied fields ignored — `routes_projects.py:166-175`.
- §3.6 — revise — ambiguity — absent or null `good_faith_effort_documented` treated as false — `routes_bidding.py:83-89`.
- §3.7 — revise — ambiguity — `submitted_by_user_id` also null at creation — `routes_vouchers.py:109`.
- §3.7 — revise — ambiguity — submit payload revisions apply on first (`DRAFT`) submission too; `resubmission_count` increments only on `REJECTED` resubmission — `routes_vouchers.py:128-194`.
- §3.8 — revise — ambiguity — `state_concurred_by_user_id` null until concurrence — `routes_change_orders.py:46`.
- §3.9 — revise — ambiguity — repayment `amount_cents` must be strictly > 0 (400); each recording adds to both the Audit's and the Authorization's `repaid_cents` — `routes_audits.py:171-173,184-185`.

**IMPL BUG list:** none. Every uniquely-pinned PRD rule is implemented as written — the §2.7 succession was verified endpoint-by-endpoint (including FK-before-body on creates vs state-gate-before-FK on award per §2.9), all formulas (dual share variants, per-line voucher rounding, 4-step change-order participation, ledger reconciliation), all window equalities (30/45/21/30 days pass exactly), cascades with version/touch discipline, role tables, and 201/200 status codes match.

**Mismatch-revision justification (§2.10):** The PRD pinned three things that cannot all hold: §2.10 "when an authorization closes, its `reimbursed_cents` minus its `repaid_cents` equals the audit's `final_eligible_federal_share_cents`"; §3.7 "`federal_reimbursable_cents` is the lesser of that per-line sum and the Authorization's remaining obligation"; §3.9 "`repayment_due_cents` is the excess of `reimbursed_cents` over `final_eligible_federal_share_cents`, floored at zero" + immediate `CLOSED` when zero. The clamp can leave lifetime reimbursed below the audited share (e.g. obligated 290, share 0.90, two vouchers of two 105-cent lines → reimbursed 190+min(190,100)=290, approved total 420 → final_eligible 378 > 290 → repayment_due 0 → closes with net 290 ≠ 378). No implementation can satisfy all three; the impl follows every pinned formula, so the invariant claim was softened to the repayment path and the corner pinned.

**Over-guard list:** repayment `amount_cents > 0` (`routes_audits.py:172-173`), non-integer `limit`/`offset` → 400 and clamping (`helpers.py:81-92`), non-object JSON body → 400 (`helpers.py:20-21`) — all three resolved by pinning into §3.9/§2.3/§2.7. Also observed, not request-content rules so not pinned: catch-all 500 `ERR_INTERNAL` (`app.py:53-55`, outside the 4xx-scoped §5 catalog) and the 405→404 remap (`app.py:49-51`).

**Dead-code audit:** all 32 catalog error_ids have live raise sites (grep-verified, errors.py excluded). Every PRD-named gate traced to a live callsite: both SoD checkpoints, fiscal constraint, DBE + full bid family, both final-voucher gates, all four time windows, all four uniqueness rules, both apportionment fiscal checks, the FULLY_DRAWN↔OBLIGATED cycle, and `recompute_cell` at all three mutation points. No defined-but-uncalled or called-but-undefined checks.

**Nullable-field audit:** every PRD-nullable field's reads are safe — internal datetime/share reads (`_advertised_dt`, `_determined_share_dec`, `_findings_dt`, `repayment_due_cents`, `eligible_amount_cents` in finalize, `nepa_class`/`row_cert_level` in gate chains) are all behind state gates that guarantee the field was set, or are None-safe equality comparisons; serializers emit null without dereferencing. No crash paths on PRD-legal nulls.

Orchestrator verification of Step 9 output (independent): PRD_COMPLETED.md = 324 lines / 55,119 chars (+2,409 delta matches report exactly); `diff -q` vs PRD_FINALIZED confirms real edits (not a silent no-op); implementation/ mtimes unchanged (≤20:33 — Step 9 made no impl edits, so no Step 9b fix-and-re-sweep needed; the §2.10 revision is an exonerated self-contradiction adjudication, not an impl violation); all 8 results.*.json still present, each passed=80/total=80/failed=0.
