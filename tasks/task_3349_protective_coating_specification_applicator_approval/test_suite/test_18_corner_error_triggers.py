"""Corner breadth index (errors): the substitution review-round cap and the
qualification reinstatement limit, both driven to their trigger points.
"""
from test_helpers import (
    REINSTATE_SUSPENSION_LIMIT,
    TECHNICAL_SERVICE_ENGINEER_HEADERS,
    ApiClient,
    ApiErrorId,
    certify_qualification,
    create_applicator,
    create_coating_system,
    create_program,
    create_substitution_request,
    create_world,
    enroll_qualification,
    read_qualification,
    read_substitution_request,
    reinstate_qualification,
    suspend_qualification,
    validate_error,
    validate_success,
)


def test_review_round_exhausted_triggerable(api: ApiClient):
    """PRD §3.4: "From `UNDER_REVIEW` the reviewer may request more
    information, moving the request to `MORE_INFO_REQUESTED`, but only while
    `review_round` is still below `max_review_rounds` — once the round count
    has reached the cap the request fails with `ERR_REVIEW_ROUND_EXHAUSTED`
    and the reviewer is forced to a final decision."

    Design: Corner/errors/review_round_exhausted_triggerable
    """
    world = create_world(api, system_overrides={"system_code": "SW-RRE-INC"})
    competitor = create_coating_system(
        api,
        system_code="COMP-RRE",
        manufacturer_name="Competitor",
        is_competitor_system=True,
    )
    request = create_substitution_request(
        api, world["spec"]["id"], competitor["id"], rationale="cheaper", max_review_rounds=1
    )
    spec_id, request_id = world["spec"]["id"], request["id"]
    validate_success(api.start_substitution_review(spec_id, request_id, TECHNICAL_SERVICE_ENGINEER_HEADERS))

    response = api.request_substitution_info(spec_id, request_id, TECHNICAL_SERVICE_ENGINEER_HEADERS)

    validate_error(response, ApiErrorId.ERR_REVIEW_ROUND_EXHAUSTED, expected_status=422)
    remaining = read_substitution_request(api, request_id)
    assert remaining["status"] == "UNDER_REVIEW"
    assert remaining["review_round"] == 1


def test_reinstate_limit_exceeded_triggerable(api: ApiClient):
    """PRD §3.3: "Reinstating a `SUSPENDED` qualification is permitted only
    while `suspension_count` is below 3 — a qualification that has already
    been suspended three times can never be reinstated again, and the attempt
    fails with `ERR_REINSTATE_LIMIT_EXCEEDED`".
    PRD §3.3: "Suspending a `CERTIFIED` qualification — whether invoked by a
    `TechnicalServiceEngineer` or triggered by the score cascade — increments
    `suspension_count` by 1".

    Design: Corner/errors/reinstate_limit_exceeded_triggerable
    """
    applicator = create_applicator(api, company_name="Reinstate Coaters", contact_email="r@coaters.example")
    system = create_coating_system(api, system_code="SW-RLE")
    # A zero score floor keeps the score gate out of the reinstate path.
    program = create_program(
        api, system["id"], program_code="QP-RLE", min_quality_history_score=0
    )
    qualification = enroll_qualification(api, applicator["id"], program["id"])
    certify_qualification(api, applicator["id"], qualification["id"])

    # Reinstatement is permitted only while suspension_count is below 3, so
    # exactly two full suspend/reinstate cycles can complete; the third
    # suspension strands the qualification at the lifetime limit.
    for _ in range(REINSTATE_SUSPENSION_LIMIT - 1):
        suspend_qualification(api, applicator["id"], qualification["id"])
        reinstate_qualification(api, applicator["id"], qualification["id"])
    # The third suspension leaves the qualification SUSPENDED with count 3.
    suspend_qualification(api, applicator["id"], qualification["id"])

    response = api.reinstate_qualification(
        applicator["id"], qualification["id"], TECHNICAL_SERVICE_ENGINEER_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_REINSTATE_LIMIT_EXCEEDED, expected_status=409)
    qualification = read_qualification(api, applicator["id"], qualification["id"])
    assert qualification["suspension_count"] == REINSTATE_SUSPENSION_LIMIT, (
        "three suspensions at +1 each from a zero start"
    )
    assert qualification["status"] == "SUSPENDED"
