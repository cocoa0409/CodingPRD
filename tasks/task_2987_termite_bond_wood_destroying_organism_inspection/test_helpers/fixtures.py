"""Composite setup helpers.

The harness restarts the server and empties the database before every test, so
each helper builds its preconditions from scratch.  Helpers use the lenient
``get_success_data`` internally: a setup failure raises a clear error rather
than masquerading as an assertion failure in the test body.

Helpers are single-purpose and composable.  Nothing here performs a transition
that would invalidate a row it has just handed back.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    ACTIVITY_HEAVY,
    ACTIVITY_MODERATE,
    CONDUCIVE_EXCESS_MOISTURE,
    CONDUCIVE_WOOD_TO_GROUND,
    METHOD_BAIT_STATION,
    METHOD_LIQUID_BARRIER,
    PURPOSE_REAL_ESTATE,
    PURPOSE_REINSTATEMENT,
    PURPOSE_RENEWAL,
    STATE_FORM_MAP,
    TIER_REPAIR_AND_RETREAT,
    date_plus_days,
    instant_plus_days,
)
from .factories import (
    amendment_payload,
    application_payload,
    attested_graph_complete_payload,
    bait_plan_payload,
    bond_payload,
    clock_payload,
    conducive_finding_payload,
    damage_claim_payload,
    damage_finding_payload,
    graph_complete_payload,
    infestation_finding_payload,
    inspection_payload,
    inspector_payload,
    property_payload,
    reinstatement_payload,
    renewal_completion_payload,
    renewal_payload,
    station_service_payload,
    treatment_plan_payload,
    verification_payload,
    wdo_report_payload,
)
from .test_users import (
    ADJUDICATOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_applicator_headers,
    make_field_inspector_headers,
    make_property_owner_headers,
)

# Non-overlapping diary slots per inspector, so a helper never trips the
# inspector-schedule-overlap rule when it opens a second graph.
_SLOTS = {}
_SLOT_BASE_DATE = "2026-06-01"


def next_diary_slot(inspector_id):
    """Return a fresh, non-overlapping (start, end) window for one inspector."""
    index = _SLOTS.get(inspector_id, 0)
    _SLOTS[inspector_id] = index + 1
    day = date_plus_days(_SLOT_BASE_DATE, index)
    return ("%sT09:00:00Z" % day, "%sT12:00:00Z" % day)


# ---------------------------------------------------------------------------
# Tier 1: the logical clock
# ---------------------------------------------------------------------------


def set_clock(api, instant):
    """Move the logical clock to the supplied UTC instant."""
    return get_success_data(api.set_clock(clock_payload(instant), OFFICER_HEADERS))


def read_clock(api):
    """Read the logical clock's present instant; needs no headers."""
    return get_success_data(api.get_clock())["current_utc"]


# ---------------------------------------------------------------------------
# Tier 2: registry rows
# ---------------------------------------------------------------------------


def register_property(api, **overrides):
    """Register one structure and return it."""
    return get_success_data(
        api.create_property(property_payload(**overrides), OFFICER_HEADERS)
    )


def register_inspector(api, **overrides):
    """Register one licensee and return it."""
    return get_success_data(
        api.create_inspector(inspector_payload(**overrides), OFFICER_HEADERS)
    )


def set_license_status(api, inspector_id, status, **overrides):
    """Drive a licence to the requested status."""
    payload = {"status": status}
    payload.update(overrides)
    return get_success_data(
        api.set_license_status(inspector_id, payload, OFFICER_HEADERS)
    )


def register_property_and_inspector(api, state_code="FL", **property_overrides):
    """Register one structure and one licensee whose licence_state matches it."""
    prop = register_property(api, state_code=state_code, **property_overrides)
    inspector = register_inspector(api, license_state=state_code)
    return prop, inspector


# ---------------------------------------------------------------------------
# Tier 3: graphs
# ---------------------------------------------------------------------------


def open_graph(api, property_id, inspector_id, **overrides):
    """Open a DRAFT graph, taking the inspector's next free diary slot."""
    if "scheduled_start_at" not in overrides and "scheduled_end_at" not in overrides:
        start, end = next_diary_slot(inspector_id)
        overrides["scheduled_start_at"] = start
        overrides["scheduled_end_at"] = end
    payload = inspection_payload(property_id, inspector_id, **overrides)
    return get_success_data(
        api.create_inspection(payload, make_field_inspector_headers(inspector_id))
    )


def add_finding(api, inspection_id, inspector_id, payload):
    """Add one immutable notation to a DRAFT graph."""
    return get_success_data(
        api.create_finding(
            inspection_id, payload, make_field_inspector_headers(inspector_id)
        )
    )


def sign_graph(api, inspection_id, inspector_id, **overrides):
    """Sign a DRAFT graph, freezing its rollups."""
    return get_success_data(
        api.graph_complete(
            inspection_id,
            graph_complete_payload(**overrides),
            make_field_inspector_headers(inspector_id),
        )
    )


def sign_empty_graph(api, inspection_id, inspector_id, **overrides):
    """Sign a graph carrying no notations, with the required attestation."""
    return get_success_data(
        api.graph_complete(
            inspection_id,
            attested_graph_complete_payload(**overrides),
            make_field_inspector_headers(inspector_id),
        )
    )


def graphed_inspection(api, property_id, inspector_id, findings=(), **overrides):
    """Open a graph, add the supplied notations and sign it."""
    graph = open_graph(api, property_id, inspector_id, **overrides)
    for payload in findings:
        add_finding(api, graph["id"], inspector_id, payload)
    if findings:
        return sign_graph(api, graph["id"], inspector_id)
    return sign_empty_graph(api, graph["id"], inspector_id)


def clean_initial_graph(api, property_id, inspector_id, **overrides):
    """A signed INITIAL graph with no findings at all."""
    return graphed_inspection(api, property_id, inspector_id, **overrides)


def conducive_initial_graph(
    api,
    property_id,
    inspector_id,
    codes=(CONDUCIVE_WOOD_TO_GROUND, CONDUCIVE_EXCESS_MOISTURE),
    **overrides
):
    """A signed INITIAL graph carrying one conducive notation per supplied code."""
    findings = [
        conducive_finding_payload("A%d" % (index + 1), code)
        for index, code in enumerate(codes)
    ]
    return graphed_inspection(api, property_id, inspector_id, findings, **overrides)


def infested_initial_graph(api, property_id, inspector_id, **overrides):
    """A signed INITIAL graph whose active_infestation_found is true."""
    findings = [infestation_finding_payload("B2")]
    return graphed_inspection(api, property_id, inspector_id, findings, **overrides)


def damage_graph(api, property_id, inspector_id, damages, **overrides):
    """A signed graph carrying the supplied DAMAGE notations.

    ``damages`` is a sequence of ``(grid_ref, estimate, pre_existing, severity)``
    tuples; ``severity`` may be ``None`` to accept the default weight of 1.
    """
    findings = []
    for grid_ref, estimate, pre_existing, severity in damages:
        findings.append(
            damage_finding_payload(
                grid_ref, estimate, pre_existing=pre_existing, severity=severity
            )
        )
    return graphed_inspection(api, property_id, inspector_id, findings, **overrides)


# ---------------------------------------------------------------------------
# Tier 4: treatment plans and their lifecycle
# ---------------------------------------------------------------------------


def propose_plan(api, property_id, inspection_id, applicator_id, **overrides):
    """Propose a plan, freezing its sizing and quote."""
    payload = treatment_plan_payload(
        property_id, inspection_id, applicator_id, **overrides
    )
    return get_success_data(api.create_treatment_plan(payload, MANAGER_HEADERS))


def propose_bait_plan(api, property_id, inspection_id, applicator_id, **overrides):
    """Propose a BAIT_STATION plan."""
    payload = bait_plan_payload(
        property_id, inspection_id, applicator_id, **overrides
    )
    return get_success_data(api.create_treatment_plan(payload, MANAGER_HEADERS))


def approve_plan(api, plan_id):
    """Advance a PROPOSED plan to APPROVED."""
    return get_success_data(api.approve_treatment_plan(plan_id, {}, MANAGER_HEADERS))


def record_application(api, plan_id, applicator_id, expected_version, **overrides):
    """Record one immutable pesticide application against an APPROVED plan."""
    payload = application_payload(expected_version, **overrides)
    return get_success_data(
        api.create_application(plan_id, payload, make_applicator_headers(applicator_id))
    )


def complete_plan(api, plan_id, applicator_id):
    """Close out an APPROVED plan."""
    return get_success_data(
        api.complete_treatment_plan(
            plan_id, {}, make_applicator_headers(applicator_id)
        )
    )


def approved_plan(api, property_id, inspection_id, applicator_id, **overrides):
    """Propose and approve one plan, returning the APPROVED row."""
    plan = propose_plan(api, property_id, inspection_id, applicator_id, **overrides)
    return approve_plan(api, plan["id"])


def completed_liquid_plan(
    api, property_id, inspection_id, applicator_id, gallons_per_visit=None, **overrides
):
    """Propose, approve, discharge enough gallons and complete a liquid plan.

    Each application carries the plan version as the previous hop left it, so
    the version guard of PRD 2.7 is satisfied on every visit.
    """
    overrides.setdefault("method", METHOD_LIQUID_BARRIER)
    plan = approved_plan(api, property_id, inspection_id, applicator_id, **overrides)
    target = plan["target_gallons"]
    version = plan["version"]
    remaining = target
    per_visit = gallons_per_visit or target
    while remaining > 0:
        gallons = min(per_visit, remaining)
        record_application(
            api, plan["id"], applicator_id, version, gallons_applied=round(gallons, 2)
        )
        version += 1
        remaining -= gallons
    return complete_plan(api, plan["id"], applicator_id)


def completed_bait_plan(api, property_id, inspection_id, applicator_id, **overrides):
    """Propose, approve, load one cartridge and complete a bait plan.

    A BAIT_STATION plan carries a target_gallons of 0.00, so the single
    application discharges the declared minimum of 0.10 gallons; the completion
    gate for a bait plan is the existence of at least one application record.
    """
    plan = propose_bait_plan(
        api, property_id, inspection_id, applicator_id, **overrides
    )
    plan = approve_plan(api, plan["id"])
    record_application(
        api,
        plan["id"],
        applicator_id,
        plan["version"],
        gallons_applied=0.10,
        product_epa_number="70103-12",
    )
    return complete_plan(api, plan["id"], applicator_id)


def list_stations(api, plan_id, **params):
    """List the stations installed beneath one plan, station_index ascending."""
    response = api.list_bait_stations(plan_id, OFFICER_HEADERS, **params)
    return get_success_data(response)


def service_station(api, station_id, inspector_id, activity_level, **overrides):
    """Record one immutable station visit."""
    payload = station_service_payload(activity_level, **overrides)
    return get_success_data(
        api.create_station_service(
            station_id, payload, make_field_inspector_headers(inspector_id)
        )
    )


def escalate_station(api, station_id, inspector_id, first_visit_instant, step_days=30):
    """Drive one station to ESCALATED with three consecutive activity visits.

    The clock advances between visits so that each ``serviced_at`` is strictly
    after the previous one, as PRD 3.9 requires.
    """
    moment = first_visit_instant
    visits = []
    for index in range(3):
        set_clock(api, moment)
        activity = ACTIVITY_MODERATE if index < 2 else ACTIVITY_HEAVY
        visits.append(service_station(api, station_id, inspector_id, activity))
        moment = instant_plus_days(moment, step_days)
    return visits


# ---------------------------------------------------------------------------
# Tier 5: bonds, renewals, reinstatement
# ---------------------------------------------------------------------------


def issue_bond(api, property_id, treatment_plan_id, **overrides):
    """Issue a bond against a COMPLETED plan."""
    payload = bond_payload(property_id, treatment_plan_id, **overrides)
    return get_success_data(api.create_bond(payload, MANAGER_HEADERS))


def bonded_property(
    api,
    state_code="FL",
    coverage_tier=TIER_REPAIR_AND_RETREAT,
    findings=(),
    issue_instant=None,
    conducive_waiver_codes=None,
    property_overrides=None,
    plan_overrides=None,
):
    """Build the whole chain from a bare structure to an ACTIVE bond.

    Returns a dict carrying the structure, the licensee, the signed INITIAL
    graph, the COMPLETED plan and the ACTIVE bond, each as the API last
    returned it.
    """
    prop, inspector = register_property_and_inspector(
        api, state_code=state_code, **(property_overrides or {})
    )
    graph = graphed_inspection(api, prop["id"], inspector["id"], findings)
    plan_overrides = dict(plan_overrides or {})
    method = plan_overrides.pop("method", METHOD_LIQUID_BARRIER)
    if method == METHOD_BAIT_STATION:
        plan = completed_bait_plan(
            api, prop["id"], graph["id"], inspector["id"], **plan_overrides
        )
    else:
        plan = completed_liquid_plan(
            api,
            prop["id"],
            graph["id"],
            inspector["id"],
            method=method,
            **plan_overrides
        )
    if issue_instant:
        set_clock(api, issue_instant)
    bond_overrides = {"coverage_tier": coverage_tier}
    if conducive_waiver_codes is not None:
        bond_overrides["conducive_waiver_codes"] = conducive_waiver_codes
    bond = issue_bond(api, prop["id"], plan["id"], **bond_overrides)
    return {
        "property": prop,
        "inspector": inspector,
        "inspection": graph,
        "plan": plan,
        "bond": bond,
    }


def open_renewal(api, bond_id, **overrides):
    """Open a PENDING renewal invoice on an ACTIVE bond."""
    return get_success_data(
        api.create_renewal(bond_id, renewal_payload(**overrides), MANAGER_HEADERS)
    )


def complete_renewal(api, renewal_id, inspection_id, amount_usd, **overrides):
    """Attach the renewal graph, pay the repriced invoice and roll the term."""
    payload = renewal_completion_payload(inspection_id, amount_usd, **overrides)
    return get_success_data(api.complete_renewal(renewal_id, payload, MANAGER_HEADERS))


def renewal_graph(api, property_id, inspector_id, supersedes_inspection_id, **overrides):
    """A signed RENEWAL graph that supersedes the graph it names."""
    overrides.setdefault("purpose", PURPOSE_RENEWAL)
    overrides["supersedes_inspection_id"] = supersedes_inspection_id
    return graphed_inspection(
        api, property_id, inspector_id, overrides.pop("findings", ()), **overrides
    )


def reinstatement_graph(
    api, property_id, inspector_id, supersedes_inspection_id, **overrides
):
    """A signed REINSTATEMENT graph showing a clean structure."""
    overrides.setdefault("purpose", PURPOSE_REINSTATEMENT)
    overrides["supersedes_inspection_id"] = supersedes_inspection_id
    return graphed_inspection(
        api, property_id, inspector_id, overrides.pop("findings", ()), **overrides
    )


def review_bond_term(api, bond_id):
    """Run the compliance term-review sweep against one bond."""
    return get_success_data(api.term_review(bond_id, {}, OFFICER_HEADERS))


def lapse_bond(api, bond, review_instant=None):
    """Park the clock past the grace deadline and review the bond into LAPSED."""
    instant = review_instant or (
        "%sT00:00:00Z" % date_plus_days(bond["current_term_end"], 31)
    )
    set_clock(api, instant)
    return review_bond_term(api, bond["id"])


def reinstate_bond(api, bond_id, reinstatement_inspection_id, amount_usd, **overrides):
    """Buy a LAPSED bond back inside its 90-day reinstatement window."""
    payload = reinstatement_payload(
        reinstatement_inspection_id, amount_usd, **overrides
    )
    return get_success_data(api.reinstate_bond(bond_id, payload, MANAGER_HEADERS))


# ---------------------------------------------------------------------------
# Tier 5: statutory reports
# ---------------------------------------------------------------------------


def real_estate_graph(
    api, property_id, inspector_id, closing_date="2026-08-20", findings=(), **overrides
):
    """A signed REAL_ESTATE graph carrying its closing_date."""
    overrides.setdefault("purpose", PURPOSE_REAL_ESTATE)
    overrides["closing_date"] = closing_date
    return graphed_inspection(api, property_id, inspector_id, findings, **overrides)


def open_wdo_report(api, inspection_id, state_code="FL", headers=None, **overrides):
    """Open a DRAFT statutory report on the form the state mandates."""
    payload = wdo_report_payload(inspection_id, state_code=state_code, **overrides)
    return get_success_data(
        api.create_wdo_report(payload, headers or OFFICER_HEADERS)
    )


def issue_wdo_report(api, report_id):
    """Issue or re-issue a report."""
    return get_success_data(api.issue_wdo_report(report_id, {}, OFFICER_HEADERS))


def amend_wdo_report(api, report_id, **overrides):
    """Amend an ISSUED report inside its amendment window."""
    return get_success_data(
        api.amend_wdo_report(report_id, amendment_payload(**overrides), OFFICER_HEADERS)
    )


def issued_wdo_report(
    api, property_id, inspector_id, closing_date="2026-08-20", state_code="FL"
):
    """Graph a real-estate visit, file the statutory report and issue it."""
    graph = real_estate_graph(api, property_id, inspector_id, closing_date)
    report = open_wdo_report(api, graph["id"], state_code=state_code)
    issued = issue_wdo_report(api, report["id"])
    return graph, issued


# ---------------------------------------------------------------------------
# Tier 5: damage claims
# ---------------------------------------------------------------------------


def file_claim(api, bond, property_id, claimed_damage_usd, **overrides):
    """File a claim against an ACTIVE bond, quoting the bond's current version."""
    expected_version = overrides.pop("expected_bond_version", bond["version"])
    payload = damage_claim_payload(
        bond["id"], expected_version, claimed_damage_usd, **overrides
    )
    return get_success_data(
        api.create_damage_claim(payload, make_property_owner_headers(property_id))
    )


def attach_verification(api, claim_id, verifying_inspection_id, inspector_id, **overrides):
    """Attach a verifying graph, pricing the claim and reserving the payout."""
    payload = verification_payload(verifying_inspection_id, **overrides)
    return get_success_data(
        api.attach_verification(
            claim_id, payload, make_field_inspector_headers(inspector_id)
        )
    )


def adjudicate_claim(api, claim_id, decision, headers=None, **overrides):
    """Decide a claim that is UNDER_ADJUDICATION."""
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api.adjudicate_claim(claim_id, payload, headers or ADJUDICATOR_HEADERS)
    )


def withdraw_claim(api, claim_id, property_id):
    """Withdraw a claim as the bonded homeowner."""
    return get_success_data(
        api.withdraw_claim(claim_id, {}, make_property_owner_headers(property_id))
    )


def verified_claim(
    api,
    chain,
    claimed_damage_usd,
    damages,
    verifier=None,
    supersedes_inspection_id=None,
):
    """File a claim and attach a verifying graph, returning the priced claim.

    ``chain`` is the dict returned by :func:`bonded_property`.  ``verifier``
    names a second licensee when the bond's own applicator may not certify the
    damage; when it is omitted the chain's inspector verifies.
    """
    prop = chain["property"]
    bond = chain["bond"]
    verifying_inspector = verifier or chain["inspector"]
    claim = file_claim(api, bond, prop["id"], claimed_damage_usd)
    graph_overrides = {}
    if supersedes_inspection_id is not None:
        graph_overrides["purpose"] = PURPOSE_RENEWAL
        graph_overrides["supersedes_inspection_id"] = supersedes_inspection_id
    graph = damage_graph(
        api, prop["id"], verifying_inspector["id"], damages, **graph_overrides
    )
    verified = attach_verification(
        api, claim["id"], graph["id"], verifying_inspector["id"]
    )
    return {"claim": verified, "verifying_inspection": graph}


def form_code_for(state_code):
    """The statutory form the supplied jurisdiction mandates."""
    return STATE_FORM_MAP[state_code]
