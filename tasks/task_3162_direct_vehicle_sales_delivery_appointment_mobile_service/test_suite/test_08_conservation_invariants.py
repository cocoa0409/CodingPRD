"""Conserved quantities: money on the ledger and bays at a site."""
from test_helpers import (
    TEST_USERS,
    assert_ledger_conservation,
    create_and_enact_jurisdiction,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    dispatch_mobile_visit,
    get_success_data,
    place_order,
    set_clock,
    settle_order_fee,
    setup_triaged_mobile_appointment,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]


class TestOrderCancellationLedger:
    """PRD §3.8: cancellation returns the fee less a retained charge."""

    def test_cancellation_settles_the_buyer_balance_at_the_retained_charge(self, api):
        """PRD §3.8: "a compensating ledger entry of type `ORDER_FEE_REFUND` is
        written with `amount_cents` of negative 20000 cents, and the buyer's
        `order_credit_balance_cents` is recomputed."
        PRD §3.8: "In ledger terms, a buyer who paid the 25000-cent fee and then
        cancelled outright settles with an `order_credit_balance_cents` of exactly
        5000 — the difference between the payment and the refund"

        Design: Difficulty/compensating_invariant/order_cancellation_conserves_buyer_credit_balance
        """
        set_clock()
        jur = create_and_enact_jurisdiction()
        center = create_center()
        config, _ = create_published_configuration()
        buyer = create_verified_buyer(full_name="Lena Ledger",
                                      email="lena.ledger@example.com")
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
        settle_order_fee(order["id"])
        place_order(order["id"], order["version"], buyer["id"])

        before = get_success_data(api.get_buyer(buyer["id"], ADMIN))
        assert before["order_credit_balance_cents"] == 25000

        cancelled = get_success_data(api.cancel_order(
            order["id"], {"X-User-ID": buyer["id"], "X-User-Role": "Buyer",
                          "Content-Type": "application/json"}))
        assert cancelled["status"] == "CANCELLED"

        after = get_success_data(api.get_buyer(buyer["id"], ADMIN))
        assert after["order_credit_balance_cents"] == 5000

    def test_the_ledger_is_conserved_against_the_buyer_balance(self, api):
        """PRD §2.8: "`order_credit_balance_cents` — the sum of `amount_cents`
        across all entries whose `buyer_id` is that buyer"
        PRD §2.8: "Entries are append-only: a mistake is corrected by writing a
        compensating entry of the opposite sign under the matching reversal type,
        never by editing or deleting the original."

        Design: Difficulty/compensating_invariant/order_cancellation_conserves_buyer_credit_balance
        """
        set_clock()
        jur = create_and_enact_jurisdiction()
        center = create_center()
        config, _ = create_published_configuration()
        buyer = create_verified_buyer(full_name="Lena Ledger",
                                      email="lena.ledger@example.com")
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
        settle_order_fee(order["id"])
        place_order(order["id"], order["version"], buyer["id"])

        get_success_data(api.cancel_order(
            order["id"], {"X-User-ID": buyer["id"], "X-User-Role": "Buyer",
                          "Content-Type": "application/json"}))

        entries = get_success_data(api.list_order_ledger_entries(order["id"], ADMIN))
        kinds = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert kinds["ORDER_FEE_PAYMENT"] == 25000
        assert kinds["ORDER_FEE_REFUND"] == -20000
        assert sum(e["amount_cents"] for e in entries) == 5000

        buyer_after = get_success_data(api.get_buyer(buyer["id"], ADMIN))
        assert_ledger_conservation(buyer_after, entries)


class TestMobileCancellationBayConservation:
    """PRD §3.10: a mobile dispatch occupies no bay and returns cleanly."""

    def test_cancelling_a_mobile_visit_returns_the_appointment_to_triage(self, api):
        """PRD §3.10: "Cancellation is available while the visit is not already
        terminal — otherwise `ERR_ALREADY_TERMINAL` (HTTP 409) — and it returns the
        linked appointment to `TRIAGED` and clears the vehicle's hold to `NONE`."

        Design: Difficulty/compensating_invariant/mobile_visit_cancellation_conserves_center_booked_slot_count
        """
        set_clock()
        ctx = setup_triaged_mobile_appointment(fault_code="SUS-3300", severity="MEDIUM")
        visit = dispatch_mobile_visit(ctx["appointment"]["id"], ctx["hub"]["id"],
                                      ctx["appointment"]["version"],
                                      labor_hours=2.0, parts_cost_cents=18000,
                                      visit_miles=20)

        get_success_data(api.cancel_mobile_visit(visit["id"], TECH))

        final_visit = get_success_data(api.get_mobile_visit(visit["id"], TECH))
        assert final_visit["status"] == "CANCELLED"
        appointment = get_success_data(api.get_service_appointment(
            ctx["appointment"]["id"], TECH))
        assert appointment["status"] == "TRIAGED"

    def test_a_mobile_dispatch_leaves_the_center_bay_count_unchanged(self, api):
        """PRD §3.9: "On success the appointment becomes `CENTER_SCHEDULED`, the site's
        `booked_slot_count` is incremented, the new window is written to
        `scheduled_start` and `scheduled_end`"
        PRD §2.6: "`booked_slot_count` on a `DeliveryCenter` is a conserved
        quantity: it counts every `DeliveryAppointment` whose status is `BOOKED`,
        `CONFIRMED`, `AT_RISK`, or `COMPLETED`, plus every `ServiceAppointment`
        whose status is `CENTER_SCHEDULED` or `COMPLETED`."

        Design: Difficulty/compensating_invariant/mobile_visit_cancellation_conserves_center_booked_slot_count
        """
        set_clock()
        holder = setup_triaged_mobile_appointment(fault_code="BRK-4400",
                                                  severity="CRITICAL",
                                                  is_driveable=False)
        get_success_data(api.schedule_service_center(
            holder["appointment"]["id"],
            {"scheduled_start": "2026-09-29T14:00:00Z",
             "scheduled_end": "2026-09-29T16:00:00Z"},
            TECH))
        before = get_success_data(
            api.get_delivery_center(holder["service_center"]["id"], ADMIN))
        assert before["booked_slot_count"] == 1

        mobile = setup_triaged_mobile_appointment(fault_code="SUS-3300",
                                                  severity="MEDIUM",
                                                  center_kind="SERVICE_CENTER")
        # Re-point the mobile scenario's appointment at the same service center.
        center_id = holder["service_center"]["id"]
        appointment = get_success_data(api.create_service_appointment(
            {"vehicle_id": mobile["vehicle"]["id"],
             "diagnostic_report_id": mobile["report"]["id"],
             "service_center_id": center_id,
             "scheduled_start": "2026-09-29T16:00:00Z",
             "scheduled_end": "2026-09-29T18:00:00Z"},
            TECH))

        visit = dispatch_mobile_visit(appointment["id"], mobile["hub"]["id"],
                                      appointment["version"],
                                      labor_hours=2.0, parts_cost_cents=18000,
                                      visit_miles=20)
        during = get_success_data(api.get_delivery_center(center_id, ADMIN))
        assert during["booked_slot_count"] == 1, "a mobile dispatch occupies no bay"

        get_success_data(api.cancel_mobile_visit(visit["id"], TECH))
        after = get_success_data(api.get_delivery_center(center_id, ADMIN))
        assert after["booked_slot_count"] == 1, (
            "the cancellation restored the appointment without disturbing the held bay"
        )
        assert get_success_data(api.get_service_appointment(
            holder["appointment"]["id"], TECH))["status"] == "CENTER_SCHEDULED"
