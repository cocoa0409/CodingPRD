"""Customer accounts: parallel state dimensions, order confirm credit gate,
OCC, stale-vs-blocked priority (PRD §3.9, §2.8, §2.7)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    set_clock, make_mill, make_grade, make_account, make_order, publish_index,
    confirm_order, get_account, get_order,
)

PM = TEST_USERS["plant_manager_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_account_parallel_credit_and_priority_dimensions():
    """PRD §3.9: "The account carries two parallel state dimensions that evolve
    independently through the same patch capability. On the credit dimension, `GOOD`
    may move to `WATCH`, `WATCH` back to `GOOD` or onward to `BLOCKED`, and `BLOCKED`
    back to `WATCH` — there is no direct `GOOD`-to-`BLOCKED` jump and no exit from
    the dimension. On the priority dimension, `STANDARD` and `STRATEGIC` swap freely.
    The patch body may carry `credit_status`, `allocation_priority`, or both, and
    each applied change bumps the account's `version` by 1."

    Design: Difficulty/non_linear_state_machine/customer_account_parallel_credit_and_priority_dimensions
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    acct = make_account(mill["id"], name="Midwest Erectors", market="CONSTRUCTION",
                        pricing_mode="SPOT")
    assert acct["credit_status"] == "GOOD"
    assert acct["allocation_priority"] == "STANDARD"

    p1 = validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "WATCH"}, AM), 200)
    assert p1["credit_status"] == "WATCH"
    assert p1["allocation_priority"] == "STANDARD"

    p2 = validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"allocation_priority": "STRATEGIC"}, AM), 200)
    assert p2["allocation_priority"] == "STRATEGIC"
    assert p2["credit_status"] == "WATCH"

    p3 = validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "GOOD"}, AM), 200)
    assert p3["credit_status"] == "GOOD"
    assert p3["allocation_priority"] == "STRATEGIC"
    assert p3["version"] == 4  # creation + three applied changes


def test_account_dimensions_survive_credit_repair():
    """PRD §3.9: "On the credit dimension, `GOOD` may move to `WATCH`, `WATCH` back
    to `GOOD` or onward to `BLOCKED`, and `BLOCKED` back to `WATCH` — there is no
    direct `GOOD`-to-`BLOCKED` jump and no exit from the dimension. On the priority
    dimension, `STANDARD` and `STRATEGIC` swap freely."

    Design: Difficulty/non_linear_state_machine/customer_account_parallel_credit_and_priority_dimensions
    """
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    acct = make_account(mill["id"], name="Midwest Erectors", market="CONSTRUCTION",
                        pricing_mode="SPOT")
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"allocation_priority": "STRATEGIC"}, AM), 200)
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "WATCH"}, AM), 200)
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "BLOCKED"}, AM), 200)
    repaired = validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "WATCH"}, AM), 200)
    # Priority dimension is untouched by the credit round-trip.
    assert repaired["credit_status"] == "WATCH"
    assert repaired["allocation_priority"] == "STRATEGIC"


def _setup_quotable_order(pricing_mode="SPOT", account_name="Watch List Erectors"):
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-09",
                  price_per_ton_cents=38000)
    grade = make_grade(mill["id"], grade_code="GR40")
    acct = make_account(mill["id"], name=account_name, market="CONSTRUCTION",
                        pricing_mode=pricing_mode)
    order = make_order(mill["id"], acct["id"], grade["id"], tons=5,
                       fulfillment_month="2026-09", base_price_cents_per_ton=25000)
    return mill, grade, acct, order


def test_order_confirm_succeeds_on_watch_account():
    """PRD §3.9: "Beyond the state and concurrency checks, confirmation is gated on
    credit and posture: the account's `credit_status` must not be `BLOCKED` — else
    `ERR_ACCOUNT_BLOCKED` (HTTP 402)"

    Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_account_credit
    """
    mill, grade, acct, order = _setup_quotable_order()
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "WATCH"}, AM), 200)

    confirmed = confirm_order(mill["id"], acct["id"], order)
    assert confirmed["status"] == "CONFIRMED"


def test_order_confirm_blocked_account_rejected():
    """PRD §3.9: "the account's `credit_status` must not be `BLOCKED` — else
    `ERR_ACCOUNT_BLOCKED` (HTTP 402)"

    Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_account_credit
    """
    mill, grade, acct, order = _setup_quotable_order()
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "WATCH"}, AM), 200)
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "BLOCKED"}, AM), 200)

    resp = api_client.confirm_order(
        mill["id"], acct["id"], order["id"],
        {"expected_order_version": order["version"]}, AM)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_BLOCKED, 402)
    assert get_order(mill["id"], order["id"])["status"] == "QUOTED"


def test_order_confirm_stale_version_412():
    """PRD §2.8: "Confirming an order requires a non-optional `expected_order_version`
    field in the request body, carrying the client's last observed `version` of that
    order; if the order's current `version` differs — because another writer advanced
    it since the client last read — the confirm is rejected with `ERR_STALE_VERSION`
    (HTTP 412), so a second confirm issued against a stale view cannot silently
    double-stamp the price."

    Design: Corner/complexity_layers/order_confirm_stale_version_412
    """
    mill, grade, acct, order = _setup_quotable_order(pricing_mode="CONTRACT")
    first = confirm_order(mill["id"], acct["id"], order)
    assert first["status"] == "CONFIRMED"
    assert first["version"] == 2

    stale = api_client.confirm_order(
        mill["id"], acct["id"], order["id"],
        {"expected_order_version": order["version"]}, AM)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_order(mill["id"], order["id"])["version"] == 2


def test_stale_version_beats_account_blocked_on_confirm():
    """PRD §2.7: "(6) optimistic concurrency mismatches yield `ERR_STALE_VERSION`"
    PRD §2.7: "(17) blocked accounts yield `ERR_ACCOUNT_BLOCKED`"
    PRD §2.7: "A request failing two checks at different priorities surfaces the
    earlier one."

    Design: Difficulty/priority_pair_validation_conflict/credit_fiscal_beats_nothing_but_blocked_vs_stale_version
    """
    mill, grade, acct, order = _setup_quotable_order(account_name="Shaky Credit Erectors")
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "WATCH"}, AM), 200)
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "BLOCKED"}, AM), 200)

    # Stale OCC (order.version is 1; we send 0) on a BLOCKED account: the earlier
    # priority (6, OCC) must surface, not the later fiscal block (17).
    resp = api_client.confirm_order(
        mill["id"], acct["id"], order["id"],
        {"expected_order_version": order["version"] - 1}, AM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_order(mill["id"], order["id"])["status"] == "QUOTED"


def test_blocked_account_alone_yields_account_blocked():
    """PRD §3.9: "the account's `credit_status` must not be `BLOCKED` — else
    `ERR_ACCOUNT_BLOCKED` (HTTP 402)"

    Design: Difficulty/priority_pair_validation_conflict/credit_fiscal_beats_nothing_but_blocked_vs_stale_version
    """
    mill, grade, acct, order = _setup_quotable_order(account_name="Shaky Credit Erectors")
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "WATCH"}, AM), 200)
    validate_success(api_client.patch_account(
        mill["id"], acct["id"], {"credit_status": "BLOCKED"}, AM), 200)

    # Same scenario with the CORRECT version: only the fiscal gate can fire.
    resp = api_client.confirm_order(
        mill["id"], acct["id"], order["id"],
        {"expected_order_version": order["version"]}, AM)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_BLOCKED, 402)
    assert get_order(mill["id"], order["id"])["status"] == "QUOTED"
