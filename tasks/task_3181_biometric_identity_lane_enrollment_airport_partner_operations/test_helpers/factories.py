"""Payload factories — one per creatable entity, input fields only."""
import itertools

from .constants import DEFAULT_CLOCK

_counter = itertools.count(1000)


def _uniq(prefix):
    return f"{prefix}{next(_counter)}"


_iata_counter = itertools.count(1)


def create_airport_payload(iata_code=None, **overrides):
    if iata_code is None:
        n = next(_iata_counter)
        # 3-letter uppercase code, globally unique per server run
        iata_code = chr(ord("A") + (n // 26) % 26) + chr(ord("A") + n % 26) + chr(
            ord("A") + (n // 676) % 26
        )
    defaults = {
        "iata_code": iata_code,
        "name": f"Airport {_uniq('N')}",
        "city": "Testville",
        "state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(airport_id, **overrides):
    defaults = {
        "airport_id": airport_id,
        "rev_share_rate": 0.10,
        "subscription_share_rate": 0.02,
        "monthly_minimum_cents": 10000,
        "federal_integration": False,
        "staffing_footprint_seats": 4,
        "term_months": 12,
        "effective_from": DEFAULT_CLOCK,
    }
    defaults.update(overrides)
    return defaults


def create_lane_payload(airport_id, agreement_id, **overrides):
    defaults = {
        "airport_id": airport_id,
        "agreement_id": agreement_id,
        "terminal": "T1",
        "position_index": 1,
        "open_time": "00:00",
        "close_time": "23:59",
        "capacity_hours": 4,
    }
    defaults.update(overrides)
    return defaults


def create_kiosk_payload(airport_id, **overrides):
    defaults = {
        "airport_id": airport_id,
        "code": _uniq("K-"),
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_center_payload(airport_id, **overrides):
    defaults = {
        "airport_id": airport_id,
        "name": f"Center {_uniq('C')}",
        "ambassador_capacity": 4,
    }
    defaults.update(overrides)
    return defaults


def create_ambassador_payload(airport_id, **overrides):
    defaults = {
        "airport_id": airport_id,
        "display_name": f"Amb {_uniq('A')}",
        "employee_ref": _uniq("EMP-"),
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides):
    defaults = {
        "email": f"{_uniq('user')}@example.com",
        "full_name": "Test Member",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(member_id, site_type, site_id, **overrides):
    defaults = {
        "member_id": member_id,
        "site_type": site_type,
        "site_id": site_id,
        "document_type": "PASSPORT",
        "document_number": _uniq("P"),
        "document_expiry": "2030-01-01",
        "biometric_capture_ok": True,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(member_id, **overrides):
    defaults = {
        "member_id": member_id,
        "plan": "INDIVIDUAL",
        "billing_cycle_day": 1,
    }
    defaults.update(overrides)
    return defaults


def create_discount_payload(airport_id, **overrides):
    defaults = {
        "airport_id": airport_id,
        "code": _uniq("DISC"),
        "percent_off": 10,
        "max_redemptions": 5,
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(member_id, lane_id, ambassador_id, **overrides):
    defaults = {
        "member_id": member_id,
        "lane_id": lane_id,
        "ambassador_id": ambassador_id,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides):
    defaults = {
        "name": f"Venue {_uniq('V')}",
        "venue_type": "ARENA",
        "city": "Testville",
        "state_code": "TX",
        "access_rule_mode": "AGE_18_PLUS",
    }
    defaults.update(overrides)
    return defaults


def create_venue_event_payload(venue_id, **overrides):
    defaults = {
        "venue_id": venue_id,
        "name": f"Event {_uniq('E')}",
        "start_time": "2026-10-10T10:00:00Z",
        "end_time": "2026-10-10T12:00:00Z",
        "buffer_hours": 0,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(member_id, enrollment_id, **overrides):
    defaults = {
        "member_id": member_id,
        "enrollment_id": enrollment_id,
        "reason": "IDENTITY_TAKEOVER",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_settlement_payload(**overrides):
    defaults = {
        "period_start": "2026-09-01",
        "period_end": "2026-10-01",
        "attributable_mrr_cents": 0,
        "verification_revenue_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payout_payload(**overrides):
    defaults = {
        "period_start": "2026-09-01",
        "period_end": "2026-10-01",
        "verification_revenue_cents": 0,
        "events_count": 0,
        "venue_capacity_seats": 8000,
    }
    defaults.update(overrides)
    return defaults
