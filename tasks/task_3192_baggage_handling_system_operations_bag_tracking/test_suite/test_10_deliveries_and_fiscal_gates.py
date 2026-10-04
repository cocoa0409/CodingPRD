"""Delivery logistics and the claim fiscal gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_station, list_rows,
    create_bag_payload, create_report_payload, create_arrange_delivery_payload,
    delivered_bag_with_report, report_through_delivered, board_and_depart,
    make_loaded_bag, weigh_ok, create_assign_makeup_payload,
)


def test_offloading_a_bag_synthesizes_a_delivery_row_with_the_declared_default(api):
    """PRD §3.14: "Every bag carries at most one `Delivery` row, and a bag that
    reaches `HELD` or `OFFLOADED` without one has it synthesized automatically, so
    a delivery record always exists from the moment a bag stops moving normally."
    PRD §3.14: "A delivery names its `method` — `COURIER`, `PASSENGER_PICKUP` or
    `FORWARD_ON_NEXT_FLIGHT`, defaulting to `PASSENGER_PICKUP`"

    Design: Corner/entities/delivery_create_is_server_synthesized_on_offload
    """
    scenario = base_scenario()
    bag = make_loaded_bag(scenario)
    board_and_depart(scenario)

    before = list_rows(api.list_bag_deliveries(bag["id"],
                                               TEST_USERS["baggage_service_agent_headers"]))
    assert before == [], "no delivery row exists before the bag stops moving normally"

    offloaded = validate_success(api.offload_bag(bag["id"], TEST_USERS["load_agent_headers"]), 200)
    assert offloaded["custody_status"] == "OFFLOADED"

    rows = list_rows(api.list_bag_deliveries(bag["id"],
                                             TEST_USERS["baggage_service_agent_headers"]))
    assert len(rows) == 1, "the offload synthesizes exactly one delivery row"
    assert rows[0]["method"] == "PASSENGER_PICKUP", "the default method is applied rather than left null"
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["proof_required"] is False
    assert rows[0].get("delivered_utc") is None
    assert rows[0].get("schedule_utc") is None or rows[0].get("scheduled_utc") is None


def test_arranging_delivery_in_the_past_is_refused(api):
    """PRD §3.14: "Arranging delivery is where the promised instant is pinned
    down, and the instant must not precede the current logical clock instant; a
    promise set in the past is refused with `ERR_DELIVERY_IN_PAST` (422)."

    Design: Corner/validations/delivery_schedule_may_not_precede_the_logical_clock
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"]), TEST_USERS["acceptance_agent_headers"]))
    report = get_success_data(api.create_report(
        create_report_payload(bag["id"], scenario["st"], report_type="DELAYED"),
        TEST_USERS["baggage_service_agent_headers"]))
    api.investigate_report(report["id"], TEST_USERS["baggage_service_agent_headers"])

    response = api.arrange_delivery(
        report["id"],
        create_arrange_delivery_payload(scheduled_utc="2026-09-01T06:00:00Z"),
        TEST_USERS["baggage_service_agent_headers"])
    validate_error(response, ApiErrorId.ERR_DELIVERY_IN_PAST, 422)

    still = get_success_data(api.get_report(report["id"],
                                            TEST_USERS["baggage_service_agent_headers"]))
    assert still["status"] == "INVESTIGATING"


def test_arranging_delivery_after_the_clock_pins_the_instant(api):
    """PRD §3.14: "A pending delivery moves to `IN_TRANSIT` on its own, without a
    dedicated call: it happens either when the linked mishandled report reaches
    `DELIVERY_ARRANGED` — at which point the delivery takes its `method` and
    `scheduled_utc` from the report's arrangement"

    Design: Corner/validations/delivery_schedule_may_not_precede_the_logical_clock
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"]), TEST_USERS["acceptance_agent_headers"]))
    report = get_success_data(api.create_report(
        create_report_payload(bag["id"], scenario["st"], report_type="DELAYED"),
        TEST_USERS["baggage_service_agent_headers"]))
    api.investigate_report(report["id"], TEST_USERS["baggage_service_agent_headers"])

    arranged = validate_success(api.arrange_delivery(
        report["id"],
        create_arrange_delivery_payload(delivery_method="COURIER",
                                        scheduled_utc="2026-09-01T09:00:00Z"),
        TEST_USERS["baggage_service_agent_headers"]), 200)
    assert arranged["status"] == "DELIVERY_ARRANGED"
    assert arranged["delivery_method"] == "COURIER"

    rows = list_rows(api.list_report_deliveries(
        report["id"], TEST_USERS["baggage_service_agent_headers"]))
    assert len(rows) == 1
    assert rows[0]["scheduled_utc"] == "2026-09-01T09:00:00Z"
    assert rows[0]["status"] == "IN_TRANSIT"
    assert rows[0]["mishandled_report_id"] == report["id"]


def test_a_proof_flagged_delivery_cannot_be_completed_without_proof(api):
    """PRD §3.14: "Completing a delivery is available from `IN_TRANSIT` or from
    `OUT_FOR_DELIVERY`, and both routes carry the same proof requirement: unless
    the row's `proof_required` flag is false, a `proof_of_delivery` must be
    supplied, and its absence is refused with `ERR_PROOF_OF_DELIVERY_REQUIRED`
    (409)."

    Design: Corner/validations/proof_of_delivery_required_blocks_completion_until_supplied
    """
    scenario = base_scenario()
    bag = make_loaded_bag(scenario)
    board_and_depart(scenario)

    report = get_success_data(api.create_report(
        create_report_payload(bag["id"], scenario["st"], report_type="DELAYED"),
        TEST_USERS["baggage_service_agent_headers"]))
    api.investigate_report(report["id"], TEST_USERS["baggage_service_agent_headers"])
    api.arrange_delivery(
        report["id"],
        create_arrange_delivery_payload(delivery_method="COURIER",
                                        scheduled_utc="2026-09-01T14:30:00Z",
                                        proof_required=True),
        TEST_USERS["baggage_service_agent_headers"])

    rows = list_rows(api.list_report_deliveries(
        report["id"], TEST_USERS["baggage_service_agent_headers"]))
    delivery = rows[0]
    assert delivery["proof_required"] is True
    api.dispatch_delivery(delivery["id"], "CR-7781",
                          TEST_USERS["baggage_service_agent_headers"])

    refused = api.complete_delivery(delivery["id"], {},
                                    TEST_USERS["baggage_service_agent_headers"])
    validate_error(refused, ApiErrorId.ERR_PROOF_OF_DELIVERY_REQUIRED, 409)

    still = get_success_data(api.get_delivery(delivery["id"],
                                              TEST_USERS["baggage_service_agent_headers"]))
    assert still["status"] == "OUT_FOR_DELIVERY"
    assert still.get("delivered_utc") is None


def test_the_proof_flagged_delivery_completes_once_proof_is_supplied(api):
    """PRD §3.14: "A completed delivery moves to `DELIVERED` and stamps the
    current logical clock instant into `delivered_utc`."
    PRD §3.14: "unless the row's `proof_required` flag is false, a
    `proof_of_delivery` must be supplied"

    Design: Corner/validations/proof_of_delivery_required_blocks_completion_until_supplied
    """
    scenario = base_scenario()
    bag = make_loaded_bag(scenario)
    board_and_depart(scenario)

    report = get_success_data(api.create_report(
        create_report_payload(bag["id"], scenario["st"], report_type="DELAYED"),
        TEST_USERS["baggage_service_agent_headers"]))
    api.investigate_report(report["id"], TEST_USERS["baggage_service_agent_headers"])
    api.arrange_delivery(
        report["id"],
        create_arrange_delivery_payload(delivery_method="COURIER",
                                        scheduled_utc="2026-09-01T14:30:00Z",
                                        proof_required=True),
        TEST_USERS["baggage_service_agent_headers"])
    delivery = list_rows(api.list_report_deliveries(
        report["id"], TEST_USERS["baggage_service_agent_headers"]))[0]
    api.dispatch_delivery(delivery["id"], "CR-7781",
                          TEST_USERS["baggage_service_agent_headers"])

    set_clock("2026-09-01T14:40:00Z")
    completed = validate_success(api.complete_delivery(
        delivery["id"], {"proof_of_delivery": "SIGNATURE-4417"},
        TEST_USERS["baggage_service_agent_headers"]), 200)
    assert completed["status"] == "DELIVERED"
    assert completed["delivered_utc"] == "2026-09-01T14:40:00Z"


def test_a_claim_filed_above_the_carrier_ceiling_is_rejected(api):
    """PRD §3.12: "A request exceeding the carrier's cap is refused outright with
    `ERR_COMPENSATION_OVER_CAP` (422)."

    Design: Corner/validations/claim_filing_above_the_airline_ceiling_is_rejected
    """
    scenario = base_scenario(airline_overrides={"compensation_cap_cents": 100000})
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    report = get_success_data(api.create_report(
        create_report_payload(bag["id"], scenario["st"], report_type="DELAYED"),
        TEST_USERS["baggage_service_agent_headers"]))
    api.investigate_report(report["id"], TEST_USERS["baggage_service_agent_headers"])

    over = api.file_claim(report["id"], 150000, TEST_USERS["baggage_service_agent_headers"])
    validate_error(over, ApiErrorId.ERR_COMPENSATION_OVER_CAP, 422)

    unchanged = get_success_data(api.get_report(report["id"],
                                                TEST_USERS["baggage_service_agent_headers"]))
    assert unchanged["claim_status"] == "NONE"


def test_a_claim_filed_at_the_carrier_ceiling_is_accepted(api):
    """PRD §3.12: "Filing also moves the report's `claim_status` to `FILED` and
    copies the requested amount into the report's `claim_amount_cents` as the
    amount claimed by the passenger"

    Design: Corner/validations/claim_filing_above_the_airline_ceiling_is_rejected
    """
    scenario = base_scenario(airline_overrides={"compensation_cap_cents": 100000})
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    report = get_success_data(api.create_report(
        create_report_payload(bag["id"], scenario["st"], report_type="DELAYED"),
        TEST_USERS["baggage_service_agent_headers"]))
    api.investigate_report(report["id"], TEST_USERS["baggage_service_agent_headers"])

    claim = validate_success(api.file_claim(
        report["id"], 100000, TEST_USERS["baggage_service_agent_headers"]), 201)
    assert claim["requested_amount_cents"] == 100000

    updated = get_success_data(api.get_report(report["id"],
                                              TEST_USERS["baggage_service_agent_headers"]))
    assert updated["claim_status"] == "FILED"
    assert updated["claim_amount_cents"] == 100000

    rows = list_rows(api.list_report_claims(report["id"],
                                            TEST_USERS["baggage_service_agent_headers"]))
    assert len(rows) == 1


def test_clearing_an_outage_that_is_not_active_is_refused(api):
    """PRD §3.9: "The outage is cleared through a dedicated clearance
    operation, which flips `outage_active` to false"
    PRD §2.13: "The target resource must be in a state that admits the requested transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/errors/outage_clear_without_an_active_outage_is_rejected
    """
    scenario = base_scenario()
    response = api.clear_outage(scenario["st"], TEST_USERS["platform_admin_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    station = get_station(scenario["st"])
    assert station["outage_active"] is False
    assert station.get("outage_started_utc") is None
    assert station["posture"] == "OPEN"


def test_declaring_then_clearing_an_outage_restores_open_posture(api):
    """PRD §3.9: "An airport administrator declares a sortation-system outage by
    naming the station, which sets the station's `outage_active` flag to true,
    stamps the current logical clock instant into `outage_started_utc`, and forces
    the station's posture to `SUSPENDED`."
    PRD §3.9: "which flips `outage_active` to false and recomputes the station's
    posture from the ordinary posture rule"

    Design: Corner/errors/outage_clear_without_an_active_outage_is_rejected
    """
    scenario = base_scenario()
    from test_helpers import declare_outage

    suspended = declare_outage(scenario)
    assert suspended["outage_active"] is True
    assert suspended["posture"] == "SUSPENDED"
    assert suspended["outage_started_utc"] == "2026-09-01T07:00:00Z"

    cleared = validate_success(api.clear_outage(
        scenario["st"], TEST_USERS["platform_admin_headers"]), 200)
    assert cleared["outage_active"] is False
    assert cleared["posture"] == "OPEN"

    again = api.clear_outage(scenario["st"], TEST_USERS["platform_admin_headers"])
    validate_error(again, ApiErrorId.ERR_INVALID_STATE, 409)