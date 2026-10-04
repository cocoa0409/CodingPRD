"""Taxpayer Advocate hardship-case tests: the expedite gate on a linked
FILTER_HELD return with its hold-priority side effect, and segregation of
duties on resolve.

PRD section 3.9.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_advocate_case,
    create_taxpayer,
    get_return_hold,
    make_taxpayer_advocate_headers,
    resolve_advocate_case_payload,
    set_clock,
    setup_held_return,
    setup_released_return,
    validate_error,
    validate_success,
)

ADVOCATE_1 = make_taxpayer_advocate_headers("adv-1")
ADVOCATE_2 = make_taxpayer_advocate_headers("adv-2")


def test_expedite_on_released_return_rejected(api):
    """PRD section 3.9: "It requires the case to name a `return_id` whose
    return is currently `FILTER_HELD` — expediting an account-level case, or
    one whose return is not held, is rejected with
    `ERR_HARDSHIP_NOT_EXPEDITABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/advocate_expedite_requires_held_return
    """
    _taxpayer, rtn, _disb = setup_released_return(claimed_refund_cents=20000)
    assert rtn["status"] == "REFUND_RELEASED"

    case = create_advocate_case(
        rtn["taxpayer_id"], return_id=rtn["id"], hardship_type="MEDICAL",
        advocate_user_id="adv-1",
    )
    resp = api.expedite_advocate_case(case["id"], ADVOCATE_1)
    validate_error(resp, ApiErrorId.ERR_HARDSHIP_NOT_EXPEDITABLE)


def test_expedite_on_held_return_prioritizes_hold(api):
    """PRD section 3.9: "A successful expedite moves the case to
    `EXPEDITED_REVIEW`, sets `expedited` true, flips the held return's `OPEN`
    hold to `priority_review` true, and compresses the verification clock: a
    linked non-terminal identity-verification case on the same return, if one
    exists, has its `deadline_at` shrunk to the earlier of its current
    deadline and seven days from now by the logical clock."

    Design: Difficulty/cross_entity_state_dependency/advocate_expedite_requires_held_return
    """
    set_clock("2027-02-01T00:00:00Z")
    taxpayer, rtn, hold = setup_held_return()
    case = create_advocate_case(
        taxpayer["id"], return_id=rtn["id"], hardship_type="EVICTION",
        advocate_user_id="adv-1",
    )

    resp = api.expedite_advocate_case(case["id"], ADVOCATE_1)
    expedited = validate_success(resp, 200)
    assert expedited["status"] == "EXPEDITED_REVIEW"
    assert expedited["expedited"] is True

    assert get_return_hold(rtn["id"])["priority_review"] is True


def test_sod_advocate_resolve_by_opener_rejected(api):
    """PRD section 3.9: "Segregation of duties applies here as everywhere:
    the resolving advocate's `X-User-ID` must differ from the case's
    `opened_by_user_id`, or the request is rejected with
    `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403) — the advocate who opened a
    hardship case may not be the one who closes it."

    Design: Corner/rbac/sod_advocate_resolve_by_opener_rejected
    """
    taxpayer = create_taxpayer()
    case = create_advocate_case(
        taxpayer["id"], hardship_type="LEVY_THREAT", advocate_user_id="adv-1"
    )
    assert case["opened_by_user_id"] == "adv-1"

    own_resolve = api.resolve_advocate_case(
        case["id"], resolve_advocate_case_payload("self"), ADVOCATE_1
    )
    validate_error(own_resolve, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)

    peer_resolve = api.resolve_advocate_case(
        case["id"], resolve_advocate_case_payload("peer review complete"),
        ADVOCATE_2,
    )
    resolved = validate_success(peer_resolve, 200)
    assert resolved["status"] == "RESOLVED"
