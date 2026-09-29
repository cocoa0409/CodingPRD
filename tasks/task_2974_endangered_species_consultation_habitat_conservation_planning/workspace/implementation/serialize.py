"""Resource representations.  Field order follows the scaffold entity table."""
import datetime

import util

SPECIES = (
    "scientific_name",
    "common_name",
    "listing_status",
    "critical_habitat_designated",
    "take_authorization_unit",
    "take_density_per_acre",
    "recovery_unit_population",
    "survey_season_start_month",
    "survey_season_end_month",
    "listing_change_count",
    "last_listing_change_at",
)

PROPONENT = (
    "org_name",
    "contact_email",
    "is_federal_agency",
    "compliance_standing_score",
    "compliance_variant_applied",
    "open_reinitiation_count",
)

HABITAT_UNIT = (
    "species_id",
    "unit_code",
    "acres",
    "county_code",
    "designation_status",
    "primary_constituent_elements",
)

ACTION = (
    "proponent_id",
    "action_name",
    "action_type",
    "footprint_acres",
    "county_code",
    "construction_start_date",
    "construction_end_date",
    "status",
    "effect_determination",
    "total_overlap_acres",
    "overlap_pct",
    "active_consultation_id",
    "reinitiation_reason",
)

DETERMINATION = (
    "project_action_id",
    "species_id",
    "critical_habitat_unit_id",
    "method",
    "detection_result",
    "survey_window_start",
    "survey_window_end",
    "habitat_overlap_acres",
    "presence_status",
    "survey_in_season",
    "requires_reevaluation",
)

CONSULTATION = (
    "project_action_id",
    "consultation_type",
    "status",
    "clock_started_at",
    "statutory_days",
    "tolled_days",
    "deadline_at",
    "ba_revision_number",
    "ba_submitted_at",
    "ba_narrative",
    "ba_effects_analysis_complete",
    "info_request_count",
    "info_requested_at",
    "reinitiation_triggered_at",
    "reinitiation_count",
)

OPINION = (
    "consultation_id",
    "primary_species_scientific_name",
    "primary_species_listing_status",
    "conclusion",
    "rpa_required",
    "rpa_description",
    "exposed_acres",
    "take_unit",
    "authorized_take_units",
    "jeopardy_fraction",
    "reinitiation_trigger_units",
    "issued_by_user_id",
    "issued_at",
    "issued_late",
)

BANK = (
    "bank_name",
    "covered_species_id",
    "service_area_county_codes",
    "credit_price_cents",
    "credits_total_minted",
    "credits_available",
    "credits_reserved",
    "credits_transferred",
)

PLAN = (
    "project_action_id",
    "plan_name",
    "covered_acres",
    "permit_term_years",
    "plan_status",
    "funding_status",
    "preliminary_mitigation_units",
    "final_mitigation_units",
    "mitigation_delta_units",
    "secured_mitigation_units",
    "endowment_base_cents",
    "changed_circumstance_reserve_cents",
    "endowment_required_cents",
    "endowment_secured_cents",
    "funded_ratio",
    "reserve_drawn_cents",
    "reserve_remaining_cents",
    "approved_by_user_id",
    "assurance_review_required",
)

COMMITMENT = (
    "hcp_id",
    "conservation_bank_id",
    "mechanism",
    "units",
    "status",
    "base_fee_cents",
    "admin_fee_pct_applied",
    "admin_fee_cents",
    "total_cost_cents",
    "endowment_contribution_cents",
)

PERMIT = (
    "hcp_id",
    "permit_number",
    "status",
    "term_start",
    "term_end",
    "implementing_agreement_reference",
    "issued_by_user_id",
    "authorized_take_units",
    "take_unit",
    "reinitiation_trigger_units",
    "take_consumed_units",
    "take_remaining_units",
    "suspension_count",
)

REPORT = (
    "permit_id",
    "period_start",
    "period_end",
    "take_units_reported",
    "mitigation_units_verified",
    "submitted_at",
    "due_at",
    "is_late",
    "status",
    "adjudicated_at",
    "adjudicated_by_user_id",
    "adjudication_note",
)

EVENT = (
    "hcp_id",
    "circumstance_type",
    "description",
    "response_cost_cents",
    "reported_at",
    "status",
    "reserve_draw_cents",
    "required_additional_cents",
    "contributed_cents",
    "permittee_borne_cents",
    "agency_borne_cents",
    "assurances_invoked",
    "response_note",
)


def _scalar(value):
    if isinstance(value, datetime.datetime):
        return util.fmt_instant(value)
    if isinstance(value, datetime.date):
        return util.fmt_date(value)
    if isinstance(value, list):
        return list(value)
    return value


def render(row, fields, versioned=True):
    out = {"id": row["id"]}
    for name in fields:
        out[name] = _scalar(row.get(name))
    out["created_at"] = util.fmt_instant(row["created_at"])
    if versioned:
        out["updated_at"] = util.fmt_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


def species(row):
    return render(row, SPECIES)


def proponent(row):
    return render(row, PROPONENT)


def habitat_unit(row):
    return render(row, HABITAT_UNIT)


def action(row):
    return render(row, ACTION)


def determination(row):
    return render(row, DETERMINATION)


def consultation(row):
    return render(row, CONSULTATION)


def opinion(row):
    # A biological opinion is immutable: no updated_at, no version.
    return render(row, OPINION, versioned=False)


def bank(row):
    return render(row, BANK)


def plan(row):
    return render(row, PLAN)


def commitment(row):
    return render(row, COMMITMENT)


def permit(row):
    return render(row, PERMIT)


def report(row):
    return render(row, REPORT)


def event(row):
    return render(row, EVENT)
