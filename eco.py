"""
Paso 1 del Agente #3: un bot "eco" que repite lo que le escribes.

Sirve para comprobar que tu Mac y Telegram ya se hablan.
Funciona con "polling": tu Mac le pregunta a Telegram, una y otra vez,
"¿hay mensajes nuevos?". (En la Fase 2, en AWS, será al revés: Telegram
avisará por webhook.)

Uso:  python eco.py      (para detenerlo: Ctrl + C)
"""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()                                   # lee TELEGRAM_BOT_TOKEN del archivo .env
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]        # nunca se imprime ni se sube a GitHub
API = f"https://api.telegram.org/bot{TOKEN}"


def recibir_mensajes(desde):
    """Le pregunta a Telegram si hay mensajes nuevos (espera hasta 30 s si no hay)."""
    r = requests.get(f"{API}/getUpdates", params={"offset": desde, "timeout": 30}, timeout=40)
    r.raise_for_status()
    return r.json()["result"]


def enviar(chat_id, texto):
    """Le manda un mensaje al cliente."""
    requests.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": texto}, timeout=10)


print("🤖 Bot encendido. Escríbele en Telegram. (Ctrl + C para apagarlo)")
siguiente = 0
try:
    while True:
        try:
            updates = recibir_mensajes(siguiente)
        except requests.HTTPError as e:
            # Telegram sí contestó, pero con un error (ej. 401 = token inválido).
            # Mostramos solo el código y la explicación, NUNCA la URL (trae el token).
            codigo = e.response.status_code
            motivo = e.response.json().get("description", "") if e.response.content else ""
            print(f"⚠️  Telegram respondió {codigo}: {motivo}. Reintento en 5 s...")
            if codigo == 401:
                print("   → El token no es válido. Revisa el archivo .env (¿pegaste el token nuevo y guardaste?).")
            time.sleep(5)
            continue
        except requests.RequestException as e:
            # Si se corta internet, no tronamos: esperamos y reintentamos.
            print(f"⚠️  Sin conexión con Telegram ({type(e).__name__}). Reintento en 5 s...")
            time.sleep(5)
            continue
        for update in updates:
            siguiente = update["update_id"] + 1          # para no leer el mismo mensaje dos veces
            mensaje = update.get("message")
            if not mensaje or "text" not in mensaje:
                continue
            chat_id = mensaje["chat"]["id"]
            nombre = mensaje["from"].get("first_name", "cliente")
            texto = mensaje["text"]
            print(f"📩 {nombre}: {texto}")
            try:
                enviar(chat_id, f"Eco: {texto}")
            except requests.RequestException as e:
                print(f"⚠️  No se pudo responder ({type(e).__name__}).")
except KeyboardInterrupt:
    print("\n👋 Bot apagado.")
