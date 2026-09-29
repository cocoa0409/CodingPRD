"""Who may do what, and the identity check that outlives the role check.

Six opaque roles with disjoint write surfaces, the kiosk identity's narrow reach, the
shared read surface the segregation rule does not partition, and the close-out gate that
compares two stored operator strings.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
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


def test_the_cashier_who_opened_the_visit_still_cannot_void_it(api):
    """Reading is the cashier's, voiding is not, on the very same visit.

    PRD 2.1: "**`StoreCashier`** — the point-of-sale operator. This role opens sales,
    rings lines, tenders, and routes special orders. It cannot void a sale; voiding is the
    `ComplianceOfficer`'s exclusive power."
    PRD 2.8: "2. **Authorisation** — the role is permitted on this endpoint
    (`ERR_ROLE_NOT_PERMITTED`), and then, for the five patron-scoped operations, that the
    acting patron owns the addressed record (`ERR_PATRON_SCOPE_VIOLATION`)."

    Design: Corner/rbac/corner_cashier_cannot_void_sale
    """
    store = fx.create_store(
        api,
        name="Fort Novosel Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    patron = fx.create_patron(api, full_name="SGT I Kovalenko", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])

    validate_error(
        api.void_sale(
            sale["id"], factories.void_payload("OPERATOR_ERROR"), HEADERS_STORE_CASHIER
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    read_sale = validate_success(api.get_sale(sale["id"], HEADERS_STORE_CASHIER), 200)
    assert read_sale["tender_state"] == "OPEN"
    assert read_sale["voided_reason"] is None


def test_the_controller_who_submitted_a_project_cannot_also_decide_it(api):
    """The decision belongs to the board, so the project stays SUBMITTED and undecided.

    PRD 2.1: "**`SurchargeFundController`** — the agency fund officer. This role registers
    stores, runs the period-close checkpoint, and drafts, submits and closes
    surcharge-funded capital projects. It may never render the board decision on a
    project, and it may not close a project it submitted itself."
    PRD 3.9: "An `MwrBoardOfficer` — and only an `MwrBoardOfficer` — renders the decision,
    supplying a `decision` of `APPROVE`, `RETURN` or `REJECT` together with an optional
    `note`."

    Design: Corner/rbac/corner_fund_controller_cannot_decide_capital_project
    """
    controller = make_fund_controller_headers("sfc-701")
    store = fx.create_store(
        api,
        name="Fort Rucker Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    project = fx.create_capital_project(
        api,
        store["id"],
        title="Bakery oven refit",
        requested_amount_cents=250000,
        headers=controller,
    )
    fx.submit_capital_project(api, project["id"], headers=controller)

    validate_error(
        api.decide_capital_project(
            project["id"], factories.project_decision_payload("APPROVE"), controller
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    read_project = validate_success(
        api.get_capital_project(project["id"], HEADERS_FUND_CONTROLLER)
    )
    assert read_project["state"] == "SUBMITTED"
    assert read_project["decided_by_user_id"] is None
    assert read_project["submitted_by_user_id"] == "sfc-701"
    assert fx.read_store(api, store["id"])["surcharge_obligated_cents"] == 0


def test_the_board_officer_cannot_reach_back_to_the_submit_step(api):
    """Deciding does not imply submitting: the draft stays a draft.

    PRD 2.1: "**`MwrBoardOfficer`** — a member of the morale, welfare and recreation
    board. This role registers dividend-funded programs and renders the board decision on
    capital projects. It cannot draft, submit or close a project."
    PRD 3.9: "On success `submitted_by_user_id` is set to the submitting caller's
    `X-User-ID` and `version` is incremented by 1."

    Design: Corner/rbac/corner_board_officer_cannot_submit_capital_project
    """
    controller = make_fund_controller_headers("sfc-702")
    officer = make_board_officer_headers("mwr-702")
    store = fx.create_store(
        api,
        name="Fort Cavazos Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    project = fx.create_capital_project(
        api,
        store["id"],
        title="Parking lot resurfacing",
        requested_amount_cents=250000,
        headers=controller,
    )

    validate_error(
        api.submit_capital_project(project["id"], None, officer), "ERR_ROLE_NOT_PERMITTED", 403
    )

    read_project = validate_success(api.get_capital_project(project["id"], officer), 200)
    assert read_project["state"] == "DRAFT"
    assert read_project["submitted_by_user_id"] is None
    assert read_project["revision_count"] == 0


def test_the_compliance_officer_has_no_write_access_to_the_item_file(api):
    """The refusal precedes any thought about the sku, and nothing is filed.

    PRD 2.1: "**`AssortmentPlanner`** — the worldwide category manager. This role owns the
    item file, shelf allocations, direct-store-delivery vendor terms and promotional
    allowance windows."
    PRD 2.1: "**`ComplianceOfficer`** — the patron eligibility and resale-compliance
    authority. This role enrols patrons, manages ID card status, grants and revokes
    authorized-shopper delegations, records resale strikes, and voids sales."

    Design: Corner/rbac/corner_compliance_officer_cannot_create_products
    """
    product = fx.create_product(
        api,
        sku="SKU-PEER-100",
        name="Paper Towels 12pk",
        category="GROCERY_STAPLE",
        unit_cost_cents=1200,
    )

    validate_error(
        api.create_product(
            factories.product_payload(
                sku="SKU-PEER-101",
                name="Contraband Watchlist Item",
                category="TOBACCO",
                unit_cost_cents=900,
            ),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    _rows, meta = validate_paginated(
        api.list_products({"category": "TOBACCO"}, HEADERS_ASSORTMENT_PLANNER)
    )
    assert meta["total_count"] == 0

    read_product = validate_success(
        api.get_product(product["id"], HEADERS_ASSORTMENT_PLANNER), 200
    )
    assert read_product["sku"] == "SKU-PEER-100"


def test_the_kiosk_identity_reads_itself_but_never_the_roster(api):
    """The collection endpoint is refused outright rather than filtered to one row.

    PRD 2.1: "**`Patron`** — the patron themselves, acting through a self-service kiosk. A
    patron may place and cancel their own special orders and read their own records."
    PRD 2.1: "This ownership check applies to exactly five operations: reading one patron,
    reading one sale, reading one special order, placing a special order, and cancelling a
    special order."

    Design: Corner/rbac/corner_patron_role_cannot_list_all_patrons
    """
    self_patron = fx.create_patron(api, full_name="SGT J Abernathy", id_card_class="ACTIVE_DUTY")
    other_patron = fx.create_patron(
        api, full_name="SPC K Vasconcelos", id_card_class="ACTIVE_DUTY"
    )
    self_headers = fx.patron_headers_for(self_patron)

    validate_error(api.list_patrons(None, self_headers), "ERR_ROLE_NOT_PERMITTED", 403)

    own_record = validate_success(api.get_patron(self_patron["id"], self_headers), 200)
    assert own_record["id"] == self_patron["id"]

    rows, meta = validate_paginated(api.list_patrons(None, HEADERS_COMPLIANCE_OFFICER))
    assert meta["total_count"] == 2
    assert other_patron["id"] in [row["id"] for row in rows]


def test_the_fund_controller_and_the_board_officer_read_the_same_project(api):
    """Segregation partitions writes only, so both roles see identical payloads.

    PRD 3.9: "Capital projects can be listed with optional `store_id` and `state` filters
    and read individually, by fund controllers and board officers alike."
    PRD 3.9: "When `requested_amount_cents` is below 500000 cents (5,000.00 US dollars),
    `contingency_bp` is 1000 basis points — ten percent."
    PRD 3.9: "Finally `obligation_cents` is `requested_amount_cents` plus
    `contingency_cents`, and that obligation figure — not the request amount — is what gets
    reserved against the surcharge fund while the project is approved."

    Design: Corner/rbac/corner_shared_reads_work_for_both_fund_and_board_roles
    """
    controller = make_fund_controller_headers("sfc-703")
    officer = make_board_officer_headers("mwr-703")
    store = fx.create_store(
        api,
        name="Fort Leavenworth Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    project = fx.create_capital_project(
        api,
        store["id"],
        title="Deli case replacement",
        requested_amount_cents=250000,
        headers=controller,
    )

    board_view = validate_success(api.get_capital_project(project["id"], officer), 200)
    board_ledger, board_meta = validate_paginated(
        api.list_fund_ledger(store["id"], None, officer)
    )
    assert board_view["state"] == "DRAFT"
    assert board_view["contingency_bp"] == 1000
    assert board_view["contingency_cents"] == 25000
    assert board_view["obligation_cents"] == 275000
    assert board_meta["total_count"] == 0
    assert board_ledger == []

    controller_view = validate_success(api.get_capital_project(project["id"], controller), 200)
    _controller_ledger, controller_meta = validate_paginated(
        api.list_fund_ledger(store["id"], None, controller)
    )
    assert controller_view == board_view
    assert controller_meta["total_count"] == 0


def test_the_officer_who_asked_for_the_money_may_not_sign_it_off(api):
    """The role and the state are both right; the stored operator string is what refuses.

    PRD 3.9: "And the closing caller's `X-User-ID` must differ from the project's stored
    `submitted_by_user_id`, or the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403): the officer who asked for the money may not be the officer who signs off
    that it was spent."
    PRD 2.1: "Those three stored strings are compared to each other — never to an entity
    `id` — when the segregation-of-duties rule is enforced."

    Design: Corner/rbac/corner_close_project_by_submitting_user_returns_segregation_of_duties
    """
    submitter = make_fund_controller_headers("sfc-050")
    other_controller = make_fund_controller_headers("sfc-051")
    officer = make_board_officer_headers("mwr-050")
    store = fx.create_store(
        api,
        name="Fort McCoy Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=1000,
    )
    product = fx.create_product(
        api,
        sku="SKU-SOD-100000",
        name="Pallet Coffee",
        category="GROCERY_STAPLE",
        unit_cost_cents=100000,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AH1",
        facings=10,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="MSG L Fontaine", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 60)
    fx.tender_sale(api, sale["id"])
    project = fx.create_capital_project(
        api,
        store["id"],
        title="Front-end canopy",
        requested_amount_cents=400000,
        headers=submitter,
    )
    fx.submit_capital_project(api, project["id"], headers=submitter)
    fx.decide_capital_project(api, project["id"], "APPROVE", headers=officer)

    validate_error(
        api.close_capital_project(
            project["id"], factories.project_close_payload(380000), submitter
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    parked = validate_success(api.get_capital_project(project["id"], HEADERS_FUND_CONTROLLER))
    assert parked["state"] == "APPROVED"
    assert parked["outlay_cents"] is None
    assert parked["closed_by_user_id"] is None
    assert parked["submitted_by_user_id"] == "sfc-050"
    assert parked["decided_by_user_id"] == "mwr-050"

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_obligated_cents"] == 440000
    assert read_store["surcharge_fund_balance_cents"] == 600000

    _rows, meta = validate_paginated(
        api.list_fund_ledger(
            store["id"], {"entry_type": "CAPITAL_OUTLAY"}, HEADERS_FUND_CONTROLLER
        )
    )
    assert meta["total_count"] == 0

    closed = validate_success(
        api.close_capital_project(
            project["id"], factories.project_close_payload(380000), other_controller
        ),
        200,
    )
    assert closed["state"] == "CLOSED"
    assert closed["closed_by_user_id"] == "sfc-051"
