import json
from urllib.error import URLError
from urllib.request import Request, urlopen


def _base_url(status_url="", stream_url=""):
    if status_url:
        return status_url.rsplit("/", 1)[0]
    if stream_url:
        return stream_url.rsplit("/", 1)[0]
    raise ValueError("No Pi stream/status URL is available.")


def _post(path, status_url="", stream_url="", timeout=2.0):
    request = Request(f"{_base_url(status_url, stream_url)}{path}", method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Pi record command failed: {exc}") from exc


def start_pi_recording(status_url="", stream_url="", timeout=2.0):
    return _post("/record/start", status_url=status_url, stream_url=stream_url, timeout=timeout)


def stop_pi_recording(status_url="", stream_url="", timeout=2.0):
    return _post("/record/stop", status_url=status_url, stream_url=stream_url, timeout=timeout)
