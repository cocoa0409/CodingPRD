"""Request-payload builders.

All numeric values are emitted as JSON numbers (never strings) and all optional
keys are omitted rather than sent as null unless a test explicitly passes them.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ATTRIBUTION_CREATION_SITE,
    OVERLAY_DEMOGRAPHIC_OVERWRITE,
    PROPAGATION_MODE_BATCH,
    RECOMMENDATION_MERGE,
    RS_BASE_AUTO_LINK_THRESHOLD,
    RS_BASE_CONFLICT_PENALTY_POINTS,
    RS_BASE_NAME,
    RS_BASE_REVIEW_THRESHOLD,
    RS_BASE_VERSION_LABEL,
    RS_BASE_WEIGHTS,
    SCORE_VARIANT_STRICT,
    TRIGGER_MANUAL,
)


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``None``-by-omission."""
    return {key: value for key, value in payload.items() if value is not _OMIT}


class _Omit:
    def __repr__(self):  # pragma: no cover - debugging aid only
        return "<omit>"


_OMIT = _Omit()


# ─── Registration sites (§3.1) ────────────────────────
def site_payload(
    site_code: str,
    name: str = "Central Registration",
    region_code: str = "MW-01",
    registrar_headcount: int = 4,
) -> Dict[str, Any]:
    return {
        "site_code": site_code,
        "name": name,
        "region_code": region_code,
        "registrar_headcount": int(registrar_headcount),
    }


# ─── Match rule sets (§3.1) ───────────────────────────
def rule_set_payload(
    name: str = RS_BASE_NAME,
    version_label: str = RS_BASE_VERSION_LABEL,
    attribute_weights: Optional[Dict[str, float]] = None,
    auto_link_threshold: float = RS_BASE_AUTO_LINK_THRESHOLD,
    review_threshold: float = RS_BASE_REVIEW_THRESHOLD,
    conflict_penalty_points: float = RS_BASE_CONFLICT_PENALTY_POINTS,
) -> Dict[str, Any]:
    weights = dict(RS_BASE_WEIGHTS if attribute_weights is None else attribute_weights)
    return {
        "name": name,
        "version_label": version_label,
        "attribute_weights": {key: float(value) for key, value in weights.items()},
        "auto_link_threshold": float(auto_link_threshold),
        "review_threshold": float(review_threshold),
        "conflict_penalty_points": float(conflict_penalty_points),
    }


# ─── Registration search attempts (§3.2) ──────────────
def search_attempt_payload(
    searched_last_name: str,
    searched_first_name: Any = _OMIT,
    searched_dob: Any = _OMIT,
    searched_sex: Any = _OMIT,
    searched_ssn_last4: Any = _OMIT,
    searched_postal_code: Any = _OMIT,
    searched_phone: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "searched_last_name": searched_last_name,
            "searched_first_name": searched_first_name,
            "searched_dob": searched_dob,
            "searched_sex": searched_sex,
            "searched_ssn_last4": searched_ssn_last4,
            "searched_postal_code": searched_postal_code,
            "searched_phone": searched_phone,
        }
    )


# ─── Patient records (§3.2) ───────────────────────────
def record_payload(
    site_id: str,
    mrn: str,
    last_name: str,
    first_name: str,
    dob: str,
    sex: str,
    ssn_last4: Any = _OMIT,
    address_line: Any = _OMIT,
    postal_code: Any = _OMIT,
    phone: Any = _OMIT,
    biometric_template_hash: Any = _OMIT,
    insurance_member_id: Any = _OMIT,
    clinical_element_count: Any = _OMIT,
    origin_search_attempt_id: Any = _OMIT,
) -> Dict[str, Any]:
    payload = _compact(
        {
            "site_id": site_id,
            "mrn": mrn,
            "last_name": last_name,
            "first_name": first_name,
            "dob": dob,
            "sex": sex,
            "ssn_last4": ssn_last4,
            "address_line": address_line,
            "postal_code": postal_code,
            "phone": phone,
            "biometric_template_hash": biometric_template_hash,
            "insurance_member_id": insurance_member_id,
            "clinical_element_count": clinical_element_count,
            "origin_search_attempt_id": origin_search_attempt_id,
        }
    )
    if "clinical_element_count" in payload:
        payload["clinical_element_count"] = int(payload["clinical_element_count"])
    return payload


# ─── Candidate pairs (§3.3) ───────────────────────────
def pair_payload(
    record_a_id: str,
    record_b_id: str,
    rule_set_id: str,
    score_variant: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "record_a_id": record_a_id,
            "record_b_id": record_b_id,
            "rule_set_id": rule_set_id,
            "score_variant": score_variant,
        }
    )


def rescore_payload(
    rule_set_id: str,
    score_variant: str = SCORE_VARIANT_STRICT,
    expected_pair_version: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "rule_set_id": rule_set_id,
            "score_variant": score_variant,
            "expected_pair_version": expected_pair_version,
        }
    )


def external_match_payload(
    record_id: str,
    exchange_partner_code: str,
    consent_on_file: bool,
    external_demographics: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "record_id": record_id,
        "exchange_partner_code": exchange_partner_code,
        "consent_on_file": bool(consent_on_file),
        "external_demographics": dict(external_demographics),
    }


# ─── Duplicate queue (§3.4) ───────────────────────────
def triage_payload(triage_note: str = "Queueing for manual adjudication.") -> Dict[str, Any]:
    return {"triage_note": triage_note}


def evidence_payload(
    evidence_type: str,
    outcome: str,
    weight_points: float,
    note: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "evidence_type": evidence_type,
            "outcome": outcome,
            "weight_points": float(weight_points),
            "note": note,
        }
    )


def recommend_payload(recommendation: str = RECOMMENDATION_MERGE) -> Dict[str, Any]:
    return {"recommendation": recommendation}


def return_to_review_payload(triage_note: Any = _OMIT) -> Dict[str, Any]:
    return _compact({"triage_note": triage_note})


def resolve_distinct_payload(resolution_note: Any = _OMIT) -> Dict[str, Any]:
    return _compact({"resolution_note": resolution_note})


# ─── Merge and unmerge (§3.5, §3.7) ───────────────────
def merge_payload(
    pair_id: str,
    survivor_record_id: str,
    subsumed_record_id: str,
    rationale: str = "Same patient confirmed by review evidence.",
) -> Dict[str, Any]:
    return {
        "pair_id": pair_id,
        "survivor_record_id": survivor_record_id,
        "subsumed_record_id": subsumed_record_id,
        "rationale": rationale,
    }


def unmerge_payload(unmerge_reason: str = "Wrong survivor chosen.") -> Dict[str, Any]:
    return {"unmerge_reason": unmerge_reason}


# ─── Downstream systems and propagation (§3.1, §3.6) ──
def system_payload(
    system_code: str,
    name: str = "Downstream Consumer",
    propagation_mode: str = PROPAGATION_MODE_BATCH,
    ack_required: bool = True,
    max_concurrent_dispatch: int = 1,
) -> Dict[str, Any]:
    return {
        "system_code": system_code,
        "name": name,
        "propagation_mode": propagation_mode,
        "ack_required": bool(ack_required),
        "max_concurrent_dispatch": int(max_concurrent_dispatch),
    }


def send_payload(
    dispatch_window_start_at: str, dispatch_window_end_at: str
) -> Dict[str, Any]:
    return {
        "dispatch_window_start_at": dispatch_window_start_at,
        "dispatch_window_end_at": dispatch_window_end_at,
    }


def fail_payload(last_error_code: str = "ACK_TIMEOUT") -> Dict[str, Any]:
    return {"last_error_code": last_error_code}


# ─── Overlay corrections and remediation (§3.8) ───────
def overlay_payload(
    record_id: str,
    corrected_field_snapshot: Dict[str, Any],
    affected_clinical_element_count: int,
    encounter_from_date: str,
    encounter_to_date: str,
    expected_record_version: int,
    overlay_type: str = OVERLAY_DEMOGRAPHIC_OVERWRITE,
) -> Dict[str, Any]:
    return {
        "record_id": record_id,
        "overlay_type": overlay_type,
        "corrected_field_snapshot": dict(corrected_field_snapshot),
        "affected_clinical_element_count": int(affected_clinical_element_count),
        "encounter_from_date": encounter_from_date,
        "encounter_to_date": encounter_to_date,
        "expected_record_version": int(expected_record_version),
    }


def complete_overlay_payload(
    closure_note: str = "Corrected demographics verified.",
) -> Dict[str, Any]:
    return {"closure_note": closure_note}


def quarantine_payload(element_count_quarantined: int) -> Dict[str, Any]:
    return {"element_count_quarantined": int(element_count_quarantined)}


def reassign_payload(
    target_record_id: str, element_count_reassigned: int
) -> Dict[str, Any]:
    return {
        "target_record_id": target_record_id,
        "element_count_reassigned": int(element_count_reassigned),
    }


def close_remediation_payload(
    closure_note: str = "Contamination resolved.",
) -> Dict[str, Any]:
    return {"closure_note": closure_note}


# ─── Fraud investigations (§3.9) ──────────────────────
def investigation_payload(
    record_id: str,
    trigger_kind: str = TRIGGER_MANUAL,
    pair_id: Any = _OMIT,
    note: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "record_id": record_id,
            "pair_id": pair_id,
            "trigger_kind": trigger_kind,
            "note": note,
        }
    )


def substantiate_payload(
    finding_note: str = "Identity theft confirmed by documentation review.",
) -> Dict[str, Any]:
    return {"finding_note": finding_note}


def unsubstantiate_payload(
    finding_note: str = "No evidence of identity fraud.",
) -> Dict[str, Any]:
    return {"finding_note": finding_note}


def refer_payload(referral_reference: str = "USAO-AR-2026-0311") -> Dict[str, Any]:
    return {"referral_reference": referral_reference}


# ─── Duplicate metric runs (§3.9) ─────────────────────
def metric_run_payload(
    window_start_date: str,
    window_end_date: str,
    attribution_variant: str = ATTRIBUTION_CREATION_SITE,
) -> Dict[str, Any]:
    return {
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "attribution_variant": attribution_variant,
    }


# ─── Demographic templates for scoring scenarios ──────
def demographics(
    last_name: str = "Nakamura",
    first_name: str = "Haruto",
    dob: str = "1984-02-19",
    sex: str = "M",
    ssn_last4: Optional[str] = "4417",
    postal_code: Optional[str] = "60614",
    phone: Optional[str] = "3125550118",
) -> Dict[str, Any]:
    """A full seven-attribute demographic template for match scoring."""
    return {
        "last_name": last_name,
        "first_name": first_name,
        "dob": dob,
        "sex": sex,
        "ssn_last4": ssn_last4,
        "postal_code": postal_code,
        "phone": phone,
    }


def record_from_demographics(
    site_id: str, mrn: str, demo: Dict[str, Any], **extra: Any
) -> Dict[str, Any]:
    """Build a record payload from a demographic template plus extras."""
    payload: Dict[str, Any] = {"site_id": site_id, "mrn": mrn}
    for key, value in demo.items():
        if value is not None:
            payload[key] = value
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    if "clinical_element_count" in payload:
        payload["clinical_element_count"] = int(payload["clinical_element_count"])
    return payload


def omit() -> Any:
    """Sentinel meaning 'do not send this key at all'."""
    return _OMIT


OMIT = _OMIT

__all__: List[str] = [name for name in dir() if not name.startswith("_")]
