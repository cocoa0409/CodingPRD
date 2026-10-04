"""Editor version lifecycle: terminal lockdown, sunset cascade, risk recompute."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_org_owner_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_org,
    create_editor_version,
    create_project,
    ship_project,
    setup_shipped_project,
    setup_personal_and_pro_tiers,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Queue B — state_machines / terminal_sunset_lockdown_no_further_transitions
# ---------------------------------------------------------------------------

class TestSunsetTerminalLockdown:
    def test_sunset_rejects_further_transitions(self, api):
        """PRD §3.3: "Finally, from DEPRECATED a version reaches its terminal SUNSET
        state once its lts_window_end lies at least 12 months in the past".

        Design: Corner/state_machines/terminal_sunset_lockdown_no_further_transitions
        """
        set_clock("2026-09-01T00:00:00Z")
        ev = create_editor_version("2021.3.1f1", "2021.3", "2023-01-01")
        get_success_data(
            api.transition_editor_version(
                ev["id"],
                {"target_status": "LTS",
                 "lts_window_start": "2023-06-01", "lts_window_end": "2024-06-01"},
                ADMIN,
            ),
            200,
        )
        get_success_data(
            api.transition_editor_version(ev["id"], {"target_status": "DEPRECATED"}, ADMIN), 200
        )
        sunset = get_success_data(
            api.transition_editor_version(ev["id"], {"target_status": "SUNSET"}, ADMIN), 200
        )
        assert sunset["support_status"] == "SUNSET"

        resp = api.transition_editor_version(
            ev["id"],
            {"target_status": "LTS",
             "lts_window_start": "2026-01-01", "lts_window_end": "2027-01-01"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_success_data(api.get_editor_version(ev["id"], ADMIN), 200)
        assert after["support_status"] == "SUNSET"


# ---------------------------------------------------------------------------
# Queue B — state_machines / sunset_cascade_freezes_shipped_projects
# ---------------------------------------------------------------------------

class TestSunsetCascade:
    def test_sunset_freezes_shipped_project_and_blocks_reports(self, api):
        """PRD §3.3: "A project whose pinned editor version reaches SUNSET transitions
        from SHIPPED to FROZEN: no new install report may be created for it (attempts
        are rejected with ERR_PROJECT_FROZEN)".

        Design: Corner/state_machines/sunset_cascade_freezes_shipped_projects
        """
        set_clock("2026-09-01T00:00:00Z")
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Sunset Co", contact_email="su@x.com")
        ev = create_editor_version("2020.3.1f1", "2020.3", "2022-01-01")
        project = create_project(org, ev["id"], title="Game S")
        ship_project(org, project)

        get_success_data(
            api.transition_editor_version(
                ev["id"],
                {"target_status": "LTS",
                 "lts_window_start": "2022-06-01", "lts_window_end": "2023-06-01"},
                ADMIN,
            ),
            200,
        )
        get_success_data(
            api.transition_editor_version(ev["id"], {"target_status": "DEPRECATED"}, ADMIN), 200
        )
        get_success_data(
            api.transition_editor_version(ev["id"], {"target_status": "SUNSET"}, ADMIN), 200
        )

        owner = make_org_owner_headers(org["id"])
        frozen = get_success_data(api.get_project(project["id"], owner), 200)
        assert frozen["project_status"] == "FROZEN"

        resp = api.create_install_report(
            project["id"],
            {
                "period_month": "2026-09",
                "new_device_installs": 5,
                "reinstalls": 0,
                "bundle_installs": 0,
                "expected_project_version": frozen["version"],
            },
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_FROZEN.value)


# ---------------------------------------------------------------------------
# Queue B — calculations / upgrade_risk_score_weighted_recompute_on_lts
# ---------------------------------------------------------------------------

class TestUpgradeRiskScore:
    def test_risk_score_initial_and_after_lts(self, api):
        """PRD §3.3: "The support weight contributes up to 25 points: SUPPORTED weighs
        0, LTS weighs 1, DEPRECATED weighs 2, and SUNSET weighs 3, and the contribution
        is 25 times the weight divided by 3. Age contributes up to 20 points: the
        number of whole months since released_on, divided by 36 and capped at 1, times
        20."
        PRD §3.3: "The four contributions are summed, capped at 100, and rounded half
        up to an integer. The score is recomputed on ship, on every support-status
        transition of the pinned version, and on every install acceptance".

        Design: Corner/calculations/upgrade_risk_score_weighted_recompute_on_lts
        """
        set_clock("2026-09-01T00:00:00Z")
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Risk Co", contact_email="r@x.com")
        ev = create_editor_version("2022.3.30f1", "2022.3", "2025-09-01")
        project = create_project(org, ev["id"], title="Game R")
        shipped = ship_project(org, project)
        # SUPPORTED (0 * 25/3) + age 12/36 * 20 = 6.67 + 0 installs + 0 APIs = 7.
        assert shipped["upgrade_risk_score"] == 7

        get_success_data(
            api.transition_editor_version(
                ev["id"],
                {"target_status": "LTS",
                 "lts_window_start": "2026-09-01", "lts_window_end": "2028-09-01"},
                ADMIN,
            ),
            200,
        )
        owner = make_org_owner_headers(org["id"])
        after = get_success_data(api.get_project(project["id"], owner), 200)
        # LTS (25 * 1/3 = 8.33) + 6.67 = 15.0 -> 15.
        assert after["upgrade_risk_score"] == 15
