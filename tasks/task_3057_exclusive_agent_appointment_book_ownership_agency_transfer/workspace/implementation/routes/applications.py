"""Appointment-application endpoints."""

from flask import request

import middleware
import serializers
from response import object_response
from routes import _common as c
from services import applications, agents


def register(app):

    @app.route("/agency-network/appointment-applications", methods=["POST"])
    def submit_application():
        middleware.authorize(request, ("FieldManager",))
        record = applications.submit(c.body())
        return object_response(serializers.view_application(record), 201)

    @app.route("/agency-network/appointment-applications", methods=["GET"])
    def list_applications():
        middleware.authorize(request, ("FieldManager", "AppointingExecutive"))
        return c.paged(request, applications.list_applications(request),
                       serializers.view_application)

    @app.route("/agency-network/appointment-applications/<application_id>", methods=["GET"])
    def read_application(application_id):
        middleware.authorize(request, ("FieldManager", "AppointingExecutive"))
        record = c.application_or_404(application_id)
        return object_response(serializers.view_application(record), 200)

    @app.route("/agency-network/appointment-applications/<application_id>/assess",
               methods=["POST"])
    def assess_application(application_id):
        middleware.authorize(request, ("FieldManager",))
        record = c.application_or_404(application_id)
        applications.assess(record)
        return object_response(serializers.view_application(record), 200)

    @app.route("/agency-network/appointment-applications/<application_id>/approve",
               methods=["POST"])
    def approve_application(application_id):
        middleware.authorize(request, ("AppointingExecutive",))
        record = c.application_or_404(application_id)
        applications.approve(record)
        return object_response(serializers.view_application(record), 200)

    @app.route("/agency-network/appointment-applications/<application_id>/reject",
               methods=["POST"])
    def reject_application(application_id):
        middleware.authorize(request, ("AppointingExecutive",))
        record = c.application_or_404(application_id)
        applications.reject(record, c.body())
        return object_response(serializers.view_application(record), 200)

    @app.route("/agency-network/appointment-applications/<application_id>/appoint",
               methods=["POST"])
    def appoint_application(application_id):
        middleware.authorize(request, ("FieldManager",))
        record = c.application_or_404(application_id)
        agent = applications.appoint(record)
        return object_response(serializers.view_agent(agent), 201)