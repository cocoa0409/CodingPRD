"""Teams, consent lifecycle, coach dashboard projection, and membership removal."""
from test_helpers import (
    ApiErrorId,
    create_member_with_term,
    make_coach_headers,
    make_member_headers,
    set_clock,
    setup_member_with_metric_set,
    setup_team_membership_with_consent,
    setup_team_with_membership,
    validate_error,
    validate_success,
)


class TestConsentOcc:
    def test_occ_stale_version_on_consent_grant(self, api, anonymous_headers):
        """PRD: "A consent grant or revoke on a team membership must carry
        expected_team_membership_version equal to that membership's current
        version."
        PRD: "In both cases, a mismatch between the supplied expectation and the
        parent's current version is rejected with ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/validations/occ_stale_version_on_consent_grant
        """
        member, term = create_member_with_term()
        team, membership = setup_team_with_membership(member["id"], "coach-7")
        headers = make_member_headers(member["id"])
        v0 = membership["version"]
        granted = validate_success(
            api.grant_or_revoke_consent(
                membership["id"],
                {
                    "scope": "STRAIN",
                    "action": "GRANT",
                    "expected_team_membership_version": v0,
                },
                headers,
            )
        )
        v1 = granted["version"]
        assert v1 == v0 + 1
        resp = api.grant_or_revoke_consent(
            membership["id"],
            {
                "scope": "SLEEP",
                "action": "GRANT",
                "expected_team_membership_version": v0,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        granted2 = validate_success(
            api.grant_or_revoke_consent(
                membership["id"],
                {
                    "scope": "SLEEP",
                    "action": "GRANT",
                    "expected_team_membership_version": v1,
                },
                headers,
            )
        )
        scopes = {e["scope"]: e["status"] for e in granted2["consent_scopes"]}
        assert scopes["STRAIN"] == "GRANTED"
        assert scopes["SLEEP"] == "GRANTED"

    def test_occ_stale_consent_does_not_mutate_membership(self, api, anonymous_headers):
        """PRD: "A consent grant or revoke on a team membership must carry
        expected_team_membership_version equal to that membership's current
        version."
        PRD: "Either action increments the membership's version by one — which is
        exactly why the OCC rule of §2.6 exists for this endpoint."

        Design: Corner/validations/occ_stale_version_on_consent_grant
        """
        member, term = create_member_with_term()
        team, membership = setup_team_with_membership(member["id"], "coach-7")
        headers = make_member_headers(member["id"])
        v0 = membership["version"]
        granted = validate_success(
            api.grant_or_revoke_consent(
                membership["id"],
                {
                    "scope": "STRAIN",
                    "action": "GRANT",
                    "expected_team_membership_version": v0,
                },
                headers,
            )
        )
        api.grant_or_revoke_consent(
            membership["id"],
            {
                "scope": "SLEEP",
                "action": "GRANT",
                "expected_team_membership_version": v0,
            },
            headers,
        )
        membership_after = validate_success(
            api.get_team_membership(membership["id"], make_coach_headers("coach-7"))
        )
        assert membership_after["version"] == granted["version"]


class TestConsentExpiry:
    def test_consent_expiry_via_clock(self, api, anonymous_headers):
        """PRD: "When the logical clock advances past an entry's expires_on, the
        entry's status becomes EXPIRED."
        PRD: "each metric field independently shows the member's latest metric
        value (by day_on descending) when that scope's consent entry exists with
        status GRANTED and either has no expires_on or an expires_on on or after
        today; failing that, the field is null."

        Design: Corner/state_machines/consent_expiry_via_clock
        """
        member, term, device, metric_set = setup_member_with_metric_set(
            avg_hr=100, hrv_ms=100, resting_hr=50, sleep_minutes=480
        )
        team, membership = setup_team_membership_with_consent(
            member["id"], "coach-9", "STRAIN", expires_on="2026-09-05"
        )
        coach = make_coach_headers("coach-9")
        dash = validate_success(api.get_team_dashboard(team["id"], coach))
        assert dash["rows"][0]["strain_score"] == 10.0
        set_clock("2026-09-06T00:00:00Z")
        dash = validate_success(api.get_team_dashboard(team["id"], coach))
        assert dash["rows"][0]["strain_score"] is None

    def test_consent_expiry_flips_entry_status_to_expired(self, api, anonymous_headers):
        """PRD: "When the logical clock advances past an entry's expires_on, the
        entry's status becomes EXPIRED."

        Design: Corner/state_machines/consent_expiry_via_clock
        """
        member, term, device, metric_set = setup_member_with_metric_set()
        team, membership = setup_team_membership_with_consent(
            member["id"], "coach-9", "STRAIN", expires_on="2026-09-05"
        )
        set_clock("2026-09-06T00:00:00Z")
        membership_after = validate_success(
            api.get_team_membership(membership["id"], make_coach_headers("coach-9"))
        )
        entries = {e["scope"]: e["status"] for e in membership_after["consent_scopes"]}
        assert entries["STRAIN"] == "EXPIRED"


class TestDashboardProjection:
    def test_dashboard_scope_projection_partial_consent(self, api, anonymous_headers):
        """PRD: "Otherwise suppressed is false, and each metric field independently
        shows the member's latest metric value (by day_on descending) when that
        scope's consent entry exists with status GRANTED and either has no
        expires_on or an expires_on on or after today; failing that, the field is
        null."

        Design: Corner/endpoints/dashboard_scope_projection_partial_consent
        """
        member, term, device, metric_set = setup_member_with_metric_set(
            avg_hr=100, hrv_ms=100, resting_hr=50, sleep_minutes=480
        )
        team, membership = setup_team_membership_with_consent(
            member["id"], "coach-3", "STRAIN"
        )
        dash = validate_success(
            api.get_team_dashboard(team["id"], make_coach_headers("coach-3"))
        )
        assert len(dash["rows"]) == 1
        row = dash["rows"][0]
        assert row["suppressed"] is False
        assert row["strain_score"] == 10.0
        assert row["recovery_score"] is None
        assert row["sleep_performance_pct"] is None

    def test_dashboard_row_gated_by_member_term_status(self, api, anonymous_headers):
        """PRD: "Omission happens when the member owns no membership term at all,
        or when the member's latest term (ordering by term created_at ascending,
        latest last) is CANCELLED_EARLY or COMPLETED."

        Design: Difficulty/cross_entity_state_dependency/dashboard_row_gated_by_member_term_status
        """
        member, term, device, metric_set = setup_member_with_metric_set(
            avg_hr=100, hrv_ms=100, resting_hr=50, sleep_minutes=480
        )
        team, membership = setup_team_membership_with_consent(
            member["id"], "coach-2", "RECOVERY"
        )
        coach = make_coach_headers("coach-2")
        dash = validate_success(api.get_team_dashboard(team["id"], coach))
        assert len(dash["rows"]) == 1
        assert dash["rows"][0]["recovery_score"] == 67
        validate_success(
            api.cancel_term(term["id"], make_member_headers(member["id"]))
        )
        dash = validate_success(api.get_team_dashboard(team["id"], coach))
        assert dash["rows"] == []

    def test_dashboard_row_disappears_on_cancelled_term(self, api, anonymous_headers):
        """PRD: "For each such membership the dashboard either emits one row
        carrying membership_id, member_id, a suppressed flag, and the three metric
        fields, or omits the member entirely. Omission happens when the member
        owns no membership term at all, or when the member's latest term
        (ordering by term created_at ascending, latest last) is CANCELLED_EARLY
        or COMPLETED."

        Design: Difficulty/cross_entity_state_dependency/dashboard_row_gated_by_member_term_status
        """
        member, term = create_member_with_term()
        team, membership = setup_team_with_membership(member["id"], "coach-2")
        validate_success(
            api.cancel_term(term["id"], make_member_headers(member["id"]))
        )
        dash = validate_success(
            api.get_team_dashboard(team["id"], make_coach_headers("coach-2"))
        )
        assert dash["rows"] == []


class TestMembershipRemoval:
    def test_removal_revokes_consents(self, api, anonymous_headers):
        """PRD: "Either the owning coach or the member themself removes an ACTIVE
        membership; the membership becomes REMOVED (terminal), and every consent
        entry still GRANTED flips to REVOKED — consent dies with the membership."

        Design: Corner/endpoints/removal_revokes_consents
        """
        member, term = create_member_with_term()
        team, membership = setup_team_membership_with_consent(
            member["id"], "coach-4", "SLEEP"
        )
        removed = validate_success(
            api.remove_team_membership(
                membership["id"], make_coach_headers("coach-4")
            )
        )
        assert removed["membership_status"] == "REMOVED"
        assert removed["consent_scopes"], "expected consent entries to remain listed"
        assert all(e["status"] == "REVOKED" for e in removed["consent_scopes"])

    def test_removal_by_member_self_also_revokes_consents(self, api, anonymous_headers):
        """PRD: "Either the owning coach or the member themself removes an ACTIVE
        membership; the membership becomes REMOVED (terminal), and every consent
        entry still GRANTED flips to REVOKED — consent dies with the membership."

        Design: Corner/endpoints/removal_revokes_consents
        """
        member, term = create_member_with_term()
        team, membership = setup_team_membership_with_consent(
            member["id"], "coach-4", "SLEEP"
        )
        removed = validate_success(
            api.remove_team_membership(
                membership["id"], make_member_headers(member["id"])
            )
        )
        assert removed["membership_status"] == "REMOVED"
        assert all(e["status"] == "REVOKED" for e in removed["consent_scopes"])
