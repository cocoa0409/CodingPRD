"""Entity-level breadth: creation shapes, retrieval projections, listing windows,
declared defaults, ignored client input, type constraints, immutability and
foreign-key resolution.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_accuracy_record,
    assert_customer,
    assert_envelope_meta,
    assert_item,
    assert_pagination_meta,
    assert_planning_cycle,
    assert_product_family,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.factories import (
    accuracy_record_payload,
    customer_payload,
    demand_forecast_payload,
    item_payload,
    product_family_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    EXEC,
    LEAD,
    PLANNER,
    SUPPLY,
    create_customer,
    create_cycle,
    create_family,
    create_item,
    create_item_with_defaults,
    post_accuracy_record,
    read_accuracy_summary,
    setup_published_cycle_fixture,
)

UNKNOWN_FAMILY_ID = "00000000-0000-0000-0000-0000000000aa"
UNKNOWN_CUSTOMER_ID = "00000000-0000-0000-0000-0000000000bb"
UNKNOWN_PLAN_ID = "00000000-0000-0000-0000-0000000000ff"


def test_new_family_is_created_without_any_accuracy_history():
    """A family registered into an empty system carries the throughput and ceiling
    it was given, and every accuracy field sits at its unscored initial value —
    the two rolling percentages null rather than zero.

    PRD: "A newly registered family starts with no accuracy history at all: its
    `rolling_wmape_pct` and `rolling_bias_pct` are both null, its `bias_flag` is
    `NONE`, its `accuracy_grade` is `UNGRADED`, and its `scored_record_count` is
    0."

    Design: Corner/entities/create_product_family_returns_201_with_initialized_accuracy_fields
    """
    response = api_client.create_product_family(
        product_family_payload(
            family_code="FAM-BASE",
            name="Base Family",
            accountable_planner_user_id="planner-1",
            units_per_hour=100,
            max_monthly_hours=800,
        ),
        ADMIN,
    )
    body = response.json()
    assert_envelope_meta(body)
    assert body["response_type"] == "object"

    family = validate_success(response, 201)
    assert_product_family(family)
    assert family["family_code"] == "FAM-BASE"
    assert family["accountable_planner_user_id"] == "planner-1"
    assert float(family["units_per_hour"]) == 100
    assert float(family["max_monthly_hours"]) == 800
    assert family["rolling_wmape_pct"] is None
    assert family["rolling_bias_pct"] is None
    assert family["bias_flag"] == "NONE"
    assert family["accuracy_grade"] == "UNGRADED"
    assert family["scored_record_count"] == 0
    assert family["version"] == 1


def test_reading_a_fresh_cycle_shows_the_whole_commitment_as_the_gap():
    """Nothing has been planned yet, so the gross gap is the entire commitment, no
    closure has been booked, and the positive committed revenue alone is enough to
    put the posture at risk.

    PRD: "a freshly opened cycle has `gross_gap_cents` equal to its whole
    `financial_commitment_cents`, `selected_closure_cents` at 0,
    `residual_gap_cents` equal to `gross_gap_cents`, and consequently a `posture`
    of `AT_RISK` whenever the committed revenue is positive."

    Design: Corner/entities/get_planning_cycle_returns_stored_money_and_posture_fields
    """
    cycle = create_cycle(cycle_code="CY-READ", financial_commitment_cents=2000000)

    read = validate_success(api_client.get_planning_cycle(cycle["id"], EXEC), 200)
    assert_planning_cycle(read)
    assert read["status"] == "DEMAND_REVIEW"
    assert read["reopen_count"] == 0
    assert read["published_at"] is None
    assert read["plan_value_cents"] == 0
    assert read["gross_gap_cents"] == 2000000
    assert read["selected_closure_cents"] == 0
    assert read["residual_gap_cents"] == 2000000
    assert read["constrained_plan_count"] == 0
    assert read["posture"] == "AT_RISK"
    assert read["version"] == 1


def test_item_listing_reports_the_prefilter_total_across_two_pages():
    """Three items behind a two-row window: the reported total counts every
    matching row rather than the returned ones, and the more-rows flag flips once
    the second page has drained the set.

    PRD: "`total_count` is the number of rows matching the filters before
    pagination is applied, and `has_more` is true exactly when rows remain beyond
    the returned page."

    Design: Corner/entities/list_items_paginates_with_total_count_and_has_more
    """
    family = create_family()
    create_item(family["id"], sku="SKU-P1")
    create_item(family["id"], sku="SKU-P2")
    create_item(family["id"], sku="SKU-P3")

    first_response = api_client.list_items(
        PLANNER, params={"family_id": family["id"], "limit": 2, "offset": 0}
    )
    body = first_response.json()
    assert body["response_type"] == "array"
    first_rows, first_meta = validate_paginated(first_response)
    assert len(first_rows) == 2
    assert_pagination_meta(first_meta, 2, 0, 3)
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api_client.list_items(
            PLANNER, params={"family_id": family["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_rows) == 1
    assert_pagination_meta(second_meta, 2, 2, 3)
    assert second_meta["has_more"] is False

    first_skus = {row["sku"] for row in first_rows}
    second_skus = {row["sku"] for row in second_rows}
    assert first_skus & second_skus == set()
    assert first_skus | second_skus == {"SKU-P1", "SKU-P2", "SKU-P3"}


def test_unknown_supply_plan_path_id_returns_the_plan_specific_not_found():
    """The single path segment resolves to nothing, so the rejection is the 404
    that belongs to that segment's entity type.

    PRD: "Path identifiers are resolved strictly left to right, and the first
    segment that resolves to nothing determines the rejection"

    Design: Corner/entities/get_supply_plan_with_unknown_uuid_returns_supply_plan_not_found
    """
    response = api_client.get_supply_plan(UNKNOWN_PLAN_ID, SUPPLY)
    body = response.json()
    assert body["response_type"] == "error"

    error = validate_error(
        response, ApiErrorId.ERR_SUPPLY_PLAN_NOT_FOUND.value, 404
    )
    assert error["message"]


def test_item_create_without_a_family_id_is_a_shape_failure_not_a_lookup_failure():
    """The required-field check runs before any identifier is resolved, so the
    omission surfaces as a request-shape rejection.

    PRD: "The body parses; every required field is present; every field has its
    declared type"

    Design: Corner/entities/create_item_missing_family_id_returns_invalid_request
    """
    family = create_family()
    payload = item_payload(family["id"], sku="SKU-NOFAM")
    payload.pop("family_id")

    error = validate_error(
        api_client.create_item(payload, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    assert error["error_id"] != ApiErrorId.ERR_FAMILY_NOT_FOUND.value

    _rows, meta = validate_paginated(api_client.list_items(ADMIN))
    assert meta["total_count"] == 0


def test_item_create_omitting_the_policy_triple_takes_the_declared_defaults():
    """With the optional inputs left out, the server seeds the ramp, the service
    level, the variability and the lead time from their declared defaults, opens
    the item as already selling, and derives a policy pair whose reorder point
    ceilings its cycle-stock term on its own.

    PRD: "`lifecycle_state` may be supplied on the create, and **when it is
    omitted the new item is created as `MATURE`**, not as `PRELAUNCH`."

    Design: Corner/entities/create_item_omitting_policy_fields_applies_declared_defaults
    """
    family = create_family()

    item = create_item_with_defaults(family["id"], sku="SKU-DEFAULTS")
    assert_item(item)
    assert item["npi_ramp_pct"] == 100
    assert float(item["service_level_target_pct"]) == 95.0
    assert float(item["demand_cv"]) == 0.30
    assert item["lead_time_days"] == 30
    assert item["lifecycle_state"] == "MATURE"
    assert item["successor_item_id"] is None
    assert item["runout_end_month"] is None
    assert item["safety_stock_units"] == 495
    assert item["reorder_point_units"] == 1495


def test_forecast_create_derives_the_method_and_the_baseline_over_client_input():
    """The client sends its own method, baseline, consensus and status alongside
    the real inputs; every one of them is disregarded and the server's own
    derivation stands.

    PRD: "Unknown fields in a body are ignored rather than rejected."

    Design: Corner/entities/create_demand_forecast_ignores_client_supplied_computed_fields_input_ignored
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-IGN")

    payload = demand_forecast_payload(
        cycle["id"],
        item["id"],
        customer["id"],
        level_units=1000,
        baseline_units=99999,
        method="CROSTON_FLAT",
        consensus_units=1,
        status="CONSENSUS_LOCKED",
    )
    line = validate_success(api_client.create_demand_forecast(payload, PLANNER), 201)
    assert line["method"] == "HOLT_WINTERS"
    assert line["baseline_units"] == 1000
    assert line["consensus_units"] == 1000
    assert line["status"] == "BASELINE"
    assert line["endorsed_adjustment_count"] == 0


def test_customer_create_ignores_a_client_supplied_identity_and_audit_stamp():
    """A create that tries to dictate its own identifier, version and timestamps
    gets none of them: the server mints the row, opens it at the first version and
    stamps it from the logical clock.

    PRD: "The clock is also what stamps `created_at`, `updated_at` and a cycle's
    `published_at`."

    Design: Corner/entities/create_customer_system_fields_input_ignored
    """
    supplied_id = "11111111-1111-1111-1111-111111111111"
    payload = customer_payload(
        customer_code="CUST-SYS",
        id=supplied_id,
        version=77,
        created_at="1999-01-01T00:00:00Z",
        updated_at="1999-01-01T00:00:00Z",
    )

    customer = validate_success(api_client.create_customer(payload, ADMIN), 201)
    assert_customer(customer)
    assert customer["id"] != supplied_id
    assert customer["version"] == 1
    assert customer["created_at"].startswith(DEFAULT_CLOCK_UTC[:19])
    assert customer["credit_hold"] is False

    validate_error(
        api_client.get_customer(supplied_id, ADMIN),
        ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value,
        404,
    )


def test_customer_create_rejects_an_undeclared_channel_and_a_rank_below_one():
    """An enum value outside its declared set and a rank under the declared floor
    are both request-shape failures, and the rank at the floor is accepted.

    PRD: "every enum value belongs to its declared set; every declared numeric
    range holds"

    Design: Corner/entities/create_customer_with_unknown_channel_enum_returns_invalid_request
    """
    validate_error(
        api_client.create_customer(
            customer_payload(customer_code="CUST-BADCHAN", channel="WHOLESALE"), ADMIN
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_customer(
            customer_payload(customer_code="CUST-BADRANK", priority_rank=0), ADMIN
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    accepted = validate_success(
        api_client.create_customer(
            customer_payload(customer_code="CUST-OK", priority_rank=1), ADMIN
        ),
        201,
    )
    assert accepted["priority_rank"] == 1

    _rows, meta = validate_paginated(api_client.list_customers(ADMIN))
    assert meta["total_count"] == 1


def test_accuracy_record_carries_no_version_and_cannot_be_posted_twice():
    """A posted actual is an audit fact: the row exposes neither a version nor an
    update stamp, and a second post for the same triple is refused rather than
    overwriting the first.

    PRD: "audit fact that nothing may ever rewrite, so an accuracy record carries
    only `id` and `created_at`: it has **no** `updated_at` field and **no**
    `version` field, and no endpoint exists that could modify one once written."

    Design: Corner/entities/accuracy_record_is_immutable_with_no_version_field
    """
    ctx = setup_published_cycle_fixture(cycle_code="CY-IMMUT")
    record = post_accuracy_record(
        ctx["cycle"]["id"], ctx["item"]["id"], ctx["customer"]["id"], 900
    )

    read = validate_success(api_client.get_accuracy_record(record["id"], LEAD), 200)
    assert_accuracy_record(read)
    assert "version" not in read
    assert "updated_at" not in read
    assert read["forecast_units_snapshot"] == 1000
    assert read["actual_units"] == 900
    assert read["signed_error_units"] == 100
    assert read["abs_error_units"] == 100
    assert float(read["ape_pct"]) == 11.11
    assert read["accountable_planner_user_id"] == "planner-1"

    validate_error(
        api_client.create_accuracy_record(
            accuracy_record_payload(
                ctx["cycle"]["id"], ctx["item"]["id"], ctx["customer"]["id"], 1000
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_ACCURACY_RECORD.value,
        409,
    )
    assert (
        validate_success(api_client.get_accuracy_record(record["id"], LEAD), 200)[
            "actual_units"
        ]
        == 900
    )


def test_item_create_citing_an_unknown_family_resolves_to_the_family_not_found():
    """The body's foreign key names no family, and the rejection is the 404 of the
    entity that key names.

    PRD: "A `family_id` that matches no product family yields
    `ERR_FAMILY_NOT_FOUND`"

    Design: Corner/entities/create_item_with_unknown_family_id_returns_family_not_found
    """
    create_family()

    validate_error(
        api_client.create_item(
            item_payload(UNKNOWN_FAMILY_ID, sku="SKU-ORPHAN"), ADMIN
        ),
        ApiErrorId.ERR_FAMILY_NOT_FOUND.value,
        404,
    )

    _rows, meta = validate_paginated(api_client.list_items(ADMIN))
    assert meta["total_count"] == 0


def test_forecast_create_citing_an_unknown_customer_resolves_to_customer_not_found():
    """Every other reference in the body resolves; the one that does not is the
    customer, and its own 404 is what surfaces.

    PRD: "an unknown `customer_id` yields `ERR_CUSTOMER_NOT_FOUND`; an unknown
    `cycle_id` yields `ERR_CYCLE_NOT_FOUND`"

    Design: Corner/entities/create_demand_forecast_with_unknown_customer_id_returns_customer_not_found
    """
    family = create_family()
    item = create_item(family["id"])
    cycle = create_cycle(cycle_code="CY-FK")

    validate_error(
        api_client.create_demand_forecast(
            demand_forecast_payload(cycle["id"], item["id"], UNKNOWN_CUSTOMER_ID),
            PLANNER,
        ),
        ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value,
        404,
    )

    _rows, meta = validate_paginated(
        api_client.list_demand_forecasts(PLANNER, params={"cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 0
