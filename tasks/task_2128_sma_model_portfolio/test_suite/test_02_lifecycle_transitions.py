"""Lifecycle transition coverage for the SMA Model Delivery API.

Every test here drives a subject row into one specific from-state and then
exercises a transition against it, checking both the outcome the PRD declares
and the fields the PRD says are (or are not) written.
"""
from test_helpers import (
    COMPLIANCE_USER_ID,
    MANAGER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    approve_version,
    create_draft_version,
    create_harvest_proposal,
    create_block,
    create_model,
    create_securities,
    execute_block,
    execute_block_payload,
    get_account,
    get_block,
    get_model_version,
    get_trade_order,
    lift_restriction,
    list_tax_lots,
    make_portfolio_manager_headers,
    publish_version,
    rebalance,
    reject_harvest,
    setup_drifted_account_with_orders,
    setup_funded_account,
    setup_harvest_ready_account,
    submit_version,
    suspend_account,
    cancel_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
MANAGER_HEADERS = TEST_USERS["portfolio_manager_headers"]
COMPLIANCE_HEADERS = TEST_USERS["compliance_officer_headers"]

ALFA_ONLY = [("ALFA", "Alfa Industrials", 10_000)]
ALFA_SLEEVE = [("ALFA", 10000)]


def _model_with_approved_version():
    """Register ALFA, a strategy, and carry one version through to APPROVED."""
    securities = create_securities(ALFA_ONLY)
    model = create_model()
    version = create_draft_version(model["id"], ALFA_SLEEVE, securities)
    submit_version(version["id"], MANAGER_USER_ID)
    approve_version(version["id"], COMPLIANCE_USER_ID)
    return securities, model, get_model_version(version["id"])


def _publish_new_version(model_id, securities):
    """Author, submit, approve and publish one more version of the strategy."""
    version = create_draft_version(model_id, ALFA_SLEEVE, securities)
    submit_version(version["id"], MANAGER_USER_ID)
    approve_version(version["id"], COMPLIANCE_USER_ID)
    return publish_version(version["id"], MANAGER_USER_ID)


# ---------------------------------------------------------------------------
# ModelVersion transitions
# ---------------------------------------------------------------------------
def test_submit_on_an_approved_version_is_refused_as_invalid_state(api):
    """PRD §2.6: "Opening an account against a model that has never published a version fails with `ERR_MODEL_NOT_PUBLISHED`; requesting a rebalance on an account whose `implementation_status` is not `DRIFTED` fails with `ERR_ACCOUNT_NOT_DRIFTED`; every other from-state mismatch, including requesting an implementation on an account that is not in `PENDING_IMPLEMENTATION`, fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/submit_from_approved_model_version_returns_invalid_state
    """
    _securities, _model, version = _model_with_approved_version()
    assert version["status"] == "APPROVED", "Setup must leave the version APPROVED"

    response = api.submit_model_version(
        version["id"], make_portfolio_manager_headers(MANAGER_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_model_version(version["id"])
    assert after["status"] == "APPROVED", (
        "A refused submission must leave the version in APPROVED, "
        f"got {after['status']}"
    )
    assert after["approved_by_user_id"] == COMPLIANCE_USER_ID, (
        "approved_by_user_id must still name the reviewing user, "
        f"got {after['approved_by_user_id']!r}"
    )
    assert after["submitted_by_user_id"] == MANAGER_USER_ID, (
        "submitted_by_user_id must be untouched by the refused submission, "
        f"got {after['submitted_by_user_id']!r}"
    )


def test_publish_on_a_draft_version_is_refused_as_invalid_state(api):
    """PRD §2.6: "Opening an account against a model that has never published a version fails with `ERR_MODEL_NOT_PUBLISHED`; requesting a rebalance on an account whose `implementation_status` is not `DRIFTED` fails with `ERR_ACCOUNT_NOT_DRIFTED`; every other from-state mismatch, including requesting an implementation on an account that is not in `PENDING_IMPLEMENTATION`, fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/publish_from_draft_model_version_returns_invalid_state
    """
    securities = create_securities(ALFA_ONLY)
    model = create_model()
    version = create_draft_version(model["id"], ALFA_SLEEVE, securities)
    assert version["status"] == "DRAFT", "Setup must leave the version in DRAFT"

    response = api.publish_model_version(
        version["id"], make_portfolio_manager_headers(MANAGER_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_model_version(version["id"])
    assert after["status"] == "DRAFT", (
        f"A refused publication must leave the version in DRAFT, got {after['status']}"
    )
    assert after["published_at"] is None, (
        f"published_at must stay null, got {after['published_at']!r}"
    )

    model_after = validate_success(api.get_model(model["id"], MANAGER_HEADERS), 200)
    assert model_after["published_model_version_id"] is None, (
        "The strategy's published_model_version_id must stay null, got "
        f"{model_after['published_model_version_id']!r}"
    )


def test_republishing_a_superseded_version_is_refused_as_invalid_state(api):
    """PRD §2.6: "Opening an account against a model that has never published a version fails with `ERR_MODEL_NOT_PUBLISHED`; requesting a rebalance on an account whose `implementation_status` is not `DRIFTED` fails with `ERR_ACCOUNT_NOT_DRIFTED`; every other from-state mismatch, including requesting an implementation on an account that is not in `PENDING_IMPLEMENTATION`, fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/superseded_model_version_rejects_every_further_transition
    """
    securities, model, version_one = _model_with_approved_version()
    publish_version(version_one["id"], MANAGER_USER_ID)
    version_two = _publish_new_version(model["id"], securities)

    assert get_model_version(version_one["id"])["status"] == "SUPERSEDED", (
        "Publishing the successor must supersede the previously published version"
    )

    response = api.publish_model_version(
        version_one["id"], make_portfolio_manager_headers(MANAGER_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_model_version(version_one["id"])
    assert after["status"] == "SUPERSEDED", (
        f"A superseded version is never revived, got {after['status']}"
    )

    model_after = validate_success(api.get_model(model["id"], MANAGER_HEADERS), 200)
    assert model_after["published_model_version_id"] == version_two["id"], (
        "The strategy must still point at the newer published version, got "
        f"{model_after['published_model_version_id']!r}"
    )

    published, meta = validate_paginated(
        api.list_model_versions(
            MANAGER_HEADERS, params={"model_id": model["id"], "status": "PUBLISHED"}
        )
    )
    assert meta["total_count"] == 1, (
        "At most one version of a strategy may sit in PUBLISHED, total_count was "
        f"{meta['total_count']}"
    )
    assert len(published) == 1 and published[0]["id"] == version_two["id"], (
        "The single PUBLISHED row must be the newer version"
    )


# ---------------------------------------------------------------------------
# Account implementation-dimension transitions
# ---------------------------------------------------------------------------
def test_suspending_an_already_suspended_account_is_refused(api):
    """PRD §2.6: "Opening an account against a model that has never published a version fails with `ERR_MODEL_NOT_PUBLISHED`; requesting a rebalance on an account whose `implementation_status` is not `DRIFTED` fails with `ERR_ACCOUNT_NOT_DRIFTED`; every other from-state mismatch, including requesting an implementation on an account that is not in `PENDING_IMPLEMENTATION`, fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/suspending_an_already_suspended_account_returns_invalid_state
    """
    env = setup_funded_account(securities=ALFA_ONLY, sleeves=ALFA_SLEEVE)
    suspended = suspend_account(env["account"]["id"])
    assert suspended["implementation_status"] == "SUSPENDED", (
        "Setup must leave the account SUSPENDED"
    )
    version_after_first = suspended["version"]

    response = api.suspend_account(env["account"]["id"], COMPLIANCE_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_account(env["account"]["id"])
    assert after["implementation_status"] == "SUSPENDED", (
        f"The account must stay SUSPENDED, got {after['implementation_status']}"
    )
    assert after["billing_status"] == "CURRENT", (
        "Suspension leaves the billing dimension untouched, got "
        f"{after['billing_status']}"
    )
    assert after["version"] == version_after_first, (
        "A refused transition mutates nothing, so the account version must stay "
        f"{version_after_first}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# AccountRestriction ACTIVE -> LIFTED
# ---------------------------------------------------------------------------
def test_lifting_a_restriction_restores_base_weights_on_the_next_generation(api):
    """PRD §3.4: "Lifting a restriction moves it `ACTIVE → LIFTED`, stamps `lifted_at` at the clock instant, and advances both the restriction's `version` and the account's `version`; from the next generation onward the lifted restriction stops participating in the effective-weight computation entirely, although any orders it already shaped are left exactly as they were."

    Design: Corner/state_machines/lifting_a_restriction_restores_base_weights_on_the_next_generation
    """
    env = setup_drifted_account_with_orders(
        drift_threshold_bps=1000,
        restrictions=[("ALFA", "MAX_POSITION", 3000)],
    )
    account_id = env["account"]["id"]
    beta_id = env["securities"]["BETA"]["id"]

    restricted_beta = next(
        order for order in env["orders"] if order["security_id"] == beta_id
    )
    assert restricted_beta["effective_weight_bps"] == 4200, (
        "Under the ALFA cap the free BETA sleeve must solve to 4200 bps, got "
        f"{restricted_beta['effective_weight_bps']}"
    )
    assert restricted_beta["side"] == "BUY", (
        f"The capped generation must buy BETA, got {restricted_beta['side']}"
    )
    assert restricted_beta["shares"] == 579, (
        f"The capped generation must buy 579 BETA shares, got {restricted_beta['shares']}"
    )

    lifted = lift_restriction(env["restrictions"][0]["id"])
    assert lifted["status"] == "LIFTED", (
        f"The restriction must move ACTIVE -> LIFTED, got {lifted['status']}"
    )
    assert lifted["lifted_at"] is not None, "lifted_at must be stamped at the lift"

    rebalance(account_id, env["sponsor"]["id"])

    beta_orders, beta_meta = validate_paginated(
        api.list_trade_orders(
            ADMIN_HEADERS,
            params={
                "account_id": account_id,
                "security_id": beta_id,
                "status": "PROPOSED",
            },
        )
    )
    assert beta_meta["total_count"] == 2, (
        f"Two PROPOSED BETA orders must exist, got {beta_meta['total_count']}"
    )
    assert beta_orders[0]["id"] == restricted_beta["id"], (
        "Orders list created_at ascending, so the capped order comes first"
    )

    free_beta = beta_orders[1]
    assert free_beta["effective_weight_bps"] == 3000, (
        "Once the cap is lifted BETA returns to its 3000 bps base weight, got "
        f"{free_beta['effective_weight_bps']}"
    )
    assert free_beta["side"] == "SELL", (
        f"The unrestricted generation must sell BETA, got {free_beta['side']}"
    )
    assert free_beta["shares"] == 15, (
        f"The unrestricted generation must sell 15 BETA shares, got {free_beta['shares']}"
    )

    _active, active_meta = validate_paginated(
        api.list_restrictions(
            ADMIN_HEADERS, params={"account_id": account_id, "status": "ACTIVE"}
        )
    )
    assert active_meta["total_count"] == 0, (
        f"No ACTIVE restriction may remain on the account, got {active_meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# HarvestProposal branches out of PROPOSED
# ---------------------------------------------------------------------------
def test_harvest_rejection_writes_only_the_rejection_note(api):
    """PRD §3.8: "Rejection by a `ComplianceOfficer` moves it `PROPOSED → REJECTED`, records the reviewer's supplied text as `rejection_note`, and writes nothing else — `realized_loss_cents` stays null, and not a single tax lot is touched."

    Design: Corner/state_machines/harvest_reject_branch_writes_only_the_rejection_note
    """
    env = setup_harvest_ready_account(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        harvest_budget_cents=500_000,
        positions=[("ALFA", 100, 1_200_000)],
    )
    account_id = env["account"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]
    lot = list_tax_lots(account_id=account_id)[0]

    proposal = create_harvest_proposal(account_id, alfa_id, 100)
    assert proposal["status"] == "PROPOSED", "Setup must leave the proposal PROPOSED"

    note = "Client opted out of loss harvesting this quarter"
    rejected = reject_harvest(proposal["id"], note)
    assert rejected["status"] == "REJECTED", (
        f"Rejection must move the proposal to REJECTED, got {rejected['status']}"
    )

    after = validate_success(
        api.get_harvest_proposal(proposal["id"], MANAGER_HEADERS), 200
    )
    assert after["rejection_note"] == note, (
        f"rejection_note must record the reviewer's text, got {after['rejection_note']!r}"
    )
    assert after["realized_loss_cents"] is None, (
        f"realized_loss_cents must stay null, got {after['realized_loss_cents']!r}"
    )
    assert after["executed_at"] is None, (
        f"executed_at must stay null, got {after['executed_at']!r}"
    )
    assert after["approved_by_user_id"] is None, (
        f"approved_by_user_id must stay null, got {after['approved_by_user_id']!r}"
    )
    assert after["target_loss_cents"] == -200000, (
        "The signed net quote must be preserved through the rejection, got "
        f"{after['target_loss_cents']}"
    )
    assert after["proposed_loss_cents"] == 200000, (
        "The negative-only quote must be preserved through the rejection, got "
        f"{after['proposed_loss_cents']}"
    )

    lot_after = validate_success(api.get_tax_lot(lot["id"], ADMIN_HEADERS), 200)
    assert lot_after["status"] == "OPEN", (
        f"No tax lot may be touched by a rejection, got status {lot_after['status']}"
    )
    assert lot_after["shares_open"] == 100, (
        f"The lot must still hold 100 open shares, got {lot_after['shares_open']}"
    )
    assert lot_after["realized_gain_cents"] is None, (
        f"realized_gain_cents must stay null, got {lot_after['realized_gain_cents']!r}"
    )

    account_after = get_account(account_id)
    assert account_after["cash_cents"] == 0, (
        f"A rejection credits no cash, got {account_after['cash_cents']}"
    )
    assert account_after["realized_loss_ytd_cents"] == 0, (
        "A rejection realizes no loss, got "
        f"{account_after['realized_loss_ytd_cents']}"
    )


def test_a_second_proposal_supersedes_the_prior_one_for_the_same_pair(api):
    """PRD §3.8: "Creating a proposal also **supersedes** any earlier proposal for the same account and security that is still sitting in `PROPOSED`, moving it `PROPOSED → SUPERSEDED`."

    Design: Corner/state_machines/second_harvest_proposal_supersedes_the_prior_one_for_the_same_pair
    """
    env = setup_harvest_ready_account(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        harvest_budget_cents=500_000,
        positions=[("ALFA", 100, 1_200_000)],
    )
    account_id = env["account"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]

    first = create_harvest_proposal(account_id, alfa_id, 100)
    version_before_second = get_account(account_id)["version"]

    second = create_harvest_proposal(
        account_id, alfa_id, 40, expected_account_version=version_before_second
    )

    first_after = validate_success(
        api.get_harvest_proposal(first["id"], MANAGER_HEADERS), 200
    )
    assert first_after["status"] == "SUPERSEDED", (
        "The earlier live proposal for the same account and security must be "
        f"superseded, got {first_after['status']}"
    )
    assert second["status"] == "PROPOSED", (
        f"The newer proposal stays PROPOSED, got {second['status']}"
    )
    assert second["shares"] == 40, (
        f"The newer proposal must carry the 40 shares requested, got {second['shares']}"
    )
    assert second["target_loss_cents"] == -80000, (
        f"The signed net quote must be -80000, got {second['target_loss_cents']}"
    )
    assert second["proposed_loss_cents"] == 80000, (
        f"The negative-only quote must be 80000, got {second['proposed_loss_cents']}"
    )

    live, live_meta = validate_paginated(
        api.list_harvest_proposals(
            ADMIN_HEADERS, params={"account_id": account_id, "status": "PROPOSED"}
        )
    )
    assert live_meta["total_count"] == 1, (
        "The account may never carry two live proposals for one instrument, got "
        f"{live_meta['total_count']}"
    )
    assert live[0]["id"] == second["id"], "The surviving live proposal is the newer one"

    account_after = get_account(account_id)
    assert account_after["version"] == version_before_second + 1, (
        "A successful proposal advances the owning account's version to "
        f"{version_before_second + 1}, got {account_after['version']}"
    )


# ---------------------------------------------------------------------------
# Block and TradeOrder transitions
# ---------------------------------------------------------------------------
def _drifted_account_with_one_alfa_buy():
    """A DRIFTED ALFA-only account carrying exactly one PROPOSED BUY order."""
    env = setup_drifted_account_with_orders(
        drift_threshold_bps=10,
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        positions=[],
        cash_cents=1_000_000,
    )
    assert len(env["orders"]) == 1, (
        f"Setup must generate exactly one order, got {len(env['orders'])}"
    )
    return env


def test_executing_an_already_filled_block_is_refused_as_invalid_state(api):
    """PRD §2.6: "Opening an account against a model that has never published a version fails with `ERR_MODEL_NOT_PUBLISHED`; requesting a rebalance on an account whose `implementation_status` is not `DRIFTED` fails with `ERR_ACCOUNT_NOT_DRIFTED`; every other from-state mismatch, including requesting an implementation on an account that is not in `PENDING_IMPLEMENTATION`, fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/executing_an_already_executed_block_returns_invalid_state
    """
    env = _drifted_account_with_one_alfa_buy()
    order = env["orders"][0]
    assert order["shares"] == 99, (
        f"Setup must generate a BUY of 99 ALFA shares, got {order['shares']}"
    )

    block = create_block([order["id"]], env["sponsor"]["id"])
    block = execute_block(block["id"], 99, 10_000)
    assert block["status"] == "FILLED", "Setup must leave the block FILLED"

    response = api.execute_block(
        block["id"], execute_block_payload(50, 9_000), ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_block(block["id"])
    assert after["status"] == "FILLED", (
        f"The block must stay FILLED, got {after['status']}"
    )
    assert after["filled_shares"] == 99, (
        f"filled_shares must not be overwritten, got {after['filled_shares']}"
    )
    assert after["avg_fill_price_cents"] == 10_000, (
        "avg_fill_price_cents must not be overwritten, got "
        f"{after['avg_fill_price_cents']}"
    )
    assert after["allocated_shares"] == 0, (
        f"allocated_shares must still be 0, got {after['allocated_shares']}"
    )
    assert after["unallocated_shares"] == 99, (
        "unallocated_shares must still be the whole fill, got "
        f"{after['unallocated_shares']}"
    )

    order_after = get_trade_order(order["id"])
    assert order_after["status"] == "BLOCKED", (
        f"The member order must stay BLOCKED, got {order_after['status']}"
    )
    assert order_after["shares"] == 99, (
        f"The member order must still request 99 shares, got {order_after['shares']}"
    )
    assert order_after["target_shares"] == 99, (
        f"target_shares must still be 99, got {order_after['target_shares']}"
    )


def test_cancelling_a_blocked_order_recomputes_the_block_counters(api):
    """PRD §3.7: "A cancellation out of `BLOCKED` clears the order's `block_id` and makes the block recompute its `requested_shares` and `order_count`."

    Design: Corner/state_machines/cancelling_a_blocked_order_recomputes_the_block_counters
    """
    env = _drifted_account_with_one_alfa_buy()
    order = env["orders"][0]

    block = create_block([order["id"]], env["sponsor"]["id"])
    assert block["status"] == "OPEN", "Setup must leave the block OPEN"
    assert block["requested_shares"] == 99, (
        f"The fresh block must request 99 shares, got {block['requested_shares']}"
    )
    assert block["order_count"] == 1, (
        f"The fresh block must hold one member, got {block['order_count']}"
    )

    cancelled = cancel_order(order["id"], env["sponsor"]["id"])
    assert cancelled["status"] == "CANCELLED", (
        f"The order must move BLOCKED -> CANCELLED, got {cancelled['status']}"
    )
    assert cancelled["block_id"] is None, (
        f"The cancellation must clear block_id, got {cancelled['block_id']!r}"
    )

    after = get_block(block["id"])
    assert after["requested_shares"] == 0, (
        f"The block must recompute requested_shares to 0, got {after['requested_shares']}"
    )
    assert after["order_count"] == 0, (
        f"The block must recompute order_count to 0, got {after['order_count']}"
    )
    assert after["status"] == "OPEN", (
        f"The block itself stays OPEN, got {after['status']}"
    )
    assert after["filled_shares"] == 0, (
        f"filled_shares must still be 0, got {after['filled_shares']}"
    )
    assert after["allocated_shares"] == 0, (
        f"allocated_shares must still be 0, got {after['allocated_shares']}"
    )
    assert after["unallocated_shares"] == 0, (
        f"unallocated_shares must still be 0, got {after['unallocated_shares']}"
    )

    members, members_meta = validate_paginated(
        api.list_trade_orders(ADMIN_HEADERS, params={"block_id": block["id"]})
    )
    assert members_meta["total_count"] == 0, (
        f"No order may still name the block, got {members_meta['total_count']}"
    )
    assert members == [], "The block's member listing must be empty"
