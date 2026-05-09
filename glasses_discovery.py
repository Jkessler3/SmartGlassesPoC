import ipaddress
import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class GlassesDevice:
    name: str
    host: str
    port: int
    stream_url: str
    status_url: str
    description: str


def _local_ipv4_addresses():
    addrs = set()
    hostname = socket.gethostname()
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addrs.add(info[4][0])
    except socket.gaierror:
        pass

    probe = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        addrs.add(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        try:
            if probe is not None:
                probe.close()
        except Exception:
            pass

    return sorted(addr for addr in addrs if not addr.startswith("127."))


def candidate_hosts():
    hosts = set()
    for addr in _local_ipv4_addresses():
        try:
            network = ipaddress.ip_network(f"{addr}/24", strict=False)
        except ValueError:
            continue
        for host in network.hosts():
            host_s = str(host)
            if host_s != addr:
                hosts.add(host_s)
    return sorted(hosts, key=lambda ip: tuple(int(part) for part in ip.split(".")))


def probe_glasses(host, port=8000, timeout=0.25):
    status_url = f"http://{host}:{port}/status.json"
    try:
        with urlopen(status_url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError, TimeoutError):
        return None

    if payload.get("service") != "smart-glasses-pi-stream":
        return None

    stream_path = payload.get("stream_path") or "/stream.mjpg"
    stream_url = f"http://{host}:{port}{stream_path}"
    name = payload.get("name") or payload.get("hostname") or host
    width = payload.get("width", "?")
    height = payload.get("height", "?")
    fps = payload.get("fps", "?")
    description = f"{name} ({host}) {width}x{height}@{fps}"
    return GlassesDevice(
        name=name,
        host=host,
        port=port,
        stream_url=stream_url,
        status_url=status_url,
        description=description,
    )


def discover_glasses(port=8000, timeout=0.25, workers=64):
    devices = []
    hosts = candidate_hosts()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(probe_glasses, host, port, timeout) for host in hosts]
        for future in as_completed(futures):
            try:
                device = future.result()
            except Exception:
                continue
            if device is not None:
                devices.append(device)
    return sorted(devices, key=lambda device: (device.name.lower(), device.host))
