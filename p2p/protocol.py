"""Protocolo TCP com frame JSON e payload binario opcional.

Frame: 4 bytes unsigned big endian com tamanho do cabecalho JSON,
seguido do JSON UTF-8 e de `payload_length` bytes binarios (se houver).
"""
import asyncio
import json
import struct

MAX_HEADER = 4 * 1024 * 1024
MAX_PAYLOAD = 1024 * 1024


class ProtocolError(Exception):
    """Mensagem invalida ou conexao protocolar inconsistente."""


async def send_frame(writer, message: dict, payload: bytes = b""):
    if not isinstance(payload, bytes):
        raise TypeError("payload precisa ser bytes")
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("payload maior que o limite")
    msg = dict(message)
    if payload:
        msg["payload_length"] = len(payload)
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not raw or len(raw) > MAX_HEADER:
        raise ProtocolError("cabecalho excedeu o tamanho permitido")
    writer.write(struct.pack("!I", len(raw)) + raw + payload)
    await writer.drain()


async def read_frame(reader):
    size = struct.unpack("!I", await reader.readexactly(4))[0]
    if not 0 < size <= MAX_HEADER:
        raise ProtocolError("tamanho do cabecalho invalido")
    raw = await reader.readexactly(size)
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ProtocolError("JSON invalido") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("cabecalho nao e objeto JSON")
    size_data = obj.get("payload_length", 0)
    if type(size_data) is not int or not 0 <= size_data <= MAX_PAYLOAD:
        raise ProtocolError("tamanho de payload invalido")
    return obj, await reader.readexactly(size_data)
