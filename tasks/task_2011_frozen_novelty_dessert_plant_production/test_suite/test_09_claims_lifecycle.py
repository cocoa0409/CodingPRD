"""Claim lifecycle: deny/appeal cycle, terminal states, ownership, filing
gates (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    allocate,
    create_customer,
    create_shipment,
    file_claim,
    get_success_data,
    make_customer_rep_headers,
    set_clock,
    setup_completed_run,
    setup_delivered_shipment,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADJUSTER, WH

TWO_CLEAN_READINGS = [
    {"recorded_at": "2026-08-10T09:00:00Z", "temp_c": -19.0},
    {"recorded_at": "2026-08-10T10:00:00Z", "temp_c": -19.0},
]

STANDARD_LOG = [
    {"recorded_at": "2026-08-12T08:00:00Z", "temp_c": -19.0},
    {"recorded_at": "2026-08-12T09:00:00Z", "temp_c": -16.0},
    {"recorded_at": "2026-08-12T10:00:00Z", "temp_c": -16.0},
    {"recorded_at": "2026-08-12T11:00:00Z", "temp_c": -20.0},
    {"recorded_at": "2026-08-12T12:00:00Z", "temp_c": -15.0},
]


class TestClaimAppealCycle:
    def test_claim_denied_appeal_cycle_recomputes_identically(self, api):
        """PRD §3.9: "The DENIED → APPEALED → EVIDENCE_REVIEW loop permits
        unlimited appeals." A ClaimsAdjuster "opens evidence review on a
        SUBMITTED or APPEALED claim"; the replay is deterministic on
        unchanged readings, so the second review recomputes abuse_minutes
        180 again.

        Design: Difficulty/non_linear_state_machine/claim_denied_appeal_cycle
        """
        ctx = setup_delivered_shipment(readings=STANDARD_LOG)
        claim = file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                           claim_code="CL-X", declared_value_cents=100000)
        first = validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        assert first["abuse_minutes"] == 180
        denied = validate_success(api.deny_claim(claim["id"], ADJUSTER))
        assert denied["status"] == "DENIED"
        # Appeal at decided_at + 3 days — inside the 14-day window.
        set_clock("2026-08-15T13:00:00Z")
        appealed = validate_success(api.appeal_claim(
            claim["id"], make_customer_rep_headers(ctx["customer"]["id"])))
        assert appealed["status"] == "APPEALED"
        second = validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        assert second["status"] == "EVIDENCE_REVIEW"
        assert second["abuse_minutes"] == 180

    def test_claim_denied_appeal_cycle_status_path(self, api):
        """PRD §3.9: "The filer may appeal a DENIED claim, moving it to
        APPEALED, provided the current logical clock is no later than
        decided_at plus 14 days (the boundary is inclusive; day 14 still
        appeals)." The status path EVIDENCE_REVIEW -> DENIED -> APPEALED ->
        EVIDENCE_REVIEW re-enters a state the claim already occupied — a
        cycle, not a linear pipeline.

        Design: Difficulty/non_linear_state_machine/claim_denied_appeal_cycle
        """
        ctx = setup_delivered_shipment(readings=STANDARD_LOG)
        claim = file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                           claim_code="CL-X2", declared_value_cents=100000)
        reviewed = validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        assert reviewed["status"] == "EVIDENCE_REVIEW"
        denied = validate_success(api.deny_claim(claim["id"], ADJUSTER))
        assert denied["status"] == "DENIED"
        appealed = validate_success(api.appeal_claim(
            claim["id"], make_customer_rep_headers(ctx["customer"]["id"])))
        assert appealed["status"] == "APPEALED"
        reopened = validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        assert reopened["status"] == "EVIDENCE_REVIEW"


class TestClaimTerminalLockdown:
    def test_claim_appeal_after_paid_rejected(self, api):
        """PRD §3.9: "The filer may appeal a DENIED claim, moving it to
        APPEALED" — appeal is offered from DENIED only, so an appeal on a
        PAID claim fails the state gate: §5 ERR_INVALID_STATE — "Target
        resource's state does not allow the requested transition".

        Design: Corner/state_machines/claim_appeal_after_paid_rejected
        """
        ctx = setup_delivered_shipment(
            readings=[
                {"recorded_at": "2026-08-10T09:00:00Z", "temp_c": -19.0},
                {"recorded_at": "2026-08-10T10:00:00Z", "temp_c": -19.0},
            ],
            dispatch_time="2026-08-10T08:30:00Z",
            deliver_time="2026-08-10T12:00:00Z",
            shipment_code="SH-P")
        claim = file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                           claim_code="CL-P")
        validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        validate_success(api.approve_claim(claim["id"], ADJUSTER))
        validate_success(api.pay_claim(claim["id"], ADJUSTER))
        resp = api.appeal_claim(
            claim["id"], make_customer_rep_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestClaimFilingGates:
    def test_claim_before_delivery_not_allowed(self, api):
        """PRD §3.9: "A CustomerRep files a TempAbuseClaim against a
        shipment that is DELIVERED or REJECTED — any other status rejects
        with ERR_CLAIM_NOT_ALLOWED"."

        Design: Corner/validations/claim_before_delivery_not_allowed
        """
        ctx = setup_completed_run(actual_units=2000, mix_metered_litres=100.0)
        customer = create_customer()
        shipment = create_shipment(customer["id"], shipment_code="SH-IT")
        allocate(shipment["id"], ctx["lot"]["id"], 500)
        get_success_data(api.load_shipment(shipment["id"], WH))
        get_success_data(api.dispatch_shipment(shipment["id"], WH))
        resp = api.create_temp_abuse_claim(
            {"claim_code": "CL-IT", "shipment_id": shipment["id"],
             "declared_value_cents": 50000},
            make_customer_rep_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ALLOWED)

    def test_duplicate_claim_rejected(self, api):
        """PRD §3.9: "At most one non-terminal claim per shipment: a second
        filing while an existing claim is SUBMITTED, EVIDENCE_REVIEW,
        APPEALED, or APPROVED rejects with ERR_DUPLICATE_CLAIM (HTTP 409)."

        Design: Corner/validations/duplicate_claim_rejected
        """
        ctx = setup_delivered_shipment(shipment_code="SH-DUP",
                                       dispatch_time="2026-08-12T08:00:00Z",
                                       deliver_time="2026-08-12T13:00:00Z")
        file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                   claim_code="CL-1")
        resp = api.create_temp_abuse_claim(
            {"claim_code": "CL-2", "shipment_id": ctx["shipment"]["id"],
             "declared_value_cents": 40000},
            make_customer_rep_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)

    def test_claim_filed_by_other_customer_rejected(self, api):
        """PRD §2.1: "A CustomerRep filing a temperature-abuse claim must be
        filing against a shipment whose customer_id matches their own id;
        ... Violations are rejected with ERR_NOT_RESOURCE_OWNER
        (HTTP 403)."

        Design: Corner/validations/claim_filed_by_other_customer_rejected
        """
        ctx = setup_delivered_shipment(shipment_code="SH-OW",
                                       dispatch_time="2026-08-12T08:00:00Z",
                                       deliver_time="2026-08-12T13:00:00Z")
        other = create_customer(customer_code="C-B", display_name="Customer B")
        resp = api.create_temp_abuse_claim(
            {"claim_code": "CL-OW", "shipment_id": ctx["shipment"]["id"],
             "declared_value_cents": 50000},
            make_customer_rep_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestOpenReviewGates:
    def test_insufficient_readings_rejected(self, api):
        """PRD §3.9: "The shipment must carry at least 2 temperature
        readings, else ERR_INSUFFICIENT_READINGS"."

        Design: Corner/validations/insufficient_readings_rejected
        """
        ctx = setup_delivered_shipment(
            readings=[
                {"recorded_at": "2026-08-10T09:00:00Z", "temp_c": -16.0},
            ],
            dispatch_time="2026-08-10T08:30:00Z",
            deliver_time="2026-08-10T12:00:00Z",
            shipment_code="SH-IR")
        claim = file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                           claim_code="CL-IR")
        resp = api.open_claim_review(claim["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_READINGS)

    def test_appeal_window_closed_rejected(self, api):
        """PRD §3.9: "provided the current logical clock is no later than
        decided_at plus 14 days (the boundary is inclusive; day 14 still
        appeals). A later appeal rejects with ERR_APPEAL_WINDOW_CLOSED
        (HTTP 422)." Denial at 2026-08-12T13:00 + appeal at
        2026-08-27T13:01 is more than 14 days later.

        Design: Corner/validations/appeal_window_closed_rejected
        """
        ctx = setup_delivered_shipment(
            readings=[
                {"recorded_at": "2026-08-10T09:00:00Z", "temp_c": -19.0},
                {"recorded_at": "2026-08-10T10:00:00Z", "temp_c": -19.0},
            ],
            dispatch_time="2026-08-10T08:30:00Z",
            deliver_time="2026-08-12T13:00:00Z",
            shipment_code="SH-AW")
        claim = file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                           claim_code="CL-AW")
        validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        validate_success(api.deny_claim(claim["id"], ADJUSTER))
        # decided_at is 2026-08-12T13:00 (the logical clock at deny).
        set_clock("2026-08-27T13:01:00Z")
        resp = api.appeal_claim(
            claim["id"], make_customer_rep_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
