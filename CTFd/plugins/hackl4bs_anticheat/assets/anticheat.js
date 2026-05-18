(function () {
  "use strict";

  var _lockoutEnd    = null;
  var _lockoutTimer  = null;

  // ── Inyectar estilos una sola vez ──────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("hl-ac-styles")) return;
    var s = document.createElement("style");
    s.id = "hl-ac-styles";
    s.textContent = [
      "#hl-ac-banner {",
      "  display: none;",
      "  align-items: center;",
      "  gap: 12px;",
      "  padding: 12px 16px;",
      "  margin: 12px 0;",
      "  background: rgba(255,68,68,.08);",
      "  border: 1px solid rgba(255,68,68,.35);",
      "  border-radius: 8px;",
      "  animation: hl-ac-fadein .3s ease;",
      "}",
      "#hl-ac-banner.visible { display: flex; }",
      "@keyframes hl-ac-fadein { from { opacity:0; transform:translateY(-4px); } to { opacity:1; transform:none; } }",
      "#hl-ac-icon { font-size: 22px; flex-shrink: 0; }",
      "#hl-ac-title { font-weight: 700; color: #ff4444; font-family: monospace; font-size: 12px; letter-spacing: 1px; }",
      "#hl-ac-countdown { font-size: 13px; color: #8b949e; font-family: monospace; margin-top: 2px; }",
      ".hl-ac-attempts-bar {",
      "  height: 3px;",
      "  background: #21262d;",
      "  border-radius: 2px;",
      "  margin-top: 8px;",
      "  overflow: hidden;",
      "}",
      ".hl-ac-attempts-fill {",
      "  height: 100%;",
      "  background: linear-gradient(to right, #f0e040, #ff4444);",
      "  border-radius: 2px;",
      "  transition: width .4s;",
      "}",
    ].join("\n");
    document.head.appendChild(s);
  }

  // ── Banner de lockout ──────────────────────────────────────────────────────
  function getBanner() {
    var existing = document.getElementById("hl-ac-banner");
    if (existing) return existing;

    var banner = document.createElement("div");
    banner.id = "hl-ac-banner";
    banner.innerHTML = [
      '<div id="hl-ac-icon">🔒</div>',
      '<div>',
      '  <div id="hl-ac-title">DEMASIADOS INTENTOS FALLIDOS</div>',
      '  <div id="hl-ac-countdown">Calculando...</div>',
      '</div>',
    ].join("");

    // Insertar antes del botón de submit del modal de challenge
    var submitBtn =
      document.querySelector("#challenge-submit") ||
      document.querySelector("button[data-submit]") ||
      document.querySelector(".modal-footer button[type=submit]") ||
      document.querySelector("[id*=submit]");

    if (submitBtn && submitBtn.parentNode) {
      submitBtn.parentNode.insertBefore(banner, submitBtn);
    } else {
      // Fallback: append al modal body activo
      var modalBody = document.querySelector(".modal.show .modal-body") ||
                      document.querySelector(".modal-body");
      if (modalBody) modalBody.appendChild(banner);
    }
    return banner;
  }

  function showLockout(remainingSeconds) {
    injectStyles();
    _lockoutEnd = Date.now() + remainingSeconds * 1000;

    var banner = getBanner();
    banner.classList.add("visible");

    // Deshabilitar submit
    var submitBtn = document.querySelector("#challenge-submit, button[data-submit], .modal-footer button[type=submit]");
    if (submitBtn) submitBtn.disabled = true;

    if (_lockoutTimer) clearInterval(_lockoutTimer);

    function tick() {
      var rem = Math.max(0, Math.ceil((_lockoutEnd - Date.now()) / 1000));
      var mins = Math.floor(rem / 60);
      var secs = rem % 60;
      var countdownEl = document.getElementById("hl-ac-countdown");
      if (countdownEl) {
        countdownEl.textContent = rem > 0
          ? "Bloqueado por " + (mins > 0 ? mins + "m " : "") + secs + "s más"
          : "Ya puedes intentar de nuevo ✓";
      }
      if (rem <= 0) {
        clearInterval(_lockoutTimer);
        _lockoutTimer = null;
        setTimeout(function () {
          var b = document.getElementById("hl-ac-banner");
          if (b) b.classList.remove("visible");
          var btn = document.querySelector("#challenge-submit, button[data-submit], .modal-footer button[type=submit]");
          if (btn) btn.disabled = false;
        }, 1500);
      }
    }
    tick();
    _lockoutTimer = setInterval(tick, 1000);
  }

  // ── Barra de intentos (advertencia previa al lockout) ──────────────────────
  function updateAttemptsBar(attempts, maxAttempts) {
    if (!attempts || !maxAttempts) return;
    var pct = Math.min(100, Math.round((attempts / maxAttempts) * 100));

    var bar = document.getElementById("hl-ac-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "hl-ac-bar";
      bar.className = "hl-ac-attempts-bar";
      bar.innerHTML = '<div class="hl-ac-attempts-fill" style="width:0%"></div>';
      var submitBtn = document.querySelector("#challenge-submit, button[data-submit], .modal-footer button[type=submit]");
      if (submitBtn && submitBtn.parentNode) {
        submitBtn.parentNode.insertBefore(bar, submitBtn.nextSibling);
      }
    }

    var fill = bar.querySelector(".hl-ac-attempts-fill");
    if (fill) fill.style.width = pct + "%";

    // Quitar barra si está vacía
    if (pct === 0) bar.style.display = "none";
    else bar.style.display = "block";
  }

  // ── Interceptar fetch para capturar 429 ────────────────────────────────────
  var _origFetch = window.fetch;
  window.fetch = function () {
    var args = Array.prototype.slice.call(arguments);
    var url = (args[0] && args[0].toString) ? args[0].toString() : "";

    return _origFetch.apply(window, args).then(function (response) {
      if (url.indexOf("/api/v1/challenges/attempt") !== -1) {
        if (response.status === 429) {
          var clone = response.clone();
          clone.json().then(function (data) {
            var rem = (data.data && data.data.remaining_seconds) ? data.data.remaining_seconds : 60;
            showLockout(rem);
          }).catch(function () { showLockout(60); });
        } else if (response.status === 200) {
          // En respuesta correcta → limpiar barra
          var clone2 = response.clone();
          clone2.json().then(function (data) {
            var status = data && data.data && data.data.status;
            if (status === "incorrect") {
              // Consultar estado actualizado
              setTimeout(function () {
                var bodyStr = args[1] && args[1].body ? args[1].body : "{}";
                var body = {};
                try { body = JSON.parse(bodyStr); } catch (e) {}
                var chalId = body.challenge_id;
                if (chalId) {
                  fetch("/api/hackl4bs/anticheat/status/" + chalId)
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                      if (d.locked) {
                        showLockout(d.remaining_seconds);
                      } else {
                        updateAttemptsBar(d.attempts, d.max_attempts);
                      }
                    })
                    .catch(function () {});
                }
              }, 200);
            } else if (status === "correct" || status === "already_solved") {
              var bar = document.getElementById("hl-ac-bar");
              if (bar) bar.remove();
              var banner = document.getElementById("hl-ac-banner");
              if (banner) banner.classList.remove("visible");
            }
          }).catch(function () {});
        }
      }
      return response;
    });
  };

  // ── Limpiar banner al cerrar el modal de challenge ─────────────────────────
  document.addEventListener("hidden.bs.modal", function () {
    var banner = document.getElementById("hl-ac-banner");
    if (banner) banner.classList.remove("visible");
    var bar = document.getElementById("hl-ac-bar");
    if (bar) bar.remove();
    if (_lockoutTimer) {
      clearInterval(_lockoutTimer);
      _lockoutTimer = null;
    }
  });

  document.addEventListener("challenge:closed", function () {
    var banner = document.getElementById("hl-ac-banner");
    if (banner) banner.classList.remove("visible");
  });

})();
