"""Carrier onboarding, compliance gates, suspension and reinstatement."""
from test_helpers import (
    api_client as api,
    attest_insurance_payload,
    create_carrier_payload,
    make_carrier_headers,
    make_compliance_reviewer_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_carrier,
    set_clock,
    setup_board,
    setup_plain_carrier,
)


def _headers():
    return make_compliance_reviewer_headers()


class TestOnboardingStaircase:
    """Authorisation, insurance and safety are three ordered rungs."""

    def test_authority_verification_is_the_only_first_step(self):
        """PRD section 3.1: "The first rung is authority verification.  The
        reviewer attests that the docket has been checked; the carrier moves from
        `PENDING` to `AUTHORITY_VERIFIED`, `operating_authority_status` is set to
        `ACTIVE`, and `authority_verified_at` is stamped with the current logical
        clock."

        Design: Corner/state_machines/carrier_verify_authority_from_pending_is_the_only_first_step
        """
        set_clock("2026-09-20T00:00:00Z")
        carrier = setup_plain_carrier(units=0)
        assert carrier["status"] == "PENDING"
        assert carrier["operating_authority_status"] == "NONE"
        assert carrier["operational_risk_score"] == 100.0
        assert carrier["claims_clawback_count"] == 0
        assert carrier["certificate_reference"] is None

        verified = api.verify_authority(carrier["id"], _headers())
        assert verified.status_code == 200, verified.text
        data = verified.json()["data"]
        assert data["status"] == "AUTHORITY_VERIFIED"
        assert data["operating_authority_status"] == "ACTIVE"
        assert data["authority_verified_at"] is not None
        assert data["version"] == carrier["version"] + 1

    def test_a_second_authority_call_from_the_verified_rung_is_undeclared(self):
        """PRD section 2.6: "Where a working resource is in a state from which the requested transition is simply not declared, the request is refused as an invalid state rather than as a business-rule failure, and a request aimed at a resource that has already reached one of its terminal states is refused as `ERR_ALREADY_TERMINAL` (HTTP 409) rather than being re-examined against the rules of the state it left."

        Design: Corner/state_machines/carrier_verify_authority_from_pending_is_the_only_first_step
        """
        set_clock("2026-09-20T00:00:00Z")
        carrier = setup_plain_carrier(units=0)
        api.verify_authority(carrier["id"], _headers())
        again = api.verify_authority(carrier["id"], _headers())
        assert again.status_code == 409, again.text
        assert read_carrier(carrier["id"])["status"] == "AUTHORITY_VERIFIED"


class TestInsuranceFloors:
    """Liability and cargo coverage have separate, independent minima."""

    def test_cargo_coverage_below_the_floor_is_reported_as_its_own_error(self):
        """PRD section 3.1: "the auto liability limit must be at least 75,000,000
        cents, or `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` (HTTP 409); and the cargo
        coverage limit must be at least 100,000,000 cents, or
        `ERR_CARGO_COVERAGE_BELOW_MINIMUM` (HTTP 409)."

        Design: Corner/errors/cargo_coverage_below_minimum_returns_cargo_coverage_below_minimum
        """
        set_clock("2026-09-20T00:00:00Z")
        carrier = setup_plain_carrier(units=0)
        api.verify_authority(carrier["id"], _headers())

        rejected = api.attest_insurance(
            carrier["id"],
            attest_insurance_payload(cargo_coverage_limit_cents=90000000),
            _headers())
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_CARGO_COVERAGE_BELOW_MINIMUM"
        assert rejected.json()["data"]["error_id"] != "ERR_INSURANCE_LIMIT_BELOW_MINIMUM"
        assert read_carrier(carrier["id"])["status"] == "AUTHORITY_VERIFIED"

    def test_an_insurance_floor_at_the_boundary_is_accepted(self):
        """PRD section 3.1: "The reviewer supplies `insurance_expires_at`, `insurance_liability_limit_cents`, `cargo_coverage_limit_cents`, and an optional `certificate_reference`; a carrier file that reached this rung with no certificate on hand is not a dead end, because this step is exactly how a certificate gets recorded. Three conditions must hold together: the expiry must be strictly later than the logical clock, or the answer is `ERR_INSURANCE_EXPIRED` (HTTP 409); the auto liability limit must be at least 75,000,000 cents, or `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` (HTTP 409); and the cargo coverage limit must be at least 100,000,000 cents, or `ERR_CARGO_COVERAGE_BELOW_MINIMUM` (HTTP 409)."

        Design: Corner/errors/cargo_coverage_below_minimum_returns_cargo_coverage_below_minimum
        """
        set_clock("2026-09-20T00:00:00Z")
        carrier = setup_plain_carrier(units=0)
        api.verify_authority(carrier["id"], _headers())
        accepted = api.attest_insurance(
            carrier["id"],
            attest_insurance_payload(cargo_coverage_limit_cents=100000000,
                                     insurance_liability_limit_cents=75000000),
            _headers())
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["status"] == "INSURANCE_ON_FILE"

    def test_an_expiring_certificate_flips_the_comparison_at_the_instant(self):
        """PRD section 3.1: "Three conditions must hold together: the expiry must be strictly later than the logical clock, or the answer is `ERR_INSURANCE_EXPIRED` (HTTP 409); the auto liability limit must be at least 75,000,000 cents, or `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` (HTTP 409); and the cargo coverage limit must be at least 100,000,000 cents, or `ERR_CARGO_COVERAGE_BELOW_MINIMUM` (HTTP 409)."
        PRD section 3.10: "A reinstate is available to an operator once insurance is valid
        again — the expiry must be strictly later than the clock and both
        the liability and cargo limits must still meet the 75,000,000-
        and 100,000,000-cent floors of §3.1."

        Design: Corner/errors/insurance_just_expired_returns_insurance_expired_at_the_instant
        """
        set_clock("2026-09-30T23:59:59Z")
        carrier = setup_plain_carrier(units=1)
        api.verify_authority(carrier["id"], _headers())
        early = api.attest_insurance(
            carrier["id"],
            attest_insurance_payload(insurance_expires_at="2026-10-01T00:00:00Z"),
            _headers())
        assert early.status_code == 200, early.text
        assert early.json()["data"]["status"] == "INSURANCE_ON_FILE"
        api.verify_safety(carrier["id"], {"safety_score": 72.0}, _headers())
        assert read_carrier(carrier["id"])["status"] == "VERIFIED"

        # One second later the certificate has reached the clock instant, so the
        # carrier suspends on that read; reinstatement is then refused because the
        # expiry is no longer strictly later than the clock.
        set_clock("2026-10-01T00:00:00Z")
        assert read_carrier(carrier["id"])["status"] == "SUSPENDED"
        revoked = api.reinstate_carrier(carrier["id"], make_platform_admin_headers())
        assert revoked.status_code == 409, revoked.text
        assert revoked.json()["data"]["error_id"] == "ERR_INSURANCE_EXPIRED"


class TestSafetyRung:
    """Safety verification needs a passing score and a unit on file."""

    def test_safety_verification_without_a_unit_is_refused(self):
        """PRD section 3.1: "The reviewer may supply a `safety_score` in the request or fall back on the one already on file; either way the score must be at or below 80.0, or the answer is `ERR_SAFETY_SCORE_TOO_LOW` (HTTP 409). Separately, the carrier must already have at least one equipment unit on file in `AVAILABLE` status, or the answer is `ERR_NO_EQUIPMENT_ON_FILE` (HTTP 409) — the platform will not verify a carrier that cannot actually haul anything."

        Design: Corner/state_machines/carrier_verify_safety_without_equipment_returns_no_equipment_on_file
        """
        set_clock("2026-09-20T00:00:00Z")
        carrier = setup_plain_carrier(units=0)
        api.verify_authority(carrier["id"], _headers())
        api.attest_insurance(carrier["id"], attest_insurance_payload(), _headers())

        rejected = api.verify_safety(carrier["id"], {"safety_score": 72.0}, _headers())
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_NO_EQUIPMENT_ON_FILE"
        assert read_carrier(carrier["id"])["status"] == "INSURANCE_ON_FILE"

    def test_the_safety_ceiling_is_inclusive_at_eighty(self):
        """PRD section 3.1: "either way the score must be at or below 80.0, or the
        answer is `ERR_SAFETY_SCORE_TOO_LOW` (HTTP 409)."

        Design: Corner/errors/safety_score_above_eighty_returns_safety_score_too_low
        """
        set_clock("2026-09-20T00:00:00Z")
        passing = setup_plain_carrier(units=1)
        api.verify_authority(passing["id"], _headers())
        api.attest_insurance(passing["id"], attest_insurance_payload(), _headers())
        accepted = api.verify_safety(passing["id"], {"safety_score": 80.0}, _headers())
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["status"] == "VERIFIED"

        failing = setup_plain_carrier(units=1)
        api.create_equipment(
            {"carrier_id": failing["id"], "equipment_type": "DRY_VAN",
             "unit_number": "SAFE-1", "driver_name": "M. Pham"},
            make_carrier_headers(failing["id"]))
        api.verify_authority(failing["id"], _headers())
        api.attest_insurance(failing["id"], attest_insurance_payload(), _headers())
        rejected = api.verify_safety(failing["id"], {"safety_score": 80.1}, _headers())
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_SAFETY_SCORE_TOO_LOW"
        assert read_carrier(failing["id"])["status"] == "INSURANCE_ON_FILE"


class TestDuplicateDocketNumber:
    """The MC number is unique across the platform."""

    def test_a_duplicate_mc_number_is_refused_and_creates_no_row(self):
        """PRD section 3.1: "The `mc_number` is the carrier's identity on the docket
        and must be unique across the whole platform: a second carrier presenting a
        docket number already on file is refused with `ERR_DUPLICATE_MC_NUMBER`
        (HTTP 400)."

        Design: Corner/errors/duplicate_mc_number_returns_duplicate_mc_number
        """
        set_clock("2026-09-20T00:00:00Z")
        api.create_carrier(create_carrier_payload("100001"), _headers())

        duplicate = api.create_carrier(
            create_carrier_payload("100001", legal_name="Twin Docket Freight Inc"), _headers())
        assert duplicate.status_code == 400, duplicate.text
        assert duplicate.json()["data"]["error_id"] == "ERR_DUPLICATE_MC_NUMBER"

        distinct = api.create_carrier(
            create_carrier_payload("100002", legal_name="Twin Docket Freight Inc"), _headers())
        assert distinct.status_code == 201, distinct.text

        pending = api.list_carriers(_headers(), {"status": "PENDING"})
        assert pending.status_code == 200
        dockets = sorted(row["mc_number"] for row in pending.json()["data"])
        assert dockets == ["100001", "100002"], (
            "the refused duplicate creates no row, so both live carriers remain")
        assert distinct.json()["data"]["id"] in [row["id"] for row in pending.json()["data"]]


class TestSuspensionAndReinstatement:
    """Suspension unwinds live bookings; reinstatement restores the file."""

    def test_manual_suspension_records_the_reason_code(self):
        """PRD section 3.10: "The manual route is an operator suspension with a
        supplied `reason_code`, which records that code as the
        `suspension_reason`."

        Design: Corner/state_machines/carrier_verify_authority_from_pending_is_the_only_first_step
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        suspended = api.suspend_carrier(board["carrier_id"], {"reason_code": "RISK_REVIEW"},
                                       make_platform_admin_headers())
        assert suspended.status_code == 200, suspended.text
        assert suspended.json()["data"]["status"] == "SUSPENDED"
        assert suspended.json()["data"]["suspension_reason"] == "RISK_REVIEW"

    def test_reinstatement_clears_the_reason_and_restamps_attestation(self):
        """PRD section 3.10: "Every booking of that carrier in `PENDING_APPOINTMENT` or `IN_TRANSIT` status becomes `CANCELLED`; each such booking's equipment unit returns to `AVAILABLE`; and each such booking's load returns to `UNCOVERED` so the shipper may repost it. A reinstate is available to an operator once insurance is valid again — the expiry must be strictly later than the clock and both the liability and cargo limits must still meet the 75,000,000- and 100,000,000-cent floors of §3.1 — and it returns the carrier to `INSURANCE_ON_FILE`, clears `suspension_reason` to null, and re-stamps `insurance_attested_at`."
        PRD section 3.10: "A reinstate is available to an operator once insurance is valid
        again — the expiry must be strictly later than the clock and both
        the liability and cargo limits must still meet the 75,000,000-
        and 100,000,000-cent floors of §3.1 — and it returns the carrier
        to `INSURANCE_ON_FILE`, clears `suspension_reason` to null, and
        re-stamps `insurance_attested_at`."

        Design: Corner/errors/insurance_just_expired_returns_insurance_expired_at_the_instant
        """
        board = setup_board(units=1)
        carrier_id = board["carrier_id"]
        set_clock("2026-10-05T00:00:00Z")
        suspended = api.suspend_carrier(carrier_id, {"reason_code": "RISK_REVIEW"},
                                        make_platform_admin_headers())
        assert suspended.status_code == 200, suspended.text
        assert read_carrier(carrier_id)["status"] == "SUSPENDED"

        reinstated = api.reinstate_carrier(carrier_id, make_platform_admin_headers())
        assert reinstated.status_code == 200, reinstated.text
        data = reinstated.json()["data"]
        assert data["status"] == "INSURANCE_ON_FILE"
        assert data["suspension_reason"] is None
        assert data["insurance_attested_at"] is not None


class TestShipperSuspension:
    """An operator may suspend a shipper of record."""

    def test_suspending_a_shipper_flips_its_status(self):
        """PRD section 2.8: "An operator may suspend a shipper with a supplied
        `reason_code`, which flips its status to `SUSPENDED` and stops its posted
        loads accepting bookings."

        Design: Corner/entities/shipper_create_returns_every_declared_field_and_starts_active
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        suspended = api.suspend_shipper(board["shipper_id"], {"reason_code": "FRAUD_REVIEW"},
                                        make_platform_admin_headers())
        assert suspended.status_code == 200, suspended.text
        assert suspended.json()["data"]["status"] == "SUSPENDED"
        assert suspended.json()["data"]["version"] == board["shipper"]["version"] + 1

        stored = api.get_shipper(
            board["shipper_id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert stored["status"] == "SUSPENDED"


class TestEquipmentRoster:
    """A unit moves between AVAILABLE and IN_SHOP unless it is committed."""

    def test_a_unit_carrying_a_live_booking_cannot_go_to_the_shop(self):
        """PRD section 3.7: "a unit can be moved between `AVAILABLE` and `IN_SHOP`,
        except that a move to `IN_SHOP` is refused while that unit still carries a
        non-terminal booking."

        Design: Corner/entities/carrier_equipment_listing_paginates_and_reports_total_count
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)
        booked = api.create_booking(
            {"load_id": load["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": load["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert booked.status_code == 201, booked.text

        refused = api.set_equipment_status(board["equipment"][0]["id"], "IN_SHOP",
                                           make_carrier_headers(board["carrier_id"]))
        assert refused.status_code >= 400, (
            "a committed unit must not be moved into the shop while it carries a live booking")

    def test_an_uncommitted_unit_can_move_to_the_shop_and_back(self):
        """PRD section 3.7: "A carrier's equipment roster is registered alongside this: each unit is recorded with its `carrier_id`, its `equipment_type` and `unit_number`, and the `driver_name` assigned to it, and a unit can be moved between `AVAILABLE` and `IN_SHOP`, except that a move to `IN_SHOP` is refused while that unit still carries a non-terminal booking."

        Design: Corner/entities/carrier_equipment_listing_paginates_and_reports_total_count
        """
        board = setup_board(units=2)
        unit = board["equipment"][1]
        headers = make_carrier_headers(board["carrier_id"])
        moved = api.set_equipment_status(unit["id"], "IN_SHOP", headers)
        assert moved.status_code == 200, moved.text
        assert moved.json()["data"]["status"] == "IN_SHOP"
        back = api.set_equipment_status(unit["id"], "AVAILABLE", headers)
        assert back.status_code == 200, back.text
        assert back.json()["data"]["status"] == "AVAILABLE"


def _posted_load(board):
    created = api.create_load(
        {
            "shipper_id": board["shipper_id"],
            "origin_facility_id": board["origin_facility_id"],
            "destination_facility_id": board["destination_facility_id"],
            "pricing_mode": "SPOT",
            "equipment_type": "DRY_VAN",
            "commodity": "GENERAL",
            "weight_lbs": 40000,
            "declared_cargo_value_cents": 5000000,
            "distance_miles": 1200,
            "pickup_window_start": "2026-10-05T08:00:00Z",
            "pickup_window_end": "2026-10-05T12:00:00Z",
            "delivery_deadline": "2026-10-07T18:00:00Z",
            "market_band": "BALANCED",
        },
        make_shipper_headers(board["shipper_id"]),
    )
    assert created.status_code == 201, created.text
    load_id = created.json()["data"]["id"]
    posted = api.post_load(load_id, make_shipper_headers(board["shipper_id"]))
    assert posted.status_code == 200, posted.text
    quote = api.list_load_rate_quotes(
        load_id, make_shipper_headers(board["shipper_id"])).json()["data"][-1]
    return posted.json()["data"], quote