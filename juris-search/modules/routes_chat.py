"""Chat and file upload endpoints for juris-search."""

from fastapi import APIRouter, UploadFile, File, Form

from modules.config import DEFAULT_COURT
from modules.models import ChatRequest
from modules.courts import _resolve_court, COURT_NAMES
from modules.deepseek_client import chat_with_deepseek
from modules.file_extraction import process_uploaded_file

router = APIRouter()


# from modules.gemini_client import chat_with_tuned_gemini

@router.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    if (req.provider and "gemini" in req.provider.lower()) or (req.model and "gemini" in req.model.lower()):
        reply = await chat_with_tuned_gemini(
            user_message=req.message,
            conversation=req.conversation,
            file_text=req.file_text,
            file_name=req.file_name,
            court=req.court,
        )
    else:
        reply = await chat_with_deepseek(
            user_message=req.message,
            conversation=req.conversation,
            file_text=req.file_text,
            file_name=req.file_name,
            model=req.model,
            court=req.court,
        )
    return {"reply": reply}


@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...), court: str = Form("TJRS")):
    content = await file.read()
    result = process_uploaded_file(file.filename, content)
    court_key = _resolve_court(court)
    court_name = COURT_NAMES.get(court_key, COURT_NAMES["TJRS"])

    if result.get("image_b64"):
        reply = await chat_with_deepseek(
            user_message=f"Analise esta imagem e sugira campos de busca para jurisprudência no {court_name}.",
            image_b64=result["image_b64"],
            file_name=file.filename,
            court=court_key,
        )
    elif result.get("text"):
        reply = await chat_with_deepseek(
            user_message=f"Analise este documento e sugira campos de busca para jurisprudência no {court_name}.",
            file_text=result["text"],
            file_name=file.filename,
            court=court_key,
        )
    else:
        reply = "Não foi possível extrair conteúdo deste arquivo."

    return {
        "filename": file.filename,
        "extracted_text_preview": (result.get("text") or "")[:500],
        "reply": reply,
    }
