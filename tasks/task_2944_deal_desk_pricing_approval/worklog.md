# Worklog — task_2944_deal_desk_pricing_approval

## Step 1: Create task directory — 2026-09-05T19:48:24.390Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2944_deal_desk_pricing_approval` and `workspace/` (pre-assigned path, index fixed by scenario number 2944; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-05T21:09:46.173919422Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2944_deal_desk_pricing_approval/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2944_deal_desk_pricing_approval/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2944_deal_desk_pricing_approval/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     34
  Calls scanned (§1.8+§1.9):  1178

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2944_deal_desk_pricing_approval/`)

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 2191 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key present |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1891 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2628 | `scaffold_corner_design` only |

`worklog.md` and `workspace/` were not touched; no sibling task was read.

## What the scaffold covers

- **15 entities**: DeskPolicy, ApprovalTier, Product, VolumeTier, BundleRule (last four immutable config), Account, Quote, QuoteLine, NonStandardTerm, CompetitiveException, RevRecAssessment, ApprovalRequest, ApprovalStep, DelegationGrant, OrderForm. Topology flat, consistency immediate, difficulty_level `expert_plus`.
- **8 calculations**: C1 line pricing (dual variant WHOLE_QUANTITY_AVERAGE vs MARGINAL_PROGRESSIVE over volume bands + bundle + term multiplier), C2 order totals (rebate on net subtotal, then 30-day-block payment uplift), C3 blended discount → approval-matrix level, C4 margin + exception allowance give-up (dual variant), C5 service levels/expiry (quarter-end surge window, halved SLA, expiry capping), C6 non-standard-term risk (AGGREGATE_WEIGHTED vs DOMINANT_CATEGORY), C7 rev-rec waterfall allocation with residual, C8 booking ARR/TCV ledger.
- **16 ordered validation priorities** (auth → role → path FK → shape → body FK → config integrity → ownership → state → OCC 412 → segregation of duties → business constraints → temporal overlap → submit gates → fiscal floors → booking acceptance criteria), **45 errors**, **8 roles** (SalesRep, DealDeskAnalyst, SalesDirector, VPSales, CFO, LegalCounsel, RevenueAccountant, PlatformAdmin) under a `delegated_authority` role model.
- **55 endpoints** covering policy/tier/product/volume-tier/bundle config, accounts + credit decisions, quotes/lines/pricing-preview, non-standard terms + legal review/co-sign, competitive exceptions (file/decide/revoke), rev-rec assessments, submit/reopen/renegotiate, delegation grants, order forms (generate/send/signature/book/reverse-booking), plus `/expiry-sweeps`, `/sla-escalation-sweeps` and the logical clock.
- **2 OCC rules**: `occ-renegotiate-stale-quote` and `occ-order-form-supersede`, both on `expected_quote_version` → `ERR_STALE_QUOTE_VERSION` 412.

## Design-file counts

- **Difficulty design**: all 9 rule_ids × 2 instances = **18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **Corner design**: **53 instances** across all nine claim-extraction-guide sections — entities 10, state_machines 8, calculations 6, validations 5, endpoints 3, errors 10, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1 — of which **34 are live test recipes** and 19 are `excluded_because` stubs citing the covering §1.8 instance by name.
- **71 globally unique instance names**, no duplicates across the two files. Every money/percent/instant literal is code-verified against a Decimal reference implementation of C1–C8.

Orchestrator note: verified no "harder than expert" difficulty-directive leak in any scaffold file (grep clean).

## Step 3: Copy shared files — 2026-09-05T21:09:51.54703547Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T21:24:30.534866901Z

Subagent summary (verbatim):

Verification is complete — the fuzzy-language scan is clean (the only hits for "about"/"around" are ordinary prose: "cares about", "works around", "nothing else about that grant"), and no hedging quantifiers appear anywhere in the document.

## Deliverable

`workspace/PRD.md` — **445 lines**, ending at a real section boundary (final row of the §5 error table, `| ERR_BOOKING_CRITERIA_UNMET | 422 |`), no audit footer or contract report leaked into the file.

## Section list

- **§1. Introduction** · **§2. Global Specifications** (2.1 RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Identity/Timestamps/Versions · 2.5 Logical Clock + Quarter-End Surge Window · 2.6 Money/Percent/Rounding · 2.7 Desk Policy Pinning · 2.8 Cascade Discipline · 2.9 Stale-Version Protection · 2.10 Segregation of Duties + Delegated Authority · 2.11 Path Resolution + Validation Precedence · 2.12 Conserved Ledgers) · **§3. Business Logic & Workflows** (3.1–3.9) · **§4. Endpoint Definitions** (55 rows) · **§5. Error Code Catalogue** (59 rows)

## Coverage

| Area | Scaffold | In PRD |
|---|---|---|
| Entities | 15 | 15 |
| Endpoints | 55 | 55 |
| Calculations | 8 (C1–C8, incl. dual variants) | 8 |
| Errors | 59 | 59 |
| Roles | 8 | 8 |
| Validation priorities | 16 | 16, in explicit order |
| State machines / transitions | 9 / 53 | 9 / 53 |
| OCC rules | 2 | 2 |

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** entities[].fields: 159 required / 159 present. Endpoint input/query_params/path_params identifiers: 81 / 81.

**Contract 2 — Rule Coverage: PASS.** All 16 validation priorities with explicit relative ordering plus two disambiguation examples; both OCC rules carry write endpoint, expected_quote_version, ERR_STALE_QUOTE_VERSION, 412; all 53 transitions have preconditions paired to error IDs and side effects stated; C1–C8 in prose with all constants (term multipliers 1.10/1.00/0.95/0.90, 30-day uplift blocks, exception minimum level 3, dominant multiplier 1.25, score cap 100); sibling-branch symmetry verified. All 59 error IDs referenced in §1–§3 narrative, not only §5.

**Contract 3 — §3 Path Purity: PASS.** 1080 backtick tokens scanned in §3; 0 paths, 0 bare HTTP methods.

## Note for the orchestrator

The scaffold header comment says 45 error codes but the actual §1.6 catalogue contains **59** unique entries. All 59 covered.

Constraints honoured: neither design yaml opened, no sibling task read, chunked appends used, only workspace/PRD.md modified.

Orchestrator verification: PRD.md = 445 lines / 106135 bytes, tail ends on the final §5 error-table row (real section boundary, not mid-sentence) — no truncation. Leak grep for the difficulty directive / "scaffold" / "test_recipe" is clean. Created `.scratch/step5`, `.scratch/step6`, `.scratch/step7` for per-step scratch isolation.

## Step 6: Generate implementation — 2026-09-05T22:04:28.814082403Z

Subagent summary (verbatim):

Step 6 complete. The reference implementation is finished, boots cleanly, and passed three end-to-end smoke scenarios.

## Deliverables
`workspace/implementation/` — Python 3 + Flask, 22 files, 3,584 lines, no `__pycache__`, in-memory dicts only, zero seeded data.

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` | 10 | `routes_config.py` | 369 |
| `requirements.txt` | 1 | `routes_quotes.py` | 309 |
| `app.py` | 94 | `routes_terms.py` | 205 |
| `clock.py` | 116 | `routes_exceptions.py` | 153 |
| `db.py` | 214 | `routes_revrec.py` | 92 |
| `errors.py` | 95 | `routes_approvals.py` | 381 |
| `response.py` | 83 | `routes_delegations.py` | 94 |
| `auth.py` | 64 | `routes_orderforms.py` | 219 |
| `validation.py` | 145 | `routes_sweeps.py` | 159 |
| `common.py` | 47 | `calc.py` | 419 |
| | | `workflow.py` | 315 |

## Endpoint coverage
**55 routes registered, an exact 1:1 match with the 55 rows of PRD §4** (diffed the registered URL map against the PRD table — no extras, no gaps; the PRD's prose "54" undercounts its own table by one, the `/_clock` endpoint).

## Written this session
- `routes_sweeps.py` — `POST /expiry-sweeps` (three origin-specific cascades, BOOKED-form guard on APPROVED, `QUOTE_EXPIRED` voids, ACTIVE-grant lapse), `POST /sla-escalation-sweeps` (surge-aware +2/+1 level jump capped at 4, `at_backstop`, breach bookkeeping), `POST /_clock/set_current_utc`.
- `app.py` — 9 blueprints, `before_request` authentication, `ApiError`/404/405/`HTTPException` handlers all emitting the §2.2 envelope, `0.0.0.0:$PORT` (default 10000), `threaded=True`, no reloader.

## Two PRD-conformance bugs found and fixed while smoke-testing
1. `calc.margin_give_up_cents` returned a *negative* figure for a healthy deal. PRD §3.2: "It is only ever charged when `final_margin_pct` sits strictly below `margin_floor_pct`" — now clamped to 0 above the soft floor.
2. `POST /quotes/{id}/reopen` stamped the cancelled request's `decided_at` but not `total_turnaround_hours`. PRD §3.8 states the general rule for *any* terminal status, and CANCELLED is terminal — now stamped (matching the EXPIRED path in the new sweep).

## Smoke-test result (PORT 35469, killed by its own PID; no pattern kills used)
Envelope verified: `meta.api_request_id` = `req_` + 20 upper-alnum, `api_request_timestamp` with exactly 3 fractional digits, `response_type` `object`/`array`/`error`, errors as `{error_id, message}` inside `data`, list `meta` carrying `limit`/`offset`/`total_count`/`has_more`. 401 unauthenticated, 403 role, 404 unrouted all correct.

- **Happy path**: policy + 4 tiers + activate → product + 2 bands → account → quote (36mo) → line (qty 150, 5% req) → preview → submit → L1 (DealDeskAnalyst) → L2 (SalesDirector) → request APPROVED / `sla_state` MET → order form → send → sign → book → reverse. Arithmetic hand-checked: marginal-progressive net 118,287,000, 2% rebate → 115,921,260 TCV, C8 ARR 39,429,000 = net/3yr; the account ledger went 0 → 39,429,000 → 0 on reversal.
- **Sweeps**: clock +25h → SLA sweep escalated the L1 step, created an L2 replacement with `escalated_from_step_level` 1 and fresh SLA fields, `escalation_count` 1, `sla_state` BREACHED. Clock +50d → expiry sweep expired the quote, drove the request OPEN→EXPIRED with `decided_at`, `total_turnaround_hours` 1200.0 and BREACHED retained.
- **Full fork**: two non-standard terms (severity/risk 0.25→5.0 and 0.833333→25.0, aggregate 30.0, dominant 31.25), revrec assessment CLEARED, exception ACCEPTED (give-up 3,428,004, level floored to 3), submit → terms axis PENDING_LEGAL, two legal APPROVEs → CLEARED, L1/L2 direct + **L3 under a delegation grant** (`delegation_grant_id` recorded, `used_step_count` → 1) → quote APPROVED; renegotiate clone created; exception revoke correctly refused with `ERR_QUOTE_STATE_INVALID_FOR_REVOKE` from APPROVED. Notably, accepting the exception correctly re-staled the CLEARED assessment and blocked submit with `ERR_REVREC_NOT_CLEARED` until re-assessed — the §3.6 staleness rule working as specified.

`.scratch/step6/` removed; sibling `.scratch/step5` and `.scratch/step7` left untouched. Did not read `test_suite/`, `test_helpers/`, either difficulty/corner design file, or any sibling task, and did not modify `worklog.md`, `PRD.md` or `INSTRUCTION.md`.

## Step 5: Generate unit tests — 2026-09-05T22:24:14.567848891Z

Subagent summary (verbatim):

The test infrastructure and test suite are complete and verified.

## Tests emitted

**70 tests total, all tagged to exactly one design instance.**

| Queue | Instances in index | Non-stub | Covered | Tests |
|---|---|---|---|---|
| A — Difficulty (`SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8) | 18 | 18 | 18 (≥2 each) | 36 |
| B — Corner (`SCAFFOLD_CORNER_DESIGN.yaml` §1.9) | 53 | 34 | 34 (≥1 each) | 34 |

Queue B by section: entities 9, state_machines 5, calculations 3, validations 4, endpoints 3, errors 4, rbac 3, cross_cutting_complexity_layers 2, consistency_model 1.

## Instances skipped

**19 corner instances, all carrying an explicit `excluded_because:` stub in the yaml** — each one names the queue-A difficulty instance that already covers the identical trigger (e.g. `line_write_on_a_non_draft_quote_returns_quote_not_draft` → `resubmit_conflict_state_error_wins_over_margin_floor_breach`; the six error-catalogue stubs at yaml lines 2071–2113; `four_level_cascade_from_a_single_reopen_call`; `both_line_pricing_variants_diverge_on_the_same_quote`; `surge_adjusted_service_level_threshold_at_the_boundary`; `quote_owner_cannot_decide_its_own_approval_step`; `delegatee_can_decide_a_step_inside_the_grant_window`; `state_error_outranks_the_fiscal_floor_on_resubmit`). No non-stub instance was skipped, and nothing was weakened, xfailed or placeholdered.

One design assertion was **not** transcribed literally because the PRD contradicts it: `order_form_generation_with_a_stale_expected_quote_version_is_rejected` asserts `of2.generated_from_quote_version == q_v2` (the version read *before* the second generate), while PRD §3.9 states generation "increments `Quote.version` by one and then records `generated_from_quote_version` as the **incremented** value". The test asserts the PRD-derived value (compared against a fresh read after generation); every other assertion in that instance is intact.

## Verification gates (all clean)

- `ast.parse` on every file; `pytest --collect-only` → **70 tests collected, 0 errors**.
- Citation checker: every test has exactly one `Design:` line as its **last** docstring line, and every quoted span ≥8 words is a **verbatim** substring of `workspace/PRD.md` → `problems: 0`.
- Section checker: every `PRD (§X.Y)` label resolves to the section that actually contains the quote → no mismatches.
- Coverage audit against both yamls: no missing instance, no difficulty instance under 2 tests, no tag pointing at a stub or at a non-existent instance.
- Unused-import sweep: clean (fixed three stragglers in test_01/test_03/test_09).

## Files

`test_helpers/` — `__init__.py` 44, `api_client.py` 205, `api_errors.py` 155, `assertions.py` 465, `constants.py` 169, `factories.py` 243, `fixtures.py` 735, `test_users.py` 109, `types.py` 465.

`test_suite/` — `conftest.py` 68, `test_01_quote_pricing_and_totals.py` 252, `test_02_nonstandard_term_risk.py` 115, `test_03_approval_workflow_cycles.py` 193, `test_04_cascade_propagation.py` 210, `test_05_conserved_ledgers.py` 186, `test_06_validation_precedence.py` 178, `test_07_boundaries_and_service_levels.py` 161, `test_08_cross_entity_state.py` 220, `test_09_temporal_overlaps.py` 177, `test_10_entity_shapes_and_defaults.py` 298, `test_11_state_machine_transitions.py` 198, `test_12_calculation_thresholds.py` 137, `test_13_validation_gates.py` 223, `test_14_endpoint_actions.py` 148, `test_15_error_surfaces.py` 196, `test_16_rbac_boundaries.py` 128, `test_17_concurrency_and_consistency.py` 171. Total 5,849 lines.

Both directories are at the **task root**; nothing named `test_helpers` or `test_suite` exists under `workspace/`. Scratch stayed in `.scratch/step5/`; `worklog.md`, `workspace/PRD.md`, `SCAFFOLD*.yaml` and `workspace/implementation/` were never written, and `implementation/` was never read or listed.

Orchestrator note: verified that no `test_helpers/` or `test_suite/` directory landed under `workspace/`; both are at the task root as required. Steps 5 and 6 were launched concurrently in a single message, so the implementation generator started before `test_suite/` existed (physical isolation from the measuring instrument).

## Step 7: Run tests and iterate — 2026-09-05T22:35:30.136988770Z

Subagent summary (verbatim):

All 8 rounds pass. Here is the summary.

## Iterations run
**2** (iteration 1 diagnosed, iteration 2 verified clean).

## Tests deleted
**None.** Both failures survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), so neither was a PRD-silence or collapse-pattern case.

## Fixes applied to `test_helpers/`
None. Iteration 1 produced only 2 deterministic failures with no shared setup-error cluster, so the common-upstream-fixture triage hint did not apply.

## Fixes applied to `test_suite/`
- `test_suite/test_08_cross_entity_state.py`, `test_booking_is_refused_while_the_account_sits_on_credit_hold` — the test asserted `form["generated_from_quote_version"] == submitted["version"]`, comparing against the quote version read *before* generation. PRD 3.9 states: *"Generation increments `Quote.version` by one and then records `generated_from_quote_version` as the **incremented** value, so a freshly generated form always matches its quote exactly"*. Failure signature was `assert 4 == 3`. Fixed to `== submitted["version"] + 1` and added a corroborating read asserting the quote itself now carries that incremented version — making the test *more* faithful to PRD, not less. This is the minority call site: `test_14_endpoint_actions.py` already used the correct convention (comparing to a post-generation quote read) and passed in all 8 rounds.

## Fixes applied to `implementation/`
- `workspace/implementation/routes_terms.py`, `_hold_conflict()` — off-by-one in the price-hold cooldown gap. The code computed `gap = (start - existing_end).days`, so windows ending `2027-12-31` and starting `2028-01-30` scored a gap of 30 and passed a 30-day cooldown. PRD 3.4 requires refusal *"unless the two inclusive windows are separated by at least the pinned revision's `price_hold_cooldown_days` days"*, and PRD 3.1 names the value *"the mandatory gap between two price-hold windows"*. Because both windows are **inclusive at both ends**, the days separating them are those belonging to neither window — only 29 here. The endpoint-difference reading is not merely an alternative: it scores two directly abutting windows (one ending the day before the other starts) as separated by 1 day, which contradicts both "inclusive" and "gap", so the PRD sentence uniquely determines the clear-days reading. Changed to `(start - existing_end).days - 1` on both the forward and backward branches.

## Final sweep evidence (8 rounds, from `results.$i.json`)

| Round | passed / total | failed | errors |
| --- | --- | --- | --- |
| 1 | 70 / 70 | 0 | 0 |
| 2 | 70 / 70 | 0 | 0 |
| 3 | 70 / 70 | 0 | 0 |
| 4 | 70 / 70 | 0 | 0 |
| 5 | 70 / 70 | 0 | 0 |
| 6 | 70 / 70 | 0 | 0 |
| 7 | 70 / 70 | 0 | 0 |
| 8 | 70 / 70 | 0 | 0 |

Union of failing tests across all 8 rounds: **0**. No flakiness observed — iteration 1's 2 failures were deterministic in all 8 rounds, and iteration 2's clean result was likewise uniform, so no load-induced timeout/connection noise had to be discounted.

Housekeeping: `.scratch/step7/` removed (sibling `.scratch/step5/` left intact); `worklog.md`, `PRD.md`, and `INSTRUCTION.md` untouched.

Orchestrator verification: independently re-read all 8 `results.$i.json` — every round reports 70/70 passed, 0 failed, 0 errors. `workspace/SWEEP_DONE` sentinel written 2026-09-05T22:31:39.557Z. The sweep ran via the pre-written `workspace/sweep.sh` under `setsid nohup` (avoids the inline-quoting and reaping failure modes). Step 8 will run because Step 7 applied 1 `implementation/` fix and 1 `test_suite/` fix (non-zero diff).

## Step 8: Finalize PRD — 2026-09-05T22:43:21.746937554Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 445 lines; `PRD_FINALIZED.md`: 445 lines — 0% line delta (one line revised in place, +4 sentences of prose).

## Changes
- **§3.4 (Price holds are rationed in time)** — *revise* — pinned the arithmetic of "separated by at least `price_hold_cooldown_days` days" to the clear-days reading: separation = (later `hold_start_date` − earlier `hold_end_date`).days − 1; abutting windows are separated by zero days; 31 Dec vs 30 Jan is twenty-nine days, not thirty; overlapping windows always conflict — `implementation/routes_terms.py:46-59` (`_hold_conflict`, lines 53-59).

## Per-edit pre-edit search log
**Edit 1 — §3.4 price-hold cooldown separation**
- (a) Subject: the day-count arithmetic used to decide whether two inclusive `PRICE_HOLD_RENEWAL` windows respect `price_hold_cooldown_days`, plus the degenerate overlap case in the same predicate.
- (b) Impl paths enumerated (grep for `hold_start_date|hold_end_date|price_hold_cooldown|_hold_conflict` across all of `implementation/`, then read): `routes_terms.py:46-59` (`_hold_conflict` — overlap early-return, forward branch `(start - existing_end).days - 1`, backward branch `(existing_start - end).days - 1`, `gap < cooldown_days`); `routes_terms.py:94-113` (the only callsite — candidate scoping by category, `review_state in (PENDING, APPROVED)`, same `hold_product_id`, same `account_id` via the other term's quote, iterated in `created_at` order across all quotes); `routes_terms.py:68-81` + `:75-76` (hold-field co-requirement and `hold_end_date >= hold_start_date`); `routes_config.py:35` (`price_hold_cooldown_days` integer, `ge: 0` — so no negative cooldown can make the overlap claim false); `routes_config.py:310` (`GET /products/{id}/price-holds` sort by `hold_start_date` — read-only, unaffected); `validation.py:75-79` (`date` coercion, so `.days` is an exact whole-day difference). No other write path re-checks the cooldown (term review, submit, reopen and the sweeps never call `_hold_conflict`), so the sentence stays scoped to term attachment as PRD §2.11 item 13 already says.
- (c) Wording adjustments made: stated the rule symmetrically as "the clear days belonging to neither window" rather than only the forward "new window starts after the existing one ends" direction, so the backward branch (`existing_start - end`) is equally described; wrote the overlap clause as "not separated and always conflict" without tying it to a cooldown value, since the `ge: 0` bound means the early return is unconditional for every configurable cooldown; kept the sentence inside the existing paragraph, ahead of the untouched scoping sentence, so the candidate-set rules and the `REJECTED`/`WITHDRAWN` exemption remain verbatim.

The other Step 7 item (`generated_from_quote_version`) required **no** PRD change: `routes_orderforms.py:55-60` does `db.touch(quote)` and then records `quote["version"]`, i.e. the post-increment value, which is exactly what §3.9 already states verbatim. That failure was a test-artifact convention bug at the minority callsite, not PRD silence.

Orchestrator verification: PRD_FINALIZED.md is 106694 bytes vs PRD.md 106135 (+559 bytes) — not byte-identical, so the edit landed. Step 9 will run as three sequential module-partitioned passes over one shared PRD_COMPLETED.md (pass 1 performs the cp; passes 2 and 3 must not).

## Step 9: Complete PRD — 2026-09-05T23:07:39.126404053Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 edited in place with no `cp`). Partition: pass 1 = app/auth/validation/db/clock/response/errors/common/routes_config; pass 2 = calc/routes_quotes/routes_terms/routes_exceptions/routes_revrec; pass 3 = workflow/routes_approvals/routes_delegations/routes_orderforms/routes_sweeps.

### Pass 1 summary (verbatim)

**Setup:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` performed (PRD_FINALIZED.md verified present, 445 lines). Line count **445 before → 447 after** (the +2 is two appended §5 error-table rows). Tail still ends on a §5 error-table row; header count unchanged at 29.

**Counts:** 15 ambiguity-pins, 4 mismatch-revisions (19 changed lines total).

- §2.1 — revise — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` is `ERR_UNAUTHENTICATED`, not just an empty string — auth.py:29-32
- §2.1 — insert — ambiguity — both header values are stripped before being recorded or compared, so `  rep-1  ` equals `rep-1` for ownership — auth.py:37,42
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A-Z0-9` — response.py:11,15
- §2.2 — insert — ambiguity — `api_request_timestamp` is the logical-clock reading, not wall clock — response.py:21
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; unknown query params ignored — validation.py:109-121,132-137
- §2.3 — insert — ambiguity — every ordering breaks ties by insertion order — db.py:73-79,149,161,310
- §2.4 — insert — ambiguity — `hold_start_date`/`hold_end_date` render as bare `YYYY-MM-DD`; "unset" fields are present carrying JSON `null`; client instants accept `Z` or an offset, zoneless read as UTC — response.py:38-41, clock.py:48-63
- §2.4 — revise — mismatch — `version` advances by exactly one **per HTTP request** however many times that request touches the record — db.py:102-126, db.py:82-99
- §2.6 — insert — ambiguity — `_cents` and all percentage/risk/hour fields are JSON numbers, never quoted strings — response.py:36-37
- §2.6 — revise — mismatch — `margin_floor_pct`'s four decimals are a convention; the service stores supplied precision and never rounds or rejects on precision — routes_config.py:23
- §2.8 — insert — ambiguity — a cascade reaching a record the addressed write already moved counts as one mutation for `version` — db.py:102-126
- §2.11 — insert — ambiguity — unrouted path `ERR_NOT_FOUND` (404), wrong method `ERR_METHOD_NOT_ALLOWED` (405), both behind step-1 auth; trailing slash insignificant — app.py:42,48-51,57-69
- §2.11 step 4 — revise — ambiguity — names the four cross-field comparisons as `ERR_INVALID_REQUEST`; absent/empty body = empty object, non-object body = 400, explicit `null` = omitted; bodyless transition endpoints accept only an empty body — routes_config.py:46-60,146,194,224; validation.py:15-27,99-104
- §3.1 — revise — mismatch — a revision takes **sixteen** configured numbers plus `name` (seventeen required fields) — routes_config.py:21-39
- §3.1 — insert — ambiguity — zero matrix rows fails the coverage check; when both fail, coverage beats `ERR_DESK_POLICY_NOT_DRAFT` — routes_config.py:75-101
- §3.1 — insert — ambiguity — touching bands do not overlap; matrix rows may be added to `DRAFT`, `ACTIVE` or `SUPERSEDED` — routes_config.py:150-156
- §3.1 — revise — ambiguity — an unbounded quantity band reports `max_quantity` as explicit `null` — routes_config.py:240
- §3.1 — insert — ambiguity — a credit decision replaces `credit_note` wholesale, is accepted from any posture including a repeat, and bumps `version` — routes_config.py:361-369
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` 404 and `ERR_METHOD_NOT_ALLOWED` 405 rows — errors.py:76-77

### Pass 2 summary (verbatim)

**File integrity:** 447 lines before → 447 after (all in-paragraph). Tail still ends at `| ERR_METHOD_NOT_ALLOWED | 405 |`. **No `cp` run** — 23 targeted Edit calls.

**Counts:** 19 ambiguity-pins, 4 mismatch-revisions.

- §3.2 — revise — ambiguity — header patch: the empty subset is well-formed and still reprices, bumps `version` and stales assessments — routes_quotes.py:127-136
- §3.2 — insert — ambiguity — line body FKs resolved `quote_id` then `product_id` — routes_quotes.py:171-176
- §3.2 — revise — mismatch — `volume_tier_level_applied` records 0 whenever *no band applies* — calc.py:112
- §3.2 — insert — ambiguity — bundle anchor: earliest-created sibling carrying the anchor product supplies the ratio denominator — calc.py:83-91
- §3.2 — insert — ambiguity — implicit full-quantity band exists only when a product has no bands; bands all above `quantity` give `final_net_cents` 0 — calc.py:123-134
- §3.3 — insert — ambiguity — zero `list_total_cents` → both blended figures `0.000000` — calc.py:185-186
- §3.3 — insert — ambiguity — matrix level out-of-band: ≥ top `max_discount_pct` takes the top tier; below every `min_discount_pct` → level 0 — calc.py:197-206
- §3.3 — revise — ambiguity — zero order total → margin `0.000000`; margin otherwise unclamped, may be negative — calc.py:191-194
- §3.3 — revise — mismatch — exception *accept* reruns full repricing; *revoke* re-derives `required_approval_level` alone — routes_exceptions.py:117,150
- §3.3 — revise — ambiguity — pricing-preview `lines` ordering and exact field set; single object, no pagination, no `allocation_lines` — routes_quotes.py:247-308
- §3.4 — insert — ambiguity — hold fields on a non-hold category are `ERR_INVALID_REQUEST` ahead of FK resolution; FK order `quote_id` then `hold_product_id` — routes_terms.py:67-87
- §3.4 — insert — ambiguity — empty risk input set → both scores `0.00`, no co-signature obligation — calc.py:302-307
- §3.5 — insert — ambiguity — an exception may be filed against a quote in any status and leaves the quote untouched — routes_exceptions.py:31-52
- §3.5 — revise — ambiguity — a rejection writes nothing to the quote — routes_exceptions.py:84-90
- §3.5 — revise — ambiguity — revoke keeps the acceptance-time `decision_note` when omitted, and marks assessments stale — routes_exceptions.py:140-152
- §3.6 — insert — ambiguity — assessments may be opened against a quote in any status; opening leaves the quote untouched — routes_revrec.py:29-48
- §3.6 — revise — ambiguity — zero-line quote is `SINGLE_ELEMENT` — calc.py:336-337
- §3.6 — insert — ambiguity — no allocable line: nothing allocated, residual 0, `allocable_amount_cents` still reported — calc.py:355,396
- §3.6 — revise — ambiguity — `allocation_lines` ordered by line `created_at` ascending; usage lines report `extended_list_cents` as `ssp_cents` — calc.py:377-390
- §3.6 — revise — ambiguity — `BLOCK` recomputes nothing and does not re-base `snapshot_quote_version` — routes_revrec.py:86-87
- §3.6 — revise — mismatch — version-advance producers: accepting *or revoking* an exception; a rejected exception moves nothing — routes_exceptions.py:84-90,150-152
- §3.7 — insert — ambiguity — role/decision pairing on term review enforced with `ERR_FORBIDDEN_ROLE` after body validation, before state checks — routes_terms.py:164-167
- §3.7 — revise — mismatch — `COSIGN` precondition order is term-state, quote-state, `requires_cfo_cosign`, `cfo_cosigned_at` — routes_terms.py:174-181
- §3.8 — insert — ambiguity — no matrix band at a step's level → `sla_hours_effective` `0.00` and `sla_due_at` = `created_at` — calc.py:230-239
- §3.8 — revise — ambiguity — approval re-base truncates to the quarter-end instant only when it would otherwise fall strictly after it — calc.py:253-261

### Pass 3 summary (verbatim)

**File state:** 447 lines / 117,893 bytes before → **447 lines / 123,085 bytes** after. **No `cp` was run** — 21 targeted Edit calls.

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions.

- §2.10 — insert — ambiguity — grant inputs pinned: all five required, `tier_level` 1–4 and untied to the granting role's level, `max_discount_pct` >0 and ≤1, self-delegation is `ERR_INVALID_REQUEST`, revoke requires `ACTIVE` — routes_delegations.py:20-37,89-90
- §2.10 — insert — ambiguity — with several live grants at the step's level, the earliest-created one whose ceiling admits the deal is recorded; `ERR_DELEGATION_SCOPE_EXCEEDED` only when none admits — routes_approvals.py:199-210
- §2.10 — insert — ambiguity — grant list filters `grantee_user_id`, `tier_level`, `status`, conjunctive — routes_delegations.py:64-79
- §3.3 — insert — ambiguity — a repricing pass writes only lines whose seven computed figures actually move — workflow.py:79-84
- §3.4 — insert — ambiguity — the `requires_cfo_cosign` placement pass rewrites only terms whose flag changes — workflow.py:139-143
- §3.7 — insert — ambiguity — submit's response body is the updated quote, not the approval request — routes_approvals.py:137
- §3.7 — revise — **mismatch** — step-decision preconditions reordered: state, SoD, approver authority, `ERR_QUOTE_EXPIRED` last — routes_approvals.py:222-229
- §3.7 — revise — **mismatch** — `APPROVE` clears the discount axis when the step's `level` is *at or above* `required_level` — routes_approvals.py:245
- §3.7 — insert — ambiguity — `REQUEST_CHANGES` leaves `decided_at`, `total_turnaround_hours`, `sla_state` untouched — routes_approvals.py:260-266
- §3.7 — revise — ambiguity — reopen cancels only the newest request and only while `CHANGES_REQUESTED`, stamping `decided_at` and `total_turnaround_hours` — routes_approvals.py:289-296
- §3.8 — insert — ambiguity — a step at a level the matrix does not define has `assigned_role` unset, so only a delegation can decide it — workflow.py:221
- §3.8 — insert — ambiguity — the escalation sweep's candidate set is fixed at start, so its own replacements are never escalated in the same run — routes_sweeps.py:105-109
- §3.8 — revise — **mismatch** — a level-4 step that breaches is still escalated, its replacement landing at level 4 again — routes_sweeps.py:127-131
- §3.8 — revise — **mismatch** — dropped "no further escalation is possible" from the `at_backstop` sentence — routes_sweeps.py:137-138
- §3.8 — insert — ambiguity — each request appears at most once in `breached_request_ids` — routes_sweeps.py:140-141
- §3.8 — revise — ambiguity — expiry sweep expires the newest request only while `OPEN`, computing `total_turnaround_hours` alongside `decided_at` — routes_sweeps.py:54-63
- §3.8 — revise — ambiguity — delegation grants swept after every candidate quote, ascending `created_at` — routes_sweeps.py:78-85
- §3.8 — revise — ambiguity — renegotiation: source status ungated, no expiry check; clone copies `account_id`/`title`/non-overridden header, stamps owner from the actor, pins `desk_policy_id` to the **source's** revision, copies the source lines' snapshots — routes_approvals.py:330-367
- §3.9 — insert — ambiguity — generation requires quote `APPROVED` then `expected_quote_version` then non-expiry, in that order; signatory strings unvalidated — routes_orderforms.py:26-45
- §3.9 — insert — ambiguity — a `DECLINED` outcome leaves `signed_by_name` unset even when supplied — routes_orderforms.py:134-136
- §3.9 — revise — ambiguity — reversal reports a non-`BOOKED` parent quote with `ERR_ORDER_FORM_STATE_INVALID` and applies no expiry check — routes_orderforms.py:196-199

**Integrity check (final pass):** 29 headers, byte-identical header list to PRD_FINALIZED.md; §1–§5 all present; §4 endpoint table still 55 rows; §5 error table intact at 61 rows (PRD_FINALIZED has 59 — pass 1 legitimately added `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`); file still ends at `| ERR_METHOD_NOT_ALLOWED | 405 |`.

### Orchestrator close-out

- Totals across the three passes: **51 ambiguity-pins, 12 mismatch-revisions**.
- `workspace/PRD_COMPLETED.md` = 447 lines / 123,085 bytes vs `PRD_FINALIZED.md` 445 lines / 106,694 bytes — **not byte-identical**, so the scan genuinely ran (the byte-identical failure mode did not occur).
- Neither Step 8 nor Step 9 modified `implementation/`, `test_suite/` or `test_helpers/`, so the Step 7 sweep evidence (8/8 rounds at 70/70) remains the final test state; `results.{1..8}.json` are retained under `workspace/implementation/`.
- Cleanup: removed `.scratch/`, `workspace/sweep.log`, `workspace/round.*.log`, `workspace/SWEEP_DONE` and all `__pycache__/`. Kept `workspace/sweep.sh` for reproducibility.
- Pipeline complete through Step 9.
