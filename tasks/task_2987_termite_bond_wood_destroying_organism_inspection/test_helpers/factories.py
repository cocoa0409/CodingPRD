"""Payload factories.

Every factory returns a valid request body and accepts ``**overrides`` so a
test can vary exactly the field under examination.  Money fields are JSON
numbers, instants are full RFC 3339 UTC timestamps ending in ``Z``, and
calendar dates are ``YYYY-MM-DD``.
"""

import itertools

from .constants import (
    ACTIVITY_NONE,
    CATEGORY_TERMITE_APPLICATOR,
    CATEGORY_WDO_INSPECTOR,
    CLAIM_TYPE_REPAIR,
    CONDUCIVE_NONE,
    CONDUCIVE_WOOD_TO_GROUND,
    CONSTRUCTION_SLAB,
    DECISION_APPROVE_REPAIR,
    FINDING_CONDUCIVE_CONDITION,
    FINDING_DAMAGE,
    FINDING_PREVIOUS_TREATMENT_EVIDENCE,
    METHOD_BAIT_STATION,
    METHOD_FUMIGATION,
    METHOD_LIQUID_BARRIER,
    ORGANISM_NONE,
    PRODUCT_FIPRO_9,
    PRODUCT_HEXA_BAIT_2,
    PRODUCT_SULFURYL_F,
    PURPOSE_INITIAL,
    PURPOSE_REAL_ESTATE,
    PURPOSE_REINSTATEMENT,
    PURPOSE_RENEWAL,
    STATE_FORM_MAP,
    TIER_REPAIR_AND_RETREAT,
)

_license_counter = itertools.count(10001)


def next_license_number(state_prefix="FL"):
    """A fresh licence number: two uppercase letters, a hyphen, five digits."""
    return "%s-%05d" % (state_prefix, next(_license_counter) % 100000)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc, **overrides):
    """Body for the logical-clock setter."""
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------


def property_payload(**overrides):
    """A registrable structure: FL slab, 2000 sqft, 180 linear feet."""
    payload = {
        "address_line1": "118 Sabal Palm Way",
        "state_code": "FL",
        "construction_type": CONSTRUCTION_SLAB,
        "square_footage": 2000,
        "linear_footage": 180,
        "year_built": 1995,
    }
    payload.update(overrides)
    return payload


def crawlspace_property_payload(**overrides):
    """A GA crawlspace structure, 1800 sqft, 175 linear feet."""
    defaults = {
        "address_line1": "44 Peachtree Ridge",
        "state_code": "GA",
        "construction_type": "CRAWLSPACE",
        "square_footage": 1800,
        "linear_footage": 175,
        "year_built": 1988,
        "crawl_clearance_inches": 22,
    }
    defaults.update(overrides)
    return property_payload(**defaults)


def basement_property_payload(**overrides):
    """A TX basement structure."""
    defaults = {
        "address_line1": "9 Cedar Hollow",
        "state_code": "TX",
        "construction_type": "BASEMENT",
        "square_footage": 2400,
        "linear_footage": 200,
        "year_built": 1979,
    }
    defaults.update(overrides)
    return property_payload(**defaults)


# ---------------------------------------------------------------------------
# Inspectors
# ---------------------------------------------------------------------------


def inspector_payload(**overrides):
    """A WDO inspector plus termite applicator, licensed in FL, expiring 2029-06-30."""
    payload = {
        "full_name": "Dana Whitfield",
        "license_number": next_license_number("FL"),
        "license_state": "FL",
        "license_categories": [CATEGORY_WDO_INSPECTOR, CATEGORY_TERMITE_APPLICATOR],
        "license_expires_on": "2029-06-30",
    }
    payload.update(overrides)
    return payload


def wdo_only_inspector_payload(**overrides):
    """An inspector holding only the WDO endorsement."""
    defaults = {
        "full_name": "Marcus Lindell",
        "license_categories": [CATEGORY_WDO_INSPECTOR],
    }
    defaults.update(overrides)
    return inspector_payload(**defaults)


def applicator_only_inspector_payload(**overrides):
    """A licensee holding only the termite applicator endorsement."""
    defaults = {
        "full_name": "Rosa Ibarra",
        "license_categories": [CATEGORY_TERMITE_APPLICATOR],
    }
    defaults.update(overrides)
    return inspector_payload(**defaults)


def fumigation_inspector_payload(**overrides):
    """A licensee certified for fumigation with the endorsement flag set."""
    defaults = {
        "full_name": "Teodor Vance",
        "license_categories": [
            CATEGORY_WDO_INSPECTOR,
            CATEGORY_TERMITE_APPLICATOR,
            "FUMIGATION_CERTIFIED",
        ],
        "fumigation_endorsement": True,
    }
    defaults.update(overrides)
    return inspector_payload(**defaults)


def license_status_payload(status, **overrides):
    """Body for a licence-status change."""
    payload = {"status": status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Graphs and notations
# ---------------------------------------------------------------------------


def inspection_payload(property_id, inspector_id, **overrides):
    """An INITIAL graph occupying 2026-08-01T09:00Z to 2026-08-01T12:00Z."""
    payload = {
        "property_id": property_id,
        "inspector_id": inspector_id,
        "purpose": PURPOSE_INITIAL,
        "scheduled_start_at": "2026-08-01T09:00:00Z",
        "scheduled_end_at": "2026-08-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def renewal_inspection_payload(
    property_id, inspector_id, supersedes_inspection_id, **overrides
):
    """A RENEWAL graph, which must name the graph it replaces."""
    defaults = {
        "purpose": PURPOSE_RENEWAL,
        "supersedes_inspection_id": supersedes_inspection_id,
    }
    defaults.update(overrides)
    return inspection_payload(property_id, inspector_id, **defaults)


def reinstatement_inspection_payload(
    property_id, inspector_id, supersedes_inspection_id, **overrides
):
    """A REINSTATEMENT graph, which must name the graph it replaces."""
    defaults = {
        "purpose": PURPOSE_REINSTATEMENT,
        "supersedes_inspection_id": supersedes_inspection_id,
    }
    defaults.update(overrides)
    return inspection_payload(property_id, inspector_id, **defaults)


def real_estate_inspection_payload(
    property_id, inspector_id, closing_date="2026-08-20", **overrides
):
    """A REAL_ESTATE graph, which must carry a closing_date."""
    defaults = {"purpose": PURPOSE_REAL_ESTATE, "closing_date": closing_date}
    defaults.update(overrides)
    return inspection_payload(property_id, inspector_id, **defaults)


def finding_payload(finding_type, grid_ref, **overrides):
    """A notation of the requested type, with the pairings PRD 2.6 demands."""
    payload = {"finding_type": finding_type, "grid_ref": grid_ref}
    if finding_type == FINDING_CONDUCIVE_CONDITION:
        payload["conducive_code"] = CONDUCIVE_WOOD_TO_GROUND
    elif finding_type == FINDING_DAMAGE:
        payload["damage_estimate_usd"] = 1500.00
        payload["pre_existing"] = False
    elif finding_type == "ACTIVE_INFESTATION":
        payload["organism"] = "SUBTERRANEAN_TERMITE"
    payload.update(overrides)
    return payload


def conducive_finding_payload(grid_ref, conducive_code, **overrides):
    """A CONDUCIVE_CONDITION notation carrying a real conducive code."""
    defaults = {"conducive_code": conducive_code}
    defaults.update(overrides)
    return finding_payload(FINDING_CONDUCIVE_CONDITION, grid_ref, **defaults)


def damage_finding_payload(
    grid_ref, damage_estimate_usd, pre_existing=False, severity=None, **overrides
):
    """A DAMAGE notation: estimate strictly above zero, pre_existing supplied."""
    defaults = {
        "damage_estimate_usd": damage_estimate_usd,
        "pre_existing": pre_existing,
    }
    if severity is not None:
        defaults["severity"] = severity
    defaults.update(overrides)
    return finding_payload(FINDING_DAMAGE, grid_ref, **defaults)


def infestation_finding_payload(
    grid_ref, organism="SUBTERRANEAN_TERMITE", **overrides
):
    """An ACTIVE_INFESTATION notation, whose organism may not be NONE."""
    defaults = {"organism": organism}
    defaults.update(overrides)
    return finding_payload("ACTIVE_INFESTATION", grid_ref, **defaults)


def evidence_finding_payload(grid_ref, **overrides):
    """A PREVIOUS_TREATMENT_EVIDENCE notation: no code, no estimate, no flag."""
    payload = {
        "finding_type": FINDING_PREVIOUS_TREATMENT_EVIDENCE,
        "grid_ref": grid_ref,
        "organism": ORGANISM_NONE,
        "conducive_code": CONDUCIVE_NONE,
    }
    payload.update(overrides)
    return payload


def graph_complete_payload(**overrides):
    """Body for signing a graph."""
    payload = {}
    payload.update(overrides)
    return payload


def attested_graph_complete_payload(**overrides):
    """Signing a zero-notation graph requires the no-findings attestation."""
    defaults = {"no_findings_attested": True}
    defaults.update(overrides)
    return graph_complete_payload(**defaults)


# ---------------------------------------------------------------------------
# Treatment plans
# ---------------------------------------------------------------------------


def treatment_plan_payload(property_id, inspection_id, applicator_id, **overrides):
    """A LIQUID_BARRIER plan loaded with FIPRO_9."""
    payload = {
        "property_id": property_id,
        "inspection_id": inspection_id,
        "applicator_id": applicator_id,
        "method": METHOD_LIQUID_BARRIER,
        "chemical_product_code": PRODUCT_FIPRO_9,
    }
    payload.update(overrides)
    return payload


def bait_plan_payload(property_id, inspection_id, applicator_id, **overrides):
    """A BAIT_STATION plan, which only accepts HEXA_BAIT_2."""
    defaults = {
        "method": METHOD_BAIT_STATION,
        "chemical_product_code": PRODUCT_HEXA_BAIT_2,
    }
    defaults.update(overrides)
    return treatment_plan_payload(
        property_id, inspection_id, applicator_id, **defaults
    )


def fumigation_plan_payload(
    property_id,
    inspection_id,
    applicator_id,
    fumigation_start_at="2026-08-05T08:00:00Z",
    fumigation_reentry_at="2026-08-07T08:00:00Z",
    **overrides
):
    """A FUMIGATION plan, which requires all three fumigation inputs."""
    defaults = {
        "method": METHOD_FUMIGATION,
        "chemical_product_code": PRODUCT_SULFURYL_F,
        "fumigation_permit_number": "FUM-004417",
        "fumigation_start_at": fumigation_start_at,
        "fumigation_reentry_at": fumigation_reentry_at,
    }
    defaults.update(overrides)
    return treatment_plan_payload(
        property_id, inspection_id, applicator_id, **defaults
    )


def application_payload(expected_treatment_plan_version, **overrides):
    """A pesticide application; gallons and concentration are JSON numbers."""
    payload = {
        "product_epa_number": "432-1471",
        "gallons_applied": 95.00,
        "concentration_pct": 0.10,
        "expected_treatment_plan_version": expected_treatment_plan_version,
    }
    payload.update(overrides)
    return payload


def minimal_application_payload(expected_treatment_plan_version, **overrides):
    """The smallest lawful discharge: 0.10 gallons, the declared range floor."""
    defaults = {"gallons_applied": 0.10}
    defaults.update(overrides)
    return application_payload(expected_treatment_plan_version, **defaults)


# ---------------------------------------------------------------------------
# Bait station services
# ---------------------------------------------------------------------------


def station_service_payload(activity_level=ACTIVITY_NONE, **overrides):
    """A station visit recording the activity found in the bait matrix."""
    payload = {"activity_level": activity_level}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bonds, renewals, reinstatement
# ---------------------------------------------------------------------------


def bond_payload(property_id, treatment_plan_id, **overrides):
    """A REPAIR_AND_RETREAT bond with no conducive waivers."""
    payload = {
        "property_id": property_id,
        "treatment_plan_id": treatment_plan_id,
        "coverage_tier": TIER_REPAIR_AND_RETREAT,
    }
    payload.update(overrides)
    return payload


def renewal_payload(**overrides):
    """Body for opening a renewal invoice."""
    payload = {}
    payload.update(overrides)
    return payload


def renewal_completion_payload(inspection_id, amount_usd, **overrides):
    """Body for completing a renewal invoice; amount_usd is a JSON number."""
    payload = {"inspection_id": inspection_id, "amount_usd": amount_usd}
    payload.update(overrides)
    return payload


def reinstatement_payload(reinstatement_inspection_id, amount_usd, **overrides):
    """Body for reinstating a lapsed bond; amount_usd is a JSON number."""
    payload = {
        "reinstatement_inspection_id": reinstatement_inspection_id,
        "amount_usd": amount_usd,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Statutory reports
# ---------------------------------------------------------------------------


def wdo_report_payload(inspection_id, state_code="FL", **overrides):
    """A statutory report on the form the structure's state mandates."""
    payload = {
        "inspection_id": inspection_id,
        "form_code": STATE_FORM_MAP[state_code],
    }
    payload.update(overrides)
    return payload


def amendment_payload(amendment_reason_code="CLERICAL_CORRECTION", **overrides):
    """Body for amending an issued report."""
    payload = {"amendment_reason_code": amendment_reason_code}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Damage claims
# ---------------------------------------------------------------------------


def damage_claim_payload(bond_id, expected_bond_version, claimed_damage_usd, **overrides):
    """A REPAIR claim; the damage amount is a JSON number."""
    payload = {
        "bond_id": bond_id,
        "claim_type": CLAIM_TYPE_REPAIR,
        "claimed_damage_usd": claimed_damage_usd,
        "expected_bond_version": expected_bond_version,
    }
    payload.update(overrides)
    return payload


def verification_payload(verifying_inspection_id, **overrides):
    """Body for attaching a verifying graph to a claim."""
    payload = {"verifying_inspection_id": verifying_inspection_id}
    payload.update(overrides)
    return payload


def adjudication_payload(decision=DECISION_APPROVE_REPAIR, **overrides):
    """Body for an adjudication decision."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def denial_payload(denial_reason_code="NO_ELIGIBLE_DAMAGE", **overrides):
    """A DENY decision, which must carry a denial reason code."""
    defaults = {"decision": "DENY", "denial_reason_code": denial_reason_code}
    defaults.update(overrides)
    return adjudication_payload(**defaults)
