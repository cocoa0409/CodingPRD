"""Corner-design translations: deterministic validation ordering.

PRD §2.10 pins the evaluation order of the ten validation gates in prose;
these tests exercise the two orderings §2.10 states explicitly: payload shape
before existence, and reservation quota before barrel eligibility.
"""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    NON_EXISTENT_UUID,
    create_assessment_payload,
    create_commissioned_rickhouse,
    create_program,
    create_reservation,
    create_reservation_payload,
    fill_mature_barrel,
    fill_placed_barrel,
    get_program_fresh,
    set_clock,
    validate_error,
    validate_paginated,
)


def test_payload_validation_beats_existence(api, warehouse_manager_headers):
    """PRD §2.10: "An earlier gate masks every later one. A malformed body on a
    non-existent resource returns `ERR_VALIDATION`, never `ERR_NOT_FOUND`."
    PRD §2.8: "Payload-shape validation runs before any of these existence
    checks (§2.10), so a malformed body draws `ERR_VALIDATION` even when its
    identifiers would not have resolved."

    Design: Corner/validations/payload_validation_beats_existence
    """
    set_clock(DEFAULT_CLOCK_ISO)

    # The path barrel does not exist AND the body's kind enum is invalid;
    # gate 3 (payload shape) must mask gate 4 (existence).
    resp = api.create_barrel_assessment(
        NON_EXISTENT_UUID,
        create_assessment_payload("BOGUS_KIND"),
        warehouse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_reservation_quota_checked_before_eligibility(api, program_director_headers):
    """PRD §2.10: "Within gate 8 the reservation quota is examined before barrel
    eligibility, so an exhausted program answers `ERR_RESERVATION_QUOTA_EXHAUSTED`
    even when the named barrel would also fail eligibility."
    PRD §3.6: "Within the conflict checks, quota comes before eligibility: when
    `available_slots` has reached zero the reservation is rejected with
    `ERR_RESERVATION_QUOTA_EXHAUSTED` (HTTP 409) before the barrel is even
    examined; only then does a barrel failing the eligibility predicate above
    draw `ERR_BARREL_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/reservation_quota_checked_before_eligibility
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=2, name="RH-V2",
    )
    mature = fill_mature_barrel(ctx["slots"][0]["id"])  # MATURE_ELIGIBLE at fill
    aging = fill_placed_barrel(ctx["slots"][1]["id"], min_maturation_months=48)  # AGING
    program = create_program(
        name="Quota First", min_quality_score=0,
        required_barrel_count=1, reservation_window_days=45,
    )
    reservation = create_reservation(program["id"], mature["id"])
    assert reservation["state"] == "ACTIVE"
    assert get_program_fresh(program["id"])["available_slots"] == 0, (
        "Setup failed: the single quota slot should be consumed"
    )

    # Fresh expected_program_version (PRD §2.7): the OCC gate passes, so the
    # quota-vs-eligibility ordering inside gate 8 decides the error.
    program_now = get_program_fresh(program["id"])
    resp = api.create_reservation(
        program["id"],
        create_reservation_payload(aging["id"], program_now["version"]),
        program_director_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_QUOTA_EXHAUSTED)

    data, _meta = validate_paginated(
        api.list_barrel_reservations(aging["id"], program_director_headers)
    )
    assert data == [], "no reservation was created for the ineligible barrel"
