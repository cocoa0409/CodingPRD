"""State-machine behaviour: initial states, declared transitions, invalid
transitions, terminal lockdown, temporal preconditions and the derived-state
bubble-up the PRD specifies for the account compliance posture.

Every test builds its own preconditions against an empty database and reads the
logical clock the PRD pins rather than any wall clock.
"""
from test_helpers import (
    ApiErrorId,
    LIAISON_USER_ID,
    PERFECT_MATCH_POINTS,
    PORTING_USER_ID,
    THRESHOLD_STRICT,
    assert_block_census,
    assert_common_fields,
    assert_instant,
    assert_null,
    assert_version,
    book_slot,
    get_success_data,
    make_account_admin_headers,
    make_cancel_payload,
    make_carrier_liaison_headers,
    make_csr_snapshot_payload,
    make_device_payload,
    make_e911_validator_headers,
    make_numbering_admin_headers,
    make_port_request_payload,
    make_porting_specialist_headers,
    make_resubmit_payload,
    make_verify_payload,
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
    validate_error,
    validate_success,
    verify_registration,
)


def test_new_port_request_starts_in_submitted_with_null_derived_fields(api):
    """A new request begins in `SUBMITTED` with `resubmission_count` at 0, `last_rejection_code` null, `last_match_points` null, `last_mismatch_fields` an empty array, `validated_at` null and `earliest_cutover_at` null.

    Design: Corner/state_machines/new_port_request_starts_in_submitted_with_null_derived_fields
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1006", billing_name="GORSE LTD", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "GL08",
        name="Gorse Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=60,
        foc_business_days=3,
    )

    response = api.create_port_request(
        make_port_request_payload(
            account["id"],
            carrier["id"],
            requested_numbers=["+14155551701", "+14155551702"],
            claimed_account_number="CSR-1006",
            claimed_pin="1006",
            claimed_billing_name="GORSE LTD",
            claimed_address_line1="6 GORSE LN",
            claimed_zip="94577",
        ),
        make_porting_specialist_headers(PORTING_USER_ID),
    )
    port_request = validate_success(response, 201)

    assert_common_fields(port_request, "port request")
    assert port_request["status"] == "SUBMITTED", (
        f"a freshly filed port request must be SUBMITTED, got {port_request['status']!r}"
    )
    assert port_request["resubmission_count"] == 0, (
        f"resubmission_count must start at 0, got {port_request['resubmission_count']!r}"
    )
    assert_null(port_request["last_rejection_code"], "last_rejection_code")
    assert_null(port_request["last_match_points"], "last_match_points")
    assert port_request["last_mismatch_fields"] == [], (
        "last_mismatch_fields must be an empty array before any comparison, got "
        f"{port_request['last_mismatch_fields']!r}"
    )
    assert_null(port_request["validated_at"], "validated_at")
    assert_null(port_request["earliest_cutover_at"], "earliest_cutover_at")
    assert_version(port_request, 1, "port request")


def test_matched_csr_snapshot_moves_port_request_submitted_to_validated(api):
    """If `match_status` is `MATCHED`, the request moves `SUBMITTED → VALIDATED`, `validated_at` is set to the logical clock, and `earliest_cutover_at` is computed as described below.

    The clock sits on Monday 2026-08-03 and the losing carrier demands three
    business days, so the firm-order-commitment floor lands on Thursday
    2026-08-06 at midnight UTC.

    Design: Corner/state_machines/matched_csr_snapshot_moves_port_request_submitted_to_validated
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1007", billing_name="HAZEL NV", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "HL09",
        name="Hazel Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=60,
        foc_business_days=3,
    )
    port_request = get_success_data(
        api.create_port_request(
            make_port_request_payload(
                account["id"],
                carrier["id"],
                requested_numbers=["+14155551703"],
                claimed_account_number="CSR-1007",
                claimed_pin="1007",
                claimed_billing_name="HAZEL NV",
                claimed_address_line1="7 HAZEL CT",
                claimed_zip="94577",
            ),
            make_porting_specialist_headers(PORTING_USER_ID),
        )
    )

    response = api.create_csr_snapshot(
        port_request["id"],
        make_csr_snapshot_payload(
            port_request["version"],
            account_number_on_file="CSR-1007",
            pin_on_file="1007",
            billing_name_on_file="HAZEL NV",
            address_line1_on_file="7 HAZEL CT",
            zip_on_file="94577",
        ),
        make_carrier_liaison_headers(LIAISON_USER_ID),
    )
    snapshot = validate_success(response, 201)

    assert snapshot["match_points"] == PERFECT_MATCH_POINTS, (
        f"all five comparison points agree, so match_points must be "
        f"{PERFECT_MATCH_POINTS}, got {snapshot['match_points']!r}"
    )
    assert snapshot["threshold_applied"] == THRESHOLD_STRICT, (
        f"a STRICT carrier applies a threshold of {THRESHOLD_STRICT}, got "
        f"{snapshot['threshold_applied']!r}"
    )
    assert snapshot["match_status"] == "MATCHED", (
        f"match_points at or above the threshold is MATCHED, got {snapshot['match_status']!r}"
    )
    assert snapshot["mismatch_fields"] == [], (
        f"nothing disagreed, so mismatch_fields must be empty, got {snapshot['mismatch_fields']!r}"
    )
    assert_null(snapshot["superseded_at"], "snapshot.superseded_at")

    updated = read_port_request(port_request["id"])
    assert updated["status"] == "VALIDATED", (
        f"a MATCHED snapshot drives SUBMITTED -> VALIDATED, got {updated['status']!r}"
    )
    assert updated["last_match_points"] == PERFECT_MATCH_POINTS, (
        f"last_match_points echoes the snapshot, got {updated['last_match_points']!r}"
    )
    assert updated["last_mismatch_fields"] == [], (
        f"last_mismatch_fields echoes the snapshot, got {updated['last_mismatch_fields']!r}"
    )
    assert_instant(updated["validated_at"], "2026-08-03T09:00:00.000Z", "validated_at")
    assert_instant(
        updated["earliest_cutover_at"], "2026-08-06T00:00:00.000Z", "earliest_cutover_at"
    )
    assert_version(updated, 2, "port request")


def test_resubmit_on_a_submitted_port_request_is_rejected(api):
    """Resubmission is permitted from exactly two statuses, `CSR_MISMATCH` and `REJECTED`; from anywhere else it is `ERR_PORT_REQUEST_STATE_INVALID`.

    Design: Corner/state_machines/resubmit_on_a_submitted_port_request_is_rejected
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1008", billing_name="IVY GMBH", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "IL10",
        name="Ivy Legacy",
        csr_match_policy="RELAXED",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )
    port_request = get_success_data(
        api.create_port_request(
            make_port_request_payload(
                account["id"],
                carrier["id"],
                requested_numbers=["+14155551704"],
                claimed_account_number="CSR-1008",
                claimed_pin="1008",
                claimed_billing_name="IVY GMBH",
                claimed_address_line1="8 IVY ROW",
                claimed_zip="94577",
            ),
            make_porting_specialist_headers(PORTING_USER_ID),
        )
    )
    assert port_request["status"] == "SUBMITTED", "setup step failed: expected SUBMITTED"

    response = api.resubmit_port_request(
        port_request["id"],
        make_resubmit_payload(
            claimed_account_number="CSR-1008B",
            claimed_pin="9008",
            claimed_billing_name="IVY GMBH",
            claimed_address_line1="8 IVY ROW",
            claimed_zip="94577",
        ),
        make_porting_specialist_headers(PORTING_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_PORT_REQUEST_STATE_INVALID.value, 409)

    unchanged = read_port_request(port_request["id"])
    assert unchanged["status"] == "SUBMITTED", (
        f"a refused resubmission leaves the request SUBMITTED, got {unchanged['status']!r}"
    )
    assert unchanged["resubmission_count"] == 0, (
        f"a refused resubmission does not spend the budget, got "
        f"{unchanged['resubmission_count']!r}"
    )
    assert unchanged["claimed_account_number"] == "CSR-1008", (
        "a refused resubmission must not overwrite the claimed values, got "
        f"{unchanged['claimed_account_number']!r}"
    )
    assert_version(unchanged, 1, "port request")


def test_verifying_an_already_verified_registration_is_rejected(api):
    """Only an `E911Validator` records an outcome, and only on a registration whose `verification_status` is `UNVERIFIED` or `STALE`; a row that is already `VERIFIED`, or that is `REJECTED` or `SUPERSEDED`, is refused with `ERR_REGISTRATION_NOT_VERIFIABLE`.

    Design: Corner/state_machines/verifying_an_already_verified_registration_is_rejected
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1009", billing_name="JASMINE BV", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415604", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "1801")
    device = seed_device(
        account["id"],
        "AABBCC001801",
        device_type="HANDSET",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="9 JASMINE AVE",
        unit="",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    verified = verify_registration(registration["id"], "VERIFIED")
    assert verified["verification_status"] == "VERIFIED", (
        "setup step failed: the first verification did not land on VERIFIED"
    )

    response = api.verify_e911_registration(
        registration["id"], make_verify_payload("VERIFIED"), make_e911_validator_headers()
    )
    validate_error(response, ApiErrorId.ERR_REGISTRATION_NOT_VERIFIABLE.value, 409)

    unchanged = read_registration(registration["id"])
    assert unchanged["verification_status"] == "VERIFIED", (
        f"the refused second outcome leaves the row VERIFIED, got "
        f"{unchanged['verification_status']!r}"
    )
    assert_instant(unchanged["verified_at"], "2026-08-01T00:00:00.000Z", "verified_at")

    holder = read_device(device["id"])
    assert holder["registration_status"] == "REGISTERED", (
        f"the device keeps the REGISTERED status its first verification gave it, got "
        f"{holder['registration_status']!r}"
    )


def test_completed_port_request_is_terminal_and_refuses_further_triggers(api):
    """Completion drives the request to `COMPLETED`, a terminal status, and increments its `version` by 1.

    The request carries no bridge, so the `SCHEDULED -> COMPLETED` path is
    available, and once it is COMPLETED neither a cancellation nor a
    resubmission is a declared trigger any more.

    Design: Corner/state_machines/completed_port_request_is_terminal_and_refuses_further_triggers
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1010", billing_name="KUDZU KK", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "KL11",
        name="Kudzu Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=60,
        foc_business_days=3,
    )
    port_request = get_success_data(
        api.create_port_request(
            make_port_request_payload(
                account["id"],
                carrier["id"],
                requested_numbers=["+14155551705", "+14155551706"],
                claimed_account_number="CSR-1010",
                claimed_pin="1010",
                claimed_billing_name="KUDZU KK",
                claimed_address_line1="10 KUDZU ST",
                claimed_zip="94577",
            ),
            make_porting_specialist_headers(PORTING_USER_ID),
        )
    )
    get_success_data(
        api.create_csr_snapshot(
            port_request["id"],
            make_csr_snapshot_payload(
                port_request["version"],
                account_number_on_file="CSR-1010",
                pin_on_file="1010",
                billing_name_on_file="KUDZU KK",
                address_line1_on_file="10 KUDZU ST",
                zip_on_file="94577",
            ),
            make_carrier_liaison_headers(LIAISON_USER_ID),
        )
    )
    slot = seed_cutover_slot(
        carrier["id"],
        window_start="2026-08-10T14:00:00.000Z",
        window_end="2026-08-10T18:00:00.000Z",
    )
    scheduled = book_slot(port_request["id"], slot["id"])
    assert scheduled["status"] == "SCHEDULED", "setup step failed: expected SCHEDULED"

    completion = api.complete_cutover(
        port_request["id"], make_porting_specialist_headers(PORTING_USER_ID)
    )
    completed = validate_success(completion, 200)
    assert completed["status"] == "COMPLETED", (
        f"a bridge-less SCHEDULED request completes, got {completed['status']!r}"
    )

    consumed_slot = read_cutover_slot(slot["id"])
    assert consumed_slot["status"] == "CONSUMED", (
        f"the booked slot moves BOOKED -> CONSUMED, got {consumed_slot['status']!r}"
    )
    assert consumed_slot["booked_port_request_id"] == port_request["id"], (
        "a consumed slot retains booked_port_request_id as the permanent completion "
        f"record, got {consumed_slot['booked_port_request_id']!r}"
    )

    owner = read_account(account["id"])
    assert owner["ported_number_count"] == 2, (
        "ported_number_count counts the E.164 strings of every COMPLETED request, "
        f"expected 2, got {owner['ported_number_count']!r}"
    )

    cancellation = api.cancel_port_request(
        port_request["id"],
        make_cancel_payload(reason_note="customer changed their mind"),
        make_porting_specialist_headers(PORTING_USER_ID),
    )
    validate_error(cancellation, ApiErrorId.ERR_PORT_REQUEST_STATE_INVALID.value, 409)

    resubmission = api.resubmit_port_request(
        port_request["id"],
        make_resubmit_payload(
            claimed_account_number="CSR-1010B",
            claimed_pin="9010",
            claimed_billing_name="KUDZU KK",
            claimed_address_line1="10 KUDZU ST",
            claimed_zip="94577",
        ),
        make_porting_specialist_headers(PORTING_USER_ID),
    )
    validate_error(resubmission, ApiErrorId.ERR_PORT_REQUEST_STATE_INVALID.value, 409)

    still_completed = read_port_request(port_request["id"])
    assert still_completed["status"] == "COMPLETED", (
        f"the two refused triggers leave the terminal status alone, got "
        f"{still_completed['status']!r}"
    )
    assert still_completed["resubmission_count"] == 0, (
        f"the refused resubmission spends no budget, got "
        f"{still_completed['resubmission_count']!r}"
    )


def test_bridge_activation_before_the_cutover_window_opens_is_rejected(api):
    """The logical clock must lie inside that slot's half-open window — at or after `window_start` and strictly before `window_end` — and a clock outside it is refused with `ERR_BRIDGE_ACTIVATION_OUTSIDE_WINDOW`.

    The clock sits one second before the booked window opens, so the bridge is
    left exactly as provisioning made it.

    Design: Corner/state_machines/bridge_activation_before_the_cutover_window_opens_is_rejected
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1011", billing_name="LOTUS SPA", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "LL12",
        name="Lotus Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=60,
        foc_business_days=3,
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415605", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "1901")
    port_request = get_success_data(
        api.create_port_request(
            make_port_request_payload(
                account["id"],
                carrier["id"],
                requested_numbers=["+14155551707"],
                claimed_account_number="CSR-1011",
                claimed_pin="1011",
                claimed_billing_name="LOTUS SPA",
                claimed_address_line1="11 LOTUS WAY",
                claimed_zip="94577",
            ),
            make_porting_specialist_headers(PORTING_USER_ID),
        )
    )
    get_success_data(
        api.create_csr_snapshot(
            port_request["id"],
            make_csr_snapshot_payload(
                port_request["version"],
                account_number_on_file="CSR-1011",
                pin_on_file="1011",
                billing_name_on_file="LOTUS SPA",
                address_line1_on_file="11 LOTUS WAY",
                zip_on_file="94577",
            ),
            make_carrier_liaison_headers(LIAISON_USER_ID),
        )
    )
    slot = seed_cutover_slot(
        carrier["id"],
        window_start="2026-08-10T14:00:00.000Z",
        window_end="2026-08-10T18:00:00.000Z",
    )
    book_slot(port_request["id"], slot["id"])
    reservation = seed_reservation(
        block["id"],
        account["id"],
        purpose="PORT_BRIDGE",
        reserved_from="2026-08-10T00:00:00.000Z",
        reserved_until="2026-08-11T00:00:00.000Z",
        number_id=number["id"],
    )
    bridge = provision_bridge(port_request["id"], reservation["id"])
    assert bridge["status"] == "PROVISIONED", "setup step failed: expected PROVISIONED"

    set_clock("2026-08-10T13:59:59.000Z")
    response = api.activate_temporary_bridge(
        bridge["id"], make_porting_specialist_headers(PORTING_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_BRIDGE_ACTIVATION_OUTSIDE_WINDOW.value, 409)

    unchanged = get_success_data(
        api.get_temporary_bridge(bridge["id"], make_porting_specialist_headers())
    )
    assert unchanged["status"] == "PROVISIONED", (
        f"a refused activation leaves the bridge PROVISIONED, got {unchanged['status']!r}"
    )
    assert_null(unchanged["activated_at"], "activated_at")
    assert unchanged["bridge_number_id"] == number["id"], (
        "the bridge keeps the reservation's number, got "
        f"{unchanged['bridge_number_id']!r}"
    )

    assert read_port_request(port_request["id"])["status"] == "SCHEDULED", (
        "the port request stays SCHEDULED because the bridge never activated"
    )
    assert read_reservation(reservation["id"])["status"] == "CONSUMED", (
        "provisioning consumed the PORT_BRIDGE reservation and the refusal did not undo it"
    )
    assert read_phone_number(number["id"])["status"] == "RESERVED", (
        "the bridged number stays RESERVED for the whole life of the bridge"
    )


def test_reclamation_run_expires_only_reservations_whose_window_has_passed(api):
    """Second, every `HELD` reservation of the block whose `reserved_until` is strictly before the logical clock transitions `HELD → EXPIRED`, and its `RESERVED` number returns to `AVAILABLE` provided no other `HELD` reservation of that same number remains, in which case the number stays `RESERVED`.

    Design: Corner/state_machines/reclamation_run_expires_only_reservations_whose_window_has_passed
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1012", billing_name="MYRTLE OY", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415606", total_capacity=10, max_concurrent_reservations=3
    )
    first_number = seed_phone_number(block["id"], "2001")
    second_number = seed_phone_number(block["id"], "2002")
    lapsed = seed_reservation(
        block["id"],
        account["id"],
        purpose="NEW_LINE",
        reserved_from="2026-08-02T00:00:00.000Z",
        reserved_until="2026-08-05T00:00:00.000Z",
        number_id=first_number["id"],
    )
    live = seed_reservation(
        block["id"],
        account["id"],
        purpose="NEW_LINE",
        reserved_from="2026-08-02T00:00:00.000Z",
        reserved_until="2026-08-20T00:00:00.000Z",
        number_id=second_number["id"],
    )

    set_clock("2026-08-06T00:00:00.000Z")
    response = api.create_reclamation_run(block["id"], make_numbering_admin_headers())
    validate_success(response, 200)

    expired = read_reservation(lapsed["id"])
    assert expired["status"] == "EXPIRED", (
        "a hold whose reserved_until is strictly past expires, got "
        f"{expired['status']!r}"
    )
    # An expiry is not a release, and the PRD populates released_reason only on a
    # released reservation.
    assert_null(expired["released_reason"], "released_reason")

    untouched = read_reservation(live["id"])
    assert untouched["status"] == "HELD", (
        f"a hold running to 2026-08-20 is still live and stays HELD, got "
        f"{untouched['status']!r}"
    )

    assert read_phone_number(first_number["id"])["status"] == "AVAILABLE", (
        "the expired hold's number returns to AVAILABLE"
    )
    assert read_phone_number(second_number["id"])["status"] == "RESERVED", (
        "the still-held number stays RESERVED"
    )

    assert_block_census(
        read_number_block(block["id"]),
        minted=2,
        available=1,
        reserved=1,
        assigned=0,
        parked=0,
    )


def test_releasing_an_assigned_number_parks_it_for_168_hours_then_reclaims(api):
    """It sets `parked_until` to the logical clock plus the cooling-off period of 168 hours — seven days — increments `park_cycle_count` by 1, and clears `assigned_account_id` to null.

    A reclamation run at exactly that `parked_until` instant then returns the
    number to AVAILABLE while retaining its reuse history.

    Design: Corner/state_machines/releasing_an_assigned_number_parks_it_for_168_hours_then_reclaims
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account(
        "ACCT1013", billing_name="NUTMEG SA", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415607", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "2101")
    device = seed_device(
        account["id"],
        "AABBCC002101",
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )

    release = api.release_phone_number(number["id"], make_numbering_admin_headers())
    validate_success(release, 200)

    parked = read_phone_number(number["id"])
    assert parked["status"] == "PARKED", (
        f"releasing an ASSIGNED number drives it to PARKED, got {parked['status']!r}"
    )
    assert_instant(parked["parked_until"], "2026-08-10T09:00:00.000Z", "parked_until")
    assert parked["park_cycle_count"] == 1, (
        f"park_cycle_count increments by 1, got {parked['park_cycle_count']!r}"
    )
    assert_null(parked["assigned_account_id"], "assigned_account_id")

    stripped = read_device(device["id"])
    assert_null(stripped["assigned_number_id"], "device.assigned_number_id")

    assert_block_census(read_number_block(block["id"]), minted=1, assigned=0, parked=1)

    settled = read_account(account["id"])
    assert settled["e911_compliance_posture"] == "COMPLIANT", (
        "the released device leaves the posture population, so the account returns to "
        f"COMPLIANT, got {settled['e911_compliance_posture']!r}"
    )

    set_clock("2026-08-10T09:00:00.000Z")
    reclamation = api.create_reclamation_run(block["id"], make_numbering_admin_headers())
    validate_success(reclamation, 200)

    reclaimed = read_phone_number(number["id"])
    assert reclaimed["status"] == "AVAILABLE", (
        "a PARKED number whose parked_until is at the clock is reclaimed, got "
        f"{reclaimed['status']!r}"
    )
    assert_null(reclaimed["parked_until"], "parked_until")
    assert reclaimed["park_cycle_count"] == 1, (
        "reclamation retains park_cycle_count as the number's reuse history, got "
        f"{reclaimed['park_cycle_count']!r}"
    )

    assert_block_census(read_number_block(block["id"]), minted=1, available=1, parked=0)


def test_account_posture_bubbles_to_blocked_when_the_prompt_deadline_passes(api):
    """From those classifications the posture follows: `BLOCKED` if any device in the population is hard-failed or overdue; otherwise `AT_RISK` if any device is stale or in grace; otherwise `COMPLIANT`, including the vacuous case where the population is empty.

    The number-holding device has no dispatchable location at all, so it is
    merely in grace until its 72-hour prompt deadline and overdue afterwards,
    and the BLOCKED sweep then reaches every device of the account.

    Design: Corner/state_machines/account_posture_bubbles_to_blocked_when_the_prompt_deadline_passes
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1014", billing_name="OLIVE LTD", service_state_code="CA", status="ACTIVE"
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415608", total_capacity=10, max_concurrent_reservations=2
    )
    number = seed_phone_number(block["id"], "2201")
    holder = seed_device(
        account["id"],
        "AABBCC002201",
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )

    assert_instant(
        holder["registration_prompt_deadline"],
        "2026-08-04T00:00:00.000Z",
        "registration_prompt_deadline",
    )
    assert holder["registration_status"] == "PENDING_REGISTRATION", (
        f"a device with no captured location starts at PENDING_REGISTRATION, got "
        f"{holder['registration_status']!r}"
    )

    # Moving the clock recomputes nothing, so the posture is still the one the
    # in-grace classification produced when the device was registered.
    set_clock("2026-08-05T00:00:00.000Z")
    before = read_account(account["id"])
    assert before["e911_compliance_posture"] == "AT_RISK", (
        f"an in-grace device makes the account AT_RISK, got "
        f"{before['e911_compliance_posture']!r}"
    )
    assert read_device(holder["id"])["calling_status"] == "UNRESTRICTED", (
        "the AT_RISK sweep touches only nomadic devices, so this one stays UNRESTRICTED"
    )

    response = api.create_device(
        make_device_payload(
            account["id"], "AABBCC002202", device_type="SOFTPHONE", nomadic=False
        ),
        make_account_admin_headers(account["id"]),
    )
    second = validate_success(response, 201)

    assert_null(second["assigned_number_id"], "assigned_number_id")
    assert_instant(
        second["registration_prompt_deadline"],
        "2026-08-08T00:00:00.000Z",
        "registration_prompt_deadline",
    )

    after = read_account(account["id"])
    assert after["e911_compliance_posture"] == "BLOCKED", (
        "the overdue number-holding device drives the account to BLOCKED, got "
        f"{after['e911_compliance_posture']!r}"
    )
    assert read_device(holder["id"])["calling_status"] == "FULL_BLOCKED", (
        "moving to BLOCKED sends every device of the account to FULL_BLOCKED"
    )
    assert read_device(second["id"])["calling_status"] == "FULL_BLOCKED", (
        "the sweep reaches the newly registered device too"
    )
