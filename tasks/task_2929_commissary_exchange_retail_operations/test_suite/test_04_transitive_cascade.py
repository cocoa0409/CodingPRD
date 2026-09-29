"""Chains where each hop is caused by the hop before it.

Suspending a sponsor reaches an open basket three records away, and tendering a
large visit reaches a parked capital project four hops away.
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
    validate_paginated,
    validate_success,
)


def _scene_sponsor_chain(api):
    """A dependent delegate shopping for a third patron on an open basket."""
    store = fx.create_store(
        api,
        name="Fort Bragg Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-GRO-200",
        name="Toasted Oat Cereal",
        category="GROCERY_STAPLE",
        unit_cost_cents=400,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="F6",
        facings=5,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    sponsor = fx.create_patron(api, full_name="MSG F Lane", id_card_class="ACTIVE_DUTY")
    dependent = fx.create_patron(
        api, full_name="Dana Lane", id_card_class="DEPENDENT", sponsor_patron_id=sponsor["id"]
    )
    other_sponsor = fx.create_patron(api, full_name="SFC G Moss", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_06)
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=other_sponsor["id"],
        delegate_patron_id=dependent["id"],
        valid_from=C.AUG_01,
        valid_to=C.SEP_01,
        per_sale_spend_cap_cents=50000,
        expected_delegate_patron_version=dependent["version"],
    )
    sale = fx.open_sale(
        api, store["id"], other_sponsor["id"], acting_delegation_id=delegation["id"]
    )
    fx.add_line(api, sale["id"], product["id"], 2)
    return {
        "store": store,
        "product": product,
        "sponsor": sponsor,
        "dependent": dependent,
        "other_sponsor": other_sponsor,
        "delegation": delegation,
        "sale": sale,
    }


def test_suspending_a_sponsor_reaches_the_open_basket_three_hops_away(api):
    """Dependent suspended, delegation suspended by sponsor, open sale flagged.

    PRD 3.7: "Hop one: every patron whose `sponsor_patron_id` names this patron and
    whose own `card_status` is `VALID` is itself moved to `SUSPENDED` with
    `suspension_reason` set to `SPONSOR_SUSPENDED` — a sponsor losing their card
    takes their dependents down with them."
    PRD 3.7: "Hop three, caused by hop two: every sale whose `acting_delegation_id`
    names one of those newly suspended delegations and whose `tender_state` is
    `OPEN` has its compliance axis moved `CLEARED → FLAGGED`, which blocks its
    tender until it is cleared."

    Design: Difficulty/transitive_cascade/sponsor_suspension_cascades_three_hops_to_open_sale_flag
    """
    scene = _scene_sponsor_chain(api)

    validate_success(
        api.set_card_status(
            scene["sponsor"]["id"],
            factories.card_status_payload("SUSPEND"),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        200,
    )

    dependent = validate_success(
        api.get_patron(scene["dependent"]["id"], HEADERS_COMPLIANCE_OFFICER)
    )
    assert dependent["card_status"] == "SUSPENDED"
    assert dependent["suspension_reason"] == "SPONSOR_SUSPENDED"

    delegation = validate_success(
        api.get_delegation(scene["delegation"]["id"], HEADERS_COMPLIANCE_OFFICER)
    )
    assert delegation["status"] == "SUSPENDED_BY_SPONSOR"

    sale = validate_success(api.get_sale(scene["sale"]["id"], HEADERS_STORE_CASHIER))
    assert sale["compliance_state"] == "FLAGGED"
    assert sale["tender_state"] == "OPEN"


def test_the_chain_stops_at_the_delegate_and_never_touches_the_grants_sponsor(api):
    """The suspended patron carries ADMIN_ACTION; the grant's own sponsor stays VALID.

    PRD 3.7: "**Suspension** (`VALID → SUSPENDED`, legal only while `card_status`
    is `VALID`) sets `suspension_reason` to `ADMIN_ACTION` and then runs three
    ordered cascade hops."
    PRD 3.7: "Hop two, caused by hop one: every shopper delegation whose
    `delegate_patron_id` names one of those newly suspended dependents and whose
    `status` is `ACTIVE` is moved `ACTIVE → SUSPENDED_BY_SPONSOR`."

    Design: Difficulty/transitive_cascade/sponsor_suspension_cascades_three_hops_to_open_sale_flag
    """
    scene = _scene_sponsor_chain(api)

    suspended = validate_success(
        api.set_card_status(
            scene["sponsor"]["id"],
            factories.card_status_payload("SUSPEND"),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        200,
    )
    assert suspended["card_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "ADMIN_ACTION"

    other = validate_success(
        api.get_patron(scene["other_sponsor"]["id"], HEADERS_COMPLIANCE_OFFICER)
    )
    assert other["card_status"] == "VALID"
    assert other["suspension_reason"] is None

    _entries, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0


def _scene_parked_project_and_large_basket(api):
    """A project parked in AWAITING_FUNDS plus an open basket worth 100,000.00."""
    store = fx.create_store(
        api,
        name="Pearl Harbor Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=1000,
    )
    product = fx.create_product(
        api,
        sku="SKU-GRO-1000",
        name="Bulk Coffee Case",
        category="GROCERY_STAPLE",
        unit_cost_cents=100000,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="G7",
        facings=10,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="CPO H Kalani", id_card_class="ACTIVE_DUTY")
    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Walk-in freezer replacement",
                requested_amount_cents=400000,
            ),
            make_fund_controller_headers("sfc-010"),
        ),
        201,
    )
    validate_success(
        api.submit_capital_project(project["id"], None, make_fund_controller_headers("sfc-010")),
        200,
    )
    parked = validate_success(
        api.decide_capital_project(
            project["id"],
            factories.project_decision_payload("APPROVE"),
            make_board_officer_headers("mwr-010"),
        ),
        200,
    )
    fx.set_clock(api, C.AUG_07)
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 100)
    return {
        "store": store,
        "product": product,
        "patron": patron,
        "project": project,
        "parked": parked,
        "sale": sale,
    }


def test_tender_posts_the_collection_and_re_derives_the_posture(api):
    """The collection lands in the ledger and lifts the store out of FROZEN.

    PRD 3.6: "The first hop recomputes the store's `surcharge_fund_balance_cents`
    and `dividend_fund_balance_cents` from the ledger."
    PRD 3.6: "The second hop, caused by the first, re-derives the store's
    `fund_posture` from its available surcharge."

    Design: Difficulty/transitive_cascade/tender_cascades_four_hops_into_awaiting_funds_project_approval
    """
    scene = _scene_parked_project_and_large_basket(api)
    assert scene["parked"]["state"] == "AWAITING_FUNDS"

    sale = validate_success(
        api.tender_sale(scene["sale"]["id"], factories.tender_payload(), HEADERS_STORE_CASHIER),
        200,
    )
    assert sale["merchandise_cents"] == 10000000
    assert sale["surcharge_total_cents"] == 1000000
    assert sale["total_due_cents"] == 11000000

    entries, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 1
    assert entries[0]["entry_type"] == "SURCHARGE_COLLECTION"
    assert entries[0]["amount_cents"] == 1000000
    assert entries[0]["balance_after_cents"] == 1000000

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["surcharge_fund_balance_cents"] == 1000000


def test_tender_auto_approves_the_parked_project_and_books_its_obligation(api):
    """The parked project reaches APPROVED and 440000 is obligated on the store.

    PRD 3.6: "The third hop, caused by the second, is the one worth watching: when
    the freshly derived `fund_posture` is `UNRESTRICTED`, every capital project of
    this store currently in `AWAITING_FUNDS` is walked in `created_at` ascending
    order, and each one whose `obligation_cents` is no greater than the available
    surcharge *at the moment that project is walked* is auto-transitioned to
    `APPROVED`, with its `obligation_cents` added to the store's
    `surcharge_obligated_cents` before the next project is considered."

    Design: Difficulty/transitive_cascade/tender_cascades_four_hops_into_awaiting_funds_project_approval
    """
    scene = _scene_parked_project_and_large_basket(api)

    validate_success(
        api.tender_sale(scene["sale"]["id"], factories.tender_payload(), HEADERS_STORE_CASHIER),
        200,
    )

    project = validate_success(
        api.get_capital_project(scene["project"]["id"], HEADERS_FUND_CONTROLLER)
    )
    assert project["state"] == "APPROVED"
    assert project["contingency_bp"] == 1000
    assert project["contingency_cents"] == 40000
    assert project["obligation_cents"] == 440000

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["surcharge_obligated_cents"] == 440000
    assert store["fund_posture"] == "UNRESTRICTED"
