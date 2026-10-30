"""Peer simetrico cliente/servidor com asyncio e vizinhos estaticos."""
import argparse
import asyncio
import base64
from collections import Counter
from datetime import datetime, timezone
import json
import signal
import sys
import time
from pathlib import Path

from .protocol import ProtocolError, read_frame, send_frame
from .storage import BlockStore, create_manifest, validate_manifest, sha256_file


def peer_address(text):
    try:
        host, port = text.rsplit(":", 1)
        if not host or not 1 <= int(port) <= 65535:
            raise ValueError()
        return host, int(port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("endereco deve ser HOST:PORTA") from exc


class Node:
    def __init__(self, args):
        self.args = args
        self.root = Path(args.directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_file = (self.root / "events.jsonl").open("a", buffering=1, encoding="utf-8")
        self.store = None
        self.server = None
        self.reserved = set()
        self.reserve_lock = asyncio.Lock()
        self.started_at = time.monotonic()
        self.source_counts = Counter()
        self.received_bytes = 0
        self.requests = 0
        self.stop = asyncio.Event()
        self.completed = asyncio.Event()
        self.name = f"{args.host}:{args.port}"
        self.last_percent = -1

    def log(self, event, **kwargs):
        record = {"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                  "event": event, "node": self.name, **kwargs}
        self.log_file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        if event in ("listening", "manifest_ready", "complete", "error"):
            print(f"[{self.name}] {event}: {kwargs}", flush=True)

    async def handle_client(self, reader, writer):
        remote = writer.get_extra_info("peername")
        try:
            while True:
                request, payload = await read_frame(reader)
                kind = request.get("type")
                if kind == "manifest":
                    if self.store is None:
                        await send_frame(writer, {"type": "not_ready"})
                    else:
                        await send_frame(writer, {"type": "manifest", "data": self.store.manifest})
                elif kind == "status":
                    if self.store is None:
                        await send_frame(writer, {"type": "not_ready"})
                    else:
                        await send_frame(writer, {"type": "status", "sha256": self.store.manifest["sha256"],
                                                  "block_size": self.store.manifest["block_size"],
                                                  "count": self.store.count,
                                                  "bits": base64.b64encode(self.store.bits).decode("ascii")})
                elif kind == "block":
                    idx = request.get("index")
                    data = self.store.read_block(idx) if self.store else None
                    if data is None:
                        await send_frame(writer, {"type": "missing", "index": idx})
                    else:
                        await send_frame(writer, {"type": "block", "index": idx}, data)
                        self.log("sent_block", to=str(remote), block=idx, bytes=len(data))
                else:
                    await send_frame(writer, {"type": "error", "message": "operacao desconhecida"})
                if payload:
                    raise ProtocolError("requisicoes nao podem ter payload")
        except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError, asyncio.CancelledError):
            pass
        except (ProtocolError, ValueError) as exc:
            self.log("protocol_rejection", remote=str(remote), detail=str(exc))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass

    async def request_manifest(self, neighbor):
        reader, writer = await asyncio.wait_for(asyncio.open_connection(*neighbor), timeout=2.0)
        try:
            await send_frame(writer, {"type": "manifest"})
            header, _ = await asyncio.wait_for(read_frame(reader), timeout=10)
            if header.get("type") == "manifest":
                return validate_manifest(header.get("data"))
        finally:
            writer.close()
            await writer.wait_closed()
        return None

    async def obtain_manifest(self):
        if self.args.seed:
            manifest = create_manifest(self.args.seed, self.args.block_size)
            self.store = BlockStore(self.root, manifest, source_path=self.args.seed)
            (self.root / "metadata.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            self.log("manifest_ready", blocks=self.store.n, size=manifest["size"], sha256=manifest["sha256"])
            return
        if not self.args.peer:
            raise ValueError("leecher precisa de pelo menos um vizinho")
        deadline = time.monotonic() + self.args.timeout
        while time.monotonic() < deadline and not self.stop.is_set():
            # Conecta a todos os vizinhos para obter metadados, mesmo se alguns ainda nao subiram.
            results = await asyncio.gather(*(self.request_manifest(p) for p in self.args.peer),
                                           return_exceptions=True)
            manifests = [v for v in results if isinstance(v, dict)]
            if manifests:
                first = manifests[0]
                if any(m != first for m in manifests):
                    raise ProtocolError("vizinhos possuem manifestos divergentes")
                self.store = BlockStore(self.root, first)
                (self.root / "metadata.json").write_text(json.dumps(first, indent=2), encoding="utf-8")
                self.log("manifest_ready", blocks=self.store.n, size=first["size"], sha256=first["sha256"])
                return
            await asyncio.sleep(.15)
        raise TimeoutError("nao foi possivel obter o manifesto dos vizinhos")

    async def reserve(self, remote_bits, start):
        n = self.store.n
        async with self.reserve_lock:
            for advance in range(n):
                i = (start + advance) % n
                if not self.store.has(i) and i not in self.reserved and remote_bits[i // 8] & (1 << (i % 8)):
                    self.reserved.add(i)
                    return i
            return None

    async def worker(self, address, ordinal):
        label = f"{address[0]}:{address[1]}"
        cursor = (ordinal * max(1, self.store.n // max(1, len(self.args.peer)))) % max(1, self.store.n)
        while not self.completed.is_set() and not self.stop.is_set():
            writer = None
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(*address), timeout=2)
                self.log("connected", neighbor=label)
                while not self.completed.is_set() and not self.stop.is_set():
                    await send_frame(writer, {"type": "status"})
                    reply, _ = await asyncio.wait_for(read_frame(reader), timeout=10)
                    if reply.get("type") != "status":
                        await asyncio.sleep(.10)
                        continue
                    if reply.get("sha256") != self.store.manifest["sha256"] or reply.get("block_size") != self.store.manifest["block_size"]:
                        raise ProtocolError(f"swarm diferente em {label}")
                    try:
                        remote_bits = base64.b64decode(reply["bits"], validate=True)
                    except (ValueError, KeyError) as exc:
                        raise ProtocolError("inventario corrompido") from exc
                    if len(remote_bits) != len(self.store.bits):
                        raise ProtocolError("inventario com tamanho incorreto")
                    self.log("inventory", neighbor=label, remote_count=reply["count"], local_count=self.store.count)
                    got_any = False
                    for _ in range(32):
                        if self.completed.is_set() or self.stop.is_set():
                            break
                        idx = await self.reserve(remote_bits, cursor)
                        if idx is None:
                            break
                        cursor = (idx + 1) % max(1, self.store.n)
                        try:
                            await send_frame(writer, {"type": "block", "index": idx})
                            self.requests += 1
                            response, payload = await asyncio.wait_for(read_frame(reader), timeout=10)
                            if response.get("type") == "block" and response.get("index") == idx:
                                saved = await self.store.save_block(idx, payload)
                                if saved:
                                    got_any = True
                                    self.received_bytes += len(payload)
                                    self.source_counts[label] += 1
                                    self.log("received_block", source=label, block=idx, bytes=len(payload))
                                    pct = 100 * self.store.count // max(1, self.store.n)
                                    if pct // 10 > self.last_percent // 10:
                                        self.last_percent = pct
                                        self.log("progress", count=self.store.count, total=self.store.n, percent=pct)
                                    if self.store.count == self.store.n:
                                        self.completed.set()
                            elif response.get("type") != "missing":
                                raise ProtocolError("resposta de bloco inesperada")
                        finally:
                            self.reserved.discard(idx)
                    if not got_any:
                        await asyncio.sleep(.08)
            except (OSError, ConnectionError, asyncio.IncompleteReadError, asyncio.TimeoutError, ProtocolError) as exc:
                self.log("connection_retry", neighbor=label, detail=str(exc))
                await asyncio.sleep(.15)
            finally:
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except (OSError, ConnectionError):
                        pass

    async def run(self):
        try:
            self.server = await asyncio.start_server(self.handle_client, self.args.host, self.args.port)
            self.log("listening", neighbors=[f"{p[0]}:{p[1]}" for p in self.args.peer])
            await self.obtain_manifest()
            if self.args.seed:
                await self.stop.wait()
                return 0
            if self.store.count == self.store.n:
                self.completed.set()
            workers = [asyncio.create_task(self.worker(p, i)) for i, p in enumerate(self.args.peer)]
            try:
                await asyncio.wait_for(self.completed.wait(), timeout=self.args.timeout)
                result = self.store.finalize()
                elapsed = round(time.monotonic() - self.started_at, 6)
                summary = {"node": self.name, "file": str(result), "file_name": result.name,
                           "size": self.store.manifest["size"], "block_size": self.store.manifest["block_size"],
                           "blocks": self.store.n, "sha256_expected": self.store.manifest["sha256"],
                           "sha256_observed": sha256_file(result), "integrity_ok": True,
                           "elapsed_seconds": elapsed, "received_bytes": self.received_bytes,
                           "block_requests": self.requests,
                           "source_blocks": dict(self.source_counts)}
                (self.root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
                self.log("complete", elapsed_seconds=elapsed, blocks=self.store.count,
                         sha256=summary["sha256_observed"], sources=summary["source_blocks"])
                # Mantenha o servidor vivo por padrao para repassar blocos aos outros leechers.
                if not self.args.exit_when_complete:
                    await self.stop.wait()
            finally:
                for worker in workers:
                    worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
            return 0
        except Exception as exc:
            self.log("error", detail=f"{type(exc).__name__}: {exc}")
            return 1
        finally:
            if self.server:
                self.server.close()
                await self.server.wait_closed()
            self.log_file.close()


def main():
    parser = argparse.ArgumentParser(description="TP2: transferencia de arquivo P2P usando sockets TCP/asyncio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--peer", type=peer_address, action="append", default=[], help="vizinho HOST:PORTA (repita)")
    parser.add_argument("--directory", required=True, help="diretorio isolado deste peer")
    parser.add_argument("--seed", help="arquivo original do seeder; omitir em leechers")
    parser.add_argument("--block-size", type=int, default=1024, help="1024 ou 4096 nos estudos de caso")
    parser.add_argument("--timeout", type=float, default=180, help="tempo maximo do leecher em segundos")
    parser.add_argument("--exit-when-complete", action="store_true", help="encerrar leecher depois do download (modo de teste)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.timeout <= 0:
        parser.error("porta ou timeout invalido")
    if len(set(args.peer)) != len(args.peer):
        parser.error("vizinhos duplicados")
    if (args.host, args.port) in args.peer:
        parser.error("o proprio peer nao pode constar como vizinho")
    node = Node(args)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, node.stop.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda _sig, _frame: loop.call_soon_threadsafe(node.stop.set))
    try:
        exit_code = loop.run_until_complete(node.run())
    finally:
        loop.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
