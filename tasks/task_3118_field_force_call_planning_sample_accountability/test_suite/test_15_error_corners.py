"""Error catalogue corner coverage: signature shape, quarantine-open resolve,
manager-only reconcile, receiver-only accept/reject, and visit ownership.

Queue B — corner design section ``errors``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
    validate_error,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE_HEADERS, QA_HEADERS


class TestSignatureRequired:
    def _setup_pending(self, api):
        return fx.setup_completed_visit_with_disbursement(api, disbursement_qty=2)

    def test_short_signature_payload_rejected(self, api):
        """PRD section 3.5: "the payload must be present and at least 32 characters
        long (otherwise ERR_SIGNATURE_REQUIRED)."

        Design: Corner/errors/error_signature_required_on_short_payload
        """
        ctx = self._setup_pending(api)
        response = api.capture_signature(
            ctx["disbursement"]["id"],
            "tooshort",
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SIGNATURE_REQUIRED)

    def test_failed_capture_leaves_disbursement_pending(self, api):
        """PRD section 3.5: "The reconciliation_status enumeration is
        PENDING_SIGNATURE, SIGNED, REJECTED, and VOIDED, with the latter three
        terminal." — a refused capture performs no transition.

        Design: Corner/errors/error_signature_required_on_short_payload
        """
        ctx = self._setup_pending(api)
        api.capture_signature(
            ctx["disbursement"]["id"],
            "tooshort",
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        after = get_success_data(
            api.get_sample_disbursement(
                ctx["disbursement"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert after["reconciliation_status"] == "PENDING_SIGNATURE"


class TestQuarantineOpenBlocksResolve:
    def _setup_assessed_critical(self, api):
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=10, lot_quantity=50)
        excursion = fx.report_excursion(
            api,
            ctx["sender"],
            ctx["product"]["id"],
            location_type="VEHICLE",
            observed_temp_c=14.0,
            excursion_minutes=60,
        )
        fx.assess_excursion(api, excursion["id"])
        ctx["excursion"] = excursion
        return ctx

    def test_resolve_blocked_while_quarantine_open(self, api):
        """PRD section 3.7: "Resolution — moving from ASSESSED to RESOLVED — is
        blocked for a CRITICAL excursion until every quarantined lot has been
        destroyed or sent back through the return workflow; attempting to resolve
        earlier is rejected with ERR_QUARANTINE_OPEN."

        Design: Corner/errors/error_quarantine_open_blocks_excursion_resolve
        """
        ctx = self._setup_assessed_critical(api)
        response = api.resolve_temperature_excursion(
            ctx["excursion"]["id"], headers=QA_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_QUARANTINE_OPEN)

    def test_excursion_remains_assessed_after_blocked_resolve(self, api):
        """PRD section 3.7: "the excursion's status enumeration is REPORTED, ASSESSED,
        and RESOLVED, with RESOLVED terminal." — a refused resolve performs no
        transition.

        Design: Corner/errors/error_quarantine_open_blocks_excursion_resolve
        """
        ctx = self._setup_assessed_critical(api)
        api.resolve_temperature_excursion(ctx["excursion"]["id"], headers=QA_HEADERS)
        excursion = get_success_data(
            api.get_temperature_excursion(ctx["excursion"]["id"], headers=QA_HEADERS)
        )
        assert excursion["status"] == "ASSESSED"


class TestReconcileByNonManager:
    def _setup_counted_session(self, api):
        ctx = fx.setup_count_session_cast(api, custodian_issue_qty=10)
        # A second manager who is NOT the custodian's manager.
        other_manager = fx.create_representative(api, ctx["t_custodian"]["id"])
        session = fx.open_count_session(
            api,
            ctx["custodian"],
            ctx["counter"],
            ctx["manager"],
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-21T00:00:00Z",
        )
        fx.submit_full_count(
            api, session["id"], ctx["counter"], {ctx["lot"]["id"]: 10}
        )
        ctx["session"] = session
        ctx["other_manager"] = other_manager
        return ctx

    def test_non_manager_reconcile_forbidden(self, api):
        """PRD section 3.6: "Reconciliation belongs to the custodian's direct manager:
        the acting DistrictManager's identity must equal the custodian's
        manager_rep_id (otherwise ERR_NOT_CUSTODIAN_MANAGER)."

        Design: Corner/errors/error_reconcile_by_non_manager_forbidden
        """
        ctx = self._setup_counted_session(api)
        response = api.reconcile_count_session(
            ctx["session"]["id"],
            headers=make_district_manager_headers(ctx["other_manager"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NOT_CUSTODIAN_MANAGER)

    def test_session_remains_counted_after_forbidden_reconcile(self, api):
        """PRD section 3.6: "A session's status enumeration is OPEN, COUNTED,
        RECONCILED, CLOSED, and VOIDED, with CLOSED and VOIDED terminal." — a refused
        reconcile performs no transition out of COUNTED.

        Design: Corner/errors/error_reconcile_by_non_manager_forbidden
        """
        ctx = self._setup_counted_session(api)
        api.reconcile_count_session(
            ctx["session"]["id"],
            headers=make_district_manager_headers(ctx["other_manager"]["id"]),
        )
        session = get_success_data(
            api.get_count_session(ctx["session"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert session["status"] == "COUNTED"


class TestTransferReceiverEnforcement:
    def _setup_requested(self, api):
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=10, lot_quantity=50)
        transfer = fx.request_transfer(
            api, ctx["sender"], ctx["receiver"], ctx["lot"], 3
        )
        ctx["transfer"] = transfer
        return ctx

    def test_sender_cannot_accept(self, api):
        """PRD section 3.6: "The receiver — and only the receiver — may accept or
        reject. Acceptance requires that X-User-ID equal the transfer's to_rep_id
        (otherwise ERR_NOT_TRANSFER_RECEIVER); the segregation-of-duties rule means
        the sender can never accept their own transfer."

        Design: Corner/errors/error_transfer_receiver_enforcement_on_accept_and_reject
        """
        ctx = self._setup_requested(api)
        response = api.accept_transfer(
            ctx["transfer"]["id"],
            headers=make_field_rep_headers(ctx["sender"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NOT_TRANSFER_RECEIVER)

    def test_sender_cannot_reject_and_transfer_stays_requested(self, api):
        """PRD section 3.6: "The receiver — and only the receiver — may accept or
        reject." and "Rejection likewise requires the receiver's identity."

        Design: Corner/errors/error_transfer_receiver_enforcement_on_accept_and_reject
        """
        ctx = self._setup_requested(api)
        response = api.reject_transfer(
            ctx["transfer"]["id"],
            headers=make_field_rep_headers(ctx["sender"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NOT_TRANSFER_RECEIVER)
        transfer = get_success_data(
            api.get_sample_transfer(ctx["transfer"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert transfer["status"] == "REQUESTED"


class TestVisitOwnership:
    def test_non_owner_complete_forbidden(self, api):
        """PRD section 3.4: "The acting rep's identity must equal the visit's
        representative_id (otherwise ERR_NOT_VISIT_OWNER)."

        Design: Corner/errors/error_not_visit_owner_on_complete_and_submit_count_non_counter
        """
        ctx = fx.setup_published_plan_with_rep(api, tier="C", planned_sample_units=10)
        other_rep = fx.create_representative(api, ctx["territory"]["id"])
        visit = fx.schedule_visit(
            api, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"]
        )
        response = api.complete_call_visit(
            visit["id"], headers=make_field_rep_headers(other_rep["id"])
        )
        validate_error(response, ApiErrorId.ERR_NOT_VISIT_OWNER)
        visit_after = get_success_data(
            api.get_call_visit(
                visit["id"], headers=make_field_rep_headers(ctx["rep"]["id"])
            )
        )
        assert visit_after["call_status"] == "SCHEDULED"

    def test_non_counter_submit_forbidden(self, api):
        """PRD section 3.6: "The counter — a FieldRep whose identity must equal the
        session's counter_rep_id (otherwise ERR_NOT_COUNT_COUNTER)."

        Design: Corner/errors/error_not_visit_owner_on_complete_and_submit_count_non_counter
        """
        ctx = fx.setup_count_session_cast(api, custodian_issue_qty=10)
        session = fx.open_count_session(
            api,
            ctx["custodian"],
            ctx["counter"],
            ctx["manager"],
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-21T00:00:00Z",
        )
        # The custodian is not the counter.
        response = api.submit_count(
            session["id"],
            [{"lot_id": ctx["lot"]["id"], "counted_qty": 10}],
            headers=make_field_rep_headers(ctx["custodian"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NOT_COUNT_COUNTER)
