import os
import re
import pandas as pd
import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from datetime import datetime

class ReportConverter:
    def __init__(self, input_pdf, output_xlsx):
        self.input_pdf = input_pdf
        self.output_xlsx = output_xlsx
        self.headers = []
        self.records = []
        self.report_type = self._detect_report_type()

    def _detect_report_type(self):
        filename = os.path.basename(self.input_pdf).upper()
        if "POS_PAG" in filename:
            return "POSICAO_PAGAMENTOS"
        elif "COB_EFET" in filename:
            return "COBRANCAS_EFETUADAS"
        elif "POS_CONT" in filename:
            return "POSICAO_CONTABIL"
        return "UNKNOWN"

    def parse(self):
        print(f"Parsing {self.input_pdf} as {self.report_type}...")
        with pdfplumber.open(self.input_pdf) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                
                lines = text.splitlines()
                if self.report_type == "POSICAO_PAGAMENTOS":
                    self._parse_pos_pag(lines)
                elif self.report_type == "COBRANCAS_EFETUADAS":
                    self._parse_cob_efet(lines)
                elif self.report_type == "POSICAO_CONTABIL":
                    self._parse_pos_cont(lines)
                else:
                    print(f"Unknown report type for {self.input_pdf}")
                    return False
        return True

    def _parse_pos_pag(self, lines):
        # Header: Data vencto Código Razão social Documento Data emissão Valor docto Moeda Classe Tipo
        self.headers = ['Data vencto', 'Código', 'Razão social', 'Documento', 'Data emissão', 'Valor docto', 'Moeda', 'Classe', 'Tipo']
        
        current_date = None
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Detect Date Header for groups
            date_header_match = re.match(r'^(\d{2}/\d{2}/\d{4})', line)
            if date_header_match and "Total geral" not in line:
                # This could be a record or a date header
                # In POS_PAG, records start with a date but might be followed by "Total geral do dia"
                if "Total geral do dia" in line:
                    continue
                
                # Check if it has enough parts to be a record
                parts = line.split()
                if len(parts) >= 6:
                    # Example: 02/01/2026 591GOBAUTO SOLUCOES AUTOMOTIVAS LTDA067126...
                    # This format is tricky because fields are stuck together
                    # We'll use a more heuristic approach or regex if possible
                    date_venc = parts[0]
                    # The rest is harder to split without fixed widths or smarter logic
                    # For now, let's try to extract the value and currency which are usually at the end
                    value_match = re.search(r'(\d[\d\.,]*)\s+(R\$|USD|EUR)', line)
                    if value_match:
                        valor = value_match.group(1)
                        moeda = value_match.group(2)
                        
                        # Extract what's between date and value
                        mid_section = line[len(date_venc):value_match.start()].strip()
                        # Extract Type and Class which are after Currency
                        end_section = line[value_match.end():].strip()
                        
                        self.records.append({
                            'Data vencto': date_venc,
                            'Content': mid_section, # Temporary placeholder
                            'Valor docto': valor,
                            'Moeda': moeda,
                            'Classe/Tipo': end_section
                        })

    def _parse_cob_efet(self, lines):
        # Header: Data Digitação Código Razão social Documento Data emissão Data vencto Valor documento Tipo Data pagto Valor pagamento Valor desconto Valor acréscimo
        self.headers = ['Classe', 'Data Digitação', 'Código', 'Razão social', 'Documento', 'Data emissão', 'Data vencto', 'Valor documento', 'Tipo', 'Data pagto', 'Valor pagamento', 'Valor desconto', 'Valor acréscimo']
        
        current_classe = ""
        for line in lines:
            line = line.strip()
            if not line: continue
            
            if line.startswith("Classe:"):
                current_classe = line.replace("Classe:", "").strip()
                continue
            
            if line.startswith("Total da classe") or "Data Digitação" in line or "Emitido em" in line:
                continue

            # Check if starts with date
            if re.match(r'^\d{2}/\d{2}/\d{4}', line):
                parts = line.split()
                if len(parts) >= 8:
                    # Try to map parts - this is still heuristic
                    self.records.append({
                        'Classe': current_classe,
                        'Data Digitação': parts[0],
                        'Rest': " ".join(parts[1:])
                    })

    def _parse_pos_cont(self, lines):
        # Header: Data docto Banco Conta Documento Histórico Valor a debito
        # Note: 'Classe' is usually in the header of the page or preceding line
        self.headers = ['Classe', 'Data docto', 'Banco', 'Conta', 'Documento', 'Histórico', 'Valor a debito']
        
        current_classe = ""
        for line in lines:
            line = line.strip()
            if not line: continue
            
            if "Classe:" in line:
                match = re.search(r'Classe:\s+(.*?)\s+Tipo:', line)
                if match:
                    current_classe = match.group(1).strip()
                continue
                
            if "Data docto" in line or "Emitido em" in line or "Total da classe" in line:
                continue
            
            if re.match(r'^\d{2}/\d{2}/\d{4}', line):
                parts = line.split()
                if len(parts) >= 4:
                    self.records.append({
                        'Classe': current_classe,
                        'Data docto': parts[0],
                        'Banco': parts[1],
                        'Conta': parts[2],
                        'Documento': parts[3],
                        'Rest': " ".join(parts[4:])
                    })
            elif self.records and current_classe:
                # Continuation of Histórico
                self.records[-1]['Rest'] = self.records[-1].get('Rest', '') + " " + line

    def save(self):
        if not self.records:
            print(f"No records found for {self.input_pdf}")
            return
        
        df = pd.DataFrame(self.records)
        df.to_excel(self.output_xlsx, index=False)
        print(f"Saved {len(self.records)} records to {self.output_xlsx}")

def main():
    files_to_convert = [
        "IBSCO/Financeiro/Pagamentos/Posicao_Pagamentos/POS_PAG_2026Q1_IBSCO_20260331.pdf",
        "IBSCO/Financeiro/Pagamentos/Posicao_Pagamentos/POS_PAG_2025_IBSCO_20260331.pdf",
        "IBSCO/Financeiro/Contas_Receber/Cobrancas_Efetuadas/COB_EFET_2025Q1_2026_IBSCO_20260331.pdf",
        "IBSCO/Financeiro/Contabilidade/Posicao_Contabil/POS_CONT_2026Q1_IBSCO_20260331.pdf",
        "IBSCO/Financeiro/Contabilidade/Posicao_Contabil/POS_CONT_2025_IBSCO_20260331.pdf"
    ]
    
    for pdf_path in files_to_convert:
        if not os.path.exists(pdf_path):
            print(f"File not found: {pdf_path}")
            continue
            
        output_xlsx = pdf_path.replace(".pdf", ".xlsx")
        converter = ReportConverter(pdf_path, output_xlsx)
        if converter.parse():
            converter.save()

if __name__ == "__main__":
    main()
