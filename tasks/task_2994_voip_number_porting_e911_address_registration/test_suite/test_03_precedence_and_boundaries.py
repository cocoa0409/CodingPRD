"""Validation-precedence conflicts and inclusive/exclusive numeric boundaries.

Two families of depth tests live here. The first drives a single request that
violates two rules of the PRD's precedence ladder at once and pins which of the
two the caller is allowed to see. The second walks a numeric ceiling one unit at
a time so that the inclusive edge and the exclusive edge are both observed.

Every test builds all of its own preconditions against a fresh database.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_ISO,
    assert_block_census,
    assert_cents_equal,
    assert_immutable_common_fields,
    assert_instant,
    assert_null,
    block_version,
    book_slot,
    estimated_base_cents,
    make_account_admin_headers,
    make_call_attempt_payload,
    make_number_reservation_payload,
    make_numbering_admin_headers,
    make_porting_specialist_headers,
    make_schedule_payload,
    projected_day_total_cents,
    read_account,
    read_cutover_slot,
    read_device,
    read_number_block,
    read_phone_number,
    read_port_request,
    read_registration,
    read_reservation,
    seed_account,
    seed_cutover_slot,
    seed_device,
    seed_jurisdiction,
    seed_number_block,
    seed_phone_number,
    seed_registration,
    seed_reservation,
    set_clock,
    setup_compliant_device,
    setup_validated_port_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify_registration,
)

# The scheduling scenario below is anchored on Monday 2026-08-03: a carrier with
# foc_business_days 3 counts Tuesday the 4th, Wednesday the 5th and Thursday the
# 6th, so the firm-order-commitment floor lands at midnight of the 6th.
SCHEDULE_CLOCK = "2026-08-03T09:00:00.000Z"
FOC_FLOOR = "2026-08-06T00:00:00.000Z"
LATE_WINDOW_START = "2026-08-10T14:00:00.000Z"
LATE_WINDOW_END = "2026-08-10T18:00:00.000Z"
EARLY_WINDOW_START = "2026-08-04T10:00:00.000Z"
EARLY_WINDOW_END = "2026-08-04T12:00:00.000Z"


def _error_id_of(response):
    """The `error_id` carried inside an error envelope's data object."""
    body = response.json()
    data = body.get("data") or {}
    return data.get("error_id")


def _assert_not_refused_as(response, forbidden_error_ids=(), forbidden_statuses=()):
    """Assert a refusal names none of these error ids and none of these statuses."""
    observed = _error_id_of(response)
    for error_id in forbidden_error_ids:
        assert observed != error_id, (
            f"the losing rule must not be reported: got error_id {observed!r}"
        )
    for status in forbidden_statuses:
        assert response.status_code != status, (
            f"the losing rule's HTTP status must not be used: got {response.status_code}"
        )


def _build_double_violation_schedule():
    """A SCHEDULED port request plus an OPEN slot that sits before its FOC floor.

    Re-booking that second slot violates the state precondition and the
    firm-order-commitment floor in one request.
    """
    set_clock(SCHEDULE_CLOCK)
    scenario = setup_validated_port_request(
        account_number="ACCT0009",
        ocn="PL03",
        carrier_overrides={
            "name": "Pacific Legacy",
            "csr_match_policy": "STRICT",
            "porting_buffer_minutes": 60,
            "foc_business_days": 3,
        },
        account_overrides={"billing_name": "IRONWOOD SA"},
        requested_numbers=["+14155550003"],
    )
    carrier_id = scenario["carrier"]["id"]
    # Opened first, and far enough out that the 60-minute buffer on either side
    # of it cannot reach the earlier candidate window.
    booked_slot = seed_cutover_slot(
        carrier_id, window_start=LATE_WINDOW_START, window_end=LATE_WINDOW_END
    )
    early_slot = seed_cutover_slot(
        carrier_id, window_start=EARLY_WINDOW_START, window_end=EARLY_WINDOW_END
    )
    scenario["port_request"] = book_slot(
        scenario["port_request"]["id"], booked_slot["id"]
    )
    scenario["booked_slot"] = booked_slot
    scenario["early_slot"] = early_slot
    return scenario


def test_schedule_state_precondition_outranks_foc_window_violation__error_identity(api):
    """The request must be `VALIDATED`; any other status is refused with `ERR_PORT_REQUEST_NOT_SCHEDULABLE` before the cutover window is examined at all, so a request in `CSR_MISMATCH` never discovers whether its chosen window would have been legal.

    The request is already SCHEDULED and the second slot starts two days before
    its earliest_cutover_at, so both the state rule and the FOC floor are broken.

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_precondition_outranks_foc_window_violation
    """
    scenario = _build_double_violation_schedule()
    port_request = scenario["port_request"]
    assert port_request["status"] == "SCHEDULED", (
        f"precondition: expected SCHEDULED, got {port_request['status']!r}"
    )
    assert_instant(port_request["earliest_cutover_at"], FOC_FLOOR, "earliest_cutover_at")

    response = api.schedule_port_request(
        port_request["id"],
        make_schedule_payload(scenario["early_slot"]["id"]),
        make_porting_specialist_headers(),
    )
    validate_error(
        response, ApiErrorId.ERR_PORT_REQUEST_NOT_SCHEDULABLE.value, 409
    )
    _assert_not_refused_as(
        response,
        forbidden_error_ids=(
            ApiErrorId.ERR_CUTOVER_BEFORE_FOC.value,
            ApiErrorId.ERR_SLOT_NOT_OPEN.value,
            ApiErrorId.ERR_SLOT_CARRIER_MISMATCH.value,
        ),
        forbidden_statuses=(422,),
    )

    after = read_port_request(port_request["id"])
    assert after["status"] == "SCHEDULED", (
        f"the refusal must persist nothing: status is {after['status']!r}"
    )
    assert_instant(after["earliest_cutover_at"], FOC_FLOOR, "earliest_cutover_at")


def test_schedule_state_precondition_outranks_foc_window_violation__slots_untouched(api):
    """Scheduling checks that the port request is `VALIDATED` (rule 12) *before* it looks at the slot's status (rule 14), its carrier (rule 30) or the firm-order-commitment floor (rule 41) — a request in the wrong status never learns whether its chosen window would have been acceptable.

    Because the refusal happens at the state check, neither calendar row moves:
    the earlier window stays OPEN and the booked window keeps its booking.

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_precondition_outranks_foc_window_violation
    """
    scenario = _build_double_violation_schedule()
    port_request = scenario["port_request"]
    booked_slot_id = scenario["booked_slot"]["id"]
    early_slot_id = scenario["early_slot"]["id"]

    booked_before = read_cutover_slot(booked_slot_id)
    early_before = read_cutover_slot(early_slot_id)
    assert booked_before["status"] == "BOOKED"
    assert early_before["status"] == "OPEN"

    response = api.schedule_port_request(
        port_request["id"],
        make_schedule_payload(early_slot_id),
        make_porting_specialist_headers(),
    )
    validate_error(response, ApiErrorId.ERR_PORT_REQUEST_NOT_SCHEDULABLE.value, 409)

    early_after = read_cutover_slot(early_slot_id)
    assert early_after["status"] == "OPEN", (
        f"the rejected candidate slot must stay OPEN, got {early_after['status']!r}"
    )
    assert_null(early_after["booked_port_request_id"], "booked_port_request_id")
    assert_null(early_after["booked_at"], "booked_at")
    assert early_after["version"] == early_before["version"], (
        "an unbooked slot must not be mutated by a refused booking"
    )

    booked_after = read_cutover_slot(booked_slot_id)
    assert booked_after["status"] == "BOOKED", (
        f"the standing booking must survive, got {booked_after['status']!r}"
    )
    assert booked_after["booked_port_request_id"] == port_request["id"], (
        "the standing booking must still name the port request"
    )
    assert booked_after["version"] == booked_before["version"], (
        "the standing booking must not be mutated by a refused booking"
    )


def _build_suspended_number_less_device(account_number="ACCT0010", cap_cents=1):
    """A device whose captured location was REJECTED, so it is SUSPENDED_911.

    The device deliberately holds no phone number. Per the PRD the compliance
    population is exactly the account's number-holding devices, so this device
    is outside it: the account stays out of `BLOCKED` and the device therefore
    keeps `calling_status` `UNRESTRICTED`, which is what leaves the 911
    suspension as the first gate the call attempt can fail.
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account(
        account_number,
        billing_name="JUNIPER KK",
        service_state_code="CA",
        status="ACTIVE",
        intl_calling_enabled=True,
        intl_daily_cap_cents=cap_cents,
    )
    jurisdiction = seed_jurisdiction("CA", "06001")
    device = seed_device(
        account["id"],
        "AABBCC000061",
        device_type="BASE_STATION",
        nomadic=False,
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="999 NOWHERE RD",
        unit="",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    registration = verify_registration(
        registration["id"],
        "REJECTED",
        rejection_note="address is not a dispatchable location",
    )
    return {
        "account": account,
        "jurisdiction": jurisdiction,
        "device": read_device(device["id"]),
        "registration": registration,
    }


def test_e911_suspension_outranks_intl_spend_cap_on_call_attempt__error_identity(api):
    """The fiscal ceiling is the very last check in the entire system, so every safety refusal above outranks it: a device that is fully blocked, 911-suspended or fraud-scoring over threshold reports that fact rather than a spend problem, even when the projection would also have breached the cap.

    A one-hour call to country code 44 prices at 720 cents against a daily cap of
    one cent, so the spend gate would also have refused this attempt.

    Design: Difficulty/priority_pair_validation_conflict/e911_suspension_outranks_intl_spend_cap_on_call_attempt
    """
    scenario = _build_suspended_number_less_device()
    device = scenario["device"]
    account = scenario["account"]
    assert device["registration_status"] == "SUSPENDED_911", (
        f"precondition: expected SUSPENDED_911, got {device['registration_status']!r}"
    )
    assert device["calling_status"] == "UNRESTRICTED", (
        f"precondition: expected UNRESTRICTED, got {device['calling_status']!r}"
    )

    response = api.create_call_attempt(
        device["id"],
        make_call_attempt_payload(
            destination_e164="+447700900123",
            destination_country_code="44",
            requested_duration_seconds=3600,
        ),
        make_account_admin_headers(account["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DEVICE_911_SUSPENDED.value, 409)
    _assert_not_refused_as(
        response,
        forbidden_error_ids=(
            ApiErrorId.ERR_INTL_SPEND_CAP_EXCEEDED.value,
            ApiErrorId.ERR_ACCOUNT_E911_BLOCKED.value,
            ApiErrorId.ERR_DEVICE_CALLING_BLOCKED.value,
        ),
        forbidden_statuses=(402,),
    )

    after = read_device(device["id"])
    assert after["registration_status"] == "SUSPENDED_911", (
        f"the refusal must not move the device, got {after['registration_status']!r}"
    )
    assert read_registration(scenario["registration"]["id"])["verification_status"] == (
        "REJECTED"
    ), "the rejected dispatchable location must stay REJECTED"
    # The population of the posture is the account's number-holding devices, and
    # this device holds none, so the vacuous case applies.
    assert read_account(account["id"])["e911_compliance_posture"] == "COMPLIANT"


def test_e911_suspension_outranks_intl_spend_cap_on_call_attempt__cap_is_really_breached(api):
    """And the fiscal ceiling on international spend (rule 53) is the very last check in the entire ladder, so every safety refusal — a fully blocked device, a suspended location, a blocked account posture, a missing registration, a disabled or blocked international path, and a breached fraud threshold — outranks it.

    The same one-hour call to country code 44 is placed twice on one account: the
    911-suspended device reports its suspension, while a sibling device with a
    VERIFIED location gets as far as the fiscal ceiling and reports that instead.

    Design: Difficulty/priority_pair_validation_conflict/e911_suspension_outranks_intl_spend_cap_on_call_attempt
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account(
        "ACCT0010",
        billing_name="JUNIPER KK",
        service_state_code="CA",
        status="ACTIVE",
        intl_calling_enabled=True,
        intl_daily_cap_cents=1,
    )
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415562", total_capacity=20,
        max_concurrent_reservations=5,
    )
    number = seed_phone_number(block["id"], "0801")
    healthy = seed_device(
        account["id"], "AABBCC000062", device_type="BASE_STATION",
        nomadic=False, assigned_number_id=number["id"],
    )
    healthy_registration = seed_registration(
        healthy["id"], jurisdiction["id"], account["id"],
        address_line1="12 JUNIPER LN", unit="", city="OAKLAND",
        state_code="CA", postal_code="94601",
    )
    verify_registration(healthy_registration["id"], "VERIFIED")

    suspended = seed_device(
        account["id"], "AABBCC000061", device_type="BASE_STATION", nomadic=False
    )
    suspended_registration = seed_registration(
        suspended["id"], jurisdiction["id"], account["id"],
        address_line1="999 NOWHERE RD", unit="", city="OAKLAND",
        state_code="CA", postal_code="94601",
    )
    verify_registration(
        suspended_registration["id"], "REJECTED",
        rejection_note="address is not a dispatchable location",
    )

    payload = make_call_attempt_payload(
        destination_e164="+447700900123",
        destination_country_code="44",
        requested_duration_seconds=3600,
    )
    headers = make_account_admin_headers(account["id"])

    suspended_response = api.create_call_attempt(suspended["id"], payload, headers)
    validate_error(
        suspended_response, ApiErrorId.ERR_DEVICE_911_SUSPENDED.value, 409
    )
    _assert_not_refused_as(
        suspended_response,
        forbidden_error_ids=(ApiErrorId.ERR_INTL_SPEND_CAP_EXCEEDED.value,),
        forbidden_statuses=(402,),
    )

    healthy_response = api.create_call_attempt(healthy["id"], payload, headers)
    validate_error(
        healthy_response, ApiErrorId.ERR_INTL_SPEND_CAP_EXCEEDED.value, 402
    )

    rows, _meta = validate_paginated(
        api.list_call_attempts(healthy["id"], headers, {"decision": "BLOCKED_SPEND_CAP"})
    )
    assert len(rows) == 1, (
        f"the sibling device must hold exactly one spend-capped row, got {len(rows)}"
    )
    assert_cents_equal(
        rows[0]["projected_day_total_cents"],
        estimated_base_cents("44", 3600),
        "projected_day_total_cents",
    )
    assert rows[0]["decision_error_id"] == ApiErrorId.ERR_INTL_SPEND_CAP_EXCEEDED.value


def test_e911_suspension_outranks_intl_spend_cap_on_call_attempt__audit_row(api):
    """On every domestic attempt — cleared or refused — and on every non-domestic attempt refused at gates 1 through 7, `day_subtotal_cents`, `surcharge_pct_applied` and `projected_day_total_cents` are all recorded as 0.

    The audit row proves the spend gate was never reached: the three day-level
    figures are zero even though the priced base is 720 cents against a cap of 1.

    Design: Difficulty/priority_pair_validation_conflict/e911_suspension_outranks_intl_spend_cap_on_call_attempt
    """
    scenario = _build_suspended_number_less_device()
    device = scenario["device"]
    headers = make_account_admin_headers(scenario["account"]["id"])

    response = api.create_call_attempt(
        device["id"],
        make_call_attempt_payload(
            destination_e164="+447700900123",
            destination_country_code="44",
            requested_duration_seconds=3600,
        ),
        headers,
    )
    validate_error(response, ApiErrorId.ERR_DEVICE_911_SUSPENDED.value, 409)

    rows, _meta = validate_paginated(api.list_call_attempts(device["id"], headers))
    assert len(rows) == 1, f"expected exactly one persisted attempt, got {len(rows)}"
    row = rows[0]
    assert_immutable_common_fields(row, "call attempt")
    assert row["decision"] == "BLOCKED_E911", (
        f"decision expected BLOCKED_E911, got {row['decision']!r}"
    )
    assert row["decision_error_id"] == ApiErrorId.ERR_DEVICE_911_SUSPENDED.value, (
        f"decision_error_id expected the suspension id, got {row['decision_error_id']!r}"
    )
    # Always-computed pricing figures, carried even on a refused row.
    assert row["billable_minutes"] == 60
    assert row["rate_cents_per_minute"] == 12
    assert_cents_equal(row["estimated_base_cents"], 720, "estimated_base_cents")
    # The fraud score is computed at gate 7, which this row never reached.
    assert row["realtime_risk_score"] == 0, (
        f"realtime_risk_score expected 0, got {row['realtime_risk_score']}"
    )
    assert_cents_equal(row["day_subtotal_cents"], 0, "day_subtotal_cents")
    assert row["surcharge_pct_applied"] == 0, (
        f"surcharge_pct_applied expected 0, got {row['surcharge_pct_applied']}"
    )
    assert_cents_equal(row["projected_day_total_cents"], 0, "projected_day_total_cents")
    assert read_device(device["id"])["toll_fraud_score"] == 0, (
        "a row refused before the fraud gate leaves toll_fraud_score untouched"
    )


# One hour to country code 44 prices at 12 cents a minute over 60 billable
# minutes, so every call of the spend-cap scenario contributes 720 cents.
HOUR_CALL_SECONDS = 3600
UK_COUNTRY_CODE = "44"
HOUR_CALL_BASE_CENTS = 720
SPEND_CLOCK = "2026-08-05T12:00:00.000Z"
SPEND_CAP_CENTS = 2267


def _build_intl_spend_scenario():
    """A settled number-holding device on an account with a 2267-cent daily cap.

    The device is created while the clock still reads the default instant and the
    clock is then moved four days on, so the device is older than 72 hours and no
    new-device multiplier distorts the fraud score of the calls that follow.
    """
    set_clock(CLOCK_DEFAULT_ISO)
    scenario = setup_compliant_device(
        account_number="ACCT0011",
        npa_nxx="415563",
        line_number="0901",
        mac_address="AABBCC000071",
        device_overrides={"nomadic": False},
        account_overrides={
            "billing_name": "KESTREL BV",
            "status": "ACTIVE",
            "intl_calling_enabled": True,
            "intl_daily_cap_cents": SPEND_CAP_CENTS,
        },
    )
    set_clock(SPEND_CLOCK)
    return scenario


def _dial_one_hour(api, scenario, last_digit):
    """Place a one-hour call to country code 44 and return the raw response."""
    return api.create_call_attempt(
        scenario["device"]["id"],
        make_call_attempt_payload(
            destination_e164=f"+44770090000{last_digit}",
            destination_country_code=UK_COUNTRY_CODE,
            requested_duration_seconds=HOUR_CALL_SECONDS,
        ),
        make_account_admin_headers(scenario["account"]["id"]),
    )


def test_intl_spend_cap_blocks_one_cent_above_ceiling_and_excludes_blocked_spend__under_ceiling(api):
    """For a non-domestic attempt that reaches gate 8, the day subtotal is this attempt's own `estimated_base_cents` plus the sum of `estimated_base_cents` over every call attempt that belongs to *any* device of the same account, whose `created_at` falls inside the clock's UTC calendar day, whose `destination_country_code` is not `1`, and whose `decision` is `ALLOWED`.

    The first two hours of the day project 720 and then 1440 cents, both inside
    the 2267-cent ceiling and both below the 2000-cent surcharge tier only on the
    first call.

    Design: Difficulty/boundary_precision_check/intl_spend_cap_blocks_one_cent_above_ceiling_and_excludes_blocked_spend
    """
    scenario = _build_intl_spend_scenario()

    first = validate_success(_dial_one_hour(api, scenario, 1), 201)
    assert first["decision"] == "ALLOWED", (
        f"the first hour must be allowed, got {first['decision']!r}"
    )
    assert_null(first["decision_error_id"], "decision_error_id")
    assert_cents_equal(
        first["estimated_base_cents"], HOUR_CALL_BASE_CENTS, "estimated_base_cents"
    )
    assert_cents_equal(
        first["day_subtotal_cents"], HOUR_CALL_BASE_CENTS, "day_subtotal_cents"
    )
    assert first["surcharge_pct_applied"] == 0, (
        f"a 720-cent subtotal is below the 2000-cent tier, got "
        f"{first['surcharge_pct_applied']}"
    )
    assert_cents_equal(
        first["projected_day_total_cents"],
        HOUR_CALL_BASE_CENTS,
        "projected_day_total_cents",
    )

    second = validate_success(_dial_one_hour(api, scenario, 2), 201)
    assert second["decision"] == "ALLOWED", (
        f"the second hour must be allowed, got {second['decision']!r}"
    )
    assert_cents_equal(
        second["day_subtotal_cents"], 2 * HOUR_CALL_BASE_CENTS, "day_subtotal_cents"
    )
    assert second["surcharge_pct_applied"] == 0, (
        f"a 1440-cent subtotal is still below the tier, got "
        f"{second['surcharge_pct_applied']}"
    )
    assert_cents_equal(
        second["projected_day_total_cents"],
        2 * HOUR_CALL_BASE_CENTS,
        "projected_day_total_cents",
    )
    assert 2 * HOUR_CALL_BASE_CENTS <= SPEND_CAP_CENTS


def test_intl_spend_cap_blocks_one_cent_above_ceiling_and_excludes_blocked_spend__one_cent_over(api):
    """A projection landing exactly on `intl_daily_cap_cents` is allowed; only a projection strictly greater than the cap breaches, is refused with `ERR_INTL_SPEND_CAP_EXCEEDED`, and is recorded as `BLOCKED_SPEND_CAP`.

    The third hour of the day carries a 2160-cent subtotal into the 5 percent
    tier, projecting 2268 cents against a cap of 2267 — over by a single cent.

    Design: Difficulty/boundary_precision_check/intl_spend_cap_blocks_one_cent_above_ceiling_and_excludes_blocked_spend
    """
    scenario = _build_intl_spend_scenario()
    validate_success(_dial_one_hour(api, scenario, 1), 201)
    validate_success(_dial_one_hour(api, scenario, 2), 201)

    expected_subtotal = 3 * HOUR_CALL_BASE_CENTS
    expected_projection = projected_day_total_cents(expected_subtotal)
    assert expected_projection == SPEND_CAP_CENTS + 1, (
        "the scenario must sit exactly one cent above the ceiling"
    )

    response = _dial_one_hour(api, scenario, 3)
    validate_error(response, ApiErrorId.ERR_INTL_SPEND_CAP_EXCEEDED.value, 402)

    headers = make_account_admin_headers(scenario["account"]["id"])
    rows, _meta = validate_paginated(
        api.list_call_attempts(
            scenario["device"]["id"], headers, {"decision": "BLOCKED_SPEND_CAP"}
        )
    )
    assert len(rows) == 1, f"expected exactly one refused row, got {len(rows)}"
    row = rows[0]
    assert row["decision_error_id"] == ApiErrorId.ERR_INTL_SPEND_CAP_EXCEEDED.value
    assert_cents_equal(row["day_subtotal_cents"], expected_subtotal, "day_subtotal_cents")
    assert row["surcharge_pct_applied"] == 5, (
        f"a 2160-cent subtotal sits in the 5 percent tier, got "
        f"{row['surcharge_pct_applied']}"
    )
    assert_cents_equal(
        row["projected_day_total_cents"], expected_projection, "projected_day_total_cents"
    )


def test_intl_spend_cap_blocks_one_cent_above_ceiling_and_excludes_blocked_spend__refused_spend_excluded(api):
    """Refused attempts never contribute to any later subtotal, so a blocked call does not poison the rest of the account's day.

    A fourth identical hour therefore recomputes the same 2160-cent subtotal that
    the third one saw rather than doubling it, and both refusals are persisted.

    Design: Difficulty/boundary_precision_check/intl_spend_cap_blocks_one_cent_above_ceiling_and_excludes_blocked_spend
    """
    scenario = _build_intl_spend_scenario()
    validate_success(_dial_one_hour(api, scenario, 1), 201)
    validate_success(_dial_one_hour(api, scenario, 2), 201)

    third = _dial_one_hour(api, scenario, 3)
    validate_error(third, ApiErrorId.ERR_INTL_SPEND_CAP_EXCEEDED.value, 402)
    fourth = _dial_one_hour(api, scenario, 4)
    validate_error(fourth, ApiErrorId.ERR_INTL_SPEND_CAP_EXCEEDED.value, 402)

    expected_subtotal = 3 * HOUR_CALL_BASE_CENTS
    expected_projection = projected_day_total_cents(expected_subtotal)
    headers = make_account_admin_headers(scenario["account"]["id"])

    refused, _refused_meta = validate_paginated(
        api.list_call_attempts(
            scenario["device"]["id"], headers, {"decision": "BLOCKED_SPEND_CAP"}
        )
    )
    assert len(refused) == 2, f"expected two refused rows, got {len(refused)}"
    for row in refused:
        assert_cents_equal(
            row["day_subtotal_cents"], expected_subtotal, "day_subtotal_cents"
        )
        assert row["surcharge_pct_applied"] == 5, (
            f"surcharge_pct_applied expected 5, got {row['surcharge_pct_applied']}"
        )
        assert_cents_equal(
            row["projected_day_total_cents"],
            expected_projection,
            "projected_day_total_cents",
        )

    allowed, _allowed_meta = validate_paginated(
        api.list_call_attempts(
            scenario["device"]["id"], headers, {"decision": "ALLOWED"}
        )
    )
    assert len(allowed) == 2, (
        f"only the first two hours may be allowed, got {len(allowed)}"
    )

    device = read_device(scenario["device"]["id"])
    assert device["calling_status"] == "UNRESTRICTED", (
        f"a spend refusal is not a fraud block, got {device['calling_status']!r}"
    )
    assert device["fraud_block_count"] == 0, (
        f"a spend refusal must not raise fraud_block_count, got "
        f"{device['fraud_block_count']}"
    )


# Three intersecting closed intervals over one block whose ceiling is two
# concurrent holds: the second is admitted at the limit, the third is not.
FIRST_HOLD = ("2026-08-05T00:00:00.000Z", "2026-08-10T00:00:00.000Z")
SECOND_HOLD = ("2026-08-08T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
THIRD_HOLD = ("2026-08-09T00:00:00.000Z", "2026-08-11T00:00:00.000Z")


def _build_capacity_two_block():
    """An account plus a block whose ceiling is two holds and three free numbers."""
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account(
        "ACCT0012", billing_name="LARCH OY", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415564", total_capacity=20,
        max_concurrent_reservations=2,
    )
    numbers = [
        seed_phone_number(block["id"], line_number)
        for line_number in ("1001", "1002", "1003")
    ]
    return {"account": account, "block": block, "numbers": numbers}


def _hold(api, scenario, number, interval):
    """Post one NEW_LINE hold with a freshly read block concurrency token."""
    block_id = scenario["block"]["id"]
    return api.create_number_reservation(
        make_number_reservation_payload(
            block_id,
            scenario["account"]["id"],
            block_version(block_id),
            purpose="NEW_LINE",
            reserved_from=interval[0],
            reserved_until=interval[1],
            number_id=number["id"],
        ),
        make_numbering_admin_headers(),
    )


def test_block_reservation_capacity_admits_the_limit_and_refuses_the_next__admits_the_limit(api):
    """Second the block's aggregate ceiling is tested: the server counts the `HELD` reservations of the same block whose closed intervals intersect the candidate interval, and if that count plus this new one would exceed the block's `max_concurrent_reservations`, the request is refused with `ERR_BLOCK_RESERVATION_CAPACITY_EXCEEDED`.

    One standing hold plus this one is two, which does not exceed a ceiling of
    two, so the intersecting second hold is admitted.

    Design: Difficulty/boundary_precision_check/block_reservation_capacity_admits_the_limit_and_refuses_the_next
    """
    scenario = _build_capacity_two_block()
    numbers = scenario["numbers"]
    seed_reservation(
        scenario["block"]["id"],
        scenario["account"]["id"],
        purpose="NEW_LINE",
        number_id=numbers[0]["id"],
        reserved_from=FIRST_HOLD[0],
        reserved_until=FIRST_HOLD[1],
    )

    second = validate_success(_hold(api, scenario, numbers[1], SECOND_HOLD), 201)
    assert second["status"] == "HELD", (
        f"the hold at the limit must be admitted as HELD, got {second['status']!r}"
    )
    assert second["number_id"] == numbers[1]["id"], (
        "the hold must earmark the number it named"
    )
    assert_null(second["released_reason"], "released_reason")
    assert read_reservation(second["id"])["status"] == "HELD"
    assert read_phone_number(numbers[1]["id"])["status"] == "RESERVED", (
        "an admitted hold drives its number AVAILABLE -> RESERVED"
    )
    assert_block_census(
        read_number_block(scenario["block"]["id"]),
        minted=3, available=1, reserved=2, assigned=0, parked=0,
    )


def test_block_reservation_capacity_admits_the_limit_and_refuses_the_next__refuses_the_next(api):
    """Second the block's aggregate ceiling is tested: the server counts the `HELD` reservations of the same block whose closed intervals intersect the candidate interval, and if that count plus this new one would exceed the block's `max_concurrent_reservations`, the request is refused with `ERR_BLOCK_RESERVATION_CAPACITY_EXCEEDED`.

    The third candidate intersects both standing holds, so two plus one exceeds
    the ceiling of two even though its own number is entirely unencumbered.

    Design: Difficulty/boundary_precision_check/block_reservation_capacity_admits_the_limit_and_refuses_the_next
    """
    scenario = _build_capacity_two_block()
    numbers = scenario["numbers"]
    block_id = scenario["block"]["id"]
    for number, interval in ((numbers[0], FIRST_HOLD), (numbers[1], SECOND_HOLD)):
        seed_reservation(
            block_id,
            scenario["account"]["id"],
            purpose="NEW_LINE",
            number_id=number["id"],
            reserved_from=interval[0],
            reserved_until=interval[1],
        )

    census_before = read_number_block(block_id)
    response = _hold(api, scenario, numbers[2], THIRD_HOLD)
    validate_error(
        response, ApiErrorId.ERR_BLOCK_RESERVATION_CAPACITY_EXCEEDED.value, 409
    )
    _assert_not_refused_as(
        response,
        forbidden_error_ids=(
            ApiErrorId.ERR_NUMBER_RESERVATION_OVERLAP.value,
            ApiErrorId.ERR_NO_NUMBERS_AVAILABLE.value,
            ApiErrorId.ERR_PHONE_NUMBER_STATE_INVALID.value,
        ),
    )

    assert read_phone_number(numbers[2]["id"])["status"] == "AVAILABLE", (
        "a refused hold leaves its named number AVAILABLE"
    )
    block_after = read_number_block(block_id)
    assert_block_census(
        block_after, minted=3, available=1, reserved=2, assigned=0, parked=0
    )
    assert block_after["version"] == census_before["version"], (
        "a refused hold must not bump the block's version"
    )

    rows, _meta = validate_paginated(
        api.list_number_reservations(
            make_numbering_admin_headers(), {"block_id": block_id, "status": "HELD"}
        )
    )
    assert len(rows) == 2, f"exactly two holds may stand on the block, got {len(rows)}"
