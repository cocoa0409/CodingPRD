"""The deficiency-notice / cure loop: a row re-entering a state it already left."""

from test_helpers import (
    api_client,
    assert_completeness_review,
    assert_instant_equals,
    validate_paginated,
)
from test_helpers.fixtures import (
    ADMIN,
    INTAKE,
    file_cure,
    issue_deficiency_notice,
    refresh_application,
    seed_completeness_window,
    set_clock,
)
from test_helpers.test_users import INTAKE_USER_ID

INSIDE_COMPLETENESS_WINDOW = "2026-08-21T00:00:00Z"
FIRST_CURE_DEADLINE = "2026-08-25T00:00:00Z"
SECOND_CURE_DEADLINE = "2026-09-01T00:00:00Z"


def _world_in_completeness_window():
    world = seed_completeness_window()
    set_clock(INSIDE_COMPLETENESS_WINDOW)
    world["application"] = refresh_application(world["application"]["id"])
    return world


class TestDeficiencyCureLoop:
    def test_two_rounds_of_notice_and_cure_then_deemed_complete(self):
        """The application leaves and re-enters COMPLETENESS_REVIEW twice.

        PRD §3.5: "A new completeness review row is created for the named
        `application_id` with `status` `DEFICIENCY_NOTICE_ISSUED`, its
        `round_number` set to the application's `completeness_round_count` plus
        1, and its `issued_by_user_id` stamped from the acting analyst's
        `X-User-ID` — that stamp is what later disqualifies the same user from
        scoring this application."
        PRD §3.5: "Notice and cure therefore form a loop that can run any number
        of times: `COMPLETENESS_REVIEW` → `INCOMPLETE` on each new notice,
        `INCOMPLETE` → `COMPLETENESS_REVIEW` on each cure."
        PRD §3.5: "Success sets the application's `status` to `DEEMED_COMPLETE`
        and increases its `version` by 1."

        Design: Difficulty/non_linear_state_machine/application_deficiency_cure_two_round_revision_loop
        """
        world = _world_in_completeness_window()
        application = world["application"]

        review_1 = issue_deficiency_notice(
            application, ["Missing audited financial statements"], FIRST_CURE_DEADLINE
        )
        file_cure(review_1, world["applicant"], "Audited statements attached")
        review_2 = issue_deficiency_notice(
            application,
            ["Financial projections still omit year three"],
            SECOND_CURE_DEADLINE,
        )
        file_cure(review_2, world["applicant"], "Year three projections attached")
        final = api_client.deem_application_complete(application["id"], INTAKE)

        assert final.status_code == 200, final.text
        assert review_1["round_number"] == 1
        assert review_2["round_number"] == 2
        application = refresh_application(application["id"])
        assert application["completeness_round_count"] == 2
        assert application["status"] == "DEEMED_COMPLETE"

    def test_each_cure_records_its_own_terminal_state(self):
        """Both rounds end CURED with cured_at stamped from the logical clock.

        PRD §3.5: "The cure sets the review's `status` to `CURED`, stamps
        `cured_at` from the logical clock, stores the supplied `cure_response`
        on the review and increases the review's `version` by 1; in the same
        operation the parent application moves from `INCOMPLETE` back to
        `COMPLETENESS_REVIEW` and its `version` increases by 1."
        PRD §3.5: "A review's own status enumeration is
        `DEFICIENCY_NOTICE_ISSUED`, `CURED` and `EXPIRED`, of which the last two
        are terminal; `cure_response` and `cured_at` are both null until the
        cure lands."

        Design: Difficulty/non_linear_state_machine/application_deficiency_cure_two_round_revision_loop
        """
        world = _world_in_completeness_window()
        application = world["application"]

        review_1 = issue_deficiency_notice(
            application, ["Missing audited financial statements"], FIRST_CURE_DEADLINE
        )
        assert_completeness_review(review_1)
        assert review_1["status"] == "DEFICIENCY_NOTICE_ISSUED"
        assert review_1["cured_at"] is None
        assert review_1["cure_response"] is None
        assert review_1["issued_by_user_id"] == INTAKE_USER_ID

        cured_1 = file_cure(
            review_1, world["applicant"], "Audited statements attached"
        )
        assert cured_1["status"] == "CURED"
        assert_instant_equals(cured_1["cured_at"], INSIDE_COMPLETENESS_WINDOW)
        assert cured_1["cure_response"] == "Audited statements attached"
        assert refresh_application(application["id"])["status"] == "COMPLETENESS_REVIEW"

        review_2 = issue_deficiency_notice(
            application,
            ["Financial projections still omit year three"],
            SECOND_CURE_DEADLINE,
        )
        cured_2 = file_cure(
            review_2, world["applicant"], "Year three projections attached"
        )
        assert cured_2["round_number"] == 2
        assert cured_2["status"] == "CURED"

    def test_notice_moves_the_application_to_incomplete(self):
        """Each notice pushes the row back out of COMPLETENESS_REVIEW.

        PRD §3.5: "The application's `completeness_round_count` increases by 1.
        And the application's `status` becomes `INCOMPLETE`, with its `version`
        increased by 1."
        PRD §3.5: "Because the notice may be issued from either `SUBMITTED` or
        `COMPLETENESS_REVIEW`, second and later rounds work identically, with
        `round_number` advancing by one each time."

        Design: Difficulty/non_linear_state_machine/application_deficiency_cure_two_round_revision_loop
        """
        world = _world_in_completeness_window()
        application = world["application"]
        version_before = application["version"]

        review_1 = issue_deficiency_notice(
            application, ["Missing audited financial statements"], FIRST_CURE_DEADLINE
        )

        application = refresh_application(application["id"])
        assert application["status"] == "INCOMPLETE"
        assert application["completeness_round_count"] == 1
        assert application["version"] == version_before + 1

        file_cure(review_1, world["applicant"], "Audited statements attached")
        issue_deficiency_notice(
            application,
            ["Financial projections still omit year three"],
            SECOND_CURE_DEADLINE,
        )
        application = refresh_application(application["id"])
        assert application["status"] == "INCOMPLETE"
        assert application["completeness_round_count"] == 2

    def test_rounds_are_listed_in_created_at_order(self):
        """The case file lists round 1 before round 2.

        PRD §3.5: "The rounds of an application can be listed in `created_at`
        order for the case file."

        Design: Difficulty/non_linear_state_machine/application_deficiency_cure_two_round_revision_loop
        """
        world = _world_in_completeness_window()
        application = world["application"]
        review_1 = issue_deficiency_notice(
            application, ["Missing audited financial statements"], FIRST_CURE_DEADLINE
        )
        file_cure(review_1, world["applicant"], "Audited statements attached")
        review_2 = issue_deficiency_notice(
            application,
            ["Financial projections still omit year three"],
            SECOND_CURE_DEADLINE,
        )

        rounds, meta = validate_paginated(
            api_client.list_completeness_reviews(application["id"], ADMIN)
        )

        assert meta["total_count"] == 2
        assert [row["id"] for row in rounds] == [review_1["id"], review_2["id"]]
        assert [row["round_number"] for row in rounds] == [1, 2]
