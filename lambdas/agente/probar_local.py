"""
Prueba LOCAL de la Lambda del agente, antes de subirla a AWS.

Corre el mismo código de app.py en tu Mac, pero contra la tabla REAL de DynamoDB y
Claude REAL en Bedrock (con tu perfil "personal"). Lo único que no hace es mandar
mensajes a Telegram: las respuestas se imprimen aquí (MODO_PRUEBA).

Simula lo que hará SQS: le entrega a la Lambda un mensaje a la vez, con su update_id.

Uso (desde la carpeta del proyecto, con el .venv activado):
    python lambdas/agente/probar_local.py
"""
import json
import os
import sys
import time

os.environ["MODO_PRUEBA"] = "1"
os.environ.setdefault("AWS_PROFILE", "personal")
os.environ.setdefault("AWS_REGION", "us-east-1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402  (se importa después de preparar las variables)

CHAT_PRUEBA = 900001                       # chat ficticio, no es un cliente real
base = int(time.time())                    # update_id distintos en cada corrida


def evento_sqs(update_id, texto):
    """Así se ve lo que SQS le entrega a la Lambda (un mensaje por vez)."""
    cuerpo = {"update_id": update_id, "chat_id": CHAT_PRUEBA, "nombre": "Cliente Prueba", "texto": texto}
    return {"Records": [{"body": json.dumps(cuerpo)}]}


platica = [
    "/start",
    "Qué onda, quiero 2 kilos de tortilla de maíz y un refresco de cola de 2 litros",
    "Mándalo a Calle Roble 12, Colonia Centro, pago en efectivo",
    "Sí, confírmalo",
]

print("🧪 Prueba local del agente (DynamoDB y Bedrock reales; Telegram simulado)\n")
for i, texto in enumerate(platica):
    print(f"📩 Cliente: {texto}")
    app.handler(evento_sqs(base + i, texto), None)
    print()

print("🔁 Mandamos OTRA VEZ el mensaje 2 con el mismo update_id (como si Telegram reintentara):")
app.handler(evento_sqs(base + 1, platica[1]), None)
print("   ↑ Debe decir DUPLICADO_IGNORADO y no contestar nada.\n")
print("✅ Revisa en la consola de DynamoDB → pedidos-don-chuy → Explore items: el pedido, las libretas VENTAS y la PLATICA.")
