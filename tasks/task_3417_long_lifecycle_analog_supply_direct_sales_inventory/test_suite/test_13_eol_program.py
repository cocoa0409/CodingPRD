"""End-of-life program: risk cascade, rescind cycle, and the clock-driven sweep."""
from test_helpers import (
    EOL_LAST_ORDER_DATE,
    EOL_LAST_SHIP_DATE,
    TEST_USERS,
    get_customer,
    get_part,
    make_active_design_win,
    make_customer,
    make_eol_notice,
    make_part,
    set_clock,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]
FIELD = TEST_USERS["field_engineer_headers"]


class TestEolProgram:
    def test_eol_notice_cascades_part_designwin_customer(self, api):
        """PRD §3.7: "Issuing a notice moves the part from `ACTIVE` — or from
        `NRND` — to `EOL_ANNOUNCED`, and the risk cascade fires in the same
        operation: every design win whose `part_id` is this part and whose status is
        `ACTIVE` flips its `at_risk` flag to true, and each affected win's owning
        customer has `at_risk_design_win_count` recomputed as the count of that
        customer's `ACTIVE` wins with `at_risk` true."

        Design: Difficulty/transitive_cascade/eol_notice_cascades_part_designwin_customer
        """
        part = make_part(part_number="OPA333AIDBVR", package_family="SOT23",
                         process_technology="CMOS_180NM")
        cust = make_customer(name="Metering Labs", tier="KEY",
                             channel="DIRECT_ONLINE", credit_limit_cents=10_000_000)
        _, win = make_active_design_win(part, cust, title="Energy meter front end")
        assert win["at_risk"] is False
        assert get_customer(cust["id"])["at_risk_design_win_count"] == 0

        notice = make_eol_notice(part["id"], reason="Die bank exhausted")
        assert notice["status"] == "ANNOUNCED"

        assert get_part(part["id"])["lifecycle_status"] == "EOL_ANNOUNCED"
        win_after = validate_success(api.get_design_win(win["id"], FIELD), 200)
        assert win_after["at_risk"] is True
        assert get_customer(cust["id"])["at_risk_design_win_count"] == 1

        notices, meta = validate_paginated(
            api.list_part_eol_notices(part["id"], PLANNER)
        )
        assert meta["total_count"] == 1
        assert notices[0]["status"] == "ANNOUNCED"

    def test_eol_notice_counts_two_active_wins_for_same_customer(self, api):
        """PRD §3.7: "Issuing a notice moves the part from `ACTIVE` — or from
        `NRND` — to `EOL_ANNOUNCED`, and the risk cascade fires in the same
        operation: every design win whose `part_id` is this part and whose status is
        `ACTIVE` flips its `at_risk` flag to true, and each affected win's owning
        customer has `at_risk_design_win_count` recomputed as the count of that
        customer's `ACTIVE` wins with `at_risk` true."

        Design: Difficulty/transitive_cascade/eol_notice_cascades_part_designwin_customer
        """
        part = make_part(part_number="OPA333X2", package_family="SOT23",
                         process_technology="CMOS_180NM")
        cust = make_customer(name="Two Wins Co", tier="KEY",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        _, win1 = make_active_design_win(part, cust, title="Win one")
        _, win2 = make_active_design_win(part, cust, title="Win two")

        make_eol_notice(part["id"])
        assert validate_success(api.get_design_win(win1["id"], FIELD), 200)["at_risk"] is True
        assert validate_success(api.get_design_win(win2["id"], FIELD), 200)["at_risk"] is True
        assert get_customer(cust["id"])["at_risk_design_win_count"] == 2

    def test_part_lifecycle_eol_rescind_cycle(self, api):
        """PRD §3.7: "Rescinding moves the notice to the terminal `RESCINDED`,
        returns the part from `EOL_ANNOUNCED` to `ACTIVE` — rescission always
        restores `ACTIVE` — flips every `ACTIVE` design win on the part back to
        `at_risk` false, and recomputes the affected customers'
        `at_risk_design_win_count`."

        Design: Difficulty/non_linear_state_machine/part_lifecycle_eol_rescind_cycle
        """
        part = make_part(part_number="REF5025IDR", package_family="SOIC",
                         process_technology="CMOS_180NM")
        cust = make_customer(name="Med Devices", tier="KEY",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        _, win = make_active_design_win(part, cust, title="Patient monitor AFE")
        notice = make_eol_notice(part["id"], reason="Fab closure")
        assert get_part(part["id"])["lifecycle_status"] == "EOL_ANNOUNCED"
        assert validate_success(api.get_design_win(win["id"], FIELD), 200)["at_risk"] is True

        rescinded = validate_success(api.rescind_eol_notice(notice["id"], PLANNER), 200)
        assert rescinded["status"] == "RESCINDED"

        assert get_part(part["id"])["lifecycle_status"] == "ACTIVE"
        assert validate_success(api.get_design_win(win["id"], FIELD), 200)["at_risk"] is False
        assert get_customer(cust["id"])["at_risk_design_win_count"] == 0

    def test_rescind_from_nrnd_restores_active(self, api):
        """PRD §3.7: "Issuing a notice moves the part from `ACTIVE` — or from
        `NRND` — to `EOL_ANNOUNCED`".
        PRD §3.7: "Rescinding moves the notice to the terminal `RESCINDED`, returns
        the part from `EOL_ANNOUNCED` to `ACTIVE` — rescission always restores
        `ACTIVE`".

        Design: Difficulty/non_linear_state_machine/part_lifecycle_eol_rescind_cycle
        """
        part = make_part(part_number="REF5025X2", package_family="SOIC",
                         process_technology="CMOS_180NM")
        nrnd = validate_success(
            api.patch_part(part["id"], {"lifecycle_status": "NRND"}, PLANNER), 200
        )
        assert nrnd["lifecycle_status"] == "NRND"

        notice = make_eol_notice(part["id"])
        assert get_part(part["id"])["lifecycle_status"] == "EOL_ANNOUNCED"

        rescinded = validate_success(api.rescind_eol_notice(notice["id"], PLANNER), 200)
        assert rescinded["status"] == "RESCINDED"
        assert get_part(part["id"])["lifecycle_status"] == "ACTIVE"

    def test_eol_clock_sweep_drives_last_time_buy_and_discontinued(self, api):
        """PRD §2.5: "A part in `EOL_ANNOUNCED` advances to `LAST_TIME_BUY` once the
        clock reaches the `last_order_date` of its `ANNOUNCED` end-of-life notice,
        and from `LAST_TIME_BUY` to `DISCONTINUED` once the clock reaches that
        notice's `last_ship_date`; reaching `DISCONTINUED` also moves the linked
        notice from `ANNOUNCED` to `COMPLETED`."

        Design: Corner/state_machines/eol_clock_sweep_drives_last_time_buy_and_discontinued
        """
        part = make_part(part_number="CD4001BE", process_technology="CMOS_180NM")
        notice = make_eol_notice(part["id"], reason="EOL program")

        set_clock(EOL_LAST_ORDER_DATE)
        assert get_part(part["id"])["lifecycle_status"] == "LAST_TIME_BUY"

        set_clock(EOL_LAST_SHIP_DATE)
        assert get_part(part["id"])["lifecycle_status"] == "DISCONTINUED"

        notices, meta = validate_paginated(
            api.list_part_eol_notices(part["id"], PLANNER)
        )
        assert meta["total_count"] == 1
        assert notices[0]["id"] == notice["id"]
        assert notices[0]["status"] == "COMPLETED"
