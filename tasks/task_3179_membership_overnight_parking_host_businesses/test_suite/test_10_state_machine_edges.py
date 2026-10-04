"""The state machines' terminal and cyclic edges, and single-shot rulings."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_basic_scenario,
    setup_confirmed_stay,
    setup_checked_in_stay,
    file_stay,
    confirm_stay,
    read_member,
    read_stay,
    read_capacity_summary,
    host_version,
    conduct_injection,
    set_clock,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
)


def test_a_departed_stay_refuses_both_cancellation_and_a_second_checkout(api):
    """PRD §3.5: "Departure is recorded on the other side of the same rule: once the
    clock has reached the stay's `occupancy_end` and the stay is `CHECKED_IN`, host
    staff record the check-out, which moves the stay to `CHECKED_OUT`, stamps
    `checked_out_at`, and increments the member's `total_stays_completed` by one."
    PRD §2.10: "State suitability is checked next, yielding `ERR_INVALID_STATE`
    (HTTP 409) whenever a target resource is not in a state that permits the
    requested operation."

    Design: Corner/state_machines/stay_request_terminal_state_lockdown_on_checked_out
    """
    set_clock("2026-06-05T00:00:00Z")
    parts = setup_checked_in_stay(arrival_date="2026-06-05", nights=1,
                                  plan_tier="PLUS")
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    set_clock("2026-06-06T11:00:00Z")
    out = validate_success(api.check_out_stay(parts["stay"]["id"], host_headers))
    assert out["request_status"] == "CHECKED_OUT"
    assert out["checked_out_at"] is not None
    stamped = out["checked_out_at"]

    validate_error(
        api.cancel_stay_request(parts["stay"]["id"], make_member_headers(member_id)),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.check_out_stay(parts["stay"]["id"], host_headers),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    assert read_member(member_id)["total_stays_completed"] == 1
    assert read_stay(parts["stay"]["id"], host_id)["checked_out_at"] == stamped


def test_a_rejected_host_admits_no_further_ruling(api):
    """PRD §3.1: "A rejection sets `onboarding_status` to `REJECTED`, which is
    terminal — there is no path back out of it"
    PRD §2.10: "State suitability is checked next, yielding `ERR_INVALID_STATE`
    (HTTP 409) whenever a target resource is not in a state that permits the
    requested operation."

    Design: Corner/state_machines/initial_state_lockdown_of_host_rejection_is_terminal
    """
    host = declare_host()
    rejected = validate_success(
        api.decide_host(
            host["id"],
            {"action": "REJECT", "reason": "no amenities declared",
             "expected_host_version": host_version(host["id"])},
            make_platform_admin_headers(),
        )
    )
    assert rejected["onboarding_status"] == "REJECTED"
    assert rejected["posture"] == "SUSPENDED"
    version_after_rejection = rejected["version"]

    validate_error(
        api.decide_host(
            host["id"],
            {"action": "REINSTATE", "reason": "second look",
             "expected_host_version": version_after_rejection},
            make_platform_admin_headers(),
        ),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.decide_host(
            host["id"],
            {"action": "SUSPEND", "reason": "n/a",
             "expected_host_version": version_after_rejection},
            make_platform_admin_headers(),
        ),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    assert api.get_host(host["id"], make_host_operator_headers(host["id"])).json()[
        "data"
    ]["version"] == version_after_rejection


def test_an_upheld_incident_refuses_a_second_ruling(api):
    """PRD §3.7: "A ruling is admitted only against an incident that is still `OPEN`;
    a disposition attempted on an incident that has already been upheld, dismissed or
    withdrawn is refused with `ERR_INCIDENT_NOT_OPEN` (HTTP 409)."

    Design: Corner/state_machines/incident_disposition_is_idempotent_after_resolution
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1)
    member_id = parts["member"]["id"]

    incident = validate_success(
        api.create_incident(
            {"member_id": member_id, "host_id": parts["host"]["id"],
             "severity": "MAJOR", "narrative": "generator curfew"},
            make_member_headers(member_id),
        ),
        201,
    )
    assert incident["incident_status"] == "OPEN"

    upheld = validate_success(
        api.create_disposition(
            incident["id"],
            {"action": "UPHOLD", "decided_by_display_name": "Panel A",
             "requested_decision": "UPHOLD"},
            make_member_headers(member_id),
        )
    )
    assert upheld["incident_status"] == "UPHELD"
    assert upheld["waived_days_remaining"] == 3, "MINOR and MAJOR grant 3 days"

    validate_error(
        api.create_disposition(
            incident["id"],
            {"action": "DISMISS", "decided_by_display_name": "Panel B",
             "requested_decision": "DISMISS"},
            make_member_headers(member_id),
        ),
        ApiErrorId.ERR_INCIDENT_NOT_OPEN,
        409,
    )
    assert api.get_incident(incident["id"], make_platform_admin_headers()).json()[
        "data"
    ]["incident_status"] == "UPHELD"
    member = read_member(member_id)
    assert member["strike_count"] == 1
    assert member["standing_score"] == 85


def test_a_live_window_can_be_amended_repeatedly_without_leaving_active(api):
    """PRD §3.2: "An amendment is admitted only while the window is `ACTIVE` —
    against any other status it fails with `ERR_WINDOW_NOT_ACTIVE` (HTTP 409), because
    a scheduled window is edited by cancelling it and declaring a fresh one."
    PRD §3.2: "`capacity_override`, `reserved_sites`, `start_date` and `end_date` may
    each be revised, the window's `member_capacity_ceiling` is recomputed"

    Design: Corner/state_machines/availability_window_amend_is_a_cyclic_self_transition
    """
    set_clock("2026-10-05T00:00:00Z")
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)
    declare_sites(host["id"], 1, labels=["C1"])
    approve_host(host["id"])

    window = validate_success(
        api.create_window(
            {"host_id": host["id"], "kind": "EVENT", "label": "Harvest Weekend",
             "start_date": "2026-10-01", "end_date": "2026-10-20",
             "capacity_override": 20, "reserved_sites": 15},
            make_host_operator_headers(host["id"]),
        ),
        201,
    )
    assert window["window_status"] == "ACTIVE"
    assert window["member_capacity_ceiling"] == 5

    amended = validate_success(
        api.amend_window(
            window["id"],
            {"capacity_override": 22, "expected_window_version": window["version"]},
            make_host_operator_headers(host["id"]),
        )
    )
    assert amended["window_status"] == "ACTIVE", "the self-transition kept the state"
    assert amended["member_capacity_ceiling"] == 7


def test_rewinding_the_clock_returns_a_live_window_to_scheduled_and_back(api):
    """PRD §3.2: "Rewinding the clock to before a window's `start_date` returns an
    `ACTIVE` window to `SCHEDULED`, from which it can later activate again — the
    window machine is cyclic rather than one-way."
    PRD §2.13: "becomes `ACTIVE` when the logical clock reaches its `start_date`"

    Design: Corner/state_machines/availability_window_amend_is_a_cyclic_self_transition
    """
    set_clock("2026-10-05T00:00:00Z")
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)
    declare_sites(host["id"], 1, labels=["C1"])
    approve_host(host["id"])
    window = validate_success(
        api.create_window(
            {"host_id": host["id"], "kind": "EVENT", "label": "Harvest Weekend",
             "start_date": "2026-10-01", "end_date": "2026-10-20",
             "capacity_override": 20, "reserved_sites": 15},
            make_host_operator_headers(host["id"]),
        ),
        201,
    )
    headers = make_host_operator_headers(host["id"])

    set_clock("2026-09-20T00:00:00Z")
    assert api.get_window(window["id"], headers).json()["data"][
        "window_status"
    ] == "SCHEDULED", "the cyclic revert edge"

    set_clock("2026-10-06T00:00:00Z")
    assert api.get_window(window["id"], headers).json()["data"][
        "window_status"
    ] == "ACTIVE", "the window can be re-entered after each revert"


def test_confirmation_applies_all_of_its_declared_side_effects(api):
    """PRD §3.4: "A confirmed stay moves to `request_status` `CONFIRMED`, records the
    assigned site in `confirmed_site_id`, computes its `ancillary_charge_cents`, and
    leaves the member's `total_stays_completed` untouched until check-out."
    PRD §3.4: "The host's `committed_sites` and `free_sites` are recomputed, its
    posture follows from the derivation in §2.4, and the host's `version` increments."

    Design: Corner/state_machines/stay_request_side_effects_of_confirmation_are_all_applied
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]
    host_headers = make_host_operator_headers(host_id)

    site_x1 = validate_success(
        api.create_parking_site(
            host_id,
            {"site_label": "X1", "site_class": "BACK_IN",
             "max_vehicle_length_feet": 40, "has_electric": True,
             "electric_service_code": "ELECTRIC_30A"},
            host_headers,
        ),
        201,
    )
    stay = file_stay(host_id, parts["member"]["id"], parts["vehicle"]["id"],
                     arrival_date="2026-06-20", nights=2, party_size=3,
                     electric_request_code="ELECTRIC_30A")
    assert stay["ancillary_charge_cents"] == 0, "charges are computed at confirmation"

    version_before = host_version(host_id)
    confirmed = confirm_stay(host_id, stay["id"], site_id=site_x1["id"])

    # 700 * 2 = 1400 electric; the member's PLUS allotment of 2 covers both
    # guests, so no guest component; PLUS 10% of 1400 -> 140; charge 1260.
    assert confirmed["ancillary_charge_cents"] == 1260
    assert confirmed["confirmed_site_id"] == site_x1["id"]
    assert confirmed["request_status"] == "CONFIRMED"
    assert host_version(host_id) > version_before, (
        "the confirmation bumped the parent the endpoint declared"
    )