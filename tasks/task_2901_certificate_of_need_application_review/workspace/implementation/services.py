"""Cross-entity services: lookups, derived-field recomputation and cascades."""

import calc
import clock
import store
from errors import ApiError

ACTIVE_CERT_STATES = ("ISSUED", "IMPLEMENTED", "SUSPENDED")
PENDING_APPEAL_STATES = ("FILED", "BRIEFING", "STAYED", "HEARD")
LIVE_INTAKE_STATES = ("SUBMITTED", "COMPLETENESS_REVIEW", "INCOMPLETE", "DEEMED_COMPLETE")


# --- lookups -----------------------------------------------------------------

def _find(collection, record_id, error_id):
    record = store.get(collection, record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def hsa(record_id):
    return _find("health_service_areas", record_id, "ERR_HSA_NOT_FOUND")


def formula(record_id):
    return _find("state_plan_formulas", record_id, "ERR_FORMULA_NOT_FOUND")


def hearing_room(record_id):
    return _find("hearing_rooms", record_id, "ERR_HEARING_ROOM_NOT_FOUND")


def applicant(record_id):
    return _find("applicants", record_id, "ERR_APPLICANT_NOT_FOUND")


def cycle(record_id):
    return _find("batching_cycles", record_id, "ERR_CYCLE_NOT_FOUND")


def loi(record_id):
    return _find("letters_of_intent", record_id, "ERR_LOI_NOT_FOUND")


def application(record_id):
    return _find("applications", record_id, "ERR_APPLICATION_NOT_FOUND")


def completeness_review(record_id):
    return _find("completeness_reviews", record_id, "ERR_COMPLETENESS_REVIEW_NOT_FOUND")


def intervention(record_id):
    return _find("interventions", record_id, "ERR_INTERVENTION_NOT_FOUND")


def hearing(record_id):
    return _find("public_hearings", record_id, "ERR_HEARING_NOT_FOUND")


def certificate(record_id):
    return _find("certificates", record_id, "ERR_CERTIFICATE_NOT_FOUND")


def appeal(record_id):
    return _find("appeals", record_id, "ERR_APPEAL_NOT_FOUND")


# --- relationship helpers ----------------------------------------------------

def cycle_of_application(app):
    return store.get("batching_cycles", app["batching_cycle_id"])


def applications_of_cycle(cycle_row):
    return [a for a in store.rows("applications")
            if a["batching_cycle_id"] == cycle_row["id"]]


def sheets_of_application(application_id, status=None):
    rows = [s for s in store.rows("score_sheets") if s["application_id"] == application_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return rows


def reviews_of_application(application_id):
    return [r for r in store.rows("completeness_reviews")
            if r["application_id"] == application_id]


def appeals_of_application(application_id):
    return [a for a in store.rows("appeals") if a["application_id"] == application_id]


def certificates_of_application(application_id):
    return [c for c in store.rows("certificates") if c["application_id"] == application_id]


def litigation_hold_active(application_id):
    return any(a["litigation_hold_active"] for a in appeals_of_application(application_id))


def pending_appeal_exists(application_id):
    return any(a["status"] in PENDING_APPEAL_STATES
               for a in appeals_of_application(application_id))


def cycle_has_pending_appeal(cycle_row):
    for app in applications_of_cycle(cycle_row):
        if pending_appeal_exists(app["id"]):
            return True
    return False


# --- derived fields ----------------------------------------------------------

def recompute_application_score(app):
    """Refresh comparative_score / score_sheet_count from the ACTIVE sheets."""
    sheets = sheets_of_application(app["id"], "ACTIVE")
    score, count = calc.comparative_score(sheets)
    changed = (app.get("comparative_score") != score
               or app.get("score_sheet_count") != count)
    app["comparative_score"] = score
    app["score_sheet_count"] = count
    return changed


def charge_strike(applicant_row):
    """A compliance strike; standing flips at 2 (RESTRICTED) and 4 (BARRED)."""
    if applicant_row is None:
        return
    applicant_row["compliance_strike_count"] = applicant_row["compliance_strike_count"] + 1
    strikes = applicant_row["compliance_strike_count"]
    if strikes >= 4:
        applicant_row["standing"] = "BARRED"
    elif strikes >= 2:
        applicant_row["standing"] = "RESTRICTED"
    store.touch(applicant_row)


def lineage_ids(cert):
    """This certificate plus every ancestor reached through superseded_certificate_id."""
    ids = []
    seen = set()
    current = cert
    while current is not None and current["id"] not in seen:
        ids.append(current["id"])
        seen.add(current["id"])
        parent_id = current.get("superseded_certificate_id")
        current = store.get("certificates", parent_id) if parent_id else None
    return ids


def accepted_lineage_reports(cert):
    ids = set(lineage_ids(cert))
    return [r for r in store.rows("progress_reports")
            if r["certificate_id"] in ids and r["status"] == "ACCEPTED"]


def governing_expenditure(cert):
    reports = accepted_lineage_reports(cert)
    cash, accrual = calc.cumulative_expenditure(reports)
    return accrual if cert["expenditure_basis"] == "ACCRUAL" else cash


def recompute_certificate_fiscal(cert):
    """Rewrite both cumulative variants, the ceiling, latest completion and the money axis."""
    reports = accepted_lineage_reports(cert)
    cash, accrual = calc.cumulative_expenditure(reports)
    cert["cumulative_expenditure_cash_cents"] = cash
    cert["cumulative_expenditure_accrual_cents"] = accrual
    cert["expenditure_ceiling_cents"] = calc.expenditure_ceiling(
        cert["approved_expenditure_limit_cents"])
    latest = calc.latest_completion(reports)
    cert["latest_completion_pct"] = 0 if latest is None else latest
    governing = accrual if cert["expenditure_basis"] == "ACCRUAL" else cash
    cert["expenditure_status"] = calc.expenditure_status(
        governing, cert["approved_expenditure_limit_cents"],
        cert["expenditure_ceiling_cents"])
    return governing


def applicant_of_certificate(cert):
    app = store.get("applications", cert["application_id"])
    if app is None:
        return None
    return store.get("applicants", app["applicant_id"])


def area_of_certificate(cert):
    app = store.get("applications", cert["application_id"])
    if app is None:
        return None
    cycle_row = store.get("batching_cycles", app["batching_cycle_id"])
    if cycle_row is None:
        return None
    return store.get("health_service_areas", cycle_row["hsa_id"])


def credit_area(area, beds=0, cents=0, licensed=0):
    if area is None:
        return
    if beds:
        area["approved_unimplemented_beds"] = max(0, area["approved_unimplemented_beds"] + beds)
    if licensed:
        area["existing_licensed_beds"] = max(0, area["existing_licensed_beds"] + licensed)
    if cents:
        area["capital_authorization_committed_cents"] = max(
            0, area["capital_authorization_committed_cents"] + cents)


def credit_pool(cycle_row, beds):
    if cycle_row is None or not beds:
        return
    cycle_row["unallocated_bed_need"] = max(0, cycle_row["unallocated_bed_need"] + beds)


# --- guards ------------------------------------------------------------------

def require_owner(user_id, owner_id):
    """Rank 6: the acting Applicant must be the applicant of record for the target."""
    if user_id != owner_id:
        raise ApiError("ERR_NOT_FILING_OWNER",
                       "Only the filing party may perform this operation.")


def require_standing_good(applicant_row):
    """Rank 15, strict form: letter filing, application creation and submission."""
    if applicant_row is None or applicant_row["standing"] != "GOOD":
        raise ApiError("ERR_APPLICANT_STANDING_RESTRICTED",
                       "The applicant's programme standing does not permit this filing.")


def require_not_barred(applicant_row):
    """Rank 15, lenient form: every other applicant-role write."""
    if applicant_row is not None and applicant_row["standing"] == "BARRED":
        raise ApiError("ERR_APPLICANT_STANDING_RESTRICTED",
                       "A barred applicant may not file.")


def require_no_hold(application_id):
    """Rank 13: a live litigation hold freezes the operation."""
    if litigation_hold_active(application_id):
        raise ApiError("ERR_LITIGATION_HOLD_ACTIVE",
                       "A litigation hold on this application freezes the operation.")


def applicant_of_application(app):
    return store.get("applicants", app["applicant_id"])


def cycle_of_certificate(cert):
    app = store.get("applications", cert["application_id"])
    if app is None:
        return None
    return store.get("batching_cycles", app["batching_cycle_id"])
