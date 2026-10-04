"""Routes: cut-pipe consignment quotes and the cut list."""

from flask import request as flask_request

from common import body_json
from db import db
from response import ok_object
from route_util import gate, paginated
from serializers import square_line as ser_square_line
from serializers import square_request as ser_square_request
from svc_square import (create_square_request, cut_square_request,
                        get_square_request, square_line_matches,
                        square_lines_of)


def register(app):

    @app.post("/square-footage-requests")
    def _square_create():
        user_id, _role = gate("POST", "/square-footage-requests")
        return ok_object(ser_square_request(create_square_request(db, user_id, body_json())), 201)

    @app.get("/square-footage-requests")
    def _square_list():
        gate("GET", "/square-footage-requests")
        account_id = flask_request.args.get("account_id")
        rows = [r for r in db.square_footage_requests.values()
                if not account_id or r.get("account_id") == account_id]
        return paginated(rows, ser_square_request)

    @app.get("/square-footage-requests/<request_id>")
    def _square_get(request_id):
        gate("GET", "/square-footage-requests/<request_id>")
        return ok_object(ser_square_request(get_square_request(db, request_id)))

    @app.get("/square-footage-requests/<request_id>/lines")
    def _square_lines(request_id):
        gate("GET", "/square-footage-requests/<request_id>/lines")
        get_square_request(db, request_id)
        return paginated(square_lines_of(db, request_id), ser_square_line)

    @app.get("/square-footage-lines")
    def _square_lines_all():
        gate("GET", "/square-footage-lines")
        rows = [l for l in db.square_footage_lines.values()
                if square_line_matches(l, flask_request.args)]
        return paginated(rows, ser_square_line)

    @app.post("/square-footage-requests/<request_id>/cut")
    def _square_cut(request_id):
        gate("POST", "/square-footage-requests/<request_id>/cut")
        request = get_square_request(db, request_id)
        return ok_object(ser_square_request(cut_square_request(db, request, body_json())))