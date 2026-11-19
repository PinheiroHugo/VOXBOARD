// Verifica el contrato de selección sin instalar dependencias de navegador.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

test('los botones y la API seleccionan cada recurso; un ID desconocido no cambia nada', () => {
  const resourcePath = path.join(__dirname, '..', 'static', 'resources');
  const ids = fs.readdirSync(resourcePath).filter(name => name.endsWith('.svg'))
    .map(name => name.slice(0, -4));
  assert.equal(ids.length, 5);
  const buttons = ids.map(id => ({
    dataset: { resourceId: id, title: `Título ${id}`, image: `/static/resources/${id}.svg` },
    attributes: {},
    handlers: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, handler) { this.handlers[name] = handler; },
  }));
  const elements = {
    'resource-title': {}, 'resource-image': {}, 'resource-area': { dataset: {} },
  };
  const context = {
    window: {},
    setTimeout, clearTimeout,
    document: {
      querySelectorAll: () => buttons,
      getElementById: id => elements[id],
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'resource-commands.js'), 'utf8'), context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'board.js'), 'utf8'), context);
  function verify(button) {
    assert.equal(elements['resource-title'].textContent, button.dataset.title);
    assert.equal(elements['resource-image'].src, button.dataset.image);
    assert.equal(elements['resource-image'].alt, `Ilustración de ${button.dataset.title}`);
    assert.equal(elements['resource-area'].dataset.selectedResource, button.dataset.resourceId);
    assert.equal(button.attributes['aria-pressed'], 'true');
    assert.equal(buttons.filter(item => item.attributes['aria-pressed'] === 'true').length, 1);
  }
  verify(buttons[0]);
  for (const button of buttons) {
    button.handlers.click();
    verify(button);
    assert.equal(context.window.selectResource(button.dataset.resourceId), true);
    verify(button);
  }
  assert.equal(context.window.selectResource('recurso-inexistente'), false);
  verify(buttons.at(-1));
});
