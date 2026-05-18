/**
 * Whaley CTFd Plugin
 * Inyecta un panel "Iniciar Instancia" en el modal de cada reto.
 */

(function () {
  "use strict";

  const WHALEY_API = "/api/whaley";

  // Puertos que se consideran web (HTTP/HTTPS)
  const WEB_PORTS = new Set([80, 443, 8080, 8443, 3000, 5000, 5001, 8000, 8888, 4000]);

  // Categorías de retos que usan conexión HTTP
  const WEB_CATEGORIES = new Set(["web"]);

  // ── Banner de penalización global ─────────────────────────────────────────
  let _penaltyBanner = null;
  let _penaltyInterval = null;

  async function checkGlobalPenalty() {
    try {
      const resp = await fetch(`${WHALEY_API}/my-penalty`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.active) {
        showPenaltyBanner(data);
      } else {
        hidePenaltyBanner();
      }
    } catch (e) { }
  }

  function showPenaltyBanner(data) {
    if (!_penaltyBanner) {
      _penaltyBanner = document.createElement("div");
      _penaltyBanner.id = "whaley-penalty-banner";
      document.body.prepend(_penaltyBanner);
    }
    const icon = data.type === "ban" ? "🚨" : "⚠️";
    const label = data.type === "ban" ? "BAN ACTIVO" : "BLOQUEADO";
    _penaltyBanner.textContent = `${icon} ${label}: ${data.reason}. Tiempo restante: ${data.remaining_str}`;
    _penaltyBanner.style.cssText =
      "position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px 16px;" +
      "text-align:center;font-family:monospace;font-size:13px;font-weight:bold;" +
      (data.type === "ban"
        ? "background:#7b1a1a;color:#ffd6d6;border-bottom:2px solid #e74c3c;"
        : "background:#7b5a00;color:#fff3cd;border-bottom:2px solid #f39c12;");
  }

  function hidePenaltyBanner() {
    if (_penaltyBanner) {
      _penaltyBanner.remove();
      _penaltyBanner = null;
    }
  }

  // Verificar cada 15 s y al cargar
  checkGlobalPenalty();
  setInterval(checkGlobalPenalty, 15000);

  // ── Estilos del panel Whaley ────────────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent = `
    .whaley-panel {
      background: #1a1a2e;
      border: 1px solid #16213e;
      border-radius: 8px;
      padding: 16px;
      margin-top: 16px;
      color: #e0e0e0;
      font-family: monospace;
    }
    .whaley-panel h6 {
      color: #00d4aa;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 12px;
    }
    .whaley-btn {
      border: none;
      border-radius: 5px;
      padding: 8px 18px;
      font-size: 13px;
      cursor: pointer;
      font-weight: 600;
      transition: all 0.2s;
      margin-right: 8px;
    }
    .whaley-btn-start  { background: #00d4aa; color: #0d0d0d; }
    .whaley-btn-start:hover  { background: #00b894; }
    .whaley-btn-stop   { background: #e74c3c; color: #fff; }
    .whaley-btn-stop:hover   { background: #c0392b; }
    .whaley-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .whaley-info {
      margin-top: 12px;
      padding: 10px;
      background: #0f3460;
      border-radius: 5px;
      font-size: 13px;
      display: none;
    }
    .whaley-info.show { display: block; }
    .whaley-info a { color: #00d4aa; text-decoration: none; }
    .whaley-info a:hover { text-decoration: underline; }
    .whaley-conn-block {
      margin-top: 8px;
    }
    .whaley-conn-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }
    .whaley-conn-label {
      font-size: 11px;
      color: #aaa;
      min-width: 52px;
    }
    .whaley-nc-cmd {
      background: #0a0a1a;
      border: 1px solid #16213e;
      border-radius: 4px;
      padding: 4px 10px;
      font-family: monospace;
      font-size: 13px;
      color: #00d4aa;
      flex: 1;
      user-select: all;
      cursor: text;
    }
    .whaley-copy-btn {
      background: #16213e;
      color: #00d4aa;
      border: 1px solid #00d4aa;
      border-radius: 4px;
      padding: 3px 8px;
      font-size: 11px;
      cursor: pointer;
      white-space: nowrap;
      transition: background 0.15s;
    }
    .whaley-copy-btn:hover { background: #00d4aa; color: #0d0d0d; }
    .whaley-copy-btn.copied { background: #00b894; color: #0d0d0d; }
    .whaley-timer {
      font-size: 11px;
      color: #aaa;
      margin-top: 6px;
    }
    .whaley-status-dot {
      display: inline-block;
      width: 8px; height: 8px;
      border-radius: 50%;
      margin-right: 6px;
    }
    .dot-green { background: #00d4aa; }
    .dot-red   { background: #e74c3c; }
    .dot-yellow { background: #f39c12; animation: blink 1s infinite; }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
    .whaley-msg {
      font-size: 12px;
      margin-top: 8px;
      color: #aaa;
      min-height: 18px;
    }
    .whaley-msg.error { color: #e74c3c; }
    .whaley-msg.success { color: #00d4aa; }
    .whaley-floating-btn {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: #00d4aa;
      color: #0f3460;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      z-index: 9999;
      transition: all 0.3s ease;
      display: none;
    }
    .whaley-floating-btn:hover {
      transform: scale(1.1);
      box-shadow: 0 6px 16px rgba(0, 212, 170, 0.4);
    }
    .whaley-badge {
      position: absolute;
      top: -4px;
      right: -4px;
      background: #e74c3c;
      color: white;
      font-size: 11px;
      font-weight: bold;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .whaley-floating-panel {
      position: fixed;
      bottom: 90px;
      right: 24px;
      width: 320px;
      max-height: 400px;
      overflow-y: auto;
      background: #1a1a2e;
      border: 1px solid #16213e;
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5);
      z-index: 9998;
      padding: 16px;
      display: none;
      color: #e0e0e0;
      font-family: monospace;
    }
    .whaley-floating-panel.open {
      display: block;
      animation: slideUp 0.3s ease;
    }
    @keyframes slideUp {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .whaley-floating-header {
      border-bottom: 1px solid #16213e;
      padding-bottom: 8px;
      margin-bottom: 12px;
      font-weight: bold;
      color: #00d4aa;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 14px;
    }
    .whaley-tabs {
      display: flex;
      gap: 4px;
      margin-bottom: 10px;
    }
    .whaley-tab {
      flex: 1;
      background: #0f3460;
      border: none;
      color: #aaa;
      padding: 5px 8px;
      border-radius: 4px;
      cursor: pointer;
      font-family: monospace;
      font-size: 11px;
    }
    .whaley-tab.active {
      background: #00d4aa;
      color: #000;
      font-weight: bold;
    }
    .whaley-activity-item {
      padding: 7px 10px;
      border-radius: 5px;
      margin-bottom: 6px;
      font-size: 11px;
      line-height: 1.4;
      background: #0f3460;
    }
    .whaley-activity-item.solved { border-left: 3px solid #00d4aa; }
    .whaley-activity-item.started { border-left: 3px solid #f39c12; }
    .whaley-activity-time {
      color: #888;
      font-size: 10px;
      float: right;
    }
    .whaley-activity-empty {
      text-align: center;
      color: #aaa;
      padding: 20px;
      font-size: 12px;
    }
    .whaley-instance-item {
      background: #0f3460;
      padding: 10px;
      border-radius: 6px;
      margin-bottom: 10px;
      font-size: 12px;
    }
    .whaley-instance-item:last-child { margin-bottom: 0; }
    .whaley-instance-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }
    .whaley-instance-name { font-weight: bold; color: #fff; }
    .whaley-instance-link { color: #00d4aa; text-decoration: none; word-break: break-all; }
    .whaley-instance-link:hover { text-decoration: underline; }
    .whaley-instance-nc {
      color: #00d4aa;
      background: #0a0a1a;
      border-radius: 4px;
      padding: 3px 6px;
      user-select: all;
      word-break: break-all;
    }
    .whaley-instance-timer { color: #aaa; margin-top: 6px; font-size: 11px; }
    .whaley-stop-btn-sm {
      background: #e74c3c;
      color: #fff;
      border: none;
      border-radius: 4px;
      padding: 4px 8px;
      font-size: 11px;
      cursor: pointer;
    }
    .whaley-stop-btn-sm:hover { background: #c0392b; }
    .whaley-close-panel { cursor: pointer; color: #aaa; font-size: 16px; }
    .whaley-close-panel:hover { color: #fff; }
    .whaley-owner-badge {
      background: rgba(243,156,18,0.15);
      border: 1px solid rgba(243,156,18,0.4);
      color: #f39c12;
      border-radius: 4px;
      padding: 4px 10px;
      font-size: 11px;
      margin-bottom: 8px;
      font-family: 'Courier New', monospace;
    }
    .whaley-owner-tag {
      font-size: 10px;
      color: #f39c12;
      background: rgba(243,156,18,0.15);
      border-radius: 3px;
      padding: 1px 5px;
      margin-left: 6px;
      font-family: 'Courier New', monospace;
    }
  `;
  document.head.appendChild(style);

  // ── Helpers de conexión ─────────────────────────────────────────────────────

  /**
   * Intenta obtener la categoría del reto actual desde el DOM del modal de CTFd.
   * CTFd la pone en distintos sitios según la versión/tema.
   */
  function getChallengeCategory() {
    const selectors = [
      ".challenge-category",
      "[data-chal-category]",
      "[data-category]",
      ".category-badge",
      ".badge",
    ];
    const modal = document.querySelector(
      "#challenge-window, .challenge-window, #challenge-modal, .modal.show"
    );
    const scope = modal || document;
    for (const sel of selectors) {
      const el = scope.querySelector(sel);
      if (el) {
        const text = (el.dataset.chalCategory || el.dataset.category || el.textContent || "").trim().toLowerCase();
        if (text) return text;
      }
    }
    return null;
  }

  /**
   * Determina si una conexión es web (HTTP) o TCP (nc/netcat).
   * Prioriza la categoría del reto; si no está disponible, usa el número de puerto.
   */
  function isWebConnection(port, category) {
    if (category && WEB_CATEGORIES.has(category.toLowerCase())) return true;
    if (category && category.toLowerCase() !== "web") return false;
    return WEB_PORTS.has(parseInt(port, 10));
  }

  /**
   * Copia texto al portapapeles y da feedback visual al botón.
   */
  function copyToClipboard(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = "¡Copiado!";
      btn.classList.add("copied");
      setTimeout(() => {
        btn.textContent = "Copiar";
        btn.classList.remove("copied");
      }, 1500);
    }).catch(() => {
      // Fallback para navegadores sin clipboard API
      const el = document.createElement("textarea");
      el.value = text;
      el.style.position = "fixed";
      el.style.opacity = "0";
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      btn.textContent = "¡Copiado!";
      setTimeout(() => { btn.textContent = "Copiar"; }, 1500);
    });
  }

  /**
   * Genera el HTML de conexión para una sola URL (host:port).
   * Devuelve HTML con enlace (web) o comando nc con botón copiar (tcp).
   */
  function buildConnectionHTML(publicUrl, internalPort, category) {
    if (!publicUrl) return "";
    const parts = publicUrl.split(":");
    const host = parts.slice(0, -1).join(":");
    const port = parts[parts.length - 1];

    if (isWebConnection(port, category)) {
      const url = `http://${publicUrl}`;
      return `<a href="${url}" target="_blank" rel="noopener" class="whaley-instance-link">${url}</a>`;
    } else {
      const cmd = `nc ${host} ${port}`;
      return `
        <div class="whaley-conn-row">
          <span class="whaley-conn-label">TCP:</span>
          <span class="whaley-nc-cmd" id="nc-cmd-${internalPort}">${cmd}</span>
          <button class="whaley-copy-btn" data-cmd="${cmd}">Copiar</button>
        </div>`;
    }
  }

  // ── Obtener el challenge_id del modal abierto ───────────────────────────────
  function getChallengeId() {
    const form = document.getElementById("challenge-id");
    if (form) return form.value;

    const modal = document.querySelector(".challenge-window");
    if (modal) {
      const idField = modal.querySelector("[data-chal-id], [name='id'], #challenge-id");
      if (idField) return idField.value || idField.dataset.chalId;
    }

    const activeLink = document.querySelector("a[data-chal-id].active, [data-chal-id]");
    if (activeLink) return activeLink.dataset.chalId;

    return null;
  }

  // ── Crear el panel Whaley ───────────────────────────────────────────────────
  function createWhaleyPanel(challengeId) {
    const panel = document.createElement("div");
    panel.className = "whaley-panel";
    panel.id = "whaley-panel-" + challengeId;
    panel.innerHTML = `
      <h6>🐳 Instancia del Reto</h6>
      <div>
        <button class="whaley-btn whaley-btn-start" id="whaley-start-${challengeId}">
          ▶ Iniciar Instancia
        </button>
        <button class="whaley-btn whaley-btn-stop" id="whaley-stop-${challengeId}" style="display:none">
          ■ Detener
        </button>
        <button class="whaley-btn" id="whaley-extend-${challengeId}"
          style="display:none;background:#0f3460;color:#00d4aa;border:1px solid #00d4aa;">
          ⏱ +30 min
        </button>
      </div>
      <div class="whaley-info" id="whaley-info-${challengeId}">
        <span class="whaley-status-dot dot-green"></span>
        <strong>Instancia activa</strong>
        <div class="whaley-conn-block" id="whaley-conn-${challengeId}"></div>
        <div class="whaley-timer" id="whaley-timer-${challengeId}"></div>
      </div>
      <div class="whaley-msg" id="whaley-msg-${challengeId}"></div>
      <div id="whaley-stats-${challengeId}" style="margin-top: 12px; font-size: 12px; color: #aaa; display: none;"></div>
    `;

    const startBtn = panel.querySelector(`#whaley-start-${challengeId}`);
    const stopBtn = panel.querySelector(`#whaley-stop-${challengeId}`);
    const extendBtn = panel.querySelector(`#whaley-extend-${challengeId}`);
    const info = panel.querySelector(`#whaley-info-${challengeId}`);
    const connBlock = panel.querySelector(`#whaley-conn-${challengeId}`);
    const msg = panel.querySelector(`#whaley-msg-${challengeId}`);
    const timer = panel.querySelector(`#whaley-timer-${challengeId}`);
    const statsDiv = panel.querySelector(`#whaley-stats-${challengeId}`);

    let instanceId = null;
    let countdownInterval = null;

    async function loadStats() {
      window.whaleyFastestUser = null;
      window.whaleyFastestTime = null;
      try {
        const resp = await fetch(`${WHALEY_API}/stats/${challengeId}`);
        const data = await resp.json();
        let html = "";
        if (data.fastest) {
          window.whaleyFastestUser = data.fastest.user_name;
          window.whaleyFastestTime = data.fastest.time_str;
          html += `<div>⚡ <strong>Más Rápido:</strong> ${data.fastest.user_name} (${data.fastest.time_str})</div>`;
        }
        if (html) {
          statsDiv.innerHTML = html;
          statsDiv.style.display = "block";
        }
      } catch (e) {
        console.log("No se pudieron cargar los stats", e);
      }
    }

    function setMsg(text, type = "") {
      msg.textContent = text;
      msg.className = "whaley-msg" + (type ? " " + type : "");
    }

    function showInstance(data) {
      instanceId = data.instance_id || null;
      const category = getChallengeCategory();

      // Construir bloque de conexión
      let connHTML = "";

      if (data.public_urls && Object.keys(data.public_urls).length > 0) {
        // Múltiples puertos
        for (const [internalPort, publicUrl] of Object.entries(data.public_urls)) {
          connHTML += buildConnectionHTML(publicUrl, internalPort, category);
        }
      } else {
        // Un solo puerto
        const singleUrl = data.public_url || (data.host && data.port ? `${data.host}:${data.port}` : "");
        connHTML = buildConnectionHTML(singleUrl, "0", category);
      }

      connBlock.innerHTML = connHTML;

      // Asignar eventos de copiar
      connBlock.querySelectorAll(".whaley-copy-btn").forEach(btn => {
        btn.addEventListener("click", () => copyToClipboard(btn.dataset.cmd, btn));
      });

      info.classList.add("show");
      startBtn.style.display = "none";

      // Solo el creador puede detener/extender su propia instancia
      const isMine = data.is_mine !== false; // true por defecto si no viene el campo
      stopBtn.style.display = isMine ? "inline-block" : "none";
      extendBtn.style.display = isMine ? "inline-block" : "none";

      // Mostrar quién creó la instancia si no soy yo
      let ownerBadge = panel.querySelector(".whaley-owner-badge");
      if (!isMine && data.spawned_by) {
        if (!ownerBadge) {
          ownerBadge = document.createElement("div");
          ownerBadge.className = "whaley-owner-badge";
          info.prepend(ownerBadge);
        }
        ownerBadge.textContent = `Instancia de @${data.spawned_by} (solo lectura)`;
      } else if (ownerBadge) {
        ownerBadge.remove();
      }

      // Countdown
      if (countdownInterval) clearInterval(countdownInterval);
      let remaining = data.expires_in || 3600;
      if (data.expires_at) {
        const d = new Date(data.expires_at);
        if (!isNaN(d.getTime())) {
          remaining = Math.floor((d.getTime() - Date.now()) / 1000);
          if (remaining < 0) remaining = 0;
        }
      }

      function updateTimer() {
        if (remaining <= 0) {
          clearInterval(countdownInterval);
          timer.textContent = "⏱ Instancia expirada";
          resetPanel();
          return;
        }
        const m = Math.floor(remaining / 60);
        const s = remaining % 60;
        timer.textContent = `⏱ Expira en: ${m}m ${s < 10 ? "0" : ""}${s}s`;
        remaining--;
      }
      updateTimer();
      countdownInterval = setInterval(updateTimer, 1000);
    }

    function resetPanel() {
      info.classList.remove("show");
      startBtn.style.display = "inline-block";
      stopBtn.style.display = "none";
      extendBtn.style.display = "none";
      connBlock.innerHTML = "";
      if (countdownInterval) clearInterval(countdownInterval);
    }

    async function checkStatus() {
      try {
        setMsg("Verificando estado...");
        const resp = await fetch(`${WHALEY_API}/status/${challengeId}`);
        const data = await resp.json();
        if (data.running) {
          showInstance(data);
          setMsg("Instancia en ejecución.", "success");
        } else {
          setMsg("");
        }
      } catch (e) {
        setMsg("No se pudo verificar el estado.", "error");
      }
    }

    // Spawn
    startBtn.addEventListener("click", async () => {
      startBtn.disabled = true;
      setMsg("Iniciando instancia...");

      const dot = panel.querySelector(".whaley-status-dot");
      if (dot) { dot.className = "whaley-status-dot dot-yellow"; }

      try {
        const resp = await fetch(`${WHALEY_API}/spawn`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "CSRF-Token": init.csrfNonce || ""
          },
          body: JSON.stringify({ challenge_id: challengeId })
        });
        const data = await resp.json();

        if (data.success) {
          showInstance(data);
          setMsg("✓ Instancia lista.", "success");
          if (dot) dot.className = "whaley-status-dot dot-green";
          document.dispatchEvent(new Event("whaley:instancesChanged"));
        } else {
          setMsg("✗ " + (data.message || "Error al iniciar"), "error");
          if (dot) dot.className = "whaley-status-dot dot-red";
          startBtn.disabled = false;
        }
      } catch (e) {
        setMsg("✗ Error de conexión con Whaley", "error");
        startBtn.disabled = false;
      }
    });

    // Extend (+30 min)
    extendBtn.addEventListener("click", async () => {
      if (!instanceId) return;
      extendBtn.disabled = true;
      setMsg("Extendiendo instancia...");
      try {
        const resp = await fetch(`${WHALEY_API}/extend`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "CSRF-Token": init.csrfNonce || ""
          },
          body: JSON.stringify({ instance_id: instanceId, extra_minutes: 30 })
        });
        const data = await resp.json();
        if (data.success) {
          setMsg("✓ Instancia extendida 30 minutos.", "success");
          // Refrescar el estado para actualizar el countdown
          await checkStatus();
        } else {
          setMsg("✗ " + (data.message || "No se pudo extender"), "error");
        }
      } catch (e) {
        setMsg("✗ Error al extender", "error");
      } finally {
        extendBtn.disabled = false;
      }
    });

    // Stop
    stopBtn.addEventListener("click", async () => {
      stopBtn.disabled = true;
      setMsg("Deteniendo instancia...");
      try {
        await fetch(`${WHALEY_API}/stop`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "CSRF-Token": init.csrfNonce || ""
          },
          body: JSON.stringify({ challenge_id: challengeId, instance_id: instanceId })
        });
        resetPanel();
        setMsg("Instancia detenida.");
        stopBtn.disabled = false;
        document.dispatchEvent(new Event("whaley:instancesChanged"));
      } catch (e) {
        setMsg("Error al detener.", "error");
        stopBtn.disabled = false;
      }
    });

    checkStatus();
    loadStats();

    return panel;
  }

  // ── Inyectar panel cuando se abre un modal de challenge ────────────────────
  function injectWhaleyPanel() {
    const modalBody = document.querySelector(
      "#challenge-window .modal-body, " +
      ".challenge-window .card-body, " +
      "#challenge-modal .modal-body"
    );

    if (!modalBody) return;
    if (modalBody.querySelector(".whaley-panel")) return;

    const chalId = getChallengeId();
    if (!chalId) return;

    const panel = createWhaleyPanel(chalId);
    modalBody.appendChild(panel);
  }

  // ── Observar apertura de modales ───────────────────────────────────────────
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType === 1) {
          if (
            node.id === "challenge-window" ||
            node.classList?.contains("challenge-window") ||
            node.querySelector?.("#challenge-id")
          ) {
            setTimeout(injectWhaleyPanel, 100);
          }
        }
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  document.addEventListener("shown.bs.modal", () => {
    setTimeout(injectWhaleyPanel, 150);
  });

  document.addEventListener("challenge:opened", () => {
    setTimeout(injectWhaleyPanel, 150);
  });

  // ── Floating Widget ────────────────────────────────────────────────────────
  function initFloatingWidget() {
    const floatBtn = document.createElement("div");
    floatBtn.className = "whaley-floating-btn";
    floatBtn.innerHTML = `🐳<div class="whaley-badge" id="whaley-float-badge" style="display:none">0</div>`;
    document.body.appendChild(floatBtn);

    const floatPanel = document.createElement("div");
    floatPanel.className = "whaley-floating-panel";
    floatPanel.id = "whaley-float-panel";
    floatPanel.innerHTML = `
      <div class="whaley-floating-header">
        <span> HackL4bs CTF</span>
        <span class="whaley-close-panel" id="whaley-close-float">&times;</span>
      </div>
      <div class="whaley-tabs">
        <button class="whaley-tab active" data-tab="instances">Instancias</button>
        <button class="whaley-tab" data-tab="activity">👥 Equipo</button>
      </div>
      <div id="whaley-float-content">Cargando...</div>
      <div id="whaley-activity-content" style="display:none">Cargando...</div>
    `;
    document.body.appendChild(floatPanel);

    let activeInstances = [];

    let activeTab = "instances";

    floatPanel.querySelectorAll(".whaley-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        floatPanel.querySelectorAll(".whaley-tab").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activeTab = btn.dataset.tab;
        document.getElementById("whaley-float-content").style.display = activeTab === "instances" ? "" : "none";
        document.getElementById("whaley-activity-content").style.display = activeTab === "activity" ? "" : "none";
        if (activeTab === "activity") fetchTeamActivity();
      });
    });

    floatBtn.addEventListener("click", () => {
      floatPanel.classList.toggle("open");
      if (floatPanel.classList.contains("open")) {
        if (activeTab === "instances") renderFloatingInstances();
        else fetchTeamActivity();
      }
    });

    document.getElementById("whaley-close-float").addEventListener("click", () => {
      floatPanel.classList.remove("open");
    });

    // ── Team Activity Feed ────────────────────────────────────────────────────
    function timeAgo(isoStr) {
      const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
      if (diff < 60) return `hace ${diff}s`;
      if (diff < 3600) return `hace ${Math.floor(diff / 60)}m`;
      if (diff < 86400) return `hace ${Math.floor(diff / 3600)}h`;
      return `hace ${Math.floor(diff / 86400)}d`;
    }

    async function fetchTeamActivity() {
      const el = document.getElementById("whaley-activity-content");
      try {
        const resp = await fetch(`${WHALEY_API}/team-activity`);
        if (!resp.ok) { el.innerHTML = `<div class="whaley-activity-empty">Error al cargar actividad.</div>`; return; }
        const data = await resp.json();
        renderTeamActivity(data.events || []);
      } catch (e) {
        el.innerHTML = `<div class="whaley-activity-empty">Sin conexión.</div>`;
      }
    }

    function renderTeamActivity(events) {
      const el = document.getElementById("whaley-activity-content");
      if (!events.length) {
        el.innerHTML = `<div class="whaley-activity-empty">Sin actividad reciente del equipo.</div>`;
        return;
      }
      el.innerHTML = events.map(ev => {
        const who = ev.is_me ? "Tú" : `<strong>${ev.username}</strong>`;
        const when = timeAgo(ev.time);
        if (ev.type === "started") {
          return `<div class="whaley-activity-item started">
            🟢 ${who} inició <em>${ev.challenge}</em> <span class="whaley-activity-time">${when}</span>
          </div>`;
        } else {
          return `<div class="whaley-activity-item solved">
            ✅ ${who} completó <em>${ev.challenge}</em> en ${ev.duration} <span class="whaley-activity-time">${when}</span>
          </div>`;
        }
      }).join("");
    }

    async function fetchAllInstances() {
      try {
        const resp = await fetch(`${WHALEY_API}/instances`);
        if (!resp.ok) return;
        const data = await resp.json();
        activeInstances = data.instances || [];

        const badge = document.getElementById("whaley-float-badge");
        if (activeInstances.length > 0) {
          floatBtn.style.display = "flex";
          badge.style.display = "flex";
          badge.textContent = activeInstances.length;
        } else {
          floatBtn.style.display = "none";
          badge.style.display = "none";
          floatPanel.classList.remove("open");
        }

        if (floatPanel.classList.contains("open")) {
          renderFloatingInstances();
        }
      } catch (e) {
        console.error("Whaley:", e);
      }
    }

    function renderFloatingInstances() {
      const content = document.getElementById("whaley-float-content");
      if (activeInstances.length === 0) {
        content.innerHTML = `<div style="text-align:center; color:#aaa; padding:20px;">No hay instancias activas.</div>`;
        return;
      }

      let html = "";
      activeInstances.forEach((inst, index) => {
        let remaining = 3600;
        if (inst.expires_at) {
          const d = new Date(inst.expires_at);
          if (!isNaN(d.getTime())) {
            remaining = Math.floor((d.getTime() - Date.now()) / 1000);
            if (remaining < 0) remaining = 0;
          }
        }

        const m = Math.floor(remaining / 60);
        const s = remaining % 60;
        const timeStr = remaining > 0 ? `${m}m ${s < 10 ? "0" : ""}${s}s` : "Expirada";

        // Determinar cómo mostrar la conexión en el panel flotante
        const publicUrl = inst.public_url || "";
        let connDisplay = "";
        if (publicUrl) {
          const parts = publicUrl.split(":");
          const port = parts[parts.length - 1];
          const host = parts.slice(0, -1).join(":");
          // En el panel flotante no tenemos la categoría fácilmente, usamos el puerto
          if (WEB_PORTS.has(parseInt(port, 10))) {
            connDisplay = `<a href="http://${publicUrl}" target="_blank" class="whaley-instance-link">http://${publicUrl}</a>`;
          } else {
            connDisplay = `<span class="whaley-instance-nc">nc ${host} ${port}</span>`;
          }
        }

        const isMine = inst.is_mine !== false;
        const ownerTag = !isMine && inst.spawned_by
          ? `<span class="whaley-owner-tag">@${inst.spawned_by}</span>` : "";
        const stopBtnHtml = isMine
          ? `<button class="whaley-stop-btn-sm" data-idx="${index}">Detener</button>` : "";

        html += `
          <div class="whaley-instance-item">
            <div class="whaley-instance-header">
              <span class="whaley-instance-name">${inst.challenge_id}${ownerTag}</span>
              ${stopBtnHtml}
            </div>
            <div>${connDisplay}</div>
            <div class="whaley-instance-timer">⏱ Expira en: <span>${timeStr}</span></div>
          </div>
        `;
      });
      content.innerHTML = html;

      content.querySelectorAll(".whaley-stop-btn-sm").forEach(btn => {
        btn.addEventListener("click", async (e) => {
          const idx = e.target.getAttribute("data-idx");
          const inst = activeInstances[idx];
          e.target.disabled = true;
          e.target.textContent = "...";
          try {
            await fetch(`${WHALEY_API}/stop`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "CSRF-Token": init.csrfNonce || ""
              },
              body: JSON.stringify({ instance_id: inst.instance_id, challenge_id: inst.challenge_id })
            });
            setTimeout(fetchAllInstances, 1000);
            if (document.getElementById(`whaley-stop-${inst.challenge_id}`)) {
              document.getElementById(`whaley-stop-${inst.challenge_id}`).click();
            }
          } catch (err) {
            e.target.disabled = false;
            e.target.textContent = "Detener";
          }
        });
      });
    }

    fetchAllInstances();
    setInterval(fetchAllInstances, 30000);
    setInterval(() => {
      if (floatPanel.classList.contains("open")) {
        if (activeTab === "instances") renderFloatingInstances();
      }
    }, 1000);
    setInterval(() => {
      if (floatPanel.classList.contains("open") && activeTab === "activity") {
        fetchTeamActivity();
      }
    }, 20000);
    document.addEventListener("whaley:instancesChanged", fetchAllInstances);
  }

  async function maybeInitFloatingWidget() {
    try {
      const resp = await fetch("/api/v1/users/me");
      if (!resp.ok) return;
      const data = await resp.json();
      const user = data.data;
      if (!user || !user.team_id) return;
      initFloatingWidget();
    } catch (e) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", maybeInitFloatingWidget);
  } else {
    maybeInitFloatingWidget();
  }

})();
