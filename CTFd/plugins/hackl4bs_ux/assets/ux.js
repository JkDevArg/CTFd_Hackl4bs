/**
 * HackL4bs UX Plugin
 * 10 mejoras de experiencia de usuario para el CTF.
 */
(function () {
  "use strict";

  const API = "/api/hackl4bs";

  // ── Utilidades generales ───────────────────────────────────────────────────

  function showToast(msg, type = "") {
    let container = document.getElementById("ux-toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "ux-toast-container";
      document.body.appendChild(container);
    }
    const toast = document.createElement("div");
    toast.className = "ux-toast" + (type ? " " + type : "");
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5200);
  }

  function timeAgo(isoDate) {
    if (!isoDate) return "";
    const diff = Math.floor((Date.now() - new Date(isoDate).getTime()) / 1000);
    if (diff < 60) return `${diff}s`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}d`;
  }

  function getCsrf() {
    return (typeof init !== "undefined" && init.csrfNonce) ? init.csrfNonce : "";
  }

  async function apiFetch(url, opts = {}) {
    opts.headers = Object.assign({ "Content-Type": "application/json", "CSRF-Token": getCsrf() }, opts.headers || {});
    const resp = await fetch(url, opts);
    return resp.json();
  }

  // ── 8. COUNTDOWN ──────────────────────────────────────────────────────────
  async function initCountdown() {
    try {
      const data = await apiFetch(`${API}/ctf-info`);
      const endTs = data.end ? parseInt(data.end, 10) * 1000 : null;
      const startTs = data.start ? parseInt(data.start, 10) * 1000 : null;
      if (!endTs) return;

      const banner = document.createElement("div");
      banner.id = "ux-countdown";
      // Insertar debajo del navbar
      const navbar = document.querySelector("nav, .navbar, header");
      if (navbar) navbar.insertAdjacentElement("afterend", banner);
      else document.body.prepend(banner);

      function tick() {
        const now = Date.now();
        if (startTs && now < startTs) {
          const rem = Math.floor((startTs - now) / 1000);
          const h = Math.floor(rem / 3600), m = Math.floor((rem % 3600) / 60), s = rem % 60;
          banner.innerHTML = `CTF comienza en <span>${h}h ${m}m ${s}s</span>`;
          banner.classList.remove("ending");
          return;
        }
        const rem = Math.floor((endTs - now) / 1000);
        if (rem <= 0) {
          banner.innerHTML = "🏁 <span>CTF finalizado</span>";
          clearInterval(_cdInterval);
          return;
        }
        const h = Math.floor(rem / 3600), m = Math.floor((rem % 3600) / 60), s = rem % 60;
        banner.innerHTML = `⏱ Tiempo restante: <span>${h}h ${String(m).padStart(2,"0")}m ${String(s).padStart(2,"0")}s</span>`;
        banner.classList.toggle("ending", rem < 600);
      }
      tick();
      const _cdInterval = setInterval(tick, 1000);
    } catch (e) {}
  }

  // ── 2. FIRST BLOOD TOASTS ─────────────────────────────────────────────────
  const _knownBloods = new Set();
  let _bloodsReady = false;

  async function pollFirstBloods() {
    try {
      const data = await apiFetch(`${API}/first-bloods`);
      for (const fb of (data.first_bloods || [])) {
        const key = String(fb.challenge_id);
        if (!_knownBloods.has(key)) {
          if (_bloodsReady) {
            showToast(`🩸 First Blood! ${fb.solver} resolvió "${fb.challenge_name}"`, "blood");
          }
          _knownBloods.add(key);
        }
      }
      _bloodsReady = true;
    } catch (e) {}
  }

  // ── 4. CONFETTI (solve celebration) ───────────────────────────────────────
  const CONFETTI_COLORS = ["#00d4aa","#e74c3c","#f39c12","#3498db","#9b59b6","#27ae60","#fff"];

  function triggerConfetti() {
    const count = 80;
    for (let i = 0; i < count; i++) {
      const el = document.createElement("div");
      el.className = "ux-confetti-piece";
      el.style.cssText = [
        `left:${Math.random() * 100}vw`,
        `background:${CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)]}`,
        `width:${6 + Math.random() * 8}px`,
        `height:${6 + Math.random() * 8}px`,
        `animation-duration:${1.5 + Math.random() * 2}s`,
        `animation-delay:${Math.random() * 0.5}s`,
        `border-radius:${Math.random() > 0.5 ? "50%" : "2px"}`,
      ].join(";");
      document.body.appendChild(el);
      el.addEventListener("animationend", () => el.remove());
    }
  }

  function hookSolveCelebration() {
    // Interceptar la respuesta del endpoint de submit de CTFd
    const origFetch = window.fetch;
    window.fetch = async function (url, opts) {
      const resp = await origFetch(url, opts);
      if (typeof url === "string" && url.includes("/api/v1/challenges/attempt")) {
        try {
          const clone = resp.clone();
          const data = await clone.json();
          if (data?.data?.status === "correct") {
            setTimeout(triggerConfetti, 200);
            showToast("🎉 ¡Flag correcta!", "success");
          }
        } catch (e) {}
      }
      return resp;
    };
  }

  // ── 1. CHALLENGE FILTER / SEARCH ──────────────────────────────────────────
  function initChallengeFilter() {
    const board = document.querySelector("#challenges-board, .challenges-board, #challenge-board, [id*=challenge]");
    if (!board) return;

    // Recopilar categorías únicas de los cards
    const getCards = () => Array.from(document.querySelectorAll("[data-chal-id], .challenge-button, .card[data-chal-id]"));
    const getCategory = (card) =>
      card.dataset.chalCategory ||
      card.querySelector(".badge, .category, [class*=category]")?.textContent?.trim() ||
      "";

    const bar = document.createElement("div");
    bar.id = "ux-filter-bar";

    const search = document.createElement("input");
    search.id = "ux-search";
    search.type = "text";
    search.placeholder = "🔍 Buscar reto...";
    bar.appendChild(search);

    const allBtn = document.createElement("button");
    allBtn.className = "ux-filter-btn active";
    allBtn.textContent = "Todos";
    allBtn.dataset.cat = "";
    bar.appendChild(allBtn);

    const toggle = document.createElement("label");
    toggle.id = "ux-unsolved-toggle";
    toggle.innerHTML = '<input type="checkbox" id="ux-unsolved-check"> Solo no resueltos';
    bar.appendChild(toggle);

    // Insertar antes del board
    board.parentNode.insertBefore(bar, board);

    let activeCat = "";
    let unsolvedOnly = false;
    let categoryBtns = [allBtn];

    function buildCategoryBtns() {
      const cats = new Set();
      getCards().forEach(c => { const cat = getCategory(c); if (cat) cats.add(cat); });
      cats.forEach(cat => {
        if (categoryBtns.find(b => b.dataset.cat === cat)) return;
        const btn = document.createElement("button");
        btn.className = "ux-filter-btn";
        btn.textContent = cat;
        btn.dataset.cat = cat;
        bar.insertBefore(btn, toggle);
        categoryBtns.push(btn);
        btn.addEventListener("click", () => { activeCat = cat; applyFilter(); setActiveBtn(btn); });
      });
    }

    function setActiveBtn(active) {
      categoryBtns.forEach(b => b.classList.toggle("active", b === active));
    }

    function applyFilter() {
      const q = search.value.toLowerCase().trim();
      getCards().forEach(card => {
        const title = (card.querySelector(".challenge-name, h3, h4, .card-title, [class*=name]")?.textContent || "").toLowerCase();
        const cat = getCategory(card).toLowerCase();
        const solved = card.classList.contains("solved") || !!card.querySelector(".solved, [class*=solved]");

        const matchSearch = !q || title.includes(q);
        const matchCat = !activeCat || cat === activeCat.toLowerCase();
        const matchSolved = !unsolvedOnly || !solved;

        card.closest("div[class]").style.display = (matchSearch && matchCat && matchSolved) ? "" : "none";
      });
    }

    allBtn.addEventListener("click", () => { activeCat = ""; applyFilter(); setActiveBtn(allBtn); });
    search.addEventListener("input", applyFilter);
    document.getElementById("ux-unsolved-check").addEventListener("change", e => { unsolvedOnly = e.target.checked; applyFilter(); });

    // Construir botones de categoría cuando los cards estén disponibles
    const obs = new MutationObserver(() => { buildCategoryBtns(); applyFilter(); });
    obs.observe(board, { childList: true, subtree: true });
    setTimeout(() => { buildCategoryBtns(); }, 800);
  }

  // ── 3. CATEGORY PROGRESS ──────────────────────────────────────────────────
  async function initCategoryProgress() {
    try {
      const data = await apiFetch(`${API}/progress`);
      const cats = data.categories || {};
      if (!Object.keys(cats).length) return;

      const panel = document.createElement("div");
      panel.id = "ux-progress-panel";
      panel.innerHTML = "<h6>Progreso por categoría</h6>";

      const maxTotal = Math.max(...Object.values(cats).map(c => c.total), 1);
      Object.entries(cats).sort((a, b) => b[1].solved - a[1].solved).forEach(([cat, info]) => {
        const pct = info.total ? Math.round((info.solved / info.total) * 100) : 0;
        const complete = info.solved === info.total;
        const row = document.createElement("div");
        row.className = "ux-progress-row";
        row.innerHTML = `
          <span class="ux-progress-label">${cat}</span>
          <div class="ux-progress-track">
            <div class="ux-progress-fill${complete ? " complete" : ""}" style="width:${pct}%"></div>
          </div>
          <span class="ux-progress-count">${info.solved}/${info.total}</span>`;
        panel.appendChild(row);
      });

      const board = document.querySelector("#challenges-board, .challenges-board, #challenge-board, [id*=challenge]");
      const filterBar = document.getElementById("ux-filter-bar");
      if (filterBar) filterBar.insertAdjacentElement("afterend", panel);
      else if (board) board.parentNode.insertBefore(panel, board);
    } catch (e) {}
  }

  // ── 5. DIFFICULTY RATING ──────────────────────────────────────────────────
  async function initDifficultyRating() {
    const modal = document.querySelector(".modal.show, #challenge-window.show, #challenge-window[style*=block]");
    if (!modal) return;
    if (modal.querySelector(".ux-rating-block")) return;

    const chalIdEl = modal.querySelector("#challenge-id, [name=id], [data-chal-id]");
    if (!chalIdEl) return;
    const chalId = chalIdEl.value || chalIdEl.dataset.chalId;
    if (!chalId) return;

    const block = document.createElement("div");
    block.className = "ux-rating-block";
    block.innerHTML = `
      <h6>⭐ Dificultad</h6>
      <div class="ux-stars">
        ${[1,2,3,4,5].map(i => `<span class="ux-star" data-val="${i}">★</span>`).join("")}
      </div>
      <div class="ux-rating-avg"></div>`;

    const stars = block.querySelectorAll(".ux-star");
    const avgEl = block.querySelector(".ux-rating-avg");

    function setStars(val) {
      stars.forEach(s => s.classList.toggle("active", parseInt(s.dataset.val) <= val));
    }

    async function loadRating() {
      try {
        const d = await apiFetch(`${API}/ratings/${chalId}`);
        if (d.my_rating) setStars(d.my_rating);
        if (d.average !== null) {
          avgEl.textContent = `Promedio: ${d.average}★ (${d.count} votos)`;
        } else {
          avgEl.textContent = "Sin votos aún";
        }
      } catch (e) {}
    }

    stars.forEach(star => {
      star.addEventListener("mouseover", () => setStars(parseInt(star.dataset.val)));
      star.addEventListener("mouseleave", loadRating);
      star.addEventListener("click", async () => {
        try {
          const d = await apiFetch(`${API}/rate/${chalId}`, {
            method: "POST",
            body: JSON.stringify({ rating: parseInt(star.dataset.val) }),
          });
          if (d.success) {
            setStars(parseInt(star.dataset.val));
            avgEl.textContent = `Promedio: ${d.average}★ (${d.count} votos)`;
            showToast("⭐ Rating guardado", "success");
          } else {
            showToast(d.message || "Resuelve el reto primero", "warn");
          }
        } catch (e) {}
      });
    });

    const target = modal.querySelector(".modal-body, .card-body");
    if (target) target.appendChild(block);
    loadRating();
  }

  // ── 9. WORKING ON THIS ────────────────────────────────────────────────────
  async function initWorkingOn() {
    const modal = document.querySelector(".modal.show, #challenge-window.show, #challenge-window[style*=block]");
    if (!modal) return;
    if (modal.querySelector(".ux-working-block")) return;

    const chalIdEl = modal.querySelector("#challenge-id, [name=id], [data-chal-id]");
    if (!chalIdEl) return;
    const chalId = chalIdEl.value || chalIdEl.dataset.chalId;
    if (!chalId) return;

    const block = document.createElement("div");
    block.className = "ux-working-block";
    block.innerHTML = `
      <h6>👥 Equipo</h6>
      <button class="ux-working-btn" id="ux-working-btn-${chalId}">🔨 Trabajando en esto</button>
      <div class="ux-working-teammates" id="ux-working-mates-${chalId}"></div>`;

    const btn = block.querySelector(`#ux-working-btn-${chalId}`);
    const matesEl = block.querySelector(`#ux-working-mates-${chalId}`);
    let isWorking = false;

    async function refreshWorking() {
      try {
        const d = await apiFetch(`${API}/team-working`);
        const me = (d.working || []).find(w => w.is_me && w.challenge_id == chalId);
        isWorking = !!me;
        btn.classList.toggle("active", isWorking);
        btn.textContent = isWorking ? "✓ Trabajando en esto" : "🔨 Trabajando en esto";

        const teammates = (d.working || []).filter(w => !w.is_me && w.challenge_id == chalId);
        if (teammates.length) {
          matesEl.innerHTML = "También trabajando: " + teammates.map(w =>
            `<span class="ux-working-teammate">${w.username}</span>`
          ).join("");
        } else {
          matesEl.innerHTML = "";
        }
      } catch (e) {}
    }

    btn.addEventListener("click", async () => {
      try {
        if (isWorking) {
          await apiFetch(`${API}/working/${chalId}`, { method: "DELETE" });
        } else {
          await apiFetch(`${API}/working/${chalId}`, { method: "POST" });
        }
        await refreshWorking();
      } catch (e) {}
    });

    const target = modal.querySelector(".modal-body, .card-body");
    if (target) target.appendChild(block);
    refreshWorking();
  }

  // ── 6. TEAM ACTIVITY FEED ─────────────────────────────────────────────────
  function initTeamActivity() {
    const btn = document.createElement("div");
    btn.id = "ux-activity-btn";
    btn.title = "Actividad del equipo";
    btn.textContent = "📡";
    document.body.appendChild(btn);

    const panel = document.createElement("div");
    panel.id = "ux-activity-panel";
    panel.innerHTML = `
      <div class="ux-activity-header">
        <span>📡 Actividad del equipo</span>
        <span style="cursor:pointer;color:var(--ux-muted)" id="ux-activity-close">✕</span>
      </div>
      <div id="ux-activity-list"><div style="padding:16px;color:var(--ux-muted);font-size:12px;">Cargando...</div></div>`;
    document.body.appendChild(panel);

    btn.addEventListener("click", () => {
      panel.classList.toggle("open");
      if (panel.classList.contains("open")) renderActivity();
    });
    document.getElementById("ux-activity-close").addEventListener("click", () => panel.classList.remove("open"));

    async function renderActivity() {
      const list = document.getElementById("ux-activity-list");
      try {
        const data = await apiFetch(`${API}/activity`);
        const events = data.events || [];
        if (!events.length) {
          list.innerHTML = `<div style="padding:16px;color:var(--ux-muted);font-size:12px;">Sin actividad aún.</div>`;
          return;
        }
        list.innerHTML = events.map(e => `
          <div class="ux-activity-event">
            <span class="time">${timeAgo(e.date)}</span>
            <span class="who${e.is_me ? " me" : ""}">${e.username}</span>
            resolvió <span class="chal">${e.challenge}</span>
            <span class="pts">+${e.points}pts</span>
          </div>`).join("");
      } catch (e) {
        list.innerHTML = `<div style="padding:16px;color:var(--ux-muted);font-size:12px;">Sin equipo o no autenticado.</div>`;
      }
    }

    setInterval(() => { if (panel.classList.contains("open")) renderActivity(); }, 30000);
  }

  // ── 7. PROFILE STATS ──────────────────────────────────────────────────────
  async function initProfileStats() {
    const match = window.location.pathname.match(/\/users\/(\d+)/);
    if (!match) return;
    const userId = match[1];
    if (document.getElementById("ux-profile-stats")) return;

    try {
      const data = await apiFetch(`${API}/profile-stats/${userId}`);
      if (!data.total_solves) return;

      // username from DOM
      const usernameEl = document.querySelector(".jumbotron h1, .page-header h1, h1");
      const username = (usernameEl ? usernameEl.textContent.trim() : "operator").replace(/[<>]/g, "");

      // achievements
      const achBadges = [];
      if (data.first_blood > 0)
        achBadges.push(`<span class="ux-ach-pill ux-ach-pill-blood">🩸 First Blood ×${data.first_blood}</span>`);
      if (data.fast_solve > 0)
        achBadges.push(`<span class="ux-ach-pill ux-ach-pill-fast">⚡ Fast Solve ×${data.fast_solve}</span>`);
      const achHTML = achBadges.length ? `<div class="ux-ach-pills">${achBadges.join("")}</div>` : "";

      const catCount = Object.keys(data.by_category || {}).length;

      // ── Panel ─────────────────────────────────────────────────────────────
      const panel = document.createElement("div");
      panel.id = "ux-profile-stats";
      panel.innerHTML = `
        <div class="ux-terminal-bar">
          <div class="ux-terminal-dot ux-terminal-dot-r"></div>
          <div class="ux-terminal-dot ux-terminal-dot-y"></div>
          <div class="ux-terminal-dot ux-terminal-dot-g"></div>
          <div class="ux-terminal-title">operator — profile stats</div>
        </div>
        <div class="ux-profile-body">
          <div class="ux-profile-prompt">
            <span class="ux-prompt-sym">$</span>
            <span class="ux-prompt-host">hackl4bs</span>
            <span style="color:var(--ux-muted)">:~#</span>
            <span class="ux-prompt-user">${username}</span>
            <span class="ux-prompt-status">AUTHENTICATED</span>
          </div>
          ${achHTML}
          <div class="ux-stat-grid">
            <div class="ux-stat-card">
              <div class="ux-stat-num" data-target="${data.total_solves}">0</div>
              <div class="ux-stat-lbl">Solves</div>
            </div>
            <div class="ux-stat-card">
              <div class="ux-stat-num" data-target="${data.total_points}">0</div>
              <div class="ux-stat-lbl">Puntos</div>
            </div>
            <div class="ux-stat-card">
              <div class="ux-stat-num" data-target="${catCount}">0</div>
              <div class="ux-stat-lbl">Categorías</div>
            </div>
          </div>
        </div>`;

      const body = panel.querySelector(".ux-profile-body");

      // ── Barras por categoría ──────────────────────────────────────────────
      const cats = data.by_category || {};
      if (Object.keys(cats).length) {
        const maxCount = Math.max(...Object.values(cats), 1);
        const catSection = document.createElement("div");
        catSection.innerHTML = `<div class="ux-section-label">breakdown</div><div class="ux-cat-bars"></div>`;
        const catDiv = catSection.querySelector(".ux-cat-bars");
        Object.entries(cats).sort((a, b) => b[1] - a[1]).forEach(([cat, count]) => {
          const pct = Math.round((count / maxCount) * 100);
          catDiv.innerHTML += `
            <div class="ux-cat-bar-row">
              <span class="ux-cat-bar-label">${cat}</span>
              <div class="ux-cat-bar-track"><div class="ux-cat-bar-fill" data-pct="${pct}"></div></div>
              <span class="ux-cat-bar-count">${count}</span>
            </div>`;
        });
        body.appendChild(catSection);
      }

      // ── Timeline sparkline ────────────────────────────────────────────────
      if ((data.timeline || []).length > 1) {
        const timeSection = document.createElement("div");
        timeSection.innerHTML = `<div class="ux-section-label">actividad</div>`;
        const barsDiv = document.createElement("div");
        barsDiv.className = "ux-timeline-bars";
        const maxCount = Math.max(...data.timeline.map(t => t.count), 1);
        data.timeline.forEach(point => {
          const bar = document.createElement("div");
          bar.className = "ux-timeline-bar";
          bar.style.height = `${Math.round((point.count / maxCount) * 40)}px`;
          bar.dataset.tip = `${point.date}: ${point.count}`;
          barsDiv.appendChild(bar);
        });
        timeSection.appendChild(barsDiv);
        body.appendChild(timeSection);
      }

      // ── Inyección ─────────────────────────────────────────────────────────
      const anchor =
        document.getElementById("solves-row") ||
        document.getElementById("keys-row") ||
        document.querySelector("[id*='solve']") ||
        (() => {
          const tbl = document.querySelector("table");
          return tbl ? tbl.closest(".row, section, .card") : null;
        })();

      const wrapper = document.createElement("div");
      wrapper.className = "row mb-4";
      const col = document.createElement("div");
      col.className = "col-md-12";
      col.appendChild(panel);
      wrapper.appendChild(col);

      if (anchor && anchor.parentNode) {
        anchor.parentNode.insertBefore(wrapper, anchor);
      } else {
        const container = document.querySelector(".container");
        if (container) container.appendChild(wrapper);
      }

      // ── Números animados (count-up) ───────────────────────────────────────
      panel.querySelectorAll(".ux-stat-num[data-target]").forEach(el => {
        const target = parseInt(el.dataset.target, 10);
        const duration = 900;
        const start = performance.now();
        function tick(now) {
          const t = Math.min((now - start) / duration, 1);
          const ease = 1 - Math.pow(1 - t, 3);
          el.textContent = Math.round(ease * target);
          if (t < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      });

      // ── Barras animadas (trigger después de insert) ───────────────────────
      setTimeout(() => {
        panel.querySelectorAll(".ux-cat-bar-fill[data-pct]").forEach(el => {
          el.style.width = el.dataset.pct + "%";
        });
      }, 120);

    } catch (e) {}
  }

  // ── 10. HINT MODAL IMPROVEMENTS ───────────────────────────────────────────
  function enhanceHints() {
    const modal = document.querySelector(".modal.show, #challenge-window.show, #challenge-window[style*=block]");
    if (!modal) return;

    modal.querySelectorAll(".hint-button, [data-hint-id], button[onclick*=hint]").forEach(btn => {
      if (btn.dataset.uxEnhanced) return;
      btn.dataset.uxEnhanced = "1";

      const cost = btn.dataset.cost || btn.dataset.hintCost || "0";
      const badge = document.createElement("span");
      const costNum = parseInt(cost, 10);
      if (costNum > 0) {
        badge.className = "ux-hint-cost-badge";
        badge.textContent = `-${costNum} pts`;
      } else {
        badge.className = "ux-hint-free-badge";
        badge.textContent = "gratis";
      }
      btn.appendChild(badge);
    });
  }

  // ── Inicialización ─────────────────────────────────────────────────────────

  function onModalOpen() {
    setTimeout(() => {
      initDifficultyRating();
      initWorkingOn();
      enhanceHints();
    }, 250);
  }

  function init() {
    // Features globales
    initCountdown();
    hookSolveCelebration();
    fetch("/api/v1/users/me").then(r => r.ok ? r.json() : null).then(data => {
      if (data && data.data && data.data.team_id) initTeamActivity();
    }).catch(() => {});
    pollFirstBloods();
    setInterval(pollFirstBloods, 30000);

    // Challenges page
    if (window.location.pathname === "/challenges" || window.location.pathname.startsWith("/challenges")) {
      // Esperar a que CTFd cargue los retos vía AJAX
      const waitForBoard = setInterval(() => {
        const cards = document.querySelectorAll("[data-chal-id]");
        if (cards.length > 0) {
          clearInterval(waitForBoard);
          initChallengeFilter();
          initCategoryProgress();
        }
      }, 300);
      setTimeout(() => clearInterval(waitForBoard), 10000);
    }

    // Profile page
    if (/\/users\/\d+/.test(window.location.pathname)) {
      initProfileStats();
    }

    // Hooks de modal
    document.addEventListener("shown.bs.modal", onModalOpen);
    document.addEventListener("challenge:opened", onModalOpen);

    // MutationObserver como fallback para temas que no usan Bootstrap modal events
    const bodyObs = new MutationObserver(mutations => {
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType === 1 && (
            node.id === "challenge-window" ||
            node.classList?.contains("challenge-window") ||
            node.querySelector?.("#challenge-id")
          )) {
            onModalOpen();
          }
        }
      }
    });
    bodyObs.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
