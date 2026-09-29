"""Validation rules of the VoIP porting & E911 contract.

Each test drives one validation rule of the PRD to the exact point where it
bites: a natural-key collision, an ownership comparison made before the body is
read, the ladder of §2.7 stopping at its first violated rule, the inclusive edge
of a temporal span, a two-part conjunction on a remittance period, a
cross-entity identity comparison, a rule that is conditional on the destination,
a pair of refusals whose relative order is pinned by the selection step between
them, and a cumulative budget.
"""
from test_helpers import (
    CLOCK_DEFAULT_ISO,
    MATCH_POINT_WEIGHTS,
    NON_EXISTENT_UUID,
    PERFECT_MATCH_POINTS,
    PORT_RESUBMISSION_LIMIT,
    ApiErrorId,
    assert_block_census,
    assert_cents_equal,
    assert_instant,
    assert_null,
    assert_version,
    block_version,
    find_by,
    make_account_admin_headers,
    make_account_payload,
    make_call_attempt_payload,
    make_device_payload,
    make_number_reservation_payload,
    make_port_request_payload,
    make_remittance_run_payload,
    make_resubmit_payload,
    make_schedule_payload,
    post_csr_snapshot,
    post_matching_csr_snapshot,
    read_cutover_slot,
    read_device,
    read_number_block,
    read_phone_number,
    read_port_request,
    read_reservation,
    resubmit_port_request,
    seed_account,
    seed_carrier,
    seed_cutover_slot,
    seed_device,
    seed_jurisdiction,
    seed_number_block,
    seed_phone_number,
    seed_port_request,
    seed_registration,
    seed_reservation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_registration,
)


def test_reusing_an_account_number_returns_duplicate_identifier(api, platform_admin_headers):
    """A duplicate `account_number` is refused with `ERR_DUPLICATE_IDENTIFIER`, and a request for an account id that does not exist yields `ERR_ACCOUNT_NOT_FOUND`.

    Every other field of the second request is individually well formed, so the
    natural-key collision is the only thing that can refuse it.

    Design: Corner/validations/reusing_an_account_number_returns_duplicate_identifier
    """
    set_clock(CLOCK_DEFAULT_ISO)
    first = seed_account(
        "ACCT1023",
        billing_name="XANTHE LDA",
        service_state_code="CA",
        status="ACTIVE",
    )

    colliding = api.create_account(
        make_account_payload(
            "ACCT1023",
            billing_name="XANTHE TWO LDA",
            service_state_code="NV",
            status="ACTIVE",
        ),
        platform_admin_headers,
    )
    validate_error(colliding, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 409)

    stored = validate_success(api.get_account(first["id"], platform_admin_headers))
    assert stored["billing_name"] == "XANTHE LDA"
    assert stored["service_state_code"] == "CA"
    assert_version(stored, 1, "Account")


def test_account_admin_cannot_create_a_device_under_another_account(api, platform_admin_headers):
    """On creation endpoints the owning account is named in the body rather than the path — `account_id` when a port request or device is created, and the owning account of the `device_id` when a dispatchable location is captured — and the same comparison against `X-User-ID` applies to that named owner.

    Both accounts exist and are ACTIVE, so the ownership comparison is the only
    thing standing between this body and a created device.

    Design: Corner/validations/account_admin_cannot_create_a_device_under_another_account
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account_a = seed_account(
        "ACCT1024", billing_name="YARROW AS", service_state_code="CA", status="ACTIVE"
    )
    account_b = seed_account(
        "ACCT1025", billing_name="ZEPHYR AS", service_state_code="CA", status="ACTIVE"
    )

    payload = make_device_payload(
        account_b["id"],
        mac_address="AABBCC003001",
        device_type="HANDSET",
        nomadic=False,
    )
    refused = api.create_device(payload, make_account_admin_headers(account_a["id"]))
    validate_error(refused, ApiErrorId.ERR_ACCOUNT_FORBIDDEN.value, 403)

    rows, meta = validate_paginated(
        api.list_devices(platform_admin_headers, params={"account_id": account_b["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    # The identical body accepted for a role that is not ownership-scoped proves
    # the payload itself was valid.
    created = validate_success(api.create_device(payload, platform_admin_headers), 201)
    assert created["account_id"] == account_b["id"]


def test_role_check_outranks_port_request_existence_returns_403(
    api, billing_admin_headers, carrier_liaison_headers
):
    """The checks below are evaluated in the order listed, and the first one that fails produces the response.

    A `BillingAdmin` rejecting a port-request id that does not exist, with an
    empty body, violates the role rule, the body-shape rule and the resolution
    rule at once, and sees only the first of the three.

    Design: Corner/validations/role_check_outranks_port_request_existence_returns_403
    """
    set_clock(CLOCK_DEFAULT_ISO)

    refused = api.reject_port_request(NON_EXISTENT_UUID, {}, billing_admin_headers)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_PORT_REQUEST_NOT_FOUND.value
    assert reported != ApiErrorId.ERR_INVALID_REQUEST.value

    # For a role the endpoint does authorize, the ladder falls through to the
    # next rule this same call violates. The PRD orders request-body shape
    # ahead of port-request resolution, and `reason_code` is mandatory on a
    # rejection, so the empty body is what answers — not the unresolvable id.
    liaison = api.reject_port_request(NON_EXISTENT_UUID, {}, carrier_liaison_headers)
    validate_error(liaison, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_reservation_window_of_exactly_45_days_is_accepted_and_46_is_not(
    api, numbering_admin_headers
):
    """`reserved_until` must be strictly later than `reserved_from`, `reserved_from` must not lie before the logical clock, and the span from `reserved_from` to `reserved_until` must not exceed 45 days; any of those three failures is `ERR_RESERVATION_WINDOW_INVALID`.

    2026-08-01 through 2026-09-15 is exactly 45 days and passes; extending the
    same hold by one day fails, so the maximum span is inclusive.

    Design: Corner/validations/reservation_window_of_exactly_45_days_is_accepted_and_46_is_not
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account(
        "ACCT1026", billing_name="ASTER NV", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA",
        "06001",
        fee_type="PER_LINE",
        monthly_fee_cents=175,
        remit_day_of_month=5,
    )
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx="415615",
        total_capacity=10,
        max_concurrent_reservations=2,
    )
    number_one = seed_phone_number(block["id"], "3101")
    number_two = seed_phone_number(block["id"], "3102")

    accepted = validate_success(
        api.create_number_reservation(
            make_number_reservation_payload(
                block["id"],
                account["id"],
                block_version(block["id"]),
                reserved_from="2026-08-01T00:00:00.000Z",
                reserved_until="2026-09-15T00:00:00.000Z",
                purpose="NEW_LINE",
            ),
            numbering_admin_headers,
        ),
        201,
    )
    assert accepted["status"] == "HELD"
    assert accepted["number_id"] == number_one["id"]

    version_after_hold = block_version(block["id"])
    refused = api.create_number_reservation(
        make_number_reservation_payload(
            block["id"],
            account["id"],
            version_after_hold,
            reserved_from="2026-08-01T00:00:00.000Z",
            reserved_until="2026-09-16T00:00:00.000Z",
            purpose="NEW_LINE",
        ),
        numbering_admin_headers,
    )
    validate_error(refused, ApiErrorId.ERR_RESERVATION_WINDOW_INVALID.value, 422)

    assert read_phone_number(number_two["id"])["status"] == "AVAILABLE"
    block_now = read_number_block(block["id"])
    assert_block_census(
        block_now, minted=2, available=1, reserved=1, assigned=0, parked=0
    )
    assert_version(block_now, version_after_hold, "NumberBlock")


def test_remittance_run_before_the_remit_day_of_month_is_rejected(
    api, billing_admin_headers, platform_admin_headers
):
    """Failing either is `ERR_REMITTANCE_PERIOD_NOT_CLOSED` (422) — a jurisdiction that files on the 10th cannot be remitted on the 9th, and the month in progress cannot be remitted at all.

    The jurisdiction files on the 5th: a closed period is still refused while
    the clock reads the 4th, and the clock's own month is refused even once the
    day-of-month half of the conjunction is satisfied.

    Design: Corner/validations/remittance_run_before_the_remit_day_of_month_is_rejected
    """
    set_clock("2026-09-04T23:00:00.000Z")
    jurisdiction = seed_jurisdiction(
        "CA",
        "06001",
        fee_type="PER_LINE",
        monthly_fee_cents=175,
        remit_day_of_month=5,
    )

    too_early = api.create_remittance_run(
        jurisdiction["id"], make_remittance_run_payload("2026-08"), billing_admin_headers
    )
    validate_error(too_early, ApiErrorId.ERR_REMITTANCE_PERIOD_NOT_CLOSED.value, 422)

    set_clock("2026-09-06T00:00:00.000Z")
    still_open = api.create_remittance_run(
        jurisdiction["id"], make_remittance_run_payload("2026-09"), billing_admin_headers
    )
    validate_error(still_open, ApiErrorId.ERR_REMITTANCE_PERIOD_NOT_CLOSED.value, 422)

    stored = validate_success(
        api.get_jurisdiction(jurisdiction["id"], platform_admin_headers)
    )
    assert_null(stored["last_remitted_period"], "Jurisdiction.last_remitted_period")
    assert_cents_equal(stored["remitted_fee_cents"], 0, "remitted_fee_cents")


def test_scheduling_onto_another_carriers_slot_is_rejected(api, porting_specialist_headers):
    """The slot's `carrier_id` must equal the request's `losing_carrier_id`, since a window on one carrier's calendar is meaningless for another, and a mismatch is `ERR_SLOT_CARRIER_MISMATCH`.

    The slot is OPEN and starts after the request's firm-order-commitment floor,
    so carrier identity is the only difference left to refuse the booking.

    Design: Corner/validations/scheduling_onto_another_carriers_slot_is_rejected
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1027", billing_name="BRYONY OY", service_state_code="CA", status="ACTIVE"
    )
    carrier_a = seed_carrier(
        "BA15",
        name="Bryony Legacy A",
        csr_match_policy="STRICT",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )
    carrier_b = seed_carrier(
        "BB16",
        name="Bryony Legacy B",
        csr_match_policy="STRICT",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )

    claimed = make_port_request_payload(
        account["id"],
        carrier_a["id"],
        requested_numbers=["+14155551803"],
        claimed_account_number="CSR-1027",
        claimed_pin="1027",
        claimed_billing_name="BRYONY OY",
        claimed_address_line1="27 BRYONY CT",
        claimed_zip="94577",
    )
    port_request = validate_success(
        api.create_port_request(claimed, porting_specialist_headers), 201
    )
    post_matching_csr_snapshot(port_request["id"], claimed)

    validated = read_port_request(port_request["id"])
    assert validated["status"] == "VALIDATED"
    assert_instant(
        validated["earliest_cutover_at"],
        "2026-08-05T00:00:00.000Z",
        "PortRequest.earliest_cutover_at",
    )

    slot_b = seed_cutover_slot(
        carrier_b["id"],
        window_start="2026-08-06T14:00:00.000Z",
        window_end="2026-08-06T18:00:00.000Z",
    )

    refused = api.schedule_port_request(
        port_request["id"], make_schedule_payload(slot_b["id"]), porting_specialist_headers
    )
    validate_error(refused, ApiErrorId.ERR_SLOT_CARRIER_MISMATCH.value, 422)

    after = read_port_request(port_request["id"])
    assert after["status"] == "VALIDATED"
    assert_instant(
        after["earliest_cutover_at"],
        "2026-08-05T00:00:00.000Z",
        "PortRequest.earliest_cutover_at",
    )

    slot_after = read_cutover_slot(slot_b["id"])
    assert slot_after["status"] == "OPEN"
    assert_null(slot_after["booked_port_request_id"], "CutoverSlot.booked_port_request_id")


def test_intl_flag_gates_only_non_domestic_destinations(api):
    """For a non-domestic attempt only, the owning account's `intl_calling_enabled` must be true — `ERR_INTL_CALLING_DISABLED` (403), recorded as `BLOCKED_INTL`.

    One device on one account with the flag switched off dials domestically and
    internationally in turn, so only the destination distinguishes the two
    outcomes.

    Design: Corner/validations/intl_flag_gates_only_non_domestic_destinations
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account(
        "ACCT1028",
        billing_name="CLOVER LTD",
        service_state_code="CA",
        status="ACTIVE",
        intl_calling_enabled=False,
    )
    jurisdiction = seed_jurisdiction(
        "CA",
        "06001",
        fee_type="PER_LINE",
        monthly_fee_cents=175,
        remit_day_of_month=5,
    )
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx="415616",
        total_capacity=10,
        max_concurrent_reservations=2,
    )
    number = seed_phone_number(block["id"], "3201")
    device = seed_device(
        account["id"],
        "AABBCC003201",
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="28 CLOVER ROW",
        unit="",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration["id"], "VERIFIED")
    set_clock("2026-08-05T10:00:00.000Z")

    account_headers = make_account_admin_headers(account["id"])
    domestic = validate_success(
        api.create_call_attempt(
            device["id"],
            make_call_attempt_payload("+14155559001", "1", 300),
            account_headers,
        ),
        201,
    )
    assert domestic["decision"] == "ALLOWED"
    assert_null(domestic["decision_error_id"], "CallAttempt.decision_error_id")

    international = api.create_call_attempt(
        device["id"],
        make_call_attempt_payload("+447700900501", "44", 300),
        account_headers,
    )
    validate_error(international, ApiErrorId.ERR_INTL_CALLING_DISABLED.value, 403)

    rows, meta = validate_paginated(api.list_call_attempts(device["id"], account_headers))
    assert meta["total_count"] == 2
    blocked = find_by(rows, destination_country_code="44")
    assert blocked["decision"] == "BLOCKED_INTL"
    assert blocked["decision_error_id"] == ApiErrorId.ERR_INTL_CALLING_DISABLED.value

    assert read_device(device["id"])["calling_status"] == "UNRESTRICTED"


def test_no_available_number_outranks_the_per_number_overlap_check(api, numbering_admin_headers):
    """If the candidate set is empty the request is refused with `ERR_NO_NUMBERS_AVAILABLE`, and because selection runs third, that refusal is only reached after the interval and block-ceiling checks have passed.

    The per-number overlap check can only speak about a number selection has
    already chosen, so with the block's only number already held the automatic
    request reports an empty candidate set, while naming that same number
    explicitly reaches the overlap check instead.

    Design: Corner/validations/no_available_number_outranks_the_per_number_overlap_check
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account(
        "ACCT1029", billing_name="DAHLIA SA", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA",
        "06001",
        fee_type="PER_LINE",
        monthly_fee_cents=175,
        remit_day_of_month=5,
    )
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx="415617",
        total_capacity=10,
        max_concurrent_reservations=3,
    )
    number = seed_phone_number(block["id"], "3301")

    held = seed_reservation(
        block["id"],
        account["id"],
        purpose="NEW_LINE",
        reserved_from="2026-08-04T00:00:00.000Z",
        reserved_until="2026-08-10T00:00:00.000Z",
    )
    version_after_hold = block_version(block["id"])

    automatic = api.create_number_reservation(
        make_number_reservation_payload(
            block["id"],
            account["id"],
            version_after_hold,
            reserved_from="2026-08-06T00:00:00.000Z",
            reserved_until="2026-08-08T00:00:00.000Z",
            purpose="NEW_LINE",
        ),
        numbering_admin_headers,
    )
    validate_error(automatic, ApiErrorId.ERR_NO_NUMBERS_AVAILABLE.value, 409)

    explicit = api.create_number_reservation(
        make_number_reservation_payload(
            block["id"],
            account["id"],
            version_after_hold,
            number_id=number["id"],
            reserved_from="2026-08-06T00:00:00.000Z",
            reserved_until="2026-08-08T00:00:00.000Z",
            purpose="NEW_LINE",
        ),
        numbering_admin_headers,
    )
    validate_error(explicit, ApiErrorId.ERR_NUMBER_RESERVATION_OVERLAP.value, 409)

    assert read_reservation(held["id"])["status"] == "HELD"
    assert read_phone_number(number["id"])["status"] == "RESERVED"
    block_now = read_number_block(block["id"])
    assert_block_census(
        block_now, minted=1, available=0, reserved=1, assigned=0, parked=0
    )
    assert_version(block_now, version_after_hold, "NumberBlock")


def test_the_third_resubmission_is_refused_once_the_limit_is_reached(
    api, porting_specialist_headers, carrier_liaison_headers
):
    """In both cases the request must not have exhausted its budget of two resubmissions: once `resubmission_count` has reached 2, a third attempt is refused with `ERR_RESUBMISSION_LIMIT_REACHED` and the request stays exactly where it was.

    Every one of the three corrections is individually well formed and the third
    would even have matched the carrier's record, so only the cumulative count
    refuses it.

    Design: Corner/validations/the_third_resubmission_is_refused_once_the_limit_is_reached
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1030", billing_name="ELDER KFT", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "EL17",
        name="Elder Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )
    port_request = seed_port_request(
        account["id"],
        carrier["id"],
        requested_numbers=["+14155551804"],
        claimed_account_number="CSR-1030",
        claimed_pin="9999",
        claimed_billing_name="ELDER KFT",
        claimed_address_line1="30 ELDER SQ",
        claimed_zip="94577",
    )

    on_file = {
        "account_number_on_file": "CSR-1030",
        "pin_on_file": "1030",
        "billing_name_on_file": "ELDER KFT",
        "address_line1_on_file": "30 ELDER SQ",
        "zip_on_file": "94577",
    }
    # A STRICT carrier demands all five comparison points, so a disagreeing PIN
    # alone drives the request into CSR_MISMATCH every time.
    expected_points = PERFECT_MATCH_POINTS - MATCH_POINT_WEIGHTS["pin"]

    post_csr_snapshot(port_request["id"], **on_file)
    for corrected_pin in ("8888", "7777"):
        resubmit_port_request(
            port_request["id"],
            claimed_account_number="CSR-1030",
            claimed_pin=corrected_pin,
            claimed_billing_name="ELDER KFT",
            claimed_address_line1="30 ELDER SQ",
            claimed_zip="94577",
        )
        post_csr_snapshot(port_request["id"], **on_file)

    before = read_port_request(port_request["id"])
    assert before["status"] == "CSR_MISMATCH"
    assert before["resubmission_count"] == PORT_RESUBMISSION_LIMIT

    refused = api.resubmit_port_request(
        port_request["id"],
        make_resubmit_payload(
            claimed_account_number="CSR-1030",
            claimed_pin="1030",
            claimed_billing_name="ELDER KFT",
            claimed_address_line1="30 ELDER SQ",
            claimed_zip="94577",
        ),
        porting_specialist_headers,
    )
    validate_error(refused, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED.value, 409)

    after = read_port_request(port_request["id"])
    assert after["status"] == "CSR_MISMATCH"
    assert after["resubmission_count"] == PORT_RESUBMISSION_LIMIT
    assert after["claimed_pin"] == "7777"

    rows, meta = validate_paginated(
        api.list_csr_snapshots(port_request["id"], carrier_liaison_headers)
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3
    for row in rows:
        assert row["match_status"] == "MISMATCHED"
        assert row["match_points"] == expected_points
