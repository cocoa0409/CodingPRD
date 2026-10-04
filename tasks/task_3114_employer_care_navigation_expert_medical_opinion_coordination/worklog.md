# Worklog — task_3114_employer_care_navigation_expert_medical_opinion_coordination

## Step 1: Create task directory — 2026-09-30T00:15:00.000Z

Pre-allocated task directory `./tasks/task_3114_employer_care_navigation_expert_medical_opinion_coordination/workspace/` verified to exist and be empty; used as-is per command args (no new index computed).

## Step 2: Generate scaffold — 2026-09-30T01:01:00.000Z

All three files written and lint-clean. Final report:

## Summary

**Task**: `task_3114_employer_care_navigation_expert_medical_opinion_coordination` — Employer Care Navigation & Expert Medical Opinion Coordination (Included Health), pushed to the hardest supported tier.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3114_employer_care_navigation_expert_medical_opinion_coordination/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design`)

**Counts**:
- 15 entities (incl. self-referential Member→subscriber dependents and the OpinionRecordItem many-to-many junction), 82 endpoints (POST/GET pairs on shared collection paths), 34 error codes, 25 ordered validation rules, 10 calculations, 7 state machines, 2 OCC concurrency rules, 10 roles
- §1.8: 19 difficulty instances — all 9 rules with ≥2 (combinatorial_formula has 3, covering modes (a) weighted-shrinkage, (b) pinned per-line rounding, (c) pinned evaluation-order estimate)
- §1.9: 59 corner instances (53 active + 6 `excluded_because` stubs) across entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model
- Lint: **VERDICT: clean lint** — 691 calls scanned, all FKs reverse-reachable

**Key design decisions (flagging)**:
- **Archetype**: workflow-orchestration (EMO pipeline) × compliance/audit (consent-gating + segregation of duties: EMO compiler cannot review own bundle, enforced on X-User-ID vs `compiler_user_id`).
- **Two transitive cascades**: consent revoke → RecordRequests CANCELLED → EMO RECORDS_BLOCKED → origin NavigationCase ESCALATED (depth 3); plan denial → EMO AUTH_BLOCKED → NavigationCase ESCALATED, with the reverse unblock on appeal-approval (depth 2).
- **OCC** on two parents: coverage-window create-with-supersede (`expected_member_version`) and recommendation submit-with-supersede (`expected_opinion_version`).
- **Dual-variant calcs in different domains**: billing savings (provisional reprice vs negotiated final: 34900 vs 60000) and employer steerage attribution (naive 900000 vs counterfactual 600000).
- **Three distinct interval/capacity semantics**: half-open appointment slots (adjacency allowed), closed-day coverage windows (contiguity required, boundary-day overlap rejected), and aggregate 8-per-day provider capacity.
- **All assert numbers hand-computed** and pinned as literals (repricing 165100/1551-vs-1552, quality shrinkage 76.0/74.0, cost-share 48000, deductible saturation at exact 100000, etc.).
- **One judgment call worth noting**: Member (entity-backed) ownership permits a subscriber to act on dependents' paths (`subscriber_id == X-User-ID`), needed for the CHILD-routing recipe; the strict cross-member mismatch corner test uses unrelated members and still holds.

## Step 3: Copy INSTRUCTION.md — 2026-09-30T01:02:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3114_employer_care_navigation_expert_medical_opinion_coordination/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T01:15:00.000Z

PRD generation complete (agent initially returned after planning only; resumed via SendMessage and it completed the write). Summary follows.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3114_employer_care_navigation_expert_medical_opinion_coordination/workspace/PRD.md` — 316 lines.

**Section list:**
- §1 Introduction (3 paragraphs, member-journey + segregation-of-duties angle)
- §2 Global Specifications: 2.1 RBAC (all 11 roles, `Member` entity-backed identity vs. 10 opaque roles translated to prose), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Logical Clock (default 2026-09-01T00:00:00Z, `to_iso8601`/`current_utc`), 2.5 Common Resource Properties & Money (incl. ProviderMatch's absent `updated_at`/`version`), 2.6 Validation Order & nested left-to-right resolution, 2.7 OCC (both rules, `ERR_STALE_VERSION`/412), 2.8 Consent gates (all four scopes), 2.9 Segregation of duties & assignment binding, 2.10 Member eligibility freeze
- §3 Business Logic, 10 subsections organized by member journey: employer load → provider quality/matching → navigation routing/escalation → appointment booking → records + consent cascade → EMO pipeline → claims/adjudication → billing negotiation → authorizations/appeals → employer reporting
- §4 Endpoint table (85 rows, 4 columns only)
- §5 Error catalogue (34 rows, 2 columns only)

**Hard-contract self-audit results:**
- **Contract 1 (Field-Name Coverage):** PASS — 105 required names (all entity fields incl. line-item `line_code`/`billed_cents`/`schedule_rate`/`error_flag`, all request-body/query/output identifiers, OCC fields), 0 missing after repairing two initial gaps (`employer_id`, `opinion_id`).
- **Contract 2 (Rule Coverage):** PASS — all 25 validation priorities expressed in priority-ordered prose (§2.6 pipeline + per-rule homes); both OCC rules name write operation, OCC field, error id, and HTTP status; all 10 state machines' transitions rendered with from/to states, preconditions paired to error IDs, and side effects (incl. cross-entity cascades: consent→record-request→EMO-block→navigation-escalate chain, claim void→billing void cascade, auth deny/approve cascades, version bumps); all 10 calculations expressed in reconstruction-safe prose (weighted quality blend with shrinkage-to-70.0, per-line-then-sum repricing with the pinned rounding order, chronological deductible application, OON 40% vs in-network capped estimate, dual billing savings variants, dual steerage variants, utilization aggregation); sibling branches (APPEALED vs REQUESTED approval, NEGOTIATING vs ERROR_IDENTIFIED proposal, etc.) rendered with equal density.
- **Contract 3 (§3 Path Purity):** PASS — 440 backticked tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos.

**Zero-silence audit — rules that were hardest to express in prose:**
1. The coverage-window auto-close precondition `new.effective_start > prior.effective_start` — expressed indirectly via "prior window's `effective_end` set to the day before the new window's `effective_start`" plus closed-interval overlap rejection; together these uniquely determine the ordering, but it is the least explicit translation in the document.
2. The `EMO_MIN_RECORDS` constant (3) — expressed as "at least three received records" in both the submit-for-review gate and the RECORDS_BLOCKED cascade trigger.
3. The claim-repricing rounding-order pin — rendered as "each line is rounded first and then summed, never summed unrounded and rounded once, because the two orders can disagree by a cent" (deliberately omitted the scaffold's worked 777/0.666 example since that style of illustrative fixture belongs to test design, not the PRD).

**Judgment calls:**
- Grouped §3 by member journey (10 subsections) rather than by entity or role, since the domain is workflow-orchestration-shaped.
- Put the validation priority pipeline explicitly in §2.6 (auth → role → shape → existence → eligibility → state → business → OCC-last) because 25 flat priority numbers would not survive prose scattering; individual business-rule priorities live with their workflows in §3.
- Constants translated per the skill's inference guidance: 500000 cents written as "500000 cents — exactly five thousand dollars", the volume threshold 30 as "thirty adjudicated claims", the 8-per-day capacity as "the eighth booking succeeds and the ninth is rejected", weights as fractions ("half", "three-tenths", "one-fifth").
- The `ProviderMatch` ephemeral entity's missing `updated_at`/`version` is stated explicitly in §2.5 per the common-fields contract.

## Step 5: Generate unit tests — 2026-09-30T01:45:00.000Z

Good — 53 non-stub corner instances and all are covered (the earlier name-listing was truncated in my reading). Everything checks out:

- **94 test functions**, each with exactly one `Design:` tag, all tags resolve to real instances.
- All 19 difficulty instances have ≥2 tests; all 53 non-stub corner instances have ≥1 test; 6 corner stubs verified to point at real difficulty instances (no tests emitted for them).
- Every docstring's PRD citation survives a literal-grep verbatim check against PRD.md.
- No instance was skipped due to the PRD-first two-condition filter (all asserted rules — including the two priority-pair instances, covered by PRD §2.6's fixed pipeline order sentence) have verbatim PRD coverage and unique derivability.
- `pytest --collect-only` collects all 94 tests cleanly; `test_helpers` imports verified.

**Files written**

`test_helpers/` (all under `/home/ubuntu/github/CodingPRD/tasks/task_3114_employer_care_navigation_expert_medical_opinion_coordination/test_helpers/`):
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 15 status/role enums + TypedDicts for all entities (ProviderMatch carries only `id`/`created_at`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~50 methods incl. `/_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` enum + HTTP status map registered with the framework
- `assertions.py` — per-entity `assert_*` validators
- `factories.py` — payload factories (input fields only)
- `constants.py` — thresholds (500000 cost escalation, volume 30, capacity 8, min records 3, proposals 3, retries 2, appeal 30 days), weights/rates
- `test_users.py` — `TEST_USERS` for 10 roles + `make_<role>_headers` builders (mandatory `make_member_headers(member_id)` for the entity-backed Member role)
- `fixtures.py` — composite helpers: clock/employer/member/consent/provider/snapshot, navigation-case state progression (incl. closed), appointment booking + provider-day fill, claims/adjudication, billing-case to OPENED/ERROR_IDENTIFIED, record requests (received), authorizations (requested/approved), full EMO pipeline tiers (records-attached → COMPILING → READY_FOR_REVIEW → IN_REVIEW)

`test_suite/` (13 files + `conftest.py`):
- `test_01_employers_members.py`, `test_02_coverage_windows.py`, `test_03_providers_quality_matching.py`, `test_04_navigation_cases.py`, `test_05_appointments.py`, `test_06_consents_records.py`, `test_07_expert_opinions.py`, `test_08_claims_billing.py`, `test_09_authorizations.py`, `test_10_reporting.py`, `test_11_security.py`, `test_12_cross_references.py`, `test_13_cost_share_estimates.py`

**Coverage summary**: Queue A (difficulty): 19/19 instances, ≥2 tests each. Queue B (corner): 53/53 non-stub instances, ≥1 test each; 6 stubs (`errors/*` ×5, `derived_field_member_accumulators_reconcile_on_create_and_void`) not translated, cross-references verified to resolve. Instances skipped for PRD-coverage reasons: none.

## Step 6: Generate implementation — 2026-09-30T02:10:00.000Z

All smoke tests pass. Cleaning up the test process (already killed via saved PID). The implementation is complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3114_employer_care_navigation_expert_medical_opinion_coordination/workspace/implementation/`):

- `start.sh` — foreground launcher, `$PORT` (default 10000), binds 0.0.0.0, guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`
- `requirements.txt` — flask
- `app.py` — Flask entry, blueprint registration, error handlers mapping to the standard error envelope
- `db.py` — in-memory store (dicts), logical clock defaulting to 2026-09-01T00:00:00Z
- `errors.py` — error catalog with the scaffold's exact error IDs and HTTP statuses
- `common.py` — envelope helpers (`meta`/`response_type`/`data`; `limit`/`offset`/`total_count`/`has_more` in meta), auth (X-User-ID/X-User-Role), RBAC, member/dependent scope checks, consent expiry sweep (inclusive boundary) with Cascade A (revoke/expire → cancel REQUESTED record requests → RECORDS_BLOCKED → linked nav case ESCALATED) and Cascade B (auth denied → AUTH_BLOCKED → nav escalation; approved → back to INTAKE)
- `helpers.py` — entity factory (id/created_at/updated_at/version), request validation primitives
- `calcs.py` — calculation modules: `intake_routing`, `provider_quality_score` (weights 0.5/0.3/0.2, low-volume shrinkage toward 70.0, 2dp half-up), `provider_matches` (network factor 1.0/0.8, tie-break period_end DESC then provider created_at ASC), `claim_repricing` (per-line round-then-sum), `deductible_application` (chronological, 20% coinsurance), `cost_share_estimate` (OON 40% flat; IN with OOP cap), steerage/utilization aggregation lives in routes_claims.py
- `routes_core.py` — clock, employers, members, coverage windows (closed-interval overlap, open-ended supersede, OCC `expected_member_version`), providers, quality snapshots, provider matches, consents
- `routes_nav.py` — navigation cases (routing, discipline-gated start, escalate/resolve/close) and appointments (half-open overlap, 8/day capacity, late-cancel, OCC-free reschedule, complete/no-show logical-clock gates)
- `routes_records.py` — record requests (receive/fail/retry cap 2/cancel with cascades) and expert opinion cases (attach, compile, submit-for-review with 3-record + approved-auth gates, claim-review with segregation of duties, OCC `expected_opinion_version` on submit-recommendation, deliver, withdraw)
- `routes_claims.py` — claims (adjudicate pinned repricing→deductible, void with exact accumulator reversal and billing-case voiding), billing cases (identify/propose cap 3/accept/reject/abandon/close), plan authorizations (approve/deny/appeal with 30-day window), cost-share estimate, employer utilization report

**Endpoint count: 62** routes implemented (all rows in the §1.5 endpoint table).

**Calculation/state-machine modules:** 7 calculation functions in `calcs.py` (intake routing, quality scoring, match ranking, repricing, deductible application, cost-share estimate, round helpers) plus steerage/utilization aggregation inline; 10 state machines (Member eligibility, CoverageWindow, ConsentGrant, NavigationCase, Appointment, RecordRequest, ExpertOpinionCase, Claim, BillingCase, PlanAuthorization) with both system cascades (A: consent-loss chain; B: authorization-denial chain).

**Judgment calls on ambiguous PRD prose:**
1. **Open-ended coverage-window overlap vs. supersede**: scaffold validation 10 (overlap → ERR_COVERAGE_OVERLAP) nominally conflicts with the supersede rule (open-ended create auto-closes the prior OPEN window). Implemented as: overlapping a *CLOSED* window always errors; a new open-ended window overlapping only the member's prior OPEN window is allowed (that window is auto-closed at new_start − 1 day), matching PRD §3.1's description of legitimate supersede and the OCC rationale.
2. **Coverage-window create does not require member ACTIVE** — eligibility freeze (§2.10) lists consents/navigation/appointments/records/opinions/billing/authorizations only, not windows.
3. **`redirected_from_out_of_network`** defaults to `false` when omitted (scaffold default).
4. **Claim create does not enforce member ACTIVE** — not in the §2.10 creation list.
5. **Billing-case create with a claim of another member** returns 404 ERR_NOT_FOUND (left-to-right reference resolution within the member scope).
6. **Cascade navigation escalation** bumps the nav case `version` via the shared `touch()` (it is a mutation), and cascade-driven window/opinion mutations bump their own versions; the member aggregate version bump occurs only where the scaffold explicitly pins it (deactivate/reactivate, window create supersede, claim adjudicate/void).
7. **Consent expiry on read** applies at single-consent revoke and list endpoints (sweep covers everything, which also satisfies "read a consent whose expires_at has been reached expires it on the spot").

Verified end-to-end via curl smoke tests: boot from fresh process, per-line repricing (1551 vs 1552 divergence case), OCC 412s, segregation-of-duties 403, full EMO pipeline through DELIVERED, consent-revoke cascade to RECORDS_BLOCKED + nav ESCALATED, inclusive clock-expiry boundary, low-volume shrinkage and boundary claims_volume=30, match ranking with network factor, and utilization report figures.

## Resume note — 2026-09-30T02:30:55.000Z

Host session was interrupted during the initial Step 7 spawn (its tool result was never recorded). On resume, verified Steps 1–6 artifacts are all present and non-truncated: SCAFFOLD.yaml/SCAFFOLD_DIFFICULTY_DESIGN.yaml/SCAFFOLD_CORNER_DESIGN.yaml (ends mid-yaml-document correctly, FK lint clean per Step 2), PRD.md 316 lines (ends with complete §5 error table), INSTRUCTION.md copied, test_helpers/ (9 files) + test_suite/ (13 test files + conftest.py; 94 tests collect cleanly via pytest --collect-only), implementation/ (app.py, db.py, errors.py, common.py, helpers.py, calcs.py, routes_core.py, routes_nav.py, routes_records.py, routes_claims.py, start.sh, requirements.txt — all non-empty, start.sh executable). Step 6's returned summary reported curl smoke tests passing. No Step 7 results.*.json files exist, so Step 7 never ran. Restarting at Step 7 with a fresh long-lived fix subagent.

## Step 7: Run tests and iterate — 2026-09-30T02:44:32.000Z

All 8 rounds pass 94/94 with an empty failure union (orchestrator independently verified all 8 results.*.json: passed=94, total=94, failed=0).

Summary:
- Iterations run: 2 (first sweep: 92/94 in all 8 rounds with the same 2 tests failing deterministically; second sweep after fixes: 94/94 in all 8 rounds).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none (both failing tests were PRD-faithful; STEP 1 and STEP 2 cleared them).
- Fixes applied to `implementation/`:
  - `common.py` — `clock_iso()`: emit the logical clock in the PRD's canonical `Z` form (`2026-09-01T00:00:00Z`) instead of zero-padded `.000Z`. PRD §2.5 pins the default clock reading to `2026-09-01T00:00:00Z`, and §3.5 states `revoked_at` is stamped "with the logical clock time"; the "three fractional digits" sentence names only `created_at`/`updated_at`/`api_request_timestamp`. Fixes `test_consent_revoke_cancels_requests_blocks_opinion_escalates_case`.
  - `routes_records.py` — `submit_recommendation()`: moved the `expected_opinion_version` staleness check ahead of the `IN_REVIEW` state check. PRD §2.7 states a submission carrying a mismatched `expected_opinion_version` "is rejected with ERR_STALE_VERSION (412), preventing the reviewer from overwriting a draft superseded by one they have not observed" — unconditional on current case state — while §2.6 only demands state checks precede *business rules*, not OCC. Fixes `test_occ_stale_opinion_version_on_submit_recommendation` (replay of a superseded draft previously surfaced ERR_INVALID_STATE because the case had already advanced to RECOMMENDATION_SUBMITTED).

## Step 8: Finalize PRD — 2026-09-30T02:46:56.000Z

Done. `PRD_FINALIZED.md` is written at the target path with exactly two in-place edits.

## Summary

**Sizes:** PRD.md 316 lines / 53,531 chars; PRD_FINALIZED.md 316 lines / 54,379 chars (+848 chars, +1.58%).

**Changes:**

- **§2.4 — revise —** Added a sentence pinning logical-clock renderings to ISO 8601 UTC without fractional digits (canonical `2026-09-01T00:00:00Z`), applying to `current_utc`, `revoked_at`, `decided_at`; clarified §2.5's three-fractional-digit rule covers only `created_at`/`updated_at`/`api_request_timestamp` — `implementation/common.py:24-30` (`clock_iso()` uses `strftime("%Y-%m-%dT%H:%M:%SZ")`).
- **§2.6 — revise —** Appended an explicit exception to the "OCC checks come last, after state checks" sentence: on submit-recommendation the `expected_opinion_version` staleness check is evaluated before the state-machine check, so a stale version is rejected with `ERR_STALE_VERSION` (412) even when the case has left `IN_REVIEW` — `implementation/routes_records.py:364-367`.

**Per-edit pre-edit search log:**

1. *Clock rendering edit*
   - (a) Subject: rendering format of logical-clock-derived timestamps.
   - (b) Enumerated impl paths: `common.py:18-30` (`now_iso` vs `clock_iso`); grep of `clock_iso` call sites — `routes_core.py:28` (`current_utc`), `routes_core.py:397` (`revoked_at`), `routes_claims.py:380` and `routes_claims.py:398` (`decided_at`); grep of `now_iso` call sites — `calcs.py:89`, `common.py:38,46,147`, `helpers.py:11` (all wall-clock `created_at`/`updated_at`/`api_request_timestamp`); grep of `db.clock` — `common.py:121,127`, `routes_claims.py:418`, `routes_nav.py:301,313,327` (all raw-datetime comparisons, no rendering).
   - (c) Wording scoped to "readings of the logical clock" and to fields "stamped with the logical clock time," explicitly exempting `created_at`/`updated_at`/`api_request_timestamp`, so no wall-clock path is mis-described.

2. *OCC ordering edit*
   - (a) Subject: evaluation order of OCC vs state-machine checks.
   - (b) Enumerated impl paths: `routes_records.py:349-374` (`submit_recommendation` — staleness before IN_REVIEW check, before reviewer binding); `routes_core.py:166-199` (`create_coverage_window` — overlap business-rule check at line 196 runs *before* `expected_member_version` OCC at line 199); grep for all `expected_opinion_version`/`expected_member_version` occurrences confirmed these are the only two OCC sites; §2.7/§3.7 PRD prose cross-checked.
   - (c) Wording names the exception narrowly as "the opinion-submission staleness check of §2.7" and leaves the general rule (and the `expected_member_version` half of the original sentence) intact, so the coverage-window path — where OCC does not precede all state/business checks — is not mis-described.

## Step 9: Complete PRD — 2026-09-30T02:52:58.000Z

All edits applied cleanly — 15 changed paragraphs, same line count, +3,515 chars.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (316 lines, 54,561 chars) → `workspace/PRD_COMPLETED.md` (316 lines, 58,076 chars); +3,515 chars, 15 paragraphs edited inline, no sections added.

**Counts:** 15 ambiguity-pins, 0 mismatch-revisions. (The PRD had no outright contradictions of the implementation; every change pins a behavior the prose left open.)

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — pinned that the dependent-proxy rule (subscriber acting for dependents via `subscriber_id`) applies to every member-scoped check including writes (revoke, appeal, settle, deliver, withdraw, creations) — `implementation/common.py:104-113` (`check_member_scope` used uniformly across all member-scoped routes).
- §2.4 — insert — ambiguity — clock set has no monotonicity check (backwards targets accepted); sweep folded into the same sentence — `implementation/routes_core.py:20-28`.
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — `implementation/helpers.py:16` (`new_entity`).
- §2.8 — insert — ambiguity — a consent created with an already-reached `expires_at` is born ACTIVE and immediately EXPIRED within the same request; consent listing accepts optional `scope` and `status` filters — `implementation/routes_core.py:362,375-380`.
- §3.1 — insert — ambiguity — `subscriber_id` must resolve to an existing member (404 otherwise) but same-employer is not enforced — `implementation/routes_core.py:93-96`.
- §3.1 — insert — ambiguity — deactivate/reactivate require the opposite state, else `ERR_INVALID_STATE` — `implementation/routes_core.py:145-146,157-158`.
- §3.1 — revise — ambiguity — coverage-window paragraph: overlap check runs before the OCC check; supersede fires only when the new window starts strictly after the prior OPEN window's start (equal/earlier start leaves the prior window untouched, coexisting as a second OPEN window); window `status` filter and employer-member `eligibility_status`/`relationship` filters validated against their enums — `implementation/routes_core.py:182-208,229-232,63-70`.
- §3.3 — insert — ambiguity — non-applicable conditional intake fields are stored null (`acuity` unless CLINICAL, `estimated_cost_cents` unless COST) — `implementation/routes_nav.py:49-50`.
- §3.4 — insert — ambiguity — provider-day occupancy is derived on demand from BOOKED appointments by slot-start date, not persisted — `implementation/routes_nav.py:186-196`.
- §3.4 — revise — ambiguity — reschedule re-checks the APPOINTMENT_BOOKING consent gate; overlap/capacity checks exclude the appointment itself; member cancellation is not consent-gated; `late_cancel` born false — `implementation/routes_nav.py:283-285,292-303,229`.
- §3.6 — insert — ambiguity — opinion-case opening check order pinned: eligibility → benefit-enabled → consent; benefit-disabled rejected with `ERR_INVALID_REQUEST` — `implementation/routes_records.py:181-187`.
- §3.6 — revise — ambiguity — attach-records accepts any non-terminal case state, transitions only INTAKE→RECORDS_COLLECTION, and an unresolvable `record_request_id` yields `ERR_RECORD_NOT_READY` — `implementation/routes_records.py:234-236,252-254`.
- §3.7 — insert — ambiguity — claim import/adjudicate/void are not gated by member eligibility; §2.10's freeze does not name claims — `implementation/routes_claims.py:19-60` (no eligibility check anywhere in claim routes).
- §3.8 — insert — ambiguity — billing-case opening: claim must exist and belong to the path member (both → 404), and this reference check precedes eligibility/consent gates — `implementation/routes_claims.py:160-168`.
- §3.9 — insert — ambiguity — approval re-stamps `decided_at` for appealed authorizations; the 30-day appeal window is inclusive at the boundary (`clock > decided_at + 30d` rejects) — `implementation/routes_claims.py:380,417-419`.
- §4 — insert — ambiguity — unmatched paths and unsupported methods return `ERR_NOT_FOUND` (404) — `implementation/app.py:25-32`.
