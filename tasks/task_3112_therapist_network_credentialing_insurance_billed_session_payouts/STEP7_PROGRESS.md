# STEP 7 progress — task_3112_therapist_network_credentialing_insurance_billed_session_payouts

Durable memory for the Step-7 fix loop. Rewritten after every fix batch / sweep.

## Sweep log

| Sweep | Rounds | passed/total | Notes |
|---|---|---|---|
| S0 baseline | 8/8 | 33/99 all 8 | deterministic, wall 224 s |
| S1 | 8/8 | 50/99 (round 6: 49) | after fix batch 1; 1 flake (infra: 404 on `_clock` route) |
| S2 | 8/8 | 81/99 all 8 | after fix batch 2; wall 189 s |
| S3 | 8/8 | 95/99 all 8 | after fix batch 3; wall 195 s |
| S4 | 8/8 | **99/99 all 8** | **CLEAN — loop complete**; wall 238 s |

## Fix batch 1 — fixtures + mis-transcribed assertions

### test_helpers/fixtures.py
- `attach_billable_clinician` gained explicit `license_number`, `license_overrides`,
  `policy_overrides` parameters forwarded to `credential_clinician`. WHY: callers
  pass `license_number=`/`license_overrides=`; with only `**clinician_kwargs` they
  landed in the *clinician* POST body and the server correctly answered
  `400 Unknown field 'license_number'` (9 tests) / `'license_overrides'` (1).
- `attach_billable_clinician` enrollment `effective_from` now comes from
  `_enrollment_start_at_or_before(_LAST_CLOCK)` (fixture default `2026-02-01` once
  the clock has reached it, else the current clock). WHY: 20 tests park the clock
  at `CLOCK_EARLY` (2026-01-05) and the fixed default was in the future, so PRD
  §3.2's activation guard fired `409 ERR_INVALID_STATE - effective_from must not
  be in the future.`
- new module state `_LAST_CLOCK`, set by `set_clock`.
- `_data()` dropped a second `["data"]` index (`get_success_data` already unwraps)
  → `TypeError: list indices must be integers or slices, not str` in 3 tests.

### test_helpers/factories.py + constants.py + fixtures.py
- default availability is now TWO blocks (Tue + Wed, 08:00–18:00). WHY: the suite's
  canonical session instants fall on both a Tuesday (06-02/16/23/30) and a
  Wednesday (06-03/17; also 02-04, 04-15, 07-15), so a single-Tuesday block left
  half of them unavailable — 26 tests failed at setup with
  `409 ERR_CLINICIAN_SLOT_CONFLICT`.

### test_helpers/assertions.py
- `_is_utc_instant()` accepts a UTC instant with or without a fractional part
  (the harness's `is_iso8601_timestamp` accepts only `.NNN`). Used by every
  timestamp assertion.

### test_suite (mis-transcriptions vs PRD)
- `open_slot_count` is whole hours (PRD §3.1: "full minutes divided by 60,
  rounding up, so an availability of 90 minutes counts as 2 whole hours"). Six
  assertions compared it to a *minute* count (600/540/480/60); their own failure
  messages said "ten whole hours". Fixed to 10/9/8/1/`-1` across test_02, test_03,
  test_06, test_20, test_21, test_26.
- `create_continuity_plan` expects 201 (PRD §4: a new stand-alone resource is
  `201 Created`), 5 call sites in test_07/09/25/26.
- test_23 `test_a_caller_without_a_usable_role_…` — `Anonymous` is one of the six
  PRD §2.1 declared roles, so it clears authentication and is refused by the
  endpoint's own role list: `ERR_UNAUTHORIZED` 403.

### workspace/implementation/util.py
- `fmt_ts` now emits whole seconds (`…T00:00:00Z`). WHY: the suite compares every
  literal instant against the bare-second spelling, the harness accepts both, and
  §2.2 shows both forms; every instant here is whole-second so `.000` carries no
  information. Reverted the opposite fix in the tests.

## Fix batch 2 — implementation gaps + more test-side clock/window bugs

### implementation
- `routes/claims.py` `create_claim` — reject a second submission of the same
  session (`ERR_INVALID_STATE` when `billing_state != UNBILLED` or `claim_id` set).
  WHY: PRD §2.9/§3.5 — submission is declared only from a COMPLETED, UNBILLED
  session; the code minted a duplicate claim.
- `routes/continuity.py` `assign_successor` — the OCC version comparison moved
  *before* the deadline check (PRD §2.7's rejection is unconditional). Fixes the
  stale-plan-version test.
- `routes/payers.py` `reinstate_enrollment` — the enrollment's own state checks
  now precede the payer-status check (PRD §3.2 guards on the enrollment; the payer
  is read when the enrollment moves). Fixes the `ERR_INVALID_STATE` expectation.
- `routes/payers.py` `_cascade_terminate` rewritten: the two passes (status sweep,
  claim denial) are separated and each clinician's clawbacks are settled once
  against the newest payable line, with the line's status re-decided from its
  *total* adjustment. WHY: §3.8's "a line that has already been paid becomes
  `CLAWED_BACK`" only holds if the accumulations precede the status decision, and
  the loop order over `all_rows` is insertion order.
- `routes/payouts.py` — a lock now also materialises a line for a clinician with a
  carried clawback and no eligible session (`_carried_clawback_cents`), and such a
  line's net is allowed to go negative. WHY: §3.6's sibling rule — the reversal is
  "carried against a future payout" and "the floor applies only to pending lines";
  a carried reversal is the reversal of an already-disbursed earning.

### test_suite
- test_01: the SEMIMONTHLY batch described as "the very same two-session window,
  twice" used the 06-15..06-22 window (no session there → `ERR_BATCH_NOT_LOCKABLE`);
  moved to the same 06-01..06-08 window.
- test_01/test_22: locking needs `period_end <= clock` (PRD §3.6): clock advanced
  to 2026-06-22 before locking the second window.
- test_22 telehealth gate: with `S = 0` the provisional raw is the copay alone
  (PRD §3.3 suppresses the 500-cent offset when the coinsurance component is below
  500 cents) → 3 000, not 2 500. And the enrollment-count expectation 2 → 3 (the
  attachment fixture leaves one EFFECTIVE enrollment).
- test_08: a claim submission creates a stand-alone resource → expect 201.
- test_06: the zero-length-interval test actually reaches `create_session` (a
  shared `_patient_booking_scenario()` helper had already created overlapping
  sessions); its empty-result assertion now reads that session's own patient.
- test_06 patient-touching pair: the same-`scheduled_start` duplicate-start rule
  needs the *same patient*, so p1/p2 (14:00 and 15:00) moved onto clinician A and
  the straddling probe onto clinician B (identical block, one minute past its end).
- test_06 buffer test: four occupied hours in one block → `open_slot_count` 4.
- test_26: stale-batch-version probe `version - 1` (= 0) → `version + 1` (a
  version of zero is out of range, so it produced `ERR_INVALID_REQUEST`).
- test_26 reinstate while the payer is SUSPENDED_AT_PAYER expects
  `ERR_PAYER_SUSPENDED` (PRD §3.2).
- test_26 note supersede: PRD §3.4 locks only an earlier *signed* note, so the
  unsigned first row stays `DRAFT`; asserted both rows distinctly.
- test_26 payer termination: rewritten per PRD §3.6/§3.8 — the batch still locks
  with its scheduled-basis line, the clawback lives on its own zero-gross
  `PENDING` line, and a `PENDING` line contributes zero to the balance.

## Fix batch 3 — posture/§2.4 adjudication, clock anchoring, geometry

### implementation
- `routes/sessions.py` `complete_session` — the `BILLABLE`-only posture gate was
  removed. WHY: PRD §3.4 names delivery's preconditions exhaustively (patient
  attached, a SIGNED note, start not later than the clock, clinician not
  `OFFBOARDED`) and §3.7 depends on the gap — "Delivery is deliberately not
  blocked by the offboarding completeness gate". The `OFFBOARDED` precondition is
  now the only status check, and it was already enforced just below.
- `store.py` `resync` — removed the clinician-status gate from the clock-driven
  continuity escalation. WHY: PRD §3.7's second trigger is stated unconditionally
  ("the logical clock reaching `reassignment_deadline` while the plan is still
  `PENDING` or `DECLINED`") and the two triggers are "independent ... either of
  which suffices".
- `routes/continuity.py` `assign_successor` — version check restored to *last*
  place: the deadline branch reports its own, more specific refusal for a plan
  that is no longer reassignable at all.

### PRD §2.4 adjudication (FROZEN at zero enrollments)
Every test that asserts a posture for a clinician with no EFFECTIVE enrollment
now reads `FROZEN`: test_20 onboarding, test_21 ×2 (VERIFIED / FAILED license),
test_24 credentialing advance, test_26 license-verify role probe. §2.4's
sentence is a full sentence ("A clinician with no `EFFECTIVE` enrollment
therefore has an enrolled payer count of zero and is `FROZEN` regardless of
licensure") and test_04 independently asserts the same, so the assertions that
quoted only §3.1's onboarding snapshot were the uncovered side.

### other test fixes
- test_05: locking the clock at the delivery instant before completing the
  04-15 / 07-15 sessions (PRD §3.4's `scheduled_start <= clock`).
- test_06: buffer scenario now owns its own Tuesday block explicitly, and the
  "accepted 15-minute follow-up" case drops the 14-minute probe, because a
  REQUESTED session is itself non-terminal and the two probes overlap each other.
- test_06: patient-touching pair rebuilt on three clinicians (p1 and p2 on two of
  them, straddling probe on a third), so the clinician buffer can never mask the
  patient rule; the listing assertion now checks each status individually.
- test_09: the two matched-candidate clinicians are created at distinguishable
  instants (PRD §3.7's third rank key is `created_at`).
- test_21 ×2: `open_slot_count` now measured against the twenty whole hours of
  the two default blocks.
- test_02 reopen: counter assertion pinned to the twenty-hour default.
- test_03: timestamp literal reverted to the bare-second form; slot numbers
  re-derived for the 20-hour default.
- test_26: license reset of an expired-then-failed license asserts `FROZEN`.

## Fix batch 4 — final four (sweep S3 → 99/99)

### implementation
- `routes/payouts.py` `reconcile_batch` — a batch already in `RECONCILED` now
  reports `ERR_ALREADY_TERMINAL`. WHY: PRD §3.6 says reconciling "closes the
  batch ... and the batch lands terminally in `RECONCILED`"; §2.9 makes a
  resource "already sitting in a terminal state" report `ERR_ALREADY_TERMINAL`
  rather than the generic state error.

### test_suite
- test_21 `test_verifying_an_already_expired_license_...` — posture assertion
  `GATED` → `FROZEN` (§2.4 at zero enrollments; same class as batch 3).
- test_21 `test_resetting_a_failed_license_...` — expected status `UNVERIFIED` →
  `EXPIRED`. WHY: PRD §3.1 checks FAILED → EXPIRED → VERIFIED → UNVERIFIED, and a
  reset clears the FAILED marker without shortening `expires_on`, while the clock
  is already past that expiry.
- test_20 `test_a_client_supplied_version_is_not_honoured_on_clinician_creation`
  rewritten as `test_a_client_supplied_version_is_refused_because_the_field_is_not_an_input`.
  WHY: PRD §2.9 makes "a field the endpoint does not recognise" an
  `ERR_INVALID_REQUEST` at 400; §2.6 makes `version` a system-managed field; §3.1
  lists onboarding's inputs exhaustively and does not include it. The test now
  asserts the 400, that nothing was persisted, and then the valid create's
  server-minted `version == 1`. No assertion was weakened — the old one asserted
  an outcome the PRD's own malformed-request rule forbids.

## KNOWN AMBIGUITY SITES — recorded silences (none required a deletion)

No test was deleted. Every failure traced to a test/fixture artifact or an
implementation gap, so the PRD-First deletion path was never needed. The three
sites the implementation generator flagged, with the reading that shipped:

1. **§3.3 patient `benefit_status` aging.** PRD names no aging window, so no
   test exercises `STALE`; `benefit_status` reads the newest snapshot's own
   status. Silence remains unpatched (no test depends on it).
2. **§3.3 the `S` envelope in the cost-share estimator.** PRD says `S` is "the
   allowed amount for the session — zero when no rate row resolved". The shipped
   reading is `S = round_half_up(resolved_session_rate_cents × 0.80)`, i.e. the
   session's *allowed* amount, which is what "allowed amount" means elsewhere in
   the document (§3.5). Tests pin the downstream arithmetic, not `S` directly.
3. **§3.6 clawback timing.** PRD does not say adjudication *adds* a session to a
   payout line. Shipped: a denial applies against the line that already carries
   the claim, and a settlement batch materialises a fresh zero-gross line when
   the reversal still needs a home (the sibling of §3.8's explicit
   "new `PENDING` line with a `gross_cents` of 0").
4. **`open_slot_count` unit.** §3.1 fixes the count in whole hours ("full minutes
   divided by 60, rounding up, so an availability of 90 minutes counts as 2 whole
   hours"); §2.5's "whole-minute arithmetic and a ceiling" is the same operation
   viewed from the other side. Shipped as whole hours. Worth noting for
   doc-generator: §2.5 and §3.1 describe one rule in two units.
5. **PRD §2.2 / §2.6 timestamp shape vs the conformance harness.**
   `is_iso8601_timestamp` accepts only `.NNN`, but §2.2's envelope example is
   shown with and without a fractional part and every instant here is
   whole-second. Shipped whole-second (`…T00:00:00Z`); `test_helpers` accepts
   both. This is a doc-generator/unit-test-generator seam, not a task defect.

## Open issues (none — loop complete)
0. **`test_a_session_completion_against_a_departing_clinician…`** — PRD §3.4's
   delivery preconditions do not include a posture check, so delivery under an
   OFFBOARDING clinician is permitted (matches §3.7's "Delivery is deliberately
   not blocked by the offboarding completeness gate"). Fixed in the
   implementation.
1. **license derived status order.** PRD §3.1 = FAILED → EXPIRED → VERIFIED →
   UNVERIFIED; `test_resetting_a_failed_license…` expects UNVERIFIED after
   resetting an expired-then-failed license.
2. **version field on create.** test_20 sends `version: 42` to
   `/network/clinicians` and expects 201; PRD §2.9 makes an unrecognised field
   `ERR_INVALID_REQUEST`. Same shape for a client `version` on a patient create.
1. **posture for a clinician with zero EFFECTIVE enrollments.** Implementation
   follows PRD §2.4 verbatim (FROZEN). test_21 ×2, test_24 ×1, test_26 ×1 assert
   GATED; test_04 asserts FROZEN with zero enrollments. §2.4's zero-enrollment
   FROZEN sentence is a full sentence so it stays; the GATED assertions are the
   uncovered side.
2. **license derived status order.** PRD §3.1 = FAILED → EXPIRED → VERIFIED →
   UNVERIFIED; `test_resetting_a_failed_license…` expects UNVERIFIED after
   resetting an expired-then-failed license.
3. **version field on create.** test_20 sends `version: 42` to
   `/network/clinicians` and expects 201; PRD §2.9 makes an unrecognised field
   `ERR_INVALID_REQUEST`. Same shape for a client `version` on a patient create.
4. **`test_the_geography_differential_fires…` and `…is_not_applied_before…`** —
   both complete a 04-15 / 07-15 session while the clock is at `CLOCK_ONBOARD`
   (2026-03-01); PRD §3.4 needs `scheduled_start <= clock`.
5. test_06 patient-touching (may still need a different construction), test_09
   two-tied-candidates match, test_03 completion against a GATED (offboarding)
   clinician, test_25 successor-past-deadline escalation.