"""Corner queue — the suspension scan: the inert hysteresis band 75-79 in
both directions, and the second-suspension-within-730-days revocation with
REVOKED absorbing (PRD §3.7)."""

from test_helpers import (
    CLOCK_START_ISO,
    TEST_USERS,
    accept_mediation,
    business_respond,
    compute_snapshot,
    conclude_mediation_case,
    consumer_accept,
    consumer_reject,
    file_and_forward_complaint,
    get_business,
    offer_mediation,
    reopen_complaint,
    run_daily_close,
    schedule_mediation_session,
    set_clock,
    setup_accredited_business,
    setup_world,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def _mediate_to_agreement(complaint, business, consumer, session_start,
                          session_end):
    case = offer_mediation(complaint)
    case = accept_mediation(case, business, consumer)
    case = schedule_mediation_session(case, mediator_id="med-a",
                                      session_start_at=session_start,
                                      session_end_at=session_end)
    conclude_mediation_case(case, outcome="AGREEMENT")


def test_suspension_hysteresis_band_75_to_79_inert_both_directions(api):
    """PRD §3.7: "Scores from 75 through 79 form a hysteresis band: they
    neither suspend an accredited business nor reinstate a suspended one, so
    a business must genuinely recover to 80 before regaining its standing."
    PRD §3.7: "An `ACCREDITED` business whose latest published score is below
    75 is suspended: `accreditation_status` becomes `SUSPENDED`,
    `suspension_count_24m` increments by 1, `last_suspension_at` is stamped,
    and the business's `version` increments by 1."

    Design: Corner/calculations/suspension_hysteresis_band_75_to_79_inert_both_directions

    """
    world = setup_world(business_overrides={
        "legal_name": "Hysteresis Small LLC", "employee_count": 10,
        "founded_on": "2024-06-01T00:00:00Z"})  # 2 full years: age deducts 2
    bureau, consumer = world["bureau"], world["consumer"]
    business = setup_accredited_business(world=world)["business"]
    # c1 UNANSWERED at the 2026-09-16 sweep; c2 answered then rejected.
    c1 = file_and_forward_complaint(consumer, business, category="SERVICE",
                                    description="c1 expires")
    set_clock("2026-09-16T00:00:00Z")
    run_daily_close(bureau["id"])
    c2 = file_and_forward_complaint(consumer, business, category="BILLING",
                                    description="c2 rejected")
    c2 = business_respond(c2, business, body="offer")
    consumer_reject(c2, consumer, body="no")
    # 12 + 8 + 2 = 22 deductions -> 78: inside the band, ACCREDITED holds.
    assert compute_snapshot(business, "PUBLISHED")["score"] == 78
    run_daily_close(bureau["id"])
    assert get_business(business["id"])["accreditation_status"] == \
        "ACCREDITED"
    # c3 rejected too: 12 + 8 + 8 + 2 = 30 -> 70 < 75: first suspension.
    c3 = file_and_forward_complaint(consumer, business, category="SERVICE",
                                    description="c3 rejected")
    c3 = business_respond(c3, business, body="offer")
    consumer_reject(c3, consumer, body="no")
    assert compute_snapshot(business, "PUBLISHED")["score"] == 70
    run_daily_close(bureau["id"])
    suspended = get_business(business["id"])
    assert suspended["accreditation_status"] == "SUSPENDED"
    assert suspended["suspension_count_24m"] == 1
    # Mediate c3 away: 12 + 8 + 2 = 22 -> 78 again; 78 < 80: no reinstate.
    _mediate_to_agreement(c3, business, consumer,
                          "2026-09-22T09:00:00Z", "2026-09-22T10:00:00Z")
    assert compute_snapshot(business, "PUBLISHED")["score"] == 78
    run_daily_close(bureau["id"])
    assert get_business(business["id"])["accreditation_status"] == \
        "SUSPENDED", "the band is inert in both directions"
    # Mediate c2 away: 12 + 2 = 14 -> 86 >= 80: reinstatement.
    _mediate_to_agreement(c2, business, consumer,
                          "2026-09-22T10:00:00Z", "2026-09-22T11:00:00Z")
    assert compute_snapshot(business, "PUBLISHED")["score"] == 86
    run_daily_close(bureau["id"])
    assert get_business(business["id"])["accreditation_status"] == \
        "ACCREDITED"


def test_second_suspension_within_730_days_revokes_permanently(api):
    """PRD §3.7: "If that suspension would be the business's second within
    the trailing 730 days, the business is instead revoked:
    `accreditation_status` becomes `REVOKED`, with the same counter,
    timestamp, and version updates."
    PRD §3.7: "`REVOKED` is terminal: no transition leaves it."

    Design: Corner/calculations/second_suspension_within_730_days_revokes_permanently
    """
    world = setup_world(business_overrides={
        "legal_name": "Repeat Offender Micro LLC", "employee_count": 4,
        "founded_on": "2020-01-01T00:00:00Z"})  # 6 full years: age deducts 0
    bureau, consumer = world["bureau"], world["consumer"]
    business = setup_accredited_business(world=world)["business"]
    # Cycle 1: c1 UNANSWERED, c2/c3 UNRESOLVED -> published 72 -> SUSPENDED.
    c1 = file_and_forward_complaint(consumer, business, category="SERVICE",
                                    description="c1 expires")
    set_clock("2026-09-16T00:00:00Z")
    run_daily_close(bureau["id"])
    c2 = file_and_forward_complaint(consumer, business, category="BILLING",
                                    description="c2 rejected")
    c2 = business_respond(c2, business, body="offer")
    consumer_reject(c2, consumer, body="no")
    c3 = file_and_forward_complaint(consumer, business, category="WARRANTY",
                                    description="c3 rejected")
    c3 = business_respond(c3, business, body="offer")
    consumer_reject(c3, consumer, body="no")
    assert compute_snapshot(business, "PUBLISHED")["score"] == 72
    run_daily_close(bureau["id"])
    suspended = get_business(business["id"])
    assert suspended["accreditation_status"] == "SUSPENDED"
    assert suspended["suspension_count_24m"] == 1
    # Clean cycle 1 up and republish 100 -> ACCREDITED.
    c1 = reopen_complaint(c1)
    c1 = business_respond(c1, business, body="fixed")
    consumer_accept(c1, consumer, body="ok")
    _mediate_to_agreement(c2, business, consumer,
                          "2026-09-22T09:00:00Z", "2026-09-22T10:00:00Z")
    _mediate_to_agreement(c3, business, consumer,
                          "2026-09-22T10:00:00Z", "2026-09-22T11:00:00Z")
    assert compute_snapshot(business, "PUBLISHED")["score"] == 100
    run_daily_close(bureau["id"])
    assert get_business(business["id"])["accreditation_status"] == \
        "ACCREDITED"
    # Cycle 2: c4 UNANSWERED at the 2026-10-01 sweep, c5 UNRESOLVED.
    c4 = file_and_forward_complaint(consumer, business, category="DELIVERY",
                                    description="c4 expires")
    set_clock("2026-10-01T00:00:00Z")
    run_daily_close(bureau["id"])
    c5 = file_and_forward_complaint(consumer, business, category="WARRANTY",
                                    description="c5 rejected")
    c5 = business_respond(c5, business, body="offer")
    consumer_reject(c5, consumer, body="no")
    # 5 outcomes over the MICRO threshold 3: volume 12 + unanswered 12 +
    # unresolved 8 = 32 -> 68 < 75: the second suspension revokes.
    assert compute_snapshot(business, "PUBLISHED")["score"] == 68
    run_daily_close(bureau["id"])
    revoked = get_business(business["id"])
    assert revoked["accreditation_status"] == "REVOKED"
    assert revoked["suspension_count_24m"] == 2
    # Even a recovered 88 cannot leave REVOKED.
    c4 = reopen_complaint(c4)
    c4 = business_respond(c4, business, body="fixed")
    consumer_accept(c4, consumer, body="ok")
    _mediate_to_agreement(c5, business, consumer,
                          "2026-10-05T09:00:00Z", "2026-10-05T10:00:00Z")
    assert compute_snapshot(business, "PUBLISHED")["score"] == 88
    run_daily_close(bureau["id"])
    final = get_business(business["id"])
    assert final["accreditation_status"] == "REVOKED"
    assert final["suspension_count_24m"] == 2
