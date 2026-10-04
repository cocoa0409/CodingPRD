"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so every precondition is built here from PRD-declared
endpoints only. Fixtures use get_success_data() (lenient) internally and
raise a clear "Setup failed" error when a setup call is rejected.

Return-shape convention: composite setup_* fixtures return a plain dict whose
keys are the built resources plus "operator_headers" (the entity-backed
Operator headers bound to the owning operator's id, ready for
ownership-gated calls). Single-resource helpers return the resource dict.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    set_clock_payload,
    create_operator_payload,
    create_engine_payload,
    create_flight_hour_report_payload,
    create_shop_visit_payload,
    create_agreement_payload,
    amend_agreement_payload,
    enroll_engine_payload,
    issue_billing_statement_payload,
    workscope_item,
    create_workscope_payload,
    create_part_requisition_payload,
    source_requisition_payload,
    create_spare_engine_payload,
    create_spare_engine_lease_payload,
    create_directive_payload,
)
from .test_users import TEST_USERS, make_operator_headers

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["contract_manager_headers"]
PLANNER = TEST_USERS["shop_planner_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


def _unwrap(resp, what):
    """Leniently unwrap a setup response; raise a clear error on failure."""
    if resp.status_code >= 400:
        raise AssertionError(
            f"Setup failed ({what}): HTTP {resp.status_code} {resp.text}"
        )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin). Returns the response data."""
    return _unwrap(
        api_client.set_clock(set_clock_payload(to_iso8601=to_iso8601), ADMIN),
        f"set_clock({to_iso8601})",
    )


# ---------------------------------------------------------------------------
# Master data (Tier 2 building blocks)
# ---------------------------------------------------------------------------

def create_operator(name="Fixture Air", iata_code="FA", credit_rating="B", **overrides):
    """Register an operator. Returns the Operator resource."""
    return _unwrap(
        api_client.create_operator(
            create_operator_payload(
                name=name, iata_code=iata_code, credit_rating=credit_rating, **overrides
            ),
            ADMIN,
        ),
        f"create_operator({iata_code})",
    )


def create_engine(
    operator,
    esn="ESN-F001",
    engine_model="CFM56-7B",
    base_severity_tier="BENIGN",
    llp_remaining_cycles=8000,
    **overrides,
):
    """Register an engine owned by `operator`. Returns the Engine resource."""
    return _unwrap(
        api_client.create_engine(
            create_engine_payload(
                operator_id=operator["id"],
                esn=esn,
                engine_model=engine_model,
                base_severity_tier=base_severity_tier,
                llp_remaining_cycles=llp_remaining_cycles,
                **overrides,
            ),
            ADMIN,
        ),
        f"create_engine({esn})",
    )


def create_spare_engine(
    spare_serial="SP-F1", engine_model="CFM56-7B", daily_lease_rate_usd=3000, **overrides
):
    """Register a spare engine (starts AVAILABLE). Returns the SpareEngine."""
    return _unwrap(
        api_client.create_spare_engine(
            create_spare_engine_payload(
                spare_serial=spare_serial,
                engine_model=engine_model,
                daily_lease_rate_usd=daily_lease_rate_usd,
                **overrides,
            ),
            ADMIN,
        ),
        f"create_spare_engine({spare_serial})",
    )


def create_directive(
    directive_ref="AD-2026-0001",
    directive_type="AD",
    applicability_model="CFM56-7B",
    mandatory=True,
    estimated_cost_usd=100000,
    compliance_cycles=50,
    **overrides,
):
    """Issue a directive (append-only). Returns the Directive resource.

    Pass compliance_cycles=None with compliance_date=... for a purely
    date-bound directive.
    """
    payload = create_directive_payload(
        directive_ref=directive_ref,
        directive_type=directive_type,
        applicability_model=applicability_model,
        mandatory=mandatory,
        estimated_cost_usd=estimated_cost_usd,
        compliance_cycles=compliance_cycles,
        **overrides,
    )
    if compliance_cycles is None:
        payload.pop("compliance_cycles", None)
    return _unwrap(
        api_client.create_directive(payload, ADMIN),
        f"create_directive({directive_ref})",
    )


# ---------------------------------------------------------------------------
# Agreement lifecycle (Tier 1 state progression)
# ---------------------------------------------------------------------------

def create_agreement(**overrides):
    """Draft a ServiceAgreement (status DRAFT, version 1)."""
    return _unwrap(
        api_client.create_agreement(create_agreement_payload(**overrides), MANAGER),
        f"create_agreement({overrides.get('contract_ref', 'LTSA-F001')})",
    )


def activate_agreement(agreement):
    """DRAFT -> ACTIVE. Returns the activated agreement."""
    return _unwrap(
        api_client.activate_agreement(agreement["id"], MANAGER),
        f"activate_agreement({agreement['id']})",
    )


def create_active_agreement(**overrides):
    """Create + activate. Returns the ACTIVE agreement (version 2)."""
    return activate_agreement(create_agreement(**overrides))


def open_renegotiation(agreement):
    """ACTIVE -> RENEGOTIATION. Returns the updated agreement."""
    return _unwrap(
        api_client.open_renegotiation(agreement["id"], MANAGER),
        f"open_renegotiation({agreement['id']})",
    )


def amend_agreement(agreement_id, expected_agreement_version, **terms):
    """RENEGOTIATION -> ACTIVE applying amended terms (OCC-guarded)."""
    return _unwrap(
        api_client.amend_agreement(
            agreement_id,
            amend_agreement_payload(expected_agreement_version, **terms),
            MANAGER,
        ),
        f"amend_agreement({agreement_id})",
    )


def get_agreement(agreement_id):
    """Re-read one agreement."""
    return _unwrap(api_client.get_agreement(agreement_id, FINANCE), "get_agreement")


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

def enroll_engine(agreement, engine, assumed_annual_hours=2400, assumed_cycles_per_month=100):
    """Enroll an engine into an ACTIVE agreement. Returns the updated Engine
    (agreement_id set, assumptions recorded, projected_next_removal_date
    computed, version bumped)."""
    return _unwrap(
        api_client.enroll_engine(
            agreement["id"],
            enroll_engine_payload(
                engine["id"],
                assumed_annual_hours=assumed_annual_hours,
                assumed_cycles_per_month=assumed_cycles_per_month,
            ),
            MANAGER,
        ),
        f"enroll_engine({engine['id']})",
    )


def setup_enrolled_engine(
    credit_rating="B",
    esn="ESN-F001",
    engine_model="CFM56-7B",
    base_severity_tier="BENIGN",
    llp_remaining_cycles=8000,
    assumed_annual_hours=2400,
    assumed_cycles_per_month=100,
    operator_overrides=None,
    agreement_overrides=None,
    engine_overrides=None,
):
    """Operator + engine + ACTIVE agreement + enrolled engine.

    Returns {
        "operator": Operator, "engine": Engine (enrolled),
        "agreement": ServiceAgreement (ACTIVE),
        "operator_headers": dict  # bound to operator["id"]
    }.
    """
    op_kw = {"credit_rating": credit_rating}
    if operator_overrides:
        op_kw.update(operator_overrides)
    operator = create_operator(**op_kw)
    eng_kw = {
        "esn": esn,
        "engine_model": engine_model,
        "base_severity_tier": base_severity_tier,
        "llp_remaining_cycles": llp_remaining_cycles,
    }
    if engine_overrides:
        eng_kw.update(engine_overrides)
    engine = create_engine(operator, **eng_kw)
    agreement = create_active_agreement(**(agreement_overrides or {}))
    engine = enroll_engine(
        agreement,
        engine,
        assumed_annual_hours=assumed_annual_hours,
        assumed_cycles_per_month=assumed_cycles_per_month,
    )
    return {
        "operator": operator,
        "engine": engine,
        "agreement": agreement,
        "operator_headers": make_operator_headers(operator["id"]),
    }


def setup_enrolled_engines(
    engine_specs,
    credit_rating="B",
    operator_overrides=None,
    agreement_overrides=None,
):
    """One operator + one ACTIVE agreement + N enrolled engines.

    engine_specs: list of dicts, each with keys esn and optional
    engine_model / base_severity_tier / llp_remaining_cycles /
    assumed_annual_hours / assumed_cycles_per_month.

    Returns {"operator", "agreement", "engines": [Engine, ...],
             "operator_headers"}.
    """
    op_kw = {"credit_rating": credit_rating}
    if operator_overrides:
        op_kw.update(operator_overrides)
    operator = create_operator(**op_kw)
    agreement = create_active_agreement(**(agreement_overrides or {}))
    engines = []
    for spec in engine_specs:
        spec = dict(spec)
        assumed_hours = spec.pop("assumed_annual_hours", 2400)
        assumed_cpm = spec.pop("assumed_cycles_per_month", 100)
        engine = create_engine(operator, **spec)
        engines.append(
            enroll_engine(
                agreement,
                engine,
                assumed_annual_hours=assumed_hours,
                assumed_cycles_per_month=assumed_cpm,
            )
        )
    return {
        "operator": operator,
        "agreement": agreement,
        "engines": engines,
        "operator_headers": make_operator_headers(operator["id"]),
    }


# ---------------------------------------------------------------------------
# Flight-hour reports (Tier 4 accumulation helpers)
# ---------------------------------------------------------------------------

def submit_report(engine, operator_headers, period="2026-09", flight_hours=100,
                  cycles=40, observed_severity="BENIGN", **overrides):
    """Operator submits a monthly report for an enrolled, in-service engine.
    Returns the SUBMITTED FlightHourReport."""
    return _unwrap(
        api_client.submit_flight_hour_report(
            engine["id"],
            create_flight_hour_report_payload(
                period=period,
                flight_hours=flight_hours,
                cycles=cycles,
                observed_severity=observed_severity,
                **overrides,
            ),
            operator_headers,
        ),
        f"submit_report({engine['id']}, {period})",
    )


def verify_report(report):
    """FinanceController verifies a SUBMITTED report. Returns the VERIFIED
    report (verification fires the engine/forecast/lease cascade)."""
    return _unwrap(
        api_client.verify_flight_hour_report(report["id"], FINANCE),
        f"verify_report({report['id']})",
    )


def submit_and_verify_report(engine, operator_headers, **overrides):
    """Submit + verify one report. Returns the VERIFIED report."""
    return verify_report(submit_report(engine, operator_headers, **overrides))


def submit_history(engine, operator_headers, entries, verify=True):
    """Submit (and optionally verify) a series of monthly reports.

    entries: list of (period, flight_hours, cycles, observed_severity)
    tuples, or dicts with those keys. Returns the list of report resources
    in entry order. Use to build the verified utilization history that the
    12-month look-back window of the band-ratio reads.
    """
    reports = []
    for entry in entries:
        if isinstance(entry, dict):
            kw = dict(entry)
        else:
            period, hours, cycles, severity = entry
            kw = {
                "period": period,
                "flight_hours": hours,
                "cycles": cycles,
                "observed_severity": severity,
            }
        report = submit_report(engine, operator_headers, **kw)
        reports.append(verify_report(report) if verify else report)
    return reports


# ---------------------------------------------------------------------------
# Shop visits (Tier 1 state progression + Tier 3 lifecycle)
# ---------------------------------------------------------------------------

def create_visit(engine, operator_headers, planned_induction_date="2026-09-01T00:00:00Z"):
    """Operator schedules a shop visit; the server computes the forecast.
    Returns the SCHEDULED ShopVisit."""
    return _unwrap(
        api_client.create_shop_visit(
            engine["id"],
            create_shop_visit_payload(planned_induction_date=planned_induction_date),
            operator_headers,
        ),
        f"create_visit({engine['id']})",
    )


def induct_visit(visit):
    """SCHEDULED -> INDUCTED (ShopPlanner; daily capacity 2 applies).
    Returns the INDUCTED visit."""
    return _unwrap(
        api_client.induct_shop_visit(visit["id"], PLANNER),
        f"induct_visit({visit['id']})",
    )


def complete_visit(visit):
    """INDUCTED -> COMPLETED (compliance gate + no open requisitions).
    Returns the COMPLETED visit."""
    return _unwrap(
        api_client.complete_shop_visit(visit["id"], PLANNER),
        f"complete_visit({visit['id']})",
    )


def get_shop_visit(visit_id):
    """Re-read one shop visit (fresh forecast, committed cost, version)."""
    return _unwrap(api_client.get_shop_visit(visit_id, PLANNER), "get_shop_visit")


def get_visit_version(visit_id):
    """Current OCC version of a visit — read fresh before drafting the next
    workscope version."""
    return get_shop_visit(visit_id)["version"]


def setup_scheduled_visit(fx, planned_induction_date="2026-09-01T00:00:00Z"):
    """setup_enrolled_engine output + one SCHEDULED visit.
    Returns fx plus "visit"."""
    visit = create_visit(fx["engine"], fx["operator_headers"], planned_induction_date)
    return {**fx, "visit": visit}


def setup_inducted_visit(fx, planned_induction_date="2026-09-01T00:00:00Z"):
    """setup_enrolled_engine output + one INDUCTED visit.
    Returns fx plus "visit" (INDUCTED)."""
    visit = create_visit(fx["engine"], fx["operator_headers"], planned_induction_date)
    visit = induct_visit(visit)
    return {**fx, "visit": visit}


# ---------------------------------------------------------------------------
# Workscopes (Tier 3 lifecycle)
# ---------------------------------------------------------------------------

def create_workscope_version(visit_id, items=None, expected_shop_visit_version=None):
    """Create the next workscope version for an INDUCTED visit.

    When expected_shop_visit_version is None the visit's current version is
    read fresh (the OCC guard). items defaults to one MODULE_OVERHAUL item
    restoring 8000 cycles (passes the 18-month life floor for a 100
    cycles/month engine). Returns the SUBMITTED Workscope.
    """
    if expected_shop_visit_version is None:
        expected_shop_visit_version = get_visit_version(visit_id)
    return _unwrap(
        api_client.create_workscope(
            visit_id,
            create_workscope_payload(expected_shop_visit_version, items=items),
            PLANNER,
        ),
        f"create_workscope_version({visit_id})",
    )


def approve_workscope(workscope, operator_headers):
    """SUBMITTED -> APPROVED (Operator; cost-cap gate). Returns the Workscope."""
    return _unwrap(
        api_client.approve_workscope(workscope["id"], operator_headers),
        f"approve_workscope({workscope['id']})",
    )


def reject_workscope(workscope, operator_headers):
    """SUBMITTED -> REJECTED (Operator). Returns the Workscope."""
    return _unwrap(
        api_client.reject_workscope(workscope["id"], operator_headers),
        f"reject_workscope({workscope['id']})",
    )


def get_workscope(workscope_id):
    """Re-read one workscope version."""
    return _unwrap(api_client.get_workscope(workscope_id, PLANNER), "get_workscope")


def setup_submitted_workscope(fx, planned_induction_date="2026-09-01T00:00:00Z",
                              items=None):
    """Enrolled engine + INDUCTED visit + one SUBMITTED workscope.
    Returns fx plus "visit" and "workscope"."""
    fx = setup_inducted_visit(fx, planned_induction_date)
    workscope = create_workscope_version(fx["visit"]["id"], items=items)
    return {**fx, "workscope": workscope}


def setup_approved_workscope(fx, planned_induction_date="2026-09-01T00:00:00Z",
                             items=None):
    """Enrolled engine + INDUCTED visit + one APPROVED workscope.
    Returns fx plus "visit" and "workscope" (APPROVED)."""
    fx = setup_submitted_workscope(fx, planned_induction_date, items=items)
    workscope = approve_workscope(fx["workscope"], fx["operator_headers"])
    return {**fx, "workscope": workscope}


def setup_completed_visit(fx, planned_induction_date="2026-09-01T00:00:00Z",
                          items=None):
    """Full visit lifecycle through COMPLETED (Tier 5): enrolled engine +
    INDUCTED visit + APPROVED workscope + completion (engine returns
    IN_SERVICE with the LLP restoration applied).
    Returns fx plus "visit" (COMPLETED) and "workscope" (APPROVED)."""
    fx = setup_approved_workscope(fx, planned_induction_date, items=items)
    visit = complete_visit(fx["visit"])
    return {**fx, "visit": visit}


# ---------------------------------------------------------------------------
# Part requisitions and sourcing
# ---------------------------------------------------------------------------

def create_requisition(workscope, part_number="PN-F1", quantity=1,
                       list_price_usd=5000, requested_class="NEW",
                       required_by_date="2026-10-01T00:00:00Z", **overrides):
    """Demand a part on an APPROVED workscope. Returns the REQUESTED
    PartRequisition."""
    return _unwrap(
        api_client.create_part_requisition(
            workscope["id"],
            create_part_requisition_payload(
                part_number=part_number,
                quantity=quantity,
                list_price_usd=list_price_usd,
                requested_class=requested_class,
                required_by_date=required_by_date,
                **overrides,
            ),
            PLANNER,
        ),
        f"create_requisition({part_number})",
    )


def source_requisition(requisition, override=None):
    """Run the sourcing selector on a requisition.

    override=None -> ShopPlanner run (no override field sent);
    override=True -> ContractManager override run (lead time bypassed,
    allowed-class list still enforced). Returns the PartRequisition.
    """
    headers = MANAGER if override else PLANNER
    return _unwrap(
        api_client.source_part_requisition(
            requisition["id"], headers, source_requisition_payload(override)
        ),
        f"source_requisition({requisition['id']}, override={override})",
    )


# ---------------------------------------------------------------------------
# Spare engine leasing (Tier 2/5)
# ---------------------------------------------------------------------------

def create_lease(spare_engine, visit, operator_headers,
                 start_date="2026-09-01T00:00:00Z",
                 end_date="2026-10-01T00:00:00Z", **overrides):
    """Reserve a spare for a visit's aircraft-on-ground window (half-open
    [start, end); overlap and model match enforced). Returns the RESERVED
    SpareEngineLease with lease_cost_usd and deposit_usd fixed."""
    return _unwrap(
        api_client.create_spare_engine_lease(
            create_spare_engine_lease_payload(
                spare_engine_id=spare_engine["id"],
                shop_visit_id=visit["id"],
                start_date=start_date,
                end_date=end_date,
                **overrides,
            ),
            operator_headers,
        ),
        f"create_lease({spare_engine['id']}, {visit['id']})",
    )


def activate_lease(lease, operator_headers):
    """RESERVED -> ACTIVE (clock inside window; visit SCHEDULED/INDUCTED;
    spare AVAILABLE). Returns the ACTIVE lease."""
    return _unwrap(
        api_client.activate_spare_engine_lease(lease["id"], operator_headers),
        f"activate_lease({lease['id']})",
    )


def return_lease(lease, operator_headers):
    """ACTIVE -> RETURNED; the spare becomes AVAILABLE again."""
    return _unwrap(
        api_client.return_spare_engine_lease(lease["id"], operator_headers),
        f"return_lease({lease['id']})",
    )


def setup_reserved_lease(
    fx,
    planned_induction_date="2026-09-01T00:00:00Z",
    lease_start="2026-09-01T00:00:00Z",
    lease_end="2026-12-01T00:00:00Z",
    spare_serial="SP-F1",
    daily_lease_rate_usd=3000,
    engine_model="CFM56-7B",
):
    """Enrolled engine + SCHEDULED visit + spare engine + RESERVED lease.
    Returns fx plus "visit", "spare_engine", "lease"."""
    fx = setup_scheduled_visit(fx, planned_induction_date)
    spare = create_spare_engine(
        spare_serial=spare_serial,
        engine_model=engine_model,
        daily_lease_rate_usd=daily_lease_rate_usd,
    )
    lease = create_lease(
        spare, fx["visit"], fx["operator_headers"], lease_start, lease_end
    )
    return {**fx, "spare_engine": spare, "lease": lease}


# ---------------------------------------------------------------------------
# Billing and contract accounting (Tier 5)
# ---------------------------------------------------------------------------

def issue_statement(agreement, period="2026-09"):
    """Issue the PROVISIONAL statement for an ACTIVE agreement (SUBMITTED +
    VERIFIED reports). Returns the ISSUED BillingStatement."""
    return _unwrap(
        api_client.issue_billing_statement(
            agreement["id"], issue_billing_statement_payload(period=period), FINANCE
        ),
        f"issue_statement({agreement['id']}, {period})",
    )


def settle_statement(statement):
    """ISSUED -> SETTLED; recomputes with VERIFIED reports only and records
    final_total_usd / adjustment_usd. Returns the SETTLED statement."""
    return _unwrap(
        api_client.settle_billing_statement(statement["id"], FINANCE),
        f"settle_statement({statement['id']})",
    )


def issue_and_settle_statement(agreement, period="2026-09"):
    """Issue then settle one statement. Returns the SETTLED statement."""
    return settle_statement(issue_statement(agreement, period))


def create_recognition_snapshot(agreement):
    """Append a contract-accounting snapshot to an agreement. Returns the
    RecognitionSnapshot (append-only: id + created_at + computed figures)."""
    return _unwrap(
        api_client.create_recognition_snapshot(agreement["id"], FINANCE),
        f"create_recognition_snapshot({agreement['id']})",
    )


# ---------------------------------------------------------------------------
# Convenience re-exports for item construction inside tests
# ---------------------------------------------------------------------------

__all__ = [
    "set_clock",
    "create_operator",
    "create_engine",
    "create_spare_engine",
    "create_directive",
    "create_agreement",
    "activate_agreement",
    "create_active_agreement",
    "open_renegotiation",
    "amend_agreement",
    "get_agreement",
    "enroll_engine",
    "setup_enrolled_engine",
    "setup_enrolled_engines",
    "submit_report",
    "verify_report",
    "submit_and_verify_report",
    "submit_history",
    "create_visit",
    "induct_visit",
    "complete_visit",
    "get_shop_visit",
    "get_visit_version",
    "setup_scheduled_visit",
    "setup_inducted_visit",
    "create_workscope_version",
    "approve_workscope",
    "reject_workscope",
    "get_workscope",
    "setup_submitted_workscope",
    "setup_approved_workscope",
    "setup_completed_visit",
    "create_requisition",
    "source_requisition",
    "create_lease",
    "activate_lease",
    "return_lease",
    "setup_reserved_lease",
    "issue_statement",
    "settle_statement",
    "issue_and_settle_statement",
    "create_recognition_snapshot",
    "workscope_item",
]
