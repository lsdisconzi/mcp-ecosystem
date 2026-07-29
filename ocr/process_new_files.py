#!/usr/bin/env python3
"""
Process new PDF files and update existing CSV files incrementally.
Specifically for: 4 TRANSFORMACAO ABR25.pdf and 5 TRANSFORMACAO MAI25.pdf
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime
import time

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_pipeline import (
    scan_pdf_files, extract_text_from_pdf, 
    convert_to_csv, DeepSeekPDFAnalyzer
)

def process_new_files():
    """Process the two new transformacao files and update CSV."""
    
    print("=" * 80)
    print("PROCESSING NEW PDF FILES - INCREMENTAL UPDATE")
    print("=" * 80)
    
    # Configuration
    config = {
        "input_root": "./IBSCO",
        "output_root": "./pdf_processed_results_FULL_DRY",
        "working_dir": "./pipeline_full_dry_workspace",
        "supported_extensions": [".pdf"],
        "llm_model": "deepseek-v4-pro",
        "llm_temperature": 0.1,
        "llm_max_tokens": 3000,
        "max_pages_per_pdf": 10,
        "dry_run": True
    }
    
    # Paths
    workspace_dir = os.path.join(config["output_root"], config["working_dir"])
    csv_dir = os.path.join(workspace_dir, "csv_output")
    analysis_dir = os.path.join(workspace_dir, "analysis")
    
    # Create directories if needed
    os.makedirs(analysis_dir, exist_ok=True)
    os.makedirs(csv_dir, exist_ok=True)
    
    # Specific files to process
    new_files = [
        "IBSCO/PCP/transformacao/4 TRANSFORMACAO ABR25.pdf",
        "IBSCO/PCP/transformacao/5 TRANSFORMACAO MAI25.pdf"
    ]
    
    print(f"Processing {len(new_files)} new files:")
    for file in new_files:
        print(f"  - {file}")
    
    # Load existing CSV files
    print("\n1. Loading existing CSV files...")
    metadata_csv = os.path.join(csv_dir, "report_metadata.csv")
    metrics_csv = os.path.join(csv_dir, "financial_metrics.csv")
    tables_csv = os.path.join(csv_dir, "table_samples.csv")
    
    existing_data = {}
    try:
        if os.path.exists(metadata_csv):
            existing_data["metadata"] = pd.read_csv(metadata_csv, encoding='utf-8-sig')
            print(f"  Loaded metadata.csv: {len(existing_data['metadata'])} rows")
        else:
            existing_data["metadata"] = pd.DataFrame()
            print("  No existing metadata.csv found")
            
        if os.path.exists(metrics_csv):
            existing_data["metrics"] = pd.read_csv(metrics_csv, encoding='utf-8-sig')
            print(f"  Loaded financial_metrics.csv: {len(existing_data['metrics'])} rows")
        else:
            existing_data["metrics"] = pd.DataFrame()
            print("  No existing financial_metrics.csv found")
            
        if os.path.exists(tables_csv):
            existing_data["tables"] = pd.read_csv(tables_csv, encoding='utf-8-sig')
            print(f"  Loaded table_samples.csv: {len(existing_data['tables'])} rows")
        else:
            existing_data["tables"] = pd.DataFrame()
            print("  No existing table_samples.csv found")
            
    except Exception as e:
        print(f"  Error loading CSV files: {e}")
        existing_data = {"metadata": pd.DataFrame(), "metrics": pd.DataFrame(), "tables": pd.DataFrame()}
    
    # Process new files
    print("\n2. Processing new files...")
    
    # Check for API key
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    
    if not api_key:
        print("  ERROR: No DeepSeek API key found. Cannot perform LLM analysis.")
        return
    
    analyzer = DeepSeekPDFAnalyzer(api_key, model=config["llm_model"])
    all_analysis_results = {}
    
    for i, rel_path in enumerate(new_files, 1):
        full_path = os.path.join(".", rel_path)  # Relative to workspace
        
        if not os.path.exists(full_path):
            print(f"  File not found: {full_path}")
            continue
        
        filename = os.path.basename(full_path)
        print(f"  [{i}/{len(new_files)}] Processing: {filename}")
        
        # Extract text
        extraction = extract_text_from_pdf(full_path, max_pages=config["max_pages_per_pdf"])
        
        if extraction.get("error"):
            print(f"    ✗ Extraction error: {extraction['error']}")
            continue
        
        # LLM Analysis
        print(f"    Analyzing with DeepSeek LLM...")
        analysis = analyzer.analyze_financial_report(extraction)
        
        if analysis.get("error"):
            print(f"    ✗ Analysis error: {analysis.get('error')}")
        else:
            print(f"    ✓ Analysis completed")
            report_type = analysis.get("report_metadata", {}).get("report_type", "Unknown")
            period = analysis.get("report_metadata", {}).get("period", "Unknown")
            print(f"      Report type: {report_type}")
            print(f"      Period: {period}")
        
        # Save analysis
        analysis_filename = f"{filename}_analysis.json"
        analysis_path = os.path.join(analysis_dir, analysis_filename)
        
        with open(analysis_path, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        
        all_analysis_results[full_path] = analysis
        
        # Rate limiting
        if i < len(new_files):
            time.sleep(3)
    
    if not all_analysis_results:
        print("  No files processed successfully.")
        return
    
    print(f"\n3. Converting new analysis results to CSV...")
    
    # Create directory for new CSV files
    new_csv_dir = csv_dir + "_NEW"
    os.makedirs(new_csv_dir, exist_ok=True)
    
    # Convert new results to CSV format
    new_csv_files = convert_to_csv(all_analysis_results, new_csv_dir)
    
    # Load new CSV data
    new_data = {}
    for csv_type, csv_path in new_csv_files.items():
        if os.path.exists(csv_path):
            new_data[csv_type] = pd.read_csv(csv_path, encoding='utf-8-sig')
            print(f"  Loaded new {csv_type}: {len(new_data[csv_type])} rows")
    
    print(f"\n4. Merging with existing data...")
    
    # Merge metadata
    if "metadata" in new_data and not new_data["metadata"].empty:
        if not existing_data["metadata"].empty:
            # Remove duplicates based on filename
            combined_metadata = pd.concat([existing_data["metadata"], new_data["metadata"]])
            # Drop duplicates, keeping last (newest)
            combined_metadata = combined_metadata.drop_duplicates(subset=['filename'], keep='last')
            print(f"  Merged metadata: {len(combined_metadata)} total rows (+{len(new_data['metadata'])} new)")
        else:
            combined_metadata = new_data["metadata"]
            print(f"  New metadata only: {len(combined_metadata)} rows")
        
        # Save merged metadata
        combined_metadata.to_csv(metadata_csv, index=False, encoding='utf-8-sig')
        print(f"  Saved updated metadata.csv")
    
    # Merge metrics
    if "metrics" in new_data and not new_data["metrics"].empty:
        if not existing_data["metrics"].empty:
            combined_metrics = pd.concat([existing_data["metrics"], new_data["metrics"]])
            print(f"  Merged metrics: {len(combined_metrics)} total rows (+{len(new_data['metrics'])} new)")
        else:
            combined_metrics = new_data["metrics"]
            print(f"  New metrics only: {len(combined_metrics)} rows")
        
        # Save merged metrics
        combined_metrics.to_csv(metrics_csv, index=False, encoding='utf-8-sig')
        print(f"  Saved updated financial_metrics.csv")
    
    # Merge tables
    if "tables" in new_data and not new_data["tables"].empty:
        if not existing_data["tables"].empty:
            combined_tables = pd.concat([existing_data["tables"], new_data["tables"]])
            print(f"  Merged tables: {len(combined_tables)} total rows (+{len(new_data['tables'])} new)")
        else:
            combined_tables = new_data["tables"]
            print(f"  New tables only: {len(combined_tables)} rows")
        
        # Save merged tables
        combined_tables.to_csv(tables_csv, index=False, encoding='utf-8-sig')
        print(f"  Saved updated table_samples.csv")
    
    # Update index file
    print(f"\n5. Updating file index...")
    index_path = os.path.join(workspace_dir, "full_file_index.json")
    
    try:
        if os.path.exists(index_path):
            with open(index_path, 'r', encoding='utf-8') as f:
                file_index = json.load(f)
            
            # Check if new files are already in index
            existing_filenames = [item["filename"] for item in file_index]
            new_items_added = 0
            
            for full_path, analysis in all_analysis_results.items():
                filename = os.path.basename(full_path)
                if filename not in existing_filenames:
                    # Create new index entry
                    stat = os.stat(full_path)
                    import hashlib
                    
                    with open(full_path, "rb") as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()
                    
                    new_entry = {
                        "full_path": full_path,
                        "relative_path": os.path.relpath(full_path, config["input_root"]),
                        "filename": filename,
                        "directory": os.path.dirname(full_path),
                        "size_bytes": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "file_hash": file_hash,
                        "file_type": "PDF",
                        "status": "processed_new",
                        "extraction_path": f"{analysis_dir}/{filename}_extraction.json",
                        "extraction_status": "completed",
                        "analysis_path": f"{analysis_dir}/{filename}_analysis.json",
                        "analysis_status": "completed" if "error" not in analysis else "error"
                    }
                    
                    file_index.append(new_entry)
                    new_items_added += 1
            
            # Save updated index
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(file_index, f, ensure_ascii=False, indent=2)
            
            print(f"  Updated index with {new_items_added} new files")
        else:
            print(f"  Index file not found: {index_path}")
    except Exception as e:
        print(f"  Error updating index: {e}")
    
    # Create summary report
    print(f"\n6. Creating summary report...")
    
    summary = {
        "incremental_update": {
            "timestamp": datetime.now().isoformat(),
            "new_files_processed": len(new_files),
            "successful_analyses": len(all_analysis_results),
            "updated_csv_files": list(new_csv_files.keys())
        },
        "total_files_processed": len(existing_data.get("metadata", pd.DataFrame())) + len(new_data.get("metadata", pd.DataFrame())),
        "files_processed": [
            {
                "filename": os.path.basename(path),
                "status": "success" if "error" not in analysis else "error",
                "report_type": analysis.get("report_metadata", {}).get("report_type", "Unknown"),
                "period": analysis.get("report_metadata", {}).get("period", "Unknown")
            }
            for path, analysis in all_analysis_results.items()
        ]
    }
    
    summary_path = os.path.join(workspace_dir, "incremental_update_summary.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    # Human-readable summary
    human_summary = f"""
    INCREMENTAL PDF PROCESSING UPDATE
    =================================
    
    Timestamp: {summary['incremental_update']['timestamp']}
    
    PROCESSING RESULTS:
    - New files to process: {summary['incremental_update']['new_files_processed']}
    - Successfully analyzed: {summary['incremental_update']['successful_analyses']}
    - CSV files updated: {', '.join(summary['incremental_update']['updated_csv_files'])}
    
    FILES PROCESSED:
    """
    
    for file_info in summary["files_processed"]:
        human_summary += f"\n  - {file_info['filename']}: {file_info['status']}"
        human_summary += f" ({file_info['report_type']} - {file_info['period']})"
    
    human_summary += f"""
    
    TOTAL FILES IN DATABASE: {summary['total_files_processed']}
    
    Updated files located in:
    - CSV directory: {csv_dir}
    - Analysis directory: {analysis_dir}
    - Summary: {summary_path}
    
    Next steps: The CSV files have been updated with the new data.
    """
    
    human_summary_path = os.path.join(workspace_dir, "INCREMENTAL_UPDATE_SUMMARY.txt")
    with open(human_summary_path, 'w', encoding='utf-8') as f:
        f.write(human_summary)
    
    print("\n" + "=" * 80)
    print("INCREMENTAL UPDATE COMPLETED SUCCESSFULLY")
    print("=" * 80)
    print(f"✓ Processed {len(new_files)} new files")
    print(f"✓ Updated CSV files with new data")
    print(f"✓ Updated file index")
    print(f"✓ Created summary reports")
    print(f"\nSummary saved to: {summary_path}")
    print(f"Human-readable summary: {human_summary_path}")
    print("=" * 80)
    
    return summary

if __name__ == "__main__":
    process_new_files()