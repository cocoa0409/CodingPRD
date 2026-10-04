"""Cyclic and parallel lifecycles (queue A, rule `non_linear_state_machine`).

`MemberStation` runs a review loop that a station may legitimately pass through
an unbounded number of times, and `UnderwritingAgreement` carries two
independent state dimensions plus a segment-by-segment self-loop.
"""
from test_helpers import (
    AUDITOR,
    UNDERWRITING,
    api_client,
    create_station,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    set_clock,
)

# PRD §3.1: a station whose newsroom headcount is below the eligibility floor
# of 2 falls under the deficiency gate, and whose coverage sits above 50000.
DEFICIENT_INPUTS = dict(
    call_sign="KTEP", licensee_name="Border Licensee", state_code="TX",
    dma_market_rank=92, dma_households=300000, coverage_population=60000,
    full_time_staff_count=4, newsroom_staff_count=1,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)

UNDERWRITING_STATION = dict(
    call_sign="KUOW", licensee_name="Cascade Licensee", state_code="WA",
    dma_market_rank=13, dma_households=1900000, coverage_population=90000,
    full_time_staff_count=7, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)


def setup_review_loop_station():
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(**DEFICIENT_INPUTS)
    headers = make_station_manager_headers(station["id"])
    get_success_data(api_client.submit_eligibility(station["id"], headers))
    return {"station": station, "headers": headers}


def test_deficiency_record_moves_an_under_review_station_to_deficient():
    """PRD §3.1: "A compliance auditor may record a deficiency against any station
    in `UNDER_REVIEW`, moving it to `DEFICIENT`."

    Design: Difficulty/non_linear_state_machine/cyclic_station_eligibility_review_loop
    """
    ctx = setup_review_loop_station()
    resp = api_client.record_deficiency(
        ctx["station"]["id"], {"deficiency_factors": ["NEWSROOM_STAFF"]}, AUDITOR)
    data = get_success_data(resp)

    assert data["eligibility_status"] == "DEFICIENT", (
        f"expected DEFICIENT, got {data['eligibility_status']}"
    )


def test_remediation_moves_a_deficient_station_to_remediation_submitted():
    """PRD §3.1: "From `DEFICIENT` the station manager may submit remediation,
    supplying a non-empty `remediated_factors` payload and moving the station to
    `REMEDIATION_SUBMITTED`".

    Design: Difficulty/non_linear_state_machine/cyclic_station_eligibility_review_loop
    """
    ctx = setup_review_loop_station()
    get_success_data(api_client.record_deficiency(
        ctx["station"]["id"], {"deficiency_factors": ["NEWSROOM_STAFF"]}, AUDITOR))
    resp = api_client.remediation(
        ctx["station"]["id"], {"remediated_factors": ["NEWSROOM_STAFF"]}, ctx["headers"])
    data = get_success_data(resp)

    assert data["eligibility_status"] == "REMEDIATION_SUBMITTED", (
        f"expected REMEDIATION_SUBMITTED, got {data['eligibility_status']}"
    )


def test_second_submission_pass_returns_the_station_to_under_review():
    """PRD §3.1: "from there the second submission pass described above returns it
    to review".
    PRD §3.1: "The `DEFICIENT`-to-remediation-to-review loop is the station's
    revision cycle and may run more than once".

    Design: Difficulty/non_linear_state_machine/cyclic_station_eligibility_review_loop
    """
    ctx = setup_review_loop_station()
    station_id = ctx["station"]["id"]
    get_success_data(api_client.record_deficiency(
        station_id, {"deficiency_factors": ["NEWSROOM_STAFF"]}, AUDITOR))
    get_success_data(api_client.remediation(
        station_id, {"remediated_factors": ["NEWSROOM_STAFF"]}, ctx["headers"]))
    resp = api_client.submit_eligibility(station_id, ctx["headers"])
    data = get_success_data(resp)

    assert data["eligibility_status"] == "UNDER_REVIEW", (
        f"the loop should close back at UNDER_REVIEW, got {data['eligibility_status']}"
    )


def test_probation_and_restore_close_the_standing_cycle():
    """PRD §3.1: "The `ELIGIBLE`-to-`PROBATION`-to-`ELIGIBLE` pair is the cyclic
    heart of station standing, and both directions require the same auditor
    authority."

    The restore floor of 55.00 is cleared because the station's coverage, staffing
    and newsroom inputs yield an operations score of 71.60.

    Design: Difficulty/non_linear_state_machine/cyclic_station_eligibility_review_loop
    """
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(
        call_sign="WUNC", licensee_name="Piedmont Licensee", state_code="NC",
        dma_market_rank=27, dma_households=2000000, coverage_population=600000,
        full_time_staff_count=20, newsroom_staff_count=6,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH")
    on_probation = get_success_data(api_client.probation(
        station["id"], {"reason_code": "AUDIT_FINDING"}, AUDITOR))
    assert on_probation["eligibility_status"] == "PROBATION"

    restored = get_success_data(api_client.restore_eligibility(station["id"], AUDITOR))
    assert restored["eligibility_status"] == "ELIGIBLE", (
        f"the revert edge should return the station to ELIGIBLE, "
        f"got {restored['eligibility_status']}"
    )


def setup_scheduled_underwriting():
    """An agreement in SCHEDULED with a two-segment airplay requirement."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**UNDERWRITING_STATION)
    agreement = get_success_data(api_client.create_underwriting(
        {
            "sponsor_name": "Cascade Coffee Roasters",
            "station_id": station["id"],
            "program_code": "NP-1002",
            "ack_script_text": "Support for this program comes from Cascade Coffee Roasters",
            "consideration_cents": 250000,
            "compliance_segment_count": 2,
        },
        UNDERWRITING), 201)
    get_success_data(api_client.submit_underwriting_review(agreement["id"], UNDERWRITING))
    get_success_data(api_client.approve_underwriting(agreement["id"], AUDITOR))
    scheduled = get_success_data(api_client.schedule_underwriting(agreement["id"], UNDERWRITING))
    return {"station": station, "agreement": scheduled}


def test_first_air_segment_starts_the_airing_self_loop():
    """PRD §3.8: "Recording a segment on a `SCHEDULED` agreement requires the
    `aired_segment_count` to be below `compliance_segment_count`, increments the
    count by one, moves the agreement to `AIRING`, and advances the airplay
    dimension from `SLOTTED` to `PARTIALLY_AIRED` when segments remain or
    directly to `FULLY_AIRED` when the increment has brought the count up to the
    required total."

    Design: Difficulty/non_linear_state_machine/parallel_underwriting_agreement_dimensions
    """
    ctx = setup_scheduled_underwriting()
    data = get_success_data(api_client.air_segment(ctx["agreement"]["id"], UNDERWRITING))

    assert data["agreement_status"] == "AIRING", (
        f"expected AIRING after the first segment, got {data['agreement_status']}"
    )
    assert data["aired_segment_count"] == 1
    assert data["airplay_status"] == "PARTIALLY_AIRED", (
        f"one segment of two should read PARTIALLY_AIRED, got {data['airplay_status']}"
    )


def test_second_air_segment_completes_airplay_while_status_settles():
    """PRD §3.8: "Recording a further segment while already `AIRING` requires the
    count to be above zero and still below the required total; it increments the
    count and leaves the agreement in `AIRING`".
    PRD §3.8: "When the `aired_segment_count` reaches the `compliance_segment_count`,
    the agreement completes and moves to `AIRING_COMPLETE`, a terminal state."
    PRD §3.8: "an implementation that folds them into a single field cannot
    represent an agreement that is `AIRING` while still only `PARTIALLY_AIRED`".

    Design: Difficulty/non_linear_state_machine/parallel_underwriting_agreement_dimensions
    """
    ctx = setup_scheduled_underwriting()
    get_success_data(api_client.air_segment(ctx["agreement"]["id"], UNDERWRITING))
    data = get_success_data(api_client.air_segment(ctx["agreement"]["id"], UNDERWRITING))

    assert data["aired_segment_count"] == 2
    assert data["agreement_status"] == "AIRING_COMPLETE", (
        f"the count reaching the requirement should complete the agreement, "
        f"got {data['agreement_status']}"
    )
    assert data["airplay_status"] == "FULLY_AIRED", (
        f"the airplay dimension should read FULLY_AIRED, got {data['airplay_status']}"
    )