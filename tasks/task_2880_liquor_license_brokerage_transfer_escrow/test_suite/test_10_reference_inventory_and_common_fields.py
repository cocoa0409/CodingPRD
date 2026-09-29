"""Reference-data creation, declared defaults, envelopes and system-owned fields.

The reference layer is where the contract's shape shows: which fields the client
supplies, which the server derives, and what a freshly registered row reports
before any transaction has touched it.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_common_fields,
    assert_county,
    assert_error_payload_shape,
    assert_instant_equals,
    assert_ledger_entry,
    create_buyer,
    create_brokerage,
    create_county,
    create_license,
    create_license_payload,
    create_seller,
    draft_agreement,
    read_agreement,
    read_county,
    read_license,
    read_premises,
    record_landlord_consent,
    register_premises,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    verify_zoning,
)


def test_county_registration_reports_an_empty_quota_position():
    """40 total, 0 counted, 40 available, 0 bps utilised, 0 in escrow.

    PRD: "Registration immediately runs the county quota computation against an
    empty inventory, so a freshly registered county reports
    `quota_licenses_counted` of 0, `quota_available` equal to its
    `quota_licenses_total`, `quota_utilization_bps` of 0 and
    `escrow_committed_count` of 0."

    PRD: "At server startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it must not fall back to real time under any
    circumstance."

    Design: Corner/entities/county_create_returns_all_fields_with_zero_quota_counters
    """
    response = api_client.create_county(
        {
            "county_code": "NAP",
            "name": "Napa",
            "state_code": "CA",
            "quota_licenses_total": 40,
        },
        ADMIN,
    )
    county = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")

    assert_county(county)
    assert county["quota_licenses_total"] == 40
    assert county["quota_licenses_counted"] == 0
    assert county["quota_available"] == 40
    assert county["quota_utilization_bps"] == 0
    assert county["escrow_committed_count"] == 0
    assert county["version"] == 1
    assert_instant_equals(county["created_at"], "2026-08-01T00:00:00Z", "created_at")


def test_county_optional_settings_fall_back_to_the_statutory_defaults():
    """Omitting all seven optional settings yields the statutory values, not nulls.

    PRD: "Seven further settings are optional and fall back to statutory defaults
    when omitted: `permitted_zoning_codes`, the list of zoning designations in
    which a licensed premises may operate without rezoning, defaulting to `C1`,
    `C2` and `MU1`; `distance_min_feet_school` and `distance_min_feet_church`, the
    minimum lawful distances from the nearest school and the nearest place of
    worship, each defaulting to 600 feet; `posting_period_days`, the length of the
    statutory publication window, defaulting to 30 days; `protest_window_days`, the
    number of days after posting begins during which a protest is still accepted,
    also defaulting to 30 days; `transfer_fee_bps`, the county's transfer fee in
    basis points of the purchase price, defaulting to 150; and
    `default_valuation_basis`, which selects the valuation variant applied when a
    broker activates a listing without naming one, defaulting to
    `COMPARABLE_SALES` and drawn from `COMPARABLE_SALES` or `INCOME_MULTIPLE`."

    Design: Corner/entities/county_defaults_applied_when_optional_fields_omitted
    """
    county = validate_success(
        api_client.create_county(
            {
                "county_code": "MRN",
                "name": "Marin",
                "state_code": "CA",
                "quota_licenses_total": 25,
            },
            ADMIN,
        ),
        201,
    )

    assert county["permitted_zoning_codes"] == ["C1", "C2", "MU1"]
    assert "C1" in county["permitted_zoning_codes"]
    assert county["distance_min_feet_school"] == 600
    assert county["distance_min_feet_church"] == 600
    assert county["posting_period_days"] == 30
    assert county["protest_window_days"] == 30
    assert county["transfer_fee_bps"] == 150
    assert county["default_valuation_basis"] == "COMPARABLE_SALES"


def test_agreement_contingency_days_defaults_to_120_days():
    """A 2026-09-01 closing window plus the default 120 days is 2026-12-30.

    PRD: "Optionally the broker sets `contingency_days`, the length of the
    regulator-approval contingency window, which defaults to 120 days and must be
    between 30 and 365 inclusive."

    PRD: "The `contingency_deadline_at` is computed as `closing_window_start`
    advanced by `contingency_days` days, and it is the exclusive end of the
    transfer window this agreement reserves on the license."

    Design: Corner/entities/agreement_contingency_days_default_is_120
    """
    scenario = setup_scenario(stage="listing_active")

    agreement = draft_agreement(
        scenario["listing_id"],
        scenario["buyer_id"],
        scenario["premises_id"],
        scenario["listing"]["version"],
        scenario["brokerage_id"],
        closing_window_start="2026-09-01T00:00:00Z",
    )

    assert agreement["contingency_days"] == 120
    assert_instant_equals(
        agreement["contingency_deadline_at"],
        "2026-12-30T00:00:00Z",
        "contingency_deadline_at",
    )
    assert agreement["agreement_status"] == "DRAFT"
    assert agreement["escrow_status"] == "AWAITING_DEPOSIT"
    assert agreement["escrow_balance_cents"] == 0


def test_license_create_without_a_license_class_is_a_schema_failure():
    """The required enum is missing, so nothing is persisted and no counter moves.

    PRD: "License stock is added to a county's inventory by a `PlatformAdmin`, who
    names the `county_id` whose quota, distance minima and fees will govern the
    license, the `owner_seller_id` of the current licensee of record, a
    `license_number` unique across all licenses, and a `license_class` drawn from
    `CLASS_47_ONSALE_GENERAL`, `CLASS_21_OFFSALE_GENERAL` or
    `CLASS_41_ONSALE_BEER_WINE`."

    PRD: "**Request body well-formed.** On every write endpoint: every required
    field present, every enum value drawn from its declared set, every integer
    inside its declared range, every datetime a valid ISO 8601 UTC instant, every
    date a valid `YYYY-MM-DD` value, and no value of the wrong scalar type (a
    string where an integer is declared, for instance) — `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/license_create_missing_license_class_returns_invalid_request
    """
    county = create_county()
    seller = create_seller()

    refused = api_client.create_license(
        {
            "county_id": county["id"],
            "owner_seller_id": seller["id"],
            "license_number": "NOCLASS-1",
            "annual_gross_receipts_cents": 120000000,
            "last_active_date": "2026-07-01",
        },
        ADMIN,
    )
    error = validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert refused.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"]

    rows, meta = validate_paginated(
        api_client.list_licenses(ADMIN, {"county_id": county["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    unchanged = read_county(county["id"])
    assert unchanged["quota_licenses_counted"] == 0
    assert unchanged["version"] == 1


def test_zoning_verification_rejects_a_permit_status_outside_the_enum():
    """MAYBE is not one of the five declared permit standings.

    PRD: "Two standing fields start pessimistically: `conditional_use_permit_status`
    begins at `REQUIRED_NOT_FILED` — its full enumeration being `NOT_REQUIRED`,
    `REQUIRED_NOT_FILED`, `PENDING`, `GRANTED` and `DENIED` — and
    `landlord_consent_status` begins at `PENDING`, drawn from `NOT_REQUIRED`,
    `PENDING`, `GRANTED` and `REFUSED`."

    PRD: "Because the permit standing starts at `REQUIRED_NOT_FILED`, a lawfully
    sited new premises is computed as `CONDITIONAL` with reason `CUP_OUTSTANDING`
    at the moment of registration, while a too-close one is `UNSUITABLE` with
    `SCHOOL_DISTANCE` or `CHURCH_DISTANCE` immediately — and note that rule 6
    outranks rules 7 and 8, so an outstanding permit masks both an
    undue-concentration flag and a pending landlord consent."

    Design: Corner/entities/premises_zoning_verification_rejects_unknown_enum_value
    """
    scenario = setup_scenario(
        stage="premises", verify_zoning_step=False, landlord_step=False
    )

    refused = api_client.zoning_verification(
        scenario["premises_id"],
        {"conditional_use_permit_status": "MAYBE"},
        scenario["analyst_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    premises = read_premises(scenario["premises_id"])
    assert premises["conditional_use_permit_status"] == "REQUIRED_NOT_FILED"
    assert premises["suitability_status"] == "CONDITIONAL"
    assert premises["suitability_reason_code"] == "CUP_OUTSTANDING"
    assert premises["version"] == 1


def test_unknown_license_id_answers_with_the_license_specific_not_found():
    """404 in the standard error envelope, carrying error_id and message only.

    PRD: "The resource-specific not-found codes are `ERR_COUNTY_NOT_FOUND`,
    `ERR_SELLER_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND` and
    `ERR_FILING_NOT_FOUND`, each carrying HTTP 404."

    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/entities/license_get_with_unknown_id_returns_license_not_found
    """
    refused = api_client.get_license(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(refused, ApiErrorId.ERR_LICENSE_NOT_FOUND.value, 404)

    body = refused.json()
    assert body["response_type"] == "error"
    assert_error_payload_shape(error)
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_license_create_reports_the_unresolvable_county_not_the_valid_seller():
    """The body FK that resolves to nothing is the one named in the error.

    PRD: "Body foreign keys are resolved after all path identifiers, in the order
    in which the endpoint declares its input fields, and again the first
    unresolvable one is reported."

    PRD: "**Body foreign keys exist**, in declared input order, on every write
    endpoint carrying foreign keys — the matching 404 code above."

    Design: Corner/entities/license_create_with_unknown_county_returns_county_not_found
    """
    seller = create_seller()

    refused = api_client.create_license(
        create_license_payload(
            NON_EXISTENT_UUID, seller["id"], license_number="ORPHAN-1"
        ),
        ADMIN,
    )
    error = validate_error(refused, ApiErrorId.ERR_COUNTY_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_SELLER_NOT_FOUND.value

    _, meta = validate_paginated(api_client.list_licenses(ADMIN))
    assert meta["total_count"] == 0


def test_license_list_pages_in_created_at_order_with_a_filtered_total():
    """Two rows then one, total_count 3 either way, has_more only on the first page.

    PRD: "`limit` sets the maximum number of records returned; when the caller
    omits it, it defaults to 10, and a supplied value must be at least 1 and at
    most 100."

    PRD: "Unless a specific endpoint states otherwise, list results are ordered by
    `created_at` ascending."

    PRD: "`total_count` reflects the number of records matching the caller's
    filters before the page window is applied, and `has_more` is true whenever
    records matching those filters remain beyond the current window."

    Design: Corner/entities/licenses_list_paginates_with_total_count_and_has_more
    """
    county = create_county()
    seller = create_seller()
    for number in ("PAGE-1", "PAGE-2", "PAGE-3"):
        create_license(
            county["id"], seller["id"],
            license_number=number,
            license_class="CLASS_21_OFFSALE_GENERAL",
            annual_gross_receipts_cents=20000000,
        )

    first, first_meta = validate_paginated(
        api_client.list_licenses(
            ADMIN, {"county_id": county["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert [row["license_number"] for row in first] == ["PAGE-1", "PAGE-2"]

    second, second_meta = validate_paginated(
        api_client.list_licenses(
            ADMIN, {"county_id": county["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second[0]["license_number"] == "PAGE-3"

    counted = read_county(county["id"])
    assert counted["quota_licenses_counted"] == 3
    assert counted["quota_available"] == 97


def test_a_ledger_row_carries_id_and_created_at_but_no_version():
    """The one exception to the common-field quartet, and it is append-only.

    PRD: "The single exception is the escrow ledger row. An `EscrowLedgerEntry` is
    immutable once written: it carries `id` and `created_at` only. It has no
    `updated_at` and no `version`, and there is no endpoint that updates or deletes
    one."

    PRD: "Funding appends one ledger row with `entry_type` of `DEPOSIT`, an
    `amount_cents` equal to the positive deposit amount, a `balance_after_cents`
    equal to that same amount, a `memo` carrying the supplied `deposit_reference`,
    and an `occurred_at` of the current logical instant."

    Design: Corner/entities/escrow_ledger_entry_is_immutable_and_carries_no_version
    """
    scenario = setup_scenario(stage="escrow_held", deposit_by_buyer=True)

    rows, meta = validate_paginated(
        api_client.get_agreement_escrow_ledger(
            scenario["agreement_id"], scenario["escrow_headers"]
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1

    row = rows[0]
    assert row["entry_type"] == "DEPOSIT"
    assert row["amount_cents"] == 2405001
    assert row["balance_after_cents"] == 2405001
    assert "version" not in row
    assert "updated_at" not in row
    assert_ledger_entry(row)
    assert_instant_equals(row["occurred_at"], "2026-08-01T00:00:00Z", "occurred_at")


def test_reading_a_draft_agreement_returns_the_frozen_create_response():
    """Both the client's inputs and the three denormalised ids come back unchanged.

    PRD: "Three foreign keys are denormalised onto the agreement so that later
    steps never have to re-walk the chain: `brokerage_id` is copied from the
    listing, `license_id` is copied from the listing, and `seller_id` is copied
    from the `owner_seller_id` of that license."

    PRD: "The deposit requirement is computed once here and frozen for the life of
    the agreement."

    PRD: "Setting the clock changes only what subsequent reads of \"now\" return; no
    already-stored record is recomputed retroactively, so a window that was open
    when it was written stays written as it was."

    Design: Corner/entities/agreement_read_returns_every_frozen_field_unchanged
    """
    scenario = setup_scenario(stage="agreement_draft")
    created = scenario["agreement"]

    read_back = validate_success(
        api_client.get_purchase_agreement(
            scenario["agreement_id"], scenario["buyer_headers"]
        )
    )

    assert read_back == created
    assert read_back["purchase_price_cents"] == 18500010
    assert read_back["required_deposit_cents"] == 2405001
    assert_instant_equals(
        read_back["contingency_deadline_at"],
        "2026-12-30T00:00:00Z",
        "contingency_deadline_at",
    )
    assert read_back["brokerage_id"] == scenario["brokerage_id"]
    assert read_back["license_id"] == scenario["license_id"]
    assert read_back["seller_id"] == scenario["seller_id"]
    assert read_back["version"] == 1
    assert read_back["agreement_status"] == "DRAFT"
    assert read_back["escrow_status"] == "AWAITING_DEPOSIT"
    assert read_back["escrow_balance_cents"] == 0
    assert read_agreement(scenario["agreement_id"]) == read_back


def test_suitability_and_quota_availability_are_derived_never_supplied():
    """A 500-foot school distance decides the verdict; a corrected survey redecides it.

    PRD: "Suitability is not stored by the client; it is computed from the premises
    row and its county's thresholds alone, with no aggregation over other
    locations, and it is recomputed on registration, on zoning verification and on
    the recording of landlord consent."

    PRD: "1. The school distance is less than the county's
    `distance_min_feet_school` — the verdict is `UNSUITABLE` with reason
    `SCHOOL_DISTANCE`."

    PRD: "9. No rule above matched — `SUITABLE` with reason `NONE`."

    PRD: "`quota_available` is `quota_licenses_total` minus that count, floored at
    zero so it is never negative."

    Design: Corner/entities/computed_fields_are_derived_not_accepted_from_the_client
    """
    county = create_county(quota_licenses_total=8)
    assert county["quota_available"] == 8
    buyer = create_buyer()
    brokerage = create_brokerage()

    premises = register_premises(
        buyer["id"], county["id"], brokerage_id=brokerage["id"],
        address_line="9 School Way",
        distance_to_nearest_school_feet=500,
    )
    assert premises["suitability_status"] == "UNSUITABLE"
    assert premises["suitability_reason_code"] == "SCHOOL_DISTANCE"

    consented = record_landlord_consent(
        premises["id"], "GRANTED", brokerage_id=brokerage["id"]
    )
    assert consented["suitability_status"] == "UNSUITABLE"
    assert consented["suitability_reason_code"] == "SCHOOL_DISTANCE"

    corrected = verify_zoning(
        premises["id"], "NOT_REQUIRED", distance_to_nearest_school_feet=900
    )
    assert corrected["suitability_status"] == "SUITABLE"
    assert corrected["suitability_reason_code"] == "NONE"
    assert corrected["version"] == 3


def test_created_at_is_immutable_while_updated_at_and_version_move():
    """A cascade rewrite of the county's counters moves updated_at to the new instant.

    PRD: "Every resource the API returns carries a server-minted `id`, formatted as
    a UUID with no type prefix of any kind, and a `created_at` timestamp rendered
    as an ISO 8601 UTC instant with exactly three fractional-second digits."

    PRD: "When a computed field is rewritten — a county's quota counters, a
    premises' suitability verdict, a license's safekeeping window, a listing's
    offer counter, an agreement's escrow balance — that is a mutation of the owning
    resource: its `updated_at` is refreshed and its `version` advances by one."

    PRD: "Nothing in this system reads wall-clock time."

    Design: Corner/entities/system_fields_are_generated_by_the_server_on_every_row
    """
    county = create_county()
    assert_common_fields(county, "County")
    assert county["version"] == 1
    assert_instant_equals(county["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant_equals(county["updated_at"], county["created_at"], "updated_at")
    seller = create_seller()

    set_clock("2026-08-20T00:00:00Z")
    license_row = create_license(county["id"], seller["id"])
    assert_instant_equals(
        license_row["created_at"], "2026-08-20T00:00:00Z", "License.created_at"
    )
    assert read_license(license_row["id"])["id"] == license_row["id"]

    recomputed = read_county(county["id"])
    assert recomputed["id"] == county["id"]
    assert recomputed["version"] == 2
    assert_instant_equals(
        recomputed["updated_at"], "2026-08-20T00:00:00Z", "County.updated_at"
    )
    assert_instant_equals(recomputed["created_at"], county["created_at"], "created_at")
