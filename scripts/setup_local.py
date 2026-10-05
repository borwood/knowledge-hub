"""Create local-only credentials once without printing secrets."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    print('.env already exists; preserved existing credentials.')
else:
    with target.open('x', encoding='utf-8', newline='\n') as output:
        output.write(f'AWS_ACCESS_KEY_ID=hub-{secrets.token_hex(8)}\n'
                     f'AWS_SECRET_ACCESS_KEY={secrets.token_hex(24)}\n')
    print('Created ignored .env with local credentials.')

# Extend old foundation installs without replacing S3 keys or existing realm secrets.
existing = {line.split('=', 1)[0] for line in target.read_text().splitlines() if '=' in line}
with target.open('a', encoding='utf-8', newline='\n') as output:
    if not target.read_bytes().endswith(b'\n'):
        output.write('\n')
    for key in ('OIDC_CLIENT_SECRET', 'DEMO_ALICE_PASSWORD', 'DEMO_BOB_PASSWORD'):
        if key not in existing:
            output.write(f'{key}={secrets.token_urlsafe(24)}\n')
print('Local identity credentials configured; read .env locally for demo passwords.')
