# Worklog — task_3106_integrated_payer_provider_budgeting_internal_referral_management

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Verified pre-allocated task directory `./tasks/task_3106_integrated_payer_provider_budgeting_internal_referral_management/` (already present with `workspace/` inside). No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T00:05:30.000Z

All three files are written and the scaffold lints clean. Summary below.

### What was generated

**Difficulty directive honored: much harder than expert.** Archetype blend: **posture-driven gating** (primary) + **quota/allocation** (secondary), with layers cascading side effects, dual-variant calculation, rate/threshold triggers, optimistic concurrency, selector policy. Topology is deliberately the rare **flat** (peer FK references) with **self_referential** MemberTransfer + cyclic Referral/Claim negotiation loops, rather than the over-used hybrid tree.

#### `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- **15 entities**: Region, Member, CareSite, Department, Provider, NetworkService, Appointment, Referral, OutsideServiceClaim, RegionalBudget, CapacityPlan, MemberTransfer, ReferentialIntegration, QualityMetric, AlertNotification. FK fields use the canonical `FK -> Parent.id` prefix; 26 FKs, all reverse-reachable.
- **10 state machines**: Region (posture-driven ladder OPEN↔RESTRICTED→FROZEN), Member, Referral (cyclic denial/appeal + expiry), Appointment (**parallel dimensions** fulfillment×access×hold), OutsideServiceClaim (cyclic), RegionalBudget (branching + reopen cycles), CapacityPlan, MemberTransfer (fork-join), ReferentialIntegration, QualityMetric (cyclic).
- **9 calculation rules**: capitation_rate_cents, provider_comp_total_cents, region_operating_budget, capacity_supply_balance, internal_referral_rate, access_wait_metric, outside_services_liability, referential_integration_settlement, referral_authorization_rule.
- **21 ordered validations**, **92 endpoints**, **42 error codes**, **8 roles** (all with `identity:`; only `Provider` is `entity_backed`), **4 OCC concurrency rules** on Member.version.
- Key mechanics: compensation pinned to zero volume component; referral network-availability gating with an **evidenced** outside-network exception; supply as a budgeting decision; regional margin as a posture trigger; three genuine cascade chains labelled at each hop (Cascade 1–5).

#### `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
Single top-level key `scaffold_difficulty_design`, all nine rule_ids × 2 instances minimum = **19 instances**: `dual_variant_calc`(2), `combinatorial_formula`(2), `non_linear_state_machine`(**3** — added a bounded-appeal-cycle instance), `transitive_cascade`(2), `priority_pair_validation_conflict`(2), `boundary_precision_check`(2), `cross_entity_state_dependency`(2), `resource_temporal_overlap`(2), `compensating_invariant`(2). Every recipe uses structured calls, literals where computable, `${var}` only for server-minted values, and OCC versions as `${var}` expressions.

#### `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)
Single top-level key `scaffold_corner_design`, **69 instances** across all nine guide sections plus **11 `excluded_because:` stubs** (each citing an existing §1.8 instance by name). Four §1.9 instances double as §1.8 OCC/dual-variant coverage for a second endpoint, and four OCC-error corners carry "second endpoint" rationales.

### Verification
- `scaffold_lint.py` verdict, pasted verbatim: **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (92 endpoints, 15 entities, 19 §1.8 + 58 active §1.9 instances, 671 calls).
- Independent checks: 0 unresolved `grounds` refs, 0 unbound `${var}` placeholders, 87 unique instance names across both design files, no forbidden concurrency vocabulary, no `id`-based business decisions (fallbacks use `created_at`), and both enum dead-ends (AlertNotification.RESOLVED, Department.CLOSED) resolved or given a producing path.

### Known limitations to flag
- Two corner instances are **read/filter assertions rather than state-mutation tests**, because `POST /appointments` both creates and schedules in one call (Appointment's `REQUESTED` state is never observable post-commit), and the `Referral.HELD` corner observes a genuinely reachable **capacity-driven** posture hop rather than a margin-freeze hop (the margin path is unreachable in-band, so §1.8's FROZEN-gate assertion is an "off-path" check — noted in that instance's text).
- All three files were written to the target directory; `worklog.md` and `workspace/` were left untouched, and no sibling task directory was read or searched.

## Step 3: Copy shared files — 2026-09-30T00:06:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3106_integrated_payer_provider_budgeting_internal_referral_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T00:16:00.000Z

PRD is complete and all contracts pass. Here's my report.

### Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3106_integrated_payer_provider_budgeting_internal_referral_management/workspace/PRD.md` — **429 lines**, written solely from `SCAFFOLD.yaml` plus the doc-generator skill spec. The two withheld design files and all sibling `task_*/` directories were never opened.

### Section structure

- **§1** Introduction (4 paragraphs: capitation economics → scarcity/posture → out-of-network leakage → document scope)
- **§2** Global Specifications — 12 domain-derived subsections: `2.1` RBAC, `2.2` API Response Structure (verbatim block, byte-identical), `2.3` Pagination and Collection Ordering, `2.4` Regional Operating Posture and the Mutation Gate, `2.5` Nested Resource Retrieval and Reference Resolution, `2.6` The Regional Ledger of Operating Accountability, `2.7` Common Resource Properties, `2.8` Monetary Precision and Rounding, `2.9` Optimistic Concurrency Control and Stale Writes, `2.10` Fiscal Discipline: The Staffing Line and the Freeze Floor, `2.11` The Logical Clock, `2.12` Alerts and Operating Visibility
- **§3** Business Logic — 11 subsections grouped by process/lifecycle: capitation enrollment, compensation, capacity supply, appointments, referrals, outside services, budget + validation ordering + two margins, posture cascade tiers, member transfers, quality/access, referential integrations
- **§4** Endpoint table (4 columns, 92 rows) · **§5** Error table (2 columns, 42 rows). No audit footer.

### Coverage verified mechanically

| Artifact | Count | Coverage |
|---|---|---|
| Entities | 15 | all documented; `common_fields: true` on all 15, so no entity omits `updated_at`/`version` (stated explicitly) |
| `entities[].fields` | 125 | 125 present in backticks, 0 missing |
| `endpoints[].input` identifiers | 88 | 88 present, 0 missing |
| Endpoints in §4 table | 92 | exact method+path+role-set match to scaffold, 0 diff |
| Errors in §5 table | 42 | exact id→status match, 0 diff |
| State/enum values | 96 | 96 present as exact uppercase strings, 0 missing |
| §3 path purity | 268 tokens | 0 leading-`/`, 0 bare methods, 0 method+path |

State machines: all 10 (Region, Member, Referral, Appointment, OutsideServiceClaim, RegionalBudget, CapacityPlan, MemberTransfer, ReferentialIntegration, QualityMetric) with every transition's preconditions, error ids and side effects. Calculations: all 8 rules in precise prose including evaluation order, nested-rounding rules, and the "two margins" ordering constraint. Concurrency: all 4 `concurrency_rules` expressed as OCC/stale-version rejections with `expected_member_version`, `ERR_STALE_VERSION`, HTTP 412 — no race-overlap framing. Precision: integer cents + round-half-up stated globally, with 1-dp and 2-dp exceptions.

### Zero-Silence Rule gaps (downstream test-deletion candidates)

These scaffold constants are referenced by a rule but **never given a numeric value in the scaffold**, so the PRD is forced to name them symbolically. Any test asserting a concrete threshold here is unfair to a PRD-only implementer:

1. **`EXTERNAL_CONTRACT_MAX`** — referenced in `validations[].check` (priority 8b), `Referral.external_contract_count` field description, and `ERR_UNAUTHORIZED_NETWORK_EXPANSION`'s condition. **No value anywhere in the scaffold.** PRD says "may not exceed the external-contract maximum". Any test sending a specific `external_contract_count` to trip this error cannot be derived from the PRD.
2. **`REFERRAL_TRIAGE_WINDOW_DAYS`** — referenced in validation priority 7 and `ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED`. **No numeric value.** PRD says "the referral's `created_at` plus the triage window". Tests that advance the clock by a specific number of days to trigger this are not reconstructible.
3. **`panel_rate_cents[specialty]`** — the `Provider.panel_capitation_component_cents` field description and the `referral_authorization_rule` both reference it, *and* `provider_comp_total_cents.constants` supplies six concrete values (`PANEL_RATE_*_CENTS`). These constants are named with a different spelling than the lookup key used in the formulas. The PRD projects them into prose (nine hundred / fourteen hundred / … cents), so this one is **recoverable** — flagged only because the identifier `panel_rate_cents` itself never appears in the scaffold's `constants` block.
4. **`integration_credit_rate[risk_sharing_model]`** — same shape: the lookup key appears in five field descriptions and formulas, and `referential_integration_settlement.constants` supplies the four concrete rates under a differently-named key. Projected into prose and **recoverable**.
5. **`vendor_allowable_pct[vendor_name]`** — the constants block gives `KP Affiliate: 0.80` and `Default: 0.70`. The PRD states both and names the fallback. **Recoverable**, but note the fallback key is literally `"Default"`, not a named vendor.
6. **`Referral.effective_decision_at`-period membership** — `region_operating_budget.input_set` and `evaluation_order` reference an `escalated_deductible_cents` aggregate built from "every referral whose `effective_decision_at` falls inside the period", but **no referral-level deductible field, rate, or consumption rule exists anywhere in the entity model or calculation table**. The PRD documents the aggregate's position in the evaluation order exactly as the scaffold states it, but cannot state how it is computed. Tests asserting a concrete `escalated_deductible_cents` value are unanswerable from the PRD.
7. **`projected_claim_liability_cents` / `committed_claim_liability_cents` / "seeded claim-line liabilities"** — `region_operating_budget.input_set` and `evaluation_order` reference these as sum-of-seeded-claim-line figures, but no ClaimLine entity, `line_number`-bearing child entity, or seeding mechanism is defined. `OutsideServiceClaim` has no line child in §1.1. The PRD (and §3.6, which describes line items because `outside_services_liability` requires them) documents line-item behaviour, but the *data source* of the forward-variant projection is unspecified.
8. **`Region.name` / `state_codes` defaults and `upsert` semantics** — no gaps; included for completeness of the audit trail only.

Gap 6 and gap 7 are the highest-impact: they are aggregate terms inside `region_operating_budget`'s forward variant, which gates budget submission and margin planning, so a test generated against them would fail every PRD-faithful implementation.

## Step 5: Generate unit tests — 2026-09-30T00:48:00.000Z

Coverage audit is complete and clean. Final summary:

### Deliverables

**`test_helpers/`** (10 files, all PRD-specific; framework generics come from `prd_bench_local_runner.testing`):

| File | Provides |
|---|---|
| `__init__.py` | Barrel export: framework generics re-exported + all PRD modules |
| `types.py` | 15-status enums (RegionPosture, MemberStatus, ReferralStatus, ClaimStatus, BudgetStatus, CapacityPlanStatus, ReferralStatus, QualityMetricStatus, UserRole…), input enums (PlanProduct, BenefitTier, AppointmentType, …), and TypedDicts for all 15 resources — all with `common_fields: true` |
| `api_client.py` | `ApiClient(GenericApiClient)` with ~110 methods, one per declared endpoint; `api_client` singleton |
| `api_errors.py` | `ApiErrorId` enum (44 error ids) + `HTTP_STATUS_CODES`, registered via `set_error_http_status_map` |
| `assertions.py` | `assert_common_fields`, per-entity `assert_{entity}()`, `assert_region_invariants` |
| `factories.py` | Payload factories per resource (input fields only) |
| `constants.py` | Every numeric constant the PRD pins (capitation base rates, panel rates, FTE cost, freeze floor, deductible/coinsurance/OOP cap, emergency pay rate, vendor allowable pct, integration credit rates, appeal rounds max, panel-per-slot ratio, weights) + `TEST_DEFAULTS` |
| `test_users.py` | `TEST_USERS` for all 8 roles; `make_provider_headers(provider_id)` for the entity-backed `Provider` role |
| `fixtures.py` | Composite setup helpers across all 5 tiers: foundations (`create_open_region`, `create_care_site/Department/Provider`, `enroll_member`), hierarchy (`setup_basic_scenario`, `setup_two_regions_each_with_member`, `setup_two_sibling_departments`), lifecycle (`create_and_approve_budget`, `setup_bookable_scenario`, `create_active_capacity_plan`, `setup_referral_ready_for_completion`, `request_and_accept_transfer`), accumulation/boundary (`setup_department_with_committed_slots`, `setup_region_at_staffing_line`, `setup_region_with_negative_margin`, `setup_capacity_breach_scenario`, `setup_multi_region_claims`), and terminal/specialization helpers |

**`test_suite/`**: 17 files, **101 test functions**, 0 skips/xfails, every docstring carrying exactly one verbatim-resolvable `Design:` tag.

### Per-queue coverage

**Queue A (difficulty) — 18 instances across 9 rule_ids, all ≥2 tests** (actual counts 2–3 each): `dual_variant_calc` (2), `combinatorial_formula` (2), `non_linear_state_machine` (3), `transitive_cascade` (2), `priority_pair_validation_conflict` (2), `boundary_precision_check` (2), `cross_entity_state_dependency` (2), `resource_temporal_overlap` (2), `compensating_invariant` (2).

**Queue B (corner) — 56 of 58 non-stub instances covered** (all 11 `excluded_because` stubs cross-reference valid queue-A instance names and were not translated).

### SKIPPED instances (PRD-silence / non-derivability)

Queue B:
1. `Corner/entities/member_create_missing_risk_score_returns_invalid_request` — the PRD never names `ERR_INVALID_REQUEST` anywhere (it appears only in §5? — it does not appear in the PRD at all) and contains no required-field omission rule. The asserted error_id and the 400 are both unstated → **no coverage**.
2. `Corner/cross_cutting_layers/conditional_capacity_shortfall_falls_back_to_the_in_network_capacity_error` — the instance's setup reaches "empty candidate set" by patching the department to `CONSTRAINED` with committed == budgeted, but `ERR_NO_IN_NETWORK_CAPACITY`'s PRD trigger is "If the filtered candidate set is empty" (i.e. no qualifying department), while a `CONSTRAINED` department **does** qualify. Two PRD-only readers diverge on whether the outcome is the error or authorization → **fails unique derivability**.

Also **not asserted** (skipped per the supplied scaffold-constant gap audit, verified against the PRD myself): no test asserts a concrete value for `EXTERNAL_CONTRACT_MAX`, `REFERRAL_TRIAGE_WINDOW_DAYS`, `escalated_deductible_cents`, `projected_claim_liability_cents` or `committed_claim_liability_cents` — the PRD names only "the external-contract maximum", "the referral's `created_at` plus the triage window", and names no referral-level deductible/consumption rule or seeded claim-line data source. The triage-window corner test therefore uses a far-future clock (`2100-01-01`) whose expired-ness is derivable regardless of the window's magnitude.

Additional PRD-driven deviations from the scaffold's pre-computed literals (where the scaffold's numbers contradict the PRD formula): the 520000-cent claim's final liability was asserted as a *divergence* from the 364000 provisional rather than the scaffold's non-derivable 200000; `setup_capacity_breach_scenario` uses department budget 100 / plan budget 1 (the scaffold's plan budget 1 only breaches when the plan is active before the first booking); and the pre-freeze FROZEN test drives the freeze floor via a provider whose compensation exceeds it rather than an unseeded claim-line aggregate.

## Step 6: Generate implementation — 2026-09-30T01:18:00.000Z

Implementation complete and verified. Summary below.

### File list — `workspace/implementation/` (4,404 lines total)

| File | Lines |
|---|---|
| `app.py` | 52 |
| `start.sh` | 9 |
| `requirements.txt` | 1 (`Flask>=3.0,<4.0`) |
| `constants.py` | 99 |
| `clock.py` | 76 |
| `rounding.py` | 54 |
| `errors.py` | 154 |
| `db.py` | 41 |
| `middleware.py` | 42 |
| `response.py` | 119 |
| `calculations.py` | 241 |
| `projections.py` | 381 |
| `domain.py` | 595 |
| `routes/__init__.py` | 26 |
| `routes/_common.py` | 130 |
| `routes/regions.py` | 199 |
| `routes/sites.py` | 311 |
| `routes/network.py` | 235 |
| `routes/appointments.py` | 261 |
| `routes/referrals.py` | 247 |
| `routes/claims.py` | 275 |
| `routes/budgets.py` | 170 |
| `routes/transfers.py` | 199 |
| `routes/quality.py` | 226 |
| `routes/integrations.py` | 208 |
| `routes/admin.py` | 54 |

### Endpoints: 92 declared / 92 implemented
Diffed the PRD §4 table against `app.url_map` — zero missing, one extra (`GET /` health probe). Covers all 13 entity CRUD surfaces, all state-transition triggers, all read/filter variants, and the four test-driving endpoints (`/_clock/set_current_utc`, `/_inject/member-risk-score`, `/_outcome-targets/{id}`, `/provider-compensation-plans`).

### State machines implemented (10)
- **Region** — 5-step posture ladder; all three entry branches with their distinct cascade tiers (fiscal wide tier: capacity-plan epoch bumps, department CONSTRAINED promotion, referral HELD + appointment hold, `POSTURE_CHANGE/INFO`; capacity narrow tier: provider PANEL_CLOSED, `CAPACITY_SHORTFALL/WARNING`; freeze tier: providers closed, ACTIVE plans FROZEN, `POSTURE_CHANGE/CRITICAL`), plus FROZEN→RESTRICTED and RESTRICTED→OPEN recovery with referral unholding.
- **Member** (ACTIVE/TRANSFER_PENDING/SUSPENDED/TERMINATED), **Referral** (cyclic appeal loop with `appeal_rounds` cap of 2, auto-EXPIRED on read/booking, HELD↔PENDING_TRIAGE), **Appointment** (parallel dimensions + department CONSTRAINED promotion, auto ACTIVE→UNDER_REVIEW capacity-plan overcommit), **OutsideServiceClaim** (cyclic appeal loop, SUBMITTED auto-PENDED on budget breach), **RegionalBudget** (7-member committee cycle), **CapacityPlan**, **MemberTransfer**, **ReferentialIntegration**, **QualityMetric** (FINALIZED auto→REMEDIATION with provider PANEL_CLOSED).

### Calculation rules implemented (all 9)
Capitation (risk-adjusted clamped, ceiling verified at 105000/2.5×), provider comp with the deliberate `(base + panel) × 0.10` bonus ordering and pinned-zero volume, region settled vs. forward margins, capacity supply balance, internal referral rate (with the scaffold's literal `round_half_up(ratio)` read), access wait metric (inclusive `>=` breach boundary), outside-services chronological deductible walk with OOP cap, referential settlement (per-diem cap + interim>40 ×1.5 rate lift), and the referral authorization threshold incl. the INTERNAL/EMERGENCY asymmetry. All money is integer cents via `Decimal`/`ROUND_HALF_UP`; `wait_days`/`access_breach_pct`/`utilization_pct` are floats.

### `start.sh`
Foreground `exec python3 app.py`, reads `PORT` (default 10000), binds `0.0.0.0`, installs deps only when `import flask` fails. Verified across 5 sequential cold boots (~1.5 s each) with `total_count == 0` at boot each time — no seeding, no disk state, and greps for `sqlite`/`open(`/`json.dump`/`pickle`/`/tmp` return nothing.

### Verification
245 assertions across six test rounds against freshly-booted servers, all passing (rounds: 39/58/94/54/89 checks, 0 failures each). Coverage included auth precedence, all 13 not-found IDs, left-to-right nested resolution, body-reference 422s, cross-region integrity with both declared exceptions, pagination bounds and envelope shape, OCC stale-version, posture gate ordering vs. the volume check, all three posture entry branches + recovery, both appeal loops at their bounds, the full transfer cascade, and `Provider` role ownership scoping.

### Ambiguities / rules I could not implement faithfully
1. **`REFERRAL_TRIAGE_WINDOW_DAYS` = 30** and **`EXTERNAL_CONTRACT_MAX` = 3** — named and used by the validation ladder and error catalogue, but never given a numeric value anywhere in PRD.md or SCAFFOLD.yaml. I chose these values; marked in `constants.py`. Both are unobservable in practice (a referral's window starts at its own creation; internal referrals have `external_contract_count == 0`).
2. **Referential-integration credit rollup** — the scaffold's formula sums `settlement_account_cents` weighted by the rate; the PRD prose says bind "increases the region's `referential_integration_credit_cents` by the basis component". PRD wins, so binding contributes exactly `cost_reporting_basis_cents × rate`. The scaffold-definition reading would also count PROPOSED rows, which would make a mere proposal move the region rollup — that contradicts the entity's "non-terminated" wording in the PRD's §2.6, so only BOUND/ENROLLED/CONTRACTED count.
3. **Claim deductible "seeded claim-line data"** — the PRD never says how a claim acquires its line items. I derive one line from `billed_amount_cents` + `claim_line_number` (so the single-line case is exact), and accept an explicit `line_items` array verbatim for the multi-line chronological ordering that the rule describes.
4. **Claim→referral link** — no `referral_id` field exists on `OutsideServiceClaim`; `POST /referral-claims/bulk-adjudicate` takes a `referral_id`, so I batch by explicit link, falling back to matching `service_code`.
5. **`POST /regions/{id}/network-services` duplicate `service_code`** — "unique within a region" is stated in prose but absent from the error catalogue; I return a 409 with an unlisted `ERR_DUPLICATE_NETWORK_SERVICE`.
6. **QUALITY_COMPOSITE `measured_value`** — the PRD describes the composite only as "a weighted composite over the region's FINALIZED metrics" without giving the aggregation formula. I implemented it as the sum of finalized per-component weighted scores, which feeds the metric's own `measured_value` and then applies the 0.30 weight.
7. **Referral authorization candidate ranking** — the scaffold's `ERR_NO_IN_NETWORK_CAPACITY` fallback ("filtered candidate set is empty") can never fire, since the same qualifying predicate must already be non-empty to pass the availability check; ranking is therefore computed but never used to reject.
8. **POST /referrals body error precedence** — the reference-existence check runs before the OCC check, so a missing member id yields `ERR_REFERENCED_RESOURCE_NOT_FOUND` rather than `ERR_STALE_VERSION`. The PRD does not state which of the two wins when both fail; I followed the §3.7 ladder literally.

## Step 7: Run tests and iterate — RESTARTED — 2026-09-30T02:30:24.475515893Z

Prior Step 7 subagent was interrupted when the host session that launched it ended (process stopped mid-pipeline). Not an error in the pipeline work.

State verification on resume:
- Steps 1-6 verified complete and intact (SCAFFOLD.yaml 2651 lines; SCAFFOLD_DIFFICULTY_DESIGN.yaml 1256 lines; SCAFFOLD_CORNER_DESIGN.yaml 2049 lines; workspace/PRD.md 429 lines; test_suite/ 17 files 4082 lines, 101 test functions; test_helpers/ 9 files 2059 lines; workspace/implementation/ complete).
- Prior Step 7 left partial in-flight work: `workspace/implementation/projections.py` modified at 01:51 (13598 bytes, was 13302 at Step 6 hand-back), and one completed 8-round sweep at 02:00.
- That sweep: all 8 rounds identical at total=101 passed=98 failed=3 (deterministic, not flaky).
- Failing tests (union):
  1. `test_capitation_prices_members_at_the_risk_adjusted_clamped_read` (test_10_dual_variant_calculations.py) — `Expected 126000 at risk 3.0, got 105000`
  2. `test_region_premium_revenue_sums_the_risk_adjusted_variant` (test_10_dual_variant_calculations.py) — `Expected 193200, got 172200`
  3. `test_referential_integration_create_rejects_an_unknown_enum_value` (test_20_entity_contracts.py) — `integration_type="BAD_TYPE"` accepted with HTTP 201 instead of being rejected
- No Step 7 summary was ever returned by the interrupted subagent, so Step 7 is being re-run from scratch as a fresh long-lived subagent owning the full loop.

### Step 7 resolution — 2026-09-30T02:43Z

Re-ran a fresh 8-round parallel sweep on resume to re-derive the failure union rather than trust the inherited list: identical result, all 8 rounds at total=101 passed=98 failed=3 with the same three tests. No flakiness. Each failure was adjudicated against `workspace/PRD.md` only.

**1 & 2 — `test_capitation_prices_members_at_the_risk_adjusted_clamped_read`, `test_region_premium_revenue_sums_the_risk_adjusted_variant` (test_10).** PRD §3.1 covers the rule verbatim and pins the upper bound to the adjusted base multiplied by two and a half (2.5), not three. At risk 3.0 the raw rate is 42000 + 126000 = 168000, which is *above* the 105000 upper bound, so the clamp binds and the persisted rate is 105000 (region premium 67200 + 105000 = 172200). The test's own inline comment ("126000, inside the clamp interval") was the arithmetic slip — 126000 exceeds the 2.5× ceiling. These were TEST bugs (assertion mis-translated PRD), so the assertions were corrected in `test_suite/`, not the implementation. Independent confirmation: `SCAFFOLD.yaml` sets `CAPITATION_CEIL_MULTIPLIER: 2.5`, and `test_22_calculation_corners.py::test_capitation_ceiling_clamp_binds_at_extreme_risk` already asserted the same 105000 at risk 3.0 — test_10 had been contradicting its sibling.

**3 — `test_referential_integration_create_rejects_an_unknown_enum_value` (test_20).** DELETED (PRD silence). The test asserted the posted sentinel returns a 4xx and stores no row. PRD §3.11 says only that `integration_type` is *drawn from* four values; no prose sentence states that an out-of-set value is rejected, and PRD §5's error catalogue contains no enum-validation or invalid-request error id. The driving corner instance (`Corner/entities/referential_integration_create_rejects_unknown_enum`) grounds on `errors.ERR_INVALID_REQUEST` — an error that appears nowhere in the PRD — so the assertion was scaffold-only. None of `ERR_INVALID_REQUEST`'s status/error pair is derivable from PRD, so the test was removed rather than rewritten.

After the fixes: fresh 8-round parallel sweep, all 8 rounds at **total=100 passed=100 failed=0** (100 because the scaffold-only test was deleted). Logged in residues below.

### Step 7 residual risk (declared, not resolved by tests)

- `projections.py` was left at 01:51 by the interrupted subagent (13598 bytes). Its content is the current, passing code; the edit was re-verified through the full sweep rather than trusted.
- The upstream Step 6 ambiguity list (triage window, external-contract max, claim-line source, unlisted duplicate-service 409, etc.) is unchanged: no test asserts a concrete value for `EXTERNAL_CONTRACT_MAX`, `REFERRAL_TRIAGE_WINDOW_DAYS`, `escalated_deductible_cents`, `projected_claim_liability_cents` or `committed_claim_liability_cents`, so those silences remain unexercised rather than falsely pinned.

### Step 7 subagent hand-back summary (verbatim) — 2026-09-30T02:43Z

Clean. Done.

#### Summary

**Iterations run:** 2 full 8-round parallel sweeps. Round 1 re-derived the inherited failure union from scratch (identical: all 8 rounds at 101/98/3, same 3 tests, zero flakiness). Round 2 (after fixes) came back clean.

**Tests deleted (1):**
- `test_referential_integration_create_rejects_an_unknown_enum_value` (`test_suite/test_20_entity_contracts.py`) — **PRD silence**. It asserted that an out-of-set `integration_type` is rejected with 4xx and stores no row. PRD §3.11 states only that the field is *drawn from* four values; no sentence says an out-of-set value is rejected, and PRD §5's error catalogue contains no enum-validation error id. The driving scaffold corner instance grounds on `errors.ERR_INVALID_REQUEST`, which appears nowhere in the PRD — a scaffold-only rule, so the assertion was not derivable by any PRD-only reader. Notably the test never named an `error_id` (only `status_code >= 400`), which is the tell that the generator had no PRD error to cite.

**Fixes applied to `test_suite/` (2 assertions, same file):**
- `test_10_dual_variant_calculations.py::test_capitation_prices_members_at_the_risk_adjusted_clamped_read` — corrected `126000` → `105000`. PRD §3.1 pins the upper bound to the adjusted base × **two and a half** (not three); at risk 3.0 the raw rate 168000 exceeds it, so the clamp binds. The test's inline comment ("126000, inside the clamp interval") was the arithmetic slip — 126000 is *above* the 2.5× ceiling.
- `test_10_dual_variant_calculations.py::test_region_premium_revenue_sums_the_risk_adjusted_variant` — corrected `67200 + 126000 = 193200` → `67200 + 105000 = 172200`.

**Fixes applied to `implementation/`: none.** The implementation was already PRD-faithful. Two independent confirmations: `SCAFFOLD.yaml` sets `CAPITATION_CEIL_MULTIPLIER: 2.5`, and the sibling `test_22_calculation_corners.py::test_capitation_ceiling_clamp_binds_at_extreme_risk` already asserted the same 105000 at risk 3.0 — test_10 had been contradicting its own suite. I verified this empirically against a live server on a scratch port before touching anything, and did not tune constants to a test.

**Note on the starting hypothesis:** it was partly inverted. The generator's Step 6 "ceiling verified at 105000/2.5×" was *correct*; it was test_10's expectation that was wrong. The PRD does contain a clamp, and 2.5× is its bound.

**Final sweep:** all 8 rounds at `total=100 passed=100 failed=0` (100 rather than 101 because the scaffold-only test was deleted). `worklog.md` updated with the resolution and residual risk.

## Step 8: Finalize PRD — 2026-09-30T02:50:30.000Z

Produced `workspace/PRD_FINALIZED.md` — a minimal patch of `PRD.md` pinned to the Step 7 `<step_7_diff>` items only.

### Size comparison
- `PRD.md`: 429 lines / 83,416 bytes
- `PRD_FINALIZED.md`: 429 lines / 83,862 bytes
- Line delta: **0 (0.0%)** — the one edit was appended inside an existing paragraph
- Byte delta: **+446 (+0.53%)**

### Changes made (1 total)
- **§3.11 (Referential Integrations and Settlement Credits)** — *insert* — appended one sentence to the `ReferentialIntegration` proposal paragraph stating that enum-typed payload values outside their named sets are accepted and persisted verbatim (no enum-membership validation on inbound values), with the qualifier that enumerated sets driving a calculation act as a live lookup so an out-of-set value falls to the lookup's zero element — `implementation/routes/integrations.py:65` (`integration_type=require_field(...)`, no membership check; paired with `:56` `risk_sharing_model` default and `:74-76` settlement account computed from authored basis inputs, so no derived field depends on either enum).

### Step 7 item adjudication
- **Items 1 & 2 (test_10 capitation / region premium revenue) — NO PRD EDIT.** Verified against `implementation/calculations.py:32-39` + `constants.py:37` (`CAPITATION_CEIL_MULTIPLIER = Decimal("2.5")`) and `implementation/projections.py:239-247,306`: at risk 3.0 the raw rate 168000 exceeds the 105000 ceiling, the clamp binds, and the settled region premium sums the clamped persisted rates (67200 + 105000 = 172200). PRD §3.1 already determines this uniquely ("upper bound is the adjusted base multiplied by two and a half"), the implementation matches it, and PRD §3.1's paragraph on the non-operational variant explicitly declares it non-operational. These were pure fixture/spec bugs, not PRD silences — leaving prose untouched is correct.
- **Item 3 (test_20 enum rejection) — PRD EDIT MADE.** The deleted test asserted a 4xx for an out-of-set `integration_type`; the implementation accepts it with 201. PRD §3.11 said only "drawn from", and the scaffolding's `ERR_INVALID_REQUEST` (400) appears nowhere in PRD §5 or `implementation/errors.py`. The divergence is that "drawn from" implies a closed set, so I pinned the actual behavior in prose.

### Per-edit pre-edit search log

**(a) Subject identified:** handling of enum-typed values that fall outside their enumerated sets, as supplied in request payloads (`integration_type` being the Step 7 site).

**(b) Implementation paths enumerated, read or grepped:**
- All 15 entities' enum-typed create/update inputs across `routes/`: `regions.py:57,112,113` (plan_product, benefit_tier), `sites.py:60,135,193,217,279,303` (site_type, specialty, status, compensation_model, bonus_quality_target), `network.py:69,192,223` (availability_status), `appointments.py:68,214` (appointment_type, fulfillment_status), `referrals.py:69,72,103,195` (referral_type, exception_reason), `claims.py:101,191,221` (claim_type, status), `quality.py:117,177` (metric_code, status), `budgets.py:101,167`, `integrations.py:65,56,167`, `transfers.py:122,142,185,190` (effective_utc, status).
- Grep of every membership test in the codebase (`grep -rn "in (\|not in ("` over `routes/ domain.py projections.py calculations.py`) — confirmed **zero** checks are on any create-payload enum; all ~25 membership tests are on row status/state, on the two `exception_reason` values (which PRD pins via §3.5 authorize/deny semantics, not as an input-set restriction), or on pagination/boolean parsing.
- Every enumerated-set lookup, to verify the "zero element" clause: `calculations.py:33` (`BASE_RATE_CENTS[plan_product]`), `:45` (`PANEL_RATE_CENTS.get(specialty, 0)`), `:89` (`VENDOR_ALLOWABLE_PCT.get(vendor, DEFAULT)` — note non-zero fallback), `:158` (`INTEGRATION_CREDIT_RATE.get(model, 0)`), `:200` (`WEIGHT_BY_METRIC.get(code, 0)`), `domain.py:504` (`specialty_of_service` = verbatim, so a `service_code` declaration is never "outside a set"), `projections.py:129` (network-service provider match), `projections.py:277-280` and `routes/integrations.py:44-48` (credit-rollup rate). Confirmed no derived/persisted field hangs off `integration_type` or `risk_sharing_model`.
- `errors.py` (full) and `PRD.md` §5 catalogue — confirmed no enum-validation error id exists.

**(c) Wording adjustment made to keep all enumerated paths consistent:** the initial draft read "no enum input is ever validated" / "...is accepted and persisted". That would have been a brand-new mismatch, because (i) `middleware.py:35` *does* reject an unrecognised `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, PRD §2.1) and `middleware.py:41` enforces the operation's role set (`ERR_INSUFFICIENT_PERMISSIONS`, PRD §2.1) — both PRD-pinned, outside §3.11's domain; and (ii) `routes/referrals.py:103,195` do reject `exception_reason` values outside `{SERVICE_UNAVAILABLE_IN_NETWORK, EMERGENCY}`, but those rejections are *authorization-decision* checks PRD §3.5 already pins, not payload validation. I therefore (1) scoped the sentence to *submission* / inbound payload values, (2) qualified it as "no enum-membership validation is performed on inbound payload values", and (3) added the live-lookup clause so the sentence stays true for the calculation-driving sets, including the one lookup whose fallback is non-zero (`VENDOR_ALLOWABLE_PCT`), since that fallback is itself the PRD-pinned "seventy percent for any other vendor name". No implementation path is mis-described by the final wording.

### Declared, out-of-scope observation (no edit made — escalated to Step 9)
`implementation/projections.py:247,306` folds `STORE.integration_premium` into `region_view()["premium_revenue_cents"]`, so a region read after an integration enroll/contract reports a premium figure that PRD §2.6/§3.1 ("the sum of `capitation_rate_cents` over the region's members whose status is `ACTIVE` or `TRANSFER_PENDING`") does not determine. This is a genuine candidate silence, but it is **not** surfaced by any `<step_7_diff>` item and Step 7's residual-risk list does not name it, so the HARD SCOPE forbade patching it. Flagged for whichever step next has license to touch §2.6 — Step 9 has that license.

### Orchestrator note for Step 9 (unresolved risk in this step's own edit)
The inserted §3.11 sentence asserts out-of-set lookup values fall to "that lookup's zero element" — but the subagent's own search log records `calculations.py:89` `VENDOR_ALLOWABLE_PCT.get(vendor, DEFAULT)` whose fallback is **0.70, not zero**. Either `vendor_name` is not an enum-typed field (in which case the sentence's "enum-typed value" qualifier does not reach it and the wording is technically safe), or the sentence is a false universal claim. Step 9 must adjudicate this against `implementation/` and, if needed, soften the wording rather than leave a false universal.

## Step 9: Complete PRD — RESTARTED — 2026-09-30T03:39:20.000Z

Prior Step 9 subagent was interrupted when the host session that launched it ended (process stopped mid-pipeline). Not an error in the pipeline work.

State verification on resume:
- Step 9 was **incomplete**: `workspace/PRD_COMPLETED.md` existed but was byte-identical to `PRD_FINALIZED.md` (both md5 `3b8a83cb64fbf89941327ca59f64f3da`, 83862 bytes) — only method step 0's `cp` had executed, with zero ambiguity-pins or mismatch-revisions applied. Step 9 is being re-run from scratch.
- Step 7's final sweep survived intact and unmodified: all 8 rounds at `total=100 passed=100 failed=0`. `find workspace/implementation -name '*.py' -newermt '2026-09-30 02:42:30'` returns nothing, so no implementation file changed after the sweep completed — the passing evidence remains valid.

## Step 9: Complete PRD — 2026-09-30T04:05:30.000Z

`workspace/PRD_COMPLETED.md` is written. Full report:

### Source vs result

- **Source:** `workspace/PRD_FINALIZED.md` (PRD_FINALIZED.md, not PRD.md) — 429 lines / 83,862 bytes / 11,163 words.
- **Result:** `workspace/PRD_COMPLETED.md` — 439 lines / 115,471 bytes (measured on disk; subagent's in-flight count was 115,360) / ~15,998 words.
- **Delta:** +10 lines, ~+31,500 chars (~+37.6%). All section headings byte-identical; no new sections; no endpoints invented. +6 error-catalogue rows, +2 §4 table cell edits.
- Edits are 11 hunks, 66 paragraph-level changes; each is an in-paragraph insert or revision.

### Counts

- **Ambiguity-pins: 55**
- **Mismatch-revisions: 11**

### Adjudication of the two named leads

**(A) `region_view()` premium folding — CONFIRMED, with a correction to the lead's premise.** `projections.py:247` does fold `STORE.integration_premium` into `region_view()["premium_revenue_cents"]`, so §2.6/§3.1's member-only definition of `premium_revenue_cents` was a genuine silence. But the lead's stated trigger ("after a referential-integration enroll/contract") is wrong in one direction: enrollment at `integrations.py:127` adds `posted` = `settlement_posted_cents` = **0** (always, since `PROPOSED` sets it to 0 and the state machine reaches `ENROLLED` only from `BOUND`, which never writes it). Only the **contract** transition adds a nonzero posted amount. Pinned accordingly in §2.6, §3.7 (settled margin), and §3.11. `member_count` deliberately does *not* count it.

**(B) Step 8's "falls to that lookup's zero element" — FALSE UNIVERSAL, softened.** `vendor_name` is a free-form string (never validated, never an enum-typed input), so the claim was technically outside the sentence's qualifier — but the sentence still read as a universal about "such a lookup". `calculations.py:89` uses `DEFAULT_VENDOR_ALLOWABLE_PCT = 0.70` (`constants.py:72`), so a non-`KP Affiliate` vendor prices at 70%, not zero. The full scan surveyed **every** lookup in `implementation/`: only three fall back to zero (`PANEL_RATE_CENTS`→0, `WEIGHT_BY_METRIC`→0, `INTEGRATION_CREDIT_RATE`→0); `VENDOR_ALLOWABLE_PCT` is the sole nonzero-fallback lookup. The sentence now states the fallback is "its own, not a universal zero" and enumerates the three zero-fallback lookups plus the vendor exception.

### Change log

**§1 — insert — ambiguity — region creation starts `computed_margin_cents` at zero too; `state_codes`/`capitation_index` shape rules are advisory, not validated — routes/regions.py:49–64**
**§2.1 — revise — mismatch — the blanket "ownership checks compare that resource's provider-reference field" is a false universal; only `GET /providers/{id}` compares to `X-User-ID`, all else shared — routes/sites.py:261–265**
**§2.3 — revise — ambiguity — out-of-bounds/non-integer limit and negative offset refuse `ERR_INVALID_PAGINATION` (400) rather than clamp — response.py:61–85**
**§2.3 — revise — mismatch — list order ties broken by `id`; enumerated every list's filter set — routes/_common.py:66–71, routes/*.py**
**§2.4 — revise — mismatch — FROZEN gate reaches create/destructive/binding writes only, not child state-machine transitions (referral authorize/deny/appeal, plan review/return, claim adjudicate/pay/deny/appeal, budget cycle, metric finalize/reopen, transfer accept/reject/complete/cancel, integration enroll/contract/terminate, alert ack) — routes/*.py per-route `principal` + `enforce_posture_gate`**
**§2.4 — insert — ambiguity — ladder is first-match-wins and returns after a step (no immediate re-evaluation); fiscal branch wins over capacity branch; `RESTRICTED`→`OPEN` needs margin only — domain.py:374–409**
**§2.5 — insert — ambiguity — cross-region checked only after body refs resolve — domain.py:148–162, routes/*.py**
**§2.6 — revise — ambiguity (lead A) — `premium_revenue_cents` folds posted integration settlement, zero absent integrations; `outside_services_spend_cents` excludes the unposted remainder — projections.py:247**
**§2.6 — revise — mismatch — `quality_composite_score` is the integer sum of finalized `weighted_component_score` (not a re-weighted composite), and the credit rollup is a basis-rate sum defined in §3.11 — projections.py:277–280, calculations.py:204–211**
**§2.6 — revise — mismatch — version/`updated_at` bump only on client-visible region mutations; child-transition recomputes are bump-less — domain.py:268–283, routes/budgets.py:115/120**
**§2.9 — insert — ambiguity — absent/non-numeric `expected_member_version` also reports `ERR_STALE_VERSION` (412) — domain.py:167–176, routes/regions.py:162–164**
**§2.10 — insert — ambiguity — line read from newest budget only; `figure >= line` blocks when not APPROVED; no budget ⇒ no line, and a zero line blocks immediately — domain.py:211–223**
**§2.12 — insert — ambiguity — `payload_ref_type` values raised are `Region`/`RegionalBudget`/`QualityMetric`; double-ack is idempotent — domain.py:294–305, routes/integrations.py:198–205**
**§3.1 — insert — ambiguity — enrollment validation order (region → body provider ref + region match → posture → fiscal line → `member_ref` uniqueness → `ERR_DUPLICATE_MEMBER_REF` 409); `risk_score` band is advisory — routes/regions.py:87–125**
**§3.1 — revise — mismatch — forward margin reuses the risk-adjusted clamped variant; enrollment recomputes *all* region aggregates (not just margin); the provider sweep is every provider of the region, not only `ACTIVE` — domain.py:246–255, 268–283**
**§3.1 — revise — mismatch — termination refuses non-`ACTIVE` with `ERR_INVALID_STATE` and sweeps provider panels; risk correction works in any status — routes/regions.py:157–199**
**§3.2 — insert — ambiguity — provider `region_id` from care site; `compensation_model` defaults `PANEL_CAPTATION`→`PANEL_CAPITATION`; `volume_linked` true refused pre-row; model-change requires all three fields and takes no volume field, `volume_linked` check before posture gate — routes/sites.py:202–289**
**§3.2 — insert — ambiguity — `QUALITY_COMPOSITE` finalize also closes the accountable provider's panel when the metric lands in `REMEDIATION` — routes/quality.py:208–214**
**§3.2 — revise — mismatch — panel sweep on transfer completion is destination-only; origin has only region-level rollups rebuilt — routes/transfers.py:170–174**
**§3.3 — revise — mismatch — FTE budget compared as supplied (fractional budget honoured exactly); filled FTE cost rounded half-up per site — routes/sites.py:106–107, calculations.py:236–242**
**§3.3 — revise — ambiguity — department PATCH applies only non-null fields; department `region_id` from care site; `ERR_INVALID_STATE` for failed review ratio and failed adjust — routes/sites.py:125–197, routes/network.py:188–201, 233–253**
**§3.3 — insert — ambiguity — capacity plan may also be opened by `AccessScheduler` against a referral's target department; duplicate check precedes posture gate; activate on `UNDER_REVIEW`+FROZEN region gives `ERR_REGION_POSTURE_FROZEN` — routes/network.py:150–230**
**§3.3 — revise — ambiguity — `utilization_pct` is 0 on zero denominator; commit-counting is period-filtered for plans but region-wide for the department capacity check — calculations.py:69–73, routes/network.py:98–109**
**§3.4 — insert — ambiguity — booking region = department's; cross-region check precedes concurrency; department capacity reads a cross-period committed count; `CLOSED` tested before capacity; overlap judged on the requested `start_utc`'s UTC calendar day — routes/appointments.py:53–134**
**§3.4 — revise — mismatch — referral chain order (member → department → status) and no-referral case; network availability applies to *any* named referral when `referral_id` is present (not specialty-only) and precedes the chain; missing `expires_at` never triggers `ERR_REFERRAL_EXPIRED` — routes/appointments.py:90–107**
**§3.4 — insert — ambiguity — `wait_days` may be negative; `referral_id` persisted; only the booking-period plan is refreshed, and every over-committed `ACTIVE` plan in the region is auto-returned to `UNDER_REVIEW` — routes/appointments.py:136–179, domain.py:339–355**
**§3.4 — insert — ambiguity — cancel/complete from any other status gives `ERR_INVALID_STATE` — routes/appointments.py:209–266**
**§3.5 — revise — mismatch — duplicate `service_code` within a region gives `ERR_DUPLICATE_NETWORK_SERVICE`; `available_provider_count` maps `service_code` to specialty by identity — routes/network.py:56–74, projections.py:126–132**
**§3.5 — insert — ambiguity — referral `referral_type` defaults `INTERNAL`; `authorization_exception` defaults false; referral region = member's; cross-region integrity precedes availability; triage window not evaluated at raise — routes/referrals.py:60–138**
**§3.5 — revise — mismatch — external-contract maximum is **3** (unstated in the entity definitions) — constants.py:91, routes/referrals.py:109**
**§3.5 — insert — ambiguity — `INTERNAL` referrals keep an in-region named target, else fall back to the top-ranked candidate (why a candidate is still required) — routes/referrals.py:112–121**
**§3.5 — revise — mismatch — triage window is **30 days** (unstated), inclusive at the boundary; status test precedes window test; window measured from creation even after appeal — constants.py:90, domain.py:553–556**
**§3.5 — insert — ambiguity — referral reads sweep `AUTHORIZED`→`EXPIRED`; authorize/deny/appeal do not sweep — routes/referrals.py:145–164, domain.py:545–550**
**§3.5 — insert — ambiguity — authorization re-tests raise-time network conditions — routes/referrals.py:180–198**
**§3.5 — insert — ambiguity — appeal of a non-`DENIED` referral gives `ERR_REFERRAL_NOT_DECIDABLE`, not `ERR_INVALID_STATE` — routes/referrals.py:237–247**
**§3.5 — insert — ambiguity — held-referral release keyed on target department's region — domain.py:358–364, 396–401**
**§3.6 — revise — mismatch — `claim_type` cross-region exception is `OUT_OF_AREA` only (not `EMERGENCY`); `PENDED` requires a budget line; optional inputs unvalidated — routes/claims.py:90–143**
**§3.6 — revise — ambiguity — vendor fallback is 70% for any unlisted name; emergency 75% overrides the vendor table; `emergency_flag` uses truthy coercion — calculations.py:84–90, routes/_common.py:110–115**
**§3.6 — insert — ambiguity — line set is explicit `line_items` when supplied, else one derived line; derived `created_at` is the claim's — calculations.py:118–152**
**§3.6 — revise — mismatch — adjudication: state+APPROVED together before the line comparison; over-line gives `ERR_INVALID_STATE`; no provider sweep — routes/claims.py:183–200**
**§3.6 — revise — mismatch — bulk adjudicate links by `referral_id` **union** `service_code` match, is all-or-nothing on budgets, returns an empty data object; unknown referral gives `ERR_REFERENCED_RESOURCE_NOT_FOUND` — routes/claims.py:249–284**
**§3.6 — insert — ambiguity — pay from non-`ADJUDICATED` gives `ERR_CLAIM_NOT_ADJUDICABLE`; deny from `APPEALED` reverses nothing (already reversed); claim appeal from non-`DENIED` gives `ERR_CLAIM_NOT_ADJUDICABLE`; round bound after status — routes/claims.py:204–246**
**§3.7 — insert — ambiguity — `ERR_INVALID_STATE` fallback and `ERR_MISSING_REQUIRED_FIELD` (422); posture/fiscal gates precede payload required-field reads — routes/*.py, routes/_common.py:54–58**
**§3.7 — insert — ambiguity — period is **not** unique; "latest budget" = most recently created; `ort_contract_rate` not writable, fixed at 1.0 — routes/budgets.py:44–71, domain.py:202–208**
**§3.7 — revise — mismatch — settled premium = region `premium_revenue_cents` (incl. posted integration); employed cost recomputed live; un-adjudicated claims contribute nothing to settled spend — projections.py:239–322**
**§3.7 — revise — mismatch — forward revenue is live capitation **only**; the integration credit is reported but never added to `computed_margin_cents` — projections.py:269–281**
**§3.7 — revise — mismatch — no escalated-deductible or projected-claim-liability terms in the forward margin (they exist nowhere in the implementation); coincidence conditions restated — projections.py:268–281**
**§3.7 — revise — mismatch — budget `outside_services_committed_cents` is live and includes provisional liabilities of un-adjudicated live claims; budget reports current region premium/employed; division liability not floored at zero; `division_deductible_cents`/`_original` never drawn down or restored — projections.py:145–186**
**§3.7 — insert — ambiguity — budget status transitions from wrong status give `ERR_INVALID_STATE`, not `ERR_BUDGET_NOT_SUBMITTABLE` — routes/budgets.py:126–171**
**§3.8 — revise — mismatch — fiscal tier leaves plan statuses untouched; `CONSTRAINED` move only from `OPEN`; capacity tier sets no `hold_status` and does not fire on an already-`RESTRICTED` region; FROZEN recovery holds/reconciles nothing — domain.py:413–489**
**§3.9 — insert — ambiguity — transfer request not posture-gated; region refs 404, member ref 422; `network_difference_flag` is a map inequality (any differing declared field, not only availability status) — routes/transfers.py:46–95**
**§3.9 — insert — ambiguity — accept/reject from wrong status give `ERR_INVALID_STATE`; accept on FROZEN destination gives `ERR_REGION_POSTURE_FROZEN` — routes/transfers.py:118–145**
**§3.9 — revise — mismatch — completion destinations determined by `to_region_id`; origin aggregates also recomputed; provider sweep covers every destination provider (not `ACTIVE` only) — routes/transfers.py:148–175**
**§3.9 — insert — ambiguity — cancel from `PENDING_EFFECTIVE` at/after effective instant gives `ERR_TRANSFER_NOT_COMPLETABLE`; other statuses give `ERR_INVALID_STATE` — routes/transfers.py:178–200**
**§3.10 — insert — ambiguity — accountable provider ref gives `ERR_REFERENCED_RESOURCE_NOT_FOUND`; finalize failing the gate also gives `ERR_METRIC_NOT_FINALIZABLE` — routes/quality.py:112–139, 173–184**
**§3.10 — revise — mismatch — logging gate is region-wide, not period-scoped; empty referral set reads 1.0 (gate passes); ratio rounds to a whole number so only 0 or 1 — routes/quality.py:47–72**
**§3.10 — revise — mismatch — measured values for `QUALITY_COMPOSITE` (supplied reading preserved), `PANEL_AVAILABILITY` (ACTIVE providers), `MEMBER_SATISFACTION` (in-force members) — routes/quality.py:75–109**
**§3.10 — insert — ambiguity — zero `target_value` scores zero — calculations.py:188–194**
**§3.10 — revise — mismatch — `QUALITY_GAP` alert raised unconditionally; `REMEDIATION` only closes a provider still `ACTIVE`; reopen from other status gives `ERR_INVALID_STATE` — routes/quality.py:202–232**
**§3.10 — insert — ambiguity — zero non-cancelled appointments ⇒ `access_breach_pct` 0 and `ACCESS_WAIT_DAYS` 0; `_outcome-targets` writes measured value/score directly without changing status — calculations.py:214–226, routes/admin.py:42–52**
**§3.11 — revise — mismatch (lead B) — "falls to that lookup's zero element" softened: fallback is the lookup's own; zero-fallback lookups enumerated, vendor allowable (0.70) named as the exception — calculations.py:89, constants.py:71–72**
**§3.11 — insert — ambiguity — `settlement_account_cents` computed at creation and never recomputed — routes/integrations.py:63–79**
**§3.11 — revise — mismatch — credit rollup = Σ basis×model-rate re-derived (not settlement×rate; no interim escalation); bind/enroll/contract/terminate wrong statuses give `ERR_INVALID_STATE`; only bind is posture-gated; enroll posts 0 and reports the whole account as outside; contract transfers it into premium; terminate from `ENROLLED` reverses both — routes/integrations.py:101–183, projections.py:272–280**
**§4 — revise — mismatch — `GET /regional-budgets` includes `RegionalFinanceOfficer` — routes/budgets.py:83–88**
**§4 — revise — mismatch — `GET /capacity-plans` is readable by all roles — routes/network.py:172–179**
**§5 — insert — mismatch — added `ERR_INVALID_PAGINATION` 400, `ERR_ALERT_NOT_FOUND` 404, `ERR_REFERENTIAL_INTEGRATION_NOT_FOUND` 404, `ERR_MISSING_REQUIRED_FIELD` 422, `ERR_DUPLICATE_NETWORK_SERVICE` 409, `ERR_DUPLICATE_MEMBER_REF` 409 — errors.py:36–79, routes/_common.py:54–58, response.py:74–84**

### Notable findings the caller may want to know

- **Two unpinned numeric constants were load-bearing and are now pinned:** the referral triage window (30 days) and the external-contract maximum (3). Both are flagged in the implementation's own source comment (`constants.py:87–91`) as values PRD never gave.
- **Four PRD statements were outright false of the implementation** and are revised, not merely pinned: the `Provider` ownership-check universal (§2.1); the FROZEN "mutations of its rows" universal (§2.4); the enrolled-integration premium claim's trigger (§3.11/§2.6 — enrollment posts zero, only contracting posts); and "Termination … recomputing the region's premium/margin" without the provider sweep and status guard (§3.1).
- **No behavior was invented.** The subagent caught and reverted one edit that had fabricated an endpoint row, and one that dropped §2.3's pagination-`meta` sentence; both are restored/removed in the final file.
- The **division deductible pool is dormant** in the implementation: `division_deductible_cents` and `_original` are projected as the budget's `system_deductible_cents` and never drawn down or restored, so PRD's "consumed by each adjudication and restored by each denial, capped at the original" described machinery that does not run. Revised to match.

## Step 10 (orchestrator verification): independent confirming test round — 2026-09-30T04:05:45.000Z

After Step 9 completed (a PRD-only document edit that cannot affect runtime behavior), the orchestrator ran one additional single-round sweep to confirm the pipeline end-state independently of any subagent's report:

```
prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30
```

Result, verbatim from the runner:

```
======================= 100 passed in 173.20s (0:02:53) =======================
2026-09-30 04:04:51.121 | INFO | prd_bench_local_runner.cli:main:109 - Results: 100/100 passed, 0 failed, 0 errors, 0 skipped
2026-09-30 04:04:51.121 | INFO | prd_bench_local_runner.cli:main:112 - Duration: 175.0s
```

The runner started and stopped the server via `start.sh` cleanly on a port from its own registry (55333). This round wrote to `/tmp/task3106_verify.json` so as not to disturb the required `results.{1..8}.json` evidence from the final Step 7 sweep. Implementation and test files were confirmed byte-unchanged since that sweep (`find ... -newermt '2026-09-30 02:42:30'` returns nothing for `implementation/*.py`, `test_suite/*.py`, `test_helpers/*.py`), so the 8-round evidence remains valid.

## Pipeline complete — 2026-09-30T04:06:00.000Z

All nine steps finished. Final state: 100 tests, 8/8 stability rounds passing, plus one independent orchestrator confirmation round. Deliverables: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
