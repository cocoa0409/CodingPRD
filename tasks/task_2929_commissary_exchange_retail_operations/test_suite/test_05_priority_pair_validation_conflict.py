"""Requests that violate two rules at once, where only one answer is correct.

A line add that breaches the per-visit quantity limit *and* names an item that is
no longer on the shelf must report the quantity limit; a close-out of a project
that is both in the wrong state *and* over its ceiling must report the state.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    make_fund_controller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _scene_limit_and_retired_assortment(api):
    """A basket at its quantity limit whose governing allocation has been retired."""
    store = fx.create_store(
        api,
        name="Quantico Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-FOR-002",
        name="Infant Formula 24oz",
        category="INFANT_FORMULA",
        unit_cost_cents=350,
        quantity_limit_per_visit=2,
        resale_restricted=False,
    )
    assortment = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="H8",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="LCPL I Vega", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_08)
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 2)
    fx.retire_assortment(api, assortment["id"])
    return {
        "store": store,
        "product": product,
        "assortment": assortment,
        "patron": patron,
        "sale": sale,
    }


def test_quantity_limit_is_reported_before_the_missing_allocation(api):
    """The safety gate answers first, so the refusal names the quantity limit.

    PRD 3.5: "Before anything is priced, four gates run in this order: the visit's
    `tender_state` must still be `OPEN`, or the request is refused with
    `ERR_SALE_NOT_OPEN` (HTTP 409); the patron's `card_status` must still be
    `VALID`; the per-visit quantity limit must not be breached; and the resale
    watch must not forbid the item."
    PRD 3.5: "Only then does the system resolve the governing allocation, refusing
    the line with `ERR_ITEM_NOT_IN_ASSORTMENT` if none covers the visit's
    `business_date`."

    Design: Difficulty/priority_pair_validation_conflict/quantity_limit_safety_outranks_assortment_referential_check
    """
    scene = _scene_limit_and_retired_assortment(api)

    response = api.add_sale_line(
        scene["sale"]["id"],
        factories.sale_line_payload(scene["product"]["id"], 2),
        HEADERS_STORE_CASHIER,
    )
    error = validate_error(response, "ERR_QUANTITY_LIMIT_EXCEEDED", 409)
    assert error["error_id"] != "ERR_ITEM_NOT_IN_ASSORTMENT"


def test_the_refused_line_leaves_the_basket_and_the_retired_allocation_as_they_were(api):
    """The visit keeps its one priced line while the allocation stays RETIRED.

    PRD 3.5: "Three units requested twice against a limit of five therefore
    succeeds and then fails, and the patron leaves with three."

    Design: Difficulty/priority_pair_validation_conflict/quantity_limit_safety_outranks_assortment_referential_check
    """
    scene = _scene_limit_and_retired_assortment(api)

    validate_error(
        api.add_sale_line(
            scene["sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 2),
            HEADERS_STORE_CASHIER,
        ),
        "ERR_QUANTITY_LIMIT_EXCEEDED",
        409,
    )

    sale = validate_success(api.get_sale(scene["sale"]["id"], HEADERS_STORE_CASHIER))
    assert sale["line_count"] == 1
    assert sale["merchandise_cents"] == 700
    assert sale["surcharge_total_cents"] == 35
    assert sale["total_due_cents"] == 735

    assortment = validate_success(
        api.get_assortment(scene["assortment"]["id"], HEADERS_ASSORTMENT_PLANNER)
    )
    assert assortment["status"] == "RETIRED"


def _scene_draft_project_over_its_ceiling(api):
    """A never-submitted project whose obligation is well under the outlay to come."""
    store = fx.create_store(api, name="Rota Exchange", channel="EXCHANGE", region="OVERSEAS")
    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Food court HVAC",
                requested_amount_cents=100000,
            ),
            make_fund_controller_headers("sfc-020"),
        ),
        201,
    )
    return {"store": store, "project": project}


def test_project_state_is_reported_before_the_outlay_ceiling(api):
    """Closing a DRAFT project over its ceiling names the state, not the ceiling.

    PRD 3.9: "The project must be at `state` of `APPROVED`, or the attempt is
    refused with `ERR_PROJECT_NOT_APPROVED` (HTTP 409)."
    PRD 3.9: "The `outlay_cents` must be no greater than the project's
    `obligation_cents`, or the attempt is refused with
    `ERR_OUTLAY_EXCEEDS_OBLIGATION` (HTTP 409) — an outlay exactly equal to the
    obligation passes."

    Design: Difficulty/priority_pair_validation_conflict/project_state_check_outranks_outlay_ceiling_on_close
    """
    scene = _scene_draft_project_over_its_ceiling(api)

    response = api.close_capital_project(
        scene["project"]["id"],
        factories.project_close_payload(200000),
        make_fund_controller_headers("sfc-021"),
    )
    error = validate_error(response, "ERR_PROJECT_NOT_APPROVED", 409)
    assert error["error_id"] != "ERR_OUTLAY_EXCEEDS_OBLIGATION"


def test_the_refused_close_out_writes_nothing_at_all(api):
    """The project stays DRAFT with no outlay recorded and no ledger movement.

    PRD 2.8: "The system therefore evaluates checks in a fixed doctrinal order and
    returns the first failure it finds; later checks are never reached once an
    earlier one has failed."
    PRD 3.9: "A ledger entry is appended against the `SURCHARGE` fund with
    `entry_type` of `CAPITAL_OUTLAY`, `amount_cents` equal to the negative of
    `outlay_cents`, `source_ref_kind` of `CAPITAL_PROJECT` and `source_ref_id`
    naming the project."

    Design: Difficulty/priority_pair_validation_conflict/project_state_check_outranks_outlay_ceiling_on_close
    """
    scene = _scene_draft_project_over_its_ceiling(api)

    validate_error(
        api.close_capital_project(
            scene["project"]["id"],
            factories.project_close_payload(200000),
            make_fund_controller_headers("sfc-021"),
        ),
        "ERR_PROJECT_NOT_APPROVED",
        409,
    )

    project = validate_success(
        api.get_capital_project(scene["project"]["id"], HEADERS_FUND_CONTROLLER)
    )
    assert project["state"] == "DRAFT"
    assert project["obligation_cents"] == 110000
    assert project["outlay_cents"] is None
    assert project.get("closed_by_user_id") is None

    _entries, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0
