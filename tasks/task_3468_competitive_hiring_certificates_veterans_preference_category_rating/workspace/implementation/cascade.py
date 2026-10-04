"""Cascades, derived consistency (PRD 2.11) and lazy clock transitions.

- remaining_vacancies recomputed immediately on every contributing mutation
- announcement auto-FILL when remaining_vacancies reaches 0 (from CERT_ISSUED)
- certificate auto-CLOSE when its roster is exhausted
- lazy EXPIRED (certificate) / OFFER_EXPIRED (offer) on reads/scoped actions
- announcement cancellation cascade
"""
from store import DB, now, touch

OFFER_LIVE_STATES = {"TENTATIVE", "ACCEPTED", "EOD_SCHEDULED", "ENTERED_ON_DUTY"}


def offers_for_entry(entry_id):
    return [o for o in DB.offers.values() if o["certificate_entry_id"] == entry_id]


def live_offer_for_entry(entry_id):
    for o in DB.offers.values():
        if o["certificate_entry_id"] == entry_id and o["status"] in OFFER_LIVE_STATES:
            return o
    return None


def recompute_remaining(ann):
    """remaining_vacancies = vacancies_count - count(entries of this
    announcement in SELECTED with offer in TENTATIVE/ACCEPTED/EOD_SCHEDULED/
    ENTERED_ON_DUTY). Eager, on every contributing mutation."""
    consumed = 0
    for ce in DB.entries.values():
        if ce["status"] != "SELECTED":
            continue
        app_row = DB.applications.get(ce["application_id"])
        if app_row is None or app_row["announcement_id"] != ann["id"]:
            continue
        if live_offer_for_entry(ce["id"]) is not None:
            consumed += 1
    value = ann["vacancies_count"] - consumed
    if ann.get("remaining_vacancies") != value:
        ann["remaining_vacancies"] = value
        touch(ann)


def auto_fill(ann):
    """CERT_ISSUED -> FILLED when remaining_vacancies reaches 0."""
    if ann["status"] == "CERT_ISSUED" and ann.get("remaining_vacancies", 0) == 0:
        ann["status"] = "FILLED"
        touch(ann)


def auto_close_certificate(cert):
    """ACTIVE -> CLOSED when no entry remains REFERRED."""
    if cert["status"] != "ACTIVE":
        return
    entries = [e for e in DB.entries.values() if e["certificate_id"] == cert["id"]]
    if entries and all(e["status"] != "REFERRED" for e in entries):
        cert["status"] = "CLOSED"
        touch(cert)


def pool_return(cert):
    """REFERRED entries' applications return to the pool: RATED for
    CATEGORY_RATING announcements, QUALIFIED for UNRANKED."""
    ann = DB.announcements[cert["announcement_id"]]
    target = "QUALIFIED" if ann["assessment_method"] == "UNRANKED" else "RATED"
    for e in DB.entries.values():
        if e["certificate_id"] != cert["id"] or e["status"] != "REFERRED":
            continue
        app_row = DB.applications.get(e["application_id"])
        if app_row is not None and app_row["status"] == "REFERRED":
            app_row["status"] = target
            touch(app_row)


def eval_certificate(cert):
    """Lazy expiry: ACTIVE and clock >= expires_at -> EXPIRED + pool return."""
    if cert["status"] == "ACTIVE" and now() >= cert["expires_at"]:
        cert["status"] = "EXPIRED"
        touch(cert)
        pool_return(cert)
        return True
    return False


def offer_not_selected_cascade(offer):
    """Shared decline/expiry/rescind cascade: entry SELECTED -> NOT_SELECTED,
    application SELECTED -> NOT_SELECTED, remaining_vacancies recomputed."""
    entry = DB.entries.get(offer["certificate_entry_id"])
    app_row = DB.applications.get(offer["application_id"])
    ann = None
    if entry is not None and entry["status"] == "SELECTED":
        entry["status"] = "NOT_SELECTED"
        touch(entry)
    if app_row is not None and app_row["status"] == "SELECTED":
        app_row["status"] = "NOT_SELECTED"
        touch(app_row)
    if app_row is not None:
        ann = DB.announcements.get(app_row["announcement_id"])
    if ann is not None:
        recompute_remaining(ann)
    if entry is not None:
        cert = DB.certificates.get(entry["certificate_id"])
        if cert is not None:
            auto_close_certificate(cert)


def eval_offer(offer):
    """Lazy expiry: TENTATIVE and clock >= response_due_at -> OFFER_EXPIRED
    with the NOT_SELECTED cascade chain."""
    if offer["status"] == "TENTATIVE" and now() >= offer["response_due_at"]:
        offer["status"] = "OFFER_EXPIRED"
        touch(offer)
        offer_not_selected_cascade(offer)
        return True
    return False


def rescind_offer(offer):
    """Offer -> RESCINDED with the NOT_SELECTED cascade chain."""
    offer["status"] = "RESCINDED"
    touch(offer)
    offer_not_selected_cascade(offer)


def cancel_announcement_cascade(ann, from_status):
    """PRD 3.2 cancellation cascade; blast radius depends on the from-state."""
    if from_status == "OPEN":
        withdraw_from = {"RECEIVED", "QUALIFIED", "INELIGIBLE", "RATED"}
    else:  # CLOSED or CERT_ISSUED
        withdraw_from = {"RECEIVED", "QUALIFIED", "RATED", "REFERRED"}
    if from_status != "DRAFT":
        for app_row in DB.applications.values():
            if app_row["announcement_id"] == ann["id"] and app_row["status"] in withdraw_from:
                app_row["status"] = "WITHDRAWN"
                touch(app_row)
    if from_status in ("CLOSED", "CERT_ISSUED"):
        for cert in DB.certificates.values():
            if cert["announcement_id"] != ann["id"] or cert["status"] != "ACTIVE":
                continue
            cert["status"] = "CANCELLED"
            touch(cert)
            for entry in [e for e in DB.entries.values() if e["certificate_id"] == cert["id"]]:
                for offer in offers_for_entry(entry["id"]):
                    if offer["status"] in ("TENTATIVE", "ACCEPTED", "EOD_SCHEDULED"):
                        rescind_offer(offer)
    recompute_remaining(ann)
