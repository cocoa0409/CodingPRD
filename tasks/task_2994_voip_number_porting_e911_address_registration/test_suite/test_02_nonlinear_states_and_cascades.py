"""Cyclic state machines and multi-level derived-state cascades.

Two families of behaviour are exercised here.

*Non-linear state machines.* A port request re-enters `SUBMITTED` after a
mismatch and leaves it a second time with the opposite outcome, and a device
advances its E911 dimension and its calling-restriction dimension without
either trigger disturbing the other.

*Transitive cascades.* One rejection walks port request, cutover slot,
temporary bridge, reservation, phone number and block census; one network
report walks device, registration, account posture and a sibling device that
the request never named.

Every test rebuilds its own preconditions against a fresh, empty database.
"""
from test_helpers import (
    LIAISON_USER_ID,
    PORTING_USER_ID,
    THRESHOLD_STRICT,
    assert_block_census,
    assert_instant,
    assert_null,
    find_by,
    make_account_admin_headers,
    make_calling_restriction_payload,
    make_carrier_liaison_headers,
    make_csr_snapshot_payload,
    make_network_report_payload,
    make_porting_specialist_headers,
    make_reject_payload,
    make_resubmit_payload,
    make_security_analyst_headers,
    post_matching_csr_snapshot,
    provision_bridge,
    read_account,
    read_cutover_slot,
    read_device,
    read_number_block,
    read_phone_number,
    read_port_request,
    read_registration,
    read_reservation,
    seed_account,
    seed_carrier,
    seed_cutover_slot,
    seed_device,
    seed_jurisdiction,
    seed_number_block,
    seed_phone_number,
    seed_registration,
    seed_reservation,
    set_clock,
    setup_account_and_block,
    setup_compliant_device,
    setup_submitted_port_request,
    validate_paginated,
    validate_success,
    verify_registration,
    book_slot,
    port_request_version,
)

# ----------------------------------------------------------------------
# Private helpers. Each one performs only setup hops and stops at the last
# state that is internally consistent, so a test can compose them freely.
# ----------------------------------------------------------------------
PORT_CLOCK_ISO = "2026-08-03T09:00:00.000Z"
DEVICE_CLOCK_ISO = "2026-08-01T00:00:00.000Z"


def _submitted_strict_port_request() -> dict:
    """An ACTIVE account, a STRICT carrier and a freshly filed port request.

    The carrier demands three business days of firm-order-commitment interval
    and sixty minutes of quiet time. The subscriber claims a PIN of 9182, which
    the carrier's record will not agree with.
    """
    set_clock(PORT_CLOCK_ISO)
    return setup_submitted_port_request(
        account_number="ACCT0005",
        ocn="LT01",
        carrier_overrides={
            "name": "Legacy Telco",
            "csr_match_policy": "STRICT",
            "porting_buffer_minutes": 60,
            "foc_business_days": 3,
        },
        account_overrides={
            "billing_name": "EVERGREEN CO",
            "service_state_code": "CA",
            "status": "ACTIVE",
        },
        requested_numbers=["+14155550001"],
        claimed_account_number="CSR-ACC-001",
        claimed_pin="9182",
        claimed_billing_name="EVERGREEN CO",
        claimed_address_line1="500 CEDAR ST",
        claimed_zip="94601",
    )


def _post_carrier_record(api, port_request_id: str, expected_status: int = 201) -> dict:
    """Transcribe the losing carrier's record: PIN 0000, the other four agree."""
    payload = make_csr_snapshot_payload(
        port_request_version(port_request_id),
        account_number_on_file="CSR-ACC-001",
        pin_on_file="0000",
        billing_name_on_file="EVERGREEN CO",
        address_line1_on_file="500 CEDAR ST",
        zip_on_file="94601",
    )
    return validate_success(
        api.create_csr_snapshot(
            port_request_id, payload, make_carrier_liaison_headers(LIAISON_USER_ID)
        ),
        expected_status,
    )


def _correct_the_pin(api, port_request_id: str) -> dict:
    """Resubmit with the PIN corrected to the value the carrier holds."""
    payload = make_resubmit_payload(
        claimed_account_number="CSR-ACC-001",
        claimed_pin="0000",
        claimed_billing_name="EVERGREEN CO",
        claimed_address_line1="500 CEDAR ST",
        claimed_zip="94601",
    )
    return validate_success(
        api.resubmit_port_request(
            port_request_id, payload, make_porting_specialist_headers(PORTING_USER_ID)
        ),
        200,
    )


def _snapshot_rows(api, port_request_id: str) -> list:
    """Every CSR snapshot ever posted against the request, newest first."""
    rows, _meta = validate_paginated(
        api.list_csr_snapshots(
            port_request_id, make_porting_specialist_headers(PORTING_USER_ID)
        )
    )
    return rows


# ----------------------------------------------------------------------
# Difficulty / non_linear_state_machine
# port_request_cycles_csr_mismatch_back_to_submitted_then_validates
# ----------------------------------------------------------------------
def test_port_request_cycles_csr_mismatch_back_to_submitted_then_validates__mismatch_enters_csr_mismatch(api):
    """If `match_status` is `MISMATCHED`, the request moves `SUBMITTED → CSR_MISMATCH` and both `validated_at` and `earliest_cutover_at` are left exactly as they were — null on a first-pass mismatch.

    The carrier is STRICT, so the 30-point PIN disagreement leaves 70 of the
    100 points it demands.

    Design: Difficulty/non_linear_state_machine/port_request_cycles_csr_mismatch_back_to_submitted_then_validates
    """
    scenario = _submitted_strict_port_request()
    port_request_id = scenario["port_request"]["id"]
    assert scenario["port_request"]["status"] == "SUBMITTED"

    snapshot = _post_carrier_record(api, port_request_id)

    # account_number 40 + billing_name 15 + service_address_line1 10 + service_zip 5
    assert snapshot["match_points"] == 70
    assert snapshot["threshold_applied"] == THRESHOLD_STRICT
    assert snapshot["match_status"] == "MISMATCHED"
    assert snapshot["mismatch_fields"] == ["pin"]
    assert_null(snapshot["superseded_at"], "snapshot.superseded_at")

    port_request = read_port_request(port_request_id)
    assert port_request["status"] == "CSR_MISMATCH"
    assert port_request["last_match_points"] == 70
    assert port_request["last_mismatch_fields"] == ["pin"]
    assert_null(port_request["validated_at"], "port_request.validated_at")
    assert_null(port_request["earliest_cutover_at"], "port_request.earliest_cutover_at")
    assert port_request["resubmission_count"] == 0


def test_port_request_cycles_csr_mismatch_back_to_submitted_then_validates__resubmit_reenters_submitted(api):
    """A successful resubmission overwrites the five claimed values from the request body, increments `resubmission_count` by 1, and returns the request to `SUBMITTED` — closing the cycle `CSR_MISMATCH → SUBMITTED` or `REJECTED → SUBMITTED` so that the liaison can transcribe a fresh carrier record.

    The backwards edge re-enters a state the request has already visited and
    wipes the evaluation the first visit produced.

    Design: Difficulty/non_linear_state_machine/port_request_cycles_csr_mismatch_back_to_submitted_then_validates
    """
    scenario = _submitted_strict_port_request()
    port_request_id = scenario["port_request"]["id"]
    _post_carrier_record(api, port_request_id)
    assert read_port_request(port_request_id)["status"] == "CSR_MISMATCH"

    resubmitted = _correct_the_pin(api, port_request_id)

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["resubmission_count"] == 1
    assert_null(resubmitted["last_match_points"], "port_request.last_match_points")
    assert resubmitted["last_mismatch_fields"] == []
    assert_null(resubmitted["validated_at"], "port_request.validated_at")
    assert_null(resubmitted["earliest_cutover_at"], "port_request.earliest_cutover_at")
    assert_null(resubmitted["last_rejection_code"], "port_request.last_rejection_code")
    assert resubmitted["claimed_pin"] == "0000"
    assert resubmitted["created_by_user_id"] == PORTING_USER_ID


def test_port_request_cycles_csr_mismatch_back_to_submitted_then_validates__second_pass_validates(api):
    """If `match_status` is `MATCHED`, the request moves `SUBMITTED → VALIDATED`, `validated_at` is set to the logical clock, and `earliest_cutover_at` is computed as described below.

    The second visit to `SUBMITTED` ends in the opposite outcome to the first,
    and the superseded first snapshot survives in the history.

    Design: Difficulty/non_linear_state_machine/port_request_cycles_csr_mismatch_back_to_submitted_then_validates
    """
    scenario = _submitted_strict_port_request()
    port_request_id = scenario["port_request"]["id"]
    first_snapshot = _post_carrier_record(api, port_request_id)
    _correct_the_pin(api, port_request_id)

    second_snapshot = _post_carrier_record(api, port_request_id)

    assert second_snapshot["match_points"] == 100
    assert second_snapshot["match_status"] == "MATCHED"
    assert second_snapshot["mismatch_fields"] == []
    assert_null(second_snapshot["superseded_at"], "second snapshot.superseded_at")

    port_request = read_port_request(port_request_id)
    assert port_request["status"] == "VALIDATED"
    assert_instant(port_request["validated_at"], PORT_CLOCK_ISO, "validated_at")
    # 2026-08-03 is a Monday, so three business days land on Thursday 2026-08-06.
    assert_instant(
        port_request["earliest_cutover_at"],
        "2026-08-06T00:00:00.000Z",
        "earliest_cutover_at",
    )
    assert port_request["last_match_points"] == 100
    assert port_request["last_mismatch_fields"] == []
    assert port_request["resubmission_count"] == 1

    rows = _snapshot_rows(api, port_request_id)
    assert len(rows) == 2
    superseded = find_by(rows, id=first_snapshot["id"])
    assert_instant(superseded["superseded_at"], PORT_CLOCK_ISO, "superseded_at")
    assert superseded["match_points"] == 70


# ----------------------------------------------------------------------
# Difficulty / non_linear_state_machine
# device_registration_and_calling_dimensions_advance_independently
# ----------------------------------------------------------------------
def _nomadic_registered_device() -> dict:
    """A nomadic, number-holding device whose CA location is VERIFIED.

    The device therefore sits at `registration_status` `REGISTERED` and
    `calling_status` `UNRESTRICTED`, with its account `COMPLIANT`.
    """
    set_clock(DEVICE_CLOCK_ISO)
    scenario = setup_compliant_device(
        account_number="ACCT0006",
        npa_nxx="415559",
        line_number="0501",
        mac_address="AABBCC000041",
        device_overrides={"device_type": "SOFTPHONE", "nomadic": True},
        registration_overrides={
            "address_line1": "700 ELM ST",
            "city": "OAKLAND",
            "postal_code": "94601",
        },
        account_overrides={
            "billing_name": "FIRWOOD LTD",
            "status": "ACTIVE",
            "intl_calling_enabled": True,
            "intl_daily_cap_cents": 100000,
        },
        block_overrides={"total_capacity": 20, "max_concurrent_reservations": 5},
    )
    assert scenario["device"]["registration_status"] == "REGISTERED"
    assert scenario["device"]["calling_status"] == "UNRESTRICTED"
    assert scenario["account"]["e911_compliance_posture"] == "COMPLIANT"
    return scenario


def _block_intl(api, device_id: str) -> dict:
    return validate_success(
        api.create_calling_restriction(
            device_id,
            make_calling_restriction_payload("BLOCK_INTL", note="carrier abuse alert"),
            make_security_analyst_headers(),
        ),
        200,
    )


def _report_cross_jurisdiction(api, device_id: str, account_id: str,
                               postal_code: str = "89101") -> dict:
    return validate_success(
        api.create_network_report(
            device_id,
            make_network_report_payload("NV", postal_code),
            make_account_admin_headers(account_id),
        ),
        200,
    )


def test_device_registration_and_calling_dimensions_advance_independently__block_intl_spares_registration(api):
    """Neither of these two actions computes a fraud score, so `toll_fraud_score` is left as it stands, and neither touches `fraud_block_count` or `registration_status`.

    Design: Difficulty/non_linear_state_machine/device_registration_and_calling_dimensions_advance_independently
    """
    scenario = _nomadic_registered_device()
    device_id = scenario["device"]["id"]
    registration_id = scenario["registration"]["id"]

    blocked = _block_intl(api, device_id)

    assert blocked["calling_status"] == "INTL_BLOCKED"
    assert blocked["registration_status"] == "REGISTERED"
    assert blocked["fraud_block_count"] == 0
    assert blocked["toll_fraud_score"] == scenario["device"]["toll_fraud_score"]
    assert blocked["version"] == scenario["device"]["version"] + 1

    registration = read_registration(registration_id)
    assert registration["verification_status"] == "VERIFIED"
    assert_null(registration["superseded_at"], "registration.superseded_at")


def test_device_registration_and_calling_dimensions_advance_independently__relocation_spares_calling_status(api):
    """A **cross-jurisdiction** report moves the device `REGISTERED → RELOCATION_DETECTED` — the device has crossed a 911 jurisdiction line and its dispatchable location is now positively wrong — and likewise drives its current registration `VERIFIED → STALE`.

    The analyst's international block is already in force, and the relocation
    neither lifts nor strengthens it.

    Design: Difficulty/non_linear_state_machine/device_registration_and_calling_dimensions_advance_independently
    """
    scenario = _nomadic_registered_device()
    device_id = scenario["device"]["id"]
    account_id = scenario["account"]["id"]
    registration_id = scenario["registration"]["id"]
    blocked = _block_intl(api, device_id)
    assert blocked["calling_status"] == "INTL_BLOCKED"

    relocated = _report_cross_jurisdiction(api, device_id, account_id)

    assert relocated["registration_status"] == "RELOCATION_DETECTED"
    assert relocated["calling_status"] == "INTL_BLOCKED"

    registration = read_registration(registration_id)
    assert registration["verification_status"] == "STALE"
    assert_null(registration["superseded_at"], "registration.superseded_at")


def test_device_registration_and_calling_dimensions_advance_independently__report_records_location(api):
    """In every case `reported_state_code`, `reported_postal_code` and `last_network_report_at` are stored on the device, `last_network_report_at` taking the logical clock, and the device's `version` increments by 1.

    The posture recomputation the stale address triggers reaches the account
    without disturbing either dimension of the reporting device.

    Design: Difficulty/non_linear_state_machine/device_registration_and_calling_dimensions_advance_independently
    """
    scenario = _nomadic_registered_device()
    device_id = scenario["device"]["id"]
    account_id = scenario["account"]["id"]
    before = _block_intl(api, device_id)

    reported = _report_cross_jurisdiction(api, device_id, account_id)

    assert reported["reported_state_code"] == "NV"
    assert reported["reported_postal_code"] == "89101"
    assert_instant(
        reported["last_network_report_at"], DEVICE_CLOCK_ISO, "last_network_report_at"
    )
    assert reported["version"] > before["version"]
    assert reported["calling_status"] == "INTL_BLOCKED"

    # The account is AT_RISK because one device of its population is now stale.
    account = read_account(account_id)
    assert account["e911_compliance_posture"] == "AT_RISK"
    assert read_device(device_id)["registration_status"] == "RELOCATION_DETECTED"


# ----------------------------------------------------------------------
# Difficulty / transitive_cascade
# port_reject_cascades_slot_bridge_reservation_number_and_block_census
# ----------------------------------------------------------------------
def _bridged_port_request(api) -> dict:
    """A SCHEDULED port request with a BOOKED slot and a PROVISIONED bridge.

    The bridge consumes a `PORT_BRIDGE` reservation over the block's single
    minted number, so the whole rejection chain has one row at every level.
    """
    set_clock(PORT_CLOCK_ISO)
    account = seed_account(
        "ACCT0007",
        billing_name="GRANITE GROUP",
        service_state_code="CA",
        status="ACTIVE",
    )
    carrier = seed_carrier(
        "NL02",
        name="Northline Telecom",
        csr_match_policy="STRICT",
        porting_buffer_minutes=60,
        foc_business_days=3,
    )
    jurisdiction = seed_jurisdiction("CA", "06041")
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx="415560",
        total_capacity=20,
        max_concurrent_reservations=5,
    )
    number = seed_phone_number(block["id"], "0601")
    reservation = seed_reservation(
        block["id"],
        account["id"],
        number_id=number["id"],
        purpose="PORT_BRIDGE",
        # reserved_from may not lie before the logical clock, so the hold opens
        # exactly at it and runs well past the cutover window.
        reserved_from=PORT_CLOCK_ISO,
        reserved_until="2026-08-20T00:00:00.000Z",
    )
    port_request = validate_success(
        api.create_port_request(
            {
                "account_id": account["id"],
                "losing_carrier_id": carrier["id"],
                "requested_numbers": ["+14155550002"],
                "claimed_account_number": "CSR-ACC-007",
                "claimed_pin": "7777",
                "claimed_billing_name": "GRANITE GROUP",
                "claimed_address_line1": "900 QUARRY RD",
                "claimed_zip": "94566",
            },
            make_porting_specialist_headers(PORTING_USER_ID),
        ),
        201,
    )
    post_matching_csr_snapshot(port_request["id"], port_request)
    slot = seed_cutover_slot(
        carrier["id"],
        window_start="2026-08-10T14:00:00.000Z",
        window_end="2026-08-10T18:00:00.000Z",
    )
    port_request = book_slot(port_request["id"], slot["id"])
    bridge = provision_bridge(port_request["id"], reservation["id"])
    assert port_request["status"] == "SCHEDULED"
    assert bridge["status"] == "PROVISIONED"
    return {
        "account": account,
        "carrier": carrier,
        "jurisdiction": jurisdiction,
        "block": block,
        "number": number,
        "reservation": reservation,
        "port_request": port_request,
        "slot": slot,
        "bridge": bridge,
    }


def _reject_for_pending_balance(api, port_request_id: str) -> dict:
    return validate_success(
        api.reject_port_request(
            port_request_id,
            make_reject_payload(
                "PENDING_BALANCE", note="unpaid final invoice at losing carrier"
            ),
            make_carrier_liaison_headers(LIAISON_USER_ID),
        ),
        200,
    )


def test_port_reject_cascades_slot_bridge_reservation_number_and_block_census__request_and_slot(api):
    """The booked cutover slot moves `BOOKED → RELEASED`, with `booked_port_request_id` and `booked_at` both cleared to null and the slot's `version` incremented by 1; a `RELEASED` slot is terminal, can never be re-booked, and no longer blocks future candidate windows in the overlap scan of §3.5.

    The rejection itself carries the request to `REJECTED` with the reason code
    the carrier supplied, which is what makes the first cascade link fire.

    Design: Difficulty/transitive_cascade/port_reject_cascades_slot_bridge_reservation_number_and_block_census
    """
    scenario = _bridged_port_request(api)
    port_request_id = scenario["port_request"]["id"]
    slot_before = read_cutover_slot(scenario["slot"]["id"])
    assert slot_before["status"] == "BOOKED"
    assert slot_before["booked_port_request_id"] == port_request_id

    rejected = _reject_for_pending_balance(api, port_request_id)

    assert rejected["status"] == "REJECTED"
    assert rejected["last_rejection_code"] == "PENDING_BALANCE"
    assert rejected["version"] == scenario["port_request"]["version"] + 1

    slot = read_cutover_slot(scenario["slot"]["id"])
    assert slot["status"] == "RELEASED"
    assert_null(slot["booked_port_request_id"], "slot.booked_port_request_id")
    assert_null(slot["booked_at"], "slot.booked_at")
    assert slot["version"] == slot_before["version"] + 1


def test_port_reject_cascades_slot_bridge_reservation_number_and_block_census__bridge_and_reservation(api):
    """Because that slot was released, every temporary bridge of this request in `PROVISIONED` or `ACTIVE` status becomes `ORPHANED` with `released_at` set to the logical clock — a bridge that never activated is orphaned on exactly the same terms as one that did.

    The orphaned bridge in turn releases the reservation it consumed, which the
    PRD marks `BRIDGE_ORPHANED` rather than `CUTOVER_COMPLETED`.

    Design: Difficulty/transitive_cascade/port_reject_cascades_slot_bridge_reservation_number_and_block_census
    """
    scenario = _bridged_port_request(api)
    bridge_id = scenario["bridge"]["id"]
    reservation_id = scenario["reservation"]["id"]
    assert read_reservation(reservation_id)["status"] == "CONSUMED"

    _reject_for_pending_balance(api, scenario["port_request"]["id"])

    bridge = validate_success(
        api.get_temporary_bridge(bridge_id, make_porting_specialist_headers()), 200
    )
    assert bridge["status"] == "ORPHANED"
    assert_instant(bridge["released_at"], PORT_CLOCK_ISO, "bridge.released_at")
    assert_null(bridge["activated_at"], "bridge.activated_at")
    assert bridge["bridge_number_id"] == scenario["number"]["id"]

    reservation = read_reservation(reservation_id)
    assert reservation["status"] == "RELEASED"
    assert reservation["released_reason"] == "BRIDGE_ORPHANED"


def test_port_reject_cascades_slot_bridge_reservation_number_and_block_census__number_and_census(api):
    """Because that reservation was released for an orphaned bridge rather than a completed cutover, its phone number moves `RESERVED → PARKED` rather than back to `AVAILABLE`, taking a `parked_until` of the logical clock plus 168 hours and a `park_cycle_count` incremented by 1.

    The census then moves one unit out of `reserved_count` and into
    `parked_count`, five levels away from the endpoint that was called.

    Design: Difficulty/transitive_cascade/port_reject_cascades_slot_bridge_reservation_number_and_block_census
    """
    scenario = _bridged_port_request(api)
    number_id = scenario["number"]["id"]
    block_id = scenario["block"]["id"]
    block_before = read_number_block(block_id)
    assert read_phone_number(number_id)["status"] == "RESERVED"
    assert_block_census(block_before, minted=1, available=0, reserved=1, assigned=0, parked=0)

    _reject_for_pending_balance(api, scenario["port_request"]["id"])

    number = read_phone_number(number_id)
    assert number["status"] == "PARKED"
    # 2026-08-03T09:00:00Z plus the 168-hour cooling-off period.
    assert_instant(number["parked_until"], "2026-08-10T09:00:00.000Z", "parked_until")
    assert number["park_cycle_count"] == 1
    assert_null(number["assigned_account_id"], "number.assigned_account_id")

    block = read_number_block(block_id)
    assert_block_census(block, minted=1, available=0, reserved=0, assigned=0, parked=1)
    assert block["version"] == block_before["version"] + 1


# ----------------------------------------------------------------------
# Difficulty / transitive_cascade
# network_report_cascades_registration_posture_and_sibling_device_block
# ----------------------------------------------------------------------
def _two_registered_devices(sibling_nomadic: bool) -> dict:
    """Two number-holding devices of one account, both VERIFIED and settled.

    Device A is nomadic and reports from postal code 94601; device B is the
    sibling the network report will never name. Verifying B last carries the
    account back to `COMPLIANT`, which lifts the international block the
    intermediate `AT_RISK` sweep imposed, so the state left behind is stable.
    """
    set_clock(DEVICE_CLOCK_ISO)
    scenario = setup_account_and_block(
        account_number="ACCT0008",
        npa_nxx="415561",
        account_overrides={
            "billing_name": "HAZEL HOLDINGS",
            "service_state_code": "CA",
            "status": "ACTIVE",
            "intl_calling_enabled": True,
            "intl_daily_cap_cents": 100000,
        },
        block_overrides={"total_capacity": 20, "max_concurrent_reservations": 5},
    )
    account_id = scenario["account"]["id"]
    jurisdiction_id = scenario["jurisdiction"]["id"]
    number_a = seed_phone_number(scenario["block"]["id"], "0701")
    number_b = seed_phone_number(scenario["block"]["id"], "0702")

    device_a = seed_device(
        account_id,
        "AABBCC000051",
        device_type="SOFTPHONE",
        nomadic=True,
        assigned_number_id=number_a["id"],
    )
    registration_a = seed_registration(
        device_a["id"],
        jurisdiction_id,
        account_id,
        address_line1="800 LAUREL LN",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration_a["id"])

    device_b = seed_device(
        account_id,
        "AABBCC000052",
        device_type="BASE_STATION",
        nomadic=sibling_nomadic,
        assigned_number_id=number_b["id"],
    )
    registration_b = seed_registration(
        device_b["id"],
        jurisdiction_id,
        account_id,
        address_line1="801 LAUREL LN",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration_b["id"])

    scenario.update(
        {
            "number_a": number_a,
            "number_b": number_b,
            "device_a": read_device(device_a["id"]),
            "device_b": read_device(device_b["id"]),
            "registration_a": read_registration(registration_a["id"]),
            "registration_b": read_registration(registration_b["id"]),
            "account": read_account(account_id),
        }
    )
    assert scenario["account"]["e911_compliance_posture"] == "COMPLIANT"
    assert scenario["device_a"]["registration_status"] == "REGISTERED"
    assert scenario["device_a"]["calling_status"] == "UNRESTRICTED"
    assert scenario["device_b"]["registration_status"] == "REGISTERED"
    assert scenario["device_b"]["calling_status"] == "UNRESTRICTED"
    return scenario


def test_network_report_cascades_registration_posture_and_sibling_device_block__registration_and_posture(api):
    """From those classifications the posture follows: `BLOCKED` if any device in the population is hard-failed or overdue; otherwise `AT_RISK` if any device is stale or in grace; otherwise `COMPLIANT`, including the vacuous case where the population is empty.

    The reporting device's own registration goes stale first, which is the link
    that carries the recomputation up to the account.

    Design: Difficulty/transitive_cascade/network_report_cascades_registration_posture_and_sibling_device_block
    """
    scenario = _two_registered_devices(sibling_nomadic=True)
    account_id = scenario["account"]["id"]
    device_a_id = scenario["device_a"]["id"]

    reported = _report_cross_jurisdiction(api, device_a_id, account_id, "89052")

    assert reported["registration_status"] == "RELOCATION_DETECTED"
    assert reported["reported_state_code"] == "NV"
    assert reported["reported_postal_code"] == "89052"

    registration_a = read_registration(scenario["registration_a"]["id"])
    assert registration_a["verification_status"] == "STALE"

    account = read_account(account_id)
    assert account["e911_compliance_posture"] == "AT_RISK"
    assert account["version"] > scenario["account"]["version"]


def test_network_report_cascades_registration_posture_and_sibling_device_block__nomadic_sibling_blocked(api):
    """Moving to `AT_RISK` sends every device of the account that is `nomadic` and currently `UNRESTRICTED` to `INTL_BLOCKED`; non-nomadic devices are left alone by this sweep.

    The sibling device is never named in the request and its own dispatchable
    location stays perfectly good, yet the posture sweep still reaches it.

    Design: Difficulty/transitive_cascade/network_report_cascades_registration_posture_and_sibling_device_block
    """
    scenario = _two_registered_devices(sibling_nomadic=True)
    account_id = scenario["account"]["id"]

    _report_cross_jurisdiction(api, scenario["device_a"]["id"], account_id, "89052")

    device_b = read_device(scenario["device_b"]["id"])
    assert device_b["calling_status"] == "INTL_BLOCKED"
    assert device_b["registration_status"] == "REGISTERED"
    assert device_b["version"] > scenario["device_b"]["version"]

    registration_b = read_registration(scenario["registration_b"]["id"])
    assert registration_b["verification_status"] == "VERIFIED"
    assert_null(registration_b["superseded_at"], "sibling registration.superseded_at")

    device_a = read_device(scenario["device_a"]["id"])
    assert device_a["calling_status"] == "INTL_BLOCKED"


def test_network_report_cascades_registration_posture_and_sibling_device_block__stationary_sibling_spared(api):
    """Moving to `AT_RISK` sends every device of the account that is `nomadic` and currently `UNRESTRICTED` to `INTL_BLOCKED`; non-nomadic devices are left alone by this sweep.

    The same cascade stops short of a stationary sibling, so the sweep's
    population is narrower than the posture's own population.

    Design: Difficulty/transitive_cascade/network_report_cascades_registration_posture_and_sibling_device_block
    """
    scenario = _two_registered_devices(sibling_nomadic=False)
    account_id = scenario["account"]["id"]

    _report_cross_jurisdiction(api, scenario["device_a"]["id"], account_id, "89052")

    assert read_account(account_id)["e911_compliance_posture"] == "AT_RISK"
    # The nomadic reporter is swept, which proves the sweep ran at all.
    assert read_device(scenario["device_a"]["id"])["calling_status"] == "INTL_BLOCKED"

    device_b = read_device(scenario["device_b"]["id"])
    assert device_b["nomadic"] is False
    assert device_b["calling_status"] == "UNRESTRICTED"
    assert device_b["registration_status"] == "REGISTERED"
