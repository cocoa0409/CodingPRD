"""Membership lifecycle: enrollment, grace/renewal cycle, cancellation window."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_member,
    assert_member_savings_invariants,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    setup_gallery,
    setup_member,
    setup_product,
    setup_member_quote_with_consultation,
    create_member_quote,
    add_line,
    set_clock,
    run_daily_cycle,
    create_design_consultation_payload,
    create_member_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]
ANON = TEST_USERS["anonymous_headers"]


class TestMemberEnrollment:

    def test_enrollment_charges_fee_and_sets_period(self, api):
        """PRD §3.1: "Enrollment charges the annual membership fee of 17500 cents, records it in `fee_paid_total_cents`, stamps `current_period_start` with the current logical clock time, and sets `current_period_end` to exactly 365 days later. The new member enters in `ACTIVE` status."
        PRD §2.7: "A member's own `pricing_tier` field is computed the same way: `MEMBER` while `status` is `ACTIVE` or `GRACE`, `RETAIL` otherwise."
        PRD §3.1: "`lifetime_net_savings_cents`, which is always exactly `lifetime_gross_savings_cents` minus `fee_paid_total_cents`."

        Design: Corner/entities/member_creation_charges_fee_and_sets_period
        """
        member = setup_member(email="c1@x.com", full_name="C One")
        assert_member(member)
        assert member["status"] == "ACTIVE"
        assert member["fee_paid_total_cents"] == 17500
        assert member["current_period_end"] == "2027-09-01T00:00:00.000Z"
        assert member["pricing_tier"] == "MEMBER"
        assert member["lifetime_gross_savings_cents"] == 0
        assert member["lifetime_net_savings_cents"] == -17500
        assert_member_savings_invariants(member)

    def test_duplicate_member_email_rejected(self, api):
        """PRD §3.1: "The email must be unique across all members — a duplicate is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409)."

        Design: Corner/validations/duplicate_member_email_rejected
        """
        get_success_data(
            api.create_member(
                create_member_payload(email="dup@x.com", full_name="First"), ANON
            )
        )
        resp = api.create_member(
            create_member_payload(email="dup@x.com", full_name="Second", auto_renew=True),
            ANON,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


class TestMemberGraceRenewalCycle:

    def test_grace_transition_and_renewal_closes_cycle(self, api):
        """PRD §3.1: "if `auto_renew` is not set, the member moves from `ACTIVE` to `GRACE` and `grace_end` is set to 30 days after the period end."
        PRD §3.1: "Renewal from `GRACE` requires `status` to be exactly `GRACE` and supplies a fresh `payment_token`; it charges 17500 cents, restarts the period at the current clock time rather than at the old boundary (`current_period_start` becomes the clock, `current_period_end` becomes 365 days later), clears `grace_end` to null, and returns the member to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/member_grace_renewal_cycle
        """
        member = setup_member(email="m4@x.com", full_name="M Four", auto_renew=False)
        mid = member["id"]
        set_clock("2027-09-02T00:00:00Z")
        run_daily_cycle()
        after_cycle = get_success_data(api.get_member(mid, ADMIN))
        assert after_cycle["status"] == "GRACE"
        assert after_cycle["grace_end"] == "2027-10-01T00:00:00.000Z"

        renewed = validate_success(
            api.renew_member(mid, {"payment_token": "tok2"}, make_member_headers(mid))
        )
        assert renewed["status"] == "ACTIVE"
        assert renewed["current_period_start"] == "2027-09-02T00:00:00.000Z"
        assert renewed["fee_paid_total_cents"] == 35000
        assert renewed.get("grace_end") is None
        assert_member_savings_invariants(renewed)

    def test_renew_rejected_when_not_in_grace(self, api):
        """PRD §3.1: "A renewal attempt against a member not in `GRACE` is rejected as an invalid state."

        Design: Difficulty/non_linear_state_machine/member_grace_renewal_cycle
        """
        member = setup_member(auto_renew=False)
        mid = member["id"]
        resp = api.renew_member(mid, {"payment_token": "tok2"}, make_member_headers(mid))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestMemberCancellationWindow:

    def test_cancel_at_day30_exactly_refunds(self, api):
        """PRD §3.1: "if the clock is at or before 30 days after `current_period_start` — the window is inclusive of day 30 — the current period's fee of 17500 cents is refunded, `fee_paid_total_cents` is reduced by 17500, and the member ends in `CANCELLED_REFUNDED`"

        Design: Difficulty/boundary_precision_check/cancellation_window_day30_inclusive
        """
        member = setup_member(email="ma@x.com", full_name="M A")
        set_clock("2026-10-01T00:00:00Z")
        cancelled = validate_success(
            api.cancel_member(member["id"], make_member_headers(member["id"]))
        )
        assert cancelled["status"] == "CANCELLED_REFUNDED"
        assert cancelled["fee_paid_total_cents"] == 0
        assert_member_savings_invariants(cancelled)

    def test_cancel_one_second_after_day30_no_refund(self, api):
        """PRD §3.1: "if the clock is past that point, no refund is given and the member ends in `CANCELLED`."

        Design: Difficulty/boundary_precision_check/cancellation_window_day30_inclusive
        """
        member = setup_member(email="mb@x.com", full_name="M B")
        set_clock("2026-10-01T00:00:01Z")
        cancelled = validate_success(
            api.cancel_member(member["id"], make_member_headers(member["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["fee_paid_total_cents"] == 17500
        assert_member_savings_invariants(cancelled)


class TestMemberLapseCascade:

    def test_lapse_cancels_consultation_and_reprices_quote(self, api):
        """PRD §3.1: "First (Cascade A hop 2), every design consultation belonging to this member that is still `SCHEDULED` is cancelled."
        PRD §3.1: "Third (hop 2b), every order belonging to this member that is still in `QUOTE` is re-priced under the `RETAIL` track — per-line pricing and the order total are recomputed with retail rates, while the frozen `quote_total_cents` snapshot is left unchanged."

        Design: Difficulty/transitive_cascade/member_lapse_consultation_order_cascade
        """
        gallery = setup_gallery(name="Gallery G")
        member = setup_member(email="m6@x.com", full_name="M Six", auto_renew=False)
        product = setup_product(list_price_cents=100000, line_kind="STOCK")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=1, headers=headers)
        consultation = get_success_data(
            api.create_design_consultation(
                create_design_consultation_payload(
                    member["id"], order["id"], scheduled_at="2026-09-03T10:00:00Z"
                ),
                headers,
            )
        )
        set_clock("2027-10-02T00:00:00Z")
        run_daily_cycle()

        member_after = get_success_data(api.get_member(member["id"], ADMIN))
        assert member_after["status"] == "LAPSED"

        consultation_after = get_success_data(
            api.get_design_consultation(consultation["id"], ADMIN)
        )
        assert consultation_after["status"] == "CANCELLED"

        order_after = get_success_data(api.get_order(order["id"], ADMIN))
        assert order_after["pricing_tier"] == "RETAIL"
        assert order_after["total_cents"] == 119900
        assert order_after["quote_total_cents"] == 94900

    def test_lapse_removes_cancelled_consultations_extension_from_quote(self, api):
        """PRD §3.1: "if that order is still in `QUOTE`, its `quote_expires_at` is recomputed as the order's `created_at` plus 14 days plus 14 days for each of the order's remaining `COMPLETED` consultations, and `consultation_extensions_used` is recomputed to match."

        Design: Difficulty/transitive_cascade/member_lapse_consultation_order_cascade
        """
        gallery = setup_gallery(name="Gallery G2")
        member = setup_member(email="m6b@x.com", full_name="M Six B", auto_renew=False)
        product = setup_product(list_price_cents=100000, line_kind="STOCK")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=1, headers=headers)
        # One consultation completed (extends quote to 2026-09-29), one still scheduled.
        completed = get_success_data(
            api.create_design_consultation(
                create_design_consultation_payload(
                    member["id"], order["id"], scheduled_at="2026-09-03T10:00:00Z"
                ),
                headers,
            )
        )
        get_success_data(
            api.complete_design_consultation(
                completed["id"], {"design_plan_notes": "done"}, ASSOCIATE
            )
        )
        scheduled = get_success_data(
            api.create_design_consultation(
                create_design_consultation_payload(
                    member["id"], order["id"], scheduled_at="2026-09-04T10:00:00Z"
                ),
                headers,
            )
        )
        set_clock("2027-10-02T00:00:00Z")
        run_daily_cycle()

        consultation_after = get_success_data(
            api.get_design_consultation(scheduled["id"], ADMIN)
        )
        assert consultation_after["status"] == "CANCELLED"

        order_after = get_success_data(api.get_order(order["id"], ADMIN))
        assert order_after["status"] == "QUOTE"
        assert order_after["quote_expires_at"] == "2026-09-29T00:00:00.000Z"
        assert order_after["consultation_extensions_used"] == 1
