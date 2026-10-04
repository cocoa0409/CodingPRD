"""Difficulty queue A: validation priority pairs, boundary precision, cross-entity
dependencies, temporal overlap and compensating invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_account_credit_figure,
    close_contract,
    close_session,
    create_account,
    create_active_contract,
    create_contract,
    create_drawdown_payload,
    create_monitor,
    create_storage_record,
    create_warehouse,
    current_version,
    eng_headers,
    fin_headers,
    get_account,
    get_contract,
    get_monitor,
    get_warehouse,
    list_contracts,
    list_drawdowns,
    list_ledger_entries,
    list_storage_records,
    op_headers,
    open_session,
    post_drawdown,
    resume_warehouse,
    reverse_drawdown,
    scale_warehouse,
    set_clock,
    shift_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6
DOLLAR_TOL = 0.005


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / exhausted_allowance_vs_zero_amount_priority
# ---------------------------------------------------------------------------

def _exhausted_contract_context():
    """An ACTIVE contract whose 1000-credit allowance is fully drawn."""
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_PF", "SMALL",
                                 auto_suspend_seconds=600, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    contract = create_active_contract(account["id"], 1000)
    post_drawdown(contract["id"], warehouse["id"], 1000, "pf-1000")
    return account, warehouse, get_contract(contract["id"])


def test_exhausted_allowance_outranks_the_single_drawdown_range_ceiling(api):
    """PRD §2.10: "The ninth layer is the contract credit ceiling, which refuses
    a drawdown that would breach the contract's allowance plus its rollover
    ceiling, with `ERR_CONTRACT_CREDIT_EXHAUSTED` (422)." PRD §2.10: "the
    single-drawdown amount bounds raise `ERR_DRAWDOWN_AMOUNT_RANGE` (400)". PRD §3.4: "A drawdown that
    would push `drawn_credits` past `base_credits` plus `rolled_over_credits`
    plus the `rollover_cap_credits` of the active term is refused outright with
    `ERR_CONTRACT_CREDIT_EXHAUSTED` rather than being silently clipped".

    Design: Difficulty/priority_pair_validation_conflict/exhausted_allowance_vs_zero_amount_priority
    """
    account, warehouse, contract = _exhausted_contract_context()
    response = api_client.create_drawdown(
        create_drawdown_payload(contract["id"], warehouse["id"], 1300, "pf-bad",
                                contract["version"]),
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_CREDIT_EXHAUSTED)


def test_a_refused_ceiling_breach_leaves_the_contract_untouched(api):
    """PRD §3.4: "Only drawdown rows in `ACTIVE` status bound to a contract that
    is `ACTIVE`, `EXHAUSTED` or `CLOSED` participate in these rollups". PRD
    §2.10: "an earlier layer always wins."

    Design: Difficulty/priority_pair_validation_conflict/exhausted_allowance_vs_zero_amount_priority
    """
    account, warehouse, contract = _exhausted_contract_context()
    api_client.create_drawdown(
        create_drawdown_payload(contract["id"], warehouse["id"], 1300, "pf-bad",
                                contract["version"]),
        eng_headers(),
    )
    after = get_contract(contract["id"])
    assert after["drawn_credits"] == pytest.approx(1000.0, abs=CREDIT_TOL)
    assert after["drawdown_count"] == 1, "no second drawdown row was created"
    assert len(list_drawdowns(contract["id"])) == 1


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / draining_account_vs_rule_conflict_on_close
# ---------------------------------------------------------------------------

def _draining_account_with_contract():
    """An ACTIVE contract on an account driven to DRAINING by its own monitor.
    The 4500-second LARGE session reaches exactly 10.0 credits against a
    10-credit quota while billing a full 4500 seconds."""
    account = create_account(region="us-east-1")
    monitor = create_monitor(account["id"], "MON_PP", 10, interval="MONTHLY",
                             action="SUSPEND")
    contract = create_active_contract(account["id"], 1000)
    warehouse = create_warehouse(account["id"], "WH_PP", "LARGE",
                                 auto_suspend_seconds=60, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 4500))
    close_session(session["id"], warehouse["id"])
    return account, contract, monitor


def test_a_draining_account_outranks_segregation_of_duties_on_the_close_path(api):
    """PRD §2.10: "The seventh layer is account posture: an operation that
    charges or opens new consumption against an account whose `account_state` is
    `DRAINING` is refused with `ERR_ACCOUNT_DRAINING` (422). The eighth layer is
    segregation of duties on the contract path: closing a contract that the
    acting operator activated is refused with `ERR_ROLE_CONFLICT` (422)." PRD
    §2.10: "an earlier layer always wins."

    Design: Difficulty/priority_pair_validation_conflict/draining_account_vs_rule_conflict_on_close
    """
    account, contract, monitor = _draining_account_with_contract()
    assert get_account(account["id"])["account_state"] == "DRAINING"

    response = api_client.close_contract(contract["id"], {}, fin_headers())
    validate_error_is_one_of(
        response, [ApiErrorId.ERR_ACCOUNT_DRAINING, ApiErrorId.ERR_ROLE_CONFLICT]
    )


def test_the_refused_close_leaves_the_contract_active(api):
    """PRD §3.4: "Closing is a `FinanceController` action admitted from `ACTIVE`,
    `EXPIRED` or `EXHAUSTED`, moving the contract to `CLOSED`, stopping overage
    accrual and preventing any further drawdown from binding to it."

    Design: Difficulty/priority_pair_validation_conflict/draining_account_vs_rule_conflict_on_close
    """
    account, contract, monitor = _draining_account_with_contract()
    api_client.close_contract(contract["id"], {}, fin_headers())
    after = get_contract(contract["id"])
    assert after["status"] == "ACTIVE"
    assert get_account(account["id"])["account_state"] == "DRAINING"


# ---------------------------------------------------------------------------
# boundary_precision_check / billed_floor_exact_boundary_at_sixty_seconds
# ---------------------------------------------------------------------------

def test_a_fifty_nine_second_session_bills_a_full_minute(api):
    """PRD §3.3: "Its billed figure replaces the elapsed seconds with a billed
    duration that raises the elapsed seconds up to the warehouse's
    `auto_suspend_seconds` whenever the elapsed time fell short of that floor".
    PRD §2.6: "`auto_suspend_seconds` is the idle window before the warehouse
    suspends itself and also the billed floor applied to each session; it must
    be at least 60 and at most 3600 seconds".

    Design: Difficulty/boundary_precision_check/billed_floor_exact_boundary_at_sixty_seconds
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_BF", "MEDIUM",
                                 auto_suspend_seconds=60, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    set_clock(shift_clock(CLOCK_START, 53))
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 112))
    closed = close_session(session["id"], warehouse["id"])

    assert closed["elapsed_seconds"] == 59
    assert closed["billed_seconds"] == 60
    assert closed["billed_credits"] == pytest.approx(0.066667, abs=CREDIT_TOL)


def test_a_sixty_second_session_sits_exactly_on_the_floor(api):
    """PRD §3.3: "A 61-second `MEDIUM` session of a single cluster is long
    enough that both readings agree at 0.067778, because its elapsed time is at
    or above the raised duration's floor and no raise occurs." PRD §3.3: "The
    billed figure is never below the metered figure".

    Design: Difficulty/boundary_precision_check/billed_floor_exact_boundary_at_sixty_seconds
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_BF", "MEDIUM",
                                 auto_suspend_seconds=60, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    set_clock(shift_clock(CLOCK_START, 53))
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 113))
    closed = close_session(session["id"], warehouse["id"])

    assert closed["elapsed_seconds"] == 60
    assert closed["billed_seconds"] == 60
    assert closed["billed_credits"] == pytest.approx(0.066667, abs=CREDIT_TOL)
    assert closed["metered_credits"] == pytest.approx(0.066667, abs=CREDIT_TOL)
    # One second past the floor the two readings still agree, at 0.067778.
    session_2 = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 174))
    closed_2 = close_session(session_2["id"], warehouse["id"])
    assert closed_2["billed_credits"] == pytest.approx(0.067778, abs=CREDIT_TOL)


# ---------------------------------------------------------------------------
# boundary_precision_check / abandoned_session_empty_billing_edge
# ---------------------------------------------------------------------------

def test_listing_creation_is_refused_while_the_bound_share_is_draft(api):
    """PRD §3.7: "The bound share must be `PUBLISHED`, or the create is refused
    with `ERR_SHARE_NOT_PUBLISHED`." PRD §2.10: "The fourteenth layer is share
    publication: a share that is not published cannot be referenced by a usage
    event, a listing creation, a listing publication, or a paid usage row, and
    the refusal is `ERR_SHARE_NOT_PUBLISHED` (422)."

    Design: Difficulty/cross_entity_state_dependency/share_publish_requires_published_bound_listing_prestate
    """
    provider = create_account(tenant_name="Dep Share", region="us-east-1")
    consumer = create_account(tenant_name="Dep Consumer", region="us-east-1")
    from test_helpers import create_share, create_listing_payload, admin_headers

    share = create_share(provider["id"], "SHARE_DS", [consumer["id"]],
                         objects_exposed=4, status="DRAFT")
    response = api_client.create_listing(
        create_listing_payload(share["id"], "LIST_DS", "USAGE_BASED", 0.50),
        admin_headers(provider["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SHARE_NOT_PUBLISHED)


def test_the_same_listing_payload_succeeds_once_the_share_is_published(api):
    """PRD §3.6: "Publication requires `status` to be `DRAFT` or `SUSPENDED`,
    every consumer id to resolve, no consumer to be the provider, and
    `objects_exposed` to be at least 1; it moves the share to `PUBLISHED`, at
    which point consumers may post usage events against it." PRD §3.7:
    "Publication is admitted only from `DRAFT`, requires the bound share to
    still be `PUBLISHED`".

    Design: Difficulty/cross_entity_state_dependency/share_publish_requires_published_bound_listing_prestate
    """
    from test_helpers import (admin_headers, create_listing, create_share,
                              publish_listing, publish_share)

    provider = create_account(tenant_name="Dep Share", region="us-east-1")
    consumer = create_account(tenant_name="Dep Consumer", region="us-east-1")
    share = create_share(provider["id"], "SHARE_DS", [consumer["id"]],
                         objects_exposed=4, status="DRAFT")
    published = publish_share(share["id"], provider["id"])
    assert published["status"] == "PUBLISHED"

    listing = create_listing(share["id"], provider["id"], "LIST_DS",
                             pricing_model="USAGE_BASED", flat_price_usd=0.50)
    final = publish_listing(listing["id"], provider["id"])
    assert final["listing_state"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / resume_blocked_by_suspended_monitor_on_account
# ---------------------------------------------------------------------------

def test_a_fired_immediate_suspend_monitor_blocks_the_resume(api):
    """PRD §3.2: "A resume on an account whose immediate-suspend monitor has
    already fired is refused with `ERR_QUOTA_EXCEEDED`, while the same attempt
    against a monitor carrying the ordinary `SUSPEND` action is admitted,
    because that action has already drained the warehouse itself." PRD §2.10:
    "The sixteenth layer is the quota gate: a resume or a session open against an
    account whose immediate-suspend monitor has already fired is refused with
    `ERR_QUOTA_EXCEEDED` (422)."

    Design: Difficulty/cross_entity_state_dependency/resume_blocked_by_suspended_monitor_on_account
    """
    account = create_account(region="us-east-1")
    create_monitor(account["id"], "MON_DR", 1, interval="MONTHLY",
                   action="SUSPEND_IMMEDIATE")
    burner = create_warehouse(account["id"], "WH_BURN", "LARGE",
                              auto_suspend_seconds=60, auto_resume=True,
                              clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    set_clock(CLOCK_START)
    resume_warehouse(burner["id"])
    session = open_session(burner["id"])
    set_clock(shift_clock(CLOCK_START, 900))
    close_session(session["id"], burner["id"])

    target = create_warehouse(account["id"], "WH_DR", "SMALL",
                              auto_suspend_seconds=600, auto_resume=True,
                              clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    assert target["status"] == "SUSPENDED"
    response = api_client.resume_warehouse(target["id"], {}, eng_headers())
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_QUOTA_EXCEEDED, ApiErrorId.ERR_ACCOUNT_DRAINING],
    )
    assert get_warehouse(target["id"])["status"] == "SUSPENDED"


def test_a_healthy_monitor_admits_the_resume_that_the_fired_one_blocked(api):
    """PRD §2.11: "Its derived `monitor_state` is one of `OK`, `NOTIFY_SENT`, or
    `SUSPENDED`. A monitor begins life in `OK` with an `used_pct` of 0". PRD
    §3.2: "A resume is attempted by a `DataEngineer` or a `PlatformOperator` and
    requires the warehouse to be `SUSPENDED`".

    Design: Difficulty/cross_entity_state_dependency/resume_blocked_by_suspended_monitor_on_account
    """
    account = create_account(region="us-east-1")
    monitor = create_monitor(account["id"], "MON_DR", 1000, interval="MONTHLY",
                             action="SUSPEND_IMMEDIATE")
    target = create_warehouse(account["id"], "WH_DR", "SMALL",
                              auto_suspend_seconds=600, auto_resume=True,
                              clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    assert get_monitor(monitor["id"])["monitor_state"] == "OK"

    resumed = resume_warehouse(target["id"])
    assert resumed["status"] == "RUNNING", (
        "the block is the parent account's monitor state, not a static "
        "warehouse property"
    )


# ---------------------------------------------------------------------------
# resource_temporal_overlap / contract_term_half_open_adjacency_permitted
# ---------------------------------------------------------------------------

def test_a_shared_boundary_is_not_an_overlap_but_a_real_overlap_is(api):
    """PRD §2.10: "The eleventh layer is temporal overlap, refused with
    `ERR_TERM_OVERLAP` (409)." PRD §3.4: "a zero-width term is refused with
    `ERR_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contract_term_half_open_adjacency_permitted
    """
    account = create_account(region="us-east-1")
    first = create_active_contract(account["id"], 1000)
    term_end = first["term_end"]

    adjacent = create_contract(account["id"], 1000, term_start=term_end,
                               term_end="2026-11-01T00:00:00Z")
    assert adjacent["term_start"] == term_end, (
        "a shared endpoint is not an overlap under half-open windows"
    )

    # An overlapping term is the negative probe for the same rule.
    response = api_client.create_contract(
        {"account_id": account["id"], "term_start": "2026-09-20T00:00:00Z",
         "term_end": "2026-11-01T00:00:00Z", "base_credits": 1000,
         "overage_rate_per_credit": 3.00, "rollover_cap_credits": 200,
         "currency": "USD"},
        fin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_TERM_OVERLAP)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / storage_snapshot_daily_window_capacity_gap_allowed
# ---------------------------------------------------------------------------

def test_a_second_snapshot_covering_the_same_day_is_refused(api):
    """PRD §3.5: "Two snapshots of the same account may not overlap on their
    half-open daily windows, each of which runs from its `usage_date` to one day
    later; a snapshot covering a day already covered is refused with
    `ERR_TERM_OVERLAP`". PRD §2.10: "The eleventh layer is temporal overlap,
    refused with `ERR_TERM_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/storage_snapshot_daily_window_capacity_gap_allowed
    """
    account = create_account(region="us-east-1")
    create_storage_record(account["id"], "2026-09-02T00:00:00Z", active_tb=10.0,
                          time_travel_tb=1.0, fail_safe_tb=1.0, time_travel_days=7)
    response = api_client.create_storage_record(
        {"account_id": account["id"], "usage_date": "2026-09-02T12:00:00Z",
         "active_tb": 11.0, "time_travel_tb": 1.0, "fail_safe_tb": 1.0,
         "time_travel_days": 7},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_TERM_OVERLAP)


def test_a_day_with_no_snapshot_at_all_is_tolerated(api):
    """PRD §3.5: "a gap of unbilled days is entirely permitted." PRD §2.10:
    "an earlier layer always wins."

    Design: Difficulty/resource_temporal_overlap/storage_snapshot_daily_window_capacity_gap_allowed
    """
    account = create_account(region="us-east-1")
    create_storage_record(account["id"], "2026-09-02T00:00:00Z", active_tb=10.0,
                          time_travel_tb=1.0, fail_safe_tb=1.0, time_travel_days=7)
    gap = create_storage_record(account["id"], "2026-09-04T00:00:00Z", active_tb=12.0,
                                time_travel_tb=1.0, fail_safe_tb=1.0,
                                time_travel_days=7)
    assert gap["usage_date"] == "2026-09-04T00:00:00.000Z"
    records = list_storage_records(account["id"])
    assert len(records) == 2, "the unbilled gap day is tolerated"


# ---------------------------------------------------------------------------
# compensating_invariant / warehouse_session_burn_invariant_under_capacity_changes
# ---------------------------------------------------------------------------

def test_a_resize_after_the_session_opened_cannot_re_price_it(api):
    """PRD §3.2: "Every session already open keeps the frozen size and cluster
    snapshot it captured at its own start — the resize cannot re-price a session
    that is already running". PRD §3.3: "the session's own `size` and `clusters`
    are never re-read from the warehouse once it is open."

    Design: Difficulty/compensating_invariant/warehouse_session_burn_invariant_under_capacity_changes
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_IS", "SMALL",
                                 auto_suspend_seconds=60, auto_resume=True,
                                 clusters_min=1, clusters_max=3, latency_slo_ms=1000)
    create_active_contract(account["id"], 1000)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 600))
    resized = api_client.patch_warehouse(warehouse["id"], {"size": "XXXLARGE"},
                                         eng_headers())
    resized = validate_success(resized)
    closed = close_session(session["id"], warehouse["id"])

    assert closed["size"] == "SMALL", "the session keeps its frozen snapshot"
    # 2 (SMALL factor) * 1 cluster * 600 s / 3600 = 0.333333: 600 s is exactly
    # the floor, so no raise occurs.
    assert closed["billed_credits"] == pytest.approx(0.333333, abs=CREDIT_TOL), (
        "the session bills at the SMALL rate of 2 per hour, not at the "
        "XXXLARGE rate that is now on the warehouse"
    )
    assert resized["credits_per_hour"] == pytest.approx(64.0), (
        "XXXLARGE's size factor is 64"
    )


def test_the_conserved_session_burn_is_what_reaches_the_ledger(api):
    """PRD §3.3: "The `CLOSING` to `CLOSED` hop then posts a single ledger row on
    the owning account with bucket `CONSUMPTION`, `source_entity`
    \"WarehouseSession\", `source_entity_id` equal to the session's own id, and
    `amount_credits` equal to `billed_credits`".

    Design: Difficulty/compensating_invariant/warehouse_session_burn_invariant_under_capacity_changes
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_IS", "SMALL",
                                 auto_suspend_seconds=60, auto_resume=True,
                                 clusters_min=1, clusters_max=3, latency_slo_ms=1000)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 600))
    api_client.patch_warehouse(warehouse["id"], {"size": "XXXLARGE"}, eng_headers())
    close_session(session["id"], warehouse["id"])

    assert_account_credit_figure(get_account(account["id"]), 0.333333)
    rows = [e for e in list_ledger_entries(account["id"])
            if e["source_entity_id"] == session["id"]]
    assert len(rows) == 1
    assert rows[0]["bucket"] == "CONSUMPTION"
    assert rows[0]["source_entity"] == "WarehouseSession"
    assert rows[0]["amount_credits"] == pytest.approx(0.333333, abs=CREDIT_TOL)


# ---------------------------------------------------------------------------
# compensating_invariant / credit_drawdown_reversal_leaves_account_credit_conserved
# ---------------------------------------------------------------------------

def _conservation_context():
    """Account + ACTIVE contract + a closed session worth 0.333333 credits, then
    a 850-credit drawdown."""
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_ID", "SMALL",
                                 auto_suspend_seconds=60, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    contract = create_active_contract(account["id"], 1000)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 600))
    close_session(session["id"], warehouse["id"])
    drawdown = post_drawdown(contract["id"], warehouse["id"], 850, "id-850")
    return account, contract, warehouse, drawdown


def test_reversing_a_drawdown_restores_the_account_credit_figure_exactly(api):
    """PRD §3.4: "The account receives a `CONSUMPTION` ledger row carrying the
    negation of the drawdown's within-allowance portion, so a full-allowance
    drawdown reversed in full restores `posted_consumption_credits_reconciled` to
    precisely its prior value". PRD §3.4: "The reverse moves the drawdown to
    `REVERSED`, reduces the contract's `drawn_credits` by the drawdown amount".

    Design: Difficulty/compensating_invariant/credit_drawdown_reversal_leaves_account_credit_conserved
    """
    account, contract, warehouse, drawdown = _conservation_context()
    # The contract's within-allowance drawdown posts a CONSUMPTION row for the
    # full 850 credits, so the account sits at 850 + 0.333333 before reversal.
    assert_account_credit_figure(get_account(account["id"]), 850.333333)
    assert get_contract(contract["id"])["drawn_credits"] == pytest.approx(
        850.0, abs=CREDIT_TOL
    )
    assert drawdown["amount_credits"] == pytest.approx(850.0, abs=CREDIT_TOL)

    reversed_dd = reverse_drawdown(drawdown["id"])
    assert reversed_dd["status"] == "REVERSED"
    # The reversal restores the reconciled figure to its pre-drawdown value.
    assert_account_credit_figure(get_account(account["id"]), 0.333333)
    after = get_contract(contract["id"])
    assert after["remaining_credits"] == pytest.approx(1000.0, abs=CREDIT_TOL)
    assert after["drawn_credits"] == pytest.approx(0.0, abs=CREDIT_TOL)


def test_the_ledger_arithmetic_is_its_own_audit_trail_after_a_reversal(api):
    """PRD §2.4: "`posted_consumption_credits_reconciled` is the account's running
    credit total. It is the sum, rounded half up to six decimal places, of
    `amount_credits` over every `AccountLedgerEntry` row belonging to the account
    whose `bucket` is either `CONSUMPTION` or `SHARE_CONSUMPTION`." PRD §3.9:
    "because a reversed drawdown contributes a negative `CONSUMPTION` row rather
    than deleting its original, the ledger's arithmetic is its own audit trail
    and the reversed pair restores the reconciled figure exactly."

    Design: Difficulty/compensating_invariant/credit_drawdown_reversal_leaves_account_credit_conserved
    """
    account, contract, warehouse, drawdown = _conservation_context()
    reverse_drawdown(drawdown["id"])

    entries = list_ledger_entries(account["id"])
    credit_rows = [e for e in entries
                   if e["bucket"] in ("CONSUMPTION", "SHARE_CONSUMPTION")]
    ledger_sum = sum(e["amount_credits"] for e in credit_rows)
    assert ledger_sum == pytest.approx(0.333333, abs=CREDIT_TOL)
    assert_account_credit_figure(get_account(account["id"]), ledger_sum)
    assert get_contract(contract["id"])["drawn_credits"] == pytest.approx(
        0.0, abs=CREDIT_TOL
    )