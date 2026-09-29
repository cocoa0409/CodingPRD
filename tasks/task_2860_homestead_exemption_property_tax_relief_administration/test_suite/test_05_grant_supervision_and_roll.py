"""The supervised life of a grant after it reaches the roll.

A grant is a live claim the county keeps testing: three events suspend it, one
compliance action restores it and another ends it outright. Once a grant has
reached one of its three terminal statuses no compliance capability reaches it
again, and the ordering of the screening rungs decides which refusal the caller
is told about.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_GRANT_ALREADY_TERMINAL,
    ERR_GRANT_NOT_SUSPENDED,
)
from test_helpers.assertions import (
    assert_bps,
    assert_common_fields,
    assert_grant,
    assert_parcel_decomposition,
)
from test_helpers.test_users import ANALYST, REVIEWER, REVIEWER_2


def _revoked_grant(api):
    """A homestead grant driven all the way to its terminal revoked status.

    Revocation is admissible straight from `ACTIVE`, and no fraud case is opened
    on the way: an open investigation would itself refuse every compliance action
    on the grant with `ERR_FRAUD_HOLD_ACTIVE` (§2.10 rung 11), so the terminal
    status is reached by the direct path and the parcel then carries no active
    grant at all.
    """
    world = fx.approved_homestead_world(api)
    active = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(
        active,
        benefit_status="ACTIVE",
        suspension_reason=None,
    )
    world["revoked"] = fx.revoke_grant(
        api,
        world["grant_id"],
        reason="Improper claim confirmed by the assessor review.",
    )
    return world


def test_reinstating_a_revoked_grant_reports_the_terminal_status_not_the_suspension(api):
    """PRD §3.5: "The grant must currently be `SUSPENDED`: an attempt against an
    `ACTIVE` grant is refused with `ERR_GRANT_NOT_SUSPENDED`, and one against a grant
    already in a terminal status is refused with `ERR_GRANT_ALREADY_TERMINAL`, which
    as §2.10 explains is evaluated first." PRD §2.10 adds: "Only after a grant has
    been shown to be non-terminal does the system report ... `ERR_GRANT_NOT_SUSPENDED`
    (a reinstatement against an `ACTIVE` grant). A terminal grant therefore never
    yields either of those two errors."

    Design: Corner/state_machines/compliance_action_on_a_revoked_grant_returns_4xx
    """
    world = _revoked_grant(api)
    assert_grant(
        world["revoked"],
        benefit_status="REVOKED",
        suspension_reason=None,
    )

    response = api.grant_compliance_action(
        world["grant_id"],
        f.compliance_action("REINSTATE", "Taxpayer disputes the revocation."),
        REVIEWER_2,
    )
    validate_error(response, ERR_GRANT_ALREADY_TERMINAL, expected_status=409)
    assert ERR_GRANT_NOT_SUSPENDED not in response.text, (
        "the terminal check outranks the suspended-state check, so a revoked grant "
        f"must never be reported as merely not suspended: {response.text}"
    )

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(
        grant,
        benefit_status="REVOKED",
        suspension_reason=None,
        applied_exempt_value_cents=0,
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )


def test_suspending_the_senior_grant_hands_the_whole_basis_to_the_junior_one(api):
    """PRD §2.7: "Grants in any status other than `ACTIVE` — `SUSPENDED`, `REVOKED`,
    `TRANSFERRED` or `LAPSED` — are excluded from both the freeze selection and the
    waterfall, and an excluded grant's `applied_exempt_value_cents` is reset to 0.
    That exclusion is what makes suspension immediately expensive for a taxpayer and
    immediately visible on the roll."

    Design: Corner/calculations/suspended_grant_leaves_the_waterfall_input_set
    """
    world = fx.waterfall_parcel_world(api, approve_second=True)
    parcel_id = world["parcel"]["id"]

    # Before the suspension the junior grant was clipped to the leftover 100000.
    assert_grant(
        validate_success(api.get_grant(world["second_grant_id"], REVIEWER)),
        benefit_status="ACTIVE",
        benefit_amount_cents=500000,
        applied_exempt_value_cents=100000,
    )
    full = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert_parcel_decomposition(
        full,
        assessed_value_cents=1000000,
        exempt_value_cents=1000000,
        taxable_value_cents=0,
        exemption_status="FULLY_EXEMPT",
    )

    fx.open_fraud_case(
        api,
        world["first_grant_id"],
        world["taxpayer"]["id"],
        improper_start_tax_year=2024,
        improper_end_tax_year=2025,
    )

    senior = validate_success(api.get_grant(world["first_grant_id"], REVIEWER))
    assert_grant(
        senior,
        benefit_status="SUSPENDED",
        suspension_reason="FRAUD_INVESTIGATION",
        benefit_amount_cents=900000,
        applied_exempt_value_cents=0,
    )

    # With the rank-10 grant out of the input set the whole basis is available.
    junior = validate_success(api.get_grant(world["second_grant_id"], REVIEWER))
    assert_grant(
        junior,
        benefit_status="ACTIVE",
        benefit_amount_cents=500000,
        applied_exempt_value_cents=500000,
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=1000000,
        exempt_value_cents=500000,
        taxable_value_cents=500000,
        exemption_status="PARTIALLY_EXEMPT",
    )
    assert parcel["version"] == full["version"] + 1, (
        "the suspension is one further parcel mutation, got version "
        f"{parcel['version']} from {full['version']}"
    )


def test_reading_a_grant_exposes_the_waterfall_share_and_its_empty_freeze_fields(api):
    """PRD §3.4: "its `ownership_pct_bps_snapshot` taken from the `ownership_pct_bps`
    of the verified ownership record that satisfied the gate, its
    `relief_multiplier_bps` taken from the resolved income tier or 10000, its
    `first_eligible_tax_year` set to the calendar year of that verified record's
    `occupancy_start_date` ... When the programme has `freeze_enabled` true, both
    `frozen_value_cents` and `portable_balance_cents` are set to the parcel's
    `assessed_value_cents` as observed at approval; for a programme without a freeze
    both fields remain null." PRD §2.7 fixes the applied figure: "each grant in turn
    absorbs the smaller of its own `benefit_amount_cents` and the remaining basis.
    That absorbed figure is written to the grant's `applied_exempt_value_cents`".

    Design: Corner/endpoints/grant_read_exposes_the_waterfall_applied_amount_and_null_freeze_fields
    """
    world = fx.approved_homestead_world(api)

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))

    assert_common_fields(grant)
    assert_grant(
        grant,
        benefit_status="ACTIVE",
        benefit_amount_cents=8400000,
        applied_exempt_value_cents=8400000,
        relief_multiplier_bps=10000,
        suspension_reason=None,
        frozen_value_cents=None,
        portable_balance_cents=None,
    )
    assert_bps(grant, "ownership_pct_bps_snapshot", 10000)
    assert grant["exemption_type"] == "HOMESTEAD_BASIC", (
        f"the programme code is snapshotted at approval, got {grant['exemption_type']}"
    )
    assert grant["effective_tax_year"] == 2026, (
        f"the grant serves the application's tax year, got {grant['effective_tax_year']}"
    )
    assert grant["first_eligible_tax_year"] == 2019, (
        "the retroactive floor is the year the verified occupancy began, got "
        f"{grant['first_eligible_tax_year']}"
    )
    assert grant["application_id"] == world["application_id"], (
        f"the grant names the application it was minted from, got {grant['application_id']}"
    )
    assert grant["ported_from_grant_id"] is None, (
        "this grant was determined, not transferred, got "
        f"{grant['ported_from_grant_id']}"
    )
    assert grant["parcel_id"] == world["parcel"]["id"], (
        f"the grant names its parcel, got {grant['parcel_id']}"
    )
    assert grant["taxpayer_id"] == world["taxpayer"]["id"], (
        f"the grant names its claimant, got {grant['taxpayer_id']}"
    )


def test_reinstating_a_grant_that_was_never_suspended_is_refused(api):
    """PRD §3.5: "The grant must currently be `SUSPENDED`: an attempt against an
    `ACTIVE` grant is refused with `ERR_GRANT_NOT_SUSPENDED`". PRD §3.5 adds what a
    successful reinstatement would have done: "A successful reinstatement returns
    `benefit_status` to `ACTIVE`, clears `suspension_reason` back to null, and
    re-runs the parcel value decomposition so the restored benefit reappears in
    `exempt_value_cents`, with the parcel's `exemption_status` re-derived and its
    `version` incremented by 1."

    Design: Corner/endpoints/reinstate_on_an_active_grant_is_rejected
    """
    world = fx.approved_homestead_world(api)
    grant_version = world["grant_version"]

    validate_error(
        api.grant_compliance_action(
            world["grant_id"],
            f.compliance_action("REINSTATE", "Nothing was ever suspended here."),
            REVIEWER,
        ),
        ERR_GRANT_NOT_SUSPENDED,
        expected_status=409,
    )

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(
        grant,
        benefit_status="ACTIVE",
        suspension_reason=None,
        applied_exempt_value_cents=8400000,
    )
    assert grant["version"] == grant_version, (
        "a refused compliance action is not a mutation, so the grant version must "
        f"not move: {grant_version} became {grant['version']}"
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert parcel["version"] == 2, (
        "creation and the approval are the only two mutations, got version "
        f"{parcel['version']}"
    )
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=8400000,
        taxable_value_cents=25200000,
        exemption_status="PARTIALLY_EXEMPT",
    )
