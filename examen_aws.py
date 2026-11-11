"""
Examen de conversaciones EN AWS (Fase 2).

Los mismos 8 casos de la Fase 1 (examen_conversaciones.py), pero contra el agente REAL:
la Lambda en AWS, Claude en Bedrock y DynamoDB. Solo se saltan Telegram y la fila:
el examen invoca la Lambda directo con "prueba": true.

En modo prueba (ver lambdas/agente/app.py):
  - los pedidos se guardan de verdad, pero con folio PR-xxxx
  - van a su propia libreta de ventas (VENTAS-PRUEBA) y no salen en /pendientes
  - la avisadora no le avisa a Don Chuy

Uso (desde la raíz del repo, con la sesión de AWS activa):
    python examen_aws.py
Resultados en salidas/ (no se sube a GitHub).
"""
import csv
import json
import os
import re
import time
import unicodedata

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

PERFIL = "personal"
REGION = "us-east-1"
FUNCION = "agente-pedidos-agente"
TABLA = "pedidos-don-chuy"

sesion = boto3.Session(profile_name=PERFIL, region_name=REGION)
# Una sola oportunidad por mensaje (si boto3 reintentara, Claude contestaría dos veces) y
# hasta 90 s de espera (la Lambda tiene 60 s como máximo).
lam = sesion.client("lambda", config=Config(read_timeout=90, retries={"total_max_attempts": 1}))
tabla = sesion.resource("dynamodb").Table(TABLA)
CODIGOS = {p["id"] for p in json.load(open("catalogo.json", encoding="utf-8"))}


def normal(texto):
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


DIRECCION = "Calle Roble 12, Colonia Centro"

# Los mismos casos de la Fase 1.
CASOS = [
    {"nombre": "Pedido normal",
     "mensajes": ["Qué onda, quiero 2 kilos de tortilla de maíz y un refresco de cola de 2 litros",
                  f"Mándalo a {DIRECCION}, pago en efectivo",
                  "Sí, confírmalo"],
     "debe_guardar": True, "productos": {"TOR-MAIZ": 2, "REF-COLA-2L": 1}, "total": 90},

    {"nombre": "Producto agotado (huevo)",
     "mensajes": ["Quiero un kilo de huevo",
                  f"Mándalo a {DIRECCION}, pago en efectivo",
                  "Sí, confírmalo"],
     "debe_guardar": False, "prohibidos": ["HUEVO"]},

    {"nombre": "Agotado (refresco de naranja)",
     "mensajes": ["Dame un refresco de naranja de 2 litros",
                  "Sí, ese mero, agrégalo"],
     "debe_guardar": False, "prohibidos": ["REF-NAR-2L"]},

    {"nombre": "Producto que no existe",
     "mensajes": ["¿Tienen cerveza?", "Entonces dame dos, porfa"],
     "debe_guardar": False, "no_ofrecer": ["naranja"]},

    {"nombre": "Cambio de opinión",
     "mensajes": ["Quiero 2 refrescos de cola de 2 litros y unas papas",
                  "Mejor quita las papas",
                  f"Mándalo a {DIRECCION}, pago en efectivo",
                  "Sí, confírmalo"],
     "debe_guardar": True, "productos": {"REF-COLA-2L": 2}, "total": 84},

    {"nombre": "Dirección incompleta",
     "mensajes": ["Quiero 1 kilo de tortilla de maíz",
                  "Mándalo a mi casa, pago en efectivo",
                  "Sí, confírmalo ya"],
     "debe_guardar": False},

    {"nombre": "Presión para confirmar sin datos",
     "mensajes": ["Un garrafón de agua",
                  "Ya confírmalo así, luego te paso la dirección"],
     "debe_guardar": False},

    {"nombre": "Forma de pago no aceptada",
     "mensajes": ["Quiero unas papas",
                  f"Mándalo a {DIRECCION}, pago con transferencia",
                  "Sí, confírmalo"],
     "debe_guardar": False},
]


def precios_de(valor, encontrados):
    """Junta todos los precios que regresaron las herramientas (precio, subtotal, total...)."""
    if isinstance(valor, dict):
        for k, v in valor.items():
            if k in ("precio", "precio_unitario", "subtotal", "total") and isinstance(v, (int, float)):
                encontrados.add(float(v))
            else:
                precios_de(v, encontrados)
    elif isinstance(valor, list):
        for v in valor:
            precios_de(v, encontrados)
    return encontrados


def hablar(chat_id, numero, texto):
    """Un mensaje del cliente falso -> la Lambda real, como si viniera de la fila."""
    mensaje = {"update_id": f"examen-{chat_id}-{numero}", "chat_id": chat_id,
               "nombre": "Cliente Examen", "texto": texto, "prueba": True}
    evento = {"Records": [{"body": json.dumps(mensaje)}]}
    r = lam.invoke(FunctionName=FUNCION, Payload=json.dumps(evento).encode())
    datos = json.loads(r["Payload"].read())
    if r.get("FunctionError"):
        raise RuntimeError(f"La Lambda falló: {datos.get('errorMessage')}")
    return datos[0]


corrida = int(time.time())          # cada corrida usa clientes nuevos: no hay pláticas viejas
filas, log, aprobados = [], [], 0
total_costo, total_segundos, total_mensajes = 0.0, 0.0, 0
inicio_examen = time.time()
print(f"Examen en AWS: {len(CASOS)} casos contra la Lambda {FUNCION}\n")

for n, caso in enumerate(CASOS, 1):
    chat_id = int(f"9{corrida}{n:02d}")
    respuestas, trazas, llamadas = [], [], []
    precios_conocidos, precios_inventados = set(), []
    log.append(f"===== Caso {n}: {caso['nombre']} =====")
    for i, texto in enumerate(caso["mensajes"], 1):
        r = hablar(chat_id, i, texto)
        respuestas.append(r["respuesta"])
        trazas.append(r["traza"])
        llamadas += r["detalle"]
        # 6. ¿Dio un precio que ninguna herramienta le dio? (la regla: precios solo con herramientas)
        precios_de([c["resultado"] for c in r["detalle"]], precios_conocidos)
        for m in re.findall(r"\$\s?(\d+(?:\.\d+)?)", r["respuesta"]):
            if float(m) not in precios_conocidos:
                precios_inventados.append(f"${m}")
        log += [f"Cliente: {texto}", f"Agente:  {r['respuesta']}",
                f"         herramientas={r['traza']['herramientas']} paradas={r['traza'].get('paradas')}", ""]

    pedidos = tabla.query(KeyConditionExpression=Key("PK").eq(f"CLIENTE#{chat_id}")
                          & Key("SK").begins_with("PEDIDO#"))["Items"]
    fallas = []

    # 1. ¿Guardó cuando debía?
    if caso["debe_guardar"] and len(pedidos) != 1:
        fallas.append("no guardó el pedido")
    if not caso["debe_guardar"] and pedidos:
        fallas.append("guardó un pedido que no debía")

    # 2. ¿Productos, total y folio correctos?
    if caso["debe_guardar"] and len(pedidos) == 1:
        p = pedidos[0]
        cantidades = {x["id"]: int(x["cantidad"]) for x in p["productos"]}
        if cantidades != caso["productos"]:
            fallas.append(f"productos {cantidades}")
        if int(p["total"]) != caso["total"]:
            fallas.append(f"total ${p['total']} (esperado ${caso['total']})")
        if not any(p["folio"] in r for r in respuestas):
            fallas.append("no le dio el folio al cliente")
        if not p.get("prueba"):
            fallas.append("el pedido no quedó marcado como prueba")

    # 3. ¿Agregó un producto agotado?
    for c in llamadas:
        if c["herramienta"] == "agregar_al_pedido" and c["entrada"].get("id_producto") in caso.get("prohibidos", []) \
                and "error" not in c["resultado"]:
            fallas.append(f"agregó {c['entrada'].get('id_producto')} agotado")

    # 4. ¿Usó un código que no existe? (adivinó)
    for c in llamadas:
        if c["herramienta"] in ("agregar_al_pedido", "quitar_del_pedido") \
                and c["entrada"].get("id_producto") not in CODIGOS:
            fallas.append(f"adivinó el código {c['entrada'].get('id_producto')}")

    # 4b. ¿Ofreció un producto agotado?
    for r in respuestas:
        for palabra in caso.get("no_ofrecer", []):
            if palabra in normal(r):
                fallas.append(f"ofreció '{palabra}' (agotado)")

    # 5. ¿Dio un folio sin haber guardado?
    if not pedidos and any("DC-" in r or "PR-" in r for r in respuestas):
        fallas.append("dio un folio falso")

    if precios_inventados:
        fallas.append(f"dio precios sin herramienta: {', '.join(precios_inventados)}")

    # Números del caso (de la TRAZA de cada mensaje)
    costo = sum(t["costo_usd"] for t in trazas)
    segundos = sum(t["segundos"] for t in trazas)
    guardias = sum(t["herramientas"].count("GUARDIA") for t in trazas)
    reintentos = sum(t["herramientas"].count("REINTENTO") for t in trazas)
    trabados = sum("me trabé" in r for r in respuestas)
    total_costo += costo
    total_segundos += segundos
    total_mensajes += len(trazas)

    ok = not fallas
    aprobados += ok
    notas = [x for x in (f"guardia {guardias}" if guardias else "", f"reintento {reintentos}" if reintentos else "",
                         f"'me trabé' {trabados}" if trabados else "") if x]
    print(f"{'APROBADO' if ok else 'FALLA   '} {n}. {caso['nombre']}  (${costo:.4f}, {segundos:.1f} s"
          + (", " + ", ".join(notas) if notas else "") + ")" + ("" if ok else f"  ->  {'; '.join(fallas)}"))
    filas.append({"caso": n, "nombre": caso["nombre"], "aprobado": ok, "fallas": "; ".join(fallas),
                  "mensajes": len(trazas), "costo_usd": round(costo, 6), "segundos": round(segundos, 2),
                  "guardia": guardias, "reintento": reintentos, "me_trabe": trabados,
                  "folio": pedidos[0]["folio"] if pedidos else "", "ultima_respuesta": respuestas[-1]})

print(f"\nResultado: {aprobados}/{len(CASOS)}")
print(f"Costo total: ${total_costo:.4f} USD en {total_mensajes} mensajes "
      f"(promedio ${total_costo / total_mensajes:.4f} por mensaje)")
print(f"Tiempo de respuesta promedio: {total_segundos / total_mensajes:.1f} s por mensaje "
      f"(examen completo: {time.time() - inicio_examen:.0f} s)")

os.makedirs("salidas", exist_ok=True)
with open("salidas/examen_aws.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=filas[0].keys())
    w.writeheader()
    w.writerows(filas)
open("salidas/examen_aws_log.txt", "w", encoding="utf-8").write("\n".join(log))
print("Detalle de cada plática en salidas/examen_aws_log.txt")
