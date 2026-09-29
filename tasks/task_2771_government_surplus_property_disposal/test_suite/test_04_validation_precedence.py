"""Validation precedence: which rule answers when several are violated at once.

The PRD fixes a total order over its rejection rules and spells that order out
again inside the individual workflows — bidding runs its gates "in this exact
order", and release runs "four documentation gates ... in order". These tests
drive one request that violates several rules simultaneously, assert the rule the
PRD ranks highest, then peel the violations off one at a time so that every rule
in the pair is also pinned in isolation.
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    assert_auction_lot,
    assert_bid,
    assert_bidder,
    assert_deposit_custody_invariant,
    assert_lot_rollups,
    assert_surplus_asset,
    certify_clearance,
    create_bid_payload,
    get_success_data,
    list_lot_bids,
    lodge_deposit,
    make_bidder_headers,
    make_disposal_officer_headers,
    make_program_admin_headers,
    read_asset,
    read_bidder,
    read_lot,
    read_transfer_order,
    read_turn_in,
    register_bidder,
    setup_acknowledged_transfer_order,
    setup_listed_lot,
    setup_open_lot,
    setup_open_lot_with_bidder,
    validate_error,
    validate_success,
)


def _instant(value: str) -> datetime:
    """Parse one of the PRD's ISO 8601 UTC instants for exact comparison."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ─── The lot's own state versus the reserve floor ─────────────────────────


class TestLotStateOutranksReserveFloor:
    """A bid of 1000 on a DRAFT lot whose reserve is 7524 violates the lot-state
    gate and the reserve gate at once."""

    def test_bid_on_draft_lot_below_reserve_reports_lot_not_open(self, api):
        """PRD §2.12: "Implementations must not report a lower-precedence failure while a higher-precedence one is outstanding."
        PRD §3.6: "The gates then run in this exact order, and the order is exercised deliberately because several of them can be true at once."
        PRD §3.6: "The lot must be `OPEN` with the logical clock at or after `opens_at` and strictly before `closes_at`, otherwise `ERR_LOT_NOT_OPEN` — this outranks the bidder's own standing, so a bid on a closed lot by an unregistered bidder reports the lot."
        PRD §3.6: "The `amount_cents` must be at or above the lot's `reserve_price_cents`, otherwise `ERR_BID_BELOW_RESERVE` (HTTP 422)."
        PRD §2.9: "Those secondary effects are part of the operation's contract, not best-effort housekeeping: an operation either applies all of its hops or, if a validation fails, applies none of them."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_lot_not_open_outranks_bid_below_reserve
        """
        scenario = setup_listed_lot()
        lot = scenario["lot"]
        bidder = register_bidder(status="REGISTERED")

        assert_auction_lot(lot)
        assert lot["reserve_price_cents"] == 7524, (
            "sixty hundredths of a fair market value of 12540 rounds half up to "
            f"7524, got {lot['reserve_price_cents']}"
        )
        assert lot["reserve_source"] == "COMPUTED", (
            "no reserve was supplied, so the computed figure is stored"
        )
        assert lot["required_deposit_cents"] == 0, (
            "a reserve below five thousand dollars requires no deposit, got "
            f"{lot['required_deposit_cents']}"
        )
        assert lot["status"] == "DRAFT", (
            f"a newly created lot sits in DRAFT, got {lot['status']}"
        )

        response = api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], 1000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, ApiErrorId.ERR_LOT_NOT_OPEN)

        after = read_lot(lot["id"])
        assert after["status"] == "DRAFT", (
            f"the refused bid must not open the lot, got {after['status']}"
        )
        assert after["bid_count"] == 0, (
            f"a refused bid persists nothing, got bid_count {after['bid_count']}"
        )
        assert after["high_bid_cents"] == 0, (
            f"a refused bid moves no roll-up, got {after['high_bid_cents']}"
        )
        assert list_lot_bids(lot["id"]) == [], (
            "the refused bid must not exist as a row"
        )

    def test_bid_at_or_above_reserve_on_draft_lot_reports_lot_not_open(self, api):
        """PRD §3.6: "The lot must be `OPEN` with the logical clock at or after `opens_at` and strictly before `closes_at`, otherwise `ERR_LOT_NOT_OPEN` — this outranks the bidder's own standing, so a bid on a closed lot by an unregistered bidder reports the lot."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_lot_not_open_outranks_bid_below_reserve
        """
        scenario = setup_listed_lot()
        lot = scenario["lot"]
        bidder = register_bidder(status="REGISTERED")

        response = api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], lot["reserve_price_cents"]),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, ApiErrorId.ERR_LOT_NOT_OPEN)

        after = read_lot(lot["id"])
        assert after["bid_count"] == 0, (
            "the lot-state gate is violated on its own here, and the refusal "
            f"still persists nothing; got bid_count {after['bid_count']}"
        )

    def test_below_reserve_bid_on_open_lot_reports_bid_below_reserve(self, api):
        """PRD §3.6: "The `amount_cents` must be at or above the lot's `reserve_price_cents`, otherwise `ERR_BID_BELOW_RESERVE` (HTTP 422)."
        PRD §3.6: "Opening a draft lot for bidding moves it `DRAFT` → `OPEN`; it requires the venue to still be `ACTIVE`, refusing with `ERR_VENUE_CLOSED` otherwise, and it requires the logical clock to lie inside the sale window, at or after `opens_at` and strictly before `closes_at`, refusing with `ERR_INVALID_STATE` otherwise."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_lot_not_open_outranks_bid_below_reserve
        """
        scenario = setup_open_lot()
        lot = scenario["lot"]
        bidder = register_bidder(status="REGISTERED")

        assert lot["status"] == "OPEN", (
            f"the lot must be OPEN for this scenario, got {lot['status']}"
        )
        assert lot["reserve_price_cents"] == 7524, (
            f"expected the computed reserve 7524, got {lot['reserve_price_cents']}"
        )

        response = api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], 1000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BID_BELOW_RESERVE)

        after = read_lot(lot["id"])
        assert after["bid_count"] == 0, (
            "the same amount that was answered with the lot's state on a DRAFT "
            "lot surfaces the reserve once the lot is OPEN, and still persists "
            f"nothing; got bid_count {after['bid_count']}"
        )

    def test_bid_at_exactly_the_reserve_is_accepted(self, api):
        """PRD §3.6: "The `amount_cents` must be at or above the lot's `reserve_price_cents`, otherwise `ERR_BID_BELOW_RESERVE` (HTTP 422)."
        PRD §3.6: "An accepted bid is created in `status` `ACTIVE` with `placed_at` stamped from the logical clock, and it recomputes two roll-ups on the lot: `high_bid_cents` becomes the largest `amount_cents` among the lot's bids whose `status` is `ACTIVE` or `WINNING`, and 0 when that set is empty; `bid_count` becomes the number of the lot's bids whose `status` is `ACTIVE`, `WINNING` or `OUTBID`, which deliberately excludes retracted ones."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_lot_not_open_outranks_bid_below_reserve
        """
        scenario = setup_open_lot()
        lot = scenario["lot"]
        bidder = register_bidder(status="REGISTERED")

        response = api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], 7524),
            make_bidder_headers(bidder["id"]),
        )
        bid = validate_success(response, 201)
        assert_bid(bid)
        assert bid["status"] == "ACTIVE", (
            f"an accepted bid is created ACTIVE, got {bid['status']}"
        )
        assert bid["amount_cents"] == 7524, (
            "the reserve comparison is at-or-above, so equality passes; got "
            f"{bid['amount_cents']}"
        )
        assert _instant(bid["placed_at"]) == _instant("2026-09-01T00:00:00Z"), (
            f"placed_at is stamped from the logical clock, got {bid['placed_at']}"
        )

        after = read_lot(lot["id"])
        assert after["high_bid_cents"] == 7524, (
            f"high_bid_cents must re-derive to 7524, got {after['high_bid_cents']}"
        )
        assert after["bid_count"] == 1, (
            f"bid_count must re-derive to 1, got {after['bid_count']}"
        )
        assert_lot_rollups(after, list_lot_bids(lot["id"]))


# ─── The four documentation gates on release ──────────────────────────────


class TestReleaseDocumentationGateOrder:
    """A data-bearing, lien-encumbered VEHICLE with no clearance certificate and
    an empty release payload violates the sanitisation gate, the odometer gate
    and the lien gate at once."""

    @staticmethod
    def _acknowledged_encumbered_vehicle() -> dict:
        """An ACKNOWLEDGED transfer of a data-bearing pickup that still carries a
        lienholder, awaiting release out of custody."""
        return setup_acknowledged_transfer_order(
            kind="vehicle",
            asset_overrides={
                "is_data_bearing": True,
                "lien_holder_name": "Capital Credit Union",
                "description": "2019 Ford F-250 with in-cab telematics computer",
            },
            recipient_overrides={
                "name": "City of Cedar Park",
                "agency_code": "CITY-77",
                "federal_donee_status": "CERTIFIED",
                "donee_certification_expires_on": "2027-03-31",
            },
        )

    def test_release_of_uncertified_encumbered_vehicle_reports_sanitization_gate(
        self, api
    ):
        """PRD §3.8: "Past the state check, four documentation gates run in order."
        PRD §3.8: "A data-bearing asset that is not `CLEARED` is refused with `ERR_SANITIZATION_NOT_CERTIFIED`."
        PRD §3.8: "A `VEHICLE` requires an `odometer_disclosure_reading` that is present and at or above the asset's recorded `odometer_reading`, together with a non-empty `title_recipient_name`, and is otherwise refused with `ERR_ODOMETER_DISCLOSURE_REQUIRED` (HTTP 422)."
        PRD §3.8: "An asset carrying a non-null `lien_holder_name` requires a non-empty `lien_release_reference`, and is otherwise refused with `ERR_LIEN_NOT_RELEASED`."
        PRD §2.12: "Implementations must not report a lower-precedence failure while a higher-precedence one is outstanding."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_sanitization_gate_outranks_odometer_disclosure
        """
        scenario = self._acknowledged_encumbered_vehicle()
        asset = scenario["asset"]

        assert asset["is_data_bearing"] is True, (
            "the scenario needs a data-bearing asset"
        )
        assert asset["clearance_status"] == "REQUIRED_PENDING", (
            "a data-bearing asset needs sanitisation, got "
            f"{asset['clearance_status']}"
        )
        assert asset["disposition_status"] == "AWARDED_TRANSFER", (
            f"release runs from AWARDED_TRANSFER, got {asset['disposition_status']}"
        )

        response = api.release_asset(asset["id"], {}, make_disposal_officer_headers())
        validate_error(response, ApiErrorId.ERR_SANITIZATION_NOT_CERTIFIED)

        after = read_asset(asset["id"])
        assert_surplus_asset(after)
        assert after["disposition_status"] == "AWARDED_TRANSFER", (
            f"the refused release moves nothing, got {after['disposition_status']}"
        )
        assert after["released_at"] is None, (
            f"released_at stays null after a refusal, got {after['released_at']}"
        )
        assert after["odometer_disclosure_reading"] is None, (
            "the refused release stores no disclosure, got "
            f"{after['odometer_disclosure_reading']}"
        )
        assert after["lien_release_reference"] is None, (
            "the refused release stores no lien reference, got "
            f"{after['lien_release_reference']}"
        )
        assert after["version"] == asset["version"], (
            "a refused operation applies none of its hops, so version is "
            f"unchanged at {asset['version']}, got {after['version']}"
        )

    def test_release_of_uncertified_data_bearing_asset_reports_sanitization_gate(
        self, api
    ):
        """PRD §3.8: "A data-bearing asset that is not `CLEARED` is refused with `ERR_SANITIZATION_NOT_CERTIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_sanitization_gate_outranks_odometer_disclosure
        """
        scenario = setup_acknowledged_transfer_order(
            kind="it_equipment",
            asset_overrides={"is_data_bearing": True},
        )
        asset = scenario["asset"]

        assert asset["category"] == "IT_EQUIPMENT", (
            "this control carries no odometer or lien obligation"
        )
        assert asset["lien_holder_name"] is None, (
            "the sanitisation gate must be the only violated gate here"
        )

        response = api.release_asset(asset["id"], {}, make_disposal_officer_headers())
        validate_error(response, ApiErrorId.ERR_SANITIZATION_NOT_CERTIFIED)

    def test_release_after_sanitization_reports_odometer_disclosure(self, api):
        """PRD §3.8: "From `REQUIRED_PENDING`, a verified certificate that completes every required `cert_type` moves the asset to `CLEARED`; a verified certificate that still leaves a required type uncovered leaves the asset at `REQUIRED_PENDING`."
        PRD §3.8: "A `VEHICLE` requires an `odometer_disclosure_reading` that is present and at or above the asset's recorded `odometer_reading`, together with a non-empty `title_recipient_name`, and is otherwise refused with `ERR_ODOMETER_DISCLOSURE_REQUIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_sanitization_gate_outranks_odometer_disclosure
        """
        scenario = self._acknowledged_encumbered_vehicle()
        asset = scenario["asset"]

        certify_clearance(asset["id"], cert_type="DATA_SANITIZATION", method="DEGAUSS")
        cleared = read_asset(asset["id"])
        assert cleared["clearance_status"] == "CLEARED", (
            "the single required cert_type is now covered by a verified "
            f"certificate, got {cleared['clearance_status']}"
        )

        response = api.release_asset(asset["id"], {}, make_disposal_officer_headers())
        validate_error(response, ApiErrorId.ERR_ODOMETER_DISCLOSURE_REQUIRED)

        after = read_asset(asset["id"])
        assert after["disposition_status"] == "AWARDED_TRANSFER", (
            "with the sanitisation gate satisfied the next gate in order answers, "
            f"and still moves nothing; got {after['disposition_status']}"
        )

    def test_odometer_disclosure_below_the_recorded_reading_is_refused(self, api):
        """PRD §3.8: "A `VEHICLE` requires an `odometer_disclosure_reading` that is present and at or above the asset's recorded `odometer_reading`, together with a non-empty `title_recipient_name`, and is otherwise refused with `ERR_ODOMETER_DISCLOSURE_REQUIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_sanitization_gate_outranks_odometer_disclosure
        """
        scenario = self._acknowledged_encumbered_vehicle()
        asset = scenario["asset"]
        assert asset["odometer_reading"] == 184320, (
            f"expected the recorded reading 184320, got {asset['odometer_reading']}"
        )

        certify_clearance(asset["id"], cert_type="DATA_SANITIZATION", method="DEGAUSS")

        response = api.release_asset(
            asset["id"],
            {
                "odometer_disclosure_reading": 184000,
                "title_recipient_name": "City of Cedar Park",
                "lien_release_reference": "CCU-REL-2026-0413",
            },
            make_disposal_officer_headers(),
        )
        validate_error(response, ApiErrorId.ERR_ODOMETER_DISCLOSURE_REQUIRED)

        after = read_asset(asset["id"])
        assert after["disposition_status"] == "AWARDED_TRANSFER", (
            "a disclosure below the recorded reading is not a disclosure, so the "
            f"asset stays put; got {after['disposition_status']}"
        )

    def test_release_with_odometer_and_title_reports_lien_not_released(self, api):
        """PRD §3.8: "An asset carrying a non-null `lien_holder_name` requires a non-empty `lien_release_reference`, and is otherwise refused with `ERR_LIEN_NOT_RELEASED`."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_sanitization_gate_outranks_odometer_disclosure
        """
        scenario = self._acknowledged_encumbered_vehicle()
        asset = scenario["asset"]

        certify_clearance(asset["id"], cert_type="DATA_SANITIZATION", method="DEGAUSS")

        response = api.release_asset(
            asset["id"],
            {
                "odometer_disclosure_reading": 184355,
                "title_recipient_name": "City of Cedar Park",
            },
            make_disposal_officer_headers(),
        )
        validate_error(response, ApiErrorId.ERR_LIEN_NOT_RELEASED)

        after = read_asset(asset["id"])
        assert after["disposition_status"] == "AWARDED_TRANSFER", (
            "the lien gate is the last of the four and still blocks the release; "
            f"got {after['disposition_status']}"
        )
        assert after["odometer_disclosure_reading"] is None, (
            "the accepted odometer value is not persisted by a refused release, "
            f"got {after['odometer_disclosure_reading']}"
        )

    def test_release_with_complete_documentation_cascades_to_closure(self, api):
        """PRD §3.8: "A successful release stores `released_at` from the logical clock along with the supplied `odometer_disclosure_reading`, `lien_release_reference` and `title_recipient_name`, and moves the asset to `RELEASED`. From `AWARDED_TRANSFER`, a second hop caused by the asset leaving custody moves the asset's `ACKNOWLEDGED` `TransferOrder` to `COMPLETED` and, where the asset's `federal_source` is true, computes that order's `use_period_end_on` by adding the asset category's use-period months to the calendar date of the order's `acknowledged_at`, with the same day-of-month clamping described in §2.4 — the recipient inherits an obligation of its own, counted from when it accepted the paperwork rather than from when the property moved. A final hop bubbles upward exactly as destruction does: when every asset of the parent turn-in has reached a terminal disposition, the turn-in moves `ACCEPTED` → `CLOSED`. The asset's `version` increments by 1."
        PRD §3.2: "Whenever an operation leaves every one of an `ACCEPTED` turn-in's assets in a terminal `disposition_status` — that is, every asset is `RELEASED`, `RETAINED` or `DESTROYED` — the turn-in moves from `ACCEPTED` to `CLOSED` on the server's own initiative, its `appraised_total_cents` freezes at its then-current value, and its `version` increments by 1."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_sanitization_gate_outranks_odometer_disclosure
        """
        scenario = self._acknowledged_encumbered_vehicle()
        asset = scenario["asset"]
        order = scenario["transfer_order"]

        certify_clearance(asset["id"], cert_type="DATA_SANITIZATION", method="DEGAUSS")

        response = api.release_asset(
            asset["id"],
            {
                "odometer_disclosure_reading": 184355,
                "title_recipient_name": "City of Cedar Park",
                "lien_release_reference": "CCU-REL-2026-0413",
            },
            make_disposal_officer_headers(),
        )
        released = validate_success(response, 200)
        assert_surplus_asset(released)
        assert released["disposition_status"] == "RELEASED", (
            "with every gate satisfied the release completes; got "
            f"{released['disposition_status']}"
        )
        assert _instant(released["released_at"]) == _instant("2026-08-01T00:00:00Z"), (
            "released_at is stamped from the logical clock, got "
            f"{released['released_at']}"
        )
        assert released["odometer_disclosure_reading"] == 184355, (
            "the supplied disclosure is stored, got "
            f"{released['odometer_disclosure_reading']}"
        )
        assert released["lien_release_reference"] == "CCU-REL-2026-0413", (
            f"the lien reference is stored, got {released['lien_release_reference']}"
        )
        assert released["title_recipient_name"] == "City of Cedar Park", (
            f"the title recipient is stored, got {released['title_recipient_name']}"
        )

        assert read_transfer_order(order["id"])["status"] == "COMPLETED", (
            "the acknowledged order reaches COMPLETED as a consequence of release"
        )
        assert read_turn_in(scenario["turn_in"]["id"])["status"] == "CLOSED", (
            "the turn-in's only asset is now terminal, so the turn-in closes"
        )


# ─── The end-use certificate versus the deposit floor ─────────────────────


class TestEndUseCertificateOutranksDepositFloor:
    """A restricted lot with an overridden reserve of 500000 requires both an
    unlapsed end-use certificate and a 50000-cent deposit; a bidder holding
    neither is answered with the certificate."""

    @staticmethod
    def _open_restricted_lot() -> dict:
        """An OPEN lot over a RESTRICTED_MILITARY asset with the reserve pinned by
        the officer at 500000, plus a bidder holding neither certificate nor
        deposit."""
        return setup_open_lot_with_bidder(
            kind="restricted",
            route="screening",
            asset_overrides={
                "acquisition_cost_cents": 870400,
                "demil_code": "B",
            },
            lot_overrides={"reserve_price_cents": 500000},
        )

    def test_restricted_bid_without_certificate_or_deposit_reports_certificate(
        self, api
    ):
        """PRD §3.6: "The gates then run in this exact order, and the order is exercised deliberately because several of them can be true at once."
        PRD §3.6: "Where the lot's asset has `is_restricted` true, the bidder must hold an unlapsed end-use certificate: `end_use_certificate_expires_on` must be non-null and on or after the logical clock's current date, otherwise `ERR_END_USE_CERTIFICATE_REQUIRED`."
        PRD §3.6: "Last, the bidder's `deposit_held_cents` must be at or above the lot's `required_deposit_cents`, otherwise `ERR_BID_DEPOSIT_INSUFFICIENT` (HTTP 402) — the deposit requirement is re-read from the lot on every bid, and it is satisfied out of held funds without consuming them."
        PRD §3.6: "Where the `DisposalOfficer` supplies a `reserve_price_cents` in the request, that value is stored verbatim without any formula being applied, and the lot records `reserve_source` as `OFFICER_OVERRIDE`; where the officer supplies nothing, the computed figure is stored and `reserve_source` is `COMPUTED`."
        PRD §2.12: "Implementations must not report a lower-precedence failure while a higher-precedence one is outstanding."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_end_use_certificate_outranks_deposit_insufficiency
        """
        scenario = self._open_restricted_lot()
        lot = scenario["lot"]
        bidder = scenario["bidder"]

        assert scenario["asset"]["is_restricted"] is True, (
            "the certificate gate only applies to a restricted asset"
        )
        assert lot["reserve_price_cents"] == 500000, (
            "the officer's figure is stored verbatim, got "
            f"{lot['reserve_price_cents']}"
        )
        assert lot["reserve_source"] == "OFFICER_OVERRIDE", (
            f"an officer-supplied reserve records its source, got {lot['reserve_source']}"
        )
        assert lot["required_deposit_cents"] == 50000, (
            "ten hundredths of 500000 is 50000, which is exactly the five hundred "
            f"dollar floor; got {lot['required_deposit_cents']}"
        )
        assert bidder["end_use_certificate_expires_on"] is None, (
            "the bidder holds no certificate in this scenario"
        )
        assert bidder["deposit_held_cents"] == 0, (
            "the bidder holds no deposit in this scenario"
        )

        response = api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], 500000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, ApiErrorId.ERR_END_USE_CERTIFICATE_REQUIRED)

        after_lot = read_lot(lot["id"])
        assert after_lot["bid_count"] == 0, (
            f"the refused bid persists nothing, got {after_lot['bid_count']}"
        )
        after_bidder = read_bidder(bidder["id"])
        assert after_bidder["deposit_held_cents"] == 0, (
            "the refused bid touches no deposit, got "
            f"{after_bidder['deposit_held_cents']}"
        )
        assert_deposit_custody_invariant(after_bidder)

    def test_restricted_bid_with_certificate_but_no_deposit_reports_deposit(self, api):
        """PRD §3.6: "Last, the bidder's `deposit_held_cents` must be at or above the lot's `required_deposit_cents`, otherwise `ERR_BID_DEPOSIT_INSUFFICIENT` (HTTP 402) — the deposit requirement is re-read from the lot on every bid, and it is satisfied out of held funds without consuming them."
        PRD §3.1: "A separate capability records the bidder's `end_use_certificate_expires_on`, the expiry of the end-use certificate that restricted property requires before it may be bid on."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_end_use_certificate_outranks_deposit_insufficiency
        """
        scenario = self._open_restricted_lot()
        lot = scenario["lot"]
        bidder = scenario["bidder"]

        certified = validate_success(
            api.set_bidder_end_use_certificate(
                bidder["id"], "2027-01-31", make_program_admin_headers()
            ),
            200,
        )
        assert_bidder(certified)
        assert certified["end_use_certificate_expires_on"] == "2027-01-31", (
            "the recorded expiry lies after the logical clock's current date, got "
            f"{certified['end_use_certificate_expires_on']}"
        )

        response = api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], 500000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BID_DEPOSIT_INSUFFICIENT)

        assert read_lot(lot["id"])["bid_count"] == 0, (
            "peeling off the certificate violation surfaces the deposit floor, "
            "and that refusal persists nothing either"
        )

    def test_restricted_bid_with_deposit_but_no_certificate_reports_certificate(
        self, api
    ):
        """PRD §3.6: "Where the lot's asset has `is_restricted` true, the bidder must hold an unlapsed end-use certificate: `end_use_certificate_expires_on` must be non-null and on or after the logical clock's current date, otherwise `ERR_END_USE_CERTIFICATE_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_end_use_certificate_outranks_deposit_insufficiency
        """
        scenario = self._open_restricted_lot()
        lot = scenario["lot"]
        bidder = scenario["bidder"]

        funded = lodge_deposit(bidder["id"], 50000)
        assert funded["deposit_held_cents"] == 50000, (
            f"the deposit is held, got {funded['deposit_held_cents']}"
        )

        response = api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], 500000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, ApiErrorId.ERR_END_USE_CERTIFICATE_REQUIRED)

        assert read_bidder(bidder["id"])["deposit_held_cents"] == 50000, (
            "with the deposit floor satisfied the certificate gate is the only "
            "violation left, and the held deposit is not consumed"
        )

    def test_restricted_bid_with_certificate_and_exact_deposit_is_accepted(self, api):
        """PRD §3.6: "Last, the bidder's `deposit_held_cents` must be at or above the lot's `required_deposit_cents`, otherwise `ERR_BID_DEPOSIT_INSUFFICIENT` (HTTP 402) — the deposit requirement is re-read from the lot on every bid, and it is satisfied out of held funds without consuming them."
        PRD §3.6: "Where the lot's asset has `is_restricted` true, the bidder must hold an unlapsed end-use certificate: `end_use_certificate_expires_on` must be non-null and on or after the logical clock's current date, otherwise `ERR_END_USE_CERTIFICATE_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_end_use_certificate_outranks_deposit_insufficiency
        """
        scenario = self._open_restricted_lot()
        lot = scenario["lot"]
        bidder = scenario["bidder"]

        get_success_data(
            api.set_bidder_end_use_certificate(
                bidder["id"], "2027-01-31", make_program_admin_headers()
            )
        )
        lodge_deposit(bidder["id"], 50000)

        response = api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], 500000),
            make_bidder_headers(bidder["id"]),
        )
        bid = validate_success(response, 201)
        assert_bid(bid)
        assert bid["status"] == "ACTIVE", (
            f"the accepted bid is created ACTIVE, got {bid['status']}"
        )

        after_lot = read_lot(lot["id"])
        assert after_lot["high_bid_cents"] == 500000, (
            f"high_bid_cents re-derives to 500000, got {after_lot['high_bid_cents']}"
        )
        assert after_lot["bid_count"] == 1, (
            f"bid_count re-derives to 1, got {after_lot['bid_count']}"
        )

        after_bidder = read_bidder(bidder["id"])
        assert after_bidder["deposit_held_cents"] == 50000, (
            "the deposit requirement is met out of held funds without consuming "
            f"them; got {after_bidder['deposit_held_cents']}"
        )
        assert after_bidder["deposit_applied_cents"] == 0, (
            "bidding applies nothing, got "
            f"{after_bidder['deposit_applied_cents']}"
        )
        assert_deposit_custody_invariant(after_bidder)
