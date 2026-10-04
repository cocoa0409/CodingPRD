"""Composite setup helpers.

Every fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before each test), using only endpoints the
PRD declares. The logical clock is always pinned to the PRD's default
(2026-09-01T00:00:00Z) first so server-stamped timestamps are deterministic
and planning-period windows (2029-06-01 .. 2030-05-31) stay in the future.

Numeric base scenario used throughout (per the PRD §3.1 four-step roll-up):
  peak 10.0 MW, reserve margin 0.25, pool-wide EFORd 0.04
  -> installed basis 12.5 -> unforced reliability requirement 12.000 MW
  -> single RTO zone with share 1.0 gets zonal requirement 12.000 MW.
Resources accredited CLASS_AVG 0.85 on nameplate 100.0 -> 85.000 UCAP.

All setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors naming the step.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_ISO, DY_END, DY_LABEL, DY_START, TEST_DEFAULTS,
)
from .factories import (
    create_accreditation_payload,
    create_auction_run_payload,
    create_delivery_year_payload,
    create_emergency_event_payload,
    create_forecast_payload,
    create_measurement_report_payload,
    create_offer_payload,
    create_owner_payload,
    create_replacement_payload,
    create_resource_payload,
    create_zone_payload,
)
from .test_users import TEST_USERS, make_resource_owner_headers

ADMIN = TEST_USERS["market_admin_headers"]
OPS = TEST_USERS["settlement_ops_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    """Pin the logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_delivery_year(label=DY_LABEL, start=DY_START, end=DY_END, **overrides):
    payload = create_delivery_year_payload(
        delivery_year_label=label,
        planning_period_start=start,
        planning_period_end=end,
        **overrides,
    )
    return get_success_data(api_client.create_delivery_year(payload, ADMIN))


def create_zone(dy_id, zone_code="RTO", import_limit_mw=None, parent_zone_id=None):
    payload = create_zone_payload(zone_code=zone_code)
    if import_limit_mw is not None:
        payload["import_limit_mw"] = import_limit_mw
    if parent_zone_id is not None:
        payload["parent_zone_id"] = parent_zone_id
    return get_success_data(api_client.create_zone(dy_id, payload, ADMIN))


def create_forecast(dy_id, **overrides):
    return get_success_data(
        api_client.create_forecast(dy_id, create_forecast_payload(**overrides), ADMIN)
    )


def lock_forecast(dy_id):
    return get_success_data(api_client.lock_forecast(dy_id, ADMIN))


def create_owner(legal_name="Alpha GenCo", contact_email="alpha@x.com",
                 credit_score=TEST_DEFAULTS["CREDIT_SCORE"]):
    payload = create_owner_payload(
        legal_name=legal_name, contact_email=contact_email, credit_score=credit_score,
    )
    return get_success_data(api_client.create_owner(payload, ADMIN))


def create_resource(owner_id, zone_id, resource_type="GEN",
                    nameplate_mw=TEST_DEFAULTS["NAMEPLATE_MW"]):
    headers = make_resource_owner_headers(owner_id)
    payload = create_resource_payload(
        owner_id, zone_id, resource_type=resource_type, nameplate_mw=nameplate_mw,
    )
    return get_success_data(api_client.create_resource(payload, headers))


def create_accreditation(resource_id, owner_id, dy_id,
                         method="CLASS_AVG",
                         class_avg_factor=TEST_DEFAULTS["CLASS_AVG_FACTOR"],
                         unit_elcc_factor=None,
                         forced_outage_rate=TEST_DEFAULTS["FORCED_OUTAGE_RATE"],
                         scarcity_hours_sampled=TEST_DEFAULTS["SCARCITY_HOURS_SAMPLED"]):
    headers = make_resource_owner_headers(owner_id)
    overrides = {}
    if method == "UNIT_SPECIFIC":
        overrides = {"unit_elcc_factor": unit_elcc_factor}
        payload = {
            "resource_id": resource_id,
            "delivery_year_id": dy_id,
            "method": "UNIT_SPECIFIC",
            "unit_elcc_factor": unit_elcc_factor,
            "forced_outage_rate": forced_outage_rate,
            "scarcity_hours_sampled": scarcity_hours_sampled,
        }
    else:
        payload = create_accreditation_payload(
            resource_id, dy_id,
            method=method,
            class_avg_factor=class_avg_factor,
            forced_outage_rate=forced_outage_rate,
            scarcity_hours_sampled=scarcity_hours_sampled,
        )
    return get_success_data(api_client.create_accreditation(payload, headers))


def approve_accreditation(acc_id):
    return get_success_data(api_client.approve_accreditation(acc_id, ADMIN))


def create_and_approve_resource(owner_id, zone_id, dy_id,
                                resource_type="GEN",
                                nameplate_mw=TEST_DEFAULTS["NAMEPLATE_MW"],
                                class_avg_factor=TEST_DEFAULTS["CLASS_AVG_FACTOR"],
                                method="CLASS_AVG", unit_elcc_factor=None,
                                forced_outage_rate=TEST_DEFAULTS["FORCED_OUTAGE_RATE"],
                                scarcity_hours_sampled=TEST_DEFAULTS["SCARCITY_HOURS_SAMPLED"]):
    """Register a resource and walk its accreditation to EFFECTIVE.

    Returns (resource, accreditation).
    """
    resource = create_resource(owner_id, zone_id, resource_type=resource_type,
                               nameplate_mw=nameplate_mw)
    acc = create_accreditation(
        resource["id"], owner_id, dy_id, method=method,
        class_avg_factor=class_avg_factor, unit_elcc_factor=unit_elcc_factor,
        forced_outage_rate=forced_outage_rate,
        scarcity_hours_sampled=scarcity_hours_sampled,
    )
    acc = approve_accreditation(acc["id"])
    resource = get_success_data(api_client.get_resource(resource["id"], ADMIN))
    return resource, acc


# ---------------------------------------------------------------------------
# Tier 2: delivery-year hierarchy shortcuts
# ---------------------------------------------------------------------------

def setup_delivery_year_with_zone(label=DY_LABEL, start=DY_START, end=DY_END,
                                  zone_code="RTO"):
    """Clock pinned + delivery year in DRAFT + one top-level zone.

    Returns (delivery_year, zone).
    """
    set_clock()
    dy = create_delivery_year(label=label, start=start, end=end)
    zone = create_zone(dy["id"], zone_code=zone_code)
    return dy, zone


def setup_delivery_year_with_forecast(label=DY_LABEL, zone_code="RTO", **forecast_overrides):
    """Delivery year in DRAFT + one zone + one DRAFT forecast revision.

    Returns (delivery_year, zone, forecast).
    """
    dy, zone = setup_delivery_year_with_zone(label=label, zone_code=zone_code)
    forecast = create_forecast(dy["id"], **forecast_overrides)
    return dy, zone, forecast


def setup_forecast_locked_year(label=DY_LABEL, **forecast_overrides):
    """Delivery year advanced to FORECAST_LOCKED with one RTO zone.

    Returns (delivery_year, zone, forecast).
    """
    dy, zone, forecast = setup_delivery_year_with_forecast(
        label=label, **forecast_overrides
    )
    dy = lock_forecast(dy["id"])
    return dy, zone, forecast


# ---------------------------------------------------------------------------
# Tier 3: auction lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_and_open_run(dy_id, run_label="BRA"):
    """Create an auction run and open it (delivery year must be FORECAST_LOCKED).

    Returns the OPEN run.
    """
    run = get_success_data(
        api_client.create_auction_run(create_auction_run_payload(dy_id, run_label=run_label), ADMIN)
    )
    run = get_success_data(api_client.open_auction_run(run["id"], ADMIN))
    return run


def submit_offer(resource_id, owner_id, run_id, offer_mw=10.0,
                 offer_price_per_mw_day=70.0):
    headers = make_resource_owner_headers(owner_id)
    payload = create_offer_payload(
        resource_id, run_id,
        offer_mw=offer_mw, offer_price_per_mw_day=offer_price_per_mw_day,
    )
    return get_success_data(api_client.create_offer(payload, headers))


def seal_run(run_id):
    return get_success_data(api_client.seal_auction_run(run_id, ADMIN))


def get_review_for_offer(offer_id):
    data = get_success_data(api_client.get_offer_mitigation_review(offer_id, ADMIN))
    assert isinstance(data, list) and len(data) == 1, \
        f"Expected exactly one mitigation review for offer {offer_id}"
    return data[0]


def resolve_review_pass(offer_id, note="competitive offer"):
    """Resolve the offer's mitigation review to PASS.

    The PRD never specifies the three-pivotal-supplier screen's inputs, so an
    offer priced at or under its seller cap may legitimately be auto-resolved
    to EXEMPT at seal time (no PENDING review to resolve). EXEMPT and PASS
    have identical clearing semantics — both keep effective_price_per_mw_day
    equal to the submitted offer price and both satisfy the clear gate — so an
    already-EXEMPT review is returned as-is.
    """
    review = get_review_for_offer(offer_id)
    if review["outcome"] != "PENDING":
        return review
    return get_success_data(
        api_client.resolve_mitigation_review(review["id"], {"outcome": "PASS", "reviewer_note": note}, ADMIN)
    )


def seal_and_pass_all(run_id, offer_ids):
    """Seal the run, then resolve every auto-created PENDING review to PASS."""
    run = seal_run(run_id)
    for offer_id in offer_ids:
        resolve_review_pass(offer_id)
    return run


# ---------------------------------------------------------------------------
# Tier 4: full clearing scenarios
# ---------------------------------------------------------------------------

def setup_cleared_year_single_resource(offer_mw=10.0, offer_price=70.0,
                                       nameplate_mw=TEST_DEFAULTS["NAMEPLATE_MW"],
                                       credit_score=TEST_DEFAULTS["CREDIT_SCORE"],
                                       class_avg_factor=TEST_DEFAULTS["CLASS_AVG_FACTOR"]):
    """Full happy path: one owner, one accredited GEN resource, one offer,
    run cleared. Single RTO zone, requirement 12.000 MW.

    Returns dict with keys: dy, zone, forecast, owner, resource, accreditation,
    run, offer, commitment.
    """
    dy, zone, forecast = setup_forecast_locked_year()
    owner = create_owner(credit_score=credit_score)
    resource, acc = create_and_approve_resource(
        owner["id"], zone["id"], dy["id"],
        nameplate_mw=nameplate_mw, class_avg_factor=class_avg_factor,
    )
    run = create_and_open_run(dy["id"])
    offer = submit_offer(resource["id"], owner["id"], run["id"],
                         offer_mw=offer_mw, offer_price_per_mw_day=offer_price)
    seal_and_pass_all(run["id"], [offer["id"]])
    run = get_success_data(api_client.clear_auction_run(run["id"], ADMIN))
    commitments = get_success_data(
        api_client.list_commitments(ADMIN, params={"resource_id": resource["id"]})
    )
    assert len(commitments) == 1, "Expected exactly one commitment after clearing"
    return {
        "dy": dy, "zone": zone, "forecast": forecast, "owner": owner,
        "resource": resource, "accreditation": acc, "run": run,
        "offer": offer, "commitment": commitments[0],
    }


def setup_cleared_year_two_resources(offer_mw=10.0, offer_price=70.0,
                                     second_offer_mw=None, second_offer_price=None,
                                     second_nameplate_mw=TEST_DEFAULTS["NAMEPLATE_MW"],
                                     second_class_avg_factor=TEST_DEFAULTS["CLASS_AVG_FACTOR"]):
    """One owner, two accredited GEN resources, one offer each, run cleared.

    Returns dict with keys: dy, zone, owner, r1, r2, run, off1, off2, c1, c2.
    """
    dy, zone, forecast = setup_forecast_locked_year()
    owner = create_owner()
    r1, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
    r2, _ = create_and_approve_resource(
        owner["id"], zone["id"], dy["id"],
        nameplate_mw=second_nameplate_mw, class_avg_factor=second_class_avg_factor,
    )
    run = create_and_open_run(dy["id"])
    off1 = submit_offer(r1["id"], owner["id"], run["id"],
                        offer_mw=offer_mw, offer_price_per_mw_day=offer_price)
    off2 = submit_offer(
        r2["id"], owner["id"], run["id"],
        offer_mw=second_offer_mw if second_offer_mw is not None else offer_mw,
        offer_price_per_mw_day=second_offer_price if second_offer_price is not None else offer_price,
    )
    seal_and_pass_all(run["id"], [off1["id"], off2["id"]])
    run = get_success_data(api_client.clear_auction_run(run["id"], ADMIN))
    c1 = get_success_data(api_client.list_commitments(ADMIN, params={"resource_id": r1["id"]}))[0]
    c2 = get_success_data(api_client.list_commitments(ADMIN, params={"resource_id": r2["id"]}))[0]
    return {
        "dy": dy, "zone": zone, "owner": owner, "r1": r1, "r2": r2,
        "run": run, "off1": off1, "off2": off2, "c1": c1, "c2": c2,
    }


def setup_cleared_year_with_replacement_resource():
    """Cleared year (C1: 10 MW @ 70.00) plus a second accredited resource R2
    (nameplate 25.0, class-avg 0.8 -> 20.000 UCAP) with no offer, usable as
    replacement capacity.

    Returns dict with keys: dy, zone, owner, r1, r2, run, off1, c1.
    """
    dy, zone, forecast = setup_forecast_locked_year()
    owner = create_owner()
    r1, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
    r2, _ = create_and_approve_resource(
        owner["id"], zone["id"], dy["id"], nameplate_mw=25.0, class_avg_factor=0.8,
    )
    run = create_and_open_run(dy["id"])
    off1 = submit_offer(r1["id"], owner["id"], run["id"],
                        offer_mw=10.0, offer_price_per_mw_day=70.0)
    seal_and_pass_all(run["id"], [off1["id"]])
    run = get_success_data(api_client.clear_auction_run(run["id"], ADMIN))
    c1 = get_success_data(api_client.list_commitments(ADMIN, params={"resource_id": r1["id"]}))[0]
    return {
        "dy": dy, "zone": zone, "owner": owner, "r1": r1, "r2": r2,
        "run": run, "off1": off1, "c1": c1,
    }


# ---------------------------------------------------------------------------
# Tier 5: emergency assessment scenarios
# ---------------------------------------------------------------------------

def declare_event(dy_id, start="2029-06-10T13:00:00Z", end="2029-06-10T15:00:00Z",
                  event_type="EMERGENCY_ACTION"):
    payload = create_emergency_event_payload(
        dy_id, event_start=start, event_end=end, event_type=event_type,
    )
    return get_success_data(api_client.create_emergency_event(payload, ADMIN))


def begin_assessment(ev_id):
    return get_success_data(api_client.begin_assessment(ev_id, ADMIN))


def list_event_assessments(ev_id):
    return get_success_data(api_client.list_event_assessments(ev_id, ADMIN))


def record_actual(assessment_id, expected_mw, actual_mw):
    return get_success_data(api_client.record_actual(assessment_id, expected_mw, actual_mw, ADMIN))


def finalize_assessments(ev_id):
    return get_success_data(api_client.finalize_assessments(ev_id, ADMIN))


def setup_event_assessing(commitment_count=1, offer_price=70.0,
                          event_start="2029-06-10T13:00:00Z",
                          event_end="2029-06-10T15:00:00Z"):
    """Cleared year + one declared event moved to ASSESSING; returns the DRAFT
    assessments created for the in-scope commitments.

    Returns (context_dict, event, assessments).
    """
    if commitment_count == 1:
        ctx = setup_cleared_year_single_resource(offer_price=offer_price)
    else:
        ctx = setup_cleared_year_two_resources(offer_price=offer_price)
    ev = declare_event(ctx["dy"]["id"], start=event_start, end=event_end)
    ev = begin_assessment(ev["id"])
    assessments = list_event_assessments(ev["id"])
    return ctx, ev, assessments


def get_commitment(commitment_id):
    return get_success_data(api_client.get_commitment(commitment_id, ADMIN))


def get_offer(offer_id):
    return get_success_data(api_client.get_offer(offer_id, ADMIN))


def get_run(run_id):
    return get_success_data(api_client.get_auction_run(run_id, ADMIN))


def get_zone(zone_id):
    return get_success_data(api_client.get_zone(zone_id, ADMIN))


def get_delivery_year(dy_id):
    return get_success_data(api_client.get_delivery_year(dy_id, ADMIN))


def get_event(ev_id):
    return get_success_data(api_client.get_emergency_event(ev_id, ADMIN))


def get_assessment(a_id):
    return get_success_data(api_client.get_assessment(a_id, ADMIN))


def list_settlement_entries(**params):
    return get_success_data(api_client.list_settlement_entries(ADMIN, params=params))


def list_event_entries(ev_id):
    return list_settlement_entries(emergency_event_id=ev_id)


# ---------------------------------------------------------------------------
# Measurement & verification helpers
# ---------------------------------------------------------------------------

def setup_dr_resource_measured(metered_mwh=1464.0, baseline_mwh=2000.0,
                               start="2029-06-01T00:00:00Z",
                               end="2029-08-01T00:00:00Z"):
    """Delivery year (FORECAST_LOCKED) + owner + accredited DR resource
    (nameplate 20.0, class-avg 0.8 -> 16.000 UCAP) + one SUBMITTED
    measurement report.

    Returns dict with keys: dy, zone, owner, resource, accreditation, report.
    """
    dy, zone, forecast = setup_forecast_locked_year()
    owner = create_owner(legal_name="Alpha DR LLC")
    resource, acc = create_and_approve_resource(
        owner["id"], zone["id"], dy["id"],
        resource_type="DR", nameplate_mw=20.0, class_avg_factor=0.8,
        forced_outage_rate=0.05,
    )
    headers = make_resource_owner_headers(owner["id"])
    payload = create_measurement_report_payload(
        resource["id"], dy["id"],
        reporting_period_start=start, reporting_period_end=end,
        metered_mwh=metered_mwh, baseline_mwh=baseline_mwh,
    )
    report = get_success_data(api_client.create_measurement_report(payload, headers))
    return {
        "dy": dy, "zone": zone, "owner": owner,
        "resource": resource, "accreditation": acc, "report": report,
    }


def submit_measurement_report(resource_id, owner_id, dy_id, **overrides):
    headers = make_resource_owner_headers(owner_id)
    payload = create_measurement_report_payload(resource_id, dy_id, **overrides)
    return get_success_data(api_client.create_measurement_report(payload, headers))


def start_review(mr_id):
    return get_success_data(api_client.start_measurement_review(mr_id, ADMIN))


def verify_report(mr_id):
    return get_success_data(api_client.verify_measurement_report(mr_id, ADMIN))


def reject_report(mr_id):
    return get_success_data(api_client.reject_measurement_report(mr_id, ADMIN))


def get_report(mr_id):
    return get_success_data(api_client.get_measurement_report(mr_id, ADMIN))


# ---------------------------------------------------------------------------
# Replacement helpers
# ---------------------------------------------------------------------------

def submit_replacement(commitment_id, owner_id, replacement_resource_id,
                       replacement_mw, expected_commitment_version,
                       price_per_mw_day=55.0):
    headers = make_resource_owner_headers(owner_id)
    payload = create_replacement_payload(
        commitment_id, replacement_resource_id, expected_commitment_version,
        replacement_mw=replacement_mw, price_per_mw_day=price_per_mw_day,
    )
    return get_success_data(api_client.create_replacement_transaction(payload, headers))
