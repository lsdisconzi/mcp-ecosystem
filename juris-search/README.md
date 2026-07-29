# Juris Search — Assistente de Pesquisa de Jurisprudência Multi-Tribunal

Aplicação web com assistente inteligente (DeepSeek) para busca de jurisprudência nos tribunais brasileiros: **TJRS**, **TJSP** e **STF**.

## Arquitetura

```
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│  React Frontend      │────▶│  FastAPI Backend      │────▶│  TJRS Website    │
│  (Chat + Form +      │◀────│  (main.py +           │◀────│  (Selenium)      │
│   Court Selector)    │     │   modules/)           │     └──────────────────┘
│   Court Selector)    │     └──────┬───────────────┘     └──────────────────┘
└──────────────────────┘            │                      ┌──────────────────┐
                                    │                      │  TJSP Website    │
                                    ├─────────────────────▶│  (e-SAJ CJSG,    │
                                    │                      │   Selenium)      │
                                    │                      └──────────────────┘
                                    │                      ┌──────────────────┐
                                    ├─────────────────────▶│  STF Website     │
                                    │                      │  (HTTP +         │
                                    │                      │   Selenium fallb)│
                                    │                      └──────────────────┘
                             ┌──────▼───────┐
                             │  DeepSeek API  │
                             │  (deepseek-v4-pro / deepseek-v4-flash) │
                             └──────────────┘
```

Cada tribunal tem seu próprio módulo scraper com a mesma interface, carregado dinamicamente por factory dispatch.

## Setup

### 1. Backend (Python)

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar chave DeepSeek
export DEEPSEEK_API_KEY="sk-..."

# Rodar o backend
python main.py
# → Servidor em http://localhost:8000
```

### 2. Frontend (React)

```bash
cd tjrs-frontend
npm install
npm run build
# Servido estaticamente pelo backend em http://localhost:8000
```

### 3. Variáveis de Ambiente

| Variável | Descrição |
|----------|-----------|
| `DEEPSEEK_API_KEY` | Chave da API DeepSeek (obrigatória para o assistente) |
| `DEEPSEEK_MODEL` | Modelo padrão do assistente (`deepseek-v4-pro` ou `deepseek-v4-flash`) |
| `DEEPSEEK_BASE_URL` | Base URL da API DeepSeek (default `https://api.deepseek.com`) |
| `JURIS_SEARCH_DEFAULT_COURT` | Tribunal padrão: `TJRS`, `TJSP` ou `STF` (default `TJRS`) |
| `JURIS_SEARCH_DOWNLOAD_DIR` | Diretório base dos downloads brutos (`jurisprudence_downloads`) |
| `JURIS_SEARCH_HISTORY_DIR` | Diretório dos históricos de busca (`searches_history`) |
| `JURIS_SEARCH_DOCX_DIR` | Diretório de saída DOCX (`docx_jurisprudence`) |
| `JURIS_SEARCH_JSON_DIR` | Diretório de saída JSON estruturado (`json_jurisprudence`) |
| `JURIS_SEARCH_SHARED_LINK_ROOT` | Root para symlinks de publicação compartilhada |
| `JURIS_SEARCH_AGENTS_LINK_ROOT` | Root para symlinks de publicação para agents |
| `JURIS_SEARCH_EXPORT_LINKS` | Habilita/desabilita sincronização de links (`true/false`) |

## Fluxo de Uso

1. **Tribunal**: Selecione o tribunal (TJRS, TJSP, STF) no cabeçalho
2. **Chat**: Descreva o que procura ou envie um documento (PDF, Word, imagem)
3. **Assistente**: O DeepSeek V4 analisa e sugere campos de busca específicos para o tribunal selecionado
4. **Editar**: Revise e ajuste qualquer campo no painel direito
5. **Buscar**: Clique "Executar Busca" — o scraper do tribunal roda em background
6. **Resultados**: Veja os resultados com links para inteiro teor

## Persistência Local e Exportação

- Histórico de busca: salvo em `searches_history/` (JSON por job)
- Downloads brutos: salvos em `jurisprudence_downloads/`
- Conversão DOCX: materializada em `docx_jurisprudence/`
- Extração estruturada JSON: materializada em `json_jurisprudence/`
- Exposição por symlink para consumo global: habilitável por variáveis de ambiente

O frontend principal (`tjrs-frontend/src/App.jsx`) já consome endpoints para:
- verificar histórico persistido,
- visualizar paths de storage,
- acompanhar status de download e sincronização (`docx` + `json`).

## Python Capability Policy (Lightweight)

- Versão recomendada: Python `3.10` a `3.12`.
- Gerenciador de pacotes: usar `pip` atualizado (`python -m pip install --upgrade pip`).
- Estratégia de instalação: preferir wheels pré-compiladas (`--only-binary=:all:` quando possível) para reduzir falhas de build local.
- Dependências opcionais:
       - `LibreOffice` é usado para conversão de `.doc` para `.docx` quando necessário.
       - Recursos que dependem de binários externos devem degradar com warning, sem derrubar a API principal.
- Ambientes de produção: fixar versões em `requirements.txt` e evitar upgrades sem validação de scraping e parsing.

## Arquivos

- `main.py` — Backend FastAPI multi-tribunal (chat, upload, search, download) com factory dispatch; `modules/` contains the route and service modules
- `tjrs_scraper.py` — Scraper TJRS (Selenium, AngularJS-based search, DOC/DOCX/PDF)
- `tjsp_scraper.py` — Scraper TJSP (Selenium, POST-based e-SAJ CJSG, reCAPTCHA v3 + image captcha)
- `stf_scraper.py` — Scraper STF (HTTP requests + Selenium fallback, ICP-Brasil SSL)
- `tjrs-frontend/src/App.jsx` — Frontend React ativo (chat + formulário + seletor de tribunal + resultados + downloads)
- `_shared/chrome_driver.py` — Inicialização compartilhada do Chrome WebDriver para todos os scrapers
- `test_integration.py` — Testes de integração multi-tribunal (92 verificações)
- `requirements.txt` — Dependências Python
- `start.sh` — Script de bootstrap do servidor

## Endpoints da API

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/chat` | Conversar com o assistente |
| POST | `/api/upload` | Upload de arquivo + análise |
| POST | `/api/search` | Iniciar busca (retorna job_id) |
| GET | `/api/search/status/{id}` | Status da busca |
| GET | `/api/results/{id}` | Resultados da busca |
| GET | `/api/search/history` | Lista históricos persistidos |
| GET | `/api/search/history/{filename}` | Lê um histórico específico |
| POST | `/api/download` | Download de inteiro teor |
| GET | `/api/download/status/{id}` | Status do job de download |
| GET | `/api/storage/paths` | Paths locais e roots de link |
| GET | `/api/docx/index` | Índice DOCX |
| POST | `/api/docx/rebuild` | Rebuild DOCX |
| GET | `/api/json/index` | Índice JSON |
| POST | `/api/json/rebuild` | Rebuild JSON |
| POST | `/api/storage/rebuild` | Rebuild DOCX+JSON + sync de links |
| GET | `/api/stats` | Estatísticas de storage/histórico/conversão |
| GET | `/api/health` | Health check |

## Git Guidance

Do not commit generated index or watch-state files (they are ignored by `.gitignore`). If you accidentally track them, remove with:

```
git rm --cached path/to/generated_file
git commit -m "chore: remove generated files from repo"
```
