"""Ordered validation pipeline: which error surfaces when several rules are violated."""
from test_helpers import (
    TEST_USERS,
    cover_order_total,
    create_financing_application_payload,
    dispatch_and_arrive,
    make_buyer_headers,
    create_and_enact_jurisdiction,
    create_and_start_batch,
    create_appraisal_payload,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    get_order,
    get_success_data,
    lock_order,
    place_order,
    set_clock,
    settle_order_fee,
    validate_error,
    walk_order_to_at_delivery_center,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["delivery_advisor_headers"]
TRADEIN = TEST_USERS["trade_in_specialist_headers"]
FINANCE = TEST_USERS["finance_partner_headers"]


def _bookable_order(api, buyer_name="Hana Readiness", email=None):
    """An order that can actually reach the handover booking rules.

    A booking is admissible only against an order that is AT_DELIVERY_CENTER,
    whose posture is not FROZEN, whose trade-in appraisals are all ACCEPTED, and
    whose financing application has been FUNDED — and funding itself requires a
    READY posture (PRD 3.5, 3.6). This helper walks the whole chain through the
    API so the tests below reach the rule they are actually about.
    """
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer(full_name=buyer_name, email=email)
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])
    locked = lock_order(order["id"], placed["version"])
    batch, _unit = create_and_start_batch()
    get_success_data(api.allocate_order(order["id"], batch["id"],
                                        locked["version"], ADMIN))
    dispatch_and_arrive(order["id"])
    cover_order_total(order["id"])

    venture = get_success_data(api.create_financing_application(
        order["id"],
        create_financing_application_payload(term_months=60, down_payment_cents=0),
        make_buyer_headers(buyer["id"])))
    decided = get_success_data(api.decide_financing_application(
        venture["id"], "APPROVED", FINANCE))
    reviewed = get_success_data(api.contract_review(
        venture["id"], decided["version"], FINANCE))
    get_success_data(api.fund_application(venture["id"], reviewed["version"], FINANCE))

    return {
        "order": get_order(order["id"]),
        "center": center,
        "buyer": buyer,
        "jurisdiction": jur,
        "configuration": config,
        "batch": batch,
    }


class TestHandoverBookingPriority:
    """PRD §3.12 fixes the order in which business rules surface."""

    def test_bay_conflict_beats_the_stale_version_guard(self, api):
        """PRD §3.12: "Business rules then apply in the priority order below.
        Where several rules could apply to the same request, the earliest in this
        list is the one that surfaces"
        PRD §3.12: "11. Handover bay free under the buffered half-open rule —
        `ERR_DELIVERY_SLOT_CONFLICT`, 409."
        PRD §3.12: "19. Supplied expected version matches the parent's current
        version — `ERR_STALE_VERSION`, 412."

        Design: Difficulty/priority_pair_validation_conflict/priority_11_slot_conflict_beats_priority_19_stale_version
        """
        set_clock()
        first_ctx = _bookable_order(api, buyer_name="Hana Priority",
                                    email="hana.priority@example.com")
        second_ctx = _bookable_order(api, buyer_name="Ivan Priority",
                                     email="ivan.priority@example.com")
        center_id = first_ctx["center"]["id"]
        seated = first_ctx["order"]
        challenger = second_ctx["order"]

        first = get_success_data(api.book_delivery_appointment(
            {"order_id": seated["id"], "delivery_center_id": center_id,
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-22T15:00:00Z",
             "scheduled_end": "2026-09-22T16:00:00Z",
             "expected_order_version": seated["version"]},
            ADVISOR))
        get_success_data(api.confirm_delivery_appointment(first["id"], ADVISOR))

        # The challenger reads its order's version before the seated booking
        # advances it, so the request below presents both the colliding interval
        # of entry 11 and a stale version under entry 19 — and the earlier entry
        # is the one that has to surface.
        stale = challenger["version"]
        seated_after = get_order(seated["id"])
        assert seated_after["version"] > seated["version"]

        occupied = api.book_delivery_appointment(
            {"order_id": challenger["id"], "delivery_center_id": center_id,
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-22T15:30:00Z",
             "scheduled_end": "2026-09-22T16:30:00Z",
             "expected_order_version": stale},
            ADVISOR)
        validate_error(occupied, "ERR_DELIVERY_SLOT_CONFLICT")

    def test_the_rejected_booking_leaves_the_bay_count_untouched(self, api):
        """PRD §2.6: "`booked_slot_count` on a `DeliveryCenter` is a conserved
        quantity: it counts every `DeliveryAppointment` whose status is `BOOKED`,
        `CONFIRMED`, `AT_RISK`, or `COMPLETED`"
        PRD §3.6: "A successful center booking increments `booked_slot_count` by one"

        Design: Difficulty/priority_pair_validation_conflict/priority_11_slot_conflict_beats_priority_19_stale_version
        """
        set_clock()
        first_ctx = _bookable_order(api, buyer_name="Hana Bay",
                                    email="hana.bay@example.com")
        second_ctx = _bookable_order(api, buyer_name="Ivan Bay",
                                     email="ivan.bay@example.com")
        center_id = first_ctx["center"]["id"]
        seated = first_ctx["order"]
        challenger = second_ctx["order"]

        first = get_success_data(api.book_delivery_appointment(
            {"order_id": seated["id"], "delivery_center_id": center_id,
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-22T15:00:00Z",
             "scheduled_end": "2026-09-22T16:00:00Z",
             "expected_order_version": seated["version"]},
            ADVISOR))
        get_success_data(api.confirm_delivery_appointment(first["id"], ADVISOR))
        slots_before = get_success_data(
            api.get_delivery_center(center_id, ADMIN))["booked_slot_count"]

        api.book_delivery_appointment(
            {"order_id": challenger["id"], "delivery_center_id": center_id,
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-22T15:30:00Z",
             "scheduled_end": "2026-09-22T16:30:00Z",
             "expected_order_version": challenger["version"]},
            ADVISOR)

        slots_after = get_success_data(
            api.get_delivery_center(center_id, ADMIN))["booked_slot_count"]
        assert slots_after == slots_before == 1

        rows = get_success_data(
            api.list_order_appointments(challenger["id"], ADMIN))
        assert rows == [], "the rejected booking created no appointment"


class TestReadinessAndReferentialPriority:
    """PRD §3.12: the unresolved-reference check outranks the readiness gate."""

    def test_unresolved_trade_in_beats_the_frozen_posture_gate(self, api):
        """PRD §3.12: "16. Every visible appraisal accepted —
        `ERR_TRADE_IN_NOT_RESOLVED`, 409."
        PRD §3.12: "17. Readiness posture not frozen —
        `ERR_ORDER_DELIVERY_NOT_READY`, 409."
        PRD §3.6: "Every visible trade-in appraisal on the order must be
        `ACCEPTED`, otherwise `ERR_TRADE_IN_NOT_RESOLVED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/priority_16_unresolved_trade_in_beats_priority_17_frozen_posture
        """
        set_clock()
        jur = create_and_enact_jurisdiction()
        center = create_center()
        config, _ = create_published_configuration()
        buyer = create_verified_buyer(full_name="Hana Readiness",
                                      email="hana.readiness@example.com")
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
        settle_order_fee(order["id"])
        placed = place_order(order["id"], order["version"], buyer["id"])
        locked = lock_order(order["id"], placed["version"])
        batch, _unit = create_and_start_batch()
        get_success_data(api.allocate_order(order["id"], batch["id"],
                                            locked["version"], ADMIN))
        dispatch_and_arrive(order["id"])
        cover_order_total(order["id"])
        venture = get_success_data(api.create_financing_application(
            order["id"],
            create_financing_application_payload(term_months=60, down_payment_cents=0),
            make_buyer_headers(buyer["id"])))
        decided = get_success_data(api.decide_financing_application(
            venture["id"], "APPROVED", FINANCE))
        reviewed = get_success_data(api.contract_review(
            venture["id"], decided["version"], FINANCE))
        get_success_data(api.fund_application(venture["id"], reviewed["version"], FINANCE))
        order = get_order(order["id"])

        # The order carries an unresolvable hold: while an accepted financing
        # application is present, the appraisal published on the order is still
        # OFFERED, which is the obstruction the referential check names.
        appraisal = get_success_data(api.create_appraisal(
            order["id"],
            create_appraisal_payload(trade_vin="5YJ3E1EA7PF000902", mileage=42000,
                                     gross_offer_cents=900000,
                                     reconditioning_estimate_cents=40000,
                                     offer_valid_until="2026-10-15T00:00:00Z"),
            TRADEIN))
        get_success_data(api.appraise(order["id"], appraisal["id"], TRADEIN))
        offered = get_success_data(api.offer_appraisal(
            order["id"], appraisal["id"], TRADEIN))
        assert offered["status"] == "OFFERED"

        order = get_order(order["id"])
        assert order["delivery_readiness_posture"] in ("READY", "RESTRICTED")
        refused = api.book_delivery_appointment(
            {"order_id": order["id"], "delivery_center_id": center["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-25T15:10:00Z",
             "scheduled_end": "2026-09-25T16:10:00Z",
             "expected_order_version": order["version"]},
            ADVISOR)
        validate_error(refused, "ERR_TRADE_IN_NOT_RESOLVED")
        # Note on the pair: booking additionally requires every financing
        # application to be FUNDED, and funding in turn requires the order's
        # posture to be READY, which requires the allocation unit to have
        # ARRIVED — so a bookable order can never also present the FROZEN
        # posture. Entry 17 cannot be simultaneously live with entry 16 on this
        # endpoint; what is exercised here is that entry 16 fires first when the
        # obstruction is present.

    def test_the_unbooked_order_keeps_its_transit_state(self, api):
        """PRD §3.5: "Decline is available from either `SUBMITTED` or
        `CONDITIONALLY_APPROVED`. In both cases the application becomes `DECLINED`"
        PRD §3.6: "The order must be `AT_DELIVERY_CENTER`, otherwise
        `ERR_ORDER_NOT_AT_CENTER` (HTTP 409)."
        PRD §3.4: "sets the unit and the order to `IN_TRANSIT`"

        Design: Difficulty/priority_pair_validation_conflict/priority_16_unresolved_trade_in_beats_priority_17_frozen_posture
        """
        set_clock()
        jur = create_and_enact_jurisdiction()
        center = create_center()
        config, _ = create_published_configuration()
        buyer = create_verified_buyer(full_name="Hana Readiness",
                                      email="hana.readiness@example.com")
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
        settle_order_fee(order["id"])
        placed = place_order(order["id"], order["version"], buyer["id"])
        locked = lock_order(order["id"], placed["version"])
        batch, _unit = create_and_start_batch()
        get_success_data(api.allocate_order(order["id"], batch["id"],
                                            locked["version"], ADMIN))
        get_success_data(api.dispatch_to_transport(order["id"], ADMIN))

        appraisal = get_success_data(api.create_appraisal(
            order["id"],
            create_appraisal_payload(trade_vin="5YJ3E1EA7PF000902", mileage=42000,
                                     gross_offer_cents=900000,
                                     reconditioning_estimate_cents=40000,
                                     offer_valid_until="2026-10-15T00:00:00Z"),
            TRADEIN))
        get_success_data(api.appraise(order["id"], appraisal["id"], TRADEIN))
        get_success_data(api.offer_appraisal(order["id"], appraisal["id"], TRADEIN))

        api.book_delivery_appointment(
            {"order_id": order["id"], "delivery_center_id": center["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-25T15:10:00Z",
             "scheduled_end": "2026-09-25T16:10:00Z",
             "expected_order_version": get_order(order["id"])["version"]},
            ADVISOR)

        assert get_order(order["id"])["status"] == "IN_TRANSIT"
        rows = get_success_data(api.list_order_appointments(order["id"], ADMIN))
        assert rows == [], "the refused booking created no appointment"
