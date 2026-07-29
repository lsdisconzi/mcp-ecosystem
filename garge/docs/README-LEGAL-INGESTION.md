# Legal Document Ingestion System

Complete system for ingesting legal CSV files (jurisprudência) into Qdrant vector database with semantic search capabilities.

## 🌟 Features

- **CSV Processing**: Intelligent cleaning and preprocessing of legal documents
- **Text Chunking**: Legal-document-aware text splitting with configurable sizes
- **Metadata Extraction**: Automatic extraction of parties, decisions, legal basis, and precedents
- **Portuguese Optimization**: Support for Portuguese-specific embedding models
- **Flexible Ingestion**: Both API endpoints and command-line tools
- **Semantic Search**: Vector similarity search with metadata filtering
- **Batch Processing**: Efficient handling of large document sets

## 📋 Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [CSV Format](#csv-format)
- [Usage Methods](#usage-methods)
  - [Command Line](#command-line)
  - [API Endpoints](#api-endpoints)
  - [Python API](#python-api)
- [Configuration](#configuration)
- [Advanced Features](#advanced-features)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## 🔧 Installation

### 1. Install Dependencies

```bash
# Install required packages
pip install -r requirements.txt

# Or install individually
pip install pandas numpy sentence-transformers langchain qdrant-client
```

### 2. Start Qdrant

```bash
# Using Docker
docker run -p 6333:6333 qdrant/qdrant

# Or use Qdrant Cloud (configure QDRANT_URL and QDRANT_API_KEY)
```

### 3. Configure Environment

Create a `.env` file:

```env
# Qdrant Configuration
QDRANT_URL=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=  # Optional, for Qdrant Cloud

# Embedding Model (Optional)
LEGAL_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

## 🚀 Quick Start

### Basic Command Line Usage

```bash
# Simple ingestion
python scripts/ingest_legal_csv.py \
  --csv data/jurisprudencia.csv \
  --collection jurisprudencia

# With custom settings
python scripts/ingest_legal_csv.py \
  --csv data/jurisprudencia.csv \
  --collection legal_docs \
  --chunk-size 1000 \
  --recreate
```

### API Usage

```bash
# Start FastAPI server (add to main.py first)
uvicorn main:app --reload

# Upload CSV via API
curl -X POST "http://localhost:8000/legal-ingestion/upload-csv?collection_name=jurisprudencia" \
  -F "file=@jurisprudencia.csv"
```

## 📄 CSV Format

Your CSV file should contain the following columns:

### Required Columns
- `id`: Unique document identifier
- `texto`: Full text of the legal document

### Recommended Columns
- `processo`: Case number (e.g., "0001234-56.2023.8.26.0100")
- `relator`: Judge/Relator name
- `origem`: Court of origin
- `classe`: Case type (e.g., "APELAÇÃO CÍVEL", "RECURSO ESPECIAL")
- `julgado_em`: Judgment date

### Example CSV Structure

```csv
id,processo,relator,origem,classe,julgado_em,texto
1,0001234-56.2023.8.26.0100,Des. João Silva,1ª Vara Cível,APELAÇÃO CÍVEL,2023-05-15,"EMENTA: Apelação cível. Direito civil..."
2,0005678-90.2023.8.26.0200,Des. Maria Santos,2ª Vara Cível,AGRAVO,2023-06-20,"ACÓRDÃO: Vistos e relatados..."
```

## 💻 Usage Methods

### Command Line

The standalone script provides full control over ingestion:

```bash
# Basic usage
python scripts/ingest_legal_csv.py --csv FILE.csv --collection NAME

# All options
python scripts/ingest_legal_csv.py \
  --csv jurisprudencia.csv \              # Input CSV file
  --collection jurisprudencia \           # Collection name
  --text-column texto \                   # Text column name
  --chunk-size 800 \                      # Chunk size (characters)
  --chunk-overlap 100 \                   # Overlap between chunks
  --qdrant-url localhost \                # Qdrant host
  --qdrant-port 6333 \                    # Qdrant port
  --model paraphrase-multilingual-MiniLM-L12-v2 \  # Embedding model
  --recreate \                            # Recreate collection
  --verbose                               # Verbose output

# Dry run (validate without ingesting)
python scripts/ingest_legal_csv.py \
  --csv jurisprudencia.csv \
  --collection test \
  --dry-run
```

### API Endpoints

#### 1. Upload and Ingest CSV

```bash
curl -X POST "http://localhost:8000/legal-ingestion/upload-csv?collection_name=jurisprudencia&recreate_collection=true" \
  -F "file=@jurisprudencia.csv"
```

**Response:**
```json
{
  "success": true,
  "message": "CSV ingestion completed successfully",
  "collection_name": "jurisprudencia",
  "total_documents": 1500,
  "total_chunks": 8245,
  "total_points": 8245,
  "duration_seconds": 324.5
}
```

#### 2. Ingest from Server Path

```bash
curl -X POST "http://localhost:8000/legal-ingestion/ingest-file?file_path=/data/jurisprudencia.csv" \
  -H "Content-Type: application/json" \
  -d '{
    "collection_name": "jurisprudencia",
    "text_column": "texto",
    "recreate_collection": true,
    "chunk_size": 800,
    "chunk_overlap": 100
  }'
```

#### 3. Search Documents

```bash
curl -X POST "http://localhost:8000/legal-ingestion/search/jurisprudencia" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "recurso de apelação cível relacionado a contratos",
    "limit": 10,
    "filters": {
      "classe": "APELAÇÃO CÍVEL",
      "relator": "Des. João Silva"
    }
  }'
```

**Response:**
```json
{
  "query": "recurso de apelação cível relacionado a contratos",
  "results": [
    {
      "id": "abc123",
      "score": 0.92,
      "text": "EMENTA: Apelação cível. Direito civil. Contratos...",
      "metadata": {
        "processo": "0001234-56.2023.8.26.0100",
        "relator": "Des. João Silva",
        "classe": "APELAÇÃO CÍVEL"
      }
    }
  ],
  "total_results": 10
}
```

#### 4. List Collections

```bash
curl http://localhost:8000/legal-ingestion/collections
```

#### 5. Get Collection Info

```bash
curl http://localhost:8000/legal-ingestion/collection/jurisprudencia/info
```

#### 6. Delete Collection

```bash
curl -X DELETE http://localhost:8000/legal-ingestion/collection/jurisprudencia
```

### Python API

Direct usage in Python code:

```python
from services.legal_document_ingestor import LegalDocumentIngestor

# Initialize ingestor
ingestor = LegalDocumentIngestor(
    qdrant_url="localhost",
    qdrant_port=6333,
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    chunk_size=800,
    chunk_overlap=100
)

# Ingest CSV
result = ingestor.ingest_csv(
    csv_path="jurisprudencia.csv",
    collection_name="jurisprudencia",
    text_column="texto",
    recreate_collection=True
)

print(f"Ingested {result['total_documents']} documents")
print(f"Created {result['total_chunks']} chunks")

# Search
results = ingestor.search(
    collection_name="jurisprudencia",
    query="recurso de apelação sobre contratos",
    limit=5,
    filters={"classe": "APELAÇÃO CÍVEL"}
)

for result in results:
    print(f"Score: {result['score']:.2f}")
    print(f"Text: {result['text'][:200]}...")
    print(f"Metadata: {result['metadata']}")
    print("-" * 80)
```

## ⚙️ Configuration

### Embedding Models

Choose a model based on your needs:

#### Multilingual (Recommended for Portuguese)
```python
# Fast, good quality, multilingual including Portuguese
"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Larger, better quality
"sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
```

#### Portuguese-Specific
```python
# Portuguese BERT
"neuralmind/bert-base-portuguese-cased"

# Legal Portuguese (if available)
"pierreguillou/bert-base-cased-pt-lenerbr"
```

### Chunking Strategy

```python
# For shorter documents (e.g., ementas)
chunk_size=500
chunk_overlap=50

# For standard legal documents (recommended)
chunk_size=800
chunk_overlap=100

# For long documents with complex structure
chunk_size=1200
chunk_overlap=200
```

### Metadata Columns

Control which columns are stored as metadata:

```python
# Include all columns (default)
metadata_columns=None

# Include specific columns
metadata_columns=["processo", "relator", "classe", "julgado_em"]
```

## 🔥 Advanced Features

### Hierarchical Chunking

Process documents with section awareness:

```python
from utils.legal_csv_processor import LegalTextCleaner

cleaner = LegalTextCleaner()

# Split by legal sections
sections = cleaner.split_by_legal_sections(document_text)

for section in sections:
    print(f"{section['type']}: {section['content'][:100]}...")
```

### Metadata Extraction

Automatic extraction of structured information:

```python
from utils.legal_csv_processor import LegalMetadataExtractor

extractor = LegalMetadataExtractor()

# Extract parties
parties = extractor.extract_parties(document_text)
# Returns: {'autor': 'João Silva', 'reu': 'Empresa XYZ'}

# Extract decision
decision = extractor.extract_decision(document_text)

# Extract legal basis
legal_refs = extractor.extract_legal_basis(document_text)
# Returns: ['Lei 8.078/90', 'Art. 186', 'Código Civil']

# Extract precedents
precedents = extractor.extract_precedents(document_text)
# Returns: ['REsp 1234567', 'Súmula 123']
```

### Filtered Search

Search with complex filters:

```python
results = ingestor.search(
    collection_name="jurisprudencia",
    query="responsabilidade civil",
    limit=20,
    filters={
        "classe": "APELAÇÃO CÍVEL",
        "ano": 2023,
        "origem": "1ª Vara Cível"
    }
)
```

### Batch Processing

Process multiple CSV files:

```python
import glob

csv_files = glob.glob("data/jurisprudencia_*.csv")

for csv_file in csv_files:
    collection_name = f"legal_{Path(csv_file).stem}"
    
    result = ingestor.ingest_csv(
        csv_path=csv_file,
        collection_name=collection_name,
        recreate_collection=True
    )
    
    print(f"Processed {csv_file}: {result['total_chunks']} chunks")
```

## 📚 Examples

### Example 1: Basic Ingestion

```bash
python scripts/ingest_legal_csv.py \
  --csv jurisprudencia.csv \
  --collection jurisprudencia_2024 \
  --recreate
```

### Example 2: Custom Configuration

```bash
python scripts/ingest_legal_csv.py \
  --csv data/acórdãos.csv \
  --collection acordaos \
  --text-column texto_completo \
  --chunk-size 1000 \
  --chunk-overlap 150 \
  --model neuralmind/bert-base-portuguese-cased \
  --verbose
```

### Example 3: Programmatic Usage

```python
from services.legal_document_ingestor import LegalDocumentIngestor
import os

# Configure
ingestor = LegalDocumentIngestor(
    qdrant_url=os.getenv("QDRANT_URL", "localhost"),
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)

# Ingest
result = ingestor.ingest_csv(
    csv_path="jurisprudencia.csv",
    collection_name="jurisprudencia",
    recreate_collection=True
)

if result['success']:
    print(f"✓ Ingested {result['total_documents']} documents")
    
    # Test search
    results = ingestor.search(
        collection_name="jurisprudencia",
        query="apelação cível contratos",
        limit=3
    )
    
    for r in results:
        print(f"\nScore: {r['score']:.3f}")
        print(f"Processo: {r['metadata'].get('processo', 'N/A')}")
        print(f"Preview: {r['text'][:200]}...")
else:
    print(f"✗ Error: {result['error']}")
```

### Example 4: API Integration in FastAPI

Add to your [main.py](main.py):

```python
from fastapi import FastAPI
from routes.legal_ingestion import router as legal_router

app = FastAPI(title="Legal Document System")

# Include legal ingestion routes
app.include_router(legal_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

Then access API docs at: `http://localhost:8000/docs`

## 🐛 Troubleshooting

### Issue: "Column 'texto' not found"

**Solution:** Specify your text column name:
```bash
--text-column your_column_name
```

### Issue: Out of memory during ingestion

**Solution:** Use smaller chunks or batch size:
```python
ingestor = LegalDocumentIngestor(chunk_size=500)  # Smaller chunks
```

Or process in batches:
```python
# Split CSV into smaller files first
df = pd.read_csv("large_file.csv")
for i, chunk in enumerate(np.array_split(df, 10)):
    chunk.to_csv(f"batch_{i}.csv", index=False)
```

### Issue: Slow embedding generation

**Solutions:**
1. Use a smaller/faster model:
   ```bash
   --model sentence-transformers/all-MiniLM-L6-v2
   ```

2. Use GPU acceleration (if available):
   ```python
   model = SentenceTransformer(model_name, device='cuda')
   ```

### Issue: Qdrant connection error

**Solution:** Verify Qdrant is running:
```bash
# Check if Qdrant is accessible
curl http://localhost:6333/collections

# Or start Qdrant
docker run -p 6333:6333 qdrant/qdrant
```

### Issue: Encoding errors reading CSV

**Solution:** The processor tries multiple encodings automatically, but you can specify:
```python
df = pd.read_csv("file.csv", encoding="latin-1")
```

## 📊 Performance Tips

1. **Batch Size**: Adjust based on available memory
   - Default: 32 for embeddings, 100 for uploads
   - Increase for faster processing with more memory

2. **Chunk Size**: Balance between context and granularity
   - Smaller chunks (500-800): Better for precise search
   - Larger chunks (1000-1500): Better for context understanding

3. **Model Selection**: Trade-off between speed and quality
   - Fast: `all-MiniLM-L6-v2` (384 dim)
   - Balanced: `paraphrase-multilingual-MiniLM-L12-v2` (384 dim)
   - Quality: `paraphrase-multilingual-mpnet-base-v2` (768 dim)

4. **Indexing**: The system automatically creates indexes on common fields
   - `processo`, `classe`, `relator`, `origem`, `ano`

## 📝 License

This code is part of the SA Server project.

## 🤝 Contributing

For issues or improvements, please create an issue or pull request.

## 📞 Support

For questions or support, please refer to the main project documentation.

---

**Note**: This system is optimized for Brazilian legal documents (Portuguese language) but can be adapted for other languages by changing the embedding model.
