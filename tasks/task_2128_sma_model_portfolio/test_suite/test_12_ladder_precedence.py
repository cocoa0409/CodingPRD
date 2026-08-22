"""Ordering of the validation ladder when one request violates two checks.

Each test builds a request that trips two rungs at once and pins the reported
error to the earlier rung, then rebuilds the same world with only the earlier
violation removed to show the later rung surfacing on the identical request.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_approved_version,
    create_block_payload,
    create_distribution,
    create_distribution_payload,
    create_draft_version,
    create_harvest_proposal_payload,
    create_restriction,
    get_account,
    get_model_version,
    get_success_data,
    get_trade_order,
    make_sponsor_operator_headers,
    publish_version,
    reinstate_account,
    set_clock,
    setup_drifted_account_with_orders,
    setup_harvest_ready_account,
    setup_platform,
    suspend_account,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["portfolio_manager_headers"]

ONE_ALFA = [("ALFA", "Alfa Industrials", 10_000)]
ALL_IN_ALFA = [("ALFA", 10000)]

# The TRADE acquisition sits on this date; the clock is then moved to a date
# exactly 30 days later (inside the closed lookback) or 31 days later (outside).
ACQUISITION_UTC = "2026-07-02T00:00:00Z"
THIRTY_DAYS_LATER_UTC = "2026-08-01T00:00:00Z"
THIRTY_ONE_DAYS_LATER_UTC = "2026-08-02T00:00:00Z"


# ---------------------------------------------------------------------------
# World builders
# ---------------------------------------------------------------------------
def _ceta_buy_order(env):
    """The BUY 980 CETA order the rebalance generated for the env's account."""
    ceta_id = env["securities"]["CETA"]["id"]
    return next(o for o in env["orders"] if o["security_id"] == ceta_id)


def _restricted_account_world():
    """A DRIFTED account holding a PROPOSED BUY of CETA, with an ACTIVE
    DO_NOT_BUY restriction attached to that very account and security after the
    order was generated."""
    env = setup_drifted_account_with_orders()
    env["ceta_order"] = _ceta_buy_order(env)
    env["restriction"] = create_restriction(
        env["account"]["id"], env["securities"]["CETA"]["id"], "DO_NOT_BUY"
    )
    return env


def _harvest_world():
    """An account with the tax overlay on and a 150000c budget, holding one
    TRANSFER_IN lot of 100 ALFA at 1,200,000c basis and one TRADE lot of 10 ALFA
    at 100,000c basis, both acquired on the acquisition date."""
    set_clock(ACQUISITION_UTC)
    return setup_harvest_ready_account(
        securities=ONE_ALFA,
        sleeves=ALL_IN_ALFA,
        harvest_budget_cents=150_000,
        positions=[
            ("ALFA", 100, 1_200_000, "TRANSFER_IN"),
            ("ALFA", 10, 100_000, "TRADE"),
        ],
    )


def _harvest_request(env, account):
    return create_harvest_proposal_payload(
        account["id"], env["securities"]["ALFA"]["id"], 100, account["version"]
    )


def _distribution_world():
    """v1 PUBLISHED and already distributed to the sponsor from 2026-01-01 with
    no end date, the distribution still sitting in PENDING."""
    env = setup_platform(securities=ONE_ALFA, sleeves=ALL_IN_ALFA)
    env["distribution_v1"] = create_distribution(
        env["sponsor"]["id"],
        env["model_version"]["id"],
        effective_from="2026-01-01T00:00:00Z",
    )
    return env


def _colliding_distribution_payload(env, model_version):
    """A window starting 2026-03-01 with no end, squarely inside the open-ended
    window the PENDING distribution already occupies on the same key."""
    return create_distribution_payload(
        env["sponsor"]["id"],
        model_version["id"],
        model_version["version"],
        "2026-03-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Rung 9 (account suspended) versus rung 13 (restricted security)
# ---------------------------------------------------------------------------
def test_block_create_reports_the_suspension_ahead_of_the_restricted_security(api):
    """PRD §2.6: "To make the API deterministic, every request is evaluated against a single fixed ladder of twenty-eight checks in ascending order, and the **first** check that fails determines the response. No later check may mask an earlier one, and no earlier check may be skipped because a later one looks more specific."

    PRD §2.6 rung 9: "**Account not suspended.** The target account — or, for block creation, *every* member order's account — has `implementation_status` other than `SUSPENDED`. Otherwise `ERR_ACCOUNT_SUSPENDED` (409). This check guards exactly ten operations: cash deposits, transfer-in booking, implementation, drift evaluation, rebalance, block creation, block allocation, harvest-proposal creation, harvest-proposal approval and harvest-proposal execution."

    PRD §2.6 rung 13: "**Restricted securities.** No `BUY` order in a block being assembled targets a security that is restricted for its account. Otherwise `ERR_SECURITY_RESTRICTED` (422). Guards block creation only."

    Design: Difficulty/priority_pair_validation_conflict/suspended_account_outranks_restricted_security_on_block_create
    """
    env = _restricted_account_world()
    suspend_account(env["account"]["id"])
    assert get_account(env["account"]["id"])["implementation_status"] == "SUSPENDED"

    response = api.create_block(
        create_block_payload([env["ceta_order"]["id"]]),
        make_sponsor_operator_headers(env["sponsor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)

    # Nothing was assembled and the member order is exactly where it was.
    order = get_trade_order(env["ceta_order"]["id"])
    assert order["status"] == "PROPOSED"
    assert order["block_id"] is None
    blocks = api.list_blocks(ADMIN)
    assert blocks.json()["meta"]["total_count"] == 0
    assert get_success_data(blocks) == []


def test_block_create_exposes_the_restricted_security_once_only_the_suspension_lifts(api):
    """PRD §2.6: "To make the API deterministic, every request is evaluated against a single fixed ladder of twenty-eight checks in ascending order, and the **first** check that fails determines the response. No later check may mask an earlier one, and no earlier check may be skipped because a later one looks more specific."

    PRD §2.6 rung 13: "**Restricted securities.** No `BUY` order in a block being assembled targets a security that is restricted for its account. Otherwise `ERR_SECURITY_RESTRICTED` (422). Guards block creation only."

    Design: Difficulty/priority_pair_validation_conflict/suspended_account_outranks_restricted_security_on_block_create
    """
    env = _restricted_account_world()
    suspend_account(env["account"]["id"])

    # Lift the suspension and nothing else — the DO_NOT_BUY restriction is still
    # ACTIVE on the same account and security.
    reinstate_account(env["account"]["id"])
    account = get_account(env["account"]["id"])
    assert account["implementation_status"] != "SUSPENDED"
    assert env["restriction"]["status"] == "ACTIVE"

    response = api.create_block(
        create_block_payload([env["ceta_order"]["id"]]),
        make_sponsor_operator_headers(env["sponsor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SECURITY_RESTRICTED.value)

    order = get_trade_order(env["ceta_order"]["id"])
    assert order["status"] == "PROPOSED"
    assert order["block_id"] is None
    assert api.list_blocks(ADMIN).json()["meta"]["total_count"] == 0


# ---------------------------------------------------------------------------
# Rung 14 (wash-sale coordination) versus rung 26 (harvest budget)
# ---------------------------------------------------------------------------
def test_harvest_proposal_reports_the_wash_window_ahead_of_the_budget(api):
    """PRD §2.6: "To make the API deterministic, every request is evaluated against a single fixed ladder of twenty-eight checks in ascending order, and the **first** check that fails determines the response. No later check may mask an earlier one, and no earlier check may be skipped because a later one looks more specific."

    PRD §2.6 rung 14: "Otherwise `ERR_WASH_SALE_WINDOW_CONFLICT` (422). This check guards two operations: harvest-proposal creation and block creation."

    PRD §2.6 rung 26: "**Harvest budget.** The account's `tax_overlay_enabled` flag is true, and its `realized_loss_ytd_cents` plus the loss figure produced by the completed disposal walk is less than or equal to its `harvest_budget_cents`. Otherwise `ERR_HARVEST_BUDGET_EXCEEDED` (422). This check guards two operations: harvest-proposal creation and harvest-proposal execution."

    Design: Difficulty/priority_pair_validation_conflict/wash_sale_lookback_outranks_harvest_budget_on_proposal_create
    """
    env = _harvest_world()
    # Exactly 30 days after the TRADE acquisition: inside the closed lookback.
    set_clock(THIRTY_DAYS_LATER_UTC)
    account = get_account(env["account"]["id"])

    # The same request would also blow the budget: disposing the 100-share lot
    # at 10000c realizes more loss than the account is allowed to book.
    response = api.create_harvest_proposal(_harvest_request(env, account), MANAGER)
    validate_error(response, ApiErrorId.ERR_WASH_SALE_WINDOW_CONFLICT.value)

    proposals = api.list_harvest_proposals(ADMIN, params={"account_id": account["id"]})
    assert proposals.json()["meta"]["total_count"] == 0
    assert get_success_data(proposals) == []


def test_harvest_proposal_exposes_the_budget_once_the_wash_window_clears(api):
    """PRD §2.10: "The **lookback clause** applies when a harvest proposal is created: the proposal is rejected when a tax lot exists for that account and security whose `origin` is `TRADE`, whose `status` is `OPEN` or `CLOSED`, and whose `open_date` falls on a date within the closed interval running from 30 days before the current clock date to 30 days after it — a purchase exactly 30 days before the proposal collides, one 31 days before does not."

    PRD §2.6 rung 26: "**Harvest budget.** The account's `tax_overlay_enabled` flag is true, and its `realized_loss_ytd_cents` plus the loss figure produced by the completed disposal walk is less than or equal to its `harvest_budget_cents`. Otherwise `ERR_HARVEST_BUDGET_EXCEEDED` (422). This check guards two operations: harvest-proposal creation and harvest-proposal execution."

    Design: Difficulty/priority_pair_validation_conflict/wash_sale_lookback_outranks_harvest_budget_on_proposal_create
    """
    env = _harvest_world()
    # One day further on: the TRADE lot now sits 31 days back and no longer
    # collides, so the identical request reaches the later rung.
    set_clock(THIRTY_ONE_DAYS_LATER_UTC)
    account = get_account(env["account"]["id"])
    assert account["realized_loss_ytd_cents"] == 0
    assert account["harvest_budget_cents"] == 150000

    response = api.create_harvest_proposal(_harvest_request(env, account), MANAGER)
    validate_error(response, ApiErrorId.ERR_HARVEST_BUDGET_EXCEEDED.value)

    # A refused proposal writes nothing at all.
    proposals = api.list_harvest_proposals(ADMIN, params={"account_id": account["id"]})
    assert proposals.json()["meta"]["total_count"] == 0
    after = get_account(account["id"])
    assert after["realized_loss_ytd_cents"] == 0
    assert after["version"] == account["version"]


# ---------------------------------------------------------------------------
# Rung 12 (referenced sibling state) versus rung 15 (window overlap)
# ---------------------------------------------------------------------------
def test_distribution_create_reports_the_unpublished_version_ahead_of_the_overlap(api):
    """PRD §2.6: "To make the API deterministic, every request is evaluated against a single fixed ladder of twenty-eight checks in ascending order, and the **first** check that fails determines the response. No later check may mask an earlier one, and no earlier check may be skipped because a later one looks more specific."

    PRD §2.6 rung 12: "**Referenced sibling state.** The referenced sibling row is in the state the operation requires. Distribution creation and distribution activation both require the referenced model version to be `PUBLISHED`, failing otherwise with `ERR_MODEL_VERSION_NOT_PUBLISHED`; an implementation requires an `ACTIVE` distribution covering the current clock instant that links the account's sponsor to the account's pending version, failing otherwise with `ERR_DISTRIBUTION_NOT_ACTIVE`. Both are HTTP 409. This check guards those three operations."

    PRD §2.6 rung 15: "**Distribution window overlap.** The new distribution's effective window does not collide with any existing `PENDING` or `ACTIVE` distribution on the same sponsor-and-model key. Otherwise `ERR_DISTRIBUTION_WINDOW_OVERLAP` (409). Guards distribution creation only."

    Design: Difficulty/priority_pair_validation_conflict/unpublished_model_version_outranks_distribution_window_overlap
    """
    env = _distribution_world()
    draft = create_draft_version(env["model"]["id"])
    assert draft["status"] == "DRAFT"

    # The request names a DRAFT version *and* collides with the PENDING window
    # already held on the same sponsor-and-model key.
    response = api.create_distribution(
        _colliding_distribution_payload(env, draft), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_MODEL_VERSION_NOT_PUBLISHED.value)


def test_distribution_create_writes_nothing_when_the_version_is_unpublished(api):
    """PRD §2.6 rung 12: "**Referenced sibling state.** The referenced sibling row is in the state the operation requires. Distribution creation and distribution activation both require the referenced model version to be `PUBLISHED`, failing otherwise with `ERR_MODEL_VERSION_NOT_PUBLISHED`; an implementation requires an `ACTIVE` distribution covering the current clock instant that links the account's sponsor to the account's pending version, failing otherwise with `ERR_DISTRIBUTION_NOT_ACTIVE`. Both are HTTP 409. This check guards those three operations."

    PRD §3.3: "On success the distribution is born in status `PENDING` with a null `activated_at` and a null `lapsed_at`, copies `model_id` from the referenced version so that the overlap key is available without a join, and raises the version's `distribution_count` by one along with the version's `version`."

    Design: Difficulty/priority_pair_validation_conflict/unpublished_model_version_outranks_distribution_window_overlap
    """
    env = _distribution_world()
    draft = create_draft_version(env["model"]["id"])

    response = api.create_distribution(
        _colliding_distribution_payload(env, draft), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_MODEL_VERSION_NOT_PUBLISHED.value)

    listing = api.list_distributions(ADMIN, params={"model_id": env["model"]["id"]})
    rows = get_success_data(listing)
    assert listing.json()["meta"]["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == env["distribution_v1"]["id"]
    assert rows[0]["model_version_id"] == env["model_version"]["id"]

    refreshed_draft = get_model_version(draft["id"])
    assert refreshed_draft["distribution_count"] == 0
    assert refreshed_draft["version"] == draft["version"]


def test_distribution_create_exposes_the_overlap_once_the_version_is_published(api):
    """PRD §2.6 rung 15: "**Distribution window overlap.** The new distribution's effective window does not collide with any existing `PENDING` or `ACTIVE` distribution on the same sponsor-and-model key. Otherwise `ERR_DISTRIBUTION_WINDOW_OVERLAP` (409). Guards distribution creation only."

    PRD §2.10: "Two windows collide when the first window's start is strictly earlier than the second's end and the second window's start is strictly earlier than the first's end, treating a null end as unbounded."

    Design: Difficulty/priority_pair_validation_conflict/unpublished_model_version_outranks_distribution_window_overlap
    """
    env = _distribution_world()
    successor = create_approved_version(
        env["model"]["id"], ALL_IN_ALFA, env["securities"]
    )
    publish_version(successor["id"])

    # Publishing lapses only ACTIVE distributions, so the PENDING one still
    # occupies the sponsor-and-model key it was created against.
    still_pending = get_success_data(
        api.get_distribution(env["distribution_v1"]["id"], ADMIN)
    )
    assert still_pending["status"] == "PENDING"

    published = get_model_version(successor["id"])
    assert published["status"] == "PUBLISHED"

    response = api.create_distribution(
        _colliding_distribution_payload(env, published), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_DISTRIBUTION_WINDOW_OVERLAP.value)

    listing = api.list_distributions(ADMIN, params={"model_id": env["model"]["id"]})
    assert listing.json()["meta"]["total_count"] == 1
