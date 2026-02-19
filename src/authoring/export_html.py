"""
Export dialogs.json to a readable HTML report for reviews/printing.

Usage:
  - Default input: assets/dialogs/dialogs.json
  - Default output: web/authoring/dialogs_report.html

  python src/authoring/export_html.py
  python src/authoring/export_html.py path/to/dialogs.json path/to/output.html
"""
from __future__ import annotations

import json
import sys
import os
from collections import defaultdict
from html import escape


def load_dialogs(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("dialogs.json must be a list of dialogs")
    # ensure unique ids
    ids = [d.get("id") for d in data]
    dups = {i for i in ids if ids.count(i) > 1}
    if dups:
        print(f"Warning: duplicate dialog ids found: {sorted(dups)}")
    return data


def render_moves(moves: list[dict]) -> str:
    rows = []
    for m in moves or []:
        t = escape(str(m.get("type", "")))
        branch = m.get("branch")
        branch_s = f"<code class=branch>{escape(str(branch))}</code>" if branch not in (None, "") else ""
        text = m.get("text")
        audio = m.get("audio")
        options = m.get("options")
        next_map = m.get("next")
        set_var = m.get("set_variable")
        add_int = m.get("add_interest")
        add_from_ans = m.get("add_interest_from_answer")
        add_from_var = m.get("add_interest_from_variable")

        details = []
        if text:
            details.append(f"<div class=mv-text>{escape(text)}</div>")
        if audio:
            details.append(f"<div class=mv-audio>audio: <code>{escape(audio)}</code></div>")
        if options:
            details.append("<div class=mv-options>options: " + ", ".join(f"<code>{escape(str(o))}</code>" for o in options) + "</div>")
        if set_var:
            details.append(f"<div class=mv-set>set_variable: <code>{escape(set_var)}</code></div>")
        if add_int:
            details.append(f"<div class=mv-add>add_interest: <code>{escape(add_int)}</code></div>")
        if add_from_ans:
            details.append("<div class=mv-add>add_interest_from_answer: <code>true</code></div>")
        if add_from_var:
            details.append("<div class=mv-add>add_interest_from_variable: <code>true</code></div>")
        if next_map:
            try:
                next_json = json.dumps(next_map, ensure_ascii=False)
            except Exception:
                next_json = escape(str(next_map))
            details.append(f"<div class=mv-next>next: <code>{escape(next_json)}</code></div>")

        rows.append(
            """
            <div class="move">
              <div class="mv-head"><span class="mv-type">{t}</span> {branch}</div>
              <div class="mv-body">{details}</div>
            </div>
            """.format(
                t=t, branch=branch_s, details="".join(details)
            )
        )
    return "\n".join(rows)


def render_dialog(d: dict) -> str:
    did = escape(str(d.get("id", "")))
    dtype = escape(str(d.get("type", "")))
    meta_bits = []
    if dtype == "functional":
        ft = d.get("functional_type")
        if ft:
            meta_bits.append(f"functional_type: <code>{escape(str(ft))}</code>")
    if dtype == "narrative":
        thr = d.get("thread")
        pos = d.get("position")
        if thr:
            meta_bits.append(f"thread: <code>{escape(str(thr))}</code>")
        if pos is not None:
            meta_bits.append(f"position: <code>{escape(str(pos))}</code>")
    if dtype == "chitchat":
        theme = d.get("theme")
        if theme:
            meta_bits.append(f"theme: <code>{escape(str(theme))}</code>")
        topics = d.get("topics") or []
        if topics:
            meta_bits.append("topics: " + ", ".join(f"<code>{escape(str(t))}</code>" for t in topics))

    deps = d.get("dependencies") or []
    vdeps = d.get("variable_dependencies") or []
    if deps:
        meta_bits.append("dependencies: " + ", ".join(f"<code>{escape(str(x))}</code>" for x in deps))
    if vdeps:
        # support strings or {variable, required}
        def vd_to_str(v):
            if isinstance(v, dict):
                req = v.get("required")
                return f"{v.get('variable')}" + (" (required)" if req else "")
            return str(v)
        meta_bits.append("variable_dependencies: " + ", ".join(f"<code>{escape(vd_to_str(x))}</code>" for x in vdeps))

    moves_html = render_moves(d.get("moves") or [])

    return f"""
    <article class="dialog">
      <h4><code>{did}</code> <span class="dtype">[{dtype}]</span></h4>
      <div class="meta">{' • '.join(meta_bits) if meta_bits else ''}</div>
      <div class="moves">{moves_html}</div>
    </article>
    """


def build_html(dialogs: list[dict]) -> str:
    # group
    functionals = [d for d in dialogs if d.get("type") == "functional"]
    narratives = [d for d in dialogs if d.get("type") == "narrative"]
    chitchats = [d for d in dialogs if d.get("type") == "chitchat"]

    narratives_by_thread = defaultdict(list)
    for d in narratives:
        narratives_by_thread[d.get("thread")].append(d)
    for thr in narratives_by_thread:
        narratives_by_thread[thr].sort(key=lambda x: (x.get("position") is None, x.get("position", 0)))

    chitchats_by_theme = defaultdict(list)
    for d in chitchats:
        chitchats_by_theme[d.get("theme")].append(d)
    for th in chitchats_by_theme:
        chitchats_by_theme[th].sort(key=lambda x: x.get("id", ""))

    def section(title: str, body: str) -> str:
        return f"<section><h2>{escape(title)}</h2>{body}</section>"

    functional_html = "".join(render_dialog(d) for d in sorted(functionals, key=lambda x: x.get("functional_type", "") + "_" + x.get("id", "")))

    narrative_html = []
    for thr in sorted(narratives_by_thread.keys(), key=lambda s: s or ""):
        items = "".join(render_dialog(d) for d in narratives_by_thread[thr])
        head = f"<h3>Thread: <code>{escape(str(thr))}</code></h3>" if thr else ""
        narrative_html.append(f"<div class=thread>{head}{items}</div>")

    chitchat_html = []
    for th in sorted(chitchats_by_theme.keys(), key=lambda s: s or ""):
        items = "".join(render_dialog(d) for d in chitchats_by_theme[th])
        head = f"<h3>Theme: <code>{escape(str(th))}</code></h3>" if th else ""
        chitchat_html.append(f"<div class=theme>{head}{items}</div>")

    style = """
    <style>
      body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:#0b0f14;color:#e7eefb;margin:0;padding:24px}
      h1,h2,h3,h4{margin:0 0 8px 0}
      h2{margin-top:24px;border-bottom:1px solid #233046;padding-bottom:6px}
      section{margin-bottom:24px}
      .dialog{border:1px solid #233046;border-radius:8px;margin:12px 0;padding:12px;background:#121821}
      .dtype{color:#89a1bd;font-weight:normal}
      .meta{color:#89a1bd;font-size:12px;margin-bottom:8px}
      .moves{display:flex;flex-direction:column;gap:8px}
      .move{border:1px solid #233046;border-radius:6px}
      .mv-head{background:#0f1623;padding:6px 8px}
      .mv-type{background:#4ea1ff;color:#001229;padding:1px 6px;border-radius:999px;font-size:12px}
      .branch{color:#89a1bd}
      .mv-body{padding:8px 10px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}
      code{background:#0f1623;border:1px solid #233046;border-radius:4px;padding:0 4px}
      .thread,.theme{margin:8px 0}
    </style>
    """

    html = f"""
    <!doctype html>
    <html lang=\"en\">\n<meta charset=\"utf-8\">\n<title>Dialogs Report</title>
    {style}
    <h1>Dialogs Report</h1>
    {section('Functional', functional_html)}
    {section('Narrative', ''.join(narrative_html))}
    {section('Chitchat', ''.join(chitchat_html))}
    """
    return html


def main(argv: list[str]) -> int:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    default_in = os.path.join(repo_root, "assets", "dialogs", "dialogs.json")
    default_out = os.path.join(repo_root, "web", "authoring", "dialogs_report.html")

    in_path = argv[1] if len(argv) > 1 else default_in
    out_path = argv[2] if len(argv) > 2 else default_out

    dialogs = load_dialogs(in_path)
    html = build_html(dialogs)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote HTML report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
