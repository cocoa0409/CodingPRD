"""Validation priority: which of two simultaneously violated rules answers.

Every test below arranges a single request that breaks two rules from different
priority bands, asserts the higher-ranked refusal, and then proves the lower
ranked rule really was violated by isolating it in a second scenario.
"""

from test_helpers import (
    ApiErrorId,
    EngagementStatus,
    FeePaymentStatus,
    MembershipStatus,
    REGULATOR_HEADERS,
    SubmissionStatus,
    VERIFIER_USER_ID,
    VERIFIER_USER_ID_ALT,
    assert_engagement,
    assert_membership,
    assert_producer,
    assert_report,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Business safety outranks fiscal rules on a report submission
# ---------------------------------------------------------------------------
def _report_awaiting_submission_with_an_unpaid_membership(api, make_stale: bool):
    """A lined DRAFT report whose membership is ACTIVE but never paid."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Priority Glass Co",
            annual_gross_revenue_usd=8000000,
            contact_email="pa@x.com",
        ),
        sku_overrides=dict(name="Jar GA", product_category="HOUSEHOLD_CHEM"),
        with_membership=False,
        with_report=False,
    )
    producer, registration = chain["producer"], chain["registration"]
    membership = fx.apply_for_membership(
        api, producer, registration, chain["pro"], chain["schedule"]
    )
    membership = fx.approve_membership(api, chain["pro"], membership)
    assert_membership(
        membership,
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
    )

    report = fx.make_report(api, producer, registration, chain["period"])
    fx.add_line(api, producer, report, chain["sku"], 110)

    if make_stale:
        fx.make_sku_with_components(
            api,
            producer,
            components=[f.component_payload(material_type="GLASS", unit_weight_grams=50)],
            name="Jar GB",
            product_category="HOUSEHOLD_CHEM",
            units_sold_annual_estimate=40,
        )

    chain["membership"] = membership
    chain["report"] = report
    return chain


def test_stale_determination_outranks_the_unpaid_membership_fee(api):
    """A submission that breaks both rules answers with the business-safety one.

    Activating a second stock keeping unit marks the determination stale without
    moving the producer out of OBLIGATION_DETERMINED, and the membership fee has
    never been recorded, yet the refusal is the staleness one and the report is
    left untouched in DRAFT.

    Design: Difficulty/priority_pair_validation_conflict/submit_stale_determination_beats_membership_fee_outstanding
    """
    chain = _report_awaiting_submission_with_an_unpaid_membership(api, make_stale=True)

    error = validate_error(
        api.submit_report(chain["report"]["id"], None, chain["officer_headers"]),
        ApiErrorId.DETERMINATION_STALE,
    )
    assert error["error_id"] != ApiErrorId.MEMBERSHIP_FEE_OUTSTANDING.value

    producer = validate_success(
        api.get_producer(chain["producer"]["id"], chain["officer_headers"])
    )
    assert_producer(producer, status="OBLIGATION_DETERMINED", determination_stale=True)
    assert_weight(producer["annual_packaging_weight_kg"], 7.500, "annual_packaging_weight_kg")

    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.DRAFT)
    registration = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    assert_weight(registration["reported_weight_kg_ytd"], 0.000, "reported_weight_kg_ytd")


def test_the_unpaid_membership_fee_answers_once_the_determination_is_current(api):
    """With the determination current, the same submission hits the fiscal rule.

    The identical chain without the second activation leaves only the outstanding
    membership fee to violate, which proves both rules were live in the combined
    case.

    Design: Difficulty/priority_pair_validation_conflict/submit_stale_determination_beats_membership_fee_outstanding
    """
    chain = _report_awaiting_submission_with_an_unpaid_membership(api, make_stale=False)
    producer = validate_success(
        api.get_producer(chain["producer"]["id"], chain["officer_headers"])
    )
    assert_producer(producer, determination_stale=False)

    validate_error(
        api.submit_report(chain["report"]["id"], None, chain["officer_headers"]),
        ApiErrorId.MEMBERSHIP_FEE_OUTSTANDING,
    )

    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.DRAFT, submitted_by_user_id=None)


# ---------------------------------------------------------------------------
# A structural uniqueness rule outranks the temporal shape of the same request
# ---------------------------------------------------------------------------
def _submitted_report_for_engagement(api, **chain_overrides):
    """A SUBMITTED 5.500 kg report whose registration is ACTIVE and paid up."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Priority B Co",
            annual_gross_revenue_usd=8000000,
            contact_email="pb@x.com",
        ),
        sku_overrides=dict(name="Jar GB1", product_category="HOUSEHOLD_CHEM"),
        **chain_overrides,
    )
    assert_report(chain["report"], submission_status=SubmissionStatus.SUBMITTED)
    return chain


def test_an_open_engagement_outranks_a_degenerate_fieldwork_window(api):
    """A duplicate assignment with a zero-length window answers the duplicate rule.

    The report already carries an ASSIGNED engagement, and the second request
    names a different verifier with a fieldwork window whose end equals its
    start; the refusal is the one-engagement-per-report rule and nothing about
    the report or the first engagement moves.

    Design: Difficulty/priority_pair_validation_conflict/engagement_already_open_beats_invalid_fieldwork_window
    """
    chain = _submitted_report_for_engagement(api)
    first = fx.assign_engagement(
        api, chain["report"], VERIFIER_USER_ID, "2026-09-08", "2026-09-10"
    )
    assert_engagement(first, status=EngagementStatus.ASSIGNED, round_index=1)

    error = validate_error(
        api.create_engagement(
            f.engagement_payload(
                chain["report"]["id"], VERIFIER_USER_ID_ALT, "2026-09-13", "2026-09-13"
            ),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.ENGAGEMENT_ALREADY_OPEN,
        409,
    )
    assert error["error_id"] != ApiErrorId.INVALID_FIELDWORK_WINDOW.value
    assert error["error_id"] != ApiErrorId.VERIFIER_CAPACITY_EXCEEDED.value

    unchanged = validate_success(api.get_engagement(first["id"], REGULATOR_HEADERS))
    assert_engagement(
        unchanged,
        status=EngagementStatus.ASSIGNED,
        round_index=1,
        verifier_user_id=VERIFIER_USER_ID,
    )
    engagements, meta = validate_paginated(
        api.list_engagements(
            REGULATOR_HEADERS, {"packaging_report_id": chain["report"]["id"]}
        )
    )
    assert len(engagements) == 1 and meta["total_count"] == 1
    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.UNDER_VERIFICATION)


def test_a_degenerate_fieldwork_window_answers_when_no_engagement_is_open(api):
    """With no engagement on the report, the same window shape is the refusal.

    The fieldwork window is closed at both ends and its end must be strictly
    later than its start, so an assignment naming one single day is refused on
    temporal grounds, which proves that rule was live in the combined case too.

    Design: Difficulty/priority_pair_validation_conflict/engagement_already_open_beats_invalid_fieldwork_window
    """
    chain = _submitted_report_for_engagement(api)

    validate_error(
        api.create_engagement(
            f.engagement_payload(
                chain["report"]["id"], VERIFIER_USER_ID_ALT, "2026-09-13", "2026-09-13"
            ),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.INVALID_FIELDWORK_WINDOW,
        422,
    )

    engagements, meta = validate_paginated(
        api.list_engagements(
            REGULATOR_HEADERS, {"packaging_report_id": chain["report"]["id"]}
        )
    )
    assert engagements == [] and meta["total_count"] == 0
    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.SUBMITTED)


# ---------------------------------------------------------------------------
# A temporal deadline outranks the fiscal membership requirement
# ---------------------------------------------------------------------------
def _lined_report_without_any_membership(api):
    """An ACTIVE registration with a lined DRAFT report and no organisation link."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Priority C Co",
            annual_gross_revenue_usd=8000000,
            contact_email="pc@x.com",
        ),
        sku_overrides=dict(name="Jar GC", product_category="HOUSEHOLD_CHEM"),
        with_membership=False,
        with_report=False,
    )
    memberships, meta = validate_paginated(
        api.list_memberships(
            chain["officer_headers"], {"registration_id": chain["registration"]["id"]}
        )
    )
    assert memberships == [] and meta["total_count"] == 0
    report = fx.make_report(api, chain["producer"], chain["registration"], chain["period"])
    chain["report"] = report
    chain["line"] = fx.add_line(api, chain["producer"], report, chain["sku"], 110)
    return chain


def test_a_closed_submission_window_outranks_the_missing_membership(api):
    """One day past the deadline the submission answers on the calendar.

    The registration has no organisation link at all, so the fiscal rule is
    violated too, yet the refusal names the closed window and the report keeps
    its single line in DRAFT with no filer recorded.

    Design: Difficulty/priority_pair_validation_conflict/submission_window_closed_beats_no_active_membership
    """
    chain = _lined_report_without_any_membership(api)
    fx.set_clock(api, "2026-10-01T00:00:00Z")

    error = validate_error(
        api.submit_report(chain["report"]["id"], None, chain["officer_headers"]),
        ApiErrorId.SUBMISSION_WINDOW_CLOSED,
        422,
    )
    assert error["error_id"] != ApiErrorId.NO_ACTIVE_MEMBERSHIP.value

    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(
        report,
        submission_status=SubmissionStatus.DRAFT,
        submitted_by_user_id=None,
        line_count=1,
    )


def test_the_missing_membership_answers_inside_the_submission_window(api):
    """Rewound to a date inside the window, the same submission answers fiscally.

    Nothing about the report or the registration changes, only the clock, and the
    refusal moves to the absent organisation link, which proves both rules were
    violated once the deadline had passed.

    Design: Difficulty/priority_pair_validation_conflict/submission_window_closed_beats_no_active_membership
    """
    chain = _lined_report_without_any_membership(api)
    fx.set_clock(api, "2026-10-01T00:00:00Z")
    validate_error(
        api.submit_report(chain["report"]["id"], None, chain["officer_headers"]),
        ApiErrorId.SUBMISSION_WINDOW_CLOSED,
        422,
    )

    fx.set_clock(api, "2026-09-20T00:00:00Z")
    validate_error(
        api.submit_report(chain["report"]["id"], None, chain["officer_headers"]),
        ApiErrorId.NO_ACTIVE_MEMBERSHIP,
        402,
    )

    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.DRAFT, line_count=1)
