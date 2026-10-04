"""Management units, response envelope, computed-field and read paths.

Covers unit creation shape rules, server-computed fields (provisional fee,
volunteer cleared_on, citation points, unresolved comment count), not-found
reads, the winning-bid reverse reach, the success envelope, pagination, and
the unit's computed posture snapshot.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    is_iso8601_timestamp,
    create_unit, get_unit_posture,
    create_determination, create_final_determination,
    create_determination_in_public_comment, get_determination,
    submit_comment, adjudicate_comment,
    create_submitted_permit, create_approved_permit, get_permit,
    create_volunteer, clear_volunteer,
    issue_permit_citation,
    setup_awarded_agreement,
    create_management_unit_payload,
    assert_posture_snapshot,
    advance_clock,
)


def test_unit_create_missing_required_field_returns_400(api):
    """PRD §3.1: "A `RefugeManager` creates one by supplying a `name` — a
    human-readable label such as "North Marsh" — a `habitat_type` of exactly
    one of `WETLAND`, `GRASSLAND`, `FOREST`, or `MIXED`, and an `acreage` that
    must be an integer greater than zero."
    PRD §2.6: "**Request shape** — required fields are present, types match,
    enum members are valid, and citation creation supplies exactly one of its
    two subject references (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/unit_create_missing_required_field_returns_400
    """
    resp = api_client.create_management_unit(
        {"name": "No Habitat Unit", "acreage": 100},
        TEST_USERS["refuge_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_unit_create_invalid_enum_returns_invalid_request(api):
    """PRD §3.1: "a `habitat_type` of exactly one of `WETLAND`, `GRASSLAND`,
    `FOREST`, or `MIXED`, and an `acreage` that must be an integer greater
    than zero."
    PRD §2.6: "**Request shape** — required fields are present, types match,
    enum members are valid, and citation creation supplies exactly one of its
    two subject references (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/unit_create_invalid_enum_returns_invalid_request
    """
    resp = api_client.create_management_unit(
        create_management_unit_payload(
            name="Bad Unit", habitat_type="DESERT", acreage=100),
        TEST_USERS["refuge_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_permit_create_provisional_fee_ignores_crew_size(api):
    """PRD §3.3: "The estimate is deliberately flat: it is the base fee for the
    requested use type and nothing else — 15000 cents for `RESEARCH`, 7500
    cents for `PHOTOGRAPHY`, 20000 cents for `COMMERCIAL_FILMING`, and 3000
    cents for `GUIDED_ACTIVITY`. Crew size, trip length, tiering, surcharge,
    floor, and cap are all ignored at this stage, so the provisional figure
    and the eventual assessed figure differ for identical application data: a
    research application for a crew of four over three days shows 15000 cents
    provisionally and will assess at 21000 cents."

    Design: Corner/entities/permit_create_provisional_fee_ignores_crew_size
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit_small = create_submitted_permit(
        unit["id"], det["id"], applicant_ref="app-1", crew_size=1)
    permit_large = create_submitted_permit(
        unit["id"], det["id"], applicant_ref="app-2", crew_size=99)
    assert permit_small["provisional_fee_cents"] == 15000, (
        f"crew 1 provisional must be the flat RESEARCH base 15000, "
        f"got {permit_small['provisional_fee_cents']}")
    assert permit_large["provisional_fee_cents"] == 15000, (
        f"crew 99 provisional must still be 15000 (crew size ignored), "
        f"got {permit_large['provisional_fee_cents']}")


def test_volunteer_cleared_on_stamps_logical_clock_date(api):
    """PRD §3.6: "a `VolunteerCoordinator` or `RefugeManager` clears a
    volunteer whose `background_status` is `PENDING` or `EXPIRED`, moving it
    to `CLEARED` and stamping `cleared_on` with the current logical clock
    date; clearing an `EXPIRED` volunteer is a renewal under exactly the same
    rule."

    Design: Corner/entities/volunteer_cleared_on_stamps_logical_clock_date
    """
    volunteer = create_volunteer(full_name="Vol One", email="v1@x.com")
    advance_clock("2026-09-12T00:00:00Z")
    cleared = clear_volunteer(volunteer["id"])
    assert cleared["background_status"] == "CLEARED"
    assert cleared["cleared_on"] == "2026-09-12", (
        f"cleared_on must be the logical clock date 2026-09-12, "
        f"got {cleared['cleared_on']}")


def test_citation_points_computed_from_severity(api):
    """PRD §3.8: "The citation's `points` are computed from severity and never
    taken from the input, even if a value is supplied: 10 for `MINOR`, 25 for
    `MAJOR`, 50 for `CRITICAL`."
    PRD §3.8: "Against a permit subject, the citation records the violation and
    nothing more — no fee changes, no permit status change, and no version
    field on the request."

    Design: Corner/entities/citation_points_computed_from_severity
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_approved_permit(unit["id"], det["id"], applicant_ref="app-1")
    citation = issue_permit_citation(
        permit["id"], severity="MAJOR", note="Off-trail intrusion")
    assert citation["points"] == 25, (
        f"MAJOR citation points must be computed as 25, got {citation['points']}")
    after = get_permit(permit["id"])
    assert after["status"] == "APPROVED", (
        f"permit-subject citation must not change permit status, "
        f"got {after['status']}")


def test_determination_unresolved_count_tracks_comments(api):
    """PRD §3.2: "each submission creates a comment in `SUBMITTED` status —
    its `disposition` still null — and increments the determination's
    `unresolved_comment_count` by one."
    PRD §3.2: "each adjudication moves the comment to `ADJUDICATED` and
    decrements the determination's `unresolved_comment_count` by one."

    Design: Corner/entities/determination_unresolved_count_tracks_comments
    """
    det = create_determination_in_public_comment(use_type="PHOTOGRAPHY")
    comment = submit_comment(det["id"], author_name="A", body="first")
    submit_comment(det["id"], author_name="B", body="second")
    after_two = get_determination(det["id"])
    assert after_two["unresolved_comment_count"] == 2, (
        f"two submitted comments must report 2 unresolved, "
        f"got {after_two['unresolved_comment_count']}")
    adjudicate_comment(comment["id"], disposition="ACCEPTED")
    after_one = get_determination(det["id"])
    assert after_one["unresolved_comment_count"] == 1, (
        f"one adjudication must drop the count to 1, "
        f"got {after_one['unresolved_comment_count']}")


def test_permit_read_nonexistent_returns_not_found(api):
    """PRD §2.6: "**Existence** — every path identifier and every
    body-supplied resource reference resolves to an existing resource,
    validated left to right, path first and then body (`ERR_NOT_FOUND`,
    404)."

    Design: Corner/entities/permit_read_nonexistent_returns_not_found
    """
    resp = api_client.get_permit(
        "00000000-0000-0000-0000-000000000000",
        TEST_USERS["permit_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_agreement_reachable_via_winning_bid_filter(api):
    """PRD §3.7: "It is built by copying: `management_unit_id`, `aum_cap`,
    `grazing_window_start`, and `grazing_window_end` come from the offering,
    `cooperator_ref` comes from the winning bid, and `winning_bid_id` records
    the winning bid itself, one agreement per winning bid."
    PRD §3.8: "Agreements are readable individually and through a listing
    filtered optionally by `management_unit_id`, `winning_bid_id`, and
    `status` with `limit` and `offset`; citations are likewise readable
    individually and through a listing filtered by `subject_permit_id`,
    `subject_agreement_id`, and `status` with `limit` and `offset`."

    Design: Corner/entities/agreement_reachable_via_winning_bid_filter
    """
    ctx = setup_awarded_agreement()
    resp = api_client.list_agreements(
        TEST_USERS["refuge_manager_headers"],
        params={"winning_bid_id": ctx["winning_bid"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1 and len(data) == 1, (
        f"exactly one agreement must exist per winning bid, "
        f"got total_count {meta['total_count']}")
    agreement = data[0]
    assert agreement["management_unit_id"] == ctx["unit"]["id"], (
        "management_unit_id must be copied from the offering's unit")
    assert agreement["cooperator_ref"] == "coop-1", (
        f"cooperator_ref must be copied from the winning bid, "
        f"got {agreement['cooperator_ref']}")
    assert agreement["status"] == "ACTIVE"


def test_response_envelope_success_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_success_shape
    """
    unit = create_unit()
    resp = api_client.get_management_unit(
        unit["id"], TEST_USERS["biologist_headers"])
    validate_success(resp)
    body = resp.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, "
        f"got {body['meta']['api_request_id']!r}")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
        "api_request_timestamp must be an ISO 8601 timestamp")
    assert body["response_type"] == "object", (
        f"single-resource read must report response_type object, "
        f"got {body['response_type']!r}")
    assert body["data"]["id"] == unit["id"]


def test_list_pagination_limit_and_has_more(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; when omitted it defaults to 10, and any supplied value must be
    at least 1 and at most 100. The `offset` parameter specifies how many
    items to skip and defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope, alongside `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/list_pagination_limit_and_has_more
    """
    unit = create_unit()
    det = create_determination(use_type="RESEARCH")
    create_submitted_permit(
        unit["id"], det["id"], applicant_ref="app-1", crew_size=1,
        start_date="2026-10-10", end_date="2026-10-10")
    create_submitted_permit(
        unit["id"], det["id"], applicant_ref="app-2", crew_size=1,
        start_date="2026-10-11", end_date="2026-10-11")
    resp = api_client.list_permits(
        TEST_USERS["permit_officer_headers"], params={"limit": 1})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return exactly 1 item, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_permits_filter_by_management_unit(api):
    """PRD §3.3: "Applicants and staff read permits individually or through
    the listing, which accepts optional filters on `applicant_ref`,
    `management_unit_id`, `determination_id`, and `status` alongside `limit`
    and `offset`."

    Design: Corner/endpoints/permits_filter_by_management_unit
    """
    unit_one = create_unit(name="Unit One", habitat_type="WETLAND", acreage=100)
    unit_two = create_unit(name="Unit Two", habitat_type="FOREST", acreage=100)
    det = create_determination(use_type="RESEARCH")
    create_submitted_permit(
        unit_one["id"], det["id"], applicant_ref="app-1", crew_size=1,
        start_date="2026-10-10", end_date="2026-10-10")
    create_submitted_permit(
        unit_two["id"], det["id"], applicant_ref="app-2", crew_size=1,
        start_date="2026-10-10", end_date="2026-10-10")
    resp = api_client.list_permits(
        TEST_USERS["permit_officer_headers"],
        params={"management_unit_id": unit_one["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, (
        f"filtering by unit must return exactly its permits, "
        f"got total_count {meta['total_count']}")
    assert data[0]["management_unit_id"] == unit_one["id"]


def test_posture_read_returns_full_snapshot(api):
    """PRD §3.1: "Creation initializes the unit's computed fields:
    `access_posture` starts at `OPEN`, `committed_visitor_days` starts at
    zero, and both habitat priority scores start at zero."
    PRD §3.1: "A computed read on the unit exposes the whole snapshot at once:
    the current `access_posture`, the `committed_visitor_days` tally,
    `habitat_priority_breeding`, `habitat_priority_annual`, and
    `active_closure_count`, the number of closures currently in `ACTIVE`
    status on the unit."

    Design: Corner/endpoints/posture_read_returns_full_snapshot
    """
    unit = create_unit()
    posture = get_unit_posture(unit["id"])
    assert_posture_snapshot(posture)
    assert posture["access_posture"] == "OPEN"
    assert posture["committed_visitor_days"] == 0
    assert posture["habitat_priority_breeding"] == 0
    assert posture["habitat_priority_annual"] == 0
    assert posture["active_closure_count"] == 0
