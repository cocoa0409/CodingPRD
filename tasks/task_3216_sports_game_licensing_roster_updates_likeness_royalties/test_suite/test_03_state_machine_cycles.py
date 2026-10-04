"""Difficulty queue A, rule 3: non_linear_state_machine — both instances."""
from test_helpers import (
    RIGHTS,
    create_approved_edition,
    create_eligible_athlete,
    create_live_season,
    create_active_agreement,
    create_released_drop,
    setup_cascade_scenario,
    get_success_data,
    validate_success,
)
from test_helpers.api_client import api_client


class TestLikenessGrantSuspendReinstateCycle:
    def test_suspend_holds_featured_drop(self, api):
        """PRD §3.2: "Suspension moves the athlete to INELIGIBLE when no other
        GRANTED grant remains for that athlete, moves every RELEASED drop
        featuring the athlete to HELD (blocking further purchases)."

        Design: Difficulty/non_linear_state_machine/likeness_grant_granted_suspended_granted_cycle
        """
        ctx = setup_cascade_scenario()
        grant = ctx["grant"]
        drop = ctx["drop"]

        suspended = get_success_data(
            api_client.suspend_likeness_grant(
                grant["id"], {"suspended_reason": "GRIEVANCE_FILED"}, RIGHTS
            )
        )
        assert suspended["grant_status"] == "SUSPENDED"

        drop_after = get_success_data(api_client.get_content_drop(drop["id"], LIVEOPS_HEADERS))
        assert drop_after["drop_status"] == "HELD", (
            f"drop featuring the suspended athlete must move to HELD; "
            f"got {drop_after['drop_status']}"
        )

    def test_reinstate_completes_the_cycle(self, api):
        """PRD §3.2: "Reinstatement is the mirror image: a SUSPENDED grant
        returns to GRANTED provided its agreement is ACTIVE, the athlete
        returns to ELIGIBLE, drops HELD because of this grant return to
        RELEASED."

        Design: Difficulty/non_linear_state_machine/likeness_grant_granted_suspended_granted_cycle
        """
        ctx = setup_cascade_scenario()
        grant = ctx["grant"]
        drop = ctx["drop"]

        get_success_data(
            api_client.suspend_likeness_grant(
                grant["id"], {"suspended_reason": "GRIEVANCE_FILED"}, RIGHTS
            )
        )
        reinstated = get_success_data(
            api_client.reinstate_likeness_grant(grant["id"], RIGHTS)
        )
        assert reinstated["grant_status"] == "GRANTED"

        drop_after = get_success_data(api_client.get_content_drop(drop["id"], LIVEOPS_HEADERS))
        assert drop_after["drop_status"] == "RELEASED"

        athlete_after = get_success_data(api_client.get_athlete(ctx["athlete"]["id"], RIGHTS))
        assert athlete_after["athlete_status"] == "ELIGIBLE"


# LIVEOPS headers used for drop reads (GET content-drops authorizes LiveOpsManager).
from test_helpers.test_users import TEST_USERS  # noqa: E402
LIVEOPS_HEADERS = TEST_USERS["liveops_manager_headers"]


class TestRegionalEditionReviewLoop:
    def test_return_to_draft_branch(self, api):
        """PRD §3.6: "The edition starts DRAFT, moves to IN_REVIEW when
        submitted for compliance review, and from there a ComplianceReviewer
        either approves it or returns it to DRAFT for rework."

        Design: Difficulty/non_linear_state_machine/regional_edition_review_loop_branching
        """
        ctx = _live_season_ctx(api)
        from test_helpers.fixtures import create_edition_payload
        edition = get_success_data(
            api_client.create_edition(
                create_edition_payload(ctx["season"]["id"], region_code="DE",
                                       censorship_flags=["NO_BLOOD_OVERLAYS"],
                                       embargo_until_on="2026-09-01"),
                LIVEOPS_HEADERS,
            )
        )
        from test_helpers.test_users import make_liveops_manager_headers, make_compliance_reviewer_headers
        get_success_data(
            api_client.submit_edition_review(
                edition["id"], make_liveops_manager_headers("ops-7")
            )
        )
        returned = get_success_data(
            api_client.return_edition_to_draft(
                edition["id"], make_compliance_reviewer_headers("cr-1")
            )
        )
        assert returned["edition_status"] == "DRAFT", (
            f"IN_REVIEW -> DRAFT revert leg must return the edition to DRAFT; "
            f"got {returned['edition_status']}"
        )

    def test_full_review_loop_then_release_on_embargo_day(self, api):
        """PRD §3.6: "An APPROVED edition may be released once the clock date is
        on or after embargo_until_on — the threshold is inclusive, so releasing
        exactly on the embargo date is permitted — and only while the parent
        season is LIVE."

        Design: Difficulty/non_linear_state_machine/regional_edition_review_loop_branching
        """
        ctx = _live_season_ctx(api)
        edition = create_approved_edition(
            ctx["season"]["id"], region_code="DE",
            censorship_flags=["NO_BLOOD_OVERLAYS"], embargo_until_on="2026-09-01",
        )
        # clock startup is 2026-09-01, exactly the embargo date
        released = get_success_data(api_client.release_edition(edition["id"], LIVEOPS_HEADERS))
        assert released["edition_status"] == "RELEASED"


def _live_season_ctx(api):
    agreement = create_active_agreement(
        licensor_name="Hoops League", sport_category="BASKET_PRO",
        exclusivity_scope="NONE", audit_window_days=60,
    )
    athlete, grant = create_eligible_athlete(agreement["id"])
    season = create_live_season(
        agreement["id"], athlete["id"], initial_rating=80,
        title_code="HOOPS26", sport_category="BASKET_PRO",
    )
    return {"agreement": agreement, "athlete": athlete, "grant": grant,
            "season": season}
