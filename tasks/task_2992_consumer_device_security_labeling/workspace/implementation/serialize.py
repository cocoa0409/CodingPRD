"""Entity -> JSON serializers.  Field names come straight from the scaffold."""

from decimal import Decimal

from envelope import iso


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def _record(row):
    """SecurityCriterion / RecognitionSurvey carry only id and created_at."""
    return {"id": row["id"], "created_at": iso(row["created_at"])}


def program_tier(row):
    out = _common(row)
    out.update(
        {
            "tier_code": row["tier_code"],
            "required_route": row["required_route"],
            "label_validity_days": row["label_validity_days"],
            "min_overall_score": num(row["min_overall_score"]),
            "unverified_weight_factor": num(row["unverified_weight_factor"]),
            "issuance_base_fee_cents": row["issuance_base_fee_cents"],
            "max_deficiency_rounds": row["max_deficiency_rounds"],
        }
    )
    return out


def device_category(row):
    out = _common(row)
    out.update(
        {
            "category_code": row["category_code"],
            "display_name": row["display_name"],
            "eligibility_status": row["eligibility_status"],
            "exclusion_reason": row["exclusion_reason"],
            "program_tier_id": row["program_tier_id"],
            "min_support_period_days": row["min_support_period_days"],
        }
    )
    return out


def security_criterion(row):
    out = _record(row)
    out.update(
        {
            "criterion_code": row["criterion_code"],
            "practice_area": row["practice_area"],
            "weight": row["weight"],
            "requires_lab_verification": row["requires_lab_verification"],
            "criterion_text": row["criterion_text"],
        }
    )
    return out


def manufacturer(row):
    out = _common(row)
    out.update(
        {
            "legal_name": row["legal_name"],
            "contact_email": row["contact_email"],
            "enterprise_class": row["enterprise_class"],
            "annual_us_revenue_cents": row["annual_us_revenue_cents"],
            "standing": row["standing"],
            "outstanding_penalty_cents": row["outstanding_penalty_cents"],
            "paid_penalty_cents": row["paid_penalty_cents"],
            "vacated_penalty_cents": row["vacated_penalty_cents"],
            "total_assessed_penalty_cents": row["total_assessed_penalty_cents"],
            "upheld_case_count": row["upheld_case_count"],
        }
    )
    return out


def product(row):
    out = _common(row)
    out.update(
        {
            "manufacturer_id": row["manufacturer_id"],
            "device_category_id": row["device_category_id"],
            "model_name": row["model_name"],
            "sku": row["sku"],
            "firmware_version": row["firmware_version"],
            "declared_support_period_end": iso(row["declared_support_period_end"]),
            "update_policy_disclosed": row["update_policy_disclosed"],
            "retail_units_shipped": row["retail_units_shipped"],
            "spec_revision": row["spec_revision"],
            "conformance_currency": row["conformance_currency"],
            "eligibility_status": row["eligibility_status"],
            "last_change_summary": row["last_change_summary"],
        }
    )
    return out


def _area_scores(value):
    if value is None:
        return None
    return {area: num(score) for area, score in value.items()}


def assessment(row):
    out = _common(row)
    out.update(
        {
            "product_id": row["product_id"],
            "route": row["route"],
            "assessed_spec_revision": row["assessed_spec_revision"],
            "status": row["status"],
            "deficiency_round": row["deficiency_round"],
            "provisional_area_scores": _area_scores(row["provisional_area_scores"]),
            "provisional_overall_score": num(row["provisional_overall_score"]),
            "verified_area_scores": _area_scores(row["verified_area_scores"]),
            "verified_overall_score": num(row["verified_overall_score"]),
            "decided_overall_score": num(row["decided_overall_score"]),
            "decided_min_area_score": num(row["decided_min_area_score"]),
            "gate_applied": row["gate_applied"],
            "grade": row["grade"],
            "submitted_at": iso(row["submitted_at"]),
            "decided_at": iso(row["decided_at"]),
            "decided_by_user_id": row["decided_by_user_id"],
            "last_deficiency_by_user_id": row["last_deficiency_by_user_id"],
            "reviewer_note": row["reviewer_note"],
            "superseded_by_assessment_id": row["superseded_by_assessment_id"],
        }
    )
    return out


def criterion_response(row):
    out = _common(row)
    out.update(
        {
            "assessment_id": row["assessment_id"],
            "criterion_id": row["criterion_id"],
            "self_declared_conformant": row["self_declared_conformant"],
            "evidence_ref": row["evidence_ref"],
            "lab_result": row["lab_result"],
            "lab_verified": row["lab_verified"],
        }
    )
    return out


def test_lab(row):
    out = _common(row)
    out.update(
        {
            "lab_name": row["lab_name"],
            "accreditation_status": row["accreditation_status"],
            "total_bench_hours": row["total_bench_hours"],
            "concurrent_bench_capacity": row["concurrent_bench_capacity"],
            "reserved_bench_hours": row["reserved_bench_hours"],
            "available_bench_hours": row["available_bench_hours"],
        }
    )
    return out


def test_engagement(row):
    out = _common(row)
    out.update(
        {
            "assessment_id": row["assessment_id"],
            "test_lab_id": row["test_lab_id"],
            "window_start": iso(row["window_start"]),
            "window_end": iso(row["window_end"]),
            "bench_hours": row["bench_hours"],
            "status": row["status"],
            "failed_criterion_codes": row["failed_criterion_codes"],
            "report_reference": row["report_reference"],
            "cancellation_reason": row["cancellation_reason"],
            "completed_at": iso(row["completed_at"]),
        }
    )
    return out


def label_grant(row):
    out = _common(row)
    out.update(
        {
            "product_id": row["product_id"],
            "assessment_id": row["assessment_id"],
            "scannable_code": row["scannable_code"],
            "grant_status": row["grant_status"],
            "registry_publication_status": row["registry_publication_status"],
            "suspension_reason": row["suspension_reason"],
            "renewal_required": row["renewal_required"],
            "valid_from": iso(row["valid_from"]),
            "valid_until": iso(row["valid_until"]),
            "renewal_generation": row["renewal_generation"],
            "issuance_fee_cents": row["issuance_fee_cents"],
            "superseded_by_grant_id": row["superseded_by_grant_id"],
        }
    )
    return out


def registry_entry(row):
    out = _common(row)
    out.update(
        {
            "label_grant_id": row["label_grant_id"],
            "support_period_end": iso(row["support_period_end"]),
            "update_policy_url": row["update_policy_url"],
            "update_cadence": row["update_cadence"],
            "vuln_disclosure_contact": row["vuln_disclosure_contact"],
            "disclosure_completeness": row["disclosure_completeness"],
            "published_at": iso(row["published_at"]),
            "published_by_user_id": row["published_by_user_id"],
        }
    )
    return out


def retailer(row):
    out = _common(row)
    out.update(
        {
            "retailer_name": row["retailer_name"],
            "education_materials_ack": row["education_materials_ack"],
            "education_program_version": row["education_program_version"],
            "active_display_count": row["active_display_count"],
            "participation_tier": row["participation_tier"],
        }
    )
    return out


def display_authorization(row):
    out = _common(row)
    out.update(
        {
            "retailer_id": row["retailer_id"],
            "label_grant_id": row["label_grant_id"],
            "channel": row["channel"],
            "display_from": iso(row["display_from"]),
            "display_until": iso(row["display_until"]),
            "status": row["status"],
            "withdrawal_reason": row["withdrawal_reason"],
        }
    )
    return out


def enforcement_case(row):
    out = _common(row)
    out.update(
        {
            "subject_manufacturer_id": row["subject_manufacturer_id"],
            "reported_retailer_id": row["reported_retailer_id"],
            "reported_scannable_code": row["reported_scannable_code"],
            "code_matches_registry": row["code_matches_registry"],
            "violation_type": row["violation_type"],
            "violation_line_items": [dict(line) for line in row["violation_line_items"]],
            "violation_unit_count": row["violation_unit_count"],
            "case_status": row["case_status"],
            "penalty_status": row["penalty_status"],
            "penalty_variant": row["penalty_variant"],
            "penalty_cents": row["penalty_cents"],
            "aggravation_multiplier": num(row["aggravation_multiplier"]),
            "notice_reference": row["notice_reference"],
            "notice_issued_by_user_id": row["notice_issued_by_user_id"],
            "adjudicated_by_user_id": row["adjudicated_by_user_id"],
            "referred_test_lab_id": row["referred_test_lab_id"],
            "adjudicated_at": iso(row["adjudicated_at"]),
            "vacate_reason": row["vacate_reason"],
            "payment_reference": row["payment_reference"],
            "reporter_note": row["reporter_note"],
        }
    )
    return out


def recognition_survey(row):
    out = _record(row)
    out.update(
        {
            "survey_period_label": row["survey_period_label"],
            "survey_period_end": iso(row["survey_period_end"]),
            "respondents_count": row["respondents_count"],
            "recognized_count": row["recognized_count"],
        }
    )
    return out
