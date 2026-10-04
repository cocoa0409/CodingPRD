"""Ordinance profiles, the ancillary charge, and the late-cancellation bands."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, api_client
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_active_member,
    file_stay,
    confirm_stay,
    set_clock,
    host_version,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
)


def test_ca_brewery_layout_is_refused_on_the_ordinance_cap(api):
    """PRD §2.11: "The host's base capacity, measured as the count of its active
    parking sites, may not exceed the profile's nightly member site cap; the cap is
    inclusive, so a capacity exactly equal to the cap passes and one site beyond it
    fails."
    PRD §2.11: "Either violation on a platform onboarding or host-update decision is
    rejected with `ERR_ORDINANCE_CONSTRAINT` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/ordinance_cap_and_site_length_state_branch
    """
    host = declare_host(category="BREWERY", state_code="CA",
                        self_contained_required=False)
    declare_sites(
        host["id"], 4, labels=["B1", "B2", "B3", "B4"], site_class="BACK_IN",
        max_vehicle_length_feet=45, has_electric=True,
        electric_service_code="ELECTRIC_50A",
    )
    resp = api.decide_host(
        host["id"],
        {"action": "APPROVE", "reason": "declared",
         "expected_host_version": host_version(host["id"])},
        make_platform_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ORDINANCE_CONSTRAINT, 422)
    assert api.get_host(host["id"], make_host_operator_headers(host["id"])).json()[
        "data"
    ]["onboarding_status"] == "PENDING_REVIEW"


def test_byte_identical_layout_is_admitted_in_a_differently_capped_state(api):
    """PRD §2.11: "A host whose `state_code` and `category` pair appears in no
    profile is uncapped and is not forced to require self-contained rigs — the same
    category is treated differently in a different state, which is the point of
    keying on the pair rather than on either value alone."
    PRD §2.11: "`TX` / `FARM` 8" (the nightly member site cap for that pair).

    Design: Difficulty/combinatorial_formula/ordinance_cap_and_site_length_state_branch
    """
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)
    declare_sites(
        host["id"], 4, labels=["F1", "F2", "F3", "F4"], site_class="BACK_IN",
        max_vehicle_length_feet=45, has_electric=True,
        electric_service_code="ELECTRIC_50A",
    )
    resp = api.decide_host(
        host["id"],
        {"action": "APPROVE", "reason": "declared",
         "expected_host_version": host_version(host["id"])},
        make_platform_admin_headers(),
    )
    host = validate_success(resp)
    assert host["onboarding_status"] == "APPROVED", (
        "the same 4-site 45-foot layout the CA/BREWERY pair refuses is admitted "
        "under TX/FARM, proving the branch keys on the ordered pair"
    )


def _confirm_with_ancillary(plan_tier, home_state_code, vehicle_class, length_feet,
                            nights, party_size, electric_request_code,
                            guest_passes=None, arrival_date="2026-09-12"):
    """Approve a TX/FARM host with a 45-foot 50A site and confirm a stay on it,
    returning (host, member, stay)."""
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)
    declare_sites(
        host["id"], 1, labels=["F1"], site_class="BACK_IN",
        max_vehicle_length_feet=45, has_electric=True,
        electric_service_code="ELECTRIC_50A",
    )
    approve_host(host["id"])
    member, vehicle = setup_active_member(
        plan_tier=plan_tier, home_state_code=home_state_code,
        vehicle_class=vehicle_class, length_feet=length_feet,
    )
    if guest_passes is not None:
        r = api_client.member_subscription_action(
            member["id"],
            {"action": "SET_GUEST_PASSES", "guest_passes_remaining": guest_passes},
            make_platform_admin_headers(),
        )
        validate_success(r)
    stay = file_stay(
        host["id"], member["id"], vehicle["id"], arrival_date=arrival_date,
        nights=nights, party_size=party_size,
        electric_request_code=electric_request_code,
    )
    stay = confirm_stay(host["id"], stay["id"], site_label="F1")
    return host, member, stay


def test_ancillary_charge_applies_the_tier_discount_once_on_the_whole_subtotal(api):
    """PRD §3.4: "The discount amount is the subtotal multiplied by the plan's
    percentage and divided by 100, rounded half up to a whole cent. That discount is
    computed exactly once, on the whole subtotal: never per night and never per
    guest, since discounting each night separately and then adding would produce a
    different result on multi-night stays with a fractional discount."
    PRD §3.4: "A request for `ELECTRIC_50A` costs 1200 cents per night when the rig
    is a `CLASS_A` or a `FIFTH_WHEEL`, and 900 cents per night for every other
    vehicle class"

    Design: Difficulty/combinatorial_formula/constitutive_charge_rounding_order_inversion
    """
    # PREMIER, 3 nights of 50A on a CLASS_A rig, 9 people with 4 standing passes.
    # electric 1200*3 = 3600; billable guests 9-1-4 = 4 -> 2000; subtotal 5600;
    # PREMIER 20% -> 1120; charge 4480.
    host, member, stay = _confirm_with_ancillary(
        plan_tier="PREMIER", home_state_code="TX", vehicle_class="CLASS_A",
        length_feet=45, nights=3, party_size=9,
        electric_request_code="ELECTRIC_50A", guest_passes=4,
    )
    assert stay["ancillary_charge_cents"] == 4480


def test_ancillary_charge_caps_the_stored_total_at_the_hard_ceiling(api):
    """PRD §3.4: "The stored charge is the subtotal minus the discount, floored at
    zero and then capped at 25000 cents, so a large multi-night stay with several
    guests on a 50-ampere pedestal cannot exceed that hard cap"
    PRD §2.8: "The stay's ancillary total is then capped at 25000 cents after the
    tier discount has been applied, and floored at zero so the charge can never be
    negative."

    Design: Difficulty/combinatorial_formula/constitutive_charge_rounding_order_inversion
    """
    # CLASSIC, 20 nights of 50A on a FIFTH_WHEEL rig (1200/night), 8 party size,
    # no passes: electric 24000 + guests 3500 = 27500, no discount, capped 25000.
    host, member, stay = _confirm_with_ancillary(
        plan_tier="CLASSIC", home_state_code="TX", vehicle_class="FIFTH_WHEEL",
        length_feet=45, nights=20, party_size=8,
        electric_request_code="ELECTRIC_50A", guest_passes=0,
        arrival_date="2026-09-12",
    )
    assert stay["ancillary_charge_cents"] == 25000


def test_late_cancellation_fee_applies_the_middle_band_at_its_upper_bound(api):
    """PRD §3.5: "The lower band is inclusive: an ancillary charge of exactly 5000
    cents takes the middle band and bills 1250 cents, while 5001 cents takes the high
    band and bills 2750 cents."
    PRD §3.5: "Otherwise, when `ancillary_charge_cents` is at most 5000 cents, the
    fee is 15 percent of that ancillary charge, rounded half up to a whole cent, plus
    a flat 500 cents."

    Design: Difficulty/combinatorial_formula/constitutive_charge_rounding_order_inversion
    """
    # CLASSIC, 5 nights of 50A on a CLASS_C rig (900/night) = 4500, party 2 with 0
    # passes -> 500; subtotal 5000; no discount -> ancillary exactly 5000.
    set_clock("2026-06-01T00:00:00Z")
    host, member, stay = _confirm_with_ancillary(
        plan_tier="CLASSIC", home_state_code="TX", vehicle_class="CLASS_C",
        length_feet=30, nights=5, party_size=2,
        electric_request_code="ELECTRIC_50A", guest_passes=0,
        arrival_date="2026-06-10",
    )
    assert stay["ancillary_charge_cents"] == 5000
    # Three clear days of notice: inside the late band but short of the 7-day free
    # window, so the middle band bills 15% of 5000 plus the 500-cent flat.
    set_clock("2026-06-07T00:00:00Z")
    resp = api.cancel_stay_request(
        stay["id"], make_member_headers(member["id"])
    )
    cancelled = validate_success(resp)
    assert cancelled["request_status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 1250
    assert cancelled["request_depth"] == 1


def test_ancillary_charge_uses_the_class_rated_nightly_figure_for_a_trailer(api):
    """PRD §3.4: "A request for `ELECTRIC_50A` costs 1200 cents per night when the
    rig is a `CLASS_A` or a `FIFTH_WHEEL`, and 900 cents per night for every other
    vehicle class — a `CONVERSION_VAN` and a `CLASS_A` asking for the same 50-ampere
    pedestal therefore pay different nightly rates for the same service."

    Design: Difficulty/combinatorial_formula/constitutive_charge_rounding_order_inversion
    """
    set_clock("2026-09-01T00:00:00Z")
    host, member, stay = _confirm_with_ancillary(
        plan_tier="CLASSIC", home_state_code="TX", vehicle_class="TRAVEL_TRAILER",
        length_feet=30, nights=2, party_size=1,
        electric_request_code="ELECTRIC_50A", guest_passes=0,
    )
    # 900 * 2 = 1800, no guests, no discount.
    assert stay["ancillary_charge_cents"] == 1800