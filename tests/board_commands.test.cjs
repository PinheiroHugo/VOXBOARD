const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function board() {
  const names = [
    ['sistema-solar', 'Sistema solar'], ['ciclo-del-agua', 'Ciclo del agua'],
    ['partes-de-una-planta', 'Partes de una planta'],
    ['estados-de-la-materia', 'Estados de la materia'], ['cadena-alimentaria', 'Cadena alimentaria'],
  ];
  const buttons = names.map(([id, title]) => ({
    dataset: { resourceId: id, title, image: `/static/resources/${id}.svg` },
    attributes: {}, handlers: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(event, callback) { this.handlers[event] = callback; },
  }));
  const elements = Object.fromEntries(['resource-title', 'resource-image', 'resource-area', 'board-avatar', 'avatar-state', 'command-feedback']
    .map(id => [id, { dataset: {} }]));
  const timers = new Map();
  let nextTimer = 0;
  const context = {
    window: {},
    document: { querySelectorAll: () => buttons, getElementById: id => elements[id] },
    setTimeout: callback => { timers.set(++nextTimer, callback); return nextTimer; },
    clearTimeout: id => timers.delete(id),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/resource-commands.js'), 'utf8'), context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/board.js'), 'utf8'), context);
  return { context, buttons, elements, timers };
}

test('los cinco comandos toleran mayúsculas, tildes, puntuación y espacios', () => {
  const { context, buttons, elements, timers } = board();
  assert.equal(elements['avatar-state'].textContent, 'En espera');
  const originalSelect = context.window.selectResource;
  const selected = [];
  context.window.selectResource = id => { selected.push(id); return originalSelect(id); };
  for (const button of buttons) {
    for (const phrase of [`mostrar ${button.dataset.title}`, `¡MOSTRAR, ${button.dataset.title.toUpperCase()}!`,
      `  móstrár   ${button.dataset.title}...  `]) {
      const result = context.window.VoxBoard.executeCommand(phrase);
      assert.equal(result.recognized, true);
      assert.equal(elements['command-feedback'].textContent, result.message);
      assert.equal(elements['command-feedback'].hidden, false);
      assert.equal(selected.at(-1), button.dataset.resourceId);
      assert.equal(elements['resource-title'].textContent, button.dataset.title);
      assert.equal(elements['resource-image'].src, button.dataset.image);
      assert.equal(elements['board-avatar'].dataset.state, 'shown');
      assert.equal(elements['avatar-state'].textContent, 'Recurso mostrado');
      assert.equal(timers.size, 1);
    }
  }
  [...timers.values()][0]();
  assert.equal(elements['avatar-state'].textContent, 'En espera');
});

test('frases no válidas conservan el recurso; los botones siguen usando selectResource', () => {
  const { context, buttons, elements } = board();
  buttons[3].handlers.click();
  const original = elements['resource-area'].dataset.selectedResource;
  for (const phrase of ['', 'hola clase', 'mostrar', 'mostrar dinosaurios', 'no mostrar sistema solar',
    'mostrar ciclo del agua y sistema solar', 'mostrar ciclo del agua por favor']) {
    const result = context.window.VoxBoard.executeCommand(phrase);
    assert.equal(result.recognized, false);
    assert.match(result.message, /mostrar ciclo del agua/);
    assert.equal(elements['command-feedback'].textContent, result.message);
    assert.equal(elements['command-feedback'].hidden, false);
    assert.equal(elements['command-feedback'].dataset.result, 'unknown');
    assert.equal(elements['resource-area'].dataset.selectedResource, original);
    assert.equal(elements['avatar-state'].textContent, 'En espera');
  }
  const select = context.window.selectResource;
  let buttonCalls = 0;
  context.window.selectResource = id => { buttonCalls++; return select(id); };
  buttons.forEach(button => {
    button.handlers.click();
    assert.equal(elements['resource-area'].dataset.selectedResource, button.dataset.resourceId);
  });
  assert.equal(buttonCalls, 5);
  // Cambiar el avatar o pulsar botones no borra el resultado del comando.
  context.window.VoxBoard.setAvatarState('idle');
  assert.match(elements['command-feedback'].textContent, /Comando no reconocido/);
});

test('una nueva grabación cancela el temporizador de confirmación anterior', () => {
  const { context, elements, timers } = board();
  context.window.VoxBoard.executeCommand('mostrar sistema solar');
  assert.equal(timers.size, 1);
  context.window.VoxBoard.setAvatarState('listening');
  assert.equal(timers.size, 0);
  assert.equal(elements['avatar-state'].textContent, 'Escuchando');
  context.window.VoxBoard.setAvatarState('idle');
  assert.equal(elements['avatar-state'].textContent, 'En espera');
});
