"""Corner coverage - integer floors, clamps and input-set filtering."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import ADMIN_HEADERS, BANKER_HEADERS, SALES_HEADERS


def test_a_fractional_capture_rate_is_floored_not_rounded(api):
    """Two captured deals out of three funded units floors to 6666 basis points.

    PRD §2.6: "The `capture_rate_bps` value is the affiliated count multiplied by ten
    thousand, divided by the funded count, using floor division — integer basis points
    with no rounding."
    PRD §2.9: "Wherever a ratio must be converted to an integer, the system uses floor
    division and never rounds half-up."
    Design: Corner/calculations/capture_rate_realization_integer_floor_at_repeat
    """
    world = fixtures.seed_reference_data(api, committed_units=10)

    for index, lender in enumerate(
        ("AFFILIATED_LENDER", "AFFILIATED_LENDER", "THIRD_PARTY_LENDER"), start=1
    ):
        fixtures.close_deal(api, world=world, lender_entity_code=lender, suffix=str(index))

    community = fixtures.read_community(api, world["cm1"])
    assert community["funded_units"] == 3, community["funded_units"]
    assert community["affiliated_units"] == 2, community["affiliated_units"]
    assert community["capture_rate_bps"] == 6666, (
        f"6666.67 floors to 6666, proving floor rather than round, "
        f"got {community['capture_rate_bps']}"
    )
    assert community["capture_rate_bps"] != 6667, (
        "the rounded reading is expressly not the contract"
    )


def test_a_zero_debt_application_opens_with_no_debt_ratio(api):
    """Debt of zero leaves dti_bps at zero and every component of the score intact.

    PRD §3.3: "The same rule simultaneously computes `dti_bps` as monthly debt
    multiplied by ten thousand, floored over qualifying income".
    PRD §2.9: "The one weighted score in the system, `qualification_score`, is an
    integer clamped into the closed interval from 300 to 850, and every intermediate
    component of that score is floored before it is combined."
    Design: Corner/calculations/qualification_score_clamps_at_the_850_ceiling
    """
    world = fixtures.build_deal(
        api, qualify=False, qualifying_income_cents=2_000_000, monthly_debt_cents=0
    )
    application = fixtures.read_application(api, world["la1"])

    assert application["dti_bps"] == 0, (
        f"no obligations means no ratio, got {application['dti_bps']}"
    )
    assert application["qualification_score"] <= 850, (
        f"the score never leaves its declared ceiling, got {application['qualification_score']}"
    )
    assert application["qualification_score"] >= 300, application["qualification_score"]


def test_a_new_application_opens_on_the_default_underwriting_and_waiver_postures(api):
    """An application opens SUBMITTED with an untouched waiver track and the joined string.

    PRD §3.3: "The new application opens in `application_status` `SUBMITTED` with
    `lock_waiver_status` `NOT_REQUESTED`, and the composite `uw_precedence` string
    reads `SUBMITTED_NOT_REQUESTED`."
    PRD §3.3: "The `uw_precedence` field is the canonical concatenation of the two, an
    underscore-joined `{application_status}_{lock_waiver_status}` string".
    Design: Corner/calculations/qualification_score_clamps_at_the_850_ceiling
    """
    world = fixtures.build_deal(api, qualify=False)

    application = fixtures.read_application(api, world["la1"])
    assert application["lock_waiver_status"] == "NOT_REQUESTED", (
        application["lock_waiver_status"]
    )
    assert application["uw_precedence"] == "SUBMITTED_NOT_REQUESTED", (
        application["uw_precedence"]
    )
    assert application["application_status"] == "SUBMITTED", application["application_status"]


def test_the_debt_ratio_is_a_plain_floored_ratio_with_no_ceiling(api):
    """Debt above income yields a ratio above ten thousand, because only the score clamps.

    PRD §3.3: "The same rule simultaneously computes `dti_bps` as monthly debt
    multiplied by ten thousand, floored over qualifying income; that ratio is
    *provisional* while the application sits in `SUBMITTED` and is recomputed on every
    read".
    PRD §2.9: "dividing a debt figure by an income figure to obtain basis points ...
    floor their quotient to a whole number of basis points or cents."
    Design: Corner/calculations/qualification_score_floor_applies_above_ceiling_inputs_only
    """
    world = fixtures.build_deal(
        api, qualify=False, qualifying_income_cents=2_000_000, monthly_debt_cents=3_000_000
    )
    application = fixtures.read_application(api, world["la1"])

    assert application["dti_bps"] == 15000, (
        f"(3_000_000 * 10000) // 2_000_000 is a plain floored ratio, "
        f"got {application['dti_bps']}"
    )
    assert application["qualification_score"] >= 300, (
        f"the score is clamped into its interval while the ratio is not, "
        f"got {application['qualification_score']}"
    )


def test_the_score_never_falls_below_its_declared_floor_on_heavy_debt(api):
    """The debt component floors at zero, so the score holds at or above 300.

    PRD §3.3: "A debt-service component is then subtracted — specifically, monthly debt
    multiplied by 250, floored over qualifying income, and that quotient subtracted from
    250, but never allowed to drop below zero".
    PRD §2.9: "The one weighted score in the system, `qualification_score`, is an integer
    clamped into the closed interval from 300 to 850".
    Design: Corner/calculations/qualification_score_floor_applies_above_ceiling_inputs_only
    """
    world = fixtures.build_deal(
        api, qualify=False, qualifying_income_cents=1_000_000, monthly_debt_cents=9_000_000
    )
    application = fixtures.read_application(api, world["la1"])

    assert application["qualification_score"] >= 300, (
        f"the clamp holds the score at its floor, got {application['qualification_score']}"
    )
    assert application["dti_bps"] == 90000, (
        f"the ratio itself is unbounded, got {application['dti_bps']}"
    )


def test_a_booked_buydown_record_contributes_its_recognised_cost_to_the_community(api):
    """While the record is BOOKED the community recognises its gross buydown.

    PRD §2.6: "The `incentive_spend_cents` value is the sum of `allowed_buydown_cost_cents`
    across buydown cost records that are in `BOOKED` status and whose owning contract's
    home site belongs to the community."
    PRD §3.7: "Once the contract has closed, the credit depends on how long the record
    was held before closing".
    Design: Corner/calculations/buydown_recognition_input_set_excludes_reversed_records
    """
    world = fixtures.setup_contract_with_rate_buydown(
        api, buydown_cents=6_000_000, gross_buydown_cents=300_000,
        target_state="APPROVED", with_buydown_record=True,
    )
    record = fixtures.read_buydown_record(api, world["bd1"])
    assert record["record_status"] == "BOOKED", (
        f"approval books the record, got {record['record_status']}"
    )

    community = fixtures.read_community(api, world["cm1"])
    assert community["incentive_spend_cents"] == 300_000, (
        f"the booked record contributes its whole recognised cost here, "
        f"got {community['incentive_spend_cents']}"
    )


def test_a_reversed_buydown_record_drops_out_of_the_community_spend(api):
    """The cancel reverses the record and the community's recognised spend falls to zero.

    PRD §2.6: "Only `BOOKED` records contribute: records in `DRAFT` status and records
    in `REVERSED` status are both excluded, the latter even though a reversed record's
    own `allowed_buydown_cost_cents` has been zeroed."
    PRD §3.7: "When the owning contract is cancelled, the record moves to the terminal
    `REVERSED` status from either `DRAFT` or `BOOKED`, its recognized cost is zeroed,
    and the community spend is recomputed on the `BOOKED` path."
    Design: Corner/calculations/buydown_recognition_input_set_excludes_reversed_records
    """
    world = fixtures.setup_contract_with_rate_buydown(
        api, buydown_cents=6_000_000, gross_buydown_cents=300_000,
        target_state="APPROVED", with_buydown_record=True,
    )
    assert fixtures.read_community(api, world["cm1"])["incentive_spend_cents"] == 300_000

    fixtures.drive_cancel(api, world, "RATE_SHOCK")

    record = fixtures.read_buydown_record(api, world["bd1"])
    assert record["record_status"] == "REVERSED", record["record_status"]
    assert record["allowed_buydown_cost_cents"] == 0, record["allowed_buydown_cost_cents"]

    community = fixtures.read_community(api, world["cm1"])
    assert community["incentive_spend_cents"] == 0, (
        f"the reversed record contributes nothing at all, "
        f"got {community['incentive_spend_cents']}"
    )