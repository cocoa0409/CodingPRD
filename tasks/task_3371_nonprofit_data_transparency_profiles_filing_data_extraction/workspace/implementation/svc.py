"""Serialization, derived-aggregate reconciliation and cascade helpers.

Every aggregate PRD 2.11 lists is maintained here: the reconciliation is
immediate and part of the response to the request that triggered it.
"""

from decimal import Decimal

import calc
import clock
import store
from errors import ApiError, ERR_INVALID_STATE

ACTIVE_SEAL = "ACTIVE"


# --- serialization -------------------------------------------------------

def ser_organization(org):
    return {
        "id": org["id"],
        "created_at": org["created_at"],
        "updated_at": org["updated_at"],
        "version": org["version"],
        "legal_name": org.get("legal_name"),
        "display_name": org.get("display_name"),
        "former_legal_names": list(org.get("former_legal_names") or []),
        "ein": org.get("ein"),
        "org_type": org.get("org_type"),
        "state_code": org.get("state_code"),
        "ntee_code": org.get("ntee_code"),
        "ntee_code_verified": org.get("ntee_code_verified", False),
        "mission_statement": org.get("mission_statement"),
        "profile_status": org.get("profile_status"),
        "verification_level": org.get("verification_level"),
        "verification_evidence_count": org.get("verification_evidence_count", 0),
        "transparency_seal_level": org.get("transparency_seal_level", "NONE"),
        "seal_expires_on": org.get("seal_expires_on"),
        "provisional_completeness_score": org.get("provisional_completeness_score", 0),
        "verified_completeness_score": org.get("verified_completeness_score", 0),
        "profile_completeness_score": org.get("profile_completeness_score", 0),
        "disclosure_pct": org.get("disclosure_pct", 0.0),
        "total_revenue_cents": org.get("total_revenue_cents", 0),
        "latest_filing_tax_year": org.get("latest_filing_tax_year"),
        "distinct_funder_count": org.get("distinct_funder_count", 0),
        "active_license_count": org.get("active_license_count", 0),
        "open_correction_count": org.get("open_correction_count", 0),
        "last_profile_editor_user_id": org.get("last_profile_editor_user_id"),
        "successor_organization_id": org.get("successor_organization_id"),
        "dissolution_date": org.get("dissolution_date"),
    }


def ser_program(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "organization_id": row.get("organization_id"),
        "program_name": row.get("program_name"),
        "subject_code": row.get("subject_code"),
        "population_served": row.get("population_served"),
        "disclosure_level": row.get("disclosure_level"),
        "is_verified": row.get("is_verified", False),
        "status": row.get("status"),
        "fiscal_year": row.get("fiscal_year"),
    }


def ser_filing(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "organization_id": row.get("organization_id"),
        "form_type": row.get("form_type"),
        "form_version_year": row.get("form_version_year"),
        "tax_year": row.get("tax_year"),
        "revision_number": row.get("revision_number"),
        "superseded_by_revision_number": row.get("superseded_by_revision_number"),
        "pre_supersede_status": row.get("pre_supersede_status"),
        "coverage_start": row.get("coverage_start"),
        "coverage_end": row.get("coverage_end"),
        "source": row.get("source"),
        "status": row.get("status"),
        "extracted_field_count": row.get("extracted_field_count", 0),
        "total_revenue_cents": row.get("total_revenue_cents", 0),
        "extraction_confidence_pct": row.get("extraction_confidence_pct"),
        "is_verified": row.get("is_verified", False),
    }


def ser_extracted_field(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "filing_id": row.get("filing_id"),
        "line_code": row.get("line_code"),
        "raw_value": row.get("raw_value"),
        "raw_format": row.get("raw_format"),
        "schedule_code": row.get("schedule_code"),
        "is_revenue_component": row.get("is_revenue_component", False),
        "normalized_value_cents": row.get("normalized_value_cents"),
        "normalization_status": row.get("normalization_status"),
        "is_verified": row.get("is_verified", False),
        "correction_count": row.get("correction_count", 0),
        "confidence_pct": row.get("confidence_pct"),
    }


def ser_leader(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "organization_id": row.get("organization_id"),
        "full_name": row.get("full_name"),
        "office_title": row.get("office_title"),
        "is_officer": row.get("is_officer", True),
        "is_independent": row.get("is_independent", False),
        "is_verified": row.get("is_verified", False),
        "disclosure_level": row.get("disclosure_level"),
        "compensation_cents": row.get("compensation_cents", 0),
        "service_start": row.get("service_start"),
        "service_end": row.get("service_end"),
        "status": row.get("status"),
    }


def ser_demographic(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "organization_id": row.get("organization_id"),
        "category": row.get("category"),
        "value_code": row.get("value_code"),
        "disclosure_level": row.get("disclosure_level"),
        "is_verified": row.get("is_verified", False),
        "fiscal_year": row.get("fiscal_year"),
    }


def ser_seal(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "organization_id": row.get("organization_id"),
        "level": row.get("level"),
        "disclosure_pct_at_award": row.get("disclosure_pct_at_award"),
        "awarded_on": row.get("awarded_on"),
        "expires_on": row.get("expires_on"),
        "renewal_window_opens_on": row.get("renewal_window_opens_on"),
        "renewal_attempt_count": row.get("renewal_attempt_count", 0),
        "last_renewal_fee_cents": row.get("last_renewal_fee_cents"),
        "status": row.get("status"),
    }


def ser_grant(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "recipient_organization_id": row.get("recipient_organization_id"),
        "funder_organization_id": row.get("funder_organization_id"),
        "funder_name_raw": row.get("funder_name_raw"),
        "recipient_name_raw": row.get("recipient_name_raw"),
        "recipient_ein": row.get("recipient_ein"),
        "amount_cents": row.get("amount_cents"),
        "fiscal_year": row.get("fiscal_year"),
        "subject_code": row.get("subject_code"),
        "taxonomy_source": row.get("taxonomy_source"),
        "match_score": row.get("match_score", 0),
        "recipient_match_status": row.get("recipient_match_status"),
        "status": row.get("status"),
    }


def ser_license(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "licensee_organization_id": row.get("licensee_organization_id"),
        "tier": row.get("tier"),
        "permitted_use": row.get("permitted_use"),
        "term_start": row.get("term_start"),
        "term_end": row.get("term_end"),
        "status": row.get("status"),
        "projected_annual_records": row.get("projected_annual_records", 0),
        "included_records": row.get("included_records"),
        "records_accessed": row.get("records_accessed", 0),
        "overage_records": row.get("overage_records", 0),
        "projected_annual_fee_cents": row.get("projected_annual_fee_cents"),
        "final_annual_fee_cents": row.get("final_annual_fee_cents"),
        "overage_flag": row.get("overage_flag", False),
        "auto_renew": row.get("auto_renew", False),
    }


def ser_usage_event(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "license_id": row.get("license_id"),
        "dataset_scope": row.get("dataset_scope"),
        "record_count": row.get("record_count"),
        "purpose_code": row.get("purpose_code"),
        "status": row.get("status"),
        "occurred_at": row.get("occurred_at"),
    }


def ser_correction(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "organization_id": row.get("organization_id"),
        "target_extracted_field_id": row.get("target_extracted_field_id"),
        "requested_value": row.get("requested_value"),
        "evidence_url": row.get("evidence_url"),
        "justification": row.get("justification"),
        "status": row.get("status"),
        "submitted_by_user_id": row.get("submitted_by_user_id"),
        "decided_by_user_id": row.get("decided_by_user_id"),
        "review_note": row.get("review_note"),
        "requested_at": row.get("requested_at"),
        "decided_at": row.get("decided_at"),
    }


def ser_identity_case(row):
    return {
        "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "version": row["version"],
        "subject_organization_id": row.get("subject_organization_id"),
        "surviving_organization_id": row.get("surviving_organization_id"),
        "case_type": row.get("case_type"),
        "new_legal_name": row.get("new_legal_name"),
        "effective_date": row.get("effective_date"),
        "status": row.get("status"),
        "resolution_note": row.get("resolution_note"),
        "reassigned_grant_count": row.get("reassigned_grant_count", 0),
        "finalized_at": row.get("finalized_at"),
    }


# --- row lookups ---------------------------------------------------------

def get_organization(org_id):
    row = store.find("organizations", org_id)
    if row is None:
        raise ApiError("ERR_ORGANIZATION_NOT_FOUND", "No organization exists for id '%s'." % org_id)
    return row


def get_filing(filing_id):
    row = store.find("filings", filing_id)
    if row is None:
        raise ApiError("ERR_FILING_NOT_FOUND", "No filing exists for id '%s'." % filing_id)
    return row


def get_extracted_field(field_id):
    row = store.find("extracted_fields", field_id)
    if row is None:
        raise ApiError("ERR_EXTRACTED_FIELD_NOT_FOUND",
                       "No extracted field exists for id '%s'." % field_id)
    return row


def get_license(license_id):
    row = store.find("licenses", license_id)
    if row is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND", "No license exists for id '%s'." % license_id)
    return row


def get_usage_event(event_id):
    row = store.find("usage_events", event_id)
    if row is None:
        raise ApiError("ERR_USAGE_EVENT_NOT_FOUND",
                       "No usage event exists for id '%s'." % event_id)
    return row


def get_seal(seal_id):
    row = store.find("seals", seal_id)
    if row is None:
        raise ApiError("ERR_SEAL_NOT_FOUND", "No seal exists for id '%s'." % seal_id)
    return row


def get_grant(grant_id):
    row = store.find("grants", grant_id)
    if row is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", "No grant exists for id '%s'." % grant_id)
    return row


def get_correction(correction_id):
    row = store.find("correction_requests", correction_id)
    if row is None:
        raise ApiError("ERR_CORRECTION_REQUEST_NOT_FOUND",
                       "No correction request exists for id '%s'." % correction_id)
    return row


def get_identity_case(case_id):
    row = store.find("identity_cases", case_id)
    if row is None:
        raise ApiError("ERR_IDENTITY_CASE_NOT_FOUND",
                       "No identity case exists for id '%s'." % case_id)
    return row


# --- child collections ---------------------------------------------------

def org_programs(org):
    return store.where("programs", organization_id=org["id"])


def org_filings(org):
    return store.where("filings", organization_id=org["id"])


def org_leaders(org):
    return store.where("leadership_members", organization_id=org["id"])


def org_demographics(org):
    return store.where("demographic_records", organization_id=org["id"])


def org_seals(org):
    return store.where("seals", organization_id=org["id"])


def org_grants(org):
    return [g for g in store.rows("grants")
            if g.get("recipient_organization_id") == org["id"]
            or g.get("funder_organization_id") == org["id"]]


def active_seal(org):
    for seal in org_seals(org):
        if seal.get("status") == ACTIVE_SEAL:
            return seal
    return None


# --- aggregate reconciliation -------------------------------------------

def recompute_scores(org):
    programs = org_programs(org)
    filings = org_filings(org)
    leaders = org_leaders(org)
    demographics = org_demographics(org)
    provisional = calc.provisional_completeness_score(org, programs, filings, leaders, demographics)
    verified = calc.verified_completeness_score(org, programs, filings, leaders, demographics)
    org["provisional_completeness_score"] = provisional
    org["verified_completeness_score"] = verified
    org["profile_completeness_score"] = calc.published_completeness_score(org, provisional, verified)
    return org["profile_completeness_score"]


def recompute_disclosure(org):
    pct = calc.disclosure_pct(
        org,
        org_programs(org),
        org_filings(org),
        org_leaders(org),
        org_demographics(org),
    )
    org["disclosure_pct"] = float(pct)
    return pct


def recompute_revenue(org):
    included = [
        f for f in org_filings(org)
        if f.get("status") == "NORMALIZED" and f.get("superseded_by_revision_number") is None
    ]
    org["total_revenue_cents"] = sum(f.get("total_revenue_cents") or 0 for f in included)
    if included:
        org["latest_filing_tax_year"] = max(f.get("tax_year") for f in included)
    else:
        org["latest_filing_tax_year"] = None
    return org["total_revenue_cents"]


def recompute_counters(org):
    funders = set()
    for grant in store.where("grants", recipient_organization_id=org["id"]):
        if grant.get("status") == "RECORDED":
            funders.add(grant.get("funder_organization_id"))
    org["distinct_funder_count"] = len(funders)

    org["active_license_count"] = len([
        lic for lic in store.where("licenses", licensee_organization_id=org["id"])
        if lic.get("status") == "ACTIVE"
    ])

    org["open_correction_count"] = len([
        req for req in store.where("correction_requests", organization_id=org["id"])
        if req.get("status") in ("SUBMITTED", "UNDER_REVIEW")
    ])
    return org["open_correction_count"]


def recompute_seal_mirror(org):
    seal = active_seal(org)
    if seal is None:
        org["transparency_seal_level"] = "NONE"
        org["seal_expires_on"] = None
    else:
        org["transparency_seal_level"] = seal.get("level")
        org["seal_expires_on"] = seal.get("expires_on")
    return seal


def recompute_org(org, parts=("scores", "disclosure", "revenue", "counters", "seal")):
    if "scores" in parts:
        recompute_scores(org)
    if "disclosure" in parts:
        recompute_disclosure(org)
    if "revenue" in parts:
        recompute_revenue(org)
    if "counters" in parts:
        recompute_counters(org)
    if "seal" in parts:
        recompute_seal_mirror(org)
    return org


# --- filing aggregates ---------------------------------------------------

def recompute_filing_totals(filing):
    """Per-field rounding first, then an exact integer sum (PRD 3.5)."""
    total = 0
    for field in store.where("extracted_fields", filing_id=filing["id"]):
        if field.get("is_revenue_component") is not True:
            continue
        if field.get("normalization_status") not in ("NORMALIZED", "CORRECTED"):
            continue
        if field.get("normalized_value_cents") is None:
            cents = calc.normalize_cents(field.get("raw_value"), field.get("raw_format"))
            if cents is None:
                continue
            field["normalized_value_cents"] = cents
        total += field["normalized_value_cents"]
    filing["total_revenue_cents"] = total
    return total


def refresh_filing_extraction(filing):
    fields = store.where("extracted_fields", filing_id=filing["id"])
    filing["extracted_field_count"] = len(fields)
    filing["extraction_confidence_pct"] = calc.mean_confidence(
        [f["confidence_pct"] for f in fields if f.get("confidence_pct") is not None]
    )
    return filing


def refresh_filing_verified(filing):
    fields = store.where("extracted_fields", filing_id=filing["id"])
    confidence = filing.get("extraction_confidence_pct")
    filing["is_verified"] = bool(
        confidence is not None
        and Decimal(str(confidence)) >= Decimal("90.0")
        and (filing.get("extracted_field_count") or 0) >= 1
        and not any(f.get("normalization_status") == "CONFLICT" for f in fields)
    )
    return filing["is_verified"]


# --- cascades ------------------------------------------------------------

def revoke_seal(seal, org):
    seal["status"] = "REVOKED"
    store.touch(seal)
    org["transparency_seal_level"] = "NONE"
    org["seal_expires_on"] = None
    store.touch(org)


def lapse_seal(seal, org, bump_org=True):
    seal["status"] = "LAPSED"
    store.touch(seal)
    org["transparency_seal_level"] = "NONE"
    org["seal_expires_on"] = None
    if bump_org:
        store.touch(org)


def apply_seal_floor_cascade(org):
    """PRD 3.7: a disclosure_pct below the ACTIVE seal's floor revokes it."""
    seal = active_seal(org)
    if seal is None:
        return False
    floor = calc.SEAL_DISCLOSURE_FLOOR.get(seal.get("level"))
    if floor is None:
        return False
    pct = Decimal(str(org.get("disclosure_pct") or 0))
    if pct < floor:
        revoke_seal(seal, org)
        return True
    return False


def apply_profile_floor_cascade(org):
    """PRD 3.5: profile_completeness_score below 50 revokes an ACTIVE seal."""
    seal = active_seal(org)
    if seal is None:
        return False
    if (org.get("profile_completeness_score") or 0) < 50:
        revoke_seal(seal, org)
        return True
    return False


def revoke_active_seals(org, bump_org=True):
    """Revoke every ACTIVE seal of the organization (suspension / identity)."""
    revoked = 0
    for seal in org_seals(org):
        if seal.get("status") == ACTIVE_SEAL:
            seal["status"] = "REVOKED"
            store.touch(seal)
            revoked += 1
    if revoked:
        org["transparency_seal_level"] = "NONE"
        org["seal_expires_on"] = None
    return revoked


def maybe_suspend(org):
    """PRD 2.6 / 3.3: open_correction_count reaching 3 suspends the profile."""
    if org.get("profile_status") != "ACTIVE":
        return False
    if (org.get("open_correction_count") or 0) < 3:
        return False
    org["profile_status"] = "SUSPENDED"
    revoke_active_seals(org)
    store.touch(org)
    return True


def expire_license(license_row):
    license_row["status"] = "EXPIRED"
    store.touch(license_row)
    licensee = store.find("organizations", license_row.get("licensee_organization_id"))
    if licensee is not None:
        recompute_counters(licensee)
    return license_row


def ensure_org_in_standing(org, allowed=("DRAFT", "ACTIVE")):
    if org.get("profile_status") not in allowed:
        raise ApiError(
            "ERR_ORG_NOT_IN_GOOD_STANDING",
            "Organization '%s' is not in good standing." % org["id"],
        )


def ensure_actor_is_editor(acting_user_id, org):
    if acting_user_id == org.get("last_profile_editor_user_id"):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The verifying user must differ from the last profile editor.",
        )


# --- logical-clock re-evaluation ----------------------------------------

def apply_clock_effects():
    """Re-evaluate every date-sensitive rule against the new instant (PRD 2.4)."""
    now = clock.now()
    for seal in store.rows("seals"):
        if seal.get("status") != ACTIVE_SEAL:
            continue
        expires_on = clock.parse_dt(seal.get("expires_on"))
        if expires_on is None:
            continue
        lapse_at = clock.add_days(expires_on, 90)
        if now > lapse_at:
            org = store.find("organizations", seal.get("organization_id"))
            if org is not None:
                lapse_seal(seal, org, bump_org=False)
            else:
                seal["status"] = "LAPSED"
                store.touch(seal)
    for license_row in store.rows("licenses"):
        if license_row.get("status") != "ACTIVE":
            continue
        term_end = clock.parse_dt(license_row.get("term_end"))
        if term_end is None:
            continue
        if now >= term_end:
            expire_license(license_row)
    for org in store.rows("organizations"):
        recompute_seal_mirror(org)


def require_transition(condition, message):
    if not condition:
        raise ApiError(ERR_INVALID_STATE, message)
