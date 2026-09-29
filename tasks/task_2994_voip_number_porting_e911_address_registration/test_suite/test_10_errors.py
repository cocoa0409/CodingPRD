"""Error-catalogue triggerability: each refusal is raised on a request whose
only defect is the one the PRD names, so the returned `error_id` and HTTP status
identify exactly one rung of the §2.7 precedence ladder.

Every test builds its own preconditions against a fresh, empty database and,
where the PRD says nothing is persisted, proves it with a list read.
"""
from test_helpers import (
    BILLING_USER_ID,
    BILLING_USER_ID_ALT,
    LIAISON_USER_ID,
    PLATFORM_USER_ID,
    PORTING_USER_ID,
    ApiErrorId,
    assess_fee,
    assert_block_census,
    assert_cents,
    assert_cents_equal,
    assert_null,
    assert_pagination_meta,
    ids_of,
    make_account_admin_headers,
    make_billing_admin_headers,
    make_blank_role_headers,
    make_carrier_liaison_headers,
    make_cutover_slot_payload,
    make_e911_registration_payload,
    make_fee_assessment_payload,
    make_matching_csr_snapshot_payload,
    make_numbering_admin_headers,
    make_phone_number_payload,
    make_platform_admin_headers,
    make_port_request_payload,
    make_porting_specialist_headers,
    make_void_payload,
    prorated_unit_fee_cents,
    read_account,
    read_device,
    read_jurisdiction,
    read_number_block,
    read_port_request,
    seed_account,
    seed_carrier,
    seed_device,
    seed_jurisdiction,
    seed_number_block,
    seed_phone_number,
    seed_port_request,
    set_clock,
    setup_compliant_device,
    setup_registered_device,
    setup_submitted_port_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify_registration,
)

CLOCK_BASE = "2026-08-01T00:00:00.000Z"
CLOCK_MONDAY = "2026-08-03T09:00:00.000Z"
CLOCK_MID_AUGUST = "2026-08-15T00:00:00.000Z"


def test_request_missing_x_user_role_header_is_unauthenticated(api):
    """If either header is absent, present but empty, or `X-User-Role` names something that is not one of the eight roles below, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined.

    The role header is present but empty — the empty string, not a space — on a
    read whose path, id and authorization would otherwise all be fine.

    Design: Corner/errors/request_missing_x_user_role_header_is_unauthenticated
    """
    set_clock(CLOCK_BASE)
    account = seed_account("ACCT1037", billing_name="LARKSPUR SA", service_state_code="CA",
                           status="ACTIVE")

    blank_role = make_blank_role_headers(PLATFORM_USER_ID)
    assert blank_role["X-User-Role"] == "", "the role header must be the empty string"

    response = api.get_account(account["id"], blank_role)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # The same read with a well-formed role header proves the route and id were fine.
    same_read = api.get_account(account["id"], make_platform_admin_headers())
    data = validate_success(same_read, 200)
    assert data["id"] == account["id"]


def test_list_with_limit_zero_returns_invalid_pagination(api):
    """A `limit` outside the range 1 through 100, an `offset` below zero, or a non-integer value for either is refused with `ERR_INVALID_PAGINATION` (HTTP 400).

    A `limit` of 0 is below the floor; a `limit` of exactly 100 is accepted, so
    only the floor was violated.

    Design: Corner/errors/list_with_limit_zero_returns_invalid_pagination
    """
    set_clock(CLOCK_BASE)
    jurisdiction = seed_jurisdiction("CA", "06001", fee_type="PER_LINE",
                                    monthly_fee_cents=175, remit_day_of_month=5)
    block = seed_number_block(jurisdiction["id"], npa_nxx="415624", total_capacity=4,
                              max_concurrent_reservations=2)

    headers = make_numbering_admin_headers()
    refused = api.list_number_blocks(headers, params={"limit": 0, "offset": 0})
    validate_error(refused, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)

    accepted = api.list_number_blocks(headers, params={"limit": 100, "offset": 0})
    rows, meta = validate_paginated(accepted)
    assert_pagination_meta(meta, limit=100, offset=0, total_count=1, has_more=False)
    assert ids_of(rows) == [block["id"]]


def test_suspended_account_cannot_open_a_port_request(api):
    """Filing requires the owning account to be `ACTIVE`, failing which the request is refused with `ERR_ACCOUNT_NOT_ACTIVE`.

    The account resolves and every body field is valid, so the refusal is the
    409 of the account-status rung rather than a 404 or a 400, and no port
    request row is written.

    Design: Corner/errors/suspended_account_cannot_open_a_port_request
    """
    set_clock(CLOCK_BASE)
    account = seed_account("ACCT1038", billing_name="MALLOW BV", service_state_code="CA",
                           status="SUSPENDED")
    carrier = seed_carrier("ML19", name="Mallow Legacy", csr_match_policy="STRICT",
                           porting_buffer_minutes=30, foc_business_days=2)

    response = api.create_port_request(
        make_port_request_payload(
            account["id"],
            carrier["id"],
            requested_numbers=["+14155551806"],
            claimed_account_number="CSR-1038",
            claimed_pin="1038",
            claimed_billing_name="MALLOW BV",
            claimed_address_line1="38 MALLOW MEWS",
            claimed_zip="94577",
        ),
        make_porting_specialist_headers(PORTING_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value, 409)

    # Nothing was persisted: the account's port-request collection is still empty.
    listing = api.list_port_requests(
        make_porting_specialist_headers(PORTING_USER_ID),
        params={"account_id": account["id"]},
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, f"expected no port request rows, got {meta['total_count']}"
    assert rows == []


def test_the_user_who_filed_the_port_cannot_also_snapshot_its_csr(api):
    """A `CarrierLiaison` transcribing a losing carrier's customer service record onto a port request must not be the principal recorded in that request's `created_by_user_id`.

    The body is valid, the acting role is the required liaison and the version
    token is fresh, so the only defect is the colliding acting identity.

    Design: Corner/errors/the_user_who_filed_the_port_cannot_also_snapshot_its_csr
    """
    set_clock(CLOCK_MONDAY)
    scenario = setup_submitted_port_request(
        account_number="ACCT1039",
        ocn="NL20",
        account_overrides={"billing_name": "NETTLE KK", "service_state_code": "CA",
                           "status": "ACTIVE"},
        carrier_overrides={"name": "Nettle Legacy", "csr_match_policy": "STRICT",
                           "porting_buffer_minutes": 30, "foc_business_days": 2},
        requested_numbers=["+14155551807"],
        claimed_account_number="CSR-1039",
        claimed_pin="1039",
        claimed_billing_name="NETTLE KK",
        claimed_address_line1="39 NETTLE NOOK",
        claimed_zip="94577",
    )
    port_request = scenario["port_request"]
    claimed = scenario["claimed"]
    first_version = port_request["version"]
    assert port_request["created_by_user_id"] == PORTING_USER_ID
    assert port_request["status"] == "SUBMITTED"

    conflicted = api.create_csr_snapshot(
        port_request["id"],
        make_matching_csr_snapshot_payload(first_version, claimed),
        make_carrier_liaison_headers(PORTING_USER_ID),
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403)

    unchanged = read_port_request(port_request["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["version"] == first_version

    accepted = api.create_csr_snapshot(
        port_request["id"],
        make_matching_csr_snapshot_payload(first_version, claimed),
        make_carrier_liaison_headers(LIAISON_USER_ID),
    )
    snapshot = validate_success(accepted, 201)
    assert snapshot["match_status"] == "MATCHED"
    assert snapshot["match_points"] == 100

    after = read_port_request(port_request["id"])
    assert after["status"] == "VALIDATED"


def test_minting_past_total_capacity_is_rejected(api):
    """Minting is refused with `ERR_BLOCK_CAPACITY_EXHAUSTED` once the block's `minted_count` has reached its `total_capacity`, and a `line_number` that already exists in that block is refused with `ERR_DUPLICATE_IDENTIFIER`.

    With a `total_capacity` of 1 the first mint succeeds and the second is
    refused, so the ceiling is compared before the row is inserted.

    Design: Corner/errors/minting_past_total_capacity_is_rejected
    """
    set_clock(CLOCK_BASE)
    jurisdiction = seed_jurisdiction("CA", "06001", fee_type="PER_LINE",
                                    monthly_fee_cents=175, remit_day_of_month=5)
    block = seed_number_block(jurisdiction["id"], npa_nxx="415625", total_capacity=1,
                              max_concurrent_reservations=1)
    first_number = seed_phone_number(block["id"], "4001")

    response = api.mint_phone_number(
        block["id"], make_phone_number_payload("4002"), make_numbering_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_BLOCK_CAPACITY_EXHAUSTED.value, 409)

    after = read_number_block(block["id"])
    assert_block_census(after, minted=1, available=1, reserved=0, assigned=0, parked=0)

    # Nothing was written: the block still holds exactly the one number it minted.
    listing = api.list_phone_numbers(
        make_numbering_admin_headers(), params={"block_id": block["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, f"expected one minted number, got {meta['total_count']}"
    assert ids_of(rows) == [first_number["id"]]


def test_registration_addressed_to_a_foreign_state_jurisdiction_is_rejected(api):
    """The registration's `state_code` must equal the named jurisdiction's `state_code`, and a discrepancy is refused with `ERR_JURISDICTION_STATE_MISMATCH`.

    Both rows resolve and the civic address is well formed, so the only defect
    is that the captured `CA` address names the `NV` jurisdiction.

    Design: Corner/errors/registration_addressed_to_a_foreign_state_jurisdiction_is_rejected
    """
    set_clock(CLOCK_BASE)
    account = seed_account("ACCT1040", billing_name="OLIVE SPA", service_state_code="CA",
                           status="ACTIVE")
    jurisdiction_ca = seed_jurisdiction("CA", "06001", fee_type="PER_LINE",
                                        monthly_fee_cents=175, remit_day_of_month=5)
    jurisdiction_nv = seed_jurisdiction("NV", "32003", fee_type="PER_LINE",
                                        monthly_fee_cents=90, remit_day_of_month=10)
    block = seed_number_block(jurisdiction_ca["id"], npa_nxx="415626", total_capacity=10,
                              max_concurrent_reservations=2)
    number = seed_phone_number(block["id"], "4101")
    device = seed_device(account["id"], "AABBCC004101", device_type="HANDSET",
                        nomadic=False, assigned_number_id=number["id"])
    assert device["registration_status"] == "PENDING_REGISTRATION"

    owner_headers = make_account_admin_headers(account["id"])
    foreign = api.create_e911_registration(
        make_e911_registration_payload(
            device["id"], jurisdiction_nv["id"], address_line1="40 OLIVE OVAL",
            city="OAKLAND", state_code="CA", postal_code="94601", unit="",
        ),
        owner_headers,
    )
    validate_error(foreign, ApiErrorId.ERR_JURISDICTION_STATE_MISMATCH.value, 422)

    still_pending = read_device(device["id"])
    assert still_pending["registration_status"] == "PENDING_REGISTRATION"

    # Nothing was written: the device still has no dispatchable location at all.
    listing = api.list_e911_registrations(
        make_platform_admin_headers(), params={"device_id": device["id"]}
    )
    _rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, f"expected no registration rows, got {meta['total_count']}"

    matching = api.create_e911_registration(
        make_e911_registration_payload(
            device["id"], jurisdiction_ca["id"], address_line1="40 OLIVE OVAL",
            city="OAKLAND", state_code="CA", postal_code="94601", unit="",
        ),
        owner_headers,
    )
    registration = validate_success(matching, 201)
    assert registration["verification_status"] == "UNVERIFIED"
    assert read_device(device["id"])["registration_status"] == "ADDRESS_UNVERIFIED"


def test_assessing_a_jurisdiction_with_no_eligible_registration_has_no_billable_units(api):
    """If the selection produces no units at all, the assessment is refused with `ERR_NO_BILLABLE_UNITS` (422) and nothing is written.

    The account has a number-holding device with a captured location, but that
    location is still `UNVERIFIED` and so falls outside the eligible set.

    Design: Corner/errors/assessing_a_jurisdiction_with_no_eligible_registration_has_no_billable_units
    """
    set_clock(CLOCK_MID_AUGUST)
    scenario = setup_registered_device(
        account_number="ACCT1041",
        npa_nxx="415627",
        line_number="4201",
        mac_address="AABBCC004201",
        device_overrides={"device_type": "HANDSET", "nomadic": False},
        registration_overrides={"address_line1": "41 PRIMROSE PARK", "city": "OAKLAND",
                                "state_code": "CA", "postal_code": "94601", "unit": ""},
        account_overrides={"billing_name": "PRIMROSE AB", "service_state_code": "CA",
                           "status": "ACTIVE"},
        jurisdiction_overrides={"fee_type": "PER_LINE", "monthly_fee_cents": 175,
                                "remit_day_of_month": 5},
        block_overrides={"total_capacity": 10, "max_concurrent_reservations": 2},
    )
    account = scenario["account"]
    jurisdiction = scenario["jurisdiction"]
    registration = scenario["registration"]
    assert registration["verification_status"] == "UNVERIFIED"

    billing_headers = make_billing_admin_headers(BILLING_USER_ID)
    refused = api.create_fee_assessment(
        make_fee_assessment_payload(account["id"], jurisdiction["id"], "2026-08"),
        billing_headers,
    )
    validate_error(refused, ApiErrorId.ERR_NO_BILLABLE_UNITS.value, 422)

    assert_cents_equal(read_jurisdiction(jurisdiction["id"])["pending_fee_cents"], 0,
                       "pending_fee_cents")
    assert_cents_equal(read_account(account["id"])["fee_liability_cents"], 0,
                       "fee_liability_cents")

    # Nothing was written: no assessment row exists for the account at all.
    listing = api.list_fee_assessments(billing_headers, params={"account_id": account["id"]})
    _rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, f"expected no assessment rows, got {meta['total_count']}"

    verify_registration(registration["id"], "VERIFIED")
    accepted = api.create_fee_assessment(
        make_fee_assessment_payload(account["id"], jurisdiction["id"], "2026-08"),
        billing_headers,
    )
    assessment = validate_success(accepted, 201)
    assert assessment["billable_units"] == 1
    assert_cents(assessment["amount_cents"])


def test_a_second_provisional_assessment_for_the_same_period_is_rejected(api):
    """No other assessment may exist for the same account, jurisdiction and period with status `ASSESSED` — a second one is `ERR_DUPLICATE_PROVISIONAL_ASSESSMENT` (409) — and the same triple must have no `REMITTED` assessment already, because a remitted period is closed both to further assessment and to voiding; that is `ERR_ASSESSMENT_PERIOD_ALREADY_REMITTED` (409).

    Voiding the standing row releases the triple, so the re-assessment then
    succeeds and the ledger still holds exactly one live charge.

    Design: Corner/errors/a_second_provisional_assessment_for_the_same_period_is_rejected
    """
    set_clock(CLOCK_MID_AUGUST)
    scenario = setup_compliant_device(
        account_number="ACCT1042",
        npa_nxx="415628",
        line_number="4301",
        mac_address="AABBCC004301",
        device_overrides={"device_type": "HANDSET", "nomadic": False},
        registration_overrides={"address_line1": "42 QUILL QUAY", "city": "OAKLAND",
                                "state_code": "CA", "postal_code": "94601", "unit": ""},
        account_overrides={"billing_name": "QUILL LDA", "service_state_code": "CA",
                           "status": "ACTIVE"},
        jurisdiction_overrides={"fee_type": "PER_LINE", "monthly_fee_cents": 175,
                                "remit_day_of_month": 5},
        block_overrides={"total_capacity": 10, "max_concurrent_reservations": 2},
    )
    account = scenario["account"]
    jurisdiction = scenario["jurisdiction"]
    assert scenario["registration"]["verification_status"] == "VERIFIED"

    # A unit anchored on the 15th of a 31-day month is active for 17 days.
    expected_cents = prorated_unit_fee_cents(175, 17, 31)

    first = assess_fee(account["id"], jurisdiction["id"], "2026-08")
    assert_cents_equal(first["amount_cents"], expected_cents)
    assert first["status"] == "ASSESSED"
    assert first["variant"] == "PROVISIONAL"

    duplicate = api.create_fee_assessment(
        make_fee_assessment_payload(account["id"], jurisdiction["id"], "2026-08"),
        make_billing_admin_headers(BILLING_USER_ID),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_PROVISIONAL_ASSESSMENT.value, 409)

    voided = api.void_fee_assessment(
        first["id"], make_void_payload(void_note="re-assessing"),
        make_billing_admin_headers(BILLING_USER_ID_ALT),
    )
    voided_row = validate_success(voided, 200)
    assert voided_row["status"] == "VOIDED"
    assert voided_row["voided_by_user_id"] == BILLING_USER_ID_ALT

    reassessed = api.create_fee_assessment(
        make_fee_assessment_payload(account["id"], jurisdiction["id"], "2026-08"),
        make_billing_admin_headers(BILLING_USER_ID),
    )
    second = validate_success(reassessed, 201)
    assert_cents_equal(second["amount_cents"], expected_cents)
    assert second["status"] == "ASSESSED"

    assert_cents_equal(read_jurisdiction(jurisdiction["id"])["pending_fee_cents"],
                       expected_cents, "pending_fee_cents")
    assert_cents_equal(read_account(account["id"])["fee_liability_cents"],
                       expected_cents, "fee_liability_cents")


def test_a_thirty_minute_cutover_window_is_rejected(api):
    """The **length test runs first**: `window_end` must be strictly later than `window_start`, and the length of the window measured in whole minutes must be at least 60 and at most 480 — no shorter than an hour, no longer than an eight-hour shift.

    A violation of either half is `ERR_CUTOVER_WINDOW_LENGTH_INVALID`, and a
    window of exactly 60 minutes is accepted, so the minimum is inclusive.

    Design: Corner/errors/a_thirty_minute_cutover_window_is_rejected
    """
    set_clock(CLOCK_MONDAY)
    carrier = seed_carrier("RL21", name="Rowan Legacy", csr_match_policy="STRICT",
                           porting_buffer_minutes=30, foc_business_days=2)

    specialist = make_porting_specialist_headers(PORTING_USER_ID)
    too_short = api.create_cutover_slot(
        make_cutover_slot_payload(
            carrier["id"],
            window_start="2026-08-06T14:00:00.000Z",
            window_end="2026-08-06T14:30:00.000Z",
        ),
        specialist,
    )
    validate_error(too_short, ApiErrorId.ERR_CUTOVER_WINDOW_LENGTH_INVALID.value, 422)

    exactly_sixty = api.create_cutover_slot(
        make_cutover_slot_payload(
            carrier["id"],
            window_start="2026-08-06T14:00:00.000Z",
            window_end="2026-08-06T15:00:00.000Z",
        ),
        specialist,
    )
    slot = validate_success(exactly_sixty, 201)
    assert slot["status"] == "OPEN"
    assert_null(slot["booked_port_request_id"], "booked_port_request_id")

    # The refused candidate wrote nothing: only the 60-minute slot exists.
    listing = api.list_cutover_slots(specialist, params={"carrier_id": carrier["id"]})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, f"expected one cutover slot, got {meta['total_count']}"
    assert ids_of(rows) == [slot["id"]]


def test_porting_a_number_already_inside_a_live_request_is_rejected(api):
    """It also requires that no other port request of the same account is simultaneously laying claim to any of the same numbers: if another request of that account is in `SUBMITTED`, `CSR_MISMATCH`, `VALIDATED`, `SCHEDULED`, `BRIDGED` or `REJECTED` status and its `requested_numbers` shares even one E.164 string with the new array, the filing is refused with `ERR_ACTIVE_PORT_REQUEST_EXISTS`.

    A filing over a disjoint number set is accepted in exactly the same state,
    so it is the shared E.164 string and nothing else that refuses the first.

    Design: Corner/errors/porting_a_number_already_inside_a_live_request_is_rejected
    """
    set_clock(CLOCK_MONDAY)
    account = seed_account("ACCT1043", billing_name="SUMAC OY", service_state_code="CA",
                           status="ACTIVE")
    carrier = seed_carrier("SL22", name="Sumac Legacy", csr_match_policy="STRICT",
                           porting_buffer_minutes=30, foc_business_days=2)
    claims = {
        "claimed_account_number": "CSR-1043",
        "claimed_pin": "1043",
        "claimed_billing_name": "SUMAC OY",
        "claimed_address_line1": "43 SUMAC SQ",
        "claimed_zip": "94577",
    }
    first = seed_port_request(
        account["id"], carrier["id"],
        requested_numbers=["+14155551808", "+14155551809"], **claims
    )
    assert first["status"] == "SUBMITTED"

    specialist = make_porting_specialist_headers(PORTING_USER_ID)
    overlapping = api.create_port_request(
        make_port_request_payload(account["id"], carrier["id"],
                                  requested_numbers=["+14155551809"], **claims),
        specialist,
    )
    validate_error(overlapping, ApiErrorId.ERR_ACTIVE_PORT_REQUEST_EXISTS.value, 409)

    disjoint = api.create_port_request(
        make_port_request_payload(account["id"], carrier["id"],
                                  requested_numbers=["+14155551810"], **claims),
        specialist,
    )
    second = validate_success(disjoint, 201)
    assert second["status"] == "SUBMITTED"

    # The refused filing wrote nothing: the account holds exactly two requests.
    listing = api.list_port_requests(specialist, params={"account_id": account["id"]})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 2, f"expected two port requests, got {meta['total_count']}"
    assert sorted(ids_of(rows)) == sorted([first["id"], second["id"]])
