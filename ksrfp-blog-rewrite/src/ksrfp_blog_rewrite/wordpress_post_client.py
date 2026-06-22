from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .wordpress_metrics_client import WordPressMetricsError, build_basic_auth_token


def fetch_wordpress_post(
    api_base: str,
    username: str,
    application_password: str,
    post_id: int,
) -> dict[str, Any]:
    token = build_basic_auth_token(username, application_password)
    params = urlencode(
        {
            "context": "edit",
            "_fields": "id,date,modified,slug,link,status,title,content,excerpt,categories,tags",
        }
    )
    request = Request(
        f"{api_base.rstrip('/')}/posts/{post_id}?{params}",
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise WordPressMetricsError(f"WordPress post endpoint returned HTTP {exc.code}: {body[:500]}") from exc
    except URLError as exc:
        raise WordPressMetricsError(f"WordPress post endpoint connection failed: {exc}") from exc
