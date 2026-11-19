/* Coreografía visual local: no accede al micrófono ni ejecuta comandos. */
(() => {
  'use strict';
  function create(character) {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let timer, bag = [], previous = '', gestures = 0;
    let nextWave = 3 + Math.floor(Math.random() * 3);
    let suspended = document.hidden, destroyed = false;
    const random = (min, max) => min + Math.random() * (max - min);
    const durations = { blink: 230, 'look-left': 700, 'look-right': 700, tilt: 850, brow: 650, smile: 800, surprise: 700 };

    function clear() {
      clearTimeout(timer);
      character.dataset.gesture = 'still';
    }
    function schedule() {
      if (destroyed || suspended || reduced.matches || character.dataset.state !== 'idle') return;
      timer = setTimeout(perform, random(900, 2300));
    }
    function nextGesture() {
      if (!bag.length) {
        bag = Object.keys(durations);
        for (let i = bag.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [bag[i], bag[j]] = [bag[j], bag[i]];
        }
        if (bag[bag.length - 1] === previous) bag.reverse();
      }
      previous = bag.pop();
      return previous;
    }
    function perform() {
      if (destroyed || suspended || reduced.matches || character.dataset.state !== 'idle') return;
      let gesture = nextGesture();
      let duration = durations[gesture];
      if (++gestures >= nextWave) {
        gestures = 0;
        nextWave = 3 + Math.floor(Math.random() * 3);
        const count = 2 + Math.floor(Math.random() * 2);
        character.style.setProperty('--vox-wave-count', count);
        gesture = 'wave';
        duration = 1200 + count * 340;
        character.style.setProperty('--vox-wave-duration', `${duration}ms`);
      }
      character.style.setProperty('--vox-gesture-duration', `${duration}ms`);
      character.dataset.gesture = gesture;
      timer = setTimeout(() => {
        character.dataset.gesture = 'still';
        schedule();
      }, duration);
    }
    function setState(state) {
      clear();
      character.dataset.state = state;
      if (state === 'idle') schedule();
      if (state === 'recognized' || state === 'uncertain') {
        timer = setTimeout(() => setState('idle'), reduced.matches ? 1400 : 2200);
      }
    }
    function visibility() {
      suspended = document.hidden;
      clear();
      if (!suspended) {
        if (['recognized', 'uncertain'].includes(character.dataset.state)) setState('idle');
        else schedule();
      }
    }
    function preference() {
      clear();
      if (['recognized', 'uncertain'].includes(character.dataset.state)) setState('idle');
      else schedule();
    }
    function hide() { suspended = true; clear(); }
    function show() {
      suspended = document.hidden;
      clear();
      if (['recognized', 'uncertain'].includes(character.dataset.state)) setState('idle');
      else schedule();
    }
    document.addEventListener('visibilitychange', visibility);
    reduced.addEventListener('change', preference);
    window.addEventListener('pagehide', hide);
    window.addEventListener('pageshow', show);
    setState('idle');
    return {
      setState,
      finish() {
        if (!['recognized', 'uncertain'].includes(character.dataset.state)) setState('idle');
      },
      destroy() {
        destroyed = true; clear();
        document.removeEventListener('visibilitychange', visibility);
        reduced.removeEventListener('change', preference);
        window.removeEventListener('pagehide', hide);
        window.removeEventListener('pageshow', show);
      },
    };
  }
  window.VoxMotion = Object.freeze({ create });
})();
