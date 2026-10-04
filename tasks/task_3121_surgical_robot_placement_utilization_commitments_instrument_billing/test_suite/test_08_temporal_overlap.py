"""Temporal overlap semantics: the loaner unit's half-open buffered window, and the
day-granular closed transfer window with its three-day merge grace."""

from test_helpers import (
    TEST_USERS,
    accept_agreement,
    api_client,
    commission_system,
    create_configuration,
    create_credentialed_surgeon,
    create_loaner_dispatch_payload,
    create_review,
    create_training_record,
    create_transfer_payload,
    draft_agreement,
    drive_account_to_readiness,
    get_success_data,
    install_system,
    set_clock,
    setup_idn_pair,
    submit_agreement,
    validate_error,
    validate_success,
)


def test_loaner_dispatch_starting_exactly_at_the_buffered_end_is_accepted(api):
    """PRD §3.3: "Adjacency is permitted: a candidate starting exactly at an existing
    buffered end is not an overlap, because the interval is half-open, while a candidate
    intruding by a single minute is."

    Design: Difficulty/resource_temporal_overlap/loaner_unit_half_open_window_with_four_hour_turn_buffer
    """
    ctx = setup_idn_pair(idn_group_code="IDN-YARROW", commitment=25, region_code="WEST")
    system = _commissioned_system_under(ctx.source["id"])

    first = validate_success(api_client.create_loaner_dispatch(
        create_loaner_dispatch_payload(
            system["id"], loaner_serial_number="LOAN-77",
            dispatch_window_start_utc="2026-09-10T00:00:00Z",
            dispatch_window_end_utc="2026-09-24T00:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)

    second = validate_success(api_client.create_loaner_dispatch(
        create_loaner_dispatch_payload(
            system["id"], loaner_serial_number="LOAN-77",
            dispatch_window_start_utc="2026-09-24T04:00:00Z",
            dispatch_window_end_utc="2026-10-08T04:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)

    assert first["reservation_status"] == "PROGRAMMED"
    assert second["reservation_status"] == "PROGRAMMED"
    assert second["loaner_serial_number"] == "LOAN-77"


def test_one_minute_inside_the_buffered_end_is_a_loaner_conflict(api):
    """PRD §3.3: "the occupied interval is the dispatch start through the dispatch start plus
    14 days plus 4 hours, and a candidate dispatch on a given loaner unit is rejected with
    `ERR_LOANER_WINDOW_CONFLICT` (HTTP 409) when that buffered interval overlaps any
    non-terminal dispatch on the same `loaner_serial_number`."

    Design: Difficulty/resource_temporal_overlap/loaner_unit_half_open_window_with_four_hour_turn_buffer
    """
    ctx = setup_idn_pair(idn_group_code="IDN-YARROW", commitment=25, region_code="WEST")
    system = _commissioned_system_under(ctx.source["id"])
    validate_success(api_client.create_loaner_dispatch(
        create_loaner_dispatch_payload(
            system["id"], loaner_serial_number="LOAN-77",
            dispatch_window_start_utc="2026-09-10T00:00:00Z",
            dispatch_window_end_utc="2026-09-24T00:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)

    res = api_client.create_loaner_dispatch(
        create_loaner_dispatch_payload(
            system["id"], loaner_serial_number="LOAN-77",
            dispatch_window_start_utc="2026-09-24T03:03:00Z",
            dispatch_window_end_utc="2026-10-08T03:03:00Z"),
        TEST_USERS["service_engineer_headers"])

    validate_error(res, "ERR_LOANER_WINDOW_CONFLICT", expected_status=409)


def test_a_different_loaner_unit_may_hold_an_identical_window(api):
    """PRD §3.3: "the occupied interval is the dispatch start through the dispatch start plus
    14 days plus 4 hours, and a candidate dispatch on a given loaner unit is rejected with
    `ERR_LOANER_WINDOW_CONFLICT` (HTTP 409) when that buffered interval overlaps any
    non-terminal dispatch on the same `loaner_serial_number`."

    Design: Difficulty/resource_temporal_overlap/loaner_unit_half_open_window_with_four_hour_turn_buffer
    """
    ctx = setup_idn_pair(idn_group_code="IDN-YARROW", commitment=25, region_code="WEST")
    system = _commissioned_system_under(ctx.source["id"])
    validate_success(api_client.create_loaner_dispatch(
        create_loaner_dispatch_payload(
            system["id"], loaner_serial_number="LOAN-77",
            dispatch_window_start_utc="2026-09-10T00:00:00Z",
            dispatch_window_end_utc="2026-09-24T00:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)

    other = validate_success(api_client.create_loaner_dispatch(
        create_loaner_dispatch_payload(
            system["id"], loaner_serial_number="LOAN-88",
            dispatch_window_start_utc="2026-09-10T00:00:00Z",
            dispatch_window_end_utc="2026-09-24T00:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)

    assert other["loaner_serial_number"] == "LOAN-88", (
        "the resource key is the loaner unit, not the system"
    )


def test_transfer_window_starting_the_day_after_an_inclusive_end_is_accepted(api):
    """PRD §3.8: "That grace is a merge provision rather than a tolerance: a candidate whose
    start date falls within 3 days after an existing window's inclusive end date is merged
    into that window instead of being rejected, and the merged window then spans both."

    Design: Difficulty/resource_temporal_overlap/transfer_validity_window_closed_dates_with_three_day_merge_grace
    """
    ctx = setup_idn_pair(idn_group_code="IDN-ZEPHYR", commitment=12, region_code="SOUTH")
    first = validate_success(api_client.create_transfer(
        create_transfer_payload(ctx.source["id"], ctx.destination["id"], procedure_units=3,
                                transfer_window_start_utc="2026-09-01T00:00:00Z",
                                transfer_window_end_utc="2026-09-10T00:00:00Z"),
        TEST_USERS["idn_coordinator_headers"]), 201)
    assert first["transaction_status"] == "COMMITTED"

    second = validate_success(api_client.create_transfer(
        create_transfer_payload(ctx.source["id"], ctx.destination["id"], procedure_units=4,
                                transfer_window_start_utc="2026-09-11T00:00:00Z",
                                transfer_window_end_utc="2026-09-20T00:00:00Z"),
        TEST_USERS["idn_coordinator_headers"]), 201)

    assert second["transaction_status"] == "COMMITTED", (
        "starting the day after the existing inclusive end date merges rather than conflicts"
    )
    merged = get_success_data(api_client.list_transfers(
        TEST_USERS["idn_coordinator_headers"],
        {"destination_account_id": ctx.destination["id"]}), 200)
    windows = [(t["transfer_window_start_utc"], t["transfer_window_end_utc"])
               for t in merged]
    assert ("2026-09-11T00:00:00.000Z", "2026-09-20T00:00:00.000Z") in windows, (
        "the merged window spans both candidate windows"
    )
    assert first["id"] in [t["id"] for t in merged]


def test_a_transfer_window_nested_inside_an_existing_one_is_a_conflict(api):
    """PRD §3.8: "A candidate is rejected with `ERR_TRANSFER_WINDOW_CONFLICT` (HTTP 409) when
    any non-reversed transaction on the same `destination_account_id` has a closed window
    overlapping the candidate's, disregarding only gaps of 3 days or fewer."

    Design: Difficulty/resource_temporal_overlap/transfer_validity_window_closed_dates_with_three_day_merge_grace
    """
    ctx = setup_idn_pair(idn_group_code="IDN-ZEPHYR", commitment=12, region_code="SOUTH")
    validate_success(api_client.create_transfer(
        create_transfer_payload(ctx.source["id"], ctx.destination["id"], procedure_units=5,
                                transfer_window_start_utc="2026-09-01T00:00:00Z",
                                transfer_window_end_utc="2026-09-10T00:00:00Z"),
        TEST_USERS["idn_coordinator_headers"]), 201)

    res = api_client.create_transfer(
        create_transfer_payload(ctx.source["id"], ctx.destination["id"], procedure_units=1,
                                transfer_window_start_utc="2026-09-05T00:00:00Z",
                                transfer_window_end_utc="2026-09-08T00:00:00Z"),
        TEST_USERS["idn_coordinator_headers"])

    validate_error(res, "ERR_TRANSFER_WINDOW_CONFLICT", expected_status=409)


# ─── local helper ────────────────────────────────────────────────────────────

def _commissioned_system_under(account_id: str):
    """A commissioned system standing on the given account, built from scratch."""
    set_clock("2026-09-01T00:00:00Z")
    config = create_configuration()
    review = create_review(account_id, config["id"], verdict="PASSED")
    # Commissioning requires a CREDENTIALED surgeon on the account.
    create_credentialed_surgeon(account_id)
    account = drive_account_to_readiness(
        get_success_data(api_client.get_account(account_id, TEST_USERS["platform_admin_headers"])))
    agreement = draft_agreement(account_id, config["id"], review["id"])
    agreement = submit_agreement(agreement)
    account = get_success_data(api_client.get_account(account_id, TEST_USERS["platform_admin_headers"]))
    agreement = accept_agreement(agreement, account)
    system = get_success_data(api_client.list_agreement_robot_systems(
        agreement["id"], TEST_USERS["regional_sales_director_headers"]))[0]
    system = install_system(system)
    return commission_system(system)