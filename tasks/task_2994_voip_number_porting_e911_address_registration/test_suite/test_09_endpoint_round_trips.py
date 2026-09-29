"""Endpoint round trips: a write is readable back through every documented route.

Each test drives one endpoint (or one short chain of them) and then re-reads the
affected entities through their own read and list routes, so a response that was
merely echoed rather than persisted, or a cascade that stopped one link short of
where the PRD puts it, fails here.
"""
from test_helpers import (
    CLOCK_DEFAULT_ISO,
    PORTING_USER_ID,
    REMITTANCE_SENTINEL,
    ApiErrorId,
    assess_fee,
    assert_block_census,
    assert_cents_equal,
    assert_common_fields,
    assert_instant,
    assert_null,
    assert_pagination_meta,
    assert_version,
    book_slot,
    expected_e164,
    get_success_data,
    ids_of,
    make_number_block_payload,
    make_phone_number_payload,
    make_port_request_payload,
    make_porting_specialist_headers,
    make_remittance_run_payload,
    make_temporary_bridge_payload,
    make_verify_payload,
    post_matching_csr_snapshot,
    read_account,
    read_cutover_slot,
    read_device,
    read_jurisdiction,
    read_number_block,
    read_phone_number,
    read_port_request,
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
    validate_paginated,
    validate_success,
    verify_registration,
)


def test_number_block_and_phone_number_crud_round_trip(api, numbering_admin_headers):
    """`minted_count` is the number of phone numbers belonging to the block, and `available_count`, `reserved_count`, `assigned_count` and `parked_count` are the numbers of those in `AVAILABLE`, `RESERVED`, `ASSIGNED` and `PARKED` status respectively.

    The same census is read back three ways - by block id, through the
    jurisdiction-filtered block list, and through the phone-number list filtered
    by block_id - so the write is genuinely persisted rather than echoed.

    Design: Corner/endpoints/number_block_and_phone_number_crud_round_trip
    """
    set_clock(CLOCK_DEFAULT_ISO)
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )

    created = validate_success(
        api.create_number_block(
            make_number_block_payload(
                jurisdiction["id"],
                npa_nxx="415618",
                total_capacity=4,
                max_concurrent_reservations=2,
            ),
            numbering_admin_headers,
        ),
        201,
    )
    assert_common_fields(created, "NumberBlock")
    assert created["jurisdiction_id"] == jurisdiction["id"]
    assert created["npa_nxx"] == "415618"
    assert created["total_capacity"] == 4
    assert created["max_concurrent_reservations"] == 2
    # A brand-new block has minted nothing, so every counter starts at 0.
    assert_block_census(created, minted=0, available=0, reserved=0, assigned=0, parked=0)
    assert_version(created, 1, "NumberBlock")

    minted = validate_success(
        api.mint_phone_number(
            created["id"], make_phone_number_payload(line_number="3401"), numbering_admin_headers
        ),
        201,
    )
    assert minted["block_id"] == created["id"]
    assert minted["line_number"] == "3401"
    assert minted["e164"] == expected_e164("415618", "3401")
    assert minted["status"] == "AVAILABLE"

    # Route 1: read the block by its own id.
    reread = validate_success(api.get_number_block(created["id"], numbering_admin_headers))
    assert reread["id"] == created["id"]
    assert reread["npa_nxx"] == "415618"
    assert_block_census(reread, minted=1, available=1, reserved=0, assigned=0, parked=0)

    # Route 2: the jurisdiction-filtered block list.
    block_rows, block_meta = validate_paginated(
        api.list_number_blocks(
            numbering_admin_headers,
            params={"jurisdiction_id": jurisdiction["id"], "limit": 10, "offset": 0},
        )
    )
    assert_pagination_meta(block_meta, limit=10, offset=0, total_count=1, has_more=False)
    assert ids_of(block_rows) == [created["id"]]
    assert_block_census(block_rows[0], minted=1, available=1, reserved=0, assigned=0, parked=0)

    # Route 3: the phone-number list filtered by block_id.
    number_rows, number_meta = validate_paginated(
        api.list_phone_numbers(
            numbering_admin_headers,
            params={"block_id": created["id"], "limit": 10, "offset": 0},
        )
    )
    assert_pagination_meta(number_meta, limit=10, offset=0, total_count=1, has_more=False)
    assert ids_of(number_rows) == [minted["id"]]
    assert number_rows[0]["e164"] == "+14156183401"
    assert number_rows[0]["status"] == "AVAILABLE"


def test_rejecting_a_dispatchable_location_suspends_the_device_and_blocks_the_account(
    api, e911_validator_headers
):
    """An outcome of `REJECTED` moves the registration to `REJECTED`, stores the supplied `rejection_note` — null if none was given — and drives the device `ADDRESS_UNVERIFIED → SUSPENDED_911`, after which the device may place no calls at all, domestic or international.

    One action endpoint fires four documented effects: the registration status
    and note, the device's registration_status, both versions, and the account
    posture that the hard-failed registration drives to BLOCKED.

    Design: Corner/endpoints/rejecting_a_dispatchable_location_suspends_the_device_and_blocks_the_account
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account("ACCT1031", billing_name="FENNEL SRL", service_state_code="CA",
                           status="ACTIVE")
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(jurisdiction["id"], npa_nxx="415619", total_capacity=10,
                              max_concurrent_reservations=2)
    number = seed_phone_number(block["id"], "3501")
    device = seed_device(
        account["id"],
        "AABBCC003501",
        device_type="HANDSET",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="31 FENNEL PATH",
        unit="",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
    )
    assert registration["verification_status"] == "UNVERIFIED"
    registration_version_before = registration["version"]

    rejected = validate_success(
        api.verify_e911_registration(
            registration["id"],
            make_verify_payload("REJECTED", rejection_note="no such civic address"),
            e911_validator_headers,
        )
    )
    assert rejected["verification_status"] == "REJECTED"
    assert rejected["rejection_note"] == "no such civic address"
    assert_null(rejected["verified_at"], "E911Registration.verified_at")
    assert_version(rejected, registration_version_before + 1, "E911Registration")

    device_after = read_device(device["id"])
    assert device_after["registration_status"] == "SUSPENDED_911"
    # The posture recomputation moves the account AT_RISK -> BLOCKED, and the PRD
    # makes that transition sweep every device of the account to FULL_BLOCKED.
    assert device_after["calling_status"] == "FULL_BLOCKED"

    account_after = read_account(account["id"])
    assert account_after["e911_compliance_posture"] == "BLOCKED"

    # A REJECTED row never re-enters verification.
    validate_error(
        api.verify_e911_registration(
            registration["id"], make_verify_payload("VERIFIED"), e911_validator_headers
        ),
        ApiErrorId.ERR_REGISTRATION_NOT_VERIFIABLE.value,
        409,
    )


def test_one_remittance_run_closes_every_account_in_the_jurisdiction(api, billing_admin_headers):
    """Second, the run walks every account in ascending `created_at` order, computes the `FINAL` branch for that account in that jurisdiction and period, and for each account that selects at least one billable unit creates a `FeeAssessment` with `variant` `FINAL`, `unit_basis` copied from the jurisdiction, the computed `billable_units`, `unit_fee_breakdown` and `amount_cents`, `assessed_by_user_id` set to `system:remittance-run`, and `status` `ASSESSED` — then immediately drives that same row `ASSESSED → REMITTED` with `remitted_at` set to the logical clock, moving its money out of `pending_fee_cents` and into `remitted_fee_cents`.

    One run sweeps both accounts of the jurisdiction, so it is per-jurisdiction
    rather than per-account.

    Design: Corner/endpoints/one_remittance_run_closes_every_account_in_the_jurisdiction
    """
    set_clock(CLOCK_DEFAULT_ISO)
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(jurisdiction["id"], npa_nxx="415620", total_capacity=10,
                              max_concurrent_reservations=2)

    account_a = seed_account("ACCT1032", billing_name="GORSE LLC", service_state_code="CA",
                             status="ACTIVE")
    number_a = seed_phone_number(block["id"], "3601")
    device_a = seed_device(
        account_a["id"], "AABBCC003601", device_type="HANDSET", nomadic=False,
        assigned_number_id=number_a["id"],
    )
    registration_a = seed_registration(
        device_a["id"], jurisdiction["id"], account_a["id"],
        address_line1="32 GORSE GATE", unit="", city="OAKLAND", state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration_a["id"], "VERIFIED")

    account_b = seed_account("ACCT1033", billing_name="HAZEL LLC", service_state_code="CA",
                             status="ACTIVE")
    number_b = seed_phone_number(block["id"], "3602")
    device_b = seed_device(
        account_b["id"], "AABBCC003602", device_type="HANDSET", nomadic=False,
        assigned_number_id=number_b["id"],
    )
    registration_b = seed_registration(
        device_b["id"], jurisdiction["id"], account_b["id"],
        address_line1="33 HAZEL HILL", unit="", city="OAKLAND", state_code="CA",
        postal_code="94601",
    )
    verify_registration(registration_b["id"], "VERIFIED")

    provisional_a = assess_fee(account_a["id"], jurisdiction["id"], "2026-08")
    provisional_b = assess_fee(account_b["id"], jurisdiction["id"], "2026-08")
    assert_cents_equal(provisional_a["amount_cents"], 175, "FeeAssessment.amount_cents")
    assert_cents_equal(provisional_b["amount_cents"], 175, "FeeAssessment.amount_cents")

    set_clock("2026-09-05T00:00:00.000Z")

    before = read_jurisdiction(jurisdiction["id"])
    assert_cents_equal(before["pending_fee_cents"], 350, "Jurisdiction.pending_fee_cents")
    assert_cents_equal(before["remitted_fee_cents"], 0, "Jurisdiction.remitted_fee_cents")

    returned = validate_success(
        api.create_remittance_run(
            jurisdiction["id"], make_remittance_run_payload("2026-08"), billing_admin_headers
        )
    )
    # The run returns the jurisdiction it closed.
    assert returned["id"] == jurisdiction["id"]

    voided_a = validate_success(
        api.get_fee_assessment(provisional_a["id"], billing_admin_headers))
    voided_b = validate_success(
        api.get_fee_assessment(provisional_b["id"], billing_admin_headers))
    assert voided_a["status"] == "VOIDED"
    assert voided_b["status"] == "VOIDED"
    assert voided_a["voided_by_user_id"] == REMITTANCE_SENTINEL
    assert voided_b["voided_by_user_id"] == REMITTANCE_SENTINEL

    final_rows, final_meta = validate_paginated(
        api.list_fee_assessments(
            billing_admin_headers,
            params={"jurisdiction_id": jurisdiction["id"], "variant": "FINAL"},
        )
    )
    assert final_meta["total_count"] == 2
    assert len(final_rows) == 2
    for row in final_rows:
        assert row["variant"] == "FINAL"
        assert row["status"] == "REMITTED"
        assert row["unit_basis"] == "PER_LINE"
        assert row["billable_units"] == 1
        assert row["unit_fee_breakdown"] == [175]
        assert_cents_equal(row["amount_cents"], 175, "FeeAssessment.amount_cents")
        assert row["assessed_by_user_id"] == REMITTANCE_SENTINEL
        assert_instant(row["remitted_at"], "2026-09-05T00:00:00.000Z", "remitted_at")
    assert {row["account_id"] for row in final_rows} == {account_a["id"], account_b["id"]}

    after = read_jurisdiction(jurisdiction["id"])
    assert_cents_equal(after["pending_fee_cents"], 0, "Jurisdiction.pending_fee_cents")
    assert_cents_equal(after["remitted_fee_cents"], 350, "Jurisdiction.remitted_fee_cents")
    assert after["last_remitted_period"] == "2026-08"

    assert_cents_equal(
        read_account(account_a["id"])["fee_liability_cents"], 175, "Account.fee_liability_cents")
    assert_cents_equal(
        read_account(account_b["id"])["fee_liability_cents"], 175, "Account.fee_liability_cents")


def test_bridge_creation_links_a_scheduled_port_to_its_reservation(api, porting_specialist_headers):
    """On success the bridge copies the reservation's `number_id` into its own `bridge_number_id`, the reservation transitions `HELD → CONSUMED`, and the bridge is created `PROVISIONED` with `activated_at` and `released_at` both null.

    The port request itself stays SCHEDULED: only activation carries it to
    BRIDGED, so provisioning alone must not move it.

    Design: Corner/endpoints/bridge_creation_links_a_scheduled_port_to_its_reservation
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account("ACCT1034", billing_name="IVY GMBH", service_state_code="CA",
                           status="ACTIVE")
    carrier = seed_carrier(
        "IL18", name="Ivy Legacy", csr_match_policy="STRICT", porting_buffer_minutes=30,
        foc_business_days=2,
    )
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(jurisdiction["id"], npa_nxx="415621", total_capacity=10,
                              max_concurrent_reservations=2)
    number = seed_phone_number(block["id"], "3701")
    reservation = seed_reservation(
        block["id"],
        account["id"],
        purpose="PORT_BRIDGE",
        reserved_from="2026-08-04T00:00:00.000Z",
        reserved_until="2026-08-20T00:00:00.000Z",
    )
    assert reservation["status"] == "HELD"
    assert reservation["number_id"] == number["id"]

    claimed = make_port_request_payload(
        account["id"],
        carrier["id"],
        requested_numbers=["+14155551805"],
        claimed_account_number="CSR-1034",
        claimed_pin="1034",
        claimed_billing_name="IVY GMBH",
        claimed_address_line1="34 IVY LANE",
        claimed_zip="94577",
    )
    port_request = get_success_data(
        api.create_port_request(claimed, make_porting_specialist_headers(PORTING_USER_ID))
    )
    post_matching_csr_snapshot(port_request["id"], claimed)
    port_request = read_port_request(port_request["id"])
    assert port_request["status"] == "VALIDATED"
    # Validated on Monday 2026-08-03 with foc_business_days 2: Tue then Wed.
    assert_instant(port_request["earliest_cutover_at"], "2026-08-05T00:00:00.000Z",
                   "earliest_cutover_at")
    slot = seed_cutover_slot(
        carrier["id"],
        window_start="2026-08-06T14:00:00.000Z",
        window_end="2026-08-06T18:00:00.000Z",
    )
    port_request = book_slot(port_request["id"], slot["id"])
    assert port_request["status"] == "SCHEDULED"

    bridge = validate_success(
        api.create_temporary_bridge(
            make_temporary_bridge_payload(port_request["id"], reservation["id"]),
            porting_specialist_headers,
        ),
        201,
    )
    assert bridge["status"] == "PROVISIONED"
    assert_null(bridge["activated_at"], "TemporaryBridge.activated_at")
    assert_null(bridge["released_at"], "TemporaryBridge.released_at")
    assert bridge["bridge_number_id"] == number["id"]
    assert bridge["port_request_id"] == port_request["id"]
    assert bridge["reservation_id"] == reservation["id"]

    assert read_reservation(reservation["id"])["status"] == "CONSUMED"
    # The consumed PORT_BRIDGE reservation keeps governing its number.
    assert read_phone_number(number["id"])["status"] == "RESERVED"

    assert read_port_request(port_request["id"])["status"] == "SCHEDULED"

    slot_after = read_cutover_slot(slot["id"])
    assert slot_after["status"] == "BOOKED"
    assert slot_after["booked_port_request_id"] == port_request["id"]

    bridge_rows, bridge_meta = validate_paginated(
        api.list_temporary_bridges(
            porting_specialist_headers, params={"port_request_id": port_request["id"]}
        )
    )
    assert bridge_meta["total_count"] == 1
    assert ids_of(bridge_rows) == [bridge["id"]]


def test_block_census_read_counts_parked_numbers_apart_from_available(api, numbering_admin_headers):
    """The block's counters move one unit from `assigned_count` to `parked_count` and the block's `version` increments by 1.

    A parked number is therefore excluded from the available pool it will only
    rejoin after a reclamation run.

    Design: Corner/endpoints/block_census_read_counts_parked_numbers_apart_from_available
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account("ACCT1035", billing_name="JUNIPER AG", service_state_code="CA",
                           status="ACTIVE")
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(jurisdiction["id"], npa_nxx="415622", total_capacity=10,
                              max_concurrent_reservations=2)
    number_one = seed_phone_number(block["id"], "3801")
    seed_phone_number(block["id"], "3802")
    device = seed_device(
        account["id"], "AABBCC003801", device_type="HANDSET", nomadic=False,
        assigned_number_id=number_one["id"],
    )

    before = read_number_block(block["id"])
    assert_block_census(before, minted=2, available=1, reserved=0, assigned=1, parked=0)
    version_before = before["version"]

    released = validate_success(
        api.release_phone_number(number_one["id"], numbering_admin_headers)
    )
    assert released["status"] == "PARKED"
    assert_null(released["assigned_account_id"], "PhoneNumber.assigned_account_id")
    # The cooling-off period is the logical clock plus 168 hours.
    assert_instant(released["parked_until"], "2026-08-08T00:00:00.000Z", "parked_until")
    assert released["park_cycle_count"] == 1

    after = read_number_block(block["id"])
    assert_block_census(after, minted=2, available=1, reserved=0, assigned=0, parked=1)
    assert_version(after, version_before + 1, "NumberBlock")

    device_after = read_device(device["id"])
    assert_null(device_after["assigned_number_id"], "Device.assigned_number_id")
    # The device left the posture population, so the account returns to compliance.
    assert read_account(account["id"])["e911_compliance_posture"] == "COMPLIANT"


def test_releasing_a_number_that_was_never_assigned_is_rejected(api, numbering_admin_headers):
    """Releasing a number that is not `ASSIGNED` is refused with `ERR_PHONE_NUMBER_STATE_INVALID`.

    The very same call against a number a device holds succeeds, so the refusal
    is conditional on the number's inventory status rather than on the endpoint.

    Design: Corner/endpoints/releasing_a_number_that_was_never_assigned_is_rejected
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account("ACCT1036", billing_name="KELP OY", service_state_code="CA",
                           status="ACTIVE")
    jurisdiction = seed_jurisdiction(
        "CA", "06001", fee_type="PER_LINE", monthly_fee_cents=175, remit_day_of_month=5
    )
    block = seed_number_block(jurisdiction["id"], npa_nxx="415623", total_capacity=10,
                              max_concurrent_reservations=2)
    untouched = seed_phone_number(block["id"], "3901")
    held = seed_phone_number(block["id"], "3902")
    seed_device(
        account["id"], "AABBCC003902", device_type="HANDSET", nomadic=False,
        assigned_number_id=held["id"],
    )

    validate_error(
        api.release_phone_number(untouched["id"], numbering_admin_headers),
        ApiErrorId.ERR_PHONE_NUMBER_STATE_INVALID.value,
        409,
    )
    still_available = read_phone_number(untouched["id"])
    assert still_available["status"] == "AVAILABLE"
    assert_null(still_available["parked_until"], "PhoneNumber.parked_until")
    assert still_available["park_cycle_count"] == 0

    parked = validate_success(api.release_phone_number(held["id"], numbering_admin_headers))
    assert parked["status"] == "PARKED"

    assert_block_census(
        read_number_block(block["id"]), minted=2, available=1, reserved=0, assigned=0, parked=1
    )
