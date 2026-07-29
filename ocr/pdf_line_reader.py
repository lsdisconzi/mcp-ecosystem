import re
import pandas as pd

def parse_report(text):
    lines = text.splitlines()
    records = []
    current_class = None
    current_record = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Class header
        if line.startswith('Classe:'):
            # Finalize any pending record
            if current_record:
                records.append(current_record)
                current_record = None
            # Extract class name (e.g., "MATERIAIS DE CONSTRUCAO")
            match = re.search(r'Classe:\s+\d+\s+-\s+\d+\s+(.*?)\s+Tipo:', line)
            if match:
                current_class = match.group(1).strip()
            else:
                # fallback
                current_class = line.split('-')[-1].split('Tipo')[0].strip()
            i += 1
            continue

        # Total line – ignore, but finalize record if any
        if line.startswith('Total da classe'):
            if current_record:
                records.append(current_record)
                current_record = None
            i += 1
            continue

        # Data header line – skip
        if line.startswith('Data docto'):
            i += 1
            continue

        # Transaction start: line begins with a date
        if re.match(r'^\d{2}/\d{2}/\d{4}', line):
            if current_record:
                records.append(current_record)
                current_record = None

            # Extract date, bank, account
            date = line[:10]
            parts = line[10:].split()
            if len(parts) < 2:
                i += 1
                continue
            bank = parts[0]
            account = parts[1]
            rest = ' '.join(parts[2:])   # everything after account

            # Extract value at the end (format: " - 1.234,56" or " 1.234,56")
            value = None
            # Try to find a numeric value at the end
            value_match = re.search(r'([-\s]*([\d\.]+,\d{2}))\s*$', rest)
            if value_match:
                value_str = value_match.group(1).strip()
                # Remove leading dash and spaces
                value_str = value_str.lstrip('-').strip()
                # Convert to float (Brazilian format: . as thousand separator, , as decimal)
                value = float(value_str.replace('.', '').replace(',', '.'))
                # Remove the value from rest to get document + possible description
                rest = rest[:value_match.start()].strip()
            else:
                # fallback: maybe no value on this line? should not happen
                value = 0.0

            # The document is the first part until a dash (if any) or the whole rest
            # We'll store the whole rest as document; historical description will come from following lines
            # But we might want to separate document from description later.
            document = rest.strip()
            # Clean up: remove trailing dash if present
            if document.endswith('-'):
                document = document[:-1].strip()

            # Initialize current record
            current_record = {
                'Data': date,
                'Banco': bank,
                'Conta': account,
                'Documento': document,
                'Historico': '',          # will be filled with following lines
                'Valor': value,
                'Classe': current_class
            }

            # Check if next line is a continuation (does not start with a date)
            # We'll read continuation lines until we hit a new date or class
            j = i + 1
            desc_lines = []
            while j < n:
                next_line = lines[j].strip()
                if not next_line:
                    j += 1
                    continue
                if re.match(r'^\d{2}/\d{2}/\d{4}', next_line) or next_line.startswith('Classe:') or next_line.startswith('Total da classe'):
                    break
                # Otherwise it's a continuation of the description
                desc_lines.append(next_line)
                j += 1
            # Join description lines with a space
            current_record['Historico'] = ' '.join(desc_lines).strip()
            i = j
            continue

        # Any other line: if we are inside a record, treat as continuation (should be caught above)
        # but just in case:
        if current_record:
            # This shouldn't happen because we handle continuation in the previous block,
            # but we add a safety net.
            current_record['Historico'] += ' ' + line.strip()
            i += 1
        else:
            i += 1

    # Finalize last record
    if current_record:
        records.append(current_record)

    return pd.DataFrame(records)

# Read the report text (replace this with the actual text you provided)
# For this example, we'll read from a file named 'report.txt'
# You can also paste the entire text directly as a string.
with open('report.txt', 'r', encoding='utf-8') as f:
    report_text = f.read()

df = parse_report(report_text)

# Save to Excel
df.to_excel('output.xlsx', index=False)
print(f"Saved {len(df)} transactions to output.xlsx")