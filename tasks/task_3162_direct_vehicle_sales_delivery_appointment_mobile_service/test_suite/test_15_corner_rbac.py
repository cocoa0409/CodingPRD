"""Corner coverage: which role may perform which operation."""
from test_helpers import (
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_appraisal_payload,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    get_success_data,
    set_clock,
    setup_triaged_mobile_appointment,
    validate_error,
    validate_paginated,
    walk_order_to_at_delivery_center,
    walk_order_to_delivered,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]
PARTS = TEST_USERS["parts_coordinator_headers"]
TRADEIN = TEST_USERS["trade_in_specialist_headers"]


def test_platform_admin_can_read_the_catalog_while_buyer_may_only_read_own_order(api):
    """PRD §4: "| GET | `/v1/orders` | List orders | Buyer, PlatformAdmin,
    DeliveryAdvisor, FinancePartner, TradeInSpecialist |"
    PRD §2.1: "Concretely, a `Buyer` may only act on a `VehicleOrder` whose
    `buyer_id` equals their own `X-User-ID`"

    Design: Corner/rbac/platform_admin_can_read_the_catalog_while_buyer_may_only_read_own_order
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])

    rows, meta = validate_paginated(api.list_orders(ADMIN))
    assert meta["total_count"] >= 1

    own = get_success_data(api.get_order(order["id"], {
        "X-User-ID": buyer["id"], "X-User-Role": "Buyer",
        "Content-Type": "application/json"}))
    assert own["id"] == order["id"]


def test_parts_coordinator_cannot_schedule_a_service_bay(api):
    """PRD §2.1: "A request whose role is recognised but is not permitted for the
    requested operation is refused with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "| POST | `/v1/service-appointments/{id}/schedule-center` | Schedule a
    triaged appointment into a service bay | ServiceTechnician |"

    Design: Corner/rbac/parts_coordinator_cannot_schedule_a_service_bay
    """
    set_clock()
    ctx = setup_triaged_mobile_appointment(fault_code="BRK-4400", severity="CRITICAL",
                                           is_driveable=False)

    refused = api.schedule_service_center(
        ctx["appointment"]["id"],
        {"scheduled_start": "2026-09-28T14:00:00Z",
         "scheduled_end": "2026-09-28T16:00:00Z"}, PARTS)
    validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert get_success_data(api.get_service_appointment(
        ctx["appointment"]["id"], TECH))["status"] == "TRIAGED"


def test_finance_partner_cannot_appraise_a_trade_in(api):
    """PRD §4: "| POST | `/v1/orders/{id}/trade-in-appraisals/{id}/appraise` |
    Record the desktop appraisal result | TradeInSpecialist |"
    PRD §3.3: "A trade-in is opened against a specific order by the buyer or by a
    `TradeInSpecialist`."

    Design: Corner/rbac/finance_partner_cannot_appraise_a_trade_in
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    order = ctx["order"]
    appraisal = get_success_data(api.create_appraisal(
        order["id"],
        create_appraisal_payload(trade_vin="5YJ3E1EA7PF000920", mileage=20000,
                                 gross_offer_cents=900000,
                                 reconditioning_estimate_cents=40000,
                                 offer_valid_until="2026-10-15T00:00:00Z"),
        TRADEIN))

    refused = api.appraise(order["id"], appraisal["id"],
                           TEST_USERS["finance_partner_headers"])
    validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert get_success_data(api.get_appraisal(appraisal["id"], TRADEIN))["status"] == "DRAFT"

    accepted = get_success_data(api.appraise(order["id"], appraisal["id"], TRADEIN))
    assert accepted["status"] == "APPRAISED"


def test_delivery_advisor_cannot_revoke_a_software_entitlement(api):
    """PRD §4: "| POST | `/v1/vehicles/{id}/software-entitlements/{id}/revoke` |
    Revoke a purchased entitlement and refund it | PlatformAdmin |"
    PRD §3.11: "A purchased entitlement may also be revoked by a `PlatformAdmin`,
    which requires the row not already to be terminal — otherwise
    `ERR_ALREADY_TERMINAL` (HTTP 409)"

    Design: Corner/rbac/delivery_advisor_cannot_revoke_a_software_entitlement
    """
    set_clock()
    ctx = walk_order_to_delivered()
    vehicle_id = ctx["vehicle"]["id"]
    rows = get_success_data(api.grant_entitlements(
        vehicle_id,
        {"feature_entries": [{"feature_code": "PREMIUM_AUDIO", "price_cents": 300000}],
         "entitlement_source": "PURCHASE"},
        {"X-User-ID": ctx["buyer"]["id"], "X-User-Role": "Buyer",
         "Content-Type": "application/json"}))
    entitlement = rows[0]

    refused = api.revoke_entitlement(vehicle_id, entitlement["id"],
                                     TEST_USERS["delivery_advisor_headers"])
    validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    still = get_success_data(api.get_entitlement(entitlement["id"], ADMIN))
    assert still["status"] == "ACTIVE"

    # The grant itself writes the purchase's DELIVERY_FEE_WAIVER entry (PRD
    # 3.11); what the refused revoke must not add is a second one.
    entries = get_success_data(api.list_order_ledger_entries(ctx["order"]["id"], ADMIN))
    assert len([e for e in entries if e["entry_type"] == "DELIVERY_FEE_WAIVER"
                and e["amount_cents"] == 300000]) == 1, (
        "a refused revoke refunds nothing"
    )


def test_anonymous_cannot_open_an_order(api):
    """PRD §4: "| POST | `/v1/orders` | Open a vehicle order | Buyer, PlatformAdmin |"
    PRD §3.1: "Only the `Anonymous` role may take this action" (account creation)

    Design: Corner/rbac/anonymous_cannot_open_an_order
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()

    refused = api.create_order(
        {"buyer_id": "00000000-0000-4000-8000-000000000002",
         "configuration_id": config["id"], "jurisdiction_id": jur["id"],
         "delivery_center_id": center["id"], "order_fee_cents": 25000},
        TEST_USERS["anonymous_headers"])
    validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    created = get_success_data(api.create_buyer(
        {"full_name": "Anon Visitor", "email": "anon.visitor@example.com",
         "residency_state_code": "TX"}, TEST_USERS["anonymous_headers"]))
    assert created["status"] == "PENDING_VERIFICATION"
