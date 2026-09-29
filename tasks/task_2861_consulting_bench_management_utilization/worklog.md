# Worklog — task_2861_consulting_bench_management_utilization

## Step 1: Create task directory — 2026-09-05T07:54:58.483Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2861_consulting_bench_management_utilization/` and its `workspace/` subdirectory. Index 2861 was pre-assigned by the orchestrating prompt (no scan of ./tasks/ performed, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T10:03:40.717Z

All three scaffold artifacts are complete and lint-clean.

### Output files
`/home/ubuntu/github/CodingPRD/tasks/task_2861_consulting_bench_management_utilization/`
- `SCAFFOLD.yaml` — 3168 lines / 175 KB (§1.0–§1.7 + preamble; no `scaffold_difficulty_design` or `scaffold_corner_design` keys — verified top-level keys are only scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2011 lines / 139 KB (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4359 lines / 307 KB (single top-level key `scaffold_corner_design`)

All three parse under PyYAML and end at a real YAML boundary (last line is a complete quoted `assert:` item / role string).

### Scaffold surface
13 entities · 8 state machines · 10 calculations (2 dual-variant) · 44 validations in one total priority order (1 UNAUTHENTICATED → 44 EXTERNAL_SOURCING_CAP_EXCEEDED) · 63 endpoints · 56 error codes · 5 roles (4 opaque + `Consultant` = `entity_backed:Consultant`) · 2 concurrency rules. Complexity profile: `quota_allocation` / `compliance_audit`, layers [selector_policy, cascading_side_effects, dual_variant_calculation, optimistic_concurrency], topology `flat`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, difficulty `beyond_expert`.

### Instance counts
- §1.8 difficulty: **25 instances** across 9 rule_ids (dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2).
- §1.9 corner: **83 instances** — 67 full recipes + 16 `excluded_because` stubs — across all nine legal sections: entities 12, state_machines 11, calculations 17, validations 24, endpoints 5, errors 3, rbac 5, cross-cutting complexity layers 5, consistency model 1.
- 108 instance names total, all unique across the union of both files.
- All 16 stub `difficulty_instance` references resolve to real §1.8 `rule_id / name` pairs.

### Coverage audit
- **Error catalog: 56/56 triggerable — 0 missing**, and all 56 are reachable from the corner file alone (the three grouped `errors` sweeps close out the 13-code 404 catalog plus the nested/action path-before-body ordering).
- Every §1.7 role covered on both sides of the matrix: ERR_UNAUTHENTICATED (3 defect shapes incl. an unbacked entity id), ERR_UNAUTHORIZED (6 cross-role attempts incl. ResourceManager on `GET /discount-approvals`), ERR_NOT_RESOURCE_OWNER (all 5 endpoints in priority 6's applies_to), a positive per-role instance, and a segregation-of-duties instance proving the check keys on X-User-ID rather than the role header.
- Both §1.2.1 concurrency rules have a dedicated OCC instance on their declared `write_endpoint`/`occ_field`, each also asserting 404-before-412 (priority 5 before 7) and per-write version increments.
- `selector_policy` covered by a three-run auto-staff re-evaluation instance; `cascading_side_effects` and `dual_variant_calculation` deferred to §1.8 via stubs.

### Lint
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(63 endpoints, 13 entities, 25 §1.8 + 67 §1.9 instances, 1077 calls scanned; clean on the first run — no iterations needed.)

### Orchestrator post-step action
The subagent flagged that `SCAFFOLD.yaml`'s `scenario:` value still began with the literal difficulty directive line `Generate task harder than expert level!`. The orchestrator stripped that line from `SCAFFOLD.yaml` (leaving the scenario text itself verbatim) so it cannot reach PRD.md via the doc generator. Verified: `grep -rn "harder than expert"` over the task dir now returns nothing, and all three YAMLs still parse under PyYAML with unchanged top-level keys.

## Step 3: Copy Shared Files — 2026-09-05T10:04:05.749Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T10:22:10.000Z

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2861_consulting_bench_management_utilization/workspace/PRD.md` — **492 lines**, final section heading **`## 5. Error Code Catalogue`** (a complete 56-row table; the file ends at a real section boundary, not mid-sentence). Written incrementally: one `Write` plus five `cat >> … <<'PRDEOF'` heredoc appends. Scratch work confined to `/tmp/task_2861_prd/`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

**Sections emitted**

- `# Consulting Bench Management API — Product Requirements Document`
- §1 Introduction (3 paragraphs: bench as cost and surge capacity, the four-role separation of decisions, immediate consistency plus the logical clock as the two through-lines)
- §2 Global Specifications & System-Wide Principles — 11 domain-derived subsections: 2.1 RBAC (5 roles, 4 opaque identities, entity-backed `Consultant`), 2.2 API Response Structure (pasted byte-identical from the skill file), 2.3 Pagination, 2.4 Common Resource Properties (HiringForecast as the sole exception), 2.5 Logical Clock / Date Formats / all six interval conventions, 2.6 Numeric Precision and Rounding (exhaustive 2-dp / 4-dp / integer field lists), 2.7 Existence Resolution and Left-to-Right Path Validation (all 13 404 codes), 2.8 OCC on Parent Versions (both rules), 2.9 The Validation Precedence Ladder (all 44 rungs numbered, each with check, scope, error id and status), 2.10 Practice Posture and the Bench-Ratio Rollup (per-key `level_targets` fallback plus the five-level default table), 2.11 Segregation of Duties and Tiered Fiscal Authority
- §3 Business Logic & Workflows — 9 subsections organised by business-process timeline: 3.1 hierarchy and skill taxonomy, 3.2 hiring and skill assertions, 3.3 demand pipeline, 3.4 staffing branch and coverage (cyclic `staffing_status`), 3.5 internal staffing (match score, auto-staff selector, six-hop release cascade), 3.6 partner sourcing and external placements, 3.7 rate realization and the discount approval ladder (seven-step pass, both S3 variants, four-hop cascade, revise cycle), 3.8 the cyclic bench spell (aging ladder, reskilling, internal projects, separation), 3.9 measurement (operations checkpoint, utilization periods, hiring forecasts with both bases)
- §4 Endpoint Definitions — intro paragraph plus a 4-column table, all 63 endpoints
- §5 Error Code Catalogue — 2-column table, all 56 error IDs

**Coverage:** 13/13 entities, 63/63 endpoints (paths and role lists verified against the scaffold — no missing, no extras), 44/44 validations, 56/56 error codes with statuses verified to match the scaffold, 10/10 calculations including all 4 variant pairs, 8/8 state-machine entries over 7 entities, both OCC rules, all field-level defaults, all enum values, and all state names.

Three scaffold self-contradictions were resolved in favour of the majority/authoritative source and are worth flagging for Step 4+: (1) `provisional_realization_pct` — followed §1.3 S2 (`requested / standard`) over the entity description (`100 − discount_pct`); (2) staffing-mode selection — followed the state machine's `QUALIFIED`-only guard over validation rung 8's "QUALIFYING or QUALIFIED"; (3) external placement `bill_rate_usd_per_hour` — followed the entity field and the state machine (0.00 while `REQUESTED`, set to the demand's `effective_rate_usd_per_hour` on approval) over the endpoint side-effect's markup formula, and described `markup_pct` as the recorded contractual term.

**Hard Contract reports**

1. **Field-Name Coverage: PASS.** 156 scaffold identifiers extracted (entity fields, endpoint request-body fields, query parameters, path parameters) and diffed against every backticked token in PRD.md, twice — once with a naive extractor and once after stripping the §2.2 fenced JSON block that had skewed backtick pairing. 147/147 API-visible identifiers appear verbatim in backticks, including `periodId`, `current_utc`, `expected_consultant_version` and `expected_opportunity_version`. The 9 residual names are the scaffold's internal `calculations[].name` labels (`consultant_availability`, `auto_staff_selection`, `opportunity_coverage`, `bench_aging_escalation`, `practice_posture_rollup`, `utilization_period_metrics`, `rate_realization`, `discount_tier_and_margin`, `weighted_pipeline_demand`) — not fields, bodies, query params or path params, so out of scope; their semantics are all narrated in prose. `match_score`, which is both a calculation name and a field, is present.
2. **Rule Coverage: PASS.** All 44 validation priorities appear as numbered rungs in §2.9 with their scope and error id; both OCC rules with their 412 codes; every cross-entity cascade (the six-hop release chain, the four-hop discount-approval rate chain, the `WON`/`LOST` closure cascades, the separation and graduation cascades, the checkpoint sweep); every `applies_to` scope rendered in capability terms; every field-level default (verified individually for `external_sourcing_cap_pct` 20.00, `scarcity_index` 0.5000, `travel_max_nights_per_week` 3, empty `level_targets`, `cooldown_days` 3, `markup_pct` 15.00, `approval_status` `APPROVED`, `holiday_hours` 0.00, `basis` `WEIGHTED`, `retired`/`travel_willing_international`/`is_international` false, empty `industry_experience`); and both sibling branches of every symmetric pair (INTERNAL vs EXTERNAL staffing, `ESCALATED_L1` vs `ESCALATED_L2` entry into reskilling and internal projects, approve vs reject, `TARGET_BASIS` vs `AVAILABLE_BASIS`, `WEIGHTED` vs `COMMITTED`, `MIX_WEIGHTED` vs `LEVEL_FLOOR`, `BOOKED` vs `EARNED`). All 56 error ids are also referenced in §1–§4 prose, not only in the §5 table. No pseudocode: a scan for `>=`, `<=`, `==`, `:=`, `round(`, `ceil(`, `SUM(`, `IN {`, `!=` returns zero hits outside the §2.2 JSON envelope, and no fuzzy quantifier ("approximately", "roughly", "conservatively") appears anywhere.
3. **§3 Path Purity: PASS.** Every backticked token between `## 3.` and `## 4.` was extracted and tested: none begins with `/`, none is a bare `GET`/`POST`/`PATCH`/`PUT`/`DELETE`, and none combines a method with a path. §3 refers to operations only by state transition, actor role, or business capability ("the operations checkpoint", "qualification by a `SalesLead`", "the automatic selector"); the same discipline was applied to the `applies_to` phrasing in §2.9.

**Orchestrator truncation check:** `wc -l` = 492; `tail -25` shows the §5 error table completing on `ERR_EXTERNAL_SOURCING_CAP_EXCEEDED | 422` with no mid-sentence cut; heading scan confirms §1–§5 all present with §4's endpoint table spanning lines 363–432 (63 rows + header). `grep -c "harder than expert" PRD.md` = 0 — the difficulty directive did not leak. PRD accepted, no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-05T12:00:03.173Z

Generation complete for `task_2861_consulting_bench_management_utilization`.

### Coverage — 164 tests, 92/92 non-stub design instances, 0 gaps

| Queue | Instances available (non-stub) | Translated | Tests |
|---|---|---|---|
| A — Difficulty (§1.8) | 25 | **25** | 52 |
| B — Corner (§1.9) | 67 | **67** | 112 |

Queue B by section: entities 12, state_machines 10, calculations 9, validations 19, endpoints 5, errors 3, rbac 5, cross-cutting 3, consistency model 1.

**Instances skipped: none.** The 16 stub instances (state_machines 1, calculations 8, validations 5, cross-cutting 2) all carry `excluded_because` pointing at a queue-A difficulty instance; every cross-reference was verified to resolve to a real instance name that *is* translated (e.g. `release_cascade_reaches_every_ancestor_in_one_write` → `transitive_cascade/release_to_ancestor_posture_freeze_chain` in `test_04`; `utilization_variants_are_persisted_side_by_side` → `dual_variant_calc/utilization_dual_basis_diverges_on_holiday_period` and `.../realization_booked_vs_earned_diverges_on_investment_mix` in `test_01`). Stubs were correctly not translated.

### Files written this session (task root, not `workspace/`)

- `test_suite/test_14_validations_fiscal.py` — 1171 lines, 25 tests, 10 instances
- `test_suite/test_15_endpoints.py` — 564 lines, 10 tests, 5 instances
- `test_suite/test_16_errors_and_rbac.py` — 637 lines, 15 tests, 3 errors + 5 rbac instances
- `test_suite/test_17_cross_cutting.py` — 471 lines, 8 tests, 3 cross-cutting + 1 consistency-model instance

Full suite: `test_suite/` 18 files (conftest 15 lines + test_01…test_17), `test_helpers/` 9 files (fixtures 777, api_client 456, assertions 431, types 380, factories 298, constants 145, api_errors 142, __init__ 117, test_users 87). 11,476 lines total.

### Audits (all clean)

- `python3 -m compileall test_suite test_helpers` → OK; `pytest --collect-only` → **164 tests collected, no errors** (`__pycache__`/`.pytest_cache` removed afterwards).
- **PRD-citation pass**: 720 quoted fragments across all 17 test files grep-verified as literal substrings of `workspace/PRD.md` — 0 non-verbatim. Fixed four §4/§2.9 citations in `test_16` that had dropped the PRD's backticks or paraphrased rungs 19/20, plus section-label corrections (line 259/263–271 are §3.5, not §3.4; line 201 is §2.11).
- **Scaffold-citation pass**: AST-level check of all 164 test docstrings — every test has exactly one trailing `Design:` line, 0 untagged, 0 dual-tagged, every `<section>` and `<instance.name>` resolves to a real yaml key.
- Per-file import audits: every imported name used ≥2 times, no unused imports.
- No `workspace/test_helpers/` or `workspace/test_suite/`; `worklog.md` untouched; `workspace/implementation/` never read.

### Design-vs-PRD deviations (PRD wins; each documented in the helper docstring)

1. `separation_decision_needs_a_second_user_and_a_zero_allocation` (test_14) — design confirms a future-dated assignment yet asserts `allocated_pct == 40.00`; PRD §3.2 makes the sum clock-relative, so the interval was opened at the clock date.
2. `one_bench_run_moves_only_the_rows_whose_clock_test_passes` (test_15) — design asserts a spell is CLOSED after a future-dated confirm; PRD line 271 closes a spell only at `allocated_pct` ≥ 50.00, so the test asserts only the unambiguous young spell (MONITORING / `escalation_count 0` / `age_days 7`).
3. `selector_re_runs_against_the_pool_as_it_stands_at_each_call` (test_17) — clock moved from 2026-08-03 to 2026-08-17 (the window's first day) so the confirmed winner genuinely reads `ASSIGNED` at 100.00; scores, eligibility and ranking are clock-independent and unchanged.
4. `every_cascaded_field_is_readable_in_the_same_response_and_the_next_read` (test_17) — the design simultaneously wants `ASSIGNED`/100.00 (needs the clock inside the interval) and `earned_realization_pct` absent (needs no delivered workday). Both hold only if the window opens on a non-workday, so the clock and window open on Saturday 2026-08-16.
5. `ERR_INVALID_REQUEST` asserted as **400** per §2.9 rung 3 / §5, though several entity instances say 422.
6. `ERR_SELF_APPROVAL_FORBIDDEN` asserted as **403** per rung 19, though the rbac instance text says 409.

**Orchestrator verification:** `test_helpers/` (9 files) and `test_suite/` (conftest + test_01…test_17) both confirmed present at the task root; no `workspace/test_helpers/` or `workspace/test_suite/` strays; only one `worklog.md` on disk.

## Step 6: Generate Implementation — 2026-09-05T12:00:03.173Z

Implementation complete and verified.

### Modules written (all in `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | reads `$PORT`, binds `0.0.0.0`, foreground `exec python3 app.py`, flask-import guard |
| `requirements.txt` | 1 | flask |
| `app.py` | 73 | factory, 7 blueprints, `before_request` group snapshot, `ApiError`/`HTTPException`/`Exception` → envelope |
| `helpers.py` | 137 | Decimal quantisers (`q2`/`q4`, ROUND_HALF_UP), date/instant parse+format, workday arithmetic |
| `errors.py` | 76 | all 56 error ids → HTTP status |
| `envelope.py` | 76 | meta/`req_<20>`/3-frac-digit timestamps, object/array/error shapes, Decimal→JSON **number** |
| `store.py` | 103 | 13 in-memory dicts, monotonic stamps, `_seq` ordering, logical clock (epoch `2026-08-01T00:00:00Z`), request-idempotent `bump()` |
| `reqctx.py` | 351 | rungs 1–3: auth, role gate, unknown-key/type/range/width/enum validation, pagination, filters |
| `derive.py` | 724 | all 10 calculations + constants: allocation, availability, assertion status, spell age, headcount/ratio rollup + posture, coverage, realization/margin, match score, auto-staff filter+ranking, period buckets, discount 7-step pass, rate cascade, forecast |
| `serial.py` | 329 | 13 serialisers; every clock-dependent field derived at read time (forecast is the only unversioned row) |
| `ops.py` | 112 | 404 map, spell open/close/reopen cascades, practice-group `settle()` version bookkeeping |
| `routes_taxonomy.py` | 213 | practice groups (+cycle/uniqueness, child-groups), skills |
| `routes_people.py` | 313 | consultants (hire opens MONITORING spell), skill assertions, ownership gates |
| `routes_demand.py` | 300 | demand pipeline, qualify, staffing-mode, close WON/LOST unwind, auto-staff selector |
| `routes_assign.py` | 226 | propose (OCC on `expected_consultant_version`), confirm (full gate stack), release, cancel |
| `routes_bench.py` | 387 | bench spells, internal project, separation proposal/decision (SoD), reskilling cohorts + enrolment/graduation, `POST /bench-runs` checkpoint |
| `routes_partner.py` | 314 | firms (+PATCH), placements, approve (closed-interval concurrency + sourcing cap), terminate |
| `routes_finance.py` | 350 | discount create/decide/revise, utilization periods + close snapshot, hiring forecasts, `POST /_clock/set_current_utc` |

**4095 lines total.** All state is in-process dicts; nothing is seeded, no disk persistence. `test_helpers/`/`test_suite/` were never read; `worklog.md` untouched.

### Coverage
- **Endpoints: 63/63** — programmatically diffed the live `url_map` against `SCAFFOLD.yaml`: zero missing, only Flask's default `/static` extra.
- **Validation:** the §2.9 44-rung total order is honoured per handler (existence → ownership → OCC → state → SoD/tier → constraints → coherence → fiscal → posture). Two deliberate deviations, both from explicit PRD prose: enrolment reports `ERR_CONSULTANT_SEPARATED` ahead of the spell-state rung ("a separated consultant may not be enrolled at all"), and placement approval follows §3.6's stated order (placement state → firm vetting → demand state → posture → ceilings) since rung 8 does not list approval.
- **Calculations:** all 10 implemented with `Decimal` only, 2 dp money/hours/FTE and 4 dp for `match_score`/ratios/`scarcity_index`; per-demand-then-sum rounding in forecasts, single final rounding for realization/margin, `ceil(gap/0.85)` hires.
- **State machines:** all 8; only `POST /bench-runs` advances time-driven state (one rung per spell per run, 30-day internal-project return, CONFIRMED→ACTIVE, APPROVED→ACTIVE, PLANNED→RUNNING). A clock move re-derives but never advances, and never calls `settle()`.

### Smoke test (ports 51861/51862, killed by exact PID; no broad pkill)
Three scripted end-to-end passes against a fresh process all behaved per PRD:
1. group→skill→consultant→assertion→demand→qualify→mode→propose(OCC)→confirm→release-refusal-before-start→clock move→2×bench-runs→discount create→period open/close→forecast; plus 401/403/409 negatives.
2. Bench lifecycle: age to `ESCALATED_L2` (count 2) → group `FROZEN` on the L2-count arm → internal project (bench_headcount 1→0, posture back to `OPEN`) → 30-day auto-return with `age_reset_on`/`investment_ended_on` → cohort enrolment refused from `MONITORING`, accepted from `ESCALATED_L2` → graduation (`seats_taken` 0, assertion upgraded to level 5, `escalation_count` preserved) → separation proposal + non-proposer approval → consultant leaves `total_headcount`.
3. Auto-staff (score 0.8250, `end_date` = day after demand end) → confirm → discount reject/revise-lower-422/revise/approve with the 4-hop rate cascade re-pinning the assignment bill rate to 285.00 → close WON activating the assignment → external branch: request (bill rate 0.00), approve (bill rate = effective rate), closed-interval concurrency 409 on the shared boundary day, terminate, re-approve.

Period arithmetic checked by hand on a live row: 11 workdays / 88.00 capacity / 80.00 net / 56.00 billable / 24.00 bench, available basis 70.00 → target basis 63.64 on close, `variance_pp` −5.00 → −11.36. Both smoke ports are free and no stray processes remain.

## Step 7: Run Tests and Iterate — 2026-09-05T12:28:20.663Z

All 8 rounds are green. Summary below.

### Iterations run
**2 sweeps.** Iteration 1: 152/164 in all 8 rounds, 12 deterministic failures (identical union in every round — no flakiness, no load-induced failures). Iteration 2 after fixes: 164/164 in all 8 rounds.

### Tests deleted
**None.** All 12 failures passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability); all 12 were STEP 2 test-artifact bugs. The implementation was correct in every case and was not modified.

### Root cause of 7 of the 12 (one shared defect class)
`PRD §3.2` puts every new hire on the bench, so a group whose entire headcount is freshly hired sits at `own_bench_ratio`/`rollup_bench_ratio` of 1.0000 and `§2.10` makes it **FROZEN**. Four test setups hired their consultants into the same group that owned the demand and then attempted operations `§3.5`/`§3.6` forbid on a FROZEN group (an `INVESTMENT` confirmation, an external-placement request, a placement approval). Verified against a live server: one hire → `total_headcount 1, bench_headcount 1, rollup 1.0, posture FROZEN`. PRD-faithful; the fixtures were wrong.

### Fixes applied to `test_helpers/`
- `test_helpers/fixtures.py` — new Tier-2 helper `add_bench_group(api, world, ...)`: registers a second, unrelated practice group in the same geography under `world["bench_group"]`, so tests whose subject is not posture can hire there and leave the demand's own group at a 0.0000 rollup ratio and `OPEN` posture. Nothing in the PRD couples an assignment's consultant to the demand's practice group (only the §3.5 auto-staff eligibility filter does, and those tests still hire into the demand's group).

### Fixes applied to `test_suite/` (no `implementation/` changes)
- `test_01_dual_variant_measurements.py` — `_mixed_category_demand`: hire Ada/Grace into `bench_group` so the `INVESTMENT` confirm isn't refused by §3.5's FROZEN gate. (2 tests)
- `test_08_resource_temporal_overlap.py` — `_one_slot_firm_with_three_placements`: the fixture discarded `approve_placement`'s return and handed back the pre-approval `REQUESTED` row, so `assert first["status"] == APPROVED` could never hold. Now rebinds `first` to the approved row. (1 test)
- `test_12_calculations.py` — `test_one_row_moves_coverage_only_while_it_is_confirmed`: assignment started on the clock date (2026-08-03), so §3.5's "cancelling a CONFIRMED row requires the clock date strictly earlier than `start_date`" correctly refused. Interval moved to 2026-08-17→08-29. (1 test)
- `test_13_validations_master_data.py` — two tests sent `POST /consultants` and `PATCH /consultants/{id}` as `PracticePartner`, but §4 authorises `ResourceManager` only and ladder rung 2 outranks rungs 23/35, so the server correctly answered `ERR_UNAUTHORIZED`. Switched to `RESOURCE_MANAGER`. (2 tests)
- `test_14_validations_fiscal.py` — `_three_proposals_against_one_rate`: hire the three consultants into `bench_group` (FROZEN gate on the `INVESTMENT` confirm). (1 test)
- `test_15_endpoints.py` — `_four_machines_with_a_future_dated_twin` and `_one_enrolment_and_one_approved_placement`: hire into `bench_group` (FROZEN gate on external sourcing). (4 tests)
- `test_15_endpoints.py` — `test_no_neighbouring_row_moves_with_them`: asserted the group's `version == 1` after a hire, but §2.4 bumps `version` on every mutation "including mutations that only touch derived fields" and the hire moved the headcounts. Now reads the baseline version before the consultant PATCH and asserts it is unchanged after — which is the rule the test actually means. (1 test)

### Final sweep evidence
| round | passed/total |
|---|---|
| results.1.json | 164 / 164 |
| results.2.json | 164 / 164 |
| results.3.json | 164 / 164 |
| results.4.json | 164 / 164 |
| results.5.json | 164 / 164 |
| results.6.json | 164 / 164 |
| results.7.json | 164 / 164 |
| results.8.json | 164 / 164 |

`failed: 0, errors: 0` in all 8; union of failing tests across rounds is empty. `worklog.md` and `workspace/implementation/` were not touched; scratch dirs and `__pycache__` cleaned up.

**Orchestrator verification:** independently re-read all 8 `workspace/implementation/results.*.json` (all timestamped 12:24, ~53 KB each) — every one reports `passed 164 / failed 0 / errors 0 / total 164`. Sweep artifacts are real, so no re-run was needed. Step 8 is NOT skipped: Step 7 applied 1 `test_helpers/` fix and 12 `test_suite/` fixes (0 deletions, 0 `implementation/` fixes), so the skip condition (all four counts zero) does not hold.

## Step 8: Finalize PRD — 2026-09-05T12:35:12.829Z

`PRD_FINALIZED.md` is written. Four surgical in-line revisions, no new sections, no deletions.

### Size
- PRD.md: 492 lines / 130,519 bytes
- PRD_FINALIZED.md: 492 lines / 131,758 bytes
- Line delta: 0 (0.00%); byte delta: +1,239 (+0.95%). 4 changed lines out of 492 (0.81%).

### Changes
- **§3.5 (Confirmation gates, PRD line 269)** — *revise* — the `INVESTMENT`-category frozen-posture gate now names its error code (`ERR_PRACTICE_POSTURE_FROZEN`), pins its precedence (after travel-fit, ahead of allocation and margin), states it reads the posture derived at confirmation time, and states it is confirmation's only posture gate (no `CONSTRAINED` arm; `BILLABLE` never posture-gated) — `implementation/routes_assign.py:152-165`.
- **§2.9 rung 42 (PRD line 175)** — *revise* — appended that the `INVESTMENT` confirmation gate shares the code but does not sit at rung 42, deferring to §3.5's position above the allocation-capacity and margin-floor rungs — `implementation/routes_assign.py:154` vs `implementation/routes_partner.py:136-148`.
- **§3.5 (confirmation cascade, PRD line 271)** — *revise* — "the group's `bench_headcount`" disambiguated to the **consultant's own** practice group (explicitly not necessarily the demand's), plus one sentence fixing the global attribution rule: bench-population numbers book against the consultant's group, while the demand's group is what auto-staff eligibility, the posture gates, firm-vetting geography and the sourcing cap read — `implementation/derive.py:229-241, 243-254, 471-475, 658, 682`.
- **§3.5 (Cancellation, PRD line 277)** — *revise* — named `ERR_ASSIGNMENT_STATE_INVALID` as the refusal for cancelling a `CONFIRMED` row whose `start_date` has arrived — `implementation/routes_assign.py:213-214`.

### Pre-edit search log

**Edit 1 & 2 (frozen-posture gate on confirmation)**
- (a) Subject: the `FROZEN` posture gate — every enforcement site, its error code, and its ladder position.
- (b) Enumerated: `grep -n "FROZEN\|POSTURE_FROZEN" *.py` → `derive.py:269-270` (derivation), `routes_partner.py:136-148` (`_posture_gate`, used by `request_placement:180` and `approve_placement:281`), `routes_assign.py:154-155` (INVESTMENT confirm), `errors.py:57` (409). Read `routes_assign.py` in full for the confirm gate order (state→pipeline→mode→separated→reskilling→proficiency→certification→proficiency-level→travel→**frozen**→allocation→margin) and `routes_partner.py:100-315` for both external paths.
- (c) Adjustment: my first draft added confirmation to rung 42's applies-list — that would have placed it *below* allocation (32) and margin (40), contradicting `routes_assign.py`. Rewrote rung 42 to say the confirm gate explicitly does *not* sit there, and put the precedence claim in §3.5 instead. Also added the "`CONSTRAINED` never blocks a confirmation / `BILLABLE` never posture-gated" clause because `routes_assign.py:154` guards on `category == "INVESTMENT"` only and calls `group_posture` rather than `_posture_gate` (no scarcity carve-out arm).

**Edit 3 (group attribution of bench-population changes)**
- (a) Subject: which practice group's headcounts/ratios/posture move when a spell opens or closes, now that Step 7's `add_bench_group` fixture makes consultant-group ≠ demand-group.
- (b) Enumerated: `derive.py:229-241` (`group_headcounts`, filters on `consultant.practice_group_id`), `derive.py:243-254` (`escalated_l2_count`, consultant's group within subtree), `derive.py:257-283` (`group_derived`), `derive.py:291-294` (`derived_snapshot`), `ops.py:73-95` (`close_spell_after_confirm`, `reopen_spell_if_benched` — no group reference), `ops.py:99-112` (`settle`), plus every `settle()` callsite (`grep -rn "settle()"` → taxonomy 84/137, people 122/207, assign 175/199/225, demand 240/272, partner 295/313, bench 101/119/150/276/322/386). Counter-direction paths: `derive.py:471-475` (auto-staff eligibility → demand's group subtree), `derive.py:658` (sourcing cap → demand's group), `routes_partner.py:151-154` (firm vetting → demand's group geography), `derive.py:93, 682` (`level_targets` → consultant's group).
- (c) Adjustment: the generalising sentence initially listed only "the auto-staff eligibility filter, the posture gates and the external-sourcing cap" as demand-group readers, which read as exhaustive and would have mis-described `routes_partner.py:151-154`; added the firm-vetting geography comparison. Kept `level_targets` out rather than restating it (it resolves off the consultant's group, already covered by the first half of the sentence).

**Edit 4 (cancel-after-start error code)**
- (a) Subject: the refusal code for cancelling a started `CONFIRMED` assignment.
- (b) Enumerated: `grep -rn "ERR_ASSIGNMENT_STATE_INVALID" *.py` → `routes_assign.py:132, 187, 189, 211, 214` and `errors.py:24` (409). Confirmed the release-side twin (`:189`) is already named in the PRD and that the demand-close `LOST` unwind (`routes_demand.py`) cancels without a gate, so the new clause cannot be read as applying there.
- (c) No adjustment; wording scoped to the cancellation precondition only.

### Items deliberately left unpatched (PRD already determines them)
7 of the 12 Step 7 failures were the FROZEN-on-fresh-hire class; §3.2 + §2.10 already determine `total_headcount 1, bench_headcount 1, rollup 1.0000, FROZEN`, and §3.6 + rung 42 already name the code for the 4 external-sourcing cases. The `approve_placement` return value (§2.2), the cancel-before-start clock rule (§3.5), the `ResourceManager`-only consultant endpoints with rung 2 above rungs 23/35 (§4 + §2.9), and the practice-group `version` bump on a hire (§2.4's explicit derived-field-only clause) are all already uniquely pinned. I specifically declined to add a "version increments only when a value actually changed" clause: `routes_people.py:206` and `routes_taxonomy.py:136` bump unconditionally on a PATCH, so that universal would have been a false claim and a new Step 9 mismatch.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` reports 8 changed lines (4 revised lines, `<`/`>` pairs) — the file is genuinely patched, not a byte-identical copy. Both 492 lines; PRD_FINALIZED.md is +1,239 bytes.

## Step 9: Complete PRD — 2026-09-05T13:08:16.965Z

Run as **three sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not clobber earlier edits). Net result: 492 → 493 lines, 131,758 → 147,061 chars (+15,303 chars, +11.6%), **111 changed lines** versus `PRD_FINALIZED.md`. 46 ambiguity-pins + 18 mismatch-revisions across the three passes. No new sections; every patch an in-paragraph insert or revision.

### Pass 1 — app.py, envelope.py, errors.py, helpers.py, store.py, reqctx.py, ops.py, serial.py, routes_taxonomy.py, routes_people.py

492 lines / 131,758 chars → 493 lines / 138,129 chars (+6,371 chars; the one new line is an added bullet inside §2.2's existing error-format list). **17 ambiguity-pins, 6 mismatch-revisions.** Error catalogue cross-checked programmatically: 56 ids, identical ids/statuses/order to `errors.py` — no change needed.

- §2.1 — insert — ambiguity — a whitespace-only header value counts as empty for `ERR_UNAUTHENTICATED` — reqctx.py:48
- §2.2 (meta bullets) — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase-alnum chars — envelope.py:16
- §2.2 (meta bullets) — insert — ambiguity — `api_request_timestamp` reads the host's real clock, not the logical clock of §2.5 — envelope.py:22
- §2.2 (`data` bullet) — insert — ambiguity — "absent/unset/cleared" properties are emitted as explicit JSON `null`, full key set always present; forecast `updated_at`/`version` the only omitted keys — serial.py:22-30, derive.py:382-396
- §2.2 (error bullets) — insert — ambiguity — unknown path → `ERR_INVALID_REQUEST` at HTTP 404, disallowed method → same id at 405 (only non-400 uses of that id) — app.py:49-55
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; undeclared query parameters are ignored (unknown-key rule is body-only) — reqctx.py:303-319, 68-86
- §2.3 — insert — ambiguity — `created_at` order is total (monotonic minting); filters combine conjunctively; enum filters validated (400), boolean filter accepts `true/false/1/0` case-insensitively, identifier/code filters unvalidated and match nothing → empty page — store.py:57-62, reqctx.py:322-347
- §2.4 — insert — ambiguity — one `version` increment per row per request however often the cascade touches it; a `PATCH` mutates even when empty; a derived recomputation mutates only when a value actually moves; derived properties computed at read time unless snapshot/pinned/frozen — store.py:89-103, ops.py:103-112, serial.py:1-2
- §2.5 — insert — ambiguity — server-written instants always 3 fractional digits; inbound `current_utc` accepts any ISO-8601 form (any/no fraction, `Z` or numeric offset, bare date → midnight UTC) — helpers.py:77-109
- §2.9 rung 3 — insert — ambiguity — body must be a JSON object (empty→`{}`); `null` = absent; trailing zeros don't count against declared width; zero-fraction number satisfies an integer; booleans/numeric strings satisfy neither; identifier fields must be non-empty strings so a non-string id fails at rung 3, not at 4/5 — reqctx.py:68-86, 107-133, 209-219, helpers.py:21-31, 58-64
- §2.9 rung 23 — insert — ambiguity — all uniqueness comparisons are exact string equality (case/whitespace significant) — routes_taxonomy.py:41,164, routes_people.py:99, routes_partner.py:46
- §2.10 — insert — ambiguity — a `level_targets` entry may be partial with per-property fallback to firm-wide defaults; keys/inner keys constrained; escalation days 0–3650 ints, percentages 0.00–100.00 at two decimals — derive.py:89-100, reqctx.py:245-270
- §3.1 — revise — mismatch — group update also accepts `name` (uniqueness re-checked excluding itself), and only those four fields; `level_targets` replaces wholesale (`null` empties); `parent_group_id: null` detaches — routes_taxonomy.py:112-138
- §3.1 — revise — mismatch — skills are also listable by exact `code` — routes_taxonomy.py:180-187
- §3.2 — insert — ambiguity — `email` is 1–255 characters — routes_people.py:82
- §3.2 — revise — ambiguity — `industry_code` is free text 1–60 chars (not the skill-code pattern), `years` up to four decimals, both entry fields required — reqctx.py:273-299
- §3.2 — insert — ambiguity — consultant update accepts exactly those eight fields (`level`/`practice_group_id` are unknown keys), geography re-checked against the existing group, `null` clears the dev goal and empties industry experience but leaves the other six untouched — routes_people.py:159-208
- §3.2 — revise — mismatch — consultants are also listable by `home_geo_code` — routes_people.py:134
- §3.2 — insert — ambiguity — assertion revision: `null` clears either certification field with the code/expiry rule re-checked on the merged pair, `null` `last_used_on` is a no-op, `consultant_id`/`skill_id` immutable, ownership checked after shape — routes_people.py:286-313
- §4 `PATCH /practice-groups/{id}` — revise — ambiguity — "and nothing else" — routes_taxonomy.py:116
- §4 `GET /consultants` — revise — mismatch — filter list adds `development_goal_skill_id` — routes_people.py:131
- §4 `PATCH /consultants/{id}` — revise — mismatch — row claimed `level` and `practice_group` were updatable; impl rejects both as unknown body keys — routes_people.py:163-174
- §4 `PATCH /skill-assertions/{id}` — revise — mismatch — row named a nonexistent "evidence note"; impl accepts `certification_code`/`certification_expires_on`/`last_used_on` — routes_people.py:290-292

Cross-module consistency checks done before committing wording: every enum-valued filter in all seven route modules uses the validating helper and every id/code filter the non-validating one (so the §2.3 three-way claim holds system-wide); every `PATCH` in the codebase bumps unconditionally; `parse_instant` has exactly one caller (`current_utc`); all response bodies flow through `serial.py`, so the "always full key set / null not omitted" claim has no counterexample.

### Pass 2 — derive.py, routes_demand.py, routes_assign.py

493 lines / 138,129 chars → 493 lines / 141,832 chars (+3,703 chars, +0 lines). **14 ambiguity-pins, 7 mismatch-revisions.** All 21 edits in-paragraph; pass 1's edits untouched.

- §2.9 rung 4 — revise — mismatch — path existence outranks rung 3: every templated handler resolves `need(path)` before `body()`, so a nonexistent id + malformed body yields the 404 (verified universal across all 8 route modules) — routes_demand.py:184, routes_assign.py:129
- §2.9 rung 8 — revise — mismatch — staffing-branch selection requires `QUALIFIED` only (not "QUALIFYING or QUALIFIED"); closure split into `WON`→`QUALIFIED` / `LOST`→`QUALIFYING` or `QUALIFIED`; win-probability≥25 folded in; confirmation's demand-state check noted as sitting below rung 9 — routes_demand.py:204,243, routes_assign.py:131-136
- §2.9 rung 34 — insert — mismatch — non-empty-pool is evaluated *after* branch-coherence rung 36, so auto-staffing an `EXTERNAL` demand reports `ERR_STAFFING_MODE_MISMATCH` — routes_demand.py:285-289
- §2.9 rung 40 — revise — mismatch — margin gate projects the **candidate row's own** cost rate (`100*(effective_rate − row.cost_rate)/effective_rate`), not the demand's blended figure, and fires only for `BILLABLE` — routes_assign.py:161-165 (`derive.realization`'s `extra=` path is dead code)
- §2.4 — insert — ambiguity — a utilization period takes no `updated_at`/`version` from a derived move at all; its `version` advances only on close — derive.py:519-577
- §2.8 — insert — ambiguity — `expected_consultant_version` must be an integer ≥ 1; 0/negative is rung-3 malformed, not 412 — routes_assign.py:79
- §3.3 qualification — insert — ambiguity — takes no body; win-probability shortfall is `ERR_OPPORTUNITY_STATE_INVALID`, checked right after the state precondition and before the retired-skill gate — routes_demand.py:185-192
- §3.3 closure — insert — ambiguity — `note` is 1–500 characters; all three `WON` preconditions fail with `ERR_OPPORTUNITY_STATE_INVALID` in the stated order — routes_demand.py:217-227
- §3.3 `WON` activation — insert — ambiguity — each activated assignment/placement takes its own `version` increment while the consultants' rows are untouched — routes_demand.py:230-239
- §3.5 match score — insert — ambiguity — no `ACTIVE` assertion at all ⇒ skill component 0.0000, no bonus, other four components still weighted — derive.py:419-420
- §3.5 ranking — revise — mismatch — comparisons use the score *computed at ranking time* (nothing is stored yet), not a "stored" score — derive.py:497-508
- §3.5 auto-staff creation — insert — ambiguity — leaves the winner's `version` and the demand's `version` untouched, unlike a named proposal — routes_demand.py:291-300
- §3.5 confirmation — insert — ambiguity — assignment-state checked first; demand-not-`QUALIFIED` ⇒ `ERR_OPPORTUNITY_STATE_INVALID`, mode-not-`INTERNAL` ⇒ `ERR_STAFFING_MODE_MISMATCH` — routes_assign.py:131-138
- §3.5 activation — revise — mismatch — removed the false rationale that `ACTIVE` rows "enter the delivered-hours denominator"; `CONFIRMED` rows already count there — derive.py:354-359
- §3.5 release — insert — ambiguity — `reason` is 1–500 characters — routes_assign.py:185
- §3.5 cancellation — insert — ambiguity — same 1–500-character `reason` rule — routes_assign.py:209
- §3.7 rate cascade — insert — ambiguity — a re-pinned assignment's `version` moves only when `bill_rate_usd_per_hour` actually changes — derive.py:642-646
- §3.8 spell age — insert — ambiguity — `age_days` is floored at 0, so a clock behind the base date reports 0 — derive.py:191
- §3.9 utilization — insert — ambiguity — `utilization_pct_target_basis` is absent when `capacity_hours` is 0.00; `variance_pp` absent whenever `utilization_pct_of_record` is — derive.py:548,573-576
- §3.9 forecast — revise — ambiguity — `internal_supply_fte` rounds per consultant before the sum, then rounds the total again — derive.py:700-701
- §4 `/demand-opportunities/{id}/qualify` row — revise — mismatch — endpoint takes no body; the win probability is the one recorded at registration — routes_demand.py:181-195

Notable non-findings (PRD already pins impl uniquely): the 5-component/weight/bonus/cap match-score chain, `peak_allocation`'s interval-start optimisation, the 7-step discount pass including the allocation-weighted step-3 fallback and the `steps=6` revision path, posture arms and rollup, coverage/`staffing_status` fall-back, `delivered_workdays`, the confirm gate order for `ERR_CERTIFICATION_EXPIRED` vs `ERR_PROFICIENCY_INSUFFICIENT`, and `recommended_hires` ceiling arithmetic. One out-of-partition mismatch deliberately handed to pass 3: `routes_finance.py:239-245` (`list_periods`) checks ownership rung 6 *before* validating pagination (rung 3); pass 2 kept its rung-4 wording narrow so as not to falsely claim rung 3 outranks everything below it.

### Pass 3 — routes_bench.py, routes_partner.py, routes_finance.py

493 lines / 141,832 chars → 493 lines / 147,061 chars (+5,229 chars, +0 lines). 20 edits: **5 mismatch-revisions** (4 distinct subjects — three ladder-order deviations plus the placement-approval gate order, annotated at both the rung and the §3 prose) and **15 ambiguity-pins**, plus 1 self-correcting edit that withdrew an over-claim of its own.

- §2.9 rung 6 — insert — mismatch — ownership is evaluated above rung 3 on the utilization-period listing, scoped to "the only ownership-guarded endpoint that also takes pagination"; the two body-carrying ownership endpoints explicitly left ladder-consistent — routes_finance.py:243-245
- §2.9 rung 12 — insert — mismatch — on placement approval this is the first gate applied, above the demand-pipeline rung 8 and the firm-vetting rung 37 — routes_partner.py:272-278
- §2.9 rung 17 — insert — mismatch — on cohort enrolment alone the separation check runs above the spell-state rung 10 and programme-state rung 11, so a separated consultant reports `ERR_CONSULTANT_SEPARATED` — routes_bench.py:253-259
- §2.9 rung 31 — insert — mismatch — the firm-concurrency rung sits in practice below rung 37 and both posture rungs 42/43; only rung 44 falls below it — routes_partner.py:276-283
- §3.6 (placement approval) — revise — mismatch — gates applied in exactly the written order, cross-referenced to rungs 12/37 above rung 8 and rung 31 below both posture rungs — routes_partner.py:272-289
- §2.5 — insert — ambiguity — the clock is set outright, not advanced: a `current_utc` earlier than the held instant is accepted and takes effect identically — routes_finance.py:349
- §3.6 (firm PATCH) — revise — ambiguity — only the four listed properties are patchable (neither `name` nor `geo_code`); a new `max_concurrent_placements` below the live committed count is accepted, the ceiling being tested only at the next approval — routes_partner.py:111-120
- §3.6 (placement request) — insert — ambiguity — neither the demand nor the firm is written, so neither takes a new `updated_at` or `version` — routes_partner.py:181-196
- §3.6 (termination) — revise — ambiguity — `reason` is a 1–500 char string validated on the way in but neither stored nor echoed — routes_partner.py:303-305
- §3.7 (create) — revise — ambiguity — `expected_opportunity_version` is an integer ≥ 1, so 0/negative/non-integer is a rung-3 malformed request rather than a stale-version refusal; a demand already `WON`/`LOST` takes no discount request (`ERR_OPPORTUNITY_STATE_INVALID`) — routes_finance.py:78,83-84
- §3.7 (decide) — insert — ambiguity — a supplied `decision_note` overwrites; an omitted one leaves the stored note untouched — routes_finance.py:152-153
- §3.7 (revise) — insert — ambiguity — same note rule on revision — routes_finance.py:186-187
- §3.7 (revise) — insert — ambiguity — a revision writes nothing to the demand: no rate cascade, `approved_rate_usd_per_hour` untouched, demand `version` unmoved — routes_finance.py:188-189
- §3.8 (enrolment) — revise — ambiguity — enrolment clears any leftover `investment_ended_on`; a spell carries one investment window at a time — routes_bench.py:271-272
- §3.8 (graduation) — revise — ambiguity — an assertion already at or above target is left entirely untouched (no new `updated_at`/`version`); a cascade-created row carries no `certification_code`, `certification_expires_on` or `last_used_on`, so its derived `assertion_status` is `ACTIVE` — routes_bench.py:283-298
- §3.8 (graduation) — revise — self-correction — withdrew its own added clause "and the graduate is immediately staffable on that skill", which would have been a false universal (auto-staff also needs proficiency ≥ `min_proficiency_level`, positive travel fit and free capacity)
- §3.8 (internal project) — revise — ambiguity — a consultant at half capacity or more is refused with `ERR_BENCH_SPELL_STATE_INVALID` (the same code as the spell's state gate) and that allocation test runs *after* the state test; `investment_ended_on` cleared as on enrolment — routes_bench.py:93-98
- §3.8 (separation proposal) — revise — ambiguity — `rationale` is 1–500 chars, validated but neither stored nor echoed — routes_bench.py:110-111
- §3.8 (separation decision) — revise — ambiguity — `note` likewise validated then discarded — routes_bench.py:129-130
- §3.8 (re-proposal) — insert — ambiguity — a fresh proposal re-stamps `separation_proposed_by_user_id` and leaves the previous round's `separation_decision`/`separation_decided_by_user_id` standing until the new decision overwrites both — routes_bench.py:116-117
- §3.9 (hiring forecast) — revise — ambiguity — `skill_code` is shape-checked only as a 1–30 char string, not against the uppercase code pattern skills themselves must satisfy; `geography_code` is only the cut the scope is taken on and need not match any existing practice group, so a geography holding no groups yields a forecast of zeros rather than an error — routes_finance.py:295-303

Deliberate non-edits (scope / no-new-mismatch discipline): `max_investment_pct` gates nothing (dead policy data, confirmed by grep) — skipped as §2.10 is pass 1's territory; the revision's snapshot-vs-current standard-rate distinction — unobservable, since no PATCH exists on demands; rung 36 on placement approval — `staffing_mode` is set-once (routes_demand.py:206), making that branch unreachable; rung 8's own text — left alone, as it makes no claim about placement approval.

**Pass 3 self-check — PASS.** 493 lines, complete and non-truncated; final line still `| ERR_EXTERNAL_SOURCING_CAP_EXCEEDED | 422 |`; all 27 section headings intact. Passes 1 & 2's edits verified present (7/7 marker phrases found exactly once each). No file other than `PRD_COMPLETED.md` was written; no `cp` was run.

**Orchestrator verification:** `PRD_COMPLETED.md` is 493 lines / 147,061 chars and is **not** byte-identical to `PRD_FINALIZED.md` — `diff` reports 111 changed lines, so the scan genuinely ran. Tail confirms the §5 error table completes on `ERR_EXTERNAL_SOURCING_CAP_EXCEEDED | 422`. Step 9 wrote no implementation or test files, so the Step 7 sweep evidence (8×164/164) remains valid for the artifacts on disk.

---

## Pipeline complete — 2026-09-05T13:08:16.965Z

All nine steps finished. Final state: 3 scaffold YAMLs, `workspace/PRD.md` (492 lines) → `workspace/PRD_FINALIZED.md` (492 lines, 4 revised lines) → `workspace/PRD_COMPLETED.md` (493 lines, 111 changed lines vs FINALIZED), 164 tests in `test_suite/` (18 files) over `test_helpers/` (9 modules), a 4095-line Python+Flask implementation in `workspace/implementation/`, and 8 passing sweep result files (`results.1.json`–`results.8.json`, each 164/164).
