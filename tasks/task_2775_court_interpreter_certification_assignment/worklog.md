## Step 1: Create task directory — 2026-09-04T20:05:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2775_court_interpreter_certification_assignment/` and `workspace/`. Index 2775 pre-assigned by the orchestrating command (no ./tasks/ scan performed, per instruction, to avoid collisions with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T21:52:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2775_court_interpreter_certification_assignment/`)
- `SCAFFOLD.yaml` — 2,298 lines / 145 KB (§1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,958 lines / 133 KB (single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3,847 lines / 289 KB (single top-level key)

**§1.0–§1.7 counts**: 12 entities (Language, Courthouse, RateSchedule, Interpreter, Credential, ExamAttempt, Hearing, Assignment, PayClaim, Complaint, DisciplinaryAction, UnmetNeedReport) · 8 state-machine blocks · 2 OCC concurrency rules (`expected_hearing_version` on `POST /assignments`, `expected_interpreter_version` on `POST /credentials`) · 9 calculations · 37 ordered validations · 55 endpoints · 47 error codes · 6 roles (ProgramAdmin, CredentialingOfficer, SchedulingCoordinator, Interpreter, FiscalOfficer, QualityReviewer) + segregation-of-duties pairs. `complexity_profile.difficulty_level: expert_plus`; the literal "harder than expert level" directive was kept out of `scenario:` so it cannot leak into PRD.md.

**§1.8 — 9 rule_ids × 2 instances = 18**: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**§1.9 — 9 sections, 74 instances (56 full recipes + 18 `excluded_because` stubs)**: Entities 12 · State Machines 12 (4 stubs) · Calculations 11 (6) · Validations 11 (4) · Endpoints 9 (2) · Errors 8 · RBAC 4 · Cross-Cutting Complexity Layers 5 (2) · Consistency Model 2.

**Verification run**
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1,042 calls scanned across 18 + 56 instances)
- All 47 §1.6 error codes are referenced by at least one design instance — 0 uncovered.
- All 18 stub `difficulty_instance` citations resolve to real §1.8 instance names; 0 name collisions across the §1.8/§1.9 union.
- No forbidden concurrency vocabulary ("simultaneously", "at the same time", "concurrently submitted", "in parallel", "first-writer-wins", race winner/loser) in any of the three files.

Two consistency fixes were applied to §1.6 this session so the catalog conditions for `ERR_HEARING_NOT_SCHEDULABLE` and `ERR_HEARING_ALREADY_COVERED` match the narrowed §1.4 checks at priorities 13 and 26. One design bug was also caught and repaired in the `optimistic_concurrency` corner instance: the replacement `POST /assignments` originally reused the interpreter who already held a PROPOSED row on the same hearing, which `interpreter_interval_conflict` (priority 30) would have rejected with `ERR_INTERPRETER_DOUBLE_BOOKED` before the supersede path could be reached; a third fully-credentialed interpreter now drives that call. No sibling task directory was read at any point.

**Orchestrator verification**: all three files parse as YAML with the expected top-level keys; `grep -i "harder than expert" SCAFFOLD.yaml` → no match (difficulty directive did not leak); `workspace/` still present after the subagent exited.

## Step 3: Copy shared files — 2026-09-04T21:52:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T22:06:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **496 lines**, built via 12 chunked heredoc appends (no truncation).

**Section list**
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (pasted byte-verbatim from `section-2.2-response-structure.md`, confirmed by substring match) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Clock · 2.6 Path Resolution and Referential Integrity · 2.7 Version Pinning on Calendar and Roster Writes · 2.8 Money, Hours and Rounding Discipline · 2.9 The Courthouse Encumbrance Ledger · 2.10 Segregation of Duties · 2.11 Cascade Discipline · 2.12 Order of Evaluation (all 37 validations, ordered, each with error id + endpoint scope)
- `## 3. Business Logic & Workflows` — 3.1 Program Configuration · 3.2 The Roster · 3.3 The Credential Pipeline · 3.4 Credential Cycles · 3.5 The Case Calendar · 3.6 Matching Interpreters to Hearings · 3.7 Serving the Assignment · 3.8 Interpreter Compensation: One Formula, Three Variants · 3.9 Quality Review, Discipline and Appeals · 3.10 Language-Access Compliance and the Daily Operations Run
- `## 4. Endpoint Definitions` — 4 columns, 55 rows
- `## 5. Error Code Catalogue` — 2 columns, 47 rows

**Tail confirmed complete:** file ends with the final error row `| ERR_REPORT_PERIOD_INVALID | 422 |` — a real section boundary, no audit footer, no contract-report block.

**Hard Contract reports (transcript only)**

Field coverage check: entities[].fields 138/138 · endpoints[].request_body 73/73 · endpoints[].query_params 25/25 · output-shape/common identifiers 23/23 · state enumeration values (8 blocks) 0 missing · enum-typed field values 0 missing · errors[].id 47/47 · roles[].name 6/6. Status: PASS

Rule coverage check: validations[] 37/37 with explicit global ordering · concurrency_rules[] OCC 2/2 · state_machines[].transitions 51/51 · calculations[] 9/9 · validation conditions→error_id 37/37 · endpoint side_effects 55/55 · entity field structured content 138/138 · sibling-branch symmetry 6 groups, 0 asymmetric. Status: PASS

Path purity check (§3 only): 1145 backtick tokens scanned; 0 starting with `/`; 0 bare HTTP-method tokens; 0 method+path tokens; 0 raw URL paths. Status: PASS

**Two scaffold self-conflicts reconciled** (flagged for Step 5/7):
1. Sanction-by-severity mapping — `state_machines` gives a *sliding* window (MINOR→{LETTER, PROBATION}, MAJOR→{PROBATION, SUSPENSION}, SEVERE→{SUSPENSION, REVOCATION}); the `/complaints/{id}/adjudicate` endpoint note gives a *cumulative* one. Wrote the state-machine (sliding) version, paired with the endpoint's declared `ERR_INVALID_REQUEST` (400).
2. Sweep step 3 threshold — state machine says the hearing is swept `SCHEDULED → UNMET` once the clock reaches `scheduled_start`; the endpoint note says `scheduled_end`. Two of three scaffold references say start, so the PRD uses `scheduled_start`.

Did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

**Orchestrator verification (truncation guard)**: `tail -25` ends on the final error-catalogue row `| ERR_REPORT_PERIOD_INVALID | 422 |` — a clean section boundary, not mid-sentence. All 5 top-level sections present. `grep -i "harder than expert|expert level|scaffold"` → 0 matches, so the Step 2 difficulty directive did not reach PRD.md.

## Step 5: Generate unit tests — 2026-09-04T23:04:00.000Z

Stage 2 is complete and audited. Final report:

## Output locations (both at the TASK ROOT; `workspace/` verified clean — contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`)

**`test_helpers/`** (Stage 1, unchanged since Stage 2 began — mtimes confirm no worker touched it): `__init__.py`, `api_client.py` (266 L, 55 methods = 55 PRD §4 rows), `api_errors.py` (47 ids = 47 status-map keys), `assertions.py` (370 L), `constants.py` (102 L), `factories.py` (325 L), `fixtures.py` (813 L), `test_users.py` (88 L), `types.py` (467 L).

**`test_suite/`** — 17 test files + conftest, 11,033 lines: conftest.py 68 | test_01 847/14 | test_02 891/9 | test_03 564/8 | test_04 735/16 | test_05 1061/17 | test_06 1004/25 | test_07 956/14 | test_08 742/7 | test_09 356/6 | test_10 476/8 | test_11 559/8 | test_12 609/10 | test_13 325/6 | test_14 430/9 | test_15 470/7 | test_16 372/8 | test_17 568/7 (lines/tests).

**179 test functions, 196 collected** (`pytest test_suite/ --collect-only -q` clean, 1.46 s, zero import/collection errors). Collection only — no server was started.

## Coverage
- **Queue A (Difficulty): 18/18 instances translated, none skipped**, 3–7 tests each (min required 2). Split by assertion cluster: variant sides, per-hop cascade groups, each side of every numeric boundary, conflict case + its armed single-failure control.
- **Queue B (Corner): 56/56 non-stub instances translated, none skipped**, 1–5 tests each.
- **18 `excluded_because:` stubs** correctly not translated; all 18 `difficulty_instance` pointers independently verified to resolve to a real `rule_id/name` pair — **0 broken**.

## Audit result (AST-based): **0 problems**
Every one of the 179 tests has exactly one `Design:` line as its final docstring line; all tags resolve to a real non-stub instance (no dangling, no dual-tag, no stub-tag); every quoted span >=25 chars is verbatim in `PRD.md` under whitespace normalisation; no `skip`/`skipif`/`xfail` anywhere; no money sent as a JSON string.

## Assertions dropped (never weakened, per silence-pattern discipline)
Recurring categories: refused-write side-effect silence (PRD never says a rejected request leaves `version` untouched — dropped in ~6 places, kept only where §3.7's budget sentence licenses it); sub-second width of non-common timestamps (`adjudicated_at`, `swept_at`, `current_utc` asserted by instant/format, not exact string); computed-field/projection silence (eligible-interpreter row field set, courthouse list filter param names); one default-value skip (`ethics_completed_on` at enrolment). Several literals were also deferred where asserting them faithfully belonged to another instance's citations.

## PRD defects surfaced (worth carrying into Step 8/9)
1. **§3.10 says the sweep returns "six identifier arrays" then lists seven** — flagged independently by three workers; no test asserts the count.
2. **Corner yaml line 1484 contradicts the PRD**: an ORAL score of 71 against a CERTIFIED target (floor 70) is a PASS, not the yaml's `FAIL`. PRD won.
3. **Corner yaml lines 3723/3845 assert `pending_pay_cents == 17500` for an `ENCUMBERED`-only claim**; §3.2 sums only FINALIZED/SUBMITTED/APPROVED, so the correct value is 0. PRD won.
4. **`suspension_days` is only defined for SUSPENSION sanctions**, yet three recipes pass it with LETTER/PROBATION — omitted from all requests.
5. **SchedulingCoordinator has no exclusive write in PRD §4** (PA shares every calendar/assignment op), so the RBAC instance's "every role has exclusive operations" premise holds for PA/CO/FO/QR/Interpreter only.
6. Minor: yaml labels the substantiation cascade hops 3/4 where PRD §3.9 numbers them 2/3/4 (tests follow PRD); one recipe's report window is unrunnable at the default clock (§3.10 requires a fully past period) — tests advance the clock first.

`worklog.md` was not touched, `workspace/implementation/` was never read, and no sibling task directory was accessed.

## Step 6: Generate implementation — 2026-09-04T23:04:30.000Z

Implementation complete and verified.

## Deliverable
`workspace/implementation/` — 21 files, **3856 lines**:
`app.py` 70 (factory, blueprint registration, ApiError/HTTPException handlers) · `start.sh` 9 (foreground `exec python3 app.py`, reads `$PORT` default 8000, binds 0.0.0.0, chmod +x) · `requirements.txt` 1 (flask) · `store.py` 75 (in-memory dicts + logical clock; no disk, no seed data) · `util.py`/`envelope.py`/`errors.py`/`auth.py`/`validation.py` 114/70/69/38/146 (ids, fixed 3-digit ISO-8601, meta envelope, 47 error codes, RBAC, shape ladder) · `derive.py`/`serializers.py`/`pay.py`/`cascades.py` 482/278/82/263 (derived fields, output shapes, money math with Decimal half-up per component, cascade helpers) · `routes_config.py` 294 · `routes_roster.py` 149 · `routes_credentials.py` 397 · `routes_calendar.py` 167 · `routes_assignments.py` 542 · `routes_payclaims.py` 126 · `routes_complaints.py` 345 · `routes_reports.py` 139.

**Endpoints: 55**, matching the PRD §4 table one-for-one (including `POST /ops/daily-sweep` and `POST /_clock/set_current_utc`). Every module AST-parses clean.

## Smoke test
Booted `PORT=<free high port> ./start.sh` (initially 39772, held by another pipeline, moved to 41337 after checking `ss -ltn`) and drove four end-to-end scripts covering all workflow areas. All checks green, including the final pass:
- rate-schedule overlap 409, telephonic-not-permitted 422, VRI capacity 409 with closed-interval touching-endpoint collision (PRD line 290 confirms touching windows do collide)
- continuance: hearing → CONTINUED (version 4, continuance_count 1), assignment → CANCELLED/COURT_CONTINUANCE, claim → VOIDED, second continuance 409 ERR_HEARING_NOT_SCHEDULABLE
- `PATCH /courthouses` tier → NONE cascades the VRI assignment to CANCELLED/EQUIPMENT_WITHDRAWN
- ledger conserved: encumbered 12420 / available 487580 after a VRI confirm

Earlier passes verified the full credential pipeline (3-strike denial, retake interval, upgrade-supersede, lapse/renew), pay math (2.0 h × 6000 + 15% rare premium + 60 mi × 67 = 17820; late-cancellation 12420), no-show auto-complaint, complaint appeal/vacatur/remand, sweep idempotency, and the 400/401/403/404/409/412/422 error surface.

Server killed precisely by captured PID (`kill 130579`); PORT_FREE + PID_GONE confirmed. No broad `pkill` used at any point. `__pycache__` and all `/tmp` scratch scripts removed; `test_suite/`, `test_helpers/`, the corner/difficulty design YAMLs, sibling tasks, and `worklog.md` were never read or touched.

**Orchestrator note**: Steps 5 and 6 were launched in two consecutive assistant messages rather than one, so the impl generator's physical isolation from `test_suite/` was not guaranteed by directory absence alone. Mitigation: the Step 6 prompt carried an absolute prohibition on reading `test_suite/`/`test_helpers/`/the design YAMLs, and the agent reported it never read them. Both test directories landed at the task root as required; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`.

## Step 7: Run tests and iterate — 2026-09-04T23:45:00.000Z

All 8 rounds green. Final state confirmed: `results.1.json` … `results.8.json` all exist on disk from the final sweep, each showing **196/196 passed, 0 failed, 0 errors, 0 skipped**. `worklog.md` untouched (mtime still 22:56, before the subagent started); no stray worklog files; implementation has no disk persistence (in-memory dicts only).

## Summary

**Iterations run:** 2 (iteration 1 = baseline sweep, 189/196 in all 8 rounds; iteration 2 = post-fix sweep, 196/196 in all 8 rounds).

**Flakiness:** none. The 7 failures were identical and deterministic across all 8 parallel rounds in iteration 1 — no load-induced or timing-sensitive failures, no sweep reaping.

**Tests deleted:** none. Both defects were harness/plumbing bugs in the test artifact, not PRD-coverage or unique-derivability failures. Every failing test cited verbatim PRD prose that uniquely determined its assertion (§2.9 inclusive budget boundary, §3.3 exam-retake 90-day gap and per-exam-type counters, §2.1/§2.12 interpreter ownership, §3.8 rare-premium bracket keyed on rounded service component).

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_confirmed_assignment()`: it passed `config["courthouse"]["id"]` and `config["language"]["id"]` positionally to `schedule_hearing()` *and* splatted `hearing_overrides`, so any test overriding the hearing's language raised `TypeError: schedule_hearing() got multiple values for argument 'language_id'`. Now pops `courthouse_id`/`language_id` out of the overrides and uses them as the explicit arguments, defaulting to the config values. This unblocked the 3 rare-premium tests (which must place the hearing in the RARE language, not the config's DESIGNATED default) and flows through `setup_served_assignment()` too.

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_scheduling_and_credentialing_gates.py` — 5 call sites (lines 263, 278, 427, 530, 575) wrote `validate_success(...)["data"]`. The runner's `validate_success()` already returns `body["data"]`, so the extra subscript raised `KeyError: 'data'` against the unwrapped resource. Removed the redundant `["data"]`. This accounted for 4 failing tests.

**Fixes applied to `implementation/`:** none. No implementation defect was found — the PRD-faithful implementation was correct on all 196 assertions once the test-side plumbing bugs were repaired.

**Orchestrator verification**: independently parsed all 8 `results.$i.json` (all mtime 23:15, ~62 KB each) — every file reports `passed=196 total=196 failed=0 errors=0`. The clean sweep is real, not a subagent claim.

## Step 8: Finalize PRD — 2026-09-04T23:57:00.000Z

## Result: `PRD_FINALIZED.md` is byte-identical to `PRD.md` — and that is the correct output

- `PRD.md`: 496 lines. `PRD_FINALIZED.md`: 496 lines. Delta: 0 lines / 0.0%. md5 identical (`6076b106…`).
- Changes: **none.** Both Step 7 fixes were test-side plumbing defects (a Python `TypeError` from a duplicated keyword argument, and a redundant `["data"]` subscript on an already-unwrapped payload). Neither ever reached the server, so neither could reveal a behavioral choice the PRD left open, and Step 7 applied zero implementation fixes and zero test deletions.

### Verification of each <step_7_diff> item against `implementation/`

**1. `test_helpers/fixtures.py` — `setup_confirmed_assignment()` duplicated `language_id`/`courthouse_id`.** Subject: §3.8 rare-language premium and the pay formula. Paths enumerated/read: `pay.py:32-82` (whole `compute()`), `util.py:96-114` (`round_half_up_cents`, `hours_two_dp`), `routes_assignments.py:320-343` (PROVISIONAL claim at confirm), `:425-458` (FINAL claim at completion), `cascades.py` create/finalize claim callers, `derive.py:234-249` (`ledger`), `serializers.py:29-45` (courthouse ledger fields). Finding: `pay.py:59-66` brackets on the already-rounded `service_cents`, never on a running total; `:20-29` does the x4/ceil/÷4 quarter-hour round-up then the `minimum_call_hours` floor; `:68-74` treats the free radius as a cliff with `miles <= travel_free_radius_miles` and doubles the one-way figure otherwise; `:81` sums the three already-rounded components. All stated verbatim in PRD §3.8 steps one–six. No edit.

**2. `test_04…py` lines 263/278 — redundant `["data"]` (§2.9 inclusive budget boundary).** Subject: courthouse encumbrance ledger + confirm-time budget gate. Paths: `routes_assignments.py:329-333` (confirm gate), `:440-448` (completion re-check), `derive.py:234-249`, `serializers.py:29-45`, `cascades.py` recompute callers. Finding: confirm refuses only on `total_cents > available_pay_cents` — inclusive at the boundary, exactly §2.9 ¶3 and §3.7; `available` = `pay_budget_cents − encumbered − obligated` with ENCUMBERED claims summing `provisional_total_cents` and FINALIZED/SUBMITTED/APPROVED/PAID summing `final_total_cents`, matching §2.9 ¶1. No edit.

**3. `test_04…py` line 427 — redundant `["data"]` (§2.1/§2.12 interpreter ownership).** Subject: `ERR_NOT_RESOURCE_OWNER`. Paths grepped: all three ownership gates — `routes_assignments.py:60-66` (`_owner_gate`: confirm/decline/check-in/complete), `routes_payclaims.py:62-68` (submit), `routes_complaints.py:241-246` (appeal) — plus `auth.py:16-38`. Finding: every gate is a plain inequality between the resource's interpreter FK and `X-User-ID`, no existence lookup, so a non-existent interpreter id yields 403 not 404 — already pinned by §2.1 and §2.12 item 6, whose endpoint list matches the three gates exactly. No edit.

**4. `test_04…py` lines 530/575 — redundant `["data"]` (§3.3 90-day retake gap, per-exam-type counters).** Subject: exam-attempt recording, retake gate, per-type counters/ordinals. Paths: `routes_credentials.py:170-235` (create), `:45-53` (floors, best score), `:238-246` (list + `exam_type` filter), `serializers.py:98-125` (`attempts_of`, derived counts and best scores), `derive.py:13-17` (floor/limit/wait constants), `routes_credentials.py:265-290` (advance branches reading the same best scores). Finding: the retake gate filters `same_type` FAIL attempts, takes the latest `taken_on`, refuses only when the day gap is `< 90` — exactly 90 accepted, and a WRITTEN failure never gates an ORAL attempt; both verbatim in §3.3. Counters/best scores derived per exam type; `attempt_ordinal` is the 1-based index in `taken_on`,`created_at` order. No edit.

### Out-of-scope observations (reported, deliberately not edited — carried into Step 9)
- `derive.py:14` sets `ORAL_FLOOR` to 70 for `REGISTERED` and `PROVISIONAL` targets; PRD §3.3 states only the `MASTER` (85) and `CERTIFIED` (70) oral floors. Off every Step 7 site, so pinning it in Step 8 would be a new claim outside `<step_7_diff>`.
- `routes_assignments.py:440-443` computes completion-time headroom as `available_pay_cents + claim["provisional_total_cents"]` (releasing the claim's own encumbrance first); PRD §3.7 says only "re-checks the courthouse's budget headroom against the amount now being obligated". Off every Step 7 site (only the confirm-time boundary was tested).

**Orchestrator note**: byte-identical Step 8 output is the legitimate outcome when Step 7 applied 0 implementation fixes — verified by md5. Step 9 still runs and must NOT be identical; the two out-of-scope observations above are handed to it as starting leads.

## Step 9: Complete PRD — 2026-09-05T00:05:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying). Rationale: a single-agent exhaustive scan of a 21-file / 3,856-line implementation against a 496-line PRD reliably under-scans or dies at the output cap; partitioning by impl module keeps each pass's read set bounded while the shared output file accumulates all edits.

**Net result**: `PRD_FINALIZED.md` 496 lines / 109,974 chars → `PRD_COMPLETED.md` 497 lines / 125,893 chars (**+15,919 chars, +1 line**; md5 `6076b106…` → `5dca05be…`, so NOT byte-identical). **54 changes total: 38 ambiguity-pins, 16 mismatch-revisions.** No new sections; all edits in-paragraph.

### Pass 1 — app/store/util/envelope/errors/auth/validation, routes_config, routes_roster, routes_credentials
496 → 497 lines, 109,974 → 113,835 chars (+3,861). 13 changes: 10 ambiguity-pins, 3 mismatch-revisions.
- §2.2 — insert — ambiguity — unrouted path / unsupported method answer in the standard error envelope as `ERR_INVALID_REQUEST` at 404 / 405; trailing slashes insignificant in routing — `app.py:37,47-56`
- §2.3 — insert — ambiguity — every declared ordering ends in an implicit insertion-order tie-break (a batch shares one logical `created_at`); off-enum list filters are 400 while an id filter resolving to nothing just matches nothing — `store.py:73-75`, `routes_config.py:85`, `validation.py:122-129`
- §2.5 — revise — mismatch — clock startup default is `2026-08-01T00:00:00.000Z` (three fractional digits) — `util.py:14,28-36`
- §3.1 — revise — mismatch — equipment-withdrawal cancellations run §3.7's lead-time branch (void + hearing→SCHEDULED when early; finalize on late-cancellation terms + hearing→UNMET when late), in `created_at` order — `routes_config.py:185-196` → `cascades.py:106-123`
- §3.1 — insert — ambiguity — a courthouse PATCH supplying none of the four mutable fields is a no-op that still bumps `version` and triggers no cascade — `routes_config.py:159-183`
- §3.1 — insert — ambiguity — a rate-schedule window with `effective_through` before `effective_from` is accepted and governs no date — `routes_config.py:220-221`
- §3.2 — insert — ambiguity — `completed_on` never compared to the clock; `provider` required but not persisted; re-recording ethics for an already-COMPLETED interpreter overwrites the date and bumps `version` — `routes_roster.py:120-131`
- §3.2 — insert — ambiguity — roster `credential_tier` filter accepts `NONE` — `routes_roster.py:31,84,92`
- §3.3 — insert — ambiguity — on `POST /credentials` the interpreter FK resolves before the language, so two bad ids report `ERR_INTERPRETER_NOT_FOUND` — `routes_credentials.py:68-69`
- §3.3 — insert — ambiguity — `attempt_ordinal` computed once; earlier attempts' ordinals never recomputed, so a back-dated attempt repeats an ordinal — `routes_credentials.py:221-222`
- §3.3 — revise — mismatch — **Step 8 lead confirmed**: oral floor is 85 for MASTER and 70 for every other target incl. REGISTERED/PROVISIONAL (reachable because an ORAL attempt can be filed against a credential whose target never enters an oral stage) — `derive.py:14`, `routes_credentials.py:45-48,208`
- §3.4 — insert — ambiguity — renewal for a REVOKED holder is refused with `ERR_INVALID_CREDENTIAL_STATE`, before the credit-hours minimum and the grace window — `routes_credentials.py:339-343`
- §3.4 — insert/revise — mismatch+ambiguity — revocation cascade uses the same lead-time branch; the INACTIVE demotion sweeps remaining live assignments in every language under `CREDENTIAL_REVOKED`; revoking a non-ACTIVE credential leaves language count, `roster_status` and interpreter `version` untouched — `cascades.py:162-182`

### Pass 2 — routes_calendar, routes_assignments, pay.py, derive.py
497 → 497 lines, 113,835 → 118,952 chars (+5,117). 19 changes: 11 ambiguity-pins, 8 mismatch-revisions.
- §2.3 — revise — mismatch — stale cross-reference: eligible-interpreter ordering is in §3.6, not §3.5 — `derive.py:386-423`
- §2.12 item 32 — revise — mismatch — `ERR_HEARING_WINDOW_CLOSED` also applies to confirm, cancel and `POST /hearings/{id}/continue`, plus the intra-endpoint position of that test — `routes_assignments.py:286,481`, `routes_calendar.py:140`
- §3.5 — insert — ambiguity — all hearing-creation fields (incl. `in_custody`) required; placement consults neither courthouse `status` nor equipment tier and does not require a future `scheduled_start` — `routes_calendar.py:51-72`
- §3.5 — insert — ambiguity — a continuance at/after `scheduled_start` reports `ERR_HEARING_WINDOW_CLOSED`, after the schedulability test — `routes_calendar.py:135-144`
- §3.6 — insert — ambiguity — the eligibility read runs collision rules with the hearing's own `requested_delivery_mode`; a collision drops the interpreter silently; an interpreter already live on this hearing self-excludes; the read is ungated on hearing `status` — `derive.py:391,409`, `routes_calendar.py:164-167`
- §3.6 — insert — ambiguity — `POST /assignments` resolves `hearing_id` before `interpreter_id` — `routes_assignments.py:85-88`
- §3.6 — insert — ambiguity — IN_PERSON creation applies no facility constraint — `routes_assignments.py:151-174`
- §3.6 — revise — mismatch — dropped "`interpreter_id` is null exactly when `vendor_served` is true"; policed only by the TELEPHONIC clause — `routes_assignments.py:161-174,212-220`
- §3.6 — revise — mismatch — travel/double-book comparisons use full millisecond precision, not second-level — `derive.py:335-344`
- §3.7 — insert — ambiguity — confirm's seven conditions evaluated in the listed order (not §2.12 numbering), error ids named, incl. closed facility for in-person reporting `ERR_REMOTE_EQUIPMENT_UNAVAILABLE` — `routes_assignments.py:278-333`
- §3.7 — revise — mismatch — a vendor-served confirm skips the rate-schedule requirement and budget check entirely — `routes_assignments.py:320-339`
- §3.7 — revise — mismatch — check-in has no vendor test; a vendor row is refused by ownership; roster failure is `ERR_INTERPRETER_NOT_ON_ACTIVE_ROSTER` — `routes_assignments.py:367-383`
- §3.7 — insert — ambiguity — completion's rate-schedule re-check asks for any currently-governing schedule while figures come from the claim's pinned schedule — `routes_assignments.py:428-435`
- §3.7 — revise — mismatch — **Step 8 lead confirmed**: completion headroom is `available_pay_cents + claim.provisional_total_cents`, strictly-greater refused — `routes_assignments.py:440-448`
- §3.7 — insert — ambiguity — cancel at/after `scheduled_start` reports `ERR_HEARING_WINDOW_CLOSED`, after the state gate — `routes_assignments.py:475-485`
- §3.7 — insert — ambiguity — the governing late-cancellation schedule is the claim's pinned one, falling back to the hearing-date schedule, treated as early when neither exists — `cascades.py:100-109`
- §3.7 — revise — mismatch — the hearing leg of a cancellation fires only when the cancelled row was CONFIRMED *and* the hearing currently reads COVERED — `cascades.py:120-122`
- §3.7 — revise — mismatch — an early no-show reports `ERR_INVALID_ASSIGNMENT_STATE`; a non-CLEAR `compliance_status` is left untouched — `routes_assignments.py:501-510`
- §3.7 — insert — ambiguity — the auto-filed no-show complaint carries a fixed server-supplied `narrative` and does not re-run intake's cascade — `routes_assignments.py:518-537`

### Pass 3 — routes_payclaims, routes_complaints, routes_reports, cascades.py, serializers.py
497 → 497 lines, 118,952 → 125,893 chars (+6,941). 22 changes: 17 ambiguity-pins, 5 mismatch-revisions.
Mismatch revisions: §3.9 hop three — the unconditional "voiding an encumbered claim and returning its hearing to SCHEDULED" now runs the §3.7 lead-time branch (`cascades.py:106-123` via `apply_sanction:230`) · §3.9 hop three — revocation's "same reason code" pinned to `INTERPRETER_SUSPENDED` (`cascades.py:235-239`) · §3.9 hop closing — "every row touched has `version` incremented by 1" → once per *touching hop*, with the revocation example (`cascades.py:214-242,179-182`) · §3.10 step one — same unconditional void/SCHEDULED claim replaced by the lead-time branch · §3.10 — **"six identifier arrays" listing seven → "seven"** (`cascades.py:14-23`, `routes_reports.py:123-125`), resolving the PRD defect Step 5 flagged.
Ambiguity pins: intake resolves interpreter-then-assignment, never cross-checked · an assignment already UNDER_QUALITY_REVIEW/SUBSTANTIATED_DEFECT keeps its value and `version` · `findings` required but not persisted · `reviewer_recommendation` advisory, never compared to `disposition` · `suspension_days`/`sanction_type` shape-checked but ignored outside their branch · the severity-window `ERR_INVALID_REQUEST` is raised after the REVIEWED gate while missing-field checks precede path resolution · hop two overwrites `suspension_through` regardless of prior value, roster move only from ACTIVE, revocation clears it to null, LETTER/PROBATION only bump `version` · `grounds` validated and discarded · vacatur rescinds the complaint's latest still-IN_EFFECT action, leaving an EXPIRED one alone · the → CLEAR release carries the same other-open-complaint guard as a dismissal · a vacated revocation restores neither the REVOKED credentials nor `roster_status` · remand does not clear `appeal_filed_at` and leaves the assignment SUBSTANTIATED_DEFECT · complaint/action reads are not owner-scoped for an Interpreter · all three fiscal transitions bump the courthouse ledger row's `version` (no total moves), only `pay` touches the interpreter, reads not owner-scoped · early cancellation does not touch the interpreter row · the report's 400-day span is a whole-day difference (400 accepted, 401 refused) and creating a report leaves the courthouse untouched · sweep iteration orders pinned (credentials/actions/interpreters by `created_at`; hearings by `scheduled_start` then `created_at`; cascaded cancellations by assignment `created_at`), per-lapse interpreter `version` accounting, step three moves no money · sweep-array touch order, no repeated identifiers, late-finalized claims absent from `voided_pay_claim_ids`.

**Leads checked and deliberately NOT acted on** (documented so they are not re-opened): `apply_sanction:222`'s `effective_through + T23:59:59.999Z` is not a mismatch — §3.9 already speaks of the `scheduled_start` **date** falling on or before `suspension_through`, i.e. whole-day inclusion · `finalize_claim:62` writing `variant = "FINAL"` on the LATE_CANCELLATION computation was already pinned by pass 2 · `serializers.credential_out`'s read-time recomputation of best scores/attempt counts is observationally identical to §3.3's wording · `derive.claim_for_assignment` returning the latest claim is unreachable (an assignment can be confirmed only once) · a few internal cross-reference typos in prose (§3.2/§3.7 pointing at §3.8 for discipline, §3.4 at §3.9 for the daily run) are citation errors, not impl mismatches, so left alone under the minimal-change rule.

**Orchestrator verification**: `md5sum` — `PRD.md` and `PRD_FINALIZED.md` both `6076b106…`, `PRD_COMPLETED.md` `5dca05be…` (distinct, so the scan genuinely ran); 497 lines / 125,893 bytes; tail ends on the final §5 error row `| ERR_REPORT_PERIOD_INVALID | 422 |`, a real section boundary, with all 29 `##`-level headings intact — no truncation.

## Pipeline complete — 2026-09-05T00:05:30.000Z

All nine steps finished. Final state: 8/8 sweep rounds at 196/196 passing; `workspace/PRD_COMPLETED.md` written.
