"""Armar la página HTML del diagnóstico, en español o en inglés.

Entra: el diagnóstico (lo escribe Claude: veredicto y porqué de cada herramienta),
el escaneo (lo escribe detect.py: montos y fechas) y el catálogo de alternativas.
Sale: un solo archivo HTML, sin dependencias, que se abre con doble clic.

Todos los montos salen del escaneo. El diagnóstico solo puede pisar un monto
con "monthly" cuando hay una razón (por ejemplo, un plan que ya se canceló).
El idioma lo pone el diagnóstico con "lang": "es" (default) o "en".
"""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from .detect import monthly_totals

HERE = Path(__file__).parent
NEWSLETTER_URL = "https://valatnerdheart.substack.com"
AUTHOR_URL = "https://www.valeriaalfuzzi.com"

# Veredictos: llave canónica → clase CSS. Se aceptan también en español.
VERDICTS = {"keep": "keep", "review": "check", "replace": "cut", "cancel": "cut"}
VERDICT_ALIASES = {"mantener": "keep", "revisar": "review", "reemplazar": "replace", "cancelar": "cancel"}
CUT = {"replace", "cancel"}

# Estados del directorio, en el orden en que se muestran.
STATUSES = {"try": "keep", "have": "have", "evaluate": "check", "clients": "where", "skip": "cut"}
STATUS_ALIASES = {"probar ya": "try", "ya lo tienes": "have", "evaluar": "evaluate",
                  "para clientes": "clients", "no conviene": "skip", "try now": "try",
                  "you have it": "have", "for clients": "clients", "not worth it": "skip"}

T = {
    "es": {
        "title": "Menos suscripciones",
        "kicker": "revisión de suscripciones",
        "verdict": {"keep": "Mantener", "review": "Revisar", "replace": "Reemplazar", "cancel": "Cancelar"},
        "status": {"try": "Probar ya", "have": "Ya lo tienes", "evaluate": "Evaluar", "clients": "Para clientes", "skip": "No conviene"},
        "runs": {"computer": "Tu compu", "browser": "Navegador", "server": "Servidor"},
        "category": {"screen": "Grabación de pantalla", "video": "Video", "audio": "Audio y voz", "design": "Diseño e imagen",
                     "meetings": "Reuniones", "apps": "Construir apps", "marketing": "Marketing y redes",
                     "sales": "Ventas y admin", "automation": "Automatización", "security": "Seguridad", "files": "Archivos"},
        "months": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
        "summary": "Resumen", "stat_total": "Suscripciones al mes", "stat_total_sub": "lo que se repite hoy",
        "stat_cut": "Lo que puedes cortar", "per_month": "/mes", "nothing": "nada por ahora",
        "stat_year": "En un año", "stat_year_sub": "si cortas todo lo marcado",
        "plan": "Plan", "subs": "Tus suscripciones", "source_note": "{source}. Monto = lo que cobró el último mes.",
        "default_source": "Transacciones del {start} al {end}",
        "th_tool": "Herramienta", "th_month": "Al mes", "th_verdict": "Veredicto", "th_why": "Por qué", "th_alt": "Alternativa",
        "stopped": "(sin cobros recientes)", "next": "próximo cobro ~{date}",
        "by_month": "Mes a mes", "chart_aria": "Gasto mensual en suscripciones: {values} dólares",
        "partial": "* Mes en curso: todavía le faltan cargos.",
        "directory": "Directorio open source",
        "directory_note": "«Tu compu» y «Navegador» = se instala y listo, cero costo. «Servidor» = tiene que estar prendido siempre: un servidor de ~$5–10/mes o la versión en la nube de la misma empresa.",
        "filters": "Filtros", "f_all": "Todas", "f_try": "Probar ya", "f_pay": "Te ahorra plata", "f_local": "Sin servidor",
        "f_server": "Necesita servidor", "f_have": "Ya lo tienes",
        "search": "Buscar: video, firmas, Zapier…", "search_label": "Buscar herramienta",
        "th_replaces": "Reemplaza", "th_what": "Qué hace", "th_runs": "Dónde corre", "th_status": "Estado", "th_note": "Nota",
        "empty": "Nada coincide. Prueba otra palabra o quita el filtro.",
        "saves": "Ahorra ${n}/mes.", "count": "{n} de {total}",
        "footer": ('Hecho con <a href="https://github.com/valalfuzzi/menos-suscripciones">Menos suscripciones</a>, '
                   'de <a href="{author}">Valeria Alfuzzi</a>. ¿Quieres más herramientas así? '
                   'Llegan primero a <a href="{newsletter}">su newsletter</a>, gratis. Directorio revisado el {date}. {note}'),
    },
    "en": {
        "title": "Fewer subscriptions",
        "kicker": "subscription review",
        "verdict": {"keep": "Keep", "review": "Review", "replace": "Replace", "cancel": "Cancel"},
        "status": {"try": "Try now", "have": "You have it", "evaluate": "Evaluate", "clients": "For clients", "skip": "Not worth it"},
        "runs": {"computer": "Your computer", "browser": "Browser", "server": "Server"},
        "category": {"screen": "Screen recording", "video": "Video", "audio": "Audio & voice", "design": "Design & images",
                     "meetings": "Meetings", "apps": "App building", "marketing": "Marketing & social",
                     "sales": "Sales & admin", "automation": "Automation", "security": "Security", "files": "Files"},
        "months": ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        "summary": "Summary", "stat_total": "Subscriptions per month", "stat_total_sub": "what repeats today",
        "stat_cut": "What you can cut", "per_month": "/mo", "nothing": "nothing for now",
        "stat_year": "Over a year", "stat_year_sub": "if you cut everything marked",
        "plan": "Plan", "subs": "Your subscriptions", "source_note": "{source}. Amount = last month's charge.",
        "default_source": "Transactions from {start} to {end}",
        "th_tool": "Tool", "th_month": "Per month", "th_verdict": "Verdict", "th_why": "Why", "th_alt": "Alternative",
        "stopped": "(no recent charges)", "next": "next charge ~{date}",
        "by_month": "Month by month", "chart_aria": "Monthly subscription spend: {values} dollars",
        "partial": "* Current month: some charges haven't landed yet.",
        "directory": "Open-source directory",
        "directory_note": "“Your computer” and “Browser” = install and go, zero cost. “Server” = has to stay on: a ~$5–10/month server, or the same company's cloud version.",
        "filters": "Filters", "f_all": "All", "f_try": "Try now", "f_pay": "Saves money", "f_local": "No server",
        "f_server": "Needs a server", "f_have": "You have it",
        "search": "Search: video, signatures, Zapier…", "search_label": "Search tools",
        "th_replaces": "Replaces", "th_what": "What it does", "th_runs": "Runs on", "th_status": "Status", "th_note": "Note",
        "empty": "Nothing matches. Try another word or clear the filter.",
        "saves": "Saves ${n}/mo.", "count": "{n} of {total}",
        "footer": ('Made with <a href="https://github.com/valalfuzzi/menos-suscripciones">Menos suscripciones</a> '
                   'by <a href="{author}">Valeria Alfuzzi</a>. Want more tools like this? '
                   'They land first in <a href="{newsletter}">her newsletter</a> (in Spanish), free. Directory checked {date}. {note}'),
    },
}


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def money(v: float) -> str:
    return f"${v:,.0f}" if v >= 100 or float(v).is_integer() else f"${v:,.2f}"


def _alt_name(a) -> str:
    return a["name"] if isinstance(a, dict) else str(a)


def _lang(diagnosis: dict) -> str:
    lang = str(diagnosis.get("lang", "es")).lower()[:2]
    return lang if lang in T else "es"


def _text(value, lang: str) -> str:
    """El catálogo trae {"es": …, "en": …}; el diagnóstico, texto plano."""
    if isinstance(value, dict):
        return value.get(lang) or value.get("es") or next(iter(value.values()), "")
    return value or ""


def build_rows(diagnosis: dict, scan: dict) -> list[dict]:
    by_key = {r["key"]: r for r in scan.get("recurring", [])}
    rows = []
    for s in diagnosis.get("subscriptions", []):
        raw = str(s.get("verdict", "review")).lower()
        verdict = VERDICT_ALIASES.get(raw, raw)
        if verdict not in VERDICTS:
            raise ValueError(f"Veredicto desconocido para {s.get('name')}: {raw}")
        missing = [k for k in s.get("keys", []) if k not in by_key]
        if missing:
            raise ValueError(f"{s.get('name')}: estas llaves no están en el escaneo: {', '.join(missing)}")
        found = [by_key[k] for k in s.get("keys", [])]
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


def chart(rows: list[dict], scan: dict, t: dict) -> str:
    keys = {k for r in rows for k in r["keys"]}
    totals = monthly_totals(scan.get("recurring", []), keys)
    months = list(totals)[-12:]
    if len(months) < 2:
        return ""
    peak = max(totals[m] for m in months) or 1
    end = (scan.get("period") or {}).get("end")
    partial = None
    if end:
        d = date.fromisoformat(end)
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        if (nxt - d).days > 1:
            partial = f"{d.year:04d}-{d.month:02d}"
    label = lambda m: t["months"][int(m.split("-")[1]) - 1]
    bars, labels, aria = [], [], []
    for m in months:
        v = totals[m]
        cls = ' class="partial"' if m == partial else ""
        bars.append(f'<div{cls} style="height:{max(v / peak * 100, 1.5):.1f}%"><span>{money(v)}</span></div>')
        labels.append(f"<span>{label(m)}{'*' if m == partial else ''}</span>")
        aria.append(f"{label(m)} {v:.0f}")
    note = f'<p class="note">{e(t["partial"])}</p>' if partial in months else ""
    cols = len(months)
    return (f'<div class="year" role="img" aria-label="{e(t["chart_aria"].format(values=", ".join(aria)))}">'
            f'<div class="bars" style="grid-template-columns:repeat({cols},1fr)">{"".join(bars)}</div>'
            f'<div class="months" aria-hidden="true" style="grid-template-columns:repeat({cols},1fr)">{"".join(labels)}</div>'
            f"</div>{note}")


def directory(catalog: dict, diagnosis: dict, rows: list[dict]) -> list[dict]:
    lang = _lang(diagnosis)
    t = T[lang]
    overrides = {k.lower(): v for k, v in diagnosis.get("directory", {}).items()}
    savings: dict[str, float] = {}
    for r in rows:
        if r["verdict"] in CUT:
            for a in r["alternatives"]:
                key = _alt_name(a).lower()
                savings[key] = round(savings.get(key, 0) + r["monthly"], 2)
    out = []
    for tool in catalog["tools"]:
        o = overrides.get(tool["name"].lower(), {})
        raw = str(o.get("status", "")).lower()
        status = STATUS_ALIASES.get(raw, raw)
        if status not in STATUSES:
            status = "try" if tool["name"].lower() in savings else "evaluate"
        out.append({
            "name": tool["name"], "url": tool["url"], "replaces": tool["replaces"],
            "what": _text(tool["what"], lang),
            "category": t["category"].get(tool["category"], tool["category"]),
            "runs": tool["runs"], "runs_label": t["runs"].get(tool["runs"], tool["runs"]),
            "status": status, "status_label": t["status"][status], "status_class": STATUSES[status],
            "note": o.get("note", ""), "saving": savings.get(tool["name"].lower(), 0),
        })
    order = {s: i for i, s in enumerate(STATUSES)}
    out.sort(key=lambda x: (order[x["status"]], -x["saving"], x["category"], x["name"]))
    return out


def _alt_links(alts, catalog_urls: dict) -> str:
    if not alts:
        return '<span class="small">—</span>'
    parts = []
    for a in alts:
        name = _alt_name(a)
        url = (a.get("url") if isinstance(a, dict) else None) or catalog_urls.get(name.lower())
        parts.append(f'<a href="{e(url)}" target="_blank" rel="noopener">{e(name)}</a>' if url else e(name))
    return " · ".join(parts)


def _window(file_name: str, heading_id: str, heading: str, body: str) -> str:
    return (f'<section class="win" aria-labelledby="{heading_id}">'
            f'<div class="bar"><span class="box"></span><span class="stripes"></span><span class="name">{file_name}</span>'
            f'<span class="stripes"></span></div><div class="body"><h2 id="{heading_id}">{e(heading)}</h2>{body}</div></section>')


def render(diagnosis: dict, scan: dict, catalog: dict) -> str:
    lang = _lang(diagnosis)
    t = T[lang]
    rows = build_rows(diagnosis, scan)
    s = summary(rows)
    urls = {x["name"].lower(): x["url"] for x in catalog["tools"]}
    tools = directory(catalog, diagnosis, rows)
    period = scan.get("period") or {}

    table = []
    for r in rows:
        extra = f' <span class="small">{e(t["stopped"])}</span>' if r["stopped"] else ""
        nxt = f'<div class="small">{e(t["next"].format(date=r["next"]))}</div>' if r["next"] and r["verdict"] in CUT else ""
        table.append(
            f'<tr><td><div class="tool">{e(r["name"])}</div>{nxt}</td>'
            f'<td class="money">{money(r["monthly"])}{extra}</td>'
            f'<td><span class="pill {VERDICTS[r["verdict"]]}">{e(t["verdict"][r["verdict"]])}</span></td>'
            f'<td>{e(r["why"])}</td><td>{_alt_links(r["alternatives"], urls)}</td></tr>')

    phases = []
    for phase in diagnosis.get("plan", []):
        items = []
        for it in phase.get("items", []):
            saving = f' <span class="saving">{money(it["saving"])}{t["per_month"]}</span>' if it.get("saving") else ""
            items.append(f'<li><span><strong>{e(it["title"])}</strong>{saving}. {e(it.get("detail", ""))}</span></li>')
        phases.append(f'<div class="phase"><h3>{e(phase.get("when", ""))}</h3><ul>{"".join(items)}</ul></div>')

    source = diagnosis.get("source") or t["default_source"].format(start=period.get("start", "?"), end=period.get("end", "?"))
    findings = "".join(f"<li>{e(f)}</li>" for f in diagnosis.get("findings", []))
    not_seen = f'<p class="note">{e(diagnosis["not_seen"])}</p>' if diagnosis.get("not_seen") else ""
    money_cls = ' class="money"'
    th = lambda *keys: "".join(f'<th{money_cls if k == "th_month" else ""}>{e(t[k])}</th>' for k in keys)
    chips = "".join(f'<button class="chip" data-f="{f}" aria-pressed="{str(f == "all").lower()}">{e(t["f_" + f])}</button>'
                    for f in ("all", "try", "pay", "local", "server", "have"))
    data = json.dumps({"tools": tools, "t": {"saves": t["saves"], "count": t["count"]}}, ensure_ascii=False).replace("</", "<\\/")
    footer = t["footer"].format(author=AUTHOR_URL, newsletter=NEWSLETTER_URL, date=e(catalog.get("as_of", "")),
                                note=e(_text(catalog.get("note", ""), lang)))

    parts = [
        f'<header><div class="eyebrow">{e(" · ".join(x for x in (t["kicker"], diagnosis.get("owner"), diagnosis.get("as_of")) if x))}</div>',
        f'<h1>{e(diagnosis.get("title") or t["title"])}</h1><p class="lede">{e(diagnosis.get("lede", ""))}</p></header>',
        f'<section class="strip" aria-label="{e(t["summary"])}">',
        f'<div class="stat"><div class="label">{e(t["stat_total"])}</div><div class="num">{money(s["total"])}</div><div class="sub">{e(t["stat_total_sub"])}</div></div>',
        f'<div class="stat hot"><div class="label">{e(t["stat_cut"])}</div><div class="num">{money(s["cut"])}<span style="font-size:22px">{t["per_month"]}</span></div>'
        f'<div class="sub">{e(" · ".join(s["cut_names"]) or t["nothing"])}</div></div>',
        f'<div class="stat"><div class="label">{e(t["stat_year"])}</div><div class="num">{money(s["year"])}</div><div class="sub">{e(t["stat_year_sub"])}</div></div></section>',
        _window("plan.txt", "plan-h", t["plan"], f'<div class="plan">{"".join(phases)}</div>') if phases else "",
        _window("subscriptions.db", "subs-h", t["subs"],
                f'<p class="note">{e(t["source_note"].format(source=source))}</p>'
                f'<div class="scroll"><table><thead><tr>{th("th_tool", "th_month", "th_verdict", "th_why", "th_alt")}</tr></thead>'
                f'<tbody>{"".join(table)}</tbody></table></div>{not_seen}'),
        _window("by_month.txt", "year-h", t["by_month"],
                chart(rows, scan, t) + (f'<ul class="findings">{findings}</ul>' if findings else "")),
        _window("open_source.db", "dir-h", t["directory"],
                f'<p class="note">{e(t["directory_note"])}</p>'
                f'<div class="controls" role="group" aria-label="{e(t["filters"])}">{chips}'
                f'<input class="search" id="q" type="search" placeholder="{e(t["search"])}" aria-label="{e(t["search_label"])}">'
                f'<span class="count" id="count"></span></div>'
                f'<div class="scroll"><table><thead><tr>{th("th_tool", "th_replaces", "th_what", "th_runs", "th_status", "th_note")}</tr></thead>'
                f'<tbody id="dir"></tbody></table><div class="empty" id="empty" hidden>{e(t["empty"])}</div></div>'),
        f"<footer>{footer}</footer>",
    ]
    return (f'<!doctype html>\n<html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(diagnosis.get("title") or t["title"])}</title>'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Space+Mono:wght@400;700&family=Press+Start+2P&display=swap">'
            f'<style>{(HERE / "page.css").read_text(encoding="utf-8")}</style></head>'
            f'<body><div class="wrap">{"".join(parts)}</div>'
            f'<script type="application/json" id="data">{data}</script>'
            f'<script>{(HERE / "page.js").read_text(encoding="utf-8")}</script></body></html>\n')


def render_files(diagnosis_path, scan_path, out_path, catalog_path=None) -> Path:
    catalog_path = catalog_path or HERE / "alternatives.json"
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    out = Path(out_path)
    out.write_text(render(load(diagnosis_path), load(scan_path), load(catalog_path)), encoding="utf-8")
    return out
