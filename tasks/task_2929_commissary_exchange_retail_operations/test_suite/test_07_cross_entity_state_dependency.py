"""Requests whose fate is decided by the state of a *different* record.

A faultless open basket cannot be tendered once the grant it was rung under has
been withdrawn, and a faultless approval lands in a different state because the
store's fund is empty.
"""
from test_helpers import (
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    make_board_officer_headers,
    make_fund_controller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _scene_open_basket_under_a_revoked_grant(api):
    """An OPEN priced basket whose acting delegation has just been revoked."""
    store = fx.create_store(
        api,
        name="Fort Drum Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-GRO-L02",
        name="Long Grain Rice 10lb",
        category="GROCERY_STAPLE",
        unit_cost_cents=600,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="L2",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    sponsor = fx.create_patron(api, full_name="SSG M Okafor", id_card_class="ACTIVE_DUTY")
    delegate = fx.create_patron(
        api, full_name="N Okafor", id_card_class="DEPENDENT", sponsor_patron_id=sponsor["id"]
    )
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_01,
        valid_to=C.SEP_01,
        per_sale_spend_cap_cents=50000,
        expected_delegate_patron_version=delegate["version"],
    )
    fx.set_clock(api, C.AUG_11)
    sale = fx.open_sale(api, store["id"], sponsor["id"], acting_delegation_id=delegation["id"])
    fx.add_line(api, sale["id"], product["id"], 2)
    revoked = fx.revoke_delegation(api, delegation["id"], reason="PRIVILEGE_WITHDRAWN")
    return {
        "store": store,
        "product": product,
        "sponsor": sponsor,
        "delegate": delegate,
        "delegation": delegation,
        "revoked": revoked,
        "sale": sale,
    }


def test_tender_is_refused_for_the_grants_status_not_the_baskets_flag(api):
    """The withdrawn grant answers first, so the refusal names the delegation.

    PRD 3.3: "Independently of all of this, a grant may only be *used* as a visit's
    acting delegation while its `status` is `ACTIVE`; using one in any other status
    is refused with `ERR_DELEGATION_NOT_ACTIVE`, and that gate is applied both when
    the visit is opened and again when it is tendered."
    PRD 3.6: "When a visit gets flagged because its sponsor's card was suspended,
    the acting grant is simultaneously suspended by that same cascade, so a tender
    attempt is refused for the grant's status before compliance is even considered."

    Design: Difficulty/cross_entity_state_dependency/sale_tender_blocked_by_revoked_delegation_state
    """
    scene = _scene_open_basket_under_a_revoked_grant(api)
    assert scene["revoked"]["status"] == "REVOKED"

    response = api.tender_sale(scene["sale"]["id"], factories.tender_payload(), HEADERS_STORE_CASHIER)
    error = validate_error(response, "ERR_DELEGATION_NOT_ACTIVE", 409)
    assert error["error_id"] != "ERR_SALE_COMPLIANCE_FLAGGED"

    delegation = validate_success(
        api.get_delegation(scene["delegation"]["id"], HEADERS_COMPLIANCE_OFFICER)
    )
    assert delegation["status"] == "REVOKED"


def test_the_refused_tender_leaves_the_flagged_basket_open_and_the_fund_empty(api):
    """The basket keeps its priced line, gains no settled allowance and posts nothing.

    PRD 3.3: "On success `status` becomes `REVOKED`, `version` is incremented, and
    — exactly as with supersession — every sale still open under that grant has its
    compliance dimension moved `CLEARED → FLAGGED`."
    PRD 3.6: "First, unconditionally, an entry against the `SURCHARGE` fund with
    `entry_type` of `SURCHARGE_COLLECTION` and `amount_cents` equal to the visit's
    `surcharge_total_cents` as a positive amount, with `source_ref_kind` of `SALE`
    and `source_ref_id` naming the visit."

    Design: Difficulty/cross_entity_state_dependency/sale_tender_blocked_by_revoked_delegation_state
    """
    scene = _scene_open_basket_under_a_revoked_grant(api)

    validate_error(
        api.tender_sale(scene["sale"]["id"], factories.tender_payload(), HEADERS_STORE_CASHIER),
        "ERR_DELEGATION_NOT_ACTIVE",
        409,
    )

    sale = validate_success(api.get_sale(scene["sale"]["id"], HEADERS_STORE_CASHIER))
    assert sale["tender_state"] == "OPEN"
    assert sale["settled_allowance_cents"] is None
    assert sale["compliance_state"] == "FLAGGED"
    assert sale["merchandise_cents"] == 1200
    assert sale["surcharge_total_cents"] == 60

    _entries, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["surcharge_fund_balance_cents"] == 0


def _scene_submitted_project_against_an_empty_fund(api):
    """A SUBMITTED project of 330000 at a store whose surcharge fund is untouched."""
    store = fx.create_store(
        api,
        name="Fort Bliss Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Checkout lane refit",
                requested_amount_cents=300000,
            ),
            make_fund_controller_headers("sfc-030"),
        ),
        201,
    )
    submitted = validate_success(
        api.submit_capital_project(project["id"], None, make_fund_controller_headers("sfc-030")),
        200,
    )
    return {"store": store, "project": project, "submitted": submitted}


def test_an_approve_decision_parks_the_project_when_the_store_fund_is_frozen(api):
    """The board's APPROVE is honoured, but the destination state is AWAITING_FUNDS.

    PRD 3.9: "**`SUBMITTED → AWAITING_FUNDS`** is taken on the very same `APPROVE`
    decision when either condition fails: the store's `fund_posture` is anything
    other than `UNRESTRICTED`, or the project's `obligation_cents` exceeds the
    store's available surcharge."
    PRD 3.9: "This is not an error — an approval the fund cannot presently carry
    parks the project rather than refusing it."

    Design: Difficulty/cross_entity_state_dependency/capital_project_approval_parks_awaiting_funds_when_store_posture_frozen
    """
    scene = _scene_submitted_project_against_an_empty_fund(api)
    assert scene["submitted"]["state"] == "SUBMITTED"

    project = validate_success(
        api.decide_capital_project(
            scene["project"]["id"],
            factories.project_decision_payload(
                "APPROVE", note="Board concurs, funding subject to availability"
            ),
            make_board_officer_headers("mwr-030"),
        ),
        200,
    )

    assert project["state"] == "AWAITING_FUNDS"
    assert project["contingency_bp"] == 1000
    assert project["contingency_cents"] == 30000
    assert project["obligation_cents"] == 330000
    assert project["decided_by_user_id"] == "mwr-030"
    assert project["submitted_by_user_id"] == "sfc-030"


def test_the_parked_approval_books_no_obligation_against_the_store(api):
    """No obligation, no ledger movement and the posture stays FROZEN.

    PRD 3.9: "`decided_by_user_id` is written exactly as on the approved branch, but
    **no obligation is booked** and the store's `surcharge_obligated_cents` is left
    untouched."

    Design: Difficulty/cross_entity_state_dependency/capital_project_approval_parks_awaiting_funds_when_store_posture_frozen
    """
    scene = _scene_submitted_project_against_an_empty_fund(api)

    validate_success(
        api.decide_capital_project(
            scene["project"]["id"],
            factories.project_decision_payload(
                "APPROVE", note="Board concurs, funding subject to availability"
            ),
            make_board_officer_headers("mwr-030"),
        ),
        200,
    )

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["surcharge_obligated_cents"] == 0
    assert store["surcharge_fund_balance_cents"] == 0
    assert store["fund_posture"] == "FROZEN"

    _entries, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0
