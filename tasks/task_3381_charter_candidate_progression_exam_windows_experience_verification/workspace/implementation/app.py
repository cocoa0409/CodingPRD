"""Charter Candidate Progression API — Flask entry point.

All state is in-memory (see store.py); every process boot starts empty.
Listens on PORT (default 10000), bound to 0.0.0.0, in the foreground.
"""
import os
from flask import Flask
from werkzeug.exceptions import HTTPException
from errors import ApiError
from util import error_response
import routes_a
import routes_b
import routes_c

app = Flask(__name__)
app.register_blueprint(routes_a.bp)
app.register_blueprint(routes_b.bp)
app.register_blueprint(routes_c.bp)


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(Exception)
def _fallback(err):
    if isinstance(err, ApiError):
        return error_response(err)
    if isinstance(err, HTTPException):
        status = err.code or 500
        wrapped = ApiError(
            'ERR_INVALID_REQUEST' if status < 500 else 'ERR_INTERNAL',
            status, err.name)
        return error_response(wrapped)
    return error_response(ApiError('ERR_INTERNAL', 500, str(err)))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
            threaded=True)
