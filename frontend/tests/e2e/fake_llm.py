"""Tiny OpenAI-compatible server for the end-to-end tests (stdlib only).

Usage: python fake_llm.py <port>

GET  /v1/models            -> one fake model
POST /v1/chat/completions  -> a canned transcription when the request contains an image part,
                              a canned fit rating when the system prompt carries the fit instructions,
                              otherwise a canned profile with all eight headings.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "fake-model"
TRANSCRIPTION = "Jane Doe - Python developer, 5 years"
FIT = json.dumps({"rating": "good", "explanation": "Strong Python match."})
# Distinctive phrase of the fit system prompt (backend/app/services/fit.py).
FIT_MARKER = "You judge how well a job posting fits a job seeker"
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


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
