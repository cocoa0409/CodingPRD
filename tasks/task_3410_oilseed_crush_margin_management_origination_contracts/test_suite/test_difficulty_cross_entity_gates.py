"""Difficulty queue — cross_entity_state_dependency: a transition on one
entity gated by another entity's state — CrushRun scheduling gated by
CrushPlant.status, and origination-contract creation gated by
SustainabilityProgram.status (PRD §3.6 and §3.1/§3.2).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_crush_run,
    assert_origination_contract,
    close_program,
    create_active_program,
    create_cash_contract,
    create_crush_plant,
    create_crush_run,
    create_cash_contract_payload,
    post_crush_quote_set,
    read_contract,
    read_crush_run,
    schedule_crush_run_payload,
    setup_origination_site,
    validate_error,
)

MERCH = TEST_USERS["origination_merchandiser_headers"]
SCHEDULER = TEST_USERS["plant_scheduler_headers"]


class TestRunScheduleRequiresPlantActive:
    """A plant registered directly in MAINTENANCE; quotes 1200/55/17 give the
    run a healthy +204.00 spread — only the plant's state blocks scheduling."""

    def _setup(self):
        plant = create_crush_plant(status="MAINTENANCE")
        post_crush_quote_set("2026-11", bean=1200, oil=55, meal=17,
                             quote_date="2026-09-01T00:00:00Z")
        run = create_crush_run(
            plant["id"], run_date="2026-09-10T00:00:00Z",
            planned_bushels=1000, futures_month="2026-11",
        )
        return plant, run

    def test_schedule_rejected_by_plant_state(self, api):
        """PRD §3.6: "the plant must be `ACTIVE` (`ERR_PLANT_NOT_ACTIVE`)".
        Scheduling a PLANNED run at a MAINTENANCE plant fails 422 with the
        cross-entity error even though the run's own state and margin are
        clean.

        Design: Difficulty/cross_entity_state_dependency/run_schedule_requires_plant_active
        """
        _, run = self._setup()
        resp = api_client.schedule_crush_run(
            run["id"], schedule_crush_run_payload(run["version"]), SCHEDULER
        )
        validate_error(resp, ApiErrorId.ERR_PLANT_NOT_ACTIVE)

    def test_run_unchanged_with_margin_intact(self, api):
        """PRD §3.6: "The run is born `PLANNED` with `realized_margin_cents` null."
        The rejected schedule mutates nothing: the run stays PLANNED with
        planned_margin_cents 1000 x 204.00 = 204000 on record — the gate is
        purely the plant's state.

        Design: Difficulty/cross_entity_state_dependency/run_schedule_requires_plant_active
        """
        _, run = self._setup()
        assert run["planned_margin_cents"] == 204000
        resp = api_client.schedule_crush_run(
            run["id"], schedule_crush_run_payload(run["version"]), SCHEDULER
        )
        validate_error(resp, ApiErrorId.ERR_PLANT_NOT_ACTIVE)
        after = read_crush_run(run["id"])
        assert_crush_run(after)
        assert after["status"] == "PLANNED"
        assert after["planned_margin_cents"] == 204000


class TestContractCreateRequiresProgramActive:
    """An ISCC-class program with a 25-cent premium; closing it flips an
    otherwise identical contract create from 201 to ERR_PROGRAM_CLOSED."""

    def _setup(self):
        site = setup_origination_site()
        program = create_active_program(
            name="Regen Prairies", cert_standard="REGEN",
            premium_cents_per_bushel=25,
        )
        first = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=100, cash_price_cents_per_bushel=1000,
            program_id=program["id"],
        )
        close_program(program["id"])
        return site, program, first

    def test_create_against_closed_program_rejected(self, api):
        """PRD §3.1: "Programs are born `ACTIVE`; a `SustainabilityAuditor` may close one, moving it to `CLOSED` — terminal and version-incrementing — after which any new origination contract naming the program is rejected `ERR_PROGRAM_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/contract_create_requires_program_active
        """
        site, program, _ = self._setup()
        resp = api_client.create_origination_contract(
            create_cash_contract_payload(
                site["farmer"]["id"], site["elevator"]["id"],
                quantity_bushels=100, cash_price_cents_per_bushel=1000,
                program_id=program["id"],
            ),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED)

    def test_existing_contract_keeps_its_enrollment(self, api):
        """PRD §3.2: "When `program_id` is present it must resolve to a program that is still `ACTIVE". The rule bites at creation time only: the
        contract written while the program was ACTIVE survives the close with
        its certified enrollment intact and fulfillment still OPEN.

        Design: Difficulty/cross_entity_state_dependency/contract_create_requires_program_active
        """
        site, program, first = self._setup()
        assert first["program_id"] == program["id"]
        resp = api_client.create_origination_contract(
            create_cash_contract_payload(
                site["farmer"]["id"], site["elevator"]["id"],
                quantity_bushels=100, cash_price_cents_per_bushel=1000,
                program_id=program["id"],
            ),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED)
        surviving = read_contract(first["id"])
        assert_origination_contract(surviving)
        assert surviving["program_id"] == program["id"]
        assert surviving["fulfillment_status"] == "OPEN"
        assert surviving["pricing_status"] == "PRICED"
