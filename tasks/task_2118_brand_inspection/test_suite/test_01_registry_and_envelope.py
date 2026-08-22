"""The board's standing registry, the response envelope and the 404 families."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_bill_of_sale,
    assert_brand_application,
    assert_common_record_fields,
    assert_instant_equals,
    assert_inspector,
    assert_owner,
    assert_three_fraction_digit_timestamp,
    create_bill_of_sale_payload,
    create_brand_application_payload,
    create_inspector_payload,
    create_owner_payload,
    create_territory_payload,
    DEFAULT_CLOCK_UTC,
    commission_inspector,
    enrol_owner,
    make_brand_recorder_headers,
    make_field_inspector_headers,
    make_livestock_owner_headers,
    open_district,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_enrol_owner_stamps_good_standing_and_version_one(api):
    """PRD §3.1: "A newly enrolled owner begins in good fiscal standing — `standing`
    is `GOOD`, both `posted_arrears_cents` and `projected_arrears_cents` are 0, and
    `suspended_since` is null, since the owner has never been suspended."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by one on every mutation of that row, again including server-initiated
    cascades."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp
    with three fractional digits."

    Design: Corner/entities/corner_owner_creation_stamps_defaults_and_version_one
    """
    payload = create_owner_payload(
        legal_name="Corner Creek Ranch",
        mailing_state="WY",
        contact_email="corner@example.test",
    )
    response = api.create_owner(payload, BOARD_ADMIN)
    owner = validate_success(response, 201)

    assert_owner(owner)
    assert owner["standing"] == "GOOD", f"expected GOOD standing, got {owner['standing']}"
    assert owner["posted_arrears_cents"] == 0
    assert owner["projected_arrears_cents"] == 0
    assert owner["suspended_since"] is None, "a never-suspended owner has no suspended_since"
    assert owner["version"] == 1, f"a new row starts at version 1, got {owner['version']}"

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert_three_fraction_digit_timestamp(
        body["meta"]["api_request_timestamp"], "meta.api_request_timestamp"
    )


def test_read_owner_returns_the_particulars_captured_at_enrolment(api):
    """PRD §3.1: "Enrolling a livestock owner of record captures three particulars:
    the `legal_name` under which the producer holds property, a `mailing_state` given
    as the two-letter USPS code of the producer's mailing address, and a
    `contact_email` at which the board serves delinquency notices."

    Design: Corner/entities/corner_owner_retrieval_returns_stored_row
    """
    owner = enrol_owner(
        "Corner Creek Ranch", mailing_state="WY", contact_email="corner@example.test"
    )

    retrieved = validate_success(api.get_owner(owner["id"], BOARD_ADMIN), 200)

    assert_owner(retrieved)
    assert retrieved["id"] == owner["id"]
    assert retrieved["legal_name"] == "Corner Creek Ranch"
    assert retrieved["mailing_state"] == "WY"
    assert retrieved["contact_email"] == "corner@example.test"


def test_inspector_roster_page_reports_total_count_and_has_more(api):
    """PRD §2.3: "`limit` caps the number of rows returned; when it is omitted the
    server applies a default of 10, and a supplied value must be at least 1 and at
    most 100."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` reports
    the number of rows matching the filter across all pages and `has_more` reports
    whether any rows remain beyond the returned page."

    Design: Corner/entities/corner_inspector_listing_paginates_with_total_count
    """
    territory = open_district("T-PAGE")
    for badge in ("P-001", "P-002", "P-003"):
        commission_inspector(territory["id"], badge_number=badge)

    response = api.list_inspectors(
        BOARD_ADMIN,
        params={"home_territory_id": territory["id"], "limit": 2, "offset": 0},
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(rows) == 2, f"limit 2 must return 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    for row in rows:
        assert_inspector(row)


def test_unknown_inspection_order_id_reports_order_not_found(api):
    """PRD §2.8: "Every identifier embedded in the URL must resolve to a live row, and
    identifiers are resolved strictly left to right so that the outermost missing
    resource is the one reported."
    PRD §2.8: "Depending on which identifier failed, the response carries
    `ERR_OWNER_NOT_FOUND`, `ERR_TERRITORY_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_BILL_OF_SALE_NOT_FOUND`,
    `ERR_ESTRAY_CASE_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND` or
    `ERR_REMITTANCE_NOT_FOUND`, each at HTTP 404 Not Found."

    Design: Corner/entities/corner_order_not_found_returns_order_not_found
    """
    response = api.get_inspection_order(UNKNOWN_ID, BOARD_ADMIN)

    error = validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_every_path_id_family_reports_its_own_not_found(api):
    """PRD §2.8: "Every identifier embedded in the URL must resolve to a live row, and
    identifiers are resolved strictly left to right so that the outermost missing
    resource is the one reported."
    PRD §2.8: "Depending on which identifier failed, the response carries
    `ERR_OWNER_NOT_FOUND`, `ERR_TERRITORY_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_BILL_OF_SALE_NOT_FOUND`,
    `ERR_ESTRAY_CASE_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND` or
    `ERR_REMITTANCE_NOT_FOUND`, each at HTTP 404 Not Found."

    Design: Corner/errors/corner_every_path_id_family_returns_its_own_not_found_error
    """
    recorder = make_brand_recorder_headers("recorder-01")
    probes = [
        (api.get_owner(UNKNOWN_ID, BOARD_ADMIN), ApiErrorId.ERR_OWNER_NOT_FOUND.value),
        (api.get_territory(UNKNOWN_ID, BOARD_ADMIN), ApiErrorId.ERR_TERRITORY_NOT_FOUND.value),
        (api.get_brand_application(UNKNOWN_ID, recorder), ApiErrorId.ERR_APPLICATION_NOT_FOUND.value),
        (api.adjudicate_claim(UNKNOWN_ID, recorder), ApiErrorId.ERR_CLAIM_NOT_FOUND.value),
        (
            api.record_finding(
                UNKNOWN_ID, {"finding": "MATCH_CONFIRMED"},
                make_field_inspector_headers(UNKNOWN_ID),
            ),
            ApiErrorId.ERR_LOT_NOT_FOUND.value,
        ),
        (api.get_bill_of_sale(UNKNOWN_ID, BOARD_ADMIN), ApiErrorId.ERR_BILL_OF_SALE_NOT_FOUND.value),
        (
            api.claim_estray(UNKNOWN_ID, make_livestock_owner_headers(UNKNOWN_ID)),
            ApiErrorId.ERR_ESTRAY_CASE_NOT_FOUND.value,
        ),
        (
            api.refer_investigation(
                UNKNOWN_ID, {"referral_agency": "MT Department of Livestock"},
                TEST_USERS["theft_investigator_headers"],
            ),
            ApiErrorId.ERR_INVESTIGATION_NOT_FOUND.value,
        ),
        (
            api.reconcile_remittance(UNKNOWN_ID, TEST_USERS["fee_administrator_headers"]),
            ApiErrorId.ERR_REMITTANCE_NOT_FOUND.value,
        ),
    ]

    for response, expected_error_id in probes:
        assert response.status_code == 404, (
            f"expected HTTP 404 for {expected_error_id}, got {response.status_code}: "
            f"{response.text}"
        )
        validate_error(response, expected_error_id, 404)


def test_district_without_impound_capacity_is_refused(api):
    """PRD §3.1: "An inspection district is created with a board-assigned
    `territory_code`, the two-letter `state_code` the district belongs to, a flat
    `travel_surcharge_cents` that is added to every fee assessed in that district, and
    an `impound_capacity_head` giving the maximum head the district's impound facility
    may hold at any single instant."
    PRD §2.8: "Any of these failing yields `ERR_INVALID_REQUEST` (HTTP 400 Bad Request)."

    Design: Corner/entities/corner_territory_missing_required_field_returns_invalid_request
    """
    payload = create_territory_payload(territory_code="T-BAD", travel_surcharge_cents=2500)
    del payload["impound_capacity_head"]

    response = api.create_territory(payload, BOARD_ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_commission_defaults_daily_ceiling_to_three_and_status_active(api):
    """PRD §3.1: "The caller may also set `max_daily_assignments`, the ceiling on how
    many orders the inspector may hold on a single UTC calendar date; when the field is
    omitted the board applies its default of 3, and a supplied value must be at least 1."
    PRD §3.1: "A new inspector is commissioned with `status` `ACTIVE` and `version` 1."
    PRD §3.1: "The roster read exposes `active_assignment_count`, the number of orders
    currently held by that inspector whose scheduling dimension reads `SCHEDULED` or
    `IN_FIELD`, and the roster listing may be narrowed by `home_territory_id` or by
    commission `status`."

    Design: Corner/entities/corner_inspector_max_daily_assignments_defaults_to_three
    """
    territory = open_district("T-DEF")
    payload = create_inspector_payload(territory["id"], badge_number="D-001")
    assert "max_daily_assignments" not in payload

    inspector = validate_success(api.create_inspector(payload, BOARD_ADMIN), 201)

    assert_inspector(inspector)
    assert inspector["max_daily_assignments"] == 3, (
        f"omitted ceiling defaults to 3, got {inspector['max_daily_assignments']}"
    )
    assert inspector["status"] == "ACTIVE"
    assert inspector["active_assignment_count"] == 0
    assert inspector["version"] == 1


def test_duplicate_badge_number_is_refused(api):
    """PRD §3.1: "Badge numbers are unique across the whole commission roll, and a
    duplicate is refused with `ERR_DUPLICATE_BADGE_NUMBER`."

    Design: Corner/errors/corner_duplicate_badge_number_rejected
    """
    territory = open_district("T-BADGE")
    commission_inspector(territory["id"], badge_number="DUP-01")

    duplicate = create_inspector_payload(
        territory["id"],
        badge_number="DUP-01",
        certification_expires_on="2028-12-31T00:00:00Z",
    )
    response = api.create_inspector(duplicate, BOARD_ADMIN)

    validate_error(response, ApiErrorId.ERR_DUPLICATE_BADGE_NUMBER.value, 409)

    rows, meta = validate_paginated(
        api.list_inspectors(BOARD_ADMIN, params={"home_territory_id": territory["id"]})
    )
    assert meta["total_count"] == 1, "the refused commission must not have been written"


def test_duplicate_territory_code_is_refused(api):
    """PRD §3.1: "The `territory_code` must be unique across every district on file;
    reusing one is refused with `ERR_DUPLICATE_TERRITORY_CODE`."

    Design: Corner/errors/corner_duplicate_territory_code_rejected
    """
    first = open_district(
        "T-TWICE", state_code="MT", travel_surcharge_cents=2500, impound_capacity_head=100
    )

    duplicate = create_territory_payload(
        territory_code="T-TWICE",
        state_code="WY",
        travel_surcharge_cents=3000,
        impound_capacity_head=50,
    )
    response = api.create_territory(duplicate, BOARD_ADMIN)

    validate_error(response, ApiErrorId.ERR_DUPLICATE_TERRITORY_CODE.value, 409)

    unchanged = validate_success(api.get_territory(first["id"], BOARD_ADMIN), 200)
    assert unchanged["travel_surcharge_cents"] == 2500
    assert unchanged["state_code"] == "MT"


def test_bill_of_sale_carries_no_version_or_updated_at(api):
    """PRD §2.4: "A bill of sale is an ownership instrument transcribed from paper and
    is immutable once written: it carries only `id` and `created_at`."
    PRD §2.4: "A bill of sale has no `updated_at` field and no `version` field, and no
    operation in this API modifies one after creation."
    PRD §2.4: "`created_at` is an ISO 8601 timestamp in UTC with three fractional
    digits, recording the logical-clock instant at which the row was first written."

    Design: Corner/entities/corner_bill_of_sale_is_immutable_and_carries_no_version
    """
    seller = enrol_owner("Seller Ranch", contact_email="seller@example.test")
    buyer = enrol_owner("Buyer Ranch", contact_email="buyer@example.test")

    payload = create_bill_of_sale_payload(
        seller["id"],
        buyer["id"],
        document_number="BOS-0001",
        sale_date="2026-08-01T00:00:00Z",
        head_count=40,
        species_class="CATTLE",
        brand_symbol_declared="7X",
    )
    instrument = validate_success(
        api.create_bill_of_sale(payload, make_livestock_owner_headers(seller["id"])), 201
    )

    assert_bill_of_sale(instrument)
    assert_three_fraction_digit_timestamp(instrument["created_at"], "created_at")
    assert "version" not in instrument
    assert "updated_at" not in instrument

    retrieved = validate_success(
        api.get_bill_of_sale(instrument["id"], BOARD_ADMIN), 200
    )
    assert retrieved["document_number"] == "BOS-0001"
    assert "version" not in retrieved
    assert "updated_at" not in retrieved


def test_duplicate_document_number_is_refused(api):
    """PRD §3.6: "`document_number` is unique across every instrument on file, and a
    reused number is refused with `ERR_DUPLICATE_DOCUMENT_NUMBER`."

    Design: Corner/validations/corner_duplicate_document_number_rejected
    """
    seller = enrol_owner("Dup Seller", contact_email="dseller@example.test")
    buyer = enrol_owner("Dup Buyer", contact_email="dbuyer@example.test")
    first = create_bill_of_sale_payload(
        seller["id"], buyer["id"], document_number="BOS-DUP",
        sale_date="2026-08-01T00:00:00Z", head_count=10, species_class="CATTLE",
    )
    validate_success(
        api.create_bill_of_sale(first, make_livestock_owner_headers(seller["id"])), 201
    )

    reuse = create_bill_of_sale_payload(
        buyer["id"], seller["id"], document_number="BOS-DUP",
        sale_date="2026-08-02T00:00:00Z", head_count=4, species_class="SHEEP",
    )
    response = api.create_bill_of_sale(
        reuse, make_livestock_owner_headers(buyer["id"])
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_DOCUMENT_NUMBER.value, 409)

    rows, meta = validate_paginated(
        api.list_bills_of_sale(BOARD_ADMIN, params={"seller_owner_id": buyer["id"]})
    )
    assert meta["total_count"] == 0, "the refused instrument must not have been written"


def test_undeclared_position_code_is_refused(api):
    """PRD §3.2: "The filing names the applicant as `owner_id`, declares an
    `application_type` of `NEW`, `TRANSFER` or `RENEWAL`, and describes the mark itself:
    a `brand_symbol` giving the textual rendering of the design (`7X` or `BAR-L`, for
    instance), a `position_code` naming the body location the brand is applied to — one
    of `LEFT_RIB`, `RIGHT_RIB`, `LEFT_HIP`, `RIGHT_HIP`, `LEFT_SHOULDER` or
    `RIGHT_SHOULDER` — a `species_class` of `CATTLE`, `HORSE` or `SHEEP`, and the
    two-letter `state_code` the mark is being recorded in."
    PRD §2.8: "Any of these failing yields `ERR_INVALID_REQUEST` (HTTP 400 Bad Request)."

    Design: Corner/entities/corner_application_position_code_invalid_enum_rejected
    """
    owner = enrol_owner("Enum Test Ranch", contact_email="enum@example.test")
    payload = create_brand_application_payload(
        owner["id"], brand_symbol="EE", position_code="LEFT_EAR"
    )

    response = api.create_brand_application(
        payload, make_livestock_owner_headers(owner["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_brand_applications(BOARD_ADMIN, params={"owner_id": owner["id"]})
    )
    assert meta["total_count"] == 0, "the refused filing must not have been written"


def test_new_filing_enters_submitted_with_flat_filing_fee(api):
    """PRD §3.2: "A new filing enters at status `SUBMITTED` with `correction_rounds` at
    0, `examined_by_user_id`, `recorded_by_user_id` and `rejection_reason` all null."
    PRD §3.2: "`assessed_filing_fee_cents` records the filing fee owed, which for a
    `NEW` or `TRANSFER` filing is a flat 9,000 cents."
    PRD §3.2: "`original_filed_at` records the logical-clock instant at which the
    application row was first created and is never changed again, not by correction and
    not by resubmission."
    PRD §2.5: "Before any client sets it, that clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time thereafter."

    Design: Corner/state_machines/corner_application_initial_state_is_submitted
    """
    owner = enrol_owner("Initial State Ranch", contact_email="init@example.test")
    payload = create_brand_application_payload(
        owner["id"], brand_symbol="IS", position_code="LEFT_RIB"
    )

    application = validate_success(
        api.create_brand_application(payload, make_livestock_owner_headers(owner["id"])),
        201,
    )

    assert_brand_application(application)
    assert application["status"] == "SUBMITTED"
    assert application["correction_rounds"] == 0
    assert application["examined_by_user_id"] is None
    assert application["recorded_by_user_id"] is None
    assert application["rejection_reason"] is None
    assert application["assessed_filing_fee_cents"] == 9000
    assert_instant_equals(
        application["original_filed_at"], DEFAULT_CLOCK_UTC, "original_filed_at"
    )


def test_inspector_version_advances_by_one_per_status_change(api):
    """PRD §3.1: "A `BoardAdmin` may later move an inspector's `status` between
    `ACTIVE`, `SUSPENDED` and `RETIRED` by supplying the new `status`; every such change
    increments the inspector's `version` by one, which by design invalidates any
    scheduling token a client was holding."
    PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed
    on every mutation of the row — including mutations the server performs on its own
    initiative as part of a cascade, and including rewrites of purely derived values
    such as an owner's arrears aggregates or a district's live occupancy."

    Design: Corner/cross_cutting_layers/corner_version_increments_on_every_mutation
    """
    territory = open_district("T-VER")
    inspector = commission_inspector(territory["id"], badge_number="VR-001")
    assert inspector["version"] == 1
    created_at = inspector["created_at"]

    suspended = validate_success(
        api.set_inspector_status(inspector["id"], {"status": "SUSPENDED"}, BOARD_ADMIN),
        200,
    )
    assert suspended["version"] == 2, f"expected version 2, got {suspended['version']}"

    retired = validate_success(
        api.set_inspector_status(inspector["id"], {"status": "RETIRED"}, BOARD_ADMIN), 200
    )
    assert retired["version"] == 3, f"expected version 3, got {retired['version']}"
    assert retired["status"] == "RETIRED"
    assert retired["created_at"] == created_at, "created_at never moves"
    assert_three_fraction_digit_timestamp(retired["updated_at"], "updated_at")
    assert_common_record_fields(retired)


def test_request_without_context_headers_is_refused(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value that
    is not one of the six roles the board recognises, the request is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401 Unauthorized) before any other consideration."

    Design: Corner/validations/corner_missing_role_header_returns_unauthenticated
    """
    payload = create_owner_payload(
        legal_name="No Header Ranch", contact_email="nohdr@example.test"
    )

    response = api.create_owner(payload, {})

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
