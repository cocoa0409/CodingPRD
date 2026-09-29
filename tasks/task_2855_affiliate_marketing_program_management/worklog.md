# Worklog — task_2855_affiliate_marketing_program_management

## Step 1: Create task directory — 2026-09-05T07:20:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2855_affiliate_marketing_program_management` and its `workspace/` subdirectory. Index 2855 was pre-assigned by the orchestrating command; no index scan performed (concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T09:19:30.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2855_affiliate_marketing_program_management/`)
- `SCAFFOLD.yaml` — 3641 lines / 176 KB. §1.0–§1.7 only (no design keys). 14 entities, 9 state machines, 3 §1.2.1 concurrency rules, 9 calculations, 51 validation-priority rows, 50 endpoints, 51 errors, 8 roles (`ProgramAdmin`, `PartnerManager`, `ComplianceAnalyst`, `FinanceAnalyst`, `FinanceController`, `AffiliatePartner` (entity_backed), `TrackingIngestor`, `Anonymous`). Profile: `ledger_reconciliation` / `compliance_audit`, flat topology, branching state machines, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers = optimistic_concurrency + dual_variant_calculation + cascading_side_effects + rate_threshold_triggers.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1980 lines / 128 KB. Single key `scaffold_difficulty_design`: **9 rules, 19 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant — 2 instances each, 3 for the priority-conflict rule).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4069 lines / 270 KB. Single key `scaffold_corner_design`: **66 instances across all 9 legal sections** — entities 12, state_machines 16, calculations 8, validations 10, endpoints 4, errors 4, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1. 12 of those are `excluded_because` stubs citing a specific §1.8 instance; the other 54 carry full `test_recipe`s.

**Lint verdict (verbatim)**
```
Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  926

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Independent checks also pass: instance names unique across both design files, no illegal section names, every stub's `difficulty_instance` citation resolves, and **all 51 declared errors are exercised** by at least one instance (the last gap, `ERR_REVISION_LIMIT_REACHED`, was closed by an added `state_machines` instance that drives two full CHANGES_REQUESTED rounds and then refuses the third).

**Design adjudications made**
- `HELD_TAX_DOC` is assigned only at `validate`, so generation-time lines for partners without a tax form stay `INCLUDED` at 2400 bps withholding; the release-hold instances therefore file and verify a W9 first (priority 48 `ERR_TAX_DOCUMENT_INVALID` guards every release).
- The trailing fraud variant is recomputed only on case create/transition, never on `status-change`, so an "advance the clock, then reinstate" success path is unreachable; reinstatement coverage was split across two separate partners (one blocked by an open case, one sitting exactly on the 25.0/30.0 trailing ceiling).
- Segregation of duties is only cleanly testable inside one role (case opener ≠ verifier); screener/decider and preparer/approver clashes would need one user id holding two roles, so they are covered as role-denial claims instead.
- No "activate an already-ACTIVE policy" invalid-transition claim, since §1.6 declares no such error; that call is instead used for the `ERR_STALE_POLICY_VERSION` OCC claim, which needed `expected_policy_version: "${pol_v1} - 1"` because there is no policy-update endpoint to bump the version.
- OCC breadth covers all three §1.2.1 rules plus the extra §1.4-only policy guard: a tax-document filing bumps `Affiliate.version` under a decide, a late in-window click bumps `Conversion.version` under attribute, and a `release-hold` bumps `PayoutBatch.version` under approve (net_payable 0 → 4000, which is exactly what the stale approver would have blessed).
- Every numeric assert is pre-computed as a literal against the §1.3 formulas (e.g. 87.8 PASS, 83.4 after a CONTENT_NEWSLETTER resubmit, 52.3 vs 29.1 for the restricted-screen variant, 65 vs exactly 70 for the auto-suspension threshold, gross 4000 / withholding 960 / net 3040, variance exactly 50 bps at fee 201).

**Orchestrator note:** the subagent flagged that `scenario:` in `SCAFFOLD.yaml` still contained the verbatim `Generate task harder than expert level!` difficulty directive. The orchestrator stripped that line immediately after Step 2 (verified by grep: zero matches across all three YAMLs) so it cannot reach `PRD.md`.

## Step 3: Copy shared files — 2026-09-05T09:20:19.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T09:36:00.000Z

PRD generation for task 2855 is complete.

**Output:** `workspace/PRD.md` — **469 lines**, built incrementally with chunked `cat >>` heredocs (no single giant Write). The tail is a complete section: the final line is the last row of the §5 error table (`| ERR_NO_ELIGIBLE_PAYOUT_LINES | 422 |`), no mid-sentence truncation.

**Sections**

- §1 Introduction
- §2 Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified programmatically) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Mutation Counters · 2.5 Path Resolution Order for Partner-Scoped and Order-Scoped Collections · 2.6 Money, Basis Points and Rounding Discipline · 2.7 Stale-View Rejection on Version-Guarded Writes · 2.8 Segregation of Duties · 2.9 The Logical Clock · 2.10 Rule Evaluation Order (all 51 rules, ascending) · 2.11 Cascade Discipline
- §3 Business Logic & Workflows (9 subsections): 3.1 Networks, Partner Registration and Sub-Networks · 3.2 Application Screening and the Decision Fork · 3.3 Commission Rate Cards and Their Effective Windows · 3.4 Tracking Implementation and Click Ingestion · 3.5 Attribution, Channel Deduplication and Commission Booking · 3.6 The Commission Ledger, Validation and Clawback · 3.7 Compliance Monitoring, Violation Cases and Fraud Scoring · 3.8 Tax Documentation · 3.9 Settlement: Payout Batches, Lines and Network Reconciliation
- §4 API Endpoints — 4-column table (Method, Path, Description, Authorized Role(s)), all 50 rows
- §5 Error Codes — 2-column table (Error ID, HTTP Status Code), all 51 rows in scaffold order

**Hard Contracts**

- **Contract 1 — Field-Name Coverage: PASS.** All 162 entity field names across the 14 entities appear as backticked tokens (script-verified); the one initial miss, `tracking_link_id`, was added to §3.4. All 8 role names, all 51 error IDs, and every endpoint `input` field are present (`target_status` and `verification_outcome` were added on the second pass).
- **Contract 2 — Rule Coverage: PASS.** All 51 validations (§2.10, in priority order, each with error ID and status), all 51 state-machine transitions across the 9 stateful entities, all 15 calculation entries/variants (site quality with STANDARD_SCREEN/RESTRICTED_CATEGORY_SCREEN, brand suitability, attribution resolution with LAST_CLICK_RAW/INCREMENTALITY_ADJUSTED, policy selection, incrementality score, fraud score with POINT_IN_TIME/TRAILING_90D_DECAY, payout line settlement, network fee reconciliation, clawback allocation), all 4 version-guarded writes, and every named constant value is present literally (`0.01` decay reworded from prose to the numeral on the verify pass).
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 that start with `/`, are a bare HTTP method, or combine method+path; additionally zero unbacktick-ed occurrences of GET/POST/PUT/PATCH/DELETE or path-like `/token` strings anywhere in §3.

**Notes / scaffold conflicts resolved without inventing rules**

- `POST /affiliates` side-effect says `tax_document_status` is set to `MISSING`, but that field's enum is `NONE | PENDING | VALID | EXPIRED | REJECTED` (default `NONE`). PRD says `NONE`; `MISSING` is never mentioned.
- Validation priority 3 (`ERR_AFFILIATE_NOT_FOUND`) claims to also cover an unknown `network_id` at registration, which would make priority 11 (`ERR_NETWORK_NOT_FOUND`, explicitly scoped to registration) unreachable. PRD routes unknown `parent_affiliate_id` → 3 and unknown `network_id` → 11 so both codes stay reachable.
- `concurrency_rules` lists 3 OCC rules but priority 32 and the activate transition also require `expected_policy_version`; §2.7 documents all four version-guarded writes.
- Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. Scratch work used `/tmp/task_2855_prd/` only.

**Orchestrator verification (truncation guard):** independently confirmed 469 lines / 105441 bytes; headings §1–§5 all present and closed; §4 table has exactly 50 method rows; §5 table has exactly 51 `ERR_` rows; file ends at the final table row, not mid-sentence. Also grepped PRD.md for `harder than expert` / `expert level` / `scaffold` — zero matches, so the Step 2 difficulty directive did not leak.

## Step 6: Generate Implementation — 2026-09-05T10:14:00.000Z

The implementation is complete, verified, and my smoke-test server is shut down (port 51855 free; killed by exact pid only — no pattern kill was ever used).

## Modules

`/home/ubuntu/github/CodingPRD/tasks/task_2855_affiliate_marketing_program_management/workspace/implementation/`

| File | Lines | Contents |
|---|---|---|
| `common.py` | 600 | logical clock, ISO-8601 3-digit-ms formatting, `Decimal` half-up helpers, the 51 error-id → HTTP-status table, `ApiError`/`fail`, the 14-dict in-memory `Store`, `new_row`/`touch` (one version bump per row per request), deterministic `ordered()`, envelope + pagination, 8-role RBAC (`authorize`, `require_owner`, `check_sod`), all enums, and every body validator |
| `serializers.py` | 156 | exact per-entity field tuples; internal keys (`_seq`, `minimum_waived`) never leak |
| `calc.py` | 208 | all 7 calculations + every declared threshold/constant |
| `services.py` | 471 | collection helpers, incrementality/fraud recompute with auto-suspension, suspend/terminate cascades as ordered hops, validation sweep, tax expiry/refresh, click eligibility + ranking, ledger append, line/batch recompute, entry un-stamping |
| `routes_a.py` | 196 | networks, partner registration (incl. anonymous self-registration), status-change, partner-scoped lists |
| `routes_b.py` | 257 | applications (file/screen/decide/resubmit), tax documents + verification |
| `routes_c.py` | 205 | rate cards (draft/activate with supersession), tracking links, click ingestion + the candidate-count/version side effect |
| `routes_d.py` | 323 | orders, the five-step attribution run, dual audit rows, order adjustments (reversal vs. clawback) |
| `routes_e.py` | 219 | monitoring scans with cooldown collision, violation-case filing and the full transition machine |
| `routes_f.py` | 351 | ledger reads, batch generate/validate/approve/pay/void, payout lines, hold release, test clock |
| `app.py` | 72 | factory, error handlers (envelope on 400/404/405/500), `app.run` on `$PORT` |
| `start.sh` / `requirements.txt` | 10 / 1 | launcher (conditional pip install, `exec python3 app.py`) |

**3069 lines total. 50 endpoints — exact parity with the SCAFFOLD table (0 missing, 0 extra).** Storage is in-memory dicts only; nothing is seeded, and no non-source file exists in the directory.

## Verification

Three end-to-end smoke scripts (~140 assertions) all green on a fresh boot: full onboarding → screening → both approval branches → rate-card supersession → link/click → attribution (full-credit, incrementality-reduced, empty-candidate-set, dedupe) → adjustments (pre-validation reversal and post-validation pro-rata clawback with batch restatement) → settlement (generate, below-minimum/tax/fraud holds, hold release with minimum waiver, `MATCHED` and `ACCEPTED_WITH_VARIANCE` at the inclusive 50 bps boundary, approval limit, pay, void, regeneration of un-stamped entries) → compliance (4-signal scan, case loop with two failed verifications, escalation, uphold, auto-suspension, cascade to links and payout lines, reinstatement gates). Every RBAC/SoD/OCC/precedence corner I probed returned the PRD's exact code and status.

Four apparent failures during this pass were all my test-script expectations being wrong, and each confirmed the implementation matched the PRD text: restricted-promo-method 0.90 multiplier (56.2 not 62.4 → `CONDITIONAL`, so `APPROVE` correctly gave `ERR_SCREENING_NOT_PASSED`), fee variance measured in bps against the batch's own fee (2c on a 100c fee is 200 bps → correctly refused), an `UPHELD` case is *not* a reinstatement gate (only open count, trailing score, parent status), and the cookie window's strict upper bound (a click at exactly `placed_at` is ineligible).

## PRD ambiguities resolved

- `ERR_UNAUTHENTICATED` only when `X-User-ID` is absent/empty; a missing `X-User-Role` is treated as `Anonymous`.
- Uniqueness collisions with no dedicated code (network `name`, partner `contact_email`, `policy_code`, per-partner `sub_id`) → `ERR_INVALID_REQUEST` (400).
- Body-borne reference existence resolves before field validation only when the reference is supplied non-null; a missing required reference falls through to rule 14.
- Activating a non-`DRAFT` rate card → `ERR_INVALID_REQUEST`; exactly-equal ACTIVE windows are superseded (possibly several) rather than rejected, while any other overlap is refused and adjacency is allowed.
- Scan-opened cases stamp `detected_at` with the logical clock and a generated `evidence_ref` of `"monitoring scan <id>"`.
- Case transitions enforce per-action role exclusivity as `ERR_UNAUTHORIZED` *before* the existence lookup; a `TERMINATED` partner's remediation hops are refused with `ERR_CASE_INVALID_TRANSITION`.
- Attribution: dedupe short-circuits **before** rate-card selection (a deduped order needs no ACTIVE policy), and the winning partner's ACTIVE check runs after dedupe. `dedup_reason` `LOW_INCREMENTALITY_PARTNER` appears only on the selected adjusted row.
- Batch generation claims qualifying entries by period predicate without filtering on the batch's network; the pre-generation sweep/tax-refresh writes persist even when `ERR_NO_ELIGIBLE_PAYOUT_LINES` is returned, and no batch row is created.
- Validation is computed as a dry-run plan and committed only after both reconciliation checks pass; holds are applied sequentially tax → fraud → minimum, honouring a prior waiver.
- Approve reserves `net_before_fees_cents`; pay writes a `SETTLEMENT` of `-net_before_fees_cents` (leaving accrued untouched) and credits `lifetime_paid_cents` with `net_cents`; void reverses reservations only if the batch had been APPROVED and does not rewrite totals.
- Unknown ledger-entry id → HTTP 404 with `ERR_LEDGER_ENTRY_NOT_FOUND` (the PRD declares no code for that read).

## Step 5: Generate Unit Tests — 2026-09-05T10:24:00.000Z

Test suite generation for task 2855 is complete.

## Output paths (both at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` — 9 files, 2208 lines:
`__init__.py` 10 · `api_client.py` 271 · `api_errors.py` 133 · `assertions.py` 267 · `constants.py` 293 · `factories.py` 400 · `fixtures.py` 477 · `test_users.py` 95 · `types.py` 262

`test_suite/` — 15 files, 9307 lines:
`conftest.py` 26 · `test_01_networks_partners_and_resource_shape.py` 492 · `test_02_application_review_lifecycle.py` 621 · `test_03_attribution_lifecycle.py` 414 · `test_04_compliance_cases_and_reinstatement.py` 841 · `test_05_payout_batch_lifecycle.py` 367 · `test_06_scoring_and_money_calculations.py` 677 · `test_07_input_validation_and_read_consistency.py` 798 · `test_08_error_catalogue_and_precedence.py` 665 · `test_09_authentication_and_role_access.py` 590 · `test_10_optimistic_concurrency_and_fraud_gates.py` 504 · `test_11_dual_variant_and_ordered_formulas.py` 779 · `test_12_nonlinear_states_and_cascades.py` 892 · `test_13_rule_precedence_and_boundary_precision.py` 702 · `test_14_cross_entity_windows_and_invariants.py` 939

`ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no stray test dirs. `implementation/` was never read or written by me or any writer.

## Coverage

- **Queue B (Corner): 54/54 non-stub instances covered**, all 12 `excluded_because:` stubs correctly untagged. Sections: entities 11, state_machines 14, calculations 6, validations 6, endpoints 3, errors 4, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1.
- **Queue A (Difficulty): 19/19 instances covered, every one with >=2 tests** (2-3 each, 51 tests total across the 9 rule_ids).
- **137 test functions → 162 collected pytest node ids.** `pytest --collect-only` clean, `py_compile` clean on every file.

## Machine verification I ran

- Tag audit: every test has exactly one `Design:` line, it is the last docstring line, and every tag names a real non-stub `name:` in the right file/section — 0 errors, 0 untagged, 0 dual-tagged, 0 stub tags.
- Citation audit: all **276** `PRD §x.y: "…"` quotes survive a whitespace-normalised literal match against `PRD.md`. Two elided (`...`) inline quotes were found and expanded to full sentences (test_04 §3.7 severity table, test_14 §3.9 which-lines-contribute).
- 0 hits for `scaffold`/`xfail`/`skip`/`skipif`, `unittest`, `mock`, `time.sleep`; no duplicate test or class names in any file; no date-only literals, no sub-3-digit instants, no string-typed `_cents`/`_bps` values.

## No instance was skipped

All 73 non-stub instances passed both limbs of the PRD-first filter. Sub-asserts dropped (PRD silence unless noted):

- "no Network row is created" (no `GET /networks` route in §4) — 2 places.
- `dedup_reason` on non-selected/raw audit rows where §3.5 doesn't pin it (kept where it does).
- Payout-line partner-reference field — §3.9/§4 never name it; lines identified by batch + `net_cents` instead (3 places).
- Unpinned initial values: `reconciliation_status` on a DRAFT batch, `payment_reference` pre-payment, `conditional_requirements` / `decided_by_user_id` pre-decision, `payable_commission_cents` after FULL_CANCELLATION.
- `open_violation_case_count` after a *hand-filed* case (§3.7 pins the rise only for scan-opened cases); `fraud_risk_score_trailing` on scan-opened cases (their `detected_at` is unpinned).
- `winning_click_id`, `lifetime_earned_cents`, `activated_at`, line-level `tax_document_status` — fields that don't exist in the PRD.
- The `UNKNOWN_USER_PROGRAM_ADMIN` case: the PRD gives no way to tell a "known" opaque operator id from an unknown one, so it is untestable (the omitted-header half is tested).

## Yaml-vs-PRD divergences resolved in the PRD's favour (worth knowing before Step 7)

Fresh-partner `incrementality_score_bps` per the §3.5 table (4500 CONTENT/INFLUENCER, 3000 COUPON), never 0 · `AFFILIATE_ATTRIBUTED` not `ATTRIBUTED` · `FRAUD_SCORE_BREACH` not `FRAUD_THRESHOLD` · `suspension_cause` `NONE` not null · `site_quality_score` not `site_quality_composite_score` · `accrued_balance_cents` not `pending_balance_cents` · scan `engine` must be one of the four §3.7 members (yaml used `PAID_SEARCH_SERP`/`GOOGLE`) · `SUBMIT_REMEDIATION` must come from the AffiliatePartner and the `ESCALATED → UPHELD` verify from a ProgramAdmin · the tax hold applies at **validation** time only, not at generation · a scan gap of exactly 24 h is still a collision (§3.7 closed cooldown), against the yaml's 201 · the "no rate card + no clicks" scenario was rebuilt with one eligible click, because §3.5 makes an empty click set a 200.

**One genuine PRD gap:** §3.7 never states the literal enum members for the case-transition `action` or for `verify_outcome` — it only says "a verification whose outcome is cleared/failed/upheld". The suite sends `REQUEST_REMEDIATION`/`SUBMIT_REMEDIATION`/`VERIFY`/`ESCALATE` and `CLEARED`/`FAILED`/`UPHELD` (from `test_helpers/constants.py`). If the implementation guessed different spellings, every case-lifecycle test will fail on a 400 rather than on behaviour — a good candidate for a §3.7 clarification at PRD finalization.

## Step 7: Run Tests and Iterate — 2026-09-05T10:44:00.000Z

All 162 tests pass in all 8 rounds.

## Summary

**Iterations run:** 2 sweeps (baseline + verification after one fix).

**Tests deleted:** none. The baseline sweep was already at 161/162 with a single, perfectly deterministic failure (identical in all 8 rounds), so there was no flakiness signal and no PRD-silence candidate to adjudicate.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/calc.py` — added `"UPHELD"` to `OPEN_CASE_STATES` (the set `services.recompute_fraud` uses to derive a partner's `open_violation_case_count`). The implementation had been treating `UPHELD` as a closed case, dropping the counter to 0 when a case was upheld.

**Diagnosis of the one failure** (`test_04_compliance_cases_and_reinstatement.py::test_two_failed_verifications_return_the_case_to_open_then_escalation_upholds_it`, `expected open_violation_case_count == 1, got 0`):

The test was judged faithful under STEP 1/2 and the fix therefore landed in the implementation:
- PRD §3.7 moves that counter in exactly two places — it "rises by the number of cases opened", and a verification "whose outcome is cleared … lowers the partner's `open_violation_case_count` by one". No clause lowers it on the upheld branch, so the implementation's decrement-on-`UPHELD` was an unstated side effect (a cardinal-rule violation in the other direction).
- Corroborating: PRD's own live-case set for the point-in-time fraud score is `OPEN`, `REMEDIATION_REQUESTED`, `REMEDIATION_SUBMITTED`, `ESCALATED` or `UPHELD`, and "a `VERIFIED_CLEARED` case contributes exactly zero" — so in this PRD's semantics `VERIFIED_CLEARED` is the resolved terminal and `UPHELD` is not. The corrected set is now identical to `POINT_IN_TIME_STATES`, which is exactly what PRD's two stated mutation rules derive.
- Blast-radius check before editing: `OPEN_CASE_STATES` has one consumer (`services.py:79`), and `test_04:150` is the only test in the suite that reads the counter with an `UPHELD` case on file — confirmed by the clean re-sweep.

**Final sweep evidence:** results.1 through results.8 each `162/162` passed, `failed 0`, `errors 0`.

Hygiene: `worklog.md` untouched by the subagent; no stray files created; storage remains in-memory only (no sqlite/JSON-dump/`/tmp` persistence in `implementation/`).

**Orchestrator verification:** independently re-read all 8 `results.$i.json` (all present, ~57 KB each, mtime 10:40) and confirmed `passed=162 total=162 failed=0 errors=0` in every round — the clean sweep is real, not a subagent claim without artifacts.

**Step 8 gating:** Step 7 applied 1 `implementation/` fix, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-05T10:53:00.000Z

Done. `PRD_FINALIZED.md` written with a single-clause patch.

## Line counts
- `PRD.md`: 469 lines — `PRD_FINALIZED.md`: 469 lines — 0.0% line delta (1 line revised in place, +366 chars; 1/469 = 0.21% of lines touched).

## Changes
- **§3.7 (Compliance / case remediation lifecycle, PRD line 314)** — *revise* — the `UPHELD` sentence now states that upholding does **not** lower `open_violation_case_count`, and pins the counter's meaning as "every one of that partner's cases that has not reached `VERIFIED_CLEARED`", parallel to the point-in-time weighting — `implementation/calc.py:65-66` (`OPEN_CASE_STATES`), consumed at `implementation/services.py:78-79`.

## Per-edit pre-edit search log

**Edit 1 — subject: `open_violation_case_count` (its derivation and every mutation/read of it), plus the `UPHELD` case state.**

(b) Paths enumerated (grepped `open_violation_case_count`, `recompute_fraud`, `cases_of`, `OPEN_CASE_STATES`, `UPHELD`, `db.cases`, `CASE_STATES` across all of `implementation/`, then read each hit):
- `calc.py:59-68` — `OPEN_CASE_STATES` now identical to `POINT_IN_TIME_STATES`; complement of `common.py:429-430 CASE_STATES` is exactly `{VERIFIED_CLEARED}`, so "not reached `VERIFIED_CLEARED`" is an exact restatement of the tuple, not a paraphrase.
- `services.py:69-82 recompute_fraud` — the counter is a **full recount**, never an increment/decrement, so no ordering or per-branch arithmetic is implied.
- All three `recompute_fraud` callsites: `routes_e.py:96` (scan, only when `opened > 0`), `routes_e.py:119` (manual filing), `routes_e.py:218` (only when `action == "VERIFY"`). Checked the three non-VERIFY transitions (`REQUEST_REMEDIATION`, `SUBMIT_REMEDIATION`, `ESCALATE`, `routes_e.py:180-200`): they do not recompute, but all their target states are inside the counted set, so the stated invariant still holds at every observable point. Wording deliberately says nothing about *which* transitions recompute, leaving PRD's existing "every case transition" clause untouched (any divergence there is outside this diff and belongs to Step 9).
- Other writers/readers of the field: `routes_a.py:96` (registration initialises 0 — consistent, no cases exist), `routes_a.py:147` (reinstatement gate `!= 0` → an `UPHELD` case permanently blocks reinstatement, which is what the impl does and what PRD lines 167/324 already require), `serializers.py:22` (exposure only).
- Parallel `UPHELD` consumers that could be mis-described: `routes_b.py:126-129` (an `UPHELD` case blocks application decisions), `routes_e.py:153`, `:172`, `:175`, `:201-205` (role gate, SoD skip, terminal guard, transition). None concern the counter; the edit makes no claim about them.
- Confirmed no case-deletion or case-state-rewriting path exists (`db.cases` is only inserted at `routes_e.py:47` and read elsewhere), so the "not reached `VERIFIED_CLEARED`" characterisation cannot be falsified by removal.

(c) Wording adjustments made for consistency: phrased the counter as a standing count over the partner's cases rather than as "the upheld branch leaves the counter unchanged", so it also correctly covers the non-recomputing transitions and the scan/manual-filing increment path; avoided the word "terminal" as a criterion (the impl treats both `VERIFIED_CLEARED` and `UPHELD` as terminal at `routes_e.py:175`, so a "terminal cases leave the count" phrasing would have been a new mismatch); and made no statement about recomputation triggers, reinstatement, or application decisions so that PRD's existing prose on those remains authoritative.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (314), and `cmp` confirms the files are not byte-identical. A one-sentence Step 8 patch is the expected outcome given Step 7's single implementation fix.

## Step 9: Complete PRD — 2026-09-05T11:30:00.000Z

**Orchestrator decision:** a single-agent full scan of a 3069-line implementation reliably under-covers (and past runs of this pipeline have produced a byte-identical PRD_COMPLETED.md, proving the scan never ran). Step 9 was therefore executed as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** — pass 1 did the `cp`, passes 2 and 3 were explicitly forbidden from copying and edited in place. Each pass received the prior passes' out-of-partition observations as a handoff list.

Partitions: **pass 1** = `common.py` + `serializers.py` + `calc.py` + `app.py`; **pass 2** = `services.py` + `routes_a.py` + `routes_b.py` + `routes_c.py`; **pass 3** = `routes_d.py` + `routes_e.py` + `routes_f.py` (plus a final cross-pass consistency read).

### Totals

| file | lines | chars |
|---|---|---|
| `PRD.md` | 469 | 105,441 |
| `PRD_FINALIZED.md` (Step 9 source) | 469 | 105,715 |
| `PRD_COMPLETED.md` after pass 1 | 473 | 113,763 |
| `PRD_COMPLETED.md` after pass 2 | 473 | 122,238 |
| `PRD_COMPLETED.md` final | 473 | 134,327 |

Net over the source: **+4 lines / +28,612 chars**, 60 diff hunks. **70 prose changes total: 48 ambiguity-pins, 22 mismatch-revisions.** No new sections were added in any pass (all edits are in-paragraph inserts/revisions).

### Pass 1 (common.py, serializers.py, calc.py, app.py) — 17 pins, 3 mismatches

- §2.1 ¶1 — revise — mismatch — no user registry exists; authentication is only a non-blank whitespace-trimmed `X-User-ID` — `common.py:358-373`
- §2.1 ¶3 — insert — ambiguity — omitted/blank `X-User-Role` reads as `Anonymous`; `Anonymous` + a user id yields 403, not 401 — `common.py:361-370`
- §2.10 rule 1 — revise — mismatch — "known user" corrected to presence/non-blankness — `common.py:367`
- §2.2 `api_request_id` — revise — ambiguity — `req_` + 20 chars from `[A-Z0-9]` — `common.py:263-267`
- §2.2 `data` — insert — ambiguity — exactly §3's fields + §2.4 system fields, all keys always present (`null` when unset); the five §3.2 screening measurements are inputs only, never echoed; insertion sequence never exposed — `serializers.py:94-100,25-31`
- §2.2 error format — insert — ambiguity — framework failures use the same envelope with `ERR_INVALID_REQUEST` but the framework status (404/405/400/500); trailing slash is not a distinct path — `app.py:25,34-51`
- §2.3 ¶1 — insert — ambiguity — integer grammar for `limit`/`offset`; `?limit=` treated as omitted; over-large offset returns an empty page — `common.py:312-329`
- §2.3 ¶2 — insert — ambiguity — `created_at` ties broken by unexposed insertion sequence — `common.py:254-256`
- §2.3 — insert — ambiguity — filters are exact-equality, applied pre-paging; undeclared/empty filters ignored; never enum-validated (no-match → empty page, not 400) — `common.py:595-600`
- §2.4 ¶1 — insert — ambiguity — id is a random v4 UUID in canonical lower-case 36-char form — `common.py:221`
- §2.4 ¶2 — revise — mismatch — `version` counts **requests**, not writes — `common.py:219-251`
- §2.6 — revise — mismatch — "Two stored quantities" → "Three"; the one-decimal scores are JSON numbers, never strings — `common.py:104-107`
- §2.8 — insert — ambiguity — SoD is vacuous when the paired earlier actor is null; it binds only the cleared/failed verifications — `common.py:384-387`, `routes_e.py:173`
- §2.10 rule 12 — insert — ambiguity — ledger-entry existence answers `ERR_LEDGER_ENTRY_NOT_FOUND` (404) at the same rank — `routes_f.py:26-30`
- §2.10 rule 14 — insert — ambiguity — JSON `null` ≡ omitted; strict types; the full accepted ISO-8601 instant grammar and 3-digit UTC re-rendering; absent/empty body = `{}`; non-object body = 400 — `common.py:57-88,451-592`
- §2.11 — insert — ambiguity — the cascade bump is once per request however many hops write the row — `common.py:231-251`
- §3.7 case transition — insert — ambiguity — literal `action` values (`REQUEST_REMEDIATION`/`SUBMIT_REMEDIATION`/`VERIFY`/`ESCALATE`) and `verify_outcome` values (`CLEARED`/`FAILED`/`UPHELD`) — `common.py:431-432` **(this closes the PRD gap Step 5's generator flagged)**
- §3.7 trailing fraud — insert — ambiguity — the 0.20 floor is the decay's only bound; a future `detected_at` gives a decay above 1.00, still capped at 100 — `calc.py:168-185`
- §3.7 status-change — insert — ambiguity — `reason` is required non-empty but persisted nowhere — `routes_a.py:137`
- §3.9 batch creation — insert — ambiguity — batch opens `PENDING` with seven null fields — `common.py:443`, `routes_f.py:81-89`
- §5 — insert — ambiguity — added `ERR_LEDGER_ENTRY_NOT_FOUND | 404`, the only impl-raised id absent from the table; the other 51 pairs already matched `common.py:122-174` exactly

Verified clean, no edit needed: `ERROR_STATUS` vs §5, all 40 enums, every `calc.py` constant and formula, `respond`/`respond_list`/`has_more`, immutable-vs-mutable serializer tails.

### Pass 2 (services.py, routes_a/b/c.py) — 14 pins, 7 mismatches

- §2.5 — insert — ambiguity — body-borne references resolve existence on the **raw** value: wrong JSON type → that reference's own 404, omitted/null → rule 14 — `services.py:281-291`, `routes_a.py:62-67`
- §2.10 rule 14 — insert — ambiguity — rule 14 carries every uncoded constraint: uniqueness of network `name`, `contact_email`, `policy_code`, per-partner `sub_id` (across all states); only `order_ref` (41) and one-live-application (40) have dedicated codes; `sub_id` is the one departure, checked after rule 17 — `routes_a.py:32-40,75-77`, `routes_c.py:31-33,120-126`, `routes_b.py:217-219`
- §2.10 rule 17 — insert — ambiguity — status-change's source-state gate also answers `ERR_AFFILIATE_SUSPENDED`; reinstatement's parent-`ACTIVE` gate uses the same code but is evaluated **last**, after rules 35/36 — `routes_a.py:138-166`
- §2.10 rule 27 — revise — ambiguity — the status half also reaches screening; the upheld-case half only fires when deciding — `routes_b.py:87-89,122-129`
- §2.10 rule 48 — insert — ambiguity — also answers verification out of turn: non-`PENDING` first, then `expires_on` at/before the clock — `routes_b.py:237-244`
- §3.1 — insert — ambiguity — the prospective parent's own `status` is never examined at registration — `routes_a.py:82-84`
- §3.2 — insert — ambiguity — `screened_by_user_id`/`decided_by_user_id`/`decision_notes` start null while `conditional_requirements` starts an **empty array** — `routes_b.py:44-48`
- §3.2 — revise — mismatch — activation leaves `suspension_cause` as it stands rather than writing `NONE` — `routes_b.py:254-257`
- §3.2 — revise — mismatch — `conditional_requirements` must be a non-empty array **of non-empty strings** — `routes_b.py:112-113`
- §3.2 — revise — mismatch — resubmission's partner gate is rule 17 good standing, not a fresh `PENDING_APPLICATION` read; a `ProgramAdmin` may resubmit and escapes the ownership comparison — `routes_b.py:173-183`
- §3.3 — insert — ambiguity — only a `DRAFT` card may be activated, else rule 14's 400, taken **before** the version guard — `routes_c.py:69-73`
- §3.3 — insert — ambiguity — every exactly-equal incumbent is superseded (possibly several); one partial overlap refuses the activation — `routes_c.py:80-101`
- §3.4 — revise — mismatch — `household_id` and `referrer_domain` are optional, defaulting to null — `routes_c.py:162-165`
- §3.4 — insert — ambiguity — the candidate refresh recomputes from full step-one eligibility over every click on file, tests the arriving link's own window, and fires even when the new click is ineligible, so the count is often rewritten to the same value while `version` still moves — `routes_c.py:186-196`
- §3.4 — insert — ambiguity — a partner's own link list accepts an optional `status` filter — `routes_a.py:195`
- §3.4 — insert — ambiguity — `tracking_link_count` only ever rises; `sub_id` uniqueness spans all that partner's links whatever their status — `routes_c.py:123-134`
- §3.5 step two — insert — ambiguity — on a full tie of both instants the **first-written** candidate wins (stable descending sort over insertion order) — `services.py:405-411`
- §3.7 — insert — ambiguity — the per-target role split is decided at rule 2's position on the **raw** `target_status`, before the partner lookup and before enum validation, so a `ProgramAdmin` suspending an unknown partner gets `ERR_UNAUTHORIZED` — `routes_a.py:125-136`
- §3.7 — insert — ambiguity — termination is **not** a fan-out: sub-affiliates keep their status, `INCLUDED` lines untouched, no batch total recomputed, existing `suspension_cause` stays, second termination refused under rule 17 — `services.py:133-138`
- §3.8 — insert — ambiguity — filing never examines partner status and performs no expiry arithmetic — `routes_b.py:207-228`
- §3.8 — insert/revise — ambiguity — verification records `verified_by_user_id` on either outcome; "most recent" = greatest `created_at` with insertion-order tie-break, governing this mirror, the expiry mirror and §3.9's `withholding_bps`; document `version` moves either way, the partner's only when the mirror moved — `routes_b.py:230-251`, `services.py:47-51,178-186,196-201`
- §4 — revise — mismatch — `GET /affiliates` incrementality-tier filter; tracking-link creation "neither suspended nor terminated"; link list "filterable by status"

### Pass 3 (routes_d/e/f.py) — 17 pins, 12 mismatches

- §2.9 — revise — ambiguity — clock op takes a required well-formed `to_iso8601` and answers a single `current_utc` in §2.4 form — `routes_f.py:345-351`
- §2.10 rule 17 — insert — mismatch — attribution's winning-partner-`ACTIVE` gate answers `ERR_AFFILIATE_SUSPENDED` out of numeric turn (after rules 20/30 and after dedup, above rule 47) — `routes_d.py:138-141`
- §2.10 rule 48 — revise — mismatch — only the *most recent* tax doc is consulted; an older `VALID` doc behind a newer PENDING/REJECTED/EXPIRED does not satisfy it — `routes_f.py:324-331`, `services.py:47-51`
- §3.5 order fields — revise — ambiguity — `device_id`/`household_id`/`coupon_code_used` are 1–64 chars — `routes_d.py:31-35`
- §3.5 step two — revise — ambiguity — the empty-candidate pair also carries null `winning_click_occurred_at`, `device_match_mode` `NONE`, `selected` on the raw variant; no partner row read or touched — `routes_d.py:108-115`
- §3.5 step three — insert — ambiguity — the run *ends* here in success: `commission_policy_id` stays null, partner standing and card availability never examined — `routes_d.py:121-136`
- §3.5 step five — insert — ambiguity — on a credited order the unselected row carries `dedup_reason` `NONE`; `LOW_INCREMENTALITY_PARTNER` only on a selected adjusted row — `routes_d.py:158-181`
- §3.5 preconditions — revise — mismatch — names `ERR_AFFILIATE_SUSPENDED` (409) for a non-ACTIVE winning partner — `routes_d.py:139-141`
- §3.5 incrementality — revise — mismatch — four recompute moments (registration, attribution run, an adjustment *that detaches*, activation); a clawback-only adjustment recomputes nothing — `routes_d.py:191,233`, `routes_a.py:99`, `routes_b.py:256`
- §3.6 ledger entry — revise — mismatch — the null-order entry is the `SETTLEMENT`, not "batch-level adjustments" — `services.py:418-430`, `routes_f.py:247-252`
- §3.6 ledger reads — revise — ambiguity — `SETTLEMENT` is born stamped; partner list narrowed before filters (empty page, not `ERR_NOT_RESOURCE_OWNER`); single-entry read closed to partners — `routes_f.py:23-42`
- §3.6 adjustments — revise — mismatch — a deduped order clears both refusals; ceiling checked after them; full types drive accumulated `returned_amount_cents` to the order total; `occurred_at` required but recorded nowhere — `routes_d.py:201-216`
- §3.6 FULL_CANCELLATION — revise — mismatch — dropped the "must reach full `order_total_cents`" requirement — `routes_d.py:213-215`
- §3.6 unvalidated window — insert — ambiguity — a `PARTIAL_RETURN` reverses in full; an adjustment on a deduped order unwinds nothing — `routes_d.py:219-241`
- §3.6 entry landing — insert — ambiguity — entry type turns on `PAID` alone; APPROVED-batch and voided-batch accruals raise an *unstamped* `CLAWBACK` — `routes_d.py:248-262`
- §3.7 scan fields — revise — ambiguity — window bounds never compared; an inverted window is stored as supplied — `routes_e.py:64-65`
- §3.7 auto cases — revise — mismatch — server-generated `evidence_ref`; `detected_at` from the clock at scan time; a quiet scan opens nothing, recomputes nothing, leaves `version` untouched — `routes_e.py:88-96`
- §3.7 case reads — insert — ambiguity — partners reach the single read but not the list, with **no** ownership narrowing; rule 13 binds only the transition — `routes_e.py:122-136`
- §3.7 case lifecycle — insert — ambiguity — action→role split decided at rule 2 on the raw `action`/`verify_outcome`; `ERR_CASE_INVALID_TRANSITION` for the TERMINATED refusal, which binds only the two remediation actions — `routes_e.py:140-171`
- §3.7 fraud triggers — revise — mismatch — exactly three triggers; request/submit/escalate recompute nothing — `routes_e.py:96,119,217-218`
- §3.8 most-recent enumeration — revise — ambiguity — added the hold-release valid-document test — `routes_f.py:324`
- §3.8 expiry refresh — revise — mismatch — at validation the plan is computed first but *persisted last*; a failed reconciliation leaves docs and mirrors untouched — `routes_f.py:139-151,174`
- §3.9 batch creation — insert — ambiguity — period bounds never compared; batch channels closed to partners, filterable by `network_id`/`state`/`reconciliation_status` — `routes_f.py:56-57,111-123`
- §3.9 claim rule — revise — ambiguity — only entries that *name an order* are claimed — `routes_f.py:63-76`
- §3.9 line holds — insert — ambiguity — hold precedence tax → standing → minimum; money re-derived for every non-VOIDED line but the hold decision only for `INCLUDED`; an unchanged line is not touched; read/list asymmetry — `routes_f.py:143-159,177-182,293-307`
- §3.9 reconciliation — insert — ambiguity — either refusal is total: no line value, line state, batch field or tax doc written — `routes_f.py:166-174`
- §3.9 release-hold — revise — mismatch — most-recent doc must be `VALID` with `expires_on` strictly after the clock; release applies no further hold test — `routes_f.py:324-338`
- §3.9 payment — revise — ambiguity — `payment_reference` is 1–120 chars — `routes_f.py:236`
- §4 payout-batch list — revise — mismatch — filterable by network, state **and reconciliation status** — `routes_f.py:116-123`

### Pass 3's cross-pass consistency read

Re-read §2.9, §2.10 rules 17/48, §3.5, §3.6, §3.7, §3.8, §3.9 and every §4 row for conversions, scans, cases, ledger, batches, lines and the clock. Two self-contradictions found, both introduced by pass 3 itself, both fixed in place:
- §3.5 step five claimed the unselected audit row "always" carries `dedup_reason` `NONE`, contradicting step two (`NO_ELIGIBLE_CLICK` on both rows) and step three (`OTHER_CHANNEL_LATER_TOUCH` on both). Rescoped to credited orders with the two early exits named explicitly.
- §3.9 "Validation re-evaluates only the lines still sitting at `INCLUDED`" read as if held lines' money were frozen, contradicting "recomputes every surviving line". Now: money re-derived for every non-`VOIDED` line, hold decision re-evaluated only for `INCLUDED` ones.

No contradiction was found in another pass's partition. One cosmetic non-issue left alone: the §4 clock row renders the default as `2026-08-01T00:00:00Z` while §2.9 uses `2026-08-01T00:00:00.000Z` — the same instant, pre-existing wording, not a behavioural ambiguity.

### Orchestrator verification

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 60 diff hunks) — the scan genuinely ran.
- Structure intact: all five `##` sections present, §4 still exactly 50 method rows, §5 now 52 `ERR_` rows (51 original + `ERR_LEDGER_ENTRY_NOT_FOUND`), file ends at the final table row, not mid-sentence.
- No stray `test_helpers/` or `test_suite/` under `workspace/`, and no stray `worklog.md` there either.
- All `implementation/` and `test_suite/` mtimes predate the 10:40 results files, so the verified 8×162/162 green sweep is valid for the artifacts as they now stand; Step 9 changed documentation only.

**PIPELINE COMPLETE.**
