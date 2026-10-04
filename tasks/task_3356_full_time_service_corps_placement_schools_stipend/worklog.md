# Worklog — task_3356_full_time_service_corps_placement_schools_stipend

## Step 1: Create Task Directory — 2026-10-01T08:26:00.000Z

Pre-allocated directory `./tasks/task_3356_full_time_service_corps_placement_schools_stipend/` verified to exist with `workspace/` inside. No new index computed; using the provided path exactly.

## Step 2: Generate Scaffold — 2026-10-01T09:46:00.000Z

All checks pass. The scaffold package is complete and lint-clean.

**Generated files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3356_full_time_service_corps_placement_schools_stipend/`):

- `SCAFFOLD.yaml` (~1450 lines) — §1.0–§1.7: verbatim response envelope; 10 entities (Site, School, CorpsMemberApplication, CorpsMember, Team, TeamAssignment, Student, ServiceHourEntry [common_fields: false event log], StipendPayment, EvaluationReport); 13 state machines including cyclic School agreement (ACTIVE→AMENDMENT_REVIEW→ACTIVE, SUSPENDED loops), parallel CorpsMember dimensions (service × stipend × award with cross-dimension guards), cyclic Student caseload, and a revision-loop EvaluationReport; 3 OCC concurrency rules (school amend, member exit, team assignment — all `expected_*_version` with version-bump side effects); 7 calculations with two dual-variant pairs (stipend provisional/final, education-award projection/certification), order-pinned fundraising cap, and round-per-school-then-sum cost share; 31 ordered validations across auth/existence/state/safety/temporal/constraint/referential/fiscal; 40 endpoints (flat topology under `/corps`, every FK reverse-reachable); 31 errors; 6 roles with segregation of duties (hour verifier ≠ stipend approver; payment creator ≠ approver).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 18 instances, 2 per rule, each with a fully structured `setup_api_calls` chain (anchored world-setup recipes), computed literal asserts (e.g., projection 739500 vs certification 554625 on identical 90-hour data; cost-share 500001 vs sum-then-round 500000; partial award 737959 from 119.75 hours), and differentiation honored per rule (different domains/modes/entities/triggers/error-pairs/metrics/entity-pairs/interval-semantics/conserved-quantities).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 61 active corner instances + 8 `excluded_because` stubs covering entities, state machines, calculations, validations, RBAC, endpoints, cross-cutting layers (OCC ×3, derived-field reconciliation, version increments), and consistency; every catalog error is exercised.

**Verification performed**: `scaffold_lint.py` verdict is clean (40 endpoints, 10 entities, 18 §1.8 + 61 §1.9 instances, 1170 calls scanned, all FKs reverse-reachable); plus manual audits lint doesn't cover — anchor definition-before-use (clean, no redefinitions), instance-name uniqueness across both files, stub references resolve, all 31 errors named in at least one recipe, no forbidden concurrency vocabulary, all clock fixtures ≥ the pinned 2026-09-01T00:00:00Z default, and call-by-call replay of the trickiest chains (backfill budget/window boundaries, 30-day verification window, dual-failure priority pairs, depth-3 termination cascade, OCC stale-version expressions like `${school_v} - 1`).

One design note: endpoint count sits at exactly 40 — the FK reverse-reachability floor drove 13 sub-resource GETs; the interesting mechanics (award certification, stipend variants, cascades, caps) were kept dense rather than adding more surface.

## Step 3: Copy Shared Files — 2026-10-01T09:47:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T10:05:00.000Z

PRD generation complete. All three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3356_full_time_service_corps_placement_schools_stipend/workspace/PRD.md` (53 KB)

**Structure:** §1 Introduction (2 paragraphs, business-context angle); §2 with nine domain-derived subsections (RBAC with per-role identity translation, verbatim §2.2, pagination, the logical clock, common resource properties incl. the ServiceHourEntry no-`updated_at`/no-`version` exception, money/hours/rounding, OCC, validation order + nested path resolution, hierarchical cascades); §3 with eight workflow subsections (sites/funding, school partnerships + data sharing, recruitment, teams/backfill, caseloads, hours/verification, stipends/awards/exit, evaluation reporting); §4 with the 40-endpoint 4-column table; §5 with the 31-error 2-column catalogue. No audit footer after §5. The two withheld design files were never opened.

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 90 required, 90 present, 0 missing
- `endpoints[].request_body`/`input`: 60 required, 60 present, 0 missing
- query params (`limit`, `offset`, plus filter names drawn from entity fields): all present
- (103 unique names total; first pass found `team_id` missing — added in §3.4 — then re-ran to PASS)

**Contract 2 — Rule Coverage: PASS**
- validations[] with priority: 31 checked, 31 expressed — global "lowest-numbered priority wins" rule in §2.8 plus explicit per-endpoint orders (application: age→education→service; VERIFY: window→daily cap→fundraising cap; ASSIGN: state→member-active→placement→capacity→conflict; assignment create: OCC→state→backfill window→member active→overlap→capacity→backfill budget; approve: segregation first)
- concurrency_rules[] OCC: 3 checked, 3 expressed (`expected_school_version`/`expected_member_version`/`expected_team_version` + `ERR_STALE_VERSION` 412 each, no race framing)
- state_machines[].transitions: all 14 machines' transitions expressed with from/to, preconditions paired to error ids, and side effects (incl. the TERMINATED LINK 1–3 cascade, exit cascade, data-sharing auto-suspension, UNDERSTAFFED↔DEPLOYED cycle)
- calculations[]: 7 checked, 7 expressed in reconstruction-grade prose (stipend provisional/final with 26 periods / 14-day standard; award projection at 8.0 h/day vs certification with 120/24-hour and 739500-cent constants; order-pinned fundraising cap at 10% floored to the quarter hour; per-school round-then-sum cost share; posture thresholds incl. 500000-cent TIGHT bound; verified-hour self-reconciliation; evaluation overlap predicate with 5.0-point improvement)
- endpoints[].side_effects / validations[].applies_to: all expressed — walk found one scope gap (member-active guard on hour-entry creation) which was fixed
- entities[].fields[] structured content: defaults, initial values, and null-until semantics (`award_amount_cents`/`exit_type`/`exit_date` until exit, `enrolled_member_id` until ENROLLED, `rejection_reason` until a negative terminal, `reviewed_by`/`review_reason` until review) all reconstructible
- sibling-branch symmetry: withdrawal from all five states, both DISBURSED sources, COMPLETED/DISSOLVED from all team states, exits from ACTIVE/SUSPENDED/ENROLLED — all rendered with equal density

**Contract 3 — §3 Path Purity: PASS**
- backtick tokens scanned: 664; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combined: 0

Additional checks: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; no fuzzy/approximating words; no operator pseudocode in prose; §4 rows match the scaffold 40/40 with exactly 4 columns; §5 rows 31/31 with exactly 2 columns; all state enum strings and all six role names present. Note: the scaffold header comment says "30 errors" but the `errors[]` table defines 31 — the PRD catalogs all 31 from the actual table.

## Step 5: Generate Unit Tests — 2026-10-01T11:01:28.602396717Z

(First attempt interrupted mid-flight by host session stop — no files were left behind; rerun from scratch in resumed session.)

All generation and audit passes are complete. Summary of what was produced and key decisions:

## Generated artifacts

**`test_helpers/` (9 files)** at `/home/ubuntu/github/CodingPRD/tasks/task_3356_full_time_service_corps_placement_schools_stipend/test_helpers/`:
- `types.py` — 24 status/role enums + 11 entity TypedDicts; `ServiceHourEntry` correctly omits `updated_at`/`version` (PRD §2.5's sole exception).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (clock, sites, schools, applications, members, teams, assignments, students, hour entries, stipend payments, evaluation reports, plus all 11 reverse-reachability listings).
- `api_errors.py` — all 31 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — structural per-entity assertions (kept deliberately light so no computed-field over-assertion), plus I-CASH and posture-band invariant checkers.
- `factories.py`, `constants.py` (all PRD thresholds: 26 periods, 14-day period, 120/24-hour award bars, 739500 cents, 8.0 h/day, 500000 TIGHT band, 0.25 quantum, 12.0 daily cap, 10% fundraising cap, caseload 12, 30-day verify window, 45-day report window).
- `test_users.py` — opaque-role header constants (sd-1, pm-1, sa-1, sa-2, applicants) plus mandatory `make_school_liaison_headers`/`make_corps_member_headers` for the two entity-backed roles.
- `fixtures.py` — 5 tiers of composite setup (site/school chains, recruitment pipeline to ENROLLED, deployed-world builder, verified-hour accumulators, payment schedule/approve/pay, OCC-safe exit).

**`test_suite/`** — `conftest.py` + 10 test files, **95 tests**, all collected cleanly by `pytest --collect-only`.

## Audit results
- **Design tags**: every test ends with exactly one `Design:` line resolving to a real instance; all 18 difficulty instances have ≥2 tests; all 8 corner stubs cross-reference existing difficulty instances and were not translated.
- **PRD citations**: 118 quoted citations across 95 tests, all verified verbatim against `workspace/PRD.md` (14 initially truncated citations were rewritten to full PRD sentences).
- No skip/xfail markers; no scaffold references in generated code.

## Deviations worth flagging
1. **Two corner instances skipped** per the PRD-first two-condition filter (no placeholder emitted): `Corner/entities/hour_entry_create_extra_field_input_ignored` (PRD never states whether unknown request fields are ignored or rejected — the create's success isn't uniquely derivable) and `Corner/rbac/applicant_cannot_screen_application` (Applicant IS on the endpoint's §4 role list; the PRD names no error for a role-permitted endpoint with a role-disallowed transition).
2. **`hour_totals_exclude_nonverified` fixture repaired**: the design recipe's 5.0-hour base makes its 2.0 FUNDRAISING verify mathematically impossible under the PRD-pinned cap (cap would be 0.5). I re-derived the fixture with an 18.0-hour DIRECT_SERVICE base so the cap admits exactly 2.0 (floor(20.0×0.4)/4 = 2.0), preserving the instance's claim; asserted total is now 18.0.
3. **`school_agreement_amendment_and_suspension_cycle`**: the recipe's exact version-count assertion (==11) depends on whether the data-sharing-expiry cascade increments the school version once or twice — PRD §2.5 is ambiguous for same-row cascades, so I kept only the uniquely-derivable state-sequence assertions.

Orchestrator verification: `PYTHONPATH=$PWD python3 -m pytest test_suite --collect-only -q` → 95 tests collected, 0 errors (matches how prd-bench-local-run injects the task root into PYTHONPATH per executor.py).

## Step 6: Generate Implementation — 2026-10-01T12:08:10.702567394Z

Implementation complete and verified.

**Delivered** — `/home/ubuntu/github/CodingPRD/tasks/task_3356_full_time_service_corps_placement_schools_stipend/workspace/implementation/`:
- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000), `requirements.txt` (flask only)
- `app.py` + 8 support modules + 9 route modules, all byte-compiling cleanly
- All **40 endpoints** registered (29 writes/reads + 11 list endpoints), verified against the live route table
- **No seeding** — store starts empty; logical clock defaults to exactly `2026-09-01T00:00:00Z` and never reads wall-clock for business logic

**Spec fidelity highlights**:
- Envelope `meta.api_request_id/api_request_timestamp` (3-fractional-digit UTC), `response_type`, `data`; pagination `limit/offset/total_count/has_more` in `meta` with defaults 10/0, min 1, max 100
- Auth headers `X-User-ID`/`X-User-Role`; entity-backed ownership (403 `ERR_NOT_ENTITY_OWNER`) for CorpsMember self-access and SchoolLiaison school-scoped writes; segregation of duties on stipend approval
- Validation priority order followed: auth → body shape → path existence → OCC (`expected_school_version`/`expected_member_version`/`expected_team_version`, 412) → state (409) → business rules in §1.4 order (e.g. report window 15 before data-sharing 17; caseload-full 23 before caseload-conflict 24)
- Calculations in Decimal with ROUND_HALF_UP: stipend provisional (annual/26, length-independent) vs final (prorated by period_days/14), education award projection (8.0 h/day forward) vs certification (VERIFIED only), fundraising cap pinned to post-verification total floored to 0.25, per-school cost-share rounding before summation, evaluation metrics snapshot at DRAFT
- Full cascades with per-resource `version`/`updated_at` bumps: school termination LINK 1–3 (teams DISSOLVED → assignments ENDED → member stipend SUSPENDED + SCHEDULED payments FORFEITED `TEAM_DISSOLVED`), member exit cascade (`MEMBER_EXITED`), DEPLOYED↔UNDERSTAFFED auto-transitions, data-sharing expiry auto-suspension, cyclic caseload re-assign
- ServiceHourEntry correctly carries only `id`+`created_at` (no `updated_at`/`version`)

**One judgment call to flag**: `stipend_outlay_cents` after pay→clawback. The scaffold field formula `sum(PAID) − sum(CLAWED_BACK)` reads as −net under current-status semantics, but PRD §3.7 ("the pair returns both ledgers to their prior values", invariant I-CASH) and the `+=`/`-=` transition side effects require conservation (0 after the pair). Implemented as a running per-payment ledger contribution, reconciling both statements (a clawed-back payment's net was added when PAID and removed at clawback).

**Verification**: ~110 end-to-end checks across two smoke suites all passed (eligibility gates, soft-screening branches, enrollment, OCC staleness, capacity/overlap/backfill limits and windows, daily/fundraising caps, verify-void reconciliation, fiscal gate, completion/partial/forfeited awards, disbursement, report metrics/windows/revision loop, termination cascade, pagination, error envelopes). `bash start.sh` boot contract verified on a fresh port; all test server processes killed by exact PID, ports left free.

Orchestrator verification: all 18 source files byte-compile; route decorators counted = 40 (8 sites + 7 schools + 2 applications + 7 members + 6 teams + 4 students + 2 hours + 2 stipends + 2 reports), matching SCAFFOLD's 40 endpoints; `start.sh` is executable, reads `$PORT`, binds 0.0.0.0, foreground `exec python3 app.py`; no seeded data in store.

## Step 7: Test-and-Fix Iteration Loop — 2026-10-01T12:20:06.340485719Z

All 8 rounds pass 95/95. The `results.1..8.json` files remain in `workspace/implementation/` per the output contract.

## Summary

**Iterations run:** 2 (initial sweep: 92/95 in all 8 rounds, stable; post-fix sweep: 95/95 in all 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3356_full_time_service_corps_placement_schools_stipend/test_suite/test_08_member_lifecycle_awards.py` — three call sites (lines 96, 116, 342) passed raw day-of-month integers (`list(range(1, 11))`, `[1, 2, 3, 4, 5]`) to `fixtures.accumulate_verified_hours`, whose declared signature is `days: Sequence[str]`. The ints flowed verbatim into the `service_date` payload field and were correctly rejected with `ERR_INVALID_REQUEST - Field service_date must be a YYYY-MM-DD date`. Replaced with ISO date strings `[f"2026-09-{d:02d}" for d in range(...)]`, matching the fixture contract, the file-local `_twelve_hour_days` convention, and PRD's calendar-date semantics for `service_date`. Affected tests: `test_completion_hours_exactly_120_boundary`, `test_completed_award_can_be_disbursed`, `test_award_projection_partial_at_year_end` — all three quote PRD §3.7 verbatim (120-hour completion boundary / award disbursement / year-end projection), so STEP 1 coverage and unique derivability held; this was a pure STEP 2 request-construction test bug.

**Fixes applied to `test_helpers/`:** none — `fixtures.accumulate_verified_hours` was internally consistent (docstring, type annotation, and `_day_after`'s `date.fromisoformat` all assume ISO strings); only its callers were wrong.

**Fixes applied to `implementation/`:** none — the strict YYYY-MM-DD validation in `middleware.py` is PRD-faithful and is satisfied by the other 92 tests posting date strings.

Orchestrator verification: all 8 `results.{1..8}.json` read back independently → each 95/95, 0 failed; results files present (not deleted); newest implementation source (`routes_stipends.py` 12:02 UTC) predates the final sweep results (12:18 UTC) — no post-sweep impl writes; spot-checked test_08 lines 96/116/342 — ISO date comprehensions present as claimed, no raw int lists remain.

## Step 8: Finalize PRD — 2026-10-01T12:24:14.195862639Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3356_full_time_service_corps_placement_schools_stipend/workspace/PRD_FINALIZED.md` is a byte-identical copy of PRD.md — verified with `diff -q`.

## Summary

**Line counts:** PRD.md 301 lines, PRD_FINALIZED.md 301 lines, 0% delta (byte-identical). Zero edits committed.

**Changes:** none.

**Rationale — the step_7_diff reveals neither PRD silence nor PRD/impl mismatch:**

The only Step 7 items were three test_suite call sites (`test_08_member_lifecycle_awards.py:96,116,342`) passing raw ints to `fixtures.accumulate_verified_hours`, whose declared signature is `days: Sequence[str]` (`test_helpers/fixtures.py:323-326`). Verification of the behavior those ints hit:

- **Subject:** rejection of a non-date-shaped `service_date` with `ERR_INVALID_REQUEST`.
- **Impl paths enumerated:** `parse_date` (`implementation/db.py:74-78`, strict `^\d{4}-\d{2}-\d{2}$` regex + `date.fromisoformat`, rejects non-strings) behind `need_date`/`opt_date` (`implementation/middleware.py:85-102`, error text "Field %s must be a YYYY-MM-DD date"). Grep for every callsite confirms the validation is uniform across all date fields: `service_year_start`/`service_year_end` (routes_sites.py:37-38), `backfill_deadline`/`start_date`/`end_date` (routes_teams.py:30,115,171), `exit_date` (routes_members.py:121), `period_start`/`period_end` (routes_stipends.py:26-27, routes_reports.py:30-31), `service_date` (routes_hours.py:42), `date_of_birth` (routes_applications.py:32). No lax or divergent date path exists anywhere.
- **PRD pin:** PRD line 106 already pins the behavior — "the request body is checked for shape: required fields present, enums in range, **dates well-formed**, … — violations surface as `ERR_INVALID_REQUEST`" — and the PRD uses ISO 8601 consistently for every temporal literal (clock `2026-09-01T00:00:00Z` line 80, `to_iso8601` line 82, timestamps lines 45/86), with calendar-date semantics for `service_date` at line 180. Unique derivability held, exactly as Step 7's adjudication ("pure STEP 2 request-construction test bug") states; the rest of the suite already passed ISO strings, confirming the PRD was determinate for all other readers.

Adding a "YYYY-MM-DD" format sentence would be an edit demanded by nothing in the diff, so per the hard scope and the no-invented-edits instruction, none was made.

Orchestrator verification: `diff -q` confirms byte-identical; implementation sources untouched by Step 8 (newest .py mtime still 12:02 UTC, pre-Step-8).

## Step 9: Complete PRD — 2026-10-01T12:55:44.340655080Z

Done. PRD_COMPLETED.md is written and verified.

## Summary

**Source/delta:** `workspace/PRD_FINALIZED.md` → `workspace/PRD_COMPLETED.md`; 301 → 301 lines (all edits inline, no new sections), 53,291 → 57,102 chars (+3,811). 21 exact-match replacements across 20 paragraphs.

**Counts:** 15 ambiguity-pins, 6 mismatch-revisions.

**Changes** (section — kind — class — what — impl ref):

- §2.1 — insert — ambiguity — per-transition/dimension role restrictions on multi-role endpoints yield `ERR_UNAUTHORIZED_ROLE` — middleware.py:34 `forbid_role`, used in routes_schools.py:116+, routes_applications.py:87-93, routes_members.py:51-65, routes_reports.py:74/88.
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` — middleware.py:112-134.
- §2.3 — revise — ambiguity — `status` filter also on applications and teams; member-caseload listing accepts `caseload_status` only — routes_sites.py:146, routes_schools.py:206, routes_members.py:163.
- §2.4 — insert — ambiguity — clock accepts any well-formed instant (no monotonicity), echoes the submitted string verbatim — routes_sites.py:18-28, db.py:56-59.
- §2.8 — revise — mismatch+ambiguity — SoD relocated: evaluated after body-shape validation and payment resolution, before state checks; body-carried references (`site_id`/`school_id`/`corps_member_id`) resolve at the path-identifier stage with `ERR_NOT_FOUND`; per-transition role checks run before resolution on the member-state endpoint but after resolution on application/school/report state endpoints — routes_stipends.py:77-87, routes_members.py:51-66, routes_applications.py:81-93.
- §3.1 — insert — ambiguity — funding receipt has no site-status gate (allowed in SETUP/ACTIVE/CLOSED) — routes_sites.py:111-124.
- §3.2 — insert — ambiguity — school records may be created while the site is in any status — routes_schools.py:36-64.
- §3.2 — revise — mismatch — suspension blocks team creation/deployment only; report submission is governed solely by §3.8's gates (impl has no agreement check on submit) — routes_reports.py:73-86.
- §3.2 — insert — ambiguity — an amendment carrying no revisable fields still moves the agreement to `AMENDMENT_REVIEW` — routes_schools.py:95-102.
- §3.3 — revise — ambiguity — `SCREEN` valid only from `SUBMITTED`; supplied `rejection_reason` must be one of the three enums; non-`BACKGROUND_CHECK_FAILED` reasons don't alter screening — routes_applications.py:78-104.
- §3.3 — revise — mismatch — `INTERVIEWED`→`REJECTED` requires an explicit `rejection_reason` recorded verbatim (not fixed to `BACKGROUND_CHECK_FAILED`) — routes_applications.py:113-119.
- §3.4 — revise — mismatch — overlap check covers only not-yet-ended assignments; every still-ACTIVE assignment is open-ended so blocks any new placement; ended assignments never block — routes_teams.py:138-144.
- §3.4 — revise — ambiguity — deployment checks agreement-ACTIVE before the staffing floor — routes_teams.py:71-77.
- §3.5 — revise — ambiguity — `UNASSIGN` requires the student to be `ASSIGNED` (else `ERR_INVALID_STATE`) — routes_students.py:109-111.
- §3.5 — insert — ambiguity — metrics posting is not gated on enrollment status — routes_students.py:145-154.
- §3.6 — insert — ambiguity — a `reason` with `VERIFY` is accepted but not recorded (`review_reason` stays null) — routes_hours.py:114-116.
- §3.6 — revise — ambiguity — voiding records `review_reason` but does not restamp `reviewed_by` — routes_hours.py:123-128.
- §3.7 — revise — mismatch — `COMPLETED_TERM` exit accepted only from `ACTIVE` (else `ERR_INVALID_STATE`); early exits from `ACTIVE`/`SUSPENDED`/`ENROLLED` — routes_members.py:126-135.
- §3.7 — revise — mismatch — SoD enforced "before the state and member-status checks (after body validation and payment resolution)", replacing "before anything else" — routes_stipends.py:68-90.
- §3.7 — insert — ambiguity — projection fields computed on every read regardless of `service_status`, including after exit — serialize.py:71-95, services.py:114-132.
- §3.8 — revise — ambiguity — submission evaluates the 45-day window before the data-sharing gate — routes_reports.py:79-84.

**Dead-code audit:** all 34 services helpers, 13 middleware helpers, 16 route-local helpers, and 13 db helpers grep-verified to have live callsites on the paths they guard (incl. `fundraising_cap_ok`, `_link3_member_cascade`, `_reevaluate_team_after_loss`, `_capacity_exceeded`, `_member_placed_at_school`, `_data_sharing_not_signed`, the OCC comparisons, and the `ERR_COMPLETION_HOURS_NOT_MET` gate wired in routes_members.py:130-132 before `svc.member_exit`). All 31 catalogue error codes are raised somewhere. No dead PRD-required checks found; the one PRD-described behavior impl lacks (suspension blocking report submission) is absent code, not dead code, and was handled as a PRD revision per the alignment-target rule.

**Implementation edits under item 3:** none.

test_suite/ and test_helpers/ untouched; SCAFFOLD*.yaml and worklog.md never read.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (not a killed-mid-flight no-op); char counts match the claim (53,291 → 57,102); no implementation `.py` is newer than `results.1.json` (clean sweep still valid); spot-checked three edits against source — §2.4 clock-verbatim-echo (line 82), §3.7 COMPLETED_TERM-only-from-ACTIVE (line 206), §3.7 SoD relocation + §2.8 global validation-order deviations (lines 106/198) — all present as claimed and consistent with `routes_stipends.py:82` / `routes_members.py` behavior.
