"""python3 -m menos_suscripciones scan … | render …"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from .detect import detect
from .loaders import load_csv, load_json, load_mercury
from .report import render_files


def _env_key(name: str, env_file: str | None) -> str:
    if os.getenv(name):
        return os.environ[name].strip()
    for path in [p for p in (env_file, ".env") if p]:
        p = Path(path).expanduser()
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                k, sep, v = line.partition("=")
                if sep and k.strip() == name:
                    return v.strip().strip('"').strip("'")
    return ""


def cmd_scan(args) -> int:
    warnings: list[str] = []
    if args.csv:
        charges = []
        for path in args.csv:
            got, w = load_csv(path, charges_positive=False if args.charges_negative else None)
            charges += got
            warnings += [f"{Path(path).name}: {x}" for x in w]
        source = "CSV: " + ", ".join(Path(p).name for p in args.csv)
    elif args.json:
        charges = load_json(args.json)
        source = f"JSON: {Path(args.json).name}"
    elif args.mercury:
        key = _env_key("MERCURY_API_KEY", args.env_file)
        if not key:
            print("Falta MERCURY_API_KEY (en el entorno o en un archivo .env).", file=sys.stderr)
            return 2
        end = date.today()
        start = end - timedelta(days=int(args.months * 30.5))
        try:
            charges = load_mercury(key, start, end)
        except Exception as exc:  # noqa: BLE001 — se le explica a la persona, no se le muestra un traceback
            code = getattr(exc, "code", None)
            hint = (" Mercury rechazó la llave: crea una nueva en Settings → Tokens (solo lectura)."
                    if code in (401, 403) else "")
            print(f"No pude leer Mercury ({exc}).{hint}", file=sys.stderr)
            return 2
        source = "Mercury"
    else:
        print("Dime de dónde leer: --csv archivo.csv, --json archivo.json o --mercury", file=sys.stderr)
        return 2

    result = detect(charges, min_one_off=args.min_one_off)
    result["source"] = source
    result["warnings"] = warnings + result["warnings"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    p = result["period"] or {}
    print(f"{result['n_transactions']} transacciones · {p.get('start')} a {p.get('end')} · {source}")
    for w in result["warnings"]:
        print(f"Aviso: {w}")
    print(f"\n{'llave':<28} {'al mes':>10}  {'cadencia':<10} {'estado':<7} último cargo")
    for r in result["recurring"]:
        flag = "  ↑ cambió de precio" if r["price_changed"] else ""
        print(f"{r['key'][:28]:<28} {r['monthly_cost']:>10.2f}  {r['cadence']:<10} {r['status']:<7} {r['last_date']}{flag}")
    if result["charges_by_month"]:
        print("\nTotal de cargos por mes (para cuadrar contra el estado de cuenta):")
        for m, v in result["charges_by_month"].items():
            print(f"  {m}  {v:>12,.2f}")
    if result["one_offs"]:
        print(f"\nCargos únicos de ${args.min_one_off:.0f} o más (pueden ser renovaciones anuales): {len(result['one_offs'])}")
    print(f"\nGuardado en {out}")
    return 0


def cmd_render(args) -> int:
    try:
        out = render_files(args.diagnosis, args.scan, args.out, args.catalog)
    except ValueError as exc:
        print(f"El diagnóstico no cuadra con el escaneo: {exc}", file=sys.stderr)
        return 2
    print(f"Página lista: {out.resolve()}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="menos_suscripciones", description="Diagnóstico de suscripciones.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="Leer transacciones y encontrar lo que se repite")
    src = s.add_mutually_exclusive_group()
    src.add_argument("--csv", nargs="+", help="Uno o más CSV exportados del banco o la tarjeta")
    src.add_argument("--json", help="JSON con una lista de transacciones")
    src.add_argument("--mercury", action="store_true", help="Leer directo de Mercury con MERCURY_API_KEY")
    s.add_argument("--months", type=float, default=6, help="Meses hacia atrás (Mercury). Default: 6")
    s.add_argument("--env-file", help="Archivo .env donde buscar MERCURY_API_KEY")
    s.add_argument("--charges-negative", action="store_true", help="El CSV trae los cargos en negativo (no adivinar)")
    s.add_argument("--min-one-off", type=float, default=10.0, help="Cargos únicos a listar desde este monto")
    s.add_argument("--out", default="work/scan.json")
    s.set_defaults(func=cmd_scan)

    r = sub.add_parser("render", help="Armar la página desde el diagnóstico")
    r.add_argument("diagnosis")
    r.add_argument("--scan", default="work/scan.json")
    r.add_argument("--catalog", help="Otro catálogo de alternativas (JSON)")
    r.add_argument("--out", default="work/reporte.html")
    r.set_defaults(func=cmd_render)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
