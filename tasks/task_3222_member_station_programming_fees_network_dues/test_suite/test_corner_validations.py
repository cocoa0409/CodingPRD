"""Validation rules applied at their own endpoints. Queue B, section `validations`."""
from test_helpers import (
    AUDITOR,
    EDITOR,
    ApiErrorId,
    api_client,
    create_agreement,
    create_contribution,
    create_online_feed,
    create_program,
    create_window,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    move_program_premiere_ahead,
    set_clock,
    validate_error,
)

EMBARGO_STATION = dict(
    call_sign="WXXI", licensee_name="Genesee Licensee", state_code="NY",
    dma_market_rank=79, dma_households=380000, coverage_population=60000,
    full_time_staff_count=5, newsroom_staff_count=3,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST",
)

MISMATCH_STATION = dict(
    call_sign="KAZU", licensee_name="Monterey Licensee", state_code="CA",
    dma_market_rank=118, dma_households=250000, coverage_population=55000,
    full_time_staff_count=5, newsroom_staff_count=2,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)

LICENSE_STATION = dict(
    call_sign="KALW", licensee_name="Alameda Licensee", state_code="CA",
    dma_market_rank=6, dma_households=2500000, coverage_population=120000,
    full_time_staff_count=9, newsroom_staff_count=5,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)


def test_clearance_request_before_the_premiere_instant_is_refused():
    """PRD §3.3: "it re-applies the embargo rule so a window carrying an
    as-yet-unpremiered program cannot even be submitted."

    The window is created while the premiere instant still lies in the future,
    so creation succeeds; the premiere is then moved ahead of the window's start
    and the clearance request re-applies the rule and is refused.

    Design: Corner/validations/embargo_window_before_premiere_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**EMBARGO_STATION)
    headers = make_station_manager_headers(station["id"])
    # PRD §3.6: `clearance_required` is optional and defaults to true; the
    # window here is deliberately still a draft, so the gate is skipped to keep
    # the premiere walk independent of the clearance under test.
    program = create_program(program_code="NP-1012", program_title="Genesee Valley Hour",
                             strand_type="CULTURE", clearance_required=False,
                             national_premiere_at="2026-09-10T00:00:00Z")
    agreement = create_agreement(station, program_code=program["program_code"])
    window = create_window(agreement, station,
                           window_start="2026-09-20T14:00:00Z",
                           window_end="2026-09-20T15:00:00Z")
    get_success_data(api_client.submit_agreement(agreement["id"], headers))
    # PRD §3.6: `reschedule-airings` moves a published program's premiere, so the
    # program is walked through production and publication first. The premiere
    # then lands past the window's start, which is what the clearance request
    # re-applies — nothing else about the window changes.
    move_program_premiere_ahead(program, "2026-09-25T00:00:00Z",
                                station=station, headers=headers)

    resp = api_client.request_clearance(window["id"], headers)
    validate_error(resp, ApiErrorId.ERR_EMBARGO_VIOLATION)

    data = get_success_data(api_client.get_window(window["id"], AUDITOR))
    assert data["clearance_status"] == "DRAFT", (
        f"the refused request must leave the window in DRAFT, got {data['clearance_status']}"
    )


def test_window_declaring_an_unreached_embargo_instant_is_refused():
    """PRD §3.3: "if an `embargo_until` is declared the window must not start
    before it".

    The window is created while the declared embargo instant is still ahead of
    it, and the premiere is then moved past the window's start; the clearance
    request re-applies the embargo rule and is refused.

    Design: Corner/validations/embargo_window_before_premiere_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**EMBARGO_STATION)
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1013", program_title="Genesee Late Hour",
                             strand_type="CULTURE", clearance_required=False,
                             national_premiere_at="2026-09-10T00:00:00Z")
    agreement = create_agreement(station, program_code=program["program_code"])
    window = create_window(agreement, station,
                           window_start="2026-09-20T14:00:00Z",
                           window_end="2026-09-20T15:00:00Z",
                           embargo_until="2026-09-05T00:00:00Z")
    get_success_data(api_client.submit_agreement(agreement["id"], headers))
    move_program_premiere_ahead(program, "2026-09-25T00:00:00Z",
                                station=station, headers=headers)
    resp = api_client.request_clearance(window["id"], headers)

    validate_error(resp, ApiErrorId.ERR_EMBARGO_VIOLATION)


def setup_agreement_for_mismatch():
    """An agreement carrying one program code alongside a second program's code."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**MISMATCH_STATION)
    headers = make_station_manager_headers(station["id"])
    carried = create_program(program_code="NP-1014", program_title="Central Coast Journal")
    other = create_program(program_code="NP-1015", program_title="Pacific Tides",
                           strand_type="CULTURE")
    agreement = create_agreement(station, program_code=carried["program_code"])
    return {"station": station, "headers": headers, "carried": carried,
            "other": other, "agreement": agreement}


def test_window_carrying_a_foreign_program_code_is_refused():
    """PRD §3.3: "Third, the window's own `program_code` must equal its parent
    agreement's, or the request fails with `ERR_PROGRAM_CODE_MISMATCH`."

    Design: Corner/validations/program_code_mismatch_referential_violation
    """
    ctx = setup_agreement_for_mismatch()
    resp = api_client.create_window(
        {"parent_agreement_id": ctx["agreement"]["id"], "station_id": ctx["station"]["id"],
         "program_code": ctx["other"]["program_code"],
         "window_start": "2026-10-05T14:00:00Z",
         "window_end": "2026-10-05T15:00:00Z"}, ctx["headers"])

    validate_error(resp, ApiErrorId.ERR_PROGRAM_CODE_MISMATCH)


def test_window_carrying_the_parent_program_code_is_admitted():
    """PRD §3.3: "The `program_code` is the join between carriage and programming: it
    must equal the `program_code` of the `NationalProgram` the agreement carries".

    Design: Corner/validations/program_code_mismatch_referential_violation
    """
    ctx = setup_agreement_for_mismatch()
    resp = api_client.create_window(
        {"parent_agreement_id": ctx["agreement"]["id"], "station_id": ctx["station"]["id"],
         "program_code": ctx["agreement"]["program_code"],
         "window_start": "2026-10-05T14:00:00Z",
         "window_end": "2026-10-05T15:00:00Z"}, ctx["headers"])
    data = get_success_data(resp, 201)

    assert data["program_code"] == ctx["agreement"]["program_code"]


def setup_shortlisted_piece_for_suspension():
    """A SHORTLISTED piece whose originating station is then suspended."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**LICENSE_STATION)
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1016", program_title="Bay Area Brief")
    contribution = create_contribution(
        station, program, headline="Ferry terminal retrofit", duration_seconds=180)
    get_success_data(api_client.submit_contribution(contribution["id"], headers))
    get_success_data(api_client.shortlist_contribution(contribution["id"], EDITOR))
    suspended = get_success_data(api_client.suspend_station(
        station["id"], {"suspension_reason": "Dues arrears unresolved"}, AUDITOR))
    return {"station": suspended, "headers": headers, "program": program,
            "contribution": get_success_data(
                api_client.get_contribution(contribution["id"], EDITOR))}


def test_licensing_from_a_suspended_station_is_refused():
    """PRD §3.6: "Licensing a `SHORTLISTED` contribution to a program requires the
    contributing station's `eligibility_status` to be neither `SUSPENDED` nor
    `WITHDRAWN` — a suspended station's work is not purchased and the attempt
    fails with `ERR_STATION_SUSPENDED`."

    Design: Corner/validations/contribution_from_suspended_station_refused
    """
    ctx = setup_shortlisted_piece_for_suspension()
    assert ctx["contribution"]["contribution_status"] == "SHORTLISTED"
    program = get_success_data(api_client.get_program(ctx["program"]["id"], EDITOR))

    resp = api_client.license_contribution(
        ctx["contribution"]["id"],
        {"expected_program_version": program["version"]}, EDITOR)

    validate_error(resp, ApiErrorId.ERR_STATION_SUSPENDED)


def test_a_refused_license_leaves_the_piece_shortlisted():
    """PRD §3.6: "the attempt fails with `ERR_STATION_SUSPENDED`".

    The refusal must be atomic — the piece keeps the status it held.

    Design: Corner/validations/contribution_from_suspended_station_refused
    """
    ctx = setup_shortlisted_piece_for_suspension()
    program = get_success_data(api_client.get_program(ctx["program"]["id"], EDITOR))
    api_client.license_contribution(
        ctx["contribution"]["id"],
        {"expected_program_version": program["version"]}, EDITOR)

    after = get_success_data(api_client.get_contribution(ctx["contribution"]["id"], EDITOR))
    assert after["contribution_status"] == "SHORTLISTED", (
        f"a refused licence must not move the piece, got {after['contribution_status']}"
    )


def setup_feed_with_four_windows():
    """An ONLINE feed plus four non-overlapping windows under one agreement."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(
        call_sign="WITF", licensee_name="Susquehanna Licensee", state_code="PA",
        dma_market_rank=44, dma_households=620000, coverage_population=70000,
        full_time_staff_count=6, newsroom_staff_count=3,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST")
    headers = make_station_manager_headers(station["id"])
    feed = create_online_feed(feed_code="FEED-C003", feed_type="HYBRID",
                              total_capacity_units=20)
    program = create_program(program_code="NP-1017", program_title="Susquehanna Notebook",
                             strand_type="TALK")
    agreement = create_agreement(station, program_code=program["program_code"])
    windows = [
        create_window(agreement, station,
                      window_start=f"2026-10-05T{8 + 2 * i:02d}:00:00Z",
                      window_end=f"2026-10-05T{9 + 2 * i:02d}:00:00Z")
        for i in range(4)
    ]
    return {"station": station, "headers": headers, "feed": feed,
            "agreement": agreement, "windows": windows}


def test_a_block_carrying_four_reservations_is_refused_whole():
    """PRD §3.4: "A block capability reserves up to three slots in one best-effort
    request through the `reservations` payload; a block carrying more than three
    is refused whole with `ERR_SLOT_REQUEST_LIMIT_EXCEEDED` rather than partially
    applied."

    Design: Corner/validations/block_reservation_over_limit_refused
    """
    ctx = setup_feed_with_four_windows()
    reservations = [
        {"parent_feed_id": ctx["feed"]["id"], "station_id": ctx["station"]["id"],
         "window_id": window["id"],
         "slot_start": window["window_start"], "slot_end": window["window_end"],
         "priority_rank": 3}
        for window in ctx["windows"]
    ]
    resp = api_client.block_slots({"reservations": reservations}, ctx["headers"])

    validate_error(resp, ApiErrorId.ERR_SLOT_REQUEST_LIMIT_EXCEEDED)


def test_a_block_of_three_reservations_is_admitted():
    """PRD §3.4: "A block capability reserves up to three slots in one best-effort
    request through the `reservations` payload".

    Design: Corner/validations/block_reservation_over_limit_refused
    """
    ctx = setup_feed_with_four_windows()
    reservations = [
        {"parent_feed_id": ctx["feed"]["id"], "station_id": ctx["station"]["id"],
         "window_id": window["id"],
         "slot_start": window["window_start"], "slot_end": window["window_end"],
         "priority_rank": 3}
        for window in ctx["windows"][:3]
    ]
    resp = api_client.block_slots({"reservations": reservations}, ctx["headers"])
    data = get_success_data(resp)

    assert len(data) == 3, f"three reservations should yield three slots, got {len(data)}"