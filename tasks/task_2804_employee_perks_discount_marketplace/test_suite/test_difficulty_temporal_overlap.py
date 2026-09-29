"""Queue A — resource_temporal_overlap.

Every test below translates exactly one instance of §1.8's difficulty design
index; the `Design:` line of each docstring names it.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    AgreementStatus, ApiErrorId, MerchantStatus, PerkCategory, PlacementTier,
    ProgramPosture, SlotStatus, api_client, assertions as A, factories as F,
    fixtures as fx, make_merchant_headers,
)

FEATURED = PlacementTier.FEATURED


def _two_partners_on_one_storefront():
    """Two independent DINING/CA partners placing onto one `LIVE` storefront.

    The employer's roster holds exactly one eligible member, so
    `eligible_headcount` is 1 and the reach surcharge tier adds nothing to any
    placement price.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    first = fx.active_partner(
        merchant_overrides={
            "legal_name": "Bistro Uno", "contact_email": "ops@bistrouno.example",
        },
        commission_rate_bps=1200, placement_fee_base_cents=36000,
        employer_revenue_share_bps=2500,
    )
    second = fx.active_partner(
        merchant_overrides={
            "legal_name": "Cafe Duo", "contact_email": "ops@cafeduo.example",
        },
        commission_rate_bps=1200, placement_fee_base_cents=36000,
        employer_revenue_share_bps=2500,
    )
    programme = fx.live_employer(
        record_count=1, revenue_share_enabled=True, privacy_min_cohort_size=3,
        featured_categories=[PerkCategory.DINING.value], employee_count_declared=1,
    )
    employer = programme["employer"]
    assert employer["eligible_headcount"] == 1
    assert employer["program_posture"] == ProgramPosture.LIVE.value

    offers = [
        fx.approved_offer(
            partner["agreement"]["id"], partner["merchant"]["id"],
            title=title, min_spend_cents=1000, region_codes=["CA"],
            window_start="2026-08-01T00:00:00Z", window_end="2026-12-01T00:00:00Z",
        )
        for partner, title in (
            (first, "Bistro Uno dinner deal"), (second, "Cafe Duo lunch deal"),
        )
    ]
    return {
        "employer": employer,
        "merchants": [first["merchant"]["id"], second["merchant"]["id"]],
        "offers": offers,
    }


def _reserve_featured(scenario, index, start, end):
    """Reserve a FEATURED run, re-reading the offer for its current version."""
    merchant_id = scenario["merchants"][index]
    offer = fx.get_offer(scenario["offers"][index]["id"], merchant_id=merchant_id)
    return fx.reserve_slot(
        offer, scenario["employer"]["id"], merchant_id,
        placement_tier=FEATURED, slot_window_start=start, slot_window_end=end,
    )


def _attempt_featured(scenario, index, start, end):
    """The raw reservation response, for the runs that are meant to be refused."""
    merchant_id = scenario["merchants"][index]
    offer = fx.get_offer(scenario["offers"][index]["id"], merchant_id=merchant_id)
    return api_client.reserve_placement_slot(
        offer["id"],
        F.slot_payload(
            offer["version"], scenario["employer"]["id"], placement_tier=FEATURED,
            slot_window_start=start, slot_window_end=end,
        ),
        make_merchant_headers(merchant_id),
    )


def test_two_touching_featured_runs_both_fit_inside_the_capacity_of_two():
    """A run beginning exactly when another ends intersects it, and still fits.

    PRD: "**Slot run intervals are closed on both ends.** A run occupies every instant from `slot_window_start` through `slot_window_end` inclusive, which means a run that begins at exactly the instant another run ends does intersect it."

    Design: Difficulty/resource_temporal_overlap/closed_interval_featured_slot_capacity_outranks_merchant_cooldown_separation
    """
    scenario = _two_partners_on_one_storefront()

    first = _reserve_featured(
        scenario, 0, "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
    )
    second = _reserve_featured(
        scenario, 1, "2026-09-05T00:00:00Z", "2026-09-09T00:00:00Z"
    )

    # 4 days * 36000 = 144000 base; headcount 1 -> 0 bps surcharge; gross 144000
    # sits in the 500 bps volume tier -> 7200 off -> 136800.
    A.assert_placement_fee_breakdown(
        first, slot_duration_days=4, base_fee_cents=144000, reach_surcharge_bps=0,
        reach_surcharge_cents=0, gross_fee_cents=144000, volume_discount_bps=500,
        volume_discount_cents=7200, placement_fee_cents=136800,
    )
    assert second["status"] == SlotStatus.RESERVED.value
    assert second["placement_fee_cents"] == 136800


def test_third_intersecting_featured_run_is_refused_by_capacity_not_cooldown():
    """Capacity is band 8's fourth rule, the cooldown its fifth; capacity wins.

    PRD: "At most two `FEATURED` slots whose status is `RESERVED` or `CONFIRMED` may share a single combination of storefront (`employer_id`) and offer `category` over intersecting run intervals. A reservation that would make a third such slot intersect two existing ones is refused with `ERR_SLOT_CAPACITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/closed_interval_featured_slot_capacity_outranks_merchant_cooldown_separation
    """
    scenario = _two_partners_on_one_storefront()
    _reserve_featured(scenario, 0, "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z")
    _reserve_featured(scenario, 1, "2026-09-05T00:00:00Z", "2026-09-09T00:00:00Z")

    # This run intersects both incumbents and also sits 0 days after Bistro
    # Uno's own earlier run, so it breaks capacity and separation at once.
    response = _attempt_featured(
        scenario, 0, "2026-09-05T00:00:00Z", "2026-09-06T00:00:00Z"
    )

    error = validate_error(response, ApiErrorId.SLOT_CAPACITY_CONFLICT)
    assert error["error_id"] != ApiErrorId.SLOT_COOLDOWN_CONFLICT


def test_releasing_one_run_frees_capacity_and_exposes_the_cooldown_refusal():
    """With capacity satisfied, the identical request meets the next rule down.

    PRD: "The gap is measured in whole days as the difference between the later run's `slot_window_start` and the earlier run's `slot_window_end`, divided by 86,400 seconds and floored; a pair of runs that intersect at all has a gap of zero days. A gap of fewer than seven days is refused with `ERR_SLOT_COOLDOWN_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/closed_interval_featured_slot_capacity_outranks_merchant_cooldown_separation
    """
    scenario = _two_partners_on_one_storefront()
    first = _reserve_featured(
        scenario, 0, "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
    )
    second = _reserve_featured(
        scenario, 1, "2026-09-05T00:00:00Z", "2026-09-09T00:00:00Z"
    )

    released = fx.release_slot(second["id"], release_reason="MERCHANT_WITHDREW")
    assert released["status"] == SlotStatus.RELEASED.value

    response = _attempt_featured(
        scenario, 0, "2026-09-05T00:00:00Z", "2026-09-06T00:00:00Z"
    )

    validate_error(response, ApiErrorId.SLOT_COOLDOWN_CONFLICT)
    assert fx.get_slot(first["id"])["status"] == SlotStatus.RESERVED.value


def _accepted_exclusive_agreement(legal_name, contact_email, window_start,
                                  window_end):
    """One `ACCEPTED` DINING/CA agreement asking for a named exclusivity window.

    Stopping at `ACCEPTED` is deliberate: the overlap check runs at activation,
    so the order in which the three lanes activate is what decides them.
    """
    merchant = fx.create_merchant(
        legal_name=legal_name, contact_email=contact_email,
        primary_category="DINING", region_codes=["CA"],
    )
    agreement = fx.create_agreement(
        merchant["id"], category="DINING", region_code="CA",
        exclusivity_requested=True,
    )
    fx.propose_round(
        agreement, commission_rate_bps=1200, placement_fee_base_cents=36000,
        employer_revenue_share_bps=2500,
        exclusivity_window_start=window_start, exclusivity_window_end=window_end,
    )
    accepted = fx.accept_agreement(agreement["id"], merchant["id"])
    assert accepted["status"] == AgreementStatus.ACCEPTED.value
    return merchant, accepted


def _three_exclusivity_bids():
    """An incumbent, an overlapping challenger and a merely touching successor."""
    fx.set_clock("2026-08-01T00:00:00Z")
    incumbent = _accepted_exclusive_agreement(
        "Bistro Uno", "ops@bistrouno.example",
        "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
    )
    challenger = _accepted_exclusive_agreement(
        "Cafe Duo", "ops@cafeduo.example",
        "2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z",
    )
    successor = _accepted_exclusive_agreement(
        "Deli Tres", "ops@delitres.example",
        "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z",
    )
    return incumbent, challenger, successor


def test_overlapping_exclusivity_window_is_refused_and_leaves_the_lane_accepted():
    """A genuine intersection on one (category, region) lane blocks activation.

    PRD: "A genuine intersection is refused with `ERR_EXCLUSIVITY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/half_open_exclusivity_windows_collide_on_overlap_but_admit_a_touching_successor
    """
    incumbent, challenger, _successor = _three_exclusivity_bids()

    granted = fx.activate_agreement(incumbent[1]["id"])
    A.assert_fields(granted, {
        "status": AgreementStatus.ACTIVE.value,
        "exclusivity_granted": True,
    }, "agreement")

    response = api_client.activate_agreement(
        challenger[1]["id"], fx.make_partner_manager_headers()
    )

    validate_error(response, ApiErrorId.EXCLUSIVITY_OVERLAP)
    refused = fx.get_agreement(challenger[1]["id"])
    A.assert_fields(refused, {
        "status": AgreementStatus.ACCEPTED.value,
        "exclusivity_granted": False,
    }, "agreement")
    assert fx.get_merchant(challenger[0]["id"])["status"] == (
        MerchantStatus.IN_NEGOTIATION.value
    )


def test_touching_exclusivity_window_is_granted_because_the_bounds_are_half_open():
    """The successor starts exactly where the incumbent ends, so it may proceed.

    PRD: "Exclusivity windows are **half-open**: a window runs from `exclusivity_window_start` inclusive to `exclusivity_window_end` exclusive, so two windows that merely touch — where the existing window's end equals the new window's start — do not overlap and activation proceeds."

    Design: Difficulty/resource_temporal_overlap/half_open_exclusivity_windows_collide_on_overlap_but_admit_a_touching_successor
    """
    incumbent, _challenger, successor = _three_exclusivity_bids()
    fx.activate_agreement(incumbent[1]["id"])

    activated = fx.activate_agreement(successor[1]["id"])

    A.assert_fields(activated, {
        "status": AgreementStatus.ACTIVE.value,
        "exclusivity_granted": True,
    }, "agreement")
    assert fx.get_merchant(successor[0]["id"])["status"] == MerchantStatus.ACTIVE.value
