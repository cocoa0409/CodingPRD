"""Payload factories — one per entity, carrying only client-supplied fields.

Monetary figures are whole-cent JSON numbers, never strings. Every timestamp is
a full ISO 8601 UTC instant. `ein` is exactly nine digits, as the PRD requires.
"""

DEFAULTS = {
    "ORG_LEGAL_NAME": "Harbor Relief Fund",
    "ORG_EIN": "111111111",
    "ORG_TYPE": "PUBLIC_CHARITY",
    "ORG_FISCAL_YEAR_END_MONTH": 12,
    "ORG_CONTACT_EMAIL": "ops@harborrelief.org",
    "METHODOLOGY_LABEL": "M1",
    "FISCAL_YEAR": 2025,
    "PERIOD_START": "2025-01-01T00:00:00Z",
    "PERIOD_END": "2026-01-01T00:00:00Z",
    "ANALYST_USER_ID": "analyst-1",
}


def create_organization_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["ORG_LEGAL_NAME"],
        "ein": DEFAULTS["ORG_EIN"],
        "org_type": DEFAULTS["ORG_TYPE"],
        "fiscal_year_end_month": DEFAULTS["ORG_FISCAL_YEAR_END_MONTH"],
        "contact_email": DEFAULTS["ORG_CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_methodology_version_payload(**overrides) -> dict:
    payload = {
        "version_label": DEFAULTS["METHODOLOGY_LABEL"],
        "weight_financial_health": 0.4,
        "weight_accountability": 0.25,
        "weight_transparency": 0.2,
        "weight_impact": 0.15,
        "dimension_floor_score": 40.0,
    }
    payload.update(overrides)
    return payload


def adopt_methodology_payload(effective_from, effective_until=None) -> dict:
    payload = {"effective_from": effective_from}
    if effective_until is not None:
        payload["effective_until"] = effective_until
    return payload


def return_to_draft_payload(revision_note="Weights revised after comment", **overrides) -> dict:
    payload = {"revision_note": revision_note}
    payload.update(overrides)
    return payload


def create_public_comment_payload(methodology_version_id, **overrides) -> dict:
    payload = {
        "methodology_version_id": methodology_version_id,
        "commenter_kind": "PUBLIC",
        "body": "The impact weight is too low for programme-heavy charities.",
    }
    payload.update(overrides)
    return payload


def dispose_public_comment_payload(disposition="DECLINED", **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def create_filing_record_payload(
    organization_id,
    expected_organization_version,
    fiscal_year=2025,
    source_kind="AUDITED_STATEMENT",
    total_expense_cents=10000000,
    program_expense_cents=8000000,
    fundraising_expense_cents=1200000,
    admin_expense_cents=800000,
    contributions_cents=9000000,
    total_revenue_cents=11000000,
    net_assets_cents=6000000,
    total_liabilities_cents=2000000,
    **overrides,
) -> dict:
    payload = {
        "organization_id": organization_id,
        "fiscal_year": fiscal_year,
        "source_kind": source_kind,
        "total_expense_cents": total_expense_cents,
        "program_expense_cents": program_expense_cents,
        "fundraising_expense_cents": fundraising_expense_cents,
        "admin_expense_cents": admin_expense_cents,
        "contributions_cents": contributions_cents,
        "total_revenue_cents": total_revenue_cents,
        "net_assets_cents": net_assets_cents,
        "total_liabilities_cents": total_liabilities_cents,
        "expected_organization_version": expected_organization_version,
    }
    payload.update(overrides)
    return payload


def validate_filing_payload(decision="ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_governance_profile_payload(rating_cycle_id, **overrides) -> dict:
    payload = {
        "rating_cycle_id": rating_cycle_id,
        "board_member_count": 7,
        "independent_board_member_count": 4,
        "conflict_of_interest_policy_on_file": True,
        "coi_policy_reviewed_at": "2026-03-01T00:00:00Z",
        "board_meetings_last_year": 4,
        "audit_committee_exists": True,
        "whistleblower_policy": True,
        "ceo_compensation_reviewed": False,
        "impact_report_on_file": True,
        "outcome_measures_count": 3,
        "third_party_evaluation_on_file": True,
    }
    payload.update(overrides)
    return payload


def waive_standard_payload(waiver_reason="Board expansion already voted", **overrides) -> dict:
    payload = {"waiver_reason": waiver_reason}
    payload.update(overrides)
    return payload


def revoke_waiver_payload(revocation_note="Board expansion never happened", **overrides) -> dict:
    payload = {"revocation_note": revocation_note}
    payload.update(overrides)
    return payload


def create_rating_cycle_payload(
    organization_id,
    methodology_version_id,
    fiscal_year=2025,
    period_start="2025-01-01T00:00:00Z",
    period_end="2026-01-01T00:00:00Z",
    assigned_analyst_user_id="analyst-1",
    **overrides,
) -> dict:
    payload = {
        "organization_id": organization_id,
        "methodology_version_id": methodology_version_id,
        "fiscal_year": fiscal_year,
        "period_start": period_start,
        "period_end": period_end,
        "assigned_analyst_user_id": assigned_analyst_user_id,
    }
    payload.update(overrides)
    return payload


def publish_payload(publishing_reviewer_note="Cleared for release", **overrides) -> dict:
    payload = {"publishing_reviewer_note": publishing_reviewer_note}
    payload.update(overrides)
    return payload


def withdraw_payload(withdrawal_reason="Organization dissolved mid-review", **overrides) -> dict:
    payload = {"withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload


def dimension_overrides_payload(
    overrides_list, expected_rating_cycle_version, override_reason="Analyst judgement", **extra
) -> dict:
    payload = {
        "overrides": overrides_list,
        "override_reason": override_reason,
        "expected_rating_cycle_version": expected_rating_cycle_version,
    }
    payload.update(extra)
    return payload


def create_correction_request_payload(rating_cycle_id, **overrides) -> dict:
    payload = {
        "rating_cycle_id": rating_cycle_id,
        "target_kind": "FILING_FINANCIAL",
        "target_fiscal_year": 2025,
        "target_source_kind": "AUDITED_STATEMENT",
        "target_field_name": "net_assets_cents",
        "proposed_value": "2000000",
        "narrative": "Reserve figure was transcribed from the wrong schedule",
    }
    payload.update(overrides)
    # `target_fiscal_year` and `target_source_kind` are conditional on the
    # target kind, so an override of None means "omit this field entirely".
    return {key: value for key, value in payload.items() if value is not None}


def decide_correction_payload(decision="REJECT", **overrides) -> dict:
    payload = {"decision": decision}
    if decision == "REJECT":
        payload["decision_note"] = "The audited statement matches the figure on file"
    else:
        payload["decision_note"] = "The restated schedule supports the change"
    payload.update(overrides)
    return payload


def create_appeal_payload(rating_cycle_id, correction_request_id, **overrides) -> dict:
    payload = {
        "rating_cycle_id": rating_cycle_id,
        "correction_request_id": correction_request_id,
        "grounds": "The rejection ignored the restated audit schedule",
    }
    payload.update(overrides)
    return payload


def assign_panel_payload(panel_member_user_ids=None, **overrides) -> dict:
    payload = {
        "panel_member_user_ids": list(
            panel_member_user_ids or ["panel-1", "panel-2", "panel-3"]
        )
    }
    payload.update(overrides)
    return payload


def decide_appeal_payload(decision="DENY", **overrides) -> dict:
    payload = {"decision": decision, "decision_note": "Panel finding recorded"}
    payload.update(overrides)
    return payload


def create_complaint_payload(organization_id, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "complainant_kind": "DONOR",
        "category": "MISUSE_OF_FUNDS",
        "narrative": "Restricted gifts appear to have funded unrelated overheads.",
        "corroborating_document_count": 0,
    }
    payload.update(overrides)
    return payload


def triage_complaint_payload(disposition="INVESTIGATE", **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def resolve_complaint_payload(finding="SUBSTANTIATED", penalty_points=None, **overrides) -> dict:
    payload = {"finding": finding}
    if penalty_points is not None:
        payload["penalty_points"] = penalty_points
    payload.update(overrides)
    return payload


def reverse_finding_payload(reversal_reason="The witness statement was recanted", **overrides) -> dict:
    payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
