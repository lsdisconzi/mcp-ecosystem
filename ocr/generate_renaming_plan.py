#!/usr/bin/env python3
"""
Generate comprehensive renaming plan from CSV metadata.
Alternative approach to the LLM-based renaming that failed.
"""

import os
import json
import pandas as pd
from datetime import datetime

def generate_renaming_plan_from_csv():
    """Generate renaming plan directly from CSV metadata."""
    
    print("=" * 80)
    print("GENERATING RENAMING PLAN FROM CSV METADATA")
    print("=" * 80)
    
    # Paths
    workspace_dir = "./pdf_processed_results_FULL_DRY/pipeline_full_dry_workspace"
    csv_dir = os.path.join(workspace_dir, "csv_output")
    metadata_csv = os.path.join(csv_dir, "report_metadata.csv")
    
    if not os.path.exists(metadata_csv):
        print(f"ERROR: Metadata CSV not found: {metadata_csv}")
        return
    
    # Load metadata
    print(f"\n1. Loading metadata from: {metadata_csv}")
    metadata_df = pd.read_csv(metadata_csv, encoding='utf-8-sig')
    print(f"   Loaded {len(metadata_df)} records")
    
    # Define naming convention
    naming_convention = """
    [ReportType]_[Period]_[Company]_[Date].pdf
    
    Rules:
    1. ReportType: Abbreviated report type in Portuguese
    2. Period: Month and year (e.g., JANEIRO_2025, FEVEREIRO_2026)
    3. Company: IBSCO (abbreviated from company name)
    4. Date: Report generation date in YYYYMMDD format
    
    Examples:
    - DRE_JANEIRO_2026_IBSCO_20260211.pdf
    - Mapa_Producao_FEVEREIRO_2026_IBSCO_20260305.pdf
    - Custo_Operacional_JANEIRO_2026_IBSCO_20260211.pdf
    """
    
    # Define directory structure
    directory_structure = [
        "Financeiro/",
        "Financeiro/DRE/",
        "Financeiro/DRE/2025/",
        "Financeiro/DRE/2026/",
        "Financeiro/Balancetes/",
        "Financeiro/Custos_Operacionais/",
        "Financeiro/Estoque/",
        "Financeiro/Estoque/Posicao_Financeira/",
        "Financeiro/Resultados_Brutos/",
        "Financeiro/Vendas/",
        "Financeiro/Vendas/Resumos_Mensais/",
        "Financeiro/Compras/",
        "Financeiro/Compras/Resumos/",
        "Contabilidade/",
        "Contabilidade/Extratos/",
        "Contabilidade/Impostos/",
        "Contabilidade/Passivo/",
        "Producao/",
        "Producao/Mapas_de_Producao/",
        "Producao/Mapas_Transformacao/",
        "Producao/Transformacao/",
        "Producao/Relatorios_Transformacao/"
    ]
    
    # Generate file mapping
    file_mapping = []
    
    print("\n2. Generating file mapping...")
    
    for idx, row in metadata_df.iterrows():
        filename = row['filename']
        current_filepath = row['filepath']
        suggested_filename = row['file_name_suggestion']
        suggested_directory = row['directory_suggestion']
        report_type = row['report_type']
        period = row['period']
        
        # Clean and validate suggested filename
        if pd.isna(suggested_filename) or suggested_filename.strip() == "":
            # Generate filename from metadata
            clean_period = "PERIODO_DESCONHECIDO"
            if isinstance(period, str):
                # Extract month and year
                import re
                month_map = {
                    'janeiro': 'JANEIRO', 'fevereiro': 'FEVEREIRO', 'março': 'MARCO', 'marco': 'MARCO',
                    'abril': 'ABRIL', 'maio': 'MAIO', 'junho': 'JUNHO',
                    'julho': 'JULHO', 'agosto': 'AGOSTO', 'setembro': 'SETEMBRO',
                    'outubro': 'OUTUBRO', 'novembro': 'NOVEMBRO', 'dezembro': 'DEZEMBRO'
                }
                
                period_lower = period.lower()
                month_found = None
                for month_pt, month_upper in month_map.items():
                    if month_pt in period_lower:
                        month_found = month_upper
                        break
                
                year_found = None
                year_match = re.search(r'20\d{2}', period)
                if year_match:
                    year_found = year_match.group()
                
                if month_found and year_found:
                    clean_period = f"{month_found}_{year_found}"
            
            # Generate report type abbreviation
            report_type_clean = "REPORTE"
            if isinstance(report_type, str):
                type_map = {
                    'DRE': 'DRE',
                    'Mapa de Produção': 'Mapa_Producao',
                    'Mapa de Produção/Transformação': 'Mapa_Transformacao',
                    'Custo Operacional': 'Custo_Operacional',
                    'Posição Financeira do Estoque': 'Posicao_Financeira_Estoque',
                    'Balancete Industrial': 'Balancete_Industrial',
                    'Extrato Contábil': 'Extrato_Contabil',
                    'Resultado Bruto': 'Resultado_Bruto',
                    'Resumo de Compras': 'Resumo_Compras',
                    'Resumo de Vendas': 'Resumo_Vendas',
                    'Despesas Financeiras': 'Despesas_Financeiras',
                    'IRPJ e CSL': 'IRPJ_CSL',
                    'Receitas Financeiras': 'Receitas_Financeiras',
                    'Resumo de Vendas/Receitas': 'Resumo_Receitas'
                }
                
                for key, value in type_map.items():
                    if key in report_type:
                        report_type_clean = value
                        break
            
            suggested_filename = f"{report_type_clean}_{clean_period}_IBSCO.pdf"
        else:
            # Ensure .pdf extension
            if not suggested_filename.lower().endswith('.pdf'):
                suggested_filename += '.pdf'
        
        # Clean and validate suggested directory
        if pd.isna(suggested_directory) or suggested_directory.strip() == "":
            # Generate directory from report type
            if 'DRE' in report_type:
                suggested_directory = "Financeiro/DRE/"
            elif 'Mapa' in report_type and 'Transformação' in report_type:
                suggested_directory = "Producao/Mapas_Transformacao/"
            elif 'Mapa' in report_type:
                suggested_directory = "Producao/Mapas_de_Producao/"
            elif 'Custo' in report_type:
                suggested_directory = "Financeiro/Custos_Operacionais/"
            elif 'Posição' in report_type and 'Estoque' in report_type:
                suggested_directory = "Financeiro/Estoque/Posicao_Financeira/"
            elif 'Balancete' in report_type:
                suggested_directory = "Financeiro/Balancetes/"
            elif 'Extrato' in report_type:
                suggested_directory = "Contabilidade/Extratos/"
            elif 'Resultado' in report_type and 'Bruto' in report_type:
                suggested_directory = "Financeiro/Resultados_Brutos/"
            elif 'Compras' in report_type:
                suggested_directory = "Financeiro/Compras/Resumos/"
            elif 'Vendas' in report_type:
                suggested_directory = "Financeiro/Vendas/Resumos_Mensais/"
            else:
                suggested_directory = "Financeiro/Outros/"
        else:
            # Ensure directory ends with /
            if not suggested_directory.endswith('/'):
                suggested_directory += '/'
        
        # Create full new path
        new_path = os.path.join(suggested_directory, suggested_filename)
        
        # Create mapping entry
        mapping_entry = {
            "old_path": current_filepath,
            "old_filename": filename,
            "new_path": new_path,
            "new_filename": suggested_filename,
            "new_directory": suggested_directory,
            "report_type": report_type if isinstance(report_type, str) else "Unknown",
            "period": period if isinstance(period, str) else "Unknown",
            "reason": f"Standardization based on report type: {report_type}"
        }
        
        file_mapping.append(mapping_entry)
        
        # Show progress
        if (idx + 1) % 10 == 0:
            print(f"   Processed {idx + 1}/{len(metadata_df)} files")
    
    print(f"\n3. Generated mapping for {len(file_mapping)} files")
    
    # Create comprehensive renaming plan
    renaming_plan = {
        "generation_timestamp": datetime.now().isoformat(),
        "naming_convention": naming_convention.strip(),
        "directory_structure": directory_structure,
        "file_mapping": file_mapping,
        "summary": {
            "total_files": len(file_mapping),
            "unique_directories": len(set([m["new_directory"] for m in file_mapping])),
            "report_types": list(set([m["report_type"] for m in file_mapping]))
        }
    }
    
    # Save renaming plan
    renaming_plan_path = os.path.join(workspace_dir, "renaming_plan_from_csv.json")
    with open(renaming_plan_path, 'w', encoding='utf-8') as f:
        json.dump(renaming_plan, f, ensure_ascii=False, indent=2)
    
    print(f"\n4. Renaming plan saved to: {renaming_plan_path}")
    
    # Create preview
    print("\n5. Preview of renaming plan (first 10 files):")
    print("-" * 80)
    
    for i, mapping in enumerate(file_mapping[:10]):
        print(f"\nFile {i+1}:")
        print(f"  Old: {mapping['old_filename']}")
        print(f"  New: {mapping['new_filename']}")
        print(f"  Dir: {mapping['new_directory']}")
        print(f"  Type: {mapping['report_type']}")
    
    print("\n" + "=" * 80)
    print("RENAMING PLAN GENERATION COMPLETED")
    print("=" * 80)
    
    # Create human-readable summary
    human_summary = f"""
    RENAMING PLAN - GENERATED FROM CSV METADATA
    ============================================
    
    Generated: {renaming_plan['generation_timestamp']}
    
    SUMMARY:
    - Total files to rename: {renaming_plan['summary']['total_files']}
    - Unique directories: {renaming_plan['summary']['unique_directories']}
    - Report types: {len(renaming_plan['summary']['report_types'])}
    
    DIRECTORY STRUCTURE:
    """
    
    for directory in directory_structure:
        human_summary += f"\n  {directory}"
    
    human_summary += f"""
    
    NAMING CONVENTION:
    {naming_convention}
    
    FULL PLAN:
    Saved to: {renaming_plan_path}
    
    Next steps:
    1. Review the renaming plan in the JSON file
    2. Apply renaming using apply_renaming_plan.py
    3. Backup original files before applying changes
    """
    
    human_summary_path = os.path.join(workspace_dir, "RENAMING_PLAN_SUMMARY.txt")
    with open(human_summary_path, 'w', encoding='utf-8') as f:
        f.write(human_summary)
    
    print(f"Human-readable summary: {human_summary_path}")
    
    return renaming_plan

if __name__ == "__main__":
    generate_renaming_plan_from_csv()