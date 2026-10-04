"""Entity read corners: list pagination and filters, single-resource
round-trip of stored and computed fields, the entity-specific not-found
catalogue, and body foreign-key checks in declared input order.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_concept,
    create_concept,
    create_concept_payload,
    create_cost_quote_payload,
    create_product,
    create_selected_concept,
    create_selected_trend,
    create_trend,
    make_manufacturer_rep_headers,
    set_clock,
    transition_concept,
    transition_trend,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_SCOUT = TEST_USERS["trend_scout_headers"]
_PM = TEST_USERS["product_manager_headers"]
_SOURCING = TEST_USERS["sourcing_lead_headers"]


def test_products_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "List endpoints accept two query parameters: `limit`, the
    page size, defaulting to 10 with a minimum of 1 and a maximum of 100; and
    `offset`, the number of records to skip, defaulting to 0. Every list
    response reports `limit`, `offset`, `total_count`, and `has_more` in its
    `meta` object."
    With three products on file: limit=2&offset=0 -> 2 rows, total_count 3,
    has_more true; offset=2 -> 1 row, has_more false; defaults return all 3.

    Design: Corner/entities/products_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    trend = create_selected_trend()
    for name, price in (("Alpha Lash", 1000), ("Beta Brow", 600), ("Gamma Glow", 300)):
        concept = create_selected_concept(
            trend["id"], name=name, target_price_point_cents=price
        )
        create_product(concept["id"], sku_name=name.upper().replace(" ", "-"))

    rows, meta = validate_paginated(
        api.list_products(headers=_PM, params={"limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rows, meta = validate_paginated(
        api.list_products(headers=_PM, params={"limit": 2, "offset": 2})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(api.list_products(headers=_PM))
    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False


def test_concept_get_roundtrips_stored_and_computed_fields(api):
    """PRD §3.2: "When the scout selects it, the platform derives the
    concept's cost ceiling from its fixed price point and stamps
    `selected_at`."
    PRD §3.2: "The five price points therefore yield cost targets of 84, 168,
    260, 360, and 440 cents respectively."
    GET returns the posted fields plus the selection side effects: price point
    1000 -> target_unit_cost_cents 260, selected_at on the logical clock.

    Design: Corner/entities/concept_get_roundtrips_stored_and_computed_fields
    """
    set_clock()
    trend = create_selected_trend()
    concept = create_concept(trend["id"], name="Alpha Lash", target_price_point_cents=1000)
    transition_concept(concept["id"], "SELECTED")

    fetched = validate_success(api.get_concept(concept["id"], _PM))

    assert_concept(fetched)
    assert fetched["name"] == "Alpha Lash"
    assert fetched["category"] == "EYES"
    assert fetched["target_price_point_cents"] == 1000
    assert fetched["status"] == "SELECTED"
    assert fetched["target_unit_cost_cents"] == 260
    assert fetched["selected_at"] == "2026-09-01T00:00:00Z"


def test_cost_quote_get_unknown_id_returns_cost_quote_not_found(api):
    """PRD §2.8: "Fourth, path identifiers resolve, checked left to right
    (else the entity-specific not-found error, such as
    `ERR_PRODUCT_NOT_FOUND` or `ERR_LINE_REVIEW_NOT_FOUND`)."
    A syntactically valid but unallocated quote id yields the quote-specific
    404 inside the fixed error envelope.

    Design: Corner/entities/cost_quote_get_unknown_id_returns_cost_quote_not_found
    """
    set_clock()

    response = api.get_cost_quote(NON_EXISTENT_UUID, headers=_SOURCING)

    error = validate_error(response, ApiErrorId.ERR_COST_QUOTE_NOT_FOUND.value)
    assert isinstance(error["message"], str) and error["message"]
    body = response.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


_UNKNOWN_ID_CASES = [
    ("get_concept", ApiErrorId.ERR_CONCEPT_NOT_FOUND.value),
    ("get_product", ApiErrorId.ERR_PRODUCT_NOT_FOUND.value),
    ("get_manufacturer", ApiErrorId.ERR_MANUFACTURER_NOT_FOUND.value),
    ("get_formula_project", ApiErrorId.ERR_FORMULA_PROJECT_NOT_FOUND.value),
    ("get_compliance_dossier", ApiErrorId.ERR_DOSSIER_NOT_FOUND.value),
    ("get_retail_partner", ApiErrorId.ERR_RETAIL_PARTNER_NOT_FOUND.value),
    ("get_line_review", ApiErrorId.ERR_LINE_REVIEW_NOT_FOUND.value),
    ("get_planogram_slot", ApiErrorId.ERR_PLANOGRAM_SLOT_NOT_FOUND.value),
    ("get_launch_plan", ApiErrorId.ERR_LAUNCH_PLAN_NOT_FOUND.value),
    ("get_discontinuation_review", ApiErrorId.ERR_DISCONTINUATION_REVIEW_NOT_FOUND.value),
]


@pytest.mark.parametrize(
    "getter_name,error_id",
    _UNKNOWN_ID_CASES,
    ids=[case[1] for case in _UNKNOWN_ID_CASES],
)
def test_unknown_ids_return_entity_specific_not_found_per_endpoint(
    api, getter_name, error_id
):
    """PRD §2.8: "Fourth, path identifiers resolve, checked left to right
    (else the entity-specific not-found error, such as
    `ERR_PRODUCT_NOT_FOUND` or `ERR_LINE_REVIEW_NOT_FOUND`)."
    Every single-resource GET maps an unknown id to its own error code — ten
    entity-specific 404s, never a shared generic.

    Design: Corner/entities/unknown_ids_return_entity_specific_not_found_per_endpoint
    """
    set_clock()

    response = getattr(api, getter_name)(NON_EXISTENT_UUID, headers=_ADMIN)

    error = validate_error(response, error_id)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"
    assert error["error_id"] == error_id


def test_body_foreign_keys_are_checked_in_declared_input_order(api):
    """PRD §2.8: "Fifth, body foreign-key identifiers resolve, in the
    endpoint's declared input order (same family of not-found errors)."
    PRD §3.5: "A quote creation names the `product_id` and the
    `contract_manufacturer_id`..."
    A concept pitched at an unknown trend reports ERR_TREND_SIGNAL_NOT_FOUND;
    a quote naming both an unknown product and an unknown manufacturer
    reports ERR_PRODUCT_NOT_FOUND first, because `product_id` is declared
    before `contract_manufacturer_id`.

    Design: Corner/entities/concept_and_quote_body_foreign_keys_checked_in_input_order
    """
    set_clock()
    trend = create_selected_trend()
    concept = create_selected_concept(trend["id"])
    product = create_product(concept["id"])

    validate_error(
        api.create_concept(
            create_concept_payload(
                trend_signal_id="00000000-0000-4000-8000-0000000000f1",
                name="Ghost Concept",
            ),
            _SCOUT,
        ),
        ApiErrorId.ERR_TREND_SIGNAL_NOT_FOUND.value,
    )

    unknown_product = "00000000-0000-4000-8000-0000000000f2"
    unknown_cm = "00000000-0000-4000-8000-0000000000f3"
    response = api.create_cost_quote(
        create_cost_quote_payload(
            product_id=unknown_product,
            contract_manufacturer_id=unknown_cm,
            expected_product_version=product["version"],
        ),
        make_manufacturer_rep_headers(unknown_cm),
    )

    error = validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)
    assert error["error_id"] != ApiErrorId.ERR_MANUFACTURER_NOT_FOUND.value


def test_concept_create_requires_selected_trend(api):
    """PRD §3.2: "Two referential rules guard creation: the parent trend must
    be in `SELECTED` status — pitching against a trend in any other state is
    rejected with `ERR_TREND_NOT_SELECTED` — and the concept's `category` must
    equal the parent trend's category, with a mismatch reported as
    `ERR_INVALID_REQUEST`."
    The trend exists and has even been evaluated (score 70.0), but until
    SELECTED the pitch fails.

    Design: Corner/entities/concept_create_requires_selected_trend
    """
    set_clock()
    trend = create_trend()
    transition_trend(trend["id"], "EVALUATING")

    response = api.create_concept(
        create_concept_payload(trend_signal_id=trend["id"], name="Too Early"), _SCOUT
    )

    validate_error(response, ApiErrorId.ERR_TREND_NOT_SELECTED.value)
    rows, meta = validate_paginated(
        api.list_concepts(headers=_SCOUT, params={"trend_signal_id": trend["id"]})
    )
    assert meta["total_count"] == 0
