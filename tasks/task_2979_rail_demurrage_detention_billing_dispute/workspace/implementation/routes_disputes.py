"""Bunching claims and the two-round dispute ladder (PRD §3.6 and §3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import guards
import schema
from auth import (ROLE_ADJUDICATOR, ROLE_BILLING, ROLE_CUSTOMER, ROLE_REGULATOR,
                  authenticate, require_owner, segregation_bar)
from calc import (EVIDENCE_WEIGHT_POINTS, INFO_REQUEST_DAYS,
                  adjudication_days, adjudication_due_at, round_half_up_cents)
from cascade import reprice_charge
from clockcal import add_days, date_of, dates_between, date_span_count, eod, nth_business
from derive import (charge_of_cycle, claim_json, cycles_of_customer,
                    dispute_evidence_weight, dispute_json, evidence_json,
                    evidence_of_dispute, invoice_status,
                    live_charges_of_invoice)
from envelope import listing, ok
from errors import fail
from store import base_record, db, touch

bp = Blueprint("disputes", __name__)

CLAIM_METHODS = ("ORDERED_VS_CAPACITY", "ROLLING_AVERAGE_BASELINE")
MAX_CLUSTER_DATES = 14
ROLLING_WINDOW_DATES = 7

DISPUTE_SCOPES = ("SINGLE_CHARGE", "WHOLE_INVOICE")
DISPUTE_GROUNDS = ("RAILROAD_CAUSED_DELAY", "BUNCHING", "NOTIFICATION_FAILURE",
                   "RATE_UNREASONABLE", "CLOCK_BASIS_ERROR")
EVIDENCE_TYPES = ("SWITCH_LIST", "GATE_LOG", "EMAIL_NOTICE",
                  "TRACK_EMBARGO_NOTICE", "WEIGHT_CERTIFICATE")
DECISIONS = ("ALLOWED", "PARTIALLY_ALLOWED", "DENIED")
DISPUTABLE_INVOICE_STATUSES = ("ISSUED", "PARTIALLY_DISPUTED", "ADJUSTED")


# --------------------------------------------------------------------------
# bunching claims (PRD §3.6)
# --------------------------------------------------------------------------

def _windows_overlap(a_start, a_end, b_start, b_end):
    """Closed intervals: sharing a single endpoint date is an overlap."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/bunching-claims")
def create_claim():
    actor = authenticate(ROLE_CUSTOMER)
    data = schema.body()
    with db.lock:
        # Band 4 outranks band 7, so a consignee naming somebody else is told it
        # does not own the row before the identifier is even resolved.
        raw_customer = schema.opt_ref(data, "customer_id")
        if raw_customer is not None:
            require_owner(actor, raw_customer)
            guards.customer(raw_customer)

        customer_id = schema.req_ref(data, "customer_id")
        start = schema.req_instant(data, "cluster_window_start")
        end = schema.req_instant(data, "cluster_window_end")
        method = schema.req_enum(data, "method", CLAIM_METHODS)

        # Band 20.
        if start > end:
            fail("ERR_INVALID_CLUSTER_WINDOW",
                 "cluster_window_start must not be after cluster_window_end.")
        if date_span_count(date_of(start), date_of(end)) > MAX_CLUSTER_DATES:
            fail("ERR_INVALID_CLUSTER_WINDOW",
                 "A cluster window may span at most %d calendar dates."
                 % MAX_CLUSTER_DATES)

        # Band 21: only a granted window blocks a fresh one.
        for other in db.claims.values():
            if other["customer_id"] != customer_id:
                continue
            if other["status"] not in ("GRANTED", "PARTIALLY_GRANTED"):
                continue
            if _windows_overlap(date_of(start), date_of(end),
                                date_of(other["cluster_window_start"]),
                                date_of(other["cluster_window_end"])):
                fail("ERR_CLUSTER_WINDOW_OVERLAP",
                     "A granted claim already covers part of this window.")

        rec = base_record("claim")
        rec.update({
            "customer_id": customer_id,
            "cluster_window_start": start,
            "cluster_window_end": end,
            "method": method,
            "baseline_per_day": 0,
            "delivered_car_count": 0,
            "exempted_cycle_ids": [],
            "exempt_days_granted": 0,
            "cluster_chargeable_days": 0,
            "status": "SUBMITTED",
        })
        db.claims[rec["id"]] = rec
        return ok(claim_json(rec), 201)


def _cluster_set(claim):
    start = claim["cluster_window_start"]
    end = claim["cluster_window_end"]
    rows = []
    for cycle in cycles_of_customer(claim["customer_id"]):
        if cycle["movement_status"] == "VOIDED":
            continue
        placed = cycle.get("constructive_placement_at")
        if placed is None or placed < start or placed > end:
            continue
        rows.append(cycle)
    return rows


def _rolling_baseline(claim):
    """The seven calendar dates immediately preceding the window's own start
    date, counted then integer-divided by seven."""
    first_date = date_of(claim["cluster_window_start"])
    history = set(dates_between(add_days(first_date, -ROLLING_WINDOW_DATES),
                                add_days(first_date, -1)))
    count = 0
    for cycle in cycles_of_customer(claim["customer_id"]):
        if cycle["movement_status"] == "VOIDED":
            continue
        placed = cycle.get("constructive_placement_at")
        if placed is not None and date_of(placed) in history:
            count += 1
    return count // ROLLING_WINDOW_DATES


@bp.post("/bunching-claims/<clid>/analyze")
def analyze_claim(clid):
    authenticate(ROLE_ADJUDICATOR)
    with db.lock:
        claim = guards.claim(clid)
        if claim["status"] != "SUBMITTED":
            fail("ERR_CLAIM_INVALID_STATE",
                 "Only a SUBMITTED claim can be analysed.")

        cluster = _cluster_set(claim)
        if not cluster:
            fail("ERR_CLAIM_NO_DELIVERIES",
                 "No delivery falls inside this cluster window.")

        cluster_chargeable = 0
        for cycle in cluster:
            charge = charge_of_cycle(cycle["id"])
            if charge is not None:
                cluster_chargeable += charge["chargeable_days"]

        customer = db.customers[claim["customer_id"]]
        if claim["method"] == "ORDERED_VS_CAPACITY":
            baseline = customer["normal_daily_placement_capacity"]
        else:
            baseline = _rolling_baseline(claim)

        # Attribute date by date; the consignee absorbs the FIRST baseline
        # arrivals of a date, so the exempted cars are the last ones.
        exempted = []
        for day in dates_between(date_of(claim["cluster_window_start"]),
                                 date_of(claim["cluster_window_end"])):
            arrivals = [c for c in cluster
                        if date_of(c["constructive_placement_at"]) == day]
            arrivals.sort(key=lambda c: (c["constructive_placement_at"],
                                         c["created_at"], c["_seq"]))
            excess = len(arrivals) - baseline
            if excess > 0:
                exempted.extend(arrivals[len(arrivals) - excess:])

        # Forgiveness grows with position in the cluster, capped at what the
        # line actually accrued.
        planned = []
        granted = 0
        for position, cycle in enumerate(exempted, start=1):
            charge = charge_of_cycle(cycle["id"])
            if charge is None:
                continue
            value = position if position < charge["chargeable_days"] else charge["chargeable_days"]
            planned.append((cycle, charge, value))
            granted += value

        claim["baseline_per_day"] = baseline
        claim["delivered_car_count"] = len(cluster)
        claim["cluster_chargeable_days"] = cluster_chargeable
        claim["exempt_days_granted"] = granted
        if granted == 0:
            # A denied claim touches no charge line at all.
            claim["exempted_cycle_ids"] = []
            claim["status"] = "DENIED"
        else:
            for cycle, charge, value in planned:
                charge["bunching_exempt_days"] = value
                reprice_charge(cycle, charge)
            claim["exempted_cycle_ids"] = [c["id"] for c, _ch, _v in planned]
            claim["status"] = ("GRANTED" if granted == cluster_chargeable
                               else "PARTIALLY_GRANTED")
        touch(claim)
        return ok(claim_json(claim))


# --------------------------------------------------------------------------
# filing a dispute (PRD §3.8)
# --------------------------------------------------------------------------

def _reported_gross(invoice):
    """The invoice's total_gross_cents as the API reports it: zero while the
    invoice is still DRAFT, because the totals are part of issuing."""
    if invoice_status(invoice) == "DRAFT":
        return 0
    return sum(ch["gross_amount_cents"]
               for ch in live_charges_of_invoice(invoice["id"]))


@bp.post("/disputes")
def create_dispute():
    actor = authenticate(ROLE_CUSTOMER)
    data = schema.body()
    with db.lock:
        # Band 7 in declared order, with the ownership band interleaved as soon
        # as the owning invoice is known.
        invoice = None
        raw_invoice = schema.opt_ref(data, "invoice_id")
        if raw_invoice is not None:
            invoice = guards.invoice(raw_invoice)
            require_owner(actor, invoice["customer_id"])
        charge = None
        raw_charge = schema.opt_ref(data, "demurrage_charge_id")
        if raw_charge is not None:
            charge = guards.charge(raw_charge)
        claim = None
        raw_claim = schema.opt_ref(data, "bunching_claim_id")
        if raw_claim is not None:
            claim = guards.claim(raw_claim)
        superseded = None
        raw_superseded = schema.opt_ref(data, "supersedes_dispute_id")
        if raw_superseded is not None:
            superseded = guards.dispute(raw_superseded)

        # Band 8.
        schema.req_ref(data, "invoice_id")
        scope = schema.req_enum(data, "scope", DISPUTE_SCOPES)
        grounds = schema.req_enum(data, "grounds", DISPUTE_GROUNDS)
        narrative = schema.req_str(data, "narrative", 1, 2000)
        claimed = schema.req_int(data, "claimed_credit_cents", 1)
        expected = schema.req_int(data, "expected_invoice_version")

        # Band 11.
        if expected != invoice["version"]:
            fail("ERR_INVOICE_VERSION_STALE",
                 "expected_invoice_version does not match the invoice.")

        # Band 14: the pairing rules, then the attachment rule.
        if scope == "SINGLE_CHARGE" and charge is None:
            fail("ERR_DISPUTE_SCOPE_MISMATCH",
                 "A SINGLE_CHARGE dispute must name demurrage_charge_id.")
        if scope == "WHOLE_INVOICE" and charge is not None:
            fail("ERR_DISPUTE_SCOPE_MISMATCH",
                 "A WHOLE_INVOICE dispute must not name demurrage_charge_id.")
        if grounds == "BUNCHING" and claim is None:
            fail("ERR_DISPUTE_SCOPE_MISMATCH",
                 "BUNCHING grounds must rest on a bunching_claim_id.")
        if grounds != "BUNCHING" and claim is not None:
            fail("ERR_DISPUTE_SCOPE_MISMATCH",
                 "bunching_claim_id is only meaningful on BUNCHING grounds.")
        if charge is not None and charge["invoice_id"] != invoice["id"]:
            fail("ERR_CHARGE_INVOICE_MISMATCH",
                 "The named charge is not attached to the named invoice.")
        if superseded is not None and (
                superseded["invoice_id"] != invoice["id"]
                or superseded["status"] != "DECIDED"):
            fail("ERR_SUPERSEDE_TARGET_INVALID",
                 "A superseded dispute must be a DECIDED dispute on this "
                 "invoice.")

        # Band 25: the consignee's own claim ceiling.
        if scope == "SINGLE_CHARGE":
            ceiling = charge["gross_amount_cents"]
        else:
            ceiling = _reported_gross(invoice)
        if claimed > ceiling:
            fail("ERR_CLAIM_EXCEEDS_CHARGE",
                 "claimed_credit_cents exceeds the gross of the target set.")

        rec = base_record("dispute")
        rec.update({
            # The consignee is copied off the invoice; a caller-supplied value
            # is ignored outright.
            "customer_id": invoice["customer_id"],
            "invoice_id": invoice["id"],
            "demurrage_charge_id": None if charge is None else charge["id"],
            "bunching_claim_id": None if claim is None else claim["id"],
            "supersedes_dispute_id": (None if superseded is None
                                      else superseded["id"]),
            "scope": scope,
            "grounds": grounds,
            "narrative": narrative,
            "claimed_credit_cents": claimed,
            "target_charge_count": 0,
            "allowance_pct": None,
            "allowed_credit_cents": 0,
            "decision": "PENDING",
            "decision_rationale": None,
            "round_number": 1,
            "info_request_count": 0,
            "submitted_at": None,
            "adjudication_due_at": None,
            "first_level_adjudicator_id": None,
            "appeal_adjudicator_id": None,
            "status": "DRAFT",
        })
        db.disputes[rec["id"]] = rec
        # Filing touches the invoice's version and its dispute_count, but not
        # one cent of the money.
        touch(invoice)
        return ok(dispute_json(rec), 201)


@bp.get("/disputes/<did>")
def get_dispute(did):
    actor = authenticate(ROLE_CUSTOMER, ROLE_ADJUDICATOR, ROLE_REGULATOR,
                         ROLE_BILLING)
    with db.lock:
        rec = guards.dispute(did)
        require_owner(actor, rec["customer_id"])
        return ok(dispute_json(rec))


_DISPUTE_FILTERS = ("customer_id", "invoice_id", "demurrage_charge_id",
                    "bunching_claim_id", "supersedes_dispute_id", "status")


@bp.get("/disputes")
def list_disputes():
    actor = authenticate(ROLE_CUSTOMER, ROLE_ADJUDICATOR, ROLE_REGULATOR,
                         ROLE_BILLING)
    with db.lock:
        rows = db.ordered("disputes")
        for name in _DISPUTE_FILTERS:
            value = request.args.get(name)
            if value is not None:
                rows = [r for r in rows if r[name] == value]
        if actor.is_customer:
            rows = [r for r in rows if r["customer_id"] == actor.user_id]
        return listing(rows, dispute_json)


# --------------------------------------------------------------------------
# the evidence file
# --------------------------------------------------------------------------

@bp.post("/disputes/<did>/evidence")
def create_evidence(did):
    actor = authenticate(ROLE_CUSTOMER)
    with db.lock:
        dispute = guards.dispute(did)
        require_owner(actor, dispute["customer_id"])
        data = schema.body()
        kind = schema.req_enum(data, "evidence_type", EVIDENCE_TYPES)
        observed_at = schema.req_instant(data, "observed_at")
        description = schema.req_str(data, "description", 1, 500)

        if dispute["status"] not in ("DRAFT", "INFO_REQUESTED"):
            fail("ERR_DISPUTE_INVALID_STATE",
                 "Exhibits may only be filed while the evidence file is open.")

        rec = base_record("evidence", versioned=False)
        rec.update({
            "demurrage_dispute_id": dispute["id"],
            "evidence_type": kind,
            "observed_at": observed_at,
            "description": description,
            # Fixed by class and derived server-side; a caller-supplied value is
            # ignored.
            "weight_points": EVIDENCE_WEIGHT_POINTS[kind],
        })
        db.evidence[rec["id"]] = rec
        return ok(evidence_json(rec), 201)


@bp.get("/disputes/<did>/evidence")
def list_evidence(did):
    actor = authenticate(ROLE_CUSTOMER, ROLE_ADJUDICATOR, ROLE_REGULATOR)
    with db.lock:
        dispute = guards.dispute(did)
        require_owner(actor, dispute["customer_id"])
        return listing(evidence_of_dispute(dispute["id"]), evidence_json)


# --------------------------------------------------------------------------
# the target set and the round timeline
# --------------------------------------------------------------------------

def _release_key(charge):
    cycle = db.cycles.get(charge["placement_cycle_id"])
    released = None if cycle is None else cycle.get("released_at")
    return (released is None, released, charge["created_at"], charge["id"])


def _resolved_targets(dispute, require_status=None):
    """The target set in the deterministic order §3.8 fixes: the cycle's
    released_at ascending, then the charge's own created_at ascending."""
    if dispute["scope"] == "SINGLE_CHARGE":
        charge = db.charges.get(dispute["demurrage_charge_id"])
        rows = [] if charge is None else [charge]
    else:
        rows = list(live_charges_of_invoice(dispute["invoice_id"]))
    if require_status is not None:
        rows = [c for c in rows if c["status"] == require_status]
    rows.sort(key=_release_key)
    return rows


def _tariff_base(targets):
    """The adjudication base published by the tariff pinned to the charges."""
    for charge in targets:
        cycle = db.cycles.get(charge["placement_cycle_id"])
        if cycle is None:
            continue
        tariff = db.tariffs.get(cycle["tariff_rule_set_id"])
        if tariff is not None:
            return tariff["adjudication_days_base"]
    return 20


def _set_round_deadline(dispute, targets, from_instant):
    days = adjudication_days(dispute["round_number"], _tariff_base(targets),
                             dispute["grounds"],
                             dispute_evidence_weight(dispute["id"]))
    dispute["adjudication_due_at"] = adjudication_due_at(
        date_of(from_instant), days)


# --------------------------------------------------------------------------
# submission, review, information requests and resubmission
# --------------------------------------------------------------------------

@bp.post("/disputes/<did>/submit")
def submit_dispute(did):
    actor = authenticate(ROLE_CUSTOMER)
    with db.lock:
        dispute = guards.dispute(did)
        require_owner(actor, dispute["customer_id"])
        invoice = db.invoices[dispute["invoice_id"]]

        # Band 10, in the order §3.8 gives: the dispute, then the invoice, then
        # the lines.
        if dispute["status"] != "DRAFT":
            fail("ERR_DISPUTE_INVALID_STATE", "Only a DRAFT dispute can be submitted.")
        if invoice_status(invoice) not in DISPUTABLE_INVOICE_STATUSES:
            fail("ERR_INVOICE_NOT_DISPUTABLE",
                 "This invoice is not in a disputable state.")
        targets = _resolved_targets(dispute)
        for charge in targets:
            if charge["status"] != "FINAL":
                fail("ERR_CHARGE_INVALID_STATE",
                     "Every target charge must be FINAL to be disputed.")

        # Band 18, then band 24, then band 26.
        deadline = invoice["dispute_deadline_at"]
        if deadline is not None and db.now() > deadline:
            fail("ERR_DISPUTE_WINDOW_CLOSED",
                 "The invoice's dispute window has closed.")
        if not evidence_of_dispute(dispute["id"]):
            fail("ERR_DISPUTE_NO_EVIDENCE",
                 "A dispute must carry at least one exhibit to be submitted.")
        if dispute["grounds"] == "BUNCHING":
            claim = db.claims.get(dispute["bunching_claim_id"])
            if claim is None or claim["status"] not in ("GRANTED",
                                                        "PARTIALLY_GRANTED"):
                fail("ERR_BUNCHING_CLAIM_NOT_GRANTED",
                     "BUNCHING grounds require a granted bunching claim.")

        dispute["status"] = "SUBMITTED"
        dispute["submitted_at"] = db.now()
        dispute["target_charge_count"] = len(targets)
        _set_round_deadline(dispute, targets, dispute["submitted_at"])
        for charge in targets:
            charge["status"] = "DISPUTED"
            cycle = db.cycles.get(charge["placement_cycle_id"])
            if cycle is not None:
                cycle["billing_status"] = "DISPUTED"
        touch(dispute)
        touch(invoice)
        touch(db.customers[dispute["customer_id"]])
        return ok(dispute_json(dispute))


@bp.post("/disputes/<did>/begin-review")
def begin_review(did):
    actor = authenticate(ROLE_ADJUDICATOR)
    with db.lock:
        dispute = guards.dispute(did)
        # Band 5 sits above the state band, so the barred adjudicator is turned
        # away before the transition is even considered.
        segregation_bar(actor, dispute)
        if dispute["status"] not in ("SUBMITTED", "APPEALED"):
            fail("ERR_DISPUTE_INVALID_STATE",
                 "A review can only be taken up on a submitted or appealed "
                 "dispute.")

        if dispute["round_number"] == 1:
            if dispute["first_level_adjudicator_id"] is None:
                dispute["first_level_adjudicator_id"] = actor.user_id
        else:
            # first_level_adjudicator_id is deliberately left untouched, which
            # is what keeps the segregation bar alive across the round change.
            dispute["appeal_adjudicator_id"] = actor.user_id
        dispute["status"] = "UNDER_REVIEW"
        touch(dispute)
        return ok(dispute_json(dispute))


def _requested_items(data):
    """Accepts either a non-empty string or a non-empty list of strings."""
    if not schema.present(data, "requested_items"):
        schema._bad("requested_items", "is required")
    value = data["requested_items"]
    if isinstance(value, str):
        if len(value) < 1:
            schema._bad("requested_items", "must not be empty")
        return value
    if isinstance(value, list) and value:
        for item in value:
            if not isinstance(item, str) or item == "":
                schema._bad("requested_items", "must be a list of strings")
        return list(value)
    schema._bad("requested_items", "must be a string or a non-empty list")


@bp.post("/disputes/<did>/request-info")
def request_info(did):
    authenticate(ROLE_ADJUDICATOR)
    with db.lock:
        dispute = guards.dispute(did)
        data = schema.body()
        _requested_items(data)

        if dispute["status"] != "UNDER_REVIEW":
            fail("ERR_DISPUTE_INVALID_STATE",
                 "Information can only be requested on a dispute under review.")
        if dispute["info_request_count"] >= 2:
            fail("ERR_INFO_REQUEST_LIMIT",
                 "This dispute has exhausted its information requests.")

        dispute["status"] = "INFO_REQUESTED"
        dispute["info_request_count"] += 1
        # The deadline is REPLACED, not extended, so it can move either way.
        dispute["adjudication_due_at"] = eod(
            nth_business(date_of(db.now()), INFO_REQUEST_DAYS))
        dispute["_info_request_seq"] = db.next_seq()
        touch(dispute)
        return ok(dispute_json(dispute))


@bp.post("/disputes/<did>/resubmit")
def resubmit_dispute(did):
    actor = authenticate(ROLE_CUSTOMER)
    with db.lock:
        dispute = guards.dispute(did)
        require_owner(actor, dispute["customer_id"])
        if dispute["status"] != "INFO_REQUESTED":
            fail("ERR_DISPUTE_INVALID_STATE",
                 "Only an information-requested dispute can be resubmitted.")

        marker = dispute.get("_info_request_seq", 0)
        fresh = [e for e in evidence_of_dispute(dispute["id"])
                 if e["_seq"] > marker]
        if not fresh:
            fail("ERR_DISPUTE_NO_EVIDENCE",
                 "At least one exhibit must be filed after the information "
                 "request.")

        dispute["status"] = "SUBMITTED"
        dispute["submitted_at"] = db.now()
        # adjudication_due_at deliberately stays where request-info put it.
        touch(dispute)
        return ok(dispute_json(dispute))


# --------------------------------------------------------------------------
# deciding the round, where the credit is granted
# --------------------------------------------------------------------------

def _decision_targets(dispute):
    require = None if dispute["scope"] == "SINGLE_CHARGE" else "DISPUTED"
    return _resolved_targets(dispute, require)


def _allocate(targets, pct, claimed):
    """Per-line ROUND_HALF_UP, summed, then trimmed by a BACKWARDS waterfall."""
    allocated = []
    for charge in targets:
        gross = charge["gross_amount_cents"]
        value = round_half_up_cents(gross, pct)
        if value > gross:
            value = gross
        if value < 0:
            value = 0
        allocated.append(value)
    excess = sum(allocated) - claimed
    index = len(allocated) - 1
    while excess > 0 and index >= 0:
        take = allocated[index] if allocated[index] < excess else excess
        allocated[index] -= take
        excess -= take
        index -= 1
    return allocated


@bp.post("/disputes/<did>/decide")
def decide_dispute(did):
    actor = authenticate(ROLE_ADJUDICATOR)
    with db.lock:
        dispute = guards.dispute(did)
        segregation_bar(actor, dispute)
        data = schema.body()
        decision = schema.req_enum(data, "decision", DECISIONS)
        pct = schema.req_number(data, "allowance_pct", 0, 1)
        rationale = schema.req_str(data, "decision_rationale", 1, 2000)

        if dispute["status"] != "UNDER_REVIEW":
            fail("ERR_DISPUTE_INVALID_STATE",
                 "Only a dispute under review can be decided.")

        # Band 26: allowance_pct must agree with the decision.
        share = Decimal(str(pct))
        if decision == "ALLOWED" and share != Decimal(1):
            fail("ERR_ALLOWANCE_PCT_MISMATCH",
                 "An ALLOWED decision demands an allowance_pct of exactly 1.")
        if decision == "DENIED" and share != Decimal(0):
            fail("ERR_ALLOWANCE_PCT_MISMATCH",
                 "A DENIED decision demands an allowance_pct of exactly 0.")
        if decision == "PARTIALLY_ALLOWED" and not (
                Decimal(0) < share < Decimal(1)):
            fail("ERR_ALLOWANCE_PCT_MISMATCH",
                 "A PARTIALLY_ALLOWED decision demands an allowance_pct "
                 "strictly between 0 and 1.")

        targets = _decision_targets(dispute)
        allocated = _allocate(targets, pct, dispute["claimed_credit_cents"])

        # Remember what the lines carried, so an appeal can put it all back.
        dispute["_pre_credit"] = {ch["id"]: ch["credit_applied_cents"]
                                  for ch in targets}
        dispute["_decided_targets"] = [ch["id"] for ch in targets]

        for charge, value in zip(targets, allocated):
            charge["credit_applied_cents"] = value
            charge["status"] = "ADJUSTED" if value > 0 else "FINAL"
            cycle = db.cycles.get(charge["placement_cycle_id"])
            if cycle is not None:
                cycle["billing_status"] = "ADJUSTED" if value > 0 else "INVOICED"

        dispute["allowed_credit_cents"] = sum(allocated)
        dispute["allowance_pct"] = pct
        dispute["decision"] = decision
        dispute["decision_rationale"] = rationale
        dispute["status"] = "DECIDED"
        touch(dispute)
        touch(db.invoices[dispute["invoice_id"]])
        touch(db.customers[dispute["customer_id"]])
        return ok(dispute_json(dispute))


@bp.post("/disputes/<did>/appeal")
def appeal_dispute(did):
    actor = authenticate(ROLE_CUSTOMER)
    with db.lock:
        dispute = guards.dispute(did)
        require_owner(actor, dispute["customer_id"])
        data = schema.body()
        schema.req_str(data, "appeal_narrative", 1, 2000)

        if dispute["status"] != "DECIDED":
            fail("ERR_DISPUTE_INVALID_STATE",
                 "Only a decided dispute can be appealed.")
        if dispute["round_number"] >= 2:
            fail("ERR_APPEAL_LIMIT", "This dispute has already been appealed.")

        # A full reversal of the first-level credit, line by line.
        pre_credit = dispute.get("_pre_credit", {})
        for charge_id in dispute.get("_decided_targets", []):
            charge = db.charges.get(charge_id)
            if charge is None:
                continue
            charge["credit_applied_cents"] = pre_credit.get(charge_id, 0)
            charge["status"] = "DISPUTED"
            cycle = db.cycles.get(charge["placement_cycle_id"])
            if cycle is not None:
                cycle["billing_status"] = "DISPUTED"

        dispute["round_number"] = 2
        dispute["decision"] = "PENDING"
        dispute["allowance_pct"] = None
        dispute["allowed_credit_cents"] = 0
        dispute["decision_rationale"] = None
        dispute["status"] = "APPEALED"
        # The second round's clock starts when the appeal is filed, and the
        # appeal allowance ignores the evidence file entirely.
        dispute["submitted_at"] = db.now()
        _set_round_deadline(dispute, _resolved_targets(dispute, "DISPUTED"),
                            dispute["submitted_at"])
        touch(dispute)
        touch(db.invoices[dispute["invoice_id"]])
        return ok(dispute_json(dispute))
