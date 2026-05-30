/**
 * HackL4bs — Professional Dark Theme
 * Floating particles background, boot sequence, nav effects
 */
(function () {
  "use strict";

  /* ── Floating particles (login background) ───────────────────────────── */
  function initParticles(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    function resize() {
      canvas.width  = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", () => { resize(); resetParticles(); });

    const COUNT = 55;
    const BLUE = "68, 147, 248";
    let particles = [];

    function resetParticles() {
      particles = Array.from({ length: COUNT }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 1.5 + 0.4,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        a: Math.random() * 0.35 + 0.05,
      }));
    }
    resetParticles();

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Draw connections
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 130) {
            const alpha = (1 - dist / 130) * 0.12;
            ctx.beginPath();
            ctx.strokeStyle = `rgba(${BLUE}, ${alpha})`;
            ctx.lineWidth = 0.6;
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.stroke();
          }
        }
      }

      // Draw dots
      for (const p of particles) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${BLUE}, ${p.a})`;
        ctx.fill();

        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > canvas.width)  p.vx *= -1;
        if (p.y < 0 || p.y > canvas.height) p.vy *= -1;
      }

      requestAnimationFrame(draw);
    }

    draw();
  }

  /* ── Boot sequence typing ────────────────────────────────────────────── */
  function initBootSequence() {
    const el = document.getElementById("hl-boot-seq");
    if (!el) return;

    const lines = el.querySelectorAll("[data-boot-line]");
    lines.forEach((line, i) => {
      const text = line.getAttribute("data-boot-line");
      line.textContent = "";
      const delay = i * 260 + 100;

      setTimeout(() => {
        let idx = 0;
        const interval = setInterval(() => {
          line.textContent += text[idx++];
          if (idx >= text.length) clearInterval(interval);
        }, 16);
      }, delay);
    });
  }

  /* ── Navbar: replace >_ prefix with a status dot ────────────────────── */
  function initNavbarBrand() {
    const brand = document.querySelector(".navbar-brand");
    if (!brand || brand.dataset.hlInit) return;
    brand.dataset.hlInit = "1";

    if (!brand.querySelector(".hl-brand-dot")) {
      const dot = document.createElement("span");
      dot.className = "hl-brand-dot";
      brand.insertBefore(dot, brand.firstChild);
    }
  }

  /* ── Highlight active nav link ───────────────────────────────────────── */
  function highlightNav() {
    const path = window.location.pathname;
    document.querySelectorAll(".nav-link[href]").forEach(link => {
      if (link.getAttribute("href") === path) link.classList.add("active");
    });
  }

  /* ── Smooth fade-in for main content ─────────────────────────────────── */
  function initFadeIn() {
    const main = document.querySelector("main");
    if (main) {
      main.style.opacity = "0";
      main.style.transition = "opacity 0.35s ease";
      requestAnimationFrame(() => {
        main.style.opacity = "1";
      });
      main.addEventListener("transitionend", function clear() {
        main.style.transition = "";
        main.removeEventListener("transitionend", clear);
      }, { once: true });
    }
  }

  /* ── Focus terminal inputs ───────────────────────────────────────────── */
  function initFormFocus() {
    document.querySelectorAll(".hl-input").forEach(input => {
      input.addEventListener("focus",  () => input.closest(".hl-field")?.classList.add("active"));
      input.addEventListener("blur",   () => input.closest(".hl-field")?.classList.remove("active"));
    });
  }

  /* ── Boot ────────────────────────────────────────────────────────────── */
  function boot() {
    initParticles("hl-matrix-canvas");
    initBootSequence();
    initNavbarBrand();
    highlightNav();
    initFadeIn();
    initFormFocus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
