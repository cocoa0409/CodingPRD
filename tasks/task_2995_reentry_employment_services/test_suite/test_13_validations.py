"""
Refusals, and the state that must survive them.

A refusal is only half of each claim here: the other half is that nothing moved.
Every test names the one code the PRD demands, then re-reads the rows the rejected
write would have touched and shows the counters, the money and the state dimensions
exactly where they were.
"""

from test_helpers.api_errors import (
    ERR_DUPLICATE_PLACEMENT,
    ERR_FIDELITY_BOND_UNAVAILABLE,
    ERR_GRANT_FUNDS_INSUFFICIENT,
    ERR_MILESTONE_NOT_REACHED,
    ERR_PARTICIPANT_CAP_EXCEEDED,
    ERR_SESSION_ALREADY_STARTED,
    ERR_SESSION_FULL,
    ERR_SHIFT_IN_PAST,
    ERR_SUBSIDY_CAP_EXCEEDED,
    ERR_UNAUTHENTICATED,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_all_null,
    assert_int_field,
    assert_ledger_identity,
    assert_money_cents,
    assert_session_seat_identity,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    BONDING_NONE,
    BONDING_REQUESTED,
    CATEGORY_TOOLS,
    EMPLOYMENT_OFFERED,
    ENROLLMENT_ENROLLED,
    FUNDING_POSTURE_OPEN,
    MILESTONE_DAYS_VALUES,
    OPENING_OPEN,
    PARTNERSHIP_ACTIVE,
    RECIDIVISM_NONE,
    RECORD_DRUG_OFFENSE,
    RETENTION_RETAINED,
    ROLE_CASE_MANAGER,
    SESSION_SCHEDULED,
    SESSION_TYPE_DIGITAL_LITERACY,
    SESSION_TYPE_RESUME_LAB,
    STAGE_PLACED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    headers_with_empty_user_id,
)


def _subsidised_placement(api, build, authorized_cents=30000, opening=None, **opening_overrides):
    """An active, subsidised placement whose participant may legally work 08:00-17:00."""
    grant = build.grant(
        authorized_cents=authorized_cents, per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    partnership = build.partnership_active()
    if opening is None:
        opening = build.job_opening(partnership["id"], **opening_overrides)
    participant = build.participant_released()
    build.case_authorized(participant["id"], 480, 1020)
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])
    return grant, participant, opening, placement


def test_a_blank_user_identifier_is_unauthenticated_before_anything_else_is_read(
    api, build
):
    """
    The header is present but empty, and that alone settles the request: an
    otherwise perfect create is a 401 rather than a 422 or a 403.

    PRD section 2.1: "Authentication is the very first gate, evaluated before
    request-body parsing, before path resolution, and before any role check. If
    `X-User-ID` is absent, or present but an empty string, the request is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/request_with_a_blank_x_user_id_header_is_unauthenticated
    """
    blank = headers_with_empty_user_id(ROLE_CASE_MANAGER)
    assert blank["X-User-ID"] == ""

    refused = api.create_participant(f.participant_payload(), blank)
    validate_error(refused, ERR_UNAUTHENTICATED, 401)

    rows, meta = validate_paginated(
        api.list_participants(CASE_MANAGER, f.page_params(limit=10, offset=0))
    )
    assert meta["total_count"] == 0


def test_a_page_size_of_one_hundred_and_one_is_refused_rather_than_clamped(api, build):
    """
    The maximum page size is a validation bound, not a ceiling the server quietly
    applies: 101 is refused outright while 100 is served.

    PRD section 2.3: "Every list endpoint accepts two optional query parameters.
    `limit` defaults to 10 when omitted, has a minimum of 1 and a maximum of 100.
    `offset` defaults to 0 when omitted and has a minimum of 0; no upper bound applies
    to it. A `limit` below 1, a `limit` above 100, an `offset` below 0, or a
    non-integer value for either parameter is refused with `ERR_VALIDATION` (HTTP
    422)."

    Design: Corner/validations/pagination_limit_above_one_hundred_is_rejected
    """
    build.participant()
    build.participant(full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE])

    refused = api.list_participants(CASE_MANAGER, f.page_params(limit=101, offset=0))
    validate_error(refused, ERR_VALIDATION, 422)
    body = refused.json()
    assert not isinstance(body["data"], list), "a refused page must not return rows"
    assert body["response_type"] == "error"

    rows, meta = validate_paginated(
        api.list_participants(CASE_MANAGER, f.page_params(limit=100, offset=0))
    )
    assert meta["total_count"] == 2
    assert meta["limit"] == 100
    assert len(rows) == 2


def test_a_domain_score_of_five_refuses_the_whole_assessment(api, build):
    """
    One out-of-range domain is not clamped and the other four are not scored: the
    participant is left unassessed and its version does not move.

    PRD section 3.1: "The case manager submits `assessment_domain_scores`, an object
    carrying exactly five keys — `housing_score`, `transportation_score`,
    `health_score`, `work_history_score`, and `documentation_score` — each of which
    must be an integer from 0 through 4 inclusive. Omitting any of the five keys,
    carrying a key outside that set, or holding a value that is not an integer within 0
    through 4 is refused with `ERR_VALIDATION`."

    Design: Corner/validations/assessment_domain_score_outside_zero_to_four_is_rejected
    """
    participant = build.participant()

    refused = api.record_assessment(
        participant["id"],
        f.assessment_payload(housing=5, transportation=2, health=1, work_history=4, documentation=2),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_VALIDATION, 422)

    unchanged = validate_unpaginated(api.get_participant(participant["id"], CASE_MANAGER))
    assert_all_null(
        unchanged, ["barrier_score", "barrier_tier", "assessment_domain_scores"]
    )
    assert_int_field(unchanged, "version", 1)


def test_a_repeated_record_category_is_refused_rather_than_de_duplicated(api, build):
    """
    Both elements are legal enum members, yet the array constraint forbids the
    repetition, and the server does not quietly collapse it.

    PRD section 3.1: "`record_categories` lists the participant's conviction
    categories and must be a non-empty array drawn from `DRUG_OFFENSE`,
    `PROPERTY_OFFENSE`, `VIOLENT_OFFENSE`, `FINANCIAL_OFFENSE`, `DUI`, and `OTHER`,
    with no value repeated."

    Design: Corner/validations/duplicate_record_category_is_rejected
    """
    refused = api.create_participant(
        f.participant_payload(
            record_categories=[RECORD_DRUG_OFFENSE, RECORD_DRUG_OFFENSE]
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_VALIDATION, 422)

    rows, meta = validate_paginated(api.list_participants(CASE_MANAGER))
    assert meta["total_count"] == 0


def test_a_shift_dated_yesterday_is_refused_as_past_not_as_out_of_window(api, build):
    """
    The July shift's minute-of-day span sits comfortably inside the approved 08:00
    to 17:00 window, so the only thing wrong with it is the day — and the code says so.

    PRD section 3.7: "The shift must be in the future: a `starts_at` at or before the
    logical clock's current UTC instant is refused with `ERR_SHIFT_IN_PAST`, so a shift
    beginning at exactly the current instant is not allowed."

    Design: Corner/validations/shift_starting_before_the_logical_clock_is_rejected
    """
    grant, participant, opening, placement = _subsidised_placement(api, build)

    refused = api.create_work_shift(
        placement["id"],
        f.work_shift_payload("2026-07-31T09:00:00.000Z", "2026-07-31T13:00:00.000Z"),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_SHIFT_IN_PAST, 409)

    rows, meta = validate_paginated(
        api.list_placement_work_shifts(placement["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 0

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(stored, "projected_subsidy_cents", 0)


def test_enrolling_at_the_very_instant_a_session_starts_is_too_late(api, build, clock):
    """
    The clock sits exactly on `starts_at`, and the strict comparison refuses the
    enrollment even though the session is still scheduled with every seat free.

    PRD section 3.5: "the session's `starts_at` must be strictly later than the
    logical clock, so a session whose `starts_at` is at or before the current instant
    is refused with `ERR_SESSION_ALREADY_STARTED`"

    Design: Corner/validations/enrolling_after_the_session_has_started_is_rejected
    """
    participant = build.participant()
    session = build.readiness_session(
        session_type=SESSION_TYPE_RESUME_LAB,
        coach_user_id="coach-1",
        starts_at="2026-08-05T13:00:00.000Z",
        ends_at="2026-08-05T15:00:00.000Z",
        seat_capacity=3,
    )
    clock.set("2026-08-05T13:00:00.000Z")

    refused = api.create_enrollment(
        session["id"], f.enrollment_payload(participant["id"], False), CASE_MANAGER
    )
    validate_error(refused, ERR_SESSION_ALREADY_STARTED, 409)

    stored = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert stored["status"] == SESSION_SCHEDULED
    assert_int_field(stored, "enrolled_count", 0)
    assert_int_field(stored, "remaining_seats", 3)
    assert_session_seat_identity(stored)

    rows, meta = validate_paginated(api.list_enrollments(CASE_MANAGER))
    assert meta["total_count"] == 0


def test_a_thirty_day_check_two_days_in_is_refused_and_records_nothing(api, build, clock):
    """
    The milestone is measured from the placement's own start date, so a check on the
    fifth of the month cannot answer for the thirtieth day, and the placement keeps its
    empty retention columns.

    PRD section 3.9: "The milestone must genuinely have elapsed: when the logical
    clock is earlier than the placement's `start_date` plus `milestone_days` days, the
    check is refused with `ERR_MILESTONE_NOT_REACHED`, so a placement that started on
    the first of the month cannot record a thirty-day outcome until the clock reaches
    the thirty-first."

    Design: Corner/validations/retention_check_before_the_milestone_elapses_is_rejected
    """
    grant, participant, opening, placement = _subsidised_placement(api, build)
    assert placement["start_date"] == "2026-08-03"
    clock.set("2026-08-05T09:00:00.000Z")

    refused = api.record_retention_check(
        placement["id"],
        f.retention_check_payload(MILESTONE_DAYS_VALUES[0], RETENTION_RETAINED),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_MILESTONE_NOT_REACHED, 409)

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_all_null(stored, ["retention_30_outcome", "last_retention_check_at"])
    assert stored["recidivism_event"] == RECIDIVISM_NONE

    stored_participant = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert stored_participant["stage"] == STAGE_PLACED


def test_the_second_enrollment_on_a_single_seat_session_is_refused(api, build):
    """
    Each enrollment is legal on its own; it is the aggregate against a capacity of
    one that fails, and the refusal leaves the first enrollment and its seat alone.

    PRD section 3.5: "`remaining_seats` must be greater than 0, else
    `ERR_SESSION_FULL`"

    Design: Corner/validations/enrolling_into_a_full_session_is_rejected
    """
    first_participant = build.participant()
    second_participant = build.participant(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    session = build.readiness_session(
        session_type=SESSION_TYPE_DIGITAL_LITERACY,
        coach_user_id="coach-1",
        starts_at="2026-08-06T13:00:00.000Z",
        ends_at="2026-08-06T15:00:00.000Z",
        seat_capacity=1,
    )
    first = build.enrollment(session["id"], first_participant["id"])

    refused = api.create_enrollment(
        session["id"], f.enrollment_payload(second_participant["id"]), CASE_MANAGER
    )
    validate_error(refused, ERR_SESSION_FULL, 409)

    stored = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert_int_field(stored, "enrolled_count", 1)
    assert_int_field(stored, "remaining_seats", 0)
    assert_session_seat_identity(stored)

    survivor = validate_unpaginated(api.get_enrollment(first["id"], CASE_MANAGER))
    assert survivor["status"] == ENROLLMENT_ENROLLED

    rows, meta = validate_paginated(
        api.list_session_enrollments(session["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 1


def test_the_fifteenth_shift_breaks_the_per_placement_subsidy_ceiling(api, build):
    """
    Fourteen eight-hour shifts at 2,500 cents an hour land exactly on the 120,000-cent
    ceiling, which is allowed; the fifteenth would make 125,000 and is refused even
    though the grant still holds millions.

    PRD section 3.7: "If the placement's `projected_subsidy_cents`, recomputed with
    the new shift included, would exceed the per-placement subsidy ceiling of 120,000
    cents — twelve hundred dollars of subsidy per placement — the shift is refused with
    `ERR_SUBSIDY_CAP_EXCEEDED`."

    Ten shifts fill the fifty-percent tier at 10,000 each and the next four earn 5,000
    each in the twenty-five-percent tier, for exactly 120,000.

    Design: Corner/validations/fifteenth_eight_hour_shift_breaks_the_placement_subsidy_cap
    """
    grant, participant, opening, placement = _subsidised_placement(
        api, build, authorized_cents=5000000, hourly_wage_cents=2500, weekly_hours=40
    )
    for day in range(3, 17):
        build.work_shift(
            placement["id"],
            f"2026-08-{day:02d}T09:00:00.000Z",
            f"2026-08-{day:02d}T17:00:00.000Z",
        )

    refused = api.create_work_shift(
        placement["id"],
        f.work_shift_payload("2026-08-17T09:00:00.000Z", "2026-08-17T17:00:00.000Z"),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_SUBSIDY_CAP_EXCEEDED, 409)

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(stored, "projected_subsidy_cents", 120000)

    rows, meta = validate_paginated(
        api.list_placement_work_shifts(placement["id"], CASE_MANAGER, f.page_params(limit=100))
    )
    assert meta["total_count"] == 14

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 120000)
    assert_money_cents(ledger, "available_cents", 4880000)
    assert_ledger_identity(ledger)


def test_a_shift_the_grant_cannot_afford_is_refused_on_funds_not_on_the_cap(api, build):
    """
    The shift is legal against its placement and against its supervision window; it
    is the grant's 5,000-cent balance that cannot carry the 7,400-cent increase, and the
    120,000-cent placement ceiling is nowhere near.

    PRD section 3.7: "And if the increase in `projected_subsidy_cents` that the new
    shift would cause exceeds the funding grant's `available_cents`, the shift is
    refused with `ERR_GRANT_FUNDS_INSUFFICIENT`."

    Design: Corner/validations/shift_projection_beyond_the_grants_available_funds_is_rejected
    """
    grant, participant, opening, placement = _subsidised_placement(
        api, build, authorized_cents=5000
    )

    refused = api.create_work_shift(
        placement["id"],
        f.work_shift_payload("2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z"),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_GRANT_FUNDS_INSUFFICIENT, 409)

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(stored, "projected_subsidy_cents", 0)

    rows, meta = validate_paginated(
        api.list_placement_work_shifts(placement["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 0

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 0)
    assert_money_cents(ledger, "available_cents", 5000)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_ledger_identity(ledger)


def test_bonding_cannot_be_requested_from_an_employer_who_carries_no_bond(api, build):
    """
    The gate reads a flag on the partnership rather than anything on the placement,
    so the same request that a bonded employer would satisfy is refused here, and both
    placement dimensions stay where they were.

    PRD section 3.6: "`NONE → REQUESTED` opens a bonding request and requires that
    `employment_status` is `OFFERED` or `ACTIVE`, so bonding may be requested while the
    offer is still outstanding; it additionally requires the employer partnership's
    `fidelity_bond_enabled` to be true, and a request against an unbonded partnership
    is refused with `ERR_FIDELITY_BOND_UNAVAILABLE`."

    Design: Corner/validations/bonding_request_without_an_employer_bond_agreement_is_rejected
    """
    grant = build.grant(authorized_cents=30000, per_participant_cap_cents=60000)
    partnership = build.partnership_active(bond_coverage_cents=None)
    assert partnership["status"] == PARTNERSHIP_ACTIVE
    assert partnership["fidelity_bond_enabled"] is False
    opening = build.job_opening(partnership["id"], requires_fidelity_bond=False)
    participant = build.participant_released()
    build.case_authorized(participant["id"], 480, 1020)
    placement = build.placement_offered(participant["id"], opening["id"], grant["id"])

    refused = api.drive_placement_bonding(
        placement["id"], f.placement_bonding_payload(BONDING_REQUESTED), EMPLOYER_LIAISON
    )
    validate_error(refused, ERR_FIDELITY_BOND_UNAVAILABLE, 409)

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert stored["bonding_status"] == BONDING_NONE
    assert stored["employment_status"] == EMPLOYMENT_OFFERED

    stored_partnership = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert stored_partnership["fidelity_bond_enabled"] is False
    assert_all_null(stored_partnership, ["bond_coverage_cents", "bond_effective_date"])


def test_a_second_offer_to_the_same_participant_on_one_opening_is_a_duplicate(api, build):
    """
    The opening still has a free seat and the version guard is satisfied, so the only
    thing wrong with the second offer is that it repeats the first — and the seat
    counters do not move.

    PRD section 3.6: "Then uniqueness: a participant who already holds a placement on
    this same opening whose `employment_status` is `OFFERED` or `ACTIVE` is refused with
    `ERR_DUPLICATE_PLACEMENT`, while a prior `DECLINED` or `SEPARATED` placement on the
    opening does not block a fresh one."

    Design: Corner/validations/second_placement_for_the_same_participant_on_one_opening_is_rejected
    """
    grant = build.grant(authorized_cents=30000, per_participant_cap_cents=60000)
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    participant = build.participant_released()
    build.case_authorized(participant["id"], 480, 1020)
    first = build.placement_offered(participant["id"], opening["id"], grant["id"])

    refused = api.create_placement(
        f.placement_payload(
            participant["id"],
            opening["id"],
            build.opening_version(opening["id"]),
            grant["id"],
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_DUPLICATE_PLACEMENT, 409)

    stored_opening = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(stored_opening, "offered_count", 1)
    assert_int_field(stored_opening, "filled_count", 0)
    assert_int_field(stored_opening, "remaining_openings", 1)
    assert stored_opening["status"] == OPENING_OPEN

    rows, meta = validate_paginated(
        api.list_placements(CASE_MANAGER, f.page_params(participant_id=participant["id"]))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_the_participant_cap_is_compared_against_the_total_charge(api, build):
    """
    Three numbers are in play and only the last one breaches a cap of 10,500: the raw
    line sum is 12,000, the coverage rate awards 10,200, and the middle-tier fee of 306
    lifts the total charge to 10,506.

    PRD section 3.8: "Take the sum of `total_charge_cents` already held by this
    participant's support requests on this same grant whose `status` is `APPROVED`,
    `DISBURSED`, `DEFERRED`, `SUBMITTED`, or `INFO_REQUESTED`, and add this request's
    own `total_charge_cents`. If that sum is strictly greater than the grant's
    `per_participant_cap_cents`, the request is refused with
    `ERR_PARTICIPANT_CAP_EXCEEDED`."

    PRD section 3.8: "One rate governs the whole request. Each line's award is then
    that line's `unit_cost_cents` multiplied by its `quantity` multiplied by the
    coverage rate, rounded half up to whole cents"

    Design: Corner/validations/per_participant_cap_compares_the_total_charge_not_the_raw_line_sum
    """
    grant = build.grant(authorized_cents=100000, per_participant_cap_cents=10500)
    participant = build.participant_zero_barrier_draft(
        record_categories=[RECORD_DRUG_OFFENSE]
    )

    refused = api.create_support_request(
        f.support_request_payload(
            participant["id"],
            grant["id"],
            build.grant_version(grant["id"]),
            [f.line_item("Framing nailer kit", 12000)],
            category=CATEGORY_TOOLS,
            justification="Tool requirement for the carpentry placement",
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_PARTICIPANT_CAP_EXCEEDED, 409)

    rows, meta = validate_paginated(
        api.list_support_requests(
            CASE_MANAGER, f.page_params(participant_id=participant["id"])
        )
    )
    assert meta["total_count"] == 0

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_int_field(ledger, "open_request_count", 0)
    assert_money_cents(ledger, "available_cents", 100000)
    assert_money_cents(ledger, "committed_cents", 0)
    assert_ledger_identity(ledger)
