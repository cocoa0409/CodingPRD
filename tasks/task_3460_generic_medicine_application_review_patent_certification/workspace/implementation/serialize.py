"""Entity serializers: exact scaffold field sets; computed fields per read."""
from domain import (
    exclusivity_blocked,
    goal_date,
    open_deficiency_count,
    open_supplement_count,
    patent_blocked_until,
)


def _common(ent):
    return {
        "id": ent["id"],
        "created_at": ent["created_at"],
        "updated_at": ent["updated_at"],
        "version": ent["version"],
    }


def applicant(ent):
    out = _common(ent)
    out.update({
        "legal_name": ent["legal_name"],
        "contact_email": ent["contact_email"],
        "headquarters_country": ent["headquarters_country"],
    })
    return out


def reference_product(ent):
    out = _common(ent)
    out.update({
        "brand_name": ent["brand_name"],
        "active_ingredient": ent["active_ingredient"],
        "strength": ent["strength"],
        "dosage_form": ent["dosage_form"],
        "rld_approval_date": ent["rld_approval_date"],
        "is_new_chemical_entity": ent["is_new_chemical_entity"],
        "indication_codes": list(ent["indication_codes"]),
        "patent_owner_user_id": ent["patent_owner_user_id"],
    })
    return out


def patent(ent):
    out = _common(ent)
    out.update({
        "reference_product_id": ent["reference_product_id"],
        "patent_number": ent["patent_number"],
        "patent_type": ent["patent_type"],
        "use_code": ent["use_code"],
        "expiry_date": ent["expiry_date"],
        "status": ent["status"],
    })
    return out


def protection(ent):
    out = _common(ent)
    out.update({
        "reference_product_id": ent["reference_product_id"],
        "indication_code": ent["indication_code"],
        "effective_from": ent["effective_from"],
        "protected_until": ent["protected_until"],
        "status": ent["status"],
    })
    return out


def application(ent):
    blocked = patent_blocked_until(ent)
    out = _common(ent)
    out.update({
        "applicant_id": ent["applicant_id"],
        "reference_product_id": ent["reference_product_id"],
        "review_priority": ent["review_priority"],
        "labeling_mode": ent["labeling_mode"],
        "carved_indication_codes": list(ent.get("carved_indication_codes") or []),
        "status": ent["status"],
        "received_date": ent["received_date"],
        "current_cycle_number": ent["current_cycle_number"],
        "tentative_approval_date": ent["tentative_approval_date"],
        "approval_date": ent["approval_date"],
        "first_marketing_date": ent["first_marketing_date"],
        "patent_blocked_until": blocked.isoformat() if blocked else None,
        "exclusivity_blocked": exclusivity_blocked(ent),
        "open_deficiency_count": open_deficiency_count(ent["id"]),
        "open_supplement_count": open_supplement_count(ent["id"]),
    })
    return out


def study(ent):
    out = _common(ent)
    for k in ("application_id", "study_type", "analyte", "auc_ratio_pct",
              "auc_ci_low_pct", "auc_ci_high_pct", "cmax_ratio_pct",
              "cmax_ci_low_pct", "cmax_ci_high_pct", "is_adequate", "status"):
        out[k] = ent[k]
    return out


def certification(ent):
    out = _common(ent)
    for k in ("application_id", "patent_id", "certification_type", "status",
              "filed_date", "amended_date"):
        out[k] = ent[k]
    return out


def notice(ent):
    out = _common(ent)
    for k in ("certification_id", "notice_date", "is_timely", "suit_deadline",
              "suit_filed_date", "stay_until", "court_outcome",
              "court_decision_date", "status"):
        out[k] = ent[k]
    return out


def review_cycle(ent):
    out = _common(ent)
    out.update({
        "application_id": ent["application_id"],
        "cycle_number": ent["cycle_number"],
        "status": ent["status"],
        "opened_date": ent["opened_date"],
        "base_review_months": ent["base_review_months"],
        "major_amendment_extensions_count": ent["major_amendment_extensions_count"],
        "goal_date": goal_date(ent).isoformat(),
        "deficiency_issued_date": ent["deficiency_issued_date"],
        "deficiency_response_due_date": ent["deficiency_response_due_date"],
        "deficiency_response_received_date": ent["deficiency_response_received_date"],
        "deficiency_summary": ent["deficiency_summary"],
        "closed_reason": ent["closed_reason"],
    })
    return out


def amendment(ent):
    out = _common(ent)
    for k in ("application_id", "classification", "contains_new_be_data",
              "notes", "submitted_date"):
        out[k] = ent[k]
    return out


def facility(ent):
    out = _common(ent)
    for k in ("applicant_id", "facility_name", "fei_number", "country_code",
              "is_foreign"):
        out[k] = ent[k]
    return out


def inspection(ent):
    out = _common(ent)
    for k in ("facility_id", "application_id", "inspection_type",
              "scheduled_start_date", "scheduled_end_date", "status",
              "outcome_date"):
        out[k] = ent[k]
    return out


def supplement(ent):
    out = _common(ent)
    for k in ("application_id", "change_type", "pathway", "description",
              "review_status", "effectivity", "submitted_date",
              "effective_date", "decision_date"):
        out[k] = ent[k]
    return out


def award(ent):
    out = _common(ent)
    for k in ("application_id", "reference_product_id", "status",
              "awarded_date", "approval_date", "marketing_deadline",
              "first_marketing_date", "exclusivity_end_date",
              "forfeiture_reason"):
        out[k] = ent[k]
    return out
