"""Executa uma topologia configurada em JSON e preserva arquivos de saida."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    cli = argparse.ArgumentParser(description="Inicia a demonstracao P2P a partir de um arquivo de configuracao")
    cli.add_argument("config", help="ex: config/4_peers.json")
    cli.add_argument("--timeout", type=float, default=60)
    args = cli.parse_args()
    config_path = Path(args.config).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    seed = ROOT / cfg["seed_file"]
    if not seed.exists():
        cli.error(f"Arquivo de origem inexistente: {seed}")
    out = ROOT / "execucoes" / cfg["name"]
    out.mkdir(parents=True, exist_ok=True)
    procs, logs = [], []
    try:
        for idx, peer in enumerate(cfg["peers"]):
            directory = out / peer["id"]
            directory.mkdir(exist_ok=True)
            cmd = [sys.executable, "-m", "p2p.peer", "--host", peer["host"],
                   "--port", str(peer["port"]), "--directory", str(directory),
                   "--timeout", str(args.timeout)]
            if idx == 0:
                cmd += ["--seed", str(seed), "--block-size", str(cfg["block_size"])]
            for endpoint in peer["neighbors"]:
                cmd += ["--peer", endpoint]
            logfile = (out / f"{peer['id']}_console.log").open("w", encoding="utf-8")
            logs.append(logfile)
            procs.append(subprocess.Popen(cmd, cwd=ROOT, stdout=logfile, stderr=subprocess.STDOUT))
            print(f"Iniciado {peer['id']} -> {peer['host']}:{peer['port']}", flush=True)
            time.sleep(.07)
        deadline = time.monotonic() + args.timeout
        completed = [out / p["id"] / "summary.json" for p in cfg["peers"][1:]]
        while time.monotonic() < deadline:
            if all(f.is_file() for f in completed):
                break
            if any(p.poll() not in (None, 0) for p in procs):
                raise RuntimeError("algum peer falhou, veja os logs em execucoes/")
            time.sleep(.05)
        else:
            raise TimeoutError("tempo esgotado")
        for file in completed:
            data = json.loads(file.read_text(encoding="utf-8"))
            if not data["integrity_ok"]:
                raise RuntimeError(f"erro de integridade em {file}")
            print(f"{data['node']}: OK, SHA-256={data['sha256_observed']}, fontes={data['source_blocks']}")
        print(f"Arquivos remontados e logs em: {out}")
        return 0
    except (KeyboardInterrupt, Exception) as exc:
        print(f"Erro/interrupcao: {exc}", file=sys.stderr)
        return 1
    finally:
        for process in procs:
            if process.poll() is None:
                process.terminate()
        for process in procs:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    sys.exit(main())
