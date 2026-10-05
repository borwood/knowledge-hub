"""Typed answers from document-scoped relational evidence; no fixture fallback."""
import json
import math
from enum import Enum
import strawberry
from backend.auth import BusinessError, authenticate, unsafe
from backend.database import database
from backend.documents import owned

@strawberry.enum
class InvoiceQuestion(Enum):
    INVOICE_TOTAL = 'INVOICE_TOTAL'
    INVOICE_VENDOR = 'INVOICE_VENDOR'

@strawberry.type
class BoundingBox:
    left: float
    top: float
    width: float
    height: float

@strawberry.type
class Evidence:
    field_id: strawberry.ID
    entity_id: strawberry.ID
    relationship_id: strawberry.ID | None
    field_name: str
    value: str
    document_sha256: str
    page: int
    block_id: str
    bounding_box: BoundingBox
    method: str
    confidence: float
    confidence_kind: str

@strawberry.type
class InvoiceAnswer:
    document_id: strawberry.ID
    question: InvoiceQuestion
    text: str
    source_kind: str
    evidence: list[Evidence]


def missing():
    raise BusinessError('MISSING_EVIDENCE', 422)


def resolve_answer(request, document_id, question):
    from backend.app import initialize_business
    initialize_business()
    session = authenticate(request)
    if request.method != 'POST':
        raise BusinessError('POST_REQUIRED', 405)
    unsafe(request, session)
    with database() as db:
        document = owned(db, document_id, session['owner_id'])
        if document['state'] != 'ready':
            raise BusinessError('DOCUMENT_NOT_READY', 409)
        def entity(kind):
            rows = db.execute('SELECT id FROM entities WHERE document_id=? AND kind=?', (document_id, kind)).fetchall()
            if len(rows) != 1: missing()
            return rows[0]['id']
        invoice = entity('invoice')
        relation = None
        if question == InvoiceQuestion.INVOICE_VENDOR:
            target = entity('vendor')
            rows = db.execute('SELECT id FROM relationships WHERE document_id=? AND kind=? AND source_id=? AND target_id=?',
                              (document_id, 'invoice-issued-by-vendor', invoice, target)).fetchall()
            if len(rows) != 1: missing()
            relation = rows[0]['id']
            requested = [(target, 'name', 'vendor')]
        else:
            requested = [(invoice, 'total', 'total'), (invoice, 'currency', 'currency')]
        extraction = db.execute('SELECT raw FROM extractions WHERE document_id=?', (document_id,)).fetchone()
        try:
            raw = json.loads(extraction['raw'])
            blocks = {b['Id']: b for b in raw['Blocks']}
            assert len(blocks) == len(raw['Blocks'])
            assert raw['document_sha256'] == document['sha256'] and raw['source_kind'] == 'synthetic'
        except (TypeError, ValueError, KeyError, AssertionError): missing()
        evidence = []
        for entity_id, attribute, name in requested:
            row = db.execute('''SELECT f.* FROM entity_evidence e JOIN fields f
              ON f.id=e.field_id AND f.document_id=e.document_id
              WHERE e.document_id=? AND e.entity_id=? AND e.attribute=? AND f.name=?''',
              (document_id, entity_id, attribute, name)).fetchone()
            if row is None: missing()
            if relation and not db.execute('SELECT 1 FROM relationship_evidence WHERE document_id=? AND relationship_id=? AND field_id=?',
                                           (document_id, relation, row['id'])).fetchone(): missing()
            try:
                field = json.loads(row['payload'])
                box = field['evidence']['bounding_box']
                coords = [box[k] for k in ('Left', 'Top', 'Width', 'Height')]
                assert all(type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1 for v in coords)
                assert coords[2] > 0 and coords[3] > 0 and coords[0]+coords[2] <= 1 and coords[1]+coords[3] <= 1
                assert field['name'] == name and field['document_sha256'] == document['sha256']
                assert isinstance(field['value'], str) and field['value']
                assert type(field['page']) is int and 1 <= field['page'] <= 10
                assert isinstance(field['evidence']['block_id'], str) and field['evidence']['block_id']
                block = blocks[field['evidence']['block_id']]
                assert block['Page'] == field['page'] and block['Geometry']['BoundingBox'] == box
                assert field['page'] <= raw['DocumentMetadata']['Pages']
                assert block['Text'] == name.capitalize() + ': ' + field['value']
                assert field['method'] == raw['method'] and field['confidence_kind'] == raw['confidence_kind']
                assert math.isclose(block['Confidence'] / 100, field['confidence'], abs_tol=1e-12)
                assert field['method'] == 'synthetic_fixture_v1' and field['confidence_kind'] == 'invented_not_calibrated'
                assert type(field['confidence']) in (float, int) and 0 <= field['confidence'] <= 1
                evidence.append(Evidence(field_id=row['id'], entity_id=entity_id, relationship_id=relation,
                    field_name=name, value=field['value'], document_sha256=field['document_sha256'], page=field['page'],
                    block_id=field['evidence']['block_id'], bounding_box=BoundingBox(left=coords[0], top=coords[1], width=coords[2], height=coords[3]),
                    method=field['method'], confidence=field['confidence'], confidence_kind=field['confidence_kind']))
            except (ValueError, TypeError, KeyError, AssertionError): missing()
        text = evidence[0].value if relation else evidence[1].value + ' ' + evidence[0].value
        return InvoiceAnswer(document_id=document_id, question=question, text=text, source_kind='synthetic', evidence=evidence)
