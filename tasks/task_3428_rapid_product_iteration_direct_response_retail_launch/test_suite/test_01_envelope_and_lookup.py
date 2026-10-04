"""Response envelope, resource lookup, and pagination claims (PRD §2.2, §2.3,
§2.5, §2.11, §3.1).
"""
import pytest

from test_helpers import (
    ADMIN,
    LEAD,
    NON_EXISTENT_UUID,
    RETAIL,
    SOURCING,
    ApiErrorId,
    api_client,
    assert_category,
    assert_launch_season,
    create_category_payload,
    create_concept_payload,
    create_launch_commitment_payload,
    create_season,
    create_season_payload,
    reset_clock,
    setup_draft_variants,
    setup_engineering_locked_concept,
    setup_season_with_category,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated,
)

MISSING_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_season_create_returns_declared_fields_and_open_posture(api):
    """PRD §3.1: "A new season starts with `posture` `SEASON_OPEN`,
    `review_index` 0, `frozen_at_review_index` and `guarded_since_review_index`
    null, `last_review_at` null, and `penalty_accrual_cents` 0."

    Design: Corner/entities/season_create_returns_declared_fields_and_open_posture
    """
    reset_clock()
    resp = api_client.create_season(create_season_payload("FW26"), ADMIN)
    data = validate_created(resp)
    assert_launch_season(data)
    assert resp.json()["response_type"] == "object"
    assert data["posture"] == "SEASON_OPEN"
    assert data["review_index"] == 0
    assert data["penalty_accrual_cents"] == 0
    assert data["version"] == 1
    assert data["frozen_at_review_index"] is None
    assert data["guarded_since_review_index"] is None
    assert data["last_review_at"] is None


def test_category_get_round_trips_computed_fields(api):
    """PRD §3.1: "the category's `exposure_index` initializes to its
    `crowding_base`, and its `exposure_level` is banded immediately by the
    thresholds of §3.8" and "The category's litigation reserve ledger,
    `active_reserve_cents`, starts at 0."

    Design: Corner/entities/category_get_round_trips_computed_fields
    """
    base = setup_season_with_category()
    data = validate_ok(api_client.get_category(base["category"]["id"], LEAD))
    assert_category(data)
    assert data["crowding_base"] == 6
    assert data["exposure_index"] == 6
    assert data["exposure_level"] == "CLEAR"
    assert data["active_reserve_cents"] == 0


def test_mutation_visible_in_same_response_immediate(api):
    """PRD §3.1: "Patent exposure is live from the moment of creation: the
    category's `exposure_index` initializes to its `crowding_base`, and its
    `exposure_level` is banded immediately by the thresholds of §3.8".

    Design: Corner/consistency_model/mutation_visible_in_same_response_immediate
    """
    reset_clock()
    season = create_season("FW26")
    resp = api_client.create_category(
        create_category_payload(season["id"], "Cordless Vacuums", 6), ADMIN
    )
    data = validate_created(resp)
    assert data["exposure_index"] == 6
    assert data["exposure_level"] == "CLEAR"
    assert data["active_reserve_cents"] == 0
    assert data["version"] == 1


def test_concept_get_unknown_id_returns_typed_not_found(api):
    """PRD §2.11: "An unresolvable identifier is rejected with the
    entity-specific not-found error: `ERR_SEASON_NOT_FOUND`,
    `ERR_CATEGORY_NOT_FOUND`, `ERR_CONCEPT_NOT_FOUND`, ... each with HTTP 404."

    Design: Corner/entities/concept_get_unknown_id_returns_typed_not_found
    """
    reset_clock()
    resp = api_client.get_concept(MISSING_ID, LEAD)
    validate_error(resp, ApiErrorId.ERR_CONCEPT_NOT_FOUND)


def test_error_response_envelope_shape_is_fixed(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" and "The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/error_response_envelope_shape_is_fixed
    """
    reset_clock()
    resp = api_client.get_concept(MISSING_ID, LEAD)
    error_data = validate_error(resp, ApiErrorId.ERR_CONCEPT_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert isinstance(meta.get("api_request_timestamp"), str)


def test_unknown_path_ids_return_entity_typed_not_found(api):
    """PRD §2.11: "An unresolvable identifier is rejected with the
    entity-specific not-found error: `ERR_SEASON_NOT_FOUND`,
    `ERR_CATEGORY_NOT_FOUND`, `ERR_CONCEPT_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`,
    `ERR_PARTNER_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`,
    `ERR_MEDIA_TEST_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_entity_typed_not_found
    """
    reset_clock()
    checks = [
        (api_client.get_season(NON_EXISTENT_UUID, LEAD), ApiErrorId.ERR_SEASON_NOT_FOUND),
        (api_client.get_category(NON_EXISTENT_UUID, LEAD), ApiErrorId.ERR_CATEGORY_NOT_FOUND),
        (api_client.get_partner(NON_EXISTENT_UUID, LEAD), ApiErrorId.ERR_PARTNER_NOT_FOUND),
        (api_client.get_variant(NON_EXISTENT_UUID, LEAD), ApiErrorId.ERR_VARIANT_NOT_FOUND),
        (
            api_client.get_launch_commitment(NON_EXISTENT_UUID, LEAD),
            ApiErrorId.ERR_COMMITMENT_NOT_FOUND,
        ),
    ]
    for resp, expected in checks:
        validate_error(resp, expected)


def test_variants_list_paginates_and_reports_envelope_fields(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return" and "Paginated list responses carry the fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope."

    Design: Corner/entities/variants_list_paginates_and_reports_envelope_fields
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    setup_draft_variants(concept["id"])
    rows, meta = validate_paginated(
        api_client.list_variants(
            LEAD, params={"concept_id": concept["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    rows2, meta2 = validate_paginated(
        api_client.list_variants(
            LEAD, params={"concept_id": concept["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_pagination_defaults_apply_when_params_omitted(api):
    """PRD §2.3: "when omitted it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies how many items to skip and
    defaults to 0."

    Design: Corner/endpoints/pagination_defaults_apply_when_params_omitted
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    setup_draft_variants(concept["id"])
    rows, meta = validate_paginated(
        api_client.list_variants(LEAD, params={"concept_id": concept["id"]})
    )
    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_commitment_with_unknown_agreement_fk_returns_not_found(api):
    """PRD §2.11: "On any request, identifiers appearing in the path resolve
    first, strictly left to right, and foreign keys in the body resolve
    afterward. An unresolvable identifier is rejected with the entity-specific
    not-found error: ... `ERR_AGREEMENT_NOT_FOUND` ..."

    Design: Corner/entities/commitment_with_unknown_agreement_fk_returns_not_found
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    variants = setup_draft_variants(concept["id"], specs=[("CV100-AMZ", "AMAZON")])
    payload = create_launch_commitment_payload(
        NON_EXISTENT_UUID,
        variants[0]["id"],
        1,
        committed_units=10,
        need_by_date="2026-10-15T00:00:00Z",
    )
    resp = api_client.create_launch_commitment(payload, SOURCING)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)
