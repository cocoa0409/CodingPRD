"""Validation priority ordering across the fixed evaluation chain."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_confirmed_event,
    ingest_event,
    make_safety_manager_headers,
    register_clip,
    review_event,
    setup_base,
    upload_clip,
    validate_error,
)
from test_helpers.factories import create_camera_policy_payload

MANAGER = TEST_USERS["safety_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestStateBeatsPrivacyGate:
    def test_state_error_beats_privacy_business_safety(self, api, safety_manager_headers):
        """PRD §2.10: "State-machine legality is checked next
        (`ERR_INVALID_STATE`), then the safety and privacy gates (the
        inward-footage gate, segregation of duties on exoneration decisions,
        and the litigation-hold block on purge), then the temporal window
        rules ... Because the safety gate runs before the temporal and
        referential checks, a privacy-blocked inward review surfaces
        `ERR_INWARD_FOOTAGE_RESTRICTED` rather than being masked by a posture
        or driver-status failure that would also apply."
        PRD §3.4: "Dismissing an event moves it from `IN_REVIEW` to
        `DISMISSED` and removes it from the provisional scoring input set."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_privacy_business_safety
        """
        base = setup_base()
        # Event carrying an INWARD clip (privacy gate passed at registration).
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="DISTRACTION", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(
            event["id"], camera_angle="INWARD", captured_at="2026-08-30T00:00:00Z"
        )
        upload_clip(clip["id"])
        review_event(event["id"], "DISMISS", rationale="not actionable")
        # Swap in a policy that disables inward capture, so the privacy gate
        # would now fail if it were ever reached.
        from test_helpers import validate_success

        resp = api.create_camera_policy(
            create_camera_policy_payload(
                base["fleet"]["id"], name="Privacy-First Policy",
                inward_capture_enabled=False,
            ),
            ADMIN,
        )
        policy2 = validate_success(resp, 201)
        validate_success(api.activate_camera_policy(policy2["id"], ADMIN), 200)
        current = validate_success(api.get_safety_event(event["id"], MANAGER), 200)
        resp = api.review_safety_event(
            event["id"],
            {
                "action": "CONFIRM",
                "rationale": "reconsidered",
                "expected_event_version": current["version"],
            },
            safety_manager_headers,
        )
        # DISMISSED has no CONFIRM transition: state check wins over the
        # privacy gate.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_safety_event(event["id"], MANAGER), 200)
        assert after["status"] == "DISMISSED"
        assert after["review_count"] == 1

    def test_reopen_after_dismiss_not_blocked_by_privacy_swap(self, api, safety_manager_headers):
        """PRD §3.4: "A `RECLASSIFIED` or `DISMISSED` event may be returned to
        `IN_REVIEW` by the reopen action; reopening a reclassified event
        leaves `confirmed_at` unset as it was."
        PRD §2.10: "State-machine legality is checked next
        (`ERR_INVALID_STATE`), then the safety and privacy gates (the
        inward-footage gate, segregation of duties on exoneration decisions,
        and the litigation-hold block on purge)."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_privacy_business_safety
        """
        from test_helpers import validate_success

        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="DISTRACTION", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(
            event["id"], camera_angle="INWARD", captured_at="2026-08-30T00:00:00Z"
        )
        upload_clip(clip["id"])
        review_event(event["id"], "DISMISS", rationale="not actionable")
        policy2 = validate_success(
            api.create_camera_policy(
                create_camera_policy_payload(
                    base["fleet"]["id"], name="Privacy-First Policy",
                    inward_capture_enabled=False,
                ),
                ADMIN,
            ),
            201,
        )
        validate_success(api.activate_camera_policy(policy2["id"], ADMIN), 200)
        # REOPEN from DISMISSED is a legal transition and is not one of the
        # gated operations; it must succeed even under the new policy.
        reopened = review_event(event["id"], "REOPEN", rationale="reconsidered")
        assert reopened["status"] == "IN_REVIEW"
