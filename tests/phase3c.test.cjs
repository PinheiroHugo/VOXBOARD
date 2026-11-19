const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element(value = '') {
  return { value, textContent: '', dataset: {}, hidden: true, disabled: false, handlers: {},
    addEventListener(name, callback) { this.handlers[name] = callback; } };
}
function load(file, context) {
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static', file), 'utf8'), context);
}

test('Dictado añade y guarda texto; no ejecuta comandos, y conserva las ediciones', async () => {
  const elements = Object.fromEntries(['voice-mode', 'session-summary', 'summary-status', 'save-summary'].map(id => [id, element()]));
  elements['voice-mode'].value = 'dictation';
  elements['session-summary'].value = 'Resumen anterior.';
  elements['session-summary'].dataset.saveUrl = '/resumen';
  const saves = [];
  let commands = 0;
  const context = {
    window: { addEventListener() {}, VoxBoard: { executeCommand: () => { commands++; return { message: 'Mostrado' }; } } },
    document: { getElementById: id => elements[id] }, setTimeout, clearTimeout, AbortSignal,
    fetch: async (url, options) => { saves.push(JSON.parse(options.body).summary); return { ok: true, json: async () => ({}) }; },
  };
  load('dictation.js', context);
  const hooks = context.window.VoxVoiceHooks;
  hooks.onStart();
  assert.equal(elements['voice-mode'].disabled, true);
  await hooks.onText('mostrar ciclo del agua');
  hooks.onFinish();
  assert.equal(commands, 0);
  assert.equal(saves.at(-1), 'Resumen anterior.\nmostrar ciclo del agua');
  elements['session-summary'].value = 'Edición del docente';
  hooks.onStart(); await hooks.onText('Las plantas necesitan luz.'); hooks.onFinish();
  assert.equal(saves.at(-1), 'Edición del docente\nLas plantas necesitan luz.');
  const length = saves.length;
  hooks.onStart(); await hooks.onText(''); hooks.onFinish();
  assert.equal(saves.length, length);
  elements['voice-mode'].value = 'commands';
  hooks.onStart(); await hooks.onText('mostrar sistema solar'); hooks.onFinish();
  assert.equal(commands, 1);
  assert.equal(saves.length, length);
});

test('la vista previa no guarda, Cancelar descarta el comando y Confirmar envía solo el token', async () => {
  const ids = ['school-preview', 'preview-description', 'school-command-status', 'confirm-command', 'cancel-command', 'record-start', 'grade-1'];
  const elements = Object.fromEntries(ids.map(id => [id, element()]));
  elements['grade-1'].value = '70';
  const panel = { dataset: { previewUrl: '/preview', confirmUrl: '/confirm' } };
  const writes = [];
  const context = {
    window: {}, document: { querySelector: () => panel, getElementById: id => elements[id] }, AbortSignal,
    fetch: async (url, options) => {
      const body = JSON.parse(options.body);
      if (url === '/preview') return { ok: true, json: async () => ({ token: 'signed-preview', name: 'Ana García', student_id: 1, kind: 'grade', value: 85 }) };
      writes.push(body);
      return { ok: true, json: async () => ({ message: 'Cambio confirmado y guardado.', student_id: 1, kind: 'grade', value: 85 }) };
    },
  };
  load('school-voice.js', context);
  const hooks = context.window.VoxVoiceHooks;
  await hooks.onText('registrar nota ochenta y cinco al estudiante uno');
  assert.match(elements['preview-description'].textContent, /Ana García.*85/);
  assert.equal(writes.length, 0);
  elements['cancel-command'].handlers.click();
  assert.equal(elements['school-preview'].hidden, true);
  await elements['confirm-command'].handlers.click();
  assert.equal(writes.length, 0);
  assert.equal(elements['grade-1'].value, '70');
  await hooks.onText('registrar nota 85 al estudiante 1');
  await elements['confirm-command'].handlers.click();
  assert.equal(writes.length, 1);
  assert.equal(writes[0].token, 'signed-preview');
  assert.equal(elements['grade-1'].value, 85);
  assert.equal(elements['school-preview'].hidden, true);
  await hooks.onText('registrar nota 85 al estudiante 1');
  hooks.onStart();
  await elements['confirm-command'].handlers.click();
  assert.equal(writes.length, 1);
});
