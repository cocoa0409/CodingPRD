"""Lab analysis creation and result-entry gates: case phase, authorization
effectiveness (including its priority over the sample-sufficiency bound), and
the consumption ceiling."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_case,
    advance_testing_authorization,
    create_lab_analysis_payload,
    create_testing_authorization,
    get_evidence_item,
    lab_result_payload,
    list_rows,
    record_result,
    setup_case_with_item,
    setup_effective_authorization,
    setup_lab_analysis_scheduled,
    ship_sample,
    validate_error,
    validate_ok,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]
ANALYST = TEST_USERS["evidence_analyst_headers"]


def _case_in_testing_with_rejected_agreement():
    """Case in TESTING; custody-confirmed 10ng item; its only authorization
    pushed to REJECTED_BY_PROSECUTION."""
    ctx = setup_case_with_item(
        jurisdiction_overrides={"state_code": "MI", "name": "Michigan"},
        item_overrides={"initial_sample_ng": 10},
    )
    advance_case(ctx["case"]["id"], "BEGIN_TESTING")
    authorization = create_testing_authorization(
        ctx["case"]["id"], ctx["item"]["id"], "AGREEMENT", terms="Prosecutor balks"
    )
    advance_testing_authorization(authorization["id"], "PROPOSE")
    advance_testing_authorization(authorization["id"], "REJECT")
    ctx["authorization"] = authorization
    ctx["case"] = {**ctx["case"], "status": "TESTING"}
    return ctx


def test_lab_create_on_case_not_in_testing_rejected(api):
    """PRD section 3.5: "The case that owns the evidence item must be in
    `TESTING` status, else `ERR_CASE_NOT_IN_TESTING` (HTTP 409)."

    Design: Corner/validations/lab_create_on_case_not_in_testing_rejected
    """
    ctx = setup_effective_authorization(
        jurisdiction_overrides={"state_code": "VT", "name": "Vermont"}
    )
    assert ctx["case"]["status"] == "INVESTIGATION"
    assert ctx["authorization"]["status"] == "SIGNED"

    resp = api.create_lab_analysis(
        create_lab_analysis_payload(ctx["item"]["id"], ctx["authorization"]["id"]),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_TESTING)


def test_record_result_consumption_over_reserved_rejected(api):
    """PRD section 3.5: "the `actual_consumed_ng` (which must be at least 1 and
    no more than `reserved_sample_ng`, else `ERR_CONSUMED_EXCEEDS_RESERVED`)".
    PRD section 3.5: "Result entry settles the ledger: any unconsumed portion
    of the reservation — the difference between `reserved_sample_ng` and
    `actual_consumed_ng` — is refunded to the item's `remaining_sample_ng`".

    Design: Corner/validations/record_result_consumption_over_reserved_rejected
    """
    ctx = setup_lab_analysis_scheduled(
        jurisdiction_overrides={"state_code": "AZ", "name": "Arizona"},
        analysis_overrides={"required_sample_ng": 5},
    )
    assert ctx["item"]["remaining_sample_ng"] == 20  # 25 initial - 5 reserved
    ship_sample(ctx["analysis"]["id"])

    resp = api.advance_lab_analysis(
        ctx["analysis"]["id"],
        lab_result_payload("EXCLUSIONARY", 7, True),
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_CONSUMED_EXCEEDS_RESERVED)
    # The rejection settles nothing: the reservation stands.
    assert get_evidence_item(ctx["item"]["id"])["remaining_sample_ng"] == 20

    # Consuming exactly the reservation is legal.
    data = record_result(ctx["analysis"]["id"], actual_consumed_ng=5)
    assert data["status"] == "RESULT_RECORDED"
    assert data["actual_consumed_ng"] == 5


def test_lab_create_authorization_error_precedes_sample_error(api):
    """PRD section 2.9: "When a single request violates several rules, the
    system evaluates checks in a fixed priority order so that the error the
    caller receives is deterministic."
    PRD section 2.9 item 11: "A lab analysis must reference a testing
    authorization that is actually effective —
    `ERR_AUTHORIZATION_NOT_EFFECTIVE` (§3.5)."
    PRD section 2.9 item 13(c): "sample sufficiency and consumption bounds —
    `ERR_INSUFFICIENT_SAMPLE`, `ERR_CONSUMED_EXCEEDS_RESERVED`" sit strictly
    after the referenced-entity-validity check in the pinned order.

    Design: Difficulty/priority_pair_validation_conflict/lab_create_authorization_error_precedes_sample_error
    """
    ctx = _case_in_testing_with_rejected_agreement()

    # The request violates BOTH rules: the authorization is
    # REJECTED_BY_PROSECUTION (not SIGNED/GRANTED) and 50ng exceeds the 10ng
    # remaining. Referenced-entity validity (priority 11) wins over the
    # domain-constraint bound (priority 13).
    resp = api.create_lab_analysis(
        create_lab_analysis_payload(
            ctx["item"]["id"],
            ctx["authorization"]["id"],
            required_sample_ng=50,
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_EFFECTIVE)


def test_lab_create_rejection_leaves_ledger_and_item_untouched(api):
    """PRD section 3.5: "The referenced authorization must currently be
    `SIGNED` or `GRANTED`, else `ERR_AUTHORIZATION_NOT_EFFECTIVE` (HTTP 422)."
    PRD section 3.5: "otherwise `UNTESTED`" (no effective authorization and no
    analyses derive the item's testing status to UNTESTED).

    Design: Difficulty/priority_pair_validation_conflict/lab_create_authorization_error_precedes_sample_error
    """
    ctx = _case_in_testing_with_rejected_agreement()

    resp = api.create_lab_analysis(
        create_lab_analysis_payload(
            ctx["item"]["id"],
            ctx["authorization"]["id"],
            required_sample_ng=50,
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_EFFECTIVE)

    item = get_evidence_item(ctx["item"]["id"])
    assert item["remaining_sample_ng"] == 10, "no debit on a rejected creation"
    assert item["testing_status"] == "UNTESTED", (
        "a rejected authorization never flips the item to TESTING_AUTHORIZED"
    )
    rows, meta = list_rows(
        api.list_evidence_item_lab_analyses(ctx["item"]["id"], ANALYST)
    )
    assert meta["total_count"] == 0
