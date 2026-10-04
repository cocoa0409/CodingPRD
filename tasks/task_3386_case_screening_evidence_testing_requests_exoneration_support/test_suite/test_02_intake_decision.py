"""Case materialization on ACCEPTED, the decide response payload, and
intake-request list filtering plus pagination."""
from test_helpers import (
    TEST_USERS,
    advance_intake,
    assert_new_case_defaults,
    create_client,
    create_intake_request,
    create_jurisdiction,
    decide_intake,
    decide_payload,
    get_case,
    is_valid_uuid,
    list_rows,
    make_managing_attorney_headers,
    setup_intake_pipeline,
    validate_ok,
    validate_paginated,
)

SPECIALIST = TEST_USERS["intake_specialist_headers"]
DECIDER = TEST_USERS["managing_attorney_headers"]


def test_case_is_created_only_by_accept_decision(api):
    """PRD section 3.2: "When the decision is `ACCEPTED`, the server creates a
    `Case` whose `intake_request_id` points back to this intake request."
    PRD section 3.2: "Rejection is terminal as well: a `REJECTED` decision
    records the rationale in `decision_reason` and ends the pipeline for that
    request."

    Design: Corner/entities/case_is_created_only_by_accept_decision
    """
    jurisdiction = create_jurisdiction(state_code="ME", name="Maine")
    client_a = create_client(full_name="Ray Doss", inmate_number="ME-1")
    client_b = create_client(full_name="Sara Penn", inmate_number="ME-2")

    rejected = setup_intake_pipeline(
        jurisdiction_id=jurisdiction["id"],
        client_id=client_a["id"],
        intake_overrides={
            "conviction_summary": "Will be rejected",
            "claim_of_actual_innocence": False,
            "claim_strength": "WEAK",
            "evidence_potential": "NONE_KNOWN",
        },
        recommendation="REJECT",
        decision="REJECTED",
        assigned_attorney_id=None,
        rejection_reason="No innocence claim",
    )["intake"]
    assert rejected["status"] == "REJECTED"
    assert rejected["decision_reason"] == "No innocence claim"
    assert rejected["accepted_case_id"] is None

    _, meta = list_rows(api.list_intake_request_cases(rejected["id"], DECIDER))
    assert meta["total_count"] == 0, "a REJECTED request materializes no Case"

    resp = api.decide_intake_request(
        # second request driven to DECISION_PENDING first
        setup_intake_pipeline(
            jurisdiction_id=jurisdiction["id"],
            client_id=client_b["id"],
            intake_overrides={"conviction_summary": "Will be accepted"},
            recommendation="ACCEPT",
        )["intake"]["id"],
        decide_payload("ACCEPTED", assigned_attorney_id="atty_9"),
        DECIDER,
    )
    accepted = validate_ok(resp)
    case_id = accepted["accepted_case_id"]
    assert accepted["decision"] == "ACCEPTED"
    assert is_valid_uuid(case_id)

    data, meta = list_rows(api.list_intake_request_cases(accepted["id"], DECIDER))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == case_id
    assert_new_case_defaults(data[0], accepted["id"])
    assert data[0]["assigned_attorney_id"] == "atty_9"


def test_decide_accepted_response_carries_decision_fields(api):
    """PRD section 3.2: "whichever branch is taken stamps `decision` and
    `decided_by_user_id` on the request".
    PRD section 3.2: "The new case opens in `OPEN` status with
    `assigned_attorney_id` taken from the decision payload when supplied".
    PRD section 2.2: "Unless otherwise noted, operations that create or modify
    a resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/decide_accepted_response_carries_decision_fields
    """
    ctx = setup_intake_pipeline(
        jurisdiction_overrides={"state_code": "RI", "name": "Rhode Island"},
        recommendation="ACCEPT",
    )
    assert ctx["intake"]["recommended_by_user_id"] == "spec_1"

    resp = api.decide_intake_request(
        ctx["intake"]["id"],
        decide_payload("ACCEPTED", assigned_attorney_id="atty_5"),
        make_managing_attorney_headers("ma_7"),
    )
    data = validate_ok(resp)
    assert data["decision"] == "ACCEPTED"
    assert data["decided_by_user_id"] == "ma_7", (
        "decided_by_user_id records the deciding attorney, not the recommender"
    )
    assert is_valid_uuid(data["accepted_case_id"])

    case = get_case(data["accepted_case_id"])
    assert case["status"] == "OPEN"
    assert case["assigned_attorney_id"] == "atty_5"
    assert case["intake_request_id"] == ctx["intake"]["id"]


def test_list_intake_requests_pagination_and_status_filter(api):
    """PRD section 2.3: "The `limit` parameter specifies the maximum number of
    items to return; it defaults to 10 when omitted, with a minimum of 1 and a
    maximum of 100."
    PRD section 2.3: "the intake-request list accepts `status`, `client_id`,
    and `jurisdiction_id`".
    PRD section 2.3: "List responses carry the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    Design: Corner/entities/list_intake_requests_pagination_and_status_filter
    """
    jurisdiction = create_jurisdiction(state_code="NH", name="New Hampshire")
    client = create_client(full_name="Ann Wren", inmate_number="NH-1")
    requests = [
        create_intake_request(
            client["id"],
            jurisdiction["id"],
            conviction_date=f"2022-01-0{i}T00:00:00Z",
            conviction_summary=f"P{i}",
            claim_strength="WEAK",
            evidence_potential="UNCERTAIN",
            years_served=4,
            health_urgency="NONE",
        )
        for i in (1, 2, 3)
    ]
    advance_intake(requests[0]["id"], "BEGIN_SCREENING")
    advance_intake(requests[1]["id"], "BEGIN_SCREENING")
    screening_ids = {requests[0]["id"], requests[1]["id"]}

    page1, meta1 = list_rows(
        api.list_intake_requests(
            SPECIALIST, params={"status": "SCREENING", "limit": 1, "offset": 0}
        )
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0
    assert page1[0]["id"] in screening_ids
    assert page1[0]["status"] == "SCREENING"

    page2, meta2 = list_rows(
        api.list_intake_requests(
            SPECIALIST, params={"status": "SCREENING", "limit": 1, "offset": 1}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    # The two pages are disjoint and together cover exactly the SCREENING set.
    assert page2[0]["id"] in screening_ids
    assert page2[0]["id"] != page1[0]["id"]
    assert {page1[0]["id"], page2[0]["id"]} == screening_ids

    all_rows, meta_all = list_rows(api.list_intake_requests(SPECIALIST))
    assert len(all_rows) == 3
    assert meta_all["total_count"] == 3
    assert meta_all["limit"] == 10, "the default limit applies when omitted"
    assert requests[2]["id"] in {row["id"] for row in all_rows}
    assert all(
        row["id"] != requests[2]["id"]
        for row in page1 + page2
    ), "the RECEIVED request never appears under status=SCREENING"
