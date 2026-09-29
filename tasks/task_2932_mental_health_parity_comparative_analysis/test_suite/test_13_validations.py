"""Guards that refuse a write, and the priority order between them.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_collection,
    assert_empty_collection,
    assert_error,
    assert_index,
    assert_instant_equals,
    assert_is_none,
    assert_ratio,
    assert_score,
)
from test_helpers.constants import (
    AnalysisStatus,
    AppliedTo,
    CompliancePosture,
    DeterminationOutcome,
    FulfillmentStatus,
    NqtlItemStatus,
    NqtlType,
    PlanYearStatus,
    RegulatorRequestStatus,
    ReviewOutcome,
    StringencyFinding,
    SubClassification,
    SubmissionStatus,
    SubmissionType,
)
from test_helpers.test_users import OFFICER_USER_ID, make_sponsor_headers

OUTPATIENT_SLICE = {"sub_classification": SubClassification.OFFICE_VISITS}


# ═══ validations / data_submission_with_denials_over_claims_or_an_unrequested_type_rejected ══


def _request_for_two_denial_rate_sets(api):
    """One live request that asks for two denial-rate sets and nothing else.

    Both refusals under test therefore have a healthy request to be refused
    against: the counters are the only thing wrong with the first attempt, and the
    type is the only thing wrong with the second.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=2,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )
    scenario.vendor_request_id = request["id"]
    return scenario


def test_impossible_counters_and_unrequested_material_are_both_refused_without_a_row(
    api, administrator_headers_for, officer_headers
):
    """A refused submission is not a rejected submission — nothing is written at all.

    Two hundred denials drawn from one hundred adjudicated claims is arithmetically
    impossible and is refused on the counters.  A network-composition set whose
    percentages are perfectly valid is refused because the sponsor never asked for
    that kind of material.  Neither call leaves a row behind, so the request still
    reports no validated submissions and sits in OPEN, and the TPA's cooperation is
    untouched: refusals are not late production.

    PRD: "Denials cannot exceed the claims they are drawn from: `mh_denials` must be
    at most `mh_adjudicated_claims`, and `ms_denials` at most
    `ms_adjudicated_claims`, or the submission is refused with
    `ERR_DENIALS_EXCEED_CLAIMS` (HTTP 422)."

    Design: Corner/validations/data_submission_with_denials_over_claims_or_an_unrequested_type_rejected
    """
    scenario = _request_for_two_denial_rate_sets(api)
    admin_headers = administrator_headers_for(scenario.admin_id)

    assert_error(
        api.create_data_submission(
            scenario.vendor_request_id,
            f.denial_rate_submission_payload(
                scenario.classification_id,
                mh_denials=200,
                mh_adjudicated_claims=100,
                ms_denials=71,
                ms_adjudicated_claims=1913,
            ),
            admin_headers,
        ),
        ApiErrorId.DENIALS_EXCEED_CLAIMS,
        422,
    )
    assert_error(
        api.create_data_submission(
            scenario.vendor_request_id,
            f.network_composition_submission_payload(
                scenario.classification_id,
                mh_in_network_provider_pct=0.30,
                ms_in_network_provider_pct=0.58,
            ),
            admin_headers,
        ),
        ApiErrorId.SUBMISSION_TYPE_NOT_REQUESTED,
        422,
    )

    assert_empty_collection(
        api.list_data_submissions(
            {"vendor_request_id": scenario.vendor_request_id}, admin_headers
        )
    )
    request = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert request["validated_submission_count"] == 0
    assert request["fulfillment_status"] == FulfillmentStatus.OPEN

    administrator = fx.read_administrator(api, scenario.admin_id, officer_headers)
    assert_score(administrator["cooperation_score"], 100.00, "cooperation_score")
    assert administrator["outstanding_request_count"] == 1


def test_the_material_the_sponsor_did_ask_for_is_accepted_from_the_same_tpa(
    api, administrator_headers_for
):
    """The two refusals cost the TPA nothing: the very next legitimate set validates.

    A denial-rate set of the requested type with coherent counters is written as
    VALIDATED, becomes the request's first validated submission and moves the
    fulfilment dimension to PARTIAL, because two sets were asked for and one has
    arrived.

    PRD: "The type must be one the sponsor actually asked for: a `submission_type`
    absent from the owning request's `requested_submission_types` is refused with
    `ERR_SUBMISSION_TYPE_NOT_REQUESTED` (HTTP 422)."

    Design: Corner/validations/data_submission_with_denials_over_claims_or_an_unrequested_type_rejected
    """
    scenario = _request_for_two_denial_rate_sets(api)
    admin_headers = administrator_headers_for(scenario.admin_id)
    api.create_data_submission(
        scenario.vendor_request_id,
        f.network_composition_submission_payload(scenario.classification_id),
        admin_headers,
    )

    submission = validate_success(
        api.create_data_submission(
            scenario.vendor_request_id,
            f.denial_rate_submission_payload(scenario.classification_id),
            admin_headers,
        ),
        201,
    )
    assert submission["status"] == SubmissionStatus.VALIDATED
    assert submission["submission_type"] == SubmissionType.DENIAL_RATES
    assert_ratio(submission["disparity_ratio"], 1.9235, 4, "disparity_ratio")

    assert_collection(
        api.list_data_submissions(
            {"vendor_request_id": scenario.vendor_request_id}, admin_headers
        ),
        1,
        1,
        False,
    )
    request = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert request["validated_submission_count"] == 1
    assert request["fulfillment_status"] == FulfillmentStatus.PARTIAL


# ═══ validations / duplicate_nqtl_item_for_the_same_type_rejected ═══════════════


def test_a_second_item_of_the_same_type_is_refused_while_another_type_is_welcome(
    api, officer_headers
):
    """Uniqueness is scoped to the plan year, the classification and the type together.

    A second prior-authorisation entry for the same classification collides even
    though it is applied to a different benefit side — `applied_to` is not part of
    the key — while a concurrent-review entry on that same classification is
    inventoried without complaint.  Two un-analysed items then hold the plan year at
    AT_RISK with no violation anywhere.

    PRD: "And the inventory holds one live row per limitation: when an NQTL item
    whose `status` is anything other than `REMEDIATED` already exists for the same
    `plan_year_id`, `classification_id` and `nqtl_type`, the create is rejected with
    `ERR_DUPLICATE_NQTL_ITEM` (HTTP 409) — a remediated item does not block
    re-inventorying the same limitation later."

    Design: Corner/validations/duplicate_nqtl_item_for_the_same_type_rejected
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        applied_to=AppliedTo.BOTH,
        description="Prior authorization for outpatient office visits.",
    )

    assert_error(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                scenario.plan_year_id,
                scenario.classification_id,
                nqtl_type=NqtlType.PRIOR_AUTHORIZATION,
                applied_to=AppliedTo.MENTAL_HEALTH_SUD_ONLY,
                description="A second prior-authorization entry for the same classification.",
            ),
            officer_headers,
        ),
        ApiErrorId.DUPLICATE_NQTL_ITEM,
        409,
    )

    concurrent_review = validate_success(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                scenario.plan_year_id,
                scenario.classification_id,
                nqtl_type=NqtlType.CONCURRENT_REVIEW,
                applied_to=AppliedTo.BOTH,
                description="Concurrent review for outpatient office visits.",
            ),
            officer_headers,
        ),
        201,
    )
    assert concurrent_review["status"] == NqtlItemStatus.INVENTORIED

    assert_collection(
        api.list_nqtl_items({"classification_id": scenario.classification_id}, officer_headers),
        2,
        2,
        False,
    )
    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["compliance_posture"] == CompliancePosture.AT_RISK
    assert plan_year["open_violation_count"] == 0


# ═══ validations / author_reviewing_their_own_analysis_is_rejected_before_the_evidence_check ══


def _submitted_analysis_authored_by_an_officer_with_no_evidence(api):
    """A SUBMITTED analysis authored under `user-officer-01` and no as-applied data.

    The draft is written with the sponsor role header but the officer's identity,
    because the segregation-of-duties rule compares identities and not roles.  No
    production request exists at all, so the certifying branch's evidence
    requirement is violated at the same time as the self-review rule.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    author_headers = make_sponsor_headers(OFFICER_USER_ID)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        nqtl_type=NqtlType.MEDICAL_NECESSITY_CRITERIA,
        applied_to=AppliedTo.BOTH,
        description="Medical necessity criteria for outpatient office visits.",
    )
    scenario.item_id = item["id"]
    analysis = fx.draft_analysis(
        api,
        item["id"],
        item["version"],
        author_headers,
        factor_count=3,
        evidentiary_standard_count=2,
        stringency_written_finding=StringencyFinding.COMPARABLE,
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )
    scenario.analysis_id = analysis["id"]
    fx.submit_analysis(api, analysis["id"], author_headers)
    return scenario


def test_the_self_review_refusal_answers_before_the_missing_evidence_refusal(
    api, officer_headers, officer_alt_headers
):
    """One call breaks two rules and the lower-numbered rule is the one reported.

    The author reviewing their own work is refused for self-certification, not for
    the absent as-applied data — and the data really was absent, which the identical
    call from an independent officer proves by reporting exactly that.  The analysis
    is still SUBMITTED with no certifier stamped, its author and revision round are
    untouched, and the item still stands at ANALYSIS_SUBMITTED.

    PRD: "Self-review of a comparative analysis (`ERR_SELF_CERTIFICATION`)."

    Design: Corner/validations/author_reviewing_their_own_analysis_is_rejected_before_the_evidence_check
    """
    scenario = _submitted_analysis_authored_by_an_officer_with_no_evidence(api)

    assert_error(
        api.review_analysis(
            scenario.analysis_id,
            f.review_payload(
                ReviewOutcome.CERTIFIED, review_note="Reviewing the analysis I wrote myself."
            ),
            officer_headers,
        ),
        ApiErrorId.SELF_CERTIFICATION,
        409,
    )
    assert_error(
        api.review_analysis(
            scenario.analysis_id,
            f.review_payload(
                ReviewOutcome.CERTIFIED,
                review_note="Independent review, but no as-applied data is on file.",
            ),
            officer_alt_headers,
        ),
        ApiErrorId.IN_OPERATION_DATA_MISSING,
        409,
    )

    analysis = fx.read_analysis(api, scenario.analysis_id)
    assert analysis["status"] == AnalysisStatus.SUBMITTED
    assert_is_none(analysis["certified_by_user_id"], "certified_by_user_id")
    assert analysis["authored_by_user_id"] == OFFICER_USER_ID
    assert analysis["revision_round"] == 0
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_SUBMITTED


# ═══ validations / submitting_an_analysis_below_the_minimum_documentation_rejected ══


def _item_with_a_one_factor_draft(api, officer_headers):
    """A step-therapy item documented by a single factor and no evidentiary standard.

    The floor is a submission-time rule, so this draft is created without complaint
    and is only stopped when somebody tries to file it.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        nqtl_type=NqtlType.STEP_THERAPY,
        applied_to=AppliedTo.BOTH,
        description="Step therapy for outpatient office visits.",
    )
    scenario.item_id = item["id"]
    thin = validate_success(
        api.create_analysis(
            f.analysis_payload(
                item["id"],
                item["version"],
                factor_count=1,
                evidentiary_standard_count=0,
                stringency_written_finding=StringencyFinding.COMPARABLE,
                stringency_operation_finding=StringencyFinding.COMPARABLE,
            ),
            scenario.sponsor_headers,
        ),
        201,
    )
    scenario.thin_analysis = thin
    scenario.thin_analysis_id = thin["id"]
    return scenario


def test_a_thin_analysis_is_created_happily_and_refused_only_at_submission(
    api, officer_headers
):
    """The documentation floor is a business rule at submit, not a shape rule at create.

    One factor and no evidentiary standard is a perfectly well-formed payload and
    is written as DRAFT with revision round 0, which also walks the item forward to
    ANALYSIS_DRAFTED.  Filing it is what fails, and the refusal leaves the analysis
    in DRAFT and the item exactly where the create put it.

    PRD: "It also requires the documentation to be minimally complete:
    `factor_count` must be at least 2 and `evidentiary_standard_count` at least 1,
    and an analysis short of either is refused with
    `ERR_INSUFFICIENT_COMPARATIVE_ANALYSIS` (HTTP 422)."

    Design: Corner/validations/submitting_an_analysis_below_the_minimum_documentation_rejected
    """
    scenario = _item_with_a_one_factor_draft(api, officer_headers)
    assert scenario.thin_analysis["status"] == AnalysisStatus.DRAFT
    assert scenario.thin_analysis["revision_round"] == 0
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_DRAFTED

    assert_error(
        api.submit_analysis(scenario.thin_analysis_id, {}, scenario.sponsor_headers),
        ApiErrorId.INSUFFICIENT_COMPARATIVE_ANALYSIS,
        422,
    )

    assert fx.read_analysis(api, scenario.thin_analysis_id)["status"] == AnalysisStatus.DRAFT
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_DRAFTED


def test_an_analysis_exactly_at_the_floor_supersedes_the_thin_one_and_submits(
    api, officer_headers
):
    """There is no update endpoint, so the way past the floor is a replacement.

    A second analysis documenting two factors and one evidentiary standard — the
    floor itself, not a comfortable margin — withdraws the thin draft on creation
    and submits cleanly, carrying the item to ANALYSIS_SUBMITTED.  The withdrawn row
    stays on the record, so the item's analysis history holds both.

    PRD: "A successful supersession moves the named row from whichever of `DRAFT`,
    `SUBMITTED` or `INSUFFICIENT` it occupied to `WITHDRAWN`, increments that row's
    `version` by 1, and removes it from the latest-analysis selector."

    Design: Corner/validations/submitting_an_analysis_below_the_minimum_documentation_rejected
    """
    scenario = _item_with_a_one_factor_draft(api, officer_headers)
    api.submit_analysis(scenario.thin_analysis_id, {}, scenario.sponsor_headers)

    replacement = fx.draft_analysis(
        api,
        scenario.item_id,
        None,
        scenario.sponsor_headers,
        supersedes_analysis_id=scenario.thin_analysis_id,
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.COMPARABLE,
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )
    assert fx.read_analysis(api, scenario.thin_analysis_id)["status"] == AnalysisStatus.WITHDRAWN

    submitted = validate_success(
        api.submit_analysis(replacement["id"], {}, scenario.sponsor_headers)
    )
    assert submitted["status"] == AnalysisStatus.SUBMITTED
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_SUBMITTED

    assert_collection(
        api.list_analyses({"nqtl_item_id": scenario.item_id}, scenario.sponsor_headers),
        2,
        2,
        False,
    )


# ═══ validations / determination_outcome_contradicting_the_evidence_rejected ═════


def _mh_only_limitation_denying_at_three_times_the_rate(api, officer_headers):
    """A SUBMITTED analysis that claims comparability over a 3x denial disparity.

    Both stringency findings read MORE_STRINGENT_MH and the validated denial-rate
    set — 300 of 1,000 against 100 of 1,000 — clamps the item's in-operation index
    to the 10.00 ceiling, so a COMPLIANT determination contradicts the record twice
    over.  The analysis is deliberately left uncertified so that the two refusals
    can be ordered against each other.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        nqtl_type=NqtlType.PRIOR_AUTHORIZATION,
        applied_to=AppliedTo.MENTAL_HEALTH_SUD_ONLY,
        description="Prior authorization imposed on MH/SUD outpatient visits only.",
    )
    scenario.item_id = item["id"]
    fx.with_denial_rate_evidence(api, scenario, nqtl_item_id=item["id"])
    analysis = fx.draft_analysis(
        api,
        item["id"],
        None,
        scenario.sponsor_headers,
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.MORE_STRINGENT_MH,
        stringency_operation_finding=StringencyFinding.MORE_STRINGENT_MH,
    )
    scenario.analysis_id = analysis["id"]
    fx.submit_analysis(api, analysis["id"], scenario.sponsor_headers)
    return scenario


def test_certification_is_demanded_before_the_evidence_is_even_consulted(
    api, officer_headers, officer_alt_headers
):
    """Declaring compliance fails for two different reasons in two different states.

    While the analysis is merely SUBMITTED the determination is refused for the
    missing certification — the earlier rung — and nothing about the disparity is
    mentioned.  Certifying the analysis removes that objection, and the identical
    call is then refused for contradicting the evidence, which is the later rung
    that had been waiting behind it all along.

    PRD: "A parity determination is recorded on one NQTL item by a
    `ComplianceOfficer`, and it is the moment the compliance verdict is made."

    Design: Corner/validations/determination_outcome_contradicting_the_evidence_rejected
    """
    scenario = _mh_only_limitation_denying_at_three_times_the_rate(api, officer_headers)

    assert_error(
        api.create_determination(
            scenario.item_id,
            f.determination_payload(
                DeterminationOutcome.COMPLIANT,
                fx.plan_year_version(api, scenario.plan_year_id, officer_headers),
                rationale="Claiming compliance while the analysis is still uncertified.",
            ),
            officer_headers,
        ),
        ApiErrorId.ANALYSIS_NOT_CERTIFIED,
        409,
    )

    certified = validate_success(
        api.review_analysis(
            scenario.analysis_id,
            f.review_payload(
                ReviewOutcome.CERTIFIED,
                review_note=(
                    "Certified by an independent officer on the strength of the validated "
                    "denial-rate data."
                ),
            ),
            officer_alt_headers,
        )
    )
    assert certified["status"] == AnalysisStatus.CERTIFIED

    assert_error(
        api.create_determination(
            scenario.item_id,
            f.determination_payload(
                DeterminationOutcome.COMPLIANT,
                fx.plan_year_version(api, scenario.plan_year_id, officer_headers),
                rationale="Claiming compliance against a 3x denial-rate disparity.",
            ),
            officer_headers,
        ),
        ApiErrorId.STRINGENCY_CONTRADICTS_EVIDENCE,
        409,
    )


def test_a_refused_determination_cascades_absolutely_nothing(api, officer_headers):
    """The verdict is the cascade trigger, so a refused verdict leaves the world still.

    The item keeps the status its submitted analysis gave it, no determiner is
    stamped on it, and its index and flag are the ones the evidence produced rather
    than anything the attempted verdict implied.  No participant notice is minted,
    and the plan year — one analysed item, no violations, a cooperative TPA — sits
    at COMPLIANT and OPEN by the §3.1 ladder.

    PRD: "The determination is the moment the compliance verdict is made, and it is
    the widest cascade in the system."

    Design: Corner/validations/determination_outcome_contradicting_the_evidence_rejected
    """
    scenario = _mh_only_limitation_denying_at_three_times_the_rate(api, officer_headers)
    fx.review_analysis(api, scenario.analysis_id, ReviewOutcome.CERTIFIED)
    api.create_determination(
        scenario.item_id,
        f.determination_payload(
            DeterminationOutcome.COMPLIANT,
            fx.plan_year_version(api, scenario.plan_year_id, officer_headers),
            rationale="Claiming compliance against a 3x denial-rate disparity.",
        ),
        officer_headers,
    )

    item = fx.read_item(api, scenario.item_id)
    assert item["status"] == NqtlItemStatus.ANALYSIS_SUBMITTED
    assert_is_none(item["determination_recorded_by_user_id"], "determination_recorded_by_user_id")
    assert_index(item["stringency_in_operation_index"], 10.00, "stringency_in_operation_index")
    assert item["stringency_flag"] is True

    assert_empty_collection(
        api.list_participant_notices(scenario.item_id, None, officer_headers)
    )

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["open_violation_count"] == 0
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT
    assert plan_year["status"] == PlanYearStatus.OPEN


# ═══ validations / a_fourth_reopen_of_the_same_analysis_rejected ═════════════════


_REVISION_NOTES = (
    "Round 1: the factor inventory is not comparable in operation.",
    "Round 2: still no evidentiary standards for the in-operation comparison.",
    "Round 3: the stringency comparison remains unsupported.",
    "Round 4 review: still insufficient.",
)


def _analysis_exhausted_by_three_revisions(api):
    """One analysis driven around the DRAFT/SUBMITTED/INSUFFICIENT loop until it jams.

    Each pass is a genuine submit-and-reject cycle, so the row arrives at
    `revision_round` 3 legitimately rather than by being written there, and the
    fourth review leaves it INSUFFICIENT — the one state a reopen is allowed from.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        nqtl_type=NqtlType.REIMBURSEMENT_RATE,
        applied_to=AppliedTo.BOTH,
        description="Outpatient reimbursement rate methodology.",
    )
    scenario.item_id = item["id"]
    analysis = fx.draft_analysis(
        api,
        item["id"],
        None,
        scenario.sponsor_headers,
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.COMPARABLE,
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )
    scenario.analysis_id = analysis["id"]
    scenario.reopened = []
    for round_number, note in enumerate(_REVISION_NOTES, start=1):
        fx.submit_analysis(api, analysis["id"], scenario.sponsor_headers)
        fx.review_analysis(
            api, analysis["id"], ReviewOutcome.INSUFFICIENT, review_note=note
        )
        if round_number < len(_REVISION_NOTES):
            scenario.reopened.append(
                fx.reopen_analysis(api, analysis["id"], scenario.sponsor_headers)
            )
    return scenario


def test_three_revisions_are_granted_and_the_fourth_reopen_is_refused(api):
    """The bound is checked against the stored round before the increment, not after.

    Rounds 1, 2 and 3 are each granted and each return the analysis to DRAFT with
    the counter one higher than before, so three full rewrites are available.  The
    fourth request arrives with the counter already standing at 3, which is not
    strictly less than 3, and is refused.

    PRD: "The loop `DRAFT` to `SUBMITTED` to `INSUFFICIENT` to `DRAFT` is therefore
    traversable repeatedly, but it is bounded: `revision_round` must be strictly
    less than 3 for a reopen to be accepted, so the fourth reopen of the same
    analysis is refused with `ERR_REVISION_LIMIT_REACHED` (HTTP 409)."

    Design: Corner/validations/a_fourth_reopen_of_the_same_analysis_rejected
    """
    scenario = _analysis_exhausted_by_three_revisions(api)
    assert [reopened["revision_round"] for reopened in scenario.reopened] == [1, 2, 3]
    assert [reopened["status"] for reopened in scenario.reopened] == [AnalysisStatus.DRAFT] * 3

    assert_error(
        api.reopen_analysis(scenario.analysis_id, {}, scenario.sponsor_headers),
        ApiErrorId.REVISION_LIMIT_REACHED,
        409,
    )


def test_the_exhausted_analysis_is_stranded_in_insufficient_and_cannot_be_refiled(api):
    """Refusing the reopen must not have consumed a round or nudged the state.

    The counter reads 3 rather than 4 and the analysis is still INSUFFICIENT, which
    is precisely the state that makes it unusable: submit only accepts DRAFT, so the
    row is stranded and a superseding analysis is the only route forward.  The item
    stands where the insufficient review left it, and the plan year — one analysed
    item and a cooperative TPA — is COMPLIANT and OPEN throughout.

    PRD: "**Submission** is performed by a `PlanSponsor` or an `Administrator` and
    moves the analysis `DRAFT` to `SUBMITTED`. It requires the analysis to be in
    `DRAFT` — anything else is refused with `ERR_ANALYSIS_NOT_DRAFT` (HTTP 409)."

    Design: Corner/validations/a_fourth_reopen_of_the_same_analysis_rejected
    """
    scenario = _analysis_exhausted_by_three_revisions(api)
    api.reopen_analysis(scenario.analysis_id, {}, scenario.sponsor_headers)

    analysis = fx.read_analysis(api, scenario.analysis_id)
    assert analysis["revision_round"] == 3
    assert analysis["status"] == AnalysisStatus.INSUFFICIENT

    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_DRAFTED

    assert_error(
        api.submit_analysis(scenario.analysis_id, {}, scenario.sponsor_headers),
        ApiErrorId.ANALYSIS_NOT_DRAFT,
        409,
    )

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT
    assert plan_year["status"] == PlanYearStatus.OPEN


# ═══ validations / rewinding_the_logical_clock_rejected ══════════════════════════


def test_an_equal_instant_is_as_unacceptable_as_a_backwards_one(api, sponsor_headers):
    """Monotonic means strictly increasing, so standing still is also a rewind.

    The first move to 2026-09-10 succeeds and answers with the inline recomputation
    report rather than a stored row — no administrators and no plan years exist, so
    both recomputed counts are zero.  Repeating that exact instant is refused, and so
    is stepping back to 2026-08-15.

    PRD: "The clock is monotonic: `current_utc` must be strictly later than the
    clock's present value, and a value equal to or earlier than the present value is
    rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

    Design: Corner/validations/rewinding_the_logical_clock_rejected
    """
    report = validate_success(api.set_clock(f.clock_payload("2026-09-10T00:00:00.000Z"), sponsor_headers))
    assert_instant_equals(report["current_utc"], "2026-09-10T00:00:00.000Z", "current_utc")
    assert report["recomputed_administrator_count"] == 0
    assert report["recomputed_plan_year_count"] == 0

    assert_error(
        api.set_clock(f.clock_payload("2026-09-10T00:00:00.000Z"), sponsor_headers),
        ApiErrorId.CLOCK_NOT_MONOTONIC,
        422,
    )
    assert_error(
        api.set_clock(f.clock_payload("2026-08-15T00:00:00.000Z"), sponsor_headers),
        ApiErrorId.CLOCK_NOT_MONOTONIC,
        422,
    )


def test_one_millisecond_forward_is_enough_and_a_bare_date_is_not_an_instant(
    api, sponsor_headers
):
    """The refusals neither moved nor corrupted the clock, and shape outranks monotonicity.

    A single millisecond past the current value clears the strictness bar, which
    proves the two rejected calls left the clock exactly where the accepted one put
    it.  A date with no time of day is refused as a malformed field rather than as a
    rewind, even though 2026-09-11 lies comfortably in the future.

    PRD: "Instants are rendered as ISO 8601 UTC with three fractional digits."

    Design: Corner/validations/rewinding_the_logical_clock_rejected
    """
    fx.advance_clock(api, "2026-09-10T00:00:00.000Z", sponsor_headers)
    api.set_clock(f.clock_payload("2026-09-10T00:00:00.000Z"), sponsor_headers)
    api.set_clock(f.clock_payload("2026-08-15T00:00:00.000Z"), sponsor_headers)

    report = validate_success(
        api.set_clock(f.clock_payload("2026-09-10T00:00:00.001Z"), sponsor_headers)
    )
    assert_instant_equals(report["current_utc"], "2026-09-10T00:00:00.001Z", "current_utc")

    assert_error(
        api.set_clock(f.clock_payload("2026-09-11"), sponsor_headers),
        ApiErrorId.VALIDATION,
        422,
    )


# ═══ validations / responding_when_no_inventoried_item_matches_the_demand_rejected ══


def _regulator_demanding_a_type_nobody_inventoried(api, officer_headers):
    """A docket demanding STEP_THERAPY analyses against a prior-authorisation inventory.

    The plan year holds exactly one item and it is of the wrong type, so the count
    the completeness score would divide by is zero.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        applied_to=AppliedTo.BOTH,
        description="Prior authorization for outpatient office visits.",
    )
    scenario.item_id = item["id"]
    request = fx.open_regulator_request(
        api,
        scenario.plan_year_id,
        requested_nqtl_types=[NqtlType.STEP_THERAPY],
        request_reference="DOL-EBSA-2026-00912",
    )
    scenario.regulator_request_id = request["id"]
    scenario.regulator_request = request
    return scenario


def test_a_demand_matching_no_inventoried_item_is_refused_instead_of_scored_zero(
    api, officer_headers
):
    """The empty denominator is guarded, not divided into and not reported as 0.00.

    Nothing of the demanded type is on the inventory, so the response is refused
    outright rather than scored as a total failure.  The request keeps its OPEN
    status and its score and sufficiency verdict are both still null, exactly as the
    opening left them: a refused response is not a response.

    PRD: "The demand must also match something: `requested_item_count` must be at
    least 1 at the moment of responding, and a request whose demanded NQTL types
    match no inventoried item cannot be scored and is refused with
    `ERR_NO_REQUESTED_ITEMS` (HTTP 409) rather than dividing by zero."

    Design: Corner/validations/responding_when_no_inventoried_item_matches_the_demand_rejected
    """
    scenario = _regulator_demanding_a_type_nobody_inventoried(api, officer_headers)
    assert scenario.regulator_request["status"] == RegulatorRequestStatus.OPEN
    assert_is_none(scenario.regulator_request["completeness_score"], "completeness_score")
    assert_is_none(scenario.regulator_request["response_sufficient"], "response_sufficient")

    assert_error(
        api.respond_regulator_request(
            scenario.regulator_request_id,
            f.respond_payload(response_note="Nothing of the demanded type is inventoried."),
            scenario.sponsor_headers,
        ),
        ApiErrorId.NO_REQUESTED_ITEMS,
        409,
    )

    request = fx.read_regulator_request(api, scenario.regulator_request_id)
    assert request["status"] == RegulatorRequestStatus.OPEN
    assert_is_none(request["completeness_score"], "completeness_score after the refusal")
    assert_is_none(request["response_sufficient"], "response_sufficient after the refusal")


def test_inventorying_the_demanded_type_under_review_unlocks_a_zero_scored_response(
    api, officer_headers
):
    """The count is taken fresh at respond time, so the inventory can still be fixed.

    Regulator review freezes classifications and treatment limitations but not the
    NQTL inventory, so the step-therapy item is admitted while the plan year sits
    UNDER_REGULATOR_REVIEW.  The response then scores: one item demanded, none of it
    covered by a certified analysis, a base of zero and a tier-C credit scaled to
    nothing, giving 0.00 and an insufficient verdict.

    PRD: "`requested_item_count` is the number of NQTL items whose `plan_year_id` is
    the request's plan year and whose `nqtl_type` appears in `requested_nqtl_types`,
    counted at this response and not carried over from the last one."

    Design: Corner/validations/responding_when_no_inventoried_item_matches_the_demand_rejected
    """
    scenario = _regulator_demanding_a_type_nobody_inventoried(api, officer_headers)
    api.respond_regulator_request(
        scenario.regulator_request_id,
        f.respond_payload(response_note="Nothing of the demanded type is inventoried."),
        scenario.sponsor_headers,
    )
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["status"]
        == PlanYearStatus.UNDER_REGULATOR_REVIEW
    )

    step_therapy = validate_success(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                scenario.plan_year_id,
                scenario.classification_id,
                nqtl_type=NqtlType.STEP_THERAPY,
                applied_to=AppliedTo.BOTH,
                description="Step therapy for outpatient office visits.",
            ),
            officer_headers,
        ),
        201,
    )
    assert step_therapy["status"] == NqtlItemStatus.INVENTORIED

    responded = validate_success(
        api.respond_regulator_request(
            scenario.regulator_request_id,
            f.respond_payload(response_note="Step therapy is now inventoried and produced."),
            scenario.sponsor_headers,
        )
    )
    assert responded["status"] == RegulatorRequestStatus.RESPONDED
    assert responded["requested_item_count"] == 1
    assert responded["covered_item_count"] == 0
    assert_score(responded["completeness_score"], 0.00, "completeness_score")
    assert responded["response_sufficient"] is False


# ═══ validations / responding_after_the_response_window_closed_rejected ══════════


def test_the_response_window_includes_its_own_endpoint_and_nothing_after_it(
    api, officer_headers, regulator_headers
):
    """Two identical dockets, one millisecond apart, land on opposite sides of the bound.

    Both requests were opened at the clock's start and both fall due thirty days
    later, at 2026-08-31.  Responding at exactly that instant is on time — the
    comparison is "at or before", not "before" — and scores the docket at 0.00 over
    one demanded and uncovered item.  A millisecond later the sibling docket is shut,
    and its refusal leaves it OPEN with no score at all.

    PRD: "The logical clock must stand at or before `response_due_at`, including any
    extension already granted, and a late response is refused with
    `ERR_RESPONSE_WINDOW_EXPIRED` (HTTP 409)."

    Design: Corner/validations/responding_after_the_response_window_closed_rejected
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        applied_to=AppliedTo.BOTH,
        description="Prior authorization for outpatient office visits.",
    )
    request_a = fx.open_regulator_request(
        api,
        scenario.plan_year_id,
        requested_nqtl_types=[NqtlType.PRIOR_AUTHORIZATION],
        request_reference="DOL-EBSA-2026-01001",
    )
    request_b = fx.open_regulator_request(
        api,
        scenario.plan_year_id,
        requested_nqtl_types=[NqtlType.PRIOR_AUTHORIZATION],
        request_reference="DOL-EBSA-2026-01002",
    )
    for request in (request_a, request_b):
        assert_instant_equals(
            request["response_due_at"], "2026-08-31T00:00:00.000Z", "response_due_at"
        )

    fx.advance_clock(api, "2026-08-31T00:00:00.000Z", regulator_headers)
    on_time = validate_success(
        api.respond_regulator_request(
            request_a["id"],
            f.respond_payload(response_note="Produced at the last permitted instant."),
            scenario.sponsor_headers,
        )
    )
    assert on_time["status"] == RegulatorRequestStatus.RESPONDED
    assert on_time["requested_item_count"] == 1
    assert on_time["covered_item_count"] == 0
    assert_score(on_time["completeness_score"], 0.00, "completeness_score")

    fx.advance_clock(api, "2026-08-31T00:00:00.001Z", regulator_headers)
    assert_error(
        api.respond_regulator_request(
            request_b["id"],
            f.respond_payload(response_note="One millisecond late."),
            scenario.sponsor_headers,
        ),
        ApiErrorId.RESPONSE_WINDOW_EXPIRED,
        409,
    )

    late = fx.read_regulator_request(api, request_b["id"])
    assert late["status"] == RegulatorRequestStatus.OPEN
    assert_is_none(late["completeness_score"], "completeness_score of the closed-out docket")
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["status"]
        == PlanYearStatus.UNDER_REGULATOR_REVIEW
    )


# ═══ validations / superseding_an_analysis_belonging_to_a_different_item_rejected ══


def test_a_sibling_items_draft_cannot_be_superseded_from_across_the_inventory(
    api, officer_headers
):
    """The named predecessor must document the same limitation, not merely be supersedable.

    The prior-authorisation draft is in DRAFT and would be a perfectly legal thing to
    supersede — from its own item.  Named from the concurrent-review item it is
    refused as an incoherent reference, and nothing is withdrawn, no analysis is
    written against the second item, and that item is untouched at INVENTORIED with
    its original version.  Dropping the one offending field lets the identical
    payload through.

    PRD: "When `supersedes_analysis_id` is supplied it must name an analysis for the
    same `nqtl_item_id`; pointing at an analysis belonging to a different item is
    rejected with `ERR_CROSS_PLAN_YEAR_REFERENCE`."

    Design: Corner/validations/superseding_an_analysis_belonging_to_a_different_item_rejected
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item_a = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        applied_to=AppliedTo.BOTH,
        description="Prior authorization for outpatient office visits.",
    )
    item_b = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        nqtl_type=NqtlType.CONCURRENT_REVIEW,
        applied_to=AppliedTo.BOTH,
        description="Concurrent review for outpatient office visits.",
    )
    analysis_a = fx.draft_analysis(
        api,
        item_a["id"],
        item_a["version"],
        scenario.sponsor_headers,
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.COMPARABLE,
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )

    assert_error(
        api.create_analysis(
            f.analysis_payload(
                item_b["id"],
                item_b["version"],
                supersedes_analysis_id=analysis_a["id"],
                factor_count=2,
                evidentiary_standard_count=1,
                stringency_written_finding=StringencyFinding.COMPARABLE,
                stringency_operation_finding=StringencyFinding.COMPARABLE,
            ),
            scenario.sponsor_headers,
        ),
        ApiErrorId.CROSS_PLAN_YEAR_REFERENCE,
        409,
    )

    assert fx.read_analysis(api, analysis_a["id"])["status"] == AnalysisStatus.DRAFT
    assert_empty_collection(
        api.list_analyses({"nqtl_item_id": item_b["id"]}, scenario.sponsor_headers)
    )
    unchanged = fx.read_item(api, item_b["id"])
    assert unchanged["status"] == NqtlItemStatus.INVENTORIED
    assert unchanged["version"] == item_b["version"]

    accepted = validate_success(
        api.create_analysis(
            f.analysis_payload(
                item_b["id"],
                item_b["version"],
                factor_count=2,
                evidentiary_standard_count=1,
                stringency_written_finding=StringencyFinding.COMPARABLE,
                stringency_operation_finding=StringencyFinding.COMPARABLE,
            ),
            scenario.sponsor_headers,
        ),
        201,
    )
    assert accepted["status"] == AnalysisStatus.DRAFT
    assert_is_none(accepted["supersedes_analysis_id"], "supersedes_analysis_id")
