# Worklog — task_3496_rail_rate_complaint_adjudication_transaction_review

## Step 1: Create Task Directory — 2026-10-02T18:09:24.000Z

Task directory was pre-allocated by the caller at tasks/task_3496_rail_rate_complaint_adjudication_transaction_review/ with workspace/ inside; verified it exists and is empty except workspace/. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-02T19:05:00.000Z (self-recorded by scaffold subagent; orchestrator's verbatim summary entry follows below)

Generated SCAFFOLD.yaml (10 entities, 8 state machines, 6 calculations, 17 ordered validation rows, 40 endpoints, 47 errors, 4 roles, 1 OCC rule), SCAFFOLD_DIFFICULTY_DESIGN.yaml (9 rules x 2 = 18 instances), SCAFFOLD_CORNER_DESIGN.yaml (9 sections, 49 active instances + 8 excluded_because stubs). api_prefix=/stb; logical clock default 2026-09-01T00:00:00Z. All fixture literals (ratios, ROI bps, award rounding, dates, mileage) pre-computed with Python. scaffold_lint.py: VERDICT clean lint (416 calls scanned, 0 violations; all FKs reverse-reachable). One structural replay bug found and fixed during self-check: ESO duration raised 30->60 days so the merger service hold (45-day comment period) is reachable while an ESO is ACTIVE.

## Step 2: Generate Scaffold — 2026-10-02T19:20:17.000Z

Scaffold generation complete. All three artifacts are written, lint-clean, and cross-consistent.

**Output files**
- `/home/ubuntu/github/CodingPRD/tasks/task_3496_rail_rate_complaint_adjudication_transaction_review/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3496_rail_rate_complaint_adjudication_transaction_review/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3496_rail_rate_complaint_adjudication_transaction_review/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Summary counts**
- Entities: 10 (Carrier, RevenueAdequacyFinding, RateComplaint, EvidenceSubmission, ServiceComplaint, EmergencyServiceOrder, MergerApplication, ServiceAssurancePlan, AbandonmentApplication, ReciprocalSwitchingPetition)
- State machines: 8 (RateComplaint has a DECIDED→REOPENED→EVIDENTIARY_PHASE cycle; MergerApplication has a 3-way branching fork with divergent side effects)
- Calculations: 6 (alleged/adjudicated R/VC ratio variants, current-year vs 5-year-average revenue-adequacy ROI, nested min/max prescription with revenue-adequacy floor, per-shipment-then-sum reparation rounding, weighted public-interest score)
- Endpoints: 40 (exactly at the cap), including `POST /stb/_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z`
- Error catalog: 47 errors, precedence-ordered across 17 validation priorities
- Roles: 4 (PlatformAdmin, BoardAdjudicator, Shipper — opaque party id; CarrierOperator — entity_backed:Carrier)
- Difficulty-design instances: 18 (9 rules × 2, all differentiation clauses honored)
- Corner-design instances: 57 (49 active + 8 `excluded_because` stubs, covering all 9 taxonomy sections)
- api_prefix: `/stb`
- Concurrency: 1 OCC rule (`merger-amend-stale-version`, 412 via `expected_merger_application_version`)

**Key verification results**
- `scaffold_lint.py`: `VERDICT: clean lint` — 416 design calls scanned, 0 violations, all 12 FKs reverse-reachable.
- Custom audit passed: placeholder closure, grounds resolution, unique instance names, enum reachability, error-referential completeness (every error is referenced), no forbidden race vocabulary, pinned literals (`1.8000`, `$1M/$4M` track caps, 1140 bps cost of capital, 45/60/180/84-day windows, 30-mile distance, 4 interchange slots) identical across all three files.
- Replay audit caught and fixed one structural bug: the original 30-day ESO duration made the merger service-hold cascade unreachable (45-day comment period always outlived the ESO); ESO duration is now pinned at 60 days everywhere.
- All formula-derived assert literals were pre-computed in Python (e.g., per-shipment rounding 128817 vs sum-then-round 128816; five-year ROI 1180 vs current-year 1000; floor-binding prescription 11550 vs 11200).

**Orchestrator post-verification**: all three files parse as YAML; SCAFFOLD.yaml has no design keys; api_prefix `/stb` present in all three (168 + 258 grep hits in design files); 40 endpoints confirmed; domain entities (RateComplaint, MergerApplication) present in all three files — no foreign-domain contamination.

## Step 3: Copy Shared Files — 2026-10-02T19:20:08.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-02T19:40:55.000Z

All checks pass. The PRD is complete and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3496_rail_rate_complaint_adjudication_transaction_review/workspace/PRD.md` — 329 lines.

**Section list**: §1 Introduction (2 paragraphs); §2 with ten subsections (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Identity/Timestamps/Versioning, 2.5 Logical Clock & Automatic Expiry, 2.6 Validation Precedence [all 17 priorities as an explicit first-failure-wins ladder], 2.7 Precision & Rounding, 2.8 OCC, 2.9 Derived Carrier Condition Registers, 2.10 Nested Retrieval); §3 with eight workflow subsections (carrier registration/adequacy, rate filing & market dominance, evidentiary proceedings & merits, reparations ledger, service complaints & ESOs, merger review, abandonment & trail use, reciprocal switching); §4 endpoint table (4 columns); §5 error catalogue (2 columns).

**Coverage self-audit (all programmatic, YAML-parsed against SCAFFOLD.yaml)**:
- Contract 1 Field-Name Coverage: 72/72 entity fields, 53/53 endpoint inputs, 3/3 query params present in backticks — **PASS**
- Contract 2 Rule Coverage: validations-with-priority 17/17 expressed as an ordered ladder; OCC 1/1 (endpoint + `expected_merger_application_version` + `ERR_STALE_VERSION`/412 all named); transitions 31/31 (both branches of every fork, incl. consummate-from-GRANTED vs consummate-from-TRAIL_PENDING at equal density); calculations 6/6 (both R/VC variants, both ROI variants, pinned round-per-shipment-then-sum, nested min/max prescription with cross-entity adequacy floor); validation conditions all paired to error ids in §2/§3 prose; all endpoint side_effects covered — **PASS**
- Contract 3 §3 Path Purity: 467 backticked tokens scanned, 0 path-like, 0 bare-method, 0 method+path — **PASS**
- Errors: 47/47 in §2/§3 narrative and in §5; endpoints 40/40 in §4; all enum values, roles, and pinned constants (1.8000/1.7999, 100000000/400000000, 1140 bps, 45/60/180/84 days, 30 miles, 4 slots, 1.0000/1.1000, 60.00/45.00, `2026-09-01T00:00:00Z`) verbatim. §2.2 block byte-identical to `section-2.2-response-structure.md`. No pseudocode operators or fuzzy words.

**Ambiguities / self-contradictions found in the scaffold (pre-flag for the test-fixing step)**:
1. **`ERR_REVENUE_ADEQUACY_FINDING_REQUIRED` scope on DISMISSED** — validations priority 7 applies to the decide endpoint with no outcome qualifier (and priority 8 is explicitly UPHELD/REJECTED-only, implying 7 is not), but the `EVIDENTIARY_PHASE → DISMISSED` state-machine transition omits the finding precondition. PRD resolves in favor of the validations table: the finding is required for all three decide outcomes.
2. **Petition-grant check ordering conflict** — the state machine lists escalation (`ERR_PETITION_EVIDENCE_NOT_ESCALATED`) before the 84-day window (`ERR_SERVICE_FAILURE_WINDOW_EXPIRED`); the validations priority table orders window (p14) before escalation (p15). PRD follows the validations table ("first failure wins"): carrier mismatch → window → escalation → capacity.
3. **Merger-decide ordering conflict (same class)** — state machine lists the `comment_close_at` temporal check before the score-band check; the validations table puts score consistency (p12) ahead of temporal gates (p15). PRD follows the validations ladder globally.
4. **Row-level vs per-error HTTP status** — validation rows 16/17 carry a single status (409/402) that contradicts member errors' catalog statuses (`ERR_FACILITY_BEYOND_INTERCHANGE_DISTANCE` 422; `ERR_INVALID_REQUEST` 400; `ERR_AWARD_HAS_PAYMENTS` 409). PRD uses the per-error catalog statuses.
5. **Amend semantics for omitted optional fields** — scaffold says score is "recomputed from the amended scores"; PRD makes the faithful reading explicit: unsupplied fields retain current values.
6. **`shipments` omitted vs empty** — endpoint marks it optional, calculation pins "empty array → award 0"; PRD states omitted-or-empty yields 0.

**Orchestrator post-verification**: PRD.md = 328 lines; 97 ERR_ token hits; pinned constants all present (1.8000 ×4, 1140 ×1, 2026-09-01T00:00:00Z ×3, /stb/_clock/set_current_utc ×2 — correctly INSIDE the /stb prefix, 100000000 ×2, 400000000 ×2, expected_merger_application_version ×2, ERR_STALE_VERSION ×3).

## Step 5: Generate Unit Tests — 2026-10-02T20:14:39.000Z

Generation complete. Summary:

## Files written

**test_helpers/** (9 files, frozen before Stage 2):
- `types.py` — 19 status/role enums + 10 entity TypedDicts (all entities carry `common_fields: true` → full identity block)
- `constants.py` — PRD-verbatim values only: R/VC threshold 1.8000, cost of capital 1140 bps, track caps 100000000/400000000, floors 1.0000/1.1000, windows 45/60/180/84 days, 30 miles, 4 slots, clock default `2026-09-01T00:00:00Z`, plus the standard finding figures (2021–2025 ADEQUATE history, single-year 2025 INADEQUATE)
- `api_errors.py` — all 47 error IDs with §5 HTTP statuses (incl. 402 overpayment, 412 stale version), registered via `set_error_http_status_map`
- `api_client.py` — `ApiClient(GenericApiClient)` with all 40 §4 endpoints, all under `/stb`
- `test_users.py` — opaque admin/board shared constants; `make_shipper_headers(party_id)` and `make_carrier_operator_headers(carrier_id)` per-instance builders (CarrierOperator is `entity_backed:Carrier`)
- `factories.py`, `assertions.py` (two timestamp families: 3-fractional-digit identity block vs clock-verbatim domain timestamps; ledger + mileage invariants), `fixtures.py` (composite setups: carrier+findings, evidentiary complaint, decided-UPHELD, merger pair/plan, escalated service complaint, petition helpers)
- `__init__.py` barrel

**test_suite/**: `conftest.py` + 10 test files (test_01 … test_10), one test per instance.

## Coverage

- **Queue A (Difficulty): 18/18 emitted** — exactly 2 per rule across all 9 rules (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- **Queue B (Corner): 49/49 emitted** — entities 11, state_machines 9, calculations 3, validations 9, endpoints 2, errors 6, rbac 4, cross_cutting_layers 4, consistency_model 1. The 8 `excluded_because` stubs were not translated (their difficulty instances own the assertions).
- **Skipped instances: none.** Every instance passed the PRD-first two-condition filter.

## Audit results

- **AST tag audit**: 67 test functions, each with exactly one `Design:` docstring line; 0 missing, 0 unresolved, 0 untagged/dual-tagged.
- **Verbatim citation audit**: 101 quoted spans across all docstrings; every one survives whitespace-normalized literal grep of `workspace/PRD.md` (7 initial failures — ellipses, a fabricated table-row citation, trailing periods inside mid-sentence quotes — were fixed and re-verified).
- **py_compile**: all 19 files pass.
- **pytest --collect-only -q**: 67 tests collected, no import/collection errors.

Key fidelity decisions: create endpoints asserted at 201 via explicit `validate_success(resp, 201)`; petition status re-reads go through the carrier nested list view (no direct GET petition endpoint exists); clock-moving recipes advance the clock forward from the 2026-09-01 default rather than seeding past dates; the interchange-capacity tests rely on the operative PRD sentence "at most four overlapping granted switching windows" / "must be fewer than 4" (deliberately did not quote §3.8's loosely-worded "fourth overlapping granted window" clause).

**Orchestrator independent re-audit**: re-ran AST tag audit from YAML + test_suite — 67 functions, 67 tags, 0 untagged, 0 dual-tagged, 0 unresolved, 0 untranslated; `pytest --collect-only -q` collects 67 tests with no errors. Hand-back claims confirmed against source.

## Step 6: Generate Implementation — 2026-10-02T20:43:41.000Z

Done. Final summary below.

## Implementation complete — task_3496 (STB Rail Rate Complaint Adjudication)

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_3496_rail_rate_complaint_adjudication_transaction_review/workspace/implementation/`

### File list (20 files, ~2,100 lines)

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | Foreground launcher, guarded pip install, `exec python3 app.py`, `$PORT`/0.0.0.0 |
| requirements.txt | 1 | flask>=2.2 |
| app.py | 62 | App factory, blueprint registration, `before_request` lazy ESO-expiry sweep, ApiError→envelope handler |
| constants.py | 40 | All pinned values (1.8000, 1140 bps, caps 100000000/400000000, floors 1.0000/1.1000, 45/60/180/84 days, 30 miles, 4 slots, thresholds 60.00/45.00) |
| errors.py | 73 | `ApiError` + full 47-entry catalog |
| store.py | 67 | Empty in-memory dicts, logical clock (default 2026-09-01T00:00:00Z), dashed `str(uuid.uuid4())`, `touch()` version bump |
| timeutil.py | 59 | ISO parse + two rendering families (identity 3-frac; domain as-clock-reads) |
| envelope.py | 47 | `meta`/`response_type`/`data`, `req_…` ids, pagination fields in meta |
| auth.py / validate.py / pagination.py | 32/82/48 | Priority-1 headers+shape, priority-2 role, limit/offset (default 10, 1..100), created_at-ascending sort, status filter |
| derived.py | 107 | Mileage / revenue-status / standing / merger-hold / exposure recomputes (bump-on-change) + lazy ESO sweep |
| serializers.py | 181 | Per-entity views, internal `_…` keys never serialized |
| routes_clock.py | 29 | `POST /stb/_clock/set_current_utc` |
| routes_carriers.py | 190 | Carrier CRUD, 7 nested list views, revenue adequacy findings (ROI math) |
| routes_rates.py | 414 | Complaints, dominance determination, evidence, verify, decide (prescription + relief caps + per-shipment award rounding), reopen, reparation ledger |
| routes_service.py | 134 | Service complaints, escalate→ESO→PROBATION→hold cascade, resolve→LIFTED |
| routes_mergers.py | 231 | Merger create/amend (OCC)/decide, service assurance plans |
| routes_abandonment.py | 146 | Abandonment lifecycle, NITU windows, mileage ledger |
| routes_petitions.py | 145 | Switching petitions, 84-day freshness, half-open window slot capacity |

### Verification
- **`py_compile`**: all 19 .py files pass (COMPILE_OK).
- **Error audit**: catalog size 47; scripted check confirms every error_id has both a definition site (`errors.py`) and at least one call site. No KeyError→500 paths.
- **Fresh boot**: new process shows empty store (unknown carrier → 404; no seeding anywhere).

### Smoke-test transcript (dynamic port, exact PIDs killed after)
1. `POST /stb/carriers` → **201**, derived registers initialized, dashed UUID, `created_at` = `2026-09-01T00:00:00.000Z`
2. GET without headers → **400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`**; duplicate code → **409 `ERR_DUPLICATE_CARRIER_CODE`**; shipper mismatch → **403 `ERR_NOT_RESOURCE_OWNER`**
3. `POST /stb/_clock/set_current_utc` → **200** empty-object envelope
4. Complaint flow: create (ratio 2.0, track SIMPLIFIED_SAC) → dominance → EVIDENTIARY_PHASE; decide before finding → **409 `ERR_REVENUE_ADEQUACY_FINDING_REQUIRED`**; finding (1500 bps → ADEQUATE) → evidence verify (adjudicated 2.4) → decide UPHELD with fractional tons: **prescribed=2000, relief=80,000,000, award=25,000** (per-shipment round-then-sum: 16,200 + 8,800) → carrier exposure 25,000 → payment by wrong carrier → **403**; full payment by owner → PAID → auto-**CLOSED**, exposure 0
5. ESO cascade: escalate → ESO ACTIVE (`issued_at 2026-09-01T00:00:00Z`, `expires_at 2026-10-31T00:00:00Z` — domain format, no .000) → carrier PROBATION → merger hold true → decide APPROVED → **409 `ERR_MERGER_SERVICE_HOLD`**; resolve → LIFTED → hold cleared; clock past expiry on a second ESO → plain GET flips it EXPIRED, standing GOOD (lazy expiry confirmed)
6. Merger OCC: wrong version → **412 `ERR_STALE_VERSION`**; correct version → v2, score recomputed 80.0→81.5, comment window reset; decide before close → **409 `ERR_COMMENT_PERIOD_OPEN`**; decide exactly at close → **APPROVED**
7. Abandonment: GRANTED with NOT_SERVED → **422 `ERR_DECISION_INCONSISTENT_WITH_FINDING`**; consummate during NITU → **409 `ERR_TRAIL_USE_WINDOW_OPEN`**; convert exactly at `nitu_expires_at` → TRAIL_CONVERTED, mileage 32000→31980 active / 20 trail
8. Petitions: 31 miles → **422 `ERR_FACILITY_BEYOND_INTERCHANGE_DISTANCE`**; grant before escalation → **409 `ERR_PETITION_EVIDENCE_NOT_ESCALATED`**; after → GRANTED; duplicate live petition → **409 `ERR_DUPLICATE_ACTIVE_PETITION`**; list envelope carries `limit/offset/total_count/has_more`

### Interpretations chosen (PRD admitted >1 reading)
1. **Amend OCC vs state order** — PRD §3.6 sentence order (stale-version first) beats scaffold precondition order: 412 precedes 409.
2. **Slot capacity** — §3.8 self-contradicts ("at most four" vs "fourth is rejected"); followed the scaffold precondition + §2.6 "at most four": reject when ≥4 overlapping GRANTED already exist (5th window fails).
3. **Merger decide gate order** — followed §2.6's pinned numbered precedence: hold (10) → plan-required (11) → score band (12) → comment-close temporal (15), despite §3.6's narrative order.
4. **Cascade version bumps** — bump-on-change: a recompute that leaves a register unchanged is not a mutation and does not bump `version`.
5. **`service_review_hold` at creation** — literal PRD: initializes false even if an ESO is active; recomputed on subsequent ESO lifecycle events.
6. **Re-decide after reopen** — on a second UPHELD, award ledger resets (paid→0, granted/outstanding→new award) to preserve the pinned identity `outstanding == granted − paid`; REJECTED/DISMISSED leave prior award fields untouched ("award_status stays NONE").
7. **Reopen drops exposure** — exposure sums DECIDED complaints only, so it is recomputed on reopen as well as decide/payment/reversal.
8. **`api_request_timestamp`** — rendered from the logical clock (3-frac), never wall-clock.
9. **Shipment field name** — unpinned; accepted `{"tons": number}` (≥0, ≤3dp), validated only when outcome is UPHELD ("used only when upheld"), omitted/empty → award 0.
10. **Reparation amount checks at priority 17** — bad `amount_cents` on a non-DECIDED complaint yields `ERR_COMPLAINT_NOT_DECIDED`, not 400.
11. **`?status=` filter** — out-of-enum value → `ERR_INVALID_REQUEST` (priority-1 enum-range rule).
12. **Petition creation within priority 16** — distance (422) checked before duplicate-petition (409), per §3.8 narrative order.
13. **Duplicate-abandonment scope** — global per `line_segment_ref` (literal scaffold constraint, not per-carrier).
14. **Abandonment finding recorded on both branches** (GRANTED and DENIED).
15. **Domain-timestamp fractional shape** — follows the clock string's own fractional-digit count at computation time; identity timestamps always exactly 3.
16. **Fallback handlers** — unroutable paths/methods return the error envelope with non-catalog ids (defensive only; no PRD endpoint produces them).

**Orchestrator post-verification**: 20 files present, `py_compile` clean on all, no `uuid4().hex` anywhere, errors.py carries 47 ERR_ ids. Hand-back claims spot-confirmed.

## Step 7: Run Tests and Iterate — 2026-10-02T20:52:48.000Z

Confirmed: all 67 tests carry `status: passed` in every round. The sweep is clean on the first iteration.

**Summary**

- **Iterations run**: 1 (initial 8-round parallel sweep passed clean; no fix iterations needed).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none.
- **Final sweep result**: 67/67 passed in every round — round 1: 67/67, round 2: 67/67, round 3: 67/67, round 4: 67/67, round 5: 67/67, round 6: 67/67, round 7: 67/67, round 8: 67/67 (0 failed, 0 flaky across the union of all rounds).
- **Deliverables**: all 8 `results.${i}.json` files from the final sweep remain in `/home/ubuntu/github/CodingPRD/tasks/task_3496_rail_rate_complaint_adjudication_transaction_review/workspace/implementation/` (verified present, parseable, each reporting `passed == total == 67`).

The Step 5 test suite and Step 6 implementation (whose self-reported smoke transcript and interpretation list are recorded in the worklog) agree on first contact under per-test-server isolation, including the timing-sensitive areas the 8-round sweep targets (ESO lazy expiry, OCC version checks, slot-capacity windows, ledger invariants). No diagnostic arbitration was required.

**Orchestrator independent verification**: all 8 results files parsed — each passed=67/67, failed=0; per-round duration ~116s each; per-test durations differ across rounds (not copies); no source .py file in implementation/, test_suite/, or test_helpers/ is newer than the sweep (no post-sweep edits). Suspicion check on timing resolved by an orchestrator-run foreground sweep round: **67/67 passed in 112.8s**, matching the claimed per-round duration. Claim CONFIRMED. (verify file removed after check.)

## Step 8: Finalize PRD — 2026-10-02T20:52:48.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes — PRD.md already determined every behavior the implementation exhibits at the tested sites. No PRD_FINALIZED.md produced; Step 9 starts from PRD.md.

## Step 9: Complete PRD — 2026-10-02T21:10:00.000Z

The diff is exactly the 14 intended inline pins — no new sections, line count unchanged. The work is complete.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_3496_rail_rate_complaint_adjudication_transaction_review/workspace/PRD_COMPLETED.md` — produced as a copy of PRD.md plus 14 in-paragraph pins.

**Sizes:** PRD.md 328 lines / 59,660 chars → PRD_COMPLETED.md 328 lines / 61,283 chars (+1,623 chars; not byte-identical).

**Counts:** 14 ambiguity-pins, 0 mismatch-revisions, 1 impl-bug-reported.

### Pins (all ambiguity; each pins the impl's actual reading)

- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, not wall-clock — `envelope.py:24` (`render_identity(store.clock_now())`)
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` (400) — `pagination.py:12-29`
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence (logical clock makes ties ubiquitous) — `pagination.py:33` (`_seq`)
- §2.4 — revise — ambiguity — `created_at`/`updated_at` stamped from the logical clock (required for §3.8 freshness determinism) — `store.py:55-67`
- §2.5 — insert — ambiguity — unparseable `current_utc` → `ERR_INVALID_REQUEST` (400) — `routes_clock.py:21-23`
- §2.6 item 1 — insert — ambiguity — required string fields must be non-empty — `validate.py:26-29` (`req_str`)
- §2.7 — insert — ambiguity — "rendered to N places" figures serialize as JSON numbers equal to the rounded value; trailing zeros not preserved (1.8000 → `1.8`) — `serializers.py:65,132` (`float(Decimal)`)
- §2.9 — revise — ambiguity (tension with §3.5's scoping) — `service_review_hold` recomputed only on `COMMENT_PERIOD` applications; decided applications keep the last value — `derived.py:63-71`
- §2.10 — insert — ambiguity — unknown `status` filter value → `ERR_INVALID_REQUEST` (400) — `pagination.py:37-42`
- §3.1 / §3.2 — revise — ambiguity — `fiscal_year`, `contested_fiscal_year`, `annual_tons` are integers — `routes_carriers.py:151`, `routes_rates.py:55-57`
- §3.4 — revise — ambiguity — shipment object shape: tonnage in a `tons` field, non-negative, ≤3 decimal places, extra fields ignored; `shipments` omitted/null/empty → award 0 — `validate.py:70-82`, `routes_rates.py:220-238` (live-verified: `shipments: null` → award 0 → auto-CLOSED)
- §3.4 — insert — ambiguity — reopen does not clear award/prescription figures; a re-decision writes only its own outcome's fields — `routes_rates.py:340-363,277-294` (live-verified: UPHELD→partial pay→reopen→REJECTED leaves `prescribed=11550`, `award_status=PARTIALLY_PAID`, outstanding 83500)
- §3.6 — revise — ambiguity — the three showings are integers in [0,100] — `routes_mergers.py:55-57`
- §3.8 — revise — ambiguity — `facility_distance_miles` is an integer ≥ 0; malformed `YYYY-MM-DD` dates → `ERR_INVALID_REQUEST` — `routes_petitions.py:42,46-54`

### IMPL BUGS

- `implementation/routes_mergers.py:186-193` (+ `serializers.py:142-151` `plan_view`) — PRD §3.6: "The supplied conditions are recorded verbatim as `conditions_imposed`, the plan moves to `MONITORING`, and the conditions attach to the plan." — Impl records `conditions_imposed` on the merger and moves the plan `DRAFT`→`MONITORING`, but never stores the conditions on the plan resource (grep-confirmed: `conditions` is only ever written to the merger; the plan has no conditions field and none is serialized). — Minimal impl fix: on an `APPROVED_WITH_CONDITIONS` decision, persist the conditions array on the application's plan record (e.g., `plan['conditions'] = list(conditions)`) and expose it in `plan_view`. Note the PRD does not pin the plan-side field name/shape; the sweep is safe because `assert_service_assurance_plan` is subset-based (extra fields pass).

### Scan evidence (walk log)

**Files read in full:** `implementation/` — app.py, constants.py, store.py, errors.py, envelope.py, auth.py, timeutil.py, pagination.py, validate.py, serializers.py, derived.py, routes_clock.py, routes_carriers.py, routes_rates.py, routes_service.py, routes_mergers.py, routes_abandonment.py, routes_petitions.py, start.sh; `test_helpers/` — all 8 source files; `test_suite/` — conftest.py + all 10 test modules; `workspace/INSTRUCTION.md`; `results.8.json` (67/67 passed). SCAFFOLD*.yaml and worklog.md were not read.

**Per-file classification highlights:** all 40 PRD §4 endpoints present with matching roles and 201/200 conventions; all 47 `api_err` ids verified present in `ERROR_CATALOG` programmatically (no KeyError→500 path); validation priority order (shape→role→ownership→path existence→body refs→state→regulatory gates→temporal→uniqueness→fiscal) matches PRD §2.6 in every route, including the reparation event-type/role mismatch at priority 2 and the amend stale-version-before-state order of §3.6; rounding is `Decimal ROUND_HALF_UP` everywhere (away-from-zero on negatives, matching §2.7); domain vs identity timestamp families confirmed live (clock set with `.5Z` → ESO `issued_at` renders `2026-09-01T00:00:00.5Z`, `created_at` renders `.500Z`).

**Crash-path enumeration:** (a) nullable reads — all carrier/complaint/finding/`_nitu_dt`/`_comment_close_dt` accesses are state- or None-guarded; direct dict accesses (`rate_complaints[...]` in verify, `service_complaints[...]` in petition decide) are safe because referents are existence-validated at creation and never deleted; (b) catalog lookups — exhaustive match (see above); (c) divisions — denominators are `net_investment_cents ≥ 1`, `verified/alleged cost ≥ 1`, or a window list of length ≥ 1. **Live smoke (own server on dynamic port 46715, PID 2946693, killed after):** fractional-second clock + escalation rendering, negative-ROI finding (−4000 bps), integer `tons`, UPHELD→partial-pay→reopen→re-decide REJECTED corner, REVERSAL on a REJECTED complaint (legal per PRD precondition: paid == 0), `shipments: null`, `limit=0`, `status=BOGUS`, malformed `current_utc` — all returned correct 2xx/4xx envelopes, zero 500s.

**Considered and deliberately not pinned (immaterial/unreachable):** empty-string `X-User-ID` treated as missing (only viable reading — an empty id can never satisfy an ownership comparison); self-acquisition (`acquiring == target`) permitted (PRD silent, nonsense case, impl-permissive); backward clock sets permitted (PRD's "the instant the clock must thereafter read" is already unconditional); `shipments` on non-UPHELD outcomes ignored (already pinned by "used only when the complaint is upheld"); `?status=` on the three unfiltered list views silently ignored (web-default; PRD scopes the parameter to four named views); `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` envelope ids for routes/methods outside §4 (outside the PRD's jurisdiction); global (cross-carrier) `line_segment_ref` uniqueness (PRD text already reads carrier-unscoped, matching impl).

**Orchestrator post-verification**: PRD_COMPLETED.md = 328 lines (unchanged count), char delta +1612, exactly 14 lines replaced in place (no additions/removals of lines) matching the 14 claimed pins; 8 results files intact; no impl/test source files touched by Step 9 (mtime check vs sweep evidence).

## Step 9b: Impl-defect fix and re-sweep — 2026-10-02T21:22:18.000Z

Step 9 named one impl gap (PRD §3.6 "the conditions attach to the plan" unimplemented). Per the impl-defect terminal sequence: targeted impl fix, full re-sweep, PRD_COMPLETED.md untouched (impl moved toward PRD).

**Fix applied (orchestrator, 3 edits):**
1. `implementation/routes_mergers.py` decide — on `APPROVED_WITH_CONDITIONS`, each DRAFT→MONITORING plan now also receives `plan['conditions'] = list(conditions)` before `store.touch(plan)`.
2. `implementation/routes_mergers.py` plan creation — plan records now initialize `'conditions': []` for a stable serialized shape.
3. `implementation/serializers.py` `plan_view` — now exposes `'conditions': list(p.get('conditions', []))`.

**Targeted live smoke (dynamic port, exact PID killed):** created carriers A/B → merger (scores 50/50/50 → public_interest_score 50.00, in the [45,60) band) → plan (serialized with `conditions: []`) → clock advanced to 2026-10-17 (past 45-day comment close) → decide APPROVED_WITH_CONDITIONS with two conditions → plan read-back shows `status: MONITORING` and `conditions` equal to the supplied array verbatim. SMOKE PASS.

**Full 8-round parallel re-sweep (post-fix, fresh evidence replacing results.{1..8}.json):** round 1: 67/67 (113.1s), round 2: 67/67 (113.2s), round 3: 67/67 (113.1s), round 4: 67/67 (113.1s), round 5: 67/67 (113.2s), round 6: 67/67 (113.1s), round 7: 67/67 (113.2s), round 8: 67/67 (113.2s) — ALL 8 ROUNDS CLEAN. PRD_COMPLETED.md untouched.
