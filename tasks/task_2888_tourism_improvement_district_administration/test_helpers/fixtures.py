"""Composite state builders.

Every builder here reaches its state exclusively through the declared endpoints
of PRD 4 — nothing is preloaded, seeded or written behind the API — so a suite
running under a per-test server rebuilds whatever it needs from scratch.

The builders are plain functions rather than pytest fixtures so that a test can
compose them, stop part way, or vary one input of a long chain.  They all take
the client as their first argument and thread a :class:`Ctx` of identifiers.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_ORIGIN
from .test_users import ADMIN, AUDITOR, BOARD_MEMBER, BOARD_MEMBER_2, DMO_LIAISON
from .test_users import HEARING_OFFICER, operator_headers


class Ctx(dict):
    """A bag of identifiers threaded through a build chain.

    Attribute access is provided so a test body reads ``ctx.st1_id`` rather than
    ``ctx["st1_id"]``.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - developer error
            raise AttributeError(
                "%r is not in this context; it holds %s" % (name, sorted(self))
            ) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def _data(response, expected_status: int = 200) -> Dict[str, Any]:
    """Unwrap a setup response leniently.

    Setup calls are not the subject of any assertion, so any 2xx is accepted
    here: the exact status code of a write is asserted in the test bodies that
    are actually about it, and never smuggled into a build chain.  The
    ``expected_status`` argument is retained so a chain still documents which
    code it expects.
    """
    return get_success_data(response)


# --------------------------------------------------------------------------
# The logical clock (PRD 2.4)
# --------------------------------------------------------------------------
def set_clock(api: ApiClient, instant: str) -> None:
    """Move the logical clock to an explicit instant."""
    _data(api.set_clock(instant, headers=ADMIN))


def pin_clock_to_origin(api: ApiClient) -> None:
    """Pin the clock to the instant it reads before any client sets it, so a
    chain starts from the same place however the server was left."""
    set_clock(api, CLOCK_ORIGIN)


# --------------------------------------------------------------------------
# District and roll (PRD 3.1)
# --------------------------------------------------------------------------
def create_district(api: ApiClient, ctx: Optional[Ctx] = None, **overrides: Any) -> Ctx:
    """Propose the Harbor Bay district.  It lands in PROPOSED."""
    ctx = ctx if ctx is not None else Ctx()
    district = _data(
        api.create_district(f.district_payload(**overrides), headers=ADMIN), 201
    )
    ctx.district = district
    ctx.d_id = district["id"]
    return ctx


def add_business(api: ApiClient, ctx: Ctx, payload: Dict[str, Any], key: str) -> Ctx:
    """Add one property to the roll and remember its id under ``key``."""
    business = _data(api.create_lodging_business(payload, headers=ADMIN), 201)
    ctx[key] = business["id"]
    ctx[key + "_record"] = business
    return ctx


def add_roll(api: ApiClient, ctx: Ctx) -> Ctx:
    """Add the four Harbor Bay properties: two core and two perimeter, one per
    classification, giving an assessable pool of four."""
    add_business(api, ctx, f.harbor_grand_payload(ctx.d_id), "b1_id")
    add_business(api, ctx, f.bayside_inn_payload(ctx.d_id), "b2_id")
    add_business(api, ctx, f.lighthouse_boutique_payload(ctx.d_id), "b3_id")
    add_business(api, ctx, f.cove_cottages_payload(ctx.d_id), "b4_id")
    return ctx


def district_with_roll(api: ApiClient, **overrides: Any) -> Ctx:
    """A PROPOSED district carrying the four-property Harbor Bay roll."""
    pin_clock_to_origin(api)
    ctx = create_district(api, **overrides)
    return add_roll(api, ctx)


# --------------------------------------------------------------------------
# Petition circulation (PRD 3.2)
# --------------------------------------------------------------------------
def open_formation_drive(
    api: ApiClient, ctx: Ctx, closes_at: str = "2026-09-01T00:00:00Z"
) -> Ctx:
    """Open a FORMATION drive, which moves the district PROPOSED to
    PETITION_CIRCULATING."""
    drive = _data(
        api.create_petition_drive(
            f.petition_drive_payload(ctx.d_id, "FORMATION", closes_at), headers=ADMIN
        ),
        201,
    )
    ctx.pd_id = drive["id"]
    ctx.drive = drive
    return ctx


def open_renewal_drive(
    api: ApiClient, ctx: Ctx, closes_at: str
) -> Ctx:
    """Open a RENEWAL drive on a district inside its renewal window."""
    drive = _data(
        api.create_petition_drive(
            f.petition_drive_payload(ctx.d_id, "RENEWAL", closes_at), headers=ADMIN
        ),
        201,
    )
    ctx.renewal_pd_id = drive["id"]
    return ctx


def sign(
    api: ApiClient,
    ctx: Ctx,
    business_key: str,
    drive_key: str = "pd_id",
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """Record one signature, remembering its id as ``sig_<business_key>``."""
    business_id = ctx[business_key]
    signature = _data(
        api.sign_petition(
            ctx[drive_key],
            f.signature_payload(business_id),
            headers=headers if headers is not None else ADMIN,
        ),
        201,
    )
    ctx["sig_" + business_key.replace("_id", "")] = signature["id"]
    return signature["id"]


def tally(api: ApiClient, ctx: Ctx, drive_key: str = "pd_id") -> Dict[str, Any]:
    """Tally a drive: recompute support and compare it against the snapshotted
    thresholds."""
    drive = _data(api.tally_petition_drive(ctx[drive_key], headers=ADMIN))
    ctx.drive = drive
    return drive


def certify(
    api: ApiClient,
    ctx: Ctx,
    drive_key: str = "pd_id",
    certified_on: str = "2026-08-01T00:00:00Z",
) -> Dict[str, Any]:
    """Certify a QUALIFIED drive, which stamps the district's term."""
    drive = _data(
        api.certify_petition_drive(
            ctx[drive_key], f.certification_payload(certified_on), headers=ADMIN
        )
    )
    ctx.drive = drive
    return drive


def advance_district(
    api: ApiClient,
    ctx: Ctx,
    to_status: str,
    effective_on: Any = "2026-08-01T00:00:00Z",
    reason: Any = ...,
) -> Dict[str, Any]:
    """Drive the district lifecycle to the named status."""
    district = _data(
        api.advance_district_lifecycle(
            ctx.d_id,
            f.lifecycle_advance_payload(to_status, effective_on, reason),
            headers=ADMIN,
        )
    )
    ctx.district = district
    return district


def formed_district(api: ApiClient, **overrides: Any) -> Ctx:
    """A FORMED district: four properties on the roll, a formation drive signed
    by the core full-service property, tallied qualified and certified."""
    ctx = district_with_roll(api, **overrides)
    open_formation_drive(api, ctx)
    sign(api, ctx, "b1_id")
    tally(api, ctx)
    certify(api, ctx)
    return ctx


def active_district(api: ApiClient, **overrides: Any) -> Ctx:
    """An ACTIVE district, which is the state every assessment workflow needs."""
    ctx = formed_district(api, **overrides)
    advance_district(api, ctx, "ACTIVE")
    return ctx


# --------------------------------------------------------------------------
# Assessment periods and statements (PRD 3.3)
# --------------------------------------------------------------------------
def open_period(api: ApiClient, ctx: Ctx, key: str = "ap_id", **overrides: Any) -> Ctx:
    """Open an assessment period on the district."""
    period = _data(
        api.create_assessment_period(
            f.assessment_period_payload(ctx.d_id, **overrides), headers=ADMIN
        ),
        201,
    )
    ctx[key] = period["id"]
    ctx.period = period
    return ctx


def generate_statements(api: ApiClient, ctx: Ctx, period_key: str = "ap_id") -> Dict[str, Any]:
    """Issue one statement per eligible property in a single pass."""
    summary = _data(api.generate_statements(ctx[period_key], headers=ADMIN), 201)
    ctx.generation_summary = summary
    return summary


def index_statements(api: ApiClient, ctx: Ctx, period_key: str = "ap_id") -> Dict[str, str]:
    """Read the period's statements and remember each one under the key of the
    property it bills: ``st_b1_id`` and so on, plus ``st1_id``/``st2_id`` for
    the two properties the chains file for."""
    listing = _data(api.list_period_statements(ctx[period_key], headers=ADMIN))
    by_business = {row["lodging_business_id"]: row for row in listing}
    ctx.statements_by_business = by_business
    for key in ("b1_id", "b2_id", "b3_id", "b4_id"):
        business_id = ctx.get(key)
        if business_id in by_business:
            ctx["st_" + key.replace("_id", "") + "_id"] = by_business[business_id]["id"]
    if "st_b1_id" in ctx:
        ctx.st1_id = ctx.st_b1_id
    if "st_b2_id" in ctx:
        ctx.st2_id = ctx.st_b2_id
    if "st_b3_id" in ctx:
        ctx.st3_id = ctx.st_b3_id
    if "st_b4_id" in ctx:
        ctx.st4_id = ctx.st_b4_id
    return {k: v["id"] for k, v in by_business.items()}


def period_with_statements(api: ApiClient, **overrides: Any) -> Ctx:
    """An ACTIVE district with an OPEN period holding one statement per property."""
    ctx = active_district(api, **overrides)
    open_period(api, ctx)
    generate_statements(api, ctx)
    index_statements(api, ctx)
    return ctx


def file_statement(
    api: ApiClient,
    ctx: Ctx,
    statement_key: str,
    business_key: str,
    reported_room_nights: int,
    reported_gross_room_revenue_cents: int,
) -> Dict[str, Any]:
    """File a statement as the owning operator."""
    statement = _data(
        api.file_statement(
            ctx[statement_key],
            f.filing_payload(reported_room_nights, reported_gross_room_revenue_cents),
            headers=operator_headers(ctx[business_key]),
        )
    )
    ctx[statement_key.replace("_id", "") + "_filed"] = statement
    return statement


def statements_filed(api: ApiClient, **overrides: Any) -> Ctx:
    """The canonical filed pair: the core full-service property reports 2000
    nights on 41225000 cents of revenue, the core limited-service property 600
    nights on 20000000 cents."""
    ctx = period_with_statements(api, **overrides)
    ctx.st1_filed = file_statement(api, ctx, "st1_id", "b1_id", 2000, 41225000)
    ctx.st2_filed = file_statement(api, ctx, "st2_id", "b2_id", 600, 20000000)
    return ctx


def close_period(api: ApiClient, ctx: Ctx, period_key: str = "ap_id") -> Dict[str, Any]:
    """Close an OPEN period once the clock has reached its period_end."""
    period = _data(api.close_assessment_period(ctx[period_key], headers=ADMIN))
    ctx.period = period
    return period


def sweep_period(api: ApiClient, ctx: Ctx, period_key: str = "ap_id") -> Dict[str, Any]:
    """Sweep a CLOSED period for delinquency."""
    period = _data(api.sweep_delinquency(ctx[period_key], headers=ADMIN))
    ctx.period = period
    return period


# --------------------------------------------------------------------------
# Annual work plans (PRD 3.7)
# --------------------------------------------------------------------------
def draft_work_plan(
    api: ApiClient,
    ctx: Ctx,
    fiscal_year: int = 2027,
    expenditure_lines: Optional[List[Dict[str, Any]]] = None,
    key: str = "wp_id",
) -> Dict[str, Any]:
    """Draft the annual budget.  A DRAFT plan may hold any category mix at all."""
    plan = _data(
        api.create_work_plan(
            f.work_plan_payload(ctx.d_id, fiscal_year, expenditure_lines), headers=ADMIN
        ),
        201,
    )
    ctx[key] = plan["id"]
    ctx.plan = plan
    return plan


def sponsor_work_plan(api: ApiClient, ctx: Ctx, plan_key: str = "wp_id", headers=None) -> Dict[str, Any]:
    """SPONSOR moves a DRAFT plan to BOARD_REVIEW."""
    plan = _data(
        api.board_action(
            ctx[plan_key],
            f.board_action_payload("SPONSOR", "sponsored for the fiscal 2027 board cycle"),
            headers=headers if headers is not None else BOARD_MEMBER,
        )
    )
    ctx.plan = plan
    return plan


def approve_work_plan(api: ApiClient, ctx: Ctx, plan_key: str = "wp_id", headers=None) -> Dict[str, Any]:
    """APPROVE moves a BOARD_REVIEW plan to APPROVED.  A second board member acts,
    because approval requires an X-User-ID different from the sponsor's."""
    plan = _data(
        api.board_action(
            ctx[plan_key],
            f.board_action_payload("APPROVE", "approved at the board meeting"),
            headers=headers if headers is not None else BOARD_MEMBER_2,
        )
    )
    ctx.plan = plan
    ctx.wp_version = plan["version"]
    return plan


def approved_work_plan(
    api: ApiClient,
    ctx: Ctx,
    fiscal_year: int = 2027,
    expenditure_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A plan drafted, sponsored and approved, which is what funds a program."""
    draft_work_plan(api, ctx, fiscal_year, expenditure_lines)
    sponsor_work_plan(api, ctx)
    return approve_work_plan(api, ctx)


# --------------------------------------------------------------------------
# Destination marketing coordination (PRD 3.1)
# --------------------------------------------------------------------------
def execute_dmo_agreement(api: ApiClient, ctx: Ctx, **overrides: Any) -> Dict[str, Any]:
    """Record the agreement as EXECUTED, which is the cross-entity gate that lets
    marketing programs launch at all."""
    district = _data(
        api.record_dmo_coordination(
            ctx.d_id, f.dmo_coordination_payload(**overrides), headers=ADMIN
        )
    )
    ctx.district = district
    return district


# --------------------------------------------------------------------------
# Marketing programs and claims (PRD 3.8)
# --------------------------------------------------------------------------
def create_program(
    api: ApiClient, ctx: Ctx, plan_key: str = "wp_id", key: str = "mp_id", **overrides: Any
) -> Dict[str, Any]:
    """Create a program funded by an APPROVED plan.  It lands in PLANNED."""
    program = _data(
        api.create_marketing_program(
            f.marketing_program_payload(ctx[plan_key], **overrides), headers=DMO_LIAISON
        ),
        201,
    )
    ctx[key] = program["id"]
    ctx.program = program
    return program


def launch_program(api: ApiClient, ctx: Ctx, program_key: str = "mp_id") -> Dict[str, Any]:
    """Launch a PLANNED program, which requires the clock inside the booking
    window and the district's agreement EXECUTED."""
    program = _data(
        api.launch_marketing_program(ctx[program_key], f.launch_payload(), headers=DMO_LIAISON)
    )
    ctx.program = program
    return program


def running_program(api: ApiClient, **overrides: Any) -> Ctx:
    """The canonical running program: statements filed, plan approved, agreement
    executed, clock inside the booking window and the program launched."""
    ctx = statements_filed(api, **overrides)
    approved_work_plan(api, ctx)
    execute_dmo_agreement(api, ctx)
    create_program(api, ctx)
    set_clock(api, "2026-09-01T00:00:00Z")
    launch_program(api, ctx)
    return ctx


def submit_claim(
    api: ApiClient,
    ctx: Ctx,
    business_key: str = "b3_id",
    program_key: str = "mp_id",
    key: str = "rnc_id",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Claim the room nights a running program generated."""
    claim = _data(
        api.create_room_night_claim(
            ctx[program_key],
            f.room_night_claim_payload(ctx[business_key], **overrides),
            headers=headers if headers is not None else DMO_LIAISON,
        ),
        201,
    )
    ctx[key] = claim["id"]
    ctx.claim = claim
    return claim


def verify_claim(
    api: ApiClient,
    ctx: Ctx,
    claim_key: str = "rnc_id",
    decision: str = "ALLOW",
    verified_room_nights: Any = ...,
    rejection_reason: Any = ...,
) -> Dict[str, Any]:
    """Verify a SUBMITTED claim, which is what admits its nights to the
    performance numerator."""
    claim = _data(
        api.verify_room_night_claim(
            ctx[claim_key],
            f.verification_payload(decision, verified_room_nights, rejection_reason),
            headers=DMO_LIAISON,
        )
    )
    ctx.claim = claim
    return claim


def close_program(api: ApiClient, ctx: Ctx, program_key: str = "mp_id") -> Dict[str, Any]:
    """Close a RUNNING program, which publishes the performance measurement."""
    program = _data(
        api.close_marketing_program(
            ctx[program_key], f.program_closure_payload(), headers=ADMIN
        )
    )
    ctx.program = program
    return program


# --------------------------------------------------------------------------
# Disputes (PRD 3.6)
# --------------------------------------------------------------------------
def file_dispute(
    api: ApiClient,
    ctx: Ctx,
    statement_key: str = "st1_id",
    business_key: str = "b1_id",
    key: str = "dsp_id",
    **overrides: Any
) -> Dict[str, Any]:
    """File a dispute as the owning operator."""
    dispute = _data(
        api.create_dispute(
            f.dispute_payload(ctx[statement_key], **overrides),
            headers=operator_headers(ctx[business_key]),
        ),
        201,
    )
    ctx[key] = dispute["id"]
    ctx.dispute = dispute
    return dispute


def open_dispute_review(api: ApiClient, ctx: Ctx, dispute_key: str = "dsp_id") -> Dict[str, Any]:
    """OPEN_REVIEW moves a SUBMITTED dispute to UNDER_REVIEW."""
    dispute = _data(
        api.advance_dispute(
            ctx[dispute_key],
            f.proceeding_payload("OPEN_REVIEW", "docketed for hearing"),
            headers=HEARING_OFFICER,
        )
    )
    ctx.dispute = dispute
    return dispute


def resolve_dispute(
    api: ApiClient,
    ctx: Ctx,
    dispute_key: str = "dsp_id",
    outcome: str = "ADJUSTED",
    granted_adjustment_cents: Any = ...,
    exempt_status_granted: Any = ...,
) -> Dict[str, Any]:
    """Resolve an UNDER_REVIEW dispute."""
    dispute = _data(
        api.resolve_dispute(
            ctx[dispute_key],
            f.resolution_payload(
                outcome, granted_adjustment_cents, exempt_status_granted, "decided"
            ),
            headers=HEARING_OFFICER,
        )
    )
    ctx.dispute = dispute
    return dispute


# --------------------------------------------------------------------------
# Collections (PRD 3.4)
# --------------------------------------------------------------------------
def remit(
    api: ApiClient,
    ctx: Ctx,
    statement_key: str,
    business_key: str,
    amount_cents: int,
    received_on: str = "2026-08-01T00:00:00Z",
    method: str = "WIRE",
    key: str = "rem_id",
) -> Dict[str, Any]:
    """Pay a statement as the owning operator."""
    remittance = _data(
        api.submit_remittance(
            ctx[statement_key],
            f.remittance_payload(amount_cents, received_on, method),
            headers=operator_headers(ctx[business_key]),
        ),
        201,
    )
    ctx[key] = remittance["id"]
    ctx.remittance = remittance
    return remittance


def reverse(
    api: ApiClient,
    ctx: Ctx,
    statement_key: str,
    remittance_key: str = "rem_id",
    reason: str = "returned bank transfer",
) -> Dict[str, Any]:
    """Unwind a payment, which subtracts exactly the four amounts recorded on the
    remittance row."""
    remittance = _data(
        api.reverse_remittance(
            ctx[statement_key],
            f.remittance_reversal_payload(ctx[remittance_key], reason),
            headers=ADMIN,
        )
    )
    ctx.remittance = remittance
    return remittance


# --------------------------------------------------------------------------
# Audit (PRD 3.3)
# --------------------------------------------------------------------------
def audit_statement(
    api: ApiClient,
    ctx: Ctx,
    statement_key: str = "st1_id",
    audited_room_nights: Any = ...,
    audited_gross_room_revenue_cents: Any = ...,
    headers=None,
) -> Dict[str, Any]:
    """Audit a FILED or AMENDED statement, which computes the final variant."""
    statement = _data(
        api.audit_certify_statement(
            ctx[statement_key],
            f.audit_payload(
                audited_room_nights, audited_gross_room_revenue_cents, "field audit"
            ),
            headers=headers if headers is not None else AUDITOR,
        )
    )
    ctx.statement = statement
    return statement


# --------------------------------------------------------------------------
# Transparency records (PRD 3.9)
# --------------------------------------------------------------------------
def schedule_transparency_record(
    api: ApiClient,
    ctx: Ctx,
    key: str = "tr_id",
    headers=None,
    **overrides: Any
) -> Dict[str, Any]:
    """Schedule a public meeting, annual report or financial audit."""
    record = _data(
        api.create_transparency_record(
            f.transparency_record_payload(ctx.d_id, **overrides),
            headers=headers if headers is not None else ADMIN,
        ),
        201,
    )
    ctx[key] = record["id"]
    ctx.record = record
    return record


def advance_transparency_record(
    api: ApiClient,
    ctx: Ctx,
    to_status: str,
    record_key: str = "tr_id",
    document_reference: Any = ...,
    headers=None,
) -> Dict[str, Any]:
    """Advance a transparency record one forward step."""
    record = _data(
        api.advance_transparency_record(
            ctx[record_key],
            f.advance_transparency_payload(to_status, document_reference),
            headers=headers if headers is not None else ADMIN,
        )
    )
    ctx.record = record
    return record


def publish_transparency_record(
    api: ApiClient,
    ctx: Ctx,
    record_type: str,
    fiscal_year: int = 2027,
    scheduled_for: str = "2026-08-21T00:00:00Z",
    required_by: str = "2027-06-01T00:00:00Z",
    key: str = "tr_id",
    document_reference: str = "https://harborbay.example/record.pdf",
) -> Dict[str, Any]:
    """Walk one record all the way to PUBLISHED.

    The notice must be posted at least 14 whole days ahead of ``scheduled_for``
    and the completion may not be recorded before it, so the clock is advanced to
    ``scheduled_for`` between the two steps.  A FINANCIAL_AUDIT is completed and
    published by a second administrator, because both of those advances require
    an X-User-ID different from the one that engaged the audit.
    """
    from .test_users import ADMIN_2

    schedule_transparency_record(
        api,
        ctx,
        key=key,
        record_type=record_type,
        fiscal_year=fiscal_year,
        scheduled_for=scheduled_for,
        required_by=required_by,
    )
    advance_transparency_record(api, ctx, "NOTICED", record_key=key)
    set_clock(api, scheduled_for)
    acting = ADMIN_2 if record_type == "FINANCIAL_AUDIT" else ADMIN
    advance_transparency_record(api, ctx, "COMPLETED", record_key=key, headers=acting)
    return advance_transparency_record(
        api,
        ctx,
        "PUBLISHED",
        record_key=key,
        document_reference=document_reference,
        headers=acting,
    )


def transparency_compliant_district(api: ApiClient, ctx: Ctx, fiscal_year: int = 2027) -> Ctx:
    """Publish the ANNUAL_REPORT and FINANCIAL_AUDIT records a district must hold
    before it may enter RENEWAL_PENDING or certify a renewal drive."""
    publish_transparency_record(
        api,
        ctx,
        "ANNUAL_REPORT",
        fiscal_year=fiscal_year,
        scheduled_for="2026-08-21T00:00:00Z",
        key="tr_report_id",
        document_reference="https://harborbay.example/annual-report.pdf",
    )
    publish_transparency_record(
        api,
        ctx,
        "FINANCIAL_AUDIT",
        fiscal_year=fiscal_year,
        scheduled_for="2026-09-11T00:00:00Z",
        key="tr_audit_id",
        document_reference="https://harborbay.example/financial-audit.pdf",
    )
    return ctx


# --------------------------------------------------------------------------
# Terminal and enforcement shortcuts
# --------------------------------------------------------------------------
def swept_period(api: ApiClient, **overrides: Any) -> Ctx:
    """A period closed and then swept for delinquency, with the canonical pair of
    statements filed and nothing paid.  The clock lands ten days and one day past
    the due date, so exactly one day is late."""
    ctx = statements_filed(api, **overrides)
    set_clock(api, "2026-11-16T00:00:00Z")
    close_period(api, ctx)
    set_clock(api, "2026-11-26T00:00:00Z")
    sweep_period(api, ctx)
    return ctx


def closed_period_with_filings(api: ApiClient, **overrides: Any) -> Ctx:
    """A CLOSED period holding the canonical filed pair, which is the state an
    audit needs."""
    ctx = statements_filed(api, **overrides)
    set_clock(api, "2026-11-16T00:00:00Z")
    close_period(api, ctx)
    return ctx
