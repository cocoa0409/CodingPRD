"""Entity serializers. Explicit field lists so internal keys (``_seq``,
``_suspended_contract_ids``) never leak. Two timestamp families:
created_at/updated_at -> 3 fractional digits; domain timestamps -> as the
logical clock reads."""
from clock import CLOCK


def _sys(rec, versioned=True):
    out = {"created_at": CLOCK.render_precise(rec["created_at"])}
    if versioned:
        out["updated_at"] = CLOCK.render_precise(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def _dom(dt):
    return None if dt is None else CLOCK.render(dt)


def ser_carrier(c):
    return {
        "id": c["id"],
        "org_name": c["org_name"],
        "org_type": c["org_type"],
        "status": c["status"],
        "compliance_score": c["compliance_score"],
        "cumulative_civil_penalties_cents": c["cumulative_civil_penalties_cents"],
        **_sys(c),
    }


def ser_shipper(s):
    return {
        "id": s["id"],
        "company_name": s["company_name"],
        "contact_email": s["contact_email"],
        "total_recovery_cents": s["total_recovery_cents"],
        **_sys(s),
    }


def ser_tariff(t):
    return {
        "id": t["id"],
        "carrier_id": t["carrier_id"],
        "tariff_code": t["tariff_code"],
        "charge_scope": t["charge_scope"],
        "free_time_days": t["free_time_days"],
        "per_diem_rate_cents": t["per_diem_rate_cents"],
        "accrual_method": t["accrual_method"],
        "change_type": t["change_type"],
        "notice_period_days": t["notice_period_days"],
        "effective_date": _dom(t["effective_date"]),
        "filed_at": _dom(t["filed_at"]),
        "publication_status": t["publication_status"],
        **_sys(t),
    }


def ser_contract(c):
    return {
        "id": c["id"],
        "carrier_id": c["carrier_id"],
        "contract_reference": c["contract_reference"],
        "shipper_id": c["shipper_id"],
        "agreed_at": _dom(c["agreed_at"]),
        "duration_months": c["duration_months"],
        "minimum_quantity_commitment": c["minimum_quantity_commitment"],
        "negotiated_free_time_days": c["negotiated_free_time_days"],
        "negotiated_per_diem_rate_cents": c["negotiated_per_diem_rate_cents"],
        "negotiated_accrual_method": c["negotiated_accrual_method"],
        "filed_at": _dom(c["filed_at"]),
        "contract_status": c["contract_status"],
        **_sys(c),
    }


def _ser_monitoring_report(r):
    return {
        "reporting_period_start": _dom(r["reporting_period_start"]),
        "reporting_period_end": _dom(r["reporting_period_end"]),
        "total_market_teus": r["total_market_teus"],
        "member_volumes": [
            {"carrier_id": e["carrier_id"], "carried_teus": e["carried_teus"]}
            for e in r["member_volumes"]
        ],
        "hhi": float(r["hhi"]) if r["hhi"] is not None else None,
    }


def ser_agreement(a):
    return {
        "id": a["id"],
        "agreement_number": a["agreement_number"],
        "agreement_type": a["agreement_type"],
        "member_carrier_ids": list(a["member_carrier_ids"]),
        "filed_by_carrier_id": a["filed_by_carrier_id"],
        "filed_at": _dom(a["filed_at"]),
        "waiting_period_ends_at": _dom(a["waiting_period_ends_at"]),
        "review_status": a["review_status"],
        "monitoring_reports": [
            _ser_monitoring_report(r) for r in a["monitoring_reports"]
        ],
        "market_concentration_hhi": (
            float(a["market_concentration_hhi"])
            if a["market_concentration_hhi"] is not None else None
        ),
        "competitive_concern_flag": a["competitive_concern_flag"],
        **_sys(a),
    }


def _ser_bond(b):
    return {
        "bond_ref": b["bond_ref"],
        "surety_name": b["surety_name"],
        "coverage_cents": b["coverage_cents"],
        "drawn_cents": b["drawn_cents"],
        "available_cents": b["available_cents"],
        "bond_status": b["bond_status"],
    }


def ser_license(lic):
    return {
        "id": lic["id"],
        "organization_id": lic["organization_id"],
        "license_type": lic["license_type"],
        "license_status": lic["license_status"],
        "required_bond_cents": lic["required_bond_cents"],
        "surety_bonds": [_ser_bond(b) for b in lic["surety_bonds"]],
        "total_available_coverage_cents": lic["total_available_coverage_cents"],
        **_sys(lic),
    }


def ser_invoice(i):
    return {
        "id": i["id"],
        "carrier_id": i["carrier_id"],
        "invoice_number": i["invoice_number"],
        "charge_basis": i["charge_basis"],
        "tariff_id": i["tariff_id"],
        "service_contract_id": i["service_contract_id"],
        "billed_party_shipper_id": i["billed_party_shipper_id"],
        "container_number": i["container_number"],
        "port_code": i["port_code"],
        "availability_date": _dom(i["availability_date"]),
        "return_date": _dom(i["return_date"]),
        "last_accrual_date": _dom(i["last_accrual_date"]),
        "government_hold_days": i["government_hold_days"],
        "appointment_unavailable_days": i["appointment_unavailable_days"],
        "free_time_days": i["free_time_days"],
        "per_diem_rate_cents": i["per_diem_rate_cents"],
        "accrual_method": i["accrual_method"],
        "billable_days": i["billable_days"],
        "amount_cents": i["amount_cents"],
        "issued_at": _dom(i["issued_at"]),
        "invoice_status": i["invoice_status"],
        **_sys(i),
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "invoice_id": d["invoice_id"],
        "dispute_reason": d["dispute_reason"],
        "filed_at": _dom(d["filed_at"]),
        "response_due_at": _dom(d["response_due_at"]),
        "responded_at": _dom(d["responded_at"]),
        "requested_resolution": d["requested_resolution"],
        "resolution": d["resolution"],
        "response_was_late": d["response_was_late"],
        "resolved_amount_cents": d["resolved_amount_cents"],
        **_sys(d),
    }


def ser_complaint(c):
    return {
        "id": c["id"],
        "shipper_id": c["shipper_id"],
        "respondent_carrier_id": c["respondent_carrier_id"],
        "subject_invoice_ids": list(c["subject_invoice_ids"]),
        "reparations_claimed_cents": c["reparations_claimed_cents"],
        "incentive_principle_score": c["incentive_principle_score"],
        "complaint_status": c["complaint_status"],
        "ombuds_officer_id": c["ombuds_officer_id"],
        "ombuds_rounds": c["ombuds_rounds"],
        "informal_settlement_cents": c["informal_settlement_cents"],
        "presiding_judge_id": c["presiding_judge_id"],
        "reparation_method": c["reparation_method"],
        "reparations_awarded_cents": c["reparations_awarded_cents"],
        "decided_at": _dom(c["decided_at"]),
        "appeal_deadline": _dom(c["appeal_deadline"]),
        **_sys(c),
    }


def ser_proceeding(p):
    return {
        "id": p["id"],
        "target_carrier_id": p["target_carrier_id"],
        "basis": p["basis"],
        "opened_by_counsel_id": p["opened_by_counsel_id"],
        "proceeding_status": p["proceeding_status"],
        "determination": p["determination"],
        "violation_count": p["violation_count"],
        "willful": p["willful"],
        "repeat_offender": p["repeat_offender"],
        "penalty_cents": p["penalty_cents"],
        "score_delta": p["score_delta"],
        "determined_at": _dom(p["determined_at"]),
        **_sys(p),
    }


def ser_congestion(r):
    # Append-only data-collection record: id + created_at only (PRD §2.5).
    return {
        "id": r["id"],
        "port_code": r["port_code"],
        "terminal_code": r["terminal_code"],
        "week_start": _dom(r["week_start"]),
        "berth_occupancy_hours": r["berth_occupancy_hours"],
        "gate_closures_hours": r["gate_closures_hours"],
        "vessel_dwell_hours_avg": r["vessel_dwell_hours_avg"],
        "created_at": CLOCK.render_precise(r["created_at"]),
    }
