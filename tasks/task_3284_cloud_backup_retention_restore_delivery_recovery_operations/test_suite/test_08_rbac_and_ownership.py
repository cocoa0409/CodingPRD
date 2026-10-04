"""Corner claims about role exclusivity, ownership and access control."""
from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    ApiErrorId,
    GB_10,
    BACKUP,
    COMPLIANCE,
    RETENTION,
    SYS,
    build_user_headers,
    close_billing_period,
    complete_initial,
    create_account,
    create_agent,
    create_group,
    create_policy,
    create_restore,
    create_set,
    activate_agent,
    open_billing_period,
    owner_headers,
    record_version,
    set_clock,
    setup_active_set_for_restore,
)


def _active_set_scenario():
    scenario = setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/rbac.bin",
                                event_utc="2026-09-02T00:00:00Z",
                                require_mfa_for_restore=False)
    set_clock("2026-09-02T00:00:00Z")
    return scenario


def test_restore_creation_is_reserved_to_the_account_owner():
    """PRD §2.1: "`AccountOwner` alone drives restore creation and the restore
    lifecycle up to completion, cancellation, and the opening of a drive return
    window."
    PRD §2.1: "A request whose role is not permitted for the targeted operation,
    or in which an `AccountOwner` reaches for an account it does not own, is
    rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/backup_operator_cannot_create_restore_request
    """
    scenario = _active_set_scenario()
    account_id = scenario["account"]["id"]
    payload = {
        "account_id": account_id,
        "subject_agent_id": scenario["agent"]["id"],
        "restore_point_in_utc": "2026-09-02T00:00:00Z",
        "restore_type": "FILE_DOWNLOAD",
        "requested_file_count": 1,
        "requested_size_gb": 10.0,
        "restore_transaction_count": 0,
        "requester_mfa_ticket": "mfa-ticket-rb1",
        "expected_account_version": get_success_data(
            api.get_account(account_id, SYS))["version"],
    }
    response = api.create_restore_request(payload, BACKUP)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    rows = get_success_data(api.list_restore_requests(SYS, {"account_id": account_id}))
    assert rows == []


def test_a_request_without_the_role_header_is_refused_by_the_authentication_layer():
    """PRD §2.1: "Every request must carry two mandatory HTTP headers. `X-User-ID`
    identifies the acting principal, and `X-User-Role` names the operational
    capacity in which that principal is acting. A request that omits either
    header, or that names a role outside the declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/request_missing_role_header_returns_user_context_error
    """
    account = create_account(name="Northwind Personal")
    response = api.get_account(account["id"], {"X-User-ID": account["id"]})
    error = validate_error(response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert error["error_id"] != "ERR_UNAUTHORIZED"


def test_closing_a_billing_period_is_reserved_to_the_system_operator():
    """PRD §2.1: "`SystemOperator` alone registers and repairs storage pods,
    opens and closes billing periods, reinstates delinquent accounts, drives the
    drive-shipment lifecycle from shipment to closure, fails and reverses
    restore requests, blocks and unblocks agents, and expires cooling-off
    retention requests."

    Design: Corner/rbac/retention_officer_cannot_close_a_billing_period
    """
    account = create_account(name="Northwind Personal")
    period = open_billing_period(account["id"])
    set_clock("2026-09-02T00:00:00Z")

    response = api.close_billing_period(period["id"], RETENTION)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    fetched = get_success_data(api.get_billing_period(period["id"], SYS))
    assert fetched["state"] == "OPEN"


def test_an_account_owner_cannot_read_another_accounts_restore_requests():
    """PRD §2.1: "When `X-User-Role` is `AccountOwner`, `X-User-ID` is the `id`
    of the acting `Account`; ownership checks on any resource that references an
    `Account` compare the resource's `account_id` field to `X-User-ID`, and the
    `AccountOwner` is confined to its own account throughout every restore,
    retention, and shipment workflow."

    Design: Corner/rbac/account_owner_cannot_read_another_accounts_restore_requests
    """
    scenario = _active_set_scenario()
    account_id = scenario["account"]["id"]
    created = create_restore(scenario, restore_point_in_utc="2026-09-02T00:00:00Z",
                             requested_size_gb=10.0)

    other = create_account(name="Other Owner", region="US_EAST",
                           encryption_key_id="aes-256-key-other")

    # PRD 2.1: an AccountOwner is confined to its own account throughout every
    # restore workflow.  The confinement shows up as an empty scope, never as
    # another account's row; reading the foreign restore by its own id is the
    # definite ownership violation and lands in ERR_UNAUTHORIZED.
    scoped = get_success_data(api.list_restore_requests(
        build_user_headers(other["id"], "AccountOwner"), {"account_id": account_id}))
    assert scoped == []
    refused = api.get_restore_request(created["id"],
                                      build_user_headers(other["id"], "AccountOwner"))
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED)

    allowed = get_success_data(api.list_restore_requests(
        owner_headers(account_id), {"account_id": account_id}))
    assert len(allowed) == 1

