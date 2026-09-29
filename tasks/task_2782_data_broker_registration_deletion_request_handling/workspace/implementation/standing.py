"""Registry standing derivation, fee settlement and the delinquency cascade
(PRD 3.1, 3.2, 2.8)."""
import audit
from core import add_days, db, now, ordered, touch

DELINQUENCY_SUSPENSION_DAYS = 90


def _fully_covered(broker):
    """Clause three: every operating state has at least one ACCEPTED filing of
    this broker whose half-open coverage interval contains the clock."""
    codes = broker.get("operating_state_codes") or []
    if not codes:
        return False
    clock = now()
    for code in codes:
        found = False
        for reg in db.registrations.values():
            if (reg["broker_id"] == broker["id"]
                    and reg["state_code"] == code
                    and reg["status"] == "ACCEPTED"
                    and reg["coverage_period_start"] <= clock < reg["coverage_period_end"]):
                found = True
                break
        if not found:
            return False
    return True


def derive_standing(broker, actor, delinquency_cascade=False):
    """Four pinned clauses, first match wins (PRD 3.1). Returns True only when
    the stored value genuinely changed."""
    old = broker["registry_standing"]
    since = broker.get("delinquent_since")
    if since is not None and now() >= add_days(since, DELINQUENCY_SUSPENSION_DAYS):
        new = "SUSPENDED"
    elif broker["open_breach_count"] > 0:
        new = "DELINQUENT"
    elif _fully_covered(broker):
        new = "COMPLIANT"
    else:
        new = "DELINQUENT"

    if new == old:
        return False

    if new in ("DELINQUENT", "SUSPENDED") and old == "COMPLIANT":
        broker["delinquent_since"] = now()
    if new == "COMPLIANT":
        broker["delinquent_since"] = None
    broker["registry_standing"] = new
    touch(broker)
    audit.append(broker, "STANDING_CHANGED", "BROKER", broker["id"], actor,
                 "registry standing moved from %s to %s" % (old, new))
    if delinquency_cascade and new != "COMPLIANT":
        park_recipient_work(broker, actor)
    return True


def park_recipient_work(broker, actor):
    """Cascade links three and four: suspend every ACTIVE recipient that
    carries contract_propagation_required, then park the open propagation work
    of exactly those recipients with deferral_reason BROKER_DELINQUENT."""
    suspended = []
    for rec in ordered([r for r in db.recipients.values()
                        if r["broker_id"] == broker["id"]]):
        if rec["status"] == "ACTIVE" and rec["contract_propagation_required"]:
            rec["status"] = "SUSPENDED"
            touch(rec)
            audit.append(broker, "RECIPIENT_STATUS_CHANGED", "RECIPIENT",
                         rec["id"], actor,
                         "recipient suspended because the broker is no longer "
                         "in good standing")
            suspended.append(rec)
    for rec in suspended:
        for task in ordered([t for t in db.tasks.values()
                             if t["recipient_id"] == rec["id"]]):
            if task["status"] in ("PENDING", "DISPATCHED"):
                task["status"] = "DEFERRED"
                task["deferral_reason"] = "BROKER_DELINQUENT"
                touch(task)
                audit.append(broker, "PROPAGATION_DEFERRED",
                             "PROPAGATION_TASK", task["id"], actor,
                             "propagation deferred because the broker is "
                             "delinquent")


def refund_charged_fee(broker, reg):
    """Move charged_fee_cents from paid back to credit, then zero it.
    fee_deposited_cents never changes (PRD 2.7 conservation law)."""
    amount = reg.get("charged_fee_cents") or 0
    if amount:
        broker["fee_paid_cents"] -= amount
        broker["fee_credit_cents"] += amount
        touch(broker)
    reg["charged_fee_cents"] = 0


def settle_fee_delta(broker, delta):
    """Acceptance settlement: negative delta releases credit, positive delta
    consumes it."""
    if delta == 0:
        return
    if delta < 0:
        broker["fee_paid_cents"] -= -delta
        broker["fee_credit_cents"] += -delta
    else:
        broker["fee_paid_cents"] += delta
        broker["fee_credit_cents"] -= delta
    touch(broker)
