"""Entity-specific 404s along nested paths and the pagination bounds shared
by every list endpoint (PRD §2.6, §2.3, §2.2).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    conduct_violation_payload,
    create_case,
    make_iic_headers,
    set_clock,
    setup_factual,
    validate_error,
    validate_paginated,
)

DUTY_OFFICER = TEST_USERS["duty_officer_headers"]
MD_ADOPTER = TEST_USERS["md_adopter_headers"]


class TestEntitySpecificNotFound:
    def test_unknown_path_ids_return_entity_specific_not_found(self, api):
        """PRD §2.6: "Resource identifiers are validated from left to right
        along the request path, including embedded sub-path identifiers, and
        the request is rejected at the first identifier that does not resolve.
        An unknown accident-case id yields `ERR_ACCIDENT_CASE_NOT_FOUND` before
        the server even attempts to locate a `decision_id` within it; a missing
        embedded decision then yields `ERR_LAUNCH_DECISION_NOT_FOUND`. The
        remaining existence errors follow the same pattern:
        `ERR_INVESTIGATION_NOT_FOUND`, `ERR_PARTY_ORGANIZATION_NOT_FOUND`,
        `ERR_PARTY_DESIGNATION_NOT_FOUND`, `ERR_GROUP_NOT_FOUND`,
        `ERR_SEAT_NOT_FOUND`, `ERR_FACTUAL_REPORT_NOT_FOUND`,
        `ERR_RECORDER_NOT_FOUND`, `ERR_SAFETY_RECOMMENDATION_NOT_FOUND`, and
        `ERR_BOARD_MEETING_NOT_FOUND`."

        Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found
        """
        ctx = setup_factual()
        case_id = ctx["case"]["id"]
        group_id = ctx["group"]["id"]
        designation_id = ctx["designation"]["id"]
        iic = make_iic_headers(ctx["iic_user_id"])

        # Embedded sub-path ids on live parents.
        resp = api.adopt_launch_decision(
            case_id, NON_EXISTENT_UUID, {"iic_user_id": "iic-1"}, MD_ADOPTER
        )
        validate_error(resp, ApiErrorId.ERR_LAUNCH_DECISION_NOT_FOUND)

        resp = api.verify_factual_report(group_id, NON_EXISTENT_UUID, iic)
        validate_error(resp, ApiErrorId.ERR_FACTUAL_REPORT_NOT_FOUND)

        resp = api.record_conduct_violation(
            designation_id,
            NON_EXISTENT_UUID,
            conduct_violation_payload("EX_PARTE_CONTACT", "Contact."),
            iic,
        )
        validate_error(resp, ApiErrorId.ERR_SEAT_NOT_FOUND)

        # Top-level ids on the read endpoints.
        probes = [
            (api.get_accident_case, ApiErrorId.ERR_ACCIDENT_CASE_NOT_FOUND),
            (api.get_party_designation, ApiErrorId.ERR_PARTY_DESIGNATION_NOT_FOUND),
            (api.get_group, ApiErrorId.ERR_GROUP_NOT_FOUND),
            (api.get_recorder, ApiErrorId.ERR_RECORDER_NOT_FOUND),
            (api.get_safety_recommendation, ApiErrorId.ERR_SAFETY_RECOMMENDATION_NOT_FOUND),
            (api.get_board_meeting, ApiErrorId.ERR_BOARD_MEETING_NOT_FOUND),
        ]
        for get_call, error_id in probes:
            resp = get_call(NON_EXISTENT_UUID, DUTY_OFFICER)
            validate_error(resp, error_id)

    def test_investigation_get_with_unknown_id_returns_investigation_not_found(self, api):
        """PRD §2.6: "The remaining existence errors follow the same pattern:
        `ERR_INVESTIGATION_NOT_FOUND`, `ERR_PARTY_ORGANIZATION_NOT_FOUND`,
        `ERR_PARTY_DESIGNATION_NOT_FOUND`, `ERR_GROUP_NOT_FOUND`,
        `ERR_SEAT_NOT_FOUND`, `ERR_FACTUAL_REPORT_NOT_FOUND`,
        `ERR_RECORDER_NOT_FOUND`, `ERR_SAFETY_RECOMMENDATION_NOT_FOUND`, and
        `ERR_BOARD_MEETING_NOT_FOUND`". PRD §2.2: "The `error_id` is a unique,
        machine-readable string that identifies the specific error." PRD §2.2:
        "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/entities/investigation_get_with_unknown_id_returns_investigation_not_found
        """
        set_clock()
        resp = api.get_investigation(NON_EXISTENT_UUID, DUTY_OFFICER)
        error_data = validate_error(resp, ApiErrorId.ERR_INVESTIGATION_NOT_FOUND)
        assert error_data["error_id"] == "ERR_INVESTIGATION_NOT_FOUND"
        assert isinstance(error_data["message"], str) and error_data["message"]
        assert resp.json()["response_type"] == "error"


class TestPaginationBounds:
    def test_pagination_limit_zero_returns_400(self, api):
        """PRD §2.3: "`limit` specifies the maximum number of items to return:
        it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of
        100. `offset` specifies how many items to skip: it defaults to 0 and
        may never be negative. Values outside these bounds are rejected with
        `ERR_INVALID_PAGINATION_PARAMETERS`."

        Design: Corner/errors/pagination_limit_zero_returns_400
        """
        set_clock()
        create_case()

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            resp = api.list_accident_cases(DUTY_OFFICER, params=params)
            validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)

        rows, meta = validate_paginated(api.list_accident_cases(DUTY_OFFICER))
        assert len(rows) == 1
        assert meta["limit"] == 10, "the default limit is 10"
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
