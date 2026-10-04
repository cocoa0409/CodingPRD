"""The launch gate, identifier/epoch rules and segregation-of-duties gates."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error

from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    setup_stack, make_corridor, make_state_authority, setup_launched_corridor,
    create_run, record_check, file_safety_case, submit_run,
    create_readiness_check_payload, create_load_securement_payload,
    create_regulatory_engagement_payload, create_incident_report_payload,
)


def _corridor(stack, **overrides):
    return make_corridor(stack["origin"]["id"], stack["destination"]["id"], **overrides)


def _launch_ready_corridor(stack, with_sensor=True, with_load=True, with_route=True):
    """Drive a corridor to READINESS_REVIEW with its evidence recorded and filed."""
    corridor = _corridor(stack)
    api_client.start_launch_readiness(corridor["id"], TEST_USERS["corridor_manager_headers"])
    if with_sensor:
        record_check(corridor["id"], "SENSOR_CALIBRATION", "PASS", 37.0, 38.0, "CAL-01")
    if with_load:
        record_check(corridor["id"], "LOAD_SECUREMENT", "PASS", 0.0, 0.0, "SEC-01",
                     load_payload_lbs=44000)
    if with_route:
        rte = record_check(corridor["id"], "ROUTE_VALIDATION", "PASS", 37.0, 38.0, "RTE-01")
        api_client.validate_check(rte["id"], TEST_USERS["corridor_manager_headers"],
                                  {"expected_check_version": rte["version"]})
    file_safety_case(corridor["id"])
    return validate_success(api_client.get_corridor(corridor["id"], TEST_USERS["any_headers"]))


# ─── boundary_precision_check / readiness_gate_empty_check_set_is_the_zero_edge

def test_readiness_gate_refuses_an_empty_included_check_set(api, any_headers):
    """PRD §2.6: "When no row is included, the corridor's `readiness_score` is 0."
    PRD §3.1: "First the corridor must clear its own readiness arithmetic:
    `check_pass_count` must be at least `check_count` with `check_count` at
    least 1 ... either failure is `ERR_READINESS_CHECK_FAILED` (409)."

    Design: Difficulty/boundary_precision_check/readiness_gate_empty_check_set_is_the_zero_edge
    """
    stack = setup_stack()
    corridor = _launch_ready_corridor(stack, with_sensor=False, with_load=False,
                                      with_route=False)
    assert corridor["check_count"] == 0
    assert corridor["readiness_score"] == 0
    resp = api_client.validate_launch_readiness(
        corridor["id"], TEST_USERS["corridor_manager_headers"],
        {"expected_corridor_version": corridor["version"]})
    validate_error(resp, ApiErrorId.ERR_READINESS_CHECK_FAILED)
    after = validate_success(api_client.get_corridor(corridor["id"], any_headers))
    assert after["corridor_status"] == "READINESS_REVIEW"


def test_readiness_gate_passes_once_one_securement_check_is_included(api, any_headers):
    """PRD §3.1: "First the corridor must clear its own readiness arithmetic:
    `check_pass_count` must be at least `check_count` with `check_count` at
    least 1".
    PRD §3.1: "On success the corridor increments its `version`, moves
    `corridor_status` to `ACTIVE`".

    A non-empty included set lifts check_count above zero with
    check_pass_count at least matching it, so the gate passes; the boundary sits
    at a non-empty included set, not at any score value.

    Design: Difficulty/boundary_precision_check/readiness_gate_empty_check_set_is_the_zero_edge
    """
    stack = setup_stack()
    corridor = _launch_ready_corridor(stack, with_sensor=False, with_load=True,
                                      with_route=True)
    assert corridor["check_count"] == 2
    assert corridor["check_pass_count"] == 2
    data = validate_success(api_client.validate_launch_readiness(
        corridor["id"], TEST_USERS["corridor_manager_headers"],
        {"expected_corridor_version": corridor["version"]}))
    assert data["corridor_status"] == "ACTIVE"


# ─── corner: errors/stale_corridor_version_on_readiness_validate ────────────

def test_stale_corridor_version_on_validate_is_refused(api, any_headers):
    """PRD §2.9: "the server compares the supplied value to the parent row's
    current `version`, and a mismatch ... is rejected with `ERR_STALE_VERSION`
    at HTTP 412."
    PRD §3.1: "A successful pass is a guarded write. The request must carry
    `expected_corridor_version`".

    Design: Corner/errors/stale_corridor_version_on_readiness_validate_returns_precondition_failed
    """
    stack = setup_stack()
    corridor = _launch_ready_corridor(stack, with_sensor=True, with_load=True)
    stale = corridor["version"] - 1
    resp = api_client.validate_launch_readiness(
        corridor["id"], TEST_USERS["corridor_manager_headers"],
        {"expected_corridor_version": stale})
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api_client.get_corridor(corridor["id"], any_headers))
    assert after["corridor_status"] == "READINESS_REVIEW"


# ─── corner: endpoints/launch_readiness_check_creation_is_idempotent ────────

def test_readiness_check_creation_is_idempotent_within_the_epoch(api, any_headers):
    """PRD §2.6: "when a second request arrives carrying the same
    `correlation_key` within the same epoch, the server returns the original row
    with an HTTP 200 rather than recording a second check."
    PRD §2.12: "a `SENSOR_CALIBRATION` or `ROUTE_VALIDATION` check is
    deduplicated on `(corridor_id, correlation_key, epoch_start_at)`".

    Design: Corner/endpoints/launch_readiness_check_creation_is_idempotent_within_the_epoch
    """
    stack = setup_launched_corridor()
    corridor = stack["corridor"]
    payload = create_readiness_check_payload(correlation_key="IDEM-01", suite_latitude=37.0,
                                             suite_longitude=38.0)
    first = validate_success(api_client.create_readiness_check(
        corridor["id"], payload, TEST_USERS["corridor_manager_headers"]), expected_status=201)
    second = validate_success(api_client.create_readiness_check(
        corridor["id"], payload, TEST_USERS["corridor_manager_headers"]), expected_status=200)
    assert second["id"] == first["id"], "the same row is returned rather than a duplicate"
    listing = validate_success(api_client.list_readiness_checks(
        any_headers, params={"corridor_id": corridor["id"]}))
    rows = listing if isinstance(listing, list) else listing.get("data", [])
    matching = [r for r in rows if r.get("correlation_key") == "IDEM-01"]
    assert len(matching) == 1


# ─── corner: validations/create_regulatory_engagement_exceeding_the_hour_budget

def test_engagement_at_the_remaining_balance_is_accepted(api, any_headers):
    """PRD §3.12: "The `autonomous_hours_requested` must not exceed the state
    authority's `remaining_autonomous_hours` for the epoch".
    PRD §2.5: "Each authority declares an `autonomous_hours_allowed` ceiling
    (default 24) and tracks `hours_used`, with `remaining_autonomous_hours`
    reading as the allowance minus the usage."

    With an allowance of 1 and no usage, a request for exactly 1 hour is
    accepted.

    Design: Corner/validations/create_regulatory_engagement_exceeding_the_hour_budget_returns_budget_error
    """
    stack = setup_stack()
    corridor = _corridor(stack)
    authority = make_state_authority(autonomous_hours_allowed=1)
    data = validate_success(api_client.create_regulatory_engagement(
        create_regulatory_engagement_payload(corridor["id"], authority["id"],
                                             autonomous_hours_requested=1,
                                             autonomous_hours_logged=0),
        TEST_USERS["regulatory_liaison_headers"]), expected_status=201)
    assert data["engagement_status"] == "DRAFT"
    refreshed = validate_success(api_client.get_state_authority(authority["id"], any_headers))
    assert refreshed["remaining_autonomous_hours"] == 1


def test_engagement_over_the_remaining_balance_is_refused(api, any_headers):
    """PRD §3.12: "a request that overshoots is refused with
    `ERR_HOURS_BUDGET_EXCEEDED` (409)."

    One hour more than the remaining balance is refused.

    Design: Corner/validations/create_regulatory_engagement_exceeding_the_hour_budget_returns_budget_error
    """
    stack = setup_stack()
    corridor = _corridor(stack)
    authority = make_state_authority(autonomous_hours_allowed=1)
    resp = api_client.create_regulatory_engagement(
        create_regulatory_engagement_payload(corridor["id"], authority["id"],
                                             autonomous_hours_requested=2,
                                             autonomous_hours_logged=0),
        TEST_USERS["regulatory_liaison_headers"])
    validate_error(resp, ApiErrorId.ERR_HOURS_BUDGET_EXCEEDED)


# ─── corner: validations/engagement_outside_the_epoch_window ────────────────

def test_engagement_at_the_epoch_start_is_inside_the_window(api, any_headers):
    """PRD §3.12: "Its `engaged_at` must fall inside the current epoch's
    closed-open window — from `epoch_start_at` inclusive to `epoch_end_at`
    exclusive".
    PRD §3.5: "every window expressed as a range is half-open at the end and
    closed at the start".

    Design: Corner/validations/engagement_outside_the_epoch_window_returns_outside_epoch_window
    """
    stack = setup_stack()
    corridor = _corridor(stack)
    authority = make_state_authority()
    data = validate_success(api_client.create_regulatory_engagement(
        create_regulatory_engagement_payload(corridor["id"], authority["id"],
                                             autonomous_hours_requested=4,
                                             engaged_at="2026-09-01T00:00:00Z"),
        TEST_USERS["regulatory_liaison_headers"]), expected_status=201)
    assert data["engagement_status"] == "DRAFT"


def test_engagement_at_the_epoch_end_is_refused(api, any_headers):
    """PRD §3.12: "an engagement outside that window is refused with
    `ERR_OUTSIDE_EPOCH_WINDOW` (422)."
    PRD §2.5: "whose `engaged_at` falls inside the closed-open epoch window
    `[epoch_start_at, epoch_end_at)`".

    An engagement stamped exactly at epoch_end_at is outside.

    Design: Corner/validations/engagement_outside_the_epoch_window_returns_outside_epoch_window
    """
    stack = setup_stack()
    corridor = _corridor(stack)
    authority = make_state_authority()
    resp = api_client.create_regulatory_engagement(
        create_regulatory_engagement_payload(corridor["id"], authority["id"],
                                             autonomous_hours_requested=4,
                                             engaged_at="2026-10-01T00:00:00Z"),
        TEST_USERS["regulatory_liaison_headers"])
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_EPOCH_WINDOW)


# ─── corner: rbac/incident_reviewer_cannot_close_an_incident ────────────────

def test_incident_reviewer_cannot_close_an_incident(api, any_headers):
    """PRD §2.1: "A request whose role is well-formed but not permitted for the
    operation it targets is refused with `ERR_UNAUTHORIZED` and an HTTP 403."
    PRD §3.5: "Closing is the exit that restores corridor capacity. A
    `ComplianceOfficer` closes a report from `CORRECTIVE_ACTION`".

    Design: Corner/rbac/incident_reviewer_cannot_close_an_incident
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    report = validate_success(api_client.create_incident_report(
        create_incident_report_payload(stack["corridor"]["id"], run["id"],
                                       severity="MODERATE", corrective_action_count=0),
        TEST_USERS["incident_reviewer_headers"]), expected_status=201)
    api_client.investigate_incident(report["id"], TEST_USERS["incident_reviewer_headers"])
    api_client.corrective_action_incident(report["id"], {"corrective_action_count": 1},
                                          TEST_USERS["incident_reviewer_headers"])
    resp = api_client.close_incident(report["id"], TEST_USERS["incident_reviewer_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    data = validate_success(api_client.close_incident(
        report["id"], TEST_USERS["compliance_officer_headers"]))
    assert data["report_status"] == "CLOSED"