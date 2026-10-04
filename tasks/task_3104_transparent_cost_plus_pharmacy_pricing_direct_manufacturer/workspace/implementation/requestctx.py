"""Per-request context: identity headers, JSON body access and pagination."""

from errors import ApiError, fail
from resources import _as_int, parse_pagination


class RequestContext:
    def __init__(self, flask_request, rule):
        self.flask_request = flask_request
        self.rule = rule
        self.method = flask_request.method
        self.role = None
        self.user_id = flask_request.headers.get("X-User-ID")
        self._body = None
        self._body_read = False

    # -- request admission -------------------------------------------------
    def declare_identity(self, allowed_roles):
        from auth import declared_role, require_permission, require_ownership, is_patient_scoped

        self.role = declared_role(self.flask_request.headers.get("X-User-Role"))
        require_permission(self.role, self.method, self.rule, allowed_roles)
        if self.role == "Patient" and is_patient_scoped(self.flask_request.path):
            self.follows_patient_ownership = True
        else:
            self.follows_patient_ownership = False

    def guard_ownership(self, owner_patient_id):
        from auth import require_ownership

        if getattr(self, "follows_patient_ownership", False):
            require_ownership(self.role, self.user_id, owner_patient_id)

    # -- payload -----------------------------------------------------------
    def body(self):
        if not self._body_read:
            self._body_read = True
            payload = self.flask_request.get_json(silent=True)
            if payload is None:
                raw = self.flask_request.get_data(as_text=True)
                payload = {}
                if raw and raw.strip():
                    try:
                        import json

                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            payload = parsed
                    except ValueError:
                        payload = {}
            self._body = payload if isinstance(payload, dict) else {}
        return self._body

    def key(self, name):
        return self.body().get(name)

    def require_key(self, name, error_id="ERR_INVALID_AMOUNT"):
        value = self.key(name)
        if value is None:
            fail(error_id, "The %s field is required." % name)
        return value

    def text(self, name, error_id="ERR_INVALID_AMOUNT"):
        value = self.key(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            fail(error_id, "The %s field is required." % name)
        return str(value).strip()

    def integer(self, name, error_id="ERR_INVALID_AMOUNT"):
        value = self.key(name)
        parsed = _as_int(value)
        if parsed is None:
            fail(error_id, "The %s field must be an integer." % name)
        return parsed

    def boolean(self, name, default=False):
        value = self.key(name)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes")

    # -- query parameters --------------------------------------------------
    def query(self, name):
        return self.flask_request.args.get(name)

    def pagination(self, total):
        return parse_pagination(self.flask_request.args, total)