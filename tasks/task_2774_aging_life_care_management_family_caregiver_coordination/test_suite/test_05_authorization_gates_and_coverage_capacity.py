"""The care-plan state an engagement may be raised under, the aggregate
caregiver-capacity guard, and the order the two creation guards fire in.
"""
from test_helpers import (
    PRACTICE_ADMIN,
    api_client,
    authorization_state_payload,
    authorize_service_authorization,
    convene_conference,
    create_service_authorization_payload,
    family_approve_plan,
    get_success_data,
    make_care_manager_headers,
    make_practice_supervisor_headers,
    propose_service_authorization,
    read_authorization,
    read_care_plan,
    read_client,
    record_conference_decision,
    register_vendor,
    schedule_conference,
    send_plan_for_family_approval,
    setup_active_care_plan_scenario,
    setup_draft_care_plan_scenario,
    uniform_domain_scores,
    update_vendor_payload,
    validate_error,
    validate_paginated,
)

_DRAFT_PLAN_CLIENT = {
    "full_name": "Katarina Delacroix",
    "residence_setting": "PRIVATE_HOME",
    "retainer_floor_cents": 0,
    "authorized_concurrent_caregivers": 2,
}


def test_01_an_engagement_may_not_be_raised_under_a_plan_that_is_not_active():
    """A DRAFT plan is not yet a commitment, so no vendor coverage may be bought
    against it and no authorization row is left behind.

    PRD: "The parent care plan must be `ACTIVE` at proposal time, else `ERR_CARE_PLAN_NOT_ACTIVE`, and the named vendor's `standing` must not be `BARRED`, else `ERR_VENDOR_BARRED`."

    Design: Difficulty/cross_entity_state_dependency/authorization_authorize_requires_active_care_plan_state
    """
    scenario = setup_draft_care_plan_scenario(
        clock="2026-08-15T09:00:00Z",
        client_overrides=dict(_DRAFT_PLAN_CLIENT),
        scores=uniform_domain_scores(2),
    )
    plan = read_care_plan(scenario.care_plan_id)
    assert plan["status"] == "DRAFT"

    response = api_client.create_service_authorization(
        create_service_authorization_payload(
            scenario.care_plan_id,
            scenario.vendor_id,
            plan["version"],
            coverage_start="2026-09-01T08:00:00Z",
            coverage_end="2026-09-01T16:00:00Z",
            concurrent_caregivers=1,
            hourly_cost_cents=4_000,
        ),
        make_care_manager_headers(scenario.care_manager_id),
    )
    validate_error(response, "ERR_CARE_PLAN_NOT_ACTIVE", 409)

    listing = api_client.list_service_authorizations(
        PRACTICE_ADMIN, {"care_plan_id": scenario.care_plan_id}
    )
    rows, meta = validate_paginated(listing)
    assert rows == []
    assert meta["total_count"] == 0
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 0


def test_02_family_approval_is_what_moves_the_plan_into_the_active_state():
    """Only the surrogate's approval activates the plan, and that same step
    advances the client into active care.

    PRD: "Activation then does a great deal: it records the approving surrogate in `approved_by_contact_id`, sets `activated_at` to the logical clock's current instant, and recomputes `coverage_gap_flag`, which is true for a freshly activated plan because no authorization has yet been raised under it."

    Design: Difficulty/cross_entity_state_dependency/authorization_authorize_requires_active_care_plan_state
    """
    scenario = setup_draft_care_plan_scenario(
        clock="2026-08-15T09:00:00Z",
        client_overrides=dict(_DRAFT_PLAN_CLIENT),
        scores=uniform_domain_scores(2),
    )
    send_plan_for_family_approval(scenario.care_plan_id, scenario.care_manager_id)
    activated = family_approve_plan(scenario.care_plan_id, scenario.surrogate_id)

    assert activated["status"] == "ACTIVE"
    assert activated["approved_by_contact_id"] == scenario.surrogate_id
    assert activated["activated_at"] is not None
    assert activated["coverage_gap_flag"] is True
    assert read_client(scenario.client_id)["status"] == "ACTIVE_CARE"


def test_03_the_same_engagement_authorizes_once_the_plan_is_active():
    """With the plan active the identical coverage window is proposed and then
    authorized, and its hours land on the client.

    PRD: "The client's `authorized_coverage_hours` is at all times the sum of `coverage_hours` over that client's service authorizations whose `auth_status` is `AUTHORIZED` or `ACTIVE`; rows that are `PROPOSED`, `SUSPENDED` or `TERMINATED` are excluded from the sum entirely."

    Design: Difficulty/cross_entity_state_dependency/authorization_authorize_requires_active_care_plan_state
    """
    scenario = setup_draft_care_plan_scenario(
        clock="2026-08-15T09:00:00Z",
        client_overrides=dict(_DRAFT_PLAN_CLIENT),
        scores=uniform_domain_scores(2),
    )
    send_plan_for_family_approval(scenario.care_plan_id, scenario.care_manager_id)
    family_approve_plan(scenario.care_plan_id, scenario.surrogate_id)

    authorization = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-01T08:00:00Z",
        coverage_end="2026-09-01T16:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    assert authorization["auth_status"] == "PROPOSED"
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 0

    authorized = authorize_service_authorization(
        authorization["id"], scenario.supervisor_id
    )
    assert authorized["auth_status"] == "AUTHORIZED"
    assert authorized["coverage_hours"] == 8

    client = read_client(scenario.client_id)
    assert client["authorized_coverage_hours"] == 8
    assert client["risk_posture"] == "ROUTINE"
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False


def _capacity_scenario():
    """A client capped at two concurrent caregivers, already carrying an AUTHORIZED
    daytime window staffed by both of them.
    """
    scenario = setup_active_care_plan_scenario(
        clock="2026-08-17T09:00:00Z",
        client_overrides={
            "full_name": "Mira Ashgrove",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
            "authorized_concurrent_caregivers": 2,
        },
        scores=uniform_domain_scores(2),
    )
    daytime = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-01T08:00:00Z",
        coverage_end="2026-09-01T16:00:00Z",
        concurrent_caregivers=2,
        hourly_cost_cents=4_000,
    )
    daytime = authorize_service_authorization(daytime["id"], scenario.supervisor_id)
    assert daytime["coverage_hours"] == 16
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 16
    return scenario, daytime


def test_04_a_third_caregiver_inside_the_same_window_breaches_the_cap():
    """The standing window already staffs both agreed caregivers, so one more
    inside the identical interval is refused.

    PRD: "That total must be less than or equal to the client's `authorized_concurrent_caregivers`; a total exactly equal to the cap passes, and anything beyond it is rejected with `ERR_COVERAGE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/client_caregiver_capacity_closed_interval_aggregate_overlap
    """
    scenario, _daytime = _capacity_scenario()
    overlapping = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-01T08:00:00Z",
        coverage_end="2026-09-01T16:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    response = api_client.patch_service_authorization_state(
        overlapping["id"],
        authorization_state_payload("AUTHORIZED"),
        make_practice_supervisor_headers(scenario.supervisor_id),
    )
    validate_error(response, "ERR_COVERAGE_CAPACITY_EXCEEDED", 409)

    assert read_authorization(overlapping["id"])["auth_status"] == "PROPOSED"
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 16


def test_05_windows_that_merely_touch_at_an_endpoint_count_as_intersecting():
    """An evening window beginning at the exact instant the daytime window ends
    still intersects it, because coverage intervals are closed at both ends.

    PRD: "Coverage windows are **closed intervals**: both `coverage_start` and `coverage_end` are inclusive, so two windows that merely touch at an endpoint are treated as overlapping."

    Design: Difficulty/resource_temporal_overlap/client_caregiver_capacity_closed_interval_aggregate_overlap
    """
    scenario, _daytime = _capacity_scenario()
    touching = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-01T16:00:00Z",
        coverage_end="2026-09-01T20:00:00Z",
        concurrent_caregivers=2,
        hourly_cost_cents=4_000,
    )
    response = api_client.patch_service_authorization_state(
        touching["id"],
        authorization_state_payload("AUTHORIZED"),
        make_practice_supervisor_headers(scenario.supervisor_id),
    )
    validate_error(response, "ERR_COVERAGE_CAPACITY_EXCEEDED", 409)

    assert read_authorization(touching["id"])["auth_status"] == "PROPOSED"
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 16


def test_06_a_genuinely_disjoint_window_authorizes_and_the_hours_accumulate():
    """A window opening an hour after the daytime one closes shares no instant with
    it, so both may stand and the client's coverage total is their sum.

    PRD: "For the candidate authorization's coverage window, sum `concurrent_caregivers` across that client's *other* authorizations whose `auth_status` is `AUTHORIZED` or `ACTIVE` and whose closed coverage interval intersects the candidate's closed interval — touching endpoints count as intersecting — then add the candidate's own `concurrent_caregivers`."

    Design: Difficulty/resource_temporal_overlap/client_caregiver_capacity_closed_interval_aggregate_overlap
    """
    scenario, _daytime = _capacity_scenario()
    blocked = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-01T16:00:00Z",
        coverage_end="2026-09-01T20:00:00Z",
        concurrent_caregivers=2,
        hourly_cost_cents=4_000,
    )
    api_client.patch_service_authorization_state(
        blocked["id"],
        authorization_state_payload("AUTHORIZED"),
        make_practice_supervisor_headers(scenario.supervisor_id),
    )

    disjoint = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-01T17:00:00Z",
        coverage_end="2026-09-01T21:00:00Z",
        concurrent_caregivers=2,
        hourly_cost_cents=4_000,
    )
    authorized = authorize_service_authorization(disjoint["id"], scenario.supervisor_id)
    assert authorized["auth_status"] == "AUTHORIZED"
    assert authorized["coverage_hours"] == 8

    assert read_authorization(blocked["id"])["auth_status"] == "PROPOSED"
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 24


def _barred_vendor_and_unratified_decision():
    """An ACTIVE plan, a barred vendor, an approved control vendor, and a family
    decision that has been recorded but never ratified.
    """
    scenario = setup_active_care_plan_scenario(
        clock="2026-08-12T09:00:00Z",
        client_overrides={
            "full_name": "Cornelia Achterberg",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        vendor_overrides={
            "name": "Ridgeline Care Partners",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
        scores=uniform_domain_scores(1),
    )
    control_vendor = register_vendor(
        name="Northgate Home Care",
        vendor_type="HOME_CARE",
        has_referral_relationship=False,
    )
    conference = schedule_conference(
        scenario.client_id, [scenario.surrogate_id], scenario.care_manager_id
    )
    convene_conference(
        conference["id"], [scenario.surrogate_id], scenario.care_manager_id
    )
    decision = record_conference_decision(
        conference["id"],
        scenario.surrogate_id,
        scenario.care_manager_id,
        decision_type="VENDOR_ENGAGEMENT",
    )
    assert decision["status"] == "RECORDED"

    barred = get_success_data(
        api_client.update_vendor(
            scenario.vendor_id, update_vendor_payload(standing="BARRED"), PRACTICE_ADMIN
        )
    )
    assert barred["standing"] == "BARRED"
    return scenario, control_vendor, decision


def test_07_a_barred_vendor_is_reported_ahead_of_the_unratified_decision():
    """The proposal names both a barred vendor and a decision that was never
    ratified; the business-safety guard sits above the referential one, so vendor
    standing is what the caller is told.

    PRD: "Because many operations carry several independent guards, the order in which those guards run is part of the contract."

    Design: Difficulty/priority_pair_validation_conflict/barred_vendor_beats_unratified_decision_on_authorization_creation
    """
    scenario, _control, decision = _barred_vendor_and_unratified_decision()
    plan_before = read_care_plan(scenario.care_plan_id)

    response = api_client.create_service_authorization(
        create_service_authorization_payload(
            scenario.care_plan_id,
            scenario.vendor_id,
            plan_before["version"],
            coverage_start="2026-09-01T08:00:00Z",
            coverage_end="2026-09-01T16:00:00Z",
            concurrent_caregivers=1,
            hourly_cost_cents=4_000,
            authorizing_decision_id=decision["id"],
        ),
        make_care_manager_headers(scenario.care_manager_id),
    )
    validate_error(response, "ERR_VENDOR_BARRED", 422)

    listing = api_client.list_service_authorizations(
        PRACTICE_ADMIN, {"care_plan_id": scenario.care_plan_id}
    )
    rows, meta = validate_paginated(listing)
    assert rows == []
    assert meta["total_count"] == 0
    assert read_care_plan(scenario.care_plan_id)["version"] == plan_before["version"]


def test_08_an_approved_vendor_lets_the_unratified_decision_surface():
    """Swapping in a vendor in good standing clears the earlier rung, and the
    identical unratified authorizing decision is then reported as the illegal
    pairing it is.

    PRD: "When a ratified family decision authorized this vendor, that decision is named in the optional `authorizing_decision_id`; it must be a conference decision whose `status` is `RATIFIED` and whose conference belongs to the care plan's client, else `ERR_ENTITY_RELATIONSHIP_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/barred_vendor_beats_unratified_decision_on_authorization_creation
    """
    scenario, control_vendor, decision = _barred_vendor_and_unratified_decision()
    plan_before = read_care_plan(scenario.care_plan_id)

    response = api_client.create_service_authorization(
        create_service_authorization_payload(
            scenario.care_plan_id,
            control_vendor["id"],
            plan_before["version"],
            coverage_start="2026-09-01T08:00:00Z",
            coverage_end="2026-09-01T16:00:00Z",
            concurrent_caregivers=1,
            hourly_cost_cents=4_000,
            authorizing_decision_id=decision["id"],
        ),
        make_care_manager_headers(scenario.care_manager_id),
    )
    validate_error(response, "ERR_ENTITY_RELATIONSHIP_INVALID", 422)

    listing = api_client.list_service_authorizations(
        PRACTICE_ADMIN, {"care_plan_id": scenario.care_plan_id}
    )
    rows, meta = validate_paginated(listing)
    assert rows == []
    assert meta["total_count"] == 0
    assert read_care_plan(scenario.care_plan_id)["version"] == plan_before["version"]
