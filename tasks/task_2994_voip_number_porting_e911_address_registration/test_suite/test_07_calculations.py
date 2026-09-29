"""Calculation corners of the VoIP porting & E911 contract.

Every test here pins one arithmetic or classification rule of the PRD at a
boundary or fallback the ordinary happy path never reaches: the RELAXED
match threshold met by exact equality, the business-day walk that skips a
weekend, the same-location drift class, the posture population restricted to
number-holding devices, the automatic reservation selector, the unknown
country-code fallbacks, the one-second call that still bills a whole minute,
and the remittance run that replaces a prorated provisional charge with an
unprorated final one.

Money is always a JSON integer of whole cents, rounding is half up, and every
expected integer is asserted as a literal and cross-checked against the shared
pure calculators so the intent of each figure stays legible.
"""
from test_helpers import (
    BILLING_USER_ID,
    DEFAULT_COUNTRY_RISK_POINTS,
    DEFAULT_RATE_CENTS,
    FRAUD_BLOCK_THRESHOLD,
    LIAISON_USER_ID,
    REMITTANCE_SENTINEL,
    THRESHOLD_RELAXED,
    THRESHOLD_STRICT,
    VELOCITY_POINTS_REALTIME,
    assess_fee,
    assert_block_census,
    assert_cents_equal,
    assert_instant,
    assert_null,
    billable_minutes,
    block_version,
    country_risk_points,
    estimated_base_cents,
    expected_match_points,
    expected_mismatch_fields,
    final_amount_cents,
    find_by,
    make_billing_admin_headers,
    make_call_attempt_payload,
    make_carrier_liaison_headers,
    make_csr_snapshot_payload,
    make_device_payload,
    make_number_reservation_payload,
    make_remittance_run_payload,
    make_account_admin_headers,
    make_numbering_admin_headers,
    match_threshold,
    projected_day_total_cents,
    prorated_unit_fee_cents,
    rate_cents_per_minute,
    read_account,
    read_device,
    read_jurisdiction,
    read_number_block,
    read_phone_number,
    read_port_request,
    read_registration,
    read_reservation,
    seed_account,
    seed_carrier,
    seed_device,
    seed_jurisdiction,
    seed_number_block,
    seed_phone_number,
    seed_port_request,
    seed_registration,
    set_clock,
    surcharge_pct,
    validate_paginated,
    validate_success,
    verify_registration,
)


def test_relaxed_csr_policy_matches_at_exactly_the_85_point_threshold(api):
    """`match_status` is `MATCHED` when `match_points` is greater than or equal to `threshold_applied` and `MISMATCHED` otherwise, so a `RELAXED` carrier accepts a score of exactly 85 while a `STRICT` carrier demands all five comparison points.

    Only `billing_name` disagrees, so the snapshot loses exactly its 15-point
    weight and lands on 100 - 15 == 85, the RELAXED threshold itself.

    Design: Corner/calculations/relaxed_csr_policy_matches_at_exactly_the_85_point_threshold
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1015", billing_name="PEONY AG", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "PL13",
        name="Peony Legacy",
        csr_match_policy="RELAXED",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )
    claimed = {
        "account_number": "CSR-1015",
        "pin": "1015",
        "billing_name": "PEONY AG",
        "service_address_line1": "15 PEONY PL",
        "service_zip": "94577",
    }
    port_request = seed_port_request(
        account["id"],
        carrier["id"],
        requested_numbers=["+14155551801"],
        claimed_account_number=claimed["account_number"],
        claimed_pin=claimed["pin"],
        claimed_billing_name=claimed["billing_name"],
        claimed_address_line1=claimed["service_address_line1"],
        claimed_zip=claimed["service_zip"],
    )

    on_file = dict(claimed, billing_name="PEONY HOLDINGS")
    snapshot = validate_success(
        api.create_csr_snapshot(
            port_request["id"],
            make_csr_snapshot_payload(
                port_request["version"],
                account_number_on_file=on_file["account_number"],
                pin_on_file=on_file["pin"],
                billing_name_on_file=on_file["billing_name"],
                address_line1_on_file=on_file["service_address_line1"],
                zip_on_file=on_file["service_zip"],
            ),
            make_carrier_liaison_headers(LIAISON_USER_ID),
        ),
        201,
    )

    # The pure calculator agrees the score is exactly the RELAXED threshold.
    assert expected_match_points(claimed, on_file) == 85
    assert match_threshold("RELAXED") == THRESHOLD_RELAXED == 85
    assert snapshot["match_points"] == 85, snapshot
    assert snapshot["threshold_applied"] == 85, snapshot
    assert snapshot["match_status"] == "MATCHED", snapshot
    assert snapshot["mismatch_fields"] == ["billing_name"], snapshot
    assert expected_mismatch_fields(claimed, on_file) == ["billing_name"]

    stored = read_port_request(port_request["id"])
    assert stored["status"] == "VALIDATED", stored
    assert stored["last_match_points"] == 85, stored
    assert stored["last_mismatch_fields"] == ["billing_name"], stored


def test_earliest_cutover_floor_counts_only_business_days_across_a_weekend(api):
    """Advance forward one calendar day at a time, counting a day only when its UTC weekday is Monday, Tuesday, Wednesday, Thursday or Friday, and stop once as many such days have been counted as the losing carrier's `foc_business_days`.

    Validated on Thursday 2026-08-06 with three FOC business days, the walk
    counts Friday the 7th, Monday the 10th and Tuesday the 11th.

    Design: Corner/calculations/earliest_cutover_floor_counts_only_business_days_across_a_weekend
    """
    set_clock("2026-08-06T15:30:00.000Z")
    account = seed_account(
        "ACCT1016", billing_name="QUINCE BV", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "QL14",
        name="Quince Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=60,
        foc_business_days=3,
    )
    claimed = {
        "account_number": "CSR-1016",
        "pin": "1016",
        "billing_name": "QUINCE BV",
        "service_address_line1": "16 QUINCE RD",
        "service_zip": "94577",
    }
    port_request = seed_port_request(
        account["id"],
        carrier["id"],
        requested_numbers=["+14155551802"],
        claimed_account_number=claimed["account_number"],
        claimed_pin=claimed["pin"],
        claimed_billing_name=claimed["billing_name"],
        claimed_address_line1=claimed["service_address_line1"],
        claimed_zip=claimed["service_zip"],
    )

    snapshot = validate_success(
        api.create_csr_snapshot(
            port_request["id"],
            make_csr_snapshot_payload(
                port_request["version"],
                account_number_on_file=claimed["account_number"],
                pin_on_file=claimed["pin"],
                billing_name_on_file=claimed["billing_name"],
                address_line1_on_file=claimed["service_address_line1"],
                zip_on_file=claimed["service_zip"],
            ),
            make_carrier_liaison_headers(LIAISON_USER_ID),
        ),
        201,
    )
    assert snapshot["match_points"] == THRESHOLD_STRICT == 100, snapshot
    assert snapshot["match_status"] == "MATCHED", snapshot

    stored = read_port_request(port_request["id"])
    assert stored["status"] == "VALIDATED", stored
    assert_instant(stored["validated_at"], "2026-08-06T15:30:00.000Z", "validated_at")
    # Friday 2026-08-07, Monday 2026-08-10, Tuesday 2026-08-11 - the weekend is
    # skipped, so the floor is not 2026-08-09.
    assert_instant(
        stored["earliest_cutover_at"], "2026-08-11T00:00:00.000Z", "earliest_cutover_at"
    )
    assert stored["last_match_points"] == 100, stored


def test_same_postal_network_report_is_same_location_and_keeps_registration_verified(api):
    """A **same-location** report changes nothing but `reported_state_code`, `reported_postal_code` and `last_network_report_at` — no status anywhere moves.

    The device reports CA/94601 while its current registration already stands at
    CA/94601, so the drift is same-location even though the device is nomadic.

    Design: Corner/calculations/same_postal_network_report_is_same_location_and_keeps_registration_verified
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1017", billing_name="ROWAN KK", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415609", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "2401")
    device = seed_device(
        account["id"],
        "AABBCC002401",
        device_type="SOFTPHONE",
        nomadic=True,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="17 ROWAN WAY",
        unit="3B",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration["id"], "VERIFIED")

    set_clock("2026-08-02T08:00:00.000Z")
    reported = validate_success(
        api.create_network_report(
            device["id"],
            {"reported_state_code": "CA", "reported_postal_code": "94601"},
            make_account_admin_headers(account["id"]),
        ),
        200,
    )

    assert reported["reported_state_code"] == "CA", reported
    assert reported["reported_postal_code"] == "94601", reported
    assert_instant(
        reported["last_network_report_at"],
        "2026-08-02T08:00:00.000Z",
        "last_network_report_at",
    )
    assert reported["registration_status"] == "REGISTERED", reported
    assert reported["calling_status"] == "UNRESTRICTED", reported

    stored_device = read_device(device["id"])
    assert stored_device["registration_status"] == "REGISTERED", stored_device
    assert stored_device["calling_status"] == "UNRESTRICTED", stored_device

    stored_registration = read_registration(registration["id"])
    assert stored_registration["verification_status"] == "VERIFIED", stored_registration
    assert_instant(
        stored_registration["verified_at"], "2026-08-01T00:00:00.000Z", "verified_at"
    )
    assert_null(stored_registration["superseded_at"], "superseded_at")

    stored_account = read_account(account["id"])
    assert stored_account["e911_compliance_posture"] == "COMPLIANT", stored_account


def test_posture_population_excludes_devices_that_hold_no_number(api):
    """The population it considers is exactly those devices of the account whose `assigned_number_id` is not null — a device holding no number is outside the population entirely, which is why releasing a number can improve an account's posture.

    Registering a second device with no number and no dispatchable location at
    all therefore leaves the account COMPLIANT.

    Design: Corner/calculations/posture_population_excludes_devices_that_hold_no_number
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1018", billing_name="SORREL SL", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415610", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "2501")
    device_a = seed_device(
        account["id"],
        "AABBCC002501",
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration_a = seed_registration(
        device_a["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="18 SORREL ST",
        unit="",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration_a["id"], "VERIFIED")
    assert read_account(account["id"])["e911_compliance_posture"] == "COMPLIANT"

    device_b = validate_success(
        api.create_device(
            make_device_payload(
                account["id"],
                mac_address="AABBCC002502",
                device_type="HANDSET",
                nomadic=True,
            ),
            make_account_admin_headers(account["id"]),
        ),
        201,
    )

    stored_account = read_account(account["id"])
    assert stored_account["e911_compliance_posture"] == "COMPLIANT", stored_account

    assert_null(device_b["assigned_number_id"], "assigned_number_id")
    assert device_b["registration_status"] == "PENDING_REGISTRATION", device_b
    assert device_b["calling_status"] == "UNRESTRICTED", device_b

    stored_a = read_device(device_a["id"])
    assert stored_a["registration_status"] == "REGISTERED", stored_a
    assert stored_a["calling_status"] == "UNRESTRICTED", stored_a


def test_reservation_selector_takes_the_lowest_line_number_not_the_oldest_row(api):
    """Those candidates are ranked by `line_number` ascending, compared as four-character strings, with ascending `created_at` as the tie-break — a tie-break that can only fire on a same-`line_number` data anomaly, since `line_number` is unique within a block.

    2603 is minted first, so an implementation ranking by row age would pick it;
    the ranking is on `line_number`, so 2601 wins.

    Design: Corner/calculations/reservation_selector_takes_the_lowest_line_number_not_the_oldest_row
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1019", billing_name="TANSY OY", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415611", total_capacity=10, max_concurrent_reservations=2
    )
    number_2603 = seed_phone_number(block["id"], "2603")
    number_2601 = seed_phone_number(block["id"], "2601")
    number_2602 = seed_phone_number(block["id"], "2602")

    reservation = validate_success(
        api.create_number_reservation(
            make_number_reservation_payload(
                block["id"],
                account["id"],
                block_version(block["id"]),
                purpose="NEW_LINE",
                reserved_from="2026-08-04T00:00:00.000Z",
                reserved_until="2026-08-06T00:00:00.000Z",
            ),
            make_numbering_admin_headers(),
        ),
        201,
    )

    assert reservation["number_id"] == number_2601["id"], reservation
    assert reservation["status"] == "HELD", reservation
    stored_reservation = read_reservation(reservation["id"])
    assert stored_reservation["number_id"] == number_2601["id"], stored_reservation

    assert read_phone_number(number_2601["id"])["status"] == "RESERVED"
    assert read_phone_number(number_2602["id"])["status"] == "AVAILABLE"
    assert read_phone_number(number_2603["id"])["status"] == "AVAILABLE"

    assert_block_census(
        read_number_block(block["id"]), minted=3, available=2, reserved=1, assigned=0, parked=0
    )


def test_unknown_country_code_falls_back_to_default_rate_and_unknown_risk(api):
    """`rate_cents_per_minute` is looked up by country code: 12 cents for `44`, 60 for `53`, 95 for `234`, 140 for `252`, and 75 cents for every other country code including the domestic `1`, which is not in the table.

    Country code 998 is in neither the rate table nor the country-risk table, so
    the same attempt also takes the 20-point unknown-country geography score,
    summing with 4 velocity points to a realtime score of 24.

    Design: Corner/calculations/unknown_country_code_falls_back_to_default_rate_and_unknown_risk
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1020",
        billing_name="UMBER AB",
        service_state_code="CA",
        status="ACTIVE",
        intl_calling_enabled=True,
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415612", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "2701")
    device = seed_device(
        account["id"],
        "AABBCC002701",
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="20 UMBER AVE",
        unit="",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration["id"], "VERIFIED")

    set_clock("2026-08-05T10:00:00.000Z")
    attempt = validate_success(
        api.create_call_attempt(
            device["id"],
            make_call_attempt_payload(
                destination_e164="+9985550001234",
                destination_country_code="998",
                requested_duration_seconds=60,
            ),
            make_account_admin_headers(account["id"]),
        ),
        201,
    )

    assert attempt["billable_minutes"] == 1 == billable_minutes(60), attempt
    assert_cents_equal(attempt["rate_cents_per_minute"], 75, "rate_cents_per_minute")
    assert rate_cents_per_minute("998") == DEFAULT_RATE_CENTS == 75
    assert_cents_equal(attempt["estimated_base_cents"], 75, "estimated_base_cents")
    assert estimated_base_cents("998", 60) == 75
    assert_cents_equal(attempt["day_subtotal_cents"], 75, "day_subtotal_cents")
    assert attempt["surcharge_pct_applied"] == 0 == surcharge_pct(75), attempt
    assert_cents_equal(
        attempt["projected_day_total_cents"], 75, "projected_day_total_cents"
    )
    assert projected_day_total_cents(75) == 75

    # 4 velocity points for the single row plus the 20-point unknown-country risk.
    assert country_risk_points("998") == DEFAULT_COUNTRY_RISK_POINTS == 20
    assert VELOCITY_POINTS_REALTIME * 1 + DEFAULT_COUNTRY_RISK_POINTS == 24
    assert attempt["realtime_risk_score"] == 24, attempt
    assert 24 < FRAUD_BLOCK_THRESHOLD
    assert attempt["decision"] == "ALLOWED", attempt
    assert_null(attempt["decision_error_id"], "decision_error_id")

    stored_device = read_device(device["id"])
    assert stored_device["calling_status"] == "UNRESTRICTED", stored_device
    assert stored_device["fraud_block_count"] == 0, stored_device


def test_a_one_second_call_still_bills_one_whole_minute(api):
    """`billable_minutes` is the greater of 1 and the request's duration in seconds divided by 60 rounded up — so 1 second and 60 seconds both bill one minute, 61 seconds bills two.

    A one-second call to country code 44 therefore bills the whole 12-cent
    minute rather than a fraction of it.

    Design: Corner/calculations/a_one_second_call_still_bills_one_whole_minute
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1021",
        billing_name="VIOLET SPA",
        service_state_code="CA",
        status="ACTIVE",
        intl_calling_enabled=True,
        intl_daily_cap_cents=2000,
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415613", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "2801")
    device = seed_device(
        account["id"],
        "AABBCC002801",
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="21 VIOLET LN",
        unit="",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration["id"], "VERIFIED")

    set_clock("2026-08-05T10:00:00.000Z")
    attempt = validate_success(
        api.create_call_attempt(
            device["id"],
            make_call_attempt_payload(
                destination_e164="+447700900500",
                destination_country_code="44",
                requested_duration_seconds=1,
            ),
            make_account_admin_headers(account["id"]),
        ),
        201,
    )

    assert attempt["billable_minutes"] == 1 == billable_minutes(1), attempt
    assert_cents_equal(attempt["rate_cents_per_minute"], 12, "rate_cents_per_minute")
    assert rate_cents_per_minute("44") == 12
    assert_cents_equal(attempt["estimated_base_cents"], 12, "estimated_base_cents")
    assert estimated_base_cents("44", 1) == 12
    assert_cents_equal(attempt["day_subtotal_cents"], 12, "day_subtotal_cents")
    assert attempt["surcharge_pct_applied"] == 0 == surcharge_pct(12), attempt
    assert_cents_equal(
        attempt["projected_day_total_cents"], 12, "projected_day_total_cents"
    )
    assert projected_day_total_cents(12) == 12
    assert attempt["decision"] == "ALLOWED", attempt


def test_remittance_run_voids_the_provisional_and_remits_the_full_final_amount(api):
    """First, every assessment of that jurisdiction with that `period_month`, `variant` `PROVISIONAL` and `status` `ASSESSED` moves `ASSESSED → VOIDED` with `voided_by_user_id` set to the sentinel `system:remittance-run`; the segregation-of-duties rule does not apply to these system voids, and no `version`-based concurrency token is involved.

    The run then writes the unprorated FINAL charge for the same month, so the
    85-cent provisional row is replaced by a 175-cent remitted one rather than
    added to it.

    Design: Corner/calculations/remittance_run_voids_the_provisional_and_remits_the_full_final_amount
    """
    set_clock("2026-08-17T00:00:00.000Z")
    account = seed_account(
        "ACCT1022", billing_name="WILLOW GMBH", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415614", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "2901")
    device = seed_device(
        account["id"],
        "AABBCC002901",
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="22 WILLOW WAY",
        unit="",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration["id"], "VERIFIED")

    provisional = assess_fee(account["id"], jurisdiction["id"], "2026-08")
    # Anchored on the 17th of a 31-day month: 31 - 17 + 1 == 15 active days.
    assert provisional["variant"] == "PROVISIONAL", provisional
    assert_cents_equal(provisional["amount_cents"], 85, "amount_cents")
    assert prorated_unit_fee_cents(175, 15, 31) == 85

    set_clock("2026-09-05T00:00:00.000Z")
    returned_jurisdiction = validate_success(
        api.create_remittance_run(
            jurisdiction["id"],
            make_remittance_run_payload("2026-08"),
            make_billing_admin_headers(BILLING_USER_ID),
        ),
        200,
    )
    assert returned_jurisdiction["id"] == jurisdiction["id"], returned_jurisdiction

    voided = validate_success(
        api.get_fee_assessment(
            provisional["id"], make_billing_admin_headers(BILLING_USER_ID)
        )
    )
    assert voided["variant"] == "PROVISIONAL", voided
    assert voided["billable_units"] == 1, voided
    assert voided["unit_fee_breakdown"] == [85], voided
    assert_cents_equal(voided["amount_cents"], 85, "amount_cents")
    assert voided["status"] == "VOIDED", voided
    # PRD §2.10 / §3.9: the sentinel is `system:remittance-run`.
    assert voided["voided_by_user_id"] == REMITTANCE_SENTINEL, voided

    rows, _meta = validate_paginated(
        api.list_fee_assessments(
            make_billing_admin_headers(BILLING_USER_ID),
            params={"jurisdiction_id": jurisdiction["id"], "variant": "FINAL"},
        )
    )
    assert len(rows) == 1, rows
    final_row = find_by(rows, variant="FINAL")
    assert_cents_equal(final_row["amount_cents"], 175, "amount_cents")
    assert final_row["unit_fee_breakdown"] == [175], final_row
    assert final_row["billable_units"] == 1, final_row
    assert final_row["unit_basis"] == "PER_LINE", final_row
    assert final_row["status"] == "REMITTED", final_row
    assert final_amount_cents(175, 1) == 175
    assert final_row["assessed_by_user_id"] == REMITTANCE_SENTINEL, final_row
    assert_instant(final_row["remitted_at"], "2026-09-05T00:00:00.000Z", "remitted_at")

    stored_jurisdiction = read_jurisdiction(jurisdiction["id"])
    assert_cents_equal(stored_jurisdiction["pending_fee_cents"], 0, "pending_fee_cents")
    assert_cents_equal(
        stored_jurisdiction["remitted_fee_cents"], 175, "remitted_fee_cents"
    )
    assert stored_jurisdiction["last_remitted_period"] == "2026-08", stored_jurisdiction

    stored_account = read_account(account["id"])
    assert_cents_equal(stored_account["fee_liability_cents"], 175, "fee_liability_cents")
