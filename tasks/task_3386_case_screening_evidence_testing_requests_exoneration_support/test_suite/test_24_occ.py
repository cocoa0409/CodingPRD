"""Optimistic concurrency control: stale-version rejections on the case
update and on agreement amendments, and the motion amendment ban."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    amend_testing_authorization,
    amendment_payload,
    case_update_payload,
    create_testing_authorization,
    get_case,
    get_testing_authorization,
    setup_accepted_case,
    setup_case_with_item,
    update_case,
    validate_error,
    validate_ok,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]


def test_stale_case_version_rejected(api):
    """PRD section 2.7: "A request to update a case's `strategy_notes`,
    `theory_of_case`, or `assigned_attorney_id` must carry
    `expected_case_version`, set to the value of the case's `version` the
    client last observed. If another writer has advanced the case's version
    since that read — including a writer whose write was an entirely
    legitimate cascade, such as a records response that bumped the case — the
    update is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/stale_case_version_rejected
    """
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "WV", "name": "West Virginia"}
    )
    case_id = ctx["case"]["id"]
    observed = get_case(case_id)["version"]

    updated = update_case(case_id, observed, strategy_notes="Pursue DNA first")
    assert updated["version"] == observed + 1

    # Repeating the same observed version is stale, even though the payload
    # is otherwise legal.
    resp = api.update_case(
        case_id,
        case_update_payload(observed, strategy_notes="Stale rewrite"),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    case = get_case(case_id)
    assert case["strategy_notes"] == "Pursue DNA first", "the stale write did not land"
    assert case["version"] == observed + 1


def test_stale_authorization_version_and_motion_amendment_rejected(api):
    """PRD section 2.7: "Recording an amendment to a testing authorization's
    `terms` or `proposed_test_types` must carry
    `expected_testing_authorization_version` matching the authorization's
    current `version`. A mismatch means the authorization has legitimately
    advanced — a new amendment superseding the terms the client saw — and the
    request is rejected with `ERR_STALE_AUTHORIZATION_VERSION` (HTTP 412)".
    PRD section 3.4: "Amendments against a `MOTION`, or against an agreement
    that has left the negotiable statuses, are rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/cross_cutting_layers/stale_authorization_version_and_motion_amendment_rejected
    """
    ctx = setup_case_with_item(
        jurisdiction_overrides={"state_code": "MD", "name": "Maryland"}
    )
    agreement = create_testing_authorization(
        ctx["case"]["id"], ctx["item"]["id"], "AGREEMENT", terms="v1 terms"
    )
    motion = create_testing_authorization(
        ctx["case"]["id"], ctx["item"]["id"], "MOTION"
    )

    amended = amend_testing_authorization(
        agreement["id"], agreement["version"], terms="v2 terms: split costs"
    )
    assert amended["version"] == agreement["version"] + 1
    assert amended["terms"] == "v2 terms: split costs"

    # Replaying the pre-amendment version is stale.
    resp = api.amend_testing_authorization(
        agreement["id"],
        amendment_payload(agreement["version"], terms="stale v3 attempt"),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_AUTHORIZATION_VERSION)
    assert get_testing_authorization(agreement["id"])["terms"] == "v2 terms: split costs"

    # Amendments exist only on the AGREEMENT lifecycle.
    resp = api.amend_testing_authorization(
        motion["id"],
        amendment_payload(motion["version"], terms="motions are not amendable"),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
