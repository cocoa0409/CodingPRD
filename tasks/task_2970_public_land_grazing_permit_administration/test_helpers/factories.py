"""Payload factories — request-body fields only, in the PRD's JSON types.

Whole-AUM and money fields are sent as JSON integers, fractional AUM and _pct
fields as JSON numbers, dates as `YYYY-MM-DD` strings and instants as ISO 8601
UTC instants with a trailing `Z`, exactly as PRD 2.6 requires.
"""
import itertools

_SEQ = itertools.count(1)


def _next() -> int:
    return next(_SEQ)


def admin_unit_code(n: int = None) -> str:
    """Two uppercase letters, a hyphen, then three digits (PRD 3.1)."""
    value = _next() if n is None else n
    return "NV-%03d" % (value % 1000)


def allotment_payload(**overrides) -> dict:
    payload = {
        "name": "Test Allotment %d" % _next(),
        "admin_unit_code": admin_unit_code(),
        "acres": 24000,
        "total_permitted_aums": 1200,
        "season_start": "01-01",
        "season_end": "12-31",
        "required_pasture_rotation_count": 1,
    }
    payload.update(overrides)
    return payload


def pasture_payload(**overrides) -> dict:
    payload = {
        "name": "Pasture %d" % _next(),
        "pasture_aum_capacity": 300,
        "sequence_order": 1,
        "rest_required": False,
    }
    payload.update(overrides)
    return payload


def permittee_payload(**overrides) -> dict:
    seq = _next()
    payload = {
        "name": "Test Ranch %d" % seq,
        "contact_email": "ranch%d@example.com" % seq,
    }
    payload.update(overrides)
    return payload


def base_property_payload(**overrides) -> dict:
    payload = {
        "base_property_type": "LAND",
        "legal_description": "T40N R60E Sec %d NW" % ((_next() % 36) + 1),
        "carrying_capacity_aums": 600,
        "controlled_since_date": "2005-01-01",
    }
    payload.update(overrides)
    return payload


def permit_payload(allotment_id, permittee_id, base_property_id, **overrides) -> dict:
    payload = {
        "allotment_id": allotment_id,
        "permittee_id": permittee_id,
        "base_property_id": base_property_id,
        "requested_aums": 300,
        "term_start_date": "2026-01-01",
        "term_end_date": "2030-12-31",
        "livestock_kind": "CATTLE",
    }
    payload.update(overrides)
    return payload


def renew_payload(base_property_id, **overrides) -> dict:
    payload = {
        "base_property_id": base_property_id,
        "requested_aums": 300,
        "term_start_date": "2030-12-31",
        "term_end_date": "2035-12-31",
    }
    payload.update(overrides)
    return payload


def transfer_payload(transferee_permittee_id, base_property_id, **overrides) -> dict:
    payload = {
        "transferee_permittee_id": transferee_permittee_id,
        "base_property_id": base_property_id,
        "requested_aums": 300,
        "term_start_date": "2026-01-01",
        "term_end_date": "2030-12-31",
    }
    payload.update(overrides)
    return payload


def aoi_payload(permit_id, **overrides) -> dict:
    payload = {
        "permit_id": permit_id,
        "grazing_year": 2026,
        "authorized_aums": 300,
        "season_start_date": "2026-01-01",
        "season_end_date": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def use_record_payload(pasture_id, **overrides) -> dict:
    payload = {
        "pasture_id": pasture_id,
        "planned_entry_date": "2026-04-01",
        "planned_exit_date": "2026-05-01",
        "planned_head_count": 100,
        "livestock_kind": "CATTLE",
    }
    payload.update(overrides)
    return payload


def report_actual_use_payload(**overrides) -> dict:
    payload = {
        "actual_entry_date": "2026-04-01",
        "actual_exit_date": "2026-05-01",
        "actual_head_count": 100,
    }
    payload.update(overrides)
    return payload


def nonuse_payload(nonuse_aums=100, nonuse_reason="RESOURCE_CONSERVATION", **overrides) -> dict:
    payload = {"nonuse_aums": nonuse_aums, "nonuse_reason": nonuse_reason}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def void_payload(void_reason="Recorded in error during administrative review.", **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


def assessment_payload(allotment_id, **overrides) -> dict:
    payload = {
        "allotment_id": allotment_id,
        "assessment_year": 2026,
        "monitoring_method": "INDICATOR_ASSESSMENT",
        "upland_score": 80,
        "riparian_score": 80,
        "water_quality_score": 80,
    }
    payload.update(overrides)
    return payload


def review_payload(review_outcome="CONCUR", **overrides) -> dict:
    payload = {"review_outcome": review_outcome, "review_notes": "Field verification complete."}
    payload.update(overrides)
    return payload


def decision_payload(allotment_id, expected_allotment_version, **overrides) -> dict:
    payload = {
        "decision_type": "ISSUANCE",
        "allotment_id": allotment_id,
        "expected_allotment_version": expected_allotment_version,
        "nepa_level": "CX",
    }
    payload.update(overrides)
    return payload


def environmental_review_payload(**overrides) -> dict:
    payload = {
        "nepa_findings_summary": "Categorical exclusion documented; no extraordinary circumstances.",
    }
    payload.update(overrides)
    return payload


def finalize_payload(**overrides) -> dict:
    payload = {
        "rationale": "Signed after review of the administrative record and the monitoring data.",
    }
    payload.update(overrides)
    return payload


def appeal_payload(appellant_permittee_id, stay_requested=False, **overrides) -> dict:
    payload = {
        "appellant_permittee_id": appellant_permittee_id,
        "stay_requested": stay_requested,
        "statement_of_reasons": "The decision misstates the forage available on the allotment.",
    }
    payload.update(overrides)
    return payload


def appeal_decision_payload(appeal_outcome, **overrides) -> dict:
    payload = {
        "appeal_outcome": appeal_outcome,
        "decision_rationale": "Considered on the administrative record submitted by both parties.",
    }
    payload.update(overrides)
    return payload


def closure_order_payload(allotment_id, **overrides) -> dict:
    payload = {
        "allotment_id": allotment_id,
        "order_type": "DROUGHT_REDUCTION",
        "reduction_pct": 0.30,
        "effective_start_date": "2026-08-05",
        "effective_end_date": "2026-10-31",
        "justification": "Drought indicators show forage production well below the long-term average.",
    }
    payload.update(overrides)
    return payload


def lift_payload(**overrides) -> dict:
    payload = {"justification": "Late-season precipitation restored forage production on the unit."}
    payload.update(overrides)
    return payload


def trespass_payload(allotment_id, permittee_id=None, **overrides) -> dict:
    payload = {
        "allotment_id": allotment_id,
        "permittee_id": permittee_id,
        "detected_at": "2026-07-15T14:30:00Z",
        "head_count": 47,
        "livestock_kind": "CATTLE",
        "unauthorized_days": 11,
        "willfulness": "WILLFUL",
    }
    payload.update(overrides)
    return payload


def project_payload(allotment_id, **overrides) -> dict:
    payload = {
        "allotment_id": allotment_id,
        "project_type": "FENCE",
        "total_cost_cents": 1000000,
        "agency_share_pct": 0.5,
        "permittee_share_pct": 0.5,
        "maintenance_responsibility": "SHARED",
    }
    payload.update(overrides)
    return payload


def clock_payload(current_utc) -> dict:
    return {"current_utc": current_utc}
