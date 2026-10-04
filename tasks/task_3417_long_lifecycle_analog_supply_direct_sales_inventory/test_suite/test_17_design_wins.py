"""Design wins: revenue-tail dual profiles, four-year completion, activation gates."""
from test_helpers import (
    DESIGN_WIN_ONE_YEAR_CLOCK,
    TEST_USERS,
    ApiErrorId,
    create_design_win_payload,
    create_reference_design_payload,
    get_part,
    make_customer,
    make_eol_notice,
    make_part,
    set_clock,
    validate_error,
    validate_success,
)

FIELD = TEST_USERS["field_engineer_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]

START = "2027-01-01T00:00:00Z"


def _make_win(api, part, cust, title):
    rd = validate_success(
        api.create_reference_design(
            create_reference_design_payload(
                title=title, featured_part_number=part["part_number"]
            ),
            FIELD,
        ),
        201,
    )
    validate_success(api.publish_reference_design(rd["id"], FIELD), 200)
    win = validate_success(
        api.create_design_win(
            create_design_win_payload(rd["id"], cust["id"], part["id"],
                                      start_date=START),
            FIELD,
        ),
        201,
    )
    validate_success(api.activate_design_win(win["id"], FIELD), 200)
    return win


class TestDesignWins:
    def test_design_win_tail_ramped_vs_flat_recognition(self, api):
        """PRD §3.8: "Under the ramped profile, year one through year four recognize
        20%, 40%, 25%, and 15% of `expected_lifetime_revenue_cents` respectively;
        under the flat profile, each year recognizes 25%."
        PRD §3.8: "The canonical `recognized_revenue_cents` is the ramped figure when
        the part's `automotive_grade` is true and the flat figure otherwise."
        PRD §3.8: "Let the years elapsed be the number of complete twelve-month
        anniversaries of `start_date` at or before the current logical-clock reading
        — zero until the first anniversary."

        Design: Difficulty/dual_variant_calc/design_win_tail_ramped_vs_flat_recognition
        """
        part_a = make_part(part_number="TPS7A4700RGWR-A", package_family="VQFN",
                           automotive_grade=True)
        part_i = make_part(part_number="TPS7A4700RGWR-I", package_family="VQFN",
                           automotive_grade=False)
        cust = make_customer(name="Powertrain Systems Inc", tier="KEY",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        win_a = _make_win(api, part_a, cust, "ADAS power tree")
        win_i = _make_win(api, part_i, cust, "Factory IO supply")

        set_clock(DESIGN_WIN_ONE_YEAR_CLOCK)  # exactly one anniversary elapsed

        wa = validate_success(api.get_design_win(win_a["id"], FIELD), 200)
        assert wa["recognized_ramped_cents"] == 200000
        assert wa["recognized_flat_cents"] == 250000
        assert wa["recognized_revenue_cents"] == 200000  # automotive -> ramped
        wi = validate_success(api.get_design_win(win_i["id"], FIELD), 200)
        assert wi["recognized_ramped_cents"] == 200000
        assert wi["recognized_flat_cents"] == 250000
        assert wi["recognized_revenue_cents"] == 250000  # non-automotive -> flat
        assert wa["recognized_ramped_cents"] != wa["recognized_flat_cents"]
        assert wi["recognized_ramped_cents"] != wi["recognized_flat_cents"]

    def test_recognition_zero_before_first_anniversary(self, api):
        """PRD §3.8: "Let the years elapsed be the number of complete twelve-month
        anniversaries of `start_date` at or before the current logical-clock reading
        — zero until the first anniversary."
        PRD §3.8: "with its recognized-revenue fields computed (zero before the first
        anniversary, per the recognition rule below)".

        Design: Difficulty/dual_variant_calc/design_win_tail_ramped_vs_flat_recognition
        """
        part = make_part(part_number="OPA197IDR", package_family="SOIC")
        cust = make_customer(name="Early Tail Co", tier="KEY",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        # Default clock 2026-09-01 precedes start_date 2027-01-01: zero anniversaries.
        win = _make_win(api, part, cust, "Preamp front end")
        assert win["recognized_ramped_cents"] == 0
        assert win["recognized_flat_cents"] == 0
        assert win["recognized_revenue_cents"] == 0

    def test_design_win_completes_at_four_year_anniversary(self, api):
        """PRD §2.5: "An `ACTIVE` design win moves to `COMPLETED` once the clock
        reaches the win's `start_date` plus four years."
        PRD §3.8: "the fourth year's amount absorbs the remainder — the expectation
        minus the sum of the first three rounded years."

        Design: Corner/state_machines/design_win_completes_at_four_year_anniversary
        """
        part = make_part(part_number="OPA192IDR", package_family="SOIC",
                         process_technology="CMOS_180NM")
        cust = make_customer(name="Tail Co", tier="KEY",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        win = _make_win(api, part, cust, "Scanner AFE")

        set_clock("2031-01-01T00:00:00Z")  # start_date + 4 years exactly
        after = validate_success(api.get_design_win(win["id"], FIELD), 200)
        assert after["status"] == "COMPLETED"
        assert after["recognized_ramped_cents"] == 1_000_000
        assert after["recognized_flat_cents"] == 1_000_000
        assert after["recognized_revenue_cents"] == 1_000_000

    def test_design_win_activate_draft_reference_design_rejected(self, api):
        """PRD §3.8: "It requires the referenced design to be `PUBLISHED`, else
        `ERR_REFERENCE_DESIGN_NOT_PUBLISHED` (HTTP 422), and the part's
        `lifecycle_status` to be `ACTIVE` or `NRND`, else `ERR_PART_NOT_ORDERABLE`
        (HTTP 422)."

        Design: Corner/validations/design_win_activate_draft_reference_design_rejected
        """
        part = make_part(part_number="OPA2134PA")
        cust = make_customer(name="Audio Co", tier="KEY",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        rd = validate_success(
            api.create_reference_design(
                create_reference_design_payload(
                    title="Headphone driver",
                    featured_part_number=part["part_number"],
                ),
                FIELD,
            ),
            201,
        )
        win = validate_success(
            api.create_design_win(
                create_design_win_payload(rd["id"], cust["id"], part["id"],
                                          start_date=START),
                FIELD,
            ),
            201,
        )
        res = api.activate_design_win(win["id"], FIELD)
        validate_error(res, ApiErrorId.ERR_REFERENCE_DESIGN_NOT_PUBLISHED)
        after = validate_success(api.get_design_win(win["id"], FIELD), 200)
        assert after["status"] == "REGISTERED"

    def test_reference_design_publish_discontinued_part_rejected(self, api):
        """PRD §3.8: "Publishing requires the `featured_part_number` to match an
        existing part whose `lifecycle_status` is `ACTIVE` or `NRND` — a design
        featuring a part in any other lifecycle state is rejected with
        `ERR_PART_NOT_ORDERABLE` (HTTP 422); on success the design moves to
        `PUBLISHED` and `published_at` is stamped from the logical clock."
        PRD §3.8: "The design starts in `DRAFT` with `published_at` null."

        Design: Corner/validations/reference_design_publish_discontinued_part_rejected
        """
        part = make_part(part_number="CD4051BE", process_technology="CMOS_180NM")
        make_eol_notice(part["id"], reason="EOL")
        set_clock("2027-05-29T00:00:00Z")  # sweeps the part to DISCONTINUED
        assert get_part(part["id"])["lifecycle_status"] == "DISCONTINUED"

        rd = validate_success(
            api.create_reference_design(
                create_reference_design_payload(
                    title="Mux front end", featured_part_number="CD4051BE"
                ),
                FIELD,
            ),
            201,
        )
        assert rd["status"] == "DRAFT"
        assert rd["published_at"] is None

        res = api.publish_reference_design(rd["id"], FIELD)
        validate_error(res, ApiErrorId.ERR_PART_NOT_ORDERABLE)

        # The design remains DRAFT: activating a win (on a healthy ACTIVE part, so
        # only the published-design gate can fail) still rejects with
        # ERR_REFERENCE_DESIGN_NOT_PUBLISHED (PRD §3.8 activation rule).
        part_ok = make_part(part_number="CD4066BE", process_technology="CMOS_180NM")
        cust = make_customer(name="Mux Buyer", tier="KEY",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        win = validate_success(
            api.create_design_win(
                create_design_win_payload(rd["id"], cust["id"], part_ok["id"],
                                          start_date=START),
                FIELD,
            ),
            201,
        )
        validate_error(
            api.activate_design_win(win["id"], FIELD),
            ApiErrorId.ERR_REFERENCE_DESIGN_NOT_PUBLISHED,
        )
