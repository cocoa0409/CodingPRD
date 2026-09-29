"""Request payload builders.

Money is always an integer number of cents. Mass, temperature and pH are plain
JSON numbers. The ten fields the PRD declares as calendar dates carry a plain
``YYYY-MM-DD`` value with no time component; every other temporal field carries
a full ISO 8601 UTC instant.
"""

from .constants import (
    CAP_SOURCE_DEMAND,  # noqa: F401  (re-exported for symmetry with constants)
    CERT_FOOD_HANDLER,
    CERT_HACCP_RICE_ACIDIFICATION,
    FREEZE_MINUS20_7DAYS,
    HARVEST_WILD,
    MARKDOWN_POLICY_PRORATED,
    POS_CONNECTED,
    REVENUE_SHARE_GROSS_SALES,
    SEVERITY_MAJOR,
    SPECIES_TUNA_YELLOWFIN,
    VARIANCE_DECISION_APPROVE,
    VERIFY_OUTCOME_PASS,
)

# The canonical world is anchored on a single business day.
CANONICAL_CLOCK = "2026-08-03T11:00:00Z"
CANONICAL_BUSINESS_DATE = "2026-08-03"
CANONICAL_PERIOD_START = "2026-08-01"
CANONICAL_PERIOD_END = "2026-08-31"


def _merge(defaults: dict, overrides: dict) -> dict:
    payload = dict(defaults)
    payload.update(overrides)
    return payload


# --- Logical clock ----------------------------------------------------------
def clock_payload(current_utc: str = CANONICAL_CLOCK, **overrides) -> dict:
    """Body for setting the server's logical UTC clock."""
    return _merge({"current_utc": current_utc}, overrides)


# --- Host store -------------------------------------------------------------
def host_store_payload(**overrides) -> dict:
    """Body for registering a host store."""
    return _merge(
        {
            "name": "Northgate Market 418",
            "banner_chain": "Northgate",
            "store_number": "418",
            "state_code": "CA",
            "weekly_traffic_count": 63000,
            "sushi_space_sqft": 240,
            "refrigerated_case_linear_ft": 20.0,
            "refrigerated_case_capacity_packs": 400,
        },
        overrides,
    )


def pos_integration_payload(**overrides) -> dict:
    """Body for setting a host store's POS integration state."""
    return _merge(
        {"pos_integration_status": POS_CONNECTED, "pos_terminal_count": 6}, overrides
    )


def space_attestation_payload(**overrides) -> dict:
    """Body for a host store manager's space attestation."""
    return _merge(
        {
            "attested_sushi_space_sqft": 240,
            "attested_case_linear_ft": 20.0,
            "attested_on": "2026-08-01",
        },
        overrides,
    )


# --- License agreement ------------------------------------------------------
def license_agreement_payload(host_store_id: str, **overrides) -> dict:
    """Body for drafting a license agreement."""
    return _merge(
        {
            "host_store_id": host_store_id,
            "revenue_share_model": REVENUE_SHARE_GROSS_SALES,
            "markdown_policy": MARKDOWN_POLICY_PRORATED,
            "min_space_sqft_obligation": 220,
            "min_case_linear_ft_obligation": 18.0,
            "space_credit_cents_per_sqft": 1250,
            "effective_from": "2026-08-01",
            "effective_to": "2027-07-31",
        },
        overrides,
    )


def suspension_payload(**overrides) -> dict:
    """Body carrying a suspension reason."""
    return _merge({"suspension_reason": "HOST_CHAIN_REMODEL_PAUSE"}, overrides)


def termination_payload(**overrides) -> dict:
    """Body carrying a termination reason."""
    return _merge({"termination_reason": "HOST_CHAIN_EXIT"}, overrides)


# --- Chef and certifications ------------------------------------------------
def chef_payload(**overrides) -> dict:
    """Body for registering a chef candidate."""
    return _merge({"full_name": "Kenji Arai"}, overrides)


def training_payload(**overrides) -> dict:
    """Body for logging training hours against a chef."""
    return _merge({"hours": 30, "curriculum_code": "HS-CORE-24"}, overrides)


def certification_payload(**overrides) -> dict:
    """Body for issuing a certification to a chef."""
    return _merge(
        {
            "cert_type": CERT_FOOD_HANDLER,
            "exam_score": 92,
            "issued_at": "2026-08-01T00:00:00Z",
            "valid_days": 365,
        },
        overrides,
    )


def food_handler_certification_payload(**overrides) -> dict:
    """Body for issuing the mandatory food handler certification."""
    return _merge(
        certification_payload(), _merge({"cert_type": CERT_FOOD_HANDLER, "exam_score": 92}, overrides)
    )


def haccp_certification_payload(**overrides) -> dict:
    """Body for issuing the mandatory HACCP rice acidification certification."""
    return _merge(
        certification_payload(),
        _merge(
            {"cert_type": CERT_HACCP_RICE_ACIDIFICATION, "exam_score": 95}, overrides
        ),
    )


def revocation_payload(**overrides) -> dict:
    """Body carrying a certification revocation reason."""
    return _merge({"revocation_reason": "FALSIFIED_EXAM_RECORD"}, overrides)


def placement_payload(kiosk_id: str, as_lead_chef: bool = True, **overrides) -> dict:
    """Body for placing a chef at a kiosk."""
    return _merge(
        {"assigned_kiosk_id": kiosk_id, "as_lead_chef": as_lead_chef}, overrides
    )


# --- Kiosk ------------------------------------------------------------------
def kiosk_payload(license_agreement_id: str, **overrides) -> dict:
    """Body for provisioning a kiosk."""
    return _merge(
        {
            "license_agreement_id": license_agreement_id,
            "kiosk_code": "K-418-A",
            "case_footprint_sqft": 230,
        },
        overrides,
    )


def commission_payload(**overrides) -> dict:
    """Body for commissioning a kiosk, carrying a calendar date."""
    return _merge({"commissioned_on": CANONICAL_BUSINESS_DATE}, overrides)


def decommission_payload(**overrides) -> dict:
    """Body carrying a decommission reason."""
    return _merge({"decommission_reason": "HOST_STORE_REMODEL"}, overrides)


# --- Production plan --------------------------------------------------------
def production_plan_payload(kiosk_id: str, expected_kiosk_version: int, **overrides) -> dict:
    """Body for creating a production plan, including the observed kiosk version."""
    return _merge(
        {
            "kiosk_id": kiosk_id,
            "production_date": CANONICAL_BUSINESS_DATE,
            "traffic_forecast": 9000,
            "expected_kiosk_version": expected_kiosk_version,
        },
        overrides,
    )


def plan_void_payload(**overrides) -> dict:
    """Body carrying a manual plan void reason."""
    return _merge({"void_reason": "HOST_STORE_POWER_OUTAGE"}, overrides)


# --- Rice batch -------------------------------------------------------------
def rice_batch_payload(production_plan_id: str, chef_id: str, **overrides) -> dict:
    """Body for starting a rice batch and opening its acidification hold window."""
    return _merge(
        {
            "production_plan_id": production_plan_id,
            "chef_id": chef_id,
            "rice_kg": 21.6,
            "vinegar_liters": 2.2,
            "hold_start_at": "2026-08-03T05:00:00Z",
            "hold_end_at": "2026-08-03T07:00:00Z",
        },
        overrides,
    )


def acidification_reading_payload(**overrides) -> dict:
    """Body recording a batch's measured pH and maximum hold temperature."""
    return _merge(
        {
            "measured_ph": 4.1,
            "ph_measured_at": "2026-08-03T07:00:00Z",
            "max_temp_c": 19.5,
        },
        overrides,
    )


def variance_request_payload(**overrides) -> dict:
    """Body filing HACCP variance documentation for a rice batch."""
    return _merge(
        {
            "documented_ph": 4.35,
            "documented_hold_minutes": 240,
            "corrective_narrative": "Re-acidified with a second vinegar addition and re-probed.",
        },
        overrides,
    )


def variance_decision_payload(**overrides) -> dict:
    """Body carrying the auditor's variance decision."""
    return _merge(
        {
            "decision": VARIANCE_DECISION_APPROVE,
            "review_note": "Documented pH and hold time are inside the documentable band.",
        },
        overrides,
    )


def variance_revocation_payload(**overrides) -> dict:
    """Body carrying the rationale for revoking an approved variance."""
    return _merge(
        {"revocation_rationale": "Second review found the probe out of calibration."},
        overrides,
    )


# --- Fish lot ---------------------------------------------------------------
def fish_lot_payload(kiosk_id: str, **overrides) -> dict:
    """Body for receiving a fish lot at a kiosk."""
    return _merge(
        {
            "kiosk_id": kiosk_id,
            "species": SPECIES_TUNA_YELLOWFIN,
            "supplier_code": "SUP-9931",
            "harvest_method": HARVEST_WILD,
            "net_weight_kg": 12.0,
            "received_at": "2026-08-03T06:30:00Z",
            "receiving_temp_c": 2.8,
        },
        overrides,
    )


def parasite_destruction_payload(attested_by_chef_id: str, **overrides) -> dict:
    """Body recording the freezing regime applied to a fish lot."""
    return _merge(
        {
            "destruction_method": FREEZE_MINUS20_7DAYS,
            "freeze_start_at": "2026-07-20T00:00:00Z",
            "freeze_end_at": "2026-07-27T00:00:00Z",
            "freeze_min_temp_c": -22.0,
            "attested_by_chef_id": attested_by_chef_id,
        },
        overrides,
    )


def cold_chain_reading_payload(recorded_at: str, temp_c: float, **overrides) -> dict:
    """Body appending one cold-chain temperature reading."""
    return _merge({"recorded_at": recorded_at, "temp_c": temp_c}, overrides)


def release_rationale_payload(**overrides) -> dict:
    """Body carrying the explicit rationale a quarantined lot needs to be released."""
    return _merge(
        {"release_rationale": "Breach traced to a probe fault; product core stayed cold."},
        overrides,
    )


def destruction_payload(**overrides) -> dict:
    """Body carrying a fish lot destruction rationale."""
    return _merge({"destruction_rationale": "Supplier recall on the harvest lot."}, overrides)


# --- Pack lot ---------------------------------------------------------------
def pack_lot_payload(rice_batch_id: str, fish_lot_id: str, **overrides) -> dict:
    """Body for building a pack lot from a rice batch and a fish lot."""
    return _merge(
        {
            "rice_batch_id": rice_batch_id,
            "fish_lot_id": fish_lot_id,
            "sku_code": "CALIF-8",
            "pack_count": 160,
            "list_price_cents": 900,
            "produced_at": "2026-08-03T08:00:00Z",
        },
        overrides,
    )


def discard_payload(reason: str, **overrides) -> dict:
    """Body carrying the reason a pack lot's unsold packs are discarded."""
    return _merge({"reason": reason}, overrides)


def pack_lot_void_payload(**overrides) -> dict:
    """Body carrying a pack lot void reason."""
    return _merge(
        {"void_reason": "Mislabelled allergen sleeve on the whole run"}, overrides
    )


# --- POS sales feed ---------------------------------------------------------
def pos_sales_feed_payload(host_store_id: str, **overrides) -> dict:
    """Body submitting a host store's daily POS extract."""
    return _merge(
        {
            "host_store_id": host_store_id,
            "business_date": CANONICAL_BUSINESS_DATE,
            "gross_sales_cents": 2400000,
            "markdown_sales_cents": 300000,
            "full_price_units": 100,
            "markdown_units": 40,
            "lines": [],
        },
        overrides,
    )


def feed_line(pack_lot_id: str, units_sold: int, was_markdown: bool = False) -> dict:
    """One per-pack-lot register line inside a POS feed."""
    return {
        "pack_lot_id": pack_lot_id,
        "units_sold": units_sold,
        "was_markdown": was_markdown,
    }


def feed_rejection_payload(**overrides) -> dict:
    """Body carrying a POS feed rejection reason."""
    return _merge({"rejection_reason": "Terminal export truncated mid-day"}, overrides)


# --- Settlement statement ---------------------------------------------------
def settlement_statement_payload(
    license_agreement_id: str, expected_license_agreement_version: int, **overrides
) -> dict:
    """Body drafting a settlement statement for an agreement period."""
    return _merge(
        {
            "license_agreement_id": license_agreement_id,
            "period_start": CANONICAL_PERIOD_START,
            "period_end": CANONICAL_PERIOD_END,
            "expected_license_agreement_version": expected_license_agreement_version,
        },
        overrides,
    )


def dispute_payload(**overrides) -> dict:
    """Body carrying a settlement dispute reason."""
    return _merge({"dispute_reason": "MARKDOWN_UNITS_DISAGREE"}, overrides)


def revision_payload(**overrides) -> dict:
    """Body carrying a settlement revision note."""
    return _merge(
        {"revision_note": "Recomputed after markdown reconciliation"}, overrides
    )


def payment_payload(paid_amount_cents: int, **overrides) -> dict:
    """Body recording a settlement payment; the amount is integer cents."""
    return _merge(
        {"paid_amount_cents": paid_amount_cents, "paid_at": "2026-08-03T10:00:00Z"},
        overrides,
    )


def settlement_void_payload(**overrides) -> dict:
    """Body carrying a settlement void reason."""
    return _merge(
        {"void_reason": "Feed re-extracted after a terminal clock fault"}, overrides
    )


# --- Food safety audit ------------------------------------------------------
def audit_payload(kiosk_id: str, **overrides) -> dict:
    """Body scheduling an audit of a kiosk, carrying a calendar date."""
    return _merge(
        {"kiosk_id": kiosk_id, "scheduled_for": CANONICAL_BUSINESS_DATE}, overrides
    )


def finding_payload(severity: str = SEVERITY_MAJOR, **overrides) -> dict:
    """Body recording one finding against an in-progress audit."""
    defaults = {
        "severity": severity,
        "finding_code": "FS-SANITISER-CONCENTRATION",
        "description": "Sanitiser bucket measured below the posted concentration.",
    }
    return _merge(defaults, overrides)


def correction_payload(**overrides) -> dict:
    """Body recording the corrective action taken against a finding."""
    return _merge(
        {"correction_note": "Bucket remade and concentration re-verified on shift."},
        overrides,
    )


def waiver_payload(**overrides) -> dict:
    """Body carrying the rationale for waiving a minor finding."""
    return _merge(
        {"waiver_rationale": "Cosmetic label wear with no product contact."}, overrides
    )


def verification_payload(outcome: str = VERIFY_OUTCOME_PASS, **overrides) -> dict:
    """Body carrying the reverification outcome and note."""
    return _merge(
        {
            "outcome": outcome,
            "verification_note": "Re-walked the line and reviewed the corrective evidence.",
        },
        overrides,
    )
