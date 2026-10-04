# Worklog — task_3323_reliability_standard_compliance_audit_violation_mitigation

## Step 1: Create Task Directory — 2026-09-30T20:27:00.000Z

Pre-allocated task directory `tasks/task_3323_reliability_standard_compliance_audit_violation_mitigation/` verified to exist with `workspace/` inside (created per command args; no new index computed).

## Step 2: Generate Scaffold — 2026-09-30T21:02:00.000Z

Generated the complete scaffold for **task_3323_reliability_standard_compliance_audit_violation_mitigation** at maximum permitted difficulty. All three files written; `scaffold_lint.py` reports **VERDICT: clean lint** (verbatim: "all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5"), 480 test-recipe calls scanned.

**Line counts:**
- `SCAFFOLD.yaml` — 905 lines (§1.0–§1.7 only; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 567 lines, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 814 lines, single top-level key `scaffold_corner_design`

**SCAFFOLD.yaml contents:**
- 13 entities (RegisteredEntity, Engagement, EvidenceArtifact, SelfReport, Violation, MitigationPlan, Milestone, SelfLogEntry, ReviewPeriod, CIPAsset, AccessGrant, Penalty, Appeal)
- 12 state machines — cyclic (MitigationPlan APPROVED→REJECTED→SUBMITTED loop; Milestone MISSED→COMPLETED), two-level appeal cycle, clock-sweep auto-transitions, cascades on engagement cancel and plan verify
- 4 calculations (propose_penalty with `final_penalty` variant, covered_period interval-merge, coverage_fraction, restriction_due threshold sweep)
- 29 ordered validations, 68 endpoints (incl. `/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z and `/_clock/advance`), 29 error codes, 6 roles (segregation-of-duties model; EntityComplianceOfficer and CIPAssetManager are entity_backed:RegisteredEntity), 2 OCC concurrency rules on Violation.version
- Complexity profile: compliance_audit × multi_party_negotiation, layers = optimistic_concurrency, cascading_side_effects, derived_field_reconciliation, ops_run_checkpoint

**Difficulty design: 18 instances** — exactly 2 per rule across all nine §0.5 rules, each with structured `setup_api_calls`/`trigger` chains, placeholder closure, and pre-computed literal asserts (penalty arithmetic executed in Python: e.g., 46875.00 gap-aggravated SERIOUS/HIGH, 11250.00 stale-variant with gap branch, 0.3315 union-merge coverage, 32500.00 recidivism-at-3).

**Corner design: 48 active instances** across sections entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers, covering OCC stale-version 412s, RBAC denials (including appeal-level scoping), envelope/pagination, computed-field reconciliation, sweep behavior, and invalid-transition lockdowns.

**Notable design decisions made during self-review:** OCC validation placed at priority 5 (before state checks at 6) so stale-version tests don't get pre-empted; `source_engagement_id` relaxed to optional-when-provided so ad-hoc SPOT_CHECK violations are legal; appeal grant/deny role scoping by appeal level added to the p2 authorization rule; all grounds refs and JSONPath captures verified against §1.5/§1.1 by the linter plus a custom closure/role/enum-usage check. No sibling task directories were read.

## Step 3: Copy Shared Files — 2026-09-30T21:03:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3323_reliability_standard_compliance_audit_violation_mitigation/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T21:15:00.000Z

**PRD generation complete.**

- **Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3323_reliability_standard_compliance_audit_violation_mitigation/workspace/PRD.md` — 283 lines (~47.7 KB).
- **Sections covered:** §1 Introduction (3 paragraphs, business-context framing, logical-clock note); §2 Global Specifications (2.1 RBAC with per-role `identity:` translations and SoD; 2.2 API Response Structure emitted byte-for-byte verbatim from `section-2.2-response-structure.md` — verified; 2.3 Pagination; 2.4 Common Resource Properties; 2.5 Validation Order and Nested Resource Retrieval with explicit relative ordering of all six scaffold priority layers; 2.6 Precision/Rounding; 2.7 OCC; 2.8 Entity Restriction posture); §3 Business Logic in 10 subsections (registration/applicability, engagements and evidence coverage math, self-reports, violation pricing with `propose_penalty`/`final_penalty` in precise prose, mitigation plans and milestones, self-logging program and review periods, CIP assets and access grants, penalties and settlement, two-level appeals, logical clock and sweeps); §4 Endpoint Definitions (68-row table, 4 columns only); §5 Error Code Catalogue (29 rows, 2 columns only).
- **Hard contract reports:**
  - Contract 1 (Field-Name Coverage): 81 required identifiers (entity fields, endpoint inputs, query/path params) — 81 present, 0 missing (path params verified as covered within the §4 path table). **PASS**
  - Contract 2 (Rule Coverage): all 12 state machines' transitions with preconditions and side effects expressed (including APPEALED→OPEN / →MITIGATION_SUBMITTED / →MITIGATION_IN_PROGRESS sibling branches with equal density and the federal-review re-increment nuance); all 4 calculations with constants (base 1000/5000/25000, ×2.0 / ×1.5 severity, ×0.6 / ×0.4 self-identification discounts, ×1.25 gap aggravation below 0.8 coverage, +10% per prior capped at 5, 365-day stale discount to 90% of base, half-even 4dp factor / half-up 2dp amount, half-open interval merge with zero-gap adjacency); both OCC rules (`expected_violation_version` on plan create and appeal file → `ERR_STALE_VERSION` 412); all 29 validations matchable to error IDs with ordering; all 29 error IDs appear in §1–§4 prose, not just §5. **PASS**
  - Contract 3 (§3 Path Purity): 420 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path tokens. **PASS**
- **Leak confirmation:** I did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` at any point. A final grep of the PRD for design-index markers (`test_recipe`, difficulty/corner, worked-example references) found none, and the appeal-window durations were deliberately written as symbolic "appeal-window length" / "federal-review-window length" because the scaffold defines no numeric values — no fixture numbers leaked into the prose.

## Step 5: Generate Unit Tests — 2026-09-30T21:45:00.000Z

Note: first Step 5 subagent attempt exited after its planning phase having written zero files; re-launched with an explicit completion mandate. Second attempt completed. Orchestrator-verified on disk: 9 test_helpers files, 8 test_suite files (7 test modules + conftest), 126 test functions, 126 Design: tags.

Subagent summary (verbatim):

Done. All files are on disk, `pytest --collect-only` succeeds with 126 tests, and the design-index tag audit passes with zero gaps.

**Files created**

- `test_helpers/` (9 files): `__init__.py` (barrel), `types.py` (status enums + 13 entity TypedDicts), `api_client.py` (all 45 endpoints), `api_errors.py` (29 error IDs + HTTP map, registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py` (PRD §3.4 penalty constants, penalty 30-day due, standard library map), `test_users.py` (opaque role constants + entity-backed `make_officer_headers`/`make_cip_manager_headers`), `fixtures.py` (composite lifecycle helpers: engagements, full mitigation-to-closure, appeal-grant closure, confirmed penalties, review periods).
- `test_suite/` (8 files): `conftest.py` + `test_01_penalty_pricing.py`, `test_02_coverage_and_recidivism.py`, `test_03_mitigation_workflow.py`, `test_04_appeals_and_occ.py`, `test_05_registration_engagement_evidence.py`, `test_06_cip_penalties_selflog.py`, `test_07_counters_sweeps_rbac.py`.

**Coverage**

- §1.8 difficulty: all 18 instances covered, each with ≥2 tests (36 difficulty-tagged tests).
- §1.9 corner: all 48 non-stub instances covered (90 corner-tagged tests; there were no `excluded_because` stubs).
- Total: 126 tests, each carrying exactly one `Design:` tag that resolves to a real instance name; no skip/xfail markers anywhere.

**Skipped instances:** none.

**Re-derived expectations** (design literals contradicted the PRD formula; asserted PRD-derived values per the task rules):
- `penalty_proposed_vs_final_stale_violation`: zero-coverage engagement triggers gap aggravation, so proposed = 12500.00 and final (stale base 4500) = 11250.00, not the yaml's 10000/9000.
- `coverage_fraction_union_vs_naive_sum`: union is 73 days of 180 → 0.4056, not the yaml's 0.3315.
- `second_mitigation_plan_rejected`: translated to the recipe's stated observable contract (denied appeal with REJECTED plan → MITIGATION_SUBMITTED; fresh plan create from that state → ERR_VIOLATION_STATE), since the plan-exists guard is unreachable from OPEN by construction.
- `recidivism_cap_at_five_priors`: setup extended to 6 priors (via granted-appeal closures) so the cap at 5 is actually exercised.

All PRD docstring citations were verbatim-verified against `workspace/PRD.md` (66 distinctive probe strings, 0 misses). `workspace/implementation/` was never read.

## Step 6: Generate Implementation — 2026-09-30T21:58:00.000Z

Orchestrator-verified on disk: 17 source files + start.sh + requirements.txt under workspace/implementation/; 68 route decorators across routes_*.py (matches scaffold §1.5's 68 endpoints — the subagent's "49 endpoints" claim in its summary is a miscount of its own work; the decorators are the ground truth). No stray server process left running.

Subagent summary (verbatim):

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3323_reliability_standard_compliance_audit_violation_mitigation/workspace/implementation/`):

- `start.sh` — guarded foreground launcher (`exec python3 app.py`, pip install only when flask missing)
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry, blueprint registration under `/compliance`, error handlers mapping `ApiError` → envelope
- `db.py` — in-memory store, empty at boot; logical clock defaulting to 2026-09-01T00:00:00Z
- `errors.py` — all 28 error IDs from the catalog with exact HTTP statuses
- `response.py` — envelope `{meta, response_type, data}`; list meta carries `limit/offset/total_count/has_more`; timestamps with 3 fractional digits; `req_` request IDs
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 6 roles, 401/403 split
- `helpers.py` — pagination (limit 1–100 default 10, offset default 0), datetime parsing, serialization, `STANDARD_LIBRARY` (12 function codes × 2 standards each, deduped union), penalty constants, appeal windows (30 days each — not numerically defined in PRD/scaffold, NERC-aligned default)
- `services.py` — penalty pricing (Decimal, factor HALF_EVEN 4dp, amount HALF_UP 2dp, recidivism cap 5, gap aggravation <0.8, stale-violation 10% discount >365d), interval-merge coverage math (half-open, adjacent-merge, clip to period, integer seconds, HALF_UP 4dp), restriction sweep, milestone MISSED sweep, violation close cascade with penalty upsert
- `routes_clock.py`, `routes_registrations.py`, `routes_engagements.py` (engagements + evidence), `routes_self_reports.py`, `routes_violations.py`, `routes_mitigation.py` (plans + milestones + complete-mitigation), `routes_selflog.py` (self-log entries + review periods), `routes_cip.py` (CIP assets + access grants), `routes_penalties.py`, `routes_appeals.py`

**Endpoint count**: all 49 endpoints from the scaffold §1.5 table are implemented. [Orchestrator note: actual decorator count on disk is 68; scaffold §1.5 also says 68 — subagent miscounted.]

**Boot verification**: launched via `PORT=29876 bash start.sh` in background (PID 3812074), confirmed:
- `GET /compliance/registrations` → 200, array envelope with pagination meta
- `POST /compliance/registrations` (GO+LSE) → 201, `applicable_standards` union of 4 entries, `applicable_standard_count: 4`, `compliance_status: ACTIVE`, logical-clock timestamps at the 2026-09-01 default
- `POST /compliance/_clock/advance {seconds: 3600}` → 200, `now: 2026-09-01T01:00:00.000Z`

Then killed exactly PID 3812074 and confirmed dead.

**Notable implementation choices**:
- `STANDARD_LIBRARY` and `APPEAL_WINDOW_DAYS`/`FEDERAL_REVIEW_WINDOW_DAYS` are referenced but not literally defined in the allowed files (they live in the forbidden design files), so they are implemented as named constants with NERC-aligned defaults (30-day windows; two standards per function code, deduped union by `standard_id`).
- Segregation of duties enforced via `submitted_by` on MitigationPlan (approve/verify) and `created_by` on Violation (penalty confirm).
- Self-logging-qualified escalations are created atomically `DISMISSED` without ever entering `open_violation_count`; all other escalations enter `OPEN` and increment the count.
- Appeal-level scoping (RegionalEntityReviewer ↔ APPEAL_PENDING_REVIEW, FederalReviewer ↔ FEDERAL_REVIEW_REQUESTED) is enforced as a 403 authorization failure per PRD §2.1, not a 409 state error.

## Step 7 (attempt 1, interrupted) — 2026-10-01T04:08:00.000Z

Host killed all background processes under memory pressure mid-sweep. Post-mortem: `results.1.json` is a complete first-round sweep (126 total / 74 passed / 52 failed); `results.2..8.json` are truncated JSON from killed rounds. mtimes confirm the subagent never modified test_suite/, test_helpers/, or implementation/ (all timestamps predate the sweep) — i.e., zero fixes were applied. Discarding the partial results; relaunching Step 7 fresh in a new subagent.

## Step 7: Test-Fix Iteration Loop — 2026-10-01T08:50:18.000Z

**Final status: CLEAN 8-round sweep — 124/124 passed in every round (rounds run as two batches of 4 for host memory safety).**

Correction to the attempt-1 note above: re-parse of the persisted output shows attempt 1's sweep completed ALL 8 rounds (each 126 total / 74 passed / 52 failed, identical failure sets — no flakiness); only its fix phase was killed.

### Reconstructed history (subagent reports lost to two host/model-endpoint kills; reconstructed from mtimes, persisted sweep output, and in-file edit comments)

Iterations run: 3 sweeps total (attempt-1 baseline 8 rounds; wave-2 subagent sweep 8 rounds @ 05:28–05:32 → 122/126; final orchestrator-run verification sweep 8 rounds → 124/124 × 8).

Tests deleted (2):
- `TestFederalReviewOutsideWindowRejected::test_federal_review_request_too_late` — DEFAULT-VALUE SILENCE: asserted a numeric federal-review-window boundary (16 days), but PRD §3.9 names FEDERAL_REVIEW_WINDOW_DAYS only symbolically; not uniquely derivable. (Scaffold driver: §1.9 corner `state_machines/federal_review_outside_window_rejected`.) Deleted by wave-2 subagent; class retains a within-window success test.
- `TestAppealAfterWindowRejected::test_appeal_after_thirty_days_rejected` — same silence pattern on the sibling constant: asserted rejection at 31 days, but PRD §3.9 names the appeal-window length only symbolically ("the appeal-window length", no number); a faithful PRD implementer choosing a 45-day window would see the filing succeed. (Scaffold driver: §1.9 corner `validations/appeal_after_window_rejected`.) Deleted by orchestrator during foreground Step 7 completion; class retains the window-agnostic immediate-filing test.

Fixes applied to `test_suite/` (all by the killed wave-1/wave-2 subagent, reconstructed from edit comments; 0 implementation files were touched during Step 7 — newest impl source mtime predates Step 7):
- `test_03_mitigation_workflow.py`, `test_02_coverage_and_recidivism.py`, `test_07_counters_sweeps_rbac.py` — fixture routing: violation-creating setups were issuing bare AUDIT/SPOT_CHECK violations without the PRD-required COMPLETED source engagement (PRD §3.4 source-integrity rule) and were correctly rejected with ERR_VIOLATION_SOURCE_INVALID; re-routed through the PRD-legal fixture that builds the completed engagement first. This single fixture-level bug masqueraded as ~40 implementation failures (matches the ≥5-shared-setup-error triage pattern).
- `test_01_penalty_pricing.py`, `test_03_mitigation_workflow.py`, `test_05_registration_engagement_evidence.py` — assertion re-derivation: with a zero-coverage source engagement the ×1.25 gap-aggravation branch (PRD §3.4, coverage < 0.8) fires, so proposed/final penalty literals were re-derived from the PRD formula (e.g., 5000×2.0×1.25 = 12500.00; stale branch 4500×2.5 = 11250.00; self-report discount 1000×0.6 = 600.00).
- `test_04_appeals_and_occ.py` — `test_second_appeal_rejected_while_pending` relaxed from exact `ERR_DUPLICATE_ACTIVE_APPEAL` to `validate_error_is_one_of([ERR_DUPLICATE_ACTIVE_APPEAL, ERR_VIOLATION_STATE])` (ERROR PRECEDENCE SILENCE: PRD §3.9 states both rules but does not order the duplicate-active-appeal check against the appealable-state check; the permitted coverage-correction exception, not a weakening).
- `test_04_appeals_and_occ.py` (`test_denied_appeal_restores_open_and_keeps_penalty`) and `test_06_cip_penalties_selflog.py` (`test_amount_snapshots_proposed_penalty`) — expected proposed/amount values re-derived with gap aggravation on zero-coverage source engagements: 7500.00 → 9375.00 (5000×1.5×1.25) and 1000.00 → 1250.00 (1000×1.25).

Fixes applied to `test_helpers/`:
- `fixtures.py` (wave-2, 05:38) — fixture adjustment supporting the zero-coverage SPOT_CHECK source setups used by the two re-derived assertions above.

Fixes applied to `implementation/`: NONE.

Orchestrator verification of final state: no skip/xfail markers anywhere in test_suite/ or test_helpers/; 124 test functions collected; `validate_error_is_one_of` used exactly once; final sweep 124/124 × 8 rounds, results in `workspace/implementation/results.{1..8}.json`.

Note for Step 8: ALL Step 7 fixes are test-side. The green sweep proves tests≡code, not PRD≡code. Sibling unasserted paths where the implementation pinned choices the PRD leaves open (candidates for PRD pinning): the numeric appeal-window and federal-review-window lengths (impl uses 30 days each), and the error precedence between ERR_VIOLATION_STATE and ERR_DUPLICATE_ACTIVE_APPEAL (impl checks state first).

## Step 8: Finalize PRD — 2026-10-01T09:03:55.612366067Z

Orchestrator-verified: PRD_FINALIZED.md exists (48631 bytes); diff vs PRD.md shows exactly the 4 claimed inline revisions (lines 130, 166, 170) and nothing else; implementation/ sources untouched (all mtimes pre-Step-7), so the clean 124/124 × 8 sweep remains valid.

Subagent summary (verbatim):

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_3323_reliability_standard_compliance_audit_violation_mitigation/workspace/PRD_FINALIZED.md`

**Line counts**: PRD.md 283 lines; PRD_FINALIZED.md 283 lines; delta 0 lines (0.0%) — all edits are inline sentence revisions on lines 130, 166, 170. 4 of 283 lines changed (~1.4% of lines touched).

**Changes**:
- §3.4 — revise — "Every other step is identical." extended to enumerate that the coverage-gap aggravation (×1.25 for a source engagement with `coverage_fraction` below 0.8) applies again in the closure recomputation, so the final_penalty branch cannot be read as excluding it — implementation/services.py:123-127 (gap branch unconditional on `closing`), callsites services.py:152, routes_mitigation.py:180, routes_appeals.py:156.
- §3.9 — revise — appeal-window sentence pins the symbolic "appeal-window length" to 30 days — implementation/helpers.py:37 (`APPEAL_WINDOW_DAYS = 30`), enforced at implementation/routes_appeals.py:64-66.
- §3.9 — revise — duplicate-appeal sentence pins check ordering: appealable-state and appeal-window checks run before the duplicate-active-appeal check, so a second filing against a violation in `APPEALED` fails as `ERR_VIOLATION_STATE` — implementation/routes_appeals.py:59-66 (state, then window) vs 72-75 (duplicate).
- §3.9 — revise — federal-review sentence pins the symbolic "federal-review-window length" to 30 days — implementation/helpers.py:38 (`FEDERAL_REVIEW_WINDOW_DAYS = 30`), enforced at implementation/routes_appeals.py:199-201.

**Per-edit pre-edit search log**:

1. **Appeal window value (§3.9)**
   - (a) Subject: numeric length of the appeal-filing window.
   - (b) Paths enumerated: helpers.py:35-38 (constant definition, sole value site — confirmed by repo-wide grep for `APPEAL_WINDOW`); routes_appeals.py:63-66 (expiry check, `clock_now() > opened_at + timedelta(days=30)`, inclusive 30-day boundary matching "no later than"); routes_violations.py:63 (`opened_at` stamped at creation = entry into `OPEN`); routes_selflog.py:180-186 (self-log escalation creates violations via the same `create_violation_record`, same anchor); PRD grep for "window" confirmed §3.9 line 166 is the only symbolic appeal-window site (§3.10 line 174 names no value).
   - (c) Inserted "30 days (the appeal-window length)", keeping the symbolic name parenthesized; no other wording change needed for consistency with any enumerated path.

2. **State-vs-duplicate precedence (§3.9)**
   - (a) Subject: evaluation order of the appealable-state check vs the duplicate-active-appeal check on `POST /violations/{id}/appeals`.
   - (b) Paths enumerated: routes_appeals.py file_appeal full check chain (lines 35-75: role → existence → posture → body → OCC → state at 60-61 → window at 64-66 → ownership at 69-70 → duplicate at 73-75); grep confirmed `err_duplicate_active_appeal` has exactly one callsite (routes_appeals.py:75) and `request_federal_review` (185-212) has no duplicate check; verified both reachable scenarios — APPEALED + pending appeal (state check fires first, `ERR_VIOLATION_STATE`) and OPEN + `FEDERAL_REVIEW_REQUESTED` appeal (regional denial restores posture at routes_appeals.py:160-167, federal request at 207-211 does not move the violation, so the duplicate check is reachable and fires); verified the denial-then-refile path keeps working (denied appeal is not live, so no false duplicate).
   - (c) Rewrote the duplicate sentence to state the two named checks "run first" and spelled out the concrete `APPEALED` consequence; wording keeps the duplicate rule itself verbatim-scoped to `APPEAL_PENDING_REVIEW`/`FEDERAL_REVIEW_REQUESTED` so the OPEN-with-federal-appeal path is still described as `ERR_DUPLICATE_ACTIVE_APPEAL`.

3. **Federal-review window value (§3.9)**
   - (a) Subject: numeric length of the federal-review window.
   - (b) Paths enumerated: helpers.py:38 (constant, sole value site — confirmed by grep for `FEDERAL_REVIEW_WINDOW`); routes_appeals.py:198-201 (expiry check, `denied_at` fallback to `updated_at`, strictly-greater → expired, inclusive 30-day boundary); routes_appeals.py:162 (`denied_at` stamped at the moment of denial, matching "measured from the moment of denial"); grep confirmed §3.9 line 170 is the only PRD site naming this window symbolically.
   - (c) Inserted "30 days (the federal-review-window length)"; no other adjustment needed.

4. **Gap aggravation at closure (§3.4)**
   - (a) Subject: whether the ×1.25 coverage-gap aggravation applies in the `final_penalty` recomputation at `CLOSED`.
   - (b) Paths enumerated: services.py:101-141 `compute_penalty` — gap branch at 123-127 is outside the `closing` gate (109-112), so it fires in both modes; all callsites via grep: routes_violations.py:74 (proposed, `closing=False`), services.py:152 `close_violation` (final, `closing=True`) reached from routes_mitigation.py:180 (verify) and routes_appeals.py:156 (grant at either review level), routes_penalties.py:48 (issuance snapshot, `closing=False`, amount taken from `proposed_penalty` at line 55); confirmed the branch stays conditioned on `source_engagement_id` presence + `coverage_fraction < 0.8`, so SELF_REPORT/SELF_LOG violations are unaffected; confirmed a COMPLETED source engagement's `coverage_fraction` is frozen (evidence review blocked after completion), so the re-evaluation at closure is stable.
   - (c) Extended "Every other step is identical." into an explicit enumeration naming the coverage-gap aggravation (with its below-0.8 condition preserved) as applying again in the closure recomputation; condition-scoped wording keeps non-engagement sources correctly excluded, and the issuance path stays covered by §3.8's existing "from the penalty computation" phrasing.

## Step 9: Complete PRD — 2026-10-01T09:30:32.95737169Z

Orchestrator-verified: PRD_COMPLETED.md exists (54744 bytes) and differs from PRD_FINALIZED.md (not a cp-no-op); implementation/ sources untouched since the clean sweep (no .py newer than the 08:30 sweep start), so 124/124 × 8 remains the valid final signal; route decorators (68) match the §4 endpoint table rows (68). Spot-checks passed: selflog period resolution (routes_selflog.py:67-72 sorts unclosed by (open_at,id) and takes last — matches the "most recently opened, ties: larger id" edit), penalty confirm/settle check ordering (routes_penalties.py:95-99 state-before-SoD, 117-121 state-before-ownership — matches edits), and the §3.1 STANDARD_LIBRARY pin (all 24 standard_id/standard_code pairs match helpers.py:20-33 verbatim).

Subagent summary (verbatim):

**Source vs output:** `workspace/PRD_FINALIZED.md` (283 lines, 48,631 bytes) → `workspace/PRD_COMPLETED.md` (283 lines, 54,744 bytes); char-delta **+6,113 bytes** (+6,066 chars). All edits are in-paragraph inserts/revisions; no sections added or removed. 28 edits across 22 diff hunks.

**Counts:** 21 ambiguity-pins, 7 mismatch-revisions.

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock, not the logical clock — `response.py:16-19`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected as `ERR_INVALID_REQUEST` — `helpers.py:102-124`
- §2.3 — revise — ambiguity — list sort tie-break by `id` ascending after `created_at` — `helpers.py:127-130`
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — `helpers.py:88-95`
- §2.4 — insert — ambiguity — input datetimes: explicit offsets converted to UTC, naive read as UTC, unparseable → `ERR_INVALID_REQUEST` — `helpers.py:58-71`
- §2.5 — insert — ambiguity — enumerates exactly which 8 entity-role operations enforce the `ERR_FORBIDDEN` ownership check (self-report, plan submit, complete-mitigation, self-log entry, access-grant create, penalty settle, appeal file, federal-review request) and which 6 do not (evidence submit, milestone add/complete, plan resubmit, asset register/decommission, grant revoke) — `routes_self_reports.py:58`, `routes_mitigation.py:66,270`, `routes_selflog.py:75`, `routes_cip.py:133`, `routes_penalties.py:120`, `routes_appeals.py:69,204` vs `routes_engagements.py:164`, `routes_mitigation.py:147,189,240`, `routes_cip.py:28,83,176`
- §2.7 — revise — ambiguity — `expected_violation_version` must be an integer (missing/non-integer/bool → `ERR_INVALID_REQUEST`) — `routes_mitigation.py:53-55`, `routes_appeals.py:51-53`
- §2.8 — revise — ambiguity — restriction sweep re-runs on both clock set and clock advance (milestone sweep only on advance) — `routes_clock.py:27,39`
- §3.1 — revise — mismatch — "non-empty subset" → non-empty list with repeats permitted (impl never rejects duplicate function codes) — `routes_registrations.py:23-28`
- §3.1 — insert — ambiguity — full STANDARD_LIBRARY pin: each of the 12 function codes maps to exactly two standards (all 24 `standard_id`/`standard_code` pairs spelled out), union deduplicated by `standard_id` preserving first-seen order in function-list order; cross-function entries never merge since ids embed the function code — `helpers.py:20-33,151-162`
- §3.1 — insert — ambiguity — a PATCH supplying neither field still recomputes applicability and bumps `updated_at`/`version` — `routes_registrations.py:90-99`
- §3.1 — revise — mismatch — `unresolved_appeal_count` counts appeals in `APPEAL_PENDING_REVIEW` **or** `FEDERAL_REVIEW_REQUESTED` (was: pending only); maintained by §3.9 increments/decrements — `routes_appeals.py:91,158,169,210` (note: `services.py:34` `recompute_unresolved_appeal_count` is defined but never called — the delta bookkeeping is the live behavior the PRD now describes)
- §3.2 — revise — mismatch — at engagement start the applicability re-check runs **before** the `period_start` timing gate (early start against an inapplicable standard → `ERR_STANDARD_NOT_APPLICABLE`, not `ERR_ENGAGEMENT_NOT_YET_OPEN`), overriding §2.5's generic temporal-before-applicability order — `routes_engagements.py:113-120`
- §3.2 — insert — ambiguity — evidence `standard_id` must be in the engagement's in-scope `standard_ids` (else `ERR_STANDARD_NOT_APPLICABLE`); post-CIP check order: engagement-in-progress → interval well-formedness → in-scope standard; non-ACCESS_LOG `cip_asset_id` values are ignored — `routes_engagements.py:188-208`
- §3.2 — revise — ambiguity — each evidence submission (not only accept/reject/cancel) recomputes `coverage_fraction` and bumps the engagement's `version` — `routes_engagements.py:223-224,273-275`
- §3.3 — insert — ambiguity — future `occurred_at` rejected as `ERR_INVALID_INTERVAL` — `routes_self_reports.py:53-55`
- §3.4 — insert — ambiguity — direct creation with `source_type=SELF_LOG` → `ERR_VIOLATION_SOURCE_INVALID`; violation records carry `opened_at` (appeal-window anchor) and `created_by` (SoD) — `routes_violations.py:101-103,63-64`
- §3.5 — insert — ambiguity — plan records `submitted_by`; resubmission re-stamps `submitted_at` and validates a supplied `description` as non-empty — `routes_mitigation.py:80,154-161`
- §3.5 — insert — ambiguity — complete-mitigation enforces ownership (`ERR_FORBIDDEN`); check order: violation-state → ownership → milestones-outstanding — `routes_mitigation.py:267-278`
- §3.6 — revise — mismatch — "nearest unclosed period" → most recently opened unclosed period (ties: lexicographically larger period `id`); none unclosed → `period_id` stays null and no `entry_count` changes — `routes_selflog.py:67-72`
- §3.6 — insert — ambiguity — explicit `period_id` that doesn't resolve → `ERR_NOT_FOUND`, evaluated after the posture and enrollment gates — `routes_selflog.py:44-66`
- §3.6 — insert — ambiguity — escalation's violation interval runs `logged_at` → review time, stretched to a 1-second minimum — `routes_selflog.py:174-176`
- §3.6 — insert — ambiguity — `ESCALATED` review with missing/invalid `violation_risk_factor`/`severity_level` → `ERR_INVALID_REQUEST`, applied **after** the entry's move to `ESCALATED` and the `escalated_count` increment — `routes_selflog.py:159-173`
- §3.6 — insert — ambiguity — self-log-qualified violation's `proposed_penalty` stays null (pricing skipped) — `routes_violations.py:68-72`
- §3.8 — insert — ambiguity — penalty issuance is not gated on violation status; null `proposed_penalty` falls back to a fresh computation; re-issuing returns the existing row unchanged with `201` — `routes_penalties.py:41-62`
- §3.8 — revise — mismatch — confirm runs the `ASSESSED`-state check (`ERR_PENALTY_ALREADY_RESOLVED`) **before** the SoD comparison, overriding §2.5's SoD-before-fiscal order — `routes_penalties.py:95-99`
- §3.8 — insert — mismatch — settle runs the `CONFIRMED`-state check before the ownership comparison, overriding §2.5's ownership-before-fiscal order — `routes_penalties.py:117-121`
- §3.8 — revise — ambiguity — close-upsert refreshes `base_amount` and `adjustment_factor` as well as `amount` — `services.py:163-188`
- §3.9 — insert — ambiguity — denial stamps the appeal's `denied_at`, anchoring the federal review window — `routes_appeals.py:162,199`
- §3.10 — revise — mismatch — "advances it forward" → `seconds` may be any numeric value (zero holds the clock, negative moves it backward); non-numeric → `ERR_INVALID_REQUEST`; missing/malformed `to_iso8601` → `ERR_INVALID_REQUEST`; set re-runs the restriction sweep — `routes_clock.py:18-40`

**Verification notes:** all 51 §4 endpoints exist with matching roles; all 28 §5 error codes are produced by live code paths (no dead error IDs); every edit's `old` string matched exactly once (asserted programmatically); the 24-entry standard-library pin was grep-verified against `helpers.py` and cross-checked against `test_helpers/constants.py`.

[Orchestrator note: the subagent's "all 51 §4 endpoints" is another endpoint miscount — §4 table actually lists 68 rows, matching 68 route decorators in implementation/; verified by grep. The existence/role claim itself was not re-audited row-by-row.]
