"""Loop B, iterated: improve the validator several times in a row (SPEC §5.2), each change tested on human rows.

    uv run python -m taxo.improve fragrance --iterations 4 --misses 60 --ab 120
    uv run python -m taxo.improve fragrance --fit 6 --train 120 --test 120      fit on one sample, then a held-out check

One iteration:
  1. human round   a fresh dev sample with human labels (Pedia stands in for the person); the validator labels it blind;
                   its misses, with their traces, go to the improver (never the gold file, never sealed)
  2. improver      ONE change: a question edit, or a new tool with an input it fires on and one it stays quiet on
                   (code runs both; a tool whose two cases do not run, or give the same result, is refused)
  3. A/B           a fresh dev sample; the current and the candidate validator label the same listings at once
  4. decide        kept only if exact rises, harm does not, and the abstain/reject rate does not drift by more than
                   5 points; deltas are paired, with 95% intervals. A kept change writes validator.yaml (version + 1)
                   and validator_tools.py, and is committed and pushed.
A proposed tool is model-written Python: it is run once in a scratch module on its own two cases before any A/B.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

import yaml

from taxo import kpis, loop, loopb, score, validator
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR
from taxo.lattice.vocab import tokens

HARM = {"deeper", "wrong", "wrong_brand"}
FIT_TARGET = 0.95   # fit until the training error is within 5%: closer than that only memorises the sample


def _say(m: str) -> None:
    print(m, flush=True)


def per_item(domain: str, labels: list[dict]) -> dict[str, dict]:
    """Per listing: the class against the human label, and whether the validator abstained or rejected."""
    P = {json.loads(x)["id"]: json.loads(x) for x in open(RUNS_DIR / domain / "placements.jsonl", encoding="utf-8")}
    out = {}
    for v in labels:
        p = P[v["id"]]
        gp = p["pedia_path"]
        if not gp:
            continue
        cls = score.judge(p["pedia_brand"], v["path"], p["pedia_brand"], gp, set(tokens(gp[0]))).cls
        out[v["id"]] = {"exact": cls == "exact", "harm": cls in HARM,
                        "abstain": v.get("decision") in ("abstain", "reject")}
    return out


def _wilson(k: int, n: int) -> list[float]:
    if not n:
        return [0.0, 0.0]
    p, z = k / n, 1.96
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(c - h, 3), round(c + h, 3)]


def compare(a: dict, b: dict) -> dict:
    """Paired comparison on the listings both arms answered: rate per arm with a Wilson interval, and the paired
    difference (candidate - current) with a 95% normal interval."""
    ids = sorted(set(a) & set(b))
    n = len(ids)
    out = {"n": n}
    for m in ("exact", "harm", "abstain"):
        ka, kb = sum(a[i][m] for i in ids), sum(b[i][m] for i in ids)
        d = [int(b[i][m]) - int(a[i][m]) for i in ids]
        mean = sum(d) / max(n, 1)
        sd = math.sqrt(sum((x - mean) ** 2 for x in d) / max(n - 1, 1))
        half = 1.96 * sd / math.sqrt(max(n, 1))
        out[m] = {"current": round(ka / max(n, 1), 3), "current_ci": _wilson(ka, n),
                  "candidate": round(kb / max(n, 1), 3), "candidate_ci": _wilson(kb, n),
                  "delta": round(mean, 3), "delta_ci": [round(mean - half, 3), round(mean + half, 3)],
                  "changed": sum(1 for x in d if x)}
    return out


def try_tool(domain: str, ch: dict) -> tuple[str | None, str]:
    """A proposed tool: written to a scratch module, its fires_on and quiet_on cases run. Returns (the source to append
    to validator_tools.py, why) or (None, why it was refused)."""
    from agents import FunctionTool
    from agents.tool_context import ToolContext

    from taxo.pipeline import brand_names
    from taxo.roles.validator import ValidateContext
    name, code = ch.get("tool_name"), ch.get("code") or ""
    if not name or "@function_tool" not in code:
        return None, "no tool name or no @function_tool code"
    src = f"\n\n# proposed by the improver: {ch.get('text', '')[:120]}\n{code.strip()}\n\nTOOLS.append({name})\n"
    base = (DOMAINS_DIR / domain / "validator_tools.py").read_text(encoding="utf-8")
    scratch = RUNS_DIR / domain / "loopb" / f"tool-try-{uuid.uuid4().hex[:6]}.py"
    scratch.write_text(base + src, encoding="utf-8")
    try:
        ns: dict = {}
        exec(compile(scratch.read_text(encoding="utf-8"), str(scratch), "exec"), ns)
        tool = ns.get(name)
        if not isinstance(tool, FunctionTool):
            return None, f"{name} is not a FunctionTool"
        ctx = ValidateContext(domain, sorted(set(brand_names().values())), "tool-test", 0, {})
        outs = []
        for case in ("fires_on", "quiet_on"):
            args = ch.get(case)
            args = args if isinstance(args, str) else json.dumps(args or {})
            json.loads(args)
            r = asyncio.run(tool.on_invoke_tool(ToolContext(context=ctx, tool_name=name, tool_call_id="t",
                                                            tool_arguments=args), args))
            outs.append(str(r))
        if outs[0] == outs[1]:
            return None, f"fires_on and quiet_on give the same result ({outs[0][:80]})"
        return src, f"fires_on -> {outs[0][:80]} | quiet_on -> {outs[1][:80]}"
    except Exception as e:
        return None, f"tool test failed: {type(e).__name__}: {str(e)[:160]}"
    finally:
        scratch.unlink(missing_ok=True)


def _commit(msg: str) -> str:
    subprocess.run(["git", "-C", str(ROOT), "add", "domains"], check=True)
    r = subprocess.run(["git", "-C", str(ROOT), "commit", "-q", "-m", msg + "\n\nCo-Authored-By: Claude Opus 5.5 "
                        "<noreply@anthropic.com>"], capture_output=True, text=True)
    subprocess.run(["git", "-C", str(ROOT), "push", "-q"], capture_output=True)
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return sha.stdout.strip() if r.returncode == 0 else f"commit failed: {r.stderr[-200:]}"


def iteration(domain: str, k: int, n_miss: int, n_ab: int, change: dict | None = None) -> dict:
    d = RUNS_DIR / domain / "loopb"
    # 1. human round: the validator's misses, with traces
    v = loop._next_v(domain)
    loopb.sample(domain, v, pool="pedia-dev", n=n_miss)
    validator.run(domain, v)
    misses = loop._misses(domain, v)
    n_lab = sum(1 for _ in open(d / f"{v}-validator.jsonl", encoding="utf-8"))
    _say(f"iteration {k}: human round {v}: {len(misses)} misses of {n_lab}")
    # 2. the improver's change (or the one given)
    ch = change or loop.propose_change(domain, misses, d / f"{v}-improver.json")
    if change:
        (d / f"{v}-improver.json").write_text(json.dumps(change, indent=1, ensure_ascii=False), encoding="utf-8")
    c = validator.card(domain)
    rec = {"iteration": k, "human_round": v, "misses": len(misses), "of": n_lab, "change": ch,
           "card_before": c.get("version")}
    tool_src, why = None, ""
    if ch and ch.get("kind") == "tool":
        tool_src, why = try_tool(domain, ch)
        rec["tool_test"] = why
        if tool_src and not ch.get("question_id"):
            ch = {**ch, "question_id": f"use_{ch['tool_name']}", "ask": ch.get("ask") or ch.get("text")}
        if tool_src:
            ch = {**ch, "tools": sorted(set(ch.get("tools") or []) | {ch["tool_name"]})}
    cand = loop.apply_change(c, ch, f"improver {v}: {(ch or {}).get('rationale', '')[:200]}") if ch else None
    if cand is None or (ch.get("kind") == "tool" and not tool_src):
        rec["outcome"] = f"nothing testable ({(ch or {}).get('kind')}: {why or (ch or {}).get('text')})"
        _say(f"  {rec['outcome']}")
        return rec
    # 3. A/B on a fresh sample, same listings, both arms at once (a proposed tool is written for the candidate arm only:
    #    the current arm's questions do not name it)
    tools_path = DOMAINS_DIR / domain / "validator_tools.py"
    tools_before = tools_path.read_text(encoding="utf-8")
    if tool_src:
        tools_path.write_text(tools_before + tool_src, encoding="utf-8")
    ab = loop._next_v(domain)
    loopb.sample(domain, ab, pool="pedia-dev", n=n_ab)
    items = [json.loads(x) for x in open(d / f"{ab}-blind.jsonl", encoding="utf-8")]
    with ThreadPoolExecutor(2) as pool:
        fa = pool.submit(validator.label, domain, items, d / f"{ab}-validator.log")
        fb = pool.submit(validator.label, domain, items, d / f"{ab}-validator-cand.log", False, 600, cand)
        cur, new = fa.result(), fb.result()
    for name, L in ((f"{ab}-validator.jsonl", cur), (f"{ab}-validator-cand.jsonl", new)):
        (d / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in L), encoding="utf-8")
    cmp_ = compare(per_item(domain, cur), per_item(domain, new))
    keep = cmp_["exact"]["delta"] > 0 and cmp_["harm"]["delta"] <= 0 and cmp_["abstain"]["delta"] <= 0.05
    rec |= {"ab_round": ab, "ab": cmp_, "kept": keep, "card_after": cand["version"] if keep else c.get("version")}
    # 4. decide: write and commit a kept change; restore the tools file otherwise
    if keep:
        path = DOMAINS_DIR / domain / "validator.yaml"
        head = "".join(ln for ln in path.read_text(encoding="utf-8").splitlines(keepends=True) if ln.startswith("#"))
        path.write_text(head + yaml.safe_dump(cand, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
        e = cmp_["exact"]
        rec["commit"] = _commit(f"Validator v{c.get('version')} -> v{cand['version']}: {ch.get('kind')} "
                                f"{ch.get('question_id') or ch.get('tool_name')} (improver, A/B {ab}: exact "
                                f"{e['current']} -> {e['candidate']}, delta {e['delta']} {e['delta_ci']}, n={cmp_['n']})")
    elif tool_src:
        tools_path.write_text(tools_before, encoding="utf-8")
    (d / f"{ab}-improve.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    m = json.loads((RUNS_DIR / domain / "metrics.json").read_text(encoding="utf-8"))
    kpis.append(domain, kpis.row(domain, m, "B", 300 + k, f"validator improver iteration {k}: "
                                 f"{'KEPT' if keep else 'dropped'} {ch.get('kind')} {ch.get('question_id')}",
                                 DOMAINS_DIR / domain / "vocab.yaml", [ROOT / "rules" / domain, ROOT / "rules" / "global"],
                                 silver={"version": ab, "validator": f"v{c.get('version')}->v{cand['version']}",
                                         "reviewer": "pedia", "agreement": cmp_["exact"]["candidate"], "ab": cmp_,
                                         "kept": keep}))
    e, h, a_ = cmp_["exact"], cmp_["harm"], cmp_["abstain"]
    _say(f"  A/B {ab} (n={cmp_['n']}): exact {e['current']} -> {e['candidate']} (delta {e['delta']} {e['delta_ci']}), "
         f"harm {h['current']} -> {h['candidate']} (delta {h['delta']} {h['delta_ci']}), abstain {a_['current']} -> "
         f"{a_['candidate']} (delta {a_['delta']}) -> "
         + (f"KEPT v{cand['version']} {rec.get('commit', '')}" if keep else "dropped"))
    return rec


def _write(d, name: str, labels: list[dict]) -> None:
    (d / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in labels), encoding="utf-8")


def fit(domain: str, rounds: int, n_train: int, n_test: int) -> dict:  # noqa: C901
    """Fit the validator to a fixed training sample of human rows (the improver works its misses round after round;
    a change is kept when the training sample's exact rises without harm or abstain rising), then ONE held-out check
    on fresh rows it never saw: the fitted version replaces the current one only if exact does not fall and harm and
    abstain do not rise there. This is what keeps "match the sample fully" from memorising the sample."""
    d = RUNS_DIR / domain / "loopb"
    used = [int(p.name[1:].split("-")[0]) for p in d.glob("F*-blind.jsonl")]
    F = f"F{max(used, default=0) + 1}"
    s0 = validator.card(domain)
    s = s0
    tools_path = DOMAINS_DIR / domain / "validator_tools.py"
    tools0 = tools_path.read_text(encoding="utf-8")
    loopb.sample(domain, F, pool="pedia-dev", n=n_train)
    items = [json.loads(x) for x in open(d / f"{F}-blind.jsonl", encoding="utf-8")]
    cur = validator.label(domain, items, d / f"{F}-r0.log", c=s)
    _write(d, f"{F}-validator.jsonl", cur)
    cur_pi = per_item(domain, cur)
    start = {m: round(sum(x[m] for x in cur_pi.values()) / max(len(cur_pi), 1), 3) for m in ("exact", "harm", "abstain")}
    _say(f"fit {F}: training sample n={len(cur_pi)}, validator v{s0.get('version')}: exact {start['exact']} harm "
         f"{start['harm']} abstain {start['abstain']}")
    hist = []
    for r in range(1, rounds + 1):
        misses = loop._misses(domain, F)
        exact_now = sum(x["exact"] for x in cur_pi.values()) / max(len(cur_pi), 1)
        if exact_now >= FIT_TARGET:
            _say(f"  round {r}: training exact {exact_now:.3f} is within 5% error; fitting stops")
            break
        ch = loop.propose_change(domain, misses, d / f"{F}-r{r}-improver.json")
        rec = {"round": r, "misses": len(misses), "change": ch}
        tool_src = None
        if ch and ch.get("kind") == "tool":
            tool_src, rec["tool_test"] = try_tool(domain, ch)
            if tool_src:
                ch = {**ch, "question_id": ch.get("question_id") or f"use_{ch['tool_name']}",
                      "ask": ch.get("ask") or ch.get("text"),
                      "tools": sorted(set(ch.get("tools") or []) | {ch["tool_name"]})}
        why_closed = loop.reopens_closed(domain, ch or {})
        cand = None if why_closed else (loop.apply_change(s, ch, f"improver fit {F} round {r}: "
                                                          f"{(ch or {}).get('rationale', '')[:160]}", domain) if ch else None)
        if cand is None or (ch.get("kind") == "tool" and not tool_src):
            rec["outcome"] = (f"refused: reopens closed question {why_closed}" if why_closed else
                              f"nothing testable ({(ch or {}).get('kind')}: {rec.get('tool_test') or (ch or {}).get('text')})")
            _say(f"  round {r}: {rec['outcome']}")
            hist.append(rec)
            continue
        before_tools = tools_path.read_text(encoding="utf-8")
        if tool_src:
            tools_path.write_text(before_tools + tool_src, encoding="utf-8")
        new = validator.label(domain, items, d / f"{F}-r{r}.log", c=cand)
        cmp_ = compare(cur_pi, per_item(domain, new))
        keep = cmp_["exact"]["delta"] > 0 and cmp_["harm"]["delta"] <= 0 and cmp_["abstain"]["delta"] <= 0.05
        rec |= {"train": cmp_, "kept": keep}
        if keep:
            s, cur, cur_pi = cand, new, per_item(domain, new)
            _write(d, f"{F}-validator.jsonl", cur)
        elif tool_src:
            tools_path.write_text(before_tools, encoding="utf-8")
        e = cmp_["exact"]
        _say(f"  round {r}: {ch.get('kind')} `{ch.get('question_id')}`: training exact {e['current']} -> {e['candidate']} "
             f"(delta {e['delta']}, {e['changed']} changed), harm delta {cmp_['harm']['delta']}, abstain delta "
             f"{cmp_['abstain']['delta']} -> {'kept (v' + str(cand['version']) + ')' if keep else 'dropped'}")
        hist.append(rec)
    out = {"fit": F, "start": start, "rounds": hist, "card_start": s0.get("version"), "card_fitted": s.get("version")}
    if s is s0:
        _say("fit: no change kept on the training sample; nothing to check")
        tools_path.write_text(tools0, encoding="utf-8")
    else:
        # the held-out check: the fitted version against the starting one, on fresh rows, both at once
        T = loop._next_v(domain)
        loopb.sample(domain, T, pool="pedia-dev", n=n_test)
        test = [json.loads(x) for x in open(d / f"{T}-blind.jsonl", encoding="utf-8")]
        with ThreadPoolExecutor(2) as pool:
            fa = pool.submit(validator.label, domain, test, d / f"{T}-validator.log", False, 600, s0)
            fb = pool.submit(validator.label, domain, test, d / f"{T}-validator-cand.log", False, 600, s)
            a, b = fa.result(), fb.result()
        _write(d, f"{T}-validator.jsonl", a)
        _write(d, f"{T}-validator-cand.jsonl", b)
        held = compare(per_item(domain, a), per_item(domain, b))
        adopt = held["exact"]["delta"] >= 0 and held["harm"]["delta"] <= 0 and held["abstain"]["delta"] <= 0.05
        out |= {"held_out": T, "held": held, "adopted": adopt}
        e, h = held["exact"], held["harm"]
        _say(f"  held-out {T} (n={held['n']}): exact {e['current']} {e['current_ci']} -> {e['candidate']} "
             f"{e['candidate_ci']} (delta {e['delta']} {e['delta_ci']}), harm {h['current']} -> {h['candidate']} "
             f"(delta {h['delta']} {h['delta_ci']}), abstain delta {held['abstain']['delta']} -> "
             f"{'ADOPTED v' + str(s.get('version')) if adopt else 'NOT adopted: v' + str(s0.get('version')) + ' stays'}")
        if adopt:
            path = DOMAINS_DIR / domain / "validator.yaml"
            head = "".join(ln for ln in path.read_text(encoding="utf-8").splitlines(keepends=True) if ln.startswith("#"))
            path.write_text(head + yaml.safe_dump(s, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
            out["commit"] = _commit(f"Validator v{s0.get('version')} -> v{s.get('version')}: fitted on {F} "
                                    f"({sum(1 for x in hist if x.get('kept'))} improver changes kept), held-out {T}: "
                                    f"exact {e['current']} -> {e['candidate']}, delta {e['delta']} {e['delta_ci']}, "
                                    f"n={held['n']}")
        else:
            tools_path.write_text(tools0, encoding="utf-8")
    (d / f"{F}-fit.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.improve")
    ap.add_argument("domain")
    ap.add_argument("--iterations", type=int, default=4)
    ap.add_argument("--misses", type=int, default=60, help="human-round sample per iteration")
    ap.add_argument("--ab", type=int, default=120, help="A/B sample per iteration")
    ap.add_argument("--fit", type=int, default=0, help="fit mode: this many improver rounds on one training sample, "
                                                       "then one held-out check")
    ap.add_argument("--train", type=int, default=120)
    ap.add_argument("--test", type=int, default=120)
    a = ap.parse_args()
    if a.fit:
        print(json.dumps(fit(a.domain, a.fit, a.train, a.test), indent=1, ensure_ascii=False)[-3000:])
        return
    log = []
    for k in range(1, a.iterations + 1):
        log.append(iteration(a.domain, k, a.misses, a.ab))
        (RUNS_DIR / a.domain / "loopb" / "improve-log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False),
                                                                         encoding="utf-8")


if __name__ == "__main__":
    main()
