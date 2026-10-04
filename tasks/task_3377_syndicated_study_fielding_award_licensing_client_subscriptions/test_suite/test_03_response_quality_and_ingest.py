"""Response ingest: synchronous quality classification boundaries, referential
payload checks, and the study-then-frame state gate ordering (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    add_brand,
    add_frame,
    close_fielding,
    create_response_payload,
    create_study_with_pinned_methodology,
    list_frame_responses,
    open_fielding,
    setup_fielding_study,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

FOPS = TEST_USERS["field_ops_headers"]


def _one_frame_fielding_study():
    """Study in FIELDING with a single OPEN PANEL frame for BrandA, no responses."""
    ctx = setup_fielding_study(
        min_sample=1,
        brands=[{"name": "BrandA", "target": 5, "responses": []}],
    )
    return ctx["study"], ctx["frames"]["BrandA"]


def test_quality_classification_boundaries(api, field_ops_headers):
    """PRD §3.2: "A response whose `duration_seconds` is strictly less than the
    methodology's `min_duration_seconds` is `REJECTED` with `reject_reason`
    `SPEEDER`; a duration exactly equal to the threshold is acceptable. Otherwise,
    if `distinct_values` is exactly 1 and `item_count` is at least the
    methodology's `straightline_min_items`, the response is `REJECTED` with
    `reject_reason` `STRAIGHTLINE`; a straightlined response whose `item_count` is
    one short of that minimum is accepted."
    PRD §3.2: "even a `REJECTED` classification is still a successful 201 creation
    — rejection is a data verdict, not a transport failure."

    Design: Corner/calculations/quality_classification_boundaries
    """
    _, frame = _one_frame_fielding_study()

    q1 = validate_success(
        api.create_response(
            create_response_payload(frame["id"], "rt-1", 9, 8, duration_seconds=179), FOPS
        ),
        expected_status=201,
    )
    assert q1["quality_status"] == "REJECTED" and q1["reject_reason"] == "SPEEDER", (
        f"179 < 180 must be REJECTED/SPEEDER, got {q1['quality_status']}/{q1['reject_reason']}"
    )

    q2 = validate_success(
        api.create_response(
            create_response_payload(frame["id"], "rt-2", 9, 8, duration_seconds=180), FOPS
        ),
        expected_status=201,
    )
    assert q2["quality_status"] == "ACCEPTED" and q2["reject_reason"] is None, (
        f"180 == threshold must be ACCEPTED (strict <), got {q2['quality_status']}"
    )

    q3 = validate_success(
        api.create_response(
            create_response_payload(frame["id"], "rt-3", 9, 8, item_count=12, distinct_values=1),
            FOPS,
        ),
        expected_status=201,
    )
    assert q3["quality_status"] == "REJECTED" and q3["reject_reason"] == "STRAIGHTLINE", (
        f"distinct 1 with items 12 >= 12 must be REJECTED/STRAIGHTLINE, got {q3['quality_status']}"
    )

    q4 = validate_success(
        api.create_response(
            create_response_payload(frame["id"], "rt-4", 9, 8, item_count=11, distinct_values=1),
            FOPS,
        ),
        expected_status=201,
    )
    assert q4["quality_status"] == "ACCEPTED", (
        f"items 11 < 12 must escape the straightline rule, got {q4['quality_status']}"
    )


def test_rejected_ingest_is_synchronous_and_visible(api, field_ops_headers):
    """PRD §3.2: "Classification is synchronous at ingest and is answered in the
    response body itself: `quality_status` is either `ACCEPTED` or `REJECTED`, and
    even a `REJECTED` classification is still a successful 201 creation — rejection
    is a data verdict, not a transport failure."
    PRD §3.9: "a frame's responses by `quality_status`"

    Design: Corner/consistency_model/rejected_ingest_is_synchronous_and_visible
    """
    _, frame = _one_frame_fielding_study()
    created = validate_success(
        api.create_response(
            create_response_payload(frame["id"], "rt-1", 9, 8, duration_seconds=100), FOPS
        ),
        expected_status=201,
    )
    assert created["quality_status"] == "REJECTED"
    assert created["reject_reason"] == "SPEEDER", f"100 < 180 must be SPEEDER, got {created['reject_reason']}"

    rejected = list_frame_responses(frame["id"], quality_status="REJECTED")
    assert [r["id"] for r in rejected] == [created["id"]], (
        "the very next filtered read must list the rejected row — no reconciliation delay"
    )


def test_response_unknown_factor_returns_422(api, field_ops_headers):
    """PRD §3.2: "A `factor_code` not defined by the pinned methodology is rejected
    with `ERR_UNKNOWN_FACTOR`."

    Design: Corner/validations/response_unknown_factor_returns_422
    """
    _, frame = _one_frame_fielding_study()
    payload = create_response_payload(frame["id"], "rt-1", 9, 8)
    payload["factor_scores"] = [
        {"factor_code": "QUAL", "score": 9},
        {"factor_code": "NOPE", "score": 8},
    ]
    resp = api.create_response(payload, FOPS)
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_FACTOR)
    assert list_frame_responses(frame["id"]) == [], "a rejected ingest persists no row"


def test_response_score_out_of_range_returns_422(api, field_ops_headers):
    """PRD §3.2: "A score that is not an integer between 1 and 10 inclusive is
    rejected with `ERR_SCORE_OUT_OF_RANGE` before any code checks run."

    Design: Corner/validations/response_score_out_of_range_returns_422
    """
    _, frame = _one_frame_fielding_study()
    payload = create_response_payload(frame["id"], "rt-1", 9, 8)
    payload["factor_scores"] = [
        {"factor_code": "QUAL", "score": 11},
        {"factor_code": "FEAT", "score": 8},
    ]
    resp = api.create_response(payload, FOPS)
    validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE)
    assert list_frame_responses(frame["id"]) == [], "a rejected ingest persists no row"


def test_response_missing_pinned_factor_returns_422(api, field_ops_headers):
    """PRD §3.2: "A payload that fails to cover every factor of the pinned
    methodology — every response must speak to every measurement dimension — is
    rejected with `ERR_FACTOR_COVERAGE_INCOMPLETE`."

    Design: Corner/errors/response_missing_pinned_factor_returns_422
    """
    _, frame = _one_frame_fielding_study()
    payload = create_response_payload(frame["id"], "rt-1", 9, 8)
    payload["factor_scores"] = [{"factor_code": "QUAL", "score": 9}]
    resp = api.create_response(payload, FOPS)
    validate_error(resp, ApiErrorId.ERR_FACTOR_COVERAGE_INCOMPLETE)
    assert list_frame_responses(frame["id"]) == [], "a rejected ingest persists no row"


def test_ingest_rejected_while_study_not_fielding(api, field_ops_headers):
    """PRD §3.2: "Ingest is gated on both levels of the hierarchy, parent first:
    if the study is not `FIELDING` the attempt fails with
    `ERR_STUDY_NOT_FIELDING`; only if the study is fielding is the frame consulted,
    and a `CLOSED` frame fails with `ERR_FRAME_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/response_ingest_gated_by_frame_and_study_state
    """
    ctx = create_study_with_pinned_methodology(min_sample_per_brand=1)
    sid = ctx["study"]["id"]
    brand = add_brand("BrandA")
    frame = add_frame(sid, brand["id"])
    # Study is DESIGN_LOCKED, frame is OPEN — the parent gate fires first.
    assert ctx["study"]["status"] == "DESIGN_LOCKED"

    resp = api.create_response(create_response_payload(frame["id"], "rt-1", 9, 8), FOPS)
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FIELDING)
    assert list_frame_responses(frame["id"]) == [], (
        "a state-gate rejection is not a REJECTED-status 201; no row persists"
    )


def test_ingest_rejected_when_frame_closed(api, field_ops_headers):
    """PRD §3.2: "Ingest is gated on both levels of the hierarchy, parent first:
    if the study is not `FIELDING` the attempt fails with
    `ERR_STUDY_NOT_FIELDING`; only if the study is fielding is the frame consulted,
    and a `CLOSED` frame fails with `ERR_FRAME_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/response_ingest_gated_by_frame_and_study_state
    """
    _, frame = _one_frame_fielding_study()
    validate_success(api.sample_frame_state(frame["id"], {"to_status": "CLOSED"}, FOPS))

    resp = api.create_response(create_response_payload(frame["id"], "rt-1", 9, 8), FOPS)
    validate_error(resp, ApiErrorId.ERR_FRAME_NOT_OPEN)
    assert list_frame_responses(frame["id"]) == [], (
        "a state-gate rejection is not a REJECTED-status 201; no row persists"
    )
