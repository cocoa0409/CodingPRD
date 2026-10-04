"""Order submission gates: error precedence pairs and part-lifecycle gating."""
from test_helpers import (
    EOL_LAST_ORDER_DATE,
    TEST_USERS,
    ApiErrorId,
    get_part,
    make_customer,
    make_customer_headers,
    make_eol_notice,
    make_order,
    make_part,
    make_stocked_priced_part,
    publish_price,
    set_clock,
    submit_order,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


class TestOrderSubmissionGates:
    def test_submit_cancelled_order_state_beats_credit(self, api):
        """PRD §2.8: "When several checks fail on the same request, the failure
        reported is the one belonging to the lowest priority number below — that is,
        the highest-priority failing check wins and determines the response's error
        id."
        PRD §3.4: "Submission is the pivotal act and is permitted only from `DRAFT`;
        a second submission is `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.8 row 5 (state legality) precedes row 10 (quantity and fiscal floors).

        Design: Difficulty/priority_pair_validation_conflict/submit_cancelled_order_state_beats_credit
        """
        part = make_part(part_number="NE555P")
        publish_price(part["id"], unit_price_cents=100)
        cust = make_customer(
            name="Tiny Credit Co", tier="STANDARD", channel="DIRECT_FIELD",
            credit_limit_cents=100,
        )
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 2}])
        cancelled = validate_success(
            api.cancel_order(order["id"], make_customer_headers(cust["id"])), 200
        )
        assert cancelled["status"] == "CANCELLED"

        res = api.submit_order(order["id"], make_customer_headers(cust["id"]))
        err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409
        assert err["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED

        after = validate_success(api.get_order(order["id"], PLANNER), 200)
        assert after["status"] == "CANCELLED"

    def test_credit_limit_breach_on_draft_order_rejected(self, api):
        """PRD §3.2: "The boundary is inclusive — landing exactly on the credit limit
        passes — and a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/submit_cancelled_order_state_beats_credit
        """
        part = make_part(part_number="NE555P2")
        publish_price(part["id"], unit_price_cents=100)
        cust = make_customer(
            name="Tiny Credit Draft", tier="STANDARD", channel="DIRECT_FIELD",
            credit_limit_cents=100,
        )
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 2}])

        res = api.submit_order(order["id"], make_customer_headers(cust["id"]))
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        after = validate_success(api.get_order(order["id"], PLANNER), 200)
        assert after["status"] == "DRAFT"

    def test_submit_discontinued_part_referential_beats_credit(self, api):
        """PRD §2.8: "When several checks fail on the same request, the failure
        reported is the one belonging to the lowest priority number below — that is,
        the highest-priority failing check wins and determines the response's error
        id."
        PRD §3.4: "Every line's part must be orderable — `lifecycle_status` `ACTIVE`,
        `NRND`, or `EOL_ANNOUNCED`; a line on a `LAST_TIME_BUY` or `DISCONTINUED`
        part is rejected with `ERR_PART_NOT_ORDERABLE` (HTTP 422)."
        PRD §2.8 row 9 (referenced-object usability) precedes row 10 (fiscal floors).

        Design: Difficulty/priority_pair_validation_conflict/submit_discontinued_part_referential_beats_credit
        """
        part = make_part(part_number="CD4049BE", process_technology="CMOS_180NM",
                         demand_rate_units_per_week=5)
        publish_price(part["id"], unit_price_cents=50)
        make_eol_notice(part["id"], reason="Process retirement")
        set_clock("2027-05-29T00:00:00Z")  # sweeps the part to DISCONTINUED
        assert get_part(part["id"])["lifecycle_status"] == "DISCONTINUED"

        cust = make_customer(name="Micro Credit LLC", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=1)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 10}])
        res = api.submit_order(order["id"], make_customer_headers(cust["id"]))
        err = validate_error(res, ApiErrorId.ERR_PART_NOT_ORDERABLE)
        assert res.status_code == 422
        assert err["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED

    def test_submit_last_time_buy_part_rejected(self, api):
        """PRD §3.4: "Every line's part must be orderable — `lifecycle_status`
        `ACTIVE`, `NRND`, or `EOL_ANNOUNCED`; a line on a `LAST_TIME_BUY` or
        `DISCONTINUED` part is rejected with `ERR_PART_NOT_ORDERABLE` (HTTP 422)."
        PRD §2.5: "A part in `EOL_ANNOUNCED` advances to `LAST_TIME_BUY` once the
        clock reaches the `last_order_date` of its `ANNOUNCED` end-of-life notice".

        Design: Difficulty/priority_pair_validation_conflict/submit_discontinued_part_referential_beats_credit
        """
        part = make_part(part_number="CD4050BE", process_technology="CMOS_180NM",
                         demand_rate_units_per_week=5)
        publish_price(part["id"], unit_price_cents=50)
        make_eol_notice(part["id"])
        set_clock(EOL_LAST_ORDER_DATE)  # exactly at last_order_date -> LAST_TIME_BUY
        assert get_part(part["id"])["lifecycle_status"] == "LAST_TIME_BUY"

        cust = make_customer(name="Ample Credit", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 10}])
        res = api.submit_order(order["id"], make_customer_headers(cust["id"]))
        validate_error(res, ApiErrorId.ERR_PART_NOT_ORDERABLE)

    def test_order_submit_blocked_when_part_discontinued(self, api):
        """PRD §3.4: "Every line's part must be orderable — `lifecycle_status`
        `ACTIVE`, `NRND`, or `EOL_ANNOUNCED`; a line on a `LAST_TIME_BUY` or
        `DISCONTINUED` part is rejected with `ERR_PART_NOT_ORDERABLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_when_part_discontinued
        """
        part = make_part(part_number="LM741CN", demand_rate_units_per_week=5)
        publish_price(part["id"], unit_price_cents=60)
        make_eol_notice(part["id"], reason="Fab shutdown")
        set_clock("2027-05-29T00:00:00Z")  # DISCONTINUED

        cust = make_customer(name="Ample Credit Co", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 10}])
        res = api.submit_order(order["id"], make_customer_headers(cust["id"]))
        validate_error(res, ApiErrorId.ERR_PART_NOT_ORDERABLE)

        after = validate_success(api.get_order(order["id"], PLANNER), 200)
        assert after["status"] == "DRAFT"
        assert get_part(part["id"])["lifecycle_status"] == "DISCONTINUED"

    def test_submit_eol_announced_before_last_order_date_succeeds(self, api):
        """PRD §3.4: "Every line's part must be orderable — `lifecycle_status`
        `ACTIVE`, `NRND`, or `EOL_ANNOUNCED`; a line on a `LAST_TIME_BUY` or
        `DISCONTINUED` part is rejected with `ERR_PART_NOT_ORDERABLE` (HTTP 422)."
        PRD §3.4: "If a line's part is `EOL_ANNOUNCED`, the logical clock must not be
        past the part's `ANNOUNCED` notice `last_order_date`, else
        `ERR_LAST_ORDER_DATE_PASSED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_when_part_discontinued
        """
        part, _ = make_stocked_priced_part(
            "LM741E", on_hand=100, unit_price_cents=60
        )
        make_eol_notice(part["id"])
        assert get_part(part["id"])["lifecycle_status"] == "EOL_ANNOUNCED"
        # Default clock 2026-09-01 is before last_order_date 2027-02-28.

        cust = make_customer(name="Timely Buyer", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 10}])
        submitted = submit_order(order["id"], cust["id"])
        assert submitted["status"] == "ALLOCATED"
        assert submitted["total_cents"] == 600
