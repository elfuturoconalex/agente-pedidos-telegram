# Bitácora de aprendizaje · Agente de Pedidos por Telegram

Cada sesión de trabajo queda registrada: qué hice, qué aprendí y qué problemas resolví.

---

## Sesión 1: Arranque del proyecto
*18 de octubre de 2026*

### Qué hice
- Definí el agente: pedidos por Telegram para un negocio ficticio (Abarrotes Don Chuy).
- Hice el diagrama de arquitectura preliminar.
- Creé el repositorio y la estimación de tiempo y costo.

### Siguiente
- Fase 1: crear el bot en Telegram y hacer que el agente converse desde mi Mac.

---

## Sesión 2: El bot vive, y luego habla con Claude (Fase 1)
*19 de octubre de 2026*

### Qué hice
- Creé el bot **Abarrotes Don Chuy** con @BotFather y guardé su token en `.env` (nunca en GitHub).
- `eco.py`: un bot que repite lo que le escriben. Mi Mac le pregunta a Telegram si hay mensajes nuevos (**polling**).
- Hice el bot resistente a cortes de internet: reintenta en lugar de caerse y nunca muestra el token en los errores.
- `empleado.py`: ahora contesta **Claude como empleado de la tienda**, con **memoria** de la conversación por cliente.
- Separé las instrucciones en **TONO** (configurable por cliente; para la demo, de cuates) y **REGLAS** (no inventar, no prometer lo que no puede hacer).

### Resultados
| Prueba | Resultado |
|---|---|
| "Hola" → "Eco: Hola" | ✅ Mi Mac y Telegram se hablan |
| "Que sean 2 kilos" después de preguntar por tortillas | ✅ Recordó que eran tortillas |
| "¿A qué hora cierran?" | ✅ No inventó el horario |
| "¿Tienen tortillas?" | ⚠️ Dio a entender que sí había, sin catálogo |
| Promesas | ⚠️ "Déjame tu número", "checo con los compas": cosas que no puede hacer |

### Qué aprendí
- **Polling vs. webhook:** en mi Mac yo le pregunto a Telegram (reviso el buzón); en AWS Telegram me avisará (el cartero toca el timbre).
- **Telegram guarda los mensajes** hasta 24 horas: al prender el bot llegaron los que mandé con el bot apagado.
- **Un mensaje se puede perder:** si se marca como leído y falla la respuesta, no se reintenta. En la Fase 2: reintentos e idempotencia.
- **El tono es configurable, las reglas no:** buen argumento de venta.
- **Las reglas escritas reducen los inventos, pero no los eliminan.** Cuando al modelo le falta información, la rellena. La solución es darle herramientas con datos reales (catálogo).

### Problemas y cómo los resolví
- **El archivo se llamaba "   .env" (3 espacios antes del punto)** → el `.gitignore` no lo protegía y se iba a subir con el token. Lo renombré. Causa: el botón de copiar trae la sangría cuando el texto está dentro de una lista. Regla: nombres cortos se escriben a mano.
- **El token se expuso dos veces** (en una revisión y en la captura de un error que imprimía la URL) → lo revoqué con `/revoke` en @BotFather y corregí el programa para que nunca lo muestre.
- **ConnectTimeout con Telegram** → cortes de red; el bot ahora reintenta solo.
- **HTTPError después de revocar** → el `.env` tenía el token viejo; lo copié de nuevo desde /mybots.

### Siguiente
- Darle a Claude **herramientas**: un catálogo ficticio (`ver_catalogo`) para que consulte en lugar de prometer, y empezar a armar el pedido.

---

## Sesión 3: Herramientas, el catálogo y el primer pedido guardado (Fase 1)
*20 de octubre de 2026*

### Qué hice
- `catalogo.json`: 20 productos ficticios con código, nombre, presentación, precio, existencia y sinónimos (el huevo y el refresco de naranja, agotados a propósito).
- Primera **herramienta** de Claude: `buscar_producto`, que busca en el catálogo aunque el cliente escriba sin acentos o con otras palabras.
- Puse **solo los nombres** de los productos en las instrucciones; el **precio y la existencia** se consultan siempre con la herramienta.
- Herramientas para armar el pedido: `agregar_al_pedido`, `quitar_del_pedido`, `ver_pedido` y `confirmar_pedido`.
- **El código hace las cuentas**, no Claude: subtotales y total salen del catálogo.
- **Validaciones en el código:** que el producto exista, cantidad entera y positiva, que haya existencia, dirección completa y pago en efectivo o tarjeta.
- `confirmar_pedido` guarda el pedido en `salidas/pedidos.json` (fuera de GitHub) con un **folio** (`DC-0001`).
- Una **guardia** en el código que revisa a Claude: si dice "confirmado" sin haber guardado el pedido, se lo regresa para que lo haga bien.

### Resultados
| Prueba | Resultado |
|---|---|
| "¿Tienen tortillas?" | ✅ Buscó en el catálogo y dio precio real |
| "¿Qué refrescos tienen?" (antes de la lista de nombres) | ⚠️ Inventó Coca, Sprite y Fanta |
| "¿Tienen jugos?" | ⚠️ Inventó jugos → corregido con la lista de nombres |
| Pedido completo (antes de la guardia) | ❌ Dijo "confirmado" pero no se guardó |
| Pedido completo (con la guardia) | ✅ Guardado como **DC-0001**: 2 kg de tortilla + refresco de cola 2 L = $90 |

### Qué aprendí
- **Una herramienta es una función de Python** más una "ficha" que le explica a Claude para qué sirve y qué datos necesita. Claude **pide** usarla; mi código la **ejecuta** y le regresa el resultado.
- **El bucle del agente:** Claude pide herramienta → el código la usa → Claude lee el resultado → repite hasta tener la respuesta final.
- **Por qué JSON:** es texto ordenado que Python lee fácil; más adelante el mismo formato pasa a DynamoDB.
- **Lo que casi no cambia va en las instrucciones; lo que cambia seguido va en una herramienta:** los nombres en el prompt, el precio y la existencia en el catálogo.
- **El dinero y las reglas del negocio los decide el código, no el modelo.** Claude conversa; el código valida y calcula.
- **El modelo puede decir que hizo algo que no hizo.** No basta con pedírselo en las instrucciones: hay que verificarlo en el código (la guardia).
- Las piezas de un agente (modelo, instrucciones, herramientas, bucle, memoria, permisos, regla de parada y manejo de errores) ya están todas en `empleado.py`.

### Problemas y cómo los resolví
- **Claude inventaba productos** (Coca, Sprite, Fanta, jugos) → le di la lista de nombres del catálogo y la regla de usar la herramienta incluso para preguntas generales.
- **Claude dijo "confirmado" sin usar `confirmar_pedido`** → regla en las instrucciones + guardia en el código. El pedido DC-0001 ya se guardó.
- **Pendientes detectados** para el examen: a veces adivina el código del producto antes de buscarlo, y ofreció el refresco de naranja sin revisar que estaba agotada.

### Siguiente
- **Examen de conversaciones** para cerrar la Fase 1: pedido normal, producto agotado, producto que no existe, cambio de opinión, dirección incompleta y nunca "confirmado" sin guardar.
