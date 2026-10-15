"""Armar la página HTML del diagnóstico.

Entra: el diagnóstico (lo escribe Claude: veredicto y porqué de cada herramienta),
el escaneo (lo escribe detect.py: montos y fechas) y el catálogo de alternativas.
Sale: un solo archivo HTML, sin dependencias, que se abre con doble clic.

Todos los montos salen del escaneo. El diagnóstico solo puede pisar un monto
con "monthly" cuando hay una razón (por ejemplo, un plan que ya se canceló).
"""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from .detect import monthly_totals

VERDICTS = {
    "mantener": ("Mantener", "keep"),
    "revisar": ("Revisar", "check"),
    "reemplazar": ("Reemplazar", "cut"),
    "cancelar": ("Cancelar", "cut"),
}
CUT = {"reemplazar", "cancelar"}
MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
STATUSES = ("Probar ya", "Ya lo tienes", "Evaluar", "Para clientes", "No conviene")


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def money(v: float) -> str:
    return f"${v:,.0f}" if v >= 100 or float(v).is_integer() else f"${v:,.2f}"


def _alt_name(a) -> str:
    return a["name"] if isinstance(a, dict) else str(a)


def build_rows(diagnosis: dict, scan: dict) -> list[dict]:
    by_key = {r["key"]: r for r in scan.get("recurring", [])}
    rows = []
    for s in diagnosis.get("subscriptions", []):
        verdict = s.get("verdict", "revisar").lower()
        if verdict not in VERDICTS:
            raise ValueError(f"Veredicto desconocido para {s.get('name')}: {verdict}")
        found = [by_key[k] for k in s.get("keys", []) if k in by_key]
        missing = [k for k in s.get("keys", []) if k not in by_key]
        if missing:
            raise ValueError(f"{s.get('name')}: estas llaves no están en el escaneo: {', '.join(missing)}")
        active = [r for r in found if r["status"] == "activa"]
        monthly = s["monthly"] if "monthly" in s else round(sum(r["monthly_cost"] for r in active), 2)
        rows.append({
            "name": s["name"],
            "monthly": monthly,
            "verdict": verdict,
            "why": s.get("why", ""),
            "alternatives": s.get("alternatives", []),
            "stopped": bool(found) and not active,
            "keys": [r["key"] for r in found],
            "next": min((r["next_expected"] for r in active if r.get("next_expected")), default=None),
        })
    rows.sort(key=lambda r: -r["monthly"])
    return rows


def summary(rows: list[dict]) -> dict:
    total = round(sum(r["monthly"] for r in rows), 2)
    cut = round(sum(r["monthly"] for r in rows if r["verdict"] in CUT), 2)
    return {"total": total, "cut": cut, "year": round(cut * 12, 2),
            "cut_names": [r["name"] for r in rows if r["verdict"] in CUT]}


def _month_label(m: str) -> str:
    y, mo = m.split("-")
    return MONTHS_ES[int(mo) - 1]


def chart(rows: list[dict], scan: dict) -> str:
    keys = {k for r in rows for k in r["keys"]}
    totals = monthly_totals(scan.get("recurring", []), keys)
    months = list(totals)[-12:]
    if len(months) < 2:
        return ""
    peak = max(totals[m] for m in months) or 1
    end = scan.get("period", {}).get("end")
    partial = None
    if end:
        d = date.fromisoformat(end)
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        if (nxt - d).days > 1:
            partial = f"{d.year:04d}-{d.month:02d}"
    bars, labels, aria = [], [], []
    for m in months:
        v = totals[m]
        cls = ' class="partial"' if m == partial else ""
        bars.append(f'<div{cls} style="height:{max(v / peak * 100, 1.5):.1f}%"><span>{money(v)}</span></div>')
        labels.append(f"<span>{_month_label(m)}{'*' if m == partial else ''}</span>")
        aria.append(f"{_month_label(m)} {v:.0f}")
    note = '<p class="note">* Mes en curso: todavía le faltan cargos.</p>' if partial in months else ""
    cols = len(months)
    return (f'<div class="year" role="img" aria-label="Gasto mensual en suscripciones: {e(", ".join(aria))} dólares">'
            f'<div class="bars" style="grid-template-columns:repeat({cols},1fr)">{"".join(bars)}</div>'
            f'<div class="months" aria-hidden="true" style="grid-template-columns:repeat({cols},1fr)">{"".join(labels)}</div>'
            f"</div>{note}")


def directory(catalog: dict, diagnosis: dict, rows: list[dict]) -> list[dict]:
    overrides = diagnosis.get("directory", {})
    savings: dict[str, float] = {}
    for r in rows:
        if r["verdict"] in CUT:
            for a in r["alternatives"]:
                savings[_alt_name(a).lower()] = savings.get(_alt_name(a).lower(), 0) + r["monthly"]
    out = []
    for t in catalog["tools"]:
        o = overrides.get(t["name"], {})
        status = o.get("status", "Probar ya" if t["name"].lower() in savings else "Evaluar")
        if status not in STATUSES:
            status = "Evaluar"
        out.append({**t, "status": status, "note": o.get("note", ""),
                    "saving": round(savings.get(t["name"].lower(), 0), 2)})
    order = {s: i for i, s in enumerate(STATUSES)}
    out.sort(key=lambda t: (order[t["status"]], -t["saving"], t["category"], t["name"]))
    return out


def _alt_links(alts, catalog_urls: dict) -> str:
    if not alts:
        return '<span class="small">—</span>'
    parts = []
    for a in alts:
        name = _alt_name(a)
        url = a.get("url") if isinstance(a, dict) else None
        url = url or catalog_urls.get(name.lower())
        parts.append(f'<a href="{e(url)}" target="_blank" rel="noopener">{e(name)}</a>' if url else e(name))
    return " · ".join(parts)


def render(diagnosis: dict, scan: dict, catalog: dict) -> str:
    rows = build_rows(diagnosis, scan)
    s = summary(rows)
    urls = {t["name"].lower(): t["url"] for t in catalog["tools"]}
    tools = directory(catalog, diagnosis, rows)

    table = []
    for r in rows:
        label, cls = VERDICTS[r["verdict"]]
        extra = ' <span class="small">(sin cobros recientes)</span>' if r["stopped"] else ""
        nxt = f'<div class="small">próximo cobro ~{e(r["next"])}</div>' if r["next"] and r["verdict"] in CUT else ""
        table.append(
            f'<tr><td><div class="tool">{e(r["name"])}</div>{nxt}</td>'
            f'<td class="money">{money(r["monthly"])}{extra}</td>'
            f'<td><span class="pill {cls}">{label}</span></td>'
            f'<td>{e(r["why"])}</td><td>{_alt_links(r["alternatives"], urls)}</td></tr>')

    plan = []
    for phase in diagnosis.get("plan", []):
        items = []
        for it in phase.get("items", []):
            saving = f' <span class="saving">{money(it["saving"])}/mes</span>' if it.get("saving") else ""
            items.append(f'<li><span><strong>{e(it["title"])}</strong>{saving}. {e(it.get("detail", ""))}</span></li>')
        plan.append(f'<div class="phase"><h3>{e(phase.get("when", ""))}</h3><ul>{"".join(items)}</ul></div>')

    findings = "".join(f"<li>{e(f)}</li>" for f in diagnosis.get("findings", []))
    period = scan.get("period") or {}
    title = diagnosis.get("title", "Menos suscripciones")
    cut_sub = " · ".join(s["cut_names"]) or "nada por ahora"
    tools_json = json.dumps(tools, ensure_ascii=False).replace("</", "<\\/")

    return TEMPLATE.format(
        title=e(title),
        eyebrow=e(" · ".join(x for x in ("revisión de suscripciones", diagnosis.get("owner"), diagnosis.get("as_of")) if x)),
        lede=e(diagnosis.get("lede", "")),
        total=money(s["total"]), cut=money(s["cut"]), year=money(s["year"]), cut_sub=e(cut_sub),
        plan_section=(PLAN.format(phases="".join(plan)) if plan else ""),
        rows="".join(table),
        source=e(diagnosis.get("source") or f"Transacciones del {period.get('start', '?')} al {period.get('end', '?')}"),
        not_seen=(f'<p class="note">{e(diagnosis["not_seen"])}</p>' if diagnosis.get("not_seen") else ""),
        chart=chart(rows, scan),
        findings=(f'<ul class="findings">{findings}</ul>' if findings else ""),
        catalog_note=e(catalog.get("note", "")),
        catalog_date=e(catalog.get("as_of", "")),
        tools_json=tools_json,
        statuses=json.dumps({st: c for st, c in zip(STATUSES, ("keep", "have", "check", "where", "cut"))}),
    )


def render_files(diagnosis_path, scan_path, out_path, catalog_path=None) -> Path:
    catalog_path = catalog_path or Path(__file__).with_name("alternatives.json")
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    out = Path(out_path)
    out.write_text(render(load(diagnosis_path), load(scan_path), load(catalog_path)), encoding="utf-8")
    return out


PLAN = """
  <section class="win" aria-labelledby="plan-h">
    <div class="bar"><span class="box"></span><span class="stripes"></span><span class="name">plan.txt</span><span class="stripes"></span></div>
    <div class="body"><h2 id="plan-h">Plan</h2><div class="plan">{phases}</div></div>
  </section>"""

TEMPLATE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Space+Mono:wght@400;700&family=Press+Start+2P&display=swap">
<style>
  :root {{
    --page:#F4F2EB; --ink:#141110; --window:#FFFFFF; --sage:#C8D9C0; --butter:#F4E1A1; --mint:#B8E6B8;
    --pink:#F7C6D2; --muted:#EDEAE1; --muted-fg:#5D5951;
    --serif:"Instrument Serif",Georgia,serif; --mono:"Space Mono",ui-monospace,Menlo,monospace; --pixel:"Press Start 2P",ui-monospace,monospace;
    color-scheme:light;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--page); color:var(--ink); font:15px/1.55 var(--mono); padding:32px 16px 48px; }}
  ::selection {{ background:var(--butter); }}
  .wrap {{ max-width:1120px; margin-inline:auto; display:grid; gap:32px; }}
  header {{ display:grid; gap:10px; }}
  .eyebrow {{ font-family:var(--mono); font-weight:700; font-size:11px; letter-spacing:.1em; text-transform:uppercase; }}
  h1 {{ font-family:var(--serif); font-weight:400; font-size:clamp(44px,7vw,76px); line-height:.95; margin:0; text-wrap:balance; }}
  h1 mark {{ background:var(--butter); color:var(--ink); padding-inline:.12em; }}
  .lede {{ max-width:68ch; margin:0; }}
  .strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }}
  .stat {{ border:2px solid var(--ink); background:var(--window); box-shadow:3px 3px 0 var(--ink); padding:14px 16px; display:grid; gap:6px; }}
  .stat.hot {{ background:var(--butter); }}
  .stat .label {{ font-family:var(--mono); font-weight:700; font-size:11px; text-transform:uppercase; letter-spacing:.06em; line-height:1.6; }}
  .stat .num {{ font-family:var(--serif); font-size:46px; line-height:1; font-variant-numeric:tabular-nums; }}
  .stat .sub {{ color:var(--muted-fg); font-size:13px; }}
  .win {{ border:2px solid var(--ink); background:var(--window); box-shadow:4px 4px 0 var(--ink); min-width:0; }}
  .bar {{ background:var(--sage); border-bottom:2px solid var(--ink); display:flex; align-items:center; gap:10px; padding:7px 10px; }}
  .bar .box {{ width:12px; height:12px; border:2px solid var(--ink); background:var(--window); flex:none; }}
  .bar .stripes {{ flex:1; height:10px; background:repeating-linear-gradient(to bottom,var(--ink) 0 2px,transparent 2px 4px); opacity:.5; }}
  .bar .name {{ font-family:var(--pixel); font-size:9px; white-space:nowrap; }}
  .body {{ padding:18px; display:grid; gap:16px; }}
  h2 {{ font-family:var(--serif); font-weight:400; font-size:34px; line-height:1; margin:0; }}
  .note {{ color:var(--muted-fg); margin:0; max-width:80ch; font-size:13px; }}
  .scroll {{ overflow-x:auto; border:2px solid var(--ink); }}
  table {{ border-collapse:collapse; width:100%; min-width:880px; }}
  th {{ font-family:var(--mono); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; text-align:left; padding:10px; background:var(--muted); border-bottom:2px solid var(--ink); white-space:nowrap; }}
  td {{ padding:10px; border-bottom:1px dashed #BDB6A8; vertical-align:top; font-size:14px; }}
  tr:last-child td {{ border-bottom:0; }}
  td.money, th.money {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  .tool {{ font-family:var(--serif); font-size:21px; line-height:1.1; }}
  a.tool {{ display:inline-block; }}
  .small {{ color:var(--muted-fg); font-size:12px; }}
  td a {{ color:var(--ink); text-decoration-thickness:2px; text-underline-offset:3px; }}
  td a:hover {{ background:var(--butter); }}
  a:focus-visible, button:focus-visible, input:focus-visible {{ outline:3px solid var(--ink); outline-offset:2px; }}
  .pill {{ display:inline-block; font-family:var(--pixel); font-size:8px; text-transform:uppercase; border:2px solid var(--ink); border-radius:999px; padding:5px 8px; white-space:nowrap; line-height:1.3; }}
  .keep {{ background:var(--mint); }} .check {{ background:var(--butter); }} .cut {{ background:var(--ink); color:var(--page); }}
  .have {{ background:var(--pink); }} .where {{ background:var(--window); }}
  .plan {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; }}
  .phase {{ border:2px solid var(--ink); background:var(--page); padding:14px; display:grid; gap:10px; align-content:start; }}
  .phase h3 {{ font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; margin:0; line-height:1.6; }}
  .phase ul {{ list-style:none; margin:0; padding:0; display:grid; gap:10px; }}
  .phase li {{ display:grid; grid-template-columns:18px 1fr; gap:8px; }}
  .phase li::before {{ content:""; width:14px; height:14px; border:2px solid var(--ink); background:var(--window); margin-top:4px; }}
  .phase li strong {{ font-weight:400; background:var(--butter); padding-inline:3px; }}
  .saving {{ color:var(--muted-fg); font-variant-numeric:tabular-nums; }}
  .year {{ display:grid; gap:10px; }}
  .bars {{ display:grid; gap:8px; align-items:end; height:180px; border-bottom:2px solid var(--ink); padding-top:24px; }}
  .bars div {{ position:relative; background:var(--sage); border:2px solid var(--ink); border-bottom:0; }}
  .bars div.partial {{ background:repeating-linear-gradient(45deg,var(--sage) 0 6px,var(--window) 6px 10px); }}
  .bars div span {{ position:absolute; top:-22px; left:50%; transform:translateX(-50%); font-size:12px; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  .months {{ display:grid; gap:8px; font-family:var(--mono); font-weight:700; font-size:11px; text-transform:uppercase; text-align:center; }}
  .findings {{ margin:0; padding-left:20px; display:grid; gap:8px; max-width:80ch; }}
  .controls {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
  .chip {{ font:14px var(--mono); background:var(--window); color:var(--ink); border:2px solid var(--ink); box-shadow:3px 3px 0 var(--ink); padding:3px 10px; cursor:pointer; }}
  .chip[aria-pressed="true"] {{ background:var(--ink); color:var(--page); }}
  .chip:active {{ transform:translate(3px,3px); box-shadow:none; }}
  .search {{ font:14px var(--mono); border:2px solid var(--ink); background:var(--window); color:var(--ink); padding:5px 10px; min-width:0; flex:1 1 220px; max-width:340px; }}
  .count {{ font-family:var(--mono); font-size:11px; text-transform:uppercase; color:var(--muted-fg); }}
  .empty {{ padding:18px; color:var(--muted-fg); }}
  footer {{ color:var(--muted-fg); font-size:12px; max-width:80ch; }}
  @media (max-width:520px) {{ .bars div span {{ font-size:9px; }} }}
  @media (prefers-reduced-motion:reduce) {{ .chip:active {{ transform:none; }} }}
</style></head>
<body><div class="wrap">
  <header>
    <div class="eyebrow">{eyebrow}</div>
    <h1>{title}</h1>
    <p class="lede">{lede}</p>
  </header>
  <section class="strip" aria-label="Resumen">
    <div class="stat"><div class="label">Suscripciones al mes</div><div class="num">{total}</div><div class="sub">lo que se repite hoy</div></div>
    <div class="stat hot"><div class="label">Lo que puedes cortar</div><div class="num">{cut}<span style="font-size:22px">/mes</span></div><div class="sub">{cut_sub}</div></div>
    <div class="stat"><div class="label">En un año</div><div class="num">{year}</div><div class="sub">si cortas todo lo marcado</div></div>
  </section>
  {plan_section}
  <section class="win" aria-labelledby="subs-h">
    <div class="bar"><span class="box"></span><span class="stripes"></span><span class="name">tus_suscripciones.db</span><span class="stripes"></span></div>
    <div class="body">
      <h2 id="subs-h">Tus suscripciones</h2>
      <p class="note">{source}. Monto = lo que cobró el último mes.</p>
      <div class="scroll"><table>
        <thead><tr><th>Herramienta</th><th class="money">Al mes</th><th>Veredicto</th><th>Por qué</th><th>Alternativa</th></tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
      {not_seen}
    </div>
  </section>
  <section class="win" aria-labelledby="year-h">
    <div class="bar"><span class="box"></span><span class="stripes"></span><span class="name">mes_a_mes.txt</span><span class="stripes"></span></div>
    <div class="body"><h2 id="year-h">Mes a mes</h2>{chart}{findings}</div>
  </section>
  <section class="win" aria-labelledby="dir-h">
    <div class="bar"><span class="box"></span><span class="stripes"></span><span class="name">directorio_open_source.db</span><span class="stripes"></span></div>
    <div class="body">
      <h2 id="dir-h">Directorio open source</h2>
      <p class="note">«Tu compu» y «Navegador» = se instala y listo, cero costo. «Servidor» = tiene que estar prendido siempre: un servidor de ~$5–10/mes o la versión en la nube de la misma empresa.</p>
      <div class="controls" role="group" aria-label="Filtros">
        <button class="chip" data-f="all" aria-pressed="true">Todas</button>
        <button class="chip" data-f="try" aria-pressed="false">Probar ya</button>
        <button class="chip" data-f="pay" aria-pressed="false">Te ahorra plata</button>
        <button class="chip" data-f="local" aria-pressed="false">Sin servidor</button>
        <button class="chip" data-f="server" aria-pressed="false">Necesita servidor</button>
        <button class="chip" data-f="have" aria-pressed="false">Ya lo tienes</button>
        <input class="search" id="q" type="search" placeholder="Buscar: video, firmas, Zapier…" aria-label="Buscar herramienta">
        <span class="count" id="count"></span>
      </div>
      <div class="scroll"><table>
        <thead><tr><th>Herramienta</th><th>Reemplaza</th><th>Qué hace</th><th>Dónde corre</th><th>Estado</th><th>Nota</th></tr></thead>
        <tbody id="dir"></tbody>
      </table><div class="empty" id="empty" hidden>Nada coincide. Prueba otra palabra o quita el filtro.</div></div>
    </div>
  </section>
  <footer>Hecho con Menos Suscripciones, de Nerd Heart. Directorio revisado el {catalog_date}. {catalog_note}</footer>
</div>
<script>
  var TOOLS = {tools_json};
  var ST = {statuses};
  var tbody = document.getElementById("dir"), countEl = document.getElementById("count"),
      emptyEl = document.getElementById("empty"), q = document.getElementById("q"),
      chips = Array.prototype.slice.call(document.querySelectorAll(".chip")), filter = "all";
  try {{ filter = localStorage.getItem("ms-filter") || "all"; }} catch (err) {{}}
  if (!chips.some(function (c) {{ return c.dataset.f === filter; }})) filter = "all";
  function esc(s) {{ return String(s).replace(/[&<>"]/g, function (c) {{ return {{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]; }}); }}
  function matches(t) {{
    switch (filter) {{
      case "try": return t.status === "Probar ya";
      case "pay": return t.saving > 0;
      case "local": return t.runs !== "Servidor";
      case "server": return t.runs === "Servidor";
      case "have": return t.status === "Ya lo tienes";
      default: return true;
    }}
  }}
  function render() {{
    var term = q.value.trim().toLowerCase();
    var rows = TOOLS.filter(function (t) {{
      if (!matches(t)) return false;
      return !term || [t.name, t.replaces.join(" "), t.category, t.what, t.runs, t.status, t.note].join(" ").toLowerCase().indexOf(term) !== -1;
    }});
    tbody.innerHTML = rows.map(function (t) {{
      var note = (t.saving ? '<span class="saving">Ahorra $' + t.saving + '/mes.</span> ' : '') + esc(t.note);
      return '<tr><td><a class="tool" href="' + esc(t.url) + '" target="_blank" rel="noopener">' + esc(t.name) + '</a><div class="small">' + esc(t.category) + '</div></td>' +
        '<td>' + esc(t.replaces.join(", ")) + '</td><td>' + esc(t.what) + '</td>' +
        '<td><span class="pill where">' + esc(t.runs) + '</span></td>' +
        '<td><span class="pill ' + ST[t.status] + '">' + esc(t.status) + '</span></td>' +
        '<td>' + (note.trim() ? note : '<span class="small">—</span>') + '</td></tr>';
    }}).join("");
    emptyEl.hidden = rows.length > 0;
    countEl.textContent = rows.length + " de " + TOOLS.length;
    chips.forEach(function (c) {{ c.setAttribute("aria-pressed", String(c.dataset.f === filter)); }});
  }}
  chips.forEach(function (c) {{ c.addEventListener("click", function () {{
    filter = c.dataset.f; try {{ localStorage.setItem("ms-filter", filter); }} catch (err) {{}} render(); }}); }});
  q.addEventListener("input", render);
  render();
</script>
</body></html>
"""
