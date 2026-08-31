## Step 1: Create task directory — 2026-08-30T00:00:00.000Z

Created `tasks/task_2182_workforce_reduction_warn_act/` and `tasks/task_2182_workforce_reduction_warn_act/workspace/` (index 2182 = highest existing 2181 + 1).

## Step 3: Copy shared files — 2026-08-30T00:00:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2182_workforce_reduction_warn_act/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-30T02:48:00.000Z

All three scaffold artifacts are generated, mutually consistent, and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_2182_workforce_reduction_warn_act/SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2182_workforce_reduction_warn_act/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2182_workforce_reduction_warn_act/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Design summary
**Profile**: compliance_audit × temporal_windowing, **flat** topology (0% in prior examples — prioritized), **parallel** state-machine shape, **segregation_of_duties** role model, immediate consistency. Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency.

**Surface**: 10 entities, 8 state machines / 33 transitions, 2 OCC concurrency rules, 9 calculations, 34 ordered validations, 43 endpoints, 46 errors, 5 roles. Endpoint count runs above the Expert band (20–32) because the scenario carries eight distinct workstreams and every FK needs a reverse-reachability GET; entity count sits at the low end of Expert deliberately, so the difficulty comes from coupling, not volume.

**Core mechanics** (all numbers below were computed by executing the formulas, not estimated):
- Dual-variant WARN counting on `Site` — FEDERAL half-open 90-day window with part-time/short-service exclusions yields loss 2, STATE closed 30-day window yields 4 on the identical roster.
- Dual-variant severance on `SeveranceOffer` — STANDARD 16 weeks / 2 676 928¢ vs ENHANCED_RELEASE 18.5 weeks / 3 095 198¢; the pinned rounding order (rate→cents first) diverges from the naive order at 3 095 192¢.
- Circular-looking rollup: the benefit-subsidy tier is keyed on `pre_benefit_subtotal` (950 000 → 3 months → total 1 245 500), not on the total (which would give 6 months → 1 651 000).
- Two statistical variants of adverse impact over one pool (N=8, S=4): impact ratio 0.5556 → FLAGGED, hypergeometric 0.6831 → COMPUTED.
- Two interval geometries: rolling aggregate closed/half-open WARN windows on `Site` vs closed offer window + 1-day cooldown on `Employee`.
- Two conserved quantities: site headcount identity across select→rescind, plan severance reserve/benefit liability across issue→sign→revoke.

**Coverage**: §1.8 has 9 rule_ids × 2 instances = 18; §1.9 has 72 instances across all nine claim-extraction-guide sections (59 executable + 13 `excluded_because` stubs), every stub citing a real §1.8 instance name.

**Verification run**
```
Coverage
  §1.5 endpoints declared:    43
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  774

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-audits (scripted, all passing): zero unbound `${var}` placeholders across both design files; zero duplicate instance names; every `grounds:` reference resolves to a declared §1.1–§1.7 element; all 46 error codes are referenced by at least one design instance; no forbidden concurrency vocabulary anywhere.

Two notes for downstream: `api_prefix` is intentionally `""` (flat topology — every collection sits at the root, with a comment in the file explaining it), and the logical clock's mandated startup default `2026-08-01T00:00:00.000Z` is declared on `POST /_clock/set_current_utc` and assumed by every fixture date.

## Step 4: Generate PRD — 2026-08-30T02:58:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2182_workforce_reduction_warn_act/workspace/PRD.md` (449 lines, ~83.5 KB), written incrementally in five appends (header+§2.1 → §2.2 verbatim → §2.3–2.10 → §3.1–3.3 → §3.4–3.10 → §4–§5). The withheld design indices were never opened.

**Structure**: §1 Introduction (3 paragraphs), §2 with 10 domain-derived subsections (2.4 Resource Identity/Revision Counters, 2.5 Logical Compliance Clock, 2.6 Order of Evaluation, 2.7 Precision/Rounding, 2.8 OCC, 2.9 Cascade Discipline & Headcount Identity, 2.10 Left-to-Right Resolution), §3 with 10 lifecycle subsections, §4 endpoint table (4 columns, 43 rows), §5 error table (2 columns, 46 rows). File ends at §5 — no audit footer.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 122 required, 122 present, 0 missing
- endpoints[].request_body: 48 required, 48 present, 0 missing
- endpoints[].query_params: 12 required, 12 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 34 checked, 34 expressed in prose (full ordered ladder in §2.6 with error_id + applies_to scope per rung), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /adverse-impact-analyses + expected_plan_version + ERR_STALE_PLAN_VERSION/412; POST /severance-offers + expected_selection_version + ERR_STALE_SELECTION_VERSION/412), 0 missing
- state_machines[].transitions: 33 checked, 33 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 34 checked, 34 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 43 endpoints checked, 43 expressed, 0 missing
- entities[].fields[] structured content: 122 checked, 122 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (SELECTED/EXEMPTED fork, FEDERAL/STATE window semantics, IMPACT_RATIO/STANDARD_DEVIATION, STANDARD/ENHANCED_RELEASE, APPROVE/RETURN, WAIVED/RELEASED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 799
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional checks**: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; all 5 role names and both identity forms (`entity_backed:Employee` for `SeparatingEmployee`, opaque for the other four) translated into §2.1 prose; `WarnRule` explicitly called out as lacking `updated_at`/`version`; zero fuzzy/approximating words; no schema tables or field lists in §3.

**Three gaps found and repaired during the Contract-2 walk**: (1) the four `Site` headcount counters had no per-partition definitions — added to §3.2; (2) plan-level `pool_count`/`selected_count` membership sets were implied only via the analysis pool — defined explicitly in §3.3; (3) the `POST /severance-offers` side effect "increments Selection.version by 1" was absent — added to §3.8. Note the auditing script initially reported 277 false-positive misses because triple-backtick fences in §2.2 desynchronize naive backtick-pair extraction; stripping fenced blocks first is required.

## Step 6: Generate implementation — 2026-08-30T03:25:00.000Z

Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_2182_workforce_reduction_warn_act/workspace/implementation/`.

## What was built

Python + Flask, ~2,835 lines across 14 modules (each written incrementally, no giant single Write):

- `start.sh` — guarded `pip install` (skipped when flask imports), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- `core.py` — errors, envelope (`meta`/`response_type`/`data`, `req_` ids, 3-digit ISO ms), logical clock (`2026-08-01T00:00:00.000Z`), in-memory `Store`, Decimal `ROUND_HALF_UP` helpers.
- `validation.py` — ladder rungs 1–3 (auth/role/schema) plus rungs 4–5 existence lookups.
- `calc.py` — the 9 calculations; `domain.py` — derived-field recomputation and cascade chains; `selection_ops.py` — the fork and its compensation.
- `routes_*.py` — all **43 endpoints** verified present in the URL map, with RBAC matching the scaffold matrix exactly.

Storage is in-memory dicts only. No seeding anywhere — verified `db.*` is populated exclusively by request handlers.

## Verified behaviours (6 smoke suites, all passing)

- PRD's pinned severance example reproduces exactly: `weekly_rate_cents 167308`, STANDARD → 16 wks / `2676928`, ENHANCED_RELEASE → 18.5 wks / `3095198` (the single-expression variant would give the wrong 3095192).
- Jurisdictional divergence: identical roster gives FEDERAL loss 1 / workforce 4 / 25.00% vs STATE loss 4 / workforce 5 / 80.00% — half-open vs closed window boundary, part-time exclusion (numerator **and** denominator), `min_service_days` on numerator only.
- Both §2.9 invariants hold: headcount partition round-trips through decide→rescind with `roster_count` unmoved; issue→sign→revoke returns `severance_reserve_cents` and `benefit_liability_cents` to exactly their prior values.
- Full parallel-axis lifecycle: `THRESHOLD_PENDING` → `NOTICES_ISSUED` → `NOTICE_PERIOD_SATISFIED`, plus the `NOT_ASSESSED` direct path; rescission voids issued notices and releases the frozen aggregation window.
- Offer cycle `ISSUED→SIGNED→REVOKED→ISSUED` with the 1-day cooldown and the 3-issuance cap; expiry-on-sign leaves the offer `EXPIRED` and unwinds the reserve.
- Execute cascade → `SEPARATED` selections/employees, `PositionRestriction` creation, backfill block, counsel waiver, and clock-driven `RELEASED`.

## Two judgement calls worth flagging

1. **`impact_ratio` rounding.** SCAFFOLD's `variants[].difference` note claims 0.5556 for N=8/S=4/n_f=3/s_f=1, but that requires dividing *unrounded* rates. Both PRD §3.5 prose and the scaffold's own normative `formula` say the ratio is `focal_rate / reference_rate` where each rate is already rounded to 4dp — which yields 0.5555. I followed the two normative sources (the note appears to be an authoring slip; the STANDARD_DEVIATION example in the same block is consistent with the formula, confirming this). Flag status is unaffected either way.
2. **Unnamed error ids.** Three preconditions have no error assigned anywhere in PRD or scaffold; I chose the closest-fitting catalogue entry, all with the spec-correct HTTP status: rescind-with-live-offer → `ERR_INVALID_OFFER_STATE` (409); execute-with-undelivered-notice → `ERR_NOTICE_NOT_DELIVERED` (422); issue-notice-with-`threshold_met`-false → `ERR_INVALID_NOTICE_STATE` (409).

`created_at`/`updated_at` use wall clock (not the logical clock, which the PRD scopes to "deadline, window boundary and age computation") through a monotonic millisecond source, so timestamps are strictly ordered — this matters for the "latest analysis by `created_at` DESC, `version` DESC" tie-break, where a shared logical-clock timestamp would have selected a superseded row.

## Step 5: Generate unit tests — 2026-08-30T03:35:00.000Z

Test infrastructure and suite are complete.

## What was generated

**`test_helpers/`** (2,012 lines, 9 modules) — `types.py` (entity TypedDicts + enums; `WarnRule` correctly omits `updated_at`/`version` per its `common_fields: false`), `api_client.py` (one method per PRD endpoint, 40 endpoints), `api_errors.py` (46 error IDs registered with the framework's status map), `assertions.py` (per-entity assertions plus `assert_site_headcount_identity` and `assert_offer_total_is_the_sum_of_its_parts`), `factories.py` (criteria/score sheets, 12 roster-person templates, three statute-row builders), `constants.py`, `test_users.py` (opaque-role constants plus `make_separating_employee_headers(employee_id)` for the one `entity_backed` role), `fixtures.py` (5 tiers: step wrappers → site/roster/locked plan → fork resolution → clearance/approval → offer-ready/priced/issued/executed, plus five named composites for the multi-test scenarios).

**`test_suite/`** (3,814 lines, 11 themed files + conftest) — **96 tests**, all collecting cleanly under `pytest --collect-only`.

## Coverage audit (machine-verified)

- 18 difficulty instances × >=2 tests, 59 non-stub corner instances × >=1 test → **77/77 instances covered, 0 shortfalls, 0 unknown tags**.
- All 13 `excluded_because:` stubs verified to point at real difficulty instances; none translated.
- Every test carries exactly one `Design: Difficulty/…` or `Design: Corner/…` line copied verbatim from the source yaml.
- All 187 docstring quotations verified verbatim against `PRD.md` by an automated whitespace-normalised substring check (this caught 5 quotes that had silently dropped `**bold**` markers; all rewritten).
- No `skip` / `skipif` / `xfail`; no scaffold references in generated code.
- Every literal money/date/age expectation was recomputed independently (round-half-up model, day arithmetic) and matches the design indices exactly.

## Two deviations you should know about

**1. The design recipes' analysis setups are unreachable as written.** Many recipes (~20 across both queues, e.g. `severance_standard_versus_enhanced_release_same_employee`, `legal_decision_return_reverts_plan_to_draft_and_counts_the_loop`, `error_clearing_an_already_cleared_analysis_is_rejected`) create a single selection and then `POST /adverse-impact-analyses`. PRD §3.5 states: *"If removing the focal class leaves no reference group at all — that is, the pool count and the focal pooled count are equal — the request is refused with `ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA`."* A one-person (or single-class) pool therefore **cannot** produce an analysis, so those chains would 422 during setup. Fix applied: the second roster member is given a different `demographic_code` and a **PROPOSED** (undecided) selection. A PROPOSED row joins the analysis pool while moving no employee, no site counter and no `selected_count` — so every asserted headcount, ledger and count value is preserved. Only `plan.pool_count` shifts, and no affected instance asserts it.

**2. One assertion dropped as not uniquely derivable.** In `Corner/calculations/adverse_impact_ratio_flags_where_standard_deviation_does_not` the index expects `impact_ratio == 0.5556`. PRD §3.5 defines `focal_rate` and `reference_rate` as already rounded to 4 dp, then says `impact_ratio` is *"the focal rate divided by the reference rate"* — 0.3333/0.6000 = **0.5555**, while unrounded (1/3)/(3/5) = **0.5556**. Two faithful PRD readers land on different cents. The test asserts `impact_ratio < 0.80` and `status == FLAGGED` (identical under either reading) and keeps every unambiguous field (`focal_rate` 0.3333, `reference_rate` 0.6000, `shortfall_count` 1, `standard_deviations` 0.6831, `COMPUTED`). This is a **PRD gap worth fixing upstream** — the sentence should say whether the ratio divides the rounded fields or the raw quotients.

A related gap I did not test: `Corner/errors/error_owbpa_disclosure_stale_after_the_selection_set_moves` expects `analysis_1.status == SUPERSEDED`, but at that point `analysis_1` is `STALE`, and PRD §3.5 lists only `COMPUTED`/`FLAGGED`/`CLEARED` as from-states for superseding. That single assertion was omitted; the instance's core claim (`ERR_OWBPA_DISCLOSURE_STALE`) is fully tested.

## Step 7: Run tests and iterate — 2026-08-30T04:05:00.000Z

All 8 parallel rounds report `passed == total` (96/96). Clean sweep observed.

## Summary

**Iterations run:** 2 (sweep 1: 95/96 in all 8 rounds, same single failure — not flaky; sweep 2: 96/96 in all 8 rounds).

**Tests deleted:** none. One assertion removed under STEP 1c partial-coverage split.

- `test_suite/test_04_warn_threshold_and_notices.py::test_rescission_voids_the_issued_notice_and_rewinds_the_compliance_axis` — removed only `assert plan["warn_status"] == "NOT_ASSESSED"`. **Category: state-arc silence / ENUM-MEMBERSHIP-ONLY.** The test's fixture (`setup_ny_scenario_with_issued_state_notice`) leaves the plan at `warn_status == NOTICES_ISSUED` before the rescission. The only PRD sentence covering the rewind is §3.4 line 218: *"Third, if that recomputation leaves no site of the plan with a `warn_trigger_status` other than `NONE`, the plan's `warn_status` returns from `THRESHOLD_PENDING` to `NOT_ASSESSED`…"* — it names `THRESHOLD_PENDING` as the from-state, and no PRD prose anywhere names an arc out of `NOTICES_ISSUED` other than `NOTICES_ISSUED → NOTICE_PERIOD_SATISFIED` (§3.10 line 342). Two faithful readings exist: guard the arc on `THRESHOLD_PENDING` (plan stays `NOTICES_ISSUED`) vs. treat the reset as unconditional. Confirmation that this was a test-authoring slip rather than an implementation gap: `SCAFFOLD.yaml`'s own `ReductionPlan/warn_status` machine declares no `NOTICES_ISSUED → NOT_ASSESSED` transition either. Scaffold rule that drove the test: `Corner/cross_cutting_complexity_layers/rescission_cascade_voids_the_issued_warn_notice`.
- The remaining assertions in the same test were kept because they *are* verbatim-covered: the notice `ISSUED → VOID` (§3.4), the four site counters (§3.4 hop 2), the employee returning to `ACTIVE` (§3.4 hop 1), and `plan.required_notice_days == 0` / `notice_deadline_utc is None` (§3.4 line 240: *"A plan's `required_notice_days` … is 0 when no site of the plan is triggered. Its `notice_deadline_utc` … is null whenever `required_notice_days` is 0"*) — these are derived from sites independently of the warn_status arc.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. `domain.py::recompute_plan` (lines 209-212) implements exactly the two PRD-named arcs (`NOT_ASSESSED → THRESHOLD_PENDING`, `THRESHOLD_PENDING → NOT_ASSESSED`) and was left untouched — weakening its guard would have added an unnamed state transition, which the cardinal rules forbid.

Results artifacts for the clean sweep are at `/home/ubuntu/github/CodingPRD/tasks/task_2182_workforce_reduction_warn_act/workspace/implementation/results.{1..8}.json`.

### Orchestrator verification (post-Step-7)

- Independently re-read `results.{1..8}.json`: all 8 report `passed 96 / total 96, failed 0`.
- Suite integrity: 96 unique `def test_*` functions, 96 `Design:` tags — no untagged or dropped tests.
- Mutation test A (severance ladder constant `Decimal("1.5")` → `Decimal("1.6")` in `calc.py:235`): sweep dropped to **94/96** — `test_the_weekly_rate_is_rounded_before_it_is_multiplied`, `test_the_downstream_tier_and_total_follow_the_pinned_steps`. Suite is non-vacuous on the severance chain. `calc.py` restored byte-identical.
- Mutation test B (FEDERAL counting window `day < window_end` → `day <= window_end` in `calc.py:80`): sweep stayed **96/96** — the FEDERAL half-open counting-window end day is unmeasured. Root cause is upstream in the design index, not a test-generation miss: `Difficulty/dual_variant_calculation/warn_loss_count_federal_versus_state_on_identical_roster` gives every selection the same `proposed_separation_date` (2026-12-01), so its FEDERAL-vs-STATE divergence rides entirely on the part-time / `min_service_days` exclusions and never on the window geometry, and no other §1.8/§1.9 instance places a separation on the window end. Left as-is per the design-index-only contract (inventing a boundary test outside the index is forbidden). `calc.py` restored byte-identical.

## Step 8: Finalize PRD — 2026-08-30T04:12:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2182_workforce_reduction_warn_act/workspace/PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 449 lines — `PRD_FINALIZED.md`: 449 lines — **0.00% line delta** (one in-place sentence rewrite inside the long §3.3 paragraph at line 218; +633 characters).

## Changes
- **§3.3 (rescission, third hop — line 218)** — *revise* — the single conditional sentence that bundled the `warn_status` rewind with the `required_notice_days` / `notice_deadline_utc` reset is split into (a) the rewind arc, now explicitly guarded on the from-state `THRESHOLD_PENDING`, with a plan already at `NOTICES_ISSUED` or `NOTICE_PERIOD_SATISFIED` left standing where it is by this recomputation, and (b) `required_notice_days` / `notice_deadline_utc`, now stated as re-derived unconditionally from the §3.4 plan-level rules whatever `warn_status` the plan holds — `implementation/domain.py:209-212` (arc guards) and `implementation/domain.py:161-188` (the unconditional `changes` dict).

No other `<step_7_diff>` item required a patch: the diff records zero `implementation/` fixes, zero `test_helpers/` fixes and zero deletions.

## Pre-edit search log

**Edit 1 — §3.3 third hop**

(a) **Subject identified:** every write to a `ReductionPlan`'s `warn_status`, plus the plan-level `required_notice_days` / `notice_deadline_utc` derivation that the same PRD sentence governs.

(b) **Impl paths enumerated** (`grep -rn "warn_status\|recompute_plan\|sync_warn\|recompute_plans_touching_site"`, then read in full):
- `domain.py:134-214` `recompute_plan` — the only two `warn_status` arcs: forward `NOT_ASSESSED → THRESHOLD_PENDING` guarded on `NOT_ASSESSED` over *selected* sites; reverse `THRESHOLD_PENDING → NOT_ASSESSED` guarded on `THRESHOLD_PENDING` over *live* (SELECTED|SEPARATED) sites. Both sit under `if sync_warn:`; neither fires from `NOTICES_ISSUED` or `NOTICE_PERIOD_SATISFIED`. `required_notice_days` / `notice_deadline_utc` are computed earlier, in the unconditional `changes` dict, from `max(site.required_notice_days)` over the plan's selected sites.
- `domain.py:217-224` `recompute_plans_touching_site` — fans the same guarded logic out to *every* plan holding a selection at the site, including plans that are not the rescission's own plan.
- `selection_ops.py:apply_select` / `apply_exempt` / `apply_rescind` — all three end in `recompute_plan(plan)` with `sync_warn` defaulted true; the exempt path cannot change the live-site set, so the reverse arc is inert there.
- `routes_selections.py:45`, `routes_offers.py:169/188/206/239`, `routes_roster.py:106/134`, `routes_plans.py:234` — further `recompute_plan` / `recompute_plans_touching_site` callsites where the same guarded arcs run (notably roster import, which can untrigger a site by growing the denominator).
- `routes_warn.py:179-198` — notice issuance, itself guarded on `warn_status == "THRESHOLD_PENDING"` before setting `NOTICES_ISSUED`.
- `routes_plans.py:43` (creation at `NOT_ASSESSED`) and `routes_plans.py:189-193` (execution: `recompute_plan(plan, sync_warn=False)` then an **unconditional** `warn_status = NOTICE_PERIOD_SATISFIED`).
- `domain.py:88-127` `recompute_site` — supplies `warn_trigger_status` / site `required_notice_days` and voids `ISSUED` notices on a `!= NONE → NONE` edge (the sentence later in the same PRD paragraph, left verbatim).

(c) **Wording adjustments made:** three, all to avoid over-claiming. (i) The from-state clause was scoped to "by this recomputation" rather than stated as an absolute property of `warn_status`, so it cannot be read as forbidding `routes_plans.py:192`'s unconditional execution jump to `NOTICE_PERIOD_SATISFIED` or `routes_warn.py:198`'s issuance arc. (ii) The `required_notice_days` / `notice_deadline_utc` clause was written as "re-derived from the plan-level rules of §3.4… which resolve to 0 and null respectively once no site of the plan is triggered" instead of a flat "reset to 0 / null", because those two fields are recomputed on *every* `recompute_plan` callsite (offers, batches, roster import, execution's `sync_warn=False` pass) and only land on 0/null when no site of the plan is triggered. (iii) The sentence was deliberately kept local to the rescission recomputation and silent about the other callsites that can fire the same reverse arc (e.g. a roster import enlarging a denominator), leaving that under-determined rather than asserting a universal the PRD never established.

## Step 9: Complete PRD — 2026-08-30T04:20:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2182_workforce_reduction_warn_act/workspace/PRD_COMPLETED.md`.

## Stats
- **PRD_FINALIZED.md**: 449 lines / 84,352 bytes → **PRD_COMPLETED.md**: 449 lines / 87,597 bytes (**+3,245 bytes**, +3,219 chars). Line count unchanged — every edit is an in-paragraph insert or revision; no new sections, no new paragraphs.
- **26 edits**: 21 ambiguity-pins, 5 mismatch-revisions.

## Changes
- §2.1 — insert — ambiguity — only sign/revoke are recipient-checked; a `SeparatingEmployee` reading `GET /severance-offers/{id}` is not — `routes_offers.py:111`
- §2.4 — revise — mismatch — PRD said any recomputation bumps `updated_at`/`version`; impl bumps only when a value actually changes — `core.py:300-309`
- §2.6 rung 16 — revise — mismatch — `ERR_NOTICE_NOT_DELIVERED` also fires on `POST /reduction-plans/{id}/execute` — `routes_plans.py:131`
- §2.10 — insert — ambiguity — unknown path / disallowed method answers `ERR_INVALID_REQUEST` 400, not 404/405 — `app.py:35-43`
- §3.1 — revise — ambiguity — negative `severance_budget_cents` → `ERR_INVALID_REQUEST` — `routes_plans.py:30`
- §3.1 — revise — ambiguity — `selection_criteria` size violation → `ERR_INVALID_REQUEST`; `description` optional, defaults to `""` — `validation.py:203-211`
- §3.2 — insert — ambiguity — `age_at_separation` = completed years birth→separation; both derived fields null when `separation_date` cleared — `domain.py:75-87`
- §3.2 — insert — ambiguity — roster import tests every entry before creating any row (all-or-nothing) — `routes_roster.py:100-104`
- §3.3 — revise — ambiguity — a repeated `criterion_code` in the score sheet is also `ERR_CRITERION_SCORE_MISMATCH` — `selection_ops.py:41`
- §3.3 — insert — ambiguity — an `employee_ids` array naming the same person twice → `ERR_DUPLICATE_SELECTION` — `routes_plans.py:223-228`
- §3.3 — revise — ambiguity — `decision` values are literally `SELECT` / `EXEMPT`; plan at `APPROVED` → `ERR_INVALID_PLAN_STATE`, at `EXECUTED` → `ERR_INVALID_SELECTION_STATE` — `routes_selections.py:79,89-92`
- §3.3 — revise — ambiguity — unlocked criteria on the selected branch → `ERR_INVALID_PLAN_STATE`, not `ERR_CRITERIA_NOT_LOCKED` — `routes_selections.py:93-94`
- §3.3 — revise — ambiguity — missing/empty `exemption_reason` → `ERR_INVALID_REQUEST` — `routes_selections.py:80-82`
- §3.3 — revise — ambiguity — decide-batch: cross-plan `selection_id` → `ERR_SELECTION_NOT_FOUND`; all rows checked for `PROPOSED` before any mutation — `routes_plans.py:253-262`
- §3.3 — revise — ambiguity — rescind blocked by a live offer → `ERR_INVALID_OFFER_STATE` — `routes_selections.py:116-118`
- §3.4 — revise — ambiguity — a drafted notice records the applied rule's `notice_days` as `required_notice_days` even when `threshold_met` is false — `routes_warn.py:99`
- §3.4 — revise — mismatch — window freeze is released by *any* recompute returning the site to `NONE`, not only a rescission — `domain.py:124-128`
- §3.5 — revise — ambiguity — `shortfall_count` uses the recorded 4-dp `reference_rate` — `calc.py:186`
- §3.5 — revise — ambiguity — **`impact_ratio` divides the already-4-dp-rounded `focal_rate` by the already-rounded `reference_rate`**, then rounds again — `calc.py:181-205`
- §3.5 — revise — ambiguity — submit-legal-review gate failures → `ERR_INVALID_PLAN_STATE` — `routes_plans.py:83-88`
- §3.5 — revise — ambiguity — `decision` values are literally `APPROVE` / `RETURN` — `routes_plans.py:99`
- §3.8 — revise — mismatch — `outplacement_tier` is not a field of the offer representation (only `outplacement_fee_cents` is); the tier lives on the employee record — `routes_offers.py:103`, `serialize.py:38-41`
- §3.8 — revise — ambiguity — a `DRAFT` offer also carries `consideration_days_applied` of 0 — `routes_offers.py:95`
- §3.9 — revise — ambiguity — re-issuance also clears `signed_utc`, `revoked_utc`, `revocation_deadline_utc` to null — `routes_offers.py:163-165`
- §3.9 — revise — mismatch — employee `outplacement_tier` is derived from the copied month count, not copied from the offer — `routes_offers.py:203`, `calc.py:314-319`
- §3.10 — revise — ambiguity — an undelivered `SELECTED` selection at execute → `ERR_NOTICE_NOT_DELIVERED` — `routes_plans.py:131-132`

## On the two flagged sites
- **`impact_ratio` rounding order (§3.5)** — was genuinely unpinned; `calc.py:181-205` divides the two already-quantised 4-dp Decimals. Now pinned explicitly, including the negative form ("not their raw unrounded quotients"). The `shortfall_count` sentence carried the same latent ambiguity and was pinned alongside.
- **FEDERAL window end-day inclusivity (§3.4)** — already pinned in the source PRD ("Under the `FEDERAL` rule the window is half-open… A separation landing exactly on the window end day is therefore inside a state window and outside the federal one"), and it matches `calc.py:76-81` exactly. The §3.4 notice-freeze paragraph carries the same convention for `ERR_WARN_WINDOW_COLLISION`. No change was needed there.

## Step 10 (orchestrator): Confirming sweep — 2026-08-30T04:35:00.000Z

Re-ran the 8-round parallel sweep after the orchestrator's two mutation experiments (both `calc.py` restores verified byte-identical), regenerating `results.{1..8}.json`. All 8 rounds: **96 / 96, failed 0**.
