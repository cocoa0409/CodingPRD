"""Composite setup helpers.

The test harness restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use the lenient get_success_data() validator so failures surface
as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_alert_payload,
    create_assignment_payload,
    create_cell_payload,
    create_contract_payload,
    create_coordination_request_payload,
    create_device_payload,
    create_design_payload,
    create_enterprise_payload,
    create_lease_payload,
    create_remediation_payload,
    create_sim_profile_payload,
    create_site_payload,
    create_slice_payload,
    create_survey_payload,
)
from .test_users import (
    TEST_USERS,
    make_field_technician_headers,
    make_spectrum_coordinator_headers,
)

NA = TEST_USERS["network_architect_headers"]
RFE = TEST_USERS["rf_engineer_headers"]
SC = TEST_USERS["spectrum_coordinator_headers"]
SR = TEST_USERS["spectrum_regulator_headers"]
FT = TEST_USERS["field_technician_headers"]


# ---- Enterprise / Site basics ----------------------------------------------

def create_enterprise(**overrides):
    """Create an Enterprise (still ONBOARDING). Returns the enterprise dict."""
    resp = api_client.create_enterprise(create_enterprise_payload(**overrides), NA)
    return get_success_data(resp)


def create_active_enterprise(**overrides):
    """Create an Enterprise and leave it ONBOARDING (activation needs a Site).

    Note: per PRD §3.1, an Enterprise leaves ONBOARDING for ACTIVE only when it
    has at least one Site; callers that need an ACTIVE enterprise should use
    create_enterprise_with_site() instead.
    """
    return create_enterprise(**overrides)


def create_enterprise_with_site(ent_overrides=None, site_overrides=None):
    """Create Enterprise + Site, then activate the Enterprise.

    Returns (enterprise, site).
    """
    ent = create_enterprise(**(ent_overrides or {}))
    site_resp = api_client.create_site(ent["id"], create_site_payload(**(site_overrides or {})), NA)
    site = get_success_data(site_resp)
    act_resp = api_client.activate_enterprise(ent["id"], NA)
    ent = get_success_data(act_resp)
    return ent, site


# ---- Survey -----------------------------------------------------------------

def create_submitted_survey(site_id, surveyor_id="ft-001", **overrides):
    """Create + submit a SiteSurvey. Returns (survey, surveyor_headers)."""
    payload = create_survey_payload(surveyor_id=surveyor_id, **overrides)
    ft_headers = make_field_technician_headers(surveyor_id)
    resp = api_client.create_survey(site_id, payload, ft_headers)
    survey = get_success_data(resp)
    sub = api_client.submit_survey(site_id, survey["id"], ft_headers)
    survey = get_success_data(sub)
    return survey, ft_headers


def create_approved_survey(site_id, surveyor_id="ft-001", **overrides):
    """Create, submit, and approve a SiteSurvey. Returns (survey, site)."""
    survey, _ = create_submitted_survey(site_id, surveyor_id=surveyor_id, **overrides)
    resp = api_client.approve_survey(site_id, survey["id"], RFE)
    survey = get_success_data(resp)
    site = get_success_data(api_client.get_site(site_id, NA))
    return survey, site


# ---- CoverageDesign ---------------------------------------------------------

def create_design_for_site(site_id, survey_id, site_version, **overrides):
    """Create a CoverageDesign in DRAFT. Returns design dict."""
    payload = create_design_payload(
        based_on_survey_id=survey_id,
        expected_site_version=site_version,
        **overrides,
    )
    resp = api_client.create_design(site_id, payload, RFE)
    return get_success_data(resp)


def create_submitted_design(site_id, survey_id, site_version, **overrides):
    """Create + submit a CoverageDesign. Returns (design, site)."""
    design = create_design_for_site(site_id, survey_id, site_version, **overrides)
    resp = api_client.submit_design(site_id, design["id"], RFE)
    design = get_success_data(resp)
    site = get_success_data(api_client.get_site(site_id, NA))
    return design, site


# ---- CellSector -------------------------------------------------------------

def create_cell(site_id, **overrides):
    resp = api_client.create_cell(site_id, create_cell_payload(**overrides), RFE)
    return get_success_data(resp)


def create_configured_cell(site_id, **overrides):
    cell = create_cell(site_id, **overrides)
    resp = api_client.configure_cell(site_id, cell["id"], FT)
    return get_success_data(resp)


# ---- SpectrumLease ----------------------------------------------------------

def create_lease(enterprise_id, **overrides):
    resp = api_client.create_lease(enterprise_id, create_lease_payload(**overrides), SC)
    return get_success_data(resp)


def create_active_lease(enterprise_id, **overrides):
    lease = create_lease(enterprise_id, **overrides)
    resp = api_client.activate_lease(lease["id"], SC)
    return get_success_data(resp)


# ---- SpectrumCoordinationRequest -------------------------------------------

def create_approved_design(site_id, survey_id, site_version=None, cell_labels=("FX-1", "FX-2", "FX-3"), **overrides):
    """Create + submit + approve a CoverageDesign, moving the Site to DESIGNED.

    PRD §3.3 computes `predicted_capacity_mbps` at design creation over the
    cells existing at that moment and gates approval on
    `capacity_shortfall_mbps == 0`, so the cells are created first: three
    default cells give 3 x 810 = 2430 Mbps predicted against the default
    1000 Mbps target. Returns (design, site).
    """
    for label in cell_labels:
        create_cell(site_id, sector_label=label)
    site = get_success_data(api_client.get_site(site_id, NA))
    design, site = create_submitted_design(site_id, survey_id, site["version"], **overrides)
    resp = api_client.approve_design(site_id, design["id"], NA)
    design = get_success_data(resp)
    site = get_success_data(api_client.get_site(site_id, NA))
    return design, site


def create_designed_site():
    """Enterprise + Site + APPROVED survey + APPROVED design => Site DESIGNED.

    Returns (enterprise, site, survey).
    """
    ent, site = create_enterprise_with_site()
    survey, site = create_approved_survey(site["id"])
    _design, site = create_approved_design(site["id"], survey["id"], site["version"])
    return ent, site, survey


def decommission_design_cells(site_id):
    """Decommission the leftover PLANNED capacity cells on the site.

    PRD §3.5 promotes a COORDINATED site to DEPLOYED only when every PLANNED
    cell either holds an ACTIVE assignment or has been DECOMMISSIONED; tests
    that drive a site to DEPLOYED/OPERATIONAL therefore clear these leftover
    PLANNED cells first. Decommission is permitted from any non-terminal
    state (PRD §3.5).
    """
    data, _meta = validate_paginated(
        api_client.list_cells(NA, params={"site_id": site_id})
    )
    for cell in data:
        if cell["site_id"] == site_id and cell["status"] == "PLANNED":
            get_success_data(api_client.decommission_cell(site_id, cell["id"], FT))


def create_coordination_request(site_id, coordinator_id="sc-001", **overrides):
    """Create a SpectrumCoordinationRequest in DRAFT.

    Returns (request, coordinator_headers).
    """
    payload = create_coordination_request_payload(
        requesting_coordinator_id=coordinator_id, **overrides
    )
    headers = make_spectrum_coordinator_headers(coordinator_id)
    resp = api_client.create_coordination_request(site_id, payload, headers)
    return get_success_data(resp), headers


# ---- SIM / Device -----------------------------------------------------------

def create_sim_profile(enterprise_id, **overrides):
    resp = api_client.create_sim_profile(enterprise_id, create_sim_profile_payload(**overrides), FT)
    return get_success_data(resp)


def create_device(cell_id, **overrides):
    resp = api_client.create_device(cell_id, create_device_payload(**overrides), FT)
    return get_success_data(resp)


# ---- NetworkSlice -----------------------------------------------------------

def create_slice(site_id, **overrides):
    resp = api_client.create_slice(site_id, create_slice_payload(**overrides), NA)
    return get_success_data(resp)


# ---- ServiceContract --------------------------------------------------------

def create_contract(enterprise_id, **overrides):
    resp = api_client.create_contract(enterprise_id, create_contract_payload(**overrides), NA)
    return get_success_data(resp)


def create_active_contract(enterprise_id, **overrides):
    contract = create_contract(enterprise_id, **overrides)
    resp = api_client.activate_contract(enterprise_id, contract["id"], NA)
    return get_success_data(resp)


# ---- MonitoringAlert --------------------------------------------------------

def create_alert(site_id, **overrides):
    resp = api_client.create_alert(site_id, create_alert_payload(**overrides), FT)
    return get_success_data(resp)


def create_mitigating_alert(site_id, **overrides):
    alert = create_alert(site_id, **overrides)
    alert = get_success_data(api_client.acknowledge_alert(site_id, alert["id"], FT))
    alert = get_success_data(api_client.mitigate_alert(site_id, alert["id"], FT))
    return alert


# ---- CoverageRemediation ----------------------------------------------------

def create_remediation(site_id, triggered_by_alert_id, **overrides):
    payload = create_remediation_payload(triggered_by_alert_id=triggered_by_alert_id, **overrides)
    resp = api_client.create_remediation(site_id, payload, RFE)
    return get_success_data(resp)


def create_in_progress_remediation(site_id, triggered_by_alert_id, **overrides):
    rem = create_remediation(site_id, triggered_by_alert_id, **overrides)
    rem = get_success_data(api_client.approve_remediation(site_id, rem["id"], NA))
    rem = get_success_data(api_client.start_remediation(site_id, rem["id"], RFE))
    return rem
