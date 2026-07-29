import os
import sys
from pathlib import Path

# Ensure project root is on the import path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from main import app

# Ensure DEEPSEEK_API_KEY is set for the test run
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-placeholder")

client = TestClient(app)

payload = {
    "messages": [{"role": "user", "content": "Hello from test"}],
    "stream": False,
    "model": "v3.2-exp"
}

print("Sending test payload to /v1/assistants/deepseek-stream-proxy")
resp = client.post("/v1/assistants/deepseek-stream-proxy", json=payload)
print("Status code:", resp.status_code)
try:
    print("JSON:", resp.json())
except Exception:
    print("Text:", resp.text)
