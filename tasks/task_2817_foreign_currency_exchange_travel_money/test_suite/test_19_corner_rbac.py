"""The role model: the 401 that outranks everything, the 403 matrix in both
directions, and the segregation rule that binds exactly one pair of steps.

PRD 2.1 puts authentication first: "If either header is absent, or if
`X-User-Role` is not one of the six role names below, the request is refused with
`ERR_UNAUTHENTICATED` (HTTP 401)", and authorization second: "This permission check
runs **before** any identifier in the path is resolved, so an unauthorized role
calling an endpoint with a non-existent resource id receives 403 and never 404."
PRD 2.8 rank 9 then narrows segregation of duties to named pairs - "The acting
`X-User-ID` must differ from the user who performed the previous step of the same
workflow" - and PRD 3.3 names the first of them: "the reviewing `X-User-ID` must
differ from the plan's `submitted_by_user_id`".
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATORS,
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_customer_headers,
    make_manager_headers,
    make_treasury_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_authentication_outranks_both_authorization_and_id_resolution(
    api, admin_headers
):
    """A read with no X-User-Role, the same read declaring the undeclared role
    Auditor, a header-less read of an unresolvable id and a legal PlatformAdmin
    create with no X-User-ID all answer ERR_UNAUTHENTICATED at 401 - never 403 and
    never 404 - and the refused create leaves the single real branch alone.

    Design: Corner/rbac/unauthenticated_missing_headers_or_unknown_role_rejected_before_any_lookup
    """
    branch = fx.register_branch(api)

    validate_error(
        api.get_branch(branch["id"], headers_without_role()),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_branch(branch["id"], headers_with_unknown_role()),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_branch(NON_EXISTENT_UUID, headers_without_role()),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.create_branch(
            f.create_branch_payload(code="BR-XXX", name="Should not exist"),
            headers_without_user_id("PlatformAdmin"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    rows, meta = validate_paginated(api.list_branches(admin_headers))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [branch["id"]]
    assert rows[0]["code"] == "BR-LHR"


def test_no_role_can_cross_into_another_roles_exclusive_operation(
    api,
    admin_headers,
    treasury_headers,
    manager_headers,
    teller_headers,
    teller2_headers,
    compliance_headers,
    customer_headers,
):
    """Six exclusive operations are each attempted by the wrong role and each comes
    back ERR_UNAUTHORIZED at 403 with none of the endpoint's side effects performed -
    no rogue branch, the incumbent card unsuperseded and the branch version frozen,
    the hold still off, the deal still SETTLED and the contract still ISSUED at
    20000 remaining - and a ComplianceOfficer aimed at an unresolvable transaction
    id gets the same 403 rather than a 404.

    Design: Corner/rbac/role_exclusive_operations_cannot_be_crossed_by_any_other_role
    """
    world = fx.trading_world(api, position_mix=[f.denom(10000, 20)], identified=False)
    branch_id = world["branch"]["id"]
    customer_id = world["customer"]["id"]
    txn = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(txn, 22763, 797, 23560)
    contract = fx.issue_contract(api, customer_id, txn["id"], headers=teller_headers)
    assert contract["status"] == "ISSUED"
    assert contract["remaining_fx_minor_units"] == 20000
    pinned_branch_version = fx.branch_version(api, branch_id)

    validate_error(
        api.create_branch(
            f.create_branch_payload(code="BR-ZZZ", name="Rogue"), treasury_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_rate_card(
            f.create_rate_card_payload(
                branch_id,
                world["wholesale"]["id"],
                pinned_branch_version,
                buy_spread_bps=100,
                sell_spread_bps=100,
                board_display_label="EUR cheap",
                effective_from="2026-08-15T00:00:00Z",
            ),
            manager_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.compliance_hold(
            customer_id, f.compliance_hold_payload("APPLY", "not my job"), treasury_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.reverse_transaction(
            txn["id"], f.reverse_payload("not my job"), compliance_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.redeem_buyback_contract(
            contract["id"], f.redeem_payload([f.denom(10000, 1)]), admin_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.get_branch(branch_id, customer_headers),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.reverse_transaction(
            NON_EXISTENT_UUID, f.reverse_payload("probe"), compliance_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    _, branches_meta = validate_paginated(api.list_branches(admin_headers))
    assert branches_meta["total_count"] == 1
    cards, cards_meta = validate_paginated(api.list_rate_cards(treasury_headers))
    assert cards_meta["total_count"] == 1
    assert cards[0]["id"] == world["card"]["id"]
    assert cards[0]["status"] == "PUBLISHED"
    assert cards[0]["superseded_by_rate_card_id"] is None
    assert fx.branch_version(api, branch_id) == pinned_branch_version

    assert fx.read_customer(api, customer_id)["compliance_hold_active"] is False
    intact_deal = fx.read_transaction(api, txn["id"])
    assert intact_deal["settlement_status"] == "SETTLED"
    assert intact_deal["reversed_at"] is None
    intact_contract = fx.read_contract(api, contract["id"])
    assert intact_contract["status"] == "ISSUED"
    assert intact_contract["remaining_fx_minor_units"] == 20000
    assert intact_contract["redemption_count"] == 0


def test_all_six_roles_drive_one_deal_through_their_own_grants(
    api, admin_headers, treasury_headers, manager_headers, teller_headers, compliance_headers
):
    """The positive half of the matrix in one pass: the admin registers the estate,
    treasury prices it, the manager stocks it, the teller quotes and authorises, the
    manager settles the shared step for a 22763-cent gross, compliance clears axis B
    without moving the settlement axis, and the customer reads the one-line board and
    the currency catalogue - while GET /branches/{id} answers 200 for both a teller
    and a compliance officer at a vault of 195652 cents.

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_and_shared_operations
    """
    branch = validate_success(
        api.create_branch(f.create_branch_payload(), admin_headers), 201
    )
    currency = validate_success(
        api.create_currency(f.create_currency_payload(), admin_headers), 201
    )
    route = validate_success(
        api.create_armored_route(f.create_armored_route_payload(), admin_headers), 201
    )
    wholesale = validate_success(
        api.create_wholesale_rate(f.create_wholesale_rate_payload(), treasury_headers), 201
    )
    card = validate_success(
        api.create_rate_card(
            f.create_rate_card_payload(branch["id"], wholesale["id"], branch["version"]),
            treasury_headers,
        ),
        201,
    )
    published = validate_success(api.publish_rate_card(card["id"], treasury_headers))
    assert published["status"] == "PUBLISHED"
    position = validate_success(
        api.create_inventory_position(
            f.create_inventory_position_payload(
                branch["id"], currency["iso_code"], [f.denom(10000, 20)]
            ),
            manager_headers,
        ),
        201,
    )
    customer = validate_success(
        api.create_customer(
            f.create_customer_payload(home_branch_id=branch["id"]), teller_headers
        ),
        201,
    )

    quoted = validate_success(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch["id"],
                customer["id"],
                card["id"],
                currency["iso_code"],
                "SELL_FX_TO_CUSTOMER",
                [f.denom(10000, 2)],
            ),
            teller_headers,
        ),
        201,
    )
    authorized = validate_success(api.authorize_transaction(quoted["id"], teller_headers))
    assert authorized["authorized_by_user_id"] == OPERATORS["TELLER_1"]

    settled = validate_success(api.settle_transaction(quoted["id"], manager_headers))
    a.assert_exchange_transaction(settled)
    a.assert_settlement_money(settled, 22763, 797, 23560)
    assert settled["settlement_status"] == "SETTLED"
    assert settled["settled_by_user_id"] == OPERATORS["MANAGER"]

    cleared = validate_success(
        api.compliance_decision(
            quoted["id"],
            f.compliance_decision_payload("CLEAR", "reviewed, no concern"),
            compliance_headers,
        )
    )
    assert cleared["compliance_status"] == "CLEARED"
    assert cleared["settlement_status"] == "SETTLED"

    customer_headers_for_row = make_customer_headers(customer["id"])
    board = validate_success(api.get_rate_board(branch["id"], customer_headers_for_row))
    a.assert_rate_board(board)
    assert board["line_count"] == 1
    assert board["lines"][0]["board_display_label"] == "EUR Euro"
    catalogue, catalogue_meta = validate_paginated(
        api.list_currencies(customer_headers_for_row)
    )
    assert catalogue_meta["total_count"] == 1
    assert catalogue[0]["iso_code"] == "EUR"

    as_teller = validate_success(api.get_branch(branch["id"], teller_headers))
    a.assert_vault_state(as_teller, 195652, 98, "OPEN")
    as_compliance = validate_success(api.get_branch(branch["id"], compliance_headers))
    assert as_compliance["vault_usd_equivalent_cents"] == 195652

    live_route = validate_success(api.get_armored_route(route["id"], admin_headers))
    assert live_route["status"] == "ACTIVE"

    drawn_down = fx.read_position(api, position["id"])
    a.assert_position_mix_invariants(drawn_down)
    a.assert_mix_counts(drawn_down, 10000, available=18)
    assert drawn_down["total_minor_units"] == 180000


def test_segregation_binds_the_submit_review_pair_and_nothing_else(api, teller_headers):
    """One human wearing two hats cannot review the plan they submitted - the
    comparison is on X-User-ID, not on role - yet the very same human may activate
    that plan once an independent officer has approved it, and a lone teller may
    authorise and settle an 11382-cent deal because dual control only bites at
    500000 cents.

    Design: Corner/rbac/segregation_of_duties_binds_only_the_paired_step_it_names
    """
    submitter = "u-9"
    as_manager = make_manager_headers(submitter)
    wearing_treasury = make_treasury_headers(submitter)
    independent = make_treasury_headers(OPERATORS["TREASURY_ALT"])

    branch = fx.register_branch(api)
    fx.register_currency(api)
    fx.register_currency(api, f.chf_currency_payload())
    eur_wholesale = fx.record_wholesale_rate(api)
    fx.record_wholesale_rate(api, currency_code="CHF", mid_rate_micros=912345)
    card = fx.published_rate_card(
        api, branch["id"], eur_wholesale["id"], board_display_label="EUR Euro"
    )
    position = fx.open_position(api, branch["id"], "EUR", [f.denom(10000, 20)])
    corridor = fx.register_corridor(api)
    customer = fx.onboard_customer(api, home_branch_id=branch["id"])

    plan = fx.draft_plan(
        api,
        branch["id"],
        corridor["id"],
        season_days=10,
        target_lines=[f.target_line("CHF", 3000)],
        headers=as_manager,
    )
    submitted = fx.submit_plan(api, plan["id"], headers=as_manager)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == submitter
    assert submitted["revision_count"] == 0

    validate_error(
        api.review_inventory_plan(
            plan["id"], f.review_plan_payload("APPROVE", "self-approving"), wearing_treasury
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    refused = fx.read_plan(api, plan["id"])
    assert refused["status"] == "SUBMITTED"
    assert refused["reviewed_by_user_id"] is None
    assert refused["review_note"] is None
    assert refused["revision_count"] == 0

    approved = fx.review_plan(
        api, plan["id"], "APPROVE", "independent review", independent
    )
    a.assert_inventory_plan(approved)
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == OPERATORS["TREASURY_ALT"]
    assert approved["submitted_by_user_id"] == submitter
    a.assert_computed_targets_shape(approved["computed_targets"])
    assert approved["computed_targets"] == [
        {"currency_code": "CHF", "target_minor_units": 40000}
    ]

    activated = fx.activate_plan(api, plan["id"], as_manager)
    assert activated["status"] == "ACTIVE"
    assert activated["submitted_by_user_id"] == submitter
    assert activated["revision_count"] == 0

    deal = validate_success(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch["id"],
                customer["id"],
                card["id"],
                "EUR",
                "SELL_FX_TO_CUSTOMER",
                [f.denom(10000, 1)],
            ),
            teller_headers,
        ),
        201,
    )
    fx.authorize_deal(api, deal["id"], teller_headers)
    settled = fx.settle_deal(api, deal["id"], teller_headers)
    a.assert_settlement_money(settled, 11382, 400, 11782)
    assert settled["settlement_status"] == "SETTLED"
    assert settled["authorized_by_user_id"] == OPERATORS["TELLER_1"]
    assert settled["settled_by_user_id"] == OPERATORS["TELLER_1"]

    drawn_down = fx.read_position(api, position["id"])
    a.assert_position_mix_invariants(drawn_down)
    a.assert_mix_counts(drawn_down, 10000, available=19)
    assert drawn_down["total_minor_units"] == 190000
