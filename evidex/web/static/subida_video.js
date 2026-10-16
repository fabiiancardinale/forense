/* Subida de videos por partes (8 MB). Reintenta cada parte hasta 4 veces si se corta la conexión.
   Uso: EvidexVideo.subir(archivo, url, {csrf, campos, alAvanzar}) -> Promise<respuesta JSON> */
(function () {
  const PARTE = 8 * 1024 * 1024;
  function id() {
    const a = new Uint8Array(16); crypto.getRandomValues(a);
    return Array.from(a, b => b.toString(16).padStart(2, "0")).join("");
  }
  async function enviar(url, fd, csrf) {
    let ultimo = "No se pudo subir el video.";
    for (let intento = 0; intento < 4; intento++) {
      try {
        const r = await fetch(url, {method: "POST", body: fd, headers: csrf ? {"X-CSRF-Token": csrf} : {}, credentials: "same-origin"});
        let j = {};
        try { j = await r.json(); } catch (e) { j = {error: r.status === 413 ? "Parte demasiado grande." : "Respuesta inesperada del servidor."}; }
        if (r.ok) return j;
        if (r.status >= 400 && r.status < 500) throw new Error(j.error || ultimo);   // rechazo: no reintentar
        ultimo = j.error || ultimo;
      } catch (e) {
        if (e instanceof Error && e.message && !/fetch|network|Failed/i.test(e.message)) throw e;
        ultimo = "Se cortó la conexión. Reintentando…";
      }
      await new Promise(res => setTimeout(res, 1500 * (intento + 1)));
    }
    throw new Error(ultimo === "Se cortó la conexión. Reintentando…" ? "Sin conexión. Revise su internet e intente de nuevo." : ultimo);
  }
  async function subir(file, url, opts) {
    opts = opts || {};
    const total = Math.max(1, Math.ceil(file.size / PARTE)), uid = id();
    let res = null;
    for (let n = 0; n < total; n++) {
      const fd = new FormData();
      fd.append("id", uid); fd.append("n", n); fd.append("total", total); fd.append("size", file.size); fd.append("name", file.name);
      for (const [k, v] of Object.entries(opts.campos || {})) fd.append(k, v);
      if (opts.csrfCampo) fd.append("csrf_token", opts.csrfCampo);
      fd.append("parte", file.slice(n * PARTE, Math.min(file.size, (n + 1) * PARTE)), file.name);
      res = await enviar(url, fd, opts.csrf);
      if (opts.alAvanzar) opts.alAvanzar(Math.round(100 * (n + 1) / total));
      if (res.done) break;
    }
    return res;
  }
  window.EvidexVideo = {subir, PARTE};

  // botón «Subir video» del caso: <input type=file data-video-url=... data-csrf=...>
  document.querySelectorAll("input[data-video-url]").forEach(inp => inp.addEventListener("change", async () => {
    const box = document.getElementById(inp.dataset.status);
    const show = (t, bad) => { if (box) { box.hidden = false; box.className = "flash " + (bad ? "bad" : "info"); box.textContent = t; } };
    for (const f of inp.files) {
      if (f.size > 300 * 1000 * 1000) { show(`«${f.name}» pesa más de 300 MB: no se puede subir.`, true); continue; }
      try {
        const r = await subir(f, inp.dataset.videoUrl, {csrfCampo: inp.dataset.csrf,
          alAvanzar: p => show(`Subiendo «${f.name}»: ${p}%`)});
        show(r.message || "Video agregado.");
      } catch (e) { show(`«${f.name}»: ${e.message}`, true); inp.value = ""; return; }
    }
    inp.value = "";
    setTimeout(() => location.reload(), 900);
  }));
})();
