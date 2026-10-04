"""Depth tests: non-linear state machines — the cyclic DataSource suspension
loop and the branching CorrectionRequest fork."""

from test_helpers import (
    VIN_A,
    ApiErrorId,
    advance_epoch,
    create_consumer,
    get_correction,
    get_record,
    get_source,
    get_vehicle,
    make_network_admin_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
    open_correction,
    register_source,
    setup_network,
    submit_record,
    submit_title,
    validate_error,
    validate_success,
)


class TestDataSourceSuspensionCycle:
    def test_reactivate_before_remediation_window_fails(self, api, admin_headers):
        """PRD §3.2: "A `NetworkAdmin` may reactivate a suspended source only after at least one full epoch has elapsed since suspension — that is, the current `epoch_index` minus `suspended_epoch_index` must be at least 1, otherwise the request fails with `ERR_REMEDIATION_TOO_EARLY`."

        Design: Difficulty/non_linear_state_machine/datasource_suspension_cycle_with_streak_gate
        """
        source = _suspend_source_by_rejection_streak(api)
        assert source["status"] == "SUSPENDED"
        assert source["record_rejection_streak"] == 3
        # Suspended at epoch 1; reactivating in the same epoch is too early.
        resp = api.reactivate_source(source["id"], make_network_admin_headers())
        validate_error(resp, ApiErrorId.REMEDIATION_TOO_EARLY)

    def test_reactivate_requires_streak_reset_then_succeeds_at_half_reliability(self, api, admin_headers):
        """PRD §3.2: "If the suspension was rejection-driven, the administrator must first reset the streak through a dedicated streak-reset capability; attempting reactivation while `record_rejection_streak` is still at 3 or above fails with `ERR_STREAK_NOT_RESET`. Successful reactivation returns the source to `ACTIVE`, sets `reliability_score` to 50, and zeroes both `consecutive_missed_epochs` and `record_rejection_streak`."

        Design: Difficulty/non_linear_state_machine/datasource_suspension_cycle_with_streak_gate
        """
        source = _suspend_source_by_rejection_streak(api)
        advance_epoch(api, 1)  # epoch 1 -> 2: remediation window now elapsed
        resp = api.reactivate_source(source["id"], make_network_admin_headers())
        validate_error(resp, ApiErrorId.STREAK_NOT_RESET)

        validate_success(api.reset_source_streak(source["id"], make_network_admin_headers()))
        reactivated = validate_success(api.reactivate_source(source["id"], make_network_admin_headers()))
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["reliability_score"] == 50, (
            f"successful reactivation must set reliability_score to 50, got {reactivated['reliability_score']}"
        )
        assert reactivated["consecutive_missed_epochs"] == 0
        assert reactivated["record_rejection_streak"] == 0


class TestCorrectionRequestBranchingFork:
    def test_source_confirm_from_open_is_invalid_state(self, api, admin_headers):
        """PRD §2.9: "State-machine legality is checked after existence: an operation on an existing resource whose current state does not permit the requested transition — including any re-trigger against a terminal state — is rejected with `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.7: "A `NetworkAdmin` routes an `OPEN` request to the record's owning source for verification, moving it from `OPEN` to `AWAITING_SOURCE`."

        Design: Difficulty/non_linear_state_machine/correction_request_branching_fork_to_terminal
        """
        network, source = _network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        vehicle_id, record_id = title["vehicle_id"], title["id"]
        consumer = create_consumer(api)
        correction = open_correction(
            api, vehicle_id, record_id, get_vehicle(api, vehicle_id)["version"],
            make_vehicle_owner_headers(consumer["id"]),
        )
        assert correction["status"] == "OPEN"
        # The fork requires routing first: confirm from OPEN is not a permitted branch.
        resp = api.confirm_correction(correction["id"], make_source_operator_headers(source["id"]))
        validate_error(resp, ApiErrorId.INVALID_STATE_TRANSITION)

    def test_verified_branch_joins_to_applied_and_withdraws_record(self, api, admin_headers):
        """PRD §3.7: "Routing sets `source_deadline_epoch` to the current epoch plus 2 — the source has two epochs to respond."
        PRD §3.7: "`WITHDRAW` is always permitted and moves the request to `APPLIED` while transitioning the target record from `ACTIVE` to `WITHDRAWN` — firing the withdrawal cascade: the vehicle's `active_record_count` decrements by one and both the brand and accident rollups re-run."

        Design: Difficulty/non_linear_state_machine/correction_request_branching_fork_to_terminal
        """
        network, source = _network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        vehicle_id, record_id = title["vehicle_id"], title["id"]
        consumer = create_consumer(api)
        correction = open_correction(
            api, vehicle_id, record_id, get_vehicle(api, vehicle_id)["version"],
            make_vehicle_owner_headers(consumer["id"]),
        )
        routed = validate_success(api.route_correction(correction["id"], make_network_admin_headers()))
        assert routed["status"] == "AWAITING_SOURCE"
        assert routed["source_deadline_epoch"] == 2, (
            f"routed at epoch 0 must set deadline 0 + 2 = 2, got {routed['source_deadline_epoch']}"
        )

        verified = validate_success(api.confirm_correction(correction["id"], make_source_operator_headers(source["id"])))
        assert verified["status"] == "VERIFIED"

        applied = validate_success(api.apply_correction(
            correction["id"], {"resolution_action": "WITHDRAW"}, make_network_admin_headers()))
        assert applied["status"] == "APPLIED"

        record = get_record(api, record_id)
        assert record["status"] == "WITHDRAWN"
        vehicle = get_vehicle(api, vehicle_id)
        assert vehicle["canonical_brand"] == "NONE"
        assert vehicle["active_record_count"] == 0


def _network_with_source(api):
    from test_helpers import setup_network_with_source
    return setup_network_with_source(api)


def _suspend_source_by_rejection_streak(api):
    """Three rejected submissions (future event_date) push record_rejection_streak
    to 3; the next epoch advance auto-suspends the source."""
    network, source = _network_with_source(api)
    for i in range(3):
        resp = api.create_record(
            {
                "vin": VIN_A,
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2027-01-01",
                "damage_severity": 3,
                "payload_ref": f"x{i}",
                "idempotency_key": f"k-x{i}",
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(resp, ApiErrorId.EVENT_IN_FUTURE)
    advance_epoch(api, 1)
    return get_source(api, source["id"])
