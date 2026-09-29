"""Record -> JSON. Field names are exactly the names the records carry."""

from decimal import Decimal


def _value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    return value


def dump(record):
    return {key: _value(value) for key, value in record.items() if not key.startswith("_")}
