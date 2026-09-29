"""State-machine corners: initial states, single-shot transitions and cascades.

Each test drives one transition or one refused transition and pins both the record's
own resulting state and the neighbouring records the transition is meant to move.
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


def test_a_drafted_project_is_born_in_draft_with_its_obligation_already_computed(api):
    """DRAFT, revision_count 0, three null stamps, and 40000 + 4000 = 44000 reserved by nobody.

    PRD 3.9: "A project is born at `state` of `DRAFT` with `revision_count` at 0 and
    `submitted_by_user_id`, `decided_by_user_id` and `outlay_cents` all null."
    PRD 3.9: "When `requested_amount_cents` is below 500000 cents (5,000.00 US
    dollars), `contingency_bp` is 1000 basis points — ten percent."
    PRD 3.9: "Finally `obligation_cents` is `requested_amount_cents` plus
    `contingency_cents`, and that obligation figure — not the request amount — is what
    gets reserved against the surcharge fund while the project is approved."

    Design: Corner/state_machines/corner_new_capital_project_starts_in_draft_state
    """
    store = fx.create_store(
        api, name="Fort Benning Commissary", channel="COMMISSARY", region="CONUS"
    )

    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Deli case replacement",
                requested_amount_cents=40000,
            ),
            make_fund_controller_headers("sfc-100"),
        ),
        201,
    )

    assert project["state"] == "DRAFT"
    assert project["revision_count"] == 0
    assert project["submitted_by_user_id"] is None
    assert project["decided_by_user_id"] is None
    assert project["outlay_cents"] is None
    assert project["contingency_bp"] == 1000
    assert project["contingency_cents"] == 4000
    assert project["obligation_cents"] == 44000

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_obligated_cents"] == 0


def test_submitting_a_draft_stamps_the_caller_and_leaves_the_revision_tally_alone(api):
    """SUBMITTED with submitted_by_user_id sfc-101, revision_count still 0.

    PRD 3.9: "On success `submitted_by_user_id` is set to the submitting caller's
    `X-User-ID` and `version` is incremented by 1."
    PRD 3.9: "The two source states differ in exactly one respect: `DRAFT →
    SUBMITTED` leaves `revision_count` alone, while `RETURNED_FOR_REVISION →
    SUBMITTED` increments `revision_count` by 1, because that counter tallies only
    re-submissions."
    PRD 3.9: "The request amount is fixed at creation and never changes afterwards."

    Design: Corner/state_machines/corner_submit_draft_project_moves_to_submitted_and_stamps_user
    """
    store = fx.create_store(
        api, name="Fort Bragg Commissary", channel="COMMISSARY", region="CONUS"
    )
    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"], title="Bakery oven", requested_amount_cents=40000
            ),
            make_fund_controller_headers("sfc-101"),
        ),
        201,
    )

    submitted = validate_success(
        api.submit_capital_project(project["id"], None, make_fund_controller_headers("sfc-101")),
        200,
    )

    assert submitted["state"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "sfc-101"
    assert submitted["revision_count"] == 0
    assert submitted["requested_amount_cents"] == 40000
    assert submitted["obligation_cents"] == 44000
    assert submitted["version"] == project["version"] + 1


def test_the_board_cannot_decide_a_project_that_was_never_submitted(api):
    """A DRAFT project answers 409 and keeps decided_by_user_id null.

    PRD 3.9: "The project must be at `state` of `SUBMITTED`; deciding a project in
    any other state is refused with `ERR_PROJECT_NOT_SUBMITTED` (HTTP 409)."
    PRD 3.9: "Every one of the three decisions writes `decided_by_user_id` from the
    deciding caller's `X-User-ID` and increments `version` by 1."

    Design: Corner/state_machines/corner_decision_on_draft_project_returns_project_not_submitted
    """
    store = fx.create_store(
        api, name="Fort Gordon Commissary", channel="COMMISSARY", region="CONUS"
    )
    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"], title="Cart corral", requested_amount_cents=20000
            ),
            make_fund_controller_headers("sfc-102"),
        ),
        201,
    )

    validate_error(
        api.decide_capital_project(
            project["id"],
            factories.project_decision_payload("APPROVE"),
            make_board_officer_headers("mwr-102"),
        ),
        "ERR_PROJECT_NOT_SUBMITTED",
        409,
    )

    read_project = validate_success(
        api.get_capital_project(project["id"], HEADERS_FUND_CONTROLLER)
    )
    assert read_project["state"] == "DRAFT"
    assert read_project["decided_by_user_id"] is None

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_obligated_cents"] == 0


def test_a_second_revoke_of_the_same_grant_is_refused_and_bumps_no_version(api):
    """Revoke is not idempotent: the second call is 409 and the version stands still.

    PRD 3.3: "It is legal only from `status` of `ACTIVE` or `SUSPENDED_BY_SPONSOR`; a
    grant already `REVOKED`, `EXPIRED` or `SUPERSEDED` cannot be revoked again and
    yields `ERR_DELEGATION_NOT_ACTIVE` (HTTP 409)."
    PRD 3.3: "On success `status` becomes `REVOKED`, `version` is incremented, and —
    exactly as with supersession — every sale still open under that grant has its
    compliance dimension moved `CLEARED → FLAGGED`."

    Design: Corner/state_machines/corner_second_revoke_of_delegation_returns_delegation_not_active
    """
    sponsor = fx.create_patron(api, full_name="MSG P Vandermeer", id_card_class="ACTIVE_DUTY")
    delegate = fx.create_patron(
        api, full_name="Q Vandermeer", id_card_class="DEPENDENT", sponsor_patron_id=sponsor["id"]
    )
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_01,
        valid_to=C.SEP_01,
        per_sale_spend_cap_cents=30000,
        expected_delegate_patron_version=delegate["version"],
    )
    revoked = fx.revoke_delegation(api, delegation["id"], reason="PRIVILEGE_WITHDRAWN")
    assert revoked["status"] == "REVOKED"

    validate_error(
        api.revoke_delegation(
            delegation["id"],
            factories.delegation_revoke_payload("PRIVILEGE_WITHDRAWN"),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        "ERR_DELEGATION_NOT_ACTIVE",
        409,
    )

    read_delegation = fx.read_delegation(api, delegation["id"])
    assert read_delegation["status"] == "REVOKED"
    assert read_delegation["version"] == revoked["version"]


def test_a_rejected_project_cannot_be_resurrected_by_resubmission(api):
    """REJECTED is terminal, so submit answers ERR_PROJECT_NOT_DRAFT.

    PRD 3.9: "Submission is legal from `state` of either `DRAFT` or
    `RETURNED_FOR_REVISION`; from anything else it is refused with
    `ERR_PROJECT_NOT_DRAFT` (HTTP 409)."
    PRD 3.9: "**`SUBMITTED → REJECTED`** is taken on a `REJECT` decision and is
    terminal. No obligation is ever booked, and `submitted_by_user_id` is left as it
    stands."

    Design: Corner/state_machines/corner_submit_of_rejected_project_returns_project_not_draft
    """
    store = fx.create_store(
        api, name="Fort Hood Commissary", channel="COMMISSARY", region="CONUS"
    )
    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Parking lot resurfacing",
                requested_amount_cents=60000,
            ),
            make_fund_controller_headers("sfc-103"),
        ),
        201,
    )
    validate_success(
        api.submit_capital_project(project["id"], None, make_fund_controller_headers("sfc-103")),
        200,
    )
    validate_success(
        api.decide_capital_project(
            project["id"],
            factories.project_decision_payload(
                "REJECT", note="Out of scope for the surcharge fund"
            ),
            make_board_officer_headers("mwr-103"),
        ),
        200,
    )

    validate_error(
        api.submit_capital_project(project["id"], None, make_fund_controller_headers("sfc-103")),
        "ERR_PROJECT_NOT_DRAFT",
        409,
    )

    read_project = validate_success(
        api.get_capital_project(project["id"], HEADERS_FUND_CONTROLLER)
    )
    assert read_project["state"] == "REJECTED"
    assert read_project["revision_count"] == 0
    assert read_project["decided_by_user_id"] == "mwr-103"
    assert read_project["submitted_by_user_id"] == "sfc-103"

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_obligated_cents"] == 0


def test_revoking_a_suspended_card_sweeps_the_grant_and_freezes_the_watch_axis(api):
    """The grant goes REVOKED, the reason survives, and the dependent's card stays SUSPENDED.

    PRD 3.7: "**Revocation** (`SUSPENDED → REVOKED`, legal only while `card_status`
    is `SUSPENDED`, and terminal) leaves `suspension_reason` exactly as it stands."
    PRD 3.7: "Its cascade is broader in one respect and narrower in another: every
    shopper delegation in which this patron appears **either** as `sponsor_patron_id`
    **or** as `delegate_patron_id`, and whose `status` is `ACTIVE` or
    `SUSPENDED_BY_SPONSOR`, is moved to `REVOKED`. The patron's `resale_watch_status`
    is frozen at its current value and no further risk recomputation ever touches the
    record."
    PRD 3.7: "Hop one: every patron whose `sponsor_patron_id` names this patron and
    whose own `card_status` is `VALID` is itself moved to `SUSPENDED` with
    `suspension_reason` set to `SPONSOR_SUSPENDED` — a sponsor losing their card takes
    their dependents down with them."

    Design: Corner/state_machines/corner_card_revocation_revokes_all_delegations_and_freezes_watch_axis
    """
    sponsor = fx.create_patron(api, full_name="CW3 R Sanjuan", id_card_class="ACTIVE_DUTY")
    delegate = fx.create_patron(
        api, full_name="S Sanjuan", id_card_class="DEPENDENT", sponsor_patron_id=sponsor["id"]
    )
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_01,
        valid_to=C.SEP_01,
        per_sale_spend_cap_cents=30000,
        expected_delegate_patron_version=delegate["version"],
    )
    fx.set_card_status(api, sponsor["id"], "SUSPEND", reason="ADMIN_ACTION")

    revoked = validate_success(
        api.set_card_status(
            sponsor["id"], factories.card_status_payload("REVOKE"), HEADERS_COMPLIANCE_OFFICER
        ),
        200,
    )

    assert revoked["card_status"] == "REVOKED"
    assert revoked["suspension_reason"] == "ADMIN_ACTION"
    assert revoked["resale_watch_status"] == "CLEAR"
    assert revoked["resale_risk_score"] == 0

    assert fx.read_delegation(api, delegation["id"])["status"] == "REVOKED"

    read_delegate = fx.read_patron(api, delegate["id"])
    assert read_delegate["card_status"] == "SUSPENDED"
    assert read_delegate["suspension_reason"] == "SPONSOR_SUSPENDED"


def test_reinstatement_undoes_all_three_suspension_hops_without_touching_money(api):
    """Card, grant and basket all come back, and the basket's 1000 / 50 / 1050 is unchanged.

    PRD 3.7: "Hop one: every patron whose `sponsor_patron_id` names this patron, whose
    `card_status` is `SUSPENDED` **and** whose `suspension_reason` is
    `SPONSOR_SUSPENDED` is restored to `VALID` with `suspension_reason` cleared to null
    — a dependent suspended for its own reasons is deliberately left suspended."
    PRD 3.7: "Hop two, caused by hop one: every delegation whose `delegate_patron_id`
    names one of those restored dependents and whose `status` is `SUSPENDED_BY_SPONSOR`
    is moved back `SUSPENDED_BY_SPONSOR → ACTIVE`."
    PRD 3.7: "Hop three, caused by hop two: every sale whose `acting_delegation_id`
    names one of those reactivated delegations, whose `tender_state` is `OPEN` and
    whose `compliance_state` is `FLAGGED` is moved back `FLAGGED → CLEARED`."
    PRD 3.5: "Finally `total_due_cents` is `merchandise_cents` plus
    `markup_total_cents` plus `surcharge_total_cents` plus `tax_cents`."

    Design: Corner/state_machines/corner_reinstatement_compensates_three_hop_suspension_end_to_end
    """
    store = fx.create_store(
        api,
        name="Fort Belvoir Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-CMP-500",
        name="Ground Coffee 12oz",
        category="GROCERY_STAPLE",
        unit_cost_cents=500,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="F6",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    sponsor = fx.create_patron(api, full_name="1SG T Abernathy", id_card_class="ACTIVE_DUTY")
    delegate = fx.create_patron(
        api, full_name="U Abernathy", id_card_class="DEPENDENT", sponsor_patron_id=sponsor["id"]
    )
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_01,
        valid_to=C.SEP_01,
        per_sale_spend_cap_cents=30000,
        expected_delegate_patron_version=delegate["version"],
    )
    fx.set_clock(api, C.AUG_02)
    sale = fx.open_sale(api, store["id"], sponsor["id"], acting_delegation_id=delegation["id"])
    fx.add_line(api, sale["id"], product["id"], 2)
    fx.set_card_status(api, sponsor["id"], "SUSPEND", reason="ADMIN_ACTION")

    reinstated = validate_success(
        api.set_card_status(
            sponsor["id"], factories.card_status_payload("REINSTATE"), HEADERS_COMPLIANCE_OFFICER
        ),
        200,
    )
    assert reinstated["card_status"] == "VALID"
    assert reinstated["suspension_reason"] is None

    read_delegate = fx.read_patron(api, delegate["id"])
    assert read_delegate["card_status"] == "VALID"
    assert read_delegate["suspension_reason"] is None

    assert fx.read_delegation(api, delegation["id"])["status"] == "ACTIVE"

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["compliance_state"] == "CLEARED"
    assert read_sale["tender_state"] == "OPEN"
    assert read_sale["merchandise_cents"] == 1000
    assert read_sale["surcharge_total_cents"] == 50
    assert read_sale["total_due_cents"] == 1050

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_fund_balance_cents"] == 0


def test_the_checkpoint_lapses_the_stale_grant_and_fulfils_the_local_fill_order(api):
    """One sweep, two different rows moved, and the close index advances to exactly 1.

    PRD 3.9: "Every shopper delegation whose `status` is `ACTIVE` and whose `valid_to`
    is at or before the logical clock's current instant transitions `ACTIVE →
    EXPIRED`, with `version` incremented."
    PRD 3.9: "Every special order of this store whose `state` is `LOCAL_FILL_PENDING`
    or `OVERSEAS_SHIP_PENDING` transitions to `FULFILLED`, with `version` incremented,
    and the store's `shipping_allowance_committed_cents` is left unchanged."
    PRD 3.8: "The order will be filled from local stock, so no freight is incurred at
    all: `gross_ship_cents`, `patron_share_cents` and `shipping_allowance_cents` are
    all set to 0."
    PRD 3.9: "The store's `period_close_index` is incremented by 1 and the store's
    `version` is incremented by 1."

    Design: Corner/state_machines/corner_close_period_expires_lapsed_delegation_and_fulfils_pending_order
    """
    store = fx.create_store(
        api,
        name="Vicenza Commissary",
        channel="COMMISSARY",
        region="OVERSEAS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-SWP-700",
        name="Olive Oil 1L",
        category="GROCERY_STAPLE",
        unit_cost_cents=700,
        unit_weight_grams=1000,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="G7",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    sponsor = fx.create_patron(api, full_name="MAJ V Castellano", id_card_class="ACTIVE_DUTY")
    delegate = fx.create_patron(
        api, full_name="W Castellano", id_card_class="DEPENDENT", sponsor_patron_id=sponsor["id"]
    )
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_01,
        valid_to=C.AUG_05,
        per_sale_spend_cap_cents=30000,
        expected_delegate_patron_version=delegate["version"],
    )
    order = fx.create_special_order(api, store["id"], sponsor["id"], product["id"], 3)
    fx.route_special_order(api, order["id"], "LOCAL_FILL")
    fx.set_clock(api, C.AUG_06)

    closed = validate_success(api.close_period(store["id"], None, HEADERS_FUND_CONTROLLER), 200)
    assert closed["period_close_index"] == 1

    read_delegation = fx.read_delegation(api, delegation["id"])
    assert read_delegation["status"] == "EXPIRED"
    assert read_delegation["superseded_by_delegation_id"] is None

    read_order = fx.read_special_order(api, order["id"])
    assert read_order["state"] == "FULFILLED"
    assert read_order["route"] == "LOCAL_FILL"
    assert read_order["gross_ship_cents"] == 0
    assert read_order["patron_share_cents"] == 0
    assert read_order["shipping_allowance_cents"] == 0

    read_store = fx.read_store(api, store["id"])
    assert read_store["shipping_allowance_committed_cents"] == 0
    assert read_store["period_close_index"] == 1
    assert read_store["fund_posture"] == "FROZEN"

    _entries, meta = validate_paginated(
        api.list_fund_ledger(store["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0


def test_a_grant_from_a_second_sponsor_displaces_the_incumbent_rather_than_colliding(api):
    """The incumbent is SUPERSEDED with a forward pointer and its open basket is flagged.

    PRD 3.3: "A delegate may only shop for one sponsor at a time, so a new grant from
    a *different* sponsor whose window intersects an existing `ACTIVE` grant of that
    delegate does not collide — it displaces."
    PRD 3.3: "The older grant transitions `ACTIVE → SUPERSEDED`, its
    `superseded_by_delegation_id` is set to the `id` of the new grant, its `version` is
    incremented, and every sale still open that was rung under the displaced grant has
    its compliance dimension moved `CLEARED → FLAGGED`, since those baskets were
    assembled under authority that has now been withdrawn."
    PRD 3.3: "Because a delegate's live grants are a patron-level aggregate, the grant
    request must also carry `expected_delegate_patron_version` as described in §2.7,
    and a successful grant advances the delegate patron's `version` by 1."

    Design: Corner/state_machines/corner_delegation_from_different_sponsor_supersedes_overlapping_grant
    """
    store = fx.create_store(
        api,
        name="Fort Meade Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api, sku="SKU-SUP-500", name="Pasta 2lb", category="GROCERY_STAPLE", unit_cost_cents=500
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="H7",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    sponsor_one = fx.create_patron(api, full_name="SFC X Lindqvist", id_card_class="ACTIVE_DUTY")
    sponsor_two = fx.create_patron(api, full_name="SFC Y Bertrand", id_card_class="ACTIVE_DUTY")
    delegate = fx.create_patron(
        api,
        full_name="Z Lindqvist",
        id_card_class="DEPENDENT",
        sponsor_patron_id=sponsor_one["id"],
    )
    delegation_one = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor_one["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_01,
        valid_to=C.SEP_01,
        per_sale_spend_cap_cents=30000,
        expected_delegate_patron_version=delegate["version"],
    )
    fx.set_clock(api, C.AUG_02)
    sale = fx.open_sale(api, store["id"], sponsor_one["id"], acting_delegation_id=delegation_one["id"])
    fx.add_line(api, sale["id"], product["id"], 1)
    delegate_before = fx.read_patron(api, delegate["id"])

    delegation_two = validate_success(
        api.create_delegation(
            factories.delegation_payload(
                sponsor_patron_id=sponsor_two["id"],
                delegate_patron_id=delegate["id"],
                expected_delegate_patron_version=delegate_before["version"],
                valid_from=C.AUG_05,
                valid_to=C.AUG_20,
                per_sale_spend_cap_cents=45000,
            ),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        201,
    )
    assert delegation_two["status"] == "ACTIVE"
    assert delegation_two["superseded_by_delegation_id"] is None

    read_one = fx.read_delegation(api, delegation_one["id"])
    assert read_one["status"] == "SUPERSEDED"
    assert read_one["superseded_by_delegation_id"] == delegation_two["id"]

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["compliance_state"] == "FLAGGED"
    assert read_sale["tender_state"] == "OPEN"

    assert fx.read_patron(api, delegate["id"])["version"] == delegate_before["version"] + 1


def test_a_second_tender_is_refused_and_the_fund_is_not_credited_twice(api):
    """Tender is single-shot: 409, one ledger entry, and the balance stays at 25.

    PRD 3.6: "The visit's `tender_state` must be `OPEN`, or the attempt is refused
    with `ERR_SALE_NOT_OPEN`."
    PRD 3.6: "First, unconditionally, an entry against the `SURCHARGE` fund with
    `entry_type` of `SURCHARGE_COLLECTION` and `amount_cents` equal to the visit's
    `surcharge_total_cents` as a positive amount, with `source_ref_kind` of `SALE` and
    `source_ref_id` naming the visit."

    Design: Corner/state_machines/corner_second_tender_of_tendered_sale_returns_sale_not_open
    """
    store = fx.create_store(
        api,
        name="Fort Jackson Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api, sku="SKU-IDM-500", name="Cereal Box", category="GROCERY_STAPLE", unit_cost_cents=500
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="I8",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SGT A Boudreaux", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 1)
    tendered = fx.tender_sale(api, sale["id"])
    assert tendered["surcharge_total_cents"] == 25

    validate_error(
        api.tender_sale(sale["id"], factories.tender_payload(), HEADERS_STORE_CASHIER),
        "ERR_SALE_NOT_OPEN",
        409,
    )

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["tender_state"] == "TENDERED"
    assert read_sale["version"] == tendered["version"]

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_fund_balance_cents"] == 25

    _entries, meta = validate_paginated(
        api.list_fund_ledger(store["id"], {"fund": "SURCHARGE"}, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 1
