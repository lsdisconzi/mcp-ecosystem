#!/usr/bin/env python3
"""
Legal CSV Ingestion Script
Command-line tool for batch processing legal CSV files into Qdrant.

Usage:
    python scripts/ingest_legal_csv.py --csv jurisprudencia.csv --collection jurisprudencia
    
    python scripts/ingest_legal_csv.py --csv data.csv --collection legal_docs --recreate \\
        --chunk-size 1000 --text-column texto_completo
"""
import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.legal_document_ingestor import LegalDocumentIngestor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('data/logs/legal_ingestion.log')
    ]
)
logger = logging.getLogger(__name__)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Ingest legal CSV files into Qdrant vector database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic ingestion
  python scripts/ingest_legal_csv.py --csv jurisprudencia.csv --collection jurisprudencia
  
  # With custom settings
  python scripts/ingest_legal_csv.py \\
    --csv data/legal_docs.csv \\
    --collection legal_docs_2024 \\
    --text-column texto_completo \\
    --chunk-size 1000 \\
    --chunk-overlap 150 \\
    --recreate
  
  # Portuguese legal model
  python scripts/ingest_legal_csv.py \\
    --csv jurisprudencia.csv \\
    --collection jurisprudencia \\
    --model neuralmind/bert-base-portuguese-cased
  
  # With Qdrant Cloud
  python scripts/ingest_legal_csv.py \\
    --csv data.csv \\
    --collection legal \\
    --qdrant-url https://xxx.cloud.qdrant.io:6333 \\
    --qdrant-api-key your-api-key
        """
    )
    
    # Required arguments
    parser.add_argument(
        '--csv',
        type=str,
        required=True,
        help='Path to CSV file containing legal documents'
    )
    parser.add_argument(
        '--collection',
        type=str,
        required=True,
        help='Name of the Qdrant collection to create/update'
    )
    
    # Optional CSV parsing arguments
    parser.add_argument(
        '--text-column',
        type=str,
        default='texto',
        help='Name of column containing legal text (default: texto)'
    )
    parser.add_argument(
        '--metadata-columns',
        type=str,
        nargs='+',
        default=None,
        help='List of columns to include as metadata (default: all columns)'
    )
    
    # Chunking arguments
    parser.add_argument(
        '--chunk-size',
        type=int,
        default=800,
        help='Size of text chunks in characters (default: 800)'
    )
    parser.add_argument(
        '--chunk-overlap',
        type=int,
        default=100,
        help='Overlap between chunks in characters (default: 100)'
    )
    
    # Qdrant connection arguments
    parser.add_argument(
        '--qdrant-url',
        type=str,
        default=os.getenv('QDRANT_URL', 'localhost'),
        help='Qdrant server URL (default: localhost or QDRANT_URL env var)'
    )
    parser.add_argument(
        '--qdrant-port',
        type=int,
        default=int(os.getenv('QDRANT_PORT', '6333')),
        help='Qdrant server port (default: 6333 or QDRANT_PORT env var)'
    )
    parser.add_argument(
        '--qdrant-api-key',
        type=str,
        default=os.getenv('QDRANT_API_KEY'),
        help='Qdrant API key for cloud instances (default: QDRANT_API_KEY env var)'
    )
    
    # Model arguments
    parser.add_argument(
        '--model',
        type=str,
        default='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        help='Sentence transformer model name (default: multilingual MiniLM)'
    )
    
    # Collection management
    parser.add_argument(
        '--recreate',
        action='store_true',
        help='Delete and recreate collection if it exists'
    )
    
    # Dry run
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate CSV and show statistics without ingesting'
    )
    
    # Verbosity
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Only show errors'
    )
    
    return parser.parse_args()


def validate_csv(csv_path: str, text_column: str) -> bool:
    """
    Validate CSV file exists and has required columns.
    
    Args:
        csv_path: Path to CSV file
        text_column: Name of text column
        
    Returns:
        True if valid
        
    Raises:
        ValueError: If validation fails
    """
    import pandas as pd
    
    if not os.path.exists(csv_path):
        raise ValueError(f"CSV file not found: {csv_path}")
    
    # Try to read first few rows
    try:
        df = pd.read_csv(csv_path, nrows=5)
    except Exception as e:
        raise ValueError(f"Unable to read CSV file: {e}")
    
    # Check for required columns
    if 'id' not in df.columns:
        raise ValueError("CSV must contain 'id' column")
    
    if text_column not in df.columns:
        raise ValueError(
            f"Text column '{text_column}' not found. Available columns: {list(df.columns)}"
        )
    
    logger.info(f"CSV validation passed. Columns: {list(df.columns)}")
    return True


def show_dry_run_info(csv_path: str, text_column: str):
    """
    Show information about the CSV without ingesting.
    
    Args:
        csv_path: Path to CSV file
        text_column: Name of text column
    """
    import pandas as pd
    
    logger.info("=" * 60)
    logger.info("DRY RUN - CSV Analysis")
    logger.info("=" * 60)
    
    # Load full CSV
    df = pd.read_csv(csv_path)
    
    logger.info(f"\nFile: {csv_path}")
    logger.info(f"Total rows: {len(df)}")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"\nColumn types:")
    for col, dtype in df.dtypes.items():
        logger.info(f"  {col}: {dtype}")
    
    # Text statistics
    if text_column in df.columns:
        text_lengths = df[text_column].str.len()
        logger.info(f"\nText column '{text_column}' statistics:")
        logger.info(f"  Average length: {text_lengths.mean():.0f} characters")
        logger.info(f"  Min length: {text_lengths.min():.0f} characters")
        logger.info(f"  Max length: {text_lengths.max():.0f} characters")
        logger.info(f"  Total characters: {text_lengths.sum():.0f}")
    
    # Sample data
    logger.info(f"\nFirst row sample:")
    for col in df.columns[:5]:  # Show first 5 columns
        value = str(df[col].iloc[0])
        preview = value[:100] + "..." if len(value) > 100 else value
        logger.info(f"  {col}: {preview}")
    
    # Null values
    null_counts = df.isnull().sum()
    if null_counts.any():
        logger.info(f"\nNull values:")
        for col, count in null_counts[null_counts > 0].items():
            logger.info(f"  {col}: {count} ({count/len(df)*100:.1f}%)")
    
    logger.info("\n" + "=" * 60)


def main():
    """Main execution function."""
    args = parse_arguments()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    
    logger.info("=" * 60)
    logger.info("Legal CSV Ingestion Tool")
    logger.info("=" * 60)
    
    try:
        # Validate CSV
        logger.info(f"Validating CSV file: {args.csv}")
        validate_csv(args.csv, args.text_column)
        
        # Dry run mode
        if args.dry_run:
            show_dry_run_info(args.csv, args.text_column)
            logger.info("\nDry run complete. Use without --dry-run to ingest.")
            return 0
        
        # Initialize ingestor
        logger.info(f"Initializing ingestor with model: {args.model}")
        logger.info(f"Qdrant connection: {args.qdrant_url}:{args.qdrant_port}")
        
        ingestor = LegalDocumentIngestor(
            qdrant_url=args.qdrant_url,
            qdrant_port=args.qdrant_port,
            qdrant_api_key=args.qdrant_api_key,
            model_name=args.model,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap
        )
        
        # Perform ingestion
        logger.info("=" * 60)
        logger.info(f"Starting ingestion into collection: {args.collection}")
        logger.info(f"Text column: {args.text_column}")
        logger.info(f"Chunk size: {args.chunk_size}, Overlap: {args.chunk_overlap}")
        logger.info(f"Recreate collection: {args.recreate}")
        logger.info("=" * 60)
        
        result = ingestor.ingest_csv(
            csv_path=args.csv,
            collection_name=args.collection,
            text_column=args.text_column,
            recreate_collection=args.recreate,
            metadata_columns=args.metadata_columns
        )
        
        # Display results
        logger.info("=" * 60)
        if result['success']:
            logger.info("✓ INGESTION SUCCESSFUL")
            logger.info("=" * 60)
            logger.info(f"Collection: {result['collection_name']}")
            logger.info(f"Documents processed: {result['total_documents']}")
            logger.info(f"Chunks created: {result['total_chunks']}")
            logger.info(f"Points uploaded: {result['total_points']}")
            logger.info(f"Avg chunks per document: {result['chunks_per_document']:.2f}")
            logger.info(f"Embedding dimension: {result['embedding_dimension']}")
            logger.info(f"Duration: {result['duration_seconds']:.2f} seconds")
            logger.info("=" * 60)
            return 0
        else:
            logger.error("✗ INGESTION FAILED")
            logger.error("=" * 60)
            logger.error(f"Error: {result.get('error', 'Unknown error')}")
            logger.error("=" * 60)
            return 1
    
    except KeyboardInterrupt:
        logger.warning("\nIngestion interrupted by user")
        return 130
    
    except Exception as e:
        logger.error(f"\nFatal error: {e}", exc_info=args.verbose)
        return 1


if __name__ == '__main__':
    sys.exit(main())
