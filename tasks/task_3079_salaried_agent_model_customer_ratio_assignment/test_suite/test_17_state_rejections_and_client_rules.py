"""Corner tests — state transition rejections, survey answering, client/email rules (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    open_transaction,
    advance_to_review,
    close_transaction,
    create_survey,
    create_closed_transaction,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_close_is_refused_from_the_assigned_coordination_state():
    """PRD §3.5: "The transaction-scoped close accepts a transaction whose `coordination_status` is `REVIEW` and requires a contract price greater than zero".
    PRD §3.4: "`OPEN` is the only posture that admits a new client".

    Design: Corner/state_machines/transaction_close_cannot_fire_from_unassigned_coordination_state
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Open Buyer", service_area_code="98101")
    assign_client(client["id"])
    tx = open_transaction(client["id"])

    resp = api_client.close_transaction(tx["id"], TRANSACTION_COORDINATOR)
    data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert data["error_id"] == "ERR_INVALID_STATE", data


def test_a_refused_close_releases_no_capacity():
    """PRD §2.5: "A transaction reaching `CLOSED` or `CANCELLED` releases capacity in the same request that records the termination".

    Design: Corner/state_machines/transaction_close_cannot_fire_from_unassigned_coordination_state
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Open Buyer", service_area_code="98101")
    assign_client(client["id"])
    tx = open_transaction(client["id"])
    api_client.close_transaction(tx["id"], TRANSACTION_COORDINATOR)

    unchanged_tx = get_success_data(api_client.get_transaction(tx["id"], PLATFORM_ADMIN))
    assert unchanged_tx["coordination_status"] == "ASSIGNED", unchanged_tx

    unchanged_client = get_success_data(api_client.get_client(client["id"], PLATFORM_ADMIN))
    assert unchanged_client["status"] == "IN_TRANSACTION", unchanged_client

    occ = get_success_data(api_client.get_open_client_counts(lead["id"], PLATFORM_ADMIN))
    row = occ[0] if isinstance(occ, list) else occ
    assert row["active_client_count"] == 1, row


def test_second_open_transaction_for_the_same_client_is_refused():
    """PRD §3.5: "A client may not have more than one transaction in flight: opening a second while an existing transaction of the client sits in `UNASSIGNED`, `ASSIGNED` or `REVIEW` is refused with `ERR_TRANSACTION_ALREADY_OPEN` (HTTP 409)."

    Design: Corner/validations/second_transaction_for_the_same_client_returns_transaction_already_open
    """
    region = create_region(target_client_ratio=4.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="One Deal", service_area_code="98101")
    assign_client(client["id"])
    first = open_transaction(client["id"])

    resp = api_client.open_transaction(client["id"], {}, TRANSACTION_COORDINATOR)
    data = validate_error(resp, ApiErrorId.ERR_TRANSACTION_ALREADY_OPEN)
    assert data["error_id"] == "ERR_TRANSACTION_ALREADY_OPEN", data

    listed = get_success_data(api_client.list_client_transactions(client["id"], PLATFORM_ADMIN))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert len(rows) == 1, rows
    assert first["coordination_status"] == "ASSIGNED", first


def test_respond_is_refused_on_an_already_answered_survey():
    """PRD §3.9: "A survey created with a score is born `RESPONDED` with `bonus_eligible` true."
    PRD §3.9: "A manually answered dispatch is never granted bonus credit".

    Design: Corner/state_machines/survey_respond_is_idempotent_only_before_the_second_ops_run
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="First Buyer", service_area_code="98101")
    assign_client(client["id"])
    tx = open_transaction(client["id"])
    advance_to_review(tx["id"], 70_000_000)
    close_transaction(tx["id"])
    survey = create_survey(tx["id"], lead["id"])

    answered = get_success_data(api_client.respond_survey(
        survey["id"], {"score": 5}, TRANSACTION_COORDINATOR,
    ))
    assert answered["response_status"] == "RESPONDED", answered
    assert answered["score"] == 5, answered

    resp = api_client.respond_survey(survey["id"], {"score": 3}, TRANSACTION_COORDINATOR)
    data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert data["error_id"] == "ERR_INVALID_STATE", data

    unchanged = get_success_data(api_client.get_survey(survey["id"], PLATFORM_ADMIN))
    assert unchanged["score"] == 5, unchanged
    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent["satisfaction_score"] == pytest.approx(5.0, abs=1e-2), agent


def test_survey_score_outside_the_one_to_five_band_is_refused():
    """PRD §2.1: "A request whose shape is invalid — a required input missing, an enum member outside its declared set, or a survey `score` outside the inclusive range 1 to 5 — is refused with `ERR_INVALID_REQUEST` (HTTP 400) before any state is touched."

    Design: Corner/errors/survey_respond_with_a_score_outside_one_to_five_returns_invalid_request
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="First Buyer", service_area_code="98101")
    assign_client(client["id"])
    tx = open_transaction(client["id"])
    advance_to_review(tx["id"], 70_000_000)
    close_transaction(tx["id"])
    survey = create_survey(tx["id"], lead["id"])

    low = api_client.respond_survey(survey["id"], {"score": 0}, TRANSACTION_COORDINATOR)
    low_data = validate_error(low, ApiErrorId.ERR_INVALID_REQUEST)
    assert low_data["error_id"] == "ERR_INVALID_REQUEST", low_data

    high = api_client.respond_survey(survey["id"], {"score": 6}, TRANSACTION_COORDINATOR)
    high_data = validate_error(high, ApiErrorId.ERR_INVALID_REQUEST)
    assert high_data["error_id"] == "ERR_INVALID_REQUEST", high_data


def test_survey_score_inside_the_band_is_admitted_and_moves_satisfaction():
    """PRD §3.9: "Recording a score of 1 to 5 on a dispatched survey recomputes the agent's `satisfaction_score`".

    Design: Corner/errors/survey_respond_with_a_score_outside_one_to_five_returns_invalid_request
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="First Buyer", service_area_code="98101")
    assign_client(client["id"])
    tx = open_transaction(client["id"])
    advance_to_review(tx["id"], 70_000_000)
    close_transaction(tx["id"])
    survey = create_survey(tx["id"], lead["id"])

    admitted = get_success_data(api_client.respond_survey(
        survey["id"], {"score": 1}, TRANSACTION_COORDINATOR,
    ))
    assert admitted["response_status"] == "RESPONDED", admitted
    assert admitted["score"] == 1, admitted

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent["satisfaction_score"] == pytest.approx(1.0, abs=1e-2), agent


def test_client_email_must_be_unique_across_the_whole_system():
    """PRD §3.3: "A duplicate `email` anywhere in the system is refused with `ERR_CLIENT_EMAIL_DUPLICATE` (HTTP 409)".

    Design: Corner/validations/client_create_with_a_duplicate_email_returns_client_email_duplicate
    """
    region_a = create_region(target_client_ratio=2.0, service_area_codes=["98101"], name="Puget Sound")
    region_b = create_region(target_client_ratio=2.0, service_area_codes=["97201"], name="Portland")
    create_client(full_name="Dana Dup", email="dana@x.com", service_area_code="98101")

    resp = api_client.create_client(
        {"full_name": "Dana Dup Again", "email": "dana@x.com",
         "service_area_code": "97201", "need_kind": "BUY"},
        OPERATIONS_COORDINATOR,
    )
    data = validate_error(resp, ApiErrorId.ERR_CLIENT_EMAIL_DUPLICATE)
    assert data["error_id"] == "ERR_CLIENT_EMAIL_DUPLICATE", data

    listed = get_success_data(api_client.list_clients(
        PLATFORM_ADMIN, params={"region_id": region_b["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert rows == [], rows


def test_a_second_client_in_another_region_is_still_refused_on_duplicate_email():
    """PRD §3.3: "A duplicate `email` anywhere in the system is refused with `ERR_CLIENT_EMAIL_DUPLICATE` (HTTP 409)".
    PRD §3.3: "A new client opens with `status` `UNASSIGNED`, `assigned_agent_id` null and `assignment_mode` `UNASSIGNED`".

    Design: Corner/validations/client_create_with_a_duplicate_email_returns_client_email_duplicate
    """
    create_region(target_client_ratio=2.0, service_area_codes=["98101"], name="Puget Sound")
    create_region(target_client_ratio=2.0, service_area_codes=["97201"], name="Portland")
    first = create_client(full_name="Dana Dup", email="dana@x.com", service_area_code="98101")

    api_client.create_client(
        {"full_name": "Dana Dup Again", "email": "dana@x.com",
         "service_area_code": "97201", "need_kind": "BUY"},
        OPERATIONS_COORDINATOR,
    )

    unchanged = get_success_data(api_client.get_client(first["id"], PLATFORM_ADMIN))
    assert unchanged["email"] == "dana@x.com", unchanged
    assert unchanged["status"] == "UNASSIGNED", unchanged