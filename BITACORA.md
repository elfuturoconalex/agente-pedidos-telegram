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

