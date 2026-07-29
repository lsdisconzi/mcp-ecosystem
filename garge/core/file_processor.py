import os
import json
import logging

logger = logging.getLogger(__name__)

class FileProcessor:
    def extract_text(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".pdf":
                from pypdf import PdfReader
                with open(path, "rb") as f:
                    reader = PdfReader(f)
                    return "\n".join([page.extract_text() or "" for page in reader.pages])
            elif ext in [".txt", ".md"]:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            elif ext == ".json":
                with open(path, "r", encoding="utf-8") as f:
                    return json.dumps(json.load(f), indent=2)
            else:
                return "[Unsupported file type]"
        except Exception as e:
            logger.error(f"Error extracting text from {path}: {e}")
            return f"[Error extracting text: {e}]"

    def extract_text_from_base64(self, base64_data, content_type):
        import base64, io
        if content_type == "application/pdf":
            from pypdf import PdfReader
            decoded = base64.b64decode(base64_data)
            with io.BytesIO(decoded) as pdf_file:
                reader = PdfReader(pdf_file)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                return text
        else:
            # Assume text file
            decoded = base64.b64decode(base64_data)
            return decoded.decode("utf-8", errors="ignore")