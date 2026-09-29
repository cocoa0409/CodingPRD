# Worklog — task_2816_postdoctoral_appointment_visa_administration

## Step 1: Create Task Directory — 2026-09-05T01:28:22.268Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2816_postdoctoral_appointment_visa_administration` and its `workspace/` subdirectory. Index 2816 was pre-assigned by the invoking command (no auto-allocation scan performed, to avoid collisions with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T03:08:00.000Z

Subagent summary (verbatim):

Done. All three scaffold artifacts for task 2816 are complete and lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2816_postdoctoral_appointment_visa_administration/`)

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2641 | §1.0–§1.7 + preamble |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1868 | §1.8 only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4485 | §1.9 only |

**SCAFFOLD.yaml** — `compliance_audit` × `workflow_orchestration`, flat topology, parallel state machines, `segregation_of_duties` role model, `immediate` consistency, `difficulty_level: expert_plus`. 12 entities, 11 state-machine blocks (incl. the two parallel `Appointment` dimensions `appointment_status` / `compliance_status`), 2 `concurrency_rules` (OCC on `Appointment.version` at salary-exception and lab-grant), 9 calculations (2 with variants: `visa_processing_timeline`, `export_control_risk_score`), 36 priority-ordered validations, 41 endpoints (15 GET / 26 POST), 48 errors, 6 roles.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 difficulty rules × 2 instances = **18 instances**.

**SCAFFOLD_CORNER_DESIGN.yaml** — **76 instances** (56 full recipes + 20 `excluded_because` stubs) across the nine guide sections: entities 11, state_machines 13, calculations 13, validations 9, endpoints 5, errors 16, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1.

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint` (877 calls scanned across §1.8+§1.9; 6 earlier violations fixed: a mis-named `risk_tier` capture, two array-output captures on `GET /appointments/{id}/exit-record`, `FundingSource.verification_status`, a capture off the scalar clock endpoint, and one literal `expected_appointment_version`).
- Independently checked: instance names unique across the union of both design files; every `${var}` bound by an earlier `captures:`; every `state_machines.*` / `calculations.*` / `endpoints.*` / `errors.*` / `roles.*` / `concurrency_rules.*` grounds string resolves against SCAFFOLD.yaml; all 20 stubs carry `grounds` + only `{difficulty_instance, rationale}`, no `test_recipe`, and every cited `rule_id / instance_name` pair exists.
- All pinned literals were recomputed with `Decimal`/`ROUND_HALF_UP` (e.g. untimely-notice branch: extension 15 days, term 13 months, encumbrance 84557.81, available 215442.19, window `2027-10-06T23:59:59.999Z`; one-day award overlap: base 169.86, fringe 47.56, total 217.42; risk scores 25.0 / 43.8).

**Two design notes worth passing on**
- `ERR_START_BEFORE_LAWFUL_DATE` (priority 24) is structurally unreachable: activation requires an APPROVED visa (priority 22), and the approval cascade rewrites `term_start_date := earliest_lawful_start_date` first, so the two dates can only be equal. It is documented as a stub with that rationale rather than faked.
- The scenario key holds the domain text verbatim but without the leading "Generate task harder than expert level!" directive — that instruction is carried in `complexity_profile.difficulty_level: expert_plus` instead, so it cannot leak into a downstream PRD.

Orchestrator verification: all three files present (128 KB / 118 KB / 298 KB); top-level keys correct (`SCAFFOLD.yaml` has no design keys; the two design files each carry exactly one design key); `grep -i "harder than expert"` over `SCAFFOLD.yaml` returns nothing, so the difficulty directive did not leak via the scenario key.

## Step 3: Copy Shared Files — 2026-09-05T03:09:08.267Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T03:22:05.433Z

Subagent summary (verbatim):

The PRD is complete and all three hard contracts pass mechanically.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2816_postdoctoral_appointment_visa_administration/workspace/PRD.md` — **473 lines**, written via 8 chunked appends (no single-Write 64k risk).

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 11 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, byte-identical) · 2.3 Pagination · 2.4 Record Identity, Timestamps and the Logical Clock · 2.5 The Two Independent State Dimensions of an Appointment · 2.6 Cascade Discipline and Compensating Actions · 2.7 Reverse-Lookup Reads and Left-to-Right Identifier Validation · 2.8 Money, Months and Rounding Discipline · 2.9 Optimistic Concurrency Control on the Appointment Record · 2.10 Segregation of Duties · 2.11 The Validation Precedence Ladder (all 36 rules ordered, plus the 3 declared conflict pairs)
- §3 Business Logic & Workflows — 9 subsections: 3.1 Registries · 3.2 Drafting (rank ledger, term limits, classification pairing) · 3.3 Compensation (floor, exception, benefits, encumbrance, issue-offer) · 3.4 Acceptance, visa category selection, sponsorship pipeline · 3.5 Mentoring plan / IDP · 3.6 Research security screening + bench access · 3.7 Activation and Withdrawal · 3.8 Reappointment, notice, grievance · 3.9 Exit, IP assignment, separation
- §4 Endpoint Definitions (4-column table, 41 rows)
- §5 Error Code Catalogue (2-column table, 48 rows)

File ends at a complete section: the final line is the last `ERR_FUNDING_BUDGET_EXCEEDED` row of the §5 table — no audit footer, no mid-sentence truncation.

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 107 required, 107 present, 0 missing
- `endpoints` request bodies: 60 required, 60 present, 0 missing
- `endpoints` query params: 12 required, 12 present, 0 missing
- (also verified: 48/48 error ids, 6/6 role names, 82/82 enum + state values present verbatim in backticks)

**Contract 2 — Rule Coverage: PASS**
- `validations[]` with priority: 36 checked, 36 expressed as an explicit total order in §2.11, 0 missing
- `concurrency_rules[]` OCC: 2 checked, 2 expressed with write endpoint + `expected_appointment_version` + `ERR_STALE_APPOINTMENT_VERSION` + 412, framed purely as stale-version (no "simultaneously"/race wording), 0 missing
- `state_machines[].transitions`: 55 checked across 11 machines, 55 fully expressed with from/to, preconditions paired to error ids, and every side effect, 0 missing
- `calculations[]`: 9 checked, 9 fully expressed in prose with all constants embedded and every pinned rounding/evaluation order stated, 0 missing
- `validations[]` conditions: 36 checked, 36 matchable to their error id in §2/§3 narrative, 0 missing
- `endpoints[].side_effects` / `applies_to`: 25 checked, 25 expressed, 0 missing
- `entities[].fields[]` structured content (types, defaults, initial values): 107 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 16 multi-exit from-state groups checked, equal prose density (notably the fork-join `FINALIZED_RENEWED` vs `FINALIZED_NON_RENEWED` branches, the three withdrawal branches, the four screening outcomes, the two timeline variants, the two screening tiers), 0 asymmetric

**Contract 3 — §3 Path Purity: PASS** — 996 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations. All endpoints referenced by state-transition framing, role + action verb, or capability description.

**Notes worth relaying**
- Two scaffold ambiguities were resolved conservatively in favour of coverage rather than silence: (a) the mentor-training and mentor-load preconditions on the `activate` transition are stated as also carrying `ERR_MENTOR_TRAINING_LAPSED` / `ERR_MENTOR_LOAD_EXCEEDED`, even though the `validations[].applies_to` scopes list only draft/lab-grant and issue-offer; (b) the export-control reviewer's separation from `prepared_by_user_id` and `mentor_id` is mapped to `ERR_SEGREGATION_OF_DUTIES`, the only code in the catalogue whose family covers it.
- `ERR_LAB_BUFFER_CONFLICT` (priority 27) vs `ERR_LAB_CAPACITY_EXCEEDED` (priority 28) are disambiguated using the error catalogue's own wording — buffer conflict when the collision exists only because of the decontamination expansion, capacity exceeded otherwise.
- The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, no sibling task was read, and no difficulty-directive language appears anywhere in the PRD (grep for `expert`/`harder than`/`difficulty` returns nothing).

Orchestrator truncation guard: `wc -l` = 473; `tail -25` ends on the final `| ERR_FUNDING_BUDGET_EXCEEDED | 422 Unprocessable Entity |` table row — a real section boundary, not mid-sentence. All 5 top-level sections present, §5 contains exactly 48 `ERR_*` rows. `grep -i "harder than expert|expert_plus"` over PRD.md returns nothing. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-05T03:56:00.000Z

(Launched concurrently with Step 5; completed first, so it is recorded here ahead of the Step 5 entry.)

Subagent summary (verbatim):

Implementation complete for task 2816.

## Modules (`/home/ubuntu/github/CodingPRD/tasks/task_2816_postdoctoral_appointment_visa_administration/workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` (executable, guarded pip, `exec python3 app.py`) | 8 |
| `requirements.txt` (`flask>=2.0`) | 1 |
| `app.py` — blueprint registration, `g.touched_records` init, ApiError/404/405/500 handlers, `0.0.0.0:$PORT` (default 10000) | 61 |
| `errors.py` — all 48 error ids → HTTP status + default messages | 81 |
| `envelope.py` — `meta`/`response_type`/`data` envelope, `req_` + 20 A-Z0-9 ids, pagination meta | 88 |
| `store.py` — in-memory dicts, logical clock (`2026-08-01T00:00:00Z`), version/touch dedupe, Decimal + ISO-8601 (3 fractional digits) helpers | 186 |
| `guards.py` — auth (`X-User-ID`/`X-User-Role`), FK lookups, typed field validators | 186 |
| `calc.py` — all 9 calculation rules (salary floor, encumbrance, visa selection/timeline, risk score, notice policy, pinned month arithmetic) | 286 |
| `serialize.py` — 12 entity serializers | 219 |
| `cascades.py` — shared recompute + cascade service layer (CH-A…CH-E) | 341 |
| `routes_registry.py` — postdocs, mentors, funding sources + verification, laboratories, `/_clock/set_current_utc` | 202 |
| `routes_appointments.py` — draft/list/get/salary-exception/issue-offer/accept-offer/activate/withdraw, 4 reverse lookups, open review, exit | 439 |
| `routes_visa.py` — submit-petition, adjudication | 101 |
| `routes_documents.py` — submit, acknowledge, review | 92 |
| `routes_security.py` — export-control decision, lab-access-grants create/list/get | 169 |
| `routes_reviews.py` — reviews, recommendation, finalize, grievances, resolution, ip-assignment | 263 |
| **total** | **2723** |

**Endpoints: 41** (15 GET + 26 POST) — exactly the 41 paths declared in SCAFFOLD.yaml `endpoints`, verified against `app.url_map`. `GET /postdocs` correctly 405s since only `POST /postdocs` and `GET /postdocs/{id}` are declared.

## Smoke tests (port 18316/18317, killed by exact PID; no broad pkill used)

Three curl/urllib suites all PASS, run against a fresh `bash start.sh` boot:
- **smoke1** — registry CRUD, envelope shape, draft → issue-offer → accept-offer → activate happy path, funding ledger, pagination meta, auth/RBAC/ownership/404 negatives.
- **smoke2** — salary floors (NIH band 1 + 3000 uplift = 64428.00; institutional band 0 = 58000.00; fellowship 61008×0.95 = 57957.60), encumbrance 93450.00 / 64500.00, budget-exceeded 422, export-control risk 12.5 CLEARED / 41.3 CLEARED_WITH_CONDITIONS / 90.6 DENIED, CH-C sustained-grievance 3-step reversal, CH-A exit close, non-renewal notice (24 months → 60 days, untimely extension → term_months 13, encumbrance 94474.11, grievance window `…T23:59:59.999Z`).
- **smoke3** (this session) — J1 selection for IN citizenship, `ERR_PREMIUM_TRACK_UNAVAILABLE`, initial projection +21/+10, POST_RFE_REFILING 1.5×21 → ROUND_CEILING 32 days, `ERR_RFE_ROUND_LIMIT_REACHED` on the 3rd RFE, activate blocked while compliance is PENDING_REVIEW, and CH-B approval at clock 2027-01-01 → lawful start 2027-01-11 → term deferral to 8 months → auto-withdraw `VISA_DELAY_TERM_TOO_SHORT` with encumbrance released to 0.00, docs/queued cycles VOIDED, award balance restored to 300000.00.

Response envelope matches PRD §2.2 exactly (confirmed by raw curl output above, including the paginated `meta` with `limit`/`offset`/`total_count`/`has_more` and the error body carrying `error_id`/`message` inside `data`).

**Zero implementation defects were found by the smoke suites.** The three issues hit during smoking were all in my own scratch fixtures (wrong expected budget, wrong hand-computed risk score, and stale in-memory state from reusing a warm server), plus one real bug fixed earlier: `routes_security.py` called a nonexistent helper, resolved by adding `cascades.laboratory_grants()`.

Constraint compliance: storage is in-memory dicts only, nothing seeded at boot (grep for seed/preload/sqlite/file-persistence returns only the two comments asserting the absence), `worklog.md` untouched, no test_suite/ or test_helpers/ path was read/listed/grepped, no sibling task directory was read, `__pycache__` removed, and no stray listeners remain on the 1831x ports.

## Step 5: Generate Unit Tests — 2026-09-05T05:04:00.000Z

Subagent summary (verbatim):

Stage 2 is complete. The suite now covers every non-stub instance in both design indices.

## Files

`/home/ubuntu/github/CodingPRD/tasks/task_2816_postdoctoral_appointment_visa_administration/test_helpers/` (unchanged this session, 2,384 lines)
`__init__.py` 158, `api_client.py` 240, `api_errors.py` 121, `assertions.py` 329, `constants.py` 119, `factories.py` 202, `fixtures.py` 635, `test_users.py` 129, `types.py` 451

`.../test_suite/` (8,365 lines, 110 tests)
`conftest.py` 73 · `test_01` 337/6 · `test_02` 310/6 · `test_03` 298/6 · `test_04` 272/6 · `test_05` 318/6 · `test_06` 347/6 · `test_07` 392/6 · `test_08` 343/6 · `test_09` 377/6 · `test_10` 643/11 · `test_11` 945/11 · `test_12` 763/9 · `test_13` 588/8 · `test_14` 681/5 · `test_15` 612/6 · **`test_16_access_control.py` 616/4 (new)** · **`test_17_concurrency_and_consistency.py` 450/2 (new)**

## Instances translated vs skipped

- Difficulty (queue A, §1.8): 18 non-stub instances, 0 stubs → 54 tests, every instance carrying >=2 (minimum 36 required).
- Corner (queue B, §1.9): 56 non-stub instances → 56 tests, exactly one each. **Zero skips**: no instance failed the PRD-first two-condition filter.
- 20 corner stubs (`excluded_because`) correctly left untranslated; no tag points at one.

## New this session

`test_16` closes `rbac` (all six roles on their exclusive operations plus the shared read surface and shared clock; the seven cross-role 403s against ids that resolve to nothing, proving rung 2 precedes rung 3; three header defects collapsing to `ERR_UNAUTHENTICATED` with a replayed email and a `verified_at` stamp proving nothing landed; both `X-User-ID` separations refused under an authorised role with the version unbumped). `test_17` closes `cross_cutting_complexity_layers` and `consistency_model`.

Two PRD-first adjudications were needed against the corner yaml, both recorded as in-code comments:
1. `rbac/every_role_...` asserts `status == ACTIVE` on the response to `POST /postdocs`; PRD 3.1 says "On registration the scholar's `status` is set to `PROSPECTIVE`" and this scenario never activates → asserted `PROSPECTIVE`.
2. `cross_cutting.../both_declared_occ_rules...` asserts the accept-offer version is `observed_version + 1`, but a bench grant lands between the read and the acceptance and PRD 2.9 says "A successful grant creation is itself a mutation of the appointment and increments its `version` by 1" → asserted `+1` after the grant and `+2` after acceptance.
3. Carried forward: `consistency_model` asks for `active_postdoc_count == 0` after a non-renewal; PRD 3.1 defines the field as a count over `ACTIVE` rows yet enumerates decrements only for completion and compliance termination, so no single value is derivable. That one assertion was dropped (mentor row still read, identity and ceiling asserted); all 15 other assertions kept.

## Audits

- Design tags: 110/110 tests carry exactly one `Design:` line, last line of the docstring, every target resolving to a live instance; no untagged, dual-tagged, or stub-pointing tags.
- PRD citations: 193 quoted citations, all now verbatim substrings of `workspace/PRD.md`. This pass found and fixed 6 defects in earlier files — five clause-truncations closed with a `.` instead of the sentence remainder (`test_07`, `test_08` x2, `test_09`, `test_14`) and one inserted "and" (`test_10`). All are full sentences again.
- `python3 -m pyflakes test_suite/*.py` silent; `pytest --collect-only` reports 110 tests with no import errors; no occurrence of "scaffold" in emitted code; `__pycache__`/`.pytest_cache` removed; nothing written under `workspace/` and `worklog.md` untouched.

Orchestrator verification: `test_helpers/` and `test_suite/` both live at the task root (not under `workspace/`); `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and `implementation/`.

## Step 7: Run Tests and Iterate — 2026-09-05T05:29:00.000Z

Subagent summary (verbatim):

Clean exit — all 8 parallel rounds pass 110/110.

## Summary

**Iterations run:** 2

**Iteration 1** — sweep result: 8/8 rounds at 109 passed / 1 failed (deterministic, identical failure in every round, so not load-induced).

Failing test (union across all 8 rounds, size 1):
`test_11_lifecycle_transitions.py::test_a_denied_rescreen_terminates_the_active_appointment_and_revokes_bench_access`
— tripped on `assert scholar["status"] == "SEPARATED"`, got `ACTIVE`.

Diagnosis walked the protocol:
- **STEP 1a (coverage):** PRD.md line 368 verbatim: *"Once the appointment has left the held population, the server checks whether the scholar has any remaining appointment whose `appointment_status` is `DRAFT`, `OFFER_ISSUED`, `OFFER_ACCEPTED`, `ACTIVE` or `NON_RENEWED`. If none remains, the scholar's own `status` advances `ACTIVE` → `SEPARATED`."* Covered.
- **STEP 1b (unique derivability):** The trigger is stated as a *condition* on the appointment leaving the held population, not as a step of the exit-closure chain. PRD.md line 121 defines that leaving as *"the moment the appointment leaves the held population for a terminal or non-renewed state"*. The research-security denial cascade (§3.6) sets `appointment_status` to `TERMINATED`, a terminal state, so the stated precondition holds and the outcome is determined. Held.
- **STEP 2 (test consistency):** Fixture chain builds an `ACTIVE`, sole appointment for the scholar; identity headers and the `restricted_party_hit=True` payload match PRD's `ExportControlReviewer` screening-decision contract. Test is faithful.
- **STEP 3:** Implementation gap confirmed.

**Tests deleted:** none. No test failed the coverage or unique-derivability checks.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2816_postdoctoral_appointment_visa_administration/workspace/implementation/cascades.py` — `terminate_for_compliance()`: added the trailing `evaluate_separation(appointment_postdoc(appointment))` call. The existing `evaluate_separation` helper was only reached from `close_exit_record()`, so an appointment leaving the held population via the §3.6 compliance-termination path never ran the PRD §3.9 separation check and the scholar stayed `ACTIVE`. No new capability was introduced — the pre-existing helper already encoded the PRD's five held-state list and its `ACTIVE`-only guard, which is why the change is inert for the `PROSPECTIVE`-scholar withdrawal paths and for scholars still holding another held appointment.

**Iteration 2** — sweep result: all 8 rounds 110 passed / 0 failed / 0 errors. The final passing `results.{1..8}.json` are left in place in `workspace/implementation/`. `worklog.md` untouched; no stray `test_suite/` or `test_helpers/` under `workspace/`.

Orchestrator verification: independently parsed all 8 `results.$i.json` — every round reports `passed == total == 110`. Step 8 is NOT skipped (1 `implementation/` fix was applied).

## Step 8: Finalize PRD — 2026-09-05T05:22:00.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with a single-line patch.

**Line counts:** PRD.md 473 lines / PRD_FINALIZED.md 473 lines — 0% line delta; 1 of 473 lines revised (0.21% of lines), 96,483 → 96,875 bytes (+0.41%).

**Changes**
- §3.9 (line 368, separation) — revise — the separation check's trigger is no longer stated as an abstract condition ("Once the appointment has left the held population") but as the two concrete moments the implementation calls it: exit-record closure and the §3.6 denial cascade terminating an `ACTIVE` appointment. Also pinned that the transition fires only from scholar `status` `ACTIVE`, and that no other exit from the held population — withdrawal in particular — evaluates it. Impl: `implementation/cascades.py:248` (`terminate_for_compliance`, the Step 7 fix), `implementation/cascades.py:304` (`close_exit_record`), `implementation/cascades.py:275-285` (`evaluate_separation`).

**Pre-edit search log (single edit)**
- (a) Subject: when the scholar-separation check runs and what it may write to `postdoc.status`.
- (b) Enumerated impl paths — grepped `evaluate_separation|SEPARATED|withdraw_appointment|terminate_for_compliance|close_exit_record|NON_RENEWED` and `postdoc["status"]` across all of `implementation/*.py`, then read each site: `cascades.evaluate_separation` (only writer of `SEPARATED`, guarded on `postdoc["status"] != "ACTIVE"`, five-state `HELD_FOR_SEPARATION` list); its only two callsites `terminate_for_compliance` (reached solely from `apply_compliance_outcome` on a `DENIED` cycle when `appointment_status == "ACTIVE"`) and `close_exit_record` (reached solely from `routes_reviews.py:262`, the IP-assignment signature when `lab_access_cleared` is true; runs unconditionally there, including when the appointment was already `TERMINATED`/`NON_RENEWED`); the three withdrawal paths that do **not** call it (`routes_appointments.py:349`, `routes_visa.py:86`, `routes_visa.py:100`, all via `cascades.withdraw_appointment`); the non-renewal finalization (`routes_reviews.py:145`) and grievance reinstatement (`routes_reviews.py:207-238`), neither of which calls it; the only other `postdoc.status` writers, `routes_registry.py:57` (`PROSPECTIVE` at creation) and `routes_appointments.py:331-332` (`PROSPECTIVE` → `ACTIVE` on activation). Also checked that multiple appointments per scholar are permitted (`routes_appointments.py` rule 25 only bars overlapping held terms), which is what makes the withdrawal-vs-separation divergence observable.
- (c) Wording adjustments made to keep every enumerated path true: scoped the compliance trigger to "terminates an `ACTIVE` appointment" so it stays consistent with §3.6's existing "an appointment that was not `ACTIVE` … stops at the `BLOCKED` posture" and with `apply_compliance_outcome`'s `ACTIVE`-only guard; phrased the exit trigger as "when an exit record reaches `CLOSED`" rather than tying it to the `ACTIVE` → `COMPLETED` transition, because `close_exit_record` evaluates separation even when the appointment was already terminal; added the explicit "not `ACTIVE` … left untouched" clause to cover the `PROSPECTIVE`-scholar early return; kept the negative claim as "no other path out of the held population evaluates the check" (withdrawal named only as an example) rather than an exhaustive list, so it does not accidentally speak to rank-month posting or to §2.6's separate held-population language.

## Step 9: Complete PRD — 2026-09-05T05:50:00.000Z

Orchestrator decision (recorded per the autonomy directive): Step 9 was run as **three sequential file-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module, rather than as a single subagent. Rationale: the implementation is 2723 lines across 16 modules and the PRD is 473 dense lines; a single scanning agent reliably exhausts its context and returns a PRD byte-identical to its input (i.e. the scan silently never ran). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not destroy earlier edits. Each pass received the prior passes' handover notes.

- Pass 1 partition: `app.py`, `envelope.py`, `errors.py`, `store.py`, `guards.py`, `serialize.py`, `routes_registry.py`, `routes_appointments.py`
- Pass 2 partition: `calc.py`, `cascades.py`
- Pass 3 partition: `routes_visa.py`, `routes_documents.py`, `routes_security.py`, `routes_reviews.py` (+ final integrity check)

### Pass 1 summary (verbatim)

Pass 1 complete.

**Setup:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` was done as the first action. Line counts: PRD_FINALIZED.md 473 lines / 96,875 chars; PRD_COMPLETED.md 473 lines / 101,065 chars (char delta **+4,190**, 17 lines revised, no lines added or removed — every change is in-paragraph).

**Counts:** ambiguity-pins **16**, mismatch-revisions **1**.

**Changes (one per edit):**
- §2.2 success-envelope bullets — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars; `api_request_timestamp` is read from the logical clock, not wall clock — `envelope.py:18-26`
- §2.3 (pagination params) — insert — ambiguity — empty-string `limit`/`offset` treated as omitted; non-integer, out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST` (400) — `envelope.py:47-70`
- §2.3 (ordering) — insert — ambiguity — `created_at` ties (the norm under a frozen clock) break by creation order; same tie-break under the `cycle_index` ordering — `store.py:76-78`, `routes_appointments.py:381`
- §2.4 `version` bullet — insert — ambiguity — version increments at most once per record per request even when a cascade writes it repeatedly; `updated_at` refreshes on each write — `store.py:62-73`, `app.py:30-33`
- §2.4 (clock capability) — insert — ambiguity — `current_utc` parsing tolerance (Z / numeric offset / naive-as-UTC), 400 on unparseable, and the response `data` is `{"current_utc": ...}` rather than a resource — `routes_registry.py:190-202`, `store.py:152-164`
- §2.8 (money) — insert — ambiguity — monetary inputs accepted as JSON number *or* decimal string; bool / non-numeric / non-finite / negative → `ERR_INVALID_REQUEST` — `guards.py:172-186`, `store.py:89-100`
- §2.11 rule 5 — insert — ambiguity — optional field given as JSON `null` takes its default; integral JSON numbers accepted where an integer is required (booleans not); whitespace-only strings refused — `guards.py:97-169`
- §2.9 (salary-exception guard) — insert — ambiguity — the operation has no state precondition; approvable in any `appointment_status`, terminal included — `routes_appointments.py:146-171`
- §3.1 (scholar `email`) — insert — ambiguity — duplicate email is refused with `ERR_INVALID_REQUEST` — `routes_registry.py:32-34`
- §3.1 (award suspension) — insert — ambiguity — suspension leaves `verified_at`/`verified_by_user_id` intact; re-verification overwrites both — `routes_registry.py:153-158`
- §3.1 (discovery filters) — insert — ambiguity — filters are exact string matches, conjunctive, empty string ignored, unmatched value yields `total_count` 0 rather than an error — `routes_appointments.py:132-137`
- §3.2 (drafting) — insert — ambiguity — a draft's `encumbrance_usd` is 0.00 and `fringe_rate` null until issuance; exception/withdraw fields null and `reinstated_count` 0 — `routes_appointments.py:73-80`
- §3.8 (opening a review) — insert — ambiguity — no appointment-status precondition on opening; the `ACTIVE` requirement belongs to finalization only — `routes_appointments.py:393-404`, cross-checked `routes_reviews.py:85-87`
- §4 endpoint table row — revise — **mismatch** — "for an active appointment" → "for an appointment", since impl imposes no such gate — `routes_appointments.py:393-404`
- §3.9 (initiating exit) — insert — ambiguity — no appointment-status precondition; supplied `exit_reason` stored verbatim — `routes_appointments.py:428-439`
- §4 lead paragraph — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` (404), wrong method → `ERR_METHOD_NOT_ALLOWED` (405), both outside the §5 catalogue; trailing slash equivalent — `app.py:19,41-48`

**Notes for later passes:** the impl's issue-offer check order puts award-term-overlap (ladder 35) before budget (ladder 31), but rule 31 is unevaluable without an overlap, so no observable mismatch — left alone. Similarly `ERR_NO_ELIGIBLE_VISA_CATEGORY` before `ERR_PREMIUM_TRACK_UNAVAILABLE` at acceptance is vacuously consistent with the ladder. One thing passes 2/3 may want to weigh: `serialize.reappointment_review_out` omits the stored `recommendation` and `decision` fields from the review response — PRD treats both only as request inputs, so I left it unpinned.

### Pass 2 summary (verbatim)

Pass 2 complete.

## Confirmation
- **No `cp` was run.** I only used the Edit tool on `workspace/PRD_COMPLETED.md`; every other file (including `PRD_FINALIZED.md`, all of `implementation/`, `test_suite/`, `test_helpers/`, `worklog.md`) is untouched — mtimes confirm it. I did not read `SCAFFOLD*.yaml`, `worklog.md`, or any sibling task dir.
- `PRD_COMPLETED.md` before: **473 lines / 101,065 chars**. After: **473 lines / 102,255 chars** (all four edits are in-paragraph, no new sections/paragraphs).
- Pass 1's 17 edits verified intact (spot-checked several); nothing reverted.

## Counts
- ambiguity-pins: **3**
- mismatch-revisions: **1**

## Changes
- **§2.5 (Two Independent State Dimensions)** — insert — ambiguity — With two `QUEUED` screening cycles, the PRD said only that the posture is "recomputed" once none remains `QUEUED`; it did not say *which* decided cycle's outcome wins. Pinned: the outcome of the last-decided cycle alone drives it (a cycle decided while another was still `QUEUED` drives nothing and is never revisited) — `implementation/cascades.py:307-325`.
- **§2.4 (Record Identity/Timestamps)** — insert — ambiguity — PRD claimed flatly that recomputing a derived field is a mutation of its holder. Carved out the award ledger: the `encumbered_usd`/`available_balance_usd` roll-up compares before writing, so a recompute that changes neither figure is not a mutation and leaves the award's `updated_at`/`version` untouched. Placed in §2.4 rather than §3.3 because §2.2's "section 2 governs" rule would otherwise override a §3 carve-out — `implementation/cascades.py:75-82`.
- **§3.3 (Encumbrance, step one)** — insert — ambiguity — PRD only covered no-overlap at offer issuance (`ERR_AWARD_TERM_NO_OVERLAP`) and was silent on what a *cascade* recompute does when a moved term no longer overlaps the award. Pinned: `encumbrance_usd` becomes 0.00 and `fringe_rate` is left as the last computable encumbrance wrote it rather than cleared — `implementation/cascades.py:106-110`.
- **§3.9 (Exit closure cascade)** — revise — mismatch — PRD's closure carve-out named only "a terminal state", leaving a `NON_RENEWED` appointment undetermined (a reader could plausibly advance it to `COMPLETED`). Revised to: only an `ACTIVE` appointment is advanced; any other status is left exactly as it stands, `NON_RENEWED` included, with its `encumbrance_usd` still charged to the award, no postings repeated and `final_months_posted` 0 — `implementation/cascades.py:294-304`.

## Notes on things deliberately left alone
- I agree with pass 1's read on the offer-issuance check order: impl evaluates award-term overlap (ladder 35) before budget (ladder 31), but rule 31 is genuinely unviolatable with a zero/undefined new encumbrance (every prior issuance kept `encumbered_usd <= annual_budget_usd`), so the inversion is unobservable.
- `calc.py` came out **fully pinned** by the existing prose — every constant, band boundary, rounding placement, priority table, tier predicate, component weight, threshold and notice band matches the PRD exactly. All four edits arise from `cascades.py`.
- Not pinned (judged unobservable, not invented into the PRD): the `max(0, ...)` clamp on `active_postdoc_count` decrements (the count is always >=1 on those paths); the absence of a clamp on `debit_rank_months` (the matching post always precedes); `latest_visa_case`'s `(created_at, _seq)` ordering (at most one visa case can ever exist per appointment, since only `accept-offer` creates one and it is reachable once); and `base_processing_days`' PREMIUM→STANDARD fallback (ladder rule 17 blocks a PREMIUM/TN or PREMIUM/J1 pairing at both acceptance and filing).
- Dead code in my partition, not reflected in the PRD and correctly so: `cascades.recompute_salary_floor` (no callers) and `calc.REALIZED_RANK_STATUSES` / `calc.DOC_REVISION_LIMIT` (unreferenced constants).
- Pass 3 note: `routes_reviews.py` returns `ERR_FUNDING_BUDGET_EXCEEDED` for both the untimely-extension overdraw (§3.8) and the sustained-grievance overdraw, but the PRD says only "the finalization is refused" / "the resolution is refused" without naming an error. That is a routes-module behavior, so I left it — pass 3 should pin it if it owns `routes_reviews.py`.

### Pass 3 summary (verbatim)

Pass 3 complete.

## Confirmation
- **No `cp` was run** at any point. All changes were targeted `Edit` string replacements against the existing `workspace/PRD_COMPLETED.md`.
- `PRD_COMPLETED.md`: **before** 473 lines / 102,255 chars → **after** 473 lines / 106,081 chars (+3,826 chars; every edit was in-paragraph, so no line-count change and no new sections/paragraphs).

## Counts
- ambiguity-pins: **10**
- mismatch-revisions: **6**

## Changes
- §2.11 rule 6 — revise — mismatch — rule claimed "every action operation"; pinned that operations declaring no from-state (salary-exception, document acknowledgement, review opening, exit initiation) run no state test and accept terminal targets — `routes_documents.py:55-62`
- §2.11 rule 19 — revise — mismatch — scope extended to the mentor's re-submission of a `RETURNED_FOR_REVISION` document (reachable: after 3 returns the doc is stuck and re-submit yields `ERR_REVISION_LIMIT_REACHED`) — `routes_documents.py:41-44`
- §2.11 rule 31 — revise — mismatch — scope extended to reappointment finalization and grievance resolution with the same `ERR_FUNDING_BUDGET_EXCEEDED` code — `routes_reviews.py:114-116`, `routes_reviews.py:211-213`
- §2.9 (lab-access paragraph) — insert — mismatch — a negative but well-formed `expected_appointment_version` is a 412 mismatch, not the 400 that rule 5's "negative numeric field" clause implies — `routes_security.py:99-105`
- §3.4 (case field defaults) — revise — mismatch — `decided_at` is null until an *approval or denial*; a recorded RFE stamps nothing — `routes_visa.py:76-81`
- §3.4 (petition filing) — insert — ambiguity — a supplied `PREMIUM` is tested against `visa_category` (`ERR_PREMIUM_TRACK_UNAVAILABLE`, track left untouched) and an accepted switch is applied *before* the projection, so the base duration keys on the post-switch track — `routes_visa.py:33-37, 44-53`
- §3.4 (adjudication inputs) — insert — ambiguity — `decision_note` is string-validated but not persisted and appears in no response — `routes_visa.py:67`
- §3.4 (approval cascade) — insert — ambiguity — only `earliest_lawful_start_date` is replaced; `projected_decision_date` and `projection_variant` survive untouched — `routes_visa.py:90-92`
- §3.5 (acknowledgement) — insert — mismatch — no state precondition and no ownership check: any `Postdoc`, any `status` including terminal `APPROVED`/`VOIDED`, repeatable, each write bumping `version` — `routes_documents.py:55-62`
- §3.5 (document review) — insert — ambiguity — `reviewer_note` is string-validated but not persisted — `routes_documents.py:71`
- §3.6 (compliance outcomes) — insert — ambiguity — a `CLEARED_WITH_CONDITIONS` re-screen restores nothing; regression-suspended grants stay `SUSPENDED` — `routes_security.py:53` → `cascades.py:317-319`
- §3.6 (bench access) — insert — ambiguity — no `appointment_status` precondition; only the compliance dimension is consulted, so terminal-status appointments can still receive grants — `routes_security.py:80-152`
- §3.6 (capacity vs buffer) — insert — ambiguity — the two refusals are discriminated by re-running the same per-day aggregate with **every** leading edge unbuffered (requested *and* incumbents), which differs observably from unbuffering only the requested edge — `routes_security.py:131-137`
- §3.8 (mentor recommendation) — insert — ambiguity — resolves pass 1's handover: the review representation carries no `recommendation`/`decision` field; the fork surfaces through `status` alone — `serialize.py:171-189`, `routes_reviews.py:67, 119`
- §3.8 (untimely notice) — revise — ambiguity — resolves pass 2's handover: names `ERR_FUNDING_BUDGET_EXCEEDED` and pins the non-mutating projection — `routes_reviews.py:104-116`
- §3.8 (sustained grievance) — revise — ambiguity — resolves pass 2's handover: names `ERR_FUNDING_BUDGET_EXCEEDED`, pins the pre-step projection against the restored term end, and that no fiscal test runs when the appointment is no longer `NON_RENEWED` — `routes_reviews.py:206-213`

## Re-checks requested
- **Acceptance ladder inversion confirmed unobservable**: `routes_appointments.py:288-295` evaluates `ERR_NO_ELIGIBLE_VISA_CATEGORY` first, but the premium test is only reachable *after* a category has been selected, so no request can violate both. Left alone, agreeing with passes 1 and 2.
- Not edited, out of my partition — **flagging for the record**: ladder rule 17 lists `ERR_PREMIUM_TRACK_UNAVAILABLE` as arising "on petition filing" only, while `routes_appointments.py:292-294` also raises it on offer acceptance (which §3.4 prose does pin). Rule 17's operation list is incomplete; the offending code is in `routes_appointments.py`, so I left it to avoid overstepping my partition.
- Also unreachable, deliberately not pinned: the RFE-round-limit guard on the *re-filing* path (`routes_visa.py:40-42`) can never fire, since `rfe_round_count` only reaches 2 while the case is `SUBMITTED`.

## Final-pass integrity verification
- 5 top-level sections present and in order (`## 1` ... `## 5`), 20 `###` subsections — identical count to `PRD_FINALIZED.md`.
- §4 endpoint table: **41** method rows. §5 error catalogue: **48** rows. File ends at the catalogue's last row (`ERR_FUNDING_BUDGET_EXCEEDED | 422`), a real section boundary.
- `cmp` vs `PRD_FINALIZED.md`: **DIFFERENT** (not byte-identical). Cumulative diff over all three passes, on 100-col wrapped text: 75 lines removed / 173 added.

### Orchestrator closing edit and verification

Pass 3 flagged one residual mismatch it declined to fix as out of partition: §2.11 ladder rule 17 scoped `ERR_PREMIUM_TRACK_UNAVAILABLE` to "on petition filing" only. I verified the raise sites myself — `grep -n ERR_PREMIUM_TRACK_UNAVAILABLE implementation/*.py` returns `routes_appointments.py:263` (offer acceptance) as well as `routes_visa.py:36` (petition filing) — and applied the minimal widening to "on offer acceptance and on petition filing." in `PRD_COMPLETED.md`. Since Step 9's contract is zero residual mismatch, leaving a known-incomplete ladder scope was not acceptable, and the fix is a single clause fully consistent with §3.4's already-pinned acceptance prose.

Final artifact state: `PRD.md` 473 lines / 96,483 chars → `PRD_FINALIZED.md` 473 lines / 96,875 chars → `PRD_COMPLETED.md` 473 lines / 106,105 chars (+9,622 chars over PRD.md, +9.97%; 29 ambiguity-pins + 8 mismatch-revisions + 1 orchestrator fix, all in-paragraph). All three PRDs are pairwise distinct. Step 7's final passing sweep results (`results.{1..8}.json`, 110/110 each) are retained in `workspace/implementation/`. `__pycache__` directories removed; `workspace/sweep.log` retained as the run trace. Pipeline complete.
