const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(reduced = false) {
  const timers = new Map(), documentEvents = {}, windowEvents = {}, styles = {};
  let id = 0;
  const media = { matches: reduced, addEventListener(name, fn) { this[name] = fn; }, removeEventListener(name) { delete this[name]; } };
  const document = { hidden: false,
    addEventListener: (name, fn) => { documentEvents[name] = fn; },
    removeEventListener: name => delete documentEvents[name] };
  const window = { matchMedia: () => media,
    addEventListener: (name, fn) => { windowEvents[name] = fn; },
    removeEventListener: name => delete windowEvents[name] };
  const character = { dataset: {}, style: { setProperty: (key, value) => { styles[key] = value; } } };
  let seed = 37;
  const math = Object.create(Math);
  math.random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/vox-motion.js'), 'utf8'), {
    window, document, Math: math,
    setTimeout: (fn, delay) => { timers.set(++id, { fn, delay }); return id; },
    clearTimeout: key => timers.delete(key),
  });
  const motion = window.VoxMotion.create(character);
  function tick() {
    const [key, timer] = timers.entries().next().value;
    timers.delete(key); timer.fn(); return timer.delay;
  }
  return { motion, character, timers, tick, styles, document, documentEvents, windowEvents, media };
}

test('gestos variados con pausas, saludo de dos o tres oscilaciones y regreso completo al reposo', () => {
  const { motion, character, tick, styles } = setup();
  const gestures = new Set(), pauses = new Set();
  let waves = 0;
  for (let i = 0; i < 32; i++) {
    assert.equal(character.dataset.gesture, 'still');
    const pause = tick();
    assert.ok(pause >= 900 && pause <= 2300);
    pauses.add(pause);
    gestures.add(character.dataset.gesture);
    if (character.dataset.gesture === 'wave') {
      waves++;
      assert.ok([2, 3].includes(styles['--vox-wave-count']));
    }
    tick();
    assert.equal(character.dataset.gesture, 'still');
  }
  for (const gesture of ['blink','look-left','look-right','tilt','brow','smile','surprise','wave']) assert.ok(gestures.has(gesture), gesture);
  assert.ok(waves >= 4);
  assert.ok(pauses.size > 20);
  motion.destroy();
});

test('escuchar interrumpe el saludo; confirmación y duda sobreviven al fin de grabación y vuelven a reposo', () => {
  const { motion, character, timers, tick } = setup();
  character.dataset.gesture = 'wave';
  motion.setState('preparing');
  assert.equal(character.dataset.gesture, 'still');
  assert.equal(timers.size, 0);
  motion.setState('listening');
  assert.equal(timers.size, 0);
  motion.setState('processing');
  for (const state of ['recognized','uncertain']) {
    motion.setState(state); motion.finish();
    assert.equal(character.dataset.state, state);
    assert.equal(timers.size, 1);
    tick();
    assert.equal(character.dataset.state, 'idle');
    assert.equal(character.dataset.gesture, 'still');
  }
  motion.destroy();
});

test('movimiento reducido y pestaña oculta detienen los gestos sin afectar el estado de escucha', () => {
  const reduced = setup(true);
  assert.equal(reduced.timers.size, 0);
  reduced.motion.setState('recognized'); reduced.tick();
  assert.equal(reduced.character.dataset.state, 'idle');
  assert.equal(reduced.timers.size, 0);
  reduced.motion.destroy();
  const normal = setup();
  normal.document.hidden = true; normal.documentEvents.visibilitychange();
  assert.equal(normal.timers.size, 0);
  normal.motion.setState('listening');
  normal.document.hidden = false; normal.documentEvents.visibilitychange();
  assert.equal(normal.character.dataset.state, 'listening');
  assert.equal(normal.timers.size, 0);
  normal.motion.setState('idle');
  assert.equal(normal.timers.size, 1);
  normal.motion.destroy();
  assert.equal(normal.timers.size, 0);
  assert.equal(Object.keys(normal.documentEvents).length, 0);
});

test('volver desde la pizarra o cambiar movimiento reducido no deja una expresión bloqueada', () => {
  const { motion, character, windowEvents, media, timers } = setup();
  motion.setState('recognized');
  windowEvents.pagehide();
  assert.equal(timers.size, 0);
  windowEvents.pageshow();
  assert.equal(character.dataset.state, 'idle');
  assert.equal(timers.size, 1);
  motion.setState('uncertain');
  media.matches = true; media.change();
  assert.equal(character.dataset.state, 'idle');
  assert.equal(timers.size, 0);
  motion.destroy();
});
