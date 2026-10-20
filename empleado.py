"""
Paso 2 del Agente #3: el bot ya no repite; contesta Claude como empleado
de Abarrotes Don Chuy (negocio ficticio) y recuerda la conversación.

Todavía NO toma pedidos de verdad: eso viene después (catálogo + pedido estructurado).

Uso:  python empleado.py      (para detenerlo: Ctrl + C)
Necesita en .env:  TELEGRAM_BOT_TOKEN=...  y  ANTHROPIC_API_KEY=...
"""
import os
import time

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
- Todavía no tienes el catálogo: NO confirmes si hay un producto ni su precio.
  Di que con gusto y que en un momento te confirman existencia y precio.
- No inventes horarios, precios, promociones ni datos de la tienda.
- No prometas nada que no puedas hacer tú mismo en este chat (pasar teléfonos,
  mandar fotos, llamar, apartar productos). Si no sabes algo, dilo con amabilidad.
- Puedes saludar, platicar y preguntar qué necesita el cliente y los detalles
  que falten (cantidad, presentación)."""

PERSONALIDAD = REGLAS + "\n\nTono:\n" + TONO

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

    r = claude.messages.create(model=MODELO, max_tokens=300, system=PERSONALIDAD, messages=historial)
    respuesta = r.content[0].text.replace("**", "")
    historial.append({"role": "assistant", "content": respuesta})

    costo = r.usage.input_tokens / 1e6 * 1 + r.usage.output_tokens / 1e6 * 5
    print(f"   🤖 {respuesta}\n   💰 {r.usage.input_tokens} + {r.usage.output_tokens} tokens · ${costo:.5f} USD")
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
