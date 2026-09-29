"""Deliberate orderings in the rejection ladder, exercised by doubly invalid calls."""

from test_helpers import (
    CA_BID_CONFIG,
    COMPLIANCE,
    SALES,
    ApiErrorId,
    api_client,
    close_solicitation,
    create_bay,
    create_bid,
    create_profile,
    create_solicitation,
    read_bid,
    read_profile,
    read_unit,
    record_result,
    schedule_test,
    setup_built_unit,
    setup_ca_catalogue,
    setup_tx_catalogue,
    tx_profile_payload,
    validate_error,
    validate_success,
)

CA_OVER_CAP_UNIT_CENTS = 30_913_950
CA_PRICE_CAP_CENTS = 25_000_000


class TestSubmitReportsSolicitationStateOverPriceCap:
    """The price-cap check is deliberately the last rung on a submit, so a closed
    solicitation is reported instead."""

    def _over_cap_bid(self, solicitation_code: str) -> dict:
        """A fully optioned California bid priced well above a 25,000,000 cap."""
        catalogue = setup_ca_catalogue()
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code=solicitation_code,
            buyer_type="COOPERATIVE",
            buyer_name="Central Valley Cooperative",
            unit_count=12,
            required_delivery_date="2026-12-15",
            price_cap_cents_per_unit=CA_PRICE_CAP_CENTS,
        )
        config = dict(CA_BID_CONFIG)
        config["unit_count"] = 12
        bid = create_bid(
            solicitation["id"],
            catalogue["model"]["id"],
            catalogue["package"]["id"],
            **config,
        )
        assert bid["provisional_unit_price_cents"] == CA_OVER_CAP_UNIT_CENTS
        assert bid["spec_compliance_status"] == "CONFORMING"
        return {"solicitation": solicitation, "bid": bid}

    def test_a_closed_solicitation_outranks_the_over_cap_price(self):
        """A bid that is both over cap and aimed at a closed solicitation reports
        the solicitation state.

        PRD: "This is deliberately the **last** check on a submit, so a bid that is
        both over cap and aimed at a closed solicitation reports
        `ERR_SOLICITATION_NOT_OPEN` from rung 22."

        Design: Difficulty/priority_pair_validation_conflict/submit_reports_solicitation_not_open_over_price_cap_exceeded
        """
        scenario = self._over_cap_bid("SOL-CA-003")
        closed = close_solicitation(scenario["solicitation"]["id"])
        assert closed["status"] == "CLOSED"

        refused = api_client.submit_bid(scenario["bid"]["id"], SALES)
        validate_error(refused, ApiErrorId.ERR_SOLICITATION_NOT_OPEN.value)

        after = read_bid(scenario["bid"]["id"])
        assert after["status"] == "DRAFT"
        assert after["submitted_at"] in (None, "")
        assert after["provisional_unit_price_cents"] == CA_OVER_CAP_UNIT_CENTS
        assert after["spec_compliance_status"] == "CONFORMING"

    def test_the_same_bid_on_an_open_solicitation_reports_the_price_cap(self):
        """With the solicitation still open the last rung is reached and the cap is
        the reported failure, leaving the bid and its solicitation untouched.

        PRD: "the price cap is applied to the figure already standing in
        `provisional_unit_price_cents`, and a figure above the solicitation's
        `price_cap_cents_per_unit` is refused with `ERR_PRICE_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_reports_solicitation_not_open_over_price_cap_exceeded
        """
        scenario = self._over_cap_bid("SOL-CA-004")
        refused = api_client.submit_bid(scenario["bid"]["id"], SALES)
        validate_error(refused, ApiErrorId.ERR_PRICE_CAP_EXCEEDED.value)

        after = read_bid(scenario["bid"]["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] == scenario["bid"]["version"]
        solicitation = validate_success(
            api_client.get_solicitation(scenario["solicitation"]["id"], SALES)
        )
        assert solicitation["status"] == "OPEN"
        assert solicitation["price_cap_cents_per_unit"] == CA_PRICE_CAP_CENTS


class TestCertifyReportsMissingTestOverSupersededProfile:
    """The safety checks sit above the still-published check, so a bus that fails
    both reports the safety failure."""

    def _built_bus_missing_its_electrical_test(self, vin: str) -> dict:
        """A built Texas bus with brake and emergency-exit passes on file, whose
        governing profile has since been superseded."""
        catalogue = setup_tx_catalogue()
        scenario = setup_built_unit(
            catalogue,
            vin=vin,
            line_overrides={"supported_body_classes": ["TYPE_C"]},
            solicitation_overrides={"solicitation_code": "SOL-TX-004"},
        )
        bay = create_bay(
            supported_test_types=["BRAKE", "EMERGENCY_EXIT", "ELECTRICAL"]
        )
        unit_id = scenario["unit"]["id"]
        for test_type, day in (("BRAKE", "2026-09-15"), ("EMERGENCY_EXIT", "2026-09-16")):
            test = schedule_test(unit_id, bay["id"], test_type, day, day)
            record_result(test["id"], "PASS")
        second = create_profile(tx_profile_payload(min_seat_capacity=72))
        scenario.update({"bay": bay, "first_profile": catalogue["profile"],
                         "second_profile": second})
        return scenario

    def test_the_missing_electrical_test_outranks_the_superseded_profile(self):
        """Certification reports the missing required test even though the bus's
        profile is no longer published.

        PRD: "This check sits **above** the profile-still-published check at rung
        44, so a bus that is missing tests *and* whose profile has been superseded
        reports the missing-test error."

        Design: Difficulty/priority_pair_validation_conflict/certify_reports_required_test_missing_over_profile_not_published
        """
        scenario = self._built_bus_missing_its_electrical_test("1TXDSL0000000201")
        first = read_profile(scenario["first_profile"]["id"])
        assert first["status"] == "SUPERSEDED"
        assert first["superseded_by_profile_id"] == scenario["second_profile"]["id"]
        assert read_profile(scenario["second_profile"]["id"])["status"] == "PUBLISHED"

        refused = api_client.certify_bus_unit(scenario["unit"]["id"], COMPLIANCE)
        validate_error(refused, ApiErrorId.ERR_REQUIRED_TEST_MISSING.value)

        unit = read_unit(scenario["unit"]["id"])
        assert unit["certification_status"] == "PENDING"
        assert unit["production_status"] == "BUILT"

    def test_completing_the_test_set_uncovers_the_profile_check_beneath_it(self):
        """Once the electrical test passes, the same certify call falls through to
        the still-published check, and supersession never rewrote the bus's own
        profile reference.

        PRD: "The bus's `spec_profile_id` must still be `PUBLISHED`, otherwise
        `ERR_SPEC_PROFILE_NOT_PUBLISHED`".
        PRD: "Supersession rewrites no references. Bids, contract orders and buses
        that already point at the older profile keep pointing at it".

        Design: Difficulty/priority_pair_validation_conflict/certify_reports_required_test_missing_over_profile_not_published
        """
        scenario = self._built_bus_missing_its_electrical_test("1TXDSL0000000202")
        unit_id = scenario["unit"]["id"]
        electrical = schedule_test(
            unit_id, scenario["bay"]["id"], "ELECTRICAL", "2026-09-17", "2026-09-17"
        )
        assert record_result(electrical["id"], "PASS")["status"] == "PASSED"

        refused = api_client.certify_bus_unit(unit_id, COMPLIANCE)
        validate_error(refused, ApiErrorId.ERR_SPEC_PROFILE_NOT_PUBLISHED.value)

        unit = read_unit(unit_id)
        assert unit["certification_status"] == "PENDING"
        assert unit["production_status"] == "BUILT"
        assert unit["spec_profile_id"] == scenario["first_profile"]["id"]
        assert unit["certified_at"] in (None, "")
