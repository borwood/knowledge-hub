"""Small bounded GraphQL HTTP transport; errors never log query/variables."""
import json
from graphql import parse, GraphQLError
from graphql.language import ast
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import strawberry
from backend.auth import BusinessError

class PrivateSchema(strawberry.Schema):
    def process_errors(self, errors, execution_context=None):
        pass  # Errors are returned below as stable codes, never logged with query text.


def reject(code, status=400):
    return JSONResponse({'data': None, 'errors': [{'message': code, 'extensions': {'code': code}}]}, status_code=status)


def bounded(query):
    tree = parse(query, max_tokens=1000)
    count = 0
    def walk(node, depth=0):
        nonlocal count
        if isinstance(node, (ast.FragmentDefinitionNode, ast.FragmentSpreadNode, ast.InlineFragmentNode)):
            raise BusinessError('QUERY_LIMIT_EXCEEDED')
        if isinstance(node, ast.OperationDefinitionNode) and node.operation.value != 'query':
            raise BusinessError('UNSUPPORTED_OPERATION')
        if isinstance(node, ast.FieldNode):
            depth += 1
            count += 1
            if depth > 6 or count > 60: raise BusinessError('QUERY_LIMIT_EXCEEDED')
        for key in node.keys:
            value = getattr(node, key)
            if isinstance(value, ast.Node): walk(value, depth)
            elif isinstance(value, tuple):
                for child in value:
                    if isinstance(child, ast.Node): walk(child, depth)
    walk(tree)
    operations = [n for n in tree.definitions if isinstance(n, ast.OperationDefinitionNode)]
    if len(operations) != 1: raise BusinessError('QUERY_LIMIT_EXCEEDED')
    # One top-level answer/health selection prevents alias batches.
    if len(operations[0].selection_set.selections) != 1: raise BusinessError('QUERY_LIMIT_EXCEEDED')


def register(app, schema):
    @app.api_route('/graphql', methods=['GET', 'POST'])
    async def graphql_http(request: Request):
        try:
            if request.method == 'GET':
                payload = dict(request.query_params)
                if len(str(request.url).encode()) > 16384: return reject('REQUEST_TOO_LARGE', 413)
            else:
                if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                    return reject('UNSUPPORTED_MEDIA_TYPE', 415)
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 16384: return reject('REQUEST_TOO_LARGE', 413)
                    body.extend(chunk)
                payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get('query'), str):
                return reject('INVALID_REQUEST')
            variables = payload.get('variables')
            if request.method == 'GET' and isinstance(variables, str): variables = json.loads(variables)
            if variables is not None and not isinstance(variables, dict): return reject('INVALID_REQUEST')
            bounded(payload['query'])
            result = await run_in_threadpool(schema.execute_sync, payload['query'], variable_values=variables,
                                            context_value={'request': request}, operation_name=payload.get('operationName'))
            if result.errors:
                error = next((e.original_error for e in result.errors if e.original_error and e.path), None)
                if isinstance(error, BusinessError):
                    response = reject(error.code, error.status)
                    if error.status == 401: response.delete_cookie('hub_session')
                    return response
                return reject('DEPENDENCY_UNAVAILABLE', 503) if error else reject('GRAPHQL_VALIDATION_FAILED')
            return JSONResponse({'data': result.data})
        except BusinessError as error:
            return reject(error.code, error.status)
        except (ValueError, GraphQLError, TypeError, RecursionError):
            return reject('GRAPHQL_VALIDATION_FAILED')
