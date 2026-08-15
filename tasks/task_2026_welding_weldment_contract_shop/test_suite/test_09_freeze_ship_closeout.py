"""Weldment terminal-phase behavior: the FROZEN posture derivation and its
conserved distortion counter, the traveler completeness gate at shipment,
and optimistic concurrency on the ship call."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    declare_repair,
    get_success_data,
    record_weld_pass,
    setup_fab_workspace,
    setup_frozen_weldment,
    setup_vt_passed_workspace,
    sign_traveler,
    unfreeze_weldment,
    validate_error,
    weld_out,
)

ADMIN = TEST_USERS["shop_admin_headers"]
WELD_LEAD = TEST_USERS["weld_lead_headers"]
CWI = TEST_USERS["cwi_headers"]
SHIPPING_CLERK = TEST_USERS["shipping_clerk_headers"]


class TestFreezeUnfreeze:
    def test_freeze_derives_from_ndt_failure_and_distortion_count(self, api):
        """PRD §3.7: "The most severe posture is `FROZEN`, derived when two
        conditions coincide on an `OPEN` weldment: at least one joint carries
        `inspection_status` `NDT_FAILED`, and the weldment's
        `distortion_count` has reached at least 2 (the boundary is
        inclusive)."
        PRD §3.7: "Every report increments the parent weldment's
        `distortion_count` by one, and each report in turn feeds the
        weldment's derived posture."
        PRD §3.6: "A `FAIL` moves the joint to `NDT_FAILED`, increments the
        joint's `repair_cycle_count` by one, and triggers two further
        evaluations: if the count has exceeded the AWS D1.1 hard cap of two
        repair cycles, the joint is cancelled outright; and the parent
        weldment's freeze criteria are recomputed as described in §3.7."

        Design: Difficulty/compensating_invariant/weldment_posture_freeze_unfreeze_conservation
        """
        ws = setup_frozen_weldment(shop_name="Freeze Shop")
        shop_id = ws["shop"]["id"]

        joint_now = get_success_data(
            api.get_joint(shop_id, ws["joints"][0]["id"], ADMIN))
        assert joint_now["inspection_status"] == "NDT_FAILED"
        assert joint_now["repair_cycle_count"] == 1

        wm = get_success_data(
            api.get_weldment(shop_id, ws["weldment"]["id"], ADMIN))
        assert wm["distortion_count"] == 2
        assert wm["posture"] == "FROZEN", (
            "NDT_FAILED joint plus distortion_count >= 2 freezes the "
            f"weldment, got {wm['posture']}")

    def test_unfreeze_returns_open_without_resetting_distortion_count(
            self, api):
        """PRD §3.7: "A `QCManager` unfreezes the weldment once it is
        `FROZEN` and every `NDT_FAILED` joint has been moved on to
        `REPAIR_REQUIRED` or `REPAIR_WELDED_OUT`; unfreezing increments the
        weldment's `version` and returns it to `OPEN`."
        PRD §3.7: "Repair work re-enters the loop through the `QCManager`,
        who declares a repair on a joint whose `inspection_status` is
        `NDT_FAILED`. The declaration moves the joint to `REPAIR_REQUIRED`
        and re-opens its `fabrication_status` to `IN_PROGRESS` so repair
        passes can be welded."

        Unfreezing only flips posture: the cumulative distortion_count is a
        conserved counter and must not be reset.

        Design: Difficulty/compensating_invariant/weldment_posture_freeze_unfreeze_conservation
        """
        ws = setup_frozen_weldment(shop_name="Unfreeze Shop")
        shop_id = ws["shop"]["id"]
        weldment_id = ws["weldment"]["id"]
        joint_id = ws["joints"][0]["id"]

        pre = get_success_data(api.get_weldment(shop_id, weldment_id, ADMIN))
        assert pre["posture"] == "FROZEN"
        assert pre["distortion_count"] == 2

        # Move the failed joint on to REPAIR_REQUIRED so unfreeze is allowed.
        repaired = declare_repair(shop_id, joint_id)
        assert repaired["inspection_status"] == "REPAIR_REQUIRED"
        assert repaired["fabrication_status"] == "IN_PROGRESS"

        # Re-read after the repair declaration so the version comparison
        # isolates exactly the unfreeze increment.
        pre_unfreeze = get_success_data(
            api.get_weldment(shop_id, weldment_id, ADMIN))
        assert pre_unfreeze["posture"] == "FROZEN"

        unfreeze_weldment(shop_id, weldment_id)

        post = get_success_data(api.get_weldment(shop_id, weldment_id, ADMIN))
        assert post["posture"] == "OPEN"
        assert post["distortion_count"] == 2, (
            "Unfreeze must not reset the conserved distortion_count")
        assert post["version"] == pre_unfreeze["version"] + 1, (
            "Unfreezing increments the weldment's version")


class TestShipmentGates:
    def test_ship_weldment_with_unsigned_traveler_returns_error(self, api):
        """PRD §3.8: "The weldment's `posture` must be `OPEN` (otherwise
        `ERR_WELDMENT_NOT_OPEN`); every joint on it must be `WELDED_OUT` in
        fabrication (otherwise `ERR_JOINTS_NOT_WELDED_OUT`); every joint must
        be `NDT_PASSED` in inspection (otherwise `ERR_JOINTS_NOT_NDT_PASSED`);
        and all five traveler steps — `FIT_UP`, `WELD_OUT`, `VT`, `NDT`, and
        `FINAL` — must be present (otherwise `ERR_TRAVELER_INCOMPLETE`)."
        PRD §3.8: "Signing authority is split per §2.1: the `WeldLead` signs
        `FIT_UP` and `WELD_OUT`, the `QualityInspector` signs `VT` and `NDT`,
        and the `CWI` signs `VT`, `NDT`, and `FINAL`."

        Design: Corner/validations/ship_weldment_with_unsigned_traveler_returns_error
        """
        ws = setup_vt_passed_workspace(shop_name="Traveler Shop",
                                       ndt_methods=("VT",),
                                       vendor_methods=None)
        shop_id = ws["shop"]["id"]
        weldment_id = ws["weldment"]["id"]
        joint = ws["joints"][0]
        # VT-only joint is fully inspected and welded out.
        assert joint["inspection_status"] == "NDT_PASSED"
        assert joint["fabrication_status"] == "WELDED_OUT"

        # Sign FIT_UP, WELD_OUT, VT — NDT and FINAL deliberately omitted.
        sign_traveler(shop_id, weldment_id, "FIT_UP", WELD_LEAD)
        sign_traveler(shop_id, weldment_id, "WELD_OUT", WELD_LEAD)
        sign_traveler(shop_id, weldment_id, "VT", CWI)

        current = get_success_data(api.get_weldment(shop_id, weldment_id,
                                                    ADMIN))
        resp = api.ship_weldment(
            shop_id, weldment_id,
            {"expected_weldment_version": current["version"]},
            SHIPPING_CLERK)
        validate_error(resp, ApiErrorId.ERR_TRAVELER_INCOMPLETE)


class TestWeldmentShipOcc:
    def test_occ_stale_version_on_weldment_ship(self, api):
        """PRD §2.6: "Shipping a weldment requires the request to carry
        `expected_weldment_version`, holding the weldment `version` the
        client last observed. If the weldment's current `version` has
        advanced past the supplied value — for example because a joint result
        or a distortion disposition cascaded into the weldment — the ship
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "Next comes optimistic concurrency: a stale
        `expected_weldment_version`, `expected_joint_version`, or
        `expected_wps_version` is rejected (`ERR_STALE_VERSION`) before any
        lifecycle evaluation."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_weldment_ship
        """
        ws = setup_fab_workspace(shop_name="Ship OCC Shop")
        shop_id = ws["shop"]["id"]
        weldment_id = ws["weldment"]["id"]
        stale_version = ws["weldment"]["version"]
        joint = ws["joints"][0]

        # A weld pass mutates the weldment (counters + derived posture), so
        # its version advances past the client's last observation.
        record_weld_pass(shop_id, joint["id"], ws["welder"]["id"],
                         ws["qualification"]["id"], ws["lot"]["id"])
        weld_out(shop_id, joint["id"])

        resp = api.ship_weldment(
            shop_id, weldment_id,
            {"expected_weldment_version": stale_version},
            SHIPPING_CLERK)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
