"""
Paso 2 del Agente #3: el bot ya no repite; contesta Claude como empleado
de Abarrotes Don Chuy (negocio ficticio) y recuerda la conversación.

Sesión 3: Claude ya tiene su primera HERRAMIENTA: buscar_producto, que consulta
el catálogo (catalogo.json) para dar precios y existencias reales en vez de suponer.
Todavía NO arma ni guarda el pedido: eso viene después.

Uso:  python empleado.py      (para detenerlo: Ctrl + C)
Necesita en .env:  TELEGRAM_BOT_TOKEN=...  y  ANTHROPIC_API_KEY=...
"""
import json
import os
import time
import unicodedata

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]       # nunca se imprime
API = f"https://api.telegram.org/bot{TOKEN}"
claude = Anthropic()                           # lee ANTHROPIC_API_KEY del .env

MODELO = "claude-haiku-4-5"
MAX_MENSAJES = 20                              # memoria: últimos 20 mensajes por cliente

# El TONO se puede cambiar por cliente sin tocar las REGLAS.
# Para la demo: de cuates. Un despacho o una clínica elegiría otro.
TONO = """Hablas de cuates, con mucha confianza y buena onda, como el chavo que atiende
la tiendita de la esquina: "qué onda", "compa", "jefe", "va que va". Puedes usar
algún emoji de vez en cuando."""

REGLAS = """Eres el empleado que atiende el Telegram de "Abarrotes Don Chuy",
una tiendita de barrio ficticia en México.

Reglas (siempre, sin importar el tono):
- Breve: máximo 3 renglones. Texto plano, sin negritas ni listas largas.
- Español de México.
- Antes de decir si hay un producto o cuánto cuesta, USA la herramienta buscar_producto.
  Nunca des un precio ni confirmes existencia sin haberla consultado.
- Si existencia es 0, di que por ahora no hay y ofrece algo parecido del catálogo si existe.
- Si un producto no está en la lista de productos, di que no lo manejan. No menciones
  productos, marcas ni sabores que no estén en la lista.
- Cuando el cliente pida un producto, aunque sea general (ej. "un refresco"), usa la
  herramienta para ver qué opciones hay de verdad antes de preguntarle cuál quiere.
- Si hay varias presentaciones (por ejemplo 2 litros o 600 ml), pregunta cuál quiere.
- No inventes horarios, promociones ni datos de la tienda que no estén en el catálogo.
- No prometas nada que no puedas hacer tú mismo en este chat (pasar teléfonos,
  mandar fotos, llamar, apartar productos, "checar con alguien")."""

# La lista de productos (SIN precios ni existencias) va en las instrucciones,
# para que Claude sepa qué maneja la tienda y no invente marcas o productos.
# Precio y existencia cambian, por eso siempre se consultan con la herramienta.
_catalogo = json.load(open("catalogo.json", encoding="utf-8"))
LISTA_PRODUCTOS = "\n".join(sorted({f"- {p['nombre']}" for p in _catalogo}))

PERSONALIDAD = (REGLAS + "\n\nProductos que maneja la tienda (no hay otros, ni otras marcas o sabores):\n"
                + LISTA_PRODUCTOS + "\n\nTono:\n" + TONO)

# ---------- La herramienta: buscar en el catálogo ----------
CATALOGO = json.load(open("catalogo.json", encoding="utf-8"))


def normal(texto):
    """Minúsculas y sin acentos, para que 'Azúcar' y 'azucar' sean lo mismo."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def buscar_producto(texto):
    """Devuelve los productos del catálogo que coinciden con lo que busca el cliente."""
    palabras = [p for p in normal(texto).split() if len(p) > 2]
    encontrados = []
    for prod in CATALOGO:
        donde = normal(" ".join([prod["nombre"], prod["presentacion"]] + prod["sinonimos"]))
        if any(p in donde for p in palabras):
            encontrados.append({k: prod[k] for k in ("id", "nombre", "presentacion", "precio", "existencia")})
    return encontrados[:6]


# La "ficha" de la herramienta que le explicamos a Claude
HERRAMIENTAS = [{
    "name": "buscar_producto",
    "description": "Busca en el catálogo de Abarrotes Don Chuy. Devuelve los productos que coinciden, "
                   "con presentación, precio en pesos y existencia (0 = agotado). "
                   "Úsala siempre antes de dar precios o confirmar si hay algo.",
    "input_schema": {
        "type": "object",
        "properties": {"texto": {"type": "string", "description": "Lo que busca el cliente, ej. 'tortillas' o 'refresco'"}},
        "required": ["texto"],
    },
}]

conversaciones = {}   # chat_id -> lista de mensajes {"role", "content"}


def recibir_mensajes(desde):
    r = requests.get(f"{API}/getUpdates", params={"offset": desde, "timeout": 30}, timeout=40)
    r.raise_for_status()
    return r.json()["result"]


def enviar(chat_id, texto):
    requests.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": texto}, timeout=10)


def responder_con_claude(chat_id, texto):
    historial = conversaciones.setdefault(chat_id, [])
    historial.append({"role": "user", "content": texto})
    del historial[:-MAX_MENSAJES]                     # olvidamos lo más viejo
    if historial[0]["role"] != "user":                # Claude necesita empezar con el cliente
        historial.pop(0)

    # Durante este turno, Claude puede usar herramientas varias veces (el loop del agente).
    # Esas idas y vueltas viven en "turno"; en la memoria solo guardamos la respuesta final.
    turno = list(historial)
    tokens_in = tokens_out = 0
    for _ in range(5):                                 # máximo 5 vueltas, por seguridad
        r = claude.messages.create(model=MODELO, max_tokens=400, system=PERSONALIDAD,
                                   tools=HERRAMIENTAS, messages=turno)
        tokens_in += r.usage.input_tokens
        tokens_out += r.usage.output_tokens

        if r.stop_reason != "tool_use":                # ya contestó: salimos del loop
            break

        turno.append({"role": "assistant", "content": r.content})
        resultados = []
        for bloque in r.content:
            if bloque.type == "tool_use" and bloque.name == "buscar_producto":
                encontrados = buscar_producto(bloque.input.get("texto", ""))
                print(f"   🔧 buscar_producto({bloque.input.get('texto')!r}) → {len(encontrados)} resultado(s)")
                resultados.append({"type": "tool_result", "tool_use_id": bloque.id,
                                   "content": json.dumps(encontrados, ensure_ascii=False)})
        turno.append({"role": "user", "content": resultados})

    respuesta = "".join(b.text for b in r.content if b.type == "text").replace("**", "").strip()
    if not respuesta:
        respuesta = "Perdón, me trabé tantito. ¿Me lo repites?"
    historial.append({"role": "assistant", "content": respuesta})

    costo = tokens_in / 1e6 * 1 + tokens_out / 1e6 * 5
    print(f"   🤖 {respuesta}\n   💰 {tokens_in} + {tokens_out} tokens · ${costo:.5f} USD")
    return respuesta


print("🛒 Abarrotes Don Chuy abierto. Escríbele al bot en Telegram. (Ctrl + C para cerrar)")
siguiente = 0
try:
    while True:
        try:
            updates = recibir_mensajes(siguiente)
        except requests.HTTPError as e:
            codigo = e.response.status_code
            print(f"⚠️  Telegram respondió {codigo}. Reintento en 5 s...")
            time.sleep(5)
            continue
        except requests.RequestException as e:
            print(f"⚠️  Sin conexión con Telegram ({type(e).__name__}). Reintento en 5 s...")
            time.sleep(5)
            continue

        for update in updates:
            siguiente = update["update_id"] + 1
            mensaje = update.get("message")
            if not mensaje or "text" not in mensaje:
                continue
            chat_id = mensaje["chat"]["id"]
            nombre = mensaje["from"].get("first_name", "cliente")
            texto = mensaje["text"]
            print(f"📩 {nombre}: {texto}")

            if texto == "/start":
                conversaciones.pop(chat_id, None)     # /start = empezar de cero
                texto = "Hola"
            try:
                respuesta = responder_con_claude(chat_id, texto)
            except Exception as e:
                print(f"⚠️  Claude no respondió ({type(e).__name__}).")
                respuesta = "Perdón, tuve un problemita. ¿Me lo repites en un momento?"
            try:
                enviar(chat_id, respuesta)
            except requests.RequestException as e:
                print(f"⚠️  No se pudo responder ({type(e).__name__}).")
except KeyboardInterrupt:
    print("\n👋 Tienda cerrada.")
