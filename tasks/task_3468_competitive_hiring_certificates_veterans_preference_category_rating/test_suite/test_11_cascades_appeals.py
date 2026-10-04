"""Cross-entity cascades (rescission, cancellation) and the appeal machinery:
window, posture/grounds match, sustained-appeal loops, denial no-ops, and the
rated-pool conservation invariant.
"""
from test_helpers import (
    ADMIN, HR, HM, NON_EXISTENT_UUID, ApiErrorId,
    adjudicate_appeal_payload, api_client, file_appeal, file_appeal_payload,
    get_success_data, make_applicant_headers, make_sme_headers,
    rate_application, record_suitability, register_applicant,
    screen_application, set_clock, setup_accepted_offer, setup_application,
    setup_competitive_certificate, setup_open_announcement,
    setup_rated_application, submit_application, validate_error,
    validate_paginated, validate_success,
)


def test_suitability_unfavorable_rescission_chain(api):
    """PRD §3.9: "An `UNFAVORABLE` outcome rescinds the offer on the spot,
    running the same `NOT_SELECTED` cascade as a decline: application and entry
    flip, and `remaining_vacancies` climbs."

    Design: Difficulty/transitive_cascade/suitability_unfavorable_rescission_chain
    """
    ctx = setup_accepted_offer()  # vacancies 1; offer ACCEPTED at 2026-09-17
    offer, entry = ctx["offer"], ctx["entry"]
    announcement_id = ctx["announcement"]["id"]
    assert get_success_data(
        api_client.get_announcement(announcement_id, HR))["remaining_vacancies"] == 0

    review = record_suitability(offer["id"], "UNFAVORABLE")
    assert review["outcome"] == "UNFAVORABLE"

    reread_offer = get_success_data(api_client.get_offer(offer["id"], HR))
    assert reread_offer["status"] == "RESCINDED", "link 1: unfavorable review rescinds the offer"

    reread_entry = get_success_data(api_client.get_entry(entry["id"], HR))
    assert reread_entry["status"] == "NOT_SELECTED", "link 2: the entry flips with its offer"
    application = get_success_data(
        api_client.get_application(entry["application_id"], HR))
    assert application["status"] == "NOT_SELECTED"

    announcement = get_success_data(api_client.get_announcement(announcement_id, HR))
    assert announcement["remaining_vacancies"] == 1, "link 3: the vacancy counter is restored"


def test_announcement_cancel_three_hop_cascade(api):
    """PRD §3.2: "Cancelling a `CLOSED` or `CERT_ISSUED` announcement withdraws
    every application in `RECEIVED`, `QUALIFIED`, `RATED`, or `REFERRED`" and
    "cancels every `ACTIVE` certificate of the announcement, and rescinds every
    offer in `TENTATIVE`, `ACCEPTED`, or `EOD_SCHEDULED` that was created from
    those certificates' entries. Each rescinded offer flips its certificate
    entry from `SELECTED` to `NOT_SELECTED` and pushes `remaining_vacancies`
    back up by one."

    Design: Difficulty/transitive_cascade/announcement_cancel_three_hop_cascade
    """
    scenario = setup_competitive_certificate(vacancies_count=2)
    ctx = setup_accepted_offer(scenario)  # rank-1 selected, offer ACCEPTED
    certificate, offer, entry = ctx["certificate"], ctx["offer"], ctx["entry"]
    announcement_id = ctx["announcement"]["id"]
    selected_application_id = entry["application_id"]
    referred_application_id = ctx["applications"][1]["id"]
    assert get_success_data(
        api_client.get_announcement(announcement_id, HR))["remaining_vacancies"] == 1

    cancelled = validate_success(api_client.cancel_announcement(announcement_id, HM), 200)
    assert cancelled["status"] == "CANCELLED"

    reread_cert = get_success_data(api_client.get_certificate(certificate["id"], HR))
    assert reread_cert["status"] == "CANCELLED", "link 1: the active certificate follows its announcement"

    reread_offer = get_success_data(api_client.get_offer(offer["id"], HR))
    assert reread_offer["status"] == "RESCINDED", "link 2: the mid-flight offer is rescinded"

    reread_entry = get_success_data(api_client.get_entry(entry["id"], HR))
    assert reread_entry["status"] == "NOT_SELECTED", "link 3: the rescinded offer's entry flips"
    selected_application = get_success_data(
        api_client.get_application(selected_application_id, HR))
    assert selected_application["status"] == "NOT_SELECTED"

    referred_application = get_success_data(
        api_client.get_application(referred_application_id, HR))
    assert referred_application["status"] == "WITHDRAWN", (
        "unselected referred applications withdraw on cancellation")

    announcement = get_success_data(api_client.get_announcement(announcement_id, HR))
    assert announcement["remaining_vacancies"] == 2


def test_application_ineligible_qualification_appeal_loop(api):
    """PRD §3.9: "On `QUALIFICATION` or `PREFERENCE`, the application's
    `claimed_experience_months` is replaced by the appeal's
    `corrected_experience_months` and the qualification determination of §3.4
    is re-run: a passing re-screen moves the application `INELIGIBLE` →
    `QUALIFIED`, a failing one leaves it in `INELIGIBLE`, and either way the
    required and creditable month fields and `notified_at` are refreshed".

    Design: Difficulty/non_linear_state_machine/application_ineligible_qualification_appeal_loop
    """
    ctx = setup_open_announcement()  # clock 2026-09-10
    announcement = ctx["announcement"]
    applicant = register_applicant()
    application = submit_application(
        announcement, applicant,
        claimed_experience_months=17, claimed_education_months=20)

    set_clock("2026-09-14T00:00:00Z")
    screened = screen_application(application["id"])
    assert screened["status"] == "INELIGIBLE"
    assert screened["creditable_experience_months"] == 29  # 17 + min(20, 12)

    set_clock("2026-09-15T00:00:00Z")
    appeal = file_appeal(screened, applicant, "QUALIFICATION",
                         corrected_experience_months=30)
    assert appeal["status"] == "FILED"

    adjudicated = validate_success(
        api_client.adjudicate_appeal(
            appeal["id"],
            adjudicate_appeal_payload("SUSTAINED",
                                      adjudication_note="verified additional service"),
            HR),
        200)
    assert adjudicated["status"] == "SUSTAINED"

    reread = get_success_data(api_client.get_application(application["id"], HR))
    assert reread["status"] == "QUALIFIED", "the sustained appeal loops INELIGIBLE back to QUALIFIED"
    assert reread["claimed_experience_months"] == 30, "the corrected months replace the claim"
    assert reread["creditable_experience_months"] == 42  # 30 + min(20, 12)


def test_rated_pool_conservation_appeal_reopen_rerate(api):
    """PRD §3.9: "On `RATING`, the application's `ACCEPTED` assessment is forced
    to `RETURNED` with `return_reason` set to `APPEAL_SUSTAINED`, the
    application falls back `RATED` → `QUALIFIED` with its `technical_score` and
    `quality_category` cleared to null, and `notified_at` refreshes."
    PRD §3.5: "Acceptance moves the assessment `SUBMITTED` → `ACCEPTED` and
    requires the application still `QUALIFIED` with no other `ACCEPTED`
    assessment on it; acceptance cascades the application `QUALIFIED` →
    `RATED`".

    Design: Difficulty/compensating_invariant/rated_pool_conservation_appeal_reopen_rerate
    """
    ctx = setup_open_announcement()  # clock 2026-09-10
    announcement = ctx["announcement"]
    applicants, applications = [], []
    for _ in range(3):
        applicant = register_applicant()
        applicants.append(applicant)
        applications.append(submit_application(announcement, applicant))

    def rated_pool_size():
        resp = api_client.list_announcement_applications(
            announcement["id"], HR, params={"status": "RATED"})
        _items, meta = validate_paginated(resp)
        return meta["total_count"]

    set_clock("2026-09-14T00:00:00Z")  # notified_at anchor -> deadline 2026-09-28
    assessments = []
    for application, ratings in zip(applications, ((5, 5, 5), (5, 3, 5), (3, 5, 5))):
        screen_application(application["id"])
        assessment, rated = rate_application(application["id"], *ratings)
        assert rated["status"] == "RATED"
        assessments.append(assessment)
    assert rated_pool_size() == 3

    # Forward action: a sustained RATING appeal reopens the assessment (-1).
    set_clock("2026-09-15T00:00:00Z")
    appeal = file_appeal(applications[0], applicants[0], "RATING")
    adjudicated = validate_success(
        api_client.adjudicate_appeal(
            appeal["id"],
            adjudicate_appeal_payload("SUSTAINED",
                                      adjudication_note="SME overlooked supervisory experience"),
            HR),
        200)
    assert adjudicated["status"] == "SUSTAINED"

    reopened = get_success_data(api_client.get_application(applications[0]["id"], HR))
    assert reopened["status"] == "QUALIFIED"
    assert reopened["technical_score"] is None
    assert reopened["quality_category"] is None
    returned_assessment = get_success_data(
        api_client.get_assessment(assessments[0]["id"], HR))
    assert returned_assessment["status"] == "RETURNED"
    assert returned_assessment["return_reason"] == "APPEAL_SUSTAINED"
    assert rated_pool_size() == 2

    # Compensating action: resubmit and re-accept restores the pool (+1).
    resubmitted = validate_success(
        api_client.submit_assessment(
            assessments[0]["id"],
            {"rating_knowledge": 5, "rating_skill": 5, "rating_ability": 5},
            make_sme_headers("sme-1")),
        200)
    assert resubmitted["technical_score"] == 100
    validate_success(api_client.accept_assessment(assessments[0]["id"], HR), 200)

    rerated = get_success_data(api_client.get_application(applications[0]["id"], HR))
    assert rerated["status"] == "RATED"
    assert rerated["technical_score"] == 100
    assert rated_pool_size() == 3, "the appeal/reopen/resubmit cycle conserves pool headcount"


def test_denied_appeal_leaves_application_untouched(api):
    """PRD §3.9: "A denied appeal touches nothing: the application is left
    exactly as it stood when the appeal was filed."

    Design: Corner/state_machines/denied_appeal_leaves_application_untouched
    """
    ctx = setup_open_announcement()
    applicant = register_applicant()
    application = submit_application(
        ctx["announcement"], applicant,
        claimed_experience_months=0, claimed_education_months=0)

    set_clock("2026-09-14T00:00:00Z")
    screened = screen_application(application["id"])
    assert screened["status"] == "INELIGIBLE"

    set_clock("2026-09-15T00:00:00Z")
    appeal = file_appeal(screened, applicant, "QUALIFICATION",
                         corrected_experience_months=30)
    adjudicated = validate_success(
        api_client.adjudicate_appeal(
            appeal["id"],
            adjudicate_appeal_payload("DENIED", adjudication_note="no new evidence"),
            HR),
        200)
    assert adjudicated["status"] == "DENIED"

    reread = get_success_data(api_client.get_application(application["id"], HR))
    assert reread["status"] == "INELIGIBLE"
    assert reread["claimed_experience_months"] == 0, (
        "the corrected months are not applied on denial")


def test_appeal_at_exact_deadline_is_late(api):
    """PRD §3.9: "`deadline_at` is computed and stored as the application's
    `notified_at` plus fourteen days, and the filing itself must land strictly
    before that deadline — arriving at exactly `deadline_at` is already late
    and is rejected with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/validations/appeal_at_exact_deadline_is_late
    """
    ctx = setup_open_announcement()
    announcement = ctx["announcement"]
    timely_applicant = register_applicant()
    late_applicant = register_applicant()
    timely = submit_application(
        announcement, timely_applicant,
        claimed_experience_months=0, claimed_education_months=0)
    late = submit_application(
        announcement, late_applicant,
        claimed_experience_months=0, claimed_education_months=0)

    set_clock("2026-09-14T00:00:00Z")  # notified_at -> deadline 2026-09-28
    assert screen_application(timely["id"])["status"] == "INELIGIBLE"
    assert screen_application(late["id"])["status"] == "INELIGIBLE"

    set_clock("2026-09-27T00:00:00Z")  # one day before the deadline
    appeal = file_appeal(timely, timely_applicant, "QUALIFICATION",
                         corrected_experience_months=30)
    assert appeal["status"] == "FILED"
    assert appeal["deadline_at"] == "2026-09-28T00:00:00Z"

    set_clock("2026-09-28T00:00:00Z")  # exactly deadline_at: strictly-less fails
    resp = api_client.file_appeal(
        late["id"],
        file_appeal_payload("QUALIFICATION", corrected_experience_months=30),
        make_applicant_headers(late_applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)


def test_appeal_from_received_state_rejected(api):
    """PRD §3.9: "Filing requires the application in `INELIGIBLE` or `RATED`,
    and a `RATING` appeal additionally requires that no entry on an `ACTIVE`
    certificate references the application; violations are
    `ERR_APPEAL_NOT_ALLOWED_STATE` (HTTP 409)".

    Design: Corner/validations/appeal_from_received_state_rejected
    """
    ctx = setup_open_announcement()
    applicant, application = setup_application(ctx["announcement"])
    assert application["status"] == "RECEIVED"

    resp = api_client.file_appeal(
        application["id"],
        file_appeal_payload("QUALIFICATION", corrected_experience_months=30),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_ALLOWED_STATE)

    appeals, meta = validate_paginated(
        api_client.list_application_appeals(application["id"], HR))
    assert meta["total_count"] == 0, "no appeal row may be created by the rejected filing"
    assert appeals == []


def test_qualification_appeal_on_rated_application_rejected(api):
    """PRD §3.9: "Grounds must match posture: `QUALIFICATION` only from
    `INELIGIBLE`, `RATING` only from `RATED`, and `PREFERENCE` from either,
    with mismatches drawing `ERR_APPEAL_GROUND_MISMATCH` (HTTP 422)."

    Design: Corner/validations/qualification_appeal_on_rated_application_rejected
    """
    ctx = setup_open_announcement()
    applicant, application, _assessment = setup_rated_application(
        ctx["announcement"], 4, 4, 4)  # RATED at 2026-09-10
    assert application["status"] == "RATED"

    set_clock("2026-09-15T00:00:00Z")  # inside the window (deadline 2026-09-24)
    resp = api_client.file_appeal(
        application["id"],
        file_appeal_payload("QUALIFICATION", corrected_experience_months=60),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_APPEAL_GROUND_MISMATCH)


def test_platform_admin_cannot_classify(api):
    """PRD §2.1: "A request whose role is not listed among an endpoint's
    authorized roles, or that violates an entity-backed ownership rule, is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/platform_admin_cannot_classify
    """
    # PlatformAdmin owns only the test-driving clock; role authorization fires
    # before existence, so even a random id draws 403.
    resp = api_client.classify_position(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
