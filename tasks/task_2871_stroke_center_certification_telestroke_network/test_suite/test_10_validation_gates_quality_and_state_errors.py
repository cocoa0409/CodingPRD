"""Uniqueness gates, quality-report gates and the per-entity invalid-state errors.

Every test here drives one validation rule to its refusal and then proves the
refused write left nothing behind, before walking the same request down the
route the PRD does allow.
"""
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    REQUIRED_HANDOFF_PACKET_ITEMS,
    REQUIRED_HANDOFF_PACKET_ITEMS_TRANSFER_ONLY,
)
from test_helpers.test_users import (
    ABSTRACTOR,
    CERTIFICATION_REVIEWER_USER_ID,
    COORD,
    ED,
    PROGRAM_COORDINATOR_USER_ID,
    QUALITY_ABSTRACTOR_USER_ID,
    REVIEWER,
    TRANSFER,
    make_neurologist_headers,
)

DOOR_AT = "2026-09-01T08:00:00Z"


def _read_deviation(deviation_id):
    """Read a deviation back through the framework validator."""
    return validate_success(api_client.get_deviation(deviation_id, REVIEWER))


def _live_case_with_consult():
    """A case at the spoke sitting in CONSULT_IN_PROGRESS, ready for a checklist."""
    context = fx.setup_network(clock=DOOR_AT)
    built = fx.setup_case_with_completed_consult(context, DOOR_AT)
    return context, built["case"]


def test_a_second_checklist_on_the_same_case_is_refused_and_the_first_is_untouched():
    """The duplicate create is refused and the one checklist keeps both confirmed items.

    PRD 3.5: "One is opened per case, naming it through `case_id`, and a second attempt on the same case is `ERR_DUPLICATE_CHECKLIST`."
    PRD 3.5: "The code is appended, `confirmed_inclusion_item_count` is recomputed as the array's length, and `documentation_status` moves from `NOT_STARTED` to `IN_PROGRESS`."

    Design: Corner/validations/a_case_may_carry_only_one_thrombolytic_checklist
    """
    _context, case = _live_case_with_consult()
    case_id = case["id"]
    checklist = fx.create_checklist(case_id)
    assert checklist["documentation_status"] == "NOT_STARTED", (
        f"a fresh checklist starts at NOT_STARTED, got {checklist['documentation_status']}"
    )
    fx.confirm_item(checklist["id"], "INC_ONSET_CONFIRMED")
    first = fx.confirm_item(checklist["id"], "INC_NIHSS_RECORDED")
    assert first["confirmed_inclusion_item_count"] == 2, (
        f"two confirmations make a count of two, got {first['confirmed_inclusion_item_count']}"
    )
    assert first["screening_eligibility_score"] == 30.00, (
        f"15.0 points per confirmed item screens at 30.00, got {first['screening_eligibility_score']}"
    )

    fx.set_clock("2026-09-01T08:40:00Z")
    response = api_client.create_checklist(f.checklist_payload(case_id), ED)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CHECKLIST.value, 409)

    data, meta = validate_paginated(
        api_client.list_checklists(ED, {"case_id": case_id, "limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 1, (
        f"the refused create must not add a second row, got {meta['total_count']}"
    )
    assert [row["id"] for row in data] == [checklist["id"]], (
        "the surviving checklist is the original one"
    )

    after = fx.read_checklist(checklist["id"])
    assert after["version"] == first["version"], (
        f"the refused duplicate must not bump the survivor's version, got {after['version']}"
    )
    assert a.instants_equal(after["updated_at"], first["updated_at"]), (
        f"nor refresh its updated_at, got {after['updated_at']}"
    )
    assert after["confirmed_inclusion_item_codes"] == [
        "INC_ONSET_CONFIRMED", "INC_NIHSS_RECORDED",
    ], f"the confirmed items survive intact, got {after['confirmed_inclusion_item_codes']}"
    assert after["documentation_status"] == "IN_PROGRESS"
    assert after["determination_status"] == "PENDING"


def test_a_repeated_or_unknown_inclusion_item_shares_one_error_and_writes_nothing():
    """Both the repeat and the unrecognised code return ERR_DUPLICATE_INCLUSION_ITEM, not an enum failure.

    PRD 3.5: "The `item_code` must be one of `INC_ONSET_CONFIRMED`, `INC_NIHSS_RECORDED`, `INC_BP_CONTROLLED` or `INC_ANTICOAG_REVIEWED`, and must not already be present in `confirmed_inclusion_item_codes`; either an unknown code or a repeat is `ERR_DUPLICATE_INCLUSION_ITEM`."
    PRD 2.11: "one checklist per case (`ERR_DUPLICATE_CHECKLIST`, 409); one live abstraction per case-and-measure pair (`ERR_DUPLICATE_ABSTRACTION`, 409); no duplicate or unrecognised inclusion item (`ERR_DUPLICATE_INCLUSION_ITEM`, 409)"

    Design: Corner/validations/an_inclusion_item_must_be_a_known_code_and_may_not_repeat
    """
    _context, case = _live_case_with_consult()
    checklist = fx.create_checklist(case["id"])
    single = fx.confirm_item(checklist["id"], "INC_ONSET_CONFIRMED")
    assert single["confirmed_inclusion_item_count"] == 1
    assert single["screening_eligibility_score"] == 15.00, (
        f"one confirmed item screens at 15.00, got {single['screening_eligibility_score']}"
    )

    fx.set_clock("2026-09-01T08:30:00Z")
    repeat = api_client.confirm_inclusion_item(
        checklist["id"], f.inclusion_item_payload("INC_ONSET_CONFIRMED"), ED
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_INCLUSION_ITEM.value, 409)

    unknown = api_client.confirm_inclusion_item(
        checklist["id"], f.inclusion_item_payload("INC_GLUCOSE_CHECKED"), ED
    )
    error = validate_error(unknown, ApiErrorId.ERR_DUPLICATE_INCLUSION_ITEM.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_ENUM_VALUE.value, (
        "an unrecognised inclusion code is reported as a duplicate, not as an enum failure"
    )

    unchanged = fx.read_checklist(checklist["id"])
    assert unchanged["confirmed_inclusion_item_codes"] == ["INC_ONSET_CONFIRMED"], (
        f"neither refusal appends anything, got {unchanged['confirmed_inclusion_item_codes']}"
    )
    assert unchanged["confirmed_inclusion_item_count"] == 1
    assert unchanged["screening_eligibility_score"] == 15.00, (
        f"the score is untouched by the refusals, got {unchanged['screening_eligibility_score']}"
    )
    assert unchanged["version"] == single["version"], (
        f"two refused writes leave the version alone, got {unchanged['version']}"
    )

    accepted = fx.confirm_item(checklist["id"], "INC_BP_CONTROLLED")
    assert accepted["confirmed_inclusion_item_codes"] == [
        "INC_ONSET_CONFIRMED", "INC_BP_CONTROLLED",
    ], f"a genuinely new code still appends, got {accepted['confirmed_inclusion_item_codes']}"
    assert accepted["confirmed_inclusion_item_count"] == 2
    assert accepted["screening_eligibility_score"] == 30.00, (
        f"the second distinct item adds its 15.0, got {accepted['screening_eligibility_score']}"
    )
    assert accepted["version"] == single["version"] + 1, (
        f"exactly one accepted write moved the version, got {accepted['version']}"
    )


def test_retracting_an_abstraction_frees_its_case_and_measure_pair_for_a_fresh_draft():
    """The pair is locked by the live row, released by the retraction, and re-openable afterwards.

    PRD 3.9: "At most one non-`RETRACTED` abstraction may exist per case-and-measure pair (`ERR_DUPLICATE_ABSTRACTION`), and the case must not yet be `CLOSED` or `ABORTED` when the draft is opened"
    PRD 3.9: "Retraction also frees the case-and-measure pair, so a fresh abstraction for the same measure on the same case may then be created."

    Design: Corner/validations/a_measure_may_be_abstracted_once_per_case_until_the_abstraction_is_retracted
    """
    context = fx.setup_network(clock=DOOR_AT)
    built = fx.setup_treated_case(context, DOOR_AT, dtn_minutes=45, dti_minutes=20)
    case_id = built["case"]["id"]
    assert built["case"]["status"] == "THROMBOLYSIS_ADMINISTERED", (
        f"the abstraction is opened while the case is still live, got {built['case']['status']}"
    )

    first = fx.create_abstraction(case_id, "STK_DTN_60")
    assert first["status"] == "DRAFT"
    assert first["variant"] == "PROVISIONAL"
    assert first["abstracted_by_user_id"] == QUALITY_ABSTRACTOR_USER_ID, (
        f"the creator's identity header is recorded, got {first['abstracted_by_user_id']}"
    )

    duplicate = api_client.create_abstraction(
        f.abstraction_payload(case_id, "STK_DTN_60"), ABSTRACTOR
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ABSTRACTION.value, 409)

    other_measure = fx.create_abstraction(case_id, "STK_DTI_45")
    assert other_measure["measure_code"] == "STK_DTI_45", (
        "a different measure on the same case is a different pair, got "
        f"{other_measure['measure_code']}"
    )
    assert other_measure["id"] != first["id"]

    retracted = fx.retract_abstraction(first["id"])
    assert retracted["status"] == "RETRACTED", (
        f"the retraction is the compensating action, got {retracted['status']}"
    )
    assert retracted["retraction_reason"] == "wrong case abstracted", (
        f"the supplied reason is stored, got {retracted['retraction_reason']}"
    )
    assert retracted["report_id"] is None

    reopened = fx.create_abstraction(case_id, "STK_DTN_60")
    assert reopened["id"] != first["id"], "the freed pair yields a brand new row"
    assert reopened["measure_code"] == "STK_DTN_60"
    assert reopened["status"] == "DRAFT"
    assert reopened["variant"] == "PROVISIONAL"
    assert reopened["attested_by_user_id"] is None
    assert reopened["retraction_reason"] is None

    _rows, meta = validate_paginated(
        api_client.list_abstractions(ABSTRACTOR, {"case_id": case_id, "limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 3, (
        "the retracted row is kept alongside the two live ones, got "
        f"{meta['total_count']}"
    )

    still_locked = api_client.create_abstraction(
        f.abstraction_payload(case_id, "STK_DTN_60"), ABSTRACTOR
    )
    validate_error(still_locked, ApiErrorId.ERR_DUPLICATE_ABSTRACTION.value, 409)


def test_an_empty_period_report_is_refused_on_the_abstraction_gate_not_the_volume_gate():
    """With nothing finalised and nothing closed, the finalised-abstraction rule is the one reported.

    PRD 3.9: "requires the report to be `DRAFT` or `RETURNED`, `included_abstraction_count` to be 1 or more (`ERR_NO_FINALIZED_ABSTRACTIONS`, since a report with nothing finalised attached carries no signal), and `closed_case_count_in_period` to be 2 or more (`ERR_INSUFFICIENT_CASE_VOLUME`, since two closed cases is the minimum volume from which a rate means anything)"
    PRD 2.11: "a report needs at least one finalised abstraction (`ERR_NO_FINALIZED_ABSTRACTIONS`, 422); a report needs a minimum closed-case volume (`ERR_INSUFFICIENT_CASE_VOLUME`, 422)"
    PRD 3.9: "When the denominator is 0 the rate is **0.00** — never null, and never 100.00 on the reasoning that nothing failed."

    Design: Corner/validations/an_empty_report_is_refused_for_having_nothing_finalized_before_the_volume_rule_is_reached
    """
    period_start = "2026-09-01T00:00:00Z"
    period_end = "2026-10-01T00:00:00Z"
    context = fx.setup_network(clock=period_start)
    report = fx.create_report(
        context["spoke"]["id"], period_start, period_end, at="2026-10-02T09:00:00Z"
    )

    assert report["status"] == "DRAFT"
    assert report["rate_variant"] == "PROVISIONAL"
    assert report["decision"] == "PENDING"
    assert report["included_abstraction_count"] == 0, (
        f"nothing was abstracted in the period, got {report['included_abstraction_count']}"
    )
    assert report["closed_case_count_in_period"] == 0, (
        f"no case closed in the period, got {report['closed_case_count_in_period']}"
    )
    assert report["dtn_60_compliance_pct"] == 0.00
    assert report["dti_45_compliance_pct"] == 0.00
    assert report["telestroke_response_compliance_pct"] == 0.00
    assert report["mean_dtn_excess_pct"] is None, (
        "an empty population is null rather than zero, got "
        f"{report['mean_dtn_excess_pct']}"
    )
    assert report["composite_certification_score"] == 0.00, (
        f"the composite is only produced at submission, got {report['composite_certification_score']}"
    )

    fx.set_clock("2026-10-02T10:00:00Z")
    response = api_client.submit_certification_report(report["id"], headers=COORD)
    error = validate_error(response, ApiErrorId.ERR_NO_FINALIZED_ABSTRACTIONS.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_CASE_VOLUME.value, (
        "both gates are armed but the finalised-abstraction rule outranks the volume rule"
    )

    after = fx.read_report(report["id"])
    assert after["status"] == "DRAFT", f"the refused submission leaves it DRAFT, got {after['status']}"
    assert after["rate_variant"] == "PROVISIONAL", (
        f"the variant never flipped to CERTIFIED, got {after['rate_variant']}"
    )
    assert after["submitted_at"] is None, f"nothing was stamped, got {after['submitted_at']}"
    assert after["submitted_by_user_id"] is None
    assert after["composite_certification_score"] == 0.00, (
        f"no composite was computed, got {after['composite_certification_score']}"
    )
    assert after["version"] == report["version"], (
        f"the refused submission wrote nothing at all, got version {after['version']}"
    )


def test_one_closed_case_fails_the_volume_gate_while_exactly_two_clears_it():
    """Two closed cases is the whole requirement, and the adjacent second period is legal.

    PRD 3.9: "`closed_case_count_in_period` to be 2 or more (`ERR_INSUFFICIENT_CASE_VOLUME`, since two closed cases is the minimum volume from which a rate means anything)"
    PRD 3.9: "Adjacency is explicitly allowed: a period beginning at exactly an existing period's `period_end` is accepted, because the existing period never included that instant."
    PRD 3.9: "Any existing `DRAFT` report for the same facility moves to `SUPERSEDED` with its `superseded_by_report_id` pointing at the new report, and every abstraction attached to it is detached by having `report_id` cleared to null."

    Design: Corner/validations/submission_needs_two_closed_cases_in_the_period_and_exactly_two_is_enough
    """
    september_start = "2026-09-01T00:00:00Z"
    october_start = "2026-10-01T00:00:00Z"
    november_start = "2026-11-01T00:00:00Z"
    context = fx.setup_network(clock=september_start)
    spoke_id = context["spoke"]["id"]
    lonely = fx.setup_reportable_case(context, "2026-09-01T08:00:00Z", dtn_minutes=None)
    pair = [
        fx.setup_reportable_case(context, "2026-10-02T08:00:00Z", dtn_minutes=None),
        fx.setup_reportable_case(context, "2026-10-03T08:00:00Z", dtn_minutes=None),
    ]
    assert lonely["case"]["status"] == "CLOSED"
    for built in pair:
        assert built["case"]["status"] == "CLOSED"

    september = fx.create_report(
        spoke_id, september_start, october_start, at="2026-10-04T09:00:00Z"
    )
    assert september["closed_case_count_in_period"] == 1, (
        f"only one case closed inside September, got {september['closed_case_count_in_period']}"
    )
    assert september["included_abstraction_count"] == 1, (
        "its finalised abstraction is attached, so the abstraction gate is satisfied, got "
        f"{september['included_abstraction_count']}"
    )

    fx.set_clock("2026-10-04T09:30:00Z")
    response = api_client.submit_certification_report(september["id"], headers=COORD)
    error = validate_error(response, ApiErrorId.ERR_INSUFFICIENT_CASE_VOLUME.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_NO_FINALIZED_ABSTRACTIONS.value, (
        "one finalised abstraction clears the first gate, so the volume gate is the one reported"
    )
    refused = fx.read_report(september["id"])
    assert refused["status"] == "DRAFT"
    assert refused["submitted_at"] is None

    october = fx.create_report(
        spoke_id, october_start, november_start, at="2026-10-04T10:00:00Z"
    )
    assert october["status"] == "DRAFT", (
        "a period starting exactly at the previous period_end is not an overlap"
    )
    assert october["closed_case_count_in_period"] == 2, (
        f"exactly two cases closed inside October, got {october['closed_case_count_in_period']}"
    )
    assert october["included_abstraction_count"] == 2, (
        f"one finalised abstraction per October case, got {october['included_abstraction_count']}"
    )

    superseded = fx.read_report(september["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"the earlier DRAFT is superseded by the create, got {superseded['status']}"
    )
    assert superseded["superseded_by_report_id"] == october["id"], (
        f"and points at the new report, got {superseded['superseded_by_report_id']}"
    )
    assert fx.read_abstraction(lonely["abstractions"]["STK_DTN_60"]["id"])["report_id"] is None, (
        "the superseded report's abstraction is detached"
    )

    submitted = fx.submit_report(october["id"], at="2026-10-05T09:00:00Z")
    assert submitted["status"] == "SUBMITTED", (
        f"exactly two closed cases is enough volume, got {submitted['status']}"
    )
    assert submitted["rate_variant"] == "CERTIFIED", (
        f"submission flips the variant, got {submitted['rate_variant']}"
    )
    assert a.instants_equal(submitted["submitted_at"], "2026-10-05T09:00:00Z"), (
        f"submitted_at is stamped from the logical clock, got {submitted['submitted_at']}"
    )
    assert submitted["submitted_by_user_id"] == PROGRAM_COORDINATOR_USER_ID, (
        f"the submitter's identity is recorded, got {submitted['submitted_by_user_id']}"
    )
    assert submitted["closed_case_count_in_period"] == 2


def test_a_deviation_can_be_returned_for_information_only_below_review_round_three():
    """Two round trips are allowed, the third return-for-info is refused, and the decision still lands.

    PRD 3.8: "A reviewer starts the review of an `OPEN` deviation, which moves it to `UNDER_REVIEW`, raises `review_round` to 1 and records `reviewed_by_user_id`."
    PRD 3.8: "The loop terminates because entering review requires `review_round` to be below 3: the fourth entry attempt is refused with `ERR_REVIEW_ROUND_LIMIT`, and so is a return-for-info once `review_round` has already reached 3."

    Design: Corner/validations/a_deviation_may_be_returned_for_information_only_while_the_round_count_is_under_three
    """
    context = fx.setup_network(clock=DOOR_AT)
    case = fx.activate_case(context["spoke"]["id"], DOOR_AT)
    deviation = fx.create_deviation(
        case["id"], deviation_type="DTN_EXCEEDED", severity="MAJOR",
        narrative="needle documented late by the bedside team",
    )
    assert deviation["status"] == "OPEN"
    assert deviation["review_round"] == 0, (
        f"a manual deviation opens at round 0, got {deviation['review_round']}"
    )
    assert deviation["source"] == "MANUAL"
    assert deviation["debrief_completed"] is False

    entered = fx.start_review(deviation["id"])
    assert entered["status"] == "UNDER_REVIEW"
    assert entered["review_round"] == 1, (
        f"entering review raises the round to 1, got {entered['review_round']}"
    )
    assert entered["reviewed_by_user_id"] == CERTIFICATION_REVIEWER_USER_ID, (
        f"the reviewer is recorded on entry, got {entered['reviewed_by_user_id']}"
    )

    returned = fx.return_for_info(deviation["id"])
    assert returned["status"] == "RETURNED_FOR_INFO"
    assert returned["review_round"] == 1, (
        f"returning for information does not itself raise the round, got {returned['review_round']}"
    )
    assert returned["info_request"] == "supply the medication administration record", (
        f"the reviewer's request is stored, got {returned['info_request']}"
    )

    second = fx.resubmit_deviation(deviation["id"])
    assert second["status"] == "UNDER_REVIEW"
    assert second["review_round"] == 2, (
        f"each re-entry raises the round by one, got {second['review_round']}"
    )
    fx.return_for_info(deviation["id"])
    third = fx.resubmit_deviation(deviation["id"])
    assert third["review_round"] == 3, (
        f"the second round trip lands on the ceiling, got {third['review_round']}"
    )
    assert third["status"] == "UNDER_REVIEW"

    response = api_client.return_deviation_for_info(
        deviation["id"], f.return_for_info_payload(), REVIEWER
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_ROUND_LIMIT.value, 409)

    unchanged = _read_deviation(deviation["id"])
    assert unchanged["review_round"] == 3, (
        f"the refused return leaves the round on the ceiling, got {unchanged['review_round']}"
    )
    assert unchanged["status"] == "UNDER_REVIEW", (
        f"and leaves the deviation under review, got {unchanged['status']}"
    )
    assert unchanged["version"] == third["version"], (
        f"the refused return wrote nothing, got version {unchanged['version']}"
    )

    decided = fx.decide_deviation(deviation["id"], "SUBSTANTIATE")
    assert decided["status"] == "SUBSTANTIATED", (
        "the round ceiling blocks another return, not the decision, got "
        f"{decided['status']}"
    )


def test_only_a_sentinel_substantiation_is_gated_on_the_debrief():
    """A sentinel needs the debrief to be substantiated; a major does not, and a dismissal never does.

    PRD 3.8: "Substantiating a deviation whose `severity` is `SENTINEL` requires `debrief_completed` to be true, otherwise `ERR_DEBRIEF_REQUIRED`; `MINOR` and `MAJOR` deviations may be substantiated without one."
    PRD 3.8: "it is the only thing that ever writes those two fields — the decision never does, however thorough the reviewer's note"
    PRD 3.8: "Dismissal instead lowers the case's `deviation_count`, because a dismissed deviation is no longer a deviation the case is carrying."

    Design: Corner/validations/only_sentinel_deviations_need_a_debrief_before_they_can_be_substantiated
    """
    context = fx.setup_network(clock=DOOR_AT)
    case = fx.activate_case(context["spoke"]["id"], DOOR_AT)
    case_id = case["id"]
    sentinel = fx.create_deviation(
        case_id, deviation_type="LKW_WINDOW_VIOLATION", severity="SENTINEL",
        narrative="lysis considered outside the declared window",
    )
    major = fx.create_deviation(
        case_id, deviation_type="DTN_EXCEEDED", severity="MAJOR",
        narrative="needle time missed the sixty minute target",
    )
    dismissible_sentinel = fx.create_deviation(
        case_id, deviation_type="MISSING_CONTRAINDICATION_DOC", severity="SENTINEL",
        narrative="contraindication screen not filed in the record",
    )
    assert fx.read_case(case_id)["deviation_count"] == 3, "three manual deviations are carried"
    for row in (sentinel, major, dismissible_sentinel):
        entered = fx.start_review(row["id"])
        assert entered["status"] == "UNDER_REVIEW"
        assert entered["debrief_completed"] is False

    before = _read_deviation(sentinel["id"])
    response = api_client.decide_deviation(
        sentinel["id"], f.decide_deviation_payload("SUBSTANTIATE"), REVIEWER
    )
    validate_error(response, ApiErrorId.ERR_DEBRIEF_REQUIRED.value, 422)
    refused = _read_deviation(sentinel["id"])
    assert refused["status"] == "UNDER_REVIEW", (
        f"the refused decision leaves it under review, got {refused['status']}"
    )
    assert refused["debrief_completed"] is False, (
        "the decision never writes the debrief fields, got "
        f"{refused['debrief_completed']}"
    )
    assert refused["debrief_summary"] is None
    assert refused["version"] == before["version"], (
        f"the refused decision wrote nothing, got version {refused['version']}"
    )

    substantiated_major = fx.decide_deviation(major["id"], "SUBSTANTIATE")
    assert substantiated_major["status"] == "SUBSTANTIATED", (
        f"a MAJOR needs no debrief at all, got {substantiated_major['status']}"
    )
    assert substantiated_major["debrief_completed"] is False, (
        "and it was substantiated with the debrief flag still false"
    )

    dismissed = fx.decide_deviation(dismissible_sentinel["id"], "DISMISS")
    assert dismissed["status"] == "DISMISSED", (
        f"a sentinel may be dismissed without a debrief, got {dismissed['status']}"
    )
    assert dismissed["debrief_completed"] is False
    assert fx.read_case(case_id)["deviation_count"] == 2, (
        "the dismissal lowers the case's count, got "
        f"{fx.read_case(case_id)['deviation_count']}"
    )

    debriefed = fx.debrief_deviation(sentinel["id"])
    assert debriefed["debrief_completed"] is True, (
        f"the debrief is the only writer of the flag, got {debriefed['debrief_completed']}"
    )
    assert debriefed["debrief_summary"] == "multidisciplinary debrief held with the ED team", (
        f"the summary is stored verbatim, got {debriefed['debrief_summary']}"
    )
    assert debriefed["status"] == "UNDER_REVIEW", "the debrief is not a transition"

    now_allowed = fx.decide_deviation(sentinel["id"], "SUBSTANTIATE")
    assert now_allowed["status"] == "SUBSTANTIATED", (
        f"the identical decision now lands, got {now_allowed['status']}"
    )
    assert now_allowed["reviewed_by_user_id"] == CERTIFICATION_REVIEWER_USER_ID
    assert now_allowed["debrief_completed"] is True


def test_the_same_three_item_packet_is_incomplete_for_drip_and_ship_and_complete_for_transfer_only():
    """One packet, two modes: refused on the lysis transfer, accepted on the transfer-only one.

    PRD 3.7: "`HP_IMAGING_DISC`, `HP_LYTIC_RECORD`, `HP_NIHSS` and `HP_CONSENT` are all required for a `DRIP_AND_SHIP` transfer, while a `TRANSFER_ONLY` transfer requires that set minus `HP_LYTIC_RECORD` — there is no lytic record to hand over when no lytic was given."
    PRD 3.7: "A missing required item is `ERR_HANDOFF_PACKET_INCOMPLETE`, so a settled handoff always ends with `handoff_packet_complete` true."

    Design: Corner/validations/the_required_handoff_packet_depends_on_the_transfer_mode
    """
    context = fx.setup_network(clock=DOOR_AT)
    destination = fx.register_thrombectomy_center(state_code=context["spoke"]["state_code"])
    short_packet = list(REQUIRED_HANDOFF_PACKET_ITEMS_TRANSFER_ONLY)
    assert "HP_LYTIC_RECORD" not in short_packet, "the short packet is the one missing the lytic record"

    ship = fx.setup_accepted_transfer(
        context, DOOR_AT, mode="DRIP_AND_SHIP", destination_id=destination["id"],
        dtn_minutes=50, dti_minutes=10,
    )
    ship_transfer = ship["transfer"]
    assert ship_transfer["status"] == "ACCEPTED"
    assert ship_transfer["mode"] == "DRIP_AND_SHIP"

    fx.set_clock("2026-09-01T09:30:00Z")
    response = api_client.complete_handoff(
        ship_transfer["id"], f.handoff_payload(short_packet), TRANSFER
    )
    validate_error(response, ApiErrorId.ERR_HANDOFF_PACKET_INCOMPLETE.value, 422)

    unsettled = fx.read_transfer(ship_transfer["id"])
    assert unsettled["status"] == "ACCEPTED", (
        f"the refused settlement leaves the transfer accepted, got {unsettled['status']}"
    )
    assert unsettled["handoff_packet_items"] == [], (
        f"no items are recorded by a refused handoff, got {unsettled['handoff_packet_items']}"
    )
    assert unsettled["handoff_packet_complete"] is False
    assert unsettled["door_in_door_out_minutes"] is None, (
        f"and no interval is measured, got {unsettled['door_in_door_out_minutes']}"
    )
    assert unsettled["handoff_completed_at"] is None
    assert fx.read_case(ship["case"]["id"])["status"] == "TRANSFER_INITIATED", (
        "the case is still in transit"
    )

    settled = fx.complete_handoff(
        ship_transfer["id"], handoff_packet_items=REQUIRED_HANDOFF_PACKET_ITEMS,
        at="2026-09-01T09:50:00Z",
    )
    assert settled["status"] == "HANDOFF_COMPLETE", (
        f"adding the lytic record settles the same transfer, got {settled['status']}"
    )
    assert settled["handoff_packet_complete"] is True
    assert sorted(settled["handoff_packet_items"]) == sorted(REQUIRED_HANDOFF_PACKET_ITEMS), (
        f"all four items are recorded, got {settled['handoff_packet_items']}"
    )
    assert settled["door_in_door_out_minutes"] == 110, (
        f"08:00 to 09:50 is 110 whole minutes, got {settled['door_in_door_out_minutes']}"
    )
    shipped_case = fx.read_case(ship["case"]["id"])
    assert shipped_case["status"] == "CLOSED"
    assert shipped_case["disposition"] == "DRIP_AND_SHIP", (
        f"the closed case keeps the mode's disposition, got {shipped_case['disposition']}"
    )
    assert shipped_case["deviation_count"] == 0, (
        f"110 minutes is inside the 120-minute door-in-door-out target, got {shipped_case['deviation_count']}"
    )

    only = fx.setup_accepted_transfer(
        context, "2026-09-01T12:00:00Z", mode="TRANSFER_ONLY",
        destination_id=destination["id"], dti_minutes=10,
    )
    assert only["transfer"]["mode"] == "TRANSFER_ONLY"
    accepted_same_packet = fx.complete_handoff(
        only["transfer"]["id"], handoff_packet_items=short_packet, at="2026-09-01T13:30:00Z"
    )
    assert accepted_same_packet["status"] == "HANDOFF_COMPLETE", (
        "the identical three items are a complete packet for a transfer-only handoff, got "
        f"{accepted_same_packet['status']}"
    )
    assert accepted_same_packet["handoff_packet_complete"] is True, (
        "completeness is judged against the mode-conditional set"
    )
    assert sorted(accepted_same_packet["handoff_packet_items"]) == sorted(short_packet), (
        f"exactly the three supplied items are recorded, got {accepted_same_packet['handoff_packet_items']}"
    )
    assert accepted_same_packet["door_in_door_out_minutes"] == 90, (
        f"12:00 to 13:30 is 90 whole minutes, got {accepted_same_packet['door_in_door_out_minutes']}"
    )
    only_case = fx.read_case(only["case"]["id"])
    assert only_case["status"] == "CLOSED"
    assert only_case["disposition"] == "TRANSFER_ONLY", (
        f"the transfer-only case closes on its own disposition, got {only_case['disposition']}"
    )


def test_a_suspended_facility_cannot_publish_its_already_accepted_report():
    """The report is accepted and the facility is not: publication is refused and the public figure stays null.

    PRD 3.9: "requires an `ACCEPTED` report whose `decision` is `CERTIFIED` or `CONDITIONAL`, and a facility whose `certification_status` is not `SUSPENDED` or `WITHDRAWN` (`ERR_CENTER_NOT_CERTIFIED`) — a facility can be accepted on one report and suspended on the strength of a later one before the first is published, and in that case the publication is refused."
    PRD 3.9: "`CONDITIONAL` from 70.00 up to but not including 85.00"

    Design: Corner/validations/a_suspended_center_cannot_publish_its_already_accepted_report
    """
    scenario = fx.setup_report_scenario(
        cases=[
            {"measures": ("STK_DTN_60", "STK_DTI_45")},
            {"measures": ("STK_DTN_60", "STK_DTI_45")},
        ],
        submit=True,
    )
    report = scenario["report"]
    center_id = scenario["center"]["id"]
    assert report["status"] == "SUBMITTED"
    assert report["included_abstraction_count"] == 4, (
        f"two cases with two measures each, got {report['included_abstraction_count']}"
    )
    assert report["dtn_60_compliance_pct"] == 100.00
    assert report["dti_45_compliance_pct"] == 100.00
    assert report["telestroke_response_compliance_pct"] == 0.00, (
        "nothing was abstracted against the telestroke measure, got "
        f"{report['telestroke_response_compliance_pct']}"
    )
    assert report["composite_certification_score"] == 71.25, (
        "40.00 + 35.00 + 0.00 with no penalty or credit, times the 0.95 spoke multiplier, got "
        f"{report['composite_certification_score']}"
    )

    decided = fx.decide_report(report["id"], at="2026-10-05T09:00:00Z")
    assert decided["decision"] == "CONDITIONAL", (
        f"71.25 sits in the conditional band, got {decided['decision']}"
    )
    assert decided["status"] == "ACCEPTED", (
        f"a conditional decision accepts the report, got {decided['status']}"
    )
    conditional_center = fx.read_center(center_id)
    assert conditional_center["certification_status"] == "CONDITIONAL"
    assert conditional_center["ems_routing_posture"] == "DIVERT_ADVISORY", (
        "a conditional facility carries a standing divert advisory, got "
        f"{conditional_center['ems_routing_posture']}"
    )

    suspended = fx.suspend_center(center_id, suspension_reason="state review of the stroke program")
    assert suspended["certification_status"] == "SUSPENDED"
    assert suspended["ems_routing_posture"] == "BYPASS", (
        f"a suspended facility is bypassed outright, got {suspended['ems_routing_posture']}"
    )

    fx.set_clock("2026-10-06T09:00:00Z")
    response = api_client.publish_certification_report(report["id"], headers=COORD)
    error = validate_error(response, ApiErrorId.ERR_CENTER_NOT_CERTIFIED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REPORT_STATE.value, (
        "the report itself is in a publishable state; it is the facility that is not"
    )

    after = fx.read_report(report["id"])
    assert after["status"] == "ACCEPTED", (
        f"the refused publication leaves the report accepted, got {after['status']}"
    )
    assert after["decision"] == "CONDITIONAL"
    assert after["published_at"] is None, (
        f"nothing was stamped, got {after['published_at']}"
    )
    assert after["version"] == decided["version"], (
        f"the refused publication wrote nothing, got version {after['version']}"
    )

    center_after = fx.read_center(center_id)
    assert center_after["public_dtn_compliance_pct"] is None, (
        "the public figure is never refreshed by a refused publication, got "
        f"{center_after['public_dtn_compliance_pct']}"
    )
    assert center_after["public_report_published_at"] is None
    assert center_after["certification_status"] == "SUSPENDED"
    assert center_after["suspension_reason"] == "state review of the stroke program", (
        f"the suspension reason is the one the reviewer supplied, got {center_after['suspension_reason']}"
    )


def test_a_readiness_attestation_must_name_a_declared_component_and_result():
    """Undeclared component and undeclared result are enum failures that move no flag.

    PRD 3.1: "A `component` or `result` outside those declared sets is an enum failure returning `ERR_INVALID_ENUM_VALUE`."
    PRD 3.1: "Posting `FAIL` for a component whose flag is already false is accepted and has no further effect beyond the ordinary `updated_at` refresh and `version` increment; there is no error for a redundant attestation."
    PRD 2.9: "The posture is `READY` when both flags are true, `DEGRADED` when exactly one is true, and `OFFLINE` when neither is true."

    Design: Corner/validations/a_readiness_attestation_must_name_a_declared_component_and_result
    """
    fx.set_clock(DOOR_AT)
    center = fx.register_center()
    assert center["ct_scanner_ready"] is True
    assert center["video_cart_ready"] is True
    assert center["equipment_readiness_posture"] == "READY"
    assert center["ems_routing_posture"] == "ROUTINE"

    fx.set_clock("2026-09-01T08:05:00Z")
    bad_component = api_client.record_readiness_attestation(
        center["id"], f.readiness_attestation_payload("MRI_SCANNER", "PASS"), COORD
    )
    validate_error(bad_component, ApiErrorId.ERR_INVALID_ENUM_VALUE.value, 422)
    bad_result = api_client.record_readiness_attestation(
        center["id"], f.readiness_attestation_payload("CT_SCANNER", "INCONCLUSIVE"), COORD
    )
    validate_error(bad_result, ApiErrorId.ERR_INVALID_ENUM_VALUE.value, 422)

    untouched = fx.read_center(center["id"])
    assert untouched["version"] == center["version"], (
        f"neither rejected attestation bumps the version, got {untouched['version']}"
    )
    assert a.instants_equal(untouched["updated_at"], center["updated_at"]), (
        "and neither refreshes updated_at even though the clock has moved, got "
        f"{untouched['updated_at']}"
    )
    assert untouched["ct_scanner_ready"] is True
    assert untouched["video_cart_ready"] is True
    assert untouched["equipment_readiness_posture"] == "READY"

    degraded = fx.attest_readiness(center["id"], "CT_SCANNER", "FAIL")
    assert degraded["ct_scanner_ready"] is False, (
        f"a declared FAIL clears the named flag, got {degraded['ct_scanner_ready']}"
    )
    assert degraded["video_cart_ready"] is True, "the other flag is untouched"
    assert degraded["equipment_readiness_posture"] == "DEGRADED", (
        f"exactly one flag true is DEGRADED, got {degraded['equipment_readiness_posture']}"
    )
    assert degraded["ems_routing_posture"] == "DIVERT_ADVISORY", (
        f"a degraded facility diverts, got {degraded['ems_routing_posture']}"
    )

    fx.set_clock("2026-09-01T08:20:00Z")
    redundant = fx.attest_readiness(center["id"], "CT_SCANNER", "FAIL")
    assert redundant["ct_scanner_ready"] is False, "the redundant FAIL is accepted, not refused"
    assert redundant["equipment_readiness_posture"] == "DEGRADED", (
        f"and changes nothing about the posture, got {redundant['equipment_readiness_posture']}"
    )
    assert redundant["version"] == degraded["version"] + 1, (
        f"the redundant attestation still increments the version, got {redundant['version']}"
    )
    assert not a.instants_equal(redundant["updated_at"], degraded["updated_at"]), (
        f"and still refreshes updated_at, got {redundant['updated_at']}"
    )

    offline = fx.attest_readiness(center["id"], "VIDEO_CART", "FAIL")
    assert offline["video_cart_ready"] is False
    assert offline["equipment_readiness_posture"] == "OFFLINE", (
        f"neither flag true is OFFLINE, got {offline['equipment_readiness_posture']}"
    )
    assert offline["ems_routing_posture"] == "BYPASS", (
        f"an offline facility is bypassed, got {offline['ems_routing_posture']}"
    )


def test_a_consult_cannot_be_completed_on_audio_only_or_repeatedly_dropped_sessions():
    """Three recorded sessions, two of them invalid, and the completion gate opens only on the valid one.

    PRD 3.4: "the consult's `valid_video_session_count` must be 1 or more (`ERR_NO_VALID_VIDEO_SESSION`)"
    PRD 3.4: "A ten-minute `AUDIO_ONLY` session is invalid however long it ran and however stable it was, because audio-only contact cannot support a stroke examination. A ten-minute `SD` session that dropped twice is valid; the same session with a third drop is not."
    PRD 3.4: "An invalid session is not rejected — it is recorded, and it opens a system-detected `ProtocolDeviation` of type `INVALID_VIDEO_SESSION` and severity `MINOR` on the consult's case, raising that case's `deviation_count` by 1."

    Design: Corner/validations/a_consult_cannot_be_completed_on_audio_only_or_repeatedly_dropped_sessions
    """
    context = fx.setup_network(clock=DOOR_AT)
    neurologist_id = context["neurologist"]["id"]
    headers = make_neurologist_headers(neurologist_id)
    case = fx.activate_case(context["spoke"]["id"], DOOR_AT)
    case_id = case["id"]
    fx.complete_imaging(case_id, at="2026-09-01T08:10:00Z")
    requested = fx.request_consult(
        case_id, context["agreement"]["id"], at="2026-09-01T08:12:00Z"
    )
    consult_id = requested["id"]
    in_session = fx.accept_consult(consult_id, neurologist_id, at="2026-09-01T08:14:00Z")
    assert in_session["status"] == "IN_SESSION"
    assert in_session["valid_video_session_count"] == 0
    assert in_session["video_sessions"] == []

    no_sessions = api_client.complete_consult(consult_id, f.complete_consult_payload(), headers)
    validate_error(no_sessions, ApiErrorId.ERR_NO_VALID_VIDEO_SESSION.value, 409)

    fx.append_video_session(
        consult_id, neurologist_id, "2026-09-01T08:15:00Z", "2026-09-01T08:25:00Z",
        video_quality="AUDIO_ONLY",
    )
    after_audio = fx.read_consult(consult_id)
    assert len(after_audio["video_sessions"]) == 1, (
        f"the invalid session is recorded, not rejected, got {len(after_audio['video_sessions'])}"
    )
    assert after_audio["video_sessions"][0]["duration_seconds"] == 600, (
        f"ten minutes is 600 seconds, got {after_audio['video_sessions'][0]['duration_seconds']}"
    )
    assert after_audio["video_sessions"][0]["session_valid"] is False, (
        "audio-only cannot support the examination however long it ran"
    )
    assert after_audio["valid_video_session_count"] == 0, (
        f"an invalid session raises nothing, got {after_audio['valid_video_session_count']}"
    )
    still_shut = api_client.complete_consult(consult_id, f.complete_consult_payload(), headers)
    validate_error(still_shut, ApiErrorId.ERR_NO_VALID_VIDEO_SESSION.value, 409)

    fx.append_video_session(
        consult_id, neurologist_id, "2026-09-01T08:26:00Z", "2026-09-01T08:36:00Z",
        video_quality="SD", disconnect_count=3,
    )
    after_drops = fx.read_consult(consult_id)
    assert len(after_drops["video_sessions"]) == 2
    assert after_drops["video_sessions"][1]["session_valid"] is False, (
        "a third disconnect crosses the inclusive two-drop ceiling"
    )
    assert after_drops["valid_video_session_count"] == 0, (
        f"three sessions, none valid, is still a shut gate, got {after_drops['valid_video_session_count']}"
    )
    deviations = fx.list_case_deviations(case_id)
    assert len(deviations) == 2, (
        f"each invalid session opens its own deviation, got {len(deviations)}"
    )
    for deviation in deviations:
        a.assert_system_detected_deviation(deviation, "INVALID_VIDEO_SESSION", "MINOR")
    assert fx.read_case(case_id)["deviation_count"] == 2, (
        f"the case carries both, got {fx.read_case(case_id)['deviation_count']}"
    )
    refused_again = api_client.complete_consult(consult_id, f.complete_consult_payload(), headers)
    validate_error(refused_again, ApiErrorId.ERR_NO_VALID_VIDEO_SESSION.value, 409)
    assert fx.read_consult(consult_id)["status"] == "IN_SESSION", (
        "three refusals leave the consult in session"
    )

    fx.append_video_session(
        consult_id, neurologist_id, "2026-09-01T08:40:00Z", "2026-09-01T08:43:00Z",
        video_quality="HD",
    )
    after_valid = fx.read_consult(consult_id)
    assert after_valid["video_sessions"][2]["duration_seconds"] == 180, (
        f"exactly 180 seconds is on the passing side, got {after_valid['video_sessions'][2]['duration_seconds']}"
    )
    assert after_valid["video_sessions"][2]["session_valid"] is True
    assert after_valid["valid_video_session_count"] == 1, (
        f"the tally counts the valid ones only, got {after_valid['valid_video_session_count']}"
    )
    assert len(after_valid["video_sessions"]) == 3
    assert fx.read_case(case_id)["deviation_count"] == 2, (
        "the valid session opens no deviation of its own"
    )

    completed = validate_success(
        api_client.complete_consult(consult_id, f.complete_consult_payload(), headers)
    )
    assert completed["status"] == "COMPLETED", (
        f"one valid session is all the gate ever wanted, got {completed['status']}"
    )
    assert completed["recommendation"] == "THROMBOLYSIS"
    assert completed["valid_video_session_count"] == 1


def test_an_undeclared_oncall_move_and_a_repeat_suspension_carry_their_own_state_errors():
    """The neurologist edge that was never declared and the facility that is already suspended.

    PRD 2.11: "The addressed record must be in a state from which the requested transition is declared, otherwise the per-entity invalid-state code applies: `ERR_INVALID_CENTER_STATE`, `ERR_INVALID_AGREEMENT_STATE`, `ERR_INVALID_ONCALL_TRANSITION`, `ERR_INVALID_CONSULT_STATE`, `ERR_INVALID_TRANSFER_STATE`, `ERR_INVALID_DEVIATION_STATE`, `ERR_INVALID_ABSTRACTION_STATE` or `ERR_INVALID_REPORT_STATE` (all 409)."
    PRD 3.1: "`IN_CONSULT` is not settable here at all — it is reached only by accepting a consult and left only by completing or losing one — so requesting `IN_CONSULT` directly is rejected, as is any move with no declared edge such as `OFF_DUTY → UNAVAILABLE`; all such rejections carry `ERR_INVALID_ONCALL_TRANSITION`."
    PRD 3.9: "Suspending a facility that is already `SUSPENDED`, or one that is `WITHDRAWN`, is `ERR_INVALID_CENTER_STATE`."

    Design: Corner/validations/terminal_and_undeclared_transitions_return_their_own_entity_specific_state_error
    """
    fx.set_clock(DOOR_AT)
    hub = fx.register_hub()
    neurologist = fx.register_neurologist(hub["id"])
    assert neurologist["on_call_state"] == "OFF_DUTY", (
        f"a fresh neurologist is off duty, got {neurologist['on_call_state']}"
    )

    fx.set_clock("2026-09-01T08:05:00Z")
    undeclared = api_client.set_on_call_state(
        neurologist["id"], f.on_call_state_payload("UNAVAILABLE"), COORD
    )
    validate_error(undeclared, ApiErrorId.ERR_INVALID_ONCALL_TRANSITION.value, 409)
    in_consult = api_client.set_on_call_state(
        neurologist["id"], f.on_call_state_payload("IN_CONSULT"), COORD
    )
    error = validate_error(in_consult, ApiErrorId.ERR_INVALID_ONCALL_TRANSITION.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_ENUM_VALUE.value, (
        "IN_CONSULT is a declared state that is simply not settable, not an unknown value"
    )
    unmoved = fx.read_neurologist(neurologist["id"])
    assert unmoved["on_call_state"] == "OFF_DUTY", (
        f"neither refusal moves the roster state, got {unmoved['on_call_state']}"
    )
    assert unmoved["version"] == neurologist["version"], (
        f"and neither writes anything, got version {unmoved['version']}"
    )

    spoke = fx.register_spoke()
    suspended = fx.suspend_center(spoke["id"], suspension_reason="first review finding")
    assert suspended["certification_status"] == "SUSPENDED"
    assert suspended["ems_routing_posture"] == "BYPASS"
    assert suspended["suspension_reason"] == "first review finding"

    fx.set_clock("2026-09-01T08:30:00Z")
    again = api_client.suspend_stroke_center(
        spoke["id"],
        f.suspend_center_payload(suspension_reason="second review finding"),
        REVIEWER,
    )
    validate_error(again, ApiErrorId.ERR_INVALID_CENTER_STATE.value, 409)
    still = fx.read_center(spoke["id"])
    assert still["certification_status"] == "SUSPENDED"
    assert still["suspension_reason"] == "first review finding", (
        f"the refused second suspension does not overwrite the reason, got {still['suspension_reason']}"
    )
    assert still["version"] == suspended["version"], (
        f"nor bump the version, got {still['version']}"
    )


def test_publishing_a_draft_report_returns_the_report_state_error():
    """The facility is perfectly publishable; it is the report's DRAFT state that refuses.

    PRD 3.9: "takes no request body and requires an `ACCEPTED` report whose `decision` is `CERTIFIED` or `CONDITIONAL`, and a facility whose `certification_status` is not `SUSPENDED` or `WITHDRAWN` (`ERR_CENTER_NOT_CERTIFIED`)"
    PRD 3.9: "a `DENIED` one moves it to `RETURNED`, from where it can be resubmitted. Deciding a `DRAFT` report is `ERR_INVALID_REPORT_STATE`."
    PRD 2.11: "The addressed record must be in a state from which the requested transition is declared, otherwise the per-entity invalid-state code applies"

    Design: Corner/validations/terminal_and_undeclared_transitions_return_their_own_entity_specific_state_error
    """
    fx.set_clock("2026-09-01T00:00:00Z")
    spoke = fx.register_spoke()
    assert spoke["certification_status"] == "PROVISIONAL", (
        "a provisional facility is neither suspended nor withdrawn, got "
        f"{spoke['certification_status']}"
    )
    report = fx.create_report(
        spoke["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", at="2026-10-02T09:00:00Z"
    )
    assert report["status"] == "DRAFT"
    assert report["decision"] == "PENDING"

    fx.set_clock("2026-10-02T09:30:00Z")
    response = api_client.publish_certification_report(report["id"], headers=COORD)
    error = validate_error(response, ApiErrorId.ERR_INVALID_REPORT_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_CENTER_NOT_CERTIFIED.value, (
        "the facility gate is satisfied, so the report's own state error is the one reported"
    )

    after = fx.read_report(report["id"])
    assert after["status"] == "DRAFT", f"the report stays DRAFT, got {after['status']}"
    assert after["published_at"] is None, f"nothing is stamped, got {after['published_at']}"
    assert after["version"] == report["version"], (
        f"the refused publication wrote nothing, got version {after['version']}"
    )
    center_after = fx.read_center(spoke["id"])
    assert center_after["public_dtn_compliance_pct"] is None, (
        "the public rollup is untouched, got "
        f"{center_after['public_dtn_compliance_pct']}"
    )
    assert center_after["public_report_published_at"] is None


def test_a_proposed_transfer_and_an_open_deviation_each_report_their_own_state_error():
    """A complete packet cannot settle a PROPOSED transfer, and an OPEN deviation cannot be returned.

    PRD 3.7: "Only an `ACCEPTED` transfer can be handed off; attempting it on a `PROPOSED` or `DECLINED` one is `ERR_INVALID_TRANSFER_STATE`."
    PRD 3.8: "From `UNDER_REVIEW` the reviewer may return it for more information with an `info_request`, moving it to `RETURNED_FOR_INFO`"
    PRD 3.8: "Deciding an `OPEN` deviation, or resubmitting one that is already `UNDER_REVIEW`, is `ERR_INVALID_DEVIATION_STATE`."

    Design: Corner/validations/the_remaining_state_errors_are_distinct_for_transfers_deviations_and_abstractions
    """
    context = fx.setup_network(clock=DOOR_AT)
    built = fx.setup_eligible_case(context, DOOR_AT, dti_minutes=10)
    case_id = built["case"]["id"]
    destination = fx.register_thrombectomy_center(state_code=context["spoke"]["state_code"])
    transfer = fx.propose_transfer(
        case_id, destination["id"], mode="TRANSFER_ONLY", transport_eta_minutes=35,
        at="2026-09-01T08:20:00Z",
    )
    assert transfer["status"] == "PROPOSED"
    deviation = fx.create_deviation(
        case_id, deviation_type="DIDO_EXCEEDED", severity="MINOR",
        narrative="door in door out drifted while transport was arranged",
    )
    assert deviation["status"] == "OPEN"
    complete_packet = list(REQUIRED_HANDOFF_PACKET_ITEMS_TRANSFER_ONLY)

    fx.set_clock("2026-09-01T09:00:00Z")
    early_handoff = api_client.complete_handoff(
        transfer["id"], f.handoff_payload(complete_packet), TRANSFER
    )
    transfer_error = validate_error(
        early_handoff, ApiErrorId.ERR_INVALID_TRANSFER_STATE.value, 409
    )
    assert transfer_error["error_id"] != ApiErrorId.ERR_HANDOFF_PACKET_INCOMPLETE.value, (
        "the packet is complete for this mode, so only the transfer's state can refuse it"
    )
    unsettled = fx.read_transfer(transfer["id"])
    assert unsettled["status"] == "PROPOSED"
    assert unsettled["handoff_packet_items"] == [], (
        f"the refused settlement records no items, got {unsettled['handoff_packet_items']}"
    )
    assert unsettled["handoff_packet_complete"] is False
    assert unsettled["door_in_door_out_minutes"] is None
    assert unsettled["version"] == transfer["version"], (
        f"and writes nothing at all, got version {unsettled['version']}"
    )

    early_return = api_client.return_deviation_for_info(
        deviation["id"], f.return_for_info_payload(), REVIEWER
    )
    validate_error(early_return, ApiErrorId.ERR_INVALID_DEVIATION_STATE.value, 409)
    still_open = _read_deviation(deviation["id"])
    assert still_open["status"] == "OPEN", (
        f"returning for information is declared only from UNDER_REVIEW, got {still_open['status']}"
    )
    assert still_open["info_request"] is None, (
        f"the refused return stores no request, got {still_open['info_request']}"
    )
    assert still_open["review_round"] == 0
    assert still_open["version"] == deviation["version"]

    fx.accept_transfer(transfer["id"], at="2026-09-01T09:05:00Z")
    settled = fx.complete_handoff(
        transfer["id"], handoff_packet_items=complete_packet, at="2026-09-01T09:30:00Z"
    )
    assert settled["status"] == "HANDOFF_COMPLETE", (
        f"the identical packet settles the accepted transfer, got {settled['status']}"
    )
    assert settled["door_in_door_out_minutes"] == 90, (
        f"08:00 to 09:30 is 90 whole minutes, got {settled['door_in_door_out_minutes']}"
    )

    entered = fx.start_review(deviation["id"])
    assert entered["status"] == "UNDER_REVIEW"
    now_returnable = fx.return_for_info(deviation["id"])
    assert now_returnable["status"] == "RETURNED_FOR_INFO", (
        f"the identical return now lands, got {now_returnable['status']}"
    )
    assert now_returnable["info_request"] == "supply the medication administration record"


def test_retracting_an_already_retracted_abstraction_returns_the_abstraction_state_error():
    """The retraction is not idempotent: the second attempt is refused and the first reason stands.

    PRD 3.9: "retracting out from under a report that has been submitted, accepted or published is `ERR_INVALID_ABSTRACTION_STATE`, as is retracting an already-`RETRACTED` row."
    PRD 3.9: "On success the row becomes `RETRACTED`, its `report_id` is cleared to null"

    Design: Corner/validations/the_remaining_state_errors_are_distinct_for_transfers_deviations_and_abstractions
    """
    context = fx.setup_network(clock=DOOR_AT)
    case = fx.activate_case(context["spoke"]["id"], DOOR_AT)
    abstraction = fx.create_abstraction(case["id"], "STK_DTI_45")
    assert abstraction["status"] == "DRAFT"

    retracted = fx.retract_abstraction(abstraction["id"])
    assert retracted["status"] == "RETRACTED"
    assert retracted["report_id"] is None
    assert retracted["retraction_reason"] == "wrong case abstracted"

    fx.set_clock("2026-09-01T09:00:00Z")
    response = api_client.retract_abstraction(
        abstraction["id"],
        f.retract_abstraction_payload(retraction_reason="retracted a second time in error"),
        ABSTRACTOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ABSTRACTION_STATE.value, 409)

    after = fx.read_abstraction(abstraction["id"])
    assert after["status"] == "RETRACTED", f"the row is already terminal, got {after['status']}"
    assert after["retraction_reason"] == "wrong case abstracted", (
        f"the second reason is never written, got {after['retraction_reason']}"
    )
    assert after["version"] == retracted["version"], (
        f"the refused retraction wrote nothing, got version {after['version']}"
    )
