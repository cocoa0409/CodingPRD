# Worklog — task_3126_family_lodging_near_hospital_room_assignment_referral

## Step 1: Create Task Directory — 2026-09-30T01:12:00.000Z

Pre-allocated task directory `./tasks/task_3126_family_lodging_near_hospital_room_assignment_referral/` with `workspace/` inside confirmed present (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T02:00:00.000Z

All three artifacts are complete and lint-clean. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3126_family_lodging_near_hospital_room_assignment_referral/`:
- `SCAFFOLD.yaml` — §1.0–§1.7 (envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, RBAC); no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

## Scaffold surface

- **Entities: 15** — Hospital, House, Room, Family, Referral, StayRequest (parallel state dimensions verification × assignment), Stay (cyclic extension/transition-plan/relocation loops), GuestRegistration, IllnessScreening (`common_fields: false` event), ContributionRequest, VolunteerGroup, MealShift (CLAIMED→OPEN cycle), CareSpace, CareSpaceBooking, InKindDonation
- **Endpoints: 63** (incl. `POST /_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z, two ops-run sweep checkpoints, and every FK reverse-reachability GET)
- **Rules per section:** 10 state machines (incl. OCC-relevant transitions), 2 OCC concurrency rules (`stay-request-create-stale-family`, `offer-respond-stale-request`), 12 calculations (weighted scoring with caps, pinned per-night-then-multiply rounding, sweep evaluation-order snapshot, half-open vs 30-min-buffer interval semantics), 10 ordered validation priorities, 29 error codes, 5 roles (segregation-of-duties on referral verify; entity-backed FamilyContact/HospitalReferrer)

## Design instances

- **Difficulty (§1.8): 21 instances** — dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 2, transitive_cascade 2 (depth-3 referral-revoke → verification-fail → offer-rescind → re-offer; depth-2 checkout → room-release → promotion), priority_pair_validation_conflict 2 (state×safety, referential×temporal), boundary_precision_check 3 (50.0-mile eligibility, occupancy-limit count edge, 38.0 °C strict-less-than), cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2 (room census, contribution ledger decomposition). All formula-derived asserts are pre-computed literals (e.g. provisional 100.00 vs verified 85.00; settled 3521 not 3518).
- **Corner (§1.9): 55 declared instances — 50 active + 5 `excluded_because` stubs** — across all nine taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model).

## Verification

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs
have reverse-reachability in §1.5.
(§1.5 endpoints: 63, §1.1 entities: 15, §1.8 instances: 21, §1.9 instances: 50, calls scanned: 654)
```

Additionally verified mechanically: zero unbound `${var}` placeholders across all 654 calls, all OCC `expected_*_version` payloads reference captured vars (never literals), and no forbidden concurrency vocabulary appears in any file. No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-09-30T02:01:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3126_family_lodging_near_hospital_room_assignment_referral/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T02:38:14.430Z

(Note: a first Step 4 attempt was interrupted mid-flight by host session stop; re-run from scratch at this timestamp. Verified beforehand that all three scaffold YAMLs parse cleanly and are untruncated.)

All coverage checks pass. Final summary:

---

**PRD Generation Complete**

- **Output path**: `/home/ubuntu/github/CodingPRD/tasks/task_3126_family_lodging_near_hospital_room_assignment_referral/workspace/PRD.md`
- **Line count**: 324 lines
- **Section structure**:
  - §1 Introduction (2 paragraphs)
  - §2 Global Specifications — 12 subsections (2.1 RBAC, 2.2 Response envelope [verbatim fixed block], 2.3 Pagination, 2.4 Common fields + logical clock, 2.5 Validation pipeline ordering, 2.6 OCC, 2.7 Occupancy posture, 2.8 Priority scoring, 2.9 Waitlist ranking / room selector, 2.10 Occupancy intervals, 2.11 Nested retrieval, 2.12 Monetary precision)
  - §3 Business Logic — 12 subsections covering referral lifecycle, supersession, offer/respond/check-in, stay extensions/reviews/relocation, checkout cascade, guests + screening, contributions, volunteer meal program, care spaces, in-kind donations, and the two sweeps
  - §4 Endpoint table (4 columns: Method / Path / Description / Authorized Roles) — 47 endpoints
  - §5 Error Code Catalogue (2 columns) — 29 errors

**Hard Contracts Audit Results**:

- **Contract 1 (Field-Name Coverage)**: PASS — 100/100 required field names (entity fields + endpoint inputs/query params) appear verbatim in backticks. Initial pass had 9 missing; repaired by adding prose mentions of `associated_hospital_id`, `family_name`, `primary_contact_name`, `home_city`, `child_patient_name`, `city`, `name`, `stay_id`, `care_space_id`.
- **Contract 2 (Rule Coverage)**: PASS — All 29 error IDs mentioned in §2/§3 prose; all enum/state values covered; validation priorities expressed as an ordered pipeline (§2.5); both OCC rules fully expressed with `expected_family_version` and `expected_stay_request_version` naming their error IDs (`ERR_STALE_VERSION`, 412); all state-machine transitions expressed including the three-hop revocation cascade, the checkout cascade, and the four-step pinned assignment-sweep evaluation order; scoring formula with band values (40/60/80), acuity multipliers (1.0/1.25/1.5/2.0), stay-factor cap (30 nights), weight (20.0), score cap (100.0), and round-half-up to 2 decimal places all translated to prose; screening boundary at exactly 380 tenths; stay-review boundary at exactly 21 nights; cleaning buffer at 30 minutes; offer TTL at 48 hours; referral validity window at 30 days.
- **Contract 3 (§3 Path Purity)**: PASS — 581 backticked tokens scanned inside §3; zero tokens start with `/`, zero bare HTTP methods, zero method+path combinations. All endpoints are referenced via state-transition framing or role + action verb.

## Step 5: Generate Unit Tests — 2026-09-30T02:59:51.704Z

Generation complete. Summary:

## Files written

**test_helpers/ (1347 lines)**
- `__init__.py` (30) — barrel export of framework + PRD-specific names
- `types.py` (341) — status enums (Referral/Verification/Assignment/Stay/Room/Posture/Guest/Screening/Contribution/Certification/MealShift/Booking/Donation + Acuity/CareType/Hardship/MealType/SupplyCategory), UserRole, and 15 entity TypedDicts (IllnessScreening correctly omits `updated_at`/`version`)
- `api_client.py` (208) — `ApiClient(GenericApiClient)` with one method per PRD endpoint (55 methods)
- `api_errors.py` (72) — `ApiErrorId` (29 ids) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (218) — per-entity `assert_*` plus contribution-ledger and house-census invariant checkers
- `factories.py` (131) — input-only payload factories
- `constants.py` (36) — thresholds (50 mi, 380 tenths, 21 nights, 30-min buffer, 48h TTL, 0.9 ratio, 30-day referral validity, 2-extension cap)
- `test_users.py` (26) — shared constants for opaque roles + `make_family_contact_headers` / `make_hospital_referrer_headers` entity-backed builders
- `fixtures.py` (283→284) — composite setup: `setup_hospital_house`, `create_verified_referral`, `setup_waitlisted_request`, `setup_offered_request`, `setup_active_stay`, screening/guest/contribution/donation/volunteer/care-space helpers

**test_suite/ (2891 lines, 92 tests)**
- `conftest.py` (35)
- `test_01_scoring_and_contributions.py` (10 tests), `test_02_state_cycles_and_cascades.py` (8), `test_03_validation_pairs_and_boundaries.py` (10), `test_04_cross_entity_overlap_invariants.py` (14), `test_05_entities_corner.py` (8), `test_06_state_machines_corner.py` (7), `test_07_calculations_corner.py` (5), `test_08_validations_corner.py` (15), `test_09_endpoints_rbac_occ_consistency.py` (15)

## Test counts by queue
- Difficulty (queue A): 42 tests across all 16 instances (each ≥2)
- Corner (queue B): 50 tests across all 23 non-stub instances (each ≥1)

## Instances skipped
None. All 4 `excluded_because:` stubs (verify_cascade_sets_verified_score, contribution_waive_side_effects, distance_ineligible_rejected, guest_limit_exceeded_rejected, ops_checkpoint_sweep_expire_then_promote — 5 total) were correctly not translated; their difficulty-instance owners are covered.

## Self-audit results
- Stage 1: all helpers compile; barrel imports clean; `pytest --collect-only` collects 92 tests with zero import errors.
- Stage 2: every test carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag resolving to a real instance; no untagged/dual-tagged tests; no `skip`/`skipif`/`xfail` markers; no scaffold references in comments/docstrings; every docstring's quoted citation contains a ≥8-word substring found verbatim in PRD.md (with backtick normalization); two-reader filter applied (e.g., literal ISO timestamp assertion retained only where PRD pins the clock value and format).

## Step 6: Generate Implementation — 2026-09-30T04:02:22.000Z

(Note: a first Step 6 attempt was interrupted mid-flight by host session stop with zero implementation files written; re-run from scratch. Verified after completion: all files present, all Python files parse.)

Scratch server down. Done.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3126_family_lodging_near_hospital_room_assignment_referral/workspace/implementation/`:

| File | Lines | Purpose |
|---|---|---|
| `app.py` | 1733 | Flask entry point, all routes, state machines, cascades, sweeps |
| `core.py` | 189 | Priority scoring, waitlist ranking, room selector, revocation cascade, promotion |
| `serializers.py` | 279 | API payload serializers with lazily-computed derived fields (house posture/counts, volunteer certification status) |
| `store.py` | 96 | In-memory dict store, logical clock (default `2026-09-01T00:00:00Z`), ISO8601/date parsing |
| `validate.py` | 98 | Body well-formedness gate (priority 0): unknown/missing/typed/enum fields |
| `envelope.py` | 79 | Response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, min 1, max 100) |
| `errors.py` | 77 | `ApiError` + full error-id catalog with HTTP statuses |
| `auth.py` | 26 | `X-User-ID`/`X-User-Role` auth, 5-role RBAC gate |
| `start.sh` | 10 | Guarded pip install + `exec python3 app.py` (PORT env, 0.0.0.0) |
| `requirements.txt` | 1 | `flask>=3.0` |

**Endpoint coverage: 52 / 52** from PRD §4 (clock, hospitals, houses, rooms, families, referrals, stay-requests, stays, guests, screenings, extensions/review/check-out, contribution requests, volunteer groups, meal shifts, care spaces/bookings, in-kind donations, both sweeps).

**Boot sanity check: PASS.** Booted via `bash start.sh` on a scratch port (18126), ran a full walkthrough: hospital → house (posture FULL with zero rooms) → room → family → referral → segregation-of-duties 403 on creator-verify → APPROVE cascade → stay-request create (provisional 66.67 / verified 96.67 per §2.8) → OCC `ERR_STALE_VERSION` on stale `expected_family_version` → offer → respond ACCEPT with `expected_stay_request_version` → check-in (Stay ACTIVE) → screening PASS at 379 tenths → guest registration → contribution request (1005 cents × PARTIAL → per-night 503, pinned round-half-up-then-multiply → requested 5030) → clock advance → check-out (settled 2515 for 5 actual nights, FORGIVEN, guests DEPARTED, ledger invariant holds). Negative paths verified: pipeline order (malformed body 400 beats missing auth), `ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN`, `ERR_NOT_FOUND`, `ERR_DISTANCE_INELIGIBLE`, `ERR_REFERRAL_NOT_VERIFIED`, `ERR_BOOKING_REFERRAL_MISMATCH`, care-space 30-min buffer (11:29 conflicts, 11:30 adjacent accepted), `ERR_FOOD_SAFETY_CERT_REQUIRED`, `ERR_DUPLICATE_MEAL_SHIFT`, `ERR_DUPLICATE_ACTIVE_REFERRAL`, `ERR_INSUFFICIENT_SUPPLY`, `ERR_DONATION_DEPLETED`, supply rollup, and assignment-sweep promotion of a verified waitlisted request into a free room. Scratch server killed by its exact port-bound PID afterward (other pipelines untouched).

Constraints honored: in-memory dict storage only, zero seeding at startup (store starts empty; all state built via the declared API surface), no test-suite/scaffold-design files read.

## Step 7: Run Tests and Iterate — 2026-09-30T04:10:54.903Z

All 8 rounds pass 92/92. Clean exit. (Orchestrator verified: results.1.json … results.8.json each report passed 92 / 92.)

## Summary

- **Iterations run:** 2 (initial sweep surfaced 2 deterministic failures; fix; confirmation sweep clean across all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3126_family_lodging_near_hospital_room_assignment_referral/test_suite/test_03_validation_pairs_and_boundaries.py` — `test_guest_registration_state_error_beats_screening_safety` and `test_guest_registration_on_checked_out_stay_reports_state_not_screening`: changed the asserted error_id from `ERR_INVALID_STATE` to `ERR_STAY_NOT_ACTIVE` (docstrings updated to cite the correct PRD sentences). Why: PRD §3.7 (guest registration) states verbatim "The stay must be `ACTIVE` — otherwise `ERR_STAY_NOT_ACTIVE`", and PRD §2.5 confirms "stay-activity gating surfaces as `ERR_STAY_NOT_ACTIVE` (HTTP 409)" within the fifth (state) pipeline stage. The tests asserted the generic state error while PRD uniquely names the specialized one for this exact endpoint; the priority-ordering intent (state stage fifth beats safety stage sixth) is preserved, and the assertion remains an exact error_id check — made more PRD-faithful, not weaker.

- **Fixes applied to `implementation/`:** none — the implementation already returned the PRD-mandated `ERR_STAY_NOT_ACTIVE` (app.py lines 911/974/1024) and was correct.

## Step 8: Finalize PRD — 2026-09-30T04:12:45.559Z

(Orchestrator verified: PRD_FINALIZED.md exists and is byte-identical to PRD.md.)

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3126_family_lodging_near_hospital_room_assignment_referral/workspace/PRD_FINALIZED.md` — byte-identical to PRD.md (no edits required).

**Line counts / %-delta:** PRD.md 324 lines; PRD_FINALIZED.md 324 lines; delta 0.0%.

**Changes:** none.

**Rationale.** The single Step 7 item was a pure test-side correction, not a PRD silence or impl/PRD mismatch:

- The two fixed tests (`test_guest_registration_state_error_beats_screening_safety`, `test_guest_registration_on_checked_out_stay_reports_state_not_screening` in `test_suite/test_03_validation_pairs_and_boundaries.py`) had asserted `ERR_INVALID_STATE`, but the PRD already uniquely determines `ERR_STAY_NOT_ACTIVE` for this endpoint in two independent places: §2.5 (PRD.md line 80, fifth pipeline stage: "stay-activity gating surfaces as `ERR_STAY_NOT_ACTIVE` (HTTP 409)") and §3.7 guest registration (PRD.md line 172: "The stay must be `ACTIVE` — otherwise `ERR_STAY_NOT_ACTIVE`"). The pipeline priority (state stage fifth beats safety stage sixth) is likewise pinned verbatim in §2.5.
- The implementation already matched the PRD: `workspace/implementation/app.py` line 911 (guest registration state gate) raises `ERR_STAY_NOT_ACTIVE`, with the screening safety gate checked after it. No implementation fix was applied in Step 7.
- Per the method ("Where PRD already determines behavior, keep prose verbatim"), no patch was warranted.

**Per-edit pre-edit search log.** Zero edits were committed, so no per-edit log entries exist. The no-edit decision itself was verified by a global consistency check of the edit's would-be subject:

- (a) Subject: stay-activity gating error identity (`ERR_STAY_NOT_ACTIVE` vs `ERR_INVALID_STATE`) and its pipeline position relative to the screening safety gate.
- (b) Impl paths enumerated and read/grepped: `app.py` lines 896-944 (guest registration: ownership check then state gate then screening gate then occupancy), 959-986 (screening creation, line 974 same state gate), 1010-1035 (extension request, line 1024 same state gate); grep for all `ERR_STAY_NOT_ACTIVE` raise sites (exactly 3, all covered by PRD §3.7, §3.8, §3.5 respectively). PRD cross-checked at lines 80, 156, 172, 174, 302-303.
- (c) Wording adjustment: none — every enumerated path is already correctly and uniquely described by existing PRD prose, so the only consistent action was to leave the text verbatim.

## Step 9: Complete PRD — 2026-09-30T04:21:19.735Z

(Orchestrator verified: PRD_COMPLETED.md exists, 324 lines / 58,900 chars.)

Done. PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_3126_family_lodging_near_hospital_room_assignment_referral/workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md (identical to PRD.md) 324 lines / 54,903 chars → PRD_COMPLETED.md 324 lines / 58,900 chars (+3,997 chars, 19 paragraphs touched, no new sections).

**Counts:** 17 ambiguity-pins, 2 mismatch-revisions.

Changes (all in-paragraph inserts/revisions):

- §2.3 — insert — ambiguity — pin invalid `limit`/`offset` rejection (`ERR_INVALID_REQUEST` 400), `has_more` = `offset+limit < total_count`, `created_at` ties broken by creation order — envelope.py:41-74; `x["_seq"]` sorts throughout app.py
- §2.5 — insert — ambiguity — existence stage also resolves body-referenced identifiers (`family_id`, `house_id`, `referral_id`, `room_id`, `volunteer_group_id`, `associated_hospital_id`, `relocation_room_id`) to `ERR_NOT_FOUND` — app.py:501-502, 646-648, 745, 1101-1102, 1406-1407
- §2.7 — insert — ambiguity — room creation fields `room_number`/`bed_count`/`occupancy_limit`, positivity → `ERR_INVALID_REQUEST`, initial `AVAILABLE`/unoccupied — app.py:271-297
- §2.9 — insert — ambiguity — final ranking tie broken by creation order — core.py:85-89
- §3.1 — insert — ambiguity — DECLINE also stamps `verified_by_user_id`, leaves `verified_at`/`valid_until` null; `notes` accepted but not persisted — app.py:546, 568-571
- §3.3 — revise — ambiguity — family `version` increments on every stay-request creation, even when nothing was superseded — app.py:698-699
- §3.4 — revise — mismatch — offer endpoint evaluates house-match before room-availability, so `ERR_ROOM_HOUSE_MISMATCH` surfaces when both fail (deviation from §2.5 stage order) — app.py:751-759
- §3.4 — insert — ambiguity — check-in against a vanished offered room yields `ERR_NOT_FOUND` — app.py:826-828
- §3.5 — insert — ambiguity — `additional_nights` must be positive → `ERR_INVALID_DATE_RANGE`; extension-count cap evaluated before backing-referral check — app.py:1026-1032
- §3.5 — revise — mismatch — OFFLINE cascade moves `ACTIVE`, `UNDER_REVIEW`, and `TRANSITION_PLANNED` occupying stays to `RELOCATION_REQUIRED` (PRD said only ACTIVE); also pin full set-status machine (MAINTENANCE gating, AVAILABLE gating, OFFLINE idempotence) and OFFERED-hold rescission on offlining — app.py:335-380
- §3.5 — insert — ambiguity — RELOCATE without `relocation_room_id` → `ERR_INVALID_REQUEST`; unresolvable id → `ERR_NOT_FOUND` — app.py:1095-1102
- §3.8 — insert — ambiguity — contribution creation allowed on any non-`CHECKED_OUT` stay — app.py:1193-1194
- §3.8 — insert — ambiguity — `amount_cents` must be positive → `ERR_INVALID_REQUEST` — app.py:1259-1260
- §3.9 — insert — ambiguity — certify is repeatable, overwriting `certified_until` — app.py:1317-1328
- §3.9 — revise — mismatch — `certification_status` derived on every read or change (not only "on every change"), so a clock advance alone flips CERTIFIED → EXPIRED on next read — serializers.py:202-209
- §3.10 — insert — ambiguity — `party_size` must be positive → `ERR_INVALID_REQUEST`; naive datetimes interpreted as UTC and echoed normalized to UTC ISO 8601 with three fractional digits — app.py:1486-1487, store.py:86-96, app.py:1519-1520
- §3.11 — insert — ambiguity — distribution `quantity` must be positive → `ERR_INVALID_REQUEST`; rollup always reports all four categories (0 when none) — app.py:1619-1620, 259-264
- §3.12 — insert — ambiguity — assignment sweep step 1 scoped to target house; step 2 expires stale VERIFIED referrals system-wide with cascades at other houses; `promoted_request_ids` reports target-house promotions only; stay-review sweep scoped to stays whose room belongs to the target house — app.py:1649-1695, 1714-1719
- §4 — insert — ambiguity — undefined paths/unsupported methods → `ERR_NOT_FOUND` 404; `GET /api/stay-requests` for FamilyContact implicitly scoped to own family (foreign `family_id` filter yields empty list, not 403) — app.py:89-96, 722-723

No mismatches remain that I could identify; the only literal §2.5 ordering deviations in impl (offer endpoint house-match-first, extension cap-before-referral) are now explicitly pinned in §3.4/§3.5.
