"""Composite setup helpers.

Every precondition is built by calling the declared endpoints in order; nothing
here assumes the server starts with any data in it. Setup calls go through
`get_success_data`, which raises a clear message naming the error identifier when
a precondition cannot be established.

The helpers take the client explicitly rather than reaching for a global, so a
test can drive two identities through the same chain.
"""
import itertools
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    CERTIFIER_HEADERS,
    CLIENT_HEADERS,
    DESIGNER_HEADERS,
    INSTALLER_HEADERS,
    MANUFACTURER_HEADERS,
    PM_HEADERS,
    TESTER_HEADERS,
)
from .types import (
    CoordinationState,
    IdentifierScheme,
    Milestone,
    Trade,
)

_identifier_counter = itertools.count(1)


def next_class_1_identifier() -> str:
    """A fresh Class 1 identifier: two letters, two digits, hyphen, rack letter, two digits."""
    n = next(_identifier_counter)
    return f"TR{(n // 100) % 100:02d}-A{n % 100:02d}"


def next_class_2_identifier() -> str:
    """A fresh Class 2 identifier, prefixed with the floor-and-space field."""
    n = next(_identifier_counter)
    return f"{(n // 100) % 100:02d}B-TR01-A{n % 100:02d}"


# ── Logical clock ──────────────────────────────────────────────────────────
def set_clock(client: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical site clock. Requires no authentication headers."""
    return get_success_data(client.set_clock(to_iso8601))


def reset_clock(client: ApiClient) -> Dict[str, Any]:
    return set_clock(client, CLOCK_EPOCH)


# ── Projects ───────────────────────────────────────────────────────────────
def create_project(client: ApiClient, headers=None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_project(f.project_payload(**overrides), headers or PM_HEADERS)
    )


def read_project(client: ApiClient, project_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.get_project(project_id, headers or PM_HEADERS))


def project_version(client: ApiClient, project_id: str) -> int:
    return read_project(client, project_id)["version"]


# ── Telecom rooms ──────────────────────────────────────────────────────────
def create_room(
    client: ApiClient, project_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_telecom_room(
            f.telecom_room_payload(project_id, **overrides), headers or PM_HEADERS
        )
    )


def verify_grounding(
    client: ApiClient, room_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.verify_grounding(
            room_id, f.grounding_payload(**overrides), headers or PM_HEADERS
        )
    )


def create_grounded_room(
    client: ApiClient, project_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    """A room whose bonding has been proved, so terminations are unblocked."""
    room = create_room(client, project_id, headers=headers, **overrides)
    return verify_grounding(client, room["id"], headers=headers)


def read_room(client: ApiClient, room_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.get_telecom_room(room_id, headers or PM_HEADERS))


# ── Racks and elevation placements ─────────────────────────────────────────
def create_rack(
    client: ApiClient, telecom_room_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_rack(
            f.rack_payload(telecom_room_id, **overrides), headers or DESIGNER_HEADERS
        )
    )


def read_rack(client: ApiClient, rack_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.get_rack(rack_id, headers or DESIGNER_HEADERS))


def rack_version(client: ApiClient, rack_id: str) -> int:
    return read_rack(client, rack_id)["version"]


def place_equipment(
    client: ApiClient, rack_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    """Place equipment on the elevation, reading the rack's current revision first."""
    payload = f.rack_unit_assignment_payload(
        rack_id, rack_version(client, rack_id), **overrides
    )
    return get_success_data(
        client.create_rack_unit_assignment(payload, headers or DESIGNER_HEADERS)
    )


def release_equipment(
    client: ApiClient, assignment_id: str, rack_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    payload = f.release_payload(rack_version(client, rack_id), **overrides)
    return get_success_data(
        client.release_rack_unit_assignment(
            assignment_id, payload, headers or DESIGNER_HEADERS
        )
    )


# ── Pathway segments ───────────────────────────────────────────────────────
def create_segment(
    client: ApiClient, project_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_pathway_segment(
            f.pathway_segment_payload(project_id, **overrides),
            headers or DESIGNER_HEADERS,
        )
    )


def read_segment(client: ApiClient, segment_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        client.get_pathway_segment(segment_id, headers or DESIGNER_HEADERS)
    )


def segment_version(client: ApiClient, segment_id: str) -> int:
    return read_segment(client, segment_id)["version"]


def condemn_segment(
    client: ApiClient, segment_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.condemn_pathway_segment(
            segment_id, f.condemn_payload(**overrides), headers or PM_HEADERS
        )
    )


def reparent_segment(
    client: ApiClient, segment_id: str, upstream_segment_id: Optional[str], headers=None
) -> Dict[str, Any]:
    payload = f.reparent_payload(
        upstream_segment_id, segment_version(client, segment_id)
    )
    return get_success_data(
        client.reparent_pathway_segment(segment_id, payload, headers or DESIGNER_HEADERS)
    )


# ── Cable catalogue ────────────────────────────────────────────────────────
def create_cable_type(client: ApiClient, headers=None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_cable_type(
            f.cable_type_payload(**overrides), headers or DESIGNER_HEADERS
        )
    )


# ── Trade coordinations ────────────────────────────────────────────────────
def create_coordination(
    client: ApiClient,
    project_id: str,
    trade: str = Trade.CEILING,
    milestone: str = Milestone.PATHWAY_ROUGH_IN,
    headers=None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.trade_coordination_payload(
        project_id, trade=trade, milestone=milestone, **overrides
    )
    return get_success_data(
        client.create_trade_coordination(payload, headers or PM_HEADERS)
    )


def confirm_coordination(
    client: ApiClient, coordination_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.confirm_trade_coordination(
            coordination_id, f.confirm_payload(**overrides), headers or PM_HEADERS
        )
    )


def release_coordination(
    client: ApiClient, coordination_id: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        client.release_trade_coordination(coordination_id, headers or PM_HEADERS)
    )


def block_coordination(
    client: ApiClient, coordination_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.block_trade_coordination(
            coordination_id, f.block_payload(**overrides), headers or PM_HEADERS
        )
    )


def unblock_coordination(
    client: ApiClient, coordination_id: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        client.unblock_trade_coordination(coordination_id, headers or PM_HEADERS)
    )


def coordination_in_state(
    client: ApiClient,
    project_id: str,
    state: str,
    trade: str = Trade.CEILING,
    milestone: str = Milestone.PATHWAY_ROUGH_IN,
    **overrides: Any,
) -> Dict[str, Any]:
    """Drive a fresh coordination to `state` along the declared lifecycle."""
    row = create_coordination(
        client, project_id, trade=trade, milestone=milestone, **overrides
    )
    if state == CoordinationState.REQUESTED:
        return row
    row = confirm_coordination(client, row["id"])
    if state == CoordinationState.CONFIRMED:
        return row
    if state == CoordinationState.BLOCKED:
        return block_coordination(client, row["id"])
    if state == CoordinationState.RELEASED:
        return release_coordination(client, row["id"])
    raise ValueError(f"unsupported coordination state {state!r}")


# ── Links ──────────────────────────────────────────────────────────────────
def create_link(
    client: ApiClient,
    project_id: str,
    telecom_room_id: str,
    cable_type_id: str,
    headers=None,
    **overrides: Any,
) -> Dict[str, Any]:
    overrides.setdefault("identifier", next_class_1_identifier())
    payload = f.link_payload(project_id, telecom_room_id, cable_type_id, **overrides)
    return get_success_data(client.create_link(payload, headers or DESIGNER_HEADERS))


def read_link(client: ApiClient, link_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.get_link(link_id, headers or DESIGNER_HEADERS))


def route_link(
    client: ApiClient,
    link_id: str,
    pathway_segment_id: str,
    sequence_index: int = 1,
    headers=None,
) -> Dict[str, Any]:
    """Route a link through a segment, reading the segment's current revision first."""
    payload = f.link_route_payload(
        link_id,
        pathway_segment_id,
        segment_version(client, pathway_segment_id),
        sequence_index=sequence_index,
    )
    return get_success_data(client.create_link_route(payload, headers or DESIGNER_HEADERS))


def withdraw_route(
    client: ApiClient, route_id: str, pathway_segment_id: str, headers=None
) -> Dict[str, Any]:
    payload = f.withdraw_payload(segment_version(client, pathway_segment_id))
    return get_success_data(
        client.withdraw_link_route(route_id, payload, headers or DESIGNER_HEADERS)
    )


def pull_link(client: ApiClient, link_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.pull_link(link_id, headers or INSTALLER_HEADERS))


def terminate_link(client: ApiClient, link_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.terminate_link(link_id, headers or INSTALLER_HEADERS))


def label_link(
    client: ApiClient, link_id: str, applied_identifier: Optional[str] = None, headers=None
) -> Dict[str, Any]:
    if applied_identifier is None:
        applied_identifier = read_link(client, link_id)["identifier"]
    return get_success_data(
        client.label_link(
            link_id, f.label_payload(applied_identifier), headers or INSTALLER_HEADERS
        )
    )


def record_link(
    client: ApiClient, link_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.record_link(
            link_id, f.record_payload(**overrides), headers or DESIGNER_HEADERS
        )
    )


def file_test(
    client: ApiClient, link_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_test_result(
            f.test_result_payload(link_id, **overrides), headers or TESTER_HEADERS
        )
    )


def certify_link(client: ApiClient, link_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.certify_link(link_id, headers or CERTIFIER_HEADERS))


# ── Warranty registrations ─────────────────────────────────────────────────
def create_registration(
    client: ApiClient, project_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_warranty_registration(
            f.warranty_registration_payload(project_id, **overrides),
            headers or PM_HEADERS,
        )
    )


def read_registration(
    client: ApiClient, registration_id: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        client.get_warranty_registration(registration_id, headers or PM_HEADERS)
    )


def submit_registration(
    client: ApiClient, registration_id: str, project_id: str, headers=None
) -> Dict[str, Any]:
    """Submit a READY registration, pinning the project's current revision."""
    payload = f.warranty_submit_payload(project_version(client, project_id))
    return get_success_data(
        client.submit_warranty_registration(
            registration_id, payload, headers or PM_HEADERS
        )
    )


def register_decision(
    client: ApiClient, registration_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.decide_warranty_registration(
            registration_id,
            f.warranty_register_decision_payload(**overrides),
            headers or MANUFACTURER_HEADERS,
        )
    )


def reject_decision(
    client: ApiClient, registration_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.decide_warranty_registration(
            registration_id,
            f.warranty_reject_decision_payload(**overrides),
            headers or MANUFACTURER_HEADERS,
        )
    )


def reopen_registration(
    client: ApiClient, registration_id: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        client.reopen_warranty_registration(registration_id, headers or PM_HEADERS)
    )


# ── Moves-adds-changes tickets ─────────────────────────────────────────────
def create_ticket(
    client: ApiClient,
    project_id: str,
    link_id: str,
    telecom_room_id: str,
    headers=None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.mac_ticket_payload(project_id, link_id, telecom_room_id, **overrides)
    return get_success_data(client.create_mac_ticket(payload, headers or CLIENT_HEADERS))


def read_ticket(client: ApiClient, ticket_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.get_mac_ticket(ticket_id, headers or PM_HEADERS))


def schedule_ticket(
    client: ApiClient, ticket_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.schedule_mac_ticket(
            ticket_id, f.schedule_payload(**overrides), headers or PM_HEADERS
        )
    )


def reject_ticket(client: ApiClient, ticket_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.reject_mac_ticket(ticket_id, headers or PM_HEADERS))


def start_ticket(client: ApiClient, ticket_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.start_mac_ticket(ticket_id, headers or INSTALLER_HEADERS))


def rework_ticket(client: ApiClient, ticket_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.rework_mac_ticket(ticket_id, headers or PM_HEADERS))


def complete_ticket(
    client: ApiClient, ticket_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.complete_mac_ticket(
            ticket_id, f.complete_payload(**overrides), headers or INSTALLER_HEADERS
        )
    )


def declare_occupancy(
    client: ApiClient, project_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.declare_occupancy(
            project_id, f.occupancy_payload(**overrides), headers or PM_HEADERS
        )
    )


# ── Scenario tiers ─────────────────────────────────────────────────────────
def setup_base_scenario(
    client: ApiClient,
    coordination_state: str = CoordinationState.RELEASED,
    project: Optional[Dict[str, Any]] = None,
    room: Optional[Dict[str, Any]] = None,
    cable_type: Optional[Dict[str, Any]] = None,
    segment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Project, bonded room, catalogue entry, tray segment and ceiling milestone.

    The ceiling milestone is driven to `coordination_state`; both CONFIRMED and
    RELEASED admit a pull, and RELEASED is additionally what the occupancy gate
    demands, so it is the default.
    """
    proj = create_project(client, **(project or {}))
    tr = create_grounded_room(client, proj["id"], **(room or {}))
    cable = create_cable_type(client, **(cable_type or {}))
    seg = create_segment(client, proj["id"], **(segment or {}))
    coordination = coordination_in_state(client, proj["id"], coordination_state)
    return {
        "project": proj,
        "project_id": proj["id"],
        "room": tr,
        "room_id": tr["id"],
        "cable_type": cable,
        "cable_type_id": cable["id"],
        "segment": seg,
        "segment_id": seg["id"],
        "coordination": coordination,
    }


def setup_designed_link(
    client: ApiClient, scenario: Optional[Dict[str, Any]] = None, **link_overrides: Any
) -> Dict[str, Any]:
    """A designed link sitting in the base scenario, not yet routed."""
    scenario = scenario or setup_base_scenario(client)
    link = create_link(
        client,
        scenario["project_id"],
        scenario["room_id"],
        scenario["cable_type_id"],
        **link_overrides,
    )
    out = dict(scenario)
    out["link"] = link
    out["link_id"] = link["id"]
    return out


def setup_routed_link(
    client: ApiClient, scenario: Optional[Dict[str, Any]] = None, **link_overrides: Any
) -> Dict[str, Any]:
    """A designed link with one occupying routing through the tray segment."""
    out = setup_designed_link(client, scenario, **link_overrides)
    out["route"] = route_link(client, out["link_id"], out["segment_id"])
    out["route_id"] = out["route"]["id"]
    return out


def setup_pulled_link(
    client: ApiClient, scenario: Optional[Dict[str, Any]] = None, **link_overrides: Any
) -> Dict[str, Any]:
    out = setup_routed_link(client, scenario, **link_overrides)
    out["link"] = pull_link(client, out["link_id"])
    return out


def setup_terminated_link(
    client: ApiClient, scenario: Optional[Dict[str, Any]] = None, **link_overrides: Any
) -> Dict[str, Any]:
    out = setup_pulled_link(client, scenario, **link_overrides)
    out["link"] = terminate_link(client, out["link_id"])
    return out


def setup_recorded_link(
    client: ApiClient, scenario: Optional[Dict[str, Any]] = None, **link_overrides: Any
) -> Dict[str, Any]:
    """A terminated link whose administration dimension has reached RECORDED."""
    out = setup_terminated_link(client, scenario, **link_overrides)
    label_link(client, out["link_id"])
    out["link"] = record_link(client, out["link_id"])
    return out


def setup_tested_pass_link(
    client: ApiClient,
    scenario: Optional[Dict[str, Any]] = None,
    record: bool = True,
    test_overrides: Optional[Dict[str, Any]] = None,
    **link_overrides: Any,
) -> Dict[str, Any]:
    """A link carrying a clean strict PASS, recorded unless asked otherwise."""
    if record:
        out = setup_recorded_link(client, scenario, **link_overrides)
    else:
        out = setup_terminated_link(client, scenario, **link_overrides)
    out["test_result"] = file_test(client, out["link_id"], **(test_overrides or {}))
    out["link"] = read_link(client, out["link_id"])
    return out


def setup_certified_link(
    client: ApiClient,
    scenario: Optional[Dict[str, Any]] = None,
    test_overrides: Optional[Dict[str, Any]] = None,
    **link_overrides: Any,
) -> Dict[str, Any]:
    """A fully certified link: recorded, cleanly tested and signed off."""
    out = setup_tested_pass_link(
        client, scenario, record=True, test_overrides=test_overrides, **link_overrides
    )
    out["link"] = certify_link(client, out["link_id"])
    out["project"] = read_project(client, out["project_id"])
    return out


def setup_certified_project(
    client: ApiClient, scenario: Optional[Dict[str, Any]] = None, **link_overrides: Any
) -> Dict[str, Any]:
    """A project whose only link is certified, so the strict figure reads 100.00."""
    return setup_certified_link(client, scenario, **link_overrides)


def setup_occupied_project(
    client: ApiClient, scenario: Optional[Dict[str, Any]] = None, **link_overrides: Any
) -> Dict[str, Any]:
    """A handed-over project: ceiling milestone released and one certified link."""
    out = setup_certified_link(client, scenario, **link_overrides)
    out["project"] = declare_occupancy(client, out["project_id"])
    return out


def setup_rack_scenario(
    client: ApiClient,
    room: Optional[Dict[str, Any]] = None,
    rack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Project, room and one rack, ready for elevation placements."""
    proj = create_project(client)
    tr = create_room(client, proj["id"], **(room or {}))
    rk = create_rack(client, tr["id"], **(rack or {}))
    return {
        "project": proj,
        "project_id": proj["id"],
        "room": tr,
        "room_id": tr["id"],
        "rack": rk,
        "rack_id": rk["id"],
    }


def setup_ticket_ready_project(
    client: ApiClient, scenario: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    """An occupied project, so moves-adds-changes ticketing is unlocked."""
    return setup_occupied_project(client, scenario, **overrides)


def all_links_of(client: ApiClient, project_id: str) -> List[Dict[str, Any]]:
    """Every link of a project, read through the declared list endpoint."""
    response = client.list_links(
        DESIGNER_HEADERS, params={"project_id": project_id, "limit": 100}
    )
    body = response.json()
    return body["data"]
