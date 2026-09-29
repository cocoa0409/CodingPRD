"""What a refused crossing destroys.

A denial is the most far-reaching event in the system. It starts on one permit and
finishes on the route's status five hops later, taking a stamped design package
down with it on the way. The tests here follow the whole chain and, just as
importantly, pin down what the cascade must leave alone.
"""

from test_helpers import USER_IDS, fixtures as fx, validate_error, validate_success
from test_helpers.factories import permit_review_payload

_RIDGE_RING = {
    "name": "Ridge Ring",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_RIDGE_AVE_1250 = {
    "sequence_index": 1,
    "street_name": "Ridge Ave",
    "municipality_code": "MUN-014",
    "length_feet": 1250,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-25",
    "existing_conduit_available": False,
}
_GRADE_A_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "A",
    "available_vertical_clearance_in": 48,
    "existing_attachment_count": 2,
}
_MUNICIPAL_WINDOW = {
    "authority_type": "MUNICIPAL_ROW",
    "authority_name": "City of Ridgefield DPW",
    "work_window_start_on": "2026-09-15",
    "work_window_end_on": "2026-09-25",
}


def _construction_ready_route_with_a_supplemental_permit_under_review(
    coordinator, reviewer, engineer, engineer_alt, surveyor
):
    """A stamped, construction-ready ring route with a second permit still open.

    The first permit is approved and the design is stamped, so the route has
    reached `CONSTRUCTION_READY`. A supplemental municipal permit is then filed on
    the same segment on a later logical day, leaving it awaiting a decision.
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer, **_RIDGE_RING)
    segment = fx.create_segment(route["id"], headers=engineer, **_RIDGE_AVE_1250)
    fx.accepted_walkout(
        segment["id"],
        [_GRADE_A_POLE],
        reviewer=engineer,
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear aerial span, no obstructions",
    )
    fx.select_method_on_route(route["id"], segment["id"], "AERIAL", headers=engineer)
    fx.request_bid_ready(segment["id"], headers=engineer)
    fx.lock_scope(route["id"], headers=engineer)

    first = fx.create_permit(segment["id"], headers=coordinator, **_MUNICIPAL_WINDOW)
    fx.submit_permit(first["id"], headers=coordinator)
    fx.review_permit(
        first["id"], "APPROVED", headers=reviewer, decision_note="aerial attachment approved"
    )

    design = fx.create_design(
        route["id"], headers=engineer, fiber_count_allocated=288, express_fiber_count=48
    )
    splice = fx.place_splice_point(
        design["id"],
        segment["id"],
        headers=engineer,
        station_feet=0,
        enclosure_type="HANDHOLE",
        fiber_count_dropped=24,
    )
    fx.submit_design(design["id"], headers=engineer)
    fx.stamp_design(design["id"], headers=engineer_alt)

    fx.set_clock("2026-08-12T00:00:00Z")
    second = fx.create_permit(segment["id"], headers=coordinator, **_MUNICIPAL_WINDOW)
    fx.submit_permit(second["id"], headers=coordinator)

    return {
        "route_id": route["id"],
        "segment_id": segment["id"],
        "first_permit_id": first["id"],
        "second_permit_id": second["id"],
        "design_id": design["id"],
        "splice_point_id": splice["id"],
    }


def test_denying_a_supplemental_permit_blocks_the_segment_and_drops_its_bid_cost(
    api,
    coordinator_headers,
    reviewer_headers,
    engineer_headers,
    engineer_alt_headers,
    surveyor_headers,
):
    """Hops 1 to 3: DENIED, then BLOCKED, then the engineering dimension released.

    PRD: "**Hop 3**, caused by hop 2, releases that segment's engineering
    dimension `DESIGN_LOCKED → METHOD_SELECTED` and sets its
    `bid_ready_cost_cents` back to null, then recomputes the route's
    `total_bid_ready_cost_cents`."

    Design: Difficulty/transitive_cascade/permit_denial_five_hop_cascade_voids_stamp_and_reopens_route
    """
    built = _construction_ready_route_with_a_supplemental_permit_under_review(
        coordinator_headers,
        reviewer_headers,
        engineer_headers,
        engineer_alt_headers,
        surveyor_headers,
    )
    assert fx.read_route(built["route_id"])["status"] == "CONSTRUCTION_READY"

    denied = validate_success(
        api.review_permit_application(
            built["second_permit_id"],
            permit_review_payload(
                "DENIED", decision_note="supplemental attachment denied, pole loading exceeded"
            ),
            headers=reviewer_headers,
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["decided_at"] == "2026-08-12T00:00:00Z"
    assert denied["decided_by_user_id"] == USER_IDS["authority_reviewer"]
    assert denied["deemed"] is False

    segment = fx.read_segment(built["segment_id"])
    assert segment["permit_status"] == "BLOCKED"
    assert segment["engineering_status"] == "METHOD_SELECTED"
    assert segment["bid_ready_cost_cents"] is None
    assert segment["construction_method"] == "AERIAL"
    assert segment["preliminary_cost_cents"] == 1971469

    route = fx.read_route(built["route_id"])
    assert route["total_bid_ready_cost_cents"] == 0
    assert route["total_preliminary_cost_cents"] == 1971469


def test_denial_voids_the_stamp_but_keeps_the_signature_and_the_splice_work(
    api,
    coordinator_headers,
    reviewer_headers,
    engineer_headers,
    engineer_alt_headers,
    surveyor_headers,
):
    """Hops 4 and 5: the package returns to DRAFT and the route reopens permitting.

    PRD: "`stamped_by_user_id` and `stamped_at` are deliberately **retained** on
    the row for audit rather than cleared — the record that a particular engineer
    stamped a particular design at a particular instant survives the voiding"

    Design: Difficulty/transitive_cascade/permit_denial_five_hop_cascade_voids_stamp_and_reopens_route
    """
    built = _construction_ready_route_with_a_supplemental_permit_under_review(
        coordinator_headers,
        reviewer_headers,
        engineer_headers,
        engineer_alt_headers,
        surveyor_headers,
    )
    stamped = fx.read_design(built["design_id"], headers=engineer_headers)
    assert stamped["status"] == "STAMPED"
    assert stamped["stamped_by_user_id"] == USER_IDS["route_engineer_second"]
    assert stamped["stamped_at"] == "2026-08-10T00:00:00Z"
    assert stamped["stamp_voided_at"] is None

    validate_success(
        api.review_permit_application(
            built["second_permit_id"],
            permit_review_payload(
                "DENIED", decision_note="supplemental attachment denied, pole loading exceeded"
            ),
            headers=reviewer_headers,
        )
    )

    design = fx.read_design(built["design_id"], headers=engineer_headers)
    assert design["status"] == "DRAFT"
    assert design["stamp_voided_at"] == "2026-08-12T00:00:00Z"
    assert design["stamped_by_user_id"] == USER_IDS["route_engineer_second"]
    assert design["stamped_at"] == "2026-08-10T00:00:00Z"

    splices = validate_success(
        api.list_design_splice_points(built["design_id"], headers=engineer_headers)
    )
    assert len(splices) == 1
    assert splices[0]["id"] == built["splice_point_id"]
    assert splices[0]["status"] == "PLACED"
    assert splices[0]["voided_at"] is None

    assert fx.read_route(built["route_id"])["status"] == "PERMITTING"
    assert fx.read_permit(built["first_permit_id"])["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# The lapsed review window, claimed by the coordinator
# ---------------------------------------------------------------------------

_RAIL_CROSSING_SPUR = {
    "name": "Rail Crossing Spur",
    "topology_objective": "SPUR",
    "target_in_service_date": "2027-06-01",
    "budget_authorized_cents": 250000000,
}
_INLAND_SPUR = {
    "name": "Inland Spur",
    "topology_objective": "SPUR",
    "target_in_service_date": "2027-06-01",
    "budget_authorized_cents": 250000000,
}
_RAIL_YARD_CUT_600 = {
    "sequence_index": 1,
    "street_name": "Rail Yard Cut",
    "municipality_code": "MUN-014",
    "length_feet": 600,
    "terrain_class": "RAIL_CROSSING",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
}
_DOCK_STREET_400 = {
    "sequence_index": 1,
    "street_name": "Dock Street",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
}


def _permit_awaiting_an_answer(route_spec, segment_spec, authority_type, authority_name):
    """A PERMITTING spur route with exactly one permit sitting at UNDER_REVIEW."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**route_spec)
    segment = fx.create_segment(route["id"], **segment_spec)
    fx.accepted_walkout(
        segment["id"],
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="leg walked, nothing in the way",
    )
    fx.lock_scope(route["id"])
    permit = fx.filed_permit(
        segment["id"],
        authority_type=authority_type,
        authority_name=authority_name,
        work_window_start_on="2026-09-15",
        work_window_end_on="2026-09-20",
    )
    return {"route_id": route["id"], "segment_id": segment["id"], "permit": permit}


def test_a_railroad_that_never_answers_has_refused(api, coordinator_headers):
    """Silence from the railroad is a denial, and the crossing is blocked.

    PRD: "For a `RAILROAD`, `STATE_HIGHWAY` or `WATERWAY` permit there is no such
    grace: silence is refusal, the permit moves `UNDER_REVIEW → DENIED`, and hops 2
    through 5 of the permit denial cascade run exactly as they would after a
    reviewer's denial."

    Design: Corner/state_machines/deemed_decision_denies_a_railroad_permit_once_the_review_window_lapses
    """
    built = _permit_awaiting_an_answer(
        _RAIL_CROSSING_SPUR, _RAIL_YARD_CUT_600, "RAILROAD", "Eastern Rail Holdings"
    )
    permit = built["permit"]
    assert permit["review_days"] == 90, "a spur route earns no expedite at any counter"
    assert permit["decision_due_at"] == "2026-11-08T00:00:00Z"

    fx.set_clock("2026-11-09T00:00:00Z")
    claimed = validate_success(
        api.claim_deemed_decision(permit["id"], headers=coordinator_headers)
    )
    assert claimed["status"] == "DENIED"
    assert claimed["deemed"] is True
    assert claimed["decided_at"] == "2026-11-09T00:00:00Z"
    assert claimed["decided_by_user_id"] is None, "no person decided anything"

    assert fx.read_segment(built["segment_id"])["permit_status"] == "BLOCKED"

    route = fx.read_route(built["route_id"])
    assert route["status"] == "PERMITTING"
    assert route["planned_complexity_index"] == 4000
    assert route["live_complexity_index"] == 8000, "a denied railroad carries double its weight"


def test_the_deadline_instant_itself_is_still_inside_the_window(api, coordinator_headers):
    """Parked on the due instant, the claim is premature by exactly one second.

    PRD: "This lapsed-window claim requires the permit to be at `UNDER_REVIEW` and
    requires the logical clock to stand **strictly after** `decision_due_at`; a claim
    made while the clock is at or before the deadline is refused with
    `ERR_REVIEW_WINDOW_OPEN`, so the deadline instant itself is still inside the
    window."

    Design: Corner/validations/deemed_decision_at_exactly_the_due_instant_returns_review_window_open
    """
    built = _permit_awaiting_an_answer(
        _INLAND_SPUR, _DOCK_STREET_400, "MUNICIPAL_ROW", "City of Ridgefield DPW"
    )
    permit = built["permit"]
    assert permit["review_days"] == 21, "a spur route is never expedited"
    assert permit["decision_due_at"] == "2026-08-31T00:00:00Z"

    fx.set_clock("2026-08-31T00:00:00Z")
    premature = api.claim_deemed_decision(permit["id"], headers=coordinator_headers)
    validate_error(premature, "ERR_REVIEW_WINDOW_OPEN", 409)

    unchanged = fx.read_permit(permit["id"])
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["deemed"] is False
    assert unchanged["decided_at"] is None
    assert unchanged["decided_by_user_id"] is None
    assert fx.read_segment(built["segment_id"])["permit_status"] == "PENDING"
    assert fx.read_route(built["route_id"])["status"] == "PERMITTING"


def test_one_second_later_the_city_has_granted_the_permit_by_its_own_silence(
    api, coordinator_headers
):
    """The municipal branch of the lapse is a grant, and it clears the segment.

    PRD: "For a `MUNICIPAL_ROW` permit the ordinance grants the permit when the city
    lets its own review window lapse: the permit moves `UNDER_REVIEW → APPROVED` with
    exactly the same downstream effects as an authority's approval — the same
    two-part segment-clearing test, the same possible route advance to
    `CONSTRUCTION_READY`."

    Design: Corner/validations/deemed_decision_one_second_after_the_due_instant_approves_a_municipal_permit
    """
    built = _permit_awaiting_an_answer(
        _INLAND_SPUR, _DOCK_STREET_400, "MUNICIPAL_ROW", "City of Ridgefield DPW"
    )
    permit = built["permit"]
    assert permit["decision_due_at"] == "2026-08-31T00:00:00Z"

    fx.set_clock("2026-08-31T00:00:01Z")
    claimed = validate_success(
        api.claim_deemed_decision(permit["id"], headers=coordinator_headers)
    )
    assert claimed["status"] == "APPROVED"
    assert claimed["deemed"] is True
    assert claimed["decided_at"] == "2026-08-31T00:00:01Z"
    assert claimed["decided_by_user_id"] is None

    assert fx.read_segment(built["segment_id"])["permit_status"] == "CLEARED"

    route = fx.read_route(built["route_id"])
    assert route["live_complexity_index"] == 250
    assert route["status"] == "PERMITTING", "no design package on this route is stamped yet"
