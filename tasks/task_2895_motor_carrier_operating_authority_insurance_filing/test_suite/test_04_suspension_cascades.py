"""The two transitive suspension cascades that start below the authority.

A process-agent designation revoke and an insurance-filing cancel both walk the
same three hops of PRD S2.10 — authority, then its ACTIVE contracts, then those
contracts' TENDERED and IN_TRANSIT shipments — but they differ in one decisive
way: a designation gap is self-curable and opens no ``RevocationProceeding``,
while an insurance lapse mints one with a thirty-day cure deadline before the
suspension runs.

Each test builds the whole registry -> application -> publication -> designation
-> insurance -> activation -> contract -> shipment chain from scratch, because
the harness restarts the server and empties the database before every test.
"""

from types import SimpleNamespace

from test_helpers import (
    MAX_LIMIT,
    REGISTRY_ADMIN,
    THREE_STATES,
    assert_contract_population_identity,
    assert_created_at_ascending,
    assert_customer_contract,
    assert_designation,
    assert_insurance_filing,
    assert_operating_authority,
    assert_revocation_proceeding,
    assert_shipment,
    activate_authority,
    authority_for_application,
    cancel_filing,
    create_carrier,
    create_contract,
    create_draft_application,
    create_insurer,
    create_process_agent,
    depart_shipment,
    designate_states,
    expected_suspension_estimate,
    file_insurance,
    make_carrier_headers,
    pay_fee,
    read_authority,
    review_application,
    set_clock,
    submit_application,
    tender_shipment,
    validate_paginated,
    validate_success,
)

T_ENROLL_AT = "2026-08-01T00:00:00Z"
T_PUBLISH_AT = "2026-08-05T00:00:00Z"
T_ACTIVATE_AT = "2026-08-26T00:00:00Z"
T_TENDER_AT = "2026-09-02T00:00:00Z"
T_DEFECT_AT = "2026-09-10T00:00:00Z"
T_DEFECT_STAMP = "2026-09-10T00:00:00.000Z"
T_CURE_DEADLINE_STAMP = "2026-10-10T00:00:00.000Z"

BIPD_LIMIT_CENTS = 75000000
FILING_FEE_CENTS = 64791
MONTHLY_REVENUE_CENTS = 90000000
TERM_END_AT = "2026-12-31T00:00:00Z"

# PRD S3.9: 2026-09-10 to 2026-12-31 is 112 whole days of remaining term, and
# 90000000 / 30 * 112 * 0.15 rounds to this many whole cents.
SUSPENSION_ESTIMATE_CENTS = 50400000
REMAINING_TERM_DAYS = 112


# ---------------------------------------------------------------------------
# Local chain builder (the atomic PRD S4 calls, in the order S3 pins them)
# ---------------------------------------------------------------------------
def _active_authority_with_shipment(
    api,
    *,
    legal_name,
    shipper_name,
    destination_state,
    expected_delivery_at,
    declared_value_cents,
    depart,
) -> SimpleNamespace:
    """One ACTIVE FOR_HIRE_PROPERTY authority for NM/OK/TX with a live shipment.

    The logical clock is left parked on the defect instant 2026-09-10, so the
    cascade under test stamps that instant everywhere.
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
    )
    submit_application(api, carrier["id"], application["id"])
    set_clock(api, T_PUBLISH_AT)
    application = review_application(
        api,
        application["id"],
        disposition="PUBLISH",
        findings="no adverse vetting findings",
    )
    authority = authority_for_application(api, application["id"])
    designations = designate_states(
        api,
        carrier["id"],
        authority["id"],
        agent["id"],
        state_codes=list(THREE_STATES),
        effective_from=T_PUBLISH_AT,
    )
    filing = file_insurance(
        api,
        insurer["id"],
        authority["id"],
        BIPD_LIMIT_CENTS,
        filing_type="BIPD",
        effective_at=T_PUBLISH_AT,
        policy_number="BIPD-1",
    )
    pay_fee(api, carrier["id"], FILING_FEE_CENTS, memo="docket filing fee")
    set_clock(api, T_ACTIVATE_AT)
    authority = activate_authority(api, authority["id"])
    contract = create_contract(
        api,
        carrier["id"],
        authority["id"],
        shipper_name=shipper_name,
        commodity_class="GENERAL_FREIGHT",
        monthly_committed_revenue_cents=MONTHLY_REVENUE_CENTS,
        term_start_at="2026-09-01T00:00:00Z",
        term_end_at=TERM_END_AT,
    )
    set_clock(api, T_TENDER_AT)
    shipment = tender_shipment(
        api,
        carrier["id"],
        contract["id"],
        origin_state="TX",
        destination_state=destination_state,
        tender_at=T_TENDER_AT,
        expected_delivery_at=expected_delivery_at,
        declared_value_cents=declared_value_cents,
        hazmat=False,
    )
    if depart:
        shipment = depart_shipment(api, carrier["id"], shipment["id"])
    set_clock(api, T_DEFECT_AT)
    return SimpleNamespace(
        carrier_id=carrier["id"],
        carrier_headers=make_carrier_headers(carrier["id"]),
        insurer_id=insurer["id"],
        authority=read_authority(api, authority["id"]),
        authority_id=authority["id"],
        designations=designations,
        filing=filing,
        filing_id=filing["id"],
        contract=contract,
        contract_id=contract["id"],
        shipment=shipment,
        shipment_id=shipment["id"],
    )


def _designation_for_state(env, state_code):
    matches = [d for d in env.designations if d["state_code"] == state_code]
    assert matches, f"no designation was created for {state_code}: {env.designations}"
    return matches[0]


def _in_transit_chain(api) -> SimpleNamespace:
    return _active_authority_with_shipment(
        api,
        legal_name="Caprock Logistics LLC",
        shipper_name="Llano Cement Co",
        destination_state="OK",
        expected_delivery_at="2026-09-20T00:00:00Z",
        declared_value_cents=5000000,
        depart=True,
    )


def _tendered_chain(api) -> SimpleNamespace:
    return _active_authority_with_shipment(
        api,
        legal_name="Sabine River Transport LLC",
        shipper_name="Neches Chemical Supply",
        destination_state="NM",
        expected_delivery_at="2026-09-22T00:00:00Z",
        declared_value_cents=4000000,
        depart=False,
    )


def _proceedings(api, authority_id):
    return validate_paginated(
        api.list_authority_proceedings(authority_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )


# ---------------------------------------------------------------------------
# Revoking one designation: three hops, no proceeding
# ---------------------------------------------------------------------------
def test_designation_revoke_suspends_the_authority_without_opening_a_proceeding(api):
    """PRD S3.4: "**Revoking a designation** is a `CarrierRep` action on its own
    designation and moves that row `ACTIVE → REVOKED` with `revoked_at` stamped at the
    current logical time."
    PRD S3.4: "Because the row left the active set, coverage is recomputed,
    `designated_state_count` drops, and `designation_coverage_complete` may become
    false."
    PRD S3.4: "And because coverage became incomplete, if the authority was `ACTIVE`
    the full suspension cascade of §2.10 runs with `suspension_reason` set to
    `DESIGNATION_GAP`"
    PRD S3.4: "No revocation proceeding is opened for a designation gap, because the
    defect is self-curable: the carrier simply files a replacement designation."

    Design: Difficulty/transitive_cascade/designation_revoke_cascades_three_hops_without_a_proceeding
    """
    env = _in_transit_chain(api)
    assert env.authority["authority_status"] == "ACTIVE", env.authority
    assert env.authority["designated_state_count"] == len(THREE_STATES), env.authority
    assert env.authority["designation_coverage_complete"] is True, env.authority

    texas = _designation_for_state(env, "TX")
    revoked = validate_success(
        api.revoke_designation(texas["id"], env.carrier_headers)
    )
    assert_designation(revoked)
    assert revoked["status"] == "REVOKED", revoked
    assert revoked["revoked_at"] == T_DEFECT_STAMP, (
        f"revoked_at is stamped at the current logical time {T_DEFECT_STAMP}, "
        f"got {revoked['revoked_at']}"
    )

    authority = read_authority(api, env.authority_id)
    assert_operating_authority(authority)
    assert authority["designated_state_count"] == 2, (
        f"revoking one of three required jurisdictions leaves 2 covered, "
        f"got {authority['designated_state_count']}"
    )
    assert authority["designation_coverage_complete"] is False, authority
    assert authority["authority_status"] == "SUSPENDED", (
        f"hop one must suspend the ACTIVE authority, got "
        f"{authority['authority_status']}"
    )
    assert authority["suspension_reason"] == "DESIGNATION_GAP", authority
    assert authority["suspended_at"] == T_DEFECT_STAMP, authority
    assert authority["revoked_at"] is None, authority

    proceedings, meta = _proceedings(api, env.authority_id)
    assert meta["total_count"] == 0, (
        f"a designation gap is self-curable and opens no RevocationProceeding, "
        f"got {proceedings}"
    )

    rows = validate_paginated(
        api.list_designations(REGISTRY_ADMIN, authority_id=env.authority_id, limit=MAX_LIMIT)
    )[0]
    assert_created_at_ascending(rows)
    assert sorted(r["state_code"] for r in rows if r["status"] == "ACTIVE") == ["NM", "OK"], rows


def test_designation_revoke_cascade_embargoes_the_in_transit_shipment(api):
    """PRD S2.10: "Because each of those contracts became `SUSPENDED_BY_AUTHORITY`, hop
    three visits every `Shipment` whose `contract_id` names that contract and whose
    `status` is either `TENDERED` or `IN_TRANSIT`: each records its current status into
    `pre_embargo_status`, becomes `EMBARGOED`, and has `embargoed_at` set to the current
    logical time; the contract's `embargoed_shipment_count` is then set to the number of
    shipments this hop moved for it."
    PRD S2.10: "each becomes `SUSPENDED_BY_AUTHORITY`, its `suspended_at` is set to the
    current logical time, its `resumed_at` is reset to null"
    PRD S3.9: "A new shipment opens with `status` `TENDERED`, `pre_embargo_status`
    `NONE`, `embargo_days_accrued` zero, and `embargoed_at`, `embargo_released_at`,
    `delivered_at` and `diverted_at` all null."

    Design: Difficulty/transitive_cascade/designation_revoke_cascades_three_hops_without_a_proceeding
    """
    env = _in_transit_chain(api)
    assert env.shipment["status"] == "IN_TRANSIT", env.shipment
    assert env.shipment["pre_embargo_status"] == "NONE", env.shipment

    validate_success(
        api.revoke_designation(_designation_for_state(env, "TX")["id"], env.carrier_headers)
    )

    contract = validate_success(api.get_contract(env.contract_id, REGISTRY_ADMIN))
    assert_customer_contract(contract)
    assert contract["status"] == "SUSPENDED_BY_AUTHORITY", (
        f"hop two must suspend the ACTIVE contract, got {contract['status']}"
    )
    assert contract["suspended_at"] == T_DEFECT_STAMP, contract
    assert contract["resumed_at"] is None, contract
    assert contract["terminated_at"] is None, contract
    assert contract["embargoed_shipment_count"] == 1, (
        f"hop three moved exactly one shipment for this contract, got "
        f"{contract['embargoed_shipment_count']}"
    )

    shipment = validate_success(api.get_shipment(env.shipment_id, REGISTRY_ADMIN))
    assert_shipment(shipment)
    assert shipment["status"] == "EMBARGOED", shipment
    assert shipment["pre_embargo_status"] == "IN_TRANSIT", (
        f"the shipment's status at the moment of the embargo was IN_TRANSIT and must be "
        f"recorded into pre_embargo_status, got {shipment['pre_embargo_status']}"
    )
    assert shipment["embargoed_at"] == T_DEFECT_STAMP, shipment
    assert shipment["embargo_released_at"] is None, shipment
    assert shipment["embargo_days_accrued"] == 0, shipment
    assert shipment["delivered_at"] is None, shipment
    assert shipment["diverted_at"] is None, shipment


def test_designation_revoke_estimates_the_liability_and_moves_the_counters(api):
    """PRD S3.9: "Both variants start from the same daily figure: the contract's
    `monthly_committed_revenue_cents` divided by 30, kept as an exact rational value
    rather than rounded at this stage."
    PRD S3.9: "Take the interval from the contract's `suspended_at` to its
    `term_end_at`, convert it to days and round **up** to the next whole day; multiply
    the daily figure by that day count and then by the 15 percent penalty rate; round
    the product half-up to whole cents."
    PRD S3.9: "Neither the shipment penalty nor the goodwill waiver described below
    participates in this variant, and `disruption_liability_variant` is set to
    `SUSPENSION_ESTIMATE`."
    PRD S2.10: "Finally the authority's counters move: `active_contract_count` decreases
    by the number of contracts hop two moved and `suspended_contract_count` increases by
    that same number, and the owning carrier's `active_authority_count` decreases by
    one."

    Design: Difficulty/transitive_cascade/designation_revoke_cascades_three_hops_without_a_proceeding
    """
    env = _in_transit_chain(api)
    assert env.authority["active_contract_count"] == 1, env.authority
    assert env.authority["suspended_contract_count"] == 0, env.authority
    before = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert before["active_authority_count"] == 1, before

    validate_success(
        api.revoke_designation(_designation_for_state(env, "TX")["id"], env.carrier_headers)
    )

    contract = validate_success(api.get_contract(env.contract_id, REGISTRY_ADMIN))
    assert contract["disruption_liability_variant"] == "SUSPENSION_ESTIMATE", contract
    assert contract["disruption_liability_cents"] == SUSPENSION_ESTIMATE_CENTS, (
        f"the whole remaining term 2026-09-10 to {TERM_END_AT} is "
        f"{REMAINING_TERM_DAYS} days, so the estimate is "
        f"{SUSPENSION_ESTIMATE_CENTS} cents, got {contract['disruption_liability_cents']}"
    )
    assert SUSPENSION_ESTIMATE_CENTS == expected_suspension_estimate(
        MONTHLY_REVENUE_CENTS, REMAINING_TERM_DAYS
    )

    authority = read_authority(api, env.authority_id)
    assert authority["active_contract_count"] == 0, (
        f"one contract left the active population, got "
        f"{authority['active_contract_count']}"
    )
    assert authority["suspended_contract_count"] == 1, authority
    assert_contract_population_identity(api, env.authority_id, REGISTRY_ADMIN)

    after = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert after["active_authority_count"] == 0, (
        f"the carrier's active_authority_count decreases by one at suspension, got "
        f"{after['active_authority_count']}"
    )


# ---------------------------------------------------------------------------
# Cancelling the only required filing: four hops and a proceeding
# ---------------------------------------------------------------------------
def test_filing_cancel_lapses_coverage_and_opens_a_thirty_day_cure_proceeding(api):
    """PRD S3.5: "The filing then moves `ACTIVE → CANCELLED` with
    `cancellation_effective_at` set to the submitted instant."
    PRD S3.5: "If, after the cancellation, at least one required slot no longer holds an
    `ACTIVE` filing whose interval contains the current logical time, `insurance_status`
    moves `FILED → LAPSED`."
    PRD S3.5: "Because it lapsed, a `RevocationProceeding` is opened against the
    authority with `reason` `INSURANCE_LAPSE`, `status` `NOTICE_ISSUED`,
    `notice_issued_at` at the current logical time and `cure_deadline_at` exactly 30 days
    later."
    PRD S2.9: "A `RevocationProceeding` is created as a cascade side effect and is
    discoverable only through `GET /operating-authorities/{id}/revocation-proceedings`."

    Design: Difficulty/transitive_cascade/filing_cancel_cascades_four_hops_and_mints_a_proceeding
    """
    env = _tendered_chain(api)
    assert env.authority["insurance_status"] == "FILED", env.authority
    assert env.authority["required_bipd_limit_cents"] == BIPD_LIMIT_CENTS, env.authority
    assert _proceedings(api, env.authority_id)[1]["total_count"] == 0, (
        "no proceeding may exist before the cancel"
    )

    cancelled = cancel_filing(api, env.insurer_id, env.filing_id, T_DEFECT_AT)
    assert_insurance_filing(cancelled)
    assert cancelled["status"] == "CANCELLED", cancelled
    assert cancelled["cancellation_effective_at"] == T_DEFECT_STAMP, (
        f"cancellation_effective_at is the submitted instant {T_DEFECT_STAMP}, got "
        f"{cancelled['cancellation_effective_at']}"
    )

    authority = read_authority(api, env.authority_id)
    assert authority["insurance_status"] == "LAPSED", (
        f"the only required slot no longer holds an ACTIVE filing, so insurance_status "
        f"must read LAPSED, got {authority['insurance_status']}"
    )

    proceedings, meta = _proceedings(api, env.authority_id)
    assert meta["total_count"] == 1, (
        f"the lapse opens exactly one RevocationProceeding, got {proceedings}"
    )
    proceeding = proceedings[0]
    assert_revocation_proceeding(proceeding)
    assert proceeding["authority_id"] == env.authority_id, proceeding
    assert proceeding["reason"] == "INSURANCE_LAPSE", proceeding
    assert proceeding["status"] == "NOTICE_ISSUED", proceeding
    assert proceeding["notice_issued_at"] == T_DEFECT_STAMP, proceeding
    assert proceeding["cure_deadline_at"] == T_CURE_DEADLINE_STAMP, (
        f"the cure deadline is exactly 30 days after {T_DEFECT_STAMP}, which is "
        f"{T_CURE_DEADLINE_STAMP}, got {proceeding['cure_deadline_at']}"
    )


def test_filing_cancel_suspends_the_authority_and_embargoes_the_tendered_shipment(api):
    """PRD S3.5: "And because that proceeding was opened, if the authority's
    `authority_status` was `ACTIVE`, the suspension cascade of §2.10 runs with
    `suspension_reason` `INSURANCE_LAPSE` — suspending the authority, suspending its
    active contracts with their liability estimated, and embargoing those contracts'
    tendered and in-transit shipments."
    PRD S2.10: "Hop one sets the authority's `authority_status` to `SUSPENDED`, sets
    `suspended_at` to the current logical time, and sets `suspension_reason` to the
    defect that caused it"
    PRD S2.10: "each records its current status into `pre_embargo_status`, becomes
    `EMBARGOED`, and has `embargoed_at` set to the current logical time"

    Design: Difficulty/transitive_cascade/filing_cancel_cascades_four_hops_and_mints_a_proceeding
    """
    env = _tendered_chain(api)
    assert env.shipment["status"] == "TENDERED", env.shipment

    cancel_filing(api, env.insurer_id, env.filing_id, T_DEFECT_AT)

    authority = read_authority(api, env.authority_id)
    assert_operating_authority(authority)
    assert authority["authority_status"] == "SUSPENDED", (
        f"the ACTIVE authority must be suspended by the lapse cascade, got "
        f"{authority['authority_status']}"
    )
    assert authority["suspension_reason"] == "INSURANCE_LAPSE", authority
    assert authority["suspended_at"] == T_DEFECT_STAMP, authority
    assert authority["revoked_at"] is None, authority
    assert authority["rescinded_at"] is None, authority

    contract = validate_success(api.get_contract(env.contract_id, REGISTRY_ADMIN))
    assert contract["status"] == "SUSPENDED_BY_AUTHORITY", contract
    assert contract["suspended_at"] == T_DEFECT_STAMP, contract
    assert contract["disruption_liability_variant"] == "SUSPENSION_ESTIMATE", contract
    assert contract["disruption_liability_cents"] == SUSPENSION_ESTIMATE_CENTS, (
        f"the estimate projects {REMAINING_TERM_DAYS} remaining days of the term, "
        f"so it is {SUSPENSION_ESTIMATE_CENTS} cents, got "
        f"{contract['disruption_liability_cents']}"
    )
    assert contract["embargoed_shipment_count"] == 1, contract

    shipment = validate_success(api.get_shipment(env.shipment_id, REGISTRY_ADMIN))
    assert_shipment(shipment)
    assert shipment["status"] == "EMBARGOED", shipment
    assert shipment["pre_embargo_status"] == "TENDERED", (
        f"this shipment never departed, so its pre_embargo_status must record "
        f"TENDERED, got {shipment['pre_embargo_status']}"
    )
    assert shipment["embargoed_at"] == T_DEFECT_STAMP, shipment
    assert shipment["embargo_released_at"] is None, shipment
    assert shipment["diverted_at"] is None, shipment


def test_filing_cancel_touches_five_kinds_of_record_in_one_call(api):
    """PRD S3.5: "One cancel therefore touches five kinds of record: the filing, the
    authority's coverage dimension, a new proceeding, the authority's own status, and
    every contract and shipment beneath it."
    PRD S2.10: "Finally the authority's counters move: `active_contract_count` decreases
    by the number of contracts hop two moved and `suspended_contract_count` increases by
    that same number, and the owning carrier's `active_authority_count` decreases by
    one."

    Design: Difficulty/transitive_cascade/filing_cancel_cascades_four_hops_and_mints_a_proceeding
    """
    env = _tendered_chain(api)
    assert env.authority["active_contract_count"] == 1, env.authority
    assert env.authority["suspended_contract_count"] == 0, env.authority

    cancel_filing(api, env.insurer_id, env.filing_id, T_DEFECT_AT)

    filing = validate_success(api.get_filing(env.filing_id, REGISTRY_ADMIN))
    authority = read_authority(api, env.authority_id)
    proceedings, proceeding_meta = _proceedings(api, env.authority_id)
    contracts, contract_meta = validate_paginated(
        api.list_authority_contracts(env.authority_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    shipments, shipment_meta = validate_paginated(
        api.list_shipments(REGISTRY_ADMIN, contract_id=env.contract_id, limit=MAX_LIMIT)
    )

    assert filing["status"] == "CANCELLED", filing
    assert authority["insurance_status"] == "LAPSED", authority
    assert proceeding_meta["total_count"] == 1, proceedings
    assert authority["authority_status"] == "SUSPENDED", authority
    assert contract_meta["total_count"] == 1, contracts
    assert contracts[0]["status"] == "SUSPENDED_BY_AUTHORITY", contracts[0]
    assert shipment_meta["total_count"] == 1, shipments
    assert shipments[0]["status"] == "EMBARGOED", shipments[0]
    assert_created_at_ascending(contracts)
    assert_created_at_ascending(shipments)

    assert authority["active_contract_count"] == 0, authority
    assert authority["suspended_contract_count"] == 1, authority
    assert_contract_population_identity(api, env.authority_id, REGISTRY_ADMIN)
    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["active_authority_count"] == 0, (
        f"the suspension decrements the carrier's active_authority_count to 0, got "
        f"{carrier['active_authority_count']}"
    )
