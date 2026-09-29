"""Scoring the plant: two windows over identical rows, the neutral constants they
fall back to, and the identity that scopes a supplier's own reads."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_instant_equals,
    assert_item_state,
    assert_scorecard_window,
    assert_supplier_status,
    assert_two_decimal_value,
)
from test_helpers.constants import (
    DEFAULT_CLOCK,
    ITEM_CONCEPT,
    POSTURE_GREEN,
    POSTURE_WATCH,
    SUPPLIER_PROSPECT,
    SUPPLIER_QUALIFIED,
)
from test_helpers.fixtures import (
    add_second_supplier,
    advance_clock,
    build_chain,
    read_item,
    read_scorecard,
    read_supplier,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    QUALITY_HEADERS,
    REGULATORY_HEADERS,
    SOURCING_HEADERS,
    make_supplier_headers,
)


def test_the_same_audit_scores_eighty_nine_rolling_and_the_neutral_eighty_to_date(api):
    """One stored audit, two windows, two audit components and two composites.

    PRD 3.8: "otherwise it is the weighted sum of the pillar scores of the single most
    relevant audit — 0.40 times `food_safety_score`, plus 0.25 times
    `sanitation_score`, plus 0.20 times `traceability_score`, plus 0.15 times
    `capacity_score` — where the audit chosen is the finalized audit with the greatest
    `window_end` inside the window, tie-broken by the greater `created_at`."

    PRD 3.8: "The composite is 0.50 times the audit component plus 0.30 times the
    complaint component plus 0.20 times the delivery component, rounded half up to two
    decimals; every component is itself expressed to two decimals."

    PRD 3.8: "The **period-to-date** window instead spans from the supplier's
    `qualified_at` to now, and because every `QUALIFY` decision re-stamps
    `qualified_at`, this variant is reset by recertification while the rolling window is
    not."

    Design: Difficulty/dual_variant_calc/supplier_scorecard_rolling_vs_period_to_date
    """
    ctx = build_chain(api, upto=9)

    scorecard = read_scorecard(api, ctx["supplier_id"], DIRECTOR_HEADERS)

    assert_two_decimal_value(
        scorecard["rolling_12m_audit_component"], 89.55, "rolling_12m_audit_component"
    )
    assert_two_decimal_value(
        scorecard["rolling_12m_complaint_component"],
        100.00,
        "rolling_12m_complaint_component",
    )
    assert_two_decimal_value(
        scorecard["rolling_12m_delivery_component"],
        100.00,
        "rolling_12m_delivery_component",
    )
    assert_two_decimal_value(
        scorecard["rolling_12m_composite_score"], 94.78, "rolling_12m_composite_score"
    )
    assert_scorecard_window(
        scorecard, "rolling_12m_window_start", "2025-08-01T00:00:00Z"
    )
    assert_two_decimal_value(
        scorecard["period_to_date_audit_component"],
        80.00,
        "period_to_date_audit_component",
    )
    assert_two_decimal_value(
        scorecard["period_to_date_composite_score"],
        90.00,
        "period_to_date_composite_score",
    )
    assert_scorecard_window(scorecard, "period_to_date_window_start", DEFAULT_CLOCK)


def test_the_cached_composite_is_the_rolling_variant_and_not_the_period_to_date_one(
    api,
):
    """Only one of the two figures is ever written to the supplier row.

    PRD 3.8: "The **rolling-twelve-month** window spans the 365 days ending at the
    logical clock's current instant, and it is the variant written to
    `composite_score_cached` — refreshed on plant-audit finalize, on a `QUALIFY`
    decision including the recertification self-loop, and on run completion."

    PRD 3.8: "It therefore keeps counting history that predates the current
    qualification period."

    Design: Difficulty/dual_variant_calc/supplier_scorecard_rolling_vs_period_to_date
    """
    ctx = build_chain(api, upto=9)

    supplier = read_supplier(api, ctx["supplier_id"])
    scorecard = read_scorecard(api, ctx["supplier_id"], DIRECTOR_HEADERS)

    assert_supplier_status(supplier, SUPPLIER_QUALIFIED)
    assert_two_decimal_value(
        supplier["composite_score_cached"], 94.78, "composite_score_cached"
    )
    assert_two_decimal_value(
        supplier["composite_score_cached"],
        scorecard["rolling_12m_composite_score"],
        "composite_score_cached",
    )
    assert round(float(scorecard["period_to_date_composite_score"]), 2) == 90.00, (
        "the period-to-date variant reads 90.00 on the same stored rows"
    )
    assert round(float(supplier["composite_score_cached"]), 2) != round(
        float(scorecard["period_to_date_composite_score"]), 2
    ), "the cached score is the rolling variant, not the period-to-date one"


def test_an_audit_outside_both_windows_falls_back_to_the_neutral_constants(api):
    """Move the clock a year on and both variants read the same neutral 90.00.

    PRD 3.8: "The audit component is 80.00 whenever no finalized plant audit of that
    supplier has a `window_end` inside the window"

    PRD 3.8: "The delivery component is 100.00 whenever no run of that supplier's items
    reached `COMPLETED` with a `completed_at` inside the window"

    PRD 3.8: "The **rolling-twelve-month** window spans the 365 days ending at the
    logical clock's current instant, and it is the variant written to
    `composite_score_cached`"

    Design: Corner/calculations/supplier_scorecard_falls_back_to_neutral_components_outside_both_windows
    """
    ctx = build_chain(api, upto=9)
    advance_clock(api, "2027-09-05T00:00:00Z")

    scorecard = read_scorecard(api, ctx["supplier_id"], SOURCING_HEADERS)

    assert_scorecard_window(
        scorecard, "rolling_12m_window_start", "2026-09-05T00:00:00Z"
    )
    assert_two_decimal_value(
        scorecard["rolling_12m_audit_component"], 80.00, "rolling_12m_audit_component"
    )
    assert_two_decimal_value(
        scorecard["rolling_12m_complaint_component"],
        100.00,
        "rolling_12m_complaint_component",
    )
    assert_two_decimal_value(
        scorecard["rolling_12m_delivery_component"],
        100.00,
        "rolling_12m_delivery_component",
    )
    assert_two_decimal_value(
        scorecard["rolling_12m_composite_score"], 90.00, "rolling_12m_composite_score"
    )
    assert_scorecard_window(scorecard, "period_to_date_window_start", DEFAULT_CLOCK)
    assert_two_decimal_value(
        scorecard["period_to_date_audit_component"],
        80.00,
        "period_to_date_audit_component",
    )
    assert_two_decimal_value(
        scorecard["period_to_date_composite_score"],
        90.00,
        "period_to_date_composite_score",
    )
    assert_two_decimal_value(
        read_supplier(api, ctx["supplier_id"])["composite_score_cached"],
        94.78,
        "composite_score_cached",
    )


def test_a_supplier_user_may_act_only_on_its_own_supplier_records(api):
    """The refusal is scope, not role: the same caller reads its own scorecard.

    PRD 2.1: "Concretely, a `SupplierUser` may submit a cost model only for its own
    `supplier_id`, may open, revise or withdraw a cost change request only where the
    target cost model's `supplier_id` equals `X-User-ID`, and may read a supplier
    scorecard only for its own supplier. Any of those addressed at another supplier's
    records fails with `ERR_SUPPLIER_SCOPE_VIOLATION` (HTTP 403)."

    PRD 2.1: "When `X-User-Role` is `SupplierUser`, by contrast, `X-User-ID` is the
    `id` of the acting `Supplier`; ownership checks on any resource that references a
    supplier compare that resource's supplier foreign key to `X-User-ID`."

    Design: Corner/rbac/supplier_user_is_scoped_to_its_own_supplier_records
    """
    ctx = build_chain(api, upto=10)
    other = add_second_supplier(
        api,
        ctx["program_id"],
        legal_name="Southgate Baking Co",
        gfsi_certificate_expiry="2027-09-30T00:00:00Z",
    )
    other_headers = make_supplier_headers(other["id"])
    assert_supplier_status(other, SUPPLIER_PROSPECT)

    quote = api.create_cost_model(
        f.cost_model_payload(ctx["item_id"], ctx["supplier_id"]), other_headers
    )
    validate_error(quote, ApiErrorId.ERR_SUPPLIER_SCOPE_VIOLATION.value, 403)

    foreign_read = api.get_scorecard(ctx["supplier_id"], other_headers)
    validate_error(foreign_read, ApiErrorId.ERR_SUPPLIER_SCOPE_VIOLATION.value, 403)

    own_read = validate_success(api.get_scorecard(other["id"], other_headers))
    assert own_read["supplier_id"] == other["id"], (
        "a supplier user may read its own scorecard, so the refusals were scope checks"
    )

    _rows, meta = validate_paginated(
        api.list_cost_models(SOURCING_HEADERS, params={"item_id": ctx["item_id"]})
    )
    assert meta["total_count"] == 0, "a scope-refused quote persists no cost model"
    item = read_item(api, ctx["item_id"])
    assert_item_state(item, ITEM_CONCEPT, POSTURE_GREEN)
    assert item["supplier_id"] is None


def test_a_complaint_write_is_already_visible_on_the_item_and_the_supplier(api):
    """One append-only insert fans out to two other rows inside the same request.

    PRD 3.8: "Logging a complaint also refreshes the supplier's
    `weighted_complaint_points`, `probation_item_count` and `composite_score_cached`."

    PRD 3.8: "Otherwise `complaint_ppm_90d` is the weighted point total multiplied by
    1,000,000 and divided by `trailing_90d_units`, rounded half up to two decimals."

    PRD 3.8: "when an item's move into `PROBATION` brings that count to 2 or more while
    the supplier stands at `QUALIFIED`, the supplier transitions `QUALIFIED →
    CONDITIONAL`"

    Design: Corner/consistency_model/complaint_response_already_carries_the_recomputed_item_and_supplier_state
    """
    ctx = build_chain(api, upto=12)
    validate_success(
        api.post_shipment_feed(
            ctx["item_id"], f.shipment_feed_payload(20000), SOURCING_HEADERS
        )
    )

    complaint = validate_success(
        api.create_complaint(
            f.major_complaint_payload(
                ctx["item_id"],
                defect_category="LABEL",
                lot_code="L26-2401",
                narrative="Allergen statement hard to read.",
            ),
            REGULATORY_HEADERS,
        ),
        expected_status=201,
    )
    item = validate_success(api.get_item(ctx["item_id"], QUALITY_HEADERS))
    supplier = validate_success(api.get_supplier(ctx["supplier_id"], QUALITY_HEADERS))

    assert_instant_equals(complaint["received_at"], DEFAULT_CLOCK, "received_at")
    assert_two_decimal_value(item["complaint_ppm_90d"], 100.00, "complaint_ppm_90d")
    assert item["trailing_90d_units"] == 20000
    assert item["quality_posture"] == POSTURE_WATCH, (
        "the recomputation is not deferred to the next feed post"
    )
    assert supplier["weighted_complaint_points"] == 2
    assert supplier["probation_item_count"] == 0, (
        "a WATCH item is not a PROBATION item"
    )
    assert_supplier_status(supplier, SUPPLIER_QUALIFIED)
    assert "version" not in complaint, "a complaint carries no version field"
