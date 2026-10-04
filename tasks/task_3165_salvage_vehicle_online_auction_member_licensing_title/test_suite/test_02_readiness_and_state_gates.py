"""Readiness gating: image threshold, title precondition, OCC, invalid transitions."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_images,
    create_seller,
    create_vehicle,
    create_vehicle_payload,
    create_yard,
    get_success_data,
    make_seller_agent_headers,
    mark_ready,
    prepare_vehicle,
    receive_title,
    setup_paid_sale,
    issue_gate_pass,
    submit_condition,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client as _api
from test_helpers.test_users import TEST_USERS

YO = TEST_USERS["yard_operator_headers"]
TC = TEST_USERS["title_clerk_headers"]


class TestImageThreshold:
    def test_four_images_block_mark_ready(self, api):
        """PRD §3.1: "The upload that brings the count to at least five automatically
        advances the vehicle from `ASSIGNED` to `AWAITING_CONDITION`; with fewer than
        five images the vehicle stays `ASSIGNED` and any readiness attempt is rejected
        with `ERR_VEHICLE_NOT_IMAGE_READY`."

        Design: Difficulty/boundary_precision_check/image_count_five_threshold_for_mark_ready
        """
        yard = create_yard()
        seller = create_seller()
        vehicle = create_vehicle(seller, yard)
        receive_title(vehicle["id"])
        submit_condition(vehicle["id"])
        add_images(vehicle["id"], count=4)
        current = get_success_data(api.get_vehicle(vehicle["id"], YO))
        assert current["image_count"] == 4
        assert current["status"] == "ASSIGNED"
        resp = api.mark_ready(vehicle["id"], {"expected_vehicle_version": current["version"]}, YO)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_IMAGE_READY)

    def test_fifth_image_auto_advances_and_mark_ready_succeeds(self, api):
        """PRD §3.1: "The upload that brings the count to at least five automatically
        advances the vehicle from `ASSIGNED` to `AWAITING_CONDITION`; with fewer than
        five images the vehicle stays `ASSIGNED` and any readiness attempt is rejected
        with `ERR_VEHICLE_NOT_IMAGE_READY`."
        PRD §3.3: "the vehicle must be in `AWAITING_CONDITION`; its `image_count` must
        be at least five (`ERR_VEHICLE_NOT_IMAGE_READY`)"

        Design: Difficulty/boundary_precision_check/image_count_five_threshold_for_mark_ready
        """
        yard = create_yard()
        seller = create_seller()
        vehicle = create_vehicle(seller, yard)
        receive_title(vehicle["id"])
        submit_condition(vehicle["id"])
        add_images(vehicle["id"], count=4)
        last = add_images(vehicle["id"], count=1)
        assert last["image_count"] == 5
        current = get_success_data(api.get_vehicle(vehicle["id"], YO))
        assert current["status"] == "AWAITING_CONDITION"
        ready = validate_success(
            api.mark_ready(vehicle["id"], {"expected_vehicle_version": current["version"]}, YO), 200
        )
        assert ready["status"] == "SALE_READY"


class TestMarkReadyTitleGate:
    def test_mark_ready_blocked_without_received_title(self, api):
        """PRD §3.3: "a title record must exist in `RECEIVED` status
        (`ERR_TITLE_NOT_RECEIVED`)"

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_received_title_record
        """
        yard = create_yard()
        seller = create_seller()
        vehicle = create_vehicle(seller, yard)
        submit_condition(vehicle["id"])
        add_images(vehicle["id"], count=5)
        current = get_success_data(api.get_vehicle(vehicle["id"], YO))
        assert current["status"] == "AWAITING_CONDITION"
        resp = api.mark_ready(vehicle["id"], {"expected_vehicle_version": current["version"]}, YO)
        validate_error(resp, ApiErrorId.ERR_TITLE_NOT_RECEIVED)

    def test_mark_ready_succeeds_after_title_received(self, api):
        """PRD §3.3: "a title record must exist in `RECEIVED` status
        (`ERR_TITLE_NOT_RECEIVED`)"
        PRD §3.3: "On success the vehicle becomes `SALE_READY`, its `received_at` is
        stamped with the logical clock — this timestamp later anchors the seller-side
        storage window — and its `version` increments."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_received_title_record
        """
        yard = create_yard()
        seller = create_seller()
        vehicle = create_vehicle(seller, yard)
        submit_condition(vehicle["id"])
        add_images(vehicle["id"], count=5)
        before = get_success_data(api.get_vehicle(vehicle["id"], YO))
        resp = api.mark_ready(vehicle["id"], {"expected_vehicle_version": before["version"]}, YO)
        validate_error(resp, ApiErrorId.ERR_TITLE_NOT_RECEIVED)
        receive_title(vehicle["id"])
        ready = mark_ready(vehicle["id"])
        assert ready["status"] == "SALE_READY"
        assert ready["received_at"] == "2026-09-01T00:00:00Z"


class TestStaleVersion:
    def test_mark_ready_stale_version_returns_412(self, api):
        """PRD §2.8: "Because an intervening condition revision legitimately overwrites
        the very condition report the caller based its readiness judgment on, a value
        that no longer matches the vehicle's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412) rather than allowing the readiness decision to
        stand on superseded data."

        Design: Corner/validations/mark_ready_stale_version_returns_412
        """
        yard = create_yard()
        seller = create_seller()
        vehicle = create_vehicle(seller, yard)
        receive_title(vehicle["id"])
        submit_condition(vehicle["id"])
        add_images(vehicle["id"], count=5)
        stale = get_success_data(api.get_vehicle(vehicle["id"], YO))
        submit_condition(vehicle["id"], primary_damage="REAR", run_and_drive_status="STARTS")
        resp = api.mark_ready(vehicle["id"], {"expected_vehicle_version": stale["version"]}, YO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        still = get_success_data(api.get_vehicle(vehicle["id"], YO))
        assert still["status"] == "AWAITING_CONDITION"

    def test_fresh_mark_ready_retry_after_412_succeeds(self, api):
        """PRD §2.8: "That request must carry `expected_vehicle_version` holding the
        caller's last-observed `version` of the vehicle."

        Design: Corner/validations/mark_ready_stale_version_returns_412
        """
        yard = create_yard()
        seller = create_seller()
        vehicle = create_vehicle(seller, yard)
        receive_title(vehicle["id"])
        submit_condition(vehicle["id"])
        add_images(vehicle["id"], count=5)
        stale = get_success_data(api.get_vehicle(vehicle["id"], YO))
        submit_condition(vehicle["id"], primary_damage="REAR", run_and_drive_status="STARTS")
        resp = api.mark_ready(vehicle["id"], {"expected_vehicle_version": stale["version"]}, YO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_success_data(api.get_vehicle(vehicle["id"], YO))
        ready = validate_success(
            api.mark_ready(vehicle["id"], {"expected_vehicle_version": fresh["version"]}, YO), 200
        )
        assert ready["status"] == "SALE_READY"


class TestInvalidTransitions:
    def test_mark_ready_from_sale_ready_rejected_as_invalid_transition(self, api):
        """PRD §3.3: "the vehicle must be in `AWAITING_CONDITION`"
        PRD §2.7: "(7) state preconditions for the requested transition
        (`ERR_VEHICLE_INVALID_STATE`, `ERR_VEHICLE_NOT_SALE_READY`, ...)"

        Design: Corner/state_machines/mark_ready_from_sale_ready_rejected_as_invalid_transition
        """
        yard = create_yard()
        seller = create_seller()
        vehicle = prepare_vehicle(seller, yard)
        assert vehicle["status"] == "SALE_READY"
        resp = api.mark_ready(vehicle["id"], {"expected_vehicle_version": vehicle["version"]}, YO)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_INVALID_STATE)
        after = get_success_data(api.get_vehicle(vehicle["id"], YO))
        assert after["status"] == "SALE_READY"
        assert after["version"] == vehicle["version"]

    def test_condition_revision_only_allowed_while_awaiting_condition(self, api):
        """PRD §3.1: "Submitting a condition report to a vehicle in any other status is
        rejected with `ERR_VEHICLE_INVALID_STATE`."

        Design: Corner/state_machines/condition_revision_only_allowed_while_awaiting_condition
        """
        yard = create_yard()
        seller = create_seller()
        vehicle = prepare_vehicle(seller, yard)
        assert vehicle["status"] == "SALE_READY"
        resp = api.submit_condition(
            vehicle["id"], {"primary_damage": "REAR", "run_and_drive_status": "STATIONARY"}, YO
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_INVALID_STATE)
        after = get_success_data(api.get_vehicle(vehicle["id"], YO))
        assert after["primary_damage"] == "FRONT"
        assert after["run_and_drive_status"] == "RUN_AND_DRIVE"


class TestTerminalLockdown:
    def test_terminal_state_lockdown_loaded_out_vehicle_rejects_cancel(self, api):
        """PRD §3.5: "a seller may cancel a vehicle outright at any point before it
        sells — from `ASSIGNED`, `AWAITING_CONDITION`, `SALE_READY`, `LISTED`, or
        `LIVE`, with any other state rejected as `ERR_VEHICLE_NOT_CANCELLABLE`."

        Design: Corner/state_machines/terminal_state_lockdown_loaded_out_vehicle_rejects_cancel
        """
        ctx = setup_paid_sale()
        set_clock("2026-09-02T15:00:00Z")
        gp = issue_gate_pass(ctx)
        validate_success(api.check_in_gate_pass(gp["id"], YO), 200)
        validate_success(api.complete_gate_pass(gp["id"], YO), 200)
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], YO))
        assert vehicle["status"] == "LOADED_OUT"
        resp = api.cancel_vehicle(vehicle["id"], make_seller_agent_headers(ctx["seller"]["id"]))
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_CANCELLABLE)
        after = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], YO))
        assert after["status"] == "LOADED_OUT"


class TestVinDuplicate:
    def test_vin_duplicate_returns_conflict(self, api):
        """PRD §3.1: "a 17-character `vin` that must be unique system-wide (a duplicate
        is rejected with `ERR_VIN_DUPLICATE`)"

        Design: Corner/validations/vin_duplicate_returns_conflict
        """
        yard = create_yard()
        seller = create_seller()
        agent = make_seller_agent_headers(seller["id"])
        payload = create_vehicle_payload(seller["id"], yard["id"], vin="1HGCM82633A004352")
        validate_success(api.create_vehicle(payload, agent), 201)
        dup = create_vehicle_payload(
            seller["id"], yard["id"], vin="1HGCM82633A004352", year=2021, model="Civic"
        )
        resp = api.create_vehicle(dup, agent)
        validate_error(resp, ApiErrorId.ERR_VIN_DUPLICATE)


class TestRbac:
    def test_role_denied_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is declared but not permitted for the
        endpoint, or that fails an entity-backed ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST | `/salvage-auction/vehicles` | Assign a vehicle to a yard |
        SellerAgent"

        Design: Corner/validations/role_denied_returns_forbidden
        """
        yard = create_yard()
        seller = create_seller()
        payload = create_vehicle_payload(seller["id"], yard["id"])
        resp = api.create_vehicle(payload, YO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
