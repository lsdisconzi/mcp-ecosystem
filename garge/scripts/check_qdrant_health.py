"""Small script to check Qdrant connectivity and provide troubleshooting hints.

Usage: python scripts/check_qdrant_health.py
"""
from dotenv import load_dotenv
from core.qdrant_client import get_qdrant_client
from fastapi import HTTPException
import os

# Ensure environment variables from .env are loaded when running this script
load_dotenv()


def main():
    try:
        # Respect QDRANT_URL/QDRANT_API_KEY if present
        if os.getenv('QDRANT_URL'):
            print(f"Attempting to connect using QDRANT_URL={os.getenv('QDRANT_URL')}")
        else:
            print(f"Attempting to connect to localhost on default port (env QDRANT_HOST/QDRANT_PORT can override)")

        client = get_qdrant_client()
        collections = client.get_collections()
        print(f"✅ Qdrant reachable. Collections: {len(collections.collections)}")
    except HTTPException as e:
        print("❌ Qdrant unavailable (HTTP 503). Details:")
        print(e.detail)
        print("\nTip: Start a local Qdrant: docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant")
        print("If using cloud Qdrant, ensure QDRANT_URL and QDRANT_API_KEY environment variables are set.")
    except Exception as e:
        print("❌ Unexpected error while checking Qdrant:", str(e))
        print("Make sure you run this script from the project root with: PYTHONPATH=. python3 scripts/check_qdrant_health.py")


if __name__ == '__main__':
    main()
