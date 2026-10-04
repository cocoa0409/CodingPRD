"""State machines, their derived postures, and the cascades that fire when a
party's posture changes underneath the rest of the network."""
from test_helpers import (
    ApiErrorId,
    add_fleet_unit,
    api_client,
    bco_headers,
    dispatch_trip,
    enroll_agent,
    enroll_capacity_owner,
    file_standard_credentials,
    get_bco,
    get_success_data,
    post_ledger_entry,
    post_offer,
    promote_load,
    qualify_bco,
    register_customer,
    set_logical_clock,
    setup_en_route_haul,
    setup_out_of_service_bco_with_unit,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    cover_load,
)


class TestLoadAwardCycle:
    """Load walks POSTED → AWARDED → POSTED, a genuine cycle."""

    def test_aborted_trip_returns_load_to_the_board(self, api):
        """PRD §3.5: "at depth two the load returns to `POSTED` with its awarded
        owner cleared; at depth three the previously accepted offer becomes
        `DECLINED` and the remaining open offers have their ranks re-derived."
        PRD §3.5: "at depth one the capacity owner's safety score drops by 15
        and the posture is recomputed".

        Design: Difficulty/non_linear_state_machine/load_award_cycle_posted_awarded_posted
        """
        state = setup_en_route_haul()
        bco, load, trip, offer = state["bco"], state["load"], state["trip"], state["offer"]

        get_success_data(
            api.abort_trip(trip["id"], {"reason_code": "DRIVER_UNAVAILABLE"}, bco_headers(bco))
        )

        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["status"] == "POSTED"
        assert load_after["awarded_capacity_owner_id"] is None

        trip_after = get_success_data(api.get_trip(trip["id"], TEST_USERS["network_admin_headers"]))
        assert trip_after["status"] == "ABORTED"

        offer_after = get_success_data(api.get_load_offer(offer["id"], TEST_USERS["network_admin_headers"]))
        assert offer_after["status"] == "DECLINED"

        open_offers, meta = validate_paginated(
            api.list_load_board_offers(
                load["id"], TEST_USERS["network_admin_headers"], params={"status": "OPEN"}
            )
        )
        assert meta["total_count"] == 0 and open_offers == []

        owner_after = get_bco(bco["id"])
        assert owner_after["safety_score"] == 85

    def test_award_cycle_is_re_traversable_only_through_a_fresh_offer(self, api):
        """PRD §3.4: "A capacity owner declines its own open offer with a
        `declined_at`, which is refused if the offer is not `OPEN`
        (`ERR_OFFER_NOT_OPEN`)".
        PRD §3.5: "Acceptance requires that the load be `POSTED` with
        `board_required` still true".

        Design: Difficulty/non_linear_state_machine/load_award_cycle_posted_awarded_posted
        """
        state = setup_en_route_haul()
        agent, bco, load, trip, offer = (
            state["agent"], state["bco"], state["load"], state["trip"], state["offer"]
        )

        get_success_data(
            api.abort_trip(trip["id"], {"reason_code": "DRIVER_UNAVAILABLE"}, bco_headers(bco))
        )

        # The consumed offer can never be re-accepted.
        replay = api.accept_load_offer(
            offer["id"], {"accepted_at": "2026-09-01T05:00:00Z"}, bco_headers(bco)
        )
        validate_error(replay, ApiErrorId.ERR_OFFER_NOT_OPEN)

        # A fresh offer, carrying the freshly read load version, returns it to AWARDED.
        fresh = post_offer(agent, load, bco, 126000, "2026-09-01T06:00:00Z")
        validate_success(
            api.accept_load_offer(
                fresh["id"], {"accepted_at": "2026-09-01T07:00:00Z"}, bco_headers(bco)
            ), 200
        )
        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["status"] == "AWARDED"


class TestCapacityOwnerPostureDimensions:
    """The lifecycle status and the derived posture move independently."""

    def test_unit_inspection_restricts_posture_without_a_status_move(self, api):
        """PRD §3.3: "It is `QUALIFICATION_RESTRICTED` when the status is
        `OUT_OF_SERVICE`, or the safety score has fallen below the minimum of
        70, or the escrow balance has dropped below the floor of 100000 cents,
        or at least one fleet unit sits in `PENDING_INSPECTION` or
        `OUT_OF_SERVICE`."

        Design: Difficulty/non_linear_state_machine/capacity_owner_posture_parallel_dimensions
        """
        state = setup_out_of_service_bco_with_unit()
        bco, units = state["bco"], state["equipment"]

        owner_now = get_bco(bco["id"])
        assert owner_now["status"] == "QUALIFIED"
        assert owner_now["qualification_posture"] == "QUALIFICATION_RESTRICTED"

        untouched = get_success_data(api.get_equipment(units[0]["id"], TEST_USERS["network_admin_headers"]))
        assert untouched["status"] == "IN_SERVICE"
        assert untouched["inspection_status"] == "CURRENT"

    def test_suspend_reinstate_and_a_passing_inspection_restore_clear_posture(self, api):
        """PRD §3.3: "Placing a qualified owner out of service — the `QUALIFIED`
        to `OUT_OF_SERVICE` move — requires the row to be `QUALIFIED`".
        PRD §3.3: "Reinstatement back to `QUALIFIED` requires the row to be
        `OUT_OF_SERVICE`".
        PRD §3.3: "From `PENDING_INSPECTION` or from `OUT_OF_SERVICE`, a passing
        result moves the unit to `IN_SERVICE`".

        Design: Difficulty/non_linear_state_machine/capacity_owner_posture_parallel_dimensions
        """
        state = setup_out_of_service_bco_with_unit()
        bco, units = state["bco"], state["equipment"]

        suspended = validate_success(
            api.suspend_capacity_owner(
                bco["id"], {"reason_code": "REPEATED_HOURS_VIOLATIONS"},
                TEST_USERS["safety_reviewer_headers"],
            ), 200
        )
        assert suspended["status"] == "OUT_OF_SERVICE"
        assert suspended["safety_score"] == 100, "no trips existed to abort"

        first_unit = get_success_data(api.get_equipment(units[0]["id"], TEST_USERS["network_admin_headers"]))
        assert first_unit["status"] == "OUT_OF_SERVICE"

        validate_success(
            api.reinstate_capacity_owner(
                bco["id"], {"reason_code": "COUNSELING_COMPLETE"},
                TEST_USERS["safety_reviewer_headers"],
            ), 200
        )
        reinstated = get_bco(bco["id"])
        assert reinstated["status"] == "QUALIFIED"
        assert reinstated["qualification_posture"] == "QUALIFICATION_RESTRICTED"

        # Putting the out-of-service unit back through a passing inspection is
        # what clears the last restriction input.
        get_success_data(
            api.record_inspection(
                units[1]["id"],
                {"inspected_at": "2026-09-02T00:00:00Z", "result": "PASS",
                 "inspector_certificate": "CERT-TX-906"},
                TEST_USERS["safety_reviewer_headers"],
            )
        )
        cleared = get_bco(bco["id"])
        assert cleared["qualification_posture"] == "QUALIFIED_CLEAR"


class TestCascades:
    """Depth-by-depth chained side effects."""

    def test_bco_suspension_cascades_through_trip_load_and_offer(self, api):
        """PRD §3.3: "At depth one, every unit this owner has that is
        `IN_SERVICE` becomes `OUT_OF_SERVICE`. At depth two, every trip of this
        owner that is `DISPATCH_PENDING` or `EN_ROUTE` becomes `ABORTED` and the
        safety score drops by 15 per aborted trip. At depth three, every load
        whose `awarded_capacity_owner_id` points at this owner and whose status
        is `AWARDED` returns to `POSTED` with the awarded owner cleared, and each
        such load's accepted offer becomes `DECLINED`."

        Design: Difficulty/transitive_cascade/bco_abort_cascade_through_load_to_offer
        """
        state = setup_en_route_haul()
        bco, load, trip, offer, unit = (
            state["bco"], state["load"], state["trip"], state["offer"], state["equipment"]
        )

        suspended = validate_success(
            api.suspend_capacity_owner(
                bco["id"], {"reason_code": "HOURS_OF_SERVICE_VIOLATION"},
                TEST_USERS["safety_reviewer_headers"],
            ), 200
        )
        assert suspended["status"] == "OUT_OF_SERVICE"
        assert suspended["qualification_posture"] == "QUALIFICATION_RESTRICTED"

        trip_after = get_success_data(api.get_trip(trip["id"], TEST_USERS["network_admin_headers"]))
        assert trip_after["status"] == "ABORTED"
        assert get_bco(bco["id"])["safety_score"] == 85

        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["status"] == "POSTED"
        assert load_after["awarded_capacity_owner_id"] is None

        offer_after = get_success_data(api.get_load_offer(offer["id"], TEST_USERS["network_admin_headers"]))
        assert offer_after["status"] == "DECLINED"

        unit_after = get_success_data(api.get_equipment(unit["id"], TEST_USERS["network_admin_headers"]))
        assert unit_after["status"] == "OUT_OF_SERVICE"

    def test_credential_verification_cascades_through_freeze_to_the_trip(self, api):
        """PRD §2.9: "A credential's status is `REJECTED` when it has been
        explicitly rejected by the verifying clerk, is `VALID` strictly before
        its `expires_at`, is `EXPIRING_SOON` when the remaining time before
        `expires_at` is greater than zero and at most 30 days, and is `EXPIRED`
        once the clock reaches `expires_at`."
        PRD §3.3: "It is `QUALIFICATION_FROZEN` when the owner's status is
        `DECERTIFIED` or when any of its credentials currently evaluates to
        `EXPIRED`."

        Design: Difficulty/transitive_cascade/document_verification_cascade_to_posture_and_trip
        """
        set_logical_clock("2026-12-01T00:00:00Z")
        agent = enroll_agent()
        customer = register_customer(agent)

        bco = enroll_capacity_owner()
        post_ledger_entry(bco, 250000)
        # Every credential expires after the clock except the medical card.
        file_standard_credentials(bco, expires_at="2027-06-01T00:00:00Z")
        medical = get_success_data(
            api.create_compliance_document(
                {
                    "capacity_owner_id": bco["id"],
                    "document_type": "MEDICAL_CARD",
                    "document_number": "TX-MC-77502",
                    "issued_at": "2026-01-01T00:00:00Z",
                    "expires_at": "2026-06-01T00:00:00Z",
                },
                TEST_USERS["safety_reviewer_headers"],
            )
        )
        unit = add_fleet_unit(bco)
        bco = qualify_bco(bco)

        load = promote_load(agent, customer["customer_ref"])
        offer = post_offer(agent, load, bco)
        validate_success(
            api.accept_load_offer(offer["id"], {"accepted_at": "2026-09-01T02:00:00Z"}, bco_headers(bco)),
            200,
        )
        awarded = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        trip = cover_load(bco, awarded, unit)
        trip = dispatch_trip(bco, trip)

        # The credential alone moves the posture: the clock is past its expiry.
        verified = validate_success(
            api.verify_compliance_document(
                medical["id"], {"verified_at": "2026-12-01T00:00:00Z"},
                TEST_USERS["safety_reviewer_headers"],
            ), 200
        )
        assert verified["status"] == "EXPIRED"

        frozen = get_bco(bco["id"])
        assert frozen["qualification_posture"] == "QUALIFICATION_FROZEN"
        assert frozen["safety_score"] == 95, "one expired credential costs 5 points"


def _ledger(bco_id):
    return validate_paginated(
        api_client.list_capacity_owner_ledger(bco_id, TEST_USERS["settlement_operator_headers"])
    )