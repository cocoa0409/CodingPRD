"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import ALL_CATEGORIES

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def eligibility_case_payload(**overrides) -> dict:
    defaults = {
        "applicant_legal_name": f"Applicant {_seq()}",
        "applicant_dob": "1985-01-01",
        "basis_type": "DIRECT_SERVICE",
    }
    defaults.update(overrides)
    return defaults


def service_record_payload(**overrides) -> dict:
    defaults = {
        "branch": "ARMY",
        "component": "ACTIVE_DUTY",
        "rank_grade": "E-5",
        "service_start_date": "2000-01-01",
        "service_end_date": "2006-01-01",
        "discharge_characterization": "HONORABLE",
    }
    defaults.update(overrides)
    return defaults


def active_service_record_payload(**overrides) -> dict:
    """A still-serving record (null end date) for ENLISTED_ACTIVE members."""
    defaults = {
        "branch": "ARMY",
        "component": "ACTIVE_DUTY",
        "rank_grade": "E-5",
        "service_start_date": "2015-01-01",
        "service_end_date": None,
        "discharge_characterization": "STILL_SERVING",
    }
    defaults.update(overrides)
    return defaults


def evidence_payload(content_hash=None, **overrides) -> dict:
    n = _seq()
    defaults = {
        "doc_type": "DD214",
        "issuing_authority": "NPRC",
        "issued_on": "2006-02-01",
        "content_hash": content_hash or f"hash-{n:04d}",
    }
    defaults.update(overrides)
    return defaults


def decide_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def product_offering_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "product_code": f"PROD-{n:04d}",
        "product_line": "BANKING",
        "product_name": f"Product {n}",
        "allowed_categories": list(ALL_CATEGORIES),
    }
    defaults.update(overrides)
    return defaults


def entitlement_payload(product_offering_id, **overrides) -> dict:
    defaults = {"product_offering_id": product_offering_id}
    defaults.update(overrides)
    return defaults


def household_payload(primary_member_id, **overrides) -> dict:
    defaults = {
        "household_name": f"Household {_seq()}",
        "primary_member_id": primary_member_id,
    }
    defaults.update(overrides)
    return defaults


def address_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "addr_type": "DOMESTIC_RESIDENCE",
        "line1": f"{n} Main St",
        "city": "Killeen",
        "region_code": "TX",
        "postal_code": "76541",
        "country_code": "US",
        "effective_from": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def deployment_order_payload(expected_member_version, **overrides) -> dict:
    n = _seq()
    defaults = {
        "orders_number": f"ORD-{n:04d}",
        "theater": "CENTCOM",
        "start_date": "2026-09-01",
        "end_date": "2026-12-01",
        "scra_eligible": True,
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


def protection_claim_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "claim_type": "RATE_REDUCTION",
        "obligation_label": f"OBL-{n:04d}",
        "base_rate_bps": 1100,
        "monthly_interest_cents": 110000,
    }
    defaults.update(overrides)
    return defaults
