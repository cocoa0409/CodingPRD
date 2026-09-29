"""Values sitting exactly on a threshold, and the value one step below it.

Every threshold in this API is inclusive.  Each pair below pins the boundary from
both sides: the tier cut at 75 risk points, the volume-discount band at a gross
subtotal of 8,000 cents, and the training expiry instant itself.
"""

from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_counters,
    assert_instant_equals,
    assert_money_equals,
    assert_state,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    SCREENING_VENDOR_HEADERS,
    make_club_admin_headers,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}
SS101 = {
    "code": "SS101",
    "title": "Abuse Prevention Core",
    "validity_days": 365,
    "delivery_mode": "ONLINE",
    "required_for_tiers": ["TIER_1", "TIER_2", "TIER_3"],
    "pass_score": 80,
}


def _empty_club(api: ApiClient) -> Dict[str, Any]:
    """A club with no members, no audits and no orders, so history_points is zero."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    return get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)


def _head_coach(api: ApiClient, club_id: str, name: str, email: str, dob: str, codes) -> Any:
    return api.register_member(
        {
            "club_id": club_id,
            "full_name": name,
            "email": email,
            "role_type": "HEAD_COACH",
            "has_minor_athlete_contact": True,
            "date_of_birth": dob,
            "jurisdiction_codes": list(codes),
        },
        make_club_admin_headers(club_id),
    )


def test_exactly_seventy_five_risk_points_demands_the_top_screening_tier(
    api: ApiClient,
) -> None:
    """40 role points, 25 contact points and two extra jurisdictions land on the cut.

    PRD 3.1 says:
    "The jurisdiction component contributes 5 points for each jurisdiction beyond the first — that is, five points multiplied by the number of entries in `jurisdiction_codes` less one, never taken below zero — and is capped at 15 points, so a screen covering four or more states contributes the same 15 as one covering six."
    "The score selects a screening tier and writes it to `required_tier`: a score that reaches or exceeds 75 demands `TIER_3`, otherwise a score that reaches or exceeds 45 demands `TIER_2`, otherwise `TIER_1`. Both boundaries are inclusive, so a score of exactly 75 is `TIER_3` and a score of exactly 45 is `TIER_2`."

    Design: Difficulty/boundary_precision_check/tier_threshold_at_exactly_seventy_five_risk_points
    """
    club = _empty_club(api)

    member = validate_success(
        _head_coach(
            api, club["id"], "Nadia Cross", "nadia.cross@alpha.test", "1981-01-21",
            ["CA", "NV", "OR"],
        ),
        201,
    )

    assert_counters(member, risk_points=75)
    assert_state(member, "required_tier", "TIER_3")
    assert_state(member, "screening_status", "UNSCREENED")


def test_one_jurisdiction_code_fewer_scores_seventy_and_demands_the_middle_tier(
    api: ApiClient,
) -> None:
    """Removing a single jurisdiction code costs five points and drops a whole tier.

    PRD 3.1 says:
    "The role component contributes 40 points for a `HEAD_COACH`, 30 for an `ASSISTANT_COACH`, 25 for a `CHAPERONE`, 20 for an `OFFICIAL`, and 10 for a `VOLUNTEER`."
    "The contact component contributes 25 points when `has_minor_athlete_contact` is true and nothing when it is false."
    "The score selects a screening tier and writes it to `required_tier`: a score that reaches or exceeds 75 demands `TIER_3`, otherwise a score that reaches or exceeds 45 demands `TIER_2`, otherwise `TIER_1`. Both boundaries are inclusive, so a score of exactly 75 is `TIER_3` and a score of exactly 45 is `TIER_2`."

    Design: Difficulty/boundary_precision_check/tier_threshold_at_exactly_seventy_five_risk_points
    """
    club = _empty_club(api)

    member = validate_success(
        _head_coach(
            api, club["id"], "Owen Hale", "owen.hale@alpha.test", "1982-02-22", ["CA", "NV"]
        ),
        201,
    )

    assert_counters(member, risk_points=70)
    assert_state(member, "required_tier", "TIER_2")
    assert_state(member, "screening_status", "UNSCREENED")


def _volunteer(api: ApiClient, club_id: str, name: str, email: str, dob: str, codes) -> Dict[str, Any]:
    return get_success_data(
        api.register_member(
            {
                "club_id": club_id,
                "full_name": name,
                "email": email,
                "role_type": "VOLUNTEER",
                "has_minor_athlete_contact": False,
                "date_of_birth": dob,
                "jurisdiction_codes": list(codes),
            },
            make_club_admin_headers(club_id),
        ),
        201,
    )


SIX_STATES = ["CA", "NV", "OR", "WA", "AZ", "ID"]
FIVE_STATES = ["CA", "NV", "OR", "WA", "AZ"]


def _two_volunteers(api: ApiClient) -> Dict[str, Any]:
    club = _empty_club(api)
    wide = _volunteer(api, club["id"], "Pia Marek", "pia.marek@alpha.test", "1993-07-13", SIX_STATES)
    narrow = _volunteer(
        api, club["id"], "Gil Amari", "gil.amari@alpha.test", "1994-08-14", FIVE_STATES
    )
    return {"club": club, "wide": wide, "narrow": narrow}


def _order_for(api: ApiClient, club_id: str, member_id: str):
    club = get_success_data(api.get_club(club_id, NGB_ADMIN_HEADERS))
    return api.order_screening(
        member_id,
        {"expedited": False, "expected_club_version": club["version"]},
        make_club_admin_headers(club_id),
    )


def test_a_gross_subtotal_of_exactly_eight_thousand_cents_earns_the_five_percent_band(
    api: ApiClient,
) -> None:
    """Six jurisdictions put the gross subtotal exactly on the lower discount band.

    PRD 3.2 says:
    "Step two computes the multi-jurisdiction surcharge as 1,100 cents for each jurisdiction beyond the first — that is, 1,100 multiplied by the order's `jurisdiction_count` less one, never taken below zero."
    "Step four selects the volume-discount rate **from that pre-discount gross subtotal**: 10 percent when the gross subtotal reaches or exceeds 12,000 cents, otherwise 5 percent when it reaches or exceeds 8,000 cents, otherwise no discount at all."
    "Step five multiplies the gross subtotal by the selected rate and rounds the product half up to a whole cent, recording it as `discount_cents`."

    Design: Difficulty/boundary_precision_check/volume_discount_band_at_exactly_eight_thousand_gross_subtotal
    """
    setup = _two_volunteers(api)
    assert_state(setup["wide"], "required_tier", "TIER_1")

    order = validate_success(_order_for(api, setup["club"]["id"], setup["wide"]["id"]), 201)

    assert_counters(order, jurisdiction_count=6)
    assert_money_equals(order, "gross_subtotal_cents", 8000)
    assert_money_equals(order, "discount_cents", 400)
    assert_money_equals(order, "expedite_cents", 0)
    assert_money_equals(order, "charged_cents", 7600)


def test_a_gross_subtotal_one_surcharge_below_the_band_earns_no_discount_at_all(
    api: ApiClient,
) -> None:
    """Five jurisdictions fall short of the band, and the escrow records both charges.

    PRD 3.2 says:
    "Step four selects the volume-discount rate **from that pre-discount gross subtotal**: 10 percent when the gross subtotal reaches or exceeds 12,000 cents, otherwise 5 percent when it reaches or exceeds 8,000 cents, otherwise no discount at all."
    "Step eight adds the net subtotal and the expedite fee to give `charged_cents`."
    "A successful order is written in status `ORDERED` with all four money fields stamped, the club's `escrow_balance_cents` is debited by `charged_cents`, the club's `version` advances by one, and the member's screening dimension moves `UNSCREENED → SCREENING_ORDERED` (or `CLEARED → SCREENING_ORDERED`, or `EXPIRED → SCREENING_ORDERED`, all three governed by the identical preconditions and side effects)."

    Design: Difficulty/boundary_precision_check/volume_discount_band_at_exactly_eight_thousand_gross_subtotal
    """
    setup = _two_volunteers(api)
    assert_state(setup["narrow"], "required_tier", "TIER_1")
    get_success_data(_order_for(api, setup["club"]["id"], setup["wide"]["id"]), 201)

    order = validate_success(_order_for(api, setup["club"]["id"], setup["narrow"]["id"]), 201)

    assert_counters(order, jurisdiction_count=5)
    assert_money_equals(order, "gross_subtotal_cents", 6900)
    assert_money_equals(order, "discount_cents", 0)
    assert_money_equals(order, "charged_cents", 6900)

    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(club, "escrow_balance_cents", 485500)
    assert_money_equals(club, "total_funded_cents", 500000)


def _member_current_until_one_year_out(api: ApiClient) -> Dict[str, Any]:
    """A compliant member whose training expires exactly one year after the epoch."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _volunteer(api, club["id"], "Jo Rivas", "jo.rivas@alpha.test", "1997-09-17", ["CA"])
    order = get_success_data(
        api.order_screening(
            member["id"],
            {"expedited": False, "expected_club_version": club["version"]},
            admin,
        ),
        201,
    )
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    get_success_data(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    assignment = get_success_data(
        api.assign_training(
            {"member_id": member["id"], "course_code": "SS101", "due_at": "2026-09-01T00:00:00Z"},
            admin,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], admin))
    completed = get_success_data(api.complete_training(assignment["id"], {"score": 90}, admin))
    assert_instant_equals(completed["expires_at"], "2027-08-01T00:00:00.000Z")
    return {"club": club, "member": member, "assignment": completed}


def test_one_second_before_the_training_expiry_the_member_is_still_current(
    api: ApiClient,
) -> None:
    """At 2027-07-31T23:59:59Z nothing has lapsed yet.

    PRD 3.4 says:
    "Otherwise, if the logical clock has reached or passed that expiry, `training_status` is `LAPSED` — the boundary is inclusive, so at exactly the expiry instant the training is already lapsed. Otherwise `training_status` is `CURRENT`."
    PRD 2.5 says:
    "An `ACTIVE` membership becomes `LAPSED` once the clock reaches or passes the member's `eligible_through`, again inclusively."

    Design: Difficulty/boundary_precision_check/training_lapse_at_exactly_the_expiry_instant
    """
    setup = _member_current_until_one_year_out(api)
    admin = make_club_admin_headers(setup["club"]["id"])
    get_success_data(api.set_clock("2027-07-31T23:59:59Z", NGB_ADMIN_HEADERS))

    projection = validate_success(
        api.get_eligibility_projection(setup["member"]["id"], admin, variant="AUDIT_SNAPSHOT")
    )

    assert_state(projection, "training_status", "CURRENT")
    assert_state(projection, "contact_eligibility", "ELIGIBLE")
    assert_state(projection, "membership_status", "ACTIVE")


def test_at_exactly_the_training_expiry_instant_training_and_membership_have_both_lapsed(
    api: ApiClient,
) -> None:
    """One second later, at the stored expiry itself, both dimensions have already moved.

    PRD 3.4 says:
    "Otherwise, if the logical clock has reached or passed that expiry, `training_status` is `LAPSED` — the boundary is inclusive, so at exactly the expiry instant the training is already lapsed. Otherwise `training_status` is `CURRENT`."
    "Otherwise the value is `RESTRICTED` when any interim measure against the member stands in status `ACTIVE`, or when the screening dimension is `UNSCREENED`, `SCREENING_ORDERED`, `FLAGGED`, or `EXPIRED`, or when `training_status` is `NEVER` or `LAPSED`."
    PRD 2.5 says:
    "Four transitions are driven by the clock rather than by a caller, and all four are **evaluated lazily**: the platform applies them at the moment a read or a mutation next touches the affected row, so a client that repositions the clock and then reads sees the post-lapse state without any intervening request."

    Design: Difficulty/boundary_precision_check/training_lapse_at_exactly_the_expiry_instant
    """
    setup = _member_current_until_one_year_out(api)
    admin = make_club_admin_headers(setup["club"]["id"])
    get_success_data(api.set_clock("2027-08-01T00:00:00Z", NGB_ADMIN_HEADERS))

    projection = validate_success(
        api.get_eligibility_projection(setup["member"]["id"], admin, variant="AUDIT_SNAPSHOT")
    )

    assert_state(projection, "training_status", "LAPSED")
    assert_state(projection, "contact_eligibility", "RESTRICTED")
    assert_state(projection, "membership_status", "LAPSED")
    assert_state(projection, "screening_status", "CLEARED")

    member = validate_success(api.get_member(setup["member"]["id"], NGB_ADMIN_HEADERS))
    assert_instant_equals(member["eligible_through"], "2027-08-01T00:00:00.000Z")
