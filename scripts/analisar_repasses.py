"""Audita nos logs se leechers serviram blocos antes do download terminar."""
from datetime import datetime
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidencias"


def load_events(case, idx):
    source = EVIDENCE / "logs_full" / f"{case}_peer_{idx}.jsonl.gz"
    with gzip.open(source, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def first(events, name):
    return next((e["time"] for e in events if e["event"] == name), None)


def main():
    cases = ["A_20KB_variacao", "B_5MB_variacao", "C_20MB_variacao",
             "B_1MB_4peers_1024", "C_10MB_4peers_1024"]
    details = {}
    for case in cases:
        records = []
        for peer in (1, 2):
            ev = load_events(case, peer)
            first_sent = first(ev, "sent_block")
            complete = first(ev, "complete")
            delta = ((datetime.fromisoformat(complete) - datetime.fromisoformat(first_sent)).total_seconds()
                     if first_sent and complete else None)
            records.append({"peer": f"peer_{peer}", "first_sent_utc": first_sent,
                            "completed_utc": complete,
                            "served_before_completion": delta is not None and delta > 0,
                            "seconds_before_completion": delta})
        details[case] = records
    destination = EVIDENCE / "analise_repasses.json"
    destination.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    for case, entries in details.items():
        print(case, ", ".join(f"{x['peer']} antes de completar={x['served_before_completion']}"
                              for x in entries))
    print(destination)


if __name__ == "__main__":
    main()
