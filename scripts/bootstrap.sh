#!/usr/bin/env bash
set -euo pipefail

mkdir -p data/{objects,reports,secrets}
if [ ! -f data/secrets/master.key ]; then
  python3 - <<'PY'
from cryptography.fernet import Fernet
from pathlib import Path

p = Path('data/secrets/master.key')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(Fernet.generate_key())
print(f"created {p}")
PY
fi

echo "Bootstrap complete."
