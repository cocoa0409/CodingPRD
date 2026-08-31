# Worklog — task_2144_antitrust_competition_compliance

## Step 1: Create task directory — 2026-08-23T03:57:04.000Z

Created `tasks/task_2144_antitrust_competition_compliance/` and `tasks/task_2144_antitrust_competition_compliance/workspace/`.

## Step 3: Copy shared files — 2026-08-23T03:57:23.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2144_antitrust_competition_compliance/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-23T04:52:00.000Z

All three scaffold artifacts are generated and lint-clean.

**Generated** in `/home/ubuntu/github/CodingPRD/tasks/task_2144_antitrust_competition_compliance/`:

- **SCAFFOLD.yaml** (2717 lines) — §1.0–§1.7. Profile: `compliance_audit` × `posture_driven_gating`, **flat** topology, **parallel** state-machine shape, **segregation_of_duties** role model, `immediate` consistency; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. `api_prefix: /compliance`.
  - **16 entities** (BusinessUnit, EmployeeProfile, TrainingCurriculum, TrainingAssignment, TradeAssociation, AssociationParticipation, AssociationMeeting, MeetingAttendance, CompetitorContact, Transaction, HsrAnalysis, Site, ReadinessDrill, DocumentAudit, LeniencyApplication, RiskAssessment) — above the Expert band by design.
  - **13 state machines / 72 transitions**: BusinessUnit posture (derived gate OPEN/RESTRICTED/FROZEN), AssociationParticipation (fork-join with divergent branch side effects + SUSPENDED<->ACTIVE and UNDER_REVIEW->ACTIVE cycles), CompetitorContact (UNDER_REVIEW<->REMEDIATION_REQUIRED cycle), LeniencyApplication (**parallel dimensions** marker_status x disclosure_status joined once at PERFECTED), MeetingAttendance, Transaction (EXEMPT<->ANALYZED re-analysis cycle), EmployeeProfile clearance, TrainingAssignment, TradeAssociation, ReadinessDrill, DocumentAudit, RiskAssessment/HsrAnalysis supersede.
  - **13 calculations**, incl. two dual-variant across different domains (`market_risk_index` BASELINE vs INCIDENT_ADJUSTED on BusinessUnit; `hsr_size_of_transaction` SIGNED_DEAL vs MARKET_VALUE on Transaction) and three combinatorial modes: (a) `contact_exposure_points` nested caps + band multiplier, (b) `leniency_penalty_estimate` pinned round-per-year-then-sum, (c) `participation_review_load_minutes` pinned non-circular evaluation order (110, not the fixed-point 125). Two interval calculators with **opposite** semantics: delegate closed-closed + 60-min briefing buffer vs Site half-open + aggregate capacity.
  - **26 ordered validations**, **79 endpoints** (incl. `POST /compliance/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`), **43 error codes**, **4 roles** (ComplianceAdmin/AntitrustCounsel opaque; BusinessLead->BusinessUnit, Employee->EmployeeProfile entity-backed), **2 OCC concurrency rules** (BusinessUnit version on risk-assessment create; Transaction version on hsr-analysis create).

- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1863 lines) — **23 instances**, all nine §0.5 rules >=2: dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 3 (cyclic/parallel/branching, three different entities), transitive_cascade 2 (two depth-4 chains from different triggers), priority_pair_validation_conflict 3 (state<->fiscal, safety<->referential, safety<->temporal), boundary_precision_check 3 (HSR `>=` at exactly 12000000000; empty incident set; zero-density `ceil`), cross_entity_state_dependency 3 (Attendance->Participation, Contact->Training, Leniency->RiskAssessment), resource_temporal_overlap 2, compensating_invariant 2 (exposure points vs counsel review minutes). All formula-derived asserts are pre-computed literals (e.g. 540000009, 110, 40.00, 85.00, 51.00, 864000013).

- **SCAFFOLD_CORNER_DESIGN.yaml** (2755 lines) — **62 instances (51 with recipes + 11 `excluded_because` stubs)** across all nine claim-extraction sections: entities 10, state_machines 10, calculations 8, validations 8, endpoints 3, errors 2, rbac 5 (incl. both SoD pairs), cross_cutting_complexity_layers 4 (both OCC guards, RESTRICTED threshold, audit->incident cascade), consistency_model 1.

**Lint verdict** (pasted verbatim):
```
Coverage
  §1.5 endpoints declared:    79
  §1.1 entities declared:     16
  §1.8 instances scanned:     23
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  649

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-checks passed: zero unbound `${var}` placeholders across both design files, zero duplicate instance names, every `excluded_because` reference resolves to a real §1.8 instance name, no forbidden concurrency vocabulary, all endpoint roles present in the RBAC matrix.

Note: no sibling task directory was read at any point — the scaffold was derived solely from the scenario text and the generator skill.

## Step 4: Generate PRD — 2026-08-23T05:02:00.000Z

PRD generated and verified. Output: `/home/ubuntu/github/CodingPRD/tasks/task_2144_antitrust_competition_compliance/workspace/PRD.md` (486 lines, built incrementally in 7 appends — no truncation).

**Sections written**

- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 10 subsections, domain-derived: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Record Identity/Timestamps/Logical Clock, 2.5 Precision & Rounding, 2.6 OCC on Parent Records, 2.7 The Validation Ladder (all 26 rungs in priority order), 2.8 Exposure Ledger & Business-Unit Posture, 2.9 Segregation of Duties, 2.10 Occupancy & Capacity Conventions
- §3 Business Logic — 9 subsections: 3.1 Units/People/Budgets, 3.2 Training, 3.3 Risk Assessment & Banding, 3.4 Trade Associations & Participation Fork/Join, 3.5 Meetings/Bookings/Minutes Review, 3.6 Competitor Contact Log, 3.7 HSR Merger Control, 3.8 Readiness Drills & Document Audits, 3.9 Leniency Marker Race & Disclosure
- §4 Endpoint Definitions (4-column table)
- §5 Error Code Catalogue (2-column table)

**Coverage verification (scripted against SCAFFOLD.yaml)**

- 16 entities: all covered; 119 entity field names present in backticks
- 13 state machines: all covered, every transition's from/to states, preconditions->error pairings and side effects (including the 4-hop FLAGGED cascade, the FROZEN cascade order, the fork-join and both revision cycles, and LeniencyApplication's two independent dimensions + the PERFECTED join)
- 13 calculations: all expressed as precise prose with pinned evaluation orders (review-load base-keyed surcharge -> 110 not 125; per-year round-then-sum penalty; raw cap before band multiplier; findings cap before verdict points; 2dp violation-ratio rounding)
- 26 validations: all enumerated in priority order in §2.7 with error_id, HTTP status, and full `applies_to` endpoint lists
- 79 endpoints: 79 rows in the §4 table
- 43 error codes: 43 rows in §5; all 43 ids also mentioned in §2/§3 narrative

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 119 required, 119 present, 0 missing
- endpoints[].request_body: 76 required, 76 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 26 checked, 26 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 13 machines / 78 transitions checked, 78 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 26 checked, 26 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 79 checked, 79 expressed, 0 missing
- entities[].fields[] structured content: 119 checked, 119 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (legal/business branch, CLEAN|CONCERN vs VIOLATION verdicts, BASELINE vs INCIDENT_ADJUSTED, SIGNED_DEAL vs MARKET_VALUE, marker vs disclosure dimension, closed vs half-open interval), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 660
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 matches the canonical block byte-for-byte; no fuzzy words (`approximately`/`roughly`/`conservatively`/`around`/`~`) anywhere; no pseudocode operators anywhere; file ends at the §5 table with no audit footer. The two withheld design indices were not opened.

## Step 6: Generate implementation — 2026-08-23T05:20:00.000Z

All 79 endpoints are registered and both smoke suites pass clean.

**Modules written** (`.../task_2144_antitrust_competition_compliance/workspace/implementation/`, 12 files, ~120 KB):

| File | Role |
| --- | --- |
| `start.sh` | Foreground launcher, `exec python3 app.py`, guarded `pip install` (no-op once Flask present), `PORT` env / default 10000 |
| `app.py` | Flask entry point, blueprint registration, per-request lock, lazy-expiry sweep, `ApiError`/`HTTPException` handlers |
| `store.py` | In-memory dicts only (16 collections), logical clock (startup default `2026-08-01T00:00:00Z`), UUID/timestamp/`_seq` helpers |
| `errors.py` | 43-entry error catalogue with HTTP statuses |
| `envelope.py` | `meta`/`response_type`/`data` envelope, `req_*` ids, pagination meta |
| `ladder.py` | Ladder rungs 1-7 primitives (auth, shape validators, pagination, entity-specific 404 lookups) + per-request dirty/version bookkeeping |
| `calc.py` | All 13 calculations + every declared constant, `Decimal`/`ROUND_HALF_UP` throughout |
| `domain.py` | Ledger, posture derivation, 4-hop cascades, training/marker lazy expiry, leniency ranking, 16 serialisers |
| `api.py` | `ok`/`created`/`listing` helpers (commit-before-serialise) |
| `routes_core.py`, `routes_assoc.py`, `routes_biz.py`, `routes_ops.py` | 79 route handlers |

**Coverage**: 79/79 endpoints, 16/16 entities, 13/13 state machines (incl. the fork-join participation, the cyclic contact loop, the two-dimension leniency row with the PERFECTED join, and derived `BusinessUnit.posture`), 13/13 calculations, all 26 ladder rungs in strict ascending order, 43/43 error codes, both OCC fields (`expected_business_unit_version`, `expected_transaction_version`).

**Key fidelity decisions**: strict ladder order (rung 9 SoD before rung 10 transition legality; rung 10 masks rung 13 for filing); pinned review-load order (TIER_3_HIGH @100 % -> 110, not 125); per-year penalty rounding before summing (worked example -> 900 000 015); raw contact cap before the band multiplier; findings cap before verdict points; closed-closed delegate occupancy vs. half-open site capacity (adjacency legal for sites — the sweep excludes `window_end` so back-to-back windows never conflict in either creation order); version bumped exactly once per row per request via a dirty-set commit, so idempotent posture recomputes don't double-bump.

**Storage**: purely in-memory Python dicts; no SQLite, no disk writes, no seeding — verified on a fresh boot that all nine listable collections report `total_count = 0`.

**Verification**: `python -m py_compile` clean on all 12 `.py` files; server booted via `PORT=... bash start.sh` three times, each answering HTTP within ~2 s. Two smoke suites against a live server passed 55/55 and 25/25 checks respectively, covering the exposure ledger and OPEN->RESTRICTED->FROZEN->thaw path, the freeze cascade (participation suspension + future-attendance cancellation with reservations held), association-prohibition cascade, VIOLATION minutes review with its 4-hop cascade, both segregation-of-duties pairs, HSR variant divergence and threshold boundary (size exactly 12 000 000 000 -> not below threshold), lazy training expiry (strict at `expires_at`), marker expiry + posture thaw, leniency ranking/penalty, drill adjacency vs. capacity, pagination and auth/RBAC errors. Test servers were stopped afterwards.

## Step 5: Generate unit tests — 2026-08-23T05:34:00.000Z

Test infrastructure and suite generated for `task_2144_antitrust_competition_compliance`.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2144_antitrust_competition_compliance/`)

`test_helpers/` (9 files, 1,972 lines): `__init__.py`, `types.py` (16 entity TypedDicts + 27 enums), `api_client.py` (all 79 endpoint methods under `/compliance`), `api_errors.py` (43 error ids + HTTP map, registered with the framework), `assertions.py` (per-entity assertions plus the exposure-ledger and review-minutes identity checkers), `factories.py`, `constants.py`, `test_users.py` (opaque `ComplianceAdmin`/`AntitrustCounsel` constants plus `make_counsel_headers`, and mandatory per-instance `make_business_lead_headers`/`make_employee_headers` for the two `entity_backed` roles), `fixtures.py` (5-tier composites: `create_trained_employee`, `setup_active_participation`, `setup_attendance_in_minutes_submitted`, `setup_high_band_unit`, `setup_granted_marker`, `setup_filed_transaction`, `adjust_exposure`, ...).

`test_suite/` (conftest + 10 domain-named files, 3,370 lines): `test_01_programme_setup_and_reference_data` ... `test_10_posture_gates_and_access_control`.

**Per-queue translation**

- Queue A (Difficulty): **23/23 instances translated, 0 skipped**, 46 tests (exactly 2 per instance, as the skill's coverage audit requires).
- Queue B (Corner): **51/51 non-stub instances translated, 0 skipped**, 52 tests (`business_unit_creation_returns_declared_defaults_and_version_one` got 2 — defaults/version and the bare-UUID claim). All **11 `excluded_because:` stubs** were left untranslated; every `difficulty_instance` cross-reference was programmatically verified to resolve to a real `SCAFFOLD_DIFFICULTY_DESIGN.yaml` `name:`.

No instance failed the PRD-first two-condition filter. Three individual *assertions* inside otherwise-kept corner instances were dropped under the `default-value` silence pattern, where the design index asserted a null-before-set field the PRD never declares an initial value for: `review_opened_by_user_id`/`remediation_instructions`/`remediation_response` on a fresh contact, `filed_at`/`waiting_period_end` on a DRAFT transaction, and `expires_at` on a WAIVED assignment. Each instance is still covered by its remaining PRD-grounded assertions.

**Verification**

- `python -m py_compile` clean on all 19 files; every test module imports; `pytest --collect-only` -> **98 tests collected**.
- **98 tests / 98 `Design:` tags** — exactly one per test, none dual-tagged, none untagged, zero tags pointing at a non-existent instance, zero stubs translated.
- Every `PRD §x.y: "..."` citation was whitespace-normalised and checked as a literal substring of `workspace/PRD.md`: **0 mismatches**.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no "scaffold"/§1.x references leak into generated comments or docstrings.

## Step 7: Run tests and iterate — 2026-08-23T05:42:00.000Z

All background tasks have finished on their own, and the sweep is clean.

**Summary**

- **Iterations run:** 2 (one 8-round parallel sweep to diagnose, one to confirm; a third launch was aborted at boot by an unrelated host-level process kill and was re-run rather than counted).

- **Tests deleted:** none. No test failed the STEP 1a coverage check or required deletion under a PRD-silence category.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:** none.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_07_merger_control_hsr_analysis.py` — `test_filing_a_transaction_that_has_never_been_analysed_is_refused`: relaxed the exact-error assertion to `validate_error_is_one_of([ERR_TRANSACTION_NOT_ANALYZED, ERR_INVALID_STATE])`. PRD §3.7 ("Filing ... is legal only from `ANALYZED` ... anything else is refused with `ERR_TRANSACTION_NOT_ANALYZED`") and ladder rung 13 name `ERR_TRANSACTION_NOT_ANALYZED`, while ladder rung 10 ("The target resource is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE`") sits at a strictly higher priority and reports `ERR_INVALID_STATE` for a `DRAFT` transaction. Two PRD-faithful readers diverge, so the PRD names a member of the set but not the specific choice — the sanctioned coverage correction, not a weakening (HTTP 409 and the unchanged-status assertion are retained).
  - `test_suite/test_07_merger_control_hsr_analysis.py` — `test_cleared_transaction_is_terminal_and_refuses_a_second_filing`: same relaxation. Here rung 10 additionally states verbatim that `ERR_INVALID_STATE` "covers every attempt from a terminal state", and `CLEARED` is declared terminal, so the PRD in fact leans toward `ERR_INVALID_STATE` while §3.7's "anything else" clause still admits `ERR_TRANSACTION_NOT_ANALYZED`.

- **Final state:** 8/8 parallel rounds, 98/98 tests passed in every round, zero flakes.

**Orchestrator verification note:** the subagent left no `results.*.json` on disk at exit, so the orchestrator re-ran the full 8-round parallel sweep independently. Result confirmed: `results.1.json` .. `results.8.json` each report `total: 98, passed: 98, failed: 0`.

## Step 8: Finalize PRD — 2026-08-23T05:46:00.000Z

PRD.md 486 lines -> PRD_FINALIZED.md 486 lines (0.0% line delta; two lines revised in place, +718 characters).

Changes:
- §2.7 rung 13 (Cross-entity state preconditions) — revise — the HSR clause no longer folds the transaction's `ANALYZED` status into rung 13; it now requires only that the transaction's `ACTIVE` analysis exist and carry `filing_required` of true for `ERR_TRANSACTION_NOT_ANALYZED`, and states explicitly that the status itself is tested earlier at rung 10 — implementation/routes_biz.py:244-248
- §3.7 (Merger Control / filing paragraph) — revise — replaced "anything else is refused with `ERR_TRANSACTION_NOT_ANALYZED`" with the two-rung split: any status other than `ANALYZED` (`DRAFT`, `EXEMPT`, `FILED`, terminal `CLEARED`) fails rung 10 with `ERR_INVALID_STATE`; only from `ANALYZED` is the analysis consulted, and a missing `ACTIVE` analysis or `filing_required` false yields `ERR_TRANSACTION_NOT_ANALYZED`; both 409 — implementation/routes_biz.py:244-248, implementation/errors.py:32,36

Per-edit pre-edit search log:
- Edit 1 (§2.7 rung 13): (a) subject — which condition rung 13 owns for HSR filing, and whether the sentence's other three clauses stay accurate. (b) enumerated/read: `grep -rn "ERR_TRANSACTION_NOT_ANALYZED\|ERR_INVALID_STATE"` across all of implementation/ (single NOT_ANALYZED site: routes_biz.py:248; 40 INVALID_STATE sites across routes_biz/routes_assoc/routes_core/routes_ops); read routes_biz.py:240-256 (filing), plus the three parallel rung-13 clauses I left untouched to confirm the shared sentence stays true — routes_assoc.py participation/attendance path (`ERR_PARTICIPATION_NOT_ACTIVE`, routes_assoc.py:427-446 region and 172), routes_ops.py:287-291 (marker request: `ERR_INVALID_STATE` on `marker_status != NONE` first, then `ERR_RISK_BAND_TOO_LOW`), routes_ops.py:337-341 (disclosure: `ERR_INVALID_STATE` on `disclosure_status != DRAFT` first, then `ERR_MARKER_NOT_GRANTED`); errors.py for the 409 mapping of all four codes. (c) adjustment — scoped the rewrite to the HSR clause only and phrased the status point as "not tested here but earlier, at rung 10" rather than a general statement about rung 13, since the marker and disclosure clauses in the same sentence exhibit the same rung-10-first ordering and a broader claim would have needed verifying for the attendance clause too; kept "All four carry HTTP 409" verbatim.
- Edit 2 (§3.7 filing paragraph): (a) subject — the error code the filing endpoint returns for each way filing can be refused. (b) enumerated/read: routes_biz.py:240-256 (`file_transaction`: status guard -> `ERR_INVALID_STATE`; `domain.active_analysis` None-or-not-`filing_required` -> `ERR_TRANSACTION_NOT_ANALYZED`), routes_biz.py:19 (`TRANSACTION_STATUSES` = DRAFT/ANALYZED/EXEMPT/FILED/CLEARED, to enumerate the statuses my sentence names), routes_biz.py:258-268 (`clear_transaction`, the adjacent transition whose `ERR_INVALID_STATE`/`ERR_WAITING_PERIOD_ACTIVE` prose I left verbatim), routes_biz.py:280-303 (`create_hsr_analysis` — the only writer of `status = ANALYZED|EXEMPT` and of `SUPERSEDED` on the prior analysis, confirming which statuses can reach the filing endpoint), domain.py:53 `active_analysis`, errors.py:32/36 (both codes 409), and a grep of PRD_FINALIZED.md for other filing mentions (§1, §2.2 role list, §4 endpoint table lines 405-408) to confirm no other passage restates the refusal code. (c) adjustment — wrote "a missing `ACTIVE` analysis or one carrying `filing_required` of false" instead of asserting the `ANALYZED`-with-no-active-analysis case is impossible, since `create_hsr_analysis` is the only status writer and I did not want the PRD to claim reachability either way; also added "Both codes carry HTTP 409" rather than restating per-code HTTP, matching errors.py.

## Step 9: Complete PRD — 2026-08-23T05:56:00.000Z

All 26 edits applied cleanly; the document structure (486 lines, no new sections, no new paragraphs) is unchanged.

Summary
- Source: `workspace/PRD_FINALIZED.md` — 486 lines, 93,045 chars. Output: `workspace/PRD_COMPLETED.md` — 486 lines, 98,054 chars. Char delta: **+5,009**.
- Counts: **20 ambiguity-pins**, **6 mismatch-revisions** (26 total, all in-paragraph inserts/revisions).

- §2.1 User and Role-Based Access Control — revise — mismatch — only `legal_cleared_by_user_id` and `minutes_reviewed_by_user_id` gate segregation of duties; `review_opened_by_user_id` and `analyzed_by_user_id` are audit-trail only — routes_assoc.py:480, routes_assoc.py:514, routes_biz.py:106, routes_biz.py:299
- §2.2 API Response Structure — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty upper-case-alphanumeric characters — store.py:100-103
- §2.3 Pagination — insert — ambiguity — an empty-string `limit`/`offset` is treated as omitted — ladder.py:191-207
- §2.3 Pagination — insert — ambiguity — enum-filter validation precedes pagination validation; free-form identifier filters are matched literally without existence checks; empty-string filters are ignored — ladder.py:209-225, routes_core.py:62-64
- §2.4 Record Identity, Timestamps and the Logical Clock — insert — ambiguity — the lazy sweep is a single global pass over all training assignments and leniency applications at the start of any request with well-formed auth headers, ahead of role authorisation — app.py:33-41, domain.py:283-285
- §2.4 Record Identity, Timestamps and the Logical Clock — revise — ambiguity — `to_iso8601` is required and well-formed; the clock call answers 200 with a `data` object whose only member is `current_utc` — routes_core.py:299-305
- §2.7 The Validation Ladder (preamble) — insert — mismatch — lazy time-gated transitions are exempt from the no-side-effect-on-failure rule; they apply before the ladder and survive a later-rung rejection — app.py:33-41
- §2.7 rung 3 (Request shape) — revise — ambiguity — added the impl's full range set (`competitor_density_pct`, both budgets, `duration_minutes`/`validity_days`, `concurrent_drill_capacity`, the non-negative counters and the five cents figures, `affected_years` entry shape) plus non-blank-string, strict-integer and ignore-undeclared-members discipline — ladder.py:52-183, routes_core.py:26-34, routes_ops.py:28
- §2.10 Occupancy and Capacity Conventions — revise — mismatch — only the candidate's `window_start` is swept (never `window_end`), plus occupying starts strictly inside the candidate window — routes_ops.py:59-70
- §3.2 Training Targeted at Sales and Pricing Roles — revise — mismatch — curriculum `code` carries no uniqueness check; a repeat code is accepted — routes_core.py:167-188
- §3.4 Trade Associations and the Two-Branch Participation Fork — insert — ambiguity — prohibition cascade also cancels each terminated participation's still-`PLANNED` attendances with no clock condition, reason `trade association prohibited`, and bumps the unit's `version` only where minutes were reserved — routes_assoc.py:67-87
- §3.4 Trade Associations and the Two-Branch Participation Fork — insert — ambiguity — the nominated delegate need not belong to the nominating unit — routes_assoc.py:99-119
- §3.4 Trade Associations and the Two-Branch Participation Fork — insert — ambiguity — unmet reinstatement branch conditions yield `ERR_INVALID_STATE` 409, tested after the posture gate — routes_assoc.py:255-275
- §3.4 Trade Associations and the Two-Branch Participation Fork — revise — mismatch — termination cancels still-`PLANNED` attendances from any terminable status (not only `ACTIVE`), and the supplied `reason` becomes each `cancellation_reason` — routes_assoc.py:77-88
- §3.5 Meetings, Delegate Bookings and Minutes Review — insert — ambiguity — a fresh booking carries `exposure_points_assessed` 0 and six null minutes/cancellation fields — routes_assoc.py:376-389, domain.py:403-419
- §3.5 Meetings, Delegate Bookings and Minutes Review — insert — ambiguity — attendance confirmation's clock comparison is inclusive; an early attempt is `ERR_INVALID_STATE` 409 — routes_assoc.py:434-449
- §3.5 Meetings, Delegate Bookings and Minutes Review — revise — mismatch — `topics_discussed` is a required array of free-form strings, may be empty, never checked against an enumeration — routes_assoc.py:452-468, ladder.py:157-171
- §3.5 Meetings, Delegate Bookings and Minutes Review — insert — ambiguity — `findings` is required but may be empty, summing to 0 points — routes_assoc.py:475-476, calc.py:245-249
- §3.5 Meetings, Delegate Bookings and Minutes Review — insert — ambiguity — hop 2 is skipped when the freeze cascade already suspended the participation; hops 3 and 4 fire only when the delegate's clearance stands at `GRANTED` — routes_assoc.py:499-504, domain.py:173-181
- §3.7 Merger Control — revise — ambiguity — the five monetary figures are integers of cents and may not be negative — routes_biz.py:186-190
- §3.8 Inspection Readiness and Document-Creation Hygiene — revise — mismatch — `country_code` is stored as supplied with only a non-empty-string check, no ISO-3166 format validation — routes_ops.py:22-36
- §3.8 Inspection Readiness and Document-Creation Hygiene — insert — ambiguity — drill start's `window_start` comparison is inclusive; an earlier attempt is `ERR_INVALID_STATE` 409 — routes_ops.py:109-120
- §3.8 Inspection Readiness and Document-Creation Hygiene — insert — ambiguity — drill completion refreshes the site's `updated_at` and increments its `version` by 1 — routes_ops.py:123-139
- §3.8 Inspection Readiness and Document-Creation Hygiene — insert — ambiguity — both audit counts are integers >= 0, and `violation_count > sample_size` is `ERR_INVALID_REQUEST` 400 checked *after* the `OPEN` state test — routes_ops.py:198-213
- §3.9 Leniency: The Marker Race and the Disclosure Package — insert — ambiguity — a marker denial leaves `estimated_penalty_cents` exactly as it stood — routes_ops.py:322-328
- §3.9 Leniency: The Marker Race and the Disclosure Package — insert — ambiguity — withdrawal leaves `estimated_penalty_cents` untouched, and moves neither the unit's posture nor its `version` when the marker was already `NONE`/`MARKER_DENIED`/`MARKER_EXPIRED` — routes_ops.py:368-387

Cross-check performed: all 79 impl route decorators (routes_core 18, routes_biz 19, routes_ops 20, routes_assoc 22) were matched one-to-one against the §4 endpoint table for path, method and authorised roles — no divergence found there, so §4 and §5 required no edits.
