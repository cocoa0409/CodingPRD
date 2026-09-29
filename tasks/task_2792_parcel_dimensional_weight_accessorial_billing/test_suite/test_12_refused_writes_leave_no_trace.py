"""Rejections, and the emptiness they must leave behind.

A malformed induction is not merely refused; it must leave the tracking number
free, the shipper's five aggregates at zero and the collection it would have
joined empty. These tests probe the three rejection tiers a write passes on its
way in — reference existence at 404, request schema at 400, and the error
envelope that reports both — and then read the database back to prove nothing
partial was written.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_ADMIN_HEADERS,
    CARRIER_OPS_HEADERS,
    ERR_ACCESSORIAL_NOT_FOUND,
    ERR_ADJUSTMENT_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_LINE_NOT_FOUND,
    ERR_SERVICE_LEVEL_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_SHIPPER_NOT_FOUND,
    ERR_SURCHARGE_WINDOW_NOT_FOUND,
    NON_EXISTENT_UUID,
    assert_envelope_meta,
    assert_error_body_shape,
    assert_ledger,
    rate_contract_payload,
    refresh_shipment,
    refresh_shipper_account,
    scan_payload,
    shipment_payload,
    shipper_with_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"

SMALL_PARCEL = {
    "declared_length_in": 12,
    "declared_width_in": 10,
    "declared_height_in": 8,
    "declared_weight_lbs": 6.0,
}


def _acme(api):
    """SH-2001 holding the standard EXPRESS-only activated contract C1."""
    return shipper_with_active_contract(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME, with_ground=False
    )


def _induct(api, shipper, **kwargs):
    """POST one induction payload as the induction desk and return the raw response."""
    return api.create_shipment(
        shipment_payload(
            shipper.shipper_id, shipper.service_level_ids["EXPRESS"], **kwargs
        ),
        CARRIER_OPS_HEADERS,
    )


def _shipments_of(api, shipper_id):
    """Page the shipments of one account, returning rows and meta together."""
    return validate_paginated(
        api.list_shipments(
            BILLING_OPS_HEADERS, {"shipper_id": shipper_id, "limit": 100}
        )
    )


def test_01_an_induction_without_a_declared_weight_never_reaches_the_rating_engine(api):
    """PRD §3.3: "The operator supplies the rated distance `zone` as an integer between 2 and 8 inclusive, the shipper's `residential_declared` flag, and the four shipper-declared measurements `declared_length_in`, `declared_width_in`, `declared_height_in`, and `declared_weight_lbs`."
    PRD §2.10: "**Request schema**: every required field of the endpoint's input is present, every value has its declared type, every enum value is a declared member, every numeric range holds, and every dimension or weight carries at most one decimal place. Failures are `ERR_INVALID_REQUEST` (HTTP 400). On list endpoints the pagination check `ERR_INVALID_PAGINATION` sits in this same tier."
    PRD §3.3: "The owning account's `total_shipment_count` and `unbilled_shipment_count` each increase by 1, and `open_charges_cents` is recomputed."
    PRD §3.1: "Reading an account back returns those five figures computed live, so the account view is always the authoritative ledger snapshot."

    Design: Corner/entities/shipment_induction_without_declared_weight_is_invalid_request
    """
    shipper = _acme(api)

    payload = shipment_payload(
        shipper.shipper_id,
        shipper.service_level_ids["EXPRESS"],
        tracking_number="1Z-R-0001",
        zone=2,
        residential_declared=False,
        **SMALL_PARCEL,
    )
    payload.pop("declared_weight_lbs")
    assert "declared_weight_lbs" not in payload, (
        "the whole point of this probe is a payload with no scale weight in it"
    )

    response = api.create_shipment(payload, CARRIER_OPS_HEADERS)
    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert_error_body_shape(response)

    account = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        account,
        total=0,
        unbilled=0,
        billed=0,
        credit_balance_cents=0,
        open_charges_cents=0,
    )

    rows, meta = _shipments_of(api, shipper.shipper_id)
    assert meta["total_count"] == 0, (
        f"a refused induction persists no shipment row, found {meta['total_count']}"
    )
    assert rows == []


def test_02_three_declared_type_violations_all_read_as_one_invalid_request(api):
    """PRD §3.3: "The operator supplies the rated distance `zone` as an integer between 2 and 8 inclusive, the shipper's `residential_declared` flag, and the four shipper-declared measurements `declared_length_in`, `declared_width_in`, `declared_height_in`, and `declared_weight_lbs`."
    PRD §2.6: "`declared_weight_lbs` and `scanned_weight_lbs` must each be greater than 0, at most 500, and carry at most one decimal place. A value with two or more decimal places is rejected as an invalid request."
    PRD §3.3: "Two optional inputs complete the declaration: `delivery_area_class`, one of `NONE`, `DAS`, or `EXTENDED` and defaulting to `NONE`, classifying how far off the beaten path the destination sits; and `non_conveyable_declared`, defaulting to false, the shipper's own warning that the package cannot ride the automated sort belt."
    PRD §2.10: "**Request schema**: every required field of the endpoint's input is present, every value has its declared type, every enum value is a declared member, every numeric range holds, and every dimension or weight carries at most one decimal place. Failures are `ERR_INVALID_REQUEST` (HTTP 400). On list endpoints the pagination check `ERR_INVALID_PAGINATION` sits in this same tier."

    Design: Corner/entities/shipment_zone_and_decimal_precision_violations_are_invalid_request
    """
    shipper = _acme(api)

    # Zone 9 sits outside the declared 2 through 8 band.
    out_of_range_zone = _induct(
        api,
        shipper,
        tracking_number="1Z-T-0001",
        zone=9,
        residential_declared=False,
        **SMALL_PARCEL,
    )
    validate_error(out_of_range_zone, ERR_INVALID_REQUEST, 400)

    # 6.05 lb carries two decimal places and is refused rather than rounded.
    two_decimal_weight = _induct(
        api,
        shipper,
        tracking_number="1Z-T-0002",
        zone=2,
        residential_declared=False,
        declared_length_in=12,
        declared_width_in=10,
        declared_height_in=8,
        declared_weight_lbs=6.05,
    )
    validate_error(two_decimal_weight, ERR_INVALID_REQUEST, 400)

    # REMOTE is not one of NONE, DAS or EXTENDED.
    undeclared_enum_member = _induct(
        api,
        shipper,
        tracking_number="1Z-T-0003",
        zone=2,
        residential_declared=False,
        delivery_area_class="REMOTE",
        **SMALL_PARCEL,
    )
    validate_error(undeclared_enum_member, ERR_INVALID_REQUEST, 400)

    reported = {
        response.json()["data"]["error_id"]
        for response in (out_of_range_zone, two_decimal_weight, undeclared_enum_member)
    }
    assert reported == {ERR_INVALID_REQUEST}, (
        "all three schema violations collapse into a single identifier, got "
        f"{sorted(reported)}"
    )

    rows, meta = _shipments_of(api, shipper.shipper_id)
    assert meta["total_count"] == 0, (
        "none of the three rejected inductions may persist, found "
        f"{[row['tracking_number'] for row in rows]}"
    )
    account = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(account, total=0, unbilled=0, billed=0)


def test_03_an_unresolvable_parent_is_reported_in_the_order_the_contract_fixes(api):
    """PRD §3.3: "A `shipper_id` that resolves to nothing is `ERR_SHIPPER_NOT_FOUND`, an unknown `service_level_id` is `ERR_SERVICE_LEVEL_NOT_FOUND`, and a suspended account is `ERR_SHIPPER_SUSPENDED`."
    PRD §2.10: "**Existence of every referenced record**, in path order and then body order: `ERR_SHIPPER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_LEVEL_NOT_FOUND`, `ERR_SURCHARGE_WINDOW_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` — each at HTTP 404, in that relative order when a single request touches several."
    PRD §3.2: "Service levels are never mutated, so they carry no `updated_at` and no `version`; a request naming an unknown one fails with `ERR_SERVICE_LEVEL_NOT_FOUND`."
    PRD §3.3: "**Choosing the governing contract.** Before any pricing field is touched, the server resolves exactly which rate contract prices this parcel, and freezes that answer for the life of the shipment."

    Design: Corner/entities/shipment_with_an_unknown_service_level_parent_is_not_found
    """
    shipper = _acme(api)

    # The shipper and its contract both resolve; only the purchased service does not.
    unknown_service = api.create_shipment(
        shipment_payload(
            shipper.shipper_id,
            NON_EXISTENT_UUID,
            tracking_number="1Z-P-0001",
            zone=2,
            residential_declared=False,
            **SMALL_PARCEL,
        ),
        CARRIER_OPS_HEADERS,
    )
    validate_error(unknown_service, ERR_SERVICE_LEVEL_NOT_FOUND, 404)
    assert_error_body_shape(unknown_service)

    # Now the other way round: the service resolves and the owner does not.
    unknown_owner = api.create_shipment(
        shipment_payload(
            NON_EXISTENT_UUID,
            shipper.service_level_ids["EXPRESS"],
            tracking_number="1Z-P-0002",
            zone=2,
            residential_declared=False,
            **SMALL_PARCEL,
        ),
        CARRIER_OPS_HEADERS,
    )
    validate_error(unknown_owner, ERR_SHIPPER_NOT_FOUND, 404)
    assert (
        unknown_service.json()["data"]["error_id"]
        != unknown_owner.json()["data"]["error_id"]
    ), "each unresolved reference must name the entity that failed, not a shared code"

    rows, meta = _shipments_of(api, shipper.shipper_id)
    assert meta["total_count"] == 0, (
        f"neither refused induction may leave a row behind, found {meta['total_count']}"
    )
    assert rows == []


def test_04_an_unknown_shipment_id_leaks_nothing_but_an_error_identifier(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.10: "**Existence of every referenced record**, in path order and then body order: `ERR_SHIPPER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_LEVEL_NOT_FOUND`, `ERR_SURCHARGE_WINDOW_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` — each at HTTP 404, in that relative order when a single request touches several."

    Design: Corner/entities/unknown_shipment_id_returns_the_not_found_error_envelope
    """
    # Nothing is created first: no shipment row exists anywhere in the database.
    response = api.get_shipment(NON_EXISTENT_UUID, BILLING_OPS_HEADERS)
    validate_error(response, ERR_SHIPMENT_NOT_FOUND, 404)
    assert_error_body_shape(response)

    body = response.json()
    assert body["response_type"] == "error", (
        f"a 404 must declare itself an error envelope, got {body['response_type']!r}"
    )
    assert sorted(body["data"].keys()) == ["error_id", "message"], (
        "no partial entity may be leaked beside the error, got "
        f"{sorted(body['data'].keys())}"
    )
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip(), (
        f"the message must be a non-empty explanation, got {body['data']['message']!r}"
    )
    assert sorted(body["meta"].keys()) == ["api_request_id", "api_request_timestamp"], (
        "an error meta block carries exactly the two request fields, got "
        f"{sorted(body['meta'].keys())}"
    )


def test_05_a_failure_and_the_success_beside_it_are_never_confusable(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.3: "A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the limit and offset are applied."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/errors/every_error_body_uses_the_declared_error_envelope
    """
    shipper = _acme(api)
    parcel = validate_success(
        _induct(
            api,
            shipper,
            tracking_number="1Z-V-1001",
            zone=2,
            residential_declared=False,
            **SMALL_PARCEL,
        ),
        201,
    )

    missing = api.get_shipment(NON_EXISTENT_UUID, BILLING_OPS_HEADERS)
    validate_error(missing, ERR_SHIPMENT_NOT_FOUND, 404)
    failure_body = missing.json()
    for leaked in ("tracking_number", "version", "created_at", "id"):
        assert leaked not in failure_body["data"], (
            f"a 404 body must not carry {leaked}, got {sorted(failure_body['data'])}"
        )

    found = api.get_shipment(parcel["id"], BILLING_OPS_HEADERS)
    success_body = found.json()
    assert validate_success(found)["id"] == parcel["id"]
    assert success_body["response_type"] == "object", (
        f"a single resource reads back as an object, got {success_body['response_type']!r}"
    )
    assert "error_id" not in success_body["data"], (
        "a success body must carry no error identifier at all, got "
        f"{sorted(success_body['data'])}"
    )
    assert_envelope_meta(found)

    # 101 is one past the declared maximum, so the page itself is the violation.
    over_max = api.list_shipments(
        BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 101}
    )
    validate_error(over_max, ERR_INVALID_PAGINATION, 400)
    assert_error_body_shape(over_max)

    listed = api.list_shipments(BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id})
    rows, meta = validate_paginated(listed)
    assert listed.json()["response_type"] == "array", (
        f"a collection reads back as an array, got {listed.json()['response_type']!r}"
    )
    assert meta["limit"] == 10, f"the omitted limit defaults to 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"the omitted offset defaults to 0, got {meta['offset']}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [parcel["id"]]


def test_06_nine_unresolvable_identifiers_report_nine_distinct_names(api):
    """PRD §2.10: "**Existence of every referenced record**, in path order and then body order: `ERR_SHIPPER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_LEVEL_NOT_FOUND`, `ERR_SURCHARGE_WINDOW_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` — each at HTTP 404, in that relative order when a single request touches several."
    PRD §3.1: "Reading or activating a contract identifier that resolves to nothing is rejected with `ERR_CONTRACT_NOT_FOUND` (HTTP 404)."
    PRD §3.2: "Arming a window whose `status` is not `SCHEDULED`, or cancelling one that is already `CANCELLED`, is rejected with `ERR_WINDOW_NOT_IN_STATE` (HTTP 409); an unknown window identifier is `ERR_SURCHARGE_WINDOW_NOT_FOUND`."
    PRD §3.1: "Suspending or reading an account identifier that resolves to nothing is rejected with `ERR_SHIPPER_NOT_FOUND` (HTTP 404)."
    PRD §3.5: "Only an `ASSESSED` charge is waivable; a charge already at `WAIVED` or `REVERSED` is rejected with `ERR_ACCESSORIAL_NOT_WAIVABLE` (HTTP 409), and that state check precedes the freeze check. An unknown charge identifier is `ERR_ACCESSORIAL_NOT_FOUND`."
    PRD §3.6: "An unknown invoice is `ERR_INVOICE_NOT_FOUND`; an unknown line is `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §3.8: "An unknown identifier is `ERR_ADJUSTMENT_NOT_FOUND`."
    PRD §3.9: "An unknown dispute is `ERR_DISPUTE_NOT_FOUND`."
    PRD §3.9: "A claim that has already left `FILED` is refused with `ERR_CLAIM_NOT_ADJUDICABLE` (HTTP 409), and an unknown claim is `ERR_CLAIM_NOT_FOUND`."

    Design: Corner/errors/every_unresolvable_reference_has_its_own_not_found_error
    """
    # Nothing is created: every identifier below is unresolvable by construction.
    probes = [
        ("rate contract", api.get_rate_contract(NON_EXISTENT_UUID, CARRIER_ADMIN_HEADERS), ERR_CONTRACT_NOT_FOUND),
        ("service level", api.get_service_level(NON_EXISTENT_UUID, CARRIER_ADMIN_HEADERS), ERR_SERVICE_LEVEL_NOT_FOUND),
        ("surcharge window", api.get_surcharge_window(NON_EXISTENT_UUID, CARRIER_ADMIN_HEADERS), ERR_SURCHARGE_WINDOW_NOT_FOUND),
        ("shipper account", api.get_shipper_account(NON_EXISTENT_UUID, CARRIER_ADMIN_HEADERS), ERR_SHIPPER_NOT_FOUND),
        ("accessorial waiver", api.waive_accessorial(NON_EXISTENT_UUID, BILLING_OPS_HEADERS), ERR_ACCESSORIAL_NOT_FOUND),
        ("invoice line", api.get_invoice_line(NON_EXISTENT_UUID, BILLING_OPS_HEADERS), ERR_INVOICE_LINE_NOT_FOUND),
        ("billing adjustment", api.get_billing_adjustment(NON_EXISTENT_UUID, BILLING_OPS_HEADERS), ERR_ADJUSTMENT_NOT_FOUND),
        ("dispute", api.get_dispute(NON_EXISTENT_UUID, BILLING_OPS_HEADERS), ERR_DISPUTE_NOT_FOUND),
        ("guarantee claim", api.get_guarantee_claim(NON_EXISTENT_UUID, BILLING_OPS_HEADERS), ERR_CLAIM_NOT_FOUND),
    ]

    for label, response, expected in probes:
        validate_error(response, expected, 404)
        assert_error_body_shape(response)
        assert response.json()["data"]["error_id"] == expected, (
            f"the {label} lookup must name its own entity, got "
            f"{response.json()['data']['error_id']}"
        )

    reported = [response.json()["data"]["error_id"] for _, response, _ in probes]
    assert len(set(reported)) == 9, (
        f"all nine identifiers must be pairwise distinct, got {sorted(reported)}"
    )

    # The waiver proves resolution runs ahead of the state guard: 404, not 409.
    _, waiver, _ = probes[4]
    assert waiver.status_code == 404, (
        "an unknown charge is reported as missing rather than as unwaivable, got "
        f"HTTP {waiver.status_code}"
    )


def test_07_five_shapes_of_malformed_input_all_collapse_into_invalid_request(api):
    """PRD §2.10: "**Request schema**: every required field of the endpoint's input is present, every value has its declared type, every enum value is a declared member, every numeric range holds, and every dimension or weight carries at most one decimal place. Failures are `ERR_INVALID_REQUEST` (HTTP 400). On list endpoints the pagination check `ERR_INVALID_PAGINATION` sits in this same tier."
    PRD §2.6: "`declared_weight_lbs` and `scanned_weight_lbs` must each be greater than 0, at most 500, and carry at most one decimal place. A value with two or more decimal places is rejected as an invalid request."
    PRD §3.1: "The `dim_divisor` must be an integer between 100 and 250 inclusive, and `min_charge_cents` must be an integer of at least 0."
    PRD §3.4: "The `scan_source` is either `AUTOMATED_DWS`, meaning the dimension-and-weight belt scanner, or `MANUAL_REWEIGH`, meaning a deliberate human recapture used to settle a dispute."
    PRD §3.3: "All three status axes open at their initial values: `measurement_status` at `PENDING_SCAN`, `movement_status` at `IN_TRANSIT`, and `billing_status` at `UNBILLED`."

    Design: Corner/errors/malformed_field_values_all_collapse_into_invalid_request
    """
    shipper = _acme(api)
    parcel = validate_success(
        _induct(
            api,
            shipper,
            tracking_number="1Z-V-4001",
            zone=2,
            residential_declared=False,
            **SMALL_PARCEL,
        ),
        201,
    )
    parcel_version = parcel["version"]

    missing_field = shipment_payload(
        shipper.shipper_id,
        shipper.service_level_ids["EXPRESS"],
        tracking_number="1Z-V-4002",
        zone=2,
        residential_declared=False,
        **SMALL_PARCEL,
    )
    missing_field.pop("declared_weight_lbs")
    responses = {
        "missing required field": api.create_shipment(missing_field, CARRIER_OPS_HEADERS),
        "two decimal places": _induct(
            api,
            shipper,
            tracking_number="1Z-V-4003",
            zone=2,
            residential_declared=False,
            declared_length_in=12,
            declared_width_in=10,
            declared_height_in=8,
            declared_weight_lbs=6.25,
        ),
        "zone out of range": _induct(
            api,
            shipper,
            tracking_number="1Z-V-4004",
            zone=9,
            residential_declared=False,
            **SMALL_PARCEL,
        ),
        "divisor out of range": api.create_rate_contract(
            rate_contract_payload(
                shipper.shipper_id,
                effective_from="2027-01-01",
                effective_to="2027-12-31",
                dim_divisor=99,
                min_charge_cents=1195,
                rate_table=[
                    {"zone": 2, "min_lbs": 1, "max_lbs": 9999, "cents_per_lb": 380}
                ],
                tier_discount_table=[],
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        "undeclared scan source": api.create_scan(
            parcel["id"],
            scan_payload(
                parcel_version,
                scan_source="LASER_CURTAIN",
                scanned_length_in=12,
                scanned_width_in=10,
                scanned_height_in=8,
                scanned_weight_lbs=6.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
    }

    for label, response in responses.items():
        validate_error(response, ERR_INVALID_REQUEST, 400)
        assert_error_body_shape(response)
        assert response.status_code == 400, f"{label} must be a schema failure"

    _, shipment_meta = _shipments_of(api, shipper.shipper_id)
    assert shipment_meta["total_count"] == 1, (
        "only 1Z-V-4001 may exist, got "
        f"{shipment_meta['total_count']} shipments"
    )

    _, contract_meta = validate_paginated(
        api.list_rate_contracts(
            CARRIER_ADMIN_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 100}
        )
    )
    assert contract_meta["total_count"] == 1, (
        f"the refused draft must not persist, got {contract_meta['total_count']}"
    )

    _, scan_meta = validate_paginated(
        api.list_scans(parcel["id"], CARRIER_OPS_HEADERS, {"limit": 100})
    )
    assert scan_meta["total_count"] == 0, (
        f"the refused capture appended nothing, got {scan_meta['total_count']} scans"
    )

    unchanged = refresh_shipment(api, parcel["id"])
    assert unchanged["version"] == parcel_version, (
        "a rejected scan increments no version, expected "
        f"{parcel_version}, got {unchanged['version']}"
    )
    assert unchanged["measurement_status"] == "PENDING_SCAN", (
        f"the measurement axis has not moved, got {unchanged['measurement_status']}"
    )
