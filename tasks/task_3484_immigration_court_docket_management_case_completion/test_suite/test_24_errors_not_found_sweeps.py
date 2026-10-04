"""Error probes: the not-found sweep across read and action endpoints.

Every single-resource GET resolves its id or returns the pinned 404 —
resource-specific codes for Court and Hearing, the generic ERR_NOT_FOUND for
LegalOrientationProgram, CaseReassignment, and DocketReview — and the action
endpoints addressed at unallocated ids (path parameters first, then body
foreign keys) answer their resource-specific 404 before any ownership or
state logic runs.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_case,
    create_court,
    create_judge,
    make_appeal_payload,
    make_appeal_ruling_payload,
    make_assign_judge_payload,
    make_judge_headers,
    make_ruling_payload,
    validate_error,
)


def test_not_found_sweep_read_endpoints(api, admin_headers):
    """PRD §2.6: "3. **Existence (HTTP 404).** Path identifiers and body foreign-key identifiers must resolve to existing resources, validated left-to-right: path parameters first, in the order they appear in the path, then body identifiers in the endpoint's declared input order. The first unresolvable identifier produces its resource-specific error — `ERR_COURT_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`, `ERR_INTERPRETER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CONTINUANCE_NOT_FOUND`, `ERR_VENUE_MOTION_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, or `ERR_MOTION_NOT_FOUND`. References to a `LegalOrientationProgram`, a `CaseReassignment`, or a `DocketReview` that do not resolve instead produce the generic `ERR_NOT_FOUND`."

    Design: Corner/errors/not_found_sweep_read_endpoints
    """
    reads = [
        (api.get_court, ApiErrorId.ERR_COURT_NOT_FOUND),
        (api.get_hearing, ApiErrorId.ERR_HEARING_NOT_FOUND),
        (api.get_orientation_program, ApiErrorId.ERR_NOT_FOUND),
        (api.get_case_reassignment, ApiErrorId.ERR_NOT_FOUND),
        (api.get_docket_review, ApiErrorId.ERR_NOT_FOUND),
    ]
    for call, expected_error in reads:
        resp = call(NON_EXISTENT_UUID, headers=admin_headers)
        validate_error(resp, expected_error)
        assert resp.status_code == 404


def test_not_found_sweep_action_endpoints(api, admin_headers, board_headers):
    """PRD §2.6: "3. **Existence (HTTP 404).** Path identifiers and body foreign-key identifiers must resolve to existing resources, validated left-to-right: path parameters first, in the order they appear in the path, then body identifiers in the endpoint's declared input order. The first unresolvable identifier produces its resource-specific error — `ERR_COURT_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`, `ERR_INTERPRETER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CONTINUANCE_NOT_FOUND`, `ERR_VENUE_MOTION_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, or `ERR_MOTION_NOT_FOUND`."
    PRD §2.10: "Where an endpoint's path or payload references other resources, identifiers are resolved strictly left-to-right: path parameters first, in the order they appear in the path, then body foreign keys in the endpoint's declared input order. The first identifier that fails to resolve rejects the request with the 404 error of its resource type per tier 3 of §2.6, and later identifiers are never examined."

    Design: Corner/errors/not_found_sweep_action_endpoints
    """
    court = create_court()
    judge = create_judge(court["id"])
    case = create_case(court["id"])
    # A real Judge identity: the user-context tier passes, so each rejection
    # below is the existence tier, not the identity or permission tiers.
    judge_headers = make_judge_headers(judge["id"])

    # Body foreign key: the path case resolves, the named judge does not.
    resp = api.assign_judge(
        case["id"],
        make_assign_judge_payload(NON_EXISTENT_UUID),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_JUDGE_NOT_FOUND)

    # Path-parameter ids on the judge-ruled decide endpoints.
    resp = api.decide_continuance_request(
        NON_EXISTENT_UUID, make_ruling_payload("GRANTED"), headers=judge_headers
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_NOT_FOUND)
    resp = api.decide_venue_motion(
        NON_EXISTENT_UUID, make_ruling_payload("GRANTED"), headers=judge_headers
    )
    validate_error(resp, ApiErrorId.ERR_VENUE_MOTION_NOT_FOUND)
    resp = api.decide_motion_to_reopen(
        NON_EXISTENT_UUID, make_ruling_payload("GRANTED"), headers=judge_headers
    )
    validate_error(resp, ApiErrorId.ERR_MOTION_NOT_FOUND)

    # The board-ruled appeal decide on an unallocated appeal id.
    resp = api.decide_appeal(
        NON_EXISTENT_UUID,
        make_appeal_ruling_payload("AFFIRMED"),
        headers=board_headers,
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_FOUND)

    # Administrator actions on unallocated ids, path and body foreign key.
    resp = api.mark_notice_defective(NON_EXISTENT_UUID, headers=admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_FOUND)
    resp = api.create_appeal(
        make_appeal_payload(NON_EXISTENT_UUID), headers=admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_FOUND)
