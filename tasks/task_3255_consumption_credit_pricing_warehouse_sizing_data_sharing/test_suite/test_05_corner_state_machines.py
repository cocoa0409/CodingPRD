"""Corner queue B: state-machine claims."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    close_contract,
    close_session,
    create_account,
    create_active_contract,
    create_listing,
    create_published_listing,
    create_share,
    create_warehouse,
    current_version,
    eng_headers,
    fin_headers,
    get_account,
    get_contract,
    get_listing,
    get_share,
    get_warehouse,
    list_ledger_entries,
    open_session,
    publish_listing,
    publish_share,
    renew_contract,
    resume_warehouse,
    scale_warehouse,
    set_clock,
    shift_clock,
    suspend_share,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_listing,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6


def test_a_new_warehouse_starts_suspended_with_no_clusters(api):
    """PRD §2.6: "A new warehouse is created in `SUSPENDED` with a
    `cluster_count` of 0. Reaching `RUNNING` always resets `cluster_count` to
    `clusters_min`".

    Design: Corner/state_machines/new_warehouse_starts_suspended_with_no_clusters
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_INI", "MEDIUM",
                                 clusters_min=2, clusters_max=4)
    assert warehouse["status"] == "SUSPENDED"
    assert warehouse["cluster_count"] == 0

    resumed = resume_warehouse(warehouse["id"])
    assert resumed["status"] == "RUNNING"
    assert resumed["cluster_count"] == 2, "the first resume sets clusters_min"


def test_a_closed_contract_refuses_renewal_on_the_state_gate(api):
    """PRD §3.4: "Closing is a `FinanceController` action admitted from `ACTIVE`,
    `EXPIRED` or `EXHAUSTED`, moving the contract to `CLOSED`, stopping overage
    accrual and preventing any further drawdown from binding to it." PRD §3.4:
    "Renewal by a `FinanceController` is admitted only from `EXPIRED`".

    Design: Corner/state_machines/closed_contract_rejects_renewal
    """
    account = create_account(region="us-east-1")
    contract = create_active_contract(account["id"], 1000)
    close_contract(contract["id"], fin_headers("fin-other-7"), {})

    response = api_client.renew_contract(
        contract["id"],
        {"new_term_start": "2026-10-01T00:00:00Z",
         "new_term_end": "2026-11-01T00:00:00Z", "base_credits": 1000},
        fin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_contract(contract["id"])["status"] == "CLOSED"


def test_a_closed_contract_cannot_be_renewed_even_with_a_valid_window(api):
    """PRD §2.10: "The sixth layer is the state gate: the target resource must be
    in a state that admits the requested transition, and a violation yields
    `ERR_INVALID_STATE` (409)." PRD §2.10: "an earlier layer always wins."

    Design: Corner/state_machines/closed_contract_rejects_renewal
    """
    account = create_account(region="us-east-1")
    contract = create_active_contract(account["id"], 1000)
    close_contract(contract["id"], fin_headers("fin-other-8"), {})
    # The renewal window itself is perfectly valid: adjacent, non-overlapping.
    before = get_contract(contract["id"])
    response = api_client.renew_contract(
        contract["id"],
        {"new_term_start": before["term_end"],
         "new_term_end": "2026-11-01T00:00:00Z", "base_credits": 1000},
        fin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_contract(contract["id"])["status"] == "CLOSED"


def test_a_second_close_of_a_settled_session_is_refused(api):
    """PRD §3.3: "The session must be `OPEN`; a second close of an already
    `CLOSED` session is refused with `ERR_SESSION_NOT_OPEN` rather than silently
    ignored."

    Design: Corner/state_machines/second_close_of_settled_session_is_refused
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_DBL", "SMALL",
                                 auto_suspend_seconds=600)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 120))
    first = close_session(session["id"], warehouse["id"])
    assert first["state"] == "CLOSED"

    response = api_client.close_session(
        session["id"], {"expected_warehouse_version": current_version(warehouse["id"])},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SESSION_NOT_OPEN)


def test_a_refused_second_close_posts_nothing_extra(api):
    """PRD §3.3: "The `CLOSING` to `CLOSED` hop then posts a single ledger row on
    the owning account with bucket `CONSUMPTION`". PRD §3.3: "a second close of
    an already `CLOSED` session is refused with `ERR_SESSION_NOT_OPEN`".

    Design: Corner/state_machines/second_close_of_settled_session_is_refused
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_DBL", "SMALL",
                                 auto_suspend_seconds=600)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 120))
    closed = close_session(session["id"], warehouse["id"])
    api_client.close_session(
        session["id"], {"expected_warehouse_version": current_version(warehouse["id"])},
        eng_headers(),
    )
    rows = [e for e in list_ledger_entries(account["id"])
            if e["source_entity_id"] == session["id"]]
    assert len(rows) == 1, "the refused second close posts nothing"
    assert rows[0]["amount_credits"] == pytest.approx(closed["billed_credits"],
                                                      abs=CREDIT_TOL)


def test_scaling_a_suspended_warehouse_is_refused(api):
    """PRD §3.2: "it lands on a warehouse whose `status` is `RUNNING` or
    `RESIZING`; any other lifecycle state rejects the request with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/scaling_a_suspended_warehouse_is_refused
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_PC", "LARGE",
                                 clusters_min=1, clusters_max=4)
    response = api_client.scale_warehouse(
        warehouse["id"],
        {"clusters": 3, "queued_queries": 24,
         "expected_warehouse_version": current_version(warehouse["id"])},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    after = get_warehouse(warehouse["id"])
    assert after["cluster_count"] == 0
    assert after["status"] == "SUSPENDED"


def test_a_session_close_posts_exactly_one_consumption_row(api):
    """PRD §3.3: "The `CLOSING` to `CLOSED` hop then posts a single ledger row on
    the owning account with bucket `CONSUMPTION`, `source_entity`
    \"WarehouseSession\", `source_entity_id` equal to the session's own id, and
    `amount_credits` equal to `billed_credits`". PRD §2.7: "Both figures are
    rounded half up to six decimals, applied once per session at close rather
    than summed over sessions and rounded at the end".

    Design: Corner/state_machines/session_close_posts_exactly_one_consumption_row
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_SE", "LARGE",
                                 auto_suspend_seconds=60, clusters_min=1,
                                 clusters_max=4)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    scale_warehouse(warehouse["id"], clusters=3, queued_queries=24)
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 900))
    closed = close_session(session["id"], warehouse["id"])

    assert closed["size"] == "LARGE"
    assert closed["clusters"] == 3
    assert closed["billed_credits"] == pytest.approx(6.0, abs=CREDIT_TOL)
    rows = [e for e in list_ledger_entries(account["id"])
            if e["source_entity_id"] == session["id"]]
    assert len(rows) == 1, "exactly one CONSUMPTION row for the close"
    assert rows[0]["bucket"] == "CONSUMPTION"
    assert rows[0]["source_entity"] == "WarehouseSession"
    assert rows[0]["amount_credits"] == pytest.approx(6.0, abs=CREDIT_TOL)
    assert pytest.approx(get_account(account["id"])[
        "posted_consumption_credits_reconciled"
    ], CREDIT_TOL) == 6.0


def test_re_publishing_a_suspended_share_preserves_its_consumer_list(api):
    """PRD §3.6: "Re-publication from `SUSPENDED` returns the share to
    `PUBLISHED` and preserves the consumer list that was in force at suspend
    time unchanged." PRD §3.6: "Suspension is admitted only from `PUBLISHED` and
    moves the share to `SUSPENDED`".

    Design: Corner/state_machines/share_republish_preserves_consumer_list
    """
    provider = create_account(tenant_name="Corp Repub P", region="us-east-1")
    consumer = create_account(tenant_name="Corp Repub C", region="us-east-1")
    share = create_share(provider["id"], "SHARE_RP", [consumer["id"]],
                         objects_exposed=3)
    publish_share(share["id"], provider["id"])
    suspend_share(share["id"], provider["id"])
    republished = publish_share(share["id"], provider["id"])

    assert republished["status"] == "PUBLISHED"
    assert republished["consumer_account_ids"] == [consumer["id"]]
    assert republished["consumer_query_count"] == 0
    assert republished["consumer_credits"] == pytest.approx(0.0, abs=CREDIT_TOL)


def test_a_withdrawn_listing_refuses_a_second_withdrawal(api):
    """PRD §3.7: "Withdrawal from `PUBLISHED` moves the listing to `WITHDRAWN`,
    freezes `provider_payout_usd` and `platform_fee_usd` at their current values
    with the earnings remaining payable, and prevents any further paid usage row
    from binding". PRD §3.7: "Publication is admitted only from `DRAFT`".

    Design: Corner/state_machines/listing_withdraw_twice_is_refused
    """
    provider = create_account(tenant_name="Corp W2 P", region="us-east-1")
    consumer = create_account(tenant_name="Corp W2 C", region="us-east-1")
    share = create_share(provider["id"], "SHARE_W2", [consumer["id"]],
                         objects_exposed=2)
    publish_share(share["id"], provider["id"])
    listing = create_listing(share["id"], provider["id"], "LIST_W2",
                             pricing_model="FLAT", flat_price_usd=100.00)
    publish_listing(listing["id"], provider["id"])
    withdrawn = withdraw_listing(listing["id"], provider["id"])
    assert withdrawn["listing_state"] == "WITHDRAWN"

    response = api_client.withdraw_listing(listing["id"], admin_headers(provider["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    after = get_listing(listing["id"], provider["id"])
    assert after["listing_state"] == "WITHDRAWN"
    assert after["provider_payout_usd"] == pytest.approx(0.0, abs=0.005)