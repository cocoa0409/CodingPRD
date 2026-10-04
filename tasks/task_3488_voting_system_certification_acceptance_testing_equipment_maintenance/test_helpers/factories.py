"""Payload factories — one per entity, input fields only.

Only client-supplied (source: input) fields appear here; system-managed and
computed fields are never sent. Optional fields are omitted from the payload
when their value is None, so a factory call can rely on server-side defaults
(e.g. omitting max_concurrent_campaigns exercises the declared default of 3).

Uniqueness-scoped identifiers (lab_code, serial_number, badge_no,
seal_number) default to uuid-suffixed values so repeated factory calls within
one test never collide accidentally.

The two OCC-guarded writes surface their expected-version fields as explicit
factory parameters: ``expected_election_definition_version`` on the layout
PUT and ``expected_voting_system_version`` on modification create.
"""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# Test-data defaults (chosen to satisfy PRD windows against the boot clock
# 2026-09-01T00:00:00Z; these are fixtures data, not PRD thresholds).
DEFAULTS = {
    "VENDOR_NAME": "Election Systems and Software",
    "MODEL_NAME": "DS450",
    "BASELINE_VERSION": "1.0.0",
    "HARDWARE_CLASS": "OPTICAL_SCANNER",
    "LAB_NAME": "Alpha Test Lab",
    "ACCREDITATION_SCOPE": "DUAL",
    "GUIDELINES_BASELINE": "VVSG_2_0",
    "STATE_CODE": "CA",
    "JURISDICTION_NAME": "Mono County",
    "BUDGET_TOTAL_CENTS": 100_000_000,
    "OFFICIAL_FULL_NAME": "Ann Lee",
    "QUANTITY": 10,
    "UNIT_PRICE_CENTS": 2_500_000,
    "ELECTION_NAME": "2026 General",
    # 2026-11-03 is >= 30 days after the 2026-09-01 boot clock (creation lead)
    # and >= 14 days out at boot (lock freeze window).
    "ELECTION_DATE": "2026-11-03",
    "PRECINCT_COUNT": 3,
    "PAPER_WEIGHT_GSM": 90,
    "PAPER_THICKNESS_MICRONS": 100,
    "PAPER_COATING": "UNCOATED",
    "WORK_TYPE": "PREVENTIVE",
    "SCHEDULED_START": "2026-09-05T00:00:00Z",
    "SCHEDULED_END": "2026-09-06T00:00:00Z",
    "COMPONENT_CODES": ["AUDIT_LOG_SERVICE"],
    "AUDIT_TYPE": "RISK_LIMITING",
    "STORAGE_TEMPERATURE_C": 20,
    "STORAGE_HUMIDITY_PCT": 40,
}

DEFAULT_BALLOT_LAYOUT = {"contests": [{"code": "PRES", "choices": 4}]}
DEFAULT_EXPECTED_TALLIES = {"PRES": 12000, "SEN": 8000}
DEFAULT_SCANNED_TALLIES = {"PRES": 12000, "SEN": 8000}


# ---------------------------------------------------------------------------
# Platform clock
# ---------------------------------------------------------------------------
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# VotingSystem / TestLaboratory / CertificationCampaign / Certificate
# ---------------------------------------------------------------------------
def create_voting_system_payload(**overrides) -> dict:
    payload = {
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "model_name": DEFAULTS["MODEL_NAME"],
        "software_baseline_version": DEFAULTS["BASELINE_VERSION"],
        "hardware_class": DEFAULTS["HARDWARE_CLASS"],
    }
    payload.update(overrides)
    return payload


def create_test_laboratory_payload(**overrides) -> dict:
    payload = {
        "lab_code": _uniq("LAB"),
        "lab_name": DEFAULTS["LAB_NAME"],
        "accreditation_scope": DEFAULTS["ACCREDITATION_SCOPE"],
    }
    payload.update(overrides)
    # max_concurrent_campaigns is optional (server default 3): omit when None.
    if payload.get("max_concurrent_campaigns") is None:
        payload.pop("max_concurrent_campaigns", None)
    return payload


def create_campaign_payload(voting_system_id: str, lab_id: str, **overrides) -> dict:
    payload = {
        "voting_system_id": voting_system_id,
        "lab_id": lab_id,
        "guidelines_baseline": DEFAULTS["GUIDELINES_BASELINE"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    # state_code optional; null means a federal-only campaign -> omit when None.
    if payload.get("state_code") is None:
        payload.pop("state_code", None)
    return payload


def campaign_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


def certificate_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


# ---------------------------------------------------------------------------
# Jurisdiction / ElectionOfficial
# ---------------------------------------------------------------------------
def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["JURISDICTION_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "budget_total_cents": DEFAULTS["BUDGET_TOTAL_CENTS"],
    }
    payload.update(overrides)
    return payload


def budget_adjustment_payload(delta_cents: int, reason: str = "adjustment") -> dict:
    return {"delta_cents": delta_cents, "reason": reason}


def create_official_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["OFFICIAL_FULL_NAME"],
        "badge_no": _uniq("B"),
    }
    payload.update(overrides)
    return payload


def official_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


# ---------------------------------------------------------------------------
# Procurement / AcceptanceTest
# ---------------------------------------------------------------------------
def create_procurement_payload(
    jurisdiction_id: str, voting_system_id: str, certificate_id: str, **overrides
) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "voting_system_id": voting_system_id,
        "certificate_id": certificate_id,
        "quantity": DEFAULTS["QUANTITY"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def procurement_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


def create_acceptance_test_payload(
    test_type: str = "HARDWARE_DIAGNOSTIC",
    critical_defects: int = 0,
    major_defects: int = 0,
    minor_defects: int = 0,
    **overrides,
) -> dict:
    payload = {
        "test_type": test_type,
        "critical_defects": critical_defects,
        "major_defects": major_defects,
        "minor_defects": minor_defects,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ElectionDefinition / LogicAccuracyTest
# ---------------------------------------------------------------------------
def create_election_definition_payload(
    jurisdiction_id: str, procurement_id: str, **overrides
) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "procurement_id": procurement_id,
        "name": DEFAULTS["ELECTION_NAME"],
        "election_date": DEFAULTS["ELECTION_DATE"],
        "precinct_count": DEFAULTS["PRECINCT_COUNT"],
    }
    payload.update(overrides)
    return payload


def put_layout_payload(expected_election_definition_version: int, **overrides) -> dict:
    """OCC-guarded layout write: the expected definition version is required."""
    payload = {
        "ballot_layout": DEFAULT_BALLOT_LAYOUT,
        "paper_weight_gsm": DEFAULTS["PAPER_WEIGHT_GSM"],
        "paper_thickness_microns": DEFAULTS["PAPER_THICKNESS_MICRONS"],
        "paper_coating": DEFAULTS["PAPER_COATING"],
        "expected_election_definition_version": expected_election_definition_version,
    }
    payload.update(overrides)
    return payload


def election_definition_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


def create_la_test_payload(
    expected_tallies=None, scanned_tallies=None, **overrides
) -> dict:
    payload = {
        "expected_tallies": (
            dict(DEFAULT_EXPECTED_TALLIES) if expected_tallies is None else expected_tallies
        ),
        "scanned_tallies": (
            dict(DEFAULT_SCANNED_TALLIES) if scanned_tallies is None else scanned_tallies
        ),
    }
    payload.update(overrides)
    return payload


def la_test_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


# ---------------------------------------------------------------------------
# EquipmentUnit / CustodyTransfer / MaintenanceWorkOrder
# ---------------------------------------------------------------------------
def create_equipment_unit_payload(
    jurisdiction_id: str, voting_system_id: str, initial_custodian_id: str, **overrides
) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "voting_system_id": voting_system_id,
        "serial_number": _uniq("SN"),
        "initial_custodian_id": initial_custodian_id,
    }
    payload.update(overrides)
    return payload


def equipment_unit_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


def record_usage_payload(cycles_used: int) -> dict:
    return {"cycles_used": cycles_used}


def create_custody_transfer_payload(
    to_official_id: str, seal_number=None, seal_intact: bool = True, **overrides
) -> dict:
    payload = {
        "to_official_id": to_official_id,
        "seal_number": seal_number if seal_number is not None else _uniq("SEAL"),
        "seal_intact": seal_intact,
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(equipment_unit_id: str, **overrides) -> dict:
    payload = {
        "equipment_unit_id": equipment_unit_id,
        "work_type": DEFAULTS["WORK_TYPE"],
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
    }
    payload.update(overrides)
    # Calibration fields are required iff work_type == CALIBRATION; omit when
    # None so non-calibration orders never carry them.
    for field in ("calibration_paper_weight_gsm", "calibration_paper_thickness_microns"):
        if payload.get(field) is None:
            payload.pop(field, None)
    return payload


def work_order_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


# ---------------------------------------------------------------------------
# SoftwareModification
# ---------------------------------------------------------------------------
def create_software_modification_payload(
    voting_system_id: str, expected_voting_system_version: int, **overrides
) -> dict:
    """OCC-guarded modification proposal: the expected system version is
    required."""
    payload = {
        "voting_system_id": voting_system_id,
        "description": "Software modification",
        "component_codes": list(DEFAULTS["COMPONENT_CODES"]),
        "expected_voting_system_version": expected_voting_system_version,
    }
    payload.update(overrides)
    return payload


def software_modification_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload


# ---------------------------------------------------------------------------
# PostElectionAudit
# ---------------------------------------------------------------------------
def create_post_election_audit_payload(election_definition_id: str, **overrides) -> dict:
    payload = {
        "election_definition_id": election_definition_id,
        "audit_type": DEFAULTS["AUDIT_TYPE"],
    }
    payload.update(overrides)
    return payload


def post_election_audit_transition_payload(to_state: str, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update({k: v for k, v in extras.items() if v is not None})
    return payload
