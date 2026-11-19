"use strict";

(() => {
  const buttons = Array.from(document.querySelectorAll("[data-resource-id]"));
  const resources = new Map(buttons.map(button => [button.dataset.resourceId, button]));
  const title = document.getElementById("resource-title");
  const illustration = document.getElementById("resource-image");
  const area = document.getElementById("resource-area");
  const avatar = document.getElementById("board-avatar");
  const avatarLabel = document.getElementById("avatar-state");
  const commandFeedback = document.getElementById("command-feedback");
  let confirmationTimer;
  const avatarLabels = { idle: 'En espera', listening: 'Escuchando', shown: 'Recurso mostrado' };

  function setAvatarState(state) {
    clearTimeout(confirmationTimer);
    if (avatar) avatar.dataset.state = state;
    if (avatarLabel) avatarLabel.textContent = avatarLabels[state];
    if (state === 'shown') {
      confirmationTimer = setTimeout(() => setAvatarState('idle'), 2500);
    }
  }

  const commandResources = buttons.map(button => [button.dataset.resourceId, button.dataset.title]);

  // API reutilizable: selectResource("ciclo-del-agua").
  // Devuelve false si el identificador no existe, sin cambiar el recurso actual.
  window.selectResource = function selectResource(resourceId) {
    const resource = resources.get(resourceId);
    if (!resource) return false;
    title.textContent = resource.dataset.title;
    illustration.src = resource.dataset.image;
    illustration.alt = `Ilustración de ${resource.dataset.title}`;
    area.dataset.selectedResource = resourceId;
    buttons.forEach(button => {
      button.setAttribute("aria-pressed", String(button === resource));
    });
    return true;
  };

  function executeCommand(transcript) {
    const resourceId = window.VoxResourceCommands.match(transcript, commandResources);
    let result;
    if (resourceId && window.selectResource(resourceId)) {
      setAvatarState('shown');
      result = { recognized: true, message: `Recurso mostrado: ${resources.get(resourceId).dataset.title}.` };
    } else {
      setAvatarState('idle');
      result = { recognized: false, message: 'Comando no reconocido. Probá decir «mostrar ciclo del agua».' };
    }
    // El resultado tiene su propio espacio: los avisos de micrófono y la
    // comprobación inicial del servidor no pueden ocultar la sugerencia.
    if (commandFeedback) {
      commandFeedback.textContent = result.message;
      commandFeedback.dataset.result = result.recognized ? 'shown' : 'unknown';
      commandFeedback.hidden = false;
    }
    return result;
  }

  window.VoxBoard = Object.freeze({ executeCommand, setAvatarState });
  setAvatarState('idle');

  buttons.forEach(button => {
    button.addEventListener("click", () => window.selectResource(button.dataset.resourceId));
  });
  if (buttons.length) window.selectResource(area.dataset.initialResource || buttons[0].dataset.resourceId);
  if (area.dataset.voxMessage && commandFeedback) {
    commandFeedback.textContent = area.dataset.voxMessage;
    commandFeedback.hidden = false;
    setAvatarState('shown');
  }
})();
