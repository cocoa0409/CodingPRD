"""Breadth corners: error-id trigger coverage — payment amount mismatch,
insufficient stock, party guest limit, registry double-link, and OCC stale
version on reschedule."""
from test_helpers import (
    ASSOCIATE,
    ApiErrorId,
    add_party_guests,
    advance_session,
    advance_to_dressed,
    create_customer,
    create_paid_walk_in,
    create_party,
    create_registry,
    create_store,
    create_walk_in_session,
    make_customer_headers,
    pay_party_deposit,
    set_clock,
    setup_workshop_env,
    validate_error,
    validate_success,
)


class TestPaymentAmountMismatch:
    def test_amount_below_total_rejected(self, api):
        """PRD §3.5: "The submitted amount must equal the session's
        `total_price_cents` exactly — any mismatch is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Corner/errors/payment_amount_mismatch_error
        """
        env = setup_workshop_env(
            store_name="Mismatch Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Mm Mole",
                "sku": "MMO-01",
                "base_price_cents": 2500,
                "required_stuffing_grams": 100,
            },
        )
        session = create_walk_in_session(env)
        advance_to_dressed(session["id"])
        validate_error(
            api.pay_workshop(
                session["id"],
                {"payment_amount_cents": 2499, "pay_tender": "CASH"},
                make_customer_headers(env["customer"]["id"]),
            ),
            ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH,
        )


class TestInsufficientStock:
    def test_stuff_advance_rejected_when_fiber_short(self, api):
        """PRD §3.3: "From `SELECTED` to `STUFFED`, the stuffing station consumes
        fiber: the store's `STUFFING_FIBER` ledger must hold at least
        `required_stuffing_grams` on hand, otherwise the advance is rejected with
        `ERR_INSUFFICIENT_STOCK`."

        Design: Corner/errors/insufficient_stuffing_stock_error
        """
        env = setup_workshop_env(
            store_name="Stock Low Store",
            fiber_qty=100,
            chip_qty=None,
            model_overrides={
                "name": "Sloth",
                "sku": "SLO-01",
                "base_price_cents": 2000,
                "required_stuffing_grams": 500,
            },
        )
        session = create_walk_in_session(env)
        advance_session(session["id"])  # SELECT -> SELECTED
        validate_error(
            api.advance_workshop(session["id"], ASSOCIATE),
            ApiErrorId.ERR_INSUFFICIENT_STOCK,
        )


class TestPartyGuestLimit:
    def test_seventh_confirm_over_guest_count_six_rejected(self, api):
        """PRD §3.7: "Confirming a guest requires the reservation to be in `QUOTED`
        or `DEPOSIT_PAID` and the count of `CONFIRMED` guests to be below the
        reservation's `guest_count`; exceeding the booked headcount is rejected with
        `ERR_PARTY_GUEST_LIMIT`."

        Design: Corner/errors/party_guest_limit_error
        """
        store = create_store(name="Limit Store", party_room_count=2)
        customer = create_customer(email="limit@example.com", full_name="Limit L")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-10T18:00:00Z",
            guest_count=6,
            package_tier="BASIC",
            staffing_mode="SELF_GUIDED",
        )
        party = pay_party_deposit(party, customer["id"])
        guests = add_party_guests(
            party["id"], customer["id"], 7, confirm=False, name_prefix="L"
        )
        for guest in guests[:6]:
            validate_success(
                api.confirm_party_guest(
                    guest["id"], make_customer_headers(customer["id"])
                )
            )
        validate_error(
            api.confirm_party_guest(
                guests[6]["id"], make_customer_headers(customer["id"])
            ),
            ApiErrorId.ERR_PARTY_GUEST_LIMIT,
        )


class TestRegistryDoubleLink:
    def test_animal_already_linked_to_another_registry_rejected(self, api):
        """PRD §3.9: "an animal may belong to at most one registry — attempting to
        link an animal already held by another registry, or one not owned by the
        registry owner, is rejected with `ERR_REFERENTIAL_INTEGRITY`."

        Design: Corner/errors/registry_link_animal_twice_rejected
        """
        env = setup_workshop_env(
            store_name="Reg Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Reg Ram",
                "sku": "RRA-01",
                "base_price_cents": 1500,
                "required_stuffing_grams": 100,
            },
        )
        customer = env["customer"]
        _, animal_id = create_paid_walk_in(env)
        headers = make_customer_headers(customer["id"])
        reg1 = create_registry(customer, name="List One")
        reg2 = create_registry(customer, name="List Two")
        validate_success(
            api.link_registry_animal(reg1["id"], {"stuffed_animal_id": animal_id}, headers)
        )
        validate_error(
            api.link_registry_animal(reg2["id"], {"stuffed_animal_id": animal_id}, headers),
            ApiErrorId.ERR_REFERENTIAL_INTEGRITY,
        )


class TestRescheduleOcc:
    def test_stale_expected_version_rejected_with_412(self, api):
        """PRD §2.9: "The request must carry `expected_party_version`, a non-optional
        field holding the client-observed `version` of the reservation. If another
        writer has advanced the reservation's version since the client last read it,
        the value no longer matches the current `version` and the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/reschedule_stale_version_returns_412
        """
        store = create_store(name="OCC Store", party_room_count=2)
        customer = create_customer(email="occ@example.com", full_name="Occ O")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-20T18:00:00Z",
            guest_count=6,
            package_tier="BASIC",
            staffing_mode="SELF_GUIDED",
        )
        party = pay_party_deposit(party, customer["id"])
        current = validate_success(
            api.get_party(party["id"], make_customer_headers(customer["id"]))
        )
        seen_version = current["version"]
        validate_success(
            api.reschedule_party(
                party["id"],
                {
                    "new_party_start": "2026-10-22T18:00:00Z",
                    "expected_party_version": seen_version,
                },
                make_customer_headers(customer["id"]),
            )
        )
        validate_error(
            api.reschedule_party(
                party["id"],
                {
                    "new_party_start": "2026-10-24T18:00:00Z",
                    "expected_party_version": seen_version,
                },
                make_customer_headers(customer["id"]),
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
