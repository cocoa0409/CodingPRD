"""Queue B — consistency_model: mutations are visible in their own response;
no re-read is needed to observe the decision's effects.
"""
from test_helpers import (
    ADMIN,
    api_client,
    create_exam_application,
    decision_payload,
    setup_candidate_with_verified_completion,
    validate_success,
)


def test_immediate_consistency_on_decision(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.4: "Approval mints an **authorization to test**: `issued_on` at the
    approval instant, `expires_on` ninety calendar days later, status `ISSUED`,
    with the application's `att_id` pointing at it."
    PRD §2.4: "`version` — a system-managed integer that increments by one on
    every mutation of the resource".

    The approval decision's own body carries status APPROVED and a non-null
    att_id, with the version advanced past the submitted row's.

    Design: Corner/consistency_model/immediate_consistency_on_decision
    """
    ctx = setup_candidate_with_verified_completion()
    application = create_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    assert application["status"] == "SUBMITTED"

    resp = api_client.decide_exam_application(
        application["id"], decision_payload("APPROVED"), ADMIN,
    )
    decided = validate_success(resp, 200)
    assert decided["status"] == "APPROVED"
    assert decided["att_id"], "the minted authorization is linked in the same response"
    assert decided["version"] == application["version"] + 1, (
        "the decision is a mutation of the application"
    )
