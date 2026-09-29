"""Identity gates, activity completeness gates and the filing-calendar gates."""
from test_helpers import (
    COMPLIANCE,
    COMPLIANCE_2,
    DEFAULT_CLOCK_STAMP,
    DIRECTOR,
    NO_HEADERS,
    api_client,
    assert_instant_equals,
    create_activity_payload,
    create_report_payload,
    enroll_member,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    make_member_delegate_headers,
    open_report,
    read_member,
    read_report,
    read_registration,
    registration_version,
    setup_active_registration,
    setup_registration_with_adopted_position,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_blank_and_unknown_identity_headers_are_all_unauthenticated():
    """Priorities 1 and 2 answer before the role check and before any lookup.

    PRD 2.11: "Both authentication headers are present and non-empty after trimming —
    otherwise `ERR_UNAUTHENTICATED` (401)."
    PRD 2.11: "`X-User-Role` names one of the five declared roles — otherwise
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/Validations/requests_without_usable_identity_headers_unauthenticated
    """
    member = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )

    validate_error(
        api_client.get_member(member["id"], NO_HEADERS), "ERR_UNAUTHENTICATED", 401
    )
    validate_error(
        api_client.get_member(member["id"], headers_with_empty_user_id()),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api_client.get_member(member["id"], headers_with_unknown_role()),
        "ERR_UNAUTHENTICATED",
        401,
    )

    assert read_member(member["id"])["version"] == 1


def test_a_delegate_may_read_only_its_own_deductibility_notice():
    """The role check passes and the member-scope gate is what refuses the read.

    PRD 2.11: "A `MemberDelegate` is acting within its own member scope — otherwise
    `ERR_MEMBER_SCOPE_VIOLATION` (403)."
    PRD 3.1: "A member has a narrow window onto its own data, described in §2.1: its own
    record, its own deductibility notice, its own committee seats, its own ballots across
    all positions, and its own prior approvals."

    Design: Corner/Validations/member_delegate_reading_another_members_notice_forbidden
    """
    alpha = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )
    beta = enroll_member(
        legal_name="Beta Foundry Co",
        membership_tier="FULL",
        home_jurisdiction_code="STATE_CA",
        restricted_class_size=25,
    )

    validate_error(
        api_client.get_deductibility_notice(
            beta["id"], make_member_delegate_headers(alpha["id"])
        ),
        "ERR_MEMBER_SCOPE_VIOLATION",
        403,
    )

    notice = validate_success(
        api_client.get_deductibility_notice(
            beta["id"], make_member_delegate_headers(beta["id"])
        ),
        200,
    )
    assert notice["member_id"] == beta["id"]
    assert notice["notice_method"] == "FLAT_FLOOR"


def test_the_three_activity_completeness_gates_each_refuse_and_move_nothing():
    """A missing partner, an out-of-window date and an empty row all fail at 422.

    PRD 3.5: "A `coalition_partner_name` is mandatory, non-blank, whenever
    `activity_kind` is `COALITION_CONTRIBUTION` or `THIRD_PARTY_ADVOCACY`, because the
    third-party disclosure would otherwise be incomplete; its absence is refused with
    `ERR_COALITION_PARTNER_REQUIRED`."
    PRD 3.5: "Finally, an activity that records nothing at all, with `hours` of 0 and
    `expenditure_cents` of 0, is refused with `ERR_EMPTY_ACTIVITY`, since it would move no
    accumulator."

    Design: Corner/Validations/activity_logging_completeness_and_window_gates_rejected
    """
    state = setup_registration_with_adopted_position(
        position_overrides={"title": "Oppose Section 232 Expansion"}
    )
    registration_id = state["registration"]["id"]
    position_id = state["position"]["id"]

    validate_error(
        api_client.create_lobbying_activity(
            create_activity_payload(
                registration_id,
                position_id,
                activity_kind="COALITION_CONTRIBUTION",
                activity_date="2026-02-15",
                hours=1.000,
                expenditure_cents=100_000,
            ),
            DIRECTOR,
        ),
        "ERR_COALITION_PARTNER_REQUIRED",
        422,
    )
    validate_error(
        api_client.create_lobbying_activity(
            create_activity_payload(
                registration_id,
                position_id,
                activity_date="2027-01-05",
                hours=1.000,
                expenditure_cents=100_000,
            ),
            DIRECTOR,
        ),
        "ERR_ACTIVITY_OUTSIDE_COVERAGE",
        422,
    )
    validate_error(
        api_client.create_lobbying_activity(
            create_activity_payload(
                registration_id,
                position_id,
                activity_date="2026-02-15",
                hours=0.000,
                expenditure_cents=0,
            ),
            DIRECTOR,
        ),
        "ERR_EMPTY_ACTIVITY",
        422,
    )

    registration = read_registration(registration_id)
    assert registration["ytd_reportable_cents"] == 0
    assert float(registration["ytd_reportable_hours"]) == 0.000

    rows, meta = validate_paginated(
        api_client.list_registration_activities(registration_id, COMPLIANCE)
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_a_coalition_activity_with_its_partner_named_is_logged_and_flagged():
    """With the partner supplied the disclosure latch and the staff cost both land.

    PRD 3.5: "`third_party_disclosure_required` reads true in exactly two situations:
    whenever `activity_kind` is `THIRD_PARTY_ADVOCACY`, and when `activity_kind` is
    `COALITION_CONTRIBUTION` and this activity's `expenditure_cents` is at least 500,000;
    in every other case it reads false."
    PRD 3.5: "`staff_cost_cents` is the in-house labour value of this one activity: its
    `hours` multiplied by the association's standard staff rate of 8500 cents per hour —
    85 dollars — rounded half up to a whole number of cents."

    Design: Corner/Validations/coalition_activity_with_a_partner_name_is_logged_and_flagged
    """
    state = setup_registration_with_adopted_position(
        position_overrides={"title": "Oppose Section 232 Expansion"}
    )
    registration_id = state["registration"]["id"]

    activity = validate_success(
        api_client.create_lobbying_activity(
            create_activity_payload(
                registration_id,
                state["position"]["id"],
                activity_kind="COALITION_CONTRIBUTION",
                activity_date="2026-02-15",
                hours=1.500,
                expenditure_cents=500_000,
                coalition_partner_name="Manufacturers United Coalition",
            ),
            DIRECTOR,
        ),
        201,
    )
    assert activity["status"] == "LOGGED"
    assert_instant_equals(activity["logged_at"], DEFAULT_CLOCK_STAMP, "logged_at")
    assert activity["coalition_partner_name"] == "Manufacturers United Coalition"
    assert activity["staff_cost_cents"] == 12_750
    assert activity["third_party_disclosure_required"] is True

    registration = read_registration(registration_id)
    assert registration["ytd_reportable_cents"] == 500_000
    assert float(registration["ytd_reportable_hours"]) == 1.500
    assert registration["status"] == "ACTIVE"


def test_the_cadence_closure_and_emptiness_gates_each_refuse_their_own_report():
    """A semiannual filer rejects a quarterly label, and certification waits.

    PRD 3.6: "A label of the wrong shape, or one naming an out-of-range period index, is
    refused with `ERR_PERIOD_CADENCE_MISMATCH`."
    PRD 3.6: "And the period must have closed: the logical clock's UTC date must have
    reached `period_end_date` — being exactly on that date is sufficient — while an earlier
    date is refused with `ERR_PERIOD_NOT_CLOSED`."
    PRD 3.6: "The report must contain at least one activity: an `included_activity_count`
    of 0 is refused with `ERR_EMPTY_REPORT`."

    Design: Corner/Validations/report_cadence_period_closure_and_emptiness_gates_rejected
    """
    quarterly = setup_active_registration(jurisdiction_code="FEDERAL")
    semiannual = setup_active_registration(jurisdiction_code="STATE_NY")

    first_quarter = open_report(quarterly["id"], period_code="2026Q1")
    assert first_quarter["period_end_date"] == "2026-03-31"
    assert first_quarter["due_date"] == "2026-04-20"

    third_quarter = open_report(quarterly["id"], period_code="2026Q3")
    assert third_quarter["period_end_date"] == "2026-09-30"
    assert third_quarter["due_date"] == "2026-10-20"

    validate_error(
        api_client.create_expenditure_report(
            create_report_payload(
                semiannual["id"],
                registration_version(semiannual["id"]),
                period_code="2026Q3",
            ),
            COMPLIANCE,
        ),
        "ERR_PERIOD_CADENCE_MISMATCH",
        422,
    )

    validate_error(
        api_client.certify_expenditure_report(third_quarter["id"], COMPLIANCE_2),
        "ERR_PERIOD_NOT_CLOSED",
        409,
    )
    validate_error(
        api_client.certify_expenditure_report(first_quarter["id"], COMPLIANCE_2),
        "ERR_EMPTY_REPORT",
        422,
    )

    for report_id in (first_quarter["id"], third_quarter["id"]):
        report = read_report(quarterly["id"], report_id)
        assert report["status"] == "OPEN"
        assert report["certified_by_user_id"] is None
        assert report["certified_at"] is None
        assert report["late"] is False

    rows, meta = validate_paginated(
        api_client.list_registration_expenditure_reports(semiannual["id"], COMPLIANCE)
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_creator_of_a_report_cannot_certify_it_even_when_it_is_empty():
    """Segregation of duties sits above the emptiness guard in the precedence order.

    PRD 2.10: "An expenditure report may not be certified by the `ComplianceOfficer` who
    created it: certification compares the caller's `X-User-ID` against the report's
    `created_by_user_id` and, when they are equal, rejects with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
    PRD 2.11: "When a single request violates more than one rule, the response must report
    the **first** violation in the following order."

    Design: Corner/Validations/certifying_a_report_as_its_own_creator_rejected
    """
    registration = setup_active_registration()
    report = open_report(registration["id"], period_code="2026Q1", headers=COMPLIANCE)
    assert report["created_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert report["included_activity_count"] == 0

    validate_error(
        api_client.certify_expenditure_report(report["id"], COMPLIANCE),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    stored = read_report(registration["id"], report["id"])
    assert stored["status"] == "OPEN"
    assert stored["certified_by_user_id"] is None
