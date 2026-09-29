"""The operational sweep run inside every clock advance (PRD section 2.5)."""

import calc
import cascade
import db
import derive


def run(new_date):
    """Sweep every collection in created_at ascending order and report the counters."""
    swept_dealers = set()
    swept_salespersons = set()
    swept_protests = set()
    swept_complaints = set()

    def mark_salespersons(rows):
        for person in rows:
            swept_salespersons.add(person["id"])

    # 1. Expire dealer licences whose license_expires_on is earlier than the new date.
    for dealer in db.ordered("dealer"):
        derive.set_counter(dealer, "disciplinary_points", derive.dealer_points(dealer["id"], new_date))
        derive.set_counter(
            dealer, "restitution_outstanding_cents", derive.restitution_outstanding_cents(dealer["id"])
        )
        expires = dealer.get("license_expires_on")
        if dealer["license_status"] == "LICENSED" and expires is not None and expires < new_date:
            dealer["license_status"] = "EXPIRED"
            dealer["suspension_reason"] = "NONE"
            mark_salespersons(cascade.suspend_sponsored_salespersons(dealer))
            db.touch(dealer)
            swept_dealers.add(dealer["id"])

    # 2. Suspend any dealer owing restitution on a sanctioned complaint past its deadline.
    for dealer in db.ordered("dealer"):
        delinquent = [
            complaint
            for complaint in db.where("consumer_complaint", dealer_id=dealer["id"])
            if cascade.is_delinquent(complaint, new_date)
        ]
        for complaint in delinquent:
            swept_complaints.add(complaint["id"])
        if not delinquent or dealer["license_status"] != "LICENSED":
            continue
        dealer["license_status"] = "SUSPENDED"
        dealer["suspension_reason"] = "RESTITUTION_DELINQUENT"
        mark_salespersons(cascade.suspend_sponsored_salespersons(dealer))
        db.touch(dealer)
        swept_dealers.add(dealer["id"])

    # 3. Expire salesperson licences, then roll discipline back as points age out.
    for person in db.ordered("salesperson"):
        expires = person.get("license_expires_on")
        if expires is not None and expires < new_date:
            if person["license_status"] == "LICENSED":
                person["license_status"] = "EXPIRED"
                db.touch(person)
                swept_salespersons.add(person["id"])
            elif person["license_status"] == "SUSPENDED_BY_SPONSOR":
                person["license_status"] = "EXPIRED"
                db.touch(person)
                swept_salespersons.add(person["id"])
        points = derive.salesperson_points(person["id"], new_date)
        derive.set_counter(person, "disciplinary_points", points)
        status = person["discipline_status"]
        if status == "SUSPENDED_DISCIPLINARY" and points < calc.SALESPERSON_SUSPENSION_POINTS:
            person["discipline_status"] = "REINSTATED"
            db.touch(person)
            swept_salespersons.add(person["id"])
        elif status == "PROBATION" and points < calc.SALESPERSON_PROBATION_POINTS:
            person["discipline_status"] = "CLEAR"
            db.touch(person)
            swept_salespersons.add(person["id"])

    # 4. Harden a decided protest once its 30-day appeal window has lapsed.
    for protest in db.ordered("protest"):
        if protest["status"] not in ("SUSTAINED", "DENIED"):
            continue
        decided_on = protest.get("decided_on")
        if decided_on is None:
            continue
        if new_date > decided_on + calc._timedelta(30):
            protest["status"] = "FINAL"
            db.touch(protest)
            swept_protests.add(protest["id"])

    derive.recompute_all(new_date)

    return {
        "swept_dealer_count": len(swept_dealers),
        "swept_salesperson_count": len(swept_salespersons),
        "swept_protest_count": len(swept_protests),
        "swept_complaint_count": len(swept_complaints),
    }
