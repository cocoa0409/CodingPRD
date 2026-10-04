"""Authentication, role authorization and ownership scope (PRD §2.1, §2.7
tiers 1-4) plus the temporal-beats-fiscal priority pair."""
import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    TEST_USERS,
    accept_offer,
    advance_clock,
    api_client,
    create_cohort_meeting_payload,
    create_mentor,
    create_nominee_payload,
    create_offer,
    create_partner_college_payload,
    create_selected_nominee,
    get_cohort,
    get_nominee,
    get_offer,
    get_scholar,
    get_scholar_for_nominee,
    lifecycle_payload,
    make_faculty_mentor_headers,
    make_nominator_headers,
    make_nominee_headers,
    make_scholar_headers,
    nominate,
    setup_city_with_partner,
    setup_cohort_foundation,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]


class TestAuthentication:
    def test_request_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request that is missing either header, carries a
        malformed header, or names a role outside the declared set is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.7: "Tier 1 — authentication. ... This applies to every
        endpoint."

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        resp = api.get_cohort(MISSING_UUID, headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401, "auth precedes existence — not 404"


class TestRoleAuthorization:
    def test_nominator_cannot_create_partner_college(self, api):
        """PRD §2.1: "A caller whose role is not on an endpoint's
        authorized-role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/partner-colleges is authorized for ProgramAdmin only.

        Design: Corner/rbac/nominator_cannot_create_partner_college
        """
        _program, partner = setup_city_with_partner(quota=5)
        resp = api.create_partner_college(
            create_partner_college_payload(name="Nope College"),
            make_nominator_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_nominator_cannot_submit_assessment_decision(self, api):
        """PRD §2.1: "A caller whose role is not on an endpoint's
        authorized-role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/nominees/{id}/decision is authorized for
        SelectionOfficer and ProgramAdmin.

        Design: Corner/rbac/nominator_cannot_submit_assessment_decision
        """
        program, partner = setup_city_with_partner(quota=5)
        nominee = nominate(program, partner, "Nom One", by_nominator=True)
        resp = api.decide_nominee(
            nominee["id"], {"decision": "ADVANCE"}, make_nominator_headers(partner["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_nominee(nominee["id"])["status"] == "NOMINATED"


class TestOwnershipScope:
    def test_nominee_cannot_accept_other_nominees_offer(self, api):
        """PRD §2.1: "When `X-User-Role` is `Nominee`, `X-User-ID` is the `id`
        of the acting `Nominee`; ownership checks on offers compare the offer's
        `nominee_id` field to `X-User-ID`, so a nominee accepts or declines
        only its own offers."
        PRD §2.1: "Any ownership-scope violation — ... a nominee touching
        another nominee's offer ... — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/nominee_cannot_accept_other_nominees_offer
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        n1 = create_selected_nominee(ctx["program"], ctx["partner"], "Nom One")
        n2 = nominate(ctx["program"], ctx["partner"], "Nom Two", by_nominator=True)
        offer = create_offer(n1["id"], ctx["cohort"]["id"])

        resp = api.accept_offer(offer["id"], make_nominee_headers(n2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_offer(offer["id"])["status"] == "OFFERED"
        scholars, meta = validate_paginated(api.list_scholars(_ADMIN))
        assert meta["total_count"] == 0, "no scholar was created for anyone"

    def test_mentor_cannot_log_meeting_for_foreign_cohort(self, api):
        """PRD §3.8: "the caller must be the cohort's own mentor, meaning the
        cohort's `mentor_id` must equal the caller's `X-User-ID`, otherwise
        `ERR_FORBIDDEN`."
        PRD §2.7: "Tier 4 — ownership scope." (tier 4 precedes the tier-8
        state check that a FORMING cohort would otherwise trip)

        Design: Corner/rbac/mentor_cannot_log_meeting_for_foreign_cohort
        """
        ctx = setup_cohort_foundation(cohort_size=3)  # cohort FORMING under mentor 1
        other_mentor = create_mentor(ctx["college"]["id"], full_name="Prof Other")
        resp = api.create_cohort_meeting(
            create_cohort_meeting_payload(
                ctx["cohort"]["id"], "COHORT",
                "2027-09-10T10:00:00Z", "2027-09-10T11:00:00Z",
            ),
            make_faculty_mentor_headers(other_mentor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403, "ownership (tier 4) beats state (tier 8): not 409"
        assert get_cohort(ctx["cohort"]["id"])["meetings_held_count"] == 0

    def test_scholar_cannot_change_own_standing(self, api):
        """PRD §3.7: "A `Scholar` caller may target only their own record and
        may only set `to_enrollment_status` to `WITHDRAWN`; any other
        combination is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/scholar_cannot_change_own_standing
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        nominee = create_selected_nominee(ctx["program"], ctx["partner"], "Nom One")
        offer = create_offer(nominee["id"], ctx["cohort"]["id"])
        accept_offer(offer)
        scholar = get_scholar_for_nominee(nominee["id"])

        resp = api.scholar_lifecycle(
            scholar["id"],
            lifecycle_payload(to_standing="PROBATION"),
            make_scholar_headers(scholar["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_scholar(scholar["id"])["standing"] == "GOOD_STANDING"


class TestWindowErrorBeatsQuotaError:
    def _setup_window_closed_and_quota_full(self):
        """Partner quota 1 with one live nomination; clock advanced past the
        nomination window close."""
        program, partner = setup_city_with_partner(quota=1)
        nominate(program, partner, "Nom One", by_nominator=True)
        advance_clock("2026-12-01T00:00:00Z")
        return program, partner

    def test_temporal_error_wins_over_quota_error(self, api):
        """PRD §2.7: "the lower-numbered tier wins whenever one request
        violates several rules, so the error the caller receives is always the
        earliest applicable one."
        PRD §3.1: "Two business rules guard nomination creation, in this
        order. First, the logical now must fall within the city program's
        inclusive nomination window; a submission before the window opens or
        after it closes is rejected with `ERR_NOMINATION_WINDOW_CLOSED`.
        Second, the partner must have quota left: if `nominations_used`
        already equals `nomination_quota`, the nomination is rejected with
        `ERR_NOMINATION_QUOTA_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/nomination_window_error_beats_quota_error
        """
        program, partner = self._setup_window_closed_and_quota_full()
        resp = api.create_nominee(
            create_nominee_payload(program["id"], "Nom Two"),
            make_nominator_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOMINATION_WINDOW_CLOSED)
        assert resp.status_code == 422, "temporal tier 9 beats fiscal tier 11"

    def test_dual_violation_creates_no_nomination(self, api):
        """PRD §2.7: "the lower-numbered tier wins whenever one request
        violates several rules, so the error the caller receives is always the
        earliest applicable one."

        Design: Difficulty/priority_pair_validation_conflict/nomination_window_error_beats_quota_error
        """
        program, partner = self._setup_window_closed_and_quota_full()
        resp = api.create_nominee(
            create_nominee_payload(program["id"], "Nom Two"),
            make_nominator_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOMINATION_WINDOW_CLOSED)
        partners, _ = validate_paginated(api.list_partners(program["id"], _ADMIN))
        assert partners[0]["nominations_used"] == 1, "no nomination was created"
        nominees, meta = validate_paginated(
            api.list_nominees(_ADMIN, params={"city_program_id": program["id"]})
        )
        assert meta["total_count"] == 1
