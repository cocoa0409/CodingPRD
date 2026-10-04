"""Appeal and activation gates: windows, state legality, dispute exits."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    appeal_payload,
    evidence_item,
    file_appeal,
    get_cycle,
    make_class_registrar_headers,
    make_community_official_headers,
    set_clock,
    setup_published_classification,
    validate_error,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]
REGISTRAR = TEST_USERS["class_registrar_headers"]


def test_appeal_window_expired_returns_error(api):
    """PRD §3.9: "the filing must arrive within ninety days of the
    classification's `published_at` (later filings are
    `ERR_APPEAL_WINDOW_EXPIRED`, HTTP 422)" — published 2026-09-01 at the
    default clock, filed 2026-12-01, ninety-one days later.

    Design: Corner/validations/appeal_window_expired_returns_error
    """
    ctx = setup_published_classification(api, name="LateAppeal")
    community_id = ctx["community"]["id"]
    set_clock(api, "2026-12-01T00:00:00Z")
    resp = api.create_appeal(
        appeal_payload(ctx["classification"]["id"], community_id),
        make_community_official_headers(community_id),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)


def test_appeal_adjudicate_while_filed_returns_invalid_state(api):
    """PRD §3.9: adjudication runs `DATA_VERIFICATION` →
    `ADJUDICATED_UPHELD`/`ADJUDICATED_REVISED`, and "Any other appeal
    transition is `ERR_APPEAL_INVALID_STATE`" — a FILED appeal cannot skip
    verification.

    Design: Corner/errors/appeal_adjudicate_while_filed_returns_invalid_state
    """
    ctx = setup_published_classification(api, name="EarlyAdj")
    appeal = file_appeal(api, ctx["classification"]["id"], ctx["community"]["id"])
    resp = api.transition_appeal(
        appeal["id"], {"target_state": "ADJUDICATED_UPHELD"},
        make_class_registrar_headers("registrar-2"),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_INVALID_STATE)


def test_activate_with_pending_appeal_returns_appeal_pending(api):
    """PRD §3.7: "no appeal on it may be pending: a non-terminal appeal
    blocks activation with `ERR_APPEAL_PENDING` (HTTP 409)."

    Design: Corner/errors/activate_with_pending_appeal_returns_appeal_pending
    """
    ctx = setup_published_classification(api, name="PendingAppeal")
    file_appeal(
        api, ctx["classification"]["id"], ctx["community"]["id"],
        grounds="PROCEDURAL_ERROR", evidence_items=[evidence_item("E1", "s3://e1.pdf")],
    )
    resp = api.activate_classification(
        ctx["classification"]["id"], {"effective_from": "2026-09-01"}, REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_PENDING)


def test_disputed_exit_without_verification_appeal_returns_error(api):
    """PRD §3.9: "While an appeal on the cycle's classification sits in
    `DATA_VERIFICATION`, the coordinator may return the `DISPUTED` cycle to
    `FIELD_VERIFICATION` for rework — attempting that return without such an
    appeal is rejected with `ERR_NO_APPEAL_IN_VERIFICATION`."

    Design: Corner/errors/disputed_exit_without_verification_appeal_returns_error
    """
    ctx = setup_published_classification(api, name="DisputeGate")
    file_appeal(api, ctx["classification"]["id"], ctx["community"]["id"])
    cycle_id = ctx["cycle"]["id"]
    assert get_cycle(api, cycle_id)["status"] == "DISPUTED"
    resp = api.transition_evaluation_cycle(cycle_id, {"target_state": "FIELD_VERIFICATION"}, COORD)
    validate_error(resp, ApiErrorId.ERR_NO_APPEAL_IN_VERIFICATION)
    assert get_cycle(api, cycle_id)["status"] == "DISPUTED"
