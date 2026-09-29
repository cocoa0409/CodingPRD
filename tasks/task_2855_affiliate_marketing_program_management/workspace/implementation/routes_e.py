"""Routes: compliance monitoring scans and the violation-case lifecycle
(PRD 3.7)."""

from datetime import timedelta

import calc
import serializers as S
import services as SV
from common import (
    CASE_ACTIONS, CASE_STATES, ROLE_COMPLIANCE, ROLE_PARTNER,
    ROLE_PARTNER_MANAGER, ROLE_PROGRAM_ADMIN, SCAN_ENGINES, VERIFY_OUTCOMES,
    VIOLATION_TYPES, authorize, body, check_sod, db, fail, fmt_dt, g, get_enum,
    get_instant, get_int, get_str, new_row, now_iso, opt_raw, ordered,
    paginate, parse_instant, query_filter, require_owner, respond, touch,
)

# The four signals are examined in this fixed order (PRD 3.7).
SCAN_SIGNALS = (
    ("trademark_hits", "TRADEMARK_BIDDING"),
    ("forced_click_ratio_bps", "FORCED_CLICK"),
    ("cookie_stuffing_index", "COOKIE_STUFFING"),
    ("unauthorized_coupon_hits", "UNAUTHORIZED_COUPON"),
)


def _signal_fires(field, scan):
    value = scan[field]
    if field == "trademark_hits":
        return value > 0
    if field == "forced_click_ratio_bps":
        return value >= calc.FORCED_CLICK_RATIO_THRESHOLD_BPS
    if field == "cookie_stuffing_index":
        return value >= calc.COOKIE_STUFFING_INDEX_THRESHOLD
    return value > 0


def _open_case(affiliate, violation_type, evidence_ref, detected_at,
               source_scan_id, opened_by_user_id):
    row = new_row(
        affiliate_id=affiliate["id"], source_scan_id=source_scan_id,
        violation_type=violation_type, evidence_ref=evidence_ref,
        detected_at=detected_at, state="OPEN",
        severity_weight=calc.SEVERITY_WEIGHT[violation_type],
        failed_verification_count=0, remediation_evidence_ref=None,
        opened_by_user_id=opened_by_user_id, last_note=None,
    )
    db.cases[row["id"]] = row
    return row


def register(app):

    @app.post("/monitoring-scans")
    def create_scan():
        authorize([ROLE_COMPLIANCE, ROLE_PROGRAM_ADMIN])
        payload = body()
        raw_affiliate = opt_raw(payload, "affiliate_id")
        affiliate = None
        if raw_affiliate is not None:
            affiliate = SV.find_affiliate(raw_affiliate)
        if affiliate is None:
            fail("ERR_INVALID_REQUEST", "affiliate_id is required")
        engine = get_enum(payload, "engine", SCAN_ENGINES)
        window_start = get_instant(payload, "window_start")
        window_end = get_instant(payload, "window_end")
        trademark = get_int(payload, "trademark_hits", min_v=0)
        forced = get_int(payload, "forced_click_ratio_bps", min_v=0, max_v=10000)
        stuffing = get_int(payload, "cookie_stuffing_index", min_v=0, max_v=100)
        coupons = get_int(payload, "unauthorized_coupon_hits", min_v=0)
        cooldown = timedelta(hours=calc.SCAN_COOLDOWN_HOURS)
        for other in SV.scans_of(affiliate["id"], engine):
            other_start = parse_instant(other["window_start"])
            other_end = parse_instant(other["window_end"])
            clear = (window_start > other_end + cooldown
                     or other_start > window_end + cooldown)
            if not clear:
                fail("ERR_SCAN_WINDOW_OVERLAP",
                     "the window collides with another scan for this engine")
        scan = new_row(
            mutable=False, affiliate_id=affiliate["id"], engine=engine,
            window_start=fmt_dt(window_start), window_end=fmt_dt(window_end),
            trademark_hits=trademark, forced_click_ratio_bps=forced,
            cookie_stuffing_index=stuffing, unauthorized_coupon_hits=coupons,
            opened_case_count=0,
        )
        db.scans[scan["id"]] = scan
        opened = 0
        for field, violation_type in SCAN_SIGNALS:
            if _signal_fires(field, scan):
                _open_case(affiliate, violation_type,
                           "monitoring scan %s" % scan["id"], now_iso(),
                           scan["id"], None)
                opened += 1
        scan["opened_case_count"] = opened
        if opened:
            SV.recompute_fraud(affiliate)
        return respond(S.scan_out(scan), 201)

    @app.post("/policy-violation-cases")
    def file_case():
        authorize([ROLE_COMPLIANCE, ROLE_PROGRAM_ADMIN])
        payload = body()
        raw_affiliate = opt_raw(payload, "affiliate_id")
        affiliate = None
        if raw_affiliate is not None:
            affiliate = SV.find_affiliate(raw_affiliate)
        raw_scan = opt_raw(payload, "source_scan_id")
        scan = None
        if raw_scan is not None:
            scan = SV.find_scan(raw_scan)
        if affiliate is None:
            fail("ERR_INVALID_REQUEST", "affiliate_id is required")
        violation_type = get_enum(payload, "violation_type", VIOLATION_TYPES)
        evidence_ref = get_str(payload, "evidence_ref", min_len=1, max_len=120)
        detected_at = get_instant(payload, "detected_at")
        case = _open_case(affiliate, violation_type, evidence_ref,
                          fmt_dt(detected_at),
                          None if scan is None else scan["id"], g.user_id)
        SV.recompute_fraud(affiliate)
        return respond(S.case_out(case), 201)

    @app.get("/policy-violation-cases/<case_id>")
    def get_case(case_id):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE, ROLE_PARTNER_MANAGER,
                   ROLE_PARTNER])
        return respond(S.case_out(SV.find_case(case_id)))

    @app.get("/policy-violation-cases")
    def list_cases():
        authorize([ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE, ROLE_PARTNER_MANAGER])
        rows = ordered(db.cases)
        rows = query_filter(rows, "affiliate_id")
        rows = query_filter(rows, "source_scan_id")
        rows = query_filter(rows, "state")
        rows = query_filter(rows, "violation_type")
        return paginate(rows, S.case_out)

    @app.post("/policy-violation-cases/<case_id>/transition")
    def transition_case(case_id):
        role = authorize([ROLE_COMPLIANCE, ROLE_PROGRAM_ADMIN, ROLE_PARTNER])[1]
        payload = body()
        # Each action is reserved to one role, and the role check outranks the
        # existence lookup (rules 2 and 8).
        requested = payload.get("action")
        outcome_raw = payload.get("verify_outcome")
        if requested in ("REQUEST_REMEDIATION", "ESCALATE") \
                and role != ROLE_COMPLIANCE:
            fail("ERR_UNAUTHORIZED",
                 "only a ComplianceAnalyst may perform this action")
        if requested == "SUBMIT_REMEDIATION" and role != ROLE_PARTNER:
            fail("ERR_UNAUTHORIZED", "only the partner may submit remediation")
        if requested == "VERIFY":
            if outcome_raw == "UPHELD" and role != ROLE_PROGRAM_ADMIN:
                fail("ERR_UNAUTHORIZED",
                     "only a ProgramAdmin may uphold an escalated case")
            if outcome_raw in ("CLEARED", "FAILED") and role != ROLE_COMPLIANCE:
                fail("ERR_UNAUTHORIZED",
                     "only a ComplianceAnalyst may verify remediation")
        case = SV.find_case(case_id)
        require_owner(case["affiliate_id"])
        action = get_enum(payload, "action", CASE_ACTIONS)
        note = get_str(payload, "note", min_len=1)
        evidence = get_str(payload, "remediation_evidence_ref", required=False,
                          default=None, min_len=1, max_len=120)
        outcome = get_enum(payload, "verify_outcome", VERIFY_OUTCOMES,
                           required=False, default=None)
        if action == "SUBMIT_REMEDIATION" and evidence is None:
            fail("ERR_INVALID_REQUEST",
                 "remediation_evidence_ref is required to submit remediation")
        if action == "VERIFY" and outcome is None:
            fail("ERR_INVALID_REQUEST", "verify_outcome is required to verify")
        if action == "VERIFY" and outcome != "UPHELD":
            check_sod(case["opened_by_user_id"],
                      "the analyst who filed the case may not verify it")
        if case["state"] in ("VERIFIED_CLEARED", "UPHELD"):
            fail("ERR_CASE_ALREADY_TERMINAL", "the case is already terminal")
        affiliate = db.affiliates.get(case["affiliate_id"])
        terminated = affiliate is not None and affiliate["status"] == "TERMINATED"

        if action == "REQUEST_REMEDIATION":
            if case["state"] != "OPEN" or terminated:
                fail("ERR_CASE_INVALID_TRANSITION",
                     "remediation may only be requested on an OPEN case")
            case["state"] = "REMEDIATION_REQUESTED"
        elif action == "SUBMIT_REMEDIATION":
            if case["state"] != "REMEDIATION_REQUESTED" or terminated:
                fail("ERR_CASE_INVALID_TRANSITION",
                     "remediation may only be submitted once requested")
            case["state"] = "REMEDIATION_SUBMITTED"
            case["remediation_evidence_ref"] = evidence
        elif action == "ESCALATE":
            if case["state"] != "OPEN":
                fail("ERR_CASE_INVALID_TRANSITION",
                     "only an OPEN case may be escalated")
            if case["failed_verification_count"] < \
                    calc.CASE_ESCALATION_FAILED_VERIFICATIONS:
                fail("ERR_CASE_INVALID_TRANSITION",
                     "escalation requires two failed verification rounds")
            case["state"] = "ESCALATED"
        else:
            if outcome == "UPHELD":
                if case["state"] != "ESCALATED":
                    fail("ERR_CASE_INVALID_TRANSITION",
                         "only an ESCALATED case may be upheld")
                case["state"] = "UPHELD"
            else:
                if case["state"] != "REMEDIATION_SUBMITTED":
                    fail("ERR_CASE_INVALID_TRANSITION",
                         "only a submitted remediation may be verified")
                if outcome == "CLEARED":
                    case["state"] = "VERIFIED_CLEARED"
                else:
                    case["state"] = "OPEN"
                    case["failed_verification_count"] += 1
        case["last_note"] = note
        touch(case)
        if action == "VERIFY" and affiliate is not None:
            SV.recompute_fraud(affiliate)
        return respond(S.case_out(case))
