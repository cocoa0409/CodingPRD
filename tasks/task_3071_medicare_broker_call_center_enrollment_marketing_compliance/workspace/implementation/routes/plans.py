"""Plans, plan master data and plan comparison (PRD 3.1, 3.4)."""

from decimal import Decimal

import calculations as calc
import comparison
import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError

READ_ROLES = ("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "CarrierIntegration", "Any")


def register(app):
    @app.post("/plans")
    @requires("PlatformAdmin")
    def create_plan():
        payload = middleware.body()
        carrier = middleware.resolve("Carrier", middleware.require_field(payload, "carrier_id"))
        plan_type = middleware.require_field(payload, "plan_type", str)
        if plan_type not in calc.PLAN_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "plan_type must be MA, MAPD, PDP or SNP.")
        star_rating = calc.dec(middleware.require_field(payload, "star_rating"))
        if star_rating < Decimal("1.0") or star_rating > Decimal("5.0"):
            raise ApiError("ERR_INVALID_REQUEST", "star_rating must be between 1.0 and 5.0.")
        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "carrier_id": carrier["id"],
            "plan_id_code": middleware.require_field(payload, "plan_id_code", str),
            "plan_type": plan_type,
            "state_code": middleware.require_field(payload, "state_code", str),
            "county_code": middleware.require_field(payload, "county_code", str),
            "monthly_premium_cents": middleware.as_int(
                middleware.require_field(payload, "monthly_premium_cents"), "monthly_premium_cents"),
            "annual_drug_deductible_cents": middleware.as_int(
                middleware.require_field(payload, "annual_drug_deductible_cents"),
                "annual_drug_deductible_cents"),
            "star_rating": star_rating,
            "formulary_id": middleware.require_field(payload, "formulary_id", str),
            "pharmacy_network_id": middleware.require_field(payload, "pharmacy_network_id", str),
            "provider_directory_id": middleware.require_field(payload, "provider_directory_id", str),
            "enrolled_member_count": 0,
            "status": "ACTIVE",
        }
        db.plans[row["id"]] = row
        return response.ok(serializers.serialize("Plan", row), status=201)

    @app.get("/plans")
    @requires(*READ_ROLES)
    def list_plans():
        rows = list(db.plans.values())
        for arg, field in (("carrier_id", "carrier_id"), ("plan_type", "plan_type"),
                           ("state_code", "state_code"), ("county_code", "county_code"),
                           ("status", "status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Plan", page), limit, offset, total)

    @app.get("/plans/<plan_id>")
    @requires(*READ_ROLES)
    def get_plan(plan_id):
        plan = middleware.resolve("Plan", plan_id)
        # enrolled_member_count is a derived count of standing state, recomputed
        # on every read so it can never drift from the enrollment rows beneath it.
        core.recompute_plan_enrolled_count(plan)
        return response.ok(serializers.serialize("Plan", plan))

    @app.post("/plans/<plan_id>/formulary-drugs")
    @requires("PlatformAdmin")
    def add_formulary_drug(plan_id):
        plan = middleware.resolve("Plan", plan_id)
        payload = middleware.body()
        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "plan_id": plan["id"],
            "drug_name": middleware.require_field(payload, "drug_name", str),
            "rxcui": middleware.require_field(payload, "rxcui", str),
            "tier": middleware.as_int(middleware.require_field(payload, "tier"), "tier"),
            "monthly_copay_cents": middleware.as_int(
                middleware.require_field(payload, "monthly_copay_cents"), "monthly_copay_cents"),
            "prior_authorization_required": middleware.as_bool(
                middleware.require_field(payload, "prior_authorization_required"),
                "prior_authorization_required"),
            "covered": middleware.optional(payload, "covered", True),
            "quantity_limit_days": middleware.as_int(
                middleware.optional(payload, "quantity_limit_days", 30), "quantity_limit_days"),
        }
        db.formulary_drugs[row["id"]] = row
        return response.ok(serializers.serialize("FormularyDrug", row), status=201)

    @app.get("/plans/<plan_id>/formulary-drugs")
    @requires("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "Any")
    def list_formulary_drugs(plan_id):
        plan = middleware.resolve("Plan", plan_id)
        rows = [row for row in db.formulary_drugs.values() if row["plan_id"] == plan["id"]]
        rxcui = middleware.text_arg("rxcui")
        if rxcui is not None:
            rows = [row for row in rows if row["rxcui"] == rxcui]
        tier = middleware.text_arg("tier")
        if tier is not None:
            rows = [row for row in rows if str(row["tier"]) == tier]
        covered = middleware.bool_arg("covered")
        if covered is not None:
            rows = [row for row in rows if bool(row["covered"]) == covered]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("FormularyDrug", page), limit, offset, total)

    @app.post("/plans/<plan_id>/pharmacy-network-entries")
    @requires("PlatformAdmin")
    def add_pharmacy_entry(plan_id):
        plan = middleware.resolve("Plan", plan_id)
        payload = middleware.body()
        network_tier = middleware.require_field(payload, "network_tier", str)
        if network_tier not in ("PREFERRED", "STANDARD", "OUT_OF_NETWORK"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "network_tier must be PREFERRED, STANDARD or OUT_OF_NETWORK.")
        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "plan_id": plan["id"],
            "pharmacy_npi": middleware.require_field(payload, "pharmacy_npi", str),
            "pharmacy_name": middleware.require_field(payload, "pharmacy_name", str),
            "network_tier": network_tier,
            "cost_share_multiplier_pct": calc.dec(
                middleware.require_field(payload, "cost_share_multiplier_pct")),
        }
        db.pharmacy_entries[row["id"]] = row
        return response.ok(serializers.serialize("PharmacyNetworkEntry", row), status=201)

    @app.get("/plans/<plan_id>/pharmacy-network-entries")
    @requires("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "Any")
    def list_pharmacy_entries(plan_id):
        plan = middleware.resolve("Plan", plan_id)
        rows = [row for row in db.pharmacy_entries.values() if row["plan_id"] == plan["id"]]
        network_tier = middleware.text_arg("network_tier")
        if network_tier is not None:
            rows = [row for row in rows if row["network_tier"] == network_tier]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("PharmacyNetworkEntry", page), limit, offset, total)

    @app.post("/plans/<plan_id>/provider-directory-entries")
    @requires("PlatformAdmin")
    def add_provider_entry(plan_id):
        plan = middleware.resolve("Plan", plan_id)
        payload = middleware.body()
        network_status = middleware.require_field(payload, "network_status", str)
        if network_status not in ("IN_NETWORK", "OUT_OF_NETWORK"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "network_status must be IN_NETWORK or OUT_OF_NETWORK.")
        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "plan_id": plan["id"],
            "provider_npi": middleware.require_field(payload, "provider_npi", str),
            "provider_name": middleware.require_field(payload, "provider_name", str),
            "specialty": middleware.require_field(payload, "specialty", str),
            "network_status": network_status,
            "accepting_new_patients": middleware.as_bool(
                middleware.require_field(payload, "accepting_new_patients"), "accepting_new_patients"),
            "last_attested_on": middleware.as_instant(
                middleware.require_field(payload, "last_attested_on"), "last_attested_on"),
        }
        db.provider_entries[row["id"]] = row
        return response.ok(serializers.serialize("ProviderDirectoryEntry", row), status=201)

    @app.get("/plans/<plan_id>/provider-directory-entries")
    @requires("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "Any")
    def list_provider_entries(plan_id):
        plan = middleware.resolve("Plan", plan_id)
        rows = [row for row in db.provider_entries.values() if row["plan_id"] == plan["id"]]
        network_status = middleware.text_arg("network_status")
        if network_status is not None:
            rows = [row for row in rows if row["network_status"] == network_status]
        accepting = middleware.bool_arg("accepting_new_patients")
        if accepting is not None:
            rows = [row for row in rows if bool(row["accepting_new_patients"]) == accepting]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("ProviderDirectoryEntry", page), limit, offset, total)

    @app.get("/plans/<plan_id>/enrollments")
    @requires("PlatformAdmin", "ComplianceOfficer", "CarrierIntegration", "Any")
    def list_plan_enrollments(plan_id):
        plan = middleware.resolve("Plan", plan_id)
        rows = [row for row in db.enrollments.values() if row["plan_id"] == plan["id"]]
        for arg, field in (("submission_status", "submission_status"),
                           ("disenrollment_status", "disenrollment_status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Enrollment", page), limit, offset, total)

    # -- Plan comparison -----------------------------------------------------
    @app.post("/plan-comparisons")
    @requires("LicensedAgent")
    def plan_comparison():
        payload = middleware.body()
        member = middleware.resolve("Member", middleware.require_field(payload, "member_id"))
        agent = middleware.resolve("Agent", middleware.require_field(payload, "agent_id"))
        scope = middleware.resolve("ScopeOfAppointment",
                                   middleware.require_field(payload, "scope_of_appointment_id"))
        middleware.owner_check("LicensedAgent", middleware.current_user_id(), agent["id"])

        plans = comparison.candidate_plans(member)
        plan_types = sorted({plan["plan_type"] for plan in plans})
        core.require_scope_usable(scope, agent["id"])
        for plan_type in plan_types:
            if plan_type not in scope["plan_types_authorized"]:
                raise ApiError("ERR_PLAN_TYPE_NOT_AUTHORIZED",
                               "A candidate plan type is not authorized by the scope.")

        if agent["agency_id"] != member["agency_id"]:
            raise ApiError("ERR_MEMBER_NOT_IN_AGENCY",
                           "The member does not belong to the agent's agency.")
        if not plans:
            raise ApiError("ERR_PLAN_NOT_IN_SERVICE_AREA",
                           "No ACTIVE plan exists in the member's service area.")

        for plan in plans:
            try:
                core.require_staffing_authority(agent, plan)
            except ApiError:
                raise

        ranked = comparison.ranked_plans(member)
        top = ranked[0] if ranked else None
        return response.ok({
            "member_id": member["id"],
            "scope_of_appointment_id": scope["id"],
            "candidate_plan_count": len(ranked),
            "recommended_plan_id": top["plan_id"] if top else None,
            "recommended_plan_id_code": top["plan_id_code"] if top else None,
            "recommended_composite_score": top["composite_score"] if top else None,
            "ranked_plans": ranked,
        }, status=201)