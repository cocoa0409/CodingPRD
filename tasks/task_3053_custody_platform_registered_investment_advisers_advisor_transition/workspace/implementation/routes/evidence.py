"""Custody rule evidence and examination bundles."""

from core import constants as C
from core.context import body, check_if_match, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE, days_between, new_token, parse_dt
from domain import calc
from domain.cascade import apply_posture, suspend_entitlements
from domain.guards import firm_active_guard, no_outstanding_admin_action, sod_guard
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import identity, load, load_firm


def register(api):

    @api.route("/ria/firms/<firm_id>/custody-evidence", methods=["POST"],
               roles=["AdvisorOperationsLead"])
    def raise_evidence(firm_id):
        firm = load_firm(firm_id)
        firm_active_guard(firm)
        data = body()
        code = need(data, "requirement_code")
        row = create("CustodyRulesEvidence",
                     firm_id=firm_id,
                     requirement_code=code,
                     requirement_status="PENDING",
                     critical=bool(data.get("critical")),
                     drafted_by_user_id=None,
                     accepted_by_user_id=None,
                     evidence_document_hash=None,
                     submitted_at=None,
                     evidence_round_number=0)
        apply_posture(firm)
        return ok(serialize(row), 201)

    @api.route("/ria/firms/<firm_id>/custody-evidence", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_evidence(firm_id):
        from routes._base import params
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("CustodyRulesEvidence", {"firm_id": firm_id,
                                                    "requirement_status": p.get("requirement_status")})
        if p.has("critical"):
            want = p.get("critical").lower() in ("true", "1", "yes")
            rows = [r for r in rows if bool(r.get("critical")) == want]
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/custody-evidence/<evidence_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def read_evidence(evidence_id):
        return ok(serialize(load("CustodyRulesEvidence", evidence_id)), 200)

    @api.route("/ria/custody-evidence/<evidence_id>/submit", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def submit_evidence(evidence_id):
        row = load("CustodyRulesEvidence", evidence_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("PENDING",), ("ACCEPTED", "DEFICIENT", "WAIVED", "LAPSED"))
        if firm.get("firm_posture") not in ("OPEN", "LIMITED", "SUSPENDED"):
            fail("ERR_FIRM_FROZEN")
        ident = identity()
        row["requirement_status"] = "SUBMITTED"
        row["drafted_by_user_id"] = ident.user_id
        row["submitted_at"] = STORE.clock.now()
        touch(row)
        apply_posture(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/custody-evidence/<evidence_id>/accept", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def accept_evidence(evidence_id):
        row = load("CustodyRulesEvidence", evidence_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("SUBMITTED",), ("ACCEPTED", "DEFICIENT", "WAIVED", "LAPSED"))
        ident = identity()
        sod_guard(ident, row.get("drafted_by_user_id"))
        no_outstanding_admin_action(firm)
        row["requirement_status"] = "ACCEPTED"
        row["accepted_by_user_id"] = ident.user_id
        row["evidence_document_hash"] = new_token("ed_")
        touch(row)
        apply_posture(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/custody-evidence/<evidence_id>/reject", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def reject_evidence(evidence_id):
        row = load("CustodyRulesEvidence", evidence_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("SUBMITTED",), ("ACCEPTED", "DEFICIENT", "WAIVED", "LAPSED"))
        ident = identity()
        sod_guard(ident, row.get("drafted_by_user_id"))
        row["requirement_status"] = "DEFICIENT"
        row["deficiency_reason_code"] = data.get("deficiency_reason_code")
        row["evidence_round_number"] = int(row.get("evidence_round_number") or 0) + 1
        touch(row)
        apply_posture(firm)
        suspend_entitlements(firm, only_codes=("MODEL_MANAGEMENT", "ALTERNATIVE_ASSETS"))
        apply_posture(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/custody-evidence/<evidence_id>/resubmit", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def resubmit_evidence(evidence_id):
        row = load("CustodyRulesEvidence", evidence_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("DEFICIENT",), ("ACCEPTED", "WAIVED", "LAPSED"))
        if int(row.get("evidence_round_number") or 0) >= C.EVIDENCE_ROUND_CEILING:
            fail("ERR_EVIDENCE_ROUND_LIMIT")
        ident = identity()
        row["requirement_status"] = "SUBMITTED"
        row["drafted_by_user_id"] = ident.user_id
        touch(row)
        apply_posture(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/custody-evidence/<evidence_id>/waive", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def waive_evidence(evidence_id):
        row = load("CustodyRulesEvidence", evidence_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("SUBMITTED",), ("ACCEPTED", "DEFICIENT", "WAIVED", "LAPSED"))
        if row.get("critical"):
            fail("ERR_INVALID_STATE", "A critical requirement cannot be waived.")
        row["requirement_status"] = "WAIVED"
        touch(row)
        apply_posture(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/custody-evidence/<evidence_id>/lapse", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def lapse_evidence(evidence_id):
        row = load("CustodyRulesEvidence", evidence_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("ACCEPTED",), ("WAIVED", "LAPSED"))
        executed = firm.get("agreement_executed_at")
        if executed is None:
            fail("ERR_INVALID_STATE", "The firm's agreement has not been executed.")
        if days_between(STORE.clock.now_dt(), parse_dt(executed)) < C.LAPSE_WINDOW_DAYS:
            fail("ERR_INVALID_STATE", "The annual evidence window has not yet elapsed.")
        row["requirement_status"] = "LAPSED"
        touch(row)
        apply_posture(firm)
        return ok(serialize(row), 200)

    # ------------------------------------------------- examination bundles

    @api.route("/ria/firms/<firm_id>/examination-bundles", methods=["POST"],
               roles=["ComplianceReviewer"])
    def open_bundle(firm_id):
        firm = load_firm(firm_id)
        firm_active_guard(firm)
        data = body()
        row = create("ExaminationBundle",
                     firm_id=firm_id,
                     period_start_date=need(data, "period_start_date"),
                     period_end_date=need(data, "period_end_date"),
                     bundle_status="ASSEMBLING",
                     missing_evidence_codes=[],
                     sealed_evidence_hash=None,
                     generated_at=None)
        return ok(serialize(row), 201)

    @api.route("/ria/firms/<firm_id>/examination-bundles", methods=["GET"],
               roles=["ComplianceReviewer", "PlatformAdmin"])
    def list_bundles(firm_id):
        from routes._base import params
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("ExaminationBundle", {"firm_id": firm_id})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/examination-bundles/<bundle_id>/generate", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def generate_bundle(bundle_id):
        row = load("ExaminationBundle", bundle_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        if row.get("bundle_status") == "SEALED":
            fail("ERR_ALREADY_TERMINAL")
        if row.get("bundle_status") != "ASSEMBLING":
            fail("ERR_INVALID_STATE")
        missing = calc.examination_missing_codes(firm, row.get("period_start_date"),
                                                 row.get("period_end_date"))
        row["missing_evidence_codes"] = missing
        row["generated_at"] = STORE.clock.now()
        row["bundle_status"] = "GENERATED" if not missing else "INCOMPLETE"
        touch(row)
        return ok(serialize(row), 200)

    @api.route("/ria/examination-bundles/<bundle_id>/seal", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def seal_bundle(bundle_id):
        row = load("ExaminationBundle", bundle_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        if row.get("bundle_status") == "SEALED":
            fail("ERR_ALREADY_TERMINAL")
        if row.get("bundle_status") != "GENERATED":
            fail("ERR_BUNDLE_NOT_SEALABLE")
        row["bundle_status"] = "SEALED"
        row["sealed_evidence_hash"] = new_token("se_")
        touch(row)
        return ok(serialize(row), 200)


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    state = row.get(STATE_FIELDS.get(row.get("_entity")))
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")