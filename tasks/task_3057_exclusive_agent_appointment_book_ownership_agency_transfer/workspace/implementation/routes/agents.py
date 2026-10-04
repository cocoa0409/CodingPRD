"""Agent, license, book-transfer and policy-reassignment endpoints."""

from flask import request

import middleware
import serializers
from response import object_response
from routes import _common as c
from services import agents, transfers


READ_ROLES = ("FieldManager", "AppointingExecutive", "AgencyPrincipal")


def register(app):

    @app.route("/agency-network/agents", methods=["GET"])
    def list_agents():
        role, uid = middleware.authorize(request, READ_ROLES)
        return c.paged(request, agents.list_agents(request, role, uid),
                       serializers.view_agent)

    @app.route("/agency-network/agents/<agent_id>", methods=["GET"])
    def read_agent(agent_id):
        role, uid = middleware.authorize(request, READ_ROLES)
        agent = c.agent_or_404(agent_id)
        c.principal_owns(role, uid, agent.get("agency_id"))
        return object_response(serializers.view_agent(agent))

    @app.route("/agency-network/agents/<agent_id>/read-license", methods=["POST"])
    def read_license(agent_id):
        middleware.authorize(request, ("FieldManager", "PlatformAdmin"))
        agent = c.agent_or_404(agent_id)
        agents.read_license(agent, c.body())
        return object_response(serializers.view_agent(agent), 200)

    @app.route("/agency-network/agents/<agent_id>/transition-book", methods=["POST"])
    def transition_book(agent_id):
        middleware.authorize(request, ("FieldManager",))
        agent = c.agent_or_404(agent_id)
        payload = c.body()
        target = c.agency_or_404(payload.get("agency_id"))
        record = agents.transition_book(agent, target, payload.get("expected_agent_version"))
        return object_response(serializers.view_agent(record), 200)

    @app.route("/agency-network/agents/<agent_id>/cessation", methods=["POST"])
    def cessation(agent_id):
        role, uid = middleware.authorize(request, ("AgencyPrincipal",))
        agent = c.agent_or_404(agent_id)
        c.principal_owns(role, uid, agent.get("agency_id"))
        record = agents.cessation(agent, c.body())
        return object_response(serializers.view_agent(record), 200)

    @app.route("/agency-network/agents/<agent_id>/policies/<policy_id>/cessation",
               methods=["POST"])
    def policy_cessation(agent_id, policy_id):
        middleware.authorize(request, ("FieldManager",))
        agent = c.agent_or_404(agent_id)
        policy = c.policy_or_404(policy_id)
        payload = c.body()
        record = agents.reassign_policy(agent, policy, payload.get("successor_agent_id"))
        return object_response(serializers.view_policy(record), 200)

    @app.route("/agency-network/agents/<agent_id>/complete-reassignment", methods=["POST"])
    def complete_reassignment(agent_id):
        middleware.authorize(request, ("FieldManager",))
        agent = c.agent_or_404(agent_id)
        record = agents.complete_reassignment(agent)
        return object_response(serializers.view_agent(record), 200)

    @app.route("/agency-network/agents/<agent_id>/staff", methods=["GET"])
    def agent_staff(agent_id):
        role, uid = middleware.authorize(request, READ_ROLES)
        agent = c.agent_or_404(agent_id)
        c.principal_owns(role, uid, agent.get("agency_id"))
        rows = agents.staff_for_agent(agent, request)
        return c.paged(request, rows, serializers.view_staff)

    @app.route("/agency-network/agents/<agent_id>/book-transfer", methods=["POST"])
    def post_book_transfer(agent_id):
        role, uid = middleware.authorize(request, ("AgencyPrincipal", "FieldManager"))
        agent = c.agent_or_404(agent_id)
        c.principal_owns(role, uid, agent.get("agency_id"))
        record = transfers.post(agent, c.body())
        return object_response(serializers.view_transfer(record), 200)

    @app.route("/agency-network/agents/<agent_id>/book-transfers", methods=["GET"])
    def list_agent_book_transfers(agent_id):
        role, uid = middleware.authorize(
            request, ("AgencyPrincipal", "FieldManager", "PlatformAdmin"))
        agent = c.agent_or_404(agent_id)
        c.principal_owns(role, uid, agent.get("agency_id"))
        rows = transfers.transfers_for_agent(agent, request)
        return c.paged(request, rows, serializers.view_transfer)