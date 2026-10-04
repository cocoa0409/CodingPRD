"""Request-payload builders.

Each builder returns a dict that satisfies every declared constraint of the
operation it names, and accepts ``**overrides`` so a test can perturb one
field without restating the rest.  Only input fields are ever emitted;
server-computed fields are never sent.
"""

import itertools

from .constants import (
    BAND_DOUBLE,
    BAND_FAMILY,
    BAND_SOLO,
    LINE_FOOD,
    LINE_LODGING,
    LINE_RETAIL,
    LINE_TOURS,
    LOTTERY_OPEN_2027,
    LSI_LINEAR,
    RATES_DOUBLE_23000,
    RATES_FAMILY_26000,
    RATES_SOLO_19000,
    SEASON_CLOSE_2027,
    SEASON_OPEN_2027,
    STUDY_MEAN_25000_COMPARABLES,
)

_SEQUENCE = itertools.count(1)


def next_sequence():
    """A monotonically increasing integer for unique-per-test literals."""
    return next(_SEQUENCE)


def instant(year, month, day, hour=0, minute=0, second=0):
    """Build an ISO 8601 UTC instant (``...Z`` form)."""
    return "{0:04d}-{1:02d}-{2:02d}T{3:02d}:{4:02d}:{5:02d}Z".format(
        year, month, day, hour, minute, second
    )


def contract_payload(**overrides):
    """A valid POST /contracts body; term 120 months starting 2027-01-01."""
    serial = next_sequence()
    payload = {
        "park_code": "YELL",
        "contract_number": "YELL-CT-{0:05d}".format(serial),
        "term_months": 120,
        "start_date": "2027-01-01T00:00:00Z",
        "franchise_fee_rate": 0.0385,
        "employee_housing_capacity": 100,
        "lsi_annual_schedule_type": LSI_LINEAR,
        "environmental_plan_due_day_of_year": 60,
    }
    payload.update(overrides)
    return payload


def season_payload(**overrides):
    """A valid season: open 2027-06-01, close 2027-09-01, 72h lottery window."""
    payload = {
        "year": 2027,
        "open_date": SEASON_OPEN_2027,
        "close_date": SEASON_CLOSE_2027,
        "lottery_open_date": LOTTERY_OPEN_2027,
        "lottery_window_hours": 72,
    }
    payload.update(overrides)
    return payload


def service_line_payload(line_type=LINE_LODGING, **overrides):
    payload = {"line_type": line_type}
    payload.update(overrides)
    return payload


def all_service_line_types():
    return (LINE_LODGING, LINE_FOOD, LINE_RETAIL, LINE_TOURS)


def room_class_payload(**overrides):
    serial = next_sequence()
    payload = {
        "code": "CABIN_{0:04d}".format(serial),
        "total_rooms": 10,
        "peak_season_months": [6, 7, 8],
    }
    payload.update(overrides)
    return payload


def study_payload(**overrides):
    """A study whose weighted mean is exactly 25000 cents."""
    serial = next_sequence()
    payload = {
        "title": "Comparability study {0:04d}".format(serial),
        "comparables": [dict(c) for c in STUDY_MEAN_25000_COMPARABLES],
        "prepared_at": "2026-06-01T00:00:00Z",
        "valid_through": "2028-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def band_rates_payload(
    solo=RATES_SOLO_19000, double=RATES_DOUBLE_23000, family=RATES_FAMILY_26000
):
    """Exactly three band entries, one per band."""
    return [
        {"occupancy_band": BAND_SOLO, "nightly_rate_cents": solo},
        {"occupancy_band": BAND_DOUBLE, "nightly_rate_cents": double},
        {"occupancy_band": BAND_FAMILY, "nightly_rate_cents": family},
    ]


def filing_payload(season_id, room_class_id, study_id, expected_contract_version,
                   **overrides):
    payload = {
        "season_id": season_id,
        "room_class_id": room_class_id,
        "submitted_rates": band_rates_payload(),
        "reference_study_id": study_id,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def reservation_payload(season_id, room_class_id, expected_contract_version,
                        **overrides):
    """A 2-night SOLO stay inside the canonical 2027 season."""
    serial = next_sequence()
    payload = {
        "season_id": season_id,
        "room_class_id": room_class_id,
        "guest_ref": "guest-{0:04d}".format(serial),
        "check_in_date": "2027-07-10T00:00:00Z",
        "check_out_date": "2027-07-12T00:00:00Z",
        "occupancy_band": BAND_SOLO,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def receipts_report_payload(service_line_id, expected_contract_version, **overrides):
    payload = {
        "period_month": "2027-07",
        "service_line_id": service_line_id,
        "gross_receipts_cents": 20000,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def fee_statement_payload(period_month="2027-07", **overrides):
    payload = {"period_month": period_month}
    payload.update(overrides)
    return payload


def capital_project_payload(**overrides):
    serial = next_sequence()
    payload = {
        "title": "Capital project {0:04d}".format(serial),
        "asset_ref": "BLDG-{0:04d}".format(serial),
        "authorized_cost_cents": 800000,
    }
    payload.update(overrides)
    return payload


def housing_unit_payload(**overrides):
    serial = next_sequence()
    payload = {
        "unit_code": "DORM-{0:04d}".format(serial),
        "bed_count": 4,
    }
    payload.update(overrides)
    return payload


def hire_payload(season_id, service_line_id, housing_unit_id, **overrides):
    """A hire spanning the canonical 2027 season; no transport by default."""
    serial = next_sequence()
    payload = {
        "season_id": season_id,
        "service_line_id": service_line_id,
        "employee_ref": "emp-{0:04d}".format(serial),
        "housing_unit_id": housing_unit_id,
        "arrival_date": "2027-06-01T00:00:00Z",
        "departure_date": "2027-08-31T00:00:00Z",
        "needs_transport": False,
    }
    payload.update(overrides)
    return payload


def voucher_payload(hire_id, **overrides):
    payload = {
        "hire_id": hire_id,
        "origin": "Bozeman",
        "booked_seats": 1,
        "travel_date": "2027-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def incident_payload(**overrides):
    serial = next_sequence()
    payload = {
        "protocol": "WASTE",
        "severity": "MINOR",
        "occurred_at": "2027-07-01T00:00:00Z",
        "description": "Incident report {0:04d}".format(serial),
    }
    payload.update(overrides)
    return payload
