"""Attribution lifecycle claims: initial state, saturation cascade, disenroll
bubble-up, the disenroll-reattribute revision loop, terminal lockdown, OCC,
activation idempotency, and the default logical clock."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_attribution,
    create_active_attribution,
    create_attribution,
    create_care_team_payload,
    create_center,
    create_health_plan,
    create_open_center,
    create_outreach_event_payload,
    create_patient,
    create_room_payload,
    create_saturated_center,
    get_success_data,
    set_clock,
    setup_panel_with_active_patient,
    validate_error,
    validate_success,
)


def _version_error(resp):
    """The OCC version check may run before or after the state check; both
    outcomes are PRD-consistent here."""
    return validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


class TestInitialState:
    def test_attribution_initial_state_pending(self, api, enrollment_coordinator_headers):
        """PRD §3.4: "Creation sets the row's `status` to `PENDING` and, when an event is
        named, increments that event's `attributed_signups`."
        PRD §3.4: "Disenrollment — the `ACTIVE → DISENROLLED` transition by an
        `EnrollmentCoordinator` — requires the attribution to be `ACTIVE`
        (`ERR_ATTRIBUTION_NOT_ACTIVE`), stamps the row's `disenrolled_month` with the
        current logical month."

        Design: Corner/state_machines/attribution_initial_state_pending
        """
        center, team, room = create_open_center()
        plan = create_health_plan()
        patient = create_patient()
        attr = validate_success(
            api.create_attribution(
                {
                    "patient_id": patient["id"],
                    "health_plan_id": plan["id"],
                    "care_team_id": team["id"],
                    "effective_month": "2026-09",
                },
                enrollment_coordinator_headers,
            ),
            201,
        )
        assert attr["status"] == "PENDING"
        assert attr["disenrolled_month"] is None


class TestActivationSaturationCascade:
    def test_activation_panel_breach_saturates_center_and_waitlists(
        self, api, enrollment_coordinator_headers
    ):
        """PRD §2.9: "When `panel_fill_ratio` reaches at least 1.0000 — at any attribution
        activation or at a monthly close — the center transitions from `OPEN` to
        `SATURATED`, every care team whose `active_panel_count` has reached its
        `panel_cap` has `accepting` set to false, and existing `PENDING` attributions
        targeting full teams transition to `WAITLISTED`."

        Design: Difficulty/transitive_cascade/activation_panel_breach_saturates_center_and_waitlists
        """
        s = create_saturated_center(cap=2)
        assert s["center"]["status"] == "SATURATED"
        assert s["team"]["accepting"] is False
        assert s["team"]["waitlist_depth"] == 2
        for attr in s["waitlisted"]:
            assert attr["status"] == "WAITLISTED"

    def test_saturation_cascade_waitlist_depth_and_accepting_flag(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §2.9: "When `panel_fill_ratio` reaches at least 1.0000 — at any attribution
        activation or at a monthly close — the center transitions from `OPEN` to
        `SATURATED`, every care team whose `active_panel_count` has reached its
        `panel_cap` has `accepting` set to false, and existing `PENDING` attributions
        targeting full teams transition to `WAITLISTED`."
        PRD §3.4: "When activation is attempted against a full team and overflow policy is
        `WAITLIST`, the attribution instead moves `PENDING → WAITLISTED` and the team's
        `waitlist_depth` increments; the system performs the same transition during the
        saturation cascade."

        Design: Difficulty/transitive_cascade/activation_panel_breach_saturates_center_and_waitlists
        """
        s = create_saturated_center(cap=2)
        # Depth-3 observable chain: activation -> team full -> center SATURATED
        # -> remaining PENDING attributions flipped WAITLISTED with depth 2.
        assert s["team"]["active_panel_count"] == 2
        assert s["team"]["waitlist_depth"] == 2
        assert s["center"]["status"] == "SATURATED"
        # Waitlisted attributions are not activated: they rest in WAITLISTED.
        statuses = sorted(a["status"] for a in s["waitlisted"])
        assert statuses == ["WAITLISTED", "WAITLISTED"]
        for a in s["active"]:
            refreshed = get_success_data(
                api.get_attribution(a["id"], enrollment_coordinator_headers)
            )
            assert refreshed["status"] == "ACTIVE"

    def test_saturation_boundary_fill_ratio_exactly_one(
        self, api, network_operator_headers
    ):
        """PRD §2.9: "When `panel_fill_ratio` reaches at least 1.0000 — at any attribution
        activation or at a monthly close — the center transitions from `OPEN` to
        `SATURATED`, every care team whose `active_panel_count` has reached its
        `panel_cap` has `accepting` set to false, and existing `PENDING` attributions
        targeting full teams transition to `WAITLISTED`."

        Design: Difficulty/boundary_precision_check/panel_fill_ratio_exactly_one_triggers_saturation
        """
        center, team, room = create_open_center()
        get_success_data(api.patch_care_team(team["id"], {"panel_cap": 2}, network_operator_headers))
        plan = create_health_plan()
        p1 = create_patient(full_name="One")
        p2 = create_patient(full_name="Two")
        a1 = create_attribution(p1["id"], plan["id"], team["id"])
        a2 = create_attribution(p2["id"], plan["id"], team["id"])

        activate_attribution(a1["id"])
        center_mid = get_success_data(api.get_center(center["id"], network_operator_headers))
        assert center_mid["status"] == "OPEN", "ratio 0.5000 must not saturate"
        assert center_mid["panel_fill_ratio"] == pytest.approx(0.5, abs=1e-9)

        activate_attribution(a2["id"])
        center_full = get_success_data(api.get_center(center["id"], network_operator_headers))
        assert center_full["panel_fill_ratio"] == pytest.approx(1.0, abs=1e-9)
        assert center_full["status"] == "SATURATED", "ratio exactly 1.0000 must saturate"

    def test_half_fill_leaves_center_open(self, api, network_operator_headers):
        """PRD §2.9: "When `panel_fill_ratio` reaches at least 1.0000 — at any attribution
        activation or at a monthly close — the center transitions from `OPEN` to
        `SATURATED`, every care team whose `active_panel_count` has reached its
        `panel_cap` has `accepting` set to false, and existing `PENDING` attributions
        targeting full teams transition to `WAITLISTED`."
        PRD §2.9: "A center's `panel_fill_ratio` is the sum of `ACTIVE` panel member
        counts across the center's care teams divided by the sum of those teams'
        `panel_cap` values, rounded half-up to 4 decimal places."

        Design: Difficulty/boundary_precision_check/panel_fill_ratio_exactly_one_triggers_saturation
        """
        center, team, room = create_open_center()
        get_success_data(api.patch_care_team(team["id"], {"panel_cap": 2}, network_operator_headers))
        plan = create_health_plan()
        p1 = create_patient(full_name="Only")
        a1 = create_attribution(p1["id"], plan["id"], team["id"])
        activate_attribution(a1["id"])

        center_mid = get_success_data(api.get_center(center["id"], network_operator_headers))
        assert center_mid["panel_fill_ratio"] == pytest.approx(0.5, abs=1e-9)
        assert center_mid["status"] == "OPEN"
        team_mid = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        assert team_mid["accepting"] is True

    def test_center_open_gated_on_team_and_room_existence(
        self, api, network_operator_headers
    ):
        """PRD §3.1: "Opening the center — the `PRE_OPEN → OPEN` transition performed by a
        `NetworkOperator` — requires the center to still be `PRE_OPEN` (otherwise
        `ERR_CENTER_NOT_PRE_OPEN`), to have at least one care team
        (`ERR_CENTER_HAS_NO_TEAMS`), and to have at least one room
        (`ERR_CENTER_HAS_NO_ROOMS`)."

        Design: Difficulty/cross_entity_state_dependency/center_open_gated_on_team_and_room_existence
        """
        center = create_center(name="X", neighborhood_code="CHI-X", opened_on="2026-01-01")
        validate_success(
            api.create_room(center["id"], create_room_payload(room_label="R1"),
                            network_operator_headers),
            201,
        )
        resp = api.open_center(center["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_CENTER_HAS_NO_TEAMS.value, expected_status=409)
        center_after = get_success_data(api.get_center(center["id"], network_operator_headers))
        assert center_after["status"] == "PRE_OPEN"

    def test_center_open_gated_on_room_existence(self, api, network_operator_headers):
        """PRD §3.1: "Opening the center — the `PRE_OPEN → OPEN` transition performed by a
        `NetworkOperator` — requires the center to still be `PRE_OPEN` (otherwise
        `ERR_CENTER_NOT_PRE_OPEN`), to have at least one care team
        (`ERR_CENTER_HAS_NO_TEAMS`), and to have at least one room
        (`ERR_CENTER_HAS_NO_ROOMS`)."

        Design: Difficulty/cross_entity_state_dependency/center_open_gated_on_team_and_room_existence
        """
        center = create_center(name="Y", neighborhood_code="CHI-Y", opened_on="2026-01-01")
        validate_success(
            api.create_care_team(center["id"], create_care_team_payload(),
                                 network_operator_headers),
            201,
        )
        resp = api.open_center(center["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_CENTER_HAS_NO_ROOMS.value, expected_status=409)
        center_after = get_success_data(api.get_center(center["id"], network_operator_headers))
        assert center_after["status"] == "PRE_OPEN"


class TestDisenrollBubbleUp:
    def test_disenroll_bubbles_center_from_saturated_to_open_and_promotes_waitlist(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §3.4: "If the center was `SATURATED` and the fill ratio drops below 0.9000,
        the center returns to `OPEN` and the waitlist promotion sweep runs, promoting the
        earliest-`created_at` `WAITLISTED` rows to `PENDING` while headroom remains."

        Design: Corner/state_machines/disenroll_bubbles_center_from_saturated_to_open_and_promotes_waitlist
        """
        s = create_saturated_center(cap=2)
        victim = s["active"][0]
        waitlisted_first = s["waitlisted"][0]

        validate_success(
            api.disenroll_attribution(victim["id"], enrollment_coordinator_headers), 200
        )
        center = get_success_data(api.get_center(s["center"]["id"], network_operator_headers))
        assert center["status"] == "OPEN"

        promoted = get_success_data(
            api.get_attribution(waitlisted_first["id"], enrollment_coordinator_headers)
        )
        assert promoted["status"] == "PENDING"
        team = get_success_data(api.get_care_team(s["team"]["id"], network_operator_headers))
        assert team["waitlist_depth"] == 1

    def test_disenrolled_attribution_cannot_disenroll_again(
        self, api, enrollment_coordinator_headers
    ):
        """PRD §3.4: "Disenrollment — the `ACTIVE → DISENROLLED` transition by an
        `EnrollmentCoordinator` — requires the attribution to be `ACTIVE`
        (`ERR_ATTRIBUTION_NOT_ACTIVE`)."

        Design: Corner/state_machines/terminal_state_lockdown_disenrolled_attribution_cannot_disenroll_again
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        validate_success(
            api.disenroll_attribution(attr["id"], enrollment_coordinator_headers), 200
        )
        resp = api.disenroll_attribution(attr["id"], enrollment_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ATTRIBUTION_NOT_ACTIVE.value, expected_status=409)


class TestReattributeCycle:
    def test_attribution_disenroll_reattribute_cycle(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §3.4: "The old row moves to `REATTRIBUTED` and becomes a historical link; the
        new `PENDING` row is the live record and may then be activated normally."

        Design: Difficulty/non_linear_state_machine/attribution_disenroll_reattribute_cycle
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        validate_success(
            api.disenroll_attribution(attr["id"], enrollment_coordinator_headers), 200
        )
        new_attr = create_attribution(
            patient["id"], plan["id"], team["id"], effective_month="2026-11"
        )
        old = validate_success(
            api.reattribute_attribution(
                attr["id"], {"new_attribution_id": new_attr["id"]},
                enrollment_coordinator_headers,
            ),
            200,
        )
        assert old["status"] == "REATTRIBUTED"

        still_pending = get_success_data(
            api.get_attribution(new_attr["id"], enrollment_coordinator_headers)
        )
        assert still_pending["status"] == "PENDING"

        set_clock("2026-11-01T00:00:00Z")
        activated = activate_attribution(new_attr["id"])
        assert activated["status"] == "ACTIVE"

    def test_reattribute_requires_month_after_disenroll(
        self, api, enrollment_coordinator_headers
    ):
        """PRD §3.4: "the new row's `effective_month` must be strictly after the old row's
        `disenrolled_month` (`ERR_REATTRIBUTION_MONTH_NOT_AFTER_DISENROLL`)."

        Design: Difficulty/non_linear_state_machine/attribution_disenroll_reattribute_cycle
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        validate_success(
            api.disenroll_attribution(attr["id"], enrollment_coordinator_headers), 200
        )
        # disenrolled_month is the current logical month (2026-09); an equal
        # effective_month is not strictly after.
        new_attr = create_attribution(
            patient["id"], plan["id"], team["id"], effective_month="2026-09"
        )
        resp = api.reattribute_attribution(
            attr["id"], {"new_attribution_id": new_attr["id"]},
            enrollment_coordinator_headers,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_REATTRIBUTION_MONTH_NOT_AFTER_DISENROLL.value,
            expected_status=422,
        )


class TestPanelCountInvariant:
    def test_disenroll_then_reattribute_preserves_panel_count(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §3.4: "Disenrollment — the `ACTIVE → DISENROLLED` transition by an
        `EnrollmentCoordinator` — requires the attribution to be `ACTIVE`
        (`ERR_ATTRIBUTION_NOT_ACTIVE`), stamps the row's `disenrolled_month` with the
        current logical month, decrements the team's `active_panel_count`, and increments
        the team's `version`."
        PRD §3.4: "The old row moves to `REATTRIBUTED` and becomes a historical link; the
        new `PENDING` row is the live record and may then be activated normally."

        Design: Difficulty/compensating_invariant/disenroll_then_reattribute_preserves_panel_count
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        team_before = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        n = team_before["active_panel_count"]
        assert n == 1

        validate_success(
            api.disenroll_attribution(attr["id"], enrollment_coordinator_headers), 200
        )
        team_after_disenroll = get_success_data(
            api.get_care_team(team["id"], network_operator_headers)
        )
        assert team_after_disenroll["active_panel_count"] == n - 1

        new_attr = create_attribution(
            patient["id"], plan["id"], team["id"], effective_month="2026-11"
        )
        validate_success(
            api.reattribute_attribution(
                attr["id"], {"new_attribution_id": new_attr["id"]},
                enrollment_coordinator_headers,
            ),
            200,
        )
        set_clock("2026-11-01T00:00:00Z")
        activate_attribution(new_attr["id"])

        team_final = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        assert team_final["active_panel_count"] == n
        assert team_final["waitlist_depth"] == 0

    def test_disenroll_decrements_and_reattivation_restores_panel_count(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §3.4: "Disenrollment — the `ACTIVE → DISENROLLED` transition by an
        `EnrollmentCoordinator` — requires the attribution to be `ACTIVE`
        (`ERR_ATTRIBUTION_NOT_ACTIVE`), stamps the row's `disenrolled_month` with the
        current logical month, decrements the team's `active_panel_count`, and increments
        the team's `version`."
        PRD §3.4: "A successful activation increments the team's `active_panel_count` by 1
        and the team's `version` by 1, and — per §2.9 — triggers the center saturation
        cascade if the fill ratio reaches 1.0000."

        Design: Difficulty/compensating_invariant/disenroll_then_reattribute_preserves_panel_count
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        second = create_patient(full_name="Second")
        attr2 = create_active_attribution(second["id"], plan["id"], team["id"])
        team_n = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        n = team_n["active_panel_count"]
        assert n == 2

        disenrolled = validate_success(
            api.disenroll_attribution(attr["id"], enrollment_coordinator_headers), 200
        )
        assert disenrolled["status"] == "DISENROLLED"
        assert disenrolled["disenrolled_month"] == "2026-09"
        team_minus = get_success_data(
            api.get_care_team(team["id"], network_operator_headers)
        )
        assert team_minus["active_panel_count"] == n - 1

        new_attr = create_attribution(
            patient["id"], plan["id"], team["id"], effective_month="2026-11"
        )
        validate_success(
            api.reattribute_attribution(
                attr["id"], {"new_attribution_id": new_attr["id"]},
                enrollment_coordinator_headers,
            ),
            200,
        )
        set_clock("2026-11-01T00:00:00Z")
        activate_attribution(new_attr["id"])
        team_restored = get_success_data(
            api.get_care_team(team["id"], network_operator_headers)
        )
        assert team_restored["active_panel_count"] == n

    def test_second_activation_same_attribution_rejected(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §3.4: "enforces its checks **in order**: first that the attribution is `PENDING` (`ERR_ATTRIBUTION_NOT_PENDING`)."

        Design: Corner/state_machines/second_activation_same_attribution_rejected
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        team_before = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        resp = api.activate_attribution(
            attr["id"],
            {"expected_care_team_version": team_before["version"]},
            enrollment_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ATTRIBUTION_NOT_PENDING.value, expected_status=409)
        team_after = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        assert team_after["active_panel_count"] == team_before["active_panel_count"]


class TestActivationPriorityAndStaleVersion:
    def test_activate_stale_state_beats_panel_quota(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §2.7: "Every mutation passes through a fixed validation cascade, and the
        cascade's ordering is itself a contract — when several checks could fail, the
        first one in this order determines the rejection:"
        PRD §2.7: "6. State preconditions — the target entity sits in the state the
        transition requires (`ERR_INVALID_STATE`, or the transition-specific 409 codes
        named throughout §3)."
        PRD §3.4: "enforces its checks **in order**: first that the attribution is `PENDING` (`ERR_ATTRIBUTION_NOT_PENDING`)."

        Design: Difficulty/priority_pair_validation_conflict/activate_stale_state_vs_panel_quota_conflict
        """
        s = create_saturated_center(cap=2)
        victim = s["active"][0]
        validate_success(
            api.disenroll_attribution(victim["id"], enrollment_coordinator_headers), 200
        )
        # Refill the team to capacity so the quota gate would also fail.
        replacement = create_patient(full_name="Replacement")
        new_attr = create_attribution(
            replacement["id"], s["plan"]["id"], s["team"]["id"]
        )
        activate_attribution(new_attr["id"])
        team_now = get_success_data(
            api.get_care_team(s["team"]["id"], network_operator_headers)
        )
        resp = api.activate_attribution(
            victim["id"],
            {"expected_care_team_version": team_now["version"]},
            enrollment_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ATTRIBUTION_NOT_PENDING.value, expected_status=409)

    def test_activate_pending_on_full_team_reports_quota_not_state(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §3.4: "first that the attribution is `PENDING`
        (`ERR_ATTRIBUTION_NOT_PENDING`); second that `effective_month` is not after the
        current logical month (`ERR_ATTRIBUTION_NOT_YET_EFFECTIVE`); third that the target
        team's `accepting` flag is true (`ERR_TEAM_NOT_ACCEPTING`); fourth that the team's
        `active_panel_count` is still below `panel_cap` (`ERR_PANEL_CAP_REACHED`)."

        Design: Difficulty/priority_pair_validation_conflict/activate_stale_state_vs_panel_quota_conflict
        """
        s = create_saturated_center(cap=2)
        team_now = get_success_data(
            api.get_care_team(s["team"]["id"], network_operator_headers)
        )
        # A PENDING attribution against the saturated (non-accepting, full) team
        # fails the quota-side gates, not the state check. (Attributions created
        # after the saturation cascade start PENDING; only pre-existing PENDING
        # rows were flipped to WAITLISTED by the cascade.)
        late_patient = create_patient(full_name="Late Arrival")
        late_attr = create_attribution(
            late_patient["id"], s["plan"]["id"], s["team"]["id"]
        )
        assert late_attr["status"] == "PENDING"
        resp = api.activate_attribution(
            late_attr["id"],
            {"expected_care_team_version": team_now["version"]},
            enrollment_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEAM_NOT_ACCEPTING.value, expected_status=409)

    def test_activate_with_stale_team_version_rejected(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §2.7: "Activating an attribution requires the request to carry
        `expected_care_team_version` matching the target care team's current `version`.
        If another writer has advanced the team's `version` since the client last read it
        — for example, a panel-cap change or another activation that consumed the final
        headroom — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_version_triggerable
        """
        center, team, room = create_open_center()
        plan = create_health_plan()
        p1 = create_patient(full_name="One")
        p2 = create_patient(full_name="Two")
        a1 = create_attribution(p1["id"], plan["id"], team["id"])
        a2 = create_attribution(p2["id"], plan["id"], team["id"])

        team_seen = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        stale_version = team_seen["version"]

        # A first successful activation advances the team's version by 1.
        validate_success(
            api.activate_attribution(
                a1["id"], {"expected_care_team_version": stale_version},
                enrollment_coordinator_headers,
            ),
            200,
        )
        resp = api.activate_attribution(
            a2["id"], {"expected_care_team_version": stale_version},
            enrollment_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


class TestImmediateConsistency:
    def test_activation_effects_visible_immediately(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §3.4: "A successful activation increments the team's `active_panel_count` by 1
        and the team's `version` by 1, and — per §2.9 — triggers the center saturation
        cascade if the fill ratio reaches 1.0000."

        Design: Corner/consistency_model/activation_effects_visible_immediately
        """
        center, team, room = create_open_center()
        plan = create_health_plan()
        patient = create_patient()
        attr = create_attribution(patient["id"], plan["id"], team["id"])
        team_before = get_success_data(api.get_care_team(team["id"], network_operator_headers))

        activated = validate_success(
            api.activate_attribution(
                attr["id"],
                {"expected_care_team_version": team_before["version"]},
                enrollment_coordinator_headers,
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"

        team_after = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        assert team_after["active_panel_count"] == team_before["active_panel_count"] + 1


class TestDefaultClock:
    def test_clock_default_is_fixed_before_any_set(
        self, api, enrollment_coordinator_headers, network_operator_headers
    ):
        """PRD §2.4: "Before any clock-setting call has been made, the logical clock reads
        exactly `2026-09-01T00:00:00Z` and must not fall back to wall-clock time under any
        circumstance."
        PRD §3.4: "second that `effective_month` is not after the current logical month
        (`ERR_ATTRIBUTION_NOT_YET_EFFECTIVE`)."

        Design: Corner/endpoints/clock_default_is_fixed_before_any_set
        """
        center, team, room = create_open_center()
        plan = create_health_plan()
        p1 = create_patient(full_name="Current Month")
        p2 = create_patient(full_name="Future Month")

        attr_now = create_attribution(p1["id"], plan["id"], team["id"],
                                      effective_month="2026-09")
        activated = activate_attribution(attr_now["id"])
        assert activated["status"] == "ACTIVE"

        attr_future = create_attribution(p2["id"], plan["id"], team["id"],
                                         effective_month="2026-10")
        team_now = get_success_data(api.get_care_team(team["id"], network_operator_headers))
        resp = api.activate_attribution(
            attr_future["id"],
            {"expected_care_team_version": team_now["version"]},
            enrollment_coordinator_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_ATTRIBUTION_NOT_YET_EFFECTIVE.value, expected_status=409
        )


class TestOutreachEventSignups:
    def test_attribution_create_with_outreach_event_increments_signups(
        self, api, enrollment_coordinator_headers
    ):
        """PRD §3.4: "Creation sets the row's `status` to `PENDING` and, when an event is
        named, increments that event's `attributed_signups`."

        Design: Corner/endpoints/attribution_create_with_outreach_event_increments_signups
        """
        center, team, room = create_open_center()
        event = validate_success(
            api.create_outreach_event(
                center["id"],
                create_outreach_event_payload(scheduled_on="2026-09-20"),
                enrollment_coordinator_headers,
            ),
            201,
        )
        assert event["attributed_signups"] == 0

        plan = create_health_plan()
        patient = create_patient()
        validate_success(
            api.create_attribution(
                {
                    "patient_id": patient["id"],
                    "health_plan_id": plan["id"],
                    "care_team_id": team["id"],
                    "effective_month": "2026-09",
                    "outreach_event_id": event["id"],
                },
                enrollment_coordinator_headers,
            ),
            201,
        )
        event_after = get_success_data(
            api.get_outreach_event(event["id"], enrollment_coordinator_headers)
        )
        assert event_after["attributed_signups"] == 1
