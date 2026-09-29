"""Access-control breadth: who may act, and which acts are personal."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    assert_acre_feet,
    assert_cfs,
    assert_instant,
    assert_score,
    assert_total_count,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSESSMENT_CERTIFIED,
    ASSESSMENT_DRAFT,
    DRAWDOWN_ACTIVE,
    DRAWDOWN_COORDINATED,
    DRAWDOWN_REQUESTED,
    EVENT_EMERGENCY,
    HAZARD_SIGNIFICANT,
    HAZARD_UNCLASSIFIED,
    INSPECTION_ACCEPTED,
    INSPECTION_SUBMITTED,
    PERMIT_SUBMITTED,
    PERMIT_TYPE_REPAIR,
    PERMIT_UNDER_ENGINEERING_REVIEW,
    REG_REGISTERED,
    SAFETY_CONDITIONALLY_SATISFACTORY,
    SAFETY_UNRATED,
)
from test_helpers.test_users import make_engineer_headers, make_owner_headers


# ---------------------------------------------------------------------------
# The inventory belongs to program staff
# ---------------------------------------------------------------------------
@pytest.fixture()
def seeded_world(program):
    """An owner, an engineer and a reach, with the inventory still empty."""
    owner = program.create_owner()
    engineer = program.create_engineer()
    reach = program.create_reach()
    return {"owner": owner, "engineer": engineer, "reach": reach}


def test_an_engineer_cannot_add_a_dam_to_the_inventory(api, program, seeded_world):
    """Engineers write against dams but may not register one.

    PRD 2.1: "`ProgramAdmin` is state dam safety program staff: they own the inventory, the inspection calendar, enforcement, the fee ledger and the state's intervention authority."

    Design: Corner/rbac/dam_registration_by_an_engineer_returns_forbidden_role
    """
    validate_error(
        api.create_dam(
            f.dam_payload(seeded_world["owner"]["id"], seeded_world["reach"]["id"]),
            make_engineer_headers(seeded_world["engineer"]["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    _rows, meta = validate_paginated(api.list_dams(program.admin))
    assert_total_count(meta, 0)


def test_the_administrators_identical_payload_registers_the_dam(
    api, program, seeded_world
):
    """The same body from program staff creates an unclassified, unrated dam.

    PRD 3.1: "A newly registered dam is `UNCLASSIFIED` on hazard, `UNRATED` on safety and `REGISTERED` on regulatory posture."

    Design: Corner/rbac/dam_registration_by_an_engineer_returns_forbidden_role
    """
    dam = validate_success(
        api.create_dam(
            f.dam_payload(seeded_world["owner"]["id"], seeded_world["reach"]["id"]),
            program.admin,
        ),
        201,
    )
    assert dam["hazard_class"] == HAZARD_UNCLASSIFIED
    assert dam["safety_status"] == SAFETY_UNRATED
    assert dam["regulatory_status"] == REG_REGISTERED
    assert dam["version"] == 1


# ---------------------------------------------------------------------------
# Certification is the engineer's professional act
# ---------------------------------------------------------------------------
@pytest.fixture()
def draft_assessment(program, base):
    """One DRAFT consequence assessment awaiting certification."""
    return program.create_assessment(f.assessment_a1(base.dam_id), base.engineer_a_id)


def test_neither_the_owner_nor_the_administrator_may_certify(
    api, program, base, draft_assessment
):
    """Two other roles are refused, and the draft is left exactly as it was.

    PRD 3.2: "Only an `Engineer` may certify, the assessment must still be `DRAFT` (moving `DRAFT → CERTIFIED`), the acting engineer's licence must be active, the engineer must be certified for the dam's current hazard class, and the dam must not be `BREACHED`."

    Design: Corner/rbac/certification_by_the_owner_returns_forbidden_role
    """
    for headers in (make_owner_headers(base.owner_id), program.admin):
        validate_error(
            api.certify_assessment(draft_assessment["id"], None, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )

    still_draft = validate_success(
        api.get_assessment(draft_assessment["id"], program.admin)
    )
    assert still_draft["status"] == ASSESSMENT_DRAFT
    assert program.get_dam(base.dam_id)["hazard_class"] == HAZARD_UNCLASSIFIED


def test_the_engineers_certification_publishes_the_hazard_class(
    api, program, base, draft_assessment
):
    """The engineer's own act is what moves the classification onto the dam.

    PRD 3.2: "Because link 1 replaced the classification source, the dam's `hazard_class` is set to the new `certified_hazard_class`, its `current_consequence_score` to the new `certified_score`, its `eap_required` flag is recomputed, and its `next_inspection_due_at` and `inspection_overdue` are recomputed on the new class's interval."

    Design: Corner/rbac/certification_by_the_owner_returns_forbidden_role
    """
    certified = validate_success(
        api.certify_assessment(
            draft_assessment["id"], None, base.engineer_a_headers
        )
    )
    assert certified["status"] == ASSESSMENT_CERTIFIED

    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_SIGNIFICANT
    assert_score(dam["current_consequence_score"], 6.60)


# ---------------------------------------------------------------------------
# The drawdown workflow is split across two opaque roles
# ---------------------------------------------------------------------------
@pytest.fixture()
def emergency_release(program, base):
    """An escalated event on a SIGNIFICANT dam with a 300-cfs order still REQUESTED."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    event = program.declare_event(base.dam_id)
    program.set_clock("2026-08-01T04:00:00Z")
    program.escalate_event(event["id"], 1042.5)
    order = program.request_drawdown(
        base.dam_id, event["id"], requested_release_cfs=300
    )
    return {"event": event, "order": order}


def test_the_coordinator_may_not_commit_the_reach(api, program, base, emergency_release):
    """Committing scarce capacity is program staff's decision, not the coordinator's.

    PRD 3.7: "**Coordination** is where scarcity bites, and it is a `ProgramAdmin` act on an order that is `REQUESTED` whose event is still `MONITORING` or `EMERGENCY`."

    Design: Corner/rbac/coordinator_and_admin_attempts_at_each_others_exclusive_actions_are_rejected
    """
    order_id = emergency_release["order"]["id"]
    before = program.get_reach(base.reach_id)["version"]
    validate_error(
        api.coordinate_drawdown(
            order_id, f.coordinate_payload(before), program.coordinator
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    assert program.get_drawdown(order_id)["status"] == DRAWDOWN_REQUESTED
    reach = program.get_reach(base.reach_id)
    assert reach["version"] == before
    assert_cfs(reach["committed_release_cfs"], 0, "committed_release_cfs")


def test_the_administrator_may_not_open_the_gates(api, program, base, emergency_release):
    """Staff commit the capacity, but only the coordinator may start the release.

    PRD 3.7: "**Activation** opens the gates, and only the emergency coordinator may do it, on an order that is `COORDINATED`."

    Design: Corner/rbac/coordinator_and_admin_attempts_at_each_others_exclusive_actions_are_rejected
    """
    order_id = emergency_release["order"]["id"]
    coordinated = program.coordinate_drawdown(order_id, reach_id=base.reach_id)
    assert coordinated["status"] == DRAWDOWN_COORDINATED
    assert_cfs(
        program.get_reach(base.reach_id)["committed_release_cfs"],
        300,
        "committed_release_cfs",
    )
    assert_acre_feet(
        program.get_dam(base.dam_id)["committed_drawdown_acre_ft"],
        148.760,
        "committed_drawdown_acre_ft",
    )

    validate_error(
        api.activate_drawdown(order_id, None, program.admin),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    assert program.get_drawdown(order_id)["status"] == DRAWDOWN_COORDINATED


def test_each_role_acting_in_turn_completes_the_pair(api, program, base, emergency_release):
    """Coordination then activation succeeds, and both roles can read the order.

    PRD 3.7: "Activation moves the order `COORDINATED → ACTIVE`, stamps `activated_at`, and changes no commitment — the reach capacity and dam storage were taken at coordination."

    Design: Corner/rbac/coordinator_and_admin_attempts_at_each_others_exclusive_actions_are_rejected
    """
    order_id = emergency_release["order"]["id"]
    program.coordinate_drawdown(order_id, reach_id=base.reach_id)
    activated = validate_success(
        api.activate_drawdown(order_id, None, program.coordinator)
    )
    assert activated["status"] == DRAWDOWN_ACTIVE
    assert activated["activated_at"] is not None
    assert program.get_event(emergency_release["event"]["id"])["status"] == EVENT_EMERGENCY
    assert_cfs(
        program.get_reach(base.reach_id)["committed_release_cfs"],
        300,
        "committed_release_cfs",
    )

    as_admin = validate_success(api.get_drawdown_order(order_id, program.admin))
    as_coordinator = validate_success(
        api.get_drawdown_order(order_id, program.coordinator)
    )
    assert as_admin["id"] == as_coordinator["id"] == order_id


# ---------------------------------------------------------------------------
# Acceptance is refused to the person, not to the role
# ---------------------------------------------------------------------------
@pytest.fixture()
def submitted_visit(program, base):
    """An inspection submitted by engineer A rating the dam CONDITIONALLY_SATISFACTORY."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    visit = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        visit["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:00:00Z",
        condition_rating=SAFETY_CONDITIONALLY_SATISFACTORY,
        deficiencies=[],
    )
    return visit


def test_the_submitting_engineer_cannot_accept_their_own_findings(
    api, program, base, submitted_visit
):
    """The refusal is about the acting identity, not about the role it carries.

    PRD 3.3: "Either a `ProgramAdmin` or an `Engineer` may accept, the inspection must be `SUBMITTED`, the acting engineer's licence must be active, and the acting `X-User-ID` must differ from the inspection's engineer of record — accepting one's own submission is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/submitting_engineer_cannot_accept_their_own_inspection
    """
    validate_error(
        api.accept_inspection(submitted_visit["id"], None, base.engineer_a_headers),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        409,
    )

    unchanged = validate_success(
        api.get_inspection(submitted_visit["id"], program.admin)
    )
    assert unchanged["status"] == INSPECTION_SUBMITTED
    assert unchanged["accepted_by_user_id"] is None
    assert program.get_dam(base.dam_id)["safety_status"] == SAFETY_UNRATED


def test_a_second_engineer_accepts_and_the_rating_lands(
    api, program, base, submitted_visit
):
    """The identical role in different hands moves the dam's safety dial.

    PRD 3.3: "The dam's `safety_status` is then set to the accepted inspection's `condition_rating`, whatever it was."

    Design: Corner/rbac/submitting_engineer_cannot_accept_their_own_inspection
    """
    accepted = validate_success(
        api.accept_inspection(submitted_visit["id"], None, base.engineer_b_headers)
    )
    assert accepted["status"] == INSPECTION_ACCEPTED
    assert accepted["accepted_by_user_id"] == base.engineer_b_id
    assert (
        program.get_dam(base.dam_id)["safety_status"]
        == SAFETY_CONDITIONALLY_SATISFACTORY
    )


def test_the_accepted_periodic_visit_rebuilds_the_schedule(
    api, program, base, submitted_visit
):
    """A SIGNIFICANT dam's next visit falls 24 months after the accepted one.

    PRD 3.3: "`next_inspection_due_at` is that baseline advanced by the hazard class's interval in whole calendar months — 12 months at `HIGH`, 24 at `SIGNIFICANT`, 60 at `LOW` and 60 while `UNCLASSIFIED` — preserving the day of month."

    Design: Corner/rbac/submitting_engineer_cannot_accept_their_own_inspection
    """
    validate_success(
        api.accept_inspection(submitted_visit["id"], None, base.engineer_b_headers)
    )
    dam = program.get_dam(base.dam_id)
    assert_instant(
        dam["next_inspection_due_at"],
        "2028-08-05T12:00:00Z",
        "next_inspection_due_at",
    )
    assert dam["inspection_overdue"] is False


# ---------------------------------------------------------------------------
# The reviewer may not be the dam's inspecting engineer
# ---------------------------------------------------------------------------
@pytest.fixture()
def inspected_dam_with_permit(program, base):
    """An ACCEPTED inspection by engineer A and a SUBMITTED repair permit."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    accepted = program.accepted_inspection(
        base.dam_id,
        base.engineer_a_id,
        accepter_headers=base.engineer_b_headers,
        condition_rating=SAFETY_CONDITIONALLY_SATISFACTORY,
    )
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_REPAIR,
        estimated_project_cost_cents=4_000_000,
    )
    return {"accepted": accepted, "permit": permit}


def test_the_inspecting_engineer_cannot_review_the_same_dams_permit(
    api, program, base, inspected_dam_with_permit
):
    """The engineer whose rating feeds the decision cannot take the decision.

    PRD 3.6: "The nominated engineer's `license_status` must be `ACTIVE`, and they must not be the engineer of record on the dam's latest accepted inspection — that collision is `ERR_SEGREGATION_OF_DUTIES`, because an engineer's own condition rating of the structure feeds the very decision they would be making."

    Design: Corner/rbac/permit_review_cannot_be_assigned_to_the_dams_inspecting_engineer
    """
    permit_id = inspected_dam_with_permit["permit"]["id"]
    validate_error(
        api.assign_permit_review(
            permit_id, f.assign_review_payload(base.engineer_a_id), program.admin
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        409,
    )

    permit = program.get_permit(permit_id)
    assert permit["status"] == PERMIT_SUBMITTED
    assert permit["review_engineer_id"] is None


def test_the_accepting_engineer_takes_the_review(
    api, program, base, inspected_dam_with_permit
):
    """The other certified engineer is assignable and the application moves on.

    PRD 3.6: "Program staff then assign a reviewer, moving the application `SUBMITTED → UNDER_ENGINEERING_REVIEW` and storing the nominated `review_engineer_id`."

    Design: Corner/rbac/permit_review_cannot_be_assigned_to_the_dams_inspecting_engineer
    """
    assigned = validate_success(
        api.assign_permit_review(
            inspected_dam_with_permit["permit"]["id"],
            f.assign_review_payload(base.engineer_b_id),
            program.admin,
        )
    )
    assert assigned["status"] == PERMIT_UNDER_ENGINEERING_REVIEW
    assert assigned["review_engineer_id"] == base.engineer_b_id

    visit = inspected_dam_with_permit["accepted"]
    assert visit["status"] == INSPECTION_ACCEPTED
    assert visit["engineer_id"] == base.engineer_a_id
    assert visit["accepted_by_user_id"] == base.engineer_b_id
