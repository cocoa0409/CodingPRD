"""Lifecycle cycles, multi-level cascades and rejection-ordering precedence.

Every test builds its own preconditions through the declared endpoints only,
starting from an empty database and a pinned logical clock.
"""

from test_helpers import (
    CA_FLOOR_DE,
    CLOCK_DEFAULT,
    CONTRACT_MG,
    FACILITY_ADVANCE_BONDED,
    FACILITY_COLLATERAL,
    FILM_BUDGET,
    HEAD_OF_SALES_CLOSER,
    HEAD_OF_SALES_VALUER,
    LIST_ALL,
    MAX_NEGOTIATION_ROUNDS,
    add_milestone_schedule,
    assert_account_counters,
    assert_allocations,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_empty_collection,
    assert_facility_figures,
    assert_film_counters,
    assert_instant,
    assert_list_response,
    assert_money,
    assert_object_response,
    assert_tier,
    buyer_amendment_payload,
    buyer_meeting_payload,
    contract_payload,
    counter_payload,
    distribute_payload,
    drawn_facility,
    executed_contract,
    executed_contract_environment,
    find_by,
    make_account,
    make_buyer_headers,
    make_collection_agent_headers,
    make_head_of_sales_headers,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_tiers,
    milestone_by_label,
    offered_contract,
    open_market_with_buyers,
    pin_clock,
    post_receipt,
    post_receipts,
    publish_payload,
    read_account,
    read_agreement,
    read_buyer,
    read_contract,
    read_facility,
    read_film,
    read_milestones,
    read_tiers,
    read_valuation,
    record_qc_fail,
    revise_payload,
    state_payload,
    submit_package,
    valued_slate,
    validate_error,
)

# --------------------------------------------------------------------------
# Instants this module pins the logical clock to.
# --------------------------------------------------------------------------
CLOCK_AFTER_LICENSE_TERM = "2028-08-01T00:00:00Z"   # the contract's license_end_date
CLOCK_FIRST_DELIVERY = "2027-06-20T00:00:00Z"       # after holdback release
CLOCK_RESUBMISSION = "2027-07-01T00:00:00Z"         # inside the cure window

# Receipt bookings for the four-line schedule against a 2000000.00 guarantee.
FOUR_RECEIPT_DATES = (
    ("ON_SIGNATURE", "2026-08-05T00:00:00Z"),
    ("ON_DELIVERY", "2027-06-20T00:00:00Z"),
    ("ON_RELEASE", "2027-07-20T00:00:00Z"),
    ("ON_TERM_END", "2028-07-30T00:00:00Z"),
)

# The negotiated figures: the opening guarantee, the buyer's first counter, the
# agency's answer, the buyer's second counter, and the amounts the answer derives
# for the 0.45 / 0.20 / 0.10 / 0.25 schedule.
NEGOTIATION_MG = 1300000.00
COUNTER_ONE_MG = 1200000.00
REVISED_MG = 1280000.00
COUNTER_TWO_MG = 1220000.00
REVISED_MILESTONE_AMOUNTS = (576000.00, 256000.00, 128000.00, 320000.00)
SIGNATURE_RECEIPT_INSTANT = "2026-09-02T00:00:00Z"


# --------------------------------------------------------------------------
# Private module-level builders (the shared helper package is frozen).
# --------------------------------------------------------------------------
def _error_id(response):
    """The machine-readable error identifier out of an error envelope."""
    return response.json()["data"]["error_id"]


def _final_rejection_environment(api):
    """An EXECUTED contract, a bonded/approved/drawn facility, one already-rejected
    package and a second package sitting at the revision limit."""
    pin_clock(api, CLOCK_DEFAULT)
    env = executed_contract(api)
    drawn_facility(api, env)
    pin_clock(api, CLOCK_FIRST_DELIVERY)
    env["package_1"] = submit_package(api, env["contract"]["id"], technical=14, legal=6)
    record_qc_fail(api, env["package_1"]["id"], env["buyer"]["id"], "QC_FAIL")
    pin_clock(api, CLOCK_RESUBMISSION)
    env["package_2"] = submit_package(api, env["contract"]["id"], technical=15, legal=7)
    return env


def _ledger_cascade_environment(api):
    """An EXECUTED contract with an OPEN account carrying a capped collection fee and
    a sales-commission tier whose ceiling the operator authored before any cash."""
    pin_clock(api, CLOCK_DEFAULT)
    env = executed_contract_environment(api)
    env["tiers"] = make_tiers(
        api,
        env["account"]["id"],
        [
            (1, "COLLECTION_FEE", 0.0125, 25000.00),
            (2, "SALES_COMMISSION", 1.00, 1.00),
        ],
    )
    return env


def _negotiation_environment(api):
    """An OFFERED contract at the opening guarantee, its complete four-line schedule,
    and an OPEN collection account so the cash axis can move on its own."""
    pin_clock(api, CLOCK_DEFAULT)
    env = offered_contract(api, minimum_guarantee_usd=NEGOTIATION_MG)
    env["milestones"] = add_milestone_schedule(api, env["contract"]["id"])
    env["account"] = make_account(api, env["film"]["id"])
    return env


def _counter(api, env, counter_minimum_guarantee_usd):
    """The buyer's move, made by the contract's own buyer."""
    return api.counter_contract(
        env["contract"]["id"],
        counter_payload(counter_minimum_guarantee_usd),
        make_buyer_headers(env["buyer"]["id"]),
    )


def _revise(api, env, minimum_guarantee_usd):
    """The agency's answer to a countered offer."""
    return api.revise_offer(
        env["contract"]["id"],
        revise_payload(minimum_guarantee_usd),
        make_sales_agent_headers(),
    )


def _packaging_slate_with_published_valuation(api, exposure_limit_usd):
    """A picture deliberately left at PACKAGING whose one territory valuation is
    nonetheless PUBLISHED, with a buyer carrying the given exposure limit."""
    pin_clock(api, CLOCK_DEFAULT)
    env = valued_slate(api, buyer_overrides={"exposure_limit_usd": exposure_limit_usd})
    film_version = read_film(api, env["film"]["id"])["version"]
    env["valuation"] = assert_object_response(
        api.publish_valuation(
            env["valuation"]["id"],
            publish_payload(film_version),
            make_head_of_sales_headers(HEAD_OF_SALES_VALUER),
        )
    )
    return env


def _blocked_buyer_meeting_environment(api):
    """An OPEN market where one distributor already holds table 3 for 10:00-11:30 and
    a second distributor has been set to BLOCKED."""
    pin_clock(api, CLOCK_DEFAULT)
    env = open_market_with_buyers(api)
    env["meeting_nordic"] = assert_created(
        api.create_buyer_meeting(
            buyer_meeting_payload(
                env["market"]["id"],
                env["buyer_alt"]["id"],
                env["film"]["id"],
                3,
                "2026-11-06T10:00:00Z",
                "2026-11-06T11:30:00Z",
            ),
            make_sales_agent_headers(),
        )
    )
    env["buyer"] = assert_object_response(
        api.patch_buyer(
            env["buyer"]["id"],
            buyer_amendment_payload(status="BLOCKED"),
            make_platform_admin_headers(),
        )
    )
    return env


def _replay_offer(api, env, buyer_version):
    """Re-send the identical offer body, carrying the buyer version supplied."""
    return api.create_contract(
        contract_payload(
            env["film"]["id"],
            env["buyer"]["id"],
            env["territory"]["id"],
            buyer_version,
            minimum_guarantee_usd=CONTRACT_MG,
        ),
        make_sales_agent_headers(),
    )


def _replay_meeting(api, env, table_number):
    """Re-send the identical 11:00-12:00 window at the table number supplied."""
    return api.create_buyer_meeting(
        buyer_meeting_payload(
            env["market"]["id"],
            env["buyer"]["id"],
            env["film"]["id"],
            table_number,
            "2026-11-06T11:00:00Z",
            "2026-11-06T12:00:00Z",
        ),
        make_sales_agent_headers(),
    )


# ==========================================================================
# The picture's sales_status cycle: IN_MARKET -> SOLD_OUT -> IN_MARKET
# ==========================================================================
class TestFilmSalesStatusCycle:
    def test_countersigning_alone_drives_the_picture_to_sold_out(self, api):
        """One countersigning saturates the single published territory and the picture leaves IN_MARKET without any operator call.

        PRD: "`IN_MARKET → SOLD_OUT` is never requested by an operator: the system evaluates it at the end of every successful contract countersigning, and fires it when `published_territory_count` is at least 1 and `licensed_territory_count` equals `published_territory_count` — that is, when every territory the agency has published a valuation for has been licensed."

        Design: Difficulty/non_linear_state_machine/film_sales_status_cycles_in_market_to_sold_out_and_back_on_reversion
        """
        pin_clock(api, CLOCK_DEFAULT)
        env = executed_contract_environment(api)

        film = read_film(api, env["film"]["id"])
        assert_film_counters(
            film,
            sales_status="SOLD_OUT",
            published_count=1,
            licensed_count=1,
            committed=CONTRACT_MG,
        )

    def test_four_receipts_pay_the_contract_off_on_its_own_cash_axis(self, api):
        """Booking every milestone of the schedule drives the collection axis to PAID with nothing unpaid left.

        PRD: "`PARTIALLY_PAID → PAID` fires when, after the receipt, the contract's `unpaid_amount_usd` has reached exactly zero — that is, once every milestone of the contract has been received."

        Design: Difficulty/non_linear_state_machine/film_sales_status_cycles_in_market_to_sold_out_and_back_on_reversion
        """
        pin_clock(api, CLOCK_DEFAULT)
        env = executed_contract_environment(api)
        post_receipts(api, env, FOUR_RECEIPT_DATES)

        contract = read_contract(api, env["contract"]["id"])
        assert_contract_axes(contract, negotiation="EXECUTED", collection="PAID")
        assert_money(contract["unpaid_amount_usd"], 0.00, "unpaid_amount_usd")
        assert_money(contract["received_amount_usd"], CONTRACT_MG, "received_amount_usd")

    def test_reversion_returns_the_rights_and_closes_the_cycle_back_to_in_market(self, api):
        """Reverting the expired licence hands the territory back and the picture returns to a state it had already left.

        PRD: "Reversion returns the matching `LICENSED` valuation to `PUBLISHED`, recomputes the picture's `licensed_territory_count`, moves the picture `SOLD_OUT → IN_MARKET` when the licensed count now sits below the published count, increments the picture's `version`, and recomputes the buyer's `net_unpaid_exposure_usd` along with every affected facility's `advance_amount_usd`."

        Design: Difficulty/non_linear_state_machine/film_sales_status_cycles_in_market_to_sold_out_and_back_on_reversion
        """
        pin_clock(api, CLOCK_DEFAULT)
        env = executed_contract_environment(api)
        version_before_publication = env["film_version_at_publish"]
        post_receipts(api, env, FOUR_RECEIPT_DATES)

        pin_clock(api, CLOCK_AFTER_LICENSE_TERM)
        reverted = assert_object_response(
            api.revert_contract(
                env["contract"]["id"], make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
            )
        )
        assert_contract_axes(reverted, negotiation="REVERTED")

        valuation = read_valuation(api, env["valuation"]["id"])
        assert valuation["status"] == "PUBLISHED", (
            f"the reverted licence must return the valuation to PUBLISHED, "
            f"got {valuation['status']}"
        )

        film = read_film(api, env["film"]["id"])
        assert_film_counters(
            film, sales_status="IN_MARKET", published_count=1, licensed_count=0
        )
        assert film["version"] > version_before_publication, (
            "the picture's version must advance monotonically across both edges of the "
            f"cycle, got {film['version']} against {version_before_publication}"
        )

    def test_reversion_does_not_claw_back_the_collected_cash(self, api):
        """Every dollar booked before the licence ran out is still sitting undistributed in the account after reversion.

        PRD: "Residual rights return to the agency and the territory becomes sellable again — but collected cash is explicitly **not** clawed back."

        Design: Difficulty/non_linear_state_machine/film_sales_status_cycles_in_market_to_sold_out_and_back_on_reversion
        """
        pin_clock(api, CLOCK_DEFAULT)
        env = executed_contract_environment(api)
        post_receipts(api, env, FOUR_RECEIPT_DATES)

        pin_clock(api, CLOCK_AFTER_LICENSE_TERM)
        assert_object_response(
            api.revert_contract(
                env["contract"]["id"], make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
            )
        )

        account = read_account(api, env["account"]["id"])
        assert_account_counters(
            account,
            receipts=2000000.00,
            distributed=0.00,
            balance=2000000.00,
            run_count=0,
        )

    def test_the_cycle_is_not_re_enterable_through_the_reverted_contract(self, api):
        """A second countersigning of the same contract is refused because the negotiation axis has reached a terminal state.

        PRD: "**Seventh, the target row's own state.** Whether the row's own current status permits the requested transition, including a repeated trigger on a row already in the destination state or already in a terminal state, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/film_sales_status_cycles_in_market_to_sold_out_and_back_on_reversion
        """
        pin_clock(api, CLOCK_DEFAULT)
        env = executed_contract_environment(api)
        post_receipts(api, env, FOUR_RECEIPT_DATES)

        pin_clock(api, CLOCK_AFTER_LICENSE_TERM)
        assert_object_response(
            api.revert_contract(
                env["contract"]["id"], make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
            )
        )

        replay = api.execute_contract(
            env["contract"]["id"], make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
        )
        validate_error(replay, "ERR_INVALID_STATE", 409)

        contract = read_contract(api, env["contract"]["id"])
        assert_contract_axes(contract, negotiation="REVERTED")


def _read_packages(api, contract_id):
    """Every deliverable package of the contract, ordered as the collection declares."""
    rows, _meta = assert_list_response(
        api.list_deliverable_packages(contract_id, make_sales_agent_headers(), LIST_ALL)
    )
    return rows


# ==========================================================================
# The final-rejection cascade: package -> contract -> milestones -> facility -> film
# ==========================================================================
class TestFinalRejectionCascade:
    def test_first_failing_verdict_rejects_the_package_and_stamps_the_cure_window(self, api):
        """The verdict below the revision limit rejects the package, records the reason and opens a thirty-day cure window.

        PRD: "**A failing verdict below the revision limit** sets `qc_result` to `FAIL`, writes the supplied `rejection_reason`, moves the package `SUBMITTED → REJECTED`, stamps its `cure_deadline` as 30 days after the package's `submitted_at`, and drives the contract's `delivery_status` to `REJECTED`."

        Design: Difficulty/transitive_cascade/final_qc_rejection_cascades_four_levels_from_package_to_margin_call
        """
        pin_clock(api, CLOCK_DEFAULT)
        env = executed_contract(api)
        drawn_facility(api, env)
        pin_clock(api, CLOCK_FIRST_DELIVERY)
        package = submit_package(api, env["contract"]["id"], technical=14, legal=6)
        assert_instant(package["submitted_at"], CLOCK_FIRST_DELIVERY, "submitted_at")

        rejected = record_qc_fail(api, package["id"], env["buyer"]["id"], "QC_FAIL")

        assert rejected["status"] == "REJECTED", (
            f"expected package status REJECTED, got {rejected['status']}"
        )
        assert rejected["qc_result"] == "FAIL", (
            f"expected qc_result FAIL, got {rejected['qc_result']}"
        )
        assert rejected["rejection_reason"] == "QC_FAIL", (
            f"expected rejection_reason QC_FAIL, got {rejected['rejection_reason']}"
        )
        assert_instant(rejected["cure_deadline"], "2027-07-20T00:00:00Z", "cure_deadline")
        assert_contract_axes(
            read_contract(api, env["contract"]["id"]),
            negotiation="EXECUTED",
            delivery="REJECTED",
        )

    def test_level_1_failing_verdict_at_the_revision_limit_writes_rejected_final(self, api):
        """The second package carries revision round two, so its failing verdict is written straight to the terminal state.

        PRD: "The revision limit is 2, so a package at `revision_round` 2 that receives a failing verdict is written directly to `REJECTED_FINAL` rather than `REJECTED`, and `REJECTED_FINAL` is terminal."

        Design: Difficulty/transitive_cascade/final_qc_rejection_cascades_four_levels_from_package_to_margin_call
        """
        env = _final_rejection_environment(api)
        assert env["package_2"]["revision_round"] == 2, (
            "the resubmission must sit one revision round above the rejected package, got "
            f"{env['package_2']['revision_round']}"
        )

        final = record_qc_fail(
            api, env["package_2"]["id"], env["buyer"]["id"], "TECHNICAL_INCOMPLETE"
        )

        assert final["status"] == "REJECTED_FINAL", (
            f"expected package status REJECTED_FINAL, got {final['status']}"
        )
        stored = find_by(
            _read_packages(api, env["contract"]["id"]), id=env["package_2"]["id"]
        )
        assert stored["status"] == "REJECTED_FINAL", (
            f"the stored package must read REJECTED_FINAL, got {stored['status']}"
        )

    def test_level_2_the_contract_axes_collapse_in_the_same_request(self, api):
        """The deal dies on all three axes at once: delivery rejected, negotiation lapsed and the cash written off.

        PRD: "The contract's `delivery_status` becomes `REJECTED`, and its `negotiation_status` moves `EXECUTED → LAPSED` — the deal is dead."

        PRD: "The contract's `collection_status` is set to `WRITTEN_OFF`."

        Design: Difficulty/transitive_cascade/final_qc_rejection_cascades_four_levels_from_package_to_margin_call
        """
        env = _final_rejection_environment(api)
        record_qc_fail(
            api, env["package_2"]["id"], env["buyer"]["id"], "TECHNICAL_INCOMPLETE"
        )

        contract = read_contract(api, env["contract"]["id"])
        assert_contract_axes(
            contract,
            negotiation="LAPSED",
            delivery="REJECTED",
            collection="WRITTEN_OFF",
        )

    def test_level_2_every_unpaid_milestone_is_written_off(self, api):
        """All four milestones of the dead contract move to the terminal written-off state and nothing unpaid remains.

        PRD: "Every payment milestone of that contract whose `status` is `SCHEDULED` or `INVOICED` moves to `WRITTEN_OFF`, and the contract's `unpaid_amount_usd` is recomputed from what remains; already-`RECEIVED` milestones are untouched, because cash actually collected is not clawed back."

        Design: Difficulty/transitive_cascade/final_qc_rejection_cascades_four_levels_from_package_to_margin_call
        """
        env = _final_rejection_environment(api)
        record_qc_fail(
            api, env["package_2"]["id"], env["buyer"]["id"], "TECHNICAL_INCOMPLETE"
        )

        milestones = read_milestones(api, env["contract"]["id"])
        assert len(milestones) == 4, f"expected four milestones, got {len(milestones)}"
        for label in ("ON_SIGNATURE", "ON_DELIVERY", "ON_RELEASE", "ON_TERM_END"):
            row = milestone_by_label(milestones, label)
            assert row["status"] == "WRITTEN_OFF", (
                f"{label} must be WRITTEN_OFF, got {row['status']}"
            )
        assert_money(
            read_contract(api, env["contract"]["id"])["unpaid_amount_usd"],
            0.00,
            "unpaid_amount_usd",
        )

    def test_level_3_the_territory_is_freed_and_the_picture_reopens_for_sale(self, api):
        """The licence returns to the sellable pool, the committed guarantee is undone and the picture falls back to IN_MARKET.

        PRD: "The `LICENSED` valuation for the film-and-territory pair returns to `PUBLISHED`, freeing the territory for resale."

        PRD: "Finally the picture's `total_mg_committed_usd`, `licensed_territory_count` and `financing_gap_usd` are all recomputed and its `version` increments, and the picture may auto-transition `SOLD_OUT → IN_MARKET` because its licensed count now sits below its published count."

        Design: Difficulty/transitive_cascade/final_qc_rejection_cascades_four_levels_from_package_to_margin_call
        """
        env = _final_rejection_environment(api)
        before = read_film(api, env["film"]["id"])
        assert_film_counters(
            before, sales_status="SOLD_OUT", committed=CONTRACT_MG, gap=22000000.00
        )

        record_qc_fail(
            api, env["package_2"]["id"], env["buyer"]["id"], "TECHNICAL_INCOMPLETE"
        )

        valuation = read_valuation(api, env["valuation"]["id"])
        assert valuation["status"] == "PUBLISHED", (
            f"expected the valuation back at PUBLISHED, got {valuation['status']}"
        )
        after = read_film(api, env["film"]["id"])
        assert_film_counters(
            after,
            sales_status="IN_MARKET",
            published_count=1,
            licensed_count=0,
            committed=0.00,
            gap=FILM_BUDGET,
        )

    def test_level_4_the_drawn_facility_trips_to_margin_call(self, api):
        """The written-off milestones empty the collateral pool, so the over-advanced facility moves off DRAWN while its drawn amount stands.

        PRD: "Because milestones were written off, every banking facility of the picture recomputes its `eligible_collateral_usd` and `advance_amount_usd`; any facility in `DRAWN` whose recomputed `advance_amount_usd` has fallen below its `drawn_amount_usd` moves `DRAWN → MARGIN_CALL`, and because a facility in `MARGIN_CALL` still counts as live, the picture's `BANK_DEBT` waterfall tier remains `ACTIVE` and keeps recouping."

        Design: Difficulty/transitive_cascade/final_qc_rejection_cascades_four_levels_from_package_to_margin_call
        """
        env = _final_rejection_environment(api)
        before = read_facility(api, env["film"]["id"], env["facility"]["id"])
        assert_facility_figures(
            before,
            status="DRAWN",
            collateral=FACILITY_COLLATERAL,
            advance=FACILITY_ADVANCE_BONDED,
            drawn=FACILITY_ADVANCE_BONDED,
        )

        record_qc_fail(
            api, env["package_2"]["id"], env["buyer"]["id"], "TECHNICAL_INCOMPLETE"
        )

        after = read_facility(api, env["film"]["id"], env["facility"]["id"])
        assert_facility_figures(
            after,
            status="MARGIN_CALL",
            collateral=0.00,
            advance=0.00,
            drawn=FACILITY_ADVANCE_BONDED,
            outstanding=FACILITY_ADVANCE_BONDED,
        )


# ==========================================================================
# The ledger cascade of a single receipt, and the distribution that follows it
# ==========================================================================
class TestReceiptLedgerCascade:
    def test_the_receipt_advances_the_contract_cash_axis_to_partially_paid(self, api):
        """Booking the signature milestone banks the cash and moves the cash axis without touching the other two.

        PRD: "A successful receipt sets the milestone's `status` to `RECEIVED`, writes `received_amount_usd` to the posted amount, writes `received_at` from the payload and `received_by_user_id` from `X-User-ID`."

        PRD: "`UNPAID → PARTIALLY_PAID` fires when, after the receipt, the contract's `received_amount_usd` is greater than zero **and** its `unpaid_amount_usd` is still greater than zero."

        Design: Difficulty/transitive_cascade/single_receipt_ledger_cascade_resyncs_commission_tier_cap_before_distribution
        """
        env = _ledger_cascade_environment(api)

        post_receipts(api, env, [FOUR_RECEIPT_DATES[0]])

        milestone = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        assert milestone["status"] == "RECEIVED", (
            f"expected the signature milestone RECEIVED, got {milestone['status']}"
        )
        assert_money(milestone["received_amount_usd"], 900000.00, "received_amount_usd")

        contract = read_contract(api, env["contract"]["id"])
        assert_contract_axes(contract, negotiation="EXECUTED", collection="PARTIALLY_PAID")
        assert_money(contract["received_amount_usd"], 900000.00, "received_amount_usd")
        assert_money(contract["unpaid_amount_usd"], 1100000.00, "unpaid_amount_usd")
        assert_account_counters(
            read_account(api, env["account"]["id"]),
            receipts=900000.00,
            distributed=0.00,
            balance=900000.00,
            run_count=0,
        )

    def test_the_receipt_accrues_commission_at_the_undiscounted_band(self, api):
        """The first cash of the picture arrives with a prior total of zero, so the whole receipt is charged at the unreduced rate.

        PRD: "When the prior total is below one million dollars, the rate is the agreement's `commission_pct` unchanged."

        PRD: "Step four, and only now: the agreement's `gross_collected_usd` becomes the prior total plus the posted amount, rounded to two decimal places, and its `commission_earned_usd` becomes its previous value plus the accrued commission, rounded to two decimal places."

        Design: Difficulty/transitive_cascade/single_receipt_ledger_cascade_resyncs_commission_tier_cap_before_distribution
        """
        env = _ledger_cascade_environment(api)

        post_receipts(api, env, [FOUR_RECEIPT_DATES[0]])

        milestone = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        assert_money(milestone["accrued_commission_usd"], 90000.00, "accrued_commission_usd")

        agreement = read_agreement(api, env["film"]["id"], env["agreement"]["id"])
        assert_money(agreement["gross_collected_usd"], 900000.00, "gross_collected_usd")
        assert_money(agreement["commission_earned_usd"], 90000.00, "commission_earned_usd")

    def test_the_receipt_resynchronises_the_commission_tier_ceiling(self, api):
        """The commission tier's ceiling is written by the receipt, not by the operator who created the tier.

        PRD: "The `SALES_COMMISSION` tier's `cap_usd` is set to the agreement's new `commission_earned_usd`."

        Design: Difficulty/transitive_cascade/single_receipt_ledger_cascade_resyncs_commission_tier_cap_before_distribution
        """
        env = _ledger_cascade_environment(api)

        post_receipts(api, env, [FOUR_RECEIPT_DATES[0]])

        commission_tier = find_by(
            read_tiers(api, env["account"]["id"]), tier_type="SALES_COMMISSION"
        )
        assert_tier(commission_tier, recouped=0.00, cap=90000.00, status="ACTIVE")

    def test_the_distribution_allocates_in_the_pinned_rounding_order(self, api):
        """The run walks both tiers in order, caps the commission tier at its resynchronised ceiling, and leaves the rest behind.

        PRD: "For an `ACTIVE` tier the rounding order is pinned. First compute the tier's target as the current remaining figure multiplied by the tier's `pct_of_available`, **rounded half-up to two decimal places immediately**. If the tier has a `cap_usd`, compute its remaining room as `cap_usd` less `recouped_usd`, rounded to two decimal places, and reduce the target to the lesser of the two."

        PRD: "`residual_usd` is `amount_in_usd` less `amount_allocated_usd`, rounded to two decimal places — cash that stayed behind because no uncapped `ACTIVE` tier could absorb it."

        Design: Difficulty/transitive_cascade/single_receipt_ledger_cascade_resyncs_commission_tier_cap_before_distribution
        """
        env = _ledger_cascade_environment(api)
        post_receipts(api, env, [FOUR_RECEIPT_DATES[0]])

        run = assert_created(
            api.distribute(
                env["account"]["id"],
                distribute_payload(100000.00),
                make_collection_agent_headers(),
            )
        )

        assert_allocations(run, [1250.00, 90000.00], tier_count=2)
        assert_money(run["amount_in_usd"], 100000.00, "amount_in_usd")
        assert_money(run["amount_allocated_usd"], 91250.00, "amount_allocated_usd")
        assert_money(run["residual_usd"], 8750.00, "residual_usd")
        assert run["run_index"] == 1, f"expected run_index 1, got {run['run_index']}"

    def test_the_run_satisfies_the_commission_tier_and_leaves_the_fee_tier_active(self, api):
        """The commission tier hits its resynchronised ceiling exactly and is derived SATISFIED, while the fee tier keeps recouping.

        PRD: "A tier is `SATISFIED` when its `cap_usd` is not null and its `recouped_usd` has reached or passed that cap."

        PRD: "The account's `total_distributed_usd` grows by `amount_allocated_usd`, its `balance_usd` is recomputed as `total_receipts_usd` less `total_distributed_usd` rounded to two decimal places, and its `run_count` increments by one."

        Design: Difficulty/transitive_cascade/single_receipt_ledger_cascade_resyncs_commission_tier_cap_before_distribution
        """
        env = _ledger_cascade_environment(api)
        post_receipts(api, env, [FOUR_RECEIPT_DATES[0]])
        assert_created(
            api.distribute(
                env["account"]["id"],
                distribute_payload(100000.00),
                make_collection_agent_headers(),
            )
        )

        tiers = read_tiers(api, env["account"]["id"])
        assert_tier(
            find_by(tiers, tier_type="COLLECTION_FEE"),
            recouped=1250.00,
            cap=25000.00,
            status="ACTIVE",
        )
        assert_tier(
            find_by(tiers, tier_type="SALES_COMMISSION"),
            recouped=90000.00,
            cap=90000.00,
            status="SATISFIED",
        )
        assert_account_counters(
            read_account(api, env["account"]["id"]),
            receipts=900000.00,
            distributed=91250.00,
            balance=808750.00,
            run_count=1,
        )


# ==========================================================================
# Precedence: the related-row state check outranks the fiscal credit gate
# ==========================================================================
class TestOfferStateCheckOutranksCreditGate:
    def test_the_picture_state_check_wins_and_the_credit_gate_is_never_evaluated(self, api):
        """An offer that both names a picture outside the selling window and blows the credit limit reports only the state failure.

        PRD: "When a request would fail several checks at once, exactly one error is returned: the highest-precedence failing check. All lower-precedence checks are skipped, and their conditions are never evaluated."

        PRD: "**Eighth, the state of a *related* row**, in this order: the film's `sales_status` being in the window the operation needs, else `ERR_FILM_NOT_IN_MARKET` (409); then the referenced market being `OPEN`, else `ERR_MARKET_NOT_OPEN` (409); then the film's collection account existing and being `OPEN`, else `ERR_COLLECTION_ACCOUNT_NOT_OPEN` (409)."

        PRD: "**Last, fiscal checks** in this order: gross buyer exposure (`ERR_BUYER_EXPOSURE_EXCEEDED`, 422), net buyer exposure (`ERR_BUYER_NET_EXPOSURE_EXCEEDED`, 422), minimum guarantee below floor (`ERR_MG_BELOW_FLOOR`, 422), receipt amount mismatch (`ERR_RECEIPT_AMOUNT_MISMATCH`, 422), insufficient account balance (`ERR_INSUFFICIENT_ACCOUNT_BALANCE`, 422), receipt already distributed (`ERR_RECEIPT_ALREADY_DISTRIBUTED`, 422), expense log limit (`ERR_EXPENSE_LOG_LIMIT`, 422)."

        PRD: "The picture's `sales_status` must be `IN_MARKET` or `SOLD_OUT`, else `ERR_FILM_NOT_IN_MARKET` — note this is a different window from the one market bookings require, and note in particular that a `SOLD_OUT` picture still accepts new offers, since a territory may reopen."

        Design: Difficulty/priority_pair_validation_conflict/film_not_in_market_state_check_outranks_buyer_exposure_fiscal_check_on_offer
        """
        env = _packaging_slate_with_published_valuation(api, 100000.00)
        buyer_before = read_buyer(api, env["buyer"]["id"])
        film_before = read_film(api, env["film"]["id"])
        assert film_before["sales_status"] == "PACKAGING", (
            f"the picture must still be PACKAGING, got {film_before['sales_status']}"
        )

        response = _replay_offer(api, env, buyer_before["version"])

        validate_error(response, "ERR_FILM_NOT_IN_MARKET", 409)
        assert _error_id(response) != "ERR_BUYER_EXPOSURE_EXCEEDED", (
            "the fiscal credit gate must not be evaluated once the related-row state "
            "check has already failed"
        )
        assert_empty_collection(api.list_contracts(make_sales_agent_headers(), LIST_ALL))
        buyer_after = read_buyer(api, env["buyer"]["id"])
        assert buyer_after["version"] == buyer_before["version"], (
            "a rejected offer must not move the buyer's version: expected "
            f"{buyer_before['version']}, got {buyer_after['version']}"
        )
        assert_buyer_exposure(buyer_after, gross=0.00, net=0.00)
        assert read_film(api, env["film"]["id"])["version"] == film_before["version"], (
            "a rejected offer must not move the picture's version"
        )

    def test_clearing_the_state_failure_lets_the_credit_gate_surface(self, api):
        """With the picture moved into the market, the identical offer is stopped by the credit limit instead.

        PRD: "The credit gate rejects with `ERR_BUYER_EXPOSURE_EXCEEDED` when the buyer's gross pipeline exposure plus the payload's `minimum_guarantee_usd` would exceed the buyer's `exposure_limit_usd`; landing exactly on the limit passes."

        Design: Difficulty/priority_pair_validation_conflict/film_not_in_market_state_check_outranks_buyer_exposure_fiscal_check_on_offer
        """
        env = _packaging_slate_with_published_valuation(api, 100000.00)
        env["film"] = assert_object_response(
            api.set_film_state(
                env["film"]["id"], state_payload("IN_MARKET"), make_head_of_sales_headers()
            )
        )
        buyer_before = read_buyer(api, env["buyer"]["id"])

        response = _replay_offer(api, env, buyer_before["version"])

        validate_error(response, "ERR_BUYER_EXPOSURE_EXCEEDED", 422)
        assert _error_id(response) != "ERR_FILM_NOT_IN_MARKET", (
            "the picture is IN_MARKET, so the state check must no longer fire"
        )
        assert_empty_collection(api.list_contracts(make_sales_agent_headers(), LIST_ALL))
        buyer_after = read_buyer(api, env["buyer"]["id"])
        assert buyer_after["version"] == buyer_before["version"], (
            "a rejected offer must not move the buyer's version"
        )
        assert_buyer_exposure(buyer_after, gross=0.00, net=0.00)

    def test_clearing_both_conditions_lets_the_offer_through(self, api):
        """Once the picture is in the market and the limit accommodates the guarantee, the same offer is accepted and books the exposure.

        PRD: "The credit gate rejects with `ERR_BUYER_EXPOSURE_EXCEEDED` when the buyer's gross pipeline exposure plus the payload's `minimum_guarantee_usd` would exceed the buyer's `exposure_limit_usd`; landing exactly on the limit passes."

        Design: Difficulty/priority_pair_validation_conflict/film_not_in_market_state_check_outranks_buyer_exposure_fiscal_check_on_offer
        """
        env = _packaging_slate_with_published_valuation(api, 100000.00)
        env["film"] = assert_object_response(
            api.set_film_state(
                env["film"]["id"], state_payload("IN_MARKET"), make_head_of_sales_headers()
            )
        )
        env["buyer"] = assert_object_response(
            api.patch_buyer(
                env["buyer"]["id"],
                buyer_amendment_payload(exposure_limit_usd=3000000.00),
                make_platform_admin_headers(),
            )
        )

        contract = assert_created(
            _replay_offer(api, env, read_buyer(api, env["buyer"]["id"])["version"])
        )

        assert_contract_axes(
            contract, negotiation="OFFERED", delivery="PENDING", collection="UNPAID"
        )
        assert_money(contract["minimum_guarantee_usd"], CONTRACT_MG, "minimum_guarantee_usd")
        assert_buyer_exposure(read_buyer(api, env["buyer"]["id"]), gross=CONTRACT_MG)


# ==========================================================================
# Precedence: the buyer-blocking safety check outranks the table conflict
# ==========================================================================
class TestMeetingSafetyCheckOutranksTableConflict:
    def test_the_blocking_check_wins_and_the_table_conflict_is_never_evaluated(self, api):
        """A meeting request that both names a blocked distributor and collides with an occupied table reports only the blocking failure.

        PRD: "When a request would fail several checks at once, exactly one error is returned: the highest-precedence failing check. All lower-precedence checks are skipped, and their conditions are never evaluated."

        PRD: "**Ninth, business safety** — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 403), then buyer blocking (`ERR_BUYER_BLOCKED`, 422), then the completion-bond requirement (`ERR_COMPLETION_BOND_REQUIRED`, 422)."

        PRD: "**Eleventh, temporal checks** in this order: screening-room conflict (`ERR_SCREENING_ROOM_CONFLICT`, 409), meeting conflict (`ERR_MEETING_SLOT_CONFLICT`, 409), containment in the market window (`ERR_OUTSIDE_MARKET_WINDOW`, 422), holdback elapsed (`ERR_HOLDBACK_NOT_ELAPSED`, 422), licence term expired (`ERR_LICENSE_TERM_NOT_EXPIRED`, 422), cure window still open (`ERR_CURE_WINDOW_ELAPSED`, 422)."

        PRD: "Meeting creation shares three gates with screening slots — the picture must be `PACKAGING` or `IN_MARKET` (`ERR_FILM_NOT_IN_MARKET`), the market must be `OPEN` (`ERR_MARKET_NOT_OPEN`), and the window must be contained in the market window (`ERR_OUTSIDE_MARKET_WINDOW`) — and adds one of its own: a buyer whose trading `status` is `BLOCKED` cannot be met, and the attempt is rejected with `ERR_BUYER_BLOCKED`."

        Design: Difficulty/priority_pair_validation_conflict/buyer_blocked_safety_check_outranks_meeting_table_temporal_conflict
        """
        env = _blocked_buyer_meeting_environment(api)
        assert env["buyer"]["status"] == "BLOCKED", (
            f"the distributor must be BLOCKED, got {env['buyer']['status']}"
        )

        response = _replay_meeting(api, env, 3)

        validate_error(response, "ERR_BUYER_BLOCKED", 422)
        assert _error_id(response) != "ERR_MEETING_SLOT_CONFLICT", (
            "the temporal table check must not be evaluated once the business-safety "
            "check has already failed"
        )
        rows, _meta = assert_list_response(
            api.list_buyer_meetings(make_sales_agent_headers(), LIST_ALL),
            expected_total=1,
            expected_rows=1,
        )
        assert rows[0]["id"] == env["meeting_nordic"]["id"], (
            "the rejected request must not have persisted a meeting row"
        )

    def test_clearing_the_blocking_condition_lets_the_table_conflict_surface(self, api):
        """With the distributor trading again, the identical request is stopped by the occupied table instead.

        PRD: "Overlap means the requested `start_at` falls strictly before the existing `end_at` and the existing `start_at` falls strictly before the requested `end_at`. Either failure returns `ERR_MEETING_SLOT_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/buyer_blocked_safety_check_outranks_meeting_table_temporal_conflict
        """
        env = _blocked_buyer_meeting_environment(api)
        env["buyer"] = assert_object_response(
            api.patch_buyer(
                env["buyer"]["id"],
                buyer_amendment_payload(status="ACTIVE"),
                make_platform_admin_headers(),
            )
        )

        response = _replay_meeting(api, env, 3)

        validate_error(response, "ERR_MEETING_SLOT_CONFLICT", 409)
        assert _error_id(response) != "ERR_BUYER_BLOCKED", (
            "the distributor is trading again, so the blocking check must no longer fire"
        )
        rows, _meta = assert_list_response(
            api.list_buyer_meetings(make_sales_agent_headers(), LIST_ALL),
            expected_total=1,
            expected_rows=1,
        )
        assert rows[0]["id"] == env["meeting_nordic"]["id"], (
            "the rejected request must not have persisted a meeting row"
        )

    def test_clearing_both_conditions_books_the_meeting_on_a_free_table(self, api):
        """The same window at a free table is booked, and the whole minutes between the two instants are computed.

        PRD: "The service computes `duration_minutes` as the whole minutes between the two instants, flooring any partial minute."

        PRD: "A new meeting's `status` is `SCHEDULED` and its `outcome` is null."

        Design: Difficulty/priority_pair_validation_conflict/buyer_blocked_safety_check_outranks_meeting_table_temporal_conflict
        """
        env = _blocked_buyer_meeting_environment(api)
        env["buyer"] = assert_object_response(
            api.patch_buyer(
                env["buyer"]["id"],
                buyer_amendment_payload(status="ACTIVE"),
                make_platform_admin_headers(),
            )
        )

        meeting = assert_created(_replay_meeting(api, env, 4))

        assert meeting["status"] == "SCHEDULED", (
            f"expected meeting status SCHEDULED, got {meeting['status']}"
        )
        assert meeting["outcome"] is None, (
            f"a new meeting carries no outcome, got {meeting['outcome']!r}"
        )
        assert meeting["table_number"] == 4, (
            f"expected table_number 4, got {meeting['table_number']}"
        )
        assert meeting["duration_minutes"] == 60, (
            f"expected duration_minutes 60, got {meeting['duration_minutes']}"
        )

        rows, _meta = assert_list_response(
            api.list_buyer_meetings(make_sales_agent_headers(), LIST_ALL),
            expected_total=2,
            expected_rows=2,
        )
        nordic = find_by(rows, id=env["meeting_nordic"]["id"])
        assert nordic["status"] == "SCHEDULED", (
            f"the existing meeting must be untouched, got {nordic['status']}"
        )
        assert nordic["table_number"] == 3, "the existing meeting must keep its table"
        assert nordic["duration_minutes"] == 90, (
            f"the existing meeting must keep its duration, got {nordic['duration_minutes']}"
        )


# ==========================================================================
# The negotiation loop: OFFERED -> COUNTERED -> OFFERED up to the round limit,
# while the delivery and collection axes advance on their own triggers
# ==========================================================================
class TestNegotiationRoundLoop:
    def test_a_new_offer_opens_the_loop_at_the_first_round(self, api):
        """A freshly opened offer starts the alternation at round one with all three axes at their initial values.

        PRD: "A newly created contract sits at `negotiation_status` `OFFERED`, `delivery_status` `PENDING` and `collection_status` `UNPAID`, with `negotiation_round` at 1, `milestone_pct_total` at 0.0000, `counter_minimum_guarantee_usd` null and `offered_by_user_id` recorded from `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycles_offer_counter_offer_until_round_limit_while_other_axes_hold
        """
        pin_clock(api, CLOCK_DEFAULT)
        env = offered_contract(api, minimum_guarantee_usd=NEGOTIATION_MG)

        contract = read_contract(api, env["contract"]["id"])
        assert_contract_axes(
            contract, negotiation="OFFERED", delivery="PENDING", collection="UNPAID"
        )
        assert contract["negotiation_round"] == 1, (
            f"a new offer opens at round 1, got {contract['negotiation_round']}"
        )
        assert contract["counter_minimum_guarantee_usd"] is None, (
            "a new offer carries no countered figure, got "
            f"{contract['counter_minimum_guarantee_usd']!r}"
        )
        assert_money(contract["minimum_guarantee_usd"], NEGOTIATION_MG, "minimum_guarantee_usd")

    def test_the_buyers_counter_stores_its_figure_and_leaves_the_agency_number_alone(self, api):
        """The buyer's counter advances the round and records the countered figure without overwriting the agency's guarantee.

        PRD: "The countered figure is stored in `counter_minimum_guarantee_usd` and the contract's own `minimum_guarantee_usd` is deliberately left untouched — the agency's number on the table does not change just because the buyer named a different one."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycles_offer_counter_offer_until_round_limit_while_other_axes_hold
        """
        env = _negotiation_environment(api)

        countered = assert_object_response(_counter(api, env, COUNTER_ONE_MG))

        assert_contract_axes(
            countered, negotiation="COUNTERED", delivery="PENDING", collection="UNPAID"
        )
        assert countered["negotiation_round"] == 2, (
            f"the first counter advances to round 2, got {countered['negotiation_round']}"
        )
        assert_money(
            countered["counter_minimum_guarantee_usd"],
            COUNTER_ONE_MG,
            "counter_minimum_guarantee_usd",
        )
        assert_money(
            countered["minimum_guarantee_usd"], NEGOTIATION_MG, "minimum_guarantee_usd"
        )

    def test_the_agency_answer_overwrites_the_guarantee_and_re_derives_every_milestone(self, api):
        """The agency's answer returns the deal to OFFERED, replaces the guarantee, clears the countered figure and recomputes all four milestone amounts.

        PRD: "This one is a real overwrite: `minimum_guarantee_usd` is replaced, the two optional fields are replaced when supplied, `counter_minimum_guarantee_usd` is cleared back to null, and every payment milestone already attached to the contract has its `amount_usd` recomputed as its own `pct_of_mg` times the new minimum guarantee, rounded half-up to two decimal places."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycles_offer_counter_offer_until_round_limit_while_other_axes_hold
        """
        env = _negotiation_environment(api)
        assert_object_response(_counter(api, env, COUNTER_ONE_MG))

        revised = assert_object_response(_revise(api, env, REVISED_MG))

        assert_contract_axes(
            revised, negotiation="OFFERED", delivery="PENDING", collection="UNPAID"
        )
        assert revised["negotiation_round"] == 3, (
            f"the first answer advances to round 3, got {revised['negotiation_round']}"
        )
        assert_money(revised["minimum_guarantee_usd"], REVISED_MG, "minimum_guarantee_usd")
        assert revised["counter_minimum_guarantee_usd"] is None, (
            "the countered figure must be cleared, got "
            f"{revised['counter_minimum_guarantee_usd']!r}"
        )
        assert_money(revised["unpaid_amount_usd"], REVISED_MG, "unpaid_amount_usd")
        assert revised["milestone_pct_total"] == 1.0, (
            f"the schedule shares must still total 1.0000, got {revised['milestone_pct_total']}"
        )

        milestones = read_milestones(api, env["contract"]["id"])
        for label, expected in zip(
            ("ON_SIGNATURE", "ON_DELIVERY", "ON_RELEASE", "ON_TERM_END"),
            REVISED_MILESTONE_AMOUNTS,
        ):
            assert_money(
                milestone_by_label(milestones, label)["amount_usd"],
                expected,
                f"{label} amount_usd",
            )

    def test_the_answer_at_the_round_limit_is_refused(self, api):
        """A second counter reaches the fourth round, and the agency's next answer is refused because the round is no longer strictly below the limit.

        PRD: "The alternation may repeat, but not indefinitely. Both countering and revising require that `negotiation_round` be strictly below 4 before they run; a fourth round is where the cycle stops, and an attempt to go past it is rejected with `ERR_NEGOTIATION_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycles_offer_counter_offer_until_round_limit_while_other_axes_hold
        """
        env = _negotiation_environment(api)
        assert_object_response(_counter(api, env, COUNTER_ONE_MG))
        assert_object_response(_revise(api, env, REVISED_MG))
        at_limit = assert_object_response(_counter(api, env, COUNTER_TWO_MG))
        assert at_limit["negotiation_round"] == MAX_NEGOTIATION_ROUNDS, (
            f"the second counter reaches round {MAX_NEGOTIATION_ROUNDS}, got "
            f"{at_limit['negotiation_round']}"
        )

        response = _revise(api, env, 1250000.00)

        validate_error(response, "ERR_NEGOTIATION_ROUND_LIMIT", 422)
        contract = read_contract(api, env["contract"]["id"])
        assert contract["negotiation_round"] == MAX_NEGOTIATION_ROUNDS, (
            "a refused answer must not advance the round, got "
            f"{contract['negotiation_round']}"
        )
        assert_contract_axes(
            contract, negotiation="COUNTERED", delivery="PENDING", collection="UNPAID"
        )
        assert_money(contract["minimum_guarantee_usd"], REVISED_MG, "minimum_guarantee_usd")
        assert_money(
            contract["counter_minimum_guarantee_usd"],
            COUNTER_TWO_MG,
            "counter_minimum_guarantee_usd",
        )

    def test_a_further_counter_at_the_round_limit_is_refused_on_the_state_axis(self, api):
        """A further counter is a repeated trigger on a row already COUNTERED, and the own-state guard outranks the round limit.

        The buyer's move is only ever legal out of `OFFERED`, and the alternation
        puts `OFFERED` at rounds 1 and 3 only, so the round limit can never be the
        reported failure on a counter: the fourth round is always `COUNTERED`, where
        the precedence ladder stops at the row's own state first.

        PRD: "Whether the row's own current status permits the requested transition, including a repeated trigger on a row already in the destination state or already in a terminal state, else `ERR_INVALID_STATE` (HTTP 409). This guard covers every state-driving operation in the system: the state endpoints on films, agency agreements, markets, screening slots, buyer meetings, banking facilities and collection accounts, plus countering, revising an offer, accepting, executing, lapsing, reverting, publishing, recording a quality-control verdict, posting a receipt, reversing a receipt, and posting a completion bond."

        PRD: "`OFFERED → COUNTERED` is the buyer's move and is reserved to the `Buyer` role acting as the contract's own buyer."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycles_offer_counter_offer_until_round_limit_while_other_axes_hold
        """
        env = _negotiation_environment(api)
        assert_object_response(_counter(api, env, COUNTER_ONE_MG))
        assert_object_response(_revise(api, env, REVISED_MG))
        assert_object_response(_counter(api, env, COUNTER_TWO_MG))

        response = _counter(api, env, 1240000.00)

        validate_error(response, "ERR_INVALID_STATE", 409)
        contract = read_contract(api, env["contract"]["id"])
        assert contract["negotiation_round"] == MAX_NEGOTIATION_ROUNDS, (
            "a refused counter must not advance the round, got "
            f"{contract['negotiation_round']}"
        )
        assert_contract_axes(contract, negotiation="COUNTERED")
        assert_money(
            contract["counter_minimum_guarantee_usd"],
            COUNTER_TWO_MG,
            "counter_minimum_guarantee_usd",
        )

    def test_the_three_axes_hold_independent_values_on_one_row(self, api):
        """A renegotiated deal is countersigned and part-paid, leaving the commercial, materials and cash axes at three unrelated values.

        PRD: "The three status axes on a contract are genuinely independent. `negotiation_status` tracks the commercial deal, `delivery_status` tracks the materials, and `collection_status` tracks the cash. A contract may be `EXECUTED` and `REJECTED` and `PARTIALLY_PAID` all at once; no axis constrains another's enumerated values, and each advances on its own triggers."

        PRD: "`UNPAID → PARTIALLY_PAID` fires when, after the receipt, the contract's `received_amount_usd` is greater than zero **and** its `unpaid_amount_usd` is still greater than zero."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycles_offer_counter_offer_until_round_limit_while_other_axes_hold
        """
        env = _negotiation_environment(api)
        assert_object_response(_counter(api, env, COUNTER_ONE_MG))
        assert_object_response(_revise(api, env, REVISED_MG))
        assert_money(
            read_valuation(api, env["valuation"]["id"])["floor_price_usd"],
            CA_FLOOR_DE,
            "floor_price_usd",
        )

        assert_object_response(
            api.accept_contract(env["contract"]["id"], make_buyer_headers(env["buyer"]["id"]))
        )
        executed = assert_object_response(
            api.execute_contract(
                env["contract"]["id"], make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
            )
        )
        assert_contract_axes(
            executed, negotiation="EXECUTED", delivery="PENDING", collection="UNPAID"
        )

        signature = milestone_by_label(
            read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE"
        )
        assert_money(signature["amount_usd"], REVISED_MILESTONE_AMOUNTS[0], "amount_usd")
        post_receipt(api, signature, SIGNATURE_RECEIPT_INSTANT)

        contract = read_contract(api, env["contract"]["id"])
        assert_contract_axes(
            contract,
            negotiation="EXECUTED",
            delivery="PENDING",
            collection="PARTIALLY_PAID",
        )
        assert_money(contract["received_amount_usd"], 576000.00, "received_amount_usd")
        assert_money(contract["unpaid_amount_usd"], 704000.00, "unpaid_amount_usd")
        assert contract["negotiation_round"] == 3, (
            "countersigning does not touch the negotiation round, got "
            f"{contract['negotiation_round']}"
        )
