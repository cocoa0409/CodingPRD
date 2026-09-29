"""Licence fee assembly and the arithmetic of consecutive licence terms."""
from prd_bench_local_runner.testing import get_success_data, validate_error
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import BOARD_ADMIN, make_dealer_headers


class TestLicenceFeeAssembly:
    def test_tier_multiplier_scales_the_base_fee_alone(self, api):
        """PRD 3.2: "That base is multiplied by the dealership's county
        multiplier from §3.1 and the product is rounded half up to a whole cent;
        nothing else in the calculation is multiplied by the tier." PRD 3.2: "a
        line-make surcharge of 25,000 cents is levied for each line make named
        in `line_make_count`, with the surcharge as a whole capped at 100,000
        cents." PRD 3.2: "award 4,000 cents for each whole thousand square feet
        so counted, and cap the credit at 30,000 cents." A TIER_1 INITIAL
        application with two line makes and 12,500 square feet therefore quotes
        120000 x 1.25 + 50000 - 16000 = 184000, not the 192500 that scaling the
        surcharge-inclusive subtotal would give.

        Design: Difficulty/combinatorial_formula/license_fee_nested_caps_and_tier_multiplier
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(
            legal_name="Metro Aurora", county_tier="TIER_1", site_x_km=4, site_y_km=3)
        application = fx.open_application(
            dealer["id"], facility_sqft=12500, display_spaces=20,
            service_bays=6, line_make_count=2)

        submitted = get_success_data(
            api.submit_license_application(application["id"], make_dealer_headers(dealer["id"])))

        assert submitted["status"] == "SUBMITTED"
        assert submitted["fee_quoted_cents"] == 184000
        assert submitted["fee_quoted_cents"] != 192500
        assert submitted["deficiency_count"] == 0
        assert submitted["deficiency_codes"] == []

    def test_same_day_decision_reprices_to_the_identical_total(self, api):
        """PRD 3.2: "At decision time the reference date is the decision date, so
        any additional delinquent days that accrued while the board deliberated
        are billed; that result is written to `fee_total_cents`, and
        `fee_delta_cents` is `fee_total_cents` less `fee_quoted_cents`." An
        initial licence carries no late-renewal penalty, so the second
        evaluation of the same 184000-cent assembly cannot differ.

        Design: Difficulty/combinatorial_formula/license_fee_nested_caps_and_tier_multiplier
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(
            legal_name="Metro Aurora", county_tier="TIER_1", site_x_km=4, site_y_km=3)
        application = fx.open_application(
            dealer["id"], facility_sqft=12500, display_spaces=20,
            service_bays=6, line_make_count=2)
        fx.submit_application(application["id"], dealer["id"])

        decided = fx.decide_application(application["id"], "APPROVED")

        assert decided["decision_outcome"] == "APPROVED"
        assert decided["fee_total_cents"] == 184000
        assert decided["fee_delta_cents"] == 0
        assert decided["deficiency_count"] == 0

        after = fx.read_dealer(dealer["id"])
        assert after["license_status"] == "LICENSED"
        assert after["license_effective_on"] == "2026-09-01"
        assert after["license_expires_on"] == "2028-08-30"


def _licensed_then_lapsed_dealer(legal_name, site_x_km):
    """Licence a dealership on 2026-09-01 so its term expires 2028-08-30."""
    dealer = fx.create_dealer(legal_name=legal_name, site_x_km=site_x_km, site_y_km=0)
    fx.license_dealer(dealer["id"])
    return fx.read_dealer(dealer["id"])


def _open_renewal(dealer_id, requested_term_start_on):
    """Open a RENEWAL draft for a dealership, as the dealership's own act."""
    return get_success_data(api_client.create_license_application(
        f.license_application_payload(
            dealer_id, application_type="RENEWAL",
            requested_term_start_on=requested_term_start_on),
        make_dealer_headers(dealer_id),
    ))


class TestRenewalTermContiguity:
    def test_renewal_term_starting_inside_the_prior_term_is_refused(self, api):
        """PRD 3.2: "a renewal's `requested_term_start_on` must be exactly the
        day after the licensee's current `license_expires_on`, so consecutive
        terms abut precisely and never overlap; a start date that does not line
        up is refused with `ERR_TERM_NOT_CONTIGUOUS`, both at submission and
        again at decision." A start of 2028-08-25 would overlap a term running
        to 2028-08-30.

        Design: Difficulty/resource_temporal_overlap/renewal_term_must_abut_prior_expiry_no_overlap
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = _licensed_then_lapsed_dealer("Pine Aurora", 0)
        assert dealer["license_expires_on"] == "2028-08-30"
        swept = fx.set_clock("2028-09-02T00:00:00Z")
        assert swept["swept_dealer_count"] == 1
        assert fx.read_dealer(dealer["id"])["license_status"] == "EXPIRED"
        renewal = _open_renewal(dealer["id"], "2028-08-25")

        response = api.submit_license_application(
            renewal["id"], make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_TERM_NOT_CONTIGUOUS.value)

        after = fx.read_application(renewal["id"])
        assert after["status"] == "DRAFT"
        assert after["fee_quoted_cents"] is None
        assert fx.read_dealer(dealer["id"])["license_status"] == "EXPIRED"

    def test_renewal_term_leaving_a_gap_is_refused(self, api):
        """PRD 3.2: "so consecutive terms abut precisely and never overlap; a
        start date that does not line up is refused with
        `ERR_TERM_NOT_CONTIGUOUS`, both at submission and again at decision." A
        start of 2028-09-05 leaves five unlicensed days after 2028-08-30, and the
        rule is exact abutment rather than mere separation.

        Design: Difficulty/resource_temporal_overlap/renewal_term_must_abut_prior_expiry_no_overlap
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = _licensed_then_lapsed_dealer("Quarry Aurora", 3)
        fx.set_clock("2028-09-02T00:00:00Z")
        renewal = _open_renewal(dealer["id"], "2028-09-05")

        response = api.submit_license_application(
            renewal["id"], make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_TERM_NOT_CONTIGUOUS.value)

        after = fx.read_application(renewal["id"])
        assert after["status"] == "DRAFT"
        assert after["fee_quoted_cents"] is None

    def test_renewal_term_abutting_the_prior_expiry_is_licensed_retroactively(self, api):
        """PRD 3.2: "for a renewal it is the application's
        `requested_term_start_on`, which gives an `EXPIRED → LICENSED` renewal
        retroactive continuity with the term that just lapsed." PRD 3.2: "count
        the whole days from that prior expiry to the reference date, treat a
        negative count as zero, charge 5,000 cents per late day, and cap the
        penalty at 50,000 cents." Submitting on 2028-09-02 bills 3 late days
        (90000 + 25000 - 4000 + 15000 = 126000); deciding on 2028-09-07 bills 8
        (151000), so the delta is 25000.

        Design: Difficulty/resource_temporal_overlap/renewal_term_must_abut_prior_expiry_no_overlap
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = _licensed_then_lapsed_dealer("Ridge Aurora", 6)
        fx.set_clock("2028-09-02T00:00:00Z")
        renewal = _open_renewal(dealer["id"], "2028-08-31")

        submitted = get_success_data(
            api.submit_license_application(renewal["id"], make_dealer_headers(dealer["id"])))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["fee_quoted_cents"] == 126000

        fx.set_clock("2028-09-07T00:00:00Z")
        decided = get_success_data(api.decide_license_application(
            renewal["id"], f.application_decision_payload("APPROVED"), BOARD_ADMIN))
        assert decided["fee_total_cents"] == 151000
        assert decided["fee_delta_cents"] == 25000

        after = fx.read_dealer(dealer["id"])
        assert after["license_status"] == "LICENSED"
        assert after["license_effective_on"] == "2028-08-31"
        assert after["license_expires_on"] == "2030-08-30"
