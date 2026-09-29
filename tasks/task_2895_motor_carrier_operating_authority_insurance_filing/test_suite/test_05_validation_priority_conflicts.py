"""Which single error is reported when one request violates two rules at once.

PRD S2.8 fixes a numbered ladder, highest priority first, so a request that
breaks two rules is answered by whichever rule sits higher.  Two pairs are
exercised here, both drawn from that ladder's own text:

* on ``POST /operating-authorities/{id}/activate``, the target-state rung
  (``ERR_AUTHORITY_INVALID_STATE``, rung 10) outranks the money rung
  (``ERR_FILING_FEE_OUTSTANDING``, rung 31);
* on ``POST /customer-contracts/{id}/shipments``, the safety rung
  (``ERR_HAZMAT_AUTHORITY_REQUIRED``, rung 16) outranks the referential-coverage
  rung (``ERR_PROCESS_AGENT_NOT_DESIGNATED``, rung 24).

Each pair is tested three ways: the two-violation request that the ladder must
disambiguate, and single-violation requests proving the lower-ranked rule really
does fire on that endpoint when it is the only thing wrong.  Every test builds
its own chain, because the harness empties the database before each test.
"""

from types import SimpleNamespace

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER,
    MAX_LIMIT,
    REGISTRY_ADMIN,
    THREE_STATES,
    activate_authority,
    authority_for_application,
    create_carrier,
    create_contract,
    create_draft_application,
    create_insurer,
    create_process_agent,
    designate_states,
    file_insurance,
    list_designations,
    make_carrier_headers,
    pay_fee,
    read_authority,
    review_application,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

T_ENROLL_AT = "2026-08-01T00:00:00Z"
T_PUBLISH_AT = "2026-08-05T00:00:00Z"
T_ACTIVATE_AT = "2026-08-26T00:00:00Z"
T_ACTIVATE_STAMP = "2026-08-26T00:00:00.000Z"
T_TENDER_AT = "2026-09-02T00:00:00Z"

BIPD_LIMIT_CENTS = 75000000
FILING_FEE_CENTS = 64791
MONTHLY_REVENUE_CENTS = 90000000
UNDESIGNATED_STATE = "CA"


# ---------------------------------------------------------------------------
# Local chain builder (the atomic PRD S4 calls, in the order S3 pins them)
# ---------------------------------------------------------------------------
def _chain(
    api,
    *,
    legal_name,
    pay_the_fee=True,
    activate=True,
    with_contract=False,
) -> SimpleNamespace:
    """A NEW FOR_HIRE_PROPERTY docket for NM/OK/TX, with no hazmat endorsement.

    Coverage is designated for exactly those three states and the single required
    BIPD slot is filled, so the only activation condition that can be made to
    fail is the one the caller chooses.  The clock is left on 2026-08-26, which
    is the authority's ``activation_eligible_at``.
    """
    set_clock(api, T_ENROLL_AT)
    carrier = create_carrier(
        api,
        legal_name=legal_name,
        domicile_state="TX",
        self_reported_vehicle_count=40,
        self_reported_driver_count=60,
        self_reported_oos_rate_pct=12.5,
    )
    agent = create_process_agent(
        api,
        company_name="Gulf Coast Process Agents",
        coverage_states=list(THREE_STATES),
        blanket_agent=False,
    )
    insurer = create_insurer(
        api,
        company_name="Permian Mutual Casualty",
        naic_code="12345",
        authorized_states=list(THREE_STATES),
    )
    application = create_draft_application(
        api,
        carrier["id"],
        application_kind="NEW",
        transportation_type="FOR_HIRE_PROPERTY",
        requested_operating_states=list(THREE_STATES),
        hazmat_endorsement_requested=False,
        hazmat_bulk_capable=False,
    )
    submitted = submit_application(api, carrier["id"], application["id"])
    assert submitted["filing_fee_cents"] == FILING_FEE_CENTS, submitted
    set_clock(api, T_PUBLISH_AT)
    application = review_application(
        api,
        application["id"],
        disposition="PUBLISH",
        findings="no adverse vetting findings",
    )
    authority = authority_for_application(api, application["id"])
    designate_states(
        api,
        carrier["id"],
        authority["id"],
        agent["id"],
        state_codes=list(THREE_STATES),
        effective_from=T_PUBLISH_AT,
    )
    file_insurance(
        api,
        insurer["id"],
        authority["id"],
        BIPD_LIMIT_CENTS,
        filing_type="BIPD",
        effective_at=T_PUBLISH_AT,
        policy_number="BIPD-1",
    )
    if pay_the_fee:
        pay_fee(api, carrier["id"], FILING_FEE_CENTS, memo="docket filing fee")
    set_clock(api, T_ACTIVATE_AT)
    if activate:
        activate_authority(api, authority["id"], COMPLIANCE_OFFICER)
    contract = None
    if with_contract:
        contract = create_contract(
            api,
            carrier["id"],
            authority["id"],
            shipper_name="Yellow House Grain",
            commodity_class="GENERAL_FREIGHT",
            monthly_committed_revenue_cents=MONTHLY_REVENUE_CENTS,
            term_start_at="2026-09-01T00:00:00Z",
            term_end_at="2026-12-31T00:00:00Z",
        )
    return SimpleNamespace(
        carrier_id=carrier["id"],
        carrier_headers=make_carrier_headers(carrier["id"]),
        insurer_id=insurer["id"],
        process_agent_id=agent["id"],
        application_id=application["id"],
        authority=read_authority(api, authority["id"]),
        authority_id=authority["id"],
        contract=contract,
        contract_id=contract["id"] if contract else None,
    )


def _leave_a_fee_outstanding(api, env) -> int:
    """Submit a second NEW docket, whose fee lands on the same carrier's balance."""
    second = create_draft_application(
        api,
        env.carrier_id,
        application_kind="NEW",
        transportation_type="FOR_HIRE_PROPERTY",
        requested_operating_states=list(THREE_STATES),
    )
    submit_application(api, env.carrier_id, second["id"])
    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["fee_balance_cents"] > 0, (
        f"the second submission must leave money outstanding, got {carrier}"
    )
    return carrier["fee_balance_cents"]


# ---------------------------------------------------------------------------
# activate: the target-state rung outranks the money rung
# ---------------------------------------------------------------------------
def test_activate_state_error_outranks_the_outstanding_filing_fee(api):
    """PRD S2.8: "The authority admits the requested trigger —
    `ERR_AUTHORITY_INVALID_STATE` (HTTP 409). Applies to
    `POST /operating-authorities/{id}/activate` (requires `PENDING`)"
    PRD S2.8: "Money last — `ERR_FILING_FEE_OUTSTANDING` (HTTP 402). Applies to
    `POST /operating-authorities/{id}/activate`."
    PRD S2.8: "then target-state preconditions, then safety and regulatory checks, then
    temporal conflicts, then referential coverage, then constraint satisfaction, and
    money last"
    PRD S3.6: "The authority must be `PENDING`; activating anything else is
    `ERR_AUTHORITY_INVALID_STATE`."
    PRD S3.6: "The authority's `authority_status` becomes `ACTIVE`, its `activated_at` is
    stamped with the current logical time, and its `insurance_status` is set to `FILED`."
    PRD S3.6: "On the owning carrier, `unified_registration_status` becomes `REGISTERED`
    and `active_authority_count` increases by one."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_error_outranks_outstanding_filing_fee
    """
    env = _chain(api, legal_name="Caprock Logistics LLC")
    assert env.authority["authority_status"] == "ACTIVE", env.authority
    outstanding = _leave_a_fee_outstanding(api, env)
    assert outstanding == FILING_FEE_CENTS, (
        f"the second NEW docket for three states costs {FILING_FEE_CENTS} cents, "
        f"got {outstanding}"
    )

    response = api.activate_authority(env.authority_id, COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.AUTHORITY_INVALID_STATE, 409)

    authority = read_authority(api, env.authority_id)
    assert authority["authority_status"] == "ACTIVE", authority
    assert authority["activated_at"] == T_ACTIVATE_STAMP, (
        f"the first activation stamped activated_at {T_ACTIVATE_STAMP} and the refused "
        f"call reports a state error instead of restamping it, got "
        f"{authority['activated_at']}"
    )
    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["active_authority_count"] == 1, carrier
    assert carrier["unified_registration_status"] == "REGISTERED", carrier
    assert carrier["fee_balance_cents"] == FILING_FEE_CENTS, (
        f"the fiscal violation was genuinely present and was outranked, got {carrier}"
    )


def test_outstanding_filing_fee_alone_refuses_activation_with_the_money_error(api):
    """PRD S3.6: "Finally, money is checked last: the carrier's `fee_balance_cents` must
    be zero or negative, meaning nothing is outstanding. A strictly positive balance is
    refused with `ERR_FILING_FEE_OUTSTANDING` (HTTP 402) — the only 402 in the system."
    PRD S2.8: "Money last — `ERR_FILING_FEE_OUTSTANDING` (HTTP 402). Applies to
    `POST /operating-authorities/{id}/activate`."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_error_outranks_outstanding_filing_fee
    """
    env = _chain(api, legal_name="Llano Estacado Freight LLC", pay_the_fee=False, activate=False)
    assert env.authority["authority_status"] == "PENDING", env.authority
    assert env.authority["designation_coverage_complete"] is True, env.authority
    assert env.authority["insurance_status"] == "FILED", env.authority
    assert env.authority["activation_eligible_at"] == T_ACTIVATE_STAMP, env.authority
    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["fee_balance_cents"] == FILING_FEE_CENTS, carrier
    assert carrier["biennial_delinquent"] is False, carrier

    response = api.activate_authority(env.authority_id, COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.FILING_FEE_OUTSTANDING, 402)

    unchanged = read_authority(api, env.authority_id)
    assert unchanged["authority_status"] == "PENDING", unchanged
    assert unchanged["activated_at"] is None, unchanged


def test_suspended_authority_reports_the_state_error_not_the_money_error(api):
    """PRD S2.8: "The authority admits the requested trigger —
    `ERR_AUTHORITY_INVALID_STATE` (HTTP 409). Applies to
    `POST /operating-authorities/{id}/activate` (requires `PENDING`)"
    PRD S2.8: "Money last — `ERR_FILING_FEE_OUTSTANDING` (HTTP 402). Applies to
    `POST /operating-authorities/{id}/activate`."
    PRD S3.4: "And because coverage became incomplete, if the authority was `ACTIVE` the
    full suspension cascade of §2.10 runs with `suspension_reason` set to
    `DESIGNATION_GAP`"
    PRD S3.6: "The authority's `authority_status` becomes `ACTIVE`, its `activated_at` is
    stamped with the current logical time, and its `insurance_status` is set to `FILED`."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_error_outranks_outstanding_filing_fee
    """
    env = _chain(api, legal_name="Pecos Valley Carriers LLC")
    assert env.authority["activated_at"] == T_ACTIVATE_STAMP, env.authority
    assert env.authority["insurance_status"] == "FILED", env.authority

    rows = list_designations(api, env.authority_id, state_code="TX")
    assert len(rows) == 1, rows
    validate_success(api.revoke_designation(rows[0]["id"], env.carrier_headers))
    suspended = read_authority(api, env.authority_id)
    assert suspended["authority_status"] == "SUSPENDED", suspended
    assert suspended["suspension_reason"] == "DESIGNATION_GAP", suspended
    assert suspended["designation_coverage_complete"] is False, suspended

    _leave_a_fee_outstanding(api, env)

    response = api.activate_authority(env.authority_id, COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.AUTHORITY_INVALID_STATE, 409)

    after = read_authority(api, env.authority_id)
    assert after["authority_status"] == "SUSPENDED", after
    assert after["activated_at"] == T_ACTIVATE_STAMP, (
        "the earlier successful activation stamped activated_at, and the refused "
        f"request reports a state error rather than reactivating: got {after['activated_at']}"
    )


# ---------------------------------------------------------------------------
# tender: the hazmat rung outranks the process-agent-coverage rung
# ---------------------------------------------------------------------------
def _tender(api, env, *, destination_state, hazmat):
    set_clock(api, T_TENDER_AT)
    return api.create_shipment(
        env.contract_id,
        {
            "origin_state": "TX",
            "destination_state": destination_state,
            "tender_at": "2026-09-02T00:00:00Z",
            "expected_delivery_at": "2026-09-20T00:00:00Z",
            "declared_value_cents": 7000000,
            "hazmat": hazmat,
        },
        env.carrier_headers,
    )


def _shipments_on(api, env):
    return validate_paginated(
        api.list_shipments(REGISTRY_ADMIN, contract_id=env.contract_id, limit=MAX_LIMIT)
    )


def test_shipment_hazmat_error_outranks_the_missing_process_agent(api):
    """PRD S2.8: "Hazardous-materials authority — `ERR_HAZMAT_AUTHORITY_REQUIRED`
    (HTTP 422). Applies to `POST /customer-contracts/{id}/shipments`."
    PRD S2.8: "Both endpoints of the movement sit in designated states —
    `ERR_PROCESS_AGENT_NOT_DESIGNATED` (HTTP 422). Applies to
    `POST /customer-contracts/{id}/shipments`."
    PRD S2.8: "then safety and regulatory checks, then temporal conflicts, then
    referential coverage"
    PRD S3.4: "Its `transportation_type` is copied verbatim from the application, as are
    `hazmat_endorsed` (from `hazmat_endorsement_requested`), `hazmat_bulk_capable` and
    `passenger_seating_capacity`."

    Design: Difficulty/priority_pair_validation_conflict/shipment_hazmat_safety_error_outranks_missing_process_agent
    """
    env = _chain(api, legal_name="Sabine River Transport LLC", with_contract=True)
    assert env.authority["hazmat_endorsed"] is False, env.authority
    assert env.contract["status"] == "ACTIVE", env.contract
    covered = list_designations(api, env.authority_id, state_code=UNDESIGNATED_STATE)
    assert covered == [], (
        f"{UNDESIGNATED_STATE} must have no designation on this authority, got {covered}"
    )

    response = _tender(api, env, destination_state=UNDESIGNATED_STATE, hazmat=True)
    validate_error(response, ApiErrorId.HAZMAT_AUTHORITY_REQUIRED, 422)

    shipments, meta = _shipments_on(api, env)
    assert meta["total_count"] == 0, (
        f"the refused tender must leave no shipment behind, got {shipments}"
    )


def test_undesignated_destination_alone_refuses_the_tender(api):
    """PRD S3.9: "And service of process must be arranged at both ends of the movement:
    both `origin_state` and `destination_state` must be covered by an `ACTIVE`
    `ProcessAgentDesignation` on the owning authority whose interval contains the current
    logical time, failing which the tender is rejected with
    `ERR_PROCESS_AGENT_NOT_DESIGNATED`."
    PRD S2.8: "Both endpoints of the movement sit in designated states —
    `ERR_PROCESS_AGENT_NOT_DESIGNATED` (HTTP 422). Applies to
    `POST /customer-contracts/{id}/shipments`."

    Design: Difficulty/priority_pair_validation_conflict/shipment_hazmat_safety_error_outranks_missing_process_agent
    """
    env = _chain(api, legal_name="Neches Valley Haulers LLC", with_contract=True)
    assert env.authority["hazmat_endorsed"] is False, env.authority
    assert list_designations(api, env.authority_id, state_code=UNDESIGNATED_STATE) == []

    response = _tender(api, env, destination_state=UNDESIGNATED_STATE, hazmat=False)
    validate_error(response, ApiErrorId.PROCESS_AGENT_NOT_DESIGNATED, 422)

    shipments, meta = _shipments_on(api, env)
    assert meta["total_count"] == 0, shipments


def test_hazmat_flag_alone_refuses_the_tender_between_designated_states(api):
    """PRD S3.2: "a `HAZMAT_NONBULK` contract, or any individual shipment whose `hazmat`
    flag is true, requires only the endorsement"
    PRD S3.9: "The hazardous-materials rules of §3.2 apply here, rejected with
    `ERR_HAZMAT_AUTHORITY_REQUIRED`."
    PRD S3.9: "A brand-new contract opens with `status` `ACTIVE`,
    `embargoed_shipment_count` zero, `disruption_liability_cents` zero"

    Design: Difficulty/priority_pair_validation_conflict/shipment_hazmat_safety_error_outranks_missing_process_agent
    """
    env = _chain(api, legal_name="Red River Drayage LLC", with_contract=True)
    designated = list_designations(api, env.authority_id, state_code="OK")
    assert len(designated) == 1 and designated[0]["status"] == "ACTIVE", designated

    response = _tender(api, env, destination_state="OK", hazmat=True)
    validate_error(response, ApiErrorId.HAZMAT_AUTHORITY_REQUIRED, 422)

    shipments, meta = _shipments_on(api, env)
    assert meta["total_count"] == 0, shipments
    contract = validate_success(api.get_contract(env.contract_id, REGISTRY_ADMIN))
    assert contract["status"] == "ACTIVE", contract
    assert contract["embargoed_shipment_count"] == 0, contract
    assert contract["disruption_liability_cents"] == 0, contract
