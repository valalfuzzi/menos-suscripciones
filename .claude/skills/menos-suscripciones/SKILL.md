---
name: menos-suscripciones
description: Diagnóstico de suscripciones. Lee las transacciones del banco o la tarjeta (CSV de cualquier banco, JSON, o Mercury por API), encuentra los cobros que se repiten, decide qué mantener, revisar, reemplazar o cancelar, propone alternativas open source y arma una página HTML con el plan. Úsala cuando alguien diga "revisa mis suscripciones", "en qué estoy gastando en software", "qué puedo cancelar", "auditoría de herramientas", "alternativas gratis a X", "menos suscripciones", o comparta un estado de cuenta para revisar gastos recurrentes.
---

# Menos suscripciones

Tú pones el criterio y Python pone los números. Nunca sumes ni promedies montos de cabeza:
todo monto que veas en la página sale de `scan.json`. Tu trabajo es decidir **qué es cada
cobro y qué hacer con él**, con razones concretas.

Los comandos se corren desde la raíz de este repo (`python3 -m menos_suscripciones …`).
Sin dependencias: sirve el Python 3.9+ que ya trae la Mac.

## 1. Conseguir las transacciones

Pregunta de dónde salen, en este orden de preferencia:

| Fuente | Cómo |
|---|---|
| Mercury con API | `MERCURY_API_KEY` en el entorno o en un `.env` → `scan --mercury --months 6` (`--env-file ruta/.env` si vive en otro lado). Llave de solo lectura: Mercury → Settings → Tokens. |
| Conector de un banco en esta sesión (Mercury, Plaid…) | Trae las transacciones paginando completo, guárdalas en `work/transacciones.json` como lista de `{date, description, amount}` (cargos en negativo) y corre `scan --json work/transacciones.json`. |
| CSV del banco o la tarjeta | `scan --csv archivo.csv [otro.csv …]`. Detecta solo columnas, separador y formato de fecha. Si avisa que invirtió el signo y está mal, repite con `--charges-negative`. |

Pide **al menos 6 meses** (12 es mejor: así aparecen las renovaciones anuales) y **todas
las tarjetas** que paguen software. Si solo hay una, dilo en `not_seen`.

```bash
python3 -m menos_suscripciones scan --csv ~/Downloads/estado.csv --out work/scan.json
```

La salida lista cada comercio que cobró en meses seguidos (`recurring`) con su llave,
monto mensual, cadencia, si está activa o parada, y si cambió de precio. Aparte lista
los cargos únicos grandes (`one_offs`): ahí se esconden las renovaciones anuales.

## 2. Diagnosticar

Lee `work/scan.json` completo. Para cada comercio de `recurring`:

1. **¿Es software o un servicio por suscripción?** El súper, la gasolina, la nómina, los
   impuestos y las comisiones bancarias se quedan fuera (menciónalos en `findings` si llaman
   la atención). Ojo con los gastos personales en una tarjeta de empresa: nómbralos sin juzgar.
2. **Agrupa** las llaves que son la misma herramienta (`anthropic claude max` + `anthropic
   claude pro` → "Anthropic (Claude)") en un solo `keys`.
3. **Decide el veredicto** con lo que sabes de esta persona. Lee el contexto disponible
   (un `CLAUDE.md`, sus notas, lo que te haya contado) y **pregunta** lo que no puedas
   saber: "¿Tu equipo usa CapCut Pro?", "¿Sigues usando Lovable?". Una pregunta corta
   vale más que un veredicto inventado.
   - `mantener`: se usa y no hay reemplazo que valga el cambio. Di por qué en una frase.
   - `revisar`: subió de precio, se paró, cobra por usuario, o no sabes si se usa.
   - `reemplazar`: hay una alternativa gratis que cubre lo que esta persona usa, y el costo
     de mudarse es bajo. Nombra la alternativa y el paso previo (exportar, avisar al equipo).
   - `cancelar`: ya no se usa, o algo que ya tiene lo reemplazó.
4. **Alternativas**: busca primero en `menos_suscripciones/alternatives.json` (campo
   `replaces`). Si no hay nada, busca en la web (openalternative.co, alternativeto.net con
   filtro open source) y **abre la página del proyecto** antes de recomendarlo: que exista,
   que esté mantenido y que la licencia siga abierta. Pasa `{"name", "url"}` para lo que no
   está en el catálogo. Nunca propongas algo que rompa una integración de la que depende
   (bots, automatizaciones, el flujo de un cliente).

Revisa también `one_offs` por renovaciones anuales y por compras que parecen suscripciones
en otra tarjeta.

## 3. Escribir el diagnóstico

Guarda `work/diagnostico.json` (ejemplo completo en `examples/diagnostico-ejemplo.json`):

```json
{
  "title": "Menos suscripciones",
  "owner": "Nombre del negocio",
  "as_of": "AAAA-MM-DD",
  "source": "Tarjeta X, 1 abr – 30 sep 2026",
  "lede": "Dos frases: qué se revisó y qué se queda sí o sí.",
  "subscriptions": [
    {"keys": ["tango"], "name": "Tango", "verdict": "reemplazar",
     "why": "Una o dos frases concretas, con fechas y montos que salen del escaneo.",
     "alternatives": ["Mimik"]}
  ],
  "plan": [{"when": "Esta semana", "items": [{"title": "Cancelar X", "saving": 11, "detail": "Cuándo cobra de nuevo."}]}],
  "findings": ["Hallazgos de todo el período: qué entró nuevo, qué subió, reembolsos, renovaciones anuales."],
  "not_seen": "Qué no pudo ver esta revisión (otras tarjetas, pagos anuales fuera del período).",
  "directory": {"mlx-whisper": {"status": "Ya lo tienes", "note": "..."}}
}
```

- `keys` tienen que existir en `scan.json`; si no, `render` falla y dice cuál.
- `monthly` solo si hay razón para pisar el monto del escaneo (un plan ya cancelado);
  dila en `why`.
- `saving` en el plan es copia del monto mensual de esa fila del escaneo, no un cálculo nuevo.
- Estados del directorio: `Probar ya`, `Ya lo tienes`, `Evaluar`, `Para clientes`, `No
  conviene`. Las alternativas de algo que se reemplaza o cancela salen como `Probar ya` solas.
- Escribe en el idioma de la persona, con frases cortas y montos reales. Nada de "optimizar
  tu stack": di qué cancelar, cuándo y cuánto ahorra.

## 4. Armar la página y entregar

```bash
python3 -m menos_suscripciones render work/diagnostico.json --scan work/scan.json --out work/reporte.html
open work/reporte.html
```

Si la sesión puede publicar artefactos, publica `work/reporte.html` como página privada y
da el link. En el chat, en tres líneas: cuánto paga hoy por mes, cuánto puede cortar (y en
un año), y la primera acción con fecha.

`work/` está en `.gitignore`: ahí viven datos bancarios, nunca se commitean.
