"""Damage, tip-over and relocation charges: pricing, cascades and adjudication."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_charge_event,
    assert_instants_equal,
    fixtures as fx,
    make_customer_contact_headers,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SECOND_OFFICER = TEST_USERS["second_compliance_officer_headers"]

CLOCK_START = "2026-08-03T08:00:00Z"
CLOCK_START_CANONICAL = "2026-08-03T08:00:00.000Z"


def _deployed_portable(
    legal_name, site_label, authority_ref, authority_decision_ref,
    asset_tag="SP-0001", unit_class="STANDARD_PORTABLE", jurisdiction_code="CO-DN-CITY",
):
    """A mobilized 7-unit contract with exactly one unit DEPLOYED on an OPEN site."""
    return fx.setup_active_contract_with_deployment(
        shape=fx.SEVEN_UNIT,
        asset_tag=asset_tag,
        unit_class=unit_class,
        tare_length_ft=8,
        legal_name=legal_name,
        site_label=site_label,
        authority_ref=authority_ref,
        authority_decision_ref=authority_decision_ref,
        clock=CLOCK_START,
        site_overrides={
            "jurisdiction_code": jurisdiction_code,
            "access_class": "OPEN_LOT",
            "gate_open_minute": 360,
            "gate_close_minute": 1080,
            "max_truck_length_ft": 40,
        },
    )


class TestStrikeMultiplierSteps:
    """Four charges on one unit walk the prior-strike tiers 0, 1, 2 and 3."""

    def test_01_the_multiplier_steps_at_two_and_at_three_and_the_repair_hop_fires_once(self):
        """12800, 12800, 19200, 25600 — and IN_REPAIR arrives exactly on the third strike.

        PRD 3.8: "Read the unit's prior strike total as `damage_strikes` plus
        `tip_over_count` **before** the new charge is counted; a total of zero or one
        carries a 100 percent multiplier, a total of exactly two carries 150 percent, and
        a total of three or more carries 200 percent."
        PRD 3.8: "the severity factor is 40 percent for `MINOR`, 75 percent for
        `MODERATE` and 100 percent for `TOTAL_LOSS`."
        PRD 3.8: "If, after the charge is persisted, the sum of the two counters reaches
        three or more and the charge's `severity` is not `TOTAL_LOSS`, a unit in
        `DEPLOYED` moves `DEPLOYED → IN_REPAIR`, and `deployed_unit_count` is recomputed
        for the site of every deployment of that unit currently `DEPLOYED`."

        Design: Corner/calculations/strike_multiplier_steps_at_prior_strike_counts_one_two_and_three
        """
        env = _deployed_portable(
            "Marlstone Builders", "Marlstone Pad", "PL-9001", "AD-9001"
        )
        contract_id = env["contract"]["id"]
        asset_id = env["asset"]["id"]
        assert env["asset"]["status"] == "DEPLOYED"
        assert env["asset"]["damage_strikes"] == 0
        assert env["asset"]["tip_over_count"] == 0

        first = fx.assess_damage_charge(contract_id, asset_id, "MINOR")
        assert_charge_event(first)
        assert first["amount_cents"] == 12800
        unit = fx.read_asset_unit(asset_id)
        assert unit["damage_strikes"] == 1
        assert unit["status"] == "DEPLOYED"

        second = fx.assess_damage_charge(contract_id, asset_id, "MINOR")
        assert second["amount_cents"] == 12800
        unit = fx.read_asset_unit(asset_id)
        assert unit["damage_strikes"] == 2
        assert unit["status"] == "DEPLOYED"

        third = fx.assess_damage_charge(contract_id, asset_id, "MINOR")
        assert third["amount_cents"] == 19200
        unit = fx.read_asset_unit(asset_id)
        assert unit["damage_strikes"] == 3
        assert unit["status"] == "IN_REPAIR"

        fourth = fx.assess_damage_charge(contract_id, asset_id, "MINOR")
        assert fourth["amount_cents"] == 25600
        unit = fx.read_asset_unit(asset_id)
        assert unit["damage_strikes"] == 4
        assert unit["tip_over_count"] == 0
        assert unit["status"] == "IN_REPAIR"

        assert fx.read_deployment(env["deployment"]["id"])["state"] == "DEPLOYED"

        contract = fx.read_contract(contract_id)
        assert contract["charge_debits_cents"] == 70400
        assert contract["charge_debits_cents"] == 12800 + 12800 + 19200 + 25600


def _two_moderate_damage_charges_on_one_unit():
    """Two 24000-cent MODERATE charges by officer-1 against the same portable."""
    env = _deployed_portable(
        "Halyard Groundworks", "Halyard Bench", "PL-9101", "AD-9101",
        jurisdiction_code="UT-SL-CITY",
    )
    contract_id = env["contract"]["id"]
    asset_id = env["asset"]["id"]
    env["charge_one"] = fx.assess_damage_charge(
        contract_id, asset_id, "MODERATE", headers=OFFICER
    )
    env["charge_two"] = fx.assess_damage_charge(
        contract_id, asset_id, "MODERATE", headers=OFFICER
    )
    return env


class TestWaivingADamageCharge:
    """The waive must restore a physical strike counter, not just the money."""

    def test_02_the_waive_drops_the_strike_and_the_debit_by_exactly_one_charge(self):
        """Strikes fall 2 → 1, debits fall 48000 → 24000, and the amount itself survives.

        PRD 3.8: "The unit's `damage_strikes` and `tip_over_count` are recomputed — each
        counts the charges of its own kind against that unit whose `state` is `ASSESSED`
        or `UPHELD`, so a disputed or waived history does not inflate them."
        PRD 3.8: "then, only when the `charge_kind` is `DAMAGE` or `TIP_OVER`, the unit's
        `damage_strikes` and `tip_over_count` are recomputed, and if their sum falls back
        below three while the unit's `status` is `IN_REPAIR` the unit moves `IN_REPAIR →
        IN_YARD`."
        PRD 3.8: "Amounts are always non-negative, credits included: a credit's magnitude
        is positive and its sign is expressed by which ledger sum it feeds."

        Design: Difficulty/compensating_invariant/waiving_a_damage_charge_restores_the_asset_strike_count_exactly
        """
        env = _two_moderate_damage_charges_on_one_unit()
        assert env["charge_one"]["amount_cents"] == 24000
        assert env["charge_two"]["amount_cents"] == 24000
        assert env["charge_one"]["assessed_by_user_id"] == "officer-1"

        mid_unit = fx.read_asset_unit(env["asset"]["id"])
        assert mid_unit["damage_strikes"] == 2
        assert mid_unit["status"] == "DEPLOYED"
        assert fx.read_contract(env["contract"]["id"])["charge_debits_cents"] == 48000

        waived = fx.waive_charge(env["charge_two"]["id"], headers=SECOND_OFFICER)
        assert waived["state"] == "WAIVED"
        assert waived["resolved_by_user_id"] == "officer-2"
        assert waived["amount_cents"] == 24000

        post_unit = fx.read_asset_unit(env["asset"]["id"])
        assert post_unit["damage_strikes"] == 1
        assert post_unit["tip_over_count"] == 0
        assert post_unit["status"] == "DEPLOYED"

        contract = fx.read_contract(env["contract"]["id"])
        assert contract["charge_debits_cents"] == 24000
        assert contract["charge_debits_cents"] == env["charge_one"]["amount_cents"]

        assert fx.read_charge(env["charge_two"]["id"])["amount_cents"] == 24000

    def test_03_the_next_charge_prices_off_the_restored_counter(self):
        """A third MODERATE charge after the waive costs 24000, not 36000 or 48000.

        PRD 3.8: "Read the unit's prior strike total as `damage_strikes` plus
        `tip_over_count` **before** the new charge is counted; a total of zero or one
        carries a 100 percent multiplier, a total of exactly two carries 150 percent, and
        a total of three or more carries 200 percent."
        PRD 3.8: "The `amount_cents` is then the base multiplied by the severity factor,
        multiplied by the strike multiplier, divided by ten thousand — the two percentage
        factors applied to the exact product — and rounded half up to whole cents exactly
        once at the end."

        Design: Difficulty/compensating_invariant/waiving_a_damage_charge_restores_the_asset_strike_count_exactly
        """
        env = _two_moderate_damage_charges_on_one_unit()
        fx.waive_charge(env["charge_two"]["id"], headers=SECOND_OFFICER)
        assert fx.read_asset_unit(env["asset"]["id"])["damage_strikes"] == 1

        third = fx.assess_damage_charge(
            env["contract"]["id"], env["asset"]["id"], "MODERATE", headers=OFFICER
        )
        assert third["amount_cents"] == 24000
        assert third["amount_cents"] != 36000
        assert third["amount_cents"] != 48000

        unit = fx.read_asset_unit(env["asset"]["id"])
        assert unit["damage_strikes"] == 2
        assert unit["status"] == "DEPLOYED"
        assert fx.read_contract(env["contract"]["id"])["charge_debits_cents"] == 48000


def _relocation_charge_on_a_gated_destination():
    """A unit moved from an OPEN_LOT origin to a GATED annex of the same account."""
    fx.reposition_clock(CLOCK_START)
    account = fx.open_account(
        "Quarrywood Civil", account_type="CONSTRUCTION", credit_terms_days=30
    )
    origin = fx.register_site(
        account["id"], "Quarrywood Origin",
        jurisdiction_code="NV-CL-CITY", access_class="OPEN_LOT",
        right_of_way_required=False, gate_open_minute=360,
        gate_close_minute=1080, max_truck_length_ft=40,
    )
    destination = fx.register_site(
        account["id"], "Quarrywood Annex",
        jurisdiction_code="NV-CL-CITY", access_class="GATED",
        right_of_way_required=False, gate_open_minute=360,
        gate_close_minute=1080, max_truck_length_ft=40,
    )
    fx.approve_permit_for_site(
        origin["id"], authority_ref="PL-9201", authority_decision_ref="AD-9201"
    )
    fx.approve_permit_for_site(
        destination["id"], authority_ref="PL-9202", authority_decision_ref="AD-9202"
    )

    asset = fx.add_asset_unit("SP-901", unit_class="STANDARD_PORTABLE", tare_length_ft=8)
    contract = fx.raise_contract(account["id"], origin["id"])
    fx.quote_contract(contract)
    deployment = fx.commit_deployment(contract["id"], asset["id"])
    fx.mobilize_contract(contract["id"])

    fx.relocate_deployment(
        deployment["id"], destination["id"], "2026-08-05",
        relocation_reason="origin bench collapsed",
    )
    charges = fx.charges_for_contract(contract["id"], charge_kind="RELOCATION")
    assert len(charges) == 1
    return {
        "account": account,
        "origin": origin,
        "destination": destination,
        "asset": asset,
        "contract": fx.read_contract(contract["id"]),
        "deployment": fx.read_deployment(deployment["id"]),
        "charge": charges[0],
    }


class TestRelocationChargeLedgerRoundTrip:
    """DISPUTED leaves the debit input set; UPHELD puts the same figure back."""

    def test_04_disputing_then_upholding_returns_the_ledger_to_the_same_cent(self):
        """21275 leaves charge_debits_cents on dispute and returns unchanged on uphold.

        PRD 3.8: "Because both contract ledger sums admit only `ASSESSED` and `UPHELD`,
        the disputed amount leaves the input set: the contract's `charge_debits_cents` and
        `credit_accrued_cents` are recomputed and the relevant one drops by the charge's
        `amount_cents`, `net_billable_cents` follows"
        PRD 3.8: "From `DISPUTED → UPHELD`, the amount re-enters the input set, so the
        contract's `charge_debits_cents`, `credit_accrued_cents` and `net_billable_cents`
        are all recomputed and the relevant sum rises again by `amount_cents`, the
        account's `open_credit_balance_cents` and then `billing_hold` are recomputed, and
        an `INVOICED` contract flips to `REBILL_REQUIRED`."
        PRD 3.4: "Apply the destination's access-class multiplier — 100 percent for
        `OPEN_LOT`, 115 percent for `GATED`, 140 percent for `STAIR_ACCESS` and 225
        percent for `CRANE_ONLY`, since a crane pick costs us well over twice a flat-lot
        drop — by multiplying the base by that percentage, dividing by 100 and rounding
        half up to whole cents."

        Design: Corner/state_machines/disputing_a_relocation_charge_drops_it_from_the_contract_ledger_and_upholding_restores_it
        """
        env = _relocation_charge_on_a_gated_destination()

        assert env["deployment"]["state"] == "DEPLOYED"
        assert env["deployment"]["site_id"] == env["destination"]["id"]
        assert env["deployment"]["relocation_count"] == 1

        charge = env["charge"]
        assert charge["charge_kind"] == "RELOCATION"
        assert charge["amount_cents"] == 21275
        assert charge["state"] == "ASSESSED"
        assert charge["assessed_by_user_id"] == "planner-1"

        assert env["contract"]["charge_debits_cents"] == 21275
        assert env["contract"]["net_billable_cents"] == 21275

        disputed = fx.dispute_charge(
            charge["id"], env["account"]["id"],
            dispute_reason="the annex gate was our own crew's fault",
        )
        assert disputed["state"] == "DISPUTED"
        assert disputed["amount_cents"] == 21275

        mid = fx.read_contract(env["contract"]["id"])
        assert mid["charge_debits_cents"] == 0
        assert mid["net_billable_cents"] == 0
        assert mid["billing_state"] == "UNBILLED"

        upheld = fx.uphold_charge(charge["id"], headers=SECOND_OFFICER)
        assert upheld["state"] == "UPHELD"
        assert upheld["resolved_by_user_id"] == "officer-2"
        assert upheld["amount_cents"] == 21275

        after = fx.read_contract(env["contract"]["id"])
        assert after["charge_debits_cents"] == 21275
        assert after["net_billable_cents"] == 21275

        account = fx.read_account(env["account"]["id"])
        assert account["open_credit_balance_cents"] == 0
        assert account["billing_hold"] is False


class TestTotalLossCascade:
    """TOTAL_LOSS retires the iron outright and returns the live deployment with it."""

    def test_05_a_total_loss_charge_retires_the_unit_on_its_very_first_strike(self):
        """One strike, yet RETIRED rather than IN_REPAIR, and the deployment goes RETURNED.

        PRD 3.8: "A `DAMAGE` charge with `severity` `TOTAL_LOSS`, by contrast, takes a
        `DEPLOYED` unit straight to `RETIRED` — a terminal state — and drags every
        deployment of that unit in `RESERVED` or `DEPLOYED` to `RETURNED`, recomputing
        `deployed_unit_count` for each affected site."
        PRD 3.8: "For a `DAMAGE` charge, the base is the unit's class replacement basis —
        32000 cents for a `STANDARD_PORTABLE`, 48000 for an `ADA_PORTABLE`, 19000 for a
        `HANDWASH_STATION`, 145000 for a `TRAILER_2STALL` and 390000 for a
        `TRAILER_8STALL` — and the severity factor is 40 percent for `MINOR`, 75 percent
        for `MODERATE` and 100 percent for `TOTAL_LOSS`."
        PRD 3.8: "A new charge lands in `state` `ASSESSED` with `assessed_by_user_id` set
        to the acting `X-User-ID`, `assessed_at` set to the logical clock's current
        instant, `resolved_by_user_id` null, `dispute_reason` null, `resolution_note` null
        and `source_visit_id` null"

        Design: Corner/state_machines/total_loss_damage_retires_the_unit_and_returns_only_its_live_deployment
        """
        env = _deployed_portable(
            "Beltwood Sanitation", "Beltwood Verge", "PL-9401", "AD-9401",
            asset_tag="AP-901", unit_class="ADA_PORTABLE",
            jurisdiction_code="AZ-MA-CITY",
        )
        assert env["contract"]["fulfillment_state"] == "ACTIVE"
        assert env["asset"]["damage_strikes"] == 0
        assert env["asset"]["tip_over_count"] == 0
        assert env["site"]["deployed_unit_count"] == 1

        charge = fx.assess_damage_charge(
            env["contract"]["id"], env["asset"]["id"], "TOTAL_LOSS", headers=OFFICER
        )
        assert charge["amount_cents"] == 48000
        assert charge["state"] == "ASSESSED"
        assert charge["severity"] == "TOTAL_LOSS"
        assert charge["resolved_by_user_id"] is None
        assert charge["source_visit_id"] is None
        assert_instants_equal(
            charge["assessed_at"], CLOCK_START_CANONICAL, "ChargeEvent.assessed_at"
        )

        unit = fx.read_asset_unit(env["asset"]["id"])
        assert unit["status"] == "RETIRED"
        assert unit["status"] != "IN_REPAIR"
        assert unit["damage_strikes"] == 1
        assert unit["tip_over_count"] == 0

        assert fx.read_deployment(env["deployment"]["id"])["state"] == "RETURNED"

        site = fx.read_site(env["site"]["id"])
        assert site["deployed_unit_count"] == 0
        assert site["site_posture"] == "OPEN"

        contract = fx.read_contract(env["contract"]["id"])
        assert contract["charge_debits_cents"] == 48000
        assert contract["net_billable_cents"] == 48000
        assert contract["fulfillment_state"] == "ACTIVE"


class TestTipOverRestrictsTheSite:
    """An open tip-over restricts fully-permitted ground; adjudication releases it."""

    def test_06_the_tip_over_restricts_the_site_and_upholding_reopens_it(self):
        """Posture goes OPEN → RESTRICTED → OPEN while the permit stays APPROVED throughout.

        PRD 2.5: "Otherwise the service checks whether any open tip-over exists at the
        site — that is, whether there exists a charge event whose `charge_kind` is
        `TIP_OVER`, whose `state` is either `ASSESSED` or `DISPUTED`, and whose contract's
        `site_id` is this site; if one does, `site_posture` is `RESTRICTED`."
        PRD 2.5: "Tip-over charges in `UPHELD` or `WAIVED` never restrict a site:
        adjudication, in either direction, releases the operational restriction."
        PRD 3.8: "For a `TIP_OVER` charge, the base is a flat 27500 cents and the severity
        factor is a fixed 100 percent, because severity is neither accepted nor consulted
        for tip-overs."

        Design: Corner/state_machines/an_open_tip_over_restricts_the_site_and_upholding_it_releases_the_restriction
        """
        env = fx.setup_placeable_site(
            legal_name="Alderway Utilities",
            site_label="Alderway Verge",
            authority_ref="PL-9301",
            authority_decision_ref="AD-9301",
            clock=CLOCK_START,
            site_overrides={
                "jurisdiction_code": "OR-MU-CITY",
                "access_class": "OPEN_LOT",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
        )
        assert env["permit"]["status"] == "APPROVED"
        assert env["site"]["permit_status"] == "APPROVED"
        assert env["site"]["site_posture"] == "OPEN"

        asset = fx.add_asset_unit("SP-911", tare_length_ft=8)
        contract_a = fx.raise_contract(env["account"]["id"], env["site"]["id"])
        fx.quote_contract(contract_a)
        fx.commit_deployment(contract_a["id"], asset["id"])
        fx.mobilize_contract(contract_a["id"])

        contract_b = fx.raise_contract(env["account"]["id"], env["site"]["id"])
        quoted_b = fx.quote_contract(contract_b)
        assert quoted_b["fulfillment_state"] == "QUOTED"

        tip_over = fx.assess_tip_over_charge(
            contract_a["id"], asset["id"], headers=OFFICER
        )
        assert tip_over["charge_kind"] == "TIP_OVER"
        assert tip_over["amount_cents"] == 27500
        assert tip_over["severity"] is None
        assert tip_over["state"] == "ASSESSED"

        restricted = fx.read_site(env["site"]["id"])
        assert restricted["site_posture"] == "RESTRICTED"
        assert restricted["permit_status"] == "APPROVED"

        validate_error(
            api_client.activate_rental_contract(contract_b["id"], SALES),
            "ERR_SITE_POSTURE_RESTRICTED",
            409,
        )

        upheld = fx.uphold_charge(tip_over["id"], headers=SECOND_OFFICER)
        assert upheld["state"] == "UPHELD"

        reopened = fx.read_site(env["site"]["id"])
        assert reopened["site_posture"] == "OPEN"
        assert reopened["permit_status"] == "APPROVED"

        activated = validate_success(
            api_client.activate_rental_contract(contract_b["id"], SALES)
        )
        assert activated["fulfillment_state"] == "ACTIVE"


class TestDisputeWindow:
    """The fourteen-day deadline is an inclusive instant, not a calendar date."""

    def test_07_the_deadline_instant_is_accepted_and_one_millisecond_later_is_not(self):
        """Twin charges: one disputed at exactly assessed_at + 14 days, one 1 ms too late.

        PRD 3.8: "The customer's remedy is to dispute, which advances `ASSESSED →
        DISPUTED`."
        PRD 3.8: "and only within the window: the logical clock's current instant must be
        no later than the charge's `assessed_at` plus fourteen days, and a later attempt is
        refused with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 409)."
        PRD 2.4: "Where a rule compares an instant — the dispute window is the only such
        rule — the comparison is performed at full instant precision."

        Design: Corner/validations/dispute_filed_after_the_fourteen_day_window_is_refused
        """
        env = _two_moderate_damage_charges_on_one_unit()
        charge_one = env["charge_one"]
        charge_two = env["charge_two"]
        assert charge_one["amount_cents"] == 24000
        assert charge_two["amount_cents"] == 24000
        assert_instants_equal(
            charge_one["assessed_at"], CLOCK_START_CANONICAL, "charge_one.assessed_at"
        )
        assert_instants_equal(
            charge_two["assessed_at"], CLOCK_START_CANONICAL, "charge_two.assessed_at"
        )

        at_deadline = fx.reposition_clock("2026-08-17T08:00:00Z")
        assert_instants_equal(
            at_deadline["current_utc"], "2026-08-17T08:00:00.000Z", "clock.current_utc"
        )

        disputed = fx.dispute_charge(
            charge_one["id"], env["account"]["id"],
            dispute_reason="the unit was already damaged on delivery",
        )
        assert disputed["state"] == "DISPUTED"

        past_deadline = fx.reposition_clock("2026-08-17T08:00:00.001Z")
        assert_instants_equal(
            past_deadline["current_utc"],
            "2026-08-17T08:00:00.001Z",
            "clock.current_utc",
        )

        validate_error(
            api_client.dispute_charge_event(
                charge_two["id"],
                {"dispute_reason": "the unit was already damaged on delivery"},
                make_customer_contact_headers(env["account"]["id"]),
            ),
            "ERR_DISPUTE_WINDOW_CLOSED",
            409,
        )

        untouched = fx.read_charge(charge_two["id"])
        assert untouched["state"] == "ASSESSED"
        assert untouched["dispute_reason"] is None

        assert fx.read_contract(env["contract"]["id"])["charge_debits_cents"] == 24000
