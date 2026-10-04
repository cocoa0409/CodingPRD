"""Queue B — cross_cutting_layers section (4 non-stub instances)."""
from test_helpers import (
    set_manufacturer_state,
    validate_error,
    create_order_payload,
    list_payload,
    create_drug,
    create_manufacturer,
    create_license_pending,
    create_patient,
    create_pharmacy,
    create_prescriber,
    create_prescription,
    create_sourced_price,
    get_success_data,
    pay_order,
    validate_success,
    verify_license,
    reset_clock,
    OPS,
    PHARMACIST,


)


class TestLicenceExpiryThreshold:

    def test_verification_one_second_before_expiry_activates(self, api):
        """PRD §3.5: "Moving a licence from PENDING to ACTIVE requires that the
        licence is PENDING and that its expiry_at is strictly after the logical
        clock; on success verified_at is stamped with the logical clock."

        Design: Corner/cross_cutting_layers/rate_threshold_licence_expiry_requires_expiry_strictly_after_the_clock
        """
        reset_clock("2026-09-30T23:59:59Z")
        pharmacy = create_pharmacy()
        licence = create_license_pending(
            pharmacy["id"], state_code="CA", license_number="CA-MP-1001",
            expiry_at="2026-10-01T00:00:00Z")

        verified = verify_license(pharmacy["id"], licence["id"])
        assert verified["status"] == "ACTIVE"
        assert verified["verified_at"] is not None

    def test_verification_at_the_expiry_instant_expires_the_licence(self, api):
        """PRD §3.5: "The same action expires an ACTIVE licence whose expiry_at
        is at or before the logical clock, moving it from ACTIVE to EXPIRED."

        Design: Corner/cross_cutting_layers/rate_threshold_licence_expiry_requires_expiry_strictly_after_the_clock
        """
        reset_clock("2026-09-30T23:59:59Z")
        pharmacy = create_pharmacy()
        licence = verify_license(
            pharmacy["id"],
            create_license_pending(pharmacy["id"], state_code="CA",
                                   license_number="CA-MP-1001",
                                   expiry_at="2026-10-01T00:00:00Z")["id"])
        assert licence["status"] == "ACTIVE"

        reset_clock("2026-10-01T00:00:00Z")
        lapsed = verify_license(pharmacy["id"], licence["id"])
        assert lapsed["status"] == "EXPIRED", (
            "expiry equal to the logical clock does not activate, so the "
            "threshold is strict-after"
        )


class TestDerivedSupplyReconciliation:

    def test_supply_units_tracks_the_eligible_pool(self, api):
        """PRD §3.2: "The supply total, written to the drug's supply_units, sums
        available_units across rows whose sourcing dimension is SOURCED or
        UNDER_REVIEW and whose manufacturer is ACTIVE"
        PRD §3.1: "it forces every one of that manufacturer's rows that
        currently sits at SOURCED on the sourcing dimension to SUPPRESSED"

        Design: Corner/cross_cutting_layers/derived_drug_supply_units_reconcile_with_the_eligible_pool_after_a_sourcing_change
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = create_sourced_price(drug["id"], manufacturer["id"],
                                   unit_cost_cents=12, available_units=500,
                                   reliability_tier="A", packaging="500-count bottle")
        before = get_success_data(api.get_drug(drug["id"], OPS))
        assert before["supply_units"] == 500
        assert before["sourcing_status"] == "SOURCED"

        # Suspension drives every SOURCED row of the manufacturer to SUPPRESSED,
        # which takes the row out of both the sourcing pool and the supply total
        # (PRD §2.10, §3.2) — the one path that genuinely empties the headroom.
        set_manufacturer_state(manufacturer["id"], "SUSPENDED")
        after = get_success_data(api.get_drug(drug["id"], OPS))
        assert after["supply_units"] == 0, (
            "a suppressed row contributes no headroom: supply_units counts only "
            "SOURCED or UNDER_REVIEW rows of an ACTIVE manufacturer"
        )
        assert after["sourcing_status"] == "UNSOURCED"

    def test_the_row_itself_is_otherwise_unchanged_by_the_rebuild(self, api):
        """PRD §2.8: "a drug's sourcing_status, supply_units,
        effective_unit_cost_cents, ship_interval_days, expansion_score, packaging
        and demand_units_30d are all computed values that are re-derived"

        Design: Corner/cross_cutting_layers/derived_drug_supply_units_reconcile_with_the_eligible_pool_after_a_sourcing_change
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = create_sourced_price(drug["id"], manufacturer["id"],
                                   unit_cost_cents=12, available_units=500,
                                   reliability_tier="A", packaging="500-count bottle")
        get_success_data(api.move_price_sourcing(row["id"], "UNDER_REVIEW", OPS))
        after = get_success_data(api.get_price(row["id"], OPS))
        assert after["unit_cost_cents"] == 12
        assert after["available_units"] == 500
        assert after["sourcing_status"] == "UNDER_REVIEW"


class TestOptimisticConcurrencyOnFulfillment:

    def test_a_stale_version_token_is_refused(self, api):
        """PRD §2.9: "The request body must carry expected_order_version,
        carrying the client's last observed version of the target order. If the
        supplied value does not equal the order's current version, the request is
        rejected with ERR_STALE_VERSION and HTTP 412."

        Design: Corner/cross_cutting_layers/stale_expected_order_version_is_refused_on_fulfillment
        """
        reset_clock()
        ctx = paid_order(api)
        stale = ctx["version"] - 1
        response = api.fulfill_order(ctx["order"]["id"], stale, OPS)
        validate_error(response, "ERR_STALE_VERSION")
        still = get_success_data(api.get_order(ctx["order"]["id"], OPS))
        assert still["status"] == "PAID"

    def test_the_fresh_version_token_advances_the_order(self, api):
        """PRD §3.7: "An operator advances an order from PAID to FULFILLING, and
        the request body must carry expected_order_version, carrying the client's
        last observed version of the order"

        Design: Corner/cross_cutting_layers/stale_expected_order_version_is_refused_on_fulfillment
        """
        reset_clock()
        ctx = paid_order(api)
        fulfilled = validate_success(
            api.fulfill_order(ctx["order"]["id"], ctx["version"], OPS))
        assert fulfilled["status"] == "FULFILLING"
        assert fulfilled["version"] > ctx["version"]


class TestOptimisticConcurrencyOnSubstantiation:

    def test_a_pre_substitution_version_token_is_refused(self, api):
        """PRD §2.9: "Enabling a substantiation against an order is the second.
        That request body must likewise carry expected_order_version holding the
        client's last observed version of the order, and a mismatch with the
        order's current version is rejected with ERR_STALE_VERSION and HTTP 412."

        Design: Corner/cross_cutting_layers/stale_expected_order_version_is_refused_on_substantiation_enablement
        """
        reset_clock()
        ctx = order_with_substitution(api)
        response = api.enable_substantiation(
            ctx["order"]["id"], ctx["sub"]["id"], ctx["stale_version"], OPS)
        validate_error(response, "ERR_STALE_VERSION")
        still = get_success_data(api.get_substantiation(ctx["sub"]["id"], OPS))
        assert still["status"] == "PENDING"

    def test_the_post_substitution_version_token_enables_the_record(self, api):
        """PRD §3.4: "each such order's comparison is driven to
        REFRESH_REQUIRED with substantiated cleared and substantiation_digest
        cleared, and both the order's and the comparison's versions advance."

        Design: Corner/cross_cutting_layers/stale_expected_order_version_is_refused_on_substantiation_enablement
        """
        reset_clock()
        ctx = order_with_substitution(api)
        assert ctx["fresh_version"] > ctx["stale_version"], (
            "the substitution advanced the order's version"
        )
        enabled = get_success_data(api.enable_substantiation(
            ctx["order"]["id"], ctx["sub"]["id"], ctx["fresh_version"], OPS))
        assert enabled["status"] == "ENABLED"


# ─── local helpers ────────────────────────────────────

def _stack(api, total_refills_authorized=1):
    manufacturer = create_manufacturer()
    drug = create_drug()
    price_row = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=12, available_units=600,
                                     reliability_tier="A",
                                     packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=total_refills_authorized,
                             ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], 100, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    get_success_data(api.accept_intake_request(rq["id"], PHARMACIST))
    drug = get_success_data(api.expand_formulary(drug["id"], OPS))
    pharmacy = create_pharmacy()
    prices = list_payload(api.list_drug_prices_of_drug(drug["id"], OPS))
    return {"drug": drug, "pharmacy": pharmacy, "price_row": prices[0],
            "rx": rx, "rq": rq}


def paid_order(api):
    """An order driven to PAID, with the version read after the payment recompute
    so a one-behind token is genuinely stale."""
    ctx = _stack(api)
    order = get_success_data(api.create_order(create_order_payload(
        ctx["rx"]["id"], ctx["rq"]["id"], ctx["pharmacy"]["id"],
        ctx["price_row"]["id"], quantity=30), OPS))
    paid = pay_order(order["id"])
    current = get_success_data(api.get_order(paid["id"], OPS))
    return {"order": current, "version": current["version"]}


def order_with_substitution(api):
    """A CREATED order with a PENDING substantiation, a substitution that bumps
    the order's version, and both the pre- and post-substitution versions."""
    ctx = _stack(api)
    new_drug = create_drug(drug_name="Metformin ER",
                           retail_reference_price_cents=2000,
                           insured_reference_price_cents=1600)
    order = get_success_data(api.create_order(create_order_payload(
        ctx["rx"]["id"], ctx["rq"]["id"], ctx["pharmacy"]["id"],
        ctx["price_row"]["id"], quantity=60), OPS))
    stale = get_success_data(api.get_order(order["id"], OPS))["version"]
    sub = get_success_data(api.create_substantiation({
        "order_id": order["id"],
        "source_kind": "RETAIL_SURVEY",
        "source_reference": "Q3-2026 retail survey ref 88",
        "observed_at": "2026-08-15T00:00:00Z",
        "valid_until": "2026-12-01T00:00:00Z",
    }, OPS))
    get_success_data(api.substitute_prescription(
        ctx["rx"]["id"], {"new_drug_id": new_drug["id"],
                          "reason_code": "SHORTAGE_SUBSTITUTION"}, PHARMACIST))
    fresh = get_success_data(api.get_order(order["id"], OPS))["version"]
    return {"order": get_success_data(api.get_order(order["id"], OPS)),
            "sub": get_success_data(api.get_substantiation(sub["id"], OPS)),
            "stale_version": stale, "fresh_version": fresh}