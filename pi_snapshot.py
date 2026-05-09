import json
from urllib.error import URLError
from urllib.request import Request, urlopen


def capture_snapshot(status_url="", stream_url="", timeout=2.0):
    if status_url:
        base = status_url.rsplit("/", 1)[0]
    elif stream_url:
        base = stream_url.rsplit("/", 1)[0]
    else:
        raise ValueError("No Pi stream/status URL is available.")

    request = Request(f"{base}/capture", method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Snapshot capture failed: {exc}") from exc
