// Prueba opcional en Chrome real con micrófono simulado (silencio).
// Requiere un servidor de prueba vacío en VOXBOARD_TEST_URL.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const origin = new URL(process.env.VOXBOARD_TEST_URL || 'http://127.0.0.1:5051').origin;

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'voxboard-chrome-'));
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', 'about:blank',
  ], { windowsHide: true });
  let socket;
  try {
    const endpoint = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Chrome no inició en 15 segundos')), 15000);
      let output = '';
      chrome.stderr.on('data', data => {
        output += data;
        const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (match) { clearTimeout(timer); resolve(match[1]); }
      });
      chrome.on('error', error => { clearTimeout(timer); reject(error); });
      chrome.on('exit', code => { clearTimeout(timer); reject(new Error(`Chrome terminó: ${code}. ${output.slice(-1000)}`)); });
    });
    socket = new WebSocket(endpoint);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    let sequence = 0;
    const pending = new Map();
    const errors = [];
    socket.onmessage = ({ data }) => {
      const message = JSON.parse(data);
      if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails);
      if (message.id) {
        const callbacks = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) callbacks.reject(new Error(JSON.stringify(message.error)));
        else callbacks.resolve(message.result);
      }
    };
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params, sessionId }));
    });
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Runtime.enable', {}, sessionId);
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }, sessionId);
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      return result.result.value;
    };
    const waitFor = async (expression, milliseconds = 15000) => {
      const deadline = Date.now() + milliseconds;
      while (Date.now() < deadline) {
        if (await evaluate(expression)) return;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      throw new Error(`Espera agotada: ${await evaluate('document.body.innerText')}; errores: ${JSON.stringify(errors)}`);
    };
    const navigate = async pathname => {
      await send('Page.navigate', { url: origin + pathname }, sessionId);
      await waitFor(`location.pathname === ${JSON.stringify(pathname.split('?')[0])} && document.readyState === 'complete'`);
    };
    await send('Page.navigate', { url: origin + '/' }, sessionId);
    await waitFor("document.getElementById('username') && document.readyState === 'complete'");
    await evaluate("document.getElementById('username').value = 'docente_prueba'; document.getElementById('password').value = 'ClavePrueba2026'; if(document.getElementById('password-confirmation')) document.getElementById('password-confirmation').value = 'ClavePrueba2026'; document.getElementById('username').form.requestSubmit()");
    await waitFor("location.pathname === '/' && document.getElementById('course-menu')");
    console.log('Cuenta docente de prueba creada; acceso al curso autenticado.');
    await send('Page.navigate', { url: origin + '/mi-curso/registro?fecha=2026-11-16' }, sessionId);
    await waitFor("location.pathname === '/sesiones/1' && document.getElementById('grade-1')");
    await evaluate("document.querySelector('input[name=status_1][value=presente]').checked = true; document.querySelector('input[name=status_2][value=ausente]').checked = true; document.querySelector('input[name=status_1]').form.requestSubmit()");
    await waitFor("document.querySelector('.success')?.textContent.includes('Asistencia guardada')");
    await evaluate("[70, 0, 100, 50].forEach((value,i) => document.getElementById('grade-' + (i+1)).value = value); document.getElementById('grade-1').form.requestSubmit()");
    await waitFor("document.querySelector('.success')?.textContent.includes('Calificaciones guardadas')");
    await navigate('/sesiones/1');
    assert.equal(await evaluate("document.getElementById('grade-2').value"), '0');
    assert.equal(await evaluate("document.querySelector('input[name=status_1][value=presente]').checked"), true);
    console.log('Sesión creada desde el curso; asistencia y notas (incluido cero) guardadas y recuperadas.');
    await navigate('/sesiones/1/pizarra');
    await waitFor("document.getElementById('record-start') && !document.getElementById('record-start').disabled");
    await evaluate("document.getElementById('record-start').click()");
    await waitFor("!document.getElementById('record-stop').disabled");
    assert.match(await evaluate("document.getElementById('voice-status').textContent"), /Grabando/);
    await new Promise(resolve => setTimeout(resolve, 1200));
    await evaluate("document.getElementById('record-stop').click()");
    await waitFor("!document.getElementById('record-start').disabled");
    const message = await evaluate("document.getElementById('voice-status').textContent");
    assert.match(message, /No se reconoció texto|Transcripción completada/);
    assert.equal(await evaluate("document.getElementById('avatar-state').textContent"), 'En espera');
    const transcript = await evaluate("document.getElementById('voice-text').textContent");
    for (const [phrase, id] of [
      ['¡MOSTRAR, SISTÉMA SOLAR!', 'sistema-solar'],
      ['mostrar ciclo del agua', 'ciclo-del-agua'],
      ['mostrar partes de una planta', 'partes-de-una-planta'],
      ['mostrar estados de la materia', 'estados-de-la-materia'],
      ['mostrar cadena alimentaria', 'cadena-alimentaria'],
    ]) {
      assert.equal(await evaluate(`window.VoxBoard.executeCommand(${JSON.stringify(phrase)}).recognized`), true);
      assert.equal(await evaluate("document.getElementById('resource-area').dataset.selectedResource"), id);
      assert.equal(await evaluate("document.getElementById('avatar-state').textContent"), 'Recurso mostrado');
    }
    await waitFor("document.getElementById('avatar-state').textContent === 'En espera'");
    assert.equal(await evaluate("window.VoxBoard.executeCommand('hola clase').recognized"), false);
    assert.equal(await evaluate("document.getElementById('resource-area').dataset.selectedResource"), 'cadena-alimentaria');
    await evaluate("document.querySelector('[data-resource-id=\"ciclo-del-agua\"]').click()");
    assert.equal(await evaluate("document.getElementById('resource-area').dataset.selectedResource"), 'ciclo-del-agua');
    assert.equal(await evaluate("document.getElementById('voice-text').textContent"), transcript);
    await evaluate("document.getElementById('voice-mode').value = 'dictation'; window.VoxVoiceHooks.onStart(); window.VoxVoiceHooks.onText('mostrar cadena alimentaria')");
    await evaluate('window.VoxVoiceHooks.onFinish()');
    assert.equal(await evaluate("document.getElementById('resource-area').dataset.selectedResource"), 'ciclo-del-agua');
    assert.equal(await evaluate("document.getElementById('session-summary').value"), 'mostrar cadena alimentaria');
    await evaluate("window.VoxVoiceHooks.onStart(); window.VoxVoiceHooks.onText('Las plantas necesitan agua.')");
    await evaluate('window.VoxVoiceHooks.onFinish()');
    await evaluate("document.getElementById('session-summary').value += '\\nResumen editado: las raíces absorben agua, el tallo sostiene la planta y las hojas captan la luz del Sol.'; document.getElementById('save-summary').click()");
    await waitFor("document.getElementById('summary-status').textContent === 'Resumen guardado.'");
    await navigate('/sesiones/1/pizarra');
    await waitFor("document.getElementById('session-summary')?.value.includes('Las plantas necesitan agua.')");
    assert.match(await evaluate("document.getElementById('session-summary').value"), /Resumen editado/);
    await navigate('/sesiones/1');
    await waitFor("document.getElementById('school-preview') && !document.getElementById('record-start').disabled");
    await evaluate("window.VoxVoiceHooks.onText('registrar nota ochenta y cinco al estudiante uno')");
    assert.match(await evaluate("document.getElementById('preview-description').textContent"), /Ana García.*85/);
    await evaluate("document.getElementById('cancel-command').click()");
    assert.equal(await evaluate("document.getElementById('grade-1').value"), '70');
    await evaluate("window.VoxVoiceHooks.onText('registrar nota 85 al estudiante 1')");
    await evaluate("document.getElementById('confirm-command').click()");
    await waitFor("document.getElementById('grade-1').value === '85'");
    await evaluate("window.VoxVoiceHooks.onText('marcar ausente al estudiante uno')");
    await evaluate("document.getElementById('confirm-command').click()");
    await waitFor("document.querySelector('input[name=\"status_1\"][value=\"ausente\"]').checked");
    await navigate('/sesiones/1');
    await waitFor("document.getElementById('grade-1')?.value === '85'");
    assert.equal(await evaluate("document.querySelector('input[name=\"status_1\"][value=\"ausente\"]').checked"), true);
    console.log('Grabador real con audio sintético; comandos simulados, dictado editable, cancelar y confirmar: correctos.');

    if (process.env.VOXBOARD_FULL_TEST === '1') {
      await navigate('/sesiones/1/trivia');
      await evaluate("document.querySelector('button[value=generate]').click()");
      await waitFor("document.querySelector('.success')?.textContent.includes('Borrador generado') || document.querySelector('[role=alert]')", 150000);
      assert.equal(await evaluate("document.querySelector('[role=alert]')?.textContent || ''"), '');
      assert.equal(await evaluate("document.querySelectorAll('.trivia-question').length"), 5);
      await evaluate("document.getElementById('q0').value = 'Pregunta revisada: ¿qué absorben las raíces?'; document.getElementById('q0_A').value='Agua del suelo'; document.getElementById('q0_B').value='Plástico'; document.getElementById('q0_C').value='Metal'; document.getElementById('correct0').value='A'; document.querySelector('button[value=save]').click()");
      await waitFor("document.querySelector('.success')?.textContent.includes('Trivia guardada')");
      await navigate('/sesiones/1/trivia/proyectar');
      assert.equal(await evaluate("document.querySelectorAll('.projected-question').length"), 5);
      assert.match(await evaluate('document.body.textContent'), /Pregunta revisada/);
      assert.equal(await evaluate("document.querySelectorAll('input[name^=correct],select[name^=correct],[data-correcta]').length"), 0);
      assert.equal(await evaluate("document.documentElement.outerHTML.includes('correcta')"), false);
      console.log('Ollama real: trivia generada, pregunta editada, guardado y proyección sin clave correctos.');

      // Dos sesiones adicionales: empate en tercer puesto y asistencia pendiente.
      await evaluate(`(async () => {
        for (const day of ['2026-11-17','2026-11-18']) {
          await fetch('/sesiones', {method:'POST', body:new URLSearchParams({class_date:day})});
        }
        await fetch('/sesiones/2', {method:'POST', body:new URLSearchParams({form_type:'grades',grade_2:'100'})});
        await fetch('/sesiones/2', {method:'POST', body:new URLSearchParams({status_1:'presente'})});
      })()`);
      await navigate('/cursos/1/comentarios?student_id=1');
      assert.match(await evaluate('document.body.textContent'), /85.00/);
      await evaluate("document.querySelector('button[value=generate]').click()");
      await waitFor("document.querySelector('.success')?.textContent.includes('Borrador generado') || document.querySelector('[role=alert]')", 150000);
      assert.equal(await evaluate("document.querySelector('[role=alert]')?.textContent || ''"), '');
      assert.ok((await evaluate("document.getElementById('comment').value")).length > 20);
      await evaluate("document.getElementById('comment').value += ' Comentario revisado por el docente.'; document.querySelector('button[value=save]').click()");
      await waitFor("document.querySelector('.success')?.textContent.includes('Comentario guardado')");
      await navigate('/cursos/1/comentarios?student_id=1');
      assert.match(await evaluate("document.getElementById('comment').value"), /Comentario revisado por el docente/);
      console.log('Ollama real: comentario de boletín generado, editado, guardado y recuperado.');

      await navigate('/cursos/1/rendimiento');
      const tables = await evaluate("Array.from(document.querySelectorAll('table')).map(table => Array.from(table.tBodies[0].rows).map(row => Array.from(row.cells).map(cell => cell.textContent.trim())))");
      assert.deepEqual(tables[0].find(row => row[0] === 'Ana García').slice(1), ['85.00', '1', '1', '1', '50.00 %']);
      assert.deepEqual(tables[0].find(row => row[0] === 'Mateo López').slice(1), ['50.00', '2', '0', '1', '0.00 %']);
      assert.deepEqual(tables[1].map(row => [row[0],row[1],row[2]]), [['1','Sofía Mamani','100.00'],['2','Ana García','85.00'],['3','Mateo López','50.00'],['3','Lucas Pérez','50.00']]);
      const csv = await evaluate("fetch('/cursos/1/rendimiento.csv').then(async response => ({disposition:response.headers.get('Content-Disposition'), data:Array.from(new Uint8Array(await response.arrayBuffer()))}))");
      assert.match(csv.disposition, /attachment/);
      assert.deepEqual(csv.data.slice(0,3), [239,187,191]);
      const records = Buffer.from(csv.data).toString('utf8').replace(/^\uFEFF/, '').trimEnd().split('\r\n');
      assert.equal(records.shift(), 'sep=;'); records.shift();
      assert.equal(records.length, 5);
      records.forEach((record,i) => assert.deepEqual(record.split(';'), tables[0][i].map((cell,j) => j === 0 ? cell : cell === 'Sin registros' ? '' : cell.replace(' %','').replace('.',','))));
      console.log('Indicadores, empate en tercer puesto y CSV coinciden con los datos de prueba y la pantalla.');

      // Simular servicio apagado sin detener el Ollama del usuario: puerto local cerrado.
      await evaluate("fetch('/__test__/ollama/unavailable', {method:'POST'})");
      await navigate('/sesiones/1/trivia');
      await evaluate("document.getElementById('q0').value = 'Edición pendiente de trivia'; document.querySelector('button[value=generate]').click()");
      await waitFor("document.querySelector('[role=alert]')?.textContent.includes('No se pudo conectar')");
      assert.equal(await evaluate("document.getElementById('q0').value"), 'Edición pendiente de trivia');
      await navigate('/sesiones/1/trivia');
      assert.match(await evaluate("document.getElementById('q0').value"), /Pregunta revisada/);
      await navigate('/cursos/1/comentarios?student_id=1');
      await evaluate("document.getElementById('comment').value = 'Edición pendiente del comentario'; document.querySelector('button[value=generate]').click()");
      await waitFor("document.querySelector('[role=alert]')?.textContent.includes('No se pudo conectar')");
      assert.equal(await evaluate("document.getElementById('comment').value"), 'Edición pendiente del comentario');
      await navigate('/cursos/1/comentarios?student_id=1');
      assert.match(await evaluate("document.getElementById('comment').value"), /Comentario revisado por el docente/);
      console.log('Conexión real a puerto cerrado: errores claros y borradores/ediciones conservados en ambos generadores.');
    }
    await navigate('/');
    await evaluate("document.querySelector('.account-menu form, .chalk-logout').requestSubmit()");
    await waitFor("location.pathname === '/iniciar-sesion' && document.getElementById('username')");
    await evaluate("document.getElementById('username').value = 'docente_prueba'; document.getElementById('password').value = 'incorrecta'; document.getElementById('username').form.requestSubmit()");
    await waitFor("document.querySelector('[role=alert]')?.textContent.includes('incorrectos')");
    await evaluate("document.getElementById('password').value = 'ClavePrueba2026'; document.getElementById('username').form.requestSubmit()");
    await waitFor("location.pathname === '/' && document.getElementById('course-menu')");
    console.log('Cerrar sesión, rechazo de clave incorrecta y nuevo inicio de sesión: correctos.');
    assert.equal(errors.length, 0, JSON.stringify(errors));
    console.log('Chrome real: scripts cargados, clic inicia micrófono, captura WAV y transcripción local correctos.');
    console.log(message);
    console.log('Cinco comandos, normalización, avatar, retorno a espera y botones: correctos.');
    console.log('Dictado persistente, vista previa, cancelar y confirmar notas/asistencia: correctos.');
    await send('Browser.close');
  } finally {
    socket?.close();
    chrome.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
