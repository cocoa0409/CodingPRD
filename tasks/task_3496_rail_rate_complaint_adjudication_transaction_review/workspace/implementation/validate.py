"""Request-shape validation (priority 1, body). All failures are
ERR_INVALID_REQUEST (400)."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import api_err


def invalid(message):
    return api_err('ERR_INVALID_REQUEST', message)


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise invalid('Request body must be a JSON object')
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == '':
        raise invalid('Field {!r} is required and must be a non-empty string'.format(field))
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if not _is_int(v):
        raise invalid('Field {!r} is required and must be an integer'.format(field))
    if minimum is not None and v < minimum:
        raise invalid('Field {!r} must be at least {}'.format(field, minimum))
    if maximum is not None and v > maximum:
        raise invalid('Field {!r} must be at most {}'.format(field, maximum))
    return v


def opt_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return None
    return req_int(data, field, minimum, maximum)


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise invalid('Field {!r} is required and must be a boolean'.format(field))
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if v not in values:
        raise invalid('Field {!r} must be one of {}'.format(field, sorted(values)))
    return v


def req_str_list(data, field):
    v = data.get(field)
    if not isinstance(v, list) or any(not isinstance(item, str) for item in v):
        raise invalid('Field {!r} is required and must be an array of strings'.format(field))
    return v


def parse_tons(value, field='tons'):
    """A shipment tonnage: a JSON number >= 0 with up to 3 decimal places."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid('Field {!r} must be a number'.format(field))
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise invalid('Field {!r} must be a number'.format(field))
    if dec < 0:
        raise invalid('Field {!r} must be at least 0'.format(field))
    if -dec.as_tuple().exponent > 3:
        raise invalid('Field {!r} may carry at most 3 decimal places'.format(field))
    return dec
