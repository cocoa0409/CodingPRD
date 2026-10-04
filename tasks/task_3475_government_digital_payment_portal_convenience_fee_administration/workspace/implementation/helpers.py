"""Cross-cutting helpers: entity resolution (priority-3 existence), computed
gates, shared factories and cascade primitives."""
import clock
import store
from errors import raise_err


# --- entity getters: each unresolved reference reports its own 404 ---------

def get_agency(rid):
    rec = store.agencies.get(rid)
    if rec is None:
        raise_err("ERR_AGENCY_NOT_FOUND", 404, "Agency %s does not exist" % rid)
    return rec


def get_service(rid):
    rec = store.services.get(rid)
    if rec is None:
        raise_err("ERR_SERVICE_NOT_FOUND", 404, "Service %s does not exist" % rid)
    return rec


def get_payer(rid):
    rec = store.payers.get(rid)
    if rec is None:
        raise_err("ERR_PAYER_NOT_FOUND", 404, "Payer %s does not exist" % rid)
    return rec


def get_instrument(rid):
    rec = store.instruments.get(rid)
    if rec is None:
        raise_err("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument %s does not exist" % rid)
    return rec


def get_quote(rid):
    rec = store.quotes.get(rid)
    if rec is None:
        raise_err("ERR_QUOTE_NOT_FOUND", 404, "Fee quote %s does not exist" % rid)
    return rec


def get_transaction(rid):
    rec = store.transactions.get(rid)
    if rec is None:
        raise_err("ERR_TRANSACTION_NOT_FOUND", 404, "Transaction %s does not exist" % rid)
    return rec


def get_batch(rid):
    rec = store.batches.get(rid)
    if rec is None:
        raise_err("ERR_BATCH_NOT_FOUND", 404, "Settlement batch %s does not exist" % rid)
    return rec


def get_account(rid):
    rec = store.accounts.get(rid)
    if rec is None:
        raise_err("ERR_ACCOUNT_NOT_FOUND", 404, "Settlement account %s does not exist" % rid)
    return rec


def get_authorization(rid):
    rec = store.authorizations.get(rid)
    if rec is None:
        raise_err("ERR_AUTHORIZATION_NOT_FOUND", 404, "Statutory authorization %s does not exist" % rid)
    return rec


def get_refund(rid):
    rec = store.refunds.get(rid)
    if rec is None:
        raise_err("ERR_REFUND_NOT_FOUND", 404, "Refund %s does not exist" % rid)
    return rec


def get_chargeback(rid):
    rec = store.chargebacks.get(rid)
    if rec is None:
        raise_err("ERR_CHARGEBACK_NOT_FOUND", 404, "Chargeback case %s does not exist" % rid)
    return rec


def get_exception(rid):
    rec = store.exceptions.get(rid)
    if rec is None:
        raise_err("ERR_EXCEPTION_NOT_FOUND", 404, "Reconciliation exception %s does not exist" % rid)
    return rec


# --- mutation bookkeeping ---------------------------------------------------

def touch(rec):
    """Refresh updated_at and increment version on a mutation."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


# --- computed gates ----------------------------------------------------------

def pci_current(agency_id):
    """True iff the agency holds a PCI_DSS_AOC attestation whose computed
    status is CURRENT at the logical clock (clock earlier than expires_at)."""
    now = clock.now()
    for att in store.attestations.values():
        if (
            att["agency_id"] == agency_id
            and att["attestation_type"] == "PCI_DSS_AOC"
            and now < att["expires_at"]
        ):
            return True
    return False


def attestation_status(att):
    return "CURRENT" if clock.now() < att["expires_at"] else "EXPIRED"


def authorization_in_effect(auth):
    now = clock.now()
    return (
        auth["status"] == "APPROVED"
        and auth["effective_from"] <= now <= auth["effective_to"]
    )


def covering_authorization(service_id):
    """The covering APPROVED, in-effect authorization for a service, or None.
    Windows never overlap among APPROVED rows, so at most one can be in
    effect; the created-order pick is a deterministic tiebreak only."""
    best = None
    for auth in store.authorizations.values():
        if auth["service_id"] != service_id:
            continue
        if authorization_in_effect(auth):
            if best is None or auth["created_seq"] < best["created_seq"]:
                best = auth
    return best


def remaining_refundable(txn):
    return txn["amount_cents"] - txn["refunded_cents"] - txn["charged_back_cents"]


# --- settlement batches ------------------------------------------------------

def new_batch(agency_id, business_date):
    now = clock.now()
    return {
        "id": store.new_id(),
        "agency_id": agency_id,
        "business_date": business_date,
        "status": "OPEN",
        "member_count": 0,
        "gross_amount_cents": 0,
        "fees_withheld_cents": 0,
        "refund_debits_cents": 0,
        "return_debits_cents": 0,
        "chargeback_debits_cents": 0,
        "deposit_cents": 0,
        "deposit_due_date": None,
        "submitted_at": None,
        "confirmed_at": None,
        "actual_deposit_cents": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }


def find_open_batch(agency_id):
    for b in store.batches.values():
        if b["agency_id"] == agency_id and b["status"] == "OPEN":
            return b
    return None


def ensure_open_batch(agency_id):
    """Existing OPEN batch, else auto-create one stamped with the current
    clock date (ACH return / chargeback debit cascades)."""
    b = find_open_batch(agency_id)
    if b is None:
        b = new_batch(agency_id, clock.today_str())
        store.batches[b["id"]] = b
    return b


def open_exception_count(batch_id):
    return sum(
        1
        for e in store.exceptions.values()
        if e["batch_id"] == batch_id and e["status"] == "OPEN"
    )


# --- cascades ---------------------------------------------------------------

def void_open_quotes(service_id):
    for q in store.quotes.values():
        if q["service_id"] == service_id and q["status"] == "OPEN":
            q["status"] = "VOIDED"


def deactivate_service(svc):
    """Service -> DEACTIVATED; every OPEN quote of the service -> VOIDED."""
    if svc["status"] == "DEACTIVATED":
        return
    svc["status"] = "DEACTIVATED"
    touch(svc)
    void_open_quotes(svc["id"])


def require_payer_exists(uid):
    """Priority-3 existence: an unknown payer X-User-ID on a payer-scoped
    write reports ERR_PAYER_NOT_FOUND."""
    if uid not in store.payers:
        raise_err("ERR_PAYER_NOT_FOUND", 404, "Payer %s does not exist" % uid)


def require_payer_ownership(uid, payer_id):
    if payer_id != uid:
        raise_err(
            "ERR_NOT_RESOURCE_OWNER",
            403,
            "Payer %s may only touch its own records" % uid,
        )
