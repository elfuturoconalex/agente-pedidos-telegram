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

    # 2. Solo nos interesan los mensajes de texto. Fotos, stickers, etc. se ignoran (pero se contesta 200
    #    para que Telegram no los reintente).
    mensaje = update.get("message") or {}
    if "text" not in mensaje:
        print(json.dumps({"evento": "IGNORADO_SIN_TEXTO", "update_id": update.get("update_id")}))
        return respuesta(200)

    chat_id = mensaje["chat"]["id"]
    sqs.send_message(
        QueueUrl=URL_FILA,
        MessageBody=json.dumps({
            "update_id": update["update_id"],
            "chat_id": chat_id,
            "nombre": mensaje.get("from", {}).get("first_name", "cliente"),
            "texto": mensaje["text"],
        }, ensure_ascii=False),
        MessageGroupId=str(chat_id),                 # la fila de este cliente
        MessageDeduplicationId=str(update["update_id"]),
    )
    # Si send_message falla, la excepción hace que API Gateway responda 500 y Telegram reintente.

    print(json.dumps({"evento": "A_LA_FILA", "update_id": update["update_id"]}))  # sin textos del cliente
    return respuesta(200)
