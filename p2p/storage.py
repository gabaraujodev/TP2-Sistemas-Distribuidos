"""Manifesto, fragmentacao logica, bitfield, armazenamento e integridade."""
import asyncio
import hashlib
import json
import math
import os
import re
from pathlib import Path

from .protocol import MAX_PAYLOAD, ProtocolError

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_BLOCKS = 50_000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def create_manifest(path, block_size):
    path = Path(path)
    if not path.is_file():
        raise ValueError("arquivo de origem nao existe")
    if not 1 <= block_size <= MAX_PAYLOAD:
        raise ValueError("block_size invalido")
    size = path.stat().st_size
    n = math.ceil(size / block_size)
    if n > MAX_BLOCKS:
        raise ValueError("quantidade de blocos acima do limite de seguranca")
    whole = hashlib.sha256()
    hashes = []
    with path.open("rb") as f:
        while block := f.read(block_size):
            whole.update(block)
            hashes.append(hashlib.sha256(block).hexdigest())
    return {"protocol_version": 1, "file_name": path.name, "size": size,
            "block_size": block_size, "sha256": whole.hexdigest(),
            "block_hashes": hashes}


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("protocol_version") != 1:
        raise ProtocolError("versao de manifesto desconhecida")
    name = manifest.get("file_name")
    if (not isinstance(name, str) or not name or name in (".", "..")
            or Path(name).name != name or "/" in name or "\\" in name
            or "\x00" in name or ":" in name or len(name) > 180):
        raise ProtocolError("nome de arquivo inseguro")
    size, step, hashes = (manifest.get("size"), manifest.get("block_size"),
                          manifest.get("block_hashes"))
    if type(size) is not int or size < 0:
        raise ProtocolError("tamanho do arquivo invalido")
    if type(step) is not int or not 1 <= step <= MAX_PAYLOAD:
        raise ProtocolError("tamanho de bloco invalido")
    if (not isinstance(hashes, list) or len(hashes) != math.ceil(size / step)
            or len(hashes) > MAX_BLOCKS):
        raise ProtocolError("lista de hashes invalida")
    if not isinstance(manifest.get("sha256"), str) or not SHA_RE.fullmatch(manifest["sha256"]):
        raise ProtocolError("SHA-256 global invalido")
    if not all(isinstance(h, str) and SHA_RE.fullmatch(h) for h in hashes):
        raise ProtocolError("hashes de blocos invalidos")
    return manifest


class BlockStore:
    """Usa offsets em arquivo unico em vez de criar milhares de arquivos pequenos."""
    def __init__(self, directory, manifest, source_path=None):
        self.manifest = validate_manifest(manifest)
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.n = len(manifest["block_hashes"])
        self.bits = bytearray((self.n + 7) // 8)
        self.count = 0
        self.lock = asyncio.Lock()
        self.is_seed = source_path is not None
        self.output = self.root / "downloads" / manifest["file_name"]
        self.partial = self.root / "downloads" / (manifest["file_name"] + ".part")
        self.have_log = self.root / "have.log"
        if source_path:
            self.path = Path(source_path)
            if self.path.stat().st_size != manifest["size"] or sha256_file(self.path) != manifest["sha256"]:
                raise ValueError("seeder nao coincide com metadados")
            for idx in range(self.n):
                self._set_bit(idx)
        else:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.path = self.partial
            if self.output.exists() and self.output.stat().st_size == manifest["size"] and sha256_file(self.output) == manifest["sha256"]:
                self.path = self.output
                for idx in range(self.n):
                    self._set_bit(idx)
            else:
                if not self.partial.exists():
                    self.partial.touch()
                # Reinicio seguro: confirma SHA-256 dos indices do log, nunca confia cegamente.
                if self.have_log.exists():
                    try:
                        indexes = {int(line) for line in self.have_log.read_text().splitlines()}
                    except (ValueError, UnicodeError):
                        indexes = set()
                    with self.partial.open("rb") as f:
                        for idx in indexes:
                            if 0 <= idx < self.n:
                                f.seek(idx * manifest["block_size"])
                                chunk = f.read(self.block_length(idx))
                                if hashlib.sha256(chunk).hexdigest() == manifest["block_hashes"][idx]:
                                    self._set_bit(idx)

    def _set_bit(self, idx):
        if not self.has(idx):
            self.bits[idx // 8] |= 1 << (idx % 8)
            self.count += 1

    def has(self, idx):
        return bool(self.bits[idx // 8] & (1 << (idx % 8)))

    def block_length(self, idx):
        return min(self.manifest["block_size"],
                   self.manifest["size"] - idx * self.manifest["block_size"])

    def read_block(self, idx):
        if type(idx) is not int or idx < 0 or idx >= self.n or not self.has(idx):
            return None
        with self.path.open("rb") as f:
            f.seek(idx * self.manifest["block_size"])
            return f.read(self.block_length(idx))

    async def save_block(self, idx, data):
        if type(idx) is not int or idx < 0 or idx >= self.n:
            raise ProtocolError("indice de bloco invalido")
        if len(data) != self.block_length(idx):
            raise ProtocolError("comprimento de bloco invalido")
        if hashlib.sha256(data).hexdigest() != self.manifest["block_hashes"][idx]:
            raise ProtocolError("SHA-256 do bloco nao confere")
        async with self.lock:
            if self.has(idx):
                return False
            if self.path == self.output:
                raise ProtocolError("arquivo final ja disponivel")
            with self.partial.open("r+b") as f:
                f.seek(idx * self.manifest["block_size"])
                f.write(data)
            with self.have_log.open("a", encoding="utf-8") as f:
                f.write(f"{idx}\n")
            self._set_bit(idx)
            return True

    def finalize(self):
        if self.count != self.n:
            raise ValueError("faltam blocos")
        if self.is_seed:
            return self.path
        # Arquivos vazios e grandes sao validados pelo hash global.
        if self.path == self.output:
            return self.output
        if self.partial.stat().st_size != self.manifest["size"]:
            raise ValueError("tamanho remontado diferente do manifesto")
        if sha256_file(self.partial) != self.manifest["sha256"]:
            raise ValueError("SHA-256 global nao confere")
        os.replace(self.partial, self.output)
        self.path = self.output
        return self.output
