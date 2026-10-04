"""Payload factories and logical-clock-aware date arithmetic.

Every date a factory emits is a fixed literal anchored to the PRD §2.4 startup
clock (2026-09-01T00:00:00Z) or is computed from an explicit instant the test
set through the clock endpoint.  ``datetime.now()`` is never consulted: the
server evaluates every temporal rule against its own logical clock, so wall
time is meaningless to this suite.

Anniversary arithmetic follows PRD §2.9: a February 29 anchor observes its
anniversary on February 28 in non-leap target years.
"""

from datetime import datetime, timedelta, timezone

from . import constants as C


# ─── Clock-anchored default instants ─────────────────────────────────────────
# All reachable from the PRD §2.4 startup default 2026-09-01T00:00:00Z without
# any clock call, or via an explicit set_clock first.
STARTUP_CLOCK_UTC = C.STARTUP_CLOCK_UTC
# Cutoff giving records age exactly 25 at the startup clock (25th anniversary
# 2026-03-15 already reached by 2026-09-01); with the default lag of 20 years
# the transfer-lag anniversary (2021-03-15) has long elapsed.
DEFAULT_RECORDS_CUTOFF = "2001-03-15T00:00:00Z"
# A visit date comfortably inside the [clock, clock + 30 days] booking window
# at the startup clock.
DEFAULT_VISIT_DATE = "2026-09-10T00:00:00Z"
DEFAULT_TRANSFER_LAG_YEARS = 20
# Presidential-domain defaults (lag 12, cutoff 2009-01-20: lag anniversary
# 2021-01-20, records age 17 at startup).
PRESIDENTIAL_RECORDS_CUTOFF = "2009-01-20T00:00:00Z"
PRESIDENTIAL_TRANSFER_LAG_YEARS = 12


# ─── Instant arithmetic (logical-clock domain; inputs are ISO 8601 UTC) ──────
def parse_instant(iso):
    """Parse an ISO 8601 UTC instant ('...Z' or offset form) to datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def format_instant(dt):
    """Render a datetime as 'YYYY-MM-DDTHH:MM:SSZ' (whole seconds)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(iso, days):
    return format_instant(parse_instant(iso) + timedelta(days=days))


def add_hours(iso, hours):
    return format_instant(parse_instant(iso) + timedelta(hours=hours))


def add_seconds(iso, seconds):
    return format_instant(parse_instant(iso) + timedelta(seconds=seconds))


def add_years_anniversary(iso, years):
    """Shift an instant forward by whole years under PRD §2.9 anniversary
    arithmetic: Feb 29 anchors land on Feb 28 in non-leap target years."""
    dt = parse_instant(iso)
    try:
        shifted = dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in a non-leap target year.
        shifted = dt.replace(year=dt.year + years, month=2, day=28)
    return format_instant(shifted)


# ─── Metadata element sets ───────────────────────────────────────────────────
# The complete required-element lists a metadata submission must contain to
# land a transfer in VALIDATED.  Used by fixtures whenever a VALIDATED
# transfer is needed; individual elements may be dropped to probe DEFICIENT.
METADATA_ELEMENTS_BY_STANDARD = {
    "EAD_2002": ["title", "creator", "date_span", "extent"],
    "MODS_3_7": ["title", "origin", "date_span"],
    "PREMIS_3_0": ["object_id", "fixity", "format", "provenance"],
}


def metadata_elements_for(metadata_standard):
    """Full required-element list for the declared metadata standard."""
    return list(METADATA_ELEMENTS_BY_STANDARD[metadata_standard])


# ─── Agency ──────────────────────────────────────────────────────────────────
def agency_payload(agency_code="DOJ", name="Department of Justice", **overrides):
    payload = {"agency_code": agency_code, "name": name}
    payload.update(overrides)
    return payload


# ─── Records schedule ────────────────────────────────────────────────────────
def schedule_payload(
    agency_id,
    schedule_number="SCH-DOJ-001",
    title="Records Schedule",
    records_domain="FEDERAL",
    disposition="PERMANENT",
    transfer_lag_years=DEFAULT_TRANSFER_LAG_YEARS,
    classification_default="NONE",
    **overrides,
):
    """transfer_lag_years is required iff disposition is PERMANENT; pass
    transfer_lag_years=None for a TEMPORARY schedule to omit the field."""
    payload = {
        "agency_id": agency_id,
        "schedule_number": schedule_number,
        "title": title,
        "records_domain": records_domain,
        "disposition": disposition,
        "classification_default": classification_default,
    }
    if transfer_lag_years is not None:
        payload["transfer_lag_years"] = transfer_lag_years
    payload.update(overrides)
    return payload


def appraise_payload(appraisal_recommendation="APPROVE", **overrides):
    payload = {"appraisal_recommendation": appraisal_recommendation}
    payload.update(overrides)
    return payload


def decide_schedule_payload(decision="APPROVE", decision_note=None, **overrides):
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    payload.update(overrides)
    return payload


# ─── Transfer ────────────────────────────────────────────────────────────────
def transfer_payload(
    schedule_id,
    agency_id,
    transfer_method="PHYSICAL",
    metadata_standard=None,
    unit_count=50,
    records_cutoff_date=DEFAULT_RECORDS_CUTOFF,
    linear_feet=12.5,
    checksum_manifest="sha256:9f2c",
    **overrides,
):
    """Method/standard compatibility defaults: PHYSICAL pairs with EAD_2002
    (linear_feet), ELECTRONIC with PREMIS_3_0 (checksum_manifest).  The
    method-specific evidence field for the *other* method is omitted so the
    payload satisfies the PRD §3.2 requirement rules by default."""
    if metadata_standard is None:
        metadata_standard = "EAD_2002" if transfer_method == "PHYSICAL" else "PREMIS_3_0"
    payload = {
        "schedule_id": schedule_id,
        "agency_id": agency_id,
        "transfer_method": transfer_method,
        "metadata_standard": metadata_standard,
        "unit_count": unit_count,
        "records_cutoff_date": records_cutoff_date,
    }
    if transfer_method == "PHYSICAL":
        if linear_feet is not None:
            payload["linear_feet"] = linear_feet
    else:
        if checksum_manifest is not None:
            payload["checksum_manifest"] = checksum_manifest
    payload.update(overrides)
    return payload


def submit_metadata_payload(metadata_elements=None, metadata_standard=None, **overrides):
    """Element list for submit-metadata.  Pass explicit metadata_elements, or a
    metadata_standard to submit that standard's complete required set."""
    if metadata_elements is None:
        metadata_elements = metadata_elements_for(metadata_standard or "EAD_2002")
    payload = {"metadata_elements": list(metadata_elements)}
    payload.update(overrides)
    return payload


def accession_payload(receipt_note="received and verified", **overrides):
    payload = {"receipt_note": receipt_note}
    payload.update(overrides)
    return payload


# ─── Collection ──────────────────────────────────────────────────────────────
def description_payload(
    scope_note="case files",
    arrangement_note="alphabetical",
    container_list_summary="boxes 1-50",
    **overrides,
):
    payload = {
        "scope_note": scope_note,
        "arrangement_note": arrangement_note,
        "container_list_summary": container_list_summary,
    }
    payload.update(overrides)
    return payload


# ─── Declassification review / equity referral ───────────────────────────────
def declass_review_payload(
    collection_id,
    review_type,
    expected_collection_version,
    requester_researcher_id=None,
    justification=None,
    **overrides,
):
    """OCC-carrying review payload.  ``expected_collection_version`` is
    mandatory (PRD §2.7); MANDATORY reviews must also carry
    requester_researcher_id and a non-empty justification."""
    payload = {
        "collection_id": collection_id,
        "review_type": review_type,
        "expected_collection_version": expected_collection_version,
    }
    if requester_researcher_id is not None:
        payload["requester_researcher_id"] = requester_researcher_id
    if justification is not None:
        payload["justification"] = justification
    payload.update(overrides)
    return payload


def referrals_payload(agency_ids, **overrides):
    payload = {"agency_ids": list(agency_ids)}
    payload.update(overrides)
    return payload


def complete_review_payload(reviewer_assessment="DECLASSIFY", exemption_code=None, **overrides):
    payload = {"reviewer_assessment": reviewer_assessment}
    if exemption_code is not None:
        payload["exemption_code"] = exemption_code
    payload.update(overrides)
    return payload


def respond_referral_payload(decision="DECLASSIFY", exemption_code=None, **overrides):
    payload = {"decision": decision}
    if exemption_code is not None:
        payload["exemption_code"] = exemption_code
    payload.update(overrides)
    return payload


# ─── Researcher registration ─────────────────────────────────────────────────
def researcher_payload(
    full_name="Ada Research",
    email="ada@example.org",
    affiliation="ACADEMIC",
    id_document="DL-1001",
    **overrides,
):
    payload = {
        "full_name": full_name,
        "email": email,
        "affiliation": affiliation,
        "id_document": id_document,
    }
    payload.update(overrides)
    return payload


# ─── Pull request ────────────────────────────────────────────────────────────
def pull_request_payload(
    researcher_id,
    collection_id,
    unit_start=1,
    unit_end=5,
    visit_date=DEFAULT_VISIT_DATE,
    **overrides,
):
    payload = {
        "researcher_id": researcher_id,
        "collection_id": collection_id,
        "unit_start": unit_start,
        "unit_end": unit_end,
        "visit_date": visit_date,
    }
    payload.update(overrides)
    return payload


# ─── Reproduction request ────────────────────────────────────────────────────
def reproduction_payload(
    researcher_id,
    collection_id,
    page_count=10,
    format="DIGITAL_SCAN",
    rush=None,
    **overrides,
):
    """rush is omitted when None so the server-side default (false) applies;
    pass an explicit bool to pin it."""
    payload = {
        "researcher_id": researcher_id,
        "collection_id": collection_id,
        "page_count": page_count,
        "format": format,
    }
    if rush is not None:
        payload["rush"] = rush
    payload.update(overrides)
    return payload


def pay_payload(payment_reference="card-txn-1", **overrides):
    payload = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload


# ─── FOIA request ────────────────────────────────────────────────────────────
def foia_request_payload(
    researcher_id,
    collection_id,
    description_of_records="all records responsive to the request",
    **overrides,
):
    payload = {
        "researcher_id": researcher_id,
        "collection_id": collection_id,
        "description_of_records": description_of_records,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(decision="GRANT", claimed_exemptions=None, **overrides):
    """PARTIAL and DENY decisions require a non-empty claimed_exemptions
    subset of {B1, B3, B5}; GRANT claims none."""
    payload = {"decision": decision}
    if claimed_exemptions is not None:
        payload["claimed_exemptions"] = list(claimed_exemptions)
    payload.update(overrides)
    return payload


def appeal_payload(appeal_reason="public interest outweighs", **overrides):
    payload = {"appeal_reason": appeal_reason}
    payload.update(overrides)
    return payload


def decide_appeal_payload(appeal_decision="GRANT", **overrides):
    payload = {"appeal_decision": appeal_decision}
    payload.update(overrides)
    return payload


# ─── Presidential restriction ────────────────────────────────────────────────
def restriction_payload(collection_id, category="P5_CONFIDENTIAL_ADVICE", **overrides):
    payload = {"collection_id": collection_id, "category": category}
    payload.update(overrides)
    return payload


def designate_payload(representative_id="rep-44", **overrides):
    payload = {"representative_id": representative_id}
    payload.update(overrides)
    return payload


# ─── Logical clock ───────────────────────────────────────────────────────────
def clock_payload(to_iso8601=STARTUP_CLOCK_UTC, **overrides):
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
