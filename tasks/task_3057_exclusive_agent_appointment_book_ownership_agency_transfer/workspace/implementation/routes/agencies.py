"""Agency endpoints, including the nested marketing-campaign collection."""

from flask import request

import db
import middleware
import serializers
from response import array_response, object_response
from routes import _common as c
from services import agencies, agents, campaigns, policies


READ_ROLES = ("AppointingExecutive", "FieldManager", "AgencyPrincipal")
CREATE_ROLES = ("AppointingExecutive",)
GOVERN_ROLES = ("AppointingExecutive",)


def register(app):

    @app.route("/agency-network/agencies", methods=["POST"])
    def create_agency():
        middleware.authorize(request, CREATE_ROLES)
        record = agencies.create(c.body())
        return object_response(serializers.view_agency(record), 201)

    @app.route("/agency-network/agencies", methods=["GET"])
    def list_agencies():
        # The agency roll itself is not an "agency-scoped resource"; Principal
        # ownership is enforced on the resources that carry an agency FK.
        middleware.authorize(request, READ_ROLES)
        return c.paged(request, agencies.list_agencies(request), serializers.view_agency)

    @app.route("/agency-network/agencies/<agency_id>", methods=["GET"])
    def read_agency(agency_id):
        middleware.authorize(request, READ_ROLES)
        return object_response(serializers.view_agency(c.agency_or_404(agency_id)))

    @app.route("/agency-network/agencies/<agency_id>/activate", methods=["POST"])
    def activate_agency(agency_id):
        middleware.authorize(request, GOVERN_ROLES)
        agency = c.agency_or_404(agency_id)
        payload = c.body()
        record = agencies.activate(agency, payload.get("expected_agency_version"))
        return object_response(serializers.view_agency(record), 200)

    @app.route("/agency-network/agencies/<agency_id>/terminate", methods=["POST"])
    def terminate_agency(agency_id):
        middleware.authorize(request, GOVERN_ROLES)
        agency = c.agency_or_404(agency_id)
        record = agencies.terminate(agency)
        return object_response(serializers.view_agency(record), 200)

    @app.route("/agency-network/agencies/<agency_id>/run_ops", methods=["POST"])
    def run_ops(agency_id):
        middleware.authorize(request, ("PlatformAdmin", "AppointingExecutive"))
        agency = c.agency_or_404(agency_id)
        record = agencies.run_ops(agency)
        return object_response(serializers.view_agency(record), 200)

    @app.route("/agency-network/agencies/<agency_id>/performance", methods=["GET"])
    def agency_performance(agency_id):
        middleware.authorize(request, READ_ROLES)
        agency = c.agency_or_404(agency_id)
        return object_response(agencies.performance(agency), 200)

    # --- marketing campaigns ------------------------------------------------

    @app.route("/agency-network/agencies/<agency_id>/marketing-campaigns", methods=["POST"])
    def create_campaign(agency_id):
        role, uid = middleware.authorize(request, ("AgencyPrincipal",))
        c.principal_owns(role, uid, agency_id)
        agency = c.agency_or_404(agency_id)
        record = campaigns.create(agency, c.body())
        return object_response(serializers.view_campaign(record), 201)

    @app.route("/agency-network/agencies/<agency_id>/marketing-campaigns", methods=["GET"])
    def list_campaigns(agency_id):
        role, uid = middleware.authorize(
            request, ("AgencyPrincipal", "FieldManager", "AppointingExecutive"))
        c.principal_owns(role, uid, agency_id)
        agency = c.agency_or_404(agency_id)
        rows = campaigns.list_campaigns(agency, request)
        return c.paged(request, rows, serializers.view_campaign)

    @app.route("/agency-network/agencies/<agency_id>/marketing-campaigns/<campaign_id>",
               methods=["GET"])
    def read_campaign(agency_id, campaign_id):
        role, uid = middleware.authorize(
            request, ("AgencyPrincipal", "FieldManager", "AppointingExecutive"))
        c.principal_owns(role, uid, agency_id)
        agency = c.agency_or_404(agency_id)
        campaign = c.campaign_or_404(agency, campaign_id)
        return object_response(serializers.view_campaign(campaign), 200)

    @app.route("/agency-network/agencies/<agency_id>/marketing-campaigns/<campaign_id>",
               methods=["PUT"])
    def update_campaign(agency_id, campaign_id):
        role, uid = middleware.authorize(request, ("AgencyPrincipal",))
        c.principal_owns(role, uid, agency_id)
        agency = c.agency_or_404(agency_id)
        campaign = c.campaign_or_404(agency, campaign_id)
        record = campaigns.update(agency, campaign, c.body())
        return object_response(serializers.view_campaign(record), 200)

    @app.route(
        "/agency-network/agencies/<agency_id>/marketing-campaigns/<campaign_id>/participate",
        methods=["POST"])
    def participate_campaign(agency_id, campaign_id):
        role, uid = middleware.authorize(request, ("AgencyPrincipal",))
        c.principal_owns(role, uid, agency_id)
        agency = c.agency_or_404(agency_id)
        campaign = c.campaign_or_404(agency, campaign_id)
        payload = c.body()
        record = campaigns.participate(
            agency, campaign, payload.get("expected_agency_version"))
        return object_response(serializers.view_campaign(record), 200)

    @app.route("/agency-network/agencies/<agency_id>/marketing-campaigns/<campaign_id>",
               methods=["DELETE"])
    def cancel_campaign(agency_id, campaign_id):
        role, uid = middleware.authorize(request, ("AgencyPrincipal",))
        c.principal_owns(role, uid, agency_id)
        agency = c.agency_or_404(agency_id)
        campaign = c.campaign_or_404(agency, campaign_id)
        campaigns.cancel(agency, campaign)
        return object_response({}, 204)

    # --- nested reverse lookups --------------------------------------------

    @app.route("/agency-network/agencies/<agency_id>/policies", methods=["GET"])
    def agency_policies(agency_id):
        role, uid = middleware.authorize(
            request, ("AppointingExecutive", "FieldManager", "AgencyPrincipal",
                      "ClaimsAdjuster"))
        c.principal_owns(role, uid, agency_id)
        agency = c.agency_or_404(agency_id)
        rows = policies.policies_for_agency(agency, request)
        return c.paged(request, rows, serializers.view_policy)

    @app.route("/agency-network/agencies/<agency_id>/agents", methods=["GET"])
    def agency_agents(agency_id):
        role, uid = middleware.authorize(request, READ_ROLES)
        c.principal_owns(role, uid, agency_id)
        agency = c.agency_or_404(agency_id)
        rows = [a for a in middleware.filter_by(
            list(db.agent_rows().values()),
            {"status": request.args.get("status")}) if a.get("agency_id") == agency["id"]]
        rows.sort(key=lambda a: a["created_at"])
        return c.paged(request, rows, serializers.view_agent)