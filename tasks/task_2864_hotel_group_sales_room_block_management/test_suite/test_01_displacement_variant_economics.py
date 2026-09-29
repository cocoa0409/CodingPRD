"""Displacement economics: the two analysis variants and the attrition bases.

PRD 3.3 makes ``analysis_variant`` choose which of two series on the same
InventoryDay rows is displaced, and PRD 3.7 publishes both attrition bases side
by side on the pickup projection, so a single response exposes the divergence.
"""

from test_helpers import (
    REVENUE_MANAGER,
    AnalysisStatus,
    AnalysisVariant,
    AttritionBasis,
    LeadStatus,
    Verdict,
    assert_displacement_analysis,
    assert_group_contract,
    assert_lead,
    assert_pickup_summary,
    assert_rate_quote,
    confirm_reservations,
    factories as F,
    pickup_summary,
    read_contract,
    read_lead,
    read_quote,
    seed_open_master_block,
    seed_qualified_lead,
    seed_reservations,
    validate_success,
)


def _qualified_world(api):
    """A CORPORATE lead over 2026-11-09..12, qualified against a forecast-rich
    calendar whose forecast series (398 rooms) sits above the historical series
    (390 rooms) on every night of the stay (PRD 2.9, PRD 3.2)."""
    return seed_qualified_lead(api)


def _request_analysis(api, world, variant):
    return validate_success(
        api.create_displacement_analysis(
            F.displacement_analysis_payload(world["lead_id"], analysis_variant=variant),
            REVENUE_MANAGER,
        ),
        201,
    )


def test_forecast_variant_displaces_the_forecast_series(api):
    """A FORECAST_BASED study prices the transient rooms the group pushes out.

    PRD 3.3: "FORECAST_BASED reads transient_demand_rooms and
    transient_adr_cents; HISTORICAL_BASED reads historical_pickup_rooms and
    historical_adr_cents." With 400 total rooms, 398 forecast transient rooms
    and a 4-room hold on each of the three nights, 2 rooms per night spill over
    on each of the three nights - 6 displaced room nights at the 21000-cent
    transient ADR.

    Design: Difficulty/dual_variant_calc/displacement_forecast_series_versus_historical_series
    """
    world = _qualified_world(api)

    lead = read_lead(api, world["lead_id"])
    assert_lead(lead, qualification_score=35, estimated_room_night_value_cents=206640)

    forecast = _request_analysis(api, world, AnalysisVariant.FORECAST_BASED)

    assert_displacement_analysis(
        forecast,
        analysis_variant=AnalysisVariant.FORECAST_BASED,
        displaced_room_nights=6,
        displaced_revenue_cents=126000,
        ancillary_projection_cents=54000,
        net_benefit_cents=134640,
        verdict=Verdict.ACCEPT,
        status=AnalysisStatus.PENDING,
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.DISPLACEMENT_REVIEW)


def test_historical_variant_displaces_nothing_on_the_same_rows(api):
    """The historical series leaves room for the group, so nothing is displaced.

    PRD 3.3 fixes the displacement arithmetic per stay date; on the identical
    InventoryDay rows the 390-room historical series absorbs the same 4-room
    hold with no spill, so displaced_room_nights is 0 and net_benefit_cents
    differs from the forecast study by exactly the 126000 cents of displaced
    transient revenue.

    Design: Difficulty/dual_variant_calc/displacement_forecast_series_versus_historical_series
    """
    world = _qualified_world(api)

    forecast = _request_analysis(api, world, AnalysisVariant.FORECAST_BASED)
    historical = _request_analysis(api, world, AnalysisVariant.HISTORICAL_BASED)

    assert_displacement_analysis(
        historical,
        analysis_variant=AnalysisVariant.HISTORICAL_BASED,
        displaced_room_nights=0,
        displaced_revenue_cents=0,
        net_benefit_cents=260640,
        status=AnalysisStatus.PENDING,
    )
    assert forecast["status"] == AnalysisStatus.PENDING
    assert (
        historical["net_benefit_cents"] - forecast["net_benefit_cents"] == 126000
    ), "the two variants must diverge by the displaced transient revenue"
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.DISPLACEMENT_REVIEW)


_PICKUP_PATTERN = (
    {
        "guest_name": "Ada Lovelace",
        "arrival_date": "2026-11-09",
        "departure_date": "2026-11-12",
    },
    {
        "guest_name": "Grace Hopper",
        "arrival_date": "2026-11-09",
        "departure_date": "2026-11-10",
    },
    {
        "guest_name": "Alan Turing",
        "arrival_date": "2026-11-10",
        "departure_date": "2026-11-11",
    },
)


def _picked_up_block(api):
    """A signed 12-room-night contract on the ROOM_NIGHTS basis whose OPEN
    master block has actualized 5 room nights spread 2/2/1 across the stay
    (PRD 3.5, PRD 3.6)."""
    world = seed_open_master_block(api)
    rows = seed_reservations(api, world["master_block_id"], _PICKUP_PATTERN)
    confirm_reservations(api, [row["id"] for row in rows])
    world["reservation_ids"] = [row["id"] for row in rows]
    return world


def test_room_nights_basis_prices_the_shortfall_over_the_whole_stay(api):
    """On the ROOM_NIGHTS basis the commitment base is the contracted total.

    PRD 3.7: "When attrition_basis is ROOM_NIGHTS the commitment base is
    contracted_room_nights." 12 committed room nights at a 0.75 threshold
    require 9; 5 actualized leaves a 4-room-night shortfall priced at the
    contracted rate times the 0.85 damage factor.

    Design: Difficulty/dual_variant_calc/attrition_basis_room_nights_versus_peak_night
    """
    world = _picked_up_block(api)

    assert_rate_quote(read_quote(api, world["quote_id"]), effective_net_rate_cents=20880)
    assert_group_contract(
        read_contract(api, world["contract_id"]),
        attrition_basis=AttritionBasis.ROOM_NIGHTS,
        contracted_rate_cents=20880,
    )

    summary = pickup_summary(api, world["master_block_id"])

    assert_pickup_summary(
        summary,
        allotted_room_nights=12,
        picked_up_room_nights=5,
        peak_night_rooms=2,
        commitment_base_room_nights=12,
        room_nights_basis_shortfall=4,
        room_nights_basis_damages_cents=70992,
    )


def test_peak_night_basis_prices_the_same_pickup_off_the_peak_room_count(api):
    """The peak-night basis reads the same pickup through a different lens.

    PRD 3.7: "When attrition_basis is PEAK_NIGHT the shortfall is measured in
    rooms on the peak night and multiplied by nights_count." The peak night
    holds 2 of the 4 contracted peak rooms, so a 1-room miss becomes 3 room
    nights - a smaller liability than the whole-stay basis on the identical
    rooming list, and the projection publishes both so the divergence is
    visible in one response.

    Design: Difficulty/dual_variant_calc/attrition_basis_room_nights_versus_peak_night
    """
    world = _picked_up_block(api)

    summary = pickup_summary(api, world["master_block_id"])

    assert_pickup_summary(
        summary,
        picked_up_room_nights=5,
        peak_night_rooms=2,
        peak_night_basis_shortfall=3,
        peak_night_basis_damages_cents=53244,
    )
    assert (
        summary["room_nights_basis_damages_cents"]
        - summary["peak_night_basis_damages_cents"]
        == 17748
    ), "the two bases must diverge on the same pickup pattern"
