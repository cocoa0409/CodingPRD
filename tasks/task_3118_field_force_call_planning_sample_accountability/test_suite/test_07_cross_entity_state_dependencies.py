"""Cross-entity state dependencies: a transition whose legality reads another
entity's live state at the moment of the call.

Queue A — difficulty design rule ``cross_entity_state_dependency``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_field_rep_headers,
    validate_error,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN_HEADERS, COMPLIANCE_HEADERS


class TestCaptureRechecksLotReleasability:
    """The lot must still be RELEASED (and unexpired) at capture time, not
    merely at disbursement creation."""

    def _setup_pending_disbursement_on_expiring_lot(self, api):
        ctx = fx.setup_published_plan_with_rep(
            api,
            tier="B",
            planned_sample_units=40,
            budget=300,
            rep_issue_qty=20,
            lot_quantity=100,
        )
        # Point the lot's expiry just past the default clock, then create and
        # complete the visit and record the disbursement while still
        # releasable.
        lot = ctx["lot"]
        # Recreate the context with a short-dated lot for clarity.
        return ctx

    def test_capture_after_expiration_rejected(self, api):
        """PRD section 3.2: "A lot is releasable only while its status is RELEASED
        and its expiration_date is strictly later than the logical clock's current
        time. This releasability check is enforced at four points — recording a
        disbursement, capturing a signature, requesting a transfer, and accepting a
        transfer — and failure at any of them is rejected with
        ERR_LOT_NOT_RELEASABLE."

        Design: Difficulty/cross_entity_state_dependency/signature_capture_blocked_by_lot_quarantined_after_visit
        """
        ctx = fx.setup_published_plan_with_rep(
            api,
            tier="B",
            planned_sample_units=40,
            budget=300,
            rep_issue_qty=20,
            lot_quantity=100,
        )
        # Re-point the lot to expire at noon on the default-clock day by
        # issuing from a fresh short-dated lot instead.
        product = ctx["product"]
        short_lot = fx.create_sample_lot(
            api,
            product["id"],
            expiration_date="2026-09-01T12:00:00Z",
            quantity_received=100,
        )
        fx.issue_lot_to_rep(api, ctx["rep"]["id"], short_lot["id"], 20)
        visit = fx.schedule_visit(
            api, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"]
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        from test_helpers import factories as f

        disbursement = get_success_data(
            api.create_sample_disbursement(
                f.create_sample_disbursement_payload(
                    visit["id"], short_lot["id"], 4
                ),
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        # Advance the logical clock past the lot's expiration.
        fx.set_clock(api, "2026-09-01T13:00:00Z")
        response = api.capture_signature(
            disbursement["id"],
            "A" * 40,
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_LOT_NOT_RELEASABLE)

    def test_failed_capture_leaves_disbursement_pending(self, api):
        """PRD section 3.5: "The reconciliation_status enumeration is
        PENDING_SIGNATURE, SIGNED, REJECTED, and VOIDED, with the latter three
        terminal." — a refused capture must not silently advance the record.

        Design: Difficulty/cross_entity_state_dependency/signature_capture_blocked_by_lot_quarantined_after_visit
        """
        ctx = fx.setup_published_plan_with_rep(
            api,
            tier="B",
            planned_sample_units=40,
            budget=300,
            rep_issue_qty=20,
            lot_quantity=100,
        )
        product = ctx["product"]
        short_lot = fx.create_sample_lot(
            api,
            product["id"],
            expiration_date="2026-09-01T12:00:00Z",
            quantity_received=100,
        )
        fx.issue_lot_to_rep(api, ctx["rep"]["id"], short_lot["id"], 20)
        visit = fx.schedule_visit(
            api, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"]
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        from test_helpers import factories as f

        disbursement = get_success_data(
            api.create_sample_disbursement(
                f.create_sample_disbursement_payload(
                    visit["id"], short_lot["id"], 4
                ),
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        fx.set_clock(api, "2026-09-01T13:00:00Z")
        api.capture_signature(
            disbursement["id"],
            "A" * 40,
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        after = get_success_data(
            api.get_sample_disbursement(
                disbursement["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert after["reconciliation_status"] == "PENDING_SIGNATURE"


class TestCompletionReadsLivePrescriberState:
    """Eligibility is re-checked at completion time; a verification flip
    between scheduling and completion blocks the completion."""

    def _setup(self, api):
        ctx = fx.setup_published_plan_with_rep(
            api, tier="C", planned_sample_units=10, budget=100
        )
        visit = fx.schedule_visit(
            api, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"]
        )
        ctx["visit"] = visit
        return ctx

    def test_completion_rejected_after_eligibility_revoked(self, api):
        """PRD section 3.4: "The prescriber must be ELIGIBLE at completion time
        (otherwise ERR_PRESCRIBER_NOT_ELIGIBLE)."

        Design: Difficulty/cross_entity_state_dependency/visit_completion_blocked_by_prescriber_ineligible_and_rep_suspended
        """
        ctx = self._setup(api)
        fx.verify_prescriber(api, ctx["prescriber"]["id"], outcome="FAIL")
        response = api.complete_call_visit(
            ctx["visit"]["id"],
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PRESCRIBER_NOT_ELIGIBLE)

    def test_visit_remains_scheduled_after_rejected_completion(self, api):
        """PRD section 3.4: "Completing a visit — the transition from SCHEDULED to
        COMPLETED" — when the gate refuses, no transition occurs and the visit stays
        SCHEDULED.

        Design: Difficulty/cross_entity_state_dependency/visit_completion_blocked_by_prescriber_ineligible_and_rep_suspended
        """
        ctx = self._setup(api)
        fx.verify_prescriber(api, ctx["prescriber"]["id"], outcome="FAIL")
        api.complete_call_visit(
            ctx["visit"]["id"],
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        visit = get_success_data(
            api.get_call_visit(
                ctx["visit"]["id"],
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        assert visit["call_status"] == "SCHEDULED"
