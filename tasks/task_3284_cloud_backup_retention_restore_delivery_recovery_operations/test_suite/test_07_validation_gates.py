"""Corner claims about the compliance and safety gates."""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    ApiErrorId,
    GB_10,
    GB_50,
    GB_100,
    BACKUP,
    COMPLIANCE,
    RETENTION,
    SYS,
    activate_agent,
    begin_cooling_off,
    begin_restore,
    close_billing_period,
    complete_initial,
    create_account,
    create_agent,
    create_group,
    create_policy,
    create_retention_request,
    create_restore,
    open_billing_period,
    owner_headers,
    record_version,
    set_clock,
    setup_business_active_set,
    setup_active_set_for_restore,
    setup_personal_scenario,
    validate_restore,
)


def _submit_litigation_hold(scenario):
    request = create_retention_request(scenario, requested_retention_days=365,
                                       reason_code="LITIGATION_HOLD")
    begin_cooling_off(request["id"])
    return request


def test_approving_a_deletion_request_under_a_litigation_hold_is_refused():
    """PRD §3.8: "And no retention change request for any of the account's
    groups may be in flight under a litigation hold: if any
    `RetentionChangeRequest` for the account's groups is in state `SUBMITTED`,
    `COOLING_OFF`, or `APPLIED` with a `reason_code` of `LITIGATION_HOLD`, the
    approval is rejected with `ERR_LITIGATION_HOLD_ACTIVE`. This is the
    mechanism by which a legal hold stops erasure in its tracks."

    Design: Corner/validations/deletion_approve_while_litigation_hold_active_returns_hold_error
    """
    scenario = setup_personal_scenario()
    account_id = scenario["account"]["id"]
    hold = _submit_litigation_hold(scenario)
    assert hold is not None

    deletion = api.create_data_deletion_request(
        {"account_id": account_id, "deletion_scope": "DELETED_FILES",
         "authorization_ref": "ticket-DSR-7788",
         "expected_account_version": get_success_data(
             api.get_account(account_id, SYS))["version"]},
        COMPLIANCE)
    deletion = get_success_data(deletion)

    refused = api.approve_data_deletion_request(deletion["id"], COMPLIANCE)
    error = validate_error(refused, ApiErrorId.ERR_LITIGATION_HOLD_ACTIVE)
    assert error["error_id"] == "ERR_LITIGATION_HOLD_ACTIVE"

    fetched = get_success_data(api.get_data_deletion_request(deletion["id"], COMPLIANCE))
    assert fetched["state"] == "SUBMITTED"
    assert fetched["approved_at_utc"] is None


def test_deleting_a_set_inside_its_retention_window_is_refused():
    """PRD §3.8: "Deletion is blocked while the set's data is still within its
    retention grace window: deleting an `ACTIVE` set requires either that every
    file version in the set has an elapsed grace window or that the account is
    `CLOSED`, and an attempt before that point is rejected with
    `ERR_RETENTION_HOLD_ACTIVE`."

    Design: Corner/validations/backup_set_delete_inside_retention_window_returns_hold_active
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/hold.bin",
                                event_utc="2026-09-02T00:00:00Z")
    set_id = scenario["set"]["id"]

    refused = api.delete_backup_set(set_id, BACKUP)
    validate_error(refused, ApiErrorId.ERR_RETENTION_HOLD_ACTIVE)

    fetched = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert fetched["state"] == "ACTIVE"
    rows = get_success_data(api.list_file_versions(set_id, BACKUP))
    assert len(rows) == 1


def test_drive_shipment_restore_on_a_personal_account_cannot_begin():
    """PRD §3.5: "A `DRIVE_SHIPMENT` restore is confined to accounts of type
    `BUSINESS` or `ENTERPRISE`, and a shipment restore on any other account
    type is rejected with `ERR_DRIVE_SHIPMENT_NOT_PERMITTED`."

    Design: Corner/validations/drive_shipment_begin_on_personal_account_returns_not_permitted
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/drive.bin",
                                event_utc="2026-09-02T00:00:00Z",
                                require_mfa_for_restore=False)
    account_id = scenario["account"]["id"]
    set_clock("2026-09-03T00:00:00Z")

    restore = create_restore(
        scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
        restore_type="DRIVE_SHIPMENT", requested_size_gb=10.0,
        drive_capacity_gb=50.0, drive_count=1, deposit_fee_cents=5000)

    # PRD 3.5: a DRIVE_SHIPMENT restore is confined to BUSINESS / ENTERPRISE
    # accounts, and it is the *validation* gate that refuses it — the request
    # never reaches the begin stage.
    refused = api.validate_restore_request(restore["id"], owner_headers(account_id), {})
    error = validate_error(refused, ApiErrorId.ERR_DRIVE_SHIPMENT_NOT_PERMITTED)
    assert error["error_id"] == "ERR_DRIVE_SHIPMENT_NOT_PERMITTED"

    fetched = get_success_data(api.get_restore_request(restore["id"], owner_headers(account_id)))
    assert fetched["state"] == "REQUESTED"
    shipments = get_success_data(api.list_drive_shipments(
        owner_headers(account_id), {"restore_request_id": restore["id"]}))
    assert shipments == []


def test_supplying_the_mfa_ticket_satisfies_the_restore_safety_gate():
    """PRD §3.5: "When the subject group's `ACTIVE` policy has
    `require_mfa_for_restore` true, the supplied `requester_mfa_ticket` must be
    non-empty, or the request is rejected with `ERR_MFA_REQUIRED`."
    PRD §3.5: "Validation is the first substantive gate, moving a request from
    `REQUESTED` to `VALIDATING`"

    Design: Corner/validations/restore_validate_with_mfa_ticket_satisfies_the_safety_gate
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/mfa.bin",
                                event_utc="2026-09-02T00:00:00Z",
                                require_mfa_for_restore=True)
    account_id = scenario["account"]["id"]
    set_clock("2026-09-03T00:00:00Z")

    restore = create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                             requested_size_gb=10.0,
                             requester_mfa_ticket="mfa-ticket-777")
    validated = validate_restore(restore["id"], account_id, "mfa-ticket-777")
    assert validated["state"] == "VALIDATING"


def test_creating_a_group_under_an_unknown_account_reports_the_account_as_missing():
    """PRD §2.10: "A body-supplied `account_id` pointing at a non-existent
    account therefore fails with `ERR_ACCOUNT_NOT_FOUND` before any deeper
    identifier is consulted."

    Design: Corner/validations/backup_group_create_with_unknown_account_returns_account_not_found
    """
    set_clock()
    response = api.create_backup_group(
        {"account_id": "00000000-0000-4000-8000-000000000009",
         "name": "Ghost Group", "tier": "STANDARD"},
        SYS)
    error = validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
    assert error["error_id"] == "ERR_ACCOUNT_NOT_FOUND"

    rows = get_success_data(api.list_backup_groups(SYS))
    assert rows == []