"""Live derived aggregates (PRD 2.9, 3.1, 3.2, 3.4) and JSON serialization."""

from decimal import Decimal

import calc
import store

ALLOCATING_AOI_STATUSES = ("ISSUED", "USE_REPORTED", "BILLED", "CLOSED")
OUTSTANDING_BILL_STATUSES = ("ISSUED", "DELINQUENT")


def num2(value):
    return float(calc.aums2(value))


def num4(value):
    return float(calc.pct4(value))


def num_score(value):
    if value is None:
        return None
    return float(calc.score2(value))


# --------------------------------------------------------------------- allotment


def aois_of_allotment(allotment_id):
    out = []
    for aoi in store.rows("aois"):
        permit = store.get("permits", aoi["permit_id"])
        if permit is not None and permit["allotment_id"] == allotment_id:
            out.append(aoi)
    return out


def allocated_aums(allotment):
    year = store.current_grazing_year()
    total = 0
    for aoi in aois_of_allotment(allotment["id"]):
        if aoi["grazing_year"] != year:
            continue
        if aoi["aoi_status"] not in ALLOCATING_AOI_STATUSES:
            continue
        total += aoi["authorized_aums"] - aoi["nonuse_aums"]
    return total


def effective_capacity_aums(allotment):
    return calc.effective_capacity(allotment["total_permitted_aums"],
                                   allotment["stocking_adjustment_pct"])


def open_aums(allotment):
    return effective_capacity_aums(allotment) - allocated_aums(allotment)


def allotment_of_permit(permit):
    return store.get("allotments", permit["allotment_id"])


def allotment_of_aoi(aoi):
    permit = store.get("permits", aoi["permit_id"])
    return allotment_of_permit(permit) if permit else None


def permittee_of_aoi(aoi):
    permit = store.get("permits", aoi["permit_id"])
    return permit["permittee_id"] if permit else None


# ----------------------------------------------------------------------- pasture


def scheduled_aums(pasture):
    """PRD 3.1: planned_aums over records of current-year, non-draft instructions."""
    allotment = store.get("allotments", pasture["allotment_id"])
    year = store.current_grazing_year()
    total = Decimal("0")
    for record in store.rows("use_records"):
        if record["pasture_id"] != pasture["id"]:
            continue
        aoi = store.get("aois", record["aoi_id"])
        if aoi is None or aoi["grazing_year"] != year:
            continue
        if aoi["aoi_status"] not in ALLOCATING_AOI_STATUSES:
            continue
        if allotment is None:
            continue
        total += calc.dec(record["planned_aums"])
    return total


# --------------------------------------------------------------------- permittee


def bills_of_permittee(permittee_id):
    return [bill for bill in store.rows("bills")
            if bill["permittee_id"] == permittee_id]


def outstanding_balance_cents(permittee_id):
    total = 0
    for bill in bills_of_permittee(permittee_id):
        if bill["bill_status"] in OUTSTANDING_BILL_STATUSES:
            total += bill["total_amount_cents"] - bill["amount_paid_cents"]
    return total


def has_delinquent_bill(permittee_id):
    for bill in bills_of_permittee(permittee_id):
        if bill["bill_status"] == "DELINQUENT":
            return True
    return False


def permittee_status(permittee_id):
    balance = outstanding_balance_cents(permittee_id)
    if balance > 0 and has_delinquent_bill(permittee_id):
        return "DEBT_FLAGGED"
    return "IN_GOOD_STANDING"


def billed_trespass_incident_count(permittee_id):
    return len([incident for incident in store.rows("trespass_incidents")
                if incident["permittee_id"] == permittee_id
                and incident["incident_status"] in ("BILLED", "RESOLVED")])


# --------------------------------------------------------------------------- aoi


def records_of_aoi(aoi_id):
    return [record for record in store.rows("use_records")
            if record["aoi_id"] == aoi_id]


def planned_aums_total(aoi):
    total = Decimal("0")
    for record in records_of_aoi(aoi["id"]):
        total += calc.dec(record["planned_aums"])
    return total


def actual_aums_total(aoi):
    total = Decimal("0")
    for record in records_of_aoi(aoi["id"]):
        if record["record_status"] in ("ACTUAL_REPORTED", "ACCEPTED") \
                and record["actual_aums"] is not None:
            total += calc.dec(record["actual_aums"])
    return total


def distinct_pasture_count(aoi):
    return len({record["pasture_id"] for record in records_of_aoi(aoi["id"])})


def billable_aums(aoi):
    return aoi["authorized_aums"] - aoi["nonuse_aums"]


# --------------------------------------------------------------------- serializers


def common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def allotment_json(record):
    out = common(record)
    out.update({
        "name": record["name"],
        "admin_unit_code": record["admin_unit_code"],
        "acres": record["acres"],
        "total_permitted_aums": record["total_permitted_aums"],
        "season_start": record["season_start"],
        "season_end": record["season_end"],
        "required_pasture_rotation_count": record["required_pasture_rotation_count"],
        "stocking_adjustment_pct": num4(record["stocking_adjustment_pct"]),
        "effective_capacity_aums": effective_capacity_aums(record),
        "allocated_aums": allocated_aums(record),
        "open_aums": open_aums(record),
        "allotment_status": record["allotment_status"],
        "health_determination": record["health_determination"],
        "current_grazing_year": store.current_grazing_year(),
    })
    return out


def pasture_json(record):
    out = common(record)
    out.update({
        "allotment_id": record["allotment_id"],
        "name": record["name"],
        "sequence_order": record["sequence_order"],
        "pasture_aum_capacity": record["pasture_aum_capacity"],
        "rest_required": record["rest_required"],
        "scheduled_aums": num2(scheduled_aums(record)),
    })
    return out


def permittee_json(record):
    out = common(record)
    out.update({
        "name": record["name"],
        "contact_email": record["contact_email"],
        "permittee_status": permittee_status(record["id"]),
        "outstanding_balance_cents": outstanding_balance_cents(record["id"]),
        "billed_trespass_incident_count":
            billed_trespass_incident_count(record["id"]),
    })
    return out


def base_property_json(record):
    out = common(record)
    out.update({
        "permittee_id": record["permittee_id"],
        "base_property_type": record["base_property_type"],
        "legal_description": record["legal_description"],
        "carrying_capacity_aums": record["carrying_capacity_aums"],
        "controlled_since_date": record["controlled_since_date"],
        "qualified_aums": calc.qualified_aums(record["base_property_type"],
                                              record["carrying_capacity_aums"]),
    })
    return out


def permit_json(record):
    out = common(record)
    out.update({
        "allotment_id": record["allotment_id"],
        "permittee_id": record["permittee_id"],
        "base_property_id": record["base_property_id"],
        "predecessor_permit_id": record["predecessor_permit_id"],
        "permitted_aums": record["permitted_aums"],
        "term_start_date": record["term_start_date"],
        "term_end_date": record["term_end_date"],
        "livestock_kind": record["livestock_kind"],
        "preference_priority": record["preference_priority"],
        "permit_status": record["permit_status"],
        "account_status": record["account_status"],
        "suspension_reason": record["suspension_reason"],
        "consecutive_nonuse_years": record["consecutive_nonuse_years"],
    })
    return out


def aoi_json(record):
    out = common(record)
    out.update({
        "permit_id": record["permit_id"],
        "grazing_year": record["grazing_year"],
        "authorized_aums": record["authorized_aums"],
        "authorized_aums_at_issue": record["authorized_aums_at_issue"],
        "nonuse_aums": record["nonuse_aums"],
        "nonuse_reason": record["nonuse_reason"],
        "billable_aums": billable_aums(record),
        "season_start_date": record["season_start_date"],
        "season_end_date": record["season_end_date"],
        "planned_aums_total": num2(planned_aums_total(record)),
        "actual_aums_total": num2(actual_aums_total(record)),
        "distinct_pasture_count": distinct_pasture_count(record),
        "aoi_status": record["aoi_status"],
        "void_reason": record["void_reason"],
    })
    return out


def use_record_json(record):
    out = common(record)
    out.update({
        "aoi_id": record["aoi_id"],
        "pasture_id": record["pasture_id"],
        "planned_entry_date": record["planned_entry_date"],
        "planned_exit_date": record["planned_exit_date"],
        "planned_head_count": record["planned_head_count"],
        "livestock_kind": record["livestock_kind"],
        "planned_aums": num2(record["planned_aums"]),
        "actual_entry_date": record["actual_entry_date"],
        "actual_exit_date": record["actual_exit_date"],
        "actual_head_count": record["actual_head_count"],
        "actual_aums": (None if record["actual_aums"] is None
                        else num2(record["actual_aums"])),
        "record_status": record["record_status"],
    })
    return out


def bill_json(record):
    out = common(record)
    out.update({
        "permittee_id": record["permittee_id"],
        "aoi_id": record["aoi_id"],
        "trespass_incident_id": record["trespass_incident_id"],
        "project_id": record["project_id"],
        "superseded_bill_id": record["superseded_bill_id"],
        "bill_type": record["bill_type"],
        "billed_aums": num2(record["billed_aums"]),
        "fee_rate_cents_per_aum": record["fee_rate_cents_per_aum"],
        "base_amount_cents": record["base_amount_cents"],
        "admin_fee_cents": record["admin_fee_cents"],
        "penalty_amount_cents": record["penalty_amount_cents"],
        "total_amount_cents": record["total_amount_cents"],
        "amount_paid_cents": record["amount_paid_cents"],
        "due_date": record["due_date"],
        "bill_status": record["bill_status"],
        "void_reason": record["void_reason"],
    })
    return out


def assessment_json(record):
    out = common(record)
    out.update({
        "allotment_id": record["allotment_id"],
        "assessment_year": record["assessment_year"],
        "monitoring_method": record["monitoring_method"],
        "upland_score": record["upland_score"],
        "riparian_score": record["riparian_score"],
        "water_quality_score": record["water_quality_score"],
        "observed_utilization_pct": record["observed_utilization_pct"],
        "standards_not_met": list(record["standards_not_met"]),
        "causal_factor_is_livestock": record["causal_factor_is_livestock"],
        "composite_score": num_score(record["composite_score"]),
        "determination": record["determination"],
        "recommended_reduction_pct": num4(record["recommended_reduction_pct"]),
        "assessment_status": record["assessment_status"],
        "author_user_id": record["author_user_id"],
        "review_notes": record["review_notes"],
        "remand_count": record["remand_count"],
    })
    return out


def decision_json(record):
    out = common(record)
    out.update({
        "allotment_id": record["allotment_id"],
        "permit_id": record["permit_id"],
        "assessment_id": record["assessment_id"],
        "decision_type": record["decision_type"],
        "adjustment_pct": (None if record["adjustment_pct"] is None
                           else num4(record["adjustment_pct"])),
        "pre_decision_adjustment_pct":
            (None if record["pre_decision_adjustment_pct"] is None
             else num4(record["pre_decision_adjustment_pct"])),
        "nepa_level": record["nepa_level"],
        "nepa_status": record["nepa_status"],
        "nepa_findings_summary": record["nepa_findings_summary"],
        "decision_status": record["decision_status"],
        "authoring_officer_id": record["authoring_officer_id"],
        "deciding_officer_id": record["deciding_officer_id"],
        "rationale": record["rationale"],
        "effective_date": record["effective_date"],
    })
    return out


def appeal_json(record):
    out = common(record)
    out.update({
        "decision_id": record["decision_id"],
        "appellant_permittee_id": record["appellant_permittee_id"],
        "statement_of_reasons": record["statement_of_reasons"],
        "stay_requested": record["stay_requested"],
        "stay_granted": record["stay_granted"],
        "appeal_status": record["appeal_status"],
        "adjudicator_id": record["adjudicator_id"],
        "appeal_outcome": record["appeal_outcome"],
        "decision_rationale": record["decision_rationale"],
        "remand_count": record["remand_count"],
    })
    return out


def closure_order_json(record):
    out = common(record)
    out.update({
        "allotment_id": record["allotment_id"],
        "order_type": record["order_type"],
        "reduction_pct": num4(record["reduction_pct"]),
        "effective_start_date": record["effective_start_date"],
        "effective_end_date": record["effective_end_date"],
        "justification": record["justification"],
        "issuing_officer_id": record["issuing_officer_id"],
        "order_status": record["order_status"],
    })
    return out


def trespass_json(record):
    out = common(record)
    out.update({
        "allotment_id": record["allotment_id"],
        "permittee_id": record["permittee_id"],
        "detected_at": record["detected_at"],
        "head_count": record["head_count"],
        "livestock_kind": record["livestock_kind"],
        "unauthorized_days": record["unauthorized_days"],
        "willfulness": record["willfulness"],
        "unauthorized_aums": num2(record["unauthorized_aums"]),
        "billed_aums": num2(record["billed_aums"]),
        "prior_billed_incident_count": record["prior_billed_incident_count"],
        "incident_status": record["incident_status"],
    })
    return out


def project_json(record):
    out = common(record)
    out.update({
        "allotment_id": record["allotment_id"],
        "project_type": record["project_type"],
        "total_cost_cents": record["total_cost_cents"],
        "agency_share_pct": num4(record["agency_share_pct"]),
        "permittee_share_pct": num4(record["permittee_share_pct"]),
        "permittee_share_cents": record["permittee_share_cents"],
        "allocated_share_cents": record["allocated_share_cents"],
        "maintenance_responsibility": record["maintenance_responsibility"],
        "project_status": record["project_status"],
    })
    return out
