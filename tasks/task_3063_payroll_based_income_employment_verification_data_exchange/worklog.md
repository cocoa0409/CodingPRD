# Worklog — task_3063_payroll_based_income_employment_verification_data_exchange

Scenario: Payroll-Based Income and Employment Verification Data Exchange (Equifax Work Number) — employer payroll contributor onboarding with record layout mapping and refresh cadence, permissible-purpose verification for each requesting party with consumer authorization capture, instant verification response construction (employment status, tenure, income history), social service and mortgage verifier product tiers with differing data depth, consumer disclosure of their own data file and dispute of inaccurate employment records, employer data freeze and opt-out obligations, contributor compensation and pricing by transaction, data currency monitoring when an employer's feed stalls.

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3063_payroll_based_income_employment_verification_data_exchange/` was pre-allocated by the caller (with an empty `workspace/` inside). No index computation performed — used the supplied path exactly as instructed. Created `worklog.md`.

## Step 2: Generate Scaffold — 2026-09-30T00:00:00.000Z

All three files are written and `scaffold_lint.py` reports clean. Verdict block:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../task_3063_payroll_based_income_employment_verification_data_exchange/SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    74
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     30
  Calls scanned (§1.8+§1.9):  530

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written**

| File | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 2019 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1393 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 1733 |

**SCAFFOLD.yaml counts** — 15 entities, 8 state machines (43 transitions), 13 calculations, 24 validations, 74 endpoints, 31 errors, 4 roles, 2 concurrency rules, plus a `domain_constants` block.

**Difficulty design** — 9 rule blocks × 2 instances = **18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant), all with literal pre-computed asserts (e.g. per-record rounding gives `gross_amount_cents == 9500025` vs `9500026` for sum-then-round; fee boundary prices at `1665` not `1850`).

**Corner design** — **31 instances** across all 8 claim-extraction sections (30 active + 1 `excluded_because` stub).

**Difficulty shaping** — non-linear machines on 5 entities (parallel Employer dimensions, cyclic RecordDispute/VerificationRequest/CompensationAccrual, branching with revert); two cascades rooted in different triggers (freeze → records → request → attestation, and dispute escalation → feed delay → record staleness); half-open vs buffer interval semantics split across two resources; compensating invariants on two conserved quantities (counted records, settled cents).

**Orchestrator note:** the first Step 2 attempt (agent `a8bf6195bd5ba00a8`'s predecessor) failed with a 32000-output-token overflow before writing anything; the retry succeeded after the prompt was amended to force chunked Write/Edit calls with terse inter-call text. Verified independently: `scaffold_difficulty_design` and `scaffold_corner_design` are in their own files and absent from `SCAFFOLD.yaml`.

## Step 3: Copy Shared Files — 2026-09-30T00:00:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes, unchanged).

## Step 4: Generate PRD — 2026-09-30T00:00:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **365 lines**, 84,116 bytes.

**Structure emitted:** §1 Introduction. §2 Global Specifications: 2.1 Identity, Roles and Ownership Boundaries; 2.2 API Response Structure (verbatim, byte-identical to the skill's `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 Canonical Resource Properties, Precision and Rounding; 2.5 Consumer Authorization as the Permission Root; 2.6 Verification Product Tiers and Depth Constraints; 2.7 The Employer Data Freeze and Its Cascade; 2.8 Lifecycle Enumerations in Play; 2.9 Stale-View Rejection on Contributor and Worker Writes; 2.10 The Precedence Order for Verification Admission; 2.11 Interval Guards, Window Separation and Temporal Bounds; 2.12 The Logical Clock; 2.13 Reconsent Intervals and the Consent Loop; 2.14 Nested Path Addressing. §3 Business Logic & Workflows: 3.1 Contributor Onboarding, Layout Mapping and the Feed Calendar; 3.2 Authorization Capture, Opt-Out and the Worker's Control of Their File; 3.3 Payroll Batch Ingestion and the Currency Sweep; 3.4 Employment Records and Annualized Income; 3.5 Permissible-Purpose Verification from Submission to Response; 3.6 Consumer Disclosure and the Dispute Cycle; 3.7 Contributor Compensation, Pricing and Settlement; 3.8 Feed Currency, Score Escalation and Verifier Risk Contagion; 3.9 Compensating Invariants and Conserved Counters. §4 Endpoint Definitions (74 rows, 4 columns). §5 Error Code Catalogue (31 rows, 2 columns).

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 122 required, 122 present, 0 missing
- endpoints[].request_body/input: 66 required, 66 present, 0 missing
- endpoints[].query_params/path_params: included in the 66; 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 24 checked, 24 expressed, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 48 checked, 48 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed (3 variants included), 0 missing
- validations[] conditions: 24 checked, matchable to error_id, 0 missing
- endpoints[].side_effects: 74 checked, 74 expressed, 0 missing
- entities[].fields[] structured content: 122 checked, reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 229
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Confirmation: I did not read, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, and did not access any sibling task directory.

## Step 5: Generate Unit Tests — 2026-09-30T00:00:00.000Z

All checks pass. Final state summary below.

## Summary

Generated complete test infrastructure for `task_3063_payroll_based_income_employment_verification_data_exchange`.

**Files written**

`test_helpers/` (1,824 lines): `__init__.py` (27), `api_client.py` (246, 70 endpoint methods), `api_errors.py` (73), `assertions.py` (167), `constants.py` (130), `factories.py` (169), `fixtures.py` (611, 5 fixture tiers), `test_users.py` (29, with `make_employer_headers`/`make_worker_headers`/`make_verifier_headers` builders), `types.py` (374).

`test_suite/` (2,663 lines): `conftest.py` (29) plus 12 test modules — `test_01_annualized_income` … `test_12_remaining_corners`.

**Tests emitted: 96** — one or more per non-stub instance.

**Coverage:** 18/18 difficulty instances (each with ≥2 tagged tests), 30/30 non-stub corner instances.

**Instances skipped: 1.** `Corner/consistency_model/stale_response_row_after_reversal_is_immediately_absent` — an `excluded_because:` stub whose `difficulty_instance` cross-reference resolves to `worker_opt_out_releases_exactly_the_counted_verification_records`; per the skill, stubs are not translated. No instance was dropped for the two-condition filter.

**Design-tag coverage confirmed:** every one of the 96 tests' docstrings ends with exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` line; no untagged, dual-tagged, or non-resolving tags; no tag points to a non-existent instance.

**Verification performed:** all files compile; pytest collects 96 tests; a script recomputed every docstring's ≥8-word citation against a whitespace-normalized `PRD.md` — 0 verbatim failures; no `skip`/`xfail` markers remain; no scaffold/table references leak into generated code.

Two design notes: (1) fixture pay periods default to `2026-08-31` so the feed reads `CURRENT` at the default logical clock; (2) response materialization always passes through `validate-currency` first, matching PRD §3.5's admitted from-states.

## Step 6: Generate Implementation — 2026-09-30T00:00:00.000Z

Implementation complete and verified.

## Summary

**Files written** under `.../workspace/implementation/` (3464 lines total):

| File | Lines | | File | Lines |
|---|---|---|---|---|
| routes_core.py | 557 | | services_feed.py | 271 |
| routes_flow.py | 552 | | models.py | 276 |
| services_verify.py | 470 | | domain.py | 106 |
| calculations.py | 458 | | middleware.py | 81 |
| services_consent.py | 346 | | errors.py / clock.py / store.py | 76/67/55 |
| app.py | 45 | | serialize/response/start.sh/requirements | 47/48/9/1 |

**Boot confirmed**: `bash start.sh` (PORT env, `0.0.0.0`, `exec`, guarded `pip install`) starts in ~1.5 s and answers HTTP 200; state is wiped on every reboot (in-memory dicts only, `store.reset()` at import, zero seeding).

**Endpoint coverage**: all 74 scaffold endpoints present (verified programmatically against SCAFFOLD.yaml — only `<param>` name spelling differs).

**Verified behaviors** via live end-to-end tests across 5 fresh boots: annualization incl. the pinned per-record rounding and the blended-final-period variant (MONTHLY normalized 5 200 000 → 4 946 667 exactly as in PRD §3.4); tiered + blended contributor pricing (15 000 → 9¢ blended vs 8¢ marginal); fee volume-tier boundaries with projected count (proj 2 → 900, proj 5 → 1 013); feed currency bands with equality in the lower band and ACTIVE-freeze suppression; half-open authorization guard (grant admitted exactly on the expiry instant) versus the 3-day-minimum review-window guard (1-day gap rejected, 3-day admitted); stale-view OCC on both guarded writes; freeze cascade (records FROZEN + `frozen_by_employer_version`, PERMITTED/VALIDATED → DECLINED, attestations INVALIDATED, REGULATORY_HOLD irreleasable); tier downgrade floor (FULL over ~6 months → EMPLOYMENT_ONLY with 0 buckets, no pay-rate fields); `employer_match_selection` ordering; the 10-step admission precedence; dispute escalation contagion (25 → 30); and both conserved counters returning to exactly 0 after reversal/void.

I did **not** read `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

## Step 7: Run Tests and Iterate — 2026-09-30T00:00:00.000Z

All 8 concurrent rounds now pass 96/96 with zero union failures.

## Summary

**Iterations run:** 7 parallel 8-round stability sweeps. Trajectory: 53/96 → 79 → 85 → 87 → 91 → 94 → **96/96 in all 8 rounds**. No test was deleted; SETP 1a found every surviving assertion verbatim in PRD.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `get_layout`/`get_dispute`/`get_batch`/`get_review`/`get_attestation` took `(id, headers)` but the 2nd positional slot was an owner-id, so the headers dict landed in the header value (`requests.InvalidHeader`); getters now accept either form. 12 tests.
- `fixtures.py` — `setup_verification_stack`/`setup_responded_request` assigned the *response row* to `ctx["request"]`, so every later `ctx["request"]["id"]` was a response id (404 on reverse/permit); now keeps the request as `ctx["request"]` and exposes the row as `ctx["response"]`.

**Fixes applied to `test_suite/`:**
- `test_06` — `ERR_INVALID_STATE` → `ERR_ALREADY_TERMINAL` / `ERR_BATCH_LAYOUT_NOT_VERIFIED` / `ERR_FEED_NOT_MONOTONIC` (PRD §2.8, §3.3 name these); added missing `set_clock` import; read feed status inside one cadence interval; timestamp literal `Z` → `.000Z`.
- `test_07` — a variable shadow turned the request id into a response object; timestamp literal; `test_10` imports/helpers now reach an admissible response from-state and a sub-300 review.
- `test_03`, `test_09`, `test_10`, `test_11`, `test_12` — negated/reversed argument order, stale fixture clocks, settlement period ends that cover the accrual, and timestamp literals.

**Fixes applied to `workspace/implementation/`:**
- `services_verify.py` — submission is no longer gated on the §2.10 step-10 hop (PRD §3.5 gates submission only on posture/purpose/class, so a request with an unmatched or frozen employer must open, not 4xx); permitting no longer requires the escrow/match hop; `validate_currency` runs the purpose gate before the state check and only falls back when already `VALIDATED`; reversal clears `resolved_product_tier`/`rendered_field_set` and revives one attestation for its own penalty; added verifier-ownership checks.
- `services_feed.py` — a freeze also declines requests resolved by span but not yet employer-stamped; an active freeze retires the employer's layouts; released/lapsed freeze reverses it; `LAPSE` on a `REGULATORY_HOLD` raises `ERR_REGULATORY_HOLD_IRRELEASABLE`.
- `calculations.py`, `routes_core.py`, `routes_flow.py`, `domain.py` — one `FREEZE_LIVE_STATES` predicate for every guard/candidate filter, worker-scoped history depth, nearest-span employer fallback, review-decay recency fix, and rescore refresh.

**Orchestrator verification:** independently read all 8 `results.{1..8}.json` — each reports `passed=96`, `total=96`.

## Step 8: Finalize PRD — 2026-09-30T00:00:00.000Z

All edits are in place. Final report.

## PRD_FINALIZED.md produced

**Files (all absolute):**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_3063_payroll_based_income_employment_verification_data_exchange/workspace/PRD.md`
- Output: `/home/ubuntu/github/CodingPRD/tasks/task_3063_payroll_based_income_employment_verification_data_exchange/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 365 lines → PRD_FINALIZED.md 365 lines (no lines added/removed; 15 paragraphs rewritten in place, +5.4% words). *(Orchestrator check: 84,116 → 88,399 bytes, i.e. +5.1%.)*

### Changes (one bullet per edit)
- §2.7 para 1 — revise — defined "live freeze" (`REQUESTED` or `ACTIVE`) and separated the guard semantics (live = blocks admission/reconfirm/dispute-filing, removes candidates) from the cascade semantics (ACTIVE only); widened the freeze-decline set to selected-employer **or** any span of the request's worker; added layout retirement — `services_verify.py:110-113,116-121`, `calculations.py:272`, `services_feed.py:74-84`, `services_feed.py:52-62`
- §2.7 para 2 — revise — release/lapse re-declares superseded layouts `DRAFT`; `REGULATORY_HOLD` refuses lapse too; otherwise lapse needs no open dispute / no `PERMITTED` request, release has no precondition — `services_feed.py:105-151`
- §2.10 step 8 — revise — purpose binding governs permitting/validation/response only (submission compares the verifier's own purpose); the gate yields `ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE`, the three reason labels are supplied by the decline operation — `services_verify.py:68-89`
- §2.10 step 10 — revise — freeze gate reworded to "not under a live freeze"; freeze/feed/match run on validation + response, escrow only on response — `services_verify.py:217-220,291-295`
- §3.2 opt-out para — revise — reversal deletes the response row, invalidates attestations, charges the §3.8 reversal penalty (dropped the field-clearing claim, which opts-out does not do) — `services_consent.py:26-46`
- §3.5 permit para — revise — no step-10 gates; refusal leaves state and tier untouched; purpose failure is not self-recorded as a decline reason — `services_verify.py:176-194`
- §3.5 match para — revise — candidate employer must not be live-frozen; empty pool uses the most-recent span's employer for the freeze guard, so `ERR_EMPLOYER_FROZEN` can precede `ERR_NO_EMPLOYER_MATCH` — `calculations.py:262-275,278-290`, `services_verify.py:28-48,116-126`
- §3.5 depth para — revise — available history scoped to the request's worker — `calculations.py:309-327,330-335`
- §3.5 currency validation para — revise — admits `PERMITTED` **or** `VALIDATED` (terminal check first, posture/opt-out/purpose before state); re-validation skips freeze/feed/match; removed the false "all records FROZEN" claim — `services_verify.py:199-263`, `routes_flow.py:100-111`
- §3.5 response para — revise — added verifier ownership + purpose gates, "not live" freeze, escrow shortfall returns 402 without declining; documented the standalone reversal's `SIGNED`-attestation revival — `services_verify.py:278-295,406-445`, `routes_flow.py:136-143`
- §3.6 filing para — revise — adds `record_state == VERIFIED`; other non-VERIFIED → `ERR_INVALID_STATE` — `routes_flow.py:237-258`
- §3.6 correction revival — revise — trigger scoped to `current_employer_id`, which is what the impl keys on — `services_consent.py:219-232`
- §3.6 reconfirm/reopen — revise — freeze guard "not live"; the 14-day grace also governs reopening a corrected dispute — `routes_core.py:276-296`, `services_consent.py:235-249`
- §3.8 decay — revise — fallback chain is employer feed date → review `last_feed_date_in_window` → creation instant — `calculations.py:181-184`
- §3.8 escalation — revise — `VALIDATED`→`PERMITTED` with matched count reset, resolved tier left intact — `services_verify.py:448-460`
- §3.8 rescore — revise — added `CLEARED`→`ERR_ALREADY_TERMINAL`, `ESCALATED` with non-`CURRENT`/`DELAYED` feed → `ERR_INVALID_STATE` — `services_verify.py:518-541`

### Pre-edit search log (subject → paths enumerated → wording adjustment)
- **Freeze liveness** — enumerated `services_feed.freeze_employer/unfreeze_employer/_thaw_records/_retire_layouts_on_freeze/_revive_layouts_after_thaw/_decline_requests_for_freeze`, `services_verify.freeze_is_live/check_freeze/_decline_currency_failure`, `calculations.candidate_records/feed_currency_state/refresh_employer_feed_status`, `routes_core.reconfirm/retain/freeze/unfreeze`, `routes_flow.create_dispute`, all `freeze_state` greps + `FREEZE_LIVE_STATES`. Adjustment: split guard-live vs cascade-active explicitly; softened the freeze-decline set to "selected employer … or any span of its worker" to cover both accuracy branches.
- **Regulatory-hold lapse** — enumerated both `unfreeze_employer` outcome branches and `test_10` assertions. Adjustment: stated the identifier per branch (`ERR_REGULATORY_HOLD_IRRELEASABLE` vs `ERR_INVALID_STATE`) so the existing §5 status table stays true.
- **Sub-phase gating (permit/validate/response)** — enumerated every `check_*` callsite (`create_request`, `permit_request`, `validate_currency`, `build_response`, `_fallback_if_not_current`, `decline_request`). Adjustment: narrowed step-10 scope to the sites that actually call it after finding `create_request` does call `check_posture` (reverted an incorrect step-6 edit) and that no code path emits `AUTHORIZATION_EXPIRED`/`PURPOSE_MISMATCH`/`NO_AUTHORIZATION`.
- **Match/candidate & history scope** — enumerated `employer_match_selection`, `nearest_span_record`, `candidate_records`, `available_history_months`, `selected_employer_records`, all `resolution_for` callers, `routes_flow.get_request`. Adjustment: added the nearest-span fallback as an **additional** branch rather than replacing the empty-pool decline, preserving both Step 7 assertions.
- **Dispute filing/reopen/reconfirm** — enumerated `file_dispute`, `notice/respond/reopen`, `reconfirm_record`, `retain_record`, `_revive_declined_requests`, and the four route guards. Adjustment: moved the `VERIFIED` precondition out from behind the freeze clause so both error outcomes are stated.
- **Reversal/attestation/penalty** — enumerated `services_verify.reverse_request`, `_revive_one_attestation`, `_invalidate_attestations`, `services_consent.opt_out`, `calculations._attributed_events`, and `test_08`'s cleared-field assertions. Adjustment: split the two reversal variants (opt-out vs standalone) instead of asserting one behaviour for both; removed the field-clearing claim after confirming `opt_out` leaves `resolved_product_tier` intact.
- **Recency/rescore/escalation** — enumerated `feed_currency_score`, `score_review`, `escalate_review`, `rescore_review`, `fallback_requests_for_employer`, `refresh_verifiers_for_employer`. Adjustment: escrow clause re-positioned under step 10 rather than stated as a blanket "always escrow".

## Step 9: Complete PRD — 2026-09-30T00:00:00.000Z

PRD_COMPLETED.md written: 366 lines / 107,612 chars (source PRD_FINALIZED.md: 366 / 88,203; +19,409 chars, +22.0%). No new sections; all edits inline. *(Orchestrator check: on-disk PRD_COMPLETED.md is 365 lines / 107,890 bytes vs PRD_FINALIZED.md 365 / 88,399 — +22.1%.)*

Counts: 41 ambiguity-pins, 15 mismatch-revisions (56 edits).

- §2.1 — insert — ambiguity — ownership binds mutating ops only; named read exceptions — routes_core.py:69, routes_flow.py:82
- §2.3 — insert — ambiguity — list tie-break by `id` asc — middleware.py:73
- §2.4 — insert — mismatch — `ERR_COUNTER_FLOOR_VIOLATION` unreachable, counters re-derived — calculations.py:470
- §2.5 — insert — ambiguity — omitted `expected_covered_worker_version` → `ERR_STALE_VERSION`; capture bumps version — routes_core.py:467
- §2.5 — insert — ambiguity — purpose stored unvalidated — models.py:157
- §2.6 — insert — ambiguity — field-set projection keyed on depth/flag; no enum validation — domain.py:96, routes_core.py:420
- §2.7 — insert — ambiguity — filing on RELEASED/LAPSED only resets NONE — services_feed.py:41
- §2.7 — insert — ambiguity — freeze clears layout `verified_at` — services_feed.py:61
- §2.8 — revise — mismatch — uppercase is convention, not case-folded identifiers — domain.py
- §2.8 — insert — ambiguity — `FILED` is creation stamp not decision state; settlement row shape/void-zero — models.py:217, routes_flow.py:443
- §2.8 — revise — mismatch — distinct dispute states are not terminal — services_consent.py:143
- §2.10 — insert — ambiguity — step 6 skipped for worker-driven permit/decline — services_verify.py:176
- §2.10 — insert — ambiguity — permit never refuses opt-out — services_verify.py:176
- §2.10 — insert — mismatch — ceiling enforced at creation; `rejected_record_count` blocks validation — routes_core.py:169, services_feed.py:248
- §2.10 — insert — ambiguity — freeze→match→feed gate order — services_verify.py:116
- §2.11 — insert — ambiguity — reopen grace symmetric; sweep triggers; dispute error mapping — services_consent.py:275
- §2.11 — insert — mismatch — 30-day void grace inclusive — routes_flow.py:463
- §2.12 — insert — ambiguity — expire-batch lands last-feed + interval + 1; set-clock cascade — routes_core.py:547
- §2.13 — revise — mismatch — permit, not sweep, carries PENDING_AUTH forward — services_verify.py:365
- §3.1 — insert — ambiguity — no layout_version ordering check; revision must resupply fiscal month — services_feed.py:156
- §3.1 — insert — ambiguity — no `employer_type`/`payroll_frequency` membership check — models.py:18
- §3.2 — insert — ambiguity — no worker uniqueness; all CAPTURED auths revoked — services_consent.py:17
- §3.2 — revise — mismatch — opt-out clears fields, recomputes open count — services_consent.py:14
- §3.3 — revise — mismatch — validation re-derives feed status honestly — services_feed.py:283
- §3.3 — insert — ambiguity — declare/reject/attach guards — services_feed.py:214
- §3.4 — insert — ambiguity — hourly = min(reported, 40, 60); unset basis annual — calculations.py:40
- §3.4 — insert — ambiguity — final-period proration unrounded; retention guards — services_consent.py:260
- §3.5 — insert — mismatch — response builds only from VALIDATED — routes_flow.py:160
- §3.5 — insert — ambiguity — escrow-itemized fee (surcharge 350/900 × 1.00/0.90/0.75) — calculations.py:116
- §3.5 — insert — ambiguity — permit class+purpose only; missing auth id/ref errors — routes_flow.py:91
- §3.5 — insert — ambiguity — submission reference checks; decline terminal guard; auth fallback adoption — services_verify.py:68
- §3.5 — insert — ambiguity — batch-sequence tiebreak, empty-pool error — calculations.py:293
- §3.5 — insert — ambiguity — tier floor unchanged for 0-depth; read doesn't persist — routes_flow.py:72
- §3.5 — insert — ambiguity — `records_matched_count` excludes IMMUTABLE; attestation supersession; `active_employment_found` open-span — services_verify.py:309
- §3.5 — insert — ambiguity — per-month buckets from annual/12 — calculations.py:367
- §3.5 — insert — ambiguity — revalidation-fallback wording; transaction count — services_verify.py:247
- §3.6 — insert — ambiguity — `file_contents` shape; SUPERSEDED generate — services_consent.py:114
- §3.6 — insert — ambiguity — notice only from AWAITING; ACK only from NOTICE_SENT; reopen errors — services_consent.py:142
- §3.6 — insert — ambiguity — counters clamped; reconfirm errors — services_consent.py:190
- §3.7 — insert — mismatch — blended vs marginal worked figure 120000 — calculations.py:87
- §3.7 — insert — ambiguity — accrual guard, batch-derived ref, no outcome field — routes_flow.py:325
- §3.7 — insert — ambiguity — `compensation_earned_cents` recomputed — routes_flow.py:470
- §3.8 — insert — ambiguity — whole-day floors/boundaries; no-op under freeze — calculations.py:129
- §3.8 — insert — ambiguity — escalate error mapping; rescore re-derives — routes_flow.py:536
- §3.8 — insert — ambiguity — responsiveness basis; event ordering instants — calculations.py:150
- §3.9 — insert — ambiguity — recomputed on read; no-event verifier NORMAL — routes_core.py:387
- §4 — revise — mismatch — settlement ops answer 201; attestation row text — routes_flow.py:440

## Closing verification (orchestrator) — 2026-09-30T00:00:00.000Z

Post-Step-9 confirmation run (Steps 8 and 9 edited only `workspace/PRD*.md`, so no code changed): `prd-bench-local-run --isolation per-test-server` → **96/96 passed, 0 failed, 0 errors, 0 skipped** in 171.6 s. The per-round artifacts `workspace/implementation/results.{1..8}.json` from Step 7's final clean 8-round sweep remain on disk (each `passed=96`, `total=96`).

Final task tree:

```
tasks/task_3063_payroll_based_income_employment_verification_data_exchange/
├── SCAFFOLD.yaml                    (2018 lines)
├── SCAFFOLD_DIFFICULTY_DESIGN.yaml  (1393 lines)
├── SCAFFOLD_CORNER_DESIGN.yaml      (1732 lines)
├── worklog.md
├── test_helpers/                    (9 modules, ~1824 lines)
├── test_suite/                      (conftest + 12 modules, ~2663 lines; 96 tests)
└── workspace/
    ├── INSTRUCTION.md
    ├── PRD.md            (365 lines / 84,116 B)
    ├── PRD_FINALIZED.md  (365 lines / 88,399 B)
    ├── PRD_COMPLETED.md  (365 lines / 107,890 B)
    └── implementation/   (17 files, 3455 lines; start.sh + results.{1..8}.json)
```