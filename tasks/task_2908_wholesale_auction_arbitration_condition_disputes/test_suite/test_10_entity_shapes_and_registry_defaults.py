"""Entity-level shapes: registry defaults, echoed sale block data, sale-list
pagination, server-minted computed fields and the flat foreign-key lookups."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_instant_equals,
    assert_mutable_common_fields,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import CLOCK_DEFAULT, MECHANICAL_POLICY, TITLE_BRANDED_POLICY
from test_helpers.factories import (
    case_payload,
    create_buyer,
    create_case,
    create_policy,
    create_sale,
    create_seller,
    evidence_payload,
    policy_payload,
    sale_payload,
    seller_payload,
    unique_vin,
)
from test_helpers.test_users import (
    admin_headers,
    arbitrator_headers,
    buyer_rep_headers,
    clerk_headers,
)


def test_a_freshly_registered_consignor_starts_clean_on_every_counter(api):
    """Name and licence are the only inputs, and the seven counters, the tier, the
    blocked timestamp and the version are all server-set opening values.

    PRD: "A freshly registered consignor begins in `policy_tier` `GOOD_STANDING`,
    with `blocked_at_utc` null, `reinstated_count` 0, and every counter and rate on
    its record at 0: `rolling_window_sales_count`, `rolling_window_upheld_count`,
    `lifetime_sales_count`, `lifetime_upheld_count`, `open_claim_count`,
    `rolling_arbitration_rate_bps` and `lifetime_arbitration_rate_bps`."

    Design: Corner/entities/seller_creation_returns_good_standing_and_zero_counters
    """
    payload = seller_payload(name="Ridgeline Motors")

    seller = validate_success(api.create_seller(payload, admin_headers()), 201)

    assert seller["name"] == "Ridgeline Motors"
    assert seller["dealer_license_no"] == payload["dealer_license_no"]
    assert seller["policy_tier"] == "GOOD_STANDING"
    assert seller["rolling_arbitration_rate_bps"] == 0
    assert seller["lifetime_arbitration_rate_bps"] == 0
    assert seller["rolling_window_sales_count"] == 0
    assert seller["rolling_window_upheld_count"] == 0
    assert seller["lifetime_sales_count"] == 0
    assert seller["lifetime_upheld_count"] == 0
    assert seller["open_claim_count"] == 0
    assert seller["reinstated_count"] == 0
    assert seller["blocked_at_utc"] is None
    assert seller["version"] == 1
    assert is_valid_uuid(seller["id"])
    assert_mutable_common_fields(seller, "seller")


def test_reading_a_sale_back_echoes_the_block_data_and_both_opening_dimensions(api):
    """Every field the clerk typed comes back byte for byte, and both independent
    state dimensions read their opening values.

    PRD: "Alongside them the record keeps `open_case_count` at 0, a
    `settlement_hold` flag at false, and `settled_at_utc` at null."

    Design: Corner/entities/sale_retrieval_returns_the_stored_block_data
    """
    seller = create_seller(api)
    buyer = create_buyer(api)
    payload = sale_payload(
        seller["id"],
        buyer["id"],
        sale_price_cents=1450000,
        announced_odometer_miles=84000,
        light_channel="GREEN",
        title_status="CLEAN",
    )
    created = validate_success(api.create_sale(payload, clerk_headers()), 201)

    sale = validate_success(api.get_sale(created["id"], admin_headers()), 200)

    assert sale["vin"] == payload["vin"]
    assert sale["seller_id"] == seller["id"]
    assert sale["buyer_id"] == buyer["id"]
    assert sale["sale_price_cents"] == 1450000
    assert_instant_equals(sale["hammer_time_utc"], CLOCK_DEFAULT, "hammer_time_utc")
    assert sale["announced_odometer_miles"] == 84000
    assert sale["light_channel"] == "GREEN"
    assert sale["title_status"] == "CLEAN"
    assert sale["settlement_status"] == "UNSETTLED"
    assert sale["settled_at_utc"] is None
    assert sale["arbitration_status"] == "NONE"
    assert sale["open_case_count"] == 0
    assert sale["settlement_hold"] is False
    assert sale["version"] == 1


def test_the_sale_list_reports_the_pre_limit_count_on_both_pages(api):
    """Two pages of a three-row result set: total_count is the same on both, and
    has_more flips only when the offset plus the returned rows reaches it.

    PRD: "`total_count` counts the rows that match the supplied filters *before*
    `limit` and `offset` are applied, so a caller can tell how deep the result set
    runs. `has_more` is true when the sum of `offset` and the number of rows
    actually returned in `data` is strictly less than `total_count`, and false
    otherwise."

    Design: Corner/entities/sales_listing_paginates_with_total_count_and_has_more
    """
    seller = create_seller(api)
    buyer = create_buyer(api)
    vins = [unique_vin() for _ in range(3)]
    for index, vin in enumerate(vins):
        create_sale(
            api,
            seller["id"],
            buyer["id"],
            vin=vin,
            sale_price_cents=900000 + index * 10000,
            announced_odometer_miles=60000 + index * 1000,
        )

    first_rows, first_meta = validate_paginated(
        api.list_sales(admin_headers(), params={"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True
    assert_created_at_ascending(first_rows, "first page of sales")

    second_rows, second_meta = validate_paginated(
        api.list_sales(admin_headers(), params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    seen = [row["vin"] for row in first_rows + second_rows]
    assert len(seen) == len(set(seen))
    assert set(seen) == set(vins)


def test_a_case_read_on_an_unused_uuid_answers_the_case_not_found_envelope(api):
    """A syntactically valid UUID that was never minted is a 404, and the error
    payload carries nothing beyond the identifier and the message.

    PRD: "A case identifier in the path resolves to an `ArbitrationCase` — else
    `ERR_CASE_NOT_FOUND`. This guards every read and write route addressed at a
    specific case."

    Design: Corner/entities/case_lookup_on_unknown_uuid_returns_not_found
    """
    response = api.get_case(NON_EXISTENT_UUID, arbitrator_headers())

    error = validate_error(response, ApiErrorId.ERR_CASE_NOT_FOUND.value)
    assert response.status_code == 404
    body = response.json()
    assert body["response_type"] == "error"
    assert set(error.keys()) == {"error_id", "message"}
    assert isinstance(error["message"], str)
    assert error["message"] != ""


def test_recording_a_sale_without_a_vin_is_refused_and_persists_nothing(api):
    """The required input field is simply absent, which is a schema failure, and
    the sale list stays empty afterwards.

    PRD: "The body parses; every required input field is present and non-null;
    every enum-typed value is a declared member of its enum; integer fields hold
    integers; cents-denominated fields are not negative; datetime fields parse as
    ISO 8601 instants — else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/sale_creation_without_vin_returns_invalid_request
    """
    seller = create_seller(api)
    buyer = create_buyer(api)
    payload = sale_payload(seller["id"], buyer["id"])
    del payload["vin"]

    response = api.create_sale(payload, clerk_headers())

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400

    rows, meta = validate_paginated(api.list_sales(admin_headers()))
    assert meta["total_count"] == 0
    assert rows == []


def test_omitting_the_three_optional_temporal_settings_stores_null_null_and_24(api):
    """The unlimited-window shape: two nulls and a 24-hour default, not zeros.

    PRD: "`seller_response_hours` is how long the consignor has to answer once
    intake review is opened; it must be at least 1 and, when omitted, stores 24
    hours."

    Design: Corner/entities/policy_defaults_null_window_null_mileage_and_24_hour_seller_response
    """
    payload = policy_payload(TITLE_BRANDED_POLICY)
    assert "window_hours" not in payload
    assert "mileage_limit" not in payload
    assert "seller_response_hours" not in payload

    policy = validate_success(api.create_policy(payload, admin_headers()), 201)

    assert policy["defect_class"] == "TITLE_BRANDED"
    assert policy["window_hours"] is None
    assert policy["mileage_limit"] is None
    assert policy["seller_response_hours"] == 24
    assert policy["max_allowance_bps"] == 0
    assert policy["psi_extension_hours"] == 0
    assert policy["version"] == 1


def test_client_supplied_computed_fields_on_a_claim_are_discarded(api):
    """The filing body also carries a status, a window verdict, a window length and
    an elapsed-hours figure; all four are replaced by the server's own working.

    PRD: "Nothing else is accepted from the client: the claimant is not supplied
    but derived, and every derived quantity on the new case is computed by the
    server before the row exists."

    Design: Corner/entities/case_window_fields_are_computed_and_client_values_are_input_ignored
    """
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW")

    case = validate_success(
        api.create_case(
            case_payload(
                sale["id"],
                defect_class="MECHANICAL",
                claim_amount_cents=60000,
                odometer_at_claim=84100,
                complaint_text="Transmission slips under load",
                window_eligible=False,
                effective_window_hours=9999,
                hours_elapsed_at_claim=12.5,
                status="UNWOUND",
            ),
            buyer_rep_headers(buyer["id"]),
        ),
        201,
    )

    assert case["status"] == "SUBMITTED"
    assert case["window_eligible"] is True
    assert case["effective_window_hours"] == 48
    assert case["hours_elapsed_at_claim"] == 0.0
    assert case["miles_driven_at_claim"] == 100
    assert case["psi_extension_applied_hours"] == 0
    assert case["policy_version_at_intake"] == 1
    assert case["current_round_index"] == 0
    assert case["fault_party"] == "NONE"
    assert case["claimant_buyer_id"] == buyer["id"]


def test_evidence_system_fields_come_from_the_type_the_headers_and_the_clock(api):
    """A diagnostic scan asserting verified true, an inspector role and a 2020
    timestamp is stored unverified, as a BuyerRep row, at the current clock.

    PRD: "The submitting role has no influence on it — an `Inspector`-filed photo
    set is unverified and a `BuyerRep`-filed inspection report is verified — and
    any value a client supplies for it is ignored."

    Design: Corner/entities/evidence_system_fields_are_server_minted_and_input_ignored
    """
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW")
    case = create_case(
        api,
        sale["id"],
        buyer["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=60000,
        odometer_at_claim=84100,
        complaint_text="Transmission slips under load",
    )

    evidence = validate_success(
        api.create_evidence(
            case["id"],
            evidence_payload(
                evidence_type="DIAGNOSTIC_SCAN",
                provider_name="Blue Ridge Diagnostics",
                document_reference="DS-4410",
                verified=True,
                submitted_by_role="Inspector",
                recorded_at_utc="2020-01-01T00:00:00Z",
            ),
            buyer_rep_headers(buyer["id"]),
        ),
        201,
    )

    assert evidence["verified"] is False
    assert evidence["submitted_by_role"] == "BuyerRep"
    assert evidence["submitted_by_user_id"] == buyer["id"]
    assert_instant_equals(evidence["recorded_at_utc"], CLOCK_DEFAULT, "recorded_at_utc")
    assert evidence["case_version_after"] == 2

    parent = validate_success(api.get_case(case["id"], admin_headers()), 200)
    assert parent["version"] == 2


def test_a_light_channel_outside_the_closed_enum_is_refused(api):
    """AMBER is not one of the three channels the block recognises, so the sale is
    never written.

    PRD: "`light_channel` is one of `GREEN`, `YELLOW` or `RED` and is more than
    descriptive colour: it selects the severity multiplier that discounts any
    repair allowance later awarded on the unit."

    Design: Corner/entities/sale_creation_with_an_unknown_light_channel_is_rejected
    """
    seller = create_seller(api)
    buyer = create_buyer(api)

    response = api.create_sale(
        sale_payload(seller["id"], buyer["id"], light_channel="AMBER"),
        clerk_headers(),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400

    _, meta = validate_paginated(api.list_sales(admin_headers()))
    assert meta["total_count"] == 0


def test_two_identical_evidence_posts_append_two_immutable_rows(api):
    """The same provider and the same document reference posted twice produce two
    distinct rows carrying consecutive parent versions, and neither row exposes a
    version or an updated_at of its own.

    PRD: "Evidence rows are immutable and carry no `updated_at` and no `version` of
    their own; the whole file can be listed in ascending `created_at` order."

    Design: Corner/entities/claim_evidence_rows_are_immutable_and_carry_no_version
    """
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW")
    case = create_case(
        api,
        sale["id"],
        buyer["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=60000,
        odometer_at_claim=84100,
        complaint_text="Transmission slips under load",
    )
    duplicate = evidence_payload(
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=285000,
        provider_name="Statewide Vehicle Inspection",
        document_reference="IR-77120",
    )

    first = validate_success(
        api.create_evidence(case["id"], dict(duplicate), buyer_rep_headers(buyer["id"])),
        201,
    )
    second = validate_success(
        api.create_evidence(case["id"], dict(duplicate), buyer_rep_headers(buyer["id"])),
        201,
    )

    assert first["id"] != second["id"]

    rows, meta = validate_unpaginated(api.list_evidence(case["id"], admin_headers()))
    assert_unpaginated_meta(meta, 2)
    assert_created_at_ascending(rows, "claim evidence")
    assert [row["case_version_after"] for row in rows] == [2, 3]
    for row in rows:
        assert "version" not in row
        assert "updated_at" not in row
        assert row["document_reference"] == "IR-77120"
        assert row["verified"] is True


def test_filing_against_an_unused_sale_id_is_a_sale_not_found_and_moves_no_counter(api):
    """The body-level foreign key is resolved before any policy, window or buyer
    check can run, so nothing is created and the buyer's counters stay at zero.

    PRD: "A `sale_id` supplied in a claim-intake or inspection-purchase body
    resolves to an `AuctionSale` — else `ERR_SALE_NOT_FOUND`."

    Design: Corner/entities/case_creation_against_an_unknown_sale_returns_sale_not_found
    """
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)

    response = api.create_case(
        case_payload(
            NON_EXISTENT_UUID,
            defect_class="MECHANICAL",
            claim_amount_cents=60000,
            odometer_at_claim=84100,
            complaint_text="Transmission slips under load",
        ),
        buyer_rep_headers(buyer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SALE_NOT_FOUND.value)
    assert response.status_code == 404

    _, meta = validate_paginated(api.list_cases(admin_headers()))
    assert meta["total_count"] == 0

    observed = validate_success(api.get_buyer(buyer["id"], admin_headers()), 200)
    assert observed["open_claim_count"] == 0
    assert observed["lifetime_claim_count"] == 0


def test_an_unused_seller_id_in_the_sale_body_is_a_seller_not_found(api):
    """In this flat topology the consignor key is validated in the body, and its
    check fires ahead of the buyer key even though the buyer here is real.

    PRD: "A `seller_id` supplied in a sale-recording body resolves to a `Seller` —
    else `ERR_SELLER_NOT_FOUND`."

    Design: Corner/entities/sale_creation_with_an_unknown_seller_id_returns_seller_not_found
    """
    buyer = create_buyer(api)

    response = api.create_sale(
        sale_payload(NON_EXISTENT_UUID, buyer["id"]), clerk_headers()
    )

    validate_error(response, ApiErrorId.ERR_SELLER_NOT_FOUND.value)
    assert response.status_code == 404

    rows, meta = validate_paginated(api.list_sales(admin_headers()))
    assert meta["total_count"] == 0
    assert rows == []
