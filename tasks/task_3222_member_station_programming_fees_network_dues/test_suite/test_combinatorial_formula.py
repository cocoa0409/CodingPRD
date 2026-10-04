"""Pinned evaluation order inside the carriage-exception rules (queue A,
rule `combinatorial_formula`).

`carriage_clearance_ratio` names an evaluation order that is part of the
contract because the agreement's own inputs are outputs of the same rule, and
`exception_liability_accrual` pins which basis a window's terminal outcome
selects. These tests assert the window-level figures the PRD states outright.
"""
from test_helpers import (
    AUDITOR,
    REJECTED_BASE_CENTS,
    UNFILLED_SLOT_BASE_CENTS,
    api_client,
    create_agreement,
    create_program,
    create_window,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    refresh_window,
    set_clock,
)

STATION_FIXTURE = dict(
    call_sign="KQED", licensee_name="Bay Licensee", state_code="CA",
    dma_market_rank=6, dma_households=2500000, coverage_population=120000,
    full_time_staff_count=9, newsroom_staff_count=5,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)


def setup_pending_window():
    """One agreement in UNDER_REVIEW holding a single PENDING_CLEARANCE window."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**{**STATION_FIXTURE, "call_sign": "KQED"})
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1001")
    agreement = create_agreement(station, program_code=program["program_code"])
    window = create_window(agreement, station)
    get_success_data(api_client.submit_agreement(agreement["id"], headers))
    get_success_data(api_client.review_agreement(agreement["id"], AUDITOR))
    get_success_data(api_client.request_clearance(window["id"], headers))
    return {"station": station, "program": program, "agreement": agreement,
            "window": refresh_window(window)}


def test_rejected_window_accrues_the_flat_rejected_basis():
    """PRD §3.5: "A rejected window accrues a flat 25000 cents."
    PRD §2.10: "`carriage_exception_liability_cents`" is one of the fields the
    network derives rather than a value a caller supplies.

    The window is the only child of its agreement, so the accrual is the
    window's own figure.

    Design: Difficulty/combinatorial_formula/combinatorial_liability_cap_circular
    """
    ctx = setup_pending_window()
    resp = api_client.reject_window(
        ctx["window"]["id"],
        {"rejection_reason": "Clearance documents incomplete"},
        AUDITOR,
    )
    data = get_success_data(resp)

    assert data["clearance_status"] == "REJECTED"
    assert data["carriage_exception_liability_cents"] == REJECTED_BASE_CENTS, (
        f"a rejected window should accrue {REJECTED_BASE_CENTS} cents, "
        f"got {data['carriage_exception_liability_cents']}"
    )


def test_rejected_window_records_the_rejection_reason_supplied():
    """PRD §3.3: "the auditor rejects a `PENDING_CLEARANCE` window with a
    non-empty `rejection_reason`, moving it to `REJECTED` and accruing the
    window's exception liability as described in §3.5."

    Design: Difficulty/combinatorial_formula/combinatorial_liability_cap_circular
    """
    ctx = setup_pending_window()
    reason = "Clearance documents incomplete"
    resp = api_client.reject_window(ctx["window"]["id"], {"rejection_reason": reason}, AUDITOR)
    data = get_success_data(resp)

    assert data["clearance_status"] == "REJECTED"
    assert data["rejection_reason"] == reason, (
        f"the recorded rejection reason should be {reason!r}, "
        f"got {data.get('rejection_reason')!r}"
    )


def test_missed_window_accrues_the_flat_missed_slot_basis():
    """PRD §3.5: "A missed window accrues a flat 40000 cents."

    The window is carried by a published agreement and has passed its end
    instant, which is the state the missed basis describes.

    Design: Difficulty/combinatorial_formula/combinatorial_liability_two_quantities
    """
    from test_helpers import setup_published_agreement

    ctx = setup_published_agreement(
        station_overrides={**STATION_FIXTURE, "call_sign": "KUHF"},
        window_overrides={"window_start": "2026-10-05T07:00:00Z",
                          "window_end": "2026-10-05T08:00:00Z"},
    )
    set_clock("2026-10-06T00:00:00Z")
    resp = api_client.expire_window(ctx["window"]["id"], AUDITOR)
    data = get_success_data(resp)

    assert data["clearance_status"] == "MISSED"
    assert data["carriage_exception_liability_cents"] == UNFILLED_SLOT_BASE_CENTS, (
        f"a missed window should accrue {UNFILLED_SLOT_BASE_CENTS} cents, "
        f"got {data['carriage_exception_liability_cents']}"
    )


def setup_two_station_batch():
    """Two ELIGIBLE stations with assessments in one fiscal year."""
    from test_helpers import create_schedule, first_station_assessment

    set_clock("2026-09-01T00:00:00Z")
    create_schedule(schedule_code="FY2026D", fiscal_year=2026,
                    annual_adjustment_bps=0, base_fee_cents=1200000,
                    revenue_rate_bps=250, market_size_multiplier_bps=12500,
                    minimum_fee_cents=100000, maximum_fee_cents=5000000,
                    effective_from="2026-06-01T00:00:00Z",
                    effective_to="2027-06-01T00:00:00Z")
    first = make_station_eligible(
        call_sign="WKAR", licensee_name="Michigan Licensee", state_code="MI",
        dma_market_rank=5, dma_households=2200000, coverage_population=130000,
        full_time_staff_count=9, newsroom_staff_count=5,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST")
    second = make_station_eligible(
        call_sign="WETA", licensee_name="Potomac Licensee", state_code="DC",
        dma_market_rank=22, dma_households=700000, coverage_population=60000,
        full_time_staff_count=6, newsroom_staff_count=3,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH")
    return {
        "stations": [first, second],
        "assessments": [first_station_assessment(first), first_station_assessment(second)],
    }


def test_pool_allocation_distributes_the_remainder_cent_by_the_selector():
    """PRD §3.9: "Each ranked station's `allocated_dues_cents` is the flat 120000
    cents plus one cent if its rank index is below the remainder."
    PRD §3.9: "A pool of 240001 cents with one `CLASS_A` and one `CLASS_B`
    station leaves a remainder of 1 cent, which the `CLASS_A` station receives as
    the first rank, yielding 120001 and 120000 cents and a total of 240001".

    Design: Difficulty/combinatorial_formula/combinatorial_liability_two_quantities
    """
    from test_helpers import GOVERNANCE, STATION_TIER_SHARE_CENTS

    ctx = setup_two_station_batch()
    resp = api_client.allocate_pool(
        ctx["assessments"][0]["id"], {"total_pot_cents": 240001}, GOVERNANCE)
    data = get_success_data(resp)

    shares = sorted(a["allocated_dues_cents"] for a in data)
    assert shares == [STATION_TIER_SHARE_CENTS, STATION_TIER_SHARE_CENTS + 1], (
        f"one remainder cent should be handed out, got shares {shares}"
    )
    assert sum(shares) == 240001, "the batch total must equal the pool exactly"


def test_pool_allocation_gives_every_eligible_station_the_flat_share():
    """PRD §3.9: "The flat share is a tier benefit: every eligible station
    receives a flat 120000 cents".

    Design: Difficulty/combinatorial_formula/combinatorial_liability_two_quantities
    """
    from test_helpers import GOVERNANCE, STATION_TIER_SHARE_CENTS

    ctx = setup_two_station_batch()
    resp = api_client.allocate_pool(
        ctx["assessments"][0]["id"], {"total_pot_cents": 240001}, GOVERNANCE)
    data = get_success_data(resp)

    for assessment in data:
        assert assessment["allocated_dues_cents"] >= STATION_TIER_SHARE_CENTS, (
            "no eligible station may fall below the flat tier share"
        )
        assert assessment["allocated_dues_cents"] <= STATION_TIER_SHARE_CENTS + 1, (
            "no station may receive more than one remainder cent"
        )