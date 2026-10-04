# Worklog — task_3391_scholarship_qualification_semifinalist_selection_sponsor_awards

## Step 1: Create task directory — 2026-10-01T14:12:00.000Z

Task directory `tasks/task_3391_scholarship_qualification_semifinalist_selection_sponsor_awards/` was pre-allocated per command args (index not recomputed); verified it exists with an empty `workspace/` inside. No other `task_*` directory created.

## Step 2: Generate scaffold — 2026-10-01T14:28:00.000Z

Done. All three scaffold artifacts for task_3391 are generated, lint-clean, and verified.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_3391_scholarship_qualification_semifinalist_selection_sponsor_awards/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1930 | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1731 | `scaffold_difficulty_design:` — **18/18 non-stub instances** (2 per rule) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2915 | `scaffold_corner_design:` — **45 non-stub instances + 4 `excluded_because:` stubs** across 9 sections |

**Core counts:** 13 entities, 41 endpoints, 10 state machines, 7 calculations, 34 ordered validation rows, 32 error codes, 5 roles, 2 OCC concurrency rules.

**Design highlights (much-harder-than-expert calibration):** quota/allocation archetype + compliance layer; posture-driven `ProgramCycle` gating all child workflows; dual-variant apportionment (round-half-up provisional sums to 11 vs largest-remainder final summing to exactly 10 — fixture math pre-verified in Python) and reserved-vs-cash pool ledgers; combinatorial instances in distinct modes ((a) min-guarantee redistribution, (b) per-term rounding with last-term absorption, pre-computed `[41668×5, 41665]`); cyclic FinalistApplication correction loop + parallel Award dimensions (`recipient_status` × `funding_status`); depth-4+ cascades from *different* triggers (decline vs renewal-rejection); priority conflicts on distinct category pairs (state>constraint, temporal>fiscal); half-open agreement windows vs 2-day publicity minimum-gap; pool-cents and national-slot-count compensating invariants; segregation-of-duties RBAC; logical clock (default `2026-09-01T00:00:00Z`) driving deadlines, embargoes, disbursement due dates, and an offer-expiry sweep.

**Verification performed:** `scaffold_lint.py` verdict — `VERDICT: clean lint` (919 §1.8+§1.9 calls checked against §1.5; all FKs reverse-reachable). Additional self-audits the linter doesn't cover: 67/67 instance names unique across both design files; all 32 catalog errors referenced in scaffold rules AND exercised by at least one design instance; zero unbound `${var}` placeholders; all `grounds:` resolve to declared §1.1–§1.7 elements; zero forbidden concurrency vocabulary; all 4 stubs cite existing difficulty instances; no empty recipe sections. Two consistency fixes were caught and repaired mid-draft (OCC review needed resubmission before fresh-version CONFIRM; renewal-create requires ENROLLED so a term-1 release was added to the duplicate-renewal chain).

**Note:** 41 endpoints deliberately exceeds the 20–32 expert band per the difficulty instruction; per known pipeline risk (`>40` endpoints can strain impl-gen), the downstream Step 6 prompt should pre-constrain (one file per message, per-domain modules).

Orchestrator spot-check: all three files parse as YAML with expected top-level keys (`scenario`/`scaffold_difficulty_design`/`scaffold_corner_design`); scenario string matches the user's input verbatim; `domain_name: merit-scholarship-awards`, `api_prefix: /api` — on-domain, no foreign-domain contamination.

## Step 3: Copy shared files — 2026-10-01T15:51:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T16:05:00.000Z

All checks pass. The PRD is complete and verified.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_3391_scholarship_qualification_semifinalist_selection_sponsor_awards/workspace/PRD.md` — 284 lines, ending with the complete §5 error catalogue (last content row `ERR_CLOCK_REGRESSION | 422`, no truncation).

**Coverage confirmation:** All 7 §1.4 calculations are rendered as precise, pseudocode-free prose with every constant literal pinned (selection_index = sum of three section scores × section weight 2, range 48–228; state_slot_allocation in both variants — provisional round-half-up at close-entries vs final largest-remainder with `MIN_STATE_SLOTS` = 1, quota stored to 4 decimal places, tie-breaks population-then-`state_code`; semifinalist_threshold_and_selection with inclusive k-th threshold; sponsor_pool_availability reservation-vs-cash ledgers where only the reservation variant gates; award_matching_waterfall bucket order and per-bucket capacity rules; disbursement_schedule with 180-day term interval and pinned round-non-final-terms-first/remainder-absorbing-final ordering; waitlist_promotion one-award-per-iteration with 30-day acceptance window and 2-day publicity gap). All 10 state machines (45 transitions total: ProgramCycle 6, StateAllocation 2, Entry 3, FinalistApplication 8 including the unreachable-by-construction RETURNED_FOR_CORRECTION → DENIED edge, SponsorAgreement 6, CollegeInstitution 2, Award 11 across both parallel dimensions, Disbursement 4, RenewalVerification 2, Notification 2) appear with from → to pairs, preconditions paired to their error IDs, and every cascade side effect (4-link decline/expiry cascade, lapse cascade, AWARDS_COMPLETED bubble-up). All 41 endpoints appear in the §4 table with method, path, description, and authorized roles. All 32 error codes appear both in §2/§3 trigger prose and in the 2-column §5 table. All 39 §1.2 validation entries are expressed, with the full priority ordering 1–10 enumerated in §2.8 (including ERR_ENTRY_NOT_SEMIFINALIST-before-duplicate ordering and overlap-checked-before-pool-floor on amend). Hard contracts: Contract 1 field coverage 105/105 required identifiers present in backticks, 0 missing; Contract 2 rule coverage verified by systematic walk plus literal greps, 0 missing; Contract 3 §3 path purity 662 backtick tokens scanned, 0 path/method violations. §2.2 is byte-verbatim from the skill's canonical source file (verified by substring identity), pagination defaults (limit 10, 1–100; offset 0) and the logical-clock startup default 2026-09-01T00:00:00Z are stated exactly, and both OCC rules name their `expected_*_version` field, `ERR_STALE_VERSION`, and HTTP 412. One process note: the fenced JSON block in §2.2 flips naive backtick-pairing parity, so the coverage checker must strip fenced code blocks before extracting tokens — the PRD itself is correctly balanced.

Orchestrator spot-check: `workspace/PRD.md` is 283 lines per wc (subagent's 284 includes trailing newline), last 3 lines are the final error-catalogue rows (ERR_NOTIFICATION_SEQUENCE_VIOLATION, ERR_PUBLICITY_WINDOW_TOO_EARLY, ERR_CLOCK_REGRESSION) — non-truncated; 67 `ERR_` token occurrences; logical-clock default `2026-09-01T00:00:00Z` present.

## Step 5a: Generate test_helpers (Phase A of split Step 5) — 2026-10-01T16:25:00.000Z

Phase A is complete. The stray `test_*.py` match is `test_users.py` — the mandated role-headers module, not a test file.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3391_scholarship_qualification_semifinalist_selection_sponsor_awards/test_helpers/`):

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 36 | Barrel export (framework generics + all PRD-specific modules) |
| `types.py` | 402 | 22 status/enum classes + 13 entity TypedDicts; `School` correctly omits `updated_at`/`version` (PRD §2.4 exception) |
| `api_client.py` | 218 | `ApiClient(GenericApiClient)` — all 41 PRD §4 endpoints (verified 41/41 have methods) |
| `api_errors.py` | 82 | All 32 `ApiErrorId` codes + HTTP status map, registered via `set_error_http_status_map` |
| `assertions.py` | 334 | 13 per-entity shape assertions + `assert_pool_ledger_consistent` (reserved/cash reconciliation, PRD §3.6) + `assert_award_invariants` |
| `factories.py` | 211 | 14 payload factories, input-fields-only per PRD request schemas; optional fields (`parent_sponsor_id`, `first_choice_college_id`, `employee_children_only`, `min_selection_index`, `return_reason`) omitted by default so declared defaults stay observable |
| `constants.py` | 128 | PRD-literal rule constants + TEST_DEFAULTS scenario values |
| `test_users.py` | 56 | `TEST_USERS` (5 roles) + 4 entity-backed builders: `make_student_headers`, `make_school_official_headers`, `make_sponsor_admin_headers`, `make_college_admin_headers` |
| `fixtures.py` | 644 | Tier 1 granular actions (26 helpers), Tier 2 reads (paginated list + get helpers, `find_award`), Tier 3 stage composites (`setup_entry_open` → `setup_entry_closed` → `setup_semifinalists_selected` → `setup_finalists_selected` with `publish` flag → `setup_matching_run`), Tier 4 award lifecycle (`accept_all_awards`, `release_first_terms`, `setup_accepted_awards`, `setup_enrolled_awards`, `setup_renewal_submitted`), Tier 5 `setup_awards_completed` |

**Verification results:**
- All 9 files pass `python3 -m py_compile`; `import test_helpers.fixtures` (and the full package) succeed; every module's `__all__` resolves.
- **Constants vs PRD**: programmatic diff of the 32-code error map against PRD §5 table — exact match (ids + statuses). Every enum member across all 20 enums greps to PRD prose. Rule constants each traced to a verbatim literal: section weight 2 (§3.4), scores 8–38 (§3.1/§3.4/§3.5), index/floor 48–228, `MIN_STATE_SLOTS` exactly 1 (§3.2), quota 4 decimal places (§3.2), 30-day acceptance window (§3.7/§3.8), 180-day term interval (§3.8), 2-day publicity gap (§3.9), renewal GPA 2.5 (§3.8), GPA scale 0.0–4.0 (§3.5), pagination 10/1/100/0 (§2.3), clock start `2026-09-01T00:00:00Z` (§2.5), notification sequence 1–4 (§3.9).
- **Clock consistency**: all fixture-default dates (deadline 2027-12-15, embargoes 2027-09-10 / 2028-02-10 / 2028-03-01) are reachable from the 2026-09-01 clock start; clock moves only via `advance_clock()` wrapping the declared `POST /api/_clock/set_current_utc`.
- **Identity model**: fixtures thread entity-backed identities throughout — entries/applications/accept/decline as `make_student_headers(student["id"])`, endorse as `make_school_official_headers(school["id"])`, agreement create/amend as `make_sponsor_admin_headers(sponsor["id"])`, renewal submit as `make_college_admin_headers(award["college_id"])`; ProgramAdmin (opaque) uses the shared constant.
- No `test_suite/` and no `test_*.py` test files created — Phase B surface is frozen and fully exported (`validate_error_is_one_of`, race utilities, all composites included).

Orchestrator spot-check: all 9 files present, `py_compile` OK, `import test_helpers.fixtures` OK; constants.py carries PRD-verbatim literals with section citations in comments (CLOCK_START_ISO, MIN_STATE_SLOTS=1, RENEWAL_MIN_GPA=2.5). Note: Step 5 was split into 5a/5b per known output-cap failure mode on 63-instance suites.

## Step 5b: Generate test_suite (Phase B of split Step 5) — 2026-10-01T17:05:00.000Z

Everything verifies. The suite is complete and clean.

### Files generated (all under `test_suite/`)

| File | Lines | Tests |
|---|---|---|
| conftest.py | 39 | — |
| test_01_cycles_and_apportionment.py | 199 | 5 |
| test_02_entries_and_scoring.py | 316 | 15 |
| test_03_selection.py | 165 | 6 |
| test_04_finalist_applications.py | 221 | 9 |
| test_05_matching_and_pools.py | 196 | 8 |
| test_06_award_lifecycle.py | 430 | 12 |
| test_07_cascades.py | 251 | 7 |
| test_08_notifications.py | 96 | 3 |
| test_09_agreements.py | 257 | 7 |
| test_10_rbac_and_clock.py | 168 | 7 |
| **total** | **2338** | **79** |

### Collection audit
`python3 -m pytest test_suite --collect-only -q` → **exit 0, 79 tests collected** (34 difficulty-queue + 45 corner-queue).

### AST tag audit (real `ast` parse, diffed both directions against both yamls)
- 62 unique tags, all resolving to real instances; every difficulty instance has ≥2 tests; every corner non-stub has exactly 1; every tag is the docstring's final line, exactly one per test.
- Tags pointing at non-existent instances: **none**. Stub instances (`excluded_because:`) tagged: **none** (all 4 stubs verified untranslated).
- Missing: exactly 1 — the deliberate skip below.

### Skipped instance (PRD-first filter, worked-example arithmetic rule)
- **`Difficulty/transitive_cascade/renewal_rejection_cascade_lapses_and_repools`** — its pre-computed values contradict the PRD disbursement formula. The instance sets a college award of 100000/year × 2 years × 2 terms/year (amount 200000 over 4 terms) and asserts "term1 RELEASED (100000)" and `pool_paid_cents == 100000`. PRD §3.8 pins `round_half_up(amount_cents/terms_total)` = `round_half_up(200000/4)` = **50000** per term, so a single release leaves `pool_paid_cents == 50000`, not 100000. Recomputed in Python and confirmed; per the worked-example rule the PRD formula wins and the instance was skipped. (The lapse-cascade mechanics it exercised are partially covered by `corporate_decline_cascade_reoffers_waitlist`, which survives.)

### Recipe repairs applied (assertions unchanged, setup made PRD-legal)
- **`publicity_gap_minimum_separation`**: the recipe as written advances the clock to 2028-03-02 while the award is still OFFERED — the §2.5 sweep (acceptance deadline 2026-10-01) would expire it and supersede the very notifications under test. Repaired by accepting the award at the default clock before advancing; all asserted outcomes (embargo satisfied, 2-day publicity gap, inclusive boundary at 2028-03-04T10:00:00Z) are unchanged.
- **`renewal_on_single_payment_rejected`**: a single-payment award can never rest in ENROLLED (its only release completes it), so at an ACCEPTED award both priority-6 gates (`ERR_NOT_RENEWABLE`, `ERR_INVALID_STATE`) are simultaneously applicable and PRD §2.8 gives no intra-category order. Per the sanctioned error-precedence pattern, the test uses `validate_error_is_one_of([ERR_NOT_RENEWABLE, ERR_INVALID_STATE])` instead of the instance's single-id assertion.

### Verification performed
- All pre-computed worked examples (provisional 5/3/3 vs final 5/2/3 summing 11/10; largest-remainder 4/4/1/1 with the MIN_STATE_SLOTS guarantee; the [41668×5, 41665] split of 250005; all six 180-day term dates; acceptance deadlines 2026-10-01/2026-11-01; every selection-index literal) recomputed in Python and confirmed against the PRD formulas before encoding.
- Every test docstring carries a verbatim PRD citation: a strict re-check (whitespace-collapsed, backticks preserved, ≥4-word fragments) passes all 79 tests with zero failures.
- Frozen `test_helpers/` untouched; tests import from it throughout, use entity-backed header builders (`make_student_headers(student["id"])` etc.), and advance time only via the `advance_clock` helper.

Orchestrator spot-check: independent `pytest --collect-only -q` → 79 tests collected, exit 0; 10 test files + conftest present; 62 unique `Design:` tags via grep — all matches the subagent report.

## Step 6: Generate implementation — 2026-10-01T18:20:00.000Z

Implementation complete and verified. Report follows.

### File list (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `constants.py` | 86 | every named constant (SECTION_WEIGHT=2, SECTION_MIN/MAX=8/38, MIN_STATE_SLOTS=1, TERM_INTERVAL_DAYS=180, ACCEPTANCE_WINDOW_DAYS=30, PUBLICITY_GAP_DAYS=2, RENEWAL_MIN_GPA=2.5, CONFIRMING_MIN/MAX=48/228, GPA bounds, pagination 10/1/100/0, CLOCK_START_ISO="2026-09-01T00:00:00Z", role names, notification sequence map, LIVE_RECIPIENT_STATES, all enum members) |
| `store.py` | 109 | in-memory dicts (13 tables, empty at boot, zero seeding), logical clock, UUID/`_seq`/wall-clock helpers, ISO-8601 formatters (audit ts = 3 fractional digits; logical instants = seconds, `Z`) |
| `errors.py` | 50 | ApiError + full 32-entry error catalogue (id -> HTTP status) |
| `helpers.py` | 218 | envelope builders, auth (`X-User-Role`/`X-User-ID`, 401 before everything incl. unknown paths), role decorator, pagination validation, field-shape validators |
| `serializers.py` | 249 | exact per-entity field sets; School is the no-`version`/no-`updated_at` exception; `quota_raw` Decimal→float |
| `services.py` | 674 | apportionment (4dp round-half-up quota; provisional round-half-up; largest-remainder final with MIN_STATE_SLOTS + population-then-state_code ties), threshold selection (inclusive k-th), waterfall (national → corporate by created_at → college by created_at; selector si DESC, confirming DESC, submitted_at ASC), waitlist promotion on EXHAUSTED→ACTIVE flips, pool recompute (reservation + cash ledgers), decline/expiry/lapse cascades, disbursement schedule (round non-final terms half-up, final term absorbs remainder, 180-day terms, year≥2 HELD), renewal decisions, clock sweep, cycle-completion bubble-up |
| `routes_cycles.py` | 197 | 8 cycle endpoints incl. state-allocations (state_code ASC) |
| `routes_registry.py` | 134 | schools/students/sponsors/colleges |
| `routes_entries.py` | 134 | entries + scoring |
| `routes_applications.py` | 209 | applications + endorse/submit/review (OCC) |
| `routes_agreements.py` | 224 | agreement create/read/list/amend (OCC, half-open overlap excluding superseded, overlap before pool floor) |
| `routes_awards.py` | 202 | awards read/accept/decline, disbursement list/release, renewal create/list/decision |
| `routes_notifications.py` | 80 | per-student list (sequence ASC) + release gates |
| `routes_clock.py` | 31 | `POST /api/_clock/set_current_utc` (monotonic, sweep, completion re-eval) |
| `app.py` | 65 | blueprint registration, envelope error handlers (400/404/405/500), `0.0.0.0:$PORT` (default 10000) |
| `start.sh` | 9 | guarded install (`python3 -c "import flask"` check), `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=2.2 |

### Verification results

- **py_compile**: all 15 .py files compile clean. **Fresh import**: OK; exactly **41 `/api/` route rules** registered (matches the PRD endpoint table).
- **Constants cross-check**: 33 distinct `C.*` names referenced, all defined (0 undefined). 3 defined-but-unreferenced (documentary: AWARD_CATEGORIES, NOTICE_TYPES, QUOTA_DECIMALS — the last inlined as `Decimal("0.0001")` in services). All values re-checked against PRD/SCAFFOLD literals.
- **Smoke tests** (3 scenarios, each on a fresh server via `bash start.sh` on a dynamic port; servers killed by exact PID afterwards):
  - **Scenario 1** (port 51475→57925): auth 401/404 ordering, school/student/cycle create, open→entry→duplicate-409→score-posture-409→close (quotas 1.3333/0.6667, provisional 1/1)→unscored-guard-409→scoring (si=180/120)→selection (selected_total=1, threshold 180, NY null)→not-semifinalist-409→apply/endorse (mismatch-403, re-endorse-409)/submit (incomplete-422)/review (stale-412, CONFIRM)→publish→matching (national 1)→already-run-409→accept→disbursement release→award COMPLETED→**cycle AWARDS_COMPLETED via bubble-up**→clock regression 422→notification sequencing (embargo 422, sequence 409, releases, gap satisfied at 2027-01-20). Acceptance deadline verified = offered + 30d exactly.
  - **Scenario 2** (port 36219): corporate waterfall with capacity 1 → top-ranked grant, agreement EXHAUSTED (committed 50000, reserved 0); decline → pool release → EXHAUSTED→ACTIVE → **waitlist promotion granted the runner-up**, pool re-committed, EXHAUSTED again; declined student's seq-3/4 notifications SUPERSEDED (release → 409); **publicity gap** fired (`ERR_PUBLICITY_WINDOW_TOO_EARLY` at offer+0/+1d, releasable at +2d); clock at deadline = no sweep, past deadline = sweep to EXPIRED with `expired_offer_ids`; cycle completed, agreement CLOSED; amend: stale→412, CLOSED→409, positive amend→201 with `supersedes_agreement_id`, old→SUPERSEDED v2; window overlap 409 + half-open adjacency 201.
  - **Scenario 3** (port 52481): college renewable award (amount 10001×3y=30003, 6 terms): per-term round-half-up **5001×5 + final-term absorption 4998**, sum exact; years 1,1,2,2,3,3; year-1 SCHEDULED, rest HELD; 180-day schedule dates verified programmatically; NOT_DUE 422 / HELD 409 / release → ENROLLED + PARTIALLY_DISBURSED with committed 25002/paid 5001/**reserved unchanged 69997**; renewal ownership 403; sequencing (`ERR_RENEWAL_ALREADY_EXISTS` for dup year and out-of-order year); APPROVE → RENEWED + year-2 unhold; weak-GPA APPROVE → 422 CRITERIA_UNMET; REJECT → LAPSED, terms CANCELLED, pool released, college ACTIVE again, cycle AWARDS_COMPLETED; institutions not closed.

### Ambiguities resolved (Step 7/8 audit surface)

1. **run-semifinalist-selection in wrong posture** → `ERR_INVALID_STATE` (not listed in any validation row's applies_to; chose by analogy with open/close-entries, which PRD §3.1 explicitly maps to ERR_INVALID_STATE, whereas publish/matching are explicitly ERR_CYCLE_POSTURE_INVALID).
2. **Ownership (priority 3) vs body-ref existence (priority 4)** when the owned entity is body-referenced (finalist-application create) or a path id: the entity is resolved first (400/404), then ownership 403 — ownership is unevaluable without the entity. Pure string-compare ownership (entries create, sponsor-path agreements, student-path GETs) runs before existence as the priority table dictates.
3. **GET-endpoint ownership** (scaffold's priority-3 applies_to lists only POSTs; PRD §2.1 says Student ownership applies to "any resource that references a Student"): enforced for Student on single-resource GETs (`students/{id}`, `students/{id}/notifications`, `entries/{id}`, `finalist-applications/{id}`, `awards/{id}`, award sub-lists) and for SponsorAdmin on `GET /api/sponsor-agreements/{id}`; not enforced on list endpoints or for CollegeAdmin GETs (PRD's college sentence is renewal-scoped).
4. **Notification sequence gate is literal**: ALL lower-sequence notifications of the same student (including SUPERSEDED ones, which can never become RELEASED) must be RELEASED. A superseded seq-3 permanently blocks a re-promoted student's seq-4 — the PRD prose is unconditional.
5. **`pool_total_cents >= award_amount_cents` enforced on amend too** (merged payload must satisfy the entity invariant), in addition to the PRD's explicit `pool >= committed + paid` fiscal floor.
6. **Missing `expected_*_version`** on the two OCC endpoints → 400 ERR_INVALID_REQUEST (PRD §2.7 "requires the request to carry" it), checked after the OCC-mismatch/state/business gates (field-shape is priority 10).
7. **Promotion scope for college pools** (institutions span cycles): the candidate pool is the cycle of the award whose release freed the capacity.
8. **Degenerate apportionment inputs** (all-zero populations, or the mathematically possible R<0 the scaffold claims unreachable): quota_raw=0 when POP=0; a defensive trim pass keeps slots_final summing to T. Unreachable under the creation invariant (populated states ≤ T).
9. **k=0 threshold** (slots_final=0 with candidates present, unaddressed by spec): threshold null, nobody selected.
10. **Version bump granularity**: one `version += 1` per API action / cascade event per affected entity (e.g., a disbursement release that flips both award dimensions bumps the award once); cascaded children each get their own bump.

Orchestrator spot-check: all 15 files present, `py_compile` clean, fresh import registers exactly 41 `/api/` routes; zero references to `test_helpers`/`test_suite` inside implementation/ (ISOLATION RULE respected); `start.sh` is a foreground launcher with guarded pip install and `exec python3 app.py`; Step 6→7 hand-off literal grep shows impl and test_helpers constants identical (SECTION_WEIGHT=2, MIN_STATE_SLOTS=1, TERM_INTERVAL_DAYS=180, ACCEPTANCE_WINDOW_DAYS=30, PUBLICITY_GAP_DAYS=2, RENEWAL_MIN_GPA=2.5, CLOCK_START_ISO=2026-09-01T00:00:00Z) — no drift.

## Step 7: Run tests and iterate — 2026-10-01T19:05:00.000Z

Clean sweep: all 8 rounds pass 79/79, with results.1..8.json left in place in workspace/implementation/.

### Summary

- **Iterations run**: 2 (initial sweep → 1 deterministic failure → fix → clean 8-round sweep, 79/79 in every round).

- **Tests deleted**: none.

- **Fixes applied to `test_suite/`**: 1
  - `test_suite/test_07_cascades.py :: test_waitlist_empty_pool_stays_active_noop` (design tag: Corner/cross_cutting_layers/waitlist_empty_pool_stays_active_noop) — the scenario asserted `agreement.status == "ACTIVE"` (PRD §3.7 verbatim: "an empty candidate set is a no-op and the pool simply stays `ACTIVE`") but its single-award setup made the §3.8 completion bubble-up fire on the decline ("After every award recipient-status change... no award of the cycle remains live and no disbursement remains SCHEDULED or HELD... every ACTIVE or EXHAUSTED SponsorAgreement flips to CLOSED"), so PRD read as a whole uniquely determines CLOSED in that scenario. Fixed the *setup* (not the assertion): added a second student who takes the cycle's one national slot (ranked SI 224 > the corporate student's SI 220, corporate-ineligible via default `employee_children_only`), so a live OFFERED national award blocks the bubble-up and the §3.7 no-op (`ACTIVE`, committed 0, available 250000, award set unchanged by the decline) is observable. All original assertions preserved and strengthened (id-set equality before/after decline; national award untouched).

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`**: none — the implementation's decline cascade (`release_cascade` → `_release_pool_capacity` → `check_all_cycles` in `workspace/implementation/services.py`) was already PRD-faithful on both §3.7 and §3.8.

- **Sibling unasserted paths** (test-side fix was the only fix): the original scenario shape — declining the cycle's last live award with an empty waitlist, so the §3.8 bubble-up completes the cycle and flips the agreement ACTIVE → CLOSED — is no longer exercised by this test. The CLOSED flip itself remains covered via the full-disbursement path in `test_06_award_lifecycle.py` (line ~429), but the decline-triggered variant of the bubble-up is unasserted; Step 8 may want to note that gap.

Orchestrator verification (independent): all 8 `results.${i}.json` files exist in `workspace/implementation/` and each reports passed=79 total=79 failed=0; `find . -name "*.py" -newer results.1.json` (excluding `__pycache__`) is empty — no implementation source was touched after the clean sweep.

## Step 8: Finalize PRD — 2026-10-01T19:20:00.000Z

Done. **Zero edits** — `PRD_FINALIZED.md` is byte-identical to `PRD.md` (verified with `diff -q` → IDENTICAL).

### Line counts / delta
- `PRD.md`: 283 lines; `PRD_FINALIZED.md`: 283 lines; delta 0 lines, 0.0%.

### Evaluation of each `<step_7_diff>` item

- **Tests deleted: none** — nothing to trace.
- **`test_suite/` fix (1): `test_07_cascades.py::test_waitlist_empty_pool_stays_active_noop`** — this was a *fixture/setup* correction, not a PRD silence or impl mismatch. Step 7 itself concluded "PRD read as a whole uniquely determines CLOSED in that scenario": §3.7's "empty candidate set is a no-op and the pool simply stays `ACTIVE`" governs only the promotion step, while §3.8's completion bubble-up is a separate, later re-evaluation. No impl behavior was pinned that the PRD leaves open, so no edit traces to this fix.
- **`test_helpers/` fixes: none** — nothing to trace.
- **`implementation/` fixes: none** — with zero impl changes, there is no impl-chosen behavior the PRD fails to determine.
- **Sibling unasserted path (decline-triggered bubble-up, agreement `ACTIVE` → `CLOSED`)** — already covered by unconditional PRD prose, so per the method ("unconditional wording → no edit warranted") no insert was made. Verbatim coverage:
  - §3.8 (PRD line 188): "**After every award recipient-status change**, every disbursement status change, and every clock sweep, the completion bubble-up re-evaluates: when the cycle's `matching_run` is true, no award of the cycle remains in `OFFERED`, `ACCEPTED`, `ENROLLED`, or `RENEWED`, and no disbursement of the cycle's awards remains `SCHEDULED` or `HELD`, the cycle moves `FINALISTS_SELECTED` → `AWARDS_COMPLETED`, **every `ACTIVE` or `EXHAUSTED` `SponsorAgreement` of the cycle flips to `CLOSED`**" — and §3.8 itself defines decline as an award recipient-status change ("decline moves the recipient `OFFERED` → `DECLINED`", line 180).
  - §3.6 (line 162) reinforces: "Agreements — but never institutions — also reach a terminal `CLOSED` when their cycle completes, whether from `ACTIVE` or `EXHAUSTED`."

### Pre-edit search log (for the evaluated-but-rejected edit on the bubble-up subject)
- **(a) Subject**: completion bubble-up triggers and the agreement `ACTIVE`/`EXHAUSTED` → `CLOSED` flip.
- **(b) Impl paths enumerated**: `services.py:536-544` `release_cascade` (sets recipient status, supersedes notifications, `_release_pool_capacity`, then unconditionally `check_all_cycles()`); `services.py:473-490` `maybe_complete_cycle` (gates on `matching_run` + `FINALISTS_SELECTED`, no live award, no `SCHEDULED`/`HELD` disbursement; flips all cycle agreements `ACTIVE`/`EXHAUSTED` → `CLOSED`); `services.py:493-495` `check_all_cycles`; callers `services.py:544` (decline/expiry), `:553` (accept), `:614`, `:628` (disbursement release / renewal-lapse paths), `:672` (clock sweep); decline endpoint `routes_awards.py:85-91` → `release_cascade(rec, "DECLINED")`. All paths route through the same unconditional `check_all_cycles()`, exactly matching §3.8's "after every award recipient-status change" wording.
- **(c) Wording adjustment**: none — no edit committed; existing unconditional wording already describes every enumerated path, so any insert would have been a manufactured edit with NO-NEW-MISMATCH risk and no Step 7 fix to trace to.

Files: `workspace/PRD_FINALIZED.md` (created, identical to `PRD.md`).

Orchestrator verification (independent): `workspace/PRD_FINALIZED.md` exists, 58147 bytes, `diff -q PRD.md PRD_FINALIZED.md` → identical. Step 8 ran because the mechanical skip condition (0 test_suite fixes) was not met; the zero-edit outcome is the correct result given Step 7's only fix was a PRD-determined setup correction.

## Step 9: Complete PRD — 2026-10-01T19:45:00.000Z

Done. PRD_COMPLETED.md is written and verified. Final summary:

### File deltas
- Source: `workspace/PRD_FINALIZED.md` — 283 lines, 58,147 chars
- Produced: `workspace/PRD_COMPLETED.md` — 283 lines, 62,616 chars (+4,469 chars; 20 lines revised in place, zero lines added/removed)
- No other file touched: PRD.md/PRD_FINALIZED.md retain original mtimes; nothing under implementation/, test_helpers/, test_suite/ is newer than PRD_FINALIZED.md.

### Counts
- Ambiguity-pins: 19
- Mismatch-revisions: 1 (ownership-vs-existence ordering in §2.8 item 3)

### Changes (one per bullet)
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected `ERR_INVALID_REQUEST`; `has_more` defined as `offset + returned rows < total_count`; sort ties fall to `created_at` then creation order — implementation/helpers.py:167-199
- §2.4 — insert — ambiguity — one `version` increment per resource per action/cascade event regardless of field count — implementation/store.py:106-109
- §2.5 — insert — ambiguity — logical-clock-stamped instants serialize as ISO 8601 UTC `Z` at seconds precision (3 fractional digits when sub-second); multi-expiry sweep processes in `created_at` ascending — implementation/store.py:79-84, services.py:662-669
- §2.8 item 3 — revise — mismatch — pure identifier-compare ownership (path id, body `student_id`) runs at priority 3 before existence; ownership needing a persisted resource's field runs right after that resource resolves (404 then 403); ownership covers singles + nested single-parent lists only, roster lists are role-only, `CollegeAdmin` reads unchecked — implementation/routes_entries.py:32-38 vs 83-87, routes_applications.py:46-54, routes_awards.py:43-44, routes_agreements.py:151-153, routes_notifications.py:21-24
- §3.1 — insert — ambiguity — populated-state-count > `total_semifinalist_slots` is `ERR_INVALID_REQUEST` — implementation/routes_cycles.py:81-83
- §3.1 — insert — ambiguity — run-semifinalist-selection from wrong posture is `ERR_INVALID_STATE` (fires before the unscored-entries refusal); publish-finalists from wrong posture is `ERR_CYCLE_POSTURE_INVALID` — implementation/routes_cycles.py:162-163, 175-176
- §3.2 — insert — ambiguity — zero summed population → every `quota_raw` 0.0000; `quota_raw` serializes as a JSON number — implementation/services.py:75-79, serializers.py:19-22
- §3.2 — insert — ambiguity — remainder seats dealt cyclically through the tie-broken order; if bases alone exceed T, excess trimmed from smallest fractional remainder (ties: smaller population, then smaller state_code), never below zero — implementation/services.py:107-128
- §3.3 — insert — ambiguity — duplicate `school_code` is `ERR_INVALID_REQUEST` — implementation/routes_registry.py:39-41
- §3.3 — insert — ambiguity — only a well-formed `exam_year_of_hs` participates in eligibility; missing/non-enum is a field-shape 400, never `ERR_ENTRY_INELIGIBLE` — implementation/routes_entries.py:52-61
- §3.4 — revise — ambiguity — candidate-ranking residual ties fall to creation order; k=0 (zero candidates or zero `slots_final`) → null threshold, all candidates `NOT_SELECTED` — implementation/services.py:148-170
- §3.5 — insert — ambiguity — unrecognized review `decision` is `ERR_INVALID_REQUEST`, evaluated once the application is known `UNDER_REVIEW` — implementation/routes_applications.py:184-187
- §3.6 — insert — ambiguity — duplicate `sponsor_code` is `ERR_INVALID_REQUEST`; agreement creation-bound violations are `ERR_INVALID_REQUEST` — implementation/routes_registry.py:141-143, routes_agreements.py:56-74
- §3.6 — revise — ambiguity — overlap check excludes the amended agreement and every already-`SUPERSEDED` agreement; `CLOSED` agreements still participate — implementation/routes_agreements.py:41-53
- §3.6 — insert — ambiguity — amendment re-validates the merged payload against creation rules incl. `pool_total_cents >= award_amount_cents`, as `ERR_INVALID_REQUEST` at field-shape priority — implementation/routes_agreements.py:64-65, 215
- §3.6 — insert — ambiguity — duplicate `college_code` and undersized college pool are `ERR_INVALID_REQUEST` — implementation/routes_registry.py:172-181
- §3.7 — insert — ambiguity — selector residual ties fall to application creation order — implementation/services.py:277-286
- §3.7 — insert — ambiguity — promotion candidate cycle = the cycle of the award whose release freed capacity (institutional pools span cycles; only that cycle competes) — implementation/services.py:517-527
- §3.8 — insert — ambiguity — unrecognized renewal `decision` is `ERR_INVALID_REQUEST`, evaluated once the verification is known `SUBMITTED` — implementation/routes_awards.py:191-196
- §3.9 — insert — ambiguity — embargo check fires before the publicity-gap check; same-sequence notifications list in `created_at` ascending — implementation/routes_notifications.py:59-76, 33

### The 10 known interpretation sites
1. Selection wrong posture → `ERR_INVALID_STATE` — **pinned** (§3.1, incl. posture-before-unscored ordering; publish-finalists' `ERR_CYCLE_POSTURE_INVALID` pinned alongside).
2. Ownership-vs-existence ordering — **mismatch-revised** (§2.8 item 3 now pins both regimes exactly as impl behaves).
3. GET-endpoint ownership scope — **pinned** (same §2.8 item 3 revision).
4. Sequence gate includes SUPERSEDED — **already-covered**: §3.9 unconditional prose matches routes_notifications.py:49-58. No edit.
5. Amend enforces `pool_total_cents >= award_amount_cents` on merged payload — **pinned** (§3.6 merged-payload re-validation insert).
6. Missing `expected_*_version` → 400 after business gates — **already-covered**: §2.7 + §2.8 item 10. No edit.
7. College-pool promotion scope — **pinned** (§3.7).
8. Degenerate apportionment — **pinned** (§3.2).
9. `slots_final` = 0 with candidates — **pinned** (§3.4).
10. Version bump granularity — **pinned** (§2.4).

Everything else walked (envelope/meta field names, per-entity serializer sets incl. the School exception, `expired_offer_ids` response field, 401-before-404 ordering, OCC stale at priority 5, endorse self-transition, disbursement rounding order, pool ledger formulas, exhaustion/recovery loops, completion bubble-up, bucket grant math, renewal criteria and lapse cascade, all endpoint role sets, all error HTTP codes) was already uniquely determined by PRD prose and matches the implementation as-is.

Orchestrator verification (independent): `workspace/PRD_COMPLETED.md` exists (283 lines) and `diff -q` vs PRD_FINALIZED.md shows real differences (not a silent no-op); `find implementation -name "*.py" -newer results.1.json` (excluding `__pycache__`) is empty — implementation untouched after the clean sweep, so no sweep re-run is required; all 8 `results.${i}.json` remain in place, each still passed=79/79.
