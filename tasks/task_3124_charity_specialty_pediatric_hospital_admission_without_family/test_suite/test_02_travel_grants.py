"""Travel support grant calculations: dual distance variants, tier boundaries,
and the grant endpoint's state gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    decide,
    open_review,
    cast_vote,
    set_clock,
    setup_accepted_application,
    setup_submitted_application,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Corner/endpoints
# ---------------------------------------------------------------------------

def test_travel_grant_conditional_on_accepted_state(api, care_headers):
    """PRD §3.7: "For an `ACCEPTED` application, a `CareCoordinator` may create a `TravelSupportGrant` by naming a `grant_type` of `TRAVEL`, `LODGING`, or `TRAVEL_AND_LODGING`."

    Design: Corner/endpoints/travel_grant_conditional_on_accepted_state
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(
        patient_full_name="Kid Grant", home_longitude=-120.364,
    )
    open_review(application["id"])

    resp = api.create_travel_grant(application["id"], "TRAVEL", care_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    data, meta = __import__("test_helpers").validate_paginated(
        api.list_travel_grants(application["id"], care_headers)
    )
    assert data == []


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc
# ---------------------------------------------------------------------------

def test_distance_eligibility_road_variant_governs(api, care_headers):
    """PRD §3.7: "The final reading, `road_distance_miles`, multiplies the straight-line distance by a road circuity factor of 1.3 and rounds to one decimal half-up."

    Design: Difficulty/dual_variant_calc/distance_eligibility_straight_line_vs_road
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application, _ = setup_accepted_application(
        patient_full_name="Kid Two", home_longitude=-120.364,
    )
    grant = validate_success(api.create_travel_grant(
        application["id"], "TRAVEL_AND_LODGING", care_headers,
    ), expected_status=201)
    assert grant["straight_line_distance_miles"] == pytest.approx(79.9, abs=0.05)
    assert grant["road_distance_miles"] == pytest.approx(103.9, abs=0.05)


def test_distance_eligibility_variants_disagree_on_eligibility(api, care_headers):
    """PRD §3.7: "Eligibility is decided on the road distance alone: `distance_eligible` is true exactly when `road_distance_miles` is at least 100.0 miles — the boundary is inclusive, so a family at exactly 100.0 road miles qualifies."

    Design: Difficulty/dual_variant_calc/distance_eligibility_straight_line_vs_road
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application, _ = setup_accepted_application(
        patient_full_name="Kid Two", home_longitude=-120.364,
    )
    grant = validate_success(api.create_travel_grant(
        application["id"], "TRAVEL_AND_LODGING", care_headers,
    ), expected_status=201)
    # The provisional reading (79.9 < 100.0) would say ineligible; the final
    # road variant (103.9 >= 100.0) governs.
    assert grant["straight_line_distance_miles"] < 100.0
    assert grant["road_distance_miles"] >= 100.0
    assert grant["distance_eligible"] is True
    assert grant["nightly_lodging_stipend_cents"] == 15000
    assert grant["travel_allowance_cents"] == 6032  # 58 * round(103.9) = 58 * 104


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula
# ---------------------------------------------------------------------------

def _setup_accepted_with_home(home_latitude, home_longitude, name):
    return setup_accepted_application(
        patient_full_name=name,
        home_latitude=home_latitude, home_longitude=home_longitude,
        hospital_overrides={"annual_capacity": 10},
    )


def test_travel_stipend_tiering_three_input_nonlinear_lodging(api, care_headers):
    """PRD §3.7: "The `nightly_lodging_stipend_cents` applies only to `LODGING` and `TRAVEL_AND_LODGING` grants: 15000 cents per night when the road distance is at least 100.0 and strictly below 300.0 miles, and 22500 cents per night when the road distance is at least 300.0 miles."

    Design: Difficulty/combinatorial_formula/travel_stipend_tiering_three_input_nonlinear
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, a_far, _ = _setup_accepted_with_home(40.0, -75.0, "Kid Far")
    lodging = validate_success(api.create_travel_grant(
        a_far["id"], "LODGING", care_headers,
    ), expected_status=201)
    # Road 3100.5 >= 300.0 -> tier-2 stipend; LODGING never pays mileage.
    assert lodging["road_distance_miles"] >= 300.0
    assert lodging["nightly_lodging_stipend_cents"] == 22500
    assert lodging["travel_allowance_cents"] == 0


def test_travel_stipend_tiering_cap_and_tier1(api, care_headers):
    """PRD §3.7: "The `travel_allowance_cents` applies only to `TRAVEL` and `TRAVEL_AND_LODGING` grants: 58 cents per road mile, with the road distance rounded to the nearest whole mile first, and the product capped at 100000 cents."

    Design: Difficulty/combinatorial_formula/travel_stipend_tiering_three_input_nonlinear
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, a_far, _ = _setup_accepted_with_home(40.0, -75.0, "Kid Far")
    _, _, _, a_mid, _ = _setup_accepted_with_home(45.0, -118.9298, "Kid Mid")

    travel = validate_success(api.create_travel_grant(
        a_far["id"], "TRAVEL", care_headers,
    ), expected_status=201)
    # 58 * 3100 = 179800 would exceed the 100000 cap.
    assert travel["nightly_lodging_stipend_cents"] == 0
    assert travel["travel_allowance_cents"] == 100000

    both = validate_success(api.create_travel_grant(
        a_mid["id"], "TRAVEL_AND_LODGING", care_headers,
    ), expected_status=201)
    assert both["road_distance_miles"] == pytest.approx(195.0, abs=0.05)
    assert both["nightly_lodging_stipend_cents"] == 15000
    assert both["travel_allowance_cents"] == 11310  # 58 * 195, under cap


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check
# ---------------------------------------------------------------------------

def test_road_distance_exactly_100_is_eligible_distances(api, care_headers):
    """PRD §3.7: "Eligibility is decided on the road distance alone: `distance_eligible` is true exactly when `road_distance_miles` is at least 100.0 miles — the boundary is inclusive, so a family at exactly 100.0 road miles qualifies."

    Design: Difficulty/boundary_precision_check/road_distance_exactly_100_is_eligible
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application, _ = setup_accepted_application(
        patient_full_name="Kid Edge", home_longitude=-120.4265,
    )
    grant = validate_success(api.create_travel_grant(
        application["id"], "TRAVEL_AND_LODGING", care_headers,
    ), expected_status=201)
    assert grant["straight_line_distance_miles"] == pytest.approx(76.9, abs=0.05)
    assert grant["road_distance_miles"] == pytest.approx(100.0, abs=0.05)
    assert grant["distance_eligible"] is True


def test_road_distance_exactly_100_earns_tier1_and_uncapped_allowance(api, care_headers):
    """PRD §3.7: "Otherwise the benefit splits by grant type. The `nightly_lodging_stipend_cents` applies only to `LODGING` and `TRAVEL_AND_LODGING` grants: 15000 cents per night when the road distance is at least 100.0 and strictly below 300.0 miles, and 22500 cents per night when the road distance is at least 300.0 miles."

    Design: Difficulty/boundary_precision_check/road_distance_exactly_100_is_eligible
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application, _ = setup_accepted_application(
        patient_full_name="Kid Edge", home_longitude=-120.4265,
    )
    grant = validate_success(api.create_travel_grant(
        application["id"], "TRAVEL_AND_LODGING", care_headers,
    ), expected_status=201)
    assert grant["nightly_lodging_stipend_cents"] == 15000
    assert grant["travel_allowance_cents"] == 5800  # 58 * round(100.0)
