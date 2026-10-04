"""Marketplace enforcement, infraction points, and dealer standing
(PRD section 3.2)."""
from test_helpers import (
    ApiErrorId,
    add_infraction_points,
    api_client,
    boot_clock,
    create_authorized_dealer,
    create_dealer,
    create_enforcement_case,
    get_case,
    get_drop,
    get_dealer,
    get_allocation,
    make_channel_manager_headers,
    reinstate_dealer,
    resolve_case_confirmed,
    set_clock,
    setup_allocated_dealer,
    suspend_dealer,
    terminate_dealer,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

_CM = TEST_USERS["channel_manager_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


def _cm(user_id):
    return make_channel_manager_headers(user_id)


def test_escalate_legal_then_confirm_branch(api):
    """UNDER_REVIEW -> ESCALATED_LEGAL -> CONFIRMED_VIOLATION: escalation is
    not terminal, and the later confirmation still applies the points table.

    PRD section 3.2: "From `UNDER_REVIEW` the case may be escalated to
    `ESCALATED_LEGAL`. From either `UNDER_REVIEW` or `ESCALATED_LEGAL` it may
    be dismissed into `DISMISSED`, or confirmed into `CONFIRMED_VIOLATION`."
    PRD section 3.2: "a `MAP_VIOLATION` is worth 4 points, an
    `UNAUTHORIZED_MARKETPLACE` case 6, a `BRAND_STANDARD` case 3, and a
    `CHANNEL_DIVERSION` case 5."

    Design: Corner/state_machines/escalate_legal_then_confirm_branch
    """
    pair = create_authorized_dealer()
    dealer_id = pair["dealer"]["id"]
    case1 = create_enforcement_case(
        matched_dealer_id=dealer_id, marketplace="WALMART",
        seller_handle="brand-abuser", listing_url="https://walmart.example/i/b1")
    case2 = create_enforcement_case(
        matched_dealer_id=dealer_id, marketplace="OTHER",
        seller_handle="random-seller", listing_url="https://other.example/i/b2")

    resp_esc = api.resolve_enforcement_case(
        case1["id"],
        {"outcome": "ESCALATED_LEGAL", "resolution_notes": "counter-notice received"},
        _cm("cm-1"))
    assert validate_success(resp_esc)["status"] == "ESCALATED_LEGAL"

    confirmed = resolve_case_confirmed(case1["id"], dealer_id, "BRAND_STANDARD")
    assert confirmed["status"] == "CONFIRMED_VIOLATION"
    assert confirmed["infraction_points"] == 3

    resp_dis = api.resolve_enforcement_case(
        case2["id"],
        {"outcome": "DISMISSED", "resolution_notes": "legitimate secondhand listing"},
        _cm("cm-1"))
    assert validate_success(resp_dis)["status"] == "DISMISSED"
    assert get_case(case2["id"])["infraction_points"] == 0

    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 3
    assert dealer["status"] == "AUTHORIZED", "3 points is below the probation bar"


def test_probation_threshold_boundary_seven_holds_ten_crosses(api):
    """The probation bar is 8 points: 3 and 7 hold AUTHORIZED, the jump to 10
    crosses it exactly once.

    PRD section 3.2: "when it lands at 8 or more but fewer than 12 on an
    `AUTHORIZED` dealer, the dealer moves to `PROBATION`. Exactly 8 points is
    probation and exactly 12 is suspension."

    Design: Corner/calculations/probation_threshold_boundary_seven_holds_ten_crosses
    """
    pair = create_authorized_dealer()
    dealer_id = pair["dealer"]["id"]
    cases = [create_enforcement_case(matched_dealer_id=dealer_id,
                                     seller_handle=f"th-{i}",
                                     listing_url=f"https://m.example/i/t{i}")
             for i in (1, 2, 3)]

    resolve_case_confirmed(cases[0]["id"], dealer_id, "BRAND_STANDARD")
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 3 and dealer["status"] == "AUTHORIZED"

    resolve_case_confirmed(cases[1]["id"], dealer_id, "MAP_VIOLATION")
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 7 and dealer["status"] == "AUTHORIZED", \
        "7 < 8 — the boundary holds"

    resolve_case_confirmed(cases[2]["id"], dealer_id, "BRAND_STANDARD")
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 10 and dealer["status"] == "PROBATION"


def test_infraction_expiry_decays_points_but_status_waits_for_reinstate(api):
    """Expired cases stop contributing points, but standing relaxes only
    through an explicit reinstate.

    PRD section 3.2: "A dealer's live `infraction_points` is the sum of points
    over its matched cases that are in `CONFIRMED_VIOLATION` and whose
    `infraction_expires_at` is still in the future; expired cases and
    overturned cases contribute nothing."
    PRD section 3.2: "Standing never relaxes automatically — overturning a case
    lowers the points but does not restore status."
    PRD section 3.2: "reinstatement recomputes the dealer's live points from
    the clock and lands the dealer in `AUTHORIZED` when the recomputed total is
    below 8, or in `PROBATION` when it is 8 up to 11 inclusive; the landing
    state is derived, never chosen by the caller."

    Design: Corner/state_machines/infraction_expiry_decays_points_but_status_waits_for_reinstate
    """
    pair = create_authorized_dealer()
    dealer_id = pair["dealer"]["id"]
    set_clock("2026-09-11T00:00:00Z")
    cases = add_infraction_points(dealer_id, ["MAP_VIOLATION", "MAP_VIOLATION"])
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 8 and dealer["status"] == "PROBATION"

    set_clock("2027-09-12T00:00:00Z")
    assert get_case(cases[0]["id"])["infraction_state"] == "EXPIRED"
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 0, "both cases expired 365 days after issue"
    assert dealer["status"] == "PROBATION", "expiry never auto-restores standing"

    reinstated = reinstate_dealer(dealer_id)
    assert reinstated["status"] == "AUTHORIZED", "recomputed 0 points is below 8"


def test_terminated_dealer_lockdown(api):
    """TERMINATED is terminal: reinstate and suspend are both rejected and the
    record does not move.

    PRD section 3.2: "Termination is the terminal act: from `PENDING`,
    `AUTHORIZED`, `PROBATION`, or `SUSPENDED` the dealer moves to `TERMINATED`"
    PRD section 2.7: "(5) the target resource's own state permitting the
    requested transition (`ERR_INVALID_STATE_TRANSITION` and the specific state
    errors)"

    Design: Corner/state_machines/terminated_dealer_lockdown
    """
    boot_clock()
    dealer = create_dealer()
    terminated = terminate_dealer(dealer["id"], reason="fraudulent paperwork")
    assert terminated["status"] == "TERMINATED"

    resp_reinstate = api.reinstate_dealer(dealer["id"], _cm("cm-1"))
    validate_error(resp_reinstate, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    resp_suspend = api.suspend_dealer(dealer["id"], {"reason": "double jeopardy"},
                                      _cm("cm-1"))
    validate_error(resp_suspend, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_dealer(dealer["id"])["status"] == "TERMINATED"


def test_enforcement_confirm_cascades_to_pool_ledger(api):
    """Depth-4 cascade: case confirmed -> points recomputed -> dealer
    auto-SUSPENDED at >= 12 -> non-live-drop ALLOCATED allocation forfeited and
    its units return to the pool.

    PRD section 3.2: "when a recomputation lands the dealer at 12 or more
    points, the dealer moves to `SUSPENDED` from either `AUTHORIZED` or
    `PROBATION`"
    PRD section 3.2: "every launch allocation of the dealer in `REQUESTED` or
    `ALLOCATED` whose drop is still `ANNOUNCED`, `ALLOCATION_OPEN`, or
    `ALLOCATION_LOCKED` transitions to `FORFEITED` with `forfeit_reason`
    `DEALER_SUSPENDED`; allocations on drops already `LIVE` or `CLOSED` are
    untouched. Each forfeited `ALLOCATED` allocation recomputes its drop's
    `dealer_committed_units` and `unallocated_units`, returning the freed units
    to the pool, and increments the drop's `version`"

    Design: Difficulty/transitive_cascade/enforcement_confirm_cascades_to_pool_ledger
    """
    bundle = setup_allocated_dealer(
        requested_units=8,
        lock_clock="2026-09-11T00:00:00Z",
        drop_overrides={"total_units": 50, "dtc_reserved_units": 10,
                        "dealer_unit_price_cents": 2000,
                        "allocation_closes_at": "2026-09-10T00:00:00Z",
                        "go_live_at": "2026-12-01T00:00:00Z"},
    )
    dealer_id = bundle["dealer"]["id"]
    drop_id = bundle["drop"]["id"]
    alloc_id = bundle["allocation"]["id"]
    assert get_allocation(alloc_id)["status"] == "ALLOCATED"
    drop = get_drop(drop_id)
    assert drop["dealer_committed_units"] == 8 and drop["unallocated_units"] == 32

    cases = [create_enforcement_case(matched_dealer_id=dealer_id,
                                     seller_handle=f"cs-{i}",
                                     listing_url=f"https://m.example/i/c{i}")
             for i in (1, 2, 3)]

    # Hop 1-2: 5 points — below both thresholds.
    resolve_case_confirmed(cases[0]["id"], dealer_id, "CHANNEL_DIVERSION")
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 5 and dealer["status"] == "AUTHORIZED"

    # 11 points — PROBATION; probation does NOT forfeit allocations.
    resolve_case_confirmed(cases[1]["id"], dealer_id, "UNAUTHORIZED_MARKETPLACE")
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 11 and dealer["status"] == "PROBATION"
    assert get_allocation(alloc_id)["status"] == "ALLOCATED"
    assert get_drop(drop_id)["unallocated_units"] == 32

    # Hop 3-4: 15 points — SUSPENDED, and the allocation forfeits into the pool.
    resolve_case_confirmed(cases[2]["id"], dealer_id, "MAP_VIOLATION")
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 15 and dealer["status"] == "SUSPENDED"
    alloc = get_allocation(alloc_id)
    assert alloc["status"] == "FORFEITED"
    assert alloc["forfeit_reason"] == "DEALER_SUSPENDED"
    drop = get_drop(drop_id)
    assert drop["dealer_committed_units"] == 0
    assert drop["unallocated_units"] == 40, "the 8 units returned to the pool exactly"

    rows, meta = validate_paginated(api.list_enforcement_cases(
        _cm("cm-1"),
        params={"matched_dealer_id": dealer_id, "status": "CONFIRMED_VIOLATION"}))
    assert len(rows) == 3 and meta["total_count"] == 3


def test_allocation_score_switches_variant_with_season_clock(api):
    """The same dealer metrics score under STANDARD weights at a September
    clock and PEAK weights at a November clock; only the clock selects the
    variant (a read mutates nothing, so the version does not move).

    PRD section 2.9: "A dealer's `allocation_score` switches from its STANDARD
    weighting to a PEAK weighting that shifts emphasis toward brand
    presentation and punishes infraction points more heavily while the clock
    is inside the window."
    PRD section 3.4: "outside the peak window the STANDARD weighting is 0.50 on
    sell-through, 0.30 on brand presentation, 2 per tenure year, and a penalty
    of 5 per infraction point; inside the peak window the PEAK weighting shifts
    to 0.35 on sell-through, 0.45 on brand presentation, keeps 2 per tenure
    year, and punishes 8 per infraction point. The score is rounded half up to
    2 decimal places, is recomputed on every dealer read, and is read fresh at
    lock time."

    Design: Difficulty/dual_variant_calc/allocation_score_switches_variant_with_season_clock
    """
    pair = create_authorized_dealer(
        dealer_overrides={"sell_through_pct": 80, "tenure_years": 5},
        brand_score=85)
    dealer_id = pair["dealer"]["id"]

    set_clock("2026-09-03T00:00:00Z")
    read_standard = get_dealer(dealer_id)
    assert read_standard["allocation_score"] == 75.5, \
        "0.50*80 + 0.30*85 + 2*5 - 5*0 = 75.50 (STANDARD)"

    set_clock("2026-11-02T00:00:00Z")
    read_peak = get_dealer(dealer_id)
    assert read_peak["allocation_score"] == 76.25, \
        "0.35*80 + 0.45*85 + 2*5 - 8*0 = 76.25 (PEAK)"
    assert read_peak["allocation_score"] != read_standard["allocation_score"]
    assert read_peak["version"] == read_standard["version"], \
        "no write occurred between the reads, so the version is unchanged"
