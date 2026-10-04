"""Corner tests — tour scheduling, staffing, access window and no-show sweep (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    create_region,
    create_lead_agent,
    create_associate_agent,
    create_client,
    assign_client,
    schedule_tour,
    confirm_tour,
    create_closed_transaction,
    create_survey,
    set_clock,
)
from test_helpers import make_associate_agent_headers


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_tour_read_hides_the_access_code_until_the_release_instant():
    """PRD §2.4: "`created_at` is an ISO 8601 UTC timestamp with exactly three fractional digits".
    PRD §3.7: "The code becomes visible the moment the logical clock reaches 120 minutes before `scheduled_at` or later — the release instant is inclusive — and is null in every response before that."

    Design: Corner/entities/tour_access_code_is_release_windowed_on_read
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T12:00:00Z")

    before = get_success_data(api_client.get_tour(tour["id"], PLATFORM_ADMIN))
    assert before["access_code"] is None, before

    # 2026-09-02T09:59:59Z is one second before the 10:00:00Z release instant.
    get_success_data(api_client.set_current_utc("2026-09-02T09:59:59Z", PLATFORM_ADMIN))
    still_hidden = get_success_data(api_client.get_tour(tour["id"], PLATFORM_ADMIN))
    assert still_hidden["access_code"] is None, still_hidden


def test_tour_access_code_appears_at_the_inclusive_release_instant():
    """PRD §3.7: "The code becomes visible the moment the logical clock reaches 120 minutes before `scheduled_at` or later — the release instant is inclusive — and is null in every response before that."

    Design: Corner/entities/tour_access_code_is_release_windowed_on_read
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T12:00:00Z")

    get_success_data(api_client.set_current_utc("2026-09-02T10:00:00Z", PLATFORM_ADMIN))
    released = get_success_data(api_client.get_tour(tour["id"], PLATFORM_ADMIN))
    assert released["access_code"] is not None, released


def test_confirming_before_the_release_instant_is_refused():
    """PRD §3.7: "confirming before the window has opened is refused with `ERR_ACCESS_WINDOW_NOT_OPEN` (HTTP 409)".

    Design: Corner/validations/tour_confirm_before_the_release_instant_returns_access_window_not_open
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T12:00:00Z",
                         associate_agent_id=associate["id"])

    get_success_data(api_client.set_current_utc("2026-09-02T09:59:59Z", PLATFORM_ADMIN))
    resp = api_client.confirm_tour(tour["id"], make_associate_agent_headers(associate["id"]))
    data = validate_error(resp, ApiErrorId.ERR_ACCESS_WINDOW_NOT_OPEN)
    assert data["error_id"] == "ERR_ACCESS_WINDOW_NOT_OPEN", data

    unchanged = get_success_data(api_client.get_tour(tour["id"], PLATFORM_ADMIN))
    assert unchanged["status"] == "ACCESS_PENDING", unchanged


def test_confirming_at_the_release_instant_succeeds():
    """PRD §3.7: "A confirmed tour moves to `CONFIRMED`, surfaces the access code, and increments the lead agent's `associate_capacity_used` and recomputes `tours_in_week` when an associate was staffed."

    Design: Corner/validations/tour_confirm_before_the_release_instant_returns_access_window_not_open
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T12:00:00Z",
                         associate_agent_id=associate["id"])

    get_success_data(api_client.set_current_utc("2026-09-02T10:00:00Z", PLATFORM_ADMIN))
    confirmed = confirm_tour(tour["id"], associate["id"])
    assert confirmed["status"] == "CONFIRMED", confirmed
    assert confirmed["access_code"] is not None, confirmed


def test_unassisted_third_tour_is_refused_at_the_block_threshold():
    """PRD §3.7: "Once `UniServicedTourCount` reaches that threshold, an `associate_agent_id` is mandatory on a new tour, and a schedule that omits it is refused with `ERR_ASSOCIATE_AGENT_REQUIRED` (HTTP 409)."

    Design: Corner/validations/tour_without_associate_at_the_block_threshold_returns_associate_agent_required
    """
    # target 2.0 -> block threshold ceil(2.0) = 2 unassisted tours; the first
    # two are admitted and the third is refused.
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"], home_zip="98101")
    associate = create_associate_agent(region["id"], home_zip="98102")
    clients = []
    for i, code in enumerate(["98101", "98102", "98103"]):
        client = create_client(full_name=f"Tour Client {i}", service_area_code=code)
        assign_client(client["id"])
        clients.append(client)

    schedule_tour(clients[0]["id"], "2026-09-02T09:00:00Z")
    schedule_tour(clients[1]["id"], "2026-09-02T11:00:00Z")

    resp = api_client.create_tour(
        {"client_id": clients[2]["id"], "scheduled_at": "2026-09-02T13:00:00Z",
         "access_instructions": "Lockbox 3"},
        OPERATIONS_COORDINATOR,
    )
    data = validate_error(resp, ApiErrorId.ERR_ASSOCIATE_AGENT_REQUIRED)
    assert data["error_id"] == "ERR_ASSOCIATE_AGENT_REQUIRED", data


def test_staffing_an_associate_admits_the_third_tour():
    """PRD §3.7: "`ERR_ASSOCIATE_AGENT_REQUIRED` (HTTP 409). Below the threshold an associate is optional."

    Design: Corner/validations/tour_without_associate_at_the_block_threshold_returns_associate_agent_required
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"], home_zip="98101")
    associate = create_associate_agent(region["id"], home_zip="98102")
    clients = []
    for i, code in enumerate(["98101", "98102", "98103"]):
        client = create_client(full_name=f"Tour Client {i}", service_area_code=code)
        assign_client(client["id"])
        clients.append(client)

    schedule_tour(clients[0]["id"], "2026-09-02T09:00:00Z")
    schedule_tour(clients[1]["id"], "2026-09-02T11:00:00Z")
    staffed = schedule_tour(clients[2]["id"], "2026-09-02T13:00:00Z",
                            associate_agent_id=associate["id"])
    assert staffed["associate_agent_id"] == associate["id"], staffed

    tours = get_success_data(api_client.list_tours(
        PLATFORM_ADMIN, params={"lead_agent_id": lead["id"]},
    ))
    rows = tours if isinstance(tours, list) else tours.get("data", [])
    assert len(rows) == 3, rows


def test_completing_a_tour_without_a_feedback_rating_is_refused():
    """PRD §3.7: "The completing `AssociateAgent` supplies a `feedback_rating` of 1 to 5 and may supply `feedback_notes`."

    Design: Corner/errors/tour_complete_without_a_feedback_rating_returns_invalid_request
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T11:00:00Z",
                         associate_agent_id=associate["id"])
    get_success_data(api_client.set_current_utc("2026-09-02T10:00:00Z", PLATFORM_ADMIN))
    confirm_tour(tour["id"], associate["id"])

    resp = api_client.complete_tour(tour["id"], {"feedback_notes": "No rating supplied"},
                                    make_associate_agent_headers(associate["id"]))
    data = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert data["error_id"] == "ERR_INVALID_REQUEST", data

    unchanged = get_success_data(api_client.get_tour(tour["id"], PLATFORM_ADMIN))
    assert unchanged["status"] == "CONFIRMED", unchanged


def test_a_ratingless_completion_leaves_no_survey_and_no_satisfaction_score():
    """PRD §3.7: "Completing a tour is where satisfaction data enters the system."

    Design: Corner/errors/tour_complete_without_a_feedback_rating_returns_invalid_request
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T11:00:00Z",
                         associate_agent_id=associate["id"])
    get_success_data(api_client.set_current_utc("2026-09-02T10:00:00Z", PLATFORM_ADMIN))
    confirm_tour(tour["id"], associate["id"])
    api_client.complete_tour(tour["id"], {"feedback_notes": "No rating supplied"},
                             make_associate_agent_headers(associate["id"]))

    surveys = get_success_data(api_client.list_surveys(
        PLATFORM_ADMIN, params={"agent_id": lead["id"]},
    ))
    rows = surveys if isinstance(surveys, list) else surveys.get("data", [])
    assert rows == [], rows

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent["satisfaction_score"] is None, agent


def test_run_ops_cancels_a_confirmed_tour_past_its_no_show_grace():
    """PRD §3.10: "cancels confirmed tours whose `scheduled_at` plus the 30-minute no-show grace has already passed, moving them to `CANCELLED_NO_SHOW` and recomputing the lead agent's `tours_in_week`".

    Design: Corner/endpoints/run_ops_marks_a_confirmed_tour_as_cancelled_no_show_after_the_grace
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    stale_client = create_client(full_name="Tina Tour", service_area_code="98101")
    fresh_client = create_client(full_name="Uma View", service_area_code="98102")
    assign_client(stale_client["id"])
    assign_client(fresh_client["id"])

    stale = schedule_tour(stale_client["id"], "2026-09-02T10:00:00Z",
                          associate_agent_id=associate["id"])
    fresh = schedule_tour(fresh_client["id"], "2026-09-02T16:00:00Z",
                          associate_agent_id=associate["id"])
    get_success_data(api_client.set_current_utc("2026-09-02T09:30:00Z", PLATFORM_ADMIN))
    confirm_tour(stale["id"], associate["id"])
    # The second tour opens its window at 14:00; confirm it there so the
    # checkpoint can later see it still inside its 30-minute no-show grace.
    get_success_data(api_client.set_current_utc("2026-09-02T15:00:00Z", PLATFORM_ADMIN))
    confirm_tour(fresh["id"], associate["id"])

    get_success_data(api_client.set_current_utc("2026-09-02T10:31:00Z", PLATFORM_ADMIN))
    get_success_data(api_client.run_region_ops(region["id"], PLATFORM_ADMIN))

    stale_after = get_success_data(api_client.get_tour(stale["id"], PLATFORM_ADMIN))
    fresh_after = get_success_data(api_client.get_tour(fresh["id"], PLATFORM_ADMIN))
    assert stale_after["status"] == "CANCELLED_NO_SHOW", stale_after
    assert fresh_after["status"] == "CONFIRMED", fresh_after


def test_run_ops_leaves_a_tour_inside_its_grace_window_alone():
    """PRD §3.10: "The checkpoint never reads wall-clock time — it compares against the logical clock."

    Design: Corner/endpoints/run_ops_marks_a_confirmed_tour_as_cancelled_no_show_after_the_grace
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    client = create_client(full_name="Uma View", service_area_code="98102")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T16:00:00Z",
                         associate_agent_id=associate["id"])
    get_success_data(api_client.set_current_utc("2026-09-02T15:00:00Z", PLATFORM_ADMIN))
    confirm_tour(tour["id"], associate["id"])

    get_success_data(api_client.set_current_utc("2026-09-02T15:30:00Z", PLATFORM_ADMIN))
    get_success_data(api_client.run_region_ops(region["id"], PLATFORM_ADMIN))

    tours = get_success_data(api_client.list_tours(
        PLATFORM_ADMIN, params={"lead_agent_id": lead["id"], "status": "CONFIRMED"},
    ))
    rows = tours if isinstance(tours, list) else tours.get("data", [])
    assert len(rows) == 1, rows


def test_cancelling_a_completed_tour_is_refused():
    """PRD §3.7: "Tours can also end without a completion."

    Design: Corner/state_machines/tour_cancel_from_already_completed_returns_invalid_state
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T11:00:00Z",
                         associate_agent_id=associate["id"])
    get_success_data(api_client.set_current_utc("2026-09-02T10:00:00Z", PLATFORM_ADMIN))
    confirm_tour(tour["id"], associate["id"])
    get_success_data(api_client.complete_tour(
        tour["id"], {"feedback_rating": 4}, make_associate_agent_headers(associate["id"]),
    ))

    resp = api_client.cancel_tour(tour["id"], OPERATIONS_COORDINATOR)
    data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert data["error_id"] == "ERR_INVALID_STATE", data

    unchanged = get_success_data(api_client.get_tour(tour["id"], PLATFORM_ADMIN))
    assert unchanged["status"] == "COMPLETED", unchanged


def test_no_show_on_a_completed_tour_is_refused():
    """PRD §3.7: "A marked no-show moves a confirmed tour to `CANCELLED_NO_SHOW`, voiding it from the lead agent's tour load and recomputing `tours_in_week`".

    Design: Corner/state_machines/tour_cancel_from_already_completed_returns_invalid_state
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T11:00:00Z",
                         associate_agent_id=associate["id"])
    get_success_data(api_client.set_current_utc("2026-09-02T10:00:00Z", PLATFORM_ADMIN))
    confirm_tour(tour["id"], associate["id"])
    get_success_data(api_client.complete_tour(
        tour["id"], {"feedback_rating": 4}, make_associate_agent_headers(associate["id"]),
    ))

    resp = api_client.no_show_tour(tour["id"], make_associate_agent_headers(associate["id"]))
    data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert data["error_id"] == "ERR_INVALID_STATE", data


def test_a_no_show_leaves_the_agents_satisfaction_score_untouched():
    """PRD §3.7: "A marked no-show moves a confirmed tour to `CANCELLED_NO_SHOW`, voiding it from the lead agent's tour load and recomputing `tours_in_week`; crucially, no feedback was captured, so the agent's `satisfaction_score` is unaffected."

    Design: Corner/state_machines/tour_cancel_from_already_completed_returns_invalid_state
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    associate = create_associate_agent(region["id"], home_zip="98102")
    client = create_client(full_name="Tina Tour", service_area_code="98101")
    assign_client(client["id"])
    tour = schedule_tour(client["id"], "2026-09-02T11:00:00Z",
                         associate_agent_id=associate["id"])
    get_success_data(api_client.set_current_utc("2026-09-02T10:00:00Z", PLATFORM_ADMIN))
    confirm_tour(tour["id"], associate["id"])

    no_show = get_success_data(api_client.no_show_tour(
        tour["id"], make_associate_agent_headers(associate["id"]),
    ))
    assert no_show["status"] == "CANCELLED_NO_SHOW", no_show

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent["satisfaction_score"] is None, agent