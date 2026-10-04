"""Open-to-buy adjudication: provisional commitments, boundary admission, priority."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_lot,
    evaluate_lot,
    get_season,
    make_lot,
    open_season,
    setup_base,
    validate_error,
    validate_success,
)

BUYER = TEST_USERS["buyer_headers"]


class TestOpenToBuyBoundary:
    def test_admission_at_exact_forward_availability_succeeds(self, api):
        """PRD §3.1: "A candidate lot is admitted only if its landed cost is less
        than or equal to the relevant availability, and only after admission is
        the landed cost added to the corresponding commitment."

        Design: Difficulty/boundary_precision_check/otb_forward_admission_at_exact_cap_boundary
        """
        base = setup_base()
        open_season(base["season"])
        lot1 = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=6_000_000)
        evaluate_lot(lot1["id"], negotiated_price_cents=6_000_000)
        accept_lot(lot1["id"], base["season"]["id"])
        lot2 = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=14_700_000,
                        expected_sell_through_pct=0.9, estimated_unit_retail_cents=300_000)
        evaluate_lot(lot2["id"], negotiated_price_cents=14_700_000)
        accepted = accept_lot(lot2["id"], base["season"]["id"])
        assert accepted["status"] == "ACCEPTED"
        season = get_season(base["season"]["id"])
        assert season["committed_forward_cents"] == 21_000_000

    def test_admission_one_cent_over_availability_rejected(self, api):
        """PRD §3.2: "an `IMMEDIATE` lot whose landed cost exceeds forward
        availability is rejected with `ERR_OTB_FORWARD_EXCEEDED`".

        Design: Difficulty/boundary_precision_check/otb_forward_admission_at_exact_cap_boundary
        """
        base = setup_base()
        open_season(base["season"])
        lot1 = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=6_000_000)
        evaluate_lot(lot1["id"], negotiated_price_cents=6_000_000)
        accept_lot(lot1["id"], base["season"]["id"])
        lot3 = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=14_700_001,
                        expected_sell_through_pct=0.9, estimated_unit_retail_cents=300_000)
        evaluate_lot(lot3["id"], negotiated_price_cents=14_700_001)
        season = get_season(base["season"]["id"])
        res = api.accept_lot(lot3["id"], {"expected_season_version": season["version"]}, BUYER)
        validate_error(res, ApiErrorId.ERR_OTB_FORWARD_EXCEEDED)
        lot = api.get_lot(lot3["id"], BUYER).json()["data"]
        assert lot["status"] == "EVALUATED"
        season = get_season(base["season"]["id"])
        assert season["committed_forward_cents"] == 6_150_000


class TestAcceptPriority:
    def test_state_check_precedes_budget_admission(self, api):
        """PRD §3.2: "the state check (`ERR_INVALID_STATE`), then the OCC check on
        `expected_season_version` (`ERR_STALE_VERSION`, HTTP 412), then the expiry
        check (`ERR_OFFER_EXPIRED`), then vendor discretion (`ERR_VENDOR_DISCRETION`),
        then budget admission".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_lot_accept
        """
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=50_000_000,
                       expected_sell_through_pct=0.8, estimated_unit_retail_cents=1_000_000)
        season = get_season(base["season"]["id"])
        res = api.accept_lot(lot["id"], {"expected_season_version": season["version"]}, BUYER)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE"
        lot_after = api.get_lot(lot["id"], BUYER).json()["data"]
        assert lot_after["status"] == "OFFERED"
        season_after = get_season(base["season"]["id"])
        assert season_after["committed_forward_cents"] == 0

    def test_accept_from_offered_is_invalid_state(self, api):
        """PRD §3.2: "**Acceptance** (`EVALUATED → ACCEPTED`) is where open-to-buy
        discipline bites" — an OFFERED lot is not in the acceptance from-state.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_lot_accept
        """
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=100_000)
        season = get_season(base["season"]["id"])
        res = api.accept_lot(lot["id"], {"expected_season_version": season["version"]}, BUYER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        season_after = get_season(base["season"]["id"])
        assert season_after["version"] == season["version"]
