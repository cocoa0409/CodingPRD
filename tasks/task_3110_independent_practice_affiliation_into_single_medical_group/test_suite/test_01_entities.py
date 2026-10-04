"""Entities: creation defaults, retrieval round-trip, listing pagination,
not-found handling, and required-field / enum / FK-ordering checks."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_collection_batch_payload,
    create_practice_payload,
    create_provider_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_affiliated,
    setup_group_market,
    validate_error,
    validate_paginated,
    validate_success,
)

GA = TEST_USERS["group_admin_headers"]


def test_medical_group_create_applies_defaults_and_returns_common_fields(api):
    """PRD §3.1: "At creation the group also accepts its economic and
    departure-terms parameters, each with a default: `shared_services_tier1_rate`
    (default 0.07), `shared_services_tier1_cap_cents` (default 50000000),
    `shared_services_tier2_rate` (default 0.05), `distribution_hold_threshold_cents`
    (default 5000), `departure_notice_days` (default 180), `non_compete_term_months`
    (default 24), `early_exit_base_penalty_cents` (default 2500000),
    `early_exit_per_month_cents` (default 250000), and
    `insufficient_notice_penalty_cents` (default 500000). A new group starts in
    `FORMING` status."

    Design: Corner/entities/medical_group_create_applies_defaults_and_returns_common_fields
    """
    from test_helpers import set_clock

    set_clock()
    resp = api.create_medical_group({"tin": "76-0001111", "display_name": "Unified Medical Group"}, GA)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "FORMING"
    assert data["version"] == 1
    assert data["shared_services_tier1_rate"] == 0.07
    assert data["shared_services_tier1_cap_cents"] == 50000000
    assert data["shared_services_tier2_rate"] == 0.05
    assert data["distribution_hold_threshold_cents"] == 5000
    assert data["departure_notice_days"] == 180
    assert data["non_compete_term_months"] == 24
    assert data["early_exit_base_penalty_cents"] == 2500000
    assert data["early_exit_per_month_cents"] == 250000
    assert data["insufficient_notice_penalty_cents"] == 500000
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_practice_get_round_trips_stored_fields(api, compliance_officer_headers):
    """PRD §3.2: "The practice is born in `PROSPECT` status. Its `wave_id`
    starts null and is never client-supplied, and its `affiliation_effective_date`,
    `departure_effective_date`, and computed `active_provider_count` are
    system-managed."

    Design: Corner/entities/practice_get_round_trips_stored_fields
    """
    ctx = setup_group_market()
    resp = api.create_practice(
        create_practice_payload(ctx["group"]["id"], ctx["market"]["id"]), GA
    )
    created = validate_success(resp, expected_status=201)

    resp = api.get_practice(created["id"], compliance_officer_headers)
    data = validate_success(resp)
    assert data["legal_name"] == "Oak Cliff Family Medicine"
    assert data["legacy_tin"] == "75-9999999"
    assert data["org_npi"] == "1234567890"
    assert data["status"] == "PROSPECT"
    assert data["wave_id"] is None
    assert data["affiliation_effective_date"] is None
    assert data["departure_effective_date"] is None
    assert data["active_provider_count"] == 0


def test_practices_list_paginates_with_total_count_and_has_more(api, group_financial_controller_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items skipped and defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the response envelope."

    Design: Corner/entities/practices_list_paginates_with_total_count_and_has_more
    """
    ctx = setup_group_market(max_practices=5)
    names = [
        ("Oak Cliff Family Medicine", "75-9999999", "1234567890"),
        ("Bishop Arts Pediatrics", "75-8888888", "2234567891"),
        ("Trinity Internal Medicine", "75-7777777", "3234567892"),
    ]
    for legal_name, legacy_tin, org_npi in names:
        resp = api.create_practice(
            create_practice_payload(
                ctx["group"]["id"], ctx["market"]["id"],
                legal_name=legal_name, legacy_tin=legacy_tin, org_npi=org_npi,
            ),
            GA,
        )
        validate_success(resp, expected_status=201)

    # Fresh database: the three practices created above are the only rows.
    rows, meta = validate_paginated(api.list_practices(
        group_financial_controller_headers, params={"limit": 2, "offset": 0},
    ))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(api.list_practices(
        group_financial_controller_headers, params={"limit": 2, "offset": 2},
    ))
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(api.list_practices(group_financial_controller_headers))
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_practice_get_unknown_id_returns_practice_not_found(api):
    """PRD §2.9: "Fifth, existence: identifiers in the URL path are resolved
    left to right, and then foreign keys in the request body in the order they
    are declared for that endpoint, each failure producing the resource-specific
    not-found error:"
    PRD §2.9: "`ERR_PRACTICE_NOT_FOUND` for a practice,"

    Design: Corner/entities/practice_get_unknown_id_returns_practice_not_found
    """
    from test_helpers import set_clock

    set_clock()
    resp = api.get_practice("00000000-0000-4000-8000-000000000000", GA)
    err = validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_FOUND, expected_status=404)
    assert err["error_id"] == "ERR_PRACTICE_NOT_FOUND"
    assert "message" in err


def test_batch_create_missing_period_returns_invalid_request(api, distribution_accountant_headers):
    """PRD §2.9: "Fourth, request shape: every required input field must be
    present, types must match, enum values must lie in their declared sets,
    amounts must be positive where required, periods must match the `YYYY-MM`
    format, and dates must match ISO `YYYY-MM-DD`; violations are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/batch_create_missing_period_returns_invalid_request
    """
    ctx = setup_affiliated()
    payload = create_collection_batch_payload(
        ctx["practice"]["id"], ctx["contract"]["id"], posted_amount_cents=100000
    )
    del payload["period"]
    resp = api.create_collection_batch(payload, distribution_accountant_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    rows, meta = validate_paginated(api.list_collection_batches(distribution_accountant_headers))
    assert len(rows) == 0


def test_market_create_omitting_weight_defaults_to_one(api):
    """PRD §3.1: "A `Market` is created with its `medical_group_id`, a `name`,
    a two-letter `state_code`, a `max_practices` capacity cap, and an optional
    `market_weight` (default 1.0) that later feeds incentive-allocation
    scoring."

    Design: Corner/entities/market_create_omitting_weight_defaults_to_one
    """
    from test_helpers import create_group, create_market_payload, set_clock

    set_clock()
    group = create_group()
    resp = api.create_market(
        create_market_payload(group["id"]), GA
    )
    data = validate_success(resp, expected_status=201)
    assert data["market_weight"] == 1.0


def test_fee_schedule_rate_uplift_is_computed_and_client_value_ignored(api):
    """PRD §3.5: "The server computes `uplift_pct` as the difference between
    `group_rate_cents` and `legacy_rate_cents`, divided by `legacy_rate_cents`,
    expressed to 4 decimal places with round-half-up. A new rate starts
    `PROPOSED`, and proposing a rate for a contract-and-code pair that already
    has a `PROPOSED` rate supersedes the older one to `SUPERSEDED`."

    Design: Corner/entities/fee_schedule_rate_uplift_is_computed_and_client_value_ignored
    """
    from test_helpers import create_contract, create_group, add_rate

    ctx = setup_group_market()
    contract = create_contract(ctx["group"])
    rate = add_rate(contract, legacy_rate_cents=10000, group_rate_cents=10800)
    assert rate["uplift_pct"] == pytest.approx(0.08, abs=1e-9)
    assert rate["status"] == "PROPOSED"


def test_provider_create_ignores_extra_field_status_and_version(api):
    """PRD §3.4: "A new provider starts `ROSTERED`."
    PRD §2.4: "`version` (integer): a system-managed integer that increments
    by one on every mutation; it anchors optimistic concurrency control."

    Design: Corner/entities/provider_create_ignores_extra_field_status_and_version
    """
    ctx = setup_group_market()
    practice = get_success_data(api.create_practice(
        create_practice_payload(ctx["group"]["id"], ctx["market"]["id"]), GA
    ))
    payload = create_provider_payload(
        practice["id"],
        npi="5556667778",
        full_name="Dr. Cy Rao",
        specialty="Cardiology",
        employment_start_date="2026-04-01",
    )
    payload["status"] = "ACTIVE"
    payload["version"] = 99
    resp = api.create_provider(payload, GA)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ROSTERED"
    assert data["version"] == 1
    assert data["practice_id"] == practice["id"]


def test_provider_create_with_out_of_enum_role_returns_invalid_request(api):
    """PRD §2.9: "Fourth, request shape: every required input field must be
    present, types must match, enum values must lie in their declared sets,
    amounts must be positive where required, periods must match the `YYYY-MM`
    format, and dates must match ISO `YYYY-MM-DD`; violations are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.4: "a `provider_role` of `PHYSICIAN` or `APP`"

    Design: Corner/entities/provider_create_with_out_of_enum_role_returns_invalid_request
    """
    ctx = setup_group_market()
    practice = get_success_data(api.create_practice(
        create_practice_payload(ctx["group"]["id"], ctx["market"]["id"]), GA
    ))
    payload = create_provider_payload(
        practice["id"],
        npi="5556667778",
        full_name="Dr. Cy Rao",
        specialty="Cardiology",
        provider_role="DOCTOR",
        employment_start_date="2026-04-01",
    )
    resp = api.create_provider(payload, GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    rows, meta = validate_paginated(api.list_providers(GA))
    assert len(rows) == 0


def test_batch_create_body_foreign_keys_checked_in_input_order(api, distribution_accountant_headers):
    """PRD §2.9: "Fifth, existence: identifiers in the URL path are resolved
    left to right, and then foreign keys in the request body in the order they
    are declared for that endpoint, each failure producing the resource-specific
    not-found error:"
    PRD §2.9: "`ERR_PRACTICE_NOT_FOUND` for a practice,"
    PRD §2.9: "`ERR_PAYER_CONTRACT_NOT_FOUND` for a payer contract,"

    Design: Corner/entities/batch_create_body_foreign_keys_checked_in_input_order
    """
    ctx = setup_affiliated()
    bogus_a = "00000000-0000-4000-8000-000000000001"
    bogus_b = "00000000-0000-4000-8000-000000000002"

    resp = api.create_collection_batch(
        create_collection_batch_payload(bogus_a, bogus_b, period="2026-09", posted_amount_cents=1000),
        distribution_accountant_headers,
    )
    err = validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_FOUND, expected_status=404)
    assert err["error_id"] != "ERR_PAYER_CONTRACT_NOT_FOUND"

    resp = api.create_collection_batch(
        create_collection_batch_payload(ctx["practice"]["id"], bogus_b, period="2026-09", posted_amount_cents=1000),
        distribution_accountant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PAYER_CONTRACT_NOT_FOUND, expected_status=404)

    rows, meta = validate_paginated(api.list_collection_batches(distribution_accountant_headers))
    assert len(rows) == 0
