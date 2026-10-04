"""Composite setup helpers (five tiers).

Every fixture builds its preconditions from scratch via the PRD endpoints —
the runner restarts the server before every test, so nothing carries over.

Default clock choreography (all instants reachable from the §2.5 startup
default of 2026-09-01T00:00:00Z, moving monotonically forward):
  create series/position/announcement -> open          (clock at startup)
  set clock 2026-09-10 -> applications submitted       (inside [09-05, 09-20))
  screening + SME assessment/accept                    (still 2026-09-10+)
  close -> set clock 2026-09-15 -> issue certificate   (expires +60d)
  set clock 2026-09-16 -> selection (offer TENTATIVE, due +5d)
  set clock 2026-09-17 -> applicant ACCEPT
  suitability/clearance -> schedule-eod 2026-09-25 -> clock 2026-09-25 -> confirm
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_announcement_payload, create_applicant_payload, create_assessment_payload,
    create_pass_over_request_payload, create_position_payload, create_series_payload,
    file_appeal_payload, record_security_clearance_payload,
    record_suitability_review_payload, reclassify_position_payload,
    respond_to_offer_payload, schedule_eod_payload, select_entry_payload,
    set_clock_payload, submit_application_payload, upload_document_payload,
)
from .test_users import (
    SECURITY_ADJUDICATOR_ID, SME_USER_ID, SUITABILITY_REVIEWER_ID, TEST_USERS,
    make_applicant_headers, make_security_adjudicator_headers, make_sme_headers,
    make_suitability_reviewer_headers,
)

HR = TEST_USERS["hr_specialist_headers"]
HM = TEST_USERS["hiring_manager_headers"]
SO = TEST_USERS["selecting_official_headers"]
OPM = TEST_USERS["opm_delegate_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

# Fixture clock instants (not PRD constants — choreography choices consistent
# with the logical clock's 2026-09-01 startup and the default open period).
APPLY_CLOCK = "2026-09-10T00:00:00Z"
ISSUE_CLOCK = "2026-09-15T00:00:00Z"
SELECT_CLOCK = "2026-09-16T00:00:00Z"
ACCEPT_CLOCK = "2026-09-17T00:00:00Z"
DEFAULT_EOD_DATE = "2026-09-25T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creation
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Drive the server logical clock (PRD §2.5)."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    get_success_data(resp)


def create_series(**overrides) -> dict:
    resp = api_client.create_series(create_series_payload(**overrides), HR)
    return get_success_data(resp)


def create_draft_position(series_id: str, **overrides) -> dict:
    resp = api_client.create_position(create_position_payload(series_id, **overrides), HM)
    return get_success_data(resp)


def classify_position(position_id: str) -> dict:
    resp = api_client.classify_position(position_id, HR)
    return get_success_data(resp)


def create_classified_position(series_overrides=None, position_overrides=None) -> tuple:
    """Series + position classified via the point-factor method.
    Returns (series, position) with position.status == CLASSIFIED."""
    series = create_series(**(series_overrides or {}))
    position = create_draft_position(series["id"], **(position_overrides or {}))
    position = classify_position(position["id"])
    return series, position


def create_announcement(position_id: str, **overrides) -> dict:
    resp = api_client.create_announcement(
        position_id, create_announcement_payload(**overrides), HM)
    return get_success_data(resp)


def open_announcement(announcement_id: str) -> dict:
    resp = api_client.open_announcement(announcement_id, HM)
    return get_success_data(resp)


def setup_open_announcement(series_overrides=None, position_overrides=None,
                            announcement_overrides=None, apply_clock=APPLY_CLOCK) -> dict:
    """Classified position + OPEN announcement with the clock inside the open
    period. Returns {"series", "position", "announcement"}."""
    series, position = create_classified_position(series_overrides, position_overrides)
    announcement = create_announcement(position["id"], **(announcement_overrides or {}))
    announcement = open_announcement(announcement["id"])
    if apply_clock is not None:
        set_clock(apply_clock)
    return {"series": series, "position": position, "announcement": announcement}


# ---------------------------------------------------------------------------
# Tier 1: applicants, documents, applications, screening
# ---------------------------------------------------------------------------
def register_applicant(**overrides) -> dict:
    """Self-service registration under the Applicant role; the supplied
    X-User-ID is ignored and the response id becomes the identity (PRD §2.1)."""
    resp = api_client.create_applicant(
        create_applicant_payload(**overrides), TEST_USERS["applicant_headers"])
    return get_success_data(resp)


def upload_document(applicant: dict, doc_type: str) -> dict:
    """Unverified upload by the owning applicant."""
    resp = api_client.upload_document(
        applicant["id"], upload_document_payload(doc_type),
        make_applicant_headers(applicant["id"]))
    return get_success_data(resp)


def verify_document(document_id: str) -> dict:
    resp = api_client.verify_document(document_id, OPM)
    return get_success_data(resp)


def upload_and_verify_document(applicant: dict, doc_type: str) -> dict:
    return verify_document(upload_document(applicant, doc_type)["id"])


def register_verified_preference_applicant(claim: str = "FIVE_POINT", **overrides) -> dict:
    """Applicant whose preference_verified is True: FIVE_POINT needs a verified
    DD214; ten-point claims need verified DD214 + VA_LETTER (PRD §3.3)."""
    applicant = register_applicant(veteran_preference_claim=claim, **overrides)
    if claim in ("FIVE_POINT", "TEN_POINT_CP", "TEN_POINT_CPS"):
        upload_and_verify_document(applicant, "DD214")
    if claim in ("TEN_POINT_CP", "TEN_POINT_CPS"):
        upload_and_verify_document(applicant, "VA_LETTER")
    resp = api_client.get_applicant(applicant["id"], HR)
    return get_success_data(resp)


def submit_application(announcement: dict, applicant: dict, **overrides) -> dict:
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(applicant["id"], **overrides),
        make_applicant_headers(applicant["id"]))
    return get_success_data(resp)


def screen_application(application_id: str) -> dict:
    resp = api_client.screen_application(application_id, HR)
    return get_success_data(resp)


def setup_application(announcement: dict, **application_overrides) -> tuple:
    """(applicant, application in RECEIVED)."""
    applicant = register_applicant()
    application = submit_application(announcement, applicant, **application_overrides)
    return applicant, application


def setup_qualified_application(announcement: dict, applicant=None,
                                **application_overrides) -> tuple:
    """(applicant, application in QUALIFIED). Default claim qualifies against
    the default series/grade-9 position (required 30)."""
    if applicant is None:
        applicant = register_applicant()
    application = submit_application(announcement, applicant, **application_overrides)
    application = screen_application(application["id"])
    assert application["status"] == "QUALIFIED", (
        f"setup expected QUALIFIED, got {application['status']}")
    return applicant, application


def setup_ineligible_application(announcement: dict, applicant=None,
                                 **application_overrides) -> tuple:
    """(applicant, application in INELIGIBLE) via a shortfall claim."""
    overrides = {"claimed_experience_months": 0, "claimed_education_months": 0}
    overrides.update(application_overrides)
    if applicant is None:
        applicant = register_applicant()
    application = submit_application(announcement, applicant, **overrides)
    application = screen_application(application["id"])
    assert application["status"] == "INELIGIBLE", (
        f"setup expected INELIGIBLE, got {application['status']}")
    return applicant, application


# ---------------------------------------------------------------------------
# Tier 2: SME assessment to RATED
# ---------------------------------------------------------------------------
def rate_application(application_id: str, rating_knowledge: int = 5,
                     rating_skill: int = 5, rating_ability: int = 5,
                     sme_user_id: str = SME_USER_ID) -> tuple:
    """Create (DRAFT) -> submit -> accept an assessment; the owning SME id is
    threaded through submit per the authorship rule. Returns (assessment ACCEPTED,
    application re-read in RATED)."""
    sme_headers = make_sme_headers(sme_user_id)
    resp = api_client.create_assessment(
        application_id,
        create_assessment_payload(rating_knowledge, rating_skill, rating_ability),
        sme_headers)
    assessment = get_success_data(resp)
    resp = api_client.submit_assessment(assessment["id"], {}, sme_headers)
    assessment = get_success_data(resp)
    resp = api_client.accept_assessment(assessment["id"], HR)
    assessment = get_success_data(resp)
    resp = api_client.get_application(application_id, HR)
    application = get_success_data(resp)
    assert application["status"] == "RATED", (
        f"setup expected RATED, got {application['status']}")
    return assessment, application


def setup_rated_application(announcement: dict, rating_knowledge: int = 5,
                            rating_skill: int = 5, rating_ability: int = 5,
                            sme_user_id: str = SME_USER_ID,
                            applicant=None, **application_overrides) -> tuple:
    """(applicant, application RATED, assessment ACCEPTED)."""
    applicant, application = setup_qualified_application(
        announcement, applicant=applicant, **application_overrides)
    assessment, application = rate_application(
        application["id"], rating_knowledge, rating_skill, rating_ability, sme_user_id)
    return applicant, application, assessment


# ---------------------------------------------------------------------------
# Tier 3: certificates
# ---------------------------------------------------------------------------
def issue_certificate(announcement: dict, issue_clock=ISSUE_CLOCK) -> dict:
    """Close the announcement, advance the clock, issue. Returns the certificate."""
    get_success_data(api_client.close_announcement(announcement["id"], HM))
    if issue_clock is not None:
        set_clock(issue_clock)
    resp = api_client.issue_certificate(announcement["id"], HR)
    return get_success_data(resp)


def list_entries(certificate_id: str) -> list:
    """Entries in rank_position order."""
    resp = api_client.list_certificate_entries(certificate_id, HR)
    entries, _meta = validate_paginated(resp)
    return entries


def setup_competitive_certificate(ratings_list=((5, 5, 5), (5, 3, 5), (3, 5, 5)),
                                  vacancies_count: int = 1,
                                  announcement_overrides=None,
                                  series_overrides=None,
                                  position_overrides=None,
                                  applicants=None) -> dict:
    """Full CATEGORY_RATING pipeline: OPEN announcement, one screened->rated
    application per ratings tuple, close, issue certificate.

    Default ratings score 100/98/96 (all BEST_QUALIFIED at default cuts),
    matching the standard three-candidate roster. `applicants` (optional) is a
    list of pre-registered applicant dicts, one per ratings tuple, for
    preference-bearing scenarios.
    Returns {"series", "position", "announcement", "applicants",
             "applications", "assessments", "certificate", "entries"}."""
    ann_overrides = {"vacancies_count": vacancies_count}
    ann_overrides.update(announcement_overrides or {})
    ctx = setup_open_announcement(series_overrides, position_overrides, ann_overrides)
    announcement = ctx["announcement"]

    if applicants is None:
        applicants = [register_applicant() for _ in ratings_list]
    assert len(applicants) == len(ratings_list)

    applications, assessments = [], []
    for applicant, (rk, rs, ra) in zip(applicants, ratings_list):
        application = submit_application(announcement, applicant)
        application = screen_application(application["id"])
        assert application["status"] == "QUALIFIED"
        assessment, application = rate_application(application["id"], rk, rs, ra)
        applications.append(application)
        assessments.append(assessment)

    certificate = issue_certificate(announcement)
    entries = list_entries(certificate["id"])
    resp = api_client.get_announcement(announcement["id"], HR)
    announcement = get_success_data(resp)
    return {**ctx, "announcement": announcement, "applicants": applicants,
            "applications": applications, "assessments": assessments,
            "certificate": certificate, "entries": entries}


def setup_unranked_certificate(num_applicants: int = 1, vacancies_count: int = 1,
                               hiring_authority: str = "DIRECT_HIRE",
                               announcement_overrides=None,
                               series_overrides=None,
                               position_overrides=None) -> dict:
    """UNRANKED pipeline (direct-hire style): QUALIFIED applications only, no
    assessments; certificate roster is every QUALIFIED application."""
    ann_overrides = {"hiring_authority": hiring_authority,
                     "assessment_method": "UNRANKED",
                     "vacancies_count": vacancies_count}
    ann_overrides.update(announcement_overrides or {})
    ctx = setup_open_announcement(series_overrides, position_overrides, ann_overrides)
    announcement = ctx["announcement"]

    applicants, applications = [], []
    for _ in range(num_applicants):
        applicant, application = setup_qualified_application(announcement)
        applicants.append(applicant)
        applications.append(application)

    certificate = issue_certificate(announcement)
    entries = list_entries(certificate["id"])
    resp = api_client.get_announcement(announcement["id"], HR)
    announcement = get_success_data(resp)
    return {**ctx, "announcement": announcement, "applicants": applicants,
            "applications": applications, "certificate": certificate,
            "entries": entries}


def setup_pass_over_scenario() -> dict:
    """Certificate whose rank-1 entry is preference-eligible and whose rank-2
    entry is not: vet V (verified FIVE_POINT, score 96), N1 (100), N2 (98) —
    all BEST_QUALIFIED, so the preference group orders V ahead of N1.
    Returns the competitive-certificate scenario dict."""
    vet = register_verified_preference_applicant("FIVE_POINT")
    n1 = register_applicant()
    n2 = register_applicant()
    return setup_competitive_certificate(
        ratings_list=((3, 5, 5), (5, 5, 5), (5, 3, 5)),
        applicants=[vet, n1, n2])


# ---------------------------------------------------------------------------
# Tier 4: selection, offer response, pre-employment gauntlet, EOD
# ---------------------------------------------------------------------------
def select_entry(certificate_id: str, entry_id: str,
                 select_clock=SELECT_CLOCK) -> dict:
    """Select a REFERRED entry; returns the created Offer (TENTATIVE)."""
    if select_clock is not None:
        set_clock(select_clock)
    resp = api_client.select_entry(certificate_id, select_entry_payload(entry_id), SO)
    return get_success_data(resp)


def accept_offer(offer: dict, applicant: dict, accept_clock=ACCEPT_CLOCK) -> dict:
    if accept_clock is not None:
        set_clock(accept_clock)
    resp = api_client.respond_to_offer(
        offer["id"], respond_to_offer_payload("ACCEPT"),
        make_applicant_headers(applicant["id"]))
    return get_success_data(resp)


def setup_selected_offer(scenario=None, entry_index: int = 0, **scenario_kwargs) -> dict:
    """Competitive certificate + selection of the entry at entry_index.
    Returns the scenario dict plus "entry" and "offer" (TENTATIVE)."""
    if scenario is None:
        scenario = setup_competitive_certificate(**scenario_kwargs)
    entry = scenario["entries"][entry_index]
    offer = select_entry(scenario["certificate"]["id"], entry["id"])
    return {**scenario, "entry": entry, "offer": offer}


def setup_accepted_offer(scenario=None, entry_index: int = 0, **scenario_kwargs) -> dict:
    """Selected offer accepted by its applicant. Adds "offer" (ACCEPTED)."""
    ctx = setup_selected_offer(scenario, entry_index, **scenario_kwargs)
    application_id = ctx["entry"]["application_id"]
    applicant = next(a for a, ap in zip(ctx["applicants"], ctx["applications"])
                     if ap["id"] == application_id)
    offer = accept_offer(ctx["offer"], applicant)
    return {**ctx, "applicant": applicant, "offer": offer}


def record_suitability(offer_id: str, outcome: str = "FAVORABLE",
                       reviewer_id: str = SUITABILITY_REVIEWER_ID) -> dict:
    resp = api_client.record_suitability_review(
        offer_id, record_suitability_review_payload(outcome),
        make_suitability_reviewer_headers(reviewer_id))
    return get_success_data(resp)


def record_clearance(offer_id: str, outcome: str = "FAVORABLE_FINAL",
                     adjudicator_id: str = SECURITY_ADJUDICATOR_ID) -> dict:
    resp = api_client.record_security_clearance(
        offer_id, record_security_clearance_payload(outcome),
        make_security_adjudicator_headers(adjudicator_id))
    return get_success_data(resp)


def setup_offer_with_favorable_suitability(scenario=None, **kwargs) -> dict:
    """Accepted offer + FAVORABLE suitability review. Adds "suitability_review"."""
    ctx = setup_accepted_offer(scenario, **kwargs)
    review = record_suitability(ctx["offer"]["id"], "FAVORABLE")
    return {**ctx, "suitability_review": review}


def setup_eod_scheduled_offer(scenario=None, eod_date: str = DEFAULT_EOD_DATE,
                              sensitivity: str = "NONE", **kwargs) -> dict:
    """Accepted offer + favorable suitability + the clearance the sensitivity
    gate requires + schedule-eod. Default position sensitivity NONE needs no
    clearance record. Returns ctx with "offer" in EOD_SCHEDULED."""
    if scenario is None:
        position_overrides = {"sensitivity_level": sensitivity}
        kwargs.setdefault("position_overrides", position_overrides)
    ctx = setup_offer_with_favorable_suitability(scenario, **kwargs)
    offer_id = ctx["offer"]["id"]
    if sensitivity == "SECRET":
        record_clearance(offer_id, "FAVORABLE_INTERIM")
    elif sensitivity == "TOP_SECRET":
        record_clearance(offer_id, "FAVORABLE_FINAL")
    resp = api_client.schedule_eod(offer_id, schedule_eod_payload(eod_date), SO)
    offer = get_success_data(resp)
    assert offer["status"] == "EOD_SCHEDULED"
    return {**ctx, "offer": offer}


def setup_entered_on_duty(scenario=None, eod_date: str = DEFAULT_EOD_DATE,
                          **kwargs) -> dict:
    """Full lifecycle to ENTERED_ON_DUTY: clock advanced to eod_date, confirm
    creates the Appointment and flips the application to HIRED."""
    ctx = setup_eod_scheduled_offer(scenario, eod_date=eod_date, **kwargs)
    set_clock(eod_date)
    resp = api_client.confirm_eod(ctx["offer"]["id"], HR)
    offer = get_success_data(resp)
    assert offer["status"] == "ENTERED_ON_DUTY"
    resp = api_client.list_appointments(offer["id"], HR)
    appointments, _meta = validate_paginated(resp)
    return {**ctx, "offer": offer, "appointments": appointments}


# ---------------------------------------------------------------------------
# Tier 5: appeals
# ---------------------------------------------------------------------------
def file_appeal(application: dict, applicant: dict, grounds: str,
                corrected_experience_months=None) -> dict:
    """File an appeal as the owning applicant; returns the FILED appeal."""
    overrides = {}
    if corrected_experience_months is not None:
        overrides["corrected_experience_months"] = corrected_experience_months
    resp = api_client.file_appeal(
        application["id"], file_appeal_payload(grounds, **overrides),
        make_applicant_headers(applicant["id"]))
    return get_success_data(resp)
