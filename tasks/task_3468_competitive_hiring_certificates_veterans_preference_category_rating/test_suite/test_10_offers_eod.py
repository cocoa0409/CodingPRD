"""Offers: response window (temporal vs state), suitability/clearance
sequencing and segregation, the EOD date rules, and the direct-hire
UNRANKED bypass end to end.
"""
from test_helpers import (
    HR, NON_EXISTENT_UUID, SO, TEST_USERS, ApiErrorId,
    accept_offer, api_client, create_assessment_payload, get_success_data,
    issue_certificate, list_entries, make_applicant_headers,
    make_security_adjudicator_headers, make_sme_headers,
    make_suitability_reviewer_headers, record_clearance,
    record_security_clearance_payload, record_suitability,
    record_suitability_review_payload, respond_to_offer_payload,
    schedule_eod_payload, select_entry, set_clock, setup_accepted_offer,
    setup_offer_with_favorable_suitability, setup_open_announcement,
    setup_qualified_application, setup_selected_offer, validate_error,
    validate_paginated, validate_success,
)


def test_offer_respond_state_beats_temporal(api):
    """PRD §2.7: "And on offer response the temporal check runs before the
    state check: a still-`TENTATIVE` offer whose response deadline has been
    reached is rejected with `ERR_OFFER_RESPONSE_EXPIRED` (and flips to
    `OFFER_EXPIRED` with its cascade), whereas an offer in any state other
    than `TENTATIVE` fails the state check with `ERR_OFFER_NOT_ACTIONABLE`
    regardless of what the clock says."

    Design: Difficulty/priority_pair_validation_conflict/offer_respond_state_beats_temporal
    """
    ctx = setup_selected_offer()  # TENTATIVE at 2026-09-16, due 2026-09-21
    offer = ctx["offer"]
    assert offer["response_due_at"] == "2026-09-21T00:00:00Z"
    applicant = next(a for a, ap in zip(ctx["applicants"], ctx["applications"])
                     if ap["id"] == ctx["entry"]["application_id"])

    set_clock("2026-09-17T00:00:00Z")
    declined = validate_success(
        api_client.respond_to_offer(
            offer["id"], respond_to_offer_payload("DECLINE"),
            make_applicant_headers(applicant["id"])),
        200)
    assert declined["status"] == "DECLINED"

    # Past the response deadline AND no longer TENTATIVE: the state rule wins.
    set_clock("2026-09-22T00:00:00Z")
    resp = api_client.respond_to_offer(
        offer["id"], respond_to_offer_payload("ACCEPT"),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_ACTIONABLE)

    reread = get_success_data(api_client.get_offer(offer["id"], HR))
    assert reread["status"] == "DECLINED", "the rejected response must not mutate the offer"


def test_respond_after_due_on_tentative_offer(api):
    """PRD §3.8: "a `TENTATIVE` offer whose deadline has been reached is
    rejected with `ERR_OFFER_RESPONSE_EXPIRED` (HTTP 409) and flips to
    `OFFER_EXPIRED` on the spot, while an offer already past `TENTATIVE` draws
    `ERR_OFFER_NOT_ACTIONABLE` (HTTP 409) whatever the clock says. Decline and
    expiry share a cascade: the application and the certificate entry both move
    to `NOT_SELECTED`, and `remaining_vacancies` climbs by one."

    Design: Corner/validations/respond_after_due_on_tentative_offer
    """
    ctx = setup_selected_offer()  # offered 2026-09-16, due 2026-09-21
    offer, entry = ctx["offer"], ctx["entry"]

    set_clock("2026-09-21T00:00:00Z")  # exactly response_due_at
    applicant = next(a for a, ap in zip(ctx["applicants"], ctx["applications"])
                     if ap["id"] == entry["application_id"])
    resp = api_client.respond_to_offer(
        offer["id"], respond_to_offer_payload("ACCEPT"),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_RESPONSE_EXPIRED)

    reread_offer = get_success_data(api_client.get_offer(offer["id"], HR))
    assert reread_offer["status"] == "OFFER_EXPIRED"
    reread_entry = get_success_data(api_client.get_entry(entry["id"], HR))
    assert reread_entry["status"] == "NOT_SELECTED"
    application = get_success_data(api_client.get_application(entry["application_id"], HR))
    assert application["status"] == "NOT_SELECTED"
    announcement = get_success_data(
        api_client.get_announcement(ctx["announcement"]["id"], HR))
    assert announcement["remaining_vacancies"] == 1


def test_unresponded_offer_expires_at_due_instant(api):
    """PRD §3.8: "The same expiry transition also fires lazily whenever an
    offer is read or an offer-scoped action is attempted at or past
    `response_due_at`." and "creates the offer in `TENTATIVE` with
    `tentative_offered_at` stamped from the logical clock and `response_due_at`
    set five days later."

    Design: Corner/state_machines/unresponded_offer_expires_at_due_instant
    """
    ctx = setup_selected_offer()  # selected at 2026-09-16
    offer, entry = ctx["offer"], ctx["entry"]
    assert offer["tentative_offered_at"] == "2026-09-16T00:00:00Z"
    assert offer["response_due_at"] == "2026-09-21T00:00:00Z"  # + 5 days

    set_clock("2026-09-21T00:00:00Z")  # exactly response_due_at: >= boundary
    reread_offer = get_success_data(api_client.get_offer(offer["id"], HR))
    assert reread_offer["status"] == "OFFER_EXPIRED"

    reread_entry = get_success_data(api_client.get_entry(entry["id"], HR))
    assert reread_entry["status"] == "NOT_SELECTED"
    application = get_success_data(api_client.get_application(entry["application_id"], HR))
    assert application["status"] == "NOT_SELECTED"
    announcement = get_success_data(
        api_client.get_announcement(ctx["announcement"]["id"], HR))
    assert announcement["remaining_vacancies"] == 1


def test_second_suitability_review_rejected(api):
    """PRD §3.9: "a second review on the same offer is
    `ERR_REVIEW_ALREADY_RECORDED` (HTTP 409)".

    Design: Corner/validations/second_suitability_review_rejected
    """
    ctx = setup_offer_with_favorable_suitability()  # FAVORABLE review by suit-1
    offer = ctx["offer"]
    assert offer["status"] == "ACCEPTED"

    resp = api_client.record_suitability_review(
        offer["id"],
        record_suitability_review_payload("UNFAVORABLE", notes="second opinion attempt"),
        make_suitability_reviewer_headers("suit-2"))
    validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_RECORDED)

    reread = get_success_data(api_client.get_offer(offer["id"], HR))
    assert reread["status"] == "ACCEPTED", "the rejected second review must not rescind the offer"


def test_clearance_segregation_beats_duplicate_record(api):
    """PRD §3.9: "Segregation of duties binds the pair in both directions: the
    adjudicator's `X-User-ID` must differ from the offer's
    `suitability_reviewer_id`, and symmetrically the suitability reviewer must
    differ from any prior clearance adjudicator on the same offer — a collision
    in either direction is `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."
    PRD §2.7: "then business-safety rules such as segregation of duties and the
    suitability-before-clearance sequence (6); then business constraints such
    as uniqueness, roster minima, and the selection gates (7)" — so the
    segregation failure outranks the one-clearance-per-offer rule ("admits no
    second clearance per offer (`ERR_REVIEW_ALREADY_RECORDED`)", §3.9) when a
    single request violates both.

    Design: Difficulty/priority_pair_validation_conflict/clearance_segregation_beats_duplicate_record
    """
    ctx = setup_accepted_offer(position_overrides={"sensitivity_level": "SECRET"})
    offer = ctx["offer"]
    record_suitability(offer["id"], "FAVORABLE", "suit-1")
    record_clearance(offer["id"], "FAVORABLE_FINAL", "sec-1")

    # Second clearance whose adjudicator equals the suitability reviewer:
    # violates segregation (priority 6) AND one-clearance-per-offer (7).
    resp = api_client.record_security_clearance(
        offer["id"],
        record_security_clearance_payload("FAVORABLE_INTERIM"),
        make_security_adjudicator_headers("suit-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    clearances, meta = validate_paginated(
        api_client.list_security_clearances(offer["id"], HR))
    assert meta["total_count"] == 1, "exactly one clearance may exist after the rejected attempt"
    assert len(clearances) == 1


def test_schedule_eod_requires_clearance_gate(api):
    """PRD §3.9: "the clearance gate scaled to the position's sensitivity —
    `NONE` needs no clearance record at all, `SECRET` accepts
    `FAVORABLE_INTERIM` or `FAVORABLE_FINAL`, and `TOP_SECRET` insists on
    `FAVORABLE_FINAL` alone, shortfalls drawing `ERR_CLEARANCE_INSUFFICIENT`
    (HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/schedule_eod_requires_clearance_gate
    """
    ctx = setup_offer_with_favorable_suitability(
        position_overrides={"sensitivity_level": "TOP_SECRET"})
    offer = ctx["offer"]
    assert offer["status"] == "ACCEPTED"

    # Favorable suitability alone is not sufficient on a TOP_SECRET position.
    resp = api_client.schedule_eod(
        offer["id"], schedule_eod_payload("2026-09-25T00:00:00Z"), SO)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_INSUFFICIENT)

    reread = get_success_data(api_client.get_offer(offer["id"], HR))
    assert reread["status"] == "ACCEPTED"

    record_clearance(offer["id"], "FAVORABLE_FINAL")
    scheduled = validate_success(
        api_client.schedule_eod(
            offer["id"], schedule_eod_payload("2026-09-25T00:00:00Z"), SO),
        200)
    assert scheduled["status"] == "EOD_SCHEDULED"
    assert scheduled["eod_date"] == "2026-09-25T00:00:00Z"


def test_eod_date_rules_and_competitive_happy_path(api):
    """PRD §3.9: "an `eod_date` not earlier than the current logical-clock
    date, else `ERR_EOD_DATE_INVALID` (HTTP 422)" and "performed once the
    logical clock has reached `eod_date`; earlier is again
    `ERR_EOD_DATE_INVALID`".
    PRD §3.9: "the `appointment_type` derives from the announcement's
    `hiring_authority` — `COMPETITIVE` for a competitive hire, `DIRECT_HIRE`
    for a direct hire, `SPECIAL_AUTHORITY` for every other authority — and the
    appointment's `eod_date` copies the offer's."

    Design: Corner/validations/eod_date_rules_and_competitive_happy_path
    """
    ctx = setup_accepted_offer()  # NONE sensitivity; ACCEPTED at 2026-09-17
    offer = ctx["offer"]

    # Suitability must exist before scheduling.
    resp = api_client.schedule_eod(
        offer["id"], schedule_eod_payload("2026-09-25T00:00:00Z"), SO)
    validate_error(resp, ApiErrorId.ERR_SUITABILITY_NOT_FAVORABLE)

    record_suitability(offer["id"], "FAVORABLE")

    # A past entry date is invalid (clock is 2026-09-17).
    resp = api_client.schedule_eod(
        offer["id"], schedule_eod_payload("2026-09-16T00:00:00Z"), SO)
    validate_error(resp, ApiErrorId.ERR_EOD_DATE_INVALID)

    scheduled = validate_success(
        api_client.schedule_eod(
            offer["id"], schedule_eod_payload("2026-09-25T00:00:00Z"), SO),
        200)
    assert scheduled["status"] == "EOD_SCHEDULED"
    assert scheduled["eod_date"] == "2026-09-25T00:00:00Z"

    # Confirmation before the entry date is invalid.
    set_clock("2026-09-24T00:00:00Z")
    resp = api_client.confirm_eod(offer["id"], HR)
    validate_error(resp, ApiErrorId.ERR_EOD_DATE_INVALID)

    set_clock("2026-09-25T00:00:00Z")
    final = validate_success(api_client.confirm_eod(offer["id"], HR), 200)
    assert final["status"] == "ENTERED_ON_DUTY"

    appointments, meta = validate_paginated(api_client.list_appointments(offer["id"], HR))
    assert meta["total_count"] == 1
    assert appointments[0]["appointment_type"] == "COMPETITIVE"
    assert appointments[0]["eod_date"] == "2026-09-25T00:00:00Z"

    application = get_success_data(
        api_client.get_application(ctx["entry"]["application_id"], HR))
    assert application["status"] == "HIRED"


def test_direct_hire_unranked_end_to_end_bypass(api):
    """PRD §3.5: "Creating an assessment for an application of an `UNRANKED`
    announcement is rejected with `ERR_ASSESSMENT_NOT_APPLICABLE` (HTTP 422)".
    PRD §3.6: "Under `UNRANKED` the roster is simply every `QUALIFIED`
    application, with no categories and no scores; the rule-of-many minimum
    does not apply there, but an empty pool still fails issuance with
    `ERR_INSUFFICIENT_ELIGIBLES`." and "Under `UNRANKED`, entries are ordered
    by `submitted_at` ascending alone."

    Design: Corner/validations/direct_hire_unranked_end_to_end_bypass
    """
    ctx = setup_open_announcement(
        announcement_overrides={
            "hiring_authority": "DIRECT_HIRE",
            "assessment_method": "UNRANKED",
        })
    announcement = ctx["announcement"]
    applicant, application = setup_qualified_application(announcement)
    assert application["quality_category"] is None  # UNRANKED: never categorized

    # The SME machinery is bypassed, not optional.
    resp = api_client.create_assessment(
        application["id"], create_assessment_payload(5, 5, 5),
        make_sme_headers("sme-1"))
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_APPLICABLE)

    certificate = issue_certificate(announcement)  # closes, clock -> 2026-09-15
    entries = list_entries(certificate["id"])
    assert len(entries) == 1, "a single QUALIFIED applicant suffices under UNRANKED"
    entry = entries[0]
    assert entry["quality_category"] is None
    assert entry["augmented_score"] is None
    assert entry["rank_position"] == 1

    # Selection carries no category or preference gates on UNRANKED certificates.
    offer = select_entry(certificate["id"], entry["id"])
    assert offer["status"] == "TENTATIVE"

    accepted = accept_offer(offer, applicant)
    assert accepted["status"] == "ACCEPTED"
    record_suitability(offer["id"], "FAVORABLE")
    scheduled = validate_success(
        api_client.schedule_eod(
            offer["id"], schedule_eod_payload("2026-09-25T00:00:00Z"), SO),
        200)
    assert scheduled["status"] == "EOD_SCHEDULED"

    set_clock("2026-09-25T00:00:00Z")
    final = validate_success(api_client.confirm_eod(offer["id"], HR), 200)
    assert final["status"] == "ENTERED_ON_DUTY"

    appointments, meta = validate_paginated(api_client.list_appointments(offer["id"], HR))
    assert meta["total_count"] == 1
    assert appointments[0]["appointment_type"] == "DIRECT_HIRE"

    hired = get_success_data(api_client.get_application(application["id"], HR))
    assert hired["status"] == "HIRED"


def test_suitability_reviewer_cannot_record_clearance(api):
    """PRD §2.1: "A request whose role is not listed among an endpoint's
    authorized roles, or that violates an entity-backed ownership rule, is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.7: role authorization runs at priority 2, before "existence of
    every identifier in the path and every foreign key in the body (4,
    `ERR_NOT_FOUND`)".

    Design: Corner/rbac/suitability_reviewer_cannot_record_clearance
    """
    # Route-level role segregation: even a non-existent offer draws 403.
    resp = api_client.record_security_clearance(
        NON_EXISTENT_UUID,
        record_security_clearance_payload("FAVORABLE_FINAL"),
        TEST_USERS["suitability_reviewer_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
