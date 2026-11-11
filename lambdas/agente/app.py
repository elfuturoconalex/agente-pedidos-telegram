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
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

import dueno   # comandos de Don Chuy, sin IA (ADR 003)

# ---------- Configuración (variables de entorno que pone Terraform) ----------
TABLA = os.environ.get("TABLA", "pedidos-don-chuy")
PARAMETRO_TOKEN = os.environ.get("PARAMETRO_TOKEN", "/agente-pedidos/telegram/bot-token")
PARAMETRO_DUENO = os.environ.get("PARAMETRO_DUENO", "/agente-pedidos/dueno/chat-id")
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
_dueno_cache = None

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
- QUÉ HAY Y QUÉ NO: usa las listas DISPONIBLES y AGOTADOS de abajo. Se arman con el
  inventario real en cada mensaje, así que no hace falta buscar para saber si hay algo.
- PRECIOS: solo con herramientas. Antes de decir cuánto cuesta algo, usa buscar_producto
  (o usa lo que regresa agregar_al_pedido). Nunca des un precio, ni aproximado, que no te
  haya dado una herramienta en esta plática.
- Si piden algo AGOTADO, di que por ahora no hay y ofrece algo parecido de DISPONIBLES.
  Nunca ofrezcas ni recomiendes algo agotado.
- Si un producto no está en ninguna de las dos listas, di que no lo manejan. No menciones
  productos, marcas ni sabores que no estén en las listas.
- Si piden más de lo que hay, agregar_al_pedido te lo dirá: explícale al cliente cuánto hay.
- Si hay varias presentaciones (por ejemplo 2 litros o 600 ml), pregunta cuál quiere.
- No inventes horarios, promociones ni datos de la tienda que no estén en el catálogo.
- No prometas nada que no puedas hacer tú mismo en este chat (pasar teléfonos,
  mandar fotos, llamar, apartar productos, "checar con alguien").

Cómo se toma un pedido:
- Cuando el cliente diga qué quiere y cuánto, usa agregar_al_pedido con el id del producto.
  Los ids están entre paréntesis en la lista de productos: copia el id exacto, nunca lo inventes.
- Nunca calcules precios ni totales tú: usa los que regresan las herramientas.
- Antes de cerrar, pide la dirección de entrega y la forma de pago (efectivo o tarjeta).
  La dirección necesita CALLE, NÚMERO y COLONIA. Usa solo lo que dijo el cliente: si falta
  una parte, pregúntala; nunca la inventes ni la completes tú.
- Cuando ya tengas productos, dirección y forma de pago, usa preparar_pedido de inmediato
  (no preguntes "¿algo más?" en ese momento). Te regresa el resumen exacto: léeselo al cliente
  tal cual y pregúntale si está correcto.
- Usa confirmar_pedido SOLO cuando el cliente apruebe ese resumen. Cualquier aprobación cuenta:
  "sí", "sale", "va", "ok", "mándalo", "está bien", "órale", o un 👍 (escrito, en sticker o como
  reacción). Si cambia algo, ajusta el pedido y vuelve a usar preparar_pedido. Si su respuesta
  no queda clara, pregúntale de nuevo si se lo mandas así; nunca lo confirmes con la duda.
- Si llega algo entre corchetes, como [el cliente mandó una nota de voz] o [una foto], es algo
  que no puedes ver ni escuchar: pídele amablemente que te lo escriba.
- El pedido solo existe si confirmar_pedido regresa un folio. Primero usa la herramienta y
  después escribe: nunca digas que quedó confirmado ni des un folio antes de usarla.
- Si una herramienta regresa un error, explícaselo al cliente con tus palabras."""


def normal(texto):
    """Minúsculas y sin acentos, para que 'Azúcar' y 'azucar' sean lo mismo."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


# Respuestas que no son una dirección de verdad.
DIRECCIONES_VAGAS = {"casa", "mi casa", "aqui", "alla", "aca", "donde siempre", "ya sabes", "la de siempre",
                     "mi domicilio", "domicilio", "mi trabajo", "trabajo", "la misma", "igual", "no se"}


def validar_direccion(direccion):
    """El esquema de la dirección: calle, número y colonia por separado (referencias opcional).
    Regresa (errores, texto_bonito). Si hay errores, el pedido NO se guarda y Claude pregunta lo que falta."""
    if not isinstance(direccion, dict):
        return ["La dirección debe venir por partes: calle, número y colonia."], ""
    partes = {k: str(direccion.get(k) or "").strip() for k in ("calle", "numero", "colonia", "referencias")}
    calle, numero, referencias = partes["calle"], partes["numero"], partes["referencias"]
    colonia = re.sub(r"^(col\.?|colonia)\s+", "", partes["colonia"], flags=re.IGNORECASE)   # sin "Col. Col."
    errores = []
    if len(calle) < 3 or normal(calle) in DIRECCIONES_VAGAS:
        errores.append("Falta la calle (el nombre real de la calle).")
    if not re.search(r"\d", numero) and normal(numero).replace(" ", "") not in ("s/n", "sn", "sinnumero"):
        errores.append("Falta el número exterior (o 'S/N' si no tiene).")
    if len(colonia) < 3 or normal(colonia) in DIRECCIONES_VAGAS:
        errores.append("Falta la colonia.")
    texto = f"{calle} {numero}, Col. {colonia}" + (f" ({referencias})" if referencias else "")
    return errores, texto


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


def preparar_pedido(carrito, direccion, forma_pago, estado):
    """Paso 1 de 2, como un 'show | compare' antes del 'commit': valida todo y arma el resumen EXACTO
    que Claude le lee al cliente. Todavía no guarda nada; queda "por confirmar"."""
    resumen = resumen_carrito(carrito)
    errores = [] if resumen["productos"] else ["El pedido está vacío."]
    errores_dir, direccion_texto = validar_direccion(direccion)
    errores += errores_dir
    if forma_pago not in FORMAS_DE_PAGO:
        errores.append(f"La forma de pago debe ser una de: {', '.join(FORMAS_DE_PAGO)}.")
    if errores:
        return {"error": " ".join(errores) + " Pregúntale al cliente lo que falta; no lo inventes."}
    estado["por_confirmar"] = {
        "direccion": {k: str(direccion.get(k) or "").strip() for k in ("calle", "numero", "colonia", "referencias")},
        "forma_pago": forma_pago, "carrito": dict(carrito), "mensaje": estado["update_id"]}
    renglones = "; ".join(f"{r['cantidad']} x {r['producto']}: ${r['subtotal']}" for r in resumen["productos"])
    return {"ok": True, "pedido": resumen,
            "resumen_para_el_cliente": f"{renglones}. Total: ${resumen['total']}. Entrega en {direccion_texto}. "
                                       f"Pago: {forma_pago}. ¿Te lo mando así? Solo me falta tu visto bueno "
                                       f"para enviarlo.",
            "siguiente_paso": "Léele este resumen tal cual, incluida la pregunta final, y espera su respuesta. "
                              "Si lo aprueba (sí, sale, va, ok, mándalo, 👍...), usa confirmar_pedido."}


def confirmar_pedido(chat_id, carrito, nombre_cliente, estado, prueba=False):
    """Paso 2 de 2 (el 'commit'): solo guarda lo que el cliente YA VIO en el resumen y aprobó en un
    mensaje posterior. El código lo exige; no depende de que Claude siga la regla."""
    pc = estado.get("por_confirmar")
    if not pc:
        return {"error": "Primero usa preparar_pedido y léele el resumen al cliente."}
    if pc["mensaje"] == estado["update_id"]:
        return {"error": "El cliente todavía no ha visto el resumen. Léeselo y espera a que diga que sí."}
    if pc["carrito"] != carrito:
        estado["por_confirmar"] = None
        return {"error": "El pedido cambió desde el resumen. Usa preparar_pedido otra vez y léele el resumen nuevo."}
    resultado = _guardar_pedido(chat_id, carrito, nombre_cliente, pc["direccion"], pc["forma_pago"], prueba)
    if resultado.get("ok"):
        estado["por_confirmar"] = None
    return resultado


def _guardar_pedido(chat_id, carrito, nombre_cliente, direccion, forma_pago, prueba=False):
    """Valida y guarda el pedido en DynamoDB (ADR 001): folio atómico + una transacción todo-o-nada.

    prueba=True (solo el examen, invocando la Lambda directo): el pedido se guarda igual, pero con
    folio PR-xxxx, en su propia libreta de ventas y fuera de /pendientes. Así el examen prueba el
    camino real sin ensuciar las ventas ni los folios de Don Chuy (como una VLAN de pruebas)."""
    resumen = resumen_carrito(carrito)
    errores = []
    if not resumen["productos"]:
        errores.append("El pedido está vacío.")
    errores_dir, direccion_texto = validar_direccion(direccion)
    errores += errores_dir
    if forma_pago not in FORMAS_DE_PAGO:
        errores.append(f"La forma de pago debe ser una de: {', '.join(FORMAS_DE_PAGO)}.")
    if errores:   # error claro: Claude le pregunta al cliente justo lo que falta
        return {"error": " ".join(errores) + " Pregúntale al cliente lo que falta; no lo inventes."}

    # 1. Folio: DynamoDB suma 1 de forma atómica; nunca entrega el mismo número a dos pedidos.
    r = tabla.update_item(Key={"PK": "CONTADOR", "SK": "FOLIO-PRUEBA" if prueba else "FOLIO"},
                          UpdateExpression="ADD ultimo :uno",
                          ExpressionAttributeValues={":uno": 1}, ReturnValues="UPDATED_NEW")
    folio = f"{'PR' if prueba else 'DC'}-{int(r['Attributes']['ultimo']):04d}"

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
        "direccion": direccion_texto,                     # texto listo para el aviso y /pendientes
        "direccion_detalle": {k: str(direccion.get(k) or "").strip()
                              for k in ("calle", "numero", "colonia", "referencias")},
        "forma_pago": forma_pago, "estado": "nuevo",
        "GSI1PK": "ESTADO#prueba" if prueba else "ESTADO#nuevo",  # los nuevos aparecen en /pendientes
        "GSI1SK": f"{fecha}#{folio}",
    }
    if prueba:
        pedido["prueba"] = True   # la avisadora lo ignora

    # 3. Libretas de ventas: se SUMA el total, el número de pedidos y cada producto (como contadores de interfaz).
    # Ojo: "total" es palabra reservada de DynamoDB; por eso todos los nombres van con alias (#...).
    nombres = {"#total": "total", "#pedidos": "pedidos"}
    nombres.update({f"#p{i}": f"P#{r_['id']}" for i, r_ in enumerate(resumen["productos"])})
    valores = {":total": resumen["total"], ":uno": 1}
    valores.update({f":c{i}": r_["cantidad"] for i, r_ in enumerate(resumen["productos"])})
    suma = "ADD #total :total, #pedidos :uno, " + ", ".join(f"#p{i} :c{i}" for i in range(len(resumen["productos"])))

    def libreta(sk):
        return {"Update": {"TableName": TABLA, "Key": {"PK": "VENTAS-PRUEBA" if prueba else "VENTAS", "SK": sk},
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


def usar_herramienta(nombre, entrada, chat_id, carrito, nombre_cliente, prueba=False, estado=None):
    estado = estado if estado is not None else {"update_id": "", "por_confirmar": None}
    if nombre == "buscar_producto":
        return buscar_producto(entrada.get("texto", ""))
    if nombre == "agregar_al_pedido":
        return agregar_al_pedido(carrito, entrada.get("id_producto"), entrada.get("cantidad"))
    if nombre == "quitar_del_pedido":
        return quitar_del_pedido(carrito, entrada.get("id_producto"))
    if nombre == "ver_pedido":
        return resumen_carrito(carrito)
    if nombre == "preparar_pedido":
        return preparar_pedido(carrito, entrada.get("direccion"), entrada.get("forma_pago", ""), estado)
    if nombre == "confirmar_pedido":
        return confirmar_pedido(chat_id, carrito, nombre_cliente, estado, prueba)
    return {"error": f"No existe la herramienta {nombre}"}


# Fichas de las herramientas, en el formato de Bedrock (Converse API)
def _ficha(nombre, descripcion, propiedades, requeridos=()):
    return {"toolSpec": {"name": nombre, "description": descripcion,
                         "inputSchema": {"json": {"type": "object", "properties": propiedades,
                                                  "required": list(requeridos)}}}}


HERRAMIENTAS = {"tools": [
    _ficha("buscar_producto", "Busca en el catálogo de Abarrotes Don Chuy. Devuelve los productos que coinciden, "
           "con id, presentación, precio en pesos y existencia (0 = agotado). Úsala antes de dar un precio "
           "(para saber si hay algo, bastan las listas de DISPONIBLES y AGOTADOS).",
           {"texto": {"type": "string", "description": "Lo que busca el cliente, ej. 'tortillas'"}}, ["texto"]),
    _ficha("agregar_al_pedido", "Pone un producto en el pedido con la cantidad TOTAL que quiere el cliente "
           "(si ya estaba, la reemplaza; no suma). Regresa el pedido con subtotales y total.",
           {"id_producto": {"type": "string", "description": "El id del catálogo, ej. 'TOR-MAIZ'"},
            "cantidad": {"type": "integer", "description": "Cantidad TOTAL de ese producto"}},
           ["id_producto", "cantidad"]),
    _ficha("quitar_del_pedido", "Quita un producto del pedido del cliente.",
           {"id_producto": {"type": "string"}}, ["id_producto"]),
    _ficha("ver_pedido", "Muestra cómo va el pedido del cliente: productos, cantidades, subtotales y total.", {}),
    _ficha("preparar_pedido", "Valida el pedido (productos, dirección y forma de pago) y regresa el resumen exacto "
           "para leérselo al cliente. Todavía NO lo guarda.",
           {"direccion": {"type": "object",
                          "description": "La dirección POR PARTES, tal como la dijo el cliente. No inventes partes.",
                          "properties": {
                              "calle": {"type": "string", "description": "Nombre de la calle"},
                              "numero": {"type": "string", "description": "Número exterior (e interior si hay), o 'S/N'"},
                              "colonia": {"type": "string", "description": "Colonia"},
                              "referencias": {"type": "string", "description": "Opcional: entre calles, color de casa"}},
                          "required": ["calle", "numero", "colonia"]},
            "forma_pago": {"type": "string", "enum": FORMAS_DE_PAGO}}, ["direccion", "forma_pago"]),
    _ficha("confirmar_pedido", "Guarda el pedido que ya preparaste. Úsala SOLO cuando el cliente responda que sí "
           "al resumen de preparar_pedido. No lleva datos: usa lo que el cliente ya aprobó.", {}),
]}


# ---------- El bucle del agente (Claude por Bedrock) ----------
def responder(chat_id, texto, nombre_cliente, mensajes, carrito, prueba=False, estado=None):
    """Igual que en la Fase 1: Claude puede usar herramientas varias veces antes de contestar."""
    mensajes.append({"role": "user", "content": texto})
    del mensajes[:-MAX_MENSAJES]
    while mensajes and mensajes[0]["role"] != "user":     # Claude necesita empezar con el cliente
        mensajes.pop(0)

    turno = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in mensajes]
    traza = {"herramientas": [], "tokens_entrada": 0, "tokens_salida": 0, "paradas": []}
    pedido_guardado = aviso_dado = reintento_dado = vacio_reintentado = False

    for _ in range(8):                                    # máximo 8 vueltas, por seguridad
        r = bedrock.converse(modelId=MODELO, system=[{"text": instrucciones(carrito)}], messages=turno,
                             toolConfig=HERRAMIENTAS, inferenceConfig={"maxTokens": 400})
        traza["tokens_entrada"] += r["usage"]["inputTokens"]
        traza["tokens_salida"] += r["usage"]["outputTokens"]
        salida = r["output"]["message"]
        traza["paradas"].append(r["stopReason"])   # por qué terminó Claude cada vuelta (para diagnosticar)

        # Claude intentó usar una herramienta pero la "escribió mal": se le da UNA oportunidad más,
        # en lugar de contestarle al cliente "me trabé".
        if r["stopReason"] in ("malformed_tool_use", "malformed_model_output") and not reintento_dado:
            reintento_dado = True
            traza["herramientas"].append("REINTENTO")
            continue

        if r["stopReason"] != "tool_use":
            texto_final = "".join(b.get("text", "") for b in salida["content"])
            # Claude terminó SIN decir nada (la causa real del "me trabé"): se le pide el texto UNA vez.
            if not texto_final.strip() and not vacio_reintentado:
                vacio_reintentado = True
                traza["herramientas"].append("SIN_TEXTO")
                turno[-1]["content"].append({"text": "[Aviso del sistema, no del cliente] Ahora contéstale al "
                                                     "cliente con un mensaje de texto breve."})
                continue
            # GUARDIA: ¿dice que ya quedó (confirmado o con folio) sin haber guardado el pedido de verdad?
            t = normal(texto_final)
            dice_que_quedo = "?" not in t and (re.search(r"\bconfirmad[oa]\b", t) or re.search(r"\bfolio\b", t))
            if dice_que_quedo and not pedido_guardado and carrito and not aviso_dado:
                aviso_dado = True
                traza["herramientas"].append("GUARDIA")
                turno.append(salida)
                turno.append({"role": "user", "content": [{"text": "[Aviso del sistema, no del cliente] Dijiste que "
                              "el pedido quedó, pero NO usaste confirmar_pedido y el pedido NO se guardó. "
                              "Si el cliente ya dijo que sí al resumen, usa confirmar_pedido; si no, usa "
                              "preparar_pedido o pregúntale lo que falta. Contéstale al cliente sin mencionar "
                              "este aviso."}]})
                continue
            break

        turno.append(salida)
        resultados = []
        for b in salida["content"]:
            if "toolUse" in b:
                uso = b["toolUse"]
                resultado = usar_herramienta(uso["name"], uso.get("input", {}), chat_id, carrito, nombre_cliente,
                                             prueba, estado)
                if prueba:   # el examen necesita ver qué pidió Claude y qué le contestó el código
                    traza.setdefault("detalle", []).append({"herramienta": uso["name"], "entrada": uso.get("input", {}),
                                                            "resultado": resultado})
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


def chat_del_dueno():
    """El chat_id de Don Chuy (Parameter Store), leído una vez por Lambda tibia."""
    global _dueno_cache
    if _dueno_cache is None:
        _dueno_cache = ssm.get_parameter(Name=PARAMETRO_DUENO)["Parameter"]["Value"]
    return _dueno_cache


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
    # Modo examen: solo llega invocando la Lambda directo (con permiso de IAM). La recepción arma
    # el mensaje con 4 campos fijos, así que desde Telegram nadie puede activarlo.
    prueba = mensaje.get("prueba") is True

    # ¿Ya se atendió? (ADR 002: la fila evita duplicados solo 5 minutos)
    if tabla.get_item(Key={"PK": f"MENSAJE#{update_id}", "SK": "PROCESADO"}).get("Item"):
        print(json.dumps({"evento": "DUPLICADO_IGNORADO", "update_id": update_id}))
        return

    # ¿Es Don Chuy con un comando? Se contesta con datos exactos de la tabla, sin IA (ADR 003).
    # Si no es el dueño, el mensaje sigue al agente como cualquier otro.
    comando = dueno.comando_de(texto)
    if comando in dueno.COMANDOS and str(chat_id) == chat_del_dueno():
        inicio = time.time()
        respuesta = dueno.atender(tabla, texto, datetime.now(HORA_MEXICO), CATALOGO_POR_ID)
        enviar_telegram(chat_id, respuesta)
        tabla.put_item(Item={"PK": f"MENSAJE#{update_id}", "SK": "PROCESADO",
                             "expira": int(time.time()) + HORAS_PLATICA * 3600})
        print(json.dumps({"evento": "COMANDO_DUENO", "comando": comando, "update_id": update_id,
                          "segundos": round(time.time() - inicio, 2)}))
        return respuesta

    # Leer la nota del cambio de turno: la plática y el carrito de este cliente.
    item = tabla.get_item(Key={"PK": f"CLIENTE#{chat_id}", "SK": "PLATICA"}).get("Item") or {}
    mensajes = item.get("mensajes", [])
    carrito = {k: _a_entero(v) for k, v in item.get("carrito", {}).items()}
    por_confirmar = item.get("por_confirmar")           # el resumen que el cliente ya vio (paso 1 de 2)
    if por_confirmar:
        por_confirmar["carrito"] = {k: _a_entero(v) for k, v in por_confirmar["carrito"].items()}

    if texto == "/start":                                 # /start = empezar de cero
        mensajes, carrito, texto, por_confirmar = [], {}, "Hola", None
    estado = {"update_id": update_id, "por_confirmar": por_confirmar}

    inicio = time.time()
    respuesta, traza = responder(chat_id, texto, nombre, mensajes, carrito, prueba, estado)
    if not prueba:
        enviar_telegram(chat_id, respuesta)

    # Anotar lo nuevo para el siguiente mensaje (se borra solo a las 24 h).
    expira = int(time.time()) + HORAS_PLATICA * 3600
    platica = {"PK": f"CLIENTE#{chat_id}", "SK": "PLATICA", "mensajes": mensajes, "carrito": carrito, "expira": expira}
    if estado["por_confirmar"]:
        platica["por_confirmar"] = estado["por_confirmar"]
    tabla.put_item(Item=platica)
    # Marca "ya procesado" (también se borra sola a las 24 h).
    tabla.put_item(Item={"PK": f"MENSAJE#{update_id}", "SK": "PROCESADO", "expira": expira})

    # TRAZA para CloudWatch: sin textos del cliente ni datos personales.
    traza.update({"evento": "TRAZA", "update_id": update_id, "segundos": round(time.time() - inicio, 2)})
    detalle = traza.pop("detalle", [])          # el detalle (con datos del cliente) no va a los logs
    if prueba:
        traza["prueba"] = True
    print(json.dumps(traza, ensure_ascii=False, default=str))
    if prueba:
        return {"respuesta": respuesta, "traza": traza, "detalle": detalle}
    return respuesta


def handler(event, context):
    """Punto de entrada: SQS entrega un mensaje a la vez. Si algo falla, la excepción hace
    que el mensaje regrese a la fila y se reintente; después de 3 fallos se va a la DLQ.
    Lo que regresa solo lo usa el examen (SQS lo ignora)."""
    resultados = [procesar(json.loads(record["body"])) for record in event["Records"]]
    return json.loads(json.dumps(resultados, default=str))   # Decimal -> texto, para poder regresarlo
