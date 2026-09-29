"""
Who may act, and who may only watch.

Three different refusals live here and they are not interchangeable: a role outside
an endpoint's permitted set is 403 `ERR_UNAUTHORIZED`, a right-role caller acting on
someone else's row is a 403 ownership code, and a right-role caller barred by
segregation of duties is a 409. Each test pairs the denial with the identical call
from a caller who is allowed to make it, so a blanket lockout cannot pass.
"""

from test_helpers.api_errors import (
    ERR_NOT_CASE_OFFICER,
    ERR_NOT_PLACEMENT_PARTICIPANT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_int_field,
    assert_ledger_identity,
    assert_match_breakdown,
    assert_money_cents,
    assert_one_decimal_place,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    CASE_ACTIVE,
    CASE_DISCHARGED,
    CATEGORY_TRANSIT_PASS,
    DECISION_APPROVED,
    DOC_BIRTH_CERTIFICATE,
    DOC_SSN_CARD,
    DOC_STATE_ID,
    DOC_WORK_HISTORY,
    EMPLOYMENT_ACTIVE,
    EMPLOYMENT_OFFERED,
    FUNDING_POSTURE_OPEN,
    OFFER_RESPONSE_ACCEPTED,
    PARTNERSHIP_PROSPECT,
    RECORD_DRUG_OFFENSE,
    RELEASE_PLAN_APPROVED,
    RELEASE_PLAN_DRAFT,
    REQUEST_APPROVED,
    REQUEST_DISBURSED,
    REQUEST_SUBMITTED,
    ROLE_PROGRAM_DIRECTOR,
    STAGE_PLACED,
    STAGE_POST_RELEASE,
    STAGE_PRE_RELEASE,
    STAGE_RELEASE_READY,
    WORK_AUTH_APPROVED,
    WORK_AUTH_NOT_REQUESTED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    CASE_MANAGER_ID,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
    PROGRAM_DIRECTOR_2,
    PROGRAM_DIRECTOR_2_ID,
    PROGRAM_DIRECTOR_ID,
    SUPERVISION_OFFICER,
    SUPERVISION_OFFICER_2,
    headers_for_role,
    participant_headers,
)

TRANSIT_LINE = "Monthly transit pass"


def _submitted_transit_request(api, build):
    """A 4,000-cent TRANSIT_PASS request submitted by cm-1 and still SUBMITTED."""
    grant = build.grant(
        authorized_cents=100000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    participant = build.participant_zero_barrier_draft(
        record_categories=[RECORD_DRUG_OFFENSE]
    )
    request = build.support_request(
        participant["id"],
        grant["id"],
        [f.line_item(TRANSIT_LINE, 4000)],
        category=CATEGORY_TRANSIT_PASS,
    )
    assert request["status"] == REQUEST_SUBMITTED
    assert request["submitted_by_user_id"] == CASE_MANAGER_ID
    assert_money_cents(request, "requested_cents", 4000)
    assert_money_cents(request, "admin_fee_cents", 0)
    assert_money_cents(request, "total_charge_cents", 4000)
    return grant, participant, request


def test_a_case_manager_cannot_approve_a_release_plan(api, build):
    """
    The case manager authors the plan and still may not bless it: the denial writes
    nothing, and the identical call from the director then carries the participant across
    the readiness line, so the refusal was about the role and nothing else.

    PRD section 2.5: "**Role authorisation** — the caller's role is outside the
    endpoint's permitted set, yielding `ERR_UNAUTHORIZED` (403)."

    PRD section 3.2: "Approval belongs to the `ProgramDirector` alone and carries no
    payload. It sets `release_plan_status` to `APPROVED` and then re-evaluates release
    readiness, which is the moment a fully documented, fully assessed, unsuspended
    participant crosses `PRE_RELEASE → RELEASE_READY`."

    Design: Corner/rbac/a_case_manager_cannot_approve_a_release_plan
    """
    participant = build.participant_assessed()
    build.verify_documents(
        participant["id"],
        [DOC_STATE_ID, DOC_SSN_CARD, DOC_BIRTH_CERTIFICATE, DOC_WORK_HISTORY],
    )
    drafted = build.release_plan_draft(participant["id"])
    assert drafted["release_plan_status"] == RELEASE_PLAN_DRAFT
    assert_one_decimal_place(drafted, "doc_completeness_pct", 80.0)

    refused = api.approve_release_plan(participant["id"], CASE_MANAGER)
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    untouched = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert untouched["release_plan_status"] == RELEASE_PLAN_DRAFT
    assert untouched["stage"] == STAGE_PRE_RELEASE

    approved = validate_unpaginated(
        api.approve_release_plan(participant["id"], PROGRAM_DIRECTOR)
    )
    assert approved["release_plan_status"] == RELEASE_PLAN_APPROVED
    assert approved["stage"] == STAGE_RELEASE_READY


def test_an_employer_liaison_cannot_create_a_participant(api, build):
    """
    The denial is per operation rather than a session-wide lockout: the same liaison who
    may not open an intake record goes on to register an employer in the very next call,
    and the participant collection is left empty.

    PRD section 2.1: "Authorisation is the second gate. Each endpoint declares the set
    of roles permitted to invoke it, listed in the endpoint table of section 4. A caller
    whose `X-User-Role` is outside that set is refused with `ERR_UNAUTHORIZED` (HTTP
    403). This check precedes request-shape validation, so a wrong-role caller who also
    sends a malformed body receives 403 and not 422."

    PRD section 2.1: "An `EmployerLiaison` develops employer partnerships, posts job
    openings, records separations, and drives fidelity bonding."

    Design: Corner/rbac/an_employer_liaison_cannot_create_a_participant
    """
    refused = api.create_participant(
        f.participant_payload(required_document_types=[DOC_STATE_ID, DOC_SSN_CARD]),
        EMPLOYER_LIAISON,
    )
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    rows, meta = validate_paginated(api.list_participants(CASE_MANAGER))
    assert meta["total_count"] == 0
    assert rows == []

    partnership = validate_unpaginated(
        api.create_partnership(f.partnership_payload(), EMPLOYER_LIAISON), 201
    )
    assert partnership["status"] == PARTNERSHIP_PROSPECT

    rows, meta = validate_paginated(api.list_partnerships(EMPLOYER_LIAISON))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == partnership["id"]


def test_a_funder_analyst_cannot_read_the_match_preview(api, build):
    """
    The analyst reads nearly everything, so the one scoring read they are shut out of
    has to be enforced by name: the preview refuses them while the opening underneath it
    stays readable, and the case manager gets the whole 75-point breakdown.

    PRD section 2.1: "Read access is broad but not universal. Every retrieval endpoint
    is open to all six roles except three: the grant ledger read and the funder outcome
    report are restricted to `ProgramDirector` and `FunderAnalyst`, and the match-preview
    scoring read is restricted to `CaseManager`, `EmployerLiaison`, and
    `ProgramDirector`."

    Design: Corner/rbac/a_funder_analyst_cannot_read_the_match_preview
    """
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])
    participant = build.participant_released()

    refused = api.get_match_preview(
        opening["id"], FUNDER_ANALYST, {"participant_id": participant["id"]}
    )
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    preview = validate_unpaginated(
        api.get_match_preview(
            opening["id"], CASE_MANAGER, {"participant_id": participant["id"]}
        )
    )
    assert preview["eligible"] is True
    assert preview["blocking_error_id"] is None
    assert_int_field(preview, "match_score", 75)
    assert_match_breakdown(preview["match_breakdown"], 28, 20, 7, 15, 0, 5)

    readable = validate_unpaginated(api.get_job_opening(opening["id"], FUNDER_ANALYST))
    assert readable["id"] == opening["id"]


def test_a_supervision_officer_cannot_act_on_another_officers_case(api, build):
    """
    Both callers carry the same role, so only the identifier on the case can tell them
    apart, and the rule covers both of the case's action endpoints. Neither denial may
    open the work window; the owning officer's identical call does.

    PRD section 2.1: "A `SupervisionOfficer` may act only on a supervision case whose
    `officer_user_id` equals their own `X-User-ID`; acting on another officer's case is
    refused with `ERR_NOT_CASE_OFFICER` (HTTP 403), and this applies to both
    supervision-case action capabilities — the lifecycle-status transition and the
    work-authorization decision."

    Design: Corner/rbac/a_supervision_officer_cannot_act_on_another_officers_case
    """
    participant = build.participant_released()
    case = build.supervision_case_active(participant["id"], SUPERVISION_OFFICER)
    assert case["status"] == CASE_ACTIVE
    assert case["work_authorization_status"] == WORK_AUTH_NOT_REQUESTED

    validate_error(
        api.decide_work_authorization(
            case["id"],
            f.work_authorization_payload(DECISION_APPROVED, 480, 1020),
            SUPERVISION_OFFICER_2,
        ),
        ERR_NOT_CASE_OFFICER,
        403,
    )
    validate_error(
        api.set_supervision_case_status(
            case["id"],
            f.case_status_payload(CASE_DISCHARGED),
            SUPERVISION_OFFICER_2,
        ),
        ERR_NOT_CASE_OFFICER,
        403,
    )

    untouched = validate_unpaginated(
        api.get_supervision_case(case["id"], SUPERVISION_OFFICER)
    )
    assert untouched["status"] == CASE_ACTIVE
    assert untouched["work_authorization_status"] == WORK_AUTH_NOT_REQUESTED

    authorized = validate_unpaginated(
        api.decide_work_authorization(
            case["id"],
            f.work_authorization_payload(DECISION_APPROVED, 480, 1020),
            SUPERVISION_OFFICER,
        )
    )
    assert authorized["work_authorization_status"] == WORK_AUTH_APPROVED
    assert_int_field(authorized, "approved_window_start_minute", 480)
    assert_int_field(authorized, "approved_window_end_minute", 1020)


def test_a_participant_cannot_answer_another_participants_offer(api, build):
    """
    Both callers are participants in good standing, so the identifier on the placement is
    the only thing separating them, and none of acceptance's five side effects may fire
    for the stranger: the seat stays offered, the employer's headcount stays at zero, and
    the wrong caller stays unplaced.

    PRD section 3.6: "Only the participant may answer their own offer, by supplying a
    `response` of either `ACCEPTED` or `DECLINED`; a caller whose `X-User-ID` does not
    equal the placement's `participant_id` is refused with
    `ERR_NOT_PLACEMENT_PARTICIPANT`."

    Design: Corner/rbac/a_participant_cannot_answer_another_participants_offer
    """
    grant = build.grant(
        authorized_cents=30000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    owner = build.participant_released()
    build.case_authorized(owner["id"], 480, 1020)
    placement = build.placement_offered(owner["id"], opening["id"], grant["id"])
    stranger = build.participant_released(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )

    refused = api.respond_to_offer(
        placement["id"],
        f.offer_response_payload(OFFER_RESPONSE_ACCEPTED),
        participant_headers(stranger["id"]),
    )
    validate_error(refused, ERR_NOT_PLACEMENT_PARTICIPANT, 403)

    untouched = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert untouched["employment_status"] == EMPLOYMENT_OFFERED

    employer = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(employer, "active_placement_count", 0)

    unplaced = validate_unpaginated(api.get_participant(stranger["id"], CASE_MANAGER))
    assert unplaced["stage"] == STAGE_POST_RELEASE

    accepted = validate_unpaginated(
        api.respond_to_offer(
            placement["id"],
            f.offer_response_payload(OFFER_RESPONSE_ACCEPTED),
            participant_headers(owner["id"]),
        )
    )
    assert accepted["employment_status"] == EMPLOYMENT_ACTIVE

    placed = validate_unpaginated(api.get_participant(owner["id"], CASE_MANAGER))
    assert placed["stage"] == STAGE_PLACED


def test_the_director_who_submitted_the_request_cannot_review_it(api, build):
    """
    Identifiers are opaque, so the same person can appear behind two roles: a director
    presenting the submitter's identifier passes the role gate and is stopped by the
    duties control instead, at 409 rather than 403, and no money is committed until a
    different director signs.

    PRD section 2.1: "Segregation of duties then governs supportive-services money: the
    `ProgramDirector` whose `X-User-ID` equals a support request's
    `submitted_by_user_id` may not review that request, and the director whose
    `X-User-ID` equals its `reviewed_by_user_id` may not settle it. Either violation is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    PRD section 3.8: "the request moves `SUBMITTED → APPROVED`: `reviewed_by_user_id` is
    recorded, the grant's `committed_cents` rises by `total_charge_cents`, and the ledger
    re-runs, lowering `available_cents` and possibly flipping `funding_posture` from
    `OPEN` to `RESTRICTED` or to `EXHAUSTED`."

    Design: Corner/rbac/the_director_who_submitted_the_request_cannot_review_it
    """
    grant, _participant, request = _submitted_transit_request(api, build)

    refused = api.review_support_request(
        request["id"],
        f.review_payload(DECISION_APPROVED),
        headers_for_role(ROLE_PROGRAM_DIRECTOR, CASE_MANAGER_ID),
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 409)

    untouched = validate_unpaginated(
        api.get_support_request(request["id"], PROGRAM_DIRECTOR)
    )
    assert untouched["status"] == REQUEST_SUBMITTED
    assert untouched["reviewed_by_user_id"] is None

    before = validate_unpaginated(api.get_grant_ledger(grant["id"], PROGRAM_DIRECTOR))
    assert_money_cents(before, "committed_cents", 0)
    assert_money_cents(before, "available_cents", 100000)
    assert_ledger_identity(before)

    reviewed = validate_unpaginated(
        api.review_support_request(
            request["id"], f.review_payload(DECISION_APPROVED), PROGRAM_DIRECTOR
        )
    )
    assert reviewed["status"] == REQUEST_APPROVED
    assert reviewed["reviewed_by_user_id"] == PROGRAM_DIRECTOR_ID

    after = validate_unpaginated(api.get_grant_ledger(grant["id"], PROGRAM_DIRECTOR))
    assert_money_cents(after, "committed_cents", 4000)
    assert_money_cents(after, "available_cents", 96000)
    assert_ledger_identity(after)


def test_the_director_who_reviewed_the_request_cannot_settle_it(api, build):
    """
    The second half of the control compares against a different column, so guarding only
    the submitter is not enough. Until a second director signs, the money stays committed
    and undisbursed; the payout then moves it across without touching what is available.

    PRD section 3.8: "Settlement also belongs to the `ProgramDirector`, carries a
    `to_status` and an optional `settlement_note`, and is barred to whoever reviewed the
    request."

    PRD section 3.8: "`APPROVED → DISBURSED` pays the money out: `settled_by_user_id` and
    `settlement_note` are recorded, `committed_cents` falls by `total_charge_cents` and
    `disbursed_cents` rises by the same amount, so `available_cents` and
    `funding_posture` are unchanged in value by this move."

    Design: Corner/rbac/the_director_who_reviewed_the_request_cannot_settle_it
    """
    grant, _participant, request = _submitted_transit_request(api, build)
    approved = validate_unpaginated(
        api.review_support_request(
            request["id"], f.review_payload(DECISION_APPROVED), PROGRAM_DIRECTOR
        )
    )
    assert approved["status"] == REQUEST_APPROVED
    assert approved["reviewed_by_user_id"] == PROGRAM_DIRECTOR_ID

    refused = api.settle_support_request(
        request["id"], f.settle_payload(REQUEST_DISBURSED), PROGRAM_DIRECTOR
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 409)

    untouched = validate_unpaginated(
        api.get_support_request(request["id"], PROGRAM_DIRECTOR)
    )
    assert untouched["status"] == REQUEST_APPROVED
    assert untouched["settled_by_user_id"] is None

    before = validate_unpaginated(api.get_grant_ledger(grant["id"], PROGRAM_DIRECTOR))
    assert_money_cents(before, "committed_cents", 4000)
    assert_money_cents(before, "disbursed_cents", 0)
    assert_money_cents(before, "available_cents", 96000)
    assert_ledger_identity(before)

    settled = validate_unpaginated(
        api.settle_support_request(
            request["id"], f.settle_payload(REQUEST_DISBURSED), PROGRAM_DIRECTOR_2
        )
    )
    assert settled["status"] == REQUEST_DISBURSED
    assert settled["settled_by_user_id"] == PROGRAM_DIRECTOR_2_ID

    after = validate_unpaginated(api.get_grant_ledger(grant["id"], PROGRAM_DIRECTOR))
    assert_money_cents(after, "committed_cents", 0)
    assert_money_cents(after, "disbursed_cents", 4000)
    assert_money_cents(after, "available_cents", 96000)
    assert after["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_ledger_identity(after)


def test_the_director_and_the_analyst_both_read_the_grant_ledger(api, build):
    """
    The ledger has a guest list of exactly two roles. Both of them must see the same
    figures down to the last field, and the case manager who submitted the request is not
    on it — so an implementation that simply opens every read to every role fails here.

    PRD section 3.8: "A computed ledger read exposes the money for one grant, restricted
    to `ProgramDirector` and `FunderAnalyst`: it reports `grant_id`, `authorized_cents`,
    `committed_cents`, `disbursed_cents`, `available_cents`, `restricted_floor_cents`
    (the fifteen-percent floor described above), `funding_posture`,
    `open_request_count`, and `deferred_request_count`, the last being the count of
    requests on the grant whose `status` is `DEFERRED`, which is reported by this read
    and never persisted on the grant row."

    Design: Corner/rbac/the_director_and_the_analyst_both_read_the_grant_ledger
    """
    grant, _participant, request = _submitted_transit_request(api, build)
    approved = validate_unpaginated(
        api.review_support_request(
            request["id"], f.review_payload(DECISION_APPROVED), PROGRAM_DIRECTOR
        )
    )
    assert approved["status"] == REQUEST_APPROVED

    by_analyst = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(by_analyst, "committed_cents", 4000)
    assert_money_cents(by_analyst, "available_cents", 96000)
    assert by_analyst["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_ledger_identity(by_analyst)

    by_director = validate_unpaginated(
        api.get_grant_ledger(grant["id"], PROGRAM_DIRECTOR)
    )
    assert_money_cents(by_director, "committed_cents", 4000)
    assert_money_cents(by_director, "available_cents", 96000)
    assert by_director["funding_posture"] == FUNDING_POSTURE_OPEN
    assert by_director == by_analyst

    refused = api.get_grant_ledger(grant["id"], CASE_MANAGER)
    validate_error(refused, ERR_UNAUTHORIZED, 403)
