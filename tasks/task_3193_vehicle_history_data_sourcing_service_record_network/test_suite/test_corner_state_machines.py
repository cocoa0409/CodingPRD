"""Breadth tests: state-machine behavior — terminal lockdown, initial states,
non-idempotent transitions, the claim-in-flight delist gate, and correction
expiry timing."""

from test_helpers import (
    VIN_A,
    ApiErrorId,
    advance_epoch,
    create_consumer,
    create_dealer,
    file_claim,
    get_correction,
    make_dealer_agent_headers,
    make_guarantee_admin_headers,
    make_network_admin_headers,
    make_vehicle_owner_headers,
    open_correction,
    register_source,
    setup_enrolled_listing_with_escalation,
    setup_network,
    setup_network_with_source,
    submit_title,
    validate_error,
    validate_success,
)
from test_helpers import get_vehicle
from test_helpers.factories import create_shop_payload


class TestRecordTerminalLockdown:
    def test_correction_against_superseded_record_rejected(self, api, admin_headers):
        """PRD §3.7: "The target record must belong to the path vehicle and still be `ACTIVE`; otherwise the request is rejected with `ERR_RECORD_NOT_ACTIVE`."

        Design: Corner/state_machines/record_terminal_lockdown_superseded
        """
        network, source = setup_network_with_source(api)
        first = submit_title(api, source["id"], VIN_A, "CA", "clean", idempotency_key="k-t1", payload_ref="t1")
        # Same-source replacement with changed content supersedes the first record.
        submit_title(api, source["id"], VIN_A, "CA", "flood", idempotency_key="k-t2", payload_ref="t2")
        from test_helpers import get_vehicle
        vehicle = get_vehicle(api, first["vehicle_id"])
        consumer = create_consumer(api)
        resp = api.open_correction(
            first["vehicle_id"],
            {
                "target_record_id": first["id"],
                "reason": "late correction",
                "expected_vehicle_version": vehicle["version"],
            },
            make_vehicle_owner_headers(consumer["id"]),
        )
        validate_error(resp, ApiErrorId.RECORD_NOT_ACTIVE)


class TestInitialStateDefaults:
    def test_source_pending_and_shop_applied_at_creation(self, api, admin_headers):
        """PRD §3.1: "A freshly registered source sits in `PENDING` status with a `reliability_score` of 100."
        PRD §3.6: "a `NetworkAdmin` registers a shop with its `legal_name`, and the shop begins in `APPLIED` status with `reporting_tool_tier` `NONE`."

        Design: Corner/state_machines/initial_state_defaults
        """
        setup_network(api)
        source = register_source(api, activate=False)
        assert source["status"] == "PENDING"
        assert source["reliability_score"] == 100
        shop = validate_success(api.create_shop(create_shop_payload(), admin_headers), expected_status=201)
        assert shop["status"] == "APPLIED"
        assert shop["reporting_tool_tier"] == "NONE"


class TestNonIdempotentTransitions:
    def test_second_activate_on_active_source_rejected(self, api, admin_headers):
        """PRD §2.9: "State-machine legality is checked after existence: an operation on an existing resource whose current state does not permit the requested transition — including any re-trigger against a terminal state — is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/invalid_transition_activate_on_active_source
        """
        network, source = setup_network_with_source(api)
        resp = api.activate_source(source["id"], admin_headers)
        validate_error(resp, ApiErrorId.INVALID_STATE_TRANSITION)


class TestDelistClaimInFlightGate:
    def test_delist_blocked_while_claim_open_then_succeeds_after_rejection(self, api, admin_headers):
        """PRD §3.9: "An enrolled listing may not be delisted while a claim on it is `OPEN` or `APPROVED` — the attempt fails with `ERR_CLAIM_IN_FLIGHT`. Otherwise delisting an enrolled listing voids the guarantee: `guarantee_status` moves from `ENROLLED` to `VOIDED` and the network's `enrolled_listing_count` decrements by one."

        Design: Corner/state_machines/delist_with_claim_in_flight_blocked
        """
        network, source = setup_network_with_source(api)
        dealer = create_dealer(api)
        listing, vehicle_id = setup_enrolled_listing_with_escalation(api, source["id"], dealer["id"])
        claim = file_claim(api, listing["id"])
        resp = api.delist_listing(dealer["id"], listing["id"], make_dealer_agent_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.CLAIM_IN_FLIGHT)

        validate_success(api.reject_claim(claim["id"], make_guarantee_admin_headers()))
        delisted = validate_success(api.delist_listing(dealer["id"], listing["id"], make_dealer_agent_headers(dealer["id"])))
        assert delisted["status"] == "DELISTED"
        assert delisted["guarantee_status"] == "VOIDED"


class TestCorrectionExpiryAfterDeadline:
    def test_alive_at_deadline_epoch_expired_after(self, api, admin_headers):
        """PRD §3.7: "Routing sets `source_deadline_epoch` to the current epoch plus 2 — the source has two epochs to respond."
        PRD §3.7: "If the source does not respond in time, the epoch advance expires the request: when the current `epoch_index` moves past `source_deadline_epoch`, an `AWAITING_SOURCE` request transitions to `EXPIRED`, also terminal."

        Design: Corner/state_machines/correction_expiry_after_deadline
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        consumer = create_consumer(api)
        correction = open_correction(
            api, title["vehicle_id"], title["id"], get_vehicle(api, title["vehicle_id"])["version"],
            make_vehicle_owner_headers(consumer["id"]),
        )
        validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        advance_epoch(api, 2)  # now at epoch 2 == deadline; not yet past it
        at_deadline = get_correction(api, correction["id"])
        assert at_deadline["status"] == "AWAITING_SOURCE", (
            f"epoch 2 == deadline must still be AWAITING_SOURCE, got {at_deadline['status']}"
        )
        advance_epoch(api, 1)  # epoch 3 > deadline 2
        past_deadline = get_correction(api, correction["id"])
        assert past_deadline["status"] == "EXPIRED", (
            f"epoch 3 > deadline 2 must expire the request, got {past_deadline['status']}"
        )
