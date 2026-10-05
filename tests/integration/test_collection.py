"""bounded real HTTP collection and literal, isolated search."""
import time
import uuid

import httpx


from conftest import seed, cleanup


def test_bounded_collection_sizes_literal_search_and_isolation(users, runtime):
    alice, bob = users
    for count in (0, 1, 25, 1000):
        marker = 'collection-' + uuid.uuid4().hex
        try:
            seed(runtime, marker, count)
            start = time.monotonic()
            response = alice.get('/documents', params={'q': marker, 'page': 1})
            print(f'collection size={count}: {(time.monotonic()-start)*1000:.1f}ms')
            assert response.status_code == 200
            result = response.json()
            assert result['total'] == count
            assert result['page_size'] == 10 and result['page'] == 1
            assert result['total_pages'] == (count + 9) // 10
            assert len(result['documents']) == min(10, count)
            assert [d['id'] for d in result['documents']] == [marker + f'-{i:04d}' for i in reversed(range(max(0, count-10), count))]
            last = alice.get('/documents', params={'q': marker, 'page': 999999, 'page_size': 50}).json()
            assert last['page'] == max(1, (count+49)//50)
            assert len(last['documents']) <= 50
            assert bob.get('/documents', params={'q': marker}).json()['total'] == 0
            if count:
                exact = alice.get('/documents', params={'q': marker.upper()+'-0000'}).json()
                assert exact['total'] == 1
                assert alice.get('/documents', params={'q': marker+' special%_\\'}).json()['total'] == 1
                ready = alice.get('/documents', params={'q': '  '+marker+'  ', 'state': 'ready'}).json()
                assert ready['total'] == (count+2)//3
                assert all(d['state']=='ready' for d in ready['documents'])
                assert bob.get('/documents/'+marker+'-0000').status_code == 404
        finally:
            cleanup(runtime, marker)
    assert set(alice.get('/documents').json()) == {'documents'}
    assert httpx.get('http://127.0.0.1:8000/documents?q=private&page=1').status_code == 401


def test_collection_validation(users):
    alice, _ = users
    for params in ({'page':'0'}, {'page':'1.5'}, {'page':'-1'}, {'page':''},
                   {'page_size':'0'}, {'page_size':'51'}, {'page_size':'x'},
                   {'state':'unknown'}, {'q':'x'*201}):
        result = alice.get('/documents', params=params)
        assert result.status_code == 422, (params, result.text)
        assert result.json()['error']['code'] == 'INVALID_COLLECTION_QUERY'
