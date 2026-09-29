"""Two rejections are due at once; the strict ranking of §2.8 picks the winner."""

from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
)
from test_helpers.constants import ISSUANCE_CLOCK
from test_helpers.fixtures import (
    ADMIN,
    BOARD,
    OFFICER,
    advance_appeal,
    advance_cycle,
    file_appeal,
    issue_certificate,
    refresh_appeal,
    refresh_application,
    refresh_certificate,
    seed_application_submitted,
    seed_decided_cycle,
    seed_draft_application,
    set_clock,
)
from test_helpers.test_users import make_applicant_headers

PAST_APPLICATION_DEADLINE = "2026-08-21T00:00:00Z"
APPEAL_FILING_CLOCK = "2026-10-01T00:00:00Z"


def _certificate_with_exhausted_cap_and_a_hold():
    """An extension lineage at the 540-day cap under a live litigation hold."""
    world = seed_decided_cycle()
    set_clock(APPEAL_FILING_CLOCK)
    world["appeal"] = file_appeal(
        world["application"],
        world["applicant"],
        "Approval conditions exceed statutory authority",
    )
    set_clock(ISSUANCE_CLOCK)
    world["certificate"] = issue_certificate(world["application"])

    for days, justification in (
        (365, "Site preparation delays"),
        (175, "Equipment lead times"),
    ):
        world["certificate"] = get_success_data(
            api_client.extend_certificate(
                world["certificate"]["id"],
                {"requested_days": days, "justification": justification},
                OFFICER,
            )
        )

    advance_appeal(world["appeal"], "BRIEFING")
    world["appeal"] = get_success_data(
        api_client.set_litigation_hold(world["appeal"]["id"], "APPLY", BOARD)
    )
    return world


class TestApplicationStateOutranksTheFilingWindow:
    def test_resubmitting_after_the_deadline_reports_the_state_defect(self):
        """Position 8 beats position 18, so the state error is the one returned.

        PRD §2.8: "When a request violates more than one rule, exactly one error
        is returned: the one belonging to the lowest-numbered rule in the
        following order."
        PRD §2.8: "**Target-state admissibility on the application track.**
        Submission requires the application in `DRAFT` with its cycle in
        `OPEN_FOR_APPLICATIONS` (`ERR_APPLICATION_NOT_SUBMITTABLE`);
        deficiency-notice issuance and deem-complete require the application in
        `SUBMITTED` or `COMPLETENESS_REVIEW` with the cycle in
        `COMPLETENESS_WINDOW` (`ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW`); a
        cure requires the addressed review in `DEFICIENCY_NOTICE_ISSUED`
        (`ERR_COMPLETENESS_REVIEW_NOT_OPEN`). All at 409."
        PRD §2.8: "**Filing windows.** Letters of intent by `loi_deadline_at`
        (`ERR_LOI_WINDOW_CLOSED`); application submission and the completeness
        actions by `application_deadline_at` and `completeness_deadline_at`
        respectively (`ERR_FILING_WINDOW_CLOSED`); a cure by the review's
        `cure_deadline_at` (`ERR_CURE_DEADLINE_PASSED`). All bounds inclusive,
        all at 409."

        Design: Difficulty/priority_pair_validation_conflict/submit_state_conflict_outranks_closed_filing_window
        """
        world = seed_application_submitted()
        application = world["application"]
        set_clock(PAST_APPLICATION_DEADLINE)

        response = api_client.submit_application(
            application["id"], make_applicant_headers(world["applicant"]["id"])
        )

        body = validate_error(
            response, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTABLE, 409
        )
        assert body["error_id"] != ApiErrorId.ERR_FILING_WINDOW_CLOSED

    def test_the_lower_ranked_window_rule_is_genuinely_violated_on_its_own(self):
        """With the state rule satisfied, the same clock yields the window error.

        PRD §2.8: "**Filing windows.** Letters of intent by `loi_deadline_at`
        (`ERR_LOI_WINDOW_CLOSED`); application submission and the completeness
        actions by `application_deadline_at` and `completeness_deadline_at`
        respectively (`ERR_FILING_WINDOW_CLOSED`); a cure by the review's
        `cure_deadline_at` (`ERR_CURE_DEADLINE_PASSED`). All bounds inclusive,
        all at 409."
        PRD §3.4: "Only the owning applicant may submit, or the request fails
        with `ERR_NOT_FILING_OWNER`; the applicant's `standing` must be `GOOD`,
        or `ERR_APPLICANT_STANDING_RESTRICTED` applies; and the logical clock
        must be at or before the cycle's `application_deadline_at`, or the
        request is refused with `ERR_FILING_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_state_conflict_outranks_closed_filing_window
        """
        world = seed_draft_application()
        world["cycle"] = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
        application = world["application"]
        version_before = application["version"]
        set_clock(PAST_APPLICATION_DEADLINE)

        response = api_client.submit_application(
            application["id"], make_applicant_headers(world["applicant"]["id"])
        )

        validate_error(response, ApiErrorId.ERR_FILING_WINDOW_CLOSED, 409)
        application = refresh_application(application["id"])
        assert application["status"] == "DRAFT"
        assert application["version"] == version_before


class TestLitigationHoldOutranksExtensionCapacity:
    def test_a_hold_freezes_the_extension_before_the_cap_is_consulted(self):
        """Position 13 beats position 28 even though the cap is fully consumed.

        PRD §2.8: "**Litigation hold.** No appeal on the target application has
        `litigation_hold_active` set to true. The hold freezes the operation
        regardless of any other defect in the request that ranks below this
        position, and the rejection is `ERR_LITIGATION_HOLD_ACTIVE` (409). This
        rule guards four operations: certificate issuance, certificate
        extension, certificate modification and application withdrawal."
        PRD §2.8: "**Extension capacity.** The certificate lineage must have a
        remaining cumulative extension allowance greater than zero — otherwise
        `ERR_EXTENSION_CAP_EXHAUSTED` (422). This rule guards certificate
        extension."

        Design: Difficulty/priority_pair_validation_conflict/litigation_hold_outranks_extension_cap_exhausted
        """
        world = _certificate_with_exhausted_cap_and_a_hold()

        response = api_client.extend_certificate(
            world["certificate"]["id"],
            {"requested_days": 30, "justification": "Third extension request"},
            OFFICER,
        )

        body = validate_error(response, ApiErrorId.ERR_LITIGATION_HOLD_ACTIVE, 409)
        assert body["error_id"] != ApiErrorId.ERR_EXTENSION_CAP_EXHAUSTED

    def test_the_lineage_sits_exactly_on_the_cumulative_cap(self):
        """365 then 175 days consume the whole 540-day lineage allowance.

        PRD §3.8: "The lineage's remaining allowance is 540 days minus the
        certificate's `extension_days_granted_total`, which is carried forward
        across every reissue so the cap binds the whole lineage rather than each
        row; when that remaining allowance is 0 or less the request is refused
        with `ERR_EXTENSION_CAP_EXHAUSTED`."
        PRD §3.8: "Otherwise the granted days are the smallest of three
        quantities: the `requested_days` asked for, the per-grant ceiling of 365
        days, and the remaining lineage allowance."
        PRD §3.8: "The granted days are added to
        `extension_days_granted_total`, and `implementation_milestone_date` is
        pushed forward by exactly that many calendar days in UTC."

        Design: Difficulty/priority_pair_validation_conflict/litigation_hold_outranks_extension_cap_exhausted
        """
        world = _certificate_with_exhausted_cap_and_a_hold()

        certificate = refresh_certificate(world["certificate"]["id"])
        assert certificate["extension_days_granted_total"] == 540
        assert certificate["implementation_milestone_date"] == "2028-12-21"

    def test_the_hold_parks_the_appeal_and_remembers_where_it_came_from(self):
        """APPLY stashes BRIEFING in status_before_hold and moves to STAYED.

        PRD §3.9: "Applying a hold — the operation takes an `action` of `APPLY`
        — is permitted from `BRIEFING` or from `HEARD`; it stores the current
        status in `status_before_hold`, sets `status` to `STAYED`, sets
        `litigation_hold_active` to true and increases `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/litigation_hold_outranks_extension_cap_exhausted
        """
        world = _certificate_with_exhausted_cap_and_a_hold()

        appeal = refresh_appeal(world["appeal"]["id"], ADMIN)
        assert appeal["status"] == "STAYED"
        assert appeal["litigation_hold_active"] is True
        assert appeal["status_before_hold"] == "BRIEFING"
