"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "YARD_CODE": "NPL",
    "DWELL_BENCHMARK_HOURS": 10,
    "CLASSIFICATION_CAPACITY": 100,
    "TRAIN_SYMBOL": "MNPRV-14",
    "SCHEDULED_DEPARTURE": "2026-09-01T08:00:00Z",
    "CUTOFF_MINUTES": 60,
    "FREQUENCY_MASK": ["TUE"],
    "ROUTE_MILES": 300,
    "CRAFT": "CONDUCTOR",
    "SERVICE_DATE": "2026-09-01",
    "CREWS_AVAILABLE": 2,
    "UNIT_NUMBER": "UP 8821",
    "HORSEPOWER": 4400,
    "CUSTOMER_CODE": "ACME",
    "CUSTOMER_NAME": "Acme Shipper",
    "CAR_COUNT": 2,
    "PICKUP_BY": "2026-09-01T07:30:00Z",
    "DELIVERY_BY": "2026-09-05T00:00:00Z",
    "CAR_COUNT_PLANNED": 5,
    "CREW_HOURS_ESTIMATED": 6,
}


def create_yard_payload(**overrides) -> dict:
    defaults = {
        "yard_code": DEFAULTS["YARD_CODE"],
        "dwell_benchmark_hours": DEFAULTS["DWELL_BENCHMARK_HOURS"],
        "classification_capacity_cars": DEFAULTS["CLASSIFICATION_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_train_plan_payload(**overrides) -> dict:
    defaults = {
        "train_symbol": DEFAULTS["TRAIN_SYMBOL"],
        "scheduled_departure_utc": DEFAULTS["SCHEDULED_DEPARTURE"],
        "cutoff_minutes": DEFAULTS["CUTOFF_MINUTES"],
        "frequency_mask": list(DEFAULTS["FREQUENCY_MASK"]),
        "route_distance_miles": DEFAULTS["ROUTE_MILES"],
        "dwell_benchmark_hours": DEFAULTS["DWELL_BENCHMARK_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_pool_payload(**overrides) -> dict:
    defaults = {
        "craft": DEFAULTS["CRAFT"],
        "service_date": DEFAULTS["SERVICE_DATE"],
        "crews_available": DEFAULTS["CREWS_AVAILABLE"],
    }
    defaults.update(overrides)
    return defaults


def create_locomotive_payload(**overrides) -> dict:
    defaults = {
        "unit_number": DEFAULTS["UNIT_NUMBER"],
        "horsepower": DEFAULTS["HORSEPOWER"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "customer_code": DEFAULTS["CUSTOMER_CODE"],
        "name": DEFAULTS["CUSTOMER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "car_count": DEFAULTS["CAR_COUNT"],
        "first_mile_pickup_by": DEFAULTS["PICKUP_BY"],
        "last_mile_delivery_by": DEFAULTS["DELIVERY_BY"],
        "committed_route_miles": DEFAULTS["ROUTE_MILES"],
    }
    defaults.update(overrides)
    return defaults


def create_departure_payload(**overrides) -> dict:
    defaults = {
        "service_date": DEFAULTS["SERVICE_DATE"],
        "car_count_planned": DEFAULTS["CAR_COUNT_PLANNED"],
        "crew_hours_estimated": DEFAULTS["CREW_HOURS_ESTIMATED"],
    }
    defaults.update(overrides)
    return defaults


def create_car_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "YARD_ARRIVAL",
        "car_count": 1,
    }
    defaults.update(overrides)
    return defaults
