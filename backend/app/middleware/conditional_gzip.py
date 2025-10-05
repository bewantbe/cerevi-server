from starlette.middleware.base import BaseHTTPMiddleware
import gzip
from starlette.responses import Response as StarletteResponse


class ConditionalGZipMiddleware(BaseHTTPMiddleware):
    """Middleware that gzips responses only when:
    - the client sends Accept-Encoding including gzip
    - the response Content-Type starts with 'text/plain'
    - the response is larger than minimum_size
    This keeps binary/image responses untouched while still allowing
    automatic compression for plain-text payloads (e.g. mesh text).
    """
    def __init__(self, app, minimum_size: int = 1024):
        super().__init__(app)
        self.minimum_size = minimum_size

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Do not re-compress if already encoded
        if response.headers.get('content-encoding'):
            return response

        accept_encoding = request.headers.get('accept-encoding', '')
        if 'gzip' not in accept_encoding.lower():
            return response

        content_type = response.headers.get('content-type', '').lower()
        # Compress text/* and JSON-like content types (application/json, vendor types, etc.)
        if not (content_type.startswith('text/') or 'json' in content_type):
            return response

        # Collect body bytes (handle both pre-rendered and iterator responses)
        body = b''
        if getattr(response, 'body', None) is not None:
            body = response.body
        else:
            try:
                async for chunk in response.body_iterator:
                    body += chunk
            except Exception:
                return response

        if len(body) < self.minimum_size:
            # Recreate response since body_iterator may have been consumed
            return StarletteResponse(content=body, status_code=response.status_code,
                                     headers=dict(response.headers), media_type=response.media_type)

        gzipped = gzip.compress(body)

        headers = dict(response.headers)
        headers.pop('content-length', None)
        headers['Content-Encoding'] = 'gzip'
        # Ensure Vary includes Accept-Encoding
        vary = headers.get('Vary', '')
        if 'accept-encoding' not in vary.lower():
            headers['Vary'] = (vary + ', Accept-Encoding').strip(', ')

        return StarletteResponse(content=gzipped, status_code=response.status_code,
                                 headers=headers, media_type=response.media_type)
