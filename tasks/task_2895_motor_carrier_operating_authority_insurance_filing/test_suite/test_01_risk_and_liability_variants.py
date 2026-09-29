"""Dual-variant quantities: the carrier compliance risk score and the
contract disruption liability.

PRD S3.6 and S3.7 write the *same* field pair on one `Carrier`
(`compliance_risk_score` / `compliance_risk_variant`) from two differently
shaped formulas — one derived from self-reported fleet ratios at activation,
one derived from audited violation counts when the new-entrant audit result is
recorded.  PRD S2.10 and S3.9 do the same on one `CustomerContract`
(`disruption_liability_cents` / `disruption_liability_variant`): a
forward-looking suspension estimate when the contract freezes, replaced by a
settled actual — including the goodwill waiver whose tier is keyed on the
pre-waiver subtotal — when the contract is restored.

Every test builds its own registry, application, authority, coverage,
contract and shipments from scratch through the endpoints of PRD S4, because
the harness empties the database before each test.
"""

from types import SimpleNamespace

from test_helpers import (
    ACTIVATING_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    PUBLISHING_ANALYST,
    REGISTRY_ADMIN,
    THREE_STATES,
    T_ELIGIBLE,
    T_ENROLL,
    T_PUBLISH,
    activate_authority,
    assert_customer_contract,
    assert_no_embargoed_shipments,
    assert_operating_authority,
    assert_risk_score,
    assert_safety_audit,
    assert_shipment,
    authority_for_application,
    create_carrier,
    create_contract,
    create_draft_application,
    create_insurer,
    create_process_agent,
    cure_with_replacement_filing,
    depart_shipment,
    designate_states,
    expected_audited_score,
    expected_self_reported_score,
    expected_settled_actual,
    expected_suspension_estimate,
    file_insurance,
    make_carrier_headers,
    read_authority,
    record_audit,
    review_application,
    scheduled_audit,
    set_clock,
    settle_fee_balance,
    setup_suspended_by_filing_cancel,
    submit_application,
    tender_shipment,
    validate_success,
)

# The carrier of the risk-score scenario: 40 power units, 60 drivers and a
# self-reported roadside out-of-service rate of 12.5 percent.
LONE_STAR = {
    "legal_name": "Lone Star Freight LLC",
    "dba_name": "Lone Star",
    "domicile_state": "TX",
    "self_reported_vehicle_count": 40,
    "self_reported_driver_count": 60,
    "self_reported_oos_rate_pct": 12.5,
}

T_TENDER = "2026-09-02T00:00:00Z"
T_CANCEL = "2026-09-10T00:00:00Z"
T_CURE_FOUR_DAYS = "2026-09-14T00:00:00Z"
T_CURE_TEN_DAYS = "2026-09-20T00:00:00Z"
TERM_START = "2026-09-01T00:00:00Z"
TERM_END = "2026-12-31T00:00:00Z"
MONTHLY_REVENUE_CENTS = 90000000


def _active_for_hire_authority(api, *, legal_name=None, carrier=None):
    """S3.1 -> S3.6: an ACTIVE FOR_HIRE_PROPERTY authority for TX/OK/NM.

    Walks the public chain with the atomic steps of ``test_helpers``: enroll
    the carrier, its process agent and its insurer; draft and submit the
    application (freezing the filing fee); publish it; designate TX/OK/NM;
    file BIPD coverage at the required minimum; settle the fee balance; and
    activate once the 21-day waiting period has elapsed.
    """
    payload = dict(carrier or LONE_STAR)
    if legal_name:
        payload["legal_name"] = legal_name
    set_clock(api, T_ENROLL)
    carrier_row = create_carrier(api, **payload)
    agent = create_process_agent(
        api,
        company_name="Gulf Coast Process Agents",
        coverage_states=THREE_STATES,
        blanket_agent=False,
    )
    insurer = create_insurer(
        api,
        company_name="Permian Mutual Casualty",
        naic_code="12345",
        authorized_states=THREE_STATES,
    )
    application = create_draft_application(
        api,
        carrier_row["id"],
        application_kind="NEW",
        transportation_type="FOR_HIRE_PROPERTY",
        requested_operating_states=THREE_STATES,
        hazmat_endorsement_requested=False,
        hazmat_bulk_capable=False,
    )
    application = submit_application(api, carrier_row["id"], application["id"])
    set_clock(api, T_PUBLISH)
    application = review_application(
        api, application["id"], disposition="PUBLISH", headers=PUBLISHING_ANALYST
    )
    authority = authority_for_application(api, application["id"])
    designations = designate_states(
        api,
        carrier_row["id"],
        authority["id"],
        agent["id"],
        state_codes=list(authority["required_jurisdictions"]),
        effective_from=T_PUBLISH,
    )
    filing = file_insurance(
        api,
        insurer["id"],
        authority["id"],
        authority["required_bipd_limit_cents"],
        filing_type="BIPD",
        effective_at=T_PUBLISH,
        policy_number="BIPD-1",
    )
    settle_fee_balance(api, carrier_row["id"])
    set_clock(api, T_ELIGIBLE)
    authority = activate_authority(api, authority["id"], ACTIVATING_OFFICER)
    return SimpleNamespace(
        carrier=validate_success(api.get_carrier(carrier_row["id"], REGISTRY_ADMIN)),
        carrier_id=carrier_row["id"],
        carrier_headers=make_carrier_headers(carrier_row["id"]),
        agent_id=agent["id"],
        insurer_id=insurer["id"],
        application=application,
        application_id=application["id"],
        authority=authority,
        authority_id=authority["id"],
        designations=designations,
        filings={"BIPD": filing},
        filing=filing,
        activate_at=T_ELIGIBLE,
    )


def _with_contract(api, env, *, shipper_name="Acme Distributing"):
    """S3.9: one ACTIVE contract committing 90000000 cents a month."""
    env.contract = create_contract(
        api,
        env.carrier_id,
        env.authority_id,
        shipper_name=shipper_name,
        commodity_class="GENERAL_FREIGHT",
        monthly_committed_revenue_cents=MONTHLY_REVENUE_CENTS,
        term_start_at=TERM_START,
        term_end_at=TERM_END,
    )
    env.contract_id = env.contract["id"]
    env.authority = read_authority(api, env.authority_id)
    return env


def _depart_shipment(api, env, *, destination_state="OK", expected_delivery_at,
                     declared_value_cents):
    """S3.9: tender a movement on 2026-09-02 and depart it into IN_TRANSIT."""
    shipment = tender_shipment(
        api,
        env.carrier_id,
        env.contract_id,
        origin_state="TX",
        destination_state=destination_state,
        tender_at=T_TENDER,
        expected_delivery_at=expected_delivery_at,
        declared_value_cents=declared_value_cents,
        hazmat=False,
    )
    return depart_shipment(api, env.carrier_id, shipment["id"])


# ---------------------------------------------------------------------------
# The carrier compliance risk score: SELF_REPORTED versus AUDITED
# ---------------------------------------------------------------------------
def test_activation_writes_self_reported_risk_variant_from_fleet_ratios(api):
    """PRD 3.6: "The carrier is also scored for the first time:
    `compliance_risk_score` is written from the self-reported variant below and
    `compliance_risk_variant` becomes `SELF_REPORTED`."
    PRD 3.6: "The out-of-service component is `self_reported_oos_rate_pct`
    multiplied by 2, capped at 100. The driver component is the carrier's
    `self_reported_driver_count` divided by its `self_reported_vehicle_count` —
    using 1 as the divisor if the vehicle count is somehow smaller than 1 —
    then multiplied by 20, capped at 100. The vehicle component is
    `self_reported_vehicle_count` divided by a fleet normaliser of 10 power
    units and then multiplied by 10, capped at 100."
    PRD 3.6: "The raw score is the out-of-service component weighted at 0.45,
    plus the driver component weighted at 0.30, plus the vehicle component
    weighted at 0.25."
    PRD 3.6: "That raw score is then clamped to the range 0.0 through 100.0 —
    never below the floor, never above the ceiling — and the clamped value is
    rounded half-up to exactly two decimal places once."
    PRD 3.6: "That audit's `result_recorded_at`, `audited_oos_rate_pct`,
    `audited_driver_violation_count`, `audited_vehicle_defect_count`,
    `acute_violation_count` and `audit_score` all open at null."

    40 power units, 60 drivers and a 12.5 percent self-reported out-of-service
    rate give components 25, 30 and 40, so the weighted raw score is 30.25.

    Design: Difficulty/dual_variant_calc/carrier_risk_score_self_reported_versus_audited_variant
    """
    env = _active_for_hire_authority(api)
    carrier = env.carrier

    assert_risk_score(carrier["compliance_risk_score"], 30.25)
    assert abs(
        float(carrier["compliance_risk_score"]) - expected_self_reported_score(40, 60, 12.5)
    ) < 0.005, (
        "the self-reported variant must be built from the fleet ratios of S3.6, "
        f"got {carrier['compliance_risk_score']}"
    )
    assert carrier["compliance_risk_variant"] == "SELF_REPORTED", (
        "activation writes the self-reported variant, got "
        f"{carrier['compliance_risk_variant']}"
    )
    assert carrier["audited_oos_rate_pct"] is None, (
        "no audited out-of-service rate exists before a result is recorded, got "
        f"{carrier['audited_oos_rate_pct']}"
    )
    assert float(carrier["self_reported_oos_rate_pct"]) == 12.5

    audit = scheduled_audit(api, env.carrier_id)
    assert_safety_audit(audit)
    assert audit["status"] == "SCHEDULED", f"got {audit['status']}"
    assert audit["audit_score"] is None, (
        f"audit_score opens at null, got {audit['audit_score']}"
    )
    assert audit["audited_oos_rate_pct"] is None
    assert audit["result_recorded_at"] is None


def test_recorded_audit_replaces_carrier_score_with_audited_variant(api):
    """PRD 3.7: "The audited variant of the compliance risk score has the same
    shape as the self-reported variant of §3.6 and the same weights, floor,
    ceiling and rounding, but derives its components from the measured factors
    instead: the out-of-service component is `audited_oos_rate_pct` multiplied
    by 2, capped at 100; the driver component is
    `audited_driver_violation_count` multiplied by 5, capped at 100; the
    vehicle component is `audited_vehicle_defect_count` multiplied by 4, capped
    at 100; and this variant does carry a penalty, namely 12.0 points for each
    acute violation, that is 12.0 multiplied by `acute_violation_count`, added
    to the weighted sum before clamping."
    PRD 3.7: "The result is written to the audit's `audit_score`, and the same
    figure is written to the carrier's `compliance_risk_score` with
    `compliance_risk_variant` set to `AUDITED`; the carrier's
    `audited_oos_rate_pct` is set to the submitted `audited_oos_rate_pct`."
    PRD 3.7: "The outcome is then decided from the already-rounded two-decimal
    `audit_score`: the audit `FAILED` when `audit_score` is at least 40.00 **or**
    when `acute_violation_count` is 1 or more, and `PASSED` otherwise."
    PRD 3.7: "On `SCHEDULED → PASSED`: the carrier's `entrant_status` becomes
    `PERMANENT`, and every `OperatingAuthority` of that carrier whose
    `new_entrant_audit_status` is `PENDING`, walked in `created_at` ascending
    order, moves to `PASSED`."
    PRD 3.7: "Nothing is suspended and no proceeding opens."

    The same carrier that scored 30.25 from its fleet ratios scores 9.60 from
    the measured counts (components 8, 10 and 12, no acute penalty).

    Design: Difficulty/dual_variant_calc/carrier_risk_score_self_reported_versus_audited_variant
    """
    env = _active_for_hire_authority(api)
    assert_risk_score(env.carrier["compliance_risk_score"], 30.25)
    assert env.carrier["compliance_risk_variant"] == "SELF_REPORTED"

    env.audit = scheduled_audit(api, env.carrier_id)
    env.audit_id = env.audit["id"]
    env = record_audit(
        api,
        env,
        headers=COMPLIANCE_OFFICER_ALT,
        audited_oos_rate_pct=4.0,
        audited_driver_violation_count=2,
        audited_vehicle_defect_count=3,
        acute_violation_count=0,
    )

    assert_risk_score(env.audit["audit_score"], 9.60)
    assert abs(
        float(env.audit["audit_score"]) - expected_audited_score(4.0, 2, 3, 0)
    ) < 0.005, (
        f"audited variant expected 9.60, got {env.audit['audit_score']}"
    )
    assert env.audit["status"] == "PASSED", (
        "9.60 is below the inclusive 40.00 threshold and no acute violation was "
        f"recorded, so the audit passes; got {env.audit['status']}"
    )

    assert_risk_score(env.carrier["compliance_risk_score"], 9.60)
    assert env.carrier["compliance_risk_variant"] == "AUDITED", (
        f"got {env.carrier['compliance_risk_variant']}"
    )
    assert float(env.carrier["audited_oos_rate_pct"]) == 4.0, (
        f"audited_oos_rate_pct must hold the submitted figure, got "
        f"{env.carrier['audited_oos_rate_pct']}"
    )
    assert float(env.carrier["self_reported_oos_rate_pct"]) == 12.5, (
        "recording an audit result does not touch the self-reported figures, got "
        f"{env.carrier['self_reported_oos_rate_pct']}"
    )
    assert env.carrier["entrant_status"] == "PERMANENT", (
        f"a passed audit makes the carrier permanent, got {env.carrier['entrant_status']}"
    )

    assert_operating_authority(env.authority)
    assert env.authority["new_entrant_audit_status"] == "PASSED", (
        f"got {env.authority['new_entrant_audit_status']}"
    )
    assert env.authority["authority_status"] == "ACTIVE", (
        f"a passed audit suspends nothing, got {env.authority['authority_status']}"
    )
    assert env.authority["suspension_reason"] == "NONE"


# ---------------------------------------------------------------------------
# The contract disruption liability: SUSPENSION_ESTIMATE versus SETTLED_ACTUAL
# ---------------------------------------------------------------------------
# Instants as the server canonicalises them (PRD S2.4: exactly three
# fractional digits).
C_CANCEL = "2026-09-10T00:00:00.000Z"
C_CURE_FOUR_DAYS = "2026-09-14T00:00:00.000Z"
C_CURE_TEN_DAYS = "2026-09-20T00:00:00.000Z"


def test_suspension_estimate_projects_the_whole_remaining_term(api):
    """PRD 2.10: "hop two visits every `CustomerContract` whose `authority_id`
    names it and whose `status` is `ACTIVE`: each becomes
    `SUSPENDED_BY_AUTHORITY`, its `suspended_at` is set to the current logical
    time, its `resumed_at` is reset to null, its `disruption_liability_cents` is
    written from the suspension-estimate variant described in §3.9, and its
    `disruption_liability_variant` becomes `SUSPENSION_ESTIMATE`."
    PRD 3.9: "Both variants start from the same daily figure: the contract's
    `monthly_committed_revenue_cents` divided by 30, kept as an exact rational
    value rather than rounded at this stage."
    PRD 3.9: "Take the interval from the contract's `suspended_at` to its
    `term_end_at`, convert it to days and round **up** to the next whole day;
    multiply the daily figure by that day count and then by the 15 percent
    penalty rate; round the product half-up to whole cents."
    PRD 2.10: "hop three visits every `Shipment` whose `contract_id` names that
    contract and whose `status` is either `TENDERED` or `IN_TRANSIT`: each
    records its current status into `pre_embargo_status`, becomes `EMBARGOED`,
    and has `embargoed_at` set to the current logical time; the contract's
    `embargoed_shipment_count` is then set to the number of shipments this hop
    moved for it."

    Suspended on 2026-09-10 against a term ending 2026-12-31, the estimate
    projects all 112 remaining days: 3000000 x 112 x 0.15 = 50400000 cents.

    Design: Difficulty/dual_variant_calc/contract_liability_suspension_estimate_versus_settled_actual
    """
    env = _with_contract(api, _active_for_hire_authority(api))
    shipment = _depart_shipment(
        api,
        env,
        destination_state="OK",
        expected_delivery_at="2026-09-05T00:00:00Z",
        declared_value_cents=5000000,
    )
    assert shipment["status"] == "IN_TRANSIT", f"got {shipment['status']}"

    env = setup_suspended_by_filing_cancel(api, env=env, cancel_at=T_CANCEL)

    contract = validate_success(api.get_contract(env.contract_id, env.carrier_headers))
    assert_customer_contract(contract)
    assert contract["status"] == "SUSPENDED_BY_AUTHORITY", (
        f"the insurance lapse must freeze the contract, got {contract['status']}"
    )
    assert contract["suspended_at"] == C_CANCEL, (
        f"suspended_at is the current logical time, got {contract['suspended_at']}"
    )
    assert contract["resumed_at"] is None
    assert contract["disruption_liability_cents"] == 50400000, (
        "the suspension estimate projects the whole remaining term "
        f"(3000000 x 112 x 0.15), expected 50400000, got "
        f"{contract['disruption_liability_cents']}"
    )
    assert contract["disruption_liability_cents"] == expected_suspension_estimate(
        MONTHLY_REVENUE_CENTS, 112
    )
    assert contract["disruption_liability_variant"] == "SUSPENSION_ESTIMATE", (
        f"got {contract['disruption_liability_variant']}"
    )
    assert contract["embargoed_shipment_count"] == 1, (
        f"one IN_TRANSIT shipment was embargoed, got {contract['embargoed_shipment_count']}"
    )

    embargoed = validate_success(api.get_shipment(shipment["id"], env.carrier_headers))
    assert_shipment(embargoed)
    assert embargoed["status"] == "EMBARGOED", f"got {embargoed['status']}"
    assert embargoed["pre_embargo_status"] == "IN_TRANSIT", (
        f"the status held before the embargo is persisted, got "
        f"{embargoed['pre_embargo_status']}"
    )
    assert embargoed["embargoed_at"] == C_CANCEL

    assert env.authority["authority_status"] == "SUSPENDED"
    assert env.authority["suspension_reason"] == "INSURANCE_LAPSE"
    assert env.authority["active_contract_count"] == 0, (
        f"got {env.authority['active_contract_count']}"
    )
    assert env.authority["suspended_contract_count"] == 1, (
        f"got {env.authority['suspended_contract_count']}"
    )


def test_cure_rewrites_disruption_liability_as_settled_actual(api):
    """PRD 2.10: "Hop two visits every `CustomerContract` on that authority
    whose `status` is `SUSPENDED_BY_AUTHORITY`: each returns to `ACTIVE`, its
    `resumed_at` is set to the current logical time, its
    `disruption_liability_cents` is rewritten from the settled-actual variant of
    §3.9, and its `disruption_liability_variant` becomes `SETTLED_ACTUAL`."
    PRD 3.9: "First, take the interval from `suspended_at` to `resumed_at`,
    convert it to days and round up to the next whole day — call that the
    elapsed day count."
    PRD 3.9: "Second, multiply the daily figure by that elapsed day count and
    then by the 15 percent penalty rate, and round half-up to whole cents; that
    is the base charge."
    PRD 3.9: "Third, multiply the daily figure by the contract's
    `embargoed_shipment_count` and then by the same 15 percent rate, and round
    half-up to whole cents; that is the per-shipment penalty."
    PRD 3.9: "Fifth, decide the waiver rate **from that pre-waiver subtotal, not
    from the final figure**: the rate is 10 percent when the pre-waiver subtotal
    is at least $50,000 and zero otherwise — a subtotal of exactly $50,000 is
    waived."
    PRD 3.8: "A successful cure moves the proceeding `NOTICE_ISSUED → CURED`,
    stamps `cured_at` with the current logical time and records the submitted
    `replacement_policy_number`."
    PRD 2.10: "Hop three visits every `Shipment` on each of those contracts
    whose `status` is `EMBARGOED`: each returns to exactly the status recorded in
    its `pre_embargo_status`, sets `embargo_released_at` to the current logical
    time, adds to `embargo_days_accrued` the number of whole days between
    `embargoed_at` and the current logical time rounded up to the next whole
    day, and then resets `pre_embargo_status` to `NONE`."

    Four elapsed embargo days and one embargoed shipment settle at
    1800000 + 450000 = 2250000 cents, a subtotal below the goodwill tier, so
    the estimate of 50400000 is replaced rather than adjusted.

    Design: Difficulty/dual_variant_calc/contract_liability_suspension_estimate_versus_settled_actual
    """
    env = _with_contract(api, _active_for_hire_authority(api))
    shipment = _depart_shipment(
        api,
        env,
        destination_state="OK",
        expected_delivery_at="2026-09-05T00:00:00Z",
        declared_value_cents=5000000,
    )
    env = setup_suspended_by_filing_cancel(api, env=env, cancel_at=T_CANCEL)

    estimated = validate_success(api.get_contract(env.contract_id, env.carrier_headers))
    assert estimated["disruption_liability_cents"] == 50400000
    assert estimated["disruption_liability_variant"] == "SUSPENSION_ESTIMATE"

    env = cure_with_replacement_filing(
        api, env, cure_at=T_CURE_FOUR_DAYS, policy_number="BIPD-2"
    )

    assert env.proceeding["status"] == "CURED", f"got {env.proceeding['status']}"
    assert env.proceeding["cured_at"] == C_CURE_FOUR_DAYS, (
        f"got {env.proceeding['cured_at']}"
    )
    assert env.proceeding["replacement_policy_number"] == "BIPD-2"

    settled = validate_success(api.get_contract(env.contract_id, env.carrier_headers))
    assert_customer_contract(settled)
    assert settled["status"] == "ACTIVE", (
        f"the restoration returns the contract to service, got {settled['status']}"
    )
    assert settled["resumed_at"] == C_CURE_FOUR_DAYS, f"got {settled['resumed_at']}"
    assert settled["disruption_liability_cents"] == 2250000, (
        "the settled actual charges the 4 elapsed days (1800000) plus one "
        "embargoed shipment (450000) with no waiver, expected 2250000, got "
        f"{settled['disruption_liability_cents']}"
    )
    assert settled["disruption_liability_cents"] == expected_settled_actual(
        MONTHLY_REVENUE_CENTS, 4, 1
    )
    assert settled["disruption_liability_variant"] == "SETTLED_ACTUAL", (
        f"got {settled['disruption_liability_variant']}"
    )

    restored = validate_success(api.get_shipment(shipment["id"], env.carrier_headers))
    assert_shipment(restored)
    assert restored["status"] == "IN_TRANSIT", (
        f"the shipment returns to its pre_embargo_status, got {restored['status']}"
    )
    assert restored["pre_embargo_status"] == "NONE", f"got {restored['pre_embargo_status']}"
    assert restored["embargo_released_at"] == C_CURE_FOUR_DAYS
    assert restored["embargo_days_accrued"] == 4, (
        "2026-09-10 to 2026-09-14 is four whole days, got "
        f"{restored['embargo_days_accrued']}"
    )
    assert_no_embargoed_shipments(api, env.contract_id, env.carrier_headers)

    assert env.authority["authority_status"] == "ACTIVE", (
        f"got {env.authority['authority_status']}"
    )
    assert env.authority["suspension_reason"] == "NONE", (
        f"got {env.authority['suspension_reason']}"
    )
    assert env.authority["active_contract_count"] == 1
    assert env.authority["suspended_contract_count"] == 0


# ---------------------------------------------------------------------------
# The goodwill waiver tier, keyed on the pre-waiver subtotal
# ---------------------------------------------------------------------------
def _suspended_with_two_departed_shipments(api):
    """One ACTIVE contract with two IN_TRANSIT shipments, then an insurance
    lapse on 2026-09-10 that embargoes both."""
    env = _with_contract(api, _active_for_hire_authority(api),
                         shipper_name="Panhandle Grain Co")
    env.shipment_a = _depart_shipment(
        api,
        env,
        destination_state="OK",
        expected_delivery_at="2026-09-05T00:00:00Z",
        declared_value_cents=5000000,
    )
    env.shipment_b = _depart_shipment(
        api,
        env,
        destination_state="NM",
        expected_delivery_at="2026-09-06T00:00:00Z",
        declared_value_cents=3000000,
    )
    return setup_suspended_by_filing_cancel(api, env=env, cancel_at=T_CANCEL)


def test_settled_liability_waiver_is_decided_on_the_pre_waiver_subtotal(api):
    """PRD 3.9: "Third, multiply the daily figure by the contract's
    `embargoed_shipment_count` and then by the same 15 percent rate, and round
    half-up to whole cents; that is the per-shipment penalty."
    PRD 3.9: "Fourth, add the base charge and the per-shipment penalty to obtain
    the pre-waiver subtotal."
    PRD 3.9: "Fifth, decide the waiver rate **from that pre-waiver subtotal, not
    from the final figure**: the rate is 10 percent when the pre-waiver subtotal
    is at least $50,000 and zero otherwise — a subtotal of exactly $50,000 is
    waived."
    PRD 3.9: "Sixth, multiply the pre-waiver subtotal by the waiver rate, round
    that product half-up to whole cents, and subtract it from the pre-waiver
    subtotal."
    PRD 3.9: "Because the waiver tier is keyed on the pre-waiver subtotal, the
    order above is the only order that yields a well-defined figure."

    Ten elapsed days give a base charge of 4500000, which alone sits below the
    tier; the two embargoed shipments add 900000, lifting the pre-waiver
    subtotal to 5400000 so the 10 percent waiver of 540000 does apply and the
    contract settles at 4860000 rather than 5400000.

    Design: Difficulty/combinatorial_formula/settled_liability_waiver_tier_keyed_on_pre_waiver_subtotal
    """
    env = _suspended_with_two_departed_shipments(api)
    env = cure_with_replacement_filing(
        api, env, cure_at=T_CURE_TEN_DAYS, policy_number="BIPD-2"
    )

    settled = validate_success(api.get_contract(env.contract_id, env.carrier_headers))
    assert_customer_contract(settled)
    assert settled["resumed_at"] == C_CURE_TEN_DAYS, f"got {settled['resumed_at']}"
    assert settled["disruption_liability_cents"] == 4860000, (
        "base 4500000 + per-shipment penalty 900000 = pre-waiver subtotal 5400000, "
        "which is at or above the goodwill tier, so 540000 is waived; expected "
        f"4860000, got {settled['disruption_liability_cents']}"
    )
    assert settled["disruption_liability_cents"] != 5400000, (
        "the waiver tier is decided on the pre-waiver subtotal, not on the base "
        "charge alone, so the waiver must not be skipped"
    )
    assert settled["disruption_liability_cents"] == expected_settled_actual(
        MONTHLY_REVENUE_CENTS, 10, 2
    )
    assert settled["disruption_liability_variant"] == "SETTLED_ACTUAL", (
        f"got {settled['disruption_liability_variant']}"
    )
    assert settled["status"] == "ACTIVE", f"got {settled['status']}"


def test_embargoed_shipment_count_feeds_the_settled_liability_and_both_release(api):
    """PRD 2.10: "hop three visits every `Shipment` whose `contract_id` names
    that contract and whose `status` is either `TENDERED` or `IN_TRANSIT`: each
    records its current status into `pre_embargo_status`, becomes `EMBARGOED`,
    and has `embargoed_at` set to the current logical time; the contract's
    `embargoed_shipment_count` is then set to the number of shipments this hop
    moved for it."
    PRD 2.10: "Hop three visits every `Shipment` on each of those contracts
    whose `status` is `EMBARGOED`: each returns to exactly the status recorded in
    its `pre_embargo_status`, sets `embargo_released_at` to the current logical
    time, adds to `embargo_days_accrued` the number of whole days between
    `embargoed_at` and the current logical time rounded up to the next whole
    day, and then resets `pre_embargo_status` to `NONE`."
    PRD 2.10: "The authority's `suspended_contract_count` decreases by the
    number of contracts hop two moved, its `active_contract_count` increases by
    that same number, and the carrier's `active_authority_count` increases by
    one."

    Both departed shipments are counted into `embargoed_shipment_count`, which
    is the multiplicand of the per-shipment penalty that lifts the subtotal over
    the goodwill tier, and both accrue the ten whole days of the embargo.

    Design: Difficulty/combinatorial_formula/settled_liability_waiver_tier_keyed_on_pre_waiver_subtotal
    """
    env = _suspended_with_two_departed_shipments(api)

    frozen = validate_success(api.get_contract(env.contract_id, env.carrier_headers))
    assert frozen["embargoed_shipment_count"] == 2, (
        f"both IN_TRANSIT shipments were embargoed, got {frozen['embargoed_shipment_count']}"
    )
    assert frozen["disruption_liability_cents"] == 50400000, (
        "the forward-looking estimate is booked first, got "
        f"{frozen['disruption_liability_cents']}"
    )
    assert frozen["disruption_liability_variant"] == "SUSPENSION_ESTIMATE"

    env = cure_with_replacement_filing(
        api, env, cure_at=T_CURE_TEN_DAYS, policy_number="BIPD-2"
    )

    for label, shipment in (("a", env.shipment_a), ("b", env.shipment_b)):
        restored = validate_success(
            api.get_shipment(shipment["id"], env.carrier_headers)
        )
        assert_shipment(restored)
        assert restored["status"] == "IN_TRANSIT", (
            f"shipment {label} must return to its pre_embargo_status, got "
            f"{restored['status']}"
        )
        assert restored["pre_embargo_status"] == "NONE", (
            f"shipment {label}: got {restored['pre_embargo_status']}"
        )
        assert restored["embargo_released_at"] == C_CURE_TEN_DAYS
        assert restored["embargo_days_accrued"] == 10, (
            f"shipment {label}: 2026-09-10 to 2026-09-20 is ten whole days, got "
            f"{restored['embargo_days_accrued']}"
        )
    assert_no_embargoed_shipments(api, env.contract_id, env.carrier_headers)

    assert env.authority["authority_status"] == "ACTIVE", (
        f"got {env.authority['authority_status']}"
    )
    assert env.authority["suspended_contract_count"] == 0, (
        f"got {env.authority['suspended_contract_count']}"
    )
    assert env.authority["active_contract_count"] == 1, (
        f"got {env.authority['active_contract_count']}"
    )
