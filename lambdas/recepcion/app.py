"""
Lambda de RECEPCIÓN (Fase 2) — la puerta de entrada.

Telegram manda cada mensaje nuevo a la dirección de API Gateway (el webhook),
y esta Lambda hace muy poco, en milisegundos (ADR 002):
  1. Revisa la clave secreta del webhook: que el mensaje venga de Telegram y no de un extraño.
  2. Mete el mensaje a la fila SQS FIFO:
       - grupo = chat_id    → los mensajes de un mismo cliente van en orden, uno a la vez.
       - anti-duplicados = update_id de Telegram → si Telegram reintenta, se queda con uno.
  3. Le contesta "ok" a Telegram. Desde ese momento el mensaje ya está seguro en la fila;
     la Lambda del agente lo atenderá con calma.

Fase 3: lo que NO es texto (stickers, reacciones, notas de voz, fotos) ya no se ignora: se
traduce a una descripción entre corchetes para que el agente conteste. Nunca silencio.
"""
import base64
import hmac
import json
import os

import boto3

URL_FILA = os.environ["URL_FILA"]
PARAMETRO_SECRETO = os.environ["PARAMETRO_SECRETO_WEBHOOK"]

sqs = boto3.client("sqs")
ssm = boto3.client("ssm")
_secreto_cache = None


def secreto_webhook():
    """Lee la clave del webhook cifrada de Parameter Store, una vez por Lambda tibia. Nunca se imprime."""
    global _secreto_cache
    if _secreto_cache is None:
        _secreto_cache = ssm.get_parameter(Name=PARAMETRO_SECRETO, WithDecryption=True)["Parameter"]["Value"]
    return _secreto_cache


def traducir(update):
    """Convierte lo que manda Telegram en (chat_id, nombre, texto, tipo) para el agente.
    Lo que no es texto se describe entre corchetes: el agente no lo ve ni lo escucha, pero sabe que llegó."""
    reaccion = update.get("message_reaction")
    if reaccion:
        emojis = [r["emoji"] for r in reaccion.get("new_reaction", []) if r.get("type") == "emoji" and r.get("emoji")]
        if not emojis:                      # quitó su reacción: no hay nada que contestar
            return None
        return (reaccion["chat"]["id"], (reaccion.get("user") or {}).get("first_name", "cliente"),
                f"[el cliente reaccionó {' '.join(emojis)} a tu último mensaje]", "reaccion")

    m = update.get("message")
    if not m:
        return None
    chat_id, nombre = m["chat"]["id"], m.get("from", {}).get("first_name", "cliente")
    if "text" in m:
        return chat_id, nombre, m["text"], "texto"
    if "sticker" in m:
        emoji = m["sticker"].get("emoji", "")
        texto, tipo = f"[el cliente mandó un sticker {emoji}]".replace(" ]", "]"), "sticker"
    elif "voice" in m or "audio" in m:
        texto, tipo = "[el cliente mandó una nota de voz]", "voz"
    elif "photo" in m:
        texto, tipo = "[el cliente mandó una foto]", "foto"
    elif "video" in m or "video_note" in m:
        texto, tipo = "[el cliente mandó un video]", "video"
    elif "location" in m:
        texto, tipo = "[el cliente mandó su ubicación en el mapa]", "ubicacion"
    elif "document" in m:
        texto, tipo = "[el cliente mandó un archivo]", "archivo"
    else:
        texto, tipo = "[el cliente mandó un mensaje que no es texto]", "otro"
    if m.get("caption"):                    # el texto que a veces acompaña una foto o un video
        texto += f' {m["caption"]}'
    return chat_id, nombre, texto, tipo


def respuesta(codigo):
    return {"statusCode": codigo, "body": json.dumps({"ok": codigo == 200})}


def handler(event, context):
    # 1. ¿Viene de Telegram? Telegram manda la clave en este encabezado (API Gateway lo pasa en minúsculas).
    clave = (event.get("headers") or {}).get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(clave, secreto_webhook()):   # comparación segura contra adivinanzas
        print(json.dumps({"evento": "CLAVE_INCORRECTA"}))
        return respuesta(401)

    cuerpo = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        cuerpo = base64.b64decode(cuerpo).decode()
    update = json.loads(cuerpo)

    # 2. Texto, sticker, reacción, voz, foto...: todo se traduce a texto para el agente.
    #    Lo que no trae nada que contestar (por ejemplo, quitar una reacción) se ignora con 200,
    #    para que Telegram no lo reintente.
    traducido = traducir(update)
    if traducido is None:
        print(json.dumps({"evento": "IGNORADO", "update_id": update.get("update_id")}))
        return respuesta(200)

    chat_id, nombre, texto, tipo = traducido
    sqs.send_message(
        QueueUrl=URL_FILA,
        MessageBody=json.dumps({
            "update_id": update["update_id"],
            "chat_id": chat_id,
            "nombre": nombre,
            "texto": texto,
        }, ensure_ascii=False),
        MessageGroupId=str(chat_id),                 # la fila de este cliente
        MessageDeduplicationId=str(update["update_id"]),
    )
    # Si send_message falla, la excepción hace que API Gateway responda 500 y Telegram reintente.

    print(json.dumps({"evento": "A_LA_FILA", "update_id": update["update_id"], "tipo": tipo}))  # sin textos
    return respuesta(200)
