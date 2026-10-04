"""Multi-hop cascades: agreement termination unwinding coverage and incidents, and a
service action suspending a non-compliant agreement through the account's posture."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_incident_payload,
    get_account,
    get_agreement,
    get_success_data,
    month_close,
    setup_commissioned_system,
    setup_usage_based_system,
    validate_success,
)


def test_terminating_an_agreement_decommissions_its_system(api):
    """PRD §3.1.3: "Then every robot system on the agreement is moved to `DECOMMISSIONED`."

    Design: Difficulty/transitive_cascade/agreement_termination_three_hop_contract_incident_cascade
    """
    ctx = setup_commissioned_system()
    system_id = ctx.system["id"]

    validate_success(api_client.terminate_agreement(
        ctx.agreement["id"], {"expected_agreement_version": ctx.agreement["version"]},
        TEST_USERS["platform_admin_headers"]), 200)

    assert get_success_data(api_client.get_robot_system(
        system_id, TEST_USERS["platform_admin_headers"]))["service_status"] == "DECOMMISSIONED"


def test_system_decommission_terminates_its_active_coverage_contract(api):
    """PRD §3.1.3: "Then, because each of those systems has left service, every `ACTIVE`
    service contract on them is terminated — and once a contract is gone, its response-time
    commitment is no longer evaluated for that system at all."

    Design: Difficulty/transitive_cascade/agreement_termination_three_hop_contract_incident_cascade
    """
    ctx = setup_commissioned_system()
    contract_id = ctx.contract["id"]
    assert ctx.contract["contract_status"] == "ACTIVE"

    validate_success(api_client.terminate_agreement(
        ctx.agreement["id"], {"expected_agreement_version": ctx.agreement["version"]},
        TEST_USERS["platform_admin_headers"]), 200)

    assert get_success_data(api_client.get_service_contract(
        contract_id, TEST_USERS["service_engineer_headers"]))["contract_status"] == "TERMINATED"


def test_contract_termination_resolves_the_systems_open_incident(api):
    """PRD §3.1.3: "Then, because those contracts have ended, every incident on those
    systems that is `OPEN` or `ACKNOWLEDGED` is resolved."

    Design: Difficulty/transitive_cascade/agreement_termination_three_hop_contract_incident_cascade
    """
    ctx = setup_commissioned_system()
    incident = get_success_data(api_client.create_incident(
        create_incident_payload(ctx.system["id"],
                                incident_started_at="2026-09-05T08:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)
    assert incident["request_status"] == "OPEN"

    validate_success(api_client.terminate_agreement(
        ctx.agreement["id"], {"expected_agreement_version": ctx.agreement["version"]},
        TEST_USERS["platform_admin_headers"]), 200)

    resolved = get_success_data(api_client.get_incident(
        incident["id"], TEST_USERS["service_engineer_headers"]))
    assert resolved["request_status"] == "RESOLVED"
    assert resolved["resolved_at_utc"] is not None, (
        "the resolution instant is stamped on the incident"
    )


def test_service_action_blocks_the_account_posture(api):
    """PRD §3.2: "Because the account now has a system in service-action-required, its
    posture recomputes to `EXPANSION_BLOCKED`."

    Design: Difficulty/transitive_cascade/system_service_action_two_hop_agreement_suspension_cascade
    """
    ctx = setup_usage_based_system(minimum_procedures_per_cycle=4,
                                   placement_fee_cents=1500000,
                                   usage_rate_basis_points=400)
    month_close("2026-10-01T00:00:00Z")
    account = get_account(ctx.account["id"])
    before = account["account_posture"]

    system = get_success_data(api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["service_engineer_headers"]), 200)

    assert system["service_status"] == "SERVICE_ACTION_REQUIRED"
    after = get_account(ctx.account["id"])["account_posture"]
    assert after == "EXPANSION_BLOCKED", (
        f"the posture moves from {before} to EXPANSION_BLOCKED once a system leaves service"
    )


def test_service_action_suspends_the_non_compliant_agreement(api):
    """PRD §3.2: "Because the posture is now blocked, every `ACTIVE` placement agreement on
    that system whose `compliance_status` is `NON_COMPLIANT` is suspended."

    Design: Difficulty/transitive_cascade/system_service_action_two_hop_agreement_suspension_cascade
    """
    ctx = setup_usage_based_system(minimum_procedures_per_cycle=4,
                                   placement_fee_cents=1500000,
                                   usage_rate_basis_points=400,
                                   config_overrides={"base_placement_fee_cents": 30000000,
                                                     "model_code": "DA_V1",
                                                     "integration_tier": 1,
                                                     "max_instrument_lives": 10})
    month_close("2026-10-01T00:00:00Z")
    before = get_agreement(ctx.agreement["id"])
    assert before["compliance_status"] == "NON_COMPLIANT", (
        "zero delivered procedures against a commitment of 4, on an agreement whose "
        "placement fee pushes the shortfall tier past 25, is NON_COMPLIANT"
    )

    api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["service_engineer_headers"])

    after = get_agreement(ctx.agreement["id"])
    assert after["agreement_status"] == "SUSPENDED", (
        "the recomputed posture is what suspends the non-compliant agreement"
    )