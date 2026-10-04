"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}{next(_counter)}"


def create_station_payload(**overrides) -> dict:
    defaults = {
        "iata_code": _uniq("ST"),
        "bag_weight_limit_lbs": 50,
        "min_connection_minutes": 40,
    }
    defaults.update(overrides)
    return defaults


def create_fare_class_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("FC"),
        "included_bags": 2,
        "change_fee_cents": 0,
        "upgrade_discount_pct": 0,
        "credit_validity_days": 365,
        "preboard_eligible": False,
        "is_active": True,
    }
    defaults.update(overrides)
    return defaults


def create_passenger_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("Passenger "),
        "status_tier": "NONE",
        "is_min_eligible": True,
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "tail_number": _uniq("N"),
        "seat_count": 143,
        "fleet_type": "SINGLE_FLEET",
        "home_station_code": "DAL",
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    defaults = {
        "employee_ref": _uniq("C"),
        "crew_role": "CAPTAIN",
        "qualified_fleet": "SINGLE_FLEET",
        "base_station_code": "DAL",
    }
    defaults.update(overrides)
    return defaults


def create_flight_leg_payload(origin_station_id, destination_station_id,
                              **overrides) -> dict:
    defaults = {
        "flight_number": _uniq("WN"),
        "origin_station_id": origin_station_id,
        "destination_station_id": destination_station_id,
        "scheduled_departure_utc": "2026-10-01T12:00:00Z",
        "scheduled_arrival_utc": "2026-10-01T13:00:00Z",
        "turn_target_minutes": 35,
        "gate_agent_count": 2,
        "ramp_agent_count": 4,
        "capacity_seats": 143,
    }
    defaults.update(overrides)
    return defaults


def create_routing_payload(routing_date, aircraft_id, leg_ids,
                           **overrides) -> dict:
    defaults = {
        "routing_date": routing_date,
        "aircraft_id": aircraft_id,
        "leg_ids": list(leg_ids),
    }
    defaults.update(overrides)
    return defaults


def create_pairing_payload(pairing_date, crew_member_id, leg_ids,
                           **overrides) -> dict:
    defaults = {
        "pairing_date": pairing_date,
        "crew_member_id": crew_member_id,
        "leg_ids": list(leg_ids),
    }
    defaults.update(overrides)
    return defaults


def create_journey_payload(passenger_id, flight_leg_id, fare_class_id,
                           **overrides) -> dict:
    defaults = {
        "passenger_id": passenger_id,
        "flight_leg_id": flight_leg_id,
        "fare_class_id": fare_class_id,
        "base_fare_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(journeys, **overrides) -> dict:
    defaults = {
        "record_locator": _uniq("BK"),
        "channel": "DIRECT",
        "journeys": journeys,
    }
    defaults.update(overrides)
    return defaults


def create_disruption_payload(disruption_type, cause, **overrides) -> dict:
    defaults = {
        "disruption_type": disruption_type,
        "cause": cause,
    }
    defaults.update(overrides)
    return defaults
