"""RBAC and uniqueness validation tests: role exclusivity and duplicate
rejection rules."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_municipality,
    make_boiler,
    make_active_agreement,
    make_delivery,
    make_emissions_permit,
    create_waste_supply_agreement_payload,
    create_outage_window_payload,
    create_diversion_plan_payload,
    create_diversion_leg_payload,
    create_power_purchase_agreement_payload,
    create_landfill_payload,
    create_daily_throughput_report_payload,
    create_emissions_permit_payload,
    set_clock,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
ET = TEST_USERS["energy_trader_headers"]
EO = TEST_USERS["environmental_officer_headers"]
REG = TEST_USERS["regulator_headers"]


class TestPlantOperatorCannotManageContracts:
    def test_agreement_creation_and_plan_approval_denied(self):
        """PRD §2.1: "a `ContractsManager` manages municipalities, host community agreements, waste supply agreements and their amendments, metals recovery contracts and batch settlement, diversion plan approval, and put-or-pay settlement runs."
        PRD §2.1: "A request whose role is recognized but is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/plant_operator_cannot_manage_contracts
        """
        m1 = make_municipality()
        boiler = make_boiler()
        outage = get_success_data(
            api_client.create_outage_window(create_outage_window_payload(boiler_id=boiler["id"]), PO)
        )
        plan = get_success_data(
            api_client.create_diversion_plan(create_diversion_plan_payload(outage_id=outage["id"]), PO)
        )
        get_success_data(
            api_client.create_diversion_leg(plan["id"], create_diversion_leg_payload(planned_tonnes=400), PO)
        )

        resp = api_client.create_waste_supply_agreement(
            create_waste_supply_agreement_payload(municipality_id=m1["id"]), PO
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        resp = api_client.approve_diversion_plan(plan["id"], PO)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestEnergyTraderAndEnvironmentalOfficerSurfacesDisjoint:
    def test_cross_surface_writes_denied_both_ways(self):
        """PRD §2.1: "An `EnergyTrader` manages power purchase agreements and energy delivery billing. An `EnvironmentalOfficer` manages landfills, ash shipments and their tests, emissions permits, and emissions readings."
        PRD §2.1: "A request whose role is recognized but is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/energy_trader_cannot_touch_environmental_surface
        """
        resp = api_client.create_landfill(create_landfill_payload(), ET)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        resp = api_client.create_power_purchase_agreement(
            create_power_purchase_agreement_payload(), EO
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestRegulatorScope:
    def test_regulator_denied_business_writes_but_exclusive_ops_succeed(self):
        """PRD §2.1: "A `Regulator` has read access across the business surface, may suspend emissions permits, and is the only role permitted to drive the logical clock."
        PRD §2.1: "A request whose role is recognized but is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/regulator_read_only_except_permit_suspend_and_clock
        """
        permit = make_emissions_permit()

        resp = api_client.create_municipality(
            {"legal_name": "City of Alder", "population_served": 50000}, REG
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        suspended = get_success_data(api_client.suspend_emissions_permit(permit["id"], REG))
        assert suspended["status"] == "SUSPENDED"

        clock = set_clock("2026-09-05T00:00:00Z")
        assert clock["current_utc"].startswith("2026-09-05")


class TestDuplicateManifestRejected:
    def test_manifest_ref_is_globally_unique(self):
        """PRD §3.3: "The manifest reference is unique across every delivery in the system; a duplicate `manifest_ref` is rejected with `ERR_DUPLICATE_MANIFEST`."

        Design: Corner/validations/duplicate_manifest_rejected
        """
        m1 = make_municipality()
        agreement = make_active_agreement(municipality_id=m1["id"])
        make_delivery(agreement["id"], manifest_ref="MAN-DUP")

        resp = api_client.create_waste_delivery(
            {
                "agreement_id": agreement["id"],
                "manifest_ref": "MAN-DUP",
                "tonnes": 5,
                "heating_value_mj_per_kg": 9,
                "delivered_at": "2026-09-03T08:00:00Z",
            },
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MANIFEST)


class TestDuplicateReportDateRejected:
    def test_second_report_for_same_date_rejected(self):
        """PRD §3.6: "A `PlantOperator` creates one by supplying the `report_date` — a UTC calendar day in year-month-day form, unique across all reports, with duplicates rejected as `ERR_DUPLICATE_REPORT_DATE`"

        Design: Corner/validations/duplicate_report_date_rejected
        """
        make_boiler(max_thermal_capacity_mw=150, max_steam_tph=500)
        get_success_data(
            api_client.create_daily_throughput_report(
                create_daily_throughput_report_payload(report_date="2026-09-11"), PO
            )
        )
        resp = api_client.create_daily_throughput_report(
            create_daily_throughput_report_payload(
                report_date="2026-09-11",
                waste_processed_tonnes=100,
                avg_heating_value_mj_per_kg=5.0,
                operating_hours=10,
            ),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_DATE)


class TestDuplicateActivePermitRejected:
    def test_second_active_permit_for_same_pollutant_rejected_until_suspend(self):
        """PRD §3.10: "At most one permit per pollutant may be `ACTIVE` at a time; registering a second active permit for a pollutant already covered is rejected with `ERR_DUPLICATE_PERMIT`."
        PRD §3.10: "A permit is created `ACTIVE`; a `Regulator` may suspend it, moving it to `SUSPENDED` and incrementing its `version`."

        Design: Corner/validations/duplicate_active_permit_per_pollutant_rejected
        """
        permit = make_emissions_permit(pollutant="NOx")

        resp = api_client.create_emissions_permit(
            create_emissions_permit_payload(pollutant="NOx", hourly_limit=180, daily_limit=140), EO
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERMIT)

        get_success_data(api_client.suspend_emissions_permit(permit["id"], REG))

        replacement = validate_success(
            api_client.create_emissions_permit(
                create_emissions_permit_payload(pollutant="NOx", hourly_limit=180, daily_limit=140), EO
            ),
            expected_status=201,
        )
        assert replacement["status"] == "ACTIVE"


class TestHostAgreementRequiresHostMunicipality:
    def test_host_agreement_against_standard_municipality_rejected(self):
        """PRD §3.1: "The named municipality must actually be flagged `is_host_community`; a host agreement pointing at an ordinary municipality is rejected with `ERR_NOT_HOST_COMMUNITY`."

        Design: Corner/validations/host_agreement_requires_host_municipality
        """
        m1 = make_municipality()
        resp = api_client.create_host_community_agreement(
            {
                "municipality_id": m1["id"],
                "annual_payment_cents": 50000000,
                "payment_due_month": 3,
                "effective_start": "2026-01-01T00:00:00Z",
                "effective_end": "2026-12-31T00:00:00Z",
            },
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_HOST_COMMUNITY)


class TestLegsFrozenAfterPlanApproval:
    def test_approve_requires_a_leg_and_approved_plan_rejects_new_legs(self):
        """PRD §3.5: "Approval is performed by a `ContractsManager` and is permitted only when the plan has at least one leg, i.e. its `planned_diverted_tonnes` is greater than zero; approving an empty plan is rejected with `ERR_NO_DIVERSION_LEGS`."
        PRD §3.5: "Once the plan is approved its leg set is frozen: adding a leg to an approved plan is rejected with `ERR_PLAN_ALREADY_APPROVED`."

        Design: Corner/validations/legs_frozen_after_plan_approval
        """
        boiler = make_boiler()
        outage = get_success_data(
            api_client.create_outage_window(create_outage_window_payload(boiler_id=boiler["id"]), PO)
        )
        plan = get_success_data(
            api_client.create_diversion_plan(create_diversion_plan_payload(outage_id=outage["id"]), PO)
        )

        resp = api_client.approve_diversion_plan(plan["id"], CM)
        validate_error(resp, ApiErrorId.ERR_NO_DIVERSION_LEGS)

        get_success_data(
            api_client.create_diversion_leg(plan["id"], create_diversion_leg_payload(planned_tonnes=400), PO)
        )
        approved = get_success_data(api_client.approve_diversion_plan(plan["id"], CM))
        assert approved["approved"] is True

        resp = api_client.create_diversion_leg(
            plan["id"],
            create_diversion_leg_payload(
                receiving_facility_name="Transfer Station 4", planned_tonnes=100
            ),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_APPROVED)
