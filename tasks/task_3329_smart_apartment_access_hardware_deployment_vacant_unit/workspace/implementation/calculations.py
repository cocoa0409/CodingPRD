"""Calculation rules (SCAFFOLD table 3 / PRD 2.5, 2.10, 2.11, 3.3, 3.7, 3.8)."""

import math
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from db import clock

# --- named constants (SCAFFOLD `constants`) --------------------------------
IDENTITY_VERIFICATION_TTL_MINUTES = 60
MAX_VERIFY_ATTEMPTS = 3
REQUIRED_NOTICE_HOURS_STANDARD = 48
REQUIRED_NOTICE_HOURS_EMERGENCY = 24
NOTICE_WINDOW_OPEN_HOUR = 8
NOTICE_WINDOW_CLOSE_HOUR = 20
ESTIMATED_INSTALL_MINUTES = 120
INSTALL_BUFFER_MINUTES = 30
BATTERY_DRAIN_PER_SCAN = 1
LOW_BATTERY_ALERT_PCT = 20
NET_RSSI_THRESHOLD_DBM_POINT_TO_POINT = -67
NET_RSSI_THRESHOLD_DBM_FIELD_MESH = -75
NET_RSSI_THRESHOLD_DBM_HUB_RELAY = -80
ESTIMATED_JOB_RESERVE_CENTS = 2000
AGE_PENALTY_DB_PER_DAY = 0.1

# vacant-unit setpoint constants
DEFAULT_VACANT_SETPOINT_C = 26.0
HOT_VACANT_SETPOINT_C = 27.0
HOT_FORECAST_THRESHOLD_C = 30
SETPOINT_MIN_C = 15.0
SETPOINT_MAX_C = 27.0
OCCUPIED_SETPOINT_C = 22.0
HUMIDITY_STRESS_THRESHOLD_PCT = 60

# maintenance accrual constants
BASE_VISIT_CENTS = 2000
EMERGENCY_SURCHARGE_CENTS = 1500
HOURLY_CENTS = 700

# labor constants
LABOR_BASE_HOURS = {
    "SMART_LOCK": 0.5,
    "THERMOSTAT": 0.4,
    "LEAK_SENSOR": 0.25,
    "COMMUNITY_ACCESS": 0.75,
    "HUB": 1.0,
}
TIER_THRESHOLD_HOURS = 1.0
REWORK_RATE = 0.25

FIRMWARE_SCORES = {"LATEST": 100, "OLD": 40, "CRITICAL": 0}
W_BATTERY = 0.5
W_FIRMWARE = 0.3
W_ALERTS = 0.2
ALERT_PENALTY_PER_OPEN = 25


def _round(value, places):
    """Half-up rounding to `places` decimal places, returned as float."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def clamp(value, low, high):
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# vacant_unit_setpoint_c
# ---------------------------------------------------------------------------
def vacant_unit_setpoint_c(forecast, humidity):
    if humidity >= HUMIDITY_STRESS_THRESHOLD_PCT and forecast >= 27:
        return _round(clamp(24.0, SETPOINT_MIN_C, SETPOINT_MAX_C), 1)
    base = DEFAULT_VACANT_SETPOINT_C
    if forecast >= HOT_FORECAST_THRESHOLD_C:
        base = HOT_VACANT_SETPOINT_C
    return _round(clamp(base, SETPOINT_MIN_C, SETPOINT_MAX_C), 1)


def occupied_setpoint_c():
    return _round(OCCUPIED_SETPOINT_C, 1)


# ---------------------------------------------------------------------------
# maintenance_budget_accrual_cents
# ---------------------------------------------------------------------------
def maintenance_accrual_cents(is_emergency, hours, final):
    if final:
        hours = hours if hours is not None else 0.0
    cost = BASE_VISIT_CENTS
    if is_emergency:
        cost += EMERGENCY_SURCHARGE_CENTS
    cost += int(math.ceil(float(hours))) * HOURLY_CENTS
    return cost


# ---------------------------------------------------------------------------
# device_battery_health_score
# ---------------------------------------------------------------------------
def device_battery_health_score(battery_pct, firmware_version, open_alert_count):
    firmware_score = FIRMWARE_SCORES.get(firmware_version, 0)
    alert_score = max(0, 100 - ALERT_PENALTY_PER_OPEN * open_alert_count)
    t1 = _round(W_BATTERY * battery_pct, 1)
    t2 = _round(W_FIRMWARE * firmware_score, 1)
    t3 = _round(W_ALERTS * alert_score, 1)
    return _round(t1 + t2 + t3, 1)


# ---------------------------------------------------------------------------
# building_connectivity_ok
# ---------------------------------------------------------------------------
def _as_utc(moment):
    if isinstance(moment, str):
        text = moment.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def building_connectivity_ok(building):
    design = building.get("network_design")
    threshold = {
        "POINT_TO_POINT": NET_RSSI_THRESHOLD_DBM_POINT_TO_POINT,
        "FIELD_MESH": NET_RSSI_THRESHOLD_DBM_FIELD_MESH,
        "HUB_RELAY": NET_RSSI_THRESHOLD_DBM_HUB_RELAY,
    }.get(design)
    rssi = building.get("wifi_rssi_dbm")
    if threshold is None or rssi is None:
        return False
    serviced = building.get("last_hub_service_at")
    if serviced is None:
        penalty = 0
    else:
        elapsed_days = (clock.now - _as_utc(serviced)).total_seconds() / 86400.0
        penalty = math.floor(AGE_PENALTY_DB_PER_DAY * math.floor(elapsed_days))
    effective = rssi - penalty
    return effective >= threshold


def refresh_connectivity(building):
    """Recompute the derived verdict live (PRD 2.5).

    ``connectivity_ok`` is a computed attribute, so refreshing it is not a
    modification of the resource: it does not bump ``version``, which keeps the
    optimistic-concurrency guard keyed on real writes only.
    """
    building["connectivity_ok"] = building_connectivity_ok(building)
    return building["connectivity_ok"]


# ---------------------------------------------------------------------------
# installation_labor_hours  (base -> tier -> rework -> total)
# ---------------------------------------------------------------------------
def installation_labor_hours(device_type):
    base = LABOR_BASE_HOURS.get(device_type, 0.0)
    tier = "SIMPLE" if base < TIER_THRESHOLD_HOURS else "STANDARD"
    rework = 0.0 if tier == "SIMPLE" else _round(base * REWORK_RATE, 2)
    return _round(base + rework, 2)