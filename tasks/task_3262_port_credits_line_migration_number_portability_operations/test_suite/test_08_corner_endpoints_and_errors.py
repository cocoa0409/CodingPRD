"""Corner coverage: endpoint behaviours whose side effects reach a second entity."""
from test_helpers import (
    ADMIN,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_system_config,
    cancel_line,
    create_bare_line,
    create_account,
    create_activated_line,
    create_draft_port_request,
    create_rejection_code,
    get_account,
    get_line,
    get_port_request,
    get_system_config,
    record_rejection,
    resubmit_port_request,
    resolve_protection_case,
    create_protection_case,
    submit_port_request,
)

CARE = TEST_USERS["customer_service_headers"]


class TestProtectionClearReopensResubmittedRequest:
    def test_clearing_the_case_releases_the_line(self, api):
        """PRD §3.10: "Clearing the case moves it to `case_state` `CLEARED`, stamps
        `cleared_at` with the current logical clock instant, sets the case's `set_at` back
        to null, and sets the attached line's `port_protection_status` to `UNPROTECTED`; a
        cleared case is terminal."

        Design: Corner/endpoints/port_protection_clear_reopens_resubmitted_request
        """
        account, line, request = build_resubmitted_request_with_active_case("4155557101")

        cleared = resolve_protection_case(request["case"]["id"], "CLEAR")

        assert cleared["case_state"] == "CLEARED"
        assert get_line(line["id"])["port_protection_status"] == "UNPROTECTED"

    def test_the_clear_pushes_the_resubmitted_request_back_to_rejected(self, api):
        """PRD §3.10: "if the line carries a `PortRequest` whose `request_state` is
        `RESUBMITTED`, that request is set to `REJECTED` and the line's `number_status` is
        set to `UNASSIGNED`."

        Design: Corner/endpoints/port_protection_clear_reopens_resubmitted_request
        """
        account, line, request = build_resubmitted_request_with_active_case("4155557102")

        resolve_protection_case(request["case"]["id"], "CLEAR")

        assert get_port_request(request["port_request"]["id"])["request_state"] == "REJECTED"

    def test_the_number_is_released_when_the_clear_lands(self, api):
        """PRD §3.10: "the request must be resubmitted afresh once the line is
        unprotected, and the number is released in the meantime."

        Design: Corner/endpoints/port_protection_clear_reopens_resubmitted_request
        """
        account, line, request = build_resubmitted_request_with_active_case("4155557103")

        resolve_protection_case(request["case"]["id"], "CLEAR")

        assert get_line(line["id"])["number_status"] == "UNASSIGNED"


class TestOpsRunIdempotence:
    def test_a_run_inside_the_grace_window_leaves_the_epoch_alone(self, api):
        """PRD §3.7: "When `triggered_at` is at or before the deadline the sweep is a no-op
        apart from recording the instant: `ops_run_epoch` is left unchanged and
        `last_ops_run_at` is set to `triggered_at`."

        Design: Corner/endpoints/ops_run_is_idempotent_until_cancellation_deadline
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155558101", billing_mode="POSTPAID")
        advance_clock("2026-09-02T00:00:00Z")
        cancel_line(line["id"], reason_code="NONPAYMENT")
        assert get_system_config()["ops_run_epoch"] == 1

        api_client.run_ops({"triggered_at": "2026-09-02T12:00:00Z"}, ADMIN)
        api_client.run_ops({"triggered_at": "2026-09-03T00:00:00Z"}, ADMIN)

        assert get_system_config()["ops_run_epoch"] == 1

    def test_a_run_strictly_after_the_deadline_advances_the_epoch(self, api):
        """PRD §3.7: "when `triggered_at` is strictly after that deadline, increments the
        system's `ops_run_epoch` by one, sets `last_ops_run_at` to `triggered_at`"

        Design: Corner/endpoints/ops_run_is_idempotent_until_cancellation_deadline
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155558101", billing_mode="POSTPAID")
        advance_clock("2026-09-02T00:00:00Z")
        cancel_line(line["id"], reason_code="NONPAYMENT")

        api_client.run_ops({"triggered_at": "2026-09-03T06:00:00Z"}, ADMIN)
        config = get_system_config()

        assert config["ops_run_epoch"] == 2
        assert config["last_ops_run_at"] == "2026-09-03T06:00:00.000Z"
        assert_system_config(config)

    def test_the_sweep_reclaims_the_cancelled_lines_number(self, api):
        """PRD §3.7: "sets `number_status` to `RECLAIMED` on every subscriber line whose
        `service_status` is `CANCELLED` and whose `number_status` is `ASSIGNED`."

        Design: Corner/endpoints/ops_run_is_idempotent_until_cancellation_deadline
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155558102", billing_mode="POSTPAID")
        advance_clock("2026-09-02T00:00:00Z")
        cancel_line(line["id"], reason_code="NONPAYMENT")

        api_client.run_ops({"triggered_at": "2026-09-03T06:00:00Z"}, ADMIN)

        assert get_line(line["id"])["number_status"] == "RECLAIMED"


class TestMdnConflict:
    def test_a_number_already_assigned_cannot_be_reissued(self, api):
        """PRD §3.7: "Creating a line whose `mdn` collides with a line already holding it
        as `ASSIGNED`, `RESERVED` or `PORTED_IN` is refused with `ERR_MDN_CONFLICT` (409)."

        Design: Corner/errors/mdn_conflict_on_second_line_creation
        """
        account = create_account()
        create_activated_line(account["id"], "4155559101", billing_mode="POSTPAID")

        response = api_client.create_subscriber_line(
            {"account_id": account["id"], "mdn": "4155559101", "billing_mode": "POSTPAID"},
            ADMIN,
        )

        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_MDN_CONFLICT"

    def test_the_refused_creation_leaves_the_account_count_unchanged(self, api):
        """PRD §3.7: "Creating a line also recomputes the owning account's
        `active_line_count` as the count of that account's lines whose `service_status` is
        `ACTIVE`"

        Design: Corner/errors/mdn_conflict_on_second_line_creation
        """
        account = create_account()
        create_activated_line(account["id"], "4155559101", billing_mode="POSTPAID")
        api_client.create_subscriber_line(
            {"account_id": account["id"], "mdn": "4155559101", "billing_mode": "POSTPAID"},
            ADMIN,
        )

        assert get_account(account["id"])["active_line_count"] == 1


class TestUnknownRejectionCode:
    def test_a_code_absent_from_the_catalog_is_refused(self, api):
        """PRD §3.2: "the code must resolve to a row of the `RejectionCodeCatalog`; an
        unknown code is refused with `ERR_REJECTION_CODE_NOT_FOUND` (404)."

        Design: Corner/errors/unknown_rejection_code_is_rejected
        """
        account = create_account()
        line = create_bare_line(account["id"], "4155559201", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="9292", account_number_at_losing_carrier="ACC92",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request)

        response = api_client.record_port_rejection(
            request["id"], {"rejection_code": "NO_SUCH_CODE"}, ADMIN
        )

        assert response.status_code == 404
        assert response.json()["data"]["error_id"] == "ERR_REJECTION_CODE_NOT_FOUND"

    def test_the_refused_rejection_leaves_the_request_pending(self, api):
        """PRD §3.2: "The request must be in `PENDING` at the time, and the code must
        resolve to a row of the `RejectionCodeCatalog`"

        Design: Corner/errors/unknown_rejection_code_is_rejected
        """
        account = create_account()
        line = create_bare_line(account["id"], "4155559201", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="9292", account_number_at_losing_carrier="ACC92",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request)
        api_client.record_port_rejection(
            request["id"], {"rejection_code": "NO_SUCH_CODE"}, ADMIN
        )

        unchanged = get_port_request(request["id"])
        assert unchanged["request_state"] == "PENDING"
        assert unchanged["rejection_count"] == 0


# --- local helpers -----------------------------------------------------------

def build_resubmitted_request_with_active_case(mdn):
    """A RESUBMITTED port request on a line carrying a freshly ACTIVE case."""
    create_rejection_code(
        "ZIP_MISMATCH", resubmission_allowed=True, retry_after_hours=0
    )
    account = create_account()
    line = create_bare_line(account["id"], mdn, billing_mode="PREPAID")
    advance_clock("2026-09-02T00:00:00Z")
    port_request = create_draft_port_request(
        line, transfer_pin="7171", account_number_at_losing_carrier="ACC71",
        requested_cutover_at="2026-09-20T00:00:00Z",
    )
    submit_port_request(port_request)
    record_rejection(port_request["id"], "ZIP_MISMATCH")
    resubmit_port_request(port_request)
    case = create_protection_case(
        line, verified_identity=True, protection_type="FRAUD_HOLD",
        reason_code="SUSPECTED_FRAUD",
    )
    resolve_protection_case(case["id"], "ACTIVATE")
    return (
        account,
        get_line(line["id"]),
        {"port_request": get_port_request(port_request["id"]), "case": case},
    )