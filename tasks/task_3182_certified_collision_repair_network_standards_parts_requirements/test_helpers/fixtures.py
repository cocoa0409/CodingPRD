"""Composite setup helpers.

The certification lifecycle is long (shop -> cycle -> audit -> begin ->
zero-finding issue -> CERTIFIED), so these helpers encapsulate it. Every
helper builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use get_success_data() so failures surface as
"Setup failed" rather than confusing assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as _api
from .test_users import TEST_USERS, make_shop_manager_headers, make_auditor_headers
from .factories import (
    create_shop_payload, create_requirement_payload, create_cycle_payload,
    create_attestation_payload, schedule_audit_payload,
    create_technician_payload, create_course_payload, create_completion_payload,
    create_repair_order_payload, create_procedure_step_payload,
    create_part_line_payload, create_insurer_relation_payload,
    create_referral_payload, create_warranty_claim_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]
AUD2 = TEST_USERS["auditor2_headers"]
DEALER = TEST_USERS["dealer_headers"]

WINDOW_START = "2026-09-01T00:00:00Z"
WINDOW_END = "2027-08-31T23:59:59Z"
WINDOW2_START = "2027-09-01T00:00:00Z"
# 2027-09-01 + 365 days - 1 second = 2028-08-30T23:59:59Z (2028 is a leap year,
# so the 365-day span ends one day earlier than the naive same-date-next-year).
WINDOW2_END = "2028-08-30T23:59:59Z"


def sm(shop_id):
    """ShopManager headers owned by the given shop (identity threading)."""
    return make_shop_manager_headers(shop_id)


def admin_as(user_id):
    from .test_users import make_admin_headers
    return make_admin_headers(user_id)


def auditor_as(user_id):
    return make_auditor_headers(user_id)


# --- Tier 1/2: base entities -------------------------------------------------

def create_shop(**overrides):
    resp = _api.create_shop(create_shop_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_published_requirement(effective_from="2026-09-01T00:00:00Z", **overrides):
    resp = _api.create_requirement(create_requirement_payload(effective_from=effective_from, **overrides), ADMIN)
    req = get_success_data(resp)
    pub = _api.publish_requirement(req["id"], ADMIN)
    return get_success_data(pub)


def open_cycle(shop_id, window_start=WINDOW_START, window_end=WINDOW_END):
    resp = _api.create_cycle(shop_id, create_cycle_payload(window_start=window_start, window_end=window_end), ADMIN)
    return get_success_data(resp)


def attest(shop_id, requirement_id):
    shop = get_success_data(_api.get_shop(shop_id, sm(shop_id)))
    payload = create_attestation_payload(requirement_id, shop["version"])
    resp = _api.create_attestation(shop_id, payload, sm(shop_id))
    return get_success_data(resp)


def schedule_and_run_audit(cycle_id, auditor_headers=AUD1,
                           scheduled_start="2026-09-02T09:00:00Z",
                           scheduled_end="2026-09-02T17:00:00Z",
                           begin_at="2026-09-02T10:00:00Z"):
    """Schedule an audit, advance the clock into the window, begin it.
    Returns the audit dict (in IN_PROGRESS)."""
    resp = _api.schedule_audit(
        cycle_id,
        schedule_audit_payload(scheduled_start=scheduled_start, scheduled_end=scheduled_end),
        auditor_headers,
    )
    audit = get_success_data(resp)
    get_success_data(_api.set_clock(begin_at, ADMIN))
    get_success_data(_api.begin_audit(audit["id"], auditor_headers))
    return get_success_data(_api.get_audit(audit["id"], auditor_headers))


def certify_shop(shop_id, scheduled_start="2026-09-01T01:00:00Z",
                 scheduled_end="2026-09-01T09:00:00Z",
                 begin_at="2026-09-01T02:00:00Z"):
    """Drive a shop APPLICANT -> CERTIFIED via cycle 1 with a zero-finding
    audit (issue-findings with an empty list passes the audit and closes the
    cycle PASS, moving the shop to CERTIFIED). Returns the cycle dict."""
    cycle = open_cycle(shop_id)
    audit = schedule_and_run_audit(
        cycle["id"], AUD1, scheduled_start, scheduled_end, begin_at)
    get_success_data(_api.issue_findings(audit["id"], {"findings": []}, AUD1))
    return get_success_data(_api.get_cycle(cycle["id"], ADMIN))


def certify_shop_with_auditor(shop_id, auditor_headers,
                              scheduled_start="2026-09-01T01:00:00Z",
                              scheduled_end="2026-09-01T09:00:00Z",
                              begin_at="2026-09-01T02:00:00Z"):
    """Same as certify_shop but the audit is scheduled and begun by a
    specific auditor identity (needed when the same auditor already owns an
    in-flight audit for another shop)."""
    cycle = open_cycle(shop_id)
    audit = schedule_and_run_audit(
        cycle["id"], auditor_headers, scheduled_start, scheduled_end, begin_at)
    get_success_data(_api.issue_findings(audit["id"], {"findings": []}, auditor_headers))
    return get_success_data(_api.get_cycle(cycle["id"], ADMIN))


def create_certified_shop(auditor_headers=AUD1, **shop_overrides):
    """Shop registered and driven to CERTIFIED. Returns (shop, cycle)."""
    shop = create_shop(**shop_overrides)
    cycle = certify_shop_with_auditor(shop["id"], auditor_headers)
    shop = get_success_data(_api.get_shop(shop["id"], ADMIN))
    return shop, cycle


def create_technician(shop_id, **overrides):
    resp = _api.create_technician(shop_id, create_technician_payload(**overrides), sm(shop_id))
    return get_success_data(resp)


def create_course(**overrides):
    resp = _api.create_course(create_course_payload(**overrides), ADMIN)
    return get_success_data(resp)


def record_completion(technician_id, course_id, completed_at="2026-08-15T00:00:00Z"):
    resp = _api.create_completion(
        technician_id,
        create_completion_payload(course_id, completed_at=completed_at),
        ADMIN,
    )
    return get_success_data(resp)


def shop_version(shop_id):
    return get_success_data(_api.get_shop(shop_id, ADMIN))["version"]


def create_order(shop_id, technician_id, **overrides):
    payload = create_repair_order_payload(shop_version(shop_id), technician_id, **overrides)
    resp = _api.create_repair_order(shop_id, payload, sm(shop_id))
    return get_success_data(resp)


def record_step(order_id, step_type, technician_id, performed_at, result, shop_id, **overrides):
    payload = create_procedure_step_payload(step_type, technician_id, performed_at, result, **overrides)
    resp = _api.create_procedure_step(order_id, payload, sm(shop_id))
    return get_success_data(resp)


def add_part(order_id, shop_id, **overrides):
    resp = _api.create_part_line(order_id, create_part_line_payload(**overrides), sm(shop_id))
    return get_success_data(resp)


# --- Tier 3: repair-order lifecycle shortcuts --------------------------------

def order_in_estimate(shop_id, technician_id, **overrides):
    """CERTIFIED-shop order in ESTIMATE. Returns the order dict."""
    return create_order(shop_id, technician_id, **overrides)


def order_approved(shop_id, technician_id, performed_at="2026-09-01T03:00:00Z", **overrides):
    """Order in ESTIMATE + PRE_SCAN recorded + approved. Returns the order."""
    order = create_order(shop_id, technician_id, **overrides)
    record_step(order["id"], "PRE_SCAN", technician_id, performed_at, "PASS", shop_id)
    resp = _api.approve_order(order["id"], sm(shop_id))
    return get_success_data(resp)


def order_in_qc(shop_id, technician_id, **overrides):
    """Order driven to QC: approve, add part, start repair, submit QC."""
    order = order_approved(shop_id, technician_id, **overrides)
    add_part(order["id"], shop_id)
    get_success_data(_api.start_repair(order["id"], sm(shop_id)))
    get_success_data(_api.submit_qc(order["id"], sm(shop_id)))
    return get_success_data(_api.get_repair_order(order["id"], sm(shop_id)))


def order_completed(shop_id, technician_id, post_scan_at="2026-09-01T05:00:00Z", **overrides):
    """Non-ADAS order driven to COMPLETE via the scan-after-parts path."""
    order = order_in_qc(shop_id, technician_id, **overrides)
    record_step(order["id"], "POST_SCAN", technician_id, post_scan_at, "PASS", shop_id)
    resp = _api.pass_qc(order["id"], sm(shop_id))
    return get_success_data(resp)


def order_warranty_active(shop_id, technician_id, advance_to="2026-09-02T06:00:00Z", **overrides):
    """Order driven to COMPLETE, then clock advanced past the 24h delivery
    grace so the sweep moves it to WARRANTY_ACTIVE."""
    order = order_completed(shop_id, technician_id, **overrides)
    get_success_data(_api.set_clock(advance_to, ADMIN))
    return get_success_data(_api.get_repair_order(order["id"], ADMIN))


# --- Tier 3: audit / corrective-action lifecycle -----------------------------

def audit_with_finding(shop_id, requirement_id, severity="MAJOR",
                       auditor_headers=AUD1,
                       scheduled_start="2026-09-02T09:00:00Z",
                       scheduled_end="2026-09-02T17:00:00Z",
                       begin_at="2026-09-02T10:00:00Z"):
    """Create an attestation, run an audit against it, issue one finding.
    Returns (audit, attestation, corrective_action, cycle)."""
    att = attest(shop_id, requirement_id)
    cycle = open_cycle(shop_id)
    audit = schedule_and_run_audit(cycle["id"], auditor_headers, scheduled_start, scheduled_end, begin_at)
    get_success_data(_api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": att["id"], "severity": severity}]},
        auditor_headers,
    ))
    rows = get_success_data(_api.list_audit_corrective_actions(audit["id"], auditor_headers))
    ca = rows[0]
    audit = get_success_data(_api.get_audit(audit["id"], auditor_headers))
    return audit, att, ca, cycle


# --- Tier 5: referral / insurer helpers ---------------------------------------

def create_insurer_relation(shop_id, insurer_code="INS-Z", discount_pct_bps=300):
    resp = _api.create_insurer_relation(
        shop_id,
        create_insurer_relation_payload(insurer_code=insurer_code, discount_pct_bps=discount_pct_bps),
        ADMIN,
    )
    return get_success_data(resp)


def create_referral(headers=DEALER, **overrides):
    resp = _api.create_referral(create_referral_payload(**overrides), headers)
    return get_success_data(resp)


def suspend_shop_via_critical(shop_id, attestation_id, auditor_headers=AUD1,
                              scheduled_start="2026-09-05T09:00:00Z",
                              scheduled_end="2026-09-05T17:00:00Z",
                              begin_at="2026-09-05T10:00:00Z",
                              sweep_to="2026-09-16T00:00:00Z"):
    """Open a second cycle, audit it, issue a CRITICAL finding, then advance
    the clock past the CRITICAL corrective action's 10-day due_at so the
    sweep flips the shop CERTIFIED -> SUSPENDED. Returns (audit, cycle)."""
    cycle = open_cycle(shop_id, WINDOW2_START, WINDOW2_END)
    audit = schedule_and_run_audit(cycle["id"], auditor_headers, scheduled_start, scheduled_end, begin_at)
    get_success_data(_api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": attestation_id, "severity": "CRITICAL"}]},
        auditor_headers,
    ))
    get_success_data(_api.set_clock(sweep_to, ADMIN))
    return get_success_data(_api.get_audit(audit["id"], auditor_headers)), cycle
