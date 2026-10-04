"""Deviation creation rules and the CLOSE/REOPEN cycle."""
from test_helpers import (
    ApiErrorId, TEST_USERS, USER_IDS,
    validate_success, validate_error, validate_paginated,
    setup_batch_upstream, setup_batch_downstream,
    create_deviation_entity, create_deviation_payload,
    close_deviation, reopen_deviation,
    make_quality_assurance_reviewer_headers,
)

_QA1 = USER_IDS["reviewer"]


def _minor_deviation(env):
    return create_deviation_entity(env["batch"]["id"], kind="PROCESS", severity="MINOR",
                                   description="Brief foam-over observed in bioreactor")


def test_unsupported_deviation_action_returns_400(api, quality_assurance_reviewer_headers,
                                                  platform_admin_headers):
    """PRD §3.5: "An `action` value outside `CLOSE` and `REOPEN` is `ERR_UNSUPPORTED_ACTION`."

    Design: Corner/validations/unsupported_deviation_action_returns_400
    """
    env = setup_batch_upstream()
    deviation = _minor_deviation(env)
    resp = api.deviation_action(deviation["id"], {"action": "EXPLODE"},
                                quality_assurance_reviewer_headers)
    validate_error(resp, ApiErrorId.ERR_UNSUPPORTED_ACTION)
    rows, _m = validate_paginated(
        api.list_deviations(env["batch"]["id"], platform_admin_headers))
    assert rows[0]["status"] == "OPEN"


def test_manual_oos_deviation_create_rejected(api, platform_admin_headers):
    """PRD §3.5: "Deviations of kind `OOS` are never created through this path — they exist only as the system-created children of out-of-spec verification described in §3.4, and a create request naming `OOS` is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/manual_oos_deviation_create_rejected
    """
    env = setup_batch_upstream()
    payload = create_deviation_payload(
        kind="OOS", severity="MAJOR",
        description="Client attempting to open an OOS investigation by hand")
    resp = api.create_deviation(env["batch"]["id"], payload,
                                make_quality_assurance_reviewer_headers(_QA1))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(
        api.list_deviations(env["batch"]["id"], platform_admin_headers))
    assert meta["total_count"] == 0 and rows == []


def test_deviation_close_twice_rejected(api, quality_assurance_reviewer_headers,
                                        platform_admin_headers):
    """PRD §3.5: "Closure belongs to the `QualityAssuranceReviewer`, acting with `action` `CLOSE` on a deviation in `OPEN` or `REOPENED` (`ERR_DEVIATION_NOT_OPEN` otherwise)."

    Design: Corner/validations/deviation_close_twice_rejected
    """
    env = setup_batch_upstream()
    deviation = _minor_deviation(env)
    close_deviation(deviation["id"], "NO_ACTION_REQUIRED")
    resp = api.deviation_action(deviation["id"],
                                {"action": "CLOSE", "conclusion": "NO_ACTION_REQUIRED"},
                                quality_assurance_reviewer_headers)
    validate_error(resp, ApiErrorId.ERR_DEVIATION_NOT_OPEN)
    rows, _m = validate_paginated(
        api.list_deviations(env["batch"]["id"], platform_admin_headers))
    assert rows[0]["status"] == "CLOSED"


def test_deviation_close_reopen_close_cycle(api):
    """PRD §3.5: "The reviewer may reopen a `CLOSED` deviation with `action` `REOPEN` and a required `justification`"
    PRD §3.5: "Reopening moves the deviation to `REOPENED`, clears `conclusion` and `closed_by_user_id` to null"

    Design: Difficulty/non_linear_state_machine/deviation_close_reopen_close_cycle
    """
    env = setup_batch_downstream()
    deviation = _minor_deviation(env)
    closed = close_deviation(deviation["id"], "NO_ACTION_REQUIRED")
    assert closed["status"] == "CLOSED"
    reopened = reopen_deviation(
        deviation["id"], justification="New operator statement contradicts the first report")
    assert reopened["status"] == "REOPENED"
    assert reopened["conclusion"] is None, "the loop clears the first conclusion"
    reclosed = close_deviation(deviation["id"], "CAPA_COMPLETED",
                               capa_summary="optional here since MINOR")
    assert reclosed["status"] == "CLOSED"


def test_minor_deviation_never_moves_release_posture(api, platform_admin_headers):
    """PRD §2.9: "The counters are: `open_critical_deviation_count`, the number of deviations of severity `CRITICAL` whose status is `OPEN` or `REOPENED`"
    PRD §2.9: "It is `CLEAR` otherwise."

    Design: Difficulty/non_linear_state_machine/deviation_close_reopen_close_cycle
    """
    env = setup_batch_downstream()
    deviation = _minor_deviation(env)
    for step in ("open", "close", "reopen", "close"):
        if step == "close":
            close_deviation(deviation["id"], "NO_ACTION_REQUIRED")
        elif step == "reopen":
            reopen_deviation(deviation["id"])
        site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
        assert site["release_posture"] == "CLEAR", f"after {step}"
        assert site["open_critical_deviation_count"] == 0, f"after {step}"
