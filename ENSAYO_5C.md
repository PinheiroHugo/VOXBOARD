# Ensayo completo de VOXBOARD · 16 de noviembre de 2026

## Aislamiento

Se usó una base SQLite temporal con el curso y cinco estudiantes ficticios.
No se agregaron sesiones de demostración a la base de trabajo. El SHA-256 de
`instance/voxboard.sqlite3` fue idéntico antes y después del recorrido. También
se verificaron integridad, claves foráneas y ausencia de duplicados de asistencia
y calificaciones en la base de ensayo.

## Resultados

| Prueba | Resultado y tipo de prueba |
| --- | --- |
| Curso, sesión, asistencia y notas | Chrome real: creación de sesión desde el curso, guardado por formularios y persistencia al recargar, incluida una nota 0. |
| Grabación | Chrome real con dispositivo de micrófono **simulado**: captura, conversión WAV y envío a Flask. Vosk y modelo español **reales** procesaron el audio sintético sin voz y mostraron el aviso correspondiente. |
| Comandos escolares | Transcripciones **simuladas**, enviadas al mismo manejador de la grabación. Cancelar conservó la nota 70; confirmar la cambió a 85. Confirmación de ausencia, recarga y unicidad verificadas. |
| Pizarra | Cinco comandos simulados, normalización, botones, texto conservado, sugerencia de comando inválido y estados del avatar verificados en Chrome. |
| Resumen | Dictado simulado, edición manual, guardado y recuperación al recargar. Las frases en modo Dictado no ejecutaron comandos. |
| Trivia | Ollama local **real**: cinco preguntas validadas; edición de una pregunta, opciones y clave; guardado y proyección sin campos ni atributos con respuestas correctas. |
| Boletín | Ollama local **real**: generación, edición docente, guardado y recuperación al recargar. |
| Rendimiento | Comparación con datos ficticios conocidos: Ana 85.00 y 50.00 % de asistencia, Mateo 50.00 y 0.00 %, Sofía primer puesto y empate de Mateo y Lucas en el tercero. |
| CSV | Descarga HTTP, BOM, separador indicado, cinco filas y comparación de cada celda con la tabla de pantalla. |
| Excel | Pruebas automatizadas del `.xlsx`: nombres Unicode, anchos, tipos numéricos, formatos, ceros y celdas vacías. No se abrió Excel de escritorio. |
| Ollama no disponible | Al inicio del ensayo Ollama estaba apagado: apareció el error claro. Después se inició para las generaciones reales. Se repitió el fallo apuntando la aplicación temporal a un puerto local cerrado: trivia y comentario conservaron tanto sus versiones guardadas como las ediciones enviadas. |
| Otros errores | Pruebas unitarias con tiempo de espera y JSON inválido simulados; preservación del borrador verificada. |

## Correcciones

- El cliente compartido de Ollama ahora cierra las respuestas HTTP de error;
  la suite detectaba recursos abiertos al simular un error 404. Se añadió una
  comprobación de regresión.
- El ensayo de navegador usa la dirección configurada en todas las navegaciones,
  permite esperar la generación local y comprueba formularios, indicadores,
  descargas y errores, además de los flujos de voz.
- Se incorporó un ejecutor que crea y elimina su propia base de prueba y comprueba
  que la base existente no haya cambiado.

## Repetición

Con Ollama abierto y `qwen2.5:3b` descargado, desde PowerShell en el proyecto:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/board_selection.test.cjs tests/board_commands.test.cjs tests/audio_wav.test.cjs tests/phase3c.test.cjs
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe tests/run_phase5c.py
```

El último comando necesita Chrome instalado en su ubicación habitual de Windows;
lo ejecuta sin ventana, con micrófono simulado y servidor temporal en un puerto
libre. Las generaciones sí usan Ollama real y el modelo configurable del proyecto.
Los endpoints auxiliares que simulan el servicio apagado existen únicamente en
ese servidor temporal, nunca en la aplicación habitual.

## Comprobaciones manuales pendientes

1. Abrir la aplicación desde `http://127.0.0.1:5000` en Chrome o Edge y permitir el
   micrófono físico. Decir un comando de recurso, dictar una frase y probar un
   comando escolar; confirmar y cancelar un cambio.
2. Comprobar la precisión de Vosk con la voz, acento y ruido reales del aula.
3. Revisar que preguntas, opciones y respuesta correcta se justifiquen con el
   resumen, y que el comentario no añada inferencias: la validación estructural
   automática no sustituye la revisión docente del contenido generado.
4. Proyectar la trivia y verificar legibilidad desde el aula y ausencia de la
   clave en la pantalla destinada a estudiantes.
5. Abrir un CSV y el `.xlsx` en el Excel de este equipo y comprobar tildes, columnas,
   porcentajes y tamaños. El `.xlsx` conserva los anchos de columna.
