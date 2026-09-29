"""Filing right-of-way permits and computing the review clock.

Filing is where three ideas collide: the route must already have frozen its
scope, the requested occupancy window must not touch a paving moratorium, and the
resulting review deadline is a non-linear function of the authority class, the
route's topology objective and the number of revision rounds already spent. A
segment's permit dimension moves on its own while its engineering dimension
stands still.
"""

from test_helpers import fixtures as fx, validate_error, validate_success
from test_helpers.factories import create_permit_application_payload

_RIDGE_RING = {
    "name": "Ridge Ring",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_RIDGE_AVE_250 = {
    "sequence_index": 1,
    "street_name": "Ridge Ave",
    "municipality_code": "MUN-014",
    "length_feet": 250,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
    "existing_conduit_available": False,
}
_GRADE_A_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "A",
    "available_vertical_clearance_in": 48,
    "existing_attachment_count": 2,
}

_MILL_STREET_SPUR = {
    "name": "Mill Street Spur",
    "topology_objective": "SPUR",
    "target_in_service_date": "2027-05-01",
    "budget_authorized_cents": 90000000,
}
_MILL_STREET_POLE = {
    "pole_tag": "P-501",
    "pole_owner": "TELCO",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}


def _mill_street_segment(**overrides):
    spec = {
        "sequence_index": 1,
        "street_name": "Mill Street",
        "municipality_code": "MUN-014",
        "length_feet": 250,
        "terrain_class": "URBAN_PAVED",
        "planned_work_start_on": "2026-10-05",
        "planned_work_end_on": "2026-10-12",
        "existing_conduit_available": False,
    }
    spec.update(overrides)
    return spec


def _scope_locked_mill_street_spur(**segment_overrides):
    """A SCOPE_LOCKED spur route with one walked urban-paved segment on Mill Street."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_MILL_STREET_SPUR)
    segment = fx.create_segment(route["id"], **_mill_street_segment(**segment_overrides))
    fx.accepted_walkout(
        segment["id"],
        [_MILL_STREET_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear span along Mill Street",
    )
    fx.lock_scope(route["id"])
    return {"route_id": route["id"], "segment_id": segment["id"]}


# ---------------------------------------------------------------------------
# A segment's three dimensions advance on separate tracks
# ---------------------------------------------------------------------------


def _design_locked_ridge_ring_with_a_draft_permit():
    """A DESIGN_LOCKED aerial segment on a locked ring route, plus a DRAFT permit."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_RIDGE_RING)
    segment = fx.create_segment(route["id"], **_RIDGE_AVE_250)
    fx.accepted_walkout(
        segment["id"],
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear aerial span, no obstructions",
    )
    fx.select_method_on_route(route["id"], segment["id"], "AERIAL")
    fx.request_bid_ready(segment["id"])
    fx.lock_scope(route["id"])
    permit = fx.create_permit(
        segment["id"],
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-09-15",
        work_window_end_on="2026-09-20",
    )
    return {"route_id": route["id"], "segment_id": segment["id"], "permit_id": permit["id"]}


def test_first_municipal_filing_on_a_ring_route_gets_sixteen_review_days(
    api, coordinator_headers
):
    """21 raw days, expedited to 15.75, rounded up to 16, under the 35-day ceiling.

    PRD: "For a ring-closure route's first municipal filing, the raw count is 21
    days with no penalty, the expedited figure is 21 multiplied by 7,500 basis
    points which is 15.75 rounded up to 16, and 16 is below the municipal ceiling
    of 35, so `review_days` is 16."

    Design: Difficulty/non_linear_state_machine/segment_parallel_dimensions_advance_independently
    """
    built = _design_locked_ridge_ring_with_a_draft_permit()

    filed = validate_success(
        api.submit_permit_application(built["permit_id"], headers=coordinator_headers)
    )
    assert filed["status"] == "UNDER_REVIEW"
    assert filed["revision_round"] == 0
    assert filed["review_days"] == 16
    assert filed["submitted_at"] == "2026-08-10T00:00:00Z"
    assert filed["decision_due_at"] == "2026-08-26T00:00:00Z"
    assert filed["deemed"] is False


def test_filing_moves_the_permit_dimension_without_disturbing_engineering(
    api, coordinator_headers
):
    """The segment reaches PENDING while staying DESIGN_LOCKED and aerial.

    PRD: "A successful filing stamps `submitted_at` from the logical clock,
    computes the review schedule described below, drives the segment's permit
    dimension to `PENDING` from whichever of `NOT_REQUIRED`, `CLEARED` or
    `BLOCKED` it held, advances the route `SCOPE_LOCKED → PERMITTING` on the
    first filing anywhere on that route"

    Design: Difficulty/non_linear_state_machine/segment_parallel_dimensions_advance_independently
    """
    built = _design_locked_ridge_ring_with_a_draft_permit()
    before = fx.read_segment(built["segment_id"])
    assert before["permit_status"] == "NOT_REQUIRED"
    assert before["engineering_status"] == "DESIGN_LOCKED"

    validate_success(api.submit_permit_application(built["permit_id"], headers=coordinator_headers))

    segment = fx.read_segment(built["segment_id"])
    assert segment["permit_status"] == "PENDING"
    assert segment["engineering_status"] == "DESIGN_LOCKED"
    assert segment["construction_method"] == "AERIAL"
    assert segment["preliminary_cost_cents"] == 394294
    assert segment["bid_ready_cost_cents"] == 394295

    route = fx.read_route(built["route_id"])
    assert route["status"] == "PERMITTING"
    assert route["planned_complexity_index"] == 1000


# ---------------------------------------------------------------------------
# The revision cycle recharges the review clock and hits the authority ceiling
# ---------------------------------------------------------------------------


def _permit_sent_back_for_revision(coordinator, reviewer):
    """A municipal permit on a spur route that has been sent back once."""

    built = _scope_locked_mill_street_spur()
    permit = fx.create_permit(
        built["segment_id"],
        headers=coordinator,
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-10-05",
        work_window_end_on="2026-10-12",
    )
    built["first_filing"] = fx.submit_permit(permit["id"], headers=coordinator)
    built["permit_id"] = permit["id"]
    built["revision"] = fx.review_permit(
        permit["id"],
        "REVISION_REQUESTED",
        headers=reviewer,
        decision_note="resubmit with traffic control plan",
    )
    return built


def test_spur_route_first_filing_is_never_expedited_at_the_municipal_counter(
    api, coordinator_headers, reviewer_headers
):
    """A SPUR route pays the full 21 municipal days even though the desk is the same.

    PRD: "Railroad and waterway reviews are never expedited, and a spur or
    express-backbone route is never expedited even at a municipal counter."

    Design: Difficulty/non_linear_state_machine/permit_revision_cycle_recharges_review_days_to_authority_cap
    """
    built = _permit_sent_back_for_revision(coordinator_headers, reviewer_headers)

    assert built["first_filing"]["review_days"] == 21
    assert built["first_filing"]["submitted_at"] == "2026-08-10T00:00:00Z"
    assert built["first_filing"]["decision_due_at"] == "2026-08-31T00:00:00Z"

    assert built["revision"]["status"] == "REVISION_REQUESTED"
    assert built["revision"]["revision_round"] == 1
    assert built["revision"]["decision_note"] == "resubmit with traffic control plan"
    assert fx.read_segment(built["segment_id"])["permit_status"] == "PENDING"


def test_resubmission_penalty_lands_the_review_exactly_on_the_municipal_ceiling(
    api, coordinator_headers, reviewer_headers
):
    """21 plus a 14-day penalty is 35, which is precisely the municipal ceiling.

    PRD: "A resubmission penalty of 14 days is charged for each completed revision
    round, so the penalty is 14 multiplied by the permit's `revision_round`."

    Design: Difficulty/non_linear_state_machine/permit_revision_cycle_recharges_review_days_to_authority_cap
    """
    built = _permit_sent_back_for_revision(coordinator_headers, reviewer_headers)
    fx.set_clock("2026-08-20T00:00:00Z")

    refiled = validate_success(
        api.submit_permit_application(built["permit_id"], headers=coordinator_headers)
    )
    assert refiled["status"] == "UNDER_REVIEW"
    assert refiled["revision_round"] == 1
    assert refiled["review_days"] == 35
    assert refiled["submitted_at"] == "2026-08-20T00:00:00Z"
    assert refiled["decision_due_at"] == "2026-09-24T00:00:00Z"

    assert fx.read_segment(built["segment_id"])["permit_status"] == "PENDING"
    assert fx.read_route(built["route_id"])["status"] == "PERMITTING"


# ---------------------------------------------------------------------------
# Drafting a permit is gated on the route having frozen its segment set
# ---------------------------------------------------------------------------


def _unlocked_spur_with_a_walked_segment():
    """A PLANNING route whose only segment has already been walked and accepted."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(
        name="Unlocked Spur",
        topology_objective="SPUR",
        target_in_service_date="2027-08-01",
        budget_authorized_cents=80000000,
    )
    segment = fx.create_segment(
        route["id"],
        sequence_index=1,
        street_name="Foundry Road",
        municipality_code="MUN-022",
        length_feet=250,
        terrain_class="URBAN_PAVED",
        planned_work_start_on="2026-10-05",
        planned_work_end_on="2026-10-12",
        existing_conduit_available=False,
    )
    fx.accepted_walkout(
        segment["id"],
        [
            {
                "pole_tag": "P-701",
                "pole_owner": "TELCO",
                "condition_grade": "A",
                "available_vertical_clearance_in": 47,
                "existing_attachment_count": 1,
            }
        ],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear span along Foundry Road",
    )
    return {"route_id": route["id"], "segment_id": segment["id"]}


_FOUNDRY_PERMIT = {
    "authority_type": "MUNICIPAL_ROW",
    "authority_name": "City of Foundry DPW",
    "work_window_start_on": "2026-10-05",
    "work_window_end_on": "2026-10-12",
}


def test_permit_cannot_be_drafted_while_the_route_is_still_planning(
    api, coordinator_headers, engineer_headers
):
    """A walked segment is not enough: the route itself must have locked its scope.

    PRD: "Drafting requires the owning route to have reached `SCOPE_LOCKED`,
    `PERMITTING` or `CONSTRUCTION_READY`; a permit drafted against a route still
    in `PLANNING` is refused with `ERR_INVALID_ROUTE_STATE`, because the segment
    set it would be permitting is not yet frozen."

    Design: Difficulty/cross_entity_state_dependency/permit_application_create_requires_route_scope_locked
    """
    built = _unlocked_spur_with_a_walked_segment()
    segment = fx.read_segment(built["segment_id"])
    assert segment["engineering_status"] == "WALKED"
    assert segment["permit_status"] == "NOT_REQUIRED"

    response = api.create_permit_application(
        create_permit_application_payload(built["segment_id"], **_FOUNDRY_PERMIT),
        headers=coordinator_headers,
    )
    validate_error(response, "ERR_INVALID_ROUTE_STATE", 409)

    rows = validate_success(
        api.list_segment_permit_applications(built["segment_id"], headers=coordinator_headers)
    )
    assert rows == []
    route = fx.read_route(built["route_id"])
    assert route["status"] == "PLANNING"
    assert route["scope_locked_at"] is None


def test_the_same_permit_draft_is_accepted_once_the_scope_is_locked(
    api, coordinator_headers, engineer_headers
):
    """Locking the scope is the only thing that changes, and the draft then lands.

    PRD: "On success the route moves `PLANNING → SCOPE_LOCKED`, `scope_locked_at`
    is stamped from the logical clock, the planned permitting-complexity index is
    computed and written to `planned_complexity_index`, `live_complexity_index` is
    seeded with that identical value, and the route's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/permit_application_create_requires_route_scope_locked
    """
    built = _unlocked_spur_with_a_walked_segment()
    refusal = api.create_permit_application(
        create_permit_application_payload(built["segment_id"], **_FOUNDRY_PERMIT),
        headers=coordinator_headers,
    )
    assert refusal.status_code == 409, f"expected a 409 refusal, got {refusal.status_code}"

    locked = fx.lock_scope(built["route_id"], headers=engineer_headers)
    assert locked["status"] == "SCOPE_LOCKED"
    assert locked["scope_locked_at"] == "2026-08-10T00:00:00Z"

    created = validate_success(
        api.create_permit_application(
            create_permit_application_payload(built["segment_id"], **_FOUNDRY_PERMIT),
            headers=coordinator_headers,
        ),
        201,
    )
    assert created["status"] == "DRAFT"
    assert created["authority_name"] == "City of Foundry DPW"
    assert created["review_days"] is None
    assert created["decision_due_at"] is None


# ---------------------------------------------------------------------------
# Filing checks its own status before it consults the moratorium registry
# ---------------------------------------------------------------------------


def _approved_permit_then_a_blanket_moratorium(coordinator, reviewer, admin):
    """An APPROVED municipal permit, then a moratorium registered over its window."""

    built = _scope_locked_mill_street_spur()
    permit = fx.create_permit(
        built["segment_id"],
        headers=coordinator,
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-10-05",
        work_window_end_on="2026-10-12",
    )
    fx.submit_permit(permit["id"], headers=coordinator)
    built["approved"] = fx.review_permit(
        permit["id"], "APPROVED", headers=reviewer, decision_note="approved as filed"
    )
    built["permit_id"] = permit["id"]
    fx.create_moratorium_window(
        municipality_code="MUN-014",
        street_name="Mill Street",
        resurfaced_on="2026-06-01",
        starts_on="2026-06-01",
        ends_on="2026-12-01",
        moratorium_class="NO_OPEN_CUT",
        ordinance_reference="ORD-2026-118",
    )
    return built


def test_refiling_a_decided_permit_reports_the_status_gate_not_the_moratorium(
    api, coordinator_headers, reviewer_headers, admin_headers
):
    """An APPROVED permit whose window is now under moratorium fails on its status.

    PRD: "Filing the permit is a separate act, permitted from `DRAFT` and from
    `REVISION_REQUESTED` and requiring the route to be in `SCOPE_LOCKED`,
    `PERMITTING` or `CONSTRUCTION_READY`. Filing from any other permit status is
    `ERR_INVALID_PERMIT_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/permit_state_gate_precedes_moratorium_conflict_gate
    """
    built = _approved_permit_then_a_blanket_moratorium(
        coordinator_headers, reviewer_headers, admin_headers
    )
    assert built["approved"]["status"] == "APPROVED"

    response = api.submit_permit_application(built["permit_id"], headers=coordinator_headers)
    validate_error(response, "ERR_INVALID_PERMIT_STATE", 409)


def test_the_rejected_refiling_leaves_the_approved_schedule_untouched(
    api, coordinator_headers, reviewer_headers, admin_headers
):
    """No second submission means no second review clock and no lost clearance.

    PRD: "**Approval** moves the permit `UNDER_REVIEW → APPROVED`, which is
    terminal, and sets `deemed` to false."

    Design: Difficulty/priority_pair_validation_conflict/permit_state_gate_precedes_moratorium_conflict_gate
    """
    built = _approved_permit_then_a_blanket_moratorium(
        coordinator_headers, reviewer_headers, admin_headers
    )
    refusal = api.submit_permit_application(built["permit_id"], headers=coordinator_headers)
    assert refusal.status_code == 409, f"expected a 409 refusal, got {refusal.status_code}"

    permit = fx.read_permit(built["permit_id"])
    assert permit["status"] == "APPROVED"
    assert permit["revision_round"] == 0
    assert permit["review_days"] == 21
    assert permit["decision_due_at"] == "2026-08-31T00:00:00Z"
    assert permit["submitted_at"] == "2026-08-10T00:00:00Z"

    assert fx.read_segment(built["segment_id"])["permit_status"] == "CLEARED"
    assert fx.read_route(built["route_id"])["status"] == "PERMITTING"


# ---------------------------------------------------------------------------
# Closed intervals: a shared endpoint is an overlap
# ---------------------------------------------------------------------------


def _spur_with_a_moratorium_opening_on_the_twentieth(admin):
    """A locked spur route on Mill Street with a moratorium running 09-20 to 10-20."""

    built = _scope_locked_mill_street_spur(
        planned_work_start_on="2026-09-10", planned_work_end_on="2026-09-20"
    )
    fx.create_moratorium_window(
        municipality_code="MUN-014",
        street_name="Mill Street",
        resurfaced_on="2026-09-19",
        starts_on="2026-09-20",
        ends_on="2026-10-20",
        moratorium_class="FULL_RESTORATION",
        ordinance_reference="ORD-2026-204",
    )
    return built


def test_a_work_window_ending_on_the_moratorium_start_day_collides(
    api, coordinator_headers, admin_headers
):
    """A single shared calendar day between two closed intervals is an intersection.

    PRD: "Both intervals are closed, so a work window that merely touches a
    moratorium at a single shared endpoint does collide."

    Design: Difficulty/resource_temporal_overlap/permit_work_window_touching_moratorium_endpoint_conflicts
    """
    built = _spur_with_a_moratorium_opening_on_the_twentieth(admin_headers)
    permit = fx.create_permit(
        built["segment_id"],
        headers=coordinator_headers,
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-09-10",
        work_window_end_on="2026-09-20",
    )

    response = api.submit_permit_application(permit["id"], headers=coordinator_headers)
    validate_error(response, "ERR_MORATORIUM_WINDOW_CONFLICT", 409)

    unfiled = fx.read_permit(permit["id"])
    assert unfiled["status"] == "DRAFT"
    assert unfiled["review_days"] is None
    assert unfiled["decision_due_at"] is None
    assert unfiled["submitted_at"] is None

    assert fx.read_segment(built["segment_id"])["permit_status"] == "NOT_REQUIRED"
    route = fx.read_route(built["route_id"])
    assert route["status"] == "SCOPE_LOCKED"
    assert route["live_complexity_index"] == 1000


def test_pulling_the_window_back_one_day_clears_the_moratorium(
    api, coordinator_headers, admin_headers
):
    """Ending on the 19th instead of the 20th removes the only shared day.

    PRD: "Before anything is written, the system checks the requested occupancy
    window against the paving moratoria: if any registered moratorium window
    matching the segment's `municipality_code` and `street_name` intersects the
    closed interval running from `work_window_start_on` to `work_window_end_on`,
    the filing is refused with `ERR_MORATORIUM_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/permit_work_window_touching_moratorium_endpoint_conflicts
    """
    built = _spur_with_a_moratorium_opening_on_the_twentieth(admin_headers)
    earlier = fx.create_permit(
        built["segment_id"],
        headers=coordinator_headers,
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-09-10",
        work_window_end_on="2026-09-19",
    )

    filed = validate_success(
        api.submit_permit_application(earlier["id"], headers=coordinator_headers)
    )
    assert filed["status"] == "UNDER_REVIEW"
    assert filed["work_window_end_on"] == "2026-09-19"
    assert filed["review_days"] == 21
    assert fx.read_segment(built["segment_id"])["permit_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Expedite eligibility, decision finality, and where "now" comes from
# ---------------------------------------------------------------------------

_HARBOR_RING = {
    "name": "Harbor Ring",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_DOCK_STREET = {
    "sequence_index": 1,
    "street_name": "Dock Street",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
}
_RAIL_YARD_CUT = {
    "sequence_index": 2,
    "street_name": "Rail Yard Cut",
    "municipality_code": "MUN-014",
    "length_feet": 600,
    "terrain_class": "RAIL_CROSSING",
    "planned_work_start_on": "2026-09-21",
    "planned_work_end_on": "2026-09-25",
}
_INLAND_SPUR = {
    "name": "Inland Spur",
    "topology_objective": "SPUR",
    "target_in_service_date": "2027-06-01",
    "budget_authorized_cents": 250000000,
}


def _walk(segment_id, note):
    fx.accepted_walkout(
        segment_id,
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note=note,
    )


def test_the_railroad_counter_is_never_expedited_even_on_a_ring_route(
    api, coordinator_headers
):
    """One ring route, two authorities, and only the municipal filing is shortened.

    PRD: "An **expedited review** is available, and it is available only when both
    of two conditions hold: the owning route's `topology_objective` is
    `RING_CLOSURE`, and the permit's `authority_type` is either `MUNICIPAL_ROW` or
    `STATE_HIGHWAY`."

    Design: Corner/calculations/permit_expedite_applies_only_to_ring_closure_municipal_and_state_highway
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_HARBOR_RING)
    municipal_leg = fx.create_segment(route["id"], **_DOCK_STREET)
    rail_leg = fx.create_segment(route["id"], **_RAIL_YARD_CUT)
    _walk(municipal_leg["id"], "dock street clear")
    _walk(rail_leg["id"], "rail crossing staked")
    fx.lock_scope(route["id"])

    municipal_permit = fx.create_permit(
        municipal_leg["id"],
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-09-15",
        work_window_end_on="2026-09-20",
    )
    rail_permit = fx.create_permit(
        rail_leg["id"],
        authority_type="RAILROAD",
        authority_name="Eastern Rail Holdings",
        work_window_start_on="2026-09-21",
        work_window_end_on="2026-09-25",
    )

    filed_municipal = validate_success(
        api.submit_permit_application(municipal_permit["id"], headers=coordinator_headers)
    )
    assert filed_municipal["submitted_at"] == "2026-08-10T00:00:00Z"
    assert filed_municipal["review_days"] == 16
    assert filed_municipal["decision_due_at"] == "2026-08-26T00:00:00Z"
    assert filed_municipal["review_days"] <= 35, "the municipal statutory ceiling"

    assert fx.read_route(route["id"])["status"] == "PERMITTING"

    filed_rail = validate_success(
        api.submit_permit_application(rail_permit["id"], headers=coordinator_headers)
    )
    assert filed_rail["submitted_at"] == "2026-08-10T00:00:00Z"
    assert filed_rail["review_days"] == 90, "railroad reviews pass through unexpedited"
    assert filed_rail["decision_due_at"] == "2026-11-08T00:00:00Z"
    assert filed_rail["review_days"] <= 120, "the railroad statutory ceiling"


def test_an_approved_permit_cannot_be_decided_a_second_time(
    api, reviewer_headers, reviewer_alt_headers
):
    """A second reviewer's denial arrives too late, and nothing about the first moves.

    PRD: "**Approval** moves the permit `UNDER_REVIEW → APPROVED`, which is
    terminal, and sets `deemed` to false."

    Design: Corner/state_machines/permit_review_applied_twice_returns_invalid_permit_state
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_INLAND_SPUR)
    segment = fx.create_segment(route["id"], **_DOCK_STREET)
    _walk(segment["id"], "dock street clear")
    fx.lock_scope(route["id"])
    permit = fx.filed_permit(
        segment["id"],
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-09-15",
        work_window_end_on="2026-09-20",
    )
    first = fx.review_permit(
        permit["id"], "APPROVED", headers=reviewer_headers, decision_note="approved as filed"
    )
    assert first["status"] == "APPROVED"
    assert first["deemed"] is False

    second_bite = api.review_permit_application(
        permit["id"],
        {"decision": "DENIED", "decision_note": "second bite"},
        headers=reviewer_alt_headers,
    )
    validate_error(second_bite, "ERR_INVALID_PERMIT_STATE", 409)

    unchanged = fx.read_permit(permit["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["decided_by_user_id"] == first["decided_by_user_id"]
    assert unchanged["decided_at"] == first["decided_at"]
    assert fx.read_segment(segment["id"])["permit_status"] == "CLEARED"
    assert fx.read_route(route["id"])["live_complexity_index"] == 250


def test_deadlines_are_measured_from_the_logical_clock_and_not_from_wall_time(
    api, admin_headers, coordinator_headers
):
    """The default now stamps the lock, and a later now stamps the filing.

    PRD: "A `NetworkRecordsAdmin` moves the clock forward or backward by supplying a
    `to_iso8601` instant to the clock-setting capability, which answers with the
    newly effective `current_utc`. Setting the clock mutates no entity and evaluates
    no automatic transition: nothing becomes overdue merely because the clock passed
    a deadline."

    Design: Corner/endpoints/clock_set_endpoint_moves_the_logical_now_used_by_later_writes
    """
    route = fx.create_route(**_INLAND_SPUR)
    segment = fx.create_segment(route["id"], **_DOCK_STREET)
    _walk(segment["id"], "dock street clear")
    locked = fx.lock_scope(route["id"])
    assert locked["scope_locked_at"] == "2026-08-01T00:00:00Z", (
        "the pre-set logical clock, read before any clock call was made"
    )

    permit = fx.create_permit(
        segment["id"],
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-10-05",
        work_window_end_on="2026-10-10",
    )

    moved = validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, headers=admin_headers)
    )
    assert moved["current_utc"] == "2026-09-01T00:00:00Z"
    assert "id" not in moved, "setting the clock mutates no entity"

    filed = validate_success(
        api.submit_permit_application(permit["id"], headers=coordinator_headers)
    )
    assert filed["submitted_at"] == "2026-09-01T00:00:00Z"
    assert filed["review_days"] == 21, "a spur route is never expedited"
    assert filed["decision_due_at"] == "2026-09-22T00:00:00Z"

    after = fx.read_route(route["id"])
    assert after["scope_locked_at"] == "2026-08-01T00:00:00Z"
