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
        ${[1,2,3,4,5].map(i => `<span class="ux-star locked" data-val="${i}">★</span>`).join("")}
      </div>
      <div class="ux-rating-avg"></div>
      <div class="ux-rating-locked-msg">🔒 Resuelve este reto para valorarlo</div>`;

    const stars  = block.querySelectorAll(".ux-star");
    const avgEl  = block.querySelector(".ux-rating-avg");
    const lockEl = block.querySelector(".ux-rating-locked-msg");
    let solved = false;

    function setStars(val) {
      stars.forEach(s => s.classList.toggle("active", parseInt(s.dataset.val) <= val));
    }

    function unlock() {
      stars.forEach(s => s.classList.remove("locked"));
      lockEl.style.display = "none";
    }

    async function loadRating() {
      try {
        const d = await apiFetch(`${API}/ratings/${chalId}`);
        solved = !!d.solved;
        if (solved) unlock();
        if (d.my_rating) setStars(d.my_rating);
        if (d.average !== null) {
          avgEl.textContent = `Promedio: ${d.average}★ (${d.count} votos)`;
        } else {
          avgEl.textContent = d.count ? "" : "Sin votos aún";
        }
      } catch (e) {}
    }

    stars.forEach(star => {
      star.addEventListener("mouseover", () => { if (solved) setStars(parseInt(star.dataset.val)); });
      star.addEventListener("mouseleave", () => { if (solved) loadRating(); });
      star.addEventListener("click", async () => {
        if (!solved) return;
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

    // Desbloquear si se resuelve el reto sin cerrar el modal
    const solveObs = new MutationObserver(() => {
      if (!solved && modal.querySelector(".alert-success")) loadRating();
    });
    solveObs.observe(modal, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
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

  function buildHeatmap(timeline) {
    const countMap = {};
    timeline.forEach(({date, count}) => { countMap[date] = count; });

    const now = new Date();
    const start = new Date(now);
    start.setDate(start.getDate() - 364);
    start.setDate(start.getDate() - start.getDay()); // align to Sunday

    const level = n => n === 0 ? 0 : n === 1 ? 1 : n <= 3 ? 2 : n <= 6 ? 3 : 4;
    const months = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];

    const wrap = document.createElement("div");
    wrap.className = "ux-heatmap-wrap";

    const monthRow = document.createElement("div");
    monthRow.className = "ux-heatmap-months";

    const grid = document.createElement("div");
    grid.className = "ux-heatmap-grid";

    let currentMonth = -1;
    let colIdx = 0;
    const cursor = new Date(start);

    while (cursor <= now) {
      const col = document.createElement("div");
      col.className = "ux-heatmap-col";

      for (let dow = 0; dow < 7; dow++) {
        const d = new Date(cursor);
        d.setDate(d.getDate() + dow);
        const dateStr = d.toISOString().slice(0, 10);
        const count = countMap[dateStr] || 0;
        const cell = document.createElement("div");
        cell.className = `ux-heatmap-cell ux-heatmap-l${level(count)}`;
        cell.title = `${dateStr}: ${count} solve${count !== 1 ? "s" : ""}`;
        if (d > now) cell.classList.add("ux-heatmap-future");
        col.appendChild(cell);
      }

      if (cursor.getMonth() !== currentMonth) {
        currentMonth = cursor.getMonth();
        const lbl = document.createElement("span");
        lbl.textContent = months[currentMonth];
        lbl.style.cssText = `grid-column:${colIdx + 1};font-size:9px;color:var(--ux-muted);`;
        monthRow.appendChild(lbl);
      }

      grid.appendChild(col);
      cursor.setDate(cursor.getDate() + 7);
      colIdx++;
    }

    wrap.appendChild(monthRow);
    wrap.appendChild(grid);
    return wrap;
  }

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

      // ── Heatmap de actividad ──────────────────────────────────────────────
      if ((data.timeline || []).length) {
        const timeSection = document.createElement("div");
        timeSection.innerHTML = `<div class="ux-section-label">actividad (52 semanas)</div>`;
        timeSection.appendChild(buildHeatmap(data.timeline));
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

  // ── 8. TEAM PANEL (página /teams/N) ──────────────────────────────────────
  async function initTeamPanel() {
    const match = window.location.pathname.match(/\/teams\/(\d+)/);
    if (!match) return;
    const teamId = match[1];
    if (document.getElementById("ux-team-panel")) return;

    try {
      const data = await apiFetch(`${API}/team-stats/${teamId}`);
      if (!data.total_solves && !(data.members && data.members.length)) return;

      const panel = document.createElement("div");
      panel.id = "ux-team-panel";

      const totalMemberPts = data.members.reduce((s, m) => s + m.points, 0) || 1;
      const memberBars = data.members
        .sort((a, b) => b.points - a.points)
        .map(m => {
          const pct = Math.round((m.points / totalMemberPts) * 100);
          return `
            <div class="ux-team-member-row">
              <a href="/users/${m.user_id}" class="ux-team-member-name">${m.username}</a>
              <div class="ux-team-member-bar-track">
                <div class="ux-team-member-bar-fill" data-pct="${pct}"></div>
              </div>
              <span class="ux-team-member-pts">${m.points}pts · ${m.solves}✓</span>
            </div>`;
        }).join("");

      const catPills = Object.entries(data.by_category || {})
        .sort((a, b) => b[1] - a[1])
        .map(([cat, n]) => `<span class="ux-team-cat-pill">${cat} <b>${n}</b></span>`)
        .join("");

      const recentRows = (data.recent || []).map(s => `
        <div class="ux-team-solve-row">
          <span class="ux-team-solve-who">${s.username}</span>
          <span class="ux-team-solve-chal">${s.challenge}</span>
          <span class="ux-team-solve-cat">${s.category}</span>
          <span class="ux-team-solve-pts">+${s.points}</span>
          <span class="ux-team-solve-time">${timeAgo(s.date)}</span>
        </div>`).join("");

      panel.innerHTML = `
        <div class="ux-team-panel-header">
          <span class="ux-team-panel-title">⚡ Team Dashboard</span>
        </div>
        <div class="ux-team-stat-grid">
          <div class="ux-team-stat"><div class="ux-team-stat-num" data-target="${data.total_points}">0</div><div class="ux-team-stat-lbl">Puntos</div></div>
          <div class="ux-team-stat"><div class="ux-team-stat-num" data-target="${data.total_solves}">0</div><div class="ux-team-stat-lbl">Solves</div></div>
          <div class="ux-team-stat"><div class="ux-team-stat-num" data-target="${data.first_blood}">0</div><div class="ux-team-stat-lbl">First Bloods</div></div>
          <div class="ux-team-stat"><div class="ux-team-stat-num" data-target="${data.completed_categories}">0</div><div class="ux-team-stat-lbl">Cats Completas</div></div>
        </div>
        <div class="ux-section-label">contribución por miembro</div>
        <div class="ux-team-members">${memberBars}</div>
        ${catPills ? `<div class="ux-section-label">categorías</div><div class="ux-team-cat-pills">${catPills}</div>` : ""}
        ${recentRows ? `<div class="ux-section-label">últimas soluciones</div><div class="ux-team-solves">${recentRows}</div>` : ""}
      `;

      const anchor =
        document.querySelector("#solves-row, #keys-row, table") ||
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

      panel.querySelectorAll(".ux-team-stat-num[data-target]").forEach(el => {
        const target = parseInt(el.dataset.target, 10);
        const duration = 900;
        const start = performance.now();
        function tick(now) {
          const t = Math.min((now - start) / duration, 1);
          el.textContent = Math.round((1 - Math.pow(1 - t, 3)) * target);
          if (t < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      });

      setTimeout(() => {
        panel.querySelectorAll(".ux-team-member-bar-fill[data-pct]").forEach(el => {
          el.style.width = el.dataset.pct + "%";
        });
      }, 120);

    } catch (e) {}
  }

  // ── 9. TEAM NOTES SCRATCHPAD ──────────────────────────────────────────────
  function initTeamNotes() {
    let _saveTimer = null;
    let _lastContent = null;

    const btn = document.createElement("div");
    btn.id = "ux-notes-btn";
    btn.title = "Notas del equipo";
    btn.textContent = "📝";
    document.body.appendChild(btn);
    btn.style.display = "none";

    const widget = document.createElement("div");
    widget.id = "ux-notes-widget";
    widget.innerHTML = `
      <div class="ux-notes-header">
        <span>📝 Notas del equipo</span>
        <span id="ux-notes-close" style="cursor:pointer;color:var(--ux-muted)">✕</span>
      </div>
      <div id="ux-notes-meta"></div>
      <textarea id="ux-notes-area" placeholder="Notas compartidas del equipo...&#10;&#10;Auto-guardado cuando dejas de escribir."></textarea>
      <div id="ux-notes-status"></div>`;
    document.body.appendChild(widget);

    btn.addEventListener("click", () => {
      widget.classList.toggle("open");
      if (widget.classList.contains("open")) loadNotes();
    });
    document.getElementById("ux-notes-close").addEventListener("click", () =>
      widget.classList.remove("open")
    );

    const area   = document.getElementById("ux-notes-area");
    const meta   = document.getElementById("ux-notes-meta");
    const status = document.getElementById("ux-notes-status");

    async function loadNotes() {
      try {
        const d = await apiFetch(`${API}/team-notes`);
        if (_lastContent === null || (d.content !== _lastContent && document.activeElement !== area)) {
          area.value = d.content || "";
          _lastContent = area.value;
        }
        if (d.updated_at && d.updated_by) {
          meta.textContent = `Última edición: ${d.updated_by} · ${timeAgo(d.updated_at)}`;
        }
      } catch (e) {}
    }

    area.addEventListener("input", () => {
      status.textContent = "Guardando...";
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(async () => {
        try {
          await apiFetch(`${API}/team-notes`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({content: area.value}),
          });
          _lastContent = area.value;
          status.textContent = "✓ Guardado";
          setTimeout(() => { status.textContent = ""; }, 2000);
        } catch (e) {
          status.textContent = "⚠ Error al guardar";
        }
      }, 2500);
    });

    setInterval(() => {
      if (widget.classList.contains("open")) loadNotes();
    }, 20000);

    async function updateNotesVisibility() {
      try {
        const resp = await fetch("/api/whaley/instances");
        if (!resp.ok) return;
        const d = await resp.json();
        const active = (d.instances || []).length > 0;
        btn.style.display = active ? "" : "none";
        if (!active) widget.classList.remove("open");
      } catch (e) {}
    }
    updateNotesVisibility();
    document.addEventListener("whaley:instancesChanged", updateNotesVisibility);
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
      if (data && data.data && data.data.team_id) {
        initTeamActivity();
        initTeamNotes();
      }
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

    // Team page
    if (/\/teams\/\d+/.test(window.location.pathname)) {
      initTeamPanel();
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
