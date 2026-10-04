# Worklog — task_3463_discrimination_charge_intake_mediation_right_sue_issuance

## Step 1: Create task directory — 2026-10-02T08:16:16.123125618Z

Pre-allocated directory verified to exist: tasks/task_3463_discrimination_charge_intake_mediation_right_sue_issuance/ with workspace/ inside. No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T09:19:43.325534742Z

All checks pass. Final summary:

## Deliverables

**(a) Output files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3463_discrimination_charge_intake_mediation_right_sue_issuance/`):
- `SCAFFOLD.yaml` — 1855 lines (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1263 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2425 lines (single top-level key `scaffold_corner_design`)

**(b) YAML validity** — all three parse clean via `yaml.safe_load`, and `scaffold_lint.py` reports **VERDICT: clean lint** (686 recipe calls checked: endpoints/roles/payloads/captures/OCC-placeholder discipline all conform; all 15 FKs reverse-reachable in §1.5). The verdict block is pasted verbatim above.

**(c) Structure** — `api_prefix: /eeoc` (logical-clock endpoint lives inside the prefix at `/eeoc/_clock/set_current_utc`, default `2026-09-01T00:00:00Z`). 15 entities: Complainant, Employer, DeferralAgency, Charge, MediationCase, MediationSession, InvestigationCase, EvidenceRequest, WitnessInterview, Determination, ConciliationProcess, RemedyPackage, RightToSueNotice, SystemicCase, DisclosureRecord. **42 endpoints**, 30 error codes, 9 roles (segregation-of-duties role model; entity-backed ChargingParty/RespondentRep). Profile: compliance_audit + workflow_orchestration, flat topology, cyclic state machines, 2 OCC rules (charge amend, conciliation offers).

**(d) Design instances** — difficulty: 18 (9 rules × 2, each with falsifiable distinguishing aspect and code-computed literal asserts, e.g. remedy PROVISIONAL 7,564,932¢ vs FINAL 6,570,274¢ from identical components; per-component rounding 2¢ vs sum-first 1¢; priority score 65→98→clamp-100). Corner: 66 instances (61 active + 5 `excluded_because` stubs) across all 9 claim-extraction sections.

**(e) Constants — all pinned with values, none named-but-unvalued**: `FEDERAL_DEFAULT_DEADLINE_DAYS=180`, `TITLE_VII_MIN_EMPLOYEES=15`, `ADEA_MIN_EMPLOYEES=20` (timeliness calc); band edges 15/20/100/200/500 (band calc); `ANNUAL_INTEREST_RATE=0.05`, `CAP_TIER_CENTS` {15–100: 5,000,000; 101–200: 10,000,000; 201–500: 20,000,000; 501+: 30,000,000} (remedy calc); severity weights, `OVERDUE_PER_REQUEST=15`, `OVERDUE_COMPONENT_CAP=45`, `SYSTEMIC_MULTIPLIER=1.5`, `SCORE_CEILING=100`, `ESCALATION_THRESHOLD=80` (priority calc); `CONSOLIDATION_MIN_CHARGES=3`, `CONSOLIDATION_MIN_SHARED_BASIS=2` (systemic calc); `RTS_MIN_ELAPSED_DAYS=180`, `RTS_COURT_FILING_DAYS=90`, `EVIDENCE_RESPONSE_WINDOW_DAYS=30`, `MAX_MEDIATION_ROUNDS=2`, `VACATE_WINDOW_DAYS=10`, `INTERVIEW_BUFFER_MINUTES=30`.

Notable fixes made during self-replay: dropped unreachable `ERR_RTS_ALREADY_ISSUED` (shadowed by terminal-state gate), reclassified `ERR_CONCILIATION_ACTIVE` as a priority-6 state variant (constraint priority would never fire it), added the missing `DOCKETED → RTS_ISSUED` Director-discretion transition, and corrected the mediation-cycle instance's investigation-status asserts (OPEN, since the GATHERING→SUSPENDED_MEDIATION side effect is conditional).

Orchestrator verification: line counts confirmed (1855/1263/2425); all three files yaml.safe_load clean with expected top-level keys; api_prefix "/eeoc" confirmed; 121 "eeoc" matches, 93 domain-entity matches, 0 foreign-domain term matches.

## Step 3: Copy shared files — 2026-10-02T09:19:47.567264880Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-02T09:34:17.573417833Z

All checks pass. Final report:

**(a) Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3463_discrimination_charge_intake_mediation_right_sue_issuance/workspace/PRD.md` — 309 lines, written in 6 incremental chunks (§1+§2.1–2.3 / §2.4–2.10 / §3.1–3.3 / §3.4–3.6 / §3.7–3.9 / §4+§5).

**(b) Termination**: file ends at the intended final section — the last line is the final row of the §5 Error Code Catalogue (`ERR_DUPLICATE_AGENCY_STATE` | 409), not mid-sentence.

**(c) Constant fidelity**: ~40 scaffold numeric literals/patterns grepped, all present verbatim, zero missing — including 180 (federal deadline + RTS gate), 300 (deferral deadline), employee thresholds 15/20, band edges 14/15–19/20–100/101–200/201–500/501, interest rate 0.05, cap tiers 5000000/10000000/20000000/30000000 cents, 365-day divisor, 90-day court-filing window, 30-day evidence window, 30-minute interview buffer, 10-day vacate window, 2-round mediation cap, overdue 15/request capped at 45, multiplier 1.5, ceiling 100, escalation threshold 80, consolidation 3-charge/2-shared-basis, severity weights 30/25/20/15, age tiers 0/10/20/35 at 90/180/365 boundaries, clock default `2026-09-01T00:00:00Z`, pagination 10/1/100/0.

**Hard contracts**: Contract 1 — 107 required identifiers (entity fields + endpoint inputs + query params), all backticked, 0 missing after two repair edits (`mediation_case_id`, `conciliation_process_id`). Contract 2 — all 10 validation priorities expressed as an explicit ordered pipeline in §2.8; both OCC rules named with endpoint + `expected_charge_version`/`expected_conciliation_version` + `ERR_STALE_VERSION`/412; all state transitions, cascades (cause-approval 3-link cascade, settle/impasse/vacate/withdraw/amend-dismissal/RTS closure cascades, systemic seal/lift), and all 5 calculations rendered in precise prose with pinned evaluation orders. Contract 3 — 583 backticked tokens scanned in §3, zero path/method violations. All PASS.

**(d) Ambiguity resolutions (Step 7 drift candidates)**:
1. **RTS preconditions uneven across transitions** — the DOCKETED transition omits "no notice exists" and LITIGATION_REFERRED omits the 180-day gate; I followed the endpoint-level rule (one notice per charge ever; ChargingParty always needs `days_elapsed_since_filing` ≥ 180; Director unconditional) as global.
2. **Duplicate-notice error unnamed** — mapped to `ERR_INVALID_STATE` (409) as the priority-6 state check.
3. **Amend that re-passes screening** — scaffold only specifies the dismissal outcome; PRD states a passing re-screen keeps current state with `version` +1.
4. **`requested_by_role` for auto-issuance** — rendered as the literal string `'system'`.
5. **Consolidation terminal set** — scaffold's "five terminals union {CLOSED_SETTLED}" spelled out as all six terminal states plus the seven non-terminal ones in §3.9.
6. **Clock endpoint is under `/eeoc`** in this scaffold (not unprefixed) — PRD §4 reflects that.

Orchestrator spot-check: 309 lines confirmed; ends with ERR_DUPLICATE_AGENCY_STATE catalogue row; literals 180/0.05/5000000/30000000/2026-09-01T00:00:00Z/ERR_DUPLICATE_AGENCY_STATE/ERR_STALE_VERSION all present.

## Step 5a: Generate test helpers — 2026-10-02T09:51:00.27418565Z

All checks pass. Stage 5a is complete. Here is the exit summary for the 5b stage.

## (a) Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3463_discrimination_charge_intake_mediation_right_sue_issuance/test_helpers/`)

| File | Lines |
|---|---|
| `__init__.py` | 45 |
| `types.py` | 419 |
| `api_client.py` | 297 |
| `api_errors.py` | 86 |
| `assertions.py` | 454 |
| `factories.py` | 229 |
| `constants.py` | 182 |
| `test_users.py` | 75 |
| `fixtures.py` | 906 |

No `test_suite/` and no test files were created (5b's job).

## (b) Compile + import results

- `python3 -m py_compile` on each file individually: all OK.
- Package-graph check: `python3 -c "import test_helpers, test_helpers.api_client, test_helpers.assertions, test_helpers.factories, test_helpers.fixtures, test_helpers.test_users, test_helpers.constants, test_helpers.types, test_helpers.api_errors"` → **IMPORT GRAPH OK**.
- A runtime sanity script verified the calculators reproduce every PRD-pinned worked example in the design indices (7302-cent rounding probe; 7564932 provisional / 6570274 final with interest 46849/23425; 809904 cascade total; priority 65/98 pre/post link; 80 boundary escalation; 100 ceiling clamp; 45→30 late-response drop; all seven band edges; all pinned dates 2026-11-28 / 2026-12-29 / 2026-08-31 / 2025-06-30 / 2027-02-28 / 2027-05-29 / 2026-10-01), that all 42 endpoint methods exist on `ApiClient`, and that the 30-entry error map registered with the framework (`_error_http_status_map` populated; `ERR_STALE_VERSION→412`, `ERR_RTS_PREMATURE→422`).
- `from .api_client import ApiClient, api_client` in `__init__.py` exports the singleton as an attribute; `import test_helpers.api_client` still binds the submodule cleanly (verified by the import check).

## (c) Constant cross-check (each pinned to PRD prose)

- `FEDERAL_DEFAULT_DEADLINE_DAYS=180` — §3.2 "when none matched, the federal default of 180 days applies" ✓
- deferral 300 / choices (180,300) — §3.1 "Only two deadline values are accepted — 180 or 300 days" ✓
- `TITLE_VII_MIN_EMPLOYEES=15` — §3.2 "Every other basis survives when the snapshot headcount is at least 15" ✓
- `ADEA_MIN_EMPLOYEES=20` — §3.2 "An AGE basis survives only when the snapshot headcount is at least 20" ✓
- band edges 15/20/100/200/500 — §3.1 "UNDER_15 for 0–14 ... FROM_15_TO_19 for 15–19, FROM_20_TO_100 for 20–100, FROM_101_TO_200 for 101–200, FROM_201_TO_500 for 201–500, and OVER_500 for 501 or more" ✓
- `ANNUAL_INTEREST_RATE=0.05`, divisor 365 — §3.7 "annual rate of 0.05 (five percent)"; "multiplied by interest_days, divided by 365, then rounded half-up" ✓
- `CAP_TIER_CENTS {FROM_15_TO_19:5000000, FROM_20_TO_100:5000000, FROM_101_TO_200:10000000, FROM_201_TO_500:20000000, OVER_500:30000000}` — §3.7 verbatim ✓
- `RTS_MIN_ELAPSED_DAYS=180` — §3.8 "requires days_elapsed_since_filing of at least 180" ✓
- `RTS_COURT_FILING_DAYS=90` — §3.8 "exactly 90 days after issuance" ✓
- `EVIDENCE_RESPONSE_WINDOW_DAYS=30` — §3.5 "exactly 30 days after issuance" ✓
- `INTERVIEW_BUFFER_MINUTES=30` — §3.5 "a 30-minute buffer on both sides" ✓
- `VACATE_WINDOW_DAYS=10` — §3.8 "Within 10 days of settled_at" ✓
- `MAX_MEDIATION_ROUNDS=2` — §3.4 "the hard cap being 2 rounds per charge" ✓
- `OVERDUE_PER_REQUEST=15`, `OVERDUE_COMPONENT_CAP=45` — §3.5 "15 points per currently-OVERDUE evidence request, capped at 45 points" ✓
- `SYSTEMIC_MULTIPLIER=1.5`, `SCORE_CEILING=100`, `ESCALATION_THRESHOLD=80` — §3.5 "multiplied by 1.5", "clamped to a ceiling of 100", "reaches 80 or more" ✓
- `CONSOLIDATION_MIN_CHARGES=3`, `CONSOLIDATION_MIN_SHARED_BASIS=2` — §3.9 "at least 3 linked charges are non-terminal and at least 2 of those non-terminal charges share a basis" ✓
- severity weights 30/25/20/15 and age tiers (90→10, 180→20, 365→35) — §3.5 verbatim ✓
- pagination 10/1/100/0 — §2.3 "defaults to 10 ... minimum of 1 and a maximum of 100 ... offset ... defaults to 0" ✓
- `CLOCK_BOOT_DEFAULT="2026-09-01T00:00:00Z"` — §2.4 verbatim ✓
- No dead/duplicate definitions (mechanically verified).

Clock endpoint is routed as `POST /eeoc/_clock/set_current_utc` — inside the prefix, no special-casing (`api_client.set_clock(payload, headers)`).

## (d) Helper API surface for 5b

**Status discipline**: `assertions.validate_created(resp)` (201) and `assertions.validate_ok(resp)` (200); fixtures internally use explicit-status `_expect` that fails with "Setup failed: ..." messages.

**ApiClient methods (42)** — `set_clock(payload, headers)`; `create_deferral_agency`, `create_employer`, `update_employer(id, payload, headers)`, `create_complainant`, `create_charge`, `get_charge(id, headers)`, `list_charges(headers, params)`, `amend_charge`, `withdraw_charge(id, headers)`, `offer_mediation(charge_id, headers)`, `list_mediation_cases`, `get_mediation_case`, `respond_mediation`, `create_mediation_session`, `list_mediation_sessions`, `conclude_mediation`, `get_investigation_case`, `list_investigation_cases(headers, params)`, `assign_investigator`, `create_evidence_request`, `list_evidence_requests`, `respond_evidence_request`, `create_witness_interview`, `list_witness_interviews`, `create_determination`, `list_determinations`, `submit_determination(id, headers)`, `review_determination`, `list_conciliation_processes(charge_id, headers)`, `get_conciliation_process`, `table_offer`, `accept_conciliation(id, headers)`, `fail_conciliation`, `list_remedy_packages`, `issue_right_to_sue(charge_id, headers)`, `list_right_to_sue_notices`, `create_systemic_case`, `link_charge`, `create_disclosure`, `list_disclosures`, `vacate_settlement`.

**Headers** (`test_users`): `TEST_USERS` has 9 keys (`platform_admin_headers`, `intake_officer_headers`, `charging_party_headers`, `respondent_rep_headers`, `mediator_headers`, `investigator_headers`, `director_headers`, `commissioner_headers`, `state_agency_officer_headers`); per-role builders `make_<role>_headers(user_id)` for all nine. Entity-backed rule: always `make_charging_party_headers(charge["complainant_id"])` / `make_respondent_rep_headers(charge["employer_id"])` for ownership-gated calls.

**Factories** — `set_clock_payload`, `create_deferral_agency_payload`, `create_employer_payload`, `update_employer_payload`, `create_complainant_payload`, `create_charge_payload` (complainant_id/employer_id required), `amend_charge_payload` (expected_charge_version), `respond_mediation_payload`, `create_mediation_session_payload`, `conclude_mediation_payload`, `assign_investigator_payload`, `create_evidence_request_payload`, `respond_evidence_payload`, `create_interview_payload`, `create_determination_payload` (NO_CAUSE default), `cause_determination_payload` (CAUSE with all 5 fields), `review_determination_payload`, `table_offer_payload` (expected_conciliation_version), `fail_conciliation_payload`, `create_systemic_case_payload`, `link_charge_payload`, `create_disclosure_payload`, `vacate_settlement_payload`.

**Assertions** — `assert_<entity>(data)` for all 15 entities (DisclosureRecord asserts absence of `version`/`updated_at`); calculators `expected_size_band(count)`, `expected_priority_score(basis_codes, days_elapsed, overdue_count, systemic_linked)`, `expected_priority_escalated(...)`, `expected_interest_cents(component, days)`, `expected_remedy_valuation(back, front, comp, pun, band_used, interest_days)` (Decimal half-up, per-component round-then-sum — reproduces every pinned design value), plus `round_half_up`.

**Fixtures** — primitives: `set_clock`, `set_clock_to_date`, `create_employer`, `create_complainant`, `create_deferral_agency`, `file_charge`, `read_charge`, `offer_mediation`, `respond_to_mediation`, `decline_mediation`, `activate_mediation`, `schedule_session`, `conclude_mediation`, `charge_investigation_case_id`, `assign_investigator`, `issue_evidence_request(s)`, `log_interview`, `draft_determination`, `draft_cause_determination`, `submit_determination`, `review_determination`, `conciliation_for_charge`, `remedy_package_for_conciliation`, `table_offer(process, amount, side, charge)`, `accept_conciliation`, `fail_conciliation`, `issue_rts_as_charging_party/_as_director`, `create_systemic_case`, `link_charge`, `record_disclosure`, `vacate_settlement`, `fresh_id(prefix)`. Composites (each sets the clock first via `clock_start`, default boot default): `setup_docketed_charge`, `setup_under_investigation`, `setup_gathering`, `setup_pending_review`, `setup_conciliation`, `setup_closed_no_cause`, `setup_in_mediation`, `setup_settled_via_mediation`, `setup_settled_via_conciliation`, `setup_sealed_charge`, `setup_rts_issued(via=..., days_elapsed=180)`, `setup_overdue_evidence(request_count, days_after_due)`. All composites return dicts keyed `{employer, complainant, charge, mediation_case?, investigation_case_id?, investigator_user_id?, determination?, conciliation?, remedy_package?, notice?, systemic_case?}` — keys documented per-fixture. Date helpers exported: `date_to_iso`, `iso_at`, `add_days`, `days_between`. Opaque operator ids default to unique `fresh_id(...)` values so SoD/buffer rules never collide accidentally; tests pin explicit ids when a scenario requires it.

Orchestrator verification: 9 files at claimed line counts (2693 total); IMPORT GRAPH OK reproduced; test_suite absent as required at this stage.

## Step 5b: Generate test suite — 2026-10-02T10:28:25.824352200Z

Stage 5b is complete. Full summary:

**(a) Test files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3463_discrimination_charge_intake_mediation_right_sue_issuance/test_suite/`, `test_helpers/` untouched):
- `conftest.py` — api + 9 role-header fixtures
- Difficulty (18): `test_difficulty_dual_variant.py` (2), `test_difficulty_combinatorial.py` (2), `test_difficulty_state_cycles.py` (2), `test_difficulty_cascades.py` (2), `test_difficulty_precedence_boundaries.py` (4), `test_difficulty_cross_entity.py` (2), `test_difficulty_temporal_invariants.py` (4)
- Corner (61): `test_corner_entities.py` (10), `test_corner_state_mediation.py` (5), `test_corner_state_charge_lifecycle.py` (7), `test_corner_state_lazy_systemic.py` (3), `test_corner_calculations.py` (5), `test_corner_validations_access.py` (7), `test_corner_validations_gates.py` (6), `test_corner_endpoints.py` (5), `test_corner_errors.py` (3), `test_corner_rbac.py` (7), `test_corner_occ.py` (2), `test_corner_consistency.py` (1)

**(b) Collection**: `pytest test_suite --collect-only -q` → **79 tests collected, clean** (run with `PYTHONPATH=.` emulating the runner's path injection). pyflakes clean on all 20 files.

**(c) AST audit** (real `ast` walk, tags cross-resolved against both YAMLs): 79/79 tests carry exactly one `Design:` tag as the docstring's last line; 0 unresolved/stub-pointing/dual tags; **79/79 active instances covered**; every PRD-quoted span in every docstring survives verbatim containment in PRD.md (C1, 0 failures); 79/79 tests carry ≥1 PRD citation line; no file mentions "scaffold".

**(d) Reconciliation: emitted 79 + skipped 0 = 79.** No instance failed the PRD-first filter — every active instance's asserted rule (error_ids, thresholds, transitions, side effects, cascade shapes) has verbatim PRD coverage and a uniquely derivable outcome. The 5 corner stubs are untranslated per spec; all five `difficulty_instance` cross-references resolve to emitted difficulty tests.

**(e) Interpretations (Step 7 adjudication candidates):**
1. `remedy_interest_per_component_rounding` — recipe rewinds the clock (2026-09-01 → 2026-08-02) after intake; I park the clock at 2026-08-02 *before* any entity creation instead, so no record ever sees a backward clock and `days_elapsed` never goes negative. All pinned literals preserved (interest_days 1, interest 1+1, total 7302).
2. Absolute `version == 1`-at-creation literals are not pinned by PRD §2.5 (only "increments by exactly 1 on every mutation"; the frozen assertions likewise require only ≥1). Translated as capture-then-increment relative assertions in `complainant_creation_system_fields`, `employer_band_recomputed_on_patch`, `amend_happy_path_bumps_version`, `assign_transfer_conserves_active_assignments`.
3. Date-typed response fields are compared by their first-10-chars date part, matching the frozen fixtures' own `_to_date` convention (PRD pins day granularity, not string rendering).
4. `second_response_same_party_rejected` — PRD states the prohibition without naming the error; `ERR_INVALID_STATE` is the only §2.8 step-6 fit. Emitted, flagged.
5. `systemic_lifecycle_auto_transitions` — `RESOLVED` is not directly observable (no GET endpoint for SystemicCase exists); I assert the observable resolution side effect (seal lifted to NONE on the final withdraw response and on re-reads) plus all link-response transitions and counts.
6. `investigator_interview_thirty_minute_buffer` — the design's aspect text says "20-minute gap" but its payload pins 11:29 after a 10:00–11:00 interview (29 minutes); I followed the payload (29 < 30 → rejected, exactly-30 → accepted).
7. `charge_list_pagination_and_filters` — "filtered query returns 11 rows" asserted as `total_count == 11` with all returned rows matching the filter (default limit 10 pages the filtered result; no limit override invented).

Orchestrator re-audit (independent): 79 tests collected clean; AST walk found 79 tags, 0 unresolved, 0 active instances missing a test.

## Step 6: Generate implementation — 2026-10-02T11:01:51.167496556Z

Implementation complete. Final report:

## (a) File tree (line counts) — `workspace/implementation/`

```
 10  start.sh                 (guarded install, exec, $PORT, 0.0.0.0)
  1  requirements.txt         (flask>=3.0,<4.0)
 66  app.py                   (app factory, error handlers, blueprint wiring)
315  constants.py             (every pinned constant, defined once)
 93  errors.py                (30 error ids + HTTP status map + ApiError)
 54  store.py                 (in-memory dicts, logical clock @ 2026-09-01, empty at boot)
226  helpers.py               (envelope, auth, pagination, timestamps, OCC-free bumps)
170  validation.py            (schema validators, step-3 pipeline)
285  serializers.py           (15 entity serializers, explicit field lists)
107  domain/screening.py      (size bands, agency match, intake screening)
102  domain/priority.py       (priority score, lazy OVERDUE, sticky escalation)
109  domain/remedy.py         (PROVISIONAL/FINAL valuation, PATCH re-band)
221  domain/cascades.py       (investigation/mediation/systemic cascades, disclosures)
 29  routes/clock_routes.py   (POST /eeoc/_clock/set_current_utc — inside prefix)
129  routes/reference.py      (deferral-agencies, employers+PATCH, complainants)
340  routes/charges.py        (intake, detail w/ sealed rules, list, amend, withdraw)
335  routes/mediation.py      (offer, respond, sessions, conclude)
323  routes/investigation.py  (cases, assign, evidence, interviews)
319  routes/determinations.py (draft, submit, review + 3-link cascade)
234  routes/conciliation.py   (offers OCC, accept, fail, remedy-packages)
202  routes/rts.py            (right-to-sue issue/list, vacate-settlement)
 92  routes/systemic.py       (open, link, seal)
 74  routes/disclosures.py    (explicit disclosures, audit list)
```
All 42 endpoint method+path pairs registered (verified via `url_map`).

## (b) py_compile
All 25 `.py` files compile clean (`FINAL_COMPILE_ALL_OK`), each file tail-verified at write time; `import app` succeeds (no dangling imports); `pyflakes` clean after removing unused imports.

## (c) Constants grep audit
140 distinct `constants.X` references across the tree — **all resolve** (`MISSING: NONE`). Values pinned: 180/300 deadlines, 15/20 size thresholds, band edges 15/20/100/200/500, rate 0.05/365, caps 5M/10M/20M/30M, 90-day filing window, 30-day evidence window, 30-min buffer, 10-day vacate window, 2 rounds, overdue 15/cap 45, multiplier 1.5, ceiling 100, threshold 80, consolidation 3/2, severity 30/25/20/15, age tiers 90/180/365 → 0/10/20/35, pagination 10/1/100/0, clock boot 2026-09-01T00:00:00Z.

## (d) Guard wiring audit
Every guard has ≥1 request-path callsite: `authenticate`/`require_roles` ×42 (every endpoint), `check_party_ownership` ×7, all domain guards (screening, priority, remedy, cascades, SoD, disclosure) wired. Every callsite target exists (verified by clean import + pyflakes).

## (e) Smoke transcript (ports 45555, 52937 — both dynamically allocated, both killed)
- Boot probe `GET /eeoc/charges` → 200 empty list.
- `POST _clock/set_current_utc` → 200 `{"current_utc":"2026-09-01T00:00:00Z"}`.
- Deferral agency → 201; duplicate state → **409 ERR_DUPLICATE_AGENCY_STATE**.
- Employer(25) → 201 `size_band=FROM_20_TO_100`; complainant → 201.
- Charge (RACE+AGE, count 25, CA/300-day agency) → 201 DOCKETED, TIMELY_CONFIRMED, covered=[RACE,AGE], dual_filed=true, deadline 2026-06-01+300=2027-03-28; read-back 200.
- Negatives: no headers → 401; Mediator list → 403 FORBIDDEN_ROLE; bogus basis → 400; future incident → 422; bad id → 404.
- Mediation accept×2 → ACTIVE; conclude SETTLED → charge CLOSED_SETTLED/500000/MEDIATION.
- Deep path: amend wrong version → **412**; decline → UNDER_INVESTIGATION + auto InvestigationCase(OPEN); assign → evidence request (issued 2026-09-01, due 2026-10-01) → GATHERING, open=1, score=25; wrong investigator → 403; interview 20-min gap → **409 ERR_INTERVIEW_BUFFER_CONFLICT**, 30-min gap → 201; CAUSE determination → submit → reviewer==preparer → **409 SoD**; approve → CONCILIATION; PROVISIONAL package band FROM_20_TO_100, interest_days=123, capped 5000000, total 5742300 (hand-verified: 365000×0.05×123/365=6150 per component, round-then-sum); offers alternate (OUT_OF_TURN 409, STALE 412 in priority order); accept → FINAL (snapshot band), CLOSED_SETTLED at offer 900000; vacate conciliation → 409; systemic link → SEALED + EXPANDING; CP sealed read → 403; privileged read auto-logs INTERNAL_ACCESS (count 1); PARTY_CONSENT on sealed → 403 ERR_DISCLOSURE_FORBIDDEN; COURT_ORDER → 201; RTS premature → 422; clock +182d → issued (ELAPSED_180_DAYS, deadline +90d), charge RTS_ISSUED, systemic auto-RESOLVED lifting seal to NONE; mediation settle → vacate within window → UNDER_INVESTIGATION, settlement zeroed, mediation VACATED (amount retained), investigation auto-created OPEN; second vacate → 409; re-offer → round 2. Servers killed (`SERVER_STOPPED` both times; ports confirmed closed).

## (f) Interpretations chosen
1. **Amend that strips all coverage**: PRD §3.3 names only the DISMISSED_UNTIMELY flip, but the entity spec says "when empty the charge is DISMISSED_NO_JURISDICTION" — I flip to DISMISSED_NO_JURISDICTION with the same cascade (owner NONE, mediation declined, investigation closed/waived).
2. **Systemic link "terminal" set**: §3.9's terminal definition (incl. CLOSED_SETTLED) is used for the link gate, not the narrower §3.2 lifecycle set — consistent within §3.9.
3. **Sessions on orphaned ACTIVE mediation** (charge RTS_ISSUED): allowed — PRD pins ERR_INVALID_STATE only for *conclude*; §3.4 says sessions are scheduled "while a mediation is active", no charge-state gate stated.
4. **Interviews during SUSPENDED_MEDIATION**: allowed — PRD explicitly gates evidence requests (OPEN/GATHERING) and determinations (GATHERING) but states no state gate for interviews; only CLOSED is rejected.
5. **UNDER_15 cap tier**: undefined by PRD ("never reaches conciliation"); a PATCH can still re-band a PROVISIONAL package to UNDER_15 — treated as cap 0 rather than crashing.
6. **Pagination bounds**: out-of-range integers clamp to [1,100]/[0,∞) (PRD states min/max but no error); non-integer → 400.
7. **Date inputs**: accept `YYYY-MM-DD` and `YYYY-MM-DDT00:00:00Z`; reject non-midnight times (400). Outputs always `T00:00:00Z`.
8. **Mediation-offer gate order**: charge-state (409) → prior-non-terminal (ERR_INVALID_STATE, priority 6) → round cap (ERR_MEDIATION_ROUND_EXHAUSTED, priority 8).
9. **Lazy transitions** (OVERDUE/EXPIRED/HELD) bump `version`/`updated_at` as mutations; `days_elapsed_since_filing`/`priority_score` recompute without bumping; `priority_escalated` flip bumps the charge.
10. **Version starts at 1**; `created_at`/`updated_at`/`api_request_timestamp` derive from the logical clock (PRD: "never reads the wall clock"), millis precision; clock echo omits `.000` when zero.
11. **Evidence respond on waived/closed request** → ERR_INVALID_STATE (the request's own state gate), not ERR_CHARGE_ALREADY_CLOSED.
12. **Assign on CLOSED investigation**: allowed (no gate stated). Empty PATCH employer bumps version and re-bands.

Orchestrator verification: all 25 files compile; url_map shows 43 rules = 42 API + Flask static; clock route POST /eeoc/_clock/set_current_utc confirmed; start.sh foreground with guarded flask install, exec python3 app.py.

## Step 7: Test-fix iteration loop — 2026-10-02T11:06:42.481809557Z

Clean 8-round sweep on the first iteration — no diagnostic work was needed.

## Summary

- **Iterations run:** 1 (single 8-round parallel sweep, all rounds run to completion)
- **Result:** 79/79 tests passed in every round — 0 failed, 0 errors, 0 skipped, across all 8 rounds. No flakiness detected; no failing-test union to process.
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `test_suite/`:** none
- **Fixes applied to `implementation/`:** none
- **Sibling unasserted paths:** not applicable — no test-side fixes were made, so no coverage-vs-PRD skew was introduced this session.

**Output contract:** all 8 evidence files remain in place at `/home/ubuntu/github/CodingPRD/tasks/task_3463_discrimination_charge_intake_mediation_right_sue_issuance/workspace/implementation/results.{1..8}.json`. One note: my first verification one-liner read a nonexistent `outcome` key and falsely reported 79 failing tests per round; the actual schema uses `status`, and with the correct key every test in every round reads `passed`.

Orchestrator independent verification: parsed all 8 results files directly — every round total=79 passed=79 nonpass=0 (ALL_CLEAN). Files present with sweep mtimes.

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T11:06:42.481809557Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the granularity Step 7 exercised; no PRD_FINALIZED.md produced.

## Step 9: PRD completeness scan — 2026-10-02T11:32:36.783294679Z

All 22 hunks landed as planned. Final verification is complete — files differ (not byte-identical), +3 lines, +6,002 chars.

## Summary

**Source vs output:** `PRD.md` (309 lines, 55,381 chars) → `PRD_COMPLETED.md` (312 lines, 61,383 chars). `diff -q`: files differ. 21 paragraphs revised + 3 lines inserted (24 added / 21 removed in diff terms).

**Counts:** 21 ambiguity-pin hunks · 1 defective-PRD mismatch-revision · 1 IMPL BUG reported (PRD left unchanged on that point).

### Changes (all edits to `workspace/PRD_COMPLETED.md`)

1. §2.2 — insert — ambiguity — added bullet pinning framework fallback errors `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) using the standard envelope — `app.py:32-56`.
2. §2.3 — revise — ambiguity — out-of-range integer `limit`/`offset` clamp into [1,100]/[0,∞); non-integer → `ERR_VALIDATION_FAILED`; equal timestamps ordered by insertion sequence — `helpers.py:180-209`.
3. §2.4 — revise — ambiguity — `to_iso8601` must be timezone-aware; clock set unconditionally (no monotonicity check); `current_utc` echo omits fractional part when zero, else millis — `clock_routes.py:22-29`, `helpers.py:42-50`.
4. §2.4 — revise — ambiguity — date inputs accept bare `YYYY-MM-DD` or a timezone-aware timestamp normalizing to midnight UTC (other times → 400); date outputs always `YYYY-MM-DDT00:00:00Z`; timestamp inputs require a timezone and echo at millis — `validation.py:135-160`, `helpers.py:53-57`.
5. §2.4 — revise — ambiguity — lazy flips (OVERDUE/EXPIRED/HELD) bump version/updated_at; pure recomputations (`days_elapsed_since_filing`, priority score, request counters) do not; the `priority_escalated` flip does — `cascades.py:121-139`, `priority.py:69-102`.
6. §2.5 — revise — ambiguity — `version` starts at 1 on creation; `settled_at`/`concluded_at`/`disclosed_at` use the same millisecond format — `helpers.py:75-84`, `serializers.py`.
7. §2.8 step 3 — revise — ambiguity — body fields not named in an endpoint's schema are ignored, not rejected — `validation.py` (validators read only named fields).
8. §2.9 — revise — ambiguity — the SEALED read restriction and auto-logging apply to the charge *detail* read; list endpoints return SEALED charges to all list-authorized roles unfiltered and without audit rows — `charges.py:163-192` vs `charges.py:211-223`.
9. §3.1 — revise — ambiguity — an employer PATCH counts as an update even when it changes nothing (version bumps, `size_band` recomputed, re-banding cascade still runs and re-stamps packages) — `reference.py:82-110`, `remedy.py:85-109`.
10. §3.2 — revise — ambiguity — `employee_count_at_incident` pinned as a non-negative integer — `charges.py:97-99`.
11. §3.3 — revise — ambiguity — amending `basis_codes` *or* `incident_date` re-runs the full §3.2 screening against the original `received_date`; either `DISMISSED_UNTIMELY` or `DISMISSED_NO_JURISDICTION` flips the charge to that terminal state with the dismissal cascade — `charges.py:283-303`.
12. §3.4 — revise — ambiguity — session scheduling is gated only on the mediation being `ACTIVE`; the charge's status is not consulted, so an RTS-orphaned ACTIVE mediation still accepts sessions — `mediation.py:204-255`.
13. §3.4 — revise — ambiguity — on IMPASSE, an investigation in any status other than `SUSPENDED_MEDIATION` (e.g. a never-suspended `OPEN`) is left unchanged — `mediation.py:321-331`.
14. §3.5 — revise — ambiguity — assignment is gated neither on the investigation's status (a `CLOSED` case may be reassigned) nor on the charge's — `investigation.py:112-137`.
15. §3.5 — revise — ambiguity — responding to a `RESPONDED`/`WAIVED` request (incl. cascade-waived on a terminal charge) → `ERR_INVALID_STATE`; the charge's terminality is not separately reported — `investigation.py:229-237`.
16. §3.5 — revise — ambiguity — interviews may be logged while the case is `OPEN`, `GATHERING`, or `SUSPENDED_MEDIATION`; only `CLOSED` → `ERR_INVALID_STATE` — `investigation.py:269-274`.
17. §3.7 — revise — ambiguity — an offer's `amount_cents` is any integer, no sign/minimum constraint (contrast mediation settlement > 0) — `conciliation.py:95`.
18. §3.7 — revise — ambiguity (with corrected false premise) — `UNDER_15` *is* reachable on a PROVISIONAL package (jurisdiction uses the incident snapshot, not the current band); when `band_used` is `UNDER_15` the cap is treated as 0 cents; FINAL cannot land on `UNDER_15` — `remedy.py:52-54`.
19. §3.8 — revise — **mismatch-defective** (leg b: self-contradictory) — "any non-terminal, non-conciliating status" contradicted §3.8's own six-state issuance-cascade enumeration and §3.2's rationale (CLOSED_SETTLED is non-terminal only for vacatur); revised to pin the six issuable states and `CLOSED_SETTLED` → `ERR_INVALID_STATE`; same hunk adds a parenthetical that a duplicate-notice request in practice reports `ERR_CHARGE_ALREADY_CLOSED` per §2.8 precedence — `rts.py:39-90`.
20. §3.8 — revise — ambiguity — vacatur reopen: only a `CLOSED` investigation moves to `GATHERING`; a case in any other status (e.g. `SUSPENDED_MEDIATION`, since the §3.4 settle cascade never closes the investigation) is left unchanged — `rts.py:193-199`. (Pinned corner: such a charge returns to `UNDER_INVESTIGATION` with a suspended investigation; only a later mediation round ending in impasse resumes it.)
21. §3.9 — revise — ambiguity — the link gate's "non-terminal" uses this section's six-state set (lifecycle terminals + `CLOSED_SETTLED`) — `systemic.py:73`, `constants.py:186-197`.
22. §3.9 — revise — ambiguity — systemic status is forward-only (`OPENED`→`EXPANDING`→`CONSOLIDATED`→`RESOLVED`); the resolution seal-lift is final (a charge later re-opened by vacatur is not re-sealed and does not un-resolve the case) — `cascades.py:145-192`.

### IMPL BUG (PRD_COMPLETED.md unchanged on this point)

- `implementation/routes/mediation.py:225-242` — PRD §2.8: "the first failing check wins — its error is returned and later checks are not evaluated. The ordering is: … 8. **Business constraints** — … mediator session overlap (`ERR_SESSION_OVERLAP`) … 9. **Business-temporal rules** — … a session scheduled in the past (`ERR_SESSION_IN_PAST`) …" — the impl evaluates the past-start check (step 9) *before* the overlap loop (step 8), so a session request that is both in the past and overlapping returns `ERR_SESSION_IN_PAST` where the pipeline mandates `ERR_SESSION_OVERLAP`. §2.8 is self-consistent and trivially implementable, so the impl is at fault — suggested fix: move the overlap loop (`mediation.py:233-242`) above the `scheduled_start < now()` check (`mediation.py:225-229`).

### Verification notes

- All 12 known-interpretation sites verified against code and classified: #1-#7, #9-#12 pinned (edits 11, 21, 12, 16, 18, 2, 4, 5, 6, 15, 14/9 respectively); #8 (mediation-offer gate order state→prior-non-terminal→round-cap) is already pinned by the §2.8 pipeline — no change needed.
- Dead-code sweep: every §5 catalogued error id is raised in impl; every impl `ApiError` id is catalogued (plus the three framework fallbacks now pinned). The one-notice check (`rts.py:84-90`) is reachable-but-shadowed by the terminal-state gate — behavior complies via §2.8 precedence, clarified in edit 19, not a bug.
- Role tables (42 endpoints), state machines, calculations (priority score, remedy valuation round-then-sum, cap tiers), lazy-transition triggers, and response shapes were walked endpoint-by-endpoint against the PRD; no other divergences found.

Orchestrator adjudication: verified PRD.md §2.8 lines 117-118 (overlap step 8 before past step 9) — IMPL BUG confirmed against verbatim PRD. Verified §3.8 self-contradiction (line 209 "any non-terminal, non-conciliating status" vs §3.8 six-state cascade enumeration and the CLOSED_SETTLED-vacatur rationale) — defective-PRD revision exonerated (self-contradiction leg).

## Step 9b: Impl-bug fix + re-sweep — 2026-10-02T11:32:36.783294679Z

Orchestrator-applied the Step 9 IMPL BUG fix: `workspace/implementation/routes/mediation.py` `schedule_session` — moved the half-open overlap loop (ERR_SESSION_OVERLAP, §2.8 step 8) above the past-start check (ERR_SESSION_IN_PAST, §2.8 step 9), with a comment citing the pipeline. PRD_COMPLETED.md untouched (impl moved toward PRD). py_compile clean.

Full 8-round parallel stability sweep re-run (per-test-server isolation, dynamic ports via the runner registry): all 8 rounds 79/79 passed, 0 failed/errors/skipped — ALL_CLEAN. Fresh results.{1..8}.json regenerated in workspace/implementation/.
