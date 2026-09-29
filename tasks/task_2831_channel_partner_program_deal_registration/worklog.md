# Worklog — task_2831_channel_partner_program_deal_registration

## Step 1: Create task directory — 2026-09-05T03:40:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2831_channel_partner_program_deal_registration` and its `workspace/` subdirectory. Index 2831 was pre-assigned by the orchestrating prompt (no auto-allocation scan performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate scaffold (subagent) — 2026-09-05T05:07:00.000Z

All three artifacts are complete and the lint is clean.

**Verdict block (verbatim from `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2831_channel_partner_program_deal_registration`):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2831_channel_partner_program_deal_registration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2831_channel_partner_program_deal_registration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2831_channel_partner_program_deal_registration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  679

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Artifacts

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2817 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1853 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3087 |

## SCAFFOLD.yaml (§1.0–§1.7)
- Profile: `expert`, archetypes temporal_windowing + pricing_engine; layers `dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers`; topology `flat`; shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`.
- **12 entities**, **60 endpoints**, **13 calculations**, **~40 validation rules** (priorities 1->51), **40 error ids**, **4 roles**, **2 `concurrency_rules`** (`spr-create-stale-registration`, `mapping-create-stale-account`). Five named cascades A-E. No `scaffold_*_design` keys present; the "harder than expert level" directive does not appear anywhere in the artifacts.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 9 rules x 2 = 18 instances
1. **dual_variant_calc**: `provisional_vs_final_tier_divergence_on_performance_review`, `conflict_recommendation_variant_divergence_on_partner_vs_partner_case`
2. **combinatorial_formula**: `channel_margin_band_pinned_to_preliminary_net`, `mdf_claim_per_line_rounding_before_summation`
3. **non_linear_state_machine**: `deal_registration_revision_cycle_caps_at_two_rounds`, `mdf_claim_settlement_dimension_advances_independently_of_validation`
4. **transitive_cascade**: `cascade_a_registration_approval_to_partner_probation_depth_four`, `cascade_b_claim_clawback_to_marketing_probation_depth_four`
5. **priority_pair_validation_conflict**: `state_transition_outranks_exclusivity_conflict_on_submit`, `audit_remediation_overdue_outranks_mdf_insufficiency_on_claim_create`
6. **boundary_precision_check**: `exclusivity_window_end_instant_is_exclusive_on_submit`, `zero_verified_proofs_blocks_claim_validation`
7. **cross_entity_state_dependency**: `registration_submit_depends_on_account_direct_locked_state`, `mdf_claim_create_depends_on_allocation_closed_state`
8. **resource_temporal_overlap**: `exclusivity_half_open_single_occupant_with_renewal_exemption`, `mdf_period_capacity_over_inclusive_intersecting_periods`
9. **compensating_invariant**: `credit_memo_preserves_per_invoice_margin_conservation`, `claim_reject_restores_mdf_fund_bucket_conservation`

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 92 instances (55 full recipes, 37 `excluded_because` stubs)
All nine taxonomy sections present: `entities` (12), `state_machines` (13), `calculations` (18), `validations` (13), `endpoints` (11), `errors` (12), `rbac` (5), `cross_cutting_complexity_layers` (6), `consistency_model` (2). Every stub cites a difficulty instance that exists by name; no stub carries a `test_recipe`; all 55 full recipes have `setup`/`setup_api_calls`/`trigger`/`assert`; no name collides across the two design files.

Key literals were pre-computed in Python (Decimal/ROUND_HALF_UP) before being written as asserts, e.g. the MID-band one-cent straddle (list 5,681,818 -> margin 0.1350/invoice 4,914,773 vs 5,681,817 -> 0.1200/4,999,999, so the cheaper order invoices higher), the round-once weighted score 41.67 (not 41.80), GOLD final score 71.06, the 14-day mapping cooldown boundary 2026-06-14T23:59:59.999Z vs +1 ms, and the ceiling-pinned SPR case 0.10 + 0.06 + 0.02 = 0.1800. Both OCC rules are covered by full recipes (412 on stale version, success after re-read, version increments only on accepted writes).

**Orchestrator verification**: all three files present and non-empty; `grep -i "harder than expert"` over the task dir returns nothing, so the difficulty directive did not leak into the scaffold.

## Step 3: Copy shared files — 2026-09-05T05:08:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-05T05:24:00.000Z

PRD complete and verified.

## Deliverable
`workspace/PRD.md` — **460 lines**, built in 11 chunked `cat >>` appends plus two targeted `Edit` fixes found by the contract passes. Ends at a real section boundary: the final row of the §5 table, no mid-sentence cut, no audit footer.

## Section list
- `# Channel Partner Program API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors, Identity Headers and RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity, Audit Fields and the Logical Clock · 2.5 Money, Percentages and Rounding Discipline · 2.6 Window Geometry: Three Different Intervals · 2.7 Stale-Version Guards on Two Create Operations · 2.8 The Order of Rejection · 2.9 Cascade Discipline and Derived-Field Propagation · 2.10 Path Resolution, Sub-Resource Reads and List Filters
- `## 3. Business Logic & Workflows` — 3.1 Enrolling a Partner, Earning Credits and Unlocking the Portal · 3.2 The Coverage Map · 3.3 Staking a Claim · 3.4 Approval, the Exclusivity Window and the Protection Cascade · 3.5 Channel Conflict · 3.6 Pricing an Order · 3.7 Funding the Channel · 3.8 Settling Claims and Closing the Period · 3.9 The Annual Reckoning
- `## 4. Endpoint Definitions` (intro + 4-column table)
- `## 5. Error Code Catalogue` (2-column table)

## Hard Contract results
**HC1 Field-Name Coverage — PASS.** Three independent extraction passes over `entities[].fields[].name` plus every `input` / `query_params` / `path_params` identifier (128 required tokens, `?`-optional markers stripped) diffed against backticked tokens in PRD.md with fenced blocks excluded. Pass 1 found one gap, `claim_id` (ProofOfPerformance's parent FK, SCAFFOLD.yaml:578) — fixed in §3.7. Passes 2 and 3: **0 missing**. Separate sweep of every entity field enum literal: **0 missing**.

**HC2 Rule Coverage — PASS.** All 28 distinct validation priorities across the 39 validations are numbered in §2.8 with error id, HTTP status and enumerated `applies_to` scope; every one of the 39 validation `error_id`s appears backticked. Both `concurrency_rules` (`spr-create-stale-registration`, `mapping-create-stale-account`) documented in §2.7 with their `occ_field`, write endpoint, 412 error and rationale. All 10 state machines' states, terminal sets and transitions covered, including MdfClaim's two independent dimensions; all 13 calculations covered with every numeric constant present in prose (automated constant-presence check: 0 absent). Cascades A–E documented in §2.9 and §3, Cascade C in pinned order. A second gap surfaced here — the `/deal-registrations/{id}/review` action literals `START_REVIEW` and `REQUEST_CHANGES` were described but not named — fixed in §3.3.

**HC3 §3 Path Purity — PASS.** Token scan of every backticked span between `## 3.` and `## 4.`: 0 tokens beginning with `/`, 0 bare HTTP methods, 0 method+path combinations. Paths appear only in §2.7, §2.8 and §4 where naming the endpoint is required. Also scanned §3 for fuzzy words (`approximately`, `roughly`, …) and pseudocode operators (`>=`, `+=`, `min(`, ` IN `, …): 0 hits each.

## Coverage confirmation
- **60/60 endpoints** — table rows match the scaffold's `(method, path)` set exactly: 0 missing, 0 extra, 0 duplicates. Per-endpoint authorized roles diffed against `roles` in the scaffold: 0 mismatches.
- **12/12 entities** — Partner, CertificationRecord, Account, AccountMapping, DealRegistration, ConflictCase, SpecialPricingRequest, MdfAllocation, MdfClaim, ProofOfPerformance, OrderInvoice, PerformanceReview, all with `id` / `created_at` / `updated_at` / `version` stated in §2.4.
- **13/13 calculations** — certification_credit_rollup, partner_revenue_rollup, marketing_attainment, portal_entitlement, partner_tier_scoring, channel_margin_resolution, mdf_allocation_sizing, mdf_claim_approval, exclusivity_window, mapping_window_conflict, conflict_recommendation, channel_margin_conservation, mdf_fund_conservation.
- **39/39 error ids** in §5 with statuses matching the scaffold row-for-row (0 status mismatches, 0 extras).
- §2.2 verified byte-identical to `section-2.2-response-structure.md`. No Hard Contract or PASS text leaked into PRD.md.
- Forbidden files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced.

## Verbatim last 3 lines
```
| `ERR_SUPERSEDE_TARGET_INVALID` | 422 |
| `ERR_MDF_ALLOCATION_INSUFFICIENT` | 422 |
| `ERR_MDF_PERIOD_CAPACITY_EXCEEDED` | 422 |
```

**Orchestrator truncation check**: `tail -25` shows the §5 error-catalogue table complete through its last row; `grep -n "^#"` shows all sections §1–§5 with subsections present. PRD is not truncated.

## Step 5: Generate unit tests (subagent) — 2026-09-05T06:23:00.000Z

Generation is complete. Both output directories sit at the task root; nothing was written under `workspace/`.

## Files generated

`test_helpers/` (2679 lines)
`__init__.py` 48, `api_client.py` 267, `api_errors.py` 100, `assertions.py` 318, `constants.py` 93, `factories.py` 215, `fixtures.py` 1171, `test_users.py` 58, `types.py` 409

`test_suite/` (4653 lines, 101 tests)
`conftest.py` 46; queue B: `test_01_entities.py` 403, `test_02_state_machines.py` 477, `test_03_calculations.py` 474, `test_04_validations.py` 324, `test_05_endpoints.py` 194, `test_06_errors.py` 342, `test_07_rbac.py` 302, `test_08_cross_cutting_and_consistency.py` 212; queue A: `test_10_…` 238, `test_11_…` 213, `test_12_…` 211, `test_13_…` 235, `test_14_…` 140, `test_15_…` 197, `test_16_…` 187, `test_17_…` 252, `test_18_…` 206.

## Tests per queue and coverage

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, §1.8): **46 tests** over all **18** non-stub instances; every instance has >=2 tests (min 2, max 3).
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`, §1.9): **55 tests** over **54 of 55** non-stub instances (>=1 each). The 38 `excluded_because:` stubs were not translated.
- Every test docstring carries exactly one trailing `Design: …` line resolving to a real `- name:` in one of the two yamls (0 untagged, 0 dual-tagged, 0 unresolved), and every `PRD §x.y: "…"` citation was verified verbatim against a whitespace-normalised `workspace/PRD.md` (0 bad citations).

## Skipped design instances

1 skip, all sessions combined:

- `Corner/rbac/partner_listing_is_scoped_to_its_own_rows` — **non-unique-derivability**. The instance asserts a Partner's `GET /deal-registrations` returns `total_count == 1` (peer rows hidden). The PRD confines the ownership check to an explicitly enumerated set: §2.1 "This scope check guards eight write operations: …" (no read among them), §2.8 priority 4 defers to that same eight-operation list, §4 grants `GET /deal-registrations` to all four roles with the description "Lists deal registrations." and no scoping qualifier, and §2.3 defines `total_count` as "the number of rows matching the filters before paging is applied". A per-partner row filter is therefore not derivable from the contract (the text arguably implies the opposite), so the gap was left as a gap rather than weakened or xfailed.

## Verification

- `python3 -m py_compile` run over all 9 `test_helpers/*.py` and all 18 `test_suite/*.py` files: all clean (`PY_COMPILE_ALL_OK`); `__pycache__` artefacts removed afterwards.
- Every name imported from `test_helpers` in each test module was AST-checked against the live package: 0 missing.
- Placement confirmed by `ls -la`: `test_helpers/` and `test_suite/` exist only at the task root; `workspace/` contains just `INSTRUCTION.md`, `PRD.md`, `implementation/`. `worklog.md` was not touched, scratch stayed in `/tmp/task_2831_channel_partner_program_deal_registration/`, no `pkill` was ever issued.

One backward-compatible helper extension was made this session series: `seed_partner_vs_direct_conflict` in `test_helpers/fixtures.py` gained optional `pursuit_clock` / `pursuit_note` parameters so a conflict subject's `submitted_at` can be separated from the account's `direct_pursuit_declared_at`.

**Orchestrator verification**: 101 `def test_` functions across 17 test modules, 101 `Design:` tags (1:1). `test_helpers/` and `test_suite/` confirmed at task root only — no stray copies under `workspace/`.

## Step 6: Generate implementation (subagent) — 2026-09-05T06:00:00.000Z

Implementation complete and verified.

## Files generated — `workspace/implementation/`

19 Python modules + launcher, **3395 lines** of Python:

| lines | file | role |
|---|---|---|
| 510 | `calc.py` | all derived values (Decimal, ROUND_HALF_UP) |
| 385 | `routes_mdf.py` | MDF periods, claims, proofs, validate, settlement |
| 302 | `routes_registration.py` | deal registrations + lifecycle |
| 243 | `serialize.py` | one serializer per entity |
| 222 | `routes_account.py` | accounts, mappings, direct pursuit |
| 209 | `cascades.py` | cascades A–E + expiry sweeps |
| 187 | `validate.py` | shape/type/range validators |
| 168 | `routes_review.py` | program reviews |
| 149 | `store.py` | in-memory collections, logical clock, snapshot/restore |
| 131 | `routes_conflict.py` | conflict cases |
| 128 | `routes_partner.py` | clock, partners, certifications |
| 128 | `routes_order.py` | orders, invoicing, credit memos |
| 127 | `routes_spr.py` | special pricing requests |
| 112 | `response.py` | envelope, pagination, filtering |
| 102 | `constants.py` | enums and pinned numerics |
| 92 | `guards.py` | lookup + shared precondition guards |
| 85 | `app.py` | app factory, transaction hooks, error handlers |
| 56 | `errors.py` | 39 error IDs → HTTP status map |
| 48 | `auth.py` | identity headers, RBAC, partner scoping |
| 10 | `start.sh` | `PORT` from env, binds 0.0.0.0, `exec python3 app.py` foreground |

## Endpoint count: 60/60

Verified by enumerating `app.url_map`: exactly 60 rules, 60 rule×method pairs. Flask's implicit `/static` route is suppressed with `Flask(__name__, static_folder=None)`, and `strict_slashes = False` so trailing-slash variants resolve.

## Structure

**State machines** — implemented as per-endpoint guard sequences ordered strictly by PRD §2.8's 28-step order of rejection (existence 3 → scope 4 → shape 5 → OCC 7 → state 9 → period open 10 → claim validated 11 → suspended 13 → audit 14 → SOD 15 → margin ceiling 20 → credit size 21 → verified proof 22 → verify-once 23 → escalation cap 26 → fund availability 27 → annual capacity 28). `MdfClaim` carries two independent dimensions (`validation_state` × `settlement_state`); the settlement endpoint deliberately tests only the settlement dimension in step 9 so an un-validated claim yields `ERR_CLAIM_NOT_VALIDATED` rather than `ERR_SOD_SAME_ACTOR`.

**Calculations** — centralised in `calc.py` on `decimal.Decimal` with ROUND_HALF_UP: margins and `marketing_attainment_pct` at 4 dp, scores at 2 dp, per-line rounding before summation, residuals derived by subtraction (credit memos re-derive `margin_value_cents` then `margin_pct`). Both dual-variant calculations are computed in full and stored side by side: `partner_tier_scoring` (PROVISIONAL at review creation, FINAL at decision) and `conflict_recommendation` (`recommended_resolution_registration_first` / `..._coverage_first` plus the `applied_variant` and the chosen `recommended_resolution`). The three interval geometries are separate helpers — half-open exclusivity `[start, end)`, closed mapping window with an inclusive 14-day one-sided cooldown, and closed fiscal/review periods where touching endpoints intersect.

**Cascades A–E** — all in `cascades.py`, each a single pinned hop sequence (cascade C's four steps in order, with the residual sweep computed on the balance the first two steps produced). Atomicity comes from a global `deepcopy` snapshot taken in `before_request` for every non-GET and restored by the `ApiError`/404/405/`Exception` handlers, so a request that runs an expiry sweep and then fails a later precondition leaves zero trace — proven empirically (incumbent mapping stayed ACTIVE at an unchanged version on the failing path, and committed as EXPIRED/`WINDOW_ELAPSED` with version +1 on the succeeding one).

**OCC guards** — two, both 412 and both checked at step 7, before any state or business precondition: `expected_registration_version` on `POST /special-pricing-requests` → `ERR_STALE_REGISTRATION_VERSION`, and `expected_account_version` on `POST /account-mappings` → `ERR_STALE_ACCOUNT_VERSION`.

**Statelessness** — storage is pure Python dicts keyed by id; `store.reset()` runs at import, the clock defaults to exactly `2026-08-01T00:00:00Z` and never falls back to wall clock. A grep for `sqlite|open(|json.dump|pickle|shelve|/tmp` finds no persistence of any kind, and nothing is seeded.

## Verification

- **py_compile sweep clean** over all 19 `.py` files; `__pycache__` removed afterwards.
- **Smoke tests: 4 suites, 0 failures**, run on `PORT=18831` across two fresh `bash start.sh` boots (killed by exact captured PID only — no `pkill`). Coverage: full happy path, cascade A sibling holds + conflict creation, both OCC 412s, escalation ladder and its cap, all three resolutions incl. `DIRECT_LOCKED`, mapping cooldown/counter-cap/accept/terminate, credit-memo ceiling-before-size precedence, audit-finding freeze and overdue remediation, review REJECT → SUSPENDED and clean review → SILVER promotion, MDF sizing/annual capacity/proof rounds/per-line rounding/cascade B claw-back/WRITE_OFF/cascade C close, sweep rollback atomicity vs commit-on-success, pagination and `has_more`, 404/422 envelope shapes, clock non-fallback.
- **State wipe across reboots confirmed**: the second fresh boot reported `total_count = 0`.

`worklog.md` was not touched, and no file under `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was read, listed or globbed at any point.

**Orchestrator note**: Steps 5 and 6 were launched in back-to-back messages rather than one; the impl generator was nonetheless given an explicit absolute test-blindness constraint and confirmed in its summary that it never read, listed, or globbed `test_helpers/`, `test_suite/`, or either design yaml.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-05T06:37:00.000Z

Done. Clean 8-round parallel sweep: **101/101 passing in all 8 rounds**, zero flakiness.

## Summary

**Iterations run:** 2 (sweep → 1 fix → sweep).

**Iteration 1** (101 tests): exactly 1 failure, identical and deterministic in all 8 rounds — no flakiness, no load-induced timeouts, no connection-refused noise.

- `test_04_validations.py::TestConditionalAndTypeGates::test_a_credit_memo_is_refused_at_zero_and_at_the_whole_invoice_but_taken_between`
- `AssertionError: Expected error_id 'ERR_CREDIT_EXCEEDS_INVOICE', got 'ERR_MARGIN_CEILING_EXCEEDED'`

**Tests deleted:** none. Both PRD coverage (1a) and unique derivability (1b) held.

**Fixes applied to `test_helpers/`:** none. Factories emit integer cents and full ISO-8601 instants already; no fixture bug was involved.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful here — `routes_order.py::credit_order` evaluates the margin-ceiling check before the credit-size check, with an inline comment citing PRD §2.8, which is correct.

**Fix applied to `test_suite/`** (STEP 2, assertion mis-translated PRD wording):
- `test_suite/test_04_validations.py`, `test_a_credit_memo_is_refused_at_zero_and_at_the_whole_invoice_but_taken_between` — the test looped both refused boundaries (`0` and the whole invoice, `900000`) expecting the *same* `ERR_CREDIT_EXCEEDS_INVOICE`. PRD §2.8 places **20. Margin ceiling** (`ERR_MARGIN_CEILING_EXCEEDED`) strictly above **21. Credit size** (`ERR_CREDIT_EXCEEDS_INVOICE`), and states "the first failing check wins". A credit of the whole invoice drives the resolved margin to 1.0000, breaching the REGISTERED tier's 0.18 ceiling, so check 20 fires first; a credit of 0 leaves the margin at 0.1000, clears the ceiling, and correctly falls through to check 21. The loop was split into per-boundary expected error ids and the docstring now quotes §2.8's precedence.

Note this is a precedence/coverage correction, not a weakening: both branches still assert an **exact** `error_id` plus HTTP 422 — no `validate_error_is_one_of`, no status-only downgrade, no skip/xfail. It also unblocked the second half of the same test (the successful 1000-cent credit and its `margin_pct` 0.1010 / `trailing_revenue_cents` 899000 re-derivation assertions), which had never executed before and now passes.

Side note on reachability: given §2.8's ordering, `ERR_CREDIT_EXCEEDS_INVOICE` is only ever observable on the lower bound (`credit == 0`) — any credit at or above the current `invoice_amount_cents` necessarily breaches the tier ceiling first, and a negative credit is caught earlier still at shape check 5.

`worklog.md` was not read, created, or modified. No broad `pkill` was used. `__pycache__` directories left behind by the sweep were removed.

**Orchestrator verification**: all 8 `workspace/implementation/results.{1..8}.json` exist (timestamped 06:34) and each independently parses to `passed=101, failed=0, total=101, errors=0`.

**Step 8 decision**: Step 7 made 1 `test_suite/` fix (0 deletions, 0 `test_helpers/` fixes, 0 `implementation/` fixes), i.e. more than zero iterations beyond the baseline, so the skip condition does NOT apply — Step 8 runs.

## Step 8: Finalize PRD (subagent) — 2026-09-05T06:40:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 460 lines / 108,951 bytes
- `PRD_FINALIZED.md`: 460 lines / 109,821 bytes
- Line delta: 0 (0.0%); byte delta: +870 (+0.80%). One line changed (line 281).

## Change
- **§3.6 "Ship-and-debit credits"** — revise — pinned the evaluation order of the two credit-memo checks: the margin ceiling (§2.8 check 20) is evaluated before the credit-size check (§2.8 check 21), so a credit failing both returns `ERR_MARGIN_CEILING_EXCEEDED`. Also pinned that the "reduced invoice amount" is carried through unclamped when a large credit drives it to or below zero, and noted the resulting consequence that `ERR_CREDIT_EXCEEDS_INVOICE` is practically observable only at `credit_memo_cents == 0` (a negative value is refused earlier by shape check 5). — `implementation/routes_order.py:110-119`

Rationale: §2.8 was already unambiguous and correct (kept verbatim), but §3.6's local prose narrated size-then-ceiling, which is what the Step 7 test mis-translated. The edit removes that intra-PRD tension without contradicting §2.8.

## Pre-edit search log
- **(a) Subject:** precedence between the margin-ceiling check and the credit-size check on the credit-memo action; the definition/domain of the "reduced invoice amount" and "effective margin"; the reachability of `ERR_CREDIT_EXCEEDS_INVOICE`.
- **(b) Impl paths enumerated (read/grepped):**
  - `implementation/routes_order.py` — full file read. `credit_order` (lines 100-128): existence → `v.body()` → shape (`req_int credit_memo_cents minimum=0`, `req_string credit_reason non_empty=False`) → state precondition (`INVOICED`/`CREDITED`) → ceiling (20) → size (21) → mutations + `_recompute_partner_revenue`. Also `create_order` and `invoice_order` to confirm nothing else applies a ceiling or size gate.
  - `grep -rn "effective_margin_pct|MARGIN_CEILING|CREDIT_EXCEEDS" --include=*.py` over all of `implementation/` — only three ceiling sites: `calc.py:367` (pricing step four cap), `routes_spr.py:117` (SPR decision, base + 0.06 + granted), `routes_order.py:113` (credit memo). `ERR_CREDIT_EXCEEDS_INVOICE` has exactly one raise site.
  - `implementation/calc.py:376-378` `effective_margin_pct` — `q4((list - invoice)/list)`, no clamping, so negative `reduced` yields a value above 1; `calc.py:135-136` `recompute_revenue`; `calc.py:384-394` `mdf_basis_revenue` (second consumer of `invoice_amount_cents` after a credit — unaffected by the wording).
  - `implementation/routes_spr.py` (full) — confirmed the SPR ceiling branch sits after the validity-window check (19) and uses the base+0.06+grant formula already spelled out in §3.6, so the new sentence must not generalise about "the ceiling check" across operations.
  - `implementation/validate.py:78-120` — confirmed `req_int(minimum=0)` rejects negative credits as `ERR_INVALID_REQUEST`, and `constants.py:68` — all four tier ceilings <= 0.36, i.e. strictly below 1.0000.
- **(c) Wording adjustments made:** (1) scoped the precedence sentence to "the credit" / the credit-memo action rather than stating a general rule about margin-ceiling checks, so the SPR decision path (`routes_spr.py:110-119`, where the ceiling sits below the validity-window check) is not mis-described; (2) phrased the unreachability of the upper bound as a *consequence* ("Because every tier ceiling is well below 1.0000 … the practical way to observe") rather than a normative restriction, so it cannot be read as forbidding the check; (3) described the reduced amount as "simply carried through" rather than naming a clamp or floor, matching `effective_margin_pct`'s unclamped division; (4) left the paragraph's closing sentence on successive `CREDITED → CREDITED` credits verbatim — it says both checks apply "independently" per credit without asserting an order, which stays consistent with the new precedence sentence.

**Orchestrator verification**: `workspace/PRD_FINALIZED.md` exists (109,821 bytes vs PRD.md's 108,951), so it is not byte-identical to PRD.md.

## Step 9: Complete PRD (three sequential module-partitioned subagent passes) — 2026-09-05T07:15:00.000Z

**Orchestrator design decision (recorded per AUTONOMY instruction):** a single subagent reliably under-scans a 460-line PRD against ~3,400 lines of implementation, and the failure mode is a byte-identical output that hides the miss. Step 9 was therefore run as three SEQUENTIAL passes over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place. Partitions: P1 = app/auth/errors/response/store/validate/guards/serialize/constants; P2 = calc + routes_partner/account/registration/conflict; P3 = cascades + routes_spr/order/mdf/review. Pass 3 additionally did a closing whole-document consistency read.

### Pass 1 — cross-cutting/core modules

`cp PRD_FINALIZED.md PRD_COMPLETED.md` done first. PRD_FINALIZED.md 460 lines / 109,439 chars → PRD_COMPLETED.md 461 lines / 118,900 chars after pass 1 (+9,461 chars, 17 diff hunks, one new line for the `ERR_NOT_FOUND` catalogue row).

**ambiguity-pins: 17 · mismatch-revisions: 3**

- §2.1 (identity headers) — insert — ambiguity — a header present but carrying the empty string counts as absent for the 401 — `auth.py:16`
- §2.1 (partner scoping) — insert — ambiguity — the scope check fires only when the acting role is `Partner`, and `X-User-ID` is never resolved against the `partners` collection — `auth.py:44-48`
- §2.2 (success envelope) — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty characters from `A`–`Z` and `0`–`9` — `response.py:19`
- §2.2 (success envelope) — insert — ambiguity — `api_request_timestamp` is the one instant read from real wall-clock time, not the logical clock — `response.py:22-25`
- §2.3 (pagination) — insert — ambiguity — `offset` has no upper bound; "integer" means an optionally-signed digit run, so `""` and `10.0` are 422 — `response.py:58-88`
- §2.3 (ordering) — insert — ambiguity — `created_at` ties are broken by insertion order — `store.py:94-96`
- §2.4 (audit fields) — revise — **mismatch** — a cascade hop whose whole content is a derived-field recomputation bumps `version`/`updated_at` only when a figure actually changes; reads recompute without ever bumping — `calc.py:153-207`, `cascades.py:160-164`, `serialize.py:23-30,151`
- §2.4 (logical clock) — insert — ambiguity — the clock endpoint bypasses §2.1 entirely, so it does not inspect headers even when an unrecognised role is supplied; returns 200 with empty `data` — `routes_partner.py:16-22`
- §2.4 (logical clock) — insert — ambiguity — a fresh process starts with all twelve collections empty, nothing seeded — `store.py:33-41`
- §2.5 (rounding) — insert — ambiguity — fractions and scores travel as JSON numbers, so `0.1800` reads back `0.18` and `25.00` reads back `25.0` — `serialize.py:8-13`
- §2.6 (window geometry) — revise — **mismatch** — accepted instant grammar is 0–9 fractional digits with `Z`/`+00:00`/`+0000`; output is always three digits, **truncated not rounded** — `store.py:114-144`
- §2.7 (stale-version guards) — insert — ambiguity — both guard fields are non-negative ints, never persisted or echoed, and a shape failure on them is 422 not 412 — `routes_account.py:113`, `routes_spr.py:37`
- §2.8 item 3 — insert — ambiguity — a body FK is resolved for existence only when it is a non-blank string; otherwise it falls through to the shape check (422), not a 404 — `validate.py:163-175`
- §2.8 item 3 — insert — ambiguity — `ERR_PROOF_NOT_FOUND` also guards the standalone `GET /proofs/{id}` — `guards.py:21-26`, `routes_mdf.py:231`
- §2.8 item 5 — revise — **mismatch** — the "three fractional digits" requirement now defers to §2.6, plus five type conventions pinned (`null` = absent, blank = empty, integer/float/numeric-string coercion, strict booleans, body-must-be-a-JSON-object under a JSON content type with blank = `{}`) — `validate.py:16-29,32-42,66-75,149-154`
- §2.9 (cascade discipline) — insert — ambiguity — atomicity covers the whole request: a rejected mutating request discards even the sweeps that already ran — `app.py:27-48`, `store.py:102-108`
- §2.10 (list filters) — insert — ambiguity — exact case-sensitive equality, null values never match, an illegal filter value matches nothing rather than 422, and `verified` accepts `true`/`false`/`1`/`0` in any case while anything else is ignored — `response.py:103-112`, `validate.py:178-187`
- §3.2 (direct pursuit) — insert — ambiguity — `pursuit_note` is accepted (may be empty, no length limit) but never stored on the `Account` nor echoed — `routes_account.py:59`, `serialize.py:62-74`
- §4 (preamble) — insert — ambiguity — trailing slash tolerated; undeclared path or method → `ERR_NOT_FOUND` 404, never 405 — `app.py:24,51-60`
- §5 (catalogue) — insert — ambiguity — added the `ERR_NOT_FOUND` | 404 row — `errors.py:43`

Riskier claims were verified empirically against a live instance on port 18831 (stopped afterwards by PID, no broad `pkill`): wall-clock envelope timestamp, `ERR_NOT_FOUND` on unknown path and on method mismatch, trailing-slash tolerance, empty-header 401, clock endpoint accepting a bogus role, the instant grammar (`+0000` and 9-digit fractions accepted; date-only and `-05:00` rejected), millisecond truncation, `null`-as-absent, float-int coercion, filter tolerance, pagination edge values, the conditional version bump, and whole-request rollback (a rejected mapping proposal left the lapsed incumbent `ACTIVE`; the next successful one moved it to `EXPIRED`).

Clean cross-checks needing no edits: all **115** keys emitted by `serialize.py` already appear as backticked field names in the PRD (no emitted-but-undocumented field on any of the twelve entities); all **83** enum values plus every large numeric constant in `constants.py` documented; `errors.py`'s status map matches §5 exactly apart from the added `ERR_NOT_FOUND`. Two behaviors deliberately left unpinned as unreachable internals: `ApiError`'s fallback status 400 and `app.py`'s generic-`Exception` → `ERR_INVALID_REQUEST` 422 handler.

### Pass 2 — calc + partner/account/registration/conflict routes

PRD_COMPLETED.md 461 lines / 119,331 chars → 461 lines / 123,567 chars (all in-paragraph; no new lines, no new sections). Did NOT `cp` over the file.

**ambiguity-pins: 13 · mismatch-revisions: 1** (14 edits across 14 lines)

- §3.1 (partner amendment) — insert — ambiguity — an amendment supplying neither field, or values equal to the stored ones, is still accepted and still bumps `version` by exactly 1 (empty body is a no-op write, not a 422) — `routes_partner.py:65-79`
- §3.1 (marketing attainment) — insert — ambiguity — a standing recovery rewrites `tier_status` to `COMPLIANT` but leaves `standing_reason` at its last value; only an approving review clears it — `calc.py:176, 196-200`
- §3.2 (direct pursuit) — insert — ambiguity — only `OPEN_CHANNEL`/`CHANNEL_PROTECTED` admit the declaration (`NAMED_DIRECT` and `DIRECT_LOCKED` → `ERR_INVALID_STATE_TRANSITION`), and both admissible branches write `direct_pursuit_owner_id`/`direct_pursuit_declared_at` first and unconditionally — `routes_account.py:61-67`
- §3.2 (mapping `ACCEPT`) — insert — ambiguity — the overdue-audit freeze is evaluated against the agreement's own `partner_id` whichever authorised role acts — `routes_account.py:203-205`
- §3.2 (mapping `TERMINATE`) — revise — ambiguity — a `Partner` supplying `TERMINATE` gets `ERR_INVALID_STATE_TRANSITION`, not `ERR_UNAUTHORIZED`; same error from `COUNTERED` — `routes_account.py:216-218`
- §3.3 (resubmission) — insert — ambiguity — `closure_reason` holding the `reviewer_note` is not cleared by resubmission nor by a later approval — `routes_registration.py:197-201, 250-257`
- §3.5 (registration-first doctrine) — insert — ambiguity — a full tie on claim instant *and* tiebreaker resolves in claimant-assembly order: `GRANT_SUBJECT`, `GRANT_COUNTER`, `RELEASE_TO_DIRECT` — `calc.py:278-287`
- §3.5 (escalation) — revise — ambiguity — `escalation_note` must be a present string but may be empty/blank; a terminal case is refused with `ERR_INVALID_STATE_TRANSITION` (priority 9) even at `escalation_level` 2 — `routes_conflict.py:43-49`
- §3.5 (resolution / probation clear) — insert — ambiguity — `standing_reason` survives the return to `COMPLIANT`, and the hop bumps `version` only when a recomputed figure moves (local application of pass 1's §2.4 qualification) — `calc.py:168-181`
- §3.5 (`PARTNER` on `PARTNER_VS_DIRECT`) — insert — ambiguity — `coverage_state` and `direct_pursuit_declared_at` are left as they stood — `routes_conflict.py:90-95`
- §3.5 (`DIRECT`) — revise — **mismatch** — the account reaches `DIRECT_LOCKED` from whatever coverage state it was in (not only `NAMED_DIRECT`/`CHANNEL_PROTECTED`), and `direct_pursuit_owner_id` is deliberately retained — `routes_conflict.py:103-108`
- §3.5 (`SPLIT`) — insert — ambiguity — `protected_partner_id`/`protected_product_line` untouched, account `version` bumps whether or not `protected_until` moved, subject `closure_reason` not cleared — `routes_conflict.py:114-127`
- §3.6 (step one, special pricing uplift) — revise — ambiguity — a `created_at` tie among candidate SPRs is broken by insertion order, latest created wins — `calc.py:339`
- §3.9 (scoring formula) — revise — ambiguity — the marketing component is the stored, already-4dp `marketing_attainment_pct`; only the certification and revenue components are exact unrounded fractions — `calc.py:479-490, 508`

Deliberately left alone (verified already pinned or unobservable): the submit sweep's placement relative to the standing/audit/certification checks (§2.9 rollback makes it unobservable); `FAR_FUTURE` fallbacks in the registration-first doctrine (unreachable — a subject always carries `submitted_at`). Pass 2 flagged forward to pass 3 that cascade D's "no protecting `APPROVED` registration" branch IS reachable (a `CONVERTED` protector leaves the account `CHANNEL_PROTECTED`).

### Pass 3 — cascades + spr/order/mdf/review routes, plus closing consistency read

| file | lines | chars | bytes |
|---|---|---|---|
| `PRD_COMPLETED.md` before pass 3 | 461 | 123,065 | 123,567 |
| `PRD_COMPLETED.md` after pass 3 | 461 | 131,588 | 132,090 |
| pass 3 delta | +0 | +8,523 | +8,523 |
| `PRD_FINALIZED.md` baseline | 460 | 109,439 | 109,821 |
| **cumulative FINALIZED → COMPLETED** | **+1** | **+22,149** | **+22,269** |

**ambiguity-pins: 21 · mismatch-revisions: 2** (22 `Edit` calls touching 18 distinct PRD lines). Did NOT `cp` over the file.

- §2.8 item 10 — revise — **mismatch** — "validating a claim" narrowed to "a `VALIDATE` or `REQUEST_PROOF` claim decision"; a `REJECT` decision is never gated on the period being open, so a closed-period reject is answered by the state precondition at rung 9 — `routes_mdf.py:308-328`
- §3.2 — revise — ambiguity — "the unique registration in `APPROVED`" → the earliest such registration by `created_at`, insertion order breaking a tie — `cascades.py:69-79`
- §3.2 — insert — ambiguity — cascade D's hop 3 partner bump is conditional; the cascade may find no protecting registration at all (a `CONVERTED` protector still leaves the account `CHANNEL_PROTECTED`), in which case all three hops are skipped while the declaration still succeeds and records the pursuit fields; the account's version advances by exactly 1 either way — `cascades.py:80-81`, `routes_account.py:63-70`
- §3.4 — insert — ambiguity — hop two takes every other registration whatever partner it belongs to, the approving partner's own competing registrations included despite the closure reason's name, in ascending `created_at` order with insertion order breaking ties — `cascades.py:41-50`
- §3.4 — insert — ambiguity — hop four bumps conditionally; hops two/three/four run registration-by-registration rather than in three phases, so a partner holding two held registrations is visited twice and its version advances once per visit; with no registration in those states hops two through four write nothing — `cascades.py:52-61`, `calc.py:153-165`
- §3.6 — insert — ambiguity — an order's linked registration need only exist; it is never cross-checked against the buying `partner_id` — `routes_order.py:29-33`
- §3.6 — insert — ambiguity — a superseded SPR keeps `decided_by_user_id` null and its `expires_at` unchanged — `routes_spr.py:54-61`
- §3.6 — insert — ambiguity — no SPR decision branch re-examines the target registration (only `expires_at` gates a grant, and the ceiling test always adds the full in-window uplift), and no branch writes the registration — `routes_spr.py:107-126`
- §3.6 — insert — ambiguity — invoicing advances the partner's own `version` by 1 as `trailing_revenue_cents` moves, and touches nothing else on the partner — `routes_order.py:14-20,92-95`
- §3.6 — insert — ambiguity — `credit_reason` is required but may be empty or blank, with no length limit — `routes_order.py:104`
- §3.6 — insert — ambiguity — a credit memo never re-derives `volume_band`, and the partner's `version` advances by 1 with `trailing_revenue_cents` — `routes_order.py:120-127`
- §3.7 — revise — **mismatch** — "the period's `version` advances by 1 each time its buckets move" → by 1 on any single request that moves its buckets, once per request rather than once per transfer (so cascade C's successive transfers advance it by exactly 1), and a request moving no cents leaves it untouched — `cascades.py:115-144`
- §3.7 — insert — ambiguity — `audience_reach` is stored as null when omitted — `routes_mdf.py:192`, `validate.py:89-92`
- §3.7 — insert — ambiguity — verification never inspects the claim's `validation_state` (a `SUBMITTED`, `PROOF_REQUESTED` or terminally `REJECTED` parent is verifiable alike) and never advances the claim's version — `routes_mdf.py:234-255`
- §3.7 — insert — ambiguity — verification's recomputation stops at the two marketing figures and never moves `tier_status`, `standing_reason` or `portal_entitlement_level`; the partner bump is conditional and the partner is not visited at all unless the claim is already `VALIDATED` — `routes_mdf.py:19-27,251-254`
- §3.7 — insert — ambiguity — writing `matched_line_cents` is not a mutation of the document: its `version`/`updated_at` stay as verification left them — `calc.py:419-431`
- §3.7 — insert — ambiguity — a remainder of exactly 0 moves no cents and leaves the period's `version`/`updated_at` untouched — `routes_mdf.py:302-306`
- §3.7 — insert — ambiguity — cascade B hop one does not clear `matched_total_cents` (nor the documents' `matched_line_cents`), and `settlement_state` stays `UNPAID` — `cascades.py:97-109`
- §3.8 — insert — ambiguity — the period-close cascade stamps `PERIOD_CLOSED` rather than `WRITTEN_OFF` into `rejection_reason` and records no `settled_by_user_id` — `cascades.py:132-133`
- §3.8 — insert — ambiguity — step one leaves `settlement_state` `UNPAID` and `validated_by_user_id` as it stood; step two leaves `validation_state` `VALIDATED` with `approved_cents`/`matched_total_cents` intact and `settled_by_user_id` null — `cascades.py:119-136`
- §3.8 — insert — ambiguity — the period's `version` advances by 1 in total across all four steps, and no hop of the cascade reaches the partner — `cascades.py:115-144`
- §3.9 — insert — ambiguity — cascade E's closing hop bumps the partner conditionally, visits only that partner's own records and recomputes nothing else; the review decision does not re-run the sweep, so a record lapsing between preparation and decision is still `ACTIVE` for the final variant — `cascades.py:150-164`, `routes_review.py:146-147`
- §3.9 — revise — ambiguity — the `marketing_attainment_pct` snapshot is taken as the scoring's own recomputation has just left it, not as it stood before the request — `routes_review.py:51,69`
- §3.9 — insert — ambiguity — the `FINDINGS_OPEN` row is minted directly rather than written then rewritten, so it is created with `version` 1 and `updated_at == created_at`; and across the whole preparation the partner's `version` advances by at most 1 — `routes_review.py:25-31,75-79`
- §3.9 — insert — ambiguity — a review decision advances the partner's `version` by at most 1 in total whichever branch ran, and not at all when nothing moved — `routes_review.py:167`

**Closing whole-document consistency read — clean, nothing needed fixing.** Heading structure byte-identical to `PRD_FINALIZED.md` (27 headings, verified by `diff`); document still ends at `## 5. Error Code Catalogue` and its table, final row `| ERR_MDF_PERIOD_CAPACITY_EXCEEDED | 422 |`. §4 table: every row exactly 5 pipes. §5 table: every row exactly 3 pipes, 40 rows, no duplicates. §5 catalogue cross-checked with `comm` against every `ERR_*` literal in `implementation/*.py`: zero missing, zero extra. No broken sentence or duplicated clause left by pass 1 or pass 2, and no factual error found in their edits. Two self-corrections during the pass: one cascade-A edit initially created a new paragraph and was merged back inline; one cascade-A clause initially over-claimed absolute `open_conflict_count` values and was rewritten start-agnostically.

### Step 9 totals

**51 ambiguity-pins + 6 mismatch-revisions = 57 edits.** `PRD_FINALIZED.md` (460 lines / 109,821 bytes) → `PRD_COMPLETED.md` (461 lines / 132,090 bytes), +22,269 bytes (+20.3%).

**Orchestrator verification**: `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 95 changed lines in `diff`), heading sets are identical between the two, the file ends at the complete §5 table, and no file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the green sweep at 06:34 — so the recorded 8×101/101 result still describes the artifacts on disk. Stray `__pycache__` removed.

## Pipeline complete — 2026-09-05T07:16:00.000Z

All nine steps done. Final state: 12 entities, 60 endpoints, 101 tests, 8/8 sweep rounds at 101/101, `PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md` all present.
