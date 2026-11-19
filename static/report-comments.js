(() => {
  const form = document.getElementById('comment-form');
  if (!form) return;
  form.addEventListener('submit', event => {
    if (form.dataset.submitting) { event.preventDefault(); return; }
    form.dataset.submitting = 'true';
    if (event.submitter?.value === 'generate') document.getElementById('comment-generation-status').hidden = false;
    form.querySelectorAll('button').forEach(button => button.setAttribute('aria-disabled', 'true'));
  });
})();
