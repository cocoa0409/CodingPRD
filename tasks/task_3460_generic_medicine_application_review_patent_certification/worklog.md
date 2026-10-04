# Worklog — task_3460_generic_medicine_application_review_patent_certification

## Step 1: Create task directory — 2026-10-02T08:00:00.000Z

Pre-allocated task directory verified: `./tasks/task_3460_generic_medicine_application_review_patent_certification/` exists with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T09:13:00.000Z

All artifacts are complete and verified. Final summary for the worklog:

---

## Task 3460 scaffold generation — complete

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3460_generic_medicine_application_review_patent_certification/`):

| File | Lines | Contents |
|---|---|---|
| SCAFFOLD.yaml | 1633 | 14 entities, 10 state machines, 15 calculations, 22 validations, 41 endpoints, 37 errors, 5 roles, 2 OCC concurrency rules; §1.0 envelope verbatim; **no** `scaffold_difficulty_design`/`scaffold_corner_design` keys |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 1341 | single key `scaffold_difficulty_design`; 9 rules, 19 non-stub instances (2 per rule, `combinatorial_formula` has 3 covering modes a/b/c) |
| SCAFFOLD_CORNER_DESIGN.yaml | 2131 | single key `scaffold_corner_design`; 53 entries: 41 active instances + 12 `excluded_because` stubs (all stub refs verified to exist in §1.8) |

**Lint**: `scaffold_lint.py` → `VERDICT: clean lint` (41 endpoints, 14 entities, 19 §1.8 + 41 §1.9 active instances, 548 calls scanned, 0 violations). Also verified: all 37 error codes referenced by ≥1 validation/transition/endpoint; all `grounds:` resolve; 72 instance names unique across both design files; no forbidden concurrency vocabulary.

**api_prefix**: `/generic-drug-review` (business surface); clock is unprefixed at `POST /_clock/set_current_utc`. Total endpoints: 41.

**Logical clock**: default `2026-09-01T00:00:00Z` (pinned in the clock endpoint description); forward-only (backward → ERR_INVALID_REQUEST); drives all system transitions (patent/protection expiry, deficiency lapse, suit-window close, stay expiry, exclusivity forfeit/expire, CBE-30 effectivity, TA re-evaluation).

**Pinned constants** (grep anchors for drift checks): `P4_NOTICE_WINDOW_DAYS=20`, `SUIT_WINDOW_DAYS=45` (day 45 inclusive), `LITIGATION_STAY_MONTHS=30`, `EXCLUSIVITY_DAYS=180` (block lifts AT end date, strict <), `FAILURE_TO_MARKET_DAYS=75` (deadline day timely), `TA_FAILURE_MONTHS=30`, `STANDARD_REVIEW_MONTHS=10`, `PRIORITY_REVIEW_MONTHS=8`, `MAJOR_AMENDMENT_EXTENSION_MONTHS=3` (uncapped, per cycle), `DEFICIENCY_RESPONSE_MONTHS=12` (due date inclusive), `NCE_PIV_BAR_MONTHS=48` / `NCE_FULL_BAR_MONTHS=60` (both inclusive), `BE_CI_LOWER_BOUND_PCT=80.00` / `BE_CI_UPPER_BOUND_PCT=125.00` (inclusive; round_half_up per-bound to 2dp BEFORE comparison), `DOMESTIC_WAIVER_PRIOR_PASS_MONTHS=24`, `CBE30_EFFECTIVE_DAYS=30`. Month arithmetic: calendar months, clamp overflow to month-end (`add_months(2027-01-31,10)=2027-11-30`).

**Domain interpretation literals the PRD must reproduce verbatim**:
- Certification types: `PARAGRAPH_II_EXPIRED | PARAGRAPH_III_DEFER | PARAGRAPH_IV_CHALLENGE`; Paragraph I = RLD with zero listed patents → zero certifications required.
- Stay anchor: `stay_until = notice_date + 30 months`; is_timely = notice within 20 days of received_date (late notice recorded but forfeits award, `NOTICE_LATE`).
- Suit window: `suit_deadline = notice_date + 45 days` inclusive; late suit is unrecordable (clock flips notice to `NO_SUIT_FILED` first) — I removed a self-contradictory late-suit-acceptance branch during authoring.
- Court outcomes: `PATENT_VALID` (block converts to patent-expiry deferral) | `PATENT_INVALID_OR_NOT_INFRINGED` (block lifts).
- Approval routing: patent blocks and competitor exclusivity route APPROVE → `TENTATIVE_APPROVAL` (never an error); missing P4 notice at approval IS an error (`ERR_P4_NOTICE_REQUIRED`); open suit window contributes NO block (optimistic variant pinned; conservative documented as non-implemented variant).
- Forfeiture reasons enum: `NOTICE_LATE | CERTIFICATION_AMENDED | APPLICATION_WITHDRAWN | APPLICATION_LAPSED | TA_NOT_OBTAINED_30MO | MARKETING_NOT_COMMENCED_75D`; REFUSED_APPROVAL deliberately does NOT forfeit.
- First-filer tie-break: earliest receipt-commit order (created_at/commit order, never id).
- Overlap semantics deliberately divergent: inspections half-open `[start,end)` (adjacency allowed) vs protected indications closed `[from,until]` (adjacency = conflict).
- Supplement pathway map: `MANUFACTURING_SITE→[PRIOR_APPROVAL]`, `FORMULATION→[PRIOR_APPROVAL]`, `LABELING→[PRIOR_APPROVAL,CBE_30]`, `PACKAGING→[PRIOR_APPROVAL,CBE_30,CBE_0]`, `EDITORIAL→[CBE_0,ANNUAL_REPORT]`; ANNUAL_REPORT is born `LOGGED`×`EFFECTIVE`, never reviewable.
- Validation order: auth(1-3) → existence(4) → shape(5) → OCC(6) → state(7) → safety(8-10) → temporal(11-13) → constraint(14-18) → referential(19-22); Rule-5 pairs: (state, temporal) at submit and (safety, constraint) at approval-decision.
- Ownership: `ApplicantSponsor` is `entity_backed:ApplicantCompany`; `InnovatorSponsor` is `opaque` but bound to `ReferenceProduct.patent_owner_user_id`.
- Second-round deficiency: issuing from `AMENDMENT_RECEIVED` closes the cycle (`SUPERSEDED`) and opens cycle N+1 already in `CRL_ISSUED`.

Orchestrator verification: all three files parse (yaml.safe_load), SCAFFOLD.yaml top keys = [scenario, domain_name, api_prefix, complexity_profile, response_envelope] with no design-index keys; 93 on-domain `generic-drug-review` hits in SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-10-02T09:14:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T09:36:00.000Z

The PRD is complete and all audits pass. Final verification summary below.

---

**PRD generation complete — `workspace/PRD.md` at 316 lines** (`/home/ubuntu/github/CodingPRD/tasks/task_3460_generic_medicine_application_review_patent_certification/workspace/PRD.md`)

**Hard-contract audit results (all PASS):**
- Contract 1 (Field-Name Coverage): 102 required identifiers (all `entities[].fields[].name`, all `endpoints[].input`/query params, common fields, pagination params, `current_utc`) — 102 present in backticks, 0 missing.
- Contract 2 (Rule Coverage): all 22 validation priorities expressed as an ordered pipeline in §2.7; both OCC rules in §2.6 (`expected_application_version`, `ERR_STALE_VERSION`/412, no other endpoint takes a version field); all state-machine transitions/side-effects across 10 machines in §3.1–3.9; all 13 calculations rendered as precise prose (no operators, no fuzzy words — audited programmatically); all 37 error IDs appear in §1–§3 prose AND in the §5 table; all 41 endpoints appear in the 4-column §4 table; §5 has exactly 2 columns.
- Contract 3 (§3 Path Purity): 494 backticked tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos.
- §2.2 verified byte-identical to `section-2.2-response-structure.md` via diff.

**Literal-preservation checklist (name → value → PRD location):**
- P4_NOTICE_WINDOW_DAYS=20 (day 20 inclusive) → §3.4
- SUIT_WINDOW_DAYS=45 (day 45 inclusive) → §3.4
- LITIGATION_STAY_MONTHS=30 (clamped) → §3.4
- EXCLUSIVITY_DAYS=180 → §3.8
- FAILURE_TO_MARKET_DAYS=75 (deadline day timely) → §3.8
- TA_FAILURE_MONTHS=30 → §3.8
- STANDARD_REVIEW_MONTHS=10 / PRIORITY_REVIEW_MONTHS=8 → §3.3, §3.5
- MAJOR_AMENDMENT_EXTENSION_MONTHS=3 (no cap, recompute per amendment) → §3.5
- DEFICIENCY_RESPONSE_MONTHS=12 (due date inclusive) → §3.5
- NCE_PIV_BAR_MONTHS=48 / NCE_FULL_BAR_MONTHS=60 (both inclusive; exactly at +48 with P4 allowed, one day earlier barred) → §3.3
- BE_CI_LOWER_BOUND_PCT=80.00 / BE_CI_UPPER_BOUND_PCT=125.00 (inclusive; round half up to 2 decimals per bound before comparison) → §3.3 and §2.9
- DOMESTIC_WAIVER_PRIOR_PASS_MONTHS=24 → §3.6
- CBE30_EFFECTIVE_DAYS=30 (thirtieth day counts) → §3.9
- Calendar-month clamp: add_months(2027-01-31, 10) = 2027-11-30 → §2.4 (verbatim example)
- Certification-type enum (PARAGRAPH_II_EXPIRED | PARAGRAPH_III_DEFER | PARAGRAPH_IV_CHALLENGE) → §3.3
- Forfeiture-reason enum (all six: NOTICE_LATE, CERTIFICATION_AMENDED, APPLICATION_WITHDRAWN, APPLICATION_LAPSED, TA_NOT_OBTAINED_30MO, MARKETING_NOT_COMMENCED_75D) → §3.8
- Supplement change-type → pathway map (all five change types with exact pathway sets) → §3.9
- Inspection half-open [start,end) with adjacency allowed vs protected-indication closed [from,until] with adjacency-as-conflict → §3.6 and §3.2, cross-referenced
- Logical-clock default 2026-09-01T00:00:00Z, forward-only, backward → ERR_INVALID_REQUEST → §2.4

**Scaffold rules that could NOT be rendered without adjudication (rendered as-stated, flagged here):**
1. **ACTIVE-award forfeiture on withdrawal**: the `GenericApplication` APPROVED→WITHDRAWN transition and the withdraw endpoint's side-effects forfeit an award in AWARDED *or ACTIVE* status, while the `ExclusivityAward` machine's own FORFEITED transitions enumerate only ELIGIBLE|AWARDED. PRD §3.8 renders the more specific withdraw rule verbatim ("an `AWARDED` or `ACTIVE` award is forfeited"); not silently resolved either way.
2. **COURT_DECIDED date bounds**: the scaffold states `event_date >= suit_filed_date` and `<= current logical date` only on the DECIDED_INVALID transition; DECIDED_VALID lists only the state precondition. PRD §3.4 states the bounds once at the COURT_DECIDED event level (applying to both outcomes), matching the endpoint-level note and the `ERR_INVALID_REQUEST` catalog condition.
3. **TA_NOT_OBTAINED_30MO scope**: listed only under ELIGIBLE→FORFEITED in the award machine (an AWARDED award implies APPROVED was reached, making the condition vacuous); rendered as an ELIGIBLE-only forfeiture in §3.8.

Note for downstream: an early audit run falsely reported 99 missing fields due to backtick-parity corruption from the ```json fences in §2.2; re-running with fence-stripped extraction confirmed 0 missing. The §3 purity scan was unaffected (§3 contains no fences).

Orchestrator verification: workspace/PRD.md = 316 lines; 41 `generic-drug-review` hits; literals 80.00 (×4), 125.00 (×4), 2026-09-01T00:00:00Z, 2027-11-30, ERR_P4_NOTICE_REQUIRED (×4), PARAGRAPH_IV_CHALLENGE (×5) all present.

## Step 5: Generate unit tests — 2026-10-02T11:05:00.000Z

Test generation complete; all audits pass. Self-contained summary below.

---

**Step 5 summary — task_3460 unit test suite**

**Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3460_generic_medicine_application_review_patent_certification/`):**

test_helpers/ (9 files):
- `test_helpers/__init__.py` (18 lines) — barrel: framework generics + PRD-specific exports
- `test_helpers/types.py` (143) — 5+ role/status enums, 14 entity TypedDicts (all carry common fields per PRD §2.5)
- `test_helpers/constants.py` (37) — 17 domain constants (see diff below)
- `test_helpers/api_errors.py` (88) — 37 ApiErrorId members + HTTP map, registered via set_error_http_status_map
- `test_helpers/test_users.py` (25) — opaque-role shared headers + make_applicant_headers/make_innovator_headers per-instance builders
- `test_helpers/api_client.py` (148) — 40 endpoint methods; clock method posts raw unprefixed `/_clock/set_current_utc`, business methods carry `/generic-drug-review`
- `test_helpers/factories.py` (90) — 11 payload factories (input fields only; use_code omitted unless METHOD_OF_USE)
- `test_helpers/assertions.py` (105) — common-fields + 14 per-entity assertions
- `test_helpers/fixtures.py` (152) — set_clock, makers, add_certification/add_amendment with OCC refresh, submit/approve/notice helpers, and composites setup_submitted / setup_approved / setup_tentative_p3; all thread entity-backed X-User-ID

test_suite/ (22 files, 60 tests):
- `conftest.py` (25) — session api fixture + role-header fixtures
- Queue A (19 tests): test_01_dual_variant_calc.py (79, 2 tests), test_02_combinatorial_formula.py (143, 3), test_03_non_linear_state_machine.py (78, 2), test_04_transitive_cascade.py (70, 2), test_05_priority_pair_conflicts.py (68, 2), test_06_boundary_precision.py (69, 2), test_07_cross_entity_state.py (70, 2), test_08_temporal_overlap.py (73, 2), test_09_compensating_invariants.py (62, 2)
- Queue B (41 tests): test_10_corner_entities.py (130, 5), test_11_corner_entity_inputs.py (77, 4), test_12_corner_state_machines.py (108, 4), test_13_corner_state_machines_more.py (82, 3), test_14_corner_calculations.py (108, 3), test_15_corner_calculations_more.py (105, 3), test_16_corner_validations.py (120, 5), test_17_corner_validations_more.py (117, 4), test_18_corner_endpoints.py (99, 3), test_19_corner_errors.py (64, 1), test_20_corner_rbac.py (92, 4), test_21_corner_complexity_and_consistency.py (74, 2)

**Tests emitted per queue:** Queue A (Difficulty): 19/19 instances translated (one test per instance). Queue B (Corner): 41/41 active instances translated; 12 excluded_because stubs correctly have no test (cross-references verified to resolve to queue-A instance names).

**SKIPPED instances:** none. Every active instance passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability). One derivability tightening was applied inside a translated test: `applicant_company_create_returns_envelope_defaults_and_fixed_clock` asserts created_at startswith "2026-09-01T00:00:00" rather than the exact literal, because PRD §2.5 pins three fractional digits ("2026-09-01T00:00:00.000Z" vs "…Z" is a two-reader split; the date-instant prefix is the uniquely derivable part).

**AST tag audit (real ast.walk over docstrings, tags diffed against both source YAMLs):**
- (a) test functions: 60
- (b) with exactly one valid Design: tag: 60
- (c) tags pointing to non-existent instances: 0
- Untranslated active instances: 0; per-queue coverage: Difficulty 19/19, Corner 41/41

**pytest --collect-only:** `60 tests collected in 0.30s`, 0 errors (PYTHONPATH=task dir).

**PRD verbatim-citation sweep:** 77 quoted spans across 60 docstrings; whitespace-normalized containment in workspace/PRD.md: 77/77 found, 0 failures (7 initially non-verbatim spliced quotes were rewritten to full-sentence quotes).

**Constants diff (constants.py vs PRD prose) — all 17 MATCH:**
CLOCK_START_ISO=2026-09-01T00:00:00Z (§2.4); BE_CI_LOWER_BOUND_PCT=80.00 / BE_CI_UPPER_BOUND_PCT=125.00 inclusive (§2.9/§3.3); STANDARD_REVIEW_MONTHS=10 / PRIORITY_REVIEW_MONTHS=8 / MAJOR_AMENDMENT_EXTENSION_MONTHS=3 (§3.5); P4_NOTICE_WINDOW_DAYS=20 / SUIT_WINDOW_DAYS=45 / LITIGATION_STAY_MONTHS=30 (§3.4); DEFICIENCY_RESPONSE_MONTHS=12 (§3.5); NCE_PIV_BAR_MONTHS=48 / NCE_FULL_BAR_MONTHS=60 (§3.3); DOMESTIC_WAIVER_PRIOR_PASS_MONTHS=24 (§3.6); EXCLUSIVITY_DAYS=180 / FAILURE_TO_MARKET_DAYS=75 / TA_FAILURE_MONTHS=30 (§3.8); CBE30_EFFECTIVE_DAYS=30 (§3.9).

**Trap checks:** no hardcoded ports (0 hits for 8000/5000/localhost in both trees); no pytest.mark.skip/skipif/xfail anywhere; all validate_success calls on create endpoints pass 201 explicitly (action endpoints 200); every clock-set sequence is forward-only from the 2026-09-01T00:00:00Z start (audited per file); clock calls go to the unprefixed path; ownership-gated calls use make_applicant_headers(entity_id), never the shared constant; first-filer assertions depend on submit order, never id ordering.

Orchestrator verification (independent re-run, not the subagent's numbers): `pytest --collect-only` → 60 tests collected, 0 errors; orchestrator-run AST tag audit → 60 tests / 60 valid single Design tags / 0 bad tags / 0 uncovered active instances across both YAMLs. (Note: the subagent appended this Step 5 entry itself; format verified compliant, so it stands as the step record.)

## Step 6: Generate implementation — 2026-10-02T11:47:00.000Z

All verification complete. Final state: 41 PRD-table endpoints (40 business + 1 unprefixed clock), 37 error ids, zero seeding, fresh-boot verified.

## Summary (for worklog.md)

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3460_generic_medicine_application_review_patent_certification/workspace/implementation/`):

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | Launcher: guarded pip install, `exec python3 app.py`, `$PORT`/0.0.0.0/foreground |
| requirements.txt | 1 | `flask>=2.2` |
| app.py | 71 | Factory, blueprint wiring, envelope-wrapped error handlers, `__main__` |
| state.py | 56 | In-memory `STORE` (14 kinds, dicts keyed by id), `create_entity`/`touch`, global commit `seq` |
| clock.py | 74 | Logical clock (starts 2026-09-01T00:00:00Z), `add_months` with month-end clamp, `add_days`, `round2` half-up |
| errors.py | 63 | All 37 error ids with exact HTTP statuses |
| envelope.py | 72 | `{meta, response_type, data}` envelope, pagination `limit/offset/total_count/has_more` |
| auth.py | 45 | X-User-ID/X-User-Role validation, role check, ownership checks |
| validate.py | 103 | Priority-5 shape helpers (unknown/system fields ignored) |
| domain.py | 234 | BE adequacy, carve-out equality, NCE bar, cert completeness, `patent_blocked_until`, `exclusivity_blocked`, facility clearance, pathway map |
| serialize.py | 179 | Per-entity serializers (computed fields resolved per read) |
| system_eval.py | 135 | Clock-driven transitions (patent/protection expiry, deficiency lapse, suit-window close, stay expiry, TA/75-day forfeitures, exclusivity expiry, CBE-30 effectivity) + TA re-evaluation + award forfeiture |
| routes_clock.py | 30 | POST `/_clock/set_current_utc` (unprefixed, ProgramAdmin, monotonic) |
| routes_companies.py | 77 | Applicant companies + manufacturing facilities (4 endpoints) |
| routes_reference.py | 169 | Reference products, listed patents, protected indications (6 endpoints) |
| routes_applications.py | 146 | Application create/list/get + submit filing gate (4 endpoints) |
| routes_app_actions.py | 134 | approval-decision, withdraw, record-first-marketing (3 endpoints) |
| routes_studies.py | 59 | BE study create/list (2 endpoints) |
| routes_certifications.py | 117 | Certification create/get/list + amend (4 endpoints) |
| routes_notices.py | 126 | Notice create/list + litigation events (3 endpoints) |
| routes_cycles.py | 152 | Cycle list, issue-deficiency (incl. second-round), amendment create/list (4 endpoints) |
| routes_inspections.py | 126 | Inspection create/get/list + record-outcome (4 endpoints) |
| routes_supplements.py | 119 | Supplement create/list + review-decision + withdraw (4 endpoints) |
| routes_awards.py | 38 | Award get/list (2 endpoints) |

**Endpoint count**: 41/41 PRD §4 table rows implemented (40 business under `/generic-drug-review` + 1 unprefixed clock), verified against the live URL map (42 rules = 41 API + Flask's builtin `/static`).

**py_compile results**: all 21 Python files compile; `from app import create_app` imports the full package graph cleanly. One bug was caught and fixed during verification: `routes_inspections.py` was missing `req_enum` in its validate import (500 on record-outcome); fixed and re-verified.

**Boot smoke test**: `bash start.sh` on dynamic port 58413 — unauthenticated POST /applications → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; POST /applicant-companies as ProgramAdmin → 201; GET created company → 200; GET missing id → 404 `ERR_APPLICANT_NOT_FOUND`; clock set → 200 `{"current_utc": ...}`; backward clock → 400. Server killed by exact PID (1023591). Fresh-reboot check on port 43919: empty store (`total_count: 0`), clock reset to `2026-09-01T00:00:00.000Z`, killed exact PID (1028533).

**Behavioral verification**: six in-process e2e suites exercised the deep machinery — round-first BE bounds (80.005→pass, 79.994→fail), OCC 412/409 ordering, half-open inspection overlap (adjacency allowed), NCE 48/60-month boundaries, deficiency → MAJOR amendment goal extension (+3mo) → second-round CRL → lapse cascade with APPLICATION_LAPSED forfeiture, suit → 30-month stay → TA → STAY_EXPIRED auto-approval, first-filer award AWARDED/ACTIVE/EXPIRED with sibling `exclusivity_blocked` re-evaluation, NOTICE_LATE with the no-successor-award rule, TA_NOT_OBTAINED_30MO, CERTIFICATION_AMENDED forfeiture + P3-treatment, DECIDED_VALID blocking to patent expiry, P3 deferral release exactly on expiry date, TA reopen via amendment (MAJOR → new cycle extensions=1), foreign/domestic waiver 24-month rule, CBE-30 day-30 effectivity + REJECT revocation, ANNUAL_REPORT LOGGED + `ERR_SUPPLEMENT_NOT_REVIEWABLE`, pathway-map 422s, pagination envelope, RBAC 403s, ownership-before-existence 404s.

**Ambiguities found and interpretations chosen** (feed Step 8/9):
1. **Carve-out double-failure precedence**: when the carved set both misses an ACTIVE code and names an unprotected one, I return `ERR_LABEL_CARVE_OUT_INCOMPLETE` (missing checked first, matching the scaffold's "INCOMPLETE / UNPROTECTED" listing order).
2. **Approval-gate order, carve-out vs P4-notice**: PRD §2.7's numeric pipeline puts carve-out (priority 14) before P4 notice (17); §3.7's prose lists P4 first. I followed §2.7 (the declared fixed order): carve-out, then P4.
3. **`ERR_DEFICIENCY_RESPONSE_OPEN` scope**: applied to both APPROVE and REFUSE (PRD §3.5: "a review decision is refused outright"), despite §3.7's "refusal is always available" and the scaffold REFUSE transition listing only `ERR_INVALID_STATE`.
4. **`ERR_SUPPLEMENT_NOT_REVIEWABLE` vs `ERR_INVALID_STATE`**: ANNUAL_REPORT supplements are born LOGGED (never SUBMITTED), so a review-status check first would make the dedicated error dead code; I check `pathway == ANNUAL_REPORT` first so the catalog error fires.
5. **Litigation-event sub-role ordering**: event_type (a body field) selects the permitted role. Order implemented: notice 404 → event_type enum (400) → event-role (403) → SUIT_FILED ownership vs `patent_owner_user_id` (403) → remaining shape (400) → notice state (409) → date-window semantics (400).
6. **record-first-marketing on non-APPROVED app**: PRD §3.8 and the state machine say `ERR_INVALID_STATE`; the error catalog's condition for `ERR_APPLICATION_NOT_APPROVED` also mentions first-marketing. PRD prose + state machine win → `ERR_INVALID_STATE`.
7. **CANCELLED inspection `outcome_date`**: endpoint side_effects say "outcome_date set" for all four outcomes; the CANCELLED transition is silent. I stamp it for all four.
8. **`certification_type` after amend**: serialized unchanged (`PARAGRAPH_IV_CHALLENGE` with status `AMENDED_TO_P3`); "treated as P3" governs block computation only (field is `source: input`).
9. **CBE_30 approved before day 30**: the literal rule gates the flip on `review_status == SUBMITTED` and "approval leaves CBE_30 timing untouched", so an early-approved CBE_30 stays NOT_EFFECTIVE. Implemented literally.
10. **Timestamps**: `created_at`/`updated_at`/`api_request_timestamp` come from the logical clock ("never wall-clock time"); commit-order ties break via an internal monotonic `seq` (never serialized).
11. **Pagination out-of-range**: limit clamped to [1,100], negative offset clamped to 0; non-integer limit/offset → 400 `ERR_INVALID_REQUEST`.
12. **Patent status flip vs block release**: patent becomes EXPIRED only when clock date > expiry_date ("moved beyond"), while P3/DECIDED_VALID blocks release AT expiry_date (blocked while current < expiry). Both rules implemented as stated.
13. **Forfeiture/expiry boundaries**: TA-failure forfeits when clock > received+30mo; marketing forfeit when clock > deadline (deadline day timely); exclusivity EXPIRED when clock >= end date (lifts AT the date); CBE_30 effective when clock >= submitted+30d; deficiency lapses when clock > due date (due-date response timely).
14. **Born-EXPIRED protection windows**: overlap (priority 13) only evaluated when the new window is ACTIVE; EXPIRED windows (new or existing) never block.
15. **Naive `to_iso8601`** (no Z/offset): treated as UTC.
16. **`inspection_type` in request body**: not in the endpoint input list; if supplied must be `PRE_APPROVAL` else 400; omitted → `PRE_APPROVAL`.
17. **Facility-clearance "latest"**: latest non-CANCELLED inspection per facility by commit order (seq bumps on outcome recording); a later SCHEDULED inspection supersedes an earlier PASSED and fails clearance until resolved.
18. **Pagination on undeclared list endpoints**: `limit`/`offset` honored and meta pagination fields emitted on every list endpoint (PRD §2.2: pagination fields are included for list endpoints), including those whose endpoint-table input row is empty.

Orchestrator verification: all 22 implementation files present and py_compile clean; live URL map = 42 rules (40 prefixed business + 1 unprefixed `/_clock/set_current_utc` + Flask `/static`), matching the claim.

## Step 7: Run tests and iterate — 2026-10-02T10:44:00.000Z

Clean 8-round parallel sweep on the first iteration — no diagnosis or fixes needed.

**Summary**
- Iterations run: 1 (single 8-round parallel sweep, all rounds run to completion concurrently).
- Tests deleted: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.
- Final sweep evidence (passed/total per round):
  - results.1.json: 60/60
  - results.2.json: 60/60
  - results.3.json: 60/60
  - results.4.json: 60/60
  - results.5.json: 60/60
  - results.6.json: 60/60
  - results.7.json: 60/60
  - results.8.json: 60/60
- All 8 `results.*.json` files remain on disk in `/home/ubuntu/github/CodingPRD/tasks/task_3460_generic_medicine_application_review_patent_certification/workspace/implementation/` as required output artifacts (verified via `ls` after the sweep; not deleted or moved).

Note: per-test status breakdown confirmed every test reports `passed` in every round — no flakiness signal (no test passed in some rounds while failing in others). The union of failing tests across all 8 rounds is empty, so STEP 0 of the diagnostic protocol terminated with an empty union set and no further steps were triggered.

Orchestrator verification: independently parsed all 8 results.*.json — each reports passed=60/total=60 with all 60 per-test statuses 'passed'; files timestamped 2026-10-02T10:41Z, present on disk.

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T10:44:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the tested sites; no PRD_FINALIZED.md produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-10-02T11:20:00.000Z

Diff verified — 12 changed paragraphs, all in-place. `results.{1..8}.json` untouched (mtimes still 10:41, never opened for write). Work complete. Final report:

## Summary

**Source vs output:** `workspace/PRD.md` 316 lines / 54028 chars → `workspace/PRD_COMPLETED.md` 316 lines / 56533 chars (char-delta +2505, zero lines added — all edits are in-paragraph inserts/revisions).
**`diff -q` output:** `Files PRD.md and PRD_COMPLETED.md differ` (edit set is real, not a silent no-op; full diff inspected — exactly the 12 intended paragraph changes at lines 74, 78, 86, 147, 161, 167, 185, 191, 195, 197, 209, 223).

**Counts:** 12 ambiguity-pins, 0 mismatch-revisions, 0 impl bugs.

**Changes (one per bullet):**
- §2.3 — revise — ambiguity — pinned pagination clamping (`limit` <1→1, >100→100, negative `offset`→0, non-integer either→`ERR_INVALID_REQUEST`), `total_count`/`has_more` semantics, and `created_at` tie-break by commit order never resource id — `workspace/implementation/envelope.py:44-67,70-72`
- §2.4 — insert — ambiguity — all server-stamped instants (`created_at`, `updated_at`, `api_request_timestamp`) read the logical clock; naive `to_iso8601` interpreted as UTC — `implementation/state.py:38-39,50`, `implementation/envelope.py:13`, `implementation/clock.py:43-44`
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — `implementation/state.py:40`
- §3.3 — insert — ambiguity — when carve-out fails in both directions at once, `ERR_LABEL_CARVE_OUT_INCOMPLETE` is reported — `implementation/domain.py:53-58`
- §3.4 — insert — ambiguity — amended certification keeps stored `certification_type` = `PARAGRAPH_IV_CHALLENGE`; P3-treatment governs blocking/notice only — `implementation/routes_certifications.py:108-111`, `implementation/domain.py:142-145`
- §3.4 — insert — ambiguity — litigation-event endpoint: event-type selects actor (`SUIT_FILED`→InnovatorSponsor, `COURT_DECIDED`→ProgramAdmin, else `ERR_INSUFFICIENT_PERMISSIONS`); full check order notice-404 → event_type-400 → event-role-403 → ownership-403 → shape-400 → posture-409 → window-400 — `implementation/routes_notices.py:72-100`
- §3.6 — revise — ambiguity — `inspection_type` omissible, defaults `PRE_APPROVAL`, any other value `ERR_INVALID_REQUEST` — `implementation/routes_inspections.py:31`
- §3.6 — revise — ambiguity — clearance counts a facility's latest-recorded non-`CANCELLED` inspection whatever its posture; a latest still-`SCHEDULED` inspection fails clearance until its outcome is recorded — `implementation/domain.py:224-229`
- §3.7 — revise — ambiguity (self-contradictory prose) — "Refusal is always available" qualified: the `RECEIVED` posture and the §3.5 deficiency-response gate bind `APPROVE` and `REFUSE` alike — `implementation/routes_app_actions.py:37-44`
- §3.7 — revise — ambiguity (§3.7's enumeration contradicted its own "pipeline order of §2.7" preface) — gate list reordered to carve-out (§2.7 #14) before P4-notice (#17) — `implementation/routes_app_actions.py:57-61`
- §3.8 — insert — ambiguity — record-first-marketing response carries the updated `ExclusivityAward` object (the operation mutates both award and application; impl returns the award) — `implementation/routes_app_actions.py:134`
- §3.9 — revise — ambiguity — an annual report (born `LOGGED`) draws `ERR_SUPPLEMENT_NOT_REVIEWABLE`, checked before the `SUBMITTED` posture — `implementation/routes_supplements.py:81-86`

## IMPL BUGS

None. Every impl behavior traced to either an unambiguous PRD sentence it satisfies or a silent/ambiguous passage now pinned to it. The only unambiguous-sounding contradiction (§3.7 prose listing P4-notice before carve-out) is self-contradictory with §2.7's numbered pipeline that the same sentence invokes — adjudicated as ambiguity, pinned to impl's §2.7-consistent order.

## Checklist verdicts (18 + 3)

1. Carve-out double-failure precedence (INCOMPLETE first) — **EDIT-ADDED** (§3.3)
2. Approval-gate order carve-out (14) before P4-notice (17) — **EDIT-ADDED** (§3.7 swap; §3.7 prose self-contradicted §2.7)
3. `ERR_DEFICIENCY_RESPONSE_OPEN` gates both APPROVE and REFUSE — **EDIT-ADDED** (§3.7 "always available" qualified)
4. ANNUAL_REPORT pathway check before review-status → `ERR_SUPPLEMENT_NOT_REVIEWABLE` — **EDIT-ADDED** (§3.9)
5. Litigation-event validation order (404→enum→event-role→ownership→shape→state→window) — **EDIT-ADDED** (§3.4; PRD was silent on event-type role selection entirely)
6. record-first-marketing on non-APPROVED → `ERR_INVALID_STATE` — **PINNED-ALREADY** (§3.8 names it for both postures)
7. CANCELLED inspections stamp `outcome_date` — **PINNED-ALREADY** (§3.6 "stamped at recording" covers all four outcomes)
8. `certification_type` serialized unchanged after amend — **EDIT-ADDED** (§3.4)
9. CBE_30 approved before day 30 stays NOT_EFFECTIVE — **PINNED-ALREADY** (§3.9 "leaves CBE_30 timing untouched")
10. All timestamps from logical clock; commit ties via internal seq never serialized — **EDIT-ADDED** (§2.4 timestamps, §2.3 tie-break; seq is never emitted by any serializer — verified)
11. Pagination clamped `[1,100]`, negative offset→0, non-integer→400 — **EDIT-ADDED** (§2.3)
12. Patent EXPIRED only when clock > expiry; blocks release AT expiry — **PINNED-ALREADY** (§3.2 + §3.7 strict-inequality surfacing rule)
13. Boundary set (TA-30mo strict >, marketing-deadline strict >, exclusivity >=, CBE_30 >=, deficiency-lapse strict >) — **PINNED-ALREADY** (all five pinned by §3.5/§3.8/§3.9 boundary prose; impl `system_eval.py:74,107,114,120,129` matches each)
14. Born-EXPIRED protection windows never block, skip overlap — **PINNED-ALREADY** (§3.2 "a new ACTIVE window conflicts with an existing ACTIVE window" + "EXPIRED windows never block")
15. Naive ISO8601 → UTC — **EDIT-ADDED** (§2.4)
16. `inspection_type` defaults PRE_APPROVAL, others rejected — **EDIT-ADDED** (§3.6)
17. Clearance: latest non-CANCELLED by commit order; later SCHEDULED supersedes PASSED and fails — **EDIT-ADDED** (§3.6 "latest-recorded outcome" was ambiguous)
18. limit/offset + pagination meta on every list endpoint — **PINNED-ALREADY** (§2.2/§2.3 universal statements; `success_list` used by all 13 list routes)
- Scaffold-adjudication (a) withdrawal forfeits AWARDED *or ACTIVE* — **PINNED-ALREADY**, impl agrees (`routes_app_actions.py:104-106` vs §3.8 "from APPROVED (an AWARDED or ACTIVE award)")
- Scaffold-adjudication (b) COURT_DECIDED date bounds apply to both outcomes — **PINNED-ALREADY**, impl agrees (`routes_notices.py:111-114` single check pre-branch vs §3.4 single sentence covering both outcomes)
- Scaffold-adjudication (c) `TA_NOT_OBTAINED_30MO` is ELIGIBLE-only — **PINNED-ALREADY**, impl agrees (`system_eval.py:100` vs §3.8 "From ELIGIBLE" list)

**Out-of-scope observation (no edit):** unmatched routes/methods return `ERR_INVALID_REQUEST` with 404/405 (`app.py:47-55`); the PRD defines only its own endpoint surface, so this is outside the contract rather than a contradiction of it.

Artifact at `/home/ubuntu/github/CodingPRD/tasks/task_3460_generic_medicine_application_review_patent_certification/workspace/PRD_COMPLETED.md`.

Orchestrator verification: independent `diff -q` confirms PRD.md ≠ PRD_COMPLETED.md; line/char counts 316/54028 → 316/56533 match the claim exactly; all 8 results.*.json intact with 10:41 mtimes; `find` confirms zero implementation/*.py files (and start.sh) modified after the final sweep — the green 8× 60/60 sweep remains valid. No IMPL BUGs reported → no Step 9b fix-and-re-sweep cycle needed.
