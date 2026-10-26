from urllib.parse import quote


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    """The header `FileResponse(filename=...)` sends: plain for ASCII-safe names, RFC 5987 otherwise."""
    quoted = quote(filename)
    if quoted != filename:
        return f"{disposition}; filename*=utf-8''{quoted}"
    return f'{disposition}; filename="{filename}"'
