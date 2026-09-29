"""Composite state builders.

Every helper here drives the real API through the same endpoints a client would
use, because the server starts from an empty database for each test.  Setup steps
use the lenient ``get_success_data`` so that a broken precondition surfaces as a
setup failure rather than as a misleading assertion failure inside a test.

The builders are layered:

* primitives -- one call each (clock, route, segment, walkout, observation, ...)
* state progression -- walk a single entity to a named status
* entity hierarchy -- a route plus its segment chain plus their walkouts
* lifecycle shortcuts -- scope-locked, permitting, construction-ready, records-updated
* accumulation / threshold targeting -- make-ready, fiber and complexity setups
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import TEST_USERS, USER_IDS

JsonDict = Dict[str, Any]

ENGINEER = TEST_USERS["route_engineer"]
ENGINEER_2 = TEST_USERS["route_engineer_second"]
ENGINEER_3 = TEST_USERS["route_engineer_third"]
SURVEYOR = TEST_USERS["field_surveyor"]
COORDINATOR = TEST_USERS["permit_coordinator"]
REVIEWER = TEST_USERS["authority_reviewer"]
OWNER = TEST_USERS["pole_owner"]
ADMIN = TEST_USERS["network_records_admin"]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> JsonDict:
    """Move the logical clock; mutates no entity and evaluates no transition."""

    return get_success_data(
        api_client.set_clock(factories.clock_payload(to_iso8601), headers=ADMIN)
    )


def create_route(headers: Optional[JsonDict] = None, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_route(
            factories.create_route_payload(**overrides), headers=headers or ENGINEER
        )
    )


def read_route(route_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api_client.get_route(route_id, headers=headers or ENGINEER))


def route_version(route_id: str) -> int:
    """The route's current ``version``, i.e. the concurrency token to send next."""

    return read_route(route_id)["version"]


def adjust_budget(route_id: str, delta_cents: int, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.adjust_route_budget(
            route_id, factories.budget_adjustment_payload(delta_cents, **overrides), headers=ADMIN
        )
    )


def create_segment(route_id: str, headers: Optional[JsonDict] = None, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_segment(
            factories.create_segment_payload(route_id, **overrides), headers=headers or ENGINEER
        )
    )


def read_segment(segment_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api_client.get_segment(segment_id, headers=headers or ENGINEER))


def create_walkout(segment_id: str, headers: Optional[JsonDict] = None, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_walkout(
            factories.create_walkout_payload(segment_id, **overrides), headers=headers or SURVEYOR
        )
    )


def add_pole_observation(
    walkout_id: str, headers: Optional[JsonDict] = None, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.create_pole_observation(
            factories.create_pole_observation_payload(walkout_id, **overrides),
            headers=headers or SURVEYOR,
        )
    )


def submit_walkout(walkout_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api_client.submit_walkout(walkout_id, headers=headers or SURVEYOR))


def review_walkout(
    walkout_id: str, decision: str, headers: Optional[JsonDict] = None, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.review_walkout(
            walkout_id,
            factories.walkout_review_payload(decision, **overrides),
            headers=headers or ENGINEER,
        )
    )


def read_walkout(walkout_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api_client.get_walkout(walkout_id, headers=headers or ENGINEER))


def create_moratorium_window(**overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_moratorium_window(
            factories.create_moratorium_window_payload(**overrides), headers=ADMIN
        )
    )


def lock_scope(route_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api_client.lock_route_scope(route_id, headers=headers or ENGINEER))


def select_method(
    segment_id: str,
    method: str,
    expected_route_version: int,
    headers: Optional[JsonDict] = None,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api_client.select_construction_method(
            segment_id,
            factories.construction_method_payload(method, expected_route_version, **overrides),
            headers=headers or ENGINEER,
        )
    )


def select_method_on_route(
    route_id: str, segment_id: str, method: str, headers: Optional[JsonDict] = None
) -> JsonDict:
    """Select a method after reading the route's current version for the token."""

    return select_method(segment_id, method, route_version(route_id), headers=headers)


def request_bid_ready(segment_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.request_bid_ready_estimate(segment_id, headers=headers or ENGINEER)
    )


def create_permit(segment_id: str, headers: Optional[JsonDict] = None, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_permit_application(
            factories.create_permit_application_payload(segment_id, **overrides),
            headers=headers or COORDINATOR,
        )
    )


def submit_permit(permit_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.submit_permit_application(permit_id, headers=headers or COORDINATOR)
    )


def review_permit(
    permit_id: str, decision: str, headers: Optional[JsonDict] = None, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.review_permit_application(
            permit_id,
            factories.permit_review_payload(decision, **overrides),
            headers=headers or REVIEWER,
        )
    )


def claim_deemed_decision(permit_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.claim_deemed_decision(permit_id, headers=headers or COORDINATOR)
    )


def read_permit(permit_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.get_permit_application(permit_id, headers=headers or COORDINATOR)
    )


def create_pole_application(
    segment_id: str, headers: Optional[JsonDict] = None, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.create_pole_attachment_application(
            factories.create_pole_attachment_application_payload(segment_id, **overrides),
            headers=headers or COORDINATOR,
        )
    )


def submit_pole_application(application_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.submit_pole_attachment_application(application_id, headers=headers or COORDINATOR)
    )


def owner_respond(
    application_id: str,
    outcome: str,
    make_ready_items: Optional[List[JsonDict]] = None,
    headers: Optional[JsonDict] = None,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api_client.respond_as_pole_owner(
            application_id,
            factories.owner_response_payload(outcome, make_ready_items, **overrides),
            headers=headers or OWNER,
        )
    )


def accept_make_ready(application_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.accept_make_ready(application_id, headers=headers or COORDINATOR)
    )


def withdraw_pole_application(
    application_id: str, headers: Optional[JsonDict] = None, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.withdraw_pole_attachment_application(
            application_id, factories.withdraw_payload(**overrides), headers=headers or COORDINATOR
        )
    )


def read_pole_application(application_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.get_pole_attachment_application(application_id, headers=headers or COORDINATOR)
    )


def create_design(
    route_id: str,
    expected_route_version: Optional[int] = None,
    headers: Optional[JsonDict] = None,
    **overrides: Any,
) -> JsonDict:
    token = route_version(route_id) if expected_route_version is None else expected_route_version
    return get_success_data(
        api_client.create_design_package(
            factories.create_design_package_payload(route_id, token, **overrides),
            headers=headers or ENGINEER,
        )
    )


def read_design(design_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api_client.get_design_package(design_id, headers=headers or ENGINEER))


def place_splice_point(
    design_id: str, segment_id: str, headers: Optional[JsonDict] = None, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.create_splice_point(
            factories.create_splice_point_payload(design_id, segment_id, **overrides),
            headers=headers or ENGINEER,
        )
    )


def void_splice_point(splice_point_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.void_splice_point(splice_point_id, headers=headers or ENGINEER)
    )


def submit_design(design_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api_client.submit_design_for_review(design_id, headers=headers or ENGINEER)
    )


def stamp_design(design_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api_client.stamp_design_package(design_id, headers=headers or ENGINEER_2))


def return_design_to_draft(
    design_id: str, return_note: str, headers: Optional[JsonDict] = None
) -> JsonDict:
    return get_success_data(
        api_client.return_design_to_draft(
            design_id, factories.return_to_draft_payload(return_note), headers=headers or ENGINEER_2
        )
    )


def create_as_built(route_id: str, headers: Optional[JsonDict] = None, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_as_built_record(
            factories.create_as_built_record_payload(route_id, **overrides),
            headers=headers or SURVEYOR,
        )
    )


def certify_as_built(
    as_built_id: str, decision: str, headers: Optional[JsonDict] = None, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.certify_as_built_record(
            as_built_id, factories.certify_payload(decision, **overrides), headers=headers or ENGINEER_3
        )
    )


def read_as_built(as_built_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api_client.get_as_built_record(as_built_id, headers=headers or ENGINEER))


# ---------------------------------------------------------------------------
# State progression: field walkout
# ---------------------------------------------------------------------------

#: One grade-B pole with 45 inches of clearance: requires_make_ready is false.
CLEAN_POLE: JsonDict = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}

#: One grade-D pole: requires_make_ready is true and the grade-D rule applies.
GRADE_D_POLE: JsonDict = {
    "pole_tag": "P-002",
    "pole_owner": "TELCO",
    "condition_grade": "D",
    "available_vertical_clearance_in": 38,
    "existing_attachment_count": 3,
}


def submitted_walkout(
    segment_id: str, observations: Optional[Sequence[JsonDict]] = None, **overrides: Any
) -> JsonDict:
    """Open a walkout, append observations and submit it for engineering review."""

    walkout = create_walkout(segment_id, **overrides)
    for observation in observations or (CLEAN_POLE,):
        add_pole_observation(walkout["id"], **observation)
    return submit_walkout(walkout["id"])


def accepted_walkout(
    segment_id: str,
    observations: Optional[Sequence[JsonDict]] = None,
    reviewer: Optional[JsonDict] = None,
    **overrides: Any,
) -> JsonDict:
    """Drive a segment's engineering dimension from DRAFT to WALKED."""

    walkout = submitted_walkout(segment_id, observations, **overrides)
    return review_walkout(walkout["id"], "ACCEPTED", headers=reviewer or ENGINEER)


# ---------------------------------------------------------------------------
# Entity hierarchy: routes and segment chains
# ---------------------------------------------------------------------------


def route_with_segments(
    segment_specs: Sequence[JsonDict], route_overrides: Optional[JsonDict] = None
) -> JsonDict:
    """A PLANNING route plus one segment per spec, in the order given."""

    route = create_route(**(route_overrides or {}))
    segments: List[JsonDict] = []
    for index, spec in enumerate(segment_specs, start=1):
        spec = dict(spec)
        spec.setdefault("sequence_index", index)
        segments.append(create_segment(route["id"], **spec))
    return {"route": route, "segments": segments}


def route_with_walked_segments(
    segment_specs: Sequence[JsonDict],
    route_overrides: Optional[JsonDict] = None,
    observations: Optional[Sequence[JsonDict]] = None,
) -> JsonDict:
    """Every segment has an ACCEPTED walkout, so the route can lock its scope."""

    built = route_with_segments(segment_specs, route_overrides)
    walkouts: List[JsonDict] = []
    for index, segment in enumerate(built["segments"], start=1):
        walkouts.append(
            accepted_walkout(
                segment["id"],
                observations,
                walked_on="2026-08-11",
            )
        )
    built["walkouts"] = walkouts
    return built


def scope_locked_route(
    segment_specs: Optional[Sequence[JsonDict]] = None,
    route_overrides: Optional[JsonDict] = None,
    observations: Optional[Sequence[JsonDict]] = None,
) -> JsonDict:
    """A SCOPE_LOCKED route: both complexity indices are seeded at the lock."""

    specs = segment_specs if segment_specs is not None else [{}]
    built = route_with_walked_segments(specs, route_overrides, observations)
    built["route"] = lock_scope(built["route"]["id"])
    return built


def method_selected_route(
    method: str = "AERIAL",
    segment_specs: Optional[Sequence[JsonDict]] = None,
    route_overrides: Optional[JsonDict] = None,
    observations: Optional[Sequence[JsonDict]] = None,
) -> JsonDict:
    """A scope-locked route whose every segment sits at METHOD_SELECTED."""

    built = scope_locked_route(segment_specs, route_overrides, observations)
    route_id = built["route"]["id"]
    selected: List[JsonDict] = []
    for segment in built["segments"]:
        selected.append(select_method_on_route(route_id, segment["id"], method))
    built["segments"] = selected
    built["route"] = read_route(route_id)
    return built


def design_locked_route(
    method: str = "AERIAL",
    segment_specs: Optional[Sequence[JsonDict]] = None,
    route_overrides: Optional[JsonDict] = None,
    observations: Optional[Sequence[JsonDict]] = None,
) -> JsonDict:
    """Every segment at DESIGN_LOCKED with both cost variants written."""

    built = method_selected_route(method, segment_specs, route_overrides, observations)
    locked = [request_bid_ready(segment["id"]) for segment in built["segments"]]
    built["segments"] = locked
    built["route"] = read_route(built["route"]["id"])
    return built


# ---------------------------------------------------------------------------
# Permitting shortcuts
# ---------------------------------------------------------------------------


def filed_permit(segment_id: str, **overrides: Any) -> JsonDict:
    """Draft a permit and file it, computing the review schedule."""

    permit = create_permit(segment_id, **overrides)
    return submit_permit(permit["id"])


def cleared_segment_permit(
    segment_id: str, reviewer: Optional[JsonDict] = None, **overrides: Any
) -> JsonDict:
    """File one permit and have the authority approve it, clearing the segment."""

    permit = filed_permit(segment_id, **overrides)
    return review_permit(
        permit["id"], "APPROVED", headers=reviewer or REVIEWER, decision_note="approved as filed"
    )


def permitting_route(
    segment_specs: Optional[Sequence[JsonDict]] = None,
    route_overrides: Optional[JsonDict] = None,
    method: str = "AERIAL",
) -> JsonDict:
    """A design-locked route with every segment permit-CLEARED, so it is at PERMITTING."""

    built = design_locked_route(method, segment_specs, route_overrides)
    permits = [cleared_segment_permit(segment["id"]) for segment in built["segments"]]
    built["permits"] = permits
    built["segments"] = [read_segment(segment["id"]) for segment in built["segments"]]
    built["route"] = read_route(built["route"]["id"])
    return built


# ---------------------------------------------------------------------------
# Design shortcuts
# ---------------------------------------------------------------------------

#: One handhole at station 0 dropping 24 of a 288-fiber cable.
DEFAULT_SPLICE: JsonDict = {"station_feet": 0, "enclosure_type": "HANDHOLE", "fiber_count_dropped": 24}


def design_with_splice_points(
    route_id: str,
    segment_id: str,
    splices: Optional[Sequence[JsonDict]] = None,
    design_overrides: Optional[JsonDict] = None,
) -> JsonDict:
    """A DRAFT design revision carrying the given placed splice points."""

    design = create_design(route_id, **(design_overrides or {}))
    placed: List[JsonDict] = []
    for splice in splices or (DEFAULT_SPLICE,):
        placed.append(place_splice_point(design["id"], segment_id, **splice))
    return {"design": read_design(design["id"]), "splice_points": placed}


def design_in_review(
    route_id: str,
    segment_id: str,
    splices: Optional[Sequence[JsonDict]] = None,
    design_overrides: Optional[JsonDict] = None,
    submitter: Optional[JsonDict] = None,
) -> JsonDict:
    """A design at IN_REVIEW with ``submitted_by_user_id`` recorded."""

    built = design_with_splice_points(route_id, segment_id, splices, design_overrides)
    built["design"] = submit_design(built["design"]["id"], headers=submitter or ENGINEER)
    return built


def stamped_design(
    route_id: str,
    segment_id: str,
    splices: Optional[Sequence[JsonDict]] = None,
    design_overrides: Optional[JsonDict] = None,
    submitter: Optional[JsonDict] = None,
    stamper: Optional[JsonDict] = None,
) -> JsonDict:
    """A STAMPED design: the stamper is a different individual from the submitter."""

    built = design_in_review(route_id, segment_id, splices, design_overrides, submitter)
    built["design"] = stamp_design(built["design"]["id"], headers=stamper or ENGINEER_2)
    return built


# ---------------------------------------------------------------------------
# Full lifecycle shortcuts
# ---------------------------------------------------------------------------


def construction_ready_route(
    segment_specs: Optional[Sequence[JsonDict]] = None,
    route_overrides: Optional[JsonDict] = None,
    splices: Optional[Sequence[JsonDict]] = None,
    design_overrides: Optional[JsonDict] = None,
    submitter: Optional[JsonDict] = None,
    stamper: Optional[JsonDict] = None,
    method: str = "AERIAL",
) -> JsonDict:
    """A CONSTRUCTION_READY route: every segment CLEARED and one design STAMPED.

    The stamp lands after the permit approvals, so it is the stamp that completes
    the two-part condition and drives the route out of PERMITTING.
    """

    built = permitting_route(segment_specs, route_overrides, method)
    route_id = built["route"]["id"]
    head_segment_id = built["segments"][0]["id"]
    design_bundle = stamped_design(
        route_id, head_segment_id, splices, design_overrides, submitter, stamper
    )
    built.update(design_bundle)
    built["route"] = read_route(route_id)
    built["segments"] = [read_segment(segment["id"]) for segment in built["segments"]]
    return built


def submitted_as_built(
    segment_specs: Optional[Sequence[JsonDict]] = None,
    route_overrides: Optional[JsonDict] = None,
    as_built_overrides: Optional[JsonDict] = None,
    splices: Optional[Sequence[JsonDict]] = None,
    submitter: Optional[JsonDict] = None,
    stamper: Optional[JsonDict] = None,
) -> JsonDict:
    """A construction-ready route with one SUBMITTED as-built record filed on it."""

    built = construction_ready_route(
        segment_specs, route_overrides, splices, submitter=submitter, stamper=stamper
    )
    overrides = dict(as_built_overrides or {})
    overrides.setdefault("design_revision", built["design"]["revision"])
    overrides.setdefault("as_built_length_feet", built["route"]["design_total_length_feet"])
    overrides.setdefault("splice_point_count_field_verified", built["design"]["splice_point_count"])
    built["as_built"] = create_as_built(built["route"]["id"], **overrides)
    built["route"] = read_route(built["route"]["id"])
    return built


# ---------------------------------------------------------------------------
# Accumulation / threshold targeting: make-ready and budget
# ---------------------------------------------------------------------------


def estimated_pole_application(
    segment_id: str,
    make_ready_items: Sequence[JsonDict],
    application_overrides: Optional[JsonDict] = None,
    owner_note: str = "estimate returned",
) -> JsonDict:
    """An application at MAKE_READY_ESTIMATED with its make-ready breakdown derived."""

    application = create_pole_application(segment_id, **(application_overrides or {}))
    submit_pole_application(application["id"])
    return owner_respond(
        application["id"], "ESTIMATED", list(make_ready_items), owner_note=owner_note
    )


def granted_pole_application(
    segment_id: str,
    make_ready_items: Sequence[JsonDict],
    application_overrides: Optional[JsonDict] = None,
) -> JsonDict:
    """An application at GRANTED, so its cost is committed against the route budget."""

    estimated = estimated_pole_application(segment_id, make_ready_items, application_overrides)
    return accept_make_ready(estimated["id"])


def moratorium_on_segment_street(
    starts_on: str,
    ends_on: str,
    moratorium_class: str,
    street_name: str = "Dock Street",
    municipality_code: str = "MUN-014",
    **overrides: Any,
) -> JsonDict:
    """Register one paving moratorium on the street a segment runs down."""

    return create_moratorium_window(
        municipality_code=municipality_code,
        street_name=street_name,
        starts_on=starts_on,
        ends_on=ends_on,
        moratorium_class=moratorium_class,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def ids(rows: Iterable[JsonDict]) -> List[str]:
    return [row["id"] for row in rows]
