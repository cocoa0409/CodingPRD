"""Pickup-event dispute cycle and rate-notice cancellation ordering tests."""
from test_helpers import (
    ApiErrorId,
    set_clock,
    make_customer,
    make_contract,
    add_service_line,
    activate_contract,
    make_fixed_config,
    make_pickup_event,
    make_rate_notice,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS, make_customer_headers

OPS = TEST_USERS["ops_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestPickupDisputeRedisputeCycle:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(
            effective_from="2026-09-01T00:00:00Z", contamination_fee_cents=15000,
        )
        customer = make_customer(legal_name="Cycle Co", billing_email="c@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(
            contract["id"], container_size="CY_4",
            frequency_per_week=3, base_rate_cents=200000,
        )
        activate_contract(contract["id"])
        set_clock("2026-09-02T12:00:00Z")
        event = make_pickup_event(
            line["id"], "2026-09-02", "CONTAMINATED",
            photo_evidence_url="https://img.example/p1.jpg",
        )
        return customer, event

    def test_one_appeal_then_no_further_disputes(self, api):
        """PRD section 3.5: "The customer gets exactly one appeal: from
        `RESOLVED_UPHELD` the customer may dispute again, but only while
        `appeal_count` is still 0; that re-dispute returns the event to
        `DISPUTED` and sets `appeal_count` to 1, after which no further
        disputes of that event are possible (a further attempt is rejected with
        `ERR_INVALID_STATE`)."

        Design: Difficulty/non_linear_state_machine/pickup_dispute_redispute_cycle
        """
        customer, event = self._setup()
        cust_headers = make_customer_headers(customer["id"])

        disputed = validate_success(
            api.dispute_pickup_event(event["id"], cust_headers)
        )
        assert disputed["dispute_status"] == "DISPUTED"

        upheld = validate_success(
            api.resolve_pickup_dispute(event["id"], "UPHELD", OPS)
        )
        assert upheld["dispute_status"] == "RESOLVED_UPHELD"

        redisputed = validate_success(
            api.dispute_pickup_event(event["id"], cust_headers)
        )
        assert redisputed["dispute_status"] == "DISPUTED"
        assert redisputed["appeal_count"] == 1

        upheld2 = validate_success(
            api.resolve_pickup_dispute(event["id"], "UPHELD", OPS)
        )
        assert upheld2["dispute_status"] == "RESOLVED_UPHELD"
        assert upheld2["appeal_count"] == 1

        # Third dispute: appeal already consumed.
        resp = api.dispute_pickup_event(event["id"], cust_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fee_unchanged_throughout_dispute_cycle(self, api):
        """PRD section 3.5: "A resolution of `UPHELD` moves the event from
        `DISPUTED` to `RESOLVED_UPHELD` and keeps the fees in place."

        Design: Difficulty/non_linear_state_machine/pickup_dispute_redispute_cycle
        """
        customer, event = self._setup()
        cust_headers = make_customer_headers(customer["id"])
        validate_success(api.dispute_pickup_event(event["id"], cust_headers))
        validate_success(api.resolve_pickup_dispute(event["id"], "UPHELD", OPS))
        validate_success(api.dispute_pickup_event(event["id"], cust_headers))
        final = validate_success(
            api.resolve_pickup_dispute(event["id"], "UPHELD", OPS)
        )
        assert final["contamination_fee_cents"] == 15000, (
            "UPHELD keeps the fees in place throughout the dispute cycle"
        )


class TestTerminalStateVsWindowExpiredOnNoticeCancel:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Prio2 Co", billing_email="p2@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        notice = make_rate_notice(
            contract["id"], pct_increase=0.05,
            effective_date="2026-09-10T00:00:00Z",
        )
        set_clock("2026-09-12T00:00:00Z")
        return customer, contract, line, notice

    def test_cancel_applied_notice_is_invalid_state_not_window_expired(self, api):
        """PRD section 2.10: "fifth state admissibility of the target resource
        (`ERR_INVALID_STATE`, HTTP 409); ... seventh business time-window rules
        (`ERR_WINDOW_EXPIRED`, HTTP 422)".
        PRD section 2.10: "A request that violates more than one rule is
        rejected with the error belonging to the earliest applicable priority
        in this ordering."
        PRD section 3.3: "Both `APPLIED` and `CANCELLED` are terminal."

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_vs_window_expired_on_notice_cancel
        """
        customer, contract, line, notice = self._setup()
        applied = validate_success(api.get_rate_notice(notice["id"], OPS))
        assert applied["status"] == "APPLIED"

        resp = api.cancel_rate_notice(notice["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_rate_notice(notice["id"], OPS))
        assert after["status"] == "APPLIED"

    def test_application_not_rolled_back_by_failed_cancel(self, api):
        """PRD section 3.3: "for every service line on the contract, the line's
        `base_rate_cents` is replaced by its previous value multiplied by one
        plus the `pct_increase`, rounded half-up to a whole cent."
        PRD section 3.3: "Application moves the notice from `SCHEDULED` to
        `APPLIED`."

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_vs_window_expired_on_notice_cancel
        """
        customer, contract, line, notice = self._setup()
        resp = api.cancel_rate_notice(notice["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        line_after = validate_success(api.get_service_line(line["id"], OPS))
        assert line_after["base_rate_cents"] == 105000, (
            "the applied rate change must not be rolled back by the rejected "
            f"cancel, got {line_after['base_rate_cents']}"
        )
