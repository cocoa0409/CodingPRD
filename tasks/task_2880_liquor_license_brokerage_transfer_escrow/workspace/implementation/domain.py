"""Cascades, conserved quantities and cross-record recomputation (PRD 2.8)."""

import calc
from store import bump, db, make_record, now, sorted_ledger


# --- county ---------------------------------------------------------------
def recompute_county(county):
    """Rewrite the four counters and advance the county's version by one."""
    calc.county_quota_position(county)
    bump(county)
    return county


def county_of(license_rec):
    return db.counties.get(license_rec["county_id"])


def recompute_county_of(license_rec):
    county = county_of(license_rec)
    if county is not None:
        recompute_county(county)
    return county


# --- escrow ledger --------------------------------------------------------
def ledger_rows(agreement_id):
    return sorted_ledger([r for r in db.ledger.values() if r["agreement_id"] == agreement_id])


def replay_balance(agreement):
    """Pure replay of the append-only ledger (PRD 3.4)."""
    running = 0
    for row in ledger_rows(agreement["id"]):
        running += row["amount_cents"]
        row["balance_after_cents"] = running
    agreement["escrow_balance_cents"] = running
    return running


def append_entry(agreement, entry_type, amount_cents, memo):
    entry = make_record({
        "agreement_id": agreement["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "balance_after_cents": 0,
        "memo": memo,
        "occurred_at": now(),
    }, versioned=False)
    db.ledger[entry["id"]] = entry
    replay_balance(agreement)
    return entry


# --- disclosures ----------------------------------------------------------
def disclosures_of(agreement_id):
    return [d for d in db.disclosures.values() if d["agreement_id"] == agreement_id]


def fully_acked_disclosure(agreement_id):
    for d in disclosures_of(agreement_id):
        if d["status"] == "FULLY_ACKED":
            return d
    return None


def void_disclosures(agreement_id):
    """Move every PENDING_ACKS or FULLY_ACKED disclosure on the agreement to VOID."""
    for d in disclosures_of(agreement_id):
        if d["status"] in ("PENDING_ACKS", "FULLY_ACKED"):
            d["status"] = "VOID"
            bump(d)


# --- listings -------------------------------------------------------------
def recompute_open_offers(listing):
    """open_offer_count over the DRAFT agreements that remain on the listing."""
    count = 0
    for a in db.agreements.values():
        if a["listing_id"] == listing["id"] and a["agreement_status"] == "DRAFT":
            count += 1
    listing["open_offer_count"] = count
    return count


# --- applications and protests -------------------------------------------
def applications_of(agreement_id):
    from store import sorted_by_created
    return sorted_by_created([a for a in db.applications.values()
                              if a["agreement_id"] == agreement_id])


def application_of(agreement_id):
    """The agreement's transfer application; the latest filed one when several exist."""
    rows = applications_of(agreement_id)
    return rows[-1] if rows else None


def protests_of(application_id):
    from store import sorted_by_created
    return sorted_by_created([p for p in db.protests.values()
                              if p["application_id"] == application_id])


def pending_filing_on(license_id):
    for f in db.filings.values():
        if f["license_id"] == license_id and f["status"] == "PENDING":
            return f
    return None


# --- execution cascade (PRD 3.5 / 2.8) -----------------------------------
def execute_cascade(agreement, listing, license_rec, disclosure):
    agreement["executed_at"] = now()
    agreement["commission_mode"] = (
        "DUAL_AGENCY" if (disclosure["represents_seller"] and disclosure["represents_buyer"])
        else "SINGLE_AGENCY")
    agreement["agreement_status"] = "EXECUTED"
    bump(agreement)
    # the safekeeping window is deliberately retained so it can be restored
    license_rec["status"] = "IN_ESCROW"
    bump(license_rec)
    listing["status"] = "UNDER_CONTRACT"
    bump(listing)
    recompute_county_of(license_rec)
    return agreement


# --- five-hop closing cascade (PRD 3.7 / 2.8) ---------------------------
def approval_cascade(application, agreement, listing, license_rec):
    # hop 2: the license moves IN_ESCROW -> TRANSFERRED
    if license_rec is not None and license_rec["status"] == "IN_ESCROW":
        license_rec["status"] = "TRANSFERRED"
        license_rec["transferred_to_buyer_id"] = agreement["buyer_id"]
        license_rec["last_transfer_price_cents"] = agreement["purchase_price_cents"]
        bump(license_rec)
        # hop 3: the listing moves UNDER_CONTRACT -> SOLD
        if listing is not None and listing["status"] == "UNDER_CONTRACT":
            listing["status"] = "SOLD"
            bump(listing)
            # hop 4: the agreement closes; the money dimension stays HELD
            if agreement["agreement_status"] == "EXECUTED":
                agreement["agreement_status"] = "CLOSED"
                bump(agreement)
                # hop 5: every live protest is overruled
                for p in protests_of(application["id"]):
                    if p["status"] in ("OPEN", "RESPONDED"):
                        p["status"] = "OVERRULED"
                        bump(p)
        recompute_county_of(license_rec)


def denial_cascade(application):
    for p in protests_of(application["id"]):
        if p["status"] in ("OPEN", "RESPONDED"):
            p["status"] = "SUSTAINED"
            bump(p)


# --- four-hop compensating cascade (PRD 3.8 / 2.8) ----------------------
def compensating_cascade(agreement, termination_reason):
    # hop 2: contract dimension EXECUTED -> TERMINATED, voiding the disclosures
    if agreement["agreement_status"] == "EXECUTED":
        agreement["agreement_status"] = "TERMINATED"
        agreement["termination_reason"] = termination_reason
        bump(agreement)
        void_disclosures(agreement["id"])
        # hop 3: the license returns to whichever pre-escrow status is lawful
        license_rec = db.licenses.get(agreement["license_id"])
        if license_rec is not None and license_rec["status"] == "IN_ESCROW":
            expires = license_rec.get("safekeeping_expires_at")
            if expires is not None and now() < expires:
                license_rec["status"] = "SAFEKEEPING"
            else:
                license_rec["status"] = "ACTIVE"
            bump(license_rec)
            recompute_county_of(license_rec)
            # hop 4: the listing returns to the market
            listing = db.listings.get(agreement["listing_id"])
            if listing is not None and listing["status"] == "UNDER_CONTRACT":
                listing["status"] = "ACTIVE"
                recompute_open_offers(listing)
                bump(listing)
