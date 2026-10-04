"""Consumer alerts: case-linked lift gating and same-kind placement conflicts."""
from test_helpers import (
    ADMIN,
    INVESTIGATOR,
    OPS,
    ApiErrorId,
    create_consumer_alert_payload,
    create_page,
    create_review,
    create_solicitation_case_payload,
    create_user,
    make_reporter_headers,
    setup_confirmed_case,
    set_clock,
    validate_error,
    validate_success,
)


class TestLiftDependsOnCaseState:
    def test_lift_blocked_while_linked_case_not_dismissed(self, api):
        """PRD §3.9: "For a case-linked alert (one whose `case_id` is set), the
        referenced case must be in `DISMISSED` before the lift is permitted —
        otherwise the lift is rejected with `ERR_ALERT_CASE_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/alert_lift_depends_on_case_state
        """
        set_clock("2026-09-01T00:00:00Z")
        page, author, reporter, review, case = setup_confirmed_case()
        alert = validate_success(
            api.create_consumer_alert(
                page["id"],
                {
                    "kind": "SUSPICIOUS_ACTIVITY",
                    "evidence_text": "Unusual five-star spike this week.",
                    "case_id": case["id"],
                },
                ADMIN,
            ),
            expected_status=201,
        )
        r = api.lift_consumer_alert(alert["id"], ADMIN)
        validate_error(r, ApiErrorId.ERR_ALERT_CASE_ACTIVE.value)

    def test_alert_remains_active_after_blocked_lift(self, api):
        """PRD §3.9: "A `SupportAdmin` lifts an `ACTIVE` alert, moving it to
        terminal `LIFTED` and recording their id in `lifted_by_admin_id`. For a
        case-linked alert (one whose `case_id` is set), the referenced case
        must be in `DISMISSED` before the lift is permitted".

        Design: Difficulty/cross_entity_state_dependency/alert_lift_depends_on_case_state
        """
        set_clock("2026-09-01T00:00:00Z")
        page, author, reporter, review, case = setup_confirmed_case()
        alert = validate_success(
            api.create_consumer_alert(
                page["id"],
                {
                    "kind": "SUSPICIOUS_ACTIVITY",
                    "evidence_text": "Unusual five-star spike this week.",
                    "case_id": case["id"],
                },
                ADMIN,
            ),
            expected_status=201,
        )
        api.lift_consumer_alert(alert["id"], ADMIN)
        alert_after = validate_success(api.get_consumer_alert(alert["id"], ADMIN))
        assert alert_after["status"] == "ACTIVE"


class TestAlertPlacementConflicts:
    def test_second_active_alert_of_same_kind_conflicts(self, api):
        """PRD §3.9: "Placement is rejected with `ERR_ALERT_CONFLICT`
        (HTTP 409) when the kind is `SOLICITATION_EVIDENCE` but the referenced
        case is missing or not `CONFIRMED`, or when an `ACTIVE` alert of the
        same kind already exists on the page."

        Design: Corner/errors/err_alert_conflict_duplicate_kind
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        validate_success(
            api.create_consumer_alert(
                page["id"],
                create_consumer_alert_payload(kind="MEDIA_ATTENTION"),
                ADMIN,
            ),
            expected_status=201,
        )
        r = api.create_consumer_alert(
            page["id"],
            create_consumer_alert_payload(kind="MEDIA_ATTENTION"),
            ADMIN,
        )
        validate_error(r, ApiErrorId.ERR_ALERT_CONFLICT.value)

    def test_second_auto_solicitation_alert_not_duplicated(self, api):
        """PRD §3.8: "In the third hop, unless an `ACTIVE` consumer alert of
        kind `SOLICITATION_EVIDENCE` already exists on the case's page, the
        system auto-places one".

        Design: Corner/errors/err_alert_conflict_duplicate_kind
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        author = create_user()
        reporter = create_user()
        r1 = create_review(page["id"], author["id"], rating=2)
        r2 = create_review(page["id"], create_user()["id"], rating=3)
        for target in (r1, r2):
            case = validate_success(
                api.create_solicitation_case(
                    page["id"],
                    create_solicitation_case_payload(target_review_ids=[target["id"]]),
                    make_reporter_headers(reporter["id"]),
                ),
                expected_status=201,
            )
            validate_success(api.investigate_case(case["id"], INVESTIGATOR))
            validate_success(api.confirm_case(case["id"], INVESTIGATOR))
        alerts = validate_success(api.list_page_consumer_alerts(page["id"], OPS))
        matching = [
            a for a in alerts
            if a["kind"] == "SOLICITATION_EVIDENCE" and a["status"] == "ACTIVE"
        ]
        assert len(matching) == 1
