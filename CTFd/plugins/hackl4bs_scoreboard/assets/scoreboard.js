(function() {
    // Matches '/' and also CTFd home aliases like '' or '/?...'
    const path = window.location.pathname;
    if (path !== '/' && path !== '') return;

    async function main() {
        try {
            const res = await fetch('/api/v1/hackl4bs/top10', { headers: { 'Accept': 'application/json' } });
            if (!res.ok) return;
            const json = await res.json();
            if (!json.success || !json.data) return;
            injectScoreboardUI(json.data);
        } catch (e) {
            console.error("[HackL4bs Scoreboard]", e);
        }
    }

    // DOMContentLoaded may already have fired when this script runs
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', main);
    } else {
        main();
    }

    function injectScoreboardUI(data) {
        const standings = data.standings || [];
        const titleText = data.title || '🏆 TOP 10 LEADERBOARD 🏆';

        const style = document.createElement('style');
        style.innerHTML = `
            :root {
                --hl-primary: #7c3aed;
                --hl-cyan:    #06b6d4;
                --hl-blood:   #e74c3c;
                --hl-fast:    #f59e0b;
                --hl-green:   #10b981;
                --hl-bg:      rgba(8, 0, 20, 0.9);
                --hl-surface: rgba(255, 255, 255, 0.03);
                --hl-border:  rgba(255, 255, 255, 0.07);
                --hl-text:    #f1f5f9;
                --hl-muted:   #64748b;
                --hl-radius:  12px;
                --hl-mono:    'JetBrains Mono', 'Courier New', monospace;
            }
            .hl-sb-container {
                max-width: 1000px;
                margin: 4rem auto;
                padding: 0 1.5rem;
                font-family: 'Inter', sans-serif;
                color: var(--hl-text);
            }
            .hl-sb-header {
                text-align: center;
                margin-bottom: 2.5rem;
            }
            .hl-sb-label {
                font-family: var(--hl-mono);
                font-size: 0.75rem;
                color: var(--hl-primary);
                letter-spacing: 0.2em;
                text-transform: uppercase;
                display: block;
                margin-bottom: 0.5rem;
            }
            .hl-sb-title {
                font-size: 2.5rem;
                font-weight: 900;
                margin: 0;
                background: linear-gradient(135deg, #fff 30%, var(--hl-primary) 70%, var(--hl-cyan) 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                letter-spacing: -0.02em;
            }
            .hl-sb-list {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
            }
            .hl-sb-item {
                position: relative;
                animation: hl-fade-in 0.4s ease backwards;
            }
            @keyframes hl-fade-in {
                from { opacity: 0; transform: translateY(10px); }
                to   { opacity: 1; transform: translateY(0); }
            }
            /* ── Card ─────────────────────────────────────────────────── */
            .hl-sb-card {
                background: var(--hl-surface);
                border: 1px solid var(--hl-border);
                border-radius: var(--hl-radius);
                padding: 1rem 1.5rem;
                display: flex;
                align-items: center;
                gap: 1.25rem;
                cursor: pointer;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                backdrop-filter: blur(12px);
                user-select: none;
            }
            .hl-sb-card:hover {
                background: rgba(255, 255, 255, 0.05);
                border-color: rgba(124, 58, 237, 0.35);
                transform: translateX(6px);
                box-shadow: 0 10px 30px -10px rgba(0,0,0,0.5);
            }
            .hl-sb-card.open {
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                border-color: rgba(124, 58, 237, 0.4);
                background: rgba(124, 58, 237, 0.06);
            }
            /* ── Rank ─────────────────────────────────────────────────── */
            .hl-sb-rank {
                width: 44px;
                height: 44px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-family: var(--hl-mono);
                font-size: 1.1rem;
                font-weight: 800;
                color: var(--hl-muted);
                flex-shrink: 0;
            }
            .hl-sb-rank.top-rank { font-size: 1.6rem; }
            .hl-sb-rank svg { width: 28px; height: 28px; fill: currentColor; filter: drop-shadow(0 0 6px currentColor); }
            .rank-1 { color: #f59e0b; }
            .rank-2 { color: #94a3b8; }
            .rank-3 { color: #b45309; }
            /* ── Name + mini stats ────────────────────────────────────── */
            .hl-sb-info { flex-grow: 1; min-width: 0; }
            .hl-sb-name {
                font-size: 1.1rem;
                font-weight: 700;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .hl-sb-badges {
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                margin-top: 5px;
            }
            .hl-badge {
                font-family: var(--hl-mono);
                font-size: 0.68rem;
                font-weight: 700;
                padding: 2px 8px;
                border-radius: 20px;
                display: inline-flex;
                align-items: center;
                gap: 4px;
                white-space: nowrap;
            }
            .hl-badge-solves {
                background: rgba(6, 182, 212, 0.12);
                border: 1px solid rgba(6, 182, 212, 0.35);
                color: var(--hl-cyan);
            }
            .hl-badge-blood {
                background: rgba(231, 76, 60, 0.12);
                border: 1px solid rgba(231, 76, 60, 0.35);
                color: var(--hl-blood);
            }
            .hl-badge-fast {
                background: rgba(245, 158, 11, 0.12);
                border: 1px solid rgba(245, 158, 11, 0.35);
                color: var(--hl-fast);
            }
            /* ── Score ────────────────────────────────────────────────── */
            .hl-sb-score {
                font-family: var(--hl-mono);
                font-size: 1.2rem;
                font-weight: 700;
                color: var(--hl-cyan);
                text-align: right;
                flex-shrink: 0;
            }
            .hl-sb-score small {
                font-size: 0.7rem;
                opacity: 0.55;
                margin-left: 2px;
            }
            .hl-sb-chevron {
                font-size: 0.85rem;
                color: var(--hl-muted);
                transition: transform 0.25s;
                flex-shrink: 0;
            }
            .hl-sb-card.open .hl-sb-chevron { transform: rotate(180deg); }
            /* ── Details panel ────────────────────────────────────────── */
            .hl-sb-details {
                max-height: 0;
                overflow: hidden;
                opacity: 0;
                background: rgba(13, 17, 23, 0.5);
                border: 1px solid rgba(124, 58, 237, 0.2);
                border-top: none;
                border-radius: 0 0 var(--hl-radius) var(--hl-radius);
                margin: 0 0 0.75rem 0;
                padding: 0 1.5rem;
                transition: max-height 0.32s cubic-bezier(0.4,0,0.2,1), opacity 0.25s ease, padding 0.25s;
                backdrop-filter: blur(8px);
            }
            .hl-sb-details.active {
                max-height: 600px;
                opacity: 1;
                padding: 1.25rem 1.5rem 1.5rem;
            }
            /* ── Stats summary row ────────────────────────────────────── */
            .hl-sb-stat-row {
                display: flex;
                gap: 1rem;
                margin-bottom: 1.25rem;
                flex-wrap: wrap;
            }
            .hl-sb-stat-box {
                flex: 1;
                min-width: 90px;
                background: rgba(255,255,255,0.03);
                border: 1px solid var(--hl-border);
                border-radius: 8px;
                padding: 0.75rem 1rem;
                text-align: center;
            }
            .hl-sb-stat-num {
                font-family: var(--hl-mono);
                font-size: 1.6rem;
                font-weight: 800;
                line-height: 1;
            }
            .hl-sb-stat-lbl {
                font-family: var(--hl-mono);
                font-size: 0.65rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: var(--hl-muted);
                margin-top: 4px;
            }
            .stat-solves .hl-sb-stat-num { color: var(--hl-cyan); }
            .stat-blood  .hl-sb-stat-num { color: var(--hl-blood); }
            .stat-fast   .hl-sb-stat-num { color: var(--hl-fast); }
            /* ── Members grid ─────────────────────────────────────────── */
            .hl-sb-members-title {
                font-family: var(--hl-mono);
                font-size: 0.7rem;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                color: var(--hl-muted);
                margin-bottom: 0.75rem;
            }
            .hl-sb-member-list {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
                gap: 0.75rem;
            }
            .hl-sb-member {
                background: rgba(255,255,255,0.03);
                border: 1px solid var(--hl-border);
                border-radius: 8px;
                padding: 0.65rem 1rem;
                display: flex;
                flex-direction: column;
                gap: 4px;
            }
            .hl-sb-m-name {
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--hl-text);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .hl-sb-m-meta {
                font-family: var(--hl-mono);
                font-size: 0.72rem;
                color: var(--hl-muted);
                display: flex;
                gap: 10px;
            }
            .hl-sb-m-meta .pts  { color: var(--hl-primary); font-weight: 700; }
            .hl-sb-m-meta .slvs { color: var(--hl-cyan); }
        `;
        document.head.appendChild(style);

        const target = document.querySelector('main') || document.body;
        const container = document.createElement('section');
        container.className = 'hl-sb-container';

        container.innerHTML = `
            <div class="hl-sb-header">
                <span class="hl-sb-label">&gt; Ranking</span>
                <h2 class="hl-sb-title">${titleText}</h2>
            </div>
            <div class="hl-sb-list"></div>
        `;

        const list = container.querySelector('.hl-sb-list');

        if (standings.length === 0) {
            list.innerHTML = `
                <div style="text-align:center;padding:2.5rem 1rem;font-family:var(--hl-mono);color:var(--hl-muted);font-size:0.85rem;">
                    Aún no hay equipos con puntos.<br>
                    <span style="font-size:0.75rem;opacity:0.6;">El ranking aparecerá cuando se resuelva el primer reto.</span>
                </div>`;
        }

        standings.forEach((s, idx) => {
            const item = document.createElement('div');
            item.className = 'hl-sb-item';
            item.style.animationDelay = `${idx * 0.05}s`;

            // ── Rank icon ──────────────────────────────────────────────
            let rankClass = 'hl-sb-rank';
            let rankHTML  = `#${s.rank}`;
            if (s.rank <= 3) {
                rankClass += ` top-rank rank-${s.rank}`;
                rankHTML = `<svg viewBox="0 0 24 24"><path d="M18,2H6V4H18V2M18,7V4H6V7C6,8.1 6.9,9 8,9H16C17.1,9 18,8.1 18,7M16,11V9H8V11C8,12.1 8.9,13 10,13H14C15.1,13 16,12.1 16,11M12,15C10.3,15 9,13.7 9,12H15C15,13.7 13.7,15 12,15M17,17V15H7V17L12,22L17,17Z"/></svg>`;
            }

            // ── Mini badges ────────────────────────────────────────────
            const badgesHTML = `
                <span class="hl-badge hl-badge-solves">⚡ ${s.solve_count ?? 0} retos</span>
                ${s.first_blood > 0 ? `<span class="hl-badge hl-badge-blood">🩸 ${s.first_blood} first blood</span>` : ''}
                ${s.fast_solve  > 0 ? `<span class="hl-badge hl-badge-fast">⚡ ${s.fast_solve} fast solve</span>`  : ''}
            `;

            // ── Card ───────────────────────────────────────────────────
            const card = document.createElement('div');
            card.className = 'hl-sb-card';
            card.innerHTML = `
                <div class="${rankClass}">${rankHTML}</div>
                <div class="hl-sb-info">
                    <div class="hl-sb-name">${escHtml(s.name)}</div>
                    <div class="hl-sb-badges">${badgesHTML}</div>
                </div>
                <div class="hl-sb-score">${s.score.toLocaleString()}<small>pts</small></div>
                <span class="hl-sb-chevron">▼</span>
            `;

            // ── Details panel ──────────────────────────────────────────
            const details = document.createElement('div');
            details.className = 'hl-sb-details';

            const memberRows = (s.members || []).map(m => `
                <div class="hl-sb-member">
                    <span class="hl-sb-m-name">${escHtml(m.name)}</span>
                    <div class="hl-sb-m-meta">
                        <span class="pts">${m.score.toLocaleString()} pts</span>
                        <span class="slvs">${m.solves} solve${m.solves !== 1 ? 's' : ''}</span>
                    </div>
                </div>
            `).join('');

            details.innerHTML = `
                <div class="hl-sb-stat-row">
                    <div class="hl-sb-stat-box stat-solves">
                        <div class="hl-sb-stat-num">${s.solve_count ?? 0}</div>
                        <div class="hl-sb-stat-lbl">Retos resueltos</div>
                    </div>
                    <div class="hl-sb-stat-box stat-blood">
                        <div class="hl-sb-stat-num">${s.first_blood ?? 0}</div>
                        <div class="hl-sb-stat-lbl">First Bloods</div>
                    </div>
                    <div class="hl-sb-stat-box stat-fast">
                        <div class="hl-sb-stat-num">${s.fast_solve ?? 0}</div>
                        <div class="hl-sb-stat-lbl">Fast Solves</div>
                    </div>
                    <div class="hl-sb-stat-box">
                        <div class="hl-sb-stat-num" style="color:var(--hl-cyan)">${s.score.toLocaleString()}</div>
                        <div class="hl-sb-stat-lbl">Puntos totales</div>
                    </div>
                </div>
                <div class="hl-sb-members-title">Miembros del equipo</div>
                <div class="hl-sb-member-list">
                    ${memberRows || '<div style="color:var(--hl-muted);font-size:.8rem">Sin miembros</div>'}
                </div>
            `;

            // ── Toggle ─────────────────────────────────────────────────
            card.addEventListener('click', () => {
                const isOpen = details.classList.contains('active');
                document.querySelectorAll('.hl-sb-details.active').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.hl-sb-card.open').forEach(el => el.classList.remove('open'));
                if (!isOpen) {
                    details.classList.add('active');
                    card.classList.add('open');
                }
            });

            item.appendChild(card);
            item.appendChild(details);
            list.appendChild(item);
        });

        // Avoid double-inject on hot reload
        if (document.getElementById('hl-scoreboard-root')) return;
        container.id = 'hl-scoreboard-root';

        // CTFd home: try jumbotron → main → body
        const jumbotron = document.querySelector('.jumbotron');
        const hero      = document.querySelector('.hl-hero');
        if (hero)       hero.after(container);
        else if (jumbotron) jumbotron.after(container);
        else            target.prepend(container);
    }

    function escHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
})();
