document.getElementById('trivia-form').addEventListener('submit', event => {
  const form = event.currentTarget;
  if (form.dataset.submitting) { event.preventDefault(); return; }
  form.dataset.submitting = 'true';
  if (event.submitter?.value === 'generate') document.getElementById('generation-status').hidden = false;
  // Conservar el botón enviado: deshabilitarlo quitaría action del formulario.
  form.querySelectorAll('button').forEach(button => button.setAttribute('aria-disabled', 'true'));
});
