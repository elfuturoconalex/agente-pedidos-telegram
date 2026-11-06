"""
Lambda AVISADORA (Fase 2) — le avisa a Don Chuy por Telegram cuando entra un pedido nuevo.

Cómo despierta (ADR 003): DynamoDB Streams es el "papel carbón" de la tabla. Cada cambio que
se guarda queda copiado, y un filtro hace que esta Lambda SOLO despierte cuando se CREA un
pedido (INSERT con SK que empieza con PEDIDO#). Las pláticas, contadores y libretas se ignoran.

No toca al agente ni al cliente: si Telegram falla, se reintenta solo el aviso.
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeDeserializer

TABLA = os.environ.get("TABLA", "pedidos-don-chuy")
PARAMETRO_TOKEN = os.environ.get("PARAMETRO_TOKEN", "/agente-pedidos/telegram/bot-token")
PARAMETRO_DUENO = os.environ.get("PARAMETRO_DUENO", "/agente-pedidos/dueno/chat-id")

tabla = boto3.resource("dynamodb").Table(TABLA)
ssm = boto3.client("ssm")
_traductor = TypeDeserializer()   # convierte el formato del "papel carbón" a valores de Python
_cache = {}


def parametro(nombre, cifrado=False):
    """Lee un parámetro una sola vez por Lambda tibia. Nunca se imprime."""
    if nombre not in _cache:
        _cache[nombre] = ssm.get_parameter(Name=nombre, WithDecryption=cifrado)["Parameter"]["Value"]
    return _cache[nombre]


def pesos(v):
    v = float(v)
    return f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"


def texto_aviso(p):
    renglones = [f"🛒 Pedido nuevo {p['folio']}", f"Cliente: {p.get('cliente') or 'sin nombre'}", ""]
    for r in p["productos"]:
        renglones.append(f"• {int(r['cantidad'])} × {r['producto']} = {pesos(r['subtotal'])}")
    renglones += ["", f"Total: {pesos(p['total'])}",
                  f"Dirección: {p['direccion']}",
                  f"Pago: {p['forma_pago']}",
                  "", "Cuando lo entregues, toca: /entregado_" + p["folio"].replace("-", "")]
    return "\n".join(renglones)


def enviar_telegram(chat_id, texto):
    datos = json.dumps({"chat_id": chat_id, "text": texto}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{parametro(PARAMETRO_TOKEN, True)}/sendMessage",
                                 data=datos, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=8).read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram respondió {e.code}") from None   # solo el código: la dirección lleva el token
    except urllib.error.URLError as e:
        raise RuntimeError(f"Sin conexión con Telegram ({type(e.reason).__name__})") from None


def avisar(pedido):
    llave = {"PK": pedido["PK"], "SK": pedido["SK"]}

    # 1. Palomita de "avisado", solo si no la tiene (el papel carbón puede entregar la misma copia dos veces).
    try:
        tabla.update_item(Key=llave, UpdateExpression="SET avisado = :ahora",
                          ConditionExpression="attribute_exists(PK) AND attribute_not_exists(avisado)",
                          ExpressionAttributeValues={":ahora": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    except tabla.meta.client.exceptions.ConditionalCheckFailedException:
        print(json.dumps({"evento": "YA_AVISADO", "folio": pedido["folio"]}))
        return

    # 2. Mandar el aviso. Si falla, se quita la palomita y se reintenta (hasta 3 veces, luego a la fila de fallidos).
    try:
        dueno = parametro(PARAMETRO_DUENO)
        if not dueno.lstrip("-").isdigit():
            raise RuntimeError("Falta el chat_id del dueño en Parameter Store")
        enviar_telegram(dueno, texto_aviso(pedido))
    except Exception:
        tabla.update_item(Key=llave, UpdateExpression="REMOVE avisado")
        raise
    print(json.dumps({"evento": "AVISO_ENVIADO", "folio": pedido["folio"], "total": float(pedido["total"])}))


def handler(event, context):
    for registro in event["Records"]:
        inicio = time.time()
        copia = registro["dynamodb"]["NewImage"]
        pedido = {k: _traductor.deserialize(v) for k, v in copia.items()}
        avisar(pedido)
        print(json.dumps({"evento": "TRAZA", "folio": pedido["folio"], "ms": int((time.time() - inicio) * 1000)}))
