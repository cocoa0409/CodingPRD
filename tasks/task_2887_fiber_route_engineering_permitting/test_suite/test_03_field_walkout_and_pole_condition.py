"""Field walkouts, pole condition rollups and the re-walk rejection cascade.

A walkout is the only way field truth reaches a segment, and rejecting one is the
system's way of admitting that everything derived from the earlier walk was built
on sand. The cascade that follows a rejection is five hops deep and reaches all
the way back to the route's status.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_append_only_audit_fields,
    fixtures as fx,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_pole_observation_payload,
    create_route_payload,
    create_segment_payload,
    create_walkout_payload,
    walkout_review_payload,
)

_SEGMENT = {
    "sequence_index": 1,
    "street_name": "Ridge Ave",
    "municipality_code": "MUN-014",
    "length_feet": 1250,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-25",
    "existing_conduit_available": False,
}


def _design_locked_route_awaiting_a_rewalk_decision(api, engineer, surveyor):
    """A SCOPE_LOCKED route whose only segment is DESIGN_LOCKED, plus a second
    SUBMITTED walkout on that same segment carrying a grade-D pole.
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = validate_success(
        api.create_route(
            create_route_payload(
                name="Ridge Ring",
                topology_objective="RING_CLOSURE",
                target_in_service_date="2027-03-01",
                budget_authorized_cents=250000000,
            ),
            headers=engineer,
        ),
        201,
    )
    segment = validate_success(
        api.create_segment(create_segment_payload(route["id"], **_SEGMENT), headers=engineer), 201
    )

    first = validate_success(
        api.create_walkout(
            create_walkout_payload(
                segment["id"],
                walked_on="2026-08-11",
                obstruction_count=0,
                conduit_available_confirmed=False,
                surveyor_note="first pass",
            ),
            headers=surveyor,
        ),
        201,
    )
    validate_success(
        api.create_pole_observation(
            create_pole_observation_payload(
                first["id"],
                pole_tag="P-001",
                pole_owner="TELCO",
                condition_grade="A",
                available_vertical_clearance_in=48,
                existing_attachment_count=2,
            ),
            headers=surveyor,
        ),
        201,
    )
    validate_success(api.submit_walkout(first["id"], headers=surveyor))
    validate_success(
        api.review_walkout(first["id"], walkout_review_payload("ACCEPTED"), headers=engineer)
    )

    version = validate_success(api.get_route(route["id"], headers=engineer))["version"]
    validate_success(
        api.select_construction_method(
            segment["id"],
            {"method": "AERIAL", "expected_route_version": version},
            headers=engineer,
        )
    )
    validate_success(api.request_bid_ready_estimate(segment["id"], headers=engineer))
    validate_success(api.lock_route_scope(route["id"], headers=engineer))

    second = validate_success(
        api.create_walkout(
            create_walkout_payload(
                segment["id"],
                walked_on="2026-08-12",
                obstruction_count=3,
                conduit_available_confirmed=False,
                surveyor_note="re-walk after utility strike report",
            ),
            headers=surveyor,
        ),
        201,
    )
    validate_success(
        api.create_pole_observation(
            create_pole_observation_payload(
                second["id"],
                pole_tag="P-002",
                pole_owner="ELECTRIC_UTILITY",
                condition_grade="D",
                available_vertical_clearance_in=32,
                existing_attachment_count=4,
            ),
            headers=surveyor,
        ),
        201,
    )
    validate_success(api.submit_walkout(second["id"], headers=surveyor))

    return {
        "route_id": route["id"],
        "segment_id": segment["id"],
        "first_walkout_id": first["id"],
        "second_walkout_id": second["id"],
    }


def test_rewalk_rejection_erases_every_engineering_derivation_on_the_segment(
    api, engineer_headers, surveyor_headers
):
    """Hops 1 to 3: the walkout is rejected and the segment loses method and costs.

    PRD: "**Hop 3**, caused by hop 2, erases every engineering derivation on that
    segment: `construction_method` becomes null, `moratorium_class` returns to
    `NONE`, `restoration_cost_cents` returns to 0, and `preliminary_cost_cents`
    and `bid_ready_cost_cents` both become null."

    Design: Difficulty/transitive_cascade/rewalk_rejection_five_hop_cascade_resets_route_to_planning
    """
    built = _design_locked_route_awaiting_a_rewalk_decision(
        api, engineer_headers, surveyor_headers
    )

    rejected = validate_success(
        api.review_walkout(
            built["second_walkout_id"],
            walkout_review_payload(
                "REJECTED",
                rejection_reason="obstruction sketch missing stationing, re-walk required",
            ),
            headers=engineer_headers,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["review_round"] == 1
    assert (
        rejected["rejection_reason"]
        == "obstruction sketch missing stationing, re-walk required"
    )

    segment = validate_success(api.get_segment(built["segment_id"], headers=engineer_headers))
    assert segment["engineering_status"] == "DRAFT"
    assert segment["construction_method"] is None
    assert segment["moratorium_class"] == "NONE"
    assert segment["restoration_cost_cents"] == 0
    assert segment["preliminary_cost_cents"] is None
    assert segment["bid_ready_cost_cents"] is None


def test_rewalk_rejection_returns_the_locked_route_all_the_way_to_planning(
    api, engineer_headers, surveyor_headers
):
    """Hops 4 and 5: the route's rollups zero out and its lock is undone.

    PRD: "**Hop 5**, caused by hop 4, drives the route's status to `PLANNING`,
    sets `scope_locked_at` back to null, and sets `planned_complexity_index` back
    to null."

    Design: Difficulty/transitive_cascade/rewalk_rejection_five_hop_cascade_resets_route_to_planning
    """
    built = _design_locked_route_awaiting_a_rewalk_decision(
        api, engineer_headers, surveyor_headers
    )

    before = validate_success(api.get_route(built["route_id"], headers=engineer_headers))
    assert before["status"] == "SCOPE_LOCKED"
    assert before["scope_locked_at"] == "2026-08-10T00:00:00Z"
    assert before["planned_complexity_index"] == 1000
    assert before["total_preliminary_cost_cents"] == 1971469
    assert before["total_bid_ready_cost_cents"] == 1971475

    validate_success(
        api.review_walkout(
            built["second_walkout_id"],
            walkout_review_payload(
                "REJECTED",
                rejection_reason="obstruction sketch missing stationing, re-walk required",
            ),
            headers=engineer_headers,
        )
    )

    route = validate_success(api.get_route(built["route_id"], headers=engineer_headers))
    assert route["total_preliminary_cost_cents"] == 0
    assert route["total_bid_ready_cost_cents"] == 0
    assert route["status"] == "PLANNING"
    assert route["scope_locked_at"] is None
    assert route["planned_complexity_index"] is None

    segment = validate_success(api.get_segment(built["segment_id"], headers=engineer_headers))
    assert segment["permit_status"] == "NOT_REQUIRED"

    first = validate_success(
        api.get_walkout(built["first_walkout_id"], headers=engineer_headers)
    )
    assert first["status"] == "ACCEPTED"

    second = validate_success(
        api.get_walkout(built["second_walkout_id"], headers=engineer_headers)
    )
    assert second["worst_pole_condition_grade"] == "D"
    assert second["make_ready_flagged_pole_count"] == 1


# ---------------------------------------------------------------------------
# Opening a walkout and appending field observations
# ---------------------------------------------------------------------------

_HARBOR_LOOP = {
    "name": "Harbor Loop",
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


def _planning_route_with_one_dock_street_segment(engineer):
    """A PLANNING route carrying a single 400-foot urban paved leg."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer, **_HARBOR_LOOP)
    segment = fx.create_segment(route["id"], headers=engineer, **_DOCK_STREET)
    return {"route_id": route["id"], "segment_id": segment["id"], "segment": segment}


def test_a_walkout_opened_with_only_its_required_inputs_takes_the_declared_defaults(
    api, engineer_headers, surveyor_headers
):
    """Obstructions default to 0, the conduit flag to false and the note to null.

    PRD: "Three inputs are optional: `obstruction_count`, a count of at least zero
    that defaults to 0 and records documented obstructions found along the segment;
    `conduit_available_confirmed`, a boolean defaulting to false recording whether
    the surveyor actually confirmed usable spare conduit; and `surveyor_note`, free
    text defaulting to null."

    Design: Corner/entities/walkout_create_omitting_optional_inputs_applies_declared_defaults
    """
    built = _planning_route_with_one_dock_street_segment(engineer_headers)

    walkout = validate_success(
        api.create_walkout(
            create_walkout_payload(built["segment_id"], walked_on="2026-08-11"),
            headers=surveyor_headers,
        ),
        201,
    )
    assert walkout["obstruction_count"] == 0
    assert walkout["conduit_available_confirmed"] is False
    assert walkout["surveyor_note"] is None
    assert walkout["status"] == "OPEN"
    assert walkout["review_round"] == 0
    assert walkout["reviewed_by_user_id"] is None
    assert walkout["rejection_reason"] is None
    assert walkout["worst_pole_condition_grade"] == "NONE"
    assert walkout["make_ready_flagged_pole_count"] == 0

    assert built["segment"]["existing_conduit_available"] is False, (
        "the segment was created without the flag, so it takes its own declared default"
    )


def test_a_pole_observation_is_an_append_only_measurement_with_no_version(
    api, engineer_headers, surveyor_headers
):
    """A grade-D pole flags make-ready, and the row carries no version or updated_at.

    PRD: "Two resource types are append-only observations and are deliberately
    **not** versioned: a `PoleObservation` and a `MakeReadyItem` each carry only
    `id` and `created_at`."

    Design: Corner/entities/pole_observation_is_immutable_and_exposes_no_version_field
    """
    built = _planning_route_with_one_dock_street_segment(engineer_headers)
    walkout = fx.create_walkout(
        built["segment_id"], headers=surveyor_headers, walked_on="2026-08-11"
    )

    observation = validate_success(
        api.create_pole_observation(
            create_pole_observation_payload(
                walkout["id"],
                pole_tag="P-001",
                pole_owner="ELECTRIC_UTILITY",
                condition_grade="D",
                available_vertical_clearance_in=38,
                existing_attachment_count=4,
            ),
            headers=surveyor_headers,
        ),
        201,
    )
    assert observation["walkout_id"] == walkout["id"]
    assert observation["pole_tag"] == "P-001"
    assert observation["pole_owner"] == "ELECTRIC_UTILITY"
    assert observation["condition_grade"] == "D"
    assert observation["available_vertical_clearance_in"] == 38
    assert observation["existing_attachment_count"] == 4
    assert observation["requires_make_ready"] is True
    assert observation["id"]
    assert "version" not in observation
    assert "updated_at" not in observation
    assert_append_only_audit_fields(observation, "PoleObservation")

    rows = validate_success(
        api.list_pole_observations(walkout["id"], headers=surveyor_headers)
    )
    assert ids_of(rows) == [observation["id"]]
    assert "version" not in rows[0]

    reread = fx.read_walkout(walkout["id"])
    assert reread["worst_pole_condition_grade"] == "D"
    assert reread["make_ready_flagged_pole_count"] == 1


def test_a_walkout_against_an_unknown_segment_is_a_missing_row_not_a_bad_body(
    api, engineer_headers, surveyor_headers
):
    """The body foreign key resolves to a 404, while omitting it is a 400.

    PRD: "A nonexistent `walkout_id` is `ERR_WALKOUT_NOT_FOUND`; a nonexistent
    `segment_id` or `predecessor_segment_id` is `ERR_SEGMENT_NOT_FOUND`; a
    nonexistent `route_id` is `ERR_ROUTE_NOT_FOUND`; a nonexistent `design_id` is
    `ERR_DESIGN_NOT_FOUND`."

    Design: Corner/entities/walkout_create_with_unknown_segment_id_returns_segment_not_found
    """
    built = _planning_route_with_one_dock_street_segment(engineer_headers)

    unknown = api.create_walkout(
        create_walkout_payload(NON_EXISTENT_UUID, walked_on="2026-08-11"),
        headers=surveyor_headers,
    )
    validate_error(unknown, "ERR_SEGMENT_NOT_FOUND", 404)

    rows, meta = validate_paginated(
        api.list_segment_walkouts(built["segment_id"], headers=surveyor_headers)
    )
    assert rows == []
    assert meta["total_count"] == 0

    absent = api.create_walkout({"walked_on": "2026-08-11"}, headers=surveyor_headers)
    validate_error(absent, "ERR_INVALID_REQUEST", 400)


# ---------------------------------------------------------------------------
# The submit / review loop
# ---------------------------------------------------------------------------


def test_submitting_an_open_walkout_hands_it_to_engineering_without_touching_the_segment(
    api, engineer_headers, surveyor_headers
):
    """OPEN to SUBMITTED bumps the walkout's version and leaves the segment in DRAFT.

    PRD: "Submission requires at least one pole observation on the walkout — a
    walkout with none is refused with `ERR_WALKOUT_HAS_NO_OBSERVATIONS` — and drives
    `OPEN → SUBMITTED`."

    Design: Corner/state_machines/walkout_submit_moves_open_to_submitted
    """
    built = _planning_route_with_one_dock_street_segment(engineer_headers)
    walkout = fx.create_walkout(
        built["segment_id"], headers=surveyor_headers, walked_on="2026-08-11"
    )
    fx.add_pole_observation(
        walkout["id"],
        headers=surveyor_headers,
        pole_tag="P-001",
        pole_owner="TELCO",
        condition_grade="B",
        available_vertical_clearance_in=45,
        existing_attachment_count=2,
    )
    before = fx.read_walkout(walkout["id"])

    submitted = validate_success(api.submit_walkout(walkout["id"], headers=surveyor_headers))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["review_round"] == 0
    assert submitted["reviewed_by_user_id"] is None
    assert submitted["rejection_reason"] is None
    assert submitted["worst_pole_condition_grade"] == "B"
    assert submitted["make_ready_flagged_pole_count"] == 0
    assert submitted["version"] == before["version"] + 1

    segment = fx.read_segment(built["segment_id"])
    assert segment["engineering_status"] == "DRAFT", (
        "only an accepted review advances the engineering dimension"
    )
    assert segment["accepted_obstruction_count"] == 0


def test_reviewing_a_walkout_that_was_never_submitted_is_a_state_fault(
    api, engineer_headers, surveyor_headers
):
    """Review is defined only from SUBMITTED, so an OPEN walkout answers 409.

    PRD: "A `RouteEngineer` reviews a submitted walkout by supplying a `decision`,
    with `rejection_reason` as an accompanying optional field."

    Design: Corner/state_machines/walkout_review_on_an_open_walkout_returns_invalid_walkout_state
    """
    built = _planning_route_with_one_dock_street_segment(engineer_headers)
    walkout = fx.create_walkout(
        built["segment_id"], headers=surveyor_headers, walked_on="2026-08-11"
    )
    fx.add_pole_observation(
        walkout["id"],
        headers=surveyor_headers,
        pole_tag="P-001",
        pole_owner="TELCO",
        condition_grade="B",
        available_vertical_clearance_in=45,
        existing_attachment_count=2,
    )

    premature = api.review_walkout(
        walkout["id"], walkout_review_payload("ACCEPTED"), headers=engineer_headers
    )
    validate_error(premature, "ERR_INVALID_WALKOUT_STATE", 409)

    unchanged = fx.read_walkout(walkout["id"])
    assert unchanged["status"] == "OPEN"
    assert unchanged["reviewed_by_user_id"] is None
    assert fx.read_segment(built["segment_id"])["engineering_status"] == "DRAFT"
    assert fx.read_route(built["route_id"])["status"] == "PLANNING"


def test_a_resubmitted_walkout_keeps_the_review_round_the_rejection_earned(
    api, engineer_headers, surveyor_headers
):
    """The revision loop is not a reset: round 1 and the reason both survive.

    PRD: "The same submission operation also serves the revision loop: a walkout
    sitting at `REJECTED` is submitted again, which passes it through `OPEN` and
    immediately re-evaluates the `OPEN → SUBMITTED` transition inside the same
    request, so the response the surveyor receives shows the walkout at `SUBMITTED`
    rather than at `OPEN`."

    Design: Corner/state_machines/walkout_rejection_then_resubmission_retains_the_incremented_review_round
    """
    built = _planning_route_with_one_dock_street_segment(engineer_headers)
    walkout = fx.create_walkout(
        built["segment_id"], headers=surveyor_headers, walked_on="2026-08-11"
    )
    fx.add_pole_observation(
        walkout["id"],
        headers=surveyor_headers,
        pole_tag="P-001",
        pole_owner="TELCO",
        condition_grade="B",
        available_vertical_clearance_in=45,
        existing_attachment_count=2,
    )
    fx.submit_walkout(walkout["id"], headers=surveyor_headers)
    rejected = fx.review_walkout(
        walkout["id"],
        "REJECTED",
        headers=engineer_headers,
        rejection_reason="pole count does not match the field sketch",
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["review_round"] == 1
    assert rejected["rejection_reason"] == "pole count does not match the field sketch"

    resubmitted = validate_success(api.submit_walkout(walkout["id"], headers=surveyor_headers))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["review_round"] == 1, "the round the rejection earned is retained"
    assert resubmitted["rejection_reason"] == "pole count does not match the field sketch"

    assert fx.read_segment(built["segment_id"])["engineering_status"] == "DRAFT"


def test_a_rejection_without_a_reason_is_a_malformed_request(
    api, engineer_headers, surveyor_headers
):
    """The reason is mandatory on the rejecting branch and only on that branch.

    PRD: "**Rejection** moves the walkout `SUBMITTED → REJECTED` and requires a
    `rejection_reason` that is present and non-blank; a rejection submitted without
    one is `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/walkout_rejection_then_resubmission_retains_the_incremented_review_round
    """
    built = _planning_route_with_one_dock_street_segment(engineer_headers)
    walkout = fx.create_walkout(
        built["segment_id"], headers=surveyor_headers, walked_on="2026-08-11"
    )
    fx.add_pole_observation(
        walkout["id"],
        headers=surveyor_headers,
        pole_tag="P-001",
        pole_owner="TELCO",
        condition_grade="B",
        available_vertical_clearance_in=45,
        existing_attachment_count=2,
    )
    fx.submit_walkout(walkout["id"], headers=surveyor_headers)

    reasonless = api.review_walkout(
        walkout["id"], {"decision": "REJECTED"}, headers=engineer_headers
    )
    validate_error(reasonless, "ERR_INVALID_REQUEST", 400)

    unchanged = fx.read_walkout(walkout["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["review_round"] == 0


def test_a_walkout_with_no_observations_cannot_be_submitted_until_one_is_appended(
    api, engineer_headers, surveyor_headers
):
    """The empty-collection refusal comes first; one grade-C pole unblocks the call.

    PRD: "Submission requires at least one pole observation on the walkout — a
    walkout with none is refused with `ERR_WALKOUT_HAS_NO_OBSERVATIONS` — and drives
    `OPEN → SUBMITTED`."

    Design: Corner/errors/walkout_submit_with_no_pole_observations_returns_the_empty_collection_error
    """
    built = _planning_route_with_one_dock_street_segment(engineer_headers)
    walkout = fx.create_walkout(
        built["segment_id"],
        headers=surveyor_headers,
        walked_on="2026-08-11",
        obstruction_count=0,
    )

    empty = api.submit_walkout(walkout["id"], headers=surveyor_headers)
    validate_error(empty, "ERR_WALKOUT_HAS_NO_OBSERVATIONS", 422)

    still_open = fx.read_walkout(walkout["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["worst_pole_condition_grade"] == "NONE"

    observation = fx.add_pole_observation(
        walkout["id"],
        headers=surveyor_headers,
        pole_tag="P-001",
        pole_owner="ELECTRIC_UTILITY",
        condition_grade="C",
        available_vertical_clearance_in=40,
        existing_attachment_count=3,
    )
    assert observation["requires_make_ready"] is True
    assert "version" not in observation

    submitted = validate_success(api.submit_walkout(walkout["id"], headers=surveyor_headers))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["worst_pole_condition_grade"] == "C"
    assert submitted["review_round"] == 0
