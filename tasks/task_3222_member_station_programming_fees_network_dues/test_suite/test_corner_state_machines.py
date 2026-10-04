"""Initial states, terminal lockdown and idempotency. Queue B, section `state_machines`."""
from test_helpers import (
    AUDITOR,
    ApiErrorId,
    api_client,
    create_program,
    create_station,
    create_window,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    move_program_premiere_ahead,
    refresh_window,
    set_clock,
    validate_error,
)

WINDOW_STATION = dict(
    call_sign="KCPW", licensee_name="Wasatch Licensee", state_code="UT",
    dma_market_rank=33, dma_households=900000, coverage_population=75000,
    full_time_staff_count=6, newsroom_staff_count=3,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)

IDEMPOTENT_STATION = dict(
    call_sign="KVNO", licensee_name="Prairie Licensee", state_code="NE",
    dma_market_rank=76, dma_households=400000, coverage_population=60000,
    full_time_staff_count=5, newsroom_staff_count=3,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST",
)


def test_withdrawing_an_applicant_lands_it_in_the_terminal_state():
    """PRD §3.1: "A station manager may withdraw a station in `APPLICANT` or in
    `DEFICIENT`, and the move lands in `WITHDRAWN`, one of the two states from
    which no further transition is admitted for this lifecycle."

    Design: Corner/state_machines/station_initial_state_and_terminal_lockdown
    """
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(
        call_sign="KUSC", licensee_name="Angeles Licensee", state_code="CA",
        dma_market_rank=2, dma_households=5200000, coverage_population=100,
        full_time_staff_count=12, newsroom_staff_count=4,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST")
    assert station["eligibility_status"] == "APPLICANT"

    withdrawn = get_success_data(api_client.withdraw_station(
        station["id"], make_station_manager_headers(station["id"])))

    assert withdrawn["eligibility_status"] == "WITHDRAWN", (
        f"withdrawal should land in WITHDRAWN, got {withdrawn['eligibility_status']}"
    )


def test_no_transition_is_admitted_from_the_withdrawn_state():
    """PRD §3.1: "`WITHDRAWN` is terminal; a request that attempts any station
    transition against it fails with `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/station_initial_state_and_terminal_lockdown
    """
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(
        call_sign="KUSC", licensee_name="Angeles Licensee", state_code="CA",
        dma_market_rank=2, dma_households=5200000, coverage_population=100,
        full_time_staff_count=12, newsroom_staff_count=4,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST")
    headers = make_station_manager_headers(station["id"])
    get_success_data(api_client.withdraw_station(station["id"], headers))

    resp = api_client.submit_eligibility(station["id"], headers)

    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def setup_elastic_window():
    """A window under a program whose premiere instant has not yet arrived.

    The premiere is initially placed before the window, so the window is created
    and cleared freely. It is then moved ahead of the window's start via
    `reschedule-airings`, which puts the window inside a live premiere embargo
    without changing its shape.
    """
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**WINDOW_STATION)
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1009", program_title="Wasatch Front Report",
                             national_premiere_at="2026-10-01T00:00:00Z")
    agreement = get_success_data(api_client.create_agreement(
        {"station_id": station["id"], "program_code": program["program_code"],
         "obligation_type": "MANDATORY", "clearance_deadline": "2026-11-01T00:00:00Z",
         "exception_liability_cap_cents": 500000}, headers), 201)
    window = create_window(agreement, station,
                           window_start="2026-10-05T14:00:00Z",
                           window_end="2026-10-05T15:00:00Z")
    get_success_data(api_client.submit_agreement(agreement["id"], headers))
    get_success_data(api_client.review_agreement(agreement["id"], AUDITOR))
    get_success_data(api_client.request_clearance(window["id"], headers))
    get_success_data(api_client.clear_window(window["id"], AUDITOR))
    set_clock("2026-09-01T00:00:00Z")
    program = move_program_premiere_ahead(
        program, "2026-10-20T00:00:00Z", station=station, headers=headers)
    return {"station": station, "headers": headers, "program": program,
            "agreement": agreement, "window": refresh_window(window)}


def test_embargo_sweep_voids_a_window_cleared_before_the_premiere():
    """PRD §3.5: "it scans every window in `CLEARED` status whose start precedes its
    program's premiere instant, voids the early ones on the same basis".

    Design: Corner/state_machines/window_invalid_transition_from_terminal_violated
    """
    ctx = setup_elastic_window()
    resp = api_client.series_embargo_check(AUDITOR)
    get_success_data(resp)

    data = get_success_data(api_client.get_window(ctx["window"]["id"], AUDITOR))
    assert data["clearance_status"] == "VIOLATED", (
        f"the early window should be voided by the sweep, got {data['clearance_status']}"
    )
    assert data["rejection_reason"] == "PREMIERE_EMBARGO", (
        f"the sweep should stamp the premiere embargo reason, "
        f"got {data.get('rejection_reason')!r}"
    )


def test_voided_window_admits_no_further_transition():
    """PRD §3.3: "Rejection is reversible: the station manager may return a
    `REJECTED` window to `DRAFT` for another clearance pass".
    PRD §2.9: "a resource already in a terminal state fails with
    `ERR_ALREADY_TERMINAL` (409)".

    The revert edge is defined from REJECTED, not from the terminal VIOLATED
    state, so the attempt is refused.

    Design: Corner/state_machines/window_invalid_transition_from_terminal_violated
    """
    ctx = setup_elastic_window()
    get_success_data(api_client.series_embargo_check(AUDITOR))
    resp = api_client.remediating_window(ctx["window"]["id"], ctx["headers"])

    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_voided_window_accrues_the_coverage_breach_surcharge():
    """PRD §3.5: "A sixty-minute window in `VIOLATED` state therefore breaches at
    6000 basis points and accrues 75000 cents plus 45000 cents, or 120000 cents."

    The swept window runs the hour from 14:00 to 15:00, so its runtime is sixty
    whole minutes.

    Design: Corner/state_machines/window_invalid_transition_from_terminal_violated
    """
    ctx = setup_elastic_window()
    get_success_data(api_client.series_embargo_check(AUDITOR))
    data = get_success_data(api_client.get_window(ctx["window"]["id"], AUDITOR))

    assert data["carriage_exception_liability_cents"] == 120000, (
        f"a sixty-minute violation should accrue 120000 cents, "
        f"got {data['carriage_exception_liability_cents']}"
    )


def setup_cleared_window():
    """A window already advanced to CLEARED under a reviewed agreement."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**IDEMPOTENT_STATION)
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1010", program_title="Platte River Journal")
    agreement = get_success_data(api_client.create_agreement(
        {"station_id": station["id"], "program_code": program["program_code"],
         "obligation_type": "MANDATORY", "clearance_deadline": "2026-11-01T00:00:00Z",
         "exception_liability_cap_cents": 500000}, headers), 201)
    window = create_window(agreement, station,
                           window_start="2026-10-05T14:00:00Z",
                           window_end="2026-10-05T15:00:00Z")
    get_success_data(api_client.submit_agreement(agreement["id"], headers))
    get_success_data(api_client.review_agreement(agreement["id"], AUDITOR))
    get_success_data(api_client.request_clearance(window["id"], headers))
    cleared = get_success_data(api_client.clear_window(window["id"], AUDITOR))
    return {"station": station, "headers": headers, "agreement": agreement,
            "window": cleared}


def test_clearing_a_window_marks_it_cleared_and_raises_its_flag():
    """PRD §3.3: "A compliance auditor then clears a `PENDING_CLEARANCE` window,
    moving it to `CLEARED`, and this is the operation that sets `is_cleared` true".

    Design: Corner/state_machines/window_idempotent_second_clear_refused
    """
    ctx = setup_cleared_window()

    assert ctx["window"]["clearance_status"] == "CLEARED"
    assert ctx["window"]["is_cleared"] is True, (
        "clearing the window must raise its flag"
    )


def test_clearing_the_same_window_again_is_refused():
    """PRD §2.9: "A resource not in the required from-state, or failing a declared
    precondition on its transition, fails with `ERR_INVALID_STATE` (409)".

    The clear transition is defined from PENDING_CLEARANCE, so a second attempt
    against a window already CLEARED cannot re-fire its side effects.

    Design: Corner/state_machines/window_idempotent_second_clear_refused
    """
    ctx = setup_cleared_window()
    resp = api_client.clear_window(ctx["window"]["id"], AUDITOR)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)