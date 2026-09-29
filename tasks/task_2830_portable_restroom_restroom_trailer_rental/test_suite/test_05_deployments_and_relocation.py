"""Unit deployments: interval occupation, activation gates and relocation pricing."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_unit_deployment,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]


def _deployments_for_asset(asset_unit_id):
    rows, meta = validate_paginated(
        api_client.list_unit_deployments(PLANNER, {"asset_unit_id": asset_unit_id})
    )
    return rows, meta


class TestDeploymentReservation:
    """What a reservation writes, and how its date interval occupies the unit."""

    def test_01_deployed_unit_count_only_counts_deployments_in_deployed(self):
        """The site count stays 0 while the deployment is RESERVED and becomes 1 on activation.

        PRD 3.4: "A new commitment lands in `state` `RESERVED` with `relocation_count`
        of 0, and its `site_id` is seeded from the contract's own `site_id` rather than
        supplied by the client."
        PRD 3.4: "When those gates clear, every deployment on the contract sitting in
        `RESERVED` transitions `RESERVED → DEPLOYED` in `created_at` ascending order,
        and each such transition drags its asset unit from `IN_YARD` to `DEPLOYED`."
        PRD 3.4: "The contract's site then has its `deployed_unit_count` recomputed —
        that field is simply the number of deployments whose `site_id` is the site and
        whose `state` is `DEPLOYED`."

        Design: Corner/entities/service_site_deployed_unit_count_is_derived_from_deployment_state
        """
        env = fx.setup_quoted_contract(
            shape=fx.SEVEN_UNIT,
            legal_name="Stonegate Builders",
            site_label="Stonegate Pad 1",
            authority_ref="PL-9101",
            authority_decision_ref="AD-9101",
            site_overrides={"jurisdiction_code": "NC-WA-CITY"},
        )
        assert env["contract"]["quoted_cents"] == 91500

        asset = fx.add_asset_unit("SP-311", yard_code="YD-3")
        assert asset["status"] == "IN_YARD"

        deployment = fx.commit_deployment(env["contract"]["id"], asset["id"])
        assert_unit_deployment(deployment)
        assert deployment["state"] == "RESERVED"
        assert deployment["site_id"] == env["site"]["id"]
        assert deployment["relocation_count"] == 0
        assert fx.read_site(env["site"]["id"])["deployed_unit_count"] == 0

        activated = fx.mobilize_contract(env["contract"]["id"])
        assert activated["fulfillment_state"] == "ACTIVE"

        assert fx.read_site(env["site"]["id"])["deployed_unit_count"] == 1
        assert fx.read_deployment(deployment["id"])["state"] == "DEPLOYED"
        assert fx.read_asset_unit(asset["id"])["status"] == "DEPLOYED"

    def test_02_sharing_a_single_endpoint_date_double_books_the_unit(self):
        """Closed inclusive intervals: a booking that touches either end is refused.

        PRD 3.4: "Occupation is evaluated on closed inclusive dates with no buffer: the
        candidate set is every deployment of the same `asset_unit_id` whose `state` is
        `RESERVED` or `DEPLOYED`, and the new interval conflicts with a candidate when
        the new `deploy_from` is on or before the candidate's `deploy_to` **and** the
        candidate's `deploy_from` is on or before the new `deploy_to`, compared as
        `YYYY-MM-DD` strings."
        PRD 3.4: "Sharing a single endpoint date is therefore a conflict — a unit coming
        off one job on the 14th cannot start another on the 14th — while a one-day gap
        is clear."

        Design: Difficulty/resource_temporal_overlap/asset_deployment_dates_use_closed_inclusive_intervals_with_no_buffer
        """
        env = fx.setup_quoted_contract(
            shape=fx.SEVEN_UNIT,
            legal_name="Granite Ridge Homes",
            site_label="Granite Ridge Lot 12",
            authority_ref="PL-8601",
            authority_decision_ref="AD-8601",
            site_overrides={"jurisdiction_code": "UT-SL-CITY"},
            permit_overrides={"effective_from": "2026-07-01"},
            contract_overrides={"term_start": "2026-07-01", "term_end": "2026-09-30"},
        )
        asset = fx.add_asset_unit("SP-901", yard_code="YD-4", tare_length_ft=8)
        incumbent = fx.commit_deployment(
            env["contract"]["id"], asset["id"], "2026-08-03", "2026-08-10"
        )
        assert incumbent["state"] == "RESERVED"

        validate_error(
            api_client.create_unit_deployment(
                {
                    "contract_id": env["contract"]["id"],
                    "asset_unit_id": asset["id"],
                    "deploy_from": "2026-08-10",
                    "deploy_to": "2026-08-17",
                },
                PLANNER,
            ),
            "ERR_UNIT_DOUBLE_BOOKED",
            409,
        )
        validate_error(
            api_client.create_unit_deployment(
                {
                    "contract_id": env["contract"]["id"],
                    "asset_unit_id": asset["id"],
                    "deploy_from": "2026-07-27",
                    "deploy_to": "2026-08-03",
                },
                PLANNER,
            ),
            "ERR_UNIT_DOUBLE_BOOKED",
            409,
        )

        rows, meta = _deployments_for_asset(asset["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == incumbent["id"]

    def test_03_one_clear_day_is_enough_because_no_buffer_applies(self):
        """A booking starting the day after the incumbent ends is accepted on both sides.

        PRD 3.4: "Occupation is evaluated on closed inclusive dates with no buffer: the
        candidate set is every deployment of the same `asset_unit_id` whose `state` is
        `RESERVED` or `DEPLOYED`, and the new interval conflicts with a candidate when
        the new `deploy_from` is on or before the candidate's `deploy_to` **and** the
        candidate's `deploy_from` is on or before the new `deploy_to`, compared as
        `YYYY-MM-DD` strings."
        PRD 3.4: "Sharing a single endpoint date is therefore a conflict — a unit coming
        off one job on the 14th cannot start another on the 14th — while a one-day gap
        is clear."

        Design: Difficulty/resource_temporal_overlap/asset_deployment_dates_use_closed_inclusive_intervals_with_no_buffer
        """
        env = fx.setup_quoted_contract(
            shape=fx.SEVEN_UNIT,
            legal_name="Granite Ridge Homes",
            site_label="Granite Ridge Lot 12",
            authority_ref="PL-8601",
            authority_decision_ref="AD-8601",
            site_overrides={"jurisdiction_code": "UT-SL-CITY"},
            permit_overrides={"effective_from": "2026-07-01"},
            contract_overrides={"term_start": "2026-07-01", "term_end": "2026-09-30"},
        )
        asset = fx.add_asset_unit("SP-901", yard_code="YD-4", tare_length_ft=8)
        fx.commit_deployment(
            env["contract"]["id"], asset["id"], "2026-08-03", "2026-08-10"
        )

        after = validate_success(
            api_client.create_unit_deployment(
                {
                    "contract_id": env["contract"]["id"],
                    "asset_unit_id": asset["id"],
                    "deploy_from": "2026-08-11",
                    "deploy_to": "2026-08-17",
                },
                PLANNER,
            ),
            201,
        )
        assert after["state"] == "RESERVED"

        before = validate_success(
            api_client.create_unit_deployment(
                {
                    "contract_id": env["contract"]["id"],
                    "asset_unit_id": asset["id"],
                    "deploy_from": "2026-07-27",
                    "deploy_to": "2026-08-02",
                },
                PLANNER,
            ),
            201,
        )
        assert before["state"] == "RESERVED"

        rows, meta = _deployments_for_asset(asset["id"])
        assert meta["total_count"] == 3
        assert all(row["state"] == "RESERVED" for row in rows)


def _one_account_two_sites_and_one_oversized_trailer():
    """Two OPEN sites of one account, 40 ft and 24 ft, plus a 34 ft trailer."""
    fx.reposition_clock("2026-08-03T08:00:00Z")
    account = fx.open_account(
        "Summit Event Group", account_type="EVENT", credit_terms_days=15
    )
    wide = fx.register_site(
        account["id"],
        "Summit Main Lot",
        jurisdiction_code="NV-CC-CITY",
        access_class="OPEN_LOT",
        gate_open_minute=360,
        gate_close_minute=1200,
        max_truck_length_ft=40,
    )
    fx.approve_permit_for_site(
        wide["id"], authority_ref="PL-8101", authority_decision_ref="AD-8101"
    )
    narrow = fx.register_site(
        account["id"],
        "Summit Alley Annex",
        jurisdiction_code="NV-CC-CITY",
        access_class="GATED",
        gate_open_minute=360,
        gate_close_minute=1200,
        max_truck_length_ft=24,
    )
    narrow_permit = fx.approve_permit_for_site(
        narrow["id"], authority_ref="PL-8102", authority_decision_ref="AD-8102"
    )
    assert narrow_permit["status"] == "APPROVED"

    asset = fx.add_asset_unit(
        "TR2-501", unit_class="TRAILER_2STALL", yard_code="YD-9", tare_length_ft=34
    )
    contract_wide = fx.quote_contract(
        fx.raise_contract(
            account["id"], wide["id"], term_start="2026-08-01", term_end="2026-09-30"
        )
    )
    contract_narrow = fx.quote_contract(
        fx.raise_contract(
            account["id"], narrow["id"], term_start="2026-08-01", term_end="2026-09-30"
        )
    )
    return {
        "account": account,
        "wide": fx.read_site(wide["id"]),
        "narrow": fx.read_site(narrow["id"]),
        "asset": asset,
        "contract_wide": contract_wide,
        "contract_narrow": contract_narrow,
    }


class TestDeploymentValidationPriority:
    """Physical fit is checked before calendar occupation on one request."""

    def test_04_an_oversized_and_double_booked_unit_reports_the_fit_failure(self):
        """Both rules are violated at once and the access failure is the only one reported.

        PRD 2.11: "When several rules could reject the same request, the outcome is
        fully determined: the service evaluates checks in the fixed order below and
        returns the first failure it finds."
        PRD 2.11: "15. Physical access feasibility of the unit against the site —
        `ERR_SITE_ACCESS_INFEASIBLE`."
        PRD 2.11: "18. Asset date-interval occupation — `ERR_UNIT_DOUBLE_BOOKED`."

        Design: Difficulty/priority_pair_validation_conflict/deployment_prefers_access_infeasible_over_unit_double_booked
        """
        env = _one_account_two_sites_and_one_oversized_trailer()
        assert env["wide"]["site_posture"] == "OPEN"
        assert env["narrow"]["site_posture"] == "OPEN"
        assert env["asset"]["tare_length_ft"] == 34
        assert env["narrow"]["max_truck_length_ft"] == 24

        incumbent = fx.commit_deployment(
            env["contract_wide"]["id"], env["asset"]["id"], "2026-08-03", "2026-08-10"
        )
        assert incumbent["state"] == "RESERVED"

        response = api_client.create_unit_deployment(
            {
                "contract_id": env["contract_narrow"]["id"],
                "asset_unit_id": env["asset"]["id"],
                "deploy_from": "2026-08-05",
                "deploy_to": "2026-08-12",
            },
            PLANNER,
        )
        body = validate_error(response, "ERR_SITE_ACCESS_INFEASIBLE", 422)
        assert body["error_id"] != "ERR_UNIT_DOUBLE_BOOKED"

        rows, meta = _deployments_for_asset(env["asset"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == incumbent["id"]

    def test_05_each_of_the_two_rules_fires_alone_when_only_it_is_violated(self):
        """Controls: a clear window still fails on fit, and the wide site still fails on dates.

        PRD 3.4: "The iron must physically fit: the unit's `tare_length_ft` must be
        less than or equal to the site's `max_truck_length_ft`, and a longer unit is
        rejected with `ERR_SITE_ACCESS_INFEASIBLE` (HTTP 422)."
        PRD 3.4: "And the unit must actually be free for the whole interval."
        PRD 3.4: "A conflict is rejected with `ERR_UNIT_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/deployment_prefers_access_infeasible_over_unit_double_booked
        """
        env = _one_account_two_sites_and_one_oversized_trailer()
        incumbent = fx.commit_deployment(
            env["contract_wide"]["id"], env["asset"]["id"], "2026-08-03", "2026-08-10"
        )

        validate_error(
            api_client.create_unit_deployment(
                {
                    "contract_id": env["contract_narrow"]["id"],
                    "asset_unit_id": env["asset"]["id"],
                    "deploy_from": "2026-09-01",
                    "deploy_to": "2026-09-05",
                },
                PLANNER,
            ),
            "ERR_SITE_ACCESS_INFEASIBLE",
            422,
        )
        validate_error(
            api_client.create_unit_deployment(
                {
                    "contract_id": env["contract_wide"]["id"],
                    "asset_unit_id": env["asset"]["id"],
                    "deploy_from": "2026-08-05",
                    "deploy_to": "2026-08-12",
                },
                PLANNER,
            ),
            "ERR_UNIT_DOUBLE_BOOKED",
            409,
        )

        rows, meta = _deployments_for_asset(env["asset"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == incumbent["id"]
        assert rows[0]["state"] == "RESERVED"


class TestMobilizationGates:
    """The four gates on QUOTED to ACTIVE, and which one speaks first."""

    def test_06_activation_waits_for_the_permit_decision_then_succeeds_unchanged(self):
        """A SUBMITTED filing makes the site RESTRICTED; approving it lets the same call through.

        PRD 2.5: "Otherwise, if `permit_status` is `NONE` or `PENDING`, `site_posture`
        is `RESTRICTED`."
        PRD 2.5: "a `DRAFT` filing and a `SUBMITTED` filing both contribute `PENDING`"
        PRD 3.4: "The contract's site must have a `site_posture` of exactly `OPEN`: a
        `BLOCKED` site yields `ERR_SITE_POSTURE_BLOCKED` and a `RESTRICTED` site yields
        `ERR_SITE_POSTURE_RESTRICTED`."

        Design: Corner/validations/activating_against_a_pending_permit_is_refused_until_the_permit_is_approved
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account("Windlass Sitework", credit_terms_days=30)
        site = fx.register_site(
            account["id"],
            "Windlass Grade",
            jurisdiction_code="AL-JE-CITY",
            access_class="OPEN_LOT",
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        permit = fx.file_permit(site["id"], authority_ref="PL-11301")
        submitted = fx.submit_permit(permit["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["revision_round"] == 1

        contract = fx.quote_contract(fx.raise_contract(account["id"], site["id"]))
        assert contract["fulfillment_state"] == "QUOTED"

        pending_site = fx.read_site(site["id"])
        assert pending_site["permit_status"] == "PENDING"
        assert pending_site["site_posture"] == "RESTRICTED"

        body = validate_error(
            api_client.activate_rental_contract(contract["id"], SALES),
            "ERR_SITE_POSTURE_RESTRICTED",
            409,
        )
        assert body["error_id"] != "ERR_SITE_POSTURE_BLOCKED"

        fx.approve_permit(permit["id"], "AD-11301")
        assert fx.read_site(site["id"])["site_posture"] == "OPEN"

        activated = validate_success(
            api_client.activate_rental_contract(contract["id"], SALES)
        )
        assert activated["fulfillment_state"] == "ACTIVE"

    def test_07_activation_on_a_suspended_account_is_a_state_transition_failure(self):
        """Posture OPEN and no hold, so the account standing is the only possible refusal.

        PRD 3.1: "Account standing is recorded in `status`, one of `ACTIVE` or
        `SUSPENDED`; it may be supplied at creation, defaults to `ACTIVE`, and has no
        transition endpoint of its own."
        PRD 3.4: "The owning account's `status` must be `ACTIVE`; a `SUSPENDED` account
        is not a state from which mobilization is declared, so the attempt is rejected
        with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/activation_on_a_suspended_account_is_refused
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Hazelmere Holdings", credit_terms_days=30, status="SUSPENDED"
        )
        assert account["status"] == "SUSPENDED"
        assert account["billing_hold"] is False

        site = fx.register_site(
            account["id"],
            "Hazelmere Yard",
            jurisdiction_code="KY-JE-CITY",
            access_class="OPEN_LOT",
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        fx.approve_permit_for_site(
            site["id"], authority_ref="PL-11501", authority_decision_ref="AD-11501"
        )
        assert fx.read_site(site["id"])["site_posture"] == "OPEN"

        contract = fx.quote_contract(fx.raise_contract(account["id"], site["id"]))
        assert contract["fulfillment_state"] == "QUOTED"

        validate_error(
            api_client.activate_rental_contract(contract["id"], SALES),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        assert fx.read_contract(contract["id"])["fulfillment_state"] == "QUOTED"

    def test_08_a_blocked_site_on_a_held_account_reports_the_posture_failure(self):
        """Both the posture rule and the fiscal rule are violated; only the posture surfaces.

        PRD 2.11: "And an account on billing hold is reported before the disposal cap
        and the dispute window but after every posture, access and capacity check, so a
        mobilization attempt against a blocked site on a held account reports
        `ERR_SITE_POSTURE_BLOCKED`."
        PRD 2.11: "11. Governing site posture not `BLOCKED` —
        `ERR_SITE_POSTURE_BLOCKED`."
        PRD 2.11: "23. Account billing hold — `ERR_ACCOUNT_BILLING_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/activate_prefers_site_posture_blocked_over_account_billing_hold
        """
        env = fx.setup_missed_visit_credit(
            invoice_first=True,
            legal_name="Northgate Contractors",
            site_label="Northgate Block A",
            authority_ref="PL-8001",
            authority_decision_ref="AD-8001",
            site_overrides={
                "jurisdiction_code": "OR-PO-CITY",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
            route_code="RT-MON-22",
        )
        assert env["account"]["open_credit_balance_cents"] == 62413
        assert env["account"]["billing_hold"] is True

        blocked_site = fx.register_site(
            env["account"]["id"],
            "Northgate Block B",
            jurisdiction_code="OR-PO-CITY",
            access_class="OPEN_LOT",
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        rejected = fx.file_permit(blocked_site["id"], authority_ref="PL-8002")
        fx.submit_permit(rejected["id"])
        fx.reject_permit(rejected["id"], "AD-8002", "no traffic control plan")
        assert fx.read_site(blocked_site["id"])["site_posture"] == "BLOCKED"

        on_blocked = fx.quote_contract(
            fx.raise_contract(env["account"]["id"], blocked_site["id"])
        )
        assert on_blocked["fulfillment_state"] == "QUOTED"

        body = validate_error(
            api_client.activate_rental_contract(on_blocked["id"], SALES),
            "ERR_SITE_POSTURE_BLOCKED",
            409,
        )
        assert body["error_id"] != "ERR_ACCOUNT_BILLING_HOLD"
        assert "credit" not in body["message"].lower()
        assert fx.read_contract(on_blocked["id"])["fulfillment_state"] == "QUOTED"

    def test_09_the_same_held_account_reports_the_fiscal_failure_on_an_open_site(self):
        """Control: with the posture rule satisfied the hold is the reported refusal.

        PRD 3.4: "And the owning account's `billing_hold` must be false; a held account
        is rejected with `ERR_ACCOUNT_BILLING_HOLD` (HTTP 402), which is the one
        payment-required outcome in the whole API."
        PRD 3.6: "The account's `billing_hold` is set to true when
        `open_credit_balance_cents` is greater than or equal to 60000 cents — six hundred
        dollars of unapplied credit is where our credit team wants the brakes applied — and
        to false otherwise."

        Design: Difficulty/priority_pair_validation_conflict/activate_prefers_site_posture_blocked_over_account_billing_hold
        """
        env = fx.setup_missed_visit_credit(
            invoice_first=True,
            legal_name="Northgate Contractors",
            site_label="Northgate Block A",
            authority_ref="PL-8001",
            authority_decision_ref="AD-8001",
            site_overrides={
                "jurisdiction_code": "OR-PO-CITY",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
            route_code="RT-MON-22",
        )
        assert env["account"]["billing_hold"] is True
        assert env["site"]["site_posture"] == "OPEN"

        on_open = fx.quote_contract(
            fx.raise_contract(env["account"]["id"], env["site"]["id"])
        )
        assert on_open["fulfillment_state"] == "QUOTED"

        validate_error(
            api_client.activate_rental_contract(on_open["id"], SALES),
            "ERR_ACCOUNT_BILLING_HOLD",
            402,
        )
        assert fx.read_contract(on_open["id"])["fulfillment_state"] == "QUOTED"


class TestRelocation:
    """Moving a live unit: two pinned roundings, and the RESTRICTED exemption."""

    def test_10_the_two_relocation_roundings_are_separate_steps(self):
        """A CRANE_ONLY same-day pick bills 56194, and the plain move pins 41625.

        PRD 3.4: "Start from a base relocation fee of 18500 cents."
        PRD 3.4: "Apply the destination's access-class multiplier — 100 percent for
        `OPEN_LOT`, 115 percent for `GATED`, 140 percent for `STAIR_ACCESS` and 225
        percent for `CRANE_ONLY`, since a crane pick costs us well over twice a flat-lot
        drop — by multiplying the base by that percentage, dividing by 100 and rounding
        half up to whole cents."
        PRD 3.4: "Then, and only then, apply the same-day uplift: if the requested
        `effective_date` equals the logical clock's current calendar date the move is a
        same-day scramble and carries a further 35 percent, so multiply the rounded
        intermediate by 135, divide by 100 and round half up again; if the
        `effective_date` is any other date the uplift is zero and the second rounding
        leaves the intermediate unchanged."
        PRD 3.4: "Collapsing the two roundings into one is not permitted."

        Design: Corner/calculations/relocation_charge_rounds_half_up_once_per_pinned_step
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account("Ironwood Tower Group", credit_terms_days=45)
        origin = fx.register_site(
            account["id"],
            "Ironwood Staging",
            jurisdiction_code="IL-CO-CITY",
            access_class="OPEN_LOT",
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        destination = fx.register_site(
            account["id"],
            "Ironwood Roof Deck",
            jurisdiction_code="IL-CO-CITY",
            access_class="CRANE_ONLY",
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        fx.approve_permit_for_site(
            origin["id"], authority_ref="PL-10201", authority_decision_ref="AD-10201"
        )
        fx.approve_permit_for_site(
            destination["id"],
            authority_ref="PL-10202",
            authority_decision_ref="AD-10202",
        )
        first_unit = fx.add_asset_unit("SP-801", yard_code="YD-8", tare_length_ft=8)
        second_unit = fx.add_asset_unit("SP-802", yard_code="YD-8", tare_length_ft=8)
        contract = fx.quote_contract(fx.raise_contract(account["id"], origin["id"]))
        first = fx.commit_deployment(contract["id"], first_unit["id"])
        second = fx.commit_deployment(contract["id"], second_unit["id"])
        fx.mobilize_contract(contract["id"])

        same_day = fx.relocate_deployment(
            first["id"], destination["id"], "2026-08-03", "crane pick to roof deck"
        )
        assert same_day["site_id"] == destination["id"]
        assert same_day["relocation_count"] == 1
        assert same_day["state"] == "DEPLOYED"

        charges = fx.charges_for_contract(contract["id"], charge_kind="RELOCATION")
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == 56194
        assert charges[0]["amount_cents"] != 56193
        assert charges[0]["charge_kind"] == "RELOCATION"
        assert charges[0]["state"] == "ASSESSED"
        assert charges[0].get("severity") is None

        later = fx.relocate_deployment(
            second["id"], destination["id"], "2026-08-05", "second pick, two days out"
        )
        assert later["site_id"] == destination["id"]

        both = fx.charges_for_contract(contract["id"], charge_kind="RELOCATION")
        assert len(both) == 2
        assert sorted(charge["amount_cents"] for charge in both) == [41625, 56194]

        reread = fx.read_contract(contract["id"])
        assert reread["charge_debits_cents"] == 97819
        assert reread["charge_debits_cents"] == 56194 + 41625
        assert fx.read_site(origin["id"])["deployed_unit_count"] == 0
        assert fx.read_site(destination["id"])["deployed_unit_count"] == 2

    def test_11_a_restricted_destination_takes_a_relocation_but_not_a_new_reservation(self):
        """One RESTRICTED site refuses a fresh deployment and accepts the relocated unit.

        PRD 3.4: "The governing site — the contract's site — must not be `BLOCKED` and
        must not be `RESTRICTED`, which is why a contract cannot be stocked before its
        permits are approved and any open tip-over is adjudicated."
        PRD 3.4: "The destination site's `site_posture` must not be `BLOCKED`, but —
        uniquely among the placement operations — a `RESTRICTED` destination is
        perfectly acceptable."
        PRD 3.4: "A successful relocation rewrites the deployment's `site_id` to the
        destination, increments `relocation_count` by exactly one (the counter is
        monotonic and never decremented), creates a charge event with `charge_kind`
        `RELOCATION` in `state` `ASSESSED` against the deployment's contract and asset
        unit, recomputes the contract's `charge_debits_cents` and `net_billable_cents`,
        and recomputes `deployed_unit_count` for **both** the site the unit left and the
        site it arrived at."

        Design: Corner/validations/relocation_onto_a_restricted_site_is_allowed_while_a_new_deployment_there_is_refused
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account("Tanglewood Builders", credit_terms_days=30)
        open_site = fx.register_site(
            account["id"],
            "Tanglewood One",
            jurisdiction_code="MS-HI-CITY",
            access_class="OPEN_LOT",
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        restricted_site = fx.register_site(
            account["id"],
            "Tanglewood Two",
            jurisdiction_code="MS-HI-CITY",
            access_class="GATED",
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        fx.approve_permit_for_site(
            open_site["id"], authority_ref="PL-11401", authority_decision_ref="AD-11401"
        )
        pending = fx.file_permit(restricted_site["id"], authority_ref="PL-11402")
        fx.submit_permit(pending["id"])
        assert fx.read_site(restricted_site["id"])["site_posture"] == "RESTRICTED"

        first_unit = fx.add_asset_unit("SP-1401", yard_code="YD-14", tare_length_ft=8)
        second_unit = fx.add_asset_unit("SP-1402", yard_code="YD-14", tare_length_ft=8)
        on_open = fx.quote_contract(
            fx.raise_contract(account["id"], open_site["id"])
        )
        deployment = fx.commit_deployment(on_open["id"], first_unit["id"])
        fx.mobilize_contract(on_open["id"])
        on_restricted = fx.quote_contract(
            fx.raise_contract(account["id"], restricted_site["id"])
        )

        validate_error(
            api_client.create_unit_deployment(
                {
                    "contract_id": on_restricted["id"],
                    "asset_unit_id": second_unit["id"],
                    "deploy_from": "2026-08-03",
                    "deploy_to": "2026-09-30",
                },
                PLANNER,
            ),
            "ERR_SITE_POSTURE_RESTRICTED",
            409,
        )

        moved = fx.relocate_deployment(
            deployment["id"],
            restricted_site["id"],
            "2026-08-05",
            "moved to the restricted annex",
        )
        assert moved["state"] == "DEPLOYED"
        assert moved["site_id"] == restricted_site["id"]
        assert moved["relocation_count"] == 1

        charges = fx.charges_for_contract(on_open["id"], charge_kind="RELOCATION")
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == 21275

        landed = fx.read_site(restricted_site["id"])
        assert landed["site_posture"] == "RESTRICTED"
        assert landed["deployed_unit_count"] == 1
        assert fx.read_site(open_site["id"])["deployed_unit_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_unit_deployments(
                PLANNER, {"site_id": restricted_site["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == deployment["id"]
