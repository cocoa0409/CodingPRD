"""Phased composite setup helpers.

Two disciplines are load-bearing here.

**Phasing.**  Every helper is written so that its own last hop can never
invalidate its own first hop.  Concretely: ``POST /demurrage/placement-cycles``
consumes the rail car's ``version`` (PRD 2.7) and *increments* it on success, so
:func:`make_cycle` always re-reads the car immediately before the create rather
than reusing a version captured earlier.  The same rule applies to the invoice
``version`` consumed by ``POST /demurrage/disputes``.

**Clock parking.**  Every windowed assertion in this suite depends on where the
logical clock sits (PRD 3.9), so the composites park it explicitly at the
stations declared in ``constants`` rather than relying on the cold-start value.

Every helper returns the *response body's* ``data`` object, unwrapped exactly
once by the framework's ``get_success_data``.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    ACCESS_MODE_EMBARGOED,
    CHANNEL_EDI,
    CLOCK_AFTER_RELEASE,
    CLOCK_AT_APPEAL,
    CLOCK_AT_COMPLAINT,
    CLOCK_AT_ISSUE,
    CLOCK_AT_SUBMIT,
    COLD_START_CLOCK,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_CONSTRUCTIVE_AT,
    CYCLE_A_NOTICE_SENT_AT,
    CYCLE_A_RELEASE_AT,
    CYCLE_B_ACTUAL_AT,
    CYCLE_B_CONSTRUCTIVE_AT,
    CYCLE_B_NOTICE_SENT_AT,
    CYCLE_B_RELEASE_AT,
    COMPLAINT_TYPE_BILLING_PRACTICE,
    DECISION_ALLOWED,
    EVIDENCE_SWITCH_LIST,
    FACILITY_KIND_INDUSTRY_TRACK,
    OWNERSHIP_RAILROAD_OWNED,
    REASON_TRACK_FULL,
)
from .test_users import ADMIN, AGENT, OFFICER, make_customer_headers, make_adjudicator_headers


# ---------------------------------------------------------------------------
# Tier 1 - single-resource builders
# ---------------------------------------------------------------------------
def set_clock(api, to_iso8601: str) -> Dict[str, Any]:
    """PRD 3.9 - move the logical clock and return the ``current_utc`` body."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def make_customer(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_customer(f.customer_payload(**overrides), ADMIN), 201
    )


def make_facility(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_facility(f.facility_payload(**overrides), ADMIN), 201
    )


def make_industry_track(api, **overrides) -> Dict[str, Any]:
    """An industry track with the switch buffer disabled.

    ``switch_buffer_minutes`` defaults to 120 (PRD 3.1), which would make a
    second spot at the same facility fail with ``ERR_FACILITY_SWITCH_BUFFER``
    for reasons that have nothing to do with the rule under test.  Tests that
    are *about* the buffer build their own facility.
    """
    base = {
        "kind": FACILITY_KIND_INDUSTRY_TRACK,
        "switch_buffer_minutes": 0,
        "car_spot_capacity": 3,
    }
    base.update(overrides)
    return make_facility(api, **base)


def make_rail_car(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_rail_car(f.rail_car_payload(**overrides), AGENT), 201
    )


def make_draft_tariff(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_tariff_rule_set(f.tariff_payload(**overrides), OFFICER), 201
    )


def make_published_tariff(api, **overrides) -> Dict[str, Any]:
    draft = make_draft_tariff(api, **overrides)
    return get_success_data(api.publish_tariff_rule_set(draft["id"], OFFICER))


def get_cycle(api, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_placement_cycle(cycle_id, ADMIN))


def get_car(api, rail_car_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rail_car(rail_car_id, AGENT))


def get_invoice(api, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_invoice(invoice_id, ADMIN))


def get_customer(api, customer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_customer(customer_id, ADMIN))


def get_dispute(api, dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dispute(dispute_id, ADMIN))


def charges_of_cycle(api, cycle_id: str) -> List[Dict[str, Any]]:
    response = api.list_charges(ADMIN, {"placement_cycle_id": cycle_id})
    return get_success_data(response)


def charge_of_cycle(api, cycle_id: str) -> Dict[str, Any]:
    rows = charges_of_cycle(api, cycle_id)
    assert len(rows) == 1, (
        "expected exactly one charge line on cycle %s, got %d" % (cycle_id, len(rows))
    )
    return rows[0]


def charges_of_invoice(api, invoice_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api.list_charges(ADMIN, {"invoice_id": invoice_id}))


# ---------------------------------------------------------------------------
# Tier 2 - the reference world
# ---------------------------------------------------------------------------
def reference_world(
    api,
    clock: str = COLD_START_CLOCK,
    customer_overrides: Optional[Dict[str, Any]] = None,
    facility_overrides: Optional[Dict[str, Any]] = None,
    tariff_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clock, one consignee, one industry track and one published tariff."""
    set_clock(api, clock)
    customer = make_customer(api, **(customer_overrides or {}))
    facility = make_industry_track(api, **(facility_overrides or {}))
    tariff = make_published_tariff(api, **(tariff_overrides or {}))
    return {
        "customer": customer,
        "customer_id": customer["id"],
        "customer_headers": make_customer_headers(customer["id"]),
        "facility": facility,
        "facility_id": facility["id"],
        "tariff": tariff,
        "tariff_id": tariff["id"],
    }


def make_cycle(
    api,
    world: Dict[str, Any],
    rail_car: Optional[Dict[str, Any]] = None,
    facility_id: Optional[str] = None,
    tariff_rule_set_id: Optional[str] = None,
    **overrides
) -> Dict[str, Any]:
    """Order a car.  The car's ``version`` is re-read immediately before the
    create so that a helper reused twice on the same car never presents the
    version its own previous call consumed (PRD 2.7)."""
    car = rail_car or make_rail_car(api, ownership=OWNERSHIP_RAILROAD_OWNED)
    fresh = get_car(api, car["id"])
    payload = f.placement_cycle_payload(
        world["customer_id"],
        fresh["id"],
        facility_id or world["facility_id"],
        tariff_rule_set_id or world["tariff_id"],
        fresh["version"],
        **overrides
    )
    cycle = get_success_data(api.create_placement_cycle(payload, AGENT), 201)
    return cycle


# ---------------------------------------------------------------------------
# Tier 3 - the movement chain (PRD 3.2 - 3.5)
# ---------------------------------------------------------------------------
def place_constructively(
    api, cycle_id: str, at: str = CYCLE_A_CONSTRUCTIVE_AT, reason_code: str = REASON_TRACK_FULL
) -> Dict[str, Any]:
    return get_success_data(
        api.constructive_placement(
            cycle_id,
            f.constructive_placement_payload(at, reason_code=reason_code),
            AGENT,
        )
    )


def send_notice(
    api, cycle_id: str, sent_at: str = CYCLE_A_NOTICE_SENT_AT, channel: str = CHANNEL_EDI
) -> Dict[str, Any]:
    return get_success_data(
        api.notify(cycle_id, f.notify_payload(sent_at, channel), AGENT)
    )


def acknowledge(api, cycle_id: str, ack_at: str, customer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.acknowledge_notification(
            cycle_id, f.acknowledge_payload(ack_at), make_customer_headers(customer_id)
        )
    )


def place_actually(api, cycle_id: str, at: str = CYCLE_A_ACTUAL_AT) -> Dict[str, Any]:
    return get_success_data(
        api.actual_placement(cycle_id, f.actual_placement_payload(at), AGENT)
    )


def release_cycle(api, cycle_id: str, at: str, customer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.release(cycle_id, f.release_payload(at), make_customer_headers(customer_id))
    )


def constructively_placed_cycle(
    api, world: Dict[str, Any], at: str = CYCLE_A_CONSTRUCTIVE_AT, **kwargs
) -> Dict[str, Any]:
    cycle = make_cycle(api, world, **kwargs)
    place_constructively(api, cycle["id"], at)
    return get_cycle(api, cycle["id"])


def noticed_cycle(
    api,
    world: Dict[str, Any],
    constructive_at: str = CYCLE_A_CONSTRUCTIVE_AT,
    sent_at: str = CYCLE_A_NOTICE_SENT_AT,
    channel: str = CHANNEL_EDI,
    **kwargs
) -> Dict[str, Any]:
    cycle = make_cycle(api, world, **kwargs)
    place_constructively(api, cycle["id"], constructive_at)
    send_notice(api, cycle["id"], sent_at, channel)
    return get_cycle(api, cycle["id"])


def actually_placed_cycle(
    api,
    world: Dict[str, Any],
    constructive_at: str = CYCLE_A_CONSTRUCTIVE_AT,
    sent_at: str = CYCLE_A_NOTICE_SENT_AT,
    actual_at: str = CYCLE_A_ACTUAL_AT,
    **kwargs
) -> Dict[str, Any]:
    cycle = make_cycle(api, world, **kwargs)
    place_constructively(api, cycle["id"], constructive_at)
    send_notice(api, cycle["id"], sent_at)
    place_actually(api, cycle["id"], actual_at)
    return get_cycle(api, cycle["id"])


def released_cycle(
    api,
    world: Dict[str, Any],
    constructive_at: str = CYCLE_A_CONSTRUCTIVE_AT,
    sent_at: str = CYCLE_A_NOTICE_SENT_AT,
    actual_at: str = CYCLE_A_ACTUAL_AT,
    released_at: str = CYCLE_A_RELEASE_AT,
    **kwargs
) -> Dict[str, Any]:
    """The full industry-track chain: order, hold, notice, spot, release."""
    cycle = actually_placed_cycle(
        api, world, constructive_at, sent_at, actual_at, **kwargs
    )
    release_cycle(api, cycle["id"], released_at, world["customer_id"])
    return get_cycle(api, cycle["id"])


def released_cycle_a(api, world: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """The 3-chargeable-day, 47550-cent reference cycle."""
    return released_cycle(api, world, **kwargs)


def released_cycle_b(api, world: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """The 1-chargeable-day, 12550-cent reference cycle."""
    return released_cycle(
        api,
        world,
        constructive_at=CYCLE_B_CONSTRUCTIVE_AT,
        sent_at=CYCLE_B_NOTICE_SENT_AT,
        actual_at=CYCLE_B_ACTUAL_AT,
        released_at=CYCLE_B_RELEASE_AT,
        **kwargs
    )


def embargo_facility(api, facility_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_facility_access_mode(
            facility_id, f.access_mode_payload(ACCESS_MODE_EMBARGOED), AGENT
        )
    )


def set_access_mode(api, facility_id: str, access_mode: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_facility_access_mode(
            facility_id, f.access_mode_payload(access_mode), AGENT
        )
    )


def put_on_credit_hold(api, customer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_credit_hold(customer_id, f.credit_hold_payload(True), ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 4 - the money chain (PRD 3.7)
# ---------------------------------------------------------------------------
def draft_invoice(api, world: Dict[str, Any], clock: str = CLOCK_AFTER_RELEASE, **overrides):
    """Open a DRAFT invoice, attaching every eligible final charge."""
    set_clock(api, clock)
    return get_success_data(
        api.create_invoice(f.invoice_payload(world["customer_id"], **overrides), ADMIN),
        201,
    )


def issued_invoice(
    api, world: Dict[str, Any], draft_clock: str = CLOCK_AFTER_RELEASE, issue_clock: str = CLOCK_AT_ISSUE, **overrides
):
    """Open and then issue an invoice.

    The clock is parked twice on purpose: the attachment window is a property of
    the billing period, but ``dispute_deadline_at`` is derived from the clock at
    the moment of issue (PRD 3.7), so the issue hop gets its own station.
    """
    invoice = draft_invoice(api, world, draft_clock, **overrides)
    set_clock(api, issue_clock)
    return get_success_data(api.issue_invoice(invoice["id"], ADMIN))


def open_agreement(api, customer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_average_agreement(
            f.average_agreement_payload(customer_id, **overrides), ADMIN
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Tier 5 - the dispute chain (PRD 3.8) and escalation (PRD 3.9)
# ---------------------------------------------------------------------------
def draft_dispute(
    api,
    invoice: Dict[str, Any],
    customer_id: str,
    claimed_credit_cents: int,
    **overrides
) -> Dict[str, Any]:
    """File a dispute.  The invoice ``version`` is re-read immediately before
    the create because ``POST /demurrage/disputes`` consumes it (PRD 2.7)."""
    fresh = get_invoice(api, invoice["id"])
    payload = f.dispute_payload(
        fresh["id"], fresh["version"], claimed_credit_cents, **overrides
    )
    return get_success_data(
        api.create_dispute(payload, make_customer_headers(customer_id)), 201
    )


def add_evidence(
    api,
    dispute_id: str,
    customer_id: str,
    observed_at: str = CYCLE_A_CONSTRUCTIVE_AT,
    evidence_type: str = EVIDENCE_SWITCH_LIST,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_evidence(
            dispute_id,
            f.evidence_payload(observed_at, evidence_type),
            make_customer_headers(customer_id),
        ),
        201,
    )


def evidenced_dispute(
    api,
    invoice: Dict[str, Any],
    customer_id: str,
    claimed_credit_cents: int,
    evidence_types: Optional[List[str]] = None,
    **overrides
) -> Dict[str, Any]:
    dispute = draft_dispute(api, invoice, customer_id, claimed_credit_cents, **overrides)
    for evidence_type in evidence_types or [EVIDENCE_SWITCH_LIST]:
        add_evidence(api, dispute["id"], customer_id, evidence_type=evidence_type)
    return get_dispute(api, dispute["id"])


def submitted_dispute(
    api,
    invoice: Dict[str, Any],
    customer_id: str,
    claimed_credit_cents: int,
    submit_clock: str = CLOCK_AT_SUBMIT,
    evidence_types: Optional[List[str]] = None,
    **overrides
) -> Dict[str, Any]:
    dispute = evidenced_dispute(
        api, invoice, customer_id, claimed_credit_cents, evidence_types, **overrides
    )
    set_clock(api, submit_clock)
    return get_success_data(
        api.submit_dispute(dispute["id"], make_customer_headers(customer_id))
    )


def under_review_dispute(
    api,
    invoice: Dict[str, Any],
    customer_id: str,
    claimed_credit_cents: int,
    adjudicator_id: str,
    submit_clock: str = CLOCK_AT_SUBMIT,
    evidence_types: Optional[List[str]] = None,
    **overrides
) -> Dict[str, Any]:
    dispute = submitted_dispute(
        api,
        invoice,
        customer_id,
        claimed_credit_cents,
        submit_clock,
        evidence_types,
        **overrides
    )
    return get_success_data(
        api.begin_review(dispute["id"], make_adjudicator_headers(adjudicator_id))
    )


def decided_dispute(
    api,
    invoice: Dict[str, Any],
    customer_id: str,
    claimed_credit_cents: int,
    adjudicator_id: str,
    decision: str = DECISION_ALLOWED,
    allowance_pct: Any = 1,
    submit_clock: str = CLOCK_AT_SUBMIT,
    evidence_types: Optional[List[str]] = None,
    **overrides
) -> Dict[str, Any]:
    dispute = under_review_dispute(
        api,
        invoice,
        customer_id,
        claimed_credit_cents,
        adjudicator_id,
        submit_clock,
        evidence_types,
        **overrides
    )
    return get_success_data(
        api.decide_dispute(
            dispute["id"],
            f.decide_payload(decision, allowance_pct),
            make_adjudicator_headers(adjudicator_id),
        )
    )


def appealed_dispute(
    api,
    dispute_id: str,
    customer_id: str,
    appeal_clock: str = CLOCK_AT_APPEAL,
) -> Dict[str, Any]:
    set_clock(api, appeal_clock)
    return get_success_data(
        api.appeal_dispute(
            dispute_id, f.appeal_payload(), make_customer_headers(customer_id)
        )
    )


def twice_decided_dispute(
    api,
    invoice: Dict[str, Any],
    customer_id: str,
    claimed_credit_cents: int,
    adjudicator_a: str,
    adjudicator_b: str,
    round1_decision: str = DECISION_ALLOWED,
    round1_allowance_pct: Any = 1,
    round2_decision: str = DECISION_ALLOWED,
    round2_allowance_pct: Any = 1,
    **overrides
) -> Dict[str, Any]:
    """A dispute DECIDED with ``round_number`` 2 - the only shape PRD 3.9
    accepts for a regulatory escalation."""
    dispute = decided_dispute(
        api,
        invoice,
        customer_id,
        claimed_credit_cents,
        adjudicator_a,
        round1_decision,
        round1_allowance_pct,
        **overrides
    )
    appealed_dispute(api, dispute["id"], customer_id)
    get_success_data(
        api.begin_review(dispute["id"], make_adjudicator_headers(adjudicator_b))
    )
    return get_success_data(
        api.decide_dispute(
            dispute["id"],
            f.decide_payload(round2_decision, round2_allowance_pct),
            make_adjudicator_headers(adjudicator_b),
        )
    )


def filed_complaint(
    api,
    dispute_id: str,
    customer_id: str,
    complaint_type: str = COMPLAINT_TYPE_BILLING_PRACTICE,
    filing_clock: str = CLOCK_AT_COMPLAINT,
    **overrides
) -> Dict[str, Any]:
    set_clock(api, filing_clock)
    return get_success_data(
        api.create_regulatory_complaint(
            f.complaint_payload(dispute_id, complaint_type, **overrides),
            make_customer_headers(customer_id),
        ),
        201,
    )


def answered_complaint(api, complaint_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.answer_regulatory_complaint(complaint_id, f.answer_payload(), AGENT)
    )


# ---------------------------------------------------------------------------
# Tier 5 - the bunching chain (PRD 3.6)
# ---------------------------------------------------------------------------
def file_bunching_claim(
    api,
    customer_id: str,
    window_start: str,
    window_end: str,
    **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_bunching_claim(
            f.bunching_claim_payload(customer_id, window_start, window_end, **overrides),
            make_customer_headers(customer_id),
        ),
        201,
    )


def analyze_claim(api, claim_id: str, adjudicator_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.analyze_bunching_claim(claim_id, make_adjudicator_headers(adjudicator_id))
    )


# Re-export the unchanged reference values so a test file needs one import.
__all__ = [name for name in dir() if not name.startswith("_")]


# ---------------------------------------------------------------------------
# Tier 6 - the two-line reference invoice
# ---------------------------------------------------------------------------
def released_pair(api, world: Dict[str, Any]):
    """Cycle A and Cycle B, both released, at two *separate* industry tracks.

    The two tracks carry identical defaults, but they must not be the same
    facility.  PRD 3.5 re-derives ``last_switch_at`` from the release as well as
    from the spot, so releasing Cycle A at 2026-08-10T16:00Z would leave the
    facility's ``last_switch_at`` after Cycle B's own actual placement instant of
    2026-08-07T12:00Z, and Cycle B would then fail the PRD 3.4 switch-buffer
    guard for a reason that has nothing to do with any rule under test.

    Returns ``(cycle_a, cycle_b)`` with grosses of 47550 and 12550 cents and
    ``released_at`` ascending in that order.
    """
    track_b = make_industry_track(api)
    cycle_a = released_cycle_a(api, world)
    cycle_b = released_cycle_b(api, world, facility_id=track_b["id"])
    return cycle_a, cycle_b


def two_line_invoice(
    api,
    world: Dict[str, Any],
    draft_clock: str = CLOCK_AFTER_RELEASE,
    issue_clock: str = CLOCK_AT_ISSUE,
):
    """The ISSUED two-line invoice of the PRD 2.6 worked example.

    ``total_gross_cents`` is 60100 and no credit has landed yet.  Returns
    ``(cycle_a, cycle_b, invoice)``.
    """
    cycle_a, cycle_b = released_pair(api, world)
    invoice = issued_invoice(api, world, draft_clock, issue_clock)
    return cycle_a, cycle_b, invoice


def agreements_of(api, customer_id: str, params: Optional[Dict[str, Any]] = None):
    """PRD 3.7 - agreements are reachable only through the per-consignee list."""
    return get_success_data(
        api.list_customer_average_agreements(customer_id, ADMIN, params)
    )


def get_agreement(api, customer_id: str, agreement_id: str) -> Dict[str, Any]:
    for row in agreements_of(api, customer_id):
        if row["id"] == agreement_id:
            return row
    raise AssertionError(
        "agreement %s is not in the consignee's agreement list" % agreement_id
    )


def claims_of(api, customer_id: str, params: Optional[Dict[str, Any]] = None):
    return get_success_data(
        api.list_customer_bunching_claims(customer_id, ADMIN, params)
    )


def get_claim(api, customer_id: str, claim_id: str) -> Dict[str, Any]:
    for row in claims_of(api, customer_id):
        if row["id"] == claim_id:
            return row
    raise AssertionError("claim %s is not in the consignee's claim list" % claim_id)


# ---------------------------------------------------------------------------
# Tier 7 - the remaining single-hop actions, and the facility read-back probe
# ---------------------------------------------------------------------------
def refuse_cycle(api, cycle_id: str, customer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.refuse(
            cycle_id, f.refuse_payload(**overrides), make_customer_headers(customer_id)
        )
    )


def void_cycle(api, cycle_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api.void_cycle(cycle_id, f.void_payload(**overrides), ADMIN))


def close_invoice(api, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_invoice(invoice_id, ADMIN))


def reconcile(api, agreement_id: str) -> Dict[str, Any]:
    return get_success_data(api.reconcile_average_agreement(agreement_id, ADMIN))


def get_charge(api, charge_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_charge(charge_id, ADMIN))


def request_more_info(
    api,
    dispute_id: str,
    adjudicator_id: str,
    clock: Optional[str] = None,
    **overrides
) -> Dict[str, Any]:
    if clock is not None:
        set_clock(api, clock)
    return get_success_data(
        api.request_info(
            dispute_id,
            f.request_info_payload(**overrides),
            make_adjudicator_headers(adjudicator_id),
        )
    )


def resubmit(
    api, dispute_id: str, customer_id: str, clock: Optional[str] = None
) -> Dict[str, Any]:
    if clock is not None:
        set_clock(api, clock)
    return get_success_data(
        api.resubmit_dispute(dispute_id, make_customer_headers(customer_id))
    )


def begin_review(api, dispute_id: str, adjudicator_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.begin_review(dispute_id, make_adjudicator_headers(adjudicator_id))
    )


def decide(
    api, dispute_id: str, adjudicator_id: str, decision: str, allowance_pct: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_dispute(
            dispute_id,
            f.decide_payload(decision, allowance_pct),
            make_adjudicator_headers(adjudicator_id),
        )
    )


def probe_facility(api, facility_id: str) -> Dict[str, Any]:
    """Read a facility back through the only endpoint that returns one.

    PRD 4 declares no ``GET /demurrage/facilities/{id}``, but it does declare
    that "every mutation returns the resource it changed", and PRD 3.1 puts
    ``occupied_spot_count`` and ``last_switch_at`` on the facility.  Re-asserting
    the posture the facility already holds is therefore the only way to observe
    those two derived fields, and PRD 3.1 attaches no state precondition to the
    access-mode capability.
    """
    from .constants import ACCESS_MODE_OPEN

    return set_access_mode(api, facility_id, ACCESS_MODE_OPEN)


def get_tariff(api, tariff_rule_set_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_tariff_rule_set(tariff_rule_set_id, ADMIN))
