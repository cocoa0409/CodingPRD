"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "IATA_CODE": "SCK",
    "TIMEZONE": "America/Los_Angeles",
    "BASE_FARE_CENTS": 9900,
    "WEEKLY_FREQUENCY_CAP": 2,
    "SEASON_LABEL": "Spring 2027",
    "WINDOW_START_DATE": "2027-03-01",
    "WINDOW_END_DATE": "2027-03-31",
    "DEPARTURE_TIME_LOCAL": "07:30",
    "BLOCK_MINUTES": 240,
    "TAIL_NUMBER": "N901NV",
    "SEAT_CAPACITY": 156,
    "DAILY_UTILIZATION_CAP_MINUTES": 480,
    "PEAK_DAY_CAP_MINUTES": 720,
    "BASE_CODE": "SCK",
    "EMPLOYEE_NUMBER": "E1001",
    "CREW_ROLE": "CAPTAIN",
    "SUPPLIER_CODE": "HTL-SFB-1",
    "COMPONENT_KIND": "HOTEL",
    "NET_COST_CENTS": 12000,
    "SELL_PRICE_CENTS": 20000,
    "PASSENGER_COUNT": 1,
    "BOOKING_KIND": "AIR_ONLY",
    "ANCILLARY_KIND": "CHECKED_BAG",
    "ANCILLARY_AMOUNT_CENTS": 3500,
    "REASON_CODE": "WEATHER",
    "PERIOD_START_DATE": "2027-03-01",
    "PERIOD_END_DATE": "2027-03-31",
}


def create_station_payload(**overrides) -> dict:
    defaults = {
        "iata_code": DEFAULTS["IATA_CODE"],
        "station_kind": "ORIGIN_SMALL_CITY",
        "timezone": DEFAULTS["TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "base_fare_cents": DEFAULTS["BASE_FARE_CENTS"],
        "weekly_frequency_cap": DEFAULTS["WEEKLY_FREQUENCY_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_season_window_payload(**overrides) -> dict:
    defaults = {
        "season_label": DEFAULTS["SEASON_LABEL"],
        "window_start_date": DEFAULTS["WINDOW_START_DATE"],
        "window_end_date": DEFAULTS["WINDOW_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_publication_payload(**overrides) -> dict:
    defaults = {
        "operating_days_mask": [1],
        "first_operating_date": "2027-03-01",
        "last_operating_date": "2027-03-01",
        "departure_time_local": DEFAULTS["DEPARTURE_TIME_LOCAL"],
        "block_minutes": DEFAULTS["BLOCK_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "tail_number": DEFAULTS["TAIL_NUMBER"],
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
        "daily_utilization_cap_minutes": DEFAULTS["DAILY_UTILIZATION_CAP_MINUTES"],
        "peak_day_cap_minutes": DEFAULTS["PEAK_DAY_CAP_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_base_payload(**overrides) -> dict:
    defaults = {
        "base_code": DEFAULTS["BASE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    defaults = {
        "employee_number": DEFAULTS["EMPLOYEE_NUMBER"],
        "crew_role": DEFAULTS["CREW_ROLE"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_supplier_offer_payload(**overrides) -> dict:
    defaults = {
        "supplier_code": DEFAULTS["SUPPLIER_CODE"],
        "component_kind": DEFAULTS["COMPONENT_KIND"],
        "net_cost_cents": DEFAULTS["NET_COST_CENTS"],
        "sell_price_cents": DEFAULTS["SELL_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "passenger_count": DEFAULTS["PASSENGER_COUNT"],
        "booking_kind": DEFAULTS["BOOKING_KIND"],
    }
    defaults.update(overrides)
    return defaults


def create_ancillary_payload(**overrides) -> dict:
    defaults = {
        "ancillary_kind": DEFAULTS["ANCILLARY_KIND"],
        "amount_cents": DEFAULTS["ANCILLARY_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_disruption_payload(**overrides) -> dict:
    defaults = {
        "reason_code": DEFAULTS["REASON_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_settlement_payload(**overrides) -> dict:
    defaults = {
        "supplier_code": DEFAULTS["SUPPLIER_CODE"],
        "period_start_date": DEFAULTS["PERIOD_START_DATE"],
        "period_end_date": DEFAULTS["PERIOD_END_DATE"],
    }
    defaults.update(overrides)
    return defaults
