"""
Error identifiers that only distinguish themselves from one another.

A shared generic 404 or a single shared invalid-state code would satisfy a naive
reading of every endpoint in isolation, so the tests here address ten collections
with foreign identifiers and drive nine state machines into their own dead ends,
then insist the codes come back pairwise distinct and nothing was written.
"""

from test_helpers.api_errors import (
    ERR_BOND_ALREADY_RECORDED,
    ERR_BONDING_CLAIM_NOT_ELIGIBLE,
    ERR_BONDING_INVALID_STATE,
    ERR_CATEGORY_NOT_FUNDABLE,
    ERR_DOCUMENT_NOT_REQUIRED,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_ENROLLMENT_INVALID_STATE,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_GRANT_EXHAUSTED,
    ERR_GRANT_NOT_FOUND,
    ERR_JOB_OPENING_NOT_FOUND,
    ERR_MILESTONE_ALREADY_RECORDED,
    ERR_PARTICIPANT_HAS_ACTIVE_PLACEMENT,
    ERR_PARTICIPANT_INVALID_STATE,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_PARTNERSHIP_CAPACITY_REACHED,
    ERR_PARTNERSHIP_HAS_ACTIVE_PLACEMENTS,
    ERR_PARTNERSHIP_INVALID_STATE,
    ERR_PARTNERSHIP_NOT_FOUND,
    ERR_PLACEMENT_INVALID_STATE,
    ERR_PLACEMENT_NOT_FOUND,
    ERR_SESSION_INVALID_STATE,
    ERR_SESSION_NOT_FOUND,
    ERR_SUPERVISION_CASE_INVALID_STATE,
    ERR_SUPERVISION_CASE_NOT_FOUND,
    ERR_SUPPORT_REQUEST_INVALID_STATE,
    ERR_SUPPORT_REQUEST_NOT_FOUND,
    ERR_WORK_SHIFT_INVALID_STATE,
    ERR_WORK_SHIFT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_array_equals,
    assert_int_field,
    assert_ledger_identity,
    assert_money_cents,
    assert_one_decimal_place,
    assert_opening_seat_identity,
    assert_session_seat_identity,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    BONDING_BONDED,
    BONDING_CLAIMED,
    BONDING_NONE,
    BONDING_REQUESTED,
    CASE_ACTIVE,
    CATEGORY_ID_FEE,
    CATEGORY_TOOLS,
    CATEGORY_TRANSIT_PASS,
    DECISION_DENIED,
    DOC_BIRTH_CERTIFICATE,
    DOC_DD214,
    DOC_SSN_CARD,
    DOC_STATE_ID,
    DOC_WORK_HISTORY,
    EMPLOYMENT_ACTIVE,
    EMPLOYMENT_OFFERED,
    EMPLOYMENT_SEPARATED,
    ENROLLMENT_ATTENDED,
    ENROLLMENT_ENROLLED,
    EXIT_PROGRAM_COMPLETE,
    FUNDING_POSTURE_EXHAUSTED,
    FUNDING_POSTURE_OPEN,
    OFFER_RESPONSE_ACCEPTED,
    OPENING_FILLED,
    OPENING_OPEN,
    PARTNERSHIP_ACTIVE,
    PARTNERSHIP_ENGAGED,
    PARTNERSHIP_TERMINATED,
    POSTURE_OPEN,
    RECORD_DRUG_OFFENSE,
    REQUEST_SUBMITTED,
    RETENTION_RETAINED,
    RETENTION_SEPARATED,
    SESSION_CANCELLED,
    SESSION_HELD,
    SESSION_SCHEDULED,
    SESSION_TYPE_DISCLOSURE_COACHING,
    SESSION_TYPE_INTERVIEW_PRACTICE,
    SEPARATION_LAYOFF,
    SHIFT_WORKED,
    STAGE_POST_RELEASE,
    STAGE_PRE_RELEASE,
    STAGE_RETENTION,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
    SUPERVISION_OFFICER,
    participant_headers,
)


def _live_placement(api, build, **partnership_overrides):
    """A grant, an ACTIVE partnership, an opening and one ACTIVE placement on it."""
    grant = build.grant(
        authorized_cents=30000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    partnership = build.partnership_active(**partnership_overrides)
    opening = build.job_opening(partnership["id"])
    participant = build.participant_released()
    case = build.case_authorized(participant["id"], 480, 1020)
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])
    return grant, partnership, opening, participant, case, placement


def test_every_collection_reports_its_own_not_found_code(api, build):
    """
    Ten collections, ten codes: each read is handed a genuine live identifier that
    belongs to a different collection, so the row really is absent from the collection
    addressed, and the answer must name that collection rather than 404 generically.

    PRD section 2.5: "**Path existence** — an identifier embedded in the URL path
    matches no row of the collection it addresses, yielding that collection's own
    not-found code with HTTP 404: `ERR_PARTICIPANT_NOT_FOUND`,
    `ERR_SUPERVISION_CASE_NOT_FOUND`, `ERR_PARTNERSHIP_NOT_FOUND`,
    `ERR_JOB_OPENING_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`,
    `ERR_WORK_SHIFT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`,
    `ERR_SUPPORT_REQUEST_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, or
    `ERR_ENROLLMENT_NOT_FOUND`."

    Design: Corner/errors/every_not_found_code_is_reachable_by_addressing_the_wrong_collection
    """
    participant = build.participant()
    grant = build.grant()
    foreign = participant["id"]

    probes = [
        (api.get_participant(grant["id"], CASE_MANAGER), ERR_PARTICIPANT_NOT_FOUND),
        (
            api.get_supervision_case(foreign, CASE_MANAGER),
            ERR_SUPERVISION_CASE_NOT_FOUND,
        ),
        (api.get_partnership(foreign, CASE_MANAGER), ERR_PARTNERSHIP_NOT_FOUND),
        (api.get_job_opening(foreign, CASE_MANAGER), ERR_JOB_OPENING_NOT_FOUND),
        (api.get_placement(foreign, CASE_MANAGER), ERR_PLACEMENT_NOT_FOUND),
        (api.get_work_shift(foreign, CASE_MANAGER), ERR_WORK_SHIFT_NOT_FOUND),
        (api.get_grant(foreign, CASE_MANAGER), ERR_GRANT_NOT_FOUND),
        (api.get_support_request(foreign, CASE_MANAGER), ERR_SUPPORT_REQUEST_NOT_FOUND),
        (api.get_readiness_session(foreign, CASE_MANAGER), ERR_SESSION_NOT_FOUND),
        (api.get_enrollment(foreign, CASE_MANAGER), ERR_ENROLLMENT_NOT_FOUND),
    ]

    seen = []
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 404)
        seen.append(response.json()["data"]["error_id"])

    assert len(set(seen)) == 10, f"the ten not-found codes must be distinct: {seen}"


def test_each_state_machine_reports_its_own_invalid_state_code(api, build, clock):
    """
    Nine dimensions are each driven into a transition they do not declare — a
    re-application, a walk back up a ladder, a jump over an intermediate state, and
    four exits from terminal states — and every one answers with its own code. The
    placement contributes two of the nine, because its employment and bonding
    dimensions are separate graphs reached through the same collection.

    PRD section 2.8: "A request that names a target state is legal only when the pair
    formed by the entity's current value in that dimension and the requested target is
    a declared transition of that dimension's graph. Anything else — a transition out
    of a terminal state, a transition that skips an intermediate state, or a
    re-application of a transition already taken — is refused at band eight with the
    addressed entity's own invalid-state code and HTTP 409:
    `ERR_PARTICIPANT_INVALID_STATE`, `ERR_SUPERVISION_CASE_INVALID_STATE`,
    `ERR_PARTNERSHIP_INVALID_STATE`, `ERR_PLACEMENT_INVALID_STATE`,
    `ERR_WORK_SHIFT_INVALID_STATE`, `ERR_SUPPORT_REQUEST_INVALID_STATE`,
    `ERR_SESSION_INVALID_STATE`, `ERR_ENROLLMENT_INVALID_STATE`, or — for the
    placement bonding dimension specifically — `ERR_BONDING_INVALID_STATE`."

    Design: Corner/errors/each_entity_reports_its_own_invalid_state_code
    """
    grant, partnership, opening, participant, case, placement = _live_placement(
        api, build
    )
    shift = build.work_shift(
        placement["id"], "2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z"
    )
    session = build.readiness_session(
        session_type=SESSION_TYPE_DISCLOSURE_COACHING,
        starts_at="2026-08-02T13:00:00.000Z",
        ends_at="2026-08-02T15:00:00.000Z",
        seat_capacity=3,
    )
    enrollment = build.enrollment(session["id"], participant["id"])
    request = build.support_request_approved(
        participant["id"],
        grant["id"],
        [f.line_item("Monthly transit pass", 4000)],
        category=CATEGORY_TRANSIT_PASS,
    )

    clock.set("2026-08-03T18:00:00.000Z")
    validate_unpaginated(
        api.set_work_shift_status(
            shift["id"], f.shift_status_payload(SHIFT_WORKED), CASE_MANAGER
        )
    )
    validate_unpaginated(
        api.set_session_status(
            session["id"], f.session_status_payload(SESSION_HELD), CASE_MANAGER
        )
    )

    probes = [
        (
            api.approve_release_plan(participant["id"], PROGRAM_DIRECTOR),
            ERR_PARTICIPANT_INVALID_STATE,
        ),
        (
            api.set_supervision_case_status(
                case["id"], f.case_status_payload(CASE_ACTIVE), SUPERVISION_OFFICER
            ),
            ERR_SUPERVISION_CASE_INVALID_STATE,
        ),
        (
            api.set_partnership_status(
                partnership["id"],
                f.partnership_status_payload(PARTNERSHIP_ENGAGED),
                EMPLOYER_LIAISON,
            ),
            ERR_PARTNERSHIP_INVALID_STATE,
        ),
        (
            api.respond_to_offer(
                placement["id"],
                f.offer_response_payload(OFFER_RESPONSE_ACCEPTED),
                participant_headers(participant["id"]),
            ),
            ERR_PLACEMENT_INVALID_STATE,
        ),
        (
            api.drive_placement_bonding(
                placement["id"],
                f.placement_bonding_payload(BONDING_BONDED),
                EMPLOYER_LIAISON,
            ),
            ERR_BONDING_INVALID_STATE,
        ),
        (
            api.set_work_shift_status(
                shift["id"], f.shift_status_payload(SHIFT_WORKED), CASE_MANAGER
            ),
            ERR_WORK_SHIFT_INVALID_STATE,
        ),
        (
            api.review_support_request(
                request["id"], f.review_payload(DECISION_DENIED), PROGRAM_DIRECTOR
            ),
            ERR_SUPPORT_REQUEST_INVALID_STATE,
        ),
        (
            api.set_session_status(
                session["id"], f.session_status_payload(SESSION_CANCELLED), CASE_MANAGER
            ),
            ERR_SESSION_INVALID_STATE,
        ),
        (
            api.set_enrollment_status(
                enrollment["id"],
                f.enrollment_status_payload(ENROLLMENT_ATTENDED),
                CASE_MANAGER,
            ),
            ERR_ENROLLMENT_INVALID_STATE,
        ),
    ]

    seen = []
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 409)
        seen.append(response.json()["data"]["error_id"])

    assert len(set(seen)) == 9, f"the nine invalid-state codes must be distinct: {seen}"

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert stored["employment_status"] == EMPLOYMENT_ACTIVE
    assert stored["bonding_status"] == BONDING_NONE


def test_a_bond_claim_after_a_layoff_separation_is_not_eligible(api, build, clock):
    """
    Both structural guards on the claim edge pass — the bond really is `BONDED` and
    the placement really is `SEPARATED` — so the only thing left to refuse on is the
    reason for the separation, and the refusal leaves the coverage in force rather
    than lapsing it.

    PRD section 3.6: "`BONDED → CLAIMED` files a claim and additionally requires
    `separation_reason` to be `TERMINATED_FOR_CAUSE`, since a bond answers for
    employee dishonesty and not for a layoff or a voluntary quit — a claim attempted
    on any other separation reason is refused with `ERR_BONDING_CLAIM_NOT_ELIGIBLE`"

    Design: Corner/errors/a_bond_claim_after_a_layoff_separation_is_not_eligible
    """
    grant, partnership, opening, participant, case, placement = _live_placement(
        api, build
    )

    for target in (BONDING_REQUESTED, BONDING_BONDED):
        validate_unpaginated(
            api.drive_placement_bonding(
                placement["id"], f.placement_bonding_payload(target), EMPLOYER_LIAISON
            )
        )

    clock.set("2026-08-04T09:00:00.000Z")
    separated = validate_unpaginated(
        api.separate_placement(
            placement["id"],
            f.separation_payload(SEPARATION_LAYOFF, "2026-08-03"),
            EMPLOYER_LIAISON,
        )
    )
    assert separated["employment_status"] == EMPLOYMENT_SEPARATED
    assert separated["bonding_status"] == BONDING_BONDED

    refused = api.drive_placement_bonding(
        placement["id"], f.placement_bonding_payload(BONDING_CLAIMED), EMPLOYER_LIAISON
    )
    validate_error(refused, ERR_BONDING_CLAIM_NOT_ELIGIBLE, 409)

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert stored["bonding_status"] == BONDING_BONDED
    assert stored["employment_status"] == EMPLOYMENT_SEPARATED

    stored_partnership = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_money_cents(stored_partnership, "bond_coverage_cents", 500000)
    assert_int_field(stored_partnership, "active_placement_count", 0)


def test_a_live_placement_blocks_termination_exit_and_a_second_bond_agreement(
    api, build, clock
):
    """
    One `ACTIVE` placement bars three unrelated writes at the same band, and each
    names its own condition: the employer cannot be drained, the participant's case
    cannot be closed, and the bond already on file cannot be replaced. The exit is
    attempted from `RETENTION`, one of the four stages exit is legal from, so the live
    placement is the only bar standing in its way.

    PRD section 3.4: "Termination is reachable from both `ACTIVE` and `SUSPENDED`, is
    terminal, and requires the partnership to be drained first: `active_placement_count`
    must be 0, and a termination attempted while any placement on any of the
    partnership's openings is still `ACTIVE` is refused with
    `ERR_PARTNERSHIP_HAS_ACTIVE_PLACEMENTS`."

    PRD section 3.9: "Exit is legal from `PRE_RELEASE`, `RELEASE_READY`,
    `POST_RELEASE`, and `RETENTION`, and in every case requires that no placement of
    this participant has `employment_status` of `ACTIVE`; if one does, the exit is
    refused with `ERR_PARTICIPANT_HAS_ACTIVE_PLACEMENT`"

    PRD section 3.4: "It is refused with `ERR_PARTNERSHIP_INVALID_STATE` when the
    partnership's `status` is `SUSPENDED` or `TERMINATED`, and refused with
    `ERR_BOND_ALREADY_RECORDED` when `fidelity_bond_enabled` is already true."

    Design: Corner/errors/a_live_placement_blocks_termination_exit_and_a_second_bond_agreement
    """
    grant, partnership, opening, participant, case, placement = _live_placement(
        api, build
    )
    clock.set("2026-09-05T09:00:00.000Z")
    validate_unpaginated(
        api.record_retention_check(
            placement["id"],
            f.retention_check_payload(30, RETENTION_RETAINED),
            CASE_MANAGER,
        )
    )

    validate_error(
        api.set_partnership_status(
            partnership["id"],
            f.partnership_status_payload(PARTNERSHIP_TERMINATED),
            EMPLOYER_LIAISON,
        ),
        ERR_PARTNERSHIP_HAS_ACTIVE_PLACEMENTS,
        409,
    )
    validate_error(
        api.exit_participant(
            participant["id"],
            f.exit_payload(EXIT_PROGRAM_COMPLETE, "2026-09-05"),
            PROGRAM_DIRECTOR,
        ),
        ERR_PARTICIPANT_HAS_ACTIVE_PLACEMENT,
        409,
    )
    validate_error(
        api.record_bonding_agreement(
            partnership["id"],
            f.bonding_agreement_payload(750000, "2026-08-01"),
            EMPLOYER_LIAISON,
        ),
        ERR_BOND_ALREADY_RECORDED,
        409,
    )

    stored_partnership = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert stored_partnership["status"] == PARTNERSHIP_ACTIVE
    assert stored_partnership["fidelity_bond_enabled"] is True
    assert_money_cents(stored_partnership, "bond_coverage_cents", 500000)
    assert_int_field(stored_partnership, "active_placement_count", 1)

    stored_participant = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert stored_participant["stage"] == STAGE_RETENTION
    assert stored_participant["engagement_posture"] == POSTURE_OPEN
    assert stored_participant["exit_reason"] is None

    stored_opening = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert stored_opening["status"] == OPENING_OPEN
    assert_opening_seat_identity(stored_opening)


def test_recording_the_same_retention_milestone_twice_is_rejected(api, build, clock):
    """
    Uniqueness is per milestone, not per placement: the thirty-day slot is spent while
    the sixty-day slot on the same row is still empty, and the rejected second outcome
    must not overwrite the one already stored.

    PRD section 3.9: "Each milestone may be recorded once only: when the placement
    already carries an outcome for the supplied `milestone_days`, the check is refused
    with `ERR_MILESTONE_ALREADY_RECORDED`, and the elapse test is applied before the
    already-recorded test."

    PRD section 3.9: "When `milestone_days` is 30 and `outcome` is `RETAINED` and the
    checked placement is still `ACTIVE`, the participant's `stage` advances `PLACED →
    RETENTION`; a thirty-day check with any other `outcome`, or a sixty- or ninety-day
    check, moves `stage` not at all."

    Design: Corner/errors/recording_the_same_retention_milestone_twice_is_rejected
    """
    grant, partnership, opening, participant, case, placement = _live_placement(
        api, build
    )
    clock.set("2026-09-05T09:00:00.000Z")
    first = validate_unpaginated(
        api.record_retention_check(
            placement["id"],
            f.retention_check_payload(30, RETENTION_RETAINED),
            CASE_MANAGER,
        )
    )
    assert first["retention_30_outcome"] == RETENTION_RETAINED
    assert first["retention_60_outcome"] is None

    refused = api.record_retention_check(
        placement["id"],
        f.retention_check_payload(30, RETENTION_SEPARATED),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_MILESTONE_ALREADY_RECORDED, 409)

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert stored["retention_30_outcome"] == RETENTION_RETAINED
    assert stored["retention_60_outcome"] is None
    assert stored["retention_90_outcome"] is None
    assert stored["employment_status"] == EMPLOYMENT_ACTIVE

    stored_participant = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert stored_participant["stage"] == STAGE_RETENTION


def test_a_category_outside_the_grants_allow_list_is_rejected(api, build):
    """
    `TOOLS` is a perfectly legal support category in the enum, so the refusal can only
    come from this grant's own allow list — and the very next request, in a category
    the grant does fund, must succeed against the same grant.

    PRD section 3.8: "A `category` that is not a member of the grant's
    `allowed_categories` is refused with `ERR_CATEGORY_NOT_FUNDABLE`; note that
    `WAGE_SUBSIDY` is an allowable grant category for funding placements but is never a
    support-request `category`."

    PRD section 3.8: "`open_request_count` is the number of support requests on the
    grant whose `status` is `SUBMITTED`, `INFO_REQUESTED`, or `DEFERRED`."

    Design: Corner/errors/a_category_outside_the_grants_allow_list_is_rejected
    """
    grant = build.grant(
        authorized_cents=100000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
        allowed_categories=[CATEGORY_TRANSIT_PASS, CATEGORY_ID_FEE],
    )
    participant = build.participant_zero_barrier_draft(
        record_categories=[RECORD_DRUG_OFFENSE]
    )

    refused = api.create_support_request(
        f.support_request_payload(
            participant["id"],
            grant["id"],
            build.grant_version(grant["id"]),
            [f.line_item("Framing nailer kit", 6000)],
            category=CATEGORY_TOOLS,
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_CATEGORY_NOT_FUNDABLE, 409)

    accepted = build.support_request(
        participant["id"],
        grant["id"],
        [f.line_item("State ID replacement fee", 3000)],
        category=CATEGORY_ID_FEE,
    )
    assert accepted["status"] == REQUEST_SUBMITTED
    assert_money_cents(accepted, "requested_cents", 3000)
    assert_money_cents(accepted, "admin_fee_cents", 0)
    assert_money_cents(accepted, "total_charge_cents", 3000)

    rows, meta = validate_paginated(
        api.list_support_requests(CASE_MANAGER, {"participant_id": participant["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_int_field(ledger, "open_request_count", 1)
    assert_money_cents(ledger, "committed_cents", 0)
    assert_money_cents(ledger, "available_cents", 100000)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_ledger_identity(ledger)


def test_a_request_against_an_exhausted_grant_is_rejected(api, build):
    """
    The posture gate is read before any arithmetic on the new request: one approval
    consumes the award to the cent, driving `OPEN` straight to `EXHAUSTED`, and the next
    request is refused on the posture even though a thousand cents is trivially small.

    PRD section 3.8: "The posture is evaluated top down, so the first matching
    condition wins: `EXHAUSTED` when `available_cents` is 0 or below; otherwise
    `RESTRICTED` when `available_cents` is strictly less than the restricted floor;
    otherwise `OPEN`."

    PRD section 3.8: "While a grant is `EXHAUSTED`, new support-request creation
    against it is refused with `ERR_GRANT_EXHAUSTED`."

    An `ID_FEE` request of 10,000 is covered at 1.00, selects the middle fee tier for
    300, and charges 10,300 — exactly the award.

    Design: Corner/errors/a_request_against_an_exhausted_grant_is_rejected
    """
    grant = build.grant(
        authorized_cents=10300,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    participant = build.participant_zero_barrier_draft(
        record_categories=[RECORD_DRUG_OFFENSE]
    )
    approved = build.support_request_approved(
        participant["id"],
        grant["id"],
        [f.line_item("State ID replacement fee", 10000)],
        category=CATEGORY_ID_FEE,
    )
    assert_money_cents(approved, "requested_cents", 10000)
    assert_money_cents(approved, "admin_fee_cents", 300)
    assert_money_cents(approved, "total_charge_cents", 10300)

    exhausted = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert exhausted["funding_posture"] == FUNDING_POSTURE_EXHAUSTED
    assert_money_cents(exhausted, "available_cents", 0)

    refused = api.create_support_request(
        f.support_request_payload(
            participant["id"],
            grant["id"],
            build.grant_version(grant["id"]),
            [f.line_item("Monthly transit pass", 1000)],
            category=CATEGORY_TRANSIT_PASS,
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_GRANT_EXHAUSTED, 409)

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 10300)
    assert_money_cents(ledger, "available_cents", 0)
    assert_money_cents(ledger, "restricted_floor_cents", 1545)
    assert ledger["funding_posture"] == FUNDING_POSTURE_EXHAUSTED
    assert_int_field(ledger, "open_request_count", 0)
    assert_ledger_identity(ledger)

    rows, meta = validate_paginated(
        api.list_support_requests(CASE_MANAGER, {"grant_id": grant["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == approved["id"]


def test_verifying_an_unrequired_or_repeated_document_is_rejected(api, build):
    """
    One code answers two different mistakes — a type the programme never asked for and
    a type already confirmed — and neither may move the completeness figure off the two
    genuine confirmations or carry the participant toward readiness.

    PRD section 3.1: "A `document_type` that is not an element of the participant's
    `required_document_types`, or that already appears in `verified_document_types`, is
    refused with `ERR_DOCUMENT_NOT_REQUIRED` — the system does not track documents it
    never asked for, and it does not double-count a confirmation."

    Design: Corner/errors/verifying_an_unrequired_or_repeated_document_is_rejected
    """
    participant = build.participant(
        required_document_types=[
            DOC_STATE_ID,
            DOC_SSN_CARD,
            DOC_BIRTH_CERTIFICATE,
            DOC_WORK_HISTORY,
        ]
    )
    halfway = build.verify_documents(participant["id"], [DOC_STATE_ID, DOC_SSN_CARD])
    assert_one_decimal_place(halfway, "doc_completeness_pct", 50.0)

    unrequired = api.verify_document(
        participant["id"], f.document_verification_payload(DOC_DD214), CASE_MANAGER
    )
    validate_error(unrequired, ERR_DOCUMENT_NOT_REQUIRED, 409)

    repeated = api.verify_document(
        participant["id"], f.document_verification_payload(DOC_STATE_ID), CASE_MANAGER
    )
    validate_error(repeated, ERR_DOCUMENT_NOT_REQUIRED, 409)

    stored = validate_unpaginated(api.get_participant(participant["id"], CASE_MANAGER))
    assert_array_equals(stored, "verified_document_types", [DOC_STATE_ID, DOC_SSN_CARD])
    assert_one_decimal_place(stored, "doc_completeness_pct", 50.0)
    assert stored["stage"] == STAGE_PRE_RELEASE


def test_enrolling_the_same_participant_twice_on_one_session_is_rejected(api, build):
    """
    Every other enrolment gate is satisfied — three seats with two free, a session that
    has not begun, an unsuspended participant — so the duplicate rule is the only
    possible refusal, and the second payload's different flag must not overwrite the
    first row.

    PRD section 3.5: "and the participant must not already hold an enrollment on this
    same session whose `status` is `ENROLLED`, `ATTENDED`, or `NO_SHOW`, else
    `ERR_DUPLICATE_ENROLLMENT`"

    Design: Corner/errors/enrolling_the_same_participant_twice_on_one_session_is_rejected
    """
    participant = build.participant()
    session = build.readiness_session(
        session_type=SESSION_TYPE_INTERVIEW_PRACTICE,
        starts_at="2026-08-06T13:00:00.000Z",
        ends_at="2026-08-06T15:00:00.000Z",
        seat_capacity=3,
    )
    first = build.enrollment(session["id"], participant["id"])
    assert first["status"] == ENROLLMENT_ENROLLED
    assert first["disclosure_script_reviewed"] is False

    refused = api.create_enrollment(
        session["id"],
        f.enrollment_payload(participant["id"], True),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_DUPLICATE_ENROLLMENT, 409)

    stored = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert_int_field(stored, "enrolled_count", 1)
    assert_int_field(stored, "remaining_seats", 2)
    assert stored["status"] == SESSION_SCHEDULED
    assert_session_seat_identity(stored)

    rows, meta = validate_paginated(
        api.list_session_enrollments(session["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["disclosure_script_reviewed"] is False


def test_accepting_beyond_the_employer_concurrency_cap_is_rejected(api, build):
    """
    The concurrency ceiling belongs to acceptance, not to the offer: the second
    placement was created perfectly legally while the employer still had room, and only
    the acceptance is refused — which leaves the offer outstanding rather than declined,
    because a refused write changes nothing.

    PRD section 3.6: "and the partnership's `active_placement_count` is strictly less
    than its `max_concurrent_placements`, else `ERR_PARTNERSHIP_CAPACITY_REACHED`"

    PRD section 3.6: "Last comes capacity: an opening whose `status` is not `OPEN`, or
    whose `remaining_openings` is 0 or below, is refused with
    `ERR_JOB_OPENING_NOT_OPEN`."

    Design: Corner/errors/accepting_beyond_the_employer_concurrency_cap_is_rejected
    """
    grant, partnership, opening, first_participant, case, placement = _live_placement(
        api, build, max_concurrent_placements=1
    )
    second_participant = build.participant_released(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    offered = build.placement_offered(
        second_participant["id"], opening["id"], grant["id"]
    )
    assert offered["employment_status"] == EMPLOYMENT_OFFERED

    refused = api.respond_to_offer(
        offered["id"],
        f.offer_response_payload(OFFER_RESPONSE_ACCEPTED),
        participant_headers(second_participant["id"]),
    )
    validate_error(refused, ERR_PARTNERSHIP_CAPACITY_REACHED, 409)

    stored = validate_unpaginated(api.get_placement(offered["id"], CASE_MANAGER))
    assert stored["employment_status"] == EMPLOYMENT_OFFERED

    stored_partnership = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(stored_partnership, "active_placement_count", 1)
    assert_int_field(stored_partnership, "max_concurrent_placements", 1)

    stored_opening = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(stored_opening, "offered_count", 1)
    assert_int_field(stored_opening, "filled_count", 1)
    assert_int_field(stored_opening, "remaining_openings", 0)
    assert stored_opening["status"] == OPENING_FILLED
    assert_opening_seat_identity(stored_opening)

    assert (
        validate_unpaginated(
            api.get_participant(second_participant["id"], CASE_MANAGER)
        )["stage"]
        == STAGE_POST_RELEASE
    )
