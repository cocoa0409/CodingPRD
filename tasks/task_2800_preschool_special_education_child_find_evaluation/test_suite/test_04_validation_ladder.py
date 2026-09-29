"""The ordered refusal ladder of PRD §2.5, rung by rung.

Each test drives one write endpoint into a single named refusal, and — where PRD
§2.5 pins the relative order of two rules — into the refusal the higher rung owns
when a request breaks both rules at once. Every rung under test here is a
business rule rather than a request-shape rule: chair eligibility, segregation of
duties, the discipline map, site eligibility, the duplicate-domain guard, the
consent gates, the service-setting shapes, the override justification, the chair's
evaluation ceiling and the kindergarten conference lead time.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fields_absent
from test_helpers.constants import INITIAL_LOGICAL_CLOCK, date_part, plus_days_date
from test_helpers.test_users import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]


# --------------------------------------------------------------- local helpers
def _case_with_drafted_report(api, child_id=None, **overrides):
    """A case at REPORT_DRAFTED: five completed domains plus the chair's narrative."""
    context = fx.setup_case_with_five_completed_domains(api, child_id, **overrides)
    fx.draft_report(api, context["case"]["id"], context["chair"]["id"])
    context["case"] = fx.read_case(api, context["case"]["id"])
    return context


def _determine_eligible(api, case, **payload_overrides):
    """Record an ELIGIBLE determination without validating it, so a test can assert the refusal."""
    payload = f.eligible_determination_payload(case["version"], **payload_overrides)
    return api.determine_eligibility(case["id"], payload, PLACEMENT)


def _open_case(api, referral_id, chair_provider_id, **overrides):
    """Open an evaluation case without validating the outcome."""
    return api.open_evaluation_case(
        referral_id, f.evaluation_case_payload(chair_provider_id, **overrides), COORDINATOR
    )


def _schedule(api, case_id, evaluator_provider_id, **overrides):
    """Schedule a domain assessment without validating the outcome."""
    return api.schedule_domain_assessment(
        case_id, f.domain_assessment_payload(evaluator_provider_id, **overrides), COORDINATOR
    )


# ------------------------------------------- rung 9 chair eligibility vs rung 13
def test_ineligible_chair_outranks_the_missing_consent_gate(api):
    """PRD §2.5: "Validation is a single ordered ladder; the **first** rule that a
    request violates determines the response, and no later rule is consulted."
    PRD §2.5 rung 9: "Chair eligibility: the provider named as `chair_provider_id`
    when an evaluation case is opened must be chair-eligible, else
    `ERR_CHAIR_NOT_ELIGIBLE` (422)."
    PRD §2.5 rung 13: "Prior written parental consent for evaluation has been
    granted on the referral before any evaluation activity, else
    `ERR_CONSENT_NOT_GRANTED` (409), guarding evaluation-case opening."

    Design: Corner/validations/chair_eligibility_outranks_the_consent_gate
    """
    slp = fx.register_provider(api, discipline="SLP")
    chair = fx.register_chair(api)
    referral = fx.create_referral(api)

    both_broken = _open_case(api, referral["id"], slp["id"])
    validate_error(both_broken, ApiErrorId.ERR_CHAIR_NOT_ELIGIBLE.value)

    consent_only = _open_case(api, referral["id"], chair["id"])
    validate_error(consent_only, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value)


def test_an_ineligible_chair_is_refused_on_an_authorized_referral(api):
    """PRD §3.5: "The named provider must be chair-eligible — its `discipline` must
    be `SCHOOL_PSYCHOLOGIST` or `ECSE_TEACHER`, which is exactly what
    `is_evaluation_chair_eligible` records — or the request is refused with
    `ERR_CHAIR_NOT_ELIGIBLE`."
    PRD §3.1: "Registration derives `is_evaluation_chair_eligible` as true exactly
    when the provider's `discipline` is `SCHOOL_PSYCHOLOGIST` or `ECSE_TEACHER`,
    and false for every other discipline."

    Design: Corner/validations/chair_eligibility_outranks_the_consent_gate
    """
    granted = fx.setup_referral_with_granted_consent(api)
    slp = fx.register_provider(api, discipline="SLP")

    refused = _open_case(api, granted["referral"]["id"], slp["id"])
    validate_error(refused, ApiErrorId.ERR_CHAIR_NOT_ELIGIBLE.value)

    assert fx.read_provider(api, slp["id"])["is_evaluation_chair_eligible"] is False, (
        "an SLP is never chair-eligible"
    )


def test_a_chair_eligible_provider_opens_the_case_and_takes_a_caseload_slot(api):
    """PRD §3.5: "The named provider must be chair-eligible — its `discipline` must
    be `SCHOOL_PSYCHOLOGIST` or `ECSE_TEACHER`, which is exactly what
    `is_evaluation_chair_eligible` records — or the request is refused with
    `ERR_CHAIR_NOT_ELIGIBLE`."
    PRD §3.5: "A provider's `active_evaluation_count` is the number of evaluation
    cases that provider chairs whose `status` is one of the five non-terminal
    values `PLANNED`, `IN_PROGRESS`, `DOMAINS_COMPLETE`, `REPORT_DRAFTED` and
    `REVISIONS_REQUESTED`."

    Design: Corner/validations/chair_eligibility_outranks_the_consent_gate
    """
    granted = fx.setup_referral_with_granted_consent(api)
    chair = fx.register_chair(api)

    case = validate_success(_open_case(api, granted["referral"]["id"], chair["id"]), 201)
    assert case["chair_provider_id"] == chair["id"]
    assert case["status"] == "PLANNED", f"a new case opens at PLANNED, got {case['status']}"

    after = fx.read_provider(api, chair["id"])
    assert after["is_evaluation_chair_eligible"] is True
    assert after["active_evaluation_count"] == 1, (
        f"the chair now holds one live case, got {after['active_evaluation_count']}"
    )


# ------------------------------ rung 16 segregation of duties vs rung 19 mapping
def test_the_chair_may_not_evaluate_a_domain_its_own_discipline_covers(api):
    """PRD §3.5: "**Segregation of duties** comes first among them: the evaluator of
    a domain assessment may not be the chair of the same case, so a request whose
    `evaluator_provider_id` equals the case's `chair_provider_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.5: "`COGNITIVE` by a `SCHOOL_PSYCHOLOGIST` or an `ECSE_TEACHER`"

    Design: Corner/validations/segregation_of_duties_outranks_the_discipline_map
    """
    context = fx.setup_case(api)
    chair = context["chair"]
    assert chair["discipline"] == "SCHOOL_PSYCHOLOGIST"

    # COGNITIVE is a domain this chair's own discipline may assess, so only the
    # duty rule can fire.
    refused = _schedule(api, context["case"]["id"], chair["id"], domain="COGNITIVE")
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_segregation_of_duties_outranks_the_discipline_map(api):
    """PRD §2.5 rung 16: "Segregation of duties, else `ERR_SEGREGATION_OF_DUTIES`
    (422), guarding domain-assessment scheduling and consent-request issuance."
    PRD §2.5 rung 19: "Discipline match, else `ERR_DISCIPLINE_MISMATCH` (422),
    guarding service-line staffing and domain-assessment scheduling."
    PRD §2.5: "Validation is a single ordered ladder; the **first** rule that a
    request violates determines the response, and no later rule is consulted."

    Design: Corner/validations/segregation_of_duties_outranks_the_discipline_map
    """
    context = fx.setup_case(api)
    chair = context["chair"]

    # A SCHOOL_PSYCHOLOGIST chair asked to take COMMUNICATION breaks the duty rule
    # and the discipline map at once; the duty rule sits higher on the ladder.
    refused = _schedule(api, context["case"]["id"], chair["id"], domain="COMMUNICATION")
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_an_evaluator_other_than_the_chair_takes_the_domain(api):
    """PRD §3.5: "`COMMUNICATION` may be assessed by an `SLP` or an `ECSE_TEACHER`"
    PRD §3.5: "The first assessment scheduled on a case moves the case
    `PLANNED → IN_PROGRESS`."

    Design: Corner/validations/segregation_of_duties_outranks_the_discipline_map
    """
    context = fx.setup_case(api)
    ecse = fx.register_provider(api, discipline="ECSE_TEACHER")

    scheduled = fx.schedule_assessment(
        api, context["case"]["id"], ecse["id"], domain="COMMUNICATION"
    )
    assert scheduled["evaluator_provider_id"] == ecse["id"]
    assert scheduled["status"] == "SCHEDULED"
    assert fx.read_case(api, context["case"]["id"])["status"] == "IN_PROGRESS"


# ------------------------------------- rung 19 discipline map, on both surfaces
def test_an_occupational_therapist_may_not_assess_communication(api):
    """PRD §3.5: "The evaluator's discipline must be able to assess the requested
    domain, or the request is refused with `ERR_DISCIPLINE_MISMATCH`:
    `COMMUNICATION` may be assessed by an `SLP` or an `ECSE_TEACHER`;
    `PHYSICAL_MOTOR` by an `OT` or a `PT`"

    Design: Corner/validations/discipline_map_is_enforced_on_both_assessments_and_staffing
    """
    context = fx.setup_case(api)
    ot = fx.register_provider(api, discipline="OT")

    refused = _schedule(api, context["case"]["id"], ot["id"], domain="COMMUNICATION")
    validate_error(refused, ApiErrorId.ERR_DISCIPLINE_MISMATCH.value)


def test_an_interpreter_may_not_assess_the_permissive_adaptive_domain(api):
    """PRD §3.5: "The evaluator's discipline must be able to assess the requested
    domain, or the request is refused with `ERR_DISCIPLINE_MISMATCH`: ... and
    `ADAPTIVE` by a provider of any discipline other than `INTERPRETER`."

    Design: Corner/validations/discipline_map_is_enforced_on_both_assessments_and_staffing
    """
    context = fx.setup_case(api)
    interpreter = fx.register_interpreter(api)

    # ADAPTIVE is open to every discipline but this one.
    refused = _schedule(api, context["case"]["id"], interpreter["id"], domain="ADAPTIVE")
    validate_error(refused, ApiErrorId.ERR_DISCIPLINE_MISMATCH.value)


def test_staffing_demands_the_providers_discipline_equal_the_lines(api):
    """PRD §3.8: "The named provider's `discipline` must equal the line's own
    `discipline`, and a provider whose discipline is `INTERPRETER` may never be
    staffed to a service line at all; either failure is `ERR_DISCIPLINE_MISMATCH`."

    Design: Corner/validations/discipline_map_is_enforced_on_both_assessments_and_staffing
    """
    context = fx.setup_draft_plan(api, setting="ITINERANT_ONLY")
    line = fx.add_line(
        api, context["plan"]["id"], discipline="OT", weekly_minutes=100, delivery_model="DIRECT"
    )
    slp = fx.register_provider(api, discipline="SLP")

    refused = api.staff_service_line(
        line["id"], f.staffing_payload(slp["id"], slp["version"]), PLACEMENT
    )
    validate_error(refused, ApiErrorId.ERR_DISCIPLINE_MISMATCH.value)
    assert fx.read_line(api, line["id"])["status"] == "PROPOSED"

    ot = fx.register_provider(api, discipline="OT")
    staffed = fx.staff_line(api, line["id"], ot["id"])
    assert staffed["status"] == "STAFFED"
    assert staffed["provider_id"] == ot["id"]
    assert fx.read_provider(api, slp["id"])["direct_weekly_service_minutes"] == 0, (
        "the refused staffing left the SLP's ledger untouched"
    )


def test_an_interpreter_may_never_be_staffed_to_a_service_line(api):
    """PRD §3.8: "a provider whose discipline is `INTERPRETER` may never be staffed
    to a service line at all; either failure is `ERR_DISCIPLINE_MISMATCH`."

    Design: Corner/validations/discipline_map_is_enforced_on_both_assessments_and_staffing
    """
    context = fx.setup_draft_plan(api, setting="ITINERANT_ONLY")
    line = fx.add_line(
        api, context["plan"]["id"], discipline="SLP", weekly_minutes=100, delivery_model="DIRECT"
    )
    interpreter = fx.register_interpreter(api)

    refused = api.staff_service_line(
        line["id"], f.staffing_payload(interpreter["id"], interpreter["version"]), PLACEMENT
    )
    validate_error(refused, ApiErrorId.ERR_DISCIPLINE_MISMATCH.value)
    assert fx.read_line(api, line["id"])["status"] == "PROPOSED"


# ---------------------------------- rung 20 site eligibility, all three facets
def test_a_site_that_is_not_host_approved_cannot_host_a_screening_event(api):
    """PRD §3.2: "The host site must be `ACTIVE` **and** have
    `screening_host_approved` true; a site failing either facet is refused with
    `ERR_SITE_NOT_ELIGIBLE`."

    Design: Corner/validations/site_eligibility_covers_status_host_approval_and_language
    """
    site = fx.register_site(api, screening_host_approved=False)
    assert site["status"] == "ACTIVE", "only the host-approval facet is broken here"

    refused = api.create_screening_event(f.screening_event_payload(site["id"]), COORDINATOR)
    validate_error(refused, ApiErrorId.ERR_SITE_NOT_ELIGIBLE.value)


def test_an_inactive_site_cannot_host_a_screening_event(api):
    """PRD §3.2: "The host site must be `ACTIVE` **and** have
    `screening_host_approved` true; a site failing either facet is refused with
    `ERR_SITE_NOT_ELIGIBLE`."

    Design: Corner/validations/site_eligibility_covers_status_host_approval_and_language
    """
    site = fx.register_site(api, status="INACTIVE")
    assert site["screening_host_approved"] is True, "only the status facet is broken here"

    refused = api.create_screening_event(f.screening_event_payload(site["id"]), COORDINATOR)
    validate_error(refused, ApiErrorId.ERR_SITE_NOT_ELIGIBLE.value)


def test_a_placement_site_must_support_the_childs_language(api):
    """PRD §3.7: "Where a site is named it must be `ACTIVE` and its
    `languages_supported` must cover the child's `primary_language_code`, or the
    determination is refused with `ERR_SITE_NOT_ELIGIBLE`."

    Design: Corner/validations/site_eligibility_covers_status_host_approval_and_language
    """
    context = _case_with_drafted_report(api)
    assert context["child"]["primary_language_code"] == "en"
    spanish_only = fx.register_site(api, languages_supported=["es"])

    refused = _determine_eligible(
        api,
        context["case"],
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=spanish_only["id"],
    )
    validate_error(refused, ApiErrorId.ERR_SITE_NOT_ELIGIBLE.value)
    assert fx.read_case(api, context["case"]["id"])["status"] == "REPORT_DRAFTED"


def test_a_placement_site_must_be_active(api):
    """PRD §3.7: "Where a site is named it must be `ACTIVE` and its
    `languages_supported` must cover the child's `primary_language_code`, or the
    determination is refused with `ERR_SITE_NOT_ELIGIBLE`."

    Design: Corner/validations/site_eligibility_covers_status_host_approval_and_language
    """
    context = _case_with_drafted_report(api)
    closed = fx.register_site(api, status="INACTIVE", languages_supported=["en"])

    refused = _determine_eligible(
        api, context["case"], setting="COMMUNITY_PRESCHOOL", community_site_id=closed["id"]
    )
    validate_error(refused, ApiErrorId.ERR_SITE_NOT_ELIGIBLE.value)


def test_an_active_language_capable_site_receives_the_placement(api):
    """PRD §3.7: "Where a site is named it must be `ACTIVE` and its
    `languages_supported` must cover the child's `primary_language_code`, or the
    determination is refused with `ERR_SITE_NOT_ELIGIBLE`."
    PRD §3.7: "A successful determination moves the case to
    `ELIGIBILITY_DETERMINED`"

    Design: Corner/validations/site_eligibility_covers_status_host_approval_and_language
    """
    context = _case_with_drafted_report(api)
    site = fx.register_site(api)

    plan = validate_success(
        _determine_eligible(
            api, context["case"], setting="COMMUNITY_PRESCHOOL", community_site_id=site["id"]
        ),
        201,
    )
    assert plan["setting"] == "COMMUNITY_PRESCHOOL"
    assert plan["community_site_id"] == site["id"]
    assert plan["status"] == "DRAFT"
    assert fx.read_case(api, context["case"]["id"])["status"] == "ELIGIBILITY_DETERMINED"


# ------------------------------------------- rung 26 one live assessment per domain
def test_a_second_live_assessment_of_the_same_domain_is_refused(api):
    """PRD §3.5: "Then the case may not already hold a `SCHEDULED` or `COMPLETED`
    assessment of the same `domain`, or the request is refused with
    `ERR_DUPLICATE_DOMAIN_ASSESSMENT`"

    Design: Corner/validations/duplicate_domain_is_blocked_until_the_first_is_invalidated
    """
    context = fx.setup_case(api)
    slp = fx.register_provider(api, discipline="SLP")
    first = fx.schedule_assessment(
        api,
        context["case"]["id"],
        slp["id"],
        domain="COMMUNICATION",
        window_start_utc="2026-08-05T09:00:00Z",
    )
    assert first["status"] == "SCHEDULED"

    # A window two hours later cannot collide with the first, so the duplicate-domain
    # rung is the only one this request can reach.
    refused = _schedule(
        api,
        context["case"]["id"],
        slp["id"],
        domain="COMMUNICATION",
        window_start_utc="2026-08-05T11:00:00Z",
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_DOMAIN_ASSESSMENT.value)
    assert len(fx.assessments_for_case(api, context["case"]["id"])) == 1


def test_a_completed_assessment_still_blocks_its_domain(api):
    """PRD §3.5: "Then the case may not already hold a `SCHEDULED` or `COMPLETED`
    assessment of the same `domain`, or the request is refused with
    `ERR_DUPLICATE_DOMAIN_ASSESSMENT`"

    Design: Corner/validations/duplicate_domain_is_blocked_until_the_first_is_invalidated
    """
    context = fx.setup_case(api)
    slp = fx.register_provider(api, discipline="SLP")
    first = fx.schedule_assessment(
        api,
        context["case"]["id"],
        slp["id"],
        domain="COMMUNICATION",
        window_start_utc="2026-08-05T09:00:00Z",
    )
    completed = fx.complete_assessment(api, first["id"], slp["id"], 22)
    assert completed["status"] == "COMPLETED"

    refused = _schedule(
        api,
        context["case"]["id"],
        slp["id"],
        domain="COMMUNICATION",
        window_start_utc="2026-08-05T11:00:00Z",
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_DOMAIN_ASSESSMENT.value)


def test_an_invalidated_assessment_releases_its_domain(api):
    """PRD §3.5: "assessments that have been `INVALIDATED` do not block, which is
    exactly how a domain is re-assessed after a spoiled administration."

    Design: Corner/validations/duplicate_domain_is_blocked_until_the_first_is_invalidated
    """
    context = fx.setup_case(api)
    slp = fx.register_provider(api, discipline="SLP")
    first = fx.schedule_assessment(
        api,
        context["case"]["id"],
        slp["id"],
        domain="COMMUNICATION",
        window_start_utc="2026-08-05T09:00:00Z",
    )
    invalidated = fx.invalidate_assessment(api, first["id"], slp["id"])
    assert invalidated["status"] == "INVALIDATED"

    replacement = fx.schedule_assessment(
        api,
        context["case"]["id"],
        slp["id"],
        domain="COMMUNICATION",
        window_start_utc="2026-08-05T11:00:00Z",
    )
    assert replacement["status"] == "SCHEDULED"
    assert replacement["domain"] == "COMMUNICATION"
    assert replacement["id"] != first["id"]


# --------------------- rung 28 with carve-out A of rung 11 on notice re-issuance
def test_a_pending_notice_blocks_a_reissue(api):
    """PRD §3.4: "A referral that **already** holds an evaluation-consent record
    whose `decision` is `PENDING` or `GRANTED` is refused with
    `ERR_CONSENT_ALREADY_REQUESTED`, and this refusal pre-empts the generic
    own-state rule — this is carve-out A of §2.5 rung 11. The practical effect is
    that re-issuing a notice while the family is still deciding reports
    `ERR_CONSENT_ALREADY_REQUESTED`"

    Design: Corner/validations/a_pending_or_granted_notice_blocks_a_reissue_while_a_refusal_falls_through
    """
    referral = fx.create_referral(api)
    notice = fx.issue_evaluation_notice(api, referral["id"])
    assert notice["decision"] == "PENDING"

    refused = api.issue_consent_request(
        referral["id"], f.consent_request_payload(notice_delivery_method="EMAIL"), COORDINATOR
    )
    validate_error(refused, ApiErrorId.ERR_CONSENT_ALREADY_REQUESTED.value)

    after = fx.read_referral(api, referral["id"])
    assert after["intake_status"] == "CONSENT_PENDING"
    assert after["consent_status"] == "REQUESTED"
    assert fx.read_consent(api, notice["id"])["decision"] == "PENDING"
    assert len(fx.consent_records_for_referral(api, referral["id"])) == 1


def test_a_granted_notice_also_blocks_a_reissue(api):
    """PRD §3.4: "and so does asking again after consent has already been granted"
    PRD §2.5 rung 28: "No second evaluation-consent request while one is still
    live, else `ERR_CONSENT_ALREADY_REQUESTED` (409), guarding consent-request
    issuance."

    Design: Corner/validations/a_pending_or_granted_notice_blocks_a_reissue_while_a_refusal_falls_through
    """
    granted = fx.setup_referral_with_granted_consent(api)
    assert granted["referral"]["intake_status"] == "EVALUATION_AUTHORIZED"
    assert granted["referral"]["consent_status"] == "GRANTED"

    refused = api.issue_consent_request(
        granted["referral"]["id"], f.consent_request_payload(), COORDINATOR
    )
    validate_error(refused, ApiErrorId.ERR_CONSENT_ALREADY_REQUESTED.value)
    assert len(fx.consent_records_for_referral(api, granted["referral"]["id"])) == 1


def test_a_refused_notice_falls_through_to_the_referrals_own_state(api):
    """PRD §3.4: "whereas a referral whose only record is `REFUSED` or `REVOKED`
    holds no blocking record at all, falls through to the own-state rule, and
    reports `ERR_INVALID_REFERRAL_STATE` for its `DECLINED`, `WITHDRAWN` or
    `SUPERSEDED` intake state."

    Design: Corner/validations/a_pending_or_granted_notice_blocks_a_reissue_while_a_refusal_falls_through
    """
    referral = fx.create_referral(api)
    notice = fx.issue_evaluation_notice(api, referral["id"])
    fx.decide_consent(api, notice["id"], "REFUSED")

    declined = fx.read_referral(api, referral["id"])
    assert declined["intake_status"] == "DECLINED"
    assert declined["consent_status"] == "REFUSED"

    refused = api.issue_consent_request(referral["id"], f.consent_request_payload(), COORDINATOR)
    validate_error(refused, ApiErrorId.ERR_INVALID_REFERRAL_STATE.value)


# ----------------------------------------- rung 29 revocability of a consent record
def test_a_granted_service_consent_cannot_be_revoked(api):
    """PRD §3.4: "`GRANTED → REVOKED` is permitted only on an evaluation-consent
    record — attempting it on a service-consent record is
    `ERR_CONSENT_NOT_REVOCABLE`"

    Design: Corner/validations/only_a_granted_evaluation_consent_is_revocable
    """
    context = fx.setup_active_plan(api)
    service_consent = context["service_consent"]
    assert service_consent["kind"] == "SERVICE_CONSENT"
    assert service_consent["decision"] == "GRANTED"

    refused = api.record_consent_decision(
        service_consent["id"], f.consent_decision_payload("REVOKED"), COORDINATOR
    )
    validate_error(refused, ApiErrorId.ERR_CONSENT_NOT_REVOCABLE.value)

    assert fx.read_consent(api, service_consent["id"])["decision"] == "GRANTED"
    assert fx.read_plan(api, context["plan"]["id"])["status"] == "ACTIVE", (
        "withdrawal of services runs through the plan's own lifecycle, not the consent"
    )


def test_revoking_a_pending_evaluation_consent_is_a_state_error(api):
    """PRD §2.5 rung 11: "the target row is in a state from which the requested
    transition is declared, else the entity's own 409 state code"
    PRD §3.4: "A decision on a record whose current `decision` does not permit it —
    granting an already-granted record, or any decision on a record that is
    `REFUSED` or `REVOKED` — is `ERR_INVALID_CONSENT_STATE`."
    PRD §3.4 declares only `PENDING → GRANTED`, `PENDING → REFUSED` and
    `GRANTED → REVOKED`, so revocation from `PENDING` is undeclared and rung 11 —
    which sits above rung 29 — owns the refusal.

    Design: Corner/validations/only_a_granted_evaluation_consent_is_revocable
    """
    referral = fx.create_referral(api)
    notice = fx.issue_evaluation_notice(api, referral["id"])

    refused = api.record_consent_decision(
        notice["id"], f.consent_decision_payload("REVOKED"), COORDINATOR
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_CONSENT_STATE.value)
    assert fx.read_consent(api, notice["id"])["decision"] == "PENDING"


def test_a_granted_evaluation_consent_is_revocable(api):
    """PRD §3.4: "`GRANTED → REVOKED` is permitted only on an evaluation-consent
    record ... and moves `intake_status` `EVALUATION_AUTHORIZED → WITHDRAWN` and
    `consent_status` `GRANTED → REVOKED`, while the already-pinned
    `evaluation_due_date` is retained as the historical deadline rather than
    cleared."

    Design: Corner/validations/only_a_granted_evaluation_consent_is_revocable
    """
    granted = fx.setup_referral_with_granted_consent(api)
    pinned_due_date = granted["referral"]["evaluation_due_date"]
    assert pinned_due_date is not None

    revoked = fx.decide_consent(api, granted["consent"]["id"], "REVOKED")
    assert revoked["decision"] == "REVOKED"
    assert revoked["kind"] == "EVALUATION_CONSENT"

    after = fx.read_referral(api, granted["referral"]["id"])
    assert after["intake_status"] == "WITHDRAWN"
    assert after["consent_status"] == "REVOKED"
    assert after["evaluation_due_date"] == pinned_due_date


# ------------------------ rung 30 the four settings and their shape requirements
def test_a_community_preschool_plan_must_name_a_site(api):
    """PRD §3.7: "`community_site_id` may be supplied only when the `setting` is
    `COMMUNITY_PRESCHOOL` — a plan naming a site under any other setting, or naming
    `COMMUNITY_PRESCHOOL` with no site, is refused with
    `ERR_PLAN_SETTING_REQUIREMENTS_UNMET`."

    Design: Corner/validations/each_service_setting_carries_its_own_shape_requirement
    """
    context = _case_with_drafted_report(api)

    refused = _determine_eligible(api, context["case"], setting="COMMUNITY_PRESCHOOL")
    validate_error(refused, ApiErrorId.ERR_PLAN_SETTING_REQUIREMENTS_UNMET.value)
    assert fx.read_case(api, context["case"]["id"])["status"] == "REPORT_DRAFTED"


def test_a_home_based_plan_may_not_name_a_site(api):
    """PRD §3.7: "`community_site_id` may be supplied only when the `setting` is
    `COMMUNITY_PRESCHOOL` — a plan naming a site under any other setting, or naming
    `COMMUNITY_PRESCHOOL` with no site, is refused with
    `ERR_PLAN_SETTING_REQUIREMENTS_UNMET`."

    Design: Corner/validations/each_service_setting_carries_its_own_shape_requirement
    """
    context = _case_with_drafted_report(api)
    # An entirely eligible site: ACTIVE and covering the child's language, so only
    # the setting-shape rule can fire.
    site = fx.register_site(api)

    refused = _determine_eligible(
        api, context["case"], setting="HOME_BASED", community_site_id=site["id"]
    )
    validate_error(refused, ApiErrorId.ERR_PLAN_SETTING_REQUIREMENTS_UNMET.value)


def test_an_itinerant_only_plan_refuses_a_push_in_line(api):
    """PRD §3.8: "Where the plan's `setting` is `ITINERANT_ONLY`, every line on the
    plan must have a `delivery_model` of `DIRECT` or `CONSULT` — a `PUSH_IN` line is
    incompatible with a purely itinerant model — and no single line may exceed 300
    `weekly_minutes`; a violation of either is refused with
    `ERR_PLAN_SETTING_REQUIREMENTS_UNMET`."

    Design: Corner/validations/each_service_setting_carries_its_own_shape_requirement
    """
    context = fx.setup_draft_plan(api, setting="ITINERANT_ONLY")

    refused = api.add_service_line(
        context["plan"]["id"],
        f.service_line_payload(discipline="SLP", weekly_minutes=100, delivery_model="PUSH_IN"),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_PLAN_SETTING_REQUIREMENTS_UNMET.value)
    assert fx.lines_for_plan(api, context["plan"]["id"]) == []

    consult = fx.add_line(
        api, context["plan"]["id"], discipline="SLP", weekly_minutes=100, delivery_model="CONSULT"
    )
    assert consult["delivery_model"] == "CONSULT"
    assert consult["status"] == "PROPOSED"


def test_an_itinerant_only_line_may_not_exceed_three_hundred_minutes(api):
    """PRD §3.8: "and no single line may exceed 300 `weekly_minutes`; a violation of
    either is refused with `ERR_PLAN_SETTING_REQUIREMENTS_UNMET`."
    PRD §3.8: "Adding a line recomputes the parent plan's `assigned_weekly_minutes`,
    which is the sum of `weekly_minutes` across the plan's lines whose `status` is
    `PROPOSED`, `STAFFED` or `UNSTAFFED`"

    Design: Corner/validations/each_service_setting_carries_its_own_shape_requirement
    """
    context = fx.setup_draft_plan(api, setting="ITINERANT_ONLY")

    refused = api.add_service_line(
        context["plan"]["id"],
        f.service_line_payload(discipline="SLP", weekly_minutes=305, delivery_model="DIRECT"),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_PLAN_SETTING_REQUIREMENTS_UNMET.value)

    # 300 is the ceiling itself, which the rule allows.
    at_ceiling = fx.add_line(
        api, context["plan"]["id"], discipline="SLP", weekly_minutes=300, delivery_model="DIRECT"
    )
    assert at_ceiling["weekly_minutes"] == 300
    assert fx.read_plan(api, context["plan"]["id"])["assigned_weekly_minutes"] == 300


def test_a_plan_with_no_staffed_line_may_not_be_submitted(api):
    """PRD §3.9: "Common to all four: at least one of the plan's service lines must
    stand `STAFFED`, and a plan submitted with no staffed line at all is refused
    with `ERR_PLAN_SETTING_REQUIREMENTS_UNMET`."

    Design: Corner/validations/each_service_setting_carries_its_own_shape_requirement
    """
    context = fx.setup_draft_plan(api, setting="ITINERANT_ONLY")
    proposed = fx.add_line(
        api, context["plan"]["id"], discipline="SLP", weekly_minutes=100, delivery_model="DIRECT"
    )
    assert proposed["status"] == "PROPOSED"

    refused = api.submit_plan_for_consent(
        context["plan"]["id"], f.consent_submission_payload(), PLACEMENT
    )
    validate_error(refused, ApiErrorId.ERR_PLAN_SETTING_REQUIREMENTS_UNMET.value)
    assert fx.read_plan(api, context["plan"]["id"])["status"] == "DRAFT"


def test_a_district_classroom_plan_needs_a_staffed_ecse_teacher_line(api):
    """PRD §3.9: "A `DISTRICT_ECSE_CLASSROOM` plan must have no `community_site_id`
    and must have at least one `STAFFED` line whose `discipline` is `ECSE_TEACHER`;
    either failure is `ERR_PLAN_SETTING_REQUIREMENTS_UNMET`."
    PRD §3.9: "The plan moves `DRAFT → PENDING_PARENT_CONSENT`"

    Design: Corner/validations/each_service_setting_carries_its_own_shape_requirement
    """
    context = fx.setup_staffed_draft_plan(
        api, setting="DISTRICT_ECSE_CLASSROOM", discipline="SLP", weekly_minutes=100
    )
    assert context["line"]["status"] == "STAFFED"

    refused = api.submit_plan_for_consent(
        context["plan"]["id"], f.consent_submission_payload(), PLACEMENT
    )
    validate_error(refused, ApiErrorId.ERR_PLAN_SETTING_REQUIREMENTS_UNMET.value)

    teacher = fx.register_provider(api, discipline="ECSE_TEACHER")
    classroom_line = fx.add_line(
        api,
        context["plan"]["id"],
        discipline="ECSE_TEACHER",
        weekly_minutes=200,
        delivery_model="DIRECT",
    )
    fx.staff_line(api, classroom_line["id"], teacher["id"])

    validate_success(
        api.submit_plan_for_consent(
            context["plan"]["id"], f.consent_submission_payload(), PLACEMENT
        ),
        201,
    )
    assert fx.read_plan(api, context["plan"]["id"])["status"] == "PENDING_PARENT_CONSENT"


# ------------------------------------- rung 31 justifying a contradicted decision
def test_a_not_eligible_decision_against_an_eligible_recommendation_needs_a_justification(api):
    """PRD §3.7: "whenever the decision contradicts the team's own
    `composite_eligibility_recommendation` — a decision of `ELIGIBLE` against a
    recommendation of `NOT_ELIGIBLE_RECOMMENDED`, or a decision of `NOT_ELIGIBLE`
    against a recommendation of `ELIGIBLE_RECOMMENDED` — a non-empty
    `override_justification` is required, and its absence is refused with
    `ERR_ELIGIBILITY_OVERRIDE_JUSTIFICATION_REQUIRED`."

    Design: Corner/validations/contradicting_the_recommendation_demands_a_written_justification
    """
    context = _case_with_drafted_report(api)
    assert context["case"]["composite_eligibility_recommendation"] == "ELIGIBLE_RECOMMENDED"

    refused = api.determine_eligibility(
        context["case"]["id"],
        f.not_eligible_determination_payload(context["case"]["version"]),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_ELIGIBILITY_OVERRIDE_JUSTIFICATION_REQUIRED.value)
    assert fx.read_case(api, context["case"]["id"])["status"] == "REPORT_DRAFTED"


def test_the_justified_not_eligible_determination_closes_the_plan(api):
    """PRD §3.7: "When the decision was `NOT_ELIGIBLE` the new plan is written at
    `DRAFT` and immediately moved by the system to `CLOSED_NOT_ELIGIBLE`,
    incrementing its `version`, and the child's derived `status` becomes
    `NOT_ELIGIBLE`."
    PRD §3.7: "When `eligibility_decision` is `NOT_ELIGIBLE`, both `setting` and
    `disability_category` must be absent."

    Design: Corner/validations/contradicting_the_recommendation_demands_a_written_justification
    """
    context = _case_with_drafted_report(api)

    plan = validate_success(
        api.determine_eligibility(
            context["case"]["id"],
            f.not_eligible_determination_payload(
                context["case"]["version"],
                override_justification="Team read the delays as transient after a recent move.",
            ),
            PLACEMENT,
        ),
        201,
    )
    assert plan["eligibility_decision"] == "NOT_ELIGIBLE"
    assert plan["status"] == "CLOSED_NOT_ELIGIBLE"
    assert_fields_absent(plan, "setting", "disability_category")
    assert fx.read_case(api, context["case"]["id"])["status"] == "ELIGIBILITY_DETERMINED"
    assert fx.read_child(api, context["child"]["id"])["status"] == "NOT_ELIGIBLE"


def test_an_eligible_decision_against_a_not_eligible_recommendation_needs_a_justification(api):
    """PRD §3.7: "a decision of `ELIGIBLE` against a recommendation of
    `NOT_ELIGIBLE_RECOMMENDED` ... a non-empty `override_justification` is required,
    and its absence is refused with
    `ERR_ELIGIBILITY_OVERRIDE_JUSTIFICATION_REQUIRED`."

    Design: Corner/validations/contradicting_the_recommendation_demands_a_written_justification
    """
    context = _case_with_drafted_report(api, age_equivalents=fx.NOT_ELIGIBLE_AGE_EQUIVALENTS)
    assert context["case"]["composite_eligibility_recommendation"] == "NOT_ELIGIBLE_RECOMMENDED"

    refused = _determine_eligible(api, context["case"], setting="ITINERANT_ONLY")
    validate_error(refused, ApiErrorId.ERR_ELIGIBILITY_OVERRIDE_JUSTIFICATION_REQUIRED.value)

    plan = validate_success(
        _determine_eligible(
            api,
            context["case"],
            setting="ITINERANT_ONLY",
            override_justification="Clinical judgement of the team overrides the norm-referenced figures.",
        ),
        201,
    )
    assert plan["eligibility_decision"] == "ELIGIBLE"
    assert plan["status"] == "DRAFT"


def test_a_determination_that_agrees_with_the_recommendation_needs_no_justification(api):
    """PRD §3.7: "whenever the decision contradicts the team's own
    `composite_eligibility_recommendation` ... a non-empty `override_justification`
    is required"
    PRD §3.7: "When the decision was `ELIGIBLE` the plan stays at `DRAFT`, waiting
    for service lines."

    Design: Corner/validations/contradicting_the_recommendation_demands_a_written_justification
    """
    context = _case_with_drafted_report(api)
    assert context["case"]["composite_eligibility_recommendation"] == "ELIGIBLE_RECOMMENDED"

    plan = validate_success(
        _determine_eligible(api, context["case"], setting="ITINERANT_ONLY"), 201
    )
    assert plan["status"] == "DRAFT"
    assert plan["assigned_weekly_minutes"] == 0


# ---------------------------------------- rung 36 the chair's evaluation ceiling
def test_a_chair_at_its_evaluation_ceiling_takes_no_further_case(api):
    """PRD §3.5: "a chair whose `active_evaluation_count` has **already reached**
    its `max_evaluation_caseload` before the new case is written is refused with
    `ERR_EVALUATION_CASELOAD_EXCEEDED`, so a chair sitting at exactly the ceiling
    takes no further case."
    PRD §3.5: "From that count `evaluation_intake_posture` follows: it reads
    `AT_CAPACITY` when the count has reached or passed `max_evaluation_caseload`,
    and `OPEN` otherwise."

    Design: Corner/validations/chair_caseload_cap_refuses_the_next_case_until_one_is_cancelled
    """
    chair = fx.register_chair(api, max_evaluation_caseload=1)
    first = fx.setup_referral_with_granted_consent(api)
    fx.open_case(api, first["referral"]["id"], chair["id"])

    second = fx.setup_referral_with_granted_consent(api)
    refused = _open_case(api, second["referral"]["id"], chair["id"])
    validate_error(refused, ApiErrorId.ERR_EVALUATION_CASELOAD_EXCEEDED.value)

    caseload = fx.read_caseload(api, chair["id"])
    assert caseload["active_evaluation_count"] == 1
    assert caseload["max_evaluation_caseload"] == 1
    assert caseload["evaluation_intake_posture"] == "AT_CAPACITY"


def test_cancelling_a_case_frees_the_chairs_next_slot(api):
    """PRD §3.5: "Cases at `ELIGIBILITY_DETERMINED` or `CANCELLED` are excluded,
    which is precisely why cancelling a case frees capacity."
    PRD §3.4: "it starts the deepest cascade in the system: the referral's
    evaluation case, if its status is anything other than `ELIGIBILITY_DETERMINED`
    or `CANCELLED`, is cancelled"

    Design: Corner/validations/chair_caseload_cap_refuses_the_next_case_until_one_is_cancelled
    """
    chair = fx.register_chair(api, max_evaluation_caseload=1)
    first = fx.setup_referral_with_granted_consent(api)
    first_case = fx.open_case(api, first["referral"]["id"], chair["id"])

    second = fx.setup_referral_with_granted_consent(api)
    validate_error(
        _open_case(api, second["referral"]["id"], chair["id"]),
        ApiErrorId.ERR_EVALUATION_CASELOAD_EXCEEDED.value,
    )

    fx.decide_consent(api, first["consent"]["id"], "REVOKED")
    assert fx.read_case(api, first_case["id"])["status"] == "CANCELLED"

    second_case = validate_success(_open_case(api, second["referral"]["id"], chair["id"]), 201)
    assert second_case["status"] == "PLANNED"
    assert second_case["chair_provider_id"] == chair["id"]

    caseload = fx.read_caseload(api, chair["id"])
    assert caseload["active_evaluation_count"] == 1
    assert caseload["evaluation_intake_posture"] == "AT_CAPACITY"


# --------------------------- rung 24 conference lead time vs rung 32 action order
def test_sending_the_packet_before_the_conference_violates_the_sequence(api):
    """PRD §3.9: "the three must be taken in that order:
    `kindergarten_transition_status` must read `NOT_STARTED` for
    `SCHEDULE_CONFERENCE`, `CONFERENCE_SCHEDULED` for `SEND_PACKET`, and
    `PACKET_SENT` for `EXIT`, with any out-of-order attempt refused as
    `ERR_TRANSITION_SEQUENCE_VIOLATION`."

    Design: Corner/validations/conference_lead_time_outranks_the_transition_sequence
    """
    context = fx.setup_active_plan(api)
    assert context["plan"]["kindergarten_transition_status"] == "NOT_STARTED"

    refused = api.kindergarten_transition(
        context["plan"]["id"],
        f.transition_payload("SEND_PACKET", receiving_school_code="KS-14"),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_TRANSITION_SEQUENCE_VIOLATION.value)
    assert fx.read_plan(api, context["plan"]["id"])["kindergarten_transition_status"] == (
        "NOT_STARTED"
    )


def test_a_conference_eighty_nine_days_before_kindergarten_is_too_late(api):
    """PRD §3.9: "The date is constrained twice: the number of whole days from
    `transition_conference_date` to the child's `kindergarten_eligibility_date` must
    be at least 90, giving the receiving school a full quarter of notice, and the
    date must fall strictly after the logical clock's current date. Either failure
    is refused with `ERR_TRANSITION_CONFERENCE_TOO_LATE`."

    Design: Corner/validations/conference_lead_time_outranks_the_transition_sequence
    """
    context = fx.setup_active_plan(api)
    kindergarten = context["child"]["kindergarten_eligibility_date"]

    refused = api.kindergarten_transition(
        context["plan"]["id"],
        f.transition_payload(
            "SCHEDULE_CONFERENCE", transition_conference_date=plus_days_date(kindergarten, -89)
        ),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_TRANSITION_CONFERENCE_TOO_LATE.value)


def test_a_conference_date_no_later_than_today_is_too_late(api):
    """PRD §3.9: "and the date must fall strictly after the logical clock's current
    date. Either failure is refused with `ERR_TRANSITION_CONFERENCE_TOO_LATE`."

    Design: Corner/validations/conference_lead_time_outranks_the_transition_sequence
    """
    context = fx.setup_active_plan(api)
    yesterday = plus_days_date(date_part(INITIAL_LOGICAL_CLOCK), -1)

    # Yesterday clears the ninety-day notice requirement comfortably, so only the
    # strictly-after-today rule can refuse it.
    refused = api.kindergarten_transition(
        context["plan"]["id"],
        f.transition_payload("SCHEDULE_CONFERENCE", transition_conference_date=yesterday),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_TRANSITION_CONFERENCE_TOO_LATE.value)


def test_a_conference_exactly_ninety_days_out_is_accepted(api):
    """PRD §3.9: "the number of whole days from `transition_conference_date` to the
    child's `kindergarten_eligibility_date` must be at least 90"
    PRD §3.9: "Scheduling the conference stores the supplied
    `transition_conference_date` and advances `kindergarten_transition_status` from
    `NOT_STARTED` to `CONFERENCE_SCHEDULED` while the plan's own `status` stays
    `ACTIVE`"

    Design: Corner/validations/conference_lead_time_outranks_the_transition_sequence
    """
    context = fx.setup_active_plan(api)
    kindergarten = context["child"]["kindergarten_eligibility_date"]
    exactly_ninety = plus_days_date(kindergarten, -90)

    updated = fx.transition(
        api,
        context["plan"]["id"],
        "SCHEDULE_CONFERENCE",
        transition_conference_date=exactly_ninety,
    )
    assert updated["kindergarten_transition_status"] == "CONFERENCE_SCHEDULED"
    assert updated["transition_conference_date"] == exactly_ninety
    assert updated["status"] == "ACTIVE"
    assert updated["version"] == context["plan"]["version"] + 1


def test_the_conference_lead_time_outranks_the_transition_sequence(api):
    """PRD §2.5 rung 24: "Kindergarten transition conference lead time, else
    `ERR_TRANSITION_CONFERENCE_TOO_LATE` (422), guarding the transition endpoint and
    applying only to the conference-scheduling action."
    PRD §2.5 rung 32: "Kindergarten transition action ordering, else
    `ERR_TRANSITION_SEQUENCE_VIOLATION` (409), guarding the transition endpoint."
    PRD §2.5: "Validation is a single ordered ladder; the **first** rule that a
    request violates determines the response, and no later rule is consulted."

    Design: Corner/validations/conference_lead_time_outranks_the_transition_sequence
    """
    context = fx.setup_active_plan(api)
    kindergarten = context["child"]["kindergarten_eligibility_date"]
    fx.transition(
        api,
        context["plan"]["id"],
        "SCHEDULE_CONFERENCE",
        transition_conference_date=plus_days_date(kindergarten, -90),
    )

    # Out of order alone: EXIT needs PACKET_SENT.
    out_of_order = api.kindergarten_transition(
        context["plan"]["id"], f.transition_payload("EXIT"), PLACEMENT
    )
    validate_error(out_of_order, ApiErrorId.ERR_TRANSITION_SEQUENCE_VIOLATION.value)

    # Out of order *and* too late: the conference has already been scheduled and the
    # new date leaves only eighty-nine days of notice. The lead-time rung is higher.
    both_broken = api.kindergarten_transition(
        context["plan"]["id"],
        f.transition_payload(
            "SCHEDULE_CONFERENCE", transition_conference_date=plus_days_date(kindergarten, -89)
        ),
        PLACEMENT,
    )
    validate_error(both_broken, ApiErrorId.ERR_TRANSITION_CONFERENCE_TOO_LATE.value)


def test_the_packet_follows_the_scheduled_conference(api):
    """PRD §3.9: "Sending the packet stores the supplied `receiving_school_code` —
    which must be supplied — and advances `kindergarten_transition_status` from
    `CONFERENCE_SCHEDULED` to `PACKET_SENT`, again as a self-loop on an `ACTIVE`
    plan with a `version` increment."

    Design: Corner/validations/conference_lead_time_outranks_the_transition_sequence
    """
    context = fx.setup_active_plan(api)
    kindergarten = context["child"]["kindergarten_eligibility_date"]
    scheduled = fx.transition(
        api,
        context["plan"]["id"],
        "SCHEDULE_CONFERENCE",
        transition_conference_date=plus_days_date(kindergarten, -90),
    )

    sent = fx.transition(
        api, context["plan"]["id"], "SEND_PACKET", receiving_school_code="KS-14"
    )
    assert sent["kindergarten_transition_status"] == "PACKET_SENT"
    assert sent["receiving_school_code"] == "KS-14"
    assert sent["status"] == "ACTIVE"
    assert sent["version"] == scheduled["version"] + 1
