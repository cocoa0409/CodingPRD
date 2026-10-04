"""Logical-clock maintenance sweeps (PRD §2.4) and the shared cascade helpers
used by both sweeps and API-driven transitions (PRD §3.3, §3.7, §3.8, §3.9).

Sweep order per clock advancement: (1) payment-deadline cancellations,
(2) milestone MISSED detection, (3) lease reconciliation. Within each class,
records process in created_at ASC order (creation sequence breaks ties,
never id).
"""
import store
import calcs
from helpers import touch


# --- shared cascade primitives -------------------------------------------------
def refund_held(applicant):
    """REJECT / WITHDRAW: held deposit moves to refunded; conservation
    invariant paid == held + refunded + forfeited is preserved."""
    amount = applicant["upfront_held_cents"]
    if amount > 0:
        applicant["upfront_refunded_cents"] += amount
        applicant["upfront_held_cents"] = 0
        applicant["eligibility_units"] = calcs.eligibility_for(0)
    touch(applicant)


def forfeit_held(applicant, auction):
    """DISQUALIFY / payment-deadline lapse: held deposit moves to forfeited;
    the forfeiture itself grows Auction.forfeited_deposits_cents."""
    amount = applicant["upfront_held_cents"]
    if amount > 0:
        applicant["upfront_forfeited_cents"] += amount
        applicant["upfront_held_cents"] = 0
        applicant["eligibility_units"] = calcs.eligibility_for(0)
        touch(applicant)
        auction["forfeited_deposits_cents"] += amount
        touch(auction)


def restore_supply(auction, area_code, category):
    """CANCELLED / TERMINATED license returns one unit to available_supply."""
    for entry in auction["available_supply"]:
        if entry["area_code"] == area_code and entry["category"] == category:
            entry["available"] += 1
            break
    touch(auction)


def deny_pending_transfers(license_):
    for tr in store.DB["transfers"].values():
        if (tr["license_id"] == license_["id"]
                and tr["status"] in ("FILED", "UNDER_REVIEW", "INFO_REQUESTED")):
            tr["status"] = "DENIED"
            touch(tr)


def terminate_license(license_):
    """ACTIVE -> TERMINATED (FINAL milestone MISSED or renewal DENY):
    pending transfers DENIED and supply restored."""
    license_["status"] = "TERMINATED"
    touch(license_)
    deny_pending_transfers(license_)
    auction = store.DB["auctions"].get(license_["auction_id"])
    if auction is not None:
        restore_supply(auction, license_["area_code"], license_["category"])


def cancel_license(license_):
    """PENDING_PAYMENT -> CANCELLED (payment-deadline lapse): holder's held
    deposit forfeits into the auction, supply returns."""
    license_["status"] = "CANCELLED"
    touch(license_)
    auction = store.DB["auctions"].get(license_["auction_id"])
    holder = store.DB["applicants"].get(license_["holder_applicant_id"])
    if holder is not None and auction is not None:
        forfeit_held(holder, auction)
    if auction is not None:
        restore_supply(auction, license_["area_code"], license_["category"])


# --- the three sweeps ------------------------------------------------------------
def sweep_payment_deadlines(now):
    licenses = sorted(store.DB["licenses"].values(), key=store.created_key)
    for lic in licenses:
        if (lic["status"] == "PENDING_PAYMENT"
                and lic["payment_deadline"] is not None
                and lic["payment_deadline"] < now):
            cancel_license(lic)


def sweep_milestones(now):
    milestones = sorted(store.DB["milestones"].values(), key=store.created_key)
    for ms in milestones:
        if ms["status"] in ("PENDING", "FILED", "REJECTED") and ms["due_date"] < now:
            ms["status"] = "MISSED"
            touch(ms)
            if ms["milestone_type"] == "INTERIM":
                # Deadline acceleration: the sibling FINAL milestone's due date
                # moves INTERIM_MISS_ACCELERATION_DAYS earlier. The sweep
                # processes milestones in created_at order, so a FINAL that
                # thereby falls due is itself caught later in this same pass.
                for sib in store.DB["milestones"].values():
                    if (sib["license_id"] == ms["license_id"]
                            and sib["milestone_type"] == "FINAL"
                            and sib["status"] in ("PENDING", "FILED", "REJECTED")):
                        sib["due_date"] = store.add_days(
                            sib["due_date"], -calcs.INTERIM_MISS_ACCELERATION_DAYS)
                        touch(sib)
            else:  # FINAL missed -> license termination cascade
                lic = store.DB["licenses"].get(ms["license_id"])
                if lic is not None and lic["status"] == "ACTIVE":
                    terminate_license(lic)


def reconcile_leases(now):
    """Reconcile each license's lease fields against its APPROVED lease
    windows: the half-open window [start, end) containing now becomes active;
    an active window whose end has been reached (end <= now) is cleared."""
    licenses = sorted(store.DB["licenses"].values(), key=store.created_key)
    for lic in licenses:
        windows = [tr for tr in store.DB["transfers"].values()
                   if tr["license_id"] == lic["id"]
                   and tr["transfer_type"] == "LEASE"
                   and tr["status"] == "APPROVED"]
        windows.sort(key=store.created_key)
        containing = None
        for w in windows:
            if w["lease_start"] <= now < w["lease_end"]:
                containing = w
                break
        if containing is not None:
            if (lic["active_lease_start"] != containing["lease_start"]
                    or lic["active_lease_end"] != containing["lease_end"]
                    or lic["leased_to_applicant_id"]
                    != containing["transferee_applicant_id"]):
                lic["active_lease_start"] = containing["lease_start"]
                lic["active_lease_end"] = containing["lease_end"]
                lic["leased_to_applicant_id"] = containing["transferee_applicant_id"]
                touch(lic)
        else:
            if (lic["active_lease_end"] is not None
                    and lic["active_lease_end"] <= now):
                lic["active_lease_start"] = None
                lic["active_lease_end"] = None
                lic["leased_to_applicant_id"] = None
                touch(lic)


def run_clock_sweeps():
    now = store.now()
    sweep_payment_deadlines(now)
    sweep_milestones(now)
    reconcile_leases(now)
