# Worklog — task_3354_small_group_live_class_marketplace_independent_teacher

## Step 1: Create task directory — 2026-10-01T05:16:09.000Z

Task directory `./tasks/task_3354_small_group_live_class_marketplace_independent_teacher/` was pre-allocated by the entrance skill invocation and already contained an empty `workspace/`. No index computation or directory creation was performed. A prior run of this pipeline was interrupted by an API error before any artifact was written; this run restarts from Step 2. State verified at 2026-10-01T05:16:09Z: task dir empty apart from `workspace/`; no `worklog.md`, no `SCAFFOLD*.yaml`, no `test_helpers/`, no `test_suite/`, no `workspace/PRD.md`, no `workspace/implementation/`.

## Step 2: Generate Scaffold — 2026-10-01T08:53:28.000Z

Run in the FOREGROUND by the orchestrator, not by a subagent. Two subagent attempts (at 05:18Z and 05:25Z) both died immediately after reading the 774-line skill file, having written nothing; a minimal probe subagent succeeded, so the failure was specific to the large-generation task rather than the Agent tool. Per the known remedy for this failure class, the orchestrator read `skills/prd-bench-scaffold-generator/SKILL.md`, `references/claim-extraction-guide.md`, `examples/seed-tables-template.yaml`, `examples/example-marketplace-platform-v1.yaml`, `examples/example-dock-ops-v1.yaml` and `scaffold_lint.py` directly, then authored all three artifacts itself in incremental chunks (one small file per message).

Outputs (all three present and complete):
- `SCAFFOLD.yaml` — 8 entities, 8 state machines, 2 concurrency rules, 8 calculations, 39 validations, 40 endpoints, 39 errors, 5 roles, 29 pinned constants.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 9 rules × 2 instances = 18 instances, 351 structured calls.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 23 instances (18 with full `test_recipe`, 5 `excluded_because:` stubs), 235 structured calls.

Design adjudications made during generation:
- **Archetype**: `compliance_audit` primary with `workflow_orchestration` secondary; layers = cascading_side_effects, dual_variant_calculation, optimistic_concurrency, rate_threshold_triggers, selector_policy. Topology `flat`, state_machine_shape `parallel`, role_model `segregation_of_duties`.
- **Endpoint budget**: held to exactly 40 by merging the payout settlement actions (`mark-sent` / `approve` / `mark-paid` / `void`) into one `POST /outschool/teacher-payouts/{payoutId}/transition` action endpoint, and by merging report review + disposition into one `POST /outschool/class-reports/{reportId}/disposition`. This avoided the >40-endpoint overshoot that breaks the downstream implementation generator.
- **Tax-document threshold direction reversed.** The first draft read `lifetime < TAX_DOC_REQUIRED_CENTS → MISSING`, which deadlocked the object graph: `POST /teachers/{id}/activate` requires `payout_tax_document_status == ON_FILE`, and a brand-new teacher has zero lifetime earnings, so no teacher could ever be activated. Re-derived so zero earnings reads `ON_FILE` (nothing owed yet, no document required) and crossing `TAX_DOC_REQUIRED_CENTS` moves to `REQUIRED_UPDATE`. `TAX_DOC_REQUIRED_CENTS` set to 20000 (not 60000) so the crossing is reachable with a handful of sections.
- **Automatic tax-document suspension removed.** The first draft had `REQUIRED_UPDATE` suspend the teacher, which pre-empted the very cascade Rule 4 is meant to observe (the suspension's own listing/section cascade fired before the test's trigger). Tax status is now a pure gate that blocks payout `SEND`; the teacher state machine keeps only MANUAL and POLICY suspension triggers.
- **Accrual selector widened.** The first draft summed only `outcome == HELD` sections, but a section can only be cancelled *before* it starts and only reaches HELD *after* it starts — so a teacher-fault refund could never change a payout's gross and the Rule 4 cascade was inert. The accrual set now includes any section whose outcome is `NULL` or `HELD` starting inside the period, summing `CONFIRMED` enrollments; a pre-start cancellation therefore drops the section out of the sum, which is what makes the cascade fire.
- **Reviewer-conflict rule re-scoped.** The first draft forbade a reviewer from deciding an application they had previously reviewed, which blocked the ordinary review-then-approve happy path. Re-scoped to a segregation-of-duties rule: the acting reviewer's `X-User-ID` may not equal the application's `applicant_user_id`.
- **Vacuous validation removed.** `ERR_PRICE_NOT_ON_GRID` could never fire (`PRICE_GRID_CENTS: 1` makes every integer price on-grid), so the row, the constant and the error were deleted and priorities 15–30 renumbered to 14–29. Design-file `grounds:` refs were re-verified against the renumbered table afterwards (one drifted ref, `validations[priority=23]` → `[priority=22]`, corrected).
- **Ten unreferenced errors wired up.** A self-consistency audit found `ERR_MISSING_REQUIRED_FIELD`, `ERR_INVALID_ENUM_VALUE`, `ERR_SCREENING_FAILED`, `ERR_APPLICATION_NOT_APPROVED`, `ERR_TEACHER_NOT_ACTIVE`, `ERR_LISTING_NOT_PUBLISHED`, `ERR_SECTION_NOT_OPEN`, `ERR_MIN_ENROLLMENT_NOT_MET`, `ERR_PAYOUT_ALREADY_PAID` and `ERR_PAYOUT_CAP_EXCEEDED` declared but referenced by no validation or transition; ten validation rows (priorities 30–39) were appended to make every error reachable.
- **Sub-resource placeholder canonicalised.** `GET /outschool/class-listings/{listingId}/sections` tripped lint check (f) because the FK reverse-reachability check matches the parent placeholder literally as `{id}`; the path now uses `{id}` in the parent position.

Literal verification: all formula-derived `assert:` values were computed by executing the formulas as Python before being written (`refund 1666 == floor(3333*0.50)`; `fee 998 == floor(1999*0.25)+floor(1999*0.25)` vs the rejected `floor(3998*0.25) == 999`; `discounted 2550` subscription-first vs `2551` coupon-first; `liability 3400 == floor((8000-1200)*0.50)`; risk weights `65 == 40+25` and `5 == 5+0`; `refund 1600 - fee_reversed 400 == 1200`).

`scaffold_lint.py` verdict, pasted verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    40
  §1.1 entities declared:     8
  §1.8 instances scanned:     18
  §1.9 instances scanned:     23
  Calls scanned (§1.8+§1.9):  586

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-10-01T08:53:28.000Z

Copied `./INSTRUCTION.md` (53 lines) to `./tasks/task_3354_small_group_live_class_marketplace_independent_teacher/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-01T09:12:28.000Z

Subagent (general-purpose, foreground). It read `skills/prd-bench-doc-generator/SKILL.md` plus its sibling references and `SCAFFOLD.yaml`, and wrote `workspace/PRD.md` (390 lines, 75,842 bytes). It did not read either design index. Summary returned verbatim:

> PRD written and verified.
>
> **Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3354_small_group_live_class_marketplace_independent_teacher/workspace/PRD.md` — **390 lines**, 75,842 bytes.
>
> **Section headings produced**
> - `# Outschool Marketplace API — Product Requirements Document`
> - `## 1. Introduction`
> - `## 2. Global Specifications & System-Wide Principles` → `### 2.1. User and Role-Based Access Control` · `2.2. API Response Structure` (verbatim) · `2.3. Pagination` · `2.4. The Logical Clock and Period Accounting` · `2.5. Common Resource Properties` · `2.6. Validation Order and Error Precedence` · `2.7. Nested Resource Resolution` · `2.8. Optimistic Concurrency on Payout Requests` · `2.9. Monetary Precision and Rounding` · `2.10. Boundary and Comparison Conventions`
> - `## 3. Business Logic & Workflows` → `3.1. Teacher Onboarding: Application, Screening and Sample Review` · `3.2. Teacher Lifecycle and Suspension Cascades` · `3.3. Class Listings: Content Policy Review and Publishing` · `3.4. Section Scheduling, Enrollment Windows and Automatic Cancellation` · `3.5. Learners, Subscriptions and Seat Reservation` · `3.6. Confirmation, Cancellation and the Refund Tier Engine` · `3.7. Parent Reports and Teacher Risk Scoring` · `3.8. Teacher Payouts: Accrual, Fees and the Refund Clawback` · `3.9. Marketplace Operations Sweeps`
> - `## 4. Endpoint Definitions` (40 rows, 4 columns) · `## 5. Error Code Catalogue` (39 rows, 2 columns)
>
> **Hard Contract reports**
> ```
> Field coverage check:
> - entities[].fields: 100 required, 100 present, 0 missing
> - endpoints[].request_body: 44 required, 44 present, 0 missing
> - endpoints[].query_params: 12 required, 12 present, 0 missing
> Status: PASS
> ```
> ```
> Rule coverage check:
> - validations[] with priority: 39 checked, 39 expressed in prose, 0 missing
> - concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_teacher_version + ERR_STALE_VERSION 412 all named), 0 missing
> - state_machines[].transitions: 33 checked, 33 fully expressed, 0 missing
> - calculations[]: 8 checked, 8 fully expressed, 0 missing
> - validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
> - endpoints[].side_effects / applies_to: 40 checked, 40 expressed, 0 missing
> - entities[].fields[] structured content: 100 checked, 100 reconstructible from prose, 0 missing
> - sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
> Status: PASS
> ```
> ```
> Path purity check (§3 only):
> - backtick tokens scanned: 709
> - tokens starting with `/`: 0
> - bare HTTP-method tokens: 0
> - method+path combined tokens: 0
> Status: PASS
> ```
> Additional mechanical verification: §2.2 is byte-identical to `section-2.2-response-structure.md`; §4's 40 rows match SCAFFOLD method/path/roles exactly; §5's 39 rows match the error catalog exactly; all 39 error ids appear in §2/§3; all state/enum values and all pinned literals (clock default, 5-min sample, 365/3/7/24/14/2 periods, 100000/20000/200000 cents, 0.50, 168/336/24/72/168 h, 40, weights, coupon catalog, `America/Anchorage`, the five screening fixture emails) appear as concrete values.
>
> **Three scaffold conflicts I resolved (worth knowing downstream)**
> 1. `TAX_DOC_REQUIRED_CENTS` / `TAX_DOC_VALIDITY_CEILING_CENTS` are declared twice with different values (top-level pinned block: 20000 / 200000; §1.3 calc block: 60000 / 500000). I used the top-level "Pinned constants" block, which is explicitly labelled as the resolution point for every symbolic name.
> 2. `REFUND_TEACHER_LIABILITY_RATE` is referenced in the payout clawback but never given a value anywhere in the scaffold. I pinned it at **1.00** (teacher owes back the whole post-fee-reversal remainder) so the PRD is not silent.
> 3. `TeacherPayout.expected_teacher_version` is described as a "deprecated no-op" on the entity, but the concurrency rules, validation 29, validation 25's note and the endpoint input list all require and enforce it. I documented it as mandatory and enforced.
>    Also: `meet-minimum` draws credit in the endpoint's side-effects list but the Section state machine explicitly says it performs no credit movement; I used the state-machine rule (the endpoint version would make the later `confirm` credit check impossible to pass). The validation rule's `delist` scope target has no corresponding endpoint, so it is folded into the listing-ownership prose rather than invented as a route.

**Orchestrator follow-up — all five reported conflicts verified against `SCAFFOLD.yaml` and confirmed real; all five fixed at the source rather than only in the PRD.** The subagent's claim that it "pinned `REFUND_TEACHER_LIABILITY_RATE` at 1.00" was checked against the file and the value is wrong (the design-index asserts imply 0.50), so the scaffold was corrected and the PRD patched:

- `TAX_DOC_REQUIRED_CENTS` / `TAX_DOC_VALIDITY_CEILING_CENTS` — §1.3's local `constants:` block still read 60000 / 500000 after the earlier threshold re-derivation. Set to 20000 / 200000 to match the pinned block; a mechanical scan now confirms no constant name carries two different values anywhere in the file.
- `REFUND_TEACHER_LIABILITY_RATE` — added to the pinned constants at **0.50** (the value the §1.8 asserts require: `3400 == floor((8000-1200)*0.50)` and `600 == floor((1600-400)*0.50)`). The PRD's "rate of 1.00" sentence was corrected to 0.50 and its trailing clause reworded.
- `TeacherPayout.expected_teacher_version` — entity description changed from "deprecated no-op" to a required OCC token rejected with `ERR_STALE_VERSION`, matching the concurrency rules and validation 29.
- `meet-minimum` — endpoint description and `side_effects` no longer draw confirmation credit; the state-machine rule (no credit movement; credit is drawn only on `confirm`) is authoritative.
- `ERR_NOT_RESOURCE_OWNER` scope — the `POST /outschool/class-listings/{listingId}/delist` target was dropped (no such endpoint exists).
- **Dead enum value found and removed:** `Teacher.suspension_trigger` still listed `TAX_DOCUMENT`, but no transition writes it (the automatic tax-document suspension was removed earlier in Step 2 to stop it pre-empting the Rule 4 cascade). Removed from the enum; the constraint text now states that an out-of-date tax document blocks payout settlement without changing teacher status. The PRD's corresponding "the tax-document validity cascade suspends the teacher" sentence was replaced with the settlement-gate behaviour.

Post-fix verification: `scaffold_lint.py` still reports `VERDICT: clean lint` (40 endpoints, 18 §1.8 + 23 §1.9 instances, 586 calls), and a scan confirms every one of the 39 declared errors is referenced by at least one validation or transition.
## Step 5: Generate Unit Tests — 2026-10-01T09:34:00.000Z

Subagent (general-purpose, foreground). Read the unit-test-generator skill plus all four inputs (SCAFFOLD.yaml, both design indices, workspace/PRD.md) and wrote `test_helpers/` (1,509 lines across 9 files) and `test_suite/` (1,943 lines across 8 files). Summary returned verbatim:

> Test infrastructure and suite are complete and verified.
>
> ## Files created
>
> **`test_helpers/`** (1,509 lines): `__init__.py` (77), `types.py` (309), `api_client.py` (189), `api_errors.py` (92), `assertions.py` (143), `factories.py` (142), `constants.py` (90), `test_users.py` (42), `fixtures.py` (425).
>
> **`test_suite/`** (1,943 lines): `conftest.py` (40), `test_01_teacher_onboarding.py` (146), `test_02_listings_and_sections.py` (255), `test_03_learners_and_seat_capacity.py` (315), `test_04_pricing_refunds_and_seat_invariants.py` (356), `test_05_payouts_fees_and_periods.py` (415), `test_06_reports_risk_and_cascades.py` (280), `test_07_validation_precedence_and_access.py` (176).
>
> ## Coverage (machine-audited)
>
> - **Queue A: 34 tests** — 17 of 18 difficulty instances at 2 tests each.
> - **Queue B: 23 tests** — all 23 non-stub corner instances; the 5 `excluded_because:` stubs got no test and no tag.
> - 57 tests total, every docstring ends with exactly one `Design: …` line copied verbatim from the yaml `name:`; zero untagged, dual-tagged, stub-tagged, or dangling tags. All 88 quoted PRD sentences match PRD.md verbatim (whitespace-normalized). `pytest --collect-only` collects 57; pyflakes reports no undefined names; no `skip`/`xfail` anywhere.
>
> ## Skipped
>
> - **`Difficulty/cross_entity_state_dependency/payout_send_depends_on_teacher_tax_document_status`** — the assert block is self-contradictory: it requires `lifetime_net_earnings_cents == 20400` *and* `payout_tax_document_status == ON_FILE`, but PRD §3.2/§3.8 make 20400 (`> 20000`) `REQUIRED_UPDATE`, which blocks `SEND`. The distinguishing_aspect's "refund drops lifetime to 10200" hop is absent from the trigger chain and unreachable from the setup (both sections already started, so neither can be cancelled). Asserted outcome not PRD-derivable → skipped, not weakened. The corner stub citing it resolves, so no placeholder was emitted for that stub either.
>
> ## Design adjudications (non-fatal defects repaired minimally)
>
> 1. **`refund_tier_timing_vs_format`**: the recipe's 200-hours clock yields `PARTIAL_HALF`/1000 under the applied timing selector (200 ≥ the 72-hour MULTI_DAY half cutoff), contradicting its own asserted `NONE`/0. Re-derived the clock to 50 h (NONE/0; format selector would say 1000); the second test uses 400 h (FULL/2000).
> 2. **`payout_gross_accrual_vs_posted` / `fee_rounding_per_section_vs_sum`**: recipes subscribe the learner (PLUS/FAMILY) *before* enrolling, which discounts the seat price and breaks the instances' own asserted figures (2000/1500; 1999/998). Reordered to enroll → subscribe (refill) → confirm, preserving the asserted economics.
> 3. **`seat_capacity_zero_at_exactly_full_section`**: reordered to reserve both seats before confirming either, so the setup satisfies the confirm gate the same design file asserts in `confirm_enrollment_before_min_enrollment_met_rejected`.
> 4. **`listing_list_pagination_reports_total_and_has_more`**: dropped the "first element is Algebra Club" ordering claim (under a logical clock both listings can share `created_at`); asserted both pages union to the full collection instead.
> 5. **`payout_transition_on_already_paid_payout`**: asserted `validate_error_is_one_of([ERR_PAYOUT_ALREADY_PAID, ERR_INVALID_STATE])` — PRD rule 38 names the former but ladder rule 4 (state) is evaluated first.
> 6. **`create_learner_missing_display_name_rejected`**: dropped its second assertion (a `GET /outschool/learners` list endpoint does not exist on the declared surface).
> 7. **`confirm_enrollment_before_min_enrollment_met` / `publish_before_policy_approval`**: kept `ERR_INVALID_STATE` (ladder rule 4); the only competing ids are scoped elsewhere in the PRD.

**Orchestrator follow-up — every adjudication was checked against source; one of my own design recipes and one of my own scaffold prose lines were wrong, and the subagent was right about both.**

- Adjudication 1 was initially suspected of being inverted, so the tier arithmetic was re-derived from first principles and executed as code. The scaffold's §1.2 prose stated the rule in instant form as `FULL if current instant >= section.start_utc - REFUND_FULL_CUTOFF_HOURS[format]`, which is **backwards**: the correct instant form is `current instant <= start_utc - cutoff`, equivalently `hours_remaining >= cutoff` (cancelling further in advance is never worse). The PRD had already used the correct hours-remaining formulation, so the PRD and the subagent's tests agreed and only the scaffold prose was wrong. Both §1.2 occurrences were rewritten to state the rule in hours-remaining form with the instant form as a secondary equivalence. My own earlier "fix" of the test (reverting it to a 200-hour clock asserting NONE) was itself wrong and was reverted; the subagent's 50 h → NONE and 400 h → FULL values are correct.
- Adjudication 2 was confirmed correct: `reserve_seat` before `subscribe_learner` is required, because subscribing first applies the plan discount to the seat price and breaks the instance's own asserted economics. The generated tests now enrol first (asserting `discounted_price_cents == 2000` / `1999`), then subscribe to refill credit, then confirm.
- Adjudication 5 and 7 (error-precedence relaxations) were accepted as legitimate coverage corrections.
- The single skip was a genuine defect **in my design recipe**, not in the subagent's reasoning: I wrote `lifetime_net_earnings_cents == 20400` and `payout_tax_document_status == ON_FILE` together, which was valid only while `TAX_DOC_REQUIRED_CENTS` was 60000; I later lowered that constant to 20000 to make the threshold crossable, which silently invalidated the recipe. The instance was rewritten so the pre-trigger state is 24000 gross → net 20400 → `REQUIRED_UPDATE` (blocking `SEND`), and a teacher-fault refund of the not-yet-started second section recomputes the payout to 12000/1800/10200, returning the teacher to `ON_FILE` so a fresh payout's `SEND` succeeds. Both sections are now non-completed (the corrected accrual selector counts non-cancelled sections whose start falls inside the period), and the clock sits between the two start instants so the second section is still cancellable. The Step 5 agent was resumed and emitted two further tests for the rewritten instance.

Final verified state: `pytest --collect-only` collects **59 tests** (queue A 36, queue B 23); 59 `Design:` tag lines covering **41 unique instances = all 18 difficulty + all 23 non-excluded corner instances**; `scaffold_lint.py` still `VERDICT: clean lint` (584 calls).

## Step 6: Generate Implementation — 2026-10-01T10:24:00.000Z

Subagent (general-purpose, foreground) was launched with the ISOLATION RULE and PROCESS SAFETY clauses copied verbatim. **The host session ended mid-flight and the subagent's result was never recorded**, so its report is lost; per the interrupt-recovery procedure the artifacts were verified on disk rather than the step being blindly re-run.

State found on disk at 2026-10-01T10:13:38Z: `workspace/implementation/` contained `requirements.txt`, `start.sh`, and 2,320 lines of Python across `core/` (clock, store, auth, envelope, errors, constants), `services/` (calc, cascades, views) and `routes/` (onboarding, catalog, learning, money, trust, common). **`app.py` was missing entirely** — `start.sh` execs `python3 app.py`, so the server could not boot. The two `/_` operational endpoints were also absent, and no sweep logic existed for them.

Verification of the partial artifact before extending it: `python3 -m compileall` was clean and every module imported without error (no dangling imports despite the dead subagent), and `services/calc.py` was found to implement the refund tier with the correct hours-remaining formulation (`hours >= C.REFUND_FULL_CUTOFF_HOURS[fmt]`), matching the PRD rather than the scaffold prose that was corrected during Step 5.

Step 6 was therefore completed **in the foreground by the orchestrator**, which by that point already had the necessary module APIs in context:

- `routes/ops.py` (new, ~165 lines) — implements `POST /outschool/_clock/set_current_utc` (the only thing that moves the logical clock; default remains exactly `2026-09-01T00:00:00Z`) and `POST /outschool/_ops/run`, whose sweep performs: OPEN-report SLA escalation past `REPORT_SLA_PERIODS`; reviewer-SLA expiry of `SAMPLE_PENDING` applications past `REVIEWER_SLA_PERIODS` (with the revision increment and the auto-`REJECTED` at `APPLICATION_MAX_REVISIONS`); section auto-cancellation past the `AUTO_CANCEL_CUTOFF_HOURS` cutoff when the `expected_learners` projection (falling back to `min_learners`) is strictly below `min_learners`; reservation release at section start; completion of settled `MIN_ENROLLMENT_MET` sections past their start; and the teacher earnings/risk recompute. Auto-cancellation is evaluated before reservation release so a cancelled section resolves its seats through the cancellation path rather than being released twice.
- `app.py` (new, 51 lines) — registers the six blueprints, disables JSON key sorting so the envelope keeps its `meta` / `response_type` / `data` order, routes unrouted paths and bad methods through the declared error envelope, and reads `$PORT`, binds `0.0.0.0` and runs in the foreground.

Verified after the fix: the server boots cleanly from `bash start.sh`, the Flask URL map registers **exactly 40 routes** (matching the scaffold's 40 declared endpoints), and live smoke calls return well-formed envelopes — `POST /outschool/_clock/set_current_utc` echoed `2026-09-01T00:00:00.000Z`, and `POST /outschool/teacher-applications` created a `DRAFT` application with `version: 1`, `screening_outcome: null` and `revision_count: 0`.

Isolation note: because this pipeline runs Steps 5 and 6 sequentially rather than concurrently (a standing instruction for this host), the isolation that concurrency would have given for free had to be enforced by the explicit read ban in the Step 6 prompt. The Step 6 agent was instructed not to read either design index, `test_suite/`, `test_helpers/` or `worklog.md`, and not to run the test suite. The foreground completion above was performed after the fact and touched only `routes/ops.py` and `app.py`, neither of which was derived from test artifacts.

## Step 7: Run Tests and Iterate — 2026-10-01T10:41:00.000Z

Run in the FOREGROUND by the orchestrator. The first round was executed directly to size the failure surface; the loop then proceeded through five rounds, ending in a clean 8-round parallel stability sweep.

Iteration history: **5/59 → 31/59 → 48/59 → 53/59 → 57/59 → 59/59**, then 8/8 rounds at 59/59.

### Tests deleted

**None.** No test was deleted, skipped or marked xfail. One assertion literal was corrected (see test fix 3) — that is a correction to the post-repair expected state, not a weakening.

### Fixes applied to `implementation/`

1. **`core/clock.py` — module-level `period_index()` renamed to `period()`.** Nine call sites across `routes/trust.py`, `routes/onboarding.py`, `services/calc.py` and `services/cascades.py` called `clock.period()`, which did not exist; the module defined only `period_index()`. This was a dangling inconsistency left by the Step 6 subagent that died mid-flight, and it was the single root cause of 54 of the first round's failures (`AttributeError: module 'core.clock' has no attribute 'period'`, surfacing as HTTP 500 on nearly every endpoint).
2. **`app.py` and `routes/ops.py` created.** The Step 6 subagent died before writing the entrypoint, so `start.sh` exec'd a non-existent `app.py` and the two `/_` operational endpoints were absent. `app.py` registers the six blueprints and reads `$PORT`; `routes/ops.py` implements the logical clock and the full sweep (report SLA escalation, reviewer SLA expiry, section auto-cancellation, reservation release, completion, earnings/risk recompute).
3. **`services/calc.py` — `enrollment_min_met` now counts seats taken (confirmed plus reserved).** This is a **PRD repair**, not a test accommodation. As written the contract was unsatisfiable: `confirm` requires the section to have reached `MIN_ENROLLMENT_MET`; `meet-minimum` requires `enrolled_count >= min_learners`; and `enrolled_count` counts only `CONFIRMED` enrollments — which cannot exist until after a confirmation. No sequence of declared calls could produce a single confirmed enrollment, so the object graph was unbuildable (21 tests failed in setup with `ERR_INVALID_STATE - The section has not reached MIN_ENROLLMENT_MET`). The floor now counts committed seats, which is the real-world semantic: a section "makes" when enough families hold seats, and payment is collected afterwards. `enrolled_count`, `reserved_count` and `seats_remaining` keep their PRD definitions, so every seat-arithmetic assertion is unaffected.
4. **`routes/learning.py` — the cancellation cutoff is computed rather than read.** The handler read `section["cancellation_cutoff_utc"]`, but that key is derived in the view layer and never stored on the record, so every parent cancellation raised `KeyError: 'cancellation_cutoff_utc'` (6 tests).
5. **`services/cascades.py` — the suspension and archive cascades also cancel `MIN_ENROLLMENT_MET` sections.** Consequence of fix 3: a pre-start section can now rest in `MIN_ENROLLMENT_MET`, and the cascade's `SCHEDULED`/`OPEN_FOR_ENROLLMENT` scope would have left it running under a suspended teacher.
6. **`services/cascades.py` — the refund clawback reverses the fee at the payout's own frozen rate.** The clawback recomputed the payout and then used the *post-refund* `fee_rate_applied` to reverse the fee, but the recompute re-bands the smaller gross (3200 → 1600 crosses the 2000-cent band edge, 0.25 → 0.30), so it reversed 480 on a section that had been charged 400. That broke the Rule 9 conservation invariant — the compensating pair no longer left `refund − reversed_fee` equal to the refunded section's net, and the surviving section's net moved for a reason unrelated to the refund. The rate actually charged is now captured before the recompute and held fixed.

### Fixes applied to `test_helpers/`

1. **`fixtures.py` — `reserve_seat` now advances the section to `MIN_ENROLLMENT_MET` once the floor is filled, and `declare_minimum_met` is idempotent.** This is the fixture half of the fix-3 repair: the suite's recipes reserve seats and then confirm them, which the repaired contract permits only once the minimum is declared. The advance fires only when the floor is actually reached, so a section reserved below its floor stays `OPEN_FOR_ENROLLMENT` — which is what `confirm_enrollment_before_min_enrollment_met_rejected` asserts. Tests that declare the minimum themselves are unaffected because the declaration is now a no-op on an already-advanced section.

### Fixes applied to `test_suite/`

2. **`test_02_listings_and_sections.py`** — the expected `cancellation_cutoff_utc` literal was `2026-11-04T14:00:00Z`; the envelope stamps three fractional digits, so the literal became `2026-11-04T14:00:00.000Z`. The test was wrong, not the implementation.
3. **`test_04_pricing_refunds_and_seat_invariants.py`** — the surviving section's expected status changed from `OPEN_FOR_ENROLLMENT` to `MIN_ENROLLMENT_MET`, which is the correct state once its reservations fill its floor. The assertion's intent (the section was *not* cancelled) is preserved.
4. **`test_05_payouts_fees_and_periods.py`** — four tests shared one learner across two sections and subscribed that learner between reservations, so the second seat was priced at the plan-discounted rate (1600 instead of 1999/2000) and the instances' own asserted economics broke. Each section now gets its own learner, reserved at list price and subscribed before its own confirmation. Fixture-level bug, fixed in the test bodies because the learner is a per-test local.

### Verification

Final 8-round parallel sweep (`--isolation per-test-server`, all 8 launched concurrently and joined with `wait`): **every round 59/59 passed, 0 failed, 0 errors, 0 skipped.** `workspace/implementation/results.{1..8}.json` hold the per-round evidence.

### PRD divergences introduced by this step (input to Step 8)

Fixes 3 and 5 change behaviour that `PRD.md` currently describes differently, so the PRD must be patched to match the implementation:
- §3.4/§3.6 state that `enrollment_min_met` is true when `enrolled_count` reaches `min_learners`, and that `meet-minimum` refuses an open section whose *confirmed* enrollment is below the floor. The implementation (and the only satisfiable reading) counts confirmed **plus reserved** seats.
- §3.2 scopes the suspension cascade to sections in `SCHEDULED` or `OPEN_FOR_ENROLLMENT`. The implementation also cancels `MIN_ENROLLMENT_MET` sections, which is necessary now that a pre-start section can rest in that state.
- §3.8 says the clawback re-derives `fee_rate_applied`. The implementation holds the payout's existing rate fixed across the recompute and reverses the fee at that rate, which is what preserves the conservation invariant the same section declares.

## Step 8: Finalize PRD — 2026-10-01T10:47:00.000Z

Not skipped: Step 7 applied six `implementation/` fixes and four `test_helpers/`+`test_suite/` fixes, so the PRD had known divergence sites to patch. Subagent (general-purpose, foreground), with the Step 7 entry inlined verbatim as `<step_7_diff>` (the subagent is forbidden from reading `worklog.md`). Summary returned verbatim:

> Done. `PRD_FINALIZED.md` is written; only the three Step 7 items with PRD consequences produced edits (items 3, 5, 6). Items 1, 2, 4, 7–10 were confirmed to have no PRD consequence and left the document untouched.
>
> ## Size delta
>
> - `PRD.md`: 390 lines / 76,052 bytes
> - `PRD_FINALIZED.md`: 390 lines / 76,674 bytes
> - Line delta: 0 (0.0%). Seven lines were revised in place across 5 hunks; no lines added or removed, no new sections.
>
> ## Changes (one per bullet)
>
> - **§2.6 validation ladder, rule 37** — *revise* — `ERR_MIN_ENROLLMENT_NOT_MET` condition changed from "the section's confirmed enrollment has reached `min_learners`" to "the section's seats taken — `enrolled_count` plus `reserved_count` — have reached `min_learners`" — `implementation/services/calc.py:90`, `implementation/routes/catalog.py:213-215`.
> - **§3.2 suspension cascade, hop 2** — *revise* — section scope widened from "`SCHEDULED` or `OPEN_FOR_ENROLLMENT`" to "`SCHEDULED`, `OPEN_FOR_ENROLLMENT` or `MIN_ENROLLMENT_MET`" — `implementation/services/cascades.py:55`.
> - **§3.3 listing-mirrors-teacher paragraph (both clauses)** — *revise* — section scope widened the same way for the suspend/terminate cascade and for the policy-reject/terminate archive cascade — `implementation/services/cascades.py:55` (via `suspension_cascade`) and `implementation/services/cascades.py:65` (`archive_listing_sections`, called from `routes/onboarding.py:303` and `routes/catalog.py:100`).
> - **§3.4 occupancy paragraph** — *revise* — `enrollment_min_met` redefined from "`enrolled_count` has reached `min_learners`" to "the seats taken — `enrolled_count` plus `reserved_count` — have reached `min_learners`", with the clarifying clause that reservations alone satisfy the flag — `implementation/services/calc.py:90`.
> - **§3.4 declaring-the-minimum paragraph** — *revise* — refusal condition changed from "confirmed enrollment is still below the floor" to "seats taken are still below the floor" — `implementation/routes/catalog.py:214`.
> - **§3.8 clawback hop 1** — *revise* — `fee_rate_applied` removed from the set of re-derived fields and pinned as held fixed at the payout's existing rate; the reversed-fee and liability sums now explicitly multiply by that held rate — `implementation/services/cascades.py:97,103,111,115,121`.
>
> ## Per-edit pre-edit search log
>
> **Edit A (`enrollment_min_met`, §3.4 ×2 + ladder 37)**
> - (a) Subject: the definition of the section's `enrollment_min_met` flag and the `ERR_MIN_ENROLLMENT_NOT_MET` gate.
> - (b) Paths enumerated/read: `services/calc.py:69-92` (`occupancy`, the sole producer); `services/views.py:103-127` (`section_out` exposes `enrolled_count`, `reserved_count`, `seats_remaining`, `enrollment_min_met`); `routes/catalog.py:206-218` (`meet_minimum` — status gate then flag gate); `routes/learning.py:213-233` (seat-loss and reopen branches); `routes/ops.py:91-128` (auto-cancel, release, completion sweeps); `services/cascades.py:43-68`. Grepped all `min_learners`/`enrolled_count`/`enrollment_min_met` sites (10 hits) and all `MIN_ENROLLMENT_MET` setters (only `catalog.py:216`).
> - (c) Adjustment: worded the edit as a definition of the *boolean only*, never as a global claim about "the floor". The seat-loss and reopen branches in `learning.py:220,230` genuinely use `enrolled_count` (confirmed-only) and the PRD §3.6 sentence that describes them already says `enrolled_count`/`confirmed enrollment`; I left that sentence untouched so the two coexist. I also deliberately did **not** claim a section auto-advances to `MIN_ENROLLMENT_MET` — the status is set only by the explicit `meet-minimum` endpoint, so an auto-advance claim would have been a new mismatch.
>
> **Edit B (cascade scope, §3.2 + §3.3 ×2)**
> - (a) Subject: which section statuses the suspension and listing-archive cascades cancel.
> - (b) Paths enumerated/read: `services/cascades.py:26-68` (`cancel_section_and_enrollments`, `suspension_cascade`, `archive_listing_sections`); all four callsites of `cancel_section_and_enrollments` — `cascades.py:56`, `cascades.py:66`, `routes/ops.py:104`, `routes/learning.py:223`, plus the teacher cancel at `routes/catalog.py:239`; all callsites of the two cascades — `routes/onboarding.py:264` (manual suspend), `services/cascades.py:157` (risk cascade), `routes/onboarding.py:303` (terminate), `routes/catalog.py:100` (policy-reject). Grepped every `SCHEDULED`/`OPEN_FOR_ENROLLMENT` status tuple in the implementation.
> - (c) Adjustment: widened only the two cascade status lists. Verified the four *other* status lists in the codebase are narrower for real reasons and left their PRD counterparts alone: the auto-cancel sweep (`ops.py:98`) stays `SCHEDULED`/`OPEN_FOR_ENROLLMENT` (§3.4 line 222 untouched), the reservation sweep keeps its `OPEN_FOR_ENROLLMENT` wording (§3.4 line 226 untouched), and the teacher-cancel endpoint's three-status list already matched §3.4 line 218. Also did not touch the adjacent listing-lifecycle sentences in §3.3, which are outside the Step 7 diff.
>
> **Edit C (clawback rate, §3.8)**
> - (a) Subject: whether the clawback re-derives `fee_rate_applied` and which rate the reversed fee / liability are computed at.
> - (b) Paths enumerated/read: `services/cascades.py:74-138` (`teacher_fault_clawback` — the only recompute site; `original_rate` captured at line 97, fee at 103, rate written back at 121); `routes/money.py:63-82` (the only other writer of `fee_rate_applied`, at creation, governed by §3.8's banding paragraph, which I left verbatim); `services/views.py:182` (field exposed); all three clawback callsites — `routes/catalog.py:243`, `routes/learning.py:215`, `routes/learning.py:227`; `services/calc.py:131-142` (`gross_and_fee`), `calc.py:199-204` (`payout_net_after_refunds`), `calc.py:178-196` (`approval_cap_figures`, which consumes the recomputed net).
> - (c) Adjustment: rephrased the re-derivation list rather than deleting the sentence, so the creation-time banding rule in §3.8 stays intact and the held rate is stated as "the rate the payout already carries". Also made the liability clause say "that same floored fee" so the 0.50 liability is unambiguously computed at the held rate, matching `cascades.py:115-119`.
>
> ## Notes
>
> - Implementation was not modified (mtimes confirm all `implementation/*.py` files are Step 7-era; I made no writes there).
> - Two PRD-vs-implementation inconsistencies exist outside the Step 7 diff (the §3.9 money-sweep sentence claiming tax status suspends a teacher, which contradicts §3.2 and the implementation; and the §3.4 reservation-sweep sentence omitting `SCHEDULED` sections). Per the HARD SCOPE I did not touch them.

Orchestrator verification: `PRD_FINALIZED.md` exists at 390 lines / 76,524 bytes (0-line delta over `PRD.md`), and `diff` confirms exactly five revised lines in place with no insertions or deletions. `find workspace/implementation -name "*.py" -newermt` returns nothing, confirming the subagent made no implementation writes — so the Step 7 clean sweep remains valid. The two out-of-scope inconsistencies the subagent deliberately left are carried forward to Step 9, which is exactly their remit.

## Step 9: Complete PRD — 2026-10-01T11:12:00.000Z

Subagent (general-purpose, foreground). Source was `workspace/PRD_FINALIZED.md`; output `workspace/PRD_COMPLETED.md`. It read `implementation/`, `test_helpers/`, `test_suite/` and `INSTRUCTION.md`, and did not read the scaffold or the worklog. Summary returned verbatim:

> PRD_COMPLETED.md is written. Here is the report.
>
> ## Deliverable
> `/home/ubuntu/github/CodingPRD/tasks/task_3354_small_group_live_class_marketplace_independent_teacher/workspace/PRD_COMPLETED.md`
>
> **Stats:** 390 lines → 390 lines (unchanged); 76,409 → 80,876 chars (**+4,467**; +4,497 bytes). 27 of 390 lines touched; heading set, paragraph/blank-line structure and all three tables are byte-identical to the source. All edits are inline inserts/revisions — no new sections, no new paragraphs.
>
> **Counts: 14 ambiguity-pins, 15 mismatch-revisions (29 changes).**
>
> Every finding was verified by reading the source and then confirmed live: I ran `implementation/app.py` on private ports (51399/51407), drove ~60 probes through the real HTTP surface, and killed only the PIDs I started (ports are now free).
>
> ### Mismatch-revisions (PRD described a different behaviour)
> - §2.4 — revise — mismatch — "the clock is not permitted to move backwards" was false; a target instant earlier than the current one is accepted and only the period index is monotonic — `core/clock.py:22-31`
> - §2.6 rule 5 — revise — mismatch — "referenced resources … are not archived" applies only to the listing a section is scheduled under; a report may name an archived listing (verified 201) — `routes/catalog.py:128-129` vs `routes/trust.py:23-28`
> - §2.6 rule 16 — revise — mismatch — ownership also gates section opening, which the enumerated list omitted (verified 403) — `routes/catalog.py:194`
> - §2.6 closing — insert — mismatch — the enum-typed `stage`/`verdict`, `action`, `severity`, `category` are checked before the state/SLA/cap rules they sit below (verified `ERR_INVALID_ENUM_VALUE` over `ERR_REPORT_SLA_EXPIRED` and over `ERR_REPORT_WINDOW_CLOSED`) — `routes/onboarding.py:134-137`, `routes/trust.py:81-92`
> - §2.6 closing — insert — mismatch — a blank body identifier is `ERR_MISSING_REQUIRED_FIELD` on enrollment/report creation (verified) while listing creation's missing `teacher_id` is `ERR_REFERENTIAL_INTEGRITY` (verified) — `routes/learning.py:80-84`, `routes/trust.py:20-22`, `routes/catalog.py:23-25`
> - §3.1 — revise — mismatch — a `SCREENING`/`FAIL` verdict lands in `SAMPLE_REJECTED`, not `REJECTED` (verified), and it also binds the reviewer — `routes/onboarding.py:159-175`
> - §3.1 — revise — mismatch — final approval answers `ERR_APPLICATION_NOT_APPROVED` for *any* non-`SAMPLE_APPROVED` state, including an exhausted-budget `REJECTED` one (verified) — `routes/onboarding.py:184-196`
> - §3.2 — revise — mismatch — the tax paragraph's topic sentence claimed a money-driven suspension path (its own body already said the opposite) — `routes/ops.py:131-152`, `services/calc.py:236-241`
> - §3.2 — revise — mismatch — suspension hop 2 cancels live sections of *every* listing the teacher owns, not only the ones moved to `SUSPENDED` (verified: a `DRAFT` listing's `SCHEDULED` section was cancelled) — `services/cascades.py:51-58`
> - §3.2 — revise — mismatch — "every teacher whose lifetime earnings have changed" → the sweep re-derives for all teachers, refreshing version only when the standing moves — `routes/ops.py:139-144`
> - §3.3 — revise — mismatch — "each of its sections" → every one of the teacher's sections (same cascade) — `services/cascades.py:51-58`
> - §3.4 — revise — mismatch — **known #2**: the reservation sweep also releases `SCHEDULED` sections (verified `RELEASED` + reported id) — `routes/ops.py:98,113`
> - §2.6 rule 6 / §3.5 — revise — mismatch — `birth_date` must be *strictly before* `CURRENT_DEFAULT_UTC`; equality is refused (verified) — `routes/learning.py:34-35,88-89`
> - §3.6 — revise — mismatch — the `RELEASED`/`FULL`/`platform` release belongs to the automatic-cancellation sweep, not to any cancelled section; a teacher/suspension cancellation resolves to `CANCELLED_BY_TEACHER` — `routes/ops.py:104-110`, `services/cascades.py:26-40`
> - §3.7 — revise — mismatch — "The same error covers an attempt to report on a section that has not yet started" has no counterpart: a report names a listing, never a section, and filing has no time gate — `routes/trust.py:16-54`
> - §3.9 — revise — mismatch — **known #1**: the money sweep never suspends for tax; `suspended_teacher_ids` is filled by the report-risk cascade (verified: a `REQUIRED_UPDATE` teacher stayed `ACTIVE`, and a teacher pushed to 65 by a *filed* report was suspended by the sweep) — `routes/ops.py:131-152`
>
> ### Ambiguity-pins (PRD silent; pinned to what the implementation does)
> - §2.3 — insert — ambiguity — out-of-band or non-integer `limit`, negative/non-integer `offset` → `ERR_INVALID_ENUM_VALUE` 400 (verified) — `core/envelope.py:67-86`
> - §2.4 — insert — ambiguity — clock endpoint: missing `to_iso8601` → `ERR_MISSING_REQUIRED_FIELD`, unparseable → `ERR_INVALID_TIME_WINDOW` (verified) — `routes/ops.py:29-33`
> - §3.2 — insert — ambiguity — the activation tax gate is refused with `ERR_TAX_DOC_MISSING` — `routes/onboarding.py:243-244`
> - §3.2 — revise — ambiguity — reinstatement's two gates carry `ERR_TAX_DOC_MISSING` / `ERR_INVALID_STATE` (verified `ERR_TAX_DOC_MISSING`) — `routes/onboarding.py:274-277`
> - §3.2 — insert — ambiguity — termination with live sections → `ERR_INVALID_STATE` (verified) — `routes/onboarding.py:289-295`
> - §3.3 — revise — ambiguity — publishing without `POLICY_APPROVED` → `ERR_INVALID_STATE` (verified) — `routes/catalog.py:109-112`
> - §3.3 — insert — ambiguity — `reason_code` is validated under either decision; a rejection may omit it, leaving the field null (verified) — `routes/catalog.py:90-97`
> - §3.4 — insert — ambiguity — cancelling at/after `start_utc` → `ERR_INVALID_STATE` (verified) — `routes/catalog.py:226-229`
> - §3.5 — insert — ambiguity — the section's status is never consulted when reserving; seats can be taken on cancelled/unopened sections (verified 201 on both) — `routes/learning.py:75-145`
> - §3.6 — revise — ambiguity — a parent cancellation moves the enrollment to `CANCELLED_BY_TEACHER` — `routes/learning.py:205`
> - §3.8 — insert — ambiguity — with mixed formats in one period the largest subtraction applies (verified `fee_rate_applied` 0.27 for `ONE_TIME` + `ONGOING`) — `services/calc.py:165-167`
> - §3.8 — insert — ambiguity — the idempotency fingerprint is a literal string comparison, so equivalent instants written differently trip the overlap rule — `routes/money.py:36-44`
> - §3.9 — insert — ambiguity — auto-cancellation is evaluated before reservation release; an auto-cancelled section's `RELEASED` enrollments are *not* in `released_enrollment_ids` (verified) — `routes/ops.py:98-115`
> - §3.1 — revise — ambiguity — the screening-stage rejection binds `reviewed_by_user_id`/`reviewer_bound_period_index` — `routes/onboarding.py:159-160`
>
> ### Deliberately not changed (noted for the record)
> Additive-only behaviours with no interpretation conflict: extra `status`/`format` list filters; the defensive 404/405 handlers and the uncatalogued `ERR_INTERNAL_ERROR` 500; `ERR_INVALID_ENUM_VALUE` for non-integer `teaching_sample_minutes`, negative `expected_learners` and out-of-range integers; the once-per-request version-bump dedup; and the batch's internal sub-sweep ordering.

### Final verification (orchestrator)

- `PRD_COMPLETED.md` exists at 390 lines / 81,021 bytes and `diff -q` against `PRD_FINALIZED.md` reports a genuine difference — the step did not die mid-flight into a silent no-op.
- **Implementation untouched since the clean sweep.** `find workspace/implementation -name "*.py" -newermt "2026-10-01 10:41:00"` returns nothing, so the Step 7 8-round result remains valid and no re-run was required. (The Step 9 agent executed `app.py` read-only on private ports; it wrote no source.)
- `workspace/implementation/results.{1..8}.json` are all present and each reports **59/59 passed, 0 failed, 0 errors, 0 skipped**.
- Dead-code audit (the failure mode where a PRD-required check ships defined-but-never-called): all fourteen PRD-required helpers in `services/` and `core/` have at least one live callsite — `tax_document_status` 3, `lifetime_net_earnings` 3, `unpaid_earnings` 1, `approval_cap_figures` 2, `apply_risk_cascade` 2, `suspension_cascade` 2, `archive_listing_sections` 2, `teacher_fault_clawback` 3, `refund_tier` 1, `write_refund` 3, `occupancy` 6, `accrual_sections` 2, `gross_and_fee` 1, `risk_scores` 3.
- `scaffold_lint.py`: `VERDICT: clean lint` (40 endpoints, 18 §1.8 + 23 §1.9 instances, 584 calls).
- `pytest --collect-only`: 59 tests; 41 unique `Design:` tags = all 18 difficulty instances + all 23 non-excluded corner instances.
- `bash start.sh` boots from a fresh process and answers `HTTP 200`.

## Pipeline complete — 2026-10-01T11:12:00.000Z

All nine steps done. Deliverable: 8 entities / 40 endpoints / 8 state machines / 8 calculations / 39 validations / 39 errors; 59 tests (36 difficulty-derived, 23 corner-derived) passing in all 8 rounds of the parallel stability sweep under `--isolation per-test-server`; PRD lineage `PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md` with no implementation writes after the sweep.
