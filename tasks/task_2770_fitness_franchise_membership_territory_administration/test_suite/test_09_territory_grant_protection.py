"""The radial protection metric at exact tangency on a territory grant.

An incumbent 5.0 km circle at (34.0, −118.0). A 3.0 km candidate one tenth of a degree of
longitude east is 8.5 km away and needs exactly 8.5 km, so its clearance rounds to 0.000
and must be granted. One hundredth of a degree closer is the first refusal.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_franchisee,
    create_territory,
    create_territory_payload,
)

BRAND = TEST_USERS["brand_administrator_headers"]


def _incumbent_circle_and_two_rival_operators() -> dict:
    """One granted 5.0 km circle plus two operators still holding nothing."""
    incumbent = create_franchisee(
        legal_name="Meridian Fitness LLC", contact_email="ops@meridianfit.example"
    )
    eastgate = create_franchisee(
        legal_name="Eastgate Fitness LLC", contact_email="ops@eastgatefit.example"
    )
    westgate = create_franchisee(
        legal_name="Westgate Fitness LLC", contact_email="ops@westgatefit.example"
    )
    territory = create_territory(
        incumbent["id"], center_lat=34.0, center_lng=-118.0, protected_radius_km=5.0
    )
    return {
        "incumbent": incumbent,
        "eastgate": eastgate,
        "westgate": westgate,
        "territory": territory,
    }


def _grant(franchisee_id: str, center_lng: float, protected_radius_km: float):
    return api_client.create_territory(
        create_territory_payload(
            franchisee_id,
            center_lat=34.0,
            center_lng=center_lng,
            protected_radius_km=protected_radius_km,
        ),
        BRAND,
    )


def test_a_circle_at_exact_tangency_is_granted_with_a_clearance_of_zero():
    """8.5 km of separation against a required 8.5 km leaves a clearance of exactly 0.000,
    which is not negative and therefore not an encroachment.

    PRD 3.1: "Rejection is strict: only a negative clearance is an encroachment, so two
    circles separated by precisely the sum of their radii plus the buffer produce a clearance
    of exactly 0.000 and are accepted, while a clearance of −0.001 is refused with
    `ERR_TERRITORY_ENCROACHMENT`."

    Design: Difficulty/boundary_precision_check/territory_protection_slack_of_exactly_zero_km_is_accepted
    """
    setup = _incumbent_circle_and_two_rival_operators()

    granted = validate_success(
        _grant(setup["eastgate"]["id"], -117.9, 3.0), expected_status=201
    )
    assert granted["status"] == "RESERVED"
    assert granted["protected_radius_km"] == 3.0
    assert granted["relocation_count"] == 0


def test_one_hundredth_of_a_degree_closer_is_refused_as_an_encroachment():
    """0.09 degrees of longitude is 7.65 km against the same 8.5 km requirement, a clearance
    of −0.850, so the grant is refused.

    PRD 3.1: "For each candidate territory, the north-south separation in kilometres is the
    difference between the proposed latitude and the candidate's `center_lat`, multiplied by
    111.0; the east-west separation in kilometres is the difference between the proposed
    longitude and the candidate's `center_lng`, multiplied by 85.0."

    Design: Difficulty/boundary_precision_check/territory_protection_slack_of_exactly_zero_km_is_accepted
    """
    setup = _incumbent_circle_and_two_rival_operators()

    response = _grant(setup["westgate"]["id"], -118.09, 3.0)
    validate_error(response, ApiErrorId.ERR_TERRITORY_ENCROACHMENT.value)


def test_a_second_circle_for_the_same_operator_may_sit_right_on_top_of_the_first():
    """Self-overlap is not measured at all, so an identical centre and radius is granted
    without ever entering the candidate set.

    PRD 3.1: "Two territories owned by the same franchisee may overlap as freely as their
    owner likes, and are never candidates."

    Design: Difficulty/boundary_precision_check/territory_protection_slack_of_exactly_zero_km_is_accepted
    """
    setup = _incumbent_circle_and_two_rival_operators()

    second = validate_success(
        _grant(setup["incumbent"]["id"], -118.0, 5.0), expected_status=201
    )
    assert second["status"] == "RESERVED"
    assert second["protected_radius_km"] == 5.0
    assert second["relocation_count"] == 0


def test_the_refused_operator_ends_up_holding_no_trade_area_at_all():
    """The tangent grant was written and the encroaching one was not, which the per-operator
    listings show directly.

    PRD 3.1: "A granted territory is created `RESERVED` with `relocation_count` at 0, and it
    becomes `ACTIVE` only when its club actually opens."

    Design: Difficulty/boundary_precision_check/territory_protection_slack_of_exactly_zero_km_is_accepted
    """
    setup = _incumbent_circle_and_two_rival_operators()
    _grant(setup["eastgate"]["id"], -117.9, 3.0)
    _grant(setup["westgate"]["id"], -118.09, 3.0)

    accepted, accepted_meta = validate_paginated(
        api_client.list_territories(BRAND, params={"franchisee_id": setup["eastgate"]["id"]})
    )
    assert accepted_meta["total_count"] == 1
    assert accepted[0]["status"] == "RESERVED"
    _, refused_meta = validate_paginated(
        api_client.list_territories(BRAND, params={"franchisee_id": setup["westgate"]["id"]})
    )
    assert refused_meta["total_count"] == 0
