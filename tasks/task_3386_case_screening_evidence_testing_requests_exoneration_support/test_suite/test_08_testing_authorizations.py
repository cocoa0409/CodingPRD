"""Testing authorizations: creation gates (case phase, item custody, the
MOTION statute flag), kind-conditional event legality, and the motion ruling
cycle to effectiveness."""
from test_helpers import (
    ApiErrorId,
    STAFF_ATTORNEY_ID,
    TEST_USERS,
    advance_evidence_item,
    advance_testing_authorization,
    authorization_advance_payload,
    create_testing_authorization,
    create_testing_authorization_payload,
    get_evidence_item,
    list_rows,
    setup_case_with_item,
    validate_created,
    validate_error,
    validate_ok,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]
ANALYST = TEST_USERS["evidence_analyst_headers"]


def test_motion_requires_post_conviction_testing_statute(api):
    """PRD section 3.4: "And a `MOTION` is available only where the case's
    jurisdiction — reached through the intake request — has
    `has_post_conviction_dna_statute` true, else
    `ERR_JURISDICTION_NO_TESTING_STATUTE` (HTTP 422); the `AGREEMENT` path has
    no statutory prerequisite."

    Design: Corner/validations/motion_requires_post_conviction_testing_statute
    """
    ctx = setup_case_with_item(
        jurisdiction_overrides={
            "state_code": "MS",
            "name": "Mississippi",
            "has_post_conviction_dna_statute": False,
        }
    )
    resp = api.create_testing_authorization(
        create_testing_authorization_payload(
            ctx["case"]["id"], ctx["item"]["id"], "MOTION"
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_NO_TESTING_STATUTE)

    ok = api.create_testing_authorization(
        create_testing_authorization_payload(
            ctx["case"]["id"], ctx["item"]["id"], "AGREEMENT",
            terms="Consent path still open",
        ),
        ATTORNEY,
    )
    data = validate_created(ok)
    assert data["kind"] == "AGREEMENT"
    assert data["status"] == "DRAFTED"


def test_motion_kind_rejects_agreement_events_and_cycles_to_grant(api):
    """PRD section 3.4: "an agreement event presented against a `MOTION`, or a
    motion event against an `AGREEMENT`, is `ERR_INVALID_STATE` no matter the
    current status".
    PRD section 3.4: "From `DRAFTED` the attorney files, reaching `FILED`; from
    `FILED` or `APPEALED` the court's ruling is recorded with a payload
    `ruling` of `GRANTED` or `DENIED`, stamped into `last_ruling` (null until
    the first ruling). A denial from `DENIED` may be appealed to `APPEALED`,
    and a fresh ruling is recorded from there".

    Design: Corner/state_machines/motion_kind_rejects_agreement_events_and_cycles_to_grant
    """
    ctx = setup_case_with_item(
        jurisdiction_overrides={"state_code": "MT", "name": "Montana"}
    )
    motion = create_testing_authorization(
        ctx["case"]["id"], ctx["item"]["id"], "MOTION",
        proposed_test_types=["DNA_STR"],
    )
    assert motion["last_ruling"] is None

    resp = api.advance_testing_authorization(
        motion["id"], authorization_advance_payload("PROPOSE"), ATTORNEY
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    advance_testing_authorization(motion["id"], "FILE")
    denied = advance_testing_authorization(motion["id"], "RECORD_RULING", ruling="DENIED")
    assert denied["status"] == "DENIED"
    assert denied["last_ruling"] == "DENIED"
    advance_testing_authorization(motion["id"], "APPEAL")
    granted = advance_testing_authorization(motion["id"], "RECORD_RULING", ruling="GRANTED")
    assert granted["status"] == "GRANTED"
    assert granted["last_ruling"] == "GRANTED"

    # Effectiveness re-derives the linked item's testing dimension.
    assert get_evidence_item(ctx["item"]["id"])["testing_status"] == "TESTING_AUTHORIZED"


def test_testing_authorization_requires_case_in_investigation_or_testing(api):
    """PRD section 3.4: "The owning case must be in `INVESTIGATION` or
    `TESTING` status, else `ERR_CASE_NOT_READY_FOR_TESTING_AUTH` (HTTP 409)."

    Design: Corner/errors/testing_authorization_requires_case_in_investigation_or_testing
    """
    ctx = setup_case_with_item(
        jurisdiction_overrides={"state_code": "KS", "name": "Kansas"},
        begin_investigation=False,
    )
    assert ctx["case"]["status"] == "OPEN"
    assert ctx["item"]["location_status"] == "CUSTODY_CONFIRMED"

    resp = api.create_testing_authorization(
        create_testing_authorization_payload(
            ctx["case"]["id"], ctx["item"]["id"], "AGREEMENT", terms="Too early"
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_READY_FOR_TESTING_AUTH)


def test_authorization_create_blocked_until_item_in_custody(api):
    """PRD section 3.4: "The evidence item's `location_status` must be
    `CUSTODY_CONFIRMED`, else `ERR_EVIDENCE_NOT_IN_CUSTODY` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/testing_authorization_requires_evidence_in_custody
    """
    ctx = setup_case_with_item(
        jurisdiction_overrides={"state_code": "MO", "name": "Missouri"},
        location="LOCATED",
    )
    resp = api.create_testing_authorization(
        create_testing_authorization_payload(
            ctx["case"]["id"], ctx["item"]["id"], "AGREEMENT",
            terms="Attempt while merely LOCATED",
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_NOT_IN_CUSTODY)

    # Nothing changed but the item's location: the identical create succeeds.
    advance_evidence_item(ctx["item"]["id"], "CONFIRM_CUSTODY")
    ok = api.create_testing_authorization(
        create_testing_authorization_payload(
            ctx["case"]["id"], ctx["item"]["id"], "AGREEMENT",
            terms="Retry after custody confirmation",
        ),
        ATTORNEY,
    )
    data = validate_created(ok)
    assert data["status"] == "DRAFTED"

    rows, meta = list_rows(
        api.list_case_testing_authorizations(ctx["case"]["id"], ATTORNEY)
    )
    assert meta["total_count"] == 1, "the rejected attempt created nothing"


def test_authorization_create_records_creator_and_drafted_state(api):
    """PRD section 3.4: "Creation records the acting attorney's `X-User-ID` in
    `created_by_user_id` and lands the authorization in `DRAFTED`."
    PRD section 3.4: "The evidence item's `location_status` must be
    `CUSTODY_CONFIRMED`, else `ERR_EVIDENCE_NOT_IN_CUSTODY` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/testing_authorization_requires_evidence_in_custody
    """
    ctx = setup_case_with_item(
        jurisdiction_overrides={"state_code": "MO", "name": "Missouri"},
        location="LOCATED",
    )
    resp = api.create_testing_authorization(
        create_testing_authorization_payload(
            ctx["case"]["id"], ctx["item"]["id"], "AGREEMENT"
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_NOT_IN_CUSTODY)

    advance_evidence_item(ctx["item"]["id"], "CONFIRM_CUSTODY")
    data = validate_created(
        api.create_testing_authorization(
            create_testing_authorization_payload(
                ctx["case"]["id"], ctx["item"]["id"], "AGREEMENT",
                proposed_test_types=["DNA_STR"],
            ),
            ATTORNEY,
        )
    )
    assert data["kind"] == "AGREEMENT"
    assert data["status"] == "DRAFTED"
    assert data["created_by_user_id"] == STAFF_ATTORNEY_ID
    assert data["version"] == 1
    assert data["case_id"] == ctx["case"]["id"]
    assert data["evidence_item_id"] == ctx["item"]["id"]
