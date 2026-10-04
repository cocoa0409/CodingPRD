"""Named scenario builders.

Each builder stands up a complete, self-contained situation through the API so
that a test can start from a realistic state in one call. Every builder is
idempotent with respect to the test: it never reads state left behind by
another test.
"""
from .constants import CLOCK_START
from .fixtures import (
    activate_license,
    add_advisory_members,
    add_officers,
    add_program,
    create_filing,
    create_license,
    create_org,
    extract,
    file_correction_request,
    finalize_identity_case,
    get_filing,
    get_org,
    list_fields,
    normalize,
    open_identity_case,
    replace_demographics,
    verify_org,
)

USD_WHOLE_LINE = {"line_code": "TOTREV", "raw_value": "1000.00",
                  "raw_format": "USD_WHOLE", "is_revenue_component": True}


def add_verified_filing(org_id, *, tax_year, coverage_start, coverage_end,
                        amount="1000.00", line_code="TOTREV",
                        form_version_year=2023, form_type="FORM_990"):
    """Create, extract and normalize one filing; returns the normalized filing."""
    filing = create_filing(org_id, form_type=form_type,
                           form_version_year=form_version_year, tax_year=tax_year,
                           coverage_start=coverage_start, coverage_end=coverage_end)
    extract(filing["id"], [{"line_code": line_code, "raw_value": amount,
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    normalize(filing["id"])
    return get_filing(filing["id"])


# ---------------------------------------------------------------------------
# Organizations with a self-reported profile
# ---------------------------------------------------------------------------

def scenario_bright_futures():
    """DRAFT, SELF_REPORTED organization whose self-reported rows are complete
    but wholly unevidenced, plus one normalized filing carried on a
    USD_MILLIONS revenue line. Returns (organization, filing)."""
    org = create_org(
        "Bright Futures Alliance", "123456789", state_code="CA",
        display_name="Bright Futures", ntee_code="A20",
        mission_statement="Youth arts and tutoring for the East Bay.")
    oid = org["id"]
    add_program(oid, program_name="After School Tutoring", subject_code="A20",
                disclosure_level="PUBLIC")
    add_officers(oid, 3)
    replace_demographics(oid, [{
        "category": "RACE_ETHNICITY", "value_code": "BLACK_AFRICAN_AMERICAN",
        "disclosure_level": "PUBLIC", "fiscal_year": 2025}])
    filing = create_filing(oid, form_version_year=2023, tax_year=2025)
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "1.25",
                            "raw_format": "USD_MILLIONS", "is_revenue_component": True}])
    normalize(filing["id"])
    return get_org(oid), get_filing(filing["id"])


def scenario_helios():
    """ACTIVE, DOCUMENT_VERIFIED funder/researcher organization with a public
    program and three verified officers."""
    org = create_org(
        "Helios Foundation", "987654321", state_code="NY", ntee_code="T20",
        mission_statement="Community grantmaking in the Hudson Valley.")
    oid = org["id"]
    add_program(oid, program_name="Hudson Valley Grants", subject_code="T20",
                disclosure_level="PUBLIC")
    add_officers(oid, 3)
    verify_org(oid, "DOCUMENT_VERIFIED", 1)
    return get_org(oid)


def scenario_cascade():
    """ACTIVE, DOCUMENT_VERIFIED organization used by the correction and
    filing-lifecycle scenarios."""
    org = create_org(
        "Cascade Youth Trust", "864209753", state_code="WA", ntee_code="B82",
        mission_statement="Scholarships and mentoring for first-generation students.")
    oid = org["id"]
    add_program(oid, program_name="First-Gen Scholars", subject_code="B82",
                disclosure_level="PUBLIC")
    add_officers(oid, 3)
    verify_org(oid, "DOCUMENT_VERIFIED", 1)
    return get_org(oid)


def scenario_willow_creek(*, ein="900100200", state_code="IL", ntee_code="B82",
                          legal_name="Willow Creek Collective", activate=True):
    """ACTIVE organization used by the grant and prospect scenarios."""
    org = create_org(
        legal_name, ein, state_code=state_code, ntee_code=ntee_code,
        mission_statement="Mentoring and scholarships for first-generation students.")
    oid = org["id"]
    if activate:
        add_program(oid, program_name="Mentoring Core", subject_code=ntee_code,
                    disclosure_level="PUBLIC")
        add_officers(oid, 3)
        verify_org(oid, "DOCUMENT_VERIFIED", 1)
    return get_org(oid)


def scenario_funder(*, legal_name="Kestrel Giving Fund", ein="900100250",
                    state_code="IL", ntee_code=None, activate=False):
    org = create_org(legal_name, ein, state_code=state_code, ntee_code=ntee_code)
    if activate:
        oid = org["id"]
        add_program(oid, program_name="Giving Program", subject_code=ntee_code,
                    disclosure_level="PUBLIC")
        add_officers(oid, 3)
        verify_org(oid, "DOCUMENT_VERIFIED", 1)
        return get_org(oid)
    return org


# ---------------------------------------------------------------------------
# Seal-award scenarios
# ---------------------------------------------------------------------------

def scenario_meridian(*, verify_level="DOCUMENT_VERIFIED"):
    """Meridian Relief Network: disclosure_pct exactly 0.9000 (governance scores
    0.0 because every ACTIVE leadership row is a non-officer) and two verified
    filings in tax years 2024 and 2025."""
    org = create_org(
        "Meridian Relief Network", "246813579", state_code="TX", ntee_code="P60",
        mission_statement="Disaster relief and family assistance across the Gulf Coast.")
    oid = org["id"]
    add_program(oid, program_name="Storm Recovery Grants", subject_code="P60",
                disclosure_level="PUBLIC")
    add_advisory_members(oid, 3)
    replace_demographics(oid, [{
        "category": "AGE_BAND", "value_code": "AGE_35_44",
        "disclosure_level": "PUBLIC", "fiscal_year": 2025}])
    add_verified_filing(oid, tax_year=2024,
                        coverage_start="2024-01-01T00:00:00Z",
                        coverage_end="2024-12-31T00:00:00Z", amount="4000000.00")
    add_verified_filing(oid, tax_year=2025,
                        coverage_start="2025-01-01T00:00:00Z",
                        coverage_end="2025-12-31T00:00:00Z", amount="5000000.00")
    verify_org(oid, "DOCUMENT_VERIFIED", 3)
    if verify_level == "INDEPENDENTLY_AUDITED":
        verify_org(oid, "INDEPENDENTLY_AUDITED", 5)
    return get_org(oid)


def scenario_health_alliance(*, legal_name, ein, ntee_code=None, mission_statement=None,
                             first_amount="900000.00", second_amount="1100000.00"):
    """An INDEPENDENTLY_AUDITED organization whose disclosure_pct is driven by
    the mission dimension: 0.9000 with a full mission block, 0.8500 without the
    NTEE code. Leadership rows are non-officers, so governance scores 0.0."""
    org = create_org(legal_name, ein, state_code="VT", ntee_code=ntee_code,
                     mission_statement=mission_statement)
    oid = org["id"]
    add_program(oid, program_name="Mobile Clinic", subject_code="E30",
                disclosure_level="PUBLIC")
    add_advisory_members(oid, 3)
    replace_demographics(oid, [{
        "category": "VETERAN", "value_code": "VETERAN_SERVED",
        "disclosure_level": "PUBLIC", "fiscal_year": 2025}])
    add_verified_filing(oid, tax_year=2024,
                        coverage_start="2024-01-01T00:00:00Z",
                        coverage_end="2024-12-31T00:00:00Z", amount=first_amount)
    add_verified_filing(oid, tax_year=2025,
                        coverage_start="2025-01-01T00:00:00Z",
                        coverage_end="2025-12-31T00:00:00Z", amount=second_amount)
    verify_org(oid, "DOCUMENT_VERIFIED", 2)
    verify_org(oid, "INDEPENDENTLY_AUDITED", 4)
    return get_org(oid)


# ---------------------------------------------------------------------------
# Filing / correction scenarios
# ---------------------------------------------------------------------------

def scenario_riverbend():
    """ACTIVE organization with a filing whose two revenue lines both carry an
    exact half-cent fraction. Returns (organization, filing)."""
    org = create_org(
        "Riverbend Arts Council", "135792468", state_code="OR", ntee_code="A26",
        mission_statement="Community arts programming along the Willamette.")
    oid = org["id"]
    add_program(oid, program_name="Neighborhood Mural Project", subject_code="A26",
                disclosure_level="PUBLIC")
    add_officers(oid, 3)
    verify_org(oid, "DOCUMENT_VERIFIED", 1)
    filing = create_filing(oid, form_version_year=2023, tax_year=2025)
    extract(filing["id"], [
        {"line_code": "TOTREV", "raw_value": "1234.005", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "PROGREV", "raw_value": "5678.005", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
    ])
    normalize(filing["id"])
    return get_org(oid), get_filing(filing["id"])


def scenario_org_with_normalized_filing(org=None, *, raw_lines=None, tax_year=2025,
                                        form_type="FORM_990",
                                        coverage_start="2025-01-01T00:00:00Z",
                                        coverage_end="2025-12-31T00:00:00Z",
                                        form_version_year=2023):
    """An ACTIVE organization plus one normalized filing. Returns
    (organization, filing)."""
    org = org or scenario_cascade()
    filing = create_filing(org["id"], form_type=form_type,
                           form_version_year=form_version_year, tax_year=tax_year,
                           coverage_start=coverage_start, coverage_end=coverage_end)
    extract(filing["id"], raw_lines or [dict(USD_WHOLE_LINE)])
    normalize(filing["id"])
    return get_org(org["id"]), get_filing(filing["id"])


def scenario_org_with_open_correction(org=None, *, requested_value="2000.00"):
    """An ACTIVE organization, a normalized filing with one TOTREV line, and one
    SUBMITTED correction request against it. Returns (org, filing, field, request)."""
    org, filing = scenario_org_with_normalized_filing(org)
    field = list_fields(filing["id"], as_org=org["id"])[0]
    request = file_correction_request(org["id"], field["id"], field["version"],
                                      requested_value=requested_value)
    return org, filing, field, request


# ---------------------------------------------------------------------------
# Licensing scenarios
# ---------------------------------------------------------------------------

def scenario_license_holder(*, tier="RESEARCHER", permitted_use="AGGREGATE_RESEARCH",
                            projected_annual_records=12000,
                            term_start=CLOCK_START, term_end="2027-09-01T00:00:00Z",
                            activate=True):
    """An ACTIVE, DOCUMENT_VERIFIED organization holding one license.
    Returns (organization, license)."""
    org = scenario_helios()
    license_ = create_license(
        org["id"], tier=tier, permitted_use=permitted_use,
        projected_annual_records=projected_annual_records,
        term_start=term_start, term_end=term_end)
    if activate:
        license_ = activate_license(license_["id"], org["id"])
    return org, license_


def scenario_dissolved_license_holder():
    """An organization dissolved by a finalized DISSOLUTION case, holding a DRAFT
    RESEARCHER license whose permitted_use is illegal for that tier.
    Returns (organization, license)."""
    org = create_org("Plateau Analytics", "555111222", org_type="OTHER",
                     state_code="CO")
    case = open_identity_case(org["id"], "DISSOLUTION",
                              resolution_note="Plateau Analytics ceased operations.")
    finalize_identity_case(case["id"])
    license_ = create_license(org["id"], tier="RESEARCHER",
                              permitted_use="GRANTMAKING_DUE_DILIGENCE",
                              projected_annual_records=20000)
    return get_org(org["id"]), license_


def scenario_ridgeway():
    """An ACTIVE, DOCUMENT_VERIFIED organization holding a DRAFT RESEARCHER
    license whose permitted_use is illegal for that tier.
    Returns (organization, license)."""
    org = create_org("Ridgeway Trust", "333444555", state_code="CO", ntee_code="T20",
                     mission_statement="Place-based grantmaking in the Front Range.")
    oid = org["id"]
    add_program(oid, program_name="Front Range Grants", subject_code="T20",
                disclosure_level="PUBLIC")
    add_officers(oid, 3)
    verify_org(oid, "DOCUMENT_VERIFIED", 1)
    license_ = create_license(oid, tier="RESEARCHER",
                              permitted_use="GRANTMAKING_DUE_DILIGENCE",
                              projected_annual_records=20000)
    return get_org(oid), license_
