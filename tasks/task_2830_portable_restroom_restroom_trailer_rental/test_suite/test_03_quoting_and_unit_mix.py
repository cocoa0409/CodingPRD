"""The provisional unit-mix projection, the trailer tier and the reconciled variant."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_quote_line,
    assert_quote_line_set,
    assert_quote_lines_in_class_order,
    fixtures as fx,
    quote_line_totals,
    unit_classes_in_order,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]


def _event_account_and_site():
    """One EVENT account and one site; quoting is not posture-gated."""
    fx.reposition_clock("2026-08-03T08:00:00Z")
    account = fx.open_account(
        "Lakeshore Festivals", account_type="EVENT", credit_terms_days=0
    )
    site = fx.register_site(
        account["id"],
        "Lakeshore Green",
        jurisdiction_code="IL-CH-CITY",
        access_class="OPEN_LOT",
        gate_open_minute=300,
        gate_close_minute=1380,
        max_truck_length_ft=60,
    )
    return account, site


class TestProvisionalLineSet:
    """What one quote run emits and how the emitted rows are shaped."""

    def test_01_quote_lines_carry_only_id_and_created_at(self):
        """A quoted line set is immutable: no version, no updated_at, nothing superseded.

        PRD 2.9: "A `QuoteLine` is an immutable-by-design pricing artefact — it is
        superseded rather than edited — and it carries only `id` and `created_at`."
        PRD 3.3: "each stamped with `quote_variant` of `PROVISIONAL` and
        `is_superseded` of false, and each carrying a `unit_class`, a `quantity`, a
        `unit_rate_cents` and an `extended_cents`. The `escalated_cents` field on a
        line stays 0 until the contract is invoiced."

        Design: Corner/entities/quote_line_is_immutable_and_carries_no_version_field
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account("Kestrel Constructors")
        site = fx.register_site(
            account["id"], "Kestrel Yard", jurisdiction_code="ID-AD-CITY"
        )
        contract = fx.raise_thirteen_unit_contract(account["id"], site["id"])

        quoted = fx.quote_contract(contract)
        assert quoted["quoted_cents"] == 181500

        lines = validate_success(
            api_client.list_quote_lines(
                contract["id"], SALES, {"is_superseded": False}
            )
        )
        assert len(lines) == 3
        assert_quote_line_set(
            lines,
            [
                ("STANDARD_PORTABLE", 9, 14500, 130500),
                ("ADA_PORTABLE", 1, 22500, 22500),
                ("HANDWASH_STATION", 3, 9500, 28500),
            ],
        )
        assert_quote_lines_in_class_order(lines)
        for line in lines:
            assert_quote_line(line)
            assert line["escalated_cents"] == 0
            assert line["is_superseded"] is False
            assert "version" not in line
            assert "updated_at" not in line
        assert quote_line_totals(lines) == 181500

    def test_02_requoting_supersedes_the_old_lines_and_sums_only_the_live_ones(self):
        """Six rows exist after two runs, but quoted_cents counts the three live ones.

        PRD 3.3: "Every quote line of the contract with `quote_variant`
        `PROVISIONAL` and `is_superseded` false has `is_superseded` set to true, then
        the fresh provisional line set is created exactly as in the first run, then
        `quoted_cents` and `net_billable_cents` are recomputed and `version`
        increments again."
        PRD 3.3: "Superseded lines are never deleted — they remain readable — but
        they are excluded from the input set of every calculation in this
        specification."

        Design: Corner/calculations/requoting_supersedes_the_old_lines_and_recomputes_from_the_new_set_only
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account("Nightjar Constructors")
        site = fx.register_site(
            account["id"], "Nightjar Block C", jurisdiction_code="MO-JA-CITY"
        )
        contract = fx.raise_thirteen_unit_contract(account["id"], site["id"])
        assert contract["version"] == 1

        first = fx.quote_contract(contract)
        assert first["quoted_cents"] == 181500
        assert first["version"] == 2

        second = validate_success(
            api_client.quote_rental_contract(
                contract["id"],
                {
                    "expected_contract_version": first["version"],
                    "quote_note": "same inputs, fresh line set",
                },
                SALES,
            )
        )
        assert second["quoted_cents"] == 181500
        assert second["version"] == 3
        assert second["fulfillment_state"] == "QUOTED"
        assert second["net_billable_cents"] == 0

        live = fx.live_quote_lines(contract["id"])
        assert len(live) == 3
        assert [line["extended_cents"] for line in live] == [130500, 22500, 28500]
        assert quote_line_totals(live) == 181500

        dead = fx.superseded_quote_lines(contract["id"])
        assert len(dead) == 3
        assert all(line["is_superseded"] is True for line in dead)

        every = fx.all_quote_lines(contract["id"], quote_variant="PROVISIONAL")
        assert len(every) == 6
        assert all(line["quote_variant"] == "PROVISIONAL" for line in every)


class TestTrailerTierBoundary:
    """The tier threshold is a hard test on headcount, probed at 399 and 400."""

    def test_03_headcount_399_is_served_with_individual_portables(self):
        """One below the floor: 23 standard portables, no trailer line of either class.

        PRD 3.3: "The tier decision is a hard threshold on population, not on
        capacity: a contract whose `headcount` is 400 or more is served with restroom
        trailers, and one below 400 is served with individual portables."
        PRD 3.3: "Below the threshold, both trailer quantities are zero and the
        `STANDARD_PORTABLE` quantity is the whole base capacity."

        Design: Difficulty/boundary_precision_check/trailer_tier_boundary_at_headcount_400_changes_the_mix_shape
        """
        account, site = _event_account_and_site()
        contract = fx.raise_event_contract(
            account["id"],
            site["id"],
            headcount=399,
            event_duration_hours=12,
            term_start="2026-08-14",
            term_end="2026-08-16",
        )

        quoted = fx.quote_contract(contract)
        assert quoted["quoted_cents"] == 445000

        lines = fx.live_quote_lines(contract["id"])
        assert_quote_line_set(
            lines,
            [
                ("STANDARD_PORTABLE", 23, 14500, 333500),
                ("ADA_PORTABLE", 2, 22500, 45000),
                ("HANDWASH_STATION", 7, 9500, 66500),
            ],
        )
        classes = unit_classes_in_order(lines)
        assert "TRAILER_2STALL" not in classes
        assert "TRAILER_8STALL" not in classes

    def test_04_headcount_400_switches_the_whole_mix_shape_to_trailers(self):
        """At the floor: three eight-stall trailers and no standard-portable line at all.

        PRD 3.3: "Above the threshold, the number of `TRAILER_8STALL` units is the
        base capacity divided by 8 with any remainder discarded; the units left over
        after those eight-stall trailers are subtracted are then covered by
        `TRAILER_2STALL` units, counted as that leftover divided by 2 and rounded up —
        a leftover of zero yields no two-stall trailers — and the `STANDARD_PORTABLE`
        quantity is zero."
        PRD 3.3: "265000 for a `TRAILER_8STALL`"

        Design: Difficulty/boundary_precision_check/trailer_tier_boundary_at_headcount_400_changes_the_mix_shape
        """
        account, site = _event_account_and_site()
        below = fx.raise_event_contract(
            account["id"],
            site["id"],
            headcount=399,
            event_duration_hours=12,
            term_start="2026-08-14",
            term_end="2026-08-16",
        )
        at_floor = fx.raise_event_contract(
            account["id"],
            site["id"],
            headcount=400,
            event_duration_hours=12,
            term_start="2026-08-14",
            term_end="2026-08-16",
        )

        quoted_below = fx.quote_contract(below)
        quoted_at = fx.quote_contract(at_floor)
        assert quoted_below["quoted_cents"] == 445000
        assert quoted_at["quoted_cents"] == 906500
        assert quoted_at["quoted_cents"] - quoted_below["quoted_cents"] == 461500

        lines = fx.live_quote_lines(at_floor["id"])
        assert_quote_line_set(
            lines,
            [
                ("ADA_PORTABLE", 2, 22500, 45000),
                ("HANDWASH_STATION", 7, 9500, 66500),
                ("TRAILER_8STALL", 3, 265000, 795000),
            ],
        )
        classes = unit_classes_in_order(lines)
        assert "STANDARD_PORTABLE" not in classes
        assert "TRAILER_2STALL" not in classes
        assert classes == ["ADA_PORTABLE", "HANDWASH_STATION", "TRAILER_8STALL"]

    def test_05_the_trailer_tier_fires_on_headcount_even_when_capacity_is_tiny(self):
        """A 400-person one-hour event needs two units and still gets a trailer.

        PRD 3.3: "The tier decision is a hard threshold on population, not on
        capacity: a contract whose `headcount` is 400 or more is served with restroom
        trailers, and one below 400 is served with individual portables."
        PRD 3.3: "**Step four — restroom equivalents actually placed.** Add the
        standard-portable quantity, twice the two-stall trailer quantity, and eight
        times the eight-stall trailer quantity."
        PRD 3.3: "If it is true, divide the restroom equivalents from step four by 20
        and round up, then take whichever is larger, that result or one"

        Design: Difficulty/boundary_precision_check/trailer_tier_boundary_at_headcount_400_changes_the_mix_shape
        """
        account, site = _event_account_and_site()
        tiny = fx.raise_event_contract(
            account["id"],
            site["id"],
            headcount=400,
            event_duration_hours=1,
            term_start="2026-08-14",
            term_end="2026-08-14",
        )

        quoted = fx.quote_contract(tiny)
        assert quoted["quoted_cents"] == 110000

        lines = fx.live_quote_lines(tiny["id"])
        assert_quote_line_set(
            lines,
            [
                ("ADA_PORTABLE", 1, 22500, 22500),
                ("HANDWASH_STATION", 1, 9500, 9500),
                ("TRAILER_2STALL", 1, 78000, 78000),
            ],
        )
        assert "STANDARD_PORTABLE" not in unit_classes_in_order(lines)


def _thirteen_unit_contract_with_two_deployed_portables():
    """A 13-unit quote against which only two standard portables ever shipped."""
    env = fx.setup_placeable_site(
        legal_name="Northgate Builders LLC",
        site_label="Northgate Lot A",
        authority_ref="PL-1001",
        authority_decision_ref="AD-1001",
    )
    unit_one = fx.add_asset_unit("SP-001")
    unit_two = fx.add_asset_unit("SP-002")
    contract = fx.raise_thirteen_unit_contract(
        env["account"]["id"], env["site"]["id"]
    )
    quoted = fx.quote_contract(contract)
    assert quoted["quoted_cents"] == 181500

    deployment_one = fx.commit_deployment(contract["id"], unit_one["id"])
    deployment_two = fx.commit_deployment(contract["id"], unit_two["id"])
    fx.mobilize_contract(contract["id"])

    env.update(
        {
            "contract": quoted,
            "unit_one": unit_one,
            "unit_two": unit_two,
            "deployment_one": deployment_one,
            "deployment_two": deployment_two,
        }
    )
    return env


class TestReconciledVariant:
    """Provisional projection and reconciled actual on one contract row."""

    def test_06_quoted_and_reconciled_totals_diverge_on_the_same_contract(self):
        """Demobilization writes reconciled_cents 29000 and leaves quoted_cents at 181500.

        PRD 3.9: "Each class's `quantity` is simply the count of the contract's
        deployments whose `state` is `DEPLOYED` or `RETURNED` and whose asset unit's
        `unit_class` is that class; deployments still in `RESERVED` are excluded
        because they never reached the site."
        PRD 3.9: "The contract's `reconciled_cents` is the sum of `extended_cents`
        over the emitted reconciled lines, and `net_billable_cents` is recomputed."
        PRD 3.9: "For identical contract inputs the two variants disagree whenever the
        fleet that actually shipped differs from the mix that was modelled, which is
        exactly the exposure the branch wants visible."

        Design: Difficulty/dual_variant_calc/unit_mix_provisional_vs_reconciled_diverge_on_contract_ledger
        """
        env = _thirteen_unit_contract_with_two_deployed_portables()

        demobilized = validate_success(
            api_client.demobilize_rental_contract(
                env["contract"]["id"],
                PLANNER,
                {"demobilization_note": "phase 2 complete"},
            )
        )
        assert demobilized["fulfillment_state"] == "DEMOBILIZED"
        assert demobilized["reconciled_cents"] == 29000
        assert demobilized["quoted_cents"] == 181500

        reread = fx.read_contract(env["contract"]["id"])
        assert reread["quoted_cents"] == 181500
        assert reread["reconciled_cents"] == 29000
        assert reread["quoted_cents"] - reread["reconciled_cents"] == 152500
        assert reread["net_billable_cents"] == 0

    def test_07_the_reconciled_line_set_applies_neither_overlay(self):
        """One reconciled line for the two deployed portables; the three modelled lines die.

        PRD 3.9: "First, every quote line of the contract that has not been superseded
        — provisional lines included — has `is_superseded` set to true."
        PRD 3.9: "Then a fresh line set is created with `quote_variant` `RECONCILED`,
        in the same fixed class order (`STANDARD_PORTABLE`, `ADA_PORTABLE`,
        `HANDWASH_STATION`, `TRAILER_2STALL`, `TRAILER_8STALL`), skipping any class
        whose quantity is zero."
        PRD 3.9: "There is **no** accessibility overlay and **no** handwash overlay in
        this variant: actuals are counted, not modelled."

        Design: Difficulty/dual_variant_calc/unit_mix_provisional_vs_reconciled_diverge_on_contract_ledger
        """
        env = _thirteen_unit_contract_with_two_deployed_portables()
        contract_id = env["contract"]["id"]

        fx.demobilize_contract(contract_id, demobilization_note="phase 2 complete")

        every = fx.all_quote_lines(contract_id)
        assert len(every) == 4

        provisional = [
            line for line in every if line["quote_variant"] == "PROVISIONAL"
        ]
        assert len(provisional) == 3
        assert all(line["is_superseded"] is True for line in provisional)

        reconciled = fx.live_quote_lines(contract_id)
        assert_quote_line_set(
            reconciled,
            [("STANDARD_PORTABLE", 2, 14500, 29000)],
            variant="RECONCILED",
        )
        classes = unit_classes_in_order(reconciled)
        assert "ADA_PORTABLE" not in classes
        assert "HANDWASH_STATION" not in classes

        assert fx.read_deployment(env["deployment_one"]["id"])["state"] == "RETURNED"
        assert fx.read_deployment(env["deployment_two"]["id"])["state"] == "RETURNED"
        assert fx.read_asset_unit(env["unit_one"]["id"])["status"] == "IN_YARD"
        assert fx.read_asset_unit(env["unit_two"]["id"])["status"] == "IN_YARD"
