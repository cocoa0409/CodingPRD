"""Citation issuance, hearing rights, adjudication, settlement and payments."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import derive
import envelope
import store
from errors import fail
from helpers import find
from validate import body_of, fk, opt_str, req_enum, req_instant, req_int, req_str

enforcement_bp = Blueprint("enforcement", __name__)


def _citation_scope(ctx, cit):
    if ctx.is_owner and auth.est_of_citation(cit) != ctx.user_id:
        auth.deny()
    if ctx.is_prac and cit["subject_practitioner_id"] != ctx.user_id:
        auth.deny()


def _inspector_of(cit):
    insp = store.inspections.get(cit["inspection_id"])
    return insp["inspector_user_id"] if insp else None


# ---------------------------------------------------------------- citations
@enforcement_bp.post("/citations")
def create_citation():
    auth.authenticate(("BoardAdmin",))
    body = body_of(request)

    insp_id = fk(body, "inspection_id")
    insp = find("Inspection", insp_id) if insp_id is not None else None
    subject_id = fk(body, "subject_practitioner_id")
    subject = find("Practitioner", subject_id) if subject_id is not None else None

    if insp is None:
        fail("ERR_INVALID_REQUEST", "Field 'inspection_id' is required.")
    subject_type = req_enum(body, "subject_type", derive.SUBJECT_TYPES)
    expected_version = req_int(body, "expected_inspection_version")

    if subject_type == "PRACTITIONER":
        if subject_id is None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'subject_practitioner_id' is required when the subject is a practitioner.")
    elif subject_id is not None:
        fail("ERR_INVALID_REQUEST",
             "Field 'subject_practitioner_id' is forbidden when the subject is the establishment.")

    if insp["status"] != "FINALIZED":
        fail("ERR_INSPECTION_NOT_FINALIZED",
             "Inspection status is %s, not FINALIZED." % insp["status"])
    if expected_version != insp["version"]:
        fail("ERR_STALE_INSPECTION_VERSION",
             "Inspection version is %d, not %d." % (insp["version"], expected_version))

    findings = derive.findings_of(insp["id"])
    if subject_type == "PRACTITIONER":
        if not any(f["attributed_practitioner_id"] == subject_id for f in findings):
            fail("ERR_CITATION_SUBJECT_NOT_IN_FINDINGS",
                 "No finding on this inspection attributes the named practitioner.")
    elif not findings:
        fail("ERR_CITATION_SUBJECT_NOT_IN_FINDINGS",
             "The inspection carries no findings to cite.")

    est = store.establishments[insp["establishment_id"]]
    snapshot = insp["demerit_balance_before_finalize"]
    tier, assessed = derive.assess_citation_fine(insp, subject_type, snapshot, findings)
    fee = derive.admin_fee_cents(assessed)
    issued_at = store.now_utc()

    row = store.make_row()
    row.update({
        "inspection_id": insp["id"],
        "subject_type": subject_type,
        "subject_practitioner_id": subject_id,
        "citation_number": store.next_citation_number(),
        "max_finding_severity": derive.max_finding_severity(findings),
        "demerit_tier_multiplier": tier,
        "assessed_fine_cents": assessed,
        "administrative_fee_cents": fee,
        "total_due_cents": assessed + fee,
        "outstanding_fine_cents": 0,
        "status": "ISSUED",
        "issued_at": issued_at,
        "due_at": issued_at + timedelta(days=derive.PAYMENT_TERM_DAYS),
        "contest_deadline_at": issued_at + timedelta(days=derive.CONTEST_WINDOW_DAYS),
        "hearing_round_count": 0,
    })
    store.citations[row["id"]] = row
    derive.post_ledger("FINE_CENTS", "CITATION_ASSESSMENT",
                       delta_cents=row["total_due_cents"], citation_id=row["id"])
    derive.recompute_citation_outstanding(row)

    derive.refresh_establishment(est, force=True)
    insp["citation_count"] = len(derive.citations_of_inspection(insp["id"]))
    store.bump(insp)
    return envelope.ok(derive.ser_citation(row), 201)


@enforcement_bp.post("/citations/<cid>/contest")
def contest_citation(cid):
    ctx = auth.authenticate(("BoardAdmin", "EstablishmentOwner", "Practitioner"))
    cit = find("Citation", cid)
    _citation_scope(ctx, cit)
    body = body_of(request)
    req_str(body, "grounds")

    if cit["status"] not in ("ISSUED", "AMENDED"):
        fail("ERR_CITATION_NOT_CONTESTABLE",
             "Citation status %s is past the contest stage." % cit["status"])
    if store.now_utc() > cit["contest_deadline_at"]:
        fail("ERR_CONTEST_WINDOW_EXPIRED", "The contest window has closed.")

    cit["status"] = "CONTESTED"
    store.bump(cit)
    return envelope.ok(derive.ser_citation(cit))


@enforcement_bp.post("/citations/<cid>/hearings")
def schedule_hearing(cid):
    auth.authenticate(("BoardAdmin",))
    cit = find("Citation", cid)
    body = body_of(request)
    officer = req_str(body, "presiding_officer_user_id")
    scheduled_at = req_instant(body, "scheduled_at")
    if scheduled_at < store.now_utc():
        fail("ERR_INVALID_REQUEST", "Field 'scheduled_at' may not be in the past.")

    if cit["status"] != "CONTESTED":
        fail("ERR_CITATION_NOT_CONTESTED",
             "Citation status is %s, not CONTESTED." % cit["status"])
    if officer == _inspector_of(cit):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The presiding officer may not be the inspector of record.")
    if cit["hearing_round_count"] >= derive.MAX_HEARING_ROUNDS:
        fail("ERR_HEARING_ROUNDS_EXHAUSTED", "Both adjudication rounds have been held.")

    row = store.make_row()
    row.update({
        "citation_id": cit["id"],
        "presiding_officer_user_id": officer,
        "scheduled_at": scheduled_at,
        "status": "SCHEDULED",
        "decision": None,
        "amended_fine_cents": None,
        "rationale": None,
        "round_index": cit["hearing_round_count"] + 1,
        "decided_at": None,
    })
    store.hearings[row["id"]] = row
    cit["status"] = "HEARING_SCHEDULED"
    cit["hearing_round_count"] = cit["hearing_round_count"] + 1
    store.bump(cit)
    return envelope.ok(derive.ser_hearing(row), 201)


# ------------------------------------------------------------- adjudication
@enforcement_bp.post("/hearings/<hid>/decision")
def record_decision(hid):
    ctx = auth.authenticate(("BoardAdmin", "HearingOfficer"))
    hearing = find("Hearing", hid)
    cit = store.citations[hearing["citation_id"]]
    body = body_of(request)
    decision = req_enum(body, "decision", derive.DECISIONS)
    rationale = req_str(body, "rationale")
    amended = body.get("amended_fine_cents")

    if decision == "AMENDED":
        amended = req_int(body, "amended_fine_cents")
        if amended < derive.FINE_FLOOR_CENTS or amended > cit["assessed_fine_cents"]:
            fail("ERR_INVALID_REQUEST",
                 "Field 'amended_fine_cents' must be between %d and the current assessed fine."
                 % derive.FINE_FLOOR_CENTS)
    elif amended is not None:
        fail("ERR_INVALID_REQUEST",
             "Field 'amended_fine_cents' is only permitted on an AMENDED decision.")

    if hearing["status"] != "SCHEDULED":
        fail("ERR_HEARING_ALREADY_DECIDED", "This hearing has already been decided.")
    if ctx.user_id == _inspector_of(cit):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The inspector of record may not decide the matter.")

    insp = store.inspections[cit["inspection_id"]]
    est = store.establishments[insp["establishment_id"]]
    decided_at = store.now_utc()
    hearing["status"] = "DECIDED"
    hearing["decision"] = decision
    hearing["rationale"] = rationale
    hearing["decided_at"] = decided_at

    if decision == "AFFIRMED":
        cit["status"] = "AFFIRMED"
        store.bump(cit)
        store.bump(hearing)
        derive.refresh_establishment(est, force=False)
        return envelope.ok(derive.ser_hearing(hearing))

    if decision == "AMENDED":
        hearing["amended_fine_cents"] = amended
        old_total = cit["total_due_cents"]
        cit["assessed_fine_cents"] = amended
        cit["administrative_fee_cents"] = derive.admin_fee_cents(amended)
        cit["total_due_cents"] = cit["assessed_fine_cents"] + cit["administrative_fee_cents"]
        derive.post_ledger("FINE_CENTS", "CITATION_AMENDMENT_ADJUSTMENT",
                           delta_cents=cit["total_due_cents"] - old_total, citation_id=cit["id"])
        derive.recompute_citation_outstanding(cit)
        cit["status"] = "AMENDED"
        cit["contest_deadline_at"] = decided_at + timedelta(days=derive.CONTEST_WINDOW_DAYS)
        store.bump(cit)
        store.bump(hearing)
        derive.refresh_establishment(est, force=True)
        return envelope.ok(derive.ser_hearing(hearing))

    # DISMISSED
    outstanding = derive.citation_outstanding(cit["id"])
    derive.post_ledger("FINE_CENTS", "CITATION_DISMISSAL_REVERSAL",
                       delta_cents=-outstanding, citation_id=cit["id"])
    cit["status"] = "DISMISSED"
    derive.recompute_citation_outstanding(cit)

    siblings = derive.citations_of_inspection(insp["id"])
    if all(c["status"] == "DISMISSED" for c in siblings):
        derive.post_ledger("DEMERIT_POINTS", "INSPECTION_DEMERIT_REVERSAL",
                           delta_points=-(insp["final_adjusted_score"] or 0),
                           citation_id=cit["id"], establishment_id=est["id"],
                           inspection_id=insp["id"])

    derive.compute_establishment(est)
    if (est["license_status"] == "PROBATION"
            and est["demerit_balance"] < derive.PROBATION_DEMERIT_THRESHOLD
            and not any(c["status"] == "DELINQUENT"
                        for c in derive.citations_of_establishment(est["id"]))):
        est["license_status"] = "ACTIVE"
    derive.refresh_establishment(est, force=True)
    store.bump(cit)
    store.bump(hearing)
    return envelope.ok(derive.ser_hearing(hearing))


# ----------------------------------------------------------------- payments
@enforcement_bp.post("/citations/<cid>/payments")
def record_payment(cid):
    ctx = auth.authenticate(("BoardAdmin", "EstablishmentOwner", "Practitioner"))
    cit = find("Citation", cid)
    _citation_scope(ctx, cit)
    body = body_of(request)
    amount = req_int(body, "amount_cents", minimum=0)
    opt_str(body, "payer_reference")

    if cit["status"] in ("SETTLED", "DISMISSED"):
        fail("ERR_CITATION_ALREADY_SETTLED",
             "Citation status %s accepts no further payment." % cit["status"])

    outstanding = derive.citation_outstanding(cit["id"])
    if amount <= 0 or amount > outstanding:
        fail("ERR_PAYMENT_EXCEEDS_OUTSTANDING",
             "A payment must be strictly positive and at most the outstanding balance of %d."
             % outstanding)

    entry = derive.post_ledger("FINE_CENTS", "CITATION_PAYMENT",
                               delta_cents=-amount, citation_id=cit["id"])
    derive.recompute_citation_outstanding(cit)
    if cit["outstanding_fine_cents"] == 0:
        cit["status"] = "SETTLED"
    store.bump(cit)

    est = derive.establishment_of_citation(cit)
    if est is not None:
        derive.compute_establishment(est)
        if (est["license_status"] == "SUSPENDED"
                and est["demerit_balance"] < derive.PROBATION_DEMERIT_THRESHOLD
                and not any(c["status"] == "DELINQUENT"
                            for c in derive.citations_of_establishment(est["id"]))):
            est["license_status"] = "ACTIVE"
        derive.refresh_establishment(est, force=True)
    return envelope.ok(derive.ser_ledger_entry(entry), 201)
