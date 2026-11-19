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
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${process.env.VOXBOARD_FAKE_AUDIO}`, 'about:blank',
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
    const navigate = async (pathname, expected = pathname.split('?')[0]) => {
      await send('Page.navigate', { url: origin + pathname }, sessionId);
      await waitFor(`location.pathname === ${JSON.stringify(expected)} && document.readyState === 'complete'`);
    };

    await send('Page.enable',{},sessionId);
    await send('Page.addScriptToEvaluateOnNewDocument',{source:`if(navigator.mediaDevices){const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);window.__streams=[];navigator.mediaDevices.getUserMedia=async(...args)=>{const stream=await original(...args);window.__streams.push(stream);return stream}}`},sessionId);
    await send('Page.navigate',{url:origin+'/'},sessionId);
    await waitFor("document.getElementById('username')");

    await evaluate("document.getElementById('username').value='voz_directa';document.getElementById('password').value='ClaveDirecta2026';document.getElementById('password-confirmation').value='ClaveDirecta2026';document.getElementById('username').form.requestSubmit()");
    await waitFor("location.pathname==='/' && document.getElementById('record-start') && !document.getElementById('record-start').disabled");
    const installTranscripts = async () => evaluate(`(()=>{window.__uploads=0;const original=window.fetch;window.fetch=async(input,options)=>{
      const response=await original(input,options);
      if(String(input).includes('/api/voz/transcribir')){window.__uploads++;if(!response.ok)throw new Error('Fallo Vosk real');return new Response(JSON.stringify({text:window.__nextText}),{headers:{'Content-Type':'application/json'}})}
      return response;
    }})()`);
    await installTranscripts();
    assert.equal(await evaluate('window.__streams.length'),0);
    assert.equal(await evaluate("document.querySelector('.home-vox-zone').dataset.activeCourse"),'');
    const speak=async text=>{
      const previous=await evaluate('window.__uploads');
      await evaluate(`window.__nextText=${JSON.stringify(text)};document.getElementById('record-start').click()`);
      await waitFor("document.getElementById('vox-character').dataset.state==='listening'");
      await waitFor(`window.__uploads===${previous+1} && !document.getElementById('record-start').disabled`,20000);
      assert.equal(await evaluate('window.__streams.every(s=>s.getTracks().every(t=>t.readyState===\'ended\'))'),true);
      await new Promise(resolve=>setTimeout(resolve,200));
      assert.equal(await evaluate('window.__uploads'),previous+1);
    };
    await speak('mostrar ciclo del agua');
    assert.equal(await evaluate("document.getElementById('vox-resource-dialog').open"),true);
    assert.equal(await evaluate("document.getElementById('vox-resource-title').textContent"),'Ciclo del agua');
    assert.equal(await evaluate("document.getElementById('vox-school-fields').hidden"),true);
    assert.equal(await evaluate('location.pathname'),'/');
    await evaluate("document.getElementById('vox-close-resource').click()");
    assert.equal(await evaluate("document.getElementById('vox-resource-dialog').open"),false);
    await speak('mostrar sistema solar');
    assert.equal(await evaluate("document.getElementById('vox-resource-title').textContent"),'Sistema solar');
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27},sessionId);
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27},sessionId);
    await waitFor("!document.getElementById('vox-resource-dialog').open");
    await speak('hola clase');
    assert.match(await evaluate("document.getElementById('voice-status').textContent"),/No reconoc/);
    await waitFor("document.getElementById('vox-character').dataset.state==='idle'");
    await speak('registrar nota 85 al estudiante uno');
    assert.equal(await evaluate("document.getElementById('vox-school-fields').hidden"),false);
    assert.equal(await evaluate("document.getElementById('vox-course-field').hidden"),false);
    await navigate('/gestion/configurar');
    await evaluate("document.getElementById('school-year').value='2026';document.getElementById('course-name').value='Curso anual 2026';document.getElementById('teacher-name').value='Docente de prueba';document.getElementById('new-students').value=['Ana;García','Mateo;López'].join(String.fromCharCode(10));document.getElementById('course-name').form.requestSubmit()");
    await waitFor("location.pathname==='/cursos/1' && document.getElementById('estudiantes')");
    await navigate('/');
    await waitFor("!document.getElementById('record-start').disabled");
    await installTranscripts();
    await evaluate("document.getElementById('vox-date').value='2026-11-18'");
    await speak('registrar nota 85 al estudiante uno');
    await waitFor("!document.getElementById('vox-school-preview').hidden");
    assert.equal(await evaluate("document.getElementById('vox-school-fields').hidden"),true);
    assert.match(await evaluate("document.getElementById('vox-preview-description').textContent"),/85/);
    await evaluate("document.getElementById('vox-cancel-confirmation').click()");
    assert.equal(await evaluate("document.getElementById('vox-school-preview').hidden"),true);
    let counts=await evaluate("fetch('/__test__/counts').then(r=>r.json())");
    assert.equal(counts.grades,0);assert.equal(counts.class_sessions,0);
    await speak('marcar presente al estudiante uno');
    await evaluate("document.getElementById('vox-date').value='2026-11-17';document.getElementById('vox-date').dispatchEvent(new Event('change'))");
    await waitFor("document.getElementById('vox-preview-description').textContent.includes('2026-11-17') && !document.getElementById('vox-school-preview').hidden");
    await evaluate("document.getElementById('vox-confirm-command').click()");
    await waitFor("document.getElementById('voice-status').textContent.includes('guardado para 2026-11-17')");
    await evaluate("document.getElementById('vox-date').value='2026-11-18'");
    await speak('marcar ausente al estudiante uno');
    await evaluate("document.getElementById('vox-confirm-command').click()");
    await waitFor("document.getElementById('voice-status').textContent.includes('guardado para 2026-11-18')");
    await speak('marcar presente al estudiante uno');
    await evaluate("document.getElementById('vox-confirm-command').click()");
    await waitFor("document.getElementById('voice-status').textContent.includes('guardado para 2026-11-18')");
    counts=await evaluate("fetch('/__test__/counts').then(r=>r.json())");
    assert.equal(counts.attendance,2);assert.equal(counts.class_sessions,2);
    await speak('registrar nota 85 al estudiante uno');
    await evaluate("document.getElementById('vox-confirm-command').click()");
    await waitFor("document.getElementById('voice-status').textContent.includes('guardado para 2026-11-18')");
    // Cancelar una captura no manda audio ni procesa otro comando.
    const previous=await evaluate('window.__uploads');
    await evaluate("document.getElementById('record-start').click()");
    await waitFor("document.getElementById('vox-character').dataset.state==='listening'");
    await evaluate("document.getElementById('record-cancel').click()");
    await waitFor("!document.getElementById('record-start').disabled");
    assert.equal(await evaluate('window.__uploads'),previous);
    assert.equal(await evaluate('window.__streams.every(s=>s.getTracks().every(t=>t.readyState===\'ended\'))'),true);
    await navigate('/mi-curso', '/cursos/1');
    await waitFor("location.pathname==='/cursos/1'");
    await navigate('/gestion/configurar');
    await evaluate("document.getElementById('school-year').value='2027';document.getElementById('course-name').value='Curso anual 2027';document.getElementById('teacher-name').value='Docente de prueba';document.getElementById('new-students').value='Sofía;Mamani';document.getElementById('course-name').form.requestSubmit()");
    await waitFor("location.pathname==='/cursos/2' && document.getElementById('estudiantes')");
    await navigate('/mi-curso', '/cursos/2');await waitFor("location.pathname==='/cursos/2'");
    await navigate('/gestiones');
    assert.match(await evaluate('document.body.textContent'),/2026/);
    assert.match(await evaluate('document.body.textContent'),/2027/);
    await navigate('/sesiones/2');
    assert.equal(await evaluate("document.getElementById('grade-1').value"),'85');
    assert.equal(await evaluate("document.querySelector('.record-editor').disabled"),true);
    assert.equal(errors.length,0,JSON.stringify(errors));
    console.log('Chrome: recurso sin curso, pausa automatica, nota cancelada, dos fechas y correccion de asistencia, curso anual directo y nueva gestion con historial conservado.');
    console.log('Audio sintetico para detectar actividad; Vosk real procesa el audio; texto reconocido sustituido por frases de prueba.');
    await send('Browser.close');
  }finally{socket?.close();chrome.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
