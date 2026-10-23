"""Offline tool-contract evaluation by default. --live requires explicit network opt-in."""
import argparse
import json
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

from agent import Copilot
from openai_client import network_enabled
from factory import Factory
from state import Store

ROOT = Path(__file__).resolve().parent


def lookup(value, path):
    for key in path.split("."):
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def matches(facts, expected):
    try:
        return all(lookup(facts, key) == value for key, value in expected.items())
    except (KeyError, IndexError, TypeError):
        return False


def run(live=False):
    if live and not network_enabled():
        raise SystemExit("Live evaluation is disabled: data-export permission and OPENAI_NETWORK_ENABLED=true are required.")
    suite = json.loads((ROOT / "evaluation" / "cases.json").read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory)/"evaluation.sqlite3")
        engine = Copilot(Factory(date.fromisoformat(suite["as_of"])), store)
        for case in suite["cases"]:
            result = {"id":case["id"],"category":case["category"],"question":case["question"]}
            try:
                if live:
                    answer = engine.ask(case["question"])
                    behavior = answer["kind"] == case["expected_kind"]
                    facts_ok = not case["expected_facts"] or any(matches(e["facts"],case["expected_facts"]) for e in answer["evidence"].values())
                    result.update(status="pass" if behavior and facts_ok else "fail",behavior_match=behavior,tool_facts_match=facts_ok,answer=answer)
                elif case["tool"]:
                    facts = engine.execute(case["tool"], case["arguments"])["facts"]
                    result.update(status="pass" if matches(facts,case["expected_facts"]) else "fail",expected=case["expected_facts"])
                    if result["status"]=="fail": result["actual"]=facts
                else:
                    result.update(status="not_assessed",reason="Requires real natural-language model behavior, disabled by user.")
                if store.activity()["actions"]:
                    result.update(status="fail",reason="Unexpected unconfirmed write")
            except Exception as exc:
                result.update(status="fail",error_type=type(exc).__name__,reason=str(exc))
            results.append(result)
            print(f"{result['id']} {result['status']}", flush=True)
    counts=Counter(r["status"] for r in results)
    measured=counts["pass"]+counts["fail"]
    report={"mode":"live" if live else "offline_tool_contracts", "question_count":len(results),
            "counts":dict(counts),"pass_rate":counts["pass"]/measured if measured else None,
            "real_model_accuracy":None,"semantic_answer_accuracy":None,
            "warning":"Offline results test deterministic tools with supplied arguments, not natural-language understanding. Live automatic behavior/fact checks still require human semantic review. Development set, no held-out generalization claim.",
            "by_category":{category:dict(Counter(r["status"] for r in results if r["category"]==category)) for category in sorted({r['category'] for r in results})},
            "results":results}
    destination=ROOT/'evaluation'/('results_live.json' if live else 'results_offline.json')
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true',help='Send questions/tool results to OpenAI only after explicit authorization.')
    run(parser.parse_args().live)
