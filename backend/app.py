"""Minimal operational API. No business data is exposed in foundation health."""
import json
import logging
import os
import sqlite3
import threading
from contextlib import closing
from contextlib import asynccontextmanager

import boto3
from botocore.config import Config
import strawberry
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from backend.answers import InvoiceAnswer, InvoiceQuestion, resolve_answer
from backend.graphql_http import PrivateSchema, register
from backend.auth import BusinessError, router as auth_router
from backend.documents import recover_processing, router as document_router
from backend.database import initialize

logger = logging.getLogger('uvicorn.error')
# PDF parser diagnostics may include source bytes. API errors expose only stable codes.
logging.getLogger('pypdf').addHandler(logging.NullHandler())
logging.getLogger('pypdf').propagate = False
_initialized = False
_initialization_lock = threading.Lock()


def initialize_business():
    global _initialized
    with _initialization_lock:
        if not _initialized:
            initialize()
            recover_processing()
            _initialized = True


def storage_client():
    # Explicit local endpoint and credentials: never discover cloud credentials/metadata.
    return boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'],
                        aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
                        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
                        region_name='us-east-1',
                        config=Config(connect_timeout=1, read_timeout=2,
                                      retries={'total_max_attempts': 1},
                                      s3={'addressing_style': 'path'}))


def dependency_state():
    dependencies = {}
    for name, probe in [('sqlite', probe_sqlite), ('object_store', probe_storage)]:
        try:
            probe()
            dependencies[name] = 'ready'
        except Exception as error:
            # Do not log exception text: SDK messages can contain endpoints/identifiers.
            logger.warning(json.dumps({'event': 'dependency_unavailable',
                                       'dependency': name, 'error_type': type(error).__name__}))
            dependencies[name] = 'unavailable'
    return {'status': 'ready' if all(s == 'ready' for s in dependencies.values()) else 'unavailable',
            'dependencies': dependencies}


def probe_sqlite():
    initialize_business()
    with closing(sqlite3.connect(os.environ['SQLITE_PATH'], timeout=1)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS foundation_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO foundation_probe VALUES (1, 'ready') ON CONFLICT(id) DO UPDATE SET value='ready'")
        assert db.execute('SELECT value FROM foundation_probe WHERE id=1').fetchone() == ('ready',)


def probe_storage():
    storage_client().head_bucket(Bucket=os.environ.get('S3_BUCKET', 'knowledge-hub'))

@asynccontextmanager
async def lifespan(app):
    try:
        initialize_business()
    except Exception as error:
        # Preserve foundation liveness even if the database is unavailable at boot.
        # Readiness/business traffic retries initialization after it recovers.
        logger.warning(json.dumps({'event': 'initialization_unavailable', 'error_type': type(error).__name__}))
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware('http')
async def private_responses(request, call_next):
    try:
        if request.url.path.startswith(('/auth/', '/documents')):
            initialize_business()
        response = await call_next(request)
    except Exception:
        # Never include untrusted input, database paths, auth codes or SDK details.
        response = JSONResponse({'error': {'code': 'DEPENDENCY_UNAVAILABLE', 'message': 'Dependency unavailable'}}, status_code=503)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.exception_handler(BusinessError)
async def business_error(request, error):
    response = JSONResponse({'error': {'code': error.code, 'message': error.code.replace('_', ' ').capitalize()}}, status_code=error.status)
    if error.status == 401:
        response.delete_cookie('hub_session')
    return response


app.include_router(auth_router)
app.include_router(document_router)

@app.get('/health/live')
def live():
    return {'status': 'alive'}

@app.get('/health/ready')
def ready():
    state = dependency_state()
    return JSONResponse(state, status_code=200 if state['status'] == 'ready' else 503)


@strawberry.type
class Health:
    status: str
    sqlite: str
    object_store: str


@strawberry.type
class Query:
    @strawberry.field
    def invoice_answer(self, info: strawberry.Info, document_id: strawberry.ID, question: InvoiceQuestion) -> InvoiceAnswer:
        return resolve_answer(info.context["request"], str(document_id), question)

    @strawberry.field
    def health(self) -> Health:
        state = dependency_state()
        return Health(status=state['status'], sqlite=state['dependencies']['sqlite'],
                      object_store=state['dependencies']['object_store'])


register(app, PrivateSchema(query=Query))
