"""Existence resolution (PRD 2.8 rungs 4-13) and shared read helpers."""
from errors import fail
from store import by_seq, store


def _get(table, key, error_id):
    record = table.get(key) if isinstance(key, str) else None
    if record is None:
        fail(error_id, "no such record: %s" % (key,))
    return record


def program_year(pyid):
    return _get(store.program_years, pyid, "ERR_PROGRAM_YEAR_NOT_FOUND")


def student(sid):
    return _get(store.students, sid, "ERR_STUDENT_NOT_FOUND")


def application(aid):
    return _get(store.applications, aid, "ERR_APPLICATION_NOT_FOUND")


def account(acid):
    return _get(store.accounts, acid, "ERR_ACCOUNT_NOT_FOUND")


def provider(pid):
    return _get(store.providers, pid, "ERR_PROVIDER_NOT_FOUND")


def expense_category(cid):
    return _get(store.expense_categories, cid, "ERR_EXPENSE_CATEGORY_NOT_FOUND")


def purchase_request(prid):
    return _get(store.purchase_requests, prid, "ERR_PURCHASE_REQUEST_NOT_FOUND")


def misuse_case(mid):
    return _get(store.misuse_cases, mid, "ERR_MISUSE_CASE_NOT_FOUND")


def renewal_review(rid):
    return _get(store.renewal_reviews, rid, "ERR_RENEWAL_REVIEW_NOT_FOUND")


def appeal(apid):
    return _get(store.appeals, apid, "ERR_APPEAL_NOT_FOUND")


def category_by_code(code):
    for entry in store.expense_categories.values():
        if entry["code"] == code:
            return entry
    return None


def applications_of_year(pyid):
    return by_seq([a for a in store.applications.values()
                   if a["program_year_id"] == pyid])


def accounts_of_year(pyid):
    return by_seq([a for a in store.accounts.values()
                   if a["program_year_id"] == pyid])


def account_of_application(aid):
    for acct in by_seq(list(store.accounts.values())):
        if acct["application_id"] == aid:
            return acct
    return None


def purchase_requests_of_account(acid):
    return by_seq([p for p in store.purchase_requests.values()
                   if p["account_id"] == acid])


def purchase_requests_of_provider(pid):
    return by_seq([p for p in store.purchase_requests.values()
                   if p["provider_id"] == pid])


def misuse_cases_of_account(acid):
    return by_seq([c for c in store.misuse_cases.values()
                   if c["account_id"] == acid])


def determinations_of_application(aid):
    return by_seq([d for d in store.eligibility_determinations.values()
                   if d["application_id"] == aid])


def latest_determination(aid):
    rows = determinations_of_application(aid)
    return rows[-1] if rows else None


def appeals_of_subject(field, value):
    return by_seq([a for a in store.appeals.values() if a.get(field) == value])


def guardian_owns_application(user_id, app):
    return app["student_id"] == user_id


def student_of_account(acct):
    app = store.applications.get(acct["application_id"])
    if app is None:
        return None
    return store.students.get(app["student_id"])
