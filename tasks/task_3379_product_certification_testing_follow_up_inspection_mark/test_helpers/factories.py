"""Payload factories for the Product Certification Followup API.

One factory per writable endpoint's request body. Only client-supplied fields
appear here - system-managed fields (status, version, computed fields, the
system-stamped actor and timestamp fields) are never part of a request payload
per the PRD's endpoint narratives. Every factory accepts ``**overrides`` so a
test controls exactly the fields it cares about while the defaults keep the
payload valid.
"""

from typing import Any, Dict, List, Optional

__all__ = [
    "DEFAULTS",
    "CANONICAL_PROTOCOLS",
    "CANONICAL_SLOTS",
    "CANONICAL_COMPONENTS",
    "clock_payload",
    "standard_payload",
    "protocol_spec",
    "jurisdiction_payload",
    "manufacturer_payload",
    "suspend_manufacturer_payload",
    "factory_payload",
    "project_payload",
    "sample_payload",
    "triage_payload",
    "result_payload",
    "component_entry",
    "construction_record_payload",
    "decide_project_payload",
    "substitution_request_payload",
    "substitution_decide_payload",
    "substitution_implement_payload",
    "inspection_payload",
    "finding_entry",
    "complete_inspection_payload",
    "void_inspection_payload",
    "mark_license_payload",
    "label_batch_payload",
    "void_label_batch_payload",
    "field_evaluation_payload",
    "evaluate_payload",
    "acceptance_decision_payload",
    "withdrawal_notice_payload",
    "suspend_certification_payload",
]

DEFAULTS = {
    # Logical clock default (PRD 2.5 startup instant).
    "CLOCK_ISO": "2026-09-01T00:00:00Z",
    # Canonical standard edition: window already open at the default clock.
    "CATEGORY_CODE": "IT-AV",
    "STANDARD_CODE": "UL-62368",
    "EDITION_LABEL": "Ed. 4",
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    # Manufacturer.
    "LEGAL_NAME": "Acme Devices LLC",
    "HOME_JURISDICTION_CODE": "US-OSHA",
    "REVENUE_TIER": "SMALL",
    # Factory.
    "SITE_CODE": "SZ-1",
    "COUNTRY_CODE": "CN",
    "FACTORY_JURISDICTION_CODE": "CN-SZ",
    # Project.
    "PRODUCT_MODEL": "AC-100",
    # Sample.
    "SERIAL_NO": "S-1",
    "CONDITION": "INTACT",
    # Inspection.
    "SCHEDULED_FOR": "2026-09-01T00:00:00Z",
    # Mark license.
    "LABEL_TYPE": "STANDARD",
    "DECLARED_ANNUAL_VOLUME": 10000,
    # Label batch.
    "BATCH_QUANTITY": 100,
    # Field evaluation.
    "EQUIPMENT_DESCRIPTION": "Installed conveyor controller, never certified",
    "SITE_ADDRESS": "12 Industrial Way, Dayton OH",
    # Withdrawal notice.
    "REASON_CODE": "NONCONFORMITY",
    "PUBLIC_TEXT": "Listing withdrawn due to factory nonconformity.",
    # Suspension / void reasons.
    "SUSPEND_REASON": "Routine surveillance hold",
    "VOID_REASON": "Record created in error",
}

# The canonical standard's rulebook: two construction slots and three
# protocols (one mandatory safety-critical, one mandatory, one optional).
CANONICAL_SLOTS: List[str] = ["enclosure", "power_supply"]

CANONICAL_PROTOCOLS: List[Dict[str, Any]] = [
    {
        "protocol_code": "P-SAFE",
        "name": "Electric shock",
        "mandatory": True,
        "safety_critical": True,
        "pass_threshold": 50,
        "base_fee_cents": 5000,
    },
    {
        "protocol_code": "P-TEMP",
        "name": "Temperature rise",
        "mandatory": True,
        "safety_critical": False,
        "pass_threshold": 100,
        "base_fee_cents": 10001,
    },
    {
        "protocol_code": "P-MARK",
        "name": "Marking durability",
        "mandatory": False,
        "safety_critical": False,
        "pass_threshold": 200,
        "base_fee_cents": 10001,
    },
]

# A components array that covers every canonical slot exactly once.
CANONICAL_COMPONENTS: List[Dict[str, Any]] = [
    {
        "slot": "enclosure",
        "component_name": "BayBlend FR3010",
        "material": "PC/ABS",
        "part_number": "BB-FR3010",
        "rating": "V-0",
    },
    {
        "slot": "power_supply",
        "component_name": "MeanWell RS-25",
        "material": "n/a",
        "part_number": "MW-RS-25",
        "rating": "100-240VAC",
    },
]


# ── Logical clock ──────────────────────────────────────────────────────────

def clock_payload(to_iso8601: str = DEFAULTS["CLOCK_ISO"]) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ── Configuration ──────────────────────────────────────────────────────────

def protocol_spec(protocol_code: str, **overrides: Any) -> Dict[str, Any]:
    spec: Dict[str, Any] = {
        "protocol_code": protocol_code,
        "name": f"Protocol {protocol_code}",
        "mandatory": True,
        "safety_critical": False,
        "pass_threshold": 100,
        "base_fee_cents": 1000,
    }
    spec.update(overrides)
    return spec


def standard_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category_code": DEFAULTS["CATEGORY_CODE"],
        "standard_code": DEFAULTS["STANDARD_CODE"],
        "edition_label": DEFAULTS["EDITION_LABEL"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": None,
        "construction_requirements": list(CANONICAL_SLOTS),
        "test_protocols": [dict(p) for p in CANONICAL_PROTOCOLS],
    }
    payload.update(overrides)
    return payload


def jurisdiction_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "jurisdiction_code": "US-OSHA",
        "name": "OSHA NRTL",
        "accepts_field_labels": True,
        "accepts_reciprocity": False,
        "reciprocity_sources": [],
        "reciprocity_group": "NATIONAL",
    }
    payload.update(overrides)
    return payload


# ── Manufacturers and factories ────────────────────────────────────────────

def manufacturer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "home_jurisdiction_code": DEFAULTS["HOME_JURISDICTION_CODE"],
        "annual_revenue_tier": DEFAULTS["REVENUE_TIER"],
    }
    payload.update(overrides)
    return payload


def suspend_manufacturer_payload(reason: str = DEFAULTS["SUSPEND_REASON"]) -> Dict[str, Any]:
    return {"reason": reason}


def factory_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_code": DEFAULTS["SITE_CODE"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "jurisdiction_code": DEFAULTS["FACTORY_JURISDICTION_CODE"],
    }
    payload.update(overrides)
    return payload


# ── Projects, samples, construction records ────────────────────────────────

def project_payload(factory_id: str, standard_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "factory_id": factory_id,
        "category_code": DEFAULTS["CATEGORY_CODE"],
        "standard_id": standard_id,
        "product_model": DEFAULTS["PRODUCT_MODEL"],
    }
    payload.update(overrides)
    return payload


def sample_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "serial_no": DEFAULTS["SERIAL_NO"],
        "condition": DEFAULTS["CONDITION"],
    }
    payload.update(overrides)
    return payload


def triage_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def result_payload(protocol_code: str, measured_value, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "protocol_code": protocol_code,
        "measured_value": measured_value,
    }
    payload.update(overrides)
    return payload


def component_entry(slot: str, **overrides: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "slot": slot,
        "component_name": f"Component for {slot}",
        "material": "n/a",
        "part_number": f"PN-{slot}",
        "rating": "n/a",
    }
    entry.update(overrides)
    return entry


def construction_record_payload(
    expected_project_version: int,
    components: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "components": [dict(c) for c in (components if components is not None else CANONICAL_COMPONENTS)],
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def decide_project_payload(outcome: str = "APPROVED", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ── Substitution requests ──────────────────────────────────────────────────

def substitution_request_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "slot": "power_supply",
        "proposed_component": {
            "component_name": "MeanWell RS-25-PRO",
            "material": "n/a",
            "part_number": "MW-RS-25-PRO",
            "rating": "100-240VAC",
        },
        "rationale": "Original PSU discontinued",
    }
    payload.update(overrides)
    return payload


def substitution_decide_payload(outcome: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def substitution_implement_payload(expected_certification_version: int) -> Dict[str, Any]:
    return {"expected_certification_version": expected_certification_version}


# ── Follow-up inspections ──────────────────────────────────────────────────

def inspection_payload(scheduled_for: str = DEFAULTS["SCHEDULED_FOR"]) -> Dict[str, Any]:
    return {"scheduled_for": scheduled_for}


def finding_entry(
    finding_ref: str,
    severity: str = "CRITICAL",
    description: str = "Finding observed on the production line",
    certification_id: Optional[str] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "finding_ref": finding_ref,
        "severity": severity,
        "description": description,
    }
    if certification_id is not None:
        entry["certification_id"] = certification_id
    return entry


def complete_inspection_payload(
    findings: Optional[List[Dict[str, Any]]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"findings": list(findings) if findings is not None else []}
    payload.update(overrides)
    return payload


def void_inspection_payload(reason: str = DEFAULTS["VOID_REASON"]) -> Dict[str, Any]:
    return {"reason": reason}


# ── Mark licenses and label batches ────────────────────────────────────────

def mark_license_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "label_type": DEFAULTS["LABEL_TYPE"],
        "declared_annual_volume": DEFAULTS["DECLARED_ANNUAL_VOLUME"],
    }
    payload.update(overrides)
    return payload


def label_batch_payload(quantity: int = DEFAULTS["BATCH_QUANTITY"]) -> Dict[str, Any]:
    return {"quantity": quantity}


def void_label_batch_payload(reason: str = DEFAULTS["VOID_REASON"]) -> Dict[str, Any]:
    return {"reason": reason}


# ── Field evaluations ──────────────────────────────────────────────────────

def field_evaluation_payload(
    standard_id: str,
    evaluating_jurisdiction_id: str,
    site_jurisdiction_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "standard_id": standard_id,
        "evaluating_jurisdiction_id": evaluating_jurisdiction_id,
        "site_jurisdiction_id": site_jurisdiction_id,
        "equipment_description": DEFAULTS["EQUIPMENT_DESCRIPTION"],
        "site_address": DEFAULTS["SITE_ADDRESS"],
    }
    payload.update(overrides)
    return payload


def evaluate_payload(outcome: str = "PASS", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def acceptance_decision_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ── Withdrawal notices and compliance actions ──────────────────────────────

def withdrawal_notice_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reason_code": DEFAULTS["REASON_CODE"],
        "public_text": DEFAULTS["PUBLIC_TEXT"],
    }
    payload.update(overrides)
    return payload


def suspend_certification_payload(reason: str = DEFAULTS["SUSPEND_REASON"]) -> Dict[str, Any]:
    return {"reason": reason}
