# Worklog — task_3140_laboratory_accreditation_inspection_proficiency_testing

## Step 1: Create task directory — 2026-09-30T03:54:00.000Z

Pre-allocated directory `./tasks/task_3140_laboratory_accreditation_inspection_proficiency_testing/` with `workspace/` verified to exist (per command-args; no new index computed).

## Step 2: Generate scaffold — 2026-09-30T05:05:04.000Z

Done. All three scaffold artifacts are written and pass `scaffold_lint.py` with a clean verdict.

## What was generated

Task directory: `/home/ubuntu/github/CodingPRD/tasks/task_3140_laboratory_accreditation_inspection_proficiency_testing/`

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys):
- **Complexity profile**: compliance/audit primary + posture-driven gating secondary; flat topology; cyclic state machines; segregation-of-duties role model; layers: OCC, cascading side effects, scheduled actions, derived-field reconciliation
- **15 entities** (Laboratory, InspectorProfile, DisciplineEnrollment, TestingSection, PTSubscription, PTShipment, PTResult, PTInvestigation, InspectionCycle, TeamAssignment, InspectionFinding, PersonnelRecord, CompetencyAssessment, MethodValidation, ChecklistEditionSummary)
- **11 state machines** — notably: cyclic InspectionCycle (DECIDED → APPEALED → INTERIM_SELF_INSPECTION → RE_DECIDED → APPEALED, capped at 2 appeals), cyclic PersonnelRecord (QUALIFIED ⇄ COMPETENCY_REVIEW → DISQUALIFIED at 2 consecutive failures), cascaded Laboratory/Enrollment/Inspector probation chain
- **1 OCC concurrency rule** (`section-assign-stale-enrollment`, 412 on `expected_enrollment_version`)
- **9 calculations** including the pinned dual PT standing variants (per-event vs rolling window), round-then-sum competency composite, weighted deficiency burden, dual provisional-vs-final accreditation decision, calendar-vs-business-day response deadlines
- **72 endpoints**, **49 error codes**, **5 roles** (LaboratoryDirector entity-backed by Laboratory; Inspector entity-backed by InspectorProfile; SoD rule: citing inspector cannot accept own citation's response)
- Logical clock endpoint with mandatory `2026-09-01T00:00:00Z` startup default that fires shipment closure, finding escalation, and personnel competency-expiry transitions

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rules × 2 instances = 18, all with structured `setup_api_calls`/`trigger`/`assert` recipes; formula-derived values pre-computed as literals (e.g. composite 87.18 round-then-sum vs 87.17 sum-then-round; event score boundary 80.0 inclusive; LEVEL_2 Saturday-issue deadline 2026-09-18T23:59:59Z).

**SCAFFOLD_CORNER_DESIGN.yaml**: 33 instances across entities / state_machines / calculations / validations / endpoints / errors / roles sections.

**Lint verdict**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (694 calls scanned, 18 §1.8 + 33 §1.9 instances.)

Note: the directory also contains a pre-existing `worklog.md` and empty `workspace/` from the pipeline harness; I did not touch them.

## Step 3: Copy shared files — 2026-09-30T05:05:24.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T05:11:52.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3140_laboratory_accreditation_inspection_proficiency_testing/workspace/PRD.md` (ends at §5, no audit footer). The two forbidden scaffold files were never opened.

**Structure**: §1 introduction (2 paragraphs, business-context angle); §2 with 11 subsections including the domain-derived 2.4 (logical clock), 2.6 (cascading consistency), 2.8 (validation priority ordering), 2.9 (OCC on `expected_enrollment_version`), 2.10 (pinned round-then-sum rounding), 2.11 (half-open vs closed interval semantics); §3 with 7 lifecycle-grouped subsections; §4 endpoint table (4 columns, 70 endpoints); §5 error table (2 columns, 53 error IDs).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 62 required, 62 present, 0 missing
- endpoints[].request_body inputs (incl. current_utc, decision, replacement_inspector_id,
  expected_enrollment_version): all present, 0 missing
- endpoints[].query_params (limit, offset, affiliated_laboratory_id, laboratory_id, enrollment_id,
  subscription_id, shipment_id, inspection_cycle_id, inspector_id, section_id,
  cited_by_inspector_id, personnel_id): all present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: expressed as explicit 9-step ordered list in §2.8
- concurrency_rules[]: 1 checked, 1 expressed — write_endpoint (assign-checklist), occ_field
  expected_enrollment_version, ERR_STALE_VERSION / HTTP 412 all named in §2.9 + §3.1
- state_machines[].transitions: 30 checked across 10 state machines, all from/to states,
  preconditions (paired with error ids), and side effects expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed in prose — pt_event_score dual threshold (>=80.0
  boundary inclusive), per-event vs rolling standing (incl. U,U,S divergence), deficiency burden
  (4/2 x critical 2/1), provisional_decision tiers (0 / <=6 / >6), competency round-then-sum
  (4dp per element, 2dp composite, 85.0/70 thresholds), LEVEL_1 14-calendar vs LEVEL_2 5-business-day
  deadlines, 4-part posture, business-day helper
- validations[] conditions: all matchable to error_id in §2/§3 narrative; all 53 error ids
  appear in §1–§4 prose, not only in §5
- endpoints[].side_effects / applies_to: all expressed (incl. deadline closure = scored absence,
  no grading cascade; reinstate/revoke investigation and 180-day gates; overlap semantics
  half-open for cycles vs closed for shipments)
- entities[].fields[] structured content: defaults, nullability, enum values, computed-source
  fields (active_discipline_count, event_score, composite_score, posture_ready, burden,
  provisional/final decision, retired_count) all reconstructible
- sibling-branch symmetry: resolve from 3 source states, cease from 2, decide/re-decide gate
  rules, CLEAR/CONFLICTED/REPLACED terminal triad rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 481
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verified byte-identical to the canonical `section-2.2-response-structure.md`.

## Step 5: Generate unit tests — 2026-09-30T05:32:11.000Z

Complete. All 18 difficulty instances have ≥2 tests each, all 33 corner instances have ≥1 test, all 69 tests collect cleanly, every docstring ends with exactly one verbatim `Design:` tag resolving to a real instance, and every test carries a verbatim PRD citation (grep-verified).

## Report

**Generated for task_3140_laboratory_accreditation_inspection_proficiency_testing:**

**`test_helpers/` (8 files):**
- `types.py` — status enums (12) + TypedDicts (16 entities)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~45 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — full 54-error catalog + HTTP status map, registered with `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions (common fields, enum domains, timestamps)
- `factories.py` — payload factories with collision-free unique counters
- `constants.py` — domain thresholds (PT pass 80/80.0, composite 85.0/element 70, r² 0.95/CV 10.0, burden weights 4/2 × critical 2, CONDITIONAL band ≤6, deadlines 14d/5 business days, appeal 30d/limit 2, revoke 180d, reciprocal 365d)
- `test_users.py` — shared header constants for opaque roles + `make_director_headers(lab_id)` / `make_inspector_headers(inspector_id)` builders for the two entity-backed roles
- `fixtures.py` — composite builders: `setup_lab_with_active_enrollment`, `setup_posture_ready_lab`, `setup_conducted_cycle`, `setup_findings_issued`, `respond_and_accept`, `setup_pt_active_enrollment`, `setup_single_unsatisfactory_event`, `setup_rolling_unsatisfactory_enrollment`, `setup_decided_cycle`, etc., all threading entity-backed identity and using `get_success_data`

**`test_suite/` (9 files, 69 tests):**
- test_01 laboratories, test_02 enrollments/checklists, test_03 PT program, test_04 PT investigations, test_05 inspection cycles/team screening, test_06 findings/burden/deadlines, test_07 personnel/methods, test_08 decisions/appeals/probation, test_09 RBAC/auth

**Coverage audit (verified programmatically):** 18/18 difficulty instances with exactly ≥2 tagged tests each; 33/33 non-stub corner instances with ≥1 tagged test (no `excluded_because` stubs exist in this task); all tags resolve to real yaml instance names; every docstring contains a PRD quote surviving literal grep of `workspace/PRD.md`; no skip/xfail markers; no scaffold references in code.

**Notable translation decisions:**
- `pt_standing_per_event_vs_rolling_uus_sequence`: asserted only the PRD-pinned outcomes (per-event SATISFACTORY / rolling UNSATISFACTORY / streak 1 / 2 investigations); dropped the yaml's "second investigation OPEN" status assertion because PRD is silent on how investigation triggering interacts with an already-OPEN investigation (two-reader ambiguity).
- `inspection_cycle_window_half_open_overlap`: split the third assertion (disjoint window) into the second tagged test to keep the first test isolated.
- `test_finding_response_deadline_passed_after_due` asserts a 409 without pinning the error_id, because at due+1s the clock has also escalated the finding (state error vs deadline error — PRD's priority list resolves this, but the twin sibling test pins the exact `ERR_RESPONSE_DEADLINE_PASSED` path).
- OCC test exercises the stale path while enrollment is still WAITING (version+1 mismatch), which is the uniquely derivable interpretation of the corner instance.

## Step 6: Generate implementation — 2026-09-30T06:23:26.000Z

Implementation complete. All files live in `/home/ubuntu/github/CodingPRD/tasks/task_3140_laboratory_accreditation_inspection_proficiency_testing/workspace/implementation/`:

**Files**
- `start.sh` — executable launcher; guards `pip install` behind an `import flask` check, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — entry point, error handlers, and routes for clock, laboratories, inspector profiles, enrollments, sections/checklist assignment (with the `expected_enrollment_version` OCC rule, 412 `ERR_STALE_VERSION`, first-assignment WAITING→ACTIVE + APPLIED→ENROLLED cascade), checklist editions (retirement invalidation + `retired_count`)
- `routes_pt.py` — PT subscriptions/shipments/results/investigations: atomic grading (half-up 1-dp `event_score`, dual aggregate+critical thresholds), per-event/rolling/streak standings over GRADED-only history, auto-investigation creation with `PER_EVENT`/`ROLLING`/`BOTH` trigger, shipment closed-interval overlap, 5-day collection window, investigation state machine with suspend/resolve/cease cascades
- `routes_inspection.py` — cycles (half-open window overlap), team assembly (suspended/specialty/self-inspection/365-day reciprocal-conflict screening, flag/replace), posture gate, findings with burden (4/2 × critical multiplier), issue-findings (LEVEL_1 +14 calendar days, LEVEL_2 5th business day at 23:59:59Z, provisional decision bands 0/≤6/>6), decide/re-decide with burden gate and lab cascade, appeal (30-day window, count < 2) / self-inspect loop
- `routes_personnel.py` — personnel, competency assessments (pinned round-then-sum composite: per-element /600 rounded half-up to 4 dp, summed, ×100 rounded to 2 dp; pass ≥85.0 and every element ≥70; 365-day validity; streak→COMPETENCY_REVIEW/DISQUALIFIED), method validations with 0.95/10.0 thresholds
- `services.py` — derived-field recomputation (active_discipline_count, standings, burden, posture), probation/reinstate cascades, business-day helper, clock-driven transitions (shipment deadline close, finding escalation, competency expiry)
- `store.py`, `helpers.py`, `util.py`, `auth.py`, `errors.py` — in-memory dicts (empty at boot, no seeding), logical clock fixed at 2026-09-01T00:00:00Z until set, envelope helpers matching scaffold §1.0 exactly, X-User-ID/X-User-Role auth

**Verification** — two comprehensive smoke suites (60+ assertions) run against fresh processes, one booted via `bash start.sh`, covering: auth 401/403, duplicate CLIA/enrollment, OCC stale version, activation cascade, PT grading boundary (exactly 80.0 SATISFACTORY, critical-fail override), U/U/S healing divergence between per-event and rolling standings, investigation suspension/resolution/cessation, checklist retirement + CEASED-enrollment reassignment block, cycle window overlap (touching allowed), team screening incl. reciprocal conflict, segregation of duties, burden-gated decisions, appeal limit, 180-day revoke gate, clock-driven escalation/deadline closure/competency expiry. All pass; all smoke servers and temp files cleaned up.

## Step 7: Run tests and iterate — 2026-09-30T06:50:00.000Z

All 8 rounds: 69/69. Clean sweep.

## Summary

**Iterations run:** 3 sweeps of 8 parallel rounds each (55/69 failing → 14 → 3 → 0).

**Tests deleted:** none. No PRD-silent or non-derivable tests needed removal; every failure resolved as a test-artifact or implementation fix.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `assign_checklist_to_section()`: now re-reads the parent enrollment and auto-supplies `expected_enrollment_version` when it is `WAITING` (PRD §2.9 mandates the OCC field on WAITING-enrollment assignment; the fixture previously omitted it, causing 41 setup-time `ERR_STALE_VERSION` failures).
- `fixtures.py` — `setup_findings_issued()`: added the missing `item_code` parameter and forwarded it to `cite_finding` (4 tests passed this kwarg; fixture rejected it).

**Fixes applied to `test_suite/`:**
- `test_04_pt_investigations.py` — `_uus_history()`: close each shipment before creating the next (PRD §3.2 closed-interval overlap rule made the old back-to-back shipment creation correctly rejectable). Also corrected `unsuccessful_event_streak` assertion from 1 to 0 — PRD §3.2 verbatim: streak "resets to zero on a satisfactory event", and the sequence ends in S.
- `test_05_inspection_cycles.py` — removed a duplicate CHM/2026 checklist-edition registration in `test_screen_team_blocked_by_conflicted_assignment`; gave the second lab a distinct edition code (MIC) in `test_finding_cite_on_section_of_another_laboratory_rejected`; relaxed the screen-team block assertion to `validate_error_is_one_of([ERR_CONFLICTED_INSPECTOR, ERR_TEAM_INCOMPLETE])` (both §3.4 rules fail simultaneously; PRD names no precedence between them).
- `test_06_findings_and_burden.py` — distinct checklist code (MIC) for the second conducted cycle in `test_level2_business_day_deadline_skips_weekend`; in `test_finding_response_deadline_inclusive_endpoint_boundary`, relaxed the post-deadline rejection to `one_of([ERR_RESPONSE_DEADLINE_PASSED, ERR_INVALID_STATE])` (§2.4 clock escalation races §2.8 priority levels 4 vs 7 — ERROR PRECEDENCE SILENCE) and fixed the trailing finding-status assertion from `CITED` to `ESCALATED` per PRD §2.4.
- `test_08_decisions_appeals_probation.py` — dropped the two laboratory-status assertions (`lab2`/`lab3` == ACCREDITED) in `test_inspection_cycle_appeal_self_inspection_redecision_loop`: PRD §3.7's ACCREDITED cascade is pinned only for ENROLLED laboratories ("moves an ENROLLED laboratory to ACCREDITED"), and "identical laboratory cascade" on re-decision does not uniquely determine the PROBATION→ACCREDITED hop (two-reader ambiguity). All cycle-level assertions retained.

**Fixes applied to `implementation/`:**
- `util.py` — added `fmt_instant()` (omits `.000` fractional for whole-second instants); the PRD pins the logical clock as reading "exactly 2026-09-01T00:00:00Z", so clock-derived stamps emit in that second-precision form.
- `routes_pt.py`, `routes_personnel.py`, `routes_inspection.py`, `app.py` — switched clock-derived domain stamps (`shipped_at`, `due_at`, `collected_at`, `assessed_at`, `valid_until`, `response_due_at`, `scheduled_start/end`, clock-set `current_utc`) to `fmt_instant`; kept `fmt_ts` (3 fractional digits) for PRD-mandated `created_at`/`updated_at`/`api_request_timestamp`.
- `routes_inspection.py` — `conduct_cycle`: reordered the window check before the posture gate, per PRD §2.8 priority ((7) temporal windows precede (8) gate checks), so an out-of-window conduct attempt on an unready cycle correctly reports `ERR_INSPECTION_WINDOW_NOT_OPEN`.

Final state: 8/8 parallel rounds, 69/69 tests passing in every round.

## Step 8: Finalize PRD — 2026-09-30T06:58:25.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_3140_laboratory_accreditation_inspection_proficiency_testing/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / %-delta:** PRD.md 327 lines → PRD_FINALIZED.md 329 lines (+2 lines, +0.61%; five hunks, all minimal inline edits, no new sections).

**Changes (one bullet each):**
- §2.4 — insert — new paragraph pinning serialization of logical-clock-derived and client-supplied instants (`shipped_at`, `due_at`, `collected_at`, `assessed_at`, `valid_until`, `response_due_at`, `scheduled_start`, `scheduled_end`, clock-set `current_utc` echo) as second-precision ISO 8601 with the fractional part omitted on whole seconds, explicitly distinct from `created_at`/`updated_at`/`api_request_timestamp` (always 3 fractional digits) — impl `util.py:22-35` (fmt_instant), call sites `routes_pt.py:115-116,227`, `routes_inspection.py:55-56,164`, `routes_personnel.py:147,151`, `app.py:71`.
- §2.8 — insert — closing sentence: when both conduct gates fail, `ERR_INSPECTION_WINDOW_NOT_OPEN` (priority 7) surfaces before `ERR_CYCLE_NOT_READY` (priority 8) — impl `routes_inspection.py:127-134`.
- §3.4 — insert — one sentence: when the screen-team lead/pending condition and a lingering `CONFLICTED` assignment fail simultaneously, `ERR_TEAM_INCOMPLETE` is returned first — impl `routes_inspection.py:98-111`.
- §3.6 — insert — one sentence: a response arriving after `response_due_at` may surface either `ERR_INVALID_STATE` (finding already ESCALATED by the atomic clock-advance escalation) or `ERR_RESPONSE_DEADLINE_PASSED`; both conformant — impl `routes_inspection.py:482-502`, `services.py:237-243`.
- §3.7 — revise — ACCREDITED decision cascade now spelled out: ENROLLED→ACCREDITED, unchanged in every other state (explicitly a no-op for APPLIED and PROBATION); re-decision inherits this via the existing "identical laboratory cascade" sentence — impl `services.py:64-71`, `routes_inspection.py:179-221`.

**Step 7 items judged to need no PRD edit:** fixture `expected_enrollment_version` auto-supply (PRD §2.9 already mandates it — pure fixture bug); fixture `item_code` kwarg (pure fixture bug); `_uus_history` shipment-close sequencing (PRD §3.2 already pins closed-interval overlap — test bug); `unsuccessful_event_streak` 1→0 (PRD §3.2 already verbatim); distinct checklist codes per family (PRD §3.1 already pins per-family uniqueness).

**Per-edit pre-edit search log:**
1. **§2.4 timestamp edit** — (a) subject: timestamp serialization of clock-derived fields. (b) enumerated: `grep -n "fmt_instant\|fmt_ts"` across all impl files; read `util.py` (both formatters), `helpers.py:50-63` (new_record uses fmt_ts for created_at/updated_at), `util.py:61-78` (api_request_timestamp uses fmt_ts), all fmt_instant call sites listed above. (c) wording narrowed from a broad "clock-derived fields omit .000" claim to an explicit field whitelist plus explicit carve-out of the fmt_ts fields, since `created_at` is also logical-clock-derived but keeps 3 fractional digits.
2. **§2.8 precedence edit** — (a) subject: ERR_INSPECTION_WINDOW_NOT_OPEN vs ERR_CYCLE_NOT_READY order. (b) enumerated: `routes_inspection.py:116-137` (conduct_cycle is the sole raiser of either error; order state→window→posture); §3.6 prose lists gates without order (consistent); `grep` for both error ids confirmed no other raiser. (c) none.
3. **§3.4 screen-team edit** — (a) subject: ERR_TEAM_INCOMPLETE vs ERR_CONFLICTED_INSPECTOR order. (b) enumerated: `routes_inspection.py:86-114` (sole raiser of both; TEAM_INCOMPLETE branch lines 98-107 precedes CONFLICTED check lines 108-111); grep confirmed no other endpoint raises either. (c) none.
4. **§3.6 deadline-race edit** — (a) subject: respond_finding check order vs clock escalation. (b) enumerated: `routes_inspection.py:473-507` (finding-state check line 482 before deadline check lines 499-502; sole raiser of ERR_RESPONSE_DEADLINE_PASSED), `services.py:227-243` (fire_clock_transitions), `app.py:62-71` (clock-set runs transitions inside the same store lock). (c) wording kept deliberately two-valued ("either ... both conformant") rather than asserting one order, because the impl's outcome depends on whether a clock-set intervened; both branches are impl-exhibited.
5. **§3.7 cascade edit** — (a) subject: laboratory status map under ACCREDITED decision. (b) enumerated: `services.py:64-71` (`apply_lab_decision` — sole cascade implementation), `routes_inspection.py:179-221` (`_do_decide` shared by `decide` and `re-decide`, so both paths behave identically); revocation/reinstate paths (`app.py:112-172`) verified untouched by the wording. (c) wording scoped to "accreditation_status unchanged in every other state" rather than "no-op", since a DENIED decision on a PROBATION laboratory does refresh fields — the sentence only makes claims about the ACCREDITED branch.

## Step 9: Complete PRD scan — 2026-09-30T07:12:24.000Z

Done. PRD_COMPLETED.md written at /home/ubuntu/github/CodingPRD/tasks/task_3140_laboratory_accreditation_inspection_proficiency_testing/workspace/PRD_COMPLETED.md.

Summary:
- Source: PRD_FINALIZED.md (329 lines, 53,768 chars) → PRD_COMPLETED.md (331 lines, 56,004 chars; +2 lines, +2,236 chars).
- Counts: 16 ambiguity-pins, 1 mismatch-revision (17 changed hunks total; all inserts/revisions, no new sections).

Changes:
- §2.5 Common Resource Properties — revise — ambiguity — pin `version` initialized to 1 at creation — implementation/helpers.py:59.
- §3.1 Enrollments — insert — ambiguity — pin director ownership check (`ERR_UNAUTHORIZED` when `X-User-ID != laboratory_id`) and unknown-discipline `ERR_INVALID_REQUEST` — implementation/app.py:242-249.
- §3.1 Sections — insert — ambiguity — pin owning-director check on section creation (`ERR_UNAUTHORIZED`) — implementation/app.py:310-313.
- §3.2 PT subscriptions — insert — ambiguity — pin owning-director check and duplicate analyte-name rejection (`ERR_INVALID_REQUEST`) — implementation/routes_pt.py:35-40, 55-56.
- §3.2 Result submission guards — revise — ambiguity — reorder guard list to impl order (shipment OPEN → collection window → enrollment ACTIVE → submission deadline → coverage) and pin duplicate analyte-score names rejected — implementation/routes_pt.py:167-209.
- §3.3 Require corrective action — revise — ambiguity — pin enrollment suspension cascade applies only when the enrollment is `ACTIVE` — implementation/routes_pt.py:323-325.
- §3.3 Resolve — revise — ambiguity — pin reactivation cascade only when the enrollment stands `SUSPENDED` — implementation/routes_pt.py:347-348.
- §3.3 Cease testing — revise — ambiguity — pin cessation cascade only from `ACTIVE`/`SUSPENDED` — implementation/routes_pt.py:371-372.
- §3.4 Cycle creation — revise — mismatch — `posture_ready` at creation is computed live from the laboratory's current state (not always false) — implementation/routes_inspection.py:58.
- §3.4 Reciprocal-conflict check — insert — ambiguity — pin the 365-day look-back window is inclusive of the exact cutoff and checks evaluate the assignment's inspector regardless of acting user — implementation/routes_inspection.py:338-344.
- §3.5 Competency assessments — insert — ambiguity — pin owning-director check (`ERR_UNAUTHORIZED`) — implementation/routes_personnel.py:108-114.
- §3.5 Assessment-driven personnel transitions — revise — ambiguity — pin passing assessment qualifies from any status except `DISQUALIFIED` (incl. still-`PROVISIONAL`), and a first failure leaves `PROVISIONAL` unchanged — implementation/routes_personnel.py:159-174.
- §3.5 Method validations — insert — ambiguity — pin owning-director checks on registration and submit (`ERR_UNAUTHORIZED`) — implementation/routes_personnel.py:227-232, 268-274.
- §3.6 Finding respond — insert — ambiguity — pin check ordering: state (`ERR_INVALID_STATE`) → ownership (`ERR_UNAUTHORIZED`) → cycle `FINDINGS_ISSUED` → deadline — implementation/routes_inspection.py:482-502.
- §3.7 Appeal — insert — ambiguity — pin owning-director check and inclusive 30-day window boundary — implementation/routes_inspection.py:231-238.
- §3.7 Self-inspect — insert — ambiguity — pin owning-director check (`ERR_UNAUTHORIZED`) — implementation/routes_inspection.py:253-258.
- §3.7 Decision cascade — revise — ambiguity — pin `DENIED` applies the probation cascade only from `ENROLLED`/`ACCREDITED`; `APPLIED`/`PROBATION` left unchanged — implementation/services.py:69-71.
- §3.7 Revocation — insert — ambiguity — pin `ERR_REVOKE_TOO_EARLY` also when no `DENIED` decision exists for the laboratory — implementation/app.py:166-169.
- §4 Endpoint table — insert — ambiguity — note that GET /competency-assessments/{id} 404s with generic `ERR_NOT_FOUND` (no dedicated identifier) — implementation/routes_personnel.py:192-194.

Notable items deliberately left unpinned (PRD prose already matches impl): role-binding rules, the clock transitions and timestamp-format rules, OCC/`expected_enrollment_version` semantics, PT grading/standing math, burden weights, provisional-decision bands, and business-day deadline computation.
