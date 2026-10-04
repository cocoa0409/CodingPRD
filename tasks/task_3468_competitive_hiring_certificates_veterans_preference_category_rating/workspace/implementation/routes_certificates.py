"""Certificate issuance, lifecycle, and selection (PRD 3.6, 3.7, 3.8)."""
from datetime import timedelta

from flask import Blueprint

from auth import get_auth, require_roles
from calc import (CATEGORY_RANK, EXTENSION_MAX_DAYS, MAX_EXTENSIONS,
                  OFFER_RESPONSE_DAYS, rank_entries, select_roster)
from cascade import (auto_close_certificate, auto_fill, eval_certificate,
                     live_offer_for_entry, pool_return, recompute_remaining)
from envelope import success_list, success_object
from errors import fail, invalid_state, not_found
from serializers import certificate_out, entry_out, offer_out
from store import DB, base_fields, now, touch
from validate import get_body, parse_pagination, req_int, req_str

bp = Blueprint("certificates", __name__)


def get_certificate_or_404(certificate_id):
    row = DB.certificates.get(certificate_id)
    if row is None:
        not_found("certificate")
    return row


def get_entry_or_404(entry_id):
    row = DB.entries.get(entry_id)
    if row is None:
        not_found("certificate entry")
    return row


def _eval_announcement_certificates(ann_id):
    """Issuance inspects whether prior certificates are 'still ACTIVE'; that
    determination includes the lazy clock-based expiry evaluation."""
    for c in DB.certificates.values():
        if c["announcement_id"] == ann_id:
            eval_certificate(c)


@bp.route("/hiring/announcements/<announcement_id>/certificates", methods=["POST"])
def issue_certificate(announcement_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    get_body()
    ann = DB.announcements.get(announcement_id)
    if ann is None:
        not_found("announcement")
    if ann["status"] not in ("CLOSED", "CERT_ISSUED"):
        fail("ERR_ANNOUNCEMENT_NOT_CLOSED",
             "issuance requires CLOSED or CERT_ISSUED")
    _eval_announcement_certificates(announcement_id)
    priors = [c for c in DB.certificates.values() if c["announcement_id"] == ann["id"]]
    # ERR_ACTIVE_CERTIFICATE_EXISTS outranks the window rule when both fire.
    if any(c["status"] == "ACTIVE" for c in priors):
        fail("ERR_ACTIVE_CERTIFICATE_EXISTS",
             "another certificate of this announcement is ACTIVE")
    clock = now()
    for c in priors:
        # Closed-interval windows [issued_at, expires_at]: adjacency conflicts.
        if clock <= c["expires_at"]:
            fail("ERR_CERTIFICATE_WINDOW_OVERLAP",
                 "new issuance window overlaps a prior certificate window")
    apps = [a for a in DB.applications.values() if a["announcement_id"] == ann["id"]]
    roster = select_roster(ann, apps)
    if roster is None:
        fail("ERR_INSUFFICIENT_ELIGIBLES", "roster does not satisfy the rule of many")
    cert = base_fields()
    cert.update({
        "announcement_id": ann["id"], "issued_at": clock,
        "expires_at": clock + timedelta(days=ann["certificate_validity_days"]),
        "extension_count": 0, "status": "ACTIVE",
    })
    DB.certificates[cert["id"]] = cert
    unranked = ann["assessment_method"] == "UNRANKED"
    infos = []
    for app_row in roster:
        applicant = DB.applicants[app_row["applicant_id"]]
        # "Preference eligible" in the OPM sense: a verified non-NONE claim.
        # preference_verified is always true for NONE claims (PRD 3.3), but a
        # NONE claimant is not a preference eligible — otherwise the pass-over
        # gates of 3.8 could never fire (desired entry must be non-eligible).
        eligible = bool(applicant["preference_verified"]
                        and applicant["veteran_preference_claim"] != "NONE")
        points = applicant["preference_points"]
        if unranked:
            info = {
                "app": app_row, "quality_category": None,
                "preference_eligible": eligible, "preference_points": points,
                "augmented_score": None,
                "cps_float": False,
                "submitted_at": app_row["submitted_at"], "seq": app_row["_seq"],
            }
        else:
            info = {
                "app": app_row, "quality_category": app_row["quality_category"],
                "preference_eligible": eligible, "preference_points": points,
                "augmented_score": app_row["technical_score"] + points,
                "cps_float": bool(eligible and applicant["veteran_preference_claim"] == "TEN_POINT_CPS"),
                "submitted_at": app_row["submitted_at"], "seq": app_row["_seq"],
            }
        infos.append(info)
    ordered = rank_entries(infos, unranked)
    for position, info in enumerate(ordered, start=1):
        entry = base_fields()
        entry.update({
            "certificate_id": cert["id"], "application_id": info["app"]["id"],
            "quality_category": info["quality_category"],
            "preference_eligible": info["preference_eligible"],
            "preference_points": info["preference_points"],
            "augmented_score": info["augmented_score"],
            "rank_position": position, "status": "REFERRED",
        })
        DB.entries[entry["id"]] = entry
        app_row = info["app"]
        app_row["status"] = "REFERRED"
        touch(app_row)
    if ann["status"] == "CLOSED":
        ann["status"] = "CERT_ISSUED"
        touch(ann)
    return success_object(certificate_out(cert), 201)


@bp.route("/hiring/certificates/<certificate_id>", methods=["GET"])
def read_certificate(certificate_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial"])
    row = get_certificate_or_404(certificate_id)
    eval_certificate(row)
    return success_object(certificate_out(row))


@bp.route("/hiring/certificates/<certificate_id>/extend", methods=["POST"])
def extend_certificate(certificate_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    body = get_body()
    if "additional_days" not in body or not isinstance(body["additional_days"], int) \
            or isinstance(body["additional_days"], bool):
        fail("ERR_INVALID_REQUEST", "additional_days must be an integer")
    additional_days = body["additional_days"]
    expected_version = req_int(body, "expected_certificate_version")
    row = get_certificate_or_404(certificate_id)
    eval_certificate(row)
    if row["status"] != "ACTIVE":
        fail("ERR_CERTIFICATE_NOT_ACTIVE", "certificate is not ACTIVE")
    if row["extension_count"] >= MAX_EXTENSIONS or not (1 <= additional_days <= EXTENSION_MAX_DAYS):
        fail("ERR_EXTENSION_LIMIT",
             "at most 2 extensions of 1..30 days each")
    # OCC is the final check (priority 10).
    if expected_version != row["version"]:
        fail("ERR_STALE_VERSION", "certificate version has advanced; refresh before extending")
    row["expires_at"] = row["expires_at"] + timedelta(days=additional_days)
    row["extension_count"] += 1
    touch(row)
    return success_object(certificate_out(row))


@bp.route("/hiring/certificates/<certificate_id>/return", methods=["POST"])
def return_certificate(certificate_id):
    _, role = get_auth()
    require_roles(role, ["SelectingOfficial"])
    get_body()
    row = get_certificate_or_404(certificate_id)
    eval_certificate(row)
    if row["status"] != "ACTIVE":
        fail("ERR_CERTIFICATE_NOT_ACTIVE", "certificate is not ACTIVE")
    for e in DB.entries.values():
        if e["certificate_id"] != row["id"] or e["status"] != "SELECTED":
            continue
        offer = live_offer_for_entry(e["id"])
        if offer is not None and offer["status"] in ("TENTATIVE", "ACCEPTED", "EOD_SCHEDULED"):
            invalid_state("an entry is SELECTED with a live offer")
    row["status"] = "RETURNED"
    touch(row)
    pool_return(row)
    return success_object(certificate_out(row))


@bp.route("/hiring/certificates/<certificate_id>/entries", methods=["GET"])
def list_certificate_entries(certificate_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial"])
    row = get_certificate_or_404(certificate_id)
    limit, offset = parse_pagination()
    items = [e for e in DB.entries.values() if e["certificate_id"] == row["id"]]
    items.sort(key=lambda e: e["rank_position"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([entry_out(e) for e in page], limit, offset, total)


def _pending_pass_over_blocks(cert, entry):
    """A PENDING pass-over naming a higher-ranked REFERRED preference-eligible
    entry blocks selections of lower-ranked entries on the same certificate."""
    for por in DB.pass_overs.values():
        if por["status"] != "PENDING":
            continue
        target = DB.entries.get(por["certificate_entry_id"])
        if target is None or target["certificate_id"] != cert["id"]:
            continue
        if target["status"] == "REFERRED" and target["preference_eligible"] \
                and target["rank_position"] < entry["rank_position"]:
            return True
    return False


@bp.route("/hiring/certificates/<certificate_id>/selections", methods=["POST"])
def select_entry(certificate_id):
    _, role = get_auth()
    require_roles(role, ["SelectingOfficial"])
    body = get_body()
    entry_id = req_str(body, "certificate_entry_id")
    cert = get_certificate_or_404(certificate_id)
    entry = get_entry_or_404(entry_id)
    if entry["certificate_id"] != cert["id"]:
        not_found("certificate entry")
    eval_certificate(cert)
    # Priority 5 state gates.
    if cert["status"] != "ACTIVE":
        fail("ERR_CERTIFICATE_NOT_ACTIVE", "certificate is not ACTIVE")
    app_row = DB.applications[entry["application_id"]]
    if entry["status"] != "REFERRED" or app_row["status"] != "REFERRED":
        invalid_state("entry and application must stand in REFERRED")
    if _pending_pass_over_blocks(cert, entry):
        fail("ERR_PASS_OVER_PENDING",
             "a pending pass-over request blocks lower-ranked selections")
    # Priority 7 selection gates (CATEGORY_RATING certificates only).
    ann = DB.announcements[cert["announcement_id"]]
    if ann["assessment_method"] == "CATEGORY_RATING":
        my_rank = CATEGORY_RANK[entry["quality_category"]]
        siblings = [e for e in DB.entries.values()
                    if e["certificate_id"] == cert["id"] and e["status"] == "REFERRED"
                    and e["id"] != entry["id"]]
        if any(CATEGORY_RANK[e["quality_category"]] > my_rank for e in siblings):
            fail("ERR_CATEGORY_BYPASS",
                 "a REFERRED entry in a strictly higher category exists")
        if not entry["preference_eligible"]:
            for e in siblings:
                if e["quality_category"] != entry["quality_category"]:
                    continue
                if not e["preference_eligible"] or e["rank_position"] >= entry["rank_position"]:
                    continue
                covered = any(
                    p["status"] == "APPROVED" and p["certificate_entry_id"] == e["id"]
                    and p["desired_entry_id"] == entry["id"]
                    for p in DB.pass_overs.values()
                )
                if not covered:
                    fail("ERR_PASS_OVER_REQUIRED",
                         "an approved pass-over is required for this selection")
    if ann.get("remaining_vacancies", 0) <= 0:
        fail("ERR_NO_REMAINING_VACANCIES", "no remaining vacancies")
    # Apply: entry -> SELECTED, application -> SELECTED, offer TENTATIVE.
    entry["status"] = "SELECTED"
    touch(entry)
    app_row["status"] = "SELECTED"
    touch(app_row)
    clock = now()
    offer = base_fields()
    offer.update({
        "application_id": app_row["id"], "certificate_entry_id": entry["id"],
        "tentative_offered_at": clock,
        "response_due_at": clock + timedelta(days=OFFER_RESPONSE_DAYS),
        "responded_at": None, "suitability_reviewer_id": None,
        "eod_date": None, "status": "TENTATIVE",
    })
    DB.offers[offer["id"]] = offer
    recompute_remaining(ann)
    auto_fill(ann)
    auto_close_certificate(cert)
    return success_object(offer_out(offer), 201)
