"""Temporal overlap geometry: the carrier slot and the licence coverage rule."""
from test_helpers import (
    setup_active_prescription,
    create_order_payload,
    list_payload,
    get_success_data,
    validate_error,
    validate_success,
    create_manufacturer,
    create_drug,
    create_sourced_price,
    create_patient,
    create_prescriber,
    create_prescription,
    create_pharmacy,
    create_license_pending,
    verify_license,
    submit_intake,
    review_intake,
    accept_intake,
    pay_order,
    fulfill_order,
    ship_order,
    reset_clock,
    OPS,



)

TWO_DAYS_LATER = "2026-09-03T00:00:00Z"


class TestCarrierSlotBufferedCapacity:

    def test_two_dispatches_on_the_same_day_fill_the_slot(self, api):
        """PRD §3.7: "Each drug carries a daily carrier slot of aggregate
        capacity 2. A shipment dispatched on calendar day D occupies that day,
        and — as a quarantine buffer — also occupies calendar day D-1."

        Design: Difficulty/resource_temporal_overlap/ship_slot_buffered_aggregate_capacity_two_day_geometry
        """
        reset_clock()
        ctx = slot_stack(api, order_count=3)
        first = get_success_data(api.ship_order(ctx["orders"][0]["id"], OPS))
        second = get_success_data(api.ship_order(ctx["orders"][1]["id"], OPS))
        assert first["status"] == "SHIPPED"
        assert second["status"] == "SHIPPED", (
            "the slot capacity is 2, so two dispatches on the same day fit"
        )

    def test_dispatch_one_day_later_collides_on_the_buffer_day(self, api):
        """PRD §3.7: "The consequence of the buffer is that two shipments one day apart still
        collide, because the second shipment's buffer day is the first shipment's
        dispatch day and that day is already occupied; two shipments separated by at
        least two days never collide, because their occupied day sets are disjoint."

        Design: Difficulty/resource_temporal_overlap/ship_slot_buffered_aggregate_capacity_two_day_geometry
        """
        reset_clock()
        ctx = slot_stack(api, order_count=3)
        get_success_data(api.ship_order(ctx["orders"][0]["id"], OPS))
        get_success_data(api.ship_order(ctx["orders"][1]["id"], OPS))

        # Push the clock two calendar days forward: the third dispatch occupies
        # 2026-09-03 and its buffer day 2026-09-02, which is already occupied by
        # the first two dispatches' buffer day, so the slot is full.
        reset_clock("2026-09-02T00:00:00Z")
        response = api.ship_order(ctx["orders"][2]["id"], OPS)
        validate_error(response, "ERR_SHIP_SLOT_CONFLICT")

        order_after = get_success_data(api.get_order(ctx["orders"][2]["id"], OPS))
        assert order_after["status"] == "FULFILLING", (
            "the refused dispatch left the order in FULFILLING"
        )

    def test_departing_by_two_days_avoids_the_collision(self, api):
        """PRD §3.7: "two shipments separated by at least two days never
        collide, because their occupied day sets are disjoint."

        Design: Difficulty/resource_temporal_overlap/ship_slot_buffered_aggregate_capacity_two_day_geometry
        """
        reset_clock()
        ctx = slot_stack(api, order_count=3)
        get_success_data(api.ship_order(ctx["orders"][0]["id"], OPS))
        get_success_data(api.ship_order(ctx["orders"][1]["id"], OPS))

        # Move far enough that the third dispatch's occupied days (D-1, D) are
        # disjoint from the pair that filled 2026-09-01 and 2026-08-31.
        reset_clock(TWO_DAYS_LATER)
        shipped = get_success_data(api.ship_order(ctx["orders"][2]["id"], OPS))
        assert shipped["status"] == "SHIPPED", (
            "a two-day separation leaves the occupied day sets disjoint"
        )


class TestLicenceCoverageStrictAfter:

    def test_filing_with_an_equal_expiry_is_refused(self, api):
        """PRD §3.5: "Filing a second licence for a pair that already carries an
        ACTIVE licence, or filing a replacement whose expiry is not strictly
        after the incumbent's, is refused with ERR_LICENSE_CONFLICT and HTTP
        409."

        Design: Difficulty/resource_temporal_overlap/licence_coverage_strict_after_expiry_half_open_membership
        """
        reset_clock()
        pharmacy = create_pharmacy()
        first = create_license_pending(
            pharmacy["id"], state_code="CA", license_number="CA-MP-1001",
            expiry_at="2027-09-01T00:00:00Z")
        verify_license(pharmacy["id"], first["id"])

        response = api.file_license(pharmacy["id"], {
            "state_code": "CA", "license_number": "CA-MP-1002",
            "expiry_at": "2027-09-01T00:00:00Z",
        }, OPS)
        validate_error(response, "ERR_LICENSE_CONFLICT")
        incumbent = get_success_data(api.get_license(pharmacy["id"], first["id"], OPS))
        assert incumbent["status"] == "ACTIVE"

    def test_filing_with_a_later_expiry_supersedes_the_incumbent(self, api):
        """PRD §3.5: "when a licence for the same pharmacy-and-state pair is
        already ACTIVE and the incoming licence covers the same state_code, the
        incumbent is set to SUPERSEDED and its version advances, while the newly
        filed licence begins at PENDING."

        Design: Difficulty/resource_temporal_overlap/licence_coverage_strict_after_expiry_half_open_membership
        """
        reset_clock()
        pharmacy = create_pharmacy()
        first = create_license_pending(
            pharmacy["id"], state_code="CA", license_number="CA-MP-1001",
            expiry_at="2027-09-01T00:00:00Z")
        verify_license(pharmacy["id"], first["id"])

        replacement = validate_success(api.file_license(pharmacy["id"], {
            "state_code": "CA", "license_number": "CA-MP-1003",
            "expiry_at": "2027-09-02T00:00:00Z",
        }, OPS), 201)
        assert replacement["status"] == "PENDING"

        incumbent = get_success_data(api.get_license(pharmacy["id"], first["id"], OPS))
        assert incumbent["status"] == "SUPERSEDED", (
            "the accepted filing supersedes the earlier ACTIVE licence"
        )

        verified = verify_license(pharmacy["id"], replacement["id"])
        assert verified["status"] == "ACTIVE"
        licenses = list_payload(api.list_licenses(pharmacy["id"], OPS))
        active = [lic for lic in licenses
                  if lic["status"] == "ACTIVE" and lic["state_code"] == "CA"]
        assert len(active) == 1, "exactly one ACTIVE licence remains for CA"


# ─── local helpers ────────────────────────────────────

def slot_stack(api, order_count=3, quantity=2):
    """One formulary drug and one licensed pharmacy, with `order_count` PAID
    orders each drawn from its own prescription and request."""
    manufacturer = create_manufacturer("Bexley Generics")
    drug = create_drug()
    create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                         available_units=600, reliability_tier="A",
                         packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()

    orders = []
    first = True
    for _ in range(order_count):
        rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                                 total_refills_authorized=1, ship_state_code="CA")
        rq = submit_intake(rx["id"], packaged_quantity=quantity)
        review_intake(rq["id"])
        accept_intake(rq["id"])
        if first:
            # Admission needs trailing demand headroom relative to the 600-unit
            # row, and supply must not exceed ten times demand.
            setup_active_prescription(patient["id"], prescriber["id"], drug["id"],
                                      packaged_quantity=400,
                                      total_refills_authorized=1,
                                      ship_state_code="CA")
            drug = get_success_data(api.expand_formulary(drug["id"], OPS))
            pharmacy = create_pharmacy()
            licence = create_license_pending(pharmacy["id"], state_code="CA")
            verify_license(pharmacy["id"], licence["id"])
            prices = list_payload(api.list_drug_prices_of_drug(drug["id"], OPS))
            first = False
        order = get_success_data(api.create_order(create_order_payload(
            rx["id"], rq["id"], pharmacy["id"], prices[0]["id"], quantity=quantity), OPS))
        # Dispatch is only reachable from FULFILLING, and the shipment interval
        # must have elapsed, so each order is fulfilled a day after being paid.
        paid = pay_order(order["id"])
        # Fulfilment needs the tier-A interval (0 days here) to have elapsed;
        # the clock is then returned to the start so the dispatch geometry of
        # each test begins from a known calendar day.
        reset_clock("2026-09-02T00:00:00Z")
        orders.append(fulfill_order(paid["id"]))
        reset_clock()
    return {"drug": drug, "pharmacy": pharmacy, "orders": orders}