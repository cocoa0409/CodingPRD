"""Composite setup helpers.

Every helper builds its preconditions from scratch through the API, because the
server is restarted (and its in-memory store wiped) before every individual
test. Nothing here caches state across tests.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START,
    DEFAULT_COVERAGE_END,
    DEFAULT_COVERAGE_START,
    DEFAULT_SERVICE_START,
    DEFAULT_TERM_END,
    DEFAULT_TERM_START,
)
from .test_users import (
    ADMIN_USER_ID,
    VERIFIER_USER_ID,
    make_admin_headers,
    make_data_consumer_headers,
    make_organization_user_headers,
    make_verifier_headers,
)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(instant=CLOCK_START, user_id=ADMIN_USER_ID):
    """Advance the logical clock (PRD §2.4)."""
    resp = api_client.set_clock(instant, make_admin_headers(user_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Organization primitives
# ---------------------------------------------------------------------------

def create_org(legal_name, ein, *, org_type="501C3", state_code="IL",
               display_name=None, ntee_code=None, mission_statement=None,
               extra=None, admin_id=ADMIN_USER_ID):
    """Create an organization as PlatformAdmin. Optional fields are omitted
    unless supplied, so the server's own defaults are observable."""
    payload = {
        "legal_name": legal_name,
        "ein": ein,
        "org_type": org_type,
        "state_code": state_code,
    }
    if display_name is not None:
        payload["display_name"] = display_name
    if ntee_code is not None:
        payload["ntee_code"] = ntee_code
    if mission_statement is not None:
        payload["mission_statement"] = mission_statement
    if extra:
        payload.update(extra)
    resp = api_client.create_organization(payload, make_admin_headers(admin_id))
    return get_success_data(resp)


def get_org(org_id, user_id=None):
    headers = (make_organization_user_headers(user_id) if user_id
               else make_admin_headers())
    return get_success_data(api_client.get_organization(org_id, headers))


def org_version(org_id):
    return get_org(org_id)["version"]


def patch_org(org_id, payload, *, as_org=False, user_id=None):
    """PATCH the profile as the owning organization (or as an admin)."""
    headers = (make_organization_user_headers(user_id or org_id) if as_org
               else make_admin_headers(user_id))
    return api_client.patch_organization(org_id, payload, headers)


def replace_demographics(org_id, records):
    """Replace the organization's whole demographic set (PRD §3.1)."""
    version = org_version(org_id)
    payload = {"expected_organization_version": version, "demographic_records": records}
    resp = patch_org(org_id, payload, as_org=True)
    return get_success_data(resp)


def add_program(org_id, *, program_name="Mentoring Core", fiscal_year=2025,
                subject_code=None, disclosure_level=None, population_served=None):
    payload = {"program_name": program_name, "fiscal_year": fiscal_year}
    if subject_code is not None:
        payload["subject_code"] = subject_code
    if disclosure_level is not None:
        payload["disclosure_level"] = disclosure_level
    if population_served is not None:
        payload["population_served"] = population_served
    resp = api_client.create_program(org_id, payload, make_organization_user_headers(org_id))
    return get_success_data(resp)


def add_leader(org_id, *, full_name, office_title, is_officer=True,
               is_independent=True, disclosure_level="PUBLIC",
               service_start=DEFAULT_SERVICE_START, service_end=None,
               compensation_cents=0):
    payload = {
        "full_name": full_name,
        "office_title": office_title,
        "service_start": service_start,
        "is_officer": is_officer,
        "is_independent": is_independent,
        "disclosure_level": disclosure_level,
        "compensation_cents": compensation_cents,
    }
    if service_end is not None:
        payload["service_end"] = service_end
    resp = api_client.create_leadership_member(
        org_id, payload, make_organization_user_headers(org_id))
    return get_success_data(resp)


DEFAULT_OFFICER_TITLES = ["Board Chair", "Treasurer", "Secretary", "Audit Chair", "Member"]
DEFAULT_OFFICER_NAMES = ["Ada Reyes", "Ben Osei", "Cleo Marsh", "Dev Patel", "Eve Lang"]


def add_officers(org_id, count=3, *, independent=True, disclosure_level="PUBLIC",
                 names=None, titles=None):
    """Add `count` voting officers, each with a distinct office_title so the
    closed service intervals never collide."""
    names = names or DEFAULT_OFFICER_NAMES
    titles = titles or DEFAULT_OFFICER_TITLES
    created = []
    for i in range(count):
        created.append(add_leader(
            org_id,
            full_name=names[i % len(names)],
            office_title=titles[i % len(titles)],
            is_officer=True,
            is_independent=independent,
            disclosure_level=disclosure_level,
        ))
    return created


def add_advisory_members(org_id, count=3, *, disclosure_level="PUBLIC"):
    """Add `count` leadership rows that are neither officers nor independent."""
    names = ["Nils Berg", "Ora Finch", "Pia Lund", "Quinn Alder"]
    titles = ["Advisor", "Counsel", "Historian", "Fellow"]
    created = []
    for i in range(count):
        created.append(add_leader(
            org_id,
            full_name=names[i % len(names)],
            office_title=titles[i % len(titles)],
            is_officer=False,
            is_independent=False,
            disclosure_level=disclosure_level,
        ))
    return created


def verify_org(org_id, target_level="DOCUMENT_VERIFIED", evidence_count=1,
               verifier_id=VERIFIER_USER_ID):
    resp = api_client.verify_organization(
        org_id, {"target_level": target_level, "evidence_count": evidence_count},
        make_verifier_headers(verifier_id))
    return get_success_data(resp)


def verify_to_independently_audited(org_id, verifier_id=VERIFIER_USER_ID):
    verify_org(org_id, "DOCUMENT_VERIFIED", 1, verifier_id)
    return verify_org(org_id, "INDEPENDENTLY_AUDITED", 1, verifier_id)


# ---------------------------------------------------------------------------
# Filing primitives
# ---------------------------------------------------------------------------

def create_filing(org_id, *, form_type="FORM_990", form_version_year=2023,
                  tax_year=2025, coverage_start=DEFAULT_COVERAGE_START,
                  coverage_end=DEFAULT_COVERAGE_END, source="IRS_BULK_XML",
                  expected_organization_version=None, as_admin=False):
    if expected_organization_version is None:
        expected_organization_version = org_version(org_id)
    payload = {
        "organization_id": org_id,
        "form_type": form_type,
        "form_version_year": form_version_year,
        "tax_year": tax_year,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "source": source,
        "expected_organization_version": expected_organization_version,
    }
    headers = (make_admin_headers() if as_admin
               else make_organization_user_headers(org_id))
    resp = api_client.create_filing(payload, headers)
    return get_success_data(resp)


def extract(filing_id, raw_lines, verifier_id=VERIFIER_USER_ID):
    resp = api_client.extract_filing(
        filing_id, {"raw_lines": raw_lines}, make_verifier_headers(verifier_id))
    return get_success_data(resp)


def normalize(filing_id, verifier_id=VERIFIER_USER_ID):
    resp = api_client.normalize_filing(filing_id, make_verifier_headers(verifier_id))
    return get_success_data(resp)


def void_filing(filing_id, admin_id=ADMIN_USER_ID):
    resp = api_client.void_filing(filing_id, make_admin_headers(admin_id))
    return get_success_data(resp)


def get_filing(filing_id, verifier_id=VERIFIER_USER_ID):
    return get_success_data(api_client.get_filing(filing_id, make_verifier_headers(verifier_id)))


def list_fields(filing_id, *, as_org=None):
    headers = (make_organization_user_headers(as_org) if as_org
               else make_verifier_headers())
    return get_success_data(api_client.list_extracted_fields(filing_id, headers))


def extract_and_normalize(org_id, raw_lines, **filing_kwargs):
    """Create a filing for `org_id`, extract `raw_lines` and normalize it."""
    filing = create_filing(org_id, **filing_kwargs)
    extract(filing["id"], raw_lines)
    normalized = normalize(filing["id"])
    return filing, normalized


def create_normalized_filing(org_id, raw_lines=None, **filing_kwargs):
    """A filing whose lines have been extracted and normalized."""
    raw_lines = raw_lines or [{"line_code": "TOTREV", "raw_value": "1000.00",
                               "raw_format": "USD_WHOLE", "is_revenue_component": True}]
    filing, _ = extract_and_normalize(org_id, raw_lines, **filing_kwargs)
    return filing


# ---------------------------------------------------------------------------
# Correction request primitives
# ---------------------------------------------------------------------------

def file_correction_request(org_id, field_id, expected_field_version,
                            requested_value="2000.00",
                            evidence_url="https://evidence.example.org/audited-2025.pdf",
                            justification="The audited statement reports a different total."):
    payload = {
        "requested_value": requested_value,
        "evidence_url": evidence_url,
        "justification": justification,
        "expected_extracted_field_version": expected_field_version,
    }
    resp = api_client.create_correction_request(
        field_id, payload, make_organization_user_headers(org_id))
    return get_success_data(resp)


def decide(request_id, decision, *, verifier_id=VERIFIER_USER_ID, as_org=None,
           review_note=None, corrected_value=None):
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    if corrected_value is not None:
        payload["corrected_value"] = corrected_value
    headers = (make_organization_user_headers(as_org) if as_org
               else make_verifier_headers(verifier_id))
    resp = api_client.decide_correction_request(request_id, payload, headers)
    return get_success_data(resp)


def get_correction(request_field_id, request_id=None, *, as_org=None):
    """Read back correction requests through the field's list endpoint."""
    headers = (make_organization_user_headers(as_org) if as_org
               else make_verifier_headers())
    rows = get_success_data(api_client.list_field_correction_requests(request_field_id, headers))
    if request_id is None:
        return rows
    return next(r for r in rows if r["id"] == request_id)


# ---------------------------------------------------------------------------
# Seals
# ---------------------------------------------------------------------------

def award_seal(org_id, verifier_id=VERIFIER_USER_ID):
    resp = api_client.award_seal(org_id, make_verifier_headers(verifier_id))
    return get_success_data(resp)


def list_seals(org_id):
    return get_success_data(api_client.list_seals(org_id, make_verifier_headers()))


def renew_seal(seal_id, verifier_id=VERIFIER_USER_ID):
    resp = api_client.renew_seal(seal_id, make_verifier_headers(verifier_id))
    return get_success_data(resp)


def seal_by_id(org_id, seal_id):
    for seal in list_seals(org_id):
        if seal["id"] == seal_id:
            return seal
    raise AssertionError(f"Seal {seal_id} not found among the organization's seals")


# ---------------------------------------------------------------------------
# Data licenses
# ---------------------------------------------------------------------------

def create_license(org_id, *, tier="RESEARCHER", permitted_use="AGGREGATE_RESEARCH",
                   term_start=DEFAULT_TERM_START, term_end=DEFAULT_TERM_END,
                   projected_annual_records=12000, auto_renew=None):
    payload = {
        "tier": tier,
        "permitted_use": permitted_use,
        "term_start": term_start,
        "term_end": term_end,
        "projected_annual_records": projected_annual_records,
    }
    if auto_renew is not None:
        payload["auto_renew"] = auto_renew
    resp = api_client.create_license(org_id, payload, make_data_consumer_headers(org_id))
    return get_success_data(resp)


def activate_license(license_id, licensee_org_id):
    resp = api_client.activate_license(license_id, make_data_consumer_headers(licensee_org_id))
    return get_success_data(resp)


def get_license(license_id, licensee_org_id):
    return get_success_data(
        api_client.get_license(license_id, make_data_consumer_headers(licensee_org_id)))


def post_usage(license_id, licensee_org_id, *, record_count=1000,
               dataset_scope="ORGANIZATION_PROFILES", purpose_code="PILOT_SCAN"):
    payload = {
        "dataset_scope": dataset_scope,
        "record_count": record_count,
        "purpose_code": purpose_code,
    }
    resp = api_client.post_usage_event(
        license_id, payload, make_data_consumer_headers(licensee_org_id))
    return get_success_data(resp)


def void_usage(license_id, event_id, admin_id=ADMIN_USER_ID):
    resp = api_client.void_usage_event(license_id, event_id, make_admin_headers(admin_id))
    return get_success_data(resp)


def list_usage(license_id, licensee_org_id):
    return get_success_data(
        api_client.list_usage_events(license_id, make_data_consumer_headers(licensee_org_id)))


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

def create_grant(recipient_org_id, funder_org_id, *, funder_name_raw=None,
                 recipient_name_raw=None, amount_cents=500000, fiscal_year=2025,
                 recipient_ein=None, subject_code=None):
    payload = {
        "funder_organization_id": funder_org_id,
        "funder_name_raw": funder_name_raw or "Kestrel Giving Fund",
        "recipient_name_raw": recipient_name_raw or "Willow Creek Collective",
        "amount_cents": amount_cents,
        "fiscal_year": fiscal_year,
    }
    if recipient_ein is not None:
        payload["recipient_ein"] = recipient_ein
    if subject_code is not None:
        payload["subject_code"] = subject_code
    resp = api_client.create_grant(
        recipient_org_id, payload, make_data_consumer_headers(funder_org_id))
    return get_success_data(resp)


def list_grants(org_id, as_org=None):
    headers = (make_data_consumer_headers(as_org) if as_org
               else make_admin_headers())
    return get_success_data(api_client.list_grants(org_id, headers))


def match_recipient(grant_id, funder_org_id, *, recipient_ein=None, subject_code=None):
    payload = {}
    if recipient_ein is not None:
        payload["recipient_ein"] = recipient_ein
    if subject_code is not None:
        payload["subject_code"] = subject_code
    resp = api_client.match_grant_recipient(
        grant_id, payload, make_data_consumer_headers(funder_org_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------

def open_identity_case(subject_org_id, case_type="MERGE", *, surviving_org_id=None,
                       new_legal_name=None, effective_date=CLOCK_START,
                       resolution_note="Case opened for resolution."):
    payload = {
        "subject_organization_id": subject_org_id,
        "case_type": case_type,
        "effective_date": effective_date,
        "resolution_note": resolution_note,
    }
    if surviving_org_id is not None:
        payload["surviving_organization_id"] = surviving_org_id
    if new_legal_name is not None:
        payload["new_legal_name"] = new_legal_name
    resp = api_client.create_identity_case(payload, make_admin_headers())
    return get_success_data(resp)


def finalize_identity_case(case_id, decision="FINALIZE", admin_id=ADMIN_USER_ID):
    resp = api_client.finalize_identity_case(
        case_id, {"resolution_decision": decision}, make_admin_headers(admin_id))
    return get_success_data(resp)


def list_identity_cases(org_id):
    return get_success_data(api_client.list_identity_cases(org_id, make_admin_headers()))


# ---------------------------------------------------------------------------
# Funder research
# ---------------------------------------------------------------------------

def get_prospects(funder_org_id, *, subject_code=None, min_score=None,
                  limit=None, offset=None):
    params = {"funder_organization_id": funder_org_id}
    if subject_code is not None:
        params["subject_code"] = subject_code
    if min_score is not None:
        params["min_score"] = min_score
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    resp = api_client.get_prospects(make_data_consumer_headers(funder_org_id), params)
    return get_success_data(resp)
