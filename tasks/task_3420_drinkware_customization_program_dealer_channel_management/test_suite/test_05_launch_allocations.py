"""Launch allocations: request gates, the lock-time distribution, forfeiture
(PRD section 3.4).

Multi-dealer setups share one inspector (fi-1) with staggered site-visit
windows honoring the 60-minute travel buffer, and advance the logical clock
monotonically (record all inspections at the latest window end).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    boot_clock,
    create_allocation_request,
    create_authorized_dealer,
    create_open_application,
    create_probation_dealer,
    decide_application,
    get_allocation,
    get_drop,
    get_dealer,
    make_channel_manager_headers,
    make_dealer_headers,
    record_inspection,
    resolve_case_confirmed,
    create_enforcement_case,
    schedule_inspection,
    set_clock,
    setup_allocated_dealer,
    setup_open_drop,
    create_product_line,
    create_colorway_drop,
    verify_documents,
    validate_error,
    validate_paginated,
    validate_success,
    assert_drop_unit_ledger_invariant,
    TEST_USERS,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_CM = TEST_USERS["channel_manager_headers"]


def _authorize_dealers(specs):
    """Authorize several dealers in one monotonic clock run.

    specs: list of (dealer_overrides, brand_score, window_start, window_end).
    Returns the refreshed AUTHORIZED dealer dicts in spec order.
    """
    pairs = []
    for dealer_overrides, _brand, window_start, window_end in specs:
        pair = create_open_application(dealer_overrides=dealer_overrides)
        schedule_inspection(pair["application"]["id"], inspector_id="fi-1",
                            window_start=window_start, window_end=window_end)
        pairs.append(pair)
    set_clock(max(spec[3] for spec in specs))
    dealers = []
    for (pair, (_d, brand, _ws, _we)) in zip(pairs, specs):
        app_id = pair["application"]["id"]
        record_inspection(app_id, inspector_id="fi-1", outcome="PASSED",
                          brand_presentation_score=brand)
        verify_documents(app_id, reviewer_id="cm-docs")
        decide_application(app_id, decider_id="cm-1", decision="APPROVE")
        dealers.append(get_dealer(pair["dealer"]["id"]))
    return dealers


def _read_drop_version(drop_id):
    return get_drop(drop_id)["version"]


def test_launch_allocation_floor_then_cap_then_largest_remainder(api):
    """Oversubscribed pool: raw shares are floored first, capped at the
    request second, and the single leftover unit goes out in fractional-part
    order — C (frac .55) beats B (frac .03) despite B's higher score.

    PRD section 3.4: "the base grant is the request's `requested_units` capped
    above by the raw share rounded down to a whole unit — floor first, then
    cap, never the other order; and the leftover pool then goes out in repeated
    passes over the candidates whose base grant is still below their request,
    ranked by the fractional part of the raw share descending, then
    `allocation_score` descending, then the allocation's `created_at`
    ascending, granting one unit per candidate per pass until the leftover is
    exhausted or no candidate can take more, with any residue staying
    unallocated."

    Design: Difficulty/combinatorial_formula/launch_allocation_floor_then_cap_then_largest_remainder
    """
    boot_clock()
    # Scores (STANDARD season): A 0.5*20+0.3*70+2*5=41, B 0.5*20+0.3*70+2*4=39,
    # C 0.5*0+0.3*70+2*0=21. Weights 41/39/21 on a 70-unit pool give raw shares
    # 28.41/27.02/14.55 -> floors 28/27/14 (A capped at its request of 28),
    # leftover 1 to C by fractional part. Final: 28/27/15.
    dealer_a, dealer_b, dealer_c = _authorize_dealers([
        ({"legal_name": "Alpine Outfitters", "sell_through_pct": 20,
          "tenure_years": 5}, 70, "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"),
        ({"legal_name": "Basin Sports", "sell_through_pct": 20,
          "tenure_years": 4}, 70, "2026-09-02T11:00:00Z", "2026-09-02T12:00:00Z"),
        ({"legal_name": "Canyon Supply", "sell_through_pct": 0,
          "tenure_years": 0}, 70, "2026-09-02T13:00:00Z", "2026-09-02T14:00:00Z"),
    ])
    line = create_product_line(name="Rambler 26 oz", base_sku="RAM26",
                               base_custom_price_cents=3200,
                               map_price_cents=3799, min_custom_quantity=24)
    drop = create_colorway_drop(
        line["id"], color_name="Canopy Green", pantone_code="PMS 350",
        drop_type="LIMITED_EDITION", total_units=100, dtc_reserved_units=30,
        dealer_unit_price_cents=2000,
        allocation_closes_at="2026-09-10T00:00:00Z",
        go_live_at="2026-12-01T00:00:00Z")

    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop["id"], _ADMIN))
    alloc_a = create_allocation_request(dealer_a["id"], drop["id"], 28)
    alloc_b = create_allocation_request(dealer_b["id"], drop["id"], 50)
    alloc_c = create_allocation_request(dealer_c["id"], drop["id"], 50)
    version_at_requests = _read_drop_version(drop["id"])
    set_clock("2026-09-11T00:00:00Z")

    locked = validate_success(api.lock_allocation(
        drop["id"], {"expected_drop_version": version_at_requests}, _ADMIN))
    assert locked["status"] == "ALLOCATION_LOCKED"

    a, b, c = (get_allocation(x["id"]) for x in (alloc_a, alloc_b, alloc_c))
    assert a["status"] == "ALLOCATED" and a["allocated_units"] == 28
    assert b["status"] == "ALLOCATED" and b["allocated_units"] == 27, \
        "B keeps its floor; its fractional part 0.03 loses the leftover to C"
    assert c["status"] == "ALLOCATED" and c["allocated_units"] == 15, \
        "floor 14 + the single leftover unit"

    drop_after = get_drop(drop["id"])
    assert drop_after["dealer_committed_units"] == 70
    assert drop_after["unallocated_units"] == 0
    assert_drop_unit_ledger_invariant(drop_after)


def test_lock_excludes_probation_dealer_from_eligible_set(api):
    """Eligibility is read at lock time: a dealer who requested while
    AUTHORIZED but sits at PROBATION by lock expires with 0 units.

    PRD section 3.4: "Every request whose dealer is not `AUTHORIZED` at lock
    time expires into `EXPIRED`."

    Design: Corner/calculations/lock_excludes_probation_dealer_from_eligible_set
    """
    boot_clock()
    dealer_p, dealer_q = _authorize_dealers([
        ({"legal_name": "Standard Dealer Co", "sell_through_pct": 50,
          "tenure_years": 5}, 85, "2026-09-02T09:00:00Z", "2026-09-02T11:00:00Z"),
        ({"legal_name": "Healthy Dealer Co", "sell_through_pct": 60,
          "tenure_years": 6}, 85, "2026-09-02T12:00:00Z", "2026-09-02T13:00:00Z"),
    ])
    line = create_product_line()
    drop = create_colorway_drop(
        line["id"], color_name="Probation Drop", pantone_code="PMS 180",
        total_units=60, dtc_reserved_units=0, dealer_unit_price_cents=1000,
        allocation_closes_at="2026-09-10T00:00:00Z",
        go_live_at="2026-12-01T00:00:00Z")

    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop["id"], _ADMIN))
    alloc_p = create_allocation_request(dealer_p["id"], drop["id"], 20)
    alloc_q = create_allocation_request(dealer_q["id"], drop["id"], 20)

    # P falls to PROBATION (4 + 4 = 8 points) before the lock.
    set_clock("2026-09-07T00:00:00Z")
    for i in (1, 2):
        case = create_enforcement_case(matched_dealer_id=dealer_p["id"],
                                       seller_handle=f"pq-{i}",
                                       listing_url=f"https://m.example/i/pq{i}")
        resolve_case_confirmed(case["id"], dealer_p["id"], "MAP_VIOLATION")
    assert get_dealer(dealer_p["id"])["status"] == "PROBATION"

    set_clock("2026-09-11T00:00:00Z")
    validate_success(api.lock_allocation(
        drop["id"], {"expected_drop_version": _read_drop_version(drop["id"])},
        _ADMIN))

    p = get_allocation(alloc_p["id"])
    q = get_allocation(alloc_q["id"])
    assert p["status"] == "EXPIRED" and p["allocated_units"] == 0
    assert q["status"] == "ALLOCATED" and q["allocated_units"] == 20
    drop_after = get_drop(drop["id"])
    assert drop_after["dealer_committed_units"] == 20
    assert drop_after["unallocated_units"] == 40


def test_remainder_tie_breaks_by_score_then_created_at(api):
    """Identical scores and identical raw shares tie on fractional part and
    score; the leftover unit goes to the earlier-created allocation.

    PRD section 3.4: "ranked by the fractional part of the raw share
    descending, then `allocation_score` descending, then the allocation's
    `created_at` ascending, granting one unit per candidate per pass until the
    leftover is exhausted or no candidate can take more"

    Design: Corner/calculations/remainder_tie_breaks_by_score_then_created_at
    """
    boot_clock()
    # Identical metrics -> identical STANDARD scores 0.5*50+0.3*85+2*5 = 60.5.
    dealer_t1, dealer_t2 = _authorize_dealers([
        ({"legal_name": "Twin Dealer One", "sell_through_pct": 50,
          "tenure_years": 5}, 85, "2026-09-02T09:00:00Z", "2026-09-02T11:00:00Z"),
        ({"legal_name": "Twin Dealer Two", "sell_through_pct": 50,
          "tenure_years": 5}, 85, "2026-09-02T13:00:00Z", "2026-09-02T14:00:00Z"),
    ])
    line = create_product_line()
    drop = create_colorway_drop(
        line["id"], color_name="Tiebreak Tan", pantone_code="PMS 468",
        drop_type="LIMITED_EDITION", total_units=21, dtc_reserved_units=0,
        dealer_unit_price_cents=1000,
        allocation_closes_at="2026-09-10T00:00:00Z",
        go_live_at="2026-12-01T00:00:00Z")

    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop["id"], _ADMIN))
    # T1's request is created first; raw shares tie at 10.5 each on pool 21.
    alloc_t1 = create_allocation_request(dealer_t1["id"], drop["id"], 20)
    alloc_t2 = create_allocation_request(dealer_t2["id"], drop["id"], 20)
    set_clock("2026-09-11T00:00:00Z")
    validate_success(api.lock_allocation(
        drop["id"], {"expected_drop_version": _read_drop_version(drop["id"])},
        _ADMIN))

    t1 = get_allocation(alloc_t1["id"])
    t2 = get_allocation(alloc_t2["id"])
    assert t1["allocated_units"] == 11, "floors 10+10, leftover 1 to earlier created_at"
    assert t2["allocated_units"] == 10
    drop_after = get_drop(drop["id"])
    assert drop_after["dealer_committed_units"] == 21
    assert drop_after["unallocated_units"] == 0


def test_probation_dealer_blocked_from_allocation_request(api):
    """A dealer at exactly 8 points (PROBATION) is rejected even though the
    drop is open and credit would pass.

    PRD section 3.4: "The dealer must be `AUTHORIZED`; a request from a
    `PENDING`, `PROBATION`, `SUSPENDED`, or `TERMINATED` dealer is rejected
    with `ERR_DEALER_NOT_AUTHORIZED`."

    Design: Difficulty/cross_entity_state_dependency/probation_dealer_blocked_from_allocation_request
    """
    pair = create_probation_dealer()  # 4 + 4 = 8 points -> PROBATION
    dealer = pair["dealer"]
    assert dealer["status"] == "PROBATION" and dealer["infraction_points"] == 8

    opened = setup_open_drop(
        drop_overrides={"color_name": "Probation Pink", "pantone_code": "PMS 210",
                        "total_units": 40, "dtc_reserved_units": 10,
                        "dealer_unit_price_cents": 2000})
    drop = opened["drop"]

    resp = api.create_launch_allocation(
        {"dealer_id": dealer["id"], "drop_id": drop["id"], "requested_units": 5},
        make_dealer_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_DEALER_NOT_AUTHORIZED)

    rows, meta = validate_paginated(api.list_launch_allocations(
        _ADMIN, params={"dealer_id": dealer["id"]}))
    assert len(rows) == 0 and meta["total_count"] == 0, \
        "no REQUESTED row persisted"


def test_credit_limit_boundary_inclusive(api):
    """The credit gate is 'must not exceed': projected 12000 > 10000 is
    rejected while exactly 10000 == the limit is accepted.

    PRD section 3.4: "the dealer's `outstanding_balance_cents` — the sum of
    `allocated_units` times `unit_price_cents` across the dealer's allocations
    currently in `ALLOCATED` — plus the requested units times the drop's
    `dealer_unit_price_cents` must not exceed the dealer's
    `credit_limit_cents`, failing with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/credit_limit_boundary_inclusive
    """
    pair = create_authorized_dealer(
        dealer_overrides={"legal_name": "Thin Credit Co",
                          "credit_limit_cents": 10000})
    dealer_id = pair["dealer"]["id"]
    line = create_product_line()
    drop_a = create_colorway_drop(line["id"], color_name="Credit A",
                                  pantone_code="PMS 100", total_units=100,
                                  dtc_reserved_units=0,
                                  dealer_unit_price_cents=2000)
    drop_b = create_colorway_drop(line["id"], color_name="Credit B",
                                  pantone_code="PMS 101", total_units=100,
                                  dtc_reserved_units=0,
                                  dealer_unit_price_cents=2000)
    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop_a["id"], _ADMIN))
    validate_success(api.open_allocation(drop_b["id"], _ADMIN))

    resp = api.create_launch_allocation(
        {"dealer_id": dealer_id, "drop_id": drop_a["id"], "requested_units": 6},
        make_dealer_headers(dealer_id))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    ok = create_allocation_request(dealer_id, drop_b["id"], 5)
    assert ok["status"] == "REQUESTED", "5 x 2000 == 10000 <= limit passes"
    assert get_dealer(dealer_id)["outstanding_balance_cents"] == 0, \
        "REQUESTED rows do not draw credit until ALLOCATED"


def test_duplicate_allocation_request_returns_409(api):
    """One REQUESTED allocation per (dealer, drop); also, a request against an
    ANNOUNCED drop is rejected before the window even opens.

    PRD section 3.4: "The drop must be `ALLOCATION_OPEN`, else
    `ERR_DROP_NOT_OPEN_FOR_ALLOCATION`"
    PRD section 3.4: "A dealer may hold at most one `REQUESTED` allocation per
    drop; a second is rejected with `ERR_DUPLICATE_ALLOCATION_REQUEST`."

    Design: Corner/validations/duplicate_allocation_request_returns_409
    """
    pair = create_authorized_dealer()
    dealer_id = pair["dealer"]["id"]
    opened_line = create_product_line()
    drop = create_colorway_drop(opened_line["id"])  # ANNOUNCED

    resp_notopen = api.create_launch_allocation(
        {"dealer_id": dealer_id, "drop_id": drop["id"], "requested_units": 2},
        make_dealer_headers(dealer_id))
    validate_error(resp_notopen, ApiErrorId.ERR_DROP_NOT_OPEN_FOR_ALLOCATION)

    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop["id"], _ADMIN))
    first = create_allocation_request(dealer_id, drop["id"], 5)
    assert first["status"] == "REQUESTED"

    resp_dup = api.create_launch_allocation(
        {"dealer_id": dealer_id, "drop_id": drop["id"], "requested_units": 7},
        make_dealer_headers(dealer_id))
    validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_ALLOCATION_REQUEST)

    rows, meta = validate_paginated(api.list_launch_allocations(
        _ADMIN, params={"dealer_id": dealer_id, "drop_id": drop["id"]}))
    assert len(rows) == 1 and meta["total_count"] == 1


def test_allocation_window_temporal_edges(api):
    """The window's three temporal edges: open before opens_at, lock before
    closes_at, a request at exactly closes_at, then the lock at closes_at.

    PRD section 3.3: "Opening the dealer allocation window moves the drop from
    `ANNOUNCED` to `ALLOCATION_OPEN` and is permitted only while the clock is
    inside the half-open window from `allocation_opens_at` up to but not
    including `allocation_closes_at`; outside that window the attempt is
    rejected with `ERR_ALLOCATION_WINDOW_NOT_OPEN`. Closing the window is the
    lock: permitted only once the clock has reached `allocation_closes_at` —
    earlier attempts are rejected with `ERR_ALLOCATION_WINDOW_OPEN`"
    PRD section 3.4: "the clock must still be before `allocation_closes_at`,
    else `ERR_ALLOCATION_WINDOW_CLOSED`"

    Design: Corner/validations/allocation_window_temporal_edges
    """
    pair = create_authorized_dealer()
    dealer_id = pair["dealer"]["id"]
    line = create_product_line()
    drop = create_colorway_drop(
        line["id"], color_name="Window Wine", pantone_code="PMS 1815",
        total_units=40, dtc_reserved_units=10, dealer_unit_price_cents=1000,
        allocation_opens_at="2026-09-05T00:00:00Z",
        allocation_closes_at="2026-09-10T00:00:00Z",
        go_live_at="2026-12-01T00:00:00Z")

    set_clock("2026-09-04T00:00:00Z")
    resp_early = api.open_allocation(drop["id"], _ADMIN)
    validate_error(resp_early, ApiErrorId.ERR_ALLOCATION_WINDOW_NOT_OPEN)

    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop["id"], _ADMIN))

    set_clock("2026-09-09T00:00:00Z")
    resp_lock_early = api.lock_allocation(
        drop["id"], {"expected_drop_version": _read_drop_version(drop["id"])},
        _ADMIN)
    validate_error(resp_lock_early, ApiErrorId.ERR_ALLOCATION_WINDOW_OPEN)

    set_clock("2026-09-10T00:00:00Z")
    resp_closed_edge = api.create_launch_allocation(
        {"dealer_id": dealer_id, "drop_id": drop["id"], "requested_units": 2},
        make_dealer_headers(dealer_id))
    validate_error(resp_closed_edge, ApiErrorId.ERR_ALLOCATION_WINDOW_CLOSED)

    locked = validate_success(api.lock_allocation(
        drop["id"], {"expected_drop_version": _read_drop_version(drop["id"])},
        _ADMIN))
    assert locked["status"] == "ALLOCATION_LOCKED", \
        "the lock at exactly allocation_closes_at succeeds"


def test_lock_then_forfeit_restores_drop_units_exactly(api):
    """The drop unit ledger is conserved: lock moves 30 units into committed,
    the manual forfeit returns them, restoring the pre-lock composition.

    PRD section 2.10: "an allocated allocation that is later forfeited returns
    its units to the pool and restores `unallocated_units` exactly."
    PRD section 3.4: "Manual forfeiture lands the allocation in `FORFEITED`
    with `forfeit_reason` `DEALER_CHOICE`"

    Design: Difficulty/compensating_invariant/lock_then_forfeit_restores_drop_units_exactly
    """
    bundle = setup_allocated_dealer(
        requested_units=30,
        lock_clock="2026-09-11T00:00:00Z",
        drop_overrides={"color_name": "Invariant Teal", "pantone_code": "PMS 321",
                        "drop_type": "LIMITED_EDITION", "total_units": 100,
                        "dtc_reserved_units": 20, "dealer_unit_price_cents": 2000,
                        "allocation_closes_at": "2026-09-10T00:00:00Z",
                        "go_live_at": "2026-12-01T00:00:00Z"},
    )
    drop_id = bundle["drop"]["id"]
    alloc_id = bundle["allocation"]["id"]

    mid = get_drop(drop_id)
    assert mid["dealer_committed_units"] == 30 and mid["unallocated_units"] == 50
    assert_drop_unit_ledger_invariant(mid)  # 100 == 30 + 20 + 0 + 50

    forfeited = validate_success(api.forfeit_launch_allocation(
        alloc_id, make_channel_manager_headers("cm-1")))
    assert forfeited["status"] == "FORFEITED"
    assert forfeited["forfeit_reason"] == "DEALER_CHOICE"

    end = get_drop(drop_id)
    assert end["dealer_committed_units"] == 0
    assert end["unallocated_units"] == 80, "exactly the pre-lock pool composition"
    assert_drop_unit_ledger_invariant(end)  # 100 == 0 + 20 + 0 + 80
