"""
Lambda del AGENTE (Fase 2) — el empleado de Abarrotes Don Chuy, ahora en AWS.

Es el mismo empleado de empleado.py (Fase 1), con 4 cambios:
  1. La plática y el carrito ya no viven en la memoria: se leen y se guardan en DynamoDB
     (la Lambda "olvida todo" al apagarse; DynamoDB es la nota del cambio de turno).   ADR 001
  2. Los mensajes llegan de una fila SQS FIFO, uno a la vez por cliente, y cada mensaje
     se marca como "ya procesado" para no atenderlo dos veces.                          ADR 002
  3. Claude se usa a través de Amazon Bedrock con el rol de la Lambda: sin llave de Anthropic.
  4. El token de Telegram se lee cifrado de Parameter Store; nunca se imprime.

No usa librerías externas: solo Python y boto3 (que ya viene en Lambda). Así el paquete
es solo este archivo y el catálogo.
"""
import json
import os
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

# ---------- Configuración (variables de entorno que pone Terraform) ----------
TABLA = os.environ.get("TABLA", "pedidos-don-chuy")
PARAMETRO_TOKEN = os.environ.get("PARAMETRO_TOKEN", "/agente-pedidos/telegram/bot-token")
MODELO = os.environ.get("MODELO", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
MODO_PRUEBA = os.environ.get("MODO_PRUEBA") == "1"   # 1 = no manda nada a Telegram (pruebas locales)
REGION = os.environ.get("AWS_REGION", "us-east-1")

MAX_MENSAJES = 20                                    # memoria: últimos 20 mensajes por cliente
HORAS_PLATICA = 24                                   # la plática se borra sola (TTL) después de 24 h
FORMAS_DE_PAGO = ["efectivo", "tarjeta"]
# Ciudad de México está en UTC-6 todo el año (sin horario de verano desde 2022).
HORA_MEXICO = timezone(timedelta(hours=-6), "America/Mexico_City")

# Los clientes se crean UNA vez, fuera del handler: si la Lambda sigue "tibia",
# el siguiente mensaje los reutiliza y responde más rápido.
dynamo = boto3.resource("dynamodb", region_name=REGION)
tabla = dynamo.Table(TABLA)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)
_token_cache = None

# ---------- Catálogo (archivo que viaja con la Lambda) ----------
_aqui = os.path.dirname(os.path.abspath(__file__))
_ruta_catalogo = os.path.join(_aqui, "catalogo.json")
if not os.path.exists(_ruta_catalogo):                # pruebas locales: el catálogo de la raíz del repo
    _ruta_catalogo = os.path.join(_aqui, "..", "..", "catalogo.json")
CATALOGO = json.load(open(_ruta_catalogo, encoding="utf-8"))
CATALOGO_POR_ID = {p["id"]: p for p in CATALOGO}

# ---------- Instrucciones (iguales a la Fase 1) ----------
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
- Antes de OFRECER o recomendar cualquier producto (también como alternativa), revisa con
  buscar_producto que sí haya existencia. Nunca ofrezcas algo agotado.
- Si un producto no está en la lista de productos, di que no lo manejan. No menciones
  productos, marcas ni sabores que no estén en la lista.
- Cuando el cliente pida un producto, aunque sea general (ej. "un refresco"), usa la
  herramienta para ver qué opciones hay de verdad antes de preguntarle cuál quiere.
- Si hay varias presentaciones (por ejemplo 2 litros o 600 ml), pregunta cuál quiere.
- No inventes horarios, promociones ni datos de la tienda que no estén en el catálogo.
- No prometas nada que no puedas hacer tú mismo en este chat (pasar teléfonos,
  mandar fotos, llamar, apartar productos, "checar con alguien").

Cómo se toma un pedido:
- Cuando el cliente diga qué quiere y cuánto, usa agregar_al_pedido con el id del producto.
  Los ids están entre paréntesis en la lista de productos: copia el id exacto, nunca lo inventes.
- Nunca calcules precios ni totales tú: usa los que regresan las herramientas.
- Antes de cerrar, pide la dirección de entrega y la forma de pago (efectivo o tarjeta).
- Lee el resumen al cliente (productos, cantidades, total, dirección y pago) y pregúntale
  si está correcto. Usa confirmar_pedido SOLO después de que diga que sí.
- El pedido solo existe si confirmar_pedido regresa un folio. Nunca digas que el pedido
  está confirmado sin haberla usado, y al confirmar dale al cliente su folio.
- Si una herramienta regresa un error, explícaselo al cliente con tus palabras."""


def normal(texto):
    """Minúsculas y sin acentos, para que 'Azúcar' y 'azucar' sean lo mismo."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def resumen_carrito(carrito):
    """El código (no Claude) arma el resumen y calcula los totales."""
    renglones = []
    for id_prod, cantidad in carrito.items():
        prod = CATALOGO_POR_ID[id_prod]
        renglones.append({"id": id_prod, "producto": f"{prod['nombre']} ({prod['presentacion']})",
                          "cantidad": cantidad, "precio_unitario": prod["precio"],
                          "subtotal": cantidad * prod["precio"]})
    return {"productos": renglones, "total": sum(r["subtotal"] for r in renglones)}


def instrucciones(carrito):
    """Se arma en CADA mensaje: lista de disponibles, agotados aparte y el pedido actual (lecciones de la Fase 1)."""
    def renglon(p):
        return f"- {p['nombre']}, {p['presentacion']} ({p['id']})"
    lista = "\n".join(sorted(renglon(p) for p in CATALOGO if p["existencia"] > 0))
    agotados = "\n".join(sorted(renglon(p) for p in CATALOGO if p["existencia"] == 0)) or "(ninguno)"
    pedido = resumen_carrito(carrito)
    if pedido["productos"]:
        estado = "\n".join(f"- {r['producto']} ({r['id']}): {r['cantidad']}" for r in pedido["productos"])
        estado += f"\nTotal: ${pedido['total']}"
    else:
        estado = "(vacío)"
    return (REGLAS + "\n\nProductos DISPONIBLES (no hay otros, ni otras marcas o sabores):\n" + lista
            + "\n\nAGOTADOS por ahora. Nunca los ofrezcas ni los menciones como opción; "
              "solo si el cliente los pide, dile que se acabaron:\n" + agotados
            + "\n\nPedido actual de este cliente (ya guardado en el carrito, NO lo vuelvas a agregar):\n" + estado
            + "\n\nTono:\n" + TONO)


# ---------- Herramientas ----------
def buscar_producto(texto):
    palabras = [p for p in normal(texto).split() if len(p) > 2]
    encontrados = []
    for prod in CATALOGO:
        donde = normal(" ".join([prod["nombre"], prod["presentacion"]] + prod["sinonimos"]))
        if any(p in donde for p in palabras):
            encontrados.append({k: prod[k] for k in ("id", "nombre", "presentacion", "precio", "existencia")})
    return {"productos": encontrados[:6]}


def agregar_al_pedido(carrito, id_producto, cantidad):
    prod = CATALOGO_POR_ID.get(id_producto)
    if prod is None:
        return {"error": f"No existe el producto '{id_producto}'. Usa buscar_producto para ver los ids."}
    if not isinstance(cantidad, int) or cantidad < 1:
        return {"error": "La cantidad debe ser un número entero mayor a 0."}
    if cantidad > prod["existencia"]:
        return {"error": f"Solo hay {prod['existencia']} de {prod['nombre']} ({prod['presentacion']})."}
    carrito[id_producto] = cantidad              # DEJA en N, no suma (lección del cobro doble)
    return {"ok": True, "pedido": resumen_carrito(carrito)}


def quitar_del_pedido(carrito, id_producto):
    if id_producto not in carrito:
        return {"error": "Ese producto no está en el pedido."}
    del carrito[id_producto]
    return {"ok": True, "pedido": resumen_carrito(carrito)}


def confirmar_pedido(chat_id, carrito, nombre_cliente, direccion, forma_pago):
    """Valida y guarda el pedido en DynamoDB (ADR 001): folio atómico + una transacción todo-o-nada."""
    resumen = resumen_carrito(carrito)
    errores = []
    if not resumen["productos"]:
        errores.append("El pedido está vacío.")
    if not direccion or len(direccion.strip()) < 8:
        errores.append("Falta una dirección de entrega completa (calle, número y colonia).")
    if forma_pago not in FORMAS_DE_PAGO:
        errores.append(f"La forma de pago debe ser una de: {', '.join(FORMAS_DE_PAGO)}.")
    if errores:
        return {"error": " ".join(errores)}

    # 1. Folio: DynamoDB suma 1 de forma atómica; nunca entrega el mismo número a dos pedidos.
    r = tabla.update_item(Key={"PK": "CONTADOR", "SK": "FOLIO"}, UpdateExpression="ADD ultimo :uno",
                          ExpressionAttributeValues={":uno": 1}, ReturnValues="UPDATED_NEW")
    folio = f"DC-{int(r['Attributes']['ultimo']):04d}"

    # 2. Fechas en hora de México: semana ISO (lunes a domingo) y mes.
    ahora = datetime.now(HORA_MEXICO)
    fecha = ahora.isoformat(timespec="seconds")
    iso = ahora.isocalendar()
    semana = f"SEMANA#{iso[0]}-W{iso[1]:02d}"
    mes = f"MES#{ahora:%Y-%m}"

    pedido = {
        "PK": f"CLIENTE#{chat_id}", "SK": f"PEDIDO#{folio}",
        "folio": folio, "fecha": fecha, "chat_id": str(chat_id), "cliente": nombre_cliente,
        "productos": resumen["productos"], "total": resumen["total"],
        "direccion": direccion.strip(), "forma_pago": forma_pago, "estado": "nuevo",
        "GSI1PK": "ESTADO#nuevo", "GSI1SK": f"{fecha}#{folio}",   # aparece en la lista de pedidos nuevos
    }

    # 3. Libretas de ventas: se SUMA el total, el número de pedidos y cada producto (como contadores de interfaz).
    # Ojo: "total" es palabra reservada de DynamoDB; por eso todos los nombres van con alias (#...).
    nombres = {"#total": "total", "#pedidos": "pedidos"}
    nombres.update({f"#p{i}": f"P#{r_['id']}" for i, r_ in enumerate(resumen["productos"])})
    valores = {":total": resumen["total"], ":uno": 1}
    valores.update({f":c{i}": r_["cantidad"] for i, r_ in enumerate(resumen["productos"])})
    suma = "ADD #total :total, #pedidos :uno, " + ", ".join(f"#p{i} :c{i}" for i in range(len(resumen["productos"])))

    def libreta(sk):
        return {"Update": {"TableName": TABLA, "Key": {"PK": "VENTAS", "SK": sk},
                           "UpdateExpression": suma, "ExpressionAttributeNames": nombres,
                           "ExpressionAttributeValues": valores}}

    # 4. Transacción: pedido + libreta semanal + libreta mensual + carrito vacío. Todo o nada.
    # (tabla.meta.client convierte solo los valores de Python al formato de DynamoDB.)
    tabla.meta.client.transact_write_items(TransactItems=[
        {"Put": {"TableName": TABLA, "Item": pedido, "ConditionExpression": "attribute_not_exists(PK)"}},
        libreta(semana),
        libreta(mes),
        {"Update": {"TableName": TABLA, "Key": {"PK": f"CLIENTE#{chat_id}", "SK": "PLATICA"},
                    "UpdateExpression": "SET carrito = :vacio", "ExpressionAttributeValues": {":vacio": {}}}},
    ])
    carrito.clear()
    print(json.dumps({"evento": "PEDIDO_GUARDADO", "folio": folio, "total": resumen["total"]}))
    return {"ok": True, "folio": folio, "total": resumen["total"]}


def usar_herramienta(nombre, entrada, chat_id, carrito, nombre_cliente):
    if nombre == "buscar_producto":
        return buscar_producto(entrada.get("texto", ""))
    if nombre == "agregar_al_pedido":
        return agregar_al_pedido(carrito, entrada.get("id_producto"), entrada.get("cantidad"))
    if nombre == "quitar_del_pedido":
        return quitar_del_pedido(carrito, entrada.get("id_producto"))
    if nombre == "ver_pedido":
        return resumen_carrito(carrito)
    if nombre == "confirmar_pedido":
        return confirmar_pedido(chat_id, carrito, nombre_cliente,
                                entrada.get("direccion", ""), entrada.get("forma_pago", ""))
    return {"error": f"No existe la herramienta {nombre}"}


# Fichas de las herramientas, en el formato de Bedrock (Converse API)
def _ficha(nombre, descripcion, propiedades, requeridos=()):
    return {"toolSpec": {"name": nombre, "description": descripcion,
                         "inputSchema": {"json": {"type": "object", "properties": propiedades,
                                                  "required": list(requeridos)}}}}


HERRAMIENTAS = {"tools": [
    _ficha("buscar_producto", "Busca en el catálogo de Abarrotes Don Chuy. Devuelve los productos que coinciden, "
           "con id, presentación, precio en pesos y existencia (0 = agotado). Úsala siempre antes de dar precios "
           "o confirmar si hay algo.",
           {"texto": {"type": "string", "description": "Lo que busca el cliente, ej. 'tortillas'"}}, ["texto"]),
    _ficha("agregar_al_pedido", "Pone un producto en el pedido con la cantidad TOTAL que quiere el cliente "
           "(si ya estaba, la reemplaza; no suma). Regresa el pedido con subtotales y total.",
           {"id_producto": {"type": "string", "description": "El id del catálogo, ej. 'TOR-MAIZ'"},
            "cantidad": {"type": "integer", "description": "Cantidad TOTAL de ese producto"}},
           ["id_producto", "cantidad"]),
    _ficha("quitar_del_pedido", "Quita un producto del pedido del cliente.",
           {"id_producto": {"type": "string"}}, ["id_producto"]),
    _ficha("ver_pedido", "Muestra cómo va el pedido del cliente: productos, cantidades, subtotales y total.", {}),
    _ficha("confirmar_pedido", "Guarda el pedido. Úsala SOLO después de leerle el resumen al cliente y que diga que sí.",
           {"direccion": {"type": "string", "description": "Calle, número y colonia"},
            "forma_pago": {"type": "string", "enum": FORMAS_DE_PAGO}}, ["direccion", "forma_pago"]),
]}


# ---------- El bucle del agente (Claude por Bedrock) ----------
def responder(chat_id, texto, nombre_cliente, mensajes, carrito):
    """Igual que en la Fase 1: Claude puede usar herramientas varias veces antes de contestar."""
    mensajes.append({"role": "user", "content": texto})
    del mensajes[:-MAX_MENSAJES]
    while mensajes and mensajes[0]["role"] != "user":     # Claude necesita empezar con el cliente
        mensajes.pop(0)

    turno = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in mensajes]
    traza = {"herramientas": [], "tokens_entrada": 0, "tokens_salida": 0}
    pedido_guardado = aviso_dado = False

    for _ in range(8):                                    # máximo 8 vueltas, por seguridad
        r = bedrock.converse(modelId=MODELO, system=[{"text": instrucciones(carrito)}], messages=turno,
                             toolConfig=HERRAMIENTAS, inferenceConfig={"maxTokens": 400})
        traza["tokens_entrada"] += r["usage"]["inputTokens"]
        traza["tokens_salida"] += r["usage"]["outputTokens"]
        salida = r["output"]["message"]

        if r["stopReason"] != "tool_use":
            texto_final = "".join(b.get("text", "") for b in salida["content"])
            # GUARDIA: ¿dice "confirmado" sin haber guardado el pedido de verdad?
            if "confirmad" in normal(texto_final) and not pedido_guardado and carrito and not aviso_dado:
                aviso_dado = True
                traza["herramientas"].append("GUARDIA")
                turno.append(salida)
                turno.append({"role": "user", "content": [{"text": "[Aviso del sistema, no del cliente] Dijiste que "
                              "el pedido está confirmado, pero NO usaste confirmar_pedido y el pedido NO se guardó. "
                              "Si el cliente ya dijo que sí, usa confirmar_pedido ahora con su dirección y forma de "
                              "pago; si no, pregúntale."}]})
                continue
            break

        turno.append(salida)
        resultados = []
        for b in salida["content"]:
            if "toolUse" in b:
                uso = b["toolUse"]
                resultado = usar_herramienta(uso["name"], uso.get("input", {}), chat_id, carrito, nombre_cliente)
                hubo_error = "error" in resultado
                if uso["name"] == "confirmar_pedido" and resultado.get("ok"):
                    pedido_guardado = True
                traza["herramientas"].append(("❌ " if hubo_error else "") + uso["name"])
                resultados.append({"toolResult": {"toolUseId": uso["toolUseId"], "content": [{"json": resultado}],
                                                  "status": "error" if hubo_error else "success"}})
        turno.append({"role": "user", "content": resultados})

    respuesta = "".join(b.get("text", "") for b in salida["content"]).replace("**", "").strip()
    if not respuesta:
        respuesta = "Perdón, me trabé tantito. ¿Me lo repites?"
    mensajes.append({"role": "assistant", "content": respuesta})
    traza["costo_usd"] = round(traza["tokens_entrada"] / 1e6 * 1 + traza["tokens_salida"] / 1e6 * 5, 6)
    return respuesta, traza


# ---------- Telegram ----------
def token_telegram():
    """Lee el token cifrado de Parameter Store una sola vez por Lambda tibia. Nunca se imprime."""
    global _token_cache
    if _token_cache is None:
        _token_cache = ssm.get_parameter(Name=PARAMETRO_TOKEN, WithDecryption=True)["Parameter"]["Value"]
    return _token_cache


def enviar_telegram(chat_id, texto):
    if MODO_PRUEBA:
        print(f"   🤖 (prueba, no se envía) {texto}")
        return
    datos = json.dumps({"chat_id": chat_id, "text": texto}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token_telegram()}/sendMessage", data=datos,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.HTTPError as e:
        # Se reporta solo el código: la dirección lleva el token y no debe salir en los logs.
        raise RuntimeError(f"Telegram respondió {e.code}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Sin conexión con Telegram ({type(e.reason).__name__})") from None


# ---------- Un mensaje de la fila ----------
def _a_entero(v):
    return int(v) if isinstance(v, Decimal) else v


def procesar(mensaje):
    update_id = str(mensaje["update_id"])
    chat_id = mensaje["chat_id"]
    nombre = mensaje.get("nombre", "cliente")
    texto = mensaje.get("texto", "")

    # ¿Ya se atendió? (ADR 002: la fila evita duplicados solo 5 minutos)
    if tabla.get_item(Key={"PK": f"MENSAJE#{update_id}", "SK": "PROCESADO"}).get("Item"):
        print(json.dumps({"evento": "DUPLICADO_IGNORADO", "update_id": update_id}))
        return

    # Leer la nota del cambio de turno: la plática y el carrito de este cliente.
    item = tabla.get_item(Key={"PK": f"CLIENTE#{chat_id}", "SK": "PLATICA"}).get("Item") or {}
    mensajes = item.get("mensajes", [])
    carrito = {k: _a_entero(v) for k, v in item.get("carrito", {}).items()}

    if texto == "/start":                                 # /start = empezar de cero
        mensajes, carrito, texto = [], {}, "Hola"

    inicio = time.time()
    respuesta, traza = responder(chat_id, texto, nombre, mensajes, carrito)
    enviar_telegram(chat_id, respuesta)

    # Anotar lo nuevo para el siguiente mensaje (se borra solo a las 24 h).
    expira = int(time.time()) + HORAS_PLATICA * 3600
    tabla.put_item(Item={"PK": f"CLIENTE#{chat_id}", "SK": "PLATICA",
                         "mensajes": mensajes, "carrito": carrito, "expira": expira})
    # Marca "ya procesado" (también se borra sola a las 24 h).
    tabla.put_item(Item={"PK": f"MENSAJE#{update_id}", "SK": "PROCESADO", "expira": expira})

    # TRAZA para CloudWatch: sin textos del cliente ni datos personales.
    traza.update({"evento": "TRAZA", "update_id": update_id, "segundos": round(time.time() - inicio, 2)})
    print(json.dumps(traza, ensure_ascii=False))
    return respuesta


def handler(event, context):
    """Punto de entrada: SQS entrega un mensaje a la vez. Si algo falla, la excepción hace
    que el mensaje regrese a la fila y se reintente; después de 3 fallos se va a la DLQ."""
    for record in event["Records"]:
        procesar(json.loads(record["body"]))
