"""Actual public demo assets and narrowly scoped runtime credential delivery."""
import hashlib
from pathlib import Path
import httpx
from conftest import demo_password

ROOT=Path(__file__).resolve().parents[2]


def test_public_sample_matches_canonical_fixture(runtime):
    canonical=(ROOT/'fixtures/invoice/invoice.pdf').read_bytes()
    public=(ROOT/'frontend/public/demo-invoice.pdf').read_bytes()
    served=httpx.get('http://127.0.0.1:3000/demo-invoice.pdf')
    assert served.status_code==200
    assert hashlib.sha256(canonical).digest()==hashlib.sha256(public).digest()==hashlib.sha256(served.content).digest()


def test_runtime_credentials_are_only_advertised_demo_accounts(runtime):
    response=httpx.get('http://127.0.0.1:3000/api/demo-credentials')
    assert response.status_code==200
    assert response.headers['cache-control']=='no-store'
    data=response.json()
    assert set(data)=={'accounts'}
    assert len(data['accounts'])==2
    for account,username in zip(data['accounts'],('alice','bob')):
        assert set(account)=={'username','password'}
        matches=account['username']==username and account['password']==demo_password(username)
        assert matches, 'Advertised account must match runtime local configuration'
    runtime('exec','-T','web','node','-e',r'''
const fs=require('node:fs'),path=require('node:path');
const credentials=[process.env.DEMO_ALICE_PASSWORD,process.env.DEMO_BOB_PASSWORD].filter(Boolean);
function inspect(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){const file=path.join(dir,entry.name);if(entry.isDirectory())inspect(file);else {const bytes=fs.readFileSync(file);if(credentials.some(value=>bytes.includes(Buffer.from(value))))throw Error('Demo credentials found in browser assets');}}}
inspect('.next/static');console.log('No runtime demo credentials embedded in browser assets');
''')


def test_missing_credential_configuration_is_unavailable_and_not_cached(runtime):
    # Isolated production web container: override only the two intended credentials.
    # Existing services, identity accounts and volumes remain untouched.
    runtime('run','--rm','--no-deps','-e','DEMO_ALICE_PASSWORD=','-e','DEMO_BOB_PASSWORD=',
        'web','node','-e',r'''
const {spawn}=require('node:child_process');
const server=spawn(process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3010'],{stdio:'ignore'});
(async()=>{try {
 let response;
 for(let i=0;i<100;i++){try{response=await fetch('http://127.0.0.1:3010/api/demo-credentials');break;}catch{await new Promise(r=>setTimeout(r,100));}}
 if(!response||response.status!==503||response.headers.get('cache-control')!=='no-store')throw Error('Missing configuration response contract');
 const body=await response.json();
 if(Object.keys(body).join()!=='error'||!body.error.includes('unavailable'))throw Error('Unexpected missing configuration payload');
 console.log('Missing demo configuration is unavailable, no-store, and contains no credentials');
}catch(e){console.error(e.message);process.exitCode=1;}finally{server.kill();}})();
''')
