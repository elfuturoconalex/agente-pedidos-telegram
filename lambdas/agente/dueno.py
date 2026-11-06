"""
Comandos de DON CHUY (ADR 003) — respuestas exactas leídas de la tabla, SIN IA.

Por qué sin IA: son números de dinero. Un comando fijo los lee tal cual de DynamoDB,
contesta en milisegundos y no gasta en Bedrock. La IA se queda platicando con los clientes.

  /pendientes            pedidos nuevos, del más viejo al más nuevo (índice GSI1)
  /ventas                total de la semana y del mes, y lo más vendido (libretas VENTAS)
  /entregado_DC0005      marca el pedido como entregado y lo saca de pendientes
  (también acepta "/entregado DC-0005")
"""
import re
from datetime import datetime

from boto3.dynamodb.conditions import Key

COMANDOS = ("/pendientes", "/ventas", "/entregado")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def comando_de(texto):
    """'/entregado_DC0005' o '/entregado@MiBot DC-0005' -> '/entregado'."""
    palabra = (texto or "").strip().split(" ")[0].lower()
    return palabra.split("@")[0].split("_")[0]


def pesos(v):
    v = float(v)
    return f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"


def boton_entregado(folio):
    """Telegram vuelve 'tocable' un comando sin espacios ni guiones: /entregado_DC0005."""
    return "/entregado_" + folio.replace("-", "")


def _pedidos_nuevos(tabla):
    r = tabla.query(IndexName="GSI1", KeyConditionExpression=Key("GSI1PK").eq("ESTADO#nuevo"),
                    ScanIndexForward=True)   # del más viejo al más nuevo (la fecha va en GSI1SK)
    return r["Items"]


def pendientes(tabla):
    pedidos = _pedidos_nuevos(tabla)
    if not pedidos:
        return "✅ No hay pedidos pendientes."
    renglones = [f"📋 Pedidos pendientes: {len(pedidos)}", ""]
    for p in pedidos:
        hora = datetime.fromisoformat(p["fecha"])
        renglones += [f"{p['folio']} · {hora:%d/%m %H:%M} · {pesos(p['total'])} · {p['forma_pago']}",
                      f"   {p['direccion']}",
                      f"   {boton_entregado(p['folio'])}", ""]
    return "\n".join(renglones).strip()


def ventas(tabla, ahora, catalogo_por_id):
    iso = ahora.isocalendar()
    semana = tabla.get_item(Key={"PK": "VENTAS", "SK": f"SEMANA#{iso[0]}-W{iso[1]:02d}"}).get("Item") or {}
    mes = tabla.get_item(Key={"PK": "VENTAS", "SK": f"MES#{ahora:%Y-%m}"}).get("Item") or {}

    def linea(nombre, libreta):
        n = int(libreta.get("pedidos", 0))
        return f"{nombre}: {pesos(libreta.get('total', 0))} en {n} pedido{'s' if n != 1 else ''}"

    renglones = ["📊 Ventas", linea("Esta semana", semana), linea(f"Este mes ({MESES[ahora.month - 1]})", mes)]

    # Lo más vendido del mes: los contadores "P#<id>" de la libreta del mes.
    productos = sorted(((k[2:], int(v)) for k, v in mes.items() if k.startswith("P#")), key=lambda x: -x[1])
    if productos:
        renglones += ["", "Lo más vendido del mes:"]
        for i, (id_prod, cantidad) in enumerate(productos[:3], 1):
            prod = catalogo_por_id.get(id_prod)
            nombre = f"{prod['nombre']} ({prod['presentacion']})" if prod else id_prod
            renglones.append(f"{i}. {nombre} — {cantidad}")
    return "\n".join(renglones)


def entregado(tabla, texto, ahora):
    m = re.search(r"DC-?(\d{4})", texto.upper())
    if not m:
        return "¿Cuál pedido? Toca el comando que viene en el aviso, o escribe por ejemplo: /entregado DC-0005"
    folio = f"DC-{m.group(1)}"

    pedido = next((p for p in _pedidos_nuevos(tabla) if p["folio"] == folio), None)
    if not pedido:
        return f"No encontré {folio} en pendientes. Puede que ya esté entregado; revisa /pendientes."

    # Cambiar la etiqueta del índice: de ESTADO#nuevo a ESTADO#entregado (sale de /pendientes).
    # La condición evita marcarlo dos veces si el comando llega repetido.
    try:
        tabla.update_item(Key={"PK": pedido["PK"], "SK": pedido["SK"]},
                          UpdateExpression="SET estado = :e, GSI1PK = :g, entregado = :f",
                          ConditionExpression="GSI1PK = :nuevo",
                          ExpressionAttributeValues={":e": "entregado", ":g": "ESTADO#entregado",
                                                     ":f": ahora.isoformat(timespec="seconds"),
                                                     ":nuevo": "ESTADO#nuevo"})
    except tabla.meta.client.exceptions.ConditionalCheckFailedException:
        return f"{folio} ya estaba marcado como entregado."
    return f"✅ {folio} marcado como entregado ({pesos(pedido['total'])})."


def atender(tabla, texto, ahora, catalogo_por_id):
    comando = comando_de(texto)
    if comando == "/pendientes":
        return pendientes(tabla)
    if comando == "/ventas":
        return ventas(tabla, ahora, catalogo_por_id)
    return entregado(tabla, texto, ahora)
