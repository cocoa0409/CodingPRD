"""Request-payload builders.

Each builder emits only the fields the PRD declares as inputs for that
endpoint, with defaults that satisfy every declared length, charset and range
rule. Optional fields are omitted unless explicitly supplied, so a caller can
exercise a declared default simply by not passing the field.

Conventions honoured here:
- money is always a JSON integer of whole US cents, never a string (PRD 2.8);
- every datetime input is a full ISO-8601 UTC instant ending in `Z`, never a
  date-only string (PRD 2.8);
- unique codes are drawn from unique-code generators so two agencies, sites,
  templates, keysets or talkgroups built in one test never collide.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    ACTION_ASSIGN,
    AGENCY_TYPE_LAW,
    ALGO_AES256,
    BACKUP_GENERATOR,
    CAUSE_RF_FAULT,
    ENC_CLEAR,
    EVENT_UNPLANNED_OUTAGE,
    KIND_NORMAL,
    MODEL_PORTABLE,
    STANDARD_P25_PHASE1,
    TG_KIND_DISPATCH,
)

# --- Unique-value generators ----------------------------------------------
# PRD 3.1 caps `agency_code` at 4-6 characters of A-Z and 0-9; PRD 3.2 allows
# 3-12 characters of uppercase letters, digits and the hyphen for `site_code`.

_agency_code_seq = itertools.count(1)
_site_code_seq = itertools.count(1)
_serial_seq = itertools.count(1)
_radio_id_seq = itertools.count(20001)
_tg_decimal_seq = itertools.count(9001)
_keyset_name_seq = itertools.count(1)
_template_name_seq = itertools.count(1)


def next_agency_code(prefix: str = "AGY") -> str:
    """A unique 4-6 character agency code of uppercase letters and digits."""
    return f"{prefix}{next(_agency_code_seq):02d}"[:6]


def next_site_code(prefix: str = "SITE") -> str:
    """A unique 3-12 character site code of uppercase letters, digits, hyphen."""
    return f"{prefix}-{next(_site_code_seq):03d}"[:12]


def next_serial_number(prefix: str = "SNX") -> str:
    """A unique 6-24 character serial of uppercase letters and digits."""
    return f"{prefix}{next(_serial_seq):06d}"


def next_radio_id() -> int:
    """A unique P25 subscriber decimal identifier inside 1..16777215."""
    return next(_radio_id_seq)


def next_tg_decimal_id() -> int:
    """A unique P25 talkgroup decimal identifier inside 1..65535."""
    return next(_tg_decimal_seq)


def next_keyset_name(prefix: str = "CKR") -> str:
    """A unique 3-40 character common key reference name."""
    return f"{prefix}-{next(_keyset_name_seq):03d}"


def next_template_name(prefix: str = "TPL") -> str:
    """A unique 1-80 character template name."""
    return f"{prefix}-{next(_template_name_seq):03d}"


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``None`` for an *omitted* field."""
    return {k: v for k, v in payload.items() if v is not None}


# --- Logical clock ---------------------------------------------------------


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    """PRD 2.5 — the SystemAdmin moves the clock by supplying `to_iso8601`."""
    return {"to_iso8601": to_iso8601}


# --- MemberAgency ---------------------------------------------------------


def agency_payload(
    name: str = "Alpha County Sheriff",
    agency_code: Optional[str] = None,
    agency_type: str = AGENCY_TYPE_LAW,
    fee_basis: Optional[str] = None,
    interop_privilege: Optional[str] = None,
    console_position_count: Optional[int] = None,
    recorder_retention_days: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD 3.1 registration payload; the four optional inputs are omitted
    unless supplied so their declared defaults apply."""
    return _prune(
        {
            "name": name,
            "agency_code": agency_code if agency_code is not None else next_agency_code(),
            "agency_type": agency_type,
            "fee_basis": fee_basis,
            "interop_privilege": interop_privilege,
            "console_position_count": console_position_count,
            "recorder_retention_days": recorder_retention_days,
        }
    )


def console_config_payload(
    console_position_count: Optional[int] = None,
    recorder_retention_days: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD 2.10 console-configuration change."""
    return _prune(
        {
            "console_position_count": console_position_count,
            "recorder_retention_days": recorder_retention_days,
        }
    )


def fee_assessment_payload(
    period_start: str, period_end: str, expected_agency_version: int
) -> Dict[str, Any]:
    """PRD 3.9 / 2.6 — the billing period plus the mandatory agency version pin."""
    return {
        "period_start": period_start,
        "period_end": period_end,
        "expected_agency_version": expected_agency_version,
    }


def payment_payload(amount_cents: int) -> Dict[str, Any]:
    """PRD 3.9 — `amount_cents` is a whole-cent integer, never a string."""
    return {"amount_cents": amount_cents}


# --- Site -----------------------------------------------------------------


def site_payload(
    site_code: Optional[str] = None,
    name: str = "Alpha Ridge Repeater",
    channel_capacity: int = 8,
    backup_power_type: str = BACKUP_GENERATOR,
    battery_runtime_minutes: Optional[int] = None,
    generator_fuel_hours: Optional[float] = None,
    migration_standard: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD 3.2 site registration; the four rating inputs are optional."""
    return _prune(
        {
            "site_code": site_code if site_code is not None else next_site_code(),
            "name": name,
            "channel_capacity": channel_capacity,
            "backup_power_type": backup_power_type,
            "battery_runtime_minutes": battery_runtime_minutes,
            "generator_fuel_hours": generator_fuel_hours,
            "migration_standard": migration_standard,
        }
    )


def coverage_payload(
    covered_test_points: int, total_test_points: int, expected_site_version: int
) -> Dict[str, Any]:
    """PRD 3.2 / 2.6 — drive-test results plus the mandatory site version pin."""
    return {
        "covered_test_points": covered_test_points,
        "total_test_points": total_test_points,
        "expected_site_version": expected_site_version,
    }


# --- RadioTemplate -------------------------------------------------------


def template_payload(
    template_name: Optional[str] = None,
    target_standard: str = STANDARD_P25_PHASE1,
    talkgroup_slot_count: int = 8,
    encryption_required: Optional[bool] = None,
) -> Dict[str, Any]:
    """PRD 3.3 root-template creation; `encryption_required` defaults to false."""
    return _prune(
        {
            "template_name": (
                template_name if template_name is not None else next_template_name()
            ),
            "target_standard": target_standard,
            "talkgroup_slot_count": talkgroup_slot_count,
            "encryption_required": encryption_required,
        }
    )


def template_revision_payload(
    expected_template_version: int,
    template_name: Optional[str] = None,
    target_standard: str = STANDARD_P25_PHASE1,
    talkgroup_slot_count: int = 8,
    encryption_required: Optional[bool] = None,
) -> Dict[str, Any]:
    """PRD 3.3 / 2.6 — the same four content inputs plus the version pin."""
    payload = template_payload(
        template_name=template_name,
        target_standard=target_standard,
        talkgroup_slot_count=talkgroup_slot_count,
        encryption_required=encryption_required,
    )
    payload["expected_template_version"] = expected_template_version
    return payload


# --- ProgrammingChangeRequest -------------------------------------------


def change_request_payload(
    template_id: str, target_agency_id: str, title: str = "Regional codeplug refresh"
) -> Dict[str, Any]:
    """PRD 3.3 change-request creation."""
    return {
        "template_id": template_id,
        "target_agency_id": target_agency_id,
        "title": title,
    }


def review_decision_payload(
    decision: str, review_comment: Optional[str] = None
) -> Dict[str, Any]:
    """PRD 3.3 board ruling; `review_comment` is optional and stored null when
    omitted."""
    return _prune({"decision": decision, "review_comment": review_comment})


# --- SubscriberUnit -----------------------------------------------------


def unit_payload(
    agency_id: str,
    serial_number: Optional[str] = None,
    radio_id: Optional[int] = None,
    model: str = MODEL_PORTABLE,
    priority_class: Optional[int] = None,
    emergency_button_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """PRD 3.4 unit creation; `priority_class` and `emergency_button_enabled`
    are optional so their declared defaults apply when omitted."""
    return _prune(
        {
            "agency_id": agency_id,
            "serial_number": (
                serial_number if serial_number is not None else next_serial_number()
            ),
            "radio_id": radio_id if radio_id is not None else next_radio_id(),
            "model": model,
            "priority_class": priority_class,
            "emergency_button_enabled": emergency_button_enabled,
        }
    )


def lifecycle_payload(
    action: str = ACTION_ASSIGN, template_id: Optional[str] = None
) -> Dict[str, Any]:
    """PRD 3.4 — `template_id` is consumed only by `ASSIGN`."""
    return _prune({"action": action, "template_id": template_id})


# --- Keyset and OTAR ----------------------------------------------------


def keyset_payload(
    keyset_name: Optional[str] = None,
    algorithm: str = ALGO_AES256,
    crypto_period_start: str = "2026-08-01T00:00:00Z",
    crypto_period_end: str = "2026-09-01T00:00:00Z",
) -> Dict[str, Any]:
    """PRD 3.5 keyset creation; the crypto period is half-open."""
    return {
        "keyset_name": keyset_name if keyset_name is not None else next_keyset_name(),
        "algorithm": algorithm,
        "crypto_period_start": crypto_period_start,
        "crypto_period_end": crypto_period_end,
    }


def keyset_decision_payload(decision: str) -> Dict[str, Any]:
    """PRD 3.5 — the SecurityOfficer supplies `APPROVE` or `REJECT`."""
    return {"decision": decision}


def otar_campaign_payload(
    keyset_id: str,
    agency_id: str,
    window_start: str = "2026-08-05T00:00:00Z",
    window_end: str = "2026-08-05T02:00:00Z",
) -> Dict[str, Any]:
    """PRD 3.5 rekey-window scheduling; the window is half-open."""
    return {
        "keyset_id": keyset_id,
        "agency_id": agency_id,
        "window_start": window_start,
        "window_end": window_end,
    }


# --- Talkgroup and InteropPatch ----------------------------------------


def talkgroup_payload(
    owner_agency_id: str,
    home_site_id: str,
    alias: str = "TG-DISP",
    tg_decimal_id: Optional[int] = None,
    kind: str = TG_KIND_DISPATCH,
    encryption_mode: str = ENC_CLEAR,
    priority_level: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD 3.6 talkgroup creation; `alias` is 1-16 characters."""
    return _prune(
        {
            "owner_agency_id": owner_agency_id,
            "home_site_id": home_site_id,
            "alias": alias,
            "tg_decimal_id": (
                tg_decimal_id if tg_decimal_id is not None else next_tg_decimal_id()
            ),
            "kind": kind,
            "encryption_mode": encryption_mode,
            "priority_level": priority_level,
        }
    )


def talkgroup_status_payload(action: str) -> Dict[str, Any]:
    """PRD 3.6 — `LOCK`, `UNLOCK` or `DECOMMISSION`."""
    return {"action": action}


def interop_patch_payload(
    source_talkgroup_id: str,
    target_talkgroup_id: str,
    requesting_agency_id: str,
    scheduled_start: str = "2026-08-01T00:00:00Z",
    scheduled_end: str = "2026-08-01T02:00:00Z",
) -> Dict[str, Any]:
    """PRD 3.6 patch request; the reserved window is half-open."""
    return {
        "source_talkgroup_id": source_talkgroup_id,
        "target_talkgroup_id": target_talkgroup_id,
        "requesting_agency_id": requesting_agency_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }


def patch_decision_payload(decision: str) -> Dict[str, Any]:
    """PRD 3.6 — the requesting dispatcher rules `ACTIVATE` or `DENY`."""
    return {"decision": decision}


# --- SiteEvent and TalkpathRequest -------------------------------------


def site_event_payload(
    site_id: str,
    event_class: str = EVENT_UNPLANNED_OUTAGE,
    cause: str = CAUSE_RF_FAULT,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD 3.7 — the window pair is required for `PLANNED_MAINTENANCE` and must
    be omitted for every other `event_class`."""
    return _prune(
        {
            "site_id": site_id,
            "event_class": event_class,
            "cause": cause,
            "window_start": window_start,
            "window_end": window_end,
        }
    )


def advance_payload(action: str) -> Dict[str, Any]:
    """PRD 3.7 — one of the seven declared site-event actions."""
    return {"action": action}


def talkpath_payload(
    site_id: str,
    talkgroup_id: str,
    unit_id: str,
    request_kind: str = KIND_NORMAL,
    site_event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD 3.8 talkpath request; `site_event_id` is optional and left null for
    routine traffic."""
    return _prune(
        {
            "site_id": site_id,
            "talkgroup_id": talkgroup_id,
            "unit_id": unit_id,
            "request_kind": request_kind,
            "site_event_id": site_event_id,
        }
    )
