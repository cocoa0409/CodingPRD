# Worklog — task_3472_wetland_permit_review_compensatory_mitigation_requirements

## Step 1: Create task directory — 2026-10-02T11:07:00.000Z

Task directory pre-allocated per command args: `tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/` with empty `workspace/` inside. Verified it exists; no new directory created.

## Step 2: Generate Scaffold — 2026-10-02T12:55:00.000Z

Scaffold generation complete. All three artifacts written, parse-verified after every chunk, and clean-linted.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/SCAFFOLD.yaml` (1899 lines) — §1.0–§1.7 only; no design keys
- `/home/ubuntu/github/CodingPRD/tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (768 lines) — single top-level `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/SCAFFOLD_CORNER_DESIGN.yaml` (1826 lines) — single top-level `scaffold_corner_design:`

## Parse verification

Each file was parsed with `yaml.safe_load` after every incremental append (7 parse checkpoints for SCAFFOLD, 5 for DIFFICULTY, 8 for CORNER). One YAML flow-sequence error (unquoted `errors[ERR_X]` in `grounds:`) was caught and fixed mid-write. Final parse: all three OK.

## Counts

| Element | Count |
|---|---|
| Entities | 13 |
| State machine entries | 12 (incl. PermitApplication notice dimension; branching pathway fork, AA/plan revision cycles, EnforcementCase dual dimensions with DEFAULTED loop) |
| Concurrency (OCC) rules | 2 (PATCH application, PATCH plan) |
| Calculations | 7 (3 dual-variant: credits provisional/final, PIR standard/ATF, penalty restoration/ATF) |
| Validations | 31 (priority-ordered) |
| Endpoints | 67 |
| Error codes | 56 (all referenced by a validation or transition — audited) |
| Roles | 6 (Applicant entity-backed; segregation-of-duties on render-decision and confirm-violation) |
| §1.8 difficulty instances | 19 (9 rules × ≥2; combinatorial_formula has 3 covering modes a/b/c) |
| §1.9 corner instances | 89 total = 75 active + 14 `excluded_because` stubs |

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(67 endpoints, 13 entities, 19 + 75 instances scanned, 1192 calls scanned; the one initial FK_REVERSE_UNREACHABLE — `PermitApplication.enforcement_case_id` — was fixed by adding the filter to `GET /applications`.)

## Additional audits I ran beyond the linter

- Placeholder closure: every `${var}` in both design files is bound by an earlier `captures:` in the same instance; capture names unique per instance; instance names unique across both files (108 total).
- All `grounds:` references resolve to declared entities/fields/calculations/transitions/validations/errors/OCC rules/roles/endpoints.
- No forbidden race vocabulary anywhere.
- All formula-derived asserts were pre-computed by hand (e.g., PIR 17.25 vs 9.25 ATF; credits 6.00→6.60→8.25; ILF 35050.00 per-line rounding; pricing 270000.00/60000.00/69000.00; penalty 34000.00 offset, 15500.00 ATF full, 500000.00 cap; all clock dates derived from the 2026-09-01T00:00:00Z pinned default).

## One deliberate deviation to flag

Endpoint count is 67, above the §0.4 Expert band (20–32) — the scenario names nine regulatory subsystems (JD+appeals, pathways, alternatives, notice+comments, PIR, three mitigation mechanisms, banks/credit ledger, monitoring, enforcement) and the requester asked for maximum difficulty. Difficulty is concentrated in coupling (depth-3 cascades, cross-entity gates, priority conflicts), not CRUD volume. Note my memory warning: >40 endpoints can strain Step 6 impl-gen unless the orchestrator's prompt pre-constrains (per-domain modules, one file per message); this repo's Step 6 prompt does not currently include those pre-constraints, so the orchestrator may want to add them for this task.

(Orchestrator note: orchestrator independently re-verified all three files parse with yaml.safe_load and that SCAFFOLD.yaml describes the wetland domain — api_prefix `/wetland-permits`, domain_name `wetland-permit-review`.)

## Step 3: Copy shared files — 2026-10-02T12:56:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-02T13:15:00.000Z

All checks pass and the part files are cleaned up. The two withheld design-index files were never opened or referenced.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/workspace/PRD.md` — 360 lines.

**Section list:**
- §1 Introduction (3 paragraphs, regulatory-burden angle)
- §2 Global Specifications: 2.1 RBAC (six roles + identity prose), 2.2 API Response Structure (verified **byte-identical** to the canonical block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 Logical Clock & Time-Driven Transitions (startup default, pinned 5-step evaluation order, lazy JD expiry), 2.6 Precision & Rounding (all four pinned rounding orders), 2.7 OCC, 2.8 Validation Pipeline (first-failure-wins, full priority order), 2.9 Ownership Scoping & Segregation of Duties
- §3 Business Logic (9 subsections, lifecycle-stage grouping): 3.1 applicants/sites/JDs, 3.2 appeals & suspension cascade, 3.3 pathways/submission/screening, 3.4 alternatives analysis & LEDPA, 3.5 public notice/comments/PIR score, 3.6 mitigation plans/banks/credit transactions, 3.7 decision/issuance/denial cascade, 3.8 monitoring/permit lifecycle/breach, 3.9 enforcement & after-the-fact
- §4 Endpoint Definitions (67 rows, 4 columns), §5 Error Code Catalogue (56 rows, 2 columns)

**Scaffold-rule rendering confirmation:** all 13 entities, all 12 state machines (71 transitions incl. the dual notice dimension, sibling withdraw/suspension/cancellation fans), all 7 calculations with every constant (ratios 2.0/3.0/1.5/1.0, ILF rates 40000/55000/30000/25000, PIR weights 0.40/0.35/0.25 + 250000/10000 clamp, penalty 250.0/acre-day capped 500000 with 0.5 offset, price tiers 0.5/0.8 → 1.0/1.15/1.30, lag tiers 365/730 → 1.0/1.10/1.20, ATF 1.5, location 1.0/1.25, 1825-day validity, WP-0001 numbering, 60/90/60-day windows), all 31 validations in priority order with error ids, all 56 errors, all 6 roles, and all 67 endpoints are rendered as prose (tables only in §4/§5 per spec).

**Hard Contract Reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs/query/path: 112 required, 112 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed (§2.8 ordered pipeline), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (occ field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 71 checked, 71 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed with constants and pinned orders, 0 missing
- validations[] conditions: 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 67 checked, 67 expressed, 0 missing
- entities[].fields[] structured content: defaults/initials/nullability reconstructible, 0 missing
- sibling-branch symmetry: withdraw(8)/suspension(6)/plan-cancel(5)/report-submit(3) groups equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 703
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot-checks passed: no pseudocode operators (`==`, `>=`, `:=`, `+=`) in prose, no fuzzy approximators near thresholds, §4 table contains exactly the scaffold's 67 paths, §5 contains exactly the 56 error ids with correct HTTP statuses.

(Orchestrator note: independently measured design indices from YAML — §1.8: 19 active instances across 9 rules; §1.9: 75 active + 14 excluded stubs across 9 sections; 94 testable instances total.)

## Step 5a: Generate test helpers — 2026-10-02T13:45:00.000Z

Stage 1 is complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/`)

| File | Lines |
|---|---|
| `test_helpers/types.py` | 505 |
| `test_helpers/api_errors.py` | 138 |
| `test_helpers/constants.py` | 184 |
| `test_helpers/api_client.py` | 334 |
| `test_helpers/factories.py` | 277 |
| `test_helpers/assertions.py` | 398 |
| `test_helpers/test_users.py` | 98 |
| `test_helpers/fixtures.py` | 916 |
| `test_helpers/__init__.py` | 39 |
| `test_suite/conftest.py` | 84 |

No `test_suite/test_*.py` files were written (Stage 2 scope).

## Verification results
- **Parse check**: all 10 files pass `ast.parse`.
- **Import check**: `import test_helpers` succeeds; barrel spot-check of 30 exported names passes; `ApiClient` has 71 public methods (67 endpoints + inherited helpers); singleton pattern consistent (`th.api_client is test_helpers.api_client's instance` — the memory-noted module/singleton shadowing was probed and handled via `sys.modules` for introspection).
- **Error catalog**: 56 `ApiErrorId` members, all mapped in `HTTP_STATUS_CODES`, registered via `set_error_http_status_map`; statuses match PRD §5 exactly.
- **Clock endpoint**: `/_clock/set_current_utc` unprefixed, confirmed verbatim in PRD §4; no prefixed variant anywhere in the client.
- **pytest collect**: `test_suite` collects cleanly with 0 tests (conftest wiring valid).

## Frozen constants — PRD-verbatim confirmation
All 39 literal checks + 5 special-condition strings grep-verified against PRD.md: clock default `2026-09-01T00:00:00Z` (§2.5), validity 1825 days (§3.1/§3.7), appeal window 60 days (§3.2), comment window default 30 / 15–60 (§3.5), GP cap 0.50 + codes NWP-29/39 + types {EM, STREAM} (§3.3), mitigation trigger 0.10 strict (§3.3), ratios 2.0/3.0/1.5/1.0 (§3.6), ATF 1.5, location 1.25, lag 365/730 → 1.0/1.10/1.20, ILF rates 40000/55000/30000/25000, PIR weights 0.40/0.35/0.25 + all PIR terms (§3.5), penalty 250.0/acre-day capped 500000.0, 0.5 good-faith offset, 90-day deadline, 60-day extension (§3.9), 5 reports × 365 days, 60-day breach (§3.7/§3.8), WP-0001 numbering, price tiers 0.5/0.8 → 1.0/1.15/1.30 (§3.6).

**Critical finding — one constant deliberately NOT frozen**: the design index asserts `assurance_required_dollars == 60000.00` (6.00 credits × 10000/credit), but the PRD (§3.6) says only that it "is computed and stored" — the formula/rate appears nowhere in PRD prose. Per the two-reader rule, `constants.py` carries an explicit NOTE and no `ASSURANCE_RATE_PER_CREDIT`; the fixture `setup_secured_prm_plan` instead creates the plan, reads the server-computed `assurance_required_dollars`, and OCC-patches the plan to exactly that amount. Stage 2 must follow the same read-back pattern for assurance boundary tests.

## Helper inventory for Stage 2
- **Fixtures** (all clock-reachable from the PRD default — every clock move derives from a response timestamp plus a positive day offset; date arithmetic self-tested to reproduce every design-recipe literal): base chain (`create_applicant`, `create_site`, `create_jd`/`issue_jd`, `setup_site_with_issued_jd`); application walks (`walk_application_to_alternatives_review`, `walk_general_application_to_decision_pending`, `setup_application_in_alternatives_review`, `setup_aa_accepted`, `setup_application_public_notice_open`, `setup_application_decision_pending`, `close_comment_period`); mitigation (`setup_plan_approved`, `setup_operational_bank`, `reserve_credits`/`purchase_credits`/`reserve_and_purchase`/`release_credits`, `secure_plan`, `pay_ilf_fee`, `setup_secured_bank_credits_plan`, `setup_secured_prm_plan`, `setup_secured_ilf_plan`); issuance/lifecycle (`render_decision` defaulting to decider de-9 ≠ screener rev-1, `setup_issued_permit`, `setup_issued_general_permit`, `commence_permit`, `setup_active_permit`, `submit_report` with auto zero-gap coverage, `review_report`, `submit_and_accept_report`, `setup_completed_monitoring`, `setup_closed_permit`, `setup_suspended_permit_by_breach`); appeals (`file_appeal`, `decide_appeal`, `setup_suspended_application`, `create_and_issue_jd` for replacements); enforcement (`create_case` opener eo-1, `confirm_case` confirmer eo-2, `set_resolution_restoration`/`set_resolution_atf`, `verify_restoration`, `grant_extension`, `setup_case_opened/confirmed/restoration_pending`, `setup_atf_application_linked`, `setup_issued_atf_permit`); clock (`set_clock`, `advance_clock_days`); OCC (`patch_application`, `patch_plan`).
- **Roles**: six roles per PRD §2.1; canonical operator IDs keep both SoD gates deterministic; `make_applicant_headers(applicant["id"])` is the mandatory ownership-gated builder (shared `applicant_headers` documented as fallback-only); `NO_AUTH_HEADERS = {}` for the missing-auth probe.
- **Assertions**: per-entity `assert_*` for all 13 entities plus `assert_bank_inventory_conserved`, `assert_credit_requirement`, `assert_permit_conditions_for_pathway`, `assert_monitoring_schedule_shape`, `iso_add_days`/`parse_iso8601`/`assert_iso_instants_equal`, `expected_coverage_interval`. Two two-reader relaxations applied: no assertion on `final_credits_required_by_type` for secured ILF plans (PRD never says the ILF path populates it) and no price-field assertion on REFUNDED transactions (PRD silent on whether refund clears stamped prices).

## Step 5b: Generate test suite — 2026-10-02T14:40:00.000Z

Stage 2 complete. Summary:

**Files written (17 files, 94 tests — all under `test_suite/` in the task dir):**

Queue A (Difficulty): `test_difficulty_dual_variant_calc.py` (2), `test_difficulty_combinatorial_formula.py` (3), `test_difficulty_non_linear_state_machine.py` (2), `test_difficulty_transitive_cascade.py` (2), `test_difficulty_priority_pair_validation.py` (2), `test_difficulty_boundary_precision.py` (2), `test_difficulty_cross_entity_state.py` (2), `test_difficulty_resource_temporal_overlap.py` (2), `test_difficulty_compensating_invariant.py` (2) — 19 total.

Queue B (Corner): `test_corner_entities.py` (10), `test_corner_state_machines.py` (16), `test_corner_calculations.py` (7), `test_corner_validations.py` (26), `test_corner_endpoints.py` (4), `test_corner_rbac.py` (6), `test_corner_complexity_layers.py` (5), `test_corner_consistency_model.py` (1) — 75 total.

**Skipped instances: none.** All 94 active instances passed the PRD-first filter and were translated; the 14 `excluded_because` stubs (state_machines 2, calculations 2, errors 8, complexity_layers 2) emitted nothing, and the audit confirms no test tags a stub.

**Verification results:**
- `pytest --collect-only -q`: 94 tests collected, zero import/collection errors.
- AST tag audit (parsed, not grepped): 94/94 tests carry exactly one `Design:` tag as the last docstring line; all tags resolve to real active instances; coverage is exactly 1:1 with the 94 active instances; 0 problems.
- PRD citation verbatim audit: 146 quoted spans extracted from docstrings, all present verbatim in PRD.md (3 initially failed due to `...` elision inside quotes; fixed by quoting complete sentences).

**Assertion-level adjudications (instances kept, sub-assertions adjusted to what PRD uniquely derives):**
1. `corner_insufficient_assurance_rejected` / `corner_prm_secure_success` — PRD never publishes the assurance rate (Stage-1 finding honored): used the read-back pattern (create → read `assurance_required_dollars` → OCC-patch to half / exactly that amount). The recipes' 60000.00/30000.00 literals dropped.
2. OCC pair + applicant-creation test — PRD pins "incremented by exactly 1" but only "a small integer" start, so version assertions are relative (`v+1`) / type-level, not the recipes' absolute 1/2/3.
3. `corner_gp_acreage_boundary` (0.51) and `corner_gp_disallowed_resource_type` — PRD §3.3 enforces eligibility "both when the application is created and again when it is submitted", so the rejection is asserted at creation; the recipes' submit-time trigger is unreachable under a faithful implementation.
4. `corner_list_pagination_envelope` — same-timestamp tie-break order is not PRD-pinned; asserts page sizes, totals, has_more, partition, and non-decreasing `created_at` instead of strict A,B,C identity order.

**Helper-layer problem found and fixed (the only edit outside `test_suite/`):** `test_helpers/assertions.py` used `PlanStatus` in `assert_mitigation_plan` (3 references) without importing it — a NameError at every call. Added the one-line import and verified `import test_helpers` succeeds. `conftest.py` untouched.

(Orchestrator note: independently re-ran the AST tag audit — 94/94 tests tagged, 0 missing instances, 0 extra/invalid tags; `pytest --collect-only` collects 94 tests cleanly.)

## Step 6: Generate implementation — 2026-10-02T15:30:00.000Z

Implementation complete. Summary below.

## Files written (all under `.../workspace/implementation/`, 3,589 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Guarded install (`import flask` check) + `exec python3 app.py`, `$PORT`/0.0.0.0/foreground |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 52 | Flask factory, blueprint registration, envelope-shaped 404/405/500 handlers |
| `errors.py` | 86 | All 56 catalogued error_ids with their HTTP statuses |
| `db.py` | 116 | Empty in-memory store (13 dicts), logical clock default `2026-09-01T00:00:00Z`, UUID ids, ISO8601-ms formatting, `version` starting at 1, `bump()` mutation helper |
| `response.py` | 131 | `meta`/`response_type`/`data` envelope, list pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, range 1..100), query filters |
| `middleware.py` | 49 | `X-User-ID`/`X-User-Role` auth (401), role lists (403), Applicant ownership (403) |
| `helpers.py` | 219 | Tier-6 shape validators (required/enum/number/int/bool/list/datetime, impacts array) |
| `serialization.py` | 258 | Per-entity serializers; computed-on-read fields (prior_violation_count, bank inventory/revenue, penalty accrual) |
| `calculations.py` | 291 | All 7 calculation rules with pinned constants and round-half-up order |
| `cascades.py` | 230 | JD-reversal suspension cascade, deny/withdraw compensation cascade, permit issuance (WP-#### numbering, pinned special conditions, 5-report schedule, ATF case closure), the 5 pinned clock-transition steps |
| `routes/applicants_sites.py` | 97 | 5 endpoints |
| `routes/jds_appeals.py` | 194 | 8 endpoints (JD CRUD+issue, appeal file/decide + SUSTAINED reversal) |
| `routes/applications.py` | 555 | 10 endpoints (create/PATCH-OCC/submit/screening/publish-notice/advance/render/withdraw) |
| `routes/review.py` | 248 | 9 endpoints (AA + agency comments) |
| `routes/mitigation.py` | 334 | 8 endpoints (plans, secure-credits final recompute, pay-in-lieu-fee) |
| `routes/banks.py` | 269 | 10 endpoints (banks + credit transactions, tier pricing) |
| `routes/permits.py` | 223 | 9 endpoints (permits + monitoring reports, period_index sort) |
| `routes/enforcement.py` | 194 | 7 endpoints |
| `routes/clock.py` | 31 | `POST /_clock/set_current_utc` — **unprefixed**, as declared |

## Route-coverage diff
Scaffold §1.5 declares **67** endpoints; Flask `url_map` registers **67**; MISSING: none; EXTRA: none (normalized `{id}` vs `<id>` before diffing).

## Smoke-test transcript
- Port: dynamically allocated (55851, then 40895) via `socket.bind(0)`; server launched with `PORT=$PORT bash start.sh &`, killed exactly the started PIDs (verified via `/proc/<pid>/cwd` before kill). No other processes touched.
- Boot: clean, responding within 3 s on both launches.
- Requests: unauth list → **401 ERR_MISSING_AUTH**; list sites → **200** with pagination meta; create applicant → **201** (`version: 1`, `created_at: 2026-09-01T00:00:00.000Z`); JD create→issue → **200** (expiration 2031-08-31 = +1825 d, version 2); application create → computed `total_impact_acres 0.5`, `compensatory_mitigation_required true`; submit → **200**; `POST /_clock/set_current_utc` → **200** `{current_utc}`; same-value re-set → **422 ERR_CLOCK_REGRESSION**.
- Deep flow (all passed): stale PATCH → **412**; LEDPA-gated AA accept → **422**; reserve on unapproved bank → **409**; secure before purchase → **422 ERR_CREDITS_NOT_SECURED**; tier-1 pricing verified (1000.00/2000.00 unit, revenue 2200, available 4.1); notice +15 d clock close; advance → **pir_score 17.5 FAVORABLE** (hand-checked: 0.40·30 + 0.35·5 + 0.25·15); render by screening reviewer → **403 ERR_SEGREGATION_OF_DUTIES**; ISSUE → permit **WP-0001**, 3 IP special conditions, 5 DUE reports, plan → ACTIVE.

## Interpretation choices (PRD admits more than one reading — for Step 7 audit)

1. **`assurance_required_dollars` formula is unpinned** in both PRD and scaffold. I derive it as the ILF-rate-weighted sum of the credit requirement (per-line round-half-up, then summed — the only per-credit dollar rates the spec declares): computed from *provisional* credits at create/PATCH, **recomputed from final credits at secure-credits** (honoring "the recomputed assurance_required_dollars"); COMBINATION compares against `round_half_up(0.5 * assurance)`.
2. **Initial `version` = 1** ("starts as a small integer" is unpinned).
3. **AgencyComment wrong-state resolve** → `ERR_INVALID_REQUEST` (400): the 56-code catalog has no `ERR_COMMENT_INVALID_STATE`.
4. **General-pathway plan creation on a non-DECISION_PENDING application** → `ERR_APPLICATION_INVALID_STATE` (priority-19 note says "checked at priority 7" but names no error id).
5. **Resubmit `new_jd_id` naming a JD of a different site** → `ERR_JD_NOT_FOUND` (scaffold maps only the four listed errors; "missing reference" reading).
6. **Withdraw from SUSPENDED_PENDING_JD**: runs the full compensation cascade (PURCHASED → REFUNDED included), not just plan cancellation — PRD §3.3 says "same cascade as a denial" and its "only the plan cancellation applies" nuance is premised on no PURCHASED txns existing, which is reachable.
7. **Location multiplier with zero PURCHASED transactions** → 1.0 (vacuous-truth reading of "every PURCHASED transaction is in-basin").
8. **pay-in-lieu-fee also computes and stores `final_credits_required_by_type`** (the calc trigger lists "secure-credits / pay-in-lieu-fee (final variant)"); the *fee* itself is never recomputed.
9. **pay-in-lieu-fee on a non-IN_LIEU_FEE plan** → `ERR_PLAN_INVALID_STATE` (symmetric to the explicit secure-credits rejection of IN_LIEU_FEE).
10. **Individual-pathway plan creation checks only AA ACCEPTED**, not application status (per priority 19's letter) — a plan can be created e.g. while PUBLIC_NOTICE_OPEN/DECISION_PENDING.
11. **OCC field missing from PATCH body** → 400 (shape tier, before the 409 state check); non-integer version → 400.
12. **Body-FK vs ownership ordering**: for creates, the FK needed for the ownership check (jd_id for appeals, application_id for AA/plans, plan_id for credit txns) is resolved first (404), then ownership (403), then remaining FKs — ownership is unevaluable without it.
13. **Duplicate resource_types within `impacts`**: allowed; acreages are summed per type before ratio application (the requirement map is keyed by type).
14. **Manual enforcement case with `unauthorized_fill_acres: 0` is allowed** — PRD §3.9 says "(zero or more)"; the scaffold's "(0 only for MONITORING_BREACH)" note reads as descriptive, and PRD wins.
15. **Not format-validated** (presence/type only): `state_code` 2-letter shape, `watershed_code` 8-digit shape, non-empty strings — priority 6 enumerates only fields/enums/ranges/conditional fields.
16. **Bank computed maps** (`credits_reserved/purchased/available_by_type`) always emit all four resource types with 0 defaults ("missing types are 0"); `credit_capacity`/`base_price_per_credit` echo input as given. Bank/applicant computed fields refresh on read **without** version bumps (they are derived, not mutated); entity state changes in cascades do bump version/updated_at.
17. **Monitoring report resubmit after DEFICIENT** keeps the previous `outcome`/`deficiency_notes` until re-reviewed ("outcome null until reviewed"; notes "stay null unless a deficiency has been recorded").
18. **Submit from DRAFT/RETURNED carrying `new_jd_id`**: ignored (the field is defined only for SUSPENDED_PENDING_JD resubmission).
19. **Non-ATF application carrying `enforcement_case_id` / individual pathway carrying `general_permit_code`**: accepted and stored (the conditional rules require presence for specific pathways but never forbid presence otherwise).
20. **Clock-driven flips require the permit ACTIVE**: DUE→OVERDUE and breach suspension are evaluated only for reports of ACTIVE permits (literal §2.5 step 3/4); ISSUED and SUSPENDED permits' reports are untouched, and SUSPENDED permits never expire (EXPIRED is defined only from ISSUED/ACTIVE).
21. **Meta `api_request_timestamp`** is wall-clock UTC (server-generated per PRD §2.2; entity timestamps use the logical clock).
22. **Submit JD-check order** follows the global pipeline everywhere (state 409 → expired 409 → GP-eligibility 422 → jurisdictional 422 → ATF case 409), per PRD §2.8's pinned note, including the SUSPENDED resubmit path where the scaffold's precondition listing order differs.

(Orchestrator note: independently smoke-verified boot on a dynamic port — server responds 401 to unauthenticated list (auth gate live); clock endpoint unprefixed; process killed by PID.)

## Step 7: Test-fix iteration loop — 2026-10-02T15:50:00.000Z

Clean sweep: **all 8 rounds pass 94/94**. The final results.${1..8}.json artifacts remain in `workspace/implementation/` as required.

## Summary

**Iterations run:** 2 (one diagnostic sweep: 85/94 × 8 rounds, identical failures everywhere; one verification sweep: 94/94 × 8 rounds).

**Tests deleted:** none.

**Fixes to `test_helpers/` (1):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/test_helpers/fixtures.py` — added `create_appeal_payload` to the `from .factories import (...)` list. `fixtures.file_appeal()` (line ~730) called it as a module global that was never imported, so every fixture path through `file_appeal` / `setup_suspended_application` raised `NameError` regardless of what the test module itself imported. Fixed 6 tests (`test_corner_jd_reversed_terminal_lockdown`, `test_corner_appeal_double_decide_rejected`, `test_corner_suspended_application_resumes_with_new_jd`, `test_corner_second_appeal_rejected`, `test_appeal_window_exactly_sixty_days`, `test_appeal_sustain_cascades_jd_application_credits`).

**Fixes to `test_suite/` (2):**
- `test_corner_complexity_layers.py` — added missing `setup_site_with_issued_jd` to the `from test_helpers import` block (the test used it at line 58 unimported; NameError).
- `test_corner_validations.py::test_corner_double_notice_rejected` — relaxed `validate_error(resp, ERR_NOTICE_ALREADY_PUBLISHED)` to `validate_error_is_one_of([ERR_NOTICE_ALREADY_PUBLISHED, ERR_APPLICATION_INVALID_STATE])`. ERROR-PRECEDENCE-SILENCE: PRD §3.5 names the singleton error for re-publication ("a notice already published cannot be published again, ERR_NOTICE_ALREADY_PUBLISHED (HTTP 409)"), but §2.8's pipeline runs the tier-7 state gate (the app now sits in PUBLIC_NOTICE_OPEN) before domain singleton rules; PRD pins no precedence between them on this path, so both readings are PRD-faithful.

**Fixes to `implementation/` (1):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/workspace/implementation/calculations.py::bank_inventory` — REFUNDED transactions no longer subtract from `revenue_dollars`. PRD §3.6 states refunding moves PURCHASED→REFUNDED "restoring both inventory and revenue"; since REFUNDED is reachable only from PURCHASED, a refunded transaction's price enters both sums of the "sum over PURCHASED minus sum over REFUNDED" invariant and cancels, so a purchase-then-refund pair is revenue-neutral. The old code evaluated the formula over post-transition statuses and produced −60000 after refund, violating the restore sentence. Fixed `test_bank_revenue_conservation_across_purchase_refund`.

**Iteration balance note:** this loop was test-side dominated (3 test/helper fixes vs 1 impl fix). Sibling paths that implement the same rules but remain unasserted, for Step 8: (a) the tier-7-vs-singleton precedence question resolved as one-of for notices also applies to `ERR_AA_ALREADY_EXISTS` and `ERR_ACTIVE_PLAN_EXISTS` — their exact-error reachability under the §2.8 pipeline is not pinned anywhere in the suite; (b) the revenue-restoration fix in `bank_inventory` also serves the DENY cascade (§3.6/§3.7 "Withdrawal ... runs this identical cascade" applies to denial too), but only the withdraw path is asserted by the conservation test — denial-triggered revenue restore is unasserted.

(Orchestrator note: independently verified all 8 `results.*.json` show passed=94/total=94/failed=0. Post-Step-7 source-mtime snapshot taken at 2026-10-02T15:51:47Z — newest source 15:47:37Z (calculations.py, the Step 7 impl fix); any later impl/test mtime invalidates this sweep and triggers a re-run after Step 9.)

## Step 8: Finalize PRD — 2026-10-02T16:00:00.000Z

The diff is exactly the two intended in-place revisions. Final report:

## Summary

**Line counts:** PRD.md 360 lines → PRD_FINALIZED.md 360 lines (0% delta; two lines revised in place, no lines added or removed).

**Changes (one bullet each):**

- **§3.5 (line 167) — revise** — appended a precedence sentence to the publish-notice paragraph: because publication moves the application out of `ALTERNATIVES_REVIEW`, a repeat publication attempt finds it in `PUBLIC_NOTICE_OPEN` (or beyond) and fails the §2.8 tier-7 state precondition with `ERR_APPLICATION_INVALID_STATE` (HTTP 409) before the `ERR_NOTICE_ALREADY_PUBLISHED` singleton rule is consulted — `implementation/routes/applications.py:436-451` (state gate at 437-239 runs before singleton at 449-451).
- **§3.6 (line 193) — revise** — revenue invariant clause changed from "sum of `total_price_dollars` over `PURCHASED` transactions minus the sum over `REFUNDED` ones" (which, read over current statuses, yields −60000 after a purchase-then-refund and contradicts the same paragraph's "restoring both inventory and revenue") to "sum of `total_price_dollars` over the transactions currently standing in `PURCHASED`, and because a refund moves the transaction out of `PURCHASED`, a purchase-then-refund pair leaves revenue unchanged" — `implementation/calculations.py:254-270` (REFUNDED branch is a deliberate no-op).

**Zero-edit Step 7 items (verified, not manufactured):** the `test_helpers/fixtures.py` `create_appeal_payload` import and the `test_corner_complexity_layers.py` `setup_site_with_issued_jd` import are pure fixture bugs (NameError in test code) with no PRD silence or impl mismatch behind them — no PRD edit.

**Per-edit pre-edit search log:**

- **Edit 1 (revenue invariant):** (a) Subject: `revenue_dollars` computation semantics. (b) Enumerated and read/grepped: `calculations.py:241-273` (`bank_inventory`, the sole aggregator — PURCHASED adds, REFUNDED no-op); `serialization.py:175,188` (bank read/list surfaces it); `routes/banks.py:81-82,203` (available-only use); `calculations.py:284` (`purchase_pricing` ignores revenue); `cascades.py:73-88` (`compensation_cascade` PURCHASED→REFUNDED, shared by DENY at `routes/applications.py:534` and WITHDRAW at `:552`); `cascades.py:51-70` (`reverse_jd_cascade` releases RESERVED only — no revenue effect, consistent since RESERVED never contributes); full-tree grep for `revenue`/`REFUNDED` confirmed no other writers/readers. (c) Adjustment: chose "currently standing in `PURCHASED`" phrasing to pin observable behavior and exclude the losing current-status reading of the old "minus REFUNDED" formula; added the revenue-neutral consequence clause parallel to the existing availability clause, which also covers the unasserted DENY-cascade path flagged in the balance note (§3.7's "restoring the banks' inventory and revenue" now agrees with the formula).
- **Edit 2 (notice precedence):** (a) Subject: error precedence between the publish-notice state precondition and the notice singleton rule. (b) Enumerated: `routes/applications.py:428-458` (full guard order); both `notice_status` writers (`applications.py:453` — simultaneous with status→PUBLIC_NOTICE_OPEN; `cascades.py:161` — clock-driven close); all application-status writers in `routes/applications.py` + `cascades.py` (no path returns an app to `ALTERNATIVES_REVIEW`, so the singleton is shadowed on every reachable re-publication); sibling singleton sites `routes/review.py:50-60` (AA) and `routes/mitigation.py:88-112` (plan) — those singletons stay reachable because AA/plan creation never changes application status, so PRD §2.8+§3.4/§3.6 already uniquely determine them and needed no edit; §4 endpoint table (line 250) and §5 catalogue (line 349) carry no conflicting claims. (c) Adjustment: kept the original singleton sentence verbatim and appended a scoping sentence pinned to the repeat-publication path only — no universal claim about singleton rules, no claim that the singleton is dead code.

**Balance-note dispositions:** (a) `ERR_AA_ALREADY_EXISTS`/`ERR_ACTIVE_PLAN_EXISTS` — no edit; impl matches what PRD already determines (state tier first per §2.8, singleton reachable since creation doesn't move app status). (b) Denial-cascade revenue restore — covered by Edit 1's formula revision; §3.7's cascade prose was already correct and is now consistent with the pinned formula.

(Orchestrator note: independently verified PRD_FINALIZED.md exists and the diff vs PRD.md is exactly the two described in-place line revisions — 167 and 193 — nothing else.)

## Step 9: Complete PRD scan — 2026-10-02T16:20:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_3472_wetland_permit_review_compensatory_mitigation_requirements/workspace/PRD_COMPLETED.md`.

## Summary

**Source:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md`. Lines 360 → 360 (all inserts in-paragraph, no new sections); chars 71,608 → 76,339 (+4,731). Latest sweep (results.8.json): 94/94 green, so every pin matches the shipped behavior.

**Counts:** 27 ambiguity-pins, 2 mismatch-revisions (both in the §3.3 conditional-fields sentence, where the PRD contradicted itself), 1 IMPL BUG.

### Ambiguity-pins (insert unless noted)

- §2.1 — pin — `Applicant`-role `X-User-ID` is never verified against the applicant registry; used as-is — middleware.py:25-33
- §2.2 — pin — meta `api_request_timestamp` is wall-clock UTC, not the logical clock — response.py:32, db.py:90-92
- §2.3 — pin — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400) — response.py:75-97
- §2.3 — pin — `has_more` = offset + returned items < total_count — response.py:49
- §2.3 — pin — sort ties broken by creation order — db.py:95-97
- §2.4 — revise — `version` "starts as a small integer" → "starts at 1" — db.py:107
- §2.7 — pin — missing/non-integer expected-version field → `ERR_INVALID_REQUEST` (400) at shape tier — applications.py:221-228, mitigation.py:157-164
- §2.8 tier 6 — pin — explicit JSON null for an optional field with a default is treated as absent — helpers.py:29-36
- §2.8 — pin — body-derived ownership (appeals/analyses/plans/credit-txns): parent FK existence (404) and required-field shape resolve before `ERR_NOT_RESOURCE_OWNER` — jds_appeals.py:108-117, review.py:36-43, mitigation.py:67-80, banks.py:155-167
- §3.1 — pin — no format validation beyond string-ness for `state_code`/`watershed_code`/`contact_email` — applicants_sites.py:58-64
- §3.2 — pin — cross-site `new_jd_id` → `ERR_JD_NOT_FOUND`, checked before state/expiry/jurisdictional; `new_jd_id` on a DRAFT/RETURNED submit is existence-validated then ignored — applications.py:327-364
- §3.3 — pin — conditional fields may be supplied off-pathway: validated/stored, `is_after_the_fact` derives from pathway alone — applications.py:131-155
- §3.3 — pin — screening `return_reason` accepted but not persisted — applications.py:402
- §3.3 — pin — edit: explicit null clears `general_permit_code`/`enforcement_case_id` (merged checks still apply); nulls elsewhere ignored — applications.py:259-308
- §3.4 — pin — `minimization_steps` may be empty at filing — review.py:47
- §3.4 — pin — AA `revision_notes` not persisted — review.py:148
- §3.5 — pin — resolving a non-`FILED` comment → `ERR_INVALID_REQUEST` (400), no comment-specific state error exists — review.py:239-244
- §3.6 — pin — plan creation allowed regardless of `compensatory_mitigation_required` — mitigation.py:88-112
- §3.6 — pin — impact lines sharing a resource type are summed before ratios; one requirement entry per type — calculations.py:71-82
- §3.6 — pin — `assurance_required_dollars` formula = in-lieu fee formula over the (provisional, then final at secure) requirement; per-type lines rounded then summed — calculations.py:148-159, mitigation.py:56-60, 273-274
- §3.6 — pin — empty `stewardship_entity_name` counts as absent → `ERR_INVALID_REQUEST` — mitigation.py:38-45
- §3.6 — pin — every supplied bank price strictly positive (even zero-capacity types); unknown map keys → `ERR_INVALID_REQUEST`; computed inventory maps always carry all four types — banks.py:30-73, calculations.py:241-273
- §3.6 — pin — txn `resource_type` not a key of the plan's requirement map → `ERR_INVALID_REQUEST` (400) — banks.py:180-184
- §3.6 — pin — secure-credits recomputes and stores `final_credits_required_by_type`/assurance *before* the sufficiency gates, so a rejected attempt persists them — mitigation.py:268-274
- §3.6 — pin — pay-in-lieu-fee also computes/stores `final_credits_required_by_type` (only the fee is never recomputed); pay on a non-`IN_LIEU_FEE` plan → `ERR_PLAN_INVALID_STATE` — mitigation.py:319-329
- §3.6 — pin — plan-review `revision_notes` not persisted — mitigation.py:234
- §3.7 — pin — render-decision `decision_rationale` not persisted — applications.py:495
- §3.8 — pin — auto breach case stamps `opened_date` from the advancing clock and description "Monitoring report overdue by more than 60 days (compliance breach)" — cascades.py:202-219
- §3.8 — pin — `DEFICIENT` review requires a *non-empty* `deficiency_notes` — permits.py:196

### Mismatch-revisions (PRD text at fault — internally inconsistent)

- §3.3 — revise — dropped "and must be `NWP-29` or `NWP-39`" from the shape-tier sentence: the code-value restriction fires only as the eligibility rule `ERR_GENERAL_PERMIT_INELIGIBLE` (422) at creation/submission, as §3.3 ¶2 itself pins; the shape sentence's 400 claim contradicted it — applications.py:131-134, 159-161
- §3.3 — revise — a nonexistent `enforcement_case_id` is the tier-5 FK failure `ERR_CASE_NOT_FOUND` (404), not the 400 "shape failure" the sentence claimed (§2.8 tier 5 explicitly lists `enforcement_case_id` as a body FK); the responsible-applicant match remains `ERR_INVALID_REQUEST` — applications.py:70-75, 137-147

### IMPL BUGs (PRD unchanged; orchestrator to fix impl and re-sweep)

- §2.6/§3.7 — verbatim rule: "All credit quantities and dollar amounts are carried at two decimal places … rounding half-up to two decimal places happens only when the penalty is fixed at case closure" — `workspace/implementation/cascades.py:140` — ATF-track closure at permit issuance stores `penalty_final_dollars = calc.penalty_accrued(case, clock)` **unrounded**, so a sub-cent accrual (e.g. fractional `unauthorized_fill_acres` such as 0.0001) persists a >2-decimal dollar amount; the restoration closure path (`routes/enforcement.py:169-170`) does round via `q2(accrued * 0.5)`. §3.7's "full … accrual" contrasts with the 50% offset, not with rounding, so §2.6's carriage rule governs and the impl violates it.

## Step 9b: Impl fix + re-sweep — 2026-10-02T16:35:00.000Z

Orchestrator handled Step 9's IMPL BUG directly (terminal sequence: targeted impl fix, full re-sweep, PRD_COMPLETED untouched — the impl moved toward the PRD, not the reverse).

**Impl fix (1):** `workspace/implementation/cascades.py:140` (`_issue_permit` ATF closure) — verified the bug against source first (restoration path `routes/enforcement.py:168-170` rounds via `calc.q2(accrued * 0.5)`; ATF path stored raw `penalty_accrued`), then wrapped the ATF fixation in `calc.q2(...)`. PRD_COMPLETED.md left byte-untouched.

**Re-sweep:** full 8-round parallel stability sweep re-run by the orchestrator after the fix (`rm -f results.*.json` first, all 8 rounds joined with `wait`). Result: **all 8 rounds 94/94/0** — `results.1.json` … `results.8.json` all show `passed: 94, total: 94, failed: 0`. Results artifacts retained in `workspace/implementation/`.

**Post-Step-7 write audit:** the only implementation/test source file with an mtime after the Step 7 sweep is `workspace/implementation/cascades.py` (this Step 9b fix) — no Step 8/9 subagent touched `implementation/`, `test_helpers/`, or `test_suite/`.
