"""Encontrar los cargos que se repiten.

La unidad es el mes, no el cargo: un comercio que cobra en dos o más meses
seguidos es una suscripción, cobre una vez o cinco veces por mes. Así quedan
bien los casos que rompen la detección por intervalos: dos planes del mismo
proveedor, cobro por uso (Slack por miembro activo) y recargas de créditos.

Python hace toda la aritmética. El diagnóstico (qué se queda y qué se corta)
lo decide quien lee el resultado, no este archivo.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median

from .loaders import Charge

# Procesadores de pago: lo que importa es lo que viene después del asterisco.
_PROCESSORS = {"paypal", "pp", "sq", "tst", "paddle", "paddle.net", "fs", "sp", "2co", "stripe", "dlocal", "ebanx"}
_NOISE_WORDS = {"inc", "llc", "ltd", "co", "corp", "the", "com", "www", "subscription", "subscr", "suscripcion",
                "suscripción", "payment", "pago", "purchase", "compra", "pos", "recurring", "monthly", "billing",
                "usd", "us", "ca", "ny", "sf", "help", "bill"}


def merchant_key(description: str) -> str:
    s = description.lower().strip()
    if "*" in s:
        before, _, after = s.partition("*")
        # 'PADDLE.NET* CAPCUT' → capcut · 'GOOGLE *WORKSPACE' → google workspace
        s = after if before.strip() in _PROCESSORS or not before.strip() else f"{before} {after}"
    s = re.sub(r"https?://", " ", s)
    s = re.sub(r"\.(com|net|io|ai|app|co|org|so|us)\b", " ", s)
    # Palabras con números son referencias o teléfonos ('T0123ABC', '888-799-9666'), no el nombre.
    s = " ".join(w for w in s.split() if not re.search(r"\d", w))
    s = re.sub(r"[^a-záéíóúñü ]+", " ", s)
    words = [w for w in s.split() if w not in _NOISE_WORDS and len(w) > 1]
    return " ".join(words[:3]) or description.lower().strip()


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_index(m: str) -> int:
    y, mo = m.split("-")
    return int(y) * 12 + int(mo)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


def _display_name(descriptions: list[str]) -> str:
    name = Counter(descriptions).most_common(1)[0][0]
    return name.title() if name.isupper() else name


def detect(charges: list[Charge], min_one_off: float = 10.0) -> dict:
    if not charges:
        return {"period": None, "n_transactions": 0, "recurring": [], "one_offs": [], "charges_by_month": {},
                "warnings": ["No hay transacciones."]}
    start = min(c.date for c in charges)
    end = max(c.date for c in charges)

    groups: dict[str, list[Charge]] = defaultdict(list)
    for c in charges:
        groups[merchant_key(c.description)].append(c)

    recurring, one_offs = [], []
    for key, items in groups.items():
        out = [c for c in items if c.amount < 0]
        if not out:
            continue  # solo entradas de plata: es ingreso, no gasto
        net = sum(c.amount for c in items)
        if net >= 0:
            continue  # te devolvieron todo, o es un cliente que te paga
        by_month: dict[str, float] = defaultdict(float)
        for c in items:
            by_month[_month(c.date)] += -c.amount
        by_month = {m: round(v, 2) for m, v in sorted(by_month.items()) if round(v, 2) > 0}
        months = list(by_month)
        out.sort(key=lambda c: c.date)
        name = _display_name([c.description for c in out])
        refunds = round(sum(c.amount for c in items if c.amount > 0), 2)

        gaps = [_month_index(b) - _month_index(a) for a, b in zip(months, months[1:])]
        cadence = None
        if len(months) >= 2:
            g = median(gaps)
            if g <= 1.5:
                cadence = "mensual"
            elif 2.5 <= g <= 3.5:
                cadence = "trimestral"
            elif 11 <= g <= 13:
                cadence = "anual"
        if cadence is None:
            for c in out:
                if -c.amount >= min_one_off:
                    one_offs.append({"key": key, "name": name, "date": c.date.isoformat(), "amount": round(-c.amount, 2)})
            continue

        last = out[-1]
        last_month_total = by_month[months[-1]]
        divisor = {"mensual": 1, "trimestral": 3, "anual": 12}[cadence]
        step = {"mensual": 1, "trimestral": 3, "anual": 12}[cadence]
        next_expected = _add_months(last.date, step)
        # Activa si el próximo cobro no está atrasado más de medio ciclo.
        grace = timedelta(days=int(15 * step))
        status = "activa" if next_expected + grace >= end else "parada"
        first_full = by_month[months[0]]
        recurring.append({
            "key": key,
            "name": name,
            "cadence": cadence,
            "monthly_cost": round(last_month_total / divisor, 2),
            "last_amount": round(-last.amount, 2),
            "last_date": last.date.isoformat(),
            "first_date": out[0].date.isoformat(),
            "next_expected": next_expected.isoformat() if status == "activa" else None,
            "status": status,
            "n_charges": len(out),
            "price_first": first_full,
            "price_last": last_month_total,
            "price_changed": abs(last_month_total - first_full) > max(1.0, 0.02 * first_full),
            "refunds": refunds,
            "by_month": by_month,
        })

    # Total de cargos por mes (todo, no solo suscripciones): sirve para cuadrar contra
    # el total del estado de cuenta cuando las transacciones se transcribieron de un PDF.
    charges_by_month: dict[str, float] = defaultdict(float)
    for c in charges:
        if c.amount < 0:
            charges_by_month[_month(c.date)] += -c.amount

    recurring.sort(key=lambda r: (r["status"] != "activa", -r["monthly_cost"]))
    one_offs.sort(key=lambda o: -o["amount"])
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "n_transactions": len(charges),
        "recurring": recurring,
        "one_offs": one_offs[:30],
        "charges_by_month": {m: round(v, 2) for m, v in sorted(charges_by_month.items())},
        "warnings": [],
    }


def monthly_totals(recurring: list[dict], keys: set[str] | None = None) -> dict[str, float]:
    """Gasto por mes sumando solo los comercios elegidos (todos si keys es None)."""
    totals: dict[str, float] = defaultdict(float)
    for r in recurring:
        if keys is None or r["key"] in keys:
            for m, v in r["by_month"].items():
                totals[m] += v
    return {m: round(v, 2) for m, v in sorted(totals.items())}
