"""Entity -> JSON projections."""
import calc
from store import db
from util import fmt_ms, fmt_sec, num


def _base(row):
    return {"id": row["id"], "created_at": fmt_ms(row["created_at"]),
            "updated_at": fmt_ms(row["updated_at"]), "version": row["version"]}


def market_json(row):
    # PRD 2.4: a market regime is immutable, so it carries only id and
    # created_at -- neither updated_at nor version is ever emitted.
    return {
        "id": row["id"],
        "created_at": fmt_ms(row["created_at"]),
        "market_code": row["market_code"],
        "required_languages": list(row["required_languages"]),
        "fiber_tolerance_pp": num(row["fiber_tolerance_pp"]),
        "absolute_claim_tolerance_pp": num(row["absolute_claim_tolerance_pp"]),
        "min_durability_cycles": row["min_durability_cycles"],
        "marking_duty_rate": num(row["marking_duty_rate"]),
        "requires_identity_disclosure": row["requires_identity_disclosure"],
        "requires_origin_statement": row["requires_origin_statement"],
    }


def brand_json(row):
    out = _base(row)
    responsible = calc.responsible_of(row)
    out.update({
        "legal_name": row["legal_name"],
        "party_type": row["party_type"],
        "rn_number": row["rn_number"],
        "licensor_brand_id": row["licensor_brand_id"],
        "responsibility_mode": row["responsibility_mode"],
        "responsible_brand_id": responsible,
        "outstanding_penalty_usd": num(calc.brand_penalty_ledger(row["id"])),
        "critical_audit_finding_count": calc.critical_audit_finding_count(row["id"]),
        "posture": calc.brand_posture(row["id"]),
    })
    return out


def fiber_line_json(line):
    return {"fiber_generic_name": line["fiber_generic_name"],
            "declared_pct": num(line["declared_pct"]),
            "ornamentation_exempt": line["ornamentation_exempt"]}


def style_json(row):
    out = _base(row)
    out.update({
        "brand_id": row["brand_id"],
        "style_code": row["style_code"],
        "product_class": row["product_class"],
        "target_market_codes": list(row["target_market_codes"]),
        "net_weight_grams": num(row["net_weight_grams"]),
        "declared_fibers": [fiber_line_json(l) for l in row["declared_fibers"]],
        "substantiation_state": row["substantiation_state"],
        "origin_state": row["origin_state"],
        "label_readiness": calc.label_readiness(row),
        "effective_fiber_content_text": calc.effective_fiber_content_text(row["declared_fibers"]),
    })
    return out


def material_json(row):
    out = _base(row)
    out.update({
        "style_id": row["style_id"],
        "parent_input_id": row["parent_input_id"],
        "stage": row["stage"],
        "country_code": row["country_code"],
        "value_added_usd": num(row["value_added_usd"]),
        "weight_grams": num(row["weight_grams"]),
        "is_ornamentation": row["is_ornamentation"],
        "depth": row["depth"],
    })
    return out


def measured_line_json(line):
    return {"fiber_generic_name": line["fiber_generic_name"],
            "measured_pct": num(line["measured_pct"])}


def lab_test_json(row):
    out = _base(row)
    measured = row["measured_fibers"]
    out.update({
        "style_id": row["style_id"],
        "test_type": row["test_type"],
        "lab_code": row["lab_code"],
        "method": row["method"],
        "specimen_received_at": fmt_sec(row["specimen_received_at"]),
        "results_due_at": fmt_sec(row["results_due_at"]),
        "wash_temp_c": row["wash_temp_c"],
        "state": row["state"],
        "attempt_no": row["attempt_no"],
        "cycles_run": row["cycles_run"],
        "measured_fibers": ([measured_line_json(l) for l in measured]
                            if measured is not None else None),
        "dimensional_change_pct": num(row["dimensional_change_pct"]),
        "colorfastness_grade": num(row["colorfastness_grade"]),
        "legibility_cycles": row["legibility_cycles"],
        "result_delta_pp_max": num(row["result_delta_pp_max"]),
        "valid_until": fmt_sec(row["valid_until"]),
    })
    return out


def origin_json(row):
    out = _base(row)
    out.update({
        "style_id": row["style_id"],
        "state": row["state"],
        "method_pinned": row["method_pinned"],
        "st_country": row["st_country"],
        "yf_country": row["yf_country"],
        "divergent": row["divergent"],
        "determined_country": row["determined_country"],
        "graph_node_count": row["graph_node_count"],
        "issued_at": fmt_sec(row["issued_at"]),
    })
    return out


def label_json(row):
    out = _base(row)
    out.update({
        "style_id": row["style_id"],
        "artifact_type": row["artifact_type"],
        "parent_label_spec_id": row["parent_label_spec_id"],
        "origin_determination_id": row["origin_determination_id"],
        "care_test_id": row["care_test_id"],
        "market_codes": list(row["market_codes"]),
        "languages": list(row["languages"]),
        "placement_code": row["placement_code"],
        "durability_cycles_rating": row["durability_cycles_rating"],
        "wash_temp_c": row["wash_temp_c"],
        "bleach_code": row["bleach_code"],
        "dry_code": row["dry_code"],
        "iron_code": row["iron_code"],
        "dryclean_code": row["dryclean_code"],
        "identity_display_mode": row["identity_display_mode"],
        "fiber_content_text": row["fiber_content_text"],
        "origin_text": row["origin_text"],
        "marketing_claims": list(row["marketing_claims"]),
        "state": row["state"],
        "authored_by_user_id": row["authored_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "revision_note": row["revision_note"],
        "withdrawn_reason": row["withdrawn_reason"],
        "effective_from": fmt_sec(row["effective_from"]),
        "effective_to": fmt_sec(row["effective_to"]),
        "content_hash": row["content_hash"],
        "consistency_state": row["consistency_state"],
    })
    return out


def shipment_json(row):
    out = _base(row)
    out.update({
        "importer_brand_id": row["importer_brand_id"],
        "style_id": row["style_id"],
        "corrective_label_spec_id": row["corrective_label_spec_id"],
        "entry_number": row["entry_number"],
        "quantity_units": row["quantity_units"],
        "declared_value_usd": num(row["declared_value_usd"]),
        "entry_market_code": row["entry_market_code"],
        "marking_state": row["marking_state"],
        "deficiency_code": row["deficiency_code"],
        "review_decided_at": fmt_sec(row["review_decided_at"]),
        "redelivery_deadline_at": fmt_sec(row["redelivery_deadline_at"]),
        "posture_at_review": row["posture_at_review"],
        "assessment_basis": row["assessment_basis"],
        "penalty_ad_valorem_usd": num(row["penalty_ad_valorem_usd"]),
        "penalty_statutory_usd": num(row["penalty_statutory_usd"]),
        "penalty_assessed_usd": num(row["penalty_assessed_usd"]),
        "penalty_mitigated_usd": num(row["penalty_mitigated_usd"]),
        "corrected_units": row["corrected_units"],
    })
    return out


def audit_json(row):
    out = _base(row)
    open_count, critical, units, _total = calc.audit_counts(row["id"])
    out.update({
        "brand_id": row["brand_id"],
        "scope": row["scope"],
        "audit_window_from": fmt_sec(row["audit_window_from"]),
        "audit_window_to": fmt_sec(row["audit_window_to"]),
        "state": row["state"],
        "open_finding_count": open_count,
        "critical_finding_count": critical,
        "units_in_scope": units,
        "closed_at": fmt_sec(row["closed_at"]),
    })
    return out


def finding_json(row):
    out = _base(row)
    out.update({
        "audit_id": row["audit_id"],
        "style_id": row["style_id"],
        "corrective_label_spec_id": row["corrective_label_spec_id"],
        "finding_code": row["finding_code"],
        "severity": row["severity"],
        "units_affected": row["units_affected"],
        "units_relabeled": row["units_relabeled"],
        "units_destroyed": row["units_destroyed"],
        "units_released": row["units_released"],
        "units_unresolved": calc.units_unresolved(row),
        "state": row["state"],
        "disposition_recorded_at": fmt_sec(row["disposition_recorded_at"]),
        "verified_at": fmt_sec(row["verified_at"]),
        "reopen_reason": row["reopen_reason"],
    })
    return out


def compliance_summary_json(style):
    care = calc.newest_passed_care_test(style["id"])
    determination = calc.current_issued_determination(style["id"])
    required = calc.durability_floor(style["target_market_codes"], style["product_class"])
    substantiated = care["legibility_cycles"] if care else 0
    published = len([l for l in db.label_specs.values()
                     if l["style_id"] == style["id"]
                     and l["artifact_type"] == "PERMANENT_LABEL"
                     and l["state"] == "PUBLISHED"])
    reasons = []
    if style["substantiation_state"] != "FIBER_SUBSTANTIATED":
        reasons.append("ERR_FIBER_NOT_SUBSTANTIATED")
    if style["origin_state"] != "ORIGIN_ISSUED":
        reasons.append("ERR_ORIGIN_NOT_ISSUED")
    if care is None:
        reasons.append("ERR_CARE_NOT_SUBSTANTIATED")
    if substantiated < required:
        reasons.append("ERR_DURABILITY_INSUFFICIENT")
    return {
        "style_id": style["id"],
        "substantiation_state": style["substantiation_state"],
        "origin_state": style["origin_state"],
        "label_readiness": calc.label_readiness(style),
        "effective_fiber_content_text": calc.effective_fiber_content_text(style["declared_fibers"]),
        "determined_country": determination["determined_country"] if determination else None,
        "required_durability_cycles": required,
        "substantiated_durability_cycles": substantiated,
        "published_permanent_label_count": published,
        "blocking_reasons": reasons,
    }
