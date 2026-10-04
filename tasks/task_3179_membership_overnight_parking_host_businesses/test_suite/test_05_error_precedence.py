"""Which guard reports when a request violates more than one rule."""
import pytest

from test_helpers import validate_error, ApiErrorId
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    suspend_host,
    setup_basic_scenario,
    setup_declined_stay,
    file_stay,
    try_file_stay,
    read_stay,
    host_version,
    set_clock,
    make_host_operator_headers,
    make_platform_admin_headers,
)


def test_a_host_that_was_never_approved_refuses_a_stay_request(api):
    """PRD §3.4: "The host must be accepting stays at all: a host whose
    `onboarding_status` is not `APPROVED`, or whose posture is `SUSPENDED`, refuses
    the request with `ERR_HOST_NOT_ACCEPTING_STAYS` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/host_posture_pair_beats_member_standing_pair
    """
    set_clock("2026-06-01T00:00:00Z")
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)
    declare_sites(host["id"], 2, labels=["P1", "P2"])
    # Left at PENDING_REVIEW on purpose — never approved.
    parts = setup_basic_scenario(site_count=1)
    member, vehicle = parts["member"], parts["vehicle"]

    resp = try_file_stay(
        host["id"], member["id"], vehicle["id"],
        arrival_date="2026-07-01", nights=2,
    )
    validate_error(resp, ApiErrorId.ERR_HOST_NOT_ACCEPTING_STAYS, 409)


def test_a_suspended_host_refuses_a_stay_request_before_anything_else(api):
    """PRD §3.4: "The host must be accepting stays at all: a host whose
    `onboarding_status` is not `APPROVED`, or whose posture is `SUSPENDED`, refuses
    the request with `ERR_HOST_NOT_ACCEPTING_STAYS` (HTTP 409)."
    PRD §2.10: "Whether a host is accepting stays at all — its `onboarding_status`
    must be `APPROVED` and its `posture` must not be `SUSPENDED` — is checked before
    the details of the stay are inspected, and a failure yields
    `ERR_HOST_NOT_ACCEPTING_STAYS` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/host_posture_pair_beats_member_standing_pair
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]
    host = suspend_host(host_id)
    assert host["posture"] == "SUSPENDED"

    resp = try_file_stay(
        host_id, parts["member"]["id"], parts["vehicle"]["id"],
        arrival_date="2026-07-01", nights=2,
    )
    validate_error(resp, ApiErrorId.ERR_HOST_NOT_ACCEPTING_STAYS, 409)


def test_a_request_filed_inside_the_lead_time_guard_is_refused(api):
    """PRD §3.4: "The logical clock must be at least 48 hours before the request's
    `occupancy_start`, unless the host has enabled same-day availability and the
    request carries `same_day_hold` as true, in which case the guard is waived
    entirely; a request filed inside the guard without that exemption is refused with
    `ERR_REQUEST_LEAD_TIME` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/state_pair_beats_temporal_pair
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1)
    # arrival 2026-06-02 with the default 14:00 start hour is under 48 hours away.
    resp = try_file_stay(
        parts["host"]["id"], parts["member"]["id"], parts["vehicle"]["id"],
        arrival_date="2026-06-02", nights=2,
    )
    validate_error(resp, ApiErrorId.ERR_REQUEST_LEAD_TIME, 422)


def test_a_second_decision_on_a_declined_request_fails_the_state_gate(api):
    """PRD §2.10: "where a single operation is guarded by several of these, the
    earlier check in this ordering is the one whose error the caller receives."
    PRD §2.10: "State suitability is checked next, yielding `ERR_INVALID_STATE`
    (HTTP 409) whenever a target resource is not in a state that permits the
    requested operation."

    Design: Difficulty/priority_pair_validation_conflict/state_pair_beats_temporal_pair
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_declined_stay(decline_arrival="2026-06-02")
    host_id = parts["host"]["id"]
    assert parts["stay"]["request_status"] == "DECLINED"
    assert parts["stay"]["request_depth"] == 1

    resp = api.decide_stay_request(
        parts["stay"]["id"],
        {"decision": "CONFIRM", "site_id": None,
         "expected_host_version": host_version(host_id)},
        make_host_operator_headers(host_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    after = read_stay(parts["stay"]["id"], host_id)
    assert after["request_status"] == "DECLINED"
    assert after["request_depth"] == 1