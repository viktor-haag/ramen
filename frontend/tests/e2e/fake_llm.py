"""Tiny OpenAI-compatible server for the end-to-end tests (stdlib only).

Usage: python fake_llm.py <port>

GET  /v1/models            -> one fake model
POST /v1/chat/completions  -> a canned transcription when the request contains an image part,
                              a canned fit rating when the system prompt carries the fit instructions,
                              a canned cover letter (document, <<<RAMEN-NOTE>>>, note) streamed as SSE when it carries the cover letter instructions,
                              otherwise a canned profile with all eight headings.
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "fake-model"
TRANSCRIPTION = "Jane Doe - Python developer, 5 years"
FIT = json.dumps({"rating": "good", "explanation": "Strong Python match."})
# Distinctive phrase of the fit system prompt (backend/app/services/fit.py).
FIT_MARKER = "You judge how well a job posting fits a job seeker"
# Distinctive phrase of the cover letter system prompt (backend/app/services/prompts.py).
COVER_MARKER = "You write a cover letter"
OPENING = "Opening paragraph: the position and why you are writing."
LATEX_LETTER = (
    "\\documentclass[11pt]{article}\n"
    "\\usepackage[a4paper,margin=2.5cm]{geometry}\n"
    "\\begin{document}\n"
    "Dear Hiring Team,\n\n" + OPENING + "\n\n"
    "Main paragraph: what you bring, backed by evidence.\n\n"
    "Sincerely,\n\nJane Doe\n"
    "\\end{document}\n"
)
TEXT_LETTER = (
    "Dear Hiring Team,\n\n" + OPENING + "\n\n"
    "Main paragraph: what you bring, backed by evidence.\n\n"
    "Sincerely,\nJane Doe\n"
)
NOTE_SEPARATOR = "\n<<<RAMEN-NOTE>>>\n"
CHUNKS = 10
CHUNK_DELAY = 0.15
PROFILE = """## Summary
Jane Doe is a Python developer with five years of experience.

## Strengths
- Solid Python track record

## Core skills
- Python
- FastAPI

## Experience
- Python developer, 5 years

## Education
- None stated

## Languages
- English

## Constraints
None stated

## Gaps
- Little frontend experience
"""


def has_image(body: dict) -> bool:
    for message in body.get("messages", []):
        content = message.get("content")
        if isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            return True
    return False


def is_fit(body: dict) -> bool:
    for message in body.get("messages", []):
        if message.get("role") in ("system", "developer") and FIT_MARKER in str(message.get("content")):
            return True
    return False


def role_text(body: dict, *roles: str) -> str:
    return " ".join(str(m.get("content")) for m in body.get("messages", []) if m.get("role") in roles)


def cover_letter(body: dict) -> str:
    """Generate: the default letter (LaTeX or plain text, by the system prompt); revise: one paragraph replaced.

    Returns the streamed answer: document, the note separator, then the note."""
    document = TEXT_LETTER if "plain text" in role_text(body, "system", "developer") else LATEX_LETTER
    user = role_text(body, "user")
    if "Change the letter as follows:" in user:
        m = re.search(r"<current>\n(.*?)\n</current>", user, re.DOTALL)
        document = (m.group(1) if m else document).replace(OPENING, "Revised opening paragraph.")
        return document + NOTE_SEPARATOR + "Updated."
    return document + NOTE_SEPARATOR + "Draft ready."


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream(self, model: str, text: str) -> None:
        """OpenAI chat completions SSE: ~CHUNKS content pieces, a usage chunk, then [DONE]."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(choices: list, usage: dict | None = None) -> None:
            chunk = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": model, "choices": choices}
            if usage:
                chunk["usage"] = usage
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        size = max(1, -(-len(text) // CHUNKS))
        for i in range(0, len(text), size):
            emit([{"index": 0, "delta": {"content": text[i:i + size]}, "finish_reason": None}])
            time.sleep(CHUNK_DELAY)
        emit([], {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "fake"}]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._send(404, {"error": {"message": "not found"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": {"message": "invalid json"}})
            return
        if COVER_MARKER in role_text(body, "system", "developer"):
            text = cover_letter(body)
            if body.get("stream"):
                self._stream(body.get("model", MODEL), text)
                return
        else:
            text = FIT if is_fit(body) else TRANSCRIPTION if has_image(body) else PROFILE
        self._send(200, {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", MODEL),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        })

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
