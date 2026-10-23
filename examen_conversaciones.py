"""
Examen de conversaciones del Agente #3 (cierra la Fase 1).

Un "cliente falso" le escribe al empleado varios mensajes seguidos, SIN Telegram.
Al final revisamos con datos, no a ojo:
  - ¿Guardó el pedido cuando debía (y NO lo guardó cuando no debía)?
  - ¿El total es correcto y lleva solo los productos correctos?
  - ¿Usó códigos que sí existen (no los adivinó)?
  - ¿Solo ofreció productos con existencia (no recomendó agotados)?
  - ¿Nunca dio un folio sin haber guardado el pedido?

Los pedidos del examen van a salidas/pedidos_examen.json (no tocan los pedidos reales).
Uso:  python examen_conversaciones.py
"""
import contextlib
import csv
import io
import json
import os

import empleado

# Los pedidos del examen van a otro archivo
os.makedirs("salidas", exist_ok=True)
empleado.ARCHIVO_PEDIDOS = "salidas/pedidos_examen.json"
json.dump([], open(empleado.ARCHIVO_PEDIDOS, "w", encoding="utf-8"))

DIRECCION = "Calle Roble 12, Colonia Centro"

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

# Espiamos las herramientas: guardamos qué pidió Claude y qué le respondió el código
_original = empleado.usar_herramienta
llamadas = []
def espia(nombre, entrada, chat_id, nombre_cliente):
    resultado = _original(nombre, entrada, chat_id, nombre_cliente)
    llamadas.append({"herramienta": nombre, "entrada": entrada, "resultado": resultado})
    return resultado
empleado.usar_herramienta = espia


filas, aprobados, log = [], 0, []
print(f"🧪 Examen de conversaciones: {len(CASOS)} casos\n")

for n, caso in enumerate(CASOS, 1):
    chat_id = 900000 + n
    empleado.conversaciones.pop(chat_id, None)
    empleado.pedidos_en_curso.pop(chat_id, None)
    llamadas.clear()
    respuestas, salida = [], io.StringIO()

    with contextlib.redirect_stdout(salida):            # escondemos el detalle; va al log
        for m in caso["mensajes"]:
            print(f"📩 Cliente: {m}")
            respuestas.append(empleado.responder_con_claude(chat_id, m, "Cliente Examen"))
    log.append(f"===== Caso {n}: {caso['nombre']} =====\n{salida.getvalue()}")

    pedidos = [p for p in json.load(open(empleado.ARCHIVO_PEDIDOS, encoding="utf-8")) if p["chat_id"] == chat_id]
    fallas = []

    # 1. ¿Guardó cuando debía?
    if caso["debe_guardar"] and len(pedidos) != 1:
        fallas.append("no guardó el pedido")
    if not caso["debe_guardar"] and pedidos:
        fallas.append("guardó un pedido que no debía")

    # 2. ¿Productos y total correctos?
    if caso["debe_guardar"] and len(pedidos) == 1:
        p = pedidos[0]
        cantidades = {x["id"]: x["cantidad"] for x in p["productos"]}
        if cantidades != caso["productos"]:
            fallas.append(f"productos {cantidades}")
        if p["total"] != caso["total"]:
            fallas.append(f"total ${p['total']} (esperado ${caso['total']})")
        if not any(p["folio"] in r for r in respuestas):
            fallas.append("no le dio el folio al cliente")

    # 3. ¿Agregó un producto agotado?
    for c in llamadas:
        if c["herramienta"] == "agregar_al_pedido" and c["entrada"].get("id_producto") in caso.get("prohibidos", []) \
                and "error" not in c["resultado"]:
            fallas.append(f"agregó {c['entrada'].get('id_producto')} agotado")

    # 4. ¿Usó un código que no existe? (adivinó)
    for c in llamadas:
        if c["herramienta"] in ("agregar_al_pedido", "quitar_del_pedido") \
                and c["entrada"].get("id_producto") not in empleado.CATALOGO_POR_ID:
            fallas.append(f"adivinó el código {c['entrada'].get('id_producto')}")

    # 4b. ¿Ofreció un producto agotado? (lo nombra en su respuesta)
    for r in respuestas:
        for palabra in caso.get("no_ofrecer", []):
            if palabra in empleado.normal(r):
                fallas.append(f"ofreció '{palabra}' (agotado)")

    # 5. ¿Dio un folio sin haber guardado?
    if not pedidos and any("DC-" in r for r in respuestas):
        fallas.append("dio un folio falso")

    ok = not fallas
    aprobados += ok
    guardias = salida.getvalue().count("🛑")
    nota = f" (la guardia actuó {guardias} vez)" if guardias else ""
    print(f"{'✅' if ok else '❌'} {n}. {caso['nombre']}{nota}" + ("" if ok else f"  →  {'; '.join(fallas)}"))
    filas.append({"caso": n, "nombre": caso["nombre"], "aprobado": ok, "fallas": "; ".join(fallas),
                  "guardia": guardias, "ultima_respuesta": respuestas[-1]})

print(f"\n🎯 Resultado: {aprobados}/{len(CASOS)}")

with open("salidas/examen_conversaciones.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=filas[0].keys())
    w.writeheader()
    w.writerows(filas)
open("salidas/examen_conversaciones_log.txt", "w", encoding="utf-8").write("\n".join(log))
print("📄 Detalle de cada plática en salidas/examen_conversaciones_log.txt")
