# Worklog — task_3182_certified_collision_repair_network_standards_parts_requirements

## Step 1: Create Task Directory — 2026-09-30T08:05:21.230Z

Task directory pre-allocated by caller: `./tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/` with `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T08:35:00.000Z

All checks pass. Final lint verdict block (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/SCAFFOLD.yaml
  Difficulty design:  tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    78
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     24
  Calls scanned (§1.8+§1.9):  525

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Report

Generated the full scaffold package for task 3182 (Certified Collision Repair Network) in `/home/ubuntu/github/CodingPRD/tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/`, with difficulty maximized per the caller's directive:

**SCAFFOLD.yaml** (§1.0–§1.7):
- Archetype: compliance/audit primary + posture-driven gating secondary; layers: cascading side effects, rate/threshold triggers, derived-field reconciliation, OCC, version-pinning. Hybrid topology, compound state machines, segregation-of-duties role model, immediate consistency.
- 15 entities (Shop posture machine with APPLICANT→CERTIFIED→PROBATION/SUSPENDED/EXPIRED→DECERTIFIED; versioned Requirement revisions that lapse pinned attestations; CertificationCycle with zero-gap 365-day closed windows; Audit with half-open scheduling windows; CorrectiveAction with severity-keyed due dates and issuer≠verifier segregation; Technician + TrainingCourse + CourseCompletion with calendar-month currency expiry; RepairOrder with QC↔REWORK cycle bounded at 3; ProcedureStep chronology rules (pre-scan required, post-scan-after-parts, calibration-after-scan); PartLineItem with OE/safety/documentation rules; WarrantyClaim with escalation thresholds; InsurerRelation steering gated by posture; Referral with 72h TTL and a 3-factor min-capped ranking selector).
- 7 calculations (dual-variant compliance score live vs audit-snapshot; dual-variant OE parts ratio by-count vs by-cost with empty-set = 1.0; tiered+multiplier+penalty warranty accrual with pinned round-before-penalty order; threshold grading with escalation penalty; weighted referral selector with explicit tie-breaks excluding id; technician currency with vacuous-100 rule; half-open audit overlap).
- 25 ordered validations, 78 endpoints (incl. `/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z and `/_sweep/run`), 24 error codes, 3 OCC concurrency rules, 6 roles.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances, exactly 2 per each of the 9 difficulty rules, with all formula-derived asserts precomputed as literals (e.g. ratio 0.5/0.7843, accrual 8500, grade boundaries 24→C / 25→F, compliance 85.0).

**SCAFFOLD_CORNER_DESIGN.yaml**: 24 instances across all 9 guide sections (entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, consistency model).

`scaffold_lint.py` reports clean lint (0 violations) over 525 scanned calls; all instance names unique across both design files; scenario stored verbatim.

## Step 3: Copy Shared Files — 2026-09-30T08:35:16.662Z

Copied `./INSTRUCTION.md` → `tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T08:43:44.942Z

All checks now pass. The PRD is complete.

**Report**

Generated `/home/ubuntu/github/CodingPRD/tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/workspace/PRD.md` (~60 KB, 5 sections) from the task's SCAFFOLD.yaml, following the prd-bench-doc-generator skill. The two forbidden design-index files were not read.

Structure: §1 introduction (3 paragraphs); §2 with 11 subsections (roles/RBAC with per-role identity translation, verbatim §2.2 response envelope, pagination, common resource properties, logical clock & sweeps, posture-as-derived-state, live-vs-snapshot compliance score, precision/rounding regimes, OCC, nested-resource resolution & validation priority order, warranty reserve ledger); §3 with 8 narrative subsections (onboarding & cycles, requirements & attestations, audits & corrective actions, technicians & training, repair orders & chronology, parts provenance & OE ratios, warranty & reserve accrual, referrals/locator/insurer relations); §4 4-column endpoint table (all 78 endpoints); §5 2-column error table (all 24 error IDs).

Hard contract results:
- **Contract 1 (field-name coverage): PASS** — 94 entity fields, 71 endpoint inputs, 2 OCC fields all present in backticks (verified mechanically via a YAML-vs-PRD diff script; final diff empty after adding `reviewed_by_user_id`, bare `status`, and `TERMINATED`).
- **Contract 2 (rule coverage): PASS** — all state-machine transitions with preconditions/side effects (including Shop posture cascades at depth 3, corrective-action rejection loops with `round_number` increment, and compensation transitions), all 7 calculations with precise prose formulas and pinned constants (weights 30/30/15/25; grades A/B/C/F at 0/1–5/6–24/25+ with escalation penalty 3; OE ratio empty-set rule 1.0 and 4-decimal rounding; training vacuous 100.0; referral scoring 0.6/0.3/0.1 with load cap 20 and `created_at` tie-break; tiered reserve accrual 3%/2%/1% with ADAS multiplier 1.5, rework penalty 500 cents, and mandatory round-before-penalty ordering; half-open audit-overlap rule), all 25 validations paired with their error IDs, all 3 OCC rules (`expected_shop_version` ×2, `expected_cycle_version`, `ERR_STALE_VERSION`/412), validation priority ordering, and sibling-branch symmetry (both pass-qc paths, both resolve verdicts, all requirement lifecycle branches).
- **Contract 3 (§3 path purity): PASS** — 586 backticked tokens in §3 scanned, zero path/method violations.

One bug fixed during QA: a typo (`WARRANT_ACTIVE` → `WARRANTY_ACTIVE`) and an ambiguous reading of the referral load term were both corrected before shipping.

## Step 5: Generate Unit Tests — 2026-09-30T09:18:21.607Z

All 83 tests collect cleanly. Final summary of what was generated.

## Report

Generated the complete test infrastructure and suite for task 3182 at `/home/ubuntu/github/CodingPRD/tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/`.

**test_helpers/** (7 files):
- `types.py` — all 15 entity TypedDicts with full common fields (PRD §2.4 says every entity carries the full set), plus status enums and the six-role `UserRole` enum.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (shops, cycles, requirements, attestations, audits, corrective actions, technicians/courses/completions, repair orders, procedure steps, part lines, warranty claims, insurer relations, referrals, locator, clock/sweep).
- `api_errors.py` — all 24 error IDs mapped to PRD §5 HTTP statuses, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` plus `assert_shop_invariants`.
- `factories.py` — input-only payload factories (scan_report_uri auto-attached for PRE_SCAN/POST_SCAN per the PRD rule).
- `constants.py` — category weights, severity weights, corrective-action deadlines, grade boundaries, accrual tiers, TTLs.
- `test_users.py` — opaque-role shared constants plus `make_shop_manager_headers(shop_id)` (entity-backed identity threading), auditor/admin per-instance builders, and `ANONYMOUS_HEADERS = None` for the locator.
- `fixtures.py` — composite helpers: `certify_shop`/`certify_shop_with_auditor` (APPLICANT→CERTIFIED via zero-finding audit), `open_cycle`, `attest` (OCC-aware, re-reads shop version), `audit_with_finding`, order lifecycle shortcuts (`order_in_qc`, `order_completed`, `order_warranty_active`), `create_insurer_relation`, `create_referral`, `suspend_shop_via_critical`.

**test_suite/** (conftest + 13 test files, 83 tests):
- Coverage audit passed programmatically: every one of the 14 queue-A difficulty instances has exactly 2 tests; every one of the 24 queue-B corner instances (no stubs exist in this index) has ≥1 test; all tags resolve to real `name:` entries; zero bad tags.
- Citation sweep passed: every docstring carries a PRD §-cited verbatim quote verified against PRD.md after whitespace/backtick normalization (0 misses); every test has exactly one `Design:` line and no `skip`/`xfail` marks anywhere.
- All files byte-compile, `test_helpers` and `conftest` import cleanly against the framework, and pytest collects all 83 tests.

**Key design adaptations:**
- Publish-time `ERR_EFFECTIVE_IN_PAST` means "past" `effective_from` values in recipes are impossible; fixtures create requirements effective at the startup clock and run certification audits first (this also preserves the 85.0 live-score arithmetic the recipes pin).
- Ambiguous recipe-pinned outcomes were relaxed per the error-precedence silence pattern: `referral_accept_gated_by_shop_posture` and `approve_gated_by_technician_currency` assert via `validate_error_is_one_of([...])` plus the state pin (referral DECLINED / order remains ESTIMATE), since the PRD does not pin a single error_id when the suspension cascade preempts the accept/TTL check.
- Multi-shop routing tests use distinct auditor identities for parallel certifications to respect the PRD §3.3 rule that a shop's cycle cannot schedule an audit while another audit of the same shop is active — and auditor scoping keeps windows independent per shop.

## Step 6: Generate Implementation — 2026-09-30T09:45:27.581Z

Implementation complete. Summary of what was built:

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_3182_certified_collision_repair_network_standards_parts_requirements/workspace/implementation/`:

- **`start.sh`** — executable, guards `pip install` behind a `flask` import check (safe for per-test-server reboots), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- **`app.py`** — Flask app, auth `before_request` (all endpoints require `X-User-ID` + recognized `X-User-Role` except the anonymous `POST /network/locator/search`), `ApiError` handler producing the scaffold's exact error envelope
- **`db.py`** — in-memory dicts for all 15 entity types, logical clock starting at `2026-09-01T00:00:00Z`, monotonic `_seq` for creation-order tie-breaks, `serialize()` strips internal fields
- **`util.py`** — envelope (`meta.api_request_id`/`api_request_timestamp`/`response_type`/`data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, 1..100), ISO8601 ms timestamps, OCC `bump()` (version+1, updated_at from logical clock)
- **`calc.py`** — all six calculations with pinned constants and round-half-up precision: weighted compliance score (incl. TRAINING halving factor), grade thresholds (0=A, 1-5=B, 6-24=C, ≥25=F, +3 per ESCALATED claim), OE ratios (4dp, empty-set=1.0), technician currency (2dp, vacuous 100.0), referral ranking (0.6/0.3/0.1 weights, load cap 20, tie-breaks score→compliance→created_at, 6dp), warranty accrual (marginal tiers 3%/2%/1%, ×1.5 ADAS, round then +500/rework), haversine miles, calendar `add_months`
- **`sweep.py`** — posture cascades (suspend/decertify force-decline ROUTED referrals, steering recompute, locator_hidden incl. VERIFICATION-with-CRITICAL rule), `apply_pass_posture` shared by cycle-close and zero-finding pass, and the full clock sweep (completion expiry, referral TTL, claim 30-day close, COMPLETE→WARRANTY_ACTIVE with accrual, WARRANTY_ACTIVE→CLOSED with reserve release, corrective-action overdue → audit FAILED/cycle CLOSED_FAIL, CRITICAL overdue → SUSPENDED, cycle window expiry on the shop's latest cycle → EXPIRED)
- **`routes/`** — 8 blueprints covering all 79 registered endpoints: shops/cycles/attestations, requirements (versioned rows, publish/publish-revision/retire with attestation lapse cascades), audits + corrective actions (segregation-of-duties verify, REJECTED spawns fresh OPEN action with new due_at, round_number bump), technicians/courses/completions (with status filters tolerant of un-swept EXPIRED), repair orders/steps/part lines, warranty claims (escalation gating, reserve floor), insurer relations, referrals/locator/clock

## Verified end-to-end (fresh boots each time)

Certification via zero-finding pass (APPLICANT→CERTIFIED), full corrective-action loop with self-verify rejection and grade-B close, OCC `ERR_STALE_VERSION`, `ERR_CYCLE_WINDOW`, safety-critical/undocumented part rejections, OE ratio variants, scan-after-parts chronology both accept and reject paths, `ERR_MAX_REWORK`, ADAS gating, insurer steering gating on referral auto-route, referral accept/decline/TTL-expiry with counter compensation, warranty reserve accrual (5000c on 200000c base) and claim acceptance decrement, cycle-window expiry to EXPIRED and recovery via a new cycle, requirement revision cascade (`REQUIREMENT_REVISED` lapse, score 70→55), `ERR_EFFECTIVE_IN_PAST`.

## Deliberate ambiguation calls (documented in code)

- **ZIP centroids**: derived from known shop ZIP codes (same-ZIP ⇒ distance 0); unknown consumer ZIP ⇒ empty pool. The PRD references no ZIP input for referrals beyond the code itself, so no better source exists.
- **Procedure steps in ESTIMATE**: allowed in addition to the four listed states — otherwise the approve-time PRE_SCAN precondition is unsatisfiable and the whole repair lifecycle is deadlocked.
- **Part-line create restricted to ESTIMATE** (delete keeps the spec'd ESTIMATE/APPROVED/IN_REPAIR): parts created in IN_REPAIR get `created_at` at the current logical clock, which could never be preceded by any POST_SCAN `performed_at`, permanently blocking non-ADAS completion.
- **Part/step `created_at` stamped with wall clock** (chronology markers), while `updated_at`/version and sweep logic stay on the logical clock.

## Step 7: Run Tests and Iterate — 2026-09-30T10:40:00.000Z

All 8 rounds pass 83/83. Clean exit.

## Summary

- **Iterations run:** 5 probe/diagnostic rounds + 2 full 8-round sweeps (initial baseline 44/83; final sweep 8 × 83/83, zero failures in any round).
- **Tests deleted:** none — every failing test traced to a rule covered verbatim in PRD.md; all were repairable at the fixture/test layer or were genuine implementation bugs.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `WINDOW2_END`: leap-year arithmetic bug. 2027-09-01 + 365 days − 1s = 2028-08-30T23:59:59Z (2028 is a leap year), not 2028-08-31T23:59:59Z. This single constant broke every second-cycle setup (12+ tests).

**Fixes applied to `test_suite/`:**
- `test_12_difficulty_dependency_temporal.py` — gap-case window_end made internally consistent (start+365d−1s) so the ERR_CYCLE_WINDOW assertion fires on the gap rule; `test_audit_window_overlap_same_instant_start_rejected` now schedules the duplicate window against a second cycle (same-cycle scheduling is legitimately blocked by the cycle-state gate before the overlap rule); `test_audit_window_half_open_adjacency` rewritten to exercise touching/overlap windows across cycles 1–3 of the same shop (PRD §3.3's first refusal clause bars a second active audit on the same cycle); `_shop_graded_f_with_routed_referral` now certifies the shop first (referrals can't route to APPLICANT shops) and fails cycle 2.
- `test_10_difficulty_state_cascade.py` — two `effective_from` values bumped past the already-advanced logical clock (ERR_EFFECTIVE_IN_PAST); revision-cascade test given a second attested EQUIPMENT row so the PRD §3.2 formula uniquely yields 85.0; retire test's expectation corrected to 100.0 (retiring the only row returns the category to the vacuous 100.0 per §3.2 — the old 85.0 assertion contradicted the PRD formula); suspension-cascade test creates the referral at clock 09-14 so the 72h TTL can't expire it before the 09-16 suspension sweep; rejection-loop test advances the clock before REJECTED so the fresh due_at provably differs.
- `test_08_difficulty_calc.py` — `_ratio_order` now certifies the shop (PRD §3.5 gates order creation on CERTIFIED/PROBATION); snapshot-divergence test's revision `effective_from` set to the close instant (the previous 11:00 value made the row not-yet-effective, so the PRD formula yields 100, not 85); snapshot-stable test reworked to assert the PRD-correct 100.0/100.0 outcome; `_setup_two_certified_shops_same_location` rebuilt to derive LOW=85.0 via a PRD-listed recompute trigger (revision cascade lapsing one of two attested EQUIPMENT rows, then HIGH re-attests); load-drag test fixed arithmetic — at 9 pending the scores tie at 0.955000 and PRD's live-score tie-break keeps the leader, so the flip happens on the 11th referral (10 pending); malformed 15-char VIN format string fixed to 17 chars.
- `test_06_locator_referrals.py`, `test_07_calculations.py`, `test_11_difficulty_priority_boundary.py` — `effective_from` values aligned with the logical clock at creation time; `_grade_boundary_shop` certifies the shop before the graded audit (an APPLICANT's cycle close produces no posture change per §3.1, which only defines APPLICANT→CERTIFIED).

**Fixes applied to `implementation/`:**
- `routes/repairs.py` — part lines and procedure steps were stamped with wall-clock `created_at`, making the PRD §3.5 scan-after-parts chronology unsatisfiable with logical-time `performed_at` values; reverted to the logical-clock common-field stamp. Also widened `EDITABLE_FOR_PARTS` to ESTIMATE/APPROVED/IN_REPAIR per §3.6's editability definition.
- `routes/audits.py` — accept `severity` as an alias for the finding payload key (PRD names only the recorded `finding_severity` field, not the request key); removed the shop-wide duplicate-audit ERR_INVALID_STATE guard so same-shop window intersections surface as ERR_AUDIT_OVERLAP per §3.3; the "last OPEN action submitted" transition to VERIFICATION now ignores REJECTED actions (their OPEN replacements are what matters); the "all actions VERIFIED → PASSED" check likewise excludes REJECTED actions per §3.3's "last non-verified action".
- `routes/shops.py` — close-cycle PASS gate excludes REJECTED corrective actions (superseded by their OPEN replacements).

## Step 8: Finalize PRD — 2026-09-30T10:50:00.000Z

All verified. The file is complete.

## Summary

**File counts:** `PRD.md` 326 lines → `PRD_FINALIZED.md` 326 lines (0% line-count delta; all edits are in-place inline revisions within existing paragraphs — 8 lines modified of 326).

**Changes (one bullet each):**

- §2.4 (Common Resource Properties) — revise — pinned `created_at`/`updated_at` as logical-clock stamps (never wall-clock), noting they feed §3 temporal rules — `implementation/util.py:131-140` (`new_common`, `bump` use `now_logical()`); `implementation/routes/repairs.py:433` comment.
- §3.2 (live_compliance_score) — revise — pinned per-category-score rounding to 2 dp round-half-up, with worked examples (1-of-2 attested = 50.0 exactly; retire-to-vacuous = 100.0) — `implementation/calc.py:101` (`cat_score = 100.0 * satisfied / total`, exact-division rounding).
- §3.2 (audit_snapshot_score) — revise — pinned that "as of the close instant" includes the `effective_from <= clock` effectiveness filter — `implementation/calc.py:89`; `implementation/routes/shops.py:267` (snapshot via `compute_compliance_score` at close).
- §3.3 (audit overlap rule) — revise — pinned that `ERR_AUDIT_OVERLAP` surfaces shop-wide even when the intersecting audit sits on a different, already-closed cycle — `implementation/routes/audits.py:68-77` (no same-cycle guard on the overlap scan).
- §3.3 (issue-findings payload) — revise — pinned request keys: `attestation_id` plus `finding_severity` (with `severity` accepted as alias) — `implementation/routes/audits.py:184-185`.
- §3.3 (FINDINGS_ISSUED → VERIFICATION transition) — revise — pinned that REJECTED actions do not count in the all-SUBMITTED/VERIFIED check — `implementation/routes/audits.py:289-295`.
- §3.3 (VERIFICATION → PASSED + §3.3 cycle-close PASS gate) — revise — pinned that REJECTED actions are ignored by the all-verified check and do not block a PASS close — `implementation/routes/audits.py:332-334`; `implementation/routes/shops.py:233-238`.
- §3.6 (part-line editability) — revise — pinned that adding a part line, like removal, is permitted in ESTIMATE/APPROVED/IN_REPAIR — `implementation/routes/repairs.py:18,426,471`.
- §3.8 (referral ranking) — revise — pinned that score ties at the 6th decimal resolve by live compliance score before creation order (load term decays in 0.005 steps) — `implementation/calc.py:269-271`; `implementation/routes/referrals.py:26-30,183`.

**Per-edit pre-edit search log:**

1. **§2.4 clock-stamping.** (a) Subject: timestamp source for `created_at`/`updated_at`. (b) Enumerated: `util.py` `new_common`/`bump` (single writers for all entities); `routes/repairs.py:250-266` (scan-after-parts reads part-line `created_at`); `repairs.py:36-43` (sequence_index tie-break on `created_at`); `util.py:143-144` (`sort_by_created`); `calc.py:270-271` (ranking tie-break on shop `created_at`); `sweep.py:268-269` (latest-cycle selection). All use the same logical-clock stamps — consistent. (c) None needed.
2. **§3.2 category rounding.** (a) Subject: category-score rounding. (b) Enumerated: `calc.py:83-112` (`compute_compliance_score`, only caller of the category formula; feeds `recompute_shop_score` live score and both snapshot writes at `audits.py:172` and `shops.py:226,267`). (c) Added worked examples matching the Step-7-corrected test expectations (50.0/85.0/100.0 family); verified `round_half_up(score/100, 2)` outer rounding preserves the examples.
3. **§3.2 snapshot effectiveness filter.** (a) Subject: which requirement rows count at close. (b) Enumerated: `calc.py:87-89` (filter applied identically for live and snapshot since snapshot calls the same function); `requirements.py:105-108,130-133` (`effective_from` ≥ clock at publish, so a close-time-effective revision counts; a future one doesn't). (c) Worded as "does not yet count in any category denominator" — matches filter exactly.
4. **§3.3 cross-cycle overlap.** (a) Subject: scope of the overlap rule. (b) Enumerated: `audits.py:54-61` (cycle-state gates: cycle OPEN + no active same-cycle audit) vs `audits.py:68-77` (shop-wide overlap scan including SCHEDULED/IN_PROGRESS audits on CLOSED cycles). (c) Wording explicitly preserves the existing "audits in CANCELLED/PASSED/FAILED never conflict" carve-out while noting the cross-cycle surface.
5. **§3.3 severity alias.** (a) Subject: finding request payload key. (b) Enumerated: `audits.py:185` (`f.get("finding_severity", f.get("severity"))` — the only parse site); `_refresh_audit_points`/`grade_for_audit` read the stored `finding_severity` field, unaffected. (c) Named the canonical key first and the alias second, matching the impl's precedence.
6. **§3.3 VERIFICATION transition ignores REJECTED.** (a) Subject: condition for FINDINGS_ISSUED → VERIFICATION. (b) Enumerated: `audits.py:289-295` (no OPEN actions, gate `audit.status == FINDINGS_ISSUED`); `audits.py:341-361` (REJECTED returns audit VERIFICATION → FINDINGS_ISSUED, leaving no OPEN — next submit must re-enter VERIFICATION). (c) Worded as "REJECTED does not count; its OPEN replacement is what matters" — matches both sites.
7. **§3.3 all-verified / close-PASS gates ignore REJECTED.** (a) Subject: REJECTED participation in verification-completeness and close gates. (b) Enumerated: `audits.py:328-340` (verify: all non-REJECTED VERIFIED → PASSED); `shops.py:233-238` (close PASS from CORRECTIVE_ACTION: reject if any action not in (VERIFIED, REJECTED)); `shops.py:260-264` (SUSPENDED-restore gate uses `!= "VERIFIED"` — but unreachable with a lingering REJECTED since the audit must already be PASSED to close PASS, and PASSED implies all non-REJECTED VERIFIED — consistent). (c) Wording in both spots says REJECTED is "superseded by its OPEN replacement"; consistent with sweep fail-check (§3.3 already pins OPEN/SUBMITTED past-due there).
8. **§3.6 parts editability.** (a) Subject: editable states for part-line add and remove. (b) Enumerated: `repairs.py:18` `EDITABLE_FOR_PARTS`; `repairs.py:426` (add gate); `repairs.py:471` (remove gate, same set). Both use ESTIMATE/APPROVED/IN_REPAIR. (c) Wrote one sentence covering both operations with the same state set.
9. **§3.8 ranking tie-break.** (a) Subject: candidate ordering. (b) Enumerated: `calc.py:266-272` (`rank_candidates` — shared by referral routing `referrals.py:24-37` and public locator `referrals.py:174-185`); tie-break tuple `(-score, -live_compliance_score, created_at, _seq)`. (c) Kept the original sentence verbatim and appended an observability note; explicitly preserves "id never participates."

No edits were made for pure fixture/test-layer items (WINDOW2_END leap-year arithmetic, `effective_from` clock alignment, test-setup certification of APPLICANT shops, TTL/clock race fixes, VIN length) — those trace to PRD rules already stated verbatim or to test-harness bugs with no PRD silence.

## Step 9: Complete PRD — 2026-09-30T11:05:00.000Z

The PRD_COMPLETED.md is written. Summary:

**Files:** `workspace/PRD_FINALIZED.md` (326 lines, 63,135 chars) → `workspace/PRD_COMPLETED.md` (326 lines, 66,564 chars; +3,429 chars). Both same line count (all edits were inline).

**Counts:** 14 ambiguity-pins, 3 mismatch-revisions (17 edits total).

Changes:
- §2.1 role list lead-in — insert — ambiguity — pinned that `X-User-Role` must match a known role name exactly — implementation/app.py:24
- §2.1 Anonymous role bullet — insert — ambiguity — pinned that sending `X-User-Role: Anonymous` to a non-locator endpoint yields `ERR_UNAUTHENTICATED` 401 — implementation/app.py:24
- §2.3 Pagination — revise — ambiguity — pinned non-integer/out-of-range `limit` (1..100) and negative `offset` to `ERR_INVALID_REQUEST` 400, the created_at-then-creation-sequence tie-break, and the exact `has_more` formula — implementation/util.py:102-128,143-144
- §3.1 shop registration — insert — ambiguity — pinned that APPLICANT shops are excluded from locator/referral pools by the posture filter despite `locator_hidden=false` at rest — implementation/calc.py:256
- §3.1 suspension paragraph — insert — ambiguity — pinned SUSPENDED + PASS at grade C/F stays SUSPENDED (idempotent cascade re-run) — implementation/sweep.py:110-114
- §3.1 passive expiry — revise — ambiguity — pinned "current cycle" as the shop's most recently created cycle, open or closed — implementation/sweep.py:263-285
- §3.2 attestation create — insert — ambiguity — pinned the explicit `ERR_INVALID_STATE` 409 rejection for SUSPENDED/EXPIRED/DECERTIFIED attestation and its ordering before the OCC check — implementation/routes/shops.py:290-295
- §3.2 compliance score — revise — mismatch — removed the claimed per-category round-half-up; impl rounds only the final weighted sum — implementation/calc.py:101-112
- §3.2 compliance score — revise — ambiguity — pinned TRAINING currency-factor role population to non-INACTIVE technicians, halving exactly once, and vacuous 100.0 for shops with no active technicians — implementation/calc.py:102-110
- §3.3 audit scheduling — revise — mismatch — pinned the per-cycle active-audit gate to audits of that cycle only (error `ERR_INVALID_STATE` 409); the cross-shop window-intersection rule retains `ERR_AUDIT_OVERLAP` — implementation/routes/audits.py:58-61
- §3.3 verify verdict — insert — ambiguity — pinned that the VERIFIED compensation clears the attestation's `lapse_reason` — implementation/routes/audits.py:323
- §3.4 completion lifecycle — insert — ambiguity — pinned calendar-month clamping and the list-endpoint interpretation of `status=CURRENT`/`EXPIRED` filters against the logical clock for un-swept completions — implementation/routes/technicians.py:199-226, implementation/calc.py:47-54
- §3.4 technician currency — insert — ambiguity — pinned that losing currency demotes only CURRENT → LAPSED; PROVISIONAL below 100.0 stays PROVISIONAL — implementation/calc.py:194-203
- §3.5 procedure steps — revise — mismatch — pinned step-recordable states to ESTIMATE, IN_REPAIR, QC, REWORK, CALIBRATION (PRD previously omitted ESTIMATE) — implementation/routes/repairs.py:19,326
- §3.5 sequence_index — insert — ambiguity — pinned dense 1-based reassignment across the whole order on every step record — implementation/routes/repairs.py:36-43,366
- §3.8 referral eligibility — insert — ambiguity — pinned inclusive 25-mile boundary and that the consumer ZIP centroid is the mean location of shops registered at that ZIP (unregistered ZIP → empty pool) — implementation/calc.py:58-68,262
- §3.8 locator — insert — ambiguity — pinned `radius_miles` default 25 and non-positive rejection as `ERR_INVALID_REQUEST` 400 — implementation/routes/referrals.py:178-182
- §4 endpoint table (2 rows) — insert — ambiguity — pinned `sequence_index`-ascending ordering for the two procedure-step list endpoints — implementation/routes/repairs.py:382, implementation/routes/technicians.py:273
