"""Error-catalogue conformance: each refusal names the exact PRD error id.

Every test here drives one specific rejection from PRD S5 to its trigger
condition, asserts the exact ``error_id`` (and, through the framework's
status map, the exact HTTP status), and then proves the refusal wrote
nothing: the target record still holds the state it held beforehand.
"""

from test_helpers import (
    ApiErrorId,
    BIPD_PROPERTY_BASE_CENTS,
    BROKER_BOND_CENTS,
    COMPLIANCE_OFFICER,
    FEE_NEW_FOR_HIRE_THREE_STATES_CENTS,
    MAX_LIMIT,
    NON_EXISTENT_UUID,
    REGISTRY_ADMIN,
    UNDESIGNATED_STATE,
    assert_risk_score,
    assert_fee_ledger_identities,
    audit_result_payload,
    authority_for_application,
    authority_version,
    biennial_update_payload,
    contract_payload,
    create_draft_application,
    designate_states,
    filing_payload,
    get_success_data,
    list_designations,
    make_insurer_headers,
    pay_fee,
    read_authority,
    review_application,
    run_sweep,
    set_clock,
    settle_fee_balance,
    setup_active_authority,
    setup_active_authority_with_contract,
    setup_pending_authority_with_coverage,
    setup_published_authority,
    setup_registry,
    shipment_payload,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _filings_on(api, authority_id, filing_type=None):
    """Every insurance filing on one authority, read in ``created_at`` order.

    PRD 2.3 caps a page at 100 records and orders every listing by
    ``created_at`` ascending; each test below builds a world far smaller than
    one page, so a single unfiltered read is a complete census.
    """
    rows, _ = validate_paginated(api.list_filings(REGISTRY_ADMIN, limit=MAX_LIMIT))
    return [
        row
        for row in rows
        if row["authority_id"] == authority_id
        and (filing_type is None or row["filing_type"] == filing_type)
    ]


def _shipments_under(api, contract_id):
    """Every shipment tendered under one contract, in ``created_at`` order."""
    rows, _ = validate_paginated(api.list_shipments(REGISTRY_ADMIN, limit=MAX_LIMIT))
    return [row for row in rows if row["contract_id"] == contract_id]


def test_unknown_path_identifiers_return_the_entity_specific_not_found_error(api):
    """Four unknown path ids each raise their own 404, not a generic one.

    PRD 2.8: "A missing `AuthorityApplication` on `GET /authority-applications/{id}`,
    `POST /authority-applications/{id}/submit` or
    `POST /authority-applications/{id}/vetting-review` yields
    `ERR_APPLICATION_NOT_FOUND`."

    PRD 2.8: "A missing `InsuranceFiling` on `GET /insurance-filings/{id}` or
    `POST /insurance-filings/{id}/cancel` yields `ERR_FILING_NOT_FOUND`."

    PRD 2.8: "the contract on `GET /customer-contracts/{id}` and
    `POST /customer-contracts/{id}/shipments`, and the shipment on
    `GET /shipments/{id}`, `POST /shipments/{id}/depart` and
    `POST /shipments/{id}/deliver` — yields `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/errors/unknown_path_identifiers_return_the_entity_specific_not_found_error
    """
    unknown = NON_EXISTENT_UUID

    application_error = validate_error(
        api.get_application(unknown, COMPLIANCE_OFFICER),
        ApiErrorId.APPLICATION_NOT_FOUND,
    )
    filing_error = validate_error(
        api.get_filing(unknown, COMPLIANCE_OFFICER), ApiErrorId.FILING_NOT_FOUND
    )
    contract_error = validate_error(
        api.get_contract(unknown, COMPLIANCE_OFFICER), ApiErrorId.REFERENCE_NOT_FOUND
    )
    shipment_error = validate_error(
        api.get_shipment(unknown, COMPLIANCE_OFFICER), ApiErrorId.REFERENCE_NOT_FOUND
    )

    # The application and the filing get their own ids; the contract and the
    # shipment both fall through to the generic reference error.
    assert application_error["error_id"] != filing_error["error_id"]
    assert contract_error["error_id"] == shipment_error["error_id"]
    for error in (application_error, filing_error, contract_error, shipment_error):
        assert isinstance(error.get("message"), str) and error["message"].strip()


def test_activate_with_no_insurance_filing_at_all_is_rejected(api):
    """A property authority with zero filings cannot activate.

    PRD 3.6: "Whenever `required_bipd_limit_cents` is greater than zero, an
    `ACTIVE` `BIPD` filing must exist on this authority whose coverage interval
    contains the current logical time, and whenever `required_cargo_limit_cents`
    is greater than zero the same must be true of a `CARGO` filing; a missing one
    is `ERR_INSURANCE_NOT_ON_FILE`."

    PRD 3.4: "`designation_coverage_complete` is true exactly when no required
    jurisdiction is left uncovered"

    Design: Corner/errors/activate_with_no_insurance_filing_at_all_is_rejected
    """
    env = setup_published_authority(api)
    designate_states(
        api,
        env.carrier_id,
        env.authority_id,
        env.agent_id,
        state_codes=list(env.authority["required_jurisdictions"]),
        effective_from=env.publish_at,
    )
    settle_fee_balance(api, env.carrier_id)

    before = read_authority(api, env.authority_id)
    assert before["designation_coverage_complete"] is True
    assert before["required_bipd_limit_cents"] == BIPD_PROPERTY_BASE_CENTS
    assert before["required_bipd_limit_cents"] == 75000000
    assert before["insurance_status"] == "NOT_FILED"

    set_clock(api, before["activation_eligible_at"])
    validate_error(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER),
        ApiErrorId.INSURANCE_NOT_ON_FILE,
    )

    after = read_authority(api, env.authority_id)
    assert after["authority_status"] == "PENDING"
    assert after["insurance_status"] == "NOT_FILED"
    assert after["activated_at"] is None
    assert after["version"] == before["version"]

    assert _filings_on(api, env.authority_id) == []


def test_filing_one_cent_below_the_required_minimum_is_rejected(api):
    """One cent short is refused; the exact minimum is booked and meets it.

    PRD 3.5: "`meets_required_minimum` is set from the comparison of
    `coverage_limit_cents` against the authority's required limit for this
    `filing_type` — `required_bipd_limit_cents` for a `BIPD` filing,
    `required_cargo_limit_cents` for a `CARGO` filing, and
    `required_bond_limit_cents` for a `SURETY_BOND` or `TRUST_FUND` filing — and a
    filing that would be booked below that minimum is rejected outright with
    `ERR_INSURANCE_BELOW_MINIMUM`."

    PRD 3.5: "`NOT_FILED → FILED` when the authority has exactly one required slot
    and the new filing satisfies it."

    Design: Corner/errors/filing_one_cent_below_the_required_minimum_is_rejected
    """
    env = setup_published_authority(api)
    minimum = env.authority["required_bipd_limit_cents"]
    assert minimum == 75000000
    guarded_version = authority_version(api, env.authority_id)

    validate_error(
        api.create_filing(
            filing_payload(
                env.authority_id,
                env.insurer_id,
                minimum - 1,
                guarded_version,
                filing_type="BIPD",
                policy_number="BIPD-SHORT",
                effective_at=env.publish_at,
            ),
            make_insurer_headers(env.insurer_id),
        ),
        ApiErrorId.INSURANCE_BELOW_MINIMUM,
    )

    refused = read_authority(api, env.authority_id)
    assert refused["insurance_status"] == "NOT_FILED"
    # The refusal wrote nothing, so the version the client already holds is
    # still current and can be reused verbatim on the corrected attempt.
    assert refused["version"] == guarded_version

    accepted = validate_success(
        api.create_filing(
            filing_payload(
                env.authority_id,
                env.insurer_id,
                minimum,
                guarded_version,
                filing_type="BIPD",
                policy_number="BIPD-EXACT",
                effective_at=env.publish_at,
            ),
            make_insurer_headers(env.insurer_id),
        ),
        201,
    )
    assert accepted["coverage_limit_cents"] == 75000000
    assert accepted["meets_required_minimum"] is True
    assert accepted["status"] == "ACTIVE"

    after = read_authority(api, env.authority_id)
    assert after["insurance_status"] == "FILED"
    assert after["version"] == guarded_version + 1

    booked = _filings_on(api, env.authority_id)
    assert len(booked) == 1
    assert booked[0]["policy_number"] == "BIPD-EXACT"


def test_broker_activation_needs_a_bond_filing_that_bipd_alone_cannot_satisfy(api):
    """A property broker owes a bond, not liability cover, before it activates.

    PRD 3.2: "For a `PROPERTY_BROKER` application, the base is zero — a broker
    arranges transportation rather than performing it, so no liability limit is
    imposed on it."

    PRD 3.2: "`required_bond_limit_cents` is $75,000 for a `PROPERTY_BROKER` or
    `FREIGHT_FORWARDER` application and zero for every other class."

    PRD 3.6: "And whenever `required_bond_limit_cents` is greater than zero —
    which is the broker and freight-forwarder case — an `ACTIVE` filing of type
    either `SURETY_BOND` or `TRUST_FUND` must exist at or above
    `required_bond_limit_cents`, failing which the activation is refused with
    `ERR_BOND_FILING_REQUIRED`."

    Design: Corner/errors/broker_activation_needs_a_bond_filing_that_bipd_alone_cannot_satisfy
    """
    env = setup_published_authority(
        api, application_kwargs={"transportation_type": "PROPERTY_BROKER"}
    )
    assert env.authority["required_bipd_limit_cents"] == 0
    assert env.authority["required_cargo_limit_cents"] == 0
    assert env.authority["required_bond_limit_cents"] == BROKER_BOND_CENTS
    assert env.authority["required_bond_limit_cents"] == 7500000

    designate_states(
        api,
        env.carrier_id,
        env.authority_id,
        env.agent_id,
        state_codes=list(env.authority["required_jurisdictions"]),
        effective_from=env.publish_at,
    )
    settle_fee_balance(api, env.carrier_id)
    eligible_at = read_authority(api, env.authority_id)["activation_eligible_at"]
    set_clock(api, eligible_at)

    # No filing of any kind exists: because both liability minimums are zero the
    # request falls straight through to the bond requirement.
    validate_error(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER),
        ApiErrorId.BOND_FILING_REQUIRED,
    )
    refused = read_authority(api, env.authority_id)
    assert refused["authority_status"] == "PENDING"
    assert refused["insurance_status"] == "NOT_FILED"

    bond_version = authority_version(api, env.authority_id)
    bond = validate_success(
        api.create_filing(
            filing_payload(
                env.authority_id,
                env.insurer_id,
                7500000,
                bond_version,
                filing_type="SURETY_BOND",
                policy_number="BOND-1",
                effective_at=eligible_at,
            ),
            make_insurer_headers(env.insurer_id),
        ),
        201,
    )
    assert bond["filing_type"] == "SURETY_BOND"
    assert bond["meets_required_minimum"] is True
    assert read_authority(api, env.authority_id)["insurance_status"] == "FILED"

    activated = validate_success(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER)
    )
    assert activated["authority_status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-26T00:00:00.000Z"

    assert _filings_on(api, env.authority_id, filing_type="BIPD") == []
    assert len(_filings_on(api, env.authority_id, filing_type="SURETY_BOND")) == 1


def test_commodity_class_and_transportation_type_must_agree_in_both_directions(api):
    """A passenger load needs a passenger authority, and vice versa.

    PRD 3.2: "a contract covering the `PASSENGERS` commodity class may only be
    written against an authority whose class is `PASSENGER` and whose recorded
    seating capacity is at least 1 — and, symmetrically, a `PASSENGER` authority
    may not carry any freight commodity class. Either mismatch is rejected with
    `ERR_PASSENGER_AUTHORITY_REQUIRED`."

    PRD 3.2: "For a `PASSENGER` application, the base is $1,500,000 when
    `passenger_seating_capacity` is at most 15 seats"

    Design: Corner/errors/commodity_class_and_transportation_type_must_agree_in_both_directions
    """
    # One carrier, two authorities of different classes.  The freight authority
    # is activated first so the carrier reads REGISTERED, which leaves the
    # commodity mismatch as the only defect either contract create carries.
    env = setup_active_authority(api)
    freight_authority = env.authority
    assert freight_authority["transportation_type"] == "FOR_HIRE_PROPERTY"
    assert freight_authority["passenger_seating_capacity"] is None
    assert env.carrier["unified_registration_status"] == "REGISTERED"

    passenger_application = create_draft_application(
        api,
        env.carrier_id,
        transportation_type="PASSENGER",
        passenger_seating_capacity=15,
    )
    submit_application(api, env.carrier_id, passenger_application["id"])
    review_application(api, passenger_application["id"], disposition="PUBLISH")
    passenger_authority = authority_for_application(api, passenger_application["id"])
    assert passenger_authority["transportation_type"] == "PASSENGER"
    assert passenger_authority["passenger_seating_capacity"] == 15
    assert passenger_authority["required_bipd_limit_cents"] == 150000000

    freight_version = authority_version(api, freight_authority["id"])
    passenger_version = authority_version(api, passenger_authority["id"])

    validate_error(
        api.create_contract(
            freight_authority["id"],
            contract_payload(
                freight_version,
                shipper_name="Rio Grande Tours",
                commodity_class="PASSENGERS",
            ),
            env.carrier_headers,
        ),
        ApiErrorId.PASSENGER_AUTHORITY_REQUIRED,
    )
    validate_error(
        api.create_contract(
            passenger_authority["id"],
            contract_payload(
                passenger_version,
                shipper_name="Bexar Wholesale Grocers",
                commodity_class="GENERAL_FREIGHT",
            ),
            env.carrier_headers,
        ),
        ApiErrorId.PASSENGER_AUTHORITY_REQUIRED,
    )

    for authority_id, expected_version in (
        (freight_authority["id"], freight_version),
        (passenger_authority["id"], passenger_version),
    ):
        after = read_authority(api, authority_id)
        assert after["active_contract_count"] == 0
        assert after["version"] == expected_version
        _, meta = validate_paginated(
            api.list_authority_contracts(authority_id, REGISTRY_ADMIN)
        )
        assert meta["total_count"] == 0


def test_recording_an_audit_result_twice_is_rejected(api):
    """The second record-result call finds the audit already PASSED.

    PRD 3.7: "the audit must still be `SCHEDULED` — a `PASSED`, `FAILED` or
    `MISSED` audit refuses a result with `ERR_AUDIT_INVALID_STATE`"

    PRD 3.7: "the audit `FAILED` when `audit_score` is at least 40.00 **or** when
    `acute_violation_count` is 1 or more, and `PASSED` otherwise."

    PRD 3.7: "On `SCHEDULED → PASSED`: the carrier's `entrant_status` becomes
    `PERMANENT`, and every `OperatingAuthority` of that carrier whose
    `new_entrant_audit_status` is `PENDING`, walked in `created_at` ascending
    order, moves to `PASSED`."

    Design: Corner/errors/recording_an_audit_result_twice_is_rejected
    """
    env = setup_active_authority(api)
    assert env.audit is not None
    assert env.audit["status"] == "SCHEDULED"
    assert env.audit["audit_window_opens_at"] == "2026-08-26T00:00:00.000Z"
    assert env.audit["audit_deadline_at"] == "2028-02-26T00:00:00.000Z"

    set_clock(api, "2026-10-01T00:00:00Z")
    payload = audit_result_payload(
        audited_oos_rate_pct=4.0,
        audited_driver_violation_count=2,
        audited_vehicle_defect_count=3,
        acute_violation_count=0,
    )
    recorded = validate_success(
        api.record_audit_result(env.audit_id, payload, COMPLIANCE_OFFICER)
    )
    assert recorded["status"] == "PASSED"
    assert_risk_score(recorded["audit_score"], 9.60)
    assert recorded["result_recorded_at"] == "2026-10-01T00:00:00.000Z"

    # The identical replay is refused because the audit is no longer SCHEDULED.
    validate_error(
        api.record_audit_result(env.audit_id, payload, COMPLIANCE_OFFICER),
        ApiErrorId.AUDIT_INVALID_STATE,
    )

    carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["entrant_status"] == "PERMANENT"
    assert carrier["compliance_risk_variant"] == "AUDITED"
    assert_risk_score(carrier["compliance_risk_score"], 9.60)
    assert read_authority(api, env.authority_id)["new_entrant_audit_status"] == "PASSED"

    rows, meta = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "PASSED"
    assert_risk_score(rows[0]["audit_score"], 9.60)
    assert rows[0]["result_recorded_at"] == "2026-10-01T00:00:00.000Z"


def test_shipment_tender_is_rejected_for_an_undesignated_state_and_for_a_suspended_contract(
    api,
):
    """Two different tender refusals: no agent at one end, then a frozen contract.

    PRD 3.9: "both `origin_state` and `destination_state` must be covered by an
    `ACTIVE` `ProcessAgentDesignation` on the owning authority whose interval
    contains the current logical time, failing which the tender is rejected with
    `ERR_PROCESS_AGENT_NOT_DESIGNATED`."

    PRD 3.9: "The contract itself must be `ACTIVE`: a contract that is
    `SUSPENDED_BY_AUTHORITY` or `TERMINATED` refuses new shipments with
    `ERR_CONTRACT_NOT_ACTIVE`."

    PRD 3.4: "if the authority was `ACTIVE` the full suspension cascade of §2.10
    runs with `suspension_reason` set to `DESIGNATION_GAP`"

    PRD 3.4: "No revocation proceeding is opened for a designation gap, because the
    defect is self-curable: the carrier simply files a replacement designation."

    Design: Corner/errors/shipment_tender_is_rejected_for_an_undesignated_state_and_for_a_suspended_contract
    """
    env = setup_active_authority_with_contract(api)
    assert env.authority["designated_state_count"] == 3
    assert env.contract["status"] == "ACTIVE"

    # WY was never designated, so the destination end has no agent standing.
    validate_error(
        api.create_shipment(
            env.contract_id,
            shipment_payload(origin_state="TX", destination_state=UNDESIGNATED_STATE),
            env.carrier_headers,
        ),
        ApiErrorId.PROCESS_AGENT_NOT_DESIGNATED,
    )

    texas = [
        row
        for row in list_designations(api, env.authority_id)
        if row["state_code"] == "TX"
    ]
    assert len(texas) == 1
    revoked = validate_success(
        api.revoke_designation(texas[0]["id"], env.carrier_headers)
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] == "2026-08-26T00:00:00.000Z"

    gapped = read_authority(api, env.authority_id)
    assert gapped["authority_status"] == "SUSPENDED"
    assert gapped["suspension_reason"] == "DESIGNATION_GAP"
    assert gapped["designated_state_count"] == 2
    assert gapped["designation_coverage_complete"] is False

    suspended_contract = get_success_data(
        api.get_contract(env.contract_id, env.carrier_headers)
    )
    assert suspended_contract["status"] == "SUSPENDED_BY_AUTHORITY"
    assert suspended_contract["suspended_at"] == "2026-08-26T00:00:00.000Z"

    # OK and NM are both still designated, so the only defect left is the
    # contract's own status.
    validate_error(
        api.create_shipment(
            env.contract_id,
            shipment_payload(origin_state="OK", destination_state="NM"),
            env.carrier_headers,
        ),
        ApiErrorId.CONTRACT_NOT_ACTIVE,
    )

    assert _shipments_under(api, env.contract_id) == []
    _, proceedings_meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, REGISTRY_ADMIN)
    )
    assert proceedings_meta["total_count"] == 0


def test_a_biennially_delinquent_carrier_cannot_submit_an_application(api):
    """The sweep flags the carrier, the submit is refused, the update clears it.

    PRD 3.8: "Every `Carrier` whose `biennial_update_due_at` is strictly earlier
    than the current logical time and whose `biennial_delinquent` is still false has
    `biennial_delinquent` set to true, adding one to
    `carriers_flagged_delinquent_count` per carrier."

    PRD 3.3: "the acting user is the owning carrier, and that carrier is not flagged
    `biennial_delinquent` — a delinquent carrier is turned away with
    `ERR_BIENNIAL_UPDATE_DELINQUENT`."

    PRD 3.1: "it records `last_biennial_update_at` as the current logical time and
    pushes `biennial_update_due_at` out to the current logical time plus 730 days;
    and it clears `biennial_delinquent` back to false."

    Design: Corner/errors/a_biennially_delinquent_carrier_cannot_submit_an_application
    """
    env = setup_registry(api, with_agent=False, with_insurer=False)
    assert env.carrier["biennial_delinquent"] is False

    set_clock(api, "2028-08-01T00:00:00Z")
    sweep = run_sweep(api)
    assert sweep["carriers_flagged_delinquent_count"] == 1
    assert sweep["audits_missed_count"] == 0
    flagged = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert flagged["biennial_delinquent"] is True

    # Opening a draft is not gated on registration currency; submitting it is.
    draft = create_draft_application(api, env.carrier_id)
    assert draft["status"] == "DRAFT"
    assert draft["submission_count"] == 0

    validate_error(
        api.submit_application(draft["id"], env.carrier_headers),
        ApiErrorId.BIENNIAL_UPDATE_DELINQUENT,
    )
    refused = get_success_data(api.get_application(draft["id"], REGISTRY_ADMIN))
    assert refused["status"] == "DRAFT"
    assert refused["submission_count"] == 0
    # No submission means no fee was ever assessed.
    assert get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))[
        "fee_balance_cents"
    ] == 0

    cured = validate_success(
        api.file_biennial_update(
            env.carrier_id, biennial_update_payload(), env.carrier_headers
        )
    )
    assert cured["biennial_delinquent"] is False
    assert cured["last_biennial_update_at"] == "2028-08-01T00:00:00.000Z"
    assert cured["biennial_update_due_at"] == "2030-08-01T00:00:00.000Z"

    submitted = validate_success(
        api.submit_application(draft["id"], env.carrier_headers)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_count"] == 1


def test_activate_with_an_outstanding_filing_fee_is_rejected(api):
    """Money is the last gate: an unpaid docket fee blocks an otherwise ready authority.

    PRD 3.6: "Finally, money is checked last: the carrier's `fee_balance_cents` must
    be zero or negative, meaning nothing is outstanding. A strictly positive balance
    is refused with `ERR_FILING_FEE_OUTSTANDING` (HTTP 402) — the only 402 in the
    system."

    PRD 3.3: "a ledger entry with `entry_type` `FILING_FEE_DEBIT` and an
    `amount_cents` equal to positive `filing_fee_cents` is appended with its
    `docket_ref` naming this application, and both `fees_assessed_total_cents` and
    `fee_balance_cents` on the owning carrier increase by that amount."

    PRD 3.1: "Recording it appends a ledger entry whose `entry_type` is
    `FEE_PAYMENT_CREDIT` and whose `amount_cents` is the negation of the submitted
    amount, then increases `fees_paid_total_cents` by the submitted amount and
    decreases `fee_balance_cents` by the same amount."

    Design: Corner/errors/activate_with_an_outstanding_filing_fee_is_rejected
    """
    env = setup_pending_authority_with_coverage(api, pay_fee_in_full=False)
    assert env.authority["designation_coverage_complete"] is True
    assert env.authority["insurance_status"] == "FILED"

    unpaid = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert unpaid["fee_balance_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES_CENTS
    assert unpaid["fee_balance_cents"] == 64791
    assert unpaid["fees_assessed_total_cents"] == 64791
    assert unpaid["fees_paid_total_cents"] == 0

    eligible_at = env.authority["activation_eligible_at"]
    set_clock(api, eligible_at)
    validate_error(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER),
        ApiErrorId.FILING_FEE_OUTSTANDING,
    )
    refused = read_authority(api, env.authority_id)
    assert refused["authority_status"] == "PENDING"
    assert refused["activated_at"] is None

    settled = pay_fee(api, env.carrier_id, 64791)
    assert settled["fee_balance_cents"] == 0
    assert settled["fees_paid_total_cents"] == 64791
    assert settled["fees_assessed_total_cents"] == 64791
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)

    activated = validate_success(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER)
    )
    assert activated["authority_status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-26T00:00:00.000Z"

    final_carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert final_carrier["fees_paid_total_cents"] == 64791
    assert final_carrier["fees_assessed_total_cents"] == 64791
    assert final_carrier["unified_registration_status"] == "REGISTERED"
