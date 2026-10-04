"""Abuse report and court order corner tests (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    get_domain,
    get_success_data,
    make_abuse_headers,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    setup_active_domain,
    validate_error,
)


class TestAbuseReportCycle:
    def test_requeue_returns_report_to_filed(self, api):
        """PRD §3.6: "An `AbuseAnalyst` then triages it: reviewing moves it
        to `UNDER_REVIEW`, requeueing cycles an under-review report back to
        `FILED`, and resolving an under-review report takes an `action` of
        either `ACTIONED` or `DISMISSED`, both terminal."

        Design: Corner/state_machines/abuse_report_requeue_cycle_returns_to_filed
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-01T00:00:00Z", name="abused-domain")
        abuse = make_abuse_headers()

        resp = api.create_abuse_report(
            {"domain_id": domain["id"],
             "reporter_contact": "user@example.com", "category": "SPAM",
             "detail": "spam farm"},
            abuse,
        )
        report = get_success_data(resp, expected_status=201)
        assert report["status"] == "FILED"

        resp = api.review_abuse_report(report["id"], abuse)
        reviewed = get_success_data(resp)
        assert reviewed["status"] == "UNDER_REVIEW"

        resp = api.requeue_abuse_report(report["id"], abuse)
        requeued = get_success_data(resp)
        assert requeued["status"] == "FILED"

        assert get_domain(domain["id"])["suspension_status"] == "NONE"

        resp = api.review_abuse_report(report["id"], abuse)
        reviewed_again = get_success_data(resp)
        assert reviewed_again["status"] == "UNDER_REVIEW"

    def test_requeue_from_filed_is_invalid_state(self, api):
        """PRD §3.6: "requeueing cycles an under-review report back to
        `FILED`".
        PRD §2.9: "Only then does the system evaluate whether the target
        resource is in a state from which the requested transition exists
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/abuse_report_requeue_cycle_returns_to_filed
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-01T00:00:00Z", name="abused-domain")
        abuse = make_abuse_headers()

        resp = api.create_abuse_report(
            {"domain_id": domain["id"],
             "reporter_contact": "user@example.com", "category": "SPAM",
             "detail": "spam farm"},
            abuse,
        )
        report = get_success_data(resp, expected_status=201)

        # Requeue is only defined from UNDER_REVIEW; from FILED it is an
        # invalid transition.
        resp = api.requeue_abuse_report(report["id"], abuse)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api.review_abuse_report(report["id"], abuse))
        resp = api.requeue_abuse_report(report["id"], abuse)
        assert get_success_data(resp)["status"] == "FILED"


class TestCourtOrderDeferredEnforcement:
    def test_deferred_order_enforces_at_48_hours(self, api):
        """PRD §3.6: "The order is lodged in `LODGED` status; when
        `effective_immediately` is true it is enforced at lodge time,
        otherwise enforcement fires once the logical clock passes forty-eight
        hours after lodging."
        PRD §3.6: "Enforcement effects depend on the action: `SUSPEND` places
        the domain's `suspension_status` on `HOLD`".
        PRD §3.3: "A domain under suspension cannot be renewed: any renewal
        attempt while `suspension_status` is `HOLD` fails with
        `ERR_DOMAIN_SUSPENDED`".

        Design: Corner/state_machines/court_order_deferred_enforcement_at_48_hours
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-29T00:00:00Z", name="court-domain")
        headers = make_operator_headers(registrar["id"])

        resp = api.create_court_order(
            {"case_reference": "CASE-2026-001", "domain_id": domain["id"],
             "action": "SUSPEND", "effective_immediately": False},
            make_admin_headers(),
        )
        order = get_success_data(resp, expected_status=201)
        assert order["status"] == "LODGED"

        # +47h: still lodged, no suspension yet.
        set_clock("2027-04-30T23:00:00Z")
        resp = api.get_court_order(order["id"], make_admin_headers())
        at_47h = get_success_data(resp)
        assert at_47h["status"] == "LODGED"
        assert get_domain(domain["id"])["suspension_status"] == "NONE"

        # +48h1s: enforced, domain on HOLD, renewal blocked.
        set_clock("2027-05-01T00:00:01Z")
        resp = api.get_court_order(order["id"], make_admin_headers())
        at_48h = get_success_data(resp)
        assert at_48h["status"] == "ENFORCED"
        assert get_domain(domain["id"])["suspension_status"] == "HOLD"

        resp = api.renew_domain(domain["id"], 1, headers)
        validate_error(resp, ApiErrorId.ERR_DOMAIN_SUSPENDED)

    def test_immediate_order_enforced_at_lodge_time(self, api):
        """PRD §3.6: "The order is lodged in `LODGED` status; when
        `effective_immediately` is true it is enforced at lodge time,
        otherwise enforcement fires once the logical clock passes forty-eight
        hours after lodging."
        PRD §3.6: "Once enforced, an order's `status` is `ENFORCED` and
        final."

        Design: Corner/state_machines/court_order_deferred_enforcement_at_48_hours
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-29T00:00:00Z", name="court-domain")

        resp = api.create_court_order(
            {"case_reference": "CASE-2026-002", "domain_id": domain["id"],
             "action": "SUSPEND", "effective_immediately": True},
            make_admin_headers(),
        )
        order = get_success_data(resp, expected_status=201)
        assert order["status"] == "ENFORCED", (
            "an effective_immediately order is enforced at lodge time"
        )
        assert get_domain(domain["id"])["suspension_status"] == "HOLD"

        resp = api.get_court_order(order["id"], make_admin_headers())
        assert get_success_data(resp)["status"] == "ENFORCED"
