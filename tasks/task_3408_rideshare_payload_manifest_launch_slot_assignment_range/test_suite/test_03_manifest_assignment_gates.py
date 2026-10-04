"""Assignment creation gates: existence order, state gates, compatibility,
capacity ordering, and the mission-version OCC guard."""
from test_helpers import (
    ApiErrorId,
    assignment_payload,
    confirm_assignment,
    create_assignment,
    create_contract,
    create_customer,
    create_granted_customer_license,
    create_mission,
    create_port,
    create_signed_contract,
    get_mission,
    list_payloads,
    lock_manifest,
    mission_version,
    payload_entry,
    review_assignment,
    set_clock,
    setup_provisional_assignments,
    validate_error,
    validate_paginated,
    validate_success,
    verify_assignment,
    api_client,
)
from test_helpers.test_users import TEST_USERS

MOPS = TEST_USERS["mission_ops_headers"]
UNKNOWN_MISSION = "00000000-0000-4000-8000-000000000011"
UNKNOWN_PAYLOAD = "00000000-0000-4000-8000-000000000012"
UNKNOWN_PORT = "00000000-0000-4000-8000-000000000013"


def test_assignment_existence_checks_follow_declared_input_order(api):
    """PRD §2.7: "Existence checks then continue across request-body references
    in their declared input order."
    PRD §3.3: "A `MissionOps` operator creates an assignment by naming the
    `mission_id`, the `payload_id`, the `dispenser_port_id` of a port on that
    mission's ring, and the optimistic-concurrency guard
    `expected_mission_version` (§2.8)."

    Design: Corner/validations/assignment_existence_checks_follow_declared_input_order
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    create_port(mission["id"])
    contract, payloads = create_signed_contract(customer["id"], [payload_entry()])
    v = mission_version(mission["id"])

    r1 = api_client.create_assignment(
        assignment_payload(UNKNOWN_MISSION, UNKNOWN_PAYLOAD, UNKNOWN_PORT, v), MOPS
    )
    validate_error(r1, ApiErrorId.ERR_MISSION_NOT_FOUND)

    r2 = api_client.create_assignment(
        assignment_payload(mission["id"], UNKNOWN_PAYLOAD, UNKNOWN_PORT, v), MOPS
    )
    validate_error(r2, ApiErrorId.ERR_PAYLOAD_NOT_FOUND)

    r3 = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[0]["id"], UNKNOWN_PORT, v), MOPS
    )
    validate_error(r3, ApiErrorId.ERR_DISPENSER_PORT_NOT_FOUND)

    rows, _ = validate_paginated(api_client.list_assignments(MOPS))
    assert rows == [], "failed creates must persist nothing"


def test_contract_window_exactly_covering_mission_window_is_compatible(api):
    """PRD §3.3: "The contract's launch-date window must cover the mission's
    window — the contract's `window_open_utc` on or before the mission's
    `window_open_utc`, and the contract's `window_close_utc` on or after the
    mission's `window_close_utc` — else `ERR_WINDOW_INCOMPATIBLE` (HTTP 422)."

    Design: Corner/validations/contract_window_exactly_covering_mission_window_is_compatible
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    port = create_port(mission["id"])
    contract, payloads = create_signed_contract(
        customer["id"],
        [payload_entry()],
        window_open_utc="2026-10-10T00:00:00Z",
        window_close_utc="2026-10-20T00:00:00Z",
    )
    resp = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[0]["id"], port["id"], mission_version(mission["id"])),
        MOPS,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PROVISIONAL"


def test_assign_after_manifest_lock_rejected(api):
    """PRD §3.3: "The mission must still be `MANIFEST_OPEN`, else
    `ERR_MANIFEST_LOCKED` (HTTP 409)"

    Design: Corner/errors/assign_after_manifest_lock_rejected
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    port_a = create_port(mission["id"])
    port_b = create_port(
        mission["id"], port_code="DSP-B", stack_position=3, max_mass_kg=100,
        supported_interface_classes=["CUBESAT"],
    )
    contract, payloads = create_signed_contract(
        customer["id"],
        [
            payload_entry(payload_name="PL1", mass_kg=100),
            payload_entry(payload_name="PL2", mass_kg=50, volume_m3=1.0, interface_class="CUBESAT"),
        ],
    )
    create_granted_customer_license(customer["id"])
    a1 = create_assignment(mission["id"], payloads[0]["id"], port_a["id"])
    verify_assignment(a1["id"])
    review_assignment(a1["id"])
    confirm_assignment(a1["id"])
    lock_manifest(mission["id"])

    resp = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[1]["id"], port_b["id"], mission_version(mission["id"])),
        MOPS,
    )
    validate_error(resp, ApiErrorId.ERR_MANIFEST_LOCKED)
    rows, meta = validate_paginated(
        api_client.list_assignments(MOPS, params={"mission_id": mission["id"]})
    )
    assert len(rows) == 1 and meta["total_count"] == 1


def test_assign_same_payload_twice_rejected(api):
    """PRD §3.3: "the payload must be `REGISTERED`, else
    `ERR_PAYLOAD_ALREADY_MANIFESTED` (409)"
    PRD §2.6: "Every request passes through the same validation pipeline, and the
    stages run in a fixed order: a failure at an earlier stage masks every later
    check, so the response always carries the first applicable rejection."

    Design: Corner/errors/assign_same_payload_twice_rejected
    """
    ctx = setup_provisional_assignments()
    mission = ctx["mission"]
    pl1 = ctx["payloads"][0]
    port_b = create_port(
        mission["id"], port_code="DSP-B", stack_position=3, max_mass_kg=100,
        supported_interface_classes=["CUBESAT"],
    )
    resp = api_client.create_assignment(
        assignment_payload(mission["id"], pl1["id"], port_b["id"], mission_version(mission["id"])),
        MOPS,
    )
    err = validate_error(resp, ApiErrorId.ERR_PAYLOAD_ALREADY_MANIFESTED)
    assert err["error_id"] != "ERR_INTERFACE_INCOMPATIBLE", (
        "state priority precedes the interface constraint"
    )
    rows, _ = validate_paginated(
        api_client.list_assignments(MOPS, params={"mission_id": mission["id"]})
    )
    assert len(rows) == 1


def test_assign_against_draft_contract_rejected(api):
    """PRD §3.3: "the payload's contract must stand in `SIGNED` or `MANIFESTED`,
    else `ERR_CONTRACT_NOT_SIGNED` (409)."

    Design: Corner/errors/assign_against_draft_contract_rejected
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    port = create_port(mission["id"])
    contract = create_contract(customer["id"], [payload_entry()])
    payloads = list_payloads(contract["id"])
    resp = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[0]["id"], port["id"], mission_version(mission["id"])),
        MOPS,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_SIGNED)
    rows, _ = validate_paginated(api_client.list_assignments(MOPS))
    assert rows == []


def test_assign_to_non_target_mission_rejected(api):
    """PRD §3.3: "And if the contract's `target_mission_id` is set, it must equal
    the assignment's mission, else `ERR_MISSION_MISMATCH`."

    Design: Corner/errors/assign_to_non_target_mission_rejected
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    create_port(mission["id"])
    m2 = create_mission(mission_name="Transporter-X7")
    port_a2 = create_port(m2["id"])
    contract, payloads = create_signed_contract(
        customer["id"], [payload_entry()], target_mission_id=mission["id"]
    )
    resp = api_client.create_assignment(
        assignment_payload(m2["id"], payloads[0]["id"], port_a2["id"], mission_version(m2["id"])),
        MOPS,
    )
    validate_error(resp, ApiErrorId.ERR_MISSION_MISMATCH)
    rows, _ = validate_paginated(api_client.list_assignments(MOPS))
    assert rows == []


def test_volume_overflow_rejected_after_mass_passes(api):
    """PRD §3.3: "If adding the payload would push the mission's
    `committed_mass_kg` strictly above `mass_capacity_kg`, the create is rejected
    with `ERR_MASS_CAPACITY_EXCEEDED`; only after mass passes does the system
    check volume, rejecting with `ERR_VOLUME_CAPACITY_EXCEEDED` when
    `committed_volume_m3` would exceed `volume_capacity_m3`."

    Design: Corner/validations/volume_overflow_rejected_after_mass_passes
    """
    set_clock()
    customer = create_customer()
    mission = create_mission(mission_name="Transporter-V9", volume_capacity_m3=4.0)
    port_a = create_port(mission["id"])
    port_b = create_port(
        mission["id"], port_code="DSP-B", stack_position=3, max_mass_kg=100,
        supported_interface_classes=["CUBESAT"],
    )
    contract, payloads = create_signed_contract(
        customer["id"],
        [
            payload_entry(payload_name="PLV1", mass_kg=100, volume_m3=3.5),
            payload_entry(payload_name="PLV2", mass_kg=50, volume_m3=1.0,
                          interface_class="CUBESAT"),
        ],
    )
    create_assignment(mission["id"], payloads[0]["id"], port_a["id"])

    resp = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[1]["id"], port_b["id"], mission_version(mission["id"])),
        MOPS,
    )
    err = validate_error(resp, ApiErrorId.ERR_VOLUME_CAPACITY_EXCEEDED)
    assert err["error_id"] != "ERR_MASS_CAPACITY_EXCEEDED", (
        "150 kg <= 300 kg passes the mass leg; volume fails after it"
    )
    mission_after = get_mission(mission["id"])
    assert mission_after["committed_volume_m3"] == 3.5, "rejected create must not change volume"


def test_assignment_constraint_violations_orbit_interface_occupancy(api):
    """PRD §3.3: "The payload's `required_orbit` must equal the mission's
    `target_orbit`, else `ERR_ORBIT_MISMATCH`. The payload's `interface_class`
    must appear in the port's `supported_interface_classes`, else
    `ERR_INTERFACE_INCOMPATIBLE`. The port must carry no other live assignment —
    one whose status is not `REMOVED` — else `ERR_PORT_OCCUPIED` (HTTP 409)."
    PRD §2.5: "An entity's `version` starts at 1 when the entity is created and
    increments by exactly 1 only where a state-machine transition or an
    endpoint's documented side effects say so."

    Design: Corner/errors/assignment_constraint_violations_orbit_interface_occupancy
    """
    set_clock()
    customer = create_customer()
    mission = create_mission(mission_name="Transporter-L1", target_orbit="LEO")
    port_a = create_port(mission["id"])
    create_port(mission["id"], port_code="DSP-B", stack_position=3, max_mass_kg=100,
                supported_interface_classes=["CUBESAT"])
    contract, payloads = create_signed_contract(
        customer["id"],
        [
            payload_entry(payload_name="PL_SSO", mass_kg=50, volume_m3=1.0, required_orbit="SSO"),
            payload_entry(payload_name="PL_LEO_CB", mass_kg=40, volume_m3=0.5,
                          interface_class="CUBESAT", required_orbit="LEO"),
            payload_entry(payload_name="PL_LEO_R15", mass_kg=50, volume_m3=1.0, required_orbit="LEO"),
            payload_entry(payload_name="PL_LEO_R24", mass_kg=45, volume_m3=0.9,
                          interface_class="RING_24", required_orbit="LEO"),
        ],
    )
    pl_sso, pl_leo_cb, pl_leo_r15, pl_leo_r24 = [p["id"] for p in payloads]
    v0 = mission_version(mission["id"])

    r_orbit = api_client.create_assignment(
        assignment_payload(mission["id"], pl_sso, port_a["id"], v0), MOPS
    )
    validate_error(r_orbit, ApiErrorId.ERR_ORBIT_MISMATCH)

    r_iface = api_client.create_assignment(
        assignment_payload(mission["id"], pl_leo_cb, port_a["id"], v0), MOPS
    )
    validate_error(r_iface, ApiErrorId.ERR_INTERFACE_INCOMPATIBLE)

    assert mission_version(mission["id"]) == v0, (
        "rejected writes never bump the mission version"
    )

    r_ok = api_client.create_assignment(
        assignment_payload(mission["id"], pl_leo_r15, port_a["id"], v0), MOPS
    )
    validate_success(r_ok, 201)

    r_port = api_client.create_assignment(
        assignment_payload(mission["id"], pl_leo_r24, port_a["id"], mission_version(mission["id"])),
        MOPS,
    )
    validate_error(r_port, ApiErrorId.ERR_PORT_OCCUPIED)

    rows, meta = validate_paginated(
        api_client.list_assignments(MOPS, params={"mission_id": mission["id"]})
    )
    assert len(rows) == 1 and meta["total_count"] == 1


def test_occ_stale_mission_version_rejected_on_assignment_create(api):
    """PRD §2.8: "Creating a manifest assignment requires the non-optional field
    `expected_mission_version`, carrying the client's last observed `version` of
    the target mission. If the mission's version has advanced since that
    observation — because another assignment was created or removed, the manifest
    was locked, or a delay landed — the create is rejected with
    `ERR_STALE_MISSION_VERSION` (HTTP 412), protecting the client from acting on
    a stale view of manifest capacity."

    Design: Corner/complexity_layers/occ_stale_mission_version_rejected_on_assignment_create
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    port_a = create_port(mission["id"])
    port_b = create_port(mission["id"], port_code="DSP-B", stack_position=3, max_mass_kg=100,
                         supported_interface_classes=["CUBESAT"])
    contract, payloads = create_signed_contract(
        customer["id"],
        [
            payload_entry(payload_name="PL1", mass_kg=100),
            payload_entry(payload_name="PL2", mass_kg=50, volume_m3=1.0, interface_class="CUBESAT"),
        ],
    )
    v1 = mission_version(mission["id"])

    r1 = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[0]["id"], port_a["id"], v1), MOPS
    )
    validate_success(r1, 201)

    r_stale = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[1]["id"], port_b["id"], v1), MOPS
    )
    validate_error(r_stale, ApiErrorId.ERR_STALE_MISSION_VERSION)

    v2 = mission_version(mission["id"])
    assert v2 == v1 + 1, "the successful create bumped the mission version exactly once"

    r2 = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[1]["id"], port_b["id"], v2), MOPS
    )
    validate_success(r2, 201)
    mission = get_mission(mission["id"])
    assert mission["committed_mass_kg"] == 150
    rows, _ = validate_paginated(
        api_client.list_assignments(MOPS, params={"mission_id": mission["id"]})
    )
    assert len(rows) == 2
