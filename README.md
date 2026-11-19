# VOXBOARD

Aplicación web para docentes de primaria, desarrollada con **Python, Flask, Jinja y SQLite**. Combina gestión académica, una pizarra de recursos educativos, reconocimiento de voz con Vosk y generación de contenidos con Ollama en el equipo servidor.

Este repositorio contiene el **software principal**, independiente del sitio informativo VOXBOARD-WEB.

## Funciones disponibles

- Una cuenta docente local, con inicio/cierre de sesión y protección CSRF.
- Curso anual activo, configuración de estudiantes e historial de gestiones anteriores.
- Asistencia por fecha y notas enteras de 0 a 100, con corrección y persistencia.
- Avatar Vox animado; comandos con cierre automático por pausa y confirmación antes de guardar registros.
- Cinco recursos SVG locales: Sistema solar, Ciclo del agua, Partes de una planta, Estados de la materia y Cadena alimentaria.
- Recursos flotantes desde Vox, incluso sin curso configurado; cierre con X o Escape.
- Dictado y edición del resumen, trivias editables con proyección sin clave y comentarios de boletín.
- Indicadores, cuadro de honor con empates e informes CSV/XLSX.
- Ayuda configurable hacia el portal informativo, con aviso temporal si no existe URL.

El trabajo diario **no requiere crear ni elegir sesiones manualmente**: se reutiliza un registro interno por curso y fecha. Algunas pantallas aún dicen «sesión» para referirse a ese contexto. Se conservan los registros históricos.

## Requisitos

- Windows, PowerShell y Python de 64 bits con el lanzador `py` disponible.
- Chrome o Edge actualizado y permiso de micrófono para voz.
- Dependencias de `requirements.txt`:

  | Paquete | Versión |
  | --- | --- |
  | Flask | 3.1.3 |
  | vosk | 0.3.45 |
  | openpyxl | 3.1.5 |
  | waitress | 3.0.2 |

- Modelo español Vosk `vosk-model-small-es-0.42`, descargado por separado.
- Ollama con `qwen2.5:3b`, solo para generar trivias/comentarios.
- Git para clonar; Node con `node --test` para las pruebas JavaScript opcionales.

No se fija una versión menor de Python ni requisitos mínimos medidos de RAM/GPU. Validar compatibilidad de Vosk y rendimiento de Ollama en el equipo destino. La instalación inicial requiere descargar dependencias/modelos; después, las funciones locales no necesitan internet. El acceso remoto y la Ayuda externa sí lo requieren.

## Instalación en Windows

Desde PowerShell:

```powershell
git clone https://github.com/PinheiroHugo/VOXBOARD.git
Set-Location VOXBOARD
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No es necesario activar el entorno ni cambiar la política de ejecución de PowerShell: los comandos usan directamente su intérprete.

### Descargar el modelo Vosk

1. Abrir el [catálogo oficial de modelos](https://alphacephei.com/vosk/models).
2. Descargar el modelo español **vosk-model-small-es-0.42** y descomprimirlo.
3. Colocarlo con esta estructura, sin duplicar una carpeta intermedia:

   ```text
   VOXBOARD/
     models/
       vosk-model-small-es-0.42/
         am/
         conf/
         graph/
         ivector/
         ...
   ```

El modelo y su ZIP no se distribuyen en Git. VOXBOARD no los descarga automáticamente. Si faltan, los formularios y recursos por botones continúan disponibles, pero la voz muestra un error.

### Configurar Ollama

Instalar [Ollama para Windows](https://ollama.com/download/windows) y descargar el modelo:

```powershell
ollama pull qwen2.5:3b
ollama list
```

Abrir Ollama. Si no está ejecutándose como aplicación/servicio, usar `ollama serve` en otra terminal. No iniciar otra instancia si ya ocupa el puerto. Comprobar desde el servidor:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Solo Flask se comunica con Ollama. No instalarlo en cada dispositivo visitante ni exponer su puerto a internet. Si Ollama falla, se conserva el borrador; las funciones académicas, recursos, voz con Vosk e informes siguen disponibles.

## Arranque y datos ficticios

Para comenzar una demostración con **curso y cinco estudiantes ficticios** en una base separada:

```powershell
.\.venv\Scripts\python.exe .\server.py --demo
```

Abrir **http://127.0.0.1:8080**. En el primer uso, crear una cuenta con credenciales propias. **No hay contraseña predeterminada**. La demo se guarda en `instance/demo/voxboard.sqlite3`, conserva los cambios entre reinicios y no duplica la carga inicial.

Para uso habitual, sin insertar estudiantes ficticios:

```powershell
.\.venv\Scripts\python.exe .\server.py
```

Abrir la misma dirección y configurar el curso desde **Mi curso**. Los datos habituales se guardan en `instance/voxboard.sqlite3`, independientes de la demo.

Waitress escucha solo en loopback, con depuración desactivada. Detener con **Ctrl+C**. Para desarrollo local también existe:

```powershell
.\.venv\Scripts\python.exe .\app.py
```

Ese servidor usa `http://127.0.0.1:5000`; no utilizarlo como servidor público.

## Configuración

`.env.example` es una referencia sin secretos. La aplicación **no carga `.env` automáticamente**. Asignar variables en PowerShell antes de arrancar:

```powershell
$env:OLLAMA_MODEL = 'qwen2.5:3b'
$env:OLLAMA_URL = 'http://127.0.0.1:11434'
$env:OLLAMA_TIMEOUT = '120'
.\.venv\Scripts\python.exe .\server.py --demo
```

| Variable de entorno | Predeterminado | Uso |
| --- | --- | --- |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Modelo compartido por trivia y boletín. |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Solo HTTP loopback: localhost, 127.0.0.1 o ::1. |
| `OLLAMA_TIMEOUT` | `120` | Límite en segundos; debe ser numérico. |
| `VOXBOARD_HELP_URL` | `https://voxboard-web.vercel.app/novedades.html` | URL pública HTTP/HTTPS de novedades y recursos de VOXBOARD-WEB. |

**Ayuda** abre directamente [Novedades y recursos](https://voxboard-web.vercel.app/novedades.html) en otra pestaña. Se puede cambiar su destino asignando otra dirección completa a `$env:VOXBOARD_HELP_URL`. Si se configura explícitamente una URL vacía o inválida, muestra «El centro de ayuda estará disponible próximamente».

Para integración/pruebas, `create_app(config)` acepta `DATABASE`, `VOSK_MODEL_PATH` y `SECRET_KEY`; estas claves no se leen automáticamente del entorno. Normalmente la clave se genera aleatoriamente en `.secret_key`, junto a cada base, y se conserva al reiniciar. No publicarla.

## Uso básico

1. Entrar y abrir **Mi curso**. Configurar año, curso y estudiantes con formato `Nombres;Apellidos`, uno por línea. Consultar sus ID.
2. Abrir **Asistencia** o **Calificaciones** y revisar/corregir la fecha antes de guardar. Una nota vacía está pendiente; 0 es un valor válido.
3. Pulsar **Hablar con Vox** y decir «mostrar ciclo del agua». Una pausa de unos 0,9 segundos después de hablar termina la captura. También existe **Terminar de hablar**. El recurso se abre como ventana flotante.
4. Para registrar, decir «marcar presente al estudiante uno» o «registrar nota ochenta y cinco al estudiante uno», reemplazando el número por el ID del estudiante. Revisar nombre, fecha y valor; pulsar **Confirmar** o **Cancelar**. Transcribir no guarda por sí solo.
5. En **Pizarra y resumen**, seleccionar **Dictado**, usar **Grabar frase** y **Detener y transcribir**, editar y guardar el resumen. El fin automático por silencio corresponde al inicio con Vox; esta pizarra usa detención manual.
6. Generar la trivia desde el resumen, revisar y guardar ediciones antes de proyectar. Para boletines, revisar los datos y guardar el comentario editado.
7. Abrir **Seguimiento del curso** para rendimiento/cuadro de honor. Descargar Excel con formatos y anchos o CSV con UTF-8 BOM, separador `;` y coma decimal.
8. Al iniciar otro año, crear una **Nueva gestión**. La anterior queda para consulta; no hay reactivación desde la interfaz.

La voz no es conversación libre. Los recursos se piden con `mostrar` más su título exacto. Los registros usan ID, no nombres. El micrófono se libera al terminar o cancelar; Vox responde visualmente y por texto, sin voz sintetizada.

## Demostración por internet

Crear primero la cuenta privadamente con `--demo` y detener el servidor. Para un túnel HTTPS:

```powershell
.\.venv\Scripts\python.exe .\server.py --demo --tunnel
```

En otra terminal, con cloudflared instalado:

```powershell
cloudflared tunnel --url http://127.0.0.1:8080
```

Abrir la URL HTTPS temporal que imprima cloudflared. El micrófono remoto necesita contexto seguro y permiso del usuario; Vosk y Ollama se ejecutan en el servidor. `--tunnel` exige cuenta previa y activa cookies Secure.

Seguir [la guía de demostración](docs/DEMOSTRACION_INTERNET.md) antes de compartir. Quick Tunnel es temporal, no un despliegue permanente. El software no abre túneles automáticamente.

## Datos y respaldo

Esta versión admite **una sola cuenta docente por base**: no ofrece aislamiento entre varios docentes/instituciones ni recuperación de contraseña desde la interfaz.

SQLite, claves y respaldos están excluidos de Git. No se distribuyen registros reales ni credenciales. Los nombres del curso semilla son ficticios; las claves de `tests/` se usan únicamente en bases temporales, nunca para crear una cuenta de ejecución.

Respaldar demo:

```powershell
.\.venv\Scripts\python.exe .\manage_data.py backup --demo
```

Omitir `--demo` para los datos habituales. Las copias se crean en `backups/` junto a la base. Conservar la clave `.secret_key` por separado de forma privada. Para restaurar, detener servidor/túnel y seguir [el procedimiento de recuperación](docs/DEMOSTRACION_INTERNET.md#7-persistencia-y-recuperación). Se valida la copia y conserva el estado anterior.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.cjs
```

Las suites usan bases temporales y simulaciones de IA/audio, sin cuentas reales ni túnel público. Node no es necesario para ejecutar la aplicación y no hay dependencias npm que instalar.

Ensayo opcional con Chrome, audio sintético y Vosk real:

```powershell
.\.venv\Scripts\python.exe tests/run_home_direct.py
```

Requiere Chrome en la ubicación Windows indicada por el script, Node con WebSocket global, modelo Vosk y una base habitual existente para comparar su hash. Sustituye las transcripciones por frases controladas: no acredita un micrófono físico. `tests/run_phase5c.py` tiene un modo completo con Ollama real; consultar la guía antes de ejecutarlo.

## Estructura

| Ruta | Responsabilidad |
| --- | --- |
| `app.py`, `annual.py`, `auth.py` | Factoría Flask, gestión anual y autenticación. |
| `school_records.py`, `voice.py` | Guardado/parseo escolar y Vosk. |
| `ollama_client.py`, `trivia.py`, `report_comments.py` | IA local, trivias y boletines. |
| `performance.py` | Indicadores, empates y exportaciones. |
| `server.py`, `manage_data.py` | Waitress y respaldo/restauración. |
| `templates/`, `static/` | Pantallas, avatar, captura y recursos visuales. |
| `tests/`, `docs/` | Pruebas y documentación operativa. |
| `instance/`, `models/` | Datos y modelos locales, excluidos de Git. |

## Comprobaciones manuales y límites

- Probar micrófono físico, ruido del aula y fin de frase en el dispositivo destino.
- Verificar calidad/tiempos con Ollama real: estructura válida no demuestra exactitud pedagógica. Revisar siempre los borradores.
- Abrir CSV/XLSX en la versión y configuración regional de Excel utilizada.
- Revisar HTTPS y permisos de micrófono desde otro dispositivo antes de una presentación.
- La tipografía de tiza depende de fuentes instaladas; no hay una fuente propia incluida.
- `ENSAYO_5C.md` conserva evidencia histórica, no certifica cada ejecución futura.

La publicación del código no publica automáticamente la aplicación ni sus datos.
