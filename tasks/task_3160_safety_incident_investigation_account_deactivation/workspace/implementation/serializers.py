"""Entity serialisation.

Every field the entity tables declare is rendered under its declared name; the
only keys withheld are the implementation's private bookkeeping keys, which are
prefixed with an underscore and are not part of any declared contract.
"""

from db import iso

_HIDDEN_PREFIX = "_"


def _public(resource):
    out = {}
    for key, value in resource.items():
        if key.startswith(_HIDDEN_PREFIX):
            continue
        out[key] = _render(value)
    return out


def _render(value):
    if hasattr(value, "strftime"):
        return iso(value)
    return value


def render_value(value):
    """Render a bare value (used by the ad-hoc projection payloads)."""
    return _render(value)


def render_mapping(payload):
    """Render every datetime in a projection payload as an ISO 8601 instant."""
    return {key: _render(value) for key, value in payload.items()}


def account(resource):
    return _public(resource)


def cluster(resource):
    return _public(resource)


def link(resource):
    return _public(resource)


def trip(resource):
    return _public(resource)


def incident(resource):
    return _public(resource)


def evidence(resource):
    return _public(resource)


def enforcement_action(resource):
    return _public(resource)


def regulator_report(resource):
    return _public(resource)


def background_check(resource):
    return _public(resource)


def policy(resource):
    return _public(resource)


def many(fn, resources):
    return [fn(r) for r in resources]