/* Upload progress reports bytes transferred, never analysis progress. */
(() => {
  const form = document.getElementById('inspection-upload');
  if (form) {
    const file = document.getElementById('inspection-file');
    const submit = document.getElementById('upload-submit');
    const error = document.getElementById('upload-error');
    const message = document.getElementById('upload-message');
    const meter = document.getElementById('upload-meter');
    let busy = false;
    const showError = text => { error.textContent = text; error.hidden = false; };
    file.addEventListener('change', () => {
      error.hidden = true;
      // A different selection starts a new request; retries keep the existing key.
      form.elements.request_key.value = Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2, '0')).join('');
      const chosen = file.files[0];
      document.getElementById('file-meta').textContent = chosen ? `${chosen.name} · ${(chosen.size / 1000000).toLocaleString('es', {maximumFractionDigits: 2})} MB` : '';
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (busy) return;
      const chosen = file.files[0];
      if (!chosen) return showError('Selecciona un archivo para continuar.');
      if (!chosen.size) return showError('El archivo está vacío. Selecciona otro.');
      if (chosen.size > Number(form.dataset.maxBytes)) return showError('El archivo supera los 25 MB. Selecciona uno más pequeño.');
      if (!/\.(jpe?g|png|webp|heic|heif|pdf)$/i.test(chosen.name)) return showError('Usa una imagen JPG, PNG, WebP, HEIC o un documento PDF.');
      const data = new FormData(form);
      busy = true; submit.disabled = true; file.disabled = true;
      form.setAttribute('aria-busy', 'true'); error.hidden = true;
      document.getElementById('upload-progress').hidden = false;
      meter.value = 0; message.textContent = 'Subiendo archivo…'; submit.textContent = 'Subiendo…';
      const xhr = new XMLHttpRequest();
      xhr.open('POST', form.action); xhr.setRequestHeader('Accept', 'application/json');
      xhr.responseType = 'json'; xhr.timeout = 180000;
      const recover = text => {
        busy = false; submit.disabled = false; file.disabled = false;
        form.removeAttribute('aria-busy'); submit.textContent = 'Reintentar carga';
        document.getElementById('upload-progress').hidden = true;
        showError(text);
      };
      xhr.upload.addEventListener('progress', event => {
        if (event.lengthComputable) {
          meter.value = Math.round(event.loaded / event.total * 100);
          message.textContent = meter.value === 100 ? 'Carga enviada. Confirmando recepción…' : `Subiendo archivo: ${meter.value}%`;
        } else { meter.removeAttribute('value'); }
      });
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300 && xhr.response?.url) {
          const destination = new URL(xhr.response.url, location.href);
          if (destination.origin === location.origin) { location.assign(destination.href); return; }
        }
        const defaults = {400:'No se pudo aceptar la carga. Recarga la página e inténtalo otra vez.',401:'Tu sesión terminó. Vuelve a iniciar sesión.',413:'El archivo supera el tamaño permitido de 25 MB.',429:'Llegaste al límite de cargas. Espera o contacta al administrador.'};
        recover(xhr.response?.error || defaults[xhr.status] || 'No pudimos confirmar la recepción. Revisa tu sesión y vuelve a intentarlo; no se duplicará una carga ya recibida.');
      });
      xhr.addEventListener('error', () => recover('Se perdió la conexión. Puedes reintentar con el mismo archivo sin duplicar la carga.'));
      xhr.addEventListener('timeout', () => recover('La conexión tardó demasiado. Puedes reintentar con el mismo archivo.'));
      xhr.send(data);
    });
  }
  const pending = document.getElementById('analysis-pending');
  if (pending) {
    const retry = document.getElementById('poll-retry');
    const message = document.getElementById('poll-message');
    let failures = 0;
    async function check() {
      retry.hidden = true;
      try {
        const response = await fetch(pending.dataset.statusUrl, {headers:{Accept:'application/json'}, signal:AbortSignal.timeout(15000)});
        if (!response.ok) throw new Error('status unavailable');
        const data = await response.json();
        if (!data.status) throw new Error('invalid response');
        if (!['queued','running'].includes(data.status)) { location.reload(); return; }
        failures = 0;
        const running = data.status === 'running';
        document.getElementById('job-state').textContent = running ? 'En análisis' : 'En espera';
        document.getElementById('job-state').className = `state-pill state-${data.status}`;
        document.getElementById('pending-title').textContent = running ? 'Estamos revisando tu archivo' : 'Tu archivo está en espera';
        message.textContent = 'No necesitas mantener esta página abierta. El resultado quedará en «Mis análisis».';
        setTimeout(check, 5000);
      } catch (_) {
        failures++;
        message.textContent = 'No pudimos actualizar el estado. Tu archivo sigue registrado; puedes volver a consultarlo más tarde.';
        if (failures < 3) setTimeout(check, 5000); else retry.hidden = false;
      }
    }
    retry.addEventListener('click', () => { failures = 0; check(); });
    setTimeout(check, 3000);
  }
})();
