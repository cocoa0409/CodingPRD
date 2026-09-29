"""Transactional multi-link cascades (PRD sections 2.7, 3.3, 3.4, 3.7, 3.9)."""

import calc
import db
import derive

SPONSOR_SUSPENDABLE_STATES = ("LICENSED", "RENEWAL_PENDING")
OPEN_APPLICATION_STATES = ("DRAFT", "SUBMITTED", "DEFICIENT")


def suspend_sponsored_salespersons(dealer):
    """Every salesperson in LICENSED or RENEWAL_PENDING moves to SUSPENDED_BY_SPONSOR."""
    moved = []
    for person in db.where("salesperson", sponsoring_dealer_id=dealer["id"]):
        if person["license_status"] in SPONSOR_SUSPENDABLE_STATES:
            person["license_status"] = "SUSPENDED_BY_SPONSOR"
            db.touch(person)
            moved.append(person)
    return moved


def reinstate_sponsored_salespersons(dealer):
    """On the sponsor's reinstatement each SUSPENDED_BY_SPONSOR row returns or expires."""
    moved = []
    reference = db.today()
    for person in db.where("salesperson", sponsoring_dealer_id=dealer["id"]):
        if person["license_status"] != "SUSPENDED_BY_SPONSOR":
            continue
        expires = person.get("license_expires_on")
        person["license_status"] = "LICENSED" if expires is not None and expires >= reference else "EXPIRED"
        db.touch(person)
        moved.append(person)
    return moved


def void_open_applications(dealer):
    moved = []
    for application in db.where("license_application", dealer_id=dealer["id"]):
        if application["status"] in OPEN_APPLICATION_STATES:
            application["status"] = "VOID_SPONSOR_CANCELLED"
            db.touch(application)
            moved.append(application)
    return moved


def moot_open_disputes(dealer):
    """Termination finalisation moots every open rate dispute naming the dealership."""
    moved = []
    for dispute in db.where("warranty_rate_dispute", dealer_id=dealer["id"]):
        if dispute["status"] in derive.OPEN_DISPUTE_STATES:
            dispute["status"] = "DISMISSED_MOOT"
            db.touch(dispute)
            moved.append(dispute)
    return moved


def release_docket(protest):
    """Free the room interval and the day slot held by a protest."""
    room = db.get("hearing_room", protest.get("hearing_room_id"))
    protest["hearing_room_id"] = None
    protest["hearing_start_at"] = None
    protest["hearing_end_at"] = None
    protest["hearing_session_count"] = None
    protest["evidence_deadline_at"] = None
    db.touch(protest)
    if room is not None:
        derive.set_counter(room, "booked_hearing_count", derive.booked_hearing_count(room["id"]))
        db.touch(room)
    return room


def resolve_filing_when_quiet(filing):
    """PROTEST_PENDING -> PROTEST_RESOLVED once no protest is still live."""
    if filing is None or filing["status"] != "PROTEST_PENDING":
        return False
    for protest in derive.protests_for_filing(filing["id"]):
        if protest["status"] in derive.LIVE_PROTEST_STATES:
            return False
    filing["status"] = "PROTEST_RESOLVED"
    db.touch(filing)
    return True


def dealer_leaves_licensed(dealer):
    """Shared tail of every transition that takes a dealership out of LICENSED."""
    suspend_sponsored_salespersons(dealer)
    db.touch(dealer)


def apply_dealer_point_thresholds(dealer):
    """The two disciplinary thresholds of PRD 3.9, both cascading."""
    points = derive.dealer_points(dealer["id"])
    derive.set_counter(dealer, "disciplinary_points", points)
    if dealer["license_status"] != "LICENSED":
        return None
    if points >= calc.DEALER_REVOCATION_POINTS:
        dealer["license_status"] = "REVOKED"
        dealer["suspension_reason"] = "NONE"
        suspend_sponsored_salespersons(dealer)
        void_open_applications(dealer)
        db.touch(dealer)
        return "REVOKED"
    if points >= calc.DEALER_SUSPENSION_POINTS:
        dealer["license_status"] = "SUSPENDED"
        dealer["suspension_reason"] = "DISCIPLINARY_POINTS"
        suspend_sponsored_salespersons(dealer)
        db.touch(dealer)
        return "SUSPENDED"
    return None


def advance_salesperson_discipline(salesperson):
    """Complaint resolutions advance the discipline dimension; only the sweep rolls back."""
    if salesperson is None:
        return
    points = derive.salesperson_points(salesperson["id"])
    derive.set_counter(salesperson, "disciplinary_points", points)
    status = salesperson["discipline_status"]
    if points >= calc.SALESPERSON_SUSPENSION_POINTS:
        if status != "SUSPENDED_DISCIPLINARY":
            salesperson["discipline_status"] = "SUSPENDED_DISCIPLINARY"
            db.touch(salesperson)
    elif points >= calc.SALESPERSON_PROBATION_POINTS and status == "CLEAR":
        salesperson["discipline_status"] = "PROBATION"
        db.touch(salesperson)


def is_delinquent(complaint, reference_date):
    if complaint["status"] != "SANCTIONED":
        return False
    due_on = complaint.get("restitution_due_on")
    if due_on is None or not (due_on < reference_date):
        return False
    return (complaint.get("restitution_paid_cents") or 0) < (
        complaint.get("restitution_ordered_cents") or 0
    )


def restore_dealer_after_settlement(dealer):
    """The compensating reversal for a delinquency suspension (PRD 3.9)."""
    if dealer["license_status"] != "SUSPENDED" or dealer["suspension_reason"] != "RESTITUTION_DELINQUENT":
        return False
    reference = db.today()
    for complaint in db.where("consumer_complaint", dealer_id=dealer["id"]):
        if is_delinquent(complaint, reference):
            return False
    outstanding = derive.restitution_outstanding_cents(dealer["id"])
    if outstanding != 0:
        return False
    if derive.dealer_points(dealer["id"]) >= calc.DEALER_SUSPENSION_POINTS:
        return False
    expires = dealer.get("license_expires_on")
    if expires is None or expires < reference:
        return False
    dealer["license_status"] = "LICENSED"
    dealer["suspension_reason"] = "NONE"
    reinstate_sponsored_salespersons(dealer)
    db.touch(dealer)
    return True


def finalize_termination(filing):
    """The longest cascade in the system (PRD 3.4)."""
    dealer = db.get("dealer", filing.get("affected_dealer_id"))
    if dealer is None:
        return
    if dealer["franchise_status"] == "TERMINATION_PENDING":
        dealer["franchise_status"] = "TERMINATED"
    if dealer["dealer_type"] == "NEW_MOTOR_VEHICLE" and dealer["license_status"] == "LICENSED":
        dealer["license_status"] = "CANCELLED"
        dealer["suspension_reason"] = "NONE"
    moot_open_disputes(dealer)
    suspend_sponsored_salespersons(dealer)
    db.touch(dealer)
