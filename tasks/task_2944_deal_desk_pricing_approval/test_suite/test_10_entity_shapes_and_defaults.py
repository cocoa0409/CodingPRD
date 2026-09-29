"""Declared defaults, server-generated fields, listing windows and shape rejections."""
import pytest

from test_helpers import (
    ApiErrorId,
    EPOCH_STAMP,
    UNKNOWN_UUID,
    USER_IDS,
    add_line,
    assert_account,
    assert_account_ledgers,
    assert_approval_tier,
    assert_instant_equals,
    assert_paginated_list,
    assert_quote,
    assert_unset,
    assert_versioned_record,
    create_account,
    create_quote,
    ids_of,
    nonstandard_term_payload,
    quote_line_payload,
    quote_payload,
    read_account,
    read_quote,
    validate_error,
    validate_success,
)


def test_a_new_quote_takes_the_declared_defaults_and_pins_the_active_policy(
    api, base, rep_headers
):
    """PRD §3.2: "Two further inputs are optional: `payment_terms_days`, between 1 and 180
    inclusive, which defaults to 30 when omitted; and `billing_frequency`, one of `ANNUAL`,
    `SEMI_ANNUAL`, `QUARTERLY` or `MONTHLY`, which defaults to `ANNUAL`."
    PRD §3.2: "The service stamps `owner_rep_user_id` with the acting `X-User-ID`, pins
    `desk_policy_id` to whichever revision currently holds `ACTIVE`, and refuses the whole
    request with `ERR_NO_ACTIVE_DESK_POLICY` when no revision is active."
    PRD §3.2: "Its `expires_at` is set to its `created_at` plus the pinned revision's
    `quote_validity_days` days."

    Design: Corner/entities/quote_creation_applies_declared_defaults_and_pins_the_active_policy
    """
    assert base["policy"]["status"] == "ACTIVE"

    quote = validate_success(
        api.create_quote(
            quote_payload(base["account"]["id"], "Northwind Baseline Quote", 12), rep_headers
        ),
        201,
    )
    assert_quote(quote)
    assert_versioned_record(quote, expected_version=1)

    assert quote["status"] == "DRAFT"
    assert quote["payment_terms_days"] == 30
    assert quote["billing_frequency"] == "ANNUAL"
    assert quote["desk_policy_id"] == base["policy"]["id"]
    assert quote["owner_rep_user_id"] == USER_IDS["rep"]
    assert_instant_equals(quote["created_at"], EPOCH_STAMP, "created_at")
    assert_instant_equals(quote["expires_at"], "2026-08-31T00:00:00.000Z", "expires_at")

    assert quote["list_total_cents"] == 0
    assert quote["final_net_total_cents"] == 0
    assert quote["final_blended_discount_pct"] == pytest.approx(0.0, abs=1e-9)
    assert quote["required_approval_level"] == 0
    assert quote["arrangement_type"] == "SINGLE_ELEMENT"
    assert quote["policy_revalidation_required"] is False
    assert quote["revision_count"] == 0
    assert quote["renegotiation_count"] == 0
    assert_unset(
        quote,
        "pinned_policy_version",
        "renegotiated_from_quote_id",
        "submitted_at",
        "approved_at",
        "booked_at",
    )


def test_a_new_account_is_born_with_empty_ledgers_and_a_clear_credit_posture(
    api, base, analyst_headers, rep_headers
):
    """PRD §3.1: "A new account starts with `credit_status` of `CLEAR`, an unset
    `credit_note`, and both conserved counters — `booked_arr_cents` and
    `exception_allowance_used_cents` — at zero."
    PRD §2.4: "`version` is an integer that starts at 1 when the record is created and
    increases by exactly 1 on every mutation of that record."

    Design: Corner/entities/account_system_and_computed_fields_are_server_generated
    """
    account = validate_success(
        api.create_account(
            {"name": "Cascade Manufacturing", "segment": "MID_MARKET", "region": "EMEA"},
            analyst_headers,
        ),
        201,
    )
    assert_account(account)
    assert_versioned_record(account, expected_version=1)
    assert_instant_equals(account["created_at"], EPOCH_STAMP, "created_at")

    assert account["credit_status"] == "CLEAR"
    assert account["existing_arr_cents"] == 0, "the optional opening balance defaults to zero"
    assert_account_ledgers(account, 0, 0)
    assert_unset(account, "credit_note")

    read_back = read_account(api, account["id"], rep_headers)
    assert read_back["id"] == account["id"]
    assert read_back["credit_status"] == "CLEAR"


def test_the_quote_listing_filter_is_applied_before_the_page_window(
    api, base, rep_headers, other_rep_headers, analyst_headers
):
    """PRD §2.3: "`total_count` is the number of records matching the request's filters
    before the page window is applied, and `has_more` is true exactly when records matching
    the filters remain beyond the current window."

    Design: Corner/entities/quote_listing_filters_by_account_and_honours_limit_and_offset
    """
    northwind = base["account"]["id"]
    cascade = create_account(
        api, analyst_headers, name="Cascade Manufacturing", segment="MID_MARKET", region="EMEA"
    )["id"]

    q1 = create_quote(api, northwind, 12, rep_headers, title="Northwind Quote One")
    q2 = create_quote(api, northwind, 24, rep_headers, title="Northwind Quote Two")
    q3 = create_quote(api, northwind, 36, rep_headers, title="Northwind Quote Three")
    q4 = create_quote(api, cascade, 12, other_rep_headers, title="Cascade Quote One")

    page1, _ = assert_paginated_list(
        api.list_quotes(analyst_headers, params={"account_id": northwind, "limit": 2, "offset": 0}),
        expected_total=3, expected_page_size=2, expected_limit=2, expected_offset=0,
        expected_has_more=True,
    )
    page2, _ = assert_paginated_list(
        api.list_quotes(analyst_headers, params={"account_id": northwind, "limit": 2, "offset": 2}),
        expected_total=3, expected_page_size=1, expected_limit=2, expected_offset=2,
        expected_has_more=False,
    )
    assert set(ids_of(page1) + ids_of(page2)) == {q1["id"], q2["id"], q3["id"]}

    other, _ = assert_paginated_list(
        api.list_quotes(analyst_headers, params={"account_id": cascade}),
        expected_total=1, expected_page_size=1, expected_has_more=False,
    )
    assert other[0]["id"] == q4["id"]


def test_reading_a_well_formed_but_unknown_quote_id_answers_quote_not_found(
    api, base, analyst_headers
):
    """PRD §2.11: "Identifiers embedded in a URL are resolved strictly left to right, and the
    first identifier that resolves to nothing decides the response."

    Design: Corner/entities/get_quote_with_unknown_id_returns_quote_not_found
    """
    response = api.get_quote(UNKNOWN_UUID, analyst_headers)
    validate_error(response, ApiErrorId.ERR_QUOTE_NOT_FOUND.value, 404)
    assert response.json().get("data", {}).get("error_id") == "ERR_QUOTE_NOT_FOUND"


def test_a_quote_line_missing_its_quantity_is_a_malformed_request(api, base, rep_headers, analyst_headers):
    """PRD §3.2: "Lines are added one at a time, each naming the `quote_id` it belongs to, the
    `product_id` being sold, a `quantity` between 1 and 1,000,000 inclusive, and an optional
    `requested_discount_pct` — the rep's own ask, at least zero and strictly below one,
    defaulting to zero."
    PRD §2.11: "Checks are evaluated from the top of the list downwards, the first violated
    check decides the response, and no side effect of the request — not a state change, not a
    recomputation, not a ledger move — is applied when any check fails."

    Design: Corner/entities/quote_line_without_quantity_is_invalid_request
    """
    quote = create_quote(api, base["account"]["id"], 12, rep_headers, title="Northwind Shape Check")

    response = api.create_quote_line(
        {"quote_id": quote["id"], "product_id": base["support"]["id"]}, rep_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    assert_paginated_list(
        api.list_quote_lines(quote["id"], analyst_headers), expected_total=0, expected_page_size=0
    )
    after = read_quote(api, quote["id"], rep_headers)
    assert after["list_total_cents"] == 0
    assert after["version"] == 1, "a rejected line write reprices nothing"


def test_an_omitted_requested_discount_defaults_to_zero_on_the_line(api, base, rep_headers):
    """PRD §3.2: "Under the **whole-quantity-average** treatment the entire quantity receives
    the discount of the single band that contains it: the line's
    `effective_stack_discount_pct` is the applicable band's `tier_discount_pct` — zero when no
    band applies — plus `bundle_discount_applied_pct` plus `requested_discount_pct`, with the
    sum capped at the pinned revision's `max_stack_discount_pct` and rounded half up to six
    decimal places, and `provisional_net_cents` is `extended_list_cents` multiplied by one
    minus that stacked discount, multiplied by the term multiplier, and rounded half up once
    to a whole cent."
    PRD §3.2: "`extended_list_cents` is the `quantity` multiplied by the line's snapshotted
    `unit_list_price_cents`, and `extended_cost_cents` is the `quantity` multiplied by the
    snapshotted `unit_cost_cents`."

    Design: Corner/entities/quote_line_requested_discount_defaults_to_zero
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Default Discount", payment_terms_days=30,
    )

    line = validate_success(
        api.create_quote_line(quote_line_payload(quote["id"], base["core"]["id"], 10), rep_headers),
        201,
    )
    assert line["requested_discount_pct"] == pytest.approx(0.0, abs=1e-9)
    assert line["effective_stack_discount_pct"] == pytest.approx(0.0, abs=1e-9)
    assert line["volume_tier_level_applied"] == 1, "ten units sit in the first quantity band"
    assert line["extended_list_cents"] == 1200000
    assert line["provisional_net_cents"] == 1200000
    assert line["final_net_cents"] == 1200000

    rolled = read_quote(api, quote["id"], rep_headers)
    assert rolled["final_net_total_cents"] == 1200000
    assert rolled["final_blended_discount_pct"] == pytest.approx(0.0, abs=1e-9)
    assert rolled["final_margin_pct"] == pytest.approx(0.750000, abs=1e-9)


def test_a_term_category_outside_the_five_declared_members_is_rejected(
    api, base, rep_headers, legal_headers
):
    """PRD §3.4: "The five categories are `PAYMENT_TERMS`, where the number is a count of
    days; `SLA_COMMITMENT`, where it is an uptime percentage; `INDEMNITY_CAP`, where it is a
    multiple of annual contract value; `TERMINATION_FOR_CONVENIENCE`, where it is a notice
    period in months; and `PRICE_HOLD_RENEWAL`, where it is a renewal uplift cap expressed as
    a percentage."
    PRD §2.11: "The body carries every required field for the endpoint, every value matches
    its declared type, every enumerated value is a declared member, every numeric value lies
    inside its declared range, a price-hold window has its `hold_start_date` at or before its
    `hold_end_date`, a delegation window has its `starts_at` strictly before its `ends_at`,
    and no unknown field is present; any violation is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/nonstandard_term_with_undeclared_category_is_invalid_request
    """
    quote = create_quote(api, base["account"]["id"], 12, rep_headers, title="Northwind Enum Check")
    add_line(api, quote["id"], base["support"]["id"], 10, 0.00, rep_headers)

    response = api.create_nonstandard_term(
        nonstandard_term_payload(
            quote["id"], "DATA_RESIDENCY", 1, requested_text="EU-only data residency"
        ),
        rep_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    assert_paginated_list(
        api.list_quote_nonstandard_terms(quote["id"], legal_headers),
        expected_total=0, expected_page_size=0,
    )
    after = read_quote(api, quote["id"], rep_headers)
    assert after["terms_risk_score_aggregate"] == pytest.approx(0.0, abs=1e-9)


def test_a_line_naming_an_unknown_parent_quote_answers_quote_not_found(api, base, rep_headers):
    """PRD §2.11: "Every foreign key supplied in the body resolves — `account_id`,
    `product_id`, `quote_id`, `approval_request_id`, `hold_product_id`, `desk_policy_id`,
    `anchor_product_id` and `attached_product_id` — otherwise `ERR_ACCOUNT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND` or `ERR_DESK_POLICY_NOT_FOUND` (404) as
    appropriate."

    Design: Corner/entities/quote_line_for_unknown_quote_id_is_quote_not_found
    """
    response = api.create_quote_line(
        quote_line_payload(UNKNOWN_UUID, base["support"]["id"], 10, 0.00), rep_headers
    )
    validate_error(response, ApiErrorId.ERR_QUOTE_NOT_FOUND.value, 404)


def test_approval_matrix_rows_are_configuration_only_and_ordered_by_level(
    api, base, analyst_headers
):
    """PRD §2.4: "Three record types are pure configuration rows and are never edited after
    creation: the approval matrix row, the product quantity band and the bundle rule."
    PRD §2.4: "They have no `updated_at` field and no `version` field at all — the keys are
    absent from their representations rather than present and null."

    Design: Corner/entities/approval_tier_rows_are_immutable_config_without_version_fields
    """
    tiers, _ = assert_paginated_list(
        api.list_approval_tiers(base["policy"]["id"], analyst_headers),
        expected_total=4, expected_page_size=4,
    )
    for tier in tiers:
        assert_approval_tier(tier)

    assert [tier["tier_level"] for tier in tiers] == [1, 2, 3, 4]
    assert [tier["required_role"] for tier in tiers] == [
        "DealDeskAnalyst", "SalesDirector", "VPSales", "CFO",
    ]
