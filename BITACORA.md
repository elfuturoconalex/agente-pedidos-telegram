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

---

## Sesión 4: Examen de conversaciones, cierre de la Fase 1
*22 de octubre de 2026*

### Qué hice
- `examen_conversaciones.py`: un **cliente falso** que le escribe al agente 8 pláticas completas, sin Telegram, y revisa los resultados con datos.
- Casos: pedido normal, huevo agotado, refresco de naranja agotado, producto que no existe, cambio de opinión, dirección incompleta, presión para confirmar sin datos y pago no aceptado.
- Los pedidos del examen van a un archivo aparte (`salidas/pedidos_examen.json`) para no mezclarse con los reales.
- Ajusté `empleado.py` para que el examen pueda usar al empleado sin abrir Telegram (`if __name__ == "__main__"`).

### Resultados
| Intento | Resultado | Qué encontró |
|---|---|---|
| 1 | 6/8 | Inventó el código `AGUA-GARF20`; ofreció refresco de naranja agotado |
| 2 | 6/8 | Agregó dos veces los refrescos: el cliente vio $84 y se guardó $168 |
| 3 | 7/8 | Seguía ofreciendo el refresco de naranja |
| 4 | ✅ 8/8 | Todo correcto |

En el intento 1 la **guardia** actuó: Claude dijo "confirmado" sin guardar y la guardia lo corrigió (pedido guardado).

### Qué aprendí
- **La memoria guarda lo que Claude dijo, no lo que hizo ni lo que vio.** Por eso olvidaba los códigos y volvía a agregar productos.
- **Idempotencia:** hacer lo mismo dos veces debe dar el mismo resultado. Agregar ahora "deja en 2", no "suma 2". Es la misma idea de SQS para no duplicar mensajes.
- **El código lleva el estado y se lo muestra al modelo en cada mensaje** (pedido actual y agotados). No depende de que Claude se acuerde.
- **Una regla escrita no basta; el dato debe estar a la vista.** Ni la regla ni la etiqueta "AGOTADO" funcionaron; sacar los agotados a otra lista sí.
- **Lo que casi no cambia (nombre, id) va en las instrucciones; lo que cambia (precio, existencia) se consulta o se arma en cada mensaje.**
- **Un examen con datos encuentra errores que a ojo no se ven:** el cobro doble se veía bien en la plática.

### Problemas y cómo los resolví
- **"No such file or directory"** → la terminal estaba en la carpeta del agente 2. `deactivate`, `cd` a la carpeta del agente 3 y activar su `.venv`.
- **"command not found"** → faltaba escribir `python` antes del nombre del archivo.

### Siguiente
- **Fase 2 en AWS con Terraform:** ADR 001 (DynamoDB y sus llaves), Terraform sin llaves, base de datos y secretos.

---

## Sesión 5: ADR 001 (base de datos) y Terraform sin llaves (Fase 2)
*26 y 27 de octubre de 2026*

### Qué hice
- Escribí el **[ADR 001](docs/adr/001-base-de-datos.md)**: DynamoDB en una sola tabla y el diseño de sus llaves.
- Instalé **AWS CLI** (v2.38) y **Terraform** (v1.17) con Homebrew.
- Activé **IAM Identity Center** (una sola región, us-east-1) y creé un usuario de trabajo, `alejandro`, con **MFA en Duo**.
- Le di el permiso **AdministratorAccess** sobre mi cuenta, con sesiones de **8 horas**.
- Conecté la terminal con `aws configure sso` (perfil `personal`) y probé con `aws sts get-caller-identity`: **mi Mac entra a AWS sin llaves permanentes**.

### Decisiones del ADR 001
| Decisión | Por qué |
|---|---|
| **DynamoDB bajo demanda** | Sin costo fijo, sin servidor, encaja con Lambda |
| **Carpeta por `chat_id`** (no por nombre ni por pedido) | El nombre se repite y cambia; el pedido no existe hasta confirmar |
| **Índice solo de pedidos nuevos** | "¿Qué tengo pendiente?" es abrir una sola carpeta |
| **Libretas de ventas por semana y por mes** | "¿Cuánto llevo?" es una sola lectura; el mes no son 4 semanas exactas |
| **Contador atómico de folios** | Nunca dos pedidos con el mismo folio |
| **Pláticas que se borran solas (TTL 24 h)** | No se acumula basura |

### Qué aprendí
- **La Lambda tiene amnesia:** se prende, contesta y olvida. La base de datos es la nota del cambio de turno.
- **DynamoDB es como la tabla de MACs de un switch:** buscar por llave es instantáneo; recorrer todo (Scan) es lento y caro.
- **SQL vs. DynamoDB:** en SQL guardas y después preguntas lo que quieras (como Excel); en DynamoDB primero decides qué vas a buscar y preparas una "carpeta" para cada búsqueda (como los grupos de la agenda del celular).
- **Los contadores que se suman** (como los de una interfaz) evitan recontar pedidos para los reportes.
- **CloudFormation vs. Terraform:** el primero es solo de AWS (como la herramienta del fabricante); Terraform sirve para varias nubes (como Ansible) y te enseña con `plan` qué va a hacer antes de hacerlo.
- **Llaves temporales:** en lugar de una llave permanente en la Mac, el navegador le da a la terminal una llave que caduca sola. Así entran las empresas.
- **La cuenta principal de una organización** es como la red de administración: en una empresa no corre aplicaciones, para limitar el daño si algo falla.

### Problemas y cómo los resolví
- **AWS proponía por defecto una instancia "Multi-Region"** con llave de cifrado propia (KMS) que cobra cada mes → elegí **Single-Region**.
- **La contraseña del usuario nuevo apareció completa en una captura** y Chrome la iba a guardar en mi cuenta del trabajo → la descarté, elegí otra y la guardé en mi llavero personal.
- **"aws configure" pide llaves permanentes** → no lo usé; usé `aws configure sso`.
- **El CLI ofreció conectar AWS a asistentes de IA** → dije que no por ahora (tendrían permisos de administrador).

### Siguiente
- Primer archivo de **Terraform**: crear la tabla de DynamoDB del ADR 001 y ver el primer `terraform plan`.
- Revisar en Identity Center → Settings que no quedó la llave KMS multirregión.

---

## Sesión 6: Primera infraestructura con Terraform (Fase 2)
*28 de octubre de 2026*

### Qué hice
- Creé la carpeta `infra/` con 5 archivos de Terraform: `versions.tf`, `providers.tf`, `variables.tf`, `dynamodb.tf` y `outputs.tf`.
- Corrí `terraform init` (descarga el "traductor" de AWS), `terraform plan` (vista previa) y `terraform apply` (crear).
- Creé la tabla **`pedidos-don-chuy`** tal como dice el ADR 001: PK/SK de texto, bajo demanda, índice GSI1 de pedidos nuevos, TTL en `expira`, respaldo continuo (PITR) y 3 etiquetas del proyecto.
- Revisé en la consola que todo coincidiera con el ADR.
- El archivo candado `.terraform.lock.hcl` ahora sí se sube a GitHub; el `terraform.tfstate` y la carpeta `.terraform` no.

### Resultados
| Paso | Resultado |
|---|---|
| `terraform plan` (primera vez) | ⚠️ 1 to add, con un Warning: `hash_key` obsoleto en el índice |
| `terraform plan` (corregido) | ✅ 1 to add, sin warnings |
| `terraform apply` | ✅ Tabla creada en 30 segundos |
| Revisión en la consola | ✅ Todo coincide con el ADR 001 |

### Qué aprendí
- **Terraform lee todos los `.tf` de la carpeta donde estás**, por eso importa el `cd infra`.
- **`init`** prepara las herramientas; **`plan`** compara lo que quiero (los archivos) contra lo que existe (AWS y el state) y muestra la diferencia; **`apply`** la ejecuta. Es como `show | compare` y `commit` en un Juniper.
- **Símbolos del plan:** `+` crear, `~` cambiar, `-` borrar (este hay que leerlo con lupa).
- **`(known after apply)`:** datos que AWS inventa al crear, como el ARN.
- **El state es la libreta de Terraform:** anota lo que creó. No se sube a GitHub porque puede tener datos sensibles.
- **Warm throughput (12,000 / 4,000)** es capacidad precalentada que AWS da por defecto; no cobra si no la cambio.
- **Infraestructura como código:** si borro la tabla, `terraform apply` la vuelve a crear idéntica.
- **Experimento:** cambié el nombre en `variables.tf` y el plan dijo `forces replacement` y `1 to destroy`: AWS no permite renombrar una tabla, así que Terraform la borraría y crearía otra vacía. **Siempre leer el plan antes del `yes`**; en producción, `deletion_protection_enabled = true`. Regresé el nombre y el plan dijo `No changes`.

### Problemas y cómo los resolví
- **Warning "hash_key is deprecated"** en el índice → el traductor de AWS 6.x pide escribir las llaves del índice con bloques `key_schema`. Cambié solo ese bloque; el diseño no cambió.

### Siguiente
- Guardar el token de Telegram como secreto cifrado en AWS (la llave de Claude ya no hace falta: en AWS se usa Bedrock con el rol de la Lambda).
- ADR 002: fila SQS FIFO + DLQ.

---

## Sesión 7: Secreto de Telegram, ADR 002 y filas SQS (Fase 2)
*3 y 4 de noviembre de 2026*

### Qué hice
- **Secreto:** `infra/secretos.tf` crea un parámetro cifrado (SecureString) en **Parameter Store**: `/agente-pedidos/telegram/bot-token`.
  - Terraform lo crea con un valor de relleno y `ignore_changes`; el token real lo pegué a mano en la consola.
  - Comprobé sin mostrar el token: versión 2, 46 caracteres e **IGUALES** al `.env`.
  - La llave de Claude ya no hace falta: en AWS se usa Bedrock con el rol de la Lambda.
- **[ADR 002](docs/adr/002-fila-sqs.md):** fila SQS FIFO + DLQ entre la Lambda de recepción y la del agente, con su PDF.
- **Filas:** `infra/sqs.tf` crea la fila principal `agente-pedidos-mensajes.fifo` y la DLQ `agente-pedidos-mensajes-dlq.fifo`.

### Decisiones del ADR 002
| Decisión | Por qué |
|---|---|
| **Fila SQS FIFO** (no directo, no Lambda que se llama a sí misma, no fila estándar) | Orden por cliente y sin duplicados |
| **Grupo = `chat_id`** | Cada cliente en su propia fila; clientes distintos en paralelo |
| **Anti-duplicados = `update_id` de Telegram** | Si Telegram reintenta, se procesa una sola vez (ventana de 5 min) |
| **Marca "ya procesado" en DynamoDB** | Protección después de los 5 minutos (idempotencia) |
| **DLQ después de 3 intentos** | Lo que falla se aparta sin trabar a los demás |
| **Invisibilidad de 6 minutos** | 6 veces el tiempo máximo de la Lambda (60 s), como recomienda AWS |

### Resultados
| Paso | Resultado |
|---|---|
| Parámetro del token (`terraform apply`) | ✅ 1 added |
| Token pegado y comprobado | ✅ Versión 2, 46 caracteres, IGUALES |
| Filas SQS (`terraform apply`) | ✅ 2 added (primero la DLQ, después la principal) |

### Qué aprendí
- **Un secreto es como la llave de la casa:** da acceso o poder. La dirección (número de cuenta, nombre de la tabla) no es secreta; la llave (token, contraseñas, llaves de acceso) sí.
- **Parameter Store estándar es gratis**; Secrets Manager cobra por secreto y se justifica con rotación automática.
- **El valor de un secreto no va en el código ni en el state:** Terraform crea el cajón, yo pongo el valor.
- **Lo que funcionó en el Investigador aquí no sirve:** ahí cada tema era independiente; aquí la plática tiene orden.
- **FIFO = la fila de la tortillería:** primero en llegar, primero en ser atendido.
- **Invisibilidad = el número de turno:** mientras atienden un mensaje nadie más lo toma; si el agente falla, a los 6 minutos reaparece.
- **Dependencias en Terraform:** la fila principal necesita la dirección (ARN) de la DLQ, así que Terraform creó primero la DLQ sin que yo le dijera el orden.
- **`true` / `false`** en código es "sí / no", como `no shutdown` / `shutdown`.

### Repaso de código (fragmentos)
| Fragmento | Resultado | Lo que me faltaba |
|---|---|---|
| `dynamodb.tf` (Sesión 6) | 2.5 de 5 | PK/SK (carpeta y hoja), apodo interno vs. nombre real, protección contra borrado |
| `sqs.tf` | 2.5 de 5 | Qué es `true`, invisibilidad (es al revés), el ARN es la dirección, no donde se guarda |

### Problemas y cómo los resolví
- **"No valid credential sources found" en Terraform** → la llave temporal de 8 horas caducó (así debe ser). `aws sso login --profile personal` y listo.

### Siguiente
- Las dos Lambdas: adaptar el código del empleado para guardar la plática, el carrito y los pedidos en DynamoDB, y usar Claude por Bedrock.

---

## Sesión 8: El agente funciona 100% en AWS (Fase 2)
*4 de noviembre de 2026*

### Qué hice
- **El empleado se mudó a una Lambda** (`lambdas/agente/app.py`): mismo `empleado.py`, pero la plática y el carrito se leen y guardan en **DynamoDB**, los pedidos usan **folio atómico + transacción**, cada mensaje se marca como "ya procesado" y Claude se usa por **Bedrock** (sin llave de Anthropic). Sin librerías externas.
- **Prueba local** (`lambdas/agente/probar_local.py`): el mismo código desde mi Mac contra la tabla real y Claude real; Telegram simulado.
- **Lambda del agente con Terraform** (`infra/lambda_agente.tf`): el paquete .zip, el rol con 5 permisos mínimos, logs de 14 días, la Lambda (arm64, 60 s) y su conexión con la fila (1 mensaje por vuelta, máximo 5 a la vez).
- **La puerta de entrada** (`infra/lambda_recepcion.tf` y `lambdas/recepcion/app.py`): API Gateway (`POST /telegram`, freno de 10 por segundo), una **clave secreta del webhook** generada por Terraform y una Lambda de recepción que solo revisa la clave y mete el mensaje a la fila.
- **Registré el webhook en Telegram** tomando el token y la clave directo de AWS (nunca aparecieron en pantalla).
- **Le escribí al bot desde mi celular** y el pedido **DC-0004** se guardó, atendido 100% desde AWS.

### Resultados
| Prueba | Resultado |
|---|---|
| Prueba local, intento 1 | ❌ "total" es palabra reservada de DynamoDB |
| Prueba local, intento 2 | ❌ Datos "traducidos" dos veces (MAP) |
| Prueba local, intento 3 | ✅ DC-0003 guardado y DUPLICADO_IGNORADO |
| Mensaje falso a la fila (modo prueba) | ✅ La Lambda en AWS contestó y escribió su TRAZA |
| Tocar la puerta sin clave | ✅ `{"ok": false}` y CLAVE_INCORRECTA en el log |
| Registrar el webhook | ✅ "Webhook was set" |
| Pedido real desde mi celular | ✅ DC-0004, $48, **la GUARDIA lo salvó** |

### Números reales
| Dato | Valor |
|---|---|
| Costo de un pedido completo (6 mensajes) | ~3 centavos de dólar |
| Recepción → "ok" a Telegram | 9 a 250 ms |
| Respuesta del agente | 1.5 a 4 segundos |
| Memoria usada | 100 de 256 MB (agente), 94 de 128 MB (recepción) |

### Qué aprendí
- **La guardia sí importa en producción:** Claude dijo "confirmado" sin guardar; la guardia se lo regresó y el pedido se guardó. Para el cliente fue invisible.
- **La transacción "todo o nada" funciona:** dos intentos fallaron y no quedó ni un pedido a medias.
- **Huecos en los folios son normales:** el contador suma antes de la transacción; si ésta falla, se salta un número. Lo importante es que nunca se repita.
- **La marca "ya procesado" va al final:** así un mensaje que falla nunca se da por atendido.
- **Palabras reservadas:** DynamoDB no acepta ciertos nombres sueltos (como `total`); se usan alias (`#total`).
- **Arranque en frío:** la primera vez la Lambda tarda ~0.5 s más en "despertar"; AWS también cobra ese arranque.
- **Probar en capas:** primero en local, luego con un mensaje falso a la fila, luego la puerta sin clave y al final desde el celular. Cada capa aísla un problema.
- **Con el webhook, `empleado.py` ya no funciona en la Mac:** Telegram deja de usar el buzón (polling) y toca el timbre en AWS.

### Repaso de código
| Fragmento | Resultado | Lo que me faltaba |
|---|---|---|
| `lambdas/recepcion/app.py` | 3.5 de 6 | Códigos HTTP (200 = recibido, 401 = no autorizado); con una foto se contesta 200 para que Telegram no la reintente; el anti-duplicados tira el repetido, no lo actualiza. ✅ Pregunta de entrevista: sin la clave, cualquiera mete mensajes falsos (defensa en capas) |

### Para la Fase 3
- Aceptó "Calle bellavista #2" sin colonia: la validación de dirección debe ser más estricta.
- Dio el precio por kilo sin consultar la herramienta (lo calculó bien, pero la regla dice consultar).

### Siguiente
- ADR 003: avisarle a Don Chuy cuando entra un pedido y que pueda consultar sus pedidos nuevos y sus ventas.
- Examen de conversaciones corriendo en AWS, revisión de costos, diagrama y README.

## Sesión 9: Don Chuy se entera de cada pedido (Fase 2)
*5 de noviembre de 2026*

### Qué hice
- **ADR 003** (`docs/adr/003-aviso-al-dueno.md`): cómo se entera Don Chuy de los pedidos. Comparé 4 opciones (directo desde el agente, EventBridge, DynamoDB Streams, correo/SMS) y elegí **DynamoDB Streams + una Lambda avisadora**. Las consultas del dueño van con **comandos fijos, sin IA**.
- **El "papel carbón" de la tabla** (`infra/dynamodb.tf`): encendí el Stream. Fue un cambio en sitio (`~`), sin reemplazar la tabla ni tocar los datos.
- **La avisadora** (`infra/lambda_avisador.tf` y `lambdas/avisador/app.py`): un **filtro** hace que solo despierte cuando se **crea** un pedido. Pone una palomita de "avisado" (para no avisar dos veces) y le manda el pedido a Don Chuy. Si falla 3 veces, deja nota en una **fila de avisos fallidos**.
- **El `chat_id` del dueño** quedó en Parameter Store. Lo saqué del pedido DC-0004 con un comando, sin escribirlo a mano.
- **Diagnóstico del "me trabé"**: la traza ahora guarda **por qué terminó Claude** cada vuelta (`paradas`), y si Claude escribe mal una herramienta tiene **un reintento** antes de contestar al cliente.
- **Comandos de Don Chuy** (`lambdas/agente/dueno.py`): `/pendientes`, `/ventas` y `/entregado_DC0005`. El agente los atiende **antes** de llamar a Claude, solo si vienen del `chat_id` del dueño. Permiso nuevo: consultar **solo el índice** de pendientes.

### Resultados
| Prueba | Resultado |
|---|---|
| `terraform apply` del Stream y la avisadora | ✅ 7 creados, 1 cambiado (la tabla, en sitio), 0 destruidos |
| Pedido real DC-0005 desde mi celular | ✅ Confirmación al cliente y **aviso a Don Chuy en el mismo minuto** |
| Logs de la avisadora | ✅ `AVISO_ENVIADO` en 1.25 s |
| Primer mensaje del pedido | ⚠️ "Perdón, me trabé tantito": Claude terminó sin texto ni herramienta |
| `/pendientes` | ✅ 3 pedidos, del más viejo al más nuevo |
| `/ventas` | ✅ $178 en 3 pedidos ($90 + $48 + $40: **cuadra exacto**) |
| `/entregado_DC0003` (un toque) | ✅ Marcado y fuera de la lista |

### Números reales
| Dato | Valor |
|---|---|
| Pedido completo (8 mensajes) | ~US$0.039 (unos 70 centavos de peso) |
| Mensaje con herramientas vs. pura plática | ~US$0.010 vs. ~US$0.003 |
| Avisadora | 1.25 s (incluye 0.56 s de arranque en frío), 98 de 128 MB |
| Leer el Stream desde Lambda | Sin costo; los registros filtrados no despiertan la Lambda |

### Qué aprendí
- **DynamoDB Streams = puerto espejo (SPAN):** cada cambio guardado se copia a una salida aparte; quien escucha ahí no toca el tráfico principal.
- **El problema de la doble escritura:** si el agente guarda el pedido y *luego* publica un aviso (EventBridge), puede salir bien lo primero y fallar lo segundo. Con el Stream, el aviso nace del pedido ya guardado.
- **"Al menos una vez":** el Stream puede entregar la misma copia dos veces; por eso la **palomita condicional** ("solo si no tiene palomita").
- **Un bot es como un firewall stateful:** no puede iniciar la conversación; Don Chuy le escribe una vez (paso de instalación) y desde ahí el bot le puede avisar.
- **Sin IA para el dinero:** los comandos leen la libreta tal cual; contestan en milisegundos y no gastan en Bedrock.
- **Telegram solo vuelve "tocable" un comando sin espacios ni guiones:** por eso `/entregado_DC0005` y no `/entregado DC-0005`.
- **Observabilidad:** la traza decía *que* falló, pero no *por qué* (un ping sin código de error). Ahora guarda el motivo de cada vuelta.
- **Defensa en capas para el aviso:** si se perdiera, el pedido sigue en `/pendientes`. "El aviso es la campanita; la lista es la libreta."

### Repaso de código
| Fragmento | Resultado | Lo que me faltaba |
|---|---|---|
| `lambdas/agente/dueno.py` (`/entregado`) | 0.75 de 4 | `next(...)` = hojear la lista y quedarse con el primero que cumple (o "nada"); `/pendientes` solo pregunta por la carpeta `ESTADO#nuevo` del índice (como una VLAN: cambias el puerto de VLAN y deja de verse ahí); la condición evita marcarlo dos veces y que se reescriba la hora de entrega. ✅ Entrevista: el código lee los números exactos de DynamoDB (faltó decir: el dinero debe ser exacto, y así es más barato y rápido) |

### Para la Fase 3
- **La GUARDIA volvió a actuar** al confirmar DC-0005: hay que reforzar la instrucción de usar `confirmar_pedido` antes de decir "confirmado".
- **Vigilar las `paradas`** en la traza para confirmar si el "me trabé" fue una herramienta mal escrita (`malformed_tool_use`).

### Siguiente
- Alarmas: aviso si algo cae en la DLQ de mensajes o en la fila de avisos fallidos.
- Examen de conversaciones en AWS y revisión de costos.
- Diagrama, README y cierre de la Fase 2.

## Sesión 10: Alarmas, examen en AWS y cierre de la Fase 2
*9 de noviembre de 2026*

### Qué hice
- **Alarmas** (`infra/alarmas.tf`): una alarma de CloudWatch por cada fila de fallas (la DLQ de mensajes y la de avisos fallidos). Si llega 1 mensaje, **SNS** me manda un correo, y otro cuando vuelve a la normalidad. Usé `for_each`: una receta, dos alarmas.
- **Mi correo fuera de GitHub:** va en `terraform.tfvars`, que Git ignora.
- **Probé las alarmas de punta a punta:** metí un mensaje falso a la fila de avisos fallidos → correo ALARM → vacié la fila → correo OK.
- **Modo prueba aislado** en el agente: con `"prueba": true` (solo invocando la Lambda directo) el pedido se guarda de verdad, pero con folio `PR-`, en su propia libreta de ventas, fuera de `/pendientes` y sin aviso a Don Chuy.
- **Examen en AWS** (`examen_aws.py`): los 8 casos de la Fase 1 contra la Lambda real, con costo y tiempo de cada caso.
- **Cierre de la Fase 2:** diagrama final (`docs/arquitectura-aws.png`), README nuevo (sin emojis en el título), tabla de ADRs, números reales, cómo desplegarlo y estimado vs. real.

### Resultados
| Prueba | Resultado |
|---|---|
| `terraform apply` de las alarmas | ✅ 4 creados (tema SNS, suscripción, 2 alarmas) |
| Mensaje de prueba a la fila de avisos fallidos | ✅ Correo ALARM en ~6 minutos |
| Vaciar la fila | ✅ Correo OK ~8 minutos después |
| Primer intento del examen | ❌ "Telegram respondió 400": faltaba el `terraform apply` del código nuevo |
| Examen en AWS | ✅ **8/8** en 47 segundos |

### Números reales
| Dato | Valor |
|---|---|
| Examen completo (22 mensajes) | US$0.0965 |
| Pedido confirmado (3–4 mensajes) | ~US$0.02 |
| Respuesta promedio | 1.9 s por mensaje |
| Guardia, reintento o "me trabé" en el examen | 0 |
| Recursos creados con Terraform | 31 |
| Fase 2: sesiones estimadas vs. reales | 7.5 vs. 6 |

### Qué aprendí
- **Alarma = SNMP trap:** CloudWatch vigila la fila y SNS reparte el aviso. Sin alarma, una DLQ es un syslog que nadie lee.
- **Probar la alarma, no solo crearla:** hasta que no llega el correo, no sé si funciona (y el primero cayó en la carpeta equivocada).
- **El correo de alertas debe confirmarse:** sin el clic en "Confirm subscription", SNS no manda nada.
- **Datos personales fuera del código:** `terraform.tfvars` ignorado por Git; aun así, el valor queda en el state.
- **Modo prueba aislado = VLAN de pruebas:** el mismo camino real, pero con sus propios folios y ventas, y sin poder activarse desde Telegram.
- **Aprobar el examen no es todo:** el examen revisa datos; al leer las pláticas vi que el agente responde existencias sin consultar la herramienta, porque la lista ya va en sus instrucciones. Las instrucciones se contradicen.
- **Si el código no cambia en AWS, no cambia nada:** editar el archivo no basta; hay que hacer `terraform apply`.

### Repaso de código
| Fragmento | Resultado | Lo que me faltaba |
|---|---|---|
| `infra/alarmas.tf` (la alarma) | 1.75 de 4 | `for_each` crea **una alarma por cada fila de la lista: 2**; suena cuando, en una ventana de 5 minutos, el máximo de mensajes esperando en la fila llega a 1 o más; `ok_actions` manda el correo de "ya se resolvió" (sin él, no sabría si el problema sigue). ✅ Entrevista: vigilar lo que importa (pedidos que no se procesaron), no cada error; faltó decir que los errores pasajeros ya se reintentan solos y alarmar cada uno sería puro ruido |

### Para la Fase 3
- Decidir: existencias desde la lista de las instrucciones y precio con la herramienta, o quitar la lista y obligar a consultar.
- Dirección más estricta (calle, número y colonia) y reforzar `confirmar_pedido` antes de decir "confirmado".
- Examen de 20–30 conversaciones, incluidas trampas.

### Siguiente
- **Fase 3**: salida estructurada y validación con esquema, reglas más estrictas y examen grande.

## Sesión 11: El agente aprende a no mentir (Fase 3)
*10 al 12 de noviembre de 2026*

### Qué hice
- **Precios solo con herramientas:** quité la contradicción de las instrucciones. La existencia sale de las listas DISPONIBLES y AGOTADOS; el precio, solo de una herramienta. El examen ahora revisa que ningún `$` salga de la memoria de Claude.
- **Dirección con esquema:** `calle`, `numero` y `colonia` por separado (referencias opcional). Si falta algo, el código no guarda y Claude pregunta justo eso. Rechaza "mi casa", "aquí", direcciones sin colonia.
- **Confirmación en 2 pasos** (como `show | compare` y luego `commit`): `preparar_pedido` arma el resumen exacto; `confirmar_pedido` solo funciona en un mensaje posterior y si el pedido no cambió. Es idempotente: preparar el mismo resumen otra vez no reinicia nada.
- **Respuestas sin texto:** la recepción ya no ignora nada; traduce stickers, reacciones, notas de voz y fotos a texto entre corchetes. El código decide que solo 👍 👌 ✅ 🙌 aprueban; un sticker de gatito no.
- **Guardias que obligan (`toolChoice`):** el código revisa cada respuesta antes de que llegue al cliente y, si algo no cuadra, obliga a Claude a usar la herramienta correcta:
  - `GUARDIA_PRECIO`: un precio que ninguna herramienta dio → `buscar_producto`.
  - `GUARDIA_CAMBIO`: dice "quité/agregué" pero el carrito sigue igual → alguna herramienta.
  - `GUARDIA_TOTAL`: un total distinto al real → `ver_pedido`.
  - `GUARDIA_RESUMEN`: un resumen escrito por Claude → `preparar_pedido`.
  - `GUARDIA`: "confirmado", "folio" o "ahí va tu pedido" sin pedido guardado → `confirmar_pedido` o `preparar_pedido`.
- **`RESUMEN_EXACTO`:** si Claude parafrasea el resumen del código, el cliente recibe el original.
- **Telegram manda reacciones:** `allowed_updates` con `message_reaction`.
- **Examen de 8 a 15 casos:** sin colonia, con referencias, aprueba con "sale", con 👍 escrito, con reacción 👍, sticker que no se entiende y nota de voz.
- **Diagrama en Lucid** actualizado con los textos de la Fase 3.

### El camino del examen
| Corrida | Resultado | Qué encontró |
|---|---|---|
| Precios con herramienta | 8/8 | Sin contradicción: −10% de costo y más rápido |
| Esquema de dirección | 9/10 | Confirmó sin que el cliente dijera sí y dijo "$68" en lugar de $84 |
| 2 pasos | 9/10 | El guion del examen no traía el "sí" después del resumen |
| Stickers y reacciones | 14/15 | Un sticker 🐱 llegó antes del resumen |
| Reglas reforzadas | 13/15 | Confirmó con 🐱; escribió su propio resumen |
| Guardias que regañan | 12/15 | Regañar no basta: hacía otra cosa |
| `toolChoice` | 13/15 | "Quitadas las papas" sin quitarlas; "ahí va tu pedido" sin guardar |
| Guardias de cambio y total | 14/15 | Ciclo de volver a preparar |
| Preparar idempotente | 14/15 | "Un garrafón": preguntaba cuántos |
| "Un" = 1 | 14/15 | "Confirmado" escondido junto a una pregunta |
| Solo afirmaciones | **15/15** | — |
| Resumen exacto | **15/15** | `RESUMEN_EXACTO` actuó 6 veces |

### Prueba real desde mi celular
| Prueba | Resultado |
|---|---|
| 👍 escrito al resumen | ✅ DC-0006 confirmado y aviso a Don Chuy |
| Reacción ❤️ al resumen | ✅ No confirmó; volvió a preguntar |
| Reacción 👍 al resumen | ✅ DC-0007 confirmado |
| Dirección en inglés y en formato de formulario | ✅ La acomodó por partes |

### Números reales
| Dato | Valor |
|---|---|
| Examen final | 15/15 · US$0.29 por 42 mensajes · 2.7 s por mensaje |
| Pedido confirmado | ~US$0.03 |
| Guardias en el examen final | GUARDIA 5 · RESUMEN_EXACTO 6 · GUARDIA_RESUMEN 3 · SIN_TEXTO 2 |

### Qué aprendí
- **Claude narra acciones que no ejecuta.** No inventa datos: inventa que *ya hizo algo* ("quitadas las papas", "ahí va tu pedido"). La defensa es que el código compare lo que dice contra lo que de verdad pasó (carrito, total, pedido guardado).
- **Regañar no basta; hay que obligar.** Un aviso del sistema deja que Claude decida qué hacer; `toolChoice` lo obliga a usar la herramienta correcta. Como pasar de un syslog a un EEM applet.
- **Lo importante lo vigila el código; lo ambiguo, también.** "Sale" lo interpreta Claude; un sticker lo decide el código.
- **La idempotencia aparece en todos lados:** "agregar deja en N" (Fase 1) y "preparar el mismo resumen no reinicia" (Fase 3) son la misma lección.
- **Un mismo caso a veces pasa y a veces no.** Un 15/15 no prueba mucho: hay que correr varias veces y medir el porcentaje.
- **Las reacciones no se ven como burbuja en el chat.** Los "dos mensajes seguidos" eran la respuesta a una reacción; los logs lo aclararon (la recepción registra el `tipo`).
- **Eliminar una contradicción en las instrucciones bajó el costo 10%.** Instrucciones claras = menos vueltas.

### Repaso de código
| Fragmento | Resultado | Lo que me faltaba |
|---|---|---|
| `lambdas/agente/app.py` (aprobación sin texto y confirmar) | Pendiente | |

### Para el examen grande
- Bajar las correcciones: Claude anuncia "confirmado" antes de usar la herramienta (5 de 42 mensajes).
- Casos nuevos: cliente grosero, pide datos de otro cliente, intenta engañar al agente, pide más de lo que hay, cambia el pedido después del resumen.
- Correr cada caso 3 veces y reportar el porcentaje.

### Siguiente
- Examen grande (25–30 casos × 3 corridas).
- Cierre: PNG del diagrama de Lucid, README final de la Fase 3, estimado vs. real y costo en Billing.
- ADR 004 a futuro: botones y recordatorios ("¿te lo mando?"), incluido WhatsApp.
