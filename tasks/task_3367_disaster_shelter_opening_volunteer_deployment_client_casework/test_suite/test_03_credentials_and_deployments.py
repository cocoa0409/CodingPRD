"""Volunteer credentialing, the deployable pool and deployment approval."""
from test_helpers import (
    ApiErrorId,
    create_deployment_payload,
    create_operation,
    create_region,
    create_shelter_operation,
    create_shelter_site,
    create_volunteer,
    inspect_site,
    refresh_credentials,
    request_deployment,
    set_clock,
    setup_open_shelter,
    validate_error,
    validate_success,
)


def test_recall_releases_the_volunteer_without_touching_credentials(api):
    """PRD §2.6: "Recall releases them: the volunteer returns to `AVAILABLE`, which is what
    makes a recalled volunteer immediately re-deployable."

    PRD §2.6: "The two are orthogonal: a volunteer with `EXPIRED` credentials can still be
    `AVAILABLE`, and a volunteer with `ACTIVE` credentials can be `RESTING`."

    Design: Difficulty/non_linear_state_machine/volunteer_two_independent_state_dimensions
    """
    bundle = setup_open_shelter()
    coord = bundle["coordinator_headers"]

    before = validate_success(api.get_volunteer(bundle["volunteer_id"], coord))
    assert before["credential_status"] == "ACTIVE"
    assert before["deployment_availability"] == "DEPLOYED"

    recalled = validate_success(
        api.recall_deployment(bundle["deployment_id"], coord))
    assert recalled["status"] == "RECALLED"

    after = validate_success(api.get_volunteer(bundle["volunteer_id"], coord))
    assert after["credential_status"] == "ACTIVE", (
        "the credential dimension is untouched by a recall")
    assert after["deployment_availability"] == "AVAILABLE"


def test_end_of_rotation_parks_the_volunteer_in_resting(api):
    """PRD §3.4: "Ending a rotation sets the deployment to `ROTATION_ENDED`, moves the
    volunteer's `deployment_availability` to `RESTING` — they are off duty, not yet back in the
    pool — and adds the deployment's `rotation_days` to the volunteer's
    `rotation_days_used_ytd`."

    PRD §2.6: "Refreshing credentials is the universal reset: it always leaves the volunteer
    `ACTIVE` and `AVAILABLE`, whether they were `PENDING`, `EXPIRED`, `RESTING` or
    `UNAVAILABLE` beforehand, which is how a resting volunteer is returned to the deployable
    pool."

    Design: Difficulty/non_linear_state_machine/volunteer_two_independent_state_dimensions
    """
    bundle = setup_open_shelter(rotation_days=7)
    coord = bundle["coordinator_headers"]
    volunteer_hdr = bundle["volunteer_headers"]
    manager = bundle["manager_headers"]

    shift = validate_success(api.create_shift(
        {"volunteer_deployment_id": bundle["deployment_id"],
         "shelter_operation_id": bundle["shelter_id"],
         "functional_area": "REGISTRATION",
         "shift_start_at": "2026-09-03T08:00:00Z",
         "shift_end_at": "2026-09-03T16:00:00Z"},
        manager), 201)
    set_clock("2026-09-03T07:30:00Z")
    validate_success(api.check_in_shift(shift["id"], volunteer_hdr))

    deployment = validate_success(api.end_rotation(bundle["deployment_id"], volunteer_hdr))
    assert deployment["status"] == "ROTATION_ENDED"

    resting = validate_success(api.get_volunteer(bundle["volunteer_id"], coord))
    assert resting["deployment_availability"] == "RESTING"
    assert resting["credential_status"] == "ACTIVE"
    assert resting["rotation_days_used_ytd"] == 7

    reinstated = validate_success(api.refresh_credentials(bundle["volunteer_id"], coord))
    assert reinstated["credential_status"] == "ACTIVE"
    assert reinstated["deployment_availability"] == "AVAILABLE"


def test_expired_credential_blocks_deployment_approval(api):
    """PRD §2.5: "A deployment request or an approval that involves a volunteer whose
    `credential_status` is not `ACTIVE`, or whose availability is not `AVAILABLE`, or whose
    requested `role_code` does not appear in that volunteer's `qualified_role_codes`, is refused
    with `ERR_VOLUNTEER_NOT_CREDENTIALED` at HTTP status 409."

    Design: Difficulty/cross_entity_state_dependency/deployment_approval_requires_active_credential
    """
    bundle = setup_open_shelter(open_the_shelter=False)
    coord = bundle["coordinator_headers"]

    # PRD §2.5 gates the *request* as well as the approval, so the pending
    # deployment has to be raised while the volunteer is still ACTIVE/AVAILABLE:
    # recall the fixture's deployment to release them, then request.
    validate_success(api.recall_deployment(bundle["deployment_id"], coord))
    second = request_deployment(
        bundle["volunteer_id"], bundle["operation_id"],
        shelter_operation_id=bundle["shelter_id"], role_code="SHELTER_MANAGER",
        travel_mode="AIR", rotation_start_at="2026-10-06T00:00:00Z", rotation_days=14)

    # The credential refresh happened at the 2026-09-01 default clock and lasts 30 days.
    set_clock("2026-10-05T00:00:00Z")
    expired = validate_success(api.get_volunteer(bundle["volunteer_id"], coord))
    assert expired["credential_status"] == "EXPIRED"
    assert expired["deployment_availability"] == "UNAVAILABLE"

    resp = api.approve_deployment(second["id"], coord)
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_CREDENTIALED)


def test_credential_refresh_reinstates_the_volunteer_and_prices_the_trip(api):
    """PRD §3.4: "That refresh is also the recovery path for every degraded condition — a
    `PENDING` volunteer becomes deployable, an `EXPIRED` volunteer is reinstated."

    PRD §3.4: "An `AIR` deployment costs a base of 45,000 cents plus 2,500 cents for each day by
    which the rotation exceeds 14 days, counting only the excess and never a negative amount."

    Design: Difficulty/cross_entity_state_dependency/deployment_approval_requires_active_credential
    """
    bundle = setup_open_shelter(open_the_shelter=False)
    coord = bundle["coordinator_headers"]

    # Raise the pending deployment while the volunteer is still ACTIVE, then let
    # the 30-day credential lapse (PRD §2.5 gates the request as well).
    validate_success(api.recall_deployment(bundle["deployment_id"], coord))
    pending = request_deployment(
        bundle["volunteer_id"], bundle["operation_id"],
        shelter_operation_id=bundle["shelter_id"], role_code="SHELTER_MANAGER",
        travel_mode="AIR", rotation_start_at="2026-10-06T00:00:00Z", rotation_days=14)

    set_clock("2026-10-05T00:00:00Z")
    validate_error(api.approve_deployment(pending["id"], coord),
                   ApiErrorId.ERR_VOLUNTEER_NOT_CREDENTIALED)

    refreshed = validate_success(
        api.refresh_credentials(bundle["volunteer_id"], coord))
    assert refreshed["credential_status"] == "ACTIVE"

    approved = validate_success(
        api.approve_deployment(pending["id"], coord))
    assert approved["status"] == "APPROVED"
    assert approved["travel_cost_cents"] == 45000, (
        "a 14-day AIR rotation pays the base fare alone")


def test_approving_a_deployment_reserves_the_volunteer(api):
    """PRD §2.6: "Approval prices the trip and reserves the volunteer, moving their availability
    to `DEPLOYED`."

    PRD §2.6: "The region's `deployed_volunteer_count` counts volunteers of that region whose
    `deployment_availability` is `DEPLOYED`."

    Design: Difficulty/compensating_invariant/region_available_volunteer_count_conserved
    """
    region = create_region()
    operation = create_operation(region["id"])
    site = create_shelter_site(region["id"])
    inspect_site(site["id"], site["version"])
    volunteer = refresh_credentials(create_volunteer(region["id"])["id"])
    shelter = create_shelter_operation(site["id"], operation["id"])

    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}

    before = validate_success(api.get_region(region["id"], coord))
    assert before["available_volunteer_count"] == 1
    assert before["deployed_volunteer_count"] == 0

    deployment = request_deployment(
        volunteer["id"], operation["id"], shelter_operation_id=shelter["id"])
    validate_success(api.approve_deployment(deployment["id"], coord))

    during = validate_success(api.get_region(region["id"], coord))
    assert during["available_volunteer_count"] == 0
    assert during["deployed_volunteer_count"] == 1


def test_recall_restores_the_region_deployable_headcount(api):
    """PRD §3.1: "each affected volunteer's `deployment_availability` returns to `AVAILABLE`,
    and the `available_volunteer_count` and `deployed_volunteer_count` of every affected
    volunteer's home region are recomputed."

    Design: Difficulty/compensating_invariant/region_available_volunteer_count_conserved
    """
    region = create_region()
    operation = create_operation(region["id"])
    site = create_shelter_site(region["id"])
    inspect_site(site["id"], site["version"])
    volunteer = refresh_credentials(create_volunteer(region["id"])["id"])
    shelter = create_shelter_operation(site["id"], operation["id"])

    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}

    deployment = request_deployment(
        volunteer["id"], operation["id"], shelter_operation_id=shelter["id"])
    validate_success(api.approve_deployment(deployment["id"], coord))

    recalled = validate_success(api.recall_deployment(deployment["id"], coord))
    assert recalled["status"] == "RECALLED"

    after = validate_success(api.get_region(region["id"], coord))
    assert after["available_volunteer_count"] == 1
    assert after["deployed_volunteer_count"] == 0


def test_expired_credential_error_precedes_the_shelter_mismatch_error(api):
    """PRD §2.11: "Fifth, the credentialing and site-approval gates of §2.5. Sixth, the interval
    collision checks of §2.7. Seventh, the uniqueness and workload caps ... Eighth, cross-entity
    reference authorization."

    PRD §2.5: "A deployment request or an approval that involves a volunteer whose
    `credential_status` is not `ACTIVE` ... is refused with `ERR_VOLUNTEER_NOT_CREDENTIALED` at
    HTTP status 409."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_expired_credential_mismatched_shelter
    """
    region = create_region()
    op1 = create_operation(region["id"], incident_code="DR-9101", incident_type="FLOOD")
    op2 = create_operation(region["id"], incident_code="DR-9102", incident_type="WILDFIRE")
    site = create_shelter_site(region["id"])
    inspect_site(site["id"], site["version"])
    volunteer = refresh_credentials(create_volunteer(region["id"])["id"])

    so1 = create_shelter_operation(site["id"], op1["id"])
    so2 = create_shelter_operation(site["id"], op2["id"])
    assert so1["id"] != so2["id"]

    set_clock("2026-10-05T00:00:00Z")
    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}
    expired = validate_success(api.get_volunteer(volunteer["id"], coord))
    assert expired["credential_status"] == "EXPIRED"

    resp = api.create_deployment(
        {"volunteer_id": volunteer["id"], "disaster_relief_operation_id": op1["id"],
         "shelter_operation_id": so2["id"], "role_code": "SHELTER_MANAGER",
         "travel_mode": "AIR", "rotation_start_at": "2026-10-06T00:00:00Z",
         "rotation_days": 14},
        coord)
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_CREDENTIALED)


def test_shelter_mismatch_alone_is_reported_as_the_referential_error(api):
    """PRD §3.4: "When a `shelter_operation_id` is supplied, it must belong to the same disaster
    relief operation as the deployment's `disaster_relief_operation_id`; a mismatch is refused
    with `ERR_DEPLOYMENT_SHELTER_MISMATCH` at HTTP status 409."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_expired_credential_mismatched_shelter
    """
    region = create_region()
    op1 = create_operation(region["id"], incident_code="DR-9101", incident_type="FLOOD")
    op2 = create_operation(region["id"], incident_code="DR-9102", incident_type="WILDFIRE")
    site = create_shelter_site(region["id"])
    inspect_site(site["id"], site["version"])
    volunteer = refresh_credentials(create_volunteer(region["id"])["id"])
    so2 = create_shelter_operation(site["id"], op2["id"])

    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}
    active = validate_success(api.get_volunteer(volunteer["id"], coord))
    assert active["credential_status"] == "ACTIVE"

    resp = api.create_deployment(
        {"volunteer_id": volunteer["id"], "disaster_relief_operation_id": op1["id"],
         "shelter_operation_id": so2["id"], "role_code": "SHELTER_MANAGER",
         "travel_mode": "AIR", "rotation_start_at": "2026-09-03T00:00:00Z",
         "rotation_days": 14},
        coord)
    validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_SHELTER_MISMATCH)


def test_approving_a_deployment_twice_is_rejected(api):
    """PRD §2.7: "a request to move a resource that is not in a state admitting the requested
    transition is refused with `ERR_INVALID_STATE` at HTTP status 409."

    Design: Corner/state_machines/deployment_double_approve_rejected
    """
    bundle = setup_open_shelter(open_the_shelter=False)
    coord = bundle["coordinator_headers"]

    # The fixture's own deployment is already approved, so raise a fresh request to
    # exercise the double approve. Its rotation starts well beyond the AIR lead time
    # so the deployment is still observable in APPROVED.
    validate_success(api.recall_deployment(bundle["deployment_id"], coord))
    pending = request_deployment(
        bundle["volunteer_id"], bundle["operation_id"],
        shelter_operation_id=bundle["shelter_id"], role_code="SHELTER_MANAGER",
        travel_mode="AIR", rotation_start_at="2026-09-20T00:00:00Z", rotation_days=14)

    first = validate_success(api.approve_deployment(pending["id"], coord))
    assert first["travel_cost_cents"] == 45000

    resp = api.approve_deployment(pending["id"], coord)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    still = validate_success(api.get_deployment(pending["id"], coord))
    assert still["travel_cost_cents"] == 45000
    assert still["status"] == "APPROVED"


def test_travel_pricing_applies_the_air_and_ground_constants(api):
    """PRD §3.4: "An `AIR` deployment costs a base of 45,000 cents plus 2,500 cents for each day
    by which the rotation exceeds 14 days."

    PRD §3.4: "A `GROUND` deployment costs 55 cents for each of those miles plus 12,000 cents
    for each day by which the rotation exceeds 7 days."

    Design: Corner/calculations/travel_cost_air_and_ground_constants
    """
    region_gl = create_region()
    region_nw = create_region(code="NW", name="Northwest", state_codes=["WA", "OR"],
                              coordinator_user_id="rc_nw", volunteer_pool_target=25,
                              authorized_agency_codes=["FEMA"])
    operation = create_operation(region_gl["id"])
    site = create_shelter_site(region_gl["id"])
    inspect_site(site["id"], site["version"])
    shelter = create_shelter_operation(site["id"], operation["id"])

    vol_gl = refresh_credentials(create_volunteer(region_gl["id"])["id"])
    vol_nw = refresh_credentials(create_volunteer(
        region_nw["id"], full_name="Eli Nakamura")["id"])

    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}

    air = request_deployment(
        vol_gl["id"], operation["id"], shelter_operation_id=shelter["id"],
        role_code="SHELTER_MANAGER", travel_mode="AIR",
        rotation_start_at="2026-09-03T00:00:00Z", rotation_days=15)
    ground = request_deployment(
        vol_nw["id"], operation["id"], shelter_operation_id=shelter["id"],
        role_code="SHELTER_MANAGER", travel_mode="GROUND",
        rotation_start_at="2026-09-03T00:00:00Z", rotation_days=8)

    approved_air = validate_success(api.approve_deployment(air["id"], coord))
    approved_ground = validate_success(api.approve_deployment(ground["id"], coord))

    assert approved_air["travel_cost_cents"] == 47500
    assert approved_ground["travel_cost_cents"] == 34000


def test_rotation_longer_than_the_cap_is_refused_at_creation(api):
    """PRD §2.7: "A rotation is at least 1 day and at most 21 days long, enforced when the
    deployment is requested; a value above 21 is refused with `ERR_ROTATION_TOO_LONG` at HTTP
    status 422."

    Design: Corner/validations/rotation_length_cap_rejected_at_creation
    """
    bundle = setup_open_shelter(open_the_shelter=False)
    coord = bundle["coordinator_headers"]

    # PRD §2.11 ranks the credentialing gate above the rotation cap, so the
    # volunteer has to be free for the cap itself to be the reported error.
    validate_success(api.recall_deployment(bundle["deployment_id"], coord))

    resp = api.create_deployment(
        create_deployment_payload(
            bundle["volunteer_id"], bundle["operation_id"],
            shelter_operation_id=bundle["shelter_id"], rotation_days=22),
        coord)
    validate_error(resp, ApiErrorId.ERR_ROTATION_TOO_LONG)

    accepted = validate_success(api.create_deployment(
        create_deployment_payload(
            bundle["volunteer_id"], bundle["operation_id"],
            shelter_operation_id=bundle["shelter_id"], rotation_days=21),
        coord), 201)
    assert accepted["rotation_days"] == 21, "21 days sits exactly on the inclusive boundary"


def test_annual_rotation_cap_is_enforced_at_approval(api):
    """PRD §2.7: "A volunteer may accumulate at most 40 rotation days in the year to date,
    enforced when a deployment is approved: if the volunteer's `rotation_days_used_ytd` plus the
    deployment's `rotation_days` exceeds 40, the approval is refused with
    `ERR_ANNUAL_ROTATION_CAP` at HTTP status 422."

    Design: Corner/validations/annual_rotation_cap_enforced_at_approval
    """
    bundle = setup_open_shelter(rotation_days=21)
    coord = bundle["coordinator_headers"]
    manager = bundle["manager_headers"]
    volunteer_hdr = bundle["volunteer_headers"]

    shift = validate_success(api.create_shift(
        {"volunteer_deployment_id": bundle["deployment_id"],
         "shelter_operation_id": bundle["shelter_id"],
         "functional_area": "REGISTRATION",
         "shift_start_at": "2026-09-03T08:00:00Z",
         "shift_end_at": "2026-09-03T16:00:00Z"},
        manager), 201)
    set_clock("2026-09-03T07:30:00Z")
    validate_success(api.check_in_shift(shift["id"], volunteer_hdr))
    validate_success(api.end_rotation(bundle["deployment_id"], volunteer_hdr))

    used = validate_success(api.get_volunteer(bundle["volunteer_id"], coord))
    assert used["rotation_days_used_ytd"] == 21

    validate_success(api.refresh_credentials(bundle["volunteer_id"], coord))
    second = request_deployment(
        bundle["volunteer_id"], bundle["operation_id"],
        shelter_operation_id=bundle["shelter_id"], role_code="SHELTER_MANAGER",
        travel_mode="AIR", rotation_start_at="2026-10-01T00:00:00Z", rotation_days=21)

    resp = api.approve_deployment(second["id"], coord)
    validate_error(resp, ApiErrorId.ERR_ANNUAL_ROTATION_CAP)

    still = validate_success(api.get_deployment(second["id"], coord))
    assert still["status"] == "REQUESTED"
