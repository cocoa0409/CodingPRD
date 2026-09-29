"""Opening a brand program and sizing a category gap."""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_freshly_created,
    assert_item_state,
    assert_money_cents,
    assert_page_window,
    assert_shelf_slots,
    assert_status,
)
from test_helpers.constants import (
    GAP_DRAFT,
    ITEM_CONCEPT,
    POSTURE_GREEN,
    PROGRAM_ACTIVE,
    UNKNOWN_UUID_2,
    UNKNOWN_UUID_3,
)
from test_helpers.test_users import DIRECTOR_HEADERS, SOURCING_HEADERS


def test_new_program_opens_active_with_every_ledger_counter_at_zero(api):
    """A brand program opens ACTIVE with all four commitment counters zeroed.

    PRD 3.1: "A new program opens in `ACTIVE` status with `committed_budget_cents`,
    `lifetime_committed_cents`, `lifetime_released_cents` and `active_item_count`
    all initialised to zero."

    Design: Corner/entities/program_create_returns_zeroed_ledger_counters
    """
    response = api.create_program(f.program_payload(), DIRECTOR_HEADERS)
    program = validate_success(response, expected_status=201)

    assert response.json()["response_type"] == "object"
    assert is_valid_uuid(program["id"]), "program id must be a bare UUID"
    assert program["brand_name"] == "Harvest Lane"
    assert program["retailer_name"] == "MidState Grocers"
    assert program["fiscal_year"] == 2026
    assert_money_cents(program["dev_budget_cents"], 5000000, "dev_budget_cents")
    assert_money_cents(program["committed_budget_cents"], 0, "committed_budget_cents")
    assert_money_cents(
        program["lifetime_committed_cents"], 0, "lifetime_committed_cents"
    )
    assert_money_cents(program["lifetime_released_cents"], 0, "lifetime_released_cents")
    assert program["active_item_count"] == 0
    assert_status(program, PROGRAM_ACTIVE, "program")
    assert_freshly_created(program, "program")


def test_program_create_without_a_development_budget_is_rejected(api):
    """dev_budget_cents is required, and its omission creates nothing.

    PRD 2.9: "Well-formedness, evaluated fourth, covers a single rejection code,
    `ERR_INVALID_REQUEST` (HTTP 422), for all of: an unknown field in the body or
    query string, a missing required field, a value of the wrong type, an
    enumerated value outside its declared set, a numeric value violating one of
    the constraints stated in the workflow narratives below, a datetime that is
    not ISO 8601 UTC, and a pagination `limit` or `offset` outside its permitted
    range."

    Design: Corner/entities/program_create_missing_dev_budget_cents_rejected
    """
    response = api.create_program(
        f.program_payload(dev_budget_cents=None), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    rows, meta = validate_paginated(api.list_programs(DIRECTOR_HEADERS))
    assert meta["total_count"] == 0, "the rejected create must not persist a program"
    assert rows == []


def test_new_gap_opens_unscored_with_its_full_slot_quota_open(api, program):
    """A gap opens DRAFT with no score, no tiers and every slot still open.

    PRD 3.1: "A new gap opens in `DRAFT` with `gap_score`, `recommended_tier` and
    `approved_tier` all null, `slots_consumed` at zero, `slots_open` equal to
    `shelf_slots_quota`, and `slots_consumed_lifetime` and
    `slots_released_lifetime` both at zero."

    Design: Corner/entities/gap_create_starts_with_null_score_and_zero_slot_counters
    """
    gap = validate_success(
        api.create_gap(f.gap_payload(program["program_id"]), SOURCING_HEADERS),
        expected_status=201,
    )

    assert_status(gap, GAP_DRAFT, "gap")
    assert gap["gap_score"] is None, "gap_score is null until the gap is analysed"
    assert gap["recommended_tier"] is None
    assert gap["approved_tier"] is None
    assert_shelf_slots(
        gap,
        slots_consumed=0,
        slots_open=2,
        slots_consumed_lifetime=0,
        slots_released_lifetime=0,
        shelf_slots_quota=2,
    )
    assert_freshly_created(gap, "gap")


def test_gap_listing_windows_three_gaps_and_reports_rows_beyond_the_window(
    api, program
):
    """total_count counts matching rows before the window; has_more reports the rest.

    PRD 2.3: "List responses carry `response_type` of `"array"`, and their `meta`
    object carries the four pagination fields `limit`, `offset`, `total_count` and
    `has_more` — where `total_count` is the number of rows matching the filter
    before the window is applied and `has_more` is true exactly when rows remain
    beyond the returned window."

    Design: Corner/entities/category_gaps_list_paginates_with_total_count_and_has_more
    """
    program_id = program["program_id"]
    for factory in (f.gap_payload, f.single_slot_gap_payload):
        validate_success(
            api.create_gap(factory(program_id), SOURCING_HEADERS), expected_status=201
        )
    validate_success(
        api.create_gap(
            f.gap_payload(
                program_id,
                category_code="PRETZELS",
                national_brand_name="Twistco",
                nb_retail_price_cents=300,
                category_annual_sales_cents=90000000,
                pl_share_pct=30.0,
                unit_velocity_per_week=260,
                shelf_slots_quota=1,
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    first_response = api.list_gaps(
        SOURCING_HEADERS, params={"program_id": program_id, "limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2, "the first window returns exactly two rows"
    assert_page_window(first_meta, limit=2, offset=0, total_count=3)
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_gaps(
            SOURCING_HEADERS, params={"program_id": program_id, "limit": 2, "offset": 2}
        )
    )
    assert len(second_rows) == 1, "the second window returns the remaining row"
    assert_page_window(second_meta, limit=2, offset=2, total_count=3)
    assert second_meta["has_more"] is False

    for row in first_rows + second_rows:
        assert row["program_id"] == program_id


def test_item_create_naming_an_unknown_gap_is_a_gap_not_found(api, program):
    """An unresolvable body foreign key is a 404 keyed to that identifier.

    PRD 2.9: "Each identifier has its own not-found code:
    `ERR_PROGRAM_NOT_FOUND` for `program_id`, `ERR_GAP_NOT_FOUND` for `gap_id`,
    `ERR_SUPPLIER_NOT_FOUND` for `supplier_id`, `ERR_PLANT_LINE_NOT_FOUND` for
    `plant_line_id`, `ERR_AUDIT_NOT_FOUND` for `plant_audit_id` or
    `basis_audit_id`, `ERR_ITEM_NOT_FOUND` for `item_id` or
    `replacement_item_id`, `ERR_COST_MODEL_NOT_FOUND` for `cost_model_id` or
    `pinned_cost_model_id`, `ERR_STUDY_NOT_FOUND` for `study_id`,
    `ERR_ARTWORK_ROUND_NOT_FOUND` for `artwork_round_id` or
    `pinned_artwork_round_id`, `ERR_CLAIM_NOT_FOUND` for `label_claim_id`,
    `ERR_SPECIFICATION_NOT_FOUND` for `specification_id`, `ERR_RUN_NOT_FOUND`
    for `production_run_id`, `ERR_COMPLAINT_NOT_FOUND` for `complaint_id`, and
    `ERR_CHANGE_REQUEST_NOT_FOUND` for `cost_change_request_id`."

    Design: Corner/entities/item_create_with_unknown_gap_id_rejected
    """
    response = api.create_item(
        f.item_payload(UNKNOWN_UUID_3, trailing_90d_units=None), SOURCING_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_GAP_NOT_FOUND.value, 404)

    reread = validate_success(api.get_program(program["program_id"], DIRECTOR_HEADERS))
    assert reread["active_item_count"] == 0, "a refused create claims no facing"


def test_cost_model_create_naming_an_unknown_supplier_is_a_supplier_not_found(
    api, concept_item
):
    """Body foreign keys resolve in declaration order, so supplier_id is reached.

    PRD 2.9: "Foreign keys in a request body are resolved after path identifiers,
    in the order the receiving resource declares its fields."

    Design: Corner/entities/cost_model_create_with_unknown_supplier_id_rejected
    """
    response = api.create_cost_model(
        f.cost_model_payload(concept_item["item_id"], UNKNOWN_UUID_2), SOURCING_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_SUPPLIER_NOT_FOUND.value, 404)

    item = validate_success(api.get_item(concept_item["item_id"], SOURCING_HEADERS))
    assert item["supplier_id"] is None, "no award may follow a refused quote"
    assert_item_state(item, ITEM_CONCEPT, POSTURE_GREEN)
