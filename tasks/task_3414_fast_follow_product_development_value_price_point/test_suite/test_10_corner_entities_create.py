"""Entity creation corners: server-minted system fields, required-field and
conditional-required shape checks, fixed price points, optional-field
defaults, and computed fields that ignore client input.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_trend_signal,
    create_concept,
    create_concept_payload,
    create_quote,
    create_selected_trend,
    create_trend_signal_payload,
    is_valid_uuid,
    set_clock,
    setup_sourcing_product,
    transition_concept,
    validate_error,
    validate_paginated,
    validate_success,
)

_SCOUT = TEST_USERS["trend_scout_headers"]


def test_trend_create_ignores_client_supplied_system_fields(api):
    """PRD §2.5: "Every persisted resource carries a server-minted `id` as a
    UUID with no type prefix, plus `created_at` and `updated_at` timestamps
    rendered as ISO 8601 UTC with three fractional digits, and an integer
    `version` that increments by one on every mutation of that resource —
    including mutations caused by cascades."
    PRD §3.1: "A new signal starts in `DISCOVERED`, with `momentum_score` null
    and `evaluated_at` unset."
    PRD §2.4: "Before the clock has been set by any call, it reads exactly
    `2026-09-01T00:00:00Z` and must not fall back to wall-clock time."
    A body carrying id/version/created_at still yields a fresh server UUID at
    version 1, created on the logical clock.

    Design: Corner/entities/trend_signal_create_system_field_input_ignored
    """
    set_clock()
    supplied_id = "00000000-0000-4000-8000-0000000000aa"

    response = api.create_trend_signal(
        create_trend_signal_payload(
            id=supplied_id, version=99, created_at="1999-01-01T00:00:00Z"
        ),
        _SCOUT,
    )

    data = validate_success(response, expected_status=201)
    assert_trend_signal(data)
    assert data["status"] == "DISCOVERED"
    assert data["momentum_score"] is None
    assert data["evaluated_at"] is None
    assert data["version"] == 1
    assert data["id"] != supplied_id
    assert is_valid_uuid(data["id"])
    assert data["created_at"] == "2026-09-01T00:00:00.000Z"
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_concept_create_without_required_name_is_invalid_request(api):
    """PRD §2.8: "Third, request shape: required fields present, types valid,
    enum members valid, conditionally required fields supplied, and review
    outcomes belonging to the requested dimension's outcome set (else
    `ERR_INVALID_REQUEST`)."
    PRD §3.2: "To pitch one, a `TrendScout` supplies the `trend_signal_id` of
    the parent trend, a `name`, a `category`, and a
    `target_price_point_cents`."
    Omitting `name` is a 400 and persists no concept.

    Design: Corner/entities/concept_create_missing_required_name_returns_invalid_request
    """
    trend = create_selected_trend()

    response = api.create_concept(
        create_concept_payload(trend_signal_id=trend["id"], name=None), _SCOUT
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    rows, meta = validate_paginated(
        api.list_concepts(headers=_SCOUT, params={"trend_signal_id": trend["id"]})
    )
    assert meta["total_count"] == 0


def test_trend_create_conditional_field_follows_source(api):
    """PRD §3.1: "a signal whose `source` is `PRESTIGE_LAUNCH` must supply
    `prestige_similarity`, a similarity score between 0 and 1 against the
    prestige reference product, and a signal whose `source` is
    `SOCIAL_PLATFORM` must supply `cross_platform_spread`, a spread score
    between 0 and 1; supplying the wrong one for the source, or omitting the
    required one, is rejected with `ERR_INVALID_REQUEST`."
    PRESTIGE without similarity: 400. SOCIAL without spread: 400. SOCIAL with
    spread (and no similarity): 201 in DISCOVERED.

    Design: Corner/entities/trend_create_conditional_field_invalid_request
    """
    set_clock()

    validate_error(
        api.create_trend_signal(
            create_trend_signal_payload(prestige_similarity=None), _SCOUT
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.create_trend_signal(
            create_trend_signal_payload(
                source="SOCIAL_PLATFORM",
                platform="tiktok",
                category="LIPS",
                prestige_similarity=None,
                cross_platform_spread=None,
            ),
            _SCOUT,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    response = api.create_trend_signal(
        create_trend_signal_payload(
            source="SOCIAL_PLATFORM",
            platform="tiktok",
            category="LIPS",
            mention_velocity_7d=2500,
            engagement_growth_pct=1.0,
            prestige_similarity=None,
            cross_platform_spread=0.9,
        ),
        _SCOUT,
    )
    data = validate_success(response, expected_status=201)
    assert data["status"] == "DISCOVERED"
    rows, meta = validate_paginated(api.list_trend_signals(headers=_SCOUT))
    assert meta["total_count"] == 1


def test_concept_off_price_point_and_bogus_enum_are_rejected(api):
    """PRD §3.2: "The price point is not free: `target_price_point_cents` must
    be one of exactly five values — 300, 600, 1000, 1500, or 2000 cents — and
    any other value is rejected with `ERR_INVALID_PRICE_POINT`."
    PRD §2.8: "Third, request shape: required fields present, types valid,
    enum members valid, conditionally required fields supplied, and review
    outcomes belonging to the requested dimension's outcome set (else
    `ERR_INVALID_REQUEST`)."
    A 700-cent price point is 422; a status of "BOGUS" on PATCH is 400.

    Design: Corner/entities/concept_create_invalid_price_point_and_invalid_enum_rejected
    """
    trend = create_selected_trend()

    validate_error(
        api.create_concept(
            create_concept_payload(
                trend_signal_id=trend["id"], name="Off Price",
                target_price_point_cents=700,
            ),
            _SCOUT,
        ),
        ApiErrorId.ERR_INVALID_PRICE_POINT.value,
    )
    validate_error(
        api.patch_trend_signal(trend["id"], {"status": "BOGUS"}, _SCOUT),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(
        api.list_concepts(headers=_SCOUT, params={"trend_signal_id": trend["id"]})
    )
    assert meta["total_count"] == 0
    rows, meta = validate_paginated(
        api.list_trend_signals(headers=_SCOUT, params={"status": "SELECTED"})
    )
    assert [row["id"] for row in rows] == [trend["id"]]


def test_quote_create_omitting_tooling_fee_defaults_to_zero(api):
    """PRD §3.5: "A quote creation names the `product_id` and the
    `contract_manufacturer_id` ... and carries the commercial terms:
    `unit_cost_cents`, an optional `tooling_fee_cents` defaulting to zero,
    `freight_total_cents` for the whole shipment, ..."
    With the field omitted, the stored value is 0 and the provisional landed
    cost carries no amortization: 200 + 0 + 4 + 20 == 224.

    Design: Corner/entities/quote_create_omitting_tooling_fee_defaults_to_zero
    """
    ctx = setup_sourcing_product()

    quote = create_quote(
        ctx["product"]["id"], ctx["manufacturer"]["id"], tooling_fee_cents=None
    )

    assert quote["tooling_fee_cents"] == 0
    assert quote["landed_provisional_cents"] == 224


def test_concept_select_ignores_supplied_cost_and_computes_target(api):
    """PRD §3.2: "When the scout selects it, the platform derives the
    concept's cost ceiling from its fixed price point and stamps
    `selected_at`."
    PRD §3.2: "The five price points therefore yield cost targets of 84, 168,
    260, 360, and 440 cents respectively."
    A client-supplied `target_unit_cost_cents` at creation is not an input:
    the field stays null until selection computes floor(1000 * 0.26) == 260.

    Design: Corner/entities/concept_select_computes_target_cost_and_input_ignored
    """
    trend = create_selected_trend()

    created = create_concept(
        trend["id"],
        name="Sneaky Cost",
        target_price_point_cents=1000,
        target_unit_cost_cents=1,
    )
    assert created["target_unit_cost_cents"] is None

    selected = transition_concept(created["id"], "SELECTED")
    assert selected["target_unit_cost_cents"] == 260
