"""Composite setup helpers — multi-step API preconditions for tests.

Every helper builds its state from PRD-declared endpoints against an empty
database (the runner restarts the server before every test) and returns
plain dicts of created entities. Setup calls use get_success_data() so a
broken precondition surfaces as a clear setup failure.

Identity threading: entity-backed DistributorContact calls always use
make_distributor_contact_headers(distributor["id"]); Consumer calls use
make_consumer_headers(submitter_ref). Segregation-sensitive defaults:
manufacturers/grants are created by tso-1, promotions by pa-1, approvals
by mm-1, revocations by ca-1.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories
from .api_client import api_client
from .test_users import TEST_USERS, make_distributor_contact_headers, make_consumer_headers

# Canonical default headers per workflow owner (short aliases).
BM = TEST_USERS["brand_manager_headers"]
TSO = TEST_USERS["trade_secret_officer_headers"]
CA = TEST_USERS["compliance_auditor_headers"]
CM = TEST_USERS["channel_manager_headers"]
PA = TEST_USERS["pricing_analyst_headers"]
MM = TEST_USERS["marketing_manager_headers"]
RA = TEST_USERS["regulatory_affairs_headers"]
SP = TEST_USERS["supply_planner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Platform clock
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PlatformAdmin); returns {current_utc: ...}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: atomic validated creators
# ---------------------------------------------------------------------------

def create_brand(headers=None, **overrides) -> dict:
    """Create a brand (OPERATING, posture NORMAL); returns the brand."""
    return get_success_data(api_client.create_brand(
        factories.create_brand_payload(**overrides), headers or BM))


def create_market(headers=None, **overrides) -> dict:
    """Create a market (OPEN); returns the market."""
    return get_success_data(api_client.create_market(
        factories.create_market_payload(**overrides), headers or RA))


def create_product_line(brand_id, headers=None, **overrides) -> dict:
    """Create a product line under a brand (FORMULATION); returns the line."""
    return get_success_data(api_client.create_product_line(
        brand_id, factories.create_product_line_payload(**overrides), headers or BM))


def create_formulation(line_id, headers=None, **overrides) -> dict:
    """Create a formulation for a line (DRAFT); returns the formulation."""
    return get_success_data(api_client.create_formulation(
        line_id, factories.create_formulation_payload(**overrides), headers or TSO))


def create_and_seal_formulation(line_id, headers=None, **overrides) -> dict:
    """Create a formulation and seal it (SEALED); returns the sealed formulation."""
    form = create_formulation(line_id, headers=headers, **overrides)
    return get_success_data(api_client.seal_formulation(form["id"], headers or TSO))


def create_manufacturer(headers=None, **overrides) -> dict:
    """Onboard a contract manufacturer (VETTING); returns the manufacturer."""
    return get_success_data(api_client.create_contract_manufacturer(
        factories.create_contract_manufacturer_payload(**overrides), headers or TSO))


def create_qualified_manufacturer(headers=None, **overrides) -> dict:
    """Onboard and qualify a contract manufacturer (QUALIFIED)."""
    mfr = create_manufacturer(headers=headers, **overrides)
    return get_success_data(api_client.qualify_contract_manufacturer(
        mfr["id"], headers or TSO))


def create_grant_request(manufacturer_id, formulation_id, headers=None, **overrides) -> dict:
    """Request a confidentiality grant (REQUESTED); returns the grant."""
    return get_success_data(api_client.create_confidentiality_grant(
        factories.create_confidentiality_grant_payload(
            manufacturer_id=manufacturer_id, formulation_id=formulation_id, **overrides),
        headers or TSO))


def create_granted_grant(manufacturer_id, formulation_id, headers=None, **overrides) -> dict:
    """Request and grant a confidentiality grant (GRANTED); returns the grant."""
    grant = create_grant_request(manufacturer_id, formulation_id,
                                 headers=headers, **overrides)
    return get_success_data(api_client.grant_confidentiality_grant(
        grant["id"], headers or TSO))


def create_active_grant(manufacturer_id, formulation_id, headers=None, **overrides) -> dict:
    """Request, grant and activate a confidentiality grant (ACTIVE)."""
    grant = create_granted_grant(manufacturer_id, formulation_id,
                                 headers=headers, **overrides)
    return get_success_data(api_client.activate_confidentiality_grant(
        grant["id"], headers or TSO))


def create_distributor_record(home_market_id, headers=None, **overrides) -> dict:
    """Create a distributor (APPLICANT); returns the distributor."""
    return get_success_data(api_client.create_distributor(
        factories.create_distributor_payload(home_market_id=home_market_id, **overrides),
        headers or CM))


def create_approved_distributor(home_market_id, headers=None, **overrides) -> dict:
    """Create and approve a distributor (APPROVED); returns the distributor."""
    dist = create_distributor_record(home_market_id, headers=headers, **overrides)
    return get_success_data(api_client.approve_distributor(dist["id"], headers or CM))


def get_distributor_version(distributor_id) -> int:
    """Read the distributor's current version (OCC token)."""
    return get_success_data(api_client.get_distributor(distributor_id, CM))["version"]


def get_pack_format_version(pack_format_id) -> int:
    """Read the pack format's current version (OCC token)."""
    return get_success_data(api_client.get_pack_format(pack_format_id, SP))["version"]


def propose_coverage_assignment(distributor_id, market_id, product_line_id,
                                headers=None, expected_distributor_version=None,
                                **overrides) -> dict:
    """Propose a coverage assignment (PROPOSED); auto-fetches the OCC version."""
    if expected_distributor_version is None:
        expected_distributor_version = get_distributor_version(distributor_id)
    return get_success_data(api_client.create_coverage_assignment(
        distributor_id,
        factories.create_coverage_assignment_payload(
            market_id=market_id, product_line_id=product_line_id,
            expected_distributor_version=expected_distributor_version, **overrides),
        headers or CM))


def create_active_assignment(distributor_id, market_id, product_line_id,
                             headers=None, **overrides) -> dict:
    """Propose and activate a coverage assignment (ACTIVE)."""
    asg = propose_coverage_assignment(distributor_id, market_id, product_line_id,
                                      headers=headers, **overrides)
    return get_success_data(api_client.activate_coverage_assignment(
        asg["id"], headers or CM))


def create_pack_format_record(line_id, headers=None, **overrides) -> dict:
    """Create a pack format (DESIGNED); returns the pack."""
    return get_success_data(api_client.create_pack_format(
        line_id, factories.create_pack_format_payload(**overrides), headers or SP))


def create_tooled_pack(line_id, headers=None, **overrides) -> dict:
    """Create and tool a pack format (TOOLED); the line must be PILOT/LAUNCHED."""
    pack = create_pack_format_record(line_id, headers=headers, **overrides)
    return get_success_data(api_client.tool_pack_format(pack["id"], headers or SP))


def create_price_list_record(pack_format_id, headers=None,
                             expected_pack_format_version=None, **overrides) -> dict:
    """Create a channel price list; auto-fetches the pack's OCC version."""
    if expected_pack_format_version is None:
        expected_pack_format_version = get_pack_format_version(pack_format_id)
    return get_success_data(api_client.create_price_list(
        pack_format_id,
        factories.create_price_list_payload(
            expected_pack_format_version=expected_pack_format_version, **overrides),
        headers or PA))


def create_promotion_record(line_id, headers=None, **overrides) -> dict:
    """Create a promotion (DRAFT); the caller is recorded as creator."""
    return get_success_data(api_client.create_promotion(
        factories.create_promotion_payload(product_line_id=line_id, **overrides),
        headers or PA))


def create_counterfeit_case_record(brand_id, market_id, headers=None, **overrides) -> dict:
    """Report a counterfeit case (REPORTED); recomputes brand posture."""
    return get_success_data(api_client.create_counterfeit_case(
        brand_id,
        factories.create_counterfeit_case_payload(market_id=market_id, **overrides),
        headers or CA))


def create_use_case_record(line_id, submitter_ref, headers=None, **overrides) -> dict:
    """Submit a consumer use case (SUBMITTED); caller id equals submitter_ref."""
    return get_success_data(api_client.create_use_case(
        line_id,
        factories.create_use_case_payload(submitter_ref=submitter_ref, **overrides),
        headers or make_consumer_headers(submitter_ref)))


def file_sell_through_report(distributor_id, assignment_id, period_month,
                             units_sold, units_returned=None) -> dict:
    """File a sell-through report as the owning DistributorContact."""
    overrides = {}
    if units_returned is not None:
        overrides["units_returned"] = units_returned
    return get_success_data(api_client.create_sell_through_report(
        distributor_id,
        factories.create_sell_through_report_payload(
            coverage_assignment_id=assignment_id, period_month=period_month,
            units_sold=units_sold, **overrides),
        make_distributor_contact_headers(distributor_id)))


def create_market_registration_record(market_id, product_line_id, formulation_id,
                                      headers=None, **overrides) -> dict:
    """Create a market registration (DRAFT); returns the registration."""
    return get_success_data(api_client.create_market_registration(
        factories.create_market_registration_payload(
            market_id=market_id, product_line_id=product_line_id,
            formulation_id=formulation_id, **overrides),
        headers or RA))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchies
# ---------------------------------------------------------------------------

def setup_brand_with_market(brand_overrides=None, market_overrides=None) -> dict:
    """Brand plus one market. Returns {"brand", "market"}."""
    brand = create_brand(**(brand_overrides or {}))
    market = create_market(**(market_overrides or {}))
    return {"brand": brand, "market": market}


def setup_line_with_sealed_formulation(line_overrides=None, form_overrides=None) -> dict:
    """Brand + product line + SEALED formulation. Returns {"brand", "line", "formulation"}."""
    brand = create_brand()
    line = create_product_line(brand["id"], **(line_overrides or {}))
    form = create_and_seal_formulation(line["id"], **(form_overrides or {}))
    return {"brand": brand, "line": line, "formulation": form}


def setup_compartmentalized_line(line_overrides=None, form_overrides=None,
                                 scope_a=("C1", "C2"), scope_b=("C3", "C4")) -> dict:
    """Brand + line + formulation COMPARTMENTALIZED via two ACTIVE grants held
    by two QUALIFIED manufacturers (split scopes). Returns {"brand", "line",
    "formulation", "mfr1", "mfr2", "grant1", "grant2"}."""
    base = setup_line_with_sealed_formulation(line_overrides, form_overrides)
    mfr1 = create_qualified_manufacturer(
        legal_name="Alpha Blending Co", capabilities=["BLENDING"])
    mfr2 = create_qualified_manufacturer(
        legal_name="Beta Filling Inc", capabilities=["AEROSOL_FILL"])
    grant1 = create_active_grant(mfr1["id"], base["formulation"]["id"],
                                 component_scope=list(scope_a))
    grant2 = create_active_grant(mfr2["id"], base["formulation"]["id"],
                                 component_scope=list(scope_b))
    return {**base, "mfr1": mfr1, "mfr2": mfr2, "grant1": grant1, "grant2": grant2}


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def approve_line_to_pilot(line_id, headers=None) -> dict:
    """Brand-review APPROVE: FORMULATION -> PILOT (freezes dilution cost)."""
    return get_success_data(api_client.brand_review(line_id, "APPROVE", headers or BM))


def setup_pilot_line(line_overrides=None, form_overrides=None) -> dict:
    """Compartmentalized formulation + brand-review APPROVE: line in PILOT.
    Returns the compartmentalized scenario plus the updated "line"."""
    sc = setup_compartmentalized_line(line_overrides, form_overrides)
    line = approve_line_to_pilot(sc["line"]["id"])
    return {**sc, "line": line}


def setup_launched_line(line_overrides=None, form_overrides=None,
                        pack_overrides=None, price_overrides=None) -> dict:
    """Full launch chain: PILOT line + pack TOOLED + price list + IN_PRODUCTION
    + launch. Returns the pilot scenario plus "pack" and "price_list", with
    "line" in LAUNCHED."""
    sc = setup_pilot_line(line_overrides, form_overrides)
    pack = create_tooled_pack(sc["line"]["id"], **(pack_overrides or {}))
    price_list = create_price_list_record(pack["id"], **(price_overrides or {}))
    pack = get_success_data(api_client.enter_production_pack_format(pack["id"], SP))
    line = get_success_data(api_client.launch_product_line(sc["line"]["id"], BM))
    return {**sc, "line": line, "pack": pack, "price_list": price_list}


def setup_active_coverage(launched=None, quota=1200, exclusive=False,
                          channels_served=("HARDWARE",),
                          window=(C.DEFAULT_COVERAGE_START, C.DEFAULT_COVERAGE_END),
                          channel="HARDWARE", market_overrides=None,
                          distributor_overrides=None) -> dict:
    """Launched line + market + APPROVED distributor + ACTIVE assignment.
    Returns the launched scenario plus "market", "distributor", "assignment"."""
    sc = launched or setup_launched_line()
    market = create_market(**(market_overrides or {}))
    distributor = create_approved_distributor(
        market["id"], channels_served=list(channels_served),
        **(distributor_overrides or {}))
    assignment = create_active_assignment(
        distributor["id"], market["id"], sc["line"]["id"],
        channel=channel, exclusive=exclusive,
        starts_on=window[0], ends_on=window[1], annual_quota_units=quota)
    return {**sc, "market": market, "distributor": distributor,
            "assignment": assignment}


def setup_submitted_promotion(scenario=None, promo_overrides=None,
                              creator_headers=None) -> dict:
    """Launched line + promotion submitted (PENDING_APPROVAL) by the creator.
    Returns the scenario plus "promotion"."""
    sc = scenario or setup_launched_line()
    promo = create_promotion_record(sc["line"]["id"],
                                    headers=creator_headers or PA,
                                    **(promo_overrides or {}))
    promo = get_success_data(api_client.submit_promotion(
        promo["id"], creator_headers or PA))
    return {**sc, "promotion": promo}


def setup_approved_promotion(scenario=None, promo_overrides=None,
                             creator_headers=None, approver_headers=None) -> dict:
    """Promotion approved (APPROVED, or LIVE when the window covers today).
    Approver differs from the creator (segregation of duties)."""
    sc = setup_submitted_promotion(scenario, promo_overrides, creator_headers)
    promo = get_success_data(api_client.approve_promotion(
        sc["promotion"]["id"], approver_headers or MM))
    return {**sc, "promotion": promo}


def setup_live_promotion(scenario=None, promo_overrides=None,
                         creator_headers=None, approver_headers=None) -> dict:
    """Promotion approved with a window covering the default clock date, so it
    enters LIVE immediately at approve. Returns scenario plus "promotion"."""
    window = {"starts_on": C.DEFAULT_COVERAGE_START, "ends_on": C.DEFAULT_COVERAGE_END}
    window.update(promo_overrides or {})
    return setup_approved_promotion(scenario, window,
                                    creator_headers, approver_headers)


def setup_active_registration(scenario=None, market_overrides=None,
                              registration_overrides=None,
                              registration_number="REG-DE-1001") -> dict:
    """Pilot (or launched) line + registration-required market + registration
    driven DRAFT -> SUBMITTED -> ACTIVE. Returns the scenario plus "market"
    and "registration"."""
    sc = scenario or setup_pilot_line()
    market_defaults = {
        "country_code": "DE", "name": "Germany",
        "registration_required": True,
        "allowed_channels": ["HARDWARE", "AUTOMOTIVE", "INDUSTRIAL", "MASS"],
    }
    market_defaults.update(market_overrides or {})
    market = create_market(**market_defaults)
    reg = create_market_registration_record(
        market["id"], sc["line"]["id"], sc["formulation"]["id"],
        **(registration_overrides or {}))
    reg = get_success_data(api_client.submit_market_registration(reg["id"], RA))
    reg = get_success_data(api_client.approve_market_registration(
        reg["id"], registration_number, RA))
    return {**sc, "market": market, "registration": reg}


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def file_reports(distributor_id, assignment_id, reports) -> list:
    """File several sell-through reports; each entry is a dict with
    period_month, units_sold and optional units_returned."""
    return [
        file_sell_through_report(
            distributor_id, assignment_id,
            period_month=rep["period_month"], units_sold=rep["units_sold"],
            units_returned=rep.get("units_returned"))
        for rep in reports
    ]


def setup_distributor_with_attainment(reports, quota=1200,
                                      channels_served=("HARDWARE",),
                                      exclusive=False) -> dict:
    """ACTIVE coverage plus a set of filed reports (drives attainment
    recomputation, possibly the SANCTION cascade). Returns the coverage
    scenario plus "reports"."""
    sc = setup_active_coverage(quota=quota, channels_served=channels_served,
                               exclusive=exclusive)
    filed = file_reports(sc["distributor"]["id"], sc["assignment"]["id"], reports)
    return {**sc, "reports": filed}


def setup_brand_with_open_cases(brand_id, market_id, severities) -> list:
    """File one open counterfeit case per severity; returns the cases."""
    return [create_counterfeit_case_record(brand_id, market_id, severity=sev)
            for sev in severities]


def setup_brand_at_posture(brand_id, market_id, posture) -> list:
    """Drive a brand to a target posture with open cases: ELEVATED via two
    severity-3 cases (sum 6), CRITICAL via one severity-5 case."""
    if posture == "NORMAL":
        return []
    if posture == "ELEVATED":
        return setup_brand_with_open_cases(brand_id, market_id, [3, 3])
    if posture == "CRITICAL":
        return setup_brand_with_open_cases(brand_id, market_id, [5])
    raise ValueError(f"unknown posture target: {posture!r}")


def create_flagged_use_cases(line_id, count, publish=True, start_index=1) -> list:
    """Create `count` use cases, VERIFY them with generic_use_flag true, and
    (optionally) publish each; returns the final submission dicts."""
    subs = []
    for i in range(start_index, start_index + count):
        ref = f"consumer-{i}"
        sub = create_use_case_record(line_id, submitter_ref=ref)
        sub = get_success_data(api_client.review_use_case(
            sub["id"], "VERIFY", True, MM))
        if publish:
            sub = get_success_data(api_client.publish_use_case(sub["id"], MM))
        subs.append(sub)
    return subs


# ---------------------------------------------------------------------------
# Tier 5: terminal-state fixtures
# ---------------------------------------------------------------------------

def setup_discontinued_line(scenario=None) -> dict:
    """A non-core line launched and then discontinued (DISCONTINUED).
    Returns the scenario with "line" in DISCONTINUED."""
    sc = scenario or setup_launched_line(
        line_overrides={"line_code": "EXT-1", "name": "Doomed Extension",
                        "is_core": False})
    line = get_success_data(api_client.discontinue_product_line(sc["line"]["id"], BM))
    return {**sc, "line": line}


def setup_terminated_distributor(scenario=None) -> dict:
    """Distributor terminated outright; PROPOSED assignments withdraw and
    ACTIVE/SUSPENDED ones terminate. Returns the scenario with "distributor"
    in TERMINATED."""
    sc = scenario or setup_active_coverage()
    dist = get_success_data(api_client.terminate_distributor(
        sc["distributor"]["id"], CM))
    return {**sc, "distributor": dist}
