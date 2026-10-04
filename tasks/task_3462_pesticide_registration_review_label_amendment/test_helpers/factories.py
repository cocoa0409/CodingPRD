"""Payload factories — one per entity, input fields only.

Factories build request bodies; they never call the API (that is what
fixtures.py does through the ApiClient). ``**overrides`` always wins, so a
test can perturb exactly one field.
"""
import itertools

_COUNTER = itertools.count(1)


def _seq() -> int:
    return next(_COUNTER)


# --- Active ingredients ------------------------------------------------------
def make_active_ingredient_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "common_name": f"nominex-{n}",
        "cas_number": f"100-{n:04d}-1",
        "tox_category": "III",
        "reference_dose_mg_kg_day": 0.05,
        "aquatic_lc50_ppm": 100.0,
    }
    defaults.update(overrides)
    return defaults


# --- Products ------------------------------------------------------------------
def make_product_payload(active_ingredient_id: str, **overrides) -> dict:
    defaults = {
        "product_name": f"Nominex {_seq()}G",
        "active_ingredient_id": active_ingredient_id,
        "formulation_type": "GRANULAR",
    }
    defaults.update(overrides)
    return defaults


# --- Use-site objects (application proposed_use_sites and NEW_USE payloads) ----
def make_use_site_object(**overrides) -> dict:
    """The seven-field use-site object (PRD §3.2). Defaults are deliberately
    tame: a 1.0 lbs/acre GROUND site keeps occupational and ecological
    quotients far below their levels of concern for a 0.05 rfd / 100 lc50
    active ingredient."""
    defaults = {
        "site_code": "CORN",
        "pest_code": "ARMYWORM",
        "max_application_rate_lbs_acre": 1.0,
        "max_applications_per_season": 2,
        "preharvest_interval_days": 7,
        "application_method": "GROUND",
        "restricted_entry_interval_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def make_non_food_use_site_object(**overrides) -> dict:
    defaults = make_use_site_object(
        site_code="TURF", pest_code="GRUB",
        max_application_rate_lbs_acre=1.0, preharvest_interval_days=0)
    defaults.update(overrides)
    return defaults


# --- Registration applications ---------------------------------------------------
def make_application_payload(product_id: str, use_pattern: str = "NON_FOOD_USE",
                             **overrides) -> dict:
    if use_pattern == "NON_FOOD_USE":
        default_sites = [make_non_food_use_site_object()]
    else:
        default_sites = [make_use_site_object()]
    defaults = {
        "product_id": product_id,
        "use_pattern": use_pattern,
        "requested_classification": "GENERAL_USE",
        "proposed_use_sites": default_sites,
    }
    defaults.update(overrides)
    return defaults


def make_submit_payload(use_pattern: str, **overrides) -> dict:
    """First-submit body carrying the exact filing fee for the use pattern."""
    from .constants import APPLICATION_FEE_CENTS
    defaults = {"payment_cents": APPLICATION_FEE_CENTS[use_pattern]}
    defaults.update(overrides)
    return defaults


def make_application_decision_payload(decision: str, **overrides) -> dict:
    """decision is APPROVE | DENY | DEFICIENCY; APPROVE also needs
    final_classification (pass final_classification=...)."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# --- Study submissions -----------------------------------------------------------
def make_study_payload(application_id=None, data_call_in_id=None,
                       study_type="EFFICACY", **overrides) -> dict:
    """Exactly one parent (application_id XOR data_call_in_id). For
    RESIDUE_CHEMISTRY pass commodity_code and field_trial_residue_ppm via
    overrides (or use make_residue_study_payload)."""
    assert (application_id is None) != (data_call_in_id is None), (
        "exactly one of application_id / data_call_in_id")
    defaults = {
        "study_type": study_type,
        "guideline_reference": f"OCSPP 810.{_seq():04d}",
    }
    if application_id is not None:
        defaults["application_id"] = application_id
    if data_call_in_id is not None:
        defaults["data_call_in_id"] = data_call_in_id
    if study_type == "RESIDUE_CHEMISTRY":
        defaults.setdefault("commodity_code", "CORN")
        defaults.setdefault("field_trial_residue_ppm", 0.02)
    defaults.update(overrides)
    return defaults


def make_residue_study_payload(application_id=None, data_call_in_id=None,
                               commodity_code="CORN", field_trial_residue_ppm=0.02,
                               **overrides) -> dict:
    return make_study_payload(
        application_id=application_id, data_call_in_id=data_call_in_id,
        study_type="RESIDUE_CHEMISTRY", commodity_code=commodity_code,
        field_trial_residue_ppm=field_trial_residue_ppm, **overrides)


def make_study_decision_payload(decision: str, **overrides) -> dict:
    """decision is ACCEPT | REJECT."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# --- Risk assessments --------------------------------------------------------------
def make_risk_assessment_payload(application_id: str, tier: str = "SCREENING",
                                 **overrides) -> dict:
    defaults = {"application_id": application_id, "tier": tier}
    if tier == "REFINED":
        defaults.setdefault("pct_crop_treated", 0.5)
    defaults.update(overrides)
    return defaults


# --- Tolerances ----------------------------------------------------------------------
def make_tolerance_payload(product_id: str, commodity_code: str = "CORN",
                           tolerance_ppm: float = 0.05, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "commodity_code": commodity_code,
        "tolerance_ppm": tolerance_ppm,
    }
    defaults.update(overrides)
    return defaults


# --- Label amendments ---------------------------------------------------------
def make_new_use_payload(use_site=None, commodity_code=None, tolerance_ppm=None,
                         **overrides) -> dict:
    """NEW_USE change set; commodity_code/tolerance_ppm optional pair."""
    payload = {"use_site": use_site if use_site is not None else make_use_site_object(
        site_code="SOYBEAN", pest_code="APHID", max_application_rate_lbs_acre=1.5,
        preharvest_interval_days=14, restricted_entry_interval_hours=48)}
    if commodity_code is not None:
        payload["commodity_code"] = commodity_code
    if tolerance_ppm is not None:
        payload["tolerance_ppm"] = tolerance_ppm
    payload.update(overrides)
    return payload


def make_rate_change_payload(use_site_id: str, new_rate: float = 2.0,
                             **overrides) -> dict:
    payload = {
        "use_site_id": use_site_id,
        "new_max_application_rate_lbs_acre": new_rate,
    }
    payload.update(overrides)
    return payload


def make_method_change_payload(use_site_id: str, new_method: str = "AERIAL",
                               expedited=None, **overrides) -> dict:
    payload = {
        "use_site_id": use_site_id,
        "new_application_method": new_method,
    }
    if expedited is not None:
        payload["expedited"] = expedited
    payload.update(overrides)
    return payload


def make_amendment_payload(product_id: str, amendment_type: str, payload: dict,
                           expected_product_version: int, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "amendment_type": amendment_type,
        "payload": payload,
        "expected_product_version": expected_product_version,
    }
    defaults.update(overrides)
    return defaults


def make_amendment_decision_payload(decision: str, **overrides) -> dict:
    """decision is APPROVE | REJECT."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# --- Applicator certifications --------------------------------------------------
def make_certification_payload(state_code: str = "TX",
                               certified_until: str = "2030-01-01T00:00:00Z",
                               **overrides) -> dict:
    defaults = {
        "applicator_name": f"Applicator {_seq()}",
        "state_code": state_code,
        "category": "AGRICULTURAL_PEST_CONTROL",
        "certified_until": certified_until,
    }
    defaults.update(overrides)
    return defaults


def make_certification_renewal_payload(new_certified_until: str, **overrides) -> dict:
    defaults = {"new_certified_until": new_certified_until}
    defaults.update(overrides)
    return defaults


# --- Endangered-species bulletins -------------------------------------------------
def make_bulletin_payload(product_id: str, county_fips: str = "06037",
                          restriction_code: str = "SEASONAL_WINDOW",
                          window_start_month: int = 3, window_end_month: int = 8,
                          **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "county_fips": county_fips,
        "restriction_code": restriction_code,
        "window_start_month": window_start_month,
        "window_end_month": window_end_month,
        "consultation_reference": f"USFWS-BO-2026-{_seq():03d}",
    }
    if restriction_code == "RATE_CAP":
        defaults.setdefault("rate_cap_lbs_acre", 1.0)
    defaults.update(overrides)
    return defaults


# --- Registration review cases ------------------------------------------------------
def make_review_case_payload(product_id: str, opened_at: str,
                             due_at=None, **overrides) -> dict:
    defaults = {"product_id": product_id, "opened_at": opened_at}
    if due_at is not None:
        defaults["due_at"] = due_at
    defaults.update(overrides)
    return defaults


# --- Data call-ins ---------------------------------------------------------------------
def make_data_call_in_payload(review_case_id: str,
                              required_study_types=("TOXICOLOGY",),
                              response_deadline: str = "2027-02-09T00:00:00Z",
                              **overrides) -> dict:
    defaults = {
        "review_case_id": review_case_id,
        "required_study_types": list(required_study_types),
        "response_deadline": response_deadline,
    }
    defaults.update(overrides)
    return defaults


def make_dci_response_payload(study_submission_ids, **overrides) -> dict:
    defaults = {"study_submission_ids": list(study_submission_ids)}
    defaults.update(overrides)
    return defaults


# --- Cancellation / suspension proceedings ----------------------------------------------
def make_proceeding_payload(product_id: str, proceeding_type: str = "CANCELLATION",
                            reason: str = "RISK_FINDING", **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "proceeding_type": proceeding_type,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def make_issue_order_payload(stocks_method=None, authorized_units=None,
                             depletion_rate_units_per_month=None, **overrides) -> dict:
    """CANCELLATION orders need the stocks provision; SUSPENSION orders carry
    none of these fields (pass no arguments for a suspension order)."""
    payload = {}
    if stocks_method is not None:
        payload["stocks_method"] = stocks_method
    if authorized_units is not None:
        payload["existing_stocks_authorized_units"] = authorized_units
    if depletion_rate_units_per_month is not None:
        payload["depletion_rate_units_per_month"] = depletion_rate_units_per_month
    payload.update(overrides)
    return payload


def make_fixed_order_payload(units: int = 100, **overrides) -> dict:
    return make_issue_order_payload(
        stocks_method="FIXED", authorized_units=units, **overrides)


def make_depletion_order_payload(units: int, depletion_rate: int, **overrides) -> dict:
    return make_issue_order_payload(
        stocks_method="DEPLETION", authorized_units=units,
        depletion_rate_units_per_month=depletion_rate, **overrides)


def make_vacatur_payload(**overrides) -> dict:
    defaults = {"vacatur_reason": f"vacatur {_seq()}"}
    defaults.update(overrides)
    return defaults


def make_disposal_payload(units: int, method: str = "SALE", **overrides) -> dict:
    defaults = {"units": units, "method": method}
    defaults.update(overrides)
    return defaults


# --- State registrations ------------------------------------------------------------------
def make_state_registration_payload(product_id: str, state_code: str = "TX",
                                    **overrides) -> dict:
    defaults = {"product_id": product_id, "state_code": state_code}
    defaults.update(overrides)
    return defaults


def make_state_decision_payload(decision: str, **overrides) -> dict:
    """decision is GRANT | DENY; GRANT may carry additional_restrictions."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def make_renewal_payload(payment_cents: int, **overrides) -> dict:
    defaults = {"payment_cents": payment_cents}
    defaults.update(overrides)
    return defaults


# --- Logical clock --------------------------------------------------------------------------
def make_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
