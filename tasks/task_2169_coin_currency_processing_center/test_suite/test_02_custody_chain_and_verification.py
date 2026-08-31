"""The armored drop: sealed bags, chain-of-custody hops and drop verification."""

from test_helpers import (
    ApiErrorId,
    CARRIER_1,
    MANAGER_1,
    TELLER_1,
    add_custody_hop,
    assert_custody_event,
    create_account,
    create_bag,
    create_machine,
    create_sealed_bag_payload,
    create_ticket,
    create_vault,
    custody_event_payload,
    deliver_bag_to_vault,
    make_carrier_headers,
    make_manager_headers,
    make_teller_headers,
    read_bag,
    schedule_session,
    setup_intake_ticket,
    validate_error,
    validate_paginated,
    validate_success,
    verify_ticket,
)


class TestCustodyEvents:
    def test_first_custody_hop_is_an_append_only_record_with_sequence_one(self, api):
        """PRD §2.4: "A `CustodyEvent` — one hop in a bag's chain of custody — has no
        `updated_at` and no `version`."
        PRD §3.2: "The server records the acting `X-User-ID` as `actor_user_id`, assigns
        `sequence_no` as the 1-based position of this event within the bag's chain when
        the chain is ordered by `created_at` ascending, and computes `seal_intact` as true
        exactly when `observed_seal_number` equals the bag's registered `seal_number` and
        false otherwise."
        PRD §3.2: "A `PICKUP` hop, recorded by the carrier, moves a bag `SEALED →
        IN_TRANSIT`."
        PRD §3.2: "Each of these four hops increments the bag's `version` by 1, and a hop
        whose type does not match the bag's current custody position — a `PICKUP` on an
        already-received bag, for instance — is `ERR_INVALID_STATE`."

        Design: Corner/entities/custody_event_is_immutable_and_exposes_only_id_and_created_at
        """
        vault = create_vault(vault_code="CV-C05", name="Corner Vault Five")
        account = create_account(account_number="ACC-C05", customer_name="Corner Deli Five")
        ticket = create_ticket(
            account["id"], vault["id"], courier_manifest_number="MAN-C05", declared_bag_count=1
        )
        bag = create_bag(
            ticket["id"],
            seal_number="S-C05",
            bag_type="CURRENCY",
            declared_amount_cents=50_000,
            declared_note_count=50,
            declared_coin_weight_grams=0,
        )

        response = api.create_custody_event(
            bag["id"],
            custody_event_payload("PICKUP", "S-C05", "SITE-CUST"),
            make_carrier_headers(CARRIER_1),
        )
        event = validate_success(response, 201)

        assert_custody_event(event)
        assert event["sequence_no"] == 1, f"First hop must carry sequence_no 1, got {event['sequence_no']}"
        assert event["seal_intact"] is True, "The observed seal matched the registered seal"
        assert event["actor_user_id"] == CARRIER_1, (
            "actor_user_id must be the acting X-User-ID"
        )
        assert "updated_at" not in event, "A CustodyEvent carries no updated_at"
        assert "version" not in event, "A CustodyEvent carries no version"
        assert "id" in event and "created_at" in event

        refreshed = read_bag(bag["id"])
        assert refreshed["custody_status"] == "IN_TRANSIT", (
            f"A PICKUP hop moves the bag to IN_TRANSIT, got {refreshed['custody_status']}"
        )
        assert refreshed["version"] == 2, (
            f"The hop increments the bag's version from 1 to 2, got {refreshed['version']}"
        )

    def test_custody_chain_reads_back_in_ascending_sequence_order(self, api):
        """PRD §3.2: "Custody events are append-only records; they may be read back as an
        ordered chain, paged by `limit` and `offset`, but never modified."
        PRD §3.2: "The server records the acting `X-User-ID` as `actor_user_id`, assigns
        `sequence_no` as the 1-based position of this event within the bag's chain when
        the chain is ordered by `created_at` ascending, and computes `seal_intact` as true
        exactly when `observed_seal_number` equals the bag's registered `seal_number` and
        false otherwise."
        PRD §2.3: "Unless a specific endpoint narrative says otherwise, list results are
        sorted by `created_at` in ascending order — oldest first."

        Design: Corner/endpoints/custody_events_subresource_returns_the_chain_in_sequence_order
        """
        vault = create_vault(vault_code="CV-C44", name="Chain Order Vault")
        account = create_account(account_number="ACC-C44", customer_name="Chain Order Cafe")
        machine = create_machine(vault["id"], machine_code="SORT-C44")
        ticket = create_ticket(
            account["id"], vault["id"], courier_manifest_number="MAN-C44", declared_bag_count=1
        )
        bag = create_bag(
            ticket["id"],
            seal_number="S-C44",
            bag_type="CURRENCY",
            declared_amount_cents=100_000,
            declared_note_count=100,
            declared_coin_weight_grams=0,
        )
        deliver_bag_to_vault(bag["id"], "S-C44", "CV-C44-DOCK")
        schedule_session(bag["id"], machine["id"])
        add_custody_hop(bag["id"], "OPEN", "S-C44", "CV-C44-FLOOR")

        events, meta = validate_paginated(
            api.list_custody_events(
                bag["id"], make_manager_headers(MANAGER_1), params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3, f"Expected a three-hop chain, got {meta['total_count']}"
        assert meta["has_more"] is False
        assert [event["sequence_no"] for event in events] == [1, 2, 3], (
            f"sequence_no must run 1, 2, 3 in ascending created_at order, got {[e['sequence_no'] for e in events]}"
        )
        assert [event["event_type"] for event in events] == ["PICKUP", "VAULT_RECEIPT", "OPEN"], (
            f"Unexpected hop order: {[e['event_type'] for e in events]}"
        )
        for event in events:
            assert_custody_event(event)
            assert event["sealed_bag_id"] == bag["id"]

    def test_vault_receipt_with_a_mismatched_seal_is_refused(self, api):
        """PRD §3.2: "A `VAULT_RECEIPT` hop, recorded by a `VaultTeller`, moves the bag
        `IN_TRANSIT → VAULT_RECEIVED`, and this is the hop where the seal is legally read:
        the supplied `observed_seal_number` must equal the bag's `seal_number`, and a
        mismatch is refused with `ERR_SEAL_TAMPERED`, so a receipt hop that succeeds
        always records `seal_intact` as true."

        Design: Corner/state_machines/vault_receipt_with_mismatched_seal_number_rejected
        """
        vault = create_vault(vault_code="CV-C13", name="Corner Vault Thirteen")
        account = create_account(account_number="ACC-C13", customer_name="Corner Salon Thirteen")
        ticket = create_ticket(
            account["id"], vault["id"], courier_manifest_number="MAN-C13", declared_bag_count=1
        )
        bag = create_bag(
            ticket["id"],
            seal_number="S-C13",
            bag_type="CURRENCY",
            declared_amount_cents=60_000,
            declared_note_count=60,
            declared_coin_weight_grams=0,
        )
        add_custody_hop(bag["id"], "PICKUP", "S-C13", "SITE-CUST")

        response = api.create_custody_event(
            bag["id"],
            custody_event_payload("VAULT_RECEIPT", "S-C13-TAMPERED", "CV-C13-DOCK"),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_SEAL_TAMPERED.value)
        assert response.status_code == 409

        refreshed = read_bag(bag["id"])
        assert refreshed["custody_status"] == "IN_TRANSIT", (
            "A refused receipt hop leaves the bag IN_TRANSIT"
        )
        assert refreshed["version"] == 2, (
            f"A refused hop appends nothing and bumps nothing, expected version 2, got {refreshed['version']}"
        )
        _, meta = validate_paginated(
            api.list_custody_events(bag["id"], make_manager_headers(MANAGER_1))
        )
        assert meta["total_count"] == 1, (
            f"Only the PICKUP hop may be on the chain, got {meta['total_count']}"
        )

    def test_open_hop_without_a_scheduled_count_is_refused(self, api):
        """PRD §3.2: "An `OPEN` hop, also teller-recorded, moves the bag `VAULT_RECEIVED →
        OPENED`, and it is permitted only when a counting session for that bag already
        exists in `SCHEDULED` condition; opening a bag with no scheduled count is refused
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/open_hop_without_scheduled_session_rejected_with_invalid_state
        """
        vault = create_vault(vault_code="CV-C14", name="Corner Vault Fourteen")
        account = create_account(account_number="ACC-C14", customer_name="Corner Hardware Fourteen")
        ticket = create_ticket(
            account["id"], vault["id"], courier_manifest_number="MAN-C14", declared_bag_count=1
        )
        bag = create_bag(
            ticket["id"],
            seal_number="S-C14",
            bag_type="CURRENCY",
            declared_amount_cents=60_000,
            declared_note_count=60,
            declared_coin_weight_grams=0,
        )
        deliver_bag_to_vault(bag["id"], "S-C14", "CV-C14-DOCK")

        response = api.create_custody_event(
            bag["id"],
            custody_event_payload("OPEN", "S-C14", "CV-C14-FLOOR"),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
        assert response.status_code == 409

        refreshed = read_bag(bag["id"])
        assert refreshed["custody_status"] == "VAULT_RECEIVED", (
            f"The bag stays VAULT_RECEIVED, got {refreshed['custody_status']}"
        )


class TestSealedBagRegistration:
    def test_a_repeated_seal_number_is_rejected(self, api):
        """PRD §3.2: "The carrier supplies the `deposit_ticket_id` it belongs to, the
        tamper-evident `seal_number` applied to it, which must be unique across all sealed
        bags — a repeat is `ERR_DUPLICATE_SEAL` — and a `bag_type` of `CURRENCY`, `COIN`,
        or `MIXED`, which determines what class of machine may later process it."
        PRD §3.2: "Bags can be read individually or listed with optional
        `deposit_ticket_id`, `custody_status` and `count_status` filters and the usual
        `limit` and `offset`."

        Design: Corner/validations/duplicate_seal_number_rejected_on_sealed_bag_create
        """
        vault = create_vault(vault_code="CV-C23", name="Corner Vault TwentyThree")
        account = create_account(account_number="ACC-C23", customer_name="Corner Seal Shop")
        ticket = create_ticket(
            account["id"], vault["id"], courier_manifest_number="MAN-C23", declared_bag_count=2
        )
        create_bag(
            ticket["id"],
            seal_number="S-C23",
            bag_type="CURRENCY",
            declared_amount_cents=50_000,
            declared_note_count=50,
            declared_coin_weight_grams=0,
        )

        response = api.create_sealed_bag(
            create_sealed_bag_payload(
                ticket["id"],
                seal_number="S-C23",
                bag_type="CURRENCY",
                declared_amount_cents=70_000,
                declared_note_count=70,
                declared_coin_weight_grams=0,
            ),
            make_carrier_headers(CARRIER_1),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_SEAL.value)
        assert response.status_code == 409

        _, meta = validate_paginated(
            api.list_sealed_bags(
                make_manager_headers(MANAGER_1), params={"deposit_ticket_id": ticket["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"The rejected registration must create no bag, got {meta['total_count']}"
        )
        refreshed_ticket = validate_success(
            api.get_deposit_ticket(ticket["id"], make_manager_headers(MANAGER_1))
        )
        assert refreshed_ticket["declared_total_cents"] == 50_000, (
            "declared_total_cents must still reflect only the one registered bag"
        )


class TestDropVerification:
    def test_verify_is_refused_when_the_bag_count_disagrees_with_the_manifest(self, api):
        """PRD §3.2: "The number of registered bags carrying this `deposit_ticket_id` must
        equal the ticket's `declared_bag_count`; a short or long drop is
        `ERR_BAG_COUNT_MISMATCH`."

        Design: Corner/state_machines/verify_rejected_when_bag_count_differs_from_declared_bag_count
        """
        vault = create_vault(vault_code="CV-C12", name="Corner Vault Twelve")
        account = create_account(account_number="ACC-C12", customer_name="Corner Laundry Twelve")
        ticket = create_ticket(
            account["id"], vault["id"], courier_manifest_number="MAN-C12", declared_bag_count=2
        )
        bag = create_bag(
            ticket["id"],
            seal_number="S-C12",
            bag_type="CURRENCY",
            declared_amount_cents=60_000,
            declared_note_count=60,
            declared_coin_weight_grams=0,
        )
        deliver_bag_to_vault(bag["id"], "S-C12", "CV-C12-DOCK")

        response = api.verify_deposit_ticket(ticket["id"], make_teller_headers(TELLER_1))
        validate_error(response, ApiErrorId.ERR_BAG_COUNT_MISMATCH.value)
        assert response.status_code == 409

        refreshed = validate_success(
            api.get_deposit_ticket(ticket["id"], make_manager_headers(MANAGER_1))
        )
        assert refreshed["status"] == "INTAKE", (
            f"A refused verification leaves the ticket in INTAKE, got {refreshed['status']}"
        )

    def test_verifying_an_already_verified_ticket_is_refused(self, api):
        """PRD §3.2: "Once every bag on the manifest is physically in the vault, a teller
        **verifies** the drop, moving the ticket `INTAKE → VERIFIED`."
        PRD §2.6: "**Transition legality.** The target entity is in a state from which the
        requested transition is declared — `ERR_INVALID_STATE` (409)."
        PRD §3.2: "Verification recomputes `declared_total_cents` from the bags as its side
        effect, so the figure the credit decision reads is the one the vault actually
        holds."

        Design: Corner/state_machines/verify_on_already_verified_ticket_rejects_with_invalid_state
        """
        scenario = setup_intake_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 60_000,
                    "declared_note_count": 60,
                    "declared_coin_weight_grams": 0,
                }
            ]
        )
        first = verify_ticket(scenario["ticket"]["id"])
        assert first["status"] == "VERIFIED", f"Expected VERIFIED, got {first['status']}"

        response = api.verify_deposit_ticket(
            scenario["ticket"]["id"], make_teller_headers(TELLER_1)
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
        assert response.status_code == 409

        refreshed = validate_success(
            api.get_deposit_ticket(scenario["ticket"]["id"], make_manager_headers(MANAGER_1))
        )
        assert refreshed["status"] == "VERIFIED"
        assert refreshed["declared_total_cents"] == 60_000, (
            f"declared_total_cents must remain 60000, got {refreshed['declared_total_cents']}"
        )
