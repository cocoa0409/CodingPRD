"""Corner coverage: state-machine preconditions and the errors they raise."""
from test_helpers import (
    ADMIN,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_subscriber_line,
    create_account,
    create_activated_line,
    create_active_protection_case,
    create_bare_line,
    create_protection_case,
    create_reservation,
    get_line,
    get_port_request,
    setup_ported_line,
)

CARE = TEST_USERS["customer_service_headers"]


def _reservation_state(account_id, reservation_id):
    """Read one reservation back out of the account-scoped reservation list."""
    listed = api_client.list_account_number_reservations(account_id, ADMIN)
    for row in listed.json()["data"]:
        if row["id"] == reservation_id:
            return row["reservation_state"]
    return None


class TestPortRequestInvalidTransition:
    def test_submitting_a_ported_request_is_refused(self, api):
        """PRD §2.9: "The generic state gate is reported as `ERR_INVALID_STATE` with an
        HTTP status of 409: this is what a caller receives when it asks for a transition
        on a resource whose current state is not the starting state that transition
        requires, and it applies to every state-transition operation in this API —
        submitting, rejecting, resubmitting, accepting and cancelling a port request"
        PRD §3.1: "The `PortRequest` must currently be in `DRAFT`."

        Design: Corner/state_machines/submit_from_ported_request_returns_invalid_state
        """
        account, line, ported = setup_ported_line("4155554101",
                                                  cutover_at="2026-09-05T00:00:00Z")
        assert ported["request_state"] == "PORTED"

        response = api_client.submit_port_request(
            ported["id"],
            {"transfer_pin": "4141", "account_number_at_losing_carrier": "ACC41"},
            CARE,
        )

        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_INVALID_STATE"

    def test_a_ported_request_stays_ported_after_the_refused_submit(self, api):
        """PRD §2.9: "it applies to every state-transition operation in this API —
        submitting, rejecting, resubmitting, accepting and cancelling a port request"

        Design: Corner/state_machines/submit_from_ported_request_returns_invalid_state
        """
        account, line, ported = setup_ported_line("4155554102",
                                                  cutover_at="2026-09-05T00:00:00Z")
        api_client.submit_port_request(
            ported["id"],
            {"transfer_pin": "4141", "account_number_at_losing_carrier": "ACC41"},
            CARE,
        )

        assert get_port_request(ported["id"])["request_state"] == "PORTED"


class TestProtectionActivationPrecondition:
    def test_unverified_case_cannot_be_activated(self, api):
        """PRD §3.10: "The case's `verified_identity` must be true — a case opened without
        verification that is then activated is refused with `ERR_IDENTITY_NOT_VERIFIED`
        (403), which is what stops a fraudulently opened case from being turned into a
        real freeze."

        Design: Corner/state_machines/protection_resolve_without_verified_identity_denied
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155554201", billing_mode="PREPAID")
        case = create_protection_case(
            line, verified_identity=False,
            protection_type="ACCOUNT_PIN", reason_code="UNVERIFIED",
        )

        response = api_client.resolve_port_protection_case(
            case["id"], {"resolution": "ACTIVATE"}, ADMIN
        )

        assert response.json()["data"]["error_id"] == "ERR_IDENTITY_NOT_VERIFIED"

    def test_the_refused_activation_leaves_the_line_unprotected(self, api):
        """PRD §3.10: "Opening a case by itself changes nothing about the line; the freeze
        only takes effect when the case is resolved with an activation."

        Design: Corner/state_machines/protection_resolve_without_verified_identity_denied
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155554201", billing_mode="PREPAID")
        case = create_protection_case(
            line, verified_identity=False,
            protection_type="ACCOUNT_PIN", reason_code="UNVERIFIED",
        )
        api_client.resolve_port_protection_case(case["id"], {"resolution": "ACTIVATE"}, ADMIN)

        refreshed = get_line(line["id"])
        assert refreshed["port_protection_status"] == "UNPROTECTED"
        assert_subscriber_line(refreshed)

    def test_a_second_active_case_on_the_line_is_refused(self, api):
        """PRD §3.10: "And no other `PortProtectionCase` on the same subscriber line may
        already have `case_state` `ACTIVE`, or the activation is refused with
        `ERR_PROTECTION_ALREADY_ACTIVE` (409); a line carries at most one active
        protection at a time."

        Design: Corner/state_machines/protection_resolve_without_verified_identity_denied
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155554202", billing_mode="PREPAID")
        create_active_protection_case(line)
        second = create_protection_case(line)

        response = api_client.resolve_port_protection_case(
            second["id"], {"resolution": "ACTIVATE"}, ADMIN
        )

        assert response.json()["data"]["error_id"] == "ERR_PROTECTION_ALREADY_ACTIVE"


class TestReservationCommitWindow:
    def test_committing_after_the_exclusive_upper_bound_is_refused(self, api):
        """PRD §3.9: "A commit attempted at or after `reserved_until` is refused with
        `ERR_RESERVATION_WINDOW_CLOSED` (409)."

        Design: Corner/state_machines/reservation_commit_after_window_close_returns_window_closed
        """
        account = create_account()
        line = create_bare_line(account["id"], "4155554301", billing_mode="POSTPAID")
        reservation = create_reservation(
            account["id"], "4155554302",
            reserved_at="2026-09-01T00:00:00Z", reserved_until="2026-09-16T00:00:00Z",
        )
        advance_clock("2026-09-16T00:00:00Z")

        response = api_client.commit_number_reservation(
            reservation["id"], {"subscriber_line_id": line["id"]}, ADMIN
        )

        assert response.json()["data"]["error_id"] == "ERR_RESERVATION_WINDOW_CLOSED"

    def test_the_closed_window_leaves_the_hold_outstanding(self, api):
        """PRD §3.9: "When the logical clock reaches the reservation's `reserved_until`
        while the reservation is still `HELD`, the reservation moves to
        `reservation_state` `EXPIRED`" and "A commit attempted at or after
        `reserved_until` is refused with `ERR_RESERVATION_WINDOW_CLOSED` (409)", which
        "leaves the hold outstanding" rather than committing it: the named line is not
        put into service and its number is not assigned.

        Design: Corner/state_machines/reservation_commit_after_window_close_returns_window_closed
        """
        account = create_account()
        line = create_bare_line(account["id"], "4155554301", billing_mode="POSTPAID")
        reservation = create_reservation(
            account["id"], "4155554302",
            reserved_at="2026-09-01T00:00:00Z", reserved_until="2026-09-16T00:00:00Z",
        )
        advance_clock("2026-09-16T00:00:00Z")
        api_client.commit_number_reservation(
            reservation["id"], {"subscriber_line_id": line["id"]}, ADMIN
        )

        assert get_line(line["id"])["number_status"] == "UNASSIGNED"
        assert _reservation_state(account["id"], reservation["id"]) == "EXPIRED"