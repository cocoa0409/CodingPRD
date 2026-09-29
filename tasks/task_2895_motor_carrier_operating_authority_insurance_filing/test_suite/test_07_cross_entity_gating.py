"""Operations whose admissibility is decided by the state of a *sibling* row.

Writing a customer contract is legal or illegal depending on the parent
authority's status and on registration state the carrier only acquires at
activation (PRD S3.9).  Curing a revocation proceeding is legal or illegal
depending on an insurance filing that lives on the same authority (PRD S3.8).
Both operations therefore need state assembled across entities before the
request under test is even formulated.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER,
    REGISTRY_ADMIN,
    assert_customer_contract,
    assert_insurance_filing,
    assert_revocation_proceeding,
    contract_payload,
    cure_payload,
    cure_with_replacement_filing,
    get_success_data,
    read_authority,
    setup_active_authority,
    setup_pending_authority_with_coverage,
    setup_suspended_by_filing_cancel,
    validate_error,
    validate_paginated,
    validate_success,
)

NEW_SHIPPER = "Muleshoe Cotton Co-op"


# ---------------------------------------------------------------------------
# A contract's admissibility depends on its parent authority and carrier
# ---------------------------------------------------------------------------
def test_contract_creation_is_refused_while_the_parent_authority_is_suspended(api):
    """PRD S3.9: "The authority must be `PENDING` or `ACTIVE` — never
    `SUSPENDED`, `REVOKED` or `RESCINDED`, each of which yields
    `ERR_AUTHORITY_INVALID_STATE`."
    PRD S2.10: "Hop one sets the authority's `authority_status` to `SUSPENDED`,
    sets `suspended_at` to the current logical time, and sets
    `suspension_reason` to the defect that caused it — one of `INSURANCE_LAPSE`,
    `DESIGNATION_GAP`, `SAFETY_AUDIT_FAILURE` or `AUDIT_WINDOW_MISSED`."

    Design: Difficulty/cross_entity_state_dependency/contract_creation_is_gated_on_the_parent_authority_status
    """
    env = setup_suspended_by_filing_cancel(api)
    assert env.authority["authority_status"] == "SUSPENDED"
    assert env.authority["suspension_reason"] == "INSURANCE_LAPSE"

    response = api.create_contract(
        env.authority_id,
        contract_payload(env.authority["version"], shipper_name=NEW_SHIPPER),
        env.carrier_headers,
    )
    validate_error(response, ApiErrorId.AUTHORITY_INVALID_STATE)

    contracts, meta = validate_paginated(
        api.list_authority_contracts(env.authority_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 1, (
        "the refused request must not add a contract to the suspended authority"
    )
    assert [row for row in contracts if row["shipper_name"] == NEW_SHIPPER] == []
    after = read_authority(api, env.authority_id)
    assert after["active_contract_count"] == 0
    assert after["suspended_contract_count"] == 1


def test_contract_creation_is_refused_before_activation_registers_the_carrier(api):
    """PRD S3.9: "And the carrier must be current on unified registration:
    `biennial_delinquent` must be false **and**, uniquely to this operation,
    `unified_registration_status` must already read `REGISTERED`. Either
    shortfall is `ERR_BIENNIAL_UPDATE_DELINQUENT`."
    PRD S3.6: "On the owning carrier, `unified_registration_status` becomes
    `REGISTERED` and `active_authority_count` increases by one."

    Design: Difficulty/cross_entity_state_dependency/contract_creation_is_gated_on_the_parent_authority_status
    """
    env = setup_pending_authority_with_coverage(api)
    assert env.authority["authority_status"] == "PENDING"

    carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["unified_registration_status"] == "NOT_REGISTERED", (
        "registration is minted by activation, which has not happened yet"
    )
    assert carrier["biennial_delinquent"] is False

    response = api.create_contract(
        env.authority_id,
        contract_payload(env.authority["version"], shipper_name=NEW_SHIPPER),
        env.carrier_headers,
    )
    validate_error(response, ApiErrorId.BIENNIAL_UPDATE_DELINQUENT)

    contracts, meta = validate_paginated(
        api.list_authority_contracts(env.authority_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 0
    assert contracts == []


def test_contract_creation_is_admitted_once_the_authority_is_active(api):
    """PRD S3.9: "The authority must be `PENDING` or `ACTIVE` — never
    `SUSPENDED`, `REVOKED` or `RESCINDED`, each of which yields
    `ERR_AUTHORITY_INVALID_STATE`."
    PRD S3.9: "A brand-new contract opens with `status` `ACTIVE`,
    `embargoed_shipment_count` zero, `disruption_liability_cents` zero,
    `disruption_liability_variant` `NONE`, and `suspended_at`, `resumed_at` and
    `terminated_at` all null. The authority's `active_contract_count` increases
    by one, its `version` increases by one, and the contract-population
    identities of §2.10 are re-asserted."

    Design: Difficulty/cross_entity_state_dependency/contract_creation_is_gated_on_the_parent_authority_status
    """
    env = setup_active_authority(api)
    assert env.authority["authority_status"] == "ACTIVE"
    version_before = env.authority["version"]
    assert env.carrier["unified_registration_status"] == "REGISTERED"

    contract = validate_success(
        api.create_contract(
            env.authority_id,
            contract_payload(version_before, shipper_name=NEW_SHIPPER),
            env.carrier_headers,
        ),
        expected_status=201,
    )
    assert_customer_contract(contract)
    assert contract["status"] == "ACTIVE"
    assert contract["shipper_name"] == NEW_SHIPPER
    assert contract["authority_id"] == env.authority_id
    assert contract["embargoed_shipment_count"] == 0
    assert contract["disruption_liability_cents"] == 0
    assert contract["disruption_liability_variant"] == "NONE"
    assert contract["suspended_at"] is None
    assert contract["resumed_at"] is None
    assert contract["terminated_at"] is None

    after = read_authority(api, env.authority_id)
    assert after["active_contract_count"] == 1
    assert after["suspended_contract_count"] == 0
    assert after["version"] == version_before + 1


# ---------------------------------------------------------------------------
# A cure's admissibility depends on a filing that lives on the same authority
# ---------------------------------------------------------------------------
def test_cure_naming_a_policy_that_is_not_on_file_leaves_the_proceeding_open(api):
    """PRD S3.8: "Curing is a `ComplianceOfficer` action that points at a
    replacement policy already on file. The officer supplies
    `replacement_policy_number`, and four conditions must hold." ... "An
    `InsuranceFiling` must exist on the proceeding's authority whose
    `policy_number` equals the submitted value, whose `status` is `ACTIVE`, and
    whose coverage interval contains the current logical time."
    PRD S3.8: "A successful cure moves the proceeding `NOTICE_ISSUED → CURED`,
    stamps `cured_at` with the current logical time and records the submitted
    `replacement_policy_number`."

    Design: Difficulty/cross_entity_state_dependency/proceeding_cure_is_gated_on_a_replacement_filing_at_the_minimum
    """
    env = setup_suspended_by_filing_cancel(api)
    assert env.proceeding["status"] == "NOTICE_ISSUED"

    # No filing named BIPD-2 has been booked on this authority, so the third of
    # the four cure conditions cannot hold and the proceeding must not close.
    api.cure_proceeding(env.proceeding_id, cure_payload("BIPD-2"), COMPLIANCE_OFFICER)

    proceedings, meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 1
    proceeding = assert_revocation_proceeding(proceedings[0])
    assert proceeding["status"] == "NOTICE_ISSUED", (
        "a cure that points at no filing at all must not move the proceeding"
    )
    assert proceeding["cured_at"] is None
    assert proceeding["replacement_policy_number"] is None

    after = read_authority(api, env.authority_id)
    assert after["authority_status"] == "SUSPENDED", (
        "the restoration cascade must not run without a replacement filing"
    )
    assert after["insurance_status"] == "LAPSED"
    assert after["suspension_reason"] == "INSURANCE_LAPSE"


def test_cure_succeeds_once_a_replacement_filing_at_the_minimum_is_active(api):
    """PRD S3.8: "An `InsuranceFiling` must exist on the proceeding's authority
    whose `policy_number` equals the submitted value, whose `status` is
    `ACTIVE`, and whose coverage interval contains the current logical time. And
    that filing's `coverage_limit_cents` must be at least the authority's
    required minimum for that filing's `filing_type`, failing which the cure is
    refused with `ERR_INSURANCE_BELOW_MINIMUM`."
    PRD S3.8: "A successful cure moves the proceeding `NOTICE_ISSUED → CURED`,
    stamps `cured_at` with the current logical time and records the submitted
    `replacement_policy_number`. Because the proceeding was cured, the
    authority's `insurance_status` is recomputed to `FILED`."

    Design: Difficulty/cross_entity_state_dependency/proceeding_cure_is_gated_on_a_replacement_filing_at_the_minimum
    """
    env = setup_suspended_by_filing_cancel(api)
    required_minimum = env.authority["required_bipd_limit_cents"]

    env = cure_with_replacement_filing(
        api, env, cure_at="2026-09-14T00:00:00Z", policy_number="BIPD-2"
    )

    replacement = assert_insurance_filing(env.replacement_filing)
    assert replacement["policy_number"] == "BIPD-2"
    assert replacement["status"] == "ACTIVE"
    assert replacement["coverage_limit_cents"] == required_minimum
    assert replacement["meets_required_minimum"] is True
    assert replacement["effective_at"] == "2026-09-14T00:00:00.000Z"

    proceeding = assert_revocation_proceeding(env.proceeding)
    assert proceeding["status"] == "CURED"
    assert proceeding["cured_at"] == "2026-09-14T00:00:00.000Z"
    assert proceeding["replacement_policy_number"] == "BIPD-2"
    assert proceeding["revoked_at"] is None

    assert env.authority["insurance_status"] == "FILED"
    assert env.authority["authority_status"] == "ACTIVE"
    assert env.authority["suspension_reason"] == "NONE"
    assert env.authority["suspended_at"] is None


def test_cure_of_an_already_cured_proceeding_is_refused(api):
    """PRD S3.8: "The proceeding must still be `NOTICE_ISSUED`, since `CURED`
    and `REVOKED` are both terminal and yield `ERR_PROCEEDING_NOT_OPEN`."
    PRD S3.8: "A successful cure moves the proceeding `NOTICE_ISSUED → CURED`,
    stamps `cured_at` with the current logical time and records the submitted
    `replacement_policy_number`."

    Design: Difficulty/cross_entity_state_dependency/proceeding_cure_is_gated_on_a_replacement_filing_at_the_minimum
    """
    env = setup_suspended_by_filing_cancel(api)
    env = cure_with_replacement_filing(
        api, env, cure_at="2026-09-14T00:00:00Z", policy_number="BIPD-2"
    )
    assert env.proceeding["status"] == "CURED"

    response = api.cure_proceeding(
        env.proceeding_id, cure_payload("BIPD-2"), COMPLIANCE_OFFICER
    )
    validate_error(response, ApiErrorId.PROCEEDING_NOT_OPEN)

    proceedings, meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 1
    assert proceedings[0]["status"] == "CURED"
    assert proceedings[0]["cured_at"] == "2026-09-14T00:00:00.000Z"

    after = read_authority(api, env.authority_id)
    assert after["authority_status"] == "ACTIVE"
    assert after["suspension_reason"] == "NONE"
