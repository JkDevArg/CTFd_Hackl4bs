(function () {
  "use strict";

  // ── Toast queue ────────────────────────────────────────────────────────────
  const _queue = [];
  let _showing = false;

  function _showNext() {
    if (_showing || !_queue.length) return;
    _showing = true;
    const a = _queue.shift();

    const toast = document.createElement("div");
    toast.className = "hl-ach-toast";
    toast.innerHTML =
      '<div class="hl-ach-toast-shine"></div>' +
      '<div class="hl-ach-toast-icon">' + a.icon + '</div>' +
      '<div class="hl-ach-toast-body">' +
        '<div class="hl-ach-toast-label">¡Logro desbloqueado!</div>' +
        '<div class="hl-ach-toast-name">' + a.name + '</div>' +
        '<div class="hl-ach-toast-desc">' + a.description + '</div>' +
      '</div>';

    document.body.appendChild(toast);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => toast.classList.add("hl-ach-toast--in"));
    });

    setTimeout(() => {
      toast.classList.remove("hl-ach-toast--in");
      toast.classList.add("hl-ach-toast--out");
      setTimeout(() => {
        toast.remove();
        _showing = false;
        _showNext();
      }, 400);
    }, 4000);
  }

  function enqueueToast(a) {
    _queue.push(a);
    _showNext();
  }

  // ── Poll for pending achievements ──────────────────────────────────────────
  function pollPending() {
    fetch("/api/hackl4bs/achievements/pending")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var list = data.new || [];
        list.forEach(function (a) { enqueueToast(a); });
      })
      .catch(function () {});
  }

  // ── Inject achievements on profile pages ───────────────────────────────────
  function injectProfileBadges(userId) {
    fetch("/api/hackl4bs/achievements/user/" + userId)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var achievements = data.achievements || [];
        var container = document.createElement("div");
        container.className = "hl-ach-profile";

        var title = document.createElement("div");
        title.className = "hl-ach-profile-title";
        title.textContent = "Logros";
        container.appendChild(title);

        var grid = document.createElement("div");
        grid.className = "hl-ach-profile-grid";

        achievements.forEach(function (a) {
          var badge = document.createElement("div");
          badge.className = "hl-ach-badge" + (a.earned ? " hl-ach-badge--earned" : " hl-ach-badge--locked");
          badge.title = a.name + " — " + a.description + (a.earned ? "\nObtenido: " + new Date(a.earned_at).toLocaleString() : "");
          badge.innerHTML =
            '<div class="hl-ach-badge-icon">' + a.icon + '</div>' +
            '<div class="hl-ach-badge-name">' + a.name + '</div>';
          grid.appendChild(badge);
        });

        container.appendChild(grid);

        // Insert after the first .card or .container > .row
        var target =
          document.querySelector(".container .row") ||
          document.querySelector("main .container") ||
          document.querySelector(".container");
        if (target) {
          target.parentNode.insertBefore(container, target.nextSibling);
        }
      })
      .catch(function () {});
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    // Profile page detection
    var profileMatch = window.location.pathname.match(/\/users\/(\d+)/);
    if (profileMatch) {
      injectProfileBadges(parseInt(profileMatch[1], 10));
    }

    // Only poll if logged in
    fetch("/api/v1/users/me")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.data && data.data.id) {
          pollPending();
          setInterval(pollPending, 30000);
        }
      })
      .catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
