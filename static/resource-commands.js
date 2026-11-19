(() => {
  const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
  function match(text, resources) {
    const command = normalize(text);
    return resources.find(([id, title]) => command === `mostrar ${normalize(title)}`)?.[0] || null;
  }
  window.VoxResourceCommands = Object.freeze({ normalize, match });
})();
