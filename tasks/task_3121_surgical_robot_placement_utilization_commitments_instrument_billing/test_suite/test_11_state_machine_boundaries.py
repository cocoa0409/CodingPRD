"""State-machine boundaries: terminal states, invalid transitions, and the side effect a
commissioning transition produces."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_training_record,
    get_success_data,
    setup_account_with_review,
    setup_agreement,
    setup_closed_account,
    setup_commissioned_system,
    setup_terminated_agreement,
    validate_error,
    validate_success,
)


def test_a_closed_account_is_terminal_and_refuses_reactivation(api):
    """PRD §2.5: "It is revived by the dormant-account reactivation, which requires
    `account_status == DORMANT` (`ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE`, checked first)".

    Design: Corner/state_machines/account_starts_in_prospect_and_close_locks_the_terminal_state
    """
    ctx = setup_closed_account()
    assert ctx.account["account_status"] == "CLOSED"

    res = api_client.reactivate_account(
        ctx.account["id"], {"expected_account_version": ctx.account["version"]},
        TEST_USERS["regional_sales_director_headers"])

    validate_error(res, "ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE", expected_status=409)
    assert get_success_data(api_client.get_account(
        ctx.account["id"], TEST_USERS["platform_admin_headers"]))["account_status"] == "CLOSED"


def test_account_activation_without_a_training_record_reports_uninitialized(api):
    """PRD §2.5: "`PROSPECT` to `READINESS` is driven by the account readiness activation,
    which requires the `account_status` to still be `PROSPECT`
    (`ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE`, HTTP 409, checked before the rest), at least one
    readiness review on file (`ERR_READINESS_REVIEW_REQUIRED`, HTTP 409), and at least one
    surgeon training record on file (`ERR_TRAINING_PATH_UNINITIALIZED`, HTTP 409)."

    Design: Corner/state_machines/account_activation_without_training_path_returns_uninitialized
    """
    ctx = setup_account_with_review(verdict=None, training_record=False)
    assert ctx.account["account_status"] == "PROSPECT"

    res = api_client.activate_account_readiness(
        ctx.review["id"], {"expected_account_version": ctx.account["version"]},
        TEST_USERS["clinical_operations_lead_headers"])

    validate_error(res, "ERR_TRAINING_PATH_UNINITIALIZED", expected_status=409)


def test_adding_the_training_record_lets_the_account_reach_readiness(api):
    """PRD §3.1.1: "Before any commercial paperwork can move, the account needs at least one
    site-readiness review and at least one surgeon training record on file".

    Design: Corner/state_machines/account_activation_without_training_path_returns_uninitialized
    """
    ctx = setup_account_with_review(verdict=None, training_record=False)
    api_client.activate_account_readiness(
        ctx.review["id"], {"expected_account_version": ctx.account["version"]},
        TEST_USERS["clinical_operations_lead_headers"])
    assert get_success_data(api_client.get_account(
        ctx.account["id"], TEST_USERS["platform_admin_headers"]))["account_status"] == "PROSPECT"

    create_training_record(ctx.account["id"])
    account = get_success_data(api_client.get_account(
        ctx.account["id"], TEST_USERS["platform_admin_headers"]))
    activated = validate_success(api_client.activate_account_readiness(
        ctx.review["id"], {"expected_account_version": account["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)

    assert activated["account_status"] == "READINESS"


def test_commissioning_opens_an_underutilized_cycle_for_the_system(api):
    """PRD §3.2: "A `UtilizationCycle` is opened for the system's current commitment
    interval: if none exists for that interval it is created, and if one does exist it is
    reused as the open cycle rather than duplicated. Its identifier is stamped onto the
    system as `current_utilization_cycle_id`, and the band is initialized to
    `UNDERUTILIZED`, which is where an empty cycle naturally falls."

    Design: Corner/state_machines/commissioning_synthesizes_an_underutilized_cycle_as_a_side_effect
    """
    ctx = setup_commissioned_system()

    assert ctx.system["service_status"] == "IN_SERVICE"
    assert ctx.system["current_utilization_cycle_id"] is not None
    cycle = get_success_data(api_client.get_current_utilization_cycle(
        ctx.system["id"], TEST_USERS["clinical_operations_lead_headers"]))
    assert cycle["completed_case_count"] == 0
    assert cycle["scheduled_case_count"] == 0
    assert cycle["utilization_band"] == "UNDERUTILIZED"


def test_commissioning_from_the_uninstalled_state_is_refused(api):
    """PRD §3.2: "A `ClinicalOperationsLead` commissions an `INSTALLED` system, which
    requires at least one `CREDENTIALED` surgeon training record on the account
    (`ERR_NO_CREDENTIALED_SURGEON`, HTTP 409)".

    Design: Corner/state_machines/commissioning_from_the_uninstalled_state_returns_status_invalid
    """
    ctx = setup_agreement(accepted=True)
    assert ctx.system["service_status"] == "NOT_INSTALLED"

    res = api_client.commission_robot_system(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["clinical_operations_lead_headers"])

    validate_error(res, "ERR_SYSTEM_STATUS_INVALID", expected_status=409)
    unchanged = get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["clinical_operations_lead_headers"]))
    assert unchanged["service_status"] == "NOT_INSTALLED"
    assert unchanged["current_utilization_cycle_id"] is None


def test_revoked_evidence_cannot_be_revoked_again(api):
    """PRD §3.5: "Note that `EXPIRED` is renewable while `REVOKED` is not, the latter being
    the only status the renew path refuses. A `ComplianceOfficer` may revoke evidence from
    `VALID` or `EXPIRING_SOON`, moving it to `REVOKED`, and revoking is refused from
    `REVOKED` under the same not-renewable code."

    Design: Corner/state_machines/evidence_state_machine_starts_valid_and_expiry_is_terminal
    """
    ctx = setup_account_with_review(verdict="PASSED")
    record = create_training_record(ctx.account["id"])
    evidence = get_success_data(api_client.create_credentialing_evidence(
        record["id"],
        {"evidence_type": "CREDENTIAL_LETTER", "issued_utc": "2026-08-01T00:00:00Z",
         "expires_utc": "2027-08-01T00:00:00Z"},
        ctx.account_headers), 201)
    assert evidence["evidence_status"] == "VALID"
    revoked = get_success_data(api_client.revoke_credentialing_evidence(
        evidence["id"], {"expected_evidence_version": evidence["version"]},
        TEST_USERS["compliance_officer_headers"]), 200)
    assert revoked["evidence_status"] == "REVOKED"

    res = api_client.revoke_credentialing_evidence(
        evidence["id"], {"expected_evidence_version": revoked["version"]},
        TEST_USERS["compliance_officer_headers"])

    validate_error(res, "ERR_EVIDENCE_NOT_RENEWABLE", expected_status=409)


def test_a_terminated_agreement_cannot_be_terminated_again(api):
    """PRD §3.1.3: "A `PlatformAdmin` may terminate an agreement in `ACTIVE` or `SUSPENDED`;
    anything else is `ERR_AGREEMENT_NOT_TERMINABLE` (HTTP 409, checked first)."

    Design: Corner/state_machines/agreement_already_terminated_cannot_be_terminated_again
    """
    ctx = setup_terminated_agreement()
    assert ctx.agreement["agreement_status"] == "TERMINATED"

    res = api_client.terminate_agreement(
        ctx.agreement["id"], {"expected_agreement_version": ctx.agreement["version"]},
        TEST_USERS["platform_admin_headers"])

    validate_error(res, "ERR_AGREEMENT_NOT_TERMINABLE", expected_status=409)
    assert get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["platform_admin_headers"]))["service_status"] == "DECOMMISSIONED"