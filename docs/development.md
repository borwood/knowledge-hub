# Development and testing

Use Python 3.13, Node.js 22 LTS (the container pins 22.22.2), Docker with Compose v2 and Playwright Chromium. Run commands from the repository root.

```text
python -m venv .venv
```

Activate with `.venv\Scripts\Activate.ps1` in PowerShell, or `source .venv/bin/activate` on Linux/macOS.

```text
python -m pip install -r requirements-test.txt
python -m playwright install chromium
```

Linux may require `python -m playwright install --with-deps chromium`. On Windows, nested Python commands can resolve the base interpreter after activation. Set this variable in the same PowerShell session so those children can find the environment's packages:

```powershell
$env:PYTHONPATH = (Resolve-Path '.venv/Lib/site-packages').Path
```

Start the app and execute the checks:

```text
python scripts/setup_local.py
docker compose up -d --build --wait --wait-timeout 120
python scripts/check_frontend.py
python -m pytest tests/integration tests/e2e -q
```

The frontend check runs `npm ci` and a production build. Integration/browser checks require real services and Chromium; missing prerequisites fail rather than skip. They build candidate images, recreate containers, briefly stop storage, and leave synthetic acceptance uploads in both demo accounts. Run one suite at a time while the demo is idle. Data volumes and existing records are preserved; disposable seeded collection rows and persistence probes are cleaned up. Browser captures go to ignored `test-results/`.

Dependencies are pinned in `frontend/package-lock.json`, `backend/requirements.txt` and `requirements-test.txt`; base images use digests. Python locks were generated with pip-tools 7.6.1 from the adjacent `.in` files.

To inspect the fixture adapter without a host backend environment:

```text
docker compose exec -T api python -m backend.fixture adapt invoice.pdf
```

With backend dependencies installed, `python -m backend.fixture generate` regenerates the committed synthetic fixture artifacts reproducibly. See the [fixture contract](fixture-contract.md) before changing them.
