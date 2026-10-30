"""Estudos de caso reais: 2/4 peers, 1024/4096 B e 10KB-20MB.

Uso: python scripts/benchmark.py --quick | --full
As saidas registram cada teste e suas provas de integridade em evidencias/.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidencias"
DEFAULT_CASES = [
    ("A_10KB_base", 2, 1024, 10 * 1024),
    ("A_20KB_variacao", 4, 4096, 20 * 1024),
    ("B_1MB_base", 2, 1024, 1 * 1024 * 1024),
    ("B_5MB_variacao", 4, 4096, 5 * 1024 * 1024),
    ("C_10MB_base", 2, 1024, 10 * 1024 * 1024),
    ("C_20MB_variacao", 4, 4096, 20 * 1024 * 1024),
    # Contrastes controlados, para nao confundir efeito de #peers e tamanho de bloco:
    ("B_1MB_4peers_1024", 4, 1024, 1 * 1024 * 1024),
    ("B_1MB_2peers_4096", 2, 4096, 1 * 1024 * 1024),
    ("C_10MB_4peers_1024", 4, 1024, 10 * 1024 * 1024),
    ("C_10MB_2peers_4096", 2, 4096, 10 * 1024 * 1024),
]
QUICK_CASES = DEFAULT_CASES[:4]


def test_bytes(path, size, seed):
    rng = random.Random(seed)
    with path.open("wb") as f:
        remaining = size
        while remaining:
            n = min(1024 * 1024, remaining)
            f.write(rng.randbytes(n))
            remaining -= n


def checksum(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def run_case(case, work_root, index, timeout=180):
    name, n_peers, block_size, size = case
    case_dir = work_root / name
    case_dir.mkdir(parents=True, exist_ok=True)
    payload = case_dir / f"File_{name.split('_')[0]}.bin"
    test_bytes(payload, size, seed=731 + size)
    original_hash = checksum(payload)
    ports = [31000 + index * 10 + i for i in range(n_peers)]
    procs = []
    log_files = []
    t0 = time.perf_counter()
    success = False
    failure = ""
    try:
        for i, port in enumerate(ports):
            pdir = case_dir / f"peer_{i}"
            cmd = [sys.executable, "-m", "p2p.peer", "--host", "127.0.0.1", "--port", str(port),
                   "--directory", str(pdir), "--timeout", str(timeout)]
            if i == 0:
                cmd += ["--seed", str(payload), "--block-size", str(block_size)]
            else:
                # Topologia em cadeia 0 -> 1 -> 2 -> 3, para exigir real compartilhamento.
                cmd += ["--peer", f"127.0.0.1:{ports[i-1]}"]
            logfile = (pdir.parent / f"console_peer_{i}.log").open("w", encoding="utf-8")
            log_files.append(logfile)
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=logfile, stderr=subprocess.STDOUT)
            procs.append(proc)
            # Pequena defasagem: conexoes concorrentes existem durante a transferencia.
            time.sleep(.035 if i else .08)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all((case_dir / f"peer_{i}" / "summary.json").exists() for i in range(1, n_peers)):
                break
            if any(p.poll() not in (None, 0) for p in procs):
                raise RuntimeError("peer encerrou com erro; consulte o console")
            time.sleep(.05)
        else:
            raise TimeoutError("tempo esgotado esperando todos os peers")
        reports = []
        for i in range(1, n_peers):
            report = json.loads((case_dir / f"peer_{i}" / "summary.json").read_text())
            reconstructed = Path(report["file"])
            if not reconstructed.is_file() or reconstructed.stat().st_size != size:
                raise AssertionError(f"peer {i}: tamanho de arquivo incorreto")
            if checksum(reconstructed) != original_hash or not report["integrity_ok"]:
                raise AssertionError(f"peer {i}: SHA-256 nao coincide")
            reports.append(report)
        if n_peers == 4:
            # Em cadeia, 2 so pode obter blocos de 1, e 3 apenas de 2.
            for idx, report in enumerate(reports[1:], start=2):
                expected = f"127.0.0.1:{ports[idx - 1]}"
                if not report["source_blocks"].get(expected, 0):
                    raise AssertionError(f"peer {idx} nao transferiu blocos do vizinho {expected}")
        success = True
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for f in log_files:
            f.close()
    elapsed = round(time.perf_counter() - t0, 4)
    summaries = []
    for i in range(1, n_peers):
        path = case_dir / f"peer_{i}" / "summary.json"
        if path.exists():
            summaries.append(json.loads(path.read_text()))
    record = {"case": name, "peers": n_peers, "block_size_bytes": block_size,
              "file_size_bytes": size, "blocks": (size + block_size - 1) // block_size,
              "sha256_original": original_hash, "all_sha256_match": success,
              "wall_seconds": elapsed,
              "last_peer_seconds": max((x["elapsed_seconds"] for x in summaries), default=None),
              "downloaded_peers": len(summaries),
              "relay_block_counts": {f"peer_{i}": r["source_blocks"] for i, r in enumerate(summaries, start=1)},
              "status": "PASS" if success else "FAIL", "error": failure}
    (case_dir / "result.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def main():
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--quick", action="store_true", help="4 testes para verificar a instalacao")
    group.add_argument("--full", action="store_true", help="10 estudos de caso completos")
    ap.add_argument("--keep-work", action="store_true", help="mantem arquivos binarios e downloads intermediarios")
    ap.add_argument("--timeout", type=float, default=240)
    args = ap.parse_args()
    EVIDENCE.mkdir(exist_ok=True)
    work = ROOT / ".benchmark_work"
    work.mkdir(exist_ok=True)
    cases = QUICK_CASES if args.quick else DEFAULT_CASES
    records = []
    for i, case in enumerate(cases):
        print(f"[{i+1}/{len(cases)}] {case[0]}: peers={case[1]}, bloco={case[2]}, bytes={case[3]}", flush=True)
        record = run_case(case, work, i, args.timeout)
        records.append(record)
        print(f"    {record['status']}, {record['wall_seconds']}s, relays={record['relay_block_counts']}", flush=True)
        if record["status"] != "PASS":
            print("ERRO:", record["error"], file=sys.stderr)
            break
    tag = "quick" if args.quick else "full"
    now = datetime.now(timezone.utc).isoformat()
    (EVIDENCE / f"resultados_{tag}.json").write_text(json.dumps({"run_utc": now, "cases": records}, indent=2, ensure_ascii=False), encoding="utf-8")
    columns = ["case", "peers", "block_size_bytes", "file_size_bytes", "blocks", "wall_seconds", "last_peer_seconds", "downloaded_peers", "sha256_original", "all_sha256_match", "status", "error"]
    with (EVIDENCE / f"resultados_{tag}.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=columns)
        wr.writeheader()
        wr.writerows({k: record.get(k) for k in columns} for record in records)
    logdir = EVIDENCE / f"logs_{tag}"
    logdir.mkdir(exist_ok=True)
    import gzip
    for result in records:
        case_dir = work / result["case"]
        for file in case_dir.glob("peer_*/events.jsonl"):
            with file.open("rb") as inp, gzip.open(logdir / f"{result['case']}_{file.parent.name}.jsonl.gz", "wb", compresslevel=5) as out:
                shutil.copyfileobj(inp, out)
        if not args.keep_work:
            shutil.rmtree(case_dir)
    if not args.keep_work:
        try:
            work.rmdir()
        except OSError:
            pass
    print(f"Resultados: {EVIDENCE / f'resultados_{tag}.csv'}", flush=True)
    return 0 if len(records) == len(cases) and all(r["status"] == "PASS" for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
