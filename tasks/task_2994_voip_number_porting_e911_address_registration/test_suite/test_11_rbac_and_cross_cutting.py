"""Role-based access control, the two optimistic-concurrency tokens, the fraud
threshold walk, and the immediate visibility of derived state.

Every test builds its own preconditions against a fresh, empty database and a
logical clock that starts at 2026-08-01T00:00:00Z.
"""
from test_helpers import (
    ApiErrorId,
    BILLING_USER_ID,
    BILLING_USER_ID_ALT,
    LIAISON_USER_ID,
    PORTING_USER_ID,
    assert_block_census,
    assert_cents_equal,
    assert_instant,
    assert_null,
    count_by,
    find_by,
    make_account_admin_headers,
    make_billing_admin_headers,
    make_call_attempt_payload,
    make_calling_restriction_payload,
    make_carrier_liaison_headers,
    make_csr_snapshot_payload,
    make_cutover_slot_payload,
    make_e911_registration_payload,
    make_e911_validator_headers,
    make_fee_assessment_payload,
    make_number_block_payload,
    make_number_reservation_payload,
    make_numbering_admin_headers,
    make_port_request_payload,
    make_porting_specialist_headers,
    make_reject_payload,
    make_remittance_run_payload,
    make_security_analyst_headers,
    make_verify_payload,
    make_void_payload,
    post_csr_snapshot,
    prorated_unit_fee_cents,
    read_account,
    read_device,
    read_jurisdiction,
    read_number_block,
    read_port_request,
    read_registration,
    resubmit_port_request,
    seed_account,
    seed_carrier,
    seed_device,
    seed_jurisdiction,
    seed_number_block,
    seed_phone_number,
    seed_port_request,
    seed_registration,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_registration,
)

# Well-shaped but unpersisted ids: the role refusal must win before any lookup.
FABRICATED_CARRIER_ID = "00000000-0000-4000-8000-0000000000aa"
FABRICATED_ACCOUNT_ID = "00000000-0000-4000-8000-0000000000bb"
FABRICATED_PORT_REQUEST_ID = "00000000-0000-4000-8000-0000000000cc"


def test_exclusive_operations_are_refused_to_every_other_role_returns_403(api):
    """If both headers are well formed but the named role does not appear in the authorized-role list of the endpoint being addressed (§4), the request is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

    Each attempt names a well-shaped id that was never persisted, so a refusal
    that leaked a not-found error would prove the lookup ran first.

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role_returns_403
    """
    set_clock("2026-08-01T00:00:00.000Z")
    jurisdiction = seed_jurisdiction("CA", "06001")

    # Inventory creation belongs to NumberingAdmin alone.
    resp = api.create_number_block(
        make_number_block_payload(
            jurisdiction["id"], npa_nxx="415629",
            total_capacity=4, max_concurrent_reservations=2,
        ),
        make_porting_specialist_headers(PORTING_USER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # Opening a cutover window belongs to PortingSpecialist alone.
    resp = api.create_cutover_slot(
        make_cutover_slot_payload(
            FABRICATED_CARRIER_ID,
            window_start="2026-08-06T14:00:00.000Z",
            window_end="2026-08-06T18:00:00.000Z",
        ),
        make_numbering_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # Assessing a fee belongs to BillingAdmin alone.
    resp = api.create_fee_assessment(
        make_fee_assessment_payload(
            FABRICATED_ACCOUNT_ID, jurisdiction["id"], "2026-07"
        ),
        make_e911_validator_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # Recording a carrier rejection belongs to CarrierLiaison alone.
    resp = api.reject_port_request(
        FABRICATED_PORT_REQUEST_ID,
        make_reject_payload("PIN_INVALID"),
        make_security_analyst_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # Closing a period belongs to BillingAdmin alone.
    resp = api.create_remittance_run(
        jurisdiction["id"],
        make_remittance_run_payload("2026-07"),
        make_numbering_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # Nothing was written by any of the five refusals.
    rows, meta = validate_paginated(
        api.list_number_blocks(
            make_numbering_admin_headers(),
            params={"jurisdiction_id": jurisdiction["id"]},
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused block creation persisted a row: {rows}"
    )


def test_e911_validator_cannot_capture_the_location_it_verifies(api):
    """It cannot capture a location itself.

    The validator is refused the capture route yet is the only role the verify
    route accepts for the very same registration.

    Design: Corner/rbac/e911_validator_cannot_capture_the_location_it_verifies
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account("ACCT1044", billing_name="TEASEL NV", service_state_code="CA")
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(jurisdiction["id"], npa_nxx="415630", total_capacity=10)
    number = seed_phone_number(block["id"], "4401")
    device = seed_device(
        account["id"],
        "AABBCC004401",
        device_type="HANDSET",
        nomadic=False,
        assigned_number_id=number["id"],
    )

    capture_payload = make_e911_registration_payload(
        device["id"],
        jurisdiction["id"],
        address_line1="44 TEASEL TERRACE",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
        unit="",
    )

    resp = api.create_e911_registration(capture_payload, make_e911_validator_headers())
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert read_device(device["id"])["registration_status"] == "PENDING_REGISTRATION"

    resp = api.create_e911_registration(
        capture_payload, make_account_admin_headers(account["id"])
    )
    registration = validate_success(resp, 201)
    assert read_device(device["id"])["registration_status"] == "ADDRESS_UNVERIFIED"

    resp = api.verify_e911_registration(
        registration["id"], make_verify_payload("VERIFIED"), make_e911_validator_headers()
    )
    verified = validate_success(resp, 200)
    assert verified["verification_status"] == "VERIFIED"
    assert read_device(device["id"])["registration_status"] == "REGISTERED"

    # The owning account's own administrator is still refused the verify route.
    resp = api.verify_e911_registration(
        registration["id"],
        make_verify_payload("VERIFIED"),
        make_account_admin_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)


def test_only_the_security_analyst_may_apply_a_calling_restriction_returns_403(api):
    """Only a `SecurityAnalyst` applies or lifts a restriction on a device.

    The account's own administrator may place calls from the device but may not
    restrict it, while the identical body from the analyst is accepted.

    Design: Corner/rbac/only_the_security_analyst_may_apply_a_calling_restriction_returns_403
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account("ACCT1045", billing_name="VETCH SA", service_state_code="CA")
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(jurisdiction["id"], npa_nxx="415631", total_capacity=10)
    number = seed_phone_number(block["id"], "4501")
    device = seed_device(
        account["id"],
        "AABBCC004501",
        device_type="HANDSET",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="45 VETCH VALE",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
        unit="",
    )
    verify_registration(registration["id"], "VERIFIED")

    resp = api.create_calling_restriction(
        device["id"],
        make_calling_restriction_payload("BLOCK_INTL", note="subscriber request"),
        make_account_admin_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert read_device(device["id"])["calling_status"] == "UNRESTRICTED"

    resp = api.create_calling_restriction(
        device["id"],
        make_calling_restriction_payload("BLOCK_INTL", note="analyst hold"),
        make_security_analyst_headers(),
    )
    restricted = validate_success(resp, 200)
    assert restricted["calling_status"] == "INTL_BLOCKED"

    # The fraud dimension and the E911 dimension are untouched by a restriction.
    assert restricted["registration_status"] == "REGISTERED"
    assert restricted["fraud_block_count"] == 0

    # Reading the device is a shared operation the analyst holds.
    validate_success(api.get_device(device["id"], make_security_analyst_headers()), 200)


def test_the_assessing_billing_admin_cannot_void_its_own_assessment(api):
    """The voiding administrator's `X-User-ID` must differ from the row's `assessed_by_user_id`, or the void is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403) — the same principal may not both charge a subscriber and erase the charge.

    Both principals hold the `BillingAdmin` role, so only `X-User-ID` separates
    them.

    Design: Corner/rbac/the_assessing_billing_admin_cannot_void_its_own_assessment
    """
    set_clock("2026-08-15T00:00:00.000Z")
    account = seed_account("ACCT1046", billing_name="WOAD KFT", service_state_code="CA")
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(jurisdiction["id"], npa_nxx="415632", total_capacity=10)
    number = seed_phone_number(block["id"], "4601")
    device = seed_device(
        account["id"],
        "AABBCC004601",
        device_type="HANDSET",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="46 WOAD WALK",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
        unit="",
    )
    verify_registration(registration["id"], "VERIFIED")

    assessment = validate_success(
        api.create_fee_assessment(
            make_fee_assessment_payload(account["id"], jurisdiction["id"], "2026-08"),
            make_billing_admin_headers(BILLING_USER_ID),
        ),
        201,
    )
    assessed_version = assessment["version"]
    # One PER_LINE unit anchored on the 15th of a 31-day month: 17 active days.
    expected_amount = prorated_unit_fee_cents(175, 17, 31)
    assert_cents_equal(assessment["amount_cents"], expected_amount)

    resp = api.void_fee_assessment(
        assessment["id"],
        make_void_payload(void_note="self void"),
        make_billing_admin_headers(BILLING_USER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403)

    still_standing = validate_success(
        api.get_fee_assessment(assessment["id"], make_billing_admin_headers(BILLING_USER_ID)),
        200,
    )
    assert still_standing["status"] == "ASSESSED"
    assert still_standing["version"] == assessed_version
    assert still_standing["assessed_by_user_id"] == BILLING_USER_ID

    voided = validate_success(
        api.void_fee_assessment(
            assessment["id"],
            make_void_payload(void_note="peer void"),
            make_billing_admin_headers(BILLING_USER_ID_ALT),
        ),
        200,
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_by_user_id"] == BILLING_USER_ID_ALT
    assert voided["version"] == assessed_version + 1

    assert_cents_equal(
        read_jurisdiction(jurisdiction["id"])["pending_fee_cents"], 0, "pending_fee_cents"
    )
    assert_cents_equal(
        read_account(account["id"])["fee_liability_cents"], 0, "fee_liability_cents"
    )


def test_account_admin_runs_its_own_shared_operations_end_to_end(api):
    """When `X-User-Role` is `AccountAdmin`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's account-bearing field to `X-User-ID`.

    Every shared operation of the role succeeds when the acting id is the owning
    account, so the ownership rule scopes the role rather than forbidding it.

    Design: Corner/rbac/account_admin_runs_its_own_shared_operations_end_to_end
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account("ACCT1047", billing_name="YEW LLC", service_state_code="CA")
    carrier = seed_carrier(
        "YL23",
        name="Yew Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(jurisdiction["id"], npa_nxx="415633", total_capacity=10)
    number = seed_phone_number(block["id"], "4701")

    owner = make_account_admin_headers(account["id"])

    device = validate_success(
        api.create_device(
            {
                "account_id": account["id"],
                "mac_address": "AABBCC004701",
                "device_type": "SOFTPHONE",
                "nomadic": True,
                "assigned_number_id": number["id"],
            },
            owner,
        ),
        201,
    )
    assert device["registration_status"] == "PENDING_REGISTRATION"

    registration = validate_success(
        api.create_e911_registration(
            make_e911_registration_payload(
                device["id"],
                jurisdiction["id"],
                address_line1="47 YEW YARD",
                city="OAKLAND",
                state_code="CA",
                postal_code="94601",
                unit="2",
            ),
            owner,
        ),
        201,
    )
    assert read_device(device["id"])["registration_status"] == "ADDRESS_UNVERIFIED"

    reported = validate_success(
        api.create_network_report(
            device["id"],
            {"reported_state_code": "CA", "reported_postal_code": "94601"},
            owner,
        ),
        200,
    )
    assert_instant(
        reported["last_network_report_at"],
        "2026-08-03T09:00:00.000Z",
        "last_network_report_at",
    )
    assert reported["reported_postal_code"] == "94601"

    # A report of the same location does not verify the address.
    assert read_registration(registration["id"])["verification_status"] == "UNVERIFIED"

    port_request = validate_success(
        api.create_port_request(
            make_port_request_payload(
                account["id"],
                carrier["id"],
                requested_numbers=["+14155551811"],
                claimed_account_number="CSR-1047",
                claimed_pin="1047",
                claimed_billing_name="YEW LLC",
                claimed_address_line1="47 YEW YARD",
                claimed_zip="94577",
            ),
            owner,
        ),
        201,
    )
    assert port_request["status"] == "SUBMITTED"
    assert port_request["created_by_user_id"] == account["id"]

    validate_success(api.get_account(account["id"], owner), 200)
    validate_success(api.get_port_request(port_request["id"], owner), 200)


def test_stale_number_block_version_is_refused_and_the_refreshed_one_succeeds(api):
    """If it does not equal that block's current `version`, the write is refused with `ERR_STALE_NUMBER_BLOCK_VERSION` (HTTP 412).

    The second reservation is otherwise perfectly legal, so only the token the
    caller carried distinguishes it from the third.

    Design: Corner/cross_cutting_complexity_layers/stale_number_block_version_is_refused_and_the_refreshed_one_succeeds
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account("ACCT1048", billing_name="ZINNIA AS", service_state_code="CA")
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(
        jurisdiction["id"], npa_nxx="415634",
        total_capacity=4, max_concurrent_reservations=3,
    )
    number_one = seed_phone_number(block["id"], "4801")
    number_two = seed_phone_number(block["id"], "4802")

    blk_v1 = validate_success(
        api.get_number_block(block["id"], make_numbering_admin_headers()), 200
    )["version"]

    def _reservation_body(version):
        return make_number_reservation_payload(
            block["id"],
            account["id"],
            version,
            purpose="NEW_LINE",
            reserved_from="2026-08-04T00:00:00.000Z",
            reserved_until="2026-08-06T00:00:00.000Z",
        )

    first = validate_success(
        api.create_number_reservation(
            _reservation_body(blk_v1), make_numbering_admin_headers()
        ),
        201,
    )
    assert first["number_id"] == number_one["id"]

    resp = api.create_number_reservation(
        _reservation_body(blk_v1), make_numbering_admin_headers()
    )
    validate_error(resp, ApiErrorId.ERR_STALE_NUMBER_BLOCK_VERSION.value, 412)

    rows, meta = validate_paginated(
        api.list_number_reservations(
            make_numbering_admin_headers(), params={"block_id": block["id"]}
        )
    )
    assert meta["total_count"] == 1, f"the refused reservation was persisted: {rows}"

    blk_v2 = validate_success(
        api.get_number_block(block["id"], make_numbering_admin_headers()), 200
    )["version"]
    assert blk_v2 == blk_v1 + 1, (
        f"exactly one write should have advanced the block: {blk_v1} -> {blk_v2}"
    )

    second = validate_success(
        api.create_number_reservation(
            _reservation_body(blk_v2), make_numbering_admin_headers()
        ),
        201,
    )
    assert second["number_id"] == number_two["id"]

    final_block = read_number_block(block["id"])
    assert_block_census(final_block, minted=2, available=0, reserved=2, assigned=0, parked=0)
    assert final_block["version"] == blk_v1 + 2


def test_stale_port_request_version_is_refused_after_a_resubmit_bumped_it(api):
    """If it does not equal that port request's current `version`, the write is refused with `ERR_STALE_PORT_REQUEST_VERSION` (HTTP 412).

    The resubmission returned the request to `SUBMITTED`, so a second snapshot is
    a legal operation and the only defect is the liaison's stale token.

    Design: Corner/cross_cutting_complexity_layers/stale_port_request_version_is_refused_after_a_resubmit_bumped_it
    """
    set_clock("2026-08-03T09:00:00.000Z")
    account = seed_account("ACCT1049", billing_name="ALDER OY", service_state_code="CA")
    carrier = seed_carrier(
        "AL24",
        name="Alder Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )
    port_request = seed_port_request(
        account["id"],
        carrier["id"],
        requested_numbers=["+14155551812"],
        claimed_account_number="CSR-1049",
        claimed_pin="0000",
        claimed_billing_name="ALDER OY",
        claimed_address_line1="49 ALDER ARCH",
        claimed_zip="94577",
    )
    pr_v1 = port_request["version"]

    on_file = {
        "account_number_on_file": "CSR-1049",
        "pin_on_file": "1049",
        "billing_name_on_file": "ALDER OY",
        "address_line1_on_file": "49 ALDER ARCH",
        "zip_on_file": "94577",
    }

    # A STRICT carrier demands all five points, so the wrong pin mismatches.
    post_csr_snapshot(port_request["id"], expected_port_request_version=pr_v1, **on_file)

    resubmitted = resubmit_port_request(
        port_request["id"],
        claimed_account_number="CSR-1049",
        claimed_pin="1049",
        claimed_billing_name="ALDER OY",
        claimed_address_line1="49 ALDER ARCH",
        claimed_zip="94577",
    )
    pr_v3 = resubmitted["version"]
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["resubmission_count"] == 1
    assert pr_v3 == pr_v1 + 2, f"expected version {pr_v1 + 2}, got {pr_v3}"

    resp = api.create_csr_snapshot(
        port_request["id"],
        make_csr_snapshot_payload(pr_v1, **on_file),
        make_carrier_liaison_headers(LIAISON_USER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PORT_REQUEST_VERSION.value, 412)

    rows, meta = validate_paginated(
        api.list_csr_snapshots(
            port_request["id"], make_carrier_liaison_headers(LIAISON_USER_ID)
        )
    )
    assert meta["total_count"] == 1, f"the refused snapshot was persisted: {rows}"

    snapshot = validate_success(
        api.create_csr_snapshot(
            port_request["id"],
            make_csr_snapshot_payload(pr_v3, **on_file),
            make_carrier_liaison_headers(LIAISON_USER_ID),
        ),
        201,
    )
    assert snapshot["match_status"] == "MATCHED"
    assert read_port_request(port_request["id"])["status"] == "VALIDATED"


def test_the_fourth_rapid_international_attempt_crosses_the_fraud_threshold(api):
    """The comparison against the threshold is at-or-above, so a score of exactly 60 blocks the call and 59 does not.

    Four one-minute calls at a frozen clock score 39, 49, 59 and 69: velocity and
    spread grow with the run while geography stays pinned at the worst country
    seen.

    Design: Corner/cross_cutting_complexity_layers/the_fourth_rapid_international_attempt_crosses_the_fraud_threshold
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account(
        "ACCT1050",
        billing_name="BIRCH SPA",
        service_state_code="CA",
        intl_calling_enabled=True,
    )
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(jurisdiction["id"], npa_nxx="415635", total_capacity=10)
    number = seed_phone_number(block["id"], "4901")
    device = seed_device(
        account["id"],
        "AABBCC004901",
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1="50 BIRCH BEND",
        city="OAKLAND",
        state_code="CA",
        postal_code="94601",
        unit="",
    )
    verify_registration(registration["id"], "VERIFIED")

    # Four days on, so the device is no longer young and the multiplier is 1.0.
    set_clock("2026-08-05T10:00:00.000Z")
    owner = make_account_admin_headers(account["id"])

    first = validate_success(
        api.create_call_attempt(
            device["id"],
            make_call_attempt_payload("+252612345678", "252", 60),
            owner,
        ),
        201,
    )
    assert first["decision"] == "ALLOWED"
    assert first["realtime_risk_score"] == 39
    assert first["rate_cents_per_minute"] == 140
    assert_cents_equal(first["day_subtotal_cents"], 140, "day_subtotal_cents")

    second = validate_success(
        api.create_call_attempt(
            device["id"],
            make_call_attempt_payload("+2348012345678", "234", 60),
            owner,
        ),
        201,
    )
    assert second["decision"] == "ALLOWED"
    assert second["realtime_risk_score"] == 49
    assert second["rate_cents_per_minute"] == 95
    assert_cents_equal(second["day_subtotal_cents"], 235, "day_subtotal_cents")

    third = validate_success(
        api.create_call_attempt(
            device["id"],
            make_call_attempt_payload("+5355551234", "53", 60),
            owner,
        ),
        201,
    )
    assert third["decision"] == "ALLOWED"
    assert third["realtime_risk_score"] == 59
    assert third["rate_cents_per_minute"] == 60
    assert_cents_equal(third["day_subtotal_cents"], 295, "day_subtotal_cents")

    resp = api.create_call_attempt(
        device["id"],
        make_call_attempt_payload("+447700900502", "44", 60),
        owner,
    )
    validate_error(resp, ApiErrorId.ERR_TOLL_FRAUD_THRESHOLD_BREACHED.value, 409)

    rows, meta = validate_paginated(api.list_call_attempts(device["id"], owner))
    assert meta["total_count"] == 4
    blocked = find_by(rows, decision="BLOCKED_FRAUD")
    assert blocked["realtime_risk_score"] == 69
    assert blocked["decision_error_id"] == ApiErrorId.ERR_TOLL_FRAUD_THRESHOLD_BREACHED.value
    assert count_by(rows, decision="BLOCKED_FRAUD") == 1

    scored = read_device(device["id"])
    assert scored["toll_fraud_score"] == 69
    assert scored["fraud_block_count"] == 1
    assert scored["calling_status"] == "INTL_BLOCKED"


def test_derived_fields_are_visible_in_the_response_that_changed_them(api):
    """Unless an endpoint's description states otherwise, a successful response returns the complete resource, with every computed and system-managed field populated to its post-operation value.

    No re-read is needed anywhere: the census, the posture and both fee ledgers
    are already true in the very next call after the write that moved them.

    Design: Corner/consistency_model/derived_fields_are_visible_in_the_response_that_changed_them
    """
    set_clock("2026-08-01T00:00:00.000Z")
    account = seed_account("ACCT1051", billing_name="CEDAR LLC", service_state_code="CA")
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(jurisdiction["id"], npa_nxx="415636", total_capacity=10)
    number = seed_phone_number(block["id"], "5001")

    owner = make_account_admin_headers(account["id"])

    device = validate_success(
        api.create_device(
            {
                "account_id": account["id"],
                "mac_address": "AABBCC005001",
                "device_type": "HANDSET",
                "nomadic": False,
                "assigned_number_id": number["id"],
            },
            owner,
        ),
        201,
    )

    # The very next call already sees the number counted as assigned.
    after_assignment = validate_success(
        api.get_number_block(block["id"], make_numbering_admin_headers()), 200
    )
    assert_block_census(
        after_assignment, minted=1, available=0, reserved=0, assigned=1, parked=0
    )

    registration = validate_success(
        api.create_e911_registration(
            make_e911_registration_payload(
                device["id"],
                jurisdiction["id"],
                address_line1="51 CEDAR CLOSE",
                city="OAKLAND",
                state_code="CA",
                postal_code="94601",
                unit="",
            ),
            owner,
        ),
        201,
    )

    verified = validate_success(
        api.verify_e911_registration(
            registration["id"],
            make_verify_payload("VERIFIED"),
            make_e911_validator_headers(),
        ),
        200,
    )
    assert verified["verification_status"] == "VERIFIED"
    assert_instant(verified["verified_at"], "2026-08-01T00:00:00.000Z", "verified_at")

    after_verification = validate_success(api.get_account(account["id"], owner), 200)
    assert after_verification["e911_compliance_posture"] == "COMPLIANT"

    assessment = validate_success(
        api.create_fee_assessment(
            make_fee_assessment_payload(account["id"], jurisdiction["id"], "2026-08"),
            make_billing_admin_headers(BILLING_USER_ID),
        ),
        201,
    )
    assert_cents_equal(assessment["amount_cents"], 175)

    after_assessment = validate_success(
        api.get_jurisdiction(jurisdiction["id"], make_billing_admin_headers(BILLING_USER_ID)),
        200,
    )
    assert_cents_equal(after_assessment["pending_fee_cents"], 175, "pending_fee_cents")

    charged = validate_success(api.get_account(account["id"], owner), 200)
    assert_cents_equal(charged["fee_liability_cents"], 175, "fee_liability_cents")

    # A unit anchored on day 1 of the period is charged the whole month.
    assert assessment["variant"] == "PROVISIONAL"
    assert assessment["billable_units"] == 1
    assert assessment["unit_fee_breakdown"] == [175]
    assert_null(assessment["remitted_at"], "remitted_at")
