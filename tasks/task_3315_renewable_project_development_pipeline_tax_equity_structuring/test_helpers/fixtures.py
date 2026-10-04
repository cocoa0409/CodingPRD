"""Composite setup helpers: multi-step state builders used by the test suite.

Every fixture builds its preconditions from scratch through the public API
(the runner restarts the server before each test, so each test starts against
an empty database). Setup calls use get_success_data() so setup failures
surface as clear errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_contribution_payload,
    create_interconnection_request_payload,
    create_milestone_payload,
    create_offtake_payload,
    create_partnership_payload,
    create_procurement_order_payload,
    create_project_payload,
    create_site_control_payload,
    create_study_payload,
    create_supply_agreement_payload,
)
from .test_users import (
    TEST_USERS,
    make_construction_manager_headers,
    make_tax_counsel_headers,
)

ADMIN = TEST_USERS["developer_admin_headers"]
ORIG = TEST_USERS["origination_manager_headers"]
PROC = TEST_USERS["procurement_lead_headers"]
TAX = TEST_USERS["tax_counsel_headers"]
INVESTOR = TEST_USERS["investor_manager_headers"]
LENDER = TEST_USERS["lender_agent_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]

# Segregation-of-duties ids: the milestone submitter and certifier differ.
CM_USER = "cm-1"
TC_USER = "tc-1"
CM_HEADERS = make_construction_manager_headers(CM_USER)
TC_HEADERS = make_tax_counsel_headers(TC_USER)

# Standard study windows (distinct per phase so no 5-day-buffer conflict).
STUDY_WINDOWS = {
    "FEASIBILITY": ("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z"),
    "SYSTEM_IMPACT": ("2026-11-06T00:00:00Z", "2026-12-15T00:00:00Z"),
    "FACILITIES": ("2027-01-05T00:00:00Z", "2027-02-15T00:00:00Z"),
}

# Standard milestone plan/work dates in sequence order.
MILESTONE_DATES = {
    "FOUNDATION": ("2027-03-01T00:00:00Z", "2027-03-01T00:00:00Z"),
    "ERECTION": ("2027-05-01T00:00:00Z", "2027-05-01T00:00:00Z"),
    "ENERGIZATION": ("2027-07-01T00:00:00Z", "2027-07-01T00:00:00Z"),
    "SUBSTANTIAL_COMPLETION": ("2027-09-01T00:00:00Z", "2027-09-01T00:00:00Z"),
    "COMMERCIAL_OPERATION": ("2027-11-01T00:00:00Z", "2027-11-01T00:00:00Z"),
}


def set_clock(to_iso8601: str) -> str:
    """Drive the logical clock to the supplied instant."""
    data = get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PLATFORM)
    )
    return data.get("current_utc", to_iso8601)


def create_project(**overrides):
    """Create a project. Returns the project dict."""
    return get_success_data(
        api_client.create_project(create_project_payload(**overrides), ADMIN)
    )


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, ADMIN))


def get_tcq(project_id):
    """Return the project's single tax credit qualification."""
    data = get_success_data(api_client.list_tax_credit_qualifications(project_id, TAX))
    entries = data if isinstance(data, list) else data.get("data", data)
    if isinstance(entries, dict):  # defensive: paginated shape
        entries = entries.get("data", [])
    assert len(entries) == 1, f"expected exactly one qualification, got {len(entries)}"
    return entries[0]


def transition_project(project_id, to, **extra):
    payload = {"to": to}
    payload.update(extra)
    return get_success_data(api_client.transition_project(project_id, payload, ADMIN))


def create_executed_instrument(project_id, parcel_id="PCL-F1",
                               start_date="2026-09-01T00:00:00Z",
                               end_date="2046-09-01T00:00:00Z"):
    """Create a site control instrument and execute it. Returns the instrument."""
    inst = get_success_data(
        api_client.create_site_control_instrument(
            project_id,
            create_site_control_payload(
                parcel_id=parcel_id, start_date=start_date, end_date=end_date
            ),
            ADMIN,
        )
    )
    return get_success_data(
        api_client.transition_site_control_instrument(inst["id"], {"to": "EXECUTED"}, ADMIN)
    )


def create_exercised_instrument(project_id, **kwargs):
    """Create + execute + exercise an instrument. Returns the instrument."""
    inst = create_executed_instrument(project_id, **kwargs)
    return get_success_data(
        api_client.transition_site_control_instrument(inst["id"], {"to": "EXERCISED"}, ADMIN)
    )


def site_secured_project(project_id, parcel_id="PCL-F1"):
    """Exercise an instrument and advance the project to SITE_SECURED."""
    create_exercised_instrument(project_id, parcel_id=parcel_id)
    return transition_project(project_id, "SITE_SECURED")


def create_interconnection_request(project_id, cluster_id, capacity_mw):
    return get_success_data(
        api_client.create_interconnection_request(
            project_id,
            create_interconnection_request_payload(
                cluster_id=cluster_id, requested_capacity_mw=capacity_mw
            ),
            ORIG,
        )
    )


def _run_accepted_study(request_id, phase):
    """Scope a study and drive it SCOPED -> IN_PROGRESS -> DELIVERED -> ACCEPTED."""
    window_start, window_end = STUDY_WINDOWS[phase]
    study = get_success_data(
        api_client.create_study(
            request_id,
            create_study_payload(
                phase=phase, window_start=window_start, window_end=window_end
            ),
            ORIG,
        )
    )
    for to in ("IN_PROGRESS", "DELIVERED", "ACCEPTED"):
        get_success_data(api_client.transition_study(study["id"], {"to": to}, ORIG))
    return study


def drive_request_to_agreement_executed(request_id, upgrade_total=900000):
    """Walk an interconnection request QUEUED -> AGREEMENT_EXECUTED.

    Runs accepted studies for each phase gate and a cluster upgrade cost
    allocation before entering FACILITIES_STUDY.
    """
    get_success_data(
        api_client.transition_interconnection_request(
            request_id, {"to": "FEASIBILITY_STUDY"}, ORIG
        )
    )
    _run_accepted_study(request_id, "FEASIBILITY")
    get_success_data(
        api_client.transition_interconnection_request(
            request_id, {"to": "SYSTEM_IMPACT_STUDY"}, ORIG
        )
    )
    _run_accepted_study(request_id, "SYSTEM_IMPACT")
    get_success_data(
        api_client.allocate_upgrade_costs(
            request_id, {"total_upgrade_cost_usd": upgrade_total}, PLATFORM
        )
    )
    get_success_data(
        api_client.transition_interconnection_request(
            request_id, {"to": "FACILITIES_STUDY"}, ORIG
        )
    )
    _run_accepted_study(request_id, "FACILITIES")
    return get_success_data(
        api_client.transition_interconnection_request(
            request_id, {"to": "AGREEMENT_EXECUTED"}, ORIG
        )
    )


def development_project(project_id, cluster_id, capacity_mw, upgrade_total=900000):
    """From SITE_SECURED: create an interconnection request, drive it to
    AGREEMENT_EXECUTED, and advance the project to DEVELOPMENT."""
    req = create_interconnection_request(project_id, cluster_id, capacity_mw)
    transition_project(project_id, "DEVELOPMENT")
    drive_request_to_agreement_executed(req["id"], upgrade_total=upgrade_total)
    return req


def create_effective_offtake(project_id, base_price_usd_mwh=45.00,
                             buyer_type="UTILITY", term_years=20,
                             escalator_pct=2.0):
    """Open an offtake negotiation with a fresh OCC version, then drive it to
    EXECUTED and EFFECTIVE. Returns the agreement."""
    version = get_project(project_id)["version"]
    agreement = get_success_data(
        api_client.create_offtake_agreement(
            project_id,
            create_offtake_payload(
                version,
                base_price_usd_mwh=base_price_usd_mwh,
                buyer_type=buyer_type,
                term_years=term_years,
                escalator_pct=escalator_pct,
            ),
            ORIG,
        )
    )
    get_success_data(
        api_client.transition_offtake_agreement(agreement["id"], {"to": "EXECUTED"}, ORIG)
    )
    return get_success_data(
        api_client.transition_offtake_agreement(agreement["id"], {"to": "EFFECTIVE"}, ORIG)
    )


def create_supply_agreement(project_id, **overrides):
    return get_success_data(
        api_client.create_supply_agreement(
            project_id, create_supply_agreement_payload(**overrides), PROC
        )
    )


def execute_supply_agreement(agreement_id):
    return get_success_data(
        api_client.transition_supply_agreement(agreement_id, {"to": "EXECUTED"}, PROC)
    )


def place_order(agreement_id, order_amount_usd, safe_harbor_method,
                eligible_cost_basis_usd, **overrides):
    return get_success_data(
        api_client.create_procurement_order(
            agreement_id,
            create_procurement_order_payload(
                order_amount_usd=order_amount_usd,
                safe_harbor_method=safe_harbor_method,
                eligible_cost_basis_usd=eligible_cost_basis_usd,
                **overrides,
            ),
            PROC,
        )
    )


def pay_deposit(order_id, amount_usd):
    return get_success_data(
        api_client.transition_procurement_order(
            order_id, {"to": "DEPOSIT_PAID", "deposit_amount_usd": amount_usd}, PROC
        )
    )


def place_order_paid(agreement_id, order_amount_usd, safe_harbor_method,
                     eligible_cost_basis_usd, deposit_usd, **overrides):
    """Place an order and pay a deposit. Returns the order (DEPOSIT_PAID)."""
    order = place_order(
        agreement_id, order_amount_usd, safe_harbor_method,
        eligible_cost_basis_usd, **overrides,
    )
    return pay_deposit(order["id"], deposit_usd)


def confirm_order(order_id, physical_work_evidence_uri=None):
    payload = {"to": "SAFE_HARBOR_QUALIFIED"}
    if physical_work_evidence_uri is not None:
        payload["physical_work_evidence_uri"] = physical_work_evidence_uri
    return get_success_data(
        api_client.transition_procurement_order(order_id, payload, PROC)
    )


def safe_harbor_project(project_id, order_amount_usd=2000000.00,
                        safe_harbor_method="FIVE_PERCENT_COST",
                        eligible_cost_basis_usd=2000000.00,
                        deposit_usd=120000.00,
                        supplier_domestic_content=False,
                        physical_work_evidence_uri=None):
    """Create + execute a supply agreement and drive one order to
    SAFE_HARBOR_QUALIFIED. Returns (supply_agreement, order)."""
    sa = create_supply_agreement(
        project_id, domestic_content_certified=supplier_domestic_content
    )
    execute_supply_agreement(sa["id"])
    order = place_order_paid(
        sa["id"], order_amount_usd, safe_harbor_method,
        eligible_cost_basis_usd, deposit_usd,
    )
    order = confirm_order(order["id"], physical_work_evidence_uri)
    return sa, order


def establish_tcq(project_id, continuity_variant="FOUR_YEAR_SAFE_HARBOR"):
    """Establish safe harbor on the project's qualification. Returns the TCQ."""
    tcq = get_tcq(project_id)
    return get_success_data(
        api_client.transition_tax_credit_qualification(
            tcq["id"],
            {"to": "SAFE_HARBOR_ESTABLISHED", "continuity_variant": continuity_variant},
            TAX,
        )
    )


def continuity_maintained_tcq(project_id, continuity_variant="FOUR_YEAR_SAFE_HARBOR"):
    """Establish safe harbor then assess continuity. Returns the TCQ."""
    tcq = establish_tcq(project_id, continuity_variant)
    return get_success_data(
        api_client.transition_tax_credit_qualification(
            tcq["id"], {"to": "CONTINUITY_MAINTAINED"}, TAX
        )
    )


def certify_milestone(project_id, sequence_no, milestone_type, planned_date=None,
                      work_date=None):
    """Plan a milestone, submit evidence, and certify it.

    Submitter (ConstructionManager cm-1) and certifier (TaxCounsel tc-1) are
    distinct users, satisfying segregation of duties. Returns the milestone.
    """
    if planned_date is None or work_date is None:
        planned_date, work_date = MILESTONE_DATES[milestone_type]
    milestone = get_success_data(
        api_client.create_milestone(
            project_id,
            create_milestone_payload(
                milestone_type=milestone_type,
                sequence_no=sequence_no,
                planned_date=planned_date,
            ),
            CM_HEADERS,
        )
    )
    get_success_data(
        api_client.submit_milestone_evidence(
            milestone["id"],
            {"evidence_uri": f"s3://ev/{project_id[:8]}-{sequence_no}",
             "work_date": work_date},
            CM_HEADERS,
        )
    )
    return get_success_data(
        api_client.certify_milestone(
            milestone["id"], {"decision": "CERTIFIED"}, TC_HEADERS
        )
    )


def certify_four_prerequisite_milestones(project_id):
    """Certify FOUNDATION, ERECTION, ENERGIZATION, SUBSTANTIAL_COMPLETION (seq 1-4)."""
    milestones = []
    for seq, mtype in enumerate(
        ("FOUNDATION", "ERECTION", "ENERGIZATION", "SUBSTANTIAL_COMPLETION"), start=1
    ):
        milestones.append(certify_milestone(project_id, seq, mtype))
    return milestones


def build_under_construction_project(name, cluster_id, capacity_mw,
                                     project_overrides=None,
                                     order_overrides=None):
    """Full chain to UNDER_CONSTRUCTION with the qualification in
    CONTINUITY_MAINTAINED. Returns (project, request, offtake, sa, order, tcq).
    """
    project = create_project(name=name, target_capacity_mw=capacity_mw,
                             **(project_overrides or {}))
    pid = project["id"]
    site_secured_project(pid, parcel_id=f"PCL-{cluster_id}")
    req = development_project(pid, cluster_id, capacity_mw)
    offtake = create_effective_offtake(pid)
    order_kwargs = order_overrides or {}
    sa, order = safe_harbor_project(pid, **order_kwargs)
    tcq = continuity_maintained_tcq(pid)
    transition_project(pid, "READY_FOR_CONSTRUCTION")
    project = transition_project(pid, "UNDER_CONSTRUCTION")
    return project, req, offtake, sa, order, tcq


def build_cod_project(name, cluster_id, capacity_mw,
                      project_overrides=None, order_overrides=None,
                      partnership=None, debt_facility=None):
    """Full chain through the COD cascade: project reaches COMMERCIAL_OPERATION.

    If ``partnership`` (dict of overrides for the partnership payload) is given,
    the partnership is created, commitment-executed, and fully funded before the
    COD milestone is certified, so the cascade moves it to PRE_FLIP_OPERATING.
    If ``debt_facility`` (dict of overrides) is given, a facility is created and
    drawn before COD so the cascade moves it to CONVERSION_PENDING.

    Returns a dict with keys: project, request, offtake, sa, order, tcq,
    cod_milestone, partnership (or None), facility (or None).
    """
    project, req, offtake, sa, order, tcq = build_under_construction_project(
        name, cluster_id, capacity_mw,
        project_overrides=project_overrides, order_overrides=order_overrides,
    )
    pid = project["id"]

    ps = None
    if partnership is not None:
        ps = get_success_data(
            api_client.create_partnership(
                pid, create_partnership_payload(**partnership), TAX
            )
        )
        get_success_data(
            api_client.transition_partnership(
                ps["id"], {"to": "COMMITMENT_EXECUTED"}, TAX
            )
        )
        get_success_data(
            api_client.post_contribution(
                ps["id"],
                create_contribution_payload(amount_usd=partnership["commitment_usd"]),
                INVESTOR,
            )
        )

    facility = None
    if debt_facility is not None:
        facility = get_success_data(
            api_client.create_debt_facility(
                pid, create_debt_facility_payload(**debt_facility), LENDER
            )
        )
        get_success_data(
            api_client.transition_debt_facility(
                facility["id"],
                {"to": "CONSTRUCTION_DRAWING",
                 "draw_amount_usd": debt_facility["draw_amount_usd"]},
                LENDER,
            )
        )

    certify_four_prerequisite_milestones(pid)
    transition_project(pid, "COMMISSIONING")
    cod_milestone = certify_milestone(pid, 5, "COMMERCIAL_OPERATION")

    project = get_project(pid)
    tcq = get_tcq(pid)
    if ps is not None:
        ps = get_success_data(api_client.get_partnership(ps["id"], TAX))
    if facility is not None:
        facility = get_success_data(api_client.get_debt_facility(facility["id"], LENDER))
    return {
        "project": project,
        "request": req,
        "offtake": offtake,
        "sa": sa,
        "order": order,
        "tcq": tcq,
        "cod_milestone": cod_milestone,
        "partnership": ps,
        "facility": facility,
    }


def create_certified_continuous_work(project_id, sequence_no, work_date):
    """Plan, submit, and certify a CONTINUOUS_WORK milestone."""
    return certify_milestone(
        project_id, sequence_no, "CONTINUOUS_WORK",
        planned_date=work_date, work_date=work_date,
    )


def post_distribution(partnership_id, amount_usd, period_end_date):
    return get_success_data(
        api_client.post_distribution(
            partnership_id,
            {"amount_usd": amount_usd, "period_end_date": period_end_date},
            TAX,
        )
    )
