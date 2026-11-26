#!/usr/bin/env python3
"""Read-only probe for Terneo local API and telemetry.

HTTP checks take the device address and serial through --host and --sn.
MQTT and broadcast modes need no device arguments. The probe never publishes
messages, never changes device parameters and never touches Home Assistant
configuration. Secrets are read from environment variables and are not printed.

Examples:
  python3 tools/probe_terneo.py --mode http --host <IP> --sn <SERIAL> --cmd 4
  python3 tools/probe_terneo.py --mode broadcast --seconds 10
  TERNEO_MQTT_HOST=<BROKER_IP> python3 tools/probe_terneo.py --mode mqtt
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.request

EPOCH_2000 = 946684800


def totp_9(secret_b32: str, when: float | None = None) -> str:
    """Return a 9-digit RFC6238 token for a Terneo base32 key."""
    secret = secret_b32.replace(" ", "").upper().encode("ascii")
    secret += b"=" * (-len(secret) % 8)
    key = base64.b32decode(secret)
    counter = int(((time.time() if when is None else when) - EPOCH_2000) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000_000:09d}"


def http_request(url: str, data: bytes | None = None, timeout: int = 7):
    """Return (status, body) for a GET or JSON POST."""
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


def http_probe(host: str, sn: str, cmd: int, totp_key: str | None) -> None:
    """Compare the integration's old payload with the auth-fields payload."""
    status, body = http_request(f"http://{host}/api.html")
    print(f"verify GET   http://{host}/api.html -> HTTP={status}")

    now = str(int(time.time()) - EPOCH_2000)
    auth = totp_9(totp_key) if totp_key else "000000000"
    variants = [
        ("legacy", {"cmd": cmd, "sn": sn}),
        ("auth", {"cmd": cmd, "sn": sn, "time": now, "auth": auth}),
    ]
    for index, (label, payload) in enumerate(variants):
        if index:
            time.sleep(1)  # the embedded API dislikes back-to-back requests
        # Terneo's parser is whitespace-sensitive; keep compact separators.
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        code, response = http_request(
            f"http://{host}/api.cgi", data=raw, timeout=7
        )
        print(f"{label:9} {raw.decode()} -> HTTP={code} {response[:260]}")


def enc_len(value: int) -> bytes:
    """Encode an MQTT remaining length."""
    out = bytearray()
    while True:
        byte = value % 128
        value //= 128
        if value:
            byte |= 0x80
        out.append(byte)
        if not value:
            return bytes(out)


def enc_str(value: str) -> bytes:
    """Encode an MQTT UTF-8 string."""
    raw = value.encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


def mqtt_packet(kind: int, flags: int, body: bytes) -> bytes:
    return bytes([(kind << 4) | flags]) + enc_len(len(body)) + body


def read_exact(sock: socket.socket, size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise EOFError("broker closed the connection")
        buf.extend(chunk)
    return bytes(buf)


def read_packet(sock: socket.socket):
    header = read_exact(sock, 1)[0]
    multiplier = 1
    remaining = 0
    while True:
        byte = read_exact(sock, 1)[0]
        remaining |= (byte & 0x7F) * multiplier
        if not byte & 0x80:
            break
        multiplier *= 128
    return header, read_exact(sock, remaining)


def mqtt_probe(args) -> None:
    """Subscribe only; print telemetry that arrives during the window."""
    host = os.environ.get("TERNEO_MQTT_HOST")
    if not host:
        print("mqtt: missing environment variable TERNEO_MQTT_HOST")
        print(
            "How to run: TERNEO_MQTT_HOST=<BROKER_IP> "
            "[TERNEO_MQTT_USER=<USER>] [TERNEO_MQTT_PASS=<PASSWORD>] "
            "python3 tools/probe_terneo.py --mode mqtt "
            "--mqtt-topic 'pub_terneo/+/get/#'"
        )
        return
    port = int(os.environ.get("TERNEO_MQTT_PORT", "1883"))
    user = os.environ.get("TERNEO_MQTT_USER", "")
    password = os.environ.get("TERNEO_MQTT_PASS", "")
    topic = args.mqtt_topic

    flags = 0x02  # clean session
    if user:
        flags |= 0x80
    if password:
        flags |= 0x40
    connect = (
        enc_str("MQTT")
        + bytes([4, flags])
        + struct.pack("!H", 60)
        + enc_str("terneo-probe")
        + (enc_str(user) if user else b"")
        + (enc_str(password) if password else b"")
    )

    deadline = time.time() + args.seconds
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.settimeout(1)
        sock.sendall(mqtt_packet(1, 0, connect))
        subscribed = False
        while time.time() < deadline:
            try:
                header, body = read_packet(sock)
            except socket.timeout:
                continue
            kind = header >> 4
            if kind == 2:  # CONNACK
                if not subscribed:
                    subscribe = struct.pack("!H", 1) + enc_str(topic) + b"\x00"
                    sock.sendall(mqtt_packet(8, 0x02, subscribe))
                    subscribed = True
                    print(f"mqtt: subscribed to {topic} (read only)")
            elif kind == 3:  # PUBLISH
                qos = (header >> 1) & 0x03
                length = struct.unpack("!H", body[:2])[0]
                name = body[2 : 2 + length].decode("utf-8", "replace")
                offset = 2 + length + (2 if qos else 0)
                payload = body[offset:].decode("utf-8", "replace")
                print(f"{name} = {payload}")


def broadcast_probe(args) -> None:
    """Listen for Terneo UDP announcements on port 23500."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    sock.bind(("0.0.0.0", 23500))
    sock.settimeout(1)
    deadline = time.time() + args.seconds
    print("broadcast: listening on UDP 23500")
    while time.time() < deadline:
        try:
            data, source = sock.recvfrom(2048)
        except socket.timeout:
            continue
        try:
            message = json.loads(data)
        except ValueError:
            continue
        if args.sn and message.get("sn") != args.sn:
            continue
        print(f"{source[0]}: {message}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode", choices=["http", "mqtt", "broadcast", "all"], default="http",
        help="http=local API, mqtt=subscribe only, broadcast=UDP search, all=every read mode",
    )
    parser.add_argument("--host", help="thermostat IP address or hostname (http/all)")
    parser.add_argument("--sn", help="thermostat serial number (http/all)")
    parser.add_argument(
        "--cmd", type=int, choices=[1, 4], default=4,
        help="read command: 4=status, 1=parameters",
    )
    parser.add_argument(
        "--seconds", type=int, default=20,
        help="listen window in seconds for mqtt/broadcast modes",
    )
    parser.add_argument(
        "--mqtt-topic", default="pub_terneo/+/get/#",
        help="read-only MQTT topic filter",
    )
    args = parser.parse_args()

    if args.mode in ("http", "all"):
        missing = []
        if not args.host:
            missing.append("--host <IP>")
        if not args.sn:
            missing.append("--sn <SERIAL>")
        if missing:
            print(f"Missing required arguments for --mode {args.mode}: {', '.join(missing)}")
            print(
                "How to run: python3 tools/probe_terneo.py --mode http "
                "--host <IP> --sn <SERIAL> --cmd 4"
            )
            raise SystemExit(2)

    totp_key = os.environ.get("TERNEO_TOTP_KEY")
    if args.mode in ("http", "all"):
        if totp_key:
            print("auth: using TERNEO_TOTP_KEY from environment")
        else:
            print("auth: TERNEO_TOTP_KEY is not set; using dummy token (read-only polling)")
        http_probe(args.host, args.sn, args.cmd, totp_key)
    if args.mode in ("mqtt", "all"):
        mqtt_probe(args)
    if args.mode in ("broadcast", "all"):
        broadcast_probe(args)


if __name__ == "__main__":
    main()
