#!/bin/bash
# Quick Start Script for Legal CSV Ingestion
# This script demonstrates the complete workflow

echo "=========================================="
echo "Legal CSV Ingestion - Quick Start"
echo "=========================================="
echo ""

# Check if virtual environment is active
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "⚠️  Virtual environment not detected. Activating..."
    source venv/bin/activate
fi

# Install dependencies
echo "📦 Installing required dependencies..."
pip install -q pandas numpy sentence-transformers langchain langchain-text-splitters qdrant-client

echo ""
echo "✅ Dependencies installed"
echo ""

# Check if Qdrant is running
echo "🔍 Checking Qdrant connection..."
if curl -s http://localhost:6333/collections > /dev/null 2>&1; then
    echo "✅ Qdrant is running"
else
    echo "❌ Qdrant is not running on localhost:6333"
    echo ""
    echo "Please start Qdrant with:"
    echo "  docker run -p 6333:6333 qdrant/qdrant"
    echo ""
    echo "Or update .env with your Qdrant Cloud credentials:"
    echo "  QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333"
    echo "  QDRANT_API_KEY=your-api-key"
    exit 1
fi

echo ""
echo "=========================================="
echo "Example 1: Dry Run (Validation Only)"
echo "=========================================="
echo ""

python scripts/ingest_legal_csv.py \
    --csv data/jurisprudencia_exemplo.csv \
    --collection jurisprudencia_test \
    --dry-run

echo ""
echo "=========================================="
echo "Example 2: Actual Ingestion"
echo "=========================================="
echo ""

read -p "Proceed with actual ingestion? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    python scripts/ingest_legal_csv.py \
        --csv data/jurisprudencia_exemplo.csv \
        --collection jurisprudencia_exemplo \
        --recreate \
        --verbose
    
    echo ""
    echo "=========================================="
    echo "Example 3: Search Test"
    echo "=========================================="
    echo ""
    
    # Create a simple Python search test
    python3 << 'PYEOF'
from services.legal_document_ingestor import LegalDocumentIngestor
import os

print("Testing search functionality...\n")

ingestor = LegalDocumentIngestor(
    qdrant_url=os.getenv("QDRANT_URL", "localhost"),
    qdrant_port=int(os.getenv("QDRANT_PORT", "6333"))
)

# Test query
query = "apelação cível contratos"
print(f"Query: '{query}'\n")

results = ingestor.search(
    collection_name="jurisprudencia_exemplo",
    query=query,
    limit=3
)

print(f"Found {len(results)} results:\n")
print("=" * 80)

for i, result in enumerate(results, 1):
    print(f"\n{i}. Score: {result['score']:.3f}")
    print(f"Processo: {result['metadata'].get('processo', 'N/A')}")
    print(f"Classe: {result['metadata'].get('classe', 'N/A')}")
    print(f"Relator: {result['metadata'].get('relator', 'N/A')}")
    print(f"\nPreview:\n{result['text'][:300]}...")
    print("=" * 80)

print("\n✅ Search test complete!")
PYEOF

    echo ""
    echo "=========================================="
    echo "✅ Quick Start Complete!"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "  1. Check the API docs:"
    echo "     uvicorn main:app --reload"
    echo "     Then visit: http://localhost:8000/docs"
    echo ""
    echo "  2. Upload your own CSV:"
    echo "     python scripts/ingest_legal_csv.py --csv YOUR_FILE.csv --collection YOUR_COLLECTION"
    echo ""
    echo "  3. Use the API:"
    echo "     curl -X POST 'http://localhost:8000/legal-ingestion/search/jurisprudencia_exemplo' \\"
    echo "       -H 'Content-Type: application/json' \\"
    echo "       -d '{\"query\": \"your search query\", \"limit\": 5}'"
    echo ""
else
    echo "Skipped actual ingestion."
fi
