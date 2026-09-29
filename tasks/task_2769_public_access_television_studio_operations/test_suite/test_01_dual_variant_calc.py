"""Calculations whose two published variants must diverge on identical inputs."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN_HEADERS, FINANCE_HEADERS


# ---------------------------------------------------------------------------
# Franchise fee allocation: ACCRUAL versus CASH on one funding period
# ---------------------------------------------------------------------------
def test_accrual_basis_selects_earned_base_and_the_high_tier_reserve(client):
    """An ACCRUAL submission recognises the earned figure at the 5 percent tier.

    PRD 3.8: "Step one selects the recognised amount: `allocable_base_cents`
    becomes `service_period_earned_cents` when the `basis` is `ACCRUAL`, and
    `remittance_received_cents` when the `basis` is `CASH`."

    PRD 3.8: "Step two chooses the administrative reserve rate from a two-row
    tier table: the rate is 500 basis points — 5 percent — when
    `allocable_base_cents` is at or above 5000000 cents, and 800 basis points —
    8 percent — below that threshold."

    PRD 3.8: "Under `ACCRUAL` the allocable base is 5000000, which reaches the
    high tier, so the reserve rate is 5 percent: the administrative reserve is
    250000, the distributable amount is 4750000, the capital share is 1662500
    giving a capital allocation of 1762500, the operating allocation is 3087500,
    and the total is 5100000."

    Design: Difficulty/dual_variant_calc/franchise_allocation_accrual_vs_cash_diverges_on_funding_period
    """
    period = fx.open_funding_period(
        client,
        fiscal_year=2026,
        quarter=3,
        basis="ACCRUAL",
        gross_franchise_fee_cents=5200000,
        service_period_earned_cents=5000000,
        remittance_received_cents=4800000,
        capital_grant_cents=100000,
    )

    submitted = a.data_of(client.submit_funding_report(period["id"], {}, FINANCE_HEADERS))

    a.assert_cents(submitted["allocable_base_cents"], 5000000, "allocable_base_cents")
    a.assert_cents(submitted["admin_reserve_cents"], 250000, "admin_reserve_cents")
    a.assert_cents(submitted["capital_allocation_cents"], 1762500, "capital_allocation_cents")
    a.assert_cents(submitted["operating_allocation_cents"], 3087500, "operating_allocation_cents")
    a.assert_cents(submitted["total_program_funds_cents"], 5100000, "total_program_funds_cents")
    a.assert_allocation_identity(submitted)
    assert submitted["report_status"] == "SUBMITTED"


def test_cash_restatement_diverges_from_the_accrual_answer_by_134000_cents(client):
    """Restating the same raw figures onto a CASH basis moves every allocation.

    PRD 3.8: "Under `CASH` the allocable base is 4800000, which falls below the
    threshold, so the reserve rate is 8 percent: the administrative reserve is
    384000, the distributable amount is 4416000, the capital share is 1545600
    giving a capital allocation of 1645600, the operating allocation is 2870400,
    and the total is 4900000."

    PRD 3.8: "Both forms raise `revision_round` by 1, re-run the whole
    allocation under the effective basis — which may itself have changed with
    this request — and increment the period's `version` by 1."

    Design: Difficulty/dual_variant_calc/franchise_allocation_accrual_vs_cash_diverges_on_funding_period
    """
    period = fx.open_funding_period(
        client,
        fiscal_year=2026,
        quarter=3,
        basis="ACCRUAL",
        gross_franchise_fee_cents=5200000,
        service_period_earned_cents=5000000,
        remittance_received_cents=4800000,
        capital_grant_cents=100000,
    )
    accrual = a.data_of(client.submit_funding_report(period["id"], {}, FINANCE_HEADERS))
    a.data_of(
        client.decide_funding_report(
            period["id"],
            {"decision": "RETURN", "reason": "Restate the quarter on a cash basis"},
            ADMIN_HEADERS,
        )
    )

    cash = fx.revise_funding_period(client, period["id"], basis="CASH")

    a.assert_cents(cash["allocable_base_cents"], 4800000, "allocable_base_cents")
    a.assert_cents(cash["admin_reserve_cents"], 384000, "admin_reserve_cents")
    a.assert_cents(cash["capital_allocation_cents"], 1645600, "capital_allocation_cents")
    a.assert_cents(cash["operating_allocation_cents"], 2870400, "operating_allocation_cents")
    a.assert_cents(cash["total_program_funds_cents"], 4900000, "total_program_funds_cents")
    a.assert_allocation_identity(cash)
    assert cash["admin_reserve_cents"] - accrual["admin_reserve_cents"] == 134000
    assert cash["report_status"] == "DRAFT"
    assert cash["revision_round"] == 1


# ---------------------------------------------------------------------------
# Community impact index: PROVISIONAL at air versus FINAL at publication
# ---------------------------------------------------------------------------
def _aired_broadcast_with_one_camera_volunteer(client):
    """Air a 1800-second live program staffed by one CAMERA volunteer.

    The owning producer holds `LIVE` certification because only a live program
    may declare crew roles, and the volunteer needs no certification for CAMERA.
    """
    owner = fx.setup_live_certified_producer(
        client, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    volunteer = fx.setup_active_producer(
        client, legal_name="Vera Rubin", email="vera@patv.example"
    )
    channel = fx.create_channel(client, call_sign="PATV1", preemption_enabled=True)
    program = fx.setup_approved_program(
        client,
        owner["id"],
        title="Neighborhood Notes",
        runtime_seconds=1800,
        is_live=True,
        required_crew_roles=["CAMERA"],
    )
    slot = fx.book_slot(client, channel["id"], program["id"], "2026-08-20T18:00:00Z")
    assignment = fx.offer_crew(client, slot["id"], volunteer["id"], "CAMERA")
    fx.confirm_crew(client, assignment["id"], volunteer["id"])
    fx.set_clock(client, "2026-08-20T18:00:00Z")
    fx.air_slot(client, slot["id"], 640)
    asset = fx.list_assets_for_slot(client, slot["id"])[0]
    return volunteer, slot, assignment, asset


def test_provisional_variant_at_air_forces_views_and_volunteer_credit_to_zero(client):
    """The provisional score reflects reach alone even though credit is stored.

    PRD 3.9: "The `PROVISIONAL` variant is what the system computes the instant
    a program airs, when no on-demand view has yet been recorded and no
    volunteer credit has yet been read: it forces both `on_demand_views` and
    `volunteer_hours_tenths` to 0, so only the reach component contributes."

    PRD 3.9: "A slot airing with 640 measured households, an occupied footprint
    of 1920 seconds and a single confirmed volunteer — who completes with a
    credit of 6 tenths of an hour — scores 32.00 provisionally."

    PRD 3.5: "`credited_hours_tenths` is the slot's `occupied_seconds` divided
    by 360 and rounded **up** to a whole number of tenths of an hour"

    Design: Difficulty/dual_variant_calc/impact_index_provisional_vs_final_diverges_on_archive_asset
    """
    volunteer, _slot, assignment, asset = _aired_broadcast_with_one_camera_volunteer(client)

    assert asset["impact_variant"] == "PROVISIONAL"
    a.assert_index_equals(asset["community_impact_index"], 32.00)
    assert asset["volunteer_hours_tenths"] == 6
    assert asset["measured_households"] == 640
    assert asset["on_demand_views"] == 0
    assert asset["on_demand_status"] == "PENDING"

    completed = fx.read_crew(client, assignment["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["credited_hours_tenths"] == 6

    volunteer_after = fx.read_producer(client, volunteer["id"])
    a.assert_producer_counters(volunteer_after, volunteer_tenths=6, commitments=0)


def test_final_variant_rises_at_publication_and_again_once_views_land(client):
    """Publication recomputes the same broadcast under the FINAL variant.

    PRD 3.9: "Recomputed as `FINAL` at publication, with views still at 0 and 6
    volunteer tenths in hand, it scores 33.20. Once 250 on-demand views are
    recorded, it scores 48.20."

    PRD 3.9: "Publication stamps `published_at` with the current logical
    instant, computes `retain_until`, recomputes `community_impact_index` under
    the `FINAL` variant, sets `impact_variant` to `FINAL`, and increments the
    asset's `version` by 1."

    Design: Difficulty/dual_variant_calc/impact_index_provisional_vs_final_diverges_on_archive_asset
    """
    _volunteer, _slot, _assignment, asset = _aired_broadcast_with_one_camera_volunteer(client)
    provisional_index = asset["community_impact_index"]

    published = fx.publish_asset(client, asset["id"], "STANDARD_24M")

    assert published["impact_variant"] == "FINAL"
    a.assert_index_equals(published["community_impact_index"], 33.20)
    a.assert_instant_equals(published["retain_until"], "2028-08-20T18:00:00Z", "retain_until")
    assert abs(float(published["community_impact_index"]) - float(provisional_index) - 1.20) < 0.005

    with_views = fx.record_views(client, asset["id"], 250)

    a.assert_index_equals(with_views["community_impact_index"], 48.20)
    assert with_views["on_demand_views"] == 250
    assert with_views["impact_variant"] == "FINAL"
