"""Damage assessment: the two fee variants and the insurance-tier selector."""
from test_helpers import (
    OPERATOR,
    api_client,
    approve_member_with_membership,
    assert_incident,
    assert_membership,
    create_pod,
    create_reservation,
    create_sponsored_membership,
    create_vehicle,
    open_incident,
    validate_success,
)


def _plus_tier_setup(repair_cost_cents):
    """Approved member with ACTIVE PLUS and PREMIUM memberships plus an OPEN damage incident."""
    member, membership = approve_member_with_membership(full_name="Dana Dual")
    # PRD §3.3: "exactly one ACTIVE primary membership may exist per member at a
    # time", so the two sponsored rows that carry the tier-selector fixture are
    # recorded non-primary on top of the approval's own primary row.
    create_sponsored_membership(member["id"], tier="PLUS", primary_flag=False)
    create_sponsored_membership(member["id"], tier="PREMIUM", primary_flag=False)
    pod = create_pod(name="Campus Hill", site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"])
    reservation = create_reservation(member["id"], pod["id"], vehicle["id"], vehicle["version"])
    incident = open_incident(
        reservation["id"], vehicle["id"], member["id"], repair_cost_cents=repair_cost_cents
    )
    return member, membership, pod, vehicle, reservation, incident


def test_assessment_writes_both_fee_variants_from_the_same_tier_selection():
    """PRD §3.13: "The estimate half is deliberately tier-blind: `damage_fee_estimate_cents`
    is `repair_cost_cents` multiplied by 0.50, rounded half-up, and ignores the membership
    tier entirely."
    PRD §3.13: "A `PLUS` membership carries a 2000-cent deductible and a member liability
    fraction of 0.10."

    Design: Difficulty/dual_variant_calc/incident_damage_fee_estimate_vs_final
    """
    member, membership, pod, vehicle, reservation, incident = _plus_tier_setup(30000)

    data = validate_success(
        api_client.party_split(
            incident["id"], {"expected_incident_version": incident["version"]}, OPERATOR
        ),
        200,
    )

    assert_incident(data)
    assert data["damage_fee_estimate_cents"] == 15000, (
        f"Estimate variant must ignore the tier: expected 15000, got {data['damage_fee_estimate_cents']}"
    )
    assert data["member_damage_fee_cents"] == 3000, (
        f"Final variant must be deductible 2000 + 0.10 * 30000: expected 3000, "
        f"got {data['member_damage_fee_cents']}"
    )
    assert data["damage_fee_estimate_cents"] != data["member_damage_fee_cents"], (
        "The estimate and final variants must diverge for a well-insured member"
    )


def test_assessment_selector_prefers_the_highest_ranked_active_tier():
    """PRD §3.13: "Among the member's membership rows whose status is `ACTIVE`, the selector
    takes the row whose `tier` has the highest rank in the order `PREMIUM` above `PLUS`
    above `STANDARD`; among rows of equal rank it takes the earliest `created_at`; and the
    member's `Member.id` and the membership's `Membership.id` never participate in the
    selection."

    Design: Difficulty/dual_variant_calc/incident_damage_fee_estimate_vs_final
    """
    member, membership, pod, vehicle, reservation, incident = _plus_tier_setup(30000)

    data = validate_success(
        api_client.party_split(
            incident["id"], {"expected_incident_version": incident["version"]}, OPERATOR
        ),
        200,
    )

    assert data["insurance_layer"] == "PREMIUM", (
        f"PREMIUM outranks PLUS, so the selector must pick it: got {data['insurance_layer']}"
    )
    # PREMIUM: deductible 3000, liability fraction 0.00 -> 3000 + 0 == 3000
    assert data["member_damage_fee_cents"] == 3000, (
        f"PREMIUM liability fraction is 0.00 so only the deductible remains: "
        f"expected 3000, got {data['member_damage_fee_cents']}"
    )
    assert data["member_damage_fee_cents"] != 15000, (
        "The fee of record must not fall back to the tier-blind estimate"
    )

    memberships = validate_success(api_client.list_member_memberships(member["id"], OPERATOR), 200)
    for row in memberships:
        assert_membership(row)