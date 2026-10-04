"""Facility derivation: licensure, licence ceiling, credential floor, posture."""

from common import iso, level_rank, parse_iso
from db import STORE
from services import calc

STATE_CREDENTIAL_RULES = {}


def facility_accreditations(facility_id):
    return STORE.where("Accreditation", lambda r: r.get("facility_id") == facility_id)


def _unexpired_granted(row, now):
    if row.get("status") != "GRANTED":
        return False
    expires = row.get("expires_at")
    if expires is None:
        return True
    return parse_iso(expires, "expires_at") > now


def unexpired_state_licenses(facility, now):
    return [
        row
        for row in facility_accreditations(facility["id"])
        if row.get("accreditation_class") == "STATE_LICENSE" and _unexpired_granted(row, now)
    ]


def has_accreditation_body(facility, now):
    return any(
        row.get("accreditation_class") == "ACCREDITATION_BODY" and row.get("status") == "GRANTED"
        for row in facility_accreditations(facility["id"])
    )


def has_revoked_accreditation_body(facility):
    return any(
        row.get("accreditation_class") == "ACCREDITATION_BODY" and row.get("status") == "REVOKED"
        for row in facility_accreditations(facility["id"])
    )


def has_recovery_house_license(facility, now):
    return any(
        row.get("accreditation_class") == "RECOVERY_HOUSE" and _unexpired_granted(row, now)
        for row in facility_accreditations(facility["id"])
    )


def recompute(facility, now=None):
    now = now or STORE.now()
    licenses = unexpired_state_licenses(facility, now)
    facility["licensed"] = len(licenses) > 0

    if licenses:
        best_level = "ASAM_1_0"
        for row in licenses:
            level_max = row.get("license_level_max") or "ASAM_1_0"
            if level_rank(level_max) > level_rank(best_level):
                best_level = level_max
        facility["as_level_max"] = best_level

        floor_tier = "TIER_4_INDEPENDENT"
        for row in licenses:
            tier_min = row.get("credential_tier_min")
            if tier_min is None:
                continue
            from common import tier_rank

            if tier_rank(tier_min) < tier_rank(floor_tier):
                floor_tier = tier_min
        facility["state_min_credential_tier"] = floor_tier
    else:
        facility["as_level_max"] = "ASAM_1_0"

    points = calc.compliance_risk_points(facility, now)
    facility["compliance_risk_points"] = points
    facility["facility_posture"] = calc.posture_from_points(points)
    facility["is_accepting_admissions"] = bool(
        facility["facility_posture"] != "FROZEN"
        and facility["licensed"]
        and has_accreditation_body(facility, now)
    )
    return facility


def recompute_housing_licensed(facility):
    now = STORE.now()
    licensed = has_recovery_house_license(facility, now)
    for house in STORE.where("RecoveryHousing", lambda r: r.get("facility_id") == facility["id"]):
        house["licensed"] = licensed
    return licensed


def expire_due_accreditations(facility, now):
    """Stage 3: a GRANTED accreditation past its expiry lapses."""
    changed = False
    for row in facility_accreditations(facility["id"]):
        if row.get("status") != "GRANTED":
            continue
        expires = row.get("expires_at")
        if expires is None:
            continue
        if parse_iso(expires, "expires_at") <= now:
            row["status"] = "EXPIRED"
            row["updated_at"] = iso(now)
            row["version"] = row.get("version", 1) + 1
            changed = True
    return changed