"""Business-rule computations shared by routes and system evaluation."""
from decimal import Decimal

from clock import add_days, add_months, parse_date, round2, today
from errors import fail
from state import STORE, get, touch

BE_LOWER = Decimal("80.00")
BE_UPPER = Decimal("125.00")

PRIORITY_MONTHS = {"PRIORITY": 8, "STANDARD": 10}

TERMINAL_APPLICATION_STATES = ("REFUSED_APPROVAL", "LAPSED", "WITHDRAWN")

PATHWAY_MAP = {
    "MANUFACTURING_SITE": ("PRIOR_APPROVAL",),
    "FORMULATION": ("PRIOR_APPROVAL",),
    "LABELING": ("PRIOR_APPROVAL", "CBE_30"),
    "PACKAGING": ("PRIOR_APPROVAL", "CBE_30", "CBE_0"),
    "EDITORIAL": ("CBE_0", "ANNUAL_REPORT"),
}


def be_is_adequate(f):
    """Per-study round-first adequacy (calculations.be_adequacy_determination)."""
    return (
        round2(f["auc_ci_low_pct"]) >= BE_LOWER
        and round2(f["auc_ci_high_pct"]) <= BE_UPPER
        and round2(f["cmax_ci_low_pct"]) >= BE_LOWER
        and round2(f["cmax_ci_high_pct"]) <= BE_UPPER
    )


def has_accepted_be(app_id):
    return any(
        s["application_id"] == app_id and s["status"] == "ACCEPTED"
        for s in STORE["studies"].values()
    )


def active_protection_codes(rp_id):
    return {
        w["indication_code"]
        for w in STORE["protections"].values()
        if w["reference_product_id"] == rp_id and w["status"] == "ACTIVE"
    }


def carve_out_problem(app):
    """Exact set equality: carved codes vs currently ACTIVE protections."""
    active = active_protection_codes(app["reference_product_id"])
    carved = set(app.get("carved_indication_codes") or [])
    if app["labeling_mode"] == "FULL" and active:
        return "ERR_LABEL_CARVE_OUT_INCOMPLETE"
    if active - carved:
        return "ERR_LABEL_CARVE_OUT_INCOMPLETE"
    if carved - active:
        return "ERR_CARVE_OUT_OF_UNPROTECTED"
    return None


def check_carve_out(app):
    problem = carve_out_problem(app)
    if problem == "ERR_LABEL_CARVE_OUT_INCOMPLETE":
        fail(problem, "An ACTIVE protected indication is missing from "
                      "carved_indication_codes (or labeling_mode FULL used "
                      "while protections are active)")
    if problem:
        fail(problem, "carved_indication_codes contains a code with no ACTIVE "
                      "protection")


def certified_p4_certs(app_id):
    return [
        c for c in STORE["certifications"].values()
        if c["application_id"] == app_id
        and c["status"] == "CERTIFIED"
        and c["certification_type"] == "PARAGRAPH_IV_CHALLENGE"
    ]


def nce_check(rp, app):
    """NCE submission bar (calculations.nce_submission_bar); inclusive bounds."""
    if not rp.get("is_new_chemical_entity"):
        return
    t = today()
    anchor = parse_date(rp["rld_approval_date"])
    if t < add_months(anchor, 48):
        fail("ERR_NCE_SUBMISSION_BARRED",
             "NCE bar: no submission before 48 months after rld_approval_date")
    if t < add_months(anchor, 60) and not certified_p4_certs(app["id"]):
        fail("ERR_NCE_SUBMISSION_BARRED",
             "NCE bar: between 48 and 60 months a PARAGRAPH_IV_CHALLENGE "
             "certification is required")


def certification_completeness_check(rp_id, app_id):
    for p in STORE["patents"].values():
        if p["reference_product_id"] != rp_id or p["status"] != "LISTED":
            continue
        n = sum(
            1 for c in STORE["certifications"].values()
            if c["application_id"] == app_id and c["patent_id"] == p["id"]
        )
        if n != 1:
            fail("ERR_CERTIFICATION_INCOMPLETE",
                 "Exactly one certification per LISTED patent of the "
                 "reference product is required")


def notice_for_cert(cert_id):
    for n in STORE["notices"].values():
        if n["certification_id"] == cert_id:
            return n
    return None


def award_for_app(app_id):
    for a in STORE["awards"].values():
        if a["application_id"] == app_id:
            return a
    return None


def awards_for_rp(rp_id):
    return [a for a in STORE["awards"].values()
            if a["reference_product_id"] == rp_id]


def patent_blocked_until(app):
    """Latest block date strictly after today, else None (approval_blocked_posture)."""
    t = today()
    candidates = []
    for c in STORE["certifications"].values():
        if c["application_id"] != app["id"]:
            continue
        if c["status"] not in ("CERTIFIED", "AMENDED_TO_P3"):
            continue
        patent = get("patents", c["patent_id"])
        if patent is None or patent["status"] == "EXPIRED":
            continue
        if c["status"] == "AMENDED_TO_P3":
            eff_type = "PARAGRAPH_III_DEFER"
        else:
            eff_type = c["certification_type"]
        if eff_type == "PARAGRAPH_II_EXPIRED":
            continue
        if eff_type == "PARAGRAPH_III_DEFER":
            candidates.append(parse_date(patent["expiry_date"]))
            continue
        # PARAGRAPH_IV_CHALLENGE still CERTIFIED: block by notice posture.
        notice = notice_for_cert(c["id"])
        if notice is None:
            continue  # hard ERR_P4_NOTICE_REQUIRED gate, not a date block
        if notice["status"] == "SUIT_FILED" and notice["stay_until"]:
            candidates.append(parse_date(notice["stay_until"]))
        elif notice["status"] == "DECIDED_VALID":
            candidates.append(parse_date(patent["expiry_date"]))
        # NOTICE_SENT / NO_SUIT_FILED / STAY_EXPIRED / DECIDED_INVALID: no block
    future = [d for d in candidates if d > t]
    return max(future) if future else None


def exclusivity_blocked(app):
    t = today()
    for a in STORE["awards"].values():
        if a["reference_product_id"] != app["reference_product_id"]:
            continue
        if a["application_id"] == app["id"]:
            continue
        if a["status"] == "AWARDED":
            return True
        if a["status"] == "ACTIVE" and a["exclusivity_end_date"]:
            if t < parse_date(a["exclusivity_end_date"]):
                return True
    return False


def open_deficiency_count(app_id):
    return sum(1 for c in STORE["cycles"].values()
               if c["application_id"] == app_id and c["status"] == "CRL_ISSUED")


def has_open_deficiency(app_id):
    return open_deficiency_count(app_id) > 0


def open_supplement_count(app_id):
    return sum(1 for s in STORE["supplements"].values()
               if s["application_id"] == app_id and s["review_status"] == "SUBMITTED")


def goal_date(cycle):
    months = cycle["base_review_months"] + 3 * cycle["major_amendment_extensions_count"]
    return add_months(parse_date(cycle["opened_date"]), months)


def current_cycle(app):
    for c in STORE["cycles"].values():
        if (c["application_id"] == app["id"]
                and c["cycle_number"] == app["current_cycle_number"]):
            return c
    return None


def close_current_cycle(app, reason):
    c = current_cycle(app)
    if c is not None and c["status"] in ("OPEN", "CRL_ISSUED", "AMENDMENT_RECEIVED"):
        c["status"] = "CLOSED"
        c["closed_reason"] = reason
        touch(c)


def facility_clearance_ok(app_id):
    """calculations.facility_clearance_evaluation (approval-decision gate)."""
    relevant = [i for i in STORE["inspections"].values()
                if i["application_id"] == app_id and i["status"] != "CANCELLED"]
    facility_ids = []
    for i in relevant:
        if i["facility_id"] not in facility_ids:
            facility_ids.append(i["facility_id"])
    if not facility_ids:
        return False
    for fid in facility_ids:
        f_ins = [i for i in relevant if i["facility_id"] == fid]
        # latest outcome commit order; seq is the commit counter (never id).
        latest = max(f_ins, key=lambda i: i["seq"])
        if latest["status"] not in ("PASSED", "WAIVED"):
            return False
        facility = get("facilities", fid)
        if facility is not None and facility["is_foreign"]:
            if not any(i["status"] == "PASSED" for i in f_ins):
                return False
    return True
