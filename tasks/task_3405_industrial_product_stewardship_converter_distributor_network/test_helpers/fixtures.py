"""Composite setup helpers for the stewardship workflows (PRD §3).

Every fixture builds its preconditions from scratch against an empty database
and drives the logical clock (PRD §2.4) before any business call. OCC-guarded
writes (PRD §2.6) re-read the parent's current version immediately before
writing. Entity-backed callers (Converter/Distributor) always authenticate
with the real entity id via make_*_headers (PRD §2.1).

Setup calls use the lenient get_success_data validator so a broken
precondition surfaces as a clear setup error rather than an assertion mess.
"""
from prd_bench_local_runner.testing import build_user_headers, get_success_data

from .api_client import api_client
from .constants import CLOCK_NOMINAL_UTC
from .factories import (
    application_case_payload,
    audit_payload,
    authorization_payload,
    book_lab_payload,
    clearance_payload,
    component_payload,
    converter_payload,
    counterfeit_report_payload,
    decision_payload,
    discontinue_payload,
    disposition_payload,
    distributor_payload,
    formulation_payload,
    jurisdiction_payload,
    order_payload,
    phase_out_program_payload,
    price_agreement_payload,
    qualification_payload,
    rebate_program_payload,
    record_result_payload,
    substance_payload,
    successor_payload,
)
from .test_users import TEST_USERS, make_converter_headers, make_distributor_headers

PA = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["product_manager_headers"]
RM = TEST_USERS["regulatory_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]
QA = TEST_USERS["quality_auditor_headers"]
TE = TEST_USERS["technical_engineer_headers"]
FC = TEST_USERS["finance_controller_headers"]


def _rm_headers(user_id="rm-1"):
    return build_user_headers(user_id, "RegulatoryManager")


def _qa_headers(user_id="qa-1"):
    return build_user_headers(user_id, "QualityAuditor")


def _cm_headers(user_id="cm-1"):
    return build_user_headers(user_id, "ChannelManager")


def _fc_headers(user_id="fc-1"):
    return build_user_headers(user_id, "FinanceController")


def _te_headers(user_id="te-1"):
    return build_user_headers(user_id, "TechnicalEngineer")


def _partner_headers(converter_id=None, distributor_id=None):
    if converter_id is not None:
        return make_converter_headers(converter_id)
    return make_distributor_headers(distributor_id)


# ---------------------------------------------------------------------------
# Clock and reference data
# ---------------------------------------------------------------------------

def set_clock(current_utc=CLOCK_NOMINAL_UTC):
    return get_success_data(api_client.set_clock(current_utc, PA))


def create_jurisdiction(code="DE", declaration_threshold_ppm=1000,
                        full_disclosure_threshold_ppm=10000, name=None, **overrides):
    payload = jurisdiction_payload(
        code=code, name=name, declaration_threshold_ppm=declaration_threshold_ppm,
        full_disclosure_threshold_ppm=full_disclosure_threshold_ppm, **overrides)
    return get_success_data(api_client.create_jurisdiction(payload, PA))


def create_substance(cas_number="50-00-0", name="Formaldehyde",
                     restriction_class="RESTRICTED", **overrides):
    payload = substance_payload(cas_number=cas_number, name=name,
                                restriction_class=restriction_class, **overrides)
    return get_success_data(api_client.create_substance(payload, PA))


# ---------------------------------------------------------------------------
# Formulations, components, clearances
# ---------------------------------------------------------------------------

def create_formulation(product_code="F-100", name="Acrylic foam base",
                       base_polymer_family="acrylic", **overrides):
    payload = formulation_payload(product_code=product_code, name=name,
                                  base_polymer_family=base_polymer_family, **overrides)
    return get_success_data(api_client.create_formulation(payload, PM))


def get_formulation(formulation_id):
    return get_success_data(api_client.get_formulation(formulation_id, PM))


def add_component(formulation_id, substance_id, concentration_ppm=5000):
    payload = component_payload(formulation_id, substance_id, concentration_ppm)
    return get_success_data(api_client.create_formulation_component(payload, PM))


def submit_clearance(formulation_id, jurisdiction_id, package="FULL_DISCLOSURE"):
    payload = clearance_payload(formulation_id, jurisdiction_id, package)
    return get_success_data(api_client.create_clearance(payload, PM))


def get_clearance(clearance_id):
    return get_success_data(api_client.get_clearance(clearance_id, PM))


def decide_clearance(clearance_id, decision="CLEARED", decider="rm-1"):
    resp = api_client.decide_clearance(clearance_id, decision_payload(decision),
                                       _rm_headers(decider))
    return get_success_data(resp)


def create_successor_formulation(formulation_id, product_code="F-100R",
                                 name="Reformulated base", base_polymer_family="acrylic"):
    predecessor = get_formulation(formulation_id)
    payload = successor_payload(product_code=product_code, name=name,
                                base_polymer_family=base_polymer_family,
                                expected_formulation_version=predecessor["version"])
    return get_success_data(api_client.create_successor(formulation_id, payload, PM))


def discontinue_formulation(formulation_id, last_time_buy_deadline="2027-01-15T00:00:00Z",
                            last_ship_date="2027-03-01T00:00:00Z", ltb_pool_quantity=1000):
    payload = discontinue_payload(last_time_buy_deadline, last_ship_date, ltb_pool_quantity)
    return get_success_data(api_client.discontinue_formulation(formulation_id, payload, PM))


def setup_active_formulation(product_code="F-100", package="FULL_DISCLOSURE",
                             components=None, jurisdiction_kwargs=None):
    """Jurisdiction + formulation (+components) + a CLEARED clearance, so the
    formulation has bubbled up to ACTIVE. Returns jurisdiction/formulation/clearance."""
    set_clock()
    jur = create_jurisdiction(**(jurisdiction_kwargs or {}))
    form = create_formulation(product_code=product_code)
    for substance_id, ppm in (components or []):
        add_component(form["id"], substance_id, ppm)
    cl = submit_clearance(form["id"], jur["id"], package)
    decide_clearance(cl["id"])
    return {
        "jurisdiction": jur,
        "formulation": get_formulation(form["id"]),
        "clearance": get_clearance(cl["id"]),
    }


# ---------------------------------------------------------------------------
# Converters, distributors, authorizations
# ---------------------------------------------------------------------------

def create_converter(name="ConvertOne GmbH", home_territory_code="DE", **overrides):
    payload = converter_payload(name=name, home_territory_code=home_territory_code, **overrides)
    return get_success_data(api_client.create_converter(payload, CM))


def get_converter(converter_id):
    return get_success_data(api_client.get_converter(converter_id, CM))


def record_audit(converter_id, audit_score=80, audit_standard="ISO9001", auditor="qa-1"):
    payload = audit_payload(audit_score, audit_standard)
    return get_success_data(api_client.record_audit(converter_id, payload, _qa_headers(auditor)))


def authorize_converter(converter_id, authorizer="cm-1"):
    return get_success_data(api_client.authorize_converter(converter_id, _cm_headers(authorizer)))


def create_authorized_converter(name="ConvertOne GmbH", home_territory_code="DE",
                                audit_score=80, auditor="qa-1", authorizer="cm-1"):
    conv = create_converter(name=name, home_territory_code=home_territory_code)
    record_audit(conv["id"], audit_score=audit_score, auditor=auditor)
    return authorize_converter(conv["id"], authorizer=authorizer)


def create_distributor(name="DistribOne GmbH", home_territory_code="DE", **overrides):
    payload = distributor_payload(name=name, home_territory_code=home_territory_code, **overrides)
    return get_success_data(api_client.create_distributor(payload, CM))


def grant_authorization(converter_id, capability="SLITTING", territory_code="DE",
                        valid_from="2026-10-01T00:00:00Z", valid_to="2027-04-01T00:00:00Z"):
    conv = get_converter(converter_id)
    payload = authorization_payload(
        converter_id, capability=capability, territory_code=territory_code,
        valid_from=valid_from, valid_to=valid_to,
        expected_converter_version=conv["version"])
    return get_success_data(api_client.create_converter_authorization(payload, CM))


def create_authorized_converter_with_grant(name="ConvertOne GmbH", capability="SLITTING",
                                           territory_code="DE",
                                           valid_from="2026-10-01T00:00:00Z",
                                           valid_to="2027-04-01T00:00:00Z", **kwargs):
    conv = create_authorized_converter(name=name, **kwargs)
    authz = grant_authorization(conv["id"], capability=capability,
                                territory_code=territory_code,
                                valid_from=valid_from, valid_to=valid_to)
    return conv, authz


# ---------------------------------------------------------------------------
# Price agreements and orders
# ---------------------------------------------------------------------------

def create_agreement(formulation_id, jurisdiction_id, converter_id=None,
                     distributor_id=None, tier="STANDARD", base_price_cents=10000,
                     volume_breakpoints=None, effective_from="2026-10-01T00:00:00Z",
                     effective_to="2027-06-01T00:00:00Z", **overrides):
    payload = price_agreement_payload(
        formulation_id, jurisdiction_id, converter_id=converter_id,
        distributor_id=distributor_id, tier=tier, base_price_cents=base_price_cents,
        volume_breakpoints=volume_breakpoints, effective_from=effective_from,
        effective_to=effective_to, **overrides)
    return get_success_data(api_client.create_price_agreement(payload, CM))


def get_agreement(agreement_id):
    return get_success_data(api_client.get_price_agreement(agreement_id, CM))


def place_order(agreement_id, quantity, converter_id=None, distributor_id=None,
                requested_ship_date="2026-11-01T00:00:00Z", intended_capability=None,
                lot_code=None):
    ag = get_agreement(agreement_id)
    payload = order_payload(
        agreement_id, quantity=quantity, requested_ship_date=requested_ship_date,
        expected_price_agreement_version=ag["version"], converter_id=converter_id,
        distributor_id=distributor_id, intended_capability=intended_capability,
        lot_code=lot_code)
    headers = _partner_headers(converter_id, distributor_id)
    return get_success_data(api_client.create_order(payload, headers))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, CM))


def advance_order(order_id, converter_id=None, distributor_id=None):
    headers = _partner_headers(converter_id, distributor_id)
    return get_success_data(api_client.advance_order(order_id, headers))


def cancel_order(order_id, converter_id=None, distributor_id=None):
    headers = _partner_headers(converter_id, distributor_id)
    return get_success_data(api_client.cancel_order(order_id, headers))


def ship_order(order_id, converter_id=None, distributor_id=None):
    advance_order(order_id, converter_id=converter_id, distributor_id=distributor_id)
    advance_order(order_id, converter_id=converter_id, distributor_id=distributor_id)
    return get_order(order_id)


# ---------------------------------------------------------------------------
# Application cases
# ---------------------------------------------------------------------------

def create_application_case(formulation_id, customer_ref="K-1", substrate_class="METAL",
                            engineer="te-1", **overrides):
    payload = application_case_payload(formulation_id, customer_ref=customer_ref,
                                       substrate_class=substrate_class, **overrides)
    return get_success_data(api_client.create_application_case(payload, _te_headers(engineer)))


def get_application_case(case_id):
    return get_success_data(api_client.get_application_case(case_id, TE))


def book_lab(case_id, bench_id="B1", bench_date="2026-10-05T00:00:00Z", bench_hours=1.0,
             engineer="te-1"):
    payload = book_lab_payload(bench_id, bench_date, bench_hours)
    return get_success_data(api_client.book_lab(case_id, payload, _te_headers(engineer)))


def record_result(case_id, peel_strength_n_per_25mm=16.0, test_temp_c=23,
                  test_standard="NOMINAL", engineer="te-1"):
    payload = record_result_payload(peel_strength_n_per_25mm, test_temp_c, test_standard)
    return get_success_data(api_client.record_result(case_id, payload, _te_headers(engineer)))


# ---------------------------------------------------------------------------
# Rebate programs and accruals
# ---------------------------------------------------------------------------

def create_rebate_program(formulation_id, partner_type="DISTRIBUTOR", converter_id=None,
                          distributor_id=None, period_start="2026-10-01T00:00:00Z",
                          period_end="2027-01-01T00:00:00Z", rebate_tiers=None,
                          budget_cap_cents=1000000, creator="cm-1", **overrides):
    payload = rebate_program_payload(
        formulation_id, partner_type=partner_type, converter_id=converter_id,
        distributor_id=distributor_id, period_start=period_start, period_end=period_end,
        rebate_tiers=rebate_tiers, budget_cap_cents=budget_cap_cents, **overrides)
    return get_success_data(api_client.create_rebate_program(payload, _cm_headers(creator)))


def advance_rebate_program(program_id, activator="fc-1"):
    return get_success_data(api_client.advance_rebate_program(program_id, _fc_headers(activator)))


def get_accrual_for_program(program_id):
    data = get_success_data(api_client.list_rebate_accruals(FC, params={"program_id": program_id}))
    assert isinstance(data, list) and len(data) == 1, "program must own exactly one accrual"
    return data[0]


def get_accrual(accrual_id):
    return get_success_data(api_client.get_rebate_accrual(accrual_id, FC))


def create_active_rebate_program(formulation_id, converter_id=None, distributor_id=None,
                                 creator="cm-1", activator="fc-1", **kwargs):
    """DRAFT program -> ACTIVE; returns (program, its fresh PROVISIONAL accrual)."""
    partner_type = "CONVERTER" if converter_id is not None else "DISTRIBUTOR"
    prog = create_rebate_program(formulation_id, partner_type=partner_type,
                                 converter_id=converter_id, distributor_id=distributor_id,
                                 creator=creator, **kwargs)
    advance_rebate_program(prog["id"], activator=activator)
    accrual = get_accrual_for_program(prog["id"])
    return prog, accrual


def close_rebate_program(program_id, closer="fc-1"):
    return advance_rebate_program(program_id, activator=closer)


# ---------------------------------------------------------------------------
# Phase-out programs
# ---------------------------------------------------------------------------

def create_phase_out_program(substance_id, jurisdiction_codes=("DE",),
                             trigger_concentration_ppm=1000, manager="rm-1"):
    payload = phase_out_program_payload(substance_id, jurisdiction_codes,
                                        trigger_concentration_ppm)
    return get_success_data(api_client.create_phase_out_program(payload, _rm_headers(manager)))


def get_phase_out_program(program_id):
    return get_success_data(api_client.get_phase_out_program(program_id, RM))


def advance_phase_out(program_id, successor_formulation_id=None, manager="rm-1"):
    payload = {}
    if successor_formulation_id is not None:
        payload["successor_formulation_id"] = successor_formulation_id
    return get_success_data(api_client.advance_phase_out_program(program_id, payload,
                                                                 _rm_headers(manager)))


def record_qualification(program_id, customer_ref, samples_passed=3, engineer="te-1"):
    payload = qualification_payload(customer_ref, samples_passed)
    return get_success_data(api_client.record_qualification(program_id, payload,
                                                            _te_headers(engineer)))


def setup_phaseout_enforceable_scenario():
    """Full chain through a QUALIFYING phase-out program with 2 qualified customers:
    F-300 ACTIVE (RESTRICTED component at 5000 ppm, FULL_DISCLOSURE clearance in DE),
    distributor STANDARD agreement base 10000c, ACTIVE rebate program (single tier
    1%), O1 qty 10 lot L-1 SHIPPED, O2 qty 5 lot L-2 PENDING, and a phase-out program
    for the substance in [DE] at trigger 1000 whose successor F-300R is CLEARED in DE.
    """
    set_clock()
    jur = create_jurisdiction()
    sub = create_substance()
    form = create_formulation(product_code="F-300", name="Legacy bonding tape",
                              base_polymer_family="solvent")
    add_component(form["id"], sub["id"], 5000)
    cl = submit_clearance(form["id"], jur["id"], "FULL_DISCLOSURE")
    decide_clearance(cl["id"])
    dist = create_distributor()
    ag = create_agreement(form["id"], jur["id"], distributor_id=dist["id"],
                          tier="STANDARD", base_price_cents=10000)
    prog, acc = create_active_rebate_program(form["id"], distributor_id=dist["id"],
                                             budget_cap_cents=100000000)
    o1 = place_order(ag["id"], 10, distributor_id=dist["id"],
                     requested_ship_date="2026-11-01T00:00:00Z", lot_code="L-1")
    o2 = place_order(ag["id"], 5, distributor_id=dist["id"],
                     requested_ship_date="2026-11-02T00:00:00Z", lot_code="L-2")
    ship_order(o1["id"], distributor_id=dist["id"])
    pop = create_phase_out_program(sub["id"], ["DE"], 1000)
    advance_phase_out(pop["id"])
    succ = create_successor_formulation(form["id"], product_code="F-300R",
                                        name="Reformulated bonding tape",
                                        base_polymer_family="solvent-free")
    cls = submit_clearance(succ["id"], jur["id"], "EXEMPT")
    decide_clearance(cls["id"])
    advance_phase_out(pop["id"], successor_formulation_id=succ["id"])
    record_qualification(pop["id"], "K-1", samples_passed=3)
    record_qualification(pop["id"], "K-2", samples_passed=3)
    return {
        "jurisdiction": jur, "substance": sub, "formulation": get_formulation(form["id"]),
        "clearance": cl, "distributor": dist, "agreement": ag, "program": prog,
        "accrual": acc, "order_shipped": o1, "order_pending": o2,
        "phaseout": get_phase_out_program(pop["id"]),
        "successor": succ, "successor_clearance": cls,
    }


# ---------------------------------------------------------------------------
# Counterfeit reports
# ---------------------------------------------------------------------------

def _reporter_headers(reporter_role, reporter_id):
    if reporter_role == "Converter":
        return make_converter_headers(reporter_id)
    if reporter_role == "Distributor":
        return make_distributor_headers(reporter_id)
    return _qa_headers(reporter_id)


def create_counterfeit_report(formulation_id, lot_code="L-X",
                              channel_description="gray-market reel lot",
                              implicated_converter_id=None,
                              reporter_role="QualityAuditor", reporter_id="qa-1"):
    payload = counterfeit_report_payload(
        formulation_id, lot_code=lot_code, channel_description=channel_description,
        implicated_converter_id=implicated_converter_id)
    headers = _reporter_headers(reporter_role, reporter_id)
    return get_success_data(api_client.create_counterfeit_report(payload, headers))


def disposition_report(report_id, outcome="CONFIRMED_COUNTERFEIT", auditor="qa-9"):
    payload = disposition_payload(outcome)
    return get_success_data(api_client.disposition_report(report_id, payload,
                                                          _qa_headers(auditor)))


def setup_rebate_flagged_scenario():
    """Distributor rebate scenario: STANDARD agreement base 10000c (window equal to
    the program period), rebate tiers [{0,1%},{100,2%},{300,4%}], O1 qty 250 lot L-X
    and O2 qty 100 lot L-Y both SHIPPED, then O1 FLAGGED by a confirmed counterfeit
    report on (formulation, lot L-X)."""
    ctx = setup_active_formulation()
    jur, form = ctx["jurisdiction"], ctx["formulation"]
    dist = create_distributor()
    ag = create_agreement(form["id"], jur["id"], distributor_id=dist["id"],
                          tier="STANDARD", base_price_cents=10000,
                          effective_from="2026-10-01T00:00:00Z",
                          effective_to="2027-01-01T00:00:00Z")
    prog, acc = create_active_rebate_program(
        form["id"], distributor_id=dist["id"],
        rebate_tiers=[{"threshold_qty": 0, "rate_pct": 0.01},
                      {"threshold_qty": 100, "rate_pct": 0.02},
                      {"threshold_qty": 300, "rate_pct": 0.04}],
        budget_cap_cents=100000000)
    o1 = place_order(ag["id"], 250, distributor_id=dist["id"],
                     requested_ship_date="2026-11-01T00:00:00Z", lot_code="L-X")
    o2 = place_order(ag["id"], 100, distributor_id=dist["id"],
                     requested_ship_date="2026-11-02T00:00:00Z", lot_code="L-Y")
    ship_order(o1["id"], distributor_id=dist["id"])
    ship_order(o2["id"], distributor_id=dist["id"])
    rep = create_counterfeit_report(form["id"], "L-X",
                                    reporter_role="Distributor", reporter_id=dist["id"])
    disposition_report(rep["id"], "CONFIRMED_COUNTERFEIT")
    return {
        "jurisdiction": jur, "formulation": form, "distributor": dist,
        "agreement": ag, "program": prog, "accrual": acc,
        "order1": o1, "order2": o2, "report": rep,
    }
