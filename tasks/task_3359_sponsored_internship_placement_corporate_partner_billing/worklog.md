# Worklog — task_3359_sponsored_internship_placement_corporate_partner_billing

## Step 1: Create task directory — 2026-10-01T08:34:04.282Z

Task directory `./tasks/task_3359_sponsored_internship_placement_corporate_partner_billing/` was pre-allocated by the caller with an empty `workspace/` inside; verified present and empty. No new index computed, no other `task_*` directory created. Scenario: Sponsored Internship Placement & Corporate Partner Billing (Year Up).

## Step 2: Generate scaffold — 2026-10-01T09:35:00.000Z

First spawn died on the 32000-output-token cap (single-Write of a whole scaffold file); respawned with a forced chunked-write plan (part files + `cat`), which succeeded.

Scaffold generation complete for `task_3359_sponsored_internship_placement_corporate_partner_billing`.

### Deliverables

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3359_sponsored_internship_placement_corporate_partner_billing/SCAFFOLD.yaml` | 1688 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3359_sponsored_internship_placement_corporate_partner_billing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1563 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3359_sponsored_internship_placement_corporate_partner_billing/SCAFFOLD_CORNER_DESIGN.yaml` | 1547 |

Directory now holds only the three artifacts plus the caller's pre-existing `worklog.md` / empty `workspace/`; all `_part_*` temp files deleted.

### Counts

- **11 entities** (Partner, Student, Cohort, Agreement, InternshipPlacement, InterviewRound, StipendStatement, SatisfactionRecord, OutcomeCheckpoint, Invoice, CreditGrant), 27 validations, **39 endpoints**, **25 error codes**, 4 roles (2 entity_backed, 2 opaque), 2 OCC concurrency rules, 7 calculations.
- **6 state machines** (Student, InternshipPlacement, Agreement, StipendStatement, Invoice, CreditGrant) — placement interview machine is cyclic (INTERVIEW_SCHEDULED↔MATCHED, INTERVIEWED→INTERVIEW_SCHEDULED), Invoice has dual compensating exits from OVERDUE, Agreement is a DRAFT→ACTIVE⇄FULFILLED cycle.
- **Difficulty: 9 rules / 19 instances** (2 each; 3 for `priority_pair_validation_conflict`), covering dual-variant placement-fee and L&D-stipend readings, per-term-rounding satisfaction composite, circular cohort-points evaluation order, a 4-hop graduation cascade, three distinct error-category priority pairs, exact 0.60 attendance-floor and interview-round-count boundaries, half-open minute slots vs inclusive day periods, and two different conserved quantities.
- **Corner: 8 sections / 27 active instances + 5 `excluded_because` stubs.**

### Lint

`python3 scaffold_lint.py <task_dir>` — final verdict verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (608 calls scanned, 0 violations.)

Findings fixed along the way: the `Invoice` entity was missing entirely (8 unresolvable captures); 11 FK reverse-reachability gaps (added `GET /placements/{id}`, `GET /invoices/{id}`, `GET /partners/{id}/agreements`, `GET /students/{id}/stipend-statements|outcome-checkpoints|credit-grants`, `GET /placements/{id}/satisfaction-records`; dropped 6 list/summary endpoints to keep the surface bounded); dropped the redundant `SatisfactionRecord.partner_id` FK; set `api_prefix: ""` so §1.5 paths and the design files' call paths agree.

Judgment calls worth flagging: the endpoint count landed at **39**, not "well under 40" — the §1.1 FK reverse-reachability rule (a hard lint check) sets a floor of ~11 read endpoints for 10 FK fields, so the subagent cut feature surface (student summary endpoint, wage-growth/pipeline calculations, agreement list, withdrawal transition) to stay under the ceiling rather than shrink the FK model. Two orphaned calculations and the `WITHDRAWN` state were removed for enum/trigger closure rather than left dangling.

**Orchestrator verification (independent of the hand-back):** all three files present with the reported line counts; all three parse as YAML; top-level keys are `scaffold_difficulty_design` / `scaffold_corner_design` only in their respective files and absent from `SCAFFOLD.yaml`; `scaffold_lint.py` re-run by the orchestrator returns the same clean verdict (19 §1.8 instances, 27 §1.9 instances, 608 calls). Noted risk: 39 endpoints is close to the ~40 ceiling above which Step 6 (implementation-gen) has historically degraded.

## Step 3: Copy shared files — 2026-10-01T09:36:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). Orchestrator also independently parsed SCAFFOLD.yaml: 11 entities, 39 endpoints, 25 errors, 7 calculations, 27 validations, 6 state machines, roles = [Anonymous, ProgramStaff, Partner, Student].

## Step 4: Generate PRD — 2026-10-01T09:45:00.000Z

PRD generated and verified.

### Output

`workspace/PRD.md` — **299 lines** (60,616 bytes). Built as four part files (`_prd_a`…`_prd_d`) in separate messages, then `cat`-ed together and the parts deleted. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task was read.

### Sections

- **§1 Introduction** — 3 paragraphs (program arc, commercial engine, time/OCC constraints)
- **§2 Global Specifications** — 11 domain-derived subsections: 2.1 Actors/Identity/RBAC, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, diff-verified), 2.3 Pagination & List Ordering, 2.4 Common Resource Properties, 2.5 Request Evaluation Order, 2.6 The Logical Clock, 2.7 Monetary Values/Ratios/Rounding, 2.8 OCC on Partner Writes, 2.9 Nested Retrieval & Referential Integrity, 2.10 Partner Ledger Reconciliation, 2.11 Program Eligibility Gates
- **§3 Business Logic** — 8 subsections: applicant intake/selection, cohort enrollment + L&D, partner onboarding/agreement activation, matching/interviews/offers, stipend administration, satisfaction/completion, fee billing/receivables, graduation/credit/outcomes
- **§4** 4-column endpoint table, **§5** 2-column error table

### Coverage

39 endpoints · 11 entities (82 fields) · 25 errors · 6 state machines (Student, InternshipPlacement, Agreement, StipendStatement, Invoice, CreditGrant — 30 transitions) · 7 calculations · 2 concurrency rules · 27 priority-ordered validations · 4 roles.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 82 required, 82 present, 0 missing
- endpoints[].request_body/input/query_params: 55 required, 55 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed, 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 39 checked (25 side-effect lists), 39 expressed, 0 missing
- entities[].fields[] structured content: 82 checked, 82 reconstructible, 0 missing
- sibling-branch symmetry: 5 groups checked (6 sibling terminations, 3 interview-outcome branches, 2 invoice payment from-states, 2 stipend phase variants, 4 partner-fiscal gates), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 527
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
Also verified mechanically: all 25 error IDs appear before §5, all state values and all enum members appear as exact backticked strings, §4 rows match the scaffold's method/path/role triples 39/39, §5 rows match error ID + status 25/25, and PRD.md ends at §5 with no audit footer.

### Under-determined points — interpretations chosen (test generator + implementer read only the PRD)

1. **`api_prefix: ""`** — stated the API is served at the server root with no path prefix.
2. **Age gate upper bound.** `errors[]` defines `ERR_AGE_INELIGIBLE` only for "below 18", but the `APPLIED → ELIGIBLE` precondition is 18 ≤ age ≤ 24. Per the state machine's note that a failing criterion reports its own error, an over-24 applicant decided `ELIGIBLE` is rejected with `ERR_AGE_INELIGIBLE` (422). Stated in §2.5/§2.11/§3.1.
3. **Wrong role for a valid operation.** No scaffold error covers "role not permitted". Mapped to `ERR_UNAUTHORIZED` (401), reserving `ERR_NOT_OWNER` (403) for the row-level ownership check.
4. **Enrollment past `cohort.graduation_date`.** Precondition exists but no error is nominated; mapped to `ERR_PARENT_STATE_CONFLICT` (409), the same error the cohort-status precondition uses.
5. **`CreditGrant` GRANTED preconditions** (student phase `INTERNSHIP`/`COMPLETED`; logical clock ≤ `graduation_at` + 365 days). No error nominated; mapped both to `ERR_PARENT_STATE_CONFLICT` (409).
6. **`ERR_INVALID_STATE` vs `ERR_ALREADY_TERMINAL`.** Priorities 6 and 7 both literally match a terminal row, so a literal reading makes priority 7 dead code. Defined check 6 as applying to non-terminal rows only, so terminal rows report `ERR_ALREADY_TERMINAL`. Written explicitly into §2.5.
7. **Interview scheduling with rounds exhausted.** Split by state: a placement back at `MATCHED` after its final failed round → `ERR_INTERVIEW_ROUNDS_EXHAUSTED` (409); one still at `INTERVIEWED` is caught by the earlier state check → `ERR_INVALID_STATE` (409), honoring the declared priority order.
8. **Interview slot overlap** is undefined in the scaffold; defined as two rounds whose `scheduled_for` + `duration_minutes` intervals share any instant with the same `supervisor_name`, across placements.
9. **Stipend period overlap** is undefined; defined as two inclusive `period_start`…`period_end` ranges sharing at least one calendar day, same student and phase, status `PENDING` or `PAID`.
10. **`supervisor_name` copied at `MATCHED`** — "the sponsoring agreement's partner legal name" resolved to `Partner.legal_name`.
11. **`CreditGrant.tuition_credit_cents`** — the scaffold names only the aggregate in the formula. Specified the grant row's own value as its per-grant amount (credit_hours × 12,500, capped at 500,000) and described the student-level total separately.
12. **`PATCH /credit-grants/{id}`** is the endpoint realizing the state machine's `/grants` and `/voids` triggers; described as advancing `PENDING → GRANTED` or `PENDING → VOID` from a `status` body field with an optional `reason`.
13. **Partner `INACTIVE`** — terminal and blocks activation, but no scaffold transition produces it; stated that no automatic rule reaches it.
14. **`hours_per_week`** — default 20 combined with the acceptance floor of 20 means the effective minimum is 20; stated both the default and the floor.

**Orchestrator verification:** `workspace/PRD.md` present at 299 lines / 60,616 bytes; section headers §1–§5 all present (2.1–2.11, 3.1–3.8); 25 `ERR_*` rows in the §5 table; no stray `_prd_*` part files remain in `workspace/`.

## Step 5: Generate unit tests — 2026-10-01T10:15:24.917Z

**Note: the Step 5 subagent was killed mid-flight by a host-session interruption; its final report was lost.** Per the "a lost subagent report is not a lost artifact" rule, the orchestrator verified the on-disk artifact against source rather than blindly re-running the step. Verification found the artifact complete and internally consistent:

- `test_helpers/`: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `scenarios.py` (10 modules). No `_part_*`/tmp files anywhere.
- `test_suite/`: `conftest.py` + 16 test modules (`test_01`…`test_16`), newest source mtime 10:07; a `pytest --collect-only` run by the dead subagent at ~10:08 left `__pycache__`.
- **63 test functions, 63 `Design:` docstring tags — 1:1, zero untagged, zero dual-tagged.**
- Orchestrator re-ran `python3 -m pytest test_suite --collect-only -q` → **63 tests collected in 0.21s, zero import/collection errors** (this is the only check that catches the dangling-import failure mode a dead generation subagent can leave).
- Tag↔index cross-check: **0 unresolved tags**; **0 `excluded_because` stubs carry a test**.

### Instance coverage: 44 of 46 active instances

Design index contains 19 difficulty instances (all active) + 32 corner instances (27 active, 5 stubs) = **46 active instances**. Two active instances have no test; both were adjudicated by the orchestrator against the PRD and both are **legitimate gaps that stay gaps**:

1. **`Corner/state_machines/second_stipend_payment_returns_invalid_state`** — the design index asserts `ERR_INVALID_STATE` when a `PAID` statement is paid again. The PRD contradicts it verbatim, twice: *"A statement that has already reached `PAID` cannot be paid again — a second attempt is refused with `ERR_ALREADY_TERMINAL` (409)."* and *"`PAID` and `VOID` are both terminal for a statement, so a paid statement cannot be voided and a voided one cannot be paid, each attempt being refused with `ERR_ALREADY_TERMINAL` (409)."* Per Key Principle 1 the PRD wins; a faithful PRD-only implementer would return `ERR_ALREADY_TERMINAL`, so the instance is not uniquely derivable and was correctly skipped. **This is a scaffold↔PRD semantic disagreement and is reported as a doc-generator/scaffold bug** (the corner index contradicts §3.5 and §2.5's priority-6/7 resolution).
2. **`Corner/cross_cutting_layers/invoice_list_excludes_void_rows_by_default`** — asserts an unfiltered `GET /invoices` omits `VOID` rows. PRD §4 line 258 says only *"List invoices filtered by partner, placement or status"*; §2.3 specifies ordering and pagination but no default exclusion. Classic **DEFAULT-VALUE SILENCE** — a faithful reader could legitimately include `VOID` rows in an unfiltered listing. Correctly skipped.

The remaining 63 tests cover the other 44 active instances (some instances carry more than one test function; every tag resolves). No test was deleted or weakened by the orchestrator.

**Step 5 outcome: COMPLETE (recovered from interruption, not regenerated).**

## Step 6: Generate implementation — 2026-10-01T10:42:33.936Z

Implementation complete and smoke-verified.

### Files written under `workspace/implementation/` (33 files, 2868 lines)

| File | Lines | File | Lines |
|---|---|---|---|
| `start.sh` (0755) | 13 | `routes/placements.py` | 151 |
| `requirements.txt` | 1 | `routes/placement_actions.py` | 222 |
| `app.py` | 77 | `routes/interviews.py` | 173 |
| `db.py` | 77 | `routes/stipends.py` | 115 |
| `errors.py` | 41 | `routes/stipend_actions.py` | 47 |
| `timeutil.py` | 107 | `routes/satisfaction.py` | 65 |
| `validators.py` | 99 | `routes/invoices.py` | 145 |
| `response.py` | 105 | `routes/outcomes.py` | 129 |
| `middleware.py` | 60 | `routes/clock.py` | 22 |
| `routes/__init__.py` | 38 | `routes/common.py` | 48 |
| `routes/partners.py` | 64 | `services/rounding.py` | 26 |
| `routes/students.py` | 160 | `services/partner_svc.py` | 161 |
| `routes/cohorts.py` | 57 | `services/billing_svc.py` | 59 |
| `routes/agreements.py` | 112 | `services/cohort_svc.py` | 75 |
| `services/student_svc.py` | 134 | `services/stipend_svc.py` | 126 |
| `services/placement_svc.py` | 78 | `services/credit_svc.py` | 80 |

Layout: `app.py` (Flask app, error handlers, per-request lock + invoice-ageing sweep) → `routes/` (13 blueprints) → `services/` (calculations, cascades) → `db.py` (module-level dicts only; no file, no seed, no startup writes), `timeutil.py` (logical clock), `response.py` (envelope), `validators.py`, `middleware.py`, `errors.py`. **39 endpoints routed**, exactly matching PRD §4. Every module was written in its own message, all under 230 lines.

### Tricky rules

- **Two-variant placement fee**: exact-day window (`round_half_up(tiered × days/180)`) with the pinned 5-step order. Verified: 211-day TIER_B/12-supervision-hour window → **296572** (scaffold's stated figure); the same agreement's 121-day accepted window → 170072.
- **Per-term-rounding satisfaction composite**: each weighted term rounded to 2dp *before* summing, then `×5/4 −1`, clamped. Ratings (4.25, 3.15, 2.05) → **3.36** (not the 3.35 sum-then-round reading); (5,5,5) → 5.00.
- **Cohort-points evaluation order**: level read from the **raw** `total_points` (≥20→3, ≥10→2, else 1), base = `round_half_up(total/3)`, award = base + level×100. Verified total 20 → **307**; 8 → 103 and 13 → 204 reproduce the scaffold's examples.
- **Graduation cascade**: `INTERNSHIP→COMPLETED` + `graduation_at` stamp + three checkpoints at 3/6/12 **calendar** months (verified 2027-04-01 → 2027-07-01 / 2027-10-01 / 2028-04-01), only when no non-terminal placement remains and ≥1 is COMPLETED; also fires the cohort-completion check.
- **§2.5 priority order**: implemented as an explicit linear guard sequence per handler (auth role → identity → path L-to-R → body FK → well-formedness → transition admissibility → terminal guard → ownership → parent state → gates 10-12 → match/fee-tier/credit-hold/standing/past-due/credit-limit/window/payment/capacity/already-placed/slot-conflict/period-overlap/rounds-exhausted/duplicate-email → stale version). **ERR_INVALID_STATE vs ERR_ALREADY_TERMINAL split**: terminal rows (Student INELIGIBLE, statement/invoice PAID|VOID, grant GRANTED|VOID, placement TERMINATED) report `ERR_ALREADY_TERMINAL`; non-terminal rows with no transition (e.g. MATCHED placement offered, COMPLETED placement completed/terminated, INTERVIEWED placement re-scheduled) report `ERR_INVALID_STATE`. Verified both directions, including that state check 6 correctly precedes parent-state check 9 (re-enrolling an ENROLLED student into a COMPLETED cohort returns `ERR_INVALID_STATE`, not `ERR_PARENT_STATE_CONFLICT`).

### Smoke tests (run by the subagent, servers started exactly as the evaluator does)

`cd .../workspace/implementation && PORT=41873 bash start.sh &` then `python3 /tmp/smoke_*.py` (scratch scripts deleted afterwards). Four scripts, ~130 assertions, **all green** apart from three initially-wrong expectations in the subagent's own scripts. Highlights: full happy path partner→student→eligibility→cohort→enrollment→agreement→activation→4 paid L&D statements→match→interview→offer→acceptance(ACTIVE)→satisfaction→completion→graduation→3 checkpoints→invoice→payment; L&D ratio-0.9000 → 350¢ deduction; internship 60h/14d → 50 billable hours (82500¢); interview exhaustion returning the placement to MATCHED then `ERR_INTERVIEW_ROUNDS_EXHAUSTED`; slot-conflict by supervisor; invoice ageing (ISSUED→OVERDUE, credit_hold, SUSPENDED past 30 days, cleared on payment); OCC 412 on both guarded writes; credit ceiling 402; all three eligibility gates; pagination meta/clamping. Fresh-boot check: a student registered in one process is re-registered successfully (201) after a restart, proving zero carry-over state. All smoke servers were stopped by killing only the specific PIDs started.

### Ambiguities and the interpretations chosen

1. **`track_code` ≠ `cohort.program_code`** — no error id anywhere in PRD/scaffold. Chose `ERR_PARENT_STATE_CONFLICT` (409), grouping it with the cohort-level refusals.
2. **`scheduled_for` outside the agreement window** — no error id. Chose `ERR_PARENT_STATE_CONFLICT` (409), same family as the acceptance-window violation (409).
3. **Completion's two conditions** (clock ≥ `end_date`, ≥1 satisfaction record) — no error id. Chose `ERR_INVALID_STATE` (409).
4. **Matching to a DRAFT/FULFILLED agreement** — PRD lists only 4 match checks. Added an agreement-ACTIVE guard returning `ERR_PARENT_STATE_CONFLICT` (409); FULFILLED is still caught by the capacity check (`ERR_CAPACITY_EXCEEDED`).
5. **Activation's supervision≥10 / slot_count≥1** re-checks — mapped to `ERR_INVALID_REQUEST` (422) per the catalogue's "numeric field out of range".
6. **Credit-grant 365-day limit with `graduation_at` null** (student in INTERNSHIP, not yet graduated) — treated as no deadline to exceed, so GRANTED succeeds.
7. **Pagination `limit` out of range** — clamped into [1,100] rather than rejected (no error id is declared for query params).
8. **Recomputation vs version bumps** — a derived-field recompute bumps `version`/`updated_at` only when a value actually changes; a request that both cascades into a row and explicitly bumps it (e.g. invoice issuance) bumps exactly once.
9. **Checkpoint re-recording** — allowed (no state machine is declared for `OutcomeCheckpoint`); `feedback` defaults to `""` per the PRD's "feedback is empty".

Spec-driven surprise flagged by the subagent: a cohort flips to `COMPLETED` as soon as *every currently enrolled* student reaches `INTERNSHIP`/`COMPLETED`, which then blocks further enrollment into it (`ERR_PARENT_STATE_CONFLICT`). That is the literal PRD/scaffold rule and is implemented as written — any test that enrolls a second student into a cohort whose first student has already advanced will see that refusal.

**Orchestrator verification (independent of the hand-back):** all 33 files present on disk (2,854 Python lines + `start.sh` + `requirements.txt`); `start.sh` is executable, `cd`s to its own directory, guards the pip install, and ends with `exec python3 app.py` (foreground); a grep for `sqlite|pickle|shelve|json.dump|open(|/tmp/` across all modules returns **zero hits** (in-memory-only storage confirmed); orchestrator booted the server itself on port 41987 → binds `0.0.0.0`, serves the correct `{meta, response_type, data}` envelope, clean startup log. A `GET /partners` 404 in that boot was the orchestrator's own probe error, not a defect: PRD §4 declares only `POST /partners` and `GET /partners/{id}`, with no list route. Smoke server killed by its exact PID (3708027), port confirmed clear.

## Step 7: Run tests and iterate — 2026-10-01T10:53:33.788Z

All 8 rounds pass 63/63. Exiting the loop.

### Summary

**Iterations run:** 2 (baseline sweep + one fix round). No tests deleted; no assertions weakened.

**Final sweep (8 parallel rounds, `--isolation per-test-server`):**

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 63/63 | 63/63 | 63/63 | 63/63 | 63/63 | 63/63 | 63/63 | 63/63 |

Baseline was 57/63 in every round (6 failures, zero flakiness — identical union across all 8). All 8 `results.${i}.json` left in `workspace/implementation/`.

**Tests deleted:** none. Every failing test's assertion traced to a verbatim PRD sentence:
- interview scheduling needs an `ACTIVE` agreement — PRD §3.4 *"The sponsoring agreement must be `ACTIVE`…"* + §2.5 check 9.
- supervisor slot overlap / half-open interval — PRD §3.4 *"two rounds conflict when the intervals running from each round's `scheduled_for` for its `duration_minutes` share any instant, regardless of which placement they belong to"*.
- match-eligibility outranks capacity — PRD §2.5 checks 13 vs 21 + §3.4.
- 14-day past-due offer block — PRD §3.4 + §2.5 check 17.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/placements.py` — `create_placement()`: **removed** the invented `agreement["status"] != "ACTIVE" → ERR_PARENT_STATE_CONFLICT` guard (and its now-unused import). It is not a PRD rule: §3.4's matching paragraph enumerates exactly four pre-match checks (student phase, partner `ACTIVE`, slot capacity, no other `ACCEPTED`/`ACTIVE` placement) and §2.5 check 9's *"Applies to…"* list pointedly covers "interview scheduling, offers, offer acceptance, cohort enrollment and stipend statement creation" — **not** placement matching. The guard made a `MATCHED` placement under a `DRAFT` agreement unreachable, which is precisely the setup the interview-scheduling gate tests require. FULFILLED agreements are still refused, via the PRD-nominated `ERR_CAPACITY_EXCEEDED`. The handler now implements the four §3.4 checks in §2.5 order, unchanged otherwise.

**Fixes applied to `test_helpers/`:**
- `test_helpers/scenarios.py` — `setup_two_matched_placements()`: the second student is now enrolled into a cohort of their own (exposed as `scenario.cohort_two`) instead of the first student's cohort. The old order violated a PRD rule the implementation correctly enforces: §3.2 *"A cohort's own `status` becomes `COMPLETED` once every enrolled student of that cohort has a `current_phase` of `INTERNSHIP` or `COMPLETED`"*, and §3.2 *"a cohort that has reached `COMPLETED` refuses it with `ERR_PARENT_STATE_CONFLICT` (409)"*. The first student reaches `INTERNSHIP` inside `setup_matched_placement`, so the shared cohort was already closed to enrollment — the fixture, not the implementation, was wrong. Cohort membership is not part of any rule these scenarios exercise.

**Fixes applied to `test_suite/`:**
- `test_08_validation_priority_conflicts.py` — `test_match_eligibility_gate_outranks_agreement_slot_capacity`: Ben is now enrolled into a fresh cohort (`create_cohort()` imported) rather than Ava's already-`COMPLETED` one. Same root cause as above; the test's own assertion (Ben at `L_AND_D`, `ERR_NOT_ELIGIBLE_FOR_MATCH`) is unchanged.
- `test_14_partner_delinquency_thresholds.py` — `test_offer_is_blocked_once_the_invoice_is_past_due_by_more_than_fourteen_days`: Cara is now enrolled into a fresh cohort (`create_cohort` imported) rather than the two matched students' completed cohorts. Assertions unchanged.

**PRD passages found genuinely ambiguous:**
1. §3.3 opens *"Activation is the point at which an agreement becomes usable"*, which a reader could stretch into an implicit "matching requires an `ACTIVE` agreement" rule — this is what the implementation's extra guard embodied. Resolved against that reading: §3.4's matching paragraph is an explicit enumeration of the pre-match checks and omits it, and §2.5's check-9 applicability list excludes placement matching. The implementation now embodies the literal reading (matching under a `DRAFT` agreement is permitted; the agreement-state gate lives on interview scheduling and offers, where §2.5 check 9 names it).
2. §3.2's cohort auto-completion has no stated exception for "a student enrolled later", so a cohort whose only student advances is permanently closed to new seats. That is implemented as written; the fixtures were re-ordered to enroll everyone before anyone advances, rather than the rule being relaxed.

**Residual risk:** none observed — the 6 failures were deterministic across all 8 baseline rounds and are gone in all 8 post-fix rounds; no timing-sensitive test appeared in either sweep.

**Orchestrator verification (independent of the hand-back):** all 8 `results.*.json` present; each parsed and reported `passed=63 total=63 failed=0`. Newest implementation source mtime is `routes/placements.py` at 10:49:57, which **predates** the results files at 10:52:46 — so the passing sweep genuinely reflects the post-fix code (no post-sweep implementation write). This also means Step 8 is **not** skipped: Step 7 applied 1 `implementation/` fix.

## Step 8: Finalize PRD — align documentation to implementation — 2026-10-01T11:00:52.935Z

Both edits are present and verified. `workspace/PRD_FINALIZED.md` is complete.

### Output

**Line counts / delta**
- `PRD.md`: 299 lines, 60,616 bytes
- `PRD_FINALIZED.md`: 299 lines, 61,571 bytes
- Line delta: **0 lines (0.00%)** — both edits are inline insertions inside existing paragraphs; byte delta +955 (+1.58%). 4 changed lines total (2 old / 2 new).

**Changes (2)**

1. §3.4 (Matching, Interviews and the Offer Cycle) — **insert** — states that the sponsoring agreement's `status` is not one of the pre-match checks: matching does not require `ACTIVE`, a placement may be matched against a `DRAFT` agreement if the other checks pass, the agreement-state gate belongs to interview scheduling / offers (`ACTIVE`) and offer acceptance (`ACTIVE` or `FULFILLED`), and a `FULFILLED` agreement is refused at matching only via the slot check with `ERR_CAPACITY_EXCEEDED` — `workspace/implementation/routes/placements.py:42-101` (guard removed at former line ~64), with the state gate at `routes/interviews.py:79` and `routes/placement_actions.py:65,113`.
2. §3.2 (Cohort Enrollment and the L&D Phase) — **revise** — pins that the cohort's `COMPLETED` re-evaluation happens at the moment a student's phase advances (not on a later read), so the cohort is already closed to later enrollment with no exception — `workspace/implementation/services/cohort_svc.py:65-75` called from `services/student_svc.py:78` and `:115`; refusal read at `routes/students.py:120`.

### Per-edit pre-edit search log

Edit 1 — subject: *agreement `status` as a precondition of placement matching*.
- (b) Enumerated/read: `routes/placements.py:42-101` (the only `db.insert("placements")` site, verified by grep); `services/placement_svc.py:30-61` (`counted_placements`, `slot_count_reached`, `refresh_agreement_status` — early-returns for `DRAFT`); `services/billing_svc.py:50-53` (`partner_of_agreement`); all 8 `agreement["status"]` comparisons found by grep — `routes/interviews.py:79`, `routes/placement_actions.py:65,113,151`, `routes/agreements.py:70,109`, `services/placement_svc.py:46-53`; PRD cross-checks §2.5 check 9, §2.10, §3.3 FULFILLED paragraph, §3.4 offer paragraph.
- (c) Wording adjustment: avoided any claim of exhaustiveness about matching's check list and avoided "agreement state never gates anything"; scoped the statement to matching, added the "as long as the other checks pass" qualifier on the DRAFT case, and named the exact mechanism (`ERR_CAPACITY_EXCEEDED` via the slot check) for the FULFILLED refusal, since a `FULFILLED` agreement always has its counted `ACCEPTED`/`ACTIVE`/`COMPLETED` placements at `slot_count` (refresh reverts it to `ACTIVE` otherwise, at `placement_actions.py:149,202,221`).

Edit 2 — subject: *when a cohort's auto-`COMPLETED` transition is evaluated*.
- (b) Enumerated/read: `services/cohort_svc.py:16-20` (`enrolled_students` filters `application_state == "ENROLLED"`) and `:65-75`; all `current_phase` assignment sites via grep — `services/student_svc.py:76` (INTERNSHIP) and `:111` (COMPLETED) are the only two, each immediately followed by `maybe_complete_cohort`, and `routes/students.py:150` (L_AND_D, which cannot trigger completion); callers `services/stipend_svc.py:117` and `routes/placement_actions.py:198`; cohort-status reads `routes/students.py:120,156`; all `application_state` assignment sites (grep) confirm `ENROLLED` is never left.
- (c) Wording adjustment: deliberately said the re-evaluation is triggered by a *phase advance* rather than claiming "a cohort with no enrolled students completes" — the implementation early-returns for an empty cohort (`cohort_svc.py:70-71`), and a literal "every enrolled student" reading would wrongly close empty cohorts at creation. The trigger-based phrasing is consistent with that guard, with the `DISMISSED`/non-`ENROLLED` filters, and with the enrollment refusal path.

Items 3 and 4 of `<step_7_diff>` (the two `test_suite/` fixes) were the same root cause as item 2 and required no additional edit.

**Orchestrator verification:** `diff -u PRD.md PRD_FINALIZED.md` returns exactly **2 hunks** (one per reported edit) — the file is a genuine minimal patch, not a byte-identical no-op copy and not a truncated rewrite. Both hunks are substantive inline insertions inside §3.2 and §3.4 paragraphs.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-10-01T11:18:39.229Z

Done. `PRD_COMPLETED.md` is written; `implementation/` was not touched (verified by the orchestrator: newest implementation source is still `routes/placements.py` at 10:49:57, predating all Step 9 edits).

### Size

| File | Lines | Bytes |
|---|---|---|
| `PRD_FINALIZED.md` (source) | 299 | 61,571 |
| `PRD_COMPLETED.md` | 299 | 66,765 |

Delta: +5,194 bytes / +5,156 chars, zero new lines (every change is an in-paragraph insert or in-place revision; no new sections).

### Counts
- **28 ambiguity-pins**, **8 mismatch-revisions** (36 edits).

### Mismatch revisions (PRD asserted something `implementation/` does not do)
- §2.4 — revise — **mismatch** — "recomputation of a derived field counts as a mutation" is too strong; a refresh reproducing the row's existing derived values writes nothing and leaves `updated_at`/`version` alone — `services/partner_svc.py:103-136`, `services/cohort_svc.py:46-53`
- §2.6 — revise — **mismatch** — clock does **not** stamp `paid_on`; the payment request must supply it (and `recorded_at` is only clock-stamped when omitted) — `routes/invoices.py:100`
- §2.6 — revise — **mismatch** — ageing is not limited to "clock advances / invoice or partner read": it is re-evaluated before *every* request — `app.py:35`, `services/partner_svc.py:150`
- §3.7 — revise — **mismatch** — same ageing-cadence correction in the §3.7 restatement
- §3.1 — revise — **mismatch** — "any later attempt to act on that student is `ERR_ALREADY_TERMINAL`" overstates: a later decision/enrollment/stipend creation is; matching is `ERR_NOT_ELIGIBLE_FOR_MATCH` — `routes/students.py:81,112`, `routes/stipends.py:54`, `routes/placements.py:53-61`
- §3.2 — revise — **mismatch** — "`COMPLETED` once every enrolled student…" is vacuously true for an empty cohort; impl requires ≥1 enrolled student — `services/cohort_svc.py:69-70`
- §3.4 — revise — **mismatch** — "matching… consumes a slot" is wrong: only `ACCEPTED`/`ACTIVE`/`COMPLETED` count, a `MATCHED` placement blocks nothing — `services/placement_svc.py:5,30-39`
- §3.4 — revise — **mismatch** — "termination is available from every non-terminal placement state" conflicts with `COMPLETED` (non-terminal, yet refused `ERR_INVALID_STATE`) — `routes/placement_actions.py:212-217`

### Ambiguity pins
- §2.1 — insert — **ambiguity** — ownership is never used to *filter* lists; list endpoints return all rows matching query filters — `routes/placements.py:111-125`, `routes/invoices.py:69-83`
- §2.3 — insert — **ambiguity** — out-of-band `limit` is clamped to 1–100 (not rejected), negative `offset`→0, non-integer→default — `response.py:71-96`
- §2.3 — insert — **ambiguity** — rows sharing a `created_at` fall back to insertion order (the norm, since the clock is frozen) — `response.py:104`, `db.py:49`
- §2.4 — revise — **ambiguity** — `version` starts at **1** (was "its initial value") — `db.py:48`
- §2.5 #25 — revise — **ambiguity** — rounds-exhausted also applies to outcome recording, ahead of the ownership check — `routes/interviews.py:145-150`
- §2.6 — insert — **ambiguity** — clock-set response carries `current_utc` — `routes/clock.py:22`
- §2.10 — revise — **ambiguity** — `on_time_payment_ratio` = Σ`amount_paid_cents`(PAID) ÷ Σ`total_amount_cents`(ISSUED+OVERDUE+PAID), VOID in neither side, 0.0000 on zero denominator — `services/partner_svc.py:47-57`
- §3.1 — insert — **ambiguity** — `date_of_birth` accepted as date or instant, returned as a UTC instant — `routes/students.py:52`, `timeutil.py:48-73`
- §3.2 — insert — **ambiguity** — `track_code` ≠ `program_code` is `ERR_PARENT_STATE_CONFLICT` (409), in the parent-state group — `routes/students.py:132-138`
- §3.2 — insert — **ambiguity** — enrollment writes `track_code` + `cohort_id` onto the student and returns the updated student — `routes/students.py:149-152,160`
- §3.3 — insert — **ambiguity** — activation-time supervision-hours/slot-count/window failures are `ERR_INVALID_REQUEST` (422), evaluated after the state check and before the partner checks — `routes/agreements.py:77-82`
- §3.4 — insert — **ambiguity** — at match: `max_interview_rounds` recorded, `start_date`/`end_date` null, `hours_per_week` 20 — `routes/placements.py:85-99`
- §3.4 — insert — **ambiguity** — `scheduled_for` outside the agreement window is `ERR_PARENT_STATE_CONFLICT` (409) — `routes/interviews.py:85-92`
- §3.4 — insert — **ambiguity** — scheduling responds with the new round (201) — `routes/interviews.py:121`
- §3.4 — insert — **ambiguity** — rounds-exhausted at outcome recording is `ERR_INTERVIEW_ROUNDS_EXHAUSTED` (409); response carries the updated round — `routes/interviews.py:145-150,173`
- §3.4 — insert — **ambiguity** — `INTERVIEWED` with a non-`PASSED` latest round → offer refused `ERR_INVALID_STATE` (409) — `routes/placement_actions.py:57-62`
- §3.4 — insert — **ambiguity** — accepted span < 28 days → `ERR_INVALID_REQUEST` (422), checked with the body first — `routes/placement_actions.py:103-106`
- §3.5 — insert — **ambiguity** — an `L_AND_D` statement needs no enrollment; only the `INELIGIBLE` terminal gate applies — `routes/stipends.py:53-66`
- §3.5 — insert — **ambiguity** — a payment matching neither roster branch leaves `roster_status` untouched (never returns to `ON_TRACK`) — `services/stipend_svc.py:110-114`
- §3.6 — insert — **ambiguity** — no lifecycle state gates a satisfaction rating — `routes/satisfaction.py:20-65`
- §3.6 — insert — **ambiguity** — completion before `end_date` / with no rating → `ERR_INVALID_STATE` (409) — `routes/placement_actions.py:168-180`
- §3.6 — insert — **ambiguity** — completion stores the recorded `outcome` on the placement — `routes/placement_actions.py:185`
- §3.6 — insert — **ambiguity** — "latest satisfaction record" = greatest `submitted_at`, ties by insertion — `services/placement_svc.py:23-27`
- §3.7 — insert — **ambiguity** — a placement with no fee yet is invoiced at 0 cents; no placement state gates invoicing — `routes/invoices.py:42`
- §3.8 — insert — **ambiguity** — checkpoint `due_date` month-addition clamps to month end — `timeutil.py:87-93`
- §3.8 — insert — **ambiguity** — checkpoints may be recorded repeatedly, each overwriting the prior values — `routes/outcomes.py:29-48`
- §3.8 — insert — **ambiguity** — grant registration has no phase gate; `credit_hours` is read as a number (fractional allowed) — `routes/outcomes.py:71-73`, `services/credit_svc.py:44-47`
- §3.8 — insert — **ambiguity** — a student with no `graduation_at` has no 365-day deadline to exceed — `routes/outcomes.py:111-125`
- §3.8 — insert — **ambiguity** — the total tuition-credit aggregate is never surfaced on any resource — `services/credit_svc.py:57-60`

### Dead-code check

Every guard helper is reachable from a routed handler: `middleware.require/authenticate/authorize` (all 39 handlers), `common.must_get`/`must_get_body`/`require_owner` (`interviews.py:154`, `placement_actions.py:110`, `satisfaction.py:41`, `outcomes.py:42`)/`require_version` (`agreements.py:106`, `invoices.py:51`)/`terminal` (`students.py:81,112`, `stipends.py:54`), `placement_actions._guard_terminal` (55/108/165/210), `stipend_actions._guard_terminal` (30/42), `interviews._slot_conflicts` (94) & `_scheduling_admissible` (70), `stipends._periods_overlap` (73), `agreements._window_days` (46/81), `student_svc.check_eligibility_gates` (`students.py:90,140`), `maybe_graduate` (`placement_actions.py:198`), `has_active_placement` (`placements.py:78`, `placement_actions.py:133`), `cohort_svc.recompute_for_student` (`stipend_svc.py:118,125`), `partner_svc.apply_derived` (`invoices.py:64,122,143`) / `age_invoice` / `sweep_invoices` (`app.py:35`, `clock.py:21`), `credit_svc.mark_converted_to_hire` (`placement_actions.py:191`).

Defined-but-never-called:
1. **`credit_svc.total_tuition_credit_cents` (`services/credit_svc.py:57`) — the one PRD-required computation that ships as dead code.** Its only callee, `included_grants` (`:50`), is dead transitively. No endpoint or response ever exposes the §3.8 aggregate; PRD §3.8 now says so explicitly.
2. `student_svc.has_non_terminal_placement` (`:119`) — logic inlined at `student_svc.py:106`; PRD rule still implemented.
3. `credit_svc.update_conversion_streak` (`:74`) — logic inlined at `placement_actions.py:193-197`; PRD rule still implemented.
4. `partner_svc.has_overdue` (`:67`) — superseded by `has_overdue_before_today` (`:71`) / `has_overdue_beyond_days` (`:79`), both called.
5. `billing_svc.partner_of_placement` (`:56`), `timeutil.get_clock` (`:16`), `reset_clock` (`:24`), `days_between` (`:76`), `add_180_days` (`:96`), `db.reset` (`:75`) — unused utilities, no PRD requirement.
6. `billing_svc.FULL_DURATION_MIN_DAYS = 168` (`:23`) — unused constant left over from the two-step proration that PRD §3.7 explicitly disclaims.

No PRD-required check lacks an implementation: all 27 rules in §2.5 and every §3 formula/transition has a reachable implementation (route map verified: 39 routes, exactly matching the §4 table).

**Orchestrator verification:** `workspace/PRD_COMPLETED.md` present at 66,765 bytes (matches the reported size); `diff -u PRD_FINALIZED.md PRD_COMPLETED.md` returns 7 unified hunks (36 edits grouped into paragraphs). **`implementation/` was NOT touched by Step 9** — newest implementation source is still `routes/placements.py` at 10:49:57, predating every Step 8/9 edit (10:59 / 11:16). All 8 `results.*.json` remain in place with `passed=63 total=63`, so the Step 7 stability sweep remains valid and **no re-run is required**.
