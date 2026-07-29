## Instruções para adicionar upload de PDF com processamento na seção "Administração do Sistema"

O objetivo é permitir que o administrador faça upload de um PDF (como o exemplo `TJPR-jurisprudence-2.pdf (http://34.59.14.129:3229/api/projects/olivia-internal-dev-fixing/raw?path=case_files%2FTJPR-jurisprudence-2.pdf)`, que contém múltiplos julgamentos) e, após o upload, acione um pipeline que:
1. Extrai cada caso individual do PDF.
2. Gera um JSON estruturado para cada caso.
3. Ingesta cada documento no Qdrant.

---

### 1. Onde adicionar o componente no frontend

Localize o componente que renderiza a seção **"Administração do Sistema"**. Em geral, pode estar em:

- `disconzi1986_gmail_com/juris-search-VPS/tjrs-frontend/src/AdminView.jsx`

Adicione um novo card ou seção chamada **"Upload de Documentos (PDF)"**.

---

### 2. Componente de upload (React + TypeScript)

Exemplo de componente funcional:

```tsx
import React, { useState } from 'react';
import { Button, Card, FileInput, ProgressBar, Alert } from '...'; // lib UI

export const UploadPdfSection = () => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [status, setStatus] = useState<{ message: string; type: 'info' | 'success' | 'error' } | null>(null);
  const [extractedCount, setExtractedCount] = useState<number | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setStatus(null);
      setExtractedCount(null);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setStatus({ message: 'Enviando arquivo...', type: 'info' });

    const formData = new FormData();
    formData.append('pdf', file);

    try {
      const res = await fetch('/api/upload-pdf', { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok) {
        setStatus({ message: `Arquivo enviado: ${data.filename}`, type: 'success' });
        // Salva o ID ou caminho do arquivo para o processamento posterior
        setFileId(data.fileId); // você pode armazenar em state
      } else {
        setStatus({ message: data.error || 'Erro no upload', type: 'error' });
      }
    } catch (err) {
      setStatus({ message: 'Erro de rede', type: 'error' });
    } finally {
      setUploading(false);
    }
  };

  const handleProcess = async () => {
    if (!fileId) return;
    setProcessing(true);
    setStatus({ message: 'Processando PDF...', type: 'info' });

    try {
      const res = await fetch('/api/process-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fileId }),
      });
      const data = await res.json();
      if (res.ok) {
        setExtractedCount(data.casesExtracted);
        setStatus({
          message: `Processado com sucesso! ${data.casesExtracted} casos extraídos e ingeridos.`,
          type: 'success'
        });
      } else {
        setStatus({ message: data.error || 'Erro no processamento', type: 'error' });
      }
    } catch (err) {
      setStatus({ message: 'Erro de rede', type: 'error' });
    } finally {
      setProcessing(false);
    }
  };

  return (
    <Card>
      <h3>Upload de PDF para processamento</h3>
      <p>Selecione um arquivo PDF contendo julgamentos (suporta múltiplos casos no mesmo PDF).</p>

      <FileInput accept=".pdf" onChange={handleFileChange} disabled={uploading || processing} />

      {file && (
        <div style={{ marginTop: '1rem' }}>
          <span>Arquivo: {file.name} ({(file.size / 1024).toFixed(1)} KB)</span>
          <Button onClick={handleUpload} disabled={uploading || processing}>
            {uploading ? 'Enviando...' : 'Upload'}
          </Button>
        </div>
      )}

      {status && (
        <Alert variant={status.type} style={{ marginTop: '1rem' }}>
          {status.message}
        </Alert>
      )}

      {fileId && !processing && status?.type === 'success' && (
        <div style={{ marginTop: '1rem' }}>
          <Button onClick={handleProcess} disabled={processing}>
            Processar
          </Button>
        </div>
      )}

      {processing && <ProgressBar label="Processando..." />}

      {extractedCount !== null && (
        <div style={{ marginTop: '1rem' }}>
          <strong>Casos extraídos e ingeridos: {extractedCount}</strong>
        </div>
      )}
    </Card>
  );
};
```

---

### 3. Endpoints no backend (Python – FastAPI/Flask)

Crie dois endpoints:

#### 3.1. Upload do PDF

**POST `/api/upload-pdf`**

Recebe o arquivo, salva em um diretório temporário (ex: `uploads/`) e retorna um `fileId` (pode ser o nome do arquivo ou um UUID).

Exemplo (FastAPI):

```python
from fastapi import UploadFile, File, HTTPException
import shutil
import uuid
import os

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/api/upload-pdf")
async def upload_pdf(pdf: UploadFile = File(...)):
    if not pdf.filename.endswith(".pdf"):
        raise HTTPException(400, "Somente arquivos PDF são permitidos")
    file_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}.pdf")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(pdf.file, buffer)
    return {"fileId": file_id, "filename": pdf.filename}
```

#### 3.2. Processamento do PDF

**POST `/api/process-pdf`**

Recebe o `fileId`, executa a pipeline de extração e ingestão, e retorna o número de casos processados.

```python
from court_extractor import process_file, _load_master_lookup, ingest_extracted_to_qdrant

@app.post("/api/process-pdf")
async def process_pdf(payload: dict):
    file_id = payload.get("fileId")
    if not file_id:
        raise HTTPException(400, "fileId é obrigatório")
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}.pdf")
    if not os.path.exists(file_path):
        raise HTTPException(404, "Arquivo não encontrado")

    # 1. Extrair todos os casos (TJPR ou outro tribunal)
    master_lookup = _load_master_lookup()  # se necessário
    results = process_file(file_path, "TJPR", master_lookup)  # ou detectar tribunal automaticamente
    if not results:
        raise HTTPException(500, "Nenhum caso extraído do PDF")

    # 2. Ingestar cada resultado no Qdrant
    count = 0
    for doc in results:
        # Cada doc é um dict com os campos extraídos
        ingest_result = ingest_extracted_to_qdrant(doc)
        if ingest_result.get("ok"):
            count += 1

    # Opcional: limpar arquivo temporário após processamento
    # os.remove(file_path)

    return {"casesExtracted": count, "status": "success"}
```

---

### 4. Observações importantes

- **TJPR multi‑caso**: O `process_file` já foi atualizado para retornar uma lista de dicionários quando o PDF contém múltiplos julgamentos (identificados por "Processo:"). Certifique-se de que a função `_process_tjpr_multiple` está presente e que `TJPRExtractor` está registrado em `EXTRACTORS`.

- **Tempo de processamento**: Para PDFs grandes, a extração pode demorar. Considere usar processamento assíncrono com filas (Celery/RQ) e polling de status, ou WebSocket para atualizações em tempo real. Por simplicidade, a solução acima bloqueia a requisição, mas você pode implementar um endpoint de status separado.

- **Segurança**: Restringir acesso a essa funcionalidade para administradores autenticados (por exemplo, usando middleware JWT ou session).

- **Validação**: O backend deve verificar se o tribunal é suportado (TJPR, TJSP, etc.) ou tentar detectar automaticamente pela estrutura do texto.

- **Inserção no Qdrant**: Certifique-se de que `ingest_extracted_to_qdrant` está disponível e configurada com a API correta.

---

### 5. Sugestão de fluxo alternativo (async)

Se preferir não bloquear a requisição:

1. **Upload** → retorna `fileId` imediatamente.
2. **Processamento** → dispara uma tarefa em background e retorna `taskId`.
3. **Status** → endpoint `/api/process-status/{taskId}` para acompanhar o progresso.
4. **Frontend** → exibe barra de progresso e, ao final, mostra o resultado.

Exemplo de estrutura de resposta:

```json
{
  "taskId": "abc123",
  "status": "processing",
  "progress": 0.5,
  "casesExtracted": null
}
```

---

### 6. Como integrar ao frontend existente

- Adicione o componente `UploadPdfSection` no local apropriado (ex: dentro do `<AdminPanel />`).
- Utilize o mesmo estilo e sistema de notificações do restante da aplicação.
- Garanta que a API base (ex: `/api`) esteja configurada no proxy do frontend.

---

Com essas instruções, o agente poderá implementar a funcionalidade completa, aproveitando o pipeline de extração já existente e adaptado para PDFs com múltiplos casos.