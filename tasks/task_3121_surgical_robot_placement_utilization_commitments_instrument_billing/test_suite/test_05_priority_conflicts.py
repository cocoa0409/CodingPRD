"""Priority ordering between a state check and a temporal check on the accept path."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_account,
    create_configuration,
    create_review,
    create_training_record,
    draft_agreement,
    drive_account_to_readiness,
    get_success_data,
    set_clock,
    submit_agreement,
    validate_error,
)


def _terminated_and_expired_agreement():
    """An agreement submitted at 2026-09-01, accepted, terminated, with the clock then
    moved past the acceptance window stamped at submit."""
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(account_name="Quarry Lake Surgical", idn_group_code="IDN-QUARRY",
                             region_code="MIDWEST", placement_cap=4,
                             maximum_procedure_commitment=25)
    config = create_configuration(model_code="DA_V1", base_placement_fee_cents=4800000,
                                  max_instrument_lives=10, integration_tier=1)
    review = create_review(account["id"], config["id"], verdict="PASSED")
    create_training_record(account["id"])
    account = drive_account_to_readiness(account)
    agreement = submit_agreement(draft_agreement(account["id"], config["id"], review["id"]))
    account = get_success_data(api_client.get_account(
        account["id"], TEST_USERS["platform_admin_headers"]))
    accepted = get_success_data(api_client.accept_agreement(
        agreement["id"],
        {"expected_agreement_version": agreement["version"],
         "expected_hospital_account_version": account["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)
    terminated = get_success_data(api_client.terminate_agreement(
        accepted["id"], {"expected_agreement_version": accepted["version"]},
        TEST_USERS["platform_admin_headers"]), 200)
    set_clock("2026-12-01T00:00:00Z")
    return account, terminated


def test_accept_on_a_terminated_and_expired_agreement_reports_the_state_error(api):
    """PRD §3.1.3: "The agreement must be `PENDING_ACCEPTANCE` (`ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE`,
    checked first), the logical clock must be strictly before `acceptance_expires_utc` —
    otherwise `ERR_ACCEPTANCE_WINDOW_EXPIRED` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/state_versus_temporal_priority_at_accept
    """
    account, terminated = _terminated_and_expired_agreement()

    res = api_client.accept_agreement(
        terminated["id"],
        {"expected_agreement_version": terminated["version"],
         "expected_hospital_account_version": account["version"]},
        TEST_USERS["hospital_procurement_officer_headers"])

    validate_error(res, "ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE", expected_status=409)


def test_the_terminated_agreement_stays_terminated_after_the_refused_accept(api):
    """PRD §3.1.3: "A `PlatformAdmin` may terminate an agreement in `ACTIVE` or `SUSPENDED`;
    anything else is `ERR_AGREEMENT_NOT_TERMINABLE` (HTTP 409, checked first)."

    Design: Difficulty/priority_pair_validation_conflict/state_versus_temporal_priority_at_accept
    """
    account, terminated = _terminated_and_expired_agreement()

    api_client.accept_agreement(
        terminated["id"],
        {"expected_agreement_version": terminated["version"],
         "expected_hospital_account_version": account["version"]},
        TEST_USERS["hospital_procurement_officer_headers"])

    still = get_success_data(api_client.get_agreement(
        terminated["id"], TEST_USERS["compliance_officer_headers"]))
    assert still["agreement_status"] == "TERMINATED"