"""Dual-variant calculation: the second variant selector (queue A, `dual_variant_calc`).

The published-fee variant pair on the schedule domain and the published-branch
selector on the content-compensation rule are the two further two-way branches
the rule set names. This file covers the compensation selector and the
membership-class surcharge that sits inside the market component.
"""
from test_helpers import (
    CONFERENCE_RATE_CENTS,
    EDITOR,
    api_client,
    create_contribution_payload,
    create_schedule,
    duration_factor_bps,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    refresh_program,
    shelf_credit_cents,
    set_clock,
)

SCHEDULE_FIXTURE = dict(
    schedule_code="FY2026C", fiscal_year=2026, base_fee_cents=1200000,
    revenue_rate_bps=250, market_tier_1_max_rank=25, market_tier_2_max_rank=75,
    market_tier_3_max_rank=150, market_size_multiplier_bps=12500,
    minimum_fee_cents=100000, maximum_fee_cents=5000000,
    annual_adjustment_bps=0, effective_from="2026-06-01T00:00:00Z",
    effective_to="2027-06-01T00:00:00Z",
)

# A CLASS_B station (score 71.60, household index 60) carrying a 180-second piece.
CLASS_B_STATION = dict(
    call_sign="WGBH", licensee_name="Charles Licensee", state_code="MA",
    dma_market_rank=10, dma_households=600000, coverage_population=600000,
    full_time_staff_count=20, newsroom_staff_count=6,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST",
)


def setup_shortlisted_piece(station_overrides=None, duration_seconds=180,
                            revision_count=0):
    """A SHORTLISTED piece carrying the requested number of revision rounds.

    PRD §3.6: a piece gains a revision round by being returned from
    `SHORTLISTED` to `DRAFT` and submitted again — "this is the station-level
    revision loop, and a piece may pass through it several times" — so the loop
    is walked `revision_count` times before the final shortlisting.
    """
    set_clock("2026-09-01T00:00:00Z")
    create_schedule(**SCHEDULE_FIXTURE)
    station = make_station_eligible(**(station_overrides or CLASS_B_STATION))
    headers = make_station_manager_headers(station["id"])
    program = get_success_data(api_client.create_program(
        {"program_code": "NP-1011", "program_title": "Boston Desk Weekly",
         "strand_type": "NEWS", "national_premiere_at": "2026-10-01T00:00:00Z"},
        EDITOR), 201)
    contribution = get_success_data(api_client.create_contribution(
        create_contribution_payload(station_id=station["id"], program_id=program["id"],
                                    duration_seconds=duration_seconds),
        headers), 201)
    get_success_data(api_client.submit_contribution(contribution["id"], headers))
    for _ in range(revision_count):
        get_success_data(api_client.shortlist_contribution(contribution["id"], EDITOR))
        get_success_data(api_client.request_resubmission(contribution["id"], EDITOR))
        get_success_data(api_client.submit_contribution(contribution["id"], headers))
    get_success_data(api_client.shortlist_contribution(contribution["id"], EDITOR))
    return {
        "station": station,
        "program": program,
        "contribution": get_success_data(
            api_client.get_contribution(contribution["id"], EDITOR)),
        "headers": headers,
    }


def test_shortlisted_piece_takes_the_shelf_credit_alone():
    """PRD §3.6: "when the piece is `LICENSED` or `USED` — the published branch —
    the credit is the greater of the shelf credit and a flat conference rate of
    60000 cents, while a piece that is merely `SUBMITTED` or `SHORTLISTED` takes
    the shelf credit alone".
    PRD §3.6: "A one-hundred-and-eighty-second `CLASS_B` piece with one revision
    round therefore credits 45125 cents while it sits shortlisted".

    Design: Difficulty/dual_variant_calc/dual_fee_class_multiplier_surcharge
    """
    ctx = setup_shortlisted_piece(revision_count=1)
    data = ctx["contribution"]

    assert data["contribution_status"] == "SHORTLISTED"
    assert data["revision_count"] == 1, (
        f"the staged revision round should be on the piece, "
        f"got {data['revision_count']}"
    )
    factor = duration_factor_bps(180)
    assert factor == 10000
    expected = shelf_credit_cents("CLASS_B", 180, 1)
    assert expected == 45125, f"PRD states the shelf figure 45125, derived {expected}"
    assert data["compensation_credit_cents"] == expected, (
        f"the shelf branch should credit {expected}, got {data['compensation_credit_cents']}"
    )


def test_licensed_piece_takes_the_conference_rate_floor():
    """PRD §3.6: "the credit is the greater of the shelf credit and a flat
    conference rate of 60000 cents, while a piece that is merely `SUBMITTED` or
    `SHORTLISTED` takes the shelf credit alone".
    PRD §3.6: "A one-hundred-and-eighty-second `CLASS_B` piece with one revision
    round therefore credits 45125 cents while it sits shortlisted and 60000 cents
    once it is licensed, and the 60000-cent floor is what the published branch
    buys."

    Design: Difficulty/dual_variant_calc/dual_fee_class_multiplier_surcharge
    """
    ctx = setup_shortlisted_piece(revision_count=1)
    program = refresh_program(ctx["program"])
    resp = api_client.license_contribution(
        ctx["contribution"]["id"],
        {"expected_program_version": program["version"]},
        EDITOR,
    )
    data = get_success_data(resp)

    assert data["contribution_status"] == "LICENSED"
    assert data["compensation_credit_cents"] == CONFERENCE_RATE_CENTS, (
        f"the published branch should credit {CONFERENCE_RATE_CENTS}, "
        f"got {data['compensation_credit_cents']}"
    )
    shelf = shelf_credit_cents("CLASS_B", 180, 1)
    assert data["compensation_credit_cents"] - shelf == 14875, (
        "the two variants should diverge by 14875 cents on this piece"
    )