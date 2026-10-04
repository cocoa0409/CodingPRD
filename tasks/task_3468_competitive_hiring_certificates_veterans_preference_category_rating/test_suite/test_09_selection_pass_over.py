"""Selection gates and the veterans-preference pass-over procedure, plus the
vacancy-slot conservation invariant.
"""
from test_helpers import (
    HR, OPM, SO, ApiErrorId,
    adjudicate_pass_over_payload, api_client, create_pass_over_request_payload,
    get_success_data, make_applicant_headers, register_applicant,
    register_verified_preference_applicant, respond_to_offer_payload,
    select_entry, select_entry_payload, set_clock, setup_competitive_certificate,
    validate_error, validate_paginated, validate_success,
)


def _preference_scenario():
    """Certificate whose rank-1 entry is a verified CPS eligible (raw 96),
    rank-2 a non-preference candidate (raw 100), rank-3 a merged
    WELL_QUALIFIED non-preference candidate (raw 94). All three categories
    derive from the default cut points 95/85."""
    carol = register_verified_preference_applicant("TEN_POINT_CPS")
    dave = register_applicant()
    frank = register_applicant()
    ctx = setup_competitive_certificate(
        ratings_list=((3, 5, 5), (5, 5, 5), (4, 4, 4)),
        vacancies_count=1,
        applicants=[carol, dave, frank])
    return ctx


def test_pending_pass_over_blocks_lower_selection(api):
    """PRD §3.8: "While a `PENDING` pass-over request names a higher-ranked
    `REFERRED` preference-eligible entry on the same certificate, selections of
    lower-ranked entries are blocked with `ERR_PASS_OVER_PENDING` (HTTP 409),
    and adjudication of that request to either outcome clears the block."

    Design: Corner/validations/pending_pass_over_blocks_lower_selection
    """
    ctx = _preference_scenario()
    certificate = ctx["certificate"]
    e1, e2, _e3 = ctx["entries"]

    request = validate_success(
        api_client.create_pass_over_request(
            e1["id"], create_pass_over_request_payload(e2["id"]), SO),
        201)
    assert request["status"] == "PENDING"

    resp = api_client.select_entry(
        certificate["id"], select_entry_payload(e2["id"]), SO)
    validate_error(resp, ApiErrorId.ERR_PASS_OVER_PENDING)

    for entry in (e1, e2):
        reread = get_success_data(api_client.get_entry(entry["id"], HR))
        assert reread["status"] == "REFERRED", "the blocked selection must not mutate entries"


def test_lower_category_selection_bypass_rejected(api):
    """PRD §3.8: "no entry may be selected while a `REFERRED` entry in a
    strictly higher category exists on the same certificate —
    `ERR_CATEGORY_BYPASS` (HTTP 422) — and a pass-over approval cannot cure a
    category bypass".

    Design: Corner/validations/lower_category_selection_bypass_rejected
    """
    ctx = _preference_scenario()
    certificate = ctx["certificate"]
    e3 = ctx["entries"][2]
    assert e3["quality_category"] == "WELL_QUALIFIED"

    resp = api_client.select_entry(
        certificate["id"], select_entry_payload(e3["id"]), SO)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_BYPASS)

    for entry in ctx["entries"]:
        reread = get_success_data(api_client.get_entry(entry["id"], HR))
        assert reread["status"] == "REFERRED", "the bypassed selection must not mutate entries"


def test_preference_pass_over_full_approval_flow(api):
    """PRD §3.8: "a non-preference-eligible entry may not be selected while a
    `REFERRED` preference-eligible entry with a smaller `rank_position` exists
    in the same category, unless an `APPROVED` pass-over request covers exactly
    that target-and-desired pair; a violation is `ERR_PASS_OVER_REQUIRED`
    (HTTP 422)".
    PRD §3.8: "An `outcome` of `APPROVED` moves the target entry `REFERRED` →
    `PASSED_OVER`, a terminal resting place, and records the delegate's
    `X-User-ID` as `adjudicated_by`".

    Design: Corner/validations/preference_pass_over_full_approval_flow
    """
    ctx = _preference_scenario()
    certificate, announcement = ctx["certificate"], ctx["announcement"]
    e1, e2, _e3 = ctx["entries"]

    resp = api_client.select_entry(
        certificate["id"], select_entry_payload(e2["id"]), SO)
    validate_error(resp, ApiErrorId.ERR_PASS_OVER_REQUIRED)

    request = validate_success(
        api_client.create_pass_over_request(
            e1["id"], create_pass_over_request_payload(e2["id"]), SO),
        201)
    adjudicated = validate_success(
        api_client.adjudicate_pass_over(
            request["id"],
            adjudicate_pass_over_payload("APPROVED",
                                         adjudication_note="objection sustained"),
            OPM),
        200)
    assert adjudicated["status"] == "APPROVED"
    assert adjudicated["adjudicated_by"] == "opm-1"

    target = get_success_data(api_client.get_entry(e1["id"], HR))
    assert target["status"] == "PASSED_OVER"

    # The clock has not moved since issuance (2026-09-15): the offer's
    # response window lands exactly five days later.
    offer = validate_success(
        api_client.select_entry(
            certificate["id"], select_entry_payload(e2["id"]), SO),
        201)
    assert offer["status"] == "TENTATIVE"
    assert offer["response_due_at"] == "2026-09-20T00:00:00Z"

    dave_application = ctx["applications"][1]
    selected = get_success_data(api_client.get_application(dave_application["id"], HR))
    assert selected["status"] == "SELECTED"
    announcement = get_success_data(api_client.get_announcement(announcement["id"], HR))
    assert announcement["remaining_vacancies"] == 0


def test_pass_over_target_must_be_preference_eligible(api):
    """PRD §3.8: "The target must be preference-eligible and must rank above
    the desired entry — that is, hold a smaller `rank_position` — and the
    desired entry must not itself be preference-eligible; failure of any of
    these is `ERR_NOT_PREFERENCE_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/pass_over_target_must_be_preference_eligible
    """
    ctx = _preference_scenario()
    e1, e2, e3 = ctx["entries"]

    # Target is the non-preference entry dave.
    resp = api_client.create_pass_over_request(
        e2["id"], create_pass_over_request_payload(e3["id"], reason_code="OTHER"), SO)
    validate_error(resp, ApiErrorId.ERR_NOT_PREFERENCE_ELIGIBLE)

    # Desired entry is itself preference-eligible (and is the target).
    resp = api_client.create_pass_over_request(
        e1["id"], create_pass_over_request_payload(e1["id"], reason_code="OTHER"), SO)
    validate_error(resp, ApiErrorId.ERR_NOT_PREFERENCE_ELIGIBLE)


def test_pass_over_double_adjudication_rejected(api):
    """PRD §3.8: "Adjudication belongs to the `OPMDelegate` and acts only on a
    `PENDING` request — anything else is `ERR_PASS_OVER_NOT_PENDING`
    (HTTP 409)."

    Design: Corner/validations/pass_over_double_adjudication_rejected
    """
    ctx = _preference_scenario()
    e1, e2, _e3 = ctx["entries"]

    request = validate_success(
        api_client.create_pass_over_request(
            e1["id"], create_pass_over_request_payload(e2["id"]), SO),
        201)
    adjudicated = validate_success(
        api_client.adjudicate_pass_over(
            request["id"], adjudicate_pass_over_payload("APPROVED"), OPM),
        200)
    assert adjudicated["status"] == "APPROVED"
    assert get_success_data(api_client.get_entry(e1["id"], HR))["status"] == "PASSED_OVER"

    resp = api_client.adjudicate_pass_over(
        request["id"], adjudicate_pass_over_payload("DENIED"), OPM)
    validate_error(resp, ApiErrorId.ERR_PASS_OVER_NOT_PENDING)

    requests, meta = validate_paginated(
        api_client.list_entry_pass_over_requests(e1["id"], HR))
    assert meta["total_count"] == 1
    assert requests[0]["status"] == "APPROVED", "the rejected re-adjudication must not flip the outcome"


def test_pass_over_denied_preserves_preference_gate(api):
    """PRD §3.8: "`DENIED` records `adjudicated_by` and leaves the entries
    untouched." and "a violation is `ERR_PASS_OVER_REQUIRED` (HTTP 422)".

    Design: Corner/validations/pass_over_denied_preserves_preference_gate
    """
    ctx = _preference_scenario()
    certificate = ctx["certificate"]
    e1, e2, _e3 = ctx["entries"]

    request = validate_success(
        api_client.create_pass_over_request(
            e1["id"], create_pass_over_request_payload(e2["id"]), SO),
        201)
    adjudicated = validate_success(
        api_client.adjudicate_pass_over(
            request["id"], adjudicate_pass_over_payload("DENIED"), OPM),
        200)
    assert adjudicated["status"] == "DENIED"

    target = get_success_data(api_client.get_entry(e1["id"], HR))
    assert target["status"] == "REFERRED", "a denied pass-over never moves the target"

    resp = api_client.select_entry(
        certificate["id"], select_entry_payload(e2["id"]), SO)
    validate_error(resp, ApiErrorId.ERR_PASS_OVER_REQUIRED)


def test_vacancy_slot_conservation_select_decline_reselect(api):
    """PRD §3.2: "The announcement's `remaining_vacancies` is a computed
    counter: `vacancies_count` minus the number of certificate entries
    belonging to this announcement that sit in `SELECTED` with their offer in
    `TENTATIVE`, `ACCEPTED`, `EOD_SCHEDULED`, or `ENTERED_ON_DUTY`".
    PRD §3.8: "Finally, `remaining_vacancies` must be positive, else
    `ERR_NO_REMAINING_VACANCIES` (HTTP 409)."
    PRD §3.2: "reaching `FILLED` does not recall or close an `ACTIVE`
    certificate: if vacancies later reappear because an offer is declined or
    rescinded, the still-`ACTIVE` certificate remains selectable".

    Design: Difficulty/compensating_invariant/vacancy_slot_conservation_select_decline_reselect
    """
    ctx = setup_competitive_certificate(vacancies_count=2)
    certificate, announcement = ctx["certificate"], ctx["announcement"]
    e1, e2, e3 = ctx["entries"]

    def remaining():
        return get_success_data(
            api_client.get_announcement(announcement["id"], HR))["remaining_vacancies"]

    offer1 = select_entry(certificate["id"], e1["id"])
    assert offer1["status"] == "TENTATIVE"
    assert remaining() == 1

    select_entry(certificate["id"], e2["id"], select_clock=None)
    assert remaining() == 0

    resp = api_client.select_entry(
        certificate["id"], select_entry_payload(e3["id"]), SO)
    validate_error(resp, ApiErrorId.ERR_NO_REMAINING_VACANCIES)

    # Compensating action: declining the first offer restores the slot.
    applicant1 = next(a for a, ap in zip(ctx["applicants"], ctx["applications"])
                      if ap["id"] == e1["application_id"])
    set_clock("2026-09-17T00:00:00Z")
    declined = validate_success(
        api_client.respond_to_offer(
            offer1["id"], respond_to_offer_payload("DECLINE"),
            make_applicant_headers(applicant1["id"])),
        200)
    assert declined["status"] == "DECLINED"
    assert remaining() == 1, "decline restores the consumed vacancy slot"

    # The still-ACTIVE certificate remains selectable even though the
    # announcement auto-filled when the counter hit zero.
    offer3 = select_entry(certificate["id"], e3["id"], select_clock=None)
    assert offer3["status"] == "TENTATIVE"
    assert remaining() == 0
