"""
Paso 2 del Agente #3: el bot ya no repite; contesta Claude como empleado
de Abarrotes Don Chuy (negocio ficticio) y recuerda la conversación.

Sesión 3: Claude ya tiene HERRAMIENTAS:
  - buscar_producto: consulta el catálogo (catalogo.json): precios y existencias reales.
  - agregar_al_pedido / quitar_del_pedido / ver_pedido: arman el pedido del cliente.
  - confirmar_pedido: guarda el pedido como DATOS ESTRUCTURADOS en salidas/pedidos.json.
Los precios y el total los calcula el CÓDIGO, nunca Claude.

Uso:  python empleado.py      (para detenerlo: Ctrl + C)
Necesita en .env:  TELEGRAM_BOT_TOKEN=...  y  ANTHROPIC_API_KEY=...
"""
import json
import os
import time
import unicodedata
from datetime import datetime

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]       # nunca se imprime
API = f"https://api.telegram.org/bot{TOKEN}"
claude = Anthropic()                           # lee ANTHROPIC_API_KEY del .env

MODELO = "claude-haiku-4-5"
MAX_MENSAJES = 20                              # memoria: últimos 20 mensajes por cliente

# El TONO se puede cambiar por cliente sin tocar las REGLAS.
# Para la demo: de cuates. Un despacho o una clínica elegiría otro.
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
  Si no sabes el id, primero usa buscar_producto.
- Nunca calcules precios ni totales tú: usa los que regresan las herramientas.
- Antes de cerrar, pide la dirección de entrega y la forma de pago (efectivo o tarjeta).
- Lee el resumen al cliente (productos, cantidades, total, dirección y pago) y pregúntale
  si está correcto. Usa confirmar_pedido SOLO después de que diga que sí.
- El pedido solo existe si confirmar_pedido regresa un folio. Nunca digas que el pedido
  está confirmado sin haberla usado, y al confirmar dale al cliente su folio.
- Si una herramienta regresa un error, explícaselo al cliente con tus palabras."""

# La lista de productos (SIN precios ni existencias) va en las instrucciones,
# para que Claude sepa qué maneja la tienda y no invente marcas o productos.
# Precio y existencia cambian, por eso siempre se consultan con la herramienta.
_catalogo = json.load(open("catalogo.json", encoding="utf-8"))
LISTA_PRODUCTOS = "\n".join(sorted({f"- {p['nombre']}" for p in _catalogo}))

PERSONALIDAD = (REGLAS + "\n\nProductos que maneja la tienda (no hay otros, ni otras marcas o sabores):\n"
                + LISTA_PRODUCTOS + "\n\nTono:\n" + TONO)

# ---------- La herramienta: buscar en el catálogo ----------
CATALOGO = json.load(open("catalogo.json", encoding="utf-8"))


def normal(texto):
    """Minúsculas y sin acentos, para que 'Azúcar' y 'azucar' sean lo mismo."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def buscar_producto(texto):
    """Devuelve los productos del catálogo que coinciden con lo que busca el cliente."""
    palabras = [p for p in normal(texto).split() if len(p) > 2]
    encontrados = []
    for prod in CATALOGO:
        donde = normal(" ".join([prod["nombre"], prod["presentacion"]] + prod["sinonimos"]))
        if any(p in donde for p in palabras):
            encontrados.append({k: prod[k] for k in ("id", "nombre", "presentacion", "precio", "existencia")})
    return encontrados[:6]


# ---------- Herramientas del pedido ----------
CATALOGO_POR_ID = {p["id"]: p for p in CATALOGO}
pedidos_en_curso = {}            # chat_id -> {id_producto: cantidad}   (el "carrito")
ARCHIVO_PEDIDOS = "salidas/pedidos.json"
FORMAS_DE_PAGO = ["efectivo", "tarjeta"]


def resumen_carrito(chat_id):
    """El código (no Claude) arma el resumen y calcula los totales."""
    carrito = pedidos_en_curso.get(chat_id, {})
    renglones = []
    for id_prod, cantidad in carrito.items():
        prod = CATALOGO_POR_ID[id_prod]
        renglones.append({"id": id_prod, "producto": f"{prod['nombre']} ({prod['presentacion']})",
                          "cantidad": cantidad, "precio_unitario": prod["precio"],
                          "subtotal": cantidad * prod["precio"]})
    return {"productos": renglones, "total": sum(r["subtotal"] for r in renglones)}


def agregar_al_pedido(chat_id, id_producto, cantidad):
    prod = CATALOGO_POR_ID.get(id_producto)
    if prod is None:
        return {"error": f"No existe el producto '{id_producto}'. Usa buscar_producto para ver los ids."}
    if not isinstance(cantidad, int) or cantidad < 1:
        return {"error": "La cantidad debe ser un número entero mayor a 0."}
    carrito = pedidos_en_curso.setdefault(chat_id, {})
    nueva = carrito.get(id_producto, 0) + cantidad
    if nueva > prod["existencia"]:
        return {"error": f"Solo hay {prod['existencia']} de {prod['nombre']} ({prod['presentacion']})."}
    carrito[id_producto] = nueva
    return {"ok": True, "pedido": resumen_carrito(chat_id)}


def quitar_del_pedido(chat_id, id_producto):
    carrito = pedidos_en_curso.get(chat_id, {})
    if id_producto not in carrito:
        return {"error": "Ese producto no está en el pedido."}
    del carrito[id_producto]
    return {"ok": True, "pedido": resumen_carrito(chat_id)}


def ver_pedido(chat_id):
    return resumen_carrito(chat_id)


def confirmar_pedido(chat_id, nombre_cliente, direccion, forma_pago):
    """Valida y guarda el pedido como datos estructurados."""
    resumen = resumen_carrito(chat_id)
    errores = []
    if not resumen["productos"]:
        errores.append("El pedido está vacío.")
    if not direccion or len(direccion.strip()) < 8:
        errores.append("Falta una dirección de entrega completa (calle, número y colonia).")
    if forma_pago not in FORMAS_DE_PAGO:
        errores.append(f"La forma de pago debe ser una de: {', '.join(FORMAS_DE_PAGO)}.")
    if errores:
        return {"error": " ".join(errores)}

    os.makedirs("salidas", exist_ok=True)
    pedidos = json.load(open(ARCHIVO_PEDIDOS, encoding="utf-8")) if os.path.exists(ARCHIVO_PEDIDOS) else []
    pedido = {
        "folio": f"DC-{len(pedidos) + 1:04d}",
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "chat_id": chat_id,
        "cliente": nombre_cliente,
        "productos": resumen["productos"],
        "total": resumen["total"],
        "direccion": direccion.strip(),
        "forma_pago": forma_pago,
        "estado": "nuevo",
    }
    pedidos.append(pedido)
    json.dump(pedidos, open(ARCHIVO_PEDIDOS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    pedidos_en_curso.pop(chat_id, None)          # carrito vacío para el siguiente pedido
    print(f"   🧾 Pedido {pedido['folio']} guardado · total ${pedido['total']}")
    return {"ok": True, "folio": pedido["folio"], "total": pedido["total"]}


# Las "fichas" de las herramientas que le explicamos a Claude
HERRAMIENTAS = [
    {
        "name": "buscar_producto",
        "description": "Busca en el catálogo de Abarrotes Don Chuy. Devuelve los productos que coinciden, "
                       "con id, presentación, precio en pesos y existencia (0 = agotado). "
                       "Úsala siempre antes de dar precios o confirmar si hay algo.",
        "input_schema": {"type": "object",
                         "properties": {"texto": {"type": "string", "description": "Lo que busca el cliente, ej. 'tortillas'"}},
                         "required": ["texto"]},
    },
    {
        "name": "agregar_al_pedido",
        "description": "Agrega un producto al pedido del cliente. Regresa el pedido con subtotales y total.",
        "input_schema": {"type": "object",
                         "properties": {"id_producto": {"type": "string", "description": "El id del catálogo, ej. 'TOR-MAIZ'"},
                                        "cantidad": {"type": "integer", "description": "Cuántas unidades (kilos, botellas, paquetes)"}},
                         "required": ["id_producto", "cantidad"]},
    },
    {
        "name": "quitar_del_pedido",
        "description": "Quita un producto del pedido del cliente.",
        "input_schema": {"type": "object",
                         "properties": {"id_producto": {"type": "string"}},
                         "required": ["id_producto"]},
    },
    {
        "name": "ver_pedido",
        "description": "Muestra cómo va el pedido del cliente: productos, cantidades, subtotales y total.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "confirmar_pedido",
        "description": "Guarda el pedido. Úsala SOLO después de leerle el resumen al cliente y que diga que sí.",
        "input_schema": {"type": "object",
                         "properties": {"direccion": {"type": "string", "description": "Calle, número y colonia"},
                                        "forma_pago": {"type": "string", "enum": FORMAS_DE_PAGO}},
                         "required": ["direccion", "forma_pago"]},
    },
]


def usar_herramienta(nombre_herr, entrada, chat_id, nombre_cliente):
    """Ejecuta la herramienta que pidió Claude y regresa el resultado."""
    if nombre_herr == "buscar_producto":
        return buscar_producto(entrada.get("texto", ""))
    if nombre_herr == "agregar_al_pedido":
        return agregar_al_pedido(chat_id, entrada.get("id_producto"), entrada.get("cantidad"))
    if nombre_herr == "quitar_del_pedido":
        return quitar_del_pedido(chat_id, entrada.get("id_producto"))
    if nombre_herr == "ver_pedido":
        return ver_pedido(chat_id)
    if nombre_herr == "confirmar_pedido":
        return confirmar_pedido(chat_id, nombre_cliente, entrada.get("direccion", ""), entrada.get("forma_pago", ""))
    return {"error": f"No existe la herramienta {nombre_herr}"}


conversaciones = {}   # chat_id -> lista de mensajes {"role", "content"}


def recibir_mensajes(desde):
    r = requests.get(f"{API}/getUpdates", params={"offset": desde, "timeout": 30}, timeout=40)
    r.raise_for_status()
    return r.json()["result"]


def enviar(chat_id, texto):
    requests.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": texto}, timeout=10)


def responder_con_claude(chat_id, texto, nombre_cliente="cliente"):
    historial = conversaciones.setdefault(chat_id, [])
    historial.append({"role": "user", "content": texto})
    del historial[:-MAX_MENSAJES]                     # olvidamos lo más viejo
    if historial[0]["role"] != "user":                # Claude necesita empezar con el cliente
        historial.pop(0)

    # Durante este turno, Claude puede usar herramientas varias veces (el loop del agente).
    # Esas idas y vueltas viven en "turno"; en la memoria solo guardamos la respuesta final.
    turno = list(historial)
    tokens_in = tokens_out = 0
    pedido_guardado = False                            # ¿confirmar_pedido funcionó en este turno?
    aviso_dado = False
    for _ in range(8):                                 # máximo 8 vueltas, por seguridad
        r = claude.messages.create(model=MODELO, max_tokens=400, system=PERSONALIDAD,
                                   tools=HERRAMIENTAS, messages=turno)
        tokens_in += r.usage.input_tokens
        tokens_out += r.usage.output_tokens

        if r.stop_reason != "tool_use":                # ya contestó...
            texto_final = "".join(b.text for b in r.content if b.type == "text")
            # GUARDIA del harness: ¿dice "confirmado" sin haber guardado el pedido de verdad?
            if "confirmad" in normal(texto_final) and not pedido_guardado and pedidos_en_curso.get(chat_id) and not aviso_dado:
                print("   🛑 Claude dijo 'confirmado' sin usar confirmar_pedido: se lo regresamos")
                aviso_dado = True
                turno.append({"role": "assistant", "content": r.content})
                turno.append({"role": "user", "content": "[Aviso del sistema, no del cliente] Dijiste que el pedido está "
                              "confirmado, pero NO usaste confirmar_pedido y el pedido NO se guardó. Si el cliente ya "
                              "dijo que sí, usa confirmar_pedido ahora con su dirección y forma de pago; si no, pregúntale."})
                continue
            break                                       # ...y es verdad: salimos del loop

        turno.append({"role": "assistant", "content": r.content})
        resultados = []
        for bloque in r.content:
            if bloque.type == "tool_use":
                resultado = usar_herramienta(bloque.name, bloque.input, chat_id, nombre_cliente)
                if bloque.name == "confirmar_pedido" and isinstance(resultado, dict) and resultado.get("ok"):
                    pedido_guardado = True
                marca = "❌" if isinstance(resultado, dict) and "error" in resultado else "🔧"
                print(f"   {marca} {bloque.name}({json.dumps(bloque.input, ensure_ascii=False)})")
                resultados.append({"type": "tool_result", "tool_use_id": bloque.id,
                                   "content": json.dumps(resultado, ensure_ascii=False)})
        turno.append({"role": "user", "content": resultados})

    respuesta = "".join(b.text for b in r.content if b.type == "text").replace("**", "").strip()
    if not respuesta:
        respuesta = "Perdón, me trabé tantito. ¿Me lo repites?"
    historial.append({"role": "assistant", "content": respuesta})

    costo = tokens_in / 1e6 * 1 + tokens_out / 1e6 * 5
    print(f"   🤖 {respuesta}\n   💰 {tokens_in} + {tokens_out} tokens · ${costo:.5f} USD")
    return respuesta


print("🛒 Abarrotes Don Chuy abierto. Escríbele al bot en Telegram. (Ctrl + C para cerrar)")
siguiente = 0
try:
    while True:
        try:
            updates = recibir_mensajes(siguiente)
        except requests.HTTPError as e:
            codigo = e.response.status_code
            print(f"⚠️  Telegram respondió {codigo}. Reintento en 5 s...")
            time.sleep(5)
            continue
        except requests.RequestException as e:
            print(f"⚠️  Sin conexión con Telegram ({type(e).__name__}). Reintento en 5 s...")
            time.sleep(5)
            continue

        for update in updates:
            siguiente = update["update_id"] + 1
            mensaje = update.get("message")
            if not mensaje or "text" not in mensaje:
                continue
            chat_id = mensaje["chat"]["id"]
            nombre = mensaje["from"].get("first_name", "cliente")
            texto = mensaje["text"]
            print(f"📩 {nombre}: {texto}")

            if texto == "/start":
                conversaciones.pop(chat_id, None)     # /start = empezar de cero
                pedidos_en_curso.pop(chat_id, None)
                texto = "Hola"
            try:
                respuesta = responder_con_claude(chat_id, texto, nombre)
            except Exception as e:
                print(f"⚠️  Claude no respondió ({type(e).__name__}).")
                respuesta = "Perdón, tuve un problemita. ¿Me lo repites en un momento?"
            try:
                enviar(chat_id, respuesta)
            except requests.RequestException as e:
                print(f"⚠️  No se pudo responder ({type(e).__name__}).")
except KeyboardInterrupt:
    print("\n👋 Tienda cerrada.")
