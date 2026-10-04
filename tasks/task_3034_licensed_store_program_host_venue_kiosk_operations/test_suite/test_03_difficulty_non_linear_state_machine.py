"""Difficulty rule: non_linear_state_machine."""
from test_helpers import (
    ADMIN,
    api_client,
    make_inspector_headers,
    make_licensee_manager_headers,
    schedule_inspection,
    set_clock,
    setup_failed_inspection,
    setup_operating_store,
    validate_success,
)
from test_helpers.fixtures import complete_inspection, list_corrective_actions_for_inspection


class TestCorrectiveActionReopenCycle:
    def _setup_two_actions(self):
        set_clock()
        bundle, inspection, actions = setup_failed_inspection(
            failing_categories=("BEVERAGE_QUALITY", "FOOD_SAFETY"))
        assert len(actions) == 2
        return bundle, inspection, actions

    def test_reopen_cycle_terminates_at_verified(self):
        """PRD §3.8: "The licensee submits an `evidence_note`, moving `OPEN` or
        `REOPENED` to `SUBMITTED`. ... Verification records `verified_by`,
        recomputes the store's posture, and lands the action at `VERIFIED`,
        terminal."

        Design: Difficulty/non_linear_state_machine/corrective_action_reopen_cycle
        """
        bundle, inspection, actions = self._setup_two_actions()
        ca1 = actions[0]
        lic_headers = make_licensee_manager_headers(bundle["licensee_id"])
        # OPEN -> SUBMITTED -> REOPENED -> SUBMITTED -> VERIFIED
        validate_success(api_client.submit_corrective_action_evidence(
            ca1["id"], {"evidence_note": "fixed"}, lic_headers))
        reopened = validate_success(api_client.reopen_corrective_action(
            ca1["id"], {"reason": "insufficient"}, make_inspector_headers("insp-A")))
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        validate_success(api_client.submit_corrective_action_evidence(
            ca1["id"], {"evidence_note": "fixed again"}, lic_headers))
        verified = validate_success(api_client.verify_corrective_action(
            ca1["id"], make_inspector_headers("insp-B")))
        assert verified["status"] == "VERIFIED"
        assert verified["reopen_count"] == 1
        assert verified["verified_by"] == "insp-B"

    def test_one_open_corrective_keeps_store_in_watch_while_operating(self):
        """PRD §3.6: "Posture is `PROBATION` when there are zero certified
        active baristas or at least 2 open correctives; failing that, `WATCH`
        when certified active baristas number fewer than 2 or exactly one
        corrective is open; otherwise `GOOD_STANDING`."

        Design: Difficulty/non_linear_state_machine/corrective_action_reopen_cycle
        """
        bundle, inspection, actions = self._setup_two_actions()
        ca1 = actions[0]
        lic_headers = make_licensee_manager_headers(bundle["licensee_id"])
        validate_success(api_client.submit_corrective_action_evidence(
            ca1["id"], {"evidence_note": "fixed"}, lic_headers))
        validate_success(api_client.reopen_corrective_action(
            ca1["id"], {"reason": "insufficient"}, make_inspector_headers("insp-A")))
        validate_success(api_client.submit_corrective_action_evidence(
            ca1["id"], {"evidence_note": "fixed again"}, lic_headers))
        validate_success(api_client.verify_corrective_action(
            ca1["id"], make_inspector_headers("insp-B")))
        # One corrective (actions[1]) still OPEN -> WATCH
        store = validate_success(api_client.get_store(bundle["store"]["id"], ADMIN))
        assert store["compliance_posture"] == "WATCH"
        assert store["operating_status"] == "OPERATING"


class TestStoreParallelDimensionsIndependent:
    def test_failed_inspection_moves_posture_only_then_suspend_moves_operating_only(self):
        """PRD §3.3: "An inspection failure can move posture to `WATCH` without
        touching operating status; a manual suspension can move operating
        status to `SUSPENDED` without touching posture."

        Design: Difficulty/non_linear_state_machine/store_parallel_dimensions_independent
        """
        set_clock()
        bundle = setup_operating_store()
        store_id = bundle["store"]["id"]
        inspection = schedule_inspection(store_id)
        completed = complete_inspection(
            inspection["id"],
            {"BEVERAGE_QUALITY": 60, "FOOD_SAFETY": 90,
             "BRAND_PRESENTATION": 90, "SERVICE_SPEED": 90},
        )
        # composite = round_half_up(60*30 + 90*40 + 90*20 + 90*10)/100
        #           = (1800+3600+1800+900)/100 = 8100/100 = 81
        assert completed["result"] == "FAILED"
        assert completed["total_score"] == 81
        store = validate_success(api_client.get_store(store_id, ADMIN))
        assert store["operating_status"] == "OPERATING"
        assert store["compliance_posture"] == "WATCH"
        # manual suspend: operating moves, posture stays
        validate_success(api_client.suspend_store(store_id, ADMIN))
        store = validate_success(api_client.get_store(store_id, ADMIN))
        assert store["operating_status"] == "SUSPENDED"
        assert store["compliance_posture"] == "WATCH"
        # resume: operating restored, posture unchanged
        validate_success(api_client.resume_store(store_id, ADMIN))
        store = validate_success(api_client.get_store(store_id, ADMIN))
        assert store["operating_status"] == "OPERATING"
        assert store["compliance_posture"] == "WATCH"

    def test_dimensions_recompute_independently_on_resume(self):
        """PRD §3.3: "`operating_status` walks `PROVISIONING → CERT_PENDING →
        OPERATING`, may drop to `SUSPENDED`, and ends at `DELICENSED`.
        `compliance_posture` is a computed judgment — `GOOD_STANDING`,
        `WATCH`, or `PROBATION` — recomputed by events described in §3.6."

        Design: Difficulty/non_linear_state_machine/store_parallel_dimensions_independent
        """
        set_clock()
        bundle = setup_operating_store()
        store_id = bundle["store"]["id"]
        inspection = schedule_inspection(store_id)
        complete_inspection(
            inspection["id"],
            {"BEVERAGE_QUALITY": 60, "FOOD_SAFETY": 90,
             "BRAND_PRESENTATION": 90, "SERVICE_SPEED": 90},
        )
        actions = list_corrective_actions_for_inspection(inspection["id"])
        assert len(actions) == 1
        # verify the corrective by a different inspector -> posture back to GOOD_STANDING
        lic_headers = make_licensee_manager_headers(bundle["licensee_id"])
        validate_success(api_client.submit_corrective_action_evidence(
            actions[0]["id"], {"evidence_note": "done"}, lic_headers))
        validate_success(api_client.verify_corrective_action(
            actions[0]["id"], make_inspector_headers("insp-B")))
        store = validate_success(api_client.get_store(store_id, ADMIN))
        assert store["operating_status"] == "OPERATING"
        assert store["compliance_posture"] == "GOOD_STANDING"
