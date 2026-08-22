"""Design review: submittal decisions, the resubmission loop and its escalation."""

from test_helpers import (
    ApiErrorId,
    assert_issue,
    assert_submittal,
    create_project,
    create_submittal,
    get_project,
    get_submittal,
    list_issues,
    review_submittal,
    setup_submittal_at_review_round_three,
    validate_error,
)
from test_helpers import CXA, DESIGN


class TestSubmittalReviewDecisions:
    def test_reviewing_an_already_approved_submittal_is_refused(self, api):
        """PRD §3.2: "A decision of `APPROVED` moves the submittal `RECEIVED` → `APPROVED`.
        Nothing else happens; the document is accepted as lodged and the state is terminal."
        PRD §2.5: "The target resource is in a status from which the requested transition is
        declared — otherwise `ERR_INVALID_STATE` (409). This applies to every state-changing
        action endpoint in the system."

        Design: Corner/state_machines/reviewing_an_approved_submittal_returns_invalid_state
        """
        project = create_project(
            name="Locked Cx",
            building_name="Locked Block",
            contract_value_cents=50_000_000,
        )
        submittal = create_submittal(
            project["id"], title="Chiller product data", submittal_kind="PRODUCT_DATA"
        )
        approved = review_submittal(submittal["id"], "APPROVED", "No exceptions taken")
        assert approved["status"] == "APPROVED"

        response = api.review_submittal(
            submittal["id"],
            {"decision": "REVISE_AND_RESUBMIT", "comment": "Changed my mind"},
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        after = get_submittal(submittal["id"])
        assert_submittal(after)
        assert after["status"] == "APPROVED"
        assert after["last_decision"] == "APPROVED"
        assert after["review_round"] == 1

    def test_design_team_may_not_review_the_submittal_it_lodged(self, api):
        """PRD §2.1: "A request whose role is recognised but is not listed for the endpoint
        in the Section 4 table is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §3.2: "Design review is the `CxAuthority`'s call. The reviewer supplies a
        `decision` and a `comment`, and the comment is retained on the row as
        `review_comment` alongside `last_decision` in all three branches, which are given
        equal standing here because the differences between them are the whole point:"

        Design: Corner/rbac/design_team_cannot_review_its_own_submittal
        """
        project = create_project(
            name="SelfReview Cx",
            building_name="SelfReview Block",
            contract_value_cents=50_000_000,
        )
        submittal = create_submittal(
            project["id"], title="Fan shop drawing", submittal_kind="SHOP_DRAWING"
        )

        response = api.review_submittal(
            submittal["id"],
            {"decision": "APPROVED", "comment": "Looks fine to me"},
            DESIGN,
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        after = get_submittal(submittal["id"])
        assert after["status"] == "RECEIVED"
        assert after["last_decision"] is None


class TestResubmissionLoopAndEscalation:
    def test_third_revise_decision_mints_the_escalation_issue(self, api):
        """PRD §3.2: "The loop closes when the `DesignTeam` resubmits:
        `REVISE_AND_RESUBMIT` → `RECEIVED` with `review_round` incremented by one,
        optionally supplying a revised `title`."
        PRD §3.2: "When — and only when — the submittal is already at `review_round` 3 at
        the moment that decision is recorded, the server additionally opens an escalation
        issue with `origin` `SUBMITTAL`, `severity` `S2`, the submittal's `equipment_id`,
        `source_ref_id` pointing at the submittal and `opened_by_user_id` of `SYSTEM`, and
        writes that issue's identifier into the submittal's `escalation_issue_id`."

        Design: Difficulty/non_linear_state_machine/submittal_review_resubmit_cycle_escalates_on_third_round
        """
        setup = setup_submittal_at_review_round_three()
        submittal = setup["submittal"]
        assert submittal["review_round"] == 3, (
            "two resubmits leave the submittal at review_round 3"
        )
        assert submittal["status"] == "RECEIVED"

        escalating = review_submittal(
            submittal["id"], "REVISE_AND_RESUBMIT", "Round 3 - escalating"
        )
        assert escalating["status"] == "REVISE_AND_RESUBMIT"
        assert escalating["review_round"] == 3
        assert escalating["escalation_issue_id"] is not None

        rows, meta = list_issues(
            project_id=setup["project"]["id"], origin="SUBMITTAL"
        )
        assert meta["total_count"] == 1, f"expected one escalation issue, got {rows}"
        issue = rows[0]
        assert_issue(issue)
        assert issue["severity"] == "S2"
        assert issue["status"] == "OPEN"
        assert issue["source_ref_id"] == submittal["id"]
        assert issue["opened_by_user_id"] == "SYSTEM"
        assert issue["id"] == escalating["escalation_issue_id"]

    def test_escalation_loads_the_index_and_locks_further_resubmission(self, api):
        """PRD §3.2: "Resubmission is refused with `ERR_REVIEW_ROUNDS_EXCEEDED` once
        `review_round` has reached 3, which makes a fourth review round structurally
        impossible — three rounds is the ceiling, and the third `REVISE_AND_RESUBMIT`
        decision is the one that escalates."
        PRD §2.6: "The severity weights are 25.0 for `S1`, 12.0 for `S2`, 8.0 for `S3` and
        2.0 for `S4`."
        PRD §2.7: "The **base hold rate** comes from the issue's own severity: 0.05 for
        `S1`, 0.02 for `S2`, 0.005 for `S3` and 0.0 for `S4`."

        Design: Difficulty/non_linear_state_machine/submittal_review_resubmit_cycle_escalates_on_third_round
        """
        setup = setup_submittal_at_review_round_three()
        submittal = setup["submittal"]
        review_submittal(submittal["id"], "REVISE_AND_RESUBMIT", "Round 3 - escalating")

        project = get_project(setup["project"]["id"])
        assert project["issue_severity_index"] == 24.00, (
            "one fresh blocking S2 contributes 12.0 * 1.00 * 2.0"
        )
        assert project["readiness_posture"] == "RESTRICTED"
        assert project["retainage_withheld_cents"] == 2_000_000, (
            "the project-wide S2 hold is 100000000 * 0.02 * 1.0"
        )

        refused = api.resubmit_submittal(submittal["id"], DESIGN)
        validate_error(refused, ApiErrorId.ERR_REVIEW_ROUNDS_EXCEEDED.value, 422)

        after = get_submittal(submittal["id"])
        assert after["status"] == "REVISE_AND_RESUBMIT"
        assert after["review_round"] == 3
