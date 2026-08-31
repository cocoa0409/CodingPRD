"""Depth coverage: the three compensating pairs and the quantities they conserve."""
from test_helpers import (
    TEST_USERS,
    assert_carrier_seat_identity,
    assert_tuition_cents_identity,
    certify_annual_review,
    completeness,
    fetch_applicant,
    fetch_carrier,
    fetch_dq_file,
    hire_from_context,
    revoke_annual_review,
    set_clock,
    setup_active_tuition_agreement,
    setup_file_due_for_annual_review,
    setup_qualified_application,
    terminate_hire,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
SCHOOL = TEST_USERS["school_coordinator_headers"]

FIVE_SERVED_MONTHS = ("2026-09", "2026-10", "2026-11", "2026-12", "2027-01")


def _agreement_with_five_months_served(dot_number: str):
    ctx = setup_active_tuition_agreement(
        tuition_total_cents=115205,
        commitment_months=12,
        service_months=FIVE_SERVED_MONTHS,
        carrier_overrides={"dot_number": dot_number},
    )
    set_clock("2026-08-20T00:00:00Z")
    return ctx


# ─── compensating_invariant: money ────────────────────────────────────────────

def test_the_termination_clawback_conserves_the_cents_identity(api):
    """PRD §3.9: "As the second hop of the termination cascade of §3.8, an `ACTIVE` agreement
    moves to `TERMINATED_CLAWBACK`: its entire `outstanding_cents` balance is moved into
    `clawback_cents` and `outstanding_cents` is set to zero."
    PRD §3.9: "One identity holds after every one of those three operations without exception:
    `tuition_total_cents` always equals `reimbursed_cents` plus `clawback_cents` plus
    `outstanding_cents` plus `forgiven_cents`. The figure `bonus_paid_cents` sits deliberately
    outside that identity — it is carrier retention money paid on top of the principal, not part of
    the tuition being retired — and it must never be included when the identity is checked."
    PRD §3.9: "The third hop then recomputes the applicant's `outstanding_clawback_cents` and
    `rehire_eligibility`, and because a positive clawback total forces `PERMANENTLY_INELIGIBLE`, a
    driver who walks away from an unretired school bill is barred from re-hire until that bill is
    settled."

    Design: Difficulty/compensating_invariant/tuition_cents_conserved_across_clawback_and_reversal
    """
    ctx = _agreement_with_five_months_served("DOT-2166-X")
    before = validate_success(
        api.get_tuition_agreement(ctx["tuition_agreement_id"], SCHOOL)
    )
    assert before["reimbursed_cents"] == 48000
    assert before["clawback_cents"] == 0
    assert before["outstanding_cents"] == 67200
    assert before["forgiven_cents"] == 5
    assert_tuition_cents_identity(before)

    terminate_hire(
        ctx["hire_id"],
        terminated_on="2026-08-20",
        termination_type="VOLUNTARY",
        rehire_flag="ELIGIBLE",
    )

    after = validate_success(
        api.get_tuition_agreement(ctx["tuition_agreement_id"], SCHOOL)
    )
    assert after["status"] == "TERMINATED_CLAWBACK"
    assert after["clawback_cents"] == 67200
    assert after["outstanding_cents"] == 0
    assert_tuition_cents_identity(after)
    assert fetch_applicant(ctx["applicant_id"])["rehire_eligibility"] == "PERMANENTLY_INELIGIBLE"


def test_reversing_the_clawback_restores_the_ledger_with_zero_drift(api):
    """PRD §3.9: "The reversal moves the whole `clawback_cents` balance back into
    `outstanding_cents`, sets `clawback_cents` to zero, returns the agreement
    `TERMINATED_CLAWBACK → ACTIVE`, and recomputes the applicant's `outstanding_clawback_cents` and
    `rehire_eligibility` — which is how a driver's re-hire eligibility is restored once the school
    bill is resolved."
    PRD §3.9: "One identity holds after every one of those three operations without exception:
    `tuition_total_cents` always equals `reimbursed_cents` plus `clawback_cents` plus
    `outstanding_cents` plus `forgiven_cents`."
    PRD §3.8: "`COOLDOWN` when the current logical-clock date is strictly earlier than the latest
    `terminated_on` advanced by the carrier's `rehire_cooldown_days`, so the cooldown expires on the
    very day that sum is reached; and `ELIGIBLE` otherwise."

    Design: Difficulty/compensating_invariant/tuition_cents_conserved_across_clawback_and_reversal
    """
    ctx = _agreement_with_five_months_served("DOT-2166-X")
    terminate_hire(
        ctx["hire_id"],
        terminated_on="2026-08-20",
        termination_type="VOLUNTARY",
        rehire_flag="ELIGIBLE",
    )

    reversed_agreement = validate_success(
        api.reverse_clawback(
            ctx["tuition_agreement_id"], {"reason": "TERMINATION_RECLASSIFIED"}, SCHOOL
        )
    )

    assert reversed_agreement["status"] == "ACTIVE"
    assert reversed_agreement["clawback_cents"] == 0
    assert reversed_agreement["outstanding_cents"] == 67200
    assert reversed_agreement["reimbursed_cents"] == 48000
    assert reversed_agreement["bonus_paid_cents"] == 4800
    assert reversed_agreement["months_served"] == 5
    assert_tuition_cents_identity(reversed_agreement)

    applicant = fetch_applicant(ctx["applicant_id"])
    assert applicant["outstanding_clawback_cents"] == 0
    assert applicant["rehire_eligibility"] == "COOLDOWN"


# ─── compensating_invariant: requisition seats ────────────────────────────────

def test_hiring_consumes_exactly_one_funded_seat(api):
    """PRD §3.8: "On success the service mints the hire record in `ACTIVE`, copying
    `applicant_id` and `carrier_id` from the application and leaving `terminated_on` null,
    `termination_type` at `NONE`, `rehire_flag` at `ELIGIBLE` and `tenure_days` at zero."
    PRD §3.8: "The application's `qualification_status` advances `QUALIFIED → HIRED`, and the
    carrier's `filled_requisitions`, `deficiency_ratio` and `posture` are recomputed with the
    carrier's `version` incremented by one."
    PRD §3.1: "The `filled_requisitions` count is the number of hire records at that carrier whose
    status is `ACTIVE`; terminated and rescinded hires do not count."

    Design: Difficulty/compensating_invariant/requisition_seats_conserved_across_hire_and_rescind
    """
    ctx = setup_qualified_application(carrier_overrides={"dot_number": "DOT-2166-Y"})
    before = fetch_carrier(ctx["carrier_id"])
    assert before["filled_requisitions"] == 0
    assert before["open_requisitions"] == 5
    assert before["posture"] == "OPEN"
    assert_carrier_seat_identity(before, 5)

    hire = hire_from_context(ctx, hired_on="2026-08-13")

    assert hire["status"] == "ACTIVE"
    assert hire["prior_hire_id"] is None
    assert hire["tenure_days"] == 0
    after = fetch_carrier(ctx["carrier_id"])
    assert after["filled_requisitions"] == 1
    assert after["posture"] == "OPEN"
    assert_carrier_seat_identity(after, 4)
    assert validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )["qualification_status"] == "HIRED"


def test_rescinding_returns_the_seat_and_the_qualified_posture(api):
    """PRD §3.8: "Rescission is the exact compensating inverse of the hire and exists for offers
    withdrawn before they took effect. The `SafetyDirector` supplies a `reason`; the record moves
    `ACTIVE → RESCINDED`, the application's `qualification_status` returns `HIRED → QUALIFIED`, and
    the carrier's `filled_requisitions`, `deficiency_ratio` and `posture` are recomputed with the
    carrier's `version` incremented by one."
    PRD §2.11: "After each compensating pair, the corresponding invariant must read exactly as it
    did before the original operation — the total qualification weight of a file, the cents identity
    of a tuition agreement, and the carrier's filled seat count respectively."
    PRD §3.8: "Active and rescinded hires are excluded from that list entirely, which is why a
    rescinded hire leaves eligibility untouched."
    PRD §3.6: "The `enrolled_count` figure counts every enrollment of the session in `RESERVED`,
    `ATTENDED` or `ABSENT`, so an absent driver still occupies the seat they consumed; only a
    cancellation gives a seat back."

    Design: Difficulty/compensating_invariant/requisition_seats_conserved_across_hire_and_rescind
    """
    ctx = setup_qualified_application(carrier_overrides={"dot_number": "DOT-2166-Y"})
    hire = hire_from_context(ctx, hired_on="2026-08-13")

    rescinded = validate_success(
        api.rescind_hire_record(hire["id"], {"reason": "OFFER_WITHDRAWN"}, SAFETY_DIRECTOR)
    )

    assert rescinded["status"] == "RESCINDED"
    carrier = fetch_carrier(ctx["carrier_id"])
    assert carrier["filled_requisitions"] == 0
    assert carrier["open_requisitions"] == 5
    assert carrier["posture"] == "OPEN"
    assert_carrier_seat_identity(carrier, 5)

    assert validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )["qualification_status"] == "QUALIFIED"
    assert validate_success(
        api.get_orientation_session(ctx["session_id"], RECRUITER)
    )["enrolled_count"] == 1
    assert fetch_applicant(ctx["applicant_id"])["rehire_eligibility"] == "ELIGIBLE"


# ─── compensating_invariant: document weight ──────────────────────────────────

def test_certification_adds_exactly_five_weight_points(api):
    """PRD §3.7: "On success the review clock returns to `NOT_DUE`, `last_annual_review_at` is
    stamped with the current logical-clock instant and `certified_by_user_id` with the acting
    `X-User-ID`; the `MVR_ANNUAL` and `ANNUAL_REVIEW_CERT` documents both become `PRESENT` with
    `effective_on` at the current logical-clock date; `next_review_due_on` is recomputed as the
    calendar date of `last_annual_review_at` advanced by the carrier's
    `annual_review_interval_days`; `completeness_pct` and `deficiency_count` are recomputed; and the
    file's `version` increments by one."
    PRD §3.7: "The final accounting, named `annual_review_final`, is the figure a DOT auditor
    certifies against and is available only on demand: it excludes `PSP_REPORT` and
    `CRIMINAL_CHECK`, which are pre-employment-only artifacts, and brings `MVR_ANNUAL` and
    `ANNUAL_REVIEW_CERT` into scope, leaving a denominator of 30, and it treats only `PRESENT` as
    satisfying, so a `WAIVED` artifact does not count."

    Design: Difficulty/compensating_invariant/dq_weight_conserved_across_annual_review_and_revocation
    """
    ctx = setup_file_due_for_annual_review(carrier_overrides={"dot_number": "DOT-2166-Z"})

    before = completeness(ctx["dq_file_id"], "annual_review_final")
    assert before["satisfied_weight"] == 6
    assert before["denominator_weight"] == 30
    assert float(before["completeness_pct"]) == 20.00
    assert fetch_dq_file(ctx["dq_file_id"])["total_weight"] == 33

    certified = certify_annual_review(ctx["dq_file_id"], auditor_user_id="aud-900")

    after = completeness(ctx["dq_file_id"], "annual_review_final")
    assert after["satisfied_weight"] == 11, "MVR_ANNUAL and ANNUAL_REVIEW_CERT add 3 + 2"
    assert after["denominator_weight"] == 30
    assert float(after["completeness_pct"]) == 36.67
    assert certified["review_state"] == "NOT_DUE"
    assert certified["next_review_due_on"] == "2028-08-31"
    assert certified["certified_by_user_id"] == "aud-900"
    assert certified["total_weight"] == 33


def test_revocation_removes_exactly_the_same_five_points(api):
    """PRD §3.7: "It clears `last_annual_review_at` and `certified_by_user_id` back to null,
    returns the `MVR_ANNUAL` and `ANNUAL_REVIEW_CERT` documents to `MISSING` with `effective_on`
    null, recomputes `next_review_due_on` from `opened_on` again — which typically pushes the review
    clock back to `DUE` — recomputes `completeness_pct` and `deficiency_count`, and increments the
    file's `version` by one. Every field the certification wrote is restored, and the file's total
    weight of 33 reads identically before the certification, after it, and after the revocation."
    PRD §2.11: "After each compensating pair, the corresponding invariant must read exactly as it
    did before the original operation — the total qualification weight of a file, the cents identity
    of a tuition agreement, and the carrier's filled seat count respectively."

    Design: Difficulty/compensating_invariant/dq_weight_conserved_across_annual_review_and_revocation
    """
    ctx = setup_file_due_for_annual_review(carrier_overrides={"dot_number": "DOT-2166-Z"})
    certify_annual_review(ctx["dq_file_id"], auditor_user_id="aud-900")

    revoked = revoke_annual_review(ctx["dq_file_id"], auditor_user_id="aud-900")

    restored = completeness(ctx["dq_file_id"], "annual_review_final")
    assert restored["satisfied_weight"] == 6, "the revocation removes exactly the 5 points added"
    assert restored["denominator_weight"] == 30
    assert float(restored["completeness_pct"]) == 20.00
    assert revoked["review_state"] == "OVERDUE"
    assert revoked["next_review_due_on"] == "2027-08-01"
    assert revoked["last_annual_review_at"] is None
    assert revoked["certified_by_user_id"] is None
    assert revoked["total_weight"] == 33
