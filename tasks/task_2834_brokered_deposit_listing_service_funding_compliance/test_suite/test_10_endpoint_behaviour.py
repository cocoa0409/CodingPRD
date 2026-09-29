"""Endpoint-surface behaviour of the Brokered Deposit Funding Compliance API.

Every test in this module builds its own state from an empty database through the
PRD's own endpoints and asserts only what the PRD states.
"""
import pytest

from test_helpers import (
    DEFAULT_CLOCK_INSTANT,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN, COMPLIANCE, DESK, EXAMINER, TREASURY


# ─── Section: create-read-list surface plus the single PATCH verb ─────────────

class TestCrudSurface:
    """The whole write surface is create / read / list plus one PATCH."""

    def test_create_returns_201_read_and_list_return_200_and_patch_recategorises(self):
        """Endpoints that create a new record respond with HTTP 201; every other
        successful call responds with HTTP 200, including the action endpoints that
        drive state machines and the computed reads.

        PRD §2.5: `version`, an integer that starts at 1 on creation and increases by
        exactly 1 on each mutation of the record.

        PRD §3.1: From the capital category the system immediately derives
        `rate_cap_regime`, which is `EXEMPT` when the category is `WELL_CAPITALIZED`
        and `CAPPED` for every other category.

        Design: Corner/endpoints/corner_crud_surface_create_read_list_update_with_no_delete_verb
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)

        institution = validate_success(
            api_client.create_institution(
                f.institution_payload(
                    legal_name="Crud Bank NA",
                    capital_category="WELL_CAPITALIZED",
                    core_deposits_cents=30_000_000_000,
                    total_liabilities_cents=45_000_000_000,
                    tier1_capital_cents=4_000_000_000,
                    liquidity_buffer_cents=900_000_000,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        asserts.assert_institution(institution)
        assert institution["version"] == 1, (
            "a freshly created bank must carry version 1, got "
            f"{institution['version']}"
        )
        assert institution["rate_cap_regime"] == "EXEMPT", (
            "a WELL_CAPITALIZED bank is EXEMPT from the rate ceiling, got "
            f"{institution['rate_cap_regime']}"
        )

        broker = validate_success(
            api_client.create_broker(
                f.broker_payload(
                    legal_name="Crud Brokers LLC",
                    broker_type="DEPOSIT_BROKER",
                    has_placement_discretion=True,
                    fee_structure="BASIS_POINT_FEE",
                    fee_bps=12,
                ),
                DESK,
            ),
            expected_status=201,
        )
        assert broker["diligence_status"] == "NOT_STARTED", (
            "a fresh counterparty starts with diligence_status NOT_STARTED, got "
            f"{broker['diligence_status']}"
        )
        assert broker["approved_agreement_count"] == 0, (
            "a fresh counterparty starts with approved_agreement_count 0, got "
            f"{broker['approved_agreement_count']}"
        )
        assert broker["fee_structure"] == "BASIS_POINT_FEE"
        assert broker["fee_bps"] == 12

        read_back = validate_success(api_client.get_broker(broker["id"], DESK))
        assert read_back["id"] == broker["id"], "the read must address the same row"
        assert read_back["legal_name"] == "Crud Brokers LLC"

        listed, meta = validate_paginated(api_client.list_brokers(COMPLIANCE))
        assert meta["total_count"] == 1, (
            f"exactly one counterparty exists, got total_count {meta['total_count']}"
        )
        assert meta["has_more"] is False, "a single row leaves nothing beyond the window"
        assert meta["limit"] == 10, "limit defaults to 10"
        assert meta["offset"] == 0, "offset defaults to 0"
        assert len(listed) == 1

        patched = validate_success(
            api_client.change_capital_category(
                institution["id"],
                {
                    "capital_category": "ADEQUATELY_CAPITALIZED",
                    "expected_institution_version": institution["version"],
                },
                EXAMINER,
            )
        )
        assert patched["capital_category"] == "ADEQUATELY_CAPITALIZED"
        assert patched["rate_cap_regime"] == "CAPPED", (
            "every category other than WELL_CAPITALIZED is CAPPED, got "
            f"{patched['rate_cap_regime']}"
        )
        assert patched["version"] == 2, (
            f"the mutation must advance version by exactly 1, got {patched['version']}"
        )

    @pytest.mark.parametrize("path_template", [
        "/institutions/{institution_id}",
        "/brokers/{broker_id}",
        "/deposit-programs/{unknown}",
        "/deposit-placements/{unknown}",
        "/primary-purpose-exceptions/{unknown}",
    ])
    def test_no_delete_verb_exists_on_any_resource(self, path_template):
        """The table below lists every endpoint the service exposes.

        PRD §4: All paths are absolute and carry no version or service prefix.

        Design: Corner/endpoints/corner_crud_surface_create_read_list_update_with_no_delete_verb
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        institution = fx.register_institution(legal_name="No Delete Bank NA")
        broker = fx.register_broker(legal_name="No Delete Brokers LLC")

        path = path_template.format(
            institution_id=institution["id"],
            broker_id=broker["id"],
            unknown=NON_EXISTENT_UUID,
        )
        response = api_client._request("DELETE", path, headers=ADMIN)
        assert not (200 <= response.status_code < 300), (
            f"DELETE {path} must not succeed because no DELETE endpoint is exposed; "
            f"got HTTP {response.status_code}"
        )


# ─── Section: plan activation sizes the buffer and then blocks deactivation ───

def _bank_with_one_active_brokered_tranche() -> dict:
    """Bank with a thin liquidity buffer and one ACTIVE 2,000,000,000 tranche."""
    return fx.setup_active_placement(
        institution_overrides={
            "legal_name": "Buffer Bank NA",
            "core_deposits_cents": 20_000_000_000,
            "total_liabilities_cents": 30_000_000_000,
            "tier1_capital_cents": 2_500_000_000,
            "liquidity_buffer_cents": 100_000_000,
        },
        placement_overrides={
            "principal_cents": 2_000_000_000,
            "rate_bps": 470,
            "issue_date": "2026-08-01",
            "tenor_days": 60,
        },
    )


_STAGED_PLAN = {
    "plan_version_label": "CFP-2026-H2",
    "effective_from": "2026-08-01",
    "effective_to": "2026-12-31",
    "stage_1_trigger_bps": 500,
    "stage_2_trigger_bps": 2000,
    "stage_3_trigger_bps": 4000,
    "stage_1_action_code": "MONITOR_DAILY",
    "stage_2_action_code": "DRAW_FHLB_LINE",
    "stage_3_action_code": "ASSET_SALE",
}


class TestPlanActivationBufferSizing:
    """One ACTIVATE call picks the stage, sizes the buffer and exposes the gap."""

    def test_activate_selects_stage_and_sizes_required_buffer_and_shortfall(self):
        """Activation selects a stage from the bank's persisted point-in-time
        `wholesale_funding_ratio_bps`, comparing downward through the three triggers,
        each an inclusive lower bound: the stage is `STAGE_3_CRISIS` when the ratio is
        at or above `stage_3_trigger_bps`, otherwise `STAGE_2_CONTINGENT` when it is at
        or above `stage_2_trigger_bps`, otherwise `STAGE_1_MONITOR` when it is at or
        above `stage_1_trigger_bps`, and otherwise `NONE`.

        PRD §3.7: `required_buffer_cents` is the maturing-soon amount multiplied by
        that multiplier and divided by 10000, with the single final quotient rounded
        half up to whole cents, and `buffer_shortfall_cents` is the amount by which
        `required_buffer_cents` exceeds the bank's `liquidity_buffer_cents`, floored at
        zero.

        Design: Corner/endpoints/corner_plan_activate_sizes_buffer_then_blocks_deactivate
        """
        env = _bank_with_one_active_brokered_tranche()
        institution = fx.read_institution(env["institution"]["id"])
        assert institution["wholesale_funding_ratio_bps"] == 909, (
            "the point-in-time ratio is floor(2000000000 * 10000 / 22000000000), got "
            f"{institution['wholesale_funding_ratio_bps']}"
        )

        plan = fx.setup_approved_plan(env["institution"]["id"], **_STAGED_PLAN)
        assert plan["status"] == "APPROVED"

        activated = validate_success(
            api_client.plan_lifecycle_action(plan["id"], {"action": "ACTIVATE"}, TREASURY)
        )
        asserts.assert_contingency_plan(activated)
        assert activated["status"] == "ACTIVATED"
        assert activated["activation_stage"] == "STAGE_1_MONITOR", (
            "909 bps clears the inclusive 500 trigger but not the 2000 trigger, got "
            f"{activated['activation_stage']}"
        )
        assert activated["required_buffer_cents"] == 500_000_000, (
            "a quarter of the 2,000,000,000 maturing inside the 90-day horizon, got "
            f"{activated['required_buffer_cents']}"
        )
        assert activated["buffer_shortfall_cents"] == 400_000_000, (
            "500000000 required less the 100000000 buffer held, got "
            f"{activated['buffer_shortfall_cents']}"
        )

    def test_deactivate_is_blocked_while_the_shortfall_is_unfunded(self):
        """Deactivation moves it `ACTIVATED → DEACTIVATED` and resets
        `activation_stage` to `NONE` with `required_buffer_cents` and
        `buffer_shortfall_cents` both back to 0, but it is blocked while
        `buffer_shortfall_cents` is greater than zero: the bank must first raise
        `liquidity_buffer_cents` to cover the `required_buffer_cents` computed at
        activation, and an attempt made too early is refused with
        `ERR_BUFFER_SHORTFALL_UNFUNDED`.

        Design: Corner/endpoints/corner_plan_activate_sizes_buffer_then_blocks_deactivate
        """
        env = _bank_with_one_active_brokered_tranche()
        plan = fx.setup_approved_plan(env["institution"]["id"], **_STAGED_PLAN)
        fx.plan_lifecycle_action(plan["id"], "ACTIVATE", TREASURY)

        response = api_client.plan_lifecycle_action(
            plan["id"], {"action": "DEACTIVATE"}, TREASURY
        )
        validate_error(response, ApiErrorId.ERR_BUFFER_SHORTFALL_UNFUNDED.value)

        after = fx.read_plan(plan["id"])
        assert after["status"] == "ACTIVATED", (
            f"the blocked DEACTIVATE must leave the plan ACTIVATED, got {after['status']}"
        )
        assert after["activation_stage"] == "STAGE_1_MONITOR", (
            "the blocked DEACTIVATE must not reset activation_stage, got "
            f"{after['activation_stage']}"
        )
        assert after["required_buffer_cents"] == 500_000_000, (
            "the blocked DEACTIVATE must not zero required_buffer_cents, got "
            f"{after['required_buffer_cents']}"
        )
        assert after["buffer_shortfall_cents"] == 400_000_000, (
            "the blocked DEACTIVATE must not zero buffer_shortfall_cents, got "
            f"{after['buffer_shortfall_cents']}"
        )


# ─── Section: the two-phase maturity sweep ────────────────────────────────────

def _sweep_environment() -> dict:
    """One bank, one counterparty and two attested 30-day brokered programs — one
    with rollover_enabled true, one false — carrying three ACTIVE tranches and one
    that is still PENDING."""
    env = fx.setup_bank(
        institution_overrides={
            "legal_name": "Sweep Bank NA",
            "core_deposits_cents": 20_000_000_000,
            "total_liabilities_cents": 30_000_000_000,
            "tier1_capital_cents": 2_500_000_000,
            "liquidity_buffer_cents": 900_000_000,
        }
    )
    env.update(fx.setup_approved_agreement())
    institution_id = env["institution"]["id"]

    def _open_attested(name, rollover_enabled):
        program = fx.open_program(
            institution_id,
            DESK,
            broker_id=env["broker"]["id"],
            agreement_id=env["agreement"]["id"],
            program_name=name,
            funding_channel_claim="BROKERED",
            product_type="TIME_DEPOSIT",
            tenor_days=30,
            offered_rate_bps=470,
            early_withdrawal_penalty_days=15,
            rollover_enabled=rollover_enabled,
            titling_convention="DIRECT_TITLED",
        )
        fx.classify_program(program["id"], program["version"], COMPLIANCE)
        return fx.attest_program(program["id"], DESK)

    env["program_rolling"] = _open_attested("Rolling Program R", True)
    env["program_static"] = _open_attested("Non Rolling Program N", False)

    env["tranche_a"] = fx.book_placement(
        env["program_rolling"]["id"], DESK, principal_cents=1_000_000_000,
        rate_bps=470, issue_date="2026-08-01", tenor_days=30,
    )
    fx.activate_placement(env["tranche_a"]["id"], DESK)
    env["tranche_b"] = fx.book_placement(
        env["program_static"]["id"], DESK, principal_cents=1_000_000_000,
        rate_bps=470, issue_date="2026-08-01", tenor_days=30,
    )
    fx.activate_placement(env["tranche_b"]["id"], DESK)
    env["tranche_c"] = fx.book_placement(
        env["program_rolling"]["id"], DESK, principal_cents=500_000_000,
        rate_bps=470, issue_date="2026-08-01", tenor_days=60,
    )
    fx.activate_placement(env["tranche_c"]["id"], DESK)
    env["tranche_d"] = fx.book_placement(
        env["program_rolling"]["id"], DESK, principal_cents=100_000_000,
        rate_bps=470, issue_date="2026-08-01", tenor_days=30,
    )
    fx.set_clock("2026-08-31T00:00:00Z")
    return env


class TestMaturitySweep:
    """One sweep matures everything due and rolls over only what is eligible."""

    def test_sweep_matures_every_due_tranche_and_reports_its_counts(self):
        """A system operator runs the sweep, supplying a single `as_of_date`, and the
        sweep covers every placement across the whole book whose `funding_status` is
        `ACTIVE` and whose `maturity_date` falls on or before that date.

        PRD §3.8: Phase one processes the eligible placements in ascending
        `maturity_date`, and where two share a maturity date, in ascending `created_at`.

        Design: Corner/endpoints/corner_maturity_run_matures_all_then_rolls_over_only_eligible
        """
        env = _sweep_environment()

        run = validate_success(
            api_client.run_maturity_sweep({"as_of_date": "2026-08-31"}, ADMIN)
        )
        assert run["as_of_date"] == "2026-08-31"
        assert run["matured_count"] == 2, (
            "only the two tranches maturing 2026-08-31 are eligible, got "
            f"{run['matured_count']}"
        )
        assert run["rolled_over_count"] == 1, (
            "only the tranche whose program permits rollover moves on, got "
            f"{run['rolled_over_count']}"
        )
        assert run["created_placement_count"] == 1, (
            "each roll creates exactly one successor, got "
            f"{run['created_placement_count']}"
        )
        assert run["matured_placement_ids"] == [
            env["tranche_a"]["id"], env["tranche_b"]["id"]
        ], (
            "phase one order is ascending maturity_date then ascending created_at, got "
            f"{run['matured_placement_ids']}"
        )

        assert fx.read_placement(env["tranche_c"]["id"])["funding_status"] == "ACTIVE", (
            "the tranche maturing 2026-09-30 is not yet due and must stay ACTIVE"
        )
        assert fx.read_placement(env["tranche_d"]["id"])["funding_status"] == "PENDING", (
            "a PENDING tranche is not covered by the sweep at all"
        )

    def test_matured_tranche_settles_to_term_and_the_ineligible_roll_is_a_silent_skip(self):
        """Its `accrued_interest_cents` is computed with a settlement date equal to its
        own `maturity_date` — not equal to the sweep's `as_of_date`, which may be later
        — and its `net_settlement_cents` becomes `principal_cents` plus
        `accrued_interest_cents`, with no penalty, because a deposit that runs to term
        is never penalised.

        PRD §3.8: A program whose `rollover_enabled` is false, or that has been
        suspended or closed, simply leaves its matured tranches at `MATURED`, and
        `MATURED` and `ROLLED_OVER` are both terminal on the funding dimension.

        Design: Corner/endpoints/corner_maturity_run_matures_all_then_rolls_over_only_eligible
        """
        env = _sweep_environment()
        validate_success(api_client.run_maturity_sweep({"as_of_date": "2026-08-31"}, ADMIN))

        rolled = fx.read_placement(env["tranche_a"]["id"])
        assert rolled["funding_status"] == "ROLLED_OVER", (
            "the tranche under the rollover-enabled program moves on, got "
            f"{rolled['funding_status']}"
        )
        assert rolled["accrued_interest_cents"] == 3_863_014, (
            "1000000000 * 470 * 30 / 10000 / 365 rounded half up, got "
            f"{rolled['accrued_interest_cents']}"
        )
        assert rolled["net_settlement_cents"] == 1_003_863_014, (
            "running to term carries no penalty, got "
            f"{rolled['net_settlement_cents']}"
        )
        assert rolled["early_withdrawal_penalty_cents"] == 0

        skipped = fx.read_placement(env["tranche_b"]["id"])
        assert skipped["funding_status"] == "MATURED", (
            "a program with rollover_enabled false leaves its tranche at MATURED, got "
            f"{skipped['funding_status']}"
        )
        assert skipped["accrued_interest_cents"] == 3_863_014, (
            "the ineligible roll is a silent skip, so the maturity settlement still ran"
        )

    def test_rollover_successor_is_booked_for_principal_plus_interest_at_the_same_rate(self):
        """Each roll creates one successor placement under the same program, with
        `rolled_from_placement_id` pointing at the placement it came from,
        `principal_cents` equal to that placement's `net_settlement_cents` — so matured
        interest compounds into the new tranche — `rate_bps` taken from the program's
        current `offered_rate_bps` rather than from the old tranche's rate, `issue_date`
        equal to the sweep's `as_of_date`, `tenor_days` taken from the program's current
        `tenor_days`, and therefore a `maturity_date` of `as_of_date` advanced by that
        many days.

        PRD §3.8: The successor is born `PENDING` on `funding_status` and `UNREVIEWED`
        on `compliance_status`, which means it has entered no wholesale bucket, has no
        `classified_as` yet, and still needs a funding activation and a fresh rate-cap
        check of its own before it counts anywhere.

        Design: Corner/endpoints/corner_maturity_run_matures_all_then_rolls_over_only_eligible
        """
        env = _sweep_environment()
        validate_success(api_client.run_maturity_sweep({"as_of_date": "2026-08-31"}, ADMIN))

        tranches, _ = validate_paginated(
            api_client.list_placements(ADMIN, params={"limit": 50})
        )
        successors = [
            t for t in tranches
            if t.get("rolled_from_placement_id") == env["tranche_a"]["id"]
        ]
        assert len(successors) == 1, (
            "exactly one successor points back at the rolled tranche, got "
            f"{len(successors)}"
        )
        successor = successors[0]
        assert successor["program_id"] == env["program_rolling"]["id"], (
            "the successor is booked on the same program"
        )
        assert successor["principal_cents"] == 1_003_863_014, (
            "principal and interest compound forward into the successor, got "
            f"{successor['principal_cents']}"
        )
        assert successor["rate_bps"] == 470, (
            "the successor takes the program's current offered_rate_bps, got "
            f"{successor['rate_bps']}"
        )
        assert successor["issue_date"] == "2026-08-31", (
            "the successor issues on the sweep's as_of_date, got "
            f"{successor['issue_date']}"
        )
        assert successor["tenor_days"] == 30, (
            f"the successor takes the program's tenor, got {successor['tenor_days']}"
        )
        assert successor["maturity_date"] == "2026-09-30", (
            "maturity_date follows from issue_date plus tenor_days, got "
            f"{successor['maturity_date']}"
        )
        assert successor["funding_status"] == "PENDING", (
            f"the successor is created in PENDING, got {successor['funding_status']}"
        )
        assert successor["compliance_status"] == "UNREVIEWED", (
            "the successor is born UNREVIEWED, got "
            f"{successor['compliance_status']}"
        )
        assert successor["tenor_bucket"] == "DAYS_1_30", (
            f"a 30-day tenor falls in DAYS_1_30, got {successor['tenor_bucket']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 500_000_000, (
            "only the still-ACTIVE tranche keeps contributing brokered money, got "
            f"{institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 20_500_000_000, (
            "total deposits are core plus live brokered money, got "
            f"{institution['total_deposits_cents']}"
        )


# ─── Section: recording a determination ───────────────────────────────────────

def _two_banks_one_counterparty() -> dict:
    """Two registered banks sharing one approved counterparty, each with its own
    ACKNOWLEDGED notice filing, plus a BROKERED program at the first bank."""
    env = fx.setup_bank(
        institution_overrides={
            "legal_name": "Home Bank NA",
            "core_deposits_cents": 30_000_000_000,
            "total_liabilities_cents": 45_000_000_000,
        }
    )
    env["other_institution"] = fx.register_institution(
        legal_name="Neighbour Bank NA",
        core_deposits_cents=15_000_000_000,
        total_liabilities_cents=22_000_000_000,
    )
    env.update(fx.setup_approved_agreement())
    env["own_exception"] = fx.setup_acknowledged_exception(
        env["broker"]["id"], env["institution"]["id"],
        designated_business_line="Advisory sweep at the home bank",
    )
    env["other_exception"] = fx.setup_acknowledged_exception(
        env["broker"]["id"], env["other_institution"]["id"],
        designated_business_line="Advisory sweep at the neighbour bank",
    )
    env["program"] = fx.open_program(
        env["institution"]["id"], DESK,
        broker_id=env["broker"]["id"],
        agreement_id=env["agreement"]["id"],
        program_name="90D Brokered CD",
        funding_channel_claim="BROKERED",
        tenor_days=60,
        offered_rate_bps=470,
    )
    return env


class TestDeterminationExceptionLink:
    """A determination may only lean on an exception filed for its own pairing."""

    def test_leaning_on_another_banks_filing_is_a_counterparty_mismatch(self):
        """Where an exception is named, that filing's `status` must be `ACKNOWLEDGED`
        or `GRANTED` — a `DRAFT`, `UNDER_REVIEW`, `INFO_REQUESTED`, `DENIED`,
        `WITHDRAWN` or `REVOKED` filing cannot be relied upon and the attempt is
        refused with `ERR_EXCEPTION_NOT_RELIABLE` — and that filing's `broker_id` must
        equal the program's `broker_id` while its `institution_id` must equal the
        program's `institution_id`, failing which the attempt is refused with
        `ERR_EXCEPTION_COUNTERPARTY_MISMATCH`.

        Design: Corner/endpoints/corner_classification_link_to_other_banks_exception_rejected
        """
        env = _two_banks_one_counterparty()

        response = api_client.create_classification(
            f.classification_payload(
                env["program"]["id"], env["program"]["version"],
                relied_exception_id=env["other_exception"]["id"],
            ),
            COMPLIANCE,
        )
        validate_error(response, ApiErrorId.ERR_EXCEPTION_COUNTERPARTY_MISMATCH.value)

        program = fx.read_program(env["program"]["id"])
        assert program["state"] == "PENDING_CLASSIFICATION", (
            "a refused determination leaves the program unclassified, got "
            f"{program['state']}"
        )
        assert program["version"] == env["program"]["version"], (
            "a refused determination does not increment the program version"
        )
        assert program["governing_classification_id"] is None, (
            "no determination governs the program yet"
        )
        assert fx.read_exception(env["other_exception"]["id"])["reliant_program_count"] == 0, (
            "the other bank's filing gained no reliant program"
        )

    def test_leaning_on_the_matching_filing_carries_the_program_out_of_brokered(self):
        """Third, when a relied exception is present, its `status` is `ACKNOWLEDGED` or
        `GRANTED` and its `test_outcome` is either `QUALIFIED` or `NOT_EVALUATED`, the
        reliance carries the program out of the brokered class and the
        `determined_class` is `LISTING_SERVICE_NON_BROKERED`.

        PRD §3.4: Reliance accounting travels with it: when the new determination names
        an exception, that filing's `reliant_program_count` increases by 1, and when the
        determination being superseded named a different exception, that other filing's
        `reliant_program_count` decreases by 1.

        Design: Corner/endpoints/corner_classification_link_to_other_banks_exception_rejected
        """
        env = _two_banks_one_counterparty()

        determination = validate_success(
            api_client.create_classification(
                f.classification_payload(
                    env["program"]["id"], env["program"]["version"],
                    relied_exception_id=env["own_exception"]["id"],
                ),
                COMPLIANCE,
            ),
            expected_status=201,
        )
        asserts.assert_deposit_classification(determination)
        assert determination["determined_class"] == "LISTING_SERVICE_NON_BROKERED", (
            "reliance on the bank's own acknowledged filing wins the third branch, got "
            f"{determination['determined_class']}"
        )
        assert determination["deposit_broker_prong"] == "NOT_APPLICABLE", (
            "the first four branches record NOT_APPLICABLE, got "
            f"{determination['deposit_broker_prong']}"
        )
        assert determination["call_report_line"] == "RC_E_M2_LISTING", (
            "LISTING_SERVICE_NON_BROKERED maps to RC_E_M2_LISTING, got "
            f"{determination['call_report_line']}"
        )
        assert determination["program_version_at_determination"] == 2, (
            "the witness is the observed version plus this determination's increment, "
            f"got {determination['program_version_at_determination']}"
        )

        program = fx.read_program(env["program"]["id"])
        assert program["state"] == "CLASSIFIED", (
            f"applying a determination moves the program to CLASSIFIED, got {program['state']}"
        )
        assert program["governing_classification_id"] == determination["id"]
        assert program["version"] == 2, (
            f"the program version increments by 1, got {program['version']}"
        )

        assert fx.read_exception(env["own_exception"]["id"])["reliant_program_count"] == 1, (
            "the relied filing gains one reliant program"
        )
        assert fx.read_exception(env["other_exception"]["id"])["reliant_program_count"] == 0, (
            "the untouched filing at the other bank is unaffected"
        )


# ─── Section: the computed fee-position read ───────────────────────────────────

def _flat_fee_book_with_two_active_lines() -> dict:
    """FLAT_FEE agreement of 25,000 cents carrying two ACTIVE tranches."""
    env = fx.setup_open_program(
        agreement_overrides={"fee_structure": "FLAT_FEE", "fee_flat_cents": 25000},
        program_overrides={
            "program_name": "Flat Fee Brokered CD",
            "tenor_days": 60,
            "offered_rate_bps": 470,
        },
    )
    env["line_one"] = fx.book_placement(
        env["program"]["id"], DESK, principal_cents=1_000_000_000,
        rate_bps=470, issue_date="2026-08-01", tenor_days=60,
    )
    fx.activate_placement(env["line_one"]["id"], DESK)
    env["line_two"] = fx.book_placement(
        env["program"]["id"], DESK, principal_cents=300_000_000,
        rate_bps=470, issue_date="2026-08-01", tenor_days=61,
    )
    fx.activate_placement(env["line_two"]["id"], DESK)
    return env


class TestFeeSummaryRead:
    """The computed fee read agrees with the mirror persisted on the agreement."""

    def test_summary_reports_round_then_sum_lines_and_agreement_mirrors_the_total(self):
        """The fee position is readable as a computed summary that names the
        `agreement_id` it belongs to, echoes the governing `fee_structure`, reports
        `line_count` as the number of contributing placements — counting only those
        whose `funding_status` is `ACTIVE` — and returns the round-then-sum total as
        `accrued_fee_cents` alongside the parallel arrays `line_fee_cents` and
        `line_placement_ids`.

        PRD §3.2: under `FLAT_FEE` and under `PER_ACCOUNT_FEE` the line fee is the
        agreement's `fee_flat_cents`

        PRD §3.2: The rounding order is pinned: every line is rounded to whole cents
        first and the rounded lines are then added together to give the agreement's
        `accrued_fee_cents`.

        Design: Corner/endpoints/corner_fee_summary_read_matches_persisted_agreement_mirror
        """
        env = _flat_fee_book_with_two_active_lines()

        summary = validate_success(
            api_client.get_fee_summary(env["agreement"]["id"], DESK)
        )
        assert summary["agreement_id"] == env["agreement"]["id"], (
            "the summary names the agreement it belongs to"
        )
        assert summary["fee_structure"] == "FLAT_FEE", (
            f"the summary echoes the governing structure, got {summary['fee_structure']}"
        )
        assert summary["line_count"] == 2, (
            f"both ACTIVE tranches contribute a line, got {summary['line_count']}"
        )
        assert summary["line_fee_cents"] == [25000, 25000], (
            "a flat fee charges fee_flat_cents per line regardless of principal, got "
            f"{summary['line_fee_cents']}"
        )
        assert summary["line_placement_ids"] == [
            env["line_one"]["id"], env["line_two"]["id"]
        ], (
            "the lines are processed in placement created_at ascending order, got "
            f"{summary['line_placement_ids']}"
        )
        assert summary["accrued_fee_cents"] == 50000, (
            "the rounded lines are added together, got "
            f"{summary['accrued_fee_cents']}"
        )

        agreement = fx.read_agreement(env["agreement"]["id"])
        assert agreement["accrued_fee_cents"] == 50000, (
            "the agreement mirrors the same round-then-sum total, got "
            f"{agreement['accrued_fee_cents']}"
        )
        for line_id in (env["line_one"]["id"], env["line_two"]["id"]):
            placement = fx.read_placement(line_id)
            assert placement["fee_accrual_cents"] == 25000, (
                f"each contributing line carries its own fee, got "
                f"{placement['fee_accrual_cents']} on {line_id}"
            )

    def test_a_tranche_leaving_active_drops_out_of_the_summary_and_the_mirror(self):
        """A placement leaving `ACTIVE` has its own `fee_accrual_cents` reset to 0 and
        drops out of the sum, and a placement under a program with no `agreement_id` has
        a `fee_accrual_cents` of 0 because no agreement governs it.

        PRD §3.5: The withdrawal then unwinds the balance sheet exactly:
        `principal_cents` is subtracted from the matching wholesale bucket and the
        concentration posture is re-run, the same amount is subtracted from the
        program's `outstanding_principal_cents`, and the agreement fee position is
        recomputed with this tranche dropped from the lines.

        Design: Corner/endpoints/corner_fee_summary_read_matches_persisted_agreement_mirror
        """
        env = _flat_fee_book_with_two_active_lines()

        fx.early_withdraw_placement(env["line_two"]["id"], "2026-08-15", DESK)

        summary = validate_success(
            api_client.get_fee_summary(env["agreement"]["id"], DESK)
        )
        assert summary["line_count"] == 1, (
            f"only the surviving ACTIVE tranche contributes, got {summary['line_count']}"
        )
        assert summary["line_placement_ids"] == [env["line_one"]["id"]], (
            f"the withdrawn tranche drops out, got {summary['line_placement_ids']}"
        )
        assert summary["line_fee_cents"] == [25000]
        assert summary["accrued_fee_cents"] == 25000, (
            f"the total falls to the one remaining line, got {summary['accrued_fee_cents']}"
        )

        assert fx.read_agreement(env["agreement"]["id"])["accrued_fee_cents"] == 25000, (
            "the persisted mirror follows the recomputed position"
        )
        withdrawn = fx.read_placement(env["line_two"]["id"])
        assert withdrawn["funding_status"] == "WITHDRAWN_EARLY"
        assert withdrawn["fee_accrual_cents"] == 0, (
            "a tranche leaving ACTIVE has its own fee reset to 0, got "
            f"{withdrawn['fee_accrual_cents']}"
        )


# ─── Section: revocation is admitted only from a live acknowledgement ──────────

def _draft_notice_filing() -> dict:
    """One bank, one counterparty and one DRAFT twenty-five-percent notice filing."""
    env = fx.setup_bank(institution_overrides={"legal_name": "Notice Bank NA"})
    env["broker"] = fx.register_broker(legal_name="Notice Brokers LLC")
    env["exception"] = fx.file_exception(
        env["broker"]["id"], env["institution"]["id"], DESK,
        exception_basis="TWENTY_FIVE_PERCENT_TEST",
        designated_business_line="Advisory cash sweep",
        total_customer_assets_cents=40_000_000_000,
        deposits_placed_at_ifs_cents=4_000_000_000,
    )
    return env


class TestExceptionRevocationAdmissibility:
    """A DRAFT filing cannot be revoked; the same call succeeds once acknowledged."""

    def test_revoking_a_draft_filing_is_refused_and_changes_nothing(self):
        """Revocation is the heaviest operation in the system and is admitted from
        `ACKNOWLEDGED` and from `GRANTED`, with identical consequences from either.

        PRD §2.8 rule 17: Exception lifecycle admissibility, including a `SUBMIT` from
        any state other than `DRAFT` and any second `SUBMIT` —
        `ERR_EXCEPTION_STATE_INVALID`. Filing actions and review actions.

        Design: Corner/endpoints/corner_revoke_allowed_only_after_acknowledgement
        """
        env = _draft_notice_filing()
        assert env["exception"]["status"] == "DRAFT", (
            f"the filing starts in DRAFT, got {env['exception']['status']}"
        )
        assert env["exception"]["reporting_due_date"] == "2026-10-30", (
            "reporting_due_date is the logical clock's date plus 90 days, got "
            f"{env['exception']['reporting_due_date']}"
        )

        response = api_client.exception_review_action(
            env["exception"]["id"], {"action": "REVOKE"}, COMPLIANCE
        )
        validate_error(response, ApiErrorId.ERR_EXCEPTION_STATE_INVALID.value)

        unchanged = fx.read_exception(env["exception"]["id"])
        assert unchanged["status"] == "DRAFT", (
            f"a refused revocation leaves the filing in DRAFT, got {unchanged['status']}"
        )
        assert unchanged["reporting_due_date"] == "2026-10-30", (
            "a refused revocation does not null the deadline, got "
            f"{unchanged['reporting_due_date']}"
        )
        assert unchanged["version"] == env["exception"]["version"], (
            "a refused revocation does not advance the version"
        )

    def test_submission_acknowledges_the_notice_and_then_revocation_nulls_the_deadline(self):
        """A `NOTICE` filing is self-effecting: it moves `DRAFT → ACKNOWLEDGED` with no
        review at all, and re-bases `reporting_due_date` to the logical clock's date plus
        90 days.

        PRD §3.3: Under the twenty-five-percent basis, `test_outcome` is `QUALIFIED`
        only when `business_line_deposit_ratio_bps` is strictly below 2500 basis points,
        which is 25 percent — a ratio of exactly 2500 fails.

        PRD §3.3: Hop one sets the filing's own status to `REVOKED` and nulls
        `reporting_due_date`.

        Design: Corner/endpoints/corner_revoke_allowed_only_after_acknowledgement
        """
        env = _draft_notice_filing()

        acknowledged = validate_success(
            api_client.exception_filing_action(
                env["exception"]["id"], {"action": "SUBMIT"}, DESK
            )
        )
        assert acknowledged["status"] == "ACKNOWLEDGED", (
            f"a notice self-effects to ACKNOWLEDGED, got {acknowledged['status']}"
        )
        assert acknowledged["test_outcome"] == "QUALIFIED", (
            "a ratio strictly below 2500 basis points qualifies, got "
            f"{acknowledged['test_outcome']}"
        )
        assert acknowledged["reporting_due_date"] == "2026-10-30", (
            "submission re-bases the deadline to the clock's date plus 90 days, got "
            f"{acknowledged['reporting_due_date']}"
        )

        revoked = validate_success(
            api_client.exception_review_action(
                env["exception"]["id"], {"action": "REVOKE"}, COMPLIANCE
            )
        )
        assert revoked["status"] == "REVOKED", (
            f"revocation is admitted from ACKNOWLEDGED, got {revoked['status']}"
        )
        assert revoked["reporting_due_date"] is None, (
            "hop one nulls reporting_due_date, got "
            f"{revoked['reporting_due_date']}"
        )
        assert revoked["reliant_program_count"] == 0, (
            "no program leaned on this filing, got "
            f"{revoked['reliant_program_count']}"
        )
